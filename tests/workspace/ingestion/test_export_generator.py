"""
test_export_generator.py
ExportGenerator 单元测试

覆盖：
- generate_csv(): CSV 格式、字段映射
- generate_markdown(): 按日期分组、格式
- generate_html(): chatMessages 数组、可被 extract_chatmessages_array 解析
"""

import csv
import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

# 确保项目根目录在 sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(PROJECT_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from scripts.workspace.ingestion.export_generator import ExportGenerator
from scripts.extract.extract_html_to_jsonl import extract_chatmessages_array


# ── Fixtures ──────────────────────────────────────────────────────────

def _make_record(
    msg_uid: str = "P1:100",
    ts: int = 1749279243,
    speaker: str = "ME",
    type_: int = 1,
    modality: str = "text",
    text_raw: str = "你好",
    **kwargs,
) -> dict:
    rec = {
        "msg_uid": msg_uid,
        "ts": ts,
        "speaker": speaker,
        "type": type_,
        "modality": modality,
        "text_raw": text_raw,
        "seq_in_html": kwargs.pop("seq_in_html", -1),
        "MsgSvrID": kwargs.pop("MsgSvrID", ""),
        "token": kwargs.pop("token", ""),
        "time_local": kwargs.pop("time_local", ""),
        "sub_type": kwargs.pop("sub_type", 0),
    }
    rec.update(kwargs)
    return rec


SAMPLE_RECORDS = [
    _make_record(
        msg_uid="P1:100", ts=1749279243, speaker="ME",
        type_=1, modality="text", text_raw="你好",
        seq_in_html=0, MsgSvrID="100",
        time_local="2025-06-07 14:54:03",
    ),
    _make_record(
        msg_uid="P1:101", ts=1749279300, speaker="OTHER:张三",
        type_=1, modality="text", text_raw="你好啊",
        seq_in_html=1, MsgSvrID="101",
        time_local="2025-06-07 14:55:00",
    ),
    _make_record(
        msg_uid="P1:102", ts=1749365643, speaker="ME",
        type_=3, modality="image", text_raw="raw/image/2025-06/photo.jpg",
        seq_in_html=2, MsgSvrID="102",
        time_local="2025-06-08 14:54:03",
    ),
]


# ── CSV Tests ─────────────────────────────────────────────────────────

class TestGenerateCSV:

    def test_csv_has_correct_columns(self, tmp_path: Path):
        gen = ExportGenerator()
        out = tmp_path / "export" / "test.csv"
        gen.generate_csv(SAMPLE_RECORDS, out)

        with open(out, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            assert reader.fieldnames == ExportGenerator.CSV_COLUMNS

    def test_csv_row_count(self, tmp_path: Path):
        gen = ExportGenerator()
        out = tmp_path / "export" / "test.csv"
        gen.generate_csv(SAMPLE_RECORDS, out)

        with open(out, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == len(SAMPLE_RECORDS)

    def test_csv_me_speaker_mapping(self, tmp_path: Path):
        gen = ExportGenerator()
        out = tmp_path / "test.csv"
        gen.generate_csv(SAMPLE_RECORDS[:1], out)

        with open(out, encoding="utf-8") as f:
            row = list(csv.DictReader(f))[0]

        assert row["TalkerId"] == "1"
        assert row["IsSender"] == "1"
        assert row["Sender"] == "ME"

    def test_csv_other_speaker_mapping(self, tmp_path: Path):
        gen = ExportGenerator()
        out = tmp_path / "test.csv"
        gen.generate_csv(SAMPLE_RECORDS[1:2], out)

        with open(out, encoding="utf-8") as f:
            row = list(csv.DictReader(f))[0]

        assert row["TalkerId"] == "2"
        assert row["IsSender"] == "0"
        # OTHER:张三 → 张三
        assert row["Sender"] == "张三"
        assert row["Remark"] == "张三"
        assert row["NickName"] == "张三"

    def test_csv_type_and_subtype(self, tmp_path: Path):
        gen = ExportGenerator()
        rec = _make_record(type_=49, sub_type=57)
        out = tmp_path / "test.csv"
        gen.generate_csv([rec], out)

        with open(out, encoding="utf-8") as f:
            row = list(csv.DictReader(f))[0]

        assert row["Type"] == "49"
        assert row["SubType"] == "57"

    def test_csv_create_time_is_ts(self, tmp_path: Path):
        gen = ExportGenerator()
        out = tmp_path / "test.csv"
        gen.generate_csv(SAMPLE_RECORDS[:1], out)

        with open(out, encoding="utf-8") as f:
            row = list(csv.DictReader(f))[0]

        assert row["CreateTime"] == str(SAMPLE_RECORDS[0]["ts"])

    def test_csv_str_time_uses_time_local(self, tmp_path: Path):
        gen = ExportGenerator()
        out = tmp_path / "test.csv"
        gen.generate_csv(SAMPLE_RECORDS[:1], out)

        with open(out, encoding="utf-8") as f:
            row = list(csv.DictReader(f))[0]

        assert row["StrTime"] == "2025-06-07 14:54:03"

    def test_csv_str_time_fallback_from_ts(self, tmp_path: Path):
        gen = ExportGenerator()
        rec = _make_record(ts=1749279243, time_local="")
        out = tmp_path / "test.csv"
        gen.generate_csv([rec], out)

        with open(out, encoding="utf-8") as f:
            row = list(csv.DictReader(f))[0]

        # 应该从 ts 格式化
        assert row["StrTime"] != ""

    def test_csv_local_id_uses_seq_in_html(self, tmp_path: Path):
        gen = ExportGenerator()
        out = tmp_path / "test.csv"
        gen.generate_csv(SAMPLE_RECORDS[:1], out)

        with open(out, encoding="utf-8") as f:
            row = list(csv.DictReader(f))[0]

        assert row["localId"] == "0"

    def test_csv_local_id_fallback_to_index(self, tmp_path: Path):
        gen = ExportGenerator()
        rec = _make_record(seq_in_html=-1)
        out = tmp_path / "test.csv"
        gen.generate_csv([rec], out)

        with open(out, encoding="utf-8") as f:
            row = list(csv.DictReader(f))[0]

        assert row["localId"] == "0"

    def test_csv_empty_records(self, tmp_path: Path):
        gen = ExportGenerator()
        out = tmp_path / "test.csv"
        gen.generate_csv([], out)

        with open(out, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 0

    def test_csv_chinese_content(self, tmp_path: Path):
        gen = ExportGenerator()
        rec = _make_record(text_raw="你好世界🎉")
        out = tmp_path / "test.csv"
        gen.generate_csv([rec], out)

        with open(out, encoding="utf-8") as f:
            row = list(csv.DictReader(f))[0]

        assert row["StrContent"] == "你好世界🎉"


# ── Markdown Tests ────────────────────────────────────────────────────

class TestGenerateMarkdown:

    def test_md_groups_by_date(self, tmp_path: Path):
        gen = ExportGenerator()
        out = tmp_path / "test.md"
        gen.generate_markdown(SAMPLE_RECORDS, out)

        content = out.read_text(encoding="utf-8")
        # 两个不同日期
        assert "## 2025-06-07" in content
        assert "## 2025-06-08" in content

    def test_md_message_format(self, tmp_path: Path):
        gen = ExportGenerator()
        out = tmp_path / "test.md"
        gen.generate_markdown(SAMPLE_RECORDS[:1], out)

        content = out.read_text(encoding="utf-8")
        # 格式：**HH:MM:SS 说话人**: 消息内容
        assert "**14:54:03 ME**: 你好" in content

    def test_md_other_speaker_name_extracted(self, tmp_path: Path):
        gen = ExportGenerator()
        out = tmp_path / "test.md"
        gen.generate_markdown(SAMPLE_RECORDS[1:2], out)

        content = out.read_text(encoding="utf-8")
        assert "张三" in content

    def test_md_empty_records(self, tmp_path: Path):
        gen = ExportGenerator()
        out = tmp_path / "test.md"
        gen.generate_markdown([], out)

        content = out.read_text(encoding="utf-8")
        assert content.strip() == ""

    def test_md_creates_parent_dirs(self, tmp_path: Path):
        gen = ExportGenerator()
        out = tmp_path / "deep" / "nested" / "test.md"
        gen.generate_markdown(SAMPLE_RECORDS[:1], out)
        assert out.exists()


# ── HTML Tests ────────────────────────────────────────────────────────

class TestGenerateHTML:

    def test_html_contains_chatmessages_var(self, tmp_path: Path):
        gen = ExportGenerator()
        out = tmp_path / "test.html"
        gen.generate_html(SAMPLE_RECORDS, out)

        content = out.read_text(encoding="utf-8")
        assert "var chatMessages =" in content

    def test_html_parseable_by_extract(self, tmp_path: Path):
        """核心测试：生成的 HTML 能被 extract_chatmessages_array 解析"""
        gen = ExportGenerator()
        out = tmp_path / "test.html"
        gen.generate_html(SAMPLE_RECORDS, out)

        parsed = extract_chatmessages_array(out)
        assert len(parsed) == len(SAMPLE_RECORDS)

    def test_html_roundtrip_type(self, tmp_path: Path):
        gen = ExportGenerator()
        out = tmp_path / "test.html"
        gen.generate_html(SAMPLE_RECORDS, out)

        parsed = extract_chatmessages_array(out)
        for orig, msg in zip(SAMPLE_RECORDS, parsed):
            assert msg["type"] == orig["type"]

    def test_html_roundtrip_timestamp(self, tmp_path: Path):
        gen = ExportGenerator()
        out = tmp_path / "test.html"
        gen.generate_html(SAMPLE_RECORDS, out)

        parsed = extract_chatmessages_array(out)
        for orig, msg in zip(SAMPLE_RECORDS, parsed):
            assert msg["timestamp"] == orig["ts"]

    def test_html_roundtrip_text(self, tmp_path: Path):
        gen = ExportGenerator()
        out = tmp_path / "test.html"
        gen.generate_html(SAMPLE_RECORDS, out)

        parsed = extract_chatmessages_array(out)
        for orig, msg in zip(SAMPLE_RECORDS, parsed):
            assert msg["text"] == orig["text_raw"]

    def test_html_roundtrip_is_send(self, tmp_path: Path):
        gen = ExportGenerator()
        out = tmp_path / "test.html"
        gen.generate_html(SAMPLE_RECORDS, out)

        parsed = extract_chatmessages_array(out)
        assert parsed[0]["is_send"] == 1  # ME
        assert parsed[1]["is_send"] == 0  # OTHER:张三

    def test_html_empty_records(self, tmp_path: Path):
        gen = ExportGenerator()
        out = tmp_path / "test.html"
        gen.generate_html([], out)

        parsed = extract_chatmessages_array(out)
        assert len(parsed) == 0

    def test_html_chinese_and_emoji(self, tmp_path: Path):
        gen = ExportGenerator()
        rec = _make_record(text_raw="你好世界🎉😊")
        out = tmp_path / "test.html"
        gen.generate_html([rec], out)

        parsed = extract_chatmessages_array(out)
        assert parsed[0]["text"] == "你好世界🎉😊"

    def test_html_voice_fields(self, tmp_path: Path):
        gen = ExportGenerator()
        rec = _make_record(
            type_=34, modality="voice",
            voice_length=5000, voice_to_text="你好啊",
        )
        out = tmp_path / "test.html"
        gen.generate_html([rec], out)

        parsed = extract_chatmessages_array(out)
        assert parsed[0]["voice_length"] == 5000
        assert parsed[0]["voice_to_text"] == "你好啊"

    def test_html_quote_fields(self, tmp_path: Path):
        gen = ExportGenerator()
        rec = _make_record(
            type_=49, sub_type=57,
            quote_svrid="P1:99", quote_type=1, quote_text="原始消息",
        )
        out = tmp_path / "test.html"
        gen.generate_html([rec], out)

        parsed = extract_chatmessages_array(out)
        assert parsed[0]["svrid"] == "P1:99"
        assert parsed[0]["refermsg_type"] == 1
        assert parsed[0]["refer_text"] == "原始消息"

    def test_html_creates_parent_dirs(self, tmp_path: Path):
        gen = ExportGenerator()
        out = tmp_path / "export" / "test.html"
        gen.generate_html(SAMPLE_RECORDS[:1], out)
        assert out.exists()

    def test_html_special_chars_in_text(self, tmp_path: Path):
        """测试特殊字符（引号、反斜杠等）不会破坏 JSON 解析"""
        gen = ExportGenerator()
        rec = _make_record(text_raw='He said "hello" and \\n newline')
        out = tmp_path / "test.html"
        gen.generate_html([rec], out)

        parsed = extract_chatmessages_array(out)
        assert parsed[0]["text"] == 'He said "hello" and \\n newline'


# ── Helper Method Tests ───────────────────────────────────────────────

class TestHelperMethods:

    def test_is_me_true(self):
        assert ExportGenerator._is_me("ME") is True

    def test_is_me_false_other(self):
        assert ExportGenerator._is_me("OTHER") is False

    def test_is_me_false_other_named(self):
        assert ExportGenerator._is_me("OTHER:张三") is False

    def test_extract_speaker_name_me(self):
        assert ExportGenerator._extract_speaker_name("ME") == "ME"

    def test_extract_speaker_name_other(self):
        assert ExportGenerator._extract_speaker_name("OTHER") == "OTHER"

    def test_extract_speaker_name_other_named(self):
        assert ExportGenerator._extract_speaker_name("OTHER:张三") == "张三"

    def test_format_ts_valid(self):
        result = ExportGenerator._format_ts(1749279243)
        assert result != ""
        # 应该是 YYYY-MM-DD HH:MM:SS 格式
        datetime.strptime(result, "%Y-%m-%d %H:%M:%S")

    def test_format_ts_zero(self):
        assert ExportGenerator._format_ts(0) == ""

    def test_format_ts_none(self):
        assert ExportGenerator._format_ts(None) == ""

    def test_format_ts_negative(self):
        assert ExportGenerator._format_ts(-1) == ""


# ── Property-Based Tests (Hypothesis) ─────────────────────────────────

import tempfile
import string

from hypothesis import given, settings
from hypothesis import strategies as st

from scripts.workspace.ingestion.schema import VALID_MODALITIES


def _speaker_strategy():
    """生成合法的 speaker 值：ME / OTHER / OTHER:{ascii_name}"""
    simple_names = st.text(
        alphabet=string.ascii_letters, min_size=1, max_size=10
    )
    return st.one_of(
        st.just("ME"),
        st.just("OTHER"),
        simple_names.map(lambda n: f"OTHER:{n}"),
    )


def _canonical_record_strategy():
    """生成合法的 CanonicalMessage-like dict"""
    return st.fixed_dictionaries({
        "msg_uid": st.from_regex(r"[A-Z]{1,4}:[0-9]{1,12}", fullmatch=True),
        "ts": st.integers(min_value=946684800, max_value=1893456000),
        "speaker": _speaker_strategy(),
        "type": st.integers(min_value=1, max_value=100),
        "modality": st.sampled_from(sorted(VALID_MODALITIES)),
        "text_raw": st.text(
            alphabet=string.ascii_letters + string.digits + " .,!?",
            min_size=1, max_size=50,
        ),
        "sub_type": st.integers(min_value=0, max_value=100),
    })


class TestExportHTMLRoundtripProperty:
    """Property 17: Export HTML 往返一致性

    **Validates: Requirements 9.3**
    """

    @given(records=st.lists(_canonical_record_strategy(), min_size=0, max_size=20))
    @settings(max_examples=200)
    def test_html_roundtrip_consistency(self, records: list[dict]):
        """Property 17: Export HTML 往返一致性

        For any 消息记录列表，ExportGenerator 生成的 HTML 文件应能被
        extract_chatmessages_array 解析，且解析出的消息数量等于原始记录数量，
        每条消息的核心字段应与原始记录一致。

        **Validates: Requirements 9.3**
        """
        gen = ExportGenerator()

        with tempfile.TemporaryDirectory() as tmpdir:
            html_path = Path(tmpdir) / "test.html"
            gen.generate_html(records, html_path)

            parsed = extract_chatmessages_array(html_path)

            # 消息数量一致
            assert len(parsed) == len(records)

            # 逐条核心字段一致
            for i, (orig, msg) in enumerate(zip(records, parsed)):
                assert msg["type"] == orig["type"], (
                    f"Record {i}: type mismatch: {msg['type']} != {orig['type']}"
                )
                assert msg["timestamp"] == orig["ts"], (
                    f"Record {i}: timestamp mismatch: {msg['timestamp']} != {orig['ts']}"
                )
                assert msg["text"] == orig["text_raw"], (
                    f"Record {i}: text mismatch: {msg['text']!r} != {orig['text_raw']!r}"
                )
                expected_is_send = 1 if orig["speaker"] == "ME" else 0
                assert msg["is_send"] == expected_is_send, (
                    f"Record {i}: is_send mismatch: {msg['is_send']} != {expected_is_send}"
                )
