#!/usr/bin/env python3
"""
数据增强与多教师蒸馏脚本

功能：
- 从外部心理咨询数据集导入数据（PsyCLIENT-CP、CPsDD、AuraDial）
- 通过多教师模型蒸馏生成高质量训练样本
- 逻辑教师（DeepSeek Reasoner）+ 风格教师（Claude Opus）双教师架构
- 质量过滤：自动过滤低质量蒸馏结果
- 支持从 JSONL 文件直接导入

处理流程：
1. 导入外部数据集或 JSONL 文件
2. 多教师蒸馏（可选）：
   a. 逻辑教师：生成结构化分析（推理链、因果关系）
   b. 风格教师：生成自然语言回复（共情、专业表达）
   c. 融合两个教师的输出
3. 质量过滤：
   a. 长度检查（过短/过长）
   b. 格式检查（字段完整性）
   c. 内容检查（有害内容检测）
4. 保存增强后的训练数据

支持的外部数据集：
- PsyCLIENT-CP: 中文心理咨询对话数据集
- CPsDD: 中文心理疾病对话数据集
- AuraDial: 多轮心理咨询对话数据集

教师模型配置：
- deepseek_reasoner: DeepSeek Reasoner（逻辑推理，低成本）
- claude_opus: Claude Opus 4.6 Think（风格生成，高质量）
- grok: Grok 4（备选）
- qwen3_max: Qwen3-235B（备选）
- glm4_plus: GLM-4-Plus（备选）

输入：
- 外部数据集文件（--dataset + --data-path）
- 或 JSONL 文件（--jsonl）

输出：
- advisor_out/training/augmented_data.jsonl: 增强后的训练数据

依赖：
- scripts/advisor/augmentor.py: DataAugmentor 数据增强器
- 各教师模型的 API 密钥（环境变量）

使用示例：
    # 导入 PsyCLIENT-CP 数据集并蒸馏
    python scripts/advisor/run_all/_10_augment_data.py --dataset PsyCLIENT-CP --data-path path/to/dataset

    # 指定教师模型
    python scripts/advisor/run_all/_10_augment_data.py --dataset CPsDD --data-path path/to/data \\
        --logic-teacher deepseek_reasoner --style-teacher claude_opus

    # 仅质量过滤（跳过蒸馏）
    python scripts/advisor/run_all/_10_augment_data.py --jsonl path/to/data.jsonl --filter-only

性能参考：
- 蒸馏速度：约 3-5 秒/条（取决于教师模型）
- 质量通过率：约 70-85%
- 预估成本：约 $0.01-0.05/条（取决于教师模型）

注意事项：
- 蒸馏需要配置教师模型的 API 密钥
- 建议先用小批量测试蒸馏质量
- --filter-only 模式可跳过蒸馏，仅做质量过滤
- 增强数据可与原始训练数据合并使用

作者：[Author]
更新于：2026-02-15
"""

import argparse
import json
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.advisor.augmentor import DataAugmentor


def main():
    parser = argparse.ArgumentParser(description='数据增强与蒸馏')
    parser.add_argument('--dataset', type=str, default=None,
                        choices=['PsyCLIENT-CP', 'CPsDD', 'AuraDial'],
                        help='外部数据集名称')
    parser.add_argument('--data-path', type=str, default=None,
                        help='数据集路径')
    parser.add_argument('--jsonl', type=str, default=None,
                        help='从 JSONL 文件导入（替代 --dataset）')
    parser.add_argument('--output', type=str, default=None,
                        help='输出文件路径')
    parser.add_argument('--logic-teacher', type=str, default='claude_opus',
                        help='逻辑教师模型（默认 claude_opus，可用: claude_opus/claude_backup/gpt/grok/gemini）')
    parser.add_argument('--style-teacher', type=str, default='claude_backup',
                        help='风格教师模型（默认 claude_backup，可用: claude_opus/claude_backup/gpt/grok/gemini）')
    parser.add_argument('--filter-only', action='store_true',
                        help='仅执行质量过滤，跳过蒸馏')
    parser.add_argument('--batch-size', type=int, default=5,
                        help='蒸馏批次大小（默认 5）')
    parser.add_argument('--rate-limit', type=float, default=1.0,
                        help='API 调用间隔秒数（默认 1.0）')

    args = parser.parse_args()

    # 确定输出路径
    workspace = PROJECT_ROOT
    output_path = args.output or str(
        workspace / 'advisor_out' / 'training' / 'augmented_data.jsonl'
    )

    # 教师模型配置（从环境变量读取 API key / base_url / model）
    # 与 .env.advisor 保持一致
    # 注意: 仅配置当前可用的后端（2026-04-26 验证）
    import os
    teacher_configs = {
        'claude_opus': {
            'model': os.environ.get('ANTHROPIC_MODEL', 'claude-sonnet-4.6-think'),
            'base_url': os.environ.get('ANTHROPIC_BASE_URL', 'https://api.example.com/v1'),
            'api_key_env': 'ANTHROPIC_API_KEY',
            'temperature': 0.7,
            'max_tokens': 2000,
            'cost_per_1k_tokens': 0.015,
        },
        'claude_backup': {
            'model': os.environ.get('ANTHROPIC_BACKUP_MODEL', 'claude-sonnet-4.6'),
            'base_url': os.environ.get('ANTHROPIC_BACKUP_BASE_URL', 'https://api.example.com/v1'),
            'api_key_env': 'ANTHROPIC_BACKUP_API_KEY',
            'temperature': 0.7,
            'max_tokens': 2000,
            'cost_per_1k_tokens': 0.015,
        },
        'gpt': {
            'model': os.environ.get('OPENAI_MODEL', 'gpt-5.3-codex-spark'),
            'base_url': os.environ.get('OPENAI_BASE_URL', 'https://api.example.com/v1'),
            'api_key_env': 'OPENAI_API_KEY',
            'temperature': 0.7,
            'max_tokens': 2000,
            'cost_per_1k_tokens': 0.003,
        },
        'grok': {
            'model': os.environ.get('XAI_MODEL', 'grok-4.1-thinking'),
            'base_url': os.environ.get('XAI_BASE_URL', 'https://api.example.com/v1'),
            'api_key_env': 'XAI_API_KEY',
            'temperature': 0.7,
            'max_tokens': 2000,
            'cost_per_1k_tokens': 0.003,
        },
        'gemini': {
            'model': os.environ.get('GOOGLE_MODEL', 'gemini-3.1-pro-preview'),
            'base_url': os.environ.get('GOOGLE_BASE_URL', 'https://api.example.com/v1'),
            'api_key_env': 'GOOGLE_API_KEY',
            'temperature': 0.7,
            'max_tokens': 2000,
            'cost_per_1k_tokens': 0.002,
        },
    }

    # 初始化
    config = {
        'teacher_configs': teacher_configs,
        'batch_size': args.batch_size,
        'rate_limit_delay': args.rate_limit,
    }
    augmentor = DataAugmentor(config)

    # 导入数据
    if args.dataset and args.data_path:
        print(f"导入数据集 {args.dataset}：{args.data_path}")
        count = augmentor.import_dataset(args.dataset, args.data_path)
        print(f"导入 {count} 条样本")
    elif args.jsonl:
        print(f"从 JSONL 导入：{args.jsonl}")
        count = augmentor.import_jsonl(args.jsonl)
        print(f"导入 {count} 条样本")
    else:
        print("错误：请指定 --dataset + --data-path 或 --jsonl")
        sys.exit(1)

    if not args.filter_only:
        # 蒸馏
        print(f"\n开始多教师蒸馏...")
        print(f"  逻辑教师：{args.logic_teacher}")
        print(f"  风格教师：{args.style_teacher}")
        success = augmentor.distill(
            logic_teacher=args.logic_teacher,
            style_teacher=args.style_teacher,
        )
        print(f"蒸馏成功：{success} 条")

    # 质量过滤
    print("\n质量过滤中...")
    remaining = augmentor.filter_quality()
    print(f"过滤后保留：{remaining} 条")

    # 保存
    augmentor.save(output_path)

    # 输出统计
    stats = augmentor.get_stats()
    print(f"\n=== 数据增强统计 ===")
    print(f"原始样本数：{stats.original_count}")
    print(f"增强后样本数：{stats.augmented_count}")
    print(f"过滤掉样本数：{stats.filtered_count}")
    print(f"质量通过率：{stats.quality_pass_rate:.1%}")
    print(f"蒸馏成功率：{stats.distill_success_rate:.1%}")
    print(f"预估成本：${stats.total_cost_usd:.4f}")
    print(f"耗时：{stats.elapsed_seconds:.1f}s")
    print(f"\n输出文件：{output_path}")
    print("完成！")


if __name__ == '__main__':
    main()
