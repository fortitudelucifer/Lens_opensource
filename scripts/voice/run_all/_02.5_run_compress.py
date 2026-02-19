# -*- coding: utf-8 -*-
"""
语音压缩步骤

功能：
- 压缩语音的 Qwen2-Audio 分析结果
- 保留关键推理，去除冗余信息
- 减少存储空间和 LLM 上下文消耗

处理流程：
1. 加载语音合并结果（voice_merged_v3.jsonl）
2. 对每条记录：
   - 提取 voice_analysis 字段
   - 使用 VoiceCompressor 压缩分析结果
   - 保留关键信息：情绪描述、语调特征、潜台词
   - 计算压缩比
3. 输出到 voice_compressed.jsonl

压缩策略：
- 保留核心情感信息
- 去除重复和冗余描述
- 合并相似的情绪标签
- 简化语调特征描述

输入：
- artifacts/before_merge/voice/voice_merged_v3.jsonl: 语音合并结果（含 Qwen 分析）

输出：
- artifacts/before_merge/voice/voice_compressed.jsonl: 压缩后的结果
  每条记录包含：
  - file: 文件名
  - analysis_summary: 压缩后的分析摘要
  - possible_intent: 可能的意图
  - possible_subtext: 可能的潜台词
  - compression_ratio: 压缩比

依赖：
- scripts.compression.voice_compressor: 语音压缩器
- configs/compression.yaml: 压缩配置

使用示例：
    python scripts/voice/run_all/_02.5_run_compress.py
    python scripts/voice/run_all/_02.5_run_compress.py --sample 10  # 测试模式

注意事项：
- 只压缩有 Qwen 分析的记录
- 压缩不会丢失关键信息
- 压缩比通常在 2-5x 之间

作者：forcifer
更新于：2026-02-02
"""

import argparse
import json
import sys
from pathlib import Path
from tqdm import tqdm

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from scripts.compression.voice_compressor import VoiceCompressor, load_voice_data, save_compressed


def main():
    parser = argparse.ArgumentParser(description='语音压缩')
    parser.add_argument('--input', '-i', type=str,
                        default='artifacts/before_merge/voice/voice_merged_v3.jsonl',
                        help='输入文件路径')
    parser.add_argument('--output', '-o', type=str,
                        default='artifacts/before_merge/voice/voice_compressed.jsonl',
                        help='输出文件路径')
    parser.add_argument('--sample', type=int, default=None,
                        help='只处理前 N 条（测试用）')
    parser.add_argument('--config', '-c', type=str,
                        default='configs/compression.yaml',
                        help='配置文件路径')
    
    args = parser.parse_args()
    
    print("[INFO] 开始语音压缩")
    print(f"[INFO] 输入: {args.input}")
    print(f"[INFO] 输出: {args.output}")
    
    # 检查输入文件
    if not Path(args.input).exists():
        print(f"[ERROR] 输入文件不存在: {args.input}")
        return
    
    # 加载数据
    voices = load_voice_data(args.input)
    print(f"[INFO] 加载 {len(voices)} 条语音")
    
    # 限制数量（测试用）
    if args.sample:
        voices = voices[:args.sample]
        print(f"[INFO] 只处理前 {args.sample} 条")
    
    # 创建压缩器
    compressor = VoiceCompressor(args.config)
    
    # 压缩
    results = []
    for voice in tqdm(voices, desc="压缩语音"):
        result = compressor.compress(voice)
        results.append(result)
    
    # 保存结果
    save_compressed(results, args.output)
    
    # 打印统计
    stats = compressor.get_stats()
    print(f"\n[INFO] 压缩完成")
    print(f"  处理: {stats['total']} 条")
    print(f"  有分析: {stats['with_analysis']} 条")
    print(f"  分析被移除: {stats['analysis_removed']} 条")
    print(f"  平均压缩比: {stats['avg_compression_ratio']}x")
    print(f"\n[INFO] 输出已保存到: {args.output}")


if __name__ == '__main__':
    main()
