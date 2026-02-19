# -*- coding: utf-8 -*-
"""
表情包压缩脚本 - Caption 和 OCR 文字压缩为意图标签

功能：
- 将表情包的 caption 和 ocr_text 压缩为意图标签
- 支持表情包字典构建（可选）
- 从字典引用常见表情包

处理流程：
1. 加载 Caption 数据（sticker_caption_v1.jsonl）
2. 创建 StickerCompressor 实例
3. 逐条压缩表情包：
   - 提取意图标签
   - 压缩描述文本
   - 从字典引用（如果存在）
4. 保存压缩结果
5. 构建字典（可选）

输入：
- artifacts/before_merge/sticker/sticker_caption_v1.jsonl
  * msg_uid, caption, ocr_text, is_animated

输出：
- artifacts/before_merge/sticker/sticker_compressed.jsonl
  * msg_uid, intent_tags, compressed_caption, from_lexicon

依赖：
- scripts/compression/sticker_compressor.py (StickerCompressor)
- configs/compression.yaml (压缩配置)

使用示例：
    # 完整处理
    python scripts/sticker/run_all/_05.5_run_compress.py
    
    # 测试模式（只处理前10条）
    python scripts/sticker/run_all/_05.5_run_compress.py --sample 10
    
    # 构建表情包字典
    python scripts/sticker/run_all/_05.5_run_compress.py --build-lexicon
    
    # 自定义路径
    python scripts/sticker/run_all/_05.5_run_compress.py \
        --input artifacts/before_merge/sticker/sticker_caption_v1.jsonl \
        --output artifacts/before_merge/sticker/sticker_compressed.jsonl

压缩策略：
- 意图标签提取：从 caption 中提取关键词
- 描述压缩：移除冗余文字，保留核心信息
- 字典引用：常见表情包从字典中引用（节省存储）

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

from scripts.compression.sticker_compressor import StickerCompressor


def load_sticker_data(input_path: str):
    """
    加载表情包数据
    
    Args:
        input_path: 输入文件路径（JSONL 格式）
    
    Returns:
        表情包数据列表
    
    Example:
        >>> stickers = load_sticker_data("sticker_caption_v1.jsonl")
        >>> print(len(stickers))
        480
    """
    stickers = []
    with open(input_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                stickers.append(json.loads(line))
    return stickers


def save_compressed(stickers, output_path: str):
    """
    保存压缩结果
    
    Args:
        stickers: 压缩后的表情包数据列表
        output_path: 输出文件路径（JSONL 格式）
    
    Example:
        >>> save_compressed(compressed_stickers, "sticker_compressed.jsonl")
    """
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        for sticker in stickers:
            f.write(json.dumps(sticker, ensure_ascii=False) + '\n')


def main():
    """
    主函数：表情包压缩流程
    
    处理步骤：
    1. 解析命令行参数
    2. 加载表情包数据
    3. 创建 StickerCompressor 实例
    4. 逐条压缩表情包
    5. 保存压缩结果
    6. 构建字典（可选）
    7. 打印统计信息（处理数、压缩数、从字典引用数）
    
    命令行参数：
        --input, -i: 输入文件路径
        --output, -o: 输出文件路径
        --sample: 只处理前 N 条（测试用）
        --config, -c: 配置文件路径
        --build-lexicon: 构建表情包字典
    
    输出统计：
        - 处理总数
        - 压缩数
        - 从字典引用数
    
    Example:
        >>> python scripts/sticker/run_all/_05.5_run_compress.py --sample 10
        [INFO] 开始表情包压缩
        [INFO] 输入: artifacts/before_merge/sticker/sticker_caption_v1.jsonl
        [INFO] 输出: artifacts/before_merge/sticker/sticker_compressed.jsonl
        [INFO] 加载 480 条表情包
        [INFO] 只处理前 10 条
        压缩表情包: 100%|████████| 10/10 [00:01<00:00, 10.00it/s]
        
        [INFO] 压缩完成
          处理: 10 条
          压缩: 10 条
          从字典引用: 2 条
        
        [INFO] 输出已保存到: artifacts/before_merge/sticker/sticker_compressed.jsonl
    """
    parser = argparse.ArgumentParser(description='表情包压缩')
    parser.add_argument('--input', '-i', type=str,
                        default='artifacts/before_merge/sticker/sticker_caption_v1.jsonl',
                        help='输入文件路径')
    parser.add_argument('--output', '-o', type=str,
                        default='artifacts/before_merge/sticker/sticker_compressed.jsonl',
                        help='输出文件路径')
    parser.add_argument('--sample', type=int, default=None,
                        help='只处理前 N 条（测试用）')
    parser.add_argument('--config', '-c', type=str,
                        default='configs/compression.yaml',
                        help='配置文件路径')
    parser.add_argument('--build-lexicon', action='store_true',
                        help='构建表情包字典')
    
    args = parser.parse_args()
    
    print("[INFO] 开始表情包压缩")
    print(f"[INFO] 输入: {args.input}")
    print(f"[INFO] 输出: {args.output}")
    
    # 检查输入文件
    if not Path(args.input).exists():
        print(f"[ERROR] 输入文件不存在: {args.input}")
        return
    
    # 加载数据
    stickers = load_sticker_data(args.input)
    print(f"[INFO] 加载 {len(stickers)} 条表情包")
    
    # 限制数量（测试用）
    if args.sample:
        stickers = stickers[:args.sample]
        print(f"[INFO] 只处理前 {args.sample} 条")
    
    # 创建压缩器
    compressor = StickerCompressor(args.config)
    
    # 压缩
    results = []
    for sticker in tqdm(stickers, desc="压缩表情包"):
        result = compressor.compress(sticker)
        results.append(result)
    
    # 保存结果
    save_compressed(results, args.output)
    
    # 构建字典（可选）
    if args.build_lexicon:
        print("\n[INFO] 构建表情包字典...")
        compressor.save_lexicon()
        print(f"[INFO] 字典已保存")
    
    # 打印统计
    stats = compressor.get_stats()
    print(f"\n[INFO] 压缩完成")
    print(f"  处理: {stats['total']} 条")
    print(f"  压缩: {stats['compressed']} 条")
    print(f"  从字典引用: {stats['from_lexicon']} 条")
    print(f"\n[INFO] 输出已保存到: {args.output}")


if __name__ == '__main__':
    main()
