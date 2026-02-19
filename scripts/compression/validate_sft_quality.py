# -*- coding: utf-8 -*-
"""
SFT 数据质量验证器

验证 agent_sft_l1.jsonl 和 agent_sft_l2.jsonl 的数据质量
检查名字泄露、字段完整性、数据分布等

用法：
    python scripts/compression/validate_sft_quality.py --level l2
    python scripts/compression/validate_sft_quality.py --level l1
    python scripts/compression/validate_sft_quality.py --level all
"""

import argparse
import json
import re
import sys
from pathlib import Path
from collections import Counter
from typing import List, Dict, Tuple, Optional

import yaml


class SFTQualityValidator:
    """SFT 数据质量验证器"""
    
    def __init__(self, anonymization_config_path: str = "configs/anonymization.yaml"):
        """
        初始化验证器
        
        Args:
            anonymization_config_path: 匿名化配置文件路径
        """
        self.anon_config = self._load_config(anonymization_config_path)
        
        # 从配置加载名字列表
        self.me_names = self.anon_config.get('me_names', [])
        self.other_names = self.anon_config.get('other_names', [])
        self.exclude_patterns = self.anon_config.get('exclude_patterns', [])
        
        # 需要检查的文本字段
        self.text_fields = [
            'text_raw', 'image_caption', 'image_ocr_text',
            'video_summary', 'video_voice_to_text',
            'voice_punct_text', 'sticker_caption', 'sticker_ocr_text',
            'link_title', 'quote_text', 'link_quote_text'
        ]
    
    def _load_config(self, config_path: str) -> dict:
        """加载配置文件"""
        path = Path(config_path)
        if not path.exists():
            print(f"[WARN] 配置文件不存在: {config_path}")
            return {}
        with open(path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    
    def _is_real_leak(self, name: str, context: str) -> bool:
        """
        判断是否是真实的名字泄露
        
        排除历史人物等情况（如"李白"包含"李"）
        
        Args:
            name: 检测到的名字
            context: 上下文文本
        
        Returns:
            是否是真实泄露
        """
        for exclude in self.exclude_patterns:
            # 只有当排除模式包含当前名字，且排除模式出现在上下文中时才排除
            if name in exclude and exclude in context:
                return False
        return True
    
    def validate_file(self, file_path: str, level: str) -> Tuple[bool, Dict]:
        """
        验证单个 SFT 文件
        
        Args:
            file_path: 文件路径
            level: 级别 (l1 或 l2)
        
        Returns:
            (是否通过, 详细报告)
        """
        path = Path(file_path)
        if not path.exists():
            return False, {"error": f"文件不存在: {file_path}"}
        
        # 统计
        total_records = 0
        empty_text_count = 0
        type_stats = Counter()
        speaker_stats = Counter()
        name_leaks = []
        
        with open(path, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                if not line.strip():
                    continue
                
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as e:
                    return False, {"error": f"JSON 解析错误 (行 {line_num}): {e}"}
                
                total_records += 1
                
                # 统计类型和说话人
                type_stats[record.get('type', 'unknown')] += 1
                speaker_stats[record.get('speaker', 'unknown')] += 1
                
                # 检查空文本
                text_raw = record.get('text_raw', '')
                if not text_raw or text_raw.strip() == '':
                    empty_text_count += 1
                
                # L2 级别检查名字泄露
                if level == 'l2':
                    for field in self.text_fields:
                        value = record.get(field, '')
                        if not value:
                            continue
                        
                        # 检查 me_names 和 other_names
                        all_names = self.me_names + self.other_names
                        for name in all_names:
                            if name in value:
                                # 获取上下文
                                idx = value.find(name)
                                context_start = max(0, idx - 20)
                                context_end = min(len(value), idx + len(name) + 20)
                                context = value[context_start:context_end]
                                
                                if self._is_real_leak(name, context):
                                    name_leaks.append({
                                        'line': line_num,
                                        'field': field,
                                        'name': name,
                                        'context': context
                                    })
        
        # 构建报告
        report = {
            "file": str(path),
            "level": level,
            "total_records": total_records,
            "empty_text_count": empty_text_count,
            "empty_text_ratio": empty_text_count / total_records if total_records > 0 else 0,
            "type_distribution": dict(type_stats.most_common()),
            "speaker_distribution": dict(speaker_stats.most_common()),
            "name_leaks": name_leaks,
            "name_leak_count": len(name_leaks)
        }
        
        # 判断是否通过
        passed = True
        issues = []
        
        if total_records == 0:
            passed = False
            issues.append("文件为空")
        
        if level == 'l2' and len(name_leaks) > 0:
            passed = False
            issues.append(f"发现 {len(name_leaks)} 处名字泄露")
        
        # 检查 speaker 是否只有 ME/OTHER/SYSTEM
        invalid_speakers = [s for s in speaker_stats.keys() 
                          if s not in ['ME', 'OTHER', 'SYSTEM', '']]
        if level == 'l2' and invalid_speakers:
            passed = False
            issues.append(f"发现非标准 speaker: {invalid_speakers}")
        
        report["passed"] = passed
        report["issues"] = issues
        
        return passed, report
    
    def print_report(self, report: Dict):
        """打印验证报告"""
        print("=" * 70)
        print(f"SFT 数据质量报告: {report.get('file', 'N/A')}")
        print(f"级别: {report.get('level', 'N/A').upper()}")
        print("=" * 70)
        
        if "error" in report:
            print(f"\n❌ 错误: {report['error']}")
            return
        
        print(f"\n📊 基础统计:")
        print(f"  总记录数: {report['total_records']}")
        print(f"  空文本记录: {report['empty_text_count']} ({report['empty_text_ratio']*100:.1f}%)")
        
        print(f"\n📊 消息类型分布:")
        for t, count in list(report['type_distribution'].items())[:10]:
            ratio = count / report['total_records'] * 100
            print(f"  {t}: {count} ({ratio:.1f}%)")
        
        print(f"\n📊 说话人分布:")
        for s, count in report['speaker_distribution'].items():
            ratio = count / report['total_records'] * 100
            print(f"  {s}: {count} ({ratio:.1f}%)")
        
        if report['level'] == 'l2':
            print(f"\n🔒 隐私检查:")
            print(f"  检查的名字: {self.me_names + self.other_names}")
            print(f"  名字泄露数: {report['name_leak_count']}")
            
            if report['name_leaks']:
                print("\n  泄露详情:")
                for leak in report['name_leaks'][:10]:
                    print(f"    行 {leak['line']}: [{leak['field']}] '{leak['name']}' in '{leak['context']}'")
                if len(report['name_leaks']) > 10:
                    print(f"    ... 还有 {len(report['name_leaks']) - 10} 处")
        
        print("\n" + "=" * 70)
        if report['passed']:
            print("✅ 质量检查通过！")
        else:
            print("❌ 质量检查失败！")
            print("问题:")
            for issue in report['issues']:
                print(f"  - {issue}")
        print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description='SFT 数据质量验证器')
    parser.add_argument('--level', choices=['l1', 'l2', 'all'], default='all',
                       help='验证级别 (l1, l2, all)')
    parser.add_argument('--input-dir', default='timeline_out',
                       help='输入目录')
    parser.add_argument('--config', default='configs/anonymization.yaml',
                       help='匿名化配置文件路径')
    parser.add_argument('--strict', action='store_true',
                       help='严格模式：任何问题都返回非零退出码')
    
    args = parser.parse_args()
    
    validator = SFTQualityValidator(args.config)
    
    files_to_check = []
    if args.level in ['l1', 'all']:
        files_to_check.append((f"{args.input_dir}/agent_sft_l1.jsonl", 'l1'))
    if args.level in ['l2', 'all']:
        files_to_check.append((f"{args.input_dir}/agent_sft_l2.jsonl", 'l2'))
    
    all_passed = True
    
    for file_path, level in files_to_check:
        if not Path(file_path).exists():
            print(f"[SKIP] 文件不存在: {file_path}")
            continue
        
        passed, report = validator.validate_file(file_path, level)
        validator.print_report(report)
        
        if not passed:
            all_passed = False
        
        print()
    
    # 返回退出码
    if args.strict and not all_passed:
        sys.exit(1)
    elif not all_passed:
        # 非严格模式下，只有名字泄露才返回非零
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == '__main__':
    main()
