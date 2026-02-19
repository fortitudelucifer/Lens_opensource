#!/usr/bin/env python3
"""
工作空间初始化脚本

将CHAT_APP导出的原始材料库转换为符合 CHAT_APP_DHA 项目结构的工作空间。

使用方法:
    python scripts/workspace/init_workspace.py              # 执行初始化
    python scripts/workspace/init_workspace.py --dry-run    # 仅预览，不执行
    python scripts/workspace/init_workspace.py --template lwy  # 指定模板工作空间
    python scripts/workspace/init_workspace.py --contact-name "CONTACT_NAME"  # 指定联系人名

功能:
    1. 创建标准目录结构
    2. 迁移原始文件到 raw/ 目录
    3. 复制脚本和配置文件
    4. 生成工作空间特定配置
    5. 清理旧目录（可选）
"""

import os
import sys
import shutil
import argparse
from pathlib import Path
from datetime import datetime
from typing import List, Tuple, Optional


def get_workspace_root() -> Path:
    """获取当前工作空间根目录"""
    script_dir = Path(__file__).resolve().parent
    return script_dir.parents[1]


def detect_contact_name(root: Path) -> Optional[str]:
    """自动检测联系人名（从 HTML 文件名）"""
    for f in root.glob("*.html"):
        if not f.name.startswith("."):
            return f.stem
    return None


def create_directory_structure(root: Path, dry_run: bool = False) -> None:
    """创建标准目录结构"""
    directories = [
        # raw 子目录
        "raw/export",
        "raw/image",
        "raw/voice",
        "raw/video",
        "raw/sticker",
        "raw/file",
        "raw/avatar",
        "raw/emoji",
        "raw/icon",
        "raw/music",
        # artifacts 子目录
        "artifacts/before_merge/image",
        "artifacts/before_merge/voice",
        "artifacts/before_merge/video",
        "artifacts/before_merge/sticker/thumbs",
        "artifacts/before_merge/sticker/frames",
        "artifacts/before_merge/linkfile",
        "artifacts/after_merge/image",
        "artifacts/after_merge/voice",
        "artifacts/after_merge/video",
        "artifacts/after_merge/sticker",
        # 其他目录
        "timeline_out",
        "configs",
        "docs",
        "logs",
        "tests/manual_images",
        "tests/manual_videos",
        ".kiro/specs",
        ".kiro/steering",
    ]
    
    print("=" * 60)
    print("[1/5] 创建目录结构")
    print("=" * 60)
    
    created = 0
    skipped = 0
    
    for dir_path in directories:
        full_path = root / dir_path
        if full_path.exists():
            skipped += 1
        else:
            if dry_run:
                print(f"  [预览] 将创建: {dir_path}")
            else:
                full_path.mkdir(parents=True, exist_ok=True)
            created += 1
    
    if not dry_run:
        print(f"  创建: {created} 个目录, 跳过: {skipped} 个已存在")


def migrate_files(root: Path, dry_run: bool = False) -> List[Tuple[Path, Path, str]]:
    """迁移原始文件到标准位置"""
    print("\n" + "=" * 60)
    print("[2/5] 迁移文件")
    print("=" * 60)
    
    migrations = []
    
    # 定义迁移规则: (源目录/文件模式, 目标目录, 类别名)
    migration_rules = [
        # 导出文件
        ("*.html", "raw/export", "导出文件"),
        ("*.csv", "raw/export", "导出文件"),
        ("*.md", "raw/export", "导出文件"),
        # 媒体目录
        ("file", "raw/file", "文件传输"),
        ("voice", "raw/voice", "语音消息"),
        ("image", "raw/image", "图片"),
        ("video", "raw/video", "视频"),
        ("emoji", "raw/emoji", "表情包"),
        ("avatar", "raw/avatar", "头像"),
        ("icon", "raw/icon", "图标"),
        ("music", "raw/music", "音乐"),
    ]
    
    for pattern, dest_dir, category in migration_rules:
        dest_path = root / dest_dir
        
        if "*" in pattern:
            # 文件模式匹配
            for src in root.glob(pattern):
                if src.name.startswith(".") or src.is_dir():
                    continue
                dest = dest_path / src.name
                if not dest.exists():
                    migrations.append((src, dest, category))
        else:
            # 目录迁移
            src_dir = root / pattern
            if src_dir.exists() and src_dir.is_dir():
                for item in src_dir.iterdir():
                    if item.is_dir():
                        dest = dest_path / item.name
                        if not dest.exists():
                            migrations.append((item, dest, f"{category}目录"))
                    elif item.is_file():
                        dest = dest_path / item.name
                        if not dest.exists():
                            migrations.append((item, dest, category))
    
    # 执行迁移
    if not migrations:
        print("  没有需要迁移的文件")
        return migrations
    
    migrated = 0
    for src, dest, category in migrations:
        if dry_run:
            print(f"  [预览] {category}: {src.name} -> {dest.relative_to(root)}")
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                shutil.copytree(src, dest)
            else:
                shutil.copy2(src, dest)
            migrated += 1
    
    if not dry_run:
        print(f"  迁移: {migrated} 个文件/目录")
    
    return migrations


def copy_scripts_and_configs(root: Path, template_workspace: str, dry_run: bool = False) -> None:
    """从模板工作空间复制脚本和配置"""
    print("\n" + "=" * 60)
    print("[3/5] 复制脚本和配置")
    print("=" * 60)
    
    template_root = root.parent / template_workspace
    
    if not template_root.exists():
        print(f"  ⚠️  模板工作空间不存在: {template_workspace}")
        return
    
    # 复制 scripts 目录（真实文件，非软链接）
    src_scripts = template_root / "scripts"
    dest_scripts = root / "scripts"
    
    if src_scripts.exists() and not dest_scripts.exists():
        if dry_run:
            print(f"  [预览] 复制 scripts/ 目录（真实文件）")
        else:
            shutil.copytree(src_scripts, dest_scripts, 
                          ignore=shutil.ignore_patterns('__pycache__', '*.pyc'),
                          symlinks=False)  # 确保复制真实文件而非软链接
            print(f"  复制: scripts/ 目录（真实文件）")
    
    # 复制通用配置文件（真实文件，非软链接）
    config_files = [
        "caption.yaml", "linkfile.yaml", "router.yaml", 
        "sticker.yaml", "video.yaml", "voice.yaml"
    ]
    
    copied_configs = 0
    for config_file in config_files:
        src = template_root / "configs" / config_file
        dest = root / "configs" / config_file
        
        if src.exists() and not dest.exists():
            if dry_run:
                print(f"  [预览] 复制 configs/{config_file}")
            else:
                # 确保复制真实文件内容
                shutil.copy2(src, dest, follow_symlinks=True)
                copied_configs += 1
    
    if not dry_run and copied_configs > 0:
        print(f"  复制: {copied_configs} 个通用配置文件（真实文件）")
    
    # 复制 steering 文件（真实文件，非软链接）
    steering_files = ["behavior.md", "product.md", "structure.md", "tech.md"]
    
    copied_steering = 0
    for steering_file in steering_files:
        src = template_root / ".kiro" / "steering" / steering_file
        dest = root / ".kiro" / "steering" / steering_file
        
        if src.exists() and not dest.exists():
            if dry_run:
                print(f"  [预览] 复制 .kiro/steering/{steering_file}")
            else:
                # 确保复制真实文件内容
                shutil.copy2(src, dest, follow_symlinks=True)
                copied_steering += 1
    
    if not dry_run and copied_steering > 0:
        print(f"  复制: {copied_steering} 个 steering 文件（真实文件）")
    
    # 复制 docs 目录（如果存在）
    src_docs = template_root / "docs"
    dest_docs = root / "docs"
    
    if src_docs.exists() and not dest_docs.exists():
        if dry_run:
            print(f"  [预览] 复制 docs/ 目录")
        else:
            shutil.copytree(src_docs, dest_docs, 
                          ignore=shutil.ignore_patterns('__pycache__', '*.pyc'),
                          symlinks=False)
            print(f"  复制: docs/ 目录")


def create_workspace_configs(root: Path, workspace_name: str, contact_name: str, 
                            dry_run: bool = False) -> None:
    """创建工作空间特定配置"""
    print("\n" + "=" * 60)
    print("[4/5] 创建工作空间配置")
    print("=" * 60)
    
    # paths.yaml
    paths_yaml = root / "configs" / "paths.yaml"
    if not paths_yaml.exists():
        content = f'''# ============================================================
# 路径配置 - 工作空间级别
# ============================================================
workspace_name: {workspace_name}
base_dir: /path/to/data/root

dirs:
  raw: ${{root}}/raw
  image: ${{root}}/raw/image
  video: ${{root}}/raw/video
  voice: ${{root}}/raw/voice
  sticker: ${{root}}/raw/sticker
  file: ${{root}}/raw/file
  export: ${{root}}/raw/export
  logs: ${{root}}/logs

raw:
  messages: ${{root}}/raw/P1_messages_raw.jsonl
  voice_dir: ${{root}}/raw/voice

artifacts:
  before_merge: ${{root}}/artifacts/before_merge
  after_merge: ${{root}}/artifacts/after_merge
  image_before: ${{root}}/artifacts/before_merge/image
  image_after: ${{root}}/artifacts/after_merge/image
  voice_before: ${{root}}/artifacts/before_merge/voice
  voice_after: ${{root}}/artifacts/after_merge/voice
  video_before: ${{root}}/artifacts/before_merge/video
  video_after: ${{root}}/artifacts/after_merge/video
  sticker_before: ${{root}}/artifacts/before_merge/sticker
  sticker_after: ${{root}}/artifacts/after_merge/sticker
  sticker_thumbs: ${{root}}/artifacts/before_merge/sticker/thumbs
  sticker_frames: ${{root}}/artifacts/before_merge/sticker/frames
  linkfile_before: ${{root}}/artifacts/before_merge/linkfile
  linkfile_after: ${{root}}/artifacts/after_merge/linkfile

cache:
  video_keyframes: /data/cache/video_keyframes
  video_audio: /data/cache/video_audio
  video_normalized: /data/cache/video_normalized
  sticker_temp: /data/cache/sticker/temp

timeline_out: ${{root}}/timeline_out
picks: ${{root}}/picks

test:
  manual_videos: ${{root}}/tests/manual_videos
  manual_images: ${{root}}/tests/manual_images
'''
        if dry_run:
            print(f"  [预览] 创建 configs/paths.yaml")
        else:
            paths_yaml.write_text(content, encoding='utf-8')
            print(f"  创建: configs/paths.yaml")
    
    # anonymization.yaml
    anon_yaml = root / "configs" / "anonymization.yaml"
    if not anon_yaml.exists():
        content = f'''# ============================================================
# 名字脱敏映射 - {workspace_name} 工作空间
# ============================================================
me_names:
  - "我的真名"
  - "我的昵称"

other_names:
  - "{contact_name}"
  - "对方昵称"

me_alias: "ME"
other_alias: "OTHER"
'''
        if dry_run:
            print(f"  [预览] 创建 configs/anonymization.yaml")
        else:
            anon_yaml.write_text(content, encoding='utf-8')
            print(f"  创建: configs/anonymization.yaml")
    
    # hotword.txt
    hotword_txt = root / "configs" / "hotword.txt"
    if not hotword_txt.exists():
        content = f'''# ASR 热词列表 - {workspace_name} 工作空间
{contact_name}
'''
        if dry_run:
            print(f"  [预览] 创建 configs/hotword.txt")
        else:
            hotword_txt.write_text(content, encoding='utf-8')
            print(f"  创建: configs/hotword.txt")


def cleanup_old_dirs(root: Path, dry_run: bool = False) -> None:
    """清理已迁移的旧目录"""
    print("\n" + "=" * 60)
    print("[5/5] 清理旧目录")
    print("=" * 60)
    
    old_dirs = ["file", "voice", "image", "video", "emoji", "avatar", "icon", "music"]
    old_files = list(root.glob("*.html")) + list(root.glob("*.csv")) + list(root.glob("*.md"))
    
    # 过滤掉 .kiro 等隐藏目录
    old_files = [f for f in old_files if not f.name.startswith(".")]
    
    items_to_clean = []
    
    for dir_name in old_dirs:
        old_dir = root / dir_name
        if old_dir.exists() and old_dir.is_dir():
            items_to_clean.append(old_dir)
    
    items_to_clean.extend(old_files)
    
    if not items_to_clean:
        print("  没有需要清理的旧文件/目录")
        return
    
    if dry_run:
        print("  以下文件/目录可以删除:")
        for item in items_to_clean:
            print(f"    - {item.name}")
        print("\n  运行不带 --dry-run 参数以执行清理")
    else:
        for item in items_to_clean:
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
        print(f"  删除: {len(items_to_clean)} 个文件/目录")


def print_summary(root: Path) -> None:
    """打印初始化摘要"""
    print("\n" + "=" * 60)
    print("初始化摘要")
    print("=" * 60)
    
    def count_files(path: Path, pattern: str = "*") -> int:
        if not path.exists():
            return 0
        return sum(1 for _ in path.rglob(pattern) if _.is_file())
    
    raw_dir = root / "raw"
    print(f"\n原始数据 (raw/):")
    print(f"  - 导出文件: {count_files(raw_dir / 'export')} 个")
    print(f"  - 图片: {count_files(raw_dir / 'image')} 个")
    print(f"  - 语音: {count_files(raw_dir / 'voice', '*.mp3')} 个")
    print(f"  - 视频: {count_files(raw_dir / 'video')} 个")
    print(f"  - 表情包: {count_files(raw_dir / 'sticker')} 个")
    print(f"  - 文件: {count_files(raw_dir / 'file')} 个")
    
    scripts_dir = root / "scripts"
    print(f"\n脚本: {count_files(scripts_dir, '*.py')} 个 Python 文件")
    
    print(f"\n下一步操作:")
    print(f"  1. 检查并更新 configs/anonymization.yaml 中的名字映射")
    print(f"  2. 运行 HTML 提取: python scripts/extract/extract_html_to_jsonl.py")
    print(f"  3. 按需运行各模态流水线")


def run_ingestion_step(root: Path, args) -> None:
    """归一化导入步骤：自动检测来源类型并执行数据归一化。

    在 create_workspace_configs() 之后、cleanup_old_dirs() 之前调用。
    失败时打印警告但不中断整个初始化流程。

    Args:
        root: 工作空间根目录
        args: 命令行参数（需包含 source_type, skip_ingest, ingest_dry_run）
    """
    print(f"\n[4.5/5] 归一化导入")
    print("-" * 40)

    if args.skip_ingest:
        print("  ⏭️  已跳过（--skip-ingest）")
        return

    try:
        from scripts.workspace.ingestion.engine import IngestionEngine
        from scripts.workspace.ingestion.registry import AdapterRegistry
        from scripts.workspace.ingestion.manifest import load_manifest, validate_manifest
    except ImportError as e:
        print(f"  ⚠️  归一化模块未安装，跳过导入步骤: {e}")
        return

    try:
        registry = AdapterRegistry()
        registry.discover()
        engine = IngestionEngine(registry)

        # 自动检测或使用指定的 source_type
        source_type = args.source_type or IngestionEngine.detect_source_type(root / "raw")

        if not source_type:
            print("  ℹ️  未检测到已知数据来源类型，跳过归一化导入")
            print("  提示: 使用 --source-type 指定来源类型，或在 raw/ 目录放置导出文件")
            return

        print(f"  来源类型: {source_type}")

        # 生成 manifest（如果不存在）
        manifest_path = root / "raw" / "source_manifest.yaml"
        if not manifest_path.exists():
            print(f"  生成 source_manifest.yaml ...")
            engine.init_manifest(source_type, root)

        # 加载并校验 manifest
        manifest = load_manifest(manifest_path)
        errors = validate_manifest(manifest, set(registry.list_types()))
        if errors:
            print("  ⚠️  manifest 校验失败:")
            for err in errors:
                print(f"    - {err}")
            print("  请修正 raw/source_manifest.yaml 后重新运行")
            return

        if args.ingest_dry_run:
            # 预检模式
            print("  执行预检（dry-run）...")
            report = engine.dry_run(manifest)
            print(f"  采样数量: {report.sampled_count}")
            print(f"  预估总数: {report.estimated_total}")
            if hasattr(report, "required_field_coverage"):
                print("  必填字段覆盖率:")
                for fname, cov in sorted(report.required_field_coverage.items()):
                    marker = "✅" if cov == 1.0 else "⚠️" if cov > 0 else "❌"
                    print(f"    {marker} {fname:<20} {cov:.1%}")
            if report.warnings:
                for w in report.warnings:
                    print(f"  ⚠️  {w}")
            conclusion_map = {
                "PASS": "✅ 所有必填字段已覆盖，可以继续转换",
                "WARN": "⚠️  部分必填字段覆盖率不足，建议检查配置",
                "FAIL": "❌ 关键必填字段缺失，需要调整配置",
            }
            print(f"  结论: {conclusion_map.get(report.conclusion, report.conclusion)}")
        else:
            # 执行完整归一化
            print("  执行归一化转换...")
            report = engine.run(manifest, root)
            print(f"  ✅ 归一化完成:")
            print(f"    总消息数: {report.total_messages}")
            print(f"    跳过记录: {report.records_skipped}")
            print(f"    媒体文件: {report.media_files_copied} 复制, {report.media_files_skipped} 跳过")
            if report.date_range[0]:
                print(f"    日期范围: {report.date_range[0]} ~ {report.date_range[1]}")

    except Exception as e:
        print(f"  ⚠️  归一化导入失败: {e}")
        print("  初始化将继续，您可以稍后使用 run_ingest.py 单独运行归一化")


def main():
    parser = argparse.ArgumentParser(description="初始化 CHAT_APP_DHA 工作空间")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不执行实际操作")
    parser.add_argument("--template", default="lwy", help="模板工作空间名称 (默认: lwy)")
    parser.add_argument("--contact-name", help="联系人名称 (默认: 从 HTML 文件名检测)")
    parser.add_argument("--skip-cleanup", action="store_true", help="跳过清理旧目录")
    parser.add_argument("--source-type", help="输入数据来源类型 (chat_app_html|telegram_json|whatsapp_txt|generic_csv|generic_jsonl)")
    parser.add_argument("--skip-ingest", action="store_true", help="跳过归一化导入步骤")
    parser.add_argument("--ingest-dry-run", action="store_true", help="仅预检归一化，不执行实际转换")
    args = parser.parse_args()
    
    root = get_workspace_root()
    workspace_name = root.name
    
    # 检测联系人名
    contact_name = args.contact_name or detect_contact_name(root) or "联系人"
    
    print(f"\n{'='*60}")
    print(f"CHAT_APP_DHA 工作空间初始化")
    print(f"{'='*60}")
    print(f"  工作空间: {workspace_name}")
    print(f"  联系人: {contact_name}")
    print(f"  模板: {args.template}")
    print(f"  模式: {'预览' if args.dry_run else '执行'}")
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 执行初始化步骤
    create_directory_structure(root, args.dry_run)
    migrate_files(root, args.dry_run)
    copy_scripts_and_configs(root, args.template, args.dry_run)
    create_workspace_configs(root, workspace_name, contact_name, args.dry_run)
    
    # 归一化导入步骤（仅在非预览模式下执行）
    if not args.dry_run:
        run_ingestion_step(root, args)
    
    if not args.skip_cleanup:
        cleanup_old_dirs(root, args.dry_run)
    
    if not args.dry_run:
        print_summary(root)
    
    print("\n" + "=" * 60)
    if args.dry_run:
        print("预览完成。使用不带 --dry-run 参数运行以执行实际操作。")
    else:
        print("✅ 初始化完成！")
    print("=" * 60)


if __name__ == "__main__":
    main()
