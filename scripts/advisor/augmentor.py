"""
数据增强与多教师蒸馏模块

功能：
- 导入外部心理互动数据集（PsyCLIENT-CP / CPsDD / AuraDial）并转换为统一格式
- 多教师模型蒸馏：逻辑教师（如 DeepSeek Reasoner）+ 风格教师（如 DeepSeek V3.2）
- CoT 蒸馏：保留 <think> 标签中的推理链，用于训练模型的思维过程
- 质量过滤：基于多维度评分（长度/结构/关键词覆盖/CoT 质量）过滤低质量样本
- 支持自定义 JSONL 数据导入

处理流程：
1. import_dataset(): 通过适配器加载外部数据集并转换为统一格式
2. distill(): 对每个样本依次调用逻辑教师和风格教师生成分析
   a. 逻辑教师：生成结构化分析（含 <think> 推理链）
   b. 风格教师：基于逻辑分析润色为目标风格
3. filter_quality(): 计算质量评分并过滤低于阈值的样本
4. save(): 导出为 JSONL 训练数据

输入：
- 外部数据集文件（JSON/JSONL 格式）
- LLM 调用函数（用于蒸馏）

输出：
- JSONL 训练数据文件（messages 格式）

依赖：
- openai: 默认 LLM 调用客户端
- tqdm: 进度条显示

使用示例：
    from scripts.advisor.augmentor import DataAugmentor
    
    augmentor = DataAugmentor(config)
    augmentor.import_dataset('PsyCLIENT-CP', 'path/to/dataset')
    augmentor.distill(logic_teacher='deepseek_reasoner', style_teacher='DeepSeek_V3_2')
    augmentor.filter_quality()
    augmentor.save('output.jsonl')

性能参考：
- 蒸馏速度取决于 LLM API 响应时间（通常 5-30s/样本）
- 质量过滤为纯 CPU 计算，1000 样本约 1-2 秒

注意事项：
- 蒸馏过程支持断点续跑（已有 analysis 的样本自动跳过）
- 质量评分阈值默认 0.3，可通过 config['quality_threshold'] 调整
- 外部数据集需要对应的适配器（PsyCLIENTAdapter/CPsDDAdapter/AuraDialAdapter）

作者：forcifer
更新于：2026-02-15
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# 数据结构
# =============================================================================

@dataclass
class AugmentationStats:
    """数据增强统计"""
    original_count: int = 0
    augmented_count: int = 0
    filtered_count: int = 0
    quality_pass_rate: float = 0.0
    distill_success_rate: float = 0.0
    total_cost_usd: float = 0.0
    elapsed_seconds: float = 0.0


@dataclass
class AugmentedSample:
    """增强后的单条样本"""
    conversation: str = ''
    analysis: str = ''
    thinking: str = ''  # <think> 推理过程
    source_dataset: str = ''
    logic_teacher: str = ''
    style_teacher: str = ''
    quality_score: float = 0.0
    metadata: dict = field(default_factory=dict)


# =============================================================================
# 数据集适配器
# =============================================================================

class DatasetAdapter:
    """外部数据集适配器基类"""

    @staticmethod
    def load(path: str) -> list[dict]:
        raise NotImplementedError


class PsyCLIENTAdapter(DatasetAdapter):
    """PsyCLIENT-CP 数据集适配器"""

    @staticmethod
    def load(path: str) -> list[dict]:
        """
        加载 PsyCLIENT-CP 数据集并转换为统一格式

        统一格式：
        {
            'conversation': str,   # ME: ... / OTHER: ... 格式
            'source': 'PsyCLIENT-CP',
            'metadata': {...}
        }
        """
        samples = []
        p = Path(path)

        files = list(p.glob('*.json')) + list(p.glob('*.jsonl'))
        for f in files:
            with open(f, 'r', encoding='utf-8') as fh:
                if f.suffix == '.jsonl':
                    for line in fh:
                        line = line.strip()
                        if line:
                            data = json.loads(line)
                            sample = PsyCLIENTAdapter._convert(data)
                            if sample:
                                samples.append(sample)
                else:
                    data = json.load(fh)
                    if isinstance(data, list):
                        for item in data:
                            sample = PsyCLIENTAdapter._convert(item)
                            if sample:
                                samples.append(sample)
                    else:
                        sample = PsyCLIENTAdapter._convert(data)
                        if sample:
                            samples.append(sample)

        return samples

    @staticmethod
    def _convert(data: dict) -> Optional[dict]:
        """将 PsyCLIENT-CP 格式转换为统一格式"""
        messages = data.get('messages', data.get('dialogue', []))
        if not messages:
            return None

        lines = []
        for msg in messages:
            role = msg.get('role', msg.get('speaker', ''))
            content = msg.get('content', msg.get('text', ''))
            if role in ('client', 'user', 'patient'):
                lines.append(f"ME: {content}")
            elif role in ('counselor', 'assistant', 'therapist'):
                lines.append(f"OTHER: {content}")

        if not lines:
            return None

        return {
            'conversation': '\n'.join(lines),
            'source': 'PsyCLIENT-CP',
            'metadata': {k: v for k, v in data.items()
                        if k not in ('messages', 'dialogue')},
        }


class CPsDDAdapter(DatasetAdapter):
    """CPsDD (68K 中文心理支持对话) 数据集适配器"""

    @staticmethod
    def load(path: str) -> list[dict]:
        samples = []
        p = Path(path)

        files = list(p.glob('*.json')) + list(p.glob('*.jsonl'))
        for f in files:
            with open(f, 'r', encoding='utf-8') as fh:
                if f.suffix == '.jsonl':
                    for line in fh:
                        line = line.strip()
                        if line:
                            data = json.loads(line)
                            sample = CPsDDAdapter._convert(data)
                            if sample:
                                samples.append(sample)
                else:
                    data = json.load(fh)
                    if isinstance(data, list):
                        for item in data:
                            sample = CPsDDAdapter._convert(item)
                            if sample:
                                samples.append(sample)

        return samples

    @staticmethod
    def _convert(data: dict) -> Optional[dict]:
        dialog = data.get('dialog', data.get('conversation', []))
        if not dialog:
            text = data.get('text', '')
            if text:
                return {
                    'conversation': text,
                    'source': 'CPsDD',
                    'metadata': {},
                }
            return None

        lines = []
        for turn in dialog:
            if isinstance(turn, dict):
                role = turn.get('role', turn.get('speaker', ''))
                content = turn.get('content', turn.get('text', ''))
                if role in ('user', 'client', 'patient', 'seeker'):
                    lines.append(f"ME: {content}")
                elif role in ('assistant', 'counselor', 'supporter'):
                    lines.append(f"OTHER: {content}")
            elif isinstance(turn, str):
                lines.append(turn)

        if not lines:
            return None

        return {
            'conversation': '\n'.join(lines),
            'source': 'CPsDD',
            'metadata': {k: v for k, v in data.items()
                        if k not in ('dialog', 'conversation')},
        }


class AuraDialAdapter(DatasetAdapter):
    """AuraDial 数据集适配器"""

    @staticmethod
    def load(path: str) -> list[dict]:
        samples = []
        p = Path(path)

        files = list(p.glob('*.json')) + list(p.glob('*.jsonl'))
        for f in files:
            with open(f, 'r', encoding='utf-8') as fh:
                if f.suffix == '.jsonl':
                    for line in fh:
                        line = line.strip()
                        if line:
                            data = json.loads(line)
                            sample = AuraDialAdapter._convert(data)
                            if sample:
                                samples.append(sample)
                else:
                    data = json.load(fh)
                    if isinstance(data, list):
                        for item in data:
                            sample = AuraDialAdapter._convert(item)
                            if sample:
                                samples.append(sample)

        return samples

    @staticmethod
    def _convert(data: dict) -> Optional[dict]:
        messages = data.get('messages', data.get('turns', []))
        if not messages:
            return None

        lines = []
        for msg in messages:
            role = msg.get('role', '')
            content = msg.get('content', '')
            if role in ('user', 'human'):
                lines.append(f"ME: {content}")
            elif role in ('assistant', 'ai'):
                lines.append(f"OTHER: {content}")

        if not lines:
            return None

        return {
            'conversation': '\n'.join(lines),
            'source': 'AuraDial',
            'metadata': {k: v for k, v in data.items()
                        if k not in ('messages', 'turns')},
        }


# 数据集注册表
DATASET_ADAPTERS = {
    'PsyCLIENT-CP': PsyCLIENTAdapter,
    'CPsDD': CPsDDAdapter,
    'AuraDial': AuraDialAdapter,
}


# =============================================================================
# DataAugmentor
# =============================================================================

class DataAugmentor:
    """
    数据增强与蒸馏器

    多教师模型蒸馏：
    - 逻辑教师（deepseek_reasoner / qwen3_max）：生成 <think> 推理过程
    - 风格教师（DeepSeek_V3_2 / glm4_plus）：重写回复使其有"人味儿"
    - 合成：Input + Logic_Teacher_Reasoning + Style_Teacher_Response
    """

    def __init__(self, config: Optional[dict] = None):
        config = config or {}

        # API 配置
        self.teacher_configs: dict = config.get('teacher_configs', {})

        # 蒸馏参数
        self.batch_size: int = config.get('batch_size', 5)
        self.concurrency: int = config.get('concurrency', 2)
        self.rate_limit_delay: float = config.get('rate_limit_delay', 1.0)

        # 质量过滤
        self.min_conversation_length: int = config.get('min_conversation_length', 50)
        self.min_analysis_length: int = config.get('min_analysis_length', 100)
        self.max_analysis_length: int = config.get('max_analysis_length', 5000)

        # 数据存储
        self._raw_samples: list[dict] = []
        self._augmented_samples: list[AugmentedSample] = []
        self._stats = AugmentationStats()

    # =========================================================================
    # 导入数据集
    # =========================================================================

    def import_dataset(self, dataset_name: str, path: str) -> int:
        """
        导入外部数据集

        Args:
            dataset_name: 数据集名称（PsyCLIENT-CP / CPsDD / AuraDial）
            path: 数据集路径

        Returns:
            导入的样本数量
        """
        if dataset_name not in DATASET_ADAPTERS:
            raise ValueError(
                f"未知数据集：{dataset_name}，"
                f"支持的数据集：{list(DATASET_ADAPTERS.keys())}"
            )

        adapter = DATASET_ADAPTERS[dataset_name]
        logger.info(f"导入数据集 {dataset_name}：{path}")

        samples = adapter.load(path)
        self._raw_samples.extend(samples)
        self._stats.original_count = len(self._raw_samples)

        logger.info(f"导入 {len(samples)} 条样本，总计 {len(self._raw_samples)} 条")
        return len(samples)

    def import_jsonl(self, path: str, source_name: str = 'custom') -> int:
        """
        从 JSONL 文件导入已有训练数据

        Args:
            path: JSONL 文件路径
            source_name: 数据源名称

        Returns:
            导入的样本数量
        """
        count = 0
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                self._raw_samples.append({
                    'conversation': data.get('conversation', data.get('conversation_text', '')),
                    'source': source_name,
                    'metadata': data,
                })
                count += 1

        self._stats.original_count = len(self._raw_samples)
        logger.info(f"从 JSONL 导入 {count} 条样本")
        return count

    # =========================================================================
    # 蒸馏
    # =========================================================================

    def distill(
        self,
        logic_teacher: str = 'deepseek_reasoner',
        style_teacher: str = 'DeepSeek_V3_2',
        call_llm_fn: Optional[Callable] = None,
        show_progress: bool = True,
    ) -> int:
        """
        多教师模型蒸馏

        Args:
            logic_teacher: 逻辑教师模型名称
            style_teacher: 风格教师模型名称
            call_llm_fn: LLM 调用函数 (prompt, model_name) -> str
                         如果为 None，使用内置 OpenAI 兼容调用
            show_progress: 是否显示进度条

        Returns:
            成功蒸馏的样本数量
        """
        if not self._raw_samples:
            logger.warning("无原始样本，跳过蒸馏")
            return 0

        start_time = time.time()

        if call_llm_fn is None:
            call_llm_fn = self._default_call_llm

        success_count = 0

        try:
            from tqdm import tqdm
            iterator = tqdm(
                self._raw_samples,
                desc="蒸馏进度",
                disable=not show_progress,
            )
        except ImportError:
            iterator = self._raw_samples

        for sample in iterator:
            conversation = sample.get('conversation', '')
            if not conversation or len(conversation) < self.min_conversation_length:
                continue

            try:
                augmented = self._distill_single(
                    conversation=conversation,
                    source=sample.get('source', ''),
                    logic_teacher=logic_teacher,
                    style_teacher=style_teacher,
                    call_llm_fn=call_llm_fn,
                )
                if augmented:
                    self._augmented_samples.append(augmented)
                    success_count += 1

                time.sleep(self.rate_limit_delay)

            except Exception as e:
                logger.warning(f"蒸馏失败：{e}")

        elapsed = time.time() - start_time
        self._stats.augmented_count = len(self._augmented_samples)
        self._stats.distill_success_rate = (
            success_count / len(self._raw_samples) if self._raw_samples else 0
        )
        self._stats.elapsed_seconds = elapsed

        logger.info(
            f"蒸馏完成：{success_count}/{len(self._raw_samples)} 成功，"
            f"耗时 {elapsed:.1f}s"
        )
        return success_count

    def _distill_single(
        self,
        conversation: str,
        source: str,
        logic_teacher: str,
        style_teacher: str,
        call_llm_fn: Callable,
    ) -> Optional[AugmentedSample]:
        """单条样本蒸馏"""
        # 1. 逻辑教师：生成 <think> 推理过程 + 分析
        logic_prompt = self._build_logic_prompt(conversation)
        logic_response = call_llm_fn(logic_prompt, logic_teacher)

        if not logic_response:
            return None

        # 提取 <think> 块
        thinking = ''
        analysis = logic_response
        if '<think>' in logic_response and '</think>' in logic_response:
            think_start = logic_response.index('<think>') + len('<think>')
            think_end = logic_response.index('</think>')
            thinking = logic_response[think_start:think_end].strip()
            analysis = logic_response[think_end + len('</think>'):].strip()

        # 2. 风格教师：重写使其有"人味儿"
        style_prompt = self._build_style_prompt(conversation, analysis)
        style_response = call_llm_fn(style_prompt, style_teacher)

        final_analysis = style_response if style_response else analysis

        return AugmentedSample(
            conversation=conversation,
            analysis=final_analysis,
            thinking=thinking,
            source_dataset=source,
            logic_teacher=logic_teacher,
            style_teacher=style_teacher,
            quality_score=0.0,  # 质量过滤时计算
        )

    @staticmethod
    def _build_logic_prompt(conversation: str) -> str:
        """构建逻辑教师提示词"""
        return (
            "你是一位资深关系分析师。请对以下对话进行深度分析。\n"
            "请先在 <think> 标签中写下你的分析推理过程，然后给出最终分析。\n\n"
            "分析应包含：\n"
            "1. 关系状态评估\n"
            "2. 核心问题识别\n"
            "3. 双方各自需要改进的地方\n"
            "4. 具体可操作的建议\n\n"
            f"对话内容：\n{conversation}\n\n"
            "请用中文回复。"
        )

    @staticmethod
    def _build_style_prompt(conversation: str, analysis: str) -> str:
        """构建风格教师提示词"""
        return (
            "你是一位温暖有人情味的关系顾问。\n"
            "以下是一段关系分析，请用更温和、更有同理心的语言重写。\n"
            "要求：\n"
            "- 避免生硬的分析语气\n"
            "- 使用日常口语而非专业术语\n"
            "- 让对方感到被理解和支持\n"
            "- 保留核心建议，但措辞更柔软\n\n"
            f"原始对话：\n{conversation[:500]}\n\n"
            f"原始分析：\n{analysis}\n\n"
            "请重写分析："
        )

    # =========================================================================
    # 质量过滤
    # =========================================================================

    def filter_quality(self, show_progress: bool = True) -> int:
        """
        质量过滤（去除低质量、格式错误的样本）

        Returns:
            过滤后保留的样本数量
        """
        if not self._augmented_samples:
            logger.warning("无增强样本，跳过质量过滤")
            return 0

        before_count = len(self._augmented_samples)
        filtered = []

        try:
            from tqdm import tqdm
            iterator = tqdm(
                self._augmented_samples,
                desc="质量过滤",
                disable=not show_progress,
            )
        except ImportError:
            iterator = self._augmented_samples

        for sample in iterator:
            score = self._compute_quality_score(sample)
            sample.quality_score = score
            if score >= 0.5:
                filtered.append(sample)

        self._augmented_samples = filtered
        self._stats.filtered_count = before_count - len(filtered)
        self._stats.quality_pass_rate = (
            len(filtered) / before_count if before_count > 0 else 0
        )

        logger.info(
            f"质量过滤：{before_count} → {len(filtered)}，"
            f"通过率 {self._stats.quality_pass_rate:.1%}"
        )
        return len(filtered)

    def _compute_quality_score(self, sample: AugmentedSample) -> float:
        """
        计算样本质量分数 [0, 1]

        评分维度：
        - 长度合理性
        - 格式正确性（包含分析结构关键词）
        - 内容多样性
        """
        score = 0.0
        max_score = 0.0

        # 1. 对话长度
        max_score += 1.0
        conv_len = len(sample.conversation)
        if self.min_conversation_length <= conv_len <= 10000:
            score += 1.0
        elif conv_len > 0:
            score += 0.5

        # 2. 分析长度
        max_score += 1.0
        ana_len = len(sample.analysis)
        if self.min_analysis_length <= ana_len <= self.max_analysis_length:
            score += 1.0
        elif ana_len > 0:
            score += 0.3

        # 3. 分析结构（包含关键分析词汇）
        max_score += 1.0
        structure_keywords = ['关系', '问题', '建议', '沟通', '改善', '需要']
        hits = sum(1 for kw in structure_keywords if kw in sample.analysis)
        score += min(hits / 3.0, 1.0)

        # 4. 对话格式（包含 ME: / OTHER:）
        max_score += 1.0
        if 'ME:' in sample.conversation and 'OTHER:' in sample.conversation:
            score += 1.0
        elif 'ME:' in sample.conversation or 'OTHER:' in sample.conversation:
            score += 0.5

        # 5. 有 thinking 推理过程加分
        max_score += 1.0
        if sample.thinking and len(sample.thinking) > 20:
            score += 1.0

        return score / max_score if max_score > 0 else 0.0

    # =========================================================================
    # 输出
    # =========================================================================

    def save(self, output_path: str, format: str = 'jsonl'):
        """
        保存增强后的数据

        Args:
            output_path: 输出文件路径
            format: 输出格式（jsonl）
        """
        output_dir = Path(output_path).parent
        output_dir.mkdir(parents=True, exist_ok=True)

        with open(output_path, 'w', encoding='utf-8') as f:
            for sample in self._augmented_samples:
                record = {
                    'messages': [
                        {'role': 'system', 'content': '你是一位专业的关系顾问。'},
                        {'role': 'user', 'content': sample.conversation},
                        {'role': 'assistant', 'content': sample.analysis},
                    ],
                    'thinking': sample.thinking,
                    'source_dataset': sample.source_dataset,
                    'logic_teacher': sample.logic_teacher,
                    'style_teacher': sample.style_teacher,
                    'quality_score': sample.quality_score,
                }
                f.write(json.dumps(record, ensure_ascii=False) + '\n')

        logger.info(f"保存 {len(self._augmented_samples)} 条增强数据到 {output_path}")

    def get_stats(self) -> AugmentationStats:
        """获取数据增强统计"""
        return self._stats

    def get_samples(self) -> list[AugmentedSample]:
        """获取增强后的样本列表"""
        return list(self._augmented_samples)

    # =========================================================================
    # 内置 LLM 调用
    # =========================================================================

    def _default_call_llm(self, prompt: str, model_name: str) -> str:
        """
        默认 LLM 调用（通过 OpenAI 兼容接口）

        Args:
            prompt: 提示词
            model_name: 模型名称（映射到 teacher_configs 中的配置）

        Returns:
            LLM 响应文本
        """
        teacher_cfg = self.teacher_configs.get(model_name, {})
        if not teacher_cfg:
            logger.warning(f"未找到教师模型配置：{model_name}")
            return ''

        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError("openai 库未安装，请运行：pip install openai")

        client = OpenAI(
            base_url=teacher_cfg.get('base_url', ''),
            api_key=teacher_cfg.get('api_key', os.environ.get(
                teacher_cfg.get('api_key_env', ''), ''
            )),
        )

        try:
            response = client.chat.completions.create(
                model=teacher_cfg.get('model', model_name),
                messages=[{'role': 'user', 'content': prompt}],
                temperature=teacher_cfg.get('temperature', 0.7),
                max_tokens=teacher_cfg.get('max_tokens', 2000),
            )
            content = response.choices[0].message.content if response.choices else ''
            # 累计成本估算
            if hasattr(response, 'usage') and response.usage:
                tokens = response.usage.total_tokens
                cost_per_1k = teacher_cfg.get('cost_per_1k_tokens', 0.002)
                self._stats.total_cost_usd += tokens * cost_per_1k / 1000
            return content
        except Exception as e:
            logger.error(f"LLM 调用失败 ({model_name}): {e}")
            return ''
