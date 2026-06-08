#!/usr/bin/env python3
"""
表情包语义描述模块 - OCR 文字提取 + VLM 描述生成

功能：
- OCR 文字提取（PaddleOCR）
- VLM 描述生成（Qwen2.5-VL-7B，4-bit 量化）
- 动图使用 Contact Sheet（多帧拼接图）
- 静图使用缩略图
- 支持专家模型路由（可选，默认禁用以节省显存）
- 定期显存清理（每 20 个表情包）

处理流程：
1. 加载 Meta、Triage、Frames 结果
2. 初始化 StickerCaptionExpert
3. 逐个处理：
   - 选择用于描述的图片（动图用 Contact Sheet，静图用缩略图）
   - OCR 提取文字
   - VLM 生成描述
   - 定期清理显存
4. 卸载模型
5. 保存 Caption 结果

输入：
- artifacts/before_merge/sticker/sticker_meta_v1.jsonl
  * msg_uid, sticker_class, thumb_path, is_animated
- artifacts/before_merge/sticker/sticker_triage_v1.jsonl
  * msg_uid, content_type
- artifacts/before_merge/sticker/sticker_frames_v1.jsonl
  * msg_uid, contact_sheet_path

输出：
- artifacts/before_merge/sticker/sticker_caption_v1.jsonl
  * msg_uid, ocr_text, caption, expert_used

依赖：
- scripts/_common/path_utils.py (load_sticker_config, get_sticker_before_merge)
- scripts/_common/jsonl_utils.py (load_jsonl_by_key, load_jsonl_list, write_jsonl)
- transformers (AutoModelForImageTextToText, AutoProcessor, BitsAndBytesConfig)
- paddleocr (PaddleOCR)
- qwen_vl_utils (process_vision_info)

使用示例：
    # 完整处理
    python scripts/sticker/run_all/_05_run_caption.py
    
    # 测试模式（只处理前10个）
    python scripts/sticker/run_all/_05_run_caption.py --sample 10
    
    # 跳过 OCR
    python scripts/sticker/run_all/_05_run_caption.py --skip-ocr

VLM Prompt 策略：
- 动图：说明这是 Contact Sheet，要求描述动画的关键帧
- 静图：要求描述静态表情包
- 包含 OCR 文字（如果有）
- 输出格式：[表情包: 描述内容]

显存管理：
- 使用 4-bit 量化（BitsAndBytesConfig）
- 每 20 个表情包清理一次显存
- 专家模型路由默认禁用（避免显存不足）

作者：[Author]
更新于：2026-02-02
"""

import os
import sys
import gc
import argparse
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import torch
from tqdm import tqdm
from PIL import Image

# 确保 tqdm 输出到 stderr 以便实时显示
tqdm_kwargs = {"file": sys.stderr, "dynamic_ncols": True}

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from scripts._common.path_utils import (
    load_sticker_config, get_sticker_before_merge
)
from scripts._common.jsonl_utils import load_jsonl_by_key, load_jsonl_list, write_jsonl

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class StickerCaptionExpert:
    """表情包语义描述专家"""
    
    def __init__(self, config: dict):
        self.config = config
        self.caption_cfg = config.get('caption', {})
        self.gen_cfg = self.caption_cfg.get('generation', {})
        # 禁用专家路由，避免显存不足问题
        self.use_expert_router = False  # self.caption_cfg.get('use_expert_router', True)
        self.model_path = "/data/models/qwen2.5-vl-7b/Qwen/Qwen2___5-VL-7B-Instruct"
        
        self.model = None
        self.processor = None
        self.ocr_engine = None
        self.expert_router = None
        
    def _load_model(self):
        """加载 VLM 模型"""
        if self.model is not None:
            return
        
        logger.info(f"加载 VLM 模型: {self.model_path}")
        
        from transformers import AutoModelForImageTextToText, AutoProcessor, BitsAndBytesConfig
        
        # 4-bit 量化配置
        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_use_double_quant=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16
        )
        
        self.model = AutoModelForImageTextToText.from_pretrained(
            self.model_path,
            device_map="auto",
            trust_remote_code=True,
            quantization_config=bnb_config
        )
        self.processor = AutoProcessor.from_pretrained(
            self.model_path, 
            trust_remote_code=True
        )
        logger.info("VLM 模型加载完成")
        
    def _load_ocr(self):
        """加载 OCR 引擎"""
        if self.ocr_engine is not None:
            return
        
        logger.info("加载 PaddleOCR...")
        from paddleocr import PaddleOCR
        self.ocr_engine = PaddleOCR(
            use_angle_cls=True, 
            lang='ch',
            show_log=False
        )
        logger.info("PaddleOCR 加载完成")
    
    def _load_expert_router(self):
        """加载专家模型路由"""
        if self.expert_router is not None or not self.use_expert_router:
            return
        
        logger.info("加载 Expert Router...")
        # 导入图片流水线的 Expert Router
        from scripts.image.experts.expert_router import ExpertRouter
        from scripts._common.path_utils import load_caption_config
        
        caption_config = load_caption_config()
        self.expert_router = ExpertRouter(caption_config)
        logger.info("Expert Router 加载完成")
        
    def extract_ocr_text(self, image_path: str) -> str:
        """提取图片中的文字"""
        self._load_ocr()
        
        try:
            result = self.ocr_engine.ocr(image_path, cls=True)
            if not result or not result[0]:
                return ""
            
            texts = []
            for line in result[0]:
                if line and len(line) >= 2:
                    text = line[1][0] if isinstance(line[1], tuple) else line[1]
                    texts.append(text)
            
            return " ".join(texts)
        except Exception as e:
            logger.debug(f"OCR 失败 {image_path}: {e}")
            return ""
    
    def generate_caption(self, image_path: str, ocr_text: str = "", is_animated: bool = False) -> str:
        """生成表情包描述"""
        self._load_model()
        
        try:
            # 构建 prompt
            if is_animated:
                prompt = """这是一个动态表情包的多帧拼接图（Contact Sheet），从左到右、从上到下展示了动画的关键帧。
请用简短的中文描述这个表情包的内容，包括：
1. 角色/形象（如卡通人物、动物、表情符号等）
2. 动作/行为
3. 表达的情绪或含义
"""
            else:
                prompt = """这是一个静态表情包。
请用简短的中文描述这个表情包的内容，包括：
1. 角色/形象
2. 动作/表情
3. 表达的情绪或含义
"""
            
            if ocr_text:
                prompt += f"\n图片中的文字: {ocr_text}"
            
            prompt += "\n请用一句话简洁描述，格式: [表情包: 描述内容]"
            
            # 构建消息
            from qwen_vl_utils import process_vision_info
            
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "image", "image": image_path},
                        {"type": "text", "text": prompt},
                    ],
                }
            ]
            
            text = self.processor.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
            image_inputs, video_inputs = process_vision_info(messages)
            inputs = self.processor(
                text=[text],
                images=image_inputs,
                videos=video_inputs,
                padding=True,
                return_tensors="pt",
            ).to(self.model.device)
            
            with torch.no_grad():
                generated_ids = self.model.generate(
                    **inputs,
                    max_new_tokens=self.gen_cfg.get('max_new_tokens', 128),
                    temperature=self.gen_cfg.get('temperature', 0.4),
                    top_p=self.gen_cfg.get('top_p', 0.9)
                )
            
            generated_ids_trimmed = [
                out_ids[len(in_ids):] 
                for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
            ]
            output_text = self.processor.batch_decode(
                generated_ids_trimmed, 
                skip_special_tokens=True, 
                clean_up_tokenization_spaces=False
            )
            
            return output_text[0].strip()
            
        except Exception as e:
            logger.error(f"Caption 生成失败 {image_path}: {e}")
            return f"[表情包: 描述生成失败]"
    
    def generate_caption_with_expert(self, image_path: str, content_type: str, ocr_text: str = "", is_animated: bool = False) -> tuple:
        """
        使用专家模型路由生成描述
        
        Returns:
            (caption, expert_used)
        """
        if not self.use_expert_router or content_type == "TYPE_C_NORMAL":
            # 正常内容使用默认模型
            caption = self.generate_caption(image_path, ocr_text, is_animated)
            return caption, "sticker_caption_expert"
        
        # 敏感内容需要卸载当前模型，为专家模型腾出显存
        logger.info(f"路由到专家模型: {content_type}，卸载主模型...")
        if self.model is not None:
            del self.model
            self.model = None
        if self.processor is not None:
            del self.processor
            self.processor = None
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        
        # 加载并使用专家模型
        self._load_expert_router()
        
        try:
            logger.info(f"使用专家模型处理: {content_type}")
            # 使用 ExpertRouter 的 process_image 方法
            result = self.expert_router.process_image(
                msg_uid="sticker_temp",
                image_path=image_path,
                route_class="STICKER",
            )
            return result.caption, result.expert_used
        except Exception as e:
            logger.error(f"专家模型处理失败: {e}，回退到默认模型")
            # 重新加载主模型
            self._load_model()
            caption = self.generate_caption(image_path, ocr_text, is_animated)
            return caption, "sticker_caption_expert_fallback"
    
    def cleanup_models(self):
        """清理所有模型以释放显存"""
        if self.model is not None:
            del self.model
            self.model = None
        if self.processor is not None:
            del self.processor
            self.processor = None
        if self.ocr_engine is not None:
            del self.ocr_engine
            self.ocr_engine = None
        if self.expert_router is not None:
            self.expert_router.cleanup()
            self.expert_router = None
        
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
        logger.info("StickerCaptionExpert models cleaned up")
    
    def unload(self):
        """卸载模型释放显存"""
        if self.model is not None:
            del self.model
            self.model = None
        if self.processor is not None:
            del self.processor
            self.processor = None
        if self.ocr_engine is not None:
            del self.ocr_engine
            self.ocr_engine = None
        if self.expert_router is not None:
            self.expert_router.cleanup()
            self.expert_router = None
        
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        logger.info("Caption Expert 已卸载")


def main():
    parser = argparse.ArgumentParser(description='表情包语义描述')
    parser.add_argument('--sample', type=int, help='仅处理前 N 个')
    parser.add_argument('--skip-ocr', action='store_true', help='跳过 OCR')
    args = parser.parse_args()
    
    # 加载配置
    config = load_sticker_config()
    
    # 设置路径
    output_dir = get_sticker_before_merge()
    
    # 加载数据
    meta_path = output_dir / "sticker_meta_v1.jsonl"
    triage_path = output_dir / "sticker_triage_v1.jsonl"
    frames_path = output_dir / "sticker_frames_v1.jsonl"
    
    logger.info(f"加载 Meta 结果: {meta_path}")
    meta_list = load_jsonl_list(str(meta_path))
    
    logger.info(f"加载 Triage 结果: {triage_path}")
    triage_data = load_jsonl_by_key(str(triage_path), 'msg_uid')
    
    logger.info(f"加载 Frames 结果: {frames_path}")
    frames_data = load_jsonl_by_key(str(frames_path), 'msg_uid')
    
    logger.info(f"共 {len(meta_list)} 条记录")
    
    if args.sample:
        meta_list = meta_list[:args.sample]
        logger.info(f"采样模式: 仅处理前 {args.sample} 个")
    
    # 初始化 Caption Expert
    expert = StickerCaptionExpert(config)
    
    # 处理
    caption_results = []
    
    # 显存管理：每处理 N 个表情包后主动清理
    CLEANUP_INTERVAL = 20  # 每 20 个表情包清理一次
    
    for idx, meta in enumerate(tqdm(meta_list, desc="表情描述", **tqdm_kwargs), 1):
        msg_uid = meta.get('msg_uid')
        file_sha256 = meta.get('file_sha256')
        sticker_class = meta.get('sticker_class')
        thumb_path = meta.get('thumb_path')
        is_animated = meta.get('is_animated', False)
        
        # 获取 triage 结果
        triage = triage_data.get(msg_uid, {})
        content_type = triage.get('content_type', 'TYPE_C_NORMAL')
        
        # 获取 frames 结果
        frames = frames_data.get(msg_uid, {})
        contact_sheet_path = frames.get('contact_sheet_path')
        
        result = {
            "schema_version": "sticker_caption_v1",
            "msg_uid": msg_uid,
            "seq_in_html": meta.get('seq_in_html', -1),
            "MsgSvrID": meta.get('MsgSvrID', ''),
            "token": meta.get('token', ''),
            "ts": meta.get('ts', 0),
            "time_local": meta.get('time_local', ''),
            "speaker": meta.get('speaker', 'UNKNOWN'),
            "type": meta.get('type', 47),
            "sub_type": meta.get('sub_type', 0),
            "modality": 'sticker',
            "file_sha256": file_sha256,
            "sticker_class": sticker_class,
            "content_type": content_type,
            "final_path": meta.get('final_path'),
            "thumb_path": thumb_path,
            "width": meta.get('width'),
            "height": meta.get('height'),
            "is_animated": is_animated,
            "n_frames": meta.get('n_frames'),
            "detected_format": meta.get('detected_format'),
            "ocr_text": "",
            "caption": "",
            "expert_used": "sticker_caption_expert"
        }
        
        # 选择用于描述的图片
        # 动图优先使用 Contact Sheet，静图使用缩略图
        if is_animated and contact_sheet_path and Path(contact_sheet_path).exists():
            caption_image = contact_sheet_path
        elif thumb_path and Path(thumb_path).exists():
            caption_image = thumb_path
        else:
            result["caption"] = "[表情包: 图片不可用]"
            caption_results.append(result)
            continue
        
        # OCR 提取文字
        if not args.skip_ocr:
            ocr_text = expert.extract_ocr_text(caption_image)
            result["ocr_text"] = ocr_text
        
        # 生成描述 - 使用专家模型路由
        caption, expert_used = expert.generate_caption_with_expert(
            caption_image,
            content_type,
            result.get("ocr_text", ""),
            is_animated
        )
        result["caption"] = caption
        result["expert_used"] = expert_used
        
        caption_results.append(result)
        
        # 定期清理显存
        if idx % CLEANUP_INTERVAL == 0:
            logger.info(f"Processed {idx}/{len(meta_list)}, performing VRAM cleanup...")
            expert.cleanup_models()
            import gc
            import torch
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
    
    # 卸载模型
    expert.unload()
    
    # 保存结果
    caption_path = output_dir / "sticker_caption_v1.jsonl"
    write_jsonl(str(caption_path), caption_results)
    logger.info(f"Caption 结果已保存到: {caption_path}")


if __name__ == '__main__':
    main()
