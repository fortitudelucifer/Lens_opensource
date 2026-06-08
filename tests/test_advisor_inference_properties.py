"""
Property 9: 推理提示词一致性

验证推理时使用的系统提示词和用户提示词格式与训练时使用的格式一致。

**Feature: relationship-advisor-agent, Property 9: 推理提示词一致性**
**Validates: Requirements 6.3**
"""

import sys
from pathlib import Path

import pytest
from hypothesis import given, settings, strategies as st

# 添加项目根目录
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.advisor.formatter import TrainingFormatter
from scripts.advisor.formatter import SYSTEM_PROMPTS as TRAINING_SYSTEM_PROMPTS
from scripts.advisor.inference import AdvisorInference, SYSTEM_PROMPTS as INFERENCE_SYSTEM_PROMPTS
from scripts.advisor.inference import USER_PROMPT_TEMPLATE


# ============================================================
# 策略定义
# ============================================================

conversation_strategy = st.text(
    alphabet=st.characters(whitelist_categories=('L', 'N', 'P', 'Z')),
    min_size=1,
    max_size=500,
)

agent_type_strategy = st.sampled_from(['neutral', 'supportive', 'psychoanalytic'])


# ============================================================
# Property 9: 推理提示词一致性
# ============================================================

class TestProperty9InferencePromptConsistency:
    """Property 9: 推理提示词一致性
    
    **Validates: Requirements 6.3**
    
    验证推理时使用的 system prompt 和 user prompt 格式与训练时一致。
    """

    @settings(max_examples=100)
    @given(agent_type=agent_type_strategy, conversation=conversation_strategy)
    def test_user_prompt_format_matches_training(self, agent_type, conversation):
        """推理的 user prompt 格式必须与训练时一致。
        
        **Validates: Requirements 6.3**
        """
        # 训练时的 user prompt（从 formatter.format_sample 中提取）
        formatter = TrainingFormatter({'format': 'jsonl'})
        # 构造一个最小的 analysis 来调用 format_sample
        dummy_analysis = {
            'relationship_status': '健康期',
            'communication_quality': '良好',
            'emotional_balance': '平衡',
            'key_issues': ['无'],
            'advice': ['无'],
            'criticism': {'ME': '无', 'OTHER': '无'},
            'overall_assessment': '良好',
        }
        training_sample = formatter.format_sample(conversation, dummy_analysis, agent_type)
        training_user_content = training_sample['messages'][1]['content']
        
        # 推理时的 user prompt
        inference_user_content = USER_PROMPT_TEMPLATE.format(conversation=conversation)
        
        # 两者必须完全一致
        assert training_user_content == inference_user_content, (
            f"训练 user prompt 与推理 user prompt 不一致:\n"
            f"  训练: {training_user_content[:100]!r}\n"
            f"  推理: {inference_user_content[:100]!r}"
        )

    @settings(max_examples=100)
    @given(agent_type=agent_type_strategy)
    def test_system_prompt_contains_training_base(self, agent_type):
        """推理的 system prompt 必须包含训练时的基础 system prompt 内容。
        
        **Validates: Requirements 6.3**
        """
        training_prompt = TRAINING_SYSTEM_PROMPTS[agent_type]
        inference_prompt = INFERENCE_SYSTEM_PROMPTS[agent_type]
        
        # 推理版 system prompt 应包含训练版的核心内容
        # 训练版是简短版，推理版是完整版（含输出格式说明）
        # 核心内容（第一句话）必须一致
        training_first_line = training_prompt.strip().split('\n')[0]
        assert training_first_line in inference_prompt, (
            f"推理 system prompt 不包含训练版的核心内容:\n"
            f"  训练首行: {training_first_line!r}\n"
            f"  推理 prompt: {inference_prompt[:200]!r}"
        )

    @settings(max_examples=100)
    @given(agent_type=agent_type_strategy, conversation=conversation_strategy)
    def test_inference_messages_structure_matches_training(self, agent_type, conversation):
        """推理构建的消息结构（角色顺序）必须与训练数据一致。
        
        **Validates: Requirements 6.3**
        """
        # 训练时的消息结构
        formatter = TrainingFormatter({'format': 'jsonl'})
        dummy_analysis = {
            'relationship_status': '健康期',
            'communication_quality': '良好',
            'emotional_balance': '平衡',
            'key_issues': ['无'],
            'advice': ['无'],
            'criticism': {'ME': '无', 'OTHER': '无'},
            'overall_assessment': '良好',
        }
        training_sample = formatter.format_sample(conversation, dummy_analysis, agent_type)
        training_roles = [m['role'] for m in training_sample['messages']]
        
        # 推理时的消息结构（不含 assistant，因为那是要生成的）
        inference = AdvisorInference.__new__(AdvisorInference)
        inference.system_prompt = INFERENCE_SYSTEM_PROMPTS[agent_type]
        messages = inference._build_messages(conversation, thinking=False)
        inference_roles = [m['role'] for m in messages]
        
        # 训练是 [system, user, assistant]，推理是 [system, user]（assistant 由模型生成）
        assert training_roles == ['system', 'user', 'assistant']
        assert inference_roles == ['system', 'user']
        # 前两个角色必须一致
        assert inference_roles == training_roles[:2]

    def test_all_agent_types_have_matching_prompts(self):
        """所有 agent 类型在训练和推理中都必须有对应的 system prompt。
        
        **Validates: Requirements 6.3**
        """
        for agent_type in ['neutral', 'supportive', 'psychoanalytic']:
            assert agent_type in TRAINING_SYSTEM_PROMPTS, (
                f"训练 SYSTEM_PROMPTS 缺少 {agent_type}"
            )
            assert agent_type in INFERENCE_SYSTEM_PROMPTS, (
                f"推理 SYSTEM_PROMPTS 缺少 {agent_type}"
            )

    @settings(max_examples=100)
    @given(agent_type=agent_type_strategy, conversation=conversation_strategy)
    def test_thinking_mode_preserves_base_prompt(self, agent_type, conversation):
        """思考模式的 prompt 必须包含标准模式的完整内容（仅追加思考指令）。
        
        **Validates: Requirements 6.3**
        """
        inference = AdvisorInference.__new__(AdvisorInference)
        inference.system_prompt = INFERENCE_SYSTEM_PROMPTS[agent_type]
        
        standard_messages = inference._build_messages(conversation, thinking=False)
        thinking_messages = inference._build_messages(conversation, thinking=True)
        
        # user prompt 完全一致
        assert standard_messages[1]['content'] == thinking_messages[1]['content']
        
        # thinking 模式的 system prompt 包含标准模式的完整内容
        standard_system = standard_messages[0]['content']
        thinking_system = thinking_messages[0]['content']
        assert standard_system in thinking_system, (
            "思考模式的 system prompt 必须包含标准模式的完整内容"
        )
        # thinking 模式额外包含思考指令
        assert len(thinking_system) > len(standard_system)
