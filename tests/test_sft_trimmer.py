# -*- coding: utf-8 -*-
"""
SFT Trimmer 属性测试

使用 Hypothesis 进行属性测试，验证 SFT 字段精简器的正确性属性。
"""

import json
import pytest
from hypothesis import given, strategies as st, settings, assume
from typing import Dict, Any, List

import sys
sys.path.insert(0, '.')
from scripts.compression.sft_trimmer import SFTTrimmer, MSG_TYPE_MAP, FIELD_CONFIG


# ============== 测试数据生成策略 ==============

@st.composite
def text_message_strategy(draw):
    """生成 TEXT 模态消息"""
    return {
        "msg_uid": draw(st.text(min_size=5, max_size=30)),
        "time_local": draw(st.from_regex(r"2025-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", fullmatch=True)),
        "speaker": draw(st.sampled_from(["ME", "OTHER", "SYSTEM"])),
        "modality": "text",
        "type": 1,
        "sub_type": 0,
        "text_raw": draw(st.text(min_size=1, max_size=200)),
        "media_path": None,
        "voice_length": None,
        "voice_to_text": None,
        "merged_count": draw(st.one_of(st.none(), st.integers(min_value=2, max_value=10))),
        "seq_in_html": draw(st.integers(min_value=0)),
        "MsgSvrID": draw(st.text(min_size=10, max_size=20)),
        "token": draw(st.text(min_size=10, max_size=40)),
        "ts": draw(st.integers(min_value=1700000000, max_value=1800000000)),
    }


@st.composite
def image_message_strategy(draw):
    """生成 IMAGE 模态消息"""
    return {
        "msg_uid": draw(st.text(min_size=5, max_size=30)),
        "time_local": draw(st.from_regex(r"2025-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", fullmatch=True)),
        "speaker": draw(st.sampled_from(["ME", "OTHER"])),
        "modality": "image",
        "type": 3,
        "sub_type": 0,
        "text_raw": "raw/image/test.jpg",
        "media_path": "raw/image/test.jpg",
        "image_summary": draw(st.text(min_size=5, max_size=100)),
        "image_ocr_text": draw(st.one_of(st.just(""), st.text(min_size=1, max_size=50))),
        "image_intent": draw(st.sampled_from(["分享", "记录", "展示", ""])),
        "image_emotion_atmosphere": draw(st.sampled_from(["中性", "轻松", "温馨", ""])),
        "image_route_class": "TEXT_PRIMARY",
        "image_triage_confidence": 0.95,
        "image_nsfw_score": 0.01,
        "image_width": 1080,
        "image_height": 1920,
        "seq_in_html": draw(st.integers(min_value=0)),
        "MsgSvrID": draw(st.text(min_size=10, max_size=20)),
        "token": draw(st.text(min_size=10, max_size=40)),
        "ts": draw(st.integers(min_value=1700000000, max_value=1800000000)),
    }


@st.composite
def voice_message_strategy(draw):
    """生成 VOICE 模态消息"""
    return {
        "msg_uid": draw(st.text(min_size=5, max_size=30)),
        "time_local": draw(st.from_regex(r"2025-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", fullmatch=True)),
        "speaker": draw(st.sampled_from(["ME", "OTHER"])),
        "modality": "voice",
        "type": 34,
        "sub_type": 0,
        "text_raw": "raw/voice/test.mp3",
        "media_path": "raw/voice/test.mp3",
        "voice_length": draw(st.integers(min_value=1000, max_value=60000)),
        "voice_to_text": draw(st.text(min_size=5, max_size=200)),
        "emotion_tags": draw(st.lists(st.sampled_from(["NEUTRAL", "HAPPY", "SAD"]), max_size=3)),
        "emotion_desc": draw(st.one_of(st.just(""), st.text(min_size=1, max_size=20))),
        "asr_engine": "funasr",
        "asr_raw_text": draw(st.text(min_size=5, max_size=200)),
        "asr_patches": [],
        "seq_in_html": draw(st.integers(min_value=0)),
        "MsgSvrID": draw(st.text(min_size=10, max_size=20)),
        "token": draw(st.text(min_size=10, max_size=40)),
        "ts": draw(st.integers(min_value=1700000000, max_value=1800000000)),
    }


@st.composite
def video_message_strategy(draw):
    """生成 VIDEO 模态消息"""
    return {
        "msg_uid": draw(st.text(min_size=5, max_size=30)),
        "time_local": draw(st.from_regex(r"2025-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", fullmatch=True)),
        "speaker": draw(st.sampled_from(["ME", "OTHER"])),
        "modality": "video",
        "type": 43,
        "sub_type": 0,
        "text_raw": "raw/video/test.mp4",
        "media_path": "raw/video/test.mp4",
        "video_summary": draw(st.text(min_size=10, max_size=200)),
        "video_voice_to_text": draw(st.one_of(st.just(""), st.text(min_size=1, max_size=100))),
        "video_emotion_tags": draw(st.lists(st.sampled_from(["NEUTRAL", "HAPPY"]), max_size=2)),
        "video_atmosphere": draw(st.sampled_from(["温馨", "轻松", "中性", ""])),
        "video_intent": draw(st.sampled_from(["分享日常", "记录", ""])),
        "video_keyframes": [{"frame_id": 0, "caption": "很长的描述..."}],
        "video_metadata": {"duration_sec": 10.0},
        "video_audit": {"model_versions": {}},
        "seq_in_html": draw(st.integers(min_value=0)),
        "MsgSvrID": draw(st.text(min_size=10, max_size=20)),
        "token": draw(st.text(min_size=10, max_size=40)),
        "ts": draw(st.integers(min_value=1700000000, max_value=1800000000)),
    }


@st.composite
def sticker_message_strategy(draw):
    """生成 STICKER 模态消息"""
    return {
        "msg_uid": draw(st.text(min_size=5, max_size=30)),
        "time_local": draw(st.from_regex(r"2025-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", fullmatch=True)),
        "speaker": draw(st.sampled_from(["ME", "OTHER"])),
        "modality": "sticker",
        "type": 47,
        "sub_type": 0,
        "text_raw": "http://example.com/sticker.gif",
        "sticker_summary": draw(st.text(min_size=5, max_size=50)),
        "sticker_intent": draw(st.sampled_from(["开心", "惊讶", "无奈", ""])),
        "sticker_ocr_text": draw(st.one_of(st.just(""), st.text(min_size=1, max_size=30))),
        "sticker_url": "http://example.com/sticker.gif",
        "sticker_http_status": 200,
        "sticker_bytes": 10240,
        "sticker_caption": "很长的表情包描述...",
        "seq_in_html": draw(st.integers(min_value=0)),
        "MsgSvrID": draw(st.text(min_size=10, max_size=20)),
        "token": draw(st.text(min_size=10, max_size=40)),
        "ts": draw(st.integers(min_value=1700000000, max_value=1800000000)),
    }


@st.composite
def link_message_strategy(draw):
    """生成 LINK_OR_FILE 模态消息"""
    sub_type = draw(st.sampled_from(["quote", "miniprogram", "link", "file"]))
    msg = {
        "msg_uid": draw(st.text(min_size=5, max_size=30)),
        "time_local": draw(st.from_regex(r"2025-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", fullmatch=True)),
        "speaker": draw(st.sampled_from(["ME", "OTHER"])),
        "modality": "link_or_file",
        "type": 49,
        "sub_type": 57 if sub_type == "quote" else 33,
        "link_sub_type": sub_type,
        "text_raw": draw(st.text(min_size=1, max_size=100)),
        "link_title": draw(st.one_of(st.just(""), st.text(min_size=1, max_size=50))),
        "link_quote_text": draw(st.one_of(st.just(""), st.text(min_size=1, max_size=100))) if sub_type == "quote" else "",
        "link_url": "http://example.com",
        "link_quote_svrid": "12345",
        "seq_in_html": draw(st.integers(min_value=0)),
        "MsgSvrID": draw(st.text(min_size=10, max_size=20)),
        "token": draw(st.text(min_size=10, max_size=40)),
        "ts": draw(st.integers(min_value=1700000000, max_value=1800000000)),
    }
    return msg


@st.composite
def system_message_strategy(draw):
    """生成 SYSTEM 模态消息（时间间隔）"""
    return {
        "msg_uid": draw(st.text(min_size=5, max_size=30)),
        "time_local": draw(st.from_regex(r"2025-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", fullmatch=True)),
        "speaker": "SYSTEM",
        "modality": "system",
        "type": "time_gap",
        "text_raw": "[2小时后]",
        "gap_seconds": draw(st.integers(min_value=3600, max_value=86400)),
        "gap_description": "2小时后",
        "break_type": draw(st.sampled_from(["topic_change", "day_change"])),
        "context": {"before_speaker": "ME", "after_speaker": "OTHER"},
        "ts": draw(st.integers(min_value=1700000000, max_value=1800000000)),
    }


@st.composite
def any_message_strategy(draw):
    """生成任意模态消息"""
    strategy = draw(st.sampled_from([
        text_message_strategy(),
        image_message_strategy(),
        voice_message_strategy(),
        video_message_strategy(),
        sticker_message_strategy(),
        link_message_strategy(),
        system_message_strategy(),
    ]))
    return draw(strategy)


@st.composite
def l2_message_strategy(draw):
    """生成带 L2 额外字段的消息"""
    msg = draw(any_message_strategy())
    msg["day_index"] = draw(st.integers(min_value=0, max_value=100))
    msg["ts_relative"] = f"第{msg['day_index'] + 1}天"
    msg["ts_shifted"] = msg.get("ts", 1700000000) - 8640000
    return msg


# ============== Property 2: 消息类型映射正确性 ==============

class TestMsgTypeMapping:
    """测试 msg_type 映射正确性"""
    
    @settings(max_examples=100)
    @given(text_message_strategy())
    def test_text_maps_to_wenben(self, msg):
        """Feature: sft-field-trimming, Property 2: TEXT -> 文本"""
        trimmer = SFTTrimmer()
        result = trimmer.trim_message(msg)
        assert result["msg_type"] == "文本"
    
    @settings(max_examples=100)
    @given(image_message_strategy())
    def test_image_maps_to_tupian(self, msg):
        """Feature: sft-field-trimming, Property 2: IMAGE -> 图片"""
        trimmer = SFTTrimmer()
        result = trimmer.trim_message(msg)
        assert result["msg_type"] == "图片"
    
    @settings(max_examples=100)
    @given(voice_message_strategy())
    def test_voice_maps_to_yuyin(self, msg):
        """Feature: sft-field-trimming, Property 2: VOICE -> 语音"""
        trimmer = SFTTrimmer()
        result = trimmer.trim_message(msg)
        assert result["msg_type"] == "语音"
    
    @settings(max_examples=100)
    @given(video_message_strategy())
    def test_video_maps_to_shipin(self, msg):
        """Feature: sft-field-trimming, Property 2: VIDEO -> 视频"""
        trimmer = SFTTrimmer()
        result = trimmer.trim_message(msg)
        assert result["msg_type"] == "视频"
    
    @settings(max_examples=100)
    @given(sticker_message_strategy())
    def test_sticker_maps_to_biaoqingbao(self, msg):
        """Feature: sft-field-trimming, Property 2: STICKER -> 表情包"""
        trimmer = SFTTrimmer()
        result = trimmer.trim_message(msg)
        assert result["msg_type"] == "表情包"
    
    @settings(max_examples=100)
    @given(link_message_strategy())
    def test_link_maps_correctly(self, msg):
        """Feature: sft-field-trimming, Property 2: LINK_OR_FILE -> 正确子类型"""
        trimmer = SFTTrimmer()
        result = trimmer.trim_message(msg)
        
        sub_type = msg.get("link_sub_type", "")
        expected_map = {
            "quote": "引用",
            "miniprogram": "小程序",
            "link": "链接",
            "file": "文件"
        }
        expected = expected_map.get(sub_type, "链接/文件")
        assert result["msg_type"] == expected
    
    @settings(max_examples=100)
    @given(system_message_strategy())
    def test_system_maps_to_time_gap(self, msg):
        """Feature: sft-field-trimming, Property 2: SYSTEM time_gap -> 时间间隔"""
        trimmer = SFTTrimmer()
        result = trimmer.trim_message(msg)
        assert result["msg_type"] == "时间间隔"


# ============== Property 1: 核心字段完整性 ==============

class TestCoreFieldsIntegrity:
    """测试核心字段完整性"""
    
    @settings(max_examples=100)
    @given(any_message_strategy())
    def test_core_fields_present(self, msg):
        """Feature: sft-field-trimming, Property 1: 核心字段完整性"""
        trimmer = SFTTrimmer()
        result = trimmer.trim_message(msg)
        
        assert "msg_uid" in result
        assert "time_local" in result
        assert "speaker" in result
        assert "msg_type" in result


# ============== Property 8: L2 额外字段保留 ==============

class TestL2ExtraFields:
    """测试 L2 额外字段保留"""
    
    @settings(max_examples=100)
    @given(l2_message_strategy())
    def test_l2_extra_fields_preserved(self, msg):
        """Feature: sft-field-trimming, Property 8: L2 额外字段保留"""
        trimmer = SFTTrimmer(is_l2=True)
        result = trimmer.trim_message(msg)
        
        assert "day_index" in result
        assert "ts_relative" in result
    
    @settings(max_examples=100)
    @given(l2_message_strategy())
    def test_l1_mode_no_extra_fields(self, msg):
        """Feature: sft-field-trimming, Property 8: L1 模式不保留 L2 字段"""
        trimmer = SFTTrimmer(is_l2=False)
        result = trimmer.trim_message(msg)
        
        # L1 模式不应保留这些字段
        assert "day_index" not in result
        assert "ts_relative" not in result


# ============== Property 3: 空值字段移除 ==============

class TestEmptyFieldsRemoval:
    """测试空值字段移除"""
    
    @settings(max_examples=100)
    @given(any_message_strategy())
    def test_no_null_values(self, msg):
        """Feature: sft-field-trimming, Property 3: 无 null 值"""
        trimmer = SFTTrimmer()
        result = trimmer.trim_message(msg)
        
        for key, value in result.items():
            assert value is not None, f"字段 {key} 不应为 null"
    
    @settings(max_examples=100)
    @given(any_message_strategy())
    def test_no_empty_strings(self, msg):
        """Feature: sft-field-trimming, Property 3: 无空字符串"""
        trimmer = SFTTrimmer()
        result = trimmer.trim_message(msg)
        
        for key, value in result.items():
            if isinstance(value, str):
                assert value != "", f"字段 {key} 不应为空字符串"
    
    @settings(max_examples=100)
    @given(any_message_strategy())
    def test_no_empty_arrays(self, msg):
        """Feature: sft-field-trimming, Property 3: 无空数组"""
        trimmer = SFTTrimmer()
        result = trimmer.trim_message(msg)
        
        for key, value in result.items():
            if isinstance(value, list):
                assert len(value) > 0, f"字段 {key} 不应为空数组"


# ============== Property 4: 元数据字段移除 ==============

class TestMetadataRemoval:
    """测试元数据字段移除"""
    
    METADATA_FIELDS = [
        "seq_in_html", "MsgSvrID", "token", "ts", "modality", "type", "sub_type",
        "media_path", "image_route_class", "image_triage_confidence", "image_nsfw_score",
        "image_sfw_score", "image_text_score", "image_ok", "image_width", "image_height",
        "image_is_long", "image_need_ocr", "image_expert_used", "image_is_fallback",
        "image_ensemble_mode", "image_ensemble_used", "image_caption_model",
        "image_compression_ratio", "image_is_compressed", "image_caption",
        "asr_engine", "asr_raw_text", "asr_patches", "event_tags",
        "video_keyframes", "video_metadata", "video_audit", "video_asr_engine",
        "video_asr_segments", "video_event_tags", "video_trigger_reasons",
        "video_voice_analysis", "video_events", "video_content_type",
        "video_triage_confidence", "video_is_compressed", "video_compression_ratio",
        "sticker_url", "sticker_file_sha256", "sticker_http_status", "sticker_bytes",
        "sticker_detected_format", "sticker_content_type_reported", "sticker_mismatch",
        "sticker_final_path", "sticker_decode_ok", "sticker_width", "sticker_height",
        "sticker_class", "sticker_is_animated", "sticker_n_frames", "sticker_thumb_path",
        "sticker_contact_sheet_path", "sticker_content_type", "sticker_max_nsfw_score",
        "sticker_is_sensitive", "sticker_expert_used", "sticker_intent_confidence",
        "sticker_caption", "link_url", "link_quote_svrid", "link_quote_type",
        "miniprogram_appid", "link_miniprogram_appid", "quote_svrid", "quote_type",
        "quote_text", "link_sub_type", "gap_seconds", "context",
        "merged_ts_range", "original_ids"
    ]
    
    @settings(max_examples=100)
    @given(any_message_strategy())
    def test_metadata_fields_removed(self, msg):
        """Feature: sft-field-trimming, Property 4: 元数据字段移除"""
        trimmer = SFTTrimmer()
        result = trimmer.trim_message(msg)
        
        for field in self.METADATA_FIELDS:
            assert field not in result, f"元数据字段 {field} 应被移除"


# ============== Property 5: 模态字段白名单 ==============

class TestModalityFieldWhitelist:
    """测试模态字段白名单"""
    
    def _get_allowed_fields(self, modality: str, is_l2: bool = False) -> set:
        """获取模态允许的字段集合"""
        allowed = set(FIELD_CONFIG["core"]) | {"msg_type"}
        if is_l2:
            allowed |= set(FIELD_CONFIG["core_l2_extra"])
        if modality in FIELD_CONFIG:
            allowed |= set(FIELD_CONFIG[modality])
        return allowed
    
    @settings(max_examples=100)
    @given(text_message_strategy())
    def test_text_whitelist(self, msg):
        """Feature: sft-field-trimming, Property 5: TEXT 字段白名单"""
        trimmer = SFTTrimmer()
        result = trimmer.trim_message(msg)
        allowed = self._get_allowed_fields("text")
        
        for field in result.keys():
            assert field in allowed, f"TEXT 消息不应包含字段 {field}"
    
    @settings(max_examples=100)
    @given(image_message_strategy())
    def test_image_whitelist(self, msg):
        """Feature: sft-field-trimming, Property 5: IMAGE 字段白名单"""
        trimmer = SFTTrimmer()
        result = trimmer.trim_message(msg)
        allowed = self._get_allowed_fields("image")
        
        for field in result.keys():
            assert field in allowed, f"IMAGE 消息不应包含字段 {field}"
    
    @settings(max_examples=100)
    @given(voice_message_strategy())
    def test_voice_whitelist(self, msg):
        """Feature: sft-field-trimming, Property 5: VOICE 字段白名单"""
        trimmer = SFTTrimmer()
        result = trimmer.trim_message(msg)
        allowed = self._get_allowed_fields("voice")
        
        for field in result.keys():
            assert field in allowed, f"VOICE 消息不应包含字段 {field}"
    
    @settings(max_examples=100)
    @given(video_message_strategy())
    def test_video_whitelist(self, msg):
        """Feature: sft-field-trimming, Property 5: VIDEO 字段白名单"""
        trimmer = SFTTrimmer()
        result = trimmer.trim_message(msg)
        allowed = self._get_allowed_fields("video")
        
        for field in result.keys():
            assert field in allowed, f"VIDEO 消息不应包含字段 {field}"
    
    @settings(max_examples=100)
    @given(sticker_message_strategy())
    def test_sticker_whitelist(self, msg):
        """Feature: sft-field-trimming, Property 5: STICKER 字段白名单"""
        trimmer = SFTTrimmer()
        result = trimmer.trim_message(msg)
        allowed = self._get_allowed_fields("sticker")
        
        for field in result.keys():
            assert field in allowed, f"STICKER 消息不应包含字段 {field}"
    
    @settings(max_examples=100)
    @given(link_message_strategy())
    def test_link_whitelist(self, msg):
        """Feature: sft-field-trimming, Property 5: LINK_OR_FILE 字段白名单"""
        trimmer = SFTTrimmer()
        result = trimmer.trim_message(msg)
        allowed = self._get_allowed_fields("link_or_file")
        
        for field in result.keys():
            assert field in allowed, f"LINK_OR_FILE 消息不应包含字段 {field}"
    
    @settings(max_examples=100)
    @given(system_message_strategy())
    def test_system_whitelist(self, msg):
        """Feature: sft-field-trimming, Property 5: SYSTEM 字段白名单"""
        trimmer = SFTTrimmer()
        result = trimmer.trim_message(msg)
        allowed = self._get_allowed_fields("system")
        
        for field in result.keys():
            assert field in allowed, f"SYSTEM 消息不应包含字段 {field}"


# ============== Property 6 & 7: 文件处理测试 ==============

import tempfile
import os

class TestFileProcessing:
    """测试文件处理功能"""
    
    def test_json_format_correctness(self):
        """Feature: sft-field-trimming, Property 7: JSON 格式正确性"""
        # 创建临时输入文件
        messages = [
            {"msg_uid": "1", "time_local": "2025-01-01 10:00:00", "speaker": "ME", "modality": "text", "text_raw": "hello"},
            {"msg_uid": "2", "time_local": "2025-01-01 10:01:00", "speaker": "OTHER", "modality": "text", "text_raw": "hi"},
        ]
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
            for msg in messages:
                f.write(json.dumps(msg, ensure_ascii=False) + "\n")
            input_path = f.name
        
        output_path = input_path.replace('.jsonl', '_sft.jsonl')
        
        try:
            trimmer = SFTTrimmer()
            trimmer.process_file(input_path, output_path)
            
            # 验证输出文件每行都是有效 JSON
            with open(output_path, 'r', encoding='utf-8') as f:
                for line in f:
                    result = json.loads(line.strip())
                    assert isinstance(result, dict)
        finally:
            os.unlink(input_path)
            if os.path.exists(output_path):
                os.unlink(output_path)
    
    def test_time_order_preserved(self):
        """Feature: sft-field-trimming, Property 6: 时间顺序保持"""
        messages = [
            {"msg_uid": "1", "time_local": "2025-01-01 10:00:00", "speaker": "ME", "modality": "text", "text_raw": "first"},
            {"msg_uid": "2", "time_local": "2025-01-01 10:01:00", "speaker": "OTHER", "modality": "text", "text_raw": "second"},
            {"msg_uid": "3", "time_local": "2025-01-01 10:02:00", "speaker": "ME", "modality": "text", "text_raw": "third"},
        ]
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
            for msg in messages:
                f.write(json.dumps(msg, ensure_ascii=False) + "\n")
            input_path = f.name
        
        output_path = input_path.replace('.jsonl', '_sft.jsonl')
        
        try:
            trimmer = SFTTrimmer()
            trimmer.process_file(input_path, output_path)
            
            # 验证输出顺序与输入一致
            with open(output_path, 'r', encoding='utf-8') as f:
                results = [json.loads(line.strip()) for line in f]
            
            assert len(results) == 3
            assert results[0]["time_local"] == "2025-01-01 10:00:00"
            assert results[1]["time_local"] == "2025-01-01 10:01:00"
            assert results[2]["time_local"] == "2025-01-01 10:02:00"
        finally:
            os.unlink(input_path)
            if os.path.exists(output_path):
                os.unlink(output_path)


# ============== 单元测试：具体示例 ==============

class TestSpecificExamples:
    """测试具体示例"""
    
    def test_video_keyframes_removed(self):
        """验证 video_keyframes 被移除"""
        msg = {
            "msg_uid": "P1:123",
            "time_local": "2025-07-14 22:38:44",
            "speaker": "OTHER",
            "modality": "video",
            "video_summary": "一只猫在床上休息",
            "video_keyframes": [
                {"frame_id": 0, "caption": "很长的描述1..."},
                {"frame_id": 1, "caption": "很长的描述2..."},
            ],
            "video_metadata": {"duration_sec": 10.0},
        }
        
        trimmer = SFTTrimmer()
        result = trimmer.trim_message(msg)
        
        assert "video_keyframes" not in result
        assert "video_metadata" not in result
        assert result["video_summary"] == "一只猫在床上休息"
    
    def test_sticker_caption_removed(self):
        """验证 sticker_caption 被移除，保留 sticker_summary"""
        msg = {
            "msg_uid": "P1:456",
            "time_local": "2025-06-16 10:28:19",
            "speaker": "OTHER",
            "modality": "sticker",
            "sticker_caption": "[表情包: 很长的描述...]",
            "sticker_summary": "[惊讶/震惊]",
            "sticker_intent": "惊讶/震惊",
        }
        
        trimmer = SFTTrimmer()
        result = trimmer.trim_message(msg)
        
        assert "sticker_caption" not in result
        assert result["sticker_summary"] == "[惊讶/震惊]"
    
    def test_image_caption_removed(self):
        """验证 image_caption 被移除，保留 image_summary"""
        msg = {
            "msg_uid": "P1:789",
            "time_local": "2025-06-17 10:21:12",
            "speaker": "OTHER",
            "modality": "image",
            "image_caption": "很长的图片描述...",
            "image_summary": "[聊天截图] 微信截图",
            "image_ocr_text": "摸鱼学导论",
        }
        
        trimmer = SFTTrimmer()
        result = trimmer.trim_message(msg)
        
        assert "image_caption" not in result
        assert result["image_summary"] == "[聊天截图] 微信截图"
    
    def test_quote_message_preserves_link_quote_text(self):
        """验证引用消息保留 link_quote_text"""
        msg = {
            "msg_uid": "P1:abc",
            "time_local": "2025-06-16 10:44:22",
            "speaker": "ME",
            "modality": "link_or_file",
            "link_sub_type": "quote",
            "text_raw": "噢？是啥",
            "link_quote_text": "OTHER: 觉得，还是有一丢丢准的",
            "quote_text": "艾里Sun Sun：觉得，还是有一丢丢准的",  # 原始未匿名化的
        }
        
        trimmer = SFTTrimmer()
        result = trimmer.trim_message(msg)
        
        assert result["msg_type"] == "引用"
        assert result["text_raw"] == "噢？是啥"
        assert result["link_quote_text"] == "OTHER: 觉得，还是有一丢丢准的"
        assert "quote_text" not in result  # 原始字段应被移除
    
    def test_sticker_ref_fallback_to_caption(self):
        """验证 sticker_summary 为 REF 时使用 sticker_caption 作为 fallback"""
        msg = {
            "msg_uid": "P1:7689074718049439347",
            "time_local": "2025-07-26 15:24:53",
            "speaker": "ME",
            "modality": "sticker",
            "sticker_summary": "[REF:8bfda471]",
            "sticker_caption": "[表情包: 狗狗在餐桌前等待蛋糕]",
            "sticker_intent": "表达情绪",
        }
        
        trimmer = SFTTrimmer()
        result = trimmer.trim_message(msg)
        
        assert result["sticker_summary"] == "[表情包: 狗狗在餐桌前等待蛋糕]"
        assert "sticker_caption" not in result
    
    def test_sticker_summary_removes_repetitive_ocr(self):
        """验证 sticker_summary 中的重复 OCR 文字被移除"""
        msg = {
            "msg_uid": "P1:7438538458213443178",
            "time_local": "2025-07-27 22:58:21",
            "speaker": "ME",
            "modality": "sticker",
            "sticker_summary": "[开心/高兴] (文字: DL DL DL Dl Dl DL)",
            "sticker_intent": "开心/高兴",
            "sticker_ocr_text": "DL DL DL Dl Dl DL",
        }
        
        trimmer = SFTTrimmer()
        result = trimmer.trim_message(msg)
        
        # summary 中的重复 OCR 应被移除
        assert result["sticker_summary"] == "[开心/高兴]"
        # OCR 文本应去重（大小写不敏感，保留第一个出现的形式）
        assert result["sticker_ocr_text"] == "DL"
    
    def test_sticker_ocr_deduplication(self):
        """验证动画 GIF 多帧 OCR 去重"""
        msg = {
            "msg_uid": "P1:6516893563260478165",
            "time_local": "2025-07-29 23:10:12",
            "speaker": "OTHER",
            "modality": "sticker",
            "sticker_summary": "[REF:cc557747]",
            "sticker_caption": "[表情包: 你这个大便]",
            "sticker_intent": "表达情绪",
            "sticker_ocr_text": "你这个 你这个 你这个 大便 大便 大便",
        }
        
        trimmer = SFTTrimmer()
        result = trimmer.trim_message(msg)
        
        # REF 应 fallback 到 caption
        assert result["sticker_summary"] == "[表情包: 你这个大便]"
        # OCR 应去重
        assert result["sticker_ocr_text"] == "你这个 大便"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
