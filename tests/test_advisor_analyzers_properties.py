"""
Property 11: 回复时间模式检测正确性
Property 12: 中立性不变量

**Feature: relationship-advisor-agent**
**Validates: Requirements 9.2, 9.3, 9.5, 12.1, 12.5**
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from hypothesis import given, settings, strategies as st, assume

# 添加项目根目录
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.advisor.analyzers import ResponseTimeAnalyzer, NeutralityChecker


# ============================================================
# 策略定义
# ============================================================

@st.composite
def timed_message_pair_strategy(draw):
    """生成带时间戳的消息对（ME 发消息 → OTHER 回复）"""
    base_time = datetime(2025, 6, 1, 10, 0, 0)
    gap_seconds = draw(st.integers(min_value=1, max_value=86400))  # 1秒 ~ 24小时
    
    reply_text_options = draw(st.sampled_from([
        '哦', '嗯', '好', '知道了',  # 冷淡短回复
        '好的，我知道了，今天确实挺累的',  # 正常回复
        '你怎么总是这样！受不了了！',  # 争吵回复
    ]))
    
    me_msg = {
        'speaker': 'ME',
        'text_raw': '今天好累啊，工作压力好大',
        'ts': base_time.strftime('%Y-%m-%d %H:%M:%S'),
    }
    other_msg = {
        'speaker': 'OTHER',
        'text_raw': reply_text_options,
        'ts': (base_time + timedelta(seconds=gap_seconds)).strftime('%Y-%m-%d %H:%M:%S'),
    }
    
    return [me_msg, other_msg], gap_seconds


@st.composite
def conversation_with_times_strategy(draw):
    """生成带时间戳的多轮对话"""
    num_messages = draw(st.integers(min_value=4, max_value=20))
    base_time = datetime(2025, 6, 1, 10, 0, 0)
    
    messages = []
    current_time = base_time
    
    for i in range(num_messages):
        gap = draw(st.integers(min_value=1, max_value=7200))
        current_time += timedelta(seconds=gap)
        speaker = 'ME' if i % 2 == 0 else 'OTHER'
        text = draw(st.text(
            alphabet=st.characters(whitelist_categories=('L', 'N', 'P')),
            min_size=1, max_size=50,
        ))
        messages.append({
            'speaker': speaker,
            'text_raw': text,
            'ts': current_time.strftime('%Y-%m-%d %H:%M:%S'),
        })
    
    return messages


analysis_text_strategy = st.text(
    alphabet=st.characters(whitelist_categories=('L', 'N', 'P', 'Z')),
    min_size=10, max_size=500,
)


# ============================================================
# Property 11: 回复时间模式检测正确性
# ============================================================

class TestProperty11ResponseTimeDetection:
    """Property 11: 回复时间模式检测正确性
    
    **Validates: Requirements 9.2, 9.3, 9.5**
    """

    @settings(max_examples=100)
    @given(data=timed_message_pair_strategy())
    def test_cold_treatment_detection(self, data):
        """回复时间 > 冷暴力阈值 + 短回复 → 检测到冷暴力迹象。
        
        **Validates: Requirements 9.2**
        """
        messages, gap_seconds = data
        analyzer = ResponseTimeAnalyzer(
            cold_threshold_hours=1.0,
            argument_threshold_seconds=30.0,
            min_cold_messages=1,  # 降低阈值以便测试单条消息
        )
        stats = analyzer.analyze(messages)
        
        reply_text = messages[1]['text_raw']
        is_short_cold = len(reply_text) <= 5 and any(
            kw in reply_text for kw in analyzer.COLD_KEYWORDS
        )
        
        # 如果回复时间 > 1小时 且 是冷淡短回复，应检测到冷暴力
        if gap_seconds > 3600 and is_short_cold:
            assert stats.cold_treatment_detected, (
                f"gap={gap_seconds}s, reply='{reply_text}' 应检测到冷暴力"
            )

    @settings(max_examples=100)
    @given(data=timed_message_pair_strategy())
    def test_argument_detection_requires_rapid_exchange(self, data):
        """争吵检测需要快速来回 + 冲突关键词。
        
        **Validates: Requirements 9.3**
        """
        messages, gap_seconds = data
        analyzer = ResponseTimeAnalyzer(
            cold_threshold_hours=1.0,
            argument_threshold_seconds=30.0,
        )
        stats = analyzer.analyze(messages)
        
        # 只有 2 条消息不足以构成争吵（需要至少 3 轮快速来回）
        # 所以 argument_detected 应该为 False
        # 这验证了争吵检测不会误报单轮对话
        if len(messages) <= 2:
            assert not stats.argument_detected

    @settings(max_examples=100)
    @given(messages=conversation_with_times_strategy())
    def test_response_asymmetry_in_range(self, messages):
        """回复不对称度分数必须在 [-1, 1] 范围内。
        
        **Validates: Requirements 9.5**
        """
        analyzer = ResponseTimeAnalyzer()
        stats = analyzer.analyze(messages)
        
        assert -1.0 <= stats.response_asymmetry <= 1.0, (
            f"response_asymmetry={stats.response_asymmetry} 超出 [-1, 1] 范围"
        )

    def test_argument_detection_with_rapid_conflict(self):
        """快速来回 + 冲突关键词 → 检测到争吵。
        
        **Validates: Requirements 9.3**
        """
        base = datetime(2025, 6, 1, 10, 0, 0)
        messages = []
        conflict_texts = [
            ('ME', '你怎么又这样！'),
            ('OTHER', '你凭什么说我！'),
            ('ME', '你总是这样！受不了了！'),
            ('OTHER', '你为什么不反省自己！'),
            ('ME', '够了！别说了！'),
            ('OTHER', '你才够了！'),
        ]
        for i, (speaker, text) in enumerate(conflict_texts):
            messages.append({
                'speaker': speaker,
                'text_raw': text,
                'ts': (base + timedelta(seconds=i * 10)).strftime('%Y-%m-%d %H:%M:%S'),
            })
        
        analyzer = ResponseTimeAnalyzer(argument_threshold_seconds=30.0)
        stats = analyzer.analyze(messages)
        assert stats.argument_detected, "快速冲突对话应检测到争吵"

    def test_cold_treatment_with_long_delay_and_short_reply(self):
        """长时间不回复 + 冷淡短回复 → 冷暴力。
        
        **Validates: Requirements 9.2**
        """
        base = datetime(2025, 6, 1, 10, 0, 0)
        messages = [
            {'speaker': 'ME', 'text_raw': '你在干嘛？', 'ts': base.strftime('%Y-%m-%d %H:%M:%S')},
            {'speaker': 'OTHER', 'text_raw': '嗯', 'ts': (base + timedelta(hours=3)).strftime('%Y-%m-%d %H:%M:%S')},
            {'speaker': 'OTHER', 'text_raw': '哦', 'ts': (base + timedelta(hours=3, minutes=1)).strftime('%Y-%m-%d %H:%M:%S')},
            {'speaker': 'OTHER', 'text_raw': '好', 'ts': (base + timedelta(hours=3, minutes=2)).strftime('%Y-%m-%d %H:%M:%S')},
        ]
        
        analyzer = ResponseTimeAnalyzer(cold_threshold_hours=1.0, min_cold_messages=3)
        stats = analyzer.analyze(messages)
        assert stats.cold_treatment_detected, "3小时后连续冷淡回复应检测到冷暴力"


# ============================================================
# Property 12: 中立性不变量
# ============================================================

class TestProperty12NeutralityInvariants:
    """Property 12: 中立性不变量
    
    **Validates: Requirements 12.1, 12.5**
    """

    @settings(max_examples=100)
    @given(text=analysis_text_strategy)
    def test_neutrality_score_in_range(self, text):
        """中立性分数必须在 [0, 1] 范围内。
        
        **Validates: Requirements 12.1**
        """
        checker = NeutralityChecker()
        score = checker.check(text)
        
        assert 0.0 <= score.overall_score <= 1.0, (
            f"overall_score={score.overall_score} 超出 [0, 1] 范围"
        )

    @settings(max_examples=100)
    @given(text=analysis_text_strategy)
    def test_criticism_ratios_sum_to_one_or_zero(self, text):
        """批评比例之和为 1（有批评时）或都为 0（无批评时）。
        
        **Validates: Requirements 12.5**
        """
        checker = NeutralityChecker()
        score = checker.check(text)
        
        total = score.me_criticism_ratio + score.other_criticism_ratio
        # 要么都是 0（无批评），要么和为 1
        assert abs(total) < 0.01 or abs(total - 1.0) < 0.01, (
            f"批评比例之和 {total} 不为 0 或 1"
        )

    @settings(max_examples=100)
    @given(text=analysis_text_strategy)
    def test_balance_score_in_range(self, text):
        """批评平衡度分数在 [0, 1] 范围内。
        
        **Validates: Requirements 12.5**
        """
        checker = NeutralityChecker()
        score = checker.check(text)
        
        assert 0.0 <= score.balance_score <= 1.0, (
            f"balance_score={score.balance_score} 超出 [0, 1] 范围"
        )

    def test_balanced_analysis_has_high_neutrality(self):
        """对双方均衡批评的分析应有较高中立性分数。
        
        **Validates: Requirements 12.1**
        """
        balanced_text = (
            "ME 的问题是沟通方式过于直接，应该注意语气。"
            "OTHER 的问题是回应不够积极，需要改善态度。"
            "双方都需要注意倾听对方的感受。"
        )
        
        checker = NeutralityChecker()
        score = checker.check(balanced_text)
        assert score.overall_score >= 0.6, (
            f"均衡批评的分析中立性分数 {score.overall_score} 应 >= 0.6"
        )

    def test_one_sided_analysis_has_low_neutrality(self):
        """只批评一方的分析应有较低中立性分数。
        
        **Validates: Requirements 12.1**
        """
        one_sided_text = (
            "你的问题很严重，你应该反省。"
            "你不应该这样做，你的错误很明显。"
            "你需要改变你的态度，你的行为不对。"
        )
        
        checker = NeutralityChecker()
        score = checker.check(one_sided_text)
        assert score.overall_score < 0.8, (
            f"单方面批评的分析中立性分数 {score.overall_score} 应 < 0.8"
        )
