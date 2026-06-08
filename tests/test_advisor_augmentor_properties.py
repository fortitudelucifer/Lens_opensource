"""
数据增强属性测试

Property 16: 数据增强格式与质量
**Feature: relationship-advisor-agent, Property 16: 数据增强格式与质量**
**Validates: Requirements 18.2, 18.6**

测试策略：
- 不调用真实 LLM API，测试 import_dataset 的格式转换和 filter_quality 的过滤逻辑
- 使用临时文件模拟外部数据集
- 验证转换后的统一格式和质量过滤阈值
"""

import json
import tempfile
from pathlib import Path

import pytest
from hypothesis import given, settings, strategies as st

from scripts.advisor.augmentor import DataAugmentor


# =============================================================================
# 测试策略
# =============================================================================

@st.composite
def conversation_turn_strategy(draw):
    """生成单轮对话"""
    role = draw(st.sampled_from(['user', 'client', 'counselor', 'therapist']))
    words = draw(st.lists(
        st.sampled_from([
            '你好', '最近', '工作', '压力', '感觉', '不太好',
            '能聊聊', '怎么了', '理解', '建议', '试试', '放松',
        ]),
        min_size=2, max_size=8,
    ))
    content = ''.join(words)
    return {'role': role, 'content': content}


@st.composite
def external_sample_strategy(draw):
    """生成模拟外部数据集样本（对话列表格式）"""
    turns = draw(st.lists(conversation_turn_strategy(), min_size=2, max_size=10))
    label = draw(st.sampled_from(['焦虑', '抑郁', '关系问题', '压力', '']))
    return {
        'dialogue': turns,
        'label': label,
    }


@st.composite
def augmented_sample_strategy(draw):
    """生成模拟增强后的样本"""
    words = draw(st.lists(
        st.sampled_from([
            '你好', '工作', '压力', '感觉', '不太好', '理解', '建议',
        ]),
        min_size=3, max_size=15,
    ))
    conversation = ''.join(words)

    # 随机决定是否包含关键标签和思维链
    include_tags = draw(st.booleans())
    include_thinking = draw(st.booleans())

    if include_tags:
        response = (
            f"【关系状态】平淡期\n"
            f"【问题】沟通不足\n"
            f"【建议】多交流\n"
            f"【批评】双方都需要改进\n"
            f"【评价】{conversation[:50]}"
        )
    else:
        # 短回复，可能不通过质量过滤
        response = draw(st.text(min_size=0, max_size=40))

    thinking = f"分析：{conversation[:30]}" if include_thinking else ''

    return {
        'conversation': conversation,
        'thinking': thinking,
        'response': response,
        'logic_teacher': 'deepseek_reasoner',
        'style_teacher': '',
        'chunk_id': draw(st.text(min_size=0, max_size=10)),
    }


# =============================================================================
# Property 16: 数据增强格式与质量
# =============================================================================

class TestDataAugmentationFormatAndQuality:
    """Property 16: 数据增强格式与质量

    **Feature: relationship-advisor-agent, Property 16: 数据增强格式与质量**
    **Validates: Requirements 18.2, 18.6**

    For any 从外部数据集导入的样本，转换后必须符合统一的训练数据格式，
    且质量过滤后的所有样本必须通过质量阈值检查。
    """

    @settings(max_examples=100, deadline=None)
    @given(st.lists(external_sample_strategy(), min_size=1, max_size=20))
    def test_imported_samples_have_unified_format(self, samples):
        """导入的样本必须包含 conversation_text 字段

        **Validates: Requirements 18.2**
        """
        augmentor = DataAugmentor()

        # 写入临时 JSONL 文件
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / 'data.jsonl'
            with open(filepath, 'w', encoding='utf-8') as f:
                for sample in samples:
                    f.write(json.dumps(sample, ensure_ascii=False) + '\n')

            imported = augmentor.import_dataset('PsyCLIENT-CP', tmpdir)

        # 验证统一格式
        for item in imported:
            assert 'conversation_text' in item, "缺少 conversation_text 字段"
            assert isinstance(item['conversation_text'], str)
            assert len(item['conversation_text']) > 0, "conversation_text 不能为空"

    @settings(max_examples=100, deadline=None)
    @given(st.lists(external_sample_strategy(), min_size=1, max_size=15))
    def test_imported_conversations_use_me_other_format(self, samples):
        """导入的对话应转换为 ME:/OTHER: 格式

        **Validates: Requirements 18.2**
        """
        augmentor = DataAugmentor()

        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / 'data.jsonl'
            with open(filepath, 'w', encoding='utf-8') as f:
                for sample in samples:
                    f.write(json.dumps(sample, ensure_ascii=False) + '\n')

            imported = augmentor.import_dataset('PsyCLIENT-CP', tmpdir)

        for item in imported:
            text = item['conversation_text']
            lines = text.strip().split('\n')
            for line in lines:
                assert line.startswith('ME: ') or line.startswith('OTHER: '), (
                    f"行格式错误: '{line}'"
                )

    @settings(max_examples=100, deadline=None)
    @given(
        st.lists(augmented_sample_strategy(), min_size=1, max_size=20),
        st.floats(min_value=0.0, max_value=1.0),
    )
    def test_quality_filter_respects_threshold(self, samples, threshold):
        """质量过滤后的所有样本分数必须 >= 阈值

        **Validates: Requirements 18.6**
        """
        augmentor = DataAugmentor(config={'quality_threshold': threshold})

        filtered = augmentor.filter_quality(samples)

        # 验证所有通过的样本分数 >= 阈值
        for sample in filtered:
            score = augmentor._quality_score(sample)
            assert score >= threshold, (
                f"样本分数 {score} 低于阈值 {threshold}"
            )

    @settings(max_examples=100, deadline=None)
    @given(st.lists(augmented_sample_strategy(), min_size=5, max_size=20))
    def test_quality_filter_count_consistency(self, samples):
        """过滤后的样本数 + 被过滤的样本数 = 原始样本数

        **Validates: Requirements 18.6**
        """
        augmentor = DataAugmentor(config={'quality_threshold': 0.5})

        filtered = augmentor.filter_quality(samples)
        stats = augmentor.get_stats()

        # filtered + filtered_count == original
        assert len(filtered) + stats['filtered_count'] == len(samples)

    @settings(max_examples=100, deadline=None)
    @given(st.lists(augmented_sample_strategy(), min_size=1, max_size=15))
    def test_quality_score_in_valid_range(self, samples):
        """质量分数必须在 [0, 1] 范围内

        **Validates: Requirements 18.6**
        """
        augmentor = DataAugmentor()

        for sample in samples:
            score = augmentor._quality_score(sample)
            assert 0.0 <= score <= 1.0, f"分数 {score} 超出 [0, 1] 范围"
