# -*- coding: utf-8 -*-
"""
表情包压缩器

将表情包的 caption 和 ocr_text 压缩为语用功能/意图标签
支持字典化压缩（重复表情包使用引用）

输入：artifacts/before_merge/sticker/sticker_caption_v1.jsonl
输出：artifacts/before_merge/sticker/sticker_compressed.jsonl
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
import yaml


@dataclass
class StickerConfig:
    """表情包压缩配置"""
    enabled: bool = True
    target_length: int = 50
    output_format: str = "[表情包: {intent}:{confidence}] {text_part}"
    lexicon_enabled: bool = True
    lexicon_path: str = "artifacts/dictionaries/sticker_lexicon.jsonl"
    min_occurrences_for_ref: int = 2
    intent_map_path: str = "configs/sticker_intent_map.yaml"
    llm_fallback_enabled: bool = True
    llm_confidence_threshold: float = 0.6


class IntentMapper:
    """意图映射器：从表情包描述映射到意图标签"""
    
    def __init__(self, config_path: str = "configs/sticker_intent_map.yaml"):
        self.config = self._load_config(config_path)
        self.high_confidence = self._parse_mappings('high_confidence')
        self.medium_confidence = self._parse_mappings('medium_confidence')
        self.low_confidence = self._parse_mappings('low_confidence')
        self.ocr_mappings = self._parse_ocr_mappings()
        self.fallback = self.config.get('fallback', {})
    
    def _load_config(self, config_path: str) -> dict:
        """加载意图映射配置"""
        path = Path(config_path)
        if not path.exists():
            print(f"[WARN] 意图映射配置不存在: {config_path}")
            return {}
        
        with open(path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    
    def _parse_mappings(self, level: str) -> List[Tuple[List[str], str, float]]:
        """解析指定级别的映射"""
        mappings = []
        level_config = self.config.get(level, {})
        
        for category, data in level_config.items():
            keywords = data.get('keywords', [])
            intent = data.get('intent', category)
            confidence = data.get('confidence', 0.5)
            mappings.append((keywords, intent, confidence))
        
        return mappings
    
    def _parse_ocr_mappings(self) -> List[Tuple[List[str], str, float]]:
        """解析 OCR 文字映射"""
        mappings = []
        ocr_config = self.config.get('ocr_text_mapping', [])
        
        for item in ocr_config:
            patterns = item.get('patterns', [])
            intent = item.get('intent', '')
            confidence = item.get('confidence', 0.8)
            mappings.append((patterns, intent, confidence))
        
        return mappings
    
    def map_intent(self, caption: str, ocr_text: str) -> Tuple[str, float]:
        """
        从描述中映射到意图标签
        
        优先级：
        1. OCR 文字匹配（最高优先级）
        2. 高置信度关键词匹配
        3. 中置信度关键词匹配
        4. 低置信度关键词匹配
        5. 兜底默认值
        
        Returns:
            (intent_label, confidence)
        """
        # 1. 优先从 OCR 文字匹配
        if ocr_text:
            for patterns, intent, confidence in self.ocr_mappings:
                for pattern in patterns:
                    if pattern in ocr_text:
                        return intent, confidence
        
        # 2-4. 从 caption 关键词匹配
        caption_lower = caption.lower()
        
        for mappings in [self.high_confidence, self.medium_confidence, self.low_confidence]:
            for keywords, intent, confidence in mappings:
                for keyword in keywords:
                    if keyword in caption_lower or keyword in caption:
                        return intent, confidence
        
        # 5. 兜底
        default_intent = self.fallback.get('default_intent', '表达情绪')
        default_confidence = self.fallback.get('default_confidence', 0.3)
        return default_intent, default_confidence


class StickerCompressor:
    """表情包压缩器：语用功能映射 + 字典化"""
    
    def __init__(self, config_path: str = "configs/compression.yaml"):
        self.config = self._load_config(config_path)
        self.sticker_config = self._parse_sticker_config()
        self.intent_mapper = IntentMapper(self.sticker_config.intent_map_path)
        self.lexicon: Dict[str, Dict] = {}  # file_sha256 -> summary_data
        self.occurrence_count: Dict[str, int] = {}  # file_sha256 -> count
        
        # 统计信息
        self.stats = {
            "total": 0,
            "compressed": 0,
            "from_lexicon": 0,
            "llm_fallback": 0,
            "avg_compression_ratio": 0.0
        }
    
    def _load_config(self, config_path: str) -> dict:
        """加载配置文件"""
        path = Path(config_path)
        if not path.exists():
            print(f"[WARN] 配置文件不存在: {config_path}")
            return {}
        
        with open(path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    
    def _parse_sticker_config(self) -> StickerConfig:
        """解析表情包压缩配置"""
        cfg = self.config.get('sticker', {})
        level = self.config.get('default_level', 'balanced')
        target_lengths = cfg.get('target_length', {})
        
        lexicon_cfg = cfg.get('lexicon', {})
        
        return StickerConfig(
            enabled=cfg.get('enabled', True),
            target_length=target_lengths.get(level, 50),
            output_format=cfg.get('output_format', "[表情包: {intent}:{confidence}] {text_part}"),
            lexicon_enabled=lexicon_cfg.get('enabled', True),
            lexicon_path=lexicon_cfg.get('output_path', "artifacts/dictionaries/sticker_lexicon.jsonl"),
            min_occurrences_for_ref=lexicon_cfg.get('min_occurrences_for_ref', 2),
            intent_map_path=cfg.get('intent_map_path', "configs/sticker_intent_map.yaml"),
            llm_fallback_enabled=cfg.get('llm_fallback', {}).get('enabled', True),
            llm_confidence_threshold=cfg.get('llm_fallback', {}).get('confidence_threshold', 0.6)
        )
    
    def compress(self, sticker_data: Dict, use_lexicon_ref: bool = True) -> Dict:
        """
        压缩单个表情包
        
        Args:
            sticker_data: 表情包数据
            use_lexicon_ref: 是否使用字典引用（重复表情包）
        
        Returns:
            压缩后的数据，包含：
            - sticker_id: file_sha256
            - sticker_summary: 压缩后的摘要
            - is_animated: 是否动画
            - intent_confidence: 意图置信度
            - compression_ratio: 压缩比
        """
        self.stats["total"] += 1
        
        file_sha256 = sticker_data.get('file_sha256', '')
        caption = sticker_data.get('caption', '')
        ocr_text = sticker_data.get('ocr_text', '')
        is_animated = sticker_data.get('is_animated', False)
        
        # 更新出现次数
        self.occurrence_count[file_sha256] = self.occurrence_count.get(file_sha256, 0) + 1
        
        # 检查是否可以使用字典引用
        if use_lexicon_ref and file_sha256 in self.lexicon:
            if self.occurrence_count[file_sha256] >= self.sticker_config.min_occurrences_for_ref:
                self.stats["from_lexicon"] += 1
                return self._create_lexicon_ref(sticker_data, self.lexicon[file_sha256])
        
        # 映射意图
        intent, confidence = self.intent_mapper.map_intent(caption, ocr_text)
        
        # 构建摘要
        sticker_summary = self._build_summary(intent, confidence, ocr_text, is_animated, caption)
        
        # 计算压缩比
        original_length = len(caption) + len(ocr_text)
        compressed_length = len(sticker_summary)
        compression_ratio = original_length / compressed_length if compressed_length > 0 else 1.0
        
        # 创建压缩结果
        result = {
            "msg_uid": sticker_data.get('msg_uid'),
            "schema_version": "sticker_compressed_v1",
            "sticker_id": file_sha256,
            "sticker_summary": sticker_summary,
            "is_animated": is_animated,
            "intent": intent,
            "intent_confidence": confidence,
            "compression_ratio": round(compression_ratio, 2),
            "original_length": original_length,
            "compressed_length": compressed_length,
            # 保留原始字段
            "ts": sticker_data.get('ts'),
            "speaker": sticker_data.get('speaker'),
            "content_type": sticker_data.get('content_type'),
            "file_sha256": file_sha256
        }
        
        # 添加到字典
        if file_sha256 and file_sha256 not in self.lexicon:
            self.lexicon[file_sha256] = {
                "sticker_id": file_sha256,
                "sticker_summary": sticker_summary,
                "intent": intent,
                "intent_confidence": confidence,
                "is_animated": is_animated,
                "first_seen_ts": sticker_data.get('ts'),
                "occurrence_count": 1
            }
        elif file_sha256 in self.lexicon:
            self.lexicon[file_sha256]["occurrence_count"] += 1
        
        self.stats["compressed"] += 1
        return result
    
    def _build_summary(self, intent: str, confidence: float, 
                       ocr_text: str, is_animated: bool,
                       caption: str = "") -> str:
        """
        构建压缩摘要
        
        策略：
        - 如果意图是明确的情绪标签（非兜底），直接用 [意图]
        - 如果意图是模糊的兜底（"表达情绪"），保留压缩后的视觉描述
        """
        # 兜底意图列表
        fallback_intents = ["表达情绪", "未知", "其他"]
        
        if intent in fallback_intents:
            # 兜底情况：保留压缩后的视觉描述
            visual_desc = self._compress_caption(caption)
            if ocr_text:
                return f"[表情包: {visual_desc}] (文字: {ocr_text[:20]})"
            return f"[表情包: {visual_desc}]"
        else:
            # 明确的情绪/意图标签
            if ocr_text:
                return f"[{intent}] (文字: {ocr_text[:20]})"
            return f"[{intent}]"
    
    def _compress_caption(self, caption: str) -> str:
        """
        压缩 caption，提取核心视觉特征
        
        输入: [表情包: 绿色青蛙戴着墨镜，露出大笑，显得非常自信和酷炫。]
        输出: 绿色青蛙戴墨镜大笑
        """
        if not caption:
            return "表情包"
        
        # 移除 [表情包: ] 前缀
        text = caption
        if text.startswith("[表情包:"):
            text = text[5:].strip()
            if text.endswith("]"):
                text = text[:-1].strip()
        elif text.startswith("[表情包："):
            text = text[6:].strip()
            if text.endswith("]"):
                text = text[:-1].strip()
        
        # 移除冗余词汇
        remove_words = [
            "显得", "非常", "十分", "特别", "似乎", "好像",
            "的样子", "的表情", "的动作", "的姿态",
            "表示", "表达", "传达", "展示",
            "一个", "一只", "一位",
        ]
        for word in remove_words:
            text = text.replace(word, "")
        
        # 移除多余标点和空格
        text = text.replace("，", "").replace("。", "").replace("、", "")
        text = " ".join(text.split())
        
        # 限制长度
        if len(text) > 30:
            text = text[:30]
        
        return text.strip() or "表情包"
    
    def _create_lexicon_ref(self, sticker_data: Dict, lexicon_entry: Dict) -> Dict:
        """创建字典引用"""
        return {
            "msg_uid": sticker_data.get('msg_uid'),
            "schema_version": "sticker_compressed_v1",
            "sticker_id": sticker_data.get('file_sha256'),
            "sticker_summary": f"[REF:{sticker_data.get('file_sha256')[:8]}]",
            "is_lexicon_ref": True,
            "ref_summary": lexicon_entry.get('sticker_summary'),
            "intent": lexicon_entry.get('intent'),
            "intent_confidence": lexicon_entry.get('intent_confidence'),
            "is_animated": lexicon_entry.get('is_animated'),
            "compression_ratio": 10.0,  # 引用压缩比很高
            "original_length": len(sticker_data.get('caption', '')) + len(sticker_data.get('ocr_text', '')),
            "compressed_length": 15,  # REF 标记长度
            "ts": sticker_data.get('ts'),
            "speaker": sticker_data.get('speaker'),
            "content_type": sticker_data.get('content_type'),
            "file_sha256": sticker_data.get('file_sha256')
        }
    
    def build_lexicon(self, stickers: List[Dict]) -> Dict[str, Dict]:
        """
        构建表情包字典
        
        Args:
            stickers: 表情包数据列表
        
        Returns:
            字典：file_sha256 -> summary_data
        """
        # 第一遍：统计出现次数
        for sticker in stickers:
            file_sha256 = sticker.get('file_sha256', '')
            if file_sha256:
                self.occurrence_count[file_sha256] = self.occurrence_count.get(file_sha256, 0) + 1
        
        # 第二遍：压缩并构建字典
        for sticker in stickers:
            self.compress(sticker, use_lexicon_ref=False)
        
        return self.lexicon
    
    def save_lexicon(self, output_path: Optional[str] = None):
        """保存字典到文件"""
        path = Path(output_path or self.sticker_config.lexicon_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(path, 'w', encoding='utf-8') as f:
            for entry in self.lexicon.values():
                f.write(json.dumps(entry, ensure_ascii=False) + '\n')
        
        print(f"[INFO] 字典已保存: {path} ({len(self.lexicon)} 条)")
    
    def load_lexicon(self, input_path: Optional[str] = None):
        """从文件加载字典"""
        path = Path(input_path or self.sticker_config.lexicon_path)
        if not path.exists():
            print(f"[WARN] 字典文件不存在: {path}")
            return
        
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    entry = json.loads(line)
                    sticker_id = entry.get('sticker_id')
                    if sticker_id:
                        self.lexicon[sticker_id] = entry
        
        print(f"[INFO] 字典已加载: {path} ({len(self.lexicon)} 条)")
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        if self.stats["compressed"] > 0:
            # 计算平均压缩比（简化版）
            pass
        return self.stats.copy()


def load_stickers(input_path: str) -> List[Dict]:
    """加载表情包数据"""
    stickers = []
    with open(input_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                stickers.append(json.loads(line))
    return stickers


def save_compressed(stickers: List[Dict], output_path: str):
    """保存压缩结果"""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        for sticker in stickers:
            f.write(json.dumps(sticker, ensure_ascii=False) + '\n')
