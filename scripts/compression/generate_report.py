# -*- coding: utf-8 -*-
"""
压缩统计报告生成器

生成各模态的压缩统计报告
包括压缩比、token 节省量、质量评估

用法：
    python scripts/compression/generate_report.py
    python scripts/compression/generate_report.py --output reports/compression_report.md
"""

import argparse
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
import random


def load_jsonl(path: str) -> List[Dict]:
    """加载 JSONL 文件"""
    items = []
    if Path(path).exists():
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    items.append(json.loads(line))
    return items


def estimate_tokens(text: str) -> int:
    """估算 token 数量（简单估算：中文约 1.5 字符/token）"""
    if not text:
        return 0
    # 中文字符
    chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    # 其他字符
    other_chars = len(text) - chinese_chars
    # 估算 token
    return int(chinese_chars / 1.5 + other_chars / 4)


def analyze_modality(modality: str, compressed_path: str, original_path: Optional[str] = None) -> Dict:
    """分析单个模态的压缩效果"""
    compressed = load_jsonl(compressed_path)
    
    if not compressed:
        return {
            "modality": modality,
            "count": 0,
            "error": f"文件不存在或为空: {compressed_path}"
        }
    
    # 统计
    total_original_length = 0
    total_compressed_length = 0
    compression_ratios = []
    
    for item in compressed:
        orig_len = item.get('original_length', 0)
        comp_len = item.get('compressed_length', 0)
        ratio = item.get('compression_ratio', 1.0)
        
        total_original_length += orig_len
        total_compressed_length += comp_len
        compression_ratios.append(ratio)
    
    # 计算统计值
    avg_ratio = sum(compression_ratios) / len(compression_ratios) if compression_ratios else 1.0
    max_ratio = max(compression_ratios) if compression_ratios else 1.0
    min_ratio = min(compression_ratios) if compression_ratios else 1.0
    
    # 估算 token 节省
    original_tokens = estimate_tokens('x' * total_original_length)
    compressed_tokens = estimate_tokens('x' * total_compressed_length)
    tokens_saved = original_tokens - compressed_tokens
    
    return {
        "modality": modality,
        "count": len(compressed),
        "total_original_length": total_original_length,
        "total_compressed_length": total_compressed_length,
        "avg_compression_ratio": round(avg_ratio, 2),
        "max_compression_ratio": round(max_ratio, 2),
        "min_compression_ratio": round(min_ratio, 2),
        "original_tokens_est": original_tokens,
        "compressed_tokens_est": compressed_tokens,
        "tokens_saved_est": tokens_saved,
        "space_saved_percent": round((1 - total_compressed_length / total_original_length) * 100, 1) if total_original_length > 0 else 0
    }


def sample_quality_check(compressed_path: str, sample_size: int = 5) -> List[Dict]:
    """抽样质量检查"""
    compressed = load_jsonl(compressed_path)
    
    if not compressed:
        return []
    
    # 随机抽样
    sample_size = min(sample_size, len(compressed))
    samples = random.sample(compressed, sample_size)
    
    results = []
    for item in samples:
        results.append({
            "id": item.get('msg_uid') or item.get('file'),
            "compression_ratio": item.get('compression_ratio', 1.0),
            "summary_preview": (item.get('image_summary') or 
                               item.get('video_summary') or 
                               item.get('sticker_output') or 
                               item.get('punct_text', ''))[:100]
        })
    
    return results


def generate_report(output_path: str):
    """生成压缩报告"""
    report_lines = []
    
    # 标题
    report_lines.append("# 语义压缩统计报告")
    report_lines.append(f"\n生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    # 模态配置
    modalities = {
        "image": "artifacts/before_merge/image/image_compressed.jsonl",
        "video": "artifacts/before_merge/video/video_compressed.jsonl",
        "voice": "artifacts/before_merge/voice/voice_compressed.jsonl",
        "sticker": "artifacts/before_merge/sticker/sticker_compressed.jsonl"
    }
    
    # 总体统计
    report_lines.append("## 总体统计\n")
    
    total_items = 0
    total_original = 0
    total_compressed = 0
    total_tokens_saved = 0
    
    modality_stats = []
    
    for modality, path in modalities.items():
        stats = analyze_modality(modality, path)
        modality_stats.append(stats)
        
        if 'error' not in stats:
            total_items += stats['count']
            total_original += stats['total_original_length']
            total_compressed += stats['total_compressed_length']
            total_tokens_saved += stats['tokens_saved_est']
    
    overall_ratio = total_original / total_compressed if total_compressed > 0 else 1.0
    
    report_lines.append(f"- 总处理项目: {total_items}")
    report_lines.append(f"- 原始总长度: {total_original:,} 字符")
    report_lines.append(f"- 压缩后总长度: {total_compressed:,} 字符")
    report_lines.append(f"- 总体压缩比: {overall_ratio:.2f}x")
    report_lines.append(f"- 节省空间: {(1 - total_compressed / total_original) * 100:.1f}%" if total_original > 0 else "- 节省空间: N/A")
    report_lines.append(f"- 估算节省 Token: ~{total_tokens_saved:,}")
    report_lines.append("")
    
    # 各模态详情
    report_lines.append("## 各模态详情\n")
    
    # 表格头
    report_lines.append("| 模态 | 数量 | 原始长度 | 压缩后长度 | 平均压缩比 | 节省空间 |")
    report_lines.append("|------|------|----------|------------|------------|----------|")
    
    for stats in modality_stats:
        if 'error' in stats:
            report_lines.append(f"| {stats['modality']} | - | - | - | - | {stats['error']} |")
        else:
            report_lines.append(
                f"| {stats['modality']} | {stats['count']} | "
                f"{stats['total_original_length']:,} | {stats['total_compressed_length']:,} | "
                f"{stats['avg_compression_ratio']}x | {stats['space_saved_percent']}% |"
            )
    
    report_lines.append("")
    
    # 压缩比分布
    report_lines.append("## 压缩比分布\n")
    
    for stats in modality_stats:
        if 'error' not in stats:
            report_lines.append(f"### {stats['modality'].upper()}")
            report_lines.append(f"- 最小压缩比: {stats['min_compression_ratio']}x")
            report_lines.append(f"- 平均压缩比: {stats['avg_compression_ratio']}x")
            report_lines.append(f"- 最大压缩比: {stats['max_compression_ratio']}x")
            report_lines.append("")
    
    # 质量抽样
    report_lines.append("## 质量抽样检查\n")
    
    for modality, path in modalities.items():
        samples = sample_quality_check(path, 3)
        if samples:
            report_lines.append(f"### {modality.upper()} 抽样")
            for i, sample in enumerate(samples, 1):
                report_lines.append(f"\n**样本 {i}** (压缩比: {sample['compression_ratio']}x)")
                report_lines.append(f"```")
                report_lines.append(sample['summary_preview'])
                report_lines.append(f"```")
            report_lines.append("")
    
    # 建议
    report_lines.append("## 优化建议\n")
    
    for stats in modality_stats:
        if 'error' not in stats:
            if stats['avg_compression_ratio'] < 2.0:
                report_lines.append(f"- **{stats['modality']}**: 压缩比偏低 ({stats['avg_compression_ratio']}x)，考虑调整压缩策略")
            elif stats['avg_compression_ratio'] > 20.0:
                report_lines.append(f"- **{stats['modality']}**: 压缩比很高 ({stats['avg_compression_ratio']}x)，建议检查是否丢失关键信息")
    
    # 写入文件
    report_content = '\n'.join(report_lines)
    
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(report_content)
    
    print(f"[INFO] 报告已生成: {output_path}")
    print("\n" + "="*60)
    print(report_content)


def main():
    parser = argparse.ArgumentParser(description='生成压缩统计报告')
    parser.add_argument('--output', '-o', type=str,
                        default='artifacts/compression_report.md',
                        help='输出文件路径')
    
    args = parser.parse_args()
    
    generate_report(args.output)


if __name__ == '__main__':
    main()
