#!/usr/bin/env python3
"""
专家路由模块 (Expert Router Module)

功能：
- 统一的专家模型入口，根据内容分类路由到合适的专家
- 管理显存（16GB 5070 Ti），一次只加载一个大模型
- 支持四种专家模型：NSFW、Gore、Document、Default Caption

路由流程：
1. router.py (L1/L2) → route_class (VISUAL_ONLY, TEXT_PRIMARY, etc.)
2. image_triage.py → content_type (TYPE_A_NSFW, TYPE_B_GORE, TYPE_C_NORMAL, TYPE_D_DOC)
3. expert_router.py → 调用对应的专家模型

专家模型：
- TYPE_A_NSFW → NSFWExpert (MiniCPM-V 4.5 Abliterated + nsfw-caption-v3 Ensemble)
- TYPE_B_GORE → GoreExpert (Qwen2.5-VL-7B Abliterated)
- TYPE_D_DOC → DocExpert (Pixtral 12B GGUF)
- TYPE_C_NORMAL → CaptionExpert (Qwen2.5-VL-7B)

显存管理：
- 5070 Ti = 16GB VRAM，一次只加载一个大模型
- 切换模型时自动卸载当前模型并清理显存
- 使用 gc.collect() + torch.cuda.empty_cache() + synchronize()

使用示例：
    from scripts.image.experts.expert_router import ExpertRouter
    
    router = ExpertRouter(config)
    result = router.process_image(
        msg_uid="msg_123",
        image_path="/path/to/image.jpg",
        route_class="VISUAL_ONLY"
    )
    print(result.caption)
    router.cleanup()

依赖：
- torch: 显存管理
- transformers: 模型加载
- 各专家模块：image_triage, gore_expert, nsfw_expert, caption_expert, doc_expert

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
from dataclasses import dataclass

# Setup paths
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.image.experts.image_triage import ImageTriage, TriageResult
from scripts.image.experts.gore_expert import GoreExpert
from scripts.image.experts.nsfw_expert import NSFWExpert
from scripts.image.experts.caption_expert import CaptionExpert
from scripts.image.experts.doc_expert import DocExpert

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


@dataclass
class ExpertResult:
    """Result from expert processing"""
    msg_uid: str
    image_path: str
    route_class: str          # From router.py L1/L2
    content_type: str         # From triage
    triage_confidence: float
    caption: str
    expert_used: str
    metadata: Dict[str, Any]


class ExpertRouter:
    """
    Routes images to appropriate expert models based on content type.
    Manages VRAM by loading/unloading experts as needed.
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        
        # Initialize triage (lightweight, always loaded)
        self._triage = ImageTriage()
        
        # Expert models (lazy loaded, only one at a time for VRAM management)
        # 5070 Ti = 16GB VRAM, 一次只加载一个大模型
        self._current_expert_type = None
        self._gore_expert = None
        self._nsfw_expert = None
        self._doc_expert = None      # DocExpert (Pixtral 12B)
        self._default_expert = None  # CaptionExpert
        
        logger.info("ExpertRouter initialized (VRAM mode: single expert)")
        
    def _unload_all_experts(self):
        """Unload all expert models to free VRAM (16GB 5070 Ti constraint)"""
        if self._gore_expert:
            self._gore_expert.unload()
            self._gore_expert = None
        if self._nsfw_expert:
            self._nsfw_expert.unload()
            self._nsfw_expert = None
        if self._doc_expert:
            self._doc_expert.unload()
            self._doc_expert = None
        if self._default_expert:
            self._default_expert.unload()
            self._default_expert = None
            
        self._current_expert_type = None
        
        # 强制垃圾回收和清空 CUDA 缓存
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            # 额外的显存清理
            torch.cuda.synchronize()
        logger.info("All experts unloaded, VRAM cleared")
            
    def _get_gore_expert(self) -> GoreExpert:
        """Get or load gore expert"""
        if self._current_expert_type != "gore":
            self._unload_all_experts()
            self._gore_expert = GoreExpert()
            self._current_expert_type = "gore"
        return self._gore_expert
        
    def _get_nsfw_expert(self) -> NSFWExpert:
        """Get or load NSFW expert"""
        if self._current_expert_type != "nsfw":
            self._unload_all_experts()
            # 从配置中读取 NSFW 专家参数
            nsfw_config = self.config.get('experts', {}).get('nsfw', {})
            generation_config = nsfw_config.get('generation', None)
            
            self._nsfw_expert = NSFWExpert(
                minicpm_path=nsfw_config.get('minicpm_path', "/data/models/minicpm-v-4.5-abliterated-int8"),
                nsfw_v3_path=nsfw_config.get('nsfw_v3_path', "/data/models/qwen2.5-vl-7b-nsfw-caption-v3"),
                ensemble_mode=nsfw_config.get('ensemble_mode', 'serial'),
                prefer_minicpm=nsfw_config.get('prefer_minicpm', True),
                generation_config=generation_config
            )
            self._current_expert_type = "nsfw"
        return self._nsfw_expert
        
    def _get_doc_expert(self) -> DocExpert:
        """Get or load document expert (Pixtral 12B)"""
        if self._current_expert_type != "doc":
            self._unload_all_experts()
            self._doc_expert = DocExpert()
            self._current_expert_type = "doc"
        return self._doc_expert
        
    def _get_default_expert(self) -> CaptionExpert:
        """Get or load default caption expert"""
        if self._current_expert_type != "default":
            self._unload_all_experts()
            self._default_expert = CaptionExpert()
            self._current_expert_type = "default"
        return self._default_expert
        
    def process_image(
        self, 
        msg_uid: str,
        image_path: str,
        router_features: Optional[Dict[str, Any]] = None,
        route_class: str = "UNKNOWN"
    ) -> ExpertResult:
        """
        Process a single image through triage and expert pipeline.
        
        Args:
            msg_uid: Message unique identifier
            image_path: Path to image file
            router_features: Features from router.py (text_area_ratio, etc.)
            route_class: Classification from router.py L1/L2
            
        Returns:
            ExpertResult with caption and metadata
        """
        # Step 1: Triage classification
        triage_result = self._triage.classify(image_path, router_features)
        
        logger.info(
            f"[{msg_uid}] Triage: {triage_result.content_type} "
            f"(conf={triage_result.confidence:.2f}, nsfw={triage_result.nsfw_score:.2f})"
        )
        
        # Step 2: Route to appropriate expert
        caption = ""
        expert_used = ""
        metadata = {}
        
        try:
            if triage_result.content_type == "TYPE_A_NSFW":
                # NSFW content → NSFW Expert (Ensemble)
                expert = self._get_nsfw_expert()
                caption, metadata = expert.generate_caption(image_path)
                expert_used = "nsfw_expert"
                
            elif triage_result.content_type == "TYPE_B_GORE":
                # Gore content → Gore Expert (Abliterated)
                expert = self._get_gore_expert()
                caption, metadata = expert.generate_caption(image_path)
                expert_used = "gore_expert"
                
            elif triage_result.content_type == "TYPE_D_DOC":
                # Document/text-heavy → DocExpert (Pixtral 12B)
                expert = self._get_doc_expert()
                caption, metadata = expert.generate_caption(image_path)
                expert_used = "doc_expert"
                
            else:  # TYPE_C_NORMAL
                # Normal content → Default CaptionExpert
                expert = self._get_default_expert()
                caption, is_fallback = expert.generate_caption(image_path)
                metadata = {"is_fallback": is_fallback}
                expert_used = "default_expert"
                
        except Exception as e:
            logger.error(f"Error processing {msg_uid}: {e}")
            caption = f"[ERROR] {str(e)}"
            metadata = {"error": str(e)}
            expert_used = "error"
            
        return ExpertResult(
            msg_uid=msg_uid,
            image_path=image_path,
            route_class=route_class,
            content_type=triage_result.content_type,
            triage_confidence=triage_result.confidence,
            caption=caption,
            expert_used=expert_used,
            metadata={
                **metadata,
                "nsfw_score": triage_result.nsfw_score,
                "sfw_score": triage_result.sfw_score,
                "text_score": triage_result.text_score
            }
        )
    
    def result_to_dict(self, result: ExpertResult) -> Dict[str, Any]:
        """Convert ExpertResult to dictionary for JSON serialization"""
        return {
            "msg_uid": result.msg_uid,
            "image_path": result.image_path,
            "route_class": result.route_class,
            "content_type": result.content_type,
            "triage_confidence": result.triage_confidence,
            "caption": result.caption,
            "expert_used": result.expert_used,
            "metadata": result.metadata
        }
        
    def cleanup(self):
        """Cleanup all resources"""
        logger.info("Starting ExpertRouter cleanup...")
        self._triage.unload()
        self._unload_all_experts()
        # 额外的显存清理
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
        logger.info("ExpertRouter cleanup complete")


# === Test ===
if __name__ == '__main__':
    import json
    
    print("Testing ExpertRouter...")
    router = ExpertRouter()
    
    test_path = "/data/demo/raw/image/test.jpg"
    
    if os.path.exists(test_path):
        result = router.process_image(
            msg_uid="TEST_001",
            image_path=test_path,
            route_class="VISUAL_ONLY"
        )
        
        print(f"\nResult:")
        print(json.dumps(router.result_to_dict(result), ensure_ascii=False, indent=2))
    else:
        print(f"Test image not found: {test_path}")
        
    router.cleanup()
    print("\nTest complete.")
