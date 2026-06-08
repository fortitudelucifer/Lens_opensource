# -*- coding: utf-8 -*-
"""
两阶段 PII 匿名化系统

Phase 1: 离线扫描 - 正则预过滤 + LLM 批量验证，生成确认人名列表
Phase 2: 精确替换 - 基于确认列表做精确字符串匹配

用法:
    # Phase 1: 扫描生成人名列表
    python scripts/compression/two_stage_pii.py scan timeline_out/agent_sft_l1.jsonl
    
    # 人工审核
    python scripts/compression/two_stage_pii.py review
    
    # Phase 2: 在匿名化时自动使用精确匹配
    from scripts.compression.two_stage_pii import TwoStagePIIScanner
    scanner = TwoStagePIIScanner()
    matches = scanner.detect("张三说...")
    anonymized = scanner.anonymize("张三说...")
"""

from .models import CandidateWord, CandidateList, ValidationResult, ConfirmedNames, ConfirmedName

__all__ = [
    'CandidateWord',
    'CandidateList', 
    'ValidationResult',
    'ConfirmedNames',
    'ConfirmedName',
    'CandidateExtractor',
    'NameReplacer',
    'LLMValidator',
    'TwoStagePIIScanner',
]

# 延迟导入其他组件（避免循环依赖）
def __getattr__(name):
    if name == 'CandidateExtractor':
        from .candidate_extractor import CandidateExtractor
        return CandidateExtractor
    elif name == 'NameReplacer':
        from .name_replacer import NameReplacer
        return NameReplacer
    elif name == 'LLMValidator':
        from .llm_validator import LLMValidator
        return LLMValidator
    elif name == 'TwoStagePIIScanner':
        from .scanner import TwoStagePIIScanner
        return TwoStagePIIScanner
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
