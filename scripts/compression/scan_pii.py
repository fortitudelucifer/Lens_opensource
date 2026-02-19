#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PII 扫描脚本

扫描时间轴数据，检测并报告 PII（个人身份信息）
支持自动建议需要添加到配置的实体

用法：
    # 扫描时间轴数据
    python scripts/compression/scan_pii.py
    
    # 扫描并建议新实体
    python scripts/compression/scan_pii.py --suggest
    
    # 指定输入文件
    python scripts/compression/scan_pii.py --input timeline_out/enriched_full.jsonl
    
    # 输出到指定文件
    python scripts/compression/scan_pii.py --output artifacts/my_pii_report.yaml
"""

import argparse
import json
import yaml
from pathlib import Path
from typing import Dict, List, Set, Optional
from collections import defaultdict
from datetime import datetime
from tqdm import tqdm

# 添加项目根目录到路径
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.compression.pii_detector import PIIDetector, PIIMatch


class PIIScanner:
    """PII 扫描器"""
    
    def __init__(self, config_path: str = "configs/compression.yaml",
                 anonymization_config_path: str = "configs/anonymization.yaml"):
        self.detector = PIIDetector(config_path, anonymization_config_path)
        self.anon_config_path = anonymization_config_path
        
        # 加载现有配置
        self.existing_config = self._load_config(anonymization_config_path)
        
        # 扫描结果
        self.results = {
            "scan_time": datetime.now().isoformat(),
            "total_messages": 0,
            "messages_with_pii": 0,
            "pii_by_type": defaultdict(list),
            "pii_by_source": defaultdict(int),
            "unique_entities": defaultdict(set),
            "suggestions": {
                "new_persons": [],
                "new_locations": [],
                "new_organizations": []
            }
        }
    
    def _load_config(self, config_path: str) -> dict:
        """加载配置文件"""
        path = Path(config_path)
        if not path.exists():
            return {}
        with open(path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    
    def scan_file(self, input_path: str, text_fields: Optional[List[str]] = None) -> Dict:
        """
        扫描 JSONL 文件中的 PII
        
        Args:
            input_path: 输入文件路径
            text_fields: 要扫描的文本字段列表
        
        Returns:
            扫描结果
        """
        if text_fields is None:
            text_fields = [
                'text_raw', 'text', 'punct_text',
                'image_summary', 'image_caption', 'image_ocr_text',
                'video_summary', 'video_voice_to_text',
                'voice_to_text',
                'sticker_summary', 'sticker_caption', 'sticker_intent', 'sticker_ocr_text',
                'quote_text', 'link_quote_text',
                'gap_description'
            ]
        
        input_file = Path(input_path)
        if not input_file.exists():
            print(f"[ERROR] 文件不存在: {input_path}")
            return self.results
        
        # 统计行数
        with open(input_file, 'r', encoding='utf-8') as f:
            total_lines = sum(1 for _ in f)
        
        print(f"[INFO] 扫描文件: {input_path}")
        print(f"[INFO] 总消息数: {total_lines}")
        
        with open(input_file, 'r', encoding='utf-8') as f:
            for line in tqdm(f, total=total_lines, desc="扫描 PII"):
                try:
                    message = json.loads(line.strip())
                    self._scan_message(message, text_fields)
                except json.JSONDecodeError:
                    continue
        
        # 转换 set 为 list（用于 YAML 序列化）
        for pii_type in self.results["unique_entities"]:
            self.results["unique_entities"][pii_type] = list(self.results["unique_entities"][pii_type])
        
        # 生成建议
        self._generate_suggestions()
        
        return self.results
    
    def _scan_message(self, message: Dict, text_fields: List[str]):
        """扫描单条消息"""
        self.results["total_messages"] += 1
        
        msg_uid = message.get('msg_uid', 'unknown')
        has_pii = False
        
        for field in text_fields:
            if field not in message or not message[field]:
                continue
            
            text = str(message[field])
            matches = self.detector.detect(text)
            
            if matches:
                has_pii = True
                
                for match in matches:
                    # 记录 PII
                    self.results["pii_by_type"][match.type].append({
                        "msg_uid": msg_uid,
                        "field": field,
                        "value": match.value,
                        "confidence": match.confidence,
                        "source": match.source
                    })
                    
                    self.results["pii_by_source"][match.source] += 1
                    self.results["unique_entities"][match.type].add(match.value)
        
        if has_pii:
            self.results["messages_with_pii"] += 1
    
    def _generate_suggestions(self):
        """生成配置建议"""
        # 获取现有配置中的实体
        existing_persons = set(self.existing_config.get('me_names', []))
        existing_persons.update(self.existing_config.get('other_names', []))
        existing_locations = set(self.existing_config.get('location_mapping', {}).keys())
        
        # 找出新发现的实体
        for entity in self.results["unique_entities"].get("PERSON", []):
            if entity not in existing_persons:
                self.results["suggestions"]["new_persons"].append(entity)
        
        for entity in self.results["unique_entities"].get("LOCATION", []):
            if entity not in existing_locations:
                self.results["suggestions"]["new_locations"].append(entity)
        
        for entity in self.results["unique_entities"].get("ORG", []):
            self.results["suggestions"]["new_organizations"].append(entity)
    
    def save_report(self, output_path: str):
        """保存扫描报告"""
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        # 准备输出数据
        report = {
            "scan_info": {
                "scan_time": self.results["scan_time"],
                "total_messages": self.results["total_messages"],
                "messages_with_pii": self.results["messages_with_pii"],
                "pii_rate": f"{self.results['messages_with_pii'] / max(1, self.results['total_messages']) * 100:.2f}%"
            },
            "detection_sources": dict(self.results["pii_by_source"]),
            "unique_entities": dict(self.results["unique_entities"]),
            "suggestions": self.results["suggestions"],
            "detailed_findings": {
                pii_type: findings[:50]  # 只保留前 50 条
                for pii_type, findings in self.results["pii_by_type"].items()
            }
        }
        
        with open(output_file, 'w', encoding='utf-8') as f:
            yaml.dump(report, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        
        print(f"[INFO] 报告已保存: {output_path}")
    
    def print_summary(self):
        """打印扫描摘要"""
        print("\n" + "=" * 60)
        print("PII 扫描摘要")
        print("=" * 60)
        
        print(f"\n总消息数: {self.results['total_messages']}")
        print(f"包含 PII 的消息: {self.results['messages_with_pii']}")
        pii_rate = self.results['messages_with_pii'] / max(1, self.results['total_messages']) * 100
        print(f"PII 检出率: {pii_rate:.2f}%")
        
        print("\n检测来源统计:")
        for source, count in self.results["pii_by_source"].items():
            print(f"  {source}: {count}")
        
        print("\n唯一实体统计:")
        for pii_type, entities in self.results["unique_entities"].items():
            entity_list = list(entities) if isinstance(entities, set) else entities
            print(f"  {pii_type}: {len(entity_list)} 个")
            if entity_list:
                preview = entity_list[:5]
                print(f"    示例: {', '.join(preview)}")
        
        # 打印建议
        if any(self.results["suggestions"].values()):
            print("\n" + "-" * 40)
            print("配置建议（新发现的实体）:")
            
            if self.results["suggestions"]["new_persons"]:
                print(f"\n  新人名 ({len(self.results['suggestions']['new_persons'])} 个):")
                for person in self.results["suggestions"]["new_persons"][:10]:
                    print(f"    - {person}")
            
            if self.results["suggestions"]["new_locations"]:
                print(f"\n  新地名 ({len(self.results['suggestions']['new_locations'])} 个):")
                for loc in self.results["suggestions"]["new_locations"][:10]:
                    print(f"    - {loc}")
            
            if self.results["suggestions"]["new_organizations"]:
                print(f"\n  新组织 ({len(self.results['suggestions']['new_organizations'])} 个):")
                for org in self.results["suggestions"]["new_organizations"][:10]:
                    print(f"    - {org}")
    
    def unload(self):
        """卸载模型"""
        self.detector.unload_models()


def main():
    parser = argparse.ArgumentParser(description="PII 扫描脚本")
    parser.add_argument(
        "--input", "-i",
        default="timeline_out/enriched_full.jsonl",
        help="输入文件路径（默认: timeline_out/enriched_full.jsonl）"
    )
    parser.add_argument(
        "--output", "-o",
        default="artifacts/detected_pii.yaml",
        help="输出报告路径（默认: artifacts/detected_pii.yaml）"
    )
    parser.add_argument(
        "--suggest",
        action="store_true",
        help="生成配置建议"
    )
    parser.add_argument(
        "--no-gliner",
        action="store_true",
        help="禁用 GLiNER 检测（仅使用规则引擎）"
    )
    
    args = parser.parse_args()
    
    # 创建扫描器
    scanner = PIIScanner()
    
    # 如果禁用 GLiNER
    if args.no_gliner:
        scanner.detector.gliner_enabled = False
    
    try:
        # 扫描文件
        scanner.scan_file(args.input)
        
        # 打印摘要
        scanner.print_summary()
        
        # 保存报告
        scanner.save_report(args.output)
        
        # 如果需要建议
        if args.suggest:
            print("\n" + "=" * 60)
            print("建议添加到 configs/anonymization.yaml 的实体:")
            print("=" * 60)
            
            suggestions = scanner.results["suggestions"]
            
            if suggestions["new_persons"]:
                print("\n# 添加到 other_names:")
                print("other_names:")
                for person in suggestions["new_persons"]:
                    print(f"  - \"{person}\"")
            
            if suggestions["new_locations"]:
                print("\n# 添加到 location_mapping:")
                print("location_mapping:")
                for loc in suggestions["new_locations"]:
                    print(f"  \"{loc}\": \"[地点]\"")
    
    finally:
        # 卸载模型
        scanner.unload()


if __name__ == '__main__':
    main()
