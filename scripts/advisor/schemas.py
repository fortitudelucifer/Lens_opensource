"""
结构化输出 Schema 定义模块

功能：
- 定义云端 LLM 分析的 Pydantic 结构化输出模型
- 实现 analysis_features（下发本地）/ rationale_private（仅审计）的数据分离
- 提供三种 Agent 类型的专用 Schema：
  1. AnalysisFeatures — 中立顾问的结构化分析要点
  2. SupportiveFeatures — 支持性顾问的扩展特征（含情感验证）
  3. PsychoanalyticFeatures — 精神分析顾问的人格/动态分析
- 定义枚举类型：关系状态、沟通质量、依附风格、风险级别
- 导出 JSON Schema 供 response_format / schema_validator 使用

处理流程：
1. 云端 LLM 生成原始 JSON 响应
2. SchemaValidator 使用本模块的 Pydantic 模型进行校验
3. 校验通过后构建 CloudAnalysisResponse 对象
4. get_features_for_local() 提取下发给本地模型的 features
5. get_private_for_audit() 提取仅用于审计的 rationale_private
6. SafetyLayer 对 features 进行诊断术语替换后下发本地模型

输入：
- 云端 LLM 的 JSON 格式分析结果

输出：
- CloudAnalysisResponse 对象（含 features + private 两部分）
- JSON Schema 字典（ANALYSIS_JSON_SCHEMA 等，供 API 的 response_format 使用）

依赖：
- pydantic: 数据模型定义、校验和 JSON Schema 导出

使用示例：
    # 导入 Schema 模型
    from scripts.advisor.schemas import (
        AnalysisFeatures,
        CloudAnalysisResponse,
        PsychoanalyticFeatures,
    )
    
    # 从 JSON 构建对象
    features = AnalysisFeatures(**json_data)
    
    # 构建完整响应
    response = CloudAnalysisResponse(
        agent_type='neutral',
        analysis_features=features,
    )
    
    # 获取下发给本地模型的 features
    local_features = response.get_features_for_local()
    
    # 导出 JSON Schema
    from scripts.advisor.schemas import ANALYSIS_JSON_SCHEMA
    print(ANALYSIS_JSON_SCHEMA)

注意事项：
- AnalysisFeatures 是 Cloud→Local 的唯一数据通道，不包含诊断性语言
- RationalePrivate 仅写入审计日志，绝不下发给本地模型
- 列表字段（key_issues, advice 等）通过 model_validator 自动截断到最大长度
- CloudAnalysisResponse 的 validate_features_match_type 确保 features 类型与 agent_type 一致
- 扩展字段（conflict_root_causes, time_patterns 等）为 Optional，向后兼容旧版数据

作者：[Author]
更新于：2026-02-15
"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator


# =============================================================================
# 枚举类型
# =============================================================================

class RelationshipStatus(str, Enum):
    """关系状态枚举
    
    描述当前关系所处的阶段，用于 AnalysisFeatures.relationship_status 字段。
    
    Values:
        HEALTHY: 健康期 — 双方沟通良好，关系稳定
        SWEET: 甜蜜期 — 高频互动，正面情绪主导
        PLAIN: 平淡期 — 互动减少，内容趋于事务性
        COLD: 冷淡期 — 明显疏远，回复延迟或缺失
        CONFLICT: 冲突期 — 频繁争吵，负面情绪主导
    """
    HEALTHY = "健康期"
    SWEET = "甜蜜期"
    PLAIN = "平淡期"
    COLD = "冷淡期"
    CONFLICT = "冲突期"


class CommunicationQuality(str, Enum):
    """沟通质量枚举
    
    评估对话中双方的沟通效果，用于 AnalysisFeatures.communication_quality 字段。
    
    Values:
        EXCELLENT: 优秀 — 积极倾听，有效表达，冲突建设性解决
        GOOD: 良好 — 基本顺畅，偶有误解但能及时修复
        AVERAGE: 一般 — 表面沟通，缺乏深度情感交流
        POOR: 较差 — 频繁误解，防御性沟通，回避重要话题
        VERY_POOR: 很差 — Gottman 四骑士（批评/蔑视/防御/石墙）频繁出现
    """
    EXCELLENT = "优秀"
    GOOD = "良好"
    AVERAGE = "一般"
    POOR = "较差"
    VERY_POOR = "很差"


class AttachmentStyle(str, Enum):
    """依附风格枚举
    
    基于 Bowlby 依附理论的四种依附类型，用于精神分析 Agent 的人格特征分析。
    
    Values:
        SECURE: 安全型 — 信任他人，舒适地表达需求和情感
        ANXIOUS: 焦虑型 — 害怕被抛弃，过度寻求确认和亲密
        AVOIDANT: 回避型 — 回避亲密，强调独立，压抑情感需求
        DISORGANIZED: 混乱型 — 矛盾的亲密需求，既渴望又恐惧
    """
    SECURE = "安全型"
    ANXIOUS = "焦虑型"
    AVOIDANT = "回避型"
    DISORGANIZED = "混乱型"


class RiskLevel(str, Enum):
    """风险级别枚举
    
    评估对话中检测到的关系风险程度，高风险触发 SafetyLayer 安全干预。
    
    Values:
        NONE: 无 — 未检测到风险信号
        LOW: 低 — 轻微不适信号，建议关注
        MEDIUM: 中 — 明显冲突或情绪困扰，建议干预
        HIGH: 高 — 严重冲突或心理危机信号，需要专业帮助
        CRITICAL: 紧急 — 自伤/暴力等紧急风险，立即干预
    """
    NONE = "无"
    LOW = "低"
    MEDIUM = "中"
    HIGH = "高"
    CRITICAL = "紧急"


# =============================================================================
# 批评子模型
# =============================================================================

class CriticismPair(BaseModel):
    """双方批评模型
    
    分别记录对 ME（用户）和 OTHER（对方）的行为批评。
    批评应基于具体行为而非人格特质。
    
    Attributes:
        ME (str): 对用户（ME）的批评，1-500 字符
        OTHER (str): 对对方（OTHER）的批评，1-500 字符
    
    Example:
        >>> criticism = CriticismPair(
        ...     ME="在争吵中使用了'你总是'这样的绝对化表达",
        ...     OTHER="多次已读不回，缺乏基本的沟通回应"
        ... )
    """
    ME: str = Field(..., min_length=1, max_length=500, description="对 ME 的批评")
    OTHER: str = Field(..., min_length=1, max_length=500, description="对 OTHER 的批评")


# =============================================================================
# 核心 Schema：analysis_features（下发本地）
# =============================================================================

class AnalysisFeatures(BaseModel):
    """
    云端分析的结构化要点 —— 下发给本地模型作为生成上下文。
    
    不包含诊断性语言、专业术语、或云端推理过程。
    这是 Cloud→Local 的唯一数据通道。
    """
    relationship_status: RelationshipStatus = Field(
        ..., description="关系状态阶段"
    )
    communication_quality: CommunicationQuality = Field(
        ..., description="沟通质量评级"
    )
    emotional_balance: str = Field(
        ..., min_length=1, max_length=200,
        description="情绪平衡描述（平衡/ME主动/OTHER主动/不对等）"
    )
    key_issues: list[str] = Field(
        ..., min_length=1, max_length=3,
        description="关键问题列表（1-3条）"
    )
    advice: list[str] = Field(
        ..., min_length=1, max_length=3,
        description="改善建议列表（1-3条）"
    )
    criticism: CriticismPair = Field(
        ..., description="双方批评"
    )
    overall_assessment: str = Field(
        ..., min_length=1, max_length=500,
        description="整体评价（1-2句话）"
    )
    risk_level: RiskLevel = Field(
        default=RiskLevel.NONE,
        description="风险级别（用于触发安全干预）"
    )
    # ---- 多模态 & 冲突根源分析扩展字段（Optional，向后兼容） ----
    conflict_root_causes: Optional[list[str]] = Field(
        default=None, max_length=3,
        description="冲突根源分析（从10种根源中识别，需引用对话证据）"
    )
    time_patterns: Optional[list[str]] = Field(
        default=None, max_length=3,
        description="时间线模式识别（冷暴力/争吵升级/追逃/修复尝试等）"
    )
    multimodal_signals: Optional[str] = Field(
        default=None, max_length=500,
        description="多模态信号总结（语音情绪、图片氛围、表情意图等情感暗示）"
    )
    repair_attempts: Optional[str] = Field(
        default=None, max_length=300,
        description="关系修复尝试识别及效果评估"
    )
    personality_dynamics: Optional[str] = Field(
        default=None, max_length=300,
        description="双方沟通风格与依附倾向初步判断"
    )

    @model_validator(mode='after')
    def validate_list_lengths(self) -> 'AnalysisFeatures':
        if len(self.key_issues) > 3:
            self.key_issues = self.key_issues[:3]
        if len(self.advice) > 3:
            self.advice = self.advice[:3]
        if self.conflict_root_causes and len(self.conflict_root_causes) > 3:
            self.conflict_root_causes = self.conflict_root_causes[:3]
        if self.time_patterns and len(self.time_patterns) > 3:
            self.time_patterns = self.time_patterns[:3]
        return self


class SupportiveFeatures(AnalysisFeatures):
    """支持性 Agent 的扩展特征
    
    继承 AnalysisFeatures 的所有字段，额外增加情感验证字段。
    支持性 Agent 优先验证用户（ME）的感受，批评偏向对方（OTHER）。
    
    Attributes:
        emotional_validation (str): 情感验证文本，首先验证用户 ME 的感受是合理的，1-500 字符
    
    Example:
        >>> features = SupportiveFeatures(
        ...     relationship_status=RelationshipStatus.CONFLICT,
        ...     communication_quality=CommunicationQuality.POOR,
        ...     emotional_balance="ME 投入更多情感",
        ...     emotional_validation="你感到失望和受伤是完全可以理解的",
        ...     key_issues=["对方回复冷淡"],
        ...     advice=["尝试表达你的感受"],
        ...     criticism=CriticismPair(ME="可以更直接表达需求", OTHER="缺乏情感回应"),
        ...     overall_assessment="关系处于冷淡期",
        ... )
    """
    emotional_validation: str = Field(
        ..., min_length=1, max_length=500,
        description="情感验证（首先验证用户 ME 的感受是合理的）"
    )


# =============================================================================
# 精神分析 Agent 特有 Schema
# =============================================================================

class PersonalityProfile(BaseModel):
    """单方人格特征模型
    
    精神分析视角下的个体人格画像，包含依附风格、防御机制和欲望模式。
    
    Attributes:
        attachment_style (AttachmentStyle): 依附风格（安全型/焦虑型/回避型/混乱型）
        defense_mechanisms (list[str]): 主要防御机制列表（1-5 个），如理智化、投射、否认等
        desire_pattern (str): 欲望模式描述，1-300 字符
    
    Example:
        >>> profile = PersonalityProfile(
        ...     attachment_style=AttachmentStyle.ANXIOUS,
        ...     defense_mechanisms=["投射", "理智化"],
        ...     desire_pattern="渴望被无条件接纳，通过频繁确认来缓解分离焦虑"
        ... )
    """
    attachment_style: AttachmentStyle = Field(..., description="依附风格")
    defense_mechanisms: list[str] = Field(
        ..., min_length=1, max_length=5,
        description="主要防御机制列表"
    )
    desire_pattern: str = Field(
        ..., min_length=1, max_length=300,
        description="欲望模式描述"
    )


class RelationshipDynamics(BaseModel):
    """关系动态模型
    
    精神分析视角下的双方关系互动模式分析。
    
    Attributes:
        attachment_interaction (str): 依附互动描述（如焦虑-回避追逃循环）
        unconscious_contract (str): 无意识契约描述（双方隐含的关系约定）
        transference_pattern (str): 移情模式描述（早期客体关系的重复）
    
    Example:
        >>> dynamics = RelationshipDynamics(
        ...     attachment_interaction="焦虑型追逐-回避型退缩的经典追逃循环",
        ...     unconscious_contract="ME 负责情感供给，OTHER 负责理性决策",
        ...     transference_pattern="ME 将早期被忽视的体验投射到 OTHER 的沉默上"
        ... )
    """
    attachment_interaction: str = Field(..., min_length=1, description="依附互动描述")
    unconscious_contract: str = Field(..., min_length=1, description="无意识契约")
    transference_pattern: str = Field(..., min_length=1, description="移情模式")


class PsychoanalyticFeatures(BaseModel):
    """
    精神分析 Agent 的结构化要点 —— 下发给本地模型。
    
    注意：下发版本中诊断性术语会被 SafetyLayer 替换为通俗表达。
    """
    me_profile: PersonalityProfile = Field(..., description="ME 的人格特征")
    other_profile: PersonalityProfile = Field(..., description="OTHER 的人格特征")
    dynamics: RelationshipDynamics = Field(..., description="关系动态分析")
    developmental_suggestions: list[str] = Field(
        ..., min_length=1, max_length=3,
        description="发展性建议（1-3条）"
    )
    overall_assessment: str = Field(
        ..., min_length=1, max_length=500,
        description="精神分析视角的整体评价"
    )
    risk_level: RiskLevel = Field(
        default=RiskLevel.NONE,
        description="风险级别"
    )


# =============================================================================
# rationale_private（仅审计，不下发本地）
# =============================================================================

class RationalePrivate(BaseModel):
    """
    云端推理过程和诊断性分析 —— 仅写入审计日志，绝不下发给本地模型。
    
    包含：
    - 云端的完整推理链（thinking/chain-of-thought）
    - 专业诊断性语言
    - 云端模型的不确定性评估
    """
    thinking_process: str = Field(
        default="",
        description="云端模型的完整推理链（<think> 标签内容）"
    )
    diagnostic_notes: str = Field(
        default="",
        description="专业诊断性备注（不对用户可见）"
    )
    confidence_score: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="云端对本次分析的置信度（0-1）"
    )
    model_used: str = Field(
        default="",
        description="实际使用的云端模型名称"
    )
    token_usage: int = Field(
        default=0, ge=0,
        description="本次 API 调用消耗的 token 数"
    )
    repair_attempts: int = Field(
        default=0, ge=0,
        description="Schema 修复尝试次数"
    )
    raw_response: str = Field(
        default="",
        description="云端模型的原始完整响应"
    )


# =============================================================================
# 完整云端分析响应（包含两个分离的部分）
# =============================================================================

class CloudAnalysisResponse(BaseModel):
    """
    云端分析的完整响应 —— 包含 features（下发）和 private（审计）两部分。
    
    使用方:
    - analysis_features → SafetyLayer → 本地模型上下文
    - rationale_private → audit_log（永不到达本地模型）
    """
    agent_type: str = Field(
        ..., description="Agent 类型: neutral / supportive / psychoanalytic"
    )
    analysis_features: Optional[AnalysisFeatures] = Field(
        default=None,
        description="结构化分析要点（neutral/supportive 类型）"
    )
    supportive_features: Optional[SupportiveFeatures] = Field(
        default=None,
        description="支持性分析要点（supportive 类型专用）"
    )
    psychoanalytic_features: Optional[PsychoanalyticFeatures] = Field(
        default=None,
        description="精神分析要点（psychoanalytic 类型专用）"
    )
    rationale_private: RationalePrivate = Field(
        default_factory=RationalePrivate,
        description="云端推理过程（仅审计）"
    )

    @model_validator(mode='after')
    def validate_features_match_type(self) -> 'CloudAnalysisResponse':
        """确保 features 类型与 agent_type 一致"""
        if self.agent_type == 'neutral' and self.analysis_features is None:
            raise ValueError("neutral 类型必须包含 analysis_features")
        if self.agent_type == 'supportive' and self.supportive_features is None:
            raise ValueError("supportive 类型必须包含 supportive_features")
        if self.agent_type == 'psychoanalytic' and self.psychoanalytic_features is None:
            raise ValueError("psychoanalytic 类型必须包含 psychoanalytic_features")
        return self

    def get_features_for_local(self) -> AnalysisFeatures | SupportiveFeatures | PsychoanalyticFeatures:
        """获取下发给本地模型的 features（不含 rationale_private）"""
        if self.agent_type == 'supportive' and self.supportive_features:
            return self.supportive_features
        if self.agent_type == 'psychoanalytic' and self.psychoanalytic_features:
            return self.psychoanalytic_features
        if self.analysis_features:
            return self.analysis_features
        raise ValueError(f"无法获取 {self.agent_type} 类型的 features")

    def get_private_for_audit(self) -> RationalePrivate:
        """获取仅用于审计的 rationale_private"""
        return self.rationale_private


# =============================================================================
# JSON Schema 导出（供 response_format / schema_validator 使用）
# =============================================================================

ANALYSIS_JSON_SCHEMA = AnalysisFeatures.model_json_schema()
SUPPORTIVE_JSON_SCHEMA = SupportiveFeatures.model_json_schema()
PSYCHOANALYTIC_JSON_SCHEMA = PsychoanalyticFeatures.model_json_schema()
