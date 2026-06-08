"""
test_advisor_data_level.py
数据级别系统属性测试与单元测试

运行方式：
    conda activate wechatDHA
    python -m pytest tests/test_advisor_data_level.py -v
"""

import tempfile
from pathlib import Path

import pytest
import yaml
from hypothesis import given, settings, strategies as st, assume

from scripts.advisor.config import (
    AdvisorConfig,
    DataLevel,
    parse_data_level,
    _LEVEL_ALIASES,
    load_config,
)


# =============================================================================
# Hypothesis 策略
# =============================================================================

# 有效级别字符串集合（含别名）
_VALID_LEVEL_STRINGS = {'l1', 'l2', 'l3', 'timeline'}


@st.composite
def fuzzy_case_level(draw):
    """生成有效级别字符串的随机大小写变体 + 首尾空白"""
    base = draw(st.sampled_from(sorted(_VALID_LEVEL_STRINGS)))
    # 随机变换每个字符的大小写
    chars = []
    for ch in base:
        if draw(st.booleans()):
            chars.append(ch.upper())
        else:
            chars.append(ch.lower())
    fuzzy = ''.join(chars)
    # 添加随机首尾空白（空格和制表符）
    leading = draw(st.text(alphabet=' \t', min_size=0, max_size=3))
    trailing = draw(st.text(alphabet=' \t', min_size=0, max_size=3))
    return leading + fuzzy + trailing


# =============================================================================
# Property 1: get_input_file 映射完整性
# =============================================================================

class TestProperty1GetInputFileMapping:
    """
    # Feature: unified-data-levels, Property 1: get_input_file 映射完整性

    对于所有有效的 DataLevel 值（l1、l2、l3），调用 get_input_file(level) 应返回
    非空字符串，且该字符串与 AdvisorConfig 中对应的路径属性一致。

    **Validates: Requirements 1.2, 1.3, 1.4, 1.5**
    """

    @settings(max_examples=100)
    @given(level=st.sampled_from(list(DataLevel)))
    def test_get_input_file_returns_correct_path(self, level):
        """
        # Feature: unified-data-levels, Property 1: get_input_file 映射完整性

        **Validates: Requirements 1.2, 1.3, 1.4, 1.5**

        对于所有有效 DataLevel，get_input_file 返回对应路径属性。
        """
        config = AdvisorConfig(
            sft_l1_file='/data/workspace/timeline_out/agent_sft_l1.jsonl',
            sft_l2_file='/data/workspace/timeline_out/agent_sft_l2.jsonl',
            timeline_file='/data/workspace/timeline_out/enriched_full.jsonl',
        )

        expected_mapping = {
            DataLevel.L1: config.sft_l1_file,
            DataLevel.L2: config.sft_l2_file,
            DataLevel.L3: config.timeline_file,
        }

        result = config.get_input_file(level.value)
        assert result == expected_mapping[level], (
            f"get_input_file('{level.value}') 返回 '{result}'，"
            f"期望 '{expected_mapping[level]}'"
        )
        assert isinstance(result, str) and len(result) > 0


# =============================================================================
# Property 2: 无效级别拒绝
# =============================================================================

class TestProperty2InvalidLevelRejection:
    """
    # Feature: unified-data-levels, Property 2: 无效级别拒绝

    对于所有不属于有效级别集合的字符串，parse_data_level 应抛出 ValueError。

    **Validates: Requirements 1.6**
    """

    @settings(max_examples=100)
    @given(value=st.text().filter(
        lambda s: s.strip().lower() not in _VALID_LEVEL_STRINGS
    ))
    def test_invalid_level_raises_value_error(self, value):
        """
        # Feature: unified-data-levels, Property 2: 无效级别拒绝

        **Validates: Requirements 1.6**

        对于所有无效字符串，parse_data_level 抛出 ValueError。
        """
        with pytest.raises(ValueError):
            parse_data_level(value)


# =============================================================================
# Property 3: 数据级别解析归一化
# =============================================================================

class TestProperty3DataLevelNormalization:
    """
    # Feature: unified-data-levels, Property 3: 数据级别解析归一化

    对于所有有效级别字符串，在任意大小写组合和任意首尾空白填充下，
    parse_data_level 应返回与标准小写形式相同的 DataLevel 枚举值。

    **Validates: Requirements 6.1, 6.2, 6.3**
    """

    @settings(max_examples=100)
    @given(fuzzy=fuzzy_case_level())
    def test_parse_normalizes_case_and_whitespace(self, fuzzy):
        """
        # Feature: unified-data-levels, Property 3: 数据级别解析归一化

        **Validates: Requirements 6.1, 6.2, 6.3**

        对有效级别随机变换大小写 + 添加首尾空白后，解析结果与标准形式一致。
        """
        normalized = fuzzy.strip().lower()

        result = parse_data_level(fuzzy)

        if normalized in _LEVEL_ALIASES:
            expected = _LEVEL_ALIASES[normalized]
        else:
            expected = DataLevel(normalized)

        assert result == expected, (
            f"parse_data_level('{fuzzy}') 返回 {result}，期望 {expected}"
        )


# =============================================================================
# 单元测试：DataLevel 基础功能
# =============================================================================

class TestDataLevelUnit:
    """
    DataLevel 基础功能单元测试

    _Requirements: 1.1, 1.3, 1.4, 1.5, 6.3_
    """

    def test_default_data_level(self):
        """AdvisorConfig 默认 data_level 为 'l1'"""
        config = AdvisorConfig()
        assert config.data_level == 'l1'

    def test_get_input_file_l1(self):
        """get_input_file('l1') 返回 sft_l1_file"""
        config = AdvisorConfig(
            sft_l1_file='/path/to/agent_sft_l1.jsonl',
            sft_l2_file='/path/to/agent_sft_l2.jsonl',
            timeline_file='/path/to/enriched_full.jsonl',
        )
        assert config.get_input_file('l1') == '/path/to/agent_sft_l1.jsonl'

    def test_get_input_file_l2(self):
        """get_input_file('l2') 返回 sft_l2_file"""
        config = AdvisorConfig(
            sft_l1_file='/path/to/agent_sft_l1.jsonl',
            sft_l2_file='/path/to/agent_sft_l2.jsonl',
            timeline_file='/path/to/enriched_full.jsonl',
        )
        assert config.get_input_file('l2') == '/path/to/agent_sft_l2.jsonl'

    def test_get_input_file_l3(self):
        """get_input_file('l3') 返回 timeline_file"""
        config = AdvisorConfig(
            sft_l1_file='/path/to/agent_sft_l1.jsonl',
            sft_l2_file='/path/to/agent_sft_l2.jsonl',
            timeline_file='/path/to/enriched_full.jsonl',
        )
        assert config.get_input_file('l3') == '/path/to/enriched_full.jsonl'

    def test_parse_timeline_alias(self):
        """parse_data_level('timeline') 返回 DataLevel.L3"""
        assert parse_data_level('timeline') == DataLevel.L3

    def test_load_config_data_level(self):
        """load_config 正确读取 data_level"""
        yaml_content = {
            'paths': {
                'data_level': 'l2',
            },
        }
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.yaml', delete=False
        ) as f:
            yaml.dump(yaml_content, f)
            tmp_path = f.name

        try:
            config = load_config(config_path=tmp_path, workspace='/tmp')
            assert config.data_level == 'l2'
        finally:
            Path(tmp_path).unlink(missing_ok=True)
