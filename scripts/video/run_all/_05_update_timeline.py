#!/usr/bin/env python3
"""
视频时间轴更新 - 将视频处理结果合并到主时间轴

功能：
- 将视频处理结果（merged_final.jsonl）合并到主时间轴
- 生成两个版本：enriched_full.jsonl（完整版）和 enriched_slim.jsonl（精简版）
- 支持增量更新（如果时间轴已存在，则更新；否则从原始消息创建）
- 优先使用压缩后的视频摘要（video_summary）

处理流程：
1. 加载视频处理结果（video_merged_final.jsonl），以 msg_uid 为索引
2. 确定输入源：
   - 如果 enriched_full.jsonl 已存在，则更新它
   - 否则从 P1_messages_raw.jsonl 创建新时间轴
3. 逐条消息处理：
   - 如果 msg_uid 匹配视频数据，合并视频字段
   - 否则保持原样
4. 输出两个版本：
   - enriched_full.jsonl：包含所有视频字段（用于分析）
   - enriched_slim.jsonl：只包含关键字段（用于 LLM RAG）

输入：
- artifacts/after_merge/video/video_merged_final.jsonl
  * msg_uid, video_metadata, transcription, emotion
  * video_understanding, video_summary, keyframes
  * content_type, triage_confidence, audit
- raw/P1_messages_raw.jsonl（如果时间轴不存在）
  * msg_uid, ts, speaker, type, modality, text_raw
- timeline_out/enriched_full.jsonl（如果已存在，则更新）

输出：
- timeline_out/enriched_full.jsonl（完整版）
  * 原始消息字段 + 所有视频字段
  * video_metadata, video_voice_to_text, video_asr_engine, video_asr_segments
  * video_emotion_tags, video_event_tags, video_trigger_reasons, video_voice_analysis
  * video_summary, video_events, video_atmosphere, video_intent
  * video_keyframes, video_content_type, video_triage_confidence, video_audit
- timeline_out/enriched_slim.jsonl（精简版）
  * 原始消息字段 + 关键视频字段
  * video_voice_to_text, video_summary（限制500字符）
  * video_emotion_tags, video_atmosphere, video_intent, video_content_type

依赖：
- scripts/_common/path_utils.py (get_video_after_merge, get_timeline_out, get_messages_path)

使用示例：
    # 完整处理（更新时间轴）
    python scripts/video/run_all/_05_update_timeline.py
    
    # 如果时间轴不存在，会从原始消息创建
    python scripts/video/run_all/_05_update_timeline.py

字段映射说明：
- 完整版（enriched_full.jsonl）：
  * video_metadata: 元数据（duration_sec, resolution, fps, has_audio）
  * video_voice_to_text: 转写文本（punct_text）
  * video_asr_engine: ASR 引擎（funasr/whisper）
  * video_asr_segments: 转写分段
  * video_emotion_tags: 情绪标签（happy, sad, angry等）
  * video_event_tags: 事件标签（music, applause等）
  * video_trigger_reasons: 情绪触发原因
  * video_voice_analysis: 语音分析（音调、语速等）
  * video_summary: 视频摘要（优先使用压缩后的）
  * video_events: 事件列表
  * video_atmosphere: 氛围（欢乐/悲伤/紧张/平静）
  * video_intent: 意图（分享日常/展示成果/记录瞬间）
  * video_keyframes: 关键帧列表（frame_id, timestamp_sec, caption）
  * video_content_type: 内容类型（TYPE_A_NSFW/TYPE_B_GORE/TYPE_C_NORMAL/TYPE_D_DOC）
  * video_triage_confidence: 分类置信度
  * video_audit: 审计信息（模型版本、参数、合并时间）

- 精简版（enriched_slim.jsonl）：
  * video_voice_to_text: 转写文本
  * video_summary: 视频摘要（限制500字符）
  * video_emotion_tags: 情绪标签
  * video_atmosphere: 氛围
  * video_intent: 意图
  * video_content_type: 内容类型

作者：[Author]
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
    get_video_after_merge, get_timeline_out, get_messages_path
)


def load_video_data(merged_file: Path) -> dict:
    """
    加载视频处理结果，以 msg_uid 为索引
    
    Args:
        merged_file: 视频合并文件路径（video_merged_final.jsonl）
    
    Returns:
        字典：msg_uid -> video_record
    
    Example:
        >>> merged_file = Path("artifacts/after_merge/video/video_merged_final.jsonl")
        >>> video_data = load_video_data(merged_file)
        >>> print(len(video_data))
        150
        >>> print(video_data["msg_123"]["video_summary"])
        "开始：人物在室内→过程：人物移动→结束：人物离开"
    """
    data = {}
    if not merged_file.exists():
        return data
    
    with merged_file.open('r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                record = json.loads(line)
                msg_uid = record.get('msg_uid', '')
                if msg_uid:
                    data[msg_uid] = record
    return data


def merge_video_to_full(msg: dict, video_data: dict) -> dict:
    """
    将视频处理结果合并到完整版消息
    
    合并字段：
    - video_metadata: 元数据（duration_sec, resolution, fps, has_audio）
    - video_voice_to_text: 转写文本
    - video_asr_engine: ASR 引擎
    - video_asr_segments: 转写分段
    - video_emotion_tags: 情绪标签
    - video_event_tags: 事件标签
    - video_trigger_reasons: 情绪触发原因
    - video_voice_analysis: 语音分析
    - video_summary: 视频摘要（优先使用压缩后的）
    - video_events: 事件列表
    - video_atmosphere: 氛围
    - video_intent: 意图
    - video_keyframes: 关键帧列表
    - video_content_type: 内容类型
    - video_triage_confidence: 分类置信度
    - video_audit: 审计信息
    
    Args:
        msg: 原始消息记录
        video_data: 视频数据字典（msg_uid -> video_record）
    
    Returns:
        合并后的消息记录
    
    Example:
        >>> msg = {"msg_uid": "msg_123", "text_raw": "发了一个视频"}
        >>> video_data = {"msg_123": {"video_summary": "...", "transcription": {...}}}
        >>> merged = merge_video_to_full(msg, video_data)
        >>> print(merged["video_summary"])
        "开始：人物在室内→过程：人物移动→结束：人物离开"
    """
    msg_uid = msg.get('msg_uid', '')
    if msg_uid not in video_data:
        return msg
    
    video = video_data[msg_uid]
    
    # 视频元数据
    msg['video_metadata'] = video.get('metadata', {})
    
    # 转写结果
    transcription = video.get('transcription', {})
    msg['video_voice_to_text'] = transcription.get('punct_text', '')
    msg['video_asr_engine'] = transcription.get('engine', '')
    msg['video_asr_segments'] = transcription.get('segments', [])
    
    # 情绪分析
    emotion = video.get('emotion', {})
    sensevoice = emotion.get('sensevoice', {})
    msg['video_emotion_tags'] = sensevoice.get('emotion_tags', [])
    msg['video_event_tags'] = sensevoice.get('event_tags', [])
    msg['video_trigger_reasons'] = emotion.get('trigger_reasons', [])
    msg['video_voice_analysis'] = emotion.get('voice_analysis', {})
    
    # 视频理解
    understanding = video.get('video_understanding', {})
    # 优先使用压缩后的 video_summary，否则使用 video_understanding.summary
    if video.get('video_summary'):
        msg['video_summary'] = video.get('video_summary', '')
        msg['video_is_compressed'] = video.get('is_compressed', False)
        msg['video_compression_ratio'] = video.get('compression_ratio', 0)
    else:
        msg['video_summary'] = understanding.get('summary', '')
        msg['video_is_compressed'] = False
    msg['video_events'] = understanding.get('events', [])
    
    # 氛围和意图（从压缩数据中获取）
    msg['video_atmosphere'] = video.get('video_atmosphere', '')
    msg['video_intent'] = video.get('video_intent', '')
    
    # 关键帧
    msg['video_keyframes'] = video.get('keyframes', [])
    
    # 内容分类
    msg['video_content_type'] = video.get('content_type', 'TYPE_C_NORMAL')
    msg['video_triage_confidence'] = video.get('triage_confidence', 0.0)
    
    # 审计信息
    msg['video_audit'] = video.get('audit', {})
    
    return msg


def merge_video_to_slim(msg: dict, video_data: dict) -> dict:
    """
    将视频处理结果合并到精简版消息（用于 LLM RAG）
    
    只保留关键字段：
    - video_voice_to_text: 转写文本
    - video_summary: 视频摘要（限制500字符）
    - video_emotion_tags: 情绪标签
    - video_atmosphere: 氛围
    - video_intent: 意图
    - video_content_type: 内容类型
    
    Args:
        msg: 原始消息记录
        video_data: 视频数据字典（msg_uid -> video_record）
    
    Returns:
        合并后的精简消息记录
    
    Example:
        >>> msg = {"msg_uid": "msg_123", "text_raw": "发了一个视频"}
        >>> video_data = {"msg_123": {"video_summary": "...", "video_atmosphere": "欢乐"}}
        >>> slim = merge_video_to_slim(msg, video_data)
        >>> print(slim["video_atmosphere"])
        "欢乐"
    """
    msg_uid = msg.get('msg_uid', '')
    if msg_uid not in video_data:
        return msg
    
    video = video_data[msg_uid]
    
    # 转写文本
    transcription = video.get('transcription', {})
    msg['video_voice_to_text'] = transcription.get('punct_text', '')
    
    # 视频摘要
    # 优先使用压缩后的 video_summary，否则使用 video_understanding.summary
    if video.get('video_summary'):
        msg['video_summary'] = video.get('video_summary', '')[:500]  # 限制长度
    else:
        understanding = video.get('video_understanding', {})
        msg['video_summary'] = understanding.get('summary', '')[:500]  # 限制长度
    
    # 情绪标签
    emotion = video.get('emotion', {})
    sensevoice = emotion.get('sensevoice', {})
    msg['video_emotion_tags'] = sensevoice.get('emotion_tags', [])
    
    # 氛围和意图（精简版也需要，用于 RAG 检索）
    msg['video_atmosphere'] = video.get('video_atmosphere', '')
    msg['video_intent'] = video.get('video_intent', '')
    
    # 内容分类
    msg['video_content_type'] = video.get('content_type', 'TYPE_C_NORMAL')
    
    return msg


def main():
    """
    主函数：视频时间轴更新流程
    
    处理步骤：
    1. 加载视频处理结果（video_merged_final.jsonl）
    2. 确定输入源（enriched_full.jsonl 或 P1_messages_raw.jsonl）
    3. 逐条消息处理：
       - 如果 msg_uid 匹配视频数据，合并视频字段
       - 否则保持原样
    4. 输出两个版本：
       - enriched_full.jsonl（完整版）
       - enriched_slim.jsonl（精简版）
    5. 打印统计信息（更新的视频消息数）
    
    输入文件：
        - video_merged_final.jsonl（必需）
        - enriched_full.jsonl（如果存在，则更新；否则从原始消息创建）
        - P1_messages_raw.jsonl（如果时间轴不存在）
    
    输出文件：
        - enriched_full.jsonl（完整版）
        - enriched_slim.jsonl（精简版）
    
    Example:
        >>> python scripts/video/run_all/_05_update_timeline.py
        ============================================================
        Video Timeline Update
        ============================================================
          Messages: raw/P1_messages_raw.jsonl
          Video Data: artifacts/after_merge/video/video_merged_final.jsonl
          Output Full: timeline_out/enriched_full.jsonl
          Output Slim: timeline_out/enriched_slim.jsonl
        
        [1/3] Loading video data...
              Loaded 150 video records
        
        [2/3] Updating existing timeline: timeline_out/enriched_full.jsonl
        
        [3/3] Merging video data...
        更新时间轴: 100%|████████| 5000/5000 [00:10<00:00, 500.00it/s]
        
        ✅ Done.
           Updated 150 video messages
           Full: timeline_out/enriched_full.jsonl
           Slim: timeline_out/enriched_slim.jsonl
    """
    print("=" * 60)
    print("Video Timeline Update")
    print("=" * 60)
    
    # 输入输出路径
    video_after = get_video_after_merge()
    timeline_out = get_timeline_out()
    messages_file = get_messages_path()
    
    timeline_out.mkdir(parents=True, exist_ok=True)
    
    merged_file = video_after / "video_merged_final.jsonl"
    full_file = timeline_out / "enriched_full.jsonl"
    slim_file = timeline_out / "enriched_slim.jsonl"
    
    print(f"  Messages: {messages_file}")
    print(f"  Video Data: {merged_file}")
    print(f"  Output Full: {full_file}")
    print(f"  Output Slim: {slim_file}")
    
    if not merged_file.exists():
        print(f"\n❌ Error: {merged_file} not found. Run _04_merge_engine.py first.")
        sys.exit(1)
    
    # 加载视频处理结果
    print("\n[1/3] Loading video data...")
    video_data = load_video_data(merged_file)
    print(f"      Loaded {len(video_data)} video records")
    
    # 确定输入源：优先使用已有的 enriched_full.jsonl，否则使用原始消息
    if full_file.exists():
        input_file = full_file
        print(f"\n[2/3] Updating existing timeline: {input_file}")
    else:
        input_file = messages_file
        print(f"\n[2/3] Creating new timeline from: {input_file}")
    
    # 统计总行数
    with input_file.open('r', encoding='utf-8') as f:
        total_lines = sum(1 for _ in f)
    
    # 处理并输出
    print("\n[3/3] Merging video data...")
    
    updated_count = 0
    temp_full = full_file.with_suffix('.tmp')
    temp_slim = slim_file.with_suffix('.tmp')
    
    with input_file.open('r', encoding='utf-8') as fin, \
         temp_full.open('w', encoding='utf-8') as f_full, \
         temp_slim.open('w', encoding='utf-8') as f_slim:
        
        for line in tqdm(fin, total=total_lines, desc="更新时间轴", **tqdm_kwargs):
            if not line.strip():
                continue
            
            msg = json.loads(line)
            msg_uid = msg.get('msg_uid', '')
            
            # 合并视频数据
            if msg_uid in video_data:
                msg = merge_video_to_full(msg, video_data)
                updated_count += 1
            
            # 写入完整版
            f_full.write(json.dumps(msg, ensure_ascii=False) + '\n')
            
            # 创建精简版
            slim_msg = {k: v for k, v in msg.items() if not k.startswith('video_') or k in [
                'video_voice_to_text', 'video_summary', 'video_emotion_tags', 
                'video_content_type', 'video_atmosphere', 'video_intent'
            ]}
            if msg_uid in video_data:
                slim_msg = merge_video_to_slim(slim_msg, video_data)
            f_slim.write(json.dumps(slim_msg, ensure_ascii=False) + '\n')
    
    # 替换原文件
    temp_full.replace(full_file)
    temp_slim.replace(slim_file)
    
    print(f"\n✅ Done.")
    print(f"   Updated {updated_count} video messages")
    print(f"   Full: {full_file}")
    print(f"   Slim: {slim_file}")


if __name__ == "__main__":
    main()
