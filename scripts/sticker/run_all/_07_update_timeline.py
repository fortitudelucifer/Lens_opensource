#!/usr/bin/env python3
"""
表情包时间轴更新步骤

功能：
- 将表情包处理结果合并到主时间轴
- 更新 enriched_full.jsonl（完整版，包含所有字段）
- 更新 enriched_slim.jsonl（精简版，仅保留 LLM RAG 所需字段）
- 支持增量更新（如果时间轴已存在）
- 支持从零创建（如果时间轴不存在）

处理流程：
1. 加载表情包处理结果（sticker_merged_final.jsonl）
2. 确定输入源：
   - 如果 enriched_full.jsonl 存在 → 增量更新
   - 否则从 P1_messages_raw.jsonl 创建新时间轴
3. 对每条消息：
   a. 如果 msg_uid 匹配表情包数据 → 合并字段
   b. 写入完整版（所有字段）
   c. 写入精简版（仅保留关键字段）
4. 原子替换原文件（使用 .tmp 临时文件）
5. 打印统计信息

字段映射策略：
- **完整版（enriched_full.jsonl）**：
  * 保留所有表情包字段（sticker_*）
  * 用于数据分析、调试、回溯
  
- **精简版（enriched_slim.jsonl）**：
  * 仅保留 LLM RAG 所需字段：
    - sticker_summary: 压缩摘要（优先）
    - sticker_caption: 原始描述（备用）
    - sticker_ocr_text: OCR 文字
    - sticker_class: 分类（静态/动图）
    - sticker_content_type: 内容类型（NSFW/Gore/Normal）
    - sticker_is_animated: 是否动图
    - sticker_intent: 意图标签
    - sticker_intent_confidence: 意图置信度
  * 减少 Token 消耗，提升 RAG 效率

增量更新机制：
- 如果时间轴已存在，直接在原有基础上更新
- 保留其他模态的字段（image_*, voice_*, video_*）
- 仅更新 sticker_* 字段
- 支持多次运行（幂等性）

输入：
- artifacts/after_merge/sticker/sticker_merged_final.jsonl: 表情包处理结果
- timeline_out/enriched_full.jsonl: 现有时间轴（可选）
- raw/P1_messages_raw.jsonl: 原始消息（如果时间轴不存在）

输出：
- timeline_out/enriched_full.jsonl: 完整版时间轴
- timeline_out/enriched_slim.jsonl: 精简版时间轴

依赖：
- scripts/_common/path_utils.py: 路径工具

使用示例：
    python scripts/sticker/run_all/_07_update_timeline.py

输出统计：
- 更新的表情包消息数量
- 输出文件路径

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
    get_sticker_after_merge, get_timeline_out, get_messages_path
)


def load_sticker_data(merged_file: Path) -> dict:
    """
    加载表情包处理结果，以 msg_uid 为索引
    
    Args:
        merged_file: 表情包合并文件路径（sticker_merged_final.jsonl）
    
    Returns:
        dict: {msg_uid: record} 映射
    
    Example:
        >>> data = load_sticker_data(Path("sticker_merged_final.jsonl"))
        >>> print(len(data))
        1234
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


def merge_sticker_to_full(msg: dict, sticker_data: dict) -> dict:
    """
    将表情包处理结果合并到完整版消息
    
    Args:
        msg: 原始消息记录
        sticker_data: 表情包数据字典（{msg_uid: record}）
    
    Returns:
        dict: 合并后的消息记录（包含所有 sticker_* 字段）
    
    字段映射：
        - 下载信息：sticker_url, sticker_file_sha256, sticker_http_status, sticker_bytes
        - 格式信息：sticker_detected_format, sticker_content_type_reported, sticker_mismatch
        - QC 信息：sticker_decode_ok, sticker_width, sticker_height
        - 分类信息：sticker_class, sticker_is_animated, sticker_n_frames
        - 产物路径：sticker_thumb_path, sticker_contact_sheet_path
        - Triage 信息：sticker_content_type, sticker_max_nsfw_score, sticker_is_sensitive
        - Caption 信息：sticker_caption, sticker_ocr_text, sticker_expert_used
        - 意图信息：sticker_intent, sticker_intent_confidence, sticker_summary
    
    Example:
        >>> msg = {"msg_uid": "123", "text_raw": "..."}
        >>> sticker_data = {"123": {"caption": "笑脸表情", ...}}
        >>> merged = merge_sticker_to_full(msg, sticker_data)
        >>> print(merged.get("sticker_caption"))
        笑脸表情
    """
    msg_uid = msg.get('msg_uid', '')
    if msg_uid not in sticker_data:
        return msg
    
    sticker = sticker_data[msg_uid]
    
    # 下载信息
    msg['sticker_url'] = sticker.get('url', '')
    msg['sticker_file_sha256'] = sticker.get('file_sha256', '')
    msg['sticker_http_status'] = sticker.get('http_status')
    msg['sticker_bytes'] = sticker.get('bytes', 0)
    
    # 格式信息
    msg['sticker_detected_format'] = sticker.get('detected_format', '')
    msg['sticker_content_type_reported'] = sticker.get('content_type_reported', '')
    msg['sticker_mismatch'] = sticker.get('mismatch', False)
    msg['sticker_final_path'] = sticker.get('final_path', '')
    
    # QC 信息
    msg['sticker_decode_ok'] = sticker.get('decode_ok', False)
    msg['sticker_width'] = sticker.get('width')
    msg['sticker_height'] = sticker.get('height')
    
    # 分类信息
    msg['sticker_class'] = sticker.get('sticker_class', '')
    msg['sticker_is_animated'] = sticker.get('is_animated', False)
    msg['sticker_n_frames'] = sticker.get('n_frames', 1)
    
    # 产物路径
    msg['sticker_thumb_path'] = sticker.get('thumb_path', '')
    msg['sticker_contact_sheet_path'] = sticker.get('contact_sheet_path', '')
    
    # Triage 信息
    msg['sticker_content_type'] = sticker.get('content_type', 'TYPE_C_NORMAL')
    msg['sticker_max_nsfw_score'] = sticker.get('max_nsfw_score', 0.0)
    msg['sticker_is_sensitive'] = sticker.get('is_sensitive', False)
    
    # Caption 信息
    msg['sticker_caption'] = sticker.get('caption', '')
    msg['sticker_ocr_text'] = sticker.get('ocr_text', '')
    msg['sticker_expert_used'] = sticker.get('expert_used', '')
    
    # 意图信息
    msg['sticker_intent'] = sticker.get('intent', '')
    msg['sticker_intent_confidence'] = sticker.get('intent_confidence', 0.0)
    msg['sticker_summary'] = sticker.get('sticker_summary', '')
    
    return msg


def merge_sticker_to_slim(msg: dict, sticker_data: dict) -> dict:
    """
    将表情包处理结果合并到精简版消息（用于 LLM RAG）
    
    Args:
        msg: 原始消息记录
        sticker_data: 表情包数据字典（{msg_uid: record}）
    
    Returns:
        dict: 合并后的消息记录（仅保留 LLM RAG 所需字段）
    
    精简字段（减少 Token 消耗）：
        - sticker_summary: 压缩摘要（优先使用）
        - sticker_caption: 原始描述（备用）
        - sticker_ocr_text: OCR 文字
        - sticker_class: 分类（静态/动图）
        - sticker_content_type: 内容类型（NSFW/Gore/Normal）
        - sticker_is_animated: 是否动图
        - sticker_intent: 意图标签
        - sticker_intent_confidence: 意图置信度
    
    设计原则：
        - 优先使用压缩后的摘要（sticker_summary）
        - 保留关键分类信息（便于过滤和检索）
        - 去除技术细节（URL、SHA256、路径等）
        - 减少 Token 消耗，提升 RAG 效率
    
    Example:
        >>> msg = {"msg_uid": "123", "text_raw": "..."}
        >>> sticker_data = {"123": {"sticker_summary": "表达开心", ...}}
        >>> slim = merge_sticker_to_slim(msg, sticker_data)
        >>> print(slim.get("sticker_summary"))
        表达开心
    """
    msg_uid = msg.get('msg_uid', '')
    if msg_uid not in sticker_data:
        return msg
    
    sticker = sticker_data[msg_uid]
    
    # 压缩摘要（优先使用）
    msg['sticker_summary'] = sticker.get('sticker_summary', '')
    
    # 描述（原始 caption，作为备用）
    msg['sticker_caption'] = sticker.get('caption', '')
    msg['sticker_ocr_text'] = sticker.get('ocr_text', '')
    
    # 分类
    msg['sticker_class'] = sticker.get('sticker_class', '')
    msg['sticker_content_type'] = sticker.get('content_type', 'TYPE_C_NORMAL')
    msg['sticker_is_animated'] = sticker.get('is_animated', False)
    
    # 意图
    msg['sticker_intent'] = sticker.get('intent', '')
    msg['sticker_intent_confidence'] = sticker.get('intent_confidence', 0.0)
    
    return msg


def main():
    """
    主函数：执行表情包时间轴更新
    
    流程：
    1. 加载表情包处理结果（sticker_merged_final.jsonl）
    2. 确定输入源：
       - 如果 enriched_full.jsonl 存在 → 增量更新
       - 否则从 P1_messages_raw.jsonl 创建新时间轴
    3. 对每条消息：
       - 如果 msg_uid 匹配表情包数据 → 合并字段
       - 写入完整版（所有字段）
       - 写入精简版（仅保留关键字段）
    4. 原子替换原文件（使用 .tmp 临时文件）
    5. 打印统计信息
    
    增量更新机制：
        - 如果时间轴已存在，直接在原有基础上更新
        - 保留其他模态的字段（image_*, voice_*, video_*）
        - 仅更新 sticker_* 字段
        - 支持多次运行（幂等性）
    
    输出统计：
        - 更新的表情包消息数量
        - 输出文件路径
    
    Raises:
        SystemExit: 如果 sticker_merged_final.jsonl 不存在
    """
    print("=" * 60)
    print("Sticker Timeline Update")
    print("=" * 60)
    
    # 输入输出路径
    sticker_after = get_sticker_after_merge()
    timeline_out = get_timeline_out()
    messages_file = get_messages_path()
    
    timeline_out.mkdir(parents=True, exist_ok=True)
    
    merged_file = sticker_after / "sticker_merged_final.jsonl"
    full_file = timeline_out / "enriched_full.jsonl"
    slim_file = timeline_out / "enriched_slim.jsonl"
    
    print(f"  Messages: {messages_file}")
    print(f"  Sticker Data: {merged_file}")
    print(f"  Output Full: {full_file}")
    print(f"  Output Slim: {slim_file}")
    
    if not merged_file.exists():
        print(f"\n❌ Error: {merged_file} not found. Run _06_merge_engine.py first.")
        sys.exit(1)
    
    # 加载表情包处理结果
    print("\n[1/3] Loading sticker data...")
    sticker_data = load_sticker_data(merged_file)
    print(f"      Loaded {len(sticker_data)} sticker records")
    
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
    print("\n[3/3] Merging sticker data...")
    
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
            
            # 合并表情包数据
            if msg_uid in sticker_data:
                msg = merge_sticker_to_full(msg, sticker_data)
                updated_count += 1
            
            # 写入完整版
            f_full.write(json.dumps(msg, ensure_ascii=False) + '\n')
            
            # 创建精简版
            slim_msg = {k: v for k, v in msg.items() if not k.startswith('sticker_') or k in [
                'sticker_summary', 'sticker_caption', 'sticker_ocr_text', 'sticker_class', 
                'sticker_content_type', 'sticker_is_animated', 'sticker_intent', 'sticker_intent_confidence'
            ]}
            if msg_uid in sticker_data:
                slim_msg = merge_sticker_to_slim(slim_msg, sticker_data)
            f_slim.write(json.dumps(slim_msg, ensure_ascii=False) + '\n')
    
    # 替换原文件
    temp_full.replace(full_file)
    temp_slim.replace(slim_file)
    
    print(f"\n✅ Done.")
    print(f"   Updated {updated_count} sticker messages")
    print(f"   Full: {full_file}")
    print(f"   Slim: {slim_file}")


if __name__ == "__main__":
    main()
