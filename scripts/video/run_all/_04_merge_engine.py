#!/usr/bin/env python3
"""
视频合并引擎 - 整合提取、转写、描述、压缩结果

功能：
- 合并视频的四个处理阶段数据（Extract + Transcribe + Caption + Compress）
- 生成统一的 merged_v2 Schema
- 支持压缩数据优先策略（使用压缩后的摘要替代原始描述）
- 生成质量报告（QC Report）

处理流程：
1. 加载四个输入文件：
   - video_extract_v1.jsonl（关键帧提取）
   - video_transcribe_v1.jsonl（音频转写 + 情绪检测）
   - video_caption_v1.jsonl（VLM 描述）
   - video_compressed.jsonl（压缩后的摘要，可选）
2. 按 file_name 匹配记录
3. 合并字段：
   - 基础字段：msg_uid, ts, speaker, type, modality
   - 元数据：duration_sec, resolution, fps, has_audio
   - 转写：transcription (punct_text, raw_text, engine)
   - 情绪：emotion (sensevoice, qwen2_audio)
   - 描述：video_summary (优先使用压缩后的摘要)
   - 关键帧：keyframes (frame_id, timestamp_sec, caption, content_type)
   - 分类：content_type, triage_confidence
4. 生成 QC 报告（统计信息、内容类型分布、处理详情）
5. 输出 merged_final.jsonl

输入：
- artifacts/before_merge/video/video_extract_v1.jsonl
  * file, video_sha256, keyframes, metadata
- artifacts/before_merge/video/video_transcribe_v1.jsonl
  * file, transcription, emotion
- artifacts/before_merge/video/video_caption_v1.jsonl
  * file, keyframe_captions, video_understanding, triage
- artifacts/before_merge/video/video_compressed.jsonl（可选）
  * media_path, video_summary, atmosphere, intent, compression_ratio

输出：
- artifacts/after_merge/video/video_merged_final.jsonl
  * 完整的合并记录（merged_v2 Schema）
- artifacts/before_merge/video/video_merged_qc_report.md
  * 质量报告（总视频数、有音频数、有转写数、内容类型分布等）

依赖：
- scripts/_common/path_utils.py (get_video_before_merge, get_video_after_merge)
- scripts/_common/schema_utils.py (build_common_header, reorder_record)

使用示例：
    # 完整处理（使用压缩数据）
    python scripts/video/run_all/_04_merge_engine.py
    
    # 如果没有压缩数据，会自动使用原始 caption
    python scripts/video/run_all/_04_merge_engine.py

合并策略：
- 压缩数据优先：如果存在 video_compressed.jsonl，使用压缩后的 video_summary
- 原始数据兜底：如果没有压缩数据，使用 video_understanding.summary
- 关键帧合并：将 extract 的 keyframes 与 caption 的 keyframe_captions 按 frame_id 匹配
- 转写合并：将 transcribe 的 transcription 和 emotion 整合到最终记录

QC 报告内容：
- 概览：总视频数、总时长、有音频数、有转写数、有情绪分析数、平均关键帧数
- 内容类型分布：TYPE_A_NSFW, TYPE_B_GORE, TYPE_C_NORMAL, TYPE_D_DOC
- 处理详情：前10个视频的详细信息（文件名、时长、帧数、类型）

作者：forcifer
更新于：2026-02-02
"""
import os
import sys
import json
from pathlib import Path
from datetime import datetime
from tqdm import tqdm

# 确保 tqdm 输出到 stderr 以便实时显示
tqdm_kwargs = {"file": sys.stderr, "dynamic_ncols": True}

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts._common.path_utils import (
    get_video_before_merge, get_video_after_merge, load_video_config
)
from scripts._common.schema_utils import (
    SCHEMA_VERSION,
    build_common_header,
    reorder_record,
)

# ========== 加载配置 ==========
video_config = load_video_config()


def merge_video_records(
    extract_record: dict,
    transcribe_record: dict,
    caption_record: dict,
    compressed_record: dict = None
) -> dict:
    """
    合并单个视频的所有记录
    
    合并策略：
    1. 使用 build_common_header 构建公共字段（msg_uid, ts, speaker等）
    2. 添加视频特定字段（file, video_sha256, metadata）
    3. 整合转写和情绪数据
    4. 优先使用压缩后的摘要（如果存在）
    5. 合并关键帧数据（extract.keyframes + caption.keyframe_captions）
    6. 添加审计信息（模型版本、参数、合并时间）
    
    Args:
        extract_record: 提取记录（keyframes, metadata）
        transcribe_record: 转写记录（transcription, emotion）
        caption_record: 描述记录（keyframe_captions, video_understanding, triage）
        compressed_record: 压缩记录（可选，video_summary, atmosphere, intent）
    
    Returns:
        合并后的记录（merged_v2 Schema）
        
    Example:
        >>> extract = {"file": "video1.mp4", "keyframes": [...]}
        >>> transcribe = {"file": "video1.mp4", "transcription": {...}}
        >>> caption = {"file": "video1.mp4", "keyframe_captions": [...]}
        >>> compressed = {"media_path": "raw/video/video1.mp4", "video_summary": "..."}
        >>> merged = merge_video_records(extract, transcribe, caption, compressed)
        >>> print(merged["video_summary"])
        "开始：人物在室内→过程：人物移动→结束：人物离开"
    """
    file_name = extract_record.get('file', '')
    
    # 使用 build_common_header 构建公共字段
    merged = build_common_header(
        raw_record=extract_record,
        schema_version=SCHEMA_VERSION,
        modality='video',
    )
    
    # 添加 video 特定字段
    merged['file'] = file_name
    merged['video_sha256'] = extract_record.get('video_sha256', '')
    
    # 元数据
    merged['metadata'] = extract_record.get('metadata', {})
    
    # 转写结果
    merged['transcription'] = transcribe_record.get('transcription', {})
    
    # 情绪分析
    merged['emotion'] = transcribe_record.get('emotion', {})
    
    # 如果有压缩数据，使用压缩后的摘要
    if compressed_record:
        # 使用压缩后的视频摘要
        merged['video_summary'] = compressed_record.get('video_summary', '')
        merged['video_atmosphere'] = compressed_record.get('atmosphere', '')
        merged['video_intent'] = compressed_record.get('intent', '')
        merged['compression_ratio'] = compressed_record.get('compression_ratio', 0)
        merged['is_compressed'] = True
        
        # 保留原始的 video_understanding 用于参考
        merged['video_understanding'] = caption_record.get('video_understanding', {})
    else:
        # 没有压缩数据，使用原始的 video_understanding
        video_understanding = caption_record.get('video_understanding', {})
        merged['video_understanding'] = video_understanding
        # 从 video_understanding 中提取 summary
        if isinstance(video_understanding, dict):
            merged['video_summary'] = video_understanding.get('summary', '')
        merged['is_compressed'] = False
    
    # 关键帧
    keyframes = extract_record.get('keyframes', [])
    keyframe_captions = {
        kc.get('frame_id'): kc 
        for kc in caption_record.get('keyframe_captions', [])
    }
    
    merged_keyframes = []
    for kf in keyframes:
        frame_id = kf.get('frame_id')
        caption_info = keyframe_captions.get(frame_id, {})
        merged_keyframes.append({
            **kf,
            'content_type': caption_info.get('content_type', 'TYPE_C_NORMAL'),
            'caption': caption_info.get('caption', ''),
            'expert_used': caption_info.get('expert_used', 'default_expert'),
            'evidence_spans': caption_info.get('evidence_spans', [])
        })
    
    merged['keyframes'] = merged_keyframes
    
    # 整体分类
    triage = caption_record.get('triage', {})
    merged['content_type'] = triage.get('content_type', 'TYPE_C_NORMAL')
    merged['triage_confidence'] = triage.get('confidence', 0)
    
    # 审计信息
    merged['audit'] = {
        'model_versions': {
            'vlm': caption_record.get('video_understanding', {}).get('model', ''),
            'asr': transcribe_record.get('transcription', {}).get('engine', ''),
        },
        'extraction_params': extract_record.get('extraction_params', {}),
        'generation_params': caption_record.get('generation_params', {}),
        'merged_at': datetime.now().isoformat()
    }
    
    # 使用 reorder_record 重排字段顺序
    return reorder_record(merged, 'video')


def generate_qc_report(merged_records: list, output_path: Path):
    """
    生成质量报告（QC Report）
    
    报告内容：
    1. 概览统计：
       - 总视频数、总时长
       - 有音频数、有转写数、有情绪分析数
       - 总关键帧数、平均关键帧数
    2. 内容类型分布：
       - TYPE_A_NSFW, TYPE_B_GORE, TYPE_C_NORMAL, TYPE_D_DOC
       - 每种类型的数量和占比
    3. 处理详情：
       - 前10个视频的详细信息（文件名、时长、帧数、类型）
    
    Args:
        merged_records: 合并后的记录列表
        output_path: 输出路径（Markdown 文件）
    
    Example:
        >>> merged_records = [...]
        >>> output_path = Path("artifacts/before_merge/video/video_merged_qc_report.md")
        >>> generate_qc_report(merged_records, output_path)
        # 生成报告文件
    """
    total = len(merged_records)
    
    # 统计
    has_audio = sum(1 for r in merged_records if r.get('metadata', {}).get('has_audio'))
    has_transcript = sum(1 for r in merged_records if r.get('transcription', {}).get('punct_text'))
    has_emotion = sum(1 for r in merged_records if r.get('emotion', {}).get('sensevoice'))
    
    content_types = {}
    for r in merged_records:
        ct = r.get('content_type', 'UNKNOWN')
        content_types[ct] = content_types.get(ct, 0) + 1
    
    total_keyframes = sum(len(r.get('keyframes', [])) for r in merged_records)
    avg_keyframes = total_keyframes / total if total > 0 else 0
    
    total_duration = sum(r.get('metadata', {}).get('duration_sec', 0) for r in merged_records)
    
    # 防止除零
    pct = lambda x: f"{x/total*100:.1f}" if total > 0 else "0.0"
    
    report = f"""# 视频合并质量报告

生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## 概览

| 指标 | 数值 |
|------|------|
| 总视频数 | {total} |
| 总时长 | {total_duration:.1f} 秒 ({total_duration/60:.1f} 分钟) |
| 有音频 | {has_audio} ({pct(has_audio)}%) |
| 有转写 | {has_transcript} ({pct(has_transcript)}%) |
| 有情绪分析 | {has_emotion} ({pct(has_emotion)}%) |
| 总关键帧数 | {total_keyframes} |
| 平均关键帧/视频 | {avg_keyframes:.1f} |

## 内容类型分布

| 类型 | 数量 | 占比 |
|------|------|------|
"""
    
    for ct, count in sorted(content_types.items()):
        report += f"| {ct} | {count} | {pct(count)}% |\n"
    
    report += f"""
## 处理详情

"""
    
    for r in merged_records[:10]:  # 只显示前10个
        file_name = r.get('file', '')
        duration = r.get('metadata', {}).get('duration_sec', 0)
        kf_count = len(r.get('keyframes', []))
        ct = r.get('content_type', '')
        report += f"- **{file_name}**: {duration:.1f}s, {kf_count} 帧, {ct}\n"
    
    if total > 10:
        report += f"\n... 还有 {total - 10} 个视频\n"
    
    output_path.write_text(report, encoding='utf-8')


def main():
    """
    主函数：视频合并流程
    
    处理步骤：
    1. 加载配置和路径
    2. 读取四个输入文件（extract, transcribe, caption, compressed）
    3. 按 file_name 匹配记录
    4. 逐条合并记录（merge_video_records）
    5. 输出 merged_final.jsonl
    6. 生成 QC 报告
    
    输入文件：
        - video_extract_v1.jsonl（必需）
        - video_transcribe_v1.jsonl（可选）
        - video_caption_v1.jsonl（可选）
        - video_compressed.jsonl（可选，优先使用）
    
    输出文件：
        - video_merged_final.jsonl（合并结果）
        - video_merged_qc_report.md（质量报告）
    
    Example:
        >>> python scripts/video/run_all/_04_merge_engine.py
        ============================================================
        Video Merge Engine
        ============================================================
          Extract: artifacts/before_merge/video/video_extract_v1.jsonl
          Transcribe: artifacts/before_merge/video/video_transcribe_v1.jsonl
          Caption: artifacts/before_merge/video/video_caption_v1.jsonl
          Compressed: artifacts/before_merge/video/video_compressed.jsonl
          Output: artifacts/after_merge/video/video_merged_final.jsonl
        
        [1/2] Found 150 video records to merge.
        
        [2/2] Merging records...
        合并: 100%|████████| 150/150 [00:01<00:00, 100.00it/s]
        
        ✅ Done.
           Merged: artifacts/after_merge/video/video_merged_final.jsonl
           QC Report: artifacts/before_merge/video/video_merged_qc_report.md
    """
    print("=" * 60)
    print("Video Merge Engine")
    print("=" * 60)
    
    # 输入输出路径
    video_before = get_video_before_merge()
    video_after = get_video_after_merge()
    video_after.mkdir(parents=True, exist_ok=True)
    
    extract_file = video_before / "video_extract_v1.jsonl"
    transcribe_file = video_before / "video_transcribe_v1.jsonl"
    caption_file = video_before / "video_caption_v1.jsonl"
    compressed_file = video_before / "video_compressed.jsonl"  # 压缩后的数据
    
    output_file = video_after / "video_merged_final.jsonl"
    qc_report_file = video_before / "video_merged_qc_report.md"  # QC报告输出到 before_merge
    
    print(f"  Extract: {extract_file}")
    print(f"  Transcribe: {transcribe_file}")
    print(f"  Caption: {caption_file}")
    print(f"  Compressed: {compressed_file}")
    print(f"  Output: {output_file}")
    
    # 检查输入文件
    if not extract_file.exists():
        print(f"\n❌ Error: {extract_file} not found.")
        sys.exit(1)
    
    # 读取所有记录
    extract_records = {}
    with extract_file.open('r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                record = json.loads(line)
                extract_records[record.get('file', '')] = record
    
    transcribe_records = {}
    if transcribe_file.exists():
        with transcribe_file.open('r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    record = json.loads(line)
                    transcribe_records[record.get('file', '')] = record
    
    caption_records = {}
    if caption_file.exists():
        with caption_file.open('r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    record = json.loads(line)
                    caption_records[record.get('file', '')] = record
    
    # 读取压缩后的数据（如果存在）
    compressed_records = {}
    if compressed_file.exists():
        print(f"  ✅ Found compressed data: {compressed_file}")
        with compressed_file.open('r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    record = json.loads(line)
                    # 压缩数据使用 media_path 作为 key
                    media_path = record.get('media_path', '')
                    file_name = media_path.split('/')[-1] if media_path else ''
                    if file_name:
                        compressed_records[file_name] = record
        print(f"  ✅ Loaded {len(compressed_records)} compressed records")
    else:
        print(f"  ⚠️ No compressed data found, using original captions")
    
    total = len(extract_records)
    print(f"\n[1/2] Found {total} video records to merge.")
    
    # 合并记录
    print("\n[2/2] Merging records...")
    merged_records = []
    
    with output_file.open('w', encoding='utf-8') as f:
        for file_name in tqdm(extract_records.keys(), desc="合并", **tqdm_kwargs):
            extract_record = extract_records.get(file_name, {})
            transcribe_record = transcribe_records.get(file_name, {})
            caption_record = caption_records.get(file_name, {})
            compressed_record = compressed_records.get(file_name, None)
            
            merged = merge_video_records(
                extract_record,
                transcribe_record,
                caption_record,
                compressed_record
            )
            merged_records.append(merged)
            f.write(json.dumps(merged, ensure_ascii=False) + '\n')
    
    # 生成质量报告
    generate_qc_report(merged_records, qc_report_file)
    
    print(f"\n✅ Done.")
    print(f"   Merged: {output_file}")
    print(f"   QC Report: {qc_report_file}")


if __name__ == "__main__":
    main()
