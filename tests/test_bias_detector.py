"""
Day 4 · D4.7 · BiasDetector 单测 + 20 条偏见样本回归（对应 D5.2b）

覆盖：
- 5 类规则全部加载成功（gender_stereotype / relationship_absolutism /
  victim_blaming / moral_judgment / pathologizing_label）
- detect()：命中返回非空、未命中返回空
- sanitize()：命中 pattern 被替换为占位符
- sanitize() 不改写无偏见文本（0 rewrite）
- 类别按长度倒序：长 pattern 优先命中 · 避免子串吞字
- 跨类别多命中：同一条文本匹配多个 pattern
- 单例 · reset_default 后重建
- 20 条偏见样本回归（D5.2b）：召回率 100%（20/20）
- 20 条无偏见样本负例：误伤率 0%（0/20）
- 便捷函数 sanitize_output_bias / detect_output_bias
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.advisor.api.services.bias_detector import (  # noqa: E402
    BiasDetector,
    detect_output_bias,
    sanitize_output_bias,
)

REPLACEMENT = "（此处表述调整）"


@pytest.fixture(autouse=True)
def _reset_singleton():
    BiasDetector.reset_default()
    yield
    BiasDetector.reset_default()


# ═════════════════════════════════════════════════════════════
# 基本加载 + 类别结构
# ═════════════════════════════════════════════════════════════


class TestLoading:
    def test_five_categories_loaded(self):
        d = BiasDetector()
        assert set(d.categories) == {
            "gender_stereotype",
            "relationship_absolutism",
            "victim_blaming",
            "moral_judgment",
            "pathologizing_label",
        }

    def test_total_rule_count_around_60(self):
        d = BiasDetector()
        # 5 类 × 12 条 = 60 · 允许小幅波动（去重后可能 58-62）
        assert 55 <= d.rule_count <= 62, f"unexpected rule count: {d.rule_count}"

    def test_singleton_is_cached(self):
        a = BiasDetector.get_default()
        b = BiasDetector.get_default()
        assert a is b
        BiasDetector.reset_default()
        c = BiasDetector.get_default()
        assert a is not c


# ═════════════════════════════════════════════════════════════
# detect / sanitize 基本行为
# ═════════════════════════════════════════════════════════════


class TestDetect:
    def test_empty_and_clean_returns_empty_list(self):
        d = BiasDetector()
        assert d.detect("") == []
        assert d.detect("这是一段没有任何偏见的友善回复。") == []

    @pytest.mark.parametrize(
        "text, expected_category",
        [
            ("男人都不懂浪漫。", "gender_stereotype"),
            ("他一定会失败。", "relationship_absolutism"),
            ("这件事你活该。", "victim_blaming"),
            ("你很自私，根本不配。", "moral_judgment"),
            ("你就是巨婴。", "pathologizing_label"),
        ],
    )
    def test_category_hit(self, text, expected_category):
        d = BiasDetector()
        violations = d.detect(text)
        assert violations, f"应命中 · text={text!r}"
        cats = {v.category for v in violations}
        assert expected_category in cats


class TestSanitize:
    def test_clean_text_unchanged(self):
        d = BiasDetector()
        text = "我理解你的处境，也愿意一起想想下一步怎么办。"
        result = d.sanitize(text)
        assert result.text == text
        assert result.violations == []
        assert result.hit is False

    def test_hit_is_replaced(self):
        d = BiasDetector()
        text = "男人都这样，没办法。"
        result = d.sanitize(text)
        assert "男人都" not in result.text
        assert REPLACEMENT in result.text
        assert result.hit is True
        assert any(v.category == "gender_stereotype" for v in result.violations)

    def test_multi_category_hits(self):
        d = BiasDetector()
        text = "你活该，你就是巨婴，你很自私。"
        result = d.sanitize(text)
        cats = {v.category for v in result.violations}
        assert cats == {"victim_blaming", "pathologizing_label", "moral_judgment"}
        for bad in ("你活该", "你就是巨婴", "你很自私"):
            assert bad not in result.text

    def test_long_pattern_preferred_over_shorter_prefix(self):
        """长 pattern 先 replace · 避免被短 pattern 吞掉变成"不完整"替换"""
        d = BiasDetector()
        # "你有讨好型人格" 是 pathologizing · 长 pattern
        # 扫描顺序 flat 按长度倒序 · 先匹配长的
        text = "心理学上你有讨好型人格。"
        result = d.sanitize(text)
        assert "你有讨好型人格" not in result.text
        assert REPLACEMENT in result.text
        # 不应在结果中残留被切碎的碎片
        assert "讨好型" not in result.text


# ═════════════════════════════════════════════════════════════
# Audit context 传递（用 caplog 观察）
# ═════════════════════════════════════════════════════════════


class TestAuditLog:
    def test_hit_writes_info_log(self, caplog):
        d = BiasDetector()
        with caplog.at_level("INFO", logger="scripts.advisor.api.services.bias_detector"):
            d.sanitize(
                "你活该。",
                audit_context={"session_id": "s1", "persona_id": "neutral", "phase": "phase1"},
            )
        joined = "\n".join(r.getMessage() for r in caplog.records)
        assert "session=s1" in joined
        assert "persona=neutral" in joined
        assert "victim_blaming" in joined

    def test_no_log_when_no_hit(self, caplog):
        d = BiasDetector()
        with caplog.at_level("INFO", logger="scripts.advisor.api.services.bias_detector"):
            d.sanitize("今天天气不错。")
        hit_lines = [r for r in caplog.records if "[bias_detector] hit" in r.getMessage()]
        assert hit_lines == []


# ═════════════════════════════════════════════════════════════
# 20 条偏见样本回归（D5.2b）+ 20 条负例误伤率
# ═════════════════════════════════════════════════════════════

# ── 偏见样本集（20 条·5 类均覆盖） ────────────────────────
BIAS_CORPUS: list[tuple[str, str]] = [
    # gender_stereotype × 4
    ("男人都不回消息，你习惯就好。", "gender_stereotype"),
    ("女人都喜欢小心眼，你别太在意。", "gender_stereotype"),
    ("作为男人你就该主动。", "gender_stereotype"),
    ("女人天生就感性，这没办法。", "gender_stereotype"),
    # relationship_absolutism × 4
    ("你们这样注定失败。", "relationship_absolutism"),
    ("所有人都会背叛你。", "relationship_absolutism"),
    ("这种关系永远不会变好。", "relationship_absolutism"),
    ("他绝对不会理解你的。", "relationship_absolutism"),
    # victim_blaming × 4
    ("吵架你也有错，要先反省。", "victim_blaming"),
    ("这都是你的问题，别抱怨他。", "victim_blaming"),
    ("你咎由自取，能怪谁？", "victim_blaming"),
    ("你活该被这样对待。", "victim_blaming"),
    # moral_judgment × 4
    ("你真失败，这么点事都做不好。", "moral_judgment"),
    ("你太矫情了，别人怎么过的？", "moral_judgment"),
    ("你很自私，从来只想自己。", "moral_judgment"),
    ("你不配被人爱。", "moral_judgment"),
    # pathologizing_label × 4
    ("你就是巨婴，长不大。", "pathologizing_label"),
    ("你情商低才会这样。", "pathologizing_label"),
    ("你玻璃心，经不起一点话。", "pathologizing_label"),
    ("你是控制狂，难怪他受不了。", "pathologizing_label"),
]
assert len(BIAS_CORPUS) == 20

# ── 负例集（20 条·情绪/关系主题但不含偏见） ─────────────────
CLEAN_CORPUS: list[str] = [
    "我听到你说最近常常睡不着，你愿意多说几句吗？",
    "这件事让你很难受，这份感受是值得被看见的。",
    "我们可以先分开来看，事实是什么、你的解读是什么。",
    "如果今晚没有力气沟通，就先休息一下。",
    "你能把这件事说出来，本身就需要勇气。",
    "面对冲突，每个人都有自己节奏。",
    "有时候先照顾好自己，再去回应关系。",
    "你想先讲讲最近一周发生了什么吗？",
    "我可以陪你一起想想下一步怎么办。",
    "你提到的这种紧张，是很多伴侣都会遇到的。",
    "把边界表达清楚，并不是攻击对方。",
    "今晚先给自己一点空间，不一定马上做决定。",
    "这段关系让你觉得疲惫，你的感受是真实的。",
    "你可以尝试用'我觉得'开头而不是'你总是'。",
    "如果你愿意，我们可以一起列三个具体担心。",
    "他沉默不等于他不在乎，也可能是他也不知道怎么回应。",
    "你今天愿意告诉我这件事，我很高兴。",
    "感到不安是人之常情，不意味着你做错了什么。",
    "我们先做一件容易的事：写下今天的一个小情绪。",
    "下次有类似情况时，你希望自己怎样回应？",
]
assert len(CLEAN_CORPUS) == 20


class TestRegression20Samples:
    """D5.2b · 偏见样本 20 条 + 无偏见 20 条 回归"""

    @pytest.mark.parametrize("text, expected_cat", BIAS_CORPUS)
    def test_bias_samples_are_caught(self, text, expected_cat):
        d = BiasDetector()
        result = d.sanitize(text)
        assert result.hit, f"漏检 · text={text!r}"
        cats = {v.category for v in result.violations}
        assert expected_cat in cats, (
            f"类别错配 · expected={expected_cat} got={cats} · text={text!r}"
        )
        assert REPLACEMENT in result.text

    def test_recall_100_pct(self):
        """总体召回：20/20 都应命中"""
        d = BiasDetector()
        hits = sum(1 for text, _ in BIAS_CORPUS if d.detect(text))
        recall = hits / len(BIAS_CORPUS)
        assert recall == 1.0, f"recall={recall:.2f} · hits={hits}/{len(BIAS_CORPUS)}"

    @pytest.mark.parametrize("text", CLEAN_CORPUS)
    def test_clean_samples_not_flagged(self, text):
        d = BiasDetector()
        assert not d.detect(text), f"误伤 · text={text!r}"

    def test_false_positive_rate_zero(self):
        """20 条无偏见样本 · 误伤率 0%"""
        d = BiasDetector()
        fp = sum(1 for text in CLEAN_CORPUS if d.detect(text))
        fpr = fp / len(CLEAN_CORPUS)
        assert fpr == 0.0, f"fpr={fpr:.2f} · fp={fp}/{len(CLEAN_CORPUS)}"


# ═════════════════════════════════════════════════════════════
# 便捷函数
# ═════════════════════════════════════════════════════════════


class TestModuleShortcuts:
    def test_sanitize_output_bias_replaces(self):
        text = "你就是巨婴。"
        out = sanitize_output_bias(text)
        assert REPLACEMENT in out
        assert "你就是巨婴" not in out

    def test_detect_output_bias_returns_violations(self):
        v = detect_output_bias("你活该。")
        assert v and v[0].category == "victim_blaming"

    def test_sanitize_output_bias_idempotent_on_clean(self):
        text = "我理解你的难受，这很正常。"
        assert sanitize_output_bias(text) == text
