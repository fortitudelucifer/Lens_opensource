"""
check_paths.py - 检查媒体文件路径有效性

用于验证 P1_messages_raw.jsonl 中的 media_path 是否指向有效文件
"""
import json
import os
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from _common.path_utils import get_root, get_messages_path, get_workspace_name


def check_paths():
    workspace = get_workspace_name()
    root = get_root()
    raw_dir = root / "raw"
    messages_path = get_messages_path()
    
    print(f"Workspace: {workspace}")
    print(f"Root: {root}")
    print(f"Checking media paths in {messages_path}...")
    
    if not messages_path.exists():
        print(f"ERROR: Messages file not found: {messages_path}")
        return
    
    missing = 0
    total_media = 0
    missing_files = []
    
    with open(messages_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
                
            if msg.get('modality') in ['image', 'doc', 'video', 'voice'] and msg.get('media_path'):
                total_media += 1
                old_path = msg['media_path']
                
                # Normalize: remove leading ./
                clean_path = old_path
                if clean_path.startswith('./'):
                    clean_path = clean_path[2:]
                
                # Construct candidate absolute path (assuming relative to RAW_DIR)
                abs_path = raw_dir / clean_path
                
                if not abs_path.exists():
                    missing += 1
                    if len(missing_files) < 10:  # Only store first 10
                        missing_files.append(str(abs_path))

    print(f"\nTotal media items: {total_media}")
    print(f"Missing files: {missing}")
    
    if missing_files:
        print("\nFirst 10 missing files:")
        for f in missing_files:
            print(f"  - {f}")
    
    # Check sample directories
    print("\nDirectory check:")
    for subdir in ['image', 'video', 'voice', 'sticker', 'file']:
        dir_path = raw_dir / subdir
        if dir_path.exists():
            items = list(dir_path.iterdir())
            print(f"  {subdir}/: {len(items)} items")
        else:
            print(f"  {subdir}/: NOT FOUND")


if __name__ == "__main__":
    check_paths()
