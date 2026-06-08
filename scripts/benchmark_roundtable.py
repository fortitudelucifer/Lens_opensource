"""
Day 4 · D4.6 · Roundtable 并发 / 首 token 延迟 benchmark

两种模式：

  (a) **mock backend**（默认 · D4.6）
      - SLO · p95 首 token 延迟 ≤ 3s（pipeline 本身开销基线）
      - 规避真 LLM 的抖动与 key quota · 关注 scheduling / GuardedEmitter
        flush / SSE queue 吞吐
      - ROUNDTABLE_USE_LLM=0 · ROUNDTABLE_BACKEND=mock

  (b) **real LLM**（Day 7 · D7.1.c · --real-llm 启用）
      - SLO · p95 首 token 延迟 ≤ 6s（放宽 · 真 LLM 首 token 固有延迟）
      - 加载 local_secrets/.env.advisor · 让 get_generator 能拿到 key
      - 强制 ROUNDTABLE_USE_LLM=1 · ROUNDTABLE_BACKEND=<--backend>
      - ⚠️  会消耗真实 API 配额 · 推荐 runs=10 concurrency=1 起步

运行：
  # mock（默认 · CI 基线）
  conda run -n wechatDHA python scripts/benchmark_roundtable.py --runs 20 --concurrency 1

  # real LLM（D7.1.c · 2026-04-30 代理生态下只有 claude 可用）
  conda run -n wechatDHA python scripts/benchmark_roundtable.py \\
      --real-llm --backend claude --runs 10 --concurrency 1
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# ─────────────────────────────────────────────────────────────
# backend 模式选择（CLI parse 前先检测 flag · 决定是否 load env）
# ─────────────────────────────────────────────────────────────
_REAL_LLM = "--real-llm" in sys.argv
_BACKEND_ARG: Optional[str] = None
for _i, _a in enumerate(sys.argv):
    if _a == "--backend" and _i + 1 < len(sys.argv):
        _BACKEND_ARG = sys.argv[_i + 1]
        break

if _REAL_LLM:
    # 加载 .env.advisor · 让 get_generator 能拿到 API key / base_url / model
    _ENV_FILE = PROJECT_ROOT / "local_secrets" / ".env.advisor"
    if _ENV_FILE.exists():
        for _line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
            _line = _line.strip()
            if not _line or _line.startswith("#"):
                continue
            if _line.startswith("export "):
                _line = _line[len("export "):]
            if "=" not in _line:
                continue
            _k, _, _v = _line.partition("=")
            _v = _v.strip().strip('"').strip("'")
            os.environ.setdefault(_k.strip(), _v)
    os.environ["ROUNDTABLE_USE_LLM"] = "1"
    os.environ["ROUNDTABLE_MODERATOR_LLM"] = "1"
    if _BACKEND_ARG:
        os.environ["ROUNDTABLE_BACKEND"] = _BACKEND_ARG
    # 真 LLM 下 3-phase 完整流程预估 40-50s · total timeout 放宽到 120s
    os.environ.setdefault("ROUNDTABLE_BENCH_FIRST_TOKEN_TIMEOUT", "20.0")
    os.environ.setdefault("ROUNDTABLE_BENCH_TOTAL_TIMEOUT", "120.0")
else:
    # 强制 mock 路径：
    #   - ROUNDTABLE_USE_LLM=0 → _stream_one_agent 跳过 LLM 直接走 _generate_mock_text
    #   - ROUNDTABLE_MODERATOR_LLM=0 → Moderator 用规则 fallback
    # 避免测到 LLM 401 + 回退的"假延迟"，聚焦 pipeline 开销
    os.environ.setdefault("ROUNDTABLE_USE_LLM", "0")
    os.environ.setdefault("ROUNDTABLE_MODERATOR_LLM", "0")
    os.environ.setdefault("ROUNDTABLE_BACKEND", "mock")

from scripts.advisor.api.services import roundtable_service as rs  # noqa: E402

# SLO 默认值 · 真 LLM 模式放宽到 6s（对齐 Section 75.4 建议）
_DEFAULT_SLO_P95 = "6.0" if _REAL_LLM else "3.0"
SLO_P95_FIRST_TOKEN = float(os.environ.get("ROUNDTABLE_SLO_P95", _DEFAULT_SLO_P95))
DEFAULT_PERSONAS = ["neutral", "supportive", "eft"]
DEFAULT_QUESTION = "我们最近经常吵架，我不知道是该沟通还是先冷静，请大家给建议。"


# ─────────────────────────────────────────────────────────────
# 数据结构
# ─────────────────────────────────────────────────────────────


@dataclass
class RunMetrics:
    run_id: int
    first_agent_chunk_s: Optional[float] = None
    first_phase_banner_s: Optional[float] = None
    session_done_s: Optional[float] = None
    agent_chunk_count: int = 0
    error: Optional[str] = None


@dataclass
class Summary:
    runs: int
    concurrency: int
    personas: list[str]
    question: str
    backend: str
    first_token_p50: float
    first_token_p95: float
    first_token_p99: float
    first_token_mean: float
    session_done_p50: float
    session_done_p95: float
    session_done_p99: float
    session_done_mean: float
    slo_p95_budget_s: float
    slo_ok: bool
    started_at: str
    finished_at: str
    per_run: list[RunMetrics] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────
# 工具
# ─────────────────────────────────────────────────────────────


def _percentile(values: list[float], pct: float) -> float:
    """线性插值 percentile · 与 numpy.percentile 接近"""
    if not values:
        return float("nan")
    xs = sorted(values)
    k = (len(xs) - 1) * pct / 100.0
    lo = math.floor(k)
    hi = math.ceil(k)
    if lo == hi:
        return xs[int(k)]
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def _stats_block(values: list[float]) -> tuple[float, float, float, float]:
    if not values:
        return (float("nan"),) * 4
    return (
        _percentile(values, 50),
        _percentile(values, 95),
        _percentile(values, 99),
        statistics.mean(values),
    )


# ─────────────────────────────────────────────────────────────
# 单次 session 跑 · 订阅到 session_done
# ─────────────────────────────────────────────────────────────


async def _run_single_session(
    run_id: int,
    personas: list[str],
    question: str,
    *,
    first_token_timeout_s: float = float(os.environ.get("ROUNDTABLE_BENCH_FIRST_TOKEN_TIMEOUT", "15.0")),
    total_timeout_s: float = float(os.environ.get("ROUNDTABLE_BENCH_TOTAL_TIMEOUT", "60.0")),
) -> RunMetrics:
    """创建一个 roundtable session · 订阅 SSE · 测量关键时间点

    测的时间点：
      - first_agent_chunk_s      · 订阅后首次收到 agent_chunk（= 首 token 感知）
      - first_phase_banner_s     · phase='phase1' 开始（pipeline 启动点）
      - session_done_s           · 收到 type=done（整个 3-phase 跑完）
    """
    metrics = RunMetrics(run_id=run_id)
    try:
        session = rs.create_session(personas=list(personas), question=question)
    except Exception as exc:
        metrics.error = f"create_session failed: {type(exc).__name__}: {exc}"
        return metrics

    start = time.perf_counter()
    try:
        async def _consume():
            async for ev in rs.subscribe(session.id):
                now = time.perf_counter() - start
                typ = ev.get("type")
                if typ == "agent_chunk" and metrics.first_agent_chunk_s is None:
                    metrics.first_agent_chunk_s = now
                if typ == "phase" and metrics.first_phase_banner_s is None:
                    metrics.first_phase_banner_s = now
                if typ == "agent_chunk":
                    metrics.agent_chunk_count += 1
                if typ == "done":
                    metrics.session_done_s = now
                    return
                # 断路器：如果 first_token 超时都还没来，直接结束
                if (metrics.first_agent_chunk_s is None
                        and now > first_token_timeout_s):
                    metrics.error = f"first_token_timeout_{first_token_timeout_s}s"
                    return

        await asyncio.wait_for(_consume(), timeout=total_timeout_s)
    except asyncio.TimeoutError:
        metrics.error = metrics.error or f"total_timeout_{total_timeout_s}s"
    except Exception as exc:
        metrics.error = f"subscribe crash: {type(exc).__name__}: {exc}"
    finally:
        # 清理 pipeline 资源（task + queue）· 防止后续 run 污染
        task = rs._tasks.pop(session.id, None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except BaseException:
                pass
        rs._queues.pop(session.id, None)
        rs._subscribed.pop(session.id, None)
        rs._sessions.pop(session.id, None)

    return metrics


# ─────────────────────────────────────────────────────────────
# 主流程
# ─────────────────────────────────────────────────────────────


async def _bench(
    runs: int,
    concurrency: int,
    personas: list[str],
    question: str,
) -> Summary:
    started_at = datetime.now().isoformat(timespec="seconds")
    sem = asyncio.Semaphore(concurrency)

    async def _one(i: int) -> RunMetrics:
        async with sem:
            return await _run_single_session(i, personas, question)

    per_run: list[RunMetrics] = await asyncio.gather(*[_one(i) for i in range(runs)])

    first_tokens = [r.first_agent_chunk_s for r in per_run if r.first_agent_chunk_s is not None]
    session_dones = [r.session_done_s for r in per_run if r.session_done_s is not None]

    ft_p50, ft_p95, ft_p99, ft_mean = _stats_block(first_tokens)
    sd_p50, sd_p95, sd_p99, sd_mean = _stats_block(session_dones)

    finished_at = datetime.now().isoformat(timespec="seconds")

    slo_ok = (not math.isnan(ft_p95)) and ft_p95 <= SLO_P95_FIRST_TOKEN

    return Summary(
        runs=runs,
        concurrency=concurrency,
        personas=personas,
        question=question,
        backend=os.environ.get("ROUNDTABLE_BACKEND", "mock"),
        first_token_p50=ft_p50,
        first_token_p95=ft_p95,
        first_token_p99=ft_p99,
        first_token_mean=ft_mean,
        session_done_p50=sd_p50,
        session_done_p95=sd_p95,
        session_done_p99=sd_p99,
        session_done_mean=sd_mean,
        slo_p95_budget_s=SLO_P95_FIRST_TOKEN,
        slo_ok=slo_ok,
        started_at=started_at,
        finished_at=finished_at,
        per_run=per_run,
    )


# ─────────────────────────────────────────────────────────────
# 输出
# ─────────────────────────────────────────────────────────────


def _fmt_ms(v: float) -> str:
    if math.isnan(v):
        return "    n/a"
    return f"{v * 1000:7.1f} ms"


def _print_summary(s: Summary) -> None:
    print("═" * 72)
    print(f"Roundtable Benchmark · backend={s.backend} runs={s.runs} concurrency={s.concurrency}")
    print(f"  question: {s.question[:60]}…")
    print(f"  personas: {', '.join(s.personas)}")
    print("─" * 72)
    ok_runs = sum(1 for r in s.per_run if r.error is None)
    err_runs = s.runs - ok_runs
    print(f"  OK runs   : {ok_runs}/{s.runs}")
    if err_runs:
        print(f"  Errors    : {err_runs}")
        for r in s.per_run:
            if r.error:
                print(f"    run#{r.run_id:02d}: {r.error}")
    print("─" * 72)
    print("  First token (agent_chunk → 首 token 感知)")
    print(f"    p50 = {_fmt_ms(s.first_token_p50)}")
    print(f"    p95 = {_fmt_ms(s.first_token_p95)}    SLO ≤ {s.slo_p95_budget_s * 1000:.0f} ms  "
          f"{'✓ PASS' if s.slo_ok else '✗ FAIL'}")
    print(f"    p99 = {_fmt_ms(s.first_token_p99)}")
    print(f"    avg = {_fmt_ms(s.first_token_mean)}")
    print("  Session done (全 3-phase 完成)")
    print(f"    p50 = {_fmt_ms(s.session_done_p50)}")
    print(f"    p95 = {_fmt_ms(s.session_done_p95)}")
    print(f"    p99 = {_fmt_ms(s.session_done_p99)}")
    print(f"    avg = {_fmt_ms(s.session_done_mean)}")
    print("═" * 72)


def _save_json(s: Summary, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = out_dir / f"roundtable_latency_c{s.concurrency}_{ts}.json"
    payload = asdict(s)
    # 转 per_run RunMetrics -> dict（asdict 已处理）
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path


# ─────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Roundtable latency benchmark (D4.6 / D7.1.c)")
    ap.add_argument("--runs", type=int, default=20, help="总 run 次数（默认 20 · 真 LLM 建议 10）")
    ap.add_argument("--concurrency", type=int, default=1, help="并发 session 数")
    ap.add_argument("--personas", nargs="+", default=DEFAULT_PERSONAS)
    ap.add_argument("--question", default=DEFAULT_QUESTION)
    ap.add_argument(
        "--out-dir",
        default=str(PROJECT_ROOT / "advisor_out" / "benchmarks"),
        help="JSON 结果保存目录",
    )
    ap.add_argument("--no-save", action="store_true", help="不写 JSON 文件")
    # D7.1.c · 真 LLM 模式（文件顶部已基于 sys.argv 处理 env · 此处仅用于 argparse help）
    ap.add_argument(
        "--real-llm",
        action="store_true",
        help="启用真 LLM · 加载 local_secrets/.env.advisor · 默认 SLO 放宽到 6s",
    )
    ap.add_argument(
        "--backend",
        type=str,
        default=None,
        help="真 LLM 模式的 backend 名（claude/openai/gemini/kimi/grok/deepseek/...）· 写入 ROUNDTABLE_BACKEND",
    )
    return ap.parse_args()


def main() -> int:
    args = _parse_args()
    summary = asyncio.run(_bench(
        runs=args.runs,
        concurrency=args.concurrency,
        personas=list(args.personas),
        question=args.question,
    ))
    _print_summary(summary)
    if not args.no_save:
        path = _save_json(summary, Path(args.out_dir))
        print(f"→ saved: {path}")
    return 0 if summary.slo_ok else 1


if __name__ == "__main__":
    sys.exit(main())
