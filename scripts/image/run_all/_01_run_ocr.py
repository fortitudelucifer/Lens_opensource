#!/usr/bin/env python3
"""
图片 OCR 处理步骤

功能：
- 使用 PaddleOCR PP-OCRv4 提取图片中的文字
- 智能路由：根据图片类型决定 OCR 策略
- 媒体质量过滤：跳过低质量图片，优化处理流程
- 检测结果复用：复用 Router 的检测框，避免重复检测

处理流程：
1. 加载图片消息列表（从 P1_messages_raw.jsonl）
2. 初始化 ImageRouter 和 OCRExpert
3. 对每张图片：
   a. 加载图片并进行质量检查（QC）
   b. 媒体质量过滤（SKIP/LITE/SLICE/FULL）
   c. 路由分类（TEXT_HEAVY/GRAY/PHOTO/etc.）
   d. 根据分类决定是否执行 OCR
   e. 优化：复用 Router 的检测框，只做识别（recognize_only）
4. 输出 OCR 结果和 QC 报告

路由策略：
- TEXT_HEAVY: 文本密集型图片，执行完整 OCR
- GRAY: 灰度图片，执行 OCR + 后续 VLM Caption
- PHOTO: 纯视觉图片，跳过 OCR
- SKIPPED: 低质量图片，完全跳过

媒体过滤层级：
- SKIP: 极低质量（< 50px 或 < 1KB），完全跳过
- LITE: 低质量（< 200px 或 < 10KB），只做 OCR，不做 VLM
- SLICE: 超大图片（> 4096px 或 > 10MB），建议切片处理
- FULL: 正常质量，完整处理

输入：
- raw/P1_messages_raw.jsonl: 原始消息记录
- raw/image/: 图片文件目录
- configs/router.yaml: 路由配置

输出：
- artifacts/before_merge/image/image_ocr_v1.jsonl: OCR 结果（仅包含有文字的图片）
- artifacts/before_merge/image/image_qc_v1.jsonl: 质量检查报告（所有图片）

依赖：
- PaddleOCR v4: OCR 引擎
- scripts/image/router.py: 图片路由器
- scripts/image/loader.py: 图片加载器
- scripts/_common/media_filter.py: 媒体质量过滤器

使用示例：
    # 完整运行
    python scripts/image/run_all/_01_run_ocr.py
    
    # 使用 CPU（在配置文件中设置 use_gpu: false）
    # 编辑 configs/router.yaml，设置 models.paddleocr.use_gpu: false

性能参考（RTX 5070 Ti 16GB）：
- 处理速度：~2-3 张/秒（GPU）
- 显存占用：~2GB
- 优化：检测框复用可节省 30-40% 时间

作者：forcifer
更新于：2026-02-02
"""

import os
import sys
import json
from pathlib import Path
from typing import Dict, Any, List, Optional
import numpy as np
from PIL import Image
from tqdm import tqdm

# 确保 tqdm 输出到 stderr 以便实时显示
tqdm_kwargs = {"file": sys.stderr, "dynamic_ncols": True}

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts._common.path_utils import PATHS
from scripts._common.media_filter import (
    filter_image, FilterTier, SkipReason, create_skip_marker
)
from scripts.image.loader import load_image_safe, get_image_path
from scripts.image.router import ImageRouter, load_router_config

from paddleocr import PaddleOCR


class OCRExpert:
    """
    OCR 专家模块，使用 PaddleOCR PP-OCRv4 进行文字识别
    
    支持两种模式：
    1. 完整 OCR（检测 + 识别）
    2. 仅识别（复用已有检测框）
    
    Attributes:
        ocr: PaddleOCR 实例
    
    Example:
        >>> expert = OCRExpert(use_gpu=True)
        >>> result = expert.extract_text("path/to/image.jpg")
        >>> print(result['full_text'])
    """
    
    def __init__(self, use_gpu: bool = True):
        """
        初始化 OCR 专家
        
        Args:
            use_gpu: 是否使用 GPU 加速
        """
        config = load_router_config()
        model_cfg = config['models']['paddleocr']
        
        self.ocr = PaddleOCR(
            det_model_dir=model_cfg['det_model_dir'],
            rec_model_dir=model_cfg['rec_model_dir'],
            cls_model_dir=model_cfg['cls_model_dir'],
            use_angle_cls=True,
            lang=model_cfg['lang'],
            use_gpu=use_gpu,
            show_log=False
        )
    
    def extract_text(self, img_path: str) -> Dict[str, Any]:
        """
        执行完整 OCR（检测 + 识别）
        
        Args:
            img_path: 图片文件路径
        
        Returns:
            OCR 结果字典：
            - ok (bool): 是否成功
            - text_lines (List[Dict]): 文本行列表，每行包含 text 和 confidence
            - full_text (str): 完整文本（换行分隔）
            - box_count (int): 检测到的文本框数量
            - avg_confidence (float): 平均置信度
            - error (str, optional): 错误信息（如果失败）
        
        Example:
            >>> result = expert.extract_text("image.jpg")
            >>> if result['ok']:
            ...     print(f"识别到 {result['box_count']} 个文本框")
            ...     print(result['full_text'])
        """
        try:
            result = self.ocr.ocr(img_path, cls=True)
        except Exception as e:
            return {
                'ok': False,
                'error': str(e)[:200],
                'text_lines': [],
                'full_text': '',
                'box_count': 0
            }
        
        if not result or not result[0]:
            return {
                'ok': True,
                'text_lines': [],
                'full_text': '',
                'box_count': 0,
                'avg_confidence': 0.0
            }
        
        boxes = result[0]
        text_lines = []
        confidences = []
        
        for box in boxes:
            # box format: [[[x1,y1], [x2,y2], [x3,y3], [x4,y4]], [text, confidence]]
            text = box[1][0]
            conf = box[1][1]
            text_lines.append({
                'text': text,
                'confidence': round(conf, 4)
            })
            confidences.append(conf)
        
        full_text = '\n'.join([t['text'] for t in text_lines])
        avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
        
        return {
            'ok': True,
            'text_lines': text_lines,
            'full_text': full_text,
            'box_count': len(boxes),
            'avg_confidence': round(avg_conf, 4)
        }

    def recognize_only(self, img_path: str, boxes: List[List[List[float]]]) -> Dict[str, Any]:
        """
        仅执行识别（跳过检测），复用已有的检测框
        
        这是一个性能优化：当 Router 已经检测到文本框时，
        直接使用这些框进行识别，避免重复检测，可节省 30-40% 时间。
        
        Args:
            img_path: 图片文件路径
            boxes: 检测框列表，格式为 [[[x1,y1], [x2,y2], [x3,y3], [x4,y4]], ...]
        
        Returns:
            OCR 结果字典（格式同 extract_text）
        
        Example:
            >>> boxes = [[[10,10], [100,10], [100,50], [10,50]]]
            >>> result = expert.recognize_only("image.jpg", boxes)
        """
        if not boxes:
            return {'ok': True, 'text_lines': [], 'full_text': '', 'box_count': 0, 'avg_confidence': 0.0}

        try:
            # Load and crop images
            img = Image.open(img_path)
            img = img.convert('RGB')
            img_w, img_h = img.size
            
            crop_list = []
            for b in boxes:
                # b: [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
                # Get bounding rect
                xs = [p[0] for p in b]
                ys = [p[1] for p in b]
                x1, y1 = max(0, min(xs)), max(0, min(ys))
                x2, y2 = min(img_w, max(xs)), min(img_h, max(ys))
                
                # Crop
                crop = img.crop((x1, y1, x2, y2))
                # Convert to numpy for PaddleOCR
                crop_list.append(np.array(crop))
            
            # Batch recognition
            # When det=False with list of images, PaddleOCR returns all results in res[0]
            res = self.ocr.ocr(crop_list, det=False, rec=True, cls=True)
            
            # Reconstruct standard result format
            text_lines = []
            confidences = []
            
            # res[0] contains list of (text, conf) tuples for all images
            if res and res[0]:
                for item in res[0]:
                    if item and len(item) >= 2:
                        text, conf = item[0], item[1]
                        if text and text.strip():  # Skip empty results
                            text_lines.append({
                                'text': text.strip(),
                                'confidence': round(conf, 4)
                            })
                            confidences.append(conf)

            full_text = '\n'.join([t['text'] for t in text_lines])
            avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
            
            return {
                'ok': True,
                'text_lines': text_lines,
                'full_text': full_text,
                'box_count': len(boxes),
                'avg_confidence': round(avg_conf, 4)
            }
            
        except Exception as e:
            return {
                'ok': False,
                'error': f"RecOnly failed: {str(e)[:100]}",
                'text_lines': [],
                'full_text': '',
                'box_count': 0
            }


def process_all_images(
    messages_path: str,
    raw_dir: str,
    output_dir: str,
    logs_dir: str,
    use_gpu: bool = True
) -> Dict[str, Any]:
    """
    处理所有图片消息，执行路由 + OCR
    
    完整流程：
    1. 加载所有图片类型的消息
    2. 初始化 Router 和 OCR Expert
    3. 对每张图片：
       - 质量检查（QC）
       - 媒体质量过滤（4 层级）
       - 路由分类（决定是否需要 OCR）
       - 执行 OCR（优化：复用检测框）
    4. 输出两个文件：OCR 结果 + QC 报告
    
    Args:
        messages_path: 消息文件路径（P1_messages_raw.jsonl）
        raw_dir: 原始数据目录（包含 image/ 子目录）
        output_dir: 输出目录（artifacts/before_merge/image/）
        logs_dir: 日志目录
        use_gpu: 是否使用 GPU
    
    Returns:
        统计信息字典：
        - total: 总图片数
        - ok: 成功加载的图片数
        - error: 加载失败的图片数
        - routes: 各路由类别的分布
        - ocr_processed: 执行 OCR 的图片数
        - ocr_skipped: 跳过 OCR 的图片数
        - filter_skip/lite/slice/full: 各过滤层级的图片数
    
    Outputs:
        - image_ocr_v1.jsonl: OCR 结果（仅包含有文字的图片）
        - image_qc_v1.jsonl: QC 报告（所有图片，包含路由和过滤信息）
    
    Example:
        >>> stats = process_all_images(
        ...     messages_path="raw/P1_messages_raw.jsonl",
        ...     raw_dir="raw",
        ...     output_dir="artifacts/before_merge/image",
        ...     logs_dir="logs",
        ...     use_gpu=True
        ... )
        >>> print(f"处理了 {stats['ocr_processed']} 张图片")
    """
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(logs_dir, exist_ok=True)
    
    # Output files
    ocr_output = os.path.join(output_dir, 'image_ocr_v1.jsonl')
    qc_output = os.path.join(output_dir, 'image_qc_v1.jsonl')
    
    # Clear previous outputs
    for f in [ocr_output, qc_output]:
        if os.path.exists(f):
            os.remove(f)
    
    # Load image messages
    print("Loading image messages...")
    messages = []
    with open(messages_path, 'r', encoding='utf-8') as f:
        for line in f:
            msg = json.loads(line)
            if msg.get('modality') == 'image':
                messages.append(msg)
    
    print(f"  Total image messages: {len(messages)}")
    
    # Initialize router and OCR expert
    print("Initializing Router and OCR Expert (GPU)...")
    router = ImageRouter(use_gpu=use_gpu)
    ocr_expert = OCRExpert(use_gpu=use_gpu)
    
    # Stats
    stats = {
        'total': 0,
        'ok': 0,
        'error': 0,
        'routes': {},
        'ocr_processed': 0,
        'ocr_skipped': 0,
        'rotated_images': 0,
        # 媒体过滤统计
        'filter_skip': 0,
        'filter_lite': 0,
        'filter_slice': 0,
        'filter_full': 0,
    }
    
    # Process each image
    print(f"\nProcessing {len(messages)} images...")
    for msg in tqdm(messages, desc="OCR处理", **tqdm_kwargs):
        msg_uid = msg.get('msg_uid', 'unknown')
        media_path = msg.get('media_path', '')
        
        abs_path = get_image_path(media_path, raw_dir)
        
        # 1. Load and QC
        img, qc = load_image_safe(abs_path)
        stats['total'] += 1
        
        if not qc['ok']:
            stats['error'] += 1
            # Write QC entry with error
            qc_entry = {
                'msg_uid': msg_uid,
                'media_path': media_path,
                'qc': qc,
                'route_class': 'ERROR',
                'ocr_result': None
            }
            with open(qc_output, 'a', encoding='utf-8') as f:
                f.write(json.dumps(qc_entry, ensure_ascii=False) + '\n')
            continue
        
        stats['ok'] += 1
        
        # 2. 媒体质量过滤
        width = qc.get('width', 0)
        height = qc.get('height', 0)
        file_size = os.path.getsize(abs_path) if os.path.exists(abs_path) else 0
        
        filter_decision = filter_image(width, height, file_size)
        
        # 更新过滤统计
        if filter_decision.tier == FilterTier.SKIP:
            stats['filter_skip'] += 1
        elif filter_decision.tier == FilterTier.LITE:
            stats['filter_lite'] += 1
        elif filter_decision.tier == FilterTier.SLICE:
            stats['filter_slice'] += 1
        else:
            stats['filter_full'] += 1
        
        # 如果跳过，写入跳过标记
        if filter_decision.should_skip:
            skip_marker = filter_decision.to_skip_marker()
            qc_entry = {
                'msg_uid': msg_uid,
                'media_path': media_path,
                'qc': qc,
                'route_class': 'SKIPPED',
                'filter_tier': filter_decision.tier.value,
                'filter_reason': filter_decision.reason,
                **skip_marker,
                'ocr_result': None,
                'need_ocr': False,
                'need_caption': False,
            }
            with open(qc_output, 'a', encoding='utf-8') as f:
                f.write(json.dumps(qc_entry, ensure_ascii=False) + '\n')
            continue
        
        # 3. Route
        decision = router.route(msg_uid, abs_path)
        route_class = decision.route_class
        stats['routes'][route_class] = stats['routes'].get(route_class, 0) + 1
        
        # Check rotation
        need_rotation = decision.why.get('need_rotation', False)
        if need_rotation:
            stats['rotated_images'] += 1
        
        # 4. OCR if needed (LITE 模式也做 OCR，但不做 VLM)
        ocr_result = None
        need_ocr = decision.need_ocr
        need_caption = decision.need_caption
        
        # LITE 模式：只做 OCR，不做 VLM Caption
        if filter_decision.tier == FilterTier.LITE:
            need_ocr = True
            need_caption = False
        
        if need_ocr:
            # Check if we have boxes from router to reuse
            router_boxes = decision.why.get('boxes')
            
            if router_boxes and len(router_boxes) > 0:
                # OPTIMIZATION: Reuse detection boxes
                ocr_result = ocr_expert.recognize_only(abs_path, router_boxes)
            else:
                # Fallback to full OCR
                ocr_result = ocr_expert.extract_text(abs_path)
                
            stats['ocr_processed'] += 1
        else:
            stats['ocr_skipped'] += 1
        
        # 5. Write QC entry with full result
        qc_entry = {
            'msg_uid': msg_uid,
            'media_path': media_path,
            'qc': qc,
            'route_class': route_class,
            'det_features': decision.why,
            'need_ocr': need_ocr,
            'need_caption': need_caption,
            'filter_tier': filter_decision.tier.value,
            'filter_reason': filter_decision.reason,
            'ocr_result': ocr_result
        }
        
        # SLICE 模式添加切片建议
        if filter_decision.tier == FilterTier.SLICE:
            qc_entry['slice_metadata'] = filter_decision.metadata
        
        with open(qc_output, 'a', encoding='utf-8') as f:
            f.write(json.dumps(qc_entry, ensure_ascii=False) + '\n')
        
        # 6. Write OCR result separately for TEXT_HEAVY and GRAY
        if ocr_result and ocr_result.get('ok') and ocr_result.get('box_count', 0) > 0:
            ocr_entry = {
                'msg_uid': msg_uid,
                'route_class': route_class,
                'full_text': ocr_result['full_text'],
                'box_count': ocr_result['box_count'],
                'avg_confidence': ocr_result['avg_confidence']
            }
            with open(ocr_output, 'a', encoding='utf-8') as f:
                f.write(json.dumps(ocr_entry, ensure_ascii=False) + '\n')
    
    # Summary
    print("\n" + "=" * 60)
    print("Processing Complete!")
    print("=" * 60)
    print(f"\nStats:")
    print(f"  Total: {stats['total']}")
    print(f"  OK: {stats['ok']}")
    print(f"  Errors: {stats['error']}")
    print(f"\n媒体过滤统计:")
    print(f"  SKIP (跳过): {stats['filter_skip']}")
    print(f"  LITE (轻量): {stats['filter_lite']}")
    print(f"  SLICE (切片): {stats['filter_slice']}")
    print(f"  FULL (完整): {stats['filter_full']}")
    print(f"\nRoute Distribution:")
    for route, count in stats['routes'].items():
        print(f"  {route}: {count}")
    print(f"\nOCR Processing:")
    print(f"  Processed: {stats['ocr_processed']}")
    print(f"  Skipped (visual only): {stats['ocr_skipped']}")
    print(f"\nOutputs:")
    print(f"  QC results:  {qc_output}")
    print(f"  OCR results: {ocr_output}")
    
    return stats


if __name__ == '__main__':
    # Load paths
    raw_dir = PATHS.get('dirs', {}).get('raw', '/data/demo/raw')
    messages_path = PATHS.get('raw', {}).get('messages', f'{raw_dir}/P1_messages_raw.jsonl')
    output_dir = PATHS.get('artifacts', {}).get('image_before', f'{PROJECT_ROOT}/artifacts/before_merge/image')
    logs_dir = PATHS.get('dirs', {}).get('logs', f'{PROJECT_ROOT}/logs')
    
    # Read use_gpu from config
    config = load_router_config()
    use_gpu = config.get('models', {}).get('paddleocr', {}).get('use_gpu', False)
    
    print("=" * 60)
    print("Image Processing Pipeline - Full Run")
    print(f"  use_gpu: {use_gpu}")
    print("=" * 60)
    
    stats = process_all_images(
        messages_path=messages_path,
        raw_dir=raw_dir,
        output_dir=output_dir,
        logs_dir=logs_dir,
        use_gpu=use_gpu
    )
    
    print("\\n✅ Full processing completed!")

