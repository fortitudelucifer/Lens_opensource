"""
test_advisor_router_properties.py
模型路由属性测试

**Property 13: 模型路由正确性**
**Validates: Requirements 15.2, 15.3, 15.6**

For any 分析请求：
- 复杂度评分在 [0, 1] 范围内
- 路由决策必须匹配配置的阈值范围（simple ≤ 0.3 → local_qwen3,
  medium ≤ 0.6 → local_qwen3_thinking, complex > 0.6 → deepseek_reasoner）
- 当云端调用累计成本超过预算上限时，后续请求必须路由到本地模型

运行方式：
    conda activate wechatDHA
    python -m pytest tests/test_advisor_router_properties.py -v
"""

import pytest
from hypothesis import given, settings, strategies as st, assume

from scripts.advisor.router import ModelRouter


# =============================================================================
# Hypothesis 策略
# =============================================================================

# 有效的复杂度阈值（simple < medium，都在 0-1 之间）
@st.composite
def threshold_strategy(draw):
    simple = draw(st.floats(min_value=0.05, max_value=0.45, allow_nan=False, allow_infinity=False))
    medium = draw(st.floats(min_value=simple + 0.05, max_value=0.95, allow_nan=False, allow_infinity=False))
    return {'simple': simple, 'medium': medium, 'complex': 1.0}


@st.composite
def task_with_complexity_strategy(draw):
    """生成带有预设复杂度评分的任务"""
    complexity = draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False))
    return {'complexity_score': complexity, 'type': 'analysis', 'conversation': ''}


@st.composite
def task_without_complexity_strategy(draw):
    """生成需要自动评估复杂度的任务"""
    # 随机对话长度
    msg_count = draw(st.integers(min_value=0, max_value=100))
    conversation = '\n'.join([f"ME: msg{i}" for i in range(msg_count)])

    analysis_type = draw(st.sampled_from(['neutral', 'supportive', 'psychoanalytic', 'long_context']))

    # 随机插入情绪关键词
    emotion_keywords = ['生气', '伤心', '分手', '崩溃', '讨厌', '受不了']
    num_emotions = draw(st.integers(min_value=0, max_value=len(emotion_keywords)))
    for kw in emotion_keywords[:num_emotions]:
        conversation += f"\nME: 我{kw}了"

    return {'conversation': conversation, 'type': analysis_type}


@st.composite
def budget_strategy(draw):
    """生成预算配置"""
    daily = draw(st.floats(min_value=0.01, max_value=100.0, allow_nan=False, allow_infinity=False))
    monthly = draw(st.floats(min_value=daily, max_value=1000.0, allow_nan=False, allow_infinity=False))
    return {'daily_limit_usd': daily, 'monthly_limit_usd': monthly}


def _make_router(thresholds=None, budget=None):
    """创建测试用 ModelRouter"""
    config = {
        'complexity_thresholds': thresholds or {'simple': 0.3, 'medium': 0.6, 'complex': 1.0},
        'budget': budget or {'daily_limit_usd': 5.0, 'monthly_limit_usd': 100.0},
        'fallback_model': 'local_qwen3',
        'routing_rules': {
            'simple': 'local_qwen3',
            'medium': 'local_qwen3_thinking',
            'complex': 'deepseek_reasoner',
            'long_context': 'kimi_k25',
        },
    }
    return ModelRouter(config)


# =============================================================================
# Property 13: 模型路由正确性
# =============================================================================

class TestProperty13ModelRouting:
    """
    **Feature: relationship-advisor-agent, Property 13: 模型路由正确性**
    **Validates: Requirements 15.2, 15.3, 15.6**
    """

    # -----------------------------------------------------------------
    # 13a: 复杂度评分在 [0, 1] 范围内
    # -----------------------------------------------------------------

    @settings(max_examples=100)
    @given(task=task_without_complexity_strategy())
    def test_complexity_score_in_range(self, task):
        """
        **Feature: relationship-advisor-agent, Property 13: 模型路由正确性**
        **Validates: Requirements 15.2**

        对于任意任务，_assess_complexity 返回的复杂度评分必须在 [0, 1] 范围内。
        """
        router = _make_router()
        score = router._assess_complexity(task)
        assert 0.0 <= score <= 1.0, f"复杂度评分 {score} 超出 [0, 1] 范围"

    # -----------------------------------------------------------------
    # 13b: 路由决策匹配配置阈值
    # -----------------------------------------------------------------

    @settings(max_examples=100)
    @given(
        task=task_with_complexity_strategy(),
        thresholds=threshold_strategy(),
    )
    def test_routing_matches_thresholds(self, task, thresholds):
        """
        **Feature: relationship-advisor-agent, Property 13: 模型路由正确性**
        **Validates: Requirements 15.3**

        对于任意复杂度评分和阈值配置，路由决策必须匹配：
        - score ≤ simple → local_qwen3
        - simple < score ≤ medium → local_qwen3_thinking
        - score > medium → deepseek_reasoner
        """
        router = _make_router(thresholds=thresholds)
        backend = router.route(task)
        score = task['complexity_score']

        if score <= thresholds['simple']:
            assert backend == 'local_qwen3', \
                f"score={score:.3f} ≤ simple={thresholds['simple']:.3f}，应路由到 local_qwen3，实际: {backend}"
        elif score <= thresholds['medium']:
            assert backend == 'local_qwen3_thinking', \
                f"score={score:.3f} ≤ medium={thresholds['medium']:.3f}，应路由到 local_qwen3_thinking，实际: {backend}"
        else:
            assert backend == 'deepseek_reasoner', \
                f"score={score:.3f} > medium={thresholds['medium']:.3f}，应路由到 deepseek_reasoner，实际: {backend}"

    # -----------------------------------------------------------------
    # 13c: 预算超限时强制路由到本地模型
    # -----------------------------------------------------------------

    @settings(max_examples=100)
    @given(
        task=task_with_complexity_strategy(),
        budget=budget_strategy(),
    )
    def test_budget_exceeded_routes_to_local(self, task, budget):
        """
        **Feature: relationship-advisor-agent, Property 13: 模型路由正确性**
        **Validates: Requirements 15.6**

        当云端调用累计成本超过日预算上限时，
        后续所有请求必须路由到本地 fallback 模型。
        """
        router = _make_router(budget=budget)

        # 模拟累计成本超过日预算
        router._daily_cost = budget['daily_limit_usd'] + 0.01

        backend = router.route(task)
        assert backend == 'local_qwen3', \
            f"日预算超限后应路由到 local_qwen3，实际: {backend}"

    @settings(max_examples=100)
    @given(
        task=task_with_complexity_strategy(),
        budget=budget_strategy(),
    )
    def test_monthly_budget_exceeded_routes_to_local(self, task, budget):
        """
        **Feature: relationship-advisor-agent, Property 13: 模型路由正确性**
        **Validates: Requirements 15.6**

        当云端调用累计成本超过月预算上限时，
        后续所有请求必须路由到本地 fallback 模型。
        """
        router = _make_router(budget=budget)

        # 模拟累计成本超过月预算
        router._monthly_cost = budget['monthly_limit_usd'] + 0.01

        backend = router.route(task)
        assert backend == 'local_qwen3', \
            f"月预算超限后应路由到 local_qwen3，实际: {backend}"

    # -----------------------------------------------------------------
    # 13d: 预算未超限时正常路由（不被强制到本地）
    # -----------------------------------------------------------------

    @settings(max_examples=100)
    @given(
        thresholds=threshold_strategy(),
        budget=budget_strategy(),
    )
    def test_under_budget_routes_normally(self, thresholds, budget):
        """
        **Feature: relationship-advisor-agent, Property 13: 模型路由正确性**
        **Validates: Requirements 15.6**

        当预算未超限时，高复杂度任务应路由到云端模型而非被强制到本地。
        """
        router = _make_router(thresholds=thresholds, budget=budget)

        # 确保预算充足
        router._daily_cost = 0.0
        router._monthly_cost = 0.0

        # 构造一个超过 medium 阈值的任务
        high_complexity = min(thresholds['medium'] + 0.1, 1.0)
        assume(high_complexity > thresholds['medium'])
        task = {'complexity_score': high_complexity, 'type': 'analysis'}

        backend = router.route(task)
        assert backend == 'deepseek_reasoner', \
            f"预算充足且 score={high_complexity:.3f} > medium，应路由到 deepseek_reasoner，实际: {backend}"

    # -----------------------------------------------------------------
    # 13e: 成本报告一致性
    # -----------------------------------------------------------------

    @settings(max_examples=100)
    @given(
        costs=st.lists(
            st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
            min_size=1,
            max_size=20,
        ),
    )
    def test_cost_report_consistency(self, costs):
        """
        **Feature: relationship-advisor-agent, Property 13: 模型路由正确性**
        **Validates: Requirements 15.5**

        成本报告中的累计成本必须等于所有记录成本之和。
        """
        router = _make_router()

        for cost in costs:
            router._record_cost('test_backend', cost)

        report = router.get_cost_report()
        expected_total = sum(costs)

        assert abs(report['daily_cost_usd'] - round(expected_total, 4)) < 1e-3, \
            f"日成本 {report['daily_cost_usd']} != 预期 {expected_total:.4f}"
        assert report['total_calls'] == len(costs), \
            f"调用次数 {report['total_calls']} != 预期 {len(costs)}"
