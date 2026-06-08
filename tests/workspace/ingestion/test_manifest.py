"""
test_manifest.py
Source Manifest 加载与校验的单元测试

测试覆盖：
- SourceManifest dataclass 创建和默认值
- load_manifest() 加载 YAML 文件
- validate_manifest() 校验清单配置

运行方式：
    python -m pytest tests/workspace/ingestion/test_manifest.py -v
"""

import sys
from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.workspace.ingestion.manifest import (
    SourceManifest,
    load_manifest,
    validate_manifest,
)


# ── SourceManifest dataclass 测试 ────────────────────────────────────

class TestSourceManifest:
    """SourceManifest dataclass 测试"""

    def test_create_with_required_fields(self):
        """仅必填字段即可创建实例"""
        m = SourceManifest(
            source_type="telegram_json",
            input_paths=["./result.json"],
        )
        assert m.source_type == "telegram_json"
        assert m.input_paths == ["./result.json"]

    def test_default_values(self):
        """可选字段应有正确的默认值"""
        m = SourceManifest(source_type="test", input_paths=["/a"])
        assert m.participant_map == {}
        assert m.timezone == "Asia/Shanghai"
        assert m.media_base_dir is None
        assert m.field_mapping == {}
        assert m.workspace_name is None

    def test_all_fields(self):
        """所有字段均可设置"""
        m = SourceManifest(
            source_type="wechat_html",
            input_paths=["/a", "/b"],
            participant_map={"张三": "ME"},
            timezone="UTC",
            media_base_dir="/media",
            field_mapping={"col1": "ts"},
            workspace_name="test_ws",
        )
        assert m.participant_map == {"张三": "ME"}
        assert m.timezone == "UTC"
        assert m.media_base_dir == "/media"
        assert m.field_mapping == {"col1": "ts"}
        assert m.workspace_name == "test_ws"


# ── load_manifest 测试 ───────────────────────────────────────────────

class TestLoadManifest:
    """load_manifest() 测试"""

    def test_load_valid_manifest(self, tmp_path):
        """加载合法的 YAML 文件"""
        data = {
            "source_type": "telegram_json",
            "input_paths": ["./result.json"],
            "participant_map": {"John": "OTHER"},
            "timezone": "UTC",
        }
        p = tmp_path / "source_manifest.yaml"
        p.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")

        m = load_manifest(p)
        assert m.source_type == "telegram_json"
        assert m.input_paths == ["./result.json"]
        assert m.participant_map == {"John": "OTHER"}
        assert m.timezone == "UTC"

    def test_load_minimal_manifest(self, tmp_path):
        """仅包含必填字段的 YAML"""
        data = {"source_type": "wechat_html", "input_paths": ["/data/export.html"]}
        p = tmp_path / "source_manifest.yaml"
        p.write_text(yaml.dump(data), encoding="utf-8")

        m = load_manifest(p)
        assert m.source_type == "wechat_html"
        assert m.timezone == "Asia/Shanghai"  # 默认值
        assert m.participant_map == {}

    def test_load_file_not_found(self, tmp_path):
        """文件不存在应抛出 FileNotFoundError"""
        with pytest.raises(FileNotFoundError, match="不存在"):
            load_manifest(tmp_path / "nonexistent.yaml")

    def test_load_not_dict(self, tmp_path):
        """YAML 内容不是字典应抛出 ValueError"""
        p = tmp_path / "source_manifest.yaml"
        p.write_text("- item1\n- item2\n", encoding="utf-8")

        with pytest.raises(ValueError, match="格式错误.*期望字典"):
            load_manifest(p)

    def test_load_missing_source_type(self, tmp_path):
        """缺少 source_type 应抛出 ValueError"""
        data = {"input_paths": ["/a"]}
        p = tmp_path / "source_manifest.yaml"
        p.write_text(yaml.dump(data), encoding="utf-8")

        with pytest.raises(ValueError, match="缺少必填字段: source_type"):
            load_manifest(p)

    def test_load_missing_input_paths(self, tmp_path):
        """缺少 input_paths 应抛出 ValueError"""
        data = {"source_type": "test"}
        p = tmp_path / "source_manifest.yaml"
        p.write_text(yaml.dump(data), encoding="utf-8")

        with pytest.raises(ValueError, match="缺少必填字段: input_paths"):
            load_manifest(p)

    def test_load_with_field_mapping(self, tmp_path):
        """field_mapping 字段应正确加载"""
        data = {
            "source_type": "generic_csv",
            "input_paths": ["./data.csv"],
            "field_mapping": {"timestamp": "ts", "_const:text": "modality"},
        }
        p = tmp_path / "source_manifest.yaml"
        p.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")

        m = load_manifest(p)
        assert m.field_mapping == {"timestamp": "ts", "_const:text": "modality"}

    def test_load_with_media_base_dir(self, tmp_path):
        """media_base_dir 字段应正确加载"""
        data = {
            "source_type": "telegram_json",
            "input_paths": ["./result.json"],
            "media_base_dir": "/data/media",
        }
        p = tmp_path / "source_manifest.yaml"
        p.write_text(yaml.dump(data), encoding="utf-8")

        m = load_manifest(p)
        assert m.media_base_dir == "/data/media"

    def test_load_with_workspace_name(self, tmp_path):
        """workspace_name 字段应正确加载"""
        data = {
            "source_type": "wechat_html",
            "input_paths": ["/a"],
            "workspace_name": "my_chat",
        }
        p = tmp_path / "source_manifest.yaml"
        p.write_text(yaml.dump(data), encoding="utf-8")

        m = load_manifest(p)
        assert m.workspace_name == "my_chat"

    def test_load_chinese_content(self, tmp_path):
        """中文内容应正确加载"""
        content = (
            "source_type: wechat_html\n"
            "input_paths:\n"
            "  - ./导出文件.html\n"
            "participant_map:\n"
            "  张三: ME\n"
            "  李四: OTHER\n"
        )
        p = tmp_path / "source_manifest.yaml"
        p.write_text(content, encoding="utf-8")

        m = load_manifest(p)
        assert m.input_paths == ["./导出文件.html"]
        assert m.participant_map == {"张三": "ME", "李四": "OTHER"}

    def test_load_null_yaml(self, tmp_path):
        """空 YAML 文件（解析为 None）应抛出 ValueError"""
        p = tmp_path / "source_manifest.yaml"
        p.write_text("", encoding="utf-8")

        with pytest.raises(ValueError, match="格式错误.*期望字典.*NoneType"):
            load_manifest(p)


# ── validate_manifest 测试 ───────────────────────────────────────────

class TestValidateManifest:
    """validate_manifest() 测试"""

    REGISTERED = {"wechat_html", "telegram_json", "whatsapp_txt", "generic_csv", "generic_jsonl"}

    def test_valid_manifest_no_errors(self):
        """合法清单应返回空错误列表"""
        m = SourceManifest(source_type="telegram_json", input_paths=["./result.json"])
        errors = validate_manifest(m, self.REGISTERED)
        assert errors == []

    def test_unknown_source_type(self):
        """未注册的 source_type 应报错并列出可用值"""
        m = SourceManifest(source_type="unknown_type", input_paths=["/a"])
        errors = validate_manifest(m, self.REGISTERED)
        assert len(errors) == 1
        assert "未知的 source_type" in errors[0]
        assert "unknown_type" in errors[0]
        # 应列出所有可用值
        for t in self.REGISTERED:
            assert t in errors[0]

    def test_empty_input_paths(self):
        """空 input_paths 应报错"""
        m = SourceManifest(source_type="wechat_html", input_paths=[])
        errors = validate_manifest(m, self.REGISTERED)
        assert any("input_paths 不能为空" in e for e in errors)

    def test_both_errors(self):
        """同时存在多个错误应全部报告"""
        m = SourceManifest(source_type="bad_type", input_paths=[])
        errors = validate_manifest(m, self.REGISTERED)
        assert len(errors) == 2

    def test_empty_registered_types(self):
        """注册表为空时任何 source_type 都应报错"""
        m = SourceManifest(source_type="wechat_html", input_paths=["/a"])
        errors = validate_manifest(m, set())
        assert len(errors) == 1
        assert "未知的 source_type" in errors[0]

    def test_available_types_sorted(self):
        """错误信息中的可用值应按字母排序"""
        m = SourceManifest(source_type="bad", input_paths=["/a"])
        errors = validate_manifest(m, {"z_type", "a_type", "m_type"})
        assert "a_type, m_type, z_type" in errors[0]
