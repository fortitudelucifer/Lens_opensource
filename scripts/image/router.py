#!/usr/bin/env python3
"""
Image Router Module - Phase 2

Implements 3-layer routing:
- L1: det-only features (box_count, text_area_ratio)
- L2: Rule-based gray zone handling (future: VLM 3B)
- Decision logging to router_decisions.jsonl
"""

import os
import sys
import json
import yaml
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional
from dataclasses import dataclass

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts._common.path_utils import PATHS
from scripts.image.loader import load_image_safe, get_image_path

# Initialize PaddleOCR
from paddleocr import PaddleOCR


@dataclass
class RouterDecision:
    """Router decision result"""
    msg_uid: str
    src_path: str
    decision_layer: int          # 1 or 2
    route_class: str             # TEXT_HEAVY, VISUAL_ONLY, GRAY, MIXED
    why: Dict[str, Any]          # Explanation features
    need_ocr: bool
    need_caption: bool


def load_router_config() -> Dict[str, Any]:
    """Load router configuration from configs/router.yaml"""
    config_path = PROJECT_ROOT / 'configs' / 'router.yaml'
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


class ImageRouter:
    """
    Image router with det-only L1 classification.
    """
    
    def __init__(self, use_gpu: bool = False):
        self.config = load_router_config()
        
        # Initialize PaddleOCR with local models
        model_cfg = self.config['models']['paddleocr']
        self.ocr = PaddleOCR(
            det_model_dir=model_cfg['det_model_dir'],
            rec_model_dir=model_cfg['rec_model_dir'],
            cls_model_dir=model_cfg['cls_model_dir'],
            use_angle_cls=True,
            lang=model_cfg['lang'],
            use_gpu=use_gpu,
            show_log=False
        )
        
        # L1 thresholds
        self.th = self.config['thresholds']
        
    def compute_det_features(self, img_path: str) -> Dict[str, Any]:
        """
        Run det-only to compute features for routing.
        Returns dict with box_count, text_area_ratio, boxes, etc.
        """
        # Run OCR detection only
        try:
            # rec=False returns only boxes: [[[x1,y1], [x2,y2], [x3,y3], [x4,y4]], ...]
            result = self.ocr.ocr(img_path, det=True, rec=False, cls=False)
        except Exception as e:
            return {
                'box_count': 0,
                'text_area_ratio': 0.0,
                'error': str(e)[:100]
            }
        
        if not result or not result[0]:
            return {
                'box_count': 0,
                'text_area_ratio': 0.0,
                'boxes': []
            }
        
        boxes = result[0]
        box_count = len(boxes)
        
        # Filter effective boxes (ignore watermark/noise)
        effective_boxes = []
        img_w, img_h = 1000, 1000 # Default if image open fails
        try:
            from PIL import Image
            with Image.open(img_path) as img:
                img_w, img_h = img.size
        except:
            pass

        img_area = img_w * img_h
        
        for b in boxes:
            # b format when rec=False: [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
            # Calculate box height and center
            # b[0] is top-left, b[1] is top-right, b[2] is bottom-right, b[3] is bottom-left
            y1 = b[0][1]
            y2 = b[2][1]
            h = abs(y2 - y1)
            # cy = (y1 + y2) / 2
            # cx = (b[0][0] + b[2][0]) / 2
            
            # Filter 1: Too small (likely noise)
            if h / img_h < self.th.get('min_box_height_ratio', 0.01):
                continue
                
            # Filter 2: Extreme edges (header/footer/watermark)
            # if cy / img_h < 0.05 or cy / img_h > 0.95:
            #     continue
            
            effective_boxes.append(b)
            
        box_count = len(effective_boxes)
        
        text_area = sum([
            abs((b[2][0] - b[0][0]) * (b[2][1] - b[0][1]))
            for b in effective_boxes
        ])
        text_area_ratio = text_area / img_area if img_area > 0 else 0
        
        # Compute avg box height
        avg_box_height = 0
        if box_count > 0:
            heights = [abs(b[2][1] - b[0][1]) for b in boxes]
            avg_box_height = sum(heights) / len(heights)
        
        return {
            'box_count': box_count,
            'text_area_ratio': round(text_area_ratio, 4),
            'avg_box_height': round(avg_box_height, 2),
            'boxes_summary': box_count,  # Effective count
            'raw_box_count': len(boxes),  # Original count
            'boxes': effective_boxes  # Added for orientation check
        }
    

    def classify_l1(self, features: Dict[str, Any]) -> str:
        """
        L1 classification based on det features.
        Returns: VISUAL_ONLY, VISUAL_PRIMARY, TEXT_PRIMARY, or GRAY
        """
        box_count = features.get('box_count', 0)
        text_area_ratio = features.get('text_area_ratio', 0)
        
        cfg = self.th.get('l1', {})
        
        # 1. VISUAL_ONLY
        if box_count <= cfg['visual_only']['box_count_max']:
            return 'VISUAL_ONLY'
            
        # 2. VISUAL_PRIMARY
        vp = cfg['visual_primary']
        if box_count <= vp['box_count_max'] and text_area_ratio < vp['text_area_ratio_max']:
            return 'VISUAL_PRIMARY'
            
        # 3. TEXT_PRIMARY (requires BOTH conditions: enough boxes AND sufficient ratio)
        tp = cfg['text_primary']
        if box_count >= tp['box_count_min'] and text_area_ratio >= tp['text_area_ratio_min']:
            return 'TEXT_PRIMARY'
            
        # 4. GRAY (Needs L2)
        return 'GRAY'

    def classify_l2_rules(self, features: Dict[str, Any]) -> str:
        """L2 Rule-based classification for GRAY items using ratio as primary discriminator"""
        box_count = features.get('box_count', 0)
        text_area_ratio = features.get('text_area_ratio', 0)
        
        cfg = self.th.get('l2', {})
        hv = cfg['hybrid_visual_main']
        ht = cfg['hybrid_text_main']
        
        # Primary check: text_area_ratio
        # Low ratio (<= threshold) -> Visual dominant
        # High ratio (>= threshold) -> Text dominant
        
        # HYBRID_TEXT_MAIN: Higher ratio (text-heavy visual)
        if text_area_ratio >= ht.get('text_area_ratio_min', 0.05):
            return 'HYBRID_TEXT_MAIN'
        
        # HYBRID_VISUAL_MAIN: Lower ratio (visual with text overlay)
        if text_area_ratio <= hv.get('text_area_ratio_max', 0.04):
            return 'HYBRID_VISUAL_MAIN'
            
        # Edge case: ratio between thresholds, use box count
        if box_count <= hv['box_count_max']:
            return 'HYBRID_VISUAL_MAIN'
            
        return 'HYBRID_TEXT_MAIN'

    def get_processing_strategy(self, route_class: str) -> Dict[str, Any]:
        """Get processing flags from matrix"""
        matrix = self.config.get('processing_matrix', {})
        return matrix.get(route_class, {
            'need_ocr': True, 'need_caption': True, 'ocr_priority': 'low', 'caption_priority': 'low'
        })
    
    def route(self, msg_uid: str, img_path: str) -> RouterDecision:
        """
        Full routing decision for an image.
        Note: Orientation detection is now handled in loader.py with auto_rotate option.
        """
        # 1. Compute det features
        features = self.compute_det_features(img_path)
        
        # 2. L1 Classification
        route_class = self.classify_l1(features)
        
        # 3. L2 Routing (if GRAY)
        if route_class == 'GRAY':
            route_class = self.classify_l2_rules(features)
                
        # 4. Get Strategy
        strategy = self.get_processing_strategy(route_class)
        
        decision = RouterDecision(
            msg_uid=msg_uid,
            src_path=img_path,
            decision_layer=2 if route_class in ['HYBRID_TEXT_MAIN', 'HYBRID_VISUAL_MAIN'] else 1,
            route_class=route_class,
            why=features,
            need_ocr=strategy['need_ocr'],
            need_caption=strategy['need_caption']
        )
        
        # Add strategy info
        decision.why['strategies'] = strategy
        
        return decision
    
    def decision_to_dict(self, d: RouterDecision) -> Dict[str, Any]:
        """Convert RouterDecision to dict for JSON serialization."""
        return {
            'msg_uid': d.msg_uid,
            'src_path': d.src_path,
            'decision_layer': d.decision_layer,
            'route_class': d.route_class,
            'why': d.why,
            'need_ocr': d.need_ocr,
            'need_caption': d.need_caption
        }


def append_router_decision(decision: Dict[str, Any], log_path: Optional[str] = None):
    """Append router decision to logs/router_decisions.jsonl"""
    if log_path is None:
        log_path = os.path.join(PATHS.get('dirs', {}).get('logs', PROJECT_ROOT / 'logs'), 'router_decisions.jsonl')
    
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    
    with open(log_path, 'a', encoding='utf-8') as f:
        f.write(json.dumps(decision, ensure_ascii=False) + '\n')


# === Test ===
if __name__ == '__main__':
    print("Initializing ImageRouter...")
    router = ImageRouter(use_gpu=False)
    
    # Test with sample image
    raw_dir = PATHS.get('dirs', {}).get('raw', '/data/demo/raw')
    test_path = f"{raw_dir}/image/test.jpg"
    
    print(f"\nRouting: {test_path}")
    decision = router.route('TEST_MSG_001', test_path)
    
    print(f"\nRouter Decision:")
    result = router.decision_to_dict(decision)
    for k, v in result.items():
        print(f"  {k}: {v}")
