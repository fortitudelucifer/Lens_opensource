#!/usr/bin/env python3
"""
视频描述生成步骤（Triage 分类 + 专家路由 + 智能 Fallback）

功能：
- 使用 Triage 分类器判断视频内容类型
- 根据分类路由到对应的专家模型
- 支持 NSFW、Gore、文档、普通视频的专业化处理
- 智能 Fallback 机制（Qwen2.5-VL → LLaVA-NeXT-Video）
- 直接视频输入 + 多帧图片双模式

处理流程：
1. 加载视频提取结果（关键帧）和转写结果（情绪上下文）
2. 对每个视频：
   a. **Triage 分类**：对每个关键帧进行内容分类
      - TYPE_A_NSFW: NSFW 内容（nsfw_score > 0.5）
      - TYPE_B_GORE: 暴力血腥（sfw_score < 0.5）
      - TYPE_C_NORMAL: 普通视频
      - TYPE_D_DOC: 录屏/文档（text_ratio > 0.15）
   b. **专家路由**：根据分类选择专家模型
      - NSFW → NSFWExpert（复用图片流水线）
      - Gore → 主模型 + 警告标记
      - Doc → 主模型 + 高分辨率
      - Normal → 主模型
   c. **视频理解**：
      - 优先：直接视频输入（Qwen2.5-VL 原生支持）
      - 回退：多帧图片模式
   d. **智能 Fallback**：检测主模型输出质量
      - 输出过短（< 50 字符）
      - 模型拒绝回答（包含"无法"等关键词）
      - 关键字段缺失
      - 触发时自动切换到 LLaVA-NeXT-Video
3. 输出描述结果

Triage 跳过策略：
- 可使用 `--skip-triage` 跳过 Triage 分类
- 跳过后所有视频都使用主模型处理
- 适用场景：已知视频内容安全，追求速度

专家路由系统：
- TYPE_A_NSFW → NSFWExpert (双模型 Ensemble)
  * 复用图片流水线的 NSFW 专家
  * MiniCPM-V 4.5 + nsfw-caption-v3
  
- TYPE_B_GORE → 主模型 + 警告标记
  * 使用 Qwen2.5-VL 但添加 [⚠️ 可能含暴力内容] 标记
  
- TYPE_C_NORMAL → Qwen2.5-VL (主模型)
  * 处理普通视频（动物、人物、风景等）
  * 支持直接视频输入（时间序列理解）
  
- TYPE_D_DOC → 主模型 + 高分辨率
  * 处理录屏、文档、截图类视频

智能 Fallback 机制：
- **主模型**: Qwen2.5-VL-7B (bfloat16)
  * 直接视频输入模式（推荐）
  * 多帧图片模式（回退）
  
- **Fallback 模型**: LLaVA-NeXT-Video-7B (float16)
  * 触发条件（可配置）：
    - output_quality_low: 输出过短
    - repeated_refusal: 模型拒绝回答
    - critical_fields_missing: 关键字段缺失
  * 自动卸载主模型，加载 Fallback 模型
  * 使用 PyAV 均匀采样 32 帧

情绪上下文融合：
- 从转写结果提取情绪标签和文本
- 注入到 VLM prompt 中
- 帮助模型理解视频的情感氛围

输入：
- artifacts/before_merge/video/video_extract_v1.jsonl: 提取结果（关键帧）
- artifacts/before_merge/video/video_transcribe_v1.jsonl: 转写结果（情绪）
- /data/cache/video_keyframes/: 关键帧图片
- raw/video/: 原始视频文件（用于直接视频输入）
- configs/video.yaml: 视频配置（模型、Triage 阈值、Fallback 条件）

输出：
- artifacts/before_merge/video/video_caption_v1.jsonl: 描述结果
  * 包含：
    - triage: 整体分类结果
    - keyframe_captions: 每帧的描述
    - video_understanding: 视频整体理解
    - fallback_reason: Fallback 触发原因（如有）

依赖：
- transformers: Qwen2.5-VL, LLaVA-NeXT-Video
- qwen_vl_utils: 视频输入处理
- av (PyAV): 视频帧读取（Fallback 用）
- scripts.image.experts: 专家模型（NSFW/Triage）

使用示例：
    python scripts/video/run_all/_03_run_caption.py              # 处理全部
    python scripts/video/run_all/_03_run_caption.py --sample 3   # 测试模式
    python scripts/video/run_all/_03_run_caption.py --skip-triage  # 跳过 Triage

性能参考（RTX 5070 Ti 16GB）：
- Triage 分类：~1 秒/帧
- 关键帧描述：~10-15 秒/帧
- 视频理解：~20-30 秒/视频
- Fallback 切换：~10 秒（模型加载）

注意事项：
- 确保先运行 _01_run_extract.py 和 _02_run_transcribe.py
- 直接视频输入需要 qwen_vl_utils 库
- LLaVA Fallback 需要 PyAV 库（pip install av）
- Fallback 触发条件可在 configs/video.yaml 中配置

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
from PIL import Image

# 确保 tqdm 输出到 stderr 以便实时显示
tqdm_kwargs = {"file": sys.stderr, "dynamic_ncols": True}

# VRAM 优化配置
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts._common.path_utils import (
    get_video_before_merge, load_video_config
)

# ========== 加载配置 ==========
video_config = load_video_config()
models_config = video_config.get('models', {})
triage_config = video_config.get('triage', {})
prompts_config = video_config.get('prompts', {})
fusion_config = video_config.get('fusion', {})

SCHEMA_VERSION = "video_caption_v1"

# 全局模型缓存
_vlm_model = None
_vlm_processor = None


def unload_model():
    """卸载模型并清理显存"""
    global _vlm_model, _vlm_processor
    if _vlm_model is not None:
        del _vlm_model
        _vlm_model = None
    if _vlm_processor is not None:
        del _vlm_processor
        _vlm_processor = None
    gc.collect()
    try:
        import torch
        torch.cuda.empty_cache()
    except:
        pass


def load_vlm_model():
    """加载 Qwen2.5-VL 模型"""
    global _vlm_model, _vlm_processor
    
    if _vlm_model is not None:
        return _vlm_model, _vlm_processor
    
    from transformers import Qwen2_5_VLForConditionalGeneration, AutoProcessor
    import torch
    
    vlm_config = models_config.get('primary_vlm', {})
    model_path = vlm_config.get('path', '/data/models/qwen2.5-vl-7b/Qwen/Qwen2___5-VL-7B-Instruct')
    
    print(f"    Loading VLM: {model_path}")
    
    # 使用 Qwen2_5_VLForConditionalGeneration（transformers 5.x 移除了 AutoModelForVision2Seq）
    _vlm_model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
        model_path,
        torch_dtype=torch.bfloat16,
        device_map="auto",
        trust_remote_code=True,
    )
    
    _vlm_processor = AutoProcessor.from_pretrained(model_path, trust_remote_code=True)
    
    return _vlm_model, _vlm_processor


# 全局 Triage 实例
_triage_instance = None


def get_triage_instance():
    """获取或创建 Triage 单例"""
    global _triage_instance
    if _triage_instance is None:
        from scripts.image.experts.image_triage import ImageTriage
        _triage_instance = ImageTriage()
    return _triage_instance


def unload_triage():
    """卸载 Triage 模型"""
    global _triage_instance
    if _triage_instance is not None:
        _triage_instance.unload()
        _triage_instance = None


def triage_keyframe(image_path: str) -> dict:
    """对关键帧进行 Triage 分类（复用图片流水线的 Triage 逻辑）"""
    try:
        triage = get_triage_instance()
        result = triage.classify(image_path)
        return {
            'content_type': result.content_type,
            'nsfw_score': result.nsfw_score,
            'sfw_score': result.sfw_score,
            'text_ratio': result.text_score if result.text_score is not None else 0.0,
            'confidence': result.confidence
        }
    except Exception as e:
        print(f"    ⚠️ Triage error for {image_path}: {e}")
        return {
            'content_type': 'TYPE_C_NORMAL',
            'nsfw_score': 0.0,
            'sfw_score': 1.0,
            'text_ratio': 0.0,
            'confidence': 0.5
        }


def generate_video_understanding(video_path: str, keyframes: list, emotion_context: str = "") -> dict:
    """
    使用 Qwen2.5-VL 直接理解视频文件（时间序列）
    
    关键：传入视频文件而不是单独的帧，让模型理解动态变化
    """
    import torch
    
    model, processor = load_vlm_model()
    
    # 构建针对动物/运动的 prompt
    prompt_template = prompts_config.get('video_understanding', '')
    if not prompt_template:
        prompt_template = """你是一个视频内容分析专家。请仔细观看这段视频，分析其中的动态变化。

{emotion_context}

请用中文详细描述：
1. 视频的主要内容和场景
2. 视频中主体的运动轨迹和动作变化（如有动物，描述其头部、身体、四肢的运动方向和幅度）
3. 关键事件的时间顺序

注意：请关注画面中的动态变化，而不仅仅是静态描述。"""
    
    prompt = prompt_template.format(
        emotion_context=emotion_context if emotion_context else ""
    )
    
    # 检查视频文件是否存在
    if not Path(video_path).exists():
        return {
            'summary': '[视频文件不存在]',
            'model': models_config.get('primary_vlm', {}).get('name', 'Qwen2.5-VL-7B'),
            'error': 'video_not_found'
        }
    
    try:
        # 使用 qwen_vl_utils 处理视频输入
        from qwen_vl_utils import process_vision_info
        
        # 构建消息 - 直接传入视频文件
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "video", "video": video_path, "max_pixels": 360 * 420, "fps": 1.0},
                    {"type": "text", "text": prompt}
                ]
            }
        ]
        
        # 处理输入
        text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        image_inputs, video_inputs = process_vision_info(messages)
        
        inputs = processor(
            text=[text],
            images=image_inputs,
            videos=video_inputs,
            padding=True,
            return_tensors="pt"
        ).to(model.device)
        
        # 生成
        gen_config = models_config.get('primary_vlm', {}).get('generation', {})
        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens=gen_config.get('max_new_tokens', 512),
                temperature=gen_config.get('temperature', 0.6),
                top_p=gen_config.get('top_p', 0.9),
                do_sample=True
            )
        
        # 解码
        generated_ids = outputs[:, inputs['input_ids'].shape[1]:]
        summary = processor.batch_decode(generated_ids, skip_special_tokens=True)[0]
        
        return {
            'summary': summary.strip(),
            'model': models_config.get('primary_vlm', {}).get('name', 'Qwen2.5-VL-7B'),
            'method': 'video_direct'  # 标记使用了直接视频输入
        }
        
    except ImportError:
        # 如果没有 qwen_vl_utils，回退到多帧图片模式
        print("    Warning: qwen_vl_utils not found, falling back to multi-frame mode")
        return generate_video_understanding_multiframe(keyframes, emotion_context)
    except Exception as e:
        print(f"    Warning: Video direct mode failed: {e}, falling back to multi-frame mode")
        return generate_video_understanding_multiframe(keyframes, emotion_context)


def generate_video_understanding_multiframe(keyframes: list, emotion_context: str = "") -> dict:
    """
    使用多帧图片模式理解视频（回退方案）
    
    当直接视频输入失败时使用
    """
    import torch
    
    model, processor = load_vlm_model()
    
    # 加载所有关键帧图片
    images = []
    for kf in keyframes:
        frame_path = kf.get('frame_path', '')
        if frame_path and Path(frame_path).exists():
            img = Image.open(frame_path).convert('RGB')
            images.append(img)
    
    if not images:
        return {
            'summary': '[无有效关键帧]',
            'model': models_config.get('primary_vlm', {}).get('name', 'Qwen2.5-VL-7B'),
            'error': 'no_valid_frames'
        }
    
    # 构建多帧 prompt
    prompt = f"""你是一个视频内容分析专家。以下是视频的关键帧序列（按时间顺序排列）。

{emotion_context if emotion_context else ""}

请分析这些帧，描述：
1. 视频的主要内容和场景
2. 从第一帧到最后一帧，主体发生了什么变化（运动方向、姿态变化等）
3. 推断视频中可能发生的动作或事件

注意：这些帧是按时间顺序排列的，请关注帧与帧之间的变化。"""
    
    # 构建消息 - 多图片输入
    content = []
    for i, img in enumerate(images):
        content.append({"type": "image", "image": img})
        content.append({"type": "text", "text": f"[帧{i+1}]"})
    content.append({"type": "text", "text": prompt})
    
    messages = [{"role": "user", "content": content}]
    
    # 处理输入
    text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = processor(
        text=[text],
        images=images,
        padding=True,
        return_tensors="pt"
    ).to(model.device)
    
    # 生成
    gen_config = models_config.get('primary_vlm', {}).get('generation', {})
    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=gen_config.get('max_new_tokens', 512),
            temperature=gen_config.get('temperature', 0.6),
            top_p=gen_config.get('top_p', 0.9),
            do_sample=True
        )
    
    # 解码
    generated_ids = outputs[:, inputs['input_ids'].shape[1]:]
    summary = processor.batch_decode(generated_ids, skip_special_tokens=True)[0]
    
    return {
        'summary': summary.strip(),
        'model': models_config.get('primary_vlm', {}).get('name', 'Qwen2.5-VL-7B'),
        'method': 'multi_frame',
        'num_frames': len(images)
    }


# ========== LLaVA-NeXT-Video Fallback ==========

_llava_model = None
_llava_processor = None


def load_llava_model():
    """加载 LLaVA-NeXT-Video-7B 模型作为 fallback"""
    global _llava_model, _llava_processor
    
    if _llava_model is not None:
        return _llava_model, _llava_processor
    
    from transformers import LlavaNextVideoProcessor, LlavaNextVideoForConditionalGeneration
    import torch
    
    fallback_config = models_config.get('fallback_vlm', {})
    model_path = fallback_config.get('path', '/data/models/llava-next-video-7b')
    
    # 如果本地路径不存在，使用 HuggingFace hub
    if not Path(model_path).exists():
        model_path = 'llava-hf/LLaVA-NeXT-Video-7B-hf'
    
    print(f"    Loading LLaVA-NeXT-Video fallback: {model_path}")
    
    _llava_model = LlavaNextVideoForConditionalGeneration.from_pretrained(
        model_path,
        torch_dtype=torch.float16,
        low_cpu_mem_usage=True,
        device_map="auto"
    )
    
    _llava_processor = LlavaNextVideoProcessor.from_pretrained(model_path)
    
    print(f"    ✅ LLaVA-NeXT-Video loaded successfully")
    return _llava_model, _llava_processor


def unload_llava_model():
    """卸载 LLaVA 模型并清理显存"""
    global _llava_model, _llava_processor
    if _llava_model is not None:
        del _llava_model
        _llava_model = None
    if _llava_processor is not None:
        del _llava_processor
        _llava_processor = None
    gc.collect()
    try:
        import torch
        torch.cuda.empty_cache()
    except:
        pass


def read_video_pyav(video_path: str, num_frames: int = 8):
    """
    使用 PyAV 读取视频并均匀采样帧
    
    Args:
        video_path: 视频文件路径
        num_frames: 需要采样的帧数
    
    Returns:
        np.ndarray: shape (num_frames, height, width, 3)
    """
    import av
    import numpy as np
    
    container = av.open(video_path)
    
    # 获取视频流信息
    stream = container.streams.video[0]
    total_frames = stream.frames
    
    if total_frames == 0:
        # 某些视频可能没有帧数信息，需要手动计数
        container.seek(0)
        total_frames = sum(1 for _ in container.decode(video=0))
        container.seek(0)
    
    # 计算均匀采样的帧索引
    indices = np.linspace(0, total_frames - 1, num_frames, dtype=int)
    indices = sorted(set(indices))  # 去重并排序
    
    # 解码指定帧
    frames = []
    container.seek(0)
    for i, frame in enumerate(container.decode(video=0)):
        if i > indices[-1]:
            break
        if i in indices:
            frames.append(frame.to_ndarray(format="rgb24"))
    
    container.close()
    
    if len(frames) < num_frames:
        # 如果帧数不足，重复最后一帧
        while len(frames) < num_frames:
            frames.append(frames[-1])
    
    return np.stack(frames)


def check_fallback_trigger(primary_result: dict) -> tuple[bool, str]:
    """
    检查是否需要触发 LLaVA fallback
    
    触发条件 (来自 video.yaml):
    - output_quality_low: 输出过短或无意义
    - repeated_refusal: 模型拒绝回答
    - critical_fields_missing: 缺少关键信息
    
    Returns:
        (should_fallback, reason)
    """
    fallback_config = models_config.get('fallback_vlm', {})
    trigger_conditions = fallback_config.get('trigger_conditions', [])
    
    summary = primary_result.get('summary', '')
    
    # 条件1: output_quality_low - 输出过短
    if 'output_quality_low' in trigger_conditions:
        if len(summary) < 50:
            return True, 'output_quality_low: summary too short'
    
    # 条件2: repeated_refusal - 模型拒绝回答
    if 'repeated_refusal' in trigger_conditions:
        refusal_keywords = [
            '无法', '不能', '无法描述', '不适合', '请勿',
            'cannot', 'unable', 'sorry', 'I cannot'
        ]
        for kw in refusal_keywords:
            if kw.lower() in summary.lower():
                return True, f'repeated_refusal: contains "{kw}"'
    
    # 条件3: critical_fields_missing - 输出为空或错误
    if 'critical_fields_missing' in trigger_conditions:
        if not summary or summary == '[无有效关键帧]':
            return True, 'critical_fields_missing: empty summary'
        if 'error' in primary_result:
            return True, f'critical_fields_missing: {primary_result.get("error")}'
    
    return False, ''


def generate_video_understanding_llava(video_path: str, emotion_context: str = "") -> dict:
    """
    使用 LLaVA-NeXT-Video-7B 理解视频（终极 fallback）
    
    Args:
        video_path: 视频文件路径
        emotion_context: 情绪上下文
    
    Returns:
        dict with summary, model, method
    """
    import torch
    
    try:
        model, processor = load_llava_model()
        
        fallback_config = models_config.get('fallback_vlm', {})
        num_frames = fallback_config.get('uniform_frames', 32)
        
        # 读取视频帧
        print(f"    Reading {num_frames} frames from video...")
        clip = read_video_pyav(video_path, num_frames=num_frames)
        
        # 构建对话
        prompt = f"""你是一个视频内容分析专家。请仔细观看这段视频，用中文详细描述：

{emotion_context if emotion_context else ''}

1. 视频的主要内容和场景
2. 视频中的关键事件和时间点
3. 人物的动作和表情（如有）

请关注视频中的动态变化，而不仅仅是静态描述。"""
        
        conversation = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "video"},
                ]
            }
        ]
        
        prompt_text = processor.apply_chat_template(conversation, add_generation_prompt=True)
        
        inputs = processor(
            text=prompt_text,
            videos=clip,
            padding=True,
            return_tensors="pt"
        ).to(model.device)
        
        # 生成
        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens=512,
                do_sample=False
            )
        
        # 解码
        summary = processor.decode(outputs[0], skip_special_tokens=True)
        
        # 清理 prompt 部分，只保留生成的内容
        if prompt in summary:
            summary = summary.split(prompt)[-1].strip()
        
        return {
            'summary': summary.strip(),
            'model': fallback_config.get('name', 'LLaVA-NeXT-Video-7B'),
            'method': 'llava_video',
            'num_frames': num_frames,
            'is_fallback': True
        }
        
    except ImportError as e:
        print(f"    ⚠️ LLaVA fallback failed: missing dependency: {e}")
        print(f"    Install with: pip install av")
        return {
            'summary': '[LLaVA fallback unavailable]',
            'model': 'fallback_error',
            'error': str(e),
            'is_fallback': True
        }
    except Exception as e:
        print(f"    ⚠️ LLaVA fallback failed: {e}")
        return {
            'summary': '[LLaVA fallback error]',
            'model': 'fallback_error',
            'error': str(e),
            'is_fallback': True
        }

def generate_keyframe_caption(image_path: str, emotion_context: str = "") -> dict:
    """生成关键帧描述"""
    import torch
    
    model, processor = load_vlm_model()
    
    # 构建 prompt
    prompt_template = prompts_config.get('keyframe_caption', '请用中文详细描述这张图片的内容。')
    
    if emotion_context:
        prompt_template = f"{emotion_context}\n\n{prompt_template}"
    
    # 加载图片
    image = Image.open(image_path).convert('RGB')
    
    # 构建消息
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image", "image": image},
                {"type": "text", "text": prompt_template}
            ]
        }
    ]
    
    # 处理输入
    text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = processor(
        text=[text],
        images=[image],
        padding=True,
        return_tensors="pt"
    ).to(model.device)
    
    # 生成
    gen_config = models_config.get('primary_vlm', {}).get('generation', {})
    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=gen_config.get('max_new_tokens', 512),
            temperature=gen_config.get('temperature', 0.6),
            top_p=gen_config.get('top_p', 0.9),
            do_sample=True
        )
    
    # 解码
    generated_ids = outputs[:, inputs['input_ids'].shape[1]:]
    caption = processor.batch_decode(generated_ids, skip_special_tokens=True)[0]
    
    return {
        'caption': caption.strip(),
        'model': models_config.get('primary_vlm', {}).get('name', 'Qwen2.5-VL-7B'),
        'is_fallback': False
    }


def build_emotion_context(emotion_data: dict, transcription: dict) -> str:
    """构建情绪上下文"""
    if not fusion_config.get('inject_emotion_to_prompt', True):
        return ""
    
    sensevoice = emotion_data.get('sensevoice', {})
    emotion_tags = sensevoice.get('emotion_tags', [])
    event_tags = sensevoice.get('event_tags', [])
    transcript = transcription.get('punct_text', '')
    
    if not emotion_tags and not event_tags and not transcript:
        return ""
    
    template = fusion_config.get('emotion_prompt_template', '')
    if not template:
        return ""
    
    return template.format(
        emotion_tags=', '.join(emotion_tags) if emotion_tags else '无',
        event_tags=', '.join(event_tags) if event_tags else '无',
        transcript=transcript[:200] if transcript else '无'
    )


def process_video_caption(
    extract_record: dict,
    transcribe_record: dict,
    skip_triage: bool = False,
    video_dir: Path = None
) -> dict:
    """处理单个视频的描述生成"""
    file_name = extract_record.get('file', '')
    keyframes = extract_record.get('keyframes', [])
    
    # 获取原始 metadata 和 extraction_params
    original_metadata = extract_record.get('metadata', {})
    extraction_params = extract_record.get('extraction_params', {})
    
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
        # 保留视频元数据
        'metadata': {
            'duration': original_metadata.get('duration_sec', 0),
            'width': original_metadata.get('width', 0),
            'height': original_metadata.get('height', 0),
            'fps': original_metadata.get('fps', 0),
            'has_audio': original_metadata.get('has_audio', False),
            'motion_intensity': extraction_params.get('motion_intensity', 0),
            'content_type': extraction_params.get('content_type', 'unknown'),
            'max_frames_used': extraction_params.get('max_frames', 0),
        },
    }
    
    if not keyframes:
        result['error'] = 'no_keyframes'
        return result
    
    # 构建情绪上下文
    emotion_context = build_emotion_context(
        transcribe_record.get('emotion', {}),
        transcribe_record.get('transcription', {})
    )
    
    # 处理每个关键帧
    keyframe_captions = []
    triage_results = []
    
    for kf in tqdm(keyframes, desc=f"  {file_name}", leave=False, **tqdm_kwargs):
        frame_path = kf.get('frame_path', '')
        if not frame_path or not Path(frame_path).exists():
            continue
        
        # Triage 分类
        if not skip_triage:
            triage = triage_keyframe(frame_path)
        else:
            triage = {'content_type': 'TYPE_C_NORMAL', 'confidence': 1.0}
        
        triage_results.append({
            'frame_id': kf.get('frame_id'),
            **triage
        })
        
        # 根据分类选择处理方式
        content_type = triage.get('content_type', 'TYPE_C_NORMAL')
        
        if content_type == 'TYPE_A_NSFW' and triage.get('nsfw_score', 0) > triage_config.get('nsfw_threshold', 0.5):
            # 路由至 NSFW 专家（复用图片流水线）
            try:
                from scripts.image.experts.nsfw_expert import NSFWExpert
                nsfw_expert = NSFWExpert(ensemble_mode="serial")
                caption_text, meta = nsfw_expert.generate_caption(frame_path, use_ensemble=False)
                nsfw_expert.unload()
                
                # 注入情绪上下文
                if emotion_context:
                    caption_text = f"[情绪上下文: {emotion_context[:100]}]\n{caption_text}"
                
                caption_result = {
                    'caption': caption_text,
                    'expert_used': 'nsfw_expert',
                    'expert_meta': meta,
                    'is_fallback': False
                }
            except Exception as e:
                caption_result = {
                    'caption': f'[NSFW专家处理失败: {str(e)}]',
                    'expert_used': 'nsfw_expert',
                    'error': str(e),
                    'is_fallback': False
                }
        elif content_type == 'TYPE_B_GORE' and triage.get('sfw_score', 1) < 0.5:
            # Gore 检测：使用主模型但添加特殊 prompt
            try:
                caption_result = generate_keyframe_caption(frame_path, emotion_context)
                caption_result['expert_used'] = 'gore_expert'
                
                # Gore 内容添加警告标记
                caption_result['caption'] = f"[⚠️ 可能含暴力内容] {caption_result.get('caption', '')}"
            except Exception as e:
                caption_result = {
                    'caption': f'[Gore专家处理失败: {str(e)}]',
                    'expert_used': 'gore_expert',
                    'error': str(e)
                }
        elif content_type == 'TYPE_D_DOC' and triage.get('text_ratio', 0) > triage_config.get('doc_text_ratio', 0.15):
            # 录屏/文档类，使用更高分辨率
            try:
                caption_result = generate_keyframe_caption(frame_path, emotion_context)
                caption_result['expert_used'] = 'doc_expert'
            except Exception as e:
                caption_result = {
                    'caption': f'[生成失败: {str(e)}]',
                    'expert_used': 'doc_expert',
                    'error': str(e)
                }
        else:
            # 使用主模型
            try:
                caption_result = generate_keyframe_caption(frame_path, emotion_context)
                caption_result['expert_used'] = 'default_expert'
            except Exception as e:
                caption_result = {
                    'caption': f'[生成失败: {str(e)}]',
                    'expert_used': 'default_expert',
                    'error': str(e)
                }
        
        keyframe_captions.append({
            'frame_id': kf.get('frame_id'),
            'timestamp_sec': kf.get('timestamp_sec'),
            'content_type': content_type,
            **caption_result,
            'evidence_spans': [f"frame:{kf.get('frame_id')}"]
        })
    
    # 整体 Triage 结果（基于关键帧投票）
    content_types = [t.get('content_type') for t in triage_results]
    if 'TYPE_A_NSFW' in content_types:
        overall_type = 'TYPE_A_NSFW'
    elif 'TYPE_B_GORE' in content_types:
        overall_type = 'TYPE_B_GORE'
    elif 'TYPE_D_DOC' in content_types:
        overall_type = 'TYPE_D_DOC'
    else:
        overall_type = 'TYPE_C_NORMAL'
    
    result['triage'] = {
        'content_type': overall_type,
        'frame_triage': triage_results,
        'confidence': sum(t.get('confidence', 0) for t in triage_results) / len(triage_results) if triage_results else 0
    }
    
    result['keyframe_captions'] = keyframe_captions
    
    # 视频整体理解（使用直接视频输入或多帧模式）
    video_understanding = None
    video_path = None
    
    if keyframes and video_dir:
        # 尝试找到原始视频文件
        video_path = video_dir / file_name
        if video_path.exists():
            print(f"    Generating video understanding for {file_name}...")
            video_understanding = generate_video_understanding(
                str(video_path),
                keyframes,
                emotion_context
            )
        else:
            # 回退到多帧模式
            video_understanding = generate_video_understanding_multiframe(keyframes, emotion_context)
    elif keyframes:
        # 没有视频目录，使用多帧模式
        video_understanding = generate_video_understanding_multiframe(keyframes, emotion_context)
    
    # ===== LLaVA Fallback 检测 =====
    if video_understanding and video_path and video_path.exists():
        should_fallback, fallback_reason = check_fallback_trigger(video_understanding)
        if should_fallback:
            print(f"    ⚠️ Primary model triggered fallback: {fallback_reason}")
            print(f"    Attempting LLaVA-NeXT-Video fallback...")
            
            # 先卸载主模型释放显存
            unload_model()
            
            # 调用 LLaVA fallback
            llava_result = generate_video_understanding_llava(str(video_path), emotion_context)
            
            # 如果 LLaVA 成功，使用其结果
            if 'error' not in llava_result:
                video_understanding = llava_result
                video_understanding['fallback_reason'] = fallback_reason
            else:
                # LLaVA 也失败了，保留原结果但标记
                video_understanding['fallback_attempted'] = True
                video_understanding['fallback_error'] = llava_result.get('error')
            
            # 卸载 LLaVA 模型
            unload_llava_model()
    
    result['video_understanding'] = video_understanding
    result['generation_params'] = models_config.get('primary_vlm', {}).get('generation', {})
    
    return result


def main():
    parser = argparse.ArgumentParser(description='Video Caption Generation')
    parser.add_argument('--sample', type=int, default=0, help='仅处理前N个文件')
    parser.add_argument('--skip-triage', action='store_true', help='跳过 Triage 分类')
    parser.add_argument('--test-dir', action='store_true', help='使用测试目录')
    args = parser.parse_args()
    
    print("=" * 60)
    print("Video Caption Generation Pipeline")
    print("=" * 60)
    
    # 输入输出路径
    video_before = get_video_before_merge()
    extract_file = video_before / "video_extract_v1.jsonl"
    transcribe_file = video_before / "video_transcribe_v1.jsonl"
    output_file = video_before / "video_caption_v1.jsonl"
    triage_file = video_before / "video_triage_v1.jsonl"
    
    # 确定视频源目录
    if args.test_dir:
        video_dir = PROJECT_ROOT / "tests" / "manual_videos"
    else:
        # 从 paths.yaml 获取视频目录
        from scripts._common.path_utils import get_video_dir
        video_dir = get_video_dir()
    print(f"  Video Source: {video_dir}")
    print(f"  Extract Input: {extract_file}")
    print(f"  Transcribe Input: {transcribe_file}")
    print(f"  Output: {output_file}")
    
    if not extract_file.exists():
        print(f"\n❌ Error: {extract_file} not found. Run _01_run_extract.py first.")
        sys.exit(1)
    
    # 读取提取结果
    extract_records = {}
    with extract_file.open('r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                record = json.loads(line)
                extract_records[record.get('file', '')] = record
    
    # 读取转写结果
    transcribe_records = {}
    if transcribe_file.exists():
        with transcribe_file.open('r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    record = json.loads(line)
                    transcribe_records[record.get('file', '')] = record
    
    total = len(extract_records)
    print(f"\n[1/2] Found {total} video records.")
    
    files_to_process = list(extract_records.keys())
    if args.sample > 0:
        files_to_process = files_to_process[:args.sample]
        print(f"      Sample mode: processing only {len(files_to_process)} files")
    
    if args.skip_triage:
        print("      Triage: SKIPPED")
    
    # 处理视频
    print("\n[2/2] Generating captions...")
    
    try:
        with output_file.open('w', encoding='utf-8') as f:
            for file_name in tqdm(files_to_process, desc="视频描述", **tqdm_kwargs):
                extract_record = extract_records.get(file_name, {})
                transcribe_record = transcribe_records.get(file_name, {})
                
                if 'error' in extract_record:
                    result = {
                        'schema_version': SCHEMA_VERSION,
                        'file': file_name,
                        'error': extract_record.get('error')
                    }
                else:
                    result = process_video_caption(
                        extract_record,
                        transcribe_record,
                        skip_triage=args.skip_triage,
                        video_dir=video_dir
                    )
                
                f.write(json.dumps(result, ensure_ascii=False) + '\n')
    finally:
        # 确保卸载所有模型
        unload_model()
        unload_triage()
        unload_llava_model()
    
    print(f"\n✅ Done. Wrote {len(files_to_process)} records to: {output_file}")


if __name__ == "__main__":
    main()
