#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
时间轴后处理脚本

在 enriched_full.jsonl 生成后执行：
1. 连续消息合并（情绪感知）
2. 时间流逝标记插入
3. 对话中断类型标记

用法：
    python scripts/timeline/run_postprocess.py
    python scripts/timeline/run_postprocess.py --skip-merge
    python scripts/timeline/run_postprocess.py --skip-time-gap
    python scripts/timeline/run_postprocess.py --dry-run
"""

import argparse
import sys
from pathlib import Path
from tqdm import tqdm

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from scripts.timeline.timeline_postprocessor import (
    TimelinePostprocessor, 
    load_timeline, 
    save_timeline
)


def parse_args():
    parser = argparse.ArgumentParser(
        description='时间轴后处理：消息合并和时间标记插入'
    )
    parser.add_argument(
        '--input', '-i',
        default='timeline_out/enriched_full.jsonl',
        help='输入文件路径 (默认: timeline_out/enriched_full.jsonl)'
    )
    parser.add_argument(
        '--output', '-o',
        default='timeline_out/enriched_full_processed.jsonl',
        help='输出文件路径 (默认: timeline_out/enriched_full_processed.jsonl)'
    )
    parser.add_argument(
        '--config', '-c',
        default='configs/compression.yaml',
        help='配置文件路径 (默认: configs/compression.yaml)'
    )
    parser.add_argument(
        '--skip-merge',
        action='store_true',
        help='跳过消息合并'
    )
    parser.add_argument(
        '--skip-time-gap',
        action='store_true',
        help='跳过时间流逝标记插入'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='只显示统计信息，不保存结果'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='显示详细信息'
    )
    return parser.parse_args()


def main():
    args = parse_args()
    
    print("=" * 60)
    print("时间轴后处理")
    print("=" * 60)
    
    # 检查输入文件
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"[ERROR] 输入文件不存在: {input_path}")
        sys.exit(1)
    
    # 加载配置
    print(f"\n[1/4] 加载配置: {args.config}")
    processor = TimelinePostprocessor(args.config)
    
    # 根据参数调整配置
    if args.skip_merge:
        processor.merge_config.enabled = False
        print("  - 跳过消息合并")
    if args.skip_time_gap:
        processor.time_gap_config.enabled = False
        print("  - 跳过时间流逝标记")
    
    # 加载时间轴
    print(f"\n[2/4] 加载时间轴: {input_path}")
    messages = load_timeline(str(input_path))
    print(f"  - 加载了 {len(messages)} 条消息")
    
    # 处理
    print(f"\n[3/4] 处理中...")
    with tqdm(total=1, desc="后处理") as pbar:
        result = processor.process(messages)
        pbar.update(1)
    
    # 显示统计信息
    stats = processor.get_stats()
    print(f"\n[4/4] 处理完成")
    print(f"\n统计信息:")
    print(f"  - 原始消息数: {stats['total_messages']}")
    print(f"  - 处理后消息数: {len(result)}")
    print(f"  - 合并组数: {stats['merged_groups']}")
    print(f"  - 被合并消息数: {stats['messages_merged']}")
    print(f"  - 插入时间标记数: {stats['time_gaps_inserted']}")
    print(f"\n对话中断类型分布:")
    for break_type, count in stats['break_types'].items():
        if count > 0:
            print(f"  - {break_type}: {count}")
    
    # 保存结果
    if not args.dry_run:
        output_path = Path(args.output)
        print(f"\n保存结果到: {output_path}")
        save_timeline(result, str(output_path))
        print("完成!")
    else:
        print("\n[DRY-RUN] 未保存结果")
    
    # 显示示例
    if args.verbose:
        print("\n" + "=" * 60)
        print("示例输出（前5条）:")
        print("=" * 60)
        for i, msg in enumerate(result[:5]):
            print(f"\n--- 消息 {i+1} ---")
            print(f"  speaker: {msg.get('speaker')}")
            print(f"  modality: {msg.get('modality')}")
            print(f"  text_raw: {msg.get('text_raw', '')[:100]}...")
            if msg.get('merged_count'):
                print(f"  merged_count: {msg.get('merged_count')}")
            if msg.get('break_type'):
                print(f"  break_type: {msg.get('break_type')}")


if __name__ == '__main__':
    main()
