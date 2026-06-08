"""
对话引擎属性测试

Property 14: 对话上下文窗口不变量
**Feature: relationship-advisor-agent, Property 14: 对话上下文窗口不变量**
**Validates: Requirements 16.4**

测试策略：
- 不加载真实模型，直接测试 StreamingDialogueEngine 的上下文管理逻辑
- 验证上下文窗口大小始终不超过配置值，且保留最近的消息
"""

import pytest
from hypothesis import given, settings, strategies as st

from scripts.advisor.streaming import StreamingDialogueEngine


# =============================================================================
# 测试策略
# =============================================================================

@st.composite
def message_text_strategy(draw):
    """生成对话消息文本"""
    words = draw(st.lists(
        st.sampled_from([
            '你好', '今天', '工作', '开心', '难过', '吃饭', '睡觉',
            '想你', '在吗', '好的', '嗯', '哈哈', '累了', '回家',
            '怎么了', '没事', '谢谢', '加油', '晚安', '早安',
        ]),
        min_size=1, max_size=8,
    ))
    return ''.join(words)


@st.composite
def dialogue_sequence_strategy(draw, min_size=1, max_size=30):
    """生成对话序列（交替 user/assistant）"""
    length = draw(st.integers(min_value=min_size, max_value=max_size))
    messages = []
    for i in range(length):
        role = 'user' if i % 2 == 0 else 'assistant'
        text = draw(message_text_strategy())
        messages.append({'role': role, 'content': text})
    return messages


# =============================================================================
# Property 14: 对话上下文窗口不变量
# =============================================================================

class TestDialogueContextWindowInvariant:
    """Property 14: 对话上下文窗口不变量

    **Feature: relationship-advisor-agent, Property 14: 对话上下文窗口不变量**
    **Validates: Requirements 16.4**

    For any 对话序列，当消息轮数超过配置的上下文窗口大小（默认 10 轮）时，
    上下文中只保留最近的 N 轮对话。
    """

    @settings(max_examples=100, deadline=None)
    @given(
        dialogue_sequence_strategy(min_size=1, max_size=30),
        st.integers(min_value=2, max_value=15),
    )
    def test_context_never_exceeds_window_size(self, messages, window_size):
        """上下文大小永远不超过配置的窗口大小

        **Validates: Requirements 16.4**
        """
        engine = StreamingDialogueEngine(
            config={'context_window': window_size}
        )

        for msg in messages:
            engine.add_message(msg['content'], role=msg['role'])

        context = engine.get_context()
        assert len(context) <= window_size

    @settings(max_examples=100, deadline=None)
    @given(
        dialogue_sequence_strategy(min_size=5, max_size=30),
        st.integers(min_value=3, max_value=10),
    )
    def test_context_preserves_most_recent_messages(self, messages, window_size):
        """上下文保留的是最近的消息

        **Validates: Requirements 16.4**
        """
        engine = StreamingDialogueEngine(
            config={'context_window': window_size}
        )

        for msg in messages:
            engine.add_message(msg['content'], role=msg['role'])

        context = engine.get_context()

        if len(messages) > window_size:
            # 应该保留最后 window_size 条消息
            expected = messages[-window_size:]
            assert len(context) == window_size
            for ctx_msg, exp_msg in zip(context, expected):
                assert ctx_msg['content'] == exp_msg['content']
                assert ctx_msg['role'] == exp_msg['role']
        else:
            # 消息数不超过窗口，全部保留
            assert len(context) == len(messages)

    @settings(max_examples=100, deadline=None)
    @given(
        dialogue_sequence_strategy(min_size=1, max_size=20),
        st.integers(min_value=2, max_value=10),
    )
    def test_context_maintains_message_order(self, messages, window_size):
        """上下文中的消息保持原始时间顺序

        **Validates: Requirements 16.4**
        """
        engine = StreamingDialogueEngine(
            config={'context_window': window_size}
        )

        for msg in messages:
            engine.add_message(msg['content'], role=msg['role'])

        context = engine.get_context()

        # 验证上下文中的消息顺序与原始消息的尾部一致
        if len(messages) > window_size:
            tail = messages[-window_size:]
        else:
            tail = messages

        for i, (ctx_msg, orig_msg) in enumerate(zip(context, tail)):
            assert ctx_msg['content'] == orig_msg['content'], (
                f"位置 {i}: 上下文 '{ctx_msg['content']}' != 原始 '{orig_msg['content']}'"
            )

    @settings(max_examples=100, deadline=None)
    @given(st.integers(min_value=2, max_value=15))
    def test_reset_context_clears_all(self, window_size):
        """reset_context 应清空所有上下文

        **Validates: Requirements 16.4**
        """
        engine = StreamingDialogueEngine(
            config={'context_window': window_size}
        )

        # 添加一些消息
        for i in range(window_size + 5):
            engine.add_message(f"消息{i}", role='user')

        assert len(engine.get_context()) > 0

        engine.reset_context()
        assert len(engine.get_context()) == 0

    @settings(max_examples=100, deadline=None)
    @given(st.integers(min_value=2, max_value=10))
    def test_switch_mode_preserves_context(self, window_size):
        """切换模式不应影响已有上下文

        **Validates: Requirements 16.4**
        """
        engine = StreamingDialogueEngine(
            config={'context_window': window_size, 'default_mode': 'listen'}
        )

        # 添加消息
        engine.add_message("你好", role='user')
        engine.add_message("你好，有什么想聊的吗？", role='assistant')

        context_before = engine.get_context()

        # 切换模式
        engine.switch_mode('consult')

        context_after = engine.get_context()

        assert len(context_before) == len(context_after)
        for before, after in zip(context_before, context_after):
            assert before['content'] == after['content']
            assert before['role'] == after['role']
