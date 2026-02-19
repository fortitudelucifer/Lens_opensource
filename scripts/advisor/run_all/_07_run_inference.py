#!/usr/bin/env python3
"""
模型推理脚本

功能：
- 使用训练好的关系顾问 LoRA 模型分析对话
- 支持交互模式、单条分析、批量分析三种模式
- 支持 4-bit/8-bit 量化和无量化加载
- 自动检测最佳 LoRA 模型（Unsloth deanon > HF deanon > 旧版）

处理流程：
1. 解析命令行参数（Agent 类型、模型路径、推理参数等）
2. 自动检测最佳 LoRA 模型目录
3. 加载基座模型 + LoRA 权重（4-bit 量化）
4. 根据模式执行推理：
   a. 交互模式：终端循环输入对话，实时分析
   b. 单条模式：分析命令行输入的对话文本
   c. 批量模式：从 JSONL 文件批量分析，输出结果文件

输入：
- /data/models/Qwen3-8B-Instruct: 基座模型
- advisor_out/models/relationship_advisor_{agent_type}*/: LoRA 权重
- 或命令行输入的对话文本
- 或 JSONL 格式的对话文件

输出：
- 终端输出：分析结果文本
- 或 advisor_out/inference/results_{agent_type}.jsonl: 批量分析结果

依赖：
- scripts/advisor/inference.py: AdvisorInference 推理器
- torch, transformers, peft

使用示例：
    # 交互模式（默认）
    python scripts/advisor/run_all/_07_run_inference.py --agent-type neutral

    # 分析单条对话
    python scripts/advisor/run_all/_07_run_inference.py --input "ME: 今天好累\\nOTHER: 哦"

    # 批量分析文件
    python scripts/advisor/run_all/_07_run_inference.py --input-file conversations.jsonl --output results.jsonl

    # 只使用基座模型（不加载 LoRA）
    python scripts/advisor/run_all/_07_run_inference.py --use-base-only

性能参考（RTX 5070 Ti 16GB）：
- 显存占用：约 5-8 GB（4-bit 量化）
- 推理速度：约 2-5 秒/条（取决于输入长度）

注意事项：
- 需要约 8GB 显存（4-bit 量化）
- 确保已完成模型训练或使用基座模型
- 交互模式中用 / 分隔多条消息

作者：forcifer
更新于：2026-02-15
"""

import argparse
import os
import sys
from pathlib import Path

# 设置环境变量
os.environ['PYTORCH_CUDA_ALLOC_CONF'] = 'expandable_segments:True'

# 添加项目根目录到 Python 路径
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.advisor.inference import AdvisorInference


def interactive_mode(inference: AdvisorInference):
    """
    交互式对话分析模式
    
    在终端循环接收用户输入的对话文本，实时调用模型进行分析。
    支持用 / 分隔多条消息，输入 quit/exit/q 退出。
    
    Args:
        inference (AdvisorInference): 已加载模型的推理器实例
    """
    print("\n进入交互模式，输入对话进行分析")
    print("格式：ME: xxx / OTHER: xxx（用 / 分隔多条消息）")
    print("输入 'quit' 或 'exit' 退出\n")
    
    while True:
        try:
            user_input = input("请输入对话: ").strip()
            
            if user_input.lower() in ['quit', 'exit', 'q']:
                print("退出交互模式")
                break
            
            if not user_input:
                continue
            
            # 将 / 替换为换行
            conversation = user_input.replace(' / ', '\n').replace('/', '\n')
            
            print("\n分析中...\n")
            result = inference.analyze(conversation)
            
            print("=" * 60)
            print(result)
            print("=" * 60)
            print()
            
        except KeyboardInterrupt:
            print("\n退出交互模式")
            break
        except Exception as e:
            print(f"分析出错: {e}")


def main():
    parser = argparse.ArgumentParser(description='关系顾问模型推理')
    parser.add_argument('--agent-type', type=str, default='neutral',
                        choices=['neutral', 'supportive', 'psychoanalytic'],
                        help='Agent 类型')
    parser.add_argument('--model-dir', type=str, default=None,
                        help='LoRA 模型目录（默认自动生成）')
    parser.add_argument('--base-model', type=str, default='/data/models/Qwen3-8B-Instruct',
                        help='基座模型路径')
    parser.add_argument('--input', type=str, default=None,
                        help='要分析的对话文本')
    parser.add_argument('--input-file', type=str, default=None,
                        help='输入文件路径（JSONL 格式）')
    parser.add_argument('--output', type=str, default=None,
                        help='输出文件路径')
    parser.add_argument('--temperature', type=float, default=0.7,
                        help='生成温度')
    parser.add_argument('--top-p', type=float, default=0.9,
                        help='Top-p 采样')
    parser.add_argument('--max-tokens', type=int, default=1024,
                        help='最大生成 token 数')
    parser.add_argument('--quantization', type=str, default='4bit',
                        choices=['4bit', '8bit', 'none'],
                        help='量化方式')
    parser.add_argument('--use-base-only', action='store_true',
                        help='只使用基座模型（不加载 LoRA）')
    
    args = parser.parse_args()
    
    workspace = PROJECT_ROOT
    
    # 模型目录（优先 Unsloth deanon → HF deanon → 旧版无 deanon）
    if args.use_base_only:
        model_dir = None  # 不加载 LoRA
    elif args.model_dir:
        model_dir = args.model_dir
    else:
        candidates = [
            workspace / 'advisor_out' / 'models' / f'relationship_advisor_{args.agent_type}_deanon_unsloth',
            workspace / 'advisor_out' / 'models' / f'relationship_advisor_{args.agent_type}_deanon',
            workspace / 'advisor_out' / 'models' / f'relationship_advisor_{args.agent_type}',
        ]
        model_dir = str(next(
            (p for p in candidates if (p / 'adapter_config.json').exists()),
            candidates[-1],
        ))
    
    print("=" * 60)
    print("关系顾问模型推理")
    print("=" * 60)
    print(f"Agent 类型: {args.agent_type}")
    print(f"基座模型: {args.base_model}")
    if model_dir:
        print(f"LoRA 模型: {model_dir}")
    else:
        print("LoRA 模型: 不使用（仅基座模型）")
    print(f"量化方式: {args.quantization}")
    print("=" * 60)
    print()
    
    # 检查基座模型
    if not Path(args.base_model).exists():
        print(f"错误：基座模型不存在: {args.base_model}")
        print("请先下载 Qwen3-8B-Instruct 到 /data/models/")
        return
    
    # 创建推理器
    inference = AdvisorInference(
        agent_type=args.agent_type,
        model_dir=model_dir if not args.use_base_only else '/nonexistent',  # 强制不加载 LoRA
        base_model=args.base_model,
        quantization=args.quantization,
    )
    
    try:
        # 加载模型
        inference.load_model()
        
        if args.input_file:
            # 批量分析模式
            output_path = args.output or str(workspace / 'advisor_out' / 'inference' / f'results_{args.agent_type}.jsonl')
            
            inference.analyze_from_file(
                input_path=args.input_file,
                output_path=output_path,
                temperature=args.temperature,
                top_p=args.top_p,
                max_new_tokens=args.max_tokens,
            )
            
        elif args.input:
            # 单条分析模式
            conversation = args.input.replace('\\n', '\n')
            
            print("分析中...\n")
            result = inference.analyze(
                conversation,
                temperature=args.temperature,
                top_p=args.top_p,
                max_new_tokens=args.max_tokens,
            )
            
            print("=" * 60)
            print("分析结果：")
            print("=" * 60)
            print(result)
            print("=" * 60)
            
        else:
            # 交互模式
            interactive_mode(inference)
        
    except Exception as e:
        print(f"\n推理出错: {e}")
        raise
    finally:
        # 释放显存
        inference.unload_model()


if __name__ == '__main__':
    main()
