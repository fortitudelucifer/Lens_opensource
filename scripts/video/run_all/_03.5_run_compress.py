# -*- coding: utf-8 -*-
"""
视频压缩脚本 - 多帧描述智能合并

功能：
- 将视频的多帧描述（5-16帧）合并为连贯摘要
- 整合音频转写和情绪标签
- 自适应合并策略（sequential/segmented/key_changes）
- 提取视频氛围和发送意图

处理流程：
1. 加载 Caption 数据（keyframe_captions + video_understanding）
2. 加载转写数据（transcription + emotion_tags）
3. 根据帧数选择合并策略：
   - ≤5帧：sequential（逐帧描述）
   - 6-10帧：segmented（分段描述：开始/过程/结束）
   - 11-16帧：key_changes（只保留关键变化帧）
4. 生成视频摘要（优先使用 video_understanding 的完整摘要）
5. 提取氛围（欢乐/悲伤/紧张/平静等）和意图（分享日常/展示成果等）
6. 计算压缩比（原始长度/压缩后长度）

输入：
- artifacts/before_merge/video/video_caption_v1.jsonl
  * msg_uid, keyframe_captions, video_understanding
- artifacts/before_merge/video/video_transcribe_v1.jsonl
  * msg_uid, transcription, emotion

输出：
- artifacts/before_merge/video/video_compressed.jsonl
  * msg_uid, video_summary, transcription, emotion_tags
  * atmosphere, intent, num_frames, merge_strategy
  * compression_ratio, original_length, compressed_length

依赖：
- scripts/compression/video_compressor.py (VideoCompressor)
- configs/compression.yaml (压缩配置)

使用示例：
    # 完整处理
    python scripts/video/run_all/_03.5_run_compress.py
    
    # 测试模式（只处理前10条）
    python scripts/video/run_all/_03.5_run_compress.py --sample 10
    
    # 自定义路径
    python scripts/video/run_all/_03.5_run_compress.py \
        --caption artifacts/before_merge/video/video_caption_v1.jsonl \
        --transcribe artifacts/before_merge/video/video_transcribe_v1.jsonl \
        --output artifacts/before_merge/video/video_compressed.jsonl

压缩策略说明：
- Sequential（≤5帧）：保留时间顺序，去除重复帧
  * 格式：开始：{描述}→{描述}→结束：{描述}
- Segmented（6-10帧）：分为开始/过程/结束三段
  * 格式：开始：{描述}→过程：{描述}→结束：{描述}
- Key Changes（11-16帧）：只保留场景变化的关键帧
  * 格式：开始：{描述}→变化：{描述}→结束：{描述}

作者：[Author]
更新于：2026-02-02
"""

import argparse
import json
import sys
from pathlib import Path
from tqdm import tqdm

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from scripts.compression.video_compressor import VideoCompressor, load_video_data, save_compressed


def main():
    """
    主函数：视频压缩流程
    
    处理步骤：
    1. 解析命令行参数
    2. 加载 Caption 和转写数据
    3. 创建 VideoCompressor 实例
    4. 逐条压缩视频（自适应合并策略）
    5. 保存压缩结果
    6. 打印统计信息（处理数、有转写数、平均帧数、平均压缩比）
    
    命令行参数：
        --caption: Caption 文件路径（默认：artifacts/before_merge/video/video_caption_v1.jsonl）
        --transcribe: 转写文件路径（默认：artifacts/before_merge/video/video_transcribe_v1.jsonl）
        --output, -o: 输出文件路径（默认：artifacts/before_merge/video/video_compressed.jsonl）
        --sample: 只处理前 N 条（测试用）
        --config, -c: 配置文件路径（默认：configs/compression.yaml）
    
    输出统计：
        - 处理总数
        - 有转写的视频数
        - 平均帧数
        - 平均压缩比（原始长度/压缩后长度）
    
    Example:
        >>> # 完整处理
        >>> python scripts/video/run_all/_03.5_run_compress.py
        [INFO] 开始视频压缩
        [INFO] 加载 150 条 caption
        [INFO] 加载 120 条转写
        压缩视频: 100%|████████| 150/150 [00:05<00:00, 30.00it/s]
        [INFO] 压缩完成
          处理: 150 条
          有转写: 120 条
          平均帧数: 8.5
          平均压缩比: 3.2x
    """
    parser = argparse.ArgumentParser(description='视频压缩')
    parser.add_argument('--caption', type=str,
                        default='artifacts/before_merge/video/video_caption_v1.jsonl',
                        help='Caption 文件路径')
    parser.add_argument('--transcribe', type=str,
                        default='artifacts/before_merge/video/video_transcribe_v1.jsonl',
                        help='转写文件路径')
    parser.add_argument('--output', '-o', type=str,
                        default='artifacts/before_merge/video/video_compressed.jsonl',
                        help='输出文件路径')
    parser.add_argument('--sample', type=int, default=None,
                        help='只处理前 N 条（测试用）')
    parser.add_argument('--config', '-c', type=str,
                        default='configs/compression.yaml',
                        help='配置文件路径')
    
    args = parser.parse_args()
    
    print("[INFO] 开始视频压缩")
    print(f"[INFO] Caption: {args.caption}")
    print(f"[INFO] 转写: {args.transcribe}")
    print(f"[INFO] 输出: {args.output}")
    
    # 检查输入文件
    if not Path(args.caption).exists():
        print(f"[ERROR] Caption 文件不存在: {args.caption}")
        return
    
    # 加载数据
    captions, transcribe_dict = load_video_data(args.caption, args.transcribe)
    print(f"[INFO] 加载 {len(captions)} 条 caption")
    print(f"[INFO] 加载 {len(transcribe_dict)} 条转写")
    
    # 限制数量（测试用）
    if args.sample:
        captions = captions[:args.sample]
        print(f"[INFO] 只处理前 {args.sample} 条")
    
    # 创建压缩器
    compressor = VideoCompressor(args.config)
    
    # 压缩
    results = []
    for caption in tqdm(captions, desc="压缩视频"):
        msg_uid = caption.get('msg_uid')
        transcribe = transcribe_dict.get(msg_uid)
        
        result = compressor.compress(caption, transcribe)
        results.append(result)
    
    # 保存结果
    save_compressed(results, args.output)
    
    # 打印统计
    stats = compressor.get_stats()
    print(f"\n[INFO] 压缩完成")
    print(f"  处理: {stats['total']} 条")
    print(f"  有转写: {stats['with_transcription']} 条")
    print(f"  平均帧数: {stats['avg_frames']}")
    print(f"  平均压缩比: {stats['avg_compression_ratio']}x")
    print(f"\n[INFO] 输出已保存到: {args.output}")


if __name__ == '__main__':
    main()
