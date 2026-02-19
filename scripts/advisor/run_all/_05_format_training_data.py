#!/usr/bin/env python3
"""
训练数据格式化脚本

功能：
- 将审核后的分析结果或 MoA 融合数据转换为 SFT 训练格式
- 支持多种数据来源（MoA 融合/审核后/原始分析）
- 支持 JSONL 和 Alpaca 两种输出格式
- 自动剥离冗余字段（DeepSeek_raw/GLM_raw 等），减小训练数据体积

处理流程：
1. 自动检测或指定数据来源（MoA > reviewed > raw）
2. 加载分析结果样本
3. 可选：剥离冗余字段（DeepSeek_raw, GLM_raw, step_details 等）
4. 使用 TrainingFormatter 转换为 SFT 训练格式
5. 输出训练数据 JSONL 并展示样本示例

数据来源优先级：
- moa: MoA 融合数据（fused_analysis_*_moa.jsonl）— 推荐
- reviewed: 人工审核后的数据（reviewed_analysis_*.jsonl）
- raw: 原始 LLM 分析数据（raw_analysis_*.jsonl）

输入：
- advisor_out/analysis/fused_analysis_{agent_type}_moa.jsonl: MoA 融合数据（推荐）
- advisor_out/analysis/reviewed_analysis_{agent_type}.jsonl: 审核后数据
- advisor_out/analysis/raw_analysis_{agent_type}.jsonl: 原始分析数据

输出：
- advisor_out/training/advisor_training_{agent_type}.jsonl: SFT 训练数据
  * JSONL 格式：每行一个 {"messages": [...]} 对象
  * Alpaca 格式：每行一个 {"instruction": ..., "input": ..., "output": ...} 对象

依赖：
- scripts/advisor/formatter.py: TrainingFormatter 格式化器

使用示例：
    # 从 MoA 融合数据生成训练数据（推荐）
    python scripts/advisor/run_all/_05_format_training_data.py --agent-type neutral --source moa

    # 从审核后的数据生成
    python scripts/advisor/run_all/_05_format_training_data.py --source reviewed

    # 使用 Alpaca 格式，只导出已审核样本
    python scripts/advisor/run_all/_05_format_training_data.py --format alpaca --only-reviewed

注意事项：
- 建议优先使用 MoA 融合数据，质量最高
- --strip-raw 默认开启，会移除 DeepSeek_raw/GLM_raw 等冗余字段
- 生成的训练数据将作为 _05b_filter_split_training.py 的输入
- 确保先完成分析生成和审核流程

作者：forcifer
更新于：2026-02-15
"""

import argparse
import json
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.advisor.formatter import TrainingFormatter


def load_samples(input_path: str) -> list[dict]:
    """
    加载训练样本
    
    Args:
        input_path (str): JSONL 文件路径
    
    Returns:
        list[dict]: 样本列表
    """
    samples = []
    with open(input_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                samples.append(json.loads(line))
    return samples


def main():
    parser = argparse.ArgumentParser(description='格式化训练数据')
    parser.add_argument('--agent-type', type=str, default='neutral',
                        choices=['neutral', 'supportive', 'psychoanalytic'],
                        help='Agent 类型')
    parser.add_argument('--input', type=str, default=None,
                        help='输入文件路径（默认自动检测）')
    parser.add_argument('--output', type=str, default=None,
                        help='输出文件路径（默认自动生成）')
    parser.add_argument('--source', type=str, default='auto',
                        choices=['auto', 'moa', 'reviewed', 'raw'],
                        help='数据来源: auto=自动检测, moa=MoA融合数据, reviewed=审核后, raw=原始分析')
    parser.add_argument('--format', type=str, default='jsonl',
                        choices=['jsonl', 'alpaca'],
                        help='输出格式')
    parser.add_argument('--only-reviewed', action='store_true',
                        help='只导出已审核的样本')
    parser.add_argument('--strip-raw', action='store_true', default=True,
                        help='移除 DeepSeek_raw/GLM_raw 等冗余字段（默认开启）')
    
    args = parser.parse_args()
    
    workspace = PROJECT_ROOT
    
    # 输入路径：按 source 参数或自动检测
    if args.input:
        input_path = args.input
    else:
        moa_path = workspace / 'advisor_out' / 'analysis' / f'fused_analysis_{args.agent_type}_moa.jsonl'
        reviewed_path = workspace / 'advisor_out' / 'analysis' / f'reviewed_analysis_{args.agent_type}.jsonl'
        raw_path = workspace / 'advisor_out' / 'analysis' / f'raw_analysis_{args.agent_type}.jsonl'
        
        if args.source == 'moa' or (args.source == 'auto' and moa_path.exists()):
            if not moa_path.exists():
                print(f"MoA 融合数据不存在: {moa_path}")
                return
            input_path = str(moa_path)
            print("使用 MoA 融合数据（推荐）")
        elif args.source == 'reviewed' or (args.source == 'auto' and reviewed_path.exists()):
            if not reviewed_path.exists():
                print(f"审核数据不存在: {reviewed_path}")
                return
            input_path = str(reviewed_path)
            print("使用审核后的数据")
        elif args.source == 'raw' or (args.source == 'auto' and raw_path.exists()):
            if not raw_path.exists():
                print(f"原始分析不存在: {raw_path}")
                return
            input_path = str(raw_path)
            print("使用原始分析数据（未审核）")
        else:
            print(f"未找到分析数据文件")
            print(f"请先运行 _02c_fusion_pipeline.py --moa 生成融合分析")
            return
    
    # 输出路径
    output_path = args.output or str(workspace / 'advisor_out' / 'training' / f'advisor_training_{args.agent_type}.jsonl')
    
    print(f"Agent 类型: {args.agent_type}")
    print(f"输入文件: {input_path}")
    print(f"输出文件: {output_path}")
    print(f"输出格式: {args.format}")
    print(f"只导出已审核: {args.only_reviewed}")
    print()
    
    # 加载样本
    samples = load_samples(input_path)
    print(f"加载了 {len(samples)} 个样本")
    
    # MoA 融合数据特有字段统计
    moa_count = sum(1 for s in samples if s.get('merge_quality', '').startswith('moa'))
    has_raw = sum(1 for s in samples if 'DeepSeek_raw' in s or 'GLM_raw' in s)
    if moa_count > 0:
        print(f"MoA 融合: {moa_count}")
        print(f"含原始分析(DeepSeek_raw/GLM_raw): {has_raw}（不会进入训练数据）")
    
    # 统计审核状态
    reviewed_count = sum(1 for s in samples if s.get('reviewed', False))
    if reviewed_count > 0:
        print(f"已审核: {reviewed_count}")
        print(f"未审核: {len(samples) - reviewed_count}")
    
    # Strip 冗余字段
    if args.strip_raw:
        for s in samples:
            s.pop('DeepSeek_raw', None)
            s.pop('GLM_raw', None)
            s.pop('step_details', None)
            s.pop('review_scores', None)
            s.pop('review_verdict', None)
            s.pop('review_total', None)
            s.pop('moa_elapsed', None)
            s.pop('remediation_rounds', None)
            s.pop('moa_fallback', None)
    
    # 创建格式化器
    config = {
        'format': args.format,
    }
    formatter = TrainingFormatter(config)
    
    # 导出训练数据
    formatter.export_training_data(samples, output_path, args.agent_type, args.only_reviewed)
    
    # 统计
    stats = formatter.get_stats()
    print()
    print("=" * 50)
    print("格式化统计:")
    print(f"  导出样本数: {stats['formatted']}")
    print("=" * 50)
    
    # 显示样本示例
    print("\n样本示例:")
    with open(output_path, 'r', encoding='utf-8') as f:
        first_line = f.readline()
        if first_line:
            sample = json.loads(first_line)
            print(json.dumps(sample, ensure_ascii=False, indent=2)[:500] + '...')


if __name__ == '__main__':
    main()
