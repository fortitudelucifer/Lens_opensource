"""
结构化输出校验与自修复模块

功能：
- 对 LLM 的 JSON 输出进行 Pydantic Schema 强校验
- 校验失败时启动 2 轮 LLM 自修复循环（将错误信息反馈给 LLM 重新生成）
- 修复仍失败时调用 fallback LLM（如 DeepSeek Reasoner）进行格式转换
- 替代原有的 regex 解析方案，防止 LLM 格式漂移和字段缺失
- 自动提取 JSON 块（从 markdown 代码块或混合文本中）

处理流程：
1. validate_and_repair(): 接收 LLM 原始响应
   a. 尝试从响应中提取 JSON（支持 ```json 代码块和裸 JSON）
   b. 使用 Pydantic 模型校验 JSON 结构
   c. 校验通过 → 构建 CloudAnalysisResponse 返回
   d. 校验失败 → 将错误信息反馈给 LLM，请求修复（最多 2 轮）
   e. 修复仍失败 → 调用 fallback LLM 进行格式转换
   f. 全部失败 → 返回 None

输入：
- LLM 原始响应文本
- Agent 类型（neutral/supportive/psychoanalytic）
- LLM 调用函数（用于修复循环）
- Fallback LLM 调用函数（可选）

输出：
- CloudAnalysisResponse 对象（校验通过）或 None（校验失败）

依赖：
- pydantic: Schema 定义和校验
- scripts.advisor.schemas: AnalysisFeatures, CloudAnalysisResponse 等

使用示例：
    from scripts.advisor.schema_validator import SchemaValidator
    
    validator = SchemaValidator(config)
    result = validator.validate_and_repair(
        raw_response=llm_output,
        agent_type='neutral',
        call_llm_fn=lambda p: generator._call_api(p),
    )

注意事项：
- 修复循环每轮消耗一次 API 调用，注意成本控制
- max_repair_attempts 默认 2，可通过配置调整
- JSON 提取支持多种格式：```json 代码块、裸 JSON、混合文本中的 JSON
- 修复 prompt 中包含具体的 Pydantic 校验错误信息，帮助 LLM 精确修复

作者：[Author]
更新于：2026-02-15
"""

import json
import logging
import re
from typing import Any, Callable, Optional, Type

from pydantic import BaseModel, ValidationError

from scripts.advisor.schemas import (
    AnalysisFeatures,
    CloudAnalysisResponse,
    PsychoanalyticFeatures,
    RationalePrivate,
    SupportiveFeatures,
)

logger = logging.getLogger('advisor.schema_validator')


# =============================================================================
# JSON 提取工具
# =============================================================================

def extract_json_from_text(text: str) -> Optional[str]:
    """
    从 LLM 响应中提取 JSON 字符串。
    
    支持：
    - ```json ... ``` 代码块
    - { ... } 裸 JSON
    - <think>...</think> 标签包裹的响应（先移除 think 块）
    """
    # 移除 <think>...</think> 块，保留后面的内容
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()

    # 尝试 ```json ... ``` 代码块
    match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
    if match:
        return match.group(1).strip()

    # 尝试第一个 { ... } 块（贪心匹配最外层）
    depth = 0
    start = None
    for i, ch in enumerate(text):
        if ch == '{':
            if depth == 0:
                start = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and start is not None:
                return text[start:i + 1]

    return None


def extract_thinking_block(text: str) -> str:
    """提取 <think>...</think> 块内容，用于 rationale_private"""
    match = re.search(r'<think>(.*?)</think>', text, re.DOTALL)
    return match.group(1).strip() if match else ""


# =============================================================================
# 修复 Prompt 模板
# =============================================================================

REPAIR_PROMPT_TEMPLATE = """你之前的 JSON 输出存在格式错误，请根据以下错误信息修复。

【原始输出】
{original_response}

【验证错误】
{validation_errors}

【要求的 JSON Schema】
{json_schema}

请直接输出修复后的 JSON，不需要解释："""


# =============================================================================
# SchemaValidator
# =============================================================================

class SchemaValidator:
    """
    结构化输出校验器
    
    流程：
    1. 从 LLM 原始响应中提取 JSON
    2. 用 Pydantic 模型校验
    3. 校验失败 → 构建 repair prompt → 回传 LLM 修复（最多 2 轮）
    4. 2 轮修复仍失败 → fallback 到更强模型 或 返回 None
    """

    # agent_type → Pydantic 模型映射
    SCHEMA_MAP: dict[str, Type[BaseModel]] = {
        'neutral': AnalysisFeatures,
        'supportive': SupportiveFeatures,
        'psychoanalytic': PsychoanalyticFeatures,
    }

    def __init__(self, config: Optional[dict] = None):
        """
        Args:
            config: 配置字典，包含：
                - max_repair_attempts: 最大修复轮数（默认 2）
                - fallback_enabled: 是否启用 fallback（默认 True）
        """
        config = config or {}
        self.max_repair_attempts = config.get('max_repair_attempts', 2)
        self.fallback_enabled = config.get('fallback_enabled', True)

        # 统计
        self.stats = {
            'total_validations': 0,
            'first_pass_success': 0,
            'repair_success': 0,
            'fallback_success': 0,
            'total_failures': 0,
        }

    def validate_and_repair(
        self,
        raw_response: str,
        agent_type: str,
        call_llm_fn: Optional[Callable[[str], str]] = None,
        fallback_llm_fn: Optional[Callable[[str], str]] = None,
    ) -> Optional[CloudAnalysisResponse]:
        """
        校验 LLM 响应并在失败时尝试修复。
        
        Args:
            raw_response: LLM 的原始文本响应
            agent_type: Agent 类型 (neutral/supportive/psychoanalytic)
            call_llm_fn: 用于 repair 的 LLM 调用函数（接收 prompt，返回文本）
            fallback_llm_fn: fallback 到更强模型的调用函数
        
        Returns:
            CloudAnalysisResponse 或 None（彻底失败时）
        """
        self.stats['total_validations'] += 1

        if agent_type not in self.SCHEMA_MAP:
            logger.error(f"不支持的 agent_type: {agent_type}")
            return None

        schema_cls = self.SCHEMA_MAP[agent_type]
        thinking_text = extract_thinking_block(raw_response)

        # 第一轮：直接校验
        features = self._try_parse(raw_response, schema_cls)
        if features is not None:
            self.stats['first_pass_success'] += 1
            return self._build_response(
                agent_type, features, thinking_text, raw_response,
                repair_attempts=0,
            )

        # 修复循环（最多 max_repair_attempts 轮）
        if call_llm_fn is not None:
            last_response = raw_response
            for attempt in range(1, self.max_repair_attempts + 1):
                logger.info(f"Schema 修复尝试 {attempt}/{self.max_repair_attempts}")
                repair_prompt = self._build_repair_prompt(
                    last_response, schema_cls, agent_type,
                )
                try:
                    repaired = call_llm_fn(repair_prompt)
                except Exception as e:
                    logger.warning(f"修复调用失败: {e}")
                    break

                features = self._try_parse(repaired, schema_cls)
                if features is not None:
                    self.stats['repair_success'] += 1
                    return self._build_response(
                        agent_type, features, thinking_text, raw_response,
                        repair_attempts=attempt,
                    )
                last_response = repaired

        # Fallback 到更强模型
        if self.fallback_enabled and fallback_llm_fn is not None:
            logger.info("修复失败，尝试 fallback 到更强模型")
            try:
                fallback_response = fallback_llm_fn(raw_response)
                features = self._try_parse(fallback_response, schema_cls)
                if features is not None:
                    self.stats['fallback_success'] += 1
                    return self._build_response(
                        agent_type, features, thinking_text, raw_response,
                        repair_attempts=self.max_repair_attempts + 1,
                    )
            except Exception as e:
                logger.warning(f"Fallback 调用失败: {e}")

        # 彻底失败
        self.stats['total_failures'] += 1
        logger.error(f"Schema 校验彻底失败 (agent_type={agent_type})")
        return None

    def validate_only(self, data: dict, agent_type: str) -> Optional[BaseModel]:
        """
        仅校验（不修复），用于测试和属性验证。
        
        Args:
            data: 待校验字典
            agent_type: Agent 类型
        
        Returns:
            Pydantic 模型实例或 None
        """
        schema_cls = self.SCHEMA_MAP.get(agent_type)
        if schema_cls is None:
            return None
        try:
            return schema_cls.model_validate(data)
        except ValidationError:
            return None

    def get_stats(self) -> dict:
        """获取校验统计"""
        return self.stats.copy()

    # -------------------------------------------------------------------------
    # 内部方法
    # -------------------------------------------------------------------------

    def _try_parse(self, text: str, schema_cls: Type[BaseModel]) -> Optional[BaseModel]:
        """尝试从文本中提取并校验 JSON"""
        json_str = extract_json_from_text(text)
        if json_str is None:
            logger.debug("未能从响应中提取 JSON")
            return None

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.debug(f"JSON 解析失败: {e}")
            return None

        try:
            return schema_cls.model_validate(data)
        except ValidationError as e:
            logger.debug(f"Schema 校验失败: {e}")
            return None

    def _build_repair_prompt(
        self,
        original_response: str,
        schema_cls: Type[BaseModel],
        agent_type: str,
    ) -> str:
        """构建修复 prompt"""
        # 获取最近的校验错误
        json_str = extract_json_from_text(original_response) or original_response
        errors = self._get_validation_errors(json_str, schema_cls)

        return REPAIR_PROMPT_TEMPLATE.format(
            original_response=original_response[:2000],  # 截断防溢出
            validation_errors=errors,
            json_schema=json.dumps(
                schema_cls.model_json_schema(),
                ensure_ascii=False, indent=2,
            ),
        )

    def _get_validation_errors(self, json_str: str, schema_cls: Type[BaseModel]) -> str:
        """获取格式化的校验错误描述"""
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            return f"JSON 格式错误: {e}"

        try:
            schema_cls.model_validate(data)
            return "无错误"
        except ValidationError as e:
            error_msgs = []
            for err in e.errors():
                loc = ' -> '.join(str(x) for x in err['loc'])
                error_msgs.append(f"  字段 [{loc}]: {err['msg']} (类型: {err['type']})")
            return '\n'.join(error_msgs)

    def _build_response(
        self,
        agent_type: str,
        features: BaseModel,
        thinking_text: str,
        raw_response: str,
        repair_attempts: int,
    ) -> CloudAnalysisResponse:
        """构建 CloudAnalysisResponse"""
        private = RationalePrivate(
            thinking_process=thinking_text,
            raw_response=raw_response,
            repair_attempts=repair_attempts,
        )

        kwargs: dict[str, Any] = {
            'agent_type': agent_type,
            'rationale_private': private,
        }

        if agent_type == 'neutral':
            kwargs['analysis_features'] = features
        elif agent_type == 'supportive':
            kwargs['supportive_features'] = features
        elif agent_type == 'psychoanalytic':
            kwargs['psychoanalytic_features'] = features

        return CloudAnalysisResponse(**kwargs)
