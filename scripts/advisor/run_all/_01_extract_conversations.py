#!/usr/bin/env python3
"""
对话片段提取脚本

功能：
- 从 SFT 训练数据（agent_sft_l1.jsonl 或 agent_sft_l2.jsonl）中提取有代表性的对话片段
- 使用滑动窗口算法切分长对话为固定大小的片段
- 自动分类片段类型（冲突对话、甜蜜对话、普通对话）
- 支持 L1（本地训练数据）和 L2（匿名化数据）两种输入源

处理流程：
1. 解析命令行参数（输入源、片段数量、窗口参数）
2. 加载 SFT 训练数据（JSONL 格式）
3. 使用 ConversationExtractor 进行滑动窗口切分：
   a. 按窗口大小（默认 20 条消息）和步长（默认 10）滑动
   b. 过滤掉消息数不足的片段（最少 10 条）
   c. 自动分类片段情感类型
4. 按指定数量采样输出片段
5. 保存为 JSONL 格式并输出统计信息

输入：
- timeline_out/agent_sft_l1.jsonl: L1 本地训练数据（默认）
- timeline_out/agent_sft_l2.jsonl: L2 匿名化训练数据（可选）
- 或自定义 JSONL 文件路径

输出：
- advisor_out/chunks/conversation_chunks.jsonl: 提取的对话片段
  * 每行一个 JSON 对象，包含消息列表和元数据

依赖：
- scripts/advisor/extractor.py: ConversationExtractor 对话提取器

使用示例：
    # 从 L1 数据提取 100 个片段（默认）
    python scripts/advisor/run_all/_01_extract_conversations.py --num 100

    # 从 L2 匿名化数据提取
    python scripts/advisor/run_all/_01_extract_conversations.py --input l2 --num 100

    # 自定义输入文件和窗口参数
    python scripts/advisor/run_all/_01_extract_conversations.py \\
        --input-file path/to/file.jsonl \\
        --window-size 30 --step-size 15 --num 200

    # 指定输出路径
    python scripts/advisor/run_all/_01_extract_conversations.py --output path/to/output.jsonl

性能参考：
- 处理速度：约 1000 条消息/秒
- 内存占用：取决于输入文件大小，通常 < 1GB

注意事项：
- 输入文件必须为 JSONL 格式，每行一个 JSON 对象
- 窗口大小和步长会影响片段的重叠程度和总数量
- 提取的片段将作为后续 LLM 分析（_02_generate_analysis.py）的输入
- 建议先检查输入数据质量，确保 SFT 数据格式正确

作者：forcifer
更新于：2026-02-15
"""

import argparse
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.advisor.extractor import ConversationExtractor


def main():
    """
    主函数：执行完整的对话片段提取流程
    
    流程：
    1. 解析命令行参数（--input, --input-file, --num, --window-size, --step-size, --output）
    2. 确定输入文件路径（L1/L2/自定义）
    3. 创建 ConversationExtractor 并配置滑动窗口参数
    4. 执行片段提取和采样
    5. 保存结果并输出统计信息（总消息数、候选/选中片段数、各类型分布）
    
    命令行参数：
        --input: 输入数据类型，l1（本地）或 l2（匿名化），默认 l1
        --input-file: 自定义输入文件路径（覆盖 --input）
        --num: 提取的片段数量，默认 100
        --window-size: 滑动窗口大小（消息数），默认 20
        --step-size: 滑动步长，默认 10
        --output: 输出文件路径，默认 advisor_out/chunks/conversation_chunks.jsonl
    """
    parser = argparse.ArgumentParser(description='从 SFT 数据中提取对话片段')
    parser.add_argument('--input', choices=['l1', 'l2'], default='l1',
                        help='输入数据类型：l1（本地训练）或 l2（匿名化）')
    parser.add_argument('--input-file', type=str, default=None,
                        help='自定义输入文件路径（覆盖 --input）')
    parser.add_argument('--num', type=int, default=100,
                        help='提取的片段数量（默认 100）')
    parser.add_argument('--window-size', type=int, default=20,
                        help='滑动窗口大小（默认 20）')
    parser.add_argument('--step-size', type=int, default=10,
                        help='滑动步长（默认 10）')
    parser.add_argument('--output', type=str, default=None,
                        help='输出文件路径（默认自动生成）')
    
    args = parser.parse_args()
    
    # 工作空间路径（当前目录）
    workspace = PROJECT_ROOT
    
    # 确定输入文件
    if args.input_file:
        input_path = args.input_file
    else:
        if args.input == 'l1':
            input_path = Path(workspace) / 'timeline_out' / 'agent_sft_l1.jsonl'
        else:
            input_path = Path(workspace) / 'timeline_out' / 'agent_sft_l2.jsonl'
    
    # 确定输出文件
    if args.output:
        output_path = args.output
    else:
        output_path = Path(workspace) / 'advisor_out' / 'chunks' / 'conversation_chunks.jsonl'
    
    print(f"输入文件: {input_path}")
    print(f"输出文件: {output_path}")
    print(f"提取数量: {args.num}")
    print(f"窗口大小: {args.window_size}")
    print(f"滑动步长: {args.step_size}")
    print()
    
    # 创建提取器
    config = {
        'window_size': args.window_size,
        'step_size': args.step_size,
        'min_messages': 10,
        'exclude_system': True,
        'exclude_types': [],
    }
    
    extractor = ConversationExtractor(config)
    
    # 提取片段
    chunks = extractor.extract_chunks(str(input_path), num_chunks=args.num)
    
    # 保存结果
    extractor.save_chunks(chunks, str(output_path))
    
    # 打印统计
    stats = extractor.get_stats()
    print()
    print("=" * 50)
    print("提取统计:")
    print(f"  总消息数: {stats['total_messages']}")
    print(f"  候选片段数: {stats['total_chunks']}")
    print(f"  选中片段数: {stats['filtered_chunks']}")
    print(f"  冲突对话: {stats['conflict_chunks']}")
    print(f"  甜蜜对话: {stats['sweet_chunks']}")
    print(f"  普通对话: {stats['normal_chunks']}")
    print("=" * 50)


if __name__ == '__main__':
    main()
