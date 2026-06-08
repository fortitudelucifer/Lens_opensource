"""
test_adapter_base.py
SourceAdapter 抽象基类的单元测试

验证：
- 抽象方法不可直接实例化
- 子类必须实现 parse() 和 supported_source_type()
- validate_input() 默认行为（路径不存在时返回错误）
- detect_media_files() 默认返回空列表
- describe() 默认返回结构正确的字典
"""

import pytest
from pathlib import Path
from typing import Iterator

from scripts.workspace.ingestion.adapters.base import SourceAdapter


# ── 测试用具体子类 ────────────────────────────────────────────────────

class DummyAdapter(SourceAdapter):
    """测试用适配器"""

    def supported_source_type(self) -> str:
        return "dummy"

    def parse(self, input_path: Path, manifest: 'SourceManifest') -> Iterator[dict]:
        yield {"msg_uid": "D:1", "ts": 1000000, "speaker": "ME",
               "type": 1, "modality": "text", "text_raw": "hello"}


# ── 测试 ──────────────────────────────────────────────────────────────

class TestSourceAdapterAbstract:
    """验证 SourceAdapter 是抽象类，不可直接实例化"""

    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            SourceAdapter()

    def test_missing_parse_raises(self):
        """只实现 supported_source_type 不够"""
        class Incomplete(SourceAdapter):
            def supported_source_type(self) -> str:
                return "incomplete"

        with pytest.raises(TypeError):
            Incomplete()

    def test_missing_supported_source_type_raises(self):
        """只实现 parse 不够"""
        class Incomplete(SourceAdapter):
            def parse(self, input_path, manifest):
                yield {}

        with pytest.raises(TypeError):
            Incomplete()


class TestValidateInput:
    """验证 validate_input() 默认实现"""

    def test_nonexistent_path_returns_error(self, tmp_path: Path):
        adapter = DummyAdapter()
        errors = adapter.validate_input(tmp_path / "不存在的文件.txt")
        assert len(errors) == 1
        assert "输入路径不存在" in errors[0]

    def test_existing_path_returns_empty(self, tmp_path: Path):
        existing = tmp_path / "data.json"
        existing.write_text("{}")
        adapter = DummyAdapter()
        errors = adapter.validate_input(existing)
        assert errors == []

    def test_existing_directory_returns_empty(self, tmp_path: Path):
        adapter = DummyAdapter()
        errors = adapter.validate_input(tmp_path)
        assert errors == []


class TestDetectMediaFiles:
    """验证 detect_media_files() 默认实现"""

    def test_returns_empty_list(self, tmp_path: Path):
        adapter = DummyAdapter()
        result = adapter.detect_media_files(tmp_path)
        assert result == []


class TestDescribe:
    """验证 describe() 默认实现"""

    def test_returns_dict_with_required_keys(self):
        adapter = DummyAdapter()
        info = adapter.describe()
        assert isinstance(info, dict)
        assert info["source_type"] == "dummy"
        assert "expected_files" in info
        assert "field_mapping_example" in info

    def test_description_from_docstring(self):
        adapter = DummyAdapter()
        info = adapter.describe()
        assert info["description"] == "测试用适配器"

    def test_description_empty_when_no_docstring(self):
        class NoDocAdapter(SourceAdapter):
            def supported_source_type(self) -> str:
                return "nodoc"
            def parse(self, input_path, manifest):
                yield {}

        adapter = NoDocAdapter()
        info = adapter.describe()
        assert info["description"] == ""


class TestParse:
    """验证子类 parse() 可正常调用"""

    def test_parse_yields_records(self, tmp_path: Path):
        adapter = DummyAdapter()
        records = list(adapter.parse(tmp_path, None))
        assert len(records) == 1
        assert records[0]["msg_uid"] == "D:1"
