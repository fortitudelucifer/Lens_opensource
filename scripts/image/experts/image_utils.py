#!/usr/bin/env python3
"""
Image utility functions for expert models.
Provides common image preprocessing to avoid OOM on high-resolution images.

显存估算 (Qwen2.5-VL 4-bit, 16GB GPU):
- 模型权重: ~4.5GB
- KV Cache: ~1-2GB  
- 图像编码+激活: 与分辨率成正比

分辨率参考:
- 1280×720 (0.92M): ~2GB 额外显存 ✅ 安全
- 1600×1200 (1.92M): ~4GB 额外显存 ⚠️ 边缘（需要 FlashAttention）
- 1920×1080 (2.07M): ~4.5GB 额外显存 ⚠️ 边缘
- 2560×1440 (3.69M): ~7GB 额外显存 ❌ 危险
- 4096×3072 (12.6M): ~15GB+ 额外显存 ❌ OOM

使用 vLLM + FlashAttention-2 可提升约 40% 显存效率。
"""

import logging
from PIL import Image
from typing import Union

logger = logging.getLogger(__name__)

# 默认最大像素数: 1600×1200 = 1,920,000
# 如果遇到 OOM，可降低到 1280×720 = 921,600
DEFAULT_MAX_PIXELS = 1600 * 1200


def resize_if_needed(image_input: Union[str, Image.Image], max_pixels: int = DEFAULT_MAX_PIXELS) -> Image.Image:
    """
    如果图片像素总数超过阈值，则缩放图片以避免OOM。
    Qwen2.5-VL 等模型对高分辨率图片（如4096x3072）需要大量显存。
    
    Args:
        image_input: 图片路径或PIL Image对象
        max_pixels: 最大像素数，默认 1280*720 = 921600
        
    Returns:
        PIL.Image 对象（可能已缩放）
    """
    if isinstance(image_input, str):
        img = Image.open(image_input).convert('RGB')
    else:
        img = image_input.convert('RGB') if image_input.mode != 'RGB' else image_input
    
    w, h = img.size
    total_pixels = w * h
    
    if total_pixels > max_pixels:
        # 计算缩放比例
        scale = (max_pixels / total_pixels) ** 0.5
        new_w = int(w * scale)
        new_h = int(h * scale)
        img = img.resize((new_w, new_h), Image.LANCZOS)
        logger.debug(f"Resized image: {w}x{h} -> {new_w}x{new_h}")
        
    return img
