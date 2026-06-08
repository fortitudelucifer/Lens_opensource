#!/usr/bin/env python3
"""
语音转写步骤（FunASR 引擎）

功能：
- 使用 FunASR 引擎对语音文件进行转写
- 集成三个模型：paraformer-zh（ASR）+ fsmn-vad（VAD）+ ct-punc（标点）
- 支持热词（hotword）增强识别准确度
- 自动进行文本后处理（简繁转换、标点去重、误判修复）

处理流程：
1. 加载 FunASR 模型（三合一）
2. 扫描 raw/voice/ 目录下的所有 .mp3 文件
3. 对每个文件进行转写：
   - 调用 FunASR 引擎（带热词）
   - 繁体转简体（OpenCC）
   - 去除标点符号（用于后续标点模型）
   - 标点去重和修复
   - 应用文本补丁（修正常见错误）
   - 修复误判的问句
4. 输出到 voice_funasr_v2.jsonl

输入：
- raw/voice/*.mp3: 原始语音文件
- configs/voice.yaml: 语音配置（模型、热词等）
- configs/hotword.txt: 热词列表（可选）

输出：
- artifacts/before_merge/voice/voice_funasr_v2.jsonl: FunASR 转写结果
  每条记录包含：
  - file: 文件名
  - engine: 引擎信息
  - raw_text: 原始转写文本
  - raw_text_s: 简体转换后的文本
  - raw_for_punc: 去除标点后的文本
  - punct_text: 最终标点文本
  - patches: 应用的文本补丁列表
  - prep_meta: 预处理元数据
  - result: FunASR 原始结果

依赖：
- funasr: FunASR 引擎（阿里达摩院）
- scripts._common.text_normalize: 文本规范化工具
- scripts._common.path_utils: 路径工具

使用示例：
    python scripts/voice/run_all/_01_run_funasr.py              # 处理全部
    python scripts/voice/run_all/_01_run_funasr.py --sample 10  # 测试模式

注意事项：
- FunASR 模型会自动下载到 ~/.cache/modelscope/
- 热词可以提高特定词汇的识别准确度
- 标点模型（ct-punc）已集成在 FunASR 中
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
    to_simplified, strip_punc, dedup_punc, apply_patches, fix_false_question
)

from funasr import AutoModel

# ========== 从配置加载参数 ==========
voice_config = load_voice_config()
asr_config = voice_config.get('asr', {}).get('funasr', {})
text_config = voice_config.get('text_processing', {})

SCHEMA_VERSION = voice_config.get('schema_version', 'voice_v3')
OPENCC_CONFIG = text_config.get('opencc_config', 't2s')
PUNC_MODEL = asr_config.get('punc_model', 'ct-punc')
HOTWORD = asr_config.get('hotword', '')

# 路径配置
VOICE_DIR = get_voice_dir()
OUT_FILE = get_voice_before_merge() / "voice_funasr_v2.jsonl"


def main():
    """
    主函数：FunASR 语音转写
    
    处理流程：
    1. 解析命令行参数（--sample）
    2. 加载 FunASR 三合一模型（ASR + VAD + Punc）
    3. 扫描语音文件并逐个处理
    4. 对每个文件：
       - 调用 FunASR 引擎转写
       - 繁体转简体
       - 去除标点（为后续标点模型准备）
       - 标点去重和修复
       - 应用文本补丁
       - 修复误判的问句
    5. 输出到 voice_funasr_v2.jsonl
    
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
        - result: FunASR 原始结果
    
    异常处理：
        - 文件不存在：记录 error="file_not_found"
        - 转写失败：记录 error="asr_failed" 和异常信息
    
    Example:
        $ python scripts/voice/run_all/_01_run_funasr.py
        ============================================================
        FunASR Voice Transcription
        ============================================================
          Voice Dir: /data/workspace/raw/voice
          Output: artifacts/before_merge/voice/voice_funasr_v2.jsonl
        
        [1/3] Loading FunASR model...
              Model loaded.
        
        [2/3] Found 1234 voice files to process.
        
        [3/3] Processing...
        FunASR转写: 100%|████████████| 1234/1234 [10:23<00:00, 1.98it/s]
        
        ✅ Done. Wrote 1234 records to: artifacts/before_merge/voice/voice_funasr_v2.jsonl
    """
    parser = argparse.ArgumentParser(description='FunASR Voice Transcription')
    parser.add_argument('--sample', type=int, default=0, help='仅处理前N条（测试用）')
    args = parser.parse_args()
    
    print("=" * 60)
    print("FunASR Voice Transcription")
    print("=" * 60)
    print(f"  Voice Dir: {VOICE_DIR}")
    print(f"  Output: {OUT_FILE}")
    
    # ========== Model Init ==========
    print("\n[1/3] Loading FunASR model...")
    model = AutoModel(
        model=asr_config.get('model', 'paraformer-zh'),
        vad_model=asr_config.get('vad_model', 'fsmn-vad'),
        punc_model=asr_config.get('punc_model', 'ct-punc'),
    )
    print("      Model loaded.")
    
    # ========== Processing ==========
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    voice_files = sorted(VOICE_DIR.glob("*.mp3"))
    total = len(voice_files)
    print(f"\n[2/3] Found {total} voice files to process.")
    
    # 应用 sample 限制
    if args.sample > 0:
        voice_files = voice_files[:args.sample]
        print(f"      Sample mode: processing only {len(voice_files)} files")
    
    print("\n[3/3] Processing...")
    with OUT_FILE.open("w", encoding="utf-8") as f:
        for path in tqdm(voice_files, desc="FunASR转写", **tqdm_kwargs):
            fn = path.name
            
            if not path.exists():
                f.write(json.dumps({
                    "file": fn,
                    "error": "file_not_found",
                    "path": str(path)
                }, ensure_ascii=False) + "\n")
                continue
            
            try:
                res = model.generate(input=str(path), hotword=HOTWORD)
                raw_text = ""
                if isinstance(res, list) and res and isinstance(res[0], dict):
                    raw_text = (res[0].get("text") or "").strip()
                else:
                    raw_text = str(res)
            except Exception as e:
                f.write(json.dumps({
                    "file": fn,
                    "error": "asr_failed",
                    "exception": str(e)
                }, ensure_ascii=False) + "\n")
                continue
            
            # Post-processing
            raw_text_s = to_simplified(raw_text)
            raw_for_punc = strip_punc(raw_text_s)
            
            punct_text = dedup_punc(raw_text_s)
            punct_text, patches = apply_patches(punct_text)
            punct_text, qfix = fix_false_question(punct_text)
            patches.extend(qfix)
            
            record = {
                "schema_version": SCHEMA_VERSION,
                "file": fn,
                "engine": "FunASR paraformer-zh + fsmn-vad + ct-punc",
                "raw_text": raw_text,
                "raw_text_s": raw_text_s,
                "raw_for_punc": raw_for_punc,
                "prep_meta": {
                    "simplified": (raw_text_s != raw_text),
                    "opencc_config": OPENCC_CONFIG,
                    "strip_punc_applied": True,
                    "punc_model": PUNC_MODEL,
                    "punc_from_engine": True,
                },
                "punct_text": punct_text,
                "patches": patches,
                "result": res,
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    
    print(f"\n✅ Done. Wrote {len(voice_files)} records to: {OUT_FILE}")


if __name__ == "__main__":
    main()
