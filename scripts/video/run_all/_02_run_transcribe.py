#!/usr/bin/env python3
"""
视频音频转写步骤（FunASR 转写 + SenseVoice 情绪检测）

功能：
- 使用 FunASR 对视频音频进行转写
- 使用 SenseVoice 检测情绪和音频事件
- 支持 Triage 触发条件检测
- 自动文本后处理（简繁转换、标点修复）

处理流程：
1. 加载视频提取结果（包含音频路径）
2. 对每个视频：
   a. **FunASR 转写**：
      - 使用 paraformer-zh + fsmn-vad + ct-punc
      - 支持热词增强
      - 自动文本后处理（简繁转换、标点去重、误判修复）
   b. **SenseVoice 情绪检测**（可选）：
      - 检测情绪标签（SAD/HAPPY/ANGRY/NEUTRAL等）
      - 检测音频事件（BGM/Applause/Laughter/Cry等）
      - 提供备用转写文本
   c. **Triage 触发检测**：
      - 情绪触发：SAD/ANGRY
      - 事件触发：Cry/Laughter
      - 关键词触发：配置文件中的敏感词
3. 输出转写和情绪结果

FunASR 引擎：
- **模型**: paraformer-zh（ASR）+ fsmn-vad（VAD）+ ct-punc（标点）
- **特点**: 
  * 中文优化，准确度高
  * 集成标点模型，无需后处理
  * 支持热词增强
- **显存**: ~2GB

SenseVoice 情绪检测：
- **模型**: iic/SenseVoiceSmall
- **输出格式**: <|EMOTION|><|EVENT|><|LANG|>text
- **支持的情绪**: SAD, HAPPY, ANGRY, NEUTRAL, FEARFUL, DISGUSTED, SURPRISED
- **支持的事件**: BGM, Applause, Laughter, Cry, Cough, Sneeze, Speech
- **显存**: ~1GB

Triage 触发条件：
- **情绪触发**: 检测到 SAD/ANGRY 等负面情绪
- **事件触发**: 检测到 Cry/Laughter 等特殊事件
- **关键词触发**: 文本包含配置的敏感词
- **用途**: 标记需要深度分析的视频

文本后处理：
- 繁体转简体（OpenCC）
- 标点去重（连续标点合并）
- 应用文本补丁（修正常见错误）
- 修复误判的问句

跳过策略：
- 可使用 `--skip-emotion` 跳过情绪检测
- 适用场景：只需要转写文本，不关心情绪

输入：
- artifacts/before_merge/video/video_extract_v1.jsonl: 提取结果（含音频路径）
- /data/cache/video_audio/*.aac: 分离的音频文件
- configs/voice.yaml: 语音配置（ASR、情绪检测参数）

输出：
- artifacts/before_merge/video/video_transcribe_v1.jsonl: 转写和情绪结果
  * 包含：
    - transcription: FunASR 转写结果
      * engine: 引擎名称
      * raw_text: 原始文本
      * punct_text: 标点文本
      * patches: 应用的补丁
    - emotion: SenseVoice 情绪检测结果
      * sensevoice: 情绪和事件标签
      * trigger_reasons: Triage 触发原因

依赖：
- funasr: FunASR 和 SenseVoice 模型
- scripts._common.text_normalize: 文本规范化工具
- scripts._common.path_utils: 路径工具

使用示例：
    python scripts/video/run_all/_02_run_transcribe.py              # 处理全部
    python scripts/video/run_all/_02_run_transcribe.py --sample 3   # 测试模式
    python scripts/video/run_all/_02_run_transcribe.py --skip-emotion  # 跳过情绪检测

性能参考（RTX 5070 Ti 16GB）：
- FunASR 转写：~5-10 秒/分钟音频
- SenseVoice 情绪：~2-3 秒/分钟音频
- 显存占用：~3GB（两个模型同时加载）

注意事项：
- 确保先运行 _01_run_extract.py 提取音频
- 无音频的视频会跳过转写
- 模型会自动下载到 ~/.cache/modelscope/
- 情绪检测结果会用于后续的 Caption 生成

作者：[Author]
更新于：2026-02-02
"""
import os
import sys
import json
import gc
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
    get_video_before_merge, load_video_config, load_voice_config
)
from scripts._common.text_normalize import (
    to_simplified, strip_punc, dedup_punc, apply_patches, fix_false_question
)

# ========== 加载配置 ==========
video_config = load_video_config()
voice_config = load_voice_config()
asr_config = voice_config.get('asr', {}).get('funasr', {})
text_config = voice_config.get('text_processing', {})
emotion_config = voice_config.get('emotion', {})
triage_config = voice_config.get('triage', {})

SCHEMA_VERSION = "video_transcribe_v1"

# 全局模型缓存
_funasr_model = None
_sensevoice_model = None


def get_funasr_model():
    """获取或创建 FunASR 模型单例"""
    global _funasr_model
    if _funasr_model is None:
        from funasr import AutoModel
        print("  Loading FunASR model (one-time)...")
        _funasr_model = AutoModel(
            model=asr_config.get('model', 'paraformer-zh'),
            vad_model=asr_config.get('vad_model', 'fsmn-vad'),
            punc_model=asr_config.get('punc_model', 'ct-punc'),
            disable_update=True,
        )
    return _funasr_model


def get_sensevoice_model():
    """获取或创建 SenseVoice 模型单例"""
    global _sensevoice_model
    if _sensevoice_model is None:
        from funasr import AutoModel
        sensevoice_config = emotion_config.get('sensevoice', {})
        print("  Loading SenseVoice model (one-time)...")
        _sensevoice_model = AutoModel(
            model=sensevoice_config.get('model_id', 'iic/SenseVoiceSmall'),
            trust_remote_code=sensevoice_config.get('trust_remote_code', True),
            disable_update=True,
        )
    return _sensevoice_model


def unload_models():
    """卸载所有模型并清理显存"""
    global _funasr_model, _sensevoice_model
    if _funasr_model is not None:
        del _funasr_model
        _funasr_model = None
    if _sensevoice_model is not None:
        del _sensevoice_model
        _sensevoice_model = None
    gc.collect()
    try:
        import torch
        torch.cuda.empty_cache()
    except:
        pass


def unload_model(model):
    """卸载单个模型并清理显存（保留用于兼容）"""
    del model
    gc.collect()
    try:
        import torch
        torch.cuda.empty_cache()
    except:
        pass


def transcribe_audio(audio_path: str) -> dict:
    """使用 FunASR 转写音频"""
    model = get_funasr_model()
    
    try:
        hotword = asr_config.get('hotword', '')
        res = model.generate(input=audio_path, hotword=hotword)
        
        raw_text = ""
        if isinstance(res, list) and res and isinstance(res[0], dict):
            raw_text = (res[0].get("text") or "").strip()
        else:
            raw_text = str(res)
        
        # 文本后处理
        raw_text_s = to_simplified(raw_text)
        punct_text = dedup_punc(raw_text_s)
        punct_text, patches = apply_patches(punct_text)
        punct_text, qfix = fix_false_question(punct_text)
        patches.extend(qfix)
        
        result = {
            'engine': 'funasr',
            'raw_text': raw_text,
            'punct_text': punct_text,
            'patches': patches,
            'segments': []  # TODO: 提取时间戳分段
        }
        
    except Exception as e:
        result = {
            'engine': 'funasr',
            'error': str(e)
        }
    
    return result


def detect_emotion(audio_path: str) -> dict:
    """使用 SenseVoice 检测情绪和音频事件"""
    model = get_sensevoice_model()
    sensevoice_config = emotion_config.get('sensevoice', {})
    
    try:
        res = model.generate(
            input=audio_path,
            batch_size_s=sensevoice_config.get('batch_size_s', 60)
        )
        
        # 解析情绪标签和音频事件
        emotion_tags = []
        event_tags = []
        raw_text = ""
        
        if isinstance(res, list) and res:
            text = res[0].get('text', '') if isinstance(res[0], dict) else str(res[0])
            
            # SenseVoice 输出格式: <|EMOTION|><|EVENT|><|LANG|>text
            # 支持的事件标签: BGM, Applause, Laughter, Cry, Cough, Sneeze, Speech
            if '<|' in text:
                import re
                tags = re.findall(r'<\|([^|]+)\|>', text)
                # 提取纯文本（去除标签）
                raw_text = re.sub(r'<\|[^|]+\|>', '', text).strip()
                
                for tag in tags:
                    tag_upper = tag.upper()
                    # 情绪标签
                    if tag_upper in ['SAD', 'HAPPY', 'ANGRY', 'NEUTRAL', 'FEARFUL', 'DISGUSTED', 'SURPRISED']:
                        emotion_tags.append(tag_upper)
                    # 音频事件标签（SenseVoice 支持的事件）
                    elif tag_upper in ['BGM', 'APPLAUSE', 'LAUGHTER', 'CRY', 'COUGH', 'SNEEZE', 'SPEECH']:
                        event_tags.append(tag_upper.capitalize())
                    # 语言标签（忽略）
                    elif tag_upper in ['ZH', 'EN', 'JA', 'KO', 'YUE']:
                        pass
            else:
                raw_text = text
        
        result = {
            'emotion_tags': emotion_tags,
            'event_tags': event_tags,
            'raw_text': raw_text  # SenseVoice 也能转写，作为备用
        }
        
    except Exception as e:
        result = {
            'error': str(e)
        }
    
    return result


def check_triage_triggers(transcript: str, emotion_tags: list, event_tags: list = None) -> list:
    """检查 Triage 触发条件"""
    triggers = []
    
    # 情绪触发
    emotion_triggers = triage_config.get('emotion_triggers', ['SAD', 'ANGRY'])
    for tag in emotion_tags:
        if tag in emotion_triggers:
            triggers.append(f"emotion:{tag}")
    
    # 音频事件触发
    event_triggers = triage_config.get('event_triggers', ['Cry', 'Laughter'])
    if event_tags:
        for tag in event_tags:
            if tag in event_triggers or tag.upper() in [t.upper() for t in event_triggers]:
                triggers.append(f"event:{tag}")
    
    # 关键词触发
    keywords_config = triage_config.get('keywords', {})
    for category, keywords in keywords_config.items():
        for kw in keywords:
            if kw in transcript:
                triggers.append(f"{category}:{kw}")
                break  # 每个类别只触发一次
    
    return triggers


def process_video_audio(extract_record: dict, skip_emotion: bool = False) -> dict:
    """处理单个视频的音频"""
    file_name = extract_record.get('file', '')
    audio_path = extract_record.get('audio_path')
    
    result = {
        'schema_version': SCHEMA_VERSION,
        'file': file_name,
        # 保留原始消息字段
        'msg_uid': extract_record.get('msg_uid', ''),
        'seq_in_html': extract_record.get('seq_in_html', -1),
        'MsgSvrID': extract_record.get('MsgSvrID', ''),
        'token': extract_record.get('token', ''),
        'ts': extract_record.get('ts', 0),
        'time_local': extract_record.get('time_local', ''),
        'speaker': extract_record.get('speaker', 'UNKNOWN'),
        'type': extract_record.get('type', 43),
        'sub_type': extract_record.get('sub_type', 0),
        'modality': 'video',
        'media_path': extract_record.get('media_path', ''),
    }
    
    # 无音频
    if not audio_path or not Path(audio_path).exists():
        result['transcription'] = {'engine': 'none', 'error': 'no_audio'}
        result['emotion'] = {}
        return result
    
    # ASR 转写
    print(f"  Transcribing: {file_name}")
    transcription = transcribe_audio(audio_path)
    result['transcription'] = transcription
    
    # 情绪检测
    if not skip_emotion and 'error' not in transcription:
        print(f"  Emotion detection: {file_name}")
        sensevoice_result = detect_emotion(audio_path)
        
        # 检查触发条件
        trigger_reasons = check_triage_triggers(
            transcription.get('punct_text', ''),
            sensevoice_result.get('emotion_tags', [])
        )
        
        result['emotion'] = {
            'sensevoice': sensevoice_result,
            'trigger_reasons': trigger_reasons
        }
    else:
        result['emotion'] = {}
    
    return result


def main():
    parser = argparse.ArgumentParser(description='Video Audio Transcription')
    parser.add_argument('--sample', type=int, default=0, help='仅处理前N个文件')
    parser.add_argument('--skip-emotion', action='store_true', help='跳过情绪分析')
    args = parser.parse_args()
    
    print("=" * 60)
    print("Video Audio Transcription Pipeline")
    print("=" * 60)
    
    # 输入输出路径
    video_before = get_video_before_merge()
    extract_file = video_before / "video_extract_v1.jsonl"
    output_file = video_before / "video_transcribe_v1.jsonl"
    
    print(f"  Input: {extract_file}")
    print(f"  Output: {output_file}")
    
    if not extract_file.exists():
        print(f"\n❌ Error: {extract_file} not found. Run _01_run_extract.py first.")
        sys.exit(1)
    
    # 读取提取结果
    extract_records = []
    with extract_file.open('r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                extract_records.append(json.loads(line))
    
    total = len(extract_records)
    print(f"\n[1/2] Found {total} video records.")
    
    if args.sample > 0:
        extract_records = extract_records[:args.sample]
        print(f"      Sample mode: processing only {len(extract_records)} files")
    
    if args.skip_emotion:
        print("      Emotion detection: SKIPPED")
    
    # 处理音频
    print("\n[2/2] Processing audio...")
    try:
        with output_file.open('w', encoding='utf-8') as f:
            for record in tqdm(extract_records, desc="音频转写", **tqdm_kwargs):
                if 'error' in record:
                    # 跳过提取失败的视频，但保留原始字段
                    result = {
                        'schema_version': SCHEMA_VERSION,
                        'file': record.get('file', ''),
                        'msg_uid': record.get('msg_uid', ''),
                        'seq_in_html': record.get('seq_in_html', -1),
                        'MsgSvrID': record.get('MsgSvrID', ''),
                        'token': record.get('token', ''),
                        'ts': record.get('ts', 0),
                        'time_local': record.get('time_local', ''),
                        'speaker': record.get('speaker', 'UNKNOWN'),
                        'type': record.get('type', 43),
                        'sub_type': record.get('sub_type', 0),
                        'modality': 'video',
                        'media_path': record.get('media_path', ''),
                        'error': record.get('error')
                    }
                else:
                    result = process_video_audio(record, skip_emotion=args.skip_emotion)
                
                f.write(json.dumps(result, ensure_ascii=False) + '\n')
    finally:
        # 确保卸载模型
        unload_models()
    
    print(f"\n✅ Done. Wrote {len(extract_records)} records to: {output_file}")


if __name__ == "__main__":
    main()
