#!/usr/bin/env python3
"""
LLM 关系分析生成脚本

功能：
- 调用 LLM API 为对话片段生成关系分析报告
- 支持 9 种 LLM 后端（OpenAI、Claude、Gemini、Kimi、Grok、DeepSeek、Qwen 本地/云端、GLM）
- 支持 3 种 Agent 分析视角（中立、支持性、精神分析）
- 内置断点续跑机制，支持大批量任务中断恢复

处理流程：
1. 解析命令行参数（后端、模型、Agent 类型、输入输出路径等）
2. 加载对话片段（从 conversation_chunks.jsonl）
3. 创建 AnalysisGenerator 并配置 API 参数
4. 批量调用 LLM API 生成分析：
   a. 根据 Agent 类型构建不同的分析 prompt
   b. 逐条发送对话片段到 LLM
   c. 解析返回的分析结果
   d. 支持断点续跑（默认启用，--no-resume 可禁用）
5. 输出生成统计（成功/失败/重试/Token 用量）

支持的后端（9 个）：
- openai:     OpenAI API (gpt-5.2)
- claude:     Anthropic Claude API (claude-opus-4.6-think)，使用原生 SDK
- gemini:     Google Gemini API (gemini-3-pro-preview)
- kimi:       Moonshot Kimi API (kimi-k2.5)
- grok:       xAI Grok API (grok-4.1-thinking)
- deepseek:   DeepSeek API (deepseek-ai/DeepSeek-V3.1)
- qwen_local: 本地 Qwen（vLLM/Ollama OpenAI 兼容接口）
- qwen_cloud: 通义千问云端 (Qwen3-235B-A22B-Thinking)
- glm:        智谱 GLM (glm4.7)

Agent 分析类型：
- neutral: 中立分析，客观描述关系动态
- supportive: 支持性分析，侧重情感支持建议
- psychoanalytic: 精神分析，深层心理动力学解读

输入：
- advisor_out/chunks/conversation_chunks.jsonl: 对话片段（由 _01 步骤生成）

输出：
- advisor_out/analysis/raw_analysis_{agent_type}.jsonl: 原始分析结果
  * 每行包含：chunk_id、分析文本、Token 用量、模型信息

依赖：
- scripts/advisor/generator.py: AnalysisGenerator 分析生成器
- openai: OpenAI 兼容 API 客户端
- anthropic: Claude 原生 SDK（仅 claude 后端）

使用示例：
    # 使用 Claude 生成中立分析（默认）
    python scripts/advisor/run_all/_02_generate_analysis.py --backend claude --agent-type neutral

    # 使用 GPT-5 生成支持性分析
    python scripts/advisor/run_all/_02_generate_analysis.py --backend openai --agent-type supportive

    # 使用 DeepSeek 生成精神分析，限制处理 10 条
    python scripts/advisor/run_all/_02_generate_analysis.py --backend deepseek --agent-type psychoanalytic --limit 10

    # 禁用断点续跑，从头开始
    python scripts/advisor/run_all/_02_generate_analysis.py --no-resume

    # 自定义 API 地址（本地 Qwen）
    python scripts/advisor/run_all/_02_generate_analysis.py --backend qwen_local --base-url http://localhost:8000/v1

性能参考：
- API 调用速度：取决于后端和速率限制，通常 1-5 秒/条
- Token 消耗：每条分析约 500-2000 tokens（输出）
- 建议设置 --delay 避免触发 API 速率限制

注意事项：
- 需要设置对应后端的 API 密钥环境变量（如 ANTHROPIC_API_KEY）
- 断点续跑通过检查输出文件已有记录实现，删除输出文件可重新开始
- 不同后端的模型能力和价格差异较大，建议先用 --limit 测试
- 确保先运行 _01_extract_conversations.py 生成对话片段

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

from scripts.advisor.generator import AnalysisGenerator


def load_chunks(input_path: str) -> list[dict]:
    """
    加载对话片段文件
    
    从 JSONL 文件中逐行读取对话片段数据。
    
    Args:
        input_path (str): JSONL 文件路径
    
    Returns:
        list[dict]: 对话片段列表，每个元素为一个片段字典
    
    Example:
        >>> chunks = load_chunks("advisor_out/chunks/conversation_chunks.jsonl")
        >>> print(f"加载了 {len(chunks)} 个片段")
    """
    chunks = []
    with open(input_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                chunks.append(json.loads(line))
    return chunks


def main():
    """
    主函数：执行完整的 LLM 分析生成流程
    
    流程：
    1. 解析命令行参数（--backend, --model, --agent-type, --input, --output 等）
    2. 根据后端自动选择默认模型
    3. 加载对话片段并应用数量限制
    4. 创建 AnalysisGenerator 并配置 API 参数
    5. 批量生成分析（支持断点续跑）
    6. 输出统计信息（成功/失败/重试/Token 用量）
    
    命令行参数：
        --backend: LLM 后端（openai/claude/gemini/kimi/grok/deepseek/qwen_local/qwen_cloud/glm）
        --model: 模型名称（默认根据后端自动选择）
        --agent-type: Agent 类型（neutral/supportive/psychoanalytic）
        --input: 输入文件路径
        --output: 输出文件路径
        --api-key: API 密钥（默认从环境变量读取）
        --base-url: 自定义 API 地址
        --temperature: 生成温度，默认 0.7
        --delay: API 调用间隔（秒），默认 1.0
        --limit: 限制处理数量（测试用）
        --no-resume: 禁用断点续跑
    """
    parser = argparse.ArgumentParser(description='使用 LLM 生成关系分析')
    parser.add_argument('--backend', type=str, default='claude',
                        choices=['openai', 'claude', 'gemini', 'kimi', 'grok', 'deepseek', 'qwen_local', 'qwen_cloud', 'glm'],
                        help='LLM 后端')
    parser.add_argument('--model', type=str, default=None,
                        help='模型名称（默认根据后端自动选择）')
    parser.add_argument('--agent-type', type=str, default='neutral',
                        choices=['neutral', 'supportive', 'psychoanalytic'],
                        help='Agent 类型')
    parser.add_argument('--input', type=str, default=None,
                        help='输入文件路径（默认 advisor_out/chunks/conversation_chunks.jsonl）')
    parser.add_argument('--output', type=str, default=None,
                        help='输出文件路径（默认自动生成）')
    parser.add_argument('--api-key', type=str, default=None,
                        help='API 密钥（默认从环境变量读取）')
    parser.add_argument('--base-url', type=str, default=None,
                        help='自定义 API 地址')
    parser.add_argument('--temperature', type=float, default=0.7,
                        help='生成温度')
    parser.add_argument('--delay', type=float, default=1.0,
                        help='API 调用间隔（秒）')
    parser.add_argument('--limit', type=int, default=None,
                        help='限制处理数量（用于测试）')
    parser.add_argument('--no-resume', action='store_true',
                        help='禁用断点续跑，从头开始（默认启用断点续跑）')
    
    args = parser.parse_args()
    
    # 输入输出路径
    workspace = PROJECT_ROOT
    input_path = args.input or str(workspace / 'advisor_out' / 'chunks' / 'conversation_chunks.jsonl')
    output_path = args.output or str(workspace / 'advisor_out' / 'analysis' / f'raw_analysis_{args.agent_type}.jsonl')
    
    print(f"后端: {args.backend}")
    print(f"模型: {args.model or '从环境变量自动读取'}")
    print(f"Agent 类型: {args.agent_type}")
    print(f"输入文件: {input_path}")
    print(f"输出文件: {output_path}")
    print()
    
    # 加载对话片段
    chunks = load_chunks(input_path)
    print(f"加载了 {len(chunks)} 个对话片段")
    
    if args.limit:
        chunks = chunks[:args.limit]
        print(f"限制处理 {args.limit} 个片段")
    
    # 创建生成器（不传 model → 让 AnalysisGenerator 自动从 .env.advisor 环境变量读取）
    config = {
        'backend': args.backend,
        'api_key': args.api_key,
        'base_url': args.base_url,
        'temperature': args.temperature,
        'rate_limit_delay': args.delay,
    }
    if args.model:
        config['model'] = args.model
    
    generator = AnalysisGenerator(config)
    
    # 批量生成（默认断点续跑）
    resume = not args.no_resume
    if not resume:
        print("ℹ️  已禁用断点续跑，将从头开始生成")
    results = generator.batch_generate(chunks, args.agent_type, output_path, resume=resume)
    
    # 打印统计
    stats = generator.get_stats()
    print()
    print("=" * 50)
    print("生成统计:")
    print(f"  成功: {stats['success']}")
    print(f"  失败: {stats['failed']}")
    print(f"  重试: {stats['retries']}")
    print(f"  总 Token: {stats['total_tokens']}")
    print("=" * 50)


if __name__ == '__main__':
    main()
