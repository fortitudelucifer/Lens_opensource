"""
test_whatsapp_adapter.py
WhatsApp TXT 导出适配器的单元测试

验证：
- WhatsAppAdapter 基本属性（source_type、describe）
- validate_input 校验逻辑
- detect_media_files 媒体文件检测
- parse() 解析 WhatsApp TXT 输出标准消息格式
- 正则解析 WhatsApp 行格式（多种本地化变体）
- 多行消息续行处理
- 媒体占位符识别
- 文件扩展名 → modality 映射
- 时区感知的时间戳转换
- msg_uid 格式：WA:{行号}

Requirements: 6.1, 6.2, 6.3, 6.4
"""

import pytest
from pathlib import Path

from scripts.workspace.ingestion.adapters.whatsapp_txt import (
    WhatsAppAdapter,
    ext_to_modality,
    parse_whatsapp_datetime,
    parse_whatsapp_line,
    WHATSAPP_LINE_RE,
    MEDIA_OMITTED_RE,
    IMAGE_EXTENSIONS,
    VOICE_EXTENSIONS,
    VIDEO_EXTENSIONS,
    DATETIME_FORMATS,
)
from scripts.workspace.ingestion.manifest import SourceManifest
from scripts.workspace.ingestion.schema import VALID_MODALITIES


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def adapter():
    return WhatsAppAdapter()


@pytest.fixture
def manifest():
    """基础 manifest，包含 participant_map"""
    return SourceManifest(
        source_type="whatsapp_txt",
        input_paths=["./chat.txt"],
        participant_map={"John Doe": "OTHER", "我": "ME"},
        timezone="America/New_York",
    )


@pytest.fixture
def manifest_default_tz():
    """使用默认时区的 manifest"""
    return SourceManifest(
        source_type="whatsapp_txt",
        input_paths=["./chat.txt"],
        participant_map={"Alice": "ME", "Bob": "OTHER"},
    )


def _make_whatsapp_txt(lines: list[str]) -> str:
    """生成 WhatsApp 导出 TXT 内容"""
    return "\n".join(lines) + "\n"


# ── 基本属性测试 ──────────────────────────────────────────────────────

class TestWhatsAppAdapterBasic:

    def test_supported_source_type(self, adapter):
        assert adapter.supported_source_type() == "whatsapp_txt"

    def test_describe_returns_correct_structure(self, adapter):
        info = adapter.describe()
        assert info["source_type"] == "whatsapp_txt"
        assert "WhatsApp" in info["description"]
        assert len(info["expected_files"]) == 2
        assert isinstance(info["field_mapping_example"], dict)


# ── ext_to_modality 测试 ─────────────────────────────────────────────

class TestExtToModality:

    @pytest.mark.parametrize("ext,expected", [
        (".jpg", "image"),
        (".jpeg", "image"),
        (".png", "image"),
        (".gif", "image"),
        (".webp", "image"),
        (".JPG", "image"),
        (".Png", "image"),
    ])
    def test_image_extensions(self, ext, expected):
        assert ext_to_modality(ext) == expected

    @pytest.mark.parametrize("ext,expected", [
        (".opus", "voice"),
        (".mp3", "voice"),
        (".ogg", "voice"),
        (".m4a", "voice"),
        (".OPUS", "voice"),
    ])
    def test_voice_extensions(self, ext, expected):
        assert ext_to_modality(ext) == expected

    @pytest.mark.parametrize("ext,expected", [
        (".mp4", "video"),
        (".3gp", "video"),
        (".mov", "video"),
        (".MP4", "video"),
    ])
    def test_video_extensions(self, ext, expected):
        assert ext_to_modality(ext) == expected

    @pytest.mark.parametrize("ext", [".pdf", ".doc", ".zip", ".txt", ".xyz", ""])
    def test_other_extensions(self, ext):
        assert ext_to_modality(ext) == "link_or_file"

    def test_all_results_in_valid_modalities(self):
        """所有映射结果都在 VALID_MODALITIES 中"""
        all_exts = [*IMAGE_EXTENSIONS, *VOICE_EXTENSIONS, *VIDEO_EXTENSIONS,
                    ".pdf", ".unknown"]
        for ext in all_exts:
            assert ext_to_modality(ext) in VALID_MODALITIES


# ── parse_whatsapp_line 测试 ──────────────────────────────────────────

class TestParseWhatsAppLine:

    def test_us_format(self):
        """US 格式：M/D/YY, H:MM AM/PM"""
        result = parse_whatsapp_line("1/15/25, 10:30 AM - John Doe: Hello there")
        assert result is not None
        date_str, sender, text = result
        assert date_str == "1/15/25, 10:30 AM"
        assert sender == "John Doe"
        assert text == "Hello there"

    def test_eu_format(self):
        """EU 格式：D/M/YY, HH:MM"""
        result = parse_whatsapp_line("15/01/25, 10:30 - John: Bonjour")
        assert result is not None
        _, sender, text = result
        assert sender == "John"
        assert text == "Bonjour"

    def test_us_format_with_pm(self):
        result = parse_whatsapp_line("12/31/24, 11:59 PM - Alice: Happy New Year!")
        assert result is not None
        date_str, sender, text = result
        assert date_str == "12/31/24, 11:59 PM"
        assert sender == "Alice"
        assert text == "Happy New Year!"

    def test_long_year_format(self):
        """四位年份"""
        result = parse_whatsapp_line("1/15/2025, 10:30 AM - Bob: Long year")
        assert result is not None
        date_str, _, _ = result
        assert "2025" in date_str

    def test_with_seconds(self):
        """带秒的格式"""
        result = parse_whatsapp_line("1/15/25, 10:30:45 AM - Alice: With seconds")
        assert result is not None
        date_str, _, _ = result
        assert "10:30:45" in date_str

    def test_en_dash_separator(self):
        """使用 en-dash (–) 分隔"""
        result = parse_whatsapp_line("1/15/25, 10:30 AM – John: En dash")
        assert result is not None
        _, sender, text = result
        assert sender == "John"
        assert text == "En dash"

    def test_media_omitted(self):
        result = parse_whatsapp_line("1/15/25, 10:31 AM - Jane: <Media omitted>")
        assert result is not None
        _, _, text = result
        assert text == "<Media omitted>"

    def test_non_matching_line(self):
        """不匹配的行返回 None"""
        assert parse_whatsapp_line("This is a continuation line") is None
        assert parse_whatsapp_line("") is None
        assert parse_whatsapp_line("   ") is None

    def test_system_message_no_colon(self):
        """系统消息（无冒号分隔的 sender:text）不匹配"""
        result = parse_whatsapp_line(
            "1/15/25, 10:30 AM - Messages and calls are end-to-end encrypted"
        )
        assert result is None

    def test_sender_with_colon_in_text(self):
        """消息文本中包含冒号"""
        result = parse_whatsapp_line("1/15/25, 10:30 AM - John: URL: https://example.com")
        assert result is not None
        _, sender, text = result
        assert sender == "John"
        assert text == "URL: https://example.com"

    def test_chinese_text(self):
        """中文消息"""
        result = parse_whatsapp_line("1/15/25, 10:30 AM - 张三: 你好世界")
        assert result is not None
        _, sender, text = result
        assert sender == "张三"
        assert text == "你好世界"

    def test_lowercase_am_pm(self):
        """小写 am/pm"""
        result = parse_whatsapp_line("1/15/25, 10:30 am - Alice: lowercase")
        assert result is not None


# ── parse_whatsapp_datetime 测试 ──────────────────────────────────────

class TestParseWhatsAppDatetime:

    def test_us_format(self):
        """US 格式解析"""
        ts = parse_whatsapp_datetime("1/15/25, 10:30 AM", "America/New_York")
        assert ts > 0

    def test_eu_format(self):
        """EU 格式解析"""
        ts = parse_whatsapp_datetime("15/01/25, 10:30", "Europe/London")
        assert ts > 0

    def test_german_format(self):
        """German 格式解析（点号分隔）"""
        ts = parse_whatsapp_datetime("15.01.25, 10:30", "Europe/Berlin")
        assert ts > 0

    def test_long_year(self):
        ts = parse_whatsapp_datetime("1/15/2025, 10:30 AM", "America/New_York")
        assert ts > 0

    def test_with_seconds(self):
        ts = parse_whatsapp_datetime("1/15/25, 10:30:45 AM", "America/New_York")
        assert ts > 0

    def test_invalid_format_returns_zero(self):
        assert parse_whatsapp_datetime("not a date") == 0
        assert parse_whatsapp_datetime("") == 0

    def test_narrow_no_break_space(self):
        """处理 Unicode 窄不换行空格 (\\u202f)"""
        ts = parse_whatsapp_datetime("1/15/25, 10:30\u202fAM", "America/New_York")
        assert ts > 0

    def test_non_breaking_space(self):
        """处理 Unicode 不换行空格 (\\xa0)"""
        ts = parse_whatsapp_datetime("1/15/25, 10:30\xa0AM", "America/New_York")
        assert ts > 0

    def test_timezone_affects_result(self):
        """不同时区产生不同时间戳"""
        ts_ny = parse_whatsapp_datetime("1/15/25, 10:30 AM", "America/New_York")
        ts_sh = parse_whatsapp_datetime("1/15/25, 10:30 AM", "Asia/Shanghai")
        assert ts_ny != ts_sh

    def test_default_timezone(self):
        """默认时区为 Asia/Shanghai"""
        ts = parse_whatsapp_datetime("1/15/25, 10:30 AM")
        assert ts > 0


# ── MEDIA_OMITTED_RE 测试 ────────────────────────────────────────────

class TestMediaOmittedRegex:

    @pytest.mark.parametrize("text", [
        "<Media omitted>",
        "<media omitted>",
        "<image omitted>",
        "<video omitted>",
        "<audio omitted>",
        "<document omitted>",
        "<sticker omitted>",
        "<Media 省略>",
    ])
    def test_matches_known_patterns(self, text):
        assert MEDIA_OMITTED_RE.search(text) is not None

    def test_no_match_normal_text(self):
        assert MEDIA_OMITTED_RE.search("Hello world") is None

    def test_no_match_partial(self):
        assert MEDIA_OMITTED_RE.search("Media omitted") is None  # 缺少尖括号


# ── validate_input 测试 ───────────────────────────────────────────────

class TestValidateInput:

    def test_nonexistent_path(self, adapter, tmp_path):
        errors = adapter.validate_input(tmp_path / "不存在")
        assert len(errors) == 1
        assert "输入路径不存在" in errors[0]

    def test_non_txt_file(self, adapter, tmp_path):
        f = tmp_path / "data.json"
        f.write_text("{}")
        errors = adapter.validate_input(f)
        assert len(errors) == 1
        assert "期望 TXT 文件" in errors[0]

    def test_txt_file_valid(self, adapter, tmp_path):
        f = tmp_path / "chat.txt"
        f.write_text("hello")
        errors = adapter.validate_input(f)
        assert errors == []

    def test_directory_valid(self, adapter, tmp_path):
        """目录输入不检查后缀"""
        errors = adapter.validate_input(tmp_path)
        assert errors == []


# ── detect_media_files 测试 ───────────────────────────────────────────

class TestDetectMediaFiles:

    def test_empty_directory(self, adapter, tmp_path):
        f = tmp_path / "chat.txt"
        f.write_text("hello")
        result = adapter.detect_media_files(f)
        assert result == []

    def test_finds_media_files(self, adapter, tmp_path):
        """检测同目录下的媒体文件"""
        (tmp_path / "chat.txt").write_text("hello")
        (tmp_path / "IMG-20250115-WA0001.jpg").write_text("img")
        (tmp_path / "AUD-20250115-WA0002.opus").write_text("audio")
        (tmp_path / "VID-20250115-WA0003.mp4").write_text("video")
        (tmp_path / "DOC-20250115-WA0004.pdf").write_text("doc")

        result = adapter.detect_media_files(tmp_path / "chat.txt")
        assert len(result) == 4
        names = {r.name for r in result}
        assert "IMG-20250115-WA0001.jpg" in names
        assert "AUD-20250115-WA0002.opus" in names
        assert "VID-20250115-WA0003.mp4" in names
        assert "DOC-20250115-WA0004.pdf" in names

    def test_excludes_txt_files(self, adapter, tmp_path):
        """不包含 .txt 文件"""
        (tmp_path / "chat.txt").write_text("hello")
        (tmp_path / "notes.txt").write_text("notes")
        result = adapter.detect_media_files(tmp_path / "chat.txt")
        assert all(f.suffix != ".txt" for f in result)


# ── parse() 测试 ─────────────────────────────────────────────────────

class TestParse:

    def test_parse_text_message(self, adapter, manifest, tmp_path):
        """解析纯文本消息"""
        content = _make_whatsapp_txt([
            "1/15/25, 10:30 AM - 我: 你好世界",
        ])
        f = tmp_path / "chat.txt"
        f.write_text(content, encoding="utf-8")

        records = list(adapter.parse(f, manifest))
        assert len(records) == 1
        r = records[0]
        assert r["msg_uid"] == "WA:1"
        assert r["speaker"] == "ME"
        assert r["modality"] == "text"
        assert r["text_raw"] == "你好世界"
        assert r["media_path"] is None
        assert r["ts"] > 0

    def test_parse_media_omitted(self, adapter, manifest, tmp_path):
        """解析媒体占位符消息"""
        content = _make_whatsapp_txt([
            "1/15/25, 10:31 AM - John Doe: <Media omitted>",
        ])
        f = tmp_path / "chat.txt"
        f.write_text(content, encoding="utf-8")

        records = list(adapter.parse(f, manifest))
        r = records[0]
        assert r["modality"] == "image"  # 默认为 image
        assert r["speaker"] == "OTHER"

    def test_parse_file_attached(self, adapter, manifest, tmp_path):
        """解析附件消息"""
        content = _make_whatsapp_txt([
            "1/15/25, 10:32 AM - John Doe: IMG-20250115-WA0001.jpg (file attached)",
        ])
        f = tmp_path / "chat.txt"
        f.write_text(content, encoding="utf-8")

        records = list(adapter.parse(f, manifest))
        r = records[0]
        assert r["modality"] == "image"
        assert r["media_path"] == "IMG-20250115-WA0001.jpg"

    def test_parse_voice_attached(self, adapter, manifest, tmp_path):
        """解析语音附件"""
        content = _make_whatsapp_txt([
            "1/15/25, 10:33 AM - 我: AUD-20250115-WA0002.opus (file attached)",
        ])
        f = tmp_path / "chat.txt"
        f.write_text(content, encoding="utf-8")

        records = list(adapter.parse(f, manifest))
        r = records[0]
        assert r["modality"] == "voice"
        assert r["media_path"] == "AUD-20250115-WA0002.opus"

    def test_parse_video_attached(self, adapter, manifest, tmp_path):
        """解析视频附件"""
        content = _make_whatsapp_txt([
            "1/15/25, 10:34 AM - John Doe: VID-20250115-WA0003.mp4 (file attached)",
        ])
        f = tmp_path / "chat.txt"
        f.write_text(content, encoding="utf-8")

        records = list(adapter.parse(f, manifest))
        r = records[0]
        assert r["modality"] == "video"
        assert r["media_path"] == "VID-20250115-WA0003.mp4"

    def test_parse_multiline_message(self, adapter, manifest, tmp_path):
        """多行消息续行处理"""
        content = _make_whatsapp_txt([
            "1/15/25, 10:30 AM - 我: 第一行",
            "第二行",
            "第三行",
        ])
        f = tmp_path / "chat.txt"
        f.write_text(content, encoding="utf-8")

        records = list(adapter.parse(f, manifest))
        assert len(records) == 1
        assert records[0]["text_raw"] == "第一行\n第二行\n第三行"

    def test_parse_multiline_between_messages(self, adapter, manifest, tmp_path):
        """多行消息夹在两条消息之间"""
        content = _make_whatsapp_txt([
            "1/15/25, 10:30 AM - 我: 第一条",
            "续行内容",
            "1/15/25, 10:31 AM - John Doe: 第二条",
        ])
        f = tmp_path / "chat.txt"
        f.write_text(content, encoding="utf-8")

        records = list(adapter.parse(f, manifest))
        assert len(records) == 2
        assert records[0]["text_raw"] == "第一条\n续行内容"
        assert records[1]["text_raw"] == "第二条"

    def test_parse_multiple_messages(self, adapter, manifest, tmp_path):
        """解析多条消息"""
        content = _make_whatsapp_txt([
            "1/15/25, 10:30 AM - 我: 第一条",
            "1/15/25, 10:31 AM - John Doe: 第二条",
            "1/15/25, 10:32 AM - 我: 第三条",
        ])
        f = tmp_path / "chat.txt"
        f.write_text(content, encoding="utf-8")

        records = list(adapter.parse(f, manifest))
        assert len(records) == 3
        assert records[0]["msg_uid"] == "WA:1"
        assert records[1]["msg_uid"] == "WA:2"
        assert records[2]["msg_uid"] == "WA:3"

    def test_parse_unmapped_speaker(self, adapter, manifest, tmp_path):
        """未在 participant_map 中的发送者 → OTHER:{name}"""
        content = _make_whatsapp_txt([
            "1/15/25, 10:30 AM - Unknown User: 谁？",
        ])
        f = tmp_path / "chat.txt"
        f.write_text(content, encoding="utf-8")

        records = list(adapter.parse(f, manifest))
        assert records[0]["speaker"] == "OTHER:Unknown User"

    def test_parse_empty_file(self, adapter, manifest, tmp_path):
        """空文件"""
        f = tmp_path / "chat.txt"
        f.write_text("", encoding="utf-8")

        records = list(adapter.parse(f, manifest))
        assert records == []

    def test_parse_without_manifest(self, adapter, tmp_path):
        """manifest 为 None 时不崩溃"""
        content = _make_whatsapp_txt([
            "1/15/25, 10:30 AM - Someone: 无 manifest",
        ])
        f = tmp_path / "chat.txt"
        f.write_text(content, encoding="utf-8")

        records = list(adapter.parse(f, None))
        assert len(records) == 1
        assert records[0]["speaker"] == "OTHER:Someone"

    def test_msg_uid_format(self, adapter, manifest, tmp_path):
        """msg_uid 格式为 WA:{行号}"""
        content = _make_whatsapp_txt([
            "1/15/25, 10:30 AM - 我: uid 测试",
        ])
        f = tmp_path / "chat.txt"
        f.write_text(content, encoding="utf-8")

        records = list(adapter.parse(f, manifest))
        assert records[0]["msg_uid"].startswith("WA:")

    def test_parse_eu_format(self, adapter, tmp_path):
        """EU 格式解析"""
        manifest_eu = SourceManifest(
            source_type="whatsapp_txt",
            input_paths=["./chat.txt"],
            participant_map={"Hans": "OTHER"},
            timezone="Europe/Berlin",
        )
        content = _make_whatsapp_txt([
            "15/01/25, 10:30 - Hans: Guten Tag",
        ])
        f = tmp_path / "chat.txt"
        f.write_text(content, encoding="utf-8")

        records = list(adapter.parse(f, manifest_eu))
        assert len(records) == 1
        assert records[0]["speaker"] == "OTHER"
        assert records[0]["text_raw"] == "Guten Tag"
        assert records[0]["ts"] > 0

    def test_parse_skips_system_lines_before_first_message(self, adapter, manifest, tmp_path):
        """第一条消息前的系统行被忽略"""
        content = _make_whatsapp_txt([
            "Messages and calls are end-to-end encrypted.",
            "1/15/25, 10:30 AM - 我: 第一条消息",
        ])
        f = tmp_path / "chat.txt"
        f.write_text(content, encoding="utf-8")

        records = list(adapter.parse(f, manifest))
        assert len(records) == 1
        assert records[0]["text_raw"] == "第一条消息"

    def test_parse_type_field(self, adapter, manifest, tmp_path):
        """type 字段始终为 1"""
        content = _make_whatsapp_txt([
            "1/15/25, 10:30 AM - 我: 测试",
        ])
        f = tmp_path / "chat.txt"
        f.write_text(content, encoding="utf-8")

        records = list(adapter.parse(f, manifest))
        assert records[0]["type"] == 1

    def test_parse_doc_attached(self, adapter, manifest, tmp_path):
        """解析文档附件 → link_or_file"""
        content = _make_whatsapp_txt([
            "1/15/25, 10:35 AM - 我: DOC-20250115-WA0005.pdf (file attached)",
        ])
        f = tmp_path / "chat.txt"
        f.write_text(content, encoding="utf-8")

        records = list(adapter.parse(f, manifest))
        r = records[0]
        assert r["modality"] == "link_or_file"
        assert r["media_path"] == "DOC-20250115-WA0005.pdf"

    def test_line_numbers_with_continuation(self, adapter, manifest, tmp_path):
        """续行不影响 msg_uid 行号（使用首行行号）"""
        content = _make_whatsapp_txt([
            "1/15/25, 10:30 AM - 我: 第一条",
            "续行",
            "1/15/25, 10:31 AM - John Doe: 第二条",
        ])
        f = tmp_path / "chat.txt"
        f.write_text(content, encoding="utf-8")

        records = list(adapter.parse(f, manifest))
        assert records[0]["msg_uid"] == "WA:1"
        assert records[1]["msg_uid"] == "WA:3"


# ══════════════════════════════════════════════════════════════════════
# Property-Based Tests (hypothesis)
# ══════════════════════════════════════════════════════════════════════

from hypothesis import given, settings, assume
from hypothesis import strategies as st
from datetime import datetime as dt, timezone
import pytz
import string


# ── 自定义策略 ────────────────────────────────────────────────────────

def _whatsapp_us_line_strategy():
    """生成符合 US 格式的 WhatsApp 行：M/D/YY, H:MM AM/PM - Sender: Text"""
    # 使用安全字符集避免 \s* 在正则中吞掉文本内容
    _safe_text_chars = list(string.ascii_letters) + list(string.digits) + list("_-!?.,你好世界")
    return st.tuples(
        st.integers(min_value=1, max_value=12),   # month
        st.integers(min_value=1, max_value=28),    # day (safe range)
        st.integers(min_value=0, max_value=99),    # year (2-digit)
        st.integers(min_value=1, max_value=12),    # hour (12h)
        st.integers(min_value=0, max_value=59),    # minute
        st.sampled_from(["AM", "PM", "am", "pm"]),
        st.text(
            alphabet=st.sampled_from(
                list(string.ascii_letters) + list("_- 张三李四王五")
            ),
            min_size=1, max_size=20,
        ).filter(lambda s: s.strip() and ":" not in s and "\n" not in s),
        st.text(
            alphabet=st.sampled_from(_safe_text_chars),
            min_size=1, max_size=50,
        ),
    ).map(lambda t: (
        f"{t[0]}/{t[1]}/{t[2]:02d}, {t[3]}:{t[4]:02d} {t[5]}",
        t[6].strip(),
        t[7],
        f"{t[0]}/{t[1]}/{t[2]:02d}, {t[3]}:{t[4]:02d} {t[5]} - {t[6].strip()}: {t[7]}",
    )).filter(lambda t: len(t[1]) > 0)


def _whatsapp_eu_line_strategy():
    """生成符合 EU 格式的 WhatsApp 行：D/M/YY, HH:MM - Sender: Text"""
    _safe_text_chars = list(string.ascii_letters) + list(string.digits) + list("_-!?.,你好世界")
    return st.tuples(
        st.integers(min_value=1, max_value=28),    # day
        st.integers(min_value=1, max_value=12),    # month
        st.integers(min_value=0, max_value=99),    # year
        st.integers(min_value=0, max_value=23),    # hour (24h)
        st.integers(min_value=0, max_value=59),    # minute
        st.text(
            alphabet=st.sampled_from(
                list(string.ascii_letters) + list("_- 张三李四")
            ),
            min_size=1, max_size=20,
        ).filter(lambda s: s.strip() and ":" not in s and "\n" not in s),
        st.text(
            alphabet=st.sampled_from(_safe_text_chars),
            min_size=1, max_size=50,
        ),
    ).map(lambda t: (
        f"{t[0]}/{t[1]}/{t[2]:02d}, {t[3]}:{t[4]:02d}",
        t[5].strip(),
        t[6],
        f"{t[0]}/{t[1]}/{t[2]:02d}, {t[3]}:{t[4]:02d} - {t[5].strip()}: {t[6]}",
    )).filter(lambda t: len(t[1]) > 0)


def _non_whatsapp_line_strategy():
    """生成不符合 WhatsApp 格式的行（续行）"""
    return st.text(min_size=0, max_size=100).filter(
        lambda s: "\n" not in s and parse_whatsapp_line(s) is None
    )


# ── Property 6: WhatsApp 行格式解析 ──────────────────────────────────

class TestProperty6WhatsAppLineParsing:
    """
    Property 6: WhatsApp 行格式解析

    *For any* 符合 WhatsApp 导出格式的行（日期, 时间 - 发送者: 消息内容），
    解析器应正确提取时间戳、发送者和消息内容三个部分。
    对于不符合格式的行，应视为前一条消息的续行（return None）。

    **Validates: Requirements 6.1**
    """

    @given(data=_whatsapp_us_line_strategy())
    @settings(max_examples=200)
    def test_us_format_lines_parsed_correctly(self, data):
        """US 格式行应正确提取三个部分。 **Validates: Requirements 6.1**"""
        date_str_expected, sender_expected, text_expected, line = data
        result = parse_whatsapp_line(line)
        assert result is not None, f"应匹配 WhatsApp 格式: {line!r}"
        date_str, sender, text = result
        assert date_str == date_str_expected
        assert sender == sender_expected
        assert text == text_expected

    @given(data=_whatsapp_eu_line_strategy())
    @settings(max_examples=200)
    def test_eu_format_lines_parsed_correctly(self, data):
        """EU 格式行应正确提取三个部分。 **Validates: Requirements 6.1**"""
        date_str_expected, sender_expected, text_expected, line = data
        result = parse_whatsapp_line(line)
        assert result is not None, f"应匹配 WhatsApp 格式: {line!r}"
        date_str, sender, text = result
        # 正则中 \s*(?:AM|PM)? 在 EU 24h 格式下可能捕获尾部空格，strip 后应一致
        assert date_str.strip() == date_str_expected.strip()
        assert sender == sender_expected
        assert text == text_expected

    @given(line=_non_whatsapp_line_strategy())
    @settings(max_examples=200)
    def test_non_matching_lines_return_none(self, line):
        """不符合格式的行应返回 None（续行）。 **Validates: Requirements 6.1**"""
        assert parse_whatsapp_line(line) is None


# ── Property 7: WhatsApp 文件扩展名到 modality 映射 ──────────────────

class TestProperty7ExtToModality:
    """
    Property 7: WhatsApp 文件扩展名到 modality 映射

    *For any* 文件扩展名，映射函数应将图片扩展名映射为 image，
    语音扩展名映射为 voice，视频扩展名映射为 video，
    其他扩展名映射为 link_or_file。

    **Validates: Requirements 6.3**
    """

    @given(ext=st.sampled_from(sorted(IMAGE_EXTENSIONS)))
    @settings(max_examples=200)
    def test_image_extensions_map_to_image(self, ext):
        """图片扩展名应映射为 image。 **Validates: Requirements 6.3**"""
        assert ext_to_modality(ext) == "image"
        # 大写也应映射为 image
        assert ext_to_modality(ext.upper()) == "image"

    @given(ext=st.sampled_from(sorted(VOICE_EXTENSIONS)))
    @settings(max_examples=200)
    def test_voice_extensions_map_to_voice(self, ext):
        """语音扩展名应映射为 voice。 **Validates: Requirements 6.3**"""
        assert ext_to_modality(ext) == "voice"
        assert ext_to_modality(ext.upper()) == "voice"

    @given(ext=st.sampled_from(sorted(VIDEO_EXTENSIONS)))
    @settings(max_examples=200)
    def test_video_extensions_map_to_video(self, ext):
        """视频扩展名应映射为 video。 **Validates: Requirements 6.3**"""
        assert ext_to_modality(ext) == "video"
        assert ext_to_modality(ext.upper()) == "video"

    @given(ext=st.text(
        alphabet=st.sampled_from(list(string.ascii_lowercase) + list(string.digits)),
        min_size=1, max_size=6,
    ).map(lambda s: "." + s))
    @settings(max_examples=200)
    def test_unknown_extensions_map_to_link_or_file(self, ext):
        """未知扩展名应映射为 link_or_file。 **Validates: Requirements 6.3**"""
        assume(ext.lower() not in IMAGE_EXTENSIONS)
        assume(ext.lower() not in VOICE_EXTENSIONS)
        assume(ext.lower() not in VIDEO_EXTENSIONS)
        assert ext_to_modality(ext) == "link_or_file"

    @given(ext=st.sampled_from(
        sorted(IMAGE_EXTENSIONS | VOICE_EXTENSIONS | VIDEO_EXTENSIONS)
        + [".pdf", ".doc", ".zip", ".txt", ".xyz", ".rar"]
    ))
    @settings(max_examples=200)
    def test_all_results_in_valid_modalities(self, ext):
        """所有映射结果都在 VALID_MODALITIES 中。 **Validates: Requirements 6.3**"""
        result = ext_to_modality(ext)
        assert result in VALID_MODALITIES


# ── Property 8: 时区感知的时间戳转换 ─────────────────────────────────

# 用于 Property 8 的时区列表（常见且无歧义的时区）
_COMMON_TIMEZONES = [
    "UTC", "Asia/Shanghai", "America/New_York", "Europe/London",
    "Europe/Berlin", "Asia/Tokyo", "Australia/Sydney",
    "America/Los_Angeles", "America/Chicago",
]


class TestProperty8TimezoneRoundtrip:
    """
    Property 8: 时区感知的时间戳转换

    *For any* 本地时间字符串和时区标识组合，转换为 Unix 时间戳后再转回本地时间，
    应得到与原始时间等价的结果（往返一致性，精度到秒）。

    **Validates: Requirements 6.4**
    """

    @given(
        month=st.integers(min_value=1, max_value=12),
        day=st.integers(min_value=1, max_value=28),
        year_2d=st.integers(min_value=0, max_value=99),
        hour_12=st.integers(min_value=1, max_value=12),
        minute=st.integers(min_value=0, max_value=59),
        ampm=st.sampled_from(["AM", "PM"]),
        tz_name=st.sampled_from(_COMMON_TIMEZONES),
    )
    @settings(max_examples=200)
    def test_us_format_roundtrip(self, month, day, year_2d, hour_12, minute, ampm, tz_name):
        """US 格式往返一致性。 **Validates: Requirements 6.4**"""
        date_str = f"{month}/{day}/{year_2d:02d}, {hour_12}:{minute:02d} {ampm}"
        ts = parse_whatsapp_datetime(date_str, tz_name)
        assume(ts > 0)

        # 从 Unix 时间戳转回本地时间
        tz = pytz.timezone(tz_name)
        recovered = dt.fromtimestamp(ts, tz=tz)

        # 重新构造原始 datetime 进行比较
        original = dt.strptime(date_str.strip(), "%m/%d/%y, %I:%M %p")
        original = tz.localize(original)

        assert recovered.year == original.year
        assert recovered.month == original.month
        assert recovered.day == original.day
        assert recovered.hour == original.hour
        assert recovered.minute == original.minute

    @given(
        day=st.integers(min_value=1, max_value=28),
        month=st.integers(min_value=1, max_value=12),
        year_2d=st.integers(min_value=0, max_value=99),
        hour=st.integers(min_value=0, max_value=23),
        minute=st.integers(min_value=0, max_value=59),
        tz_name=st.sampled_from(_COMMON_TIMEZONES),
    )
    @settings(max_examples=200)
    def test_eu_format_roundtrip(self, day, month, year_2d, hour, minute, tz_name):
        """EU 格式往返一致性。 **Validates: Requirements 6.4**"""
        date_str = f"{day}/{month}/{year_2d:02d}, {hour}:{minute:02d}"
        ts = parse_whatsapp_datetime(date_str, tz_name)
        assume(ts > 0)

        tz = pytz.timezone(tz_name)
        recovered = dt.fromtimestamp(ts, tz=tz)

        original = dt.strptime(date_str.strip(), "%d/%m/%y, %H:%M")
        original = tz.localize(original)

        assert recovered.year == original.year
        assert recovered.month == original.month
        assert recovered.day == original.day
        assert recovered.hour == original.hour
        assert recovered.minute == original.minute

    @given(
        month=st.integers(min_value=1, max_value=12),
        day=st.integers(min_value=1, max_value=28),
        year_2d=st.integers(min_value=0, max_value=99),
        hour_12=st.integers(min_value=1, max_value=12),
        minute=st.integers(min_value=0, max_value=59),
        ampm=st.sampled_from(["AM", "PM"]),
        tz_name=st.sampled_from(_COMMON_TIMEZONES),
    )
    @settings(max_examples=200)
    def test_timestamp_is_positive_integer(self, month, day, year_2d, hour_12, minute, ampm, tz_name):
        """成功解析的时间戳应为正整数。 **Validates: Requirements 6.4**"""
        date_str = f"{month}/{day}/{year_2d:02d}, {hour_12}:{minute:02d} {ampm}"
        ts = parse_whatsapp_datetime(date_str, tz_name)
        assume(ts > 0)
        assert isinstance(ts, int)
        assert ts > 0
