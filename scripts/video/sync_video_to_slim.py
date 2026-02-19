#!/usr/bin/env python3
"""
sync_video_to_slim.py
将 enriched_full.jsonl 中的视频 caption/summary 同步到 enriched_slim.jsonl

同步的字段：
- video_summary
- video_keyframes (包含每帧的 caption)
- video_voice_to_text
- video_emotion_tags
- video_content_type
"""
import json
import sys
from pathlib import Path
from tqdm import tqdm

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts._common.path_utils import get_timeline_out


def main():
    timeline_out = get_timeline_out()
    full_file = timeline_out / "enriched_full.jsonl"
    slim_file = timeline_out / "enriched_slim.jsonl"
    
    print("=" * 60)
    print("Sync Video Fields from Full to Slim")
    print("=" * 60)
    print(f"  Full: {full_file}")
    print(f"  Slim: {slim_file}")
    
    if not full_file.exists():
        print(f"❌ Error: {full_file} not found")
        sys.exit(1)
    
    # 从 full 加载视频数据
    print("\n[1/3] Loading video data from full...")
    video_data = {}
    with full_file.open('r', encoding='utf-8') as f:
        for line in f:
            if not line.strip():
                continue
            record = json.loads(line)
            if record.get('modality') == 'video':
                msg_uid = record.get('msg_uid')
                video_data[msg_uid] = {
                    'video_summary': record.get('video_summary', ''),
                    'video_keyframes': record.get('video_keyframes', []),
                    'video_voice_to_text': record.get('video_voice_to_text', ''),
                    'video_emotion_tags': record.get('video_emotion_tags', []),
                    'video_content_type': record.get('video_content_type', 'TYPE_C_NORMAL'),
                }
    print(f"      Found {len(video_data)} video records")
    
    # 统计 slim 行数
    with slim_file.open('r', encoding='utf-8') as f:
        total_lines = sum(1 for _ in f)
    
    # 更新 slim
    print("\n[2/3] Updating slim...")
    temp_file = slim_file.with_suffix('.tmp')
    updated_count = 0
    
    with slim_file.open('r', encoding='utf-8') as fin, \
         temp_file.open('w', encoding='utf-8') as fout:
        for line in tqdm(fin, total=total_lines, desc="同步视频字段"):
            if not line.strip():
                continue
            record = json.loads(line)
            msg_uid = record.get('msg_uid')
            
            if msg_uid in video_data:
                # 更新视频字段
                record.update(video_data[msg_uid])
                updated_count += 1
            
            fout.write(json.dumps(record, ensure_ascii=False) + '\n')
    
    # 替换原文件
    print("\n[3/3] Replacing slim file...")
    temp_file.replace(slim_file)
    
    print(f"\n✅ Done. Updated {updated_count} video records in slim.")


if __name__ == "__main__":
    main()
