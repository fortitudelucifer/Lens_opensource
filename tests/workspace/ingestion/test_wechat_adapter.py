"""
test_wechat_adapter.py
微信 HTML+CSV 导出适配器的单元测试

验证：
- WeChatAdapter 基本属性（source_type、describe）
- validate_input 校验逻辑
- detect_media_files 媒体文件检测
- parse() 解析 HTML+CSV 输出标准消息格式
- 消息类型映射正确性
- msg_uid 格式：P1:{MsgSvrID}
- 媒体路径标准化
- participant_map → me_names 映射

Requirements: 4.1, 4.2, 4.3, 4.4
"""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from scripts.workspace.ingestion.adapters.wechat_html import WeChatAdapter
from scripts.workspace.ingestion.manifest import SourceManifest
from scripts.workspace.ingestion.schema import VALID_MODALITIES


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def adapter():
    return WeChatAdapter()


@pytest.fixture
def manifest():
    """基础 manifest，包含 participant_map"""
    return SourceManifest(
        source_type="wechat_html",
        input_paths=["./export"],
        participant_map={"我的名字": "ME", "张三": "OTHER"},
    )


@pytest.fixture
def manifest_no_map():
    """不含 participant_map 的 manifest"""
    return SourceManifest(
        source_type="wechat_html",
        input_paths=["./export"],
    )


def _make_html_content(messages: list[dict]) -> str:
    """生成包含 chatMessages 数组的最小 HTML"""
    msgs_json = json.dumps(messages, ensure_ascii=False)
    return f"""<html><body><script>
var chatMessages = {msgs_json};
</script></body></html>"""


def _make_csv_content(rows: list[dict]) -> str:
    """生成 CSV 内容"""
    if not rows:
        return "localId,TalkerId,Type,SubType,IsSender,CreateTime,Status,StrContent,StrTime,Remark,NickName,Sender\n"
    headers = list(rows[0].keys())
    lines = [",".join(headers)]
    for row in rows:
        lines.append(",".join(str(row.get(h, "")) for h in headers))
    return "\n".join(lines)


# ── 基本属性测试 ──────────────────────────────────────────────────────

class TestWeChatAdapterBasic:

    def test_supported_source_type(self, adapter):
        assert adapter.supported_source_type() == "wechat_html"

    def test_describe_returns_correct_structure(self, adapter):
        info = adapter.describe()
        assert info["source_type"] == "wechat_html"
        assert "HTML" in info["description"] or "html" in info["description"].lower()
        assert len(info["expected_files"]) == 2
        assert isinstance(info["field_mapping_example"], dict)


# ── validate_input 测试 ───────────────────────────────────────────────

class TestValidateInput:

    def test_nonexistent_path(self, adapter, tmp_path):
        errors = adapter.validate_input(tmp_path / "不存在")
        assert len(errors) == 1
        assert "输入路径不存在" in errors[0]

    def test_directory_without_html(self, adapter, tmp_path):
        """目录中没有 HTML 文件"""
        (tmp_path / "data.csv").write_text("a,b,c")
        errors = adapter.validate_input(tmp_path)
        assert len(errors) == 1
        assert "未找到 HTML 文件" in errors[0]

    def test_directory_with_html(self, adapter, tmp_path):
        """目录中有 HTML 文件"""
        (tmp_path / "chat.html").write_text("<html></html>")
        errors = adapter.validate_input(tmp_path)
        assert errors == []

    def test_file_not_html(self, adapter, tmp_path):
        """文件不是 .html 后缀"""
        f = tmp_path / "data.json"
        f.write_text("{}")
        errors = adapter.validate_input(f)
        assert len(errors) == 1
        assert "期望 HTML 文件" in errors[0]

    def test_html_file_valid(self, adapter, tmp_path):
        """正常 HTML 文件"""
        f = tmp_path / "chat.html"
        f.write_text("<html></html>")
        errors = adapter.validate_input(f)
        assert errors == []

    def test_html_file_case_insensitive(self, adapter, tmp_path):
        """大写 .HTML 后缀也应通过"""
        f = tmp_path / "chat.HTML"
        f.write_text("<html></html>")
        errors = adapter.validate_input(f)
        assert errors == []


# ── detect_media_files 测试 ───────────────────────────────────────────

class TestDetectMediaFiles:

    def test_empty_directory(self, adapter, tmp_path):
        result = adapter.detect_media_files(tmp_path)
        assert result == []

    def test_finds_media_in_subdirs(self, adapter, tmp_path):
        """检测 image/voice/video/sticker/file 子目录中的文件"""
        (tmp_path / "image" / "2025-06").mkdir(parents=True)
        (tmp_path / "voice").mkdir()
        (tmp_path / "video" / "2025-06").mkdir(parents=True)
        (tmp_path / "sticker").mkdir()
        (tmp_path / "file").mkdir()

        (tmp_path / "image" / "2025-06" / "photo.jpg").write_text("img")
        (tmp_path / "voice" / "audio.mp3").write_text("audio")
        (tmp_path / "video" / "2025-06" / "clip.mp4").write_text("video")
        (tmp_path / "sticker" / "emoji.gif").write_text("sticker")
        (tmp_path / "file" / "doc.pdf").write_text("doc")

        result = adapter.detect_media_files(tmp_path)
        assert len(result) == 5
        names = {f.name for f in result}
        assert names == {"photo.jpg", "audio.mp3", "clip.mp4", "emoji.gif", "doc.pdf"}

    def test_html_file_input_uses_parent(self, adapter, tmp_path):
        """传入 HTML 文件时，从其父目录检测媒体"""
        (tmp_path / "image").mkdir()
        (tmp_path / "image" / "pic.png").write_text("img")
        html_file = tmp_path / "chat.html"
        html_file.write_text("<html></html>")

        result = adapter.detect_media_files(html_file)
        assert len(result) == 1
        assert result[0].name == "pic.png"

    def test_ignores_directories(self, adapter, tmp_path):
        """只返回文件，不返回目录"""
        (tmp_path / "image" / "subdir").mkdir(parents=True)
        result = adapter.detect_media_files(tmp_path)
        assert result == []


# ── parse() 测试 ─────────────────────────────────────────────────────

class TestParse:

    def test_parse_text_message(self, adapter, manifest, tmp_path):
        """解析文本消息"""
        messages = [
            {
                "MsgSvrID": "123456789",
                "type": 1,
                "sub_type": 0,
                "text": "你好世界",
                "is_send": 1,
                "timestamp": 1749279243,
                "token": "abc123",
            }
        ]
        html_file = tmp_path / "chat.html"
        html_file.write_text(_make_html_content(messages))

        records = list(adapter.parse(html_file, manifest))
        assert len(records) == 1

        r = records[0]
        assert r["msg_uid"] == "P1:123456789"
        assert r["ts"] == 1749279243
        assert r["speaker"] == "ME"
        assert r["type"] == 1
        assert r["modality"] == "text"
        assert r["text_raw"] == "你好世界"
        assert r["seq_in_html"] == 0

    def test_parse_image_message(self, adapter, manifest, tmp_path):
        """解析图片消息，media_path 标准化"""
        messages = [
            {
                "MsgSvrID": "987654321",
                "type": 3,
                "sub_type": 0,
                "text": "./image/2025-06/photo.jpg",
                "is_send": 0,
                "timestamp": 1749279300,
            }
        ]
        html_file = tmp_path / "chat.html"
        html_file.write_text(_make_html_content(messages))

        records = list(adapter.parse(html_file, manifest))
        assert len(records) == 1

        r = records[0]
        assert r["modality"] == "image"
        assert r["media_path"] == "raw/image/2025-06/photo.jpg"
        assert r["speaker"] == "OTHER"

    def test_parse_voice_message(self, adapter, manifest, tmp_path):
        """解析语音消息"""
        messages = [
            {
                "MsgSvrID": "111222333",
                "type": 34,
                "sub_type": 0,
                "text": "./voice/audio.mp3",
                "is_send": 1,
                "timestamp": 1749279400,
                "voice_length": 5000,
                "voice_to_text": "你好啊",
            }
        ]
        html_file = tmp_path / "chat.html"
        html_file.write_text(_make_html_content(messages))

        records = list(adapter.parse(html_file, manifest))
        r = records[0]
        assert r["modality"] == "voice"
        assert r["voice_length"] == 5000
        assert r["voice_to_text"] == "你好啊"
        assert r["media_path"] == "raw/voice/audio.mp3"

    def test_parse_video_message(self, adapter, manifest, tmp_path):
        """解析视频消息"""
        messages = [
            {
                "MsgSvrID": "444555666",
                "type": 43,
                "sub_type": 0,
                "text": "./video/2025-06/clip.mp4",
                "is_send": 0,
                "timestamp": 1749279500,
            }
        ]
        html_file = tmp_path / "chat.html"
        html_file.write_text(_make_html_content(messages))

        records = list(adapter.parse(html_file, manifest))
        r = records[0]
        assert r["modality"] == "video"
        assert r["media_path"] == "raw/video/2025-06/clip.mp4"

    def test_parse_sticker_message(self, adapter, manifest, tmp_path):
        """解析表情包消息"""
        messages = [
            {
                "MsgSvrID": "777888999",
                "type": 47,
                "sub_type": 0,
                "text": "./sticker/emoji.gif",
                "is_send": 1,
                "timestamp": 1749279600,
            }
        ]
        html_file = tmp_path / "chat.html"
        html_file.write_text(_make_html_content(messages))

        records = list(adapter.parse(html_file, manifest))
        r = records[0]
        assert r["modality"] == "sticker"

    def test_parse_system_message(self, adapter, manifest, tmp_path):
        """解析系统消息（type=10000）"""
        messages = [
            {
                "MsgSvrID": "000111222",
                "type": 10000,
                "sub_type": 0,
                "text": "你撤回了一条消息",
                "is_send": 0,
                "timestamp": 1749279700,
            }
        ]
        html_file = tmp_path / "chat.html"
        html_file.write_text(_make_html_content(messages))

        records = list(adapter.parse(html_file, manifest))
        r = records[0]
        assert r["modality"] == "system"
        # "你撤回" 触发 speaker=ME 逻辑
        assert r["speaker"] == "ME"

    def test_parse_link_message_with_quote(self, adapter, manifest, tmp_path):
        """解析引用/回复消息（type=49, sub_type=57）"""
        messages = [
            {
                "MsgSvrID": "333444555",
                "type": 49,
                "sub_type": 57,
                "text": "我的回复",
                "is_send": 1,
                "timestamp": 1749279800,
                "svrid": "P1:123",
                "refermsg_type": 1,
                "refer_text": "原始消息",
            }
        ]
        html_file = tmp_path / "chat.html"
        html_file.write_text(_make_html_content(messages))

        records = list(adapter.parse(html_file, manifest))
        r = records[0]
        assert r["modality"] == "link_or_file"
        assert r["quote_svrid"] == "P1:123"
        assert r["quote_text"] == "原始消息"
        assert r["text_raw"] == "我的回复"

    def test_parse_multiple_messages(self, adapter, manifest, tmp_path):
        """解析多条消息，seq_in_html 递增"""
        messages = [
            {"MsgSvrID": "aaa", "type": 1, "sub_type": 0, "text": "第一条",
             "is_send": 1, "timestamp": 1000},
            {"MsgSvrID": "bbb", "type": 1, "sub_type": 0, "text": "第二条",
             "is_send": 0, "timestamp": 2000},
            {"MsgSvrID": "ccc", "type": 3, "sub_type": 0, "text": "./image/pic.jpg",
             "is_send": 1, "timestamp": 3000},
        ]
        html_file = tmp_path / "chat.html"
        html_file.write_text(_make_html_content(messages))

        records = list(adapter.parse(html_file, manifest))
        assert len(records) == 3
        assert records[0]["seq_in_html"] == 0
        assert records[1]["seq_in_html"] == 1
        assert records[2]["seq_in_html"] == 2
        assert records[0]["msg_uid"] == "P1:aaa"
        assert records[1]["msg_uid"] == "P1:bbb"

    def test_parse_directory_input(self, adapter, manifest, tmp_path):
        """传入目录时自动查找 HTML+CSV"""
        messages = [
            {"MsgSvrID": "dir1", "type": 1, "sub_type": 0, "text": "目录测试",
             "is_send": 1, "timestamp": 5000}
        ]
        (tmp_path / "chat.html").write_text(_make_html_content(messages))
        (tmp_path / "chat.csv").write_text(
            _make_csv_content([
                {"localId": "1", "TalkerId": "1", "Type": "1", "SubType": "0",
                 "IsSender": "1", "CreateTime": "5000", "Status": "",
                 "StrContent": "", "StrTime": "", "Remark": "我的名字",
                 "NickName": "我的名字", "Sender": ""}
            ])
        )

        records = list(adapter.parse(tmp_path, manifest))
        assert len(records) == 1
        assert records[0]["msg_uid"] == "P1:dir1"

    def test_parse_with_csv_metadata(self, adapter, manifest, tmp_path):
        """CSV 元数据补充 speaker 判断"""
        messages = [
            {"MsgSvrID": "csv1", "type": 1, "sub_type": 0, "text": "带CSV",
             "is_send": 0, "timestamp": 6000}
        ]
        csv_rows = [
            {"localId": "1", "TalkerId": "2", "Type": "1", "SubType": "0",
             "IsSender": "0", "CreateTime": "6000", "Status": "",
             "StrContent": "", "StrTime": "", "Remark": "我的名字",
             "NickName": "我的名字", "Sender": ""}
        ]
        (tmp_path / "chat.html").write_text(_make_html_content(messages))
        (tmp_path / "chat.csv").write_text(_make_csv_content(csv_rows))

        records = list(adapter.parse(tmp_path, manifest))
        r = records[0]
        # CSV 中 Remark="我的名字" 在 me_names 中，所以 speaker 应为 ME
        assert r["speaker"] == "ME"

    def test_parse_without_participant_map(self, adapter, manifest_no_map, tmp_path):
        """没有 participant_map 时仍能正常解析"""
        messages = [
            {"MsgSvrID": "nomap1", "type": 1, "sub_type": 0, "text": "无映射",
             "is_send": 0, "timestamp": 7000}
        ]
        (tmp_path / "chat.html").write_text(_make_html_content(messages))

        records = list(adapter.parse(tmp_path / "chat.html", manifest_no_map))
        assert len(records) == 1
        assert records[0]["speaker"] == "OTHER"

    def test_parse_with_none_manifest(self, adapter, tmp_path):
        """manifest 为 None 时不崩溃"""
        messages = [
            {"MsgSvrID": "null1", "type": 1, "sub_type": 0, "text": "空manifest",
             "is_send": 1, "timestamp": 8000}
        ]
        (tmp_path / "chat.html").write_text(_make_html_content(messages))

        records = list(adapter.parse(tmp_path / "chat.html", None))
        assert len(records) == 1


# ── msg_uid 格式测试 ─────────────────────────────────────────────────

class TestMsgUid:

    def test_msg_uid_format(self, adapter, manifest, tmp_path):
        """msg_uid 格式为 P1:{MsgSvrID}"""
        messages = [
            {"MsgSvrID": "8911054651869296902", "type": 1, "sub_type": 0,
             "text": "test", "is_send": 1, "timestamp": 9000}
        ]
        (tmp_path / "chat.html").write_text(_make_html_content(messages))

        records = list(adapter.parse(tmp_path / "chat.html", manifest))
        assert records[0]["msg_uid"] == "P1:8911054651869296902"

    def test_msg_uid_empty_svrid(self, adapter, manifest, tmp_path):
        """MsgSvrID 为空时 msg_uid 为 None"""
        messages = [
            {"MsgSvrID": "", "type": 1, "sub_type": 0,
             "text": "no id", "is_send": 1, "timestamp": 9100}
        ]
        (tmp_path / "chat.html").write_text(_make_html_content(messages))

        records = list(adapter.parse(tmp_path / "chat.html", manifest))
        assert records[0]["msg_uid"] is None


# ── 所有 modality 映射测试 ───────────────────────────────────────────

class TestModalityMapping:
    """验证所有已知消息类型码到 modality 的映射"""

    @pytest.mark.parametrize("msg_type,expected_modality", [
        (1, "text"),
        (3, "image"),
        (34, "voice"),
        (43, "video"),
        (47, "sticker"),
        (48, "location"),
        (42, "contact"),
        (49, "link_or_file"),
        (0, "system"),
        (10000, "system"),
    ])
    def test_type_to_modality(self, adapter, manifest, tmp_path,
                               msg_type, expected_modality):
        """消息类型码正确映射到 modality"""
        messages = [
            {"MsgSvrID": f"mod_{msg_type}", "type": msg_type, "sub_type": 0,
             "text": "test", "is_send": 1, "timestamp": 10000 + msg_type}
        ]
        (tmp_path / "chat.html").write_text(_make_html_content(messages))

        records = list(adapter.parse(tmp_path / "chat.html", manifest))
        assert records[0]["modality"] == expected_modality

    def test_all_modalities_are_valid(self, adapter, manifest, tmp_path):
        """所有已知类型码映射的 modality 都在 VALID_MODALITIES 中"""
        known_types = [1, 3, 34, 43, 47, 48, 42, 49, 0, 10000]
        messages = [
            {"MsgSvrID": f"val_{t}", "type": t, "sub_type": 0,
             "text": "test", "is_send": 1, "timestamp": 20000 + t}
            for t in known_types
        ]
        (tmp_path / "chat.html").write_text(_make_html_content(messages))

        records = list(adapter.parse(tmp_path / "chat.html", manifest))
        for r in records:
            assert r["modality"] in VALID_MODALITIES, (
                f"type={r['type']} 映射到 modality='{r['modality']}' 不在 VALID_MODALITIES 中"
            )


# ── Property 4: 微信消息类型到 modality 映射（属性测试）──────────────

from hypothesis import given, settings
from hypothesis import strategies as st

# 已知 type → modality 映射
KNOWN_TYPE_MAPPING = {
    1: "text",
    3: "image",
    34: "voice",
    43: "video",
    47: "sticker",
    48: "location",
    42: "contact",
    49: "link_or_file",
    0: "system",
    10000: "system",
}


class TestProperty4WeChatModalityMapping:
    """
    Property 4: 微信消息类型到 modality 映射
    Feature: universal-ingestion, Property 4: 微信消息类型到 modality 映射

    **Validates: Requirements 4.2**
    """

    @given(
        msg_type=st.sampled_from(list(KNOWN_TYPE_MAPPING.keys())),
        sub_type=st.integers(min_value=0, max_value=100),
    )
    @settings(max_examples=200)
    def test_known_types_map_to_valid_modality(self, msg_type, sub_type):
        """已知消息类型码映射到 VALID_MODALITIES 中的正确值"""
        from scripts.extract.extract_html_to_jsonl import get_modality

        result = get_modality(msg_type, sub_type)
        assert result in VALID_MODALITIES, (
            f"type={msg_type} 映射到 '{result}' 不在 VALID_MODALITIES 中"
        )
        assert result == KNOWN_TYPE_MAPPING[msg_type], (
            f"type={msg_type} 应映射到 '{KNOWN_TYPE_MAPPING[msg_type]}'，实际为 '{result}'"
        )

    @given(
        msg_type=st.integers(min_value=0, max_value=100000),
        sub_type=st.integers(min_value=0, max_value=100),
    )
    @settings(max_examples=200)
    def test_mapping_is_deterministic(self, msg_type, sub_type):
        """相同输入始终产生相同输出"""
        from scripts.extract.extract_html_to_jsonl import get_modality

        result1 = get_modality(msg_type, sub_type)
        result2 = get_modality(msg_type, sub_type)
        assert result1 == result2
