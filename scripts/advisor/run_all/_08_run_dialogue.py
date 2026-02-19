#!/usr/bin/env python3
"""
实时对话脚本

功能：
- 交互式终端对话界面，与关系顾问 Agent 实时对话
- 支持 listen（即时倾听）和 consult（深度咨询）两种模式
- listen 模式：快速共情响应，使用本地模型
- consult 模式：深度分析，使用云端模型 + GraphRAG 检索
- 支持 GraphRAG 向量检索增强
- 流式输出，逐 token 显示

处理流程：
1. 初始化 StreamingDialogueEngine（配置本地/云端模型）
2. 可选：加载 GraphRAG 向量索引
3. 进入交互式对话循环：
   a. 接收用户输入
   b. 处理命令（/listen, /consult, /clear, /history, /quit）
   c. 调用引擎生成回复（流式输出）
   d. 维护对话历史

对话模式：
- listen（即时倾听）：
  * 使用本地模型（Qwen3-8B-Instruct via Ollama）
  * 快速共情响应，低延迟
  * 适合日常倾诉和情感支持
- consult（深度咨询）：
  * 使用云端模型（DeepSeek 等）
  * GraphRAG 检索历史对话上下文
  * 深度关系分析和建议
  * 适合需要专业分析的场景

输入：
- 终端用户输入
- advisor_out/vector_index/: GraphRAG 向量索引（可选）

输出：
- 终端流式输出：顾问回复

依赖：
- scripts/advisor/streaming.py: StreamingDialogueEngine 流式对话引擎
- asyncio: 异步流式输出

使用示例：
    # 默认 listen 模式
    python scripts/advisor/run_all/_08_run_dialogue.py

    # consult 模式
    python scripts/advisor/run_all/_08_run_dialogue.py --mode consult

    # 指定 GraphRAG 索引
    python scripts/advisor/run_all/_08_run_dialogue.py --index-path path/to/index

    # 禁用 GraphRAG
    python scripts/advisor/run_all/_08_run_dialogue.py --no-graph

    # 自定义本地模型地址
    python scripts/advisor/run_all/_08_run_dialogue.py --local-url http://localhost:8000/v1

注意事项：
- listen 模式需要本地运行 Ollama 或 vLLM 服务
- consult 模式需要配置云端 API 密钥
- GraphRAG 索引需要先运行 _09_build_graph.py 构建
- 输入 /help 查看所有可用命令

作者：forcifer
更新于：2026-02-15
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.advisor.streaming import StreamingDialogueEngine


def print_banner(mode: str):
    print("\n" + "=" * 60)
    print("  关系顾问 - 实时对话")
    print(f"  当前模式：{'🎧 即时倾听 (listen)' if mode == 'listen' else '🔍 深度咨询 (consult)'}")
    print("  输入 /help 查看可用命令")
    print("=" * 60 + "\n")


def print_help():
    print("\n可用命令：")
    print("  /listen    - 切换到即时倾听模式（快速共情响应）")
    print("  /consult   - 切换到深度咨询模式（云端分析 + 本地回复）")
    print("  /clear     - 清空对话历史")
    print("  /history   - 查看对话历史")
    print("  /quit      - 退出")
    print()


async def run_dialogue(engine: StreamingDialogueEngine):
    """运行交互式对话循环"""
    print_banner(engine.mode.value)

    while True:
        try:
            user_input = input("你: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            break

        if not user_input:
            continue

        # 处理命令
        if user_input.startswith('/'):
            cmd = user_input.lower()
            if cmd == '/quit' or cmd == '/exit':
                print("再见！")
                break
            elif cmd == '/listen':
                engine.switch_mode('listen')
                print("✅ 已切换到即时倾听模式\n")
                continue
            elif cmd == '/consult':
                engine.switch_mode('consult')
                print("✅ 已切换到深度咨询模式\n")
                continue
            elif cmd == '/clear':
                engine.clear_history()
                print("✅ 对话历史已清空\n")
                continue
            elif cmd == '/history':
                history = engine.get_history()
                if not history:
                    print("（暂无对话历史）\n")
                else:
                    for turn in history:
                        prefix = "你" if turn.role == 'user' else "顾问"
                        print(f"  [{turn.mode}] {prefix}: {turn.content[:80]}...")
                    print()
                continue
            elif cmd == '/help':
                print_help()
                continue
            else:
                print(f"未知命令：{cmd}，输入 /help 查看帮助\n")
                continue

        # 对话
        mode_icon = '🎧' if engine.mode.value == 'listen' else '🔍'
        print(f"\n顾问 [{mode_icon}]: ", end="", flush=True)

        async for token in engine.chat(user_input):
            print(token, end="", flush=True)

        print("\n")


def main():
    parser = argparse.ArgumentParser(description='关系顾问实时对话')
    parser.add_argument('--mode', choices=['listen', 'consult'], default='listen',
                        help='初始对话模式（默认 listen）')
    parser.add_argument('--index-path', type=str, default=None,
                        help='GraphRAG 索引目录路径')
    parser.add_argument('--local-url', type=str, default='http://localhost:11434/v1',
                        help='本地模型 API 地址（默认 http://localhost:11434/v1）')
    parser.add_argument('--local-model', type=str, default='Qwen3-8B-Instruct',
                        help='本地模型名称')
    parser.add_argument('--cloud-backend', type=str, default='deepseek',
                        help='云端后端（默认 deepseek）')
    parser.add_argument('--no-graph', action='store_true',
                        help='禁用 GraphRAG')

    args = parser.parse_args()

    # 构建配置
    config = {
        'local_base_url': args.local_url,
        'local_model': args.local_model,
        'cloud_backend': args.cloud_backend,
    }

    # 初始化引擎
    engine = StreamingDialogueEngine(config)
    engine.switch_mode(args.mode)

    # 加载 GraphRAG 索引
    if not args.no_graph:
        index_path = args.index_path
        if index_path is None:
            default_index = PROJECT_ROOT / 'advisor_out' / 'vector_index'
            if default_index.exists():
                index_path = str(default_index)

        if index_path:
            print(f"加载 GraphRAG 索引：{index_path}")
            try:
                engine.init_graph_rag(index_path)
            except Exception as e:
                print(f"警告：GraphRAG 加载失败：{e}，继续无向量检索模式")

    # 运行对话
    try:
        asyncio.run(run_dialogue(engine))
    finally:
        engine.unload_graph_rag()


if __name__ == '__main__':
    main()
