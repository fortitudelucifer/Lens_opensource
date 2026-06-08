# -*- coding: utf-8 -*-
"""
PII 检测器 - 纯规则引擎架构

功能：
- 规则引擎 PII 检测（正则 + 配置映射）
- 支持多种 PII 类型（电话、邮箱、身份证、微信ID、日期等）
- 已知实体检测（人名、地名从配置加载）
- 置信度评分（1.0，规则匹配）
- 排除列表支持（公众人物、历史人物等）

架构演进：
- 原 Layer 2 GLiNER 零样本 NER 已废弃（2026-02-06）
  - 原因：中文误检率高，需要大量排除列表维护
  - 替代方案：两阶段 PII 检测系统（scripts/compression/two_stage_pii.py）
- 原 Layer 3 LLM 兜底已废弃（2026-02-05）
  - 替代方案：两阶段 PII 检测系统

当前架构：
Layer 1: 规则引擎（正则 + 配置映射）
  - 正则规则：电话、邮箱、身份证、微信ID、日期等
  - 配置映射：从 anonymization.yaml 加载已知实体（人名、地名）
  - 优点：快速、确定性、置信度 1.0、无显存占用
  - 缺点：无法识别未知实体（由两阶段 PII 系统补充）

推荐工作流：
1. 新数据集：先运行 `python scripts/compression/two_stage_pii.py scan` 生成确认人名列表
2. 匿名化：使用 PrivacyShield 配合两阶段 PII 检测进行匿名化

输入：
- text: 待检测文本
- configs/compression.yaml: 配置
- configs/anonymization.yaml: 已知实体和排除列表

输出：
- List[PIIMatch]: 检测到的 PII 列表
  - type: PII 类型（PERSON, PHONE, EMAIL, LOCATION, ID_CARD, WECHAT_ID, DATE）
  - value: 原始值
  - start/end: 位置
  - confidence: 置信度（1.0）
  - source: 检测来源（regex, config）

依赖：
- yaml: 配置解析
- re: 正则表达式

使用示例：
    from scripts.compression.pii_detector import PIIDetector
    
    detector = PIIDetector()
    matches = detector.detect("张三的电话是13812345678，邮箱是test@example.com")
    
    for match in matches:
        print(f"[{match.source}] {match.type}: '{match.value}' "
              f"(位置: {match.start}-{match.end}, 置信度: {match.confidence:.2f})")
    
    # 输出：
    # [config] PERSON: '张三' (位置: 0-2, 置信度: 1.00)
    # [regex] PHONE: '13812345678' (位置: 6-17, 置信度: 1.00)
    # [regex] EMAIL: 'test@example.com' (位置: 21-37, 置信度: 1.00)

作者：[Author]
更新于：2026-02-06
"""

import re
from pathlib import Path
from typing import Dict, List, Tuple
from dataclasses import dataclass
import yaml


@dataclass
class PIIMatch:
    """PII 匹配结果"""
    type: str           # 类型：PERSON, PHONE, EMAIL, LOCATION, ID_CARD, WECHAT_ID, DATE
    value: str          # 原始值
    start: int          # 起始位置
    end: int            # 结束位置
    confidence: float   # 置信度 0.0-1.0
    source: str         # 检测来源：regex, config


class PIIDetector:
    """
    PII 检测器：纯规则引擎
    
    注意：人名检测建议使用两阶段 PII 检测系统
    详见 scripts/compression/two_stage_pii.py
    """
    
    def __init__(self, config_path: str = "configs/compression.yaml",
                 anonymization_config_path: str = "configs/anonymization.yaml"):
        self.config = self._load_config(config_path)
        self.anon_config = self._load_config(anonymization_config_path)
        
        # 正则规则
        self.regex_rules = self._load_regex_rules()
        
        # 已知实体（从配置加载）
        self.known_entities = self._load_known_entities()
        
        # 排除列表（公众人物、历史人物等）
        self.exclude_list = set(self.anon_config.get('exclude_patterns', []))
        
        # 统计
        self.stats = {
            "total_detections": 0,
            "regex_detections": 0,
            "config_detections": 0,
        }
    
    def _load_config(self, config_path: str) -> dict:
        """加载配置文件"""
        path = Path(config_path)
        if not path.exists():
            return {}
        with open(path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    
    def _load_regex_rules(self) -> List[Tuple[str, str, str]]:
        """
        加载正则规则
        
        Returns:
            List of (pattern, pii_type, description)
        """
        anon_cfg = self.config.get('anonymization', {})
        l2_cfg = anon_cfg.get('l2', {})
        patterns = l2_cfg.get('pii_patterns', {})
        
        rules = []
        
        # 默认规则
        default_rules = [
            (r'1[3-9]\d{9}', 'PHONE', '中国手机号'),
            (r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', 'EMAIL', '邮箱'),
            (r'\d{17}[\dXx]', 'ID_CARD', '身份证号'),
            (r'wxid_[a-zA-Z0-9]+', 'WECHAT_ID', '微信ID'),
            (r'\d{3,4}[-\s]?\d{7,8}', 'PHONE', '固定电话'),
            (r'(?:19|20)\d{2}[-/年]\d{1,2}[-/月]\d{1,2}[日号]?', 'DATE', '日期'),
        ]
        
        # 从配置加载
        for pii_type, pattern in patterns.items():
            rules.append((pattern, pii_type.upper(), f'配置: {pii_type}'))
        
        # 添加默认规则（如果配置中没有）
        existing_types = {r[1] for r in rules}
        for pattern, pii_type, desc in default_rules:
            if pii_type not in existing_types:
                rules.append((pattern, pii_type, desc))
        
        return rules

    def _load_known_entities(self) -> Dict[str, List[str]]:
        """
        从配置加载已知实体
        
        Returns:
            {entity_type: [entity_values]}
        """
        entities = {
            'PERSON': [],
            'LOCATION': []
        }
        
        # 加载人名
        me_names = self.anon_config.get('me_names', [])
        other_names = self.anon_config.get('other_names', [])
        entities['PERSON'].extend(me_names)
        entities['PERSON'].extend(other_names)
        
        # 加载地名
        location_mapping = self.anon_config.get('location_mapping', {})
        entities['LOCATION'].extend(location_mapping.keys())
        
        return entities

    def detect(self, text: str) -> List[PIIMatch]:
        """
        规则引擎检测 PII
        
        Args:
            text: 输入文本
        
        Returns:
            List[PIIMatch]: 检测到的 PII 列表
        """
        if not text or not text.strip():
            return []
        
        results = []
        
        # 正则规则检测
        regex_matches = self._detect_by_regex(text)
        results.extend(regex_matches)
        
        # 配置映射检测
        config_matches = self._detect_by_config(text)
        results.extend(config_matches)
        
        # 去重和合并
        results = self._deduplicate_and_merge(results)
        
        self.stats["total_detections"] += len(results)
        
        return results
    
    def _detect_by_regex(self, text: str) -> List[PIIMatch]:
        """正则规则检测"""
        matches = []
        
        for pattern, pii_type, desc in self.regex_rules:
            try:
                for match in re.finditer(pattern, text):
                    # 检查是否在排除列表中
                    if match.group() in self.exclude_list:
                        continue
                    
                    matches.append(PIIMatch(
                        type=pii_type,
                        value=match.group(),
                        start=match.start(),
                        end=match.end(),
                        confidence=1.0,
                        source='regex'
                    ))
                    self.stats["regex_detections"] += 1
            except re.error as e:
                print(f"[WARN] 正则表达式错误 ({pattern}): {e}")
        
        return matches
    
    def _detect_by_config(self, text: str) -> List[PIIMatch]:
        """配置映射检测"""
        matches = []
        
        for entity_type, entities in self.known_entities.items():
            for entity in entities:
                if not entity:
                    continue
                
                # 使用 re.escape 处理特殊字符
                pattern = re.escape(entity)
                
                for match in re.finditer(pattern, text):
                    # 检查是否在排除列表中
                    if entity in self.exclude_list:
                        continue
                    
                    matches.append(PIIMatch(
                        type=entity_type,
                        value=match.group(),
                        start=match.start(),
                        end=match.end(),
                        confidence=1.0,
                        source='config'
                    ))
                    self.stats["config_detections"] += 1
        
        return matches

    def _deduplicate_and_merge(self, matches: List[PIIMatch]) -> List[PIIMatch]:
        """
        去重和合并匹配结果
        
        规则：
        1. 完全重叠的匹配，保留置信度更高的
        2. 部分重叠的匹配，保留更长的
        """
        if not matches:
            return []
        
        # 按起始位置排序
        matches.sort(key=lambda x: (x.start, -x.end, -x.confidence))
        
        result = []
        
        for match in matches:
            # 检查是否与已有结果重叠
            is_duplicate = False
            
            for i, existing in enumerate(result):
                # 完全重叠
                if match.start == existing.start and match.end == existing.end:
                    # 保留置信度更高的
                    if match.confidence > existing.confidence:
                        result[i] = match
                    is_duplicate = True
                    break
                
                # 部分重叠
                if not (match.end <= existing.start or match.start >= existing.end):
                    # 保留更长的
                    if (match.end - match.start) > (existing.end - existing.start):
                        result[i] = match
                    is_duplicate = True
                    break
            
            if not is_duplicate:
                result.append(match)
        
        # 按位置排序
        result.sort(key=lambda x: x.start)
        
        return result
    
    def unload_models(self):
        """卸载模型，释放显存（保留接口兼容性，实际无操作）"""
        pass
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        return self.stats.copy()


def main():
    """测试 PII 检测器"""
    print("=" * 60)
    print("PII 检测器测试（纯规则引擎）")
    print("=" * 60)
    
    detector = PIIDetector()
    
    # 测试用例
    test_cases = [
        "我的电话是13812345678，邮箱是test@example.com",
        "微信号是wxid_abc123xyz，身份证号是110101199001011234",
        "2025年7月14日，我们在深圳南山区开会",
    ]
    
    for i, text in enumerate(test_cases, 1):
        print(f"\n测试 {i}: {text}")
        print("-" * 40)
        
        matches = detector.detect(text)
        
        if matches:
            for match in matches:
                print(f"  [{match.source}] {match.type}: '{match.value}' "
                      f"(位置: {match.start}-{match.end}, 置信度: {match.confidence:.2f})")
        else:
            print("  未检测到 PII")
    
    print("\n" + "=" * 60)
    print("统计信息:")
    print(detector.get_stats())
    
    print("\n提示：人名检测建议使用两阶段 PII 检测系统")
    print("运行: python scripts/compression/two_stage_pii.py scan")


if __name__ == '__main__':
    main()
