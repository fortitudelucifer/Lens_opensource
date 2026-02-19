#!/usr/bin/env python3
"""
语音合并引擎步骤

功能：
- 合并三路语音处理结果：FunASR + Whisper + 情绪分析
- 统一字段结构（merged_v2 schema）
- 生成质量报告（QC Report）

处理流程：
1. 加载原始消息（获取 msg_uid 等元数据）
2. 加载 FunASR 转写结果
3. 加载 Whisper 转写结果
4. 加载情绪分析结果（SenseVoice + Qwen）
5. 加载压缩数据（如果存在）
6. 对每个语音文件：
   - 选择主引擎（FunASR 优先，Whisper 后备）
   - 合并转写文本
   - 添加情绪标签和分析
   - 添加压缩数据
   - 使用 schema_utils 构建统一结构
7. 生成 QC 报告（覆盖率、差异样本）

合并策略：
- 主引擎选择：FunASR > Whisper > None
- 情绪分析：可选，如果有则添加
- 压缩数据：可选，如果有则添加
- 字段顺序：使用 reorder_record 统一排序

输入：
- raw/P1_messages_raw.jsonl: 原始消息（元数据）
- artifacts/before_merge/voice/voice_funasr_v2.jsonl: FunASR 结果
- artifacts/before_merge/voice/voice_whisper_v2.jsonl: Whisper 结果
- artifacts/before_merge/voice/voice_merged_v3.jsonl: 情绪分析结果
- artifacts/before_merge/voice/voice_compressed.jsonl: 压缩数据（可选）

输出：
- artifacts/after_merge/voice/voice_merged_final.jsonl: 最终合并结果
- artifacts/before_merge/voice/voice_merged_qc_report.md: QC 报告

依赖：
- scripts._common.schema_utils: Schema 工具（统一字段结构）
- scripts._common.jsonl_utils: JSONL 工具
- scripts._common.path_utils: 路径工具

使用示例：
    python scripts/voice/run_all/_03_merge_engine.py

注意事项：
- 确保先运行 _01_run_funasr.py 和 _01b_run_whisper.py
- 情绪分析和压缩数据是可选的
- QC 报告包含差异样本，用于质量检查

作者：forcifer
更新于：2026-02-02
"""
import json
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
    PATHS, get_voice_before_merge, get_voice_after_merge, load_voice_config
)
from scripts._common.jsonl_utils import load_jsonl_by_key
from scripts._common.schema_utils import (
    SCHEMA_VERSION,
    build_common_header,
    reorder_record,
)

# ========== 从配置加载参数 ==========
voice_config = load_voice_config()

# 路径配置
BEFORE_MERGE = get_voice_before_merge()
AFTER_MERGE = get_voice_after_merge()

# Input files
FUNASR_FILE = BEFORE_MERGE / "voice_funasr_v2.jsonl"
WHISPER_FILE = BEFORE_MERGE / "voice_whisper_v2.jsonl"
V3_FILE = BEFORE_MERGE / "voice_merged_v3.jsonl"
COMPRESSED_FILE = BEFORE_MERGE / "voice_compressed.jsonl"  # 压缩后的数据

# Output files
OUT_MERGED = AFTER_MERGE / "voice_merged_final.jsonl"
OUT_QC = BEFORE_MERGE / "voice_merged_qc_report.md"  # QC报告输出到 before_merge


def main():
    print("=" * 60)
    print("Voice Merge Engine v3")
    print("=" * 60)
    print(f"  Input Dir: {BEFORE_MERGE}")
    print(f"  Output Dir: {AFTER_MERGE}")
    
    # ========== Load Raw Messages ==========
    raw_messages_file = PATHS.get('raw', {}).get('messages', f'{PROJECT_ROOT}/raw/P1_messages_raw.jsonl')
    print("\n[0/4] Loading raw messages...")
    raw_messages = load_jsonl_by_key(str(raw_messages_file), key='media_path')
    print(f"      Loaded {len(raw_messages)} raw message records")
    
    # ========== Load Data ==========
    print("\n[1/4] Loading FunASR results...")
    funasr_data = load_jsonl_by_key(str(FUNASR_FILE), key='file')
    print(f"      Loaded {len(funasr_data)} records")
    
    print("\n[2/4] Loading Whisper results...")
    whisper_data = load_jsonl_by_key(str(WHISPER_FILE), key='file')
    print(f"      Loaded {len(whisper_data)} records")
    
    print("\n[3/4] Loading v3 emotion analysis...")
    v3_data = {}
    if V3_FILE.exists():
        v3_data = load_jsonl_by_key(str(V3_FILE), key='file')
        print(f"      Loaded {len(v3_data)} records")
    else:
        print(f"      [WARN] v3 file not found: {V3_FILE}")
    
    # Load compressed data (if exists)
    print("\n[3.5/4] Loading compressed data...")
    compressed_data = {}
    if COMPRESSED_FILE.exists():
        compressed_data = load_jsonl_by_key(str(COMPRESSED_FILE), key='file')
        print(f"      ✅ Loaded {len(compressed_data)} compressed records")
    else:
        print(f"      ⚠️ No compressed data found, using original analysis")
    
    # ========== Merge Logic ==========
    all_files = set(funasr_data.keys()) | set(whisper_data.keys())
    print(f"\n[4/4] Merging {len(all_files)} unique voice files...")
    
    OUT_MERGED.parent.mkdir(parents=True, exist_ok=True)
    
    stats = {
        "total": 0,
        "funasr_only": 0,
        "whisper_only": 0,
        "both": 0,
        "funasr_errors": 0,
        "whisper_errors": 0,
        "with_emotion": 0,
        "with_qwen_analysis": 0,
        "diff_samples": [],
    }
    
    with OUT_MERGED.open("w", encoding="utf-8") as f:
        for fn in tqdm(sorted(all_files), desc="合并记录", **tqdm_kwargs):
            stats["total"] += 1
            funasr_rec = funasr_data.get(fn)
            whisper_rec = whisper_data.get(fn)
            v3_rec = v3_data.get(fn)
            
            has_funasr = funasr_rec and "error" not in funasr_rec
            has_whisper = whisper_rec and "error" not in whisper_rec
            
            if funasr_rec and "error" in funasr_rec:
                stats["funasr_errors"] += 1
            if whisper_rec and "error" in whisper_rec:
                stats["whisper_errors"] += 1
            
            # Merge strategy: FunASR primary, Whisper fallback
            if has_funasr:
                primary = "funasr"
                punct_text = funasr_rec.get("punct_text", "")
                raw_text = funasr_rec.get("raw_text", "")
            elif has_whisper:
                primary = "whisper"
                punct_text = whisper_rec.get("punct_text", "")
                raw_text = whisper_rec.get("raw_text", "")
            else:
                primary = "none"
                punct_text = ""
                raw_text = ""
            
            # Count coverage
            if has_funasr and has_whisper:
                stats["both"] += 1
                funasr_text = funasr_rec.get("punct_text", "")
                whisper_text = whisper_rec.get("punct_text", "")
                if funasr_text != whisper_text and len(stats["diff_samples"]) < 5:
                    stats["diff_samples"].append({
                        "file": fn,
                        "funasr": funasr_text[:100],
                        "whisper": whisper_text[:100],
                    })
            elif has_funasr:
                stats["funasr_only"] += 1
            elif has_whisper:
                stats["whisper_only"] += 1
            
            # Build merged record using schema_utils
            # fn 是文件名（如 20250618-130037-132076-1.mp3）
            # 原始消息的 media_path 是 raw/voice/文件名，需要转换
            full_media_path = f"raw/voice/{fn}"
            raw_record = raw_messages.get(full_media_path, {})
            
            merged_rec = build_common_header(
                raw_record=raw_record,
                schema_version=SCHEMA_VERSION,
                media_path=fn,
                modality='voice',
            )
            
            # 添加 voice 特定字段
            merged_rec.update({
                "primary_engine": primary,
                "punct_text": punct_text,
                "raw_text": raw_text,
                "funasr": funasr_rec if funasr_rec else None,
                "whisper": whisper_rec if whisper_rec else None,
            })
            
            # Add v3 emotion analysis if available
            if v3_rec:
                sensevoice_data = v3_rec.get("sensevoice", {})
                emotion_tags = sensevoice_data.get("emotion_tags", [])
                event_tags = sensevoice_data.get("event_tags", [])
                
                merged_rec["sensevoice"] = {
                    "emotion_tags": emotion_tags,
                    "event_tags": event_tags,
                }
                
                trigger_reasons = v3_rec.get("trigger_reasons", [])
                merged_rec["trigger_reasons"] = trigger_reasons
                
                voice_analysis = v3_rec.get("voice_analysis")
                if voice_analysis:
                    merged_rec["voice_analysis"] = {
                        "emotion_desc": voice_analysis.get("emotion_desc", ""),
                        "tonal_features": voice_analysis.get("tonal_features", ""),
                        "subtext": voice_analysis.get("subtext", ""),
                        "emotion_tags": voice_analysis.get("emotion_tags", []),
                    }
                    stats["with_qwen_analysis"] += 1
                
                if emotion_tags:
                    stats["with_emotion"] += 1
            
            # Add compressed data if available
            # 压缩数据使用 file 作为 key（文件名）
            compressed_rec = compressed_data.get(fn, {})
            if compressed_rec:
                merged_rec["analysis_summary"] = compressed_rec.get("analysis_summary", "")
                merged_rec["possible_intent"] = compressed_rec.get("possible_intent", "")
                merged_rec["possible_subtext"] = compressed_rec.get("possible_subtext", "")
                merged_rec["compression_ratio"] = compressed_rec.get("compression_ratio", 0)
                merged_rec["is_compressed"] = True
            else:
                merged_rec["is_compressed"] = False
            
            # 使用 reorder_record 重排字段顺序
            merged_rec = reorder_record(merged_rec, 'voice')
            
            f.write(json.dumps(merged_rec, ensure_ascii=False) + "\n")
    
    print(f"\n✅ Wrote merged results to: {OUT_MERGED}")
    
    # ========== Generate QC Report ==========
    with OUT_QC.open("w", encoding="utf-8") as f:
        f.write("# 语音合并质量报告 v3\n\n")
        f.write(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")
        
        f.write("## 统计概览\n\n")
        f.write("| 指标 | 数量 |\n")
        f.write("| ---- | ---- |\n")
        f.write(f"| 总文件数 | {stats['total']} |\n")
        f.write(f"| 双引擎覆盖 | {stats['both']} |\n")
        f.write(f"| 仅 FunASR | {stats['funasr_only']} |\n")
        f.write(f"| 仅 Whisper | {stats['whisper_only']} |\n")
        f.write(f"| FunASR 错误 | {stats['funasr_errors']} |\n")
        f.write(f"| Whisper 错误 | {stats['whisper_errors']} |\n")
        f.write(f"| **有情绪标签** | **{stats['with_emotion']}** |\n")
        f.write(f"| **有 Qwen 分析** | **{stats['with_qwen_analysis']}** |\n\n")
        
        if stats["diff_samples"]:
            f.write("## 差异样本 (FunASR vs Whisper)\n\n")
            for i, sample in enumerate(stats["diff_samples"], 1):
                f.write(f"### 样本 {i}: `{sample['file']}`\n\n")
                f.write(f"**FunASR**: {sample['funasr']}...\n\n")
                f.write(f"**Whisper**: {sample['whisper']}...\n\n")
    
    print(f"✅ Wrote QC report to: {OUT_QC}")
    
    # Print summary
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    print(f"  Total files: {stats['total']}")
    print(f"  With emotion tags: {stats['with_emotion']}")
    print(f"  With Qwen analysis: {stats['with_qwen_analysis']}")


if __name__ == "__main__":
    main()
