"""
实时对话引擎测试

Property 14: 对话上下文窗口不变量
- 上下文窗口大小永远 <= context_window
- 超出窗口时，保留最近的 N 条消息
- 模式切换不影响历史

Requirements: 16.1, 16.2, 16.3, 16.4, 16.5, 16.6, 16.7
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from hypothesis import given, settings
    from hypothesis import strategies as st
    HAS_HYPOTHESIS = True
except ImportError:
    HAS_HYPOTHESIS = False

from scripts.advisor.streaming import StreamingDialogueEngine, DialogueMode


# ---------------------------------------------------------------------------
# Property 14: 对话上下文窗口不变量（Hypothesis）
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not HAS_HYPOTHESIS, reason="hypothesis 未安装")
class TestContextWindowProperty:
    """Property 14: 对话上下文窗口不变量"""

    @settings(max_examples=100)
    @given(st.lists(st.text(min_size=1, max_size=100), min_size=1, max_size=30))
    def test_context_window_invariant(self, messages):
        """Feature: relationship-advisor-agent, Property 14: 对话上下文窗口不变量"""
        engine = StreamingDialogueEngine({'context_window': 10})
        for msg in messages:
            engine.add_message(msg)
        context = engine.get_context()
        assert len(context) <= 10
        if len(messages) > 10:
            assert context == [m for m in messages[-10:]]

    @settings(max_examples=100)
    @given(st.lists(st.text(min_size=1, max_size=50), min_size=1, max_size=20))
    def test_window_size_3(self, messages):
        """小窗口也保持不变量"""
        engine = StreamingDialogueEngine({'context_window': 3})
        for msg in messages:
            engine.add_message(msg)
        context = engine.get_context()
        assert len(context) <= 3
        if len(messages) > 3:
            assert context == [m for m in messages[-3:]]


# ---------------------------------------------------------------------------
# 基础功能测试
# ---------------------------------------------------------------------------

class TestStreamingDialogueEngineBasic:
    """基础功能测试（不需要 API/GPU）"""

    def test_default_mode_is_listen(self):
        engine = StreamingDialogueEngine()
        assert engine.mode == DialogueMode.LISTEN

    def test_switch_mode(self):
        engine = StreamingDialogueEngine()
        engine.switch_mode('consult')
        assert engine.mode == DialogueMode.CONSULT
        engine.switch_mode('listen')
        assert engine.mode == DialogueMode.LISTEN

    def test_invalid_mode_raises(self):
        engine = StreamingDialogueEngine()
        with pytest.raises(ValueError):
            engine.switch_mode('invalid')

    def test_add_message(self):
        engine = StreamingDialogueEngine({'context_window': 5})
        engine.add_message("hello", role='user')
        engine.add_message("hi there", role='assistant')
        assert len(engine.get_context()) == 2
        assert engine.get_context()[0] == "hello"
        assert engine.get_context()[1] == "hi there"

    def test_context_window_overflow(self):
        engine = StreamingDialogueEngine({'context_window': 3})
        for i in range(10):
            engine.add_message(f"msg_{i}")
        context = engine.get_context()
        assert len(context) == 3
        assert context == ['msg_7', 'msg_8', 'msg_9']

    def test_clear_history(self):
        engine = StreamingDialogueEngine()
        engine.add_message("test")
        engine.clear_history()
        assert len(engine.get_context()) == 0

    def test_history_preserves_mode(self):
        engine = StreamingDialogueEngine({'context_window': 10})
        engine.switch_mode('listen')
        engine.add_message("listen msg")
        engine.switch_mode('consult')
        engine.add_message("consult msg")

        history = engine.get_history()
        assert history[0].mode == 'listen'
        assert history[1].mode == 'consult'

    def test_mode_switch_does_not_clear_history(self):
        engine = StreamingDialogueEngine({'context_window': 10})
        engine.add_message("before switch")
        engine.switch_mode('consult')
        engine.add_message("after switch")
        assert len(engine.get_context()) == 2

    def test_get_history_returns_list(self):
        engine = StreamingDialogueEngine()
        engine.add_message("a")
        engine.add_message("b")
        history = engine.get_history()
        assert isinstance(history, list)
        assert len(history) == 2

    def test_config_defaults(self):
        engine = StreamingDialogueEngine()
        assert engine._config.context_window == 10
        assert engine._config.local_model == 'Qwen3-8B-Instruct'
        assert engine._config.stream is True

    def test_custom_config(self):
        engine = StreamingDialogueEngine({
            'context_window': 5,
            'local_model': 'custom-model',
            'temperature': 0.3,
        })
        assert engine._config.context_window == 5
        assert engine._config.local_model == 'custom-model'
        assert engine._config.temperature == 0.3


# ---------------------------------------------------------------------------
# _build_messages 测试
# ---------------------------------------------------------------------------

class TestBuildMessages:
    """消息构建测试"""

    def test_build_messages_basic(self):
        engine = StreamingDialogueEngine({'context_window': 10})
        engine.add_message("hello", role='user')

        messages = engine._build_messages(
            system_prompt="You are helpful.",
            user_message="hello",
        )
        assert messages[0]['role'] == 'system'
        assert messages[-1]['role'] == 'user'
        assert messages[-1]['content'] == 'hello'

    def test_build_messages_with_history(self):
        engine = StreamingDialogueEngine({'context_window': 10})
        engine.add_message("first", role='user')
        engine.add_message("response", role='assistant')
        engine.add_message("second", role='user')

        messages = engine._build_messages(
            system_prompt="sys",
            user_message="second",
        )
        # system + first user + assistant response + current user
        assert len(messages) == 4
        assert messages[0]['role'] == 'system'
        assert messages[1]['content'] == 'first'
        assert messages[2]['content'] == 'response'
        assert messages[3]['content'] == 'second'

    def test_build_messages_with_context_hint(self):
        engine = StreamingDialogueEngine({'context_window': 10})
        engine.add_message("hi", role='user')

        messages = engine._build_messages(
            system_prompt="sys",
            user_message="hi",
            context_hint="[相关历史] 之前聊过工作",
        )
        # 最后一条 user message 应包含 context_hint
        assert "[相关历史]" in messages[-1]['content']
