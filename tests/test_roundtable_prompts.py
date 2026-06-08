"""Day 6 · D6.N.d · roundtable_prompts.yaml 契约测试

目的：
  - 锁定 `neutral` persona 的「情境感知 · 关系已结束」分支不被误删
  - 锁定 `phase1_template` 规则 #4 的落点自适应（可作为 vs 已关闭）
  - 锁定 `phase2_template` 新增禁忌（已结束时不讲挽回）
  - 验证 YAML 本身可被 `_load_prompts()` 正常解析 + 关键字段齐全

这组测试是 **guardrail** · 确保后续 prompt 迭代不回退到"一刀切讲下一步行动"的老版本。
运行：`conda run -n wechatDHA python -m pytest tests/test_roundtable_prompts.py -q`
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

PROMPTS_PATH = PROJECT_ROOT / "configs" / "roundtable_prompts.yaml"


# ═══════════════════════════════════════════════════════════════════
# Fixture：两种加载方式都要 work（直接 YAML + roundtable_service 缓存）
# ═══════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def prompts_raw() -> dict:
    """直接 yaml.safe_load · 不走 roundtable_service 的缓存"""
    assert PROMPTS_PATH.exists(), f"prompts yaml missing: {PROMPTS_PATH}"
    with PROMPTS_PATH.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert isinstance(data, dict)
    return data


@pytest.fixture(scope="module")
def prompts_via_service() -> dict:
    """通过 roundtable_service._load_prompts 加载 · 验证缓存路径也能正常解析"""
    from scripts.advisor.api.services.roundtable_service import _load_prompts
    return _load_prompts()


# ═══════════════════════════════════════════════════════════════════
# 基础契约：YAML 结构完整 · 两种加载路径一致
# ═══════════════════════════════════════════════════════════════════

class TestYamlStructure:
    def test_top_level_keys(self, prompts_raw):
        for key in (
            "personas", "phase1_template", "phase2_template",
            "moderator_templates", "moderator_llm_prompt", "discourse_banlist",
        ):
            assert key in prompts_raw, f"missing top-level key: {key}"

    def test_nine_personas_present(self, prompts_raw):
        expected = {
            "neutral", "supportive", "psychoanalytic", "eft", "bowen",
            "sociology", "philosophy", "game_theory", "cultural",
        }
        assert set(prompts_raw["personas"].keys()) == expected

    def test_every_persona_has_name_and_core(self, prompts_raw):
        for pid, pdef in prompts_raw["personas"].items():
            assert "name" in pdef and pdef["name"], f"{pid}.name missing"
            assert "core" in pdef and pdef["core"], f"{pid}.core missing"

    def test_service_load_matches_direct_load(self, prompts_raw, prompts_via_service):
        """服务端缓存加载 = 直接 YAML 加载（避免 encoding / 编码问题）"""
        assert prompts_via_service["personas"]["neutral"]["core"] == \
            prompts_raw["personas"]["neutral"]["core"]
        assert prompts_via_service["phase1_template"] == prompts_raw["phase1_template"]


# ═══════════════════════════════════════════════════════════════════
# D6.N.d 契约：neutral persona.core 的情境感知分支
# ═══════════════════════════════════════════════════════════════════

class TestNeutralContextAwareness:
    """保障 `neutral.core` 里的「关系已结束 → 不讲下一步行动」分支不被误删。"""

    def test_core_has_context_awareness_header(self, prompts_raw):
        core = prompts_raw["personas"]["neutral"]["core"]
        assert "情境感知" in core, "neutral.core 应当包含【情境感知】小节"

    def test_core_mentions_relationship_ended_branch(self, prompts_raw):
        """关系已结束的场景必须被显式提到"""
        core = prompts_raw["personas"]["neutral"]["core"]
        # 触发词任选其一即可
        assert any(
            kw in core
            for kw in ["已结束", "已分手", "已离婚", "已做决定", "已断联"]
        ), "neutral.core 应当提到'关系已结束/已分手/已做决定'场景"

    def test_core_says_no_action_when_ended(self, prompts_raw):
        """关系已结束时，必须显式说明"不要讲下一步行动" / "承认 + 理解" 之一"""
        core = prompts_raw["personas"]["neutral"]["core"]
        assert "不要" in core and "下一步" in core, \
            "必须明确写出'关系已结束时不要讲下一步行动'"
        # 替代落点：承认 / 命名 / 自我照顾
        assert any(
            kw in core for kw in ["承认", "命名", "自我照顾", "自我整理"]
        ), "必须给出替代落点（承认 / 命名 / 自我照顾）"

    def test_core_still_allows_action_when_open(self, prompts_raw):
        """`尚在关系中 / 可作为 / 还在选择中` 分支仍保留原有'给出下一步行动'逻辑"""
        core = prompts_raw["personas"]["neutral"]["core"]
        assert "可作为" in core or "还在选择" in core or "尚在关系中" in core, \
            "必须保留'仍可作为的阶段可以给出下一步行动'分支"

    def test_core_has_trigger_keywords(self, prompts_raw):
        """触发词列表存在 · 至少覆盖 3 个常见线索"""
        core = prompts_raw["personas"]["neutral"]["core"]
        triggers = ["分手了", "离婚", "断联", "结束了", "走了", "分开了"]
        hits = sum(1 for t in triggers if t in core)
        assert hits >= 3, f"触发词覆盖不足（命中 {hits}/6 · 需 ≥3）"


# ═══════════════════════════════════════════════════════════════════
# D6.N.d 契约：phase1_template 规则 #4 落点自适应
# ═══════════════════════════════════════════════════════════════════

class TestPhase1TemplateAdaptiveEnding:
    def test_rule4_offers_two_options(self, prompts_raw):
        """规则 #4 必须是"二选一"的落点自适应 · 而不是硬性要求下一步行动"""
        tmpl = prompts_raw["phase1_template"]
        assert "落点自适应" in tmpl or "二选一" in tmpl, \
            "phase1_template 规则 #4 应当采用'落点自适应'的二选一写法"

    def test_rule4_still_mentions_next_step_for_open(self, prompts_raw):
        """可作为场景 → 仍要求给出'具体可行的下一步'"""
        tmpl = prompts_raw["phase1_template"]
        assert "具体可行的下一步" in tmpl, \
            "可作为场景分支应当仍保留'具体可行的下一步'要求"

    def test_rule4_softens_for_closed(self, prompts_raw):
        """已关闭场景 → 落到"命名感受 / 承认 / 自我照顾"即可"""
        tmpl = prompts_raw["phase1_template"]
        assert any(
            kw in tmpl
            for kw in ["命名此刻的感受", "承认已经发生", "自我照顾"]
        ), "已关闭场景分支应当允许落到'命名 / 承认 / 自我照顾'"

    def test_forbidden_no_repair_advice_when_ended(self, prompts_raw):
        """禁忌清单新增：关系已结束时禁止给'如何修复 / 如何挽回'类建议"""
        tmpl = prompts_raw["phase1_template"]
        # 至少命中三者之一即视为合规
        assert any(
            kw in tmpl for kw in ["如何修复", "如何挽回", "如何改善关系"]
        ), "phase1_template 禁忌段应当新增'关系结束时不谈修复/挽回'"


# ═══════════════════════════════════════════════════════════════════
# D6.N.d 契约：phase2_template 禁忌同步
# ═══════════════════════════════════════════════════════════════════

class TestPhase2TemplateForbidAddons:
    def test_phase2_banlist_mirrors_phase1(self, prompts_raw):
        """phase2 的禁忌也要收录同一条'关系结束时不谈挽回'"""
        tmpl = prompts_raw["phase2_template"]
        assert any(
            kw in tmpl for kw in ["如何修复", "如何挽回", "如何改善关系"]
        ), "phase2_template 禁忌段应当与 phase1 同步新增此项"


# ═══════════════════════════════════════════════════════════════════
# 回归：既有 behavior（不能退化）
# ═══════════════════════════════════════════════════════════════════

class TestNonRegression:
    def test_phase1_template_still_has_confidence_markers(self, prompts_raw):
        """phase2 输出格式仍保留置信度要求"""
        tmpl = prompts_raw["phase2_template"]
        assert "[置信度: 0.xx]" in tmpl

    def test_discourse_banlist_unchanged(self, prompts_raw):
        """discourse_banlist 的三个维度仍在"""
        bl = prompts_raw["discourse_banlist"]
        for key in ("diagnostic", "absolute", "prescriptive"):
            assert key in bl and len(bl[key]) >= 3

    def test_moderator_llm_prompt_still_two_stage(self, prompts_raw):
        """Moderator 仍然是两段式（thinking + JSON）"""
        p = prompts_raw["moderator_llm_prompt"]
        assert "综合思考" in p
        assert "---JSON---" in p

    def test_template_format_placeholders_intact(self, prompts_raw):
        """关键 format 占位符不被动过（不能破坏 .format() 调用）"""
        p1 = prompts_raw["phase1_template"]
        for ph in ("{persona_name}", "{persona_core}", "{question}", "{prior_context_block}"):
            assert ph in p1, f"phase1_template 缺少占位符 {ph}"

        p2 = prompts_raw["phase2_template"]
        for ph in (
            "{persona_name}", "{persona_core}", "{question}", "{prior_context_block}",
            "{peer0_name}", "{peer1_name}", "{peer0_summary}", "{peer1_summary}",
        ):
            assert ph in p2, f"phase2_template 缺少占位符 {ph}"

    def test_moderator_templates_have_prior_context_placeholder(self, prompts_raw):
        """Day 7 · 修复"Moderator 追问失忆"bug · 两套 Moderator 模板必须带
        {prior_context_block}，否则即使 _build_llm_moderator 传了 prior context
        也无法注入，用户感觉 Moderator 第一次见面。"""
        for key in ("moderator_llm_prompt", "deep_moderator_llm_prompt"):
            tmpl = prompts_raw.get(key)
            assert tmpl is not None, f"缺少 {key}"
            assert "{prior_context_block}" in tmpl, (
                f"{key} 缺少 {{prior_context_block}} 占位符 · "
                "这会让 Moderator 在追问时完全丢失历史"
            )
            assert "{question}" in tmpl
            assert "{peers_block}" in tmpl


# ═══════════════════════════════════════════════════════════════════
# 冒烟：实际渲染一遍 · 确保 .format() 不崩
# ═══════════════════════════════════════════════════════════════════

class TestSmokeRender:
    def test_phase1_renders_cleanly(self, prompts_raw):
        core = prompts_raw["personas"]["neutral"]["core"]
        tmpl = prompts_raw["phase1_template"]
        rendered = tmpl.format(
            persona_name="中立顾问",
            persona_core=core,
            question="我和他已经分手一个月了，他最近突然又来找我，我不知道该不该回。",
            prior_context_block="",
        )
        assert "已经分手" in rendered
        assert "情境感知" in rendered  # neutral.core 的新小节应当被嵌入

    def test_phase2_renders_cleanly(self, prompts_raw):
        core = prompts_raw["personas"]["neutral"]["core"]
        tmpl = prompts_raw["phase2_template"]
        rendered = tmpl.format(
            persona_name="中立顾问",
            persona_core=core,
            question="我们没办法继续了。",
            prior_context_block="",
            peer0_name="EFT 情绪聚焦",
            peer0_summary="我听到你正在经历很深的孤独感。",
            peer1_name="支持性顾问",
            peer1_summary="你愿意放下，其实已经很勇敢了。",
        )
        assert "EFT 情绪聚焦" in rendered
        assert "[置信度: 0.xx]" in rendered
