# -*- coding: utf-8 -*-
"""
视频压缩器

将视频的多帧描述和转写合并为连贯摘要
支持 5-16 帧的自适应合并策略

输入：
  - artifacts/before_merge/video/video_caption_v1.jsonl
  - artifacts/before_merge/video/video_transcribe_v1.jsonl
输出：artifacts/before_merge/video/video_compressed.jsonl
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import yaml


@dataclass
class VideoConfig:
    """视频压缩配置"""
    enabled: bool = True
    max_frames: int = 16
    target_length: int = 150
    merge_strategy: Dict = None


class VideoCompressor:
    """视频压缩器：多帧描述合并 + 规则压缩"""
    
    def __init__(self, config_path: str = "configs/compression.yaml", model=None):
        self.config = self._load_config(config_path)
        self.video_config = self._parse_video_config()
        self.model = model  # 可选的 LLM 模型
        
        # 统计信息
        self.stats = {
            "total": 0,
            "compressed": 0,
            "with_transcription": 0,
            "avg_frames": 0.0,
            "total_frames": 0,
            "avg_compression_ratio": 0.0,
            "total_original_length": 0,
            "total_compressed_length": 0
        }
    
    def _load_config(self, config_path: str) -> dict:
        """加载配置文件"""
        path = Path(config_path)
        if not path.exists():
            print(f"[WARN] 配置文件不存在: {config_path}")
            return {}
        
        with open(path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    
    def _parse_video_config(self) -> VideoConfig:
        """解析视频压缩配置"""
        cfg = self.config.get('video', {})
        level = self.config.get('default_level', 'balanced')
        target_lengths = cfg.get('target_length', {})
        
        return VideoConfig(
            enabled=cfg.get('enabled', True),
            max_frames=cfg.get('max_frames', 16),
            target_length=target_lengths.get(level, 120),
            merge_strategy=cfg.get('merge_strategy', {
                'frames_5_or_less': 'sequential',
                'frames_6_to_10': 'segmented',
                'frames_11_to_16': 'key_changes'
            })
        )
    
    def compress(self, caption_data: Dict, transcribe_data: Optional[Dict] = None) -> Dict:
        """
        压缩单个视频
        
        Args:
            caption_data: 视频 caption 数据（含 keyframe_captions 和 video_understanding）
            transcribe_data: 视频转写数据（可选）
        
        Returns:
            压缩后的数据
        """
        self.stats["total"] += 1
        
        # 提取关键帧描述（兼容新旧格式）
        keyframe_captions = caption_data.get('keyframe_captions', [])
        if not keyframe_captions:
            # 新格式：keyframes 字段包含 caption
            keyframe_captions = caption_data.get('keyframes', [])
        
        video_understanding = caption_data.get('video_understanding', {})
        num_frames = len(keyframe_captions)
        
        self.stats["total_frames"] += num_frames
        
        # 提取转写和情绪
        transcription = ''
        emotion_tags = []
        if transcribe_data:
            trans = transcribe_data.get('transcription', {})
            transcription = trans.get('punct_text', '') or trans.get('raw_text', '')
            emotion = transcribe_data.get('emotion', {})
            sensevoice = emotion.get('sensevoice', {})
            emotion_tags = sensevoice.get('emotion_tags', [])
            if transcription:
                self.stats["with_transcription"] += 1
        
        # 选择合并策略
        strategy = self._adaptive_merge_strategy(num_frames)
        
        # 合并关键帧描述
        merged_frames = self._merge_keyframes(keyframe_captions, strategy)
        
        # 生成视频摘要
        video_summary = self._generate_summary(
            merged_frames, 
            video_understanding,
            transcription,
            emotion_tags
        )
        
        # 提取氛围和意图
        atmosphere = self._extract_atmosphere(video_understanding, emotion_tags)
        intent = self._extract_intent(video_understanding)
        
        # 计算压缩比
        original_length = sum(len(kf.get('caption', '')) for kf in keyframe_captions)
        original_length += len(video_understanding.get('summary', ''))
        original_length += len(transcription)
        compressed_length = len(video_summary)
        compression_ratio = original_length / compressed_length if compressed_length > 0 else 1.0
        
        self.stats["total_original_length"] += original_length
        self.stats["total_compressed_length"] += compressed_length
        self.stats["compressed"] += 1
        
        return {
            "msg_uid": caption_data.get('msg_uid'),
            "schema_version": "video_compressed_v1",
            "video_summary": video_summary,
            "transcription": transcription if transcription else None,
            "emotion_tags": emotion_tags if emotion_tags else None,
            "atmosphere": atmosphere,
            "intent": intent,
            "num_frames": num_frames,
            "merge_strategy": strategy,
            "compression_ratio": round(compression_ratio, 2),
            "original_length": original_length,
            "compressed_length": compressed_length,
            # 保留原始字段
            "media_path": caption_data.get('media_path'),
            "content_type": caption_data.get('triage', {}).get('content_type', 'TYPE_C_NORMAL'),
            "metadata": caption_data.get('metadata')
        }
    
    def _adaptive_merge_strategy(self, num_frames: int) -> str:
        """
        根据帧数选择合并策略
        
        Returns:
            'sequential': 逐帧描述（5帧及以下）
            'segmented': 分段描述（6-10帧）
            'key_changes': 关键变化（11-16帧）
        """
        strategies = self.video_config.merge_strategy
        
        if num_frames <= 5:
            return strategies.get('frames_5_or_less', 'sequential')
        elif num_frames <= 10:
            return strategies.get('frames_6_to_10', 'segmented')
        else:
            return strategies.get('frames_11_to_16', 'key_changes')
    
    def _merge_keyframes(self, keyframe_captions: List[Dict], strategy: str) -> str:
        """
        合并关键帧描述
        
        Args:
            keyframe_captions: 关键帧描述列表
            strategy: 合并策略
        
        Returns:
            合并后的描述
        """
        if not keyframe_captions:
            return "无关键帧描述"
        
        # 提取每帧的核心内容
        frame_summaries = []
        for kf in keyframe_captions:
            caption = kf.get('caption', '')
            timestamp = kf.get('timestamp_sec', 0)
            summary = self._extract_frame_core(caption)
            frame_summaries.append({
                'timestamp': timestamp,
                'summary': summary,
                'original': caption
            })
        
        if strategy == 'sequential':
            return self._merge_sequential(frame_summaries)
        elif strategy == 'segmented':
            return self._merge_segmented(frame_summaries)
        else:  # key_changes
            return self._merge_key_changes(frame_summaries)

    def _extract_frame_core(self, caption: str) -> str:
        """从单帧描述中提取核心内容"""
        # 移除模板文字
        caption = re.sub(r'这张图片展示了|这是一张|图片中|照片中|以下是详细的描述：?', '', caption)
        caption = re.sub(r'\*\*.*?\*\*', '', caption)  # 移除 markdown 加粗
        caption = re.sub(r'\d+\.\s*', '', caption)  # 移除编号
        caption = re.sub(r'- \*\*.*?\*\*：', '', caption)  # 移除列表标题
        
        # 提取第一句有意义的描述
        sentences = re.split(r'[。\n]', caption)
        core_parts = []
        
        for sentence in sentences:
            sentence = sentence.strip()
            # 跳过无意义的句子
            if not sentence or len(sentence) < 5:
                continue
            if '无法辨认' in sentence or '不清晰' in sentence:
                continue
            if '没有明显的' in sentence or '没有出现' in sentence:
                continue
            
            # 清理句子
            sentence = re.sub(r'^\s*[-·•]\s*', '', sentence)
            core_parts.append(sentence)
            
            # 只取前两句
            if len(core_parts) >= 2:
                break
        
        return '，'.join(core_parts) if core_parts else caption[:50]
    
    def _merge_sequential(self, frame_summaries: List[Dict]) -> str:
        """
        逐帧描述合并（5帧及以下）
        保留每帧的时间顺序
        """
        parts = []
        prev_summary = ""
        
        for i, fs in enumerate(frame_summaries):
            summary = fs['summary']
            
            # 去除与前一帧重复的内容
            if prev_summary and self._is_similar(summary, prev_summary):
                continue
            
            # 添加时间标记
            if i == 0:
                parts.append(f"开始：{summary}")
            elif i == len(frame_summaries) - 1:
                parts.append(f"结束：{summary}")
            else:
                parts.append(summary)
            
            prev_summary = summary
        
        return '→'.join(parts)
    
    def _merge_segmented(self, frame_summaries: List[Dict]) -> str:
        """
        分段描述合并（6-10帧）
        分为开始/中间/结尾三段
        """
        n = len(frame_summaries)
        
        # 分段
        start_frames = frame_summaries[:2]
        middle_frames = frame_summaries[2:-2] if n > 4 else []
        end_frames = frame_summaries[-2:]
        
        parts = []
        
        # 开始段
        start_summary = self._summarize_segment(start_frames)
        parts.append(f"开始：{start_summary}")
        
        # 中间段（提取关键变化）
        if middle_frames:
            middle_summary = self._summarize_segment(middle_frames)
            if middle_summary and middle_summary != start_summary:
                parts.append(f"过程：{middle_summary}")
        
        # 结束段
        end_summary = self._summarize_segment(end_frames)
        if end_summary != start_summary:
            parts.append(f"结束：{end_summary}")
        
        return '→'.join(parts)
    
    def _merge_key_changes(self, frame_summaries: List[Dict]) -> str:
        """
        关键变化合并（11-16帧）
        只保留场景变化的关键帧
        """
        if not frame_summaries:
            return ""
        
        key_frames = [frame_summaries[0]]  # 始终保留第一帧
        prev_summary = frame_summaries[0]['summary']
        
        for fs in frame_summaries[1:-1]:
            summary = fs['summary']
            # 只保留与前一个关键帧不同的帧
            if not self._is_similar(summary, prev_summary):
                key_frames.append(fs)
                prev_summary = summary
        
        # 始终保留最后一帧
        if len(frame_summaries) > 1:
            key_frames.append(frame_summaries[-1])
        
        # 合并关键帧
        parts = []
        for i, kf in enumerate(key_frames):
            if i == 0:
                parts.append(f"开始：{kf['summary']}")
            elif i == len(key_frames) - 1:
                parts.append(f"结束：{kf['summary']}")
            else:
                parts.append(f"变化：{kf['summary']}")
        
        return '→'.join(parts)
    
    def _summarize_segment(self, frames: List[Dict]) -> str:
        """合并一个段落的帧描述"""
        if not frames:
            return ""
        
        # 去重并合并
        unique_summaries = []
        for fs in frames:
            summary = fs['summary']
            if not any(self._is_similar(summary, us) for us in unique_summaries):
                unique_summaries.append(summary)
        
        return '，'.join(unique_summaries[:2])  # 最多保留2个
    
    def _is_similar(self, text1: str, text2: str, threshold: float = 0.6) -> bool:
        """判断两段文字是否相似（简单的词重叠判断）"""
        if not text1 or not text2:
            return False
        
        words1 = set(text1)
        words2 = set(text2)
        
        if not words1 or not words2:
            return False
        
        overlap = len(words1 & words2)
        similarity = overlap / min(len(words1), len(words2))
        
        return similarity > threshold
    
    def _generate_summary(self, merged_frames: str, video_understanding: Dict,
                          transcription: str, emotion_tags: List[str]) -> str:
        """
        生成视频摘要
        
        优先使用 video_understanding 的完整摘要，保留动作描述
        """
        target_length = self.video_config.target_length
        parts = []
        
        # 1. 优先使用视频理解的完整摘要（包含动作变化）
        vu_summary = video_understanding.get('summary', '')
        if vu_summary:
            # 清理 markdown 格式，但保留完整内容
            vu_clean = self._clean_vu_summary(vu_summary)
            if vu_clean:
                parts.append(vu_clean)
        
        # 2. 如果视频理解为空或太短，使用合并的帧描述
        if not parts or len(parts[0]) < 50:
            parts = [merged_frames]
        
        # 3. 添加转写内容
        if transcription and len(transcription) > 2:
            parts.append(f"(语音: {transcription})")
        
        # 4. 添加情绪标签
        if emotion_tags:
            parts.append(f"[情绪: {','.join(emotion_tags)}]")
        
        # 合并（不截断，保留完整语义）
        summary = ' '.join(parts)
        
        # 仅当 target_length > 0 时才截断（默认为 0，不截断）
        if target_length > 0 and len(summary) > target_length:
            summary = summary[:target_length-3] + '...'
        
        return summary if summary else '视频内容'
    
    def _clean_vu_summary(self, vu_summary: str) -> str:
        """
        从视频理解摘要中提取核心总结部分
        
        VLM 生成的摘要通常包含：
        1. 总结部分（需要保留）：场景描述、主体特征、整体氛围
        2. 帧描述部分（不需要）：帧1、帧2... 或 第一帧、第二帧... 的逐帧描述
        
        只保留总结部分，去掉逐帧描述
        """
        # 在这些关键词之前截断，只保留总结部分
        cut_patterns = [
            r'\s*主体的?变化.*',           # "主体变化" 或 "主体的变化"
            r'\s*从第一帧到.*',             # "从第一帧到最后一帧的变化"
            r'\s*帧\s*1[：:].+',            # "帧1：..."
            r'\s*第一帧[：:].+',            # "第一帧：..."
            r'\s*\*\*帧\s*1\*\*.+',         # "**帧1**..."
            r'\s*1\.\s*第一帧.+',           # "1. 第一帧..."
            r'\s*可能发生的动作或事件.*',   # 推测部分
        ]
        
        for pattern in cut_patterns:
            vu_summary = re.split(pattern, vu_summary, maxsplit=1, flags=re.IGNORECASE)[0]
        
        # 移除 markdown 标题标记
        vu_summary = re.sub(r'###?\s*\d*\.?\s*', '', vu_summary)
        # 移除加粗标记
        vu_summary = re.sub(r'\*\*([^*]+)\*\*', r'\1', vu_summary)
        # 移除列表标记
        vu_summary = re.sub(r'^[-·•]\s*', '', vu_summary, flags=re.MULTILINE)
        # 合并多个换行为单个空格
        vu_summary = re.sub(r'\n+', ' ', vu_summary)
        # 清理多余空格
        vu_summary = re.sub(r'\s+', ' ', vu_summary).strip()
        
        return vu_summary
    
    def _extract_atmosphere(self, video_understanding: Dict, 
                            emotion_tags: List[str]) -> str:
        """提取视频氛围"""
        # 从情绪标签推断
        if emotion_tags:
            emotion_map = {
                'happy': '欢乐',
                'sad': '悲伤',
                'angry': '愤怒',
                'fear': '紧张',
                'surprise': '惊喜',
                'neutral': '平静'
            }
            for tag in emotion_tags:
                tag_lower = tag.lower()
                for key, value in emotion_map.items():
                    if key in tag_lower:
                        return value
        
        # 从视频理解推断
        summary = video_understanding.get('summary', '')
        atmosphere_keywords = {
            '温馨': ['温馨', '温暖', '舒适', '惬意', '美好', '甜蜜', '宁静'],
            '欢乐': ['开心', '快乐', '高兴', '愉快', '欢乐', '笑', '幸福', '活跃'],
            '严肃': ['严肃', '正式', '庄重', '认真'],
            '紧张': ['紧张', '焦虑', '担心', '害怕', '激烈'],
            '悲伤': ['悲伤', '难过', '伤心', '哭'],
            '平静': ['平静', '安静', '宁静', '淡然', '放松']
        }
        
        for atmosphere, keywords in atmosphere_keywords.items():
            if any(kw in summary for kw in keywords):
                return atmosphere
        
        return '中性'
    
    def _extract_intent(self, video_understanding: Dict) -> str:
        """提取发送意图"""
        summary = video_understanding.get('summary', '')
        
        intent_keywords = {
            '分享日常': ['分享', '记录', '日常', '生活', '展示'],
            '展示成果': ['展示', '成果', '完成', '做好', '表演'],
            '记录瞬间': ['记录', '留念', '纪念', '捕捉'],
            '娱乐搞笑': ['搞笑', '有趣', '好玩', '可爱'],
            '教程演示': ['教程', '演示', '如何', '怎么']
        }
        
        for intent, keywords in intent_keywords.items():
            if any(kw in summary for kw in keywords):
                return intent
        
        return '分享'
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        stats = self.stats.copy()
        if stats["total"] > 0:
            stats["avg_frames"] = round(stats["total_frames"] / stats["total"], 1)
        if stats["total_compressed_length"] > 0:
            stats["avg_compression_ratio"] = round(
                stats["total_original_length"] / stats["total_compressed_length"], 2
            )
        return stats


def load_video_data(caption_path: str, transcribe_path: str) -> Tuple[List[Dict], Dict[str, Dict]]:
    """
    加载视频数据
    
    Returns:
        (caption_list, transcribe_dict)
        transcribe_dict: msg_uid -> transcribe_data
    """
    captions = []
    with open(caption_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                captions.append(json.loads(line))
    
    transcribe_dict = {}
    transcribe_path = Path(transcribe_path)
    if transcribe_path.exists():
        with open(transcribe_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    data = json.loads(line)
                    msg_uid = data.get('msg_uid')
                    if msg_uid:
                        transcribe_dict[msg_uid] = data
    
    return captions, transcribe_dict


def save_compressed(videos: List[Dict], output_path: str):
    """保存压缩结果"""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        for video in videos:
            f.write(json.dumps(video, ensure_ascii=False) + '\n')
