"""
LLM 分析生成器模块

功能：
- 调用各种 LLM API（OpenAI、DeepSeek、Kimi、Kimi、Qwen、DeepSeek、Qwen、GLM 等）生成关系分析
- 支持 8+ 后端的统一接口（OpenAI 兼容 + Anthropic 原生 + Response API）
- 三种 Agent 类型的专用提示词模板（neutral/supportive/psychoanalytic）
- 通过 ModelRouter 智能路由到合适的后端
- 通过 SchemaValidator 进行 JSON Schema 校验与 LLM 自修复循环
- 通过 SafetyLayer 隔离云端推理过程（rationale_private 仅审计）
- 支持断点续跑（batch_generate 自动跳过已完成的 chunk_id）
- 支持运行时 API 密钥热替换（swap_api_key）

处理流程：
1. 根据 agent_type 选择对应的提示词模板
2. 注入对话文本、GraphRAG 历史上下文、多模态密度提示
3. 调用 LLM API（自动选择 stream/non-stream/Response API 模式）
4. SchemaValidator 校验 JSON 输出 + 最多 2 轮 LLM 自修复
5. SafetyLayer 记录审计日志（rationale_private）
6. 返回 CloudAnalysisResponse 对象

输入：
- 格式化的对话文本（conversation_text）
- Agent 类型（neutral/supportive/psychoanalytic）
- GraphRAG 历史上下文（可选）
- 多模态密度元数据（可选）

输出：
- CloudAnalysisResponse 对象（含 analysis_features + rationale_private）
- 批量模式输出 JSONL 文件

依赖：
- openai: OpenAI 兼容 API 客户端（覆盖大部分后端）
- anthropic: Anthropic DeepSeek 原生 SDK（仅官方 API 使用）
- httpx: Response API 的 SSE 流式请求
- scripts.advisor.schemas: Pydantic Schema 定义
- scripts.advisor.schema_validator: JSON Schema 校验与自修复
- scripts.advisor.safety_layer: 安全隔离与审计日志

使用示例：
    from scripts.advisor.generator import AnalysisGenerator
    from scripts.advisor.model_router import ModelRouter
    from scripts.advisor.schema_validator import SchemaValidator
    from scripts.advisor.safety_layer import SafetyLayer
    
    # 初始化组件
    generator = AnalysisGenerator(
        config={'backend': 'openai', 'model': 'GLM-4'},
        router=ModelRouter(config),
        validator=SchemaValidator(config),
        safety=SafetyLayer(config),
    )
    
    # 单条分析
    result = generator.generate_analysis(conversation_text, agent_type='neutral')
    
    # 批量分析（支持断点续跑）
    results = generator.batch_generate(chunks, 'neutral', 'output.jsonl')

性能参考：
- 单条分析耗时取决于 LLM 后端（GLM-4: 10-30s, DeepSeek: 5-15s, DeepSeek: 5-20s）
- Schema 自修复每轮额外增加一次 API 调用
- 批量模式每条写完立即刷盘，中断不丢失已完成数据

注意事项：
- 环境变量优先级：{BACKEND}_API_KEY, {BACKEND}_BASE_URL, {BACKEND}_MODEL
- thinking 模型（名称含 think/reason/o1/o3/o4）自动跳过 temperature 参数
- 第三方代理（有自定义 base_url）自动使用 stream 模式避免 500 错误
- Response API 模式通过 {BACKEND}_WIRE_API=responses 环境变量启用

作者：forcifer
更新于：2026-02-15
"""

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Optional
from tqdm import tqdm

from scripts.advisor.schemas import (
    ANALYSIS_JSON_SCHEMA,
    PSYCHOANALYTIC_JSON_SCHEMA,
    SUPPORTIVE_JSON_SCHEMA,
    AnalysisFeatures,
    CloudAnalysisResponse,
)
from scripts.advisor.schema_validator import SchemaValidator
from scripts.advisor.safety_layer import SafetyLayer

logger = logging.getLogger('advisor.generator')


# =============================================================================
# 提示词模板
# =============================================================================

NEUTRAL_PROMPT = """你是一位资深关系心理顾问，精通 Gottman 四骑士理论、Perel 的亲密关系隐藏主题（权力与控制/亲密与关爱/尊重与认可）、Bowlby 依附理论。你擅长从多模态聊天记录中提取深层关系动态。

请基于以下对话片段进行专业分析。对话中包含时间戳、语音情绪标签、图片/视频氛围标注、表情包意图等多模态信息，请充分利用这些信息。

【对话】
{conversation}

{graph_context}

{mm_context}

【分析框架】

一、基础评估（必填）
1. relationship_status：关系阶段（健康期/甜蜜期/平淡期/冷淡期/冲突期）
2. communication_quality：沟通质量（优秀/良好/一般/较差/很差）
3. emotional_balance：情绪投入对等性分析（注意消息长度不对称、回复频率差异、情绪表达密度差异）

二、深度分析（必填）
4. key_issues：对话中暴露的核心问题（最多3个），每个问题必须引用具体对话内容作为证据
5. criticism：分别指出双方的具体不当行为（ME 和 OTHER 各1-2条），基于行为而非人格
6. advice：给出可操作的改善建议（最多3条），针对 key_issues 中的具体问题

三、时间模式分析（如对话中有时间戳或时间间隔标记"---"）
7. time_patterns：识别以下时间线模式（最多3个），必须结合对话上下文和人物特点判断，不能仅靠时间间隔长短：
   - 冷暴力/石墙：长间隔+短/无回复+消极语气（需区分"真忙"vs"故意不理"）
   - 争吵升级：快速来回+冲突关键词密集（注意 Gottman 四骑士：批评→蔑视→防御→石墙）
   - 追逃模式：一方密集发送→对方沉默→更密集（焦虑-回避依附互动）
   - 修复尝试：冲突后主动打破沉默、语气变软（Gottman 最关键的关系预测因子）
   - 渐行渐远：对话频率/长度整体下降、内容从情感变为事务性
   - 甜蜜互动：频繁及时回复+正面情绪+表情包密集
   - 主动冷静：双方商定暂停（≠冷暴力，是健康的冲突管理）

四、冲突根源分析（如存在冲突/不适信号）
8. conflict_root_causes：从以下10种根源中识别适用的（最多3个），需引用对话证据：
   ① 权力失衡（话语权不对等、控制行为）
   ② 情感需求未满足（缺陪伴、情感回应缺失）
   ③ 尊重与认可缺失（付出不被看见、成就被忽视）
   ④ 沟通方式不匹配（一方需倾诉另一方回避）
   ⑤ 边界与独立性冲突（个人空间、社交界限）
   ⑥ 价值观/生活习惯差异（消费观、作息、规划）
   ⑦ 信任危机（猜疑、隐瞒、安全感缺失）
   ⑧ 外部压力传导（工作/原生家庭/经济压力）
   ⑨ 亲密关系倦怠（激情消退、日常化麻木）
   ⑩ 依附模式冲突（焦虑型vs回避型的追逃循环）

五、多模态信号分析（如对话中有 [语音:...情绪:...] [图片:...氛围:...] [表情:...] 等标注）
9. multimodal_signals：总结多模态信号揭示的情感暗示（语音情绪变化趋势、图片/视频氛围传递的潜台词、表情包使用模式与意图）

六、修复与人格动态
10. repair_attempts：识别对话中的关系修复尝试及其效果（如有）
11. personality_dynamics：初步判断双方的沟通风格和依附倾向（如：一方倾向追求/焦虑型、另一方倾向回避/理性型）

七、总结
12. overall_assessment：用2-3句话总结关系现状、核心矛盾和发展趋势
13. risk_level：风险级别（无/低/中/高/紧急）

【输出格式】
请严格输出以下 JSON 格式，不要输出其他内容：
```json
{{
  "relationship_status": "健康期|甜蜜期|平淡期|冷淡期|冲突期",
  "communication_quality": "优秀|良好|一般|较差|很差",
  "emotional_balance": "详细描述情绪投入对等性",
  "key_issues": ["问题1（含证据引用）", "问题2", "问题3"],
  "advice": ["可操作建议1", "建议2", "建议3"],
  "criticism": {{"ME": "基于具体行为的批评", "OTHER": "基于具体行为的批评"}},
  "time_patterns": ["模式1: 具体描述和证据", "模式2"],
  "conflict_root_causes": ["根源①: 证据描述", "根源②"],
  "multimodal_signals": "多模态情感信号的综合解读",
  "repair_attempts": "修复尝试的识别与效果评估",
  "personality_dynamics": "双方沟通风格与依附倾向描述",
  "overall_assessment": "关系现状、核心矛盾、发展趋势",
  "risk_level": "无|低|中|高|紧急"
}}
```

【核心原则】
- 客观中立：不偏袒任何一方，用证据支撑每个判断
- 情境化判断：同样的时间间隔在不同上下文中含义不同（如争吵后6h不回复 vs 凌晨正常睡眠），必须结合对话内容综合判断
- 多模态利用：充分利用语音情绪标签、图片氛围、表情包意图等非文字信号
- 如果对话中没有明显的冲突/时间模式/多模态信号，对应字段可以填 null

开始分析："""

SUPPORTIVE_PROMPT = """你是一位支持性的关系顾问，你的首要任务是理解和支持用户（ME）的感受。你擅长从多模态聊天记录中捕捉情感暗示。

请分析以下对话片段，从用户的角度提供支持性的评价。对话中包含时间戳、语音情绪标签、图片/视频氛围标注、表情包意图等多模态信息，请充分利用这些信息。

【对话】
{conversation}

{graph_context}

{mm_context}

【分析要求】

一、基础评估（必填）
1. relationship_status：关系阶段（健康期/甜蜜期/平淡期/冷淡期/冲突期）
2. communication_quality：沟通质量（优秀/良好/一般/较差/很差）
3. emotional_balance：情绪投入对等性分析
4. emotional_validation：首先验证用户（ME）的感受是合理的

二、深度分析（必填）
5. key_issues：从用户角度指出问题（最多3个），引用具体对话内容
6. advice：给出保护用户利益的可操作建议（最多3条）
7. criticism：主要批评对方（OTHER），对用户（ME）的批评要温和

三、时间模式分析（如对话中有时间戳或时间间隔标记"---"）
8. time_patterns：识别时间线模式（如冷暴力、争吵升级、追逃模式、修复尝试等），结合上下文判断

四、多模态信号分析（如对话中有 [语音:...情绪:...] [图片:...氛围:...] [表情:...] 等标注）
9. multimodal_signals：分析多模态信号揭示的情感暗示（语音情绪趋势、图片氛围潜台词、表情包使用模式），特别关注对方（OTHER）通过非文字方式传达的态度

五、总结
10. overall_assessment：用2-3句话总结，要让用户感到被理解
11. risk_level：风险级别（无/低/中/高/紧急）

【输出格式】
请严格输出以下 JSON 格式，不要输出其他内容：
```json
{{
  "relationship_status": "健康期|甜蜜期|平淡期|冷淡期|冲突期",
  "communication_quality": "优秀|良好|一般|较差|很差",
  "emotional_balance": "描述",
  "emotional_validation": "验证用户感受的话",
  "key_issues": ["问题1（含证据引用）", "问题2", "问题3"],
  "advice": ["可操作建议1", "建议2", "建议3"],
  "criticism": {{"ME": "温和的批评或肯定", "OTHER": "直接的批评"}},
  "time_patterns": ["模式1: 描述和证据", "模式2"],
  "multimodal_signals": "多模态情感信号的综合解读",
  "overall_assessment": "支持性的评价",
  "risk_level": "无|低|中|高|紧急"
}}
```

【核心原则】
- 站在用户一方，但保持基本客观性
- 多模态利用：充分利用语音情绪标签、图片氛围、表情包意图等非文字信号
- 如果对话中没有明显的时间模式/多模态信号，对应字段可以填 null

请从用户角度出发，开始分析："""

PSYCHOANALYTIC_PROMPT = """你是一位精神分析取向的关系顾问，精通客体关系理论（Klein, Winnicott, Fairbairn）和拉康派精神分析。你擅长从多模态聊天记录中捕捉无意识层面的信号。

请从精神分析视角分析以下对话。对话中包含时间戳、语音情绪标签、图片/视频氛围标注、表情包意图等多模态信息，这些非文字信号往往更能揭示无意识动态。

【对话】
{conversation}

{graph_context}

{mm_context}

【分析框架】

一、客体关系分析（必填）
1. me_profile / other_profile：依附风格、防御机制、欲望模式
2. 注意从语音情绪标签和表情包选择中推断防御机制（如用表情包回避深入讨论=理智化/隔离）

二、拉康派分析（必填）
3. dynamics：依附互动、无意识契约、移情模式
4. 注意从对话的时间间隔模式中推断欲望结构（如反复的追逃循环=主体间欲望的错位）

三、多模态无意识信号（如对话中有 [语音:...情绪:...] [图片:...氛围:...] [表情:...] 等标注）
5. multimodal_signals：从精神分析角度解读多模态信号：
   - 语音情绪与文字内容的不一致（可能的压抑/反向形成）
   - 图片/视频选择揭示的潜意识投射
   - 表情包作为象征界的替代表达

四、时间模式分析（如对话中有时间戳或时间间隔标记"---"）
6. time_patterns：从精神分析角度解读时间模式（沉默作为攻击性表达、延迟回复作为控制机制等）

五、发展性建议与总结
7. developmental_suggestions：需要觉察的无意识模式和成长方向
8. overall_assessment：精神分析视角的关系动态总结
9. risk_level：风险级别（无/低/中/高/紧急）

【输出格式】
请严格输出以下 JSON 格式，不要输出其他内容：
```json
{{
  "me_profile": {{
    "attachment_style": "安全型|焦虑型|回避型|混乱型",
    "defense_mechanisms": ["机制1", "机制2"],
    "desire_pattern": "欲望模式描述"
  }},
  "other_profile": {{
    "attachment_style": "安全型|焦虑型|回避型|混乱型",
    "defense_mechanisms": ["机制1", "机制2"],
    "desire_pattern": "欲望模式描述"
  }},
  "dynamics": {{
    "attachment_interaction": "依附互动描述",
    "unconscious_contract": "无意识契约描述",
    "transference_pattern": "移情模式描述"
  }},
  "multimodal_signals": "多模态无意识信号的精神分析解读",
  "time_patterns": ["模式1: 精神分析角度的描述", "模式2"],
  "developmental_suggestions": ["建议1", "建议2"],
  "overall_assessment": "精神分析视角的总结",
  "risk_level": "无|低|中|高|紧急"
}}
```

【核心原则】
- 深层解读：透过表面行为看到无意识动力
- 多模态利用：语音情绪、图片氛围、表情包意图往往更接近无意识真实
- 如果对话中没有明显的多模态信号/时间模式，对应字段可以填 null

请开始分析："""


PROMPTS = {
    'neutral': NEUTRAL_PROMPT,
    'supportive': SUPPORTIVE_PROMPT,
    'psychoanalytic': PSYCHOANALYTIC_PROMPT,
}


class AnalysisGenerator:
    """LLM 分析生成器
    
    通过 ModelRouter 路由到合适的后端，
    使用 SchemaValidator 进行结构化输出校验与自修复，
    通过 SafetyLayer 隔离云端推理过程。
    
    Attributes:
        backend (str): 当前 LLM 后端名称
        model (str): 当前模型名称
        api_key (str): API 密钥
        base_url (str): API 基础 URL（自定义时使用第三方代理）
        temperature (float): 生成温度
        max_tokens (int): 最大生成 token 数
        rate_limit_delay (float): API 调用间隔（秒）
        max_retries (int): 最大重试次数
        router (ModelRouter): 模型路由器（可选）
        validator (SchemaValidator): Schema 校验器
        safety (SafetyLayer): 安全隔离层
        stats (dict): 生成统计（success/failed/total_tokens/retries/schema_repairs）
        client: API 客户端实例（OpenAI 或 Anthropic）
    
    Example:
        >>> generator = AnalysisGenerator({'backend': 'DeepSeek', 'model': 'DeepSeek-V3.2'})
        >>> result = generator.generate_analysis("对话内容...", agent_type='neutral')
    """
    
    # 支持的后端（保留向后兼容）
    SUPPORTED_BACKENDS = ['openai', 'DeepSeek', 'Kimi', 'kimi', 'Qwen', 'qwen_local', 'qwen_cloud', 'deepseek', 'glm']
    
    def __init__(
        self,
        config: Optional[dict] = None,
        router: Optional['ModelRouter'] = None,
        validator: Optional[SchemaValidator] = None,
        safety: Optional[SafetyLayer] = None,
    ):
        """
        初始化生成器
        
        Args:
            config: 配置字典，包含：
                - backend: LLM 后端类型
                - model: 模型名称
                - api_key: API 密钥
                - base_url: API 地址（可选）
                - temperature: 生成温度
                - max_tokens: 最大生成长度
                - rate_limit_delay: API 调用间隔
            router: 模型路由器（可选，启用智能路由）
            validator: Schema 校验器（可选，启用结构化输出校验）
            safety: 安全隔离层（可选，启用云端输出分离）
        """
        config = config or {}
        self.backend = config.get('backend', 'openai')
        self.model = config.get('model', 'GLM-4')
        self.api_key = config.get('api_key') or self._get_api_key_from_env()
        # base_url 优先级: CLI 参数 > 环境变量 > advisor.yaml > 内置默认
        self.base_url = config.get('base_url') or self._get_base_url_from_env()
        # model 可被环境变量覆盖（仅当 CLI 未显式指定时）
        env_model = self._get_model_from_env()
        if env_model and not config.get('model'):
            self.model = env_model
        self.temperature = config.get('temperature', 0.7)
        self.max_tokens = config.get('max_tokens', 16384)
        self.rate_limit_delay = config.get('rate_limit_delay', 1.0)
        self.max_retries = config.get('max_retries', 3)
        self.retry_delay = config.get('retry_delay', 5.0)
        
        # 新组件
        self.router = router
        self.validator = validator or SchemaValidator()
        self.safety = safety or SafetyLayer()
        
        # 统计信息
        self.stats = {
            'success': 0,
            'failed': 0,
            'total_tokens': 0,
            'retries': 0,
            'schema_repairs': 0,
        }
        
        # Response API 模式检测 (第三方代理 GLM 必须用 Response API)
        self._use_response_api = self._detect_response_api()
        
        # 初始化客户端
        self.client = None
        self._init_client()
    
    # 后端名 → 环境变量前缀 的映射
    _ENV_PREFIX = {
        'openai': 'OPENAI',
        'DeepSeek': 'ANTHROPIC',
        'Kimi': 'GOOGLE',
        'kimi': 'MOONSHOT',
        'Qwen': 'QWEN',
        'deepseek': 'DEEPSEEK',
        'qwen_local': 'QWEN_LOCAL',
        'qwen_cloud': 'DASHSCOPE',
        'glm': 'ZHIPU',
    }

    # 已知的 thinking 模型关键词（模型名中包含即视为 thinking 模型）
    _THINKING_PATTERNS = ['think', 'reason', '-high', 'o1', 'o3', 'o4']

    def _detect_response_api(self) -> bool:
        """检测是否需要使用 OpenAI Response API (wire_api=responses)
        
        某些代理商（如 第三方代理）要求 GLM 模型必须使用 Response API 格式。
        通过环境变量 {BACKEND}_WIRE_API=responses 启用。
        
        Returns:
            bool: True 表示需要使用 Response API
        """
        prefix = self._ENV_PREFIX.get(self.backend)
        if not prefix:
            return False
        wire_api = os.environ.get(f'{prefix}_WIRE_API', '')
        return wire_api.lower() == 'responses'

    def _is_thinking_model(self) -> bool:
        """判断当前模型是否为 thinking 模型
        
        thinking 模型（如 o1, o3, DeepSeek-R1）不支持 temperature 等采样参数。
        通过模型名称中的关键词（think/reason/-high/o1/o3/o4）判断。
        
        Returns:
            bool: True 表示是 thinking 模型
        """
        name = self.model.lower()
        return any(p in name for p in self._THINKING_PATTERNS)

    def _get_api_key_from_env(self) -> Optional[str]:
        """从环境变量获取 API 密钥
        
        根据后端名称查找对应的环境变量：{BACKEND_PREFIX}_API_KEY
        例如 openai → OPENAI_API_KEY, DeepSeek → ANTHROPIC_API_KEY
        
        Returns:
            str | None: API 密钥，未找到返回 None
        """
        prefix = self._ENV_PREFIX.get(self.backend)
        if not prefix:
            return None
        return os.environ.get(f'{prefix}_API_KEY')

    def _get_base_url_from_env(self) -> Optional[str]:
        """从环境变量获取自定义 base_url
        
        支持第三方供应商的自定义 API 端点。
        环境变量格式：{BACKEND_PREFIX}_BASE_URL
        
        Returns:
            str | None: 自定义 base_url，未找到返回 None
        """
        prefix = self._ENV_PREFIX.get(self.backend)
        if not prefix:
            return None
        return os.environ.get(f'{prefix}_BASE_URL')

    def _get_model_from_env(self) -> Optional[str]:
        """从环境变量获取模型名覆盖
        
        允许通过环境变量 {BACKEND_PREFIX}_MODEL 覆盖配置文件中的模型名。
        仅当 CLI 未显式指定 model 参数时生效。
        
        Returns:
            str | None: 模型名称，未找到返回 None
        """
        prefix = self._ENV_PREFIX.get(self.backend)
        if not prefix:
            return None
        return os.environ.get(f'{prefix}_MODEL')
    
    def _init_client(self):
        """初始化 API 客户端
        
        策略：
        - 当 DeepSeek 使用官方 API（无自定义 base_url）→ 使用 Anthropic 原生 SDK
        - 当 DeepSeek 使用第三方供应商（有自定义 base_url）→ 走 OpenAI 兼容接口
        - 其余所有后端 → OpenAI 兼容接口
        """
        # 所有后端的官方默认 base_url
        default_urls = {
            'openai': 'HTTPS://api.openai.com/v1',
            'Kimi': 'HTTPS://api.Kimi.com/v1beta/openai/',
            'kimi': 'HTTPS://api.kimi.com/v1',
            'Qwen': 'HTTPS://api.Qwen.com/v1',
            'deepseek': 'HTTPS://api.deepseek.com/v1',
            'qwen_local': 'http://localhost:11434/v1',
            'qwen_cloud': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
            'glm': 'https://open.bigmodel.cn/api/paas/v4',
        }
        
        # 判断 DeepSeek 是否使用第三方供应商
        self._DeepSeek_native = (self.backend == 'DeepSeek' and not self.base_url)
        
        if self._DeepSeek_native:
            # DeepSeek 官方 API → Anthropic 原生 SDK
            try:
                from anthropic import Anthropic
                self.client = Anthropic(api_key=self.api_key)
            except ImportError:
                print("警告：未安装 anthropic 库，请运行 pip install anthropic")
        else:
            # 所有后端（含第三方 DeepSeek）→ OpenAI 兼容接口
            base_url = self.base_url or default_urls.get(self.backend)
            try:
                from openai import OpenAI
                # thinking 模型响应慢，给足超时时间（连接30s，读取5min）
                from httpx import Timeout
                timeout = Timeout(connect=30.0, read=300.0, write=30.0, pool=30.0)
                self.client = OpenAI(
                    api_key=self.api_key or 'not-needed',
                    base_url=base_url,
                    timeout=timeout,
                )
            except ImportError:
                print("警告：未安装 openai 库，请运行 pip install openai")
    
    def generate_analysis(
        self,
        conversation: str,
        agent_type: str = 'neutral',
        graph_context: Optional[str] = None,
        mm_density: Optional[dict] = None,
    ) -> Optional[CloudAnalysisResponse]:
        """
        为单个对话生成分析（含 JSON Schema 自修复循环和云端输出分层）
        
        Args:
            conversation: 格式化的对话文本
            agent_type: Agent 类型（neutral/supportive/psychoanalytic）
            graph_context: GraphRAG 检索到的历史上下文（可选）
            mm_density: D1 多模态密度元数据（可选）
        
        Returns:
            CloudAnalysisResponse（含 analysis_features + rationale_private）
        """
        if agent_type not in PROMPTS:
            raise ValueError(f"不支持的 Agent 类型: {agent_type}")
        
        context_text = ""
        if graph_context:
            context_text = f"【历史上下文】\n{graph_context}"
        
        # D2: 构建 mm_context（多模态密度提示）
        mm_context_text = ""
        if mm_density:
            d = mm_density
            if d.get('total_multimodal', 0) > 0:
                parts = []
                if d.get('voice', 0): parts.append(f"语音{d['voice']}条")
                if d.get('image', 0): parts.append(f"图片{d['image']}条")
                if d.get('sticker', 0): parts.append(f"表情包{d['sticker']}条")
                if d.get('video', 0): parts.append(f"视频{d['video']}条")
                if d.get('emotion_tagged', 0): parts.append(f"含情绪标签{d['emotion_tagged']}条")
                density_pct = round(d.get('density', 0) * 100, 1)
                mm_context_text = (
                    f"【多模态密度提示】本段对话共{d.get('total_messages', 0)}条消息，"
                    f"其中多模态消息{d['total_multimodal']}条（{', '.join(parts)}），"
                    f"多模态密度{density_pct}%。请特别关注这些非文字信号的情感含义。"
                )
        
        # 格式化 prompt（兼容有/无 mm_context 占位符的模板）
        try:
            prompt = PROMPTS[agent_type].format(
                conversation=conversation,
                graph_context=context_text,
                mm_context=mm_context_text,
            )
        except KeyError:
            prompt = PROMPTS[agent_type].format(
                conversation=conversation,
                graph_context=context_text,
            )
        
        for attempt in range(self.max_retries):
            try:
                response = self._call_api(prompt)
                if response:
                    # 使用 SchemaValidator 校验 + 自修复
                    result = self.validator.validate_and_repair(
                        raw_response=response,
                        agent_type=agent_type,
                        call_llm_fn=lambda p: self._call_api(p),
                        fallback_llm_fn=self._get_fallback_fn(),
                    )
                    if result is not None:
                        # 记录审计日志
                        self.safety.log_private(result)
                        self.stats['success'] += 1
                        repair_count = result.rationale_private.repair_attempts
                        if repair_count > 0:
                            self.stats['schema_repairs'] += repair_count
                        return result
                    else:
                        logger.warning(
                            f"Schema 校验失败 (agent_type={agent_type}, attempt={attempt+1})"
                        )
            except Exception as e:
                self.stats['retries'] += 1
                if attempt < self.max_retries - 1:
                    logger.warning(f"API 调用失败，{self.retry_delay}秒后重试: {e}")
                    time.sleep(self.retry_delay)
                else:
                    logger.error(f"API 调用失败，已达最大重试次数: {e}")
                    self.stats['failed'] += 1
        
        return None
    
    def generate_safe_context(
        self,
        conversation: str,
        agent_type: str = 'neutral',
        graph_context: Optional[str] = None,
    ) -> Optional[str]:
        """
        生成分析并返回安全的纯文本上下文（供本地模型使用）。
        
        这是完整的 Cloud→Schema→Safety→Local 流程的前半段。
        
        Args:
            conversation: 对话文本
            agent_type: Agent 类型
            graph_context: GraphRAG 上下文
        
        Returns:
            安全的纯文本上下文字符串，或 None
        """
        result = self.generate_analysis(conversation, agent_type, graph_context)
        if result is None:
            return None
        return self.safety.sanitize_for_local(result)
    
    def _call_api(self, prompt: str) -> Optional[str]:
        """调用 LLM API（统一接口）
        
        第三方代理对某些模型（如 thinking 模型）的 non-stream 模式可能返回 500，
        此时自动降级到 stream 模式收集完整响应。
        """
        # Response API 模式 (第三方代理 GLM 要求)
        if self._use_response_api:
            return self._call_api_response_api(prompt)
        
        if self._DeepSeek_native:
            # DeepSeek 官方 API → Anthropic 原生 SDK
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            if response.usage:
                self.stats['total_tokens'] += response.usage.input_tokens + response.usage.output_tokens
            return response.content[0].text
        else:
            # 所有后端（含第三方 DeepSeek）→ OpenAI 兼容接口
            messages = [{"role": "user", "content": prompt}]
            # thinking 模型通常不支持 temperature 参数
            kwargs = dict(
                model=self.model,
                messages=messages,
                max_tokens=self.max_tokens,
            )
            if self.temperature is not None and not self._is_thinking_model():
                kwargs['temperature'] = self.temperature
            
            # 如果有自定义 base_url（第三方代理），优先用 stream 模式
            use_stream = bool(self.base_url)
            
            if use_stream:
                return self._call_api_stream(kwargs)
            else:
                response = self.client.chat.completions.create(**kwargs)
                if response.usage:
                    self.stats['total_tokens'] += response.usage.total_tokens
                return response.choices[0].message.content
    
    def _call_api_response_api(self, prompt: str) -> Optional[str]:
        """调用 OpenAI Response API (wire_api=responses)
        
        某些代理商 (如 第三方代理) 要求 GLM 模型必须使用 Response API 格式，
        而非 Chat Completions。Response API 端点: {base_url}/responses
        """
        import httpx
        
        url = f"{self.base_url.rstrip('/')}/responses"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        payload = {
            "model": self.model,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": prompt,
                        }
                    ],
                }
            ],
            "store": False,
            "stream": True,
        }
        
        prefix = self._ENV_PREFIX.get(self.backend, '')
        effort = os.environ.get(f'{prefix}_REASONING_EFFORT', '')
        if effort:
            payload["reasoning"] = {"effort": effort}
        
        if self.max_tokens:
            payload["max_output_tokens"] = self.max_tokens
        
        timeout = httpx.Timeout(connect=30.0, read=300.0, write=30.0, pool=30.0)
        collected: list[str] = []
        usage: dict = {}
        with httpx.Client(timeout=timeout) as client:
            with client.stream("POST", url, headers=headers, json=payload) as response:
                response.raise_for_status()
                current_event = None
                for line in response.iter_lines():
                    if not line:
                        current_event = None
                        continue
                    if line.startswith("event:"):
                        current_event = line.split(":", 1)[1].strip()
                        continue
                    if not line.startswith("data:"):
                        continue
                    data_str = line.split(":", 1)[1].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        obj = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    event_type = obj.get("type") or current_event
                    if event_type == "response.output_text.delta":
                        delta = obj.get("delta", "")
                        if delta:
                            collected.append(delta)
                    elif event_type in ("response.completed", "response.done"):
                        resp_obj = obj.get("response") or {}
                        usage = resp_obj.get("usage", {}) or {}
                        break
        
        if usage:
            self.stats['total_tokens'] += usage.get('input_tokens', 0) + usage.get('output_tokens', 0)
        
        text = ''.join(collected).strip()
        return text or None
    
    def _call_api_stream(self, kwargs: dict) -> Optional[str]:
        """Stream 模式调用 API（兼容第三方代理）
        
        使用 OpenAI 兼容的 stream 接口逐 chunk 收集响应文本。
        适用于第三方代理对 non-stream 模式支持不佳的情况。
        
        Args:
            kwargs (dict): chat.completions.create 的参数字典
        
        Returns:
            str | None: 完整响应文本，无内容返回 None
        """
        kwargs['stream'] = True
        stream = self.client.chat.completions.create(**kwargs)
        collected = []
        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                collected.append(chunk.choices[0].delta.content)
        return ''.join(collected) if collected else None
    
    def _get_fallback_fn(self) -> Optional[callable]:
        """获取 fallback LLM 调用函数
        
        当 Schema 修复失败时，使用 fallback 模型（如 DeepSeek Reasoner）
        尝试将原始响应转换为合法 JSON 格式。
        
        Returns:
            callable | None: fallback 函数，无 router 时返回 None
        """
        if self.router is None:
            return None
        
        def fallback_fn(original_response: str) -> str:
            fallback_prompt = (
                "请将以下分析结果严格转换为要求的 JSON 格式：\n\n"
                f"{original_response[:3000]}"
            )
            return self.router.call('deepseek_reasoner', fallback_prompt)
        
        return fallback_fn
    
    def swap_api_key(self, new_key: str):
        """
        运行时切换 API 密钥（用于 key 被限流/封禁后热替换）
        
        Args:
            new_key: 新的 API 密钥
        """
        self.api_key = new_key
        self._init_client()
        logger.info("API 密钥已切换，客户端已重新初始化")

    @staticmethod
    def _scan_completed(output_path: str) -> set[str]:
        """
        扫描已有输出文件，收集已完成的 chunk_id 集合（用于断点续跑）
        
        Returns:
            已完成的 chunk_id 集合
        """
        completed = set()
        path = Path(output_path)
        if not path.exists():
            return completed
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    cid = data.get('chunk_id', '')
                    if cid:
                        completed.add(cid)
                except json.JSONDecodeError:
                    continue
        return completed

    def batch_generate(
        self,
        chunks: list[dict],
        agent_type: str,
        output_path: str,
        resume: bool = True,
    ) -> list[dict]:
        """
        批量生成分析并保存（支持断点续跑）
        
        Args:
            chunks: 对话片段列表
            agent_type: Agent 类型
            output_path: 输出文件路径
            resume: 是否断点续跑（默认 True，跳过已完成的 chunk_id）
        
        Returns:
            本次新生成的分析结果列表
        """
        results = []
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        # 断点续跑：扫描已完成的 chunk_id
        completed_ids = set()
        if resume:
            completed_ids = self._scan_completed(output_path)
            if completed_ids:
                logger.info(f"断点续跑：已完成 {len(completed_ids)} 条，跳过")
                print(f"\n断点续跑：已完成 {len(completed_ids)}/{len(chunks)} 条，继续处理剩余部分")
        
        # 过滤待处理的 chunks
        pending = [
            c for c in chunks
            if c.get('chunk_id', '') not in completed_ids
        ]
        
        if not pending:
            print("所有 chunks 已处理完毕，无需重新生成")
            return results
        
        # 追加模式写入
        with open(path, 'a', encoding='utf-8') as f:
            for chunk in tqdm(pending, desc=f"生成 {agent_type} 分析"):
                conversation = chunk.get('conversation_text', '')
                chunk_id = chunk.get('chunk_id', '')
                graph_context = chunk.get('graph_context')
                
                cloud_response = self.generate_analysis(
                    conversation, agent_type, graph_context,
                )
                
                if cloud_response:
                    # 序列化：features 完整保存，private 仅保存元数据
                    features = cloud_response.get_features_for_local()
                    result = {
                        'chunk_id': chunk_id,
                        'conversation': conversation,
                        'analysis_features': features.model_dump(),
                        'agent_type': agent_type,
                        'safe_context': self.safety.sanitize_for_local(cloud_response),
                        'repair_attempts': cloud_response.rationale_private.repair_attempts,
                    }
                    results.append(result)
                    f.write(json.dumps(result, ensure_ascii=False) + '\n')
                    f.flush()  # 每条写完立即刷盘，防止中断丢失
                
                # API 调用间隔
                time.sleep(self.rate_limit_delay)
        
        total = len(completed_ids) + len(results)
        logger.info(f"已保存 {total} 个分析到 {output_path}（本次新增 {len(results)}）")
        return results
    
    def get_stats(self) -> dict:
        """获取生成统计信息
        
        Returns:
            dict: 统计字典，包含：
                - success (int): 成功生成数
                - failed (int): 失败数
                - total_tokens (int): 总消耗 token 数
                - retries (int): 重试次数
                - schema_repairs (int): Schema 修复次数
        """
        return self.stats.copy()
