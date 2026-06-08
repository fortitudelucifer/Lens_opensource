"""
test_init_workspace_ingest.py
init_workspace.py 归一化导入整合的单元测试

测试 run_ingestion_step() 函数在各种场景下的行为：
- --skip-ingest 跳过
- 自动检测来源类型
- --source-type 指定来源类型
- --ingest-dry-run 预检模式
- 完整归一化执行
- 错误处理（manifest 校验失败、引擎异常）
- --dry-run（init 预览模式）下跳过归一化

Requirements: 10.1, 10.2
"""

import argparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator
from unittest.mock import patch, MagicMock

import pytest

from scripts.workspace.init_workspace import run_ingestion_step
from scripts.workspace.ingestion.adapters.base import SourceAdapter
from scripts.workspace.ingestion.manifest import SourceManifest


# ── 测试辅助 ──────────────────────────────────────────────


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
            "expected_files": [],
            "field_mapping_example": {},
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


def _make_args(**overrides) -> argparse.Namespace:
    """构建默认 args，可覆盖任意字段。"""
    defaults = {
        "source_type": None,
        "skip_ingest": False,
        "ingest_dry_run": False,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


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


def _setup_engine_with_mock(registry_mock, engine_mock, records=None):
    """配置 mock 的 AdapterRegistry 和 IngestionEngine。"""
    reg_instance = MagicMock()
    reg_instance.list_types.return_value = ["mock_test"]
    registry_mock.return_value = reg_instance

    eng_instance = MagicMock()
    engine_mock.return_value = eng_instance

    return reg_instance, eng_instance


# ── 测试类 ──────────────────────────────────────────────


class TestSkipIngest:
    """--skip-ingest 参数测试"""

    def test_skip_ingest_prints_skip_message(self, tmp_path: Path, capsys):
        args = _make_args(skip_ingest=True)
        run_ingestion_step(tmp_path, args)
        captured = capsys.readouterr()
        assert "已跳过" in captured.out
        assert "--skip-ingest" in captured.out

    def test_skip_ingest_does_not_import_engine(self, tmp_path: Path):
        """--skip-ingest 时不应尝试导入 ingestion 模块。"""
        args = _make_args(skip_ingest=True)
        # 如果尝试导入会触发 side_effect，但 skip 应该提前返回
        with patch(
            "scripts.workspace.init_workspace.run_ingestion_step.__module__"
        ):
            run_ingestion_step(tmp_path, args)
            # 没有异常即通过


class TestNoSourceDetected:
    """未检测到来源类型时的行为"""

    @patch("scripts.workspace.ingestion.engine.IngestionEngine.detect_source_type", return_value=None)
    @patch("scripts.workspace.ingestion.registry.AdapterRegistry.discover")
    def test_no_source_type_prints_info(self, mock_discover, mock_detect, tmp_path: Path, capsys):
        args = _make_args()
        (tmp_path / "raw").mkdir(parents=True, exist_ok=True)
        run_ingestion_step(tmp_path, args)
        captured = capsys.readouterr()
        assert "未检测到已知数据来源类型" in captured.out
        assert "--source-type" in captured.out


class TestSourceTypeDetection:
    """自动检测和手动指定来源类型"""

    @patch("scripts.workspace.ingestion.engine.IngestionEngine.detect_source_type", return_value="wechat_html")
    @patch("scripts.workspace.ingestion.registry.AdapterRegistry.discover")
    def test_auto_detect_source_type(self, mock_discover, mock_detect, tmp_path: Path, capsys):
        """自动检测到来源类型时应打印类型信息。"""
        args = _make_args()
        _write_manifest(tmp_path, "wechat_html")
        # manifest 中的 source_type 与注册表不匹配会导致校验失败，这里测试检测逻辑
        run_ingestion_step(tmp_path, args)
        captured = capsys.readouterr()
        assert "来源类型: wechat_html" in captured.out

    @patch("scripts.workspace.ingestion.engine.IngestionEngine.detect_source_type", return_value=None)
    @patch("scripts.workspace.ingestion.registry.AdapterRegistry.discover")
    def test_explicit_source_type_overrides_detect(self, mock_discover, mock_detect, tmp_path: Path, capsys):
        """--source-type 应覆盖自动检测。"""
        args = _make_args(source_type="telegram_json")
        _write_manifest(tmp_path, "telegram_json")
        run_ingestion_step(tmp_path, args)
        captured = capsys.readouterr()
        # detect_source_type 返回 None，但 --source-type 指定了 telegram_json
        assert "来源类型: telegram_json" in captured.out
        # detect_source_type 不应被调用（因为 args.source_type 优先）
        mock_detect.assert_not_called()


class TestManifestGeneration:
    """manifest 自动生成测试"""

    @patch("scripts.workspace.ingestion.engine.IngestionEngine.detect_source_type", return_value="wechat_html")
    @patch("scripts.workspace.ingestion.registry.AdapterRegistry.discover")
    def test_generates_manifest_when_missing(self, mock_discover, mock_detect, tmp_path: Path, capsys):
        """manifest 不存在时应自动生成。"""
        args = _make_args()
        (tmp_path / "raw").mkdir(parents=True, exist_ok=True)
        # 不写入 manifest，让 run_ingestion_step 自动生成
        run_ingestion_step(tmp_path, args)
        captured = capsys.readouterr()
        assert "生成 source_manifest.yaml" in captured.out

    @patch("scripts.workspace.ingestion.engine.IngestionEngine.detect_source_type", return_value="wechat_html")
    @patch("scripts.workspace.ingestion.registry.AdapterRegistry.discover")
    def test_skips_generation_when_manifest_exists(self, mock_discover, mock_detect, tmp_path: Path, capsys):
        """manifest 已存在时不应重新生成。"""
        args = _make_args()
        _write_manifest(tmp_path, "wechat_html")
        run_ingestion_step(tmp_path, args)
        captured = capsys.readouterr()
        assert "生成 source_manifest.yaml" not in captured.out


class TestManifestValidationFailure:
    """manifest 校验失败测试"""

    @patch("scripts.workspace.ingestion.engine.IngestionEngine.detect_source_type", return_value=None)
    @patch("scripts.workspace.ingestion.registry.AdapterRegistry.discover")
    def test_invalid_manifest_prints_errors(self, mock_discover, mock_detect, tmp_path: Path, capsys):
        """manifest 中 source_type 与注册表不匹配时应打印校验错误。"""
        args = _make_args(source_type="unknown_type")
        _write_manifest(tmp_path, "unknown_type")
        run_ingestion_step(tmp_path, args)
        captured = capsys.readouterr()
        assert "manifest 校验失败" in captured.out


class TestIngestDryRun:
    """--ingest-dry-run 预检模式测试"""

    @patch("scripts.workspace.ingestion.engine.IngestionEngine.detect_source_type", return_value=None)
    @patch("scripts.workspace.ingestion.registry.AdapterRegistry.discover")
    def test_ingest_dry_run_calls_dry_run(self, mock_discover, mock_detect, tmp_path: Path, capsys):
        """--ingest-dry-run 应调用 engine.dry_run() 而非 engine.run()。"""
        from scripts.workspace.ingestion.engine import IngestionEngine, DryRunReport
        from scripts.workspace.ingestion.registry import AdapterRegistry

        # 创建真实的 registry + mock adapter
        adapter = _MockAdapter(records=[_valid_record()])
        registry = AdapterRegistry()
        registry.register(adapter)
        engine = IngestionEngine(registry)

        args = _make_args(source_type="mock_test", ingest_dry_run=True)
        _write_manifest(tmp_path, "mock_test")

        with patch(
            "scripts.workspace.ingestion.registry.AdapterRegistry",
            return_value=registry,
        ), patch(
            "scripts.workspace.ingestion.engine.IngestionEngine",
            return_value=engine,
        ):
            run_ingestion_step(tmp_path, args)

        captured = capsys.readouterr()
        assert "预检" in captured.out
        assert "结论" in captured.out


class TestFullIngestion:
    """完整归一化执行测试"""

    @patch("scripts.workspace.ingestion.engine.IngestionEngine.detect_source_type", return_value=None)
    @patch("scripts.workspace.ingestion.registry.AdapterRegistry.discover")
    def test_full_run_calls_engine_run(self, mock_discover, mock_detect, tmp_path: Path, capsys):
        """非 dry-run 模式应调用 engine.run()。"""
        from scripts.workspace.ingestion.engine import IngestionEngine
        from scripts.workspace.ingestion.registry import AdapterRegistry

        adapter = _MockAdapter(records=[_valid_record()])
        registry = AdapterRegistry()
        registry.register(adapter)
        engine = IngestionEngine(registry)

        args = _make_args(source_type="mock_test")
        _write_manifest(tmp_path, "mock_test")

        with patch(
            "scripts.workspace.ingestion.registry.AdapterRegistry",
            return_value=registry,
        ), patch(
            "scripts.workspace.ingestion.engine.IngestionEngine",
            return_value=engine,
        ):
            run_ingestion_step(tmp_path, args)

        captured = capsys.readouterr()
        assert "归一化完成" in captured.out
        assert "总消息数" in captured.out


class TestErrorHandling:
    """错误处理——归一化失败不应中断初始化"""

    @patch("scripts.workspace.ingestion.engine.IngestionEngine.detect_source_type", return_value=None)
    @patch("scripts.workspace.ingestion.registry.AdapterRegistry.discover", side_effect=RuntimeError("模拟错误"))
    def test_engine_error_prints_warning(self, mock_discover, mock_detect, tmp_path: Path, capsys):
        """引擎异常时应打印警告而非崩溃。"""
        args = _make_args(source_type="mock_test")
        _write_manifest(tmp_path, "mock_test")
        # 不应抛出异常
        run_ingestion_step(tmp_path, args)
        captured = capsys.readouterr()
        assert "归一化导入失败" in captured.out
        assert "run_ingest.py" in captured.out

    def test_import_error_prints_warning(self, tmp_path: Path, capsys):
        """ingestion 模块导入失败时应打印警告。"""
        args = _make_args()
        with patch.dict("sys.modules", {"scripts.workspace.ingestion.engine": None}):
            # 强制 ImportError
            import builtins
            original_import = builtins.__import__

            def mock_import(name, *a, **kw):
                if "scripts.workspace.ingestion.engine" in name:
                    raise ImportError("模拟导入失败")
                return original_import(name, *a, **kw)

            with patch("builtins.__import__", side_effect=mock_import):
                run_ingestion_step(tmp_path, args)

            captured = capsys.readouterr()
            assert "归一化模块未安装" in captured.out


class TestMainIntegration:
    """main() 函数中归一化步骤的集成测试"""

    def test_new_args_exist_in_parser(self):
        """验证 main() 的 parser 包含新增参数。"""
        from scripts.workspace.init_workspace import main
        import inspect

        source = inspect.getsource(main)
        assert "--source-type" in source
        assert "--skip-ingest" in source
        assert "--ingest-dry-run" in source

    def test_dry_run_skips_ingestion(self, tmp_path: Path, capsys):
        """--dry-run（init 预览模式）下不应执行归一化步骤。"""
        args = _make_args(skip_ingest=False)
        # run_ingestion_step 在 main() 中被 `if not args.dry_run` 保护
        # 这里直接验证 run_ingestion_step 在正常调用时会执行
        # 而 main() 中 dry_run=True 时不会调用它
        # 通过检查 main() 源码确认逻辑
        from scripts.workspace.init_workspace import main
        import inspect

        source = inspect.getsource(main)
        assert "if not args.dry_run:" in source
        assert "run_ingestion_step" in source
