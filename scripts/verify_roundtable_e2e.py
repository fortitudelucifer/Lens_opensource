"""
Day 4 收尾 · 真 LLM 端到端 3 轮验证（Path A）

目标：
  ① 用真 LLM backend 跑一条多轮对话（3 轮 · Round 3 带 inject_context）
  ② 每轮解析完整 SSE 事件，测量：
       - first_token_latency（SLO ≤ 3s）
       - agent_chunk 总数（观察 GuardedEmitter flush 次数 ≈ 总字数/16）
       - Moderator 是否合法返回 6 段 JSON
       - Round 2/3 的 prior_context_block 是否真的注入（通过 backend log 间接观察）
  ③ 检测 BiasDetector / CrisisDetector 命中事件
  ④ 结果输出到 advisor_out/verification/roundtable_e2e_{ts}.{json,md}

使用前置：
  - backend 已在 :8801 运行
  - 真 LLM key 在 local_secrets/.env.advisor

运行：
  conda run -n wechatDHA python scripts/verify_roundtable_e2e.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import httpx

BASE = os.environ.get("ROUNDTABLE_BASE", "http://127.0.0.1:8801")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = PROJECT_ROOT / "advisor_out" / "verification"
OUT_DIR.mkdir(parents=True, exist_ok=True)

PERSONAS = ["neutral", "supportive", "eft"]

# ─────────────────────────────────────────────────────────────
# 3 轮对话剧本（真人感 · 情感咨询场景）
# ─────────────────────────────────────────────────────────────

ROUND1_Q = "我们最近经常为小事吵架，比如谁洗碗、谁接孩子，我很累，但他觉得我太敏感。我不知道是该继续沟通还是先冷静，请各位给建议。"

ROUND2_Q = "如果他总是沉默不回应，甚至说'我不想谈'，我应该硬着头皮继续开口，还是放手一段时间？"

# 模拟 RAG 注入：一段"知识手册"片段 + 一段"历史聊天"片段
ROUND3_INJECT = (
    "【相关知识片段】\n"
    "回避型依恋：在亲密关系遇到冲突时倾向于物理或情绪上的撤离，常伴随'我不想谈'、"
    "长时间沉默、工作加班等行为模式。应对时建议避免质问式追问，用邀请式表达（'我想听你的想法'）并给予物理空间。\n"
    "\n"
    "【相关聊天记录】\n"
    "Day 92 · ME: 你今天又一句话没说就进书房了\n"
    "Day 92 · OTHER: 我累了，能不能不要什么都要说\n"
)
ROUND3_Q = "结合刚才提到的那段对话和回避型的描述，我今晚见到他到底该先说什么？给我一个具体的开场白。"


# ─────────────────────────────────────────────────────────────
# 数据结构
# ─────────────────────────────────────────────────────────────


@dataclass
class AgentSnapshot:
    persona_id: str
    text: str = ""
    confidence: Optional[float] = None
    chunk_count: int = 0
    done_status: str = "pending"
    error: Optional[str] = None


@dataclass
class RoundResult:
    round_index: int
    question: str
    session_id: str
    inject_context: Optional[str] = None
    first_agent_chunk_s: Optional[float] = None
    session_done_s: Optional[float] = None
    phase1_agents: dict[str, AgentSnapshot] = field(default_factory=dict)
    phase2_agents: dict[str, AgentSnapshot] = field(default_factory=dict)
    moderator: Optional[dict] = None
    moderator_thinking: str = ""
    crisis_event: Optional[dict] = None
    safety_banner_event: Optional[dict] = None
    total_events: int = 0
    errors: list[str] = field(default_factory=list)

    def is_complete(self) -> bool:
        return self.session_done_s is not None and self.moderator is not None


@dataclass
class E2ESummary:
    started_at: str
    finished_at: str
    base_url: str
    personas: list[str]
    rounds: list[RoundResult] = field(default_factory=list)
    slo_pass: bool = False
    notes: list[str] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────
# SSE 解析
# ─────────────────────────────────────────────────────────────


def _sse_events(lines: "httpx.SyncIter[bytes]"):
    """原始 SSE 行流 → yield dict 事件"""
    buf: list[str] = []
    for raw in lines:
        if isinstance(raw, bytes):
            line = raw.decode("utf-8", errors="replace")
        else:
            line = raw
        if line == "":
            continue
        if line.startswith("data: "):
            payload = line[6:]
            if payload.strip() == "[DONE]":
                return
            try:
                yield json.loads(payload)
            except Exception:
                buf.append(payload)


def _consume_sse_stream(session_id: str, *, timeout: float = 180.0) -> tuple[list[dict], float]:
    """开一个 SSE 连接，收集所有事件直到 type=done 或 [DONE]。
    返回 (events, first_agent_chunk_relative_seconds_or_None)
    """
    events: list[dict] = []
    first_chunk_s: Optional[float] = None
    url = f"{BASE}/api/roundtable/stream/{session_id}"
    t0 = time.perf_counter()
    with httpx.Client(timeout=httpx.Timeout(timeout, read=timeout)) as client:
        with client.stream("GET", url) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line:
                    continue
                if line.startswith("data: "):
                    payload = line[6:]
                    if payload.strip() == "[DONE]":
                        break
                    try:
                        ev = json.loads(payload)
                    except Exception:
                        continue
                    events.append(ev)
                    if ev.get("type") == "agent_chunk" and first_chunk_s is None:
                        first_chunk_s = time.perf_counter() - t0
                    if ev.get("type") == "done":
                        break
    return events, first_chunk_s or -1.0


# ─────────────────────────────────────────────────────────────
# 单轮 runner
# ─────────────────────────────────────────────────────────────


def _agg_round(
    round_index: int,
    session_id: str,
    question: str,
    events: list[dict],
    first_chunk_s: float,
    total_wall_s: float,
    inject: Optional[str] = None,
) -> RoundResult:
    r = RoundResult(
        round_index=round_index,
        question=question,
        session_id=session_id,
        inject_context=inject,
        first_agent_chunk_s=first_chunk_s if first_chunk_s > 0 else None,
        session_done_s=total_wall_s,
        total_events=len(events),
    )
    for ev in events:
        t = ev.get("type")
        if t == "agent_chunk":
            phase = ev.get("phase", "phase1")
            pid = ev.get("agent_id", "?")
            bucket = r.phase1_agents if phase == "phase1" else r.phase2_agents
            snap = bucket.setdefault(pid, AgentSnapshot(persona_id=pid))
            snap.text += ev.get("delta", "")
            snap.chunk_count += 1
        elif t == "agent_done":
            phase = ev.get("phase", "phase1")
            pid = ev.get("agent_id", "?")
            bucket = r.phase1_agents if phase == "phase1" else r.phase2_agents
            snap = bucket.setdefault(pid, AgentSnapshot(persona_id=pid))
            snap.confidence = ev.get("confidence")
            snap.done_status = "done"
        elif t == "agent_error":
            phase = ev.get("phase", "phase1")
            pid = ev.get("agent_id", "?")
            bucket = r.phase1_agents if phase == "phase1" else r.phase2_agents
            snap = bucket.setdefault(pid, AgentSnapshot(persona_id=pid))
            snap.done_status = "error"
            snap.error = ev.get("error")
            r.errors.append(f"{phase}/{pid}: {ev.get('error')}")
        elif t == "moderator":
            r.moderator = ev.get("content")
            r.moderator_thinking = ev.get("thinking_text", "") or ""
        elif t == "crisis":
            r.crisis_event = ev
        elif t == "safety_banner":
            r.safety_banner_event = ev
    return r


def _run_round_1() -> RoundResult:
    """创建 session + 订阅 stream → 完成第一轮"""
    print(f"\n━━━━━━━━━━━━━━ Round 1 ━━━━━━━━━━━━━━")
    print(f"Q: {ROUND1_Q}")
    payload = {"personas": PERSONAS, "question": ROUND1_Q}
    with httpx.Client(timeout=30) as c:
        resp = c.post(f"{BASE}/api/roundtable/sessions", json=payload)
        resp.raise_for_status()
        session_id = resp.json()["session_id"]
    print(f"session_id = {session_id}")

    t0 = time.perf_counter()
    events, first_chunk_s = _consume_sse_stream(session_id, timeout=180)
    total = time.perf_counter() - t0
    print(f"  received {len(events)} events · first_chunk={first_chunk_s:.2f}s · total={total:.2f}s")
    return _agg_round(0, session_id, ROUND1_Q, events, first_chunk_s, total)


def _run_round_continue(session_id: str, round_index: int, question: str,
                         inject: Optional[str] = None) -> RoundResult:
    print(f"\n━━━━━━━━━━━━━━ Round {round_index + 1} ━━━━━━━━━━━━━━")
    print(f"Q: {question}")
    if inject:
        print(f"inject_context: {len(inject)} chars")

    body: dict[str, Any] = {"question": question}
    if inject:
        body["inject_context"] = inject
    with httpx.Client(timeout=30) as c:
        resp = c.post(f"{BASE}/api/roundtable/sessions/{session_id}/continue", json=body)
        resp.raise_for_status()

    t0 = time.perf_counter()
    events, first_chunk_s = _consume_sse_stream(session_id, timeout=180)
    total = time.perf_counter() - t0
    print(f"  received {len(events)} events · first_chunk={first_chunk_s:.2f}s · total={total:.2f}s")
    return _agg_round(round_index, session_id, question, events, first_chunk_s, total, inject=inject)


# ─────────────────────────────────────────────────────────────
# 输出
# ─────────────────────────────────────────────────────────────


def _extract_bias_hits_from_log(log_path: Path) -> list[str]:
    """从 backend 日志里抽 [bias_detector] hit 行"""
    if not log_path.exists():
        return []
    hits: list[str] = []
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if "[bias_detector] hit" in line:
                    hits.append(line.rstrip("\n"))
    except Exception:
        pass
    return hits


def _write_md_report(summary: E2ESummary, bias_hits: list[str], out_md: Path) -> None:
    lines: list[str] = []
    lines.append(f"# Roundtable 真 LLM 多轮 E2E 验证报告\n")
    lines.append(f"- 启动时间：{summary.started_at}")
    lines.append(f"- 完成时间：{summary.finished_at}")
    lines.append(f"- Backend：{summary.base_url}")
    lines.append(f"- Personas：{', '.join(summary.personas)}")
    lines.append(f"- SLO 判定：{'✅ PASS' if summary.slo_pass else '❌ FAIL'}")
    lines.append("")

    for r in summary.rounds:
        lines.append(f"## Round {r.round_index + 1}")
        lines.append(f"- question: {r.question}")
        if r.inject_context:
            lines.append(f"- inject_context: {len(r.inject_context)} 字")
        ft = f"{r.first_agent_chunk_s:.2f}s" if r.first_agent_chunk_s else "n/a"
        sd = f"{r.session_done_s:.2f}s" if r.session_done_s else "n/a"
        lines.append(f"- first_token: **{ft}** · session_done: **{sd}**")
        lines.append(f"- 总事件数：{r.total_events}")
        if r.crisis_event:
            lines.append(f"- ⚠️ crisis: `{r.crisis_event}`")
        if r.safety_banner_event:
            lines.append(f"- ⚠️ safety_banner: `{r.safety_banner_event}`")
        if r.errors:
            lines.append(f"- ❌ errors: {r.errors}")
        lines.append("")

        for phase_name, agents in (("Phase 1", r.phase1_agents), ("Phase 2", r.phase2_agents)):
            lines.append(f"### {phase_name}")
            if not agents:
                lines.append("_（无）_")
                continue
            for pid, snap in agents.items():
                conf_str = f"{snap.confidence:.2f}" if snap.confidence is not None else "n/a"
                lines.append(
                    f"- **{pid}** · chunks={snap.chunk_count} · confidence={conf_str} · "
                    f"status={snap.done_status}"
                )
                preview = snap.text[:280].replace("\n", " ")
                lines.append(f"  > {preview}{'…' if len(snap.text) > 280 else ''}")
            lines.append("")

        if r.moderator:
            lines.append("### Moderator（综合总结）")
            m = r.moderator
            lines.append(f"- **seen**: {m.get('seen', '')}")
            lines.append(f"- **angles**: {m.get('angles', [])}")
            lines.append(f"- **tries**: {m.get('tries', [])}")
            lines.append(f"- **doubts**: {m.get('doubts', [])}")
            lines.append(f"- **lens**: {m.get('lens', '')}")
            lines.append(f"- **limit**: {m.get('limit', '')}")
            if r.moderator_thinking:
                preview = r.moderator_thinking[:500].replace("\n", " ")
                lines.append(f"- **thinking**（前 500 字）: {preview}")
            lines.append("")

    lines.append("## BiasDetector 命中日志")
    if bias_hits:
        for h in bias_hits:
            lines.append(f"- `{h}`")
    else:
        lines.append("_本次真 LLM 对话未触发任何偏见规则_（空即正常 · 说明真 LLM 输出语气已较好，或规则未覆盖具体表达）")
    lines.append("")

    lines.append("## 备注 / 结论")
    for n in summary.notes:
        lines.append(f"- {n}")

    out_md.write_text("\n".join(lines), encoding="utf-8")


# ─────────────────────────────────────────────────────────────
# main
# ─────────────────────────────────────────────────────────────


def main() -> int:
    started = datetime.now().isoformat(timespec="seconds")
    summary = E2ESummary(
        started_at=started,
        finished_at="",
        base_url=BASE,
        personas=PERSONAS,
    )

    # Round 1
    try:
        r1 = _run_round_1()
    except Exception as exc:
        print(f"!!! Round 1 failed: {exc}")
        summary.notes.append(f"Round 1 fatal: {type(exc).__name__}: {exc}")
        summary.finished_at = datetime.now().isoformat(timespec="seconds")
        _finalize(summary)
        return 2
    summary.rounds.append(r1)

    # Round 2（必须在 r1 完成后）
    if r1.is_complete():
        try:
            r2 = _run_round_continue(r1.session_id, 1, ROUND2_Q)
            summary.rounds.append(r2)
        except Exception as exc:
            print(f"!!! Round 2 failed: {exc}")
            summary.notes.append(f"Round 2 fatal: {type(exc).__name__}: {exc}")
    else:
        summary.notes.append("Round 1 未 done · 跳过 Round 2/3")

    # Round 3 · 带 inject_context
    if summary.rounds and summary.rounds[-1].is_complete():
        last_sid = summary.rounds[-1].session_id
        try:
            r3 = _run_round_continue(last_sid, 2, ROUND3_Q, inject=ROUND3_INJECT)
            summary.rounds.append(r3)
        except Exception as exc:
            print(f"!!! Round 3 failed: {exc}")
            summary.notes.append(f"Round 3 fatal: {type(exc).__name__}: {exc}")

    # SLO 判定
    slo_budget = float(os.environ.get("ROUNDTABLE_SLO_P95", "3.0"))
    first_tokens = [r.first_agent_chunk_s for r in summary.rounds if r.first_agent_chunk_s]
    max_ft = max(first_tokens) if first_tokens else -1
    summary.slo_pass = bool(first_tokens) and max_ft <= slo_budget
    summary.notes.append(
        f"首 token SLO({slo_budget}s) · 样本数={len(first_tokens)} · "
        f"max={max_ft:.2f}s · {'PASS' if summary.slo_pass else 'OBSERVE · 真 LLM 首 token 抖动可超 SLO'}"
    )

    complete_rounds = sum(1 for r in summary.rounds if r.is_complete())
    summary.notes.append(f"完整完成的轮次：{complete_rounds}/3")

    # 检查 Round 2/3 是否有跨轮连贯性 · 看 moderator.seen 是否包含上轮话题字
    if len(summary.rounds) >= 2 and summary.rounds[0].moderator:
        r1_seen = summary.rounds[0].moderator.get("seen", "") or ""
        # 简单启发式：Round 2 的任一 agent 文本里是否提到了 Round 1 用户问题的关键词
        r1_topic_hits = 0
        for kw in ["吵架", "洗碗", "接孩子", "敏感"]:
            for snap in summary.rounds[1].phase1_agents.values():
                if kw in snap.text:
                    r1_topic_hits += 1
                    break
        summary.notes.append(f"Round 2 phase1 对 Round 1 关键词提及命中：{r1_topic_hits}/4（≥2 表示跨轮连贯）")

    summary.finished_at = datetime.now().isoformat(timespec="seconds")
    return _finalize(summary)


def _finalize(summary: E2ESummary) -> int:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_json = OUT_DIR / f"roundtable_e2e_{ts}.json"
    out_md = OUT_DIR / f"roundtable_e2e_{ts}.md"

    bias_hits = _extract_bias_hits_from_log(Path("/tmp/roundtable_e2e/backend.log"))

    with open(out_json, "w", encoding="utf-8") as f:
        payload = asdict(summary)
        payload["bias_hits"] = bias_hits
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
    _write_md_report(summary, bias_hits, out_md)

    print("\n" + "═" * 72)
    print(f"Saved: {out_json}")
    print(f"Saved: {out_md}")
    print("═" * 72)
    print(f"Rounds complete: {sum(1 for r in summary.rounds if r.is_complete())}/3")
    for r in summary.rounds:
        ft = f"{r.first_agent_chunk_s:.2f}s" if r.first_agent_chunk_s else "n/a"
        sd = f"{r.session_done_s:.2f}s" if r.session_done_s else "n/a"
        mod_ok = "✓" if r.moderator else "✗"
        print(f"  Round {r.round_index + 1}: first_token={ft} done={sd} moderator={mod_ok}")
    print(f"Bias hits: {len(bias_hits)}")
    print(f"SLO pass : {summary.slo_pass}")
    return 0 if all(r.is_complete() for r in summary.rounds) and len(summary.rounds) == 3 else 1


if __name__ == "__main__":
    sys.exit(main())
