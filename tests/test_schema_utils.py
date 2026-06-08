"""
test_schema_utils.py
schema_utils 模块的单元测试

测试内容：
1. 常量定义测试
2. build_common_header 函数测试
3. reorder_record 函数测试
4. migrate_legacy_record 函数测试

运行方式：
    python tests/test_schema_utils.py
"""

import unittest
from collections import OrderedDict

from scripts._common.schema_utils import (
    SCHEMA_VERSION,
    COMMON_HEADER_FIELDS,
    IMAGE_SPECIFIC_FIELDS,
    VOICE_SPECIFIC_FIELDS,
    VIDEO_SPECIFIC_FIELDS,
    STICKER_SPECIFIC_FIELDS,
    MODALITY_SPECIFIC_FIELDS,
    build_common_header,
    reorder_record,
    migrate_legacy_record,
)


# =============================================================================
# 常量定义测试
# =============================================================================

class TestConstants(unittest.TestCase):
    """测试常量定义"""
    
    def test_schema_version(self):
        """测试 SCHEMA_VERSION 常量"""
        self.assertEqual(SCHEMA_VERSION, "merged_v2")
    
    def test_common_header_fields_order(self):
        """测试 COMMON_HEADER_FIELDS 顺序"""
        expected = [
            "schema_version", "seq_in_html", "msg_uid", "MsgSvrID",
            "token", "ts", "time_local", "speaker", "type", "sub_type",
            "modality", "media_path"
        ]
        self.assertEqual(COMMON_HEADER_FIELDS, expected)
    
    def test_common_header_fields_count(self):
        """测试 COMMON_HEADER_FIELDS 字段数量"""
        self.assertEqual(len(COMMON_HEADER_FIELDS), 12)
    
    def test_schema_version_is_first(self):
        """测试 schema_version 是第一个字段"""
        self.assertEqual(COMMON_HEADER_FIELDS[0], "schema_version")
    
    def test_modality_specific_fields_mapping(self):
        """测试 MODALITY_SPECIFIC_FIELDS 映射"""
        self.assertEqual(MODALITY_SPECIFIC_FIELDS["image"], IMAGE_SPECIFIC_FIELDS)
        self.assertEqual(MODALITY_SPECIFIC_FIELDS["voice"], VOICE_SPECIFIC_FIELDS)
        self.assertEqual(MODALITY_SPECIFIC_FIELDS["video"], VIDEO_SPECIFIC_FIELDS)
        self.assertEqual(MODALITY_SPECIFIC_FIELDS["sticker"], STICKER_SPECIFIC_FIELDS)
    
    def test_image_specific_fields_contains_key_fields(self):
        """测试 IMAGE_SPECIFIC_FIELDS 包含关键字段"""
        self.assertIn("caption", IMAGE_SPECIFIC_FIELDS)
        self.assertIn("ocr_text", IMAGE_SPECIFIC_FIELDS)
        self.assertIn("content_type", IMAGE_SPECIFIC_FIELDS)
    
    def test_voice_specific_fields_contains_key_fields(self):
        """测试 VOICE_SPECIFIC_FIELDS 包含关键字段"""
        self.assertIn("punct_text", VOICE_SPECIFIC_FIELDS)
        self.assertIn("primary_engine", VOICE_SPECIFIC_FIELDS)
        self.assertIn("sensevoice", VOICE_SPECIFIC_FIELDS)
    
    def test_video_specific_fields_contains_key_fields(self):
        """测试 VIDEO_SPECIFIC_FIELDS 包含关键字段"""
        self.assertIn("file", VIDEO_SPECIFIC_FIELDS)
        self.assertIn("transcription", VIDEO_SPECIFIC_FIELDS)
        self.assertIn("video_understanding", VIDEO_SPECIFIC_FIELDS)
    
    def test_sticker_specific_fields_contains_key_fields(self):
        """测试 STICKER_SPECIFIC_FIELDS 包含关键字段"""
        self.assertIn("url", STICKER_SPECIFIC_FIELDS)
        self.assertIn("caption", STICKER_SPECIFIC_FIELDS)
        self.assertIn("is_animated", STICKER_SPECIFIC_FIELDS)


# =============================================================================
# build_common_header 函数测试
# =============================================================================

class TestBuildCommonHeader(unittest.TestCase):
    """测试 build_common_header 函数"""
    
    def test_defaults_only(self):
        """测试仅使用默认值"""
        header = build_common_header()
        self.assertEqual(header["schema_version"], SCHEMA_VERSION)
        self.assertEqual(header["seq_in_html"], -1)
        self.assertEqual(header["msg_uid"], "")
        self.assertEqual(header["speaker"], "UNKNOWN")
        self.assertEqual(header["ts"], 0)
        self.assertIsNone(header["media_path"])
    
    def test_from_raw_record(self):
        """测试从原始记录构建"""
        raw = {
            "msg_uid": "P1:123456",
            "ts": 1749279243,
            "speaker": "ME",
            "type": 3,
            "modality": "image",
        }
        header = build_common_header(raw_record=raw)
        self.assertEqual(header["msg_uid"], "P1:123456")
        self.assertEqual(header["ts"], 1749279243)
        self.assertEqual(header["speaker"], "ME")
        self.assertEqual(header["type"], 3)
        self.assertEqual(header["modality"], "image")
        # 未提供的字段使用默认值
        self.assertEqual(header["seq_in_html"], -1)
    
    def test_overrides(self):
        """测试 overrides 参数"""
        header = build_common_header(modality="voice", media_path="voice/test.mp3")
        self.assertEqual(header["modality"], "voice")
        self.assertEqual(header["media_path"], "voice/test.mp3")
    
    def test_overrides_priority(self):
        """测试 overrides 优先级高于 raw_record"""
        raw = {"msg_uid": "P1:old", "speaker": "OTHER"}
        header = build_common_header(raw_record=raw, msg_uid="P1:new")
        self.assertEqual(header["msg_uid"], "P1:new")
        self.assertEqual(header["speaker"], "OTHER")
    
    def test_raw_record_none_values_ignored(self):
        """测试 raw_record 中的 None 值不覆盖默认值"""
        raw = {"msg_uid": None, "speaker": "ME"}
        header = build_common_header(raw_record=raw)
        self.assertEqual(header["msg_uid"], "")  # 默认值
        self.assertEqual(header["speaker"], "ME")
    
    def test_all_common_fields_present(self):
        """测试返回包含所有公共字段"""
        header = build_common_header()
        for field in COMMON_HEADER_FIELDS:
            self.assertIn(field, header, f"缺少字段: {field}")


# =============================================================================
# reorder_record 函数测试
# =============================================================================

class TestReorderRecord(unittest.TestCase):
    """测试 reorder_record 函数"""
    
    def test_basic_reorder(self):
        """测试基本字段重排"""
        record = {
            "caption": "测试图片",
            "msg_uid": "P1:123",
            "schema_version": "merged_v2",
            "ts": 1749279243,
        }
        result = reorder_record(record, "image")
        keys = list(result.keys())
        # schema_version 应该在最前面
        self.assertEqual(keys[0], "schema_version")
        # msg_uid 应该在 caption 之前
        self.assertLess(keys.index("msg_uid"), keys.index("caption"))
    
    def test_field_mapping_timestamp_to_ts(self):
        """测试字段映射: timestamp → ts"""
        record = {"timestamp": 1749279243, "msg_uid": "P1:123"}
        result = reorder_record(record, "image")
        self.assertIn("ts", result)
        self.assertNotIn("timestamp", result)
        self.assertEqual(result["ts"], 1749279243)
    
    def test_field_mapping_sender_to_speaker(self):
        """测试字段映射: sender → speaker"""
        record = {"sender": "ME", "msg_uid": "P1:123"}
        result = reorder_record(record, "image")
        self.assertIn("speaker", result)
        self.assertNotIn("sender", result)
        self.assertEqual(result["speaker"], "ME")
    
    def test_no_data_loss(self):
        """测试不丢失任何字段"""
        record = {
            "msg_uid": "P1:123",
            "caption": "测试",
            "custom_field": "自定义值",
            "another_field": 42,
        }
        result = reorder_record(record, "image")
        self.assertEqual(result["msg_uid"], "P1:123")
        self.assertEqual(result["caption"], "测试")
        self.assertEqual(result["custom_field"], "自定义值")
        self.assertEqual(result["another_field"], 42)
    
    def test_include_schema_version_false(self):
        """测试 include_schema_version=False"""
        record = {"schema_version": "merged_v2", "msg_uid": "P1:123"}
        result = reorder_record(record, "image", include_schema_version=False)
        self.assertNotIn("schema_version", result)
        self.assertIn("msg_uid", result)
    
    def test_returns_ordered_dict(self):
        """测试返回 OrderedDict"""
        record = {"msg_uid": "P1:123"}
        result = reorder_record(record, "image")
        self.assertIsInstance(result, OrderedDict)
    
    def test_common_fields_before_specific(self):
        """测试公共字段在特定字段之前"""
        record = {
            "caption": "测试",
            "msg_uid": "P1:123",
            "ts": 1749279243,
            "content_type": "TYPE_C_NORMAL",
        }
        result = reorder_record(record, "image")
        keys = list(result.keys())
        # 公共字段应该在特定字段之前
        self.assertLess(keys.index("msg_uid"), keys.index("caption"))
        self.assertLess(keys.index("ts"), keys.index("content_type"))
    
    def test_all_modalities(self):
        """测试所有模态"""
        for modality in ["image", "voice", "video", "sticker"]:
            record = {"msg_uid": "P1:123", "ts": 1749279243}
            result = reorder_record(record, modality)
            self.assertIsInstance(result, OrderedDict)
            self.assertIn("msg_uid", result)


# =============================================================================
# migrate_legacy_record 函数测试
# =============================================================================

class TestMigrateLegacyRecord(unittest.TestCase):
    """测试 migrate_legacy_record 函数"""
    
    def test_already_new_format(self):
        """测试已是新格式的记录"""
        record = {"schema_version": "merged_v2", "msg_uid": "P1:123"}
        result = migrate_legacy_record(record, "image")
        self.assertEqual(result, record)
    
    def test_adds_schema_version(self):
        """测试添加 schema_version"""
        record = {"msg_uid": "P1:123", "ts": 1749279243}
        result = migrate_legacy_record(record, "image")
        self.assertEqual(result["schema_version"], SCHEMA_VERSION)
    
    def test_field_mapping_image(self):
        """测试 image 模态字段映射"""
        record = {"timestamp": 1749279243, "sender": "ME", "caption": "测试"}
        result = migrate_legacy_record(record, "image")
        self.assertIn("ts", result)
        self.assertNotIn("timestamp", result)
        self.assertIn("speaker", result)
        self.assertNotIn("sender", result)
        self.assertEqual(result["ts"], 1749279243)
        self.assertEqual(result["speaker"], "ME")
    
    def test_field_mapping_voice_file(self):
        """测试 voice 模态 file → media_path"""
        record = {"file": "voice/test.mp3", "punct_text": "你好"}
        result = migrate_legacy_record(record, "voice")
        self.assertEqual(result["media_path"], "voice/test.mp3")
        self.assertNotIn("file", result)
    
    def test_video_file_preserved(self):
        """测试 video 模态 file 字段保留"""
        record = {"file": "test.mp4", "video_sha256": "abc123"}
        result = migrate_legacy_record(record, "video")
        self.assertEqual(result["file"], "test.mp4")
    
    def test_preserves_all_data(self):
        """测试保留所有原始数据"""
        record = {
            "timestamp": 1749279243,
            "sender": "ME",
            "caption": "测试",
            "custom_field": "自定义值",
        }
        result = migrate_legacy_record(record, "image")
        self.assertEqual(result["caption"], "测试")
        self.assertEqual(result["custom_field"], "自定义值")
    
    def test_field_order_after_migration(self):
        """测试迁移后字段顺序"""
        record = {"caption": "测试", "timestamp": 1749279243}
        result = migrate_legacy_record(record, "image")
        keys = list(result.keys())
        self.assertEqual(keys[0], "schema_version")
    
    def test_old_schema_version_replaced(self):
        """测试旧 schema_version 被替换"""
        record = {"schema_version": "old_version", "msg_uid": "P1:123"}
        result = migrate_legacy_record(record, "image")
        self.assertEqual(result["schema_version"], SCHEMA_VERSION)


# =============================================================================
# 运行测试
# =============================================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)
