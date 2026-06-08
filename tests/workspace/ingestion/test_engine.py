"""
test_engine.py
IngestionEngine 单元测试

覆盖：
- run() 主流程（解析 → 验证 → 排序 → 写入 JSONL → 导出）
- dry_run() 预检模式
- show_schema() / show_adapters() / init_manifest() 信息查询
- detect_source_type() 自动检测
- 无效记录跳过 + 原因汇总

运行方式：
    conda run -n wechatDHA python -m pytest tests/workspace/ingestion/test_engine.py -x -v
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

import pytest

from scripts.workspace.ingestion.adapters.base import SourceAdapter
from scripts.workspace.ingestion.engine import (
    DryRunReport,
    IngestionEngine,
    IngestionReport,
)
from scripts.workspace.ingestion.manifest import SourceManifest
from scripts.workspace.ingestion.registry import AdapterRegistry
from scripts.workspace.ingestion.schema import REQUIRED_FIELDS, VALID_MODALITIES, validate_message


# ── Mock 适配器 ───────────────────────────────────────────────────────


class MockAdapter(SourceAdapter):
    """测试用 mock 适配器，返回预定义的消息记录"""

    def __init__(self, records: list[dict] | None = None):
        self._records = records or []

    def supported_source_type(self) -> str:
        return "mock_test"

    def parse(self, input_path: Path, manifest: SourceManifest) -> Iterator[dict]:
        yield from self._records

    def validate_input(self, input_path: Path) -> list[str]:
        # 不做真实文件检查
        return []

    def describe(self) -> dict:
        return {
            "source_type": "mock_test",
            "description": "测试用 mock 适配器",
            "expected_files": ["test.json"],
            "field_mapping_example": {"src": "dst"},
        }


def _make_valid_record(
    msg_uid: str = "T:1",
    ts: int = 1700000000,
    speaker: str = "ME",
    type_: int = 1,
    modality: str = "text",
    text_raw: str = "hello",
    **kwargs,
) -> dict:
    """生成一条合法的消息记录"""
    rec = {
        "msg_uid": msg_uid,
        "ts": ts,
        "speaker": speaker,
        "type": type_,
        "modality": modality,
        "text_raw": text_raw,
    }
    rec.update(kwargs)
    return rec


def _make_registry(records: list[dict] | None = None) -> AdapterRegistry:
    """创建包含 MockAdapter 的注册表"""
    registry = AdapterRegistry()
    registry.register(MockAdapter(records))
    return registry


def _make_manifest(**overrides) -> SourceManifest:
    """创建测试用 manifest"""
    defaults = {
        "source_type": "mock_test",
        "input_paths": ["./test_input"],
    }
    defaults.update(overrides)
    return SourceManifest(**defaults)


# ── run() 测试 ────────────────────────────────────────────────────────


class TestEngineRun:
    """测试 run() 主流程"""

    def test_run_basic(self, tmp_path: Path):
        """基本流程：解析 → 验证 → 排序 → 写入 JSONL"""
        records = [
            _make_valid_record(msg_uid="T:2", ts=1700000002, text_raw="second"),
            _make_valid_record(msg_uid="T:1", ts=1700000001, text_raw="first"),
        ]
        registry = _make_registry(records)
        engine = IngestionEngine(registry)
        manifest = _make_manifest()

        report = engine.run(manifest, tmp_path)

        assert isinstance(report, IngestionReport)
        assert report.total_messages == 2
        assert report.records_skipped == 0

        # 验证 JSONL 文件存在且按 ts 排序
        jsonl_path = tmp_path / "raw" / "P1_messages_raw.jsonl"
        assert jsonl_path.exists()
        lines = jsonl_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2
        first = json.loads(lines[0])
        second = json.loads(lines[1])
        assert first["ts"] <= second["ts"]

    def test_run_sorts_by_ts(self, tmp_path: Path):
        """验证输出按 ts 升序排列"""
        records = [
            _make_valid_record(msg_uid="T:3", ts=1700000003),
            _make_valid_record(msg_uid="T:1", ts=1700000001),
            _make_valid_record(msg_uid="T:2", ts=1700000002),
        ]
        registry = _make_registry(records)
        engine = IngestionEngine(registry)

        report = engine.run(_make_manifest(), tmp_path)

        jsonl_path = tmp_path / "raw" / "P1_messages_raw.jsonl"
        lines = jsonl_path.read_text(encoding="utf-8").strip().split("\n")
        timestamps = [json.loads(line)["ts"] for line in lines]
        assert timestamps == sorted(timestamps)

    def test_run_skips_invalid_records(self, tmp_path: Path):
        """无效记录被跳过，有效记录正常写入"""
        records = [
            _make_valid_record(msg_uid="T:1", ts=1700000001),
            {"msg_uid": "T:2", "ts": -1, "speaker": "ME", "type": 1,
             "modality": "text", "text_raw": "bad ts"},  # ts 无效
            {"speaker": "ME", "type": 1, "modality": "text",
             "text_raw": "missing uid"},  # 缺少 msg_uid
            _make_valid_record(msg_uid="T:4", ts=1700000004),
        ]
        registry = _make_registry(records)
        engine = IngestionEngine(registry)

        report = engine.run(_make_manifest(), tmp_path)

        assert report.total_messages == 2
        assert report.records_skipped == 2
        assert len(report.skip_reasons) > 0

    def test_run_generates_export_files(self, tmp_path: Path):
        """验证生成 CSV/HTML/MD 导出文件"""
        records = [_make_valid_record()]
        registry = _make_registry(records)
        engine = IngestionEngine(registry)
        manifest = _make_manifest(workspace_name="test_ws")

        engine.run(manifest, tmp_path)

        export_dir = tmp_path / "raw" / "export"
        assert (export_dir / "test_ws.csv").exists()
        assert (export_dir / "test_ws.html").exists()
        assert (export_dir / "test_ws.md").exists()

    def test_run_report_statistics(self, tmp_path: Path):
        """验证报告中的统计数据"""
        records = [
            _make_valid_record(msg_uid="T:1", ts=1700000001, speaker="ME", modality="text"),
            _make_valid_record(msg_uid="T:2", ts=1700000002, speaker="OTHER", modality="image"),
            _make_valid_record(msg_uid="T:3", ts=1700000003, speaker="ME", modality="text"),
        ]
        registry = _make_registry(records)
        engine = IngestionEngine(registry)

        report = engine.run(_make_manifest(), tmp_path)

        assert report.total_messages == 3
        assert report.by_modality["text"] == 2
        assert report.by_modality["image"] == 1
        assert report.by_speaker["ME"] == 2
        assert report.by_speaker["OTHER"] == 1
        assert report.date_range[0] != ""
        assert report.date_range[1] != ""

    def test_run_validate_input_failure(self, tmp_path: Path):
        """validate_input 返回错误时应抛出 ValueError"""

        class FailAdapter(MockAdapter):
            def validate_input(self, input_path: Path) -> list[str]:
                return ["文件不存在: test"]

        registry = AdapterRegistry()
        registry.register(FailAdapter())
        engine = IngestionEngine(registry)

        with pytest.raises(ValueError, match="输入校验失败"):
            engine.run(_make_manifest(), tmp_path)

    def test_run_empty_records(self, tmp_path: Path):
        """空记录列表应正常处理"""
        registry = _make_registry([])
        engine = IngestionEngine(registry)

        report = engine.run(_make_manifest(), tmp_path)

        assert report.total_messages == 0
        jsonl_path = tmp_path / "raw" / "P1_messages_raw.jsonl"
        assert jsonl_path.exists()
        assert jsonl_path.read_text(encoding="utf-8").strip() == ""

    def test_run_chinese_content(self, tmp_path: Path):
        """中文内容正确写入 JSONL"""
        records = [_make_valid_record(text_raw="你好世界🌍")]
        registry = _make_registry(records)
        engine = IngestionEngine(registry)

        engine.run(_make_manifest(), tmp_path)

        jsonl_path = tmp_path / "raw" / "P1_messages_raw.jsonl"
        content = jsonl_path.read_text(encoding="utf-8")
        assert "你好世界🌍" in content


# ── dry_run() 测试 ────────────────────────────────────────────────────


class TestEngineDryRun:
    """测试 dry_run() 预检模式"""

    def test_dry_run_pass(self):
        """所有必填字段覆盖率 100% → PASS"""
        records = [
            _make_valid_record(msg_uid="T:1"),
            _make_valid_record(msg_uid="T:2"),
        ]
        registry = _make_registry(records)
        engine = IngestionEngine(registry)

        report = engine.dry_run(_make_manifest())

        assert isinstance(report, DryRunReport)
        assert report.conclusion == "PASS"
        assert report.sampled_count == 2
        for fname in REQUIRED_FIELDS:
            assert report.required_field_coverage[fname] == 1.0

    def test_dry_run_warn(self):
        """部分必填字段覆盖率 < 100% → WARN"""
        records = [
            _make_valid_record(msg_uid="T:1"),
            {"msg_uid": "T:2", "ts": 1700000002, "speaker": "ME",
             "type": 1, "modality": "text", "text_raw": ""},  # text_raw 为空
        ]
        registry = _make_registry(records)
        engine = IngestionEngine(registry)

        report = engine.dry_run(_make_manifest())

        assert report.conclusion == "WARN"
        assert report.required_field_coverage["text_raw"] < 1.0

    def test_dry_run_fail(self):
        """关键必填字段完全缺失 → FAIL"""
        records = [
            {"ts": 1700000001, "speaker": "ME", "type": 1,
             "modality": "text", "text_raw": "no uid"},  # 缺少 msg_uid
        ]
        registry = _make_registry(records)
        engine = IngestionEngine(registry)

        report = engine.dry_run(_make_manifest())

        assert report.conclusion == "FAIL"
        assert report.required_field_coverage["msg_uid"] == 0.0

    def test_dry_run_empty(self):
        """空数据 → FAIL"""
        registry = _make_registry([])
        engine = IngestionEngine(registry)

        report = engine.dry_run(_make_manifest())

        assert report.conclusion == "FAIL"
        assert report.sampled_count == 0

    def test_dry_run_sample_size(self):
        """sample_size 限制采样数量"""
        records = [_make_valid_record(msg_uid=f"T:{i}") for i in range(200)]
        registry = _make_registry(records)
        engine = IngestionEngine(registry)

        report = engine.dry_run(_make_manifest(), sample_size=50)

        assert report.sampled_count == 50

    def test_dry_run_unmapped_fields(self):
        """识别未映射的源字段"""
        records = [
            {**_make_valid_record(), "extra_field": "extra_value"},
        ]
        registry = _make_registry(records)
        engine = IngestionEngine(registry)

        report = engine.dry_run(_make_manifest())

        assert "extra_field" in report.unmapped_source_fields

    def test_dry_run_optional_coverage(self):
        """可选字段覆盖率计算"""
        records = [
            _make_valid_record(media_path="image/test.jpg"),
            _make_valid_record(),
        ]
        registry = _make_registry(records)
        engine = IngestionEngine(registry)

        report = engine.dry_run(_make_manifest())

        assert "media_path" in report.optional_field_coverage
        assert report.optional_field_coverage["media_path"] == 0.5


# ── show_schema() 测试 ────────────────────────────────────────────────


class TestShowSchema:
    """测试 show_schema()"""

    def test_show_schema_contains_all_fields(self):
        """输出包含所有 CanonicalMessage 字段"""
        registry = _make_registry()
        engine = IngestionEngine(registry)

        output = engine.show_schema()

        assert "msg_uid" in output
        assert "ts" in output
        assert "speaker" in output
        assert "modality" in output
        assert "text_raw" in output
        assert "media_path" in output

    def test_show_schema_marks_required(self):
        """必填字段标记为 ✅"""
        registry = _make_registry()
        engine = IngestionEngine(registry)

        output = engine.show_schema()

        assert "✅" in output
        assert "❌" in output


# ── show_adapters() 测试 ──────────────────────────────────────────────


class TestShowAdapters:
    """测试 show_adapters()"""

    def test_show_adapters_list_all(self):
        """列出所有已注册适配器"""
        registry = _make_registry()
        engine = IngestionEngine(registry)

        output = engine.show_adapters()

        assert "mock_test" in output

    def test_show_adapters_specific(self):
        """查看特定适配器详情"""
        registry = _make_registry()
        engine = IngestionEngine(registry)

        output = engine.show_adapters(source_type="mock_test")

        assert "mock_test" in output
        assert "测试用 mock 适配器" in output

    def test_show_adapters_unknown_type(self):
        """未知 source_type 抛出 KeyError"""
        registry = _make_registry()
        engine = IngestionEngine(registry)

        with pytest.raises(KeyError):
            engine.show_adapters(source_type="nonexistent")


# ── init_manifest() 测试 ──────────────────────────────────────────────


class TestInitManifest:
    """测试 init_manifest()"""

    def test_init_manifest_creates_file(self, tmp_path: Path):
        """生成 source_manifest.yaml 文件"""
        registry = _make_registry()
        engine = IngestionEngine(registry)

        path = engine.init_manifest("mock_test", tmp_path)

        assert path.exists()
        assert path.name == "source_manifest.yaml"
        content = path.read_text(encoding="utf-8")
        assert "source_type: mock_test" in content

    def test_init_manifest_unknown_type(self, tmp_path: Path):
        """未知 source_type 抛出 KeyError"""
        registry = _make_registry()
        engine = IngestionEngine(registry)

        with pytest.raises(KeyError):
            engine.init_manifest("nonexistent", tmp_path)


# ── detect_source_type() 测试 ─────────────────────────────────────────


class TestDetectSourceType:
    """测试 detect_source_type()"""

    def test_detect_wechat(self, tmp_path: Path):
        """HTML + CSV → wechat_html"""
        (tmp_path / "export.html").write_text("<html></html>")
        (tmp_path / "data.csv").write_text("a,b,c")

        assert IngestionEngine.detect_source_type(tmp_path) == "wechat_html"

    def test_detect_telegram(self, tmp_path: Path):
        """result.json → telegram_json"""
        (tmp_path / "result.json").write_text("{}")

        assert IngestionEngine.detect_source_type(tmp_path) == "telegram_json"

    def test_detect_whatsapp(self, tmp_path: Path):
        """*.txt → whatsapp_txt"""
        (tmp_path / "chat.txt").write_text("1/1/25, 10:00 - User: Hi")

        assert IngestionEngine.detect_source_type(tmp_path) == "whatsapp_txt"

    def test_detect_none(self, tmp_path: Path):
        """无法识别 → None"""
        (tmp_path / "random.dat").write_text("data")

        assert IngestionEngine.detect_source_type(tmp_path) is None

    def test_detect_nonexistent_dir(self, tmp_path: Path):
        """目录不存在 → None"""
        assert IngestionEngine.detect_source_type(tmp_path / "nope") is None

    def test_detect_wechat_priority(self, tmp_path: Path):
        """HTML + CSV 优先于 .txt"""
        (tmp_path / "export.html").write_text("<html></html>")
        (tmp_path / "data.csv").write_text("a,b,c")
        (tmp_path / "notes.txt").write_text("some notes")

        assert IngestionEngine.detect_source_type(tmp_path) == "wechat_html"


# ── Property-Based Tests (hypothesis) ─────────────────────────────────

import tempfile
from hypothesis import given, settings, assume
from hypothesis import strategies as st


# ── 生成器策略 ────────────────────────────────────────────────────────

_modalities = sorted(VALID_MODALITIES)
_speakers = ["ME", "OTHER", "OTHER:张三", "OTHER:Alice"]


def _safe_text():
    """生成不含 NUL 字节的文本（CSV 写入兼容）"""
    return st.text(
        alphabet=st.characters(blacklist_categories=("Cs",), blacklist_characters="\x00"),
        min_size=0,
        max_size=50,
    )


def valid_record_strategy():
    """生成合法的消息记录"""
    return st.fixed_dictionaries({
        "msg_uid": st.from_regex(r"T:[1-9][0-9]{0,8}", fullmatch=True),
        "ts": st.integers(min_value=1, max_value=2_000_000_000),
        "speaker": st.sampled_from(_speakers),
        "type": st.integers(min_value=0, max_value=100),
        "modality": st.sampled_from(_modalities),
        "text_raw": _safe_text(),
    })


def invalid_record_strategy():
    """生成至少一个字段无效的消息记录（4 种缺陷之一）"""
    _safe_short = st.text(
        alphabet=st.characters(blacklist_categories=("Cs",), blacklist_characters="\x00"),
        min_size=1,
        max_size=20,
    )
    return st.one_of(
        # 缺少 msg_uid
        st.fixed_dictionaries({
            "ts": st.integers(min_value=1, max_value=2_000_000_000),
            "speaker": st.sampled_from(_speakers),
            "type": st.integers(min_value=0, max_value=100),
            "modality": st.sampled_from(_modalities),
            "text_raw": _safe_short,
        }),
        # ts <= 0
        st.fixed_dictionaries({
            "msg_uid": st.from_regex(r"T:[1-9][0-9]{0,4}", fullmatch=True),
            "ts": st.integers(min_value=-1_000_000, max_value=0),
            "speaker": st.sampled_from(_speakers),
            "type": st.integers(min_value=0, max_value=100),
            "modality": st.sampled_from(_modalities),
            "text_raw": _safe_short,
        }),
        # 无效 modality
        st.fixed_dictionaries({
            "msg_uid": st.from_regex(r"T:[1-9][0-9]{0,4}", fullmatch=True),
            "ts": st.integers(min_value=1, max_value=2_000_000_000),
            "speaker": st.sampled_from(_speakers),
            "type": st.integers(min_value=0, max_value=100),
            "modality": st.from_regex(r"INVALID_[a-z]{3}", fullmatch=True),
            "text_raw": _safe_short,
        }),
        # 无效 speaker
        st.fixed_dictionaries({
            "msg_uid": st.from_regex(r"T:[1-9][0-9]{0,4}", fullmatch=True),
            "ts": st.integers(min_value=1, max_value=2_000_000_000),
            "speaker": st.from_regex(r"BADSPK_[a-z]{3}", fullmatch=True),
            "type": st.integers(min_value=0, max_value=100),
            "modality": st.sampled_from(_modalities),
            "text_raw": _safe_short,
        }),
    )


# ── Property 13: 输出消息按时间戳排序 ─────────────────────────────────


class TestProperty13OutputSortedByTs:
    """Property 13: 输出消息按时间戳排序

    **Validates: Requirements 10.6**
    """

    @given(records=st.lists(valid_record_strategy(), min_size=1, max_size=30))
    @settings(max_examples=200)
    def test_output_sorted_by_ts(self, records: list[dict]):
        """Property 13: 经过 IngestionEngine.run() 处理后，输出 JSONL 中的消息
        按 ts 字段严格非递减排列。

        **Validates: Requirements 10.6**
        """
        # 确保 msg_uid 唯一
        for i, rec in enumerate(records):
            rec["msg_uid"] = f"T:{i + 1}"

        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            registry = _make_registry(records)
            engine = IngestionEngine(registry)
            manifest = _make_manifest()

            engine.run(manifest, workspace)

            jsonl_path = workspace / "raw" / "P1_messages_raw.jsonl"
            assert jsonl_path.exists()

            content = jsonl_path.read_text(encoding="utf-8").strip()
            if not content:
                return  # 空文件（所有记录被跳过）

            lines = content.split("\n")
            timestamps = [json.loads(line)["ts"] for line in lines]

            # 核心断言：ts 非递减
            for i in range(len(timestamps) - 1):
                assert timestamps[i] <= timestamps[i + 1], (
                    f"输出未按 ts 排序: ts[{i}]={timestamps[i]} > ts[{i+1}]={timestamps[i+1]}"
                )


# ── Property 14: 无效记录被跳过 ───────────────────────────────────────


class TestProperty14InvalidRecordsSkipped:
    """Property 14: 无效记录被跳过

    **Validates: Requirements 11.2, 11.3, 11.4**
    """

    @given(
        valid=st.lists(valid_record_strategy(), min_size=0, max_size=15),
        invalid=st.lists(invalid_record_strategy(), min_size=0, max_size=15),
    )
    @settings(max_examples=200)
    def test_invalid_records_skipped(
        self, valid: list[dict], invalid: list[dict]
    ):
        """Property 14: 包含合法和非法记录的混合列表经过引擎处理后，
        输出仅包含通过 validate_message 的记录，跳过计数等于非法记录数。

        **Validates: Requirements 11.2, 11.3, 11.4**
        """
        assume(len(valid) + len(invalid) > 0)

        # 确保 valid 记录的 msg_uid 唯一
        for i, rec in enumerate(valid):
            rec["msg_uid"] = f"V:{i + 1}"

        # 确保 invalid 记录确实无效
        truly_invalid = [r for r in invalid if validate_message(r)]
        truly_valid_from_invalid = [r for r in invalid if not validate_message(r)]

        # 把意外合法的 invalid 记录加入 valid 计数
        expected_valid_count = len(valid) + len(truly_valid_from_invalid)
        expected_skip_count = len(truly_invalid)

        mixed = valid + invalid

        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            registry = _make_registry(mixed)
            engine = IngestionEngine(registry)
            manifest = _make_manifest()

            report = engine.run(manifest, workspace)

            assert report.total_messages == expected_valid_count
            assert report.records_skipped == expected_skip_count

            # 验证输出中的每条记录都通过 validate_message
            jsonl_path = workspace / "raw" / "P1_messages_raw.jsonl"
            content = jsonl_path.read_text(encoding="utf-8").strip()
            if content:
                for line in content.split("\n"):
                    rec = json.loads(line)
                    errors = validate_message(rec)
                    assert errors == [], f"输出中包含无效记录: {errors}"


# ── Property 15: 预检覆盖率计算正确性 ─────────────────────────────────


class TestProperty15DryRunCoverage:
    """Property 15: 预检覆盖率计算正确性

    **Validates: Requirements 14.2, 14.3, 14.5**
    """

    @given(records=st.lists(
        st.fixed_dictionaries({
            "msg_uid": st.one_of(
                st.from_regex(r"T:[1-9][0-9]{0,4}", fullmatch=True),
                st.just(""),
                st.none(),
            ),
            "ts": st.one_of(
                st.integers(min_value=1, max_value=2_000_000_000),
                st.just(""),
                st.none(),
            ),
            "speaker": st.one_of(
                st.sampled_from(_speakers),
                st.just(""),
                st.none(),
            ),
            "type": st.one_of(
                st.integers(min_value=0, max_value=100),
                st.just(""),
                st.none(),
            ),
            "modality": st.one_of(
                st.sampled_from(_modalities),
                st.just(""),
                st.none(),
            ),
            "text_raw": st.one_of(
                st.text(
                    alphabet=st.characters(blacklist_categories=("Cs",), blacklist_characters="\x00"),
                    min_size=1,
                    max_size=20,
                ),
                st.just(""),
                st.none(),
            ),
        }),
        min_size=1,
        max_size=30,
    ))
    @settings(max_examples=200)
    def test_dry_run_coverage_calculation(self, records: list[dict]):
        """Property 15: 预检报告中每个必填字段的覆盖率等于
        该字段有非空值的记录数除以总记录数。
        当所有必填字段覆盖率为 100% 时结论为 PASS，否则为 WARN 或 FAIL。

        **Validates: Requirements 14.2, 14.3, 14.5**
        """
        total = len(records)

        # 手动计算期望覆盖率
        expected_coverage: dict[str, float] = {}
        for fname in REQUIRED_FIELDS:
            count = sum(
                1 for r in records
                if fname in r and r[fname] is not None and r[fname] != ""
            )
            expected_coverage[fname] = count / total

        registry = _make_registry(records)
        engine = IngestionEngine(registry)
        manifest = _make_manifest()

        report = engine.dry_run(manifest, sample_size=len(records))

        # 验证覆盖率计算
        for fname in REQUIRED_FIELDS:
            actual = report.required_field_coverage.get(fname, 0.0)
            assert abs(actual - expected_coverage[fname]) < 1e-9, (
                f"字段 '{fname}' 覆盖率不匹配: "
                f"期望 {expected_coverage[fname]:.4f}, 实际 {actual:.4f}"
            )

        # 验证结论逻辑
        all_full = all(v == 1.0 for v in expected_coverage.values())
        any_zero = any(v == 0.0 for v in expected_coverage.values())

        if all_full:
            assert report.conclusion == "PASS"
        elif any_zero:
            assert report.conclusion == "FAIL"
        else:
            assert report.conclusion == "WARN"
