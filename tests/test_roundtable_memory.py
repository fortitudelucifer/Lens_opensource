"""
Day 4 · D4.8 · CrossRoundMemory 单测

覆盖：
- 空 `session.rounds` → 返回 ("", metrics with round_count=0)
- 单轮压缩 → 输出 Tier-1 格式 · 包含 persona 上轮回应要点
- 多轮（2 轮）→ Tier-1 + Tier-2 · 预算内完全保留
- 多轮（5 轮）→ Tier-1 + Tier-2 + Tier-3 LIFO · 最老的优先丢
- 超大预算截断 → char_budget 很小时 truncated=True · Tier-3 先被丢弃
- snapshot 字段缺失（moderator=None / phase2 空） → 不 raise · 返回 placeholder
- metrics 基本正确：round_count / kept_rounds / token_estimate / tier_breakdown
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.advisor.api.core.models import (  # noqa: E402
    RoundtableAgentBuffer, RoundtableModeratorContent,
    RoundtableRoundSnapshot, RoundtableSession,
)
from scripts.advisor.api.services import roundtable_memory as mem  # noqa: E402


# ═════════════════════════════════════════════════════════════
# fixture · 构造 session + rounds
# ═════════════════════════════════════════════════════════════


def _make_moderator(
    seen: str = "双方都渴望被看见", limit: str = "我不能代替你做决定",
) -> RoundtableModeratorContent:
    return RoundtableModeratorContent(
        seen=seen,
        angles=["关注结构", "提醒感受", "代际模式"],
        tries=["先对话一次", "记录情绪"],
        doubts=["这是他真的想法吗？"],
        lens="伴侣关系",
        limit=limit,
    )


def _make_round(
    idx: int, question: str, *, personas: list[str] | None = None,
    self_text_tpl: str = "第{k}轮我的核心观点是...",
    with_moderator: bool = True,
) -> RoundtableRoundSnapshot:
    personas = personas or ["neutral", "supportive", "eft"]
    phase1 = [
        RoundtableAgentBuffer(
            persona_id=pid, status="done",  # type: ignore[arg-type]
            text=f"[{pid}] 第 {idx+1} 轮 phase1 分析",
            confidence=0.8,
        )
        for pid in personas
    ]
    phase2 = [
        RoundtableAgentBuffer(
            persona_id=pid, status="done",  # type: ignore[arg-type]
            text=self_text_tpl.format(k=idx + 1) + f" · 立场={pid}",
            confidence=0.85,
        )
        for pid in personas
    ]
    return RoundtableRoundSnapshot(
        round_index=idx,
        question=question,
        phase1=phase1,
        phase2=phase2,
        moderator=_make_moderator(
            seen=f"第 {idx+1} 轮 · 三方都在说…",
            limit=f"第 {idx+1} 轮 · 我不替你做决定",
        ) if with_moderator else None,
        moderator_thinking="",
        created_at=datetime.now(),
        completed_at=datetime.now(),
    )


def _make_session(
    rounds: list[RoundtableRoundSnapshot], *,
    question: str = "最近我们总是吵架，是我太敏感了吗？",
    personas: list[str] | None = None,
) -> RoundtableSession:
    personas = personas or ["neutral", "supportive", "eft"]
    now = datetime.now()
    return RoundtableSession(
        id="rt_memtest",
        personas=personas,  # type: ignore[arg-type]
        question=question,
        phase="phase1",
        rounds=rounds,
        round_index=len(rounds),
        created_at=now,
        updated_at=now,
    )


# ═════════════════════════════════════════════════════════════
# 空轮 / 单轮 / 多轮基础
# ═════════════════════════════════════════════════════════════


class TestBasic:
    def test_empty_rounds(self):
        session = _make_session(rounds=[])
        text, metrics = mem.build_memory_block(session, "neutral")
        assert text == ""
        assert metrics.round_count == 0
        assert metrics.kept_rounds == 0
        assert metrics.truncated is False

    def test_single_round_tier1_only(self):
        rounds = [_make_round(0, "第一轮问题")]
        session = _make_session(rounds=rounds)
        text, metrics = mem.build_memory_block(session, "neutral")

        assert metrics.round_count == 1
        assert metrics.kept_rounds == 1
        assert metrics.dropped_rounds == 0
        # Tier-1 固定标题
        assert "上一轮（第 1 轮）讨论回顾" in text
        # 包含 persona 自己那段
        assert "neutral" in text
        assert "Moderator" in text
        # 不该有 Tier-2 标题
        assert "更早一轮" not in text

    def test_two_rounds_tier1_and_tier2(self):
        rounds = [
            _make_round(0, "第 1 轮问题"),
            _make_round(1, "第 2 轮问题 · 更深"),
        ]
        session = _make_session(rounds=rounds)
        text, metrics = mem.build_memory_block(session, "neutral")

        assert metrics.round_count == 2
        assert metrics.kept_rounds == 2
        # 最近轮是 round_index=1 → label "第 2 轮"
        assert "上一轮（第 2 轮）" in text
        # Tier-2 标题（"第 1 轮"）
        assert "更早一轮（第 1 轮）" in text
        assert metrics.tier1_chars > 0
        assert metrics.tier2_chars > 0
        assert metrics.tier3_chars == 0

    def test_five_rounds_tier3_lifo(self):
        rounds = [_make_round(i, f"第 {i+1} 轮问题 · 内容") for i in range(5)]
        session = _make_session(rounds=rounds)
        text, metrics = mem.build_memory_block(session, "neutral")

        assert metrics.round_count == 5
        # Tier-1 (round 4) + Tier-2 (round 3) + Tier-3 (rounds 0,1,2)
        # 默认预算很宽松 → 应该全留住
        assert metrics.kept_rounds == 5
        assert metrics.tier3_rounds_kept == 3
        # 所有 round 标题都应出现
        for i in range(5):
            assert f"第 {i+1} 轮" in text


# ═════════════════════════════════════════════════════════════
# 预算压缩 / 截断
# ═════════════════════════════════════════════════════════════


class TestBudgetTruncation:
    def test_tight_budget_drops_tier3_first(self):
        # 5 轮 · 每轮 Tier-1 ~580，Tier-2 ~280，Tier-3 每轮 ~70
        long_text = "这是一段很长的自我观察" * 30  # 本身会被 T1_SELF=600 截断
        rounds = [
            _make_round(i, f"第 {i+1} 轮 · 问题更长的描述文字来占预算" * 3,
                        self_text_tpl=long_text + "_{k}")
            for i in range(5)
        ]
        session = _make_session(rounds=rounds)
        # 先跑一遍看真实 char_count 并把预算设在其之下
        text_full, metrics_full = mem.build_memory_block(session, "neutral")
        assert metrics_full.truncated is False
        assert metrics_full.char_count > 0
        # 扣掉 Tier-3 后理论能留下 Tier-1+Tier-2
        tight_budget = metrics_full.tier1_chars + metrics_full.tier2_chars + 10

        text, metrics = mem.build_memory_block(
            session, "neutral", char_budget=tight_budget,
        )
        assert metrics.truncated is True
        assert metrics.dropped_rounds >= 1
        # Tier-1 不会被丢
        assert "上一轮（第 5 轮）" in text
        # 若全部 Tier-3 都被丢，则第 1/2/3 轮 LIFO 标记不该在 Tier-3 段出现
        if metrics.tier3_rounds_kept == 0:
            assert "· [第 1 轮]" not in text
            assert "· [第 2 轮]" not in text

    def test_very_small_budget_keeps_only_tier1(self):
        # 用足够长的 question 让 Tier-1 单段就逼近预算下限（600），
        # 这样哪怕 budget 小于 Tier-1+Tier-2 组合也会触发 Step-D。
        long_q = "很长的问题描述用来充满字符预算测试压缩路径" * 8  # ~240 chars
        long_self = "非常详细的流派回应内容重复很多次以充满" * 20
        rounds = [
            _make_round(i, long_q, self_text_tpl=long_self + "_{k}")
            for i in range(4)
        ]
        session = _make_session(rounds=rounds)
        _, full = mem.build_memory_block(session, "neutral")
        # 预算刚好只够 Tier-1（≥ 600 下限）
        tier1_only_budget = max(full.tier1_chars + 5, 600)

        text, metrics = mem.build_memory_block(
            session, "neutral", char_budget=tier1_only_budget,
        )
        assert metrics.truncated is True
        assert metrics.kept_rounds == 1
        assert metrics.tier2_chars == 0
        assert metrics.tier3_chars == 0
        assert "上一轮" in text
        # 长度应严格 ≤ 预算 + 短裕度
        assert len(text) <= tier1_only_budget + 5

    def test_char_budget_floor(self):
        # 预算 < 600 会被抬到 600（允许 Tier-1 存活）· 但仍可能截断
        rounds = [_make_round(i, f"Q{i}") for i in range(3)]
        session = _make_session(rounds=rounds)
        text, _ = mem.build_memory_block(session, "neutral", char_budget=100)
        # 至少能输出 Tier-1 的标题
        assert "上一轮" in text


# ═════════════════════════════════════════════════════════════
# 容错
# ═════════════════════════════════════════════════════════════


class TestRobustness:
    def test_missing_moderator(self):
        rounds = [_make_round(0, "Q", with_moderator=False)]
        session = _make_session(rounds=rounds)
        text, metrics = mem.build_memory_block(session, "neutral")
        assert metrics.kept_rounds == 1
        # placeholder 不 raise
        assert "（本轮无记录）" in text

    def test_missing_self_phase2(self):
        # persona_id 不在 phase2 列表里 → self_text 走 placeholder
        rounds = [
            _make_round(0, "Q", personas=["supportive", "eft"]),  # 没有 neutral
        ]
        session = _make_session(rounds=rounds, personas=["neutral", "supportive", "eft"])
        text, metrics = mem.build_memory_block(session, "neutral")
        assert metrics.kept_rounds == 1
        assert "（本轮无记录）" in text

    def test_empty_question(self):
        # 问题空串 → placeholder
        snap = _make_round(0, "")
        session = _make_session(rounds=[snap])
        text, _ = mem.build_memory_block(session, "neutral")
        assert "（本轮无记录）" in text

    def test_very_long_fields_trimmed(self):
        """单个字段超长时应被截断（而不是失败）"""
        huge_q = "问" * 5000
        huge_self = "答" * 5000
        snap = _make_round(0, huge_q, self_text_tpl=huge_self + "_{k}")
        session = _make_session(rounds=[snap])
        text, metrics = mem.build_memory_block(session, "neutral")
        # Tier-1 question 段 ≤ 320 + 标题; self 段 ≤ 600
        assert "…" in text  # 说明有截断
        assert metrics.char_count < 4000


# ═════════════════════════════════════════════════════════════
# metrics
# ═════════════════════════════════════════════════════════════


class TestMetrics:
    def test_metrics_token_estimate(self):
        rounds = [_make_round(i, f"Q{i}") for i in range(3)]
        session = _make_session(rounds=rounds)
        text, metrics = mem.build_memory_block(session, "neutral")
        assert metrics.token_estimate > 0
        # char_count / 1.7 ≈ token_estimate · 允许 ±1 误差
        expected = int(round(metrics.char_count / 1.7))
        assert abs(metrics.token_estimate - expected) <= 1

    def test_metrics_to_dict(self):
        rounds = [_make_round(i, f"Q{i}") for i in range(2)]
        session = _make_session(rounds=rounds)
        _, metrics = mem.build_memory_block(session, "neutral")
        d = metrics.to_dict()
        # 必备字段
        for k in ("round_count", "kept_rounds", "dropped_rounds",
                  "char_count", "token_estimate", "truncated", "tier_breakdown"):
            assert k in d
        for k in ("tier1_chars", "tier2_chars", "tier3_chars", "tier3_rounds_kept"):
            assert k in d["tier_breakdown"]

    def test_metrics_char_count_matches_text(self):
        rounds = [_make_round(i, f"Q{i} 详细问题") for i in range(4)]
        session = _make_session(rounds=rounds)
        text, metrics = mem.build_memory_block(session, "neutral")
        assert metrics.char_count == len(text)


# ═════════════════════════════════════════════════════════════
# 不同 persona 隔离
# ═════════════════════════════════════════════════════════════


class TestPersonaIsolation:
    def test_different_personas_see_own_phase2(self):
        rounds = [_make_round(0, "Q")]
        session = _make_session(rounds=rounds)
        text_neutral, _ = mem.build_memory_block(session, "neutral")
        text_supportive, _ = mem.build_memory_block(session, "supportive")
        # 各自的立场关键字应该出现
        assert "立场=neutral" in text_neutral
        assert "立场=supportive" in text_supportive
        assert "立场=supportive" not in text_neutral


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
