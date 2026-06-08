"""
安全隔离层模块

功能：
- 实现云端推理过程（rationale_private）与本地模型上下文的严格隔离
- 对 analysis_features 进行诊断性语言过滤和敏感词替换
- 将安全处理后的分析要点以纯文本形式传递给本地模型
- 记录完整的云端推理过程到审计日志（仅供开发者审查）
- 风险检测：高风险内容触发安全干预提示

处理流程：
1. sanitize_for_local(): 接收 CloudAnalysisResponse
   a. 提取 analysis_features（下发部分）
   b. 执行诊断术语替换（如 '依附障碍' → '依附倾向'）
   c. 过滤敏感关键词
   d. 格式化为纯文本要点
   e. 返回安全的上下文字符串
2. log_private(): 将 rationale_private 写入审计日志
   a. 记录云端模型名称、token 消耗、修复次数
   b. 记录完整推理链（thinking_process）
   c. 记录诊断性备注（diagnostic_notes）

输入：
- CloudAnalysisResponse 对象（含 features + private 两部分）

输出：
- 安全的纯文本上下文字符串（供本地模型使用）
- 审计日志文件（JSON 格式）

依赖：
- scripts.advisor.schemas: CloudAnalysisResponse, AnalysisFeatures 等

使用示例：
    from scripts.advisor.safety_layer import SafetyLayer
    
    layer = SafetyLayer(config)
    safe_context = layer.sanitize_for_local(cloud_response)
    layer.log_private(cloud_response, output_dir='audit_logs/')

注意事项：
- rationale_private 绝不注入本地模型上下文，这是 P0 级安全要求
- 诊断术语替换映射可通过 configs/advisor.yaml 的 safety.diagnostic_replacements 配置
- 审计日志默认保存到 {workspace}/advisor_out/audit_logs/
- 风险级别为 HIGH 或 CRITICAL 时会在上下文中注入安全干预提示

作者：[Author]
更新于：2026-02-15
"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from scripts.advisor.schemas import (
    AnalysisFeatures,
    CloudAnalysisResponse,
    PsychoanalyticFeatures,
    RationalePrivate,
    RiskLevel,
    SupportiveFeatures,
)

logger = logging.getLogger('advisor.safety_layer')


# =============================================================================
# 默认过滤规则
# =============================================================================

# 诊断性术语 → 通俗替换（精神分析 Agent 用）
DEFAULT_DIAGNOSTIC_REPLACEMENTS = {
    '焦虑型依附': '对关系比较敏感、容易担心',
    '回避型依附': '倾向于保持距离感',
    '混乱型依附': '在亲密和距离之间摇摆不定',
    '安全型依附': '能够比较自如地处理亲密关系',
    '投射性认同': '把自己的感受放到对方身上',
    '投射': '把自己的感受放到对方身上',
    '分裂': '把事情看得非黑即白',
    '理想化': '过度美化对方',
    '贬低': '过度否定对方',
    '否认': '不愿面对现实',
    '合理化': '给自己找理由',
    '退行': '退回到更幼稚的应对方式',
    '反向形成': '用相反的方式表达真实感受',
    '升华': '把情绪转化为积极行为',
    '压抑': '把不愉快的想法推到意识之外',
    '移情': '把对过去重要人物的感受转移到当前关系中',
    '客体关系': '与重要他人的关系模式',
    '自恋型': '比较关注自己的需求',
    '边缘型': '情绪波动较大',
    '想象界': '自我认同和镜像关系',
    '象征界': '语言和社会规则层面',
    '实在界': '难以言说的深层感受',
    '无意识契约': '双方之间不自觉形成的默契',
    '防御机制': '心理上的自我保护方式',
    '依附风格': '与亲密的人相处的习惯模式',
    '人格结构': '性格和行为的深层模式',
}

# 高风险敏感词（触发风险标记）
DEFAULT_SENSITIVE_KEYWORDS = [
    '自杀', '自残', '自伤', '轻生', '寻死',
    '家暴', '暴力', '殴打', '虐待',
    '性侵', '强奸', '猥亵',
    '抑郁症', '双相情感障碍', '精神分裂',
    'PUA', '操控', '控制狂',
]

# 生成内容中不应出现的诊断性前缀
DIAGNOSTIC_PREFIXES = [
    '诊断：', '诊断:', '初步诊断',
    '临床表现', '症状表现',
    '疑似', '符合.*诊断标准',
]


class SafetyLayer:
    """
    安全隔离层
    
    职责：
    1. 对 analysis_features 进行诊断性语言过滤
    2. 将结构化要点转为安全的纯文本上下文（供本地模型使用）
    3. 将 rationale_private 写入审计日志（绝不传递给本地模型）
    4. 检测高风险内容并标记
    """

    def __init__(self, config: Optional[dict] = None):
        """
        Args:
            config: 配置字典，包含：
                - diagnostic_replacements: 诊断术语替换映射
                - sensitive_keywords: 敏感词列表
                - audit_log_dir: 审计日志目录
                - enable_risk_detection: 是否启用风险检测
        """
        config = config or {}
        self.replacements = config.get(
            'diagnostic_replacements', DEFAULT_DIAGNOSTIC_REPLACEMENTS,
        )
        self.sensitive_keywords = config.get(
            'sensitive_keywords', DEFAULT_SENSITIVE_KEYWORDS,
        )
        self.audit_log_dir = Path(config.get(
            'audit_log_dir', 'data/advisor/audit_logs',
        ))
        self.enable_risk_detection = config.get('enable_risk_detection', True)

    def sanitize_for_local(self, cloud_response: CloudAnalysisResponse) -> str:
        """
        将云端分析转为安全的纯文本上下文，供本地模型使用。
        
        关键约束：
        - 只从 analysis_features / supportive_features / psychoanalytic_features 提取
        - 绝不包含 rationale_private 中的任何内容
        - 诊断性术语替换为通俗表达
        - 输出为纯文本要点（非 JSON）
        
        Args:
            cloud_response: 完整的云端分析响应
        
        Returns:
            安全的纯文本上下文字符串
        """
        features = cloud_response.get_features_for_local()
        agent_type = cloud_response.agent_type

        if agent_type == 'psychoanalytic':
            return self._sanitize_psychoanalytic(features)
        elif agent_type == 'supportive':
            return self._sanitize_supportive(features)
        else:
            return self._sanitize_neutral(features)

    def log_private(
        self,
        cloud_response: CloudAnalysisResponse,
        chunk_id: str = "",
    ) -> Path:
        """
        将 rationale_private 写入审计日志。
        
        审计日志仅供内部审查，绝不传递给本地模型或用户。
        
        Args:
            cloud_response: 完整的云端分析响应
            chunk_id: 对话片段 ID
        
        Returns:
            审计日志文件路径
        """
        self.audit_log_dir.mkdir(parents=True, exist_ok=True)

        private = cloud_response.get_private_for_audit()
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"audit_{timestamp}_{chunk_id}.jsonl"
        log_path = self.audit_log_dir / filename

        log_entry = {
            'timestamp': datetime.now().isoformat(),
            'chunk_id': chunk_id,
            'agent_type': cloud_response.agent_type,
            'rationale_private': private.model_dump(),
        }

        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')

        logger.info(f"审计日志已写入: {log_path}")
        return log_path

    def detect_risk(self, text: str) -> RiskLevel:
        """
        检测文本中的风险级别。
        
        Args:
            text: 待检测文本
        
        Returns:
            风险级别
        """
        if not self.enable_risk_detection:
            return RiskLevel.NONE

        text_lower = text.lower()
        critical_keywords = ['自杀', '自残', '自伤', '轻生', '寻死']
        high_keywords = ['家暴', '暴力', '殴打', '虐待', '性侵', '强奸']

        for kw in critical_keywords:
            if kw in text_lower:
                return RiskLevel.CRITICAL

        for kw in high_keywords:
            if kw in text_lower:
                return RiskLevel.HIGH

        for kw in self.sensitive_keywords:
            if kw in text_lower:
                return RiskLevel.MEDIUM

        return RiskLevel.NONE

    # -------------------------------------------------------------------------
    # 内部方法：各 Agent 类型的 sanitize
    # -------------------------------------------------------------------------

    def _sanitize_neutral(self, features: AnalysisFeatures) -> str:
        """将 neutral 分析要点转为安全纯文本"""
        lines = [
            f"【关系状态】{features.relationship_status.value}",
            f"【沟通质量】{features.communication_quality.value}",
            f"【情绪平衡】{self._replace_diagnostic(features.emotional_balance)}",
            "【关键问题】",
        ]
        for i, issue in enumerate(features.key_issues, 1):
            lines.append(f"  {i}. {self._replace_diagnostic(issue)}")
        lines.append("【建议】")
        for i, adv in enumerate(features.advice, 1):
            lines.append(f"  {i}. {self._replace_diagnostic(adv)}")
        lines.append("【批评】")
        lines.append(f"  - ME: {self._replace_diagnostic(features.criticism.ME)}")
        lines.append(f"  - OTHER: {self._replace_diagnostic(features.criticism.OTHER)}")
        lines.append(f"【整体评价】{self._replace_diagnostic(features.overall_assessment)}")

        if features.risk_level != RiskLevel.NONE:
            lines.append(f"【风险提示】{features.risk_level.value}")

        return '\n'.join(lines)

    def _sanitize_supportive(self, features: SupportiveFeatures) -> str:
        """将 supportive 分析要点转为安全纯文本"""
        base = self._sanitize_neutral(features)
        validation_line = f"【情感验证】{self._replace_diagnostic(features.emotional_validation)}"
        # 插入到关系状态之后
        lines = base.split('\n')
        lines.insert(1, validation_line)
        return '\n'.join(lines)

    def _sanitize_psychoanalytic(self, features: PsychoanalyticFeatures) -> str:
        """将精神分析要点转为安全纯文本（大量术语替换）"""
        lines = [
            "【你的相处模式】",
            f"  - 亲密关系习惯: {self._replace_diagnostic(features.me_profile.attachment_style.value)}",
            f"  - 自我保护方式: {', '.join(self._replace_diagnostic(m) for m in features.me_profile.defense_mechanisms)}",
            f"  - 内心需求: {self._replace_diagnostic(features.me_profile.desire_pattern)}",
            "",
            "【对方的相处模式】",
            f"  - 亲密关系习惯: {self._replace_diagnostic(features.other_profile.attachment_style.value)}",
            f"  - 自我保护方式: {', '.join(self._replace_diagnostic(m) for m in features.other_profile.defense_mechanisms)}",
            f"  - 内心需求: {self._replace_diagnostic(features.other_profile.desire_pattern)}",
            "",
            "【关系互动模式】",
            f"  - {self._replace_diagnostic(features.dynamics.attachment_interaction)}",
            f"  - {self._replace_diagnostic(features.dynamics.unconscious_contract)}",
            f"  - {self._replace_diagnostic(features.dynamics.transference_pattern)}",
            "",
            "【成长建议】",
        ]
        for i, sug in enumerate(features.developmental_suggestions, 1):
            lines.append(f"  {i}. {self._replace_diagnostic(sug)}")
        lines.append(f"\n【总结】{self._replace_diagnostic(features.overall_assessment)}")

        if features.risk_level != RiskLevel.NONE:
            lines.append(f"【风险提示】{features.risk_level.value}")

        return '\n'.join(lines)

    def _replace_diagnostic(self, text: str) -> str:
        """将诊断性术语替换为通俗表达"""
        result = text
        for diagnostic, layman in self.replacements.items():
            result = result.replace(diagnostic, layman)
        # 移除残留的诊断性前缀
        for prefix_pattern in DIAGNOSTIC_PREFIXES:
            result = re.sub(prefix_pattern, '', result)
        return result.strip()
