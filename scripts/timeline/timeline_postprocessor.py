# -*- coding: utf-8 -*-
"""
时间轴后处理器 - 消息合并与时间标记

功能：
- 连续消息智能合并（情绪感知、短句识别）
- 时间流逝标记插入（2小时以上间隔）
- 对话中断类型检测（正常间隔、冷暴力、话题切换、跨天）
- 提升时间轴可读性和语义连贯性

处理流程：
1. 加载配置文件（configs/compression.yaml）
2. 读取时间轴文件（timeline_out/enriched_full.jsonl）
3. 按时间排序消息
4. 逐条处理：
   a. 检查是否需要插入时间流逝标记（间隔 >= 2小时）
   b. 检查是否可以合并连续消息（同一 speaker、时间间隔 < 60秒）
   c. 应用情绪感知合并策略
   d. 识别短句模式（确认类、情绪爆发类、讨论类）
5. 保存处理后的时间轴（timeline_out/enriched_full_processed.jsonl）

消息合并策略：
合并条件（必须全部满足）：
1. 同一 speaker（ME 或 OTHER）
2. 时间间隔 < threshold_seconds（默认 60 秒）
3. 时间间隔 < max_gap_seconds（默认 300 秒，超过5分钟不合并）
4. 都是文本消息（如果 text_only=True）
5. 情绪兼容（如果 emotion_aware=True）
6. 不是快速连发的情绪爆发类短句

情绪兼容性检查：
- 冲突的情绪组合不合并：
  * HAPPY/EXCITED vs ANGRY/SAD/FEARFUL
  * ANGRY vs HAPPY/NEUTRAL
  * SAD vs HAPPY/EXCITED
- 相同或中性情绪可以合并

短句模式识别：
1. 确认类（可合并）：
   - 关键词：好、好的、嗯、嗯嗯、收到、OK、行、可以、知道了、明白
   - 示例："好的" + "收到" → "好的 收到"

2. 情绪爆发类（不合并）：
   - 特征：！！、？？、...、。。。
   - 示例："什么！！" + "怎么可能！！" → 保持独立

3. 讨论类（可合并）：
   - 特征：包含疑问词但语气平和
   - 示例："你在哪" + "什么时候到" → "你在哪 什么时候到"

合并规则：
- 短句（<10字）：用空格连接
- 长句（>=10字）：用换行符连接
- 保留第一条消息的元数据（msg_uid, ts, speaker）
- 添加合并元数据：
  * merged_count: 合并的消息数
  * original_ids: 原始消息 ID 列表
  * merged_ts_range: 时间范围（start, end）
  * emotion_tags: 合并后的情绪标签（取并集）

时间流逝标记：
触发条件：
- 间隔 >= threshold_seconds（默认 7200 秒 = 2小时）
- 前一条消息不是时间标记

标记内容：
- msg_uid: TIME_GAP_{ts_before}_{ts_after}
- ts: 中间时间点
- speaker: SYSTEM
- modality: system
- type: time_gap
- text_raw: "[X天Y小时后]" 或 "[X小时后]"
- gap_seconds: 间隔秒数
- gap_description: 间隔描述
- break_type: 中断类型
- context: 上下文信息（前后 speaker、情绪）

对话中断类型检测：
1. normal_gap（正常间隔）：
   - 常规时间间隔（如睡觉、工作）
   - 无特殊情绪或话题变化

2. potential_cold_shoulder（潜在冷暴力）：
   - 前一条消息有负面情绪（SAD/ANGRY/FEARFUL/DISGUSTED）
   - 对方长时间未回复（>= 1小时）
   - 可能是情感冷暴力

3. topic_change（话题切换）：
   - 前后消息关键词完全不重叠
   - 可能是话题转换

4. day_change（跨天对话）：
   - 前后消息不在同一天
   - 自然的时间分界

输入：
- timeline_out/enriched_full.jsonl（完整时间轴）
- configs/compression.yaml（后处理配置）

输出：
- timeline_out/enriched_full_processed.jsonl（处理后的时间轴）

依赖：
- json: JSON 解析
- yaml: 配置解析
- datetime: 时间处理
- re: 正则表达式（关键词提取）

使用示例：
    # 命令行（通常由流水线自动调用）
    python scripts/timeline/timeline_postprocessor.py \
      --input timeline_out/enriched_full.jsonl \
      --output timeline_out/enriched_full_processed.jsonl
    
    # Python API
    from scripts.timeline.timeline_postprocessor import TimelinePostprocessor
    
    processor = TimelinePostprocessor()
    
    # 加载消息
    messages = load_timeline("timeline_out/enriched_full.jsonl")
    
    # 处理
    processed = processor.process(messages)
    
    # 保存
    save_timeline(processed, "timeline_out/enriched_full_processed.jsonl")
    
    # 获取统计
    stats = processor.get_stats()
    print(f"总消息数: {stats['total_messages']}")
    print(f"合并组数: {stats['merged_groups']}")
    print(f"合并消息数: {stats['messages_merged']}")
    print(f"插入时间标记: {stats['time_gaps_inserted']}")
    print(f"中断类型统计: {stats['break_types']}")

配置示例（configs/compression.yaml）：
    timeline_postprocess:
      message_merge:
        enabled: true
        threshold_seconds: 60        # 合并阈值（秒）
        max_gap_seconds: 300         # 最大间隔（秒）
        emotion_aware: true          # 启用情绪感知
        text_only: true              # 仅合并文本消息
        short_message:
          length_threshold: 5        # 短句长度阈值
          rapid_interval_seconds: 10 # 快速连发阈值
          confirmation_keywords:     # 确认类关键词
            - 好
            - 好的
            - 嗯
            - 收到
            - OK
          emotional_burst_patterns:  # 情绪爆发特征
            - ！！
            - ？？
            - ...
      
      time_gap:
        enabled: true
        threshold_seconds: 7200      # 时间标记阈值（2小时）

统计信息：
- total_messages: 总消息数
- merged_groups: 合并组数
- messages_merged: 被合并的消息数
- time_gaps_inserted: 插入的时间标记数
- break_types: 中断类型统计
  * normal_gap: 正常间隔数
  * potential_cold_shoulder: 潜在冷暴力数
  * topic_change: 话题切换数
  * day_change: 跨天对话数

预期效果：
- 减少碎片化消息（短句合并）
- 提升时间轴可读性
- 保留情绪变化信息
- 标记重要时间节点
- 识别对话模式（冷暴力、话题切换等）

作者：[Author]
更新于：2026-02-02
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
import yaml


@dataclass
class MergeConfig:
    """消息合并配置"""
    enabled: bool = True
    threshold_seconds: int = 60
    max_gap_seconds: int = 300
    emotion_aware: bool = True
    text_only: bool = True
    short_message_length: int = 5
    rapid_interval_seconds: int = 10
    confirmation_keywords: List[str] = field(default_factory=list)
    emotional_burst_patterns: List[str] = field(default_factory=list)


@dataclass
class TimeGapConfig:
    """时间流逝标记配置"""
    enabled: bool = True
    threshold_seconds: int = 7200  # 2小时


class TimelinePostprocessor:
    """时间轴后处理器：合并连续消息、插入时间标记"""
    
    def __init__(self, config_path: str = "configs/compression.yaml"):
        self.config = self._load_config(config_path)
        self.merge_config = self._parse_merge_config()
        self.time_gap_config = self._parse_time_gap_config()
        
        # 统计信息
        self.stats = {
            "total_messages": 0,
            "merged_groups": 0,
            "messages_merged": 0,
            "time_gaps_inserted": 0,
            "break_types": {
                "normal_gap": 0,
                "potential_cold_shoulder": 0,
                "topic_change": 0,
                "day_change": 0
            }
        }
    
    def _load_config(self, config_path: str) -> dict:
        """加载配置文件"""
        path = Path(config_path)
        if not path.exists():
            print(f"[WARN] 配置文件不存在: {config_path}，使用默认配置")
            return {}
        
        with open(path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    
    def _parse_merge_config(self) -> MergeConfig:
        """解析消息合并配置"""
        cfg = self.config.get('timeline_postprocess', {}).get('message_merge', {})
        short_cfg = cfg.get('short_message', {})
        
        return MergeConfig(
            enabled=cfg.get('enabled', True),
            threshold_seconds=cfg.get('threshold_seconds', 60),
            max_gap_seconds=cfg.get('max_gap_seconds', 300),
            emotion_aware=cfg.get('emotion_aware', True),
            text_only=cfg.get('text_only', True),
            short_message_length=short_cfg.get('length_threshold', 5),
            rapid_interval_seconds=short_cfg.get('rapid_interval_seconds', 10),
            confirmation_keywords=short_cfg.get('confirmation_keywords', [
                "好", "好的", "嗯", "嗯嗯", "收到", "OK", "ok", "行", "可以", "知道了", "明白"
            ]),
            emotional_burst_patterns=short_cfg.get('emotional_burst_patterns', [
                "！！", "？？", "...", "。。。"
            ])
        )
    
    def _parse_time_gap_config(self) -> TimeGapConfig:
        """解析时间流逝标记配置"""
        cfg = self.config.get('timeline_postprocess', {}).get('time_gap', {})
        
        return TimeGapConfig(
            enabled=cfg.get('enabled', True),
            threshold_seconds=cfg.get('threshold_seconds', 7200)
        )
    
    def process(self, messages: List[Dict]) -> List[Dict]:
        """
        处理消息列表
        
        Args:
            messages: 按时间排序的消息列表
            
        Returns:
            处理后的消息列表（包含合并和时间标记）
        """
        if not messages:
            return []
        
        self.stats["total_messages"] = len(messages)
        
        # 按时间排序
        messages = sorted(messages, key=lambda x: x.get('ts', 0))
        
        result = []
        i = 0
        
        while i < len(messages):
            current = messages[i]
            
            # 检查是否需要插入时间流逝标记
            if result and self.time_gap_config.enabled:
                prev = result[-1]
                # 跳过已经是时间标记的消息
                if prev.get('modality') != 'system':
                    gap_seconds = current.get('ts', 0) - prev.get('ts', 0)
                    if gap_seconds >= self.time_gap_config.threshold_seconds:
                        time_gap_msg = self._insert_time_gap(gap_seconds, prev, current)
                        result.append(time_gap_msg)
                        self.stats["time_gaps_inserted"] += 1
            
            # 检查是否可以合并连续消息
            if self.merge_config.enabled and self._can_start_merge(current):
                merged, consumed = self._try_merge_messages(messages, i)
                if consumed > 1:
                    result.append(merged)
                    self.stats["merged_groups"] += 1
                    self.stats["messages_merged"] += consumed
                    i += consumed
                    continue
            
            result.append(current)
            i += 1
        
        return result
    
    def _can_start_merge(self, msg: Dict) -> bool:
        """判断消息是否可以作为合并的起点"""
        # 只合并文本消息
        if self.merge_config.text_only and msg.get('modality') != 'text':
            return False
        return True
    
    def _should_merge(self, msg1: Dict, msg2: Dict) -> bool:
        """
        判断两条消息是否应该合并
        
        合并条件（必须全部满足）：
        1. 同一 speaker
        2. 时间间隔 < threshold_seconds（默认 60 秒）
        3. 时间间隔 < max_gap_seconds（超过5分钟不合并，可能是冷暴力）
        4. 都是文本消息（如果 text_only=True）
        5. 情绪兼容（如果 emotion_aware=True）
        6. 不是快速连发的情绪爆发类短句
        """
        # 条件1：同一 speaker
        if msg1.get('speaker') != msg2.get('speaker'):
            return False
        
        # 条件2&3：时间间隔
        gap = msg2.get('ts', 0) - msg1.get('ts', 0)
        if gap > self.merge_config.threshold_seconds:
            return False
        if gap > self.merge_config.max_gap_seconds:
            return False
        
        # 条件4：都是文本消息
        if self.merge_config.text_only:
            if msg1.get('modality') != 'text' or msg2.get('modality') != 'text':
                return False
        
        # 条件5：情绪兼容
        if self.merge_config.emotion_aware:
            if not self._emotions_compatible(msg1, msg2):
                return False
        
        # 条件6：检查是否为情绪爆发类短句
        text1 = msg1.get('text_raw', '')
        text2 = msg2.get('text_raw', '')
        
        if (len(text1) <= self.merge_config.short_message_length and 
            len(text2) <= self.merge_config.short_message_length and
            gap <= self.merge_config.rapid_interval_seconds):
            
            pattern = self._classify_short_message_pattern([msg1, msg2])
            if pattern == 'emotional_burst':
                return False
        
        return True
    
    def _emotions_compatible(self, msg1: Dict, msg2: Dict) -> bool:
        """
        检查两条消息的情绪是否兼容
        
        冲突的情绪组合不应合并，如：
        - HAPPY vs ANGRY
        - HAPPY vs SAD
        """
        emotions1 = set(msg1.get('emotion_tags', []))
        emotions2 = set(msg2.get('emotion_tags', []))
        
        # 如果都没有情绪标签，认为兼容
        if not emotions1 or not emotions2:
            return True
        
        # 定义冲突的情绪对
        conflicts = [
            ({'HAPPY', 'EXCITED'}, {'ANGRY', 'SAD', 'FEARFUL'}),
            ({'ANGRY'}, {'HAPPY', 'NEUTRAL'}),
            ({'SAD'}, {'HAPPY', 'EXCITED'}),
        ]
        
        for group1, group2 in conflicts:
            if (emotions1 & group1 and emotions2 & group2) or \
               (emotions1 & group2 and emotions2 & group1):
                return False
        
        return True
    
    def _classify_short_message_pattern(self, messages: List[Dict]) -> str:
        """
        分类短消息模式
        
        Returns:
            'confirmation': 确认类（可合并）
            'emotional_burst': 情绪爆发类（不合并）
            'discussion': 讨论类（可合并）
            'unknown': 无法判断（保守不合并）
        """
        texts = [m.get('text_raw', '') for m in messages]
        combined = ''.join(texts)
        
        # 检查情绪爆发类特征
        for pattern in self.merge_config.emotional_burst_patterns:
            if pattern in combined:
                return 'emotional_burst'
        
        # 检查是否全是确认类
        all_confirmation = all(
            any(kw in text for kw in self.merge_config.confirmation_keywords)
            for text in texts if text
        )
        if all_confirmation:
            return 'confirmation'
        
        # 检查是否包含疑问词但语气平和
        question_words = ['吗', '呢', '什么', '怎么', '为什么', '哪', '谁', '？']
        has_question = any(qw in combined for qw in question_words)
        has_exclamation = '！' in combined or '!' in combined
        
        if has_question and not has_exclamation:
            return 'discussion'
        
        return 'unknown'
    
    def _try_merge_messages(self, messages: List[Dict], start_idx: int) -> Tuple[Dict, int]:
        """
        尝试从 start_idx 开始合并连续消息
        
        Returns:
            (merged_message, consumed_count)
        """
        to_merge = [messages[start_idx]]
        i = start_idx + 1
        
        while i < len(messages):
            if self._should_merge(to_merge[-1], messages[i]):
                to_merge.append(messages[i])
                i += 1
            else:
                break
        
        if len(to_merge) == 1:
            return to_merge[0], 1
        
        # 合并消息
        merged = self._merge_messages(to_merge)
        return merged, len(to_merge)
    
    def _merge_messages(self, messages: List[Dict]) -> Dict:
        """
        合并多条消息为一条
        
        合并规则：
        - 短句（<10字）用空格连接
        - 长句用换行符连接
        - 保留第一条消息的元数据
        - 添加 merged_count 和 original_ids 字段
        """
        if len(messages) == 1:
            return messages[0]
        
        # 基于第一条消息创建合并结果
        merged = messages[0].copy()
        
        # 合并文本
        texts = []
        for msg in messages:
            text = msg.get('text_raw', '')
            if text:
                texts.append(text)
        
        # 判断使用空格还是换行连接
        all_short = all(len(t) < 10 for t in texts)
        separator = ' ' if all_short else '\n'
        merged['text_raw'] = separator.join(texts)
        
        # 添加合并元数据
        merged['merged_count'] = len(messages)
        merged['original_ids'] = [m.get('msg_uid') for m in messages]
        merged['merged_ts_range'] = {
            'start': messages[0].get('ts'),
            'end': messages[-1].get('ts')
        }
        
        # 合并情绪标签（取并集）
        all_emotions = set()
        for msg in messages:
            all_emotions.update(msg.get('emotion_tags', []))
        if all_emotions:
            merged['emotion_tags'] = list(all_emotions)
        
        return merged
    
    def _insert_time_gap(self, gap_seconds: int, msg_before: Dict, msg_after: Dict) -> Dict:
        """
        创建时间流逝标记消息
        
        Args:
            gap_seconds: 时间间隔（秒）
            msg_before: 前一条消息
            msg_after: 后一条消息
        
        Returns:
            时间标记消息
        """
        # 计算时间描述
        hours = gap_seconds // 3600
        days = hours // 24
        remaining_hours = hours % 24
        
        if days > 0:
            if remaining_hours > 0:
                gap_desc = f"{days}天{remaining_hours}小时后"
            else:
                gap_desc = f"{days}天后"
        else:
            gap_desc = f"{hours}小时后"
        
        # 检测对话中断类型
        break_type = self._detect_conversation_break(msg_before, msg_after, gap_seconds)
        self.stats["break_types"][break_type] += 1
        
        # 创建时间标记消息
        time_gap_msg = {
            "msg_uid": f"TIME_GAP_{msg_before.get('ts')}_{msg_after.get('ts')}",
            "ts": msg_before.get('ts') + gap_seconds // 2,  # 放在中间时间点
            "speaker": "SYSTEM",
            "modality": "system",
            "type": "time_gap",
            "text_raw": f"[{gap_desc}]",
            "gap_seconds": gap_seconds,
            "gap_description": gap_desc,
            "break_type": break_type,
            "context": {
                "before_speaker": msg_before.get('speaker'),
                "after_speaker": msg_after.get('speaker'),
                "before_emotion": msg_before.get('emotion_tags', []),
                "after_emotion": msg_after.get('emotion_tags', [])
            }
        }
        
        return time_gap_msg
    
    def _detect_conversation_break(self, msg_before: Dict, msg_after: Dict, 
                                    gap_seconds: int) -> str:
        """
        检测对话中断类型
        
        Returns:
            'normal_gap': 正常时间间隔（如睡觉、工作）
            'potential_cold_shoulder': 潜在冷暴力（负面情绪后长时间无回复）
            'topic_change': 话题切换
            'day_change': 跨天对话
        """
        # 检查是否跨天
        ts_before = msg_before.get('ts', 0)
        ts_after = msg_after.get('ts', 0)
        
        dt_before = datetime.fromtimestamp(ts_before)
        dt_after = datetime.fromtimestamp(ts_after)
        
        if dt_before.date() != dt_after.date():
            return 'day_change'
        
        # 检查是否为潜在冷暴力
        # 条件：前一条消息有负面情绪，且对方长时间未回复
        before_emotions = set(msg_before.get('emotion_tags', []))
        negative_emotions = {'SAD', 'ANGRY', 'FEARFUL', 'DISGUSTED'}
        
        if before_emotions & negative_emotions:
            # 检查是否是对方未回复
            if msg_before.get('speaker') != msg_after.get('speaker'):
                # 间隔超过1小时，可能是冷暴力
                if gap_seconds >= 3600:
                    return 'potential_cold_shoulder'
        
        # 检查话题是否切换（简单启发式：检查关键词重叠）
        text_before = msg_before.get('text_raw', '')
        text_after = msg_after.get('text_raw', '')
        
        # 提取关键词（简单分词）
        words_before = set(re.findall(r'[\u4e00-\u9fff]+', text_before))
        words_after = set(re.findall(r'[\u4e00-\u9fff]+', text_after))
        
        # 如果关键词完全不重叠，可能是话题切换
        if words_before and words_after and not (words_before & words_after):
            return 'topic_change'
        
        return 'normal_gap'
    
    def get_stats(self) -> Dict:
        """获取处理统计信息"""
        return self.stats.copy()


def load_timeline(input_path: str) -> List[Dict]:
    """加载时间轴文件"""
    messages = []
    with open(input_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                messages.append(json.loads(line))
    return messages


def save_timeline(messages: List[Dict], output_path: str):
    """保存时间轴文件"""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        for msg in messages:
            f.write(json.dumps(msg, ensure_ascii=False) + '\n')
