"""
test_advisor_extractor_properties.py
对话提取属性测试

**Property 1: 动态事件分段正确性**
**Property 2: 对话片段提取不变量**
**Property 3: 滑动窗口步长一致性**
**Validates: Requirements 1.2, 1.3, 1.4, 1.5, 1.7**

运行方式：
    conda activate wechatDHA
    python -m pytest tests/test_advisor_extractor_properties.py -v
"""

from datetime import datetime, timedelta

import pytest
from hypothesis import given, settings, strategies as st, assume

from scripts.advisor.extractor import ConversationExtractor


# =============================================================================
# Hypothesis 策略
# =============================================================================

@st.composite
def timed_message_strategy(draw, base_time=None):
    """生成带时间戳的单条消息"""
    speaker = draw(st.sampled_from(['ME', 'OTHER']))
    text = draw(st.text(
        alphabet=st.characters(whitelist_categories=('L', 'N', 'P', 'Z')),
        min_size=1,
        max_size=80,
    ))
    return {'speaker': speaker, 'text_raw': text, 'type': 'text', 'modality': 'text'}


@st.composite
def timed_message_list_strategy(draw, min_size=15, max_size=80):
    """
    生成带递增时间戳的消息列表。
    相邻消息间隔在 10 秒到 8 小时之间随机。
    """
    n = draw(st.integers(min_value=min_size, max_value=max_size))
    base = datetime(2025, 6, 1, 10, 0, 0)
    messages = []
    current_time = base

    for _ in range(n):
        speaker = draw(st.sampled_from(['ME', 'OTHER']))
        text = draw(st.text(
            alphabet=st.characters(whitelist_categories=('L', 'N', 'P', 'Z')),
            min_size=1,
            max_size=60,
        ))
        gap_seconds = draw(st.integers(min_value=10, max_value=28800))  # 10s ~ 8h
        current_time = current_time + timedelta(seconds=gap_seconds)

        messages.append({
            'speaker': speaker,
            'text_raw': text,
            'ts': current_time.strftime('%Y-%m-%d %H:%M:%S'),
            'type': 'text',
            'modality': 'text',
        })

    return messages


@st.composite
def sliding_window_config_strategy(draw):
    """生成合法的滑动窗口配置"""
    min_msg = draw(st.integers(min_value=5, max_value=10))
    max_msg = draw(st.integers(min_value=min_msg + 5, max_value=min_msg + 20))
    window = draw(st.integers(min_value=min_msg, max_value=max_msg))
    step = draw(st.integers(min_value=1, max_value=window))
    return {
        'segmentation_strategy': 'sliding_window',
        'window_size': window,
        'step_size': step,
        'min_messages': min_msg,
        'max_messages': max_msg,
        'exclude_system': True,
        'exclude_types': ['time_gap'],
    }


# =============================================================================
# Property 1: 动态事件分段正确性
# =============================================================================

class TestProperty1EventSegmentation:
    """
    **Feature: relationship-advisor-agent, Property 1: 动态事件分段正确性**
    **Validates: Requirements 1.2**
    """

    @settings(max_examples=100)
    @given(messages=timed_message_list_strategy(min_size=20, max_size=80))
    def test_event_segments_respect_time_gap_or_emotion_shift(self, messages):
        """
        **Feature: relationship-advisor-agent, Property 1: 动态事件分段正确性**
        **Validates: Requirements 1.2**

        对于任意消息序列，使用动态事件分段时，任意两个相邻片段之间
        的边界处必须满足以下至少一个条件：
        1. 时间间隔 >= time_gap_threshold
        2. 检测到情绪转折点
        """
        threshold = 21600  # 6 小时
        config = {
            'segmentation_strategy': 'event_based',
            'time_gap_threshold': threshold,
            'emotion_shift_threshold': 0.5,
            'min_messages': 5,
            'max_messages': 30,
            'exclude_system': True,
            'exclude_types': ['time_gap'],
        }
        extractor = ConversationExtractor(config)
        filtered = extractor._filter_messages(messages)
        assume(len(filtered) >= 10)

        segments = extractor._segment_by_events(filtered)

        if len(segments) < 2:
            return  # 只有一个或零个段，无需验证边界

        for i in range(len(segments) - 1):
            last_msg = segments[i][-1]
            # 找到下一段的第一条消息在原始 filtered 中的位置
            first_next = segments[i + 1][0]

            # 计算边界处的时间间隔
            time_gap = extractor._compute_time_gap(last_msg, first_next)

            # 计算边界处的情绪转折
            sent_last = extractor._get_sentiment(last_msg)
            sent_first = extractor._get_sentiment(first_next)

            has_time_gap = time_gap is not None and time_gap >= threshold
            has_emotion_shift = (
                sent_last is not None
                and sent_first is not None
                and abs(sent_last - sent_first) >= 0.5
            )
            # 也可能是因为前一段达到了 max_messages 被强制切分
            prev_at_max = len(segments[i]) >= config['max_messages']

            assert has_time_gap or has_emotion_shift or prev_at_max, (
                f"相邻段 {i} 和 {i+1} 之间既无时间间隔 >= {threshold}s "
                f"(实际: {time_gap}s)，也无情绪转折，也未达到 max_messages"
            )


# =============================================================================
# Property 2: 对话片段提取不变量
# =============================================================================

class TestProperty2ExtractionInvariants:
    """
    **Feature: relationship-advisor-agent, Property 2: 对话片段提取不变量**
    **Validates: Requirements 1.3, 1.5, 1.7**
    """

    @settings(max_examples=100)
    @given(messages=timed_message_list_strategy(min_size=20, max_size=80))
    def test_sliding_window_chunk_size_and_count(self, messages):
        """
        **Feature: relationship-advisor-agent, Property 2: 对话片段提取不变量**
        **Validates: Requirements 1.3, 1.5, 1.7**

        对于任意消息序列（滑动窗口模式）：
        - 每个片段的消息数量 >= min_messages
        - 每个片段的消息数量 <= max_messages (window_size)
        - 提取总数量 <= num_chunks
        - 每个片段至少包含一条非系统消息
        """
        min_msg = 5
        max_msg = 20
        num_chunks = 10
        config = {
            'segmentation_strategy': 'sliding_window',
            'window_size': max_msg,
            'step_size': 5,
            'min_messages': min_msg,
            'max_messages': max_msg,
            'exclude_system': True,
            'exclude_types': ['time_gap'],
        }
        extractor = ConversationExtractor(config)
        chunks = extractor.extract_chunks_from_messages(messages, num_chunks=num_chunks)

        assert len(chunks) <= num_chunks, \
            f"提取数量 {len(chunks)} 超过限制 {num_chunks}"

        for chunk in chunks:
            msgs = chunk['messages']
            assert len(msgs) >= min_msg, \
                f"片段消息数 {len(msgs)} < min_messages {min_msg}"
            assert len(msgs) <= max_msg, \
                f"片段消息数 {len(msgs)} > max_messages {max_msg}"

            non_system = [m for m in msgs if m.get('speaker') != 'SYSTEM']
            assert len(non_system) > 0, "片段中没有非系统消息"

    @settings(max_examples=100)
    @given(messages=timed_message_list_strategy(min_size=20, max_size=80))
    def test_event_based_chunk_invariants(self, messages):
        """
        **Feature: relationship-advisor-agent, Property 2: 对话片段提取不变量**
        **Validates: Requirements 1.3, 1.5, 1.7**

        对于任意消息序列（事件分段模式），同样的不变量成立。
        """
        min_msg = 5
        max_msg = 30
        num_chunks = 15
        config = {
            'segmentation_strategy': 'event_based',
            'time_gap_threshold': 21600,
            'emotion_shift_threshold': 0.5,
            'min_messages': min_msg,
            'max_messages': max_msg,
            'exclude_system': True,
            'exclude_types': ['time_gap'],
        }
        extractor = ConversationExtractor(config)
        chunks = extractor.extract_chunks_from_messages(messages, num_chunks=num_chunks)

        assert len(chunks) <= num_chunks

        for chunk in chunks:
            msgs = chunk['messages']
            assert len(msgs) >= min_msg
            assert len(msgs) <= max_msg
            non_system = [m for m in msgs if m.get('speaker') != 'SYSTEM']
            assert len(non_system) > 0


# =============================================================================
# Property 3: 滑动窗口步长一致性
# =============================================================================

class TestProperty3SlidingWindowStepConsistency:
    """
    **Feature: relationship-advisor-agent, Property 3: 滑动窗口步长一致性**
    **Validates: Requirements 1.4**
    """

    @settings(max_examples=100)
    @given(
        messages=timed_message_list_strategy(min_size=30, max_size=80),
        config=sliding_window_config_strategy(),
    )
    def test_sliding_window_step_offset(self, messages, config):
        """
        **Feature: relationship-advisor-agent, Property 3: 滑动窗口步长一致性**
        **Validates: Requirements 1.4**

        对于任意使用滑动窗口模式提取的连续片段对，
        后一个片段的起始消息在原始序列中的位置与前一个片段的起始位置之差
        等于配置的步长。
        """
        extractor = ConversationExtractor(config)
        filtered = extractor._filter_messages(messages)
        assume(len(filtered) >= config['min_messages'] + config['step_size'])

        segments = extractor._segment_by_sliding_window(filtered)

        if len(segments) < 2:
            return

        step = config['step_size']

        # 找到每个段的第一条消息在 filtered 中的索引
        for i in range(len(segments) - 1):
            first_curr = segments[i][0]
            first_next = segments[i + 1][0]

            idx_curr = None
            idx_next = None
            for j, m in enumerate(filtered):
                if m is first_curr and idx_curr is None:
                    idx_curr = j
                if m is first_next and idx_next is None:
                    idx_next = j
                if idx_curr is not None and idx_next is not None:
                    break

            assert idx_curr is not None and idx_next is not None
            actual_step = idx_next - idx_curr
            assert actual_step == step, \
                f"连续片段起始偏移 {actual_step} != 配置步长 {step}"
