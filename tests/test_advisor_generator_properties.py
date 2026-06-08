"""
test_advisor_generator_properties.py
分析生成属性测试

**Property 4: 分析结果完整性**
**Property 5: JSON Schema 校验正确性**
**Validates: Requirements 2.3, 2.7, 6.6**

运行方式：
    conda activate wechatDHA
    python -m pytest tests/test_advisor_generator_properties.py -v
"""

import copy

import pytest
from hypothesis import given, settings, strategies as st, assume

from scripts.advisor.generator import ANALYSIS_SCHEMA, validate_analysis


# =============================================================================
# Hypothesis 策略
# =============================================================================

VALID_STATUSES = ["健康期", "甜蜜期", "平淡期", "冷淡期", "冲突期"]
VALID_QUALITIES = ["优秀", "良好", "一般", "较差", "很差"]


@st.composite
def valid_analysis_strategy(draw):
    """生成符合 ANALYSIS_SCHEMA 的有效分析结果"""
    return {
        "relationship_status": draw(st.sampled_from(VALID_STATUSES)),
        "communication_quality": draw(st.sampled_from(VALID_QUALITIES)),
        "emotional_balance": draw(st.text(
            alphabet=st.characters(whitelist_categories=('L', 'N', 'P', 'Z')),
            min_size=1, max_size=50,
        )),
        "key_issues": draw(st.lists(
            st.text(
                alphabet=st.characters(whitelist_categories=('L', 'N', 'P', 'Z')),
                min_size=1, max_size=80,
            ),
            min_size=1, max_size=3,
        )),
        "advice": draw(st.lists(
            st.text(
                alphabet=st.characters(whitelist_categories=('L', 'N', 'P', 'Z')),
                min_size=1, max_size=80,
            ),
            min_size=1, max_size=3,
        )),
        "criticism": {
            "ME": draw(st.text(
                alphabet=st.characters(whitelist_categories=('L', 'N', 'P', 'Z')),
                min_size=1, max_size=80,
            )),
            "OTHER": draw(st.text(
                alphabet=st.characters(whitelist_categories=('L', 'N', 'P', 'Z')),
                min_size=1, max_size=80,
            )),
        },
        "overall_assessment": draw(st.text(
            alphabet=st.characters(whitelist_categories=('L', 'N', 'P', 'Z')),
            min_size=1, max_size=100,
        )),
    }


@st.composite
def invalid_analysis_missing_field_strategy(draw):
    """生成缺少一个必需字段的无效分析结果"""
    valid = draw(valid_analysis_strategy())
    field_to_remove = draw(st.sampled_from(ANALYSIS_SCHEMA["required"]))
    del valid[field_to_remove]
    return valid, field_to_remove


@st.composite
def invalid_analysis_wrong_type_strategy(draw):
    """生成字段类型错误的无效分析结果"""
    valid = draw(valid_analysis_strategy())
    # 选择一个字段并替换为错误类型
    field = draw(st.sampled_from([
        "relationship_status", "communication_quality",
        "emotional_balance", "overall_assessment",
    ]))
    # 将字符串字段替换为整数
    valid[field] = draw(st.integers(min_value=0, max_value=100))
    return valid, field


@st.composite
def invalid_analysis_wrong_enum_strategy(draw):
    """生成 enum 值不在允许范围内的无效分析结果"""
    valid = draw(valid_analysis_strategy())
    field = draw(st.sampled_from(["relationship_status", "communication_quality"]))
    # 生成一个不在 enum 中的字符串
    invalid_value = draw(st.text(
        alphabet=st.characters(whitelist_categories=('L',)),
        min_size=3, max_size=10,
    ))
    # 确保不在有效值中
    if field == "relationship_status":
        assume(invalid_value not in VALID_STATUSES)
    else:
        assume(invalid_value not in VALID_QUALITIES)
    valid[field] = invalid_value
    return valid, field


# =============================================================================
# Property 4: 分析结果完整性
# =============================================================================

class TestProperty4AnalysisCompleteness:
    """
    **Feature: relationship-advisor-agent, Property 4: 分析结果完整性**
    **Validates: Requirements 2.3, 6.6**
    """

    @settings(max_examples=100)
    @given(analysis=valid_analysis_strategy())
    def test_valid_analysis_has_all_required_fields(self, analysis):
        """
        **Feature: relationship-advisor-agent, Property 4: 分析结果完整性**
        **Validates: Requirements 2.3, 6.6**

        对于任意符合 schema 的分析结果，必须包含所有必需字段：
        relationship_status, communication_quality, emotional_balance,
        key_issues, advice, criticism（含 ME 和 OTHER）, overall_assessment。
        """
        required = ANALYSIS_SCHEMA["required"]
        for field in required:
            assert field in analysis, f"缺少必需字段: {field}"

        # criticism 子字段
        assert "ME" in analysis["criticism"], "criticism 缺少 ME"
        assert "OTHER" in analysis["criticism"], "criticism 缺少 OTHER"

        # 类型检查
        assert isinstance(analysis["relationship_status"], str)
        assert isinstance(analysis["communication_quality"], str)
        assert isinstance(analysis["emotional_balance"], str)
        assert isinstance(analysis["key_issues"], list)
        assert isinstance(analysis["advice"], list)
        assert isinstance(analysis["criticism"], dict)
        assert isinstance(analysis["overall_assessment"], str)

    @settings(max_examples=100)
    @given(analysis=valid_analysis_strategy())
    def test_valid_analysis_passes_validation(self, analysis):
        """
        **Feature: relationship-advisor-agent, Property 4: 分析结果完整性**
        **Validates: Requirements 2.3, 6.6**

        对于任意符合 schema 的分析结果，validate_analysis 应返回空错误列表。
        """
        errors = validate_analysis(analysis)
        assert errors == [], f"有效分析不应有错误，但得到: {errors}"


# =============================================================================
# Property 5: JSON Schema 校验正确性
# =============================================================================

class TestProperty5SchemaValidation:
    """
    **Feature: relationship-advisor-agent, Property 5: JSON Schema 校验正确性**
    **Validates: Requirements 2.7**
    """

    @settings(max_examples=100)
    @given(data=invalid_analysis_missing_field_strategy())
    def test_missing_field_detected(self, data):
        """
        **Feature: relationship-advisor-agent, Property 5: JSON Schema 校验正确性**
        **Validates: Requirements 2.7**

        对于任意缺少必需字段的 JSON 对象，校验函数应返回失败。
        """
        invalid, removed_field = data
        errors = validate_analysis(invalid)
        assert len(errors) > 0, f"缺少字段 '{removed_field}' 应被检测到"
        # 确认错误消息提到了缺失的字段
        error_text = " ".join(errors)
        assert removed_field in error_text, \
            f"错误消息应提到缺失字段 '{removed_field}'，实际: {errors}"

    @settings(max_examples=100)
    @given(data=invalid_analysis_wrong_type_strategy())
    def test_wrong_type_detected(self, data):
        """
        **Feature: relationship-advisor-agent, Property 5: JSON Schema 校验正确性**
        **Validates: Requirements 2.7**

        对于任意字段类型错误的 JSON 对象，校验函数应返回失败。
        """
        invalid, wrong_field = data
        errors = validate_analysis(invalid)
        assert len(errors) > 0, f"字段 '{wrong_field}' 类型错误应被检测到"

    @settings(max_examples=100)
    @given(data=invalid_analysis_wrong_enum_strategy())
    def test_wrong_enum_value_detected(self, data):
        """
        **Feature: relationship-advisor-agent, Property 5: JSON Schema 校验正确性**
        **Validates: Requirements 2.7**

        对于 enum 值不在允许范围内的 JSON 对象，校验函数应返回失败。
        """
        invalid, wrong_field = data
        errors = validate_analysis(invalid)
        assert len(errors) > 0, f"字段 '{wrong_field}' 的 enum 值无效应被检测到"

    @settings(max_examples=100)
    @given(analysis=valid_analysis_strategy())
    def test_too_many_items_detected(self, analysis):
        """
        **Feature: relationship-advisor-agent, Property 5: JSON Schema 校验正确性**
        **Validates: Requirements 2.7**

        当 key_issues 或 advice 超过 3 项时，校验函数应返回失败。
        """
        # 添加第 4 项
        analysis_copy = copy.deepcopy(analysis)
        analysis_copy["key_issues"] = analysis["key_issues"] + ["额外问题1", "额外问题2"]
        # 现在至少有 3 项（原始 1-3 项 + 2 项 = 3-5 项），取超过 3 项的情况
        if len(analysis_copy["key_issues"]) > 3:
            errors = validate_analysis(analysis_copy)
            assert len(errors) > 0, "key_issues 超过 3 项应被检测到"

    def test_non_dict_input(self):
        """
        **Feature: relationship-advisor-agent, Property 5: JSON Schema 校验正确性**
        **Validates: Requirements 2.7**

        非 dict 输入应返回错误。
        """
        assert len(validate_analysis("not a dict")) > 0
        assert len(validate_analysis(42)) > 0
        assert len(validate_analysis([])) > 0
        assert len(validate_analysis(None)) > 0

    def test_empty_dict(self):
        """
        **Feature: relationship-advisor-agent, Property 5: JSON Schema 校验正确性**
        **Validates: Requirements 2.7**

        空 dict 应返回所有必需字段缺失的错误。
        """
        errors = validate_analysis({})
        assert len(errors) == len(ANALYSIS_SCHEMA["required"]), \
            f"空 dict 应有 {len(ANALYSIS_SCHEMA['required'])} 个错误，实际 {len(errors)}"

    def test_criticism_missing_subfields(self):
        """
        **Feature: relationship-advisor-agent, Property 5: JSON Schema 校验正确性**
        **Validates: Requirements 2.7**

        criticism 缺少 ME 或 OTHER 子字段应被检测到。
        """
        base = {
            "relationship_status": "健康期",
            "communication_quality": "良好",
            "emotional_balance": "平衡",
            "key_issues": ["问题1"],
            "advice": ["建议1"],
            "criticism": {"ME": "批评"},  # 缺少 OTHER
            "overall_assessment": "评价",
        }
        errors = validate_analysis(base)
        assert len(errors) > 0, "criticism 缺少 OTHER 应被检测到"

        base2 = copy.deepcopy(base)
        base2["criticism"] = {"OTHER": "批评"}  # 缺少 ME
        errors2 = validate_analysis(base2)
        assert len(errors2) > 0, "criticism 缺少 ME 应被检测到"
