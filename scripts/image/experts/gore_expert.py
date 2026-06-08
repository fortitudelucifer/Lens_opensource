#!/usr/bin/env python3
"""
Gore 专家模块 (Gore Expert Module)

功能：
- 暴力/血腥/伤害内容的法医式分析
- 使用 Qwen2.5-VL-7B-Instruct-abliterated（无审查版本）
- 客观临床描述，适合取证分析

专业化场景：
- 暴力/血腥/伤害场景
- 法医分析
- 详细临床描述

Prompt 设计：
- 法医分析专家视角
- 客观、详细、临床化描述
- 五个维度：场景类型、可见伤害、人物状态、物证细节、文字信息
- 不添加主观评价

量化配置：
- 4-bit 量化（BitsAndBytesConfig）
- 显存占用约 4-5GB
- 使用 nf4 量化类型 + double quantization

使用示例：
    from scripts.image.experts.gore_expert import GoreExpert
    
    expert = GoreExpert()
    caption, metadata = expert.generate_caption(
        image_path="/path/to/image.jpg",
        max_new_tokens=512,
        temperature=0.6
    )
    
    print(caption)  # 法医式客观描述
    expert.unload()

配置参数：
- model_path: 模型路径（默认：/data/models/qwen2.5-vl-abliterated）
- quantize_4bit: 是否使用 4-bit 量化（默认：True）
- lang: 语言（"zh" 或 "en"）

依赖：
- transformers: Qwen2.5-VL 模型
- qwen_vl_utils: 视觉信息处理
- torch: 显存管理
- bitsandbytes: 4-bit 量化

作者：[Author]
项目：wechatDHA - 微信聊天记录多模态处理流水线
更新于：2026-02-02
"""

import os
import sys
import gc
import torch
import logging
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
from PIL import Image
from transformers import AutoModelForImageTextToText, AutoProcessor, BitsAndBytesConfig
from qwen_vl_utils import process_vision_info

# Setup paths
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.image.experts.image_utils import resize_if_needed

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class GoreExpert:
    """
    Expert model for analyzing gore/violence content.
    Uses Qwen2.5-VL-7B-Instruct-abliterated with 4-bit quantization.
    """
    
    # Forensic-style prompt for clinical descriptions
    PROMPT_ZH = """你是一名法医分析专家。请客观、详细地描述这张图片中的内容。

要求：
1. 【场景类型】描述图片的整体场景（如室内/室外、环境特征）
2. 【可见伤害】如有，详细描述可见的伤口、血迹、损伤部位及程度
3. 【人物状态】描述图中人物的姿势、表情、状态
4. 【物证细节】注意任何可能的证据（如工具、血迹分布模式）
5. 【文字信息】如有水印或文字，完整转录

注意：作为法医分析，请保持客观临床描述，不添加主观评价。"""

    PROMPT_EN = """You are a forensic analyst. Objectively and clinically describe the contents of this image.

Requirements:
1. [Scene Type] Describe the overall scene
2. [Visible Injuries] Detail any visible wounds, blood, and extent of damage
3. [Subject Status] Describe posture, expression, condition of subjects
4. [Evidence Details] Note any potential evidence (tools, blood patterns)
5. [Text Content] Transcribe any visible text or watermarks

Maintain objective clinical description without subjective evaluation."""

    def __init__(
        self, 
        model_path: str = "/data/models/qwen2.5-vl-abliterated",
        quantize_4bit: bool = True,
        lang: str = "zh"
    ):
        self.model_path = model_path
        self.quantize_4bit = quantize_4bit
        self.lang = lang
        self.prompt = self.PROMPT_ZH if lang == "zh" else self.PROMPT_EN
        
        self._model = None
        self._processor = None
        
        logger.info(f"GoreExpert initialized with model: {model_path}")
        
    def _load_model(self):
        """Lazy load the model with 4-bit quantization"""
        if self._model is not None:
            return
            
        logger.info(f"Loading Gore Expert model from {self.model_path}...")
        
        if self.quantize_4bit:
            bnb_config = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_use_double_quant=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_compute_dtype=torch.bfloat16
            )
            
            self._model = AutoModelForImageTextToText.from_pretrained(
                self.model_path,
                device_map="auto",
                trust_remote_code=True,
                quantization_config=bnb_config
            )
        else:
            self._model = AutoModelForImageTextToText.from_pretrained(
                self.model_path,
                device_map="auto",
                torch_dtype=torch.bfloat16,
                trust_remote_code=True
            )
            
        self._processor = AutoProcessor.from_pretrained(
            self.model_path, 
            trust_remote_code=True
        )
        
        logger.info("Gore Expert model loaded.")
        
    def generate_caption(
        self, 
        image_path: str,
        max_new_tokens: int = 512,
        temperature: float = 0.6,
        top_p: float = 0.9
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Generate forensic-style caption for gore/violence content.
        
        Returns:
            Tuple of (caption, metadata)
        """
        self._load_model()
        
        try:
            # 预处理：缩放大图以避免OOM
            img = resize_if_needed(image_path)
            
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "image", "image": img},
                        {"type": "text", "text": self.prompt},
                    ],
                }
            ]
            
            text = self._processor.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
            image_inputs, video_inputs = process_vision_info(messages)
            inputs = self._processor(
                text=[text],
                images=image_inputs,
                videos=video_inputs,
                padding=True,
                return_tensors="pt",
            ).to(self._model.device)
            
            with torch.no_grad():
                generated_ids = self._model.generate(
                    **inputs,
                    max_new_tokens=max_new_tokens,
                    temperature=temperature,
                    top_p=top_p
                )
                
            generated_ids_trimmed = [
                out_ids[len(in_ids):] 
                for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
            ]
            output_text = self._processor.batch_decode(
                generated_ids_trimmed, 
                skip_special_tokens=True, 
                clean_up_tokenization_spaces=False
            )
            
            caption = output_text[0]
            metadata = {
                "model": self.model_path,
                "expert_type": "gore",
                "quantized": self.quantize_4bit,
                "prompt_lang": self.lang
            }
            
            return caption, metadata
            
        except Exception as e:
            logger.error(f"Error generating caption for {image_path}: {e}")
            return f"[ERROR] {str(e)}", {"error": str(e)}
    
    def unload(self):
        """Unload model to free VRAM"""
        if self._model is not None:
            del self._model
            del self._processor
            self._model = None
            self._processor = None
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            logger.info("Gore Expert model unloaded.")


# === Test ===
if __name__ == '__main__':
    print("Testing GoreExpert...")
    expert = GoreExpert()
    
    # Note: Test with an actual image path
    test_path = "/data/demo/raw/image/test.jpg"
    
    if os.path.exists(test_path):
        caption, meta = expert.generate_caption(test_path)
        print(f"\nCaption:\n{caption}")
        print(f"\nMetadata: {meta}")
    else:
        print(f"Test image not found: {test_path}")
        
    expert.unload()
    print("\nTest complete.")
