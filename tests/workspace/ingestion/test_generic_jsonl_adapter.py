"""
test_generic_jsonl_adapter.py
通用 JSONL 适配器单元测试

测试 GenericJSONLAdapter 的解析、字段映射、类型转换、输入校验等功能。
映射逻辑（apply_field_mapping / validate_field_mapping）已在 test_generic_csv_adapter.py
和 test_field_mapping.py 中充分测试，此处聚焦 JSONL 特有行为。
"""

import json
import pytest
from pathlib import Path

from scripts.workspace.ingestion.adapters.generic_jsonl import GenericJSONLAdapter
from scripts.workspace.ingestion.manifest import SourceManifest


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def adapter():
    return GenericJSONLAdapter()


@pytest.fixture
def basic_mapping():
    return {
        "send_time": "ts",
        "sender_name": "speaker",
        "content": "text_raw",
        "msg_type": "type",
        "_const:WXWORK": "_source_prefix",
        "_default:text": "modality",
    }


@pytest.fixture
def manifest(basic_mapping):
    return SourceManifest(
        source_type="generic_jsonl",
        input_paths=["test.jsonl"],
        field_mapping=basic_mapping,
    )


def _write_jsonl(path: Path, lines: list[dict | str]) -> Path:
    """写入 JSONL 文件。lines 可以是 dict（自动序列化）或原始字符串。"""
    with open(path, "w", encoding="utf-8") as f:
        for line in lines:
            if isinstance(line, dict):
                f.write(json.dumps(line, ensure_ascii=False) + "\n")
            else:
                f.write(str(line) + "\n")
    return path


# ── 基础测试 ──────────────────────────────────────────────────────────


class TestGenericJSONLAdapterBasic:
    def test_supported_source_type(self, adapter):
        assert adapter.supported_source_type() == "generic_jsonl"

    def test_describe_returns_correct_structure(self, adapter):
        desc = adapter.describe()
        assert desc["source_type"] == "generic_jsonl"
        assert "field_mapping_example" in desc


# ── 输入校验 ──────────────────────────────────────────────────────────


class TestValidateInput:
    def test_nonexistent_path(self, adapter, tmp_path):
        errors = adapter.validate_input(tmp_path / "missing.jsonl")
        assert len(errors) == 1
        assert "不存在" in errors[0]

    def test_non_jsonl_file(self, adapter, tmp_path):
        f = tmp_path / "data.txt"
        f.write_text("{}")
        errors = adapter.validate_input(f)
        assert len(errors) == 1
        assert "期望 JSONL 文件" in errors[0]

    def test_jsonl_file_valid(self, adapter, tmp_path):
        f = tmp_path / "data.jsonl"
        f.write_text("{}")
        errors = adapter.validate_input(f)
        assert errors == []

    def test_directory_valid(self, adapter, tmp_path):
        """目录不检查扩展名"""
        errors = adapter.validate_input(tmp_path)
        assert errors == []


# ── 解析测试 ──────────────────────────────────────────────────────────


class TestParse:
    def test_parse_basic_jsonl(self, adapter, manifest, tmp_path):
        """基本解析：字段映射 + msg_uid 生成"""
        jsonl_path = _write_jsonl(tmp_path / "data.jsonl", [
            {"send_time": 1700000000, "sender_name": "ME", "content": "你好", "msg_type": 1},
            {"send_time": 1700000060, "sender_name": "OTHER", "content": "世界", "msg_type": 1},
        ])
        records = list(adapter.parse(jsonl_path, manifest))
        assert len(records) == 2

        assert records[0]["msg_uid"] == "WXWORK:1"
        assert records[0]["ts"] == 1700000000
        assert records[0]["speaker"] == "ME"
        assert records[0]["text_raw"] == "你好"
        assert records[0]["type"] == 1
        assert records[0]["modality"] == "text"

        assert records[1]["msg_uid"] == "WXWORK:2"
        assert records[1]["ts"] == 1700000060

    def test_parse_default_prefix(self, adapter, tmp_path):
        """无 _source_prefix 配置时默认使用 JSONL"""
        manifest_no_prefix = SourceManifest(
            source_type="generic_jsonl",
            input_paths=["test.jsonl"],
            field_mapping={
                "send_time": "ts",
                "sender_name": "speaker",
                "content": "text_raw",
                "msg_type": "type",
                "_default:text": "modality",
            },
        )
        jsonl_path = _write_jsonl(tmp_path / "data.jsonl", [
            {"send_time": 1700000000, "sender_name": "ME", "content": "hi", "msg_type": 1},
        ])
        records = list(adapter.parse(jsonl_path, manifest_no_prefix))
        assert records[0]["msg_uid"] == "JSONL:1"

    def test_parse_custom_prefix(self, adapter, tmp_path):
        """自定义 _source_prefix"""
        manifest_custom = SourceManifest(
            source_type="generic_jsonl",
            input_paths=["test.jsonl"],
            field_mapping={
                "ts": "ts",
                "speaker": "speaker",
                "text": "text_raw",
                "_const:1": "type",
                "_const:text": "modality",
                "_const:CUSTOM": "_source_prefix",
            },
        )
        jsonl_path = _write_jsonl(tmp_path / "data.jsonl", [
            {"ts": 100, "speaker": "ME", "text": "hello"},
        ])
        records = list(adapter.parse(jsonl_path, manifest_custom))
        assert records[0]["msg_uid"] == "CUSTOM:1"

    def test_parse_type_conversion_ts(self, adapter, manifest, tmp_path):
        """ts 字段自动转为 int"""
        jsonl_path = _write_jsonl(tmp_path / "data.jsonl", [
            {"send_time": "1700000000", "sender_name": "ME", "content": "hi", "msg_type": "1"},
        ])
        records = list(adapter.parse(jsonl_path, manifest))
        assert records[0]["ts"] == 1700000000
        assert isinstance(records[0]["ts"], int)

    def test_parse_type_conversion_type(self, adapter, manifest, tmp_path):
        """type 字段自动转为 int"""
        jsonl_path = _write_jsonl(tmp_path / "data.jsonl", [
            {"send_time": 100, "sender_name": "ME", "content": "hi", "msg_type": "3"},
        ])
        records = list(adapter.parse(jsonl_path, manifest))
        assert records[0]["type"] == 3
        assert isinstance(records[0]["type"], int)

    def test_parse_invalid_ts_defaults_to_zero(self, adapter, manifest, tmp_path):
        """ts 转换失败时默认为 0"""
        jsonl_path = _write_jsonl(tmp_path / "data.jsonl", [
            {"send_time": "not_a_number", "sender_name": "ME", "content": "hi", "msg_type": 1},
        ])
        records = list(adapter.parse(jsonl_path, manifest))
        assert records[0]["ts"] == 0

    def test_parse_sub_type_conversion(self, adapter, tmp_path):
        """sub_type 字段自动转为 int"""
        manifest_sub = SourceManifest(
            source_type="generic_jsonl",
            input_paths=["test.jsonl"],
            field_mapping={
                "ts": "ts",
                "speaker": "speaker",
                "text": "text_raw",
                "_const:1": "type",
                "_const:text": "modality",
                "sub": "sub_type",
            },
        )
        jsonl_path = _write_jsonl(tmp_path / "data.jsonl", [
            {"ts": 100, "speaker": "ME", "text": "hi", "sub": "57"},
        ])
        records = list(adapter.parse(jsonl_path, manifest_sub))
        assert records[0]["sub_type"] == 57

    def test_parse_empty_file(self, adapter, manifest, tmp_path):
        """空文件返回空列表"""
        jsonl_path = tmp_path / "empty.jsonl"
        jsonl_path.write_text("")
        records = list(adapter.parse(jsonl_path, manifest))
        assert records == []

    def test_parse_skips_blank_lines(self, adapter, manifest, tmp_path):
        """跳过空行"""
        jsonl_path = _write_jsonl(tmp_path / "data.jsonl", [
            {"send_time": 100, "sender_name": "ME", "content": "first", "msg_type": 1},
            "",
            "   ",
            {"send_time": 200, "sender_name": "OTHER", "content": "second", "msg_type": 1},
        ])
        records = list(adapter.parse(jsonl_path, manifest))
        assert len(records) == 2
        # row_num 只计非空行
        assert records[0]["msg_uid"] == "WXWORK:1"
        assert records[1]["msg_uid"] == "WXWORK:2"

    def test_parse_skips_invalid_json(self, adapter, manifest, tmp_path):
        """JSON 解析失败的行被跳过"""
        jsonl_path = tmp_path / "data.jsonl"
        jsonl_path.write_text(
            '{"send_time": 100, "sender_name": "ME", "content": "ok", "msg_type": 1}\n'
            'this is not json\n'
            '{"send_time": 200, "sender_name": "OTHER", "content": "hi", "msg_type": 1}\n'
        )
        records = list(adapter.parse(jsonl_path, manifest))
        assert len(records) == 2

    def test_parse_chinese_content(self, adapter, manifest, tmp_path):
        """中文内容正确处理"""
        jsonl_path = _write_jsonl(tmp_path / "data.jsonl", [
            {"send_time": 100, "sender_name": "OTHER:张三", "content": "你好世界🌍", "msg_type": 1},
        ])
        records = list(adapter.parse(jsonl_path, manifest))
        assert records[0]["text_raw"] == "你好世界🌍"
        assert records[0]["speaker"] == "OTHER:张三"

    def test_parse_const_type_conversion(self, adapter, tmp_path):
        """_const 值的 type 也会被转为 int"""
        manifest_const = SourceManifest(
            source_type="generic_jsonl",
            input_paths=["test.jsonl"],
            field_mapping={
                "ts": "ts",
                "speaker": "speaker",
                "text": "text_raw",
                "_const:1": "type",
                "_const:text": "modality",
            },
        )
        jsonl_path = _write_jsonl(tmp_path / "data.jsonl", [
            {"ts": 100, "speaker": "ME", "text": "hi"},
        ])
        records = list(adapter.parse(jsonl_path, manifest_const))
        assert records[0]["type"] == 1
        assert isinstance(records[0]["type"], int)

    def test_parse_row_numbering_1_based(self, adapter, manifest, tmp_path):
        """行号从 1 开始"""
        jsonl_path = _write_jsonl(tmp_path / "data.jsonl", [
            {"send_time": 100, "sender_name": "ME", "content": "a", "msg_type": 1},
            {"send_time": 200, "sender_name": "ME", "content": "b", "msg_type": 1},
            {"send_time": 300, "sender_name": "ME", "content": "c", "msg_type": 1},
        ])
        records = list(adapter.parse(jsonl_path, manifest))
        assert [r["msg_uid"] for r in records] == ["WXWORK:1", "WXWORK:2", "WXWORK:3"]

    def test_source_prefix_not_in_output_record(self, adapter, manifest, tmp_path):
        """_source_prefix 不应出现在输出记录中"""
        jsonl_path = _write_jsonl(tmp_path / "data.jsonl", [
            {"send_time": 100, "sender_name": "ME", "content": "hi", "msg_type": 1},
        ])
        records = list(adapter.parse(jsonl_path, manifest))
        assert "_source_prefix" not in records[0]

    def test_parse_missing_field_uses_default(self, adapter, tmp_path):
        """源字段缺失时使用 _default 值"""
        manifest_default = SourceManifest(
            source_type="generic_jsonl",
            input_paths=["test.jsonl"],
            field_mapping={
                "ts": "ts",
                "speaker": "speaker",
                "text": "text_raw",
                "_const:1": "type",
                "_default:text": "modality",
                "_default:0": "sub_type",
            },
        )
        jsonl_path = _write_jsonl(tmp_path / "data.jsonl", [
            {"ts": 100, "speaker": "ME", "text": "hi"},
        ])
        records = list(adapter.parse(jsonl_path, manifest_default))
        assert records[0]["modality"] == "text"
        assert records[0]["sub_type"] == 0
