#!/usr/bin/env python3
"""
导入审核结果脚本

功能：
- 解析人工审核后的 Markdown 文件
- 提取审核标注（已审核/未审核）和修改后的分析内容
- 合并所有审核文件的结果，输出为 JSONL 格式

处理流程：
1. 扫描审核目录，查找 reviewed_*.md 文件
2. 使用 TrainingFormatter 解析 Markdown 中的审核标注
3. 统计已审核/未审核样本数
4. 保存合并后的审核结果为 JSONL

输入：
- advisor_out/review/reviewed_batch_XXX_{agent_type}.md: 人工审核后的 Markdown 文件
  * 文件名必须以 'reviewed_' 开头

输出：
- advisor_out/analysis/reviewed_analysis_{agent_type}.jsonl: 合并后的审核结果
  * 包含审核标注和修改后的分析内容

依赖：
- scripts/advisor/formatter.py: TrainingFormatter（Markdown 解析）

使用示例：
    # 导入单个审核文件
    python scripts/advisor/run_all/_04_import_reviewed.py \\
        --input advisor_out/review/reviewed_batch_001_neutral.md

    # 导入目录下所有已审核文件
    python scripts/advisor/run_all/_04_import_reviewed.py \\
        --input-dir advisor_out/review/ --agent-type neutral

    # 自定义输出路径
    python scripts/advisor/run_all/_04_import_reviewed.py --output path/to/output.jsonl

注意事项：
- 审核文件名必须以 'reviewed_' 开头才能被识别
- 未勾选 [x] 已审核的样本也会被导入，但标记为未审核
- 导入后的结果将作为 _05_format_training_data.py 的输入

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


def main():
    parser = argparse.ArgumentParser(description='导入审核结果')
    parser.add_argument('--input', type=str, default=None,
                        help='单个审核文件路径')
    parser.add_argument('--input-dir', type=str, default=None,
                        help='审核文件目录（导入所有 reviewed_*.md 文件）')
    parser.add_argument('--agent-type', type=str, default='neutral',
                        choices=['neutral', 'supportive', 'psychoanalytic'],
                        help='Agent 类型（用于过滤文件）')
    parser.add_argument('--output', type=str, default=None,
                        help='输出文件路径（默认自动生成）')
    
    args = parser.parse_args()
    
    workspace = PROJECT_ROOT
    
    # 确定输入文件
    input_files = []
    if args.input:
        input_files.append(args.input)
    elif args.input_dir:
        input_dir = Path(args.input_dir)
        pattern = f'reviewed_*_{args.agent_type}.md'
        input_files = list(input_dir.glob(pattern))
        if not input_files:
            # 尝试不带 agent_type 的模式
            input_files = list(input_dir.glob('reviewed_*.md'))
    else:
        # 默认目录
        input_dir = workspace / 'advisor_out' / 'review'
        pattern = f'reviewed_*_{args.agent_type}.md'
        input_files = list(input_dir.glob(pattern))
    
    if not input_files:
        print("未找到审核文件")
        print("请确保文件名以 'reviewed_' 开头")
        return
    
    print(f"找到 {len(input_files)} 个审核文件")
    
    # 输出路径
    output_path = args.output or str(workspace / 'advisor_out' / 'analysis' / f'reviewed_analysis_{args.agent_type}.jsonl')
    
    # 解析所有文件
    formatter = TrainingFormatter()
    all_samples = []
    
    for filepath in input_files:
        print(f"解析: {filepath}")
        samples = formatter.parse_reviewed_markdown(str(filepath))
        all_samples.extend(samples)
    
    # 统计
    reviewed_count = sum(1 for s in all_samples if s.get('reviewed', False))
    print()
    print(f"总样本数: {len(all_samples)}")
    print(f"已审核: {reviewed_count}")
    print(f"未审核: {len(all_samples) - reviewed_count}")
    
    # 保存结果
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        for sample in all_samples:
            f.write(json.dumps(sample, ensure_ascii=False) + '\n')
    
    print(f"\n已保存到 {output_path}")


if __name__ == '__main__':
    main()
