#!/usr/bin/env python3
"""
图片内容分类模块 (Image Triage Module)

功能：
- NSFW/Gore/Normal/Document 内容快速分类
- 使用 Falconsai/nsfw_image_detection 进行预分类
- 为专家路由提供决策依据

分类类型：
- TYPE_A_NSFW: NSFW 内容（nsfw_score > 0.5）
- TYPE_B_GORE: 暴力/血腥内容（NSFW 高分 + OCR 包含暴力关键词）
- TYPE_C_NORMAL: 正常内容（默认）
- TYPE_D_DOC: 文档/截图（text_area_ratio > 0.15）

分类优先级：
1. TYPE_D_DOC（文字密集型）- 路由到 Pixtral 12B
2. TYPE_B_GORE（暴力内容）- 路由到 Gore Expert
3. TYPE_A_NSFW（NSFW 内容）- 路由到 NSFW Expert
4. TYPE_C_NORMAL（正常内容）- 路由到 Default Caption Expert

Gore 检测策略：
- NSFW 分类器无法区分性内容和暴力内容
- 需要结合 OCR 文本进行二次判断
- 关键词：血、伤口、尸体、死亡、暴力、杀、砍、刺、枪、炸
- 英文：blood, wound, injury, gore, violence, dead, death, kill, murder

使用示例：
    from scripts.image.experts.image_triage import ImageTriage
    
    triage = ImageTriage()
    result = triage.classify(
        image_path="/path/to/image.jpg",
        router_features={'text_area_ratio': 0.2},
        ocr_text="图片中的文字"
    )
    print(result.content_type)  # TYPE_D_DOC
    print(result.confidence)    # 0.8

依赖：
- transformers: NSFW 分类器
- torch: GPU 加速
- PIL: 图片加载

作者：[Author]
项目：wechatDHA - 微信聊天记录多模态处理流水线
更新于：2026-02-02
"""

import os
import sys
import torch
import logging
from pathlib import Path
from typing import Dict, Any, Tuple, Optional
from dataclasses import dataclass
from PIL import Image
from transformers import pipeline, AutoModelForImageClassification, AutoImageProcessor

# Setup paths
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


@dataclass
class TriageResult:
    """Triage classification result"""
    content_type: str           # TYPE_A_NSFW, TYPE_B_GORE, TYPE_C_NORMAL, TYPE_D_DOC
    confidence: float           # 0.0 - 1.0
    nsfw_score: float           # Raw NSFW probability
    sfw_score: float            # Raw SFW probability
    text_score: Optional[float] # From router.py if available


class ImageTriage:
    """
    Content-based image triage using NSFW classifier.
    Routes images to appropriate expert models.
    """
    
    # Thresholds
    NSFW_THRESHOLD = 0.5        # Above this = TYPE_A_NSFW
    GORE_KEYWORDS = ['blood', 'wound', 'injury', 'gore', 'violence', 'dead', 'death']
    TEXT_HEAVY_THRESHOLD = 0.15  # text_area_ratio above this may go to Pixtral
    
    def __init__(self, model_path: str = "/data/models/nsfw-classifier"):
        """Initialize NSFW classifier"""
        self.model_path = model_path
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self._classifier = None
        
        logger.info(f"ImageTriage initialized with model: {model_path}")
        logger.info(f"Device: {self.device}")
        
    def _load_classifier(self):
        """Lazy load the NSFW classifier"""
        if self._classifier is not None:
            return
            
        logger.info("Loading NSFW classifier...")
        self._classifier = pipeline(
            "image-classification",
            model=self.model_path,
            device=0 if self.device == "cuda" else -1
        )
        logger.info("NSFW classifier loaded.")
        
    def classify(
        self, 
        image_path: str, 
        router_features: Optional[Dict[str, Any]] = None,
        ocr_text: Optional[str] = None
    ) -> TriageResult:
        """
        Classify an image for content type.
        
        Args:
            image_path: Path to the image file
            router_features: Optional features from router.py (text_area_ratio, ocr_text, etc.)
            ocr_text: Optional OCR text for gore keyword detection
            
        Returns:
            TriageResult with content_type and confidence scores
        """
        self._load_classifier()
        
        try:
            # Run NSFW classification
            results = self._classifier(image_path)
            
            # Parse results (format: [{'label': 'nsfw', 'score': 0.9}, {'label': 'normal', 'score': 0.1}])
            nsfw_score = 0.0
            sfw_score = 0.0
            for r in results:
                if r['label'].lower() == 'nsfw':
                    nsfw_score = r['score']
                elif r['label'].lower() == 'normal':
                    sfw_score = r['score']
                    
            # Get features from router if available
            text_score = None
            if router_features:
                text_score = router_features.get('text_area_ratio', 0.0)
                # Also check if ocr_text is in router_features
                if ocr_text is None:
                    ocr_text = router_features.get('ocr_text', '')
            
            # Determine content type
            content_type, confidence = self._determine_content_type(
                nsfw_score, sfw_score, text_score, ocr_text
            )
            
            return TriageResult(
                content_type=content_type,
                confidence=confidence,
                nsfw_score=nsfw_score,
                sfw_score=sfw_score,
                text_score=text_score
            )
            
        except Exception as e:
            logger.error(f"Error classifying {image_path}: {e}")
            # Default to normal on error
            return TriageResult(
                content_type="TYPE_C_NORMAL",
                confidence=0.5,
                nsfw_score=0.0,
                sfw_score=1.0,
                text_score=None
            )
    
    def _determine_content_type(
        self, 
        nsfw_score: float, 
        sfw_score: float, 
        text_score: Optional[float],
        ocr_text: Optional[str] = None
    ) -> Tuple[str, float]:
        """
        Determine content type based on scores.
        
        Priority:
        1. TYPE_D_DOC (text_score > 0.15) - Document/Screenshot
        2. TYPE_B_GORE (NSFW high + gore keywords in OCR) - Violence/Blood
        3. TYPE_A_NSFW (nsfw_score > 0.5) - NSFW content
        4. TYPE_C_NORMAL - Default safe content
        
        Note: Gore detection requires OCR text analysis since NSFW classifier
        cannot distinguish between sexual and violent content.
        """
        # Check for document/text-heavy first
        if text_score is not None and text_score > self.TEXT_HEAVY_THRESHOLD:
            return "TYPE_D_DOC", 0.8
        
        # Check for NSFW content
        if nsfw_score > self.NSFW_THRESHOLD:
            # Secondary check: if OCR contains gore keywords, route to gore expert
            if ocr_text and self._contains_gore_keywords(ocr_text):
                return "TYPE_B_GORE", nsfw_score
            return "TYPE_A_NSFW", nsfw_score
        
        # Default to normal
        return "TYPE_C_NORMAL", sfw_score
    
    def _contains_gore_keywords(self, text: str) -> bool:
        """Check if text contains gore-related keywords"""
        if not text:
            return False
        text_lower = text.lower()
        # 中英文关键词
        gore_keywords_zh = ['血', '伤口', '尸体', '死亡', '暴力', '杀', '砍', '刺', '枪', '炸']
        gore_keywords_en = ['blood', 'wound', 'injury', 'gore', 'violence', 'dead', 'death', 'kill', 'murder']
        
        for kw in gore_keywords_zh + gore_keywords_en:
            if kw in text_lower:
                return True
        return False
    
    def unload(self):
        """Unload classifier to free VRAM"""
        if self._classifier is not None:
            del self._classifier
            self._classifier = None
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            logger.info("NSFW classifier unloaded.")


# Singleton for reuse
_triage_instance: Optional[ImageTriage] = None

def get_triage() -> ImageTriage:
    """Get or create triage singleton"""
    global _triage_instance
    if _triage_instance is None:
        _triage_instance = ImageTriage()
    return _triage_instance


# === Test ===
if __name__ == '__main__':
    import json
    
    print("Testing ImageTriage...")
    triage = ImageTriage()
    
    # Test with sample image
    test_path = "/data/demo/raw/image/test.jpg"
    
    if os.path.exists(test_path):
        result = triage.classify(test_path)
        print(f"\nTriage Result:")
        print(f"  Content Type: {result.content_type}")
        print(f"  Confidence: {result.confidence:.3f}")
        print(f"  NSFW Score: {result.nsfw_score:.3f}")
        print(f"  SFW Score: {result.sfw_score:.3f}")
    else:
        print(f"Test image not found: {test_path}")
        
    # Cleanup
    triage.unload()
    print("\nTest complete.")
