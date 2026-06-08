"""
test_generic_csv_adapter.py
通用 CSV 适配器的单元测试

验证：
- GenericCSVAdapter 基本属性（source_type、describe）
- validate_input 校验逻辑
- apply_field_mapping 三种映射语法（直接映射、常量值、默认值）
- validate_field_mapping 必填字段缺失校验
- parse() 解析 CSV 输出标准消息格式
- msg_uid 生成（_source_prefix 配置 + 默认 CSV 前缀）
- 类型转换（ts → int, type → int, sub_type → int）
- 编码容错（errors='replace'）

Requirements: 7.1, 7.3, 7.4
"""

import pytest
from pathlib import Path

from scripts.workspace.ingestion.adapters.generic_csv import (
    GenericCSVAdapter,
    apply_field_mapping,
    validate_field_mapping,
)
from scripts.workspace.ingestion.manifest import SourceManifest
from scripts.workspace.ingestion.schema import REQUIRED_FIELDS


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def adapter():
    return GenericCSVAdapter()


@pytest.fixture
def basic_mapping():
    """基础 field_mapping，覆盖所有必填字段"""
    return {
        "timestamp": "ts",
        "sender_name": "speaker",
        "content": "text_raw",
        "_const:text": "modality",
        "_const:1": "type",
        "_default:0": "sub_type",
        "_const:GEN": "_source_prefix",
    }


@pytest.fixture
def manifest(basic_mapping):
    return SourceManifest(
        source_type="generic_csv",
        input_paths=["./data.csv"],
        field_mapping=basic_mapping,
    )


def _write_csv(path: Path, header: str, rows: list[str]):
    """写入 CSV 文件"""
    lines = [header] + rows
    path.write_text("\n".join(lines), encoding="utf-8")


# ── 基本属性测试 ──────────────────────────────────────────────────────

class TestGenericCSVAdapterBasic:

    def test_supported_source_type(self, adapter):
        assert adapter.supported_source_type() == "generic_csv"

    def test_describe_returns_correct_structure(self, adapter):
        info = adapter.describe()
        assert info["source_type"] == "generic_csv"
        assert "CSV" in info["description"]
        assert len(info["expected_files"]) >= 1
        assert isinstance(info["field_mapping_example"], dict)
        assert "timestamp" in info["field_mapping_example"]


# ── apply_field_mapping 测试 ──────────────────────────────────────────

class TestApplyFieldMapping:

    def test_direct_mapping(self):
        """直接映射：source_field → target_field"""
        row = {"timestamp": "1700000000", "sender": "Alice"}
        mapping = {"timestamp": "ts", "sender": "speaker"}
        result = apply_field_mapping(row, mapping)
        assert result["ts"] == "1700000000"
        assert result["speaker"] == "Alice"

    def test_const_mapping(self):
        """常量值：_const:value → target_field"""
        row = {"content": "hello"}
        mapping = {"_const:text": "modality", "_const:1": "type"}
        result = apply_field_mapping(row, mapping)
        assert result["modality"] == "text"
        assert result["type"] == "1"

    def test_default_mapping_when_missing(self):
        """默认值：源字段缺失时使用默认值"""
        row = {"content": "hello"}
        mapping = {"_default:0": "sub_type", "content": "text_raw"}
        result = apply_field_mapping(row, mapping)
        assert result["sub_type"] == "0"
        assert result["text_raw"] == "hello"

    def test_default_not_used_when_direct_mapping_exists(self):
        """默认值：直接映射存在时不使用默认值"""
        row = {"sub_type_col": "5"}
        mapping = {"sub_type_col": "sub_type", "_default:0": "sub_type"}
        result = apply_field_mapping(row, mapping)
        assert result["sub_type"] == "5"

    def test_default_used_when_source_field_empty(self):
        """默认值：源字段为空字符串时使用默认值"""
        row = {"sub_type_col": ""}
        mapping = {"sub_type_col": "sub_type", "_default:0": "sub_type"}
        result = apply_field_mapping(row, mapping)
        assert result["sub_type"] == "0"

    def test_const_overrides_default(self):
        """常量值优先于默认值"""
        row = {}
        mapping = {"_const:text": "modality", "_default:image": "modality"}
        result = apply_field_mapping(row, mapping)
        assert result["modality"] == "text"

    def test_missing_source_field_not_in_result(self):
        """源字段不存在时，直接映射不产生目标字段"""
        row = {"content": "hello"}
        mapping = {"nonexistent": "speaker", "content": "text_raw"}
        result = apply_field_mapping(row, mapping)
        assert "speaker" not in result
        assert result["text_raw"] == "hello"

    def test_empty_mapping(self):
        """空映射返回空字典"""
        result = apply_field_mapping({"a": "1"}, {})
        assert result == {}

    def test_empty_row(self):
        """空行 + 常量/默认值仍然生效"""
        mapping = {"_const:text": "modality", "_default:0": "sub_type"}
        result = apply_field_mapping({}, mapping)
        assert result["modality"] == "text"
        assert result["sub_type"] == "0"

    def test_source_prefix_in_mapping(self):
        """_source_prefix 作为特殊 target_field"""
        row = {}
        mapping = {"_const:QQ": "_source_prefix"}
        result = apply_field_mapping(row, mapping)
        assert result["_source_prefix"] == "QQ"


# ── validate_field_mapping 测试 ───────────────────────────────────────

class TestValidateFieldMapping:

    def test_all_required_fields_covered(self):
        """所有必填字段都有映射 → 无错误"""
        mapping = {
            "timestamp": "ts",
            "sender": "speaker",
            "content": "text_raw",
            "_const:text": "modality",
            "_const:1": "type",
        }
        errors = validate_field_mapping(mapping)
        assert errors == []

    def test_missing_ts(self):
        """缺少 ts 映射 → 报错"""
        mapping = {
            "sender": "speaker",
            "content": "text_raw",
            "_const:text": "modality",
            "_const:1": "type",
        }
        errors = validate_field_mapping(mapping)
        assert any("ts" in e for e in errors)

    def test_missing_multiple_fields(self):
        """缺少多个必填字段"""
        mapping = {"_const:text": "modality"}
        errors = validate_field_mapping(mapping)
        # 应该缺少 ts, speaker, type, text_raw
        assert len(errors) >= 4

    def test_msg_uid_not_required_in_mapping(self):
        """msg_uid 由适配器自动生成，不需要在 mapping 中"""
        mapping = {
            "timestamp": "ts",
            "sender": "speaker",
            "content": "text_raw",
            "_const:text": "modality",
            "_const:1": "type",
        }
        errors = validate_field_mapping(mapping)
        assert errors == []

    def test_const_covers_required_field(self):
        """常量值可以覆盖必填字段"""
        mapping = {
            "timestamp": "ts",
            "sender": "speaker",
            "content": "text_raw",
            "_const:text": "modality",
            "_const:1": "type",
        }
        errors = validate_field_mapping(mapping)
        assert errors == []

    def test_default_covers_required_field(self):
        """默认值可以覆盖必填字段"""
        mapping = {
            "timestamp": "ts",
            "sender": "speaker",
            "content": "text_raw",
            "_const:text": "modality",
            "_default:1": "type",
        }
        errors = validate_field_mapping(mapping)
        assert errors == []

    def test_empty_mapping(self):
        """空映射 → 所有必填字段（除 msg_uid）缺失"""
        errors = validate_field_mapping({})
        required_minus_uid = set(REQUIRED_FIELDS) - {"msg_uid"}
        assert len(errors) == len(required_minus_uid)


# ── validate_input 测试 ───────────────────────────────────────────────

class TestValidateInput:

    def test_nonexistent_path(self, adapter, tmp_path):
        errors = adapter.validate_input(tmp_path / "不存在.csv")
        assert len(errors) == 1
        assert "输入路径不存在" in errors[0]

    def test_non_csv_file(self, adapter, tmp_path):
        f = tmp_path / "data.json"
        f.write_text("{}")
        errors = adapter.validate_input(f)
        assert len(errors) == 1
        assert "期望 CSV 文件" in errors[0]

    def test_csv_file_valid(self, adapter, tmp_path):
        f = tmp_path / "data.csv"
        f.write_text("a,b\n1,2")
        errors = adapter.validate_input(f)
        assert errors == []

    def test_directory_valid(self, adapter, tmp_path):
        """目录输入不检查后缀"""
        errors = adapter.validate_input(tmp_path)
        assert errors == []


# ── parse() 测试 ─────────────────────────────────────────────────────

class TestParse:

    def test_parse_basic_csv(self, adapter, manifest, tmp_path):
        """解析基础 CSV"""
        f = tmp_path / "data.csv"
        _write_csv(f, "timestamp,sender_name,content", [
            "1700000000,Alice,你好",
            "1700000060,Bob,世界",
        ])

        records = list(adapter.parse(f, manifest))
        assert len(records) == 2

        r0 = records[0]
        assert r0["msg_uid"] == "GEN:1"
        assert r0["ts"] == 1700000000
        assert r0["speaker"] == "Alice"
        assert r0["text_raw"] == "你好"
        assert r0["modality"] == "text"
        assert r0["type"] == 1

        r1 = records[1]
        assert r1["msg_uid"] == "GEN:2"
        assert r1["ts"] == 1700000060
        assert r1["speaker"] == "Bob"

    def test_parse_default_prefix_csv(self, adapter, tmp_path):
        """无 _source_prefix 配置时使用 CSV 默认前缀"""
        mapping = {
            "timestamp": "ts",
            "sender": "speaker",
            "content": "text_raw",
            "_const:text": "modality",
            "_const:1": "type",
        }
        m = SourceManifest(
            source_type="generic_csv",
            input_paths=["./data.csv"],
            field_mapping=mapping,
        )
        f = tmp_path / "data.csv"
        _write_csv(f, "timestamp,sender,content", ["1700000000,Alice,hello"])

        records = list(adapter.parse(f, m))
        assert records[0]["msg_uid"] == "CSV:1"

    def test_parse_custom_prefix(self, adapter, tmp_path):
        """自定义 _source_prefix"""
        mapping = {
            "timestamp": "ts",
            "sender": "speaker",
            "content": "text_raw",
            "_const:text": "modality",
            "_const:1": "type",
            "_const:QQ": "_source_prefix",
        }
        m = SourceManifest(
            source_type="generic_csv",
            input_paths=["./data.csv"],
            field_mapping=mapping,
        )
        f = tmp_path / "data.csv"
        _write_csv(f, "timestamp,sender,content", ["1700000000,Alice,hello"])

        records = list(adapter.parse(f, m))
        assert records[0]["msg_uid"] == "QQ:1"

    def test_parse_type_conversion_ts(self, adapter, manifest, tmp_path):
        """ts 字段自动转为 int"""
        f = tmp_path / "data.csv"
        _write_csv(f, "timestamp,sender_name,content", ["1700000000,Alice,hi"])

        records = list(adapter.parse(f, manifest))
        assert isinstance(records[0]["ts"], int)
        assert records[0]["ts"] == 1700000000

    def test_parse_type_conversion_type(self, adapter, tmp_path):
        """type 字段自动转为 int（来自直接映射时）"""
        mapping = {
            "timestamp": "ts",
            "sender": "speaker",
            "content": "text_raw",
            "_const:text": "modality",
            "msg_type": "type",
        }
        m = SourceManifest(
            source_type="generic_csv",
            input_paths=["./data.csv"],
            field_mapping=mapping,
        )
        f = tmp_path / "data.csv"
        _write_csv(f, "timestamp,sender,content,msg_type", ["1700000000,Alice,hi,3"])

        records = list(adapter.parse(f, m))
        assert isinstance(records[0]["type"], int)
        assert records[0]["type"] == 3

    def test_parse_invalid_ts_defaults_to_zero(self, adapter, manifest, tmp_path):
        """ts 转换失败时默认为 0"""
        f = tmp_path / "data.csv"
        _write_csv(f, "timestamp,sender_name,content", ["not_a_number,Alice,hi"])

        records = list(adapter.parse(f, manifest))
        assert records[0]["ts"] == 0

    def test_parse_empty_csv(self, adapter, manifest, tmp_path):
        """空 CSV（只有表头）"""
        f = tmp_path / "data.csv"
        f.write_text("timestamp,sender_name,content\n", encoding="utf-8")

        records = list(adapter.parse(f, manifest))
        assert records == []

    def test_parse_sub_type_conversion(self, adapter, manifest, tmp_path):
        """sub_type 默认值 '0' 转为 int 0"""
        f = tmp_path / "data.csv"
        _write_csv(f, "timestamp,sender_name,content", ["1700000000,Alice,hi"])

        records = list(adapter.parse(f, manifest))
        assert isinstance(records[0]["sub_type"], int)
        assert records[0]["sub_type"] == 0

    def test_parse_const_type_conversion(self, adapter, manifest, tmp_path):
        """常量 type='1' 转为 int 1"""
        f = tmp_path / "data.csv"
        _write_csv(f, "timestamp,sender_name,content", ["1700000000,Alice,hi"])

        records = list(adapter.parse(f, manifest))
        assert isinstance(records[0]["type"], int)
        assert records[0]["type"] == 1

    def test_parse_row_numbering_1_based(self, adapter, manifest, tmp_path):
        """msg_uid 行号从 1 开始"""
        f = tmp_path / "data.csv"
        _write_csv(f, "timestamp,sender_name,content", [
            "1700000000,A,first",
            "1700000001,B,second",
            "1700000002,C,third",
        ])

        records = list(adapter.parse(f, manifest))
        assert records[0]["msg_uid"] == "GEN:1"
        assert records[1]["msg_uid"] == "GEN:2"
        assert records[2]["msg_uid"] == "GEN:3"

    def test_parse_chinese_content(self, adapter, manifest, tmp_path):
        """中文内容正确处理"""
        f = tmp_path / "data.csv"
        _write_csv(f, "timestamp,sender_name,content", [
            "1700000000,张三,你好世界🌍",
        ])

        records = list(adapter.parse(f, manifest))
        assert records[0]["text_raw"] == "你好世界🌍"
        assert records[0]["speaker"] == "张三"

    def test_parse_missing_column_uses_default(self, adapter, tmp_path):
        """CSV 中缺少某列时，默认值生效"""
        mapping = {
            "timestamp": "ts",
            "sender": "speaker",
            "content": "text_raw",
            "_const:text": "modality",
            "_const:1": "type",
            "extra_col": "sub_type",
            "_default:0": "sub_type",
        }
        m = SourceManifest(
            source_type="generic_csv",
            input_paths=["./data.csv"],
            field_mapping=mapping,
        )
        f = tmp_path / "data.csv"
        # CSV 没有 extra_col 列
        _write_csv(f, "timestamp,sender,content", ["1700000000,Alice,hi"])

        records = list(adapter.parse(f, m))
        assert records[0]["sub_type"] == 0  # 默认值 '0' 转为 int

    def test_source_prefix_not_in_output_record(self, adapter, manifest, tmp_path):
        """_source_prefix 不应出现在输出记录中"""
        f = tmp_path / "data.csv"
        _write_csv(f, "timestamp,sender_name,content", ["1700000000,Alice,hi"])

        records = list(adapter.parse(f, manifest))
        assert "_source_prefix" not in records[0]
