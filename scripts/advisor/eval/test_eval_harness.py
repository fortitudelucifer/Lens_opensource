"""评测 Harness 自测（M1 MVP · 无需 pytest）

验收对应 §10：
- 私有分库（H1）：公开 trace 不含全文原文 / 完整 analysis
- 决策点随机化可复现：同 (run,session,turn) → 同臂
- 合格规则：触发 / 危机拦截 / 起始轮拦截 正确
- 指标可算：compute_report 出 availability

运行：python -m scripts.advisor.eval.test_eval_harness
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from scripts.advisor.eval.ablation import AblationContext, extract_sixdim
from scripts.advisor.eval.metrics import compute_report
from scripts.advisor.eval.tracer import EvalTracer

# 放在 80 字符摘要截断之后的唯一标记，用于验证分库
_MARKER = "ZZ_UNIQUE_RAW_MARKER_9x7q"
_PAD = "这是一段足够长的用户原始发言用来把独特标记推到公开摘要截断之外" * 2  # >80 字符


def _synthetic_session() -> dict:
    long_user = _PAD + _MARKER
    return {
        "id": "testsess",
        "agent_type": "neutral",
        "backend": "grok",
        "messages": [
            {"role": "user", "content": long_user},
            {"role": "assistant", "content": "顾问回复 A"},
            {"role": "user", "content": "用户第二句"},
            {"role": "assistant", "content": "顾问回复 B"},
            {"role": "user", "content": "用户第三句"},
            {"role": "assistant", "content": "顾问回复 C"},
            {"role": "user", "content": "用户第四句"},
            {"role": "assistant", "content": "顾问回复 D"},
        ],
        "supervision_log": [
            {"round": 0, "timestamp": "t0", "judge_backend": "claude",
             "analysis": _mk_analysis(empathy=8, safety="通过")},   # 高共情 + turn0 → 不合格(触发否+起始轮)
            {"round": 1, "timestamp": "t1", "judge_backend": "claude",
             "analysis": _mk_analysis(empathy=5, safety="通过")},   # 触发 + 非危机 → 合格
            {"round": 2, "timestamp": "t2", "judge_backend": "claude",
             "analysis": _mk_analysis(empathy=4, safety="风险")},   # 触发 + 危机 → 不合格
            {"round": 3, "timestamp": "t3", "judge_backend": "claude",
             "analysis": _mk_analysis(empathy=3, safety="通过")},
        ],
    }


def _mk_analysis(empathy: int, safety: str) -> dict:
    return {
        "dialogue_progress": {"stage": "探索", "stuck": False},
        "power_dynamics": {"score": 5, "summary": "均衡"},
        "empathy_specificity": {"score": empathy, "reason": "测试"},
        "safety_boundary": {"score": 9 if safety == "通过" else 2, "label": safety, "notes": ""},
        "single_perspective_risk": {"score": 6, "is_risk": False, "suggestion": ""},
        "attachment_signal": {"score": 7, "level": "低", "notes": ""},
    }


def _run() -> None:
    ctx = AblationContext(yaml_path=Path("/nonexistent_use_code_defaults"))  # τ=6,cooldown=2,min_turn=1,p=0.5

    # --- extract_sixdim ---
    assert extract_sixdim(None) is None
    sd = extract_sixdim(_mk_analysis(5, "通过"))
    assert sd and sd["empathy_specificity"] == 5 and sd["safety_label"] == "通过", sd
    print("✓ extract_sixdim")

    # --- 决策点随机化可复现 ---
    a1 = ctx.assign_arm("runX", "sess", 1)
    a2 = ctx.assign_arm("runX", "sess", 1)
    assert a1 == a2 and a1[0] in ("prompt", "no_prompt"), (a1, a2)
    print("✓ 随机分臂可复现:", a1)

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        tracer = EvalTracer("runtest", ctx, base_dir=base)
        n = tracer.extract_from_session(_synthetic_session())
        assert n == 4, f"应产出 4 个决策点，实得 {n}"
        tracer.write_manifest()
        print("✓ 抽取 4 个决策点")

        pub_text = (base / "traces" / "runtest" / "testsess.jsonl").read_text(encoding="utf-8")
        priv_text = (base / "_private" / "runtest" / "testsess.jsonl").read_text(encoding="utf-8")

        # --- 私有分库（H1）---
        assert _MARKER not in pub_text, "公开 trace 泄漏了全文原文！"
        assert _MARKER in priv_text, "私有库应保留全文原文"
        assert "analysis_full" not in pub_text, "公开 trace 不应含完整 analysis"
        assert "rationale" not in pub_text.lower()
        print("✓ 公开/私有分库正确（全文只在私有库）")

        # --- 合格规则逐条 ---
        pub = {json.loads(l)["turn"]: json.loads(l) for l in pub_text.splitlines()}
        assert pub[0]["eligibility"]["min_turn_block"] is True
        assert pub[0]["eligibility"]["eligible"] is False
        assert pub[1]["eligibility"]["trigger_hit"] is True
        assert pub[1]["eligibility"]["eligible"] is True
        assert pub[1]["arm"] in ("prompt", "no_prompt")
        assert pub[2]["eligibility"]["crisis_block"] is True
        assert pub[2]["eligibility"]["eligible"] is False
        assert pub[2]["arm"] is None
        print("✓ 合格规则：触发/危机/起始轮 判定正确")

        # --- 近端结局 ---
        assert pub[0]["outcome"]["proximal"]["available"] is True
        assert pub[0]["outcome"]["proximal"]["delta"]["empathy_specificity"] == 5 - 8
        assert pub[3]["outcome"]["proximal"]["available"] is False  # 最后一个无后继
        print("✓ 近端结局差 Δ 计算正确")

        # --- 指标 ---
        rep = compute_report("runtest", base_dir=base)
        assert rep["n_decision_points"] == 4
        assert rep["n_sessions"] == 1
        assert 0.0 <= rep["availability"]["eligible_rate"] <= 1.0
        assert rep["sixdim_distribution"]["empathy_specificity"]["n"] == 4
        assert rep["availability"]["blocks"]["crisis"] == 1
        print("✓ 指标报告可算:", rep["availability"])

    print("\nALL TESTS PASSED ✅")


if __name__ == "__main__":
    _run()
