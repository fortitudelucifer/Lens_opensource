#!/usr/bin/env python3
"""D7.4.c · Roundtable Beta 观测 Dashboard

从离线产物聚合 Beta 灰度期的 5 类核心观测指标：
  1. 完成率          · phase == "done" / "phase3" 占比
  2. 多轮深度        · rounds 数量分布 · 多轮 session 占比
  3. 首 token p50/p95 · 取 audit session_done.first_agent_chunk_s
  4. 降级率          · moderator_fallback_reason 非空占比
  5. RAG / Crisis / Bias 信号 · 从 session + audit 聚合

数据源（皆由 Roundtable 服务离线落盘）：
  - advisor_out/roundtable/sessions/<id>.json        · session 快照（终态）
  - advisor_out/roundtable/audit/YYYYMMDD/<id>.jsonl · 结构化事件流

用法：
    python scripts/roundtable_beta_dashboard.py                      # 全量
    python scripts/roundtable_beta_dashboard.py --since 2026-04-30   # 只看指定日期之后
    python scripts/roundtable_beta_dashboard.py --until 2026-05-10   # 只看指定日期之前
    python scripts/roundtable_beta_dashboard.py --json               # 机器可读输出
    python scripts/roundtable_beta_dashboard.py --sessions-dir ...   # override 目录

退出码：
    0 成功
    1 输入目录不存在或无 session
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from datetime import datetime, date
from pathlib import Path
from typing import Any, Iterable, Optional

# ── 项目根定位（__file__ 相对定位 · 不依赖 cwd） ──
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SESSIONS_DIR = PROJECT_ROOT / "advisor_out" / "roundtable" / "sessions"
DEFAULT_AUDIT_DIR = PROJECT_ROOT / "advisor_out" / "roundtable" / "audit"


# ═══════════════════════════════════════════════════════════════
# 加载
# ═══════════════════════════════════════════════════════════════


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    """解析 ISO 时间字符串 · 失败返回 None"""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def _in_range(
    created_at: Optional[datetime],
    since: Optional[date],
    until: Optional[date],
) -> bool:
    if created_at is None:
        # 没有时间字段 → 默认保留（不因缺字段被误删）
        return True
    d = created_at.date()
    if since and d < since:
        return False
    if until and d > until:
        return False
    return True


def load_sessions(
    sessions_dir: Path,
    since: Optional[date] = None,
    until: Optional[date] = None,
) -> list[dict[str, Any]]:
    """加载 session JSON · 按 created_at 过滤"""
    if not sessions_dir.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for p in sorted(sessions_dir.glob("*.json")):
        try:
            with open(p, "r", encoding="utf-8") as f:
                s = json.load(f)
        except Exception:
            # 坏 JSON 跳过 · 但提示
            print(f"warn: skip malformed session {p.name}", file=sys.stderr)
            continue
        if not isinstance(s, dict) or not s.get("id"):
            continue
        c_at = _parse_iso(s.get("created_at"))
        if not _in_range(c_at, since, until):
            continue
        out.append(s)
    return out


def load_audit_events(
    audit_dir: Path,
    session_ids: set[str],
) -> dict[str, list[dict[str, Any]]]:
    """加载指定 session 的所有 audit 事件 · 按 session_id 聚合。

    audit 路径是 YYYYMMDD 分片 · 扫全部分片 · 用 session_id 过滤。
    """
    by_session: dict[str, list[dict[str, Any]]] = {sid: [] for sid in session_ids}
    if not audit_dir.is_dir():
        return by_session
    # 扫所有日期子目录
    for day_dir in sorted(audit_dir.iterdir()):
        if not day_dir.is_dir():
            continue
        for jf in day_dir.glob("*.jsonl"):
            sid = jf.stem
            if sid not in session_ids:
                continue
            try:
                with open(jf, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            by_session[sid].append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
            except OSError:
                continue
    return by_session


# ═══════════════════════════════════════════════════════════════
# 聚合
# ═══════════════════════════════════════════════════════════════


def _pct(num: int, denom: int) -> float:
    return round(100.0 * num / denom, 1) if denom else 0.0


def _percentile(values: list[float], p: float) -> Optional[float]:
    """p ∈ [0, 100] · 空列表返回 None"""
    if not values:
        return None
    # statistics.quantiles 需要 ≥ 2 · 单值直接返回
    if len(values) == 1:
        return round(values[0], 3)
    s = sorted(values)
    # 线性插值法 · 与 numpy 默认一致（interpolation='linear'）
    k = (len(s) - 1) * (p / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    frac = k - lo
    return round(s[lo] + (s[hi] - s[lo]) * frac, 3)


def aggregate(
    sessions: list[dict[str, Any]],
    audit_by_session: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """把 session + audit 压成指标 dict · 供渲染/JSON 输出"""
    N = len(sessions)

    # 1. 完成率 / phase 分布 ────────────────────────
    # 口径说明：pipeline 正常走完会把 phase 置为 "phase3" 并停留在那里（不再置 "done"）。
    # "done" 只在 crisis-RED 中断或显式 reset 时出现 · 所以 "完成" 应以 phase3 为准。
    # setup 状态可能是「刚填完问题没跑」或「continue 后第 2+ 轮正在跑」· 需结合 rounds 判断。
    phase_counter: Counter[str] = Counter()
    for s in sessions:
        phase_counter[s.get("phase") or "unknown"] += 1
    done_n = phase_counter.get("done", 0)
    phase3_n = phase_counter.get("phase3", 0)
    # 「completed」口径：phase3 本身即视为完成（done 表示被危机中断）
    completed_n = phase3_n + done_n
    # 「in-progress」口径：setup/phase1/phase2 · 其中 setup 又分"真等开始"和"continue 后等第 2 轮"
    setup_pending_new_n = sum(
        1 for s in sessions
        if (s.get("phase") == "setup") and not (s.get("rounds") or [])
    )
    setup_midway_continue_n = sum(
        1 for s in sessions
        if (s.get("phase") == "setup") and (s.get("rounds") or [])
    )

    # 2. 多轮深度 ──────────────────────────────────
    # rounds[] 记录的是"已完结的历史轮" · 当前进行轮不在里面
    # 所以 effective_rounds = len(rounds) + (1 if 当前轮有进展 else 0)
    # 简化口径：用 round_index + 1 作为"当前轮号" · len(rounds) 是"已完结轮数"
    rounds_counts: list[int] = []  # 已完结轮数
    multi_round_n = 0
    for s in sessions:
        n = len(s.get("rounds") or [])
        rounds_counts.append(n)
        if n >= 1:  # 至少有一轮已归档 → 进入第二轮以上
            multi_round_n += 1
    avg_rounds = round(statistics.fmean(rounds_counts), 2) if rounds_counts else 0.0
    max_rounds = max(rounds_counts) if rounds_counts else 0

    # 3. 首 token 延迟（从 audit session_done.first_agent_chunk_s 取） ──
    first_token_samples: list[float] = []
    phase_durations: dict[str, list[float]] = {"phase1": [], "phase2": [], "phase3": []}
    moderator_durations: list[float] = []
    for sid, events in audit_by_session.items():
        for ev in events:
            etype = ev.get("event_type")
            data = ev.get("data") or {}
            if etype == "session_done":
                fac = data.get("first_agent_chunk_s")
                if isinstance(fac, (int, float)) and fac > 0:
                    first_token_samples.append(float(fac))
            elif etype == "phase_end":
                ph = ev.get("phase")
                dur = data.get("duration_s")
                if ph in phase_durations and isinstance(dur, (int, float)):
                    phase_durations[ph].append(float(dur))
            elif etype == "moderator_done":
                dur = data.get("duration_s")
                if isinstance(dur, (int, float)):
                    moderator_durations.append(float(dur))

    # 4. 降级率 ────────────────────────────────────
    fallback_sessions = [s for s in sessions if s.get("moderator_fallback_reason")]
    fallback_n = len(fallback_sessions)
    # 按原因聚合
    fallback_reasons: Counter[str] = Counter()
    for s in fallback_sessions:
        fallback_reasons[s.get("moderator_fallback_reason") or "unknown"] += 1
    # 也从 audit 聚合 moderator_done 的 fallback_reason（覆盖历史轮）
    moderator_total = 0
    moderator_fallback_total = 0
    for events in audit_by_session.values():
        for ev in events:
            if ev.get("event_type") == "moderator_done":
                moderator_total += 1
                reason = (ev.get("data") or {}).get("fallback_reason")
                if reason:
                    moderator_fallback_total += 1

    # 5. RAG 注入使用率 ────────────────────────────
    rag_used_n = sum(1 for s in sessions if (s.get("current_inject_context") or "").strip())
    # 也看 rounds 里历史注入（部分场景保留）
    rag_used_ever_n = 0
    for s in sessions:
        ever = bool((s.get("current_inject_context") or "").strip())
        if not ever:
            for r in s.get("rounds") or []:
                if (r.get("current_inject_context") or "").strip():
                    ever = True
                    break
        if ever:
            rag_used_ever_n += 1

    # 6. Deep mode 占比 ────────────────────────────
    deep_n = sum(1 for s in sessions if s.get("deep_mode"))

    # 7. Crisis / Bias 命中 ────────────────────────
    crisis_hits: Counter[str] = Counter()  # by hit_type
    crisis_session_ids: set[str] = set()
    bias_hits: Counter[str] = Counter()  # by category
    bias_session_ids: set[str] = set()
    agent_errors_n = 0
    agent_error_session_ids: set[str] = set()
    for sid, events in audit_by_session.items():
        for ev in events:
            etype = ev.get("event_type")
            data = ev.get("data") or {}
            if etype == "crisis_hit":
                crisis_hits[data.get("hit_type") or "unknown"] += 1
                crisis_session_ids.add(sid)
            elif etype == "bias_hit":
                for cat in data.get("categories") or ["unknown"]:
                    bias_hits[cat] += 1
                bias_session_ids.add(sid)
            elif etype == "agent_error":
                agent_errors_n += 1
                agent_error_session_ids.add(sid)

    # 8. Persona 分布 ──────────────────────────────
    persona_counter: Counter[str] = Counter()
    for s in sessions:
        for p in s.get("personas") or []:
            persona_counter[p] += 1

    # 9. Backend 分布 ──────────────────────────────
    backend_counter: Counter[str] = Counter()
    for s in sessions:
        backend_counter[s.get("backend") or "(default)"] += 1

    return {
        "totals": {
            "sessions": N,
            "phase_distribution": dict(phase_counter.most_common()),
            "completed": completed_n,                    # phase3 + done（正常结束）
            "completion_rate_pct": _pct(completed_n, N),
            "crisis_interrupted": done_n,                # done 只在 crisis-RED 中断时出现
            "setup_pending_new": setup_pending_new_n,    # 真"填完没跑"的
            "setup_midway_continue": setup_midway_continue_n,  # continue 后等第 2+ 轮
        },
        "multi_round": {
            "avg_archived_rounds": avg_rounds,
            "max_archived_rounds": max_rounds,
            "multi_round_sessions": multi_round_n,
            "multi_round_rate_pct": _pct(multi_round_n, N),
            "rounds_distribution": dict(Counter(rounds_counts).most_common()),
        },
        "latency": {
            "first_agent_chunk_samples": len(first_token_samples),
            "first_agent_chunk_p50_s": _percentile(first_token_samples, 50),
            "first_agent_chunk_p95_s": _percentile(first_token_samples, 95),
            "phase1_p95_s": _percentile(phase_durations["phase1"], 95),
            "phase2_p95_s": _percentile(phase_durations["phase2"], 95),
            "phase3_p95_s": _percentile(phase_durations["phase3"], 95),
            "moderator_p95_s": _percentile(moderator_durations, 95),
        },
        "fallback": {
            "sessions_with_fallback": fallback_n,
            "session_fallback_rate_pct": _pct(fallback_n, N),
            "session_fallback_reasons": dict(fallback_reasons.most_common()),
            "moderator_calls_total": moderator_total,
            "moderator_fallback_total": moderator_fallback_total,
            "moderator_fallback_rate_pct": _pct(moderator_fallback_total, moderator_total),
        },
        "rag": {
            "current_inject_sessions": rag_used_n,
            "current_inject_rate_pct": _pct(rag_used_n, N),
            "ever_inject_sessions": rag_used_ever_n,
            "ever_inject_rate_pct": _pct(rag_used_ever_n, N),
        },
        "deep_mode": {
            "sessions": deep_n,
            "rate_pct": _pct(deep_n, N),
        },
        "safety": {
            "crisis_events_total": sum(crisis_hits.values()),
            "crisis_sessions": len(crisis_session_ids),
            "crisis_by_hit_type": dict(crisis_hits.most_common()),
            "bias_events_total": sum(bias_hits.values()),
            "bias_sessions": len(bias_session_ids),
            "bias_by_category": dict(bias_hits.most_common()),
            "agent_errors_total": agent_errors_n,
            "agent_error_sessions": len(agent_error_session_ids),
            "agent_error_rate_pct": _pct(len(agent_error_session_ids), N),
        },
        "composition": {
            "personas_top": dict(persona_counter.most_common(5)),
            "backends": dict(backend_counter.most_common()),
        },
    }


# ═══════════════════════════════════════════════════════════════
# 渲染
# ═══════════════════════════════════════════════════════════════


def render_human(metrics: dict[str, Any], since: Optional[date], until: Optional[date]) -> str:
    lines: list[str] = []
    N = metrics["totals"]["sessions"]
    window = ""
    if since or until:
        window = f"  [范围 {since or '开始'} ~ {until or '今天'}]"

    def h(title: str) -> None:
        lines.append("")
        lines.append(f"── {title} " + "─" * max(1, 60 - len(title)))

    lines.append("═" * 66)
    lines.append(f" Roundtable Beta Dashboard · 共 {N} 个 session{window}")
    lines.append("═" * 66)

    if N == 0:
        lines.append("")
        lines.append("（没有符合条件的 session）")
        return "\n".join(lines)

    t = metrics["totals"]
    h("1. 完成率")
    lines.append(f"  phase 分布         : {t['phase_distribution']}")
    lines.append(f"  已完成（phase3+done）: {t['completed']}  ({t['completion_rate_pct']}%)")
    lines.append(f"  危机中断（done）    : {t['crisis_interrupted']}")
    lines.append(f"  等开始（setup 新） : {t['setup_pending_new']}")
    lines.append(f"  continue 中（setup 续）: {t['setup_midway_continue']}")

    m = metrics["multi_round"]
    h("2. 多轮深度")
    lines.append(f"  平均已归档轮数     : {m['avg_archived_rounds']}（最大 {m['max_archived_rounds']}）")
    lines.append(f"  多轮 session      : {m['multi_round_sessions']}  ({m['multi_round_rate_pct']}%)")
    lines.append(f"  轮数分布          : {m['rounds_distribution']}")

    l = metrics["latency"]
    h("3. 延迟（秒）")
    lines.append(f"  首 token p50      : {l['first_agent_chunk_p50_s']}  · 样本 {l['first_agent_chunk_samples']}")
    lines.append(f"  首 token p95      : {l['first_agent_chunk_p95_s']}")
    lines.append(f"  phase1 p95        : {l['phase1_p95_s']}")
    lines.append(f"  phase2 p95        : {l['phase2_p95_s']}")
    lines.append(f"  phase3 p95        : {l['phase3_p95_s']}")
    lines.append(f"  moderator p95     : {l['moderator_p95_s']}")

    f = metrics["fallback"]
    h("4. Moderator 降级")
    lines.append(f"  session 级降级     : {f['sessions_with_fallback']} ({f['session_fallback_rate_pct']}%)  原因={f['session_fallback_reasons']}")
    lines.append(f"  moderator 调用次数 : {f['moderator_calls_total']}  降级 {f['moderator_fallback_total']} ({f['moderator_fallback_rate_pct']}%)")

    r = metrics["rag"]
    h("5. RAG 注入")
    lines.append(f"  当前轮注入         : {r['current_inject_sessions']}  ({r['current_inject_rate_pct']}%)")
    lines.append(f"  任意轮注入过       : {r['ever_inject_sessions']}  ({r['ever_inject_rate_pct']}%)")

    d = metrics["deep_mode"]
    h("6. Deep Mode")
    lines.append(f"  启用 session      : {d['sessions']}  ({d['rate_pct']}%)")

    s = metrics["safety"]
    h("7. 安全 & 偏见")
    lines.append(f"  crisis 事件总数    : {s['crisis_events_total']}  · 涉及 {s['crisis_sessions']} 个 session")
    lines.append(f"  crisis hit_type   : {s['crisis_by_hit_type']}")
    lines.append(f"  bias 事件总数      : {s['bias_events_total']}  · 涉及 {s['bias_sessions']} 个 session")
    lines.append(f"  bias by category  : {s['bias_by_category']}")
    lines.append(f"  agent_error 总数   : {s['agent_errors_total']}  · 涉及 {s['agent_error_sessions']} session ({s['agent_error_rate_pct']}%)")

    c = metrics["composition"]
    h("8. 组合分布")
    lines.append(f"  Persona Top 5     : {c['personas_top']}")
    lines.append(f"  Backend           : {c['backends']}")

    lines.append("")
    lines.append("═" * 66)
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════


def _parse_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"日期格式必须是 YYYY-MM-DD，得到 {s!r}") from e


def main(argv: Optional[Iterable[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="Roundtable Beta 观测 Dashboard · D7.4.c",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--sessions-dir", type=Path, default=DEFAULT_SESSIONS_DIR,
                   help=f"session JSON 目录（默认：{DEFAULT_SESSIONS_DIR}）")
    p.add_argument("--audit-dir", type=Path, default=DEFAULT_AUDIT_DIR,
                   help=f"audit jsonl 根目录（默认：{DEFAULT_AUDIT_DIR}）")
    p.add_argument("--since", type=_parse_date, default=None,
                   help="只看该日期（含）之后创建的 session · 格式 YYYY-MM-DD")
    p.add_argument("--until", type=_parse_date, default=None,
                   help="只看该日期（含）之前创建的 session · 格式 YYYY-MM-DD")
    p.add_argument("--json", action="store_true",
                   help="输出 JSON（机器可读），否则输出人类可读 dashboard")
    args = p.parse_args(list(argv) if argv is not None else None)

    sessions = load_sessions(args.sessions_dir, since=args.since, until=args.until)
    if not args.sessions_dir.is_dir():
        print(f"error: sessions dir not found: {args.sessions_dir}", file=sys.stderr)
        return 1

    sid_set = {s["id"] for s in sessions}
    audit_by_session = load_audit_events(args.audit_dir, sid_set)
    metrics = aggregate(sessions, audit_by_session)

    if args.json:
        meta = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "sessions_dir": str(args.sessions_dir),
            "audit_dir": str(args.audit_dir),
            "since": args.since.isoformat() if args.since else None,
            "until": args.until.isoformat() if args.until else None,
        }
        print(json.dumps({"meta": meta, "metrics": metrics},
                         ensure_ascii=False, indent=2))
    else:
        print(render_human(metrics, args.since, args.until))
    return 0


if __name__ == "__main__":
    sys.exit(main())
