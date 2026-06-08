"""
Day 5 · D · Roundtable service 核心纯函数回归单测

覆盖（全部同步纯函数，不需要 asyncio）：
- `_extract_confidence`       · 从文本末尾抽 [置信度: 0.xx] / [confidence: 0.xx]
- `_strip_confidence_marker`  · 把末尾的标记从显示文本中移除
- `_build_rule_moderator`     · 规则 Moderator 按 phase2 confidence 降序排 angles

这些函数是 roundtable pipeline 的纯计算骨干，需要守住正则 + 排序稳定性。
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.advisor.api.core.models import (
    RoundtableAgentBuffer,
    RoundtableModeratorContent,
    RoundtableRoundSnapshot,
    RoundtableSession,
)
from scripts.advisor.api.services.roundtable_service import (  # noqa: E402
    PERSONA_NAMES,
    _build_moderator_prior_context_block,
    _build_prior_context_block,
    _build_rule_moderator,
    _extract_confidence,
    _parse_moderator_json,
    _split_moderator_output,
    _strip_confidence_marker,
    build_inject_preview,
    continue_session,
    create_session,
    get_session,
    list_sessions,
)


# ═══════════════════════════════════════════════════════════════════
# _extract_confidence
# ═══════════════════════════════════════════════════════════════════


class TestExtractConfidence:
    @pytest.mark.parametrize(
        "text, expected",
        [
            # 基本用法 · 中文关键字
            ("分析完毕。[置信度: 0.85]", 0.85),
            # 英文关键字
            ("Analysis done. [confidence: 0.72]", 0.72),
            # 全角冒号
            ("看完了。[置信度：0.90]", 0.90),
            # 不带方括号
            ("总结。置信度: 0.65", 0.65),
            # 多余空白
            ("最后.  [ 置信度  :   0.4 ]", 0.40),
            # 边界值 0 和 1
            ("[置信度: 0.0]", 0.0),
            ("[置信度: 1.0]", 1.0),
            # 两位小数 · 保留精度
            ("xxx[置信度: 0.77]", 0.77),
            # 大小写不敏感
            ("DONE [CONFIDENCE: 0.55]", 0.55),
        ],
    )
    def test_valid_extractions(self, text, expected):
        assert _extract_confidence(text) == pytest.approx(expected)

    def test_empty_string(self):
        assert _extract_confidence("") is None

    def test_none_match_plain_text(self):
        assert _extract_confidence("这段文字完全不涉及任何置信度标记") is None

    def test_out_of_range_above_one(self):
        """超出 [0, 1] 范围返回 None（正则允许但函数过滤）"""
        # 正则支持 [01]\.\d+ → 1.5 不匹配；但 1.9 匹配的是 1.9... 需要走超限分支
        # 实际正则是 [01](?:\.\d+)? 所以 1.9 会匹配到 "1.9"（首字符 1），但 float 校验在 0-1
        assert _extract_confidence("[置信度: 1.5]") is None

    def test_last_match_wins(self):
        """多个匹配时取最后一个（避免 agent 在正文中误提「置信度」）"""
        text = (
            "前文提到置信度 0.3 只是随口说的，\n"
            "结尾给最终 [置信度: 0.88]"
        )
        assert _extract_confidence(text) == pytest.approx(0.88)

    def test_rounds_to_two_decimals(self):
        """float 抽出后 round 到 2 位"""
        # 正则匹配 .\d+ 所以 0.777 也能匹配
        result = _extract_confidence("[置信度: 0.777]")
        assert result == pytest.approx(0.78)


# ═══════════════════════════════════════════════════════════════════
# _strip_confidence_marker
# ═══════════════════════════════════════════════════════════════════


class TestStripConfidenceMarker:
    def test_basic_strip(self):
        text = "第一行分析。\n第二行总结。\n[置信度: 0.82]"
        cleaned = _strip_confidence_marker(text)
        assert "[置信度" not in cleaned
        assert cleaned.endswith("总结。")

    def test_no_marker_returns_unchanged(self):
        text = "没有标记的纯正文"
        assert _strip_confidence_marker(text) == text

    def test_empty_string(self):
        assert _strip_confidence_marker("") == ""

    def test_only_strips_last_marker(self):
        """多个标记时只裁最后一个（前面提到的保留）"""
        text = "前面随口说的置信度 0.5，这里只是正文。结尾 [置信度: 0.92]"
        cleaned = _strip_confidence_marker(text)
        # 最后一个被删
        assert "[置信度: 0.92]" not in cleaned
        # 但前文被保留
        assert "随口说的置信度 0.5" in cleaned

    def test_strips_trailing_whitespace(self):
        """标记前的空白/换行也一并清理"""
        text = "正文\n\n\n   [置信度: 0.7]"
        cleaned = _strip_confidence_marker(text)
        assert cleaned == "正文"

    def test_english_variant(self):
        text = "Some analysis.\n[confidence: 0.65]"
        cleaned = _strip_confidence_marker(text)
        assert "[confidence" not in cleaned.lower()
        assert cleaned.startswith("Some analysis")


# ═══════════════════════════════════════════════════════════════════
# _build_rule_moderator · 置信度降序 + angles 正确挂载
# ═══════════════════════════════════════════════════════════════════


def _make_session(
    personas: list[str],
    phase2_confidences: list[float | None],
    question: str = "这是一条用于单测的长问题文本以满足 Pydantic 的最小长度校验。",
) -> RoundtableSession:
    """构造一个填好 phase2 confidence 的 session"""
    assert len(personas) == 3
    assert len(phase2_confidences) == 3
    now = datetime.now()
    return RoundtableSession(
        id="rt_test_session",
        personas=personas,
        question=question,
        phase="done",
        phase1=[RoundtableAgentBuffer(persona_id=p, status="done") for p in personas],
        phase2=[
            RoundtableAgentBuffer(
                persona_id=p,
                status="done",
                confidence=c,
            )
            for p, c in zip(personas, phase2_confidences)
        ],
        moderator=None,
        created_at=now,
        updated_at=now,
    )


class TestBuildRuleModerator:
    def test_angles_descending_by_confidence(self):
        """phase2 confidence 降序：最高者出现在 angles[0]"""
        session = _make_session(
            personas=["neutral", "bowen", "eft"],
            phase2_confidences=[0.70, 0.95, 0.80],
        )
        content = _build_rule_moderator(session)
        # bowen 最高 · 第一
        assert PERSONA_NAMES["bowen"] in content.angles[0]
        # eft 次之 · 第二
        assert PERSONA_NAMES["eft"] in content.angles[1]
        # neutral 最低 · 第三
        assert PERSONA_NAMES["neutral"] in content.angles[2]

    def test_angles_count_matches_personas(self):
        session = _make_session(
            personas=["neutral", "psychoanalytic", "sociology"],
            phase2_confidences=[0.8, 0.8, 0.8],
        )
        content = _build_rule_moderator(session)
        assert len(content.angles) == 3

    def test_missing_confidence_defaults_to_075(self):
        """confidence=None 时用 0.75 默认，不炸"""
        session = _make_session(
            personas=["neutral", "bowen", "eft"],
            phase2_confidences=[None, 0.95, None],
        )
        content = _build_rule_moderator(session)
        # 不抛异常即为通过
        assert len(content.angles) == 3
        # bowen 0.95 应该排第一
        assert PERSONA_NAMES["bowen"] in content.angles[0]

    def test_all_personas_represented(self):
        """angles 里每个 persona 都出现且只出现一次"""
        personas = ["neutral", "bowen", "game_theory"]
        session = _make_session(
            personas=personas,
            phase2_confidences=[0.6, 0.7, 0.8],
        )
        content = _build_rule_moderator(session)
        joined = "\n".join(content.angles)
        for pid in personas:
            name = PERSONA_NAMES[pid]
            assert joined.count(name) == 1, f"{name} 应当出现恰好 1 次"

    def test_confidence_appears_in_angle_text(self):
        """每条 angle 末尾的「自评 0.xx」应当等于 persona 的实际 confidence"""
        session = _make_session(
            personas=["neutral", "bowen", "eft"],
            phase2_confidences=[0.70, 0.95, 0.80],
        )
        content = _build_rule_moderator(session)
        # bowen 0.95 应该出现在第一条
        assert "0.95" in content.angles[0]
        assert "0.80" in content.angles[1]
        assert "0.70" in content.angles[2]

    def test_content_shape_has_required_fields(self):
        """返回的 RoundtableModeratorContent 必须填满 6 个字段"""
        session = _make_session(
            personas=["neutral", "bowen", "eft"],
            phase2_confidences=[0.8, 0.8, 0.8],
        )
        content = _build_rule_moderator(session)
        assert content.seen
        assert content.angles
        assert content.tries and len(content.tries) >= 3
        assert content.doubts and len(content.doubts) >= 2
        assert content.lens
        assert content.limit
        # limit 必须含危机热线（伦理合规）
        assert "400-161-9995" in content.limit


# ═══════════════════════════════════════════════════════════════════
# Day 7 · D7.1.j+ · _build_rule_moderator 跨轮记忆承接（降级路径）
# 修复「Moderator LLM 失败 → 规则模板 → 第 2/N 轮看起来无记忆」的体验落差。
# 仅这一组 6 个测试覆盖：首轮兼容 / 二轮承接 / 多轮 round_n / 上轮 moderator 缺失兜底
# ═══════════════════════════════════════════════════════════════════


def _make_round_snapshot(
    *,
    round_index: int,
    question: str,
    moderator: RoundtableModeratorContent | None,
    personas: list[str] = ("neutral", "bowen", "eft"),  # type: ignore[assignment]
) -> RoundtableRoundSnapshot:
    """构造一个 RoundtableRoundSnapshot 用于 session.rounds[]"""
    now = datetime.now()
    return RoundtableRoundSnapshot(
        round_index=round_index,
        question=question,
        phase1=[RoundtableAgentBuffer(persona_id=p, status="done") for p in personas],
        phase2=[RoundtableAgentBuffer(persona_id=p, status="done") for p in personas],
        moderator=moderator,
        moderator_thinking="",
        created_at=now,
        completed_at=now,
    )


def _make_prior_moderator(
    *,
    seen: str = "上轮我们一起看到的事。",
    lens: str = "上一轮的核心 lens：你不孤单。",
    tries: list[str] | None = None,
    doubts: list[str] | None = None,
) -> RoundtableModeratorContent:
    return RoundtableModeratorContent(
        seen=seen,
        angles=["x（自评 0.80）；", "y（自评 0.75）；", "z（自评 0.70）；"],
        tries=tries or ["上轮 try 第一条 · 写下三句话", "上轮 try 第二条", "上轮 try 第三条"],
        doubts=doubts or ["上轮 doubt 第一条 · 你最害怕的是什么", "上轮 doubt 第二条"],
        lens=lens,
        limit="Lens 圆桌讨论是非诊断性的探索工具…400-161-9995。",
    )


class TestBuildRuleModeratorWithMemory:
    """跨轮记忆 · 仅当 session.rounds 非空时启用承接段"""

    def test_first_round_keeps_legacy_template(self):
        """首轮（rounds=[]） · 输出与 Day 4 旧模板兼容（关键固定文案保留）"""
        session = _make_session(
            personas=["neutral", "bowen", "eft"],
            phase2_confidences=[0.8, 0.8, 0.8],
        )
        # rounds 默认为空
        assert session.rounds == []
        content = _build_rule_moderator(session)
        # 首轮固定 try 文案应保留
        assert any("先写下三句话" in t for t in content.tries)
        # 首轮 lens 应是「你不是一个人在面对这件事」
        assert "你不是一个人在面对这件事" in content.lens
        # 首轮 seen 不应包含「第 N 轮」承接语
        assert "上一轮" not in content.seen
        assert "第 1 轮陪伴" not in content.lens

    def test_second_round_has_continuation_in_seen(self):
        """二轮：seen 应同时包含「上一轮」+ 上轮 question + 当前 question"""
        prior = _make_prior_moderator()
        snap = _make_round_snapshot(
            round_index=0,
            question="上一轮我和女友因为家务分工吵架的事",
            moderator=prior,
        )
        session = _make_session(
            personas=["neutral", "bowen", "eft"],
            phase2_confidences=[0.8, 0.8, 0.8],
            question="这次又升级了 · 她说我连她加班都不在乎",
        )
        session.rounds = [snap]
        session.round_index = 1

        content = _build_rule_moderator(session)
        assert "上一轮" in content.seen
        assert "家务分工" in content.seen  # 上轮 question 被嵌入
        assert "她说我连她加班都不在乎" in content.seen  # 当前 question 被嵌入
        # angles 仍按 confidence 排序（沿用基础逻辑）
        assert len(content.angles) == 3

    def test_second_round_tries_carry_prior_first_try(self):
        """二轮 · tries[0] 应承接上轮 tries[0]（"先试一下" 句式）"""
        prior = _make_prior_moderator(
            tries=["试着每周拿出 30 分钟做一次仪式化对话", "上轮第二条", "上轮第三条"],
        )
        snap = _make_round_snapshot(
            round_index=0, question="上轮 q", moderator=prior,
        )
        session = _make_session(
            personas=["neutral", "bowen", "eft"],
            phase2_confidences=[0.8, 0.8, 0.8],
        )
        session.rounds = [snap]
        session.round_index = 1

        content = _build_rule_moderator(session)
        # 上轮第一条 try 摘要应被引用
        assert "每周拿出 30 分钟" in content.tries[0]
        assert "上轮我们建议过" in content.tries[0]

    def test_second_round_doubts_carry_prior_first_doubt(self):
        prior = _make_prior_moderator(
            doubts=["你内心是否在害怕被她真正看穿？", "上轮 doubt 2"],
        )
        snap = _make_round_snapshot(
            round_index=0, question="上轮 q", moderator=prior,
        )
        session = _make_session(
            personas=["neutral", "bowen", "eft"],
            phase2_confidences=[0.8, 0.8, 0.8],
        )
        session.rounds = [snap]
        session.round_index = 1

        content = _build_rule_moderator(session)
        assert "上轮我们一起留下过这个问题" in content.doubts[0]
        assert "你内心是否在害怕被她真正看穿" in content.doubts[0]

    def test_lens_shows_round_n_and_prior_lens(self):
        prior = _make_prior_moderator(lens="你回到这里就是力量")
        snap = _make_round_snapshot(
            round_index=0, question="上轮 q", moderator=prior,
        )
        session = _make_session(
            personas=["neutral", "bowen", "eft"],
            phase2_confidences=[0.8, 0.8, 0.8],
        )
        session.rounds = [snap]
        session.round_index = 1

        content = _build_rule_moderator(session)
        # 第 2 轮陪伴
        assert "第 2 轮陪伴" in content.lens
        # 上轮 lens 摘要应被嵌入
        assert "你回到这里就是力量" in content.lens

    def test_third_round_shows_round_3(self):
        """三轮 · lens 显示「第 3 轮陪伴」 · seen 引用最近一轮（第 2 轮）"""
        snap1 = _make_round_snapshot(
            round_index=0, question="第 1 轮 q", moderator=_make_prior_moderator(),
        )
        snap2 = _make_round_snapshot(
            round_index=1,
            question="第 2 轮 q · 关于她加班的争吵",
            moderator=_make_prior_moderator(lens="第 2 轮 lens 内容"),
        )
        session = _make_session(
            personas=["neutral", "bowen", "eft"],
            phase2_confidences=[0.8, 0.8, 0.8],
            question="第 3 轮 q · 她终于说话了",
        )
        session.rounds = [snap1, snap2]
        session.round_index = 2

        content = _build_rule_moderator(session)
        # 应承接最近一轮（snap2）
        assert "她加班的争吵" in content.seen
        assert "第 2 轮" in content.seen  # 上轮编号
        assert "第 3 轮陪伴" in content.lens
        assert "第 2 轮 lens 内容" in content.lens

    def test_continuation_with_missing_prior_moderator_falls_back_gracefully(self):
        """二轮但上轮 moderator=None（极端 · 上轮也降级失败）· 仍应输出合理内容不崩"""
        snap = _make_round_snapshot(
            round_index=0, question="上轮 q · 残缺记录", moderator=None,
        )
        session = _make_session(
            personas=["neutral", "bowen", "eft"],
            phase2_confidences=[0.8, 0.8, 0.8],
        )
        session.rounds = [snap]
        session.round_index = 1

        content = _build_rule_moderator(session)
        # 不抛 · 仍含「第 2 轮陪伴」
        assert "第 2 轮陪伴" in content.lens
        # tries 应至少 3 条（fallback 文案）
        assert len(content.tries) >= 3
        # doubts 至少 2 条（fallback 文案）
        assert len(content.doubts) >= 2
        # seen 仍引用上轮 question 摘要
        assert "残缺记录" in content.seen

    def test_continuation_keeps_limit_immutable(self):
        """无论第几轮 · limit 必须保留危机热线 · 不被改写"""
        prior = _make_prior_moderator()
        snap = _make_round_snapshot(round_index=0, question="x", moderator=prior)
        session = _make_session(
            personas=["neutral", "bowen", "eft"],
            phase2_confidences=[0.8, 0.8, 0.8],
        )
        session.rounds = [snap]
        session.round_index = 1
        content = _build_rule_moderator(session)
        assert "400-161-9995" in content.limit


# ═══════════════════════════════════════════════════════════════════
# 联合测试：extract + strip 的端到端协作
# ═══════════════════════════════════════════════════════════════════


class TestExtractStripIntegration:
    def test_extract_then_strip_roundtrip(self):
        """一段 agent 输出，抽 confidence 之后剥离，显示文本不再含标记"""
        raw = "完整的 phase2 分析正文\n\n[置信度: 0.83]"
        conf = _extract_confidence(raw)
        cleaned = _strip_confidence_marker(raw)
        assert conf == pytest.approx(0.83)
        assert "[置信度" not in cleaned
        assert cleaned == "完整的 phase2 分析正文"


# ═══════════════════════════════════════════════════════════════════
# _parse_moderator_json · LLM Moderator JSON 解析容错（Day 5 · C）
# ═══════════════════════════════════════════════════════════════════


def _valid_json_payload() -> str:
    """构造一份合法的 6 段 Moderator JSON（用于测试容错 wrapper）"""
    return (
        '{\n'
        '  "seen": "我看到你此刻在去外地读书与前女友关系之间的拉扯，这份两难是真实的。",\n'
        '  "angles": [\n'
        '    "EFT 看到你与她之间未被命名的依恋需求",\n'
        '    "中立顾问看到你需要把事实与情绪分开",\n'
        '    "Bowen 看到原生家庭对亲密选择的影响"\n'
        '  ],\n'
        '  "tries": [\n'
        '    "今晚花 30 分钟写下你希望这段关系以什么姿态结束",\n'
        '    "给自己设一个 48 小时的情绪缓冲区，不急着做决定",\n'
        '    "如果要回应她，先用一句承认她的感受再表达你的立场"\n'
        '  ],\n'
        '  "doubts": [\n'
        '    "你真正想安慰的是她，还是还没准备好和这段关系告别的自己？",\n'
        '    "去外地读书这个决定本身里，有没有更早的某种逃离的影子？"\n'
        '  ],\n'
        '  "lens": "分手后还想安慰对方是柔软的，但你也需要允许自己有边界。",\n'
        '  "limit": "Lens 圆桌讨论是非诊断性的探索工具。如果你正在经历严重情绪困扰，请拨打 400-161-9995。"\n'
        '}'
    )


class TestParseModeratorJson:
    def test_pure_json_happy_path(self):
        """纯 JSON · 所有字段齐全"""
        content = _parse_moderator_json(_valid_json_payload())
        assert content is not None
        assert "两难" in content.seen
        assert len(content.angles) == 3
        assert len(content.tries) == 3
        assert len(content.doubts) == 2
        assert "400-161-9995" in content.limit

    def test_wrapped_with_markdown_json_fence(self):
        """LLM 常见错误：用 ```json ... ``` 围栏"""
        payload = f"```json\n{_valid_json_payload()}\n```"
        content = _parse_moderator_json(payload)
        assert content is not None
        assert len(content.angles) == 3

    def test_wrapped_with_bare_fence(self):
        """无 json 标签的 ``` ... ``` 围栏"""
        payload = f"```\n{_valid_json_payload()}\n```"
        content = _parse_moderator_json(payload)
        assert content is not None

    def test_preceded_by_explanation_text(self):
        """前面有多余说明文字 · 应能裁到 {} 范围"""
        payload = f"好的，我来生成 Moderator 综合：\n\n{_valid_json_payload()}\n\n希望有帮助。"
        content = _parse_moderator_json(payload)
        assert content is not None
        assert len(content.tries) == 3

    def test_empty_string_returns_none(self):
        assert _parse_moderator_json("") is None

    def test_invalid_json_syntax_returns_none(self):
        """语法错的 JSON → None（上层 fallback）"""
        assert _parse_moderator_json("{not a valid json") is None

    def test_missing_required_key_returns_none(self):
        """缺 tries 字段 → None"""
        bad = (
            '{"seen":"s","angles":["a","b"],"doubts":["d"],'
            '"lens":"l","limit":"L"}'
        )
        assert _parse_moderator_json(bad) is None

    def test_angles_too_few_returns_none(self):
        """angles 只有 1 条 → None（至少 2 条）"""
        bad = (
            '{"seen":"s","angles":["a"],"tries":["t1","t2"],'
            '"doubts":["d1","d2"],"lens":"l","limit":"L"}'
        )
        assert _parse_moderator_json(bad) is None

    def test_doubts_empty_returns_none(self):
        """doubts 为空数组 → None"""
        bad = (
            '{"seen":"s","angles":["a1","a2"],"tries":["t1","t2"],'
            '"doubts":[],"lens":"l","limit":"L"}'
        )
        assert _parse_moderator_json(bad) is None

    def test_non_dict_top_level_returns_none(self):
        """LLM 返回数组而非对象 → None"""
        assert _parse_moderator_json("[1, 2, 3]") is None

    def test_null_input(self):
        """None 输入不炸"""
        assert _parse_moderator_json(None) is None  # type: ignore[arg-type]


# ═══════════════════════════════════════════════════════════════════
# _split_moderator_output · 两段式拆分（Day 5 方案① · 流式思考）
# ═══════════════════════════════════════════════════════════════════


class TestSplitModeratorOutput:
    def test_ideal_separator_format(self):
        """理想情况 · 有 ---JSON--- 分隔符"""
        raw = (
            "【综合思考】\n"
            "我看到三位顾问都指向同一件事：你需要先被看见。\n"
            "---JSON---\n"
            '{"seen":"xxx","angles":["a1","a2","a3"]}'
        )
        thinking, json_str = _split_moderator_output(raw)
        assert "三位顾问" in thinking
        assert "【综合思考】" not in thinking  # header 被剥掉
        assert json_str.startswith("{") and "seen" in json_str

    def test_no_separator_falls_back_to_brace_split(self):
        """无分隔符 · 退化到寻找第一个 { 拆分"""
        raw = (
            "我先整理一下三位顾问的观点…两人都指向一个张力。\n\n"
            '{"seen":"xxx"}'
        )
        thinking, json_str = _split_moderator_output(raw)
        assert "三位顾问" in thinking
        assert json_str == '{"seen":"xxx"}'

    def test_pure_json_no_thinking(self):
        """LLM 没按两段式 · 直接输出 JSON"""
        raw = '{"seen":"xxx","angles":["a","b"]}'
        thinking, json_str = _split_moderator_output(raw)
        assert thinking == ""
        assert json_str == raw

    def test_header_stripped_multiple_variants(self):
        """【思考】/【Thinking】/### 思考 等多种 header 都应剥掉"""
        for header in ("【思考】", "【综合思考】", "【Thinking】", "# 综合思考", "## 思考"):
            raw = f"{header}\n正文开始\n---JSON---\n{{}}"
            thinking, _ = _split_moderator_output(raw)
            assert thinking.startswith("正文开始"), f"header '{header}' 未剥掉 · got: {thinking!r}"

    def test_empty_input(self):
        assert _split_moderator_output("") == ("", "")

    def test_separator_at_start(self):
        """分隔符在最前 · thinking 应为空"""
        raw = '---JSON---\n{"seen":"x"}'
        thinking, json_str = _split_moderator_output(raw)
        assert thinking == ""
        assert json_str == '{"seen":"x"}'

    def test_only_thinking_no_json(self):
        """只有思考没 JSON · thinking 不丢，json 为空（上层 fallback）"""
        raw = "只是一段闲聊，没有 JSON"
        thinking, json_str = _split_moderator_output(raw)
        assert thinking == "只是一段闲聊，没有 JSON"
        assert json_str == ""

    def test_whitespace_around_separator(self):
        """分隔符前后多余空白 · 拆分后应已 strip"""
        raw = "思考正文   \n\n---JSON---\n\n   {\"k\":1}  "
        thinking, json_str = _split_moderator_output(raw)
        assert thinking == "思考正文"
        assert json_str == '{"k":1}'


# ═══════════════════════════════════════════════════════════════════
# Day 6 · 多轮对话形态 A · prior context block + continue_session
# ═══════════════════════════════════════════════════════════════════


def _mk_session(personas=("neutral", "supportive", "eft"), question="测试问题：我们为什么老吵架？"):
    """helper · 创建真实 session（会走 create_session 注册到 _sessions）"""
    return create_session(personas=list(personas), question=question)


def _complete_session_as_done(session_id: str) -> RoundtableSession:
    """helper · 把 session 手工填到 done 状态，以便测试 continue_session"""
    s = get_session(session_id)
    assert s is not None
    # 填 phase1 / phase2 agent 文本
    for buf in s.phase1:
        buf.status = "done"
        buf.text = f"{buf.persona_id} phase1 内容"
        buf.confidence = 0.75
    for buf in s.phase2:
        buf.status = "done"
        buf.text = f"{buf.persona_id} phase2 交叉回应"
        buf.confidence = 0.80
    # 填 moderator
    s.moderator = RoundtableModeratorContent(
        seen="我看到你承担了很多情绪。",
        angles=["中立顾问：拆开事实与解读", "支持性顾问：先接住情绪", "EFT：识别依恋需求"],
        tries=["今晚先别做决定", "用邀请而非质问开启对话", "给自己 1 小时写日记"],
        doubts=["他是否愿意回应？", "是否还有未说的细节？"],
        lens="你不是一个人在面对这件事。",
        limit="非诊断性工具，不替代专业咨询。",
    )
    s.moderator_thinking = "综合来看，三位顾问对核心需求有一致判断。"
    s.phase = "done"
    return s


class TestBuildPriorContextBlock:
    def test_empty_when_no_rounds_and_no_inject(self):
        """首轮、无注入 · 返回空串"""
        s = _mk_session()
        assert _build_prior_context_block(s, "neutral") == ""

    def test_has_prior_round_renders_header(self):
        """有历史轮 · 返回包含上一轮回顾的字符串"""
        s = _mk_session()
        _complete_session_as_done(s.id)
        # 归档当前轮 → 进入第 2 轮
        continue_session(s.id, question="追问：如果他还是不说话怎么办？")
        # 此时 session.rounds 有 1 条 snapshot（第 1 轮），s.round_index=1
        s_after = get_session(s.id)
        assert s_after is not None
        assert len(s_after.rounds) == 1
        block = _build_prior_context_block(s_after, "neutral")
        assert block  # 非空
        # D4.8 · CrossRoundMemory 新标题：上一轮（第 N 轮）讨论回顾
        assert "讨论回顾" in block
        assert "第 1 轮" in block  # 1-based 显示
        assert "neutral phase2 交叉回应" in block  # 本 persona 的上轮 phase2 入注
        assert "我看到你承担了很多情绪" in block  # 上一轮 moderator.seen

    def test_inject_context_appended(self):
        """注入 context · 应出现在返回的 block 中"""
        s = _mk_session()
        _complete_session_as_done(s.id)
        continue_session(
            s.id,
            question="本轮追问内容。",
            inject_context="【相关历史对话片段】\n片段 1：…你们在第 102 天争吵…",
        )
        s_after = get_session(s.id)
        assert s_after is not None
        block = _build_prior_context_block(s_after, "neutral")
        assert "用户追加注入的参考资料" in block
        assert "第 102 天" in block
        assert "不要原样引用或暴露" in block  # 自律提示在
        # 两部分都应存在（D4.8 · 标题改为「上一轮（第 N 轮）讨论回顾」）
        assert "讨论回顾" in block

    def test_inject_only_no_history(self):
        """首轮直接有注入（理论场景：首次讨论也允许）"""
        s = _mk_session()
        s.current_inject_context = "【专业知识手册】\nQ: 什么是依恋？\nA: 依恋是一种情感连接。"
        block = _build_prior_context_block(s, "neutral")
        assert "依恋是一种情感连接" in block
        assert "讨论回顾" not in block  # 无 rounds，这段不出现

    def test_inject_truncated_at_12k(self):
        """超过 12000 字符的注入应被截断"""
        s = _mk_session()
        s.current_inject_context = "长" * 13000
        block = _build_prior_context_block(s, "neutral")
        # 应看到截断标记
        assert "…" in block
        # 且整体 block 不超过 ~12100（为"长"序列 + 提示文本 + 封装段）
        assert len(block) < 12500


class TestBuildModeratorPriorContextBlock:
    """Day 7 · 修复"Moderator 追问失忆"bug · Moderator 视角的历史轮回顾块。"""

    def test_empty_when_no_rounds(self):
        """首轮 · 无 rounds · 返回空串（不打破模板结构）"""
        s = _mk_session()
        assert _build_moderator_prior_context_block(s) == ""

    def test_includes_last_round_moderator_content(self):
        """第 2 轮 · 块里应出现上一轮 Moderator 的 seen/angles/lens + 用户当时问的"""
        s = _mk_session(question="我和他经常冷战，不知道怎么开口。")
        _complete_session_as_done(s.id)
        continue_session(s.id, question="追问：他昨晚终于回我消息了，我该怎么回？")
        s_after = get_session(s.id)
        assert s_after is not None
        assert len(s_after.rounds) == 1

        block = _build_moderator_prior_context_block(s_after)
        assert block
        assert "你对该用户说过的话" in block
        assert "第 1 轮" in block  # 1-based 显示
        # 上一轮用户问的（完整或截断后的前缀）
        assert "冷战" in block
        # 上一轮 Moderator 的 seen（来自 _complete_session_as_done）
        assert "承担了很多情绪" in block
        # angles 里的关键词之一应出现
        assert "EFT" in block or "依恋" in block
        # lens 里的关键词
        assert "不是一个人" in block
        # 指令让本轮 Moderator 换措辞、承接新细节
        assert "不要重复" in block
        assert "承接" in block

    def test_older_rounds_summarized_in_tier2(self):
        """≥ 3 轮 · 最早的轮只保留一行「第 k 轮 · 问 → 说」摘要"""
        s = _mk_session(question="第 1 轮问题：最初的冲突。")
        _complete_session_as_done(s.id)
        continue_session(s.id, question="第 2 轮问题：进展如何应对。")
        # 把第 2 轮也推到 done 方便归档
        _complete_session_as_done(s.id)
        continue_session(s.id, question="第 3 轮问题：新细节出现了。")

        s_after = get_session(s.id)
        assert s_after is not None
        assert len(s_after.rounds) == 2  # rounds 里有前两轮 snapshot

        block = _build_moderator_prior_context_block(s_after)
        # Tier-1 · 最近一轮（第 2 轮）在
        assert "第 2 轮" in block
        assert "你对该用户说过的话" in block
        # Tier-2 · 更早一轮（第 1 轮）以一行摘要出现
        assert "更早的历史轮" in block
        assert "第 1 轮" in block

    def test_max_chars_budget_truncates(self):
        """整块超 max_chars 时应被兜底截断"""
        s = _mk_session()
        _complete_session_as_done(s.id)
        continue_session(s.id, question="新一轮")
        s_after = get_session(s.id)
        assert s_after is not None
        # 人为把上一轮 moderator 字段撑大
        s_after.rounds[0].moderator = RoundtableModeratorContent(
            seen="特" * 600,
            angles=["甲" * 200, "乙" * 200, "丙" * 200],
            tries=["x", "y", "z"],
            doubts=["a", "b"],
            lens="念" * 300,
            limit="limit...",
        )
        block = _build_moderator_prior_context_block(s_after, max_chars=500)
        assert len(block) <= 520  # 允许 +\n 的尾巴
        assert "…" in block  # 截断标记


class TestContinueSession:
    def test_continue_archives_current_round(self):
        """continue · 当前轮 snapshot 进 rounds，新轮重置为 setup"""
        s = _mk_session()
        _complete_session_as_done(s.id)
        assert s.round_index == 0
        continue_session(s.id, question="追问：我该怎么办？")
        s_after = get_session(s.id)
        assert s_after is not None
        assert len(s_after.rounds) == 1
        snap = s_after.rounds[0]
        assert snap.round_index == 0
        assert snap.question == "测试问题：我们为什么老吵架？"
        # 当前轮已重置
        assert s_after.round_index == 1
        assert s_after.phase == "setup"
        assert s_after.question == "追问：我该怎么办？"
        assert s_after.moderator is None
        assert s_after.moderator_thinking == ""
        # phase1/phase2 新初始化为 pending
        assert all(b.status == "pending" for b in s_after.phase1)
        assert all(b.status == "pending" for b in s_after.phase2)

    def test_continue_rejects_when_not_done(self):
        """非 done 状态调 continue · 应抛 ValueError"""
        s = _mk_session()
        # 默认 phase=setup
        with pytest.raises(ValueError, match="not done"):
            continue_session(s.id, question="硬要追问")

    def test_continue_missing_session_raises_keyerror(self):
        with pytest.raises(KeyError, match="not found"):
            continue_session("rt_does_not_exist", question="追问")

    def test_continue_stores_inject_context(self):
        s = _mk_session()
        _complete_session_as_done(s.id)
        continue_session(
            s.id,
            question="追问",
            inject_context="  【手册】Q: 共情是什么？A: ...\n  ",
        )
        s_after = get_session(s.id)
        assert s_after is not None
        # 末尾 whitespace 被 strip
        assert s_after.current_inject_context.startswith("【手册】")
        assert not s_after.current_inject_context.endswith(" ")

    def test_continue_none_inject_clears_previous(self):
        """本轮不传 inject_context · 会被重置为空串（不保留上轮）"""
        s = _mk_session()
        _complete_session_as_done(s.id)
        continue_session(s.id, question="Q2", inject_context="old ctx")
        _complete_session_as_done(s.id)
        continue_session(s.id, question="Q3")  # 不传 inject
        s_after = get_session(s.id)
        assert s_after is not None
        assert s_after.current_inject_context == ""


class TestBuildInjectPreview:
    def test_empty_environment_returns_empty_lists(self):
        """无 RAG 数据环境下 · 应返回空结构而不是崩"""
        result = build_inject_preview(query="如何处理冲突", modes=["chat_history", "knowledge"])
        assert set(result.keys()) == {"chat_history", "knowledge", "suggested_context"}
        assert isinstance(result["chat_history"], list)
        assert isinstance(result["knowledge"], list)
        assert isinstance(result["suggested_context"], str)

    def test_modes_filter_respected(self):
        """仅查 knowledge · chat_history 列表应为空"""
        result = build_inject_preview(query="如何共情", modes=["knowledge"])
        assert result["chat_history"] == []

    def test_suggested_context_has_sections_when_hits(self, monkeypatch):
        """mock enriched_search / search_faq 返回命中 · 验证 suggested_context 格式"""
        from scripts.advisor.api.services import roundtable_service as rs

        fake_chat = [
            {
                "conv": {
                    "conversation_text": "ME: 他又没回我消息。OTHER: 我只是忙。" * 5,
                    "metadata": {"chunk_id": "c1"},
                    "conversation_id": "c1",
                },
                "enriched": {
                    "chunk_id": "c1", "days": [102, 103], "chunk_type": "conflict",
                    "analysis": {"conflict_root_causes": ["沟通不足"]},
                },
                "score": 0.85,
            },
        ]
        fake_faq = [
            {"category": "psychology", "question": "什么是共情？", "answer": "能感受他人情绪。", "keywords": ["共情"]},
        ]

        def _fake_rag():
            class _Stub:
                @staticmethod
                def enriched_search(q, top_k=5):
                    return fake_chat
                @staticmethod
                def search_faq(q, top_k=2, agent_type=""):
                    return fake_faq
                @staticmethod
                def fmt_enriched_summary(echunk):
                    return "冲突根源：沟通不足"
            return _Stub

        monkeypatch.setattr(rs, "_rag", _fake_rag)
        result = build_inject_preview(query="最近我们很吵", modes=["chat_history", "knowledge"])
        assert len(result["chat_history"]) == 1
        assert len(result["knowledge"]) == 1
        sc = result["suggested_context"]
        assert "【相关历史对话片段】" in sc
        assert "第102,103天" in sc
        assert "冲突" in sc
        assert "【专业知识手册】" in sc
        assert "共情" in sc


class TestListSessions:
    def test_summary_exposes_rounds_fields(self):
        """list_sessions 输出应含 round_index / rounds_count / updated_at（Day 6）"""
        s = _mk_session()
        _complete_session_as_done(s.id)
        continue_session(s.id, question="Q2")
        summaries = list_sessions()
        # 找到刚创建的
        row = next((r for r in summaries if r["id"] == s.id), None)
        assert row is not None
        assert "round_index" in row and row["round_index"] == 1
        assert "rounds_count" in row and row["rounds_count"] == 1
        assert "updated_at" in row and isinstance(row["updated_at"], str)
        assert "question" in row  # 完整 question（非仅 excerpt）

    def test_sorted_by_updated_at_desc(self):
        """多 session · 按 updated_at 倒序"""
        import time
        s1 = _mk_session(question="早的 session 问题")
        time.sleep(0.01)
        s2 = _mk_session(question="晚的 session 问题")
        summaries = list_sessions()
        ids = [r["id"] for r in summaries]
        i1 = ids.index(s1.id)
        i2 = ids.index(s2.id)
        assert i2 < i1, f"newer session should come first, got {ids}"
