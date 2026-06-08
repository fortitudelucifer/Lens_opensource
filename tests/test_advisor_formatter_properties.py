"""
test_advisor_formatter_properties.py
格式化和审核属性测试

**Property 6: 对话和分析格式化正确性**
**Property 7: 训练数据有效性**
**Property 8: Markdown 审核 Round-Trip**
**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 4.3, 4.5**

运行方式：
    conda activate wechatDHA
    python -m pytest tests/test_advisor_formatter_properties.py -v
"""

import json
import tempfile
from pathlib import Path

import pytest
from hypothesis import given, settings, strategies as st, assume

from scripts.advisor.formatter import TrainingFormatter


# =============================================================================
# Hypothesis 策略
# =============================================================================

VALID_STATUSES = ["健康期", "甜蜜期", "平淡期", "冷淡期", "冲突期"]
VALID_QUALITIES = ["优秀", "良好", "一般", "较差", "很差"]

# 安全文本：避免特殊 markdown 字符干扰 round-trip
safe_text = st.text(
    alphabet=st.characters(whitelist_categories=('L', 'N'), whitelist_characters='，。！？、'),
    min_size=1,
    max_size=60,
).filter(lambda s: s.strip())


@st.composite
def message_strategy(draw):
    """生成单条非系统消息"""
    speaker = draw(st.sampled_from(['ME', 'OTHER']))
    text = draw(safe_text)
    return {'speaker': speaker, 'text_raw': text, 'type': 'text', 'modality': 'text'}


@st.composite
def message_list_strategy(draw, min_size=3, max_size=15):
    """生成非系统消息列表"""
    return draw(st.lists(message_strategy(), min_size=min_size, max_size=max_size))


@st.composite
def analysis_strategy(draw):
    """生成符合 schema 的分析结果"""
    return {
        "relationship_status": draw(st.sampled_from(VALID_STATUSES)),
        "communication_quality": draw(st.sampled_from(VALID_QUALITIES)),
        "emotional_balance": draw(safe_text),
        "key_issues": draw(st.lists(safe_text, min_size=1, max_size=3)),
        "advice": draw(st.lists(safe_text, min_size=1, max_size=3)),
        "criticism": {
            "ME": draw(safe_text),
            "OTHER": draw(safe_text),
        },
        "overall_assessment": draw(safe_text),
    }


@st.composite
def sample_strategy(draw):
    """生成完整的审核样本"""
    messages = draw(message_list_strategy(min_size=3, max_size=8))
    analysis = draw(analysis_strategy())
    formatter = TrainingFormatter()
    conversation = formatter.format_conversation(messages)
    assume(len(conversation.strip()) > 0)
    chunk_id = f"chunk_{draw(st.integers(min_value=1, max_value=9999)):04d}"
    return {
        'chunk_id': chunk_id,
        'conversation': conversation,
        'analysis': analysis,
    }


# =============================================================================
# Property 6: 对话和分析格式化正确性
# =============================================================================

class TestProperty6FormattingCorrectness:
    """
    **Feature: relationship-advisor-agent, Property 6: 对话和分析格式化正确性**
    **Validates: Requirements 3.1, 3.2**
    """

    @settings(max_examples=100)
    @given(messages=message_list_strategy(min_size=3, max_size=20))
    def test_conversation_format_lines_start_with_speaker(self, messages):
        """
        **Feature: relationship-advisor-agent, Property 6: 对话和分析格式化正确性**
        **Validates: Requirements 3.1**

        对于任意非系统消息列表，格式化后的对话文本每行必须以
        "ME: " 或 "OTHER: " 开头。
        """
        formatter = TrainingFormatter()
        formatted = formatter.format_conversation(messages)

        if not formatted.strip():
            return  # 全空消息，跳过

        for line in formatted.strip().split('\n'):
            assert line.startswith('ME: ') or line.startswith('OTHER: '), \
                f"行不以 ME:/OTHER: 开头: '{line}'"

    @settings(max_examples=100)
    @given(messages=message_list_strategy(min_size=3, max_size=20))
    def test_conversation_preserves_message_order(self, messages):
        """
        **Feature: relationship-advisor-agent, Property 6: 对话和分析格式化正确性**
        **Validates: Requirements 3.1**

        格式化后的对话保持消息的原始顺序。
        """
        formatter = TrainingFormatter()
        formatted = formatter.format_conversation(messages)
        lines = [l for l in formatted.strip().split('\n') if l.strip()]

        # 提取每行的 speaker
        formatted_speakers = []
        for line in lines:
            if line.startswith('ME: '):
                formatted_speakers.append('ME')
            elif line.startswith('OTHER: '):
                formatted_speakers.append('OTHER')

        # 原始消息中非空文本的 speaker 顺序
        original_speakers = [
            m['speaker'] for m in messages
            if m.get('text_raw', '').strip() and m.get('speaker') != 'SYSTEM'
        ]

        assert formatted_speakers == original_speakers, \
            f"顺序不一致: {formatted_speakers} != {original_speakers}"

    @settings(max_examples=100)
    @given(analysis=analysis_strategy())
    def test_analysis_text_contains_required_tags(self, analysis):
        """
        **Feature: relationship-advisor-agent, Property 6: 对话和分析格式化正确性**
        **Validates: Requirements 3.2**

        对于任意分析结果字典，格式化后的文本必须包含
        【关系状态】【问题】【建议】【批评】【评价】标签。
        """
        formatter = TrainingFormatter()
        text = formatter.format_analysis_text(analysis, 'neutral')

        required_tags = ['【关系状态】', '【问题】', '【建议】', '【批评】', '【评价】']
        for tag in required_tags:
            assert tag in text, f"缺少标签: {tag}"


# =============================================================================
# Property 7: 训练数据有效性
# =============================================================================

class TestProperty7TrainingDataValidity:
    """
    **Feature: relationship-advisor-agent, Property 7: 训练数据有效性**
    **Validates: Requirements 3.3, 3.4, 3.5**
    """

    @settings(max_examples=100)
    @given(analysis=analysis_strategy())
    def test_jsonl_format_has_messages_with_roles(self, analysis):
        """
        **Feature: relationship-advisor-agent, Property 7: 训练数据有效性**
        **Validates: Requirements 3.3, 3.5**

        JSONL 格式：每个样本包含 messages 数组，含 system/user/assistant 角色。
        """
        formatter = TrainingFormatter({'format': 'jsonl'})
        sample = formatter.format_sample("ME: 你好\nOTHER: 嗯", analysis, 'neutral')

        assert 'messages' in sample, "JSONL 格式缺少 messages 字段"
        assert isinstance(sample['messages'], list)

        roles = {m['role'] for m in sample['messages']}
        assert 'system' in roles, "缺少 system 角色"
        assert 'user' in roles, "缺少 user 角色"
        assert 'assistant' in roles, "缺少 assistant 角色"

        # 每条消息都有 role 和 content
        for msg in sample['messages']:
            assert 'role' in msg
            assert 'content' in msg
            assert isinstance(msg['content'], str)
            assert len(msg['content']) > 0

        # 可序列化为有效 JSON
        json_str = json.dumps(sample, ensure_ascii=False)
        parsed = json.loads(json_str)
        assert parsed == sample

    @settings(max_examples=100)
    @given(analysis=analysis_strategy())
    def test_alpaca_format_has_required_fields(self, analysis):
        """
        **Feature: relationship-advisor-agent, Property 7: 训练数据有效性**
        **Validates: Requirements 3.4, 3.5**

        Alpaca 格式：每个样本包含 instruction、input、output 字段。
        """
        formatter = TrainingFormatter({'format': 'alpaca'})
        sample = formatter.format_sample("ME: 你好\nOTHER: 嗯", analysis, 'neutral')

        assert 'instruction' in sample, "Alpaca 格式缺少 instruction"
        assert 'input' in sample, "Alpaca 格式缺少 input"
        assert 'output' in sample, "Alpaca 格式缺少 output"

        assert isinstance(sample['instruction'], str)
        assert isinstance(sample['input'], str)
        assert isinstance(sample['output'], str)
        assert len(sample['instruction']) > 0
        assert len(sample['output']) > 0

        # 可序列化为有效 JSON
        json_str = json.dumps(sample, ensure_ascii=False)
        parsed = json.loads(json_str)
        assert parsed == sample


# =============================================================================
# Property 8: Markdown 审核 Round-Trip
# =============================================================================

class TestProperty8MarkdownRoundTrip:
    """
    **Feature: relationship-advisor-agent, Property 8: Markdown 审核 Round-Trip**
    **Validates: Requirements 4.3, 4.5**
    """

    @settings(max_examples=100)
    @given(sample=sample_strategy())
    def test_markdown_roundtrip_preserves_key_fields(self, sample):
        """
        **Feature: relationship-advisor-agent, Property 8: Markdown 审核 Round-Trip**
        **Validates: Requirements 4.3, 4.5**

        对于任意样本数据，执行 generate → parse round-trip 后，
        关键分析字段应保持一致：
        - relationship_status
        - communication_quality
        - overall_assessment
        """
        formatter = TrainingFormatter({'samples_per_file': 50})

        with tempfile.TemporaryDirectory() as tmpdir:
            # 生成 Markdown
            files = formatter.generate_review_markdown(
                [sample], tmpdir, 'neutral'
            )
            assert len(files) == 1

            # 解析 Markdown
            parsed_samples = formatter.parse_reviewed_markdown(files[0])
            assert len(parsed_samples) == 1

            parsed = parsed_samples[0]
            original = sample['analysis']

            # 验证关键字段保持一致
            assert parsed['analysis'].get('relationship_status') == original['relationship_status'], \
                f"relationship_status 不一致: {parsed['analysis'].get('relationship_status')} != {original['relationship_status']}"

            assert parsed['analysis'].get('communication_quality') == original['communication_quality'], \
                f"communication_quality 不一致"

            assert parsed['analysis'].get('overall_assessment') == original['overall_assessment'], \
                f"overall_assessment 不一致"

    @settings(max_examples=100)
    @given(sample=sample_strategy())
    def test_markdown_roundtrip_preserves_criticism(self, sample):
        """
        **Feature: relationship-advisor-agent, Property 8: Markdown 审核 Round-Trip**
        **Validates: Requirements 4.3, 4.5**

        Round-trip 后 criticism 的 ME 和 OTHER 字段应保持一致。
        """
        formatter = TrainingFormatter({'samples_per_file': 50})

        with tempfile.TemporaryDirectory() as tmpdir:
            files = formatter.generate_review_markdown(
                [sample], tmpdir, 'neutral'
            )
            parsed_samples = formatter.parse_reviewed_markdown(files[0])
            assert len(parsed_samples) == 1

            parsed_crit = parsed_samples[0]['analysis'].get('criticism', {})
            original_crit = sample['analysis']['criticism']

            assert parsed_crit.get('ME') == original_crit['ME'], \
                f"criticism.ME 不一致: '{parsed_crit.get('ME')}' != '{original_crit['ME']}'"
            assert parsed_crit.get('OTHER') == original_crit['OTHER'], \
                f"criticism.OTHER 不一致"

    @settings(max_examples=100)
    @given(sample=sample_strategy())
    def test_markdown_roundtrip_preserves_chunk_id(self, sample):
        """
        **Feature: relationship-advisor-agent, Property 8: Markdown 审核 Round-Trip**
        **Validates: Requirements 4.3**

        Round-trip 后 chunk_id 应保持一致。
        """
        formatter = TrainingFormatter({'samples_per_file': 50})

        with tempfile.TemporaryDirectory() as tmpdir:
            files = formatter.generate_review_markdown(
                [sample], tmpdir, 'neutral'
            )
            parsed_samples = formatter.parse_reviewed_markdown(files[0])
            assert len(parsed_samples) == 1
            assert parsed_samples[0]['chunk_id'] == sample['chunk_id']
