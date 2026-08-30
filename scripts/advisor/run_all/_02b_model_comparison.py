#!/usr/bin/env python3
"""
多模型对比评测脚本 — 5 chunks × 8 backends 并排对比

功能：
- 从对话片段中选取 5 个代表性样本（冲突/冷暴力/甜蜜/多模态/长文本）
- 使用 8 个云端 LLM 后端分别生成关系分析
- 输出并排对比 Markdown 报告，含人工评分表
- 支持断点续跑，跳过已成功的 chunk+backend 组合

处理流程：
1. 从 500 个 chunks 中智能选取 5 个代表性片段：
   a. 高分冲突对话（按 score 排序取最高）
   b. 冷暴力/冷处理对话（含关键词匹配）
   c. 甜蜜互动对话（按 score 排序取最高）
   d. 多模态丰富对话（含语音/图片/表情标记最多的）
   e. 长文本深度对话（按文本长度排序取最长）
2. 对每个 chunk，逐后端调用 LLM API 生成分析
3. 生成每个 chunk 的详情 Markdown（含 8 个后端结果并排展示）
4. 生成汇总对比报告（成功率、耗时、人工评分表）

8 个对比后端：
- GPT-5.2-high (backup provider-codex)
- Claude Opus 4.6 Thinking (proxy-key)
- Grok 4.1 Thinking (proxy-key)
- DeepSeek V3.2 (proxy-key)
- Gemini 3 Pro (proxy-key)
- qwen3.5-397b-a17b Thinking (proxy-key)
- GLM 4.7 (backup provider-glm)
- Kimi K2.5 (proxy-key)

输入：
- advisor_out/chunks/conversation_chunks.jsonl: 对话片段
- local_secrets/platforms.yaml: API 平台配置（URL + Key）

输出：
- advisor_out/comparison/comparison_report.md: 汇总对比报告 + 人工评分表
- advisor_out/comparison/chunk_01_conflict.md: 各 chunk 的 8 后端结果详情
- advisor_out/comparison/chunk_*.json: 原始 JSON 数据

依赖：
- scripts/advisor/generator.py: AnalysisGenerator 分析生成器
- local_secrets/platforms.yaml: API 平台配置
- PyYAML: YAML 配置解析

使用示例：
    # 加载环境变量并运行
    source local_secrets/.env.advisor
    python scripts/advisor/run_all/_02b_model_comparison.py

    # 指定后端和 chunk 数量
    python scripts/advisor/run_all/_02b_model_comparison.py \\
        --backends gpt-5.5-high claude-opus-4-8-think --chunk-count 3

    # 从第 3 个 chunk 开始（跳过前 2 个）
    python scripts/advisor/run_all/_02b_model_comparison.py --start-chunk 3

性能参考：
- 单个 chunk × 8 后端：约 3-5 分钟（取决于最慢的后端）
- 完整 5 chunks × 8 backends：约 15-25 分钟
- 每个后端调用间隔 1 秒，避免触发速率限制

注意事项：
- 需要先配置 local_secrets/platforms.yaml 中的 API 密钥
- 建议先用 --chunk-count 1 测试单个 chunk
- 人工评分表需要在生成的 Markdown 文件中手动填写
- 评分维度：分析准确性、洞察深度、多模态理解、结构完整性、中文质量

作者：[Author]
更新于：2026-02-15
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))
PLATFORMS_YAML = PROJECT_ROOT / "local_secrets" / "platforms.yaml"

from scripts.advisor.generator import AnalysisGenerator


def load_platform_key(platform_name: str) -> tuple[str, str]:
    """
    从 platforms.yaml 读取指定平台的 API 配置
    
    Args:
        platform_name (str): 平台名称（如 'proxy-key', 'backup provider-codex'）
    
    Returns:
        tuple[str, str]: (base_url, api_key) 元组
    
    Raises:
        FileNotFoundError: platforms.yaml 文件不存在
        KeyError: 指定平台未在配置中定义
    
    Example:
        >>> url, key = load_platform_key('proxy-key')
        >>> print(f"API URL: {url}")
    """
    if not PLATFORMS_YAML.exists():
        raise FileNotFoundError(f"platforms.yaml 不存在: {PLATFORMS_YAML}")
    with open(PLATFORMS_YAML, 'r', encoding='utf-8') as f:
        cfg = yaml.safe_load(f)
    plat = cfg.get('platforms', {}).get(platform_name)
    if not plat:
        raise KeyError(f"平台 '{platform_name}' 未在 platforms.yaml 中定义")
    return plat['url'], plat['key']


# ── 8 个对比后端配置 ──────────────────────────────────────────
# 每个后端: (backend_key, model_name, display_name, platform)
# backend_key 决定从 .env.advisor 读哪组 API_KEY/BASE_URL
COMPARISON_BACKENDS = [
    # 1. GPT-5.2-high (backup provider-codex)
    {
        "id": "gpt-5.5-high",
        "backend": "openai",
        "model": "gpt-5.5-high",
        "display": "GPT-5.2-high",
        "platform": "backup provider-codex",
    },
    # 2. Claude Opus 4.6 Thinking (OpenAI-compatible proxy Claude 专用 key)
    {
        "id": "claude-opus-4-8-think",
        "backend": "claude",
        "model": "claude-opus-4-8-think",
        "display": "Claude Opus 4.6 Thinking",
        "platform": "proxy-key",
    },
    # 3. Grok 4.1 Thinking (OpenAI-compatible proxy)
    {
        "id": "grok-4.20-multi-agent-xhigh",
        "backend": "grok",
        "model": "grok-4.20-multi-agent-xhigh",
        "display": "Grok 4.1 Thinking",
        "platform": "proxy-key",
    },
    # 4. DeepSeek V3.2 (OpenAI-compatible proxy)
    {
        "id": "deepseek-v3.2",
        "backend": "deepseek",
        "model": "deepseek-ai/DeepSeek-V3.2",
        "display": "DeepSeek V3.2",
        "platform": "proxy-key",
    },
    # 5. Gemini 3 Pro (OpenAI-compatible proxy)
    {
        "id": "gemini-3-pro",
        "backend": "gemini",
        "model": "gemini-3-pro-preview",
        "display": "Gemini 3 Pro",
        "platform": "proxy-key",
    },
    # 6. qwen3.5-397b-a17b Thinking (OpenAI-compatible proxy)
    {
        "id": "qwen3-235b-thinking",
        "backend": "qwen_cloud",
        "model": "qwen/qwen3.5-397b-a17b",
        "display": "qwen3.5-397b-a17b Thinking",
        "platform": "proxy-key",
    },
    # 7. GLM 4.7 (backup provider)
    {
        "id": "glm-4.7",
        "backend": "glm",
        "model": "zai-glm-4.7",
        "display": "GLM 4.7",
        "platform": "backup provider-glm",
    },
    # 8. Kimi K2.5 (OpenAI-compatible proxy)
    {
        "id": "kimi-k2.5",
        "backend": "kimi",
        "model": "moonshotai/kimi-k2.5",
        "display": "Kimi K2.5",
        "platform": "proxy-key",
    },
]


def select_representative_chunks(chunks_path: str, count: int = 5) -> list[dict]:
    """
    从对话片段中智能选取代表性样本
    
    选取策略：
    1. 高分冲突对话（按 score 降序取第一）
    2. 冷暴力/冷处理对话（含"冷战""沉默"等关键词）
    3. 甜蜜互动对话（按 score 降序取第一）
    4. 多模态丰富对话（含语音/图片/表情标记最多的）
    5. 长文本深度对话（按文本长度降序取第一）
    
    Args:
        chunks_path (str): 对话片段 JSONL 文件路径
        count (int): 选取数量，默认 5
    
    Returns:
        tuple[list[dict], list[str]]: (选中的片段列表, 对应的标签列表)
    
    Example:
        >>> chunks, labels = select_representative_chunks("chunks.jsonl", 5)
        >>> # labels: ['conflict_high', 'cold_violence', 'sweet', 'multimodal', 'long_text']
    """
    all_chunks = []
    with open(chunks_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                all_chunks.append(json.loads(line))

    print(f"总共 {len(all_chunks)} 个 chunks，正在选取 {count} 个代表性片段...")

    # 分类
    conflict_chunks = []
    sweet_chunks = []
    multimodal_chunks = []
    long_chunks = []
    normal_chunks = []

    for c in all_chunks:
        text = c.get("conversation_text", "")
        chunk_type = c.get("chunk_type", "normal")
        text_len = len(text)

        # 检测多模态信号
        has_multimodal = any(tag in text for tag in ["[语音:", "[图片:", "[表情:", "情绪:"])

        if chunk_type == "conflict":
            conflict_chunks.append(c)
        elif chunk_type == "sweet":
            sweet_chunks.append(c)
        elif has_multimodal and text_len > 500:
            multimodal_chunks.append(c)
        elif text_len > 2000:
            long_chunks.append(c)
        else:
            normal_chunks.append(c)

    selected = []
    labels = []

    # 1. 高分冲突
    if conflict_chunks:
        # 按 score 排序取最高
        conflict_chunks.sort(key=lambda x: x.get("score", 0), reverse=True)
        selected.append(conflict_chunks[0])
        labels.append("conflict_high")
    elif normal_chunks:
        selected.append(normal_chunks[0])
        labels.append("conflict_high")

    # 2. 冷暴力/冷处理（含关键词）
    cold_keywords = ["冷处理", "不回", "不接", "冷战", "沉默", "忽略", "不理"]
    cold_chunks = [
        c for c in all_chunks
        if any(kw in c.get("conversation_text", "") for kw in cold_keywords)
    ]
    if cold_chunks:
        selected.append(cold_chunks[0])
        labels.append("cold_violence")
    elif len(conflict_chunks) > 1:
        selected.append(conflict_chunks[1])
        labels.append("cold_violence")
    elif normal_chunks:
        selected.append(normal_chunks[1] if len(normal_chunks) > 1 else normal_chunks[0])
        labels.append("cold_violence")

    # 3. 甜蜜互动
    if sweet_chunks:
        sweet_chunks.sort(key=lambda x: x.get("score", 0), reverse=True)
        selected.append(sweet_chunks[0])
        labels.append("sweet")
    elif normal_chunks:
        selected.append(normal_chunks[2] if len(normal_chunks) > 2 else normal_chunks[0])
        labels.append("sweet")

    # 4. 多模态丰富
    if multimodal_chunks:
        # 选多模态信号最多的
        def count_multimodal(c):
            text = c.get("conversation_text", "")
            return sum(text.count(tag) for tag in ["[语音:", "[图片:", "[表情:", "情绪:"])
        multimodal_chunks.sort(key=count_multimodal, reverse=True)
        selected.append(multimodal_chunks[0])
        labels.append("multimodal")
    elif normal_chunks:
        selected.append(normal_chunks[3] if len(normal_chunks) > 3 else normal_chunks[0])
        labels.append("multimodal")

    # 5. 长文本深度对话
    if long_chunks:
        long_chunks.sort(key=lambda x: len(x.get("conversation_text", "")), reverse=True)
        selected.append(long_chunks[0])
        labels.append("long_text")
    elif normal_chunks:
        selected.append(normal_chunks[4] if len(normal_chunks) > 4 else normal_chunks[0])
        labels.append("long_text")

    # 打印选取结果
    for i, (chunk, label) in enumerate(zip(selected, labels)):
        text = chunk.get("conversation_text", "")
        print(f"  [{i+1}] {label}: {chunk['chunk_id']} "
              f"(type={chunk.get('chunk_type', 'normal')}, "
              f"score={chunk.get('score', 'N/A')}, "
              f"len={len(text)})")

    return selected, labels


def create_generator(backend_cfg: dict) -> AnalysisGenerator:
    """
    为指定后端创建 AnalysisGenerator 实例
    
    API 密钥读取优先级：
    1. backend_cfg 中显式指定的 api_key
    2. platforms.yaml 中对应平台的配置
    3. 环境变量（如 OPENAI_API_KEY）
    
    Args:
        backend_cfg (dict): 后端配置字典，包含 id, backend, model, platform 等字段
    
    Returns:
        AnalysisGenerator: 配置好的分析生成器实例
    
    Example:
        >>> cfg = {"id": "gpt-5.5-high", "backend": "openai", "model": "gpt-5.5-high", "platform": "backup provider-codex"}
        >>> gen = create_generator(cfg)
    """
    # 读取 API 配置
    prefix_map = AnalysisGenerator._ENV_PREFIX
    backend_key = backend_cfg["backend"]
    prefix = prefix_map.get(backend_key, "")

    # 优先从 platforms.yaml 读取，其次环境变量
    if "api_key" in backend_cfg:
        api_key = backend_cfg["api_key"]
        base_url = backend_cfg.get("base_url", "")
    elif backend_cfg.get("platform") and PLATFORMS_YAML.exists():
        try:
            base_url, api_key = load_platform_key(backend_cfg["platform"])
        except (KeyError, FileNotFoundError):
            api_key = os.environ.get(f"{prefix}_API_KEY", "")
            base_url = os.environ.get(f"{prefix}_BASE_URL", "")
    elif "api_key_env" in backend_cfg:
        api_key = os.environ.get(backend_cfg["api_key_env"], "")
        base_url = os.environ.get(backend_cfg.get("base_url_env", ""), "")
    else:
        api_key = os.environ.get(f"{prefix}_API_KEY", "")
        base_url = os.environ.get(f"{prefix}_BASE_URL", "")

    config = {
        "backend": backend_key,
        "model": backend_cfg["model"],
        "api_key": api_key,
        "base_url": base_url,
        "temperature": 0.7,
        "rate_limit_delay": 0.5,
    }

    return AnalysisGenerator(config)


def run_single_analysis(gen: AnalysisGenerator, conversation: str, agent_type: str) -> dict:
    """
    运行单次 LLM 分析并返回结果
    
    Args:
        gen (AnalysisGenerator): 分析生成器实例
        conversation (str): 对话文本
        agent_type (str): Agent 类型（neutral/supportive/psychoanalytic）
    
    Returns:
        dict: 分析结果字典，包含：
        - success (bool): 是否成功
        - elapsed (float): 耗时（秒）
        - features (dict): 分析特征（成功时）
        - safe_context (str): 安全化的分析文本（成功时）
        - error (str): 错误信息（失败时）
    """
    start = time.time()
    try:
        result = gen.generate_analysis(conversation, agent_type)
        elapsed = time.time() - start
        if result:
            features = result.get_features_for_local()
            return {
                "success": True,
                "elapsed": elapsed,
                "features": features.model_dump(),
                "safe_context": gen.safety.sanitize_for_local(result),
                "repair_attempts": result.rationale_private.repair_attempts,
            }
        else:
            return {"success": False, "elapsed": elapsed, "error": "返回为空"}
    except Exception as e:
        elapsed = time.time() - start
        return {"success": False, "elapsed": elapsed, "error": str(e)}


def generate_chunk_markdown(
    chunk: dict, label: str, chunk_idx: int,
    results: dict, backends: list[dict],
) -> str:
    """
    生成单个 chunk 的并排对比 Markdown 报告
    
    包含对话原文（截取前 1500 字）、各后端分析结果、人工评分表。
    
    Args:
        chunk (dict): 对话片段数据
        label (str): 片段标签（如 'conflict_high'）
        chunk_idx (int): 片段序号（1-indexed）
        results (dict): 各后端分析结果，key 为 backend_id
        backends (list[dict]): 后端配置列表
    
    Returns:
        str: Markdown 格式的对比报告
    """
    text = chunk.get("conversation_text", "")
    # 截取前 1500 字展示
    display_text = text[:1500] + ("\n... (已截断)" if len(text) > 1500 else "")

    lines = []
    lines.append(f"# Chunk {chunk_idx:02d}: [{label}] — {chunk['chunk_id']}")
    lines.append("")
    lines.append(f"- **类型**: {chunk.get('chunk_type', 'normal')}")
    lines.append(f"- **评分**: {chunk.get('score', 'N/A')}")
    lines.append(f"- **长度**: {len(text)} 字")
    lines.append("")
    lines.append("## 对话原文")
    lines.append("")
    lines.append("```")
    lines.append(display_text)
    lines.append("```")
    lines.append("")
    lines.append("---")

    for i, bcfg in enumerate(backends):
        bid = bcfg["id"]
        r = results.get(bid, {})
        lines.append("")
        lines.append(f"## {i+1}. {bcfg['display']} ({bcfg['platform']})")
        lines.append("")

        if not r.get("success"):
            lines.append(f"**❌ 失败**: {r.get('error', '未知错误')}")
            lines.append(f"**耗时**: {r.get('elapsed', 0):.1f}s")
        else:
            lines.append(f"**⏱ 耗时**: {r['elapsed']:.1f}s | "
                         f"**修复次数**: {r.get('repair_attempts', 0)}")
            lines.append("")

            # 输出 safe_context（人类可读的分析结果）
            safe = r.get("safe_context", "")
            if safe:
                lines.append("### 分析结果")
                lines.append("")
                lines.append(safe)
            else:
                # fallback: 输出 features JSON
                lines.append("### 分析特征 (JSON)")
                lines.append("")
                lines.append("```json")
                lines.append(json.dumps(r.get("features", {}), ensure_ascii=False, indent=2))
                lines.append("```")

        lines.append("")
        lines.append("---")

    # 人工评分表
    lines.append("")
    lines.append("## 人工评分（0-10 分）")
    lines.append("")
    lines.append("| 后端 | 分析准确性 | 洞察深度 | 多模态理解 | 结构完整性 | 中文质量 | 总分 |")
    lines.append("|------|-----------|---------|-----------|-----------|---------|------|")
    for bcfg in backends:
        lines.append(f"| {bcfg['display']} | /10 | /10 | /10 | /10 | /10 | /50 |")

    return "\n".join(lines)


def generate_summary_report(
    chunks: list[dict], labels: list[str],
    all_results: list[dict], backends: list[dict],
) -> str:
    """
    生成汇总对比报告
    
    包含成功率+耗时概览表、人工总评分汇总表、评分维度说明、详细结果链接。
    
    Args:
        chunks (list[dict]): 选中的对话片段列表
        labels (list[str]): 对应的标签列表
        all_results (list[dict]): 所有 chunk 的后端结果列表
        backends (list[dict]): 后端配置列表
    
    Returns:
        str: Markdown 格式的汇总报告
    """
    lines = []
    lines.append("# 多模型对比报告")
    lines.append("")
    lines.append(f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"> Agent 类型: neutral")
    lines.append(f"> Chunk 数量: {len(chunks)}")
    lines.append(f"> 后端数量: {len(backends)}")
    lines.append("")

    # 概览表
    lines.append("## 1. 成功率 + 耗时概览")
    lines.append("")

    # Header
    header = "| 后端 |"
    sep = "|------|"
    for i, label in enumerate(labels):
        header += f" Chunk{i+1}({label}) |"
        sep += "------------|"
    header += " 平均耗时 | 成功率 |"
    sep += "---------|--------|"
    lines.append(header)
    lines.append(sep)

    for bcfg in backends:
        bid = bcfg["id"]
        row = f"| **{bcfg['display']}** |"
        times = []
        successes = 0
        for i, chunk_results in enumerate(all_results):
            r = chunk_results.get(bid, {})
            if r.get("success"):
                row += f" ✅ {r['elapsed']:.1f}s |"
                times.append(r["elapsed"])
                successes += 1
            else:
                err_short = r.get("error", "")[:20]
                row += f" ❌ {err_short} |"

        avg_time = sum(times) / len(times) if times else 0
        rate = f"{successes}/{len(chunks)}"
        row += f" {avg_time:.1f}s | {rate} |"
        lines.append(row)

    # 人工总评分表
    lines.append("")
    lines.append("## 2. 人工总评分汇总（0-10 分）")
    lines.append("")
    lines.append("在各 chunk 详情文件中填写后，将总分汇总到此处：")
    lines.append("")
    lines.append("| 后端 | Chunk1 | Chunk2 | Chunk3 | Chunk4 | Chunk5 | 总分 | 备注 |")
    lines.append("|------|--------|--------|--------|--------|--------|------|------|")
    for bcfg in backends:
        lines.append(f"| {bcfg['display']} | /50 | /50 | /50 | /50 | /50 | /250 | |")

    lines.append("")
    lines.append("## 3. 评分维度说明")
    lines.append("")
    lines.append("| 维度 | 0-3 分 | 4-6 分 | 7-10 分 |")
    lines.append("|------|--------|--------|---------|")
    lines.append("| **分析准确性** | 大量误读/捏造 | 基本准确有小偏差 | 精准反映对话内容 |")
    lines.append("| **洞察深度** | 流于表面/套话 | 有一定分析但不够深 | 深层动态洞察+心理学视角 |")
    lines.append("| **多模态理解** | 完全忽略语音/表情 | 提及但未整合分析 | 准确解读情绪信号并整合 |")
    lines.append("| **结构完整性** | JSON 残缺/字段缺失 | 基本完整有小瑕疵 | 所有字段齐全格式规范 |")
    lines.append("| **中文质量** | 机翻感/语法错误 | 通顺但缺少细腻 | 自然流畅有共情感 |")

    lines.append("")
    lines.append("## 4. 详细结果")
    lines.append("")
    for i, label in enumerate(labels):
        lines.append(f"- [Chunk {i+1:02d}: {label}](chunk_{i+1:02d}_{label}.md)")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="多模型对比: 5 chunks × 8 backends")
    parser.add_argument("--agent-type", type=str, default="neutral",
                        choices=["neutral", "supportive", "psychoanalytic"])
    parser.add_argument("--input", type=str, default=None,
                        help="输入 chunks 文件")
    parser.add_argument("--output-dir", type=str, default=None,
                        help="输出目录")
    parser.add_argument("--chunk-count", type=int, default=5,
                        help="选取的代表性 chunk 数量")
    parser.add_argument("--backends", type=str, nargs="*", default=None,
                        help="指定后端 ID（默认全部 8 个）")
    parser.add_argument("--start-chunk", type=int, default=1,
                        help="从第几个 chunk 开始（1-indexed，默认 1）")
    parser.add_argument("--resume", action="store_true", default=True,
                        help="跳过已成功的 chunk+backend 组合（默认开启）")

    args = parser.parse_args()

    workspace = PROJECT_ROOT
    chunks_path = args.input or str(workspace / "advisor_out" / "chunks" / "conversation_chunks.jsonl")
    output_dir = Path(args.output_dir or str(workspace / "advisor_out" / "comparison"))
    output_dir.mkdir(parents=True, exist_ok=True)

    # 筛选后端
    backends = COMPARISON_BACKENDS
    if args.backends:
        backends = [b for b in backends if b["id"] in args.backends]
        print(f"使用指定后端: {[b['id'] for b in backends]}")

    # 选取代表性 chunks
    selected_chunks, labels = select_representative_chunks(chunks_path, args.chunk_count)
    print(f"\n选取了 {len(selected_chunks)} 个代表性 chunks")

    # 对每个 chunk，逐后端生成分析
    all_chunk_results = []  # list of dicts: {backend_id: result}

    for ci, (chunk, label) in enumerate(zip(selected_chunks, labels)):
        chunk_num = ci + 1

        # --start-chunk 跳过
        if chunk_num < args.start_chunk:
            # 加载已有结果用于汇总报告
            json_path = output_dir / f"chunk_{chunk_num:02d}_{label}.json"
            if json_path.exists():
                with open(json_path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
                all_chunk_results.append(existing.get("results", {}))
                print(f"\nChunk {chunk_num}: [{label}] — 跳过 (start-chunk={args.start_chunk})")
            else:
                all_chunk_results.append({})
            continue

        print(f"\n{'='*60}")
        print(f"Chunk {chunk_num}/{len(selected_chunks)}: [{label}] {chunk['chunk_id']}")
        print(f"{'='*60}")

        conversation = chunk.get("conversation_text", "")

        # Resume: 加载已有的成功结果
        chunk_results = {}
        json_path = output_dir / f"chunk_{chunk_num:02d}_{label}.json"
        if args.resume and json_path.exists():
            with open(json_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
            chunk_results = existing.get("results", {})
            existing_ok = [bid for bid, r in chunk_results.items() if r.get("success")]
            if existing_ok:
                print(f"  已有成功结果: {existing_ok}")

        for bi, bcfg in enumerate(backends):
            bid = bcfg["id"]

            # 跳过已成功的
            if args.resume and bid in chunk_results and chunk_results[bid].get("success"):
                print(f"  [{bi+1}/{len(backends)}] {bcfg['display']} — ⏭ 跳过 (已成功)")
                continue

            print(f"  [{bi+1}/{len(backends)}] {bcfg['display']} ({bcfg['model']})...", end=" ", flush=True)

            gen = create_generator(bcfg)
            result = run_single_analysis(gen, conversation, args.agent_type)

            chunk_results[bcfg["id"]] = result

            if result["success"]:
                print(f"✅ {result['elapsed']:.1f}s")
            else:
                print(f"❌ {result.get('error', '')[:60]}")

            # 短暂间隔避免限速
            time.sleep(1.0)

        all_chunk_results.append(chunk_results)

        # 保存单个 chunk 的详情 Markdown
        md = generate_chunk_markdown(chunk, label, chunk_num, chunk_results, backends)
        md_path = output_dir / f"chunk_{chunk_num:02d}_{label}.md"
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"  → 已保存 {md_path}")

        # 同时保存 JSON 原始数据
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump({
                "chunk": {
                    "chunk_id": chunk["chunk_id"],
                    "chunk_type": chunk.get("chunk_type", "normal"),
                    "score": chunk.get("score"),
                    "text_length": len(conversation),
                },
                "results": chunk_results,
            }, f, ensure_ascii=False, indent=2)

    # 生成汇总报告
    report = generate_summary_report(selected_chunks, labels, all_chunk_results, backends)
    report_path = output_dir / "comparison_report.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\n{'='*60}")
    print(f"✅ 汇总报告已保存: {report_path}")
    print(f"请打开各 chunk_*.md 文件进行人工评分")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
