# -*- coding: utf-8 -*-
"""
两阶段 PII 扫描器

主类，整合候选词提取、LLM 验证和人名替换功能。
提供与现有 PIIDetector 兼容的接口。
"""

import gc
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import yaml
from tqdm import tqdm

from .candidate_extractor import CandidateExtractor
from .llm_validator import LLMValidator
from .models import (
    CandidateList,
    ConfirmedName,
    ConfirmedNames,
    ValidationResult,
)
from .name_replacer import NameReplacer


@dataclass
class PIIMatch:
    """PII 匹配结果（兼容现有接口）"""
    type: str           # PII 类型（如 "PERSON"）
    value: str          # 匹配的值
    start: int          # 起始位置
    end: int            # 结束位置
    confidence: float   # 置信度
    source: str         # 来源（如 "two_stage_pii"）


class TwoStagePIIScanner:
    """两阶段 PII 扫描器"""
    
    def __init__(self, 
                 config_path: str = "configs/compression.yaml",
                 confirmed_names_path: str = "configs/confirmed_names.yaml",
                 model_path: str = "/data/models/Qwen2.5-7B-Instruct-AWQ"):
        """
        初始化扫描器
        
        Args:
            config_path: 压缩配置路径
            confirmed_names_path: 确认人名列表路径
            model_path: LLM 模型路径
        """
        self.config_path = config_path
        self.confirmed_names_path = confirmed_names_path
        self.model_path = model_path
        
        # 组件（延迟初始化）
        self._extractor: Optional[CandidateExtractor] = None
        self._validator: Optional[LLMValidator] = None
        self._replacer: Optional[NameReplacer] = None
        
        # 加载配置
        self._load_config()
    
    def _load_config(self):
        """加载配置"""
        config_path = Path(self.config_path)
        if config_path.exists():
            with open(config_path, 'r', encoding='utf-8') as f:
                self.config = yaml.safe_load(f) or {}
        else:
            self.config = {}
    
    @property
    def extractor(self) -> CandidateExtractor:
        """获取候选词提取器（延迟初始化）"""
        if self._extractor is None:
            self._extractor = CandidateExtractor()
        return self._extractor
    
    @property
    def validator(self) -> LLMValidator:
        """获取 LLM 验证器（延迟初始化）"""
        if self._validator is None:
            self._validator = LLMValidator(model_path=self.model_path)
        return self._validator
    
    @property
    def replacer(self) -> NameReplacer:
        """获取人名替换器（延迟初始化）"""
        if self._replacer is None:
            confirmed_path = Path(self.confirmed_names_path)
            if confirmed_path.exists():
                self._replacer = NameReplacer(
                    confirmed_names_path=str(confirmed_path)
                )
            else:
                self._replacer = NameReplacer()
        return self._replacer
    
    def run_phase1(self, 
                   input_path: str,
                   output_path: str = None,
                   batch_size: int = 50,
                   show_progress: bool = True) -> Tuple[CandidateList, ValidationResult]:
        """
        运行 Phase 1：离线扫描
        
        Args:
            input_path: 输入文件路径（enriched_full.jsonl 或 agent_sft_l1.jsonl）
            output_path: 确认人名列表输出路径（默认使用 self.confirmed_names_path）
            batch_size: LLM 批处理大小
            show_progress: 是否显示进度条
        
        Returns:
            (CandidateList, ValidationResult): 候选词列表和验证结果
        """
        if output_path is None:
            output_path = self.confirmed_names_path
        
        print(f"[Phase 1] 开始扫描: {input_path}")
        
        # Step 1: 提取候选词
        print("[Step 1/3] 提取候选词...")
        candidates = self.extractor.extract_from_file(
            input_path, 
            show_progress=show_progress
        )
        print(f"  - 扫描消息数: {candidates.total_texts_scanned}")
        print(f"  - 候选词数量: {len(candidates.candidates)}")
        
        if not candidates.candidates:
            print("[WARN] 未提取到任何候选词")
            return candidates, ValidationResult()
        
        # Step 2: LLM 验证
        print("[Step 2/3] LLM 验证候选词...")
        candidate_list = candidates.to_list()
        validation_result = self.validator.validate_batch(
            candidate_list,
            batch_size=batch_size,
            show_progress=show_progress
        )
        
        print(f"  - 真实人名: {len(validation_result.real_names)}")
        print(f"  - 代词/称谓: {len(validation_result.pronouns)}")
        print(f"  - 动物名: {len(validation_result.animal_names)}")
        print(f"  - 常见词: {len(validation_result.common_words)}")
        print(f"  - 待审核: {len(validation_result.uncertain)}")
        
        # Step 3: 生成确认人名列表
        print("[Step 3/3] 生成确认人名列表...")
        confirmed = ConfirmedNames(
            version="1.0",
            generated_at=datetime.now().isoformat(),
            source_file=input_path,
        )
        
        # 添加真实人名
        for name in validation_result.real_names:
            if name in candidates.candidates:
                cw = candidates.candidates[name]
                confirmed.add_name(ConfirmedName(
                    text=name,
                    category="real_name",
                    frequency=cw.frequency,
                    contexts=cw.contexts[:3],
                ))
        
        # 添加待审核
        for name in validation_result.uncertain:
            if name in candidates.candidates:
                cw = candidates.candidates[name]
                confirmed.add_name(ConfirmedName(
                    text=name,
                    category="uncertain",
                    frequency=cw.frequency,
                    contexts=cw.contexts[:3],
                ))
        
        # 保存
        confirmed.save(output_path)
        print(f"[Phase 1] 完成，结果保存到: {output_path}")
        
        # 卸载模型释放显存
        self.validator.unload_model()
        
        return candidates, validation_result
    
    def run_review(self, confirmed_names_path: str = None):
        """
        运行人工审核 CLI
        
        Args:
            confirmed_names_path: 确认人名列表路径
        """
        if confirmed_names_path is None:
            confirmed_names_path = self.confirmed_names_path
        
        confirmed = ConfirmedNames.load(confirmed_names_path)
        
        # 获取待审核列表
        uncertain = [n for n in confirmed.names if n.category == "uncertain"]
        
        if not uncertain:
            print("没有待审核的候选词")
            return
        
        print(f"\n待审核候选词: {len(uncertain)} 个")
        print("=" * 50)
        
        for i, name in enumerate(uncertain, 1):
            print(f"\n[{i}/{len(uncertain)}] {name.text}")
            print(f"  频次: {name.frequency}")
            if name.contexts:
                print("  上下文示例:")
                for ctx in name.contexts[:3]:
                    print(f"    - {ctx[:50]}...")
            
            while True:
                choice = input("  分类 (r=真实人名, p=代词, a=动物, c=常见词, s=跳过): ").strip().lower()
                if choice == 'r':
                    name.category = "real_name"
                    break
                elif choice == 'p':
                    name.category = "pronoun"
                    break
                elif choice == 'a':
                    name.category = "animal"
                    break
                elif choice == 'c':
                    name.category = "common"
                    break
                elif choice == 's':
                    break
                else:
                    print("  无效输入，请重试")
        
        # 保存
        confirmed.save(confirmed_names_path)
        print(f"\n审核完成，结果保存到: {confirmed_names_path}")
    
    def detect(self, text: str) -> List[PIIMatch]:
        """
        检测文本中的 PII（兼容 PIIDetector 接口）
        
        Args:
            text: 输入文本
        
        Returns:
            PIIMatch 列表
        """
        if not text:
            return []
        
        # 确保替换器已加载确认人名
        if not self.replacer.confirmed_names:
            confirmed_path = Path(self.confirmed_names_path)
            if confirmed_path.exists():
                self.replacer.load_confirmed_names(str(confirmed_path))
            else:
                return []
        
        matches: List[PIIMatch] = []
        
        # 查找所有确认人名
        for confirmed in self.replacer.confirmed_names:
            name = confirmed.text
            start = 0
            while True:
                pos = text.find(name, start)
                if pos == -1:
                    break
                
                matches.append(PIIMatch(
                    type="PERSON",
                    value=name,
                    start=pos,
                    end=pos + len(name),
                    confidence=1.0,  # 确认人名，置信度为 1
                    source="two_stage_pii",
                ))
                
                start = pos + 1
        
        # 按位置排序
        matches.sort(key=lambda x: x.start)
        
        return matches
    
    def anonymize(self, text: str) -> str:
        """
        匿名化文本中的人名
        
        Args:
            text: 输入文本
        
        Returns:
            匿名化后的文本
        """
        result, _ = self.replacer.replace_names(text)
        return result
    
    def get_statistics(self) -> Dict:
        """获取统计信息"""
        confirmed_path = Path(self.confirmed_names_path)
        if not confirmed_path.exists():
            return {"status": "not_initialized"}
        
        confirmed = ConfirmedNames.load(str(confirmed_path))
        
        stats = {
            "total_names": len(confirmed.names),
            "by_category": {},
            "source_file": confirmed.source_file,
            "generated_at": confirmed.generated_at,
        }
        
        for name in confirmed.names:
            cat = name.category
            if cat not in stats["by_category"]:
                stats["by_category"][cat] = 0
            stats["by_category"][cat] += 1
        
        return stats


def create_scanner(config_path: str = "configs/compression.yaml") -> TwoStagePIIScanner:
    """
    创建扫描器实例（工厂函数）
    
    Args:
        config_path: 配置文件路径
    
    Returns:
        TwoStagePIIScanner 实例
    """
    return TwoStagePIIScanner(config_path=config_path)
