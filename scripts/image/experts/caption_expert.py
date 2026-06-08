#!/usr/bin/env python3
"""
默认描述专家模块 (Caption Expert Module)

功能：
- 使用 Qwen2.5-VL-7B 生成视觉内容描述
- 支持 Fallback 机制（主模型拒绝时切换到 Abliterated 版本）
- 4-bit 量化节省显存（~8GB）

Fallback 机制：
1. 主模型（Qwen2.5-VL-7B）先尝试生成
2. 检测拒绝关键词（"我无法"、"不适合"、"违反"等）
3. 触发 Fallback：切换到 LLaVA-NeXT（无审查版本）
4. 自动卸载主模型释放显存，加载 Fallback 模型

显存管理：
- 主模型和 Fallback 模型互斥加载
- 切换时自动卸载当前模型并清理显存
- 使用 4-bit 量化（BitsAndBytesConfig）

图片预处理：
- 自动缩放大图避免 OOM（使用 resize_if_needed）
- 保持宽高比
- 最大边长限制：4096px

使用示例：
    from scripts.image.experts.caption_expert import CaptionExpert
    
    expert = CaptionExpert()
    caption, is_fallback = expert.generate_caption("/path/to/image.jpg")
    
    if is_fallback:
        print("使用了 Fallback 模型")
    
    expert.unload()

配置文件：
- configs/caption.yaml: 模型路径、生成参数、Fallback 配置

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
import json
import torch
import logging
from pathlib import Path
from tqdm import tqdm
from PIL import Image
from transformers import AutoModelForImageTextToText, AutoProcessor, BitsAndBytesConfig
from qwen_vl_utils import process_vision_info

# Setup paths
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts._common.path_utils import PATHS
from scripts.image.loader import get_image_path
from scripts.image.experts.image_utils import resize_if_needed

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class CaptionExpert:
    def __init__(self, config_path=None, lazy_load=False):
        """
        初始化 CaptionExpert
        
        Args:
            config_path: 配置文件路径
            lazy_load: 是否延迟加载模型（用于显存管理场景）
        """
        if not config_path:
            config_path = PROJECT_ROOT / 'configs/caption.yaml'
            
        with open(config_path) as f:
            import yaml
            self.cfg = yaml.safe_load(f)
            
        self.device = self.cfg['model'].get('device', 'cuda')
        self.model_path = self.cfg['model']['path']
        
        # Generation args
        self.gen_cfg = self.cfg['generation']
        self.prompt_text = self.cfg['prompt']['zh']
        
        # Fallback config
        self.fallback_cfg = self.cfg.get('fallback', {})
        
        # Model state tracking
        self.model = None
        self.processor = None
        self.fallback_model = None
        self.fallback_processor = None
        self._current_model = None  # 'primary' or 'fallback'
        
        # 4-bit Quantization Config
        self.bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_use_double_quant=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16
        )
        
        if not lazy_load:
            self._load_primary_model()
    
    def _clear_vram(self):
        """清理显存"""
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
    
    def _load_primary_model(self):
        """加载主模型"""
        if self.model is not None:
            return
        
        # 先卸载 fallback 模型
        self._unload_fallback_model()
        
        logger.info(f"Loading model from {self.model_path} with 4-bit quantization...")
        
        self.model = AutoModelForImageTextToText.from_pretrained(
            self.model_path,
            device_map="auto",
            trust_remote_code=True,
            quantization_config=self.bnb_config
        )
        
        self.processor = AutoProcessor.from_pretrained(self.model_path, trust_remote_code=True)
        self._current_model = 'primary'
    
    def _unload_primary_model(self):
        """卸载主模型释放显存"""
        if self.model is not None:
            logger.info("Unloading primary model to free VRAM...")
            del self.model
            del self.processor
            self.model = None
            self.processor = None
            self._clear_vram()
        
    def _load_fallback_model(self):
        """加载 fallback 模型（先卸载主模型）"""
        if self.fallback_model is not None:
            return
        
        # 关键：先卸载主模型释放显存
        self._unload_primary_model()
            
        model_path = self.fallback_cfg['model_path']
        logger.info(f"Loading fallback model from {model_path}...")
        
        # 使用 4-bit 量化以节省显存
        self.fallback_model = AutoModelForImageTextToText.from_pretrained(
            model_path,
            device_map="auto",
            trust_remote_code=True,
            quantization_config=self.bnb_config
        )
        self.fallback_processor = AutoProcessor.from_pretrained(model_path, trust_remote_code=True)
        self._current_model = 'fallback'
    
    def _unload_fallback_model(self):
        """卸载 fallback 模型释放显存"""
        if self.fallback_model is not None:
            logger.info("Unloading fallback model to free VRAM...")
            del self.fallback_model
            del self.fallback_processor
            self.fallback_model = None
            self.fallback_processor = None
            self._clear_vram()
    
    def unload(self):
        """卸载所有模型"""
        self._unload_primary_model()
        self._unload_fallback_model()
        self._current_model = None
        logger.info("CaptionExpert: all models unloaded.")

    def generate_caption(self, image_path):
        """Generate caption for a single image, with automatic fallback"""
        try:
            # 确保主模型已加载
            if self.model is None:
                self._load_primary_model()
            
            # 1. Try Primary Model
            caption = self._do_inference(
                self.model, 
                self.processor, 
                image_path, 
                self.prompt_text, 
                self.gen_cfg
            )
            
            # 2. Check for Refusal
            is_refusal = False
            if self.fallback_cfg.get('enabled'):
                triggers = self.fallback_cfg.get('trigger_keywords', [])
                if any(trigger in caption for trigger in triggers):
                    is_refusal = True
                    logger.warning(f"Refusal detected in primary model output for {os.path.basename(image_path)}. Triggering fallback...")
            
            # 3. Handle Fallback
            if is_refusal:
                self._load_fallback_model()  # 会自动卸载主模型
                fallback_prompt = self.fallback_cfg['prompt']['zh']
                fallback_gen_cfg = self.fallback_cfg['generation']
                
                caption = self._do_inference(
                    self.fallback_model,
                    self.fallback_processor,
                    image_path,
                    fallback_prompt,
                    fallback_gen_cfg
                )
                return caption, True # Returns caption and fallback_flag
                
            return caption, False
            
        except Exception as e:
            logger.error(f"Error processing {image_path}: {e}")
            return f"[ERROR] {str(e)}", False
    
    def switch_to_primary(self):
        """切换回主模型（用于批量处理后恢复）"""
        if self._current_model != 'primary':
            self._load_primary_model()

    def _do_inference(self, model, processor, image_path, prompt_text, gen_cfg):
        """Helper for model inference"""
        # 预处理：缩放大图以避免OOM
        img = resize_if_needed(image_path)
        
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": img},  # 使用PIL Image对象而非路径
                    {"type": "text", "text": prompt_text},
                ],
            }
        ]
        
        text = processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        image_inputs, video_inputs = process_vision_info(messages)
        inputs = processor(
            text=[text],
            images=image_inputs,
            videos=video_inputs,
            padding=True,
            return_tensors="pt",
        ).to(model.device)
        
        with torch.no_grad():
            generated_ids = model.generate(
                **inputs,
                max_new_tokens=gen_cfg.get('max_new_tokens', 512),
                temperature=gen_cfg.get('temperature', 0.7),
                top_p=gen_cfg.get('top_p', 0.9)
            )
            
        generated_ids_trimmed = [
            out_ids[len(in_ids) :] for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
        ]
        output_text = processor.batch_decode(
            generated_ids_trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False
        )
        
        return output_text[0]

def process_all_captions():
    # Paths
    artifacts_dir = PATHS.get('artifacts', {}).get('image_after', f'{PROJECT_ROOT}/artifacts/after_merge/image')
    qc_file = os.path.join(artifacts_dir, 'image_qc.jsonl')
    output_file = os.path.join(artifacts_dir, 'caption_results.jsonl')
    raw_dir = PATHS.get('dirs', {}).get('raw', '/data/demo/raw')
    
    # Load targets
    targets = []
    target_classes = [
        'VISUAL_ONLY', 
        'VISUAL_PRIMARY', 
        'HYBRID_VISUAL_MAIN', 
        'HYBRID_TEXT_MAIN'
    ]
    
    if not os.path.exists(qc_file):
        logger.error(f"QC file not found: {qc_file}")
        return
        
    logger.info("Scanning for images to caption...")
    with open(qc_file, 'r') as f:
        for line in f:
            item = json.loads(line)
            if item.get('route_class') in target_classes:
                targets.append(item)
                
    logger.info(f"Found {len(targets)} images to process.")
    
    # Initialize Expert
    expert = CaptionExpert()
    
    # Process
    results = []
    # Load existing if any to resume? (Skip for now, straightforward overwrite)
    if os.path.exists(output_file):
        os.remove(output_file)
        
    for i, item in enumerate(tqdm(targets, desc="Generating Captions")):
        msg_uid = item['msg_uid']
        media_path = item['media_path']
        abs_path = get_image_path(media_path, raw_dir)
        
        caption, is_fallback = expert.generate_caption(abs_path)
        
        result_entry = {
            'msg_uid': msg_uid,
            'route_class': item['route_class'],
            'caption': caption,
            'model': expert.fallback_cfg['model_path'] if is_fallback else expert.model_path,
            'is_fallback': is_fallback
        }
        
        # Write incrementally
        with open(output_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(result_entry, ensure_ascii=False) + '\n')
            
    logger.info(f"Done! Results written to {output_file}")

if __name__ == '__main__':
    process_all_captions()
