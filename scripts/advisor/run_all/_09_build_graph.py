#!/usr/bin/env python3
"""
GraphRAG 向量索引构建脚本

功能：
- 从对话片段或 MoA 分析结果构建 BGE-M3 向量索引（FAISS）
- 支持全量构建和增量更新两种模式
- 构建用户档案（反复话题、冲突模式、关系趋势、主要情绪）
- 索引用于实时对话中的上下文检索增强

处理流程：
1. 加载对话数据（conversation_chunks.jsonl 或 MoA 分析结果）
2. 初始化 GraphRAGManager（BGE-M3 嵌入 + BGE-Reranker-V2-M3 重排）
3. 全量构建或增量更新 FAISS 向量索引
4. 保存索引到磁盘
5. 输出用户档案统计信息

输入：
- advisor_out/chunks/conversation_chunks.jsonl: 对话片段（默认）
- advisor_out/analysis/fused_analysis_neutral_moa.jsonl: MoA 分析结果（--from-analysis）

输出：
- advisor_out/vector_index/: FAISS 向量索引目录
  * index.faiss: FAISS 索引文件
  * metadata.json: 对话元数据
  * user_profile.json: 用户档案

依赖：
- scripts/advisor/graph_rag.py: GraphRAGManager
- sentence-transformers: BGE-M3 嵌入模型
- faiss: 向量索引

使用示例：
    # 全量构建索引
    python scripts/advisor/run_all/_09_build_graph.py

    # 增量更新
    python scripts/advisor/run_all/_09_build_graph.py --incremental

    # 从 MoA 分析结果构建（含 analysis_features 作为 metadata）
    python scripts/advisor/run_all/_09_build_graph.py --from-analysis

    # 禁用 GPU
    python scripts/advisor/run_all/_09_build_graph.py --no-gpu

性能参考：
- BGE-M3 编码：约 50-100 条/秒（GPU）
- 索引构建：< 1 分钟（500 条对话）
- 显存占用：约 2-3 GB（BGE-M3）

注意事项：
- 首次运行需要下载 BGE-M3 模型（约 2GB）
- 增量更新模式会在现有索引基础上追加
- 构建完成后可用于 _08_run_dialogue.py 的 GraphRAG 检索
- 单 GPU 串行策略：用完自动卸载模型释放显存

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

from scripts.advisor.graph_rag import GraphRAGManager


def load_conversations(input_path: Path) -> list[dict]:
    """
    从 JSONL 文件加载对话数据
    
    自动适配不同字段名（chunk_id/conversation_id, conversation/conversation_text）。
    
    Args:
        input_path (Path): JSONL 文件路径
    
    Returns:
        list[dict]: 对话列表，每个元素包含 conversation_id, conversation_text, 
                    timestamp, metadata
    """
    conversations = []
    with open(input_path, 'r', encoding='utf-8') as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                conversations.append({
                    'conversation_id': data.get('chunk_id', data.get('conversation_id', f'conv_{i}')),
                    'conversation_text': data.get('conversation', data.get('conversation_text', '')),
                    'timestamp': data.get('start_time', data.get('timestamp', '')),
                    'metadata': {
                        k: v for k, v in data.items()
                        if k not in ('conversation_id', 'conversation_text', 'timestamp')
                    },
                })
            except json.JSONDecodeError:
                print(f"警告：跳过第 {i+1} 行（JSON 解析失败）")
    return conversations


def main():
    parser = argparse.ArgumentParser(description='构建 GraphRAG 向量索引')
    parser.add_argument('--input', type=str, default=None,
                        help='输入对话文件路径（JSONL 格式）')
    parser.add_argument('--output', type=str, default=None,
                        help='索引输出目录')
    parser.add_argument('--incremental', action='store_true',
                        help='增量更新模式（在现有索引基础上追加）')
    parser.add_argument('--embedding-model', type=str, default='BAAI/bge-m3',
                        help='嵌入模型名称（默认 BAAI/bge-m3）')
    parser.add_argument('--reranker-model', type=str, default='BAAI/bge-reranker-v2-m3',
                        help='重排模型名称（默认 BAAI/bge-reranker-v2-m3）')
    parser.add_argument('--no-gpu', action='store_true',
                        help='禁用 GPU，使用 CPU 编码')
    parser.add_argument('--from-analysis', action='store_true',
                        help='从 MoA 分析结果文件构建索引（含 analysis_features 作为 metadata）')
    parser.add_argument('--index-type', type=str, default='auto', choices=['auto', 'flat', 'ivf', 'hnsw'],
                        help='FAISS 索引类型：auto(默认,自动选择) / flat(暴力搜索) / ivf(IVFFlat) / hnsw(预留)')

    args = parser.parse_args()

    # 确定路径
    workspace = PROJECT_ROOT
    if args.from_analysis and not args.input:
        input_path = workspace / 'advisor_out' / 'analysis' / 'fused_analysis_neutral_moa.jsonl'
    else:
        input_path = Path(args.input) if args.input else workspace / 'advisor_out' / 'chunks' / 'conversation_chunks.jsonl'
    output_dir = Path(args.output) if args.output else workspace / 'advisor_out' / 'vector_index'

    if not input_path.exists():
        print(f"错误：输入文件不存在：{input_path}")
        sys.exit(1)

    # 加载对话
    print(f"加载对话数据：{input_path}")
    conversations = load_conversations(input_path)
    print(f"共加载 {len(conversations)} 条对话")

    if not conversations:
        print("错误：无有效对话数据")
        sys.exit(1)

    # 初始化 GraphRAGManager
    config = {
        'embedding_model': args.embedding_model,
        'reranker_model': args.reranker_model,
        'index_dir': str(output_dir),
        'index_type': args.index_type,
        'use_gpu_for_embedding': not args.no_gpu,
    }
    manager = GraphRAGManager(config)

    try:
        if args.incremental:
            # 增量更新
            print(f"加载现有索引：{output_dir}")
            if not manager.load_index():
                print("警告：现有索引不存在，切换为全量构建")
                manager.build_index(conversations)
            else:
                print(f"增量更新 {len(conversations)} 条对话...")
                manager.update_index(conversations)
        else:
            # 全量构建
            print(f"全量构建索引...")
            manager.build_index(conversations)

        # 保存索引
        manager.save_index()

        # 输出统计
        profile = manager.get_user_profile()
        if profile:
            print(f"\n=== 用户档案 ===")
            print(f"总对话数：{profile.total_conversations}")
            print(f"时间范围：{profile.date_range[0]} ~ {profile.date_range[1]}")
            print(f"反复话题：{', '.join(profile.recurring_topics) or '无'}")
            print(f"反复冲突：{', '.join(profile.recurring_conflicts) or '无'}")
            print(f"关系趋势：{profile.relationship_trend}")
            print(f"主要情绪：{', '.join(profile.top_emotions) or '无'}")

        print(f"\n索引已保存到：{output_dir}")
        print("完成！")

    finally:
        # 单 GPU 串行策略：用完必须卸载
        manager.unload_models()


if __name__ == '__main__':
    main()
