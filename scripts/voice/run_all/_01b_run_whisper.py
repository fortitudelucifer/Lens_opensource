#!/usr/bin/env python3
"""
语音转写步骤（Whisper 引擎）

功能：
- 使用 faster-whisper 引擎对语音文件进行转写
- 作为 FunASR 的补充/后备方案
- 集成 VAD（语音活动检测）过滤静音段
- 使用独立的 ct-punc 模型添加标点
- 支持时间戳分段（segments）

处理流程：
1. 加载 faster-whisper 模型（large-v3）
2. 加载 ct-punc 标点模型（独立）
3. 扫描 raw/voice/ 目录下的所有 .mp3 文件
4. 对每个文件进行转写：
   - 调用 Whisper 引擎（带 VAD 过滤）
   - 获取分段结果（带时间戳）
   - 繁体转简体（OpenCC）
   - 去除标点符号
   - 调用 ct-punc 添加标点
   - 标点去重和修复
   - 应用文本补丁
   - 修复误判的问句
5. 输出到 voice_whisper_v2.jsonl

与 FunASR 的区别：
- FunASR：集成标点模型，速度快，适合中文
- Whisper：多语言支持，提供时间戳，标点需要独立模型
- 两者结果会在 _03_merge_engine.py 中合并

输入：
- raw/voice/*.mp3: 原始语音文件
- configs/voice.yaml: 语音配置（模型路径、参数等）

输出：
- artifacts/before_merge/voice/voice_whisper_v2.jsonl: Whisper 转写结果
  每条记录包含：
  - file: 文件名
  - engine: 引擎信息
  - raw_text: 原始转写文本
  - raw_text_s: 简体转换后的文本
  - raw_for_punc: 去除标点后的文本
  - punct_text: 最终标点文本
  - patches: 应用的文本补丁列表
  - prep_meta: 预处理元数据
  - segments: 分段结果（带时间戳）

依赖：
- faster-whisper: Whisper 引擎（CTranslate2 优化版）
- funasr: ct-punc 标点模型
- scripts._common.text_normalize: 文本规范化工具
- scripts._common.path_utils: 路径工具

使用示例：
    python scripts/voice/run_all/_01b_run_whisper.py              # 处理全部
    python scripts/voice/run_all/_01b_run_whisper.py --sample 10  # 测试模式

注意事项：
- Whisper 模型需要预先下载到 /data/models/faster-whisper-large-v3
- VAD 过滤可以去除静音段，提高准确度
- 标点模型（ct-punc）需要独立加载
- 如果文件不存在或转写失败，会记录错误信息

作者：[Author]
更新于：2026-02-02
"""
import os
import json
import sys
import argparse
from pathlib import Path
from tqdm import tqdm

# 确保 tqdm 输出到 stderr 以便实时显示
tqdm_kwargs = {"file": sys.stderr, "dynamic_ncols": True}

# VRAM 优化配置
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts._common.path_utils import (
    PATHS, get_voice_dir, get_voice_before_merge, load_voice_config
)
from scripts._common.text_normalize import (
    to_simplified, strip_punc, dedup_punc, apply_patches, fix_false_question, prepare_for_punc
)

from faster_whisper import WhisperModel
from funasr import AutoModel

# ========== 从配置加载参数 ==========
voice_config = load_voice_config()
whisper_config = voice_config.get('asr', {}).get('whisper', {})
text_config = voice_config.get('text_processing', {})

SCHEMA_VERSION = voice_config.get('schema_version', 'voice_v3')
OPENCC_CONFIG = text_config.get('opencc_config', 't2s')
PUNC_MODEL = "ct-punc"
WHISPER_MODEL_PATH = whisper_config.get('model_path', '/data/models/faster-whisper-large-v3')

# 路径配置
VOICE_DIR = get_voice_dir()
OUT_FILE = get_voice_before_merge() / "voice_whisper_v2.jsonl"


def main():
    """
    主函数：Whisper 语音转写
    
    处理流程：
    1. 解析命令行参数（--sample）
    2. 加载 faster-whisper 模型（large-v3）
    3. 加载 ct-punc 标点模型（独立）
    4. 扫描语音文件并逐个处理
    5. 对每个文件：
       - 调用 Whisper 引擎转写（带 VAD 过滤）
       - 提取分段结果（带时间戳）
       - 繁体转简体
       - 去除标点
       - 调用 ct-punc 添加标点
       - 标点去重和修复
       - 应用文本补丁
       - 修复误判的问句
    6. 输出到 voice_whisper_v2.jsonl
    
    命令行参数：
        --sample N: 仅处理前 N 个文件（测试用）
    
    输出格式：
        每行一个 JSON 对象，包含：
        - schema_version: Schema 版本
        - file: 文件名
        - engine: 引擎信息
        - raw_text: 原始转写文本
        - raw_text_s: 简体文本
        - raw_for_punc: 去标点文本
        - punct_text: 最终标点文本
        - patches: 应用的补丁
        - prep_meta: 预处理元数据
        - segments: 分段结果（带时间戳）
    
    异常处理：
        - 文件不存在：记录 error="file_not_found"
        - 转写失败：记录 error="asr_failed" 和异常信息
        - 标点失败：使用简体文本作为后备
    
    Example:
        $ python scripts/voice/run_all/_01b_run_whisper.py
        ============================================================
        Whisper Voice Transcription
        ============================================================
          Voice Dir: /data/workspace/raw/voice
          Output: artifacts/before_merge/voice/voice_whisper_v2.jsonl
          Model: /data/models/faster-whisper-large-v3
        
        [1/3] Loading Whisper model...
              Whisper model loaded.
              Loading ct-punc model...
              ct-punc model loaded.
        
        [2/3] Found 1234 voice files to process.
        
        [3/3] Processing...
        Whisper转写: 100%|████████████| 1234/1234 [15:42<00:00, 1.31it/s]
        
        ✅ Done. Wrote 1234 records to: artifacts/before_merge/voice/voice_whisper_v2.jsonl
    """
    parser = argparse.ArgumentParser(description='Whisper Voice Transcription')
    parser.add_argument('--sample', type=int, default=0, help='仅处理前N条（测试用）')
    args = parser.parse_args()
    
    print("=" * 60)
    print("Whisper Voice Transcription")
    print("=" * 60)
    print(f"  Voice Dir: {VOICE_DIR}")
    print(f"  Output: {OUT_FILE}")
    print(f"  Model: {WHISPER_MODEL_PATH}")
    
    # ========== Model Init ==========
    print("\n[1/3] Loading Whisper model...")
    asr = WhisperModel(
        WHISPER_MODEL_PATH,
        device=whisper_config.get('device', 'cuda'),
        compute_type=whisper_config.get('compute_type', 'float16')
    )
    print("      Whisper model loaded.")
    
    print("      Loading ct-punc model...")
    punc = AutoModel(model="ct-punc")
    print("      ct-punc model loaded.")
    
    # ========== Processing ==========
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    voice_files = sorted(VOICE_DIR.glob("*.mp3"))
    total = len(voice_files)
    print(f"\n[2/3] Found {total} voice files to process.")
    
    # 应用 sample 限制
    if args.sample > 0:
        voice_files = voice_files[:args.sample]
        print(f"      Sample mode: processing only {len(voice_files)} files")
    
    # Whisper 参数
    beam_size = whisper_config.get('beam_size', 5)
    language = whisper_config.get('language', 'zh')
    vad_filter = whisper_config.get('vad_filter', True)
    vad_params = whisper_config.get('vad_parameters', {})
    
    print("\n[3/3] Processing...")
    with OUT_FILE.open("w", encoding="utf-8") as f:
        for path in tqdm(voice_files, desc="Whisper转写", **tqdm_kwargs):
            fn = path.name
            
            if not path.exists():
                f.write(json.dumps({
                    "file": fn,
                    "error": "file_not_found",
                    "path": str(path)
                }, ensure_ascii=False) + "\n")
                continue
            
            try:
                segments, info = asr.transcribe(
                    str(path),
                    beam_size=beam_size,
                    language=language,
                    vad_filter=vad_filter,
                    vad_parameters=vad_params,
                )
                segs = [{"start": s.start, "end": s.end, "text": s.text} for s in segments]
                raw_text = "".join(s["text"] for s in segs).strip()
            except Exception as e:
                f.write(json.dumps({
                    "file": fn,
                    "error": "asr_failed",
                    "exception": str(e)
                }, ensure_ascii=False) + "\n")
                continue
            
            # Post-processing
            raw_text_s = to_simplified(raw_text)
            raw_for_punc, prep_meta = prepare_for_punc(raw_text, simplify=True)
            
            if not isinstance(prep_meta, dict):
                prep_meta = {}
            prep_meta.update({
                "simplified": (raw_text_s != raw_text),
                "opencc_config": OPENCC_CONFIG,
                "strip_punc_applied": True,
                "punc_model": PUNC_MODEL,
                "punc_from_engine": False,
            })
            
            try:
                pres = punc.generate(input=raw_for_punc)
                punct_text = pres[0].get("text") if isinstance(pres, list) and isinstance(pres[0], dict) and "text" in pres[0] else str(pres)
            except Exception:
                punct_text = raw_text_s
            
            punct_text = dedup_punc(punct_text)
            punct_text, patches = apply_patches(punct_text)
            punct_text, qfix = fix_false_question(punct_text)
            patches.extend(qfix)
            
            record = {
                "schema_version": SCHEMA_VERSION,
                "file": fn,
                "engine": "faster-whisper large-v3 + ct-punc",
                "raw_text": raw_text,
                "raw_text_s": raw_text_s,
                "raw_for_punc": raw_for_punc,
                "prep_meta": prep_meta,
                "punct_text": punct_text,
                "patches": patches,
                "segments": segs,
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    
    print(f"\n✅ Done. Wrote {len(voice_files)} records to: {OUT_FILE}")


if __name__ == "__main__":
    main()
