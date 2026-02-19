#!/usr/bin/env python3
"""
导出审核文件脚本

功能：
- 将 LLM 生成的关系分析结果导出为 Markdown 文件
- 供人工审核、修改和标注
- 支持按 Agent 类型分别导出
- 每个文件包含固定数量的样本，便于分批审核

处理流程：
1. 加载 LLM 分析结果（raw_analysis_{agent_type}.jsonl）
2. 使用 TrainingFormatter 将分析结果格式化为 Markdown
3. 按 samples_per_file 分批输出 Markdown 文件
4. 每个样本包含对话原文、分析结果、审核勾选框

输入：
- advisor_out/analysis/raw_analysis_{agent_type}.jsonl: LLM 分析结果

输出：
- advisor_out/review/batch_XXX_{agent_type}.md: 审核用 Markdown 文件
  * 每个文件包含 15 个样本（可配置）
  * 包含审核勾选框 [ ] 已审核

依赖：
- scripts/advisor/formatter.py: TrainingFormatter 格式化器

使用示例：
    # 导出中立分析的审核文件
    python scripts/advisor/run_all/_03_export_for_review.py --agent-type neutral

    # 导出支持性分析，每文件 20 个样本
    python scripts/advisor/run_all/_03_export_for_review.py --agent-type supportive --samples-per-file 20

    # 自定义输入输出路径
    python scripts/advisor/run_all/_03_export_for_review.py --input path/to/analysis.jsonl --output-dir path/to/review/

注意事项：
- 审核完成后需将文件重命名为 reviewed_batch_XXX.md
- 审核时勾选 [x] 已审核，可直接修改分析内容
- 审核完成后运行 _04_import_reviewed.py 导入结果
- 建议先运行 _03b_ai_review.py 进行 AI 预审核，减少人工工作量

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


def load_analysis(input_path: str) -> list[dict]:
    """
    加载 LLM 分析结果
    
    Args:
        input_path (str): JSONL 文件路径
    
    Returns:
        list[dict]: 分析结果列表
    """
    samples = []
    with open(input_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                samples.append(json.loads(line))
    return samples


def main():
    parser = argparse.ArgumentParser(description='导出审核文件')
    parser.add_argument('--agent-type', type=str, default='neutral',
                        choices=['neutral', 'supportive', 'psychoanalytic'],
                        help='Agent 类型')
    parser.add_argument('--input', type=str, default=None,
                        help='输入文件路径（默认自动生成）')
    parser.add_argument('--output-dir', type=str, default=None,
                        help='输出目录（默认 advisor_out/review/）')
    parser.add_argument('--samples-per-file', type=int, default=15,
                        help='每个文件的样本数')
    
    args = parser.parse_args()
    
    workspace = PROJECT_ROOT
    input_path = args.input or str(workspace / 'advisor_out' / 'analysis' / f'raw_analysis_{args.agent_type}.jsonl')
    output_dir = args.output_dir or str(workspace / 'advisor_out' / 'review')
    
    print(f"Agent 类型: {args.agent_type}")
    print(f"输入文件: {input_path}")
    print(f"输出目录: {output_dir}")
    print(f"每文件样本数: {args.samples_per_file}")
    print()
    
    # 加载分析结果
    samples = load_analysis(input_path)
    print(f"加载了 {len(samples)} 个分析结果")
    
    # 创建格式化器
    config = {
        'samples_per_file': args.samples_per_file,
    }
    formatter = TrainingFormatter(config)
    
    # 生成审核文件
    files = formatter.generate_review_markdown(samples, output_dir, args.agent_type)
    
    print()
    print("=" * 50)
    print("审核说明:")
    print("1. 打开生成的 Markdown 文件")
    print("2. 检查每个分析结果，如有需要可直接修改")
    print("3. 审核完成后，勾选 [x] 已审核")
    print("4. 将文件重命名为 reviewed_batch_XXX.md")
    print("5. 运行 _04_import_reviewed.py 导入审核结果")
    print("=" * 50)


if __name__ == '__main__':
    main()
