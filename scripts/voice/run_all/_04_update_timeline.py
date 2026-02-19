#!/usr/bin/env python3
"""
时间轴更新步骤（语音）

功能：
- 将语音处理结果更新到时间轴文件
- 支持 Full 和 Slim 两个版本
- Full 版本保留完整元数据（分析/回溯用）
- Slim 版本精简关键信息（LLM RAG 用）
- 生成对齐审计报告

处理流程：
1. 加载语音合并结果（voice_merged_final.jsonl）
2. 确定输入源：
   - 如果 enriched_full.jsonl 存在，使用现有时间轴
   - 否则从原始消息（P1_messages_raw.jsonl）创建新时间轴
3. 对每条消息：
   - 如果是语音消息（modality=voice 或 type=34）
   - 提取文件名并查找对应的 ASR 结果
   - 更新 enriched_full.jsonl（完整版）
   - 更新 enriched_slim.jsonl（精简版）
4. 生成对齐审计报告（voice_alignment_audit.json）

输出设计：

**enriched_full.jsonl（完整版）**：
- 所有原始字段 + 完整的语音处理结果
- 包括：
  * 转写：voice_to_text, asr_engine, asr_raw_text
  * 情绪：emotion_tags, event_tags
  * 分析：voice_analysis（Qwen 深度分析）
  * 触发：trigger_reasons
  * 补丁：asr_patches

**enriched_slim.jsonl（精简版）**：
- 只保留关键信息：
  * text: 转写文本
  * emotion_tags: 情绪标签
  * emotion_desc: 情绪描述（如有）
  * subtext: 潜台词（如有）

字段映射策略：
- Full 版本：保留所有字段，用于深度分析
- Slim 版本：只保留 LLM RAG 需要的关键信息
- 支持新旧 schema 版本（merged_v2 和 merged_v3）

输入：
- artifacts/after_merge/voice/voice_merged_final.jsonl: 语音合并结果
- timeline_out/enriched_full.jsonl: 现有时间轴（Full）
- timeline_out/enriched_slim.jsonl: 现有时间轴（Slim）
- raw/P1_messages_raw.jsonl: 原始消息（如果时间轴不存在）

输出：
- timeline_out/enriched_full.jsonl: 更新后的时间轴（Full）
- timeline_out/enriched_slim.jsonl: 更新后的时间轴（Slim）
- artifacts/before_merge/voice/voice_alignment_audit.json: 对齐审计报告

依赖：
- scripts._common.path_utils: 路径工具
- scripts._common.anonymizer: 匿名化工具（已注释，保留原始数据）

使用示例：
    python scripts/voice/run_all/_04_update_timeline.py

注意事项：
- 确保先运行 _03_merge_engine.py
- 如果时间轴文件不存在，会从原始消息创建
- 更新过程中会创建临时文件，完成后替换原文件
- 审计报告包含未匹配的样本，用于质量检查

作者：forcifer
更新于：2026-02-02
"""
import json
import re
import sys
from pathlib import Path
from datetime import datetime
from tqdm import tqdm

# 确保 tqdm 输出到 stderr 以便实时显示
tqdm_kwargs = {"file": sys.stderr, "dynamic_ncols": True}

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts._common.path_utils import (
    PATHS, get_voice_before_merge, get_voice_after_merge, get_timeline_out, get_messages_path
)
from scripts._common.anonymizer import anonymize_message_text

# ========== 配置 ==========
# 支持新旧 schema 版本
SCHEMA_EXPECTED_NEW = "merged_v2"
SCHEMA_EXPECTED_OLD = "merged_v3"  # 旧版本，向后兼容

# 路径配置
MESSAGES_FILE = get_messages_path()
MERGED_ASR_FILE = get_voice_after_merge() / "voice_merged_final.jsonl"
TIMELINE_DIR = get_timeline_out()
VOICE_BEFORE_DIR = get_voice_before_merge()

# QC/审计文件输出到 before_merge/voice/
OUT_AUDIT = VOICE_BEFORE_DIR / "voice_alignment_audit.json"
OUT_FULL = TIMELINE_DIR / "enriched_full.jsonl"
OUT_SLIM = TIMELINE_DIR / "enriched_slim.jsonl"


def load_messages(filepath):
    """Load raw messages."""
    messages = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                messages.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return messages


def load_asr_merged(filepath):
    """
    Load merged ASR results keyed by media_path (new schema) or file (old schema).
    
    新 schema (merged_v2) 使用 media_path 作为关联键
    旧 schema (merged_v3) 使用 file 作为关联键
    """
    data = {}
    if not filepath.exists():
        print(f"Warning: {filepath} not found.")
        return data
    with open(filepath, "r", encoding="utf-8") as f:
        for idx, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                rec["_line_number"] = idx
                
                # 新 schema 使用 media_path，旧 schema 使用 file
                media_path = rec.get("media_path")
                file_key = rec.get("file")
                
                # 优先使用 media_path（新 schema）
                if media_path:
                    # 提取文件名作为 key
                    fn = extract_voice_filename(media_path)
                    if fn:
                        data[fn] = rec
                elif file_key:
                    # 旧 schema 使用 file
                    data[file_key] = rec
            except json.JSONDecodeError:
                continue
    return data


def extract_voice_filename(media_path):
    """Extract filename from media_path like './voice/xxx.mp3' or 'voice/xxx.mp3'."""
    if not media_path:
        return None
    match = re.search(r'(?:\.?/)?voice/([^/]+\.mp3)', media_path)
    if match:
        return match.group(1)
    if media_path.endswith('.mp3') and '/' not in media_path:
        return media_path
    return None


def main():
    print("=" * 60)
    print("Voice Timeline Update")
    print("=" * 60)
    print(f"  Messages: {MESSAGES_FILE}")
    print(f"  ASR Data: {MERGED_ASR_FILE}")
    print(f"  Output Dir: {TIMELINE_DIR}")
    
    print("\n[1/3] Loading merged ASR results...")
    asr_data = load_asr_merged(MERGED_ASR_FILE)
    print(f"      Loaded {len(asr_data)} ASR records.")
    
    # 确定输入源：优先使用已有的 enriched_full.jsonl，否则使用原始消息
    if OUT_FULL.exists():
        input_file = OUT_FULL
        print(f"\n[2/3] Updating existing timeline: {input_file}")
    else:
        input_file = MESSAGES_FILE
        print(f"\n[2/3] Creating new timeline from: {input_file}")
    
    print(f"      Loading messages from {input_file}...")
    messages = load_messages(input_file)
    print(f"      Loaded {len(messages)} messages.")
    
    # ========== Merge and Enrich ==========
    stats = {
        "messages_total": len(messages),
        "voice_total": 0,
        "voice_missing_media_path": 0,
        "voice_hit": 0,
        "voice_miss": 0,
        "voice_schema_mismatch": 0,
        "schema_expected": SCHEMA_EXPECTED_NEW,
    }
    examples = {
        "miss": [],
        "schema_mismatch": [],
    }
    
    TIMELINE_DIR.mkdir(parents=True, exist_ok=True)
    VOICE_BEFORE_DIR.mkdir(parents=True, exist_ok=True)
    
    # 使用临时文件，避免覆盖已有数据
    temp_full = OUT_FULL.with_suffix('.tmp')
    temp_slim = OUT_SLIM.with_suffix('.tmp')
    
    print("\n[3/3] Processing messages...")
    with temp_full.open("w", encoding="utf-8") as f_full, \
         temp_slim.open("w", encoding="utf-8") as f_slim:
        
        for msg in tqdm(messages, desc="更新时间轴", **tqdm_kwargs):
            modality = msg.get("modality", "")
            is_voice = (modality == "voice") or (msg.get("type") == 34)
            
            enriched_full = dict(msg)
            
            # 保留原始 text_raw，不在此处匿名化
            # 匿名化应该在生成 L2 训练数据时进行
            raw_text = msg.get("text_raw") or ""
            # 注释掉匿名化逻辑，保留原始数据
            # msg_type = msg.get("type")
            # anonymized_text = anonymize_message_text(raw_text, modality=modality, msg_type=msg_type)
            # enriched_full["text_raw"] = anonymized_text
            
            enriched_slim = {
                "msg_uid": msg.get("msg_uid"),
                "ts": msg.get("ts"),
                "time_local": msg.get("time_local"),
                "speaker": msg.get("speaker"),
                "modality": modality,
                "text": raw_text,  # 保留原始文本
            }
            
            # 注意：quote_text 字段由 linkfile 流水线处理并映射为 link_quote_text
            # 这里不再重复处理，避免字段冗余
            
            if is_voice:
                stats["voice_total"] += 1
                media_path = msg.get("media_path")
                
                if not media_path:
                    stats["voice_missing_media_path"] += 1
                else:
                    fn = extract_voice_filename(media_path)
                    asr_rec = asr_data.get(fn) if fn else None
                    
                    if asr_rec:
                        # Check schema - 支持新旧版本
                        schema_version = asr_rec.get("schema_version")
                        if schema_version not in [SCHEMA_EXPECTED_NEW, SCHEMA_EXPECTED_OLD]:
                            stats["voice_schema_mismatch"] += 1
                            if len(examples["schema_mismatch"]) < 5:
                                examples["schema_mismatch"].append({
                                    "file": fn,
                                    "expected": f"{SCHEMA_EXPECTED_NEW} or {SCHEMA_EXPECTED_OLD}",
                                    "got": schema_version,
                                })
                        
                        stats["voice_hit"] += 1
                        
                        # Enrich full record
                        enriched_full["voice_to_text"] = asr_rec.get("punct_text", "")
                        enriched_full["asr_engine"] = asr_rec.get("primary_engine", "")
                        enriched_full["asr_raw_text"] = asr_rec.get("raw_text", "")
                        enriched_full["asr_patches"] = asr_rec.get("funasr", {}).get("patches") if asr_rec.get("funasr") else []
                        
                        # Add v3 emotion analysis
                        sensevoice_data = asr_rec.get("sensevoice", {})
                        if sensevoice_data:
                            enriched_full["emotion_tags"] = sensevoice_data.get("emotion_tags", [])
                            enriched_full["event_tags"] = sensevoice_data.get("event_tags", [])
                        
                        trigger_reasons = asr_rec.get("trigger_reasons", [])
                        if trigger_reasons:
                            enriched_full["trigger_reasons"] = trigger_reasons
                        
                        voice_analysis = asr_rec.get("voice_analysis")
                        if voice_analysis:
                            enriched_full["voice_analysis"] = voice_analysis
                        
                        # Enrich slim record
                        enriched_slim["text"] = asr_rec.get("punct_text", "")
                        
                        if sensevoice_data and sensevoice_data.get("emotion_tags"):
                            enriched_slim["emotion_tags"] = sensevoice_data.get("emotion_tags", [])
                        
                        if voice_analysis:
                            emotion_desc = voice_analysis.get("emotion_desc", "")
                            subtext = voice_analysis.get("subtext", "")
                            if emotion_desc:
                                enriched_slim["emotion_desc"] = emotion_desc
                            if subtext:
                                enriched_slim["subtext"] = subtext
                    else:
                        stats["voice_miss"] += 1
                        if len(examples["miss"]) < 20:
                            examples["miss"].append({
                                "seq_in_html": msg.get("seq_in_html"),
                                "msg_uid": msg.get("msg_uid"),
                                "media_path": media_path,
                            })
            
            f_full.write(json.dumps(enriched_full, ensure_ascii=False) + "\n")
            f_slim.write(json.dumps(enriched_slim, ensure_ascii=False) + "\n")
    
    # 替换原文件（原子操作）
    temp_full.replace(OUT_FULL)
    temp_slim.replace(OUT_SLIM)
    
    # ========== Write Audit ==========
    audit = {
        "generated": datetime.now().isoformat(),
        "stats": stats,
        "examples": examples,
    }
    
    with OUT_AUDIT.open("w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ Wrote audit to: {OUT_AUDIT}")
    print(f"✅ Wrote enriched_full to: {OUT_FULL}")
    print(f"✅ Wrote enriched_slim to: {OUT_SLIM}")
    
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    print(f"  Messages total: {stats['messages_total']}")
    print(f"  Voice total: {stats['voice_total']}")
    print(f"  Voice hit: {stats['voice_hit']}")
    print(f"  Voice miss: {stats['voice_miss']}")


if __name__ == "__main__":
    main()
