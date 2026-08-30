"""统一 Trace 落盘 + 事后抽取器 + run manifest（评测 Harness M1）

对应契约：
- §2 统一 Trace Schema（一个决策点 = 一条 trace）
- §1 H1 公开/私有分库，永不合并；H4 不阻塞主对话（本模块事后运行）
- §4 Run Manifest（H2 复现性：flags/seed/commit/数据）

MVP 定位（§12）：先做**事后抽取器**——读已存的 chat_session JSON（已含 messages +
supervision_log 六维），零侵入地产出 trace，用来验 schema/分库、估 availability。
真实干预注入（live hook）为后续增量，不在本文件。

输出布局：
  advisor_out/eval/traces/<run_id>/<session>.jsonl     # 公开（截断摘要，可分析）
  advisor_out/eval/_private/<run_id>/<session>.jsonl   # 私有（全文+完整 analysis，仅审计）
  advisor_out/eval/runs/<run_id>/manifest.json         # run 清单
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

from scripts.advisor.eval.ablation import (
    ADVISOR_OUT,
    EVAL_OUT,
    NUMERIC_DIMS,
    PROJECT_ROOT,
    AblationContext,
    extract_sixdim,
)

logger = logging.getLogger("advisor.eval.tracer")

SCHEMA_VERSION = "eval.trace.v1"
EXTRACTOR_VERSION = "post_hoc_extract.v1"
_PUBLIC_DIGEST_CHARS = 80   # 公开摘要截断长度（全文只进私有库，H1）


def _digest(text: Optional[str], n: int = _PUBLIC_DIGEST_CHARS) -> str:
    t = (text or "").strip().replace("\n", " ")
    return t[:n] + ("…" if len(t) > n else "")


def _git_commit() -> Optional[str]:
    try:
        out = subprocess.run(
            ["git", "-C", str(PROJECT_ROOT), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        return out.stdout.strip() or None
    except Exception:
        return None


def _io_by_round(messages: list[dict]) -> dict[int, dict]:
    """把 messages 映射为 round -> {input, output}。

    round = 第 k 个 assistant 回复（0-indexed），与 supervision_agent 写入的
    round 对齐；input = 该 assistant 之前最近的一条 user 消息。
    """
    io: dict[int, dict] = {}
    last_user = ""
    assistant_count = 0
    for m in messages:
        role = m.get("role")
        content = m.get("content") or ""
        if role == "user":
            last_user = content
        elif role == "assistant":
            io[assistant_count] = {"input": last_user, "output": content}
            assistant_count += 1
    return io


class EvalTracer:
    """把一个会话抽取为多条 trace，公开/私有分库落盘。"""

    def __init__(
        self,
        run_id: str,
        ctx: AblationContext,
        base_dir: Optional[Path] = None,
    ):
        self.run_id = run_id
        self.ctx = ctx
        base = Path(base_dir) if base_dir else EVAL_OUT
        self.public_dir = base / "traces" / run_id
        self.private_dir = base / "_private" / run_id
        self.runs_dir = base / "runs" / run_id
        for d in (self.public_dir, self.private_dir, self.runs_dir):
            d.mkdir(parents=True, exist_ok=True)
        self.n_decision_points = 0
        self.n_sessions = 0

    # -- 事后抽取 --
    def extract_from_session(self, session: dict) -> int:
        """抽取一个会话，返回写入的决策点数。"""
        session_id = session.get("id") or "unknown"
        messages = session.get("messages") or []
        sup_log = session.get("supervision_log") or []
        io_map = _io_by_round(messages)

        # 只保留有有效六维的督导条目，按 round 排序
        entries = []
        for e in sup_log:
            sd = extract_sixdim(e.get("analysis"))
            if sd is not None:
                entries.append((int(e.get("round", 0)), sd, e))
        entries.sort(key=lambda x: x[0])
        if not entries:
            return 0

        lag = int(self.ctx.proximal["lag"])
        agent = {"type": session.get("agent_type"), "backend": session.get("backend")}

        public_lines, private_lines = [], []
        points_since_inject = int(self.ctx.eligibility["cooldown"])  # 首点不被冷却挡

        for i, (rnd, sd, raw_entry) in enumerate(entries):
            elig = self.ctx.check_eligibility(sd, points_since_inject, rnd)
            arm, prob = (None, None)
            if elig["eligible"]:
                arm, prob = self.ctx.assign_arm(self.run_id, session_id, rnd)
            # 冷却计数：counterfactual 注入也计入（与 live 行为一致）
            if arm == "prompt":
                points_since_inject = 0
            else:
                points_since_inject += 1

            # 近端结局：lag 个决策点后的六维变化
            proximal = {"lag": lag, "available": False, "delta": {}}
            if i + lag < len(entries):
                nxt = entries[i + lag][1]
                proximal["available"] = True
                proximal["delta"] = {
                    d: (nxt[d] - sd[d]) if (sd.get(d) is not None and nxt.get(d) is not None) else None
                    for d in NUMERIC_DIMS
                }

            io = io_map.get(rnd, {"input": "", "output": ""})
            trace_id = "t_" + hashlib.sha1(
                f"{self.run_id}|{session_id}|{rnd}".encode()
            ).hexdigest()[:10]

            public_lines.append({
                "schema_version": SCHEMA_VERSION,
                "run_id": self.run_id,
                "trace_id": trace_id,
                "session_id": session_id,
                "turn": rnd,
                "ts": raw_entry.get("timestamp") or datetime.now().isoformat(),
                "unit": "chat_turn",
                "agent": agent,
                "io": {
                    "input_digest": _digest(io["input"]),
                    "output_digest": _digest(io["output"]),
                    "input_ref": f"round:{rnd}",
                    "has_output": bool(io["output"]),
                },
                "flags": self.ctx.snapshot(),
                "eligibility": elig,
                "arm": arm,
                "randomization_prob": prob,
                "metrics": {"supervision": sd},
                "outcome": {"proximal": proximal},
                "provenance": {"source": EXTRACTOR_VERSION},
            })
            private_lines.append({
                "trace_id": trace_id,
                "session_id": session_id,
                "turn": rnd,
                "raw_io": {"input": io["input"], "output": io["output"]},
                "analysis_full": raw_entry.get("analysis"),
                "judge_backend": raw_entry.get("judge_backend"),
            })

        self._write_jsonl(self.public_dir / f"{session_id}.jsonl", public_lines)
        self._write_jsonl(self.private_dir / f"{session_id}.jsonl", private_lines)
        self.n_decision_points += len(public_lines)
        self.n_sessions += 1
        return len(public_lines)

    @staticmethod
    def _write_jsonl(path: Path, rows: list[dict]) -> None:
        with open(path, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    def write_manifest(self, extra: Optional[dict] = None) -> Path:
        """写 run manifest（H2）。"""
        manifest = {
            "run_id": self.run_id,
            "created_at": datetime.now().isoformat(),
            "source": EXTRACTOR_VERSION,
            "schema_version": SCHEMA_VERSION,
            "flags": self.ctx.snapshot(),
            "eligibility": self.ctx.eligibility,
            "randomization": self.ctx.randomization,
            "proximal": self.ctx.proximal,
            "ablation_source": self.ctx.source,
            "code_commit": _git_commit(),
            "n_sessions": self.n_sessions,
            "n_decision_points": self.n_decision_points,
        }
        if extra:
            manifest.update(extra)
        path = self.runs_dir / "manifest.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        return path


def extract_sessions(
    run_id: str,
    sessions_dir: Optional[Path] = None,
    ablation_yaml: Optional[Path] = None,
    base_dir: Optional[Path] = None,
) -> dict:
    """CLI 入口：抽取一个目录下所有 chat_session。"""
    sessions_dir = Path(sessions_dir) if sessions_dir else (ADVISOR_OUT / "chat_sessions")
    ctx = AblationContext(yaml_path=ablation_yaml)
    tracer = EvalTracer(run_id, ctx, base_dir=base_dir)

    files = sorted(sessions_dir.glob("*.json"))
    skipped = 0
    for p in files:
        try:
            session = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("跳过无法解析的 session %s: %s", p.name, e)
            skipped += 1
            continue
        tracer.extract_from_session(session)

    manifest_path = tracer.write_manifest(extra={"sessions_scanned": len(files), "sessions_skipped": skipped})
    return {
        "run_id": run_id,
        "sessions_scanned": len(files),
        "sessions_with_traces": tracer.n_sessions,
        "decision_points": tracer.n_decision_points,
        "public_dir": str(tracer.public_dir),
        "private_dir": str(tracer.private_dir),
        "manifest": str(manifest_path),
    }


def main():
    ap = argparse.ArgumentParser(description="评测 Harness 事后抽取器（M1 MVP）")
    ap.add_argument("--run", required=True, help="run_id，如 pilot_2026-07-03")
    ap.add_argument("--sessions", default=None, help="chat_session 目录（默认 advisor_out/chat_sessions）")
    ap.add_argument("--ablation", default=None, help="ablation.yaml 路径（默认 configs/ablation.yaml）")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    result = extract_sessions(
        run_id=args.run,
        sessions_dir=args.sessions,
        ablation_yaml=args.ablation,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n下一步：python -m scripts.advisor.eval.metrics --run {args.run}")


if __name__ == "__main__":
    main()
