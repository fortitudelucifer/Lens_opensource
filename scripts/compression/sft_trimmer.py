# -*- coding: utf-8 -*-
"""
SFT 字段精简器 - L1/L2 训练数据生成

功能：
- 将时间轴数据转换为精简的 SFT 训练文件
- 移除处理元数据（如 *_path, *_score, *_confidence 等）
- 保留语义核心字段（text_raw, summary, intent, emotion 等）
- 支持 L1（本地训练）和 L2（云端训练）两种模式
- 智能字段过滤（去重、去噪、去冗余）

L1 vs L2 模式：
L1（本地训练）：
  - 输入：enriched_full_processed.jsonl（后处理版本）或 enriched_full.jsonl
  - 输出：enriched_full_anonymized_l1_sft.jsonl
  - 特点：从原始数据直接精简，不进行匿名化
  - 用途：本地训练，数据不出本地环境
  - 保留字段：msg_uid, time_local, speaker, msg_type + 模态字段

L2（云端训练）：
  - 输入：enriched_full_anonymized_l2.jsonl（匿名化后）
  - 输出：enriched_full_anonymized_l2_sft.jsonl
  - 特点：从匿名化数据精简，额外保留 day_index, ts_relative
  - 用途：云端训练，数据需要脱敏
  - 保留字段：msg_uid, time_local, speaker, msg_type, day_index, ts_relative + 模态字段

字段精简策略：
核心字段（所有模态）：
  - msg_uid: 消息唯一标识
  - time_local: 本地时间戳
  - speaker: 发言人（ME/OTHER）
  - msg_type: 消息类型（根据 modality + sub_type 生成）
  - day_index, ts_relative: L2 模式额外保留

文本模态：
  - text_raw: 原始文本
  - merged_count: 合并消息数（如果有）

图片模态：
  - image_summary: 图片描述（压缩后）
  - image_ocr_text: OCR 文字（如果 summary 不存在或 OCR < 200 字符）
  - image_intent: 图片意图
  - image_emotion_atmosphere: 情绪氛围

语音模态：
  - voice_to_text: 语音转文字
  - emotion_tags: 情绪标签
  - emotion_desc: 情绪描述（从 voice_analysis 提取）

视频模态：
  - video_summary: 视频描述（压缩后）
  - video_voice_to_text: 音频转写
  - video_emotion_tags: 情绪标签
  - video_atmosphere: 氛围描述
  - video_intent: 视频意图

表情包模态：
  - sticker_summary: 表情包描述（智能过滤）
  - sticker_intent: 表情包意图
  - sticker_ocr_text: OCR 文字（去重后）

链接/文件模态：
  - text_raw: 原始文本
  - link_title: 链接标题
  - link_quote_text: 引用文本
  - link_file_summary: 文件摘要

系统消息模态：
  - text_raw: 原始文本（撤回消息会匿名化昵称）
  - gap_description: 时间间隔描述
  - break_type: 中断类型

智能过滤规则：
1. 表情包 summary 过滤：
   - 过滤 [REF:xxx] 引用（如果 intent 明确）
   - 清理重复 OCR 文字（如 "DL DL DL"）
   - 去除与 intent 冗余的情绪描述

2. 表情包 OCR 去重：
   - 动画 GIF 多帧导致的重复（如 "你这个 你这个 你这个" → "你这个"）
   - 过滤无意义重复文本（如 "CRET CRET CRET"）

3. 图片 OCR 过滤：
   - 如果已有 image_summary 且 OCR > 200 字符，不保留 OCR
   - 避免冗余（summary 已包含关键信息）

4. 撤回消息匿名化：
   - "\"昵称\" recalled a message" → "OTHER recalled a message"
   - "\"昵称\" 撤回了一条消息" → "OTHER 撤回了一条消息"
   - L1 和 L2 都需要（避免泄露昵称）

处理流程：
1. 加载输入文件（enriched_full_processed.jsonl 或 enriched_full_anonymized_l2.jsonl）
2. 逐条消息处理：
   a. 提取核心字段（msg_uid, time_local, speaker）
   b. 生成 msg_type（根据 modality + sub_type）
   c. 根据模态提取特定字段
   d. 应用智能过滤规则
   e. 移除空值字段
3. 保存精简结果到输出文件
4. 输出统计信息（总数、精简数、字段移除数、压缩比）

输入：
- L1: timeline_out/enriched_full_processed.jsonl（优先）或 enriched_full.jsonl
- L2: timeline_out/enriched_full_anonymized_l2.jsonl

输出：
- L1: timeline_out/enriched_full_anonymized_l1_sft.jsonl
- L2: timeline_out/enriched_full_anonymized_l2_sft.jsonl

依赖：
- json: JSON 解析
- tqdm: 进度条显示
- pathlib: 路径处理

使用示例：
    # L1: 从原始数据生成（不匿名化）
    python scripts/compression/sft_trimmer.py --l1
    
    # L2: 从匿名化数据生成
    python scripts/compression/sft_trimmer.py --l2
    
    # 同时生成 L1 和 L2
    python scripts/compression/sft_trimmer.py --l1 --l2
    
    # 自定义输入输出目录
    python scripts/compression/sft_trimmer.py --l1 \
      --input-dir /path/to/timeline \
      --output-dir /path/to/output
    
    # Python API
    from scripts.compression.sft_trimmer import SFTTrimmer
    
    # L1 模式
    trimmer = SFTTrimmer(is_l2=False)
    stats = trimmer.process_file(
        "timeline_out/enriched_full_processed.jsonl",
        "timeline_out/enriched_full_anonymized_l1_sft.jsonl"
    )
    print(f"处理完成: {stats['trimmed']}/{stats['total']}")
    print(f"压缩比: {stats['compression_ratio']}%")

统计信息：
- total: 总消息数
- trimmed: 成功精简的消息数
- fields_removed: 移除的字段总数
- errors: 错误数
- by_modality: 按模态统计
- recall_anonymized: 撤回消息匿名化数
- compression_ratio: 字段压缩比（%）

作者：forcifer
更新于：2026-02-02
"""

import json
import argparse
import unicodedata
from pathlib import Path
from typing import Dict, Any, Optional
from tqdm import tqdm


# modality + sub_type -> msg_type 映射
MSG_TYPE_MAP = {
    "text": "文本",
    "image": "图片",
    "voice": "语音",
    "video": "视频",
    "sticker": "表情包",
    "location": "位置",
    "contact": "名片",
    "link_or_file": {
        "quote": "引用",
        "miniprogram": "小程序",
        "link": "链接",
        "file": "文件",
        "default": "链接/文件"
    },
    "system": {
        "time_gap": "时间间隔",
        "default": "系统消息"
    }
}

# 各模态保留字段配置
FIELD_CONFIG = {
    "core": ["msg_uid", "time_local", "speaker"],  # msg_type 单独生成
    "core_l2_extra": ["day_index", "ts_relative"],
    
    "text": ["text_raw", "merged_count"],
    
    "image": ["image_summary", "image_ocr_text", "image_intent", "image_emotion_atmosphere"],
    
    "voice": ["voice_to_text", "emotion_tags", "emotion_desc"],  # voice_length 对 SFT 无意义
    
    "video": ["video_summary", "video_voice_to_text", "video_emotion_tags", 
              "video_atmosphere", "video_intent"],
    
    "sticker": ["sticker_summary", "sticker_intent", "sticker_ocr_text"],
    
    "link_or_file": ["text_raw", "link_title", "link_quote_text", "link_file_summary"],
    
    "system": ["text_raw", "break_type"],  # gap_description 已包含在 text_raw 中，移除冗余
    
    "location": ["location_label", "location_poiname"],
    
    "contact": ["contact_nickname"]
}


class SFTTrimmer:
    """SFT 字段精简器"""
    
    def __init__(self, is_l2: bool = False):
        """
        初始化精简器
        
        Args:
            is_l2: 是否为 L2 文件（需要额外保留 day_index, ts_relative）
        """
        self.is_l2 = is_l2
        self.stats = {
            "total": 0,
            "trimmed": 0,
            "fields_removed": 0,
            "errors": 0,
            "by_modality": {},
            "recall_anonymized": 0,
            "unicode_cleaned": 0
        }
    
    def _clean_unicode(self, text: str) -> str:
        """
        清理文本中的无效 Unicode 字符
        
        处理：
        - 替换字符（U+FFFD，显示为 �）
        - 控制字符（除了换行和制表符）
        - 私用区字符
        - 无效的代理对
        
        Args:
            text: 原始文本
        
        Returns:
            清理后的文本
        """
        if not text:
            return text
        
        original = text
        
        # 移除替换字符（U+FFFD，通常是编码错误导致的 �）
        text = text.replace('\ufffd', '')
        
        # 移除控制字符（保留换行、制表符、回车）
        cleaned_chars = []
        for c in text:
            category = unicodedata.category(c)
            # Cc = 控制字符，Cs = 代理对，Co = 私用区
            if category == 'Cc' and c not in '\n\t\r':
                continue
            if category in ('Cs', 'Co'):
                continue
            cleaned_chars.append(c)
        
        text = ''.join(cleaned_chars)
        
        # 统计清理次数
        if text != original:
            self.stats["unicode_cleaned"] += 1
        
        return text
    
    def _clean_all_text_fields(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """
        清理结果中所有文本字段的 Unicode 问题
        
        Args:
            result: 精简后的消息字典
        
        Returns:
            清理后的消息字典
        """
        text_fields = [
            'text_raw', 'image_summary', 'image_ocr_text', 'image_intent',
            'image_emotion_atmosphere', 'voice_to_text', 'emotion_desc',
            'video_summary', 'video_voice_to_text', 'video_atmosphere',
            'video_intent', 'sticker_summary', 'sticker_intent', 'sticker_ocr_text',
            'link_title', 'link_quote_text', 'link_file_summary',
            'location_label', 'location_poiname', 'contact_nickname'
        ]
        
        for field in text_fields:
            if field in result and isinstance(result[field], str):
                result[field] = self._clean_unicode(result[field])
                # 如果清理后为空，移除该字段
                if not result[field]:
                    del result[field]
        
        return result
    
    def _is_recall_message(self, text: str) -> bool:
        """判断是否是撤回消息"""
        if not text:
            return False
        return ('recalled a message' in text.lower() or 
                '撤回了一条消息' in text or 
                '你撤回' in text or 
                'You recalled' in text)
    
    def _anonymize_recall_message(self, text: str) -> str:
        """
        匿名化撤回消息中的昵称
        
        撤回消息格式：
        - "You recalled a message." -> 保持不变（ME 撤回）
        - "\"昵称\" recalled a message" -> "OTHER recalled a message"（去掉反斜杠和引号）
        - "你撤回了一条消息" -> 保持不变（ME 撤回）
        - "\"昵称\" 撤回了一条消息" -> "OTHER 撤回了一条消息"（去掉反斜杠和引号）
        
        Args:
            text: 撤回消息文本
        
        Returns:
            匿名化后的文本
        """
        import re
        
        # "You recalled" 或 "你撤回" 是我撤回的，保持不变
        if 'You recalled' in text or '你撤回' in text:
            return text
        
        # 英文格式：\"昵称\" recalled a message 或 "昵称" recalled a message
        # 替换为：OTHER recalled a message（不带引号和反斜杠）
        en_pattern = r'\\?"([^"]+)\\?"\s*recalled a message'
        en_match = re.search(en_pattern, text)
        if en_match:
            return 'OTHER recalled a message'
        
        # 中文格式：\"昵称\" 撤回了一条消息
        # 替换为：OTHER 撤回了一条消息（不带引号和反斜杠）
        cn_pattern = r'\\?"([^"]+)\\?"\s*撤回了一条消息'
        cn_match = re.search(cn_pattern, text)
        if cn_match:
            return 'OTHER 撤回了一条消息'
        
        # 其他格式保持不变
        return text

    def _get_msg_type(self, msg: Dict[str, Any]) -> str:
        """
        根据 modality 和 type/sub_type 生成统一的 msg_type
        
        Args:
            msg: 原始消息字典
        
        Returns:
            人类可读的消息类型描述
        """
        modality = msg.get("modality", "")
        
        if modality in ["text", "image", "voice", "video", "sticker", "location", "contact"]:
            return MSG_TYPE_MAP.get(modality, modality)
        
        if modality == "link_or_file":
            sub_type = msg.get("link_sub_type", "")
            type_map = MSG_TYPE_MAP["link_or_file"]
            return type_map.get(sub_type, type_map["default"])
        
        if modality == "system":
            msg_type = msg.get("type", "")
            type_map = MSG_TYPE_MAP["system"]
            return type_map.get(msg_type, type_map["default"])
        
        return modality or "未知"
    
    def _trim_core_fields(self, msg: Dict[str, Any], result: Dict[str, Any]) -> None:
        """提取核心字段"""
        for field in FIELD_CONFIG["core"]:
            if field in msg:
                result[field] = msg[field]
        
        # 生成 msg_type
        result["msg_type"] = self._get_msg_type(msg)
        
        # L2 模式额外保留字段
        if self.is_l2:
            for field in FIELD_CONFIG["core_l2_extra"]:
                if field in msg:
                    result[field] = msg[field]
    
    def _trim_text_fields(self, msg: Dict[str, Any], result: Dict[str, Any]) -> None:
        """精简 TEXT 模态字段"""
        for field in FIELD_CONFIG["text"]:
            if field in msg:
                result[field] = msg[field]
    
    def _trim_image_fields(self, msg: Dict[str, Any], result: Dict[str, Any]) -> None:
        """精简 IMAGE 模态字段"""
        has_summary = bool(msg.get("image_summary"))
        
        for field in FIELD_CONFIG["image"]:
            if field in msg:
                value = msg[field]
                # 如果已有 image_summary，且 OCR 文本过长（>200字符），则不保留 OCR
                # 因为 summary 已经包含了关键信息
                if field == "image_ocr_text" and has_summary and value and len(value) > 200:
                    continue
                result[field] = value
    
    def _trim_voice_fields(self, msg: Dict[str, Any], result: Dict[str, Any]) -> None:
        """精简 VOICE 模态字段"""
        for field in FIELD_CONFIG["voice"]:
            if field == "emotion_desc":
                # emotion_desc 嵌套在 voice_analysis 中
                voice_analysis = msg.get("voice_analysis", {})
                if voice_analysis and voice_analysis.get("emotion_desc"):
                    result["emotion_desc"] = voice_analysis["emotion_desc"]
            elif field in msg:
                result[field] = msg[field]
    
    def _trim_video_fields(self, msg: Dict[str, Any], result: Dict[str, Any]) -> None:
        """精简 VIDEO 模态字段"""
        for field in FIELD_CONFIG["video"]:
            if field in msg:
                result[field] = msg[field]
    
    def _trim_sticker_fields(self, msg: Dict[str, Any], result: Dict[str, Any]) -> None:
        """精简 STICKER 模态字段"""
        intent = msg.get("sticker_intent", "")
        summary = msg.get("sticker_summary", "")
        
        # 判断 intent 是否是明确的情绪（非"表达情绪"通用类型）
        is_specific_intent = intent and intent != "表达情绪"
        
        for field in FIELD_CONFIG["sticker"]:
            if field in msg:
                value = msg[field]
                
                # 处理 sticker_summary
                if field == "sticker_summary" and value:
                    # 过滤掉 REF 引用
                    if value.startswith("[REF:"):
                        # 如果 intent 是明确情绪，不需要 fallback 到 caption
                        if is_specific_intent:
                            continue
                        # 否则使用 sticker_caption 作为 fallback
                        caption = msg.get("sticker_caption", "")
                        if caption:
                            result["sticker_summary"] = caption
                        continue
                    
                    # 清理 summary 中的重复 OCR 文字
                    value = self._clean_sticker_summary(value)
                    if not value:
                        continue
                    
                    # 如果 intent 是明确情绪，检查 summary 是否冗余
                    if is_specific_intent:
                        # 提取 summary 中的情绪部分（去掉方括号）
                        summary_clean = value.replace('[', '').replace(']', '').strip()
                        
                        # 如果 summary 只是 [情绪] 格式且与 intent 相同，则跳过（冗余）
                        if summary_clean == intent:
                            continue
                        
                        # 如果 summary 是 [情绪] (文字: xxx) 格式，检查情绪部分
                        import re
                        emotion_match = re.match(r'\[([^\]]+)\]', value)
                        if emotion_match:
                            emotion_part = emotion_match.group(1)
                            if emotion_part == intent:
                                # 情绪部分与 intent 相同，跳过（文字部分已在 sticker_ocr_text）
                                continue
                        
                        # 如果 summary 是 [表情包: 描述] 格式，且 intent 是明确情绪
                        # 这种情况下 summary 提供了额外的视觉描述，但 intent 已经表达了情绪
                        # 根据用户需求：明确情绪时删除 summary
                        if value.startswith("[表情包:"):
                            continue
                    
                    result[field] = value
                    continue
                
                # 处理 sticker_ocr_text：去重并过滤无意义文本
                if field == "sticker_ocr_text" and value:
                    value = self._deduplicate_ocr_text(value)
                    if not value or self._is_repetitive_text(value):
                        continue
                    result[field] = value
                    continue
                
                result[field] = value
    
    def _clean_sticker_summary(self, summary: str) -> str:
        """
        清理 sticker_summary 中的重复 OCR 文字
        
        例如: "[开心/高兴] (文字: DL DL DL Dl Dl DL)" -> "[开心/高兴]"
        """
        import re
        # 匹配 (文字: xxx) 模式
        match = re.search(r'\s*\(文字:\s*([^)]+)\)', summary)
        if match:
            ocr_text = match.group(1)
            # 检查 OCR 文字是否重复
            if self._is_repetitive_text(ocr_text):
                # 移除重复的 OCR 部分
                return re.sub(r'\s*\(文字:\s*[^)]+\)', '', summary).strip()
        return summary
    
    def _deduplicate_ocr_text(self, text: str) -> str:
        """
        去重 OCR 文本（动画 GIF 多帧导致的重复）
        
        例如: "你这个 你这个 你这个 大便 大便 大便" -> "你这个 大便"
        """
        if not text:
            return text
        
        words = text.split()
        if len(words) <= 2:
            return text
        
        # 保持顺序去重
        seen = set()
        unique_words = []
        for word in words:
            word_lower = word.lower()
            if word_lower not in seen:
                seen.add(word_lower)
                unique_words.append(word)
        
        return ' '.join(unique_words)
    
    def _is_repetitive_text(self, text: str, threshold: float = 0.5) -> bool:
        """
        检测文本是否为重复字符（如 CRET CRET CRET）
        
        Args:
            text: 待检测文本
            threshold: 重复比例阈值，超过则认为是重复文本
        
        Returns:
            是否为重复文本
        """
        if not text or len(text) < 10:
            return False
        
        words = text.split()
        if len(words) < 4:
            return False
        
        # 统计词频
        word_counts = {}
        for word in words:
            word_counts[word] = word_counts.get(word, 0) + 1
        
        # 计算最高频词的占比
        max_count = max(word_counts.values())
        if max_count / len(words) > threshold:
            return True
        
        return False
    
    def _trim_link_fields(self, msg: Dict[str, Any], result: Dict[str, Any]) -> None:
        """精简 LINK_OR_FILE 模态字段"""
        for field in FIELD_CONFIG["link_or_file"]:
            if field in msg:
                result[field] = msg[field]
    
    def _trim_system_fields(self, msg: Dict[str, Any], result: Dict[str, Any]) -> None:
        """精简 SYSTEM 模态字段"""
        for field in FIELD_CONFIG["system"]:
            if field in msg:
                value = msg[field]
                
                # 对撤回消息进行昵称匿名化（L1 和 L2 都需要）
                if field == "text_raw" and value and self._is_recall_message(value):
                    original = value
                    value = self._anonymize_recall_message(value)
                    if value != original:
                        self.stats["recall_anonymized"] += 1
                
                result[field] = value
    
    def _trim_location_fields(self, msg: Dict[str, Any], result: Dict[str, Any]) -> None:
        """精简 LOCATION 模态字段"""
        for field in FIELD_CONFIG["location"]:
            if field in msg:
                result[field] = msg[field]
    
    def _trim_contact_fields(self, msg: Dict[str, Any], result: Dict[str, Any]) -> None:
        """精简 CONTACT 模态字段"""
        for field in FIELD_CONFIG["contact"]:
            if field in msg:
                result[field] = msg[field]
    
    def _remove_empty_fields(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """移除空值字段（null, 空字符串, 空数组）"""
        cleaned = {}
        for key, value in result.items():
            if value is None:
                continue
            if isinstance(value, str) and value == "":
                continue
            if isinstance(value, list) and len(value) == 0:
                continue
            cleaned[key] = value
        return cleaned

    def trim_message(self, msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        精简单条消息
        
        Args:
            msg: 原始消息字典
        
        Returns:
            精简后的消息字典，如果处理失败返回 None
        """
        self.stats["total"] += 1
        original_fields = len(msg)
        
        try:
            result = {}
            modality = msg.get("modality", "")
            
            # 提取核心字段
            self._trim_core_fields(msg, result)
            
            # 根据模态提取特定字段
            if modality == "text":
                self._trim_text_fields(msg, result)
            elif modality == "image":
                self._trim_image_fields(msg, result)
            elif modality == "voice":
                self._trim_voice_fields(msg, result)
            elif modality == "video":
                self._trim_video_fields(msg, result)
            elif modality == "sticker":
                self._trim_sticker_fields(msg, result)
            elif modality == "link_or_file":
                self._trim_link_fields(msg, result)
            elif modality == "system":
                self._trim_system_fields(msg, result)
            elif modality == "location":
                self._trim_location_fields(msg, result)
            elif modality == "contact":
                self._trim_contact_fields(msg, result)
            else:
                # 未知模态，只保留核心字段
                pass
            
            # 移除空值字段
            result = self._remove_empty_fields(result)
            
            # 清理 Unicode 乱码
            result = self._clean_all_text_fields(result)
            
            # 更新统计
            self.stats["trimmed"] += 1
            self.stats["fields_removed"] += original_fields - len(result)
            
            # 按模态统计
            if modality not in self.stats["by_modality"]:
                self.stats["by_modality"][modality] = 0
            self.stats["by_modality"][modality] += 1
            
            return result
            
        except Exception as e:
            self.stats["errors"] += 1
            print(f"[WARN] 处理消息失败: {e}, msg_uid={msg.get('msg_uid', 'unknown')}")
            return None
    
    def validate_output(self, result: Dict[str, Any]) -> bool:
        """
        验证输出消息包含核心字段
        
        Args:
            result: 精简后的消息
        
        Returns:
            是否有效
        """
        # system 模态可能没有 time_local
        if result.get("msg_type") in ["时间间隔", "系统消息"]:
            required = ["msg_uid", "speaker", "msg_type"]
        else:
            required = ["msg_uid", "time_local", "speaker", "msg_type"]
        
        for field in required:
            if field not in result:
                return False
        return True
    
    def process_file(self, input_path: str, output_path: str) -> Dict[str, Any]:
        """
        处理整个文件
        
        Args:
            input_path: 输入文件路径
            output_path: 输出文件路径
        
        Returns:
            处理统计信息
        """
        input_file = Path(input_path)
        output_file = Path(output_path)
        
        if not input_file.exists():
            raise FileNotFoundError(f"输入文件不存在: {input_path}")
        
        # 统计行数
        with open(input_file, 'r', encoding='utf-8') as f:
            total_lines = sum(1 for _ in f)
        
        # 处理文件
        validation_errors = []
        with open(input_file, 'r', encoding='utf-8') as fin, \
             open(output_file, 'w', encoding='utf-8') as fout:
            
            for line in tqdm(fin, total=total_lines, desc="精简字段"):
                line = line.strip()
                if not line:
                    continue
                
                try:
                    msg = json.loads(line)
                    result = self.trim_message(msg)
                    
                    if result:
                        # 验证输出
                        if not self.validate_output(result):
                            validation_errors.append(msg.get("msg_uid", "unknown"))
                        
                        fout.write(json.dumps(result, ensure_ascii=False) + "\n")
                        
                except json.JSONDecodeError as e:
                    self.stats["errors"] += 1
                    print(f"[WARN] JSON 解析失败: {e}")
        
        # 记录验证错误
        if validation_errors:
            print(f"[WARN] {len(validation_errors)} 条消息缺少核心字段")
        
        return self.get_stats()
    
    def get_stats(self) -> Dict[str, Any]:
        """获取处理统计"""
        stats = self.stats.copy()
        if stats["total"] > 0:
            stats["compression_ratio"] = round(
                stats["fields_removed"] / (stats["total"] * 20) * 100, 2
            )
        return stats


def main():
    """命令行入口"""
    parser = argparse.ArgumentParser(description="SFT 字段精简器")
    parser.add_argument("--l1", action="store_true", 
                        help="处理 L1 数据（从原始数据，不匿名化）")
    parser.add_argument("--l2", action="store_true", 
                        help="处理 L2 数据（从匿名化后的数据）")
    parser.add_argument("--input-dir", default="timeline_out", help="输入目录")
    parser.add_argument("--output-dir", default="timeline_out", help="输出目录")
    
    args = parser.parse_args()
    
    if not args.l1 and not args.l2:
        print("请指定 --l1 或 --l2 参数")
        print("")
        print("说明：")
        print("  --l1: L1 本地训练数据，从原始数据直接精简，不匿名化")
        print("  --l2: L2 云端训练数据，从匿名化后的数据精简")
        return
    
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    
    if args.l1:
        print("\n=== 处理 L1 文件（无匿名化） ===")
        # L1: 从原始数据直接精简（不匿名化）
        # 优先使用 enriched_full_processed.jsonl（后处理版本）
        # 如果不存在，使用 enriched_full.jsonl
        input_path = input_dir / "enriched_full_processed.jsonl"
        
        if not input_path.exists():
            print("[INFO] enriched_full_processed.jsonl 不存在，使用 enriched_full.jsonl")
            input_path = input_dir / "enriched_full.jsonl"
        else:
            print("[INFO] 使用后处理版本 enriched_full_processed.jsonl")
        
        output_path = output_dir / "enriched_full_anonymized_l1_sft.jsonl"
        
        print(f"[INFO] L1 模式：从原始数据生成，不进行匿名化")
        print(f"[INFO] 输入: {input_path}")
        print(f"[INFO] 输出: {output_path}")
        
        trimmer = SFTTrimmer(is_l2=False)
        stats = trimmer.process_file(str(input_path), str(output_path))
        
        print(f"处理完成: {stats['trimmed']}/{stats['total']} 条消息")
        print(f"移除字段数: {stats['fields_removed']}")
        print(f"Unicode 清理数: {stats.get('unicode_cleaned', 0)}")
        print(f"错误数: {stats['errors']}")
        print(f"按模态统计: {stats['by_modality']}")
        print(f"输出文件: {output_path}")
    
    if args.l2:
        print("\n=== 处理 L2 文件（匿名化后） ===")
        # L2: 从匿名化后的数据精简
        input_path = input_dir / "enriched_full_anonymized_l2.jsonl"
        output_path = output_dir / "enriched_full_anonymized_l2_sft.jsonl"
        
        print(f"[INFO] L2 模式：从匿名化数据生成")
        print(f"[INFO] 输入: {input_path}")
        print(f"[INFO] 输出: {output_path}")
        
        trimmer = SFTTrimmer(is_l2=True)
        stats = trimmer.process_file(str(input_path), str(output_path))
        
        print(f"处理完成: {stats['trimmed']}/{stats['total']} 条消息")
        print(f"移除字段数: {stats['fields_removed']}")
        print(f"Unicode 清理数: {stats.get('unicode_cleaned', 0)}")
        print(f"错误数: {stats['errors']}")
        print(f"按模态统计: {stats['by_modality']}")
        print(f"输出文件: {output_path}")


if __name__ == "__main__":
    main()
