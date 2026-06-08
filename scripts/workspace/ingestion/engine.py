"""
engine.py
归一化引擎主流程 —— 调度适配器、执行转换、输出标准格式

功能：
- run(): 完整转换流程（manifest → 校验 → 解析 → 验证 → 媒体组织 → 排序 → 写入 JSONL → 生成导出）
- dry_run(): 预检模式（扫描前 N 条记录生成覆盖率报告）
- show_schema(): 输出 Canonical Schema 字段说明表格
- show_adapters(): 列出适配器信息
- init_manifest(): 生成预填充的 source_manifest.yaml
- detect_source_type(): 自动检测 raw/ 目录下的数据来源类型

Requirements: 10.2, 10.3, 10.4, 10.5, 10.6, 11.1, 11.2, 11.3, 11.4, 11.5

运行方式：
    python -m pytest tests/workspace/ingestion/test_engine.py -v
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from tqdm import tqdm

from scripts.workspace.ingestion.export_generator import ExportGenerator
from scripts.workspace.ingestion.manifest import SourceManifest
from scripts.workspace.ingestion.media_organizer import MediaOrganizer
from scripts.workspace.ingestion.registry import AdapterRegistry
from scripts.workspace.ingestion.schema import (
    REQUIRED_FIELDS,
    VALID_MODALITIES,
    CanonicalMessage,
    to_jsonl_line,
    validate_message,
)

logger = logging.getLogger(__name__)


# ── 报告数据类 ────────────────────────────────────────────────────────


@dataclass
class IngestionReport:
    """转换统计报告"""

    total_messages: int = 0
    by_modality: dict[str, int] = field(default_factory=dict)
    by_speaker: dict[str, int] = field(default_factory=dict)
    date_range: tuple[str, str] = ("", "")  # (min_date, max_date)
    media_files_copied: int = 0
    media_files_skipped: int = 0
    records_skipped: int = 0
    skip_reasons: dict[str, int] = field(default_factory=dict)


@dataclass
class DryRunReport:
    """预检报告"""

    estimated_total: int = 0
    sampled_count: int = 0
    required_field_coverage: dict[str, float] = field(default_factory=dict)
    optional_field_coverage: dict[str, float] = field(default_factory=dict)
    unmapped_source_fields: dict[str, str] = field(default_factory=dict)
    conclusion: str = "PASS"  # "PASS" | "WARN" | "FAIL"
    warnings: list[str] = field(default_factory=list)


# ── 引擎主类 ──────────────────────────────────────────────────────────


class IngestionEngine:
    """归一化引擎主流程"""

    def __init__(self, registry: AdapterRegistry):
        self.registry = registry

    # ── run() 完整转换 ─────────────────────────────────────────────────

    def run(self, manifest: SourceManifest, workspace_root: Path) -> IngestionReport:
        """执行完整转换流程。

        1. 获取适配器
        2. 校验输入（validate_input）
        3. 解析消息（adapter.parse）+ tqdm
        4. Schema 验证（validate_message）—— 跳过无效记录
        5. 媒体文件组织（MediaOrganizer）+ tqdm
        6. 按 ts 排序
        7. 写入 P1_messages_raw.jsonl
        8. 生成 export/ 文件（CSV/HTML/MD）
        9. 返回 IngestionReport
        """
        adapter = self.registry.get(manifest.source_type)

        # ── 校验输入 ──
        all_errors: list[str] = []
        for input_path_str in manifest.input_paths:
            input_path = Path(input_path_str)
            errors = adapter.validate_input(input_path)
            all_errors.extend(errors)
        if all_errors:
            raise ValueError(
                "输入校验失败:\n" + "\n".join(f"  - {e}" for e in all_errors)
            )

        # ── 解析消息 ──
        raw_records: list[dict] = []
        for input_path_str in manifest.input_paths:
            input_path = Path(input_path_str)
            for rec in tqdm(
                adapter.parse(input_path, manifest),
                desc=f"解析 {input_path.name}",
                unit="msg",
            ):
                raw_records.append(rec)

        # ── Schema 验证 ──
        valid_records: list[dict] = []
        skip_reasons: dict[str, int] = {}
        records_skipped = 0

        for rec in raw_records:
            errors = validate_message(rec)
            if errors:
                records_skipped += 1
                for err in errors:
                    skip_reasons[err] = skip_reasons.get(err, 0) + 1
                logger.warning("跳过无效记录: %s", "; ".join(errors))
            else:
                valid_records.append(rec)

        if records_skipped > 0:
            logger.info(
                "验证完成: 跳过 %d 条无效记录", records_skipped
            )
            for reason, count in sorted(skip_reasons.items()):
                logger.info("  - %s: %d 条", reason, count)

        # ── 媒体文件组织 ──
        raw_dir = workspace_root / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)

        media_base_dir = (
            Path(manifest.media_base_dir)
            if manifest.media_base_dir
            else (Path(manifest.input_paths[0]).parent if manifest.input_paths else raw_dir)
        )

        # 统计媒体复制前后的数量
        media_before = sum(
            1 for r in valid_records if r.get("media_path") is not None
        )

        organizer = MediaOrganizer()
        valid_records = organizer.organize(valid_records, media_base_dir, raw_dir)

        media_after = sum(
            1 for r in valid_records if r.get("media_path") is not None
        )
        media_files_copied = media_after
        media_files_skipped = media_before - media_after

        # ── 按 ts 排序 ──
        valid_records.sort(key=lambda r: r.get("ts", 0))

        # ── 写入 P1_messages_raw.jsonl ──
        jsonl_path = raw_dir / "P1_messages_raw.jsonl"
        with open(jsonl_path, "w", encoding="utf-8") as f:
            for rec in valid_records:
                f.write(to_jsonl_line(rec) + "\n")

        # ── 生成 export/ 文件 ──
        export_dir = raw_dir / "export"
        export_dir.mkdir(parents=True, exist_ok=True)

        ws_name = manifest.workspace_name or workspace_root.name
        exporter = ExportGenerator()
        exporter.generate_csv(valid_records, export_dir / f"{ws_name}.csv")
        exporter.generate_html(valid_records, export_dir / f"{ws_name}.html")
        exporter.generate_markdown(valid_records, export_dir / f"{ws_name}.md")

        # ── 构建报告 ──
        report = self._build_report(
            valid_records, records_skipped, skip_reasons,
            media_files_copied, media_files_skipped,
        )
        return report

    # ── dry_run() 预检模式 ─────────────────────────────────────────────

    def dry_run(self, manifest: SourceManifest, sample_size: int = 100) -> DryRunReport:
        """预检模式：扫描前 N 条记录生成覆盖率报告。

        1. 获取适配器，解析前 N 条记录
        2. 计算必填/可选字段覆盖率
        3. 识别未映射的源字段
        4. 判定结论：PASS / WARN / FAIL
        """
        adapter = self.registry.get(manifest.source_type)

        # 收集样本
        samples: list[dict] = []
        for input_path_str in manifest.input_paths:
            input_path = Path(input_path_str)
            for rec in adapter.parse(input_path, manifest):
                samples.append(rec)
                if len(samples) >= sample_size:
                    break
            if len(samples) >= sample_size:
                break

        sampled_count = len(samples)
        if sampled_count == 0:
            return DryRunReport(
                estimated_total=0,
                sampled_count=0,
                conclusion="FAIL",
                warnings=["未能解析到任何记录"],
            )

        # 计算字段覆盖率
        required_fields = set(REQUIRED_FIELDS)
        # 可选字段：CanonicalMessage 中非必填的字段
        all_canonical_fields = {f.name for f in CanonicalMessage.__dataclass_fields__.values()}
        optional_fields = all_canonical_fields - required_fields

        required_coverage: dict[str, float] = {}
        optional_coverage: dict[str, float] = {}

        for fname in required_fields:
            count = sum(
                1 for r in samples
                if fname in r and r[fname] is not None and r[fname] != ""
            )
            required_coverage[fname] = count / sampled_count

        for fname in sorted(optional_fields):
            count = sum(
                1 for r in samples
                if fname in r and r[fname] is not None and r[fname] != ""
            )
            if count > 0:
                optional_coverage[fname] = count / sampled_count

        # 识别未映射的源字段
        unmapped: dict[str, str] = {}
        for rec in samples:
            for key, val in rec.items():
                if key not in all_canonical_fields and key not in unmapped:
                    unmapped[key] = str(val)[:100] if val is not None else ""

        # 判定结论
        warnings: list[str] = []
        has_critical_missing = False

        for fname, cov in required_coverage.items():
            if cov < 1.0:
                warnings.append(
                    f"必填字段 '{fname}' 覆盖率: {cov:.1%}"
                )
                if cov == 0.0:
                    has_critical_missing = True

        if has_critical_missing:
            conclusion = "FAIL"
        elif warnings:
            conclusion = "WARN"
        else:
            conclusion = "PASS"

        return DryRunReport(
            estimated_total=sampled_count,  # 预估值（仅基于采样）
            sampled_count=sampled_count,
            required_field_coverage=required_coverage,
            optional_field_coverage=optional_coverage,
            unmapped_source_fields=unmapped,
            conclusion=conclusion,
            warnings=warnings,
        )

    # ── show_schema() ──────────────────────────────────────────────────

    def show_schema(self) -> str:
        """输出 Canonical Schema 字段说明表格。"""
        required_set = set(REQUIRED_FIELDS)
        lines: list[str] = []
        lines.append("Canonical Schema 字段说明")
        lines.append("=" * 80)
        lines.append(
            f"{'字段':<25} {'必填':<6} {'类型':<15} {'说明'}"
        )
        lines.append("-" * 80)

        # 字段说明映射
        field_docs = {
            "msg_uid": ("str", "{prefix}:{id} 格式唯一标识"),
            "ts": ("int", "Unix 时间戳（秒）"),
            "speaker": ("str", "ME / OTHER / OTHER:{name}"),
            "type": ("int", "消息类型码"),
            "modality": ("str", f"模态: {', '.join(sorted(VALID_MODALITIES))}"),
            "text_raw": ("str", "原始文本内容"),
            "seq_in_html": ("int", "HTML 中的序号"),
            "MsgSvrID": ("str", "微信服务器消息 ID"),
            "token": ("str", "消息 token"),
            "time_local": ("str", "本地时间 YYYY-MM-DD HH:MM:SS"),
            "sub_type": ("int", "消息子类型码"),
            "media_path": ("str?", "相对于 raw/ 的媒体路径"),
            "voice_length": ("int?", "语音时长（毫秒）"),
            "voice_to_text": ("str?", "语音转文字"),
            "link_url": ("str?", "链接 URL"),
            "link_title": ("str?", "链接标题"),
            "miniprogram_appid": ("str?", "小程序 AppID"),
            "quote_svrid": ("str?", "引用消息 ID"),
            "quote_type": ("int?", "引用消息类型"),
            "quote_text": ("str?", "引用消息文本"),
            "file_name": ("str?", "文件名"),
            "file_size": ("str?", "文件大小"),
            "location_x": ("float?", "位置经度"),
            "location_y": ("float?", "位置纬度"),
            "location_label": ("str?", "位置标签"),
            "contact_nickname": ("str?", "名片昵称"),
            "contact_username": ("str?", "名片用户名"),
        }

        for f in CanonicalMessage.__dataclass_fields__:
            is_req = "✅" if f in required_set else "❌"
            type_str, desc = field_docs.get(f, ("", ""))
            lines.append(f"{f:<25} {is_req:<6} {type_str:<15} {desc}")

        lines.append("=" * 80)
        return "\n".join(lines)

    # ── show_adapters() ────────────────────────────────────────────────

    def show_adapters(self, source_type: str = None) -> str:
        """列出适配器信息。

        如果指定 source_type，输出该适配器的详细说明；
        否则列出所有已注册适配器的概要。
        """
        if source_type:
            adapter = self.registry.get(source_type)
            info = adapter.describe()
            lines = [
                f"适配器: {info['source_type']}",
                "=" * 60,
                f"说明: {info.get('description', '').strip()}",
                "",
                "期望的输入文件:",
            ]
            for ef in info.get("expected_files", []):
                lines.append(f"  - {ef}")
            if not info.get("expected_files"):
                lines.append("  （未指定）")

            if info.get("field_mapping_example"):
                lines.append("")
                lines.append("字段映射示例:")
                for src, tgt in info["field_mapping_example"].items():
                    lines.append(f"  {src}: {tgt}")

            return "\n".join(lines)

        # 列出所有适配器
        lines = [
            "已注册的适配器",
            "=" * 60,
            f"{'source_type':<20} {'说明'}",
            "-" * 60,
        ]
        for st in self.registry.list_types():
            adapter = self.registry.get(st)
            info = adapter.describe()
            desc = info.get("description", "").strip().split("\n")[0]
            lines.append(f"{st:<20} {desc}")
        lines.append("=" * 60)
        return "\n".join(lines)

    # ── init_manifest() ────────────────────────────────────────────────

    def init_manifest(self, source_type: str, workspace_root: Path) -> Path:
        """在目标 Workspace 生成预填充的 source_manifest.yaml。

        Returns:
            生成的 manifest 文件路径。
        """
        # 验证 source_type 是否有效
        self.registry.get(source_type)

        raw_dir = workspace_root / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = raw_dir / "source_manifest.yaml"

        # 根据 source_type 生成对应的模板内容
        input_example = _SOURCE_TYPE_INPUT_EXAMPLES.get(source_type, "  - ./data_file")
        mapping_section = ""
        if source_type in ("generic_csv", "generic_jsonl"):
            mapping_section = (
                "\n"
                "# 字段映射（generic_csv / generic_jsonl 必填）\n"
                "field_mapping:\n"
                "  timestamp: ts\n"
                "  sender_name: speaker\n"
                "  content: text_raw\n"
                "  msg_type: type\n"
                "  _const:text: modality\n"
                "  _const:GEN: _source_prefix\n"
                "  _default:0: sub_type\n"
            )

        content = (
            f"# source_manifest.yaml — 由 init_manifest 自动生成\n"
            f"# source_type: {source_type}\n"
            f"\n"
            f"source_type: {source_type}\n"
            f"\n"
            f"input_paths:\n"
            f"{input_example}\n"
            f"\n"
            f"participant_map:\n"
            f'  # "我的名字": "ME"\n'
            f'  # "对方名字": "OTHER"\n'
            f"\n"
            f"timezone: Asia/Shanghai\n"
            f"\n"
            f"# media_base_dir: ./media\n"
            f"# workspace_name: {workspace_root.name}\n"
            f"{mapping_section}"
        )

        manifest_path.write_text(content, encoding="utf-8")
        logger.info("已生成 manifest: %s", manifest_path)
        return manifest_path

    # ── detect_source_type() ───────────────────────────────────────────

    @staticmethod
    def detect_source_type(raw_dir: Path) -> Optional[str]:
        """自动检测 raw/ 目录下的数据来源类型。

        检测规则：
        - 存在 *.html 且 *.csv → wechat_html
        - 存在 result.json → telegram_json
        - 存在 *.txt（WhatsApp 格式特征） → whatsapp_txt
        - 否则返回 None
        """
        if not raw_dir.exists():
            return None

        files = list(raw_dir.iterdir())
        extensions = {f.suffix.lower() for f in files if f.is_file()}
        names = {f.name for f in files if f.is_file()}

        # 微信：同时存在 .html 和 .csv
        if ".html" in extensions and ".csv" in extensions:
            return "wechat_html"

        # Telegram：存在 result.json
        if "result.json" in names:
            return "telegram_json"

        # WhatsApp：存在 .txt 文件
        if ".txt" in extensions:
            return "whatsapp_txt"

        return None

    # ── 内部方法 ───────────────────────────────────────────────────────

    @staticmethod
    def _build_report(
        records: list[dict],
        records_skipped: int,
        skip_reasons: dict[str, int],
        media_files_copied: int,
        media_files_skipped: int,
    ) -> IngestionReport:
        """从有效记录列表构建统计报告。"""
        by_modality: dict[str, int] = {}
        by_speaker: dict[str, int] = {}

        for rec in records:
            mod = rec.get("modality", "unknown")
            by_modality[mod] = by_modality.get(mod, 0) + 1

            spk = rec.get("speaker", "unknown")
            by_speaker[spk] = by_speaker.get(spk, 0) + 1

        # 日期范围
        if records:
            min_ts = min(r.get("ts", 0) for r in records)
            max_ts = max(r.get("ts", 0) for r in records)
            try:
                min_date = datetime.fromtimestamp(min_ts).strftime("%Y-%m-%d")
                max_date = datetime.fromtimestamp(max_ts).strftime("%Y-%m-%d")
            except (OSError, ValueError, OverflowError):
                min_date = max_date = ""
            date_range = (min_date, max_date)
        else:
            date_range = ("", "")

        return IngestionReport(
            total_messages=len(records),
            by_modality=by_modality,
            by_speaker=by_speaker,
            date_range=date_range,
            media_files_copied=media_files_copied,
            media_files_skipped=media_files_skipped,
            records_skipped=records_skipped,
            skip_reasons=skip_reasons,
        )


# ── 模块级常量 ────────────────────────────────────────────────────────

_SOURCE_TYPE_INPUT_EXAMPLES: dict[str, str] = {
    "wechat_html": "  - ./export.html",
    "telegram_json": "  - ./result.json",
    "whatsapp_txt": "  - ./chat.txt",
    "generic_csv": "  - ./data.csv",
    "generic_jsonl": "  - ./data.jsonl",
}
