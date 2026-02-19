# -*- coding: utf-8 -*-
"""
质量验证器

验证压缩质量，计算语义相似度
标记低质量压缩并触发 fallback

用法：
    from scripts.compression.quality_validator import QualityValidator
    
    validator = QualityValidator()
    result = validator.validate_compression(original, compressed)
"""

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import yaml


@dataclass
class ValidationResult:
    """验证结果"""
    is_valid: bool
    similarity_score: float
    compression_ratio: float
    quality_level: str  # 'high', 'medium', 'low'
    issues: List[str]
    needs_fallback: bool


@dataclass
class QualityConfig:
    """质量配置"""
    enabled: bool = True
    similarity_threshold: float = 0.7
    low_quality_threshold: float = 0.5
    compression_ratio_warn: float = 2.0
    compression_ratio_error: float = 1.5
    sampling_rate: float = 0.05


class QualityValidator:
    """质量验证器：语义相似度计算和质量标记"""
    
    def __init__(self, config_path: str = "configs/compression.yaml"):
        self.config = self._load_config(config_path)
        self.quality_config = self._parse_quality_config()
        
        # 嵌入模型（延迟加载）
        self._model = None
        self._model_loaded = False
        
        # 统计信息
        self.stats = {
            "total_validated": 0,
            "high_quality": 0,
            "medium_quality": 0,
            "low_quality": 0,
            "fallback_triggered": 0,
            "avg_similarity": 0.0,
            "total_similarity": 0.0
        }
    
    def _load_config(self, config_path: str) -> dict:
        """加载配置文件"""
        path = Path(config_path)
        if not path.exists():
            return {}
        with open(path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    
    def _parse_quality_config(self) -> QualityConfig:
        """解析质量配置"""
        cfg = self.config.get('quality', {})
        sim_cfg = cfg.get('semantic_similarity', {})
        ratio_cfg = cfg.get('compression_ratio', {})
        sampling_cfg = cfg.get('sampling', {})
        
        return QualityConfig(
            enabled=cfg.get('enabled', True),
            similarity_threshold=sim_cfg.get('threshold', 0.7),
            low_quality_threshold=sim_cfg.get('low_quality_threshold', 0.5),
            compression_ratio_warn=ratio_cfg.get('warn_if_below', 2.0),
            compression_ratio_error=ratio_cfg.get('error_if_below', 1.5),
            sampling_rate=sampling_cfg.get('rate', 0.05)
        )
    
    def _load_model(self):
        """加载嵌入模型"""
        if self._model_loaded:
            return
        
        try:
            from sentence_transformers import SentenceTransformer
            
            global_cfg = self.config.get('global', {})
            embed_cfg = global_cfg.get('embedding_model', {})
            model_path = embed_cfg.get('path', 
                '/data/models/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')
            
            print(f"[INFO] 加载嵌入模型: {model_path}")
            self._model = SentenceTransformer(model_path)
            self._model_loaded = True
            
        except ImportError:
            print("[WARN] sentence-transformers 未安装，使用简单相似度计算")
            self._model = None
            self._model_loaded = True
    
    def _compute_similarity_simple(self, text1: str, text2: str) -> float:
        """
        简单的相似度计算（基于词重叠）
        当 sentence-transformers 不可用时使用
        """
        if not text1 or not text2:
            return 0.0
        
        # 分词（简单按字符）
        chars1 = set(text1)
        chars2 = set(text2)
        
        if not chars1 or not chars2:
            return 0.0
        
        # Jaccard 相似度
        intersection = len(chars1 & chars2)
        union = len(chars1 | chars2)
        
        return intersection / union if union > 0 else 0.0
    
    def _compute_similarity_embedding(self, text1: str, text2: str) -> float:
        """
        基于嵌入的语义相似度计算
        """
        if self._model is None:
            return self._compute_similarity_simple(text1, text2)
        
        try:
            import numpy as np
            
            # 计算嵌入
            embeddings = self._model.encode([text1, text2])
            
            # 余弦相似度
            similarity = np.dot(embeddings[0], embeddings[1]) / (
                np.linalg.norm(embeddings[0]) * np.linalg.norm(embeddings[1])
            )
            
            return float(similarity)
            
        except Exception as e:
            print(f"[WARN] 嵌入计算失败: {e}")
            return self._compute_similarity_simple(text1, text2)
    
    def compute_similarity(self, original: str, compressed: str) -> float:
        """
        计算语义相似度
        
        Args:
            original: 原始文本
            compressed: 压缩后文本
        
        Returns:
            相似度分数 (0.0 - 1.0)
        """
        self._load_model()
        
        if self._model is not None:
            return self._compute_similarity_embedding(original, compressed)
        else:
            return self._compute_similarity_simple(original, compressed)
    
    def validate_compression(self, original: str, compressed: str,
                            compression_ratio: Optional[float] = None) -> ValidationResult:
        """
        验证压缩质量
        
        Args:
            original: 原始文本
            compressed: 压缩后文本
            compression_ratio: 压缩比（可选，如果不提供则计算）
        
        Returns:
            验证结果
        """
        self.stats["total_validated"] += 1
        
        # 计算相似度
        similarity = self.compute_similarity(original, compressed)
        self.stats["total_similarity"] += similarity
        
        # 计算压缩比
        if compression_ratio is None:
            orig_len = len(original)
            comp_len = len(compressed)
            compression_ratio = orig_len / comp_len if comp_len > 0 else 1.0
        
        # 判断质量级别
        issues = []
        needs_fallback = False
        
        if similarity >= self.quality_config.similarity_threshold:
            quality_level = 'high'
            self.stats["high_quality"] += 1
        elif similarity >= self.quality_config.low_quality_threshold:
            quality_level = 'medium'
            self.stats["medium_quality"] += 1
            issues.append(f"相似度偏低: {similarity:.2f}")
        else:
            quality_level = 'low'
            self.stats["low_quality"] += 1
            issues.append(f"相似度过低: {similarity:.2f}")
            needs_fallback = True
            self.stats["fallback_triggered"] += 1
        
        # 检查压缩比
        if compression_ratio < self.quality_config.compression_ratio_error:
            issues.append(f"压缩比过低: {compression_ratio:.2f}x")
        elif compression_ratio < self.quality_config.compression_ratio_warn:
            issues.append(f"压缩比偏低: {compression_ratio:.2f}x")
        
        is_valid = quality_level != 'low' and len(issues) == 0
        
        return ValidationResult(
            is_valid=is_valid,
            similarity_score=similarity,
            compression_ratio=compression_ratio,
            quality_level=quality_level,
            issues=issues,
            needs_fallback=needs_fallback
        )
    
    def validate_batch(self, items: List[Dict]) -> List[ValidationResult]:
        """
        批量验证
        
        Args:
            items: 包含 'original' 和 'compressed' 字段的字典列表
        
        Returns:
            验证结果列表
        """
        results = []
        for item in items:
            original = item.get('original', '')
            compressed = item.get('compressed', '')
            ratio = item.get('compression_ratio')
            
            result = self.validate_compression(original, compressed, ratio)
            results.append(result)
        
        return results
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        stats = self.stats.copy()
        if stats["total_validated"] > 0:
            stats["avg_similarity"] = round(
                stats["total_similarity"] / stats["total_validated"], 3
            )
        return stats


def main():
    """测试质量验证器"""
    validator = QualityValidator()
    
    # 测试用例
    test_cases = [
        {
            "original": "这张图片展示了一个温馨的场景。场景是在一个铺着格子图案床单的床上，床上躺着一只猫咪。猫咪的身体是黑白相间的条纹，四肢伸展，似乎在休息或者睡觉。",
            "compressed": "温馨场景，格子床单上躺着黑白条纹猫咪，四肢伸展休息"
        },
        {
            "original": "我觉得重庆人和四川人不应该第一瞬间就能看得出来这个人是不是gay",
            "compressed": "重庆四川人不应该一眼看出是否gay"
        },
        {
            "original": "这是一段很长的文字描述",
            "compressed": "完全不相关的内容"
        }
    ]
    
    print("=== 质量验证测试 ===")
    for i, case in enumerate(test_cases):
        result = validator.validate_compression(case["original"], case["compressed"])
        print(f"\n测试 {i+1}:")
        print(f"  原文: {case['original'][:50]}...")
        print(f"  压缩: {case['compressed']}")
        print(f"  相似度: {result.similarity_score:.3f}")
        print(f"  质量: {result.quality_level}")
        print(f"  问题: {result.issues}")
        print(f"  需要回退: {result.needs_fallback}")
    
    print("\n=== 统计 ===")
    print(validator.get_stats())


if __name__ == '__main__':
    main()
