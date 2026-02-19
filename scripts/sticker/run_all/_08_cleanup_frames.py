#!/usr/bin/env python3
"""
表情包中间帧清理步骤

功能：
- 删除表情包处理过程中生成的中间帧文件
- 保留 Contact Sheet（用于溯源和调试）
- 释放磁盘空间（中间帧可能占用数 GB）
- 支持 Dry Run 模式（预览删除操作）

处理流程：
1. 扫描 frames 目录，分类文件：
   - Contact Sheets: *_contact.png（保留）
   - Intermediate Frames: *_f00.png, *_f01.png, ...（删除）
2. 计算文件大小和数量
3. 根据参数执行操作：
   - --dry-run: 仅预览，不实际删除
   - --keep-all: 跳过清理（保留所有文件）
   - 默认: 删除中间帧，保留 Contact Sheet
4. 打印统计信息（删除数量、释放空间）

为什么需要清理：
- 表情包处理会生成大量中间帧（每个动图 8-16 帧）
- 中间帧仅用于 VLM 分析，分析完成后不再需要
- Contact Sheet 已包含所有关键帧的缩略图（用于溯源）
- 保留中间帧会占用大量磁盘空间（数 GB）

文件命名规则：
- Contact Sheet: {msg_uid}_{sha256}_contact.png
- Intermediate Frame: {msg_uid}_{sha256}_f00.png, *_f01.png, ...
- 清理规则: 删除 *_f*.png，保留 *_contact.png

输入：
- artifacts/before_merge/sticker/frames/*.png: 中间帧文件

输出：
- 删除中间帧文件
- 保留 Contact Sheet 文件

依赖：
- scripts/_common/path_utils.py: 路径工具

使用示例：
    # 预览删除操作（不实际删除）
    python scripts/sticker/run_all/_08_cleanup_frames.py --dry-run
    
    # 实际删除中间帧
    python scripts/sticker/run_all/_08_cleanup_frames.py
    
    # 跳过清理（保留所有文件）
    python scripts/sticker/run_all/_08_cleanup_frames.py --keep-all

输出统计：
- Contact Sheets 数量和大小
- Intermediate Frames 数量和大小
- 删除的文件数量
- 释放的磁盘空间

作者：forcifer
更新于：2026-02-02
"""

import os
import sys
import argparse
import logging
from pathlib import Path
from typing import List, Tuple

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from scripts._common.path_utils import get_sticker_frames_dir

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def scan_frames_dir(frames_dir: Path) -> Tuple[List[Path], List[Path]]:
    """
    扫描 frames 目录，分类文件
    
    Args:
        frames_dir: frames 目录路径
    
    Returns:
        tuple: (contact_sheets, intermediate_frames)
            - contact_sheets: Contact Sheet 文件列表（*_contact.png）
            - intermediate_frames: 中间帧文件列表（*_f*.png）
    
    文件分类规则：
        - Contact Sheet: 文件名包含 '_contact.'
        - Intermediate Frame: 文件名包含 '_f' 且以 .png 结尾
    
    Example:
        >>> contact, frames = scan_frames_dir(Path("frames/"))
        >>> print(f"Contact Sheets: {len(contact)}, Frames: {len(frames)}")
        Contact Sheets: 100, Frames: 800
    """
    contact_sheets = []
    intermediate_frames = []
    
    if not frames_dir.exists():
        return contact_sheets, intermediate_frames
    
    for file_path in frames_dir.iterdir():
        if not file_path.is_file():
            continue
        
        filename = file_path.name
        
        if '_contact.' in filename:
            contact_sheets.append(file_path)
        elif '_f' in filename and filename.endswith('.png'):
            # 匹配 *_f00.png, *_f01.png 等中间帧文件
            intermediate_frames.append(file_path)
    
    return contact_sheets, intermediate_frames


def calculate_size(files: List[Path]) -> int:
    """
    计算文件总大小（字节）
    
    Args:
        files: 文件路径列表
    
    Returns:
        int: 总大小（字节）
    
    Example:
        >>> files = [Path("file1.png"), Path("file2.png")]
        >>> size = calculate_size(files)
        >>> print(f"{size / 1024 / 1024:.1f} MB")
        12.5 MB
    """
    total = 0
    for f in files:
        try:
            total += f.stat().st_size
        except:
            pass
    return total


def format_size(size_bytes: int) -> str:
    """
    格式化文件大小（人类可读）
    
    Args:
        size_bytes: 文件大小（字节）
    
    Returns:
        str: 格式化后的大小（B/KB/MB）
    
    Example:
        >>> print(format_size(1024))
        1.0 KB
        >>> print(format_size(1024 * 1024 * 5))
        5.0 MB
    """
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"


def main():
    """
    主函数：执行表情包中间帧清理
    
    流程：
    1. 解析命令行参数（--dry-run, --keep-all）
    2. 扫描 frames 目录，分类文件
    3. 计算文件大小和数量
    4. 根据参数执行操作：
       - --keep-all: 跳过清理
       - --dry-run: 预览删除操作（不实际删除）
       - 默认: 删除中间帧，保留 Contact Sheet
    5. 打印统计信息
    
    参数：
        --dry-run: 仅预览，不实际删除
        --keep-all: 保留所有文件（跳过清理）
    
    输出统计：
        - Contact Sheets 数量和大小
        - Intermediate Frames 数量和大小
        - 删除的文件数量
        - 释放的磁盘空间
    
    Example:
        # 预览删除操作
        $ python _08_cleanup_frames.py --dry-run
        [DRY RUN] Would delete 800 files
        [DRY RUN] Would free 1.2 GB
        
        # 实际删除
        $ python _08_cleanup_frames.py
        Deleted: 800 files
        Freed: 1.2 GB
    """
    parser = argparse.ArgumentParser(description='表情包中间帧清理')
    parser.add_argument('--dry-run', action='store_true', help='仅预览，不实际删除')
    parser.add_argument('--keep-all', action='store_true', help='保留所有文件（跳过清理）')
    args = parser.parse_args()
    
    frames_dir = get_sticker_frames_dir()
    
    print("=" * 60)
    print("Sticker Frames Cleanup")
    print("=" * 60)
    print(f"  Frames directory: {frames_dir}")
    
    if args.keep_all:
        print("\n⏭️  --keep-all 指定，跳过清理")
        return
    
    if not frames_dir.exists():
        print(f"\n⚠️  Frames directory not found: {frames_dir}")
        return
    
    # 扫描文件
    print("\n[1/2] Scanning frames directory...")
    contact_sheets, intermediate_frames = scan_frames_dir(frames_dir)
    
    contact_size = calculate_size(contact_sheets)
    intermediate_size = calculate_size(intermediate_frames)
    
    print(f"      Contact Sheets: {len(contact_sheets)} files ({format_size(contact_size)})")
    print(f"      Intermediate Frames: {len(intermediate_frames)} files ({format_size(intermediate_size)})")
    
    if not intermediate_frames:
        print("\n✅ No intermediate frames to clean up.")
        return
    
    # 删除中间帧
    print("\n[2/2] Cleaning up intermediate frames...")
    
    if args.dry_run:
        print(f"      [DRY RUN] Would delete {len(intermediate_frames)} files")
        print(f"      [DRY RUN] Would free {format_size(intermediate_size)}")
        
        # 显示前 10 个文件作为示例
        print("\n      Sample files to delete:")
        for f in intermediate_frames[:10]:
            print(f"        - {f.name}")
        if len(intermediate_frames) > 10:
            print(f"        ... and {len(intermediate_frames) - 10} more")
    else:
        deleted_count = 0
        deleted_size = 0
        
        for file_path in intermediate_frames:
            try:
                size = file_path.stat().st_size
                file_path.unlink()
                deleted_count += 1
                deleted_size += size
            except Exception as e:
                logger.warning(f"Failed to delete {file_path}: {e}")
        
        print(f"      Deleted: {deleted_count} files")
        print(f"      Freed: {format_size(deleted_size)}")
    
    # 最终统计
    print("\n" + "=" * 60)
    if args.dry_run:
        print("DRY RUN complete. No files were deleted.")
        print("Run without --dry-run to actually delete files.")
    else:
        remaining_contact, remaining_frames = scan_frames_dir(frames_dir)
        remaining_size = calculate_size(remaining_contact)
        print(f"✅ Cleanup complete.")
        print(f"   Remaining: {len(remaining_contact)} Contact Sheets ({format_size(remaining_size)})")


if __name__ == '__main__':
    main()
