"""
test_run_ingest.py
run_ingest.py CLI 入口单元测试

覆盖：
- --show-schema 输出 schema 表格
- --show-adapters 列出适配器 / 查看详情
- --init-manifest 生成 manifest 模板
- --dry-run 预检模式
- 默认运行模式（完整转换）
- 参数校验与错误处理

运行方式：
    conda run -n wechatDHA python -m pytest tests/workspace/ingestion/test_run_ingest.py -x -v
"""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from typing import Iterator
from unittest.mock import patch

import pytest

from scripts.workspace.ingestion.adapters.base import SourceAdapter
from scripts.workspace.ingestion.engine import IngestionEngine
from scripts.workspace.ingestion.manifest import SourceManifest
from scripts.workspace.ingestion.registry import AdapterRegistry
from scripts.workspace.run_ingest import (
    build_parser,
    cmd_dry_run,
    cmd_init_manifest,
    cmd_run,
    cmd_show_adapters,
    cmd_show_schema,
    main,
    _print_dry_run_report,
    _print_ingestion_report,
    _resolve_workspace_root,
)


# ── Mock 适配器 ───────────────────────────────────────────────────────


class _MockAdapter(SourceAdapter):
    """测试用 mock 适配器"""

    def __init__(self, records: list[dict] | None = None):
        self._records = records or []

    def supported_source_type(self) -> str:
        return "mock_test"

    def parse(self, input_path: Path, manifest: SourceManifest) -> Iterator[dict]:
        yield from self._records

    def validate_input(self, input_path: Path) -> list[str]:
        return []

    def describe(self) -> dict:
        return {
            "source_type": "mock_test",
            "description": "测试用 mock 适配器",
            "expected_files": ["test.json"],
            "field_mapping_example": {"src": "dst"},
        }


def _valid_record(
    msg_uid: str = "T:1",
    ts: int = 1700000000,
    speaker: str = "ME",
    type_: int = 1,
    modality: str = "text",
    text_raw: str = "hello",
) -> dict:
    return {
        "msg_uid": msg_uid,
        "ts": ts,
        "speaker": speaker,
        "type": type_,
        "modality": modality,
        "text_raw": text_raw,
    }


def _make_engine(records: list[dict] | None = None) -> IngestionEngine:
    registry = AdapterRegistry()
    registry.register(_MockAdapter(records))
    return registry, IngestionEngine(registry)


def _write_manifest(workspace_root: Path, source_type: str = "mock_test") -> Path:
    """在 workspace_root/raw/ 下写入一个最小 manifest。"""
    raw_dir = workspace_root / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = raw_dir / "source_manifest.yaml"
    manifest_path.write_text(
        f"source_type: {source_type}\n"
        f"input_paths:\n"
        f"  - ./test_input\n",
        encoding="utf-8",
    )
    return manifest_path


# ── _resolve_workspace_root 测试 ──────────────────────────────────────


class TestResolveWorkspaceRoot:
    def test_default_base_dir(self, tmp_path: Path):
        """无 paths.yaml 时使用默认 base_dir"""
        with patch("scripts.workspace.run_ingest._PROJECT_ROOT", tmp_path):
            root = _resolve_workspace_root("test_ws")
            assert root == Path("<WORKSPACES_DIR>/test_ws")

    def test_custom_base_dir(self, tmp_path: Path):
        """从 paths.yaml 读取 base_dir"""
        configs_dir = tmp_path / "configs"
        configs_dir.mkdir()
        (configs_dir / "paths.yaml").write_text(
            "base_dir: /custom/path\nworkspace_name: ignored\n",
            encoding="utf-8",
        )
        with patch("scripts.workspace.run_ingest._PROJECT_ROOT", tmp_path):
            root = _resolve_workspace_root("my_ws")
            assert root == Path("/custom/path/my_ws")


# ── --show-schema 测试 ────────────────────────────────────────────────


class TestShowSchema:
    def test_show_schema_returns_zero(self):
        _, engine = _make_engine()
        assert cmd_show_schema(engine) == 0

    def test_show_schema_output(self, capsys):
        _, engine = _make_engine()
        cmd_show_schema(engine)
        output = capsys.readouterr().out
        assert "msg_uid" in output
        assert "ts" in output
        assert "modality" in output

    def test_main_show_schema(self, capsys):
        """通过 main() 调用 --show-schema"""
        with patch("scripts.workspace.run_ingest._build_registry") as mock_reg:
            registry = AdapterRegistry()
            registry.register(_MockAdapter())
            mock_reg.return_value = registry
            ret = main(["--show-schema"])
            assert ret == 0
            output = capsys.readouterr().out
            assert "msg_uid" in output


# ── --show-adapters 测试 ──────────────────────────────────────────────


class TestShowAdapters:
    def test_show_adapters_list_all(self, capsys):
        _, engine = _make_engine()
        ret = cmd_show_adapters(engine, source_type=None)
        assert ret == 0
        output = capsys.readouterr().out
        assert "mock_test" in output

    def test_show_adapters_specific(self, capsys):
        _, engine = _make_engine()
        ret = cmd_show_adapters(engine, source_type="mock_test")
        assert ret == 0
        output = capsys.readouterr().out
        assert "测试用 mock 适配器" in output

    def test_show_adapters_unknown_type(self):
        _, engine = _make_engine()
        ret = cmd_show_adapters(engine, source_type="nonexistent")
        assert ret == 1

    def test_main_show_adapters(self, capsys):
        with patch("scripts.workspace.run_ingest._build_registry") as mock_reg:
            registry = AdapterRegistry()
            registry.register(_MockAdapter())
            mock_reg.return_value = registry
            ret = main(["--show-adapters"])
            assert ret == 0
            output = capsys.readouterr().out
            assert "mock_test" in output

    def test_main_show_adapters_with_source_type(self, capsys):
        with patch("scripts.workspace.run_ingest._build_registry") as mock_reg:
            registry = AdapterRegistry()
            registry.register(_MockAdapter())
            mock_reg.return_value = registry
            ret = main(["--show-adapters", "--source-type", "mock_test"])
            assert ret == 0
            output = capsys.readouterr().out
            assert "测试用 mock 适配器" in output


# ── --init-manifest 测试 ──────────────────────────────────────────────


class TestInitManifest:
    def test_init_manifest_creates_file(self, tmp_path: Path):
        _, engine = _make_engine()
        ret = cmd_init_manifest(engine, "mock_test", "test_ws")
        # 这里 workspace_root 会指向 <WORKSPACES_DIR>/test_ws，
        # 但我们可以通过 mock _resolve_workspace_root 来测试
        # 先测试参数校验

    def test_init_manifest_missing_source_type(self):
        _, engine = _make_engine()
        ret = cmd_init_manifest(engine, None, "test_ws")
        assert ret == 1

    def test_init_manifest_missing_workspace(self):
        _, engine = _make_engine()
        ret = cmd_init_manifest(engine, "mock_test", None)
        assert ret == 1

    def test_init_manifest_success(self, tmp_path: Path):
        _, engine = _make_engine()
        with patch(
            "scripts.workspace.run_ingest._resolve_workspace_root",
            return_value=tmp_path,
        ):
            ret = cmd_init_manifest(engine, "mock_test", "test_ws")
            assert ret == 0
            manifest_path = tmp_path / "raw" / "source_manifest.yaml"
            assert manifest_path.exists()
            content = manifest_path.read_text(encoding="utf-8")
            assert "source_type: mock_test" in content

    def test_init_manifest_unknown_type(self, tmp_path: Path):
        _, engine = _make_engine()
        with patch(
            "scripts.workspace.run_ingest._resolve_workspace_root",
            return_value=tmp_path,
        ):
            ret = cmd_init_manifest(engine, "nonexistent", "test_ws")
            assert ret == 1

    def test_main_init_manifest(self, tmp_path: Path):
        with patch("scripts.workspace.run_ingest._build_registry") as mock_reg:
            registry = AdapterRegistry()
            registry.register(_MockAdapter())
            mock_reg.return_value = registry
            with patch(
                "scripts.workspace.run_ingest._resolve_workspace_root",
                return_value=tmp_path,
            ):
                ret = main(["--init-manifest", "--source-type", "mock_test", "--workspace", "ws"])
                assert ret == 0


# ── --dry-run 测试 ────────────────────────────────────────────────────


class TestDryRun:
    def test_dry_run_no_manifest(self, tmp_path: Path):
        _, engine = _make_engine()
        with patch(
            "scripts.workspace.run_ingest._resolve_workspace_root",
            return_value=tmp_path,
        ):
            ret = cmd_dry_run(engine, "test_ws")
            assert ret == 1

    def test_dry_run_success(self, tmp_path: Path, capsys):
        records = [_valid_record(msg_uid=f"T:{i}") for i in range(5)]
        _, engine = _make_engine(records)
        _write_manifest(tmp_path)
        with patch(
            "scripts.workspace.run_ingest._resolve_workspace_root",
            return_value=tmp_path,
        ):
            ret = cmd_dry_run(engine, "test_ws")
            assert ret == 0
            output = capsys.readouterr().out
            assert "预检报告" in output
            assert "PASS" in output or "所有必填字段已覆盖" in output

    def test_dry_run_invalid_source_type(self, tmp_path: Path):
        _, engine = _make_engine()
        _write_manifest(tmp_path, source_type="nonexistent")
        with patch(
            "scripts.workspace.run_ingest._resolve_workspace_root",
            return_value=tmp_path,
        ):
            ret = cmd_dry_run(engine, "test_ws")
            assert ret == 1

    def test_main_dry_run(self, tmp_path: Path, capsys):
        records = [_valid_record()]
        with patch("scripts.workspace.run_ingest._build_registry") as mock_reg:
            registry = AdapterRegistry()
            registry.register(_MockAdapter(records))
            mock_reg.return_value = registry
            _write_manifest(tmp_path)
            with patch(
                "scripts.workspace.run_ingest._resolve_workspace_root",
                return_value=tmp_path,
            ):
                ret = main(["--workspace", "ws", "--dry-run"])
                assert ret == 0


# ── 默认运行模式测试 ──────────────────────────────────────────────────


class TestRunMode:
    def test_run_no_manifest_no_detect(self, tmp_path: Path):
        """无 manifest 且无法自动检测 → 错误"""
        _, engine = _make_engine()
        with patch(
            "scripts.workspace.run_ingest._resolve_workspace_root",
            return_value=tmp_path,
        ):
            ret = cmd_run(engine, "test_ws")
            assert ret == 1

    def test_run_success(self, tmp_path: Path, capsys):
        records = [
            _valid_record(msg_uid="T:1", ts=1700000001),
            _valid_record(msg_uid="T:2", ts=1700000002, speaker="OTHER"),
        ]
        _, engine = _make_engine(records)
        _write_manifest(tmp_path)
        with patch(
            "scripts.workspace.run_ingest._resolve_workspace_root",
            return_value=tmp_path,
        ):
            ret = cmd_run(engine, "test_ws")
            assert ret == 0
            output = capsys.readouterr().out
            assert "归一化转换完成" in output
            assert "总消息数" in output

    def test_run_writes_jsonl(self, tmp_path: Path):
        records = [_valid_record(msg_uid="T:1", ts=1700000001)]
        _, engine = _make_engine(records)
        _write_manifest(tmp_path)
        with patch(
            "scripts.workspace.run_ingest._resolve_workspace_root",
            return_value=tmp_path,
        ):
            cmd_run(engine, "test_ws")
            jsonl_path = tmp_path / "raw" / "P1_messages_raw.jsonl"
            assert jsonl_path.exists()
            lines = jsonl_path.read_text(encoding="utf-8").strip().split("\n")
            assert len(lines) == 1
            rec = json.loads(lines[0])
            assert rec["msg_uid"] == "T:1"

    def test_run_invalid_manifest_source_type(self, tmp_path: Path):
        _, engine = _make_engine()
        _write_manifest(tmp_path, source_type="nonexistent")
        with patch(
            "scripts.workspace.run_ingest._resolve_workspace_root",
            return_value=tmp_path,
        ):
            ret = cmd_run(engine, "test_ws")
            assert ret == 1


# ── 参数校验测试 ──────────────────────────────────────────────────────


class TestArgValidation:
    def test_no_workspace_no_info_command(self):
        """无 --workspace 且无信息查询命令 → 错误"""
        with patch("scripts.workspace.run_ingest._build_registry") as mock_reg:
            registry = AdapterRegistry()
            registry.register(_MockAdapter())
            mock_reg.return_value = registry
            ret = main([])
            assert ret == 1

    def test_parser_structure(self):
        """验证 parser 包含所有预期参数"""
        parser = build_parser()
        # 解析一组完整参数确保不报错
        args = parser.parse_args(["--workspace", "ws", "--dry-run"])
        assert args.workspace == "ws"
        assert args.dry_run is True

        args = parser.parse_args(["--show-schema"])
        assert args.show_schema is True

        args = parser.parse_args(["--show-adapters", "--source-type", "tg"])
        assert args.show_adapters is True
        assert args.source_type == "tg"

        args = parser.parse_args(["--init-manifest", "--source-type", "tg", "--workspace", "ws"])
        assert args.init_manifest is True


# ── 报告格式化测试 ────────────────────────────────────────────────────


class TestReportFormatting:
    def test_print_ingestion_report(self, capsys):
        from scripts.workspace.ingestion.engine import IngestionReport

        report = IngestionReport(
            total_messages=100,
            by_modality={"text": 80, "image": 20},
            by_speaker={"ME": 60, "OTHER": 40},
            date_range=("2024-01-01", "2024-12-31"),
            media_files_copied=15,
            media_files_skipped=5,
            records_skipped=3,
            skip_reasons={"缺少必填字段: msg_uid": 3},
        )
        _print_ingestion_report(report)
        output = capsys.readouterr().out
        assert "100" in output
        assert "text" in output
        assert "image" in output
        assert "2024-01-01" in output

    def test_print_dry_run_report(self, capsys):
        from scripts.workspace.ingestion.engine import DryRunReport

        report = DryRunReport(
            estimated_total=50,
            sampled_count=50,
            required_field_coverage={"msg_uid": 1.0, "ts": 0.9},
            optional_field_coverage={"media_path": 0.3},
            unmapped_source_fields={"extra": "value"},
            conclusion="WARN",
            warnings=["必填字段 'ts' 覆盖率: 90.0%"],
        )
        _print_dry_run_report(report)
        output = capsys.readouterr().out
        assert "预检报告" in output
        assert "msg_uid" in output
        assert "WARN" in output or "覆盖率不足" in output
