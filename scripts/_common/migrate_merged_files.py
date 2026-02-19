#!/usr/bin/env python3
"""
migrate_merged_files.py
一次性迁移脚本：将所有旧格式 merged_final.jsonl 转换为新格式

运行方式：
    python scripts/_common/migrate_merged_files.py
    python scripts/_common/migrate_merged_files.py --dry-run  # 预览模式

迁移完成后，此脚本可删除或归档。

Requirements: 7.2, 7.3
"""

import os
import sys
import json
import shutil
import argparse
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts._common.schema_utils import (
    SCHEMA_VERSION,
    migrate_legacy_record,
)
from scripts._common.path_utils import (
    get_image_after_merge,
    get_voice_after_merge,
    get_video_after_merge,
    get_sticker_after_merge,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_merged_files() -> Dict[str, Path]:
    """获取所有模态的 merged_final.jsonl 文件路径"""
    return {
        'image': get_image_after_merge() / 'image_merged_final.jsonl',
        'voice': get_voice_after_merge() / 'voice_merged_final.jsonl',
        'video': get_video_after_merge() / 'video_merged_final.jsonl',
        'sticker': get_sticker_after_merge() / 'sticker_merged_final.jsonl',
    }


def analyze_file(file_path: Path, modality: str) -> Dict:
    """分析文件，统计新旧格式记录数"""
    if not file_path.exists():
        return {
            'exists': False,
            'total': 0,
            'new_format': 0,
            'legacy_format': 0,
        }
    
    total = 0
    new_format = 0
    legacy_format = 0
    
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                record = json.loads(line)
                total += 1
                if record.get('schema_version') == SCHEMA_VERSION:
                    new_format += 1
                else:
                    legacy_format += 1
    
    return {
        'exists': True,
        'total': total,
        'new_format': new_format,
        'legacy_format': legacy_format,
    }


def migrate_file(
    file_path: Path,
    modality: str,
    dry_run: bool = False
) -> Tuple[int, int, int]:
    """
    迁移单个文件
    
    Returns:
        (total, migrated, skipped): 总数、迁移数、跳过数
    """
    if not file_path.exists():
        logger.warning(f"文件不存在: {file_path}")
        return (0, 0, 0)
    
    # 读取所有记录
    records = []
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))
    
    total = len(records)
    migrated = 0
    skipped = 0
    
    # 迁移记录
    migrated_records = []
    for record in records:
        if record.get('schema_version') == SCHEMA_VERSION:
            # 已是新格式，跳过
            migrated_records.append(record)
            skipped += 1
        else:
            # 旧格式，迁移
            new_record = migrate_legacy_record(record, modality)
            migrated_records.append(new_record)
            migrated += 1
    
    if dry_run:
        logger.info(f"[DRY-RUN] {modality}: 将迁移 {migrated} 条记录，跳过 {skipped} 条")
        return (total, migrated, skipped)
    
    # 备份原文件
    backup_path = file_path.with_suffix('.jsonl.bak')
    shutil.copy2(file_path, backup_path)
    logger.info(f"已备份: {backup_path}")
    
    # 写入新文件
    with open(file_path, 'w', encoding='utf-8') as f:
        for record in migrated_records:
            f.write(json.dumps(record, ensure_ascii=False) + '\n')
    
    logger.info(f"{modality}: 迁移 {migrated} 条，跳过 {skipped} 条，总计 {total} 条")
    
    return (total, migrated, skipped)


def main():
    parser = argparse.ArgumentParser(
        description='迁移旧格式 merged_final.jsonl 到新格式'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='预览模式，不实际修改文件'
    )
    parser.add_argument(
        '--modality',
        choices=['image', 'voice', 'video', 'sticker', 'all'],
        default='all',
        help='指定要迁移的模态（默认: all）'
    )
    args = parser.parse_args()
    
    print("=" * 60)
    print("Merged Schema Migration Tool")
    print("=" * 60)
    print(f"目标 Schema 版本: {SCHEMA_VERSION}")
    print(f"模式: {'预览' if args.dry_run else '实际迁移'}")
    print()
    
    merged_files = get_merged_files()
    
    if args.modality != 'all':
        merged_files = {args.modality: merged_files[args.modality]}
    
    # 分析阶段
    print("[1/2] 分析文件...")
    print("-" * 60)
    
    analysis_results = {}
    for modality, file_path in merged_files.items():
        result = analyze_file(file_path, modality)
        analysis_results[modality] = result
        
        if result['exists']:
            print(f"  {modality}:")
            print(f"    文件: {file_path}")
            print(f"    总记录: {result['total']}")
            print(f"    新格式: {result['new_format']}")
            print(f"    旧格式: {result['legacy_format']}")
        else:
            print(f"  {modality}: 文件不存在")
    
    # 检查是否需要迁移
    need_migration = any(
        r['exists'] and r['legacy_format'] > 0
        for r in analysis_results.values()
    )
    
    if not need_migration:
        print()
        print("✅ 所有文件已是新格式，无需迁移")
        return
    
    # 迁移阶段
    print()
    print("[2/2] 迁移文件...")
    print("-" * 60)
    
    total_stats = {
        'total': 0,
        'migrated': 0,
        'skipped': 0,
    }
    
    for modality, file_path in merged_files.items():
        if not analysis_results[modality]['exists']:
            continue
        
        if analysis_results[modality]['legacy_format'] == 0:
            logger.info(f"{modality}: 已是新格式，跳过")
            total_stats['skipped'] += analysis_results[modality]['total']
            continue
        
        total, migrated, skipped = migrate_file(
            file_path, modality, dry_run=args.dry_run
        )
        
        total_stats['total'] += total
        total_stats['migrated'] += migrated
        total_stats['skipped'] += skipped
    
    # 输出统计报告
    print()
    print("=" * 60)
    print("迁移统计报告")
    print("=" * 60)
    print(f"  总记录数: {total_stats['total']}")
    print(f"  已迁移: {total_stats['migrated']}")
    print(f"  已跳过: {total_stats['skipped']}")
    
    if args.dry_run:
        print()
        print("⚠️  这是预览模式，未实际修改文件")
        print("    移除 --dry-run 参数以执行实际迁移")
    else:
        print()
        print("✅ 迁移完成")
        print("    原文件已备份为 *.jsonl.bak")


if __name__ == '__main__':
    main()
