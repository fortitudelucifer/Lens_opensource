"""
对话片段提取器模块

功能：
- 从 SFT 数据（agent_sft_l1.jsonl / agent_sft_l2.jsonl）中提取有代表性的对话片段
- 使用滑动窗口算法切分长对话为固定大小的 chunk
- 多维度评分系统：情绪词汇密度、对话平衡度、消息多样性、多模态丰富度
- 支持多模态信号提取：语音情绪标签、图片氛围、表情包意图、视频描述
- 计算每个 chunk 的多模态信号密度（mm_density）
- 按评分排序选取 top N 最具代表性的片段

处理流程：
1. 从 JSONL 文件加载所有消息记录
2. 过滤系统消息和指定排除类型
3. 滑动窗口切分（window_size=20, step_size=10）
4. 对每个窗口计算多维评分：
   a. 情绪词汇匹配（正面/负面关键词）
   b. 语音情绪标签加权（非 NEUTRAL 标签）
   c. 时间间隔信号加权（冷暴力/争吵间隔额外加权）
   d. 对话轮次平衡度（ME vs OTHER 发言比例）
   e. 消息长度多样性
   f. 多模态丰富度（非文本消息占比）
5. 按评分排序，选取 top N 片段
6. 为选中片段生成格式化文本和多模态密度元数据
7. 输出到 JSONL 文件

输入：
- timeline_out/agent_sft_l1.jsonl 或 agent_sft_l2.jsonl: SFT 数据文件
- 每行一个 JSON 对象，包含 speaker, type, text_raw, time, voice_to_text, emotion_tags 等字段

输出：
- JSONL 文件，每行包含：chunk_id, conversation_text, chunk_type, score, mm_density 等

依赖：
- tqdm: 进度条显示

使用示例：
    from scripts.advisor.extractor import ConversationExtractor
    
    extractor = ConversationExtractor({
        'window_size': 20,
        'step_size': 10,
        'num_chunks': 100,
    })
    chunks = extractor.extract_chunks('timeline_out/agent_sft_l1.jsonl', num_chunks=100)
    extractor.save_chunks(chunks, 'advisor_out/chunks.jsonl')
    print(extractor.get_stats())

性能参考：
- 10000 条消息提取 100 个 chunk：约 2-5 秒
- 评分计算为 CPU 密集型，无 GPU 依赖

注意事项：
- 片段类型分为 conflict（冲突）、sweet（甜蜜）、normal（普通）三类
- 冲突片段权重 1.5x，甜蜜片段 1.3x，确保训练数据中冲突场景充分覆盖
- 多模态密度（mm_density）用于下游 LLM 判断是否需要多模态深度分析
- save_chunks 保存时不包含原始消息列表（messages），仅保存格式化文本以节省空间

作者：[Author]
更新于：2026-02-15
"""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional
from tqdm import tqdm


# 情绪词汇表
NEGATIVE_KEYWORDS = [
    '生气', '烦', '累', '难过', '伤心', '失望', '无语', '算了', '不想', '讨厌',
    '为什么', '怎么', '总是', '从不', '不理', '冷', '忙', '没空', '不回',
    '吵', '闹', '分手', '离开', '不爱', '不喜欢', '受不了', '够了',
]

POSITIVE_KEYWORDS = [
    '爱你', '想你', '喜欢', '开心', '幸福', '甜', '亲爱', '宝贝', '老公', '老婆',
    '谢谢', '感谢', '抱抱', '亲亲', '么么', '❤', '😘', '🥰', '💕',
    '好棒', '厉害', '支持', '加油', '相信',
]


class ConversationExtractor:
    """对话片段提取器
    
    从 SFT 数据文件中使用滑动窗口提取有代表性的对话片段，
    通过多维度评分系统（情绪/平衡/多样性/多模态）选取最优片段。
    
    Attributes:
        window_size (int): 滑动窗口大小（消息数）
        step_size (int): 滑动步长（消息数）
        min_messages (int): 最小消息数阈值
        exclude_system (bool): 是否排除系统消息
        exclude_types (list[str]): 排除的消息类型列表
        priority_weights (dict): 片段类型权重（conflict/sweet/turning_point/normal）
        stats (dict): 提取统计信息
    
    Example:
        >>> extractor = ConversationExtractor({'window_size': 30})
        >>> chunks = extractor.extract_chunks('data.jsonl', num_chunks=50)
        >>> print(f"提取了 {len(chunks)} 个片段")
    """
    
    def __init__(self, config: Optional[dict] = None):
        """
        初始化提取器
        
        Args:
            config: 配置字典，包含：
                - window_size: 窗口大小（默认 20）
                - step_size: 滑动步长（默认 10）
                - min_messages: 最小消息数（默认 10）
                - exclude_system: 是否排除系统消息（默认 True）
                - exclude_types: 排除的消息类型列表
        """
        config = config or {}
        self.window_size = config.get('window_size', 20)
        self.step_size = config.get('step_size', 10)
        self.min_messages = config.get('min_messages', 10)
        self.max_messages = config.get('max_messages', self.window_size)
        self.segmentation_strategy = config.get('segmentation_strategy', 'sliding_window')
        self.time_gap_threshold = config.get('time_gap_threshold', 21600)
        self.emotion_shift_threshold = config.get('emotion_shift_threshold', 0.5)
        self.exclude_system = config.get('exclude_system', True)
        self.exclude_types = config.get('exclude_types', [])
        
        # 优先权重
        self.priority_weights = config.get('priority_weights', {
            'conflict': 1.5,
            'sweet': 1.3,
            'turning_point': 1.4,
            'normal': 1.0,
        })
        
        # 统计信息
        self.stats = {
            'total_messages': 0,
            'total_chunks': 0,
            'filtered_chunks': 0,
            'conflict_chunks': 0,
            'sweet_chunks': 0,
            'normal_chunks': 0,
        }

    def _filter_messages(self, messages: list[dict]) -> list[dict]:
        filtered = []
        for msg in messages:
            msg_type = msg.get('type', '')
            if msg_type in self.exclude_types:
                continue
            if self.exclude_system and msg.get('speaker') == 'SYSTEM' and msg_type != 'time_gap':
                continue
            filtered.append(msg)
        return filtered

    def _parse_time(self, msg: dict) -> Optional[datetime]:
        value = msg.get('ts') or msg.get('time_local') or msg.get('datetime')
        if not value:
            return None
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value)
        if isinstance(value, str):
            for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S'):
                try:
                    return datetime.strptime(value[:19], fmt)
                except ValueError:
                    continue
        return None

    def _compute_time_gap(self, left: dict, right: dict) -> Optional[float]:
        left_time = self._parse_time(left)
        right_time = self._parse_time(right)
        if left_time is None or right_time is None:
            return None
        return (right_time - left_time).total_seconds()

    def _get_sentiment(self, msg: dict) -> Optional[float]:
        text = self._extract_searchable_text(msg)
        if not text:
            return 0.0
        negative = sum(1 for keyword in NEGATIVE_KEYWORDS if keyword in text)
        positive = sum(1 for keyword in POSITIVE_KEYWORDS if keyword in text)
        if negative == positive == 0:
            return 0.0
        return (positive - negative) / max(positive + negative, 1)

    def _segment_by_sliding_window(self, messages: list[dict]) -> list[list[dict]]:
        segments = []
        window_size = min(self.window_size, self.max_messages)
        for i in range(0, len(messages) - self.min_messages + 1, self.step_size):
            window = messages[i:i + window_size]
            if len(window) >= self.min_messages:
                segments.append(window)
        return segments

    def _segment_by_events(self, messages: list[dict]) -> list[list[dict]]:
        segments = []
        current = []
        for msg in messages:
            if current:
                gap = self._compute_time_gap(current[-1], msg)
                last_sentiment = self._get_sentiment(current[-1])
                next_sentiment = self._get_sentiment(msg)
                has_time_gap = gap is not None and gap >= self.time_gap_threshold
                has_emotion_shift = (
                    last_sentiment is not None
                    and next_sentiment is not None
                    and abs(last_sentiment - next_sentiment) >= self.emotion_shift_threshold
                )
                should_split = (
                    len(current) >= self.max_messages
                    or (len(current) >= self.min_messages and (has_time_gap or has_emotion_shift))
                )
                if should_split:
                    segments.append(current)
                    current = []
            current.append(msg)
        if len(current) >= self.min_messages:
            segments.append(current)
        elif current and segments and len(segments[-1]) + len(current) <= self.max_messages:
            segments[-1].extend(current)
        return segments

    def extract_chunks_from_messages(self, messages: list[dict], num_chunks: int = 100) -> list[dict]:
        filtered = self._filter_messages(messages)
        if self.segmentation_strategy == 'event_based':
            segments = self._segment_by_events(filtered)
        else:
            segments = self._segment_by_sliding_window(filtered)
        chunks = []
        for i, segment in enumerate(segments[:num_chunks]):
            score, chunk_type = self._score_chunk(segment)
            chunks.append({
                'chunk_id': f"chunk_{i+1:04d}",
                'messages': segment,
                'conversation_text': self._format_chunk(segment),
                'score': score,
                'chunk_type': chunk_type,
                'message_count': len(segment),
                'mm_density': self._compute_mm_density(segment),
            })
        return chunks
    
    def extract_chunks(self, input_path: str, num_chunks: int = 100) -> list[dict]:
        """
        从 SFT 数据文件提取对话片段
        
        Args:
            input_path: 输入文件路径（agent_sft_l1.jsonl 或 agent_sft_l2.jsonl）
            num_chunks: 提取数量
        
        Returns:
            对话片段列表，每个片段包含 messages 和 metadata
        """
        # 读取所有消息
        messages = self._load_messages(input_path)
        self.stats['total_messages'] = len(messages)
        
        if len(messages) < self.min_messages:
            print(f"警告：消息数量不足 ({len(messages)} < {self.min_messages})")
            return []
        
        # 使用滑动窗口提取片段
        raw_chunks = self._sliding_window_extract(messages)
        self.stats['total_chunks'] = len(raw_chunks)
        
        # 计算每个片段的分数
        scored_chunks = []
        for chunk in tqdm(raw_chunks, desc="计算片段分数"):
            score, chunk_type = self._score_chunk(chunk['messages'])
            chunk['score'] = score
            chunk['chunk_type'] = chunk_type
            scored_chunks.append(chunk)
            
            # 更新统计
            if chunk_type == 'conflict':
                self.stats['conflict_chunks'] += 1
            elif chunk_type == 'sweet':
                self.stats['sweet_chunks'] += 1
            else:
                self.stats['normal_chunks'] += 1
        
        # 按分数排序，选取 top N
        scored_chunks.sort(key=lambda x: x['score'], reverse=True)
        selected_chunks = scored_chunks[:num_chunks]
        
        # 为选中的片段生成 ID、格式化文本和多模态密度
        result = []
        for i, chunk in enumerate(tqdm(selected_chunks, desc="格式化片段")):
            chunk['chunk_id'] = f"chunk_{i+1:04d}"
            chunk['conversation_text'] = self._format_chunk(chunk['messages'])
            chunk['mm_density'] = self._compute_mm_density(chunk['messages'])
            result.append(chunk)
        
        self.stats['filtered_chunks'] = len(result)
        return result
    
    def _load_messages(self, input_path: str) -> list[dict]:
        """从 JSONL 文件加载消息数据
        
        逐行读取 JSONL 文件，跳过空行和 JSON 解析错误的行。
        
        Args:
            input_path (str): JSONL 文件路径
        
        Returns:
            list[dict]: 消息字典列表
        
        Raises:
            FileNotFoundError: 文件不存在时抛出
        """
        messages = []
        path = Path(input_path)
        
        if not path.exists():
            raise FileNotFoundError(f"文件不存在: {input_path}")
        
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                    messages.append(msg)
                except json.JSONDecodeError as e:
                    print(f"警告：JSON 解析错误: {e}")
                    continue
        
        return messages
    
    def _sliding_window_extract(self, messages: list[dict]) -> list[dict]:
        """使用滑动窗口提取对话片段
        
        先过滤掉排除类型和系统消息，然后以 step_size 为步长、
        window_size 为窗口大小滑动切分。每个窗口需满足最小消息数
        和最小非系统消息数要求。
        
        Args:
            messages (list[dict]): 完整消息列表
        
        Returns:
            list[dict]: 片段列表，每个片段包含 messages, start_idx, end_idx,
                        start_time, end_time, message_count
        """
        chunks = []
        
        # 过滤掉不需要的消息类型
        filtered_messages = []
        for msg in messages:
            msg_type = msg.get('type', '')
            if msg_type in self.exclude_types:
                continue
            if self.exclude_system and msg.get('speaker') == 'SYSTEM' and msg_type != 'time_gap':
                continue
            filtered_messages.append(msg)
        
        # 滑动窗口
        for i in range(0, len(filtered_messages) - self.min_messages + 1, self.step_size):
            window = filtered_messages[i:i + self.window_size]
            
            # 确保窗口内有足够的消息
            if len(window) < self.min_messages:
                continue
            
            # 确保至少有一条非系统消息
            non_system = [m for m in window if m.get('speaker') != 'SYSTEM']
            if len(non_system) < self.min_messages // 2:
                continue
            
            # 获取时间范围
            start_time = window[0].get('time', '')
            end_time = window[-1].get('time', '')
            
            chunks.append({
                'messages': window,
                'start_idx': i,
                'end_idx': i + len(window),
                'start_time': start_time,
                'end_time': end_time,
                'message_count': len(window),
            })
        
        return chunks
    
    def _extract_searchable_text(self, msg: dict) -> str:
        """从消息中提取所有可搜索的文本内容（用于情绪关键词匹配）"""
        parts = []
        msg_type = msg.get('type', 'text')
        # text_raw 适用于 text/quote/link/file/miniprogram/time_gap
        raw = msg.get('text_raw', '')
        if raw:
            parts.append(raw)
        # 语音转写
        vtt = msg.get('voice_to_text', '')
        if vtt:
            parts.append(vtt)
        # 表情意图
        si = msg.get('sticker_intent', '')
        if si:
            parts.append(si)
        # 情绪描述
        ed = msg.get('emotion_desc', '')
        if ed:
            parts.append(ed)
        # 图片/视频氛围
        for field in ('image_emotion_atmosphere', 'video_atmosphere'):
            val = msg.get(field, '')
            if val:
                parts.append(val)
        return ' '.join(parts)

    def _score_chunk(self, messages: list[dict]) -> tuple[float, str]:
        """
        计算片段的代表性分数（多模态增强版）
        
        Returns:
            (分数, 类型) 元组
        """
        # 统计情绪词汇（扩展到所有模态文本）
        negative_count = 0
        positive_count = 0
        total_text_length = 0
        emotion_signal_count = 0
        time_gap_count = 0
        
        for msg in messages:
            searchable = self._extract_searchable_text(msg)
            total_text_length += len(searchable)
            
            for keyword in NEGATIVE_KEYWORDS:
                if keyword in searchable:
                    negative_count += 1
            
            for keyword in POSITIVE_KEYWORDS:
                if keyword in searchable:
                    positive_count += 1

            # 语音情绪标签（非 NEUTRAL 视为情绪信号）
            emotion_tags = msg.get('emotion_tags', [])
            if emotion_tags and emotion_tags != ['NEUTRAL']:
                emotion_signal_count += 1
                # 负面情绪标签加权
                neg_emotions = {'ANGRY', 'SAD', 'FEARFUL', 'DISGUSTED'}
                if isinstance(emotion_tags, list):
                    for tag in emotion_tags:
                        if tag.upper() in neg_emotions:
                            negative_count += 1

            # time_gap 信号（按 break_type 差异化加权）
            if msg.get('type') == 'time_gap':
                time_gap_count += 1
                bt = msg.get('break_type', '')
                if bt in ('cold_period', 'argument_gap'):
                    time_gap_count += 1  # 冷暴力/争吵间隔额外加权
                elif bt == 'topic_change':
                    time_gap_count += 0.5  # 话题切换中等加权
        
        # 计算对话轮次平衡度
        me_count = sum(1 for m in messages if m.get('speaker') == 'ME')
        other_count = sum(1 for m in messages if m.get('speaker') == 'OTHER')
        total = me_count + other_count
        balance = 1.0 - abs(me_count - other_count) / max(total, 1)
        
        # 计算消息长度多样性
        lengths = [len(self._extract_searchable_text(m)) for m in messages]
        if lengths:
            avg_length = sum(lengths) / len(lengths)
            variance = sum((l - avg_length) ** 2 for l in lengths) / len(lengths)
            diversity = min(variance / 1000, 1.0)
        else:
            diversity = 0.0
        
        # 多模态丰富度：非文本消息占比（越丰富越有分析价值）
        multimodal_types = {'sticker', 'image', 'voice', 'video', 'location'}
        multimodal_count = sum(1 for m in messages if m.get('type') in multimodal_types)
        multimodal_ratio = min(multimodal_count / max(len(messages), 1) * 2, 1.0)

        # 确定片段类型和权重
        if negative_count > positive_count and negative_count >= 3:
            chunk_type = 'conflict'
            type_weight = self.priority_weights.get('conflict', 1.5)
        elif positive_count > negative_count and positive_count >= 3:
            chunk_type = 'sweet'
            type_weight = self.priority_weights.get('sweet', 1.3)
        else:
            chunk_type = 'normal'
            type_weight = self.priority_weights.get('normal', 1.0)
        
        # 时间间隔加权：含 time_gap 意味着有时间模式可分析
        time_gap_bonus = min(time_gap_count * 0.15, 0.3)

        # 综合分数
        base_score = (
            0.25 * balance +
            0.15 * diversity +
            0.20 * min(negative_count / 5, 1.0) +
            0.15 * min(positive_count / 5, 1.0) +
            0.10 * min(total_text_length / 500, 1.0) +
            0.10 * multimodal_ratio +
            0.05 * min(emotion_signal_count / 3, 1.0)
        ) + time_gap_bonus
        
        final_score = base_score * type_weight
        return final_score, chunk_type
    
    def _compute_mm_density(self, messages: list[dict]) -> dict:
        """
        D1 优化: 计算 chunk 的多模态信号密度

        量化语音/图片/表情/视频/位置消息的分布，
        帮助下游 LLM (尤其 Gemini) 判断是否需要多模态深度分析。

        Returns:
            mm_density dict: voice/image/sticker/video/location 计数 + density 比例
        """
        counts = {
            'voice': 0,
            'image': 0,
            'sticker': 0,
            'video': 0,
            'location': 0,
            'emotion_tagged': 0,  # 带非 NEUTRAL 情绪标签的消息数
        }
        total_msgs = 0

        for msg in messages:
            msg_type = msg.get('type', 'text')
            if msg_type in ('time_gap', 'system'):
                continue
            total_msgs += 1

            if msg_type == 'voice':
                counts['voice'] += 1
            elif msg_type == 'image':
                counts['image'] += 1
            elif msg_type == 'sticker':
                counts['sticker'] += 1
            elif msg_type == 'video':
                counts['video'] += 1
            elif msg_type == 'location':
                counts['location'] += 1

            # 情绪标签 (语音情绪、图片氛围等)
            emotion_tags = msg.get('emotion_tags', [])
            if emotion_tags and emotion_tags != ['NEUTRAL']:
                counts['emotion_tagged'] += 1
            elif msg.get('image_emotion_atmosphere') or msg.get('video_atmosphere'):
                counts['emotion_tagged'] += 1

        total_mm = counts['voice'] + counts['image'] + counts['sticker'] + counts['video'] + counts['location']
        density = round(total_mm / max(total_msgs, 1), 3)

        return {
            **counts,
            'total_multimodal': total_mm,
            'total_messages': total_msgs,
            'density': density,  # 0.0 ~ 1.0, 越高多模态越丰富
        }

    def _format_chunk(self, messages: list[dict]) -> str:
        """
        将消息列表格式化为带时间戳的多模态对话文本
        
        格式：
        [第N天 HH:MM] SPEAKER: 内容
        --- [时间间隔标记] ---
        """
        lines = []
        for msg in messages:
            msg_type = msg.get('type', 'text')
            speaker = msg.get('speaker', 'UNKNOWN')

            # time_gap 特殊处理：作为时间线断点标记，无 speaker/时间前缀
            if msg_type == 'time_gap':
                gap_text = msg.get('text_raw', '')
                if gap_text:
                    lines.append(f"--- {gap_text} ---")
                continue

            # system 消息由 exclude_system 控制，此处兜底跳过
            if msg_type == 'system':
                continue

            # 构建时间前缀 [第N天 HH:MM]
            ts_rel = msg.get('ts_relative', '')
            time_val = msg.get('time', '')
            time_prefix = ''
            if ts_rel or time_val:
                time_prefix = f"[{ts_rel} {time_val}]".strip('[ ]')
                time_prefix = f"[{time_prefix}] "

            # 按类型分派，提取对应字段
            text = ''
            if msg_type == 'text':
                text = msg.get('text_raw', '')
            elif msg_type == 'quote':
                text = msg.get('text_raw', '')
                quote = msg.get('link_quote_text', '')
                if quote:
                    text = f"{text} (引用: {quote})"
            elif msg_type == 'sticker':
                intent = msg.get('sticker_intent', '')
                summary = msg.get('sticker_summary', '')
                ocr = msg.get('sticker_ocr_text', '')
                parts = [p for p in [intent, summary] if p]
                text = f"[表情: {' | '.join(parts) or '表情'}]"
                if ocr:
                    text += f" (文字: {ocr})"
            elif msg_type == 'image':
                summary = msg.get('image_summary', '图片')
                intent = msg.get('image_intent', '')
                atmosphere = msg.get('image_emotion_atmosphere', '')
                ocr = msg.get('image_ocr_text', '')
                text = f"[图片: {summary}]"
                meta = []
                if intent:
                    meta.append(f"意图:{intent}")
                if atmosphere:
                    meta.append(f"氛围:{atmosphere}")
                if meta:
                    text += f" ({', '.join(meta)})"
                if ocr:
                    text += f" (文字: {ocr})"
            elif msg_type == 'voice':
                voice_text = msg.get('voice_to_text', '')
                emotion_tags = msg.get('emotion_tags', [])
                emotion_desc = msg.get('emotion_desc', '')
                text = f"[语音: {voice_text or '(无转写)'}]"
                meta = []
                if emotion_tags and emotion_tags != ['NEUTRAL']:
                    tag_str = '/'.join(emotion_tags) if isinstance(emotion_tags, list) else str(emotion_tags)
                    meta.append(f"情绪:{tag_str}")
                if emotion_desc:
                    meta.append(emotion_desc)
                if meta:
                    text += f" ({', '.join(meta)})"
            elif msg_type == 'video':
                summary = msg.get('video_summary', '视频')
                atmosphere = msg.get('video_atmosphere', '')
                intent = msg.get('video_intent', '')
                voice = msg.get('video_voice_to_text', '')
                text = f"[视频: {summary}]"
                meta = []
                if atmosphere:
                    meta.append(f"氛围:{atmosphere}")
                if intent:
                    meta.append(f"意图:{intent}")
                if meta:
                    text += f" ({', '.join(meta)})"
                if voice:
                    text += f" (语音: {voice})"
            elif msg_type == 'location':
                poiname = msg.get('location_poiname', '')
                label = msg.get('location_label', '')
                parts = [p for p in [poiname, label] if p]
                text = f"[位置: {', '.join(parts) or '未知位置'}]"
            elif msg_type == 'file':
                file_summary = msg.get('link_file_summary', '')
                raw = msg.get('text_raw', '')
                text = f"[文件: {file_summary or raw or '文件'}]"
            elif msg_type == 'link':
                title = msg.get('link_title', '')
                raw = msg.get('text_raw', '')
                if title and raw and title != raw:
                    text = f"[链接: {title}] {raw}"
                else:
                    text = f"[链接: {title or raw or '链接'}]"
            elif msg_type == 'miniprogram':
                title = msg.get('link_title', '')
                text = f"[小程序: {title or '小程序'}]"
            elif msg_type == 'contact':
                nickname = msg.get('contact_nickname', '')
                text = f"[名片: {nickname or '联系人'}]"
            else:
                # 未知类型，尝试 text_raw 兜底
                text = msg.get('text_raw', '')

            # 跳过完全无内容的消息
            if not text.strip():
                continue

            lines.append(f"{time_prefix}{speaker}: {text}")
        
        return '\n'.join(lines)
    
    def get_stats(self) -> dict:
        """获取提取统计信息
        
        Returns:
            dict: 统计字典，包含 total_messages, total_chunks, filtered_chunks,
                  conflict_chunks, sweet_chunks, normal_chunks
        """
        return self.stats.copy()
    
    def save_chunks(self, chunks: list[dict], output_path: str) -> None:
        """
        保存提取的片段到 JSONL 文件
        
        Args:
            chunks: 片段列表
            output_path: 输出文件路径
        """
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(path, 'w', encoding='utf-8') as f:
            for chunk in chunks:
                # 创建保存版本（不包含完整消息列表以节省空间）
                save_chunk = {
                    'chunk_id': chunk['chunk_id'],
                    'conversation_text': chunk['conversation_text'],
                    'chunk_type': chunk['chunk_type'],
                    'score': chunk['score'],
                    'start_time': chunk['start_time'],
                    'end_time': chunk['end_time'],
                    'message_count': chunk['message_count'],
                    'mm_density': chunk.get('mm_density', {}),
                }
                f.write(json.dumps(save_chunk, ensure_ascii=False) + '\n')
        
        print(f"已保存 {len(chunks)} 个片段到 {output_path}")
