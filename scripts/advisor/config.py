"""
配置加载和验证模块

功能：
- 从 YAML 配置文件加载 Advisor 全部配置参数
- 支持 ${variable} 变量替换（环境变量优先，其次配置内变量）
- 提供 9 个 dataclass 子配置（提取/分析/路由/安全/云端/记忆/训练/推理/主配置）
- 支持命令行参数覆盖（merge_cli_args）
- 配置验证（validate_config）检查路径存在性和参数合法性

处理流程：
1. 读取 configs/advisor.yaml（不存在则使用默认值）
2. 从 configs/paths.yaml 获取 workspace 路径
3. 构建变量字典（workspace, root）
4. 递归解析所有 ${var} 变量引用
5. 按子配置分组构建 AdvisorConfig dataclass 对象
6. 可选：合并命令行参数覆盖

输入：
- configs/advisor.yaml: 主配置文件（YAML 格式）
- configs/paths.yaml: 路径配置（提供 workspace 变量）
- 环境变量: 用于 ${VAR} 变量替换

输出：
- AdvisorConfig 对象: 包含所有子配置的完整配置树

依赖：
- PyYAML: YAML 文件解析
- dataclasses: 配置数据结构定义

使用示例：
    # 基本用法
    from scripts.advisor.config import load_config, AdvisorConfig
    
    config = load_config()
    print(config.training.base_model)
    print(config.analysis.default_backend)
    
    # 指定配置文件和工作空间
    config = load_config('configs/advisor.yaml', workspace='/path/to/project')
    
    # 验证配置
    from scripts.advisor.config import validate_config
    errors = validate_config(config)
    if errors:
        print("配置错误:", errors)
    
    # 合并命令行参数
    from scripts.advisor.config import merge_cli_args
    config = merge_cli_args(config, args)

注意事项：
- 配置文件不存在时不会报错，而是使用全部默认值并打印警告
- ${variable} 变量替换支持嵌套在字符串、列表、字典中
- 环境变量优先级高于配置文件中定义的变量
- validate_config 会检查基座模型路径和工作空间是否存在
- 训练参数（batch_size, learning_rate, num_epochs）有合法性校验
- 推理参数（temperature 0-2, top_p 0-1）有范围校验

作者：forcifer
更新于：2026-02-15
"""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml


@dataclass
class ExtractionConfig:
    """对话提取配置
    
    控制 ConversationExtractor 的滑动窗口参数和消息过滤规则。
    
    Attributes:
        window_size: 滑动窗口大小（每个 chunk 包含的消息数），默认 20
        step_size: 滑动步长（窗口每次移动的消息数），默认 10
        min_messages: 最小消息数阈值（低于此值的窗口被丢弃），默认 10
        exclude_system: 是否排除系统消息（保留 time_gap 类型），默认 True
        exclude_types: 需要排除的消息类型列表（如 ['contact', 'miniprogram']）
        num_chunks: 最终提取的 chunk 数量（按评分排序取 top N），默认 100
    
    Example:
        >>> config = ExtractionConfig(window_size=30, step_size=15, num_chunks=200)
    """
    window_size: int = 20
    step_size: int = 10
    min_messages: int = 10
    exclude_system: bool = True
    exclude_types: list[str] = field(default_factory=list)
    num_chunks: int = 100


@dataclass
class AnalysisConfig:
    """LLM 分析配置
    
    控制 AnalysisGenerator 的 API 调用参数和各后端配置。
    
    Attributes:
        default_backend: 默认 LLM 后端（openai/DeepSeek/Kimi/kimi/Qwen/deepseek 等），默认 'openai'
        rate_limit_delay: API 调用间隔（秒），防止触发限流，默认 1.0
        max_retries: API 调用最大重试次数，默认 3
        retry_delay: 重试间隔（秒），支持指数退避，默认 5.0
        openai: OpenAI 后端配置字典（model, api_key, base_url, temperature 等）
        DeepSeek: Anthropic DeepSeek 后端配置字典
        Kimi: Google Kimi 后端配置字典
        qwen_local: 本地 Qwen 模型配置字典（通过 Ollama 或 vLLM 提供）
        kimi: Moonshot Kimi 后端配置字典
        Qwen: Qwen 后端配置字典
        deepseek: DeepSeek 后端配置字典
    
    Example:
        >>> config = AnalysisConfig(default_backend='DeepSeek', rate_limit_delay=2.0)
    """
    default_backend: str = 'openai'
    rate_limit_delay: float = 1.0
    max_retries: int = 3
    retry_delay: float = 5.0
    
    # 各后端配置
    openai: dict = field(default_factory=dict)
    DeepSeek: dict = field(default_factory=dict)
    Kimi: dict = field(default_factory=dict)
    qwen_local: dict = field(default_factory=dict)
    kimi: dict = field(default_factory=dict)
    Qwen: dict = field(default_factory=dict)
    deepseek: dict = field(default_factory=dict)


@dataclass
class RoutingConfig:
    """模型路由配置
    
    控制 ModelRouter 的复杂度评估阈值、预算限制和后端选择策略。
    
    Attributes:
        complexity_thresholds: 复杂度阈值字典，决定路由到哪个模型层级
            - simple (< 0.3): 简单查询，路由到本地模型
            - medium (< 0.6): 中等复杂度，路由到经济型云端模型
            - 其余: 高复杂度，路由到旗舰云端模型
        budget_limit_daily: 每日 API 预算上限（美元），默认 5.0
        fallback_model: 所有云端模型不可用时的兜底模型，默认 'local_qwen3'
        long_context_threshold: 长上下文阈值（token 数），超过此值路由到支持长上下文的模型，默认 32000
        backends: 各后端的详细配置字典（模型名、API 密钥、优先级等）
    
    Example:
        >>> config = RoutingConfig(budget_limit_daily=10.0, fallback_model='local_qwen3')
    """
    complexity_thresholds: dict = field(default_factory=lambda: {
        'simple': 0.3, 'medium': 0.6,
    })
    budget_limit_daily: float = 5.0
    fallback_model: str = 'local_qwen3'
    long_context_threshold: int = 32000
    backends: dict = field(default_factory=dict)


@dataclass
class SafetyConfig:
    """安全隔离配置
    
    控制 SafetyLayer 的诊断术语替换、风险检测和审计日志。
    
    Attributes:
        audit_log_dir: 审计日志输出目录，记录云端原始推理过程，默认 'data/advisor/audit_logs'
        enable_risk_detection: 是否启用风险检测（高风险内容触发安全干预），默认 True
        diagnostic_replacements: 诊断术语→通俗表达的替换映射字典
            例如 {'依附障碍': '依附倾向', '人格障碍': '性格特点'}
        sensitive_keywords: 敏感关键词列表，触发额外审查
    
    Example:
        >>> config = SafetyConfig(enable_risk_detection=True)
    """
    audit_log_dir: str = 'data/advisor/audit_logs'
    enable_risk_detection: bool = True
    diagnostic_replacements: dict = field(default_factory=dict)
    sensitive_keywords: list[str] = field(default_factory=list)


@dataclass
class CloudAnalysisConfig:
    """云端分析配置
    
    控制 SchemaValidator 的 JSON Schema 自修复循环参数。
    
    Attributes:
        max_repair_attempts: Schema 校验失败时的最大 LLM 自修复尝试次数，默认 2
        fallback_enabled: 修复失败后是否启用 fallback LLM（如 DeepSeek Reasoner），默认 True
    
    Example:
        >>> config = CloudAnalysisConfig(max_repair_attempts=3)
    """
    max_repair_attempts: int = 2
    fallback_enabled: bool = True


@dataclass
class MemoryConfig:
    """记忆/GraphRAG 配置
    
    控制 GraphRAGManager 的嵌入模型、向量索引和检索参数。
    
    Attributes:
        embedding_model: 嵌入模型名称（HuggingFace 格式），默认 'BAAI/bge-m3'
        reranker_model: 重排序模型名称，默认 'BAAI/bge-reranker-v2-m3'
        index_dir: FAISS 向量索引存储目录，默认 'data/advisor/faiss_index'
        top_k_retrieval: 初始检索返回的候选数量，默认 20
        top_k_rerank: 重排序后保留的最终结果数量，默认 5
        use_gpu_for_embedding: 是否使用 GPU 加速嵌入计算，默认 True
    
    Example:
        >>> config = MemoryConfig(top_k_retrieval=30, top_k_rerank=10)
    """
    embedding_model: str = 'BAAI/bge-m3'
    reranker_model: str = 'BAAI/bge-reranker-v2-m3'
    index_dir: str = 'data/advisor/faiss_index'
    top_k_retrieval: int = 20
    top_k_rerank: int = 5
    use_gpu_for_embedding: bool = True


@dataclass
class TrainingConfig:
    """训练配置
    
    控制 AdvisorTrainer 的 QLoRA 微调参数。
    
    Attributes:
        base_model: 基座模型路径（本地路径或 HuggingFace 模型 ID），默认 '/path/to/models/Qwen3-8B-Instruct'
        lora_r: LoRA 秩（rank），控制低秩矩阵的维度，默认 32
        lora_alpha: LoRA 缩放因子（alpha/r 为实际缩放比），默认 64
        lora_dropout: LoRA 层的 Dropout 比率，默认 0.05
        target_modules: LoRA 应用的目标模块列表，默认 ['q_proj', 'k_proj', 'v_proj']
        learning_rate: 学习率，默认 1e-4
        num_epochs: 训练轮数，默认 5
        batch_size: 每个设备的批次大小，默认 1（受显存限制）
        gradient_accumulation_steps: 梯度累积步数（等效批次 = batch_size × 此值），默认 16
        max_seq_length: 最大序列长度（token 数），默认 2048
        warmup_ratio: 学习率预热比例，默认 0.03
        use_4bit: 是否使用 4-bit 量化（QLoRA），默认 True
        use_gradient_checkpointing: 是否使用梯度检查点（节省显存），默认 True
        optimizer: 优化器类型，默认 'paged_adamw_32bit'
        save_steps: 每隔多少步保存一次检查点，默认 100
        save_total_limit: 最多保留的检查点数量，默认 3
        logging_steps: 每隔多少步记录一次日志，默认 10
    
    Example:
        >>> config = TrainingConfig(num_epochs=3, learning_rate=5e-5)
    """
    base_model: str = '/path/to/models/Qwen3-8B-Instruct'
    lora_r: int = 32
    lora_alpha: int = 64
    lora_dropout: float = 0.05
    target_modules: list[str] = field(default_factory=lambda: [
        'q_proj', 'k_proj', 'v_proj',
    ])
    learning_rate: float = 1e-4
    num_epochs: int = 5
    batch_size: int = 1
    gradient_accumulation_steps: int = 16
    max_seq_length: int = 2048
    warmup_ratio: float = 0.03
    use_4bit: bool = True
    use_gradient_checkpointing: bool = True
    optimizer: str = 'paged_adamw_32bit'
    save_steps: int = 100
    save_total_limit: int = 3
    logging_steps: int = 10


@dataclass
class InferenceConfig:
    """推理配置
    
    控制 AdvisorInference 的本地模型推理参数。
    
    Attributes:
        quantization: 量化方式（'4bit' / '8bit' / 'none'），默认 '4bit'
        temperature: 生成温度（0=确定性，2=最大随机性），默认 0.7
        top_p: 核采样概率阈值（0-1），默认 0.9
        top_k: Top-K 采样的 K 值，默认 50
        max_new_tokens: 最大生成 token 数，默认 1024
        do_sample: 是否启用采样（False 则使用贪心解码），默认 True
        auto_unload: 推理完成后是否自动卸载模型释放显存，默认 True
    
    Example:
        >>> config = InferenceConfig(temperature=0.5, max_new_tokens=2048)
    """
    quantization: str = '4bit'
    temperature: float = 0.7
    top_p: float = 0.9
    top_k: int = 50
    max_new_tokens: int = 1024
    do_sample: bool = True
    auto_unload: bool = True


@dataclass
class AdvisorConfig:
    """完整配置
    
    Advisor 系统的顶层配置对象，包含所有子配置和全局参数。
    通过 load_config() 函数从 YAML 文件构建。
    
    Attributes:
        workspace: 工作空间根目录路径
        timeline_file: Timeline 数据文件路径（enriched_full.jsonl）
        sft_l1_file: L1 级 SFT 数据文件路径（基础对话数据）
        sft_l2_file: L2 级 SFT 数据文件路径（含多模态标注的增强数据）
        output_dir: 输出目录路径（分析结果、训练数据、模型检查点等）
        extraction: 对话提取子配置（ExtractionConfig）
        analysis: LLM 分析子配置（AnalysisConfig）
        training: 训练子配置（TrainingConfig）
        inference: 推理子配置（InferenceConfig）
        routing: 模型路由子配置（RoutingConfig）
        safety: 安全隔离子配置（SafetyConfig）
        cloud_analysis: 云端分析子配置（CloudAnalysisConfig）
        memory: 记忆/GraphRAG 子配置（MemoryConfig）
        review_samples_per_file: 每个人工审核文件包含的样本数，默认 15
        log_level: 日志级别（DEBUG/INFO/WARNING/ERROR），默认 'INFO'
        log_file: 日志文件路径
    
    Example:
        >>> config = load_config('configs/advisor.yaml')
        >>> print(config.workspace)
        >>> print(config.training.base_model)
    """
    # 路径
    workspace: str = ''
    timeline_file: str = ''
    sft_l1_file: str = ''
    sft_l2_file: str = ''
    output_dir: str = ''
    
    # 子配置
    extraction: ExtractionConfig = field(default_factory=ExtractionConfig)
    analysis: AnalysisConfig = field(default_factory=AnalysisConfig)
    training: TrainingConfig = field(default_factory=TrainingConfig)
    inference: InferenceConfig = field(default_factory=InferenceConfig)
    routing: RoutingConfig = field(default_factory=RoutingConfig)
    safety: SafetyConfig = field(default_factory=SafetyConfig)
    cloud_analysis: CloudAnalysisConfig = field(default_factory=CloudAnalysisConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    
    # 审核配置
    review_samples_per_file: int = 15
    
    # 日志配置
    log_level: str = 'INFO'
    log_file: str = ''


def _resolve_variables(value: Any, variables: dict) -> Any:
    """递归解析配置值中的 ${variable} 变量引用
    
    支持在字符串、字典、列表中嵌套使用变量。
    变量查找优先级：环境变量 > variables 字典。
    未找到的变量保持原样不替换。
    
    Args:
        value (Any): 待解析的配置值（str/dict/list/其他类型）
        variables (dict): 变量字典，键为变量名，值为替换内容
    
    Returns:
        Any: 解析后的配置值，类型与输入一致
    
    Example:
        >>> _resolve_variables('${workspace}/output', {'workspace': '/path'})
        '/path/output'
    """
    if isinstance(value, str):
        # 替换 ${var} 格式的变量
        pattern = r'\$\{(\w+)\}'
        
        def replace(match):
            var_name = match.group(1)
            # 先从环境变量查找
            env_val = os.environ.get(var_name)
            if env_val:
                return env_val
            # 再从变量字典查找
            return variables.get(var_name, match.group(0))
        
        return re.sub(pattern, replace, value)
    elif isinstance(value, dict):
        return {k: _resolve_variables(v, variables) for k, v in value.items()}
    elif isinstance(value, list):
        return [_resolve_variables(v, variables) for v in value]
    return value


def load_config(
    config_path: Optional[str] = None,
    workspace: Optional[str] = None,
) -> AdvisorConfig:
    """
    加载并构建完整的 Advisor 配置对象
    
    从 YAML 配置文件读取原始配置，解析变量引用，
    按子配置分组构建 AdvisorConfig dataclass 对象。
    
    Args:
        config_path (str, optional): 配置文件路径，默认 'configs/advisor.yaml'
        workspace (str, optional): 工作空间路径，覆盖配置文件和 paths.yaml 中的值
    
    Returns:
        AdvisorConfig: 包含所有子配置的完整配置对象
    
    Example:
        >>> config = load_config()
        >>> config = load_config('configs/advisor.yaml', workspace='/path/to/project')
    """
    # 默认配置文件路径
    if config_path is None:
        config_path = 'configs/advisor.yaml'
    
    config_path = Path(config_path)
    
    # 加载 YAML
    if config_path.exists():
        with open(config_path, 'r', encoding='utf-8') as f:
            raw_config = yaml.safe_load(f) or {}
    else:
        print(f"警告：配置文件不存在: {config_path}，使用默认配置")
        raw_config = {}
    
    # 确定工作空间
    if workspace is None:
        # 尝试从 paths.yaml 加载
        paths_config = Path('configs/paths.yaml')
        if paths_config.exists():
            with open(paths_config, 'r', encoding='utf-8') as f:
                paths = yaml.safe_load(f) or {}
                workspace = paths.get('workspace', '.')
        else:
            workspace = '.'
    
    # 变量字典
    variables = {
        'workspace': workspace,
        'root': workspace,
    }
    
    # 解析变量
    raw_config = _resolve_variables(raw_config, variables)
    
    # 构建配置对象
    config = AdvisorConfig()
    
    # 路径配置
    paths = raw_config.get('paths', {})
    config.workspace = workspace
    config.timeline_file = paths.get('timeline_file', f'{workspace}/timeline_out/enriched_full.jsonl')
    config.sft_l1_file = paths.get('sft_l1_file', f'{workspace}/timeline_out/agent_sft_l1.jsonl')
    config.sft_l2_file = paths.get('sft_l2_file', f'{workspace}/timeline_out/agent_sft_l2.jsonl')
    config.output_dir = paths.get('output_dir', f'{workspace}/advisor_out')
    
    # 提取配置
    extraction = raw_config.get('extraction', {})
    config.extraction = ExtractionConfig(
        window_size=extraction.get('window_size', 20),
        step_size=extraction.get('step_size', 10),
        min_messages=extraction.get('min_messages', 10),
        exclude_system=extraction.get('exclude_system', True),
        exclude_types=extraction.get('exclude_types', []),
        num_chunks=extraction.get('num_chunks', 100),
    )
    
    # 分析配置
    analysis = raw_config.get('analysis', {})
    config.analysis = AnalysisConfig(
        default_backend=analysis.get('default_backend', 'openai'),
        rate_limit_delay=analysis.get('rate_limit_delay', 1.0),
        max_retries=analysis.get('max_retries', 3),
        retry_delay=analysis.get('retry_delay', 5.0),
        openai=analysis.get('openai', {}),
        DeepSeek=analysis.get('DeepSeek', {}),
        Kimi=analysis.get('Kimi', {}),
        qwen_local=analysis.get('qwen_local', {}),
        kimi=analysis.get('kimi', {}),
        Qwen=analysis.get('Qwen', {}),
        deepseek=analysis.get('deepseek', {}),
    )
    
    # 训练配置
    training = raw_config.get('training', {})
    lora = training.get('lora', {})
    quant = training.get('quantization', {})
    
    config.training = TrainingConfig(
        base_model=training.get('base_model', '/path/to/models/Qwen3-8B-Instruct'),
        lora_r=lora.get('r', 32),
        lora_alpha=lora.get('alpha', 64),
        lora_dropout=lora.get('dropout', 0.05),
        target_modules=lora.get('target_modules', [
            'q_proj', 'k_proj', 'v_proj',
        ]),
        learning_rate=training.get('learning_rate', 1e-4),
        num_epochs=training.get('num_epochs', 5),
        batch_size=training.get('batch_size', 1),
        gradient_accumulation_steps=training.get('gradient_accumulation_steps', 16),
        max_seq_length=training.get('max_seq_length', 2048),
        warmup_ratio=training.get('warmup_ratio', 0.03),
        use_4bit=quant.get('load_in_4bit', True),
        use_gradient_checkpointing=training.get('use_gradient_checkpointing', True),
        optimizer=training.get('optimizer', 'paged_adamw_32bit'),
        save_steps=training.get('save_steps', 100),
        save_total_limit=training.get('save_total_limit', 3),
        logging_steps=training.get('logging_steps', 10),
    )
    
    # 推理配置
    inference = raw_config.get('inference', {})
    config.inference = InferenceConfig(
        quantization=inference.get('quantization', '4bit'),
        temperature=inference.get('temperature', 0.7),
        top_p=inference.get('top_p', 0.9),
        top_k=inference.get('top_k', 50),
        max_new_tokens=inference.get('max_new_tokens', 1024),
        do_sample=inference.get('do_sample', True),
        auto_unload=inference.get('auto_unload', True),
    )
    
    # 路由配置
    routing = raw_config.get('routing', {})
    config.routing = RoutingConfig(
        complexity_thresholds=routing.get('complexity_thresholds', {
            'simple': 0.3, 'medium': 0.6,
        }),
        budget_limit_daily=routing.get('budget_limit_daily', 5.0),
        fallback_model=routing.get('fallback_model', 'local_qwen3'),
        long_context_threshold=routing.get('long_context_threshold', 32000),
        backends=routing.get('backends', {}),
    )
    
    # 安全隔离配置
    safety = raw_config.get('safety', {})
    config.safety = SafetyConfig(
        audit_log_dir=safety.get('audit_log_dir', f'{workspace}/advisor_out/audit_logs'),
        enable_risk_detection=safety.get('enable_risk_detection', True),
        diagnostic_replacements=safety.get('diagnostic_replacements', {}),
        sensitive_keywords=safety.get('sensitive_keywords', []),
    )
    
    # 云端分析配置
    cloud = raw_config.get('cloud_analysis', {})
    config.cloud_analysis = CloudAnalysisConfig(
        max_repair_attempts=cloud.get('max_repair_attempts', 2),
        fallback_enabled=cloud.get('fallback_enabled', True),
    )
    
    # 记忆/GraphRAG 配置
    memory = raw_config.get('memory', {})
    config.memory = MemoryConfig(
        embedding_model=memory.get('embedding_model', 'BAAI/bge-m3'),
        reranker_model=memory.get('reranker_model', 'BAAI/bge-reranker-v2-m3'),
        index_dir=memory.get('index_dir', f'{workspace}/advisor_out/faiss_index'),
        top_k_retrieval=memory.get('top_k_retrieval', 20),
        top_k_rerank=memory.get('top_k_rerank', 5),
        use_gpu_for_embedding=memory.get('use_gpu_for_embedding', True),
    )
    
    # 审核配置
    review = raw_config.get('review', {})
    config.review_samples_per_file = review.get('samples_per_file', 15)
    
    # 日志配置
    logging_config = raw_config.get('logging', {})
    config.log_level = logging_config.get('level', 'INFO')
    config.log_file = logging_config.get('file', f'{workspace}/logs/advisor.log')
    
    return config


def validate_config(config: AdvisorConfig) -> list[str]:
    """
    验证配置对象的合法性
    
    检查项目：
    - 基座模型路径是否存在
    - 工作空间路径是否存在
    - 训练参数合法性（batch_size > 0, learning_rate > 0, num_epochs > 0）
    - 推理参数范围（temperature 0-2, top_p 0-1）
    
    Args:
        config (AdvisorConfig): 待验证的配置对象
    
    Returns:
        list[str]: 错误消息列表，空列表表示验证通过
    
    Example:
        >>> errors = validate_config(config)
        >>> if errors:
        ...     for e in errors:
        ...         print(f"配置错误: {e}")
    """
    errors = []
    
    # 检查基座模型
    if not Path(config.training.base_model).exists():
        errors.append(f"基座模型不存在: {config.training.base_model}")
    
    # 检查工作空间
    if not Path(config.workspace).exists():
        errors.append(f"工作空间不存在: {config.workspace}")
    
    # 检查训练参数
    if config.training.batch_size < 1:
        errors.append("batch_size 必须大于 0")
    
    if config.training.learning_rate <= 0:
        errors.append("learning_rate 必须大于 0")
    
    if config.training.num_epochs < 1:
        errors.append("num_epochs 必须大于 0")
    
    # 检查推理参数
    if config.inference.temperature < 0 or config.inference.temperature > 2:
        errors.append("temperature 应该在 0-2 之间")
    
    if config.inference.top_p < 0 or config.inference.top_p > 1:
        errors.append("top_p 应该在 0-1 之间")
    
    return errors


def merge_cli_args(config: AdvisorConfig, args) -> AdvisorConfig:
    """
    合并命令行参数到配置对象
    
    将 argparse 解析的命令行参数覆盖到对应的配置字段。
    仅覆盖非 None 的参数，未指定的参数保持配置文件中的值。
    
    支持的命令行参数：
    - 训练相关: --epochs, --batch_size, --learning_rate, --base_model
    - 推理相关: --temperature, --top_p, --max_tokens
    
    Args:
        config (AdvisorConfig): 配置对象
        args: argparse.Namespace 对象，包含命令行参数
    
    Returns:
        AdvisorConfig: 更新后的配置对象（原地修改并返回）
    
    Example:
        >>> import argparse
        >>> args = argparse.Namespace(epochs=3, batch_size=2, learning_rate=None)
        >>> config = merge_cli_args(config, args)
    """
    # 训练相关参数
    if hasattr(args, 'epochs') and args.epochs is not None:
        config.training.num_epochs = args.epochs
    
    if hasattr(args, 'batch_size') and args.batch_size is not None:
        config.training.batch_size = args.batch_size
    
    if hasattr(args, 'learning_rate') and args.learning_rate is not None:
        config.training.learning_rate = args.learning_rate
    
    if hasattr(args, 'base_model') and args.base_model is not None:
        config.training.base_model = args.base_model
    
    # 推理相关参数
    if hasattr(args, 'temperature') and args.temperature is not None:
        config.inference.temperature = args.temperature
    
    if hasattr(args, 'top_p') and args.top_p is not None:
        config.inference.top_p = args.top_p
    
    if hasattr(args, 'max_tokens') and args.max_tokens is not None:
        config.inference.max_new_tokens = args.max_tokens
    
    return config
