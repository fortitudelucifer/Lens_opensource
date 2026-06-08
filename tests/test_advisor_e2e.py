"""
Task 15 端到端验证测试

覆盖：
- Property 9: 推理提示词一致性（三种 Agent 类型）
- Property 11: 回复时间模式检测正确性（Hypothesis）
- Property 12: 中立性分数不变量（Hypothesis）
- Property 13: Schema 校验 + 自修复
- ModelRouter 路由决策 + fallback
- SafetyLayer 诊断术语替换 + 风险检测
- 端到端：SchemaValidator → SafetyLayer → 本地安全上下文（P0 隔离）

Requirements: 6.3, 9.1-9.5, 12.1-12.5, 15.1-15.5, 16.4
"""

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from hypothesis import given, settings, assume
    from hypothesis import strategies as st
    HAS_HYPOTHESIS = True
except ImportError:
    HAS_HYPOTHESIS = False

from scripts.advisor.inference import AdvisorInference, SYSTEM_PROMPTS
from scripts.advisor.analyzers import (
    ResponseTimeAnalyzer,
    ConflictRootCauseAnalyzer,
    NeutralityChecker,
    PsychoanalyticDetector,
)
from scripts.advisor.model_router import ModelRouter
from scripts.advisor.schema_validator import (
    SchemaValidator,
    extract_json_from_text,
    extract_thinking_block,
)
from scripts.advisor.safety_layer import SafetyLayer, DEFAULT_DIAGNOSTIC_REPLACEMENTS
from scripts.advisor.schemas import (
    AnalysisFeatures,
    CloudAnalysisResponse,
    PsychoanalyticFeatures,
    RationalePrivate,
    RiskLevel,
    SupportiveFeatures,
)
from scripts.advisor.streaming import StreamingDialogueEngine, DialogueMode


# =============================================================================
# 测试数据
# =============================================================================

MOCK_MESSAGES = [
    {'ts': '2025-01-01 10:00:00', 'speaker': 'ME', 'text_raw': '你怎么又加班？你总是这样', 'type': 'text'},
    {'ts': '2025-01-01 10:00:30', 'speaker': 'OTHER', 'text_raw': '我也没办法啊，你凭什么这么说', 'type': 'text'},
    {'ts': '2025-01-01 10:00:45', 'speaker': 'ME', 'text_raw': '你从来不关心我的感受', 'type': 'text'},
    {'ts': '2025-01-01 10:01:00', 'speaker': 'OTHER', 'text_raw': '受不了你了', 'type': 'text'},
    {'ts': '2025-01-01 10:01:15', 'speaker': 'ME', 'text_raw': '够了，别说了', 'type': 'text'},
]

COLD_MESSAGES = [
    {'ts': '2025-01-01 10:00:00', 'speaker': 'ME', 'text_raw': '我们谈谈吧', 'type': 'text'},
    {'ts': '2025-01-01 18:00:00', 'speaker': 'OTHER', 'text_raw': '哦', 'type': 'text'},
    {'ts': '2025-01-01 18:00:30', 'speaker': 'OTHER', 'text_raw': '嗯', 'type': 'text'},
    {'ts': '2025-01-01 18:01:00', 'speaker': 'OTHER', 'text_raw': '好', 'type': 'text'},
    {'ts': '2025-01-01 18:01:30', 'speaker': 'OTHER', 'text_raw': '知道了', 'type': 'text'},
]

VALID_NEUTRAL_JSON = json.dumps({
    "relationship_status": "冲突期",
    "communication_quality": "较差",
    "emotional_balance": "ME主动表达不满，情绪不对等",
    "key_issues": ["沟通方式不当", "时间分配矛盾"],
    "advice": ["学习非暴力沟通", "约定每周固定交流时间"],
    "criticism": {"ME": "用指责语气表达诉求", "OTHER": "缺乏主动回应"},
    "overall_assessment": "双方处于冲突期，需要改善沟通方式"
}, ensure_ascii=False)

VALID_SUPPORTIVE_JSON = json.dumps({
    "relationship_status": "冲突期",
    "communication_quality": "较差",
    "emotional_balance": "ME主动",
    "key_issues": ["沟通不足"],
    "advice": ["尝试表达感受"],
    "criticism": {"ME": "表达过于急躁", "OTHER": "回应不够"},
    "overall_assessment": "建议先照顾好自己的情绪",
    "emotional_validation": "你感到被忽视和不被重视，这种感受完全可以理解"
}, ensure_ascii=False)

VALID_PSYCHOANALYTIC_JSON = json.dumps({
    "me_profile": {
        "attachment_style": "焦虑型",
        "defense_mechanisms": ["投射", "分裂"],
        "desire_pattern": "渴望被关注和认可"
    },
    "other_profile": {
        "attachment_style": "回避型",
        "defense_mechanisms": ["压抑", "合理化"],
        "desire_pattern": "维持个人空间和自主性"
    },
    "dynamics": {
        "attachment_interaction": "焦虑-回避追逃模式",
        "unconscious_contract": "ME追求亲密时OTHER退缩",
        "transference_pattern": "ME将早期依赖需求投射到关系中"
    },
    "developmental_suggestions": ["觉察追逃循环", "练习自我安抚"],
    "overall_assessment": "典型的焦虑-回避配对动态"
}, ensure_ascii=False)


# =============================================================================
# Property 9: 推理提示词一致性
# =============================================================================

class TestInferencePromptConsistency:
    """Property 9: 每种 Agent 类型对应正确的系统提示词"""

    def test_all_agent_types_have_prompts(self):
        """Feature: relationship-advisor-agent, Property 9: 三种 Agent 类型都有系统提示词"""
        for agent_type in ['neutral', 'supportive', 'psychoanalytic']:
            assert agent_type in SYSTEM_PROMPTS
            assert len(SYSTEM_PROMPTS[agent_type]) > 50

    def test_neutral_prompt_contains_key_elements(self):
        prompt = SYSTEM_PROMPTS['neutral']
        assert '中立' in prompt or '客观' in prompt
        assert 'ME' in prompt and 'OTHER' in prompt

    def test_supportive_prompt_contains_key_elements(self):
        prompt = SYSTEM_PROMPTS['supportive']
        assert '支持' in prompt or '理解' in prompt
        assert 'ME' in prompt

    def test_psychoanalytic_prompt_contains_key_elements(self):
        prompt = SYSTEM_PROMPTS['psychoanalytic']
        assert '精神分析' in prompt or '依附' in prompt
        assert '防御' in prompt or '拉康' in prompt

    def test_inference_init_selects_correct_prompt(self):
        """不加载模型，仅验证 prompt 选择逻辑"""
        for agent_type in ['neutral', 'supportive', 'psychoanalytic']:
            inf = AdvisorInference(agent_type=agent_type)
            assert inf.system_prompt == SYSTEM_PROMPTS[agent_type]
            assert inf.agent_type == agent_type

    def test_inference_unknown_type_falls_back_to_neutral(self):
        inf = AdvisorInference(agent_type='unknown')
        assert inf.system_prompt == SYSTEM_PROMPTS['neutral']


# =============================================================================
# Property 11: 回复时间模式检测正确性（Hypothesis）
# =============================================================================

@pytest.mark.skipif(not HAS_HYPOTHESIS, reason="hypothesis 未安装")
class TestResponseTimeProperty:
    """Property 11: 回复时间模式检测正确性"""

    def test_argument_detection_on_rapid_exchange(self):
        """Feature: relationship-advisor-agent, Property 11: 快速争吵检测"""
        analyzer = ResponseTimeAnalyzer()
        stats = analyzer.analyze(MOCK_MESSAGES)
        assert stats.argument_detected is True

    def test_cold_treatment_detection(self):
        """长时间不回 + 冷淡短消息 → 冷暴力检测"""
        analyzer = ResponseTimeAnalyzer()
        stats = analyzer.analyze(COLD_MESSAGES)
        assert stats.cold_treatment_detected is True

    def test_empty_messages_returns_default(self):
        analyzer = ResponseTimeAnalyzer()
        stats = analyzer.analyze([])
        assert stats.avg_response_time_me == 0.0
        assert not stats.cold_treatment_detected
        assert not stats.argument_detected

    @settings(max_examples=100)
    @given(st.floats(min_value=0.1, max_value=48.0))
    def test_cold_threshold_invariant(self, hours):
        """Property 11: 冷暴力阈值 > 0 时分析器不崩溃"""
        analyzer = ResponseTimeAnalyzer(cold_threshold_hours=hours)
        stats = analyzer.analyze(MOCK_MESSAGES)
        assert isinstance(stats.cold_treatment_detected, bool)

    @settings(max_examples=100)
    @given(st.floats(min_value=0.1, max_value=30.0))
    def test_argument_threshold_invariant(self, minutes):
        """Property 11: 争吵阈值参数化不崩溃"""
        analyzer = ResponseTimeAnalyzer(argument_threshold_minutes=minutes)
        stats = analyzer.analyze(MOCK_MESSAGES)
        assert isinstance(stats.argument_detected, bool)


class TestConflictRootCause:
    """冲突根源分析器基础验证"""

    def test_detects_communication_issues(self):
        messages = [
            {'text_raw': '你怎么不说呢，不沟通怎么行'},
            {'text_raw': '我说了你也不听'},
        ]
        analyzer = ConflictRootCauseAnalyzer()
        result = analyzer.analyze(messages)
        assert '沟通不畅' in result.root_causes

    def test_detects_trust_issues(self):
        messages = [
            {'text_raw': '你是不是骗我？偷偷瞒着我'},
        ]
        analyzer = ConflictRootCauseAnalyzer()
        result = analyzer.analyze(messages)
        assert '信任危机' in result.root_causes

    def test_empty_messages(self):
        analyzer = ConflictRootCauseAnalyzer()
        result = analyzer.analyze([])
        assert result.root_causes == []


# =============================================================================
# Property 12: 中立性分数不变量（Hypothesis）
# =============================================================================

@pytest.mark.skipif(not HAS_HYPOTHESIS, reason="hypothesis 未安装")
class TestNeutralityProperty:
    """Property 12: 中立性分数 ∈ [0, 1]"""

    @settings(max_examples=100)
    @given(st.text(min_size=10, max_size=500))
    def test_neutrality_score_range(self, text):
        """Feature: relationship-advisor-agent, Property 12: 中立性分数范围不变量"""
        checker = NeutralityChecker()
        score = checker.check(text)
        assert 0.0 <= score.overall_score <= 1.0
        assert 0.0 <= score.balance_score <= 1.0

    def test_balanced_text_high_score(self):
        text = "你需要注意自己的沟通方式。对方也应该更主动回应。双方都有需要改善的地方。"
        checker = NeutralityChecker()
        score = checker.check(text)
        assert score.overall_score >= 0.5

    def test_biased_text_lower_score(self):
        text = "你应该改。你的问题很大。你需要注意。你不应该这样。你的错误需要改。"
        checker = NeutralityChecker()
        score = checker.check(text)
        assert score.me_criticism_ratio > 0.5

    def test_no_criticism_is_balanced(self):
        text = "今天天气真好，适合出去走走。"
        checker = NeutralityChecker()
        score = checker.check(text)
        assert score.balance_score == 1.0


# =============================================================================
# 精神分析检测器测试
# =============================================================================

class TestPsychoanalyticDetector:
    """精神分析指标检测"""

    def test_anxious_attachment_detected(self):
        messages = [
            {'speaker': 'ME', 'text_raw': '你是不是不爱我了？你在干嘛为什么不回我？'},
        ]
        detector = PsychoanalyticDetector()
        result = detector.detect(messages)
        assert result.attachment_style_me == '焦虑型'

    def test_avoidant_attachment_detected(self):
        messages = [
            {'speaker': 'OTHER', 'text_raw': '我需要空间，别烦我，太累了'},
        ]
        detector = PsychoanalyticDetector()
        result = detector.detect(messages)
        assert result.attachment_style_other == '回避型'

    def test_defense_mechanisms_detected(self):
        messages = [
            {'speaker': 'ME', 'text_raw': '你才是有问题的，你自己看看你'},
        ]
        detector = PsychoanalyticDetector()
        result = detector.detect(messages)
        assert '投射' in result.defense_mechanisms_me

    def test_lacanian_analysis_structure(self):
        detector = PsychoanalyticDetector()
        result = detector.detect(MOCK_MESSAGES)
        assert '想象界' in result.lacanian_analysis
        assert '象征界' in result.lacanian_analysis
        assert '实在界' in result.lacanian_analysis


# =============================================================================
# ModelRouter 路由决策 + Fallback
# =============================================================================

class TestModelRouter:
    """ModelRouter 路由决策和 fallback 机制验证"""

    def test_simple_task_routes_local(self):
        router = ModelRouter()
        backend = router.route({'complexity_score': 0.1})
        assert backend == 'local_qwen3'
        assert router.stats['local_routes'] == 1

    def test_medium_task_routes_local_thinking(self):
        router = ModelRouter()
        backend = router.route({'complexity_score': 0.5})
        assert backend == 'local_qwen3_thinking'

    def test_complex_task_routes_cloud(self):
        router = ModelRouter()
        backend = router.route({'complexity_score': 0.8})
        assert backend == 'deepseek_reasoner'
        assert router.stats['cloud_routes'] == 1

    def test_long_context_routes_kimi(self):
        router = ModelRouter()
        backend = router.route({'complexity_score': 0.1, 'token_count': 50000})
        assert backend == 'kimi_long'

    def test_budget_exceeded_forces_local(self):
        router = ModelRouter({'budget_limit_daily': 0.0})
        backend = router.route({'complexity_score': 0.9})
        assert backend == 'local_qwen3'
        assert router.stats['budget_exceeded_routes'] == 1

    def test_is_local_backend(self):
        router = ModelRouter()
        assert router.is_local_backend('local_qwen3') is True
        assert router.is_local_backend('deepseek_reasoner') is False

    def test_call_local_raises(self):
        router = ModelRouter()
        with pytest.raises(NotImplementedError):
            router.call('local_qwen3', 'test prompt')

    def test_unknown_backend_returns_none(self):
        router = ModelRouter()
        result = router.call('nonexistent_backend', 'test')
        assert result is None

    def test_cost_report(self):
        router = ModelRouter({'budget_limit_daily': 10.0})
        report = router.get_cost_report()
        assert report['budget_limit'] == 10.0
        assert report['daily_cost'] == 0.0
        assert 'stats' in report

    def test_assess_complexity(self):
        router = ModelRouter()
        score = router._assess_complexity({'conversation': '普通对话', 'agent_type': 'neutral'})
        assert 0.0 <= score <= 1.0

        score_psycho = router._assess_complexity({
            'conversation': '普通对话', 'agent_type': 'psychoanalytic',
        })
        assert score_psycho > score  # psychoanalytic 加 0.3

    def test_assess_complexity_with_emotion_keywords(self):
        router = ModelRouter()
        score = router._assess_complexity({
            'conversation': '生气愤怒伤心失望绝望焦虑',
        })
        assert score >= 0.25


# =============================================================================
# SchemaValidator 校验 + 自修复
# =============================================================================

class TestSchemaValidator:
    """Property 13: Schema 校验 + 自修复"""

    def test_valid_neutral_json_passes(self):
        validator = SchemaValidator()
        result = validator.validate_and_repair(VALID_NEUTRAL_JSON, 'neutral')
        assert result is not None
        assert result.agent_type == 'neutral'
        assert result.analysis_features is not None
        assert validator.stats['first_pass_success'] == 1

    def test_valid_supportive_json_passes(self):
        validator = SchemaValidator()
        result = validator.validate_and_repair(VALID_SUPPORTIVE_JSON, 'supportive')
        assert result is not None
        assert result.agent_type == 'supportive'
        assert result.supportive_features is not None

    def test_valid_psychoanalytic_json_passes(self):
        validator = SchemaValidator()
        result = validator.validate_and_repair(VALID_PSYCHOANALYTIC_JSON, 'psychoanalytic')
        assert result is not None
        assert result.agent_type == 'psychoanalytic'
        assert result.psychoanalytic_features is not None

    def test_invalid_json_triggers_repair(self):
        """无效 JSON → 调用 repair LLM → 修复成功"""
        validator = SchemaValidator({'max_repair_attempts': 2})
        call_count = 0

        def mock_repair_llm(prompt: str) -> str:
            nonlocal call_count
            call_count += 1
            return VALID_NEUTRAL_JSON

        result = validator.validate_and_repair(
            '{"invalid": true}', 'neutral', call_llm_fn=mock_repair_llm,
        )
        assert result is not None
        assert call_count >= 1
        assert validator.stats['repair_success'] == 1

    def test_total_failure_returns_none(self):
        validator = SchemaValidator({'max_repair_attempts': 1})

        def mock_bad_llm(prompt: str) -> str:
            return '{"still_invalid": true}'

        result = validator.validate_and_repair(
            '{"bad": true}', 'neutral', call_llm_fn=mock_bad_llm,
        )
        assert result is None
        assert validator.stats['total_failures'] == 1

    def test_unsupported_agent_type_returns_none(self):
        validator = SchemaValidator()
        result = validator.validate_and_repair('{}', 'unknown_type')
        assert result is None

    def test_json_in_code_block_extracted(self):
        text = f"这是分析结果：\n```json\n{VALID_NEUTRAL_JSON}\n```"
        validator = SchemaValidator()
        result = validator.validate_and_repair(text, 'neutral')
        assert result is not None

    def test_thinking_block_extracted_to_private(self):
        text = f"<think>这是推理过程</think>\n{VALID_NEUTRAL_JSON}"
        validator = SchemaValidator()
        result = validator.validate_and_repair(text, 'neutral')
        assert result is not None
        assert result.rationale_private.thinking_process == '这是推理过程'

    def test_validate_only(self):
        validator = SchemaValidator()
        data = json.loads(VALID_NEUTRAL_JSON)
        model = validator.validate_only(data, 'neutral')
        assert model is not None
        assert isinstance(model, AnalysisFeatures)

    def test_validate_only_invalid(self):
        validator = SchemaValidator()
        model = validator.validate_only({'bad': True}, 'neutral')
        assert model is None


# =============================================================================
# JSON 提取工具测试
# =============================================================================

class TestJsonExtraction:
    """extract_json_from_text 和 extract_thinking_block 工具"""

    def test_extract_bare_json(self):
        result = extract_json_from_text('前面的文字 {"key": "value"} 后面的文字')
        assert result is not None
        assert json.loads(result) == {"key": "value"}

    def test_extract_code_block(self):
        text = '```json\n{"a": 1}\n```'
        result = extract_json_from_text(text)
        assert json.loads(result) == {"a": 1}

    def test_extract_removes_think_block(self):
        text = '<think>思考过程</think>\n{"a": 1}'
        result = extract_json_from_text(text)
        assert json.loads(result) == {"a": 1}

    def test_extract_thinking_block(self):
        text = '<think>推理内容</think>其他内容'
        assert extract_thinking_block(text) == '推理内容'

    def test_no_thinking_block(self):
        assert extract_thinking_block('无 think 标签') == ''


# =============================================================================
# SafetyLayer 诊断术语替换 + 风险检测
# =============================================================================

class TestSafetyLayer:
    """SafetyLayer P0 隔离验证"""

    def test_diagnostic_replacement(self):
        layer = SafetyLayer()
        result = layer._replace_diagnostic('焦虑型依附模式导致投射性认同')
        assert '焦虑型依附' not in result
        assert '投射性认同' not in result
        assert '敏感' in result or '担心' in result

    def test_all_default_replacements_work(self):
        layer = SafetyLayer()
        for diagnostic, layman in DEFAULT_DIAGNOSTIC_REPLACEMENTS.items():
            result = layer._replace_diagnostic(f'检测到{diagnostic}')
            assert diagnostic not in result

    def test_risk_detection_critical(self):
        layer = SafetyLayer()
        assert layer.detect_risk('有自杀倾向') == RiskLevel.CRITICAL

    def test_risk_detection_high(self):
        layer = SafetyLayer()
        assert layer.detect_risk('存在家暴行为') == RiskLevel.HIGH

    def test_risk_detection_medium(self):
        layer = SafetyLayer()
        assert layer.detect_risk('疑似抑郁症行为') == RiskLevel.MEDIUM

    def test_risk_detection_none(self):
        layer = SafetyLayer()
        assert layer.detect_risk('今天天气不错') == RiskLevel.NONE

    def test_risk_detection_disabled(self):
        layer = SafetyLayer({'enable_risk_detection': False})
        assert layer.detect_risk('自杀') == RiskLevel.NONE

    def test_sanitize_neutral_features(self):
        """neutral 类型 sanitize 生成安全纯文本"""
        features = AnalysisFeatures.model_validate(json.loads(VALID_NEUTRAL_JSON))
        response = CloudAnalysisResponse(
            agent_type='neutral',
            analysis_features=features,
            rationale_private=RationalePrivate(
                thinking_process='这是隐私推理，不能泄露',
                diagnostic_notes='焦虑型依附诊断',
            ),
        )
        layer = SafetyLayer()
        safe_text = layer.sanitize_for_local(response)

        assert '关系状态' in safe_text
        assert '建议' in safe_text
        # P0: rationale_private 绝不出现在 safe_text 中
        assert '不能泄露' not in safe_text
        assert '焦虑型依附诊断' not in safe_text

    def test_sanitize_psychoanalytic_replaces_terms(self):
        """psychoanalytic 类型 sanitize 替换诊断术语"""
        features = PsychoanalyticFeatures.model_validate(
            json.loads(VALID_PSYCHOANALYTIC_JSON)
        )
        response = CloudAnalysisResponse(
            agent_type='psychoanalytic',
            psychoanalytic_features=features,
        )
        layer = SafetyLayer()
        safe_text = layer.sanitize_for_local(response)

        # 诊断术语应被替换
        assert '投射' not in safe_text or '放到对方身上' in safe_text
        assert '成长建议' in safe_text or '觉察' in safe_text

    def test_audit_log_written(self, tmp_path):
        """rationale_private 写入审计日志"""
        features = AnalysisFeatures.model_validate(json.loads(VALID_NEUTRAL_JSON))
        response = CloudAnalysisResponse(
            agent_type='neutral',
            analysis_features=features,
            rationale_private=RationalePrivate(
                thinking_process='隐私推理链',
                raw_response='原始响应',
            ),
        )
        layer = SafetyLayer({'audit_log_dir': str(tmp_path / 'audit')})
        log_path = layer.log_private(response, chunk_id='test_001')

        assert log_path.exists()
        with open(log_path, 'r') as f:
            entry = json.loads(f.readline())
        assert entry['rationale_private']['thinking_process'] == '隐私推理链'


# =============================================================================
# 端到端集成：SchemaValidator → SafetyLayer → 安全上下文
# =============================================================================

class TestEndToEndIntegration:
    """端到端集成测试：从 LLM 原始响应到安全本地上下文"""

    def test_neutral_e2e_pipeline(self):
        """neutral: 原始响应 → Schema校验 → SafetyLayer → 安全文本"""
        raw_response = f"<think>深度分析推理</think>\n{VALID_NEUTRAL_JSON}"

        # 1. Schema 校验
        validator = SchemaValidator()
        cloud_response = validator.validate_and_repair(raw_response, 'neutral')
        assert cloud_response is not None

        # 2. 验证 thinking 被捕获到 private
        assert cloud_response.rationale_private.thinking_process == '深度分析推理'

        # 3. SafetyLayer 过滤
        layer = SafetyLayer()
        safe_text = layer.sanitize_for_local(cloud_response)

        # 4. P0 验证：safe_text 不含任何 private 信息
        assert '深度分析推理' not in safe_text
        assert '关系状态' in safe_text
        assert '建议' in safe_text

    def test_supportive_e2e_pipeline(self):
        raw_response = VALID_SUPPORTIVE_JSON
        validator = SchemaValidator()
        cloud_response = validator.validate_and_repair(raw_response, 'supportive')
        assert cloud_response is not None
        assert cloud_response.supportive_features.emotional_validation != ''

        layer = SafetyLayer()
        safe_text = layer.sanitize_for_local(cloud_response)
        assert '情感验证' in safe_text

    def test_psychoanalytic_e2e_pipeline(self):
        raw_response = (
            "<think>焦虑型依附配对回避型，形成典型追逃模式</think>\n"
            f"{VALID_PSYCHOANALYTIC_JSON}"
        )
        validator = SchemaValidator()
        cloud_response = validator.validate_and_repair(raw_response, 'psychoanalytic')
        assert cloud_response is not None

        layer = SafetyLayer()
        safe_text = layer.sanitize_for_local(cloud_response)

        # P0: 推理链不泄露
        assert '追逃模式' not in safe_text or '焦虑型依附配对' not in safe_text
        # 诊断术语被替换
        assert '相处模式' in safe_text or '成长建议' in safe_text

    def test_router_complexity_to_schema_flow(self):
        """ModelRouter 复杂度评估 → 路由 → 验证 Schema 类型匹配"""
        router = ModelRouter()

        # 简单任务 → local
        simple_backend = router.route({
            'complexity_score': router._assess_complexity({
                'conversation': '你好', 'agent_type': 'neutral',
            }),
        })
        assert router.is_local_backend(simple_backend)

        # 复杂任务 → cloud（直接传高分绕过 assess 上限）
        complex_backend = router.route({'complexity_score': 0.9})
        assert not router.is_local_backend(complex_backend)

    def test_streaming_engine_context_with_schema(self):
        """StreamingDialogueEngine 上下文窗口 + 模式切换"""
        engine = StreamingDialogueEngine({'context_window': 5})

        # listen 模式
        assert engine.mode == DialogueMode.LISTEN
        engine.add_message("最近好累")
        engine.add_message("我理解你的感受", role='assistant')

        # 切换 consult
        engine.switch_mode('consult')
        assert engine.mode == DialogueMode.CONSULT
        engine.add_message("能帮我分析一下吗")

        # 上下文完整
        history = engine.get_history()
        assert len(history) == 3
        assert history[0].mode == 'listen'
        assert history[2].mode == 'consult'

        # 窗口溢出测试
        for i in range(10):
            engine.add_message(f"消息{i}")
        assert len(engine.get_context()) == 5


# =============================================================================
# Schema 模型验证
# =============================================================================

class TestSchemaModels:
    """Pydantic Schema 模型正确性"""

    def test_cloud_response_requires_matching_features(self):
        """neutral 类型必须有 analysis_features"""
        with pytest.raises(Exception):
            CloudAnalysisResponse(agent_type='neutral')

    def test_cloud_response_features_for_local(self):
        features = AnalysisFeatures.model_validate(json.loads(VALID_NEUTRAL_JSON))
        response = CloudAnalysisResponse(
            agent_type='neutral', analysis_features=features,
        )
        local_features = response.get_features_for_local()
        assert isinstance(local_features, AnalysisFeatures)

    def test_cloud_response_private_for_audit(self):
        features = AnalysisFeatures.model_validate(json.loads(VALID_NEUTRAL_JSON))
        private = RationalePrivate(thinking_process='secret', raw_response='raw')
        response = CloudAnalysisResponse(
            agent_type='neutral',
            analysis_features=features,
            rationale_private=private,
        )
        audit = response.get_private_for_audit()
        assert audit.thinking_process == 'secret'

    def test_analysis_features_max_length_enforced(self):
        """Pydantic max_length=3 拒绝超长列表"""
        data = json.loads(VALID_NEUTRAL_JSON)
        data['key_issues'] = ['a', 'b', 'c', 'd', 'e']
        with pytest.raises(Exception):
            AnalysisFeatures.model_validate(data)

    def test_risk_level_enum(self):
        assert RiskLevel.NONE.value == '无'
        assert RiskLevel.CRITICAL.value == '紧急'
