# -*- coding: utf-8 -*-
"""
语音压缩器

压缩语音的 qwen_analysis 字段，保留关键推理
保留 punct_text 和 emotion_tags 原始字段

输入：artifacts/before_merge/voice/voice_merged_v3.jsonl
输出：artifacts/before_merge/voice/voice_compressed.jsonl
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass
import yaml


@dataclass
class VoiceConfig:
    """语音压缩配置"""
    enabled: bool = True
    target_length: int = 80
    preserve_fields: List[str] = None
    compress_fields: List[str] = None


class VoiceCompressor:
    """语音压缩器：保留转写+情绪，压缩分析"""
    
    def __init__(self, config_path: str = "configs/compression.yaml", model=None):
        self.config = self._load_config(config_path)
        self.voice_config = self._parse_voice_config()
        self.model = model  # 可选的 LLM 模型
        
        # 统计信息
        self.stats = {
            "total": 0,
            "compressed": 0,
            "with_analysis": 0,
            "analysis_removed": 0,
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
    
    def _parse_voice_config(self) -> VoiceConfig:
        """解析语音压缩配置"""
        cfg = self.config.get('voice', {})
        level = self.config.get('default_level', 'balanced')
        target_lengths = cfg.get('target_length', {})
        
        return VoiceConfig(
            enabled=cfg.get('enabled', True),
            target_length=target_lengths.get(level, 80),
            preserve_fields=cfg.get('preserve_fields', ['punct_text', 'emotion_tags']),
            compress_fields=cfg.get('compress_fields', ['qwen_analysis'])
        )
    
    def compress(self, voice_data: Dict) -> Dict:
        """
        压缩单条语音数据
        
        Args:
            voice_data: 语音数据（含 punct_text, sensevoice, voice_analysis 等）
        
        Returns:
            压缩后的数据
        """
        self.stats["total"] += 1
        
        # 提取原始字段
        punct_text = voice_data.get('punct_text', '')
        sensevoice = voice_data.get('sensevoice', {})
        emotion_tags = sensevoice.get('emotion_tags', [])
        voice_analysis = voice_data.get('voice_analysis', {})
        
        # 计算原始长度
        original_length = len(punct_text)
        if voice_analysis:
            original_length += len(str(voice_analysis))
            self.stats["with_analysis"] += 1
        
        # 压缩分析内容
        analysis_summary = None
        possible_intent = None
        possible_subtext = None
        
        if voice_analysis:
            emotion_desc = voice_analysis.get('emotion_desc', '')
            subtext = voice_analysis.get('subtext', '')
            
            # 判断分析是否有价值（不只是重复转写内容）
            if self._is_analysis_valuable(emotion_desc, punct_text):
                analysis_summary = self._compress_analysis(emotion_desc)
                possible_intent = self._extract_intent(punct_text, emotion_desc)
                possible_subtext = subtext if subtext else self._extract_subtext(emotion_desc)
            else:
                self.stats["analysis_removed"] += 1
        
        # 如果没有分析，尝试从转写推断意图
        if not possible_intent:
            possible_intent = self._infer_intent_from_text(punct_text)
        
        # 计算压缩后长度
        compressed_length = len(punct_text)
        if analysis_summary:
            compressed_length += len(analysis_summary)
        
        compression_ratio = original_length / compressed_length if compressed_length > 0 else 1.0
        
        self.stats["total_original_length"] += original_length
        self.stats["total_compressed_length"] += compressed_length
        self.stats["compressed"] += 1
        
        return {
            "file": voice_data.get('file'),
            "schema_version": "voice_compressed_v1",
            # 保留原始字段
            "punct_text": punct_text,
            "emotion_tags": emotion_tags if emotion_tags else None,
            # 压缩后的字段
            "analysis_summary": analysis_summary,
            "possible_intent": possible_intent,
            "possible_subtext": possible_subtext,
            # 元数据
            "compression_ratio": round(compression_ratio, 2),
            "original_length": original_length,
            "compressed_length": compressed_length,
            "trigger_reasons": voice_data.get('trigger_reasons')
        }
    
    def _is_analysis_valuable(self, emotion_desc: str, punct_text: str) -> bool:
        """
        判断分析是否有价值（不只是重复转写内容）
        
        Returns:
            True: 分析有价值，应保留
            False: 分析只是重复，可删除
        """
        if not emotion_desc:
            return False
        
        # 如果分析太短，可能没有价值
        if len(emotion_desc) < 20:
            return False
        
        # 如果分析只是说"平静"、"中性"等，价值不大
        low_value_patterns = [
            r'^语气.*平静',
            r'^没有明显.*情绪',
            r'^情绪.*中性',
            r'^语气.*中性'
        ]
        for pattern in low_value_patterns:
            if re.match(pattern, emotion_desc):
                return False
        
        # 如果分析包含具体的情感洞察，有价值
        valuable_keywords = [
            '自信', '自豪', '歉意', '内疚', '焦虑', '担心', '开心', '兴奋',
            '失望', '沮丧', '愤怒', '不满', '疑惑', '困惑', '期待', '渴望',
            '自嘲', '幽默', '讽刺', '无奈', '委屈', '撒娇'
        ]
        if any(kw in emotion_desc for kw in valuable_keywords):
            return True
        
        # 如果分析长度足够且不是简单重复，保留
        if len(emotion_desc) > 50:
            return True
        
        return False
    
    def _compress_analysis(self, emotion_desc: str) -> str:
        """压缩情感分析描述"""
        target_length = self.voice_config.target_length
        
        # 移除模板文字
        emotion_desc = re.sub(r'根据语音内容，?', '', emotion_desc)
        emotion_desc = re.sub(r'可以感受到', '', emotion_desc)
        emotion_desc = re.sub(r'整体上，?', '', emotion_desc)
        emotion_desc = re.sub(r'总体上，?', '', emotion_desc)
        
        # 提取关键情感词
        sentences = re.split(r'[。，]', emotion_desc)
        key_parts = []
        
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence or len(sentence) < 5:
                continue
            
            # 保留包含情感关键词的句子
            emotion_keywords = [
                '自信', '自豪', '歉意', '内疚', '焦虑', '担心', '开心', '兴奋',
                '失望', '沮丧', '愤怒', '不满', '疑惑', '困惑', '期待', '渴望',
                '自嘲', '幽默', '讽刺', '无奈', '委屈', '撒娇', '真诚', '诚恳',
                '积极', '乐观', '消极', '悲观'
            ]
            if any(kw in sentence for kw in emotion_keywords):
                key_parts.append(sentence)
        
        if key_parts:
            summary = '，'.join(key_parts[:3])  # 最多保留3个关键点
        else:
            # 如果没有找到关键词，截取前面部分
            summary = emotion_desc[:target_length]
        
        # 确保不超过目标长度
        if len(summary) > target_length:
            summary = summary[:target_length-3] + '...'
        
        return summary
    
    def _extract_intent(self, punct_text: str, emotion_desc: str) -> str:
        """提取可能的意图"""
        combined = punct_text + ' ' + emotion_desc
        
        intent_patterns = {
            '解释说明': ['因为', '所以', '是因为', '原因是', '解释'],
            '分享经历': ['我', '经历', '那次', '有一次', '记得'],
            '表达观点': ['我觉得', '我认为', '我想', '应该', '不应该'],
            '询问': ['吗？', '呢？', '什么', '为什么', '怎么'],
            '抱怨': ['不满', '抱怨', '烦', '讨厌'],
            '道歉': ['对不起', '抱歉', '不好意思', '伤到'],
            '自我介绍': ['我这个人', '我是', '我一般']
        }
        
        for intent, keywords in intent_patterns.items():
            if any(kw in combined for kw in keywords):
                return intent
        
        return '表达'
    
    def _extract_subtext(self, emotion_desc: str) -> Optional[str]:
        """从情感描述中提取潜台词"""
        # 查找潜台词相关的描述
        subtext_patterns = [
            r'显示出.*?的(.*?)(?:。|$)',
            r'表现出.*?的(.*?)(?:。|$)',
            r'传达出(.*?)(?:。|$)',
            r'说明.*?(.*?)(?:。|$)'
        ]
        
        for pattern in subtext_patterns:
            match = re.search(pattern, emotion_desc)
            if match:
                subtext = match.group(1).strip()
                if len(subtext) > 5 and len(subtext) < 50:
                    return subtext
        
        return None
    
    def _infer_intent_from_text(self, punct_text: str) -> str:
        """从转写文本推断意图"""
        if '？' in punct_text:
            return '询问'
        if '因为' in punct_text or '所以' in punct_text:
            return '解释说明'
        if '我觉得' in punct_text or '我认为' in punct_text:
            return '表达观点'
        if '我' in punct_text and ('经历' in punct_text or '那次' in punct_text):
            return '分享经历'
        
        return '表达'
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        stats = self.stats.copy()
        if stats["total_compressed_length"] > 0:
            stats["avg_compression_ratio"] = round(
                stats["total_original_length"] / stats["total_compressed_length"], 2
            )
        return stats


def load_voice_data(voice_path: str) -> List[Dict]:
    """加载语音数据"""
    voices = []
    with open(voice_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                voices.append(json.loads(line))
    return voices


def save_compressed(voices: List[Dict], output_path: str):
    """保存压缩结果"""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        for voice in voices:
            f.write(json.dumps(voice, ensure_ascii=False) + '\n')
