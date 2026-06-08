#!/usr/bin/env python3
"""
QLoRA 模型训练脚本

功能：
- 使用 QLoRA（4-bit 量化 + LoRA）微调 Qwen3-8B-Instruct 模型
- 支持 3 种 Agent 类型的独立训练（中立/支持性/精神分析）
- 支持 HuggingFace 标准训练和 Unsloth 加速训练两种后端
- 支持断点续训、验证集 val_loss 监控
- 自动使用反匿名化后的 splits 数据（如存在）

处理流程：
1. 解析命令行参数（Agent 类型、训练超参数、后端选择等）
2. 确定训练数据路径（优先 splits_deanon > splits > 单文件）
3. 检查基座模型和训练数据是否存在
4. 创建 AdvisorTrainer 并配置 QLoRA 参数
5. 执行训练（支持断点续训）
6. 保存 LoRA 权重到输出目录

QLoRA 配置：
- 量化：4-bit NF4 + double quantization
- LoRA rank：16（默认）
- LoRA alpha：32（默认）
- 目标模块：自动检测（q_proj, k_proj, v_proj, o_proj 等）
- 梯度检查点：启用（节省显存）

输入：
- advisor_out/training/splits_deanon/train.jsonl: 训练集（推荐）
- advisor_out/training/splits_deanon/val.jsonl: 验证集（推荐）
- 或 advisor_out/training/advisor_training_{agent_type}.jsonl: 单文件训练数据

输出：
- advisor_out/models/relationship_advisor_{agent_type}/: LoRA 权重目录
  * adapter_config.json: LoRA 配置
  * adapter_model.safetensors: LoRA 权重

依赖：
- scripts/advisor/trainer.py: AdvisorTrainer 训练器
- torch, transformers, peft, bitsandbytes, trl

使用示例：
    # 训练中立顾问（使用 splits 数据）
    python scripts/advisor/run_all/_06_train_model.py --agent-type neutral --use-splits --epochs 5

    # 使用 Unsloth 加速训练（省显存快 2x）
    python scripts/advisor/run_all/_06_train_model.py --backend unsloth --use-splits

    # 从断点继续训练
    python scripts/advisor/run_all/_06_train_model.py --resume

    # 自定义超参数
    python scripts/advisor/run_all/_06_train_model.py --learning-rate 2e-4 --lora-r 32 --epochs 3

性能参考（RTX 5070 Ti 16GB）：
- 显存占用：约 12-14 GB（4-bit 量化）
- 训练时间：约 30-60 分钟（500 条数据，5 epochs）
- Unsloth 后端：约 15-30 分钟（快 2x）

注意事项：
- 需要约 16GB 显存
- 确保已下载 Qwen3-8B-Instruct 到 /data/models/
- 建议先运行 _00_verify_environment.py 验证环境
- 训练完成后运行 _07_run_inference.py 测试推理效果

作者：[Author]
更新于：2026-02-15
"""

import argparse
import os
import sys
from pathlib import Path

# 设置环境变量
os.environ['PYTORCH_ALLOC_CONF'] = 'expandable_segments:True'

# 添加项目根目录到 Python 路径
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.advisor.trainer import AdvisorTrainer


def main():
    parser = argparse.ArgumentParser(description='训练关系顾问模型')
    parser.add_argument('--agent-type', type=str, default='neutral',
                        choices=['neutral', 'supportive', 'psychoanalytic'],
                        help='Agent 类型')
    parser.add_argument('--input', type=str, default=None,
                        help='训练数据路径（默认自动生成）')
    parser.add_argument('--eval-data', type=str, default=None,
                        help='验证数据路径（用于 val_loss 监控）')
    parser.add_argument('--use-splits', action='store_true',
                        help='使用 splits/ 目录下的 train/val 划分数据')
    parser.add_argument('--output-dir', type=str, default=None,
                        help='输出目录（默认自动生成）')
    parser.add_argument('--base-model', type=str, default='/data/models/Qwen3-8B-Instruct',
                        help='基座模型路径')
    parser.add_argument('--epochs', type=int, default=5,
                        help='训练轮数')
    parser.add_argument('--batch-size', type=int, default=1,
                        help='批次大小')
    parser.add_argument('--gradient-accumulation', type=int, default=8,
                        help='梯度累积步数')
    parser.add_argument('--learning-rate', type=float, default=1e-4,
                        help='学习率')
    parser.add_argument('--lora-r', type=int, default=16,
                        help='LoRA rank')
    parser.add_argument('--lora-alpha', type=int, default=32,
                        help='LoRA alpha')
    parser.add_argument('--max-seq-length', type=int, default=4096,
                        help='最大序列长度')
    parser.add_argument('--backend', type=str, default='hf',
                        choices=['hf', 'unsloth'],
                        help='训练后端: hf=标准HuggingFace, unsloth=Unsloth(省显存快2x)')
    parser.add_argument('--resume', action='store_true',
                        help='从断点继续训练')
    
    args = parser.parse_args()
    
    workspace = PROJECT_ROOT
    
    # 输入路径
    # 优先使用 deanon splits（真实姓名），其次旧 splits（匿名）
    splits_deanon = workspace / 'advisor_out' / 'training' / 'splits_deanon'
    splits_old = workspace / 'advisor_out' / 'training' / 'splits'
    splits_dir = splits_deanon if splits_deanon.exists() else splits_old
    if args.use_splits and splits_dir.exists():
        input_path = args.input or str(splits_dir / 'train.jsonl')
        eval_path = args.eval_data or str(splits_dir / 'val.jsonl')
    else:
        input_path = args.input or str(workspace / 'advisor_out' / 'training' / f'advisor_training_{args.agent_type}.jsonl')
        eval_path = args.eval_data
    
    # 输出目录
    output_dir = args.output_dir or str(workspace / 'advisor_out' / 'models' / f'relationship_advisor_{args.agent_type}')
    
    # 检查输入文件
    if not Path(input_path).exists():
        print(f"错误：训练数据文件不存在: {input_path}")
        print("请先运行 _05_format_training_data.py --source moa 生成训练数据")
        return
    
    # 检查基座模型
    if not Path(args.base_model).exists():
        print(f"错误：基座模型不存在: {args.base_model}")
        print("请先下载 Qwen3-8B-Instruct 到 /data/models/")
        return
    
    print("=" * 60)
    print("关系顾问模型训练")
    print("=" * 60)
    print(f"Agent 类型: {args.agent_type}")
    print(f"基座模型: {args.base_model}")
    print(f"训练数据: {input_path}")
    if eval_path:
        print(f"验证数据: {eval_path}")
    print(f"输出目录: {output_dir}")
    print(f"训练轮数: {args.epochs}")
    print(f"批次大小: {args.batch_size}")
    print(f"梯度累积: {args.gradient_accumulation}")
    print(f"有效批次: {args.batch_size * args.gradient_accumulation}")
    print(f"学习率: {args.learning_rate}")
    print(f"LoRA rank: {args.lora_r}")
    print(f"LoRA alpha: {args.lora_alpha}")
    print(f"最大序列长度: {args.max_seq_length}")
    print(f"后端: {args.backend}")
    print("=" * 60)
    print()
    
    # 创建训练器
    config = {
        'base_model': args.base_model,
        'output_dir': output_dir,
        'lora_r': args.lora_r,
        'lora_alpha': args.lora_alpha,
        'learning_rate': args.learning_rate,
        'num_epochs': args.epochs,
        'batch_size': args.batch_size,
        'gradient_accumulation_steps': args.gradient_accumulation,
        'max_seq_length': args.max_seq_length,
        'use_4bit': True,
        'use_gradient_checkpointing': True,
        'use_unsloth': args.backend == 'unsloth',
    }
    
    trainer = AdvisorTrainer(config)
    
    try:
        # 开始训练
        trainer.train(input_path, eval_data_path=eval_path, resume_from_checkpoint=args.resume)
        
        print()
        print("=" * 60)
        print("训练完成！")
        print(f"LoRA 权重已保存到: {output_dir}")
        print()
        print("下一步：")
        print(f"  python scripts/advisor/run_all/_07_run_inference.py --agent-type {args.agent_type}")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n训练出错: {e}")
        raise
    finally:
        # 释放显存
        trainer.unload_model()


if __name__ == '__main__':
    main()
