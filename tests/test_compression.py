# -*- coding: utf-8 -*-
"""
语义压缩系统测试

包含单元测试和属性测试
"""

import pytest
import json
import sys
from pathlib import Path
from typing import Dict, List

# 添加项目根目录
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.compression.image_compressor import ImageCompressor
from scripts.compression.video_compressor import VideoCompressor
from scripts.compression.voice_compressor import VoiceCompressor
from scripts.compression.sticker_compressor import StickerCompressor
from scripts.compression.privacy_shield import PrivacyShield
from scripts.compression.quality_validator import QualityValidator


# ============================================================
# 图片压缩器测试
# ============================================================

class TestImageCompressor:
    """图片压缩器测试"""
    
    @pytest.fixture
    def compressor(self):
        return ImageCompressor()
    
    def test_compress_basic(self, compressor):
        """测试基本压缩功能"""
        image_data = {
            "msg_uid": "test_001",
            "caption": "这张图片展示了一个温馨的场景。场景是在一个铺着格子图案床单的床上，床上躺着一只猫咪。",
            "content_type": "TYPE_C_NORMAL",
            "route_class": "VISUAL_PRIMARY"
        }
        
        result = compressor.compress(image_data)
        
        assert result["msg_uid"] == "test_001"
        assert "image_summary" in result
        assert len(result["image_summary"]) > 0
        assert result["compression_ratio"] >= 1.0
    
    def test_compress_with_ocr(self, compressor):
        """测试带 OCR 的压缩"""
        image_data = {
            "msg_uid": "test_002",
            "caption": "这是一张文档截图",
            "content_type": "TYPE_D_DOC",
            "route_class": "TEXT_PRIMARY"
        }
        ocr_data = {
            "msg_uid": "test_002",
            "full_text": "这是文档中的文字内容，包含一些重要信息。"
        }
        
        result = compressor.compress(image_data, ocr_data)
        
        assert "文字内容" in result["image_summary"] or "文档" in result["image_summary"]
        assert result["scene_focus"] == "document"
    
    def test_sensitive_content_label_preserved(self, compressor):
        """Property 2: 敏感内容标签保留"""
        image_data = {
            "msg_uid": "test_003",
            "caption": "敏感内容描述",
            "content_type": "TYPE_A_NSFW",
            "route_class": "VISUAL_PRIMARY"
        }
        
        result = compressor.compress(image_data)
        
        # 敏感内容标签应该被保留
        assert "TYPE_A_NSFW" in result["image_summary"]
    
    def test_compression_length_constraint(self, compressor):
        """Property 1: 图片压缩长度约束"""
        # 很长的描述
        long_caption = "这张图片展示了一个非常详细的场景。" * 20
        
        image_data = {
            "msg_uid": "test_004",
            "caption": long_caption,
            "content_type": "TYPE_C_NORMAL",
            "route_class": "VISUAL_PRIMARY"
        }
        
        result = compressor.compress(image_data)
        
        # 压缩后长度应该在合理范围内
        assert len(result["image_summary"]) <= 150
    
    def test_emotion_extraction(self, compressor):
        """测试情绪氛围提取"""
        image_data = {
            "msg_uid": "test_005",
            "caption": "这是一张充满欢乐和笑声的照片，大家都很开心。",
            "content_type": "TYPE_C_NORMAL",
            "route_class": "VISUAL_PRIMARY"
        }
        
        result = compressor.compress(image_data)
        
        assert result["emotion_atmosphere"] == "欢乐"


# ============================================================
# 视频压缩器测试
# ============================================================

class TestVideoCompressor:
    """视频压缩器测试"""
    
    @pytest.fixture
    def compressor(self):
        return VideoCompressor()
    
    def test_compress_basic(self, compressor):
        """测试基本压缩功能"""
        caption_data = {
            "msg_uid": "video_001",
            "keyframe_captions": [
                {"frame_id": 0, "timestamp_sec": 0.0, "caption": "开始场景描述"},
                {"frame_id": 1, "timestamp_sec": 1.0, "caption": "中间场景描述"},
                {"frame_id": 2, "timestamp_sec": 2.0, "caption": "结束场景描述"}
            ],
            "video_understanding": {
                "summary": "这是一段测试视频的摘要"
            },
            "triage": {"content_type": "TYPE_C_NORMAL"}
        }
        
        result = compressor.compress(caption_data)
        
        assert result["msg_uid"] == "video_001"
        assert "video_summary" in result
        assert result["num_frames"] == 3
    
    def test_adaptive_merge_strategy(self, compressor):
        """测试自适应合并策略"""
        # 5帧及以下应该使用 sequential
        assert compressor._adaptive_merge_strategy(3) == "sequential"
        assert compressor._adaptive_merge_strategy(5) == "sequential"
        
        # 6-10帧应该使用 segmented
        assert compressor._adaptive_merge_strategy(6) == "segmented"
        assert compressor._adaptive_merge_strategy(10) == "segmented"
        
        # 11-16帧应该使用 key_changes
        assert compressor._adaptive_merge_strategy(11) == "key_changes"
        assert compressor._adaptive_merge_strategy(16) == "key_changes"
    
    def test_time_order_preserved(self, compressor):
        """Property 4: 视频时间顺序保留"""
        caption_data = {
            "msg_uid": "video_002",
            "keyframe_captions": [
                {"frame_id": 0, "timestamp_sec": 0.0, "caption": "第一帧：猫咪躺着"},
                {"frame_id": 1, "timestamp_sec": 1.0, "caption": "第二帧：猫咪站起来"},
                {"frame_id": 2, "timestamp_sec": 2.0, "caption": "第三帧：猫咪走开了"}
            ],
            "video_understanding": {"summary": ""},
            "triage": {"content_type": "TYPE_C_NORMAL"}
        }
        
        result = compressor.compress(caption_data)
        
        # 摘要应该包含"开始"和"结束"标记
        assert "开始" in result["video_summary"] or "→" in result["video_summary"]
    
    def test_compression_length_constraint(self, compressor):
        """Property 3: 视频压缩长度约束"""
        # 创建很长的帧描述
        long_captions = [
            {"frame_id": i, "timestamp_sec": float(i), "caption": f"这是第{i}帧的非常详细的描述。" * 10}
            for i in range(10)
        ]
        
        caption_data = {
            "msg_uid": "video_003",
            "keyframe_captions": long_captions,
            "video_understanding": {"summary": "很长的摘要" * 50},
            "triage": {"content_type": "TYPE_C_NORMAL"}
        }
        
        result = compressor.compress(caption_data)
        
        # 压缩后长度应该在合理范围内
        assert len(result["video_summary"]) <= 300


# ============================================================
# 语音压缩器测试
# ============================================================

class TestVoiceCompressor:
    """语音压缩器测试"""
    
    @pytest.fixture
    def compressor(self):
        return VoiceCompressor()
    
    def test_compress_basic(self, compressor):
        """测试基本压缩功能"""
        voice_data = {
            "file": "test_voice.mp3",
            "punct_text": "这是一段测试语音的转写内容。",
            "sensevoice": {
                "emotion_tags": ["NEUTRAL"],
                "clean_text": "这是一段测试语音的转写内容。"
            }
        }
        
        result = compressor.compress(voice_data)
        
        assert result["file"] == "test_voice.mp3"
        assert result["punct_text"] == voice_data["punct_text"]
        assert result["emotion_tags"] == ["NEUTRAL"]
    
    def test_punct_text_preserved(self, compressor):
        """Property 5: 语音字段保留策略 - punct_text 必须保留"""
        voice_data = {
            "file": "test_voice.mp3",
            "punct_text": "原始转写内容必须保留",
            "sensevoice": {"emotion_tags": ["HAPPY"]}
        }
        
        result = compressor.compress(voice_data)
        
        assert result["punct_text"] == "原始转写内容必须保留"
    
    def test_emotion_tags_preserved(self, compressor):
        """Property 5: 语音字段保留策略 - emotion_tags 必须保留"""
        voice_data = {
            "file": "test_voice.mp3",
            "punct_text": "测试",
            "sensevoice": {"emotion_tags": ["HAPPY", "EXCITED"]}
        }
        
        result = compressor.compress(voice_data)
        
        assert result["emotion_tags"] == ["HAPPY", "EXCITED"]
    
    def test_analysis_compression(self, compressor):
        """测试分析内容压缩"""
        voice_data = {
            "file": "test_voice.mp3",
            "punct_text": "我觉得这件事情很重要",
            "sensevoice": {"emotion_tags": ["NEUTRAL"]},
            "voice_analysis": {
                "emotion_desc": "说话者表现出自信和自豪的情感，语气坚定，表达清晰。"
            }
        }
        
        result = compressor.compress(voice_data)
        
        # 有价值的分析应该被保留
        assert result["analysis_summary"] is not None
        assert "自信" in result["analysis_summary"] or "自豪" in result["analysis_summary"]
    
    def test_low_value_analysis_removed(self, compressor):
        """测试低价值分析被移除"""
        voice_data = {
            "file": "test_voice.mp3",
            "punct_text": "好的",
            "sensevoice": {"emotion_tags": ["NEUTRAL"]},
            "voice_analysis": {
                "emotion_desc": "语气听起来很平静，没有明显的情绪波动。"
            }
        }
        
        result = compressor.compress(voice_data)
        
        # 低价值分析应该被移除
        assert result["analysis_summary"] is None


# ============================================================
# 表情包压缩器测试
# ============================================================

class TestStickerCompressor:
    """表情包压缩器测试"""
    
    @pytest.fixture
    def compressor(self):
        return StickerCompressor()
    
    def test_compress_basic(self, compressor):
        """测试基本压缩功能"""
        sticker_data = {
            "msg_uid": "sticker_001",
            "caption": "一个可爱的卡通人物在笑",
            "ocr_text": ""
        }
        
        result = compressor.compress(sticker_data)
        
        assert result["msg_uid"] == "sticker_001"
        assert "intent" in result
        assert "intent_confidence" in result
    
    def test_intent_from_ocr(self, compressor):
        """测试从 OCR 提取意图"""
        sticker_data = {
            "msg_uid": "sticker_002",
            "caption": "表情包图片",
            "ocr_text": "好的"
        }
        
        result = compressor.compress(sticker_data)
        
        # OCR 包含"好的"应该映射到赞同类意图
        # 注意：实际映射取决于 sticker_intent_map.yaml 配置
        assert "intent" in result
        assert result["intent_confidence"] >= 0.0
    
    def test_confidence_range(self, compressor):
        """Property 6: 表情包格式化输出 - 置信度范围"""
        sticker_data = {
            "msg_uid": "sticker_003",
            "caption": "测试表情包",
            "ocr_text": ""
        }
        
        result = compressor.compress(sticker_data)
        
        # 置信度应该在 0.0-1.0 范围内
        assert 0.0 <= result["intent_confidence"] <= 1.0
    
    def test_lexicon_building(self, compressor):
        """Property 10: 表情包字典唯一性"""
        stickers = [
            {"msg_uid": "s1", "file_sha256": "hash1", "caption": "笑", "ocr_text": ""},
            {"msg_uid": "s2", "file_sha256": "hash1", "caption": "笑", "ocr_text": ""},  # 重复
            {"msg_uid": "s3", "file_sha256": "hash2", "caption": "哭", "ocr_text": ""}
        ]
        
        compressed = [compressor.compress(s) for s in stickers]
        lexicon = compressor.build_lexicon(compressed)
        
        # 字典应该去重
        assert len(lexicon) == 2  # hash1 和 hash2


# ============================================================
# 隐私保护层测试
# ============================================================

class TestPrivacyShield:
    """隐私保护层测试"""
    
    @pytest.fixture
    def shield(self):
        return PrivacyShield()
    
    def test_detect_phone(self, shield):
        """Property 12: PII 检测 - 手机号"""
        text = "我的电话是13812345678"
        matches = shield.detect_pii(text)
        
        phone_matches = [m for m in matches if m.type == 'phone']
        assert len(phone_matches) == 1
        assert phone_matches[0].value == "13812345678"
    
    def test_detect_email(self, shield):
        """Property 12: PII 检测 - 邮箱"""
        text = "邮箱是test@example.com"
        matches = shield.detect_pii(text)
        
        email_matches = [m for m in matches if m.type == 'email']
        assert len(email_matches) == 1
        assert email_matches[0].value == "test@example.com"
    
    def test_detect_wechat_id(self, shield):
        """Property 12: PII 检测 - 微信ID"""
        text = "微信号wxid_abc123xyz"
        matches = shield.detect_pii(text)
        
        wechat_matches = [m for m in matches if m.type == 'wechat_id']
        assert len(wechat_matches) == 1
    
    def test_name_replacement(self, shield):
        """Property 13: 一致性伪匿名化 - 名字替换"""
        # 使用配置中实际存在的名字
        message = {"text_raw": "测试用户A说了一些话"}
        
        result = shield.anonymize_l1(message)
        
        # 名字应该被替换为 ME（测试用户A在 me_names 中）
        assert "ME" in result["text_raw"]
        assert "测试用户A" not in result["text_raw"]
    
    def test_consistent_pseudonymization(self, shield):
        """Property 13: 一致性伪匿名化 - 同一实体映射一致"""
        # 使用配置中实际存在的名字
        msg1 = {"text_raw": "测试用户A说"}
        msg2 = {"text_raw": "测试用户A又说"}
        
        result1 = shield.anonymize_l1(msg1)
        result2 = shield.anonymize_l1(msg2)
        
        # 同一个名字应该映射到相同的代号
        assert result1["text_raw"].replace("说", "") == result2["text_raw"].replace("又说", "")
    
    def test_l2_timestamp_generalization(self, shield):
        """测试 L2 时间戳泛化"""
        message = {
            "text_raw": "测试消息",
            "ts": 1752503924,  # 2025-07-14 22:38:44
            "time_local": "2025-07-14 22:38:44"
        }
        
        result = shield.anonymize_l2(message)
        
        assert "ts_generalized" in result
        assert result["ts_generalized"]["period"] == "晚上"


# ============================================================
# 质量验证器测试
# ============================================================

class TestQualityValidator:
    """质量验证器测试"""
    
    @pytest.fixture
    def validator(self):
        return QualityValidator()
    
    def test_high_similarity(self, validator):
        """Property 14: 语义相似度评估 - 高相似度"""
        original = "这是一段测试文本"
        compressed = "这是测试文本"
        
        result = validator.validate_compression(original, compressed)
        
        # 相似的文本应该有较高的相似度
        assert result.similarity_score > 0.5
    
    def test_low_similarity(self, validator):
        """Property 14: 语义相似度评估 - 低相似度"""
        original = "这是一段关于猫咪的描述"
        compressed = "完全不相关的内容"
        
        result = validator.validate_compression(original, compressed)
        
        # 不相关的文本应该有较低的相似度
        assert result.similarity_score < 0.5
    
    def test_low_quality_marking(self, validator):
        """Property 15: 低质量压缩标记"""
        original = "这是一段很长的原始文本，包含很多重要信息"
        compressed = "xyz"  # 完全不相关
        
        result = validator.validate_compression(original, compressed)
        
        # 低质量压缩应该被标记
        assert result.quality_level == "low"
        assert result.needs_fallback == True
    
    def test_compression_ratio_warning(self, validator):
        """测试压缩比警告"""
        original = "短文本"
        compressed = "短文本"  # 没有压缩
        
        result = validator.validate_compression(original, compressed, compression_ratio=1.0)
        
        # 压缩比过低应该有警告
        assert any("压缩比" in issue for issue in result.issues)


# ============================================================
# 时间轴后处理器测试
# ============================================================

class TestTimelinePostprocessor:
    """时间轴后处理器测试"""
    
    @pytest.fixture
    def postprocessor(self):
        from scripts.timeline.timeline_postprocessor import TimelinePostprocessor
        return TimelinePostprocessor()
    
    def test_merge_same_speaker(self, postprocessor):
        """测试同一 speaker 连续消息合并"""
        messages = [
            {"msg_uid": "1", "speaker": "ME", "modality": "text", "text_raw": "你好", "ts": 1000},
            {"msg_uid": "2", "speaker": "ME", "modality": "text", "text_raw": "在吗", "ts": 1030}
        ]
        
        result = postprocessor.process(messages)
        
        # 应该合并为一条
        assert len(result) == 1
        assert "你好" in result[0]["text_raw"]
        assert "在吗" in result[0]["text_raw"]
    
    def test_no_merge_different_speaker(self, postprocessor):
        """测试不同 speaker 消息不合并"""
        messages = [
            {"msg_uid": "1", "speaker": "ME", "modality": "text", "text_raw": "你好", "ts": 1000},
            {"msg_uid": "2", "speaker": "OTHER", "modality": "text", "text_raw": "你好", "ts": 1030}
        ]
        
        result = postprocessor.process(messages)
        
        # 不应该合并
        assert len(result) == 2
    
    def test_no_merge_multimodal(self, postprocessor):
        """测试多模态消息不参与合并"""
        messages = [
            {"msg_uid": "1", "speaker": "ME", "modality": "text", "text_raw": "看这个", "ts": 1000},
            {"msg_uid": "2", "speaker": "ME", "modality": "image", "text_raw": "", "ts": 1030}
        ]
        
        result = postprocessor.process(messages)
        
        # 图片消息不应该被合并
        assert len(result) == 2
    
    def test_time_gap_insertion(self, postprocessor):
        """Property 9: 时间流逝标记插入"""
        messages = [
            {"msg_uid": "1", "speaker": "ME", "modality": "text", "text_raw": "早上好", "ts": 1000},
            {"msg_uid": "2", "speaker": "OTHER", "modality": "text", "text_raw": "晚上好", "ts": 1000 + 8 * 3600}  # 8小时后
        ]
        
        result = postprocessor.process(messages)
        
        # 应该插入时间标记
        assert len(result) == 3
        time_gap_msgs = [m for m in result if m.get("modality") == "system"]
        assert len(time_gap_msgs) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
