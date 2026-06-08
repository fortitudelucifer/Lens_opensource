"""
test_telegram_adapter.py
Telegram Desktop JSON 导出适配器的单元测试 + 属性测试

验证：
- TelegramAdapter 基本属性（source_type、describe）
- validate_input 校验逻辑
- detect_media_files 媒体文件检测
- parse() 解析 result.json 输出标准消息格式
- 消息类型映射正确性（media_type/photo/file → modality）
- msg_uid 格式：TG:{id}
- participant_map → speaker 映射
- 富文本数组展平为纯文本

Requirements: 5.1, 5.2, 5.3, 5.4
"""

import json
import pytest
from pathlib import Path

from scripts.workspace.ingestion.adapters.telegram_json import (
    TelegramAdapter,
    flatten_text,
    get_telegram_modality,
    get_telegram_media_path,
    map_speaker,
    TELEGRAM_MEDIA_TYPE_MAP,
)
from scripts.workspace.ingestion.manifest import SourceManifest
from scripts.workspace.ingestion.schema import VALID_MODALITIES


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def adapter():
    return TelegramAdapter()


@pytest.fixture
def manifest():
    """基础 manifest，包含 participant_map"""
    return SourceManifest(
        source_type="telegram_json",
        input_paths=["./result.json"],
        participant_map={"John Doe": "OTHER", "我": "ME"},
    )


@pytest.fixture
def manifest_no_map():
    """不含 participant_map 的 manifest"""
    return SourceManifest(
        source_type="telegram_json",
        input_paths=["./result.json"],
    )


def _make_telegram_json(messages: list[dict]) -> str:
    """生成 Telegram 导出 JSON"""
    data = {
        "name": "Test Chat",
        "type": "personal_chat",
        "messages": messages,
    }
    return json.dumps(data, ensure_ascii=False)


# ── 基本属性测试 ──────────────────────────────────────────────────────

class TestTelegramAdapterBasic:

    def test_supported_source_type(self, adapter):
        assert adapter.supported_source_type() == "telegram_json"

    def test_describe_returns_correct_structure(self, adapter):
        info = adapter.describe()
        assert info["source_type"] == "telegram_json"
        assert "Telegram" in info["description"]
        assert len(info["expected_files"]) == 1
        assert isinstance(info["field_mapping_example"], dict)


# ── flatten_text 测试 ─────────────────────────────────────────────────

class TestFlattenText:

    def test_string_input(self):
        assert flatten_text("Hello") == "Hello"

    def test_empty_string(self):
        assert flatten_text("") == ""

    def test_list_of_strings(self):
        assert flatten_text(["Hello", " ", "World"]) == "Hello World"

    def test_list_of_dicts(self):
        result = flatten_text([
            {"type": "bold", "text": "粗体"},
            {"type": "link", "text": "链接"},
        ])
        assert result == "粗体链接"

    def test_mixed_list(self):
        result = flatten_text([
            "普通文本",
            {"type": "bold", "text": "粗体"},
            " 后续",
        ])
        assert result == "普通文本粗体 后续"

    def test_dict_without_text_key(self):
        result = flatten_text([{"type": "mention_name", "user_id": 123}])
        assert result == ""

    def test_none_input(self):
        assert flatten_text(None) == ""

    def test_numeric_input(self):
        assert flatten_text(42) == "42"

    def test_empty_list(self):
        assert flatten_text([]) == ""


# ── get_telegram_modality 测试 ────────────────────────────────────────

class TestGetTelegramModality:

    @pytest.mark.parametrize("media_type,expected", [
        ("sticker", "sticker"),
        ("animation", "sticker"),
        ("voice_message", "voice"),
        ("video_message", "video"),
        ("video_file", "video"),
    ])
    def test_known_media_types(self, media_type, expected):
        msg = {"media_type": media_type}
        assert get_telegram_modality(msg) == expected

    def test_photo_without_media_type(self):
        msg = {"photo": "photos/photo.jpg"}
        assert get_telegram_modality(msg) == "image"

    def test_file_without_media_type(self):
        msg = {"file": "files/doc.pdf"}
        assert get_telegram_modality(msg) == "link_or_file"

    def test_no_media(self):
        msg = {"text": "Hello"}
        assert get_telegram_modality(msg) == "text"

    def test_media_type_takes_priority_over_photo(self):
        """media_type 优先于 photo 字段"""
        msg = {"media_type": "sticker", "photo": "photos/photo.jpg"}
        assert get_telegram_modality(msg) == "sticker"

    def test_unknown_media_type_with_photo(self):
        """未知 media_type 但有 photo → image"""
        msg = {"media_type": "unknown_type", "photo": "photos/photo.jpg"}
        assert get_telegram_modality(msg) == "image"

    def test_unknown_media_type_with_file(self):
        """未知 media_type 但有 file → link_or_file"""
        msg = {"media_type": "unknown_type", "file": "files/doc.pdf"}
        assert get_telegram_modality(msg) == "link_or_file"

    def test_unknown_media_type_no_media(self):
        """未知 media_type 且无媒体 → text"""
        msg = {"media_type": "unknown_type"}
        assert get_telegram_modality(msg) == "text"

    def test_all_results_in_valid_modalities(self):
        """所有已知 media_type 映射结果都在 VALID_MODALITIES 中"""
        for media_type in TELEGRAM_MEDIA_TYPE_MAP:
            result = get_telegram_modality({"media_type": media_type})
            assert result in VALID_MODALITIES


# ── get_telegram_media_path 测试 ──────────────────────────────────────

class TestGetTelegramMediaPath:

    def test_photo_path(self):
        msg = {"photo": "photos/photo_1.jpg"}
        assert get_telegram_media_path(msg) == "photos/photo_1.jpg"

    def test_file_path(self):
        msg = {"file": "files/document.pdf"}
        assert get_telegram_media_path(msg) == "files/document.pdf"

    def test_photo_priority_over_file(self):
        """photo 优先于 file"""
        msg = {"photo": "photos/p.jpg", "file": "files/f.pdf"}
        assert get_telegram_media_path(msg) == "photos/p.jpg"

    def test_no_media(self):
        msg = {"text": "Hello"}
        assert get_telegram_media_path(msg) is None


# ── map_speaker 测试 ──────────────────────────────────────────────────

class TestMapSpeaker:

    def test_mapped_to_me(self):
        assert map_speaker("我", {"我": "ME"}) == "ME"

    def test_mapped_to_other(self):
        assert map_speaker("John", {"John": "OTHER"}) == "OTHER"

    def test_not_in_map(self):
        assert map_speaker("Unknown", {"John": "OTHER"}) == "OTHER:Unknown"

    def test_none_from(self):
        assert map_speaker(None, {"John": "OTHER"}) == "OTHER"

    def test_empty_from(self):
        assert map_speaker("", {"John": "OTHER"}) == "OTHER"

    def test_empty_map(self):
        assert map_speaker("John", {}) == "OTHER:John"


# ── validate_input 测试 ───────────────────────────────────────────────

class TestValidateInput:

    def test_nonexistent_path(self, adapter, tmp_path):
        errors = adapter.validate_input(tmp_path / "不存在")
        assert len(errors) == 1
        assert "输入路径不存在" in errors[0]

    def test_non_json_file(self, adapter, tmp_path):
        f = tmp_path / "data.txt"
        f.write_text("hello")
        errors = adapter.validate_input(f)
        assert len(errors) == 1
        assert "期望 JSON 文件" in errors[0]

    def test_json_file_valid(self, adapter, tmp_path):
        f = tmp_path / "result.json"
        f.write_text("{}")
        errors = adapter.validate_input(f)
        assert errors == []

    def test_directory_valid(self, adapter, tmp_path):
        """目录输入不检查后缀"""
        errors = adapter.validate_input(tmp_path)
        assert errors == []


# ── detect_media_files 测试 ───────────────────────────────────────────

class TestDetectMediaFiles:

    def test_empty_directory(self, adapter, tmp_path):
        f = tmp_path / "result.json"
        f.write_text("{}")
        result = adapter.detect_media_files(f)
        assert result == []

    def test_finds_media_in_subdirs(self, adapter, tmp_path):
        """检测 Telegram 导出的媒体子目录"""
        (tmp_path / "photos").mkdir()
        (tmp_path / "stickers").mkdir()
        (tmp_path / "voice_messages").mkdir()
        (tmp_path / "video_files").mkdir()
        (tmp_path / "files").mkdir()

        (tmp_path / "photos" / "photo_1.jpg").write_text("img")
        (tmp_path / "stickers" / "sticker.webp").write_text("stk")
        (tmp_path / "voice_messages" / "audio.ogg").write_text("voice")
        (tmp_path / "video_files" / "video.mp4").write_text("vid")
        (tmp_path / "files" / "doc.pdf").write_text("doc")

        f = tmp_path / "result.json"
        f.write_text("{}")
        result = adapter.detect_media_files(f)
        assert len(result) == 5
        names = {r.name for r in result}
        assert names == {"photo_1.jpg", "sticker.webp", "audio.ogg", "video.mp4", "doc.pdf"}


# ── parse() 测试 ─────────────────────────────────────────────────────

class TestParse:

    def test_parse_text_message(self, adapter, manifest, tmp_path):
        """解析纯文本消息"""
        messages = [
            {"id": 100, "type": "message", "date": "2025-01-15T10:30:00",
             "from": "我", "text": "你好世界"}
        ]
        f = tmp_path / "result.json"
        f.write_text(_make_telegram_json(messages))

        records = list(adapter.parse(f, manifest))
        assert len(records) == 1
        r = records[0]
        assert r["msg_uid"] == "TG:100"
        assert r["speaker"] == "ME"
        assert r["modality"] == "text"
        assert r["text_raw"] == "你好世界"
        assert r["media_path"] is None

    def test_parse_sticker_message(self, adapter, manifest, tmp_path):
        """解析贴纸消息"""
        messages = [
            {"id": 200, "type": "message", "date": "2025-01-15T11:00:00",
             "from": "John Doe", "text": "", "media_type": "sticker",
             "file": "stickers/sticker.webp"}
        ]
        f = tmp_path / "result.json"
        f.write_text(_make_telegram_json(messages))

        records = list(adapter.parse(f, manifest))
        r = records[0]
        assert r["msg_uid"] == "TG:200"
        assert r["speaker"] == "OTHER"
        assert r["modality"] == "sticker"
        assert r["media_path"] == "stickers/sticker.webp"

    def test_parse_photo_message(self, adapter, manifest, tmp_path):
        """解析图片消息（无 media_type，有 photo）"""
        messages = [
            {"id": 300, "type": "message", "date": "2025-01-15T12:00:00",
             "from": "我", "text": "", "photo": "photos/photo_1.jpg"}
        ]
        f = tmp_path / "result.json"
        f.write_text(_make_telegram_json(messages))

        records = list(adapter.parse(f, manifest))
        r = records[0]
        assert r["modality"] == "image"
        assert r["media_path"] == "photos/photo_1.jpg"

    def test_parse_voice_message(self, adapter, manifest, tmp_path):
        """解析语音消息"""
        messages = [
            {"id": 400, "type": "message", "date": "2025-01-15T13:00:00",
             "from": "John Doe", "text": "", "media_type": "voice_message",
             "file": "voice_messages/audio.ogg"}
        ]
        f = tmp_path / "result.json"
        f.write_text(_make_telegram_json(messages))

        records = list(adapter.parse(f, manifest))
        r = records[0]
        assert r["modality"] == "voice"
        assert r["media_path"] == "voice_messages/audio.ogg"

    def test_parse_video_message(self, adapter, manifest, tmp_path):
        """解析视频消息"""
        messages = [
            {"id": 500, "type": "message", "date": "2025-01-15T14:00:00",
             "from": "我", "text": "", "media_type": "video_message",
             "file": "round_video_messages/video.mp4"}
        ]
        f = tmp_path / "result.json"
        f.write_text(_make_telegram_json(messages))

        records = list(adapter.parse(f, manifest))
        r = records[0]
        assert r["modality"] == "video"

    def test_parse_animation_message(self, adapter, manifest, tmp_path):
        """解析 GIF 动图消息（animation → sticker）"""
        messages = [
            {"id": 600, "type": "message", "date": "2025-01-15T15:00:00",
             "from": "John Doe", "text": "", "media_type": "animation",
             "file": "animations/anim.mp4"}
        ]
        f = tmp_path / "result.json"
        f.write_text(_make_telegram_json(messages))

        records = list(adapter.parse(f, manifest))
        r = records[0]
        assert r["modality"] == "sticker"

    def test_parse_file_message(self, adapter, manifest, tmp_path):
        """解析文件消息（无 media_type，有 file）"""
        messages = [
            {"id": 700, "type": "message", "date": "2025-01-15T16:00:00",
             "from": "我", "text": "看看这个文件", "file": "files/doc.pdf"}
        ]
        f = tmp_path / "result.json"
        f.write_text(_make_telegram_json(messages))

        records = list(adapter.parse(f, manifest))
        r = records[0]
        assert r["modality"] == "link_or_file"
        assert r["media_path"] == "files/doc.pdf"
        assert r["text_raw"] == "看看这个文件"

    def test_parse_rich_text(self, adapter, manifest, tmp_path):
        """解析富文本数组"""
        messages = [
            {"id": 800, "type": "message", "date": "2025-01-15T17:00:00",
             "from": "我", "text": [
                 "普通文本",
                 {"type": "bold", "text": "粗体"},
                 " 后续文本",
             ]}
        ]
        f = tmp_path / "result.json"
        f.write_text(_make_telegram_json(messages))

        records = list(adapter.parse(f, manifest))
        r = records[0]
        assert r["text_raw"] == "普通文本粗体 后续文本"

    def test_parse_skips_non_message_types(self, adapter, manifest, tmp_path):
        """跳过 type != 'message' 的条目"""
        messages = [
            {"id": 900, "type": "service", "date": "2025-01-15T18:00:00",
             "from": "我", "text": "服务消息"},
            {"id": 901, "type": "message", "date": "2025-01-15T18:01:00",
             "from": "我", "text": "正常消息"},
        ]
        f = tmp_path / "result.json"
        f.write_text(_make_telegram_json(messages))

        records = list(adapter.parse(f, manifest))
        assert len(records) == 1
        assert records[0]["msg_uid"] == "TG:901"

    def test_parse_unmapped_speaker(self, adapter, manifest, tmp_path):
        """未在 participant_map 中的 from → OTHER:{name}"""
        messages = [
            {"id": 1000, "type": "message", "date": "2025-01-15T19:00:00",
             "from": "Unknown User", "text": "谁？"}
        ]
        f = tmp_path / "result.json"
        f.write_text(_make_telegram_json(messages))

        records = list(adapter.parse(f, manifest))
        assert records[0]["speaker"] == "OTHER:Unknown User"

    def test_parse_multiple_messages(self, adapter, manifest, tmp_path):
        """解析多条消息"""
        messages = [
            {"id": 1, "type": "message", "date": "2025-01-15T10:00:00",
             "from": "我", "text": "第一条"},
            {"id": 2, "type": "message", "date": "2025-01-15T10:01:00",
             "from": "John Doe", "text": "第二条"},
            {"id": 3, "type": "message", "date": "2025-01-15T10:02:00",
             "from": "我", "text": "第三条"},
        ]
        f = tmp_path / "result.json"
        f.write_text(_make_telegram_json(messages))

        records = list(adapter.parse(f, manifest))
        assert len(records) == 3
        assert records[0]["msg_uid"] == "TG:1"
        assert records[1]["msg_uid"] == "TG:2"
        assert records[2]["msg_uid"] == "TG:3"

    def test_parse_empty_messages(self, adapter, manifest, tmp_path):
        """空 messages 数组"""
        f = tmp_path / "result.json"
        f.write_text(_make_telegram_json([]))

        records = list(adapter.parse(f, manifest))
        assert records == []

    def test_parse_without_manifest(self, adapter, tmp_path):
        """manifest 为 None 时不崩溃"""
        messages = [
            {"id": 1100, "type": "message", "date": "2025-01-15T20:00:00",
             "from": "Someone", "text": "无 manifest"}
        ]
        f = tmp_path / "result.json"
        f.write_text(_make_telegram_json(messages))

        records = list(adapter.parse(f, None))
        assert len(records) == 1
        assert records[0]["speaker"] == "OTHER:Someone"

    def test_parse_without_participant_map(self, adapter, manifest_no_map, tmp_path):
        """没有 participant_map 时所有人都是 OTHER:{name}"""
        messages = [
            {"id": 1200, "type": "message", "date": "2025-01-15T21:00:00",
             "from": "Alice", "text": "无映射"}
        ]
        f = tmp_path / "result.json"
        f.write_text(_make_telegram_json(messages))

        records = list(adapter.parse(f, manifest_no_map))
        assert records[0]["speaker"] == "OTHER:Alice"

    def test_parse_timestamp(self, adapter, manifest, tmp_path):
        """时间戳正确解析"""
        messages = [
            {"id": 1300, "type": "message", "date": "2025-01-15T10:30:00",
             "from": "我", "text": "时间测试"}
        ]
        f = tmp_path / "result.json"
        f.write_text(_make_telegram_json(messages))

        records = list(adapter.parse(f, manifest))
        assert records[0]["ts"] > 0

    def test_parse_invalid_date(self, adapter, manifest, tmp_path):
        """无效日期 → ts=0"""
        messages = [
            {"id": 1400, "type": "message", "date": "invalid-date",
             "from": "我", "text": "坏日期"}
        ]
        f = tmp_path / "result.json"
        f.write_text(_make_telegram_json(messages))

        records = list(adapter.parse(f, manifest))
        assert records[0]["ts"] == 0

    def test_parse_missing_from(self, adapter, manifest, tmp_path):
        """缺少 from 字段 → speaker=OTHER"""
        messages = [
            {"id": 1500, "type": "message", "date": "2025-01-15T22:00:00",
             "text": "无发送者"}
        ]
        f = tmp_path / "result.json"
        f.write_text(_make_telegram_json(messages))

        records = list(adapter.parse(f, manifest))
        assert records[0]["speaker"] == "OTHER"

    def test_msg_uid_format(self, adapter, manifest, tmp_path):
        """msg_uid 格式为 TG:{id}"""
        messages = [
            {"id": 99999, "type": "message", "date": "2025-01-15T23:00:00",
             "from": "我", "text": "uid 测试"}
        ]
        f = tmp_path / "result.json"
        f.write_text(_make_telegram_json(messages))

        records = list(adapter.parse(f, manifest))
        assert records[0]["msg_uid"] == "TG:99999"
        assert records[0]["msg_uid"].startswith("TG:")


# ── Property-Based Tests (hypothesis) ────────────────────────────────

from hypothesis import given, settings, assume
from hypothesis import strategies as st


class TestProperty5TelegramModalityMapping:
    """
    Property 5: Telegram 消息类型到 modality 映射
    Feature: universal-ingestion, Property 5: Telegram 消息类型到 modality 映射

    **Validates: Requirements 5.2**
    """

    @given(
        media_type=st.sampled_from(list(TELEGRAM_MEDIA_TYPE_MAP.keys())),
        has_photo=st.booleans(),
        has_file=st.booleans(),
    )
    @settings(max_examples=200)
    def test_known_media_types_map_to_valid_modality(self, media_type, has_photo, has_file):
        """已知 media_type 映射到 VALID_MODALITIES 中的值"""
        msg = {"media_type": media_type}
        if has_photo:
            msg["photo"] = "photos/test.jpg"
        if has_file:
            msg["file"] = "files/test.pdf"
        result = get_telegram_modality(msg)
        assert result in VALID_MODALITIES
        assert result == TELEGRAM_MEDIA_TYPE_MAP[media_type]

    @given(
        has_photo=st.booleans(),
        has_file=st.booleans(),
    )
    @settings(max_examples=100)
    def test_no_media_type_maps_to_valid_modality(self, has_photo, has_file):
        """无 media_type 时根据 photo/file 字段映射"""
        msg = {}
        if has_photo:
            msg["photo"] = "photos/test.jpg"
        if has_file:
            msg["file"] = "files/test.pdf"
        result = get_telegram_modality(msg)
        assert result in VALID_MODALITIES
        if has_photo:
            assert result == "image"
        elif has_file:
            assert result == "link_or_file"
        else:
            assert result == "text"


class TestProperty18TelegramParticipantMap:
    """
    Property 18: Telegram participant_map 映射
    Feature: universal-ingestion, Property 18: Telegram participant_map 映射

    **Validates: Requirements 5.3**
    """

    @given(
        from_name=st.text(min_size=1, max_size=30),
        mapped_speaker=st.sampled_from(["ME", "OTHER", "OTHER:GroupMember"]),
    )
    @settings(max_examples=200)
    def test_mapped_name_returns_mapped_value(self, from_name, mapped_speaker):
        """participant_map 中有映射时返回映射值"""
        participant_map = {from_name: mapped_speaker}
        result = map_speaker(from_name, participant_map)
        assert result == mapped_speaker

    @given(
        from_name=st.text(min_size=1, max_size=30),
        other_names=st.lists(st.text(min_size=1, max_size=20), max_size=5),
    )
    @settings(max_examples=200)
    def test_unmapped_name_returns_other_prefix(self, from_name, other_names):
        """participant_map 中无映射时返回 OTHER:{from_name}"""
        participant_map = {n: "OTHER" for n in other_names}
        assume(from_name not in participant_map)
        result = map_speaker(from_name, participant_map)
        assert result == f"OTHER:{from_name}"

    @given(data=st.data())
    @settings(max_examples=100)
    def test_none_or_empty_from_returns_other(self, data):
        """from 为 None 或空字符串时返回 OTHER"""
        from_name = data.draw(st.sampled_from([None, ""]))
        result = map_speaker(from_name, {"someone": "ME"})
        assert result == "OTHER"
