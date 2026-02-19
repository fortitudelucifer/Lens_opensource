# -*- coding: utf-8 -*-
"""
图片语义压缩步骤

功能：
- 将图片的 caption 和 OCR 文本压缩为简洁摘要
- 针对不同类型图片采用不同压缩策略
- 保留关键信息，去除冗余描述
- 为 LLM 训练数据优化 token 使用

处理流程：
1. 加载 caption 结果（image_caption_v1.jsonl）
2. 加载 OCR 结果（image_ocr_v1.jsonl）
3. 加载 QC 数据，找出 TEXT_PRIMARY 但无 caption 的图片
4. 对每张图片：
   a. 根据类型选择压缩策略
   b. 合并 caption 和 OCR 信息
   c. 生成简洁摘要
5. 输出压缩结果

压缩策略：
- **敏感内容（NSFW/Gore）**：
  * 保留关键描述，去除过度细节
  * 压缩比：~2-3x
  
- **TEXT_PRIMARY（文字为主）**：
  * 优先保留 OCR 文本
  * Caption 作为补充说明
  * 压缩比：~1.5-2x
  
- **普通图片**：
  * 提取核心场景和主体
  * 去除冗余修饰词
  * 压缩比：~2-4x

输入：
- artifacts/before_merge/image/image_caption_v1.jsonl: Caption 结果
- artifacts/before_merge/image/image_ocr_v1.jsonl: OCR 结果
- artifacts/before_merge/image/image_qc_v1.jsonl: QC 数据（用于 TEXT_PRIMARY）

输出：
- artifacts/before_merge/image/image_compressed.jsonl: 压缩后的摘要
  * 包含：msg_uid, image_summary, compression_ratio, original_length

依赖：
- scripts/compression/image_compressor.py: 图片压缩器
- configs/compression.yaml: 压缩配置

使用示例：
    # 完整运行
    python scripts/image/run_all/_02.5_run_compress.py
    
    # 测试模式（仅处理前 10 条）
    python scripts/image/run_all/_02.5_run_compress.py --sample 10
    
    # 自定义路径
    python scripts/image/run_all/_02.5_run_compress.py \
        --caption path/to/caption.jsonl \
        --ocr path/to/ocr.jsonl \
        --output path/to/output.jsonl

压缩效果：
- 平均压缩比：2-3x
- 信息保留率：>90%
- 适用场景：LLM 训练数据、RAG 检索

注意事项：
- 确保先运行 _01_run_ocr.py 和 _02_run_caption.py
- TEXT_PRIMARY 图片即使无 caption 也会被处理
- 压缩不会丢失关键信息，只是更简洁

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

from scripts.compression.image_compressor import ImageCompressor, load_image_data, save_compressed


def load_qc_data(qc_path: str) -> dict:
    """
    加载 QC 数据
    
    Args:
        qc_path: QC 文件路径
    
    Returns:
        msg_uid -> qc_data 的映射字典
    
    Example:
        >>> qc_dict = load_qc_data("image_qc_v1.jsonl")
        >>> print(len(qc_dict))
    """
    qc_dict = {}
    path = Path(qc_path)
    if not path.exists():
        return qc_dict
    
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                data = json.loads(line)
                msg_uid = data.get('msg_uid')
                if msg_uid:
                    qc_dict[msg_uid] = data
    return qc_dict


def main():
    """
    主函数：执行图片语义压缩
    
    流程：
    1. 解析命令行参数
    2. 加载 caption、OCR、QC 数据
    3. 识别 TEXT_PRIMARY 无 caption 的图片
    4. 批量压缩：
       - 有 caption 的图片
       - TEXT_PRIMARY 无 caption 的图片
    5. 保存压缩结果和统计信息
    
    命令行参数：
        --caption: Caption 文件路径
        --ocr: OCR 文件路径
        --qc: QC 文件路径
        --output: 输出文件路径
        --sample: 仅处理前 N 条（测试用）
        --config: 压缩配置文件路径
    
    输出统计：
        - 总处理数
        - 敏感内容数
        - 文字为主图片数
        - 平均压缩比
    """
    parser = argparse.ArgumentParser(description='图片压缩')
    parser.add_argument('--caption', type=str,
                        default='artifacts/before_merge/image/image_caption_v1.jsonl',
                        help='Caption 文件路径')
    parser.add_argument('--ocr', type=str,
                        default='artifacts/before_merge/image/image_ocr_v1.jsonl',
                        help='OCR 文件路径')
    parser.add_argument('--qc', type=str,
                        default='artifacts/before_merge/image/image_qc_v1.jsonl',
                        help='QC 文件路径（用于 TEXT_PRIMARY 图片）')
    parser.add_argument('--output', '-o', type=str,
                        default='artifacts/before_merge/image/image_compressed.jsonl',
                        help='输出文件路径')
    parser.add_argument('--sample', type=int, default=None,
                        help='只处理前 N 条（测试用）')
    parser.add_argument('--config', '-c', type=str,
                        default='configs/compression.yaml',
                        help='配置文件路径')
    
    args = parser.parse_args()
    
    print("[INFO] 开始图片压缩")
    print(f"[INFO] Caption: {args.caption}")
    print(f"[INFO] OCR: {args.ocr}")
    print(f"[INFO] QC: {args.qc}")
    print(f"[INFO] 输出: {args.output}")
    
    # 加载数据
    captions, ocr_dict = load_image_data(args.caption, args.ocr)
    print(f"[INFO] 加载 {len(captions)} 条 caption")
    print(f"[INFO] 加载 {len(ocr_dict)} 条 OCR")
    
    # 加载 QC 数据，找出 TEXT_PRIMARY 但没有 caption 的图片
    qc_dict = load_qc_data(args.qc)
    print(f"[INFO] 加载 {len(qc_dict)} 条 QC")
    
    # 找出已有 caption 的 msg_uid
    caption_uids = {c.get('msg_uid') for c in captions}
    
    # 找出 TEXT_PRIMARY 且没有 caption 的图片
    text_primary_no_caption = []
    for msg_uid, qc_data in qc_dict.items():
        if qc_data.get('route_class') == 'TEXT_PRIMARY' and msg_uid not in caption_uids:
            # 从 QC 数据构建 image_data
            ocr_result = qc_data.get('ocr_result', {})
            image_data = {
                'msg_uid': msg_uid,
                'media_path': qc_data.get('media_path'),
                'caption': '',  # 无 caption
                'route_class': 'TEXT_PRIMARY',
                'content_type': 'TYPE_C_NORMAL',
            }
            # OCR 数据
            ocr_data = {
                'msg_uid': msg_uid,
                'full_text': ocr_result.get('full_text', ''),
            }
            text_primary_no_caption.append((image_data, ocr_data))
    
    print(f"[INFO] 发现 {len(text_primary_no_caption)} 条 TEXT_PRIMARY 无 caption 图片")
    
    # 限制数量（测试用）
    if args.sample:
        captions = captions[:args.sample]
        print(f"[INFO] 只处理前 {args.sample} 条 caption")
    
    # 创建压缩器
    compressor = ImageCompressor(args.config)
    
    # 压缩有 caption 的图片
    results = []
    for caption in tqdm(captions, desc="压缩图片(有caption)"):
        msg_uid = caption.get('msg_uid')
        ocr = ocr_dict.get(msg_uid)
        
        result = compressor.compress(caption, ocr)
        results.append(result)
    
    # 压缩 TEXT_PRIMARY 无 caption 的图片
    for image_data, ocr_data in tqdm(text_primary_no_caption, desc="压缩图片(TEXT_PRIMARY)"):
        result = compressor.compress(image_data, ocr_data)
        results.append(result)
    
    # 保存结果
    save_compressed(results, args.output)
    
    # 打印统计
    stats = compressor.get_stats()
    print(f"\n[INFO] 压缩完成")
    print(f"  处理: {stats['total']} 条")
    print(f"  敏感内容: {stats['sensitive_count']} 条")
    print(f"  文字为主: {stats['text_primary_count']} 条")
    print(f"  平均压缩比: {stats['avg_compression_ratio']}x")
    print(f"\n[INFO] 输出已保存到: {args.output}")


if __name__ == '__main__':
    main()
