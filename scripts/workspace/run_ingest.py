#!/usr/bin/env python3
"""
run_ingest.py
归一化输入接口 CLI 入口

用法：
    # 完整转换
    python scripts/workspace/run_ingest.py --workspace ls

    # 预检模式
    python scripts/workspace/run_ingest.py --workspace ls --dry-run

    # 查看 schema
    python scripts/workspace/run_ingest.py --show-schema

    # 查看适配器
    python scripts/workspace/run_ingest.py --show-adapters
    python scripts/workspace/run_ingest.py --show-adapters --source-type telegram_json

    # 生成 manifest 模板
    python scripts/workspace/run_ingest.py --init-manifest --source-type telegram_json --workspace new_chat

Requirements: 10.1, 13.1, 13.2, 13.3, 13.4, 14.1
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# ── 项目根目录 ────────────────────────────────────────────────────────
# run_ingest.py 位于 scripts/workspace/，项目根在两级上层
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent.parent

if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.workspace.ingestion.engine import IngestionEngine
from scripts.workspace.ingestion.manifest import load_manifest, validate_manifest
from scripts.workspace.ingestion.registry import AdapterRegistry

logger = logging.getLogger(__name__)


# ── 工具函数 ──────────────────────────────────────────────────────────


def _resolve_workspace_root(workspace_name: str) -> Path:
    """根据 workspace 名称解析工作空间根目录。

    优先从 configs/paths.yaml 读取 base_dir，回退到默认值 <WORKSPACES_DIR>。
    """
    try:
        import yaml

        config_path = _PROJECT_ROOT / "configs" / "paths.yaml"
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
            base_dir = config.get("base_dir", "<WORKSPACES_DIR>")
        else:
            base_dir = "<WORKSPACES_DIR>"
    except Exception:
        base_dir = "<WORKSPACES_DIR>"

    return Path(base_dir) / workspace_name


def _build_registry() -> AdapterRegistry:
    """构建并初始化适配器注册表。"""
    registry = AdapterRegistry()
    registry.discover()
    return registry


def _print_ingestion_report(report) -> None:
    """格式化输出转换统计报告。"""
    print("\n" + "=" * 60)
    print("归一化转换完成")
    print("=" * 60)
    print(f"  总消息数:       {report.total_messages}")
    print(f"  跳过记录:       {report.records_skipped}")
    print(f"  媒体文件复制:   {report.media_files_copied}")
    print(f"  媒体文件跳过:   {report.media_files_skipped}")

    if report.date_range[0]:
        print(f"  日期范围:       {report.date_range[0]} ~ {report.date_range[1]}")

    if report.by_modality:
        print("\n  模态分布:")
        for mod, cnt in sorted(report.by_modality.items()):
            print(f"    {mod:<15} {cnt}")

    if report.by_speaker:
        print("\n  说话人分布:")
        for spk, cnt in sorted(report.by_speaker.items()):
            print(f"    {spk:<15} {cnt}")

    if report.skip_reasons:
        print("\n  跳过原因:")
        for reason, cnt in sorted(report.skip_reasons.items()):
            print(f"    {reason}: {cnt}")

    print("=" * 60)


def _print_dry_run_report(report) -> None:
    """格式化输出预检报告。"""
    print("\n" + "=" * 60)
    print("预检报告 (dry-run)")
    print("=" * 60)
    print(f"  采样数量:   {report.sampled_count}")
    print(f"  预估总数:   {report.estimated_total}")

    print("\n  必填字段覆盖率:")
    for fname, cov in sorted(report.required_field_coverage.items()):
        marker = "✅" if cov == 1.0 else "⚠️" if cov > 0 else "❌"
        print(f"    {marker} {fname:<20} {cov:.1%}")

    if report.optional_field_coverage:
        print("\n  可选字段覆盖率:")
        for fname, cov in sorted(report.optional_field_coverage.items()):
            print(f"    {fname:<20} {cov:.1%}")

    if report.unmapped_source_fields:
        print("\n  未映射的源字段:")
        for fname, example in sorted(report.unmapped_source_fields.items()):
            print(f"    {fname}: {example}")

    if report.warnings:
        print("\n  ⚠️  警告:")
        for w in report.warnings:
            print(f"    - {w}")

    conclusion_map = {
        "PASS": "✅ 所有必填字段已覆盖，可以继续转换",
        "WARN": "⚠️  部分必填字段覆盖率不足，建议检查配置",
        "FAIL": "❌ 关键必填字段缺失，需要调整配置",
    }
    print(f"\n  结论: {conclusion_map.get(report.conclusion, report.conclusion)}")
    print("=" * 60)


# ── 命令处理 ──────────────────────────────────────────────────────────


def cmd_show_schema(engine: IngestionEngine) -> int:
    """处理 --show-schema 命令。"""
    print(engine.show_schema())
    return 0


def cmd_show_adapters(engine: IngestionEngine, source_type: str | None) -> int:
    """处理 --show-adapters 命令。"""
    try:
        print(engine.show_adapters(source_type=source_type))
    except KeyError as e:
        print(f"错误: {e}", file=sys.stderr)
        return 1
    return 0


def cmd_init_manifest(
    engine: IngestionEngine, source_type: str | None, workspace_name: str | None
) -> int:
    """处理 --init-manifest 命令。"""
    if not source_type:
        print("错误: --init-manifest 需要指定 --source-type", file=sys.stderr)
        return 1
    if not workspace_name:
        print("错误: --init-manifest 需要指定 --workspace", file=sys.stderr)
        return 1

    workspace_root = _resolve_workspace_root(workspace_name)
    try:
        path = engine.init_manifest(source_type, workspace_root)
        print(f"已生成 manifest 模板: {path}")
    except KeyError as e:
        print(f"错误: {e}", file=sys.stderr)
        return 1
    return 0


def cmd_dry_run(engine: IngestionEngine, workspace_name: str) -> int:
    """处理 --dry-run 命令。"""
    workspace_root = _resolve_workspace_root(workspace_name)
    manifest_path = workspace_root / "raw" / "source_manifest.yaml"

    if not manifest_path.exists():
        print(
            f"错误: source_manifest.yaml 不存在: {manifest_path}\n"
            f"提示: 使用 --init-manifest 生成模板",
            file=sys.stderr,
        )
        return 1

    try:
        manifest = load_manifest(manifest_path)
    except (ValueError, Exception) as e:
        print(f"错误: 加载 manifest 失败: {e}", file=sys.stderr)
        return 1

    # 校验 manifest
    registered = set(engine.registry.list_types())
    errors = validate_manifest(manifest, registered)
    if errors:
        print("manifest 校验失败:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    report = engine.dry_run(manifest)
    _print_dry_run_report(report)
    return 0


def cmd_run(engine: IngestionEngine, workspace_name: str) -> int:
    """处理默认运行命令（完整转换）。"""
    workspace_root = _resolve_workspace_root(workspace_name)
    manifest_path = workspace_root / "raw" / "source_manifest.yaml"

    if not manifest_path.exists():
        # 尝试自动检测来源类型
        raw_dir = workspace_root / "raw"
        detected = IngestionEngine.detect_source_type(raw_dir)
        if detected:
            print(f"自动检测到来源类型: {detected}，正在生成 manifest...")
            try:
                engine.init_manifest(detected, workspace_root)
                manifest_path = workspace_root / "raw" / "source_manifest.yaml"
            except KeyError as e:
                print(f"错误: {e}", file=sys.stderr)
                return 1
        else:
            print(
                f"错误: source_manifest.yaml 不存在: {manifest_path}\n"
                f"提示: 使用 --init-manifest 生成模板",
                file=sys.stderr,
            )
            return 1

    try:
        manifest = load_manifest(manifest_path)
    except (ValueError, Exception) as e:
        print(f"错误: 加载 manifest 失败: {e}", file=sys.stderr)
        return 1

    # 校验 manifest
    registered = set(engine.registry.list_types())
    errors = validate_manifest(manifest, registered)
    if errors:
        print("manifest 校验失败:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    try:
        report = engine.run(manifest, workspace_root)
    except ValueError as e:
        print(f"错误: {e}", file=sys.stderr)
        return 1

    _print_ingestion_report(report)
    return 0


# ── argparse 定义 ─────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    """构建 CLI 参数解析器。"""
    parser = argparse.ArgumentParser(
        description="归一化输入接口 — 将多来源聊天记录转换为标准 raw/ 格式",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python scripts/workspace/run_ingest.py --workspace ls\n"
            "  python scripts/workspace/run_ingest.py --workspace ls --dry-run\n"
            "  python scripts/workspace/run_ingest.py --show-schema\n"
            "  python scripts/workspace/run_ingest.py --show-adapters --source-type telegram_json\n"
            "  python scripts/workspace/run_ingest.py --init-manifest --source-type telegram_json --workspace new_chat\n"
        ),
    )

    parser.add_argument(
        "--workspace",
        type=str,
        default=None,
        help="目标工作空间名称（run/dry-run/init-manifest 时必填）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="预检模式：扫描前 N 条记录生成覆盖率报告，不执行实际转换",
    )
    parser.add_argument(
        "--show-schema",
        action="store_true",
        help="输出 Canonical Schema 字段说明表格",
    )
    parser.add_argument(
        "--show-adapters",
        action="store_true",
        help="列出所有已注册的适配器（可配合 --source-type 查看详情）",
    )
    parser.add_argument(
        "--source-type",
        type=str,
        default=None,
        help="指定来源类型（配合 --show-adapters 或 --init-manifest 使用）",
    )
    parser.add_argument(
        "--init-manifest",
        action="store_true",
        help="生成预填充的 source_manifest.yaml 模板",
    )

    return parser


# ── main ──────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    """CLI 主入口。

    Args:
        argv: 命令行参数列表（None 时使用 sys.argv）。

    Returns:
        退出码（0=成功，非 0=失败）。
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # 构建引擎
    registry = _build_registry()
    engine = IngestionEngine(registry)

    # ── 分发命令 ──
    if args.show_schema:
        return cmd_show_schema(engine)

    if args.show_adapters:
        return cmd_show_adapters(engine, args.source_type)

    if args.init_manifest:
        return cmd_init_manifest(engine, args.source_type, args.workspace)

    # 以下命令需要 --workspace
    if not args.workspace:
        print(
            "错误: 请指定 --workspace 参数，或使用 --show-schema / --show-adapters 查看信息",
            file=sys.stderr,
        )
        parser.print_usage(sys.stderr)
        return 1

    if args.dry_run:
        return cmd_dry_run(engine, args.workspace)

    return cmd_run(engine, args.workspace)


if __name__ == "__main__":
    sys.exit(main())
