#!/usr/bin/env python3
"""
语音情绪分析步骤（四阶段流程）

功能：
- 四阶段情绪分析流水线：SenseVoice → Triage → Qwen2-Audio → 人工审核
- 自动检测情绪标签（SAD/HAPPY/ANGRY/NEUTRAL）
- 识别声音事件（Cry/Laughter/Applause/Music）
- 基于规则的 Triage 筛选（情绪触发 + 关键词触发）
- 可选的 Qwen2-Audio 深度分析（语调特征、潜台词）
- 生成 Markdown 标注文件供人工审核

处理流程：
1. **加载转写结果**：
   - 从 voice_funasr_v2.jsonl 和 voice_whisper_v2.jsonl 加载文本
   - 作为情绪分析的上下文

2. **SenseVoice 情绪检测**：
   - 使用 SenseVoice 模型分析所有语音文件
   - 提取情绪标签（SAD/HAPPY/ANGRY/NEUTRAL）
   - 提取声音事件（Cry/Laughter/Applause/Music/BGM）
   - 清理标签后的文本

3. **Triage 筛选**：
   - 情绪触发：SAD/ANGRY/HAPPY
   - 事件触发：Cry/Laughter
   - 关键词触发：配置文件中的敏感词
   - 只有触发的样本才进入下一阶段

4. **Qwen2-Audio 深度分析**（可选）：
   - 对触发的样音进行深度分析
   - 提取语调特征、情绪状态、潜台词
   - 生成结构化的情绪描述
   - 支持数量限制（--qwen-limit）

5. **生成输出**：
   - voice_v3_labeling.md: Markdown 标注文件（人工审核用）
   - voice_merged_v3.jsonl: 合并结果（SenseVoice + Qwen）
   - voice_qwen_analysis.jsonl: Qwen 分析结果（独立保存）

输入：
- raw/voice/*.mp3: 原始语音文件
- artifacts/before_merge/voice/voice_funasr_v2.jsonl: FunASR 转写结果
- artifacts/before_merge/voice/voice_whisper_v2.jsonl: Whisper 转写结果
- configs/voice.yaml: 情绪分析配置（模型、触发规则、提示词）

输出：
- artifacts/before_merge/voice/voice_v3_labeling.md: Markdown 标注文件
- artifacts/before_merge/voice/voice_merged_v3.jsonl: 合并结果
- artifacts/before_merge/voice/voice_qwen_analysis.jsonl: Qwen 分析结果

依赖：
- funasr: SenseVoice 模型
- transformers: Qwen2-Audio 模型
- librosa: 音频加载
- scripts._common.path_utils: 路径工具

使用示例：
    python scripts/voice/run_all/_02_run_emotion.py                      # 全量分析
    python scripts/voice/run_all/_02_run_emotion.py --sample 10          # 采样测试
    python scripts/voice/run_all/_02_run_emotion.py --skip-qwen          # 仅 SenseVoice
    python scripts/voice/run_all/_02_run_emotion.py --qwen-limit 5       # 限制 Qwen 数量

注意事项：
- SenseVoice 和 Qwen2-Audio 会串行加载/卸载，避免显存溢出
- Triage 规则可在 configs/voice.yaml 中配置
- Qwen2-Audio 分析较慢，建议使用 --qwen-limit 限制数量
- Markdown 文件用于人工审核和标注

作者：forcifer
更新于：2026-02-02
"""

import os
import sys
import re
import gc
import json
import argparse
from pathlib import Path
from datetime import datetime
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

# ========== 从配置加载参数 ==========
voice_config = load_voice_config()
emotion_config = voice_config.get('emotion', {})
triage_config = voice_config.get('triage', {})
prompts_config = voice_config.get('prompts', {})

# SenseVoice 配置
sensevoice_cfg = emotion_config.get('sensevoice', {})
SENSEVOICE_MODEL_ID = sensevoice_cfg.get('model_id', 'iic/SenseVoiceSmall')

# Qwen2-Audio 配置
qwen_cfg = emotion_config.get('qwen_audio', {})
QWEN_AUDIO_MODEL_ID = qwen_cfg.get('model_path', '/data/models/qwen2-audio-7b-instruct')
QWEN_GENERATION = qwen_cfg.get('generation', {})

# Triage 配置
TRIAGE_CONFIG = {
    "emotion_triggers": set(triage_config.get('emotion_triggers', ['SAD', 'ANGRY', 'HAPPY'])),
    "event_triggers": set(triage_config.get('event_triggers', ['Cry', 'Laughter'])),
    "keywords": triage_config.get('keywords', {}),
}

# 系统提示词
QWEN_SYSTEM_PROMPT = prompts_config.get('qwen_system', '')

# 路径配置
AUDIO_DIR = get_voice_dir()
ARTIFACTS_DIR = get_voice_before_merge()

# 输入文件
FUNASR_RESULTS = ARTIFACTS_DIR / "voice_funasr_v2.jsonl"
WHISPER_RESULTS = ARTIFACTS_DIR / "voice_whisper_v2.jsonl"

# 输出文件
OUTPUT_LABELING_MD = ARTIFACTS_DIR / "voice_v3_labeling.md"
OUTPUT_MERGED_JSONL = ARTIFACTS_DIR / "voice_merged_v3.jsonl"
OUTPUT_QWEN_JSONL = ARTIFACTS_DIR / "voice_qwen_analysis.jsonl"


# ============================================================================
# 工具函数
# ============================================================================

def load_existing_transcripts() -> dict:
    """加载已有的转写结果作为上下文"""
    transcripts = {}
    
    for path in [FUNASR_RESULTS, WHISPER_RESULTS]:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        data = json.loads(line.strip())
                        filename = data.get("file", "")
                        text = data.get("punct_text") or data.get("text", "")
                        if filename and text:
                            transcripts[filename] = text
                    except json.JSONDecodeError:
                        continue
    
    return transcripts


def get_audio_files(sample_size: int = None) -> list:
    """获取音频文件列表"""
    audio_files = sorted(AUDIO_DIR.glob("*.mp3"))
    
    if sample_size and sample_size < len(audio_files):
        audio_files = audio_files[:sample_size]
    
    return audio_files


def check_keyword_trigger(text: str) -> tuple:
    """检查文本是否包含触发关键词"""
    matched = []
    for category, keywords in TRIAGE_CONFIG["keywords"].items():
        for kw in keywords:
            if kw in text:
                matched.append(f"{category}:{kw}")
    return len(matched) > 0, matched


# ============================================================================
# SenseVoice 模块
# ============================================================================

_sensevoice_model = None

def get_sensevoice_model():
    """单例模式加载 SenseVoice"""
    global _sensevoice_model
    if _sensevoice_model is None:
        from funasr import AutoModel
        print("[MODEL] 加载 SenseVoice...")
        _sensevoice_model = AutoModel(
            model=SENSEVOICE_MODEL_ID,
            trust_remote_code=sensevoice_cfg.get('trust_remote_code', True),
            device=sensevoice_cfg.get('device', 'cuda:0'),
            disable_update=sensevoice_cfg.get('disable_update', True)
        )
    return _sensevoice_model


def cleanup_sensevoice():
    """释放 SenseVoice 模型 VRAM"""
    global _sensevoice_model
    import torch
    
    if _sensevoice_model is not None:
        del _sensevoice_model
        _sensevoice_model = None
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.synchronize()
    print("[MODEL] SenseVoice 已释放")


def run_sensevoice(audio_files: list, transcripts: dict) -> list:
    """
    运行 SenseVoice 情绪分析
    
    使用 SenseVoice 模型对所有语音文件进行情绪检测，
    提取情绪标签和声音事件，并结合已有的转写结果作为上下文。
    
    SenseVoice 输出格式：<|EMOTION|><|EVENT|><|sil|>text
    - EMOTION: SAD, HAPPY, ANGRY, NEUTRAL
    - EVENT: Cry, Laughter, Applause, Music, BGM
    
    Args:
        audio_files: 音频文件路径列表
        transcripts: 已有转写结果字典 {filename: text}
    
    Returns:
        list: 分析结果列表，每个元素包含：
            - file: 文件名
            - sensevoice_raw: SenseVoice 原始输出（前200字符）
            - clean_text: 清理标签后的文本
            - context_text: 上下文文本（优先使用已有转写）
            - emotion_tags: 情绪标签列表
            - event_tags: 声音事件列表
            - error: 错误信息（如果失败）
    
    Example:
        >>> audio_files = [Path('voice1.mp3'), Path('voice2.mp3')]
        >>> transcripts = {'voice1.mp3': '你好吗'}
        >>> results = run_sensevoice(audio_files, transcripts)
        >>> print(results[0]['emotion_tags'])
        ['HAPPY']
        >>> print(results[0]['event_tags'])
        ['Laughter']
    
    Note:
        - 使用单例模式加载模型，避免重复加载
        - 处理完成后需要调用 cleanup_sensevoice() 释放显存
    """
    model = get_sensevoice_model()
    results = []
    batch_size_s = sensevoice_cfg.get('batch_size_s', 60)
    
    for audio_path in tqdm(audio_files, desc="SenseVoice分析", **tqdm_kwargs):
        try:
            res = model.generate(
                input=str(audio_path),
                cache={},
                language="auto",
                use_itn=True,
                batch_size_s=batch_size_s,
            )
            
            raw_text = res[0]["text"] if res else ""
            
            # 解析 SenseVoice 输出格式: <|EMO|><|EVENT|><|sil|>text
            emotion_pattern = r"<\|([A-Z]+)\|>"
            emotions = re.findall(emotion_pattern, raw_text)
            
            # 分类情绪和事件
            emotion_tags = [e for e in emotions if e in {"SAD", "HAPPY", "ANGRY", "NEUTRAL"}]
            event_tags = [e for e in emotions if e in {"Cry", "Laughter", "Applause", "Music", "BGM"}]
            
            # 清理文本
            clean_text = re.sub(r"<\|[^|]+\|>", "", raw_text).strip()
            
            # 使用已有转写结果补充
            filename = audio_path.name
            context_text = transcripts.get(filename, clean_text)
            
            result = {
                "file": filename,
                "sensevoice_raw": raw_text[:200],
                "clean_text": clean_text,
                "context_text": context_text,
                "emotion_tags": emotion_tags,
                "event_tags": event_tags,
            }
            results.append(result)
            
        except Exception as e:
            print(f"  [ERROR] {audio_path.name}: {e}")
            results.append({
                "file": audio_path.name,
                "error": str(e)
            })
    
    return results


# ============================================================================
# Qwen2-Audio 模块
# ============================================================================

def parse_qwen_response(response: str) -> dict:
    """解析 Qwen 自然语言输出为结构化字段"""
    result = {
        "tonal_features": "",
        "emotion_desc": "",
        "subtext": "",
        "emotion_tags": [],
        "raw_output": ""
    }
    
    # 只保留 assistant 回复部分
    if "assistant" in response.lower():
        parts = response.split("assistant")
        if len(parts) > 1:
            response = parts[-1].strip()
    
    response = response.strip()
    result["raw_output"] = response[:500] if len(response) > 500 else response
    
    # 提取各字段
    patterns = {
        "tonal_features": r"语调特征[：:]\s*([^\n]+)",
        "emotion_desc": r"情绪状态[：:]\s*([^\n]+(?:\n[^语潜情][^\n]*)*)",
        "subtext": r"潜台词[：:]\s*([^\n]+)",
        "emotion_tags_raw": r"情绪标签[：:]\s*([^\n]+)",
    }
    
    for key, pattern in patterns.items():
        match = re.search(pattern, response, re.IGNORECASE)
        if match:
            value = match.group(1).strip()
            if key == "emotion_tags_raw":
                tags = re.findall(r'(中性|伤心|愤怒|期待|无奈|疑惑|诱惑|兴奋|遗憾|担忧|委屈)', value)
                result["emotion_tags"] = tags
            else:
                result[key] = value
    
    if not result["emotion_desc"] and response:
        result["emotion_desc"] = response[:200]
    
    return result


def run_qwen_audio(audio_path: Path, context_text: str) -> dict:
    """
    运行 Qwen2-Audio 深度分析
    
    使用 Qwen2-Audio 多模态模型对语音进行深度情感分析，
    提取语调特征、情绪状态、潜台词等细粒度信息。
    
    分析维度：
    1. 语调特征：音调、语速、停顿等
    2. 情绪状态：详细的情绪描述
    3. 潜台词：隐含的意图和情感
    4. 情绪标签：细粒度标签（中性/伤心/愤怒/期待/无奈等）
    
    Args:
        audio_path: 音频文件路径
        context_text: 转写文本（作为上下文）
    
    Returns:
        dict: 分析结果，包含：
            - file: 文件名
            - punct_text: 转写文本
            - qwen_analysis: 分析结果字典
                * tonal_features: 语调特征
                * emotion_desc: 情绪状态描述
                * subtext: 潜台词
                * emotion_tags: 情绪标签列表
                * raw_output: 原始输出（前500字符）
            - error: 错误信息（如果失败）
    
    Example:
        >>> result = run_qwen_audio(Path('voice.mp3'), '我很好')
        >>> print(result['qwen_analysis']['emotion_desc'])
        '语气平静但略带疲惫，可能在掩饰真实情绪'
        >>> print(result['qwen_analysis']['emotion_tags'])
        ['无奈', '疲惫']
    
    Note:
        - 模型会在函数内加载和释放，避免显存占用
        - 分析较慢，建议只对触发的样本使用
        - 使用系统提示词引导模型输出结构化结果
    """
    import torch
    import librosa
    from transformers import Qwen2AudioForConditionalGeneration, AutoProcessor
    
    model = None
    processor = None
    
    try:
        print(f"  [QWEN] 分析: {audio_path.name}")
        
        # 加载模型
        processor = AutoProcessor.from_pretrained(QWEN_AUDIO_MODEL_ID)
        model = Qwen2AudioForConditionalGeneration.from_pretrained(
            QWEN_AUDIO_MODEL_ID,
            device_map=qwen_cfg.get('device_map', 'auto'),
            torch_dtype=getattr(torch, qwen_cfg.get('torch_dtype', 'float16'))
        )
        
        # 加载音频
        audio_data, sr = librosa.load(str(audio_path), sr=16000)
        
        # 构建对话
        user_content = f"请分析这段语音的情感特征。文字内容供参考：「{context_text[:100]}」"
        
        conversation = [
            {"role": "system", "content": QWEN_SYSTEM_PROMPT},
            {"role": "user", "content": [
                {"type": "audio", "audio_url": str(audio_path)},
                {"type": "text", "text": user_content},
            ]},
        ]
        
        text = processor.apply_chat_template(conversation, add_generation_prompt=True, tokenize=False)
        audios = [audio_data]
        
        inputs = processor(text=text, audios=audios, return_tensors="pt", padding=True)
        inputs = inputs.to(model.device)
        
        with torch.no_grad():
            output_ids = model.generate(
                **inputs,
                max_new_tokens=QWEN_GENERATION.get('max_new_tokens', 300)
            )
        
        response = processor.batch_decode(output_ids, skip_special_tokens=True)[0]
        analysis = parse_qwen_response(response)
        
        return {
            "file": audio_path.name,
            "punct_text": context_text,
            "qwen_analysis": analysis
        }
        
    except Exception as e:
        return {
            "file": audio_path.name,
            "error": str(e)
        }
    
    finally:
        if model is not None:
            del model
        if processor is not None:
            del processor
        gc.collect()
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()


# ============================================================================
# Triage 模块
# ============================================================================

def run_triage(sensevoice_results: list) -> list:
    """
    执行 Triage 筛选
    
    基于规则筛选需要深度分析的语音样本，减少 Qwen2-Audio 的计算量。
    
    触发条件（满足任一即触发）：
    1. 情绪触发：检测到 SAD/ANGRY/HAPPY 等情绪
    2. 事件触发：检测到 Cry/Laughter 等声音事件
    3. 关键词触发：文本包含配置的敏感词
    
    Args:
        sensevoice_results: SenseVoice 分析结果列表
    
    Returns:
        list: 触发的样本列表，每个元素增加：
            - trigger_reasons: 触发原因列表
              格式：['emotion:SAD', 'event:Cry', 'keyword:死']
    
    Example:
        >>> results = [
        ...     {'file': 'v1.mp3', 'emotion_tags': ['SAD'], 'context_text': '我很难过'},
        ...     {'file': 'v2.mp3', 'emotion_tags': ['NEUTRAL'], 'context_text': '今天天气不错'}
        ... ]
        >>> triggered = run_triage(results)
        >>> print(len(triggered))
        1
        >>> print(triggered[0]['trigger_reasons'])
        ['emotion:SAD', 'keyword:难过']
    
    Note:
        - 触发规则在 configs/voice.yaml 中配置
        - 可以通过修改配置调整触发灵敏度
    """
    triggered = []
    
    for item in sensevoice_results:
        if "error" in item:
            continue
        
        reasons = []
        
        # 检查情绪触发
        for emo in item.get("emotion_tags", []):
            if emo in TRIAGE_CONFIG["emotion_triggers"]:
                reasons.append(f"emotion:{emo}")
        
        # 检查事件触发
        for evt in item.get("event_tags", []):
            if evt in TRIAGE_CONFIG["event_triggers"]:
                reasons.append(f"event:{evt}")
        
        # 检查关键词触发
        text = item.get("context_text", "") or item.get("clean_text", "")
        kw_triggered, kw_matches = check_keyword_trigger(text)
        if kw_triggered:
            reasons.extend(kw_matches)
        
        if reasons:
            item["trigger_reasons"] = reasons
            triggered.append(item)
    
    return triggered


# ============================================================================
# 输出生成
# ============================================================================

def generate_labeling_md(sensevoice_results: list, triggered_files: set) -> str:
    """生成 Markdown 标注文件"""
    lines = [
        "# 语音情绪标注表 v3",
        "",
        f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"**总样本**: {len(sensevoice_results)}",
        f"**触发样本**: {len(triggered_files)}",
        "",
        "**标注说明**：",
        "- 在 `你的标注:` 后填入情绪标签",
        "- 可选: 中性 / 伤心 / 疑惑 / 生气 / 期待 / 无奈 / 遗憾 等",
        "- 空白表示默认 OK",
        "",
        "---",
        ""
    ]
    
    for idx, item in enumerate(sensevoice_results, 1):
        filename = item.get("file", "unknown")
        text = item.get("context_text", "") or item.get("clean_text", "")
        emotions = item.get("emotion_tags", ["NEUTRAL"])
        is_triggered = filename in triggered_files
        
        emotion_str = str(emotions) if emotions else "NEUTRAL"
        triage_str = "✅ 触发" if is_triggered else "⏭️ 跳过"
        
        lines.extend([
            f"## {idx}. {filename}",
            "",
            f"> {text}",
            "",
            "| SenseVoice | Triage |",
            "|------------|--------|",
            f"| {emotion_str} | {triage_str} |",
            "",
            "**你的标注**: ",
            "",
            "---",
            ""
        ])
    
    return "\n".join(lines)


def generate_merged_jsonl(sensevoice_results: list, qwen_results: list) -> list:
    """生成合并的 JSONL 数据"""
    qwen_lookup = {r["file"]: r for r in qwen_results if "file" in r}
    
    merged = []
    for sv in sensevoice_results:
        filename = sv.get("file", "")
        
        entry = {
            "schema_version": "v3",
            "file": filename,
            "punct_text": sv.get("context_text", ""),
            "sensevoice": {
                "emotion_tags": sv.get("emotion_tags", []),
                "event_tags": sv.get("event_tags", []),
                "clean_text": sv.get("clean_text", ""),
            },
            "trigger_reasons": sv.get("trigger_reasons", []),
        }
        
        if filename in qwen_lookup:
            qwen_data = qwen_lookup[filename]
            qwen_analysis = qwen_data.get("qwen_analysis", {})
            entry["voice_analysis"] = {
                "emotion_desc": qwen_analysis.get("emotion_desc", ""),
                "tonal_features": qwen_analysis.get("tonal_features", ""),
                "subtext": qwen_analysis.get("subtext", ""),
                "emotion_tags": qwen_analysis.get("emotion_tags", []),
            }
        
        merged.append(entry)
    
    return merged


# ============================================================================
# 主流程
# ============================================================================

def main():
    """
    主函数：语音情绪分析流水线
    
    四阶段处理流程：
    1. 加载转写结果（FunASR + Whisper）
    2. SenseVoice 情绪检测（所有样本）
    3. Triage 筛选（基于规则）
    4. Qwen2-Audio 深度分析（触发的样本）
    5. 生成输出文件
    
    命令行参数：
        --sample N: 仅处理前 N 个文件（测试用）
        --skip-qwen: 跳过 Qwen2-Audio 分析
        --qwen-limit N: 限制 Qwen 分析数量（0=全部触发）
        --force: 强制重新生成（暂未实现）
    
    输出文件：
        1. voice_v3_labeling.md: Markdown 标注文件
           - 包含所有样本的情绪标签
           - 标记触发/跳过状态
           - 供人工审核和标注
        
        2. voice_merged_v3.jsonl: 合并结果
           - SenseVoice 情绪标签
           - Triage 触发原因
           - Qwen2-Audio 分析结果（如有）
        
        3. voice_qwen_analysis.jsonl: Qwen 分析结果
           - 独立保存 Qwen 的详细分析
           - 便于后续分析和调试
    
    显存管理：
        - SenseVoice 和 Qwen2-Audio 串行加载
        - 每个阶段完成后释放显存
        - 使用 gc.collect() + torch.cuda.empty_cache()
    
    Example:
        $ python scripts/voice/run_all/_02_run_emotion.py --sample 100 --qwen-limit 10
        ======================================================================
        Voice Emotion Analysis Pipeline v3
        ======================================================================
          Audio Dir: /data/workspace/raw/voice
          Output Dir: artifacts/before_merge/voice
        
        [1/5] 加载转写结果...
              已加载 100 条转写
        
        [2/5] 获取音频文件...
              找到 100 个音频文件
        
        ======================================================================
        [3/5] SenseVoice 情绪分析
        ======================================================================
        SenseVoice分析: 100%|████████████| 100/100 [02:15<00:00, 0.74it/s]
        [MODEL] SenseVoice 已释放
        
        ======================================================================
        [4/5] Triage 筛选
        ======================================================================
              触发: 25 / 100
        
        ======================================================================
        [4.5/5] Qwen2-Audio 深度分析 (限制 10, 共 10 条)
        ======================================================================
          [QWEN] 分析: voice_001.mp3
          [QWEN] 分析: voice_002.mp3
          ...
              完成: 10 条
        
        ======================================================================
        [5/5] 生成输出文件
        ======================================================================
              Markdown: artifacts/before_merge/voice/voice_v3_labeling.md
              Qwen分析: artifacts/before_merge/voice/voice_qwen_analysis.jsonl
              合并文件: artifacts/before_merge/voice/voice_merged_v3.jsonl
        
        ======================================================================
        完成摘要
        ======================================================================
          SenseVoice 分析: 100 条
          Triage 触发: 25 条
          Qwen2-Audio: 10 条
    """
    parser = argparse.ArgumentParser(description="Voice Emotion Analysis Pipeline v3")
    parser.add_argument("--sample", type=int, default=None, help="处理样本数 (默认全部)")
    parser.add_argument("--skip-qwen", action="store_true", help="跳过 Qwen2-Audio 分析")
    parser.add_argument("--qwen-limit", type=int, default=0, help="Qwen 分析数量限制 (默认0=全部触发)")
    parser.add_argument("--force", action="store_true", help="强制重新生成")
    args = parser.parse_args()
    
    print("=" * 70)
    print("Voice Emotion Analysis Pipeline v3")
    print("=" * 70)
    print(f"  Audio Dir: {AUDIO_DIR}")
    print(f"  Output Dir: {ARTIFACTS_DIR}")
    
    # 加载现有转写
    print("\n[1/5] 加载转写结果...")
    transcripts = load_existing_transcripts()
    print(f"      已加载 {len(transcripts)} 条转写")
    
    # 获取音频文件
    print("\n[2/5] 获取音频文件...")
    audio_files = get_audio_files(args.sample)
    print(f"      找到 {len(audio_files)} 个音频文件")
    
    # Phase 1: SenseVoice
    print("\n" + "=" * 70)
    print("[3/5] SenseVoice 情绪分析")
    print("=" * 70)
    sensevoice_results = run_sensevoice(audio_files, transcripts)
    cleanup_sensevoice()
    
    # Phase 2: Triage
    print("\n" + "=" * 70)
    print("[4/5] Triage 筛选")
    print("=" * 70)
    triggered_items = run_triage(sensevoice_results)
    triggered_files = {item["file"] for item in triggered_items}
    print(f"      触发: {len(triggered_items)} / {len(sensevoice_results)}")
    
    # Phase 3: Qwen2-Audio (可选)
    qwen_results = []
    if not args.skip_qwen and triggered_items:
        items_to_analyze = triggered_items if args.qwen_limit == 0 else triggered_items[:args.qwen_limit]
        limit_str = "全部" if args.qwen_limit == 0 else f"限制 {args.qwen_limit}"
        
        print("\n" + "=" * 70)
        print(f"[4.5/5] Qwen2-Audio 深度分析 ({limit_str}, 共 {len(items_to_analyze)} 条)")
        print("=" * 70)
        
        for item in items_to_analyze:
            audio_path = AUDIO_DIR / item["file"]
            if audio_path.exists():
                result = run_qwen_audio(audio_path, item.get("context_text", ""))
                qwen_results.append(result)
        
        print(f"      完成: {len(qwen_results)} 条")
    else:
        print("\n[4.5/5] 跳过 Qwen2-Audio 分析")
    
    # Phase 4: 生成输出
    print("\n" + "=" * 70)
    print("[5/5] 生成输出文件")
    print("=" * 70)
    
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    
    # 生成 Markdown 标注文件
    labeling_md = generate_labeling_md(sensevoice_results, triggered_files)
    OUTPUT_LABELING_MD.write_text(labeling_md, encoding="utf-8")
    print(f"      Markdown: {OUTPUT_LABELING_MD}")
    
    # 保存 Qwen 分析结果
    if qwen_results:
        with open(OUTPUT_QWEN_JSONL, "w", encoding="utf-8") as f:
            for entry in qwen_results:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        print(f"      Qwen分析: {OUTPUT_QWEN_JSONL}")
    
    # 生成 JSONL
    merged = generate_merged_jsonl(sensevoice_results, qwen_results)
    with open(OUTPUT_MERGED_JSONL, "w", encoding="utf-8") as f:
        for entry in merged:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(f"      合并文件: {OUTPUT_MERGED_JSONL}")
    
    # 摘要
    print("\n" + "=" * 70)
    print("完成摘要")
    print("=" * 70)
    print(f"  SenseVoice 分析: {len(sensevoice_results)} 条")
    print(f"  Triage 触发: {len(triggered_items)} 条")
    print(f"  Qwen2-Audio: {len(qwen_results)} 条")


if __name__ == "__main__":
    main()
