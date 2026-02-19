# -*- coding: utf-8 -*-
"""
时间轴级别匿名化脚本

说明：
    - L1（本地训练）：不需要匿名化，直接使用原始数据
    - L2（云端训练）：需要完整匿名化（名字替换、地名映射、时间偏移）

输入：timeline_out/enriched_full.jsonl
输出：
  - L2: timeline_out/enriched_full_anonymized_l2.jsonl

用法：
    # L2 匿名化（云端训练）- 推荐使用两阶段 PII
    python scripts/timeline/run_anonymization.py --level l2 --two-stage-pii
    
    # L2 匿名化（不使用两阶段 PII，仅规则引擎）
    python scripts/timeline/run_anonymization.py --level l2
    
    # 同时生成 L1 和 L2（L1 仅做字段精简，不匿名化）
    python scripts/timeline/run_anonymization.py --level both
    
    # 仅 L1（不推荐，L1 不需要匿名化）
    python scripts/timeline/run_anonymization.py --level l1

两阶段 PII 检测：
    1. 先运行 `python scripts/compression/two_stage_pii.py scan` 生成确认人名列表
    2. 人工审核 `python scripts/compression/two_stage_pii.py review`
    3. 运行匿名化时添加 --two-stage-pii 参数
"""

import argparse
import json
from pathlib import Path
from tqdm import tqdm
import sys

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.compression.privacy_shield import PrivacyShield


def load_timeline(input_path: str):
    """加载时间轴数据"""
    messages = []
    with open(input_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                messages.append(json.loads(line))
    return messages


def save_timeline(messages, output_path: str):
    """保存时间轴数据"""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        for msg in messages:
            f.write(json.dumps(msg, ensure_ascii=False) + '\n')


def run_anonymization(input_path: str, output_path: str, level: str = 'L1',
                      use_two_stage_pii: bool = False):
    """
    运行匿名化
    
    Args:
        input_path: 输入文件路径
        output_path: 输出文件路径
        level: 匿名化级别 ('L1' 或 'L2')
        use_two_stage_pii: 是否使用两阶段 PII 检测
    """
    print(f"[INFO] 开始 {level} 匿名化")
    print(f"[INFO] 输入: {input_path}")
    print(f"[INFO] 输出: {output_path}")
    if use_two_stage_pii:
        print(f"[INFO] 使用两阶段 PII 检测")
    
    # 检查输入文件
    if not Path(input_path).exists():
        print(f"[ERROR] 输入文件不存在: {input_path}")
        return
    
    # 检查两阶段 PII 配置
    confirmed_names_path = "configs/confirmed_names.yaml"
    if use_two_stage_pii and not Path(confirmed_names_path).exists():
        print(f"[ERROR] 确认人名列表不存在: {confirmed_names_path}")
        print(f"[INFO] 请先运行 'python scripts/compression/two_stage_pii.py scan' 生成")
        return
    
    # 加载数据
    messages = load_timeline(input_path)
    print(f"[INFO] 加载 {len(messages)} 条消息")
    
    # 创建隐私保护层
    shield = PrivacyShield(
        use_two_stage_pii=use_two_stage_pii,
        confirmed_names_path=confirmed_names_path,
    )
    
    # L2 模式：设置基准时间戳（第一条消息的时间）
    if level == 'L2' and messages:
        # 找到第一条消息的时间戳
        first_ts = None
        for msg in messages:
            if 'ts' in msg:
                first_ts = msg['ts']
                break
        
        if first_ts:
            shield.set_base_timestamp(first_ts)
            print(f"[INFO] L2 模式：设置基准时间戳 {first_ts}")
            print(f"[INFO] L2 模式：时间偏移 {shield.shield_config.shift_days} 天")
    
    # 匿名化
    anonymized = []
    for msg in tqdm(messages, desc=f"{level} 匿名化"):
        if level == 'L1':
            result = shield.anonymize_l1(msg)
        else:  # L2
            result = shield.anonymize_l2(msg)
        anonymized.append(result)
    
    # 保存结果
    save_timeline(anonymized, output_path)
    
    # 打印统计
    stats = shield.get_stats()
    print(f"\n[INFO] 匿名化完成")
    print(f"  处理消息: {stats['total_processed']}")
    print(f"  检测 PII: {stats['pii_detected']}")
    print(f"  替换名字: {stats['names_replaced']}")
    print(f"  替换电话: {stats['phones_replaced']}")
    print(f"  替换邮箱: {stats['emails_replaced']}")
    if use_two_stage_pii:
        print(f"  两阶段检测: {stats.get('two_stage_detections', 0)}")
    if level == 'L2':
        print(f"  替换地名: {stats.get('locations_replaced', 0)}")
        print(f"  时间泛化: {stats['timestamps_generalized']}")
        print(f"  时间偏移: {stats['timestamps_shifted']}")
    
    print(f"\n[INFO] 输出已保存到: {output_path}")
    
    # 释放模型资源
    shield.unload_models()
    print("[INFO] 模型资源已释放")


def main():
    parser = argparse.ArgumentParser(description='时间轴匿名化（L1 → L2 转换）')
    parser.add_argument('--level', '-l', type=str, 
                        choices=['l1', 'l2', 'both', 'L1', 'L2'],
                        default='l2', help='匿名化级别（推荐使用 l2）')
    parser.add_argument('--input', '-i', type=str,
                        default='timeline_out/enriched_full.jsonl',
                        help='输入文件路径')
    parser.add_argument('--output-dir', '-o', type=str,
                        default='timeline_out',
                        help='输出目录')
    parser.add_argument('--two-stage-pii', '-t', action='store_true',
                        help='使用两阶段 PII 检测（推荐）')
    
    args = parser.parse_args()
    
    # 统一转为小写
    level = args.level.lower()
    
    if level == 'l1':
        print("[WARN] L1 不需要匿名化，建议直接使用 sft_trimmer.py --l1")
        print("[INFO] 如果确实需要，将生成一个不做任何匿名化的副本")
        # L1 实际上不做匿名化，只是复制
        run_anonymization(
            args.input,
            f"{args.output_dir}/enriched_full_anonymized_l1.jsonl",
            'L1',
            use_two_stage_pii=args.two_stage_pii,
        )
    elif level == 'l2':
        # 只运行 L2 匿名化
        run_anonymization(
            args.input,
            f"{args.output_dir}/enriched_full_anonymized_l2.jsonl",
            'L2',
            use_two_stage_pii=args.two_stage_pii,
        )
    elif level == 'both':
        print("[INFO] 生成 L1 和 L2 两种数据")
        print("[INFO] L1: 不匿名化（仅复制）")
        print("[INFO] L2: 完整匿名化")
        # L1: 不匿名化，只是复制
        run_anonymization(
            args.input,
            f"{args.output_dir}/enriched_full_anonymized_l1.jsonl",
            'L1',
            use_two_stage_pii=args.two_stage_pii,
        )
        # L2: 完整匿名化
        run_anonymization(
            args.input,
            f"{args.output_dir}/enriched_full_anonymized_l2.jsonl",
            'L2',
            use_two_stage_pii=args.two_stage_pii,
        )


if __name__ == '__main__':
    main()
