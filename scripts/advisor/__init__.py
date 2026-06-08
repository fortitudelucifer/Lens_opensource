"""
关系顾问 Agent 包

功能：
- 提供三种关系顾问 Agent 的统一入口：
  1. 中立顾问 (neutral) — 客观分析，平衡批评，基于 Gottman 四骑士理论
  2. 支持性顾问 (supportive) — 情感验证，用户视角，优先共情
  3. 精神分析顾问 (psychoanalytic) — 依附风格，防御机制，拉康派分析
- 采用延迟导入（__getattr__）避免循环依赖和启动时间过长
- 统一暴露所有核心类、Schema 模型、分析器和配置工具

架构：
- 云端大脑 + 本地嘴巴 | 单 GPU (RTX 5070 Ti 16GB) 串行执行
- 核心流程：
  Timeline → ConversationExtractor 对话提取
  → ModelRouter 路由到合适的云端 LLM
  → AnalysisGenerator 云端分析
  → SchemaValidator JSON Schema 校验与自修复
  → SafetyLayer 诊断术语隔离
  → AdvisorInference 本地 LoRA 模型生成
  → GraphRAGManager 记忆存储与检索

模块组成：
- extractor.py: 对话片段提取（滑动窗口 + 多模态评分）
- generator.py: LLM API 调用与分析生成（支持 8+ 后端）
- formatter.py: 训练数据格式化与人工审核
- schemas.py: Pydantic 结构化输出 Schema（Cloud→Local 数据通道）
- analyzers.py: 响应时间/冲突根源/长期上下文/中立性/精神分析 5 大分析器
- model_router.py: 云端+本地混合路由（复杂度评估 + 预算控制）
- schema_validator.py: Pydantic 校验 + 2 轮 LLM 自修复循环
- safety_layer.py: 诊断术语替换 + 风险检测 + 审计日志
- inference.py: QLoRA 本地模型加载与推理
- trainer.py: QLoRA 微调训练
- streaming.py: 实时对话引擎（listen/consult 双模式）
- augmentor.py: 多教师蒸馏数据增强
- graph_rag.py: BGE-M3 + FAISS + BGE-Reranker 向量检索
- graph_rag_enhanced.py: 增强版 GraphRAG（日期查询 + L1/L2 分离）
- intent_classifier.py: 5 类意图分类（关键词匹配）
- key_rotator.py: API 密钥轮换与全局限流
- query_rewriter.py: 上下文感知查询改写
- pipeline_executor.py: 4 阶段异步流水线（Rich 可视化）
- chunk_based_rag.py: 多维度 chunk 检索
- config.py: YAML 配置加载与验证
- errors.py: 统一异常体系 + 显存管理 + API 重试

依赖：
- torch: GPU 显存管理
- pydantic: Schema 定义与校验
- openai / anthropic: LLM API 客户端
- sentence-transformers: BGE-M3 嵌入模型
- faiss-gpu: 向量索引
- peft / transformers: QLoRA 微调与推理
- PyYAML: 配置文件解析

使用示例：
    # 基本用法：导入核心类
    from scripts.advisor import ConversationExtractor, AnalysisGenerator
    from scripts.advisor import ModelRouter, SchemaValidator, SafetyLayer
    
    # 导入 Schema 模型
    from scripts.advisor import AnalysisFeatures, CloudAnalysisResponse
    
    # 导入配置
    from scripts.advisor import load_config, AdvisorConfig

注意事项：
- 所有导入均为延迟导入，首次访问某个类时才会加载对应模块
- GPU 密集型模块（inference, trainer, graph_rag）建议按需导入，避免不必要的显存占用
- 配置文件路径默认为 configs/advisor.yaml，可通过 load_config() 参数覆盖

作者：[Author]
更新于：2026-02-15
"""

# 延迟导入，避免循环依赖
__all__ = [
    # 核心类
    'ConversationExtractor',
    'AnalysisGenerator', 
    'TrainingFormatter',
    'AdvisorTrainer',
    'AdvisorInference',
    # 新增：路由/校验/安全
    'ModelRouter',
    'LocalModelSession',
    'SchemaValidator',
    'SafetyLayer',
    # 新增：GraphRAG
    'GraphRAGManager',
    # 新增：实时对话
    'StreamingDialogueEngine',
    # 新增：数据增强
    'DataAugmentor',
    # 新增：Schema 模型
    'AnalysisFeatures',
    'SupportiveFeatures',
    'PsychoanalyticFeatures',
    'CloudAnalysisResponse',
    # 分析器
    'ResponseTimeAnalyzer',
    'ConflictRootCauseAnalyzer',
    'LongTermContextAnalyzer',
    'NeutralityChecker',
    'PsychoanalyticDetector',
    # 配置和错误处理
    'load_config',
    'AdvisorConfig',
    'AdvisorError',
    'setup_logging',
]

def __getattr__(name):
    if name == 'ConversationExtractor':
        from .extractor import ConversationExtractor
        return ConversationExtractor
    elif name == 'AnalysisGenerator':
        from .generator import AnalysisGenerator
        return AnalysisGenerator
    elif name == 'TrainingFormatter':
        from .formatter import TrainingFormatter
        return TrainingFormatter
    elif name == 'AdvisorTrainer':
        from .trainer import AdvisorTrainer
        return AdvisorTrainer
    elif name == 'AdvisorInference':
        from .inference import AdvisorInference
        return AdvisorInference
    elif name in ('ResponseTimeAnalyzer', 'ConflictRootCauseAnalyzer', 
                  'LongTermContextAnalyzer', 'NeutralityChecker', 'PsychoanalyticDetector'):
        from . import analyzers
        return getattr(analyzers, name)
    elif name == 'GraphRAGManager':
        from .graph_rag import GraphRAGManager
        return GraphRAGManager
    elif name == 'StreamingDialogueEngine':
        from .streaming import StreamingDialogueEngine
        return StreamingDialogueEngine
    elif name == 'DataAugmentor':
        from .augmentor import DataAugmentor
        return DataAugmentor
    elif name in ('ModelRouter', 'LocalModelSession'):
        from .model_router import ModelRouter, LocalModelSession
        return {'ModelRouter': ModelRouter, 'LocalModelSession': LocalModelSession}[name]
    elif name == 'SchemaValidator':
        from .schema_validator import SchemaValidator
        return SchemaValidator
    elif name == 'SafetyLayer':
        from .safety_layer import SafetyLayer
        return SafetyLayer
    elif name in ('AnalysisFeatures', 'SupportiveFeatures', 'PsychoanalyticFeatures', 'CloudAnalysisResponse'):
        from . import schemas
        return getattr(schemas, name)
    elif name in ('load_config', 'AdvisorConfig'):
        from . import config
        return getattr(config, name)
    elif name in ('AdvisorError', 'setup_logging'):
        from . import errors
        return getattr(errors, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
