"""
Day 4 · D4.8 · CrossRoundMemory 端到端验证脚本

目的：
  1. 模拟一个 3 轮对话的 session.rounds（不需要真 LLM / HTTP）
  2. 调用 `_build_prior_context_block(s, persona)` —— 即实际 prompt 拼装的入口
  3. 验证返回文本同时包含：
       · Tier-1（最新轮 · 包含 persona 上轮的 phase2 原文）
       · Tier-2（次新轮 · 中度摘要）
       · Tier-3（第 1 轮 · 极简 LIFO）
  4. 验证 char_count 与 token_estimate 在 ≤ 2000 token 的预算内
  5. 验证审计日志 `memory_built` 被正确落盘
  6. 验证 prompt 渲染（phase1_template）时 `{prior_context_block}` 被正确替换

输出：
  advisor_out/verification/roundtable_memory_e2e_{ts}.json + .md

运行：
  conda run -n wechatDHA python scripts/verify_roundtable_memory_e2e.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# 必须在 import roundtable_audit 之前设置，确保落盘到临时目录
TMP_AUDIT = Path(tempfile.mkdtemp(prefix="rt_mem_e2e_"))
os.environ["ROUNDTABLE_AUDIT_ROOT"] = str(TMP_AUDIT)

from scripts.advisor.api.core.models import (  # noqa: E402
    RoundtableAgentBuffer, RoundtableModeratorContent,
    RoundtableRoundSnapshot, RoundtableSession,
)
from scripts.advisor.api.services import roundtable_audit as audit  # noqa: E402
from scripts.advisor.api.services import roundtable_memory as mem  # noqa: E402
from scripts.advisor.api.services.roundtable_service import (  # noqa: E402
    _build_prior_context_block, _build_phase1_prompt, _load_prompts,
)

OUT_DIR = PROJECT_ROOT / "advisor_out" / "verification"
OUT_DIR.mkdir(parents=True, exist_ok=True)

PERSONAS = ["neutral", "supportive", "eft"]
TARGET_PERSONA = "neutral"
TOKEN_BUDGET = 2000  # 目标：memory_block 估算 token 不超过 2000


# ═════════════════════════════════════════════════════════════
# 数据工厂（3 轮 · 真实感文案）
# ═════════════════════════════════════════════════════════════

ROUND_SCRIPTS = [
    {
        "question": (
            "我们最近总为家务小事吵架，我觉得他不体谅我，但他说我太敏感了。"
            "我不知道这种争吵是健康的磨合，还是关系出了问题？"
        ),
        "self_phase2": {
            "neutral": (
                "从结构看，这是分工边界不清晰 + 情绪反馈回路紊乱导致的"
                "高频低烈度冲突。建议先把'家务清单'显式化，把沟通和任务分离。"
            ),
            "supportive": (
                "先别急着下判断。你说'我很累'的那一瞬，是最值得停下来看看的。"
                "他说'太敏感'时，你内心冒出的第一个感受是什么？"
            ),
            "eft": (
                "这些争吵底下，常常是'我需要被你看见'的呐喊没被听到。"
                "试着跟他说'我害怕我们越走越远'，而不是'你又没倒垃圾'。"
            ),
        },
        "moderator": {
            "seen": "我看到你们三位都在说：表面是家务，底下是连接的渴望。",
            "limit": "我不能替你决定要不要继续这段关系。",
        },
    },
    {
        "question": (
            "如果他用沉默回应我，甚至说'我不想谈'，我应该继续追问，"
            "还是给他空间？我怕退一步就永远打不开这个话题。"
        ),
        "self_phase2": {
            "neutral": (
                "沉默是一种信号，不是障碍。承认他'此刻不想谈'，"
                "同时和他约一个可预期的重开点（例如'今晚八点再聊 20 分钟'）。"
            ),
            "supportive": (
                "你的担心我听见了。退一步，不是退让，是给情绪降温。"
                "在他沉默时，你也可以只是坐在他旁边，什么都不说。"
            ),
            "eft": (
                "沉默往往是被情绪淹没后的冻住反应，不是不爱。"
                "用身体的靠近代替语言的追问，试着摸摸他的手。"
            ),
        },
        "moderator": {
            "seen": "三位都在说：紧迫感来自你，但修复节奏得由你们共同决定。",
            "limit": "我无法评估他究竟是冻结还是抗拒。",
        },
    },
    {
        "question": (
            "结合刚才的讨论，今晚我见到他，第一句话应该怎么说？"
            "我想开启对话但不想让他觉得被追问。"
        ),
        "self_phase2": {
            "neutral": "（第 3 轮待进行，本快照不含 phase2）",
            "supportive": "（第 3 轮待进行）",
            "eft": "（第 3 轮待进行）",
        },
        "moderator": None,
    },
]


def _make_snapshot(idx: int) -> RoundtableRoundSnapshot:
    script = ROUND_SCRIPTS[idx]
    phase2 = [
        RoundtableAgentBuffer(
            persona_id=pid,  # type: ignore[arg-type]
            status="done",
            text=script["self_phase2"][pid],
            confidence=0.85,
        )
        for pid in PERSONAS
    ]
    mod = None
    if script["moderator"]:
        mod = RoundtableModeratorContent(
            seen=script["moderator"]["seen"],
            angles=["结构", "感受", "依恋"],
            tries=["显式分工", "共同节奏", "肢体安抚"],
            doubts=["他此刻到底是冻结还是抗拒？"],
            lens="伴侣关系",
            limit=script["moderator"]["limit"],
        )
    return RoundtableRoundSnapshot(
        round_index=idx,
        question=script["question"],
        phase1=[],
        phase2=phase2,
        moderator=mod,
        moderator_thinking="",
        created_at=datetime.now(),
        completed_at=datetime.now(),
    )


# ═════════════════════════════════════════════════════════════
# 验证
# ═════════════════════════════════════════════════════════════


def run_verification() -> dict:
    # 在第 3 轮「进行中」的场景：前两轮归档在 session.rounds，
    # 第三轮是 current active round（rounds 里只存完成的，当前轮在 session.question/phase1/phase2 里）
    # 所以测试：把前 2 轮存到 rounds，第 3 轮作为 current question
    # 但为了验证 Tier-3 触发（需要至少 3 完成轮），我们扩展到 3 完成轮 + 第 4 轮追问场景
    snaps = [_make_snapshot(i) for i in range(len(ROUND_SCRIPTS))]
    now = datetime.now()
    session = RoundtableSession(
        id=f"rt_memtest_e2e_{int(now.timestamp())}",
        personas=PERSONAS,  # type: ignore[arg-type]
        question="第 4 轮追问：具体一点告诉我，开场白应该讲什么？",
        phase="phase1",
        rounds=snaps,
        round_index=len(snaps),
        created_at=now,
        updated_at=now,
    )

    # ── 1. 调用入口 ──
    block = _build_prior_context_block(session, TARGET_PERSONA)

    # ── 2. 单独跑一次 build_memory_block 拿 metrics ──
    _, metrics = mem.build_memory_block(session, TARGET_PERSONA)

    # ── 3. 渲染完整 phase1 prompt ──
    try:
        prompts = _load_prompts()
        tmpl = prompts.get("phase1_template") if prompts else None
        if tmpl:
            full_prompt = tmpl.format(
                persona_name="中立顾问",
                persona_core="理性分析结构与选择空间。",
                question=session.question,
                prior_context_block=block,
            )
        else:
            full_prompt = None
    except Exception as e:
        full_prompt = f"[prompt render failed: {e}]"

    # ── 4. 检查 audit 日志 ──
    audit_files = list(TMP_AUDIT.rglob(f"{session.id}.jsonl"))
    memory_events = []
    if audit_files:
        for ln in audit_files[0].read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                ev = json.loads(ln)
                if ev.get("event_type") == "memory_built":
                    memory_events.append(ev)
            except Exception:
                pass

    # ── 5. 断言 ──
    checks: dict[str, tuple[bool, str]] = {}
    checks["block_not_empty"] = (bool(block), f"len(block) = {len(block)}")
    checks["tier1_header_present"] = (
        "讨论回顾" in block and "第 3 轮" in block,
        "含 Tier-1 标题 + 最新轮标号",
    )
    checks["tier2_present"] = (
        "更早一轮（第 2 轮）" in block,
        "Tier-2 次新轮标题",
    )
    checks["tier3_present"] = (
        "· [第 1 轮]" in block,
        "Tier-3 LIFO 条目（最早轮）",
    )
    # neutral 在 Round 2（Tier-2）的原文片段
    checks["persona_self_leaked"] = (
        "沉默是一种信号" in block,
        "Tier-2 应包含目标 persona（neutral）上轮的回应原文",
    )
    checks["token_budget_ok"] = (
        metrics.token_estimate <= TOKEN_BUDGET,
        f"token_estimate={metrics.token_estimate} ≤ {TOKEN_BUDGET}",
    )
    checks["audit_emitted"] = (
        len(memory_events) >= 1,
        f"audit log memory_built events = {len(memory_events)}",
    )
    checks["phase1_prompt_includes_memory"] = (
        full_prompt is not None and "讨论回顾" in full_prompt,
        "phase1_template 渲染后含 memory block",
    )

    results = {
        "session_id": session.id,
        "rounds_count": len(snaps),
        "target_persona": TARGET_PERSONA,
        "metrics": metrics.to_dict(),
        "block_char_count": len(block),
        "block_preview": block[:800] + ("..." if len(block) > 800 else ""),
        "phase1_prompt_char_count": len(full_prompt) if full_prompt else 0,
        "phase1_prompt_preview": (full_prompt[:1200] + "...") if full_prompt else None,
        "audit_memory_events": memory_events,
        "checks": {
            k: {"ok": ok, "detail": detail}
            for k, (ok, detail) in checks.items()
        },
        "passed": all(ok for ok, _ in checks.values()),
    }
    return results


def main() -> int:
    result = run_verification()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = OUT_DIR / f"roundtable_memory_e2e_{ts}.json"
    md_path = OUT_DIR / f"roundtable_memory_e2e_{ts}.md"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    # MD 报告
    md = [
        f"# Roundtable CrossRoundMemory E2E 验证 · {ts}",
        "",
        f"- **session_id**: `{result['session_id']}`",
        f"- **rounds_count**: {result['rounds_count']}",
        f"- **target_persona**: `{result['target_persona']}`",
        f"- **block_char_count**: {result['block_char_count']}",
        f"- **token_estimate**: {result['metrics']['token_estimate']}",
        f"- **truncated**: {result['metrics']['truncated']}",
        f"- **kept_rounds / round_count**: "
        f"{result['metrics']['kept_rounds']} / {result['metrics']['round_count']}",
        "",
        "## 检查清单",
        "",
    ]
    for k, v in result["checks"].items():
        mark = "✅" if v["ok"] else "❌"
        md.append(f"- {mark} **{k}** — {v['detail']}")
    md.extend([
        "",
        f"## 总结: {'✅ PASSED' if result['passed'] else '❌ FAILED'}",
        "",
        "### memory block preview（前 800 char）",
        "",
        "```",
        result["block_preview"],
        "```",
    ])
    md_path.write_text("\n".join(md), encoding="utf-8")

    print(f"✔ JSON: {json_path}")
    print(f"✔ MD  : {md_path}")
    print(f"✔ PASSED: {result['passed']}")
    if not result["passed"]:
        print("\nFailed checks:")
        for k, v in result["checks"].items():
            if not v["ok"]:
                print(f"  - {k}: {v['detail']}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
