# -*- coding: utf-8 -*-
"""
时间轴后处理器

对生成的时间轴进行后处理：
1. 连续消息合并（情绪感知）
2. 时间间隔标记插入
3. 对话中断类型检测

输入：timeline_out/enriched_full.jsonl
输出：timeline_out/enriched_full_processed.jsonl

用法：
    python scripts/timeline/postprocess_timeline.py
    python scripts/timeline/postprocess_timeline.py --input timeline_out/enriched_full.jsonl
    python scripts/timeline/postprocess_timeline.py --no-merge  # 禁用消息合并
    python scripts/timeline/postprocess_timeline.py --no-time-gap  # 禁用时间标记
"""

import json
import argparse
import re
import uuid
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from tqdm import tqdm
import yaml


class TimelinePostprocessor:
    """时间轴后处理器"""
    
    def __init__(self, config: dict):
        """
        初始化后处理器
        
        Args:
            config: 配置字典
        """
        # 消息合并配置
        merge_config = config.get('merge', {})
        self.merge_enabled = merge_config.get('enabled', True)
        self.merge_threshold = merge_config.get('threshold_seconds', 60)
        self.emotion_aware = merge_config.get('emotion_aware', True)
        self.merge_separator = merge_config.get('separator', ' | ')
        self.skip_modalities = set(merge_config.get('skip_modalities', [
            'image', 'voice', 'video', 'sticker', 'location', 'contact'
        ]))
        self.emotion_conflicts = [
            set(pair) for pair in merge_config.get('emotion_conflicts', [])
        ]
        
        # 时间间隔配置
        gap_config = config.get('time_gap', {})
        self.time_gap_enabled = gap_config.get('enabled', True)
        self.time_gap_threshold = gap_config.get('threshold_seconds', 7200)
        
        # 中断检测配置
        break_config = config.get('break_detection', {})
        self.break_detection_enabled = break_config.get('enabled', True)
        self.cold_shoulder_keywords = set(break_config.get('cold_shoulder_keywords', []))
        self.conflict_keywords = set(break_config.get('conflict_keywords', []))
        self.emotion_burst_pattern = re.compile(
            break_config.get('emotion_burst_pattern', r'[!！?？]{2,}')
        )
        self.cold_shoulder_hours = break_config.get('cold_shoulder_threshold_hours', 4)
        self.conflict_cooling_hours = break_config.get('conflict_cooling_threshold_hours', 12)
        
        # 快速连发配置
        rapid_config = config.get('rapid_fire', {})
        self.rapid_fire_enabled = rapid_config.get('enabled', True)
        self.rapid_threshold = rapid_config.get('threshold_seconds', 10)
        self.rapid_min_messages = rapid_config.get('min_messages', 3)
        self.rapid_max_length = rapid_config.get('max_length', 20)
        
        # 统计信息
        self.stats = {
            'total_input': 0,
            'total_output': 0,
            'messages_merged': 0,
            'merge_groups': 0,
            'time_gaps_inserted': 0,
            'break_types': {
                'normal_gap': 0,
                'potential_cold_shoulder': 0,
                'topic_change': 0,
                'conflict_cooling': 0
            },
            'rapid_fire_preserved': 0
        }
    
    def process(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        处理时间轴
        
        Args:
            messages: 原始消息列表
        
        Returns:
            处理后的消息列表
        """
        self.stats['total_input'] = len(messages)
        
        if not messages:
            return []
        
        result = []
        
        # Step 1: 消息合并
        if self.merge_enabled:
            messages = self._merge_messages(messages)
        
        # Step 2: 插入时间间隔标记
        if self.time_gap_enabled:
            messages = self._insert_time_gaps(messages)
        
        self.stats['total_output'] = len(messages)
        return messages
    
    def _merge_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        合并连续消息
        
        合并条件：
        1. 同一 speaker
        2. 时间间隔 < threshold
        3. 都是文本消息
        4. 情绪兼容
        5. 不是快速连发（吵架/撒娇）
        """
        if not messages:
            return []
        
        result = []
        merge_buffer = []  # 待合并的消息缓冲区
        
        for msg in messages:
            if not merge_buffer:
                merge_buffer.append(msg)
                continue
            
            last_msg = merge_buffer[-1]
            
            # 检查是否应该合并
            if self._should_merge(last_msg, msg, merge_buffer):
                merge_buffer.append(msg)
            else:
                # 输出合并结果
                merged = self._flush_merge_buffer(merge_buffer)
                result.extend(merged)
                merge_buffer = [msg]
        
        # 处理最后的缓冲区
        if merge_buffer:
            merged = self._flush_merge_buffer(merge_buffer)
            result.extend(merged)
        
        return result
    
    def _should_merge(self, msg1: Dict[str, Any], msg2: Dict[str, Any], 
                      buffer: List[Dict[str, Any]]) -> bool:
        """
        判断两条消息是否应该合并
        
        Args:
            msg1: 前一条消息
            msg2: 当前消息
            buffer: 当前合并缓冲区
        
        Returns:
            是否应该合并
        """
        # 条件 1: 同一 speaker
        if msg1.get('speaker') != msg2.get('speaker'):
            return False
        
        # 条件 2: 都是文本消息
        modality1 = msg1.get('modality', '')
        modality2 = msg2.get('modality', '')
        
        if modality1 in self.skip_modalities or modality2 in self.skip_modalities:
            return False
        
        if modality1 != 'text' or modality2 != 'text':
            return False
        
        # 条件 3: 时间间隔 < threshold
        gap = self._get_time_gap_seconds(msg1, msg2)
        if gap is None or gap > self.merge_threshold:
            return False
        
        # 条件 4: 情绪兼容（如果启用）
        if self.emotion_aware:
            if self._has_emotion_conflict(msg1, msg2):
                return False
            
            # 检查情绪爆发（连续感叹号/问号）
            text1 = msg1.get('text_raw', '')
            text2 = msg2.get('text_raw', '')
            if self.emotion_burst_pattern.search(text1) or self.emotion_burst_pattern.search(text2):
                return False
        
        # 条件 5: 不是快速连发（吵架/撒娇场景）
        # 检查当前消息是否是快速连发的一部分
        if self.rapid_fire_enabled:
            potential_buffer = buffer + [msg2]
            if self._is_potential_rapid_fire(potential_buffer):
                self.stats['rapid_fire_preserved'] += 1
                return False
        
        return True
    
    def _is_potential_rapid_fire(self, messages: List[Dict[str, Any]]) -> bool:
        """
        检测消息序列是否可能是快速连发的一部分
        
        与 _is_rapid_fire 不同，这个方法在消息数量不足时也会检测
        只要满足时间间隔和消息长度条件，就认为可能是快速连发
        """
        if len(messages) < 2:
            return False
        
        # 检查所有消息是否都是短消息
        for msg in messages:
            text = msg.get('text_raw', '')
            if len(text) > self.rapid_max_length:
                return False
        
        # 检查所有时间间隔是否都很短
        for i in range(1, len(messages)):
            gap = self._get_time_gap_seconds(messages[i-1], messages[i])
            if gap is None or gap > self.rapid_threshold:
                return False
        
        # 如果已经达到最小消息数，确认是快速连发
        if len(messages) >= self.rapid_min_messages:
            return True
        
        # 如果还没达到最小消息数，但满足条件，也认为可能是快速连发
        # 这样可以防止前几条消息被合并
        return True
    
    def _has_emotion_conflict(self, msg1: Dict[str, Any], msg2: Dict[str, Any]) -> bool:
        """检查两条消息是否有情绪冲突"""
        emotions1 = self._extract_emotions(msg1)
        emotions2 = self._extract_emotions(msg2)
        
        for conflict_pair in self.emotion_conflicts:
            if emotions1 & conflict_pair and emotions2 & conflict_pair:
                # 两条消息的情绪都在冲突对中
                if emotions1 != emotions2:
                    return True
        
        return False
    
    def _extract_emotions(self, msg: Dict[str, Any]) -> set:
        """从消息中提取情绪标签"""
        emotions = set()
        
        # 从 emotion_tags 提取
        tags = msg.get('emotion_tags', [])
        if isinstance(tags, list):
            emotions.update(tags)
        
        # 从 voice_analysis 提取
        voice_analysis = msg.get('voice_analysis', {})
        if voice_analysis:
            voice_tags = voice_analysis.get('emotion_tags', [])
            if isinstance(voice_tags, list):
                emotions.update(voice_tags)
        
        return emotions
    
    def _is_rapid_fire(self, messages: List[Dict[str, Any]]) -> bool:
        """
        检测是否是快速连发（吵架/撒娇场景）
        
        特征：
        - 短时间内（<10秒）连续发送
        - 至少3条消息
        - 每条消息都很短（<20字符）
        """
        if len(messages) < self.rapid_min_messages:
            return False
        
        # 检查时间间隔
        for i in range(1, len(messages)):
            gap = self._get_time_gap_seconds(messages[i-1], messages[i])
            if gap is None or gap > self.rapid_threshold:
                return False
        
        # 检查消息长度
        for msg in messages:
            text = msg.get('text_raw', '')
            if len(text) > self.rapid_max_length:
                return False
        
        return True
    
    def _flush_merge_buffer(self, buffer: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        输出合并缓冲区
        
        如果缓冲区只有一条消息，直接返回
        如果有多条消息，合并后返回
        """
        if not buffer:
            return []
        
        if len(buffer) == 1:
            return buffer
        
        # 合并多条消息
        merged = self._merge_message_group(buffer)
        self.stats['merge_groups'] += 1
        self.stats['messages_merged'] += len(buffer) - 1
        
        return [merged]
    
    def _merge_message_group(self, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        合并一组消息
        
        策略：
        - 使用第一条消息作为基础
        - 合并 text_raw
        - 添加 merged_count 字段
        """
        base = messages[0].copy()
        
        # 合并文本
        texts = [msg.get('text_raw', '') for msg in messages if msg.get('text_raw')]
        base['text_raw'] = self.merge_separator.join(texts)
        
        # 添加合并计数
        base['merged_count'] = len(messages)
        
        return base
    
    def _insert_time_gaps(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        插入时间间隔标记
        
        在间隔超过阈值的消息之间插入 time_gap 标记
        """
        if not messages:
            return []
        
        result = [messages[0]]
        
        for i in range(1, len(messages)):
            prev_msg = messages[i - 1]
            curr_msg = messages[i]
            
            gap_seconds = self._get_time_gap_seconds(prev_msg, curr_msg)
            
            if gap_seconds is not None and gap_seconds >= self.time_gap_threshold:
                # 创建时间间隔标记
                gap_marker = self._create_time_gap_marker(prev_msg, curr_msg, gap_seconds)
                result.append(gap_marker)
                self.stats['time_gaps_inserted'] += 1
            
            result.append(curr_msg)
        
        return result
    
    def _create_time_gap_marker(self, msg_before: Dict[str, Any], 
                                 msg_after: Dict[str, Any],
                                 gap_seconds: int) -> Dict[str, Any]:
        """
        创建时间间隔标记
        
        Args:
            msg_before: 间隔前的消息
            msg_after: 间隔后的消息
            gap_seconds: 间隔秒数
        
        Returns:
            时间间隔标记字典
        """
        # 生成人类可读的时间描述
        gap_description = self._format_time_gap(gap_seconds)
        
        # 检测中断类型
        break_type = 'normal_gap'
        if self.break_detection_enabled:
            break_type = self._detect_break_type(msg_before, msg_after, gap_seconds)
        
        self.stats['break_types'][break_type] = self.stats['break_types'].get(break_type, 0) + 1
        
        marker = {
            'msg_uid': f'GAP:{uuid.uuid4().hex[:8]}',
            'modality': 'system',
            'type': 'time_gap',
            'speaker': 'SYSTEM',
            'gap_description': gap_description,
            'gap_seconds': gap_seconds,
            'break_type': break_type
        }
        
        # 添加上下文提示
        context = self._generate_gap_context(break_type, gap_description)
        if context:
            marker['text_raw'] = context
        
        return marker
    
    def _format_time_gap(self, gap_seconds: int) -> str:
        """
        格式化时间间隔为精确的人类可读格式
        
        Args:
            gap_seconds: 间隔秒数
        
        Returns:
            精确的时间描述字符串
        
        格式规则：
        - < 1小时: "X分钟"
        - 1小时 ~ 1天: "X小时Y分钟"（分钟为0时省略）
        - >= 1天: "X天Y小时"（小时为0时省略）
        
        错误处理：
        - 输入为负数或0时：返回 "0分钟"
        - 输入为非整数时：向下取整处理
        """
        # 处理边界情况：负数或0
        gap_seconds = int(gap_seconds)  # 向下取整处理非整数
        if gap_seconds <= 0:
            return "0分钟"
        
        # 计算各时间单位
        days = gap_seconds // 86400
        remaining_after_days = gap_seconds % 86400
        hours = remaining_after_days // 3600
        remaining_after_hours = remaining_after_days % 3600
        minutes = remaining_after_hours // 60
        
        # 格式化输出
        if gap_seconds < 3600:
            # < 1小时: "X分钟"
            return f"{minutes}分钟"
        elif gap_seconds < 86400:
            # 1小时 ~ 1天: "X小时Y分钟"（分钟为0时省略）
            if minutes > 0:
                return f"{hours}小时{minutes}分钟"
            else:
                return f"{hours}小时"
        else:
            # >= 1天: "X天Y小时"（小时为0时省略）
            if hours > 0:
                return f"{days}天{hours}小时"
            else:
                return f"{days}天"
    
    def _detect_break_type(self, msg_before: Dict[str, Any], 
                           msg_after: Dict[str, Any],
                           gap_seconds: int) -> str:
        """
        检测对话中断类型
        
        类型：
        - normal_gap: 正常间隔（睡觉、工作）
        - potential_cold_shoulder: 潜在冷暴力
        - topic_change: 话题切换
        - conflict_cooling: 冲突后冷却期
        
        Args:
            msg_before: 间隔前的消息
            msg_after: 间隔后的消息
            gap_seconds: 间隔秒数
        
        Returns:
            中断类型
        """
        gap_hours = gap_seconds / 3600
        
        text_before = msg_before.get('text_raw', '')
        text_after = msg_after.get('text_raw', '')
        
        # 检测冲突后冷却
        if gap_hours >= self.conflict_cooling_hours:
            # 检查前一条消息是否有冲突关键词或情绪爆发
            if any(kw in text_before for kw in self.conflict_keywords):
                return 'conflict_cooling'
            if self.emotion_burst_pattern.search(text_before):
                return 'conflict_cooling'
            
            # 检查情绪标签
            emotions_before = self._extract_emotions(msg_before)
            if 'ANGRY' in emotions_before or 'SAD' in emotions_before:
                return 'conflict_cooling'
        
        # 检测潜在冷暴力
        if gap_hours >= self.cold_shoulder_hours:
            # 检查后一条消息是否是敷衍回复
            if text_after.strip() in self.cold_shoulder_keywords:
                return 'potential_cold_shoulder'
            
            # 检查前一条消息是否是求关注/求回复
            if '?' in text_before or '？' in text_before:
                if any(kw in text_before for kw in ['在吗', '干嘛', '怎么了', '为什么']):
                    return 'potential_cold_shoulder'
        
        # 检测话题切换（简单启发式：前后消息内容差异大）
        # 这里用简单的关键词重叠检测
        if self._is_topic_change(text_before, text_after):
            return 'topic_change'
        
        return 'normal_gap'
    
    def _is_topic_change(self, text_before: str, text_after: str) -> bool:
        """
        简单检测是否是话题切换
        
        启发式：如果两条消息没有共同关键词，可能是话题切换
        """
        if not text_before or not text_after:
            return False
        
        # 提取关键词（简单分词）
        words_before = set(re.findall(r'[\u4e00-\u9fff]+', text_before))
        words_after = set(re.findall(r'[\u4e00-\u9fff]+', text_after))
        
        # 过滤掉太短的词
        words_before = {w for w in words_before if len(w) >= 2}
        words_after = {w for w in words_after if len(w) >= 2}
        
        # 如果没有共同词且两边都有足够的词，认为是话题切换
        if len(words_before) >= 2 and len(words_after) >= 2:
            if not words_before & words_after:
                return True
        
        return False
    
    def _generate_gap_context(self, break_type: str, gap_description: str) -> str:
        """
        生成时间间隔的上下文提示
        
        Args:
            break_type: 中断类型
            gap_description: 时间描述
        
        Returns:
            上下文提示文本
        """
        context_map = {
            'normal_gap': f"[{gap_description}后]",
            'potential_cold_shoulder': f"[{gap_description}后，可能存在冷处理]",
            'topic_change': f"[{gap_description}后，话题切换]",
            'conflict_cooling': f"[{gap_description}后，冲突冷却期]"
        }
        
        return context_map.get(break_type, f"[{gap_description}后]")
    
    def _get_time_gap_seconds(self, msg1: Dict[str, Any], 
                               msg2: Dict[str, Any]) -> Optional[int]:
        """
        计算两条消息之间的时间间隔（秒）
        
        Args:
            msg1: 第一条消息
            msg2: 第二条消息
        
        Returns:
            时间间隔秒数，如果无法计算返回 None
        """
        ts1 = msg1.get('ts')
        ts2 = msg2.get('ts')
        
        if ts1 is None or ts2 is None:
            return None
        
        try:
            return int(ts2 - ts1)
        except (TypeError, ValueError):
            return None
    
    def get_stats(self) -> Dict[str, Any]:
        """获取处理统计"""
        return self.stats.copy()


def load_config(config_path: str) -> dict:
    """加载配置文件"""
    path = Path(config_path)
    if not path.exists():
        print(f"[WARN] 配置文件不存在: {config_path}，使用默认配置")
        return {}
    
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def load_timeline(input_path: str) -> List[Dict[str, Any]]:
    """加载时间轴数据"""
    messages = []
    with open(input_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                messages.append(json.loads(line))
    return messages


def save_timeline(messages: List[Dict[str, Any]], output_path: str):
    """保存时间轴数据"""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        for msg in messages:
            f.write(json.dumps(msg, ensure_ascii=False) + '\n')


def main():
    """命令行入口"""
    parser = argparse.ArgumentParser(description="时间轴后处理器")
    parser.add_argument('--input', '-i', 
                        default='timeline_out/enriched_full.jsonl',
                        help="输入文件路径")
    parser.add_argument('--output', '-o',
                        default='timeline_out/enriched_full_processed.jsonl',
                        help="输出文件路径")
    parser.add_argument('--config', '-c',
                        default='configs/timeline_postprocess.yaml',
                        help="配置文件路径")
    parser.add_argument('--no-merge', action='store_true',
                        help="禁用消息合并")
    parser.add_argument('--no-time-gap', action='store_true',
                        help="禁用时间间隔标记")
    
    args = parser.parse_args()
    
    # 检查输入文件
    if not Path(args.input).exists():
        print(f"[ERROR] 输入文件不存在: {args.input}")
        return
    
    # 加载配置
    config = load_config(args.config)
    
    # 命令行参数覆盖配置
    if args.no_merge:
        config.setdefault('merge', {})['enabled'] = False
    if args.no_time_gap:
        config.setdefault('time_gap', {})['enabled'] = False
    
    print("=== 时间轴后处理器 ===")
    print(f"输入: {args.input}")
    print(f"输出: {args.output}")
    print(f"消息合并: {'启用' if config.get('merge', {}).get('enabled', True) else '禁用'}")
    print(f"时间标记: {'启用' if config.get('time_gap', {}).get('enabled', True) else '禁用'}")
    print()
    
    # 加载数据
    print("[1/3] 加载时间轴数据...")
    messages = load_timeline(args.input)
    print(f"      加载 {len(messages)} 条消息")
    
    # 处理
    print("[2/3] 处理时间轴...")
    processor = TimelinePostprocessor(config)
    processed = processor.process(tqdm(messages, desc="处理中"))
    
    # 保存
    print("[3/3] 保存结果...")
    save_timeline(processed, args.output)
    
    # 打印统计
    stats = processor.get_stats()
    print(f"\n=== 处理完成 ===")
    print(f"输入消息: {stats['total_input']}")
    print(f"输出消息: {stats['total_output']}")
    print(f"合并组数: {stats['merge_groups']}")
    print(f"合并消息: {stats['messages_merged']}")
    print(f"时间标记: {stats['time_gaps_inserted']}")
    print(f"快速连发保留: {stats['rapid_fire_preserved']}")
    print(f"\n中断类型统计:")
    for break_type, count in stats['break_types'].items():
        if count > 0:
            print(f"  {break_type}: {count}")
    print(f"\n输出文件: {args.output}")


if __name__ == '__main__':
    main()
