"""
test_field_mapping.py
field_mapping 属性测试

属性测试：
- Property 9: field_mapping 应用正确性
  Validates: Requirements 7.1, 7.2, 7.3
- Property 10: field_mapping 必填字段校验
  Validates: Requirements 7.4

运行方式：
    python -m pytest tests/workspace/ingestion/test_field_mapping.py -x -v
"""

import sys
from pathlib import Path

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

# Setup paths
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.workspace.ingestion.adapters.generic_csv import (
    apply_field_mapping,
    validate_field_mapping,
)
from scripts.workspace.ingestion.schema import REQUIRED_FIELDS


# ── 常量 ──────────────────────────────────────────────────────────────

# msg_uid 由适配器自动生成，validate_field_mapping 不检查它
REQUIRED_FOR_MAPPING = sorted(set(REQUIRED_FIELDS) - {"msg_uid"})
# => ["modality", "speaker", "text_raw", "ts", "type"]


# ── 测试策略（Hypothesis Strategies）──────────────────────────────────

# 简单字符串键/值（避免 _const: / _default: 前缀冲突）
_safe_chars = st.characters(
    whitelist_categories=("L", "N"),
    whitelist_characters="_",
)
safe_keys = st.text(_safe_chars, min_size=1, max_size=15).filter(
    lambda s: not s.startswith("_const:") and not s.startswith("_default:")
)
safe_values = st.text(_safe_chars, min_size=1, max_size=20)

# 目标字段名
target_fields = st.text(_safe_chars, min_size=1, max_size=15)


# ── Property 9 策略 ──────────────────────────────────────────────────

@st.composite
def field_mapping_with_source_row(draw):
    """生成一个 (source_row, field_mapping) 组合，包含三种映射类型的混合。

    返回 (row, mapping, expected) 其中 expected 是每个目标字段的期望值和来源类型。
    """
    row = {}
    mapping = {}
    expected = {}  # target_field -> (expected_value, mapping_type)

    # 生成 1~5 个直接映射
    n_direct = draw(st.integers(min_value=1, max_value=5))
    for _ in range(n_direct):
        src_key = draw(safe_keys)
        tgt_field = draw(target_fields)
        src_value = draw(safe_values)

        # 确保源键不与已有映射冲突
        if src_key in mapping or any(
            k.endswith(f":{src_key}") for k in mapping
        ):
            continue

        row[src_key] = src_value
        mapping[src_key] = tgt_field
        expected[tgt_field] = (src_value, "direct")

    # 生成 0~3 个常量映射
    n_const = draw(st.integers(min_value=0, max_value=3))
    for _ in range(n_const):
        const_val = draw(safe_values)
        tgt_field = draw(target_fields)
        const_key = f"_const:{const_val}"

        if const_key in mapping:
            continue

        mapping[const_key] = tgt_field
        expected[tgt_field] = (const_val, "const")

    # 生成 0~3 个默认值映射
    n_default = draw(st.integers(min_value=0, max_value=3))
    for _ in range(n_default):
        default_val = draw(safe_values)
        tgt_field = draw(target_fields)
        default_key = f"_default:{default_val}"

        if default_key in mapping:
            continue
        # 默认值只在目标字段未被直接映射或常量覆盖时生效
        if tgt_field in expected:
            continue

        mapping[default_key] = tgt_field
        expected[tgt_field] = (default_val, "default_used")

    assume(len(mapping) > 0)
    return row, mapping, expected


@st.composite
def default_with_source_present(draw):
    """生成一个场景：默认值映射的目标字段同时有直接映射覆盖。

    验证：当源字段存在时，直接映射值优先于默认值。
    """
    src_key = draw(safe_keys)
    tgt_field = draw(target_fields)
    src_value = draw(safe_values)
    default_val = draw(safe_values)

    row = {src_key: src_value}
    mapping = {
        src_key: tgt_field,
        f"_default:{default_val}": tgt_field,
    }
    return row, mapping, tgt_field, src_value


@st.composite
def default_without_source(draw):
    """生成一个场景：只有默认值映射，源字段不存在。

    验证：源字段缺失时使用默认值。
    """
    tgt_field = draw(target_fields)
    default_val = draw(safe_values)

    row = {}  # 空行，源字段不存在
    mapping = {f"_default:{default_val}": tgt_field}
    return row, mapping, tgt_field, default_val


# ── Property 10 策略 ──────────────────────────────────────────────────

@st.composite
def incomplete_field_mapping(draw):
    """生成一个缺少至少一个必填字段映射的 field_mapping。

    返回 (mapping, missing_fields)。
    """
    # 随机选择要覆盖的必填字段子集（至少缺少 1 个）
    n_covered = draw(st.integers(min_value=0, max_value=len(REQUIRED_FOR_MAPPING) - 1))
    covered = draw(
        st.lists(
            st.sampled_from(REQUIRED_FOR_MAPPING),
            min_size=n_covered,
            max_size=n_covered,
            unique=True,
        )
    )

    missing = set(REQUIRED_FOR_MAPPING) - set(covered)
    assume(len(missing) > 0)

    mapping = {}
    for field_name in covered:
        # 随机选择覆盖方式：直接映射、常量、默认值
        cover_type = draw(st.sampled_from(["direct", "const", "default"]))
        if cover_type == "direct":
            src_key = draw(safe_keys)
            mapping[src_key] = field_name
        elif cover_type == "const":
            val = draw(safe_values)
            mapping[f"_const:{val}"] = field_name
        else:
            val = draw(safe_values)
            mapping[f"_default:{val}"] = field_name

    return mapping, missing


# ── Property 9: field_mapping 应用正确性 ─────────────────────────────


class TestProperty9FieldMappingApplication:
    """Property 9: field_mapping 应用正确性

    **Validates: Requirements 7.1, 7.2, 7.3**
    """

    @given(data=field_mapping_with_source_row())
    @settings(max_examples=200)
    def test_mapping_produces_correct_values(self, data):
        """对于任意源数据记录和 field_mapping 配置，应用映射后的结果应满足：
        直接映射的字段值等于源字段值，常量值字段等于指定常量，
        默认值字段在源字段缺失时等于默认值。

        **Validates: Requirements 7.1, 7.2, 7.3**
        """
        row, mapping, expected = data
        result = apply_field_mapping(row, mapping)

        for tgt_field, (exp_value, mapping_type) in expected.items():
            assert tgt_field in result, (
                f"目标字段 {tgt_field!r} 缺失 (mapping_type={mapping_type})"
            )
            assert result[tgt_field] == exp_value, (
                f"字段 {tgt_field!r}: 期望 {exp_value!r}, 实际 {result[tgt_field]!r} "
                f"(mapping_type={mapping_type})"
            )

    @given(data=default_with_source_present())
    @settings(max_examples=200)
    def test_direct_mapping_overrides_default(self, data):
        """当源字段存在时，直接映射值应优先于默认值。

        **Validates: Requirements 7.3**
        """
        row, mapping, tgt_field, expected_value = data
        result = apply_field_mapping(row, mapping)

        assert tgt_field in result
        assert result[tgt_field] == expected_value, (
            f"直接映射应优先: 期望 {expected_value!r}, 实际 {result[tgt_field]!r}"
        )

    @given(data=default_without_source())
    @settings(max_examples=200)
    def test_default_used_when_source_missing(self, data):
        """当源字段缺失时，默认值应被使用。

        **Validates: Requirements 7.3**
        """
        row, mapping, tgt_field, expected_default = data
        result = apply_field_mapping(row, mapping)

        assert tgt_field in result
        assert result[tgt_field] == expected_default, (
            f"默认值应生效: 期望 {expected_default!r}, 实际 {result[tgt_field]!r}"
        )

    @given(
        const_val=safe_values,
        tgt_field=target_fields,
    )
    @settings(max_examples=200)
    def test_const_always_applied(self, const_val, tgt_field):
        """常量值映射应始终生效，不依赖源数据。

        **Validates: Requirements 7.2**
        """
        mapping = {f"_const:{const_val}": tgt_field}
        # 即使空行，常量也应生效
        result = apply_field_mapping({}, mapping)
        assert result[tgt_field] == const_val

        # 即使行有其他字段，常量也应生效
        result2 = apply_field_mapping({"other": "data"}, mapping)
        assert result2[tgt_field] == const_val


# ── Property 10: field_mapping 必填字段校验 ──────────────────────────


class TestProperty10RequiredFieldValidation:
    """Property 10: field_mapping 必填字段校验

    **Validates: Requirements 7.4**
    """

    @given(data=incomplete_field_mapping())
    @settings(max_examples=200)
    def test_missing_required_fields_detected(self, data):
        """对于缺少至少一个必填字段映射的 field_mapping，
        校验函数应返回包含缺失字段名的错误列表。

        **Validates: Requirements 7.4**
        """
        mapping, missing_fields = data
        errors = validate_field_mapping(mapping)

        # 应返回非空错误列表
        assert len(errors) > 0, (
            f"缺少字段 {missing_fields} 但未返回错误"
        )

        # 每个缺失字段都应在错误信息中被提及
        error_text = "\n".join(errors)
        for field_name in missing_fields:
            assert field_name in error_text, (
                f"缺失字段 {field_name!r} 未在错误信息中提及: {errors}"
            )

    @given(
        cover_type=st.sampled_from(["direct", "const", "default"]),
        src_keys=st.lists(safe_keys, min_size=5, max_size=5, unique=True),
        vals=st.lists(safe_values, min_size=5, max_size=5, unique=True),
    )
    @settings(max_examples=200)
    def test_all_required_covered_passes(self, cover_type, src_keys, vals):
        """当所有必填字段都有映射覆盖时，校验应通过（返回空列表）。

        **Validates: Requirements 7.4**
        """
        mapping = {}
        for i, field_name in enumerate(REQUIRED_FOR_MAPPING):
            if cover_type == "direct":
                mapping[src_keys[i]] = field_name
            elif cover_type == "const":
                mapping[f"_const:{vals[i]}"] = field_name
            else:
                mapping[f"_default:{vals[i]}"] = field_name

        errors = validate_field_mapping(mapping)
        assert errors == [], f"所有必填字段已覆盖但仍有错误: {errors}"
