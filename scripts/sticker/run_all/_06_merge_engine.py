#!/usr/bin/env python3
"""
表情包数据合并步骤

功能：
- 合并 7 路表情包处理数据（Download/Sniff/QC/Meta/Frames/Triage/Caption）
- 构建统一的 Schema v2 格式
- 通过 SHA256 哈希复用重复表情的分析结果（节省计算资源）
- 保留完整的回溯线索（分数、置信度、专家信息）
- 支持压缩数据（intent 字段）

处理流程：
1. 加载 7 路中间产物：
   - Download: URL 下载状态、SHA256 哈希
   - Sniff: 格式识别（Magic Bytes）
   - QC: 解码验证、尺寸信息
   - Meta: 分类（静态/动图）、帧数
   - Frames: 采样帧路径、Contact Sheet
   - Triage: NSFW/Gore 检测
   - Caption: OCR + VLM 描述
2. 加载压缩数据（可选）：
   - Compressed: 意图标签（intent）、摘要
3. 构建 SHA256 索引：
   - 为重复表情复用已有的分析结果
   - 避免重复计算（节省 GPU 资源）
4. 对每条消息：
   a. 使用 build_common_header 构建公共字段
   b. 合并表情包特定字段
   c. 优先使用 msg_uid 匹配，无数据时通过 SHA256 复用
   d. 使用 reorder_record 重排字段顺序
5. 输出最终合并文件和统计信息

SHA256 复用机制：
- 表情包 URL 可能不同，但内容相同（SHA256 相同）
- 对于重复表情，只需处理一次（OCR/Caption/Triage）
- 其他消息通过 SHA256 索引复用结果
- 大幅减少 GPU 计算量（尤其是热门表情包）

输出字段设计原则：
1. **保留所有关键线索**：便于回溯和分析
2. **下载信息**：url, file_sha256, http_status, bytes
3. **格式信息**：detected_format, content_type_reported, mismatch
4. **QC 信息**：decode_ok, width, height
5. **分类信息**：sticker_class, is_animated, n_frames
6. **产物路径**：thumb_path, frame_paths, contact_sheet_path
7. **Triage 信息**：content_type, max_nsfw_score, is_sensitive
8. **Caption 信息**：caption, ocr_text, expert_used
9. **意图信息**：intent, intent_confidence, sticker_summary

Schema 版本：
- merged_v2: 统一字段结构
- 公共字段：schema_version, msg_uid, ts, speaker, type, modality, media_path
- 表情包字段：url, file_sha256, detected_format, caption, intent, etc.

输入：
- artifacts/before_merge/sticker/sticker_download_v1.jsonl: 下载结果
- artifacts/before_merge/sticker/sticker_sniff_v1.jsonl: 格式识别
- artifacts/before_merge/sticker/sticker_decode_qc_v1.jsonl: QC 结果
- artifacts/before_merge/sticker/sticker_meta_v1.jsonl: 元数据
- artifacts/before_merge/sticker/sticker_frames_v1.jsonl: 帧提取
- artifacts/before_merge/sticker/sticker_triage_v1.jsonl: Triage 结果
- artifacts/before_merge/sticker/sticker_caption_v1.jsonl: Caption 结果
- artifacts/before_merge/sticker/sticker_compressed.jsonl: 压缩结果（可选）

输出：
- artifacts/after_merge/sticker/sticker_merged_final.jsonl: 最终合并文件

依赖：
- scripts/_common/schema_utils.py: Schema 工具
- scripts/_common/jsonl_utils.py: JSONL 工具
- scripts/_common/path_utils.py: 路径工具

使用示例：
    python scripts/sticker/run_all/_06_merge_engine.py

输出统计：
- 总记录数
- 解码成功数
- 动图数量
- 敏感内容数量
- 有描述的记录数
- 有意图的记录数
- SHA256 复用数量

作者：forcifer
更新于：2026-02-02
"""

import os
import sys
import argparse
import logging
from pathlib import Path
from typing import Dict, List, Optional

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from scripts._common.path_utils import (
    get_sticker_before_merge, get_sticker_after_merge
)
from scripts._common.jsonl_utils import load_jsonl_by_key, write_jsonl
from scripts._common.schema_utils import (
    SCHEMA_VERSION,
    build_common_header,
    reorder_record,
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def main():
    """
    主函数：执行表情包数据合并
    
    流程：
    1. 加载 7 路中间产物（Download/Sniff/QC/Meta/Frames/Triage/Caption）
    2. 加载压缩数据（可选）
    3. 构建 SHA256 索引（用于复用重复表情的分析结果）
    4. 对每条消息：
       - 构建公共字段（使用 build_common_header）
       - 合并表情包特定字段
       - 优先使用 msg_uid 匹配，无数据时通过 SHA256 复用
       - 重排字段顺序（使用 reorder_record）
    5. 输出最终合并文件
    6. 打印统计信息（包括 SHA256 复用数量）
    
    SHA256 复用机制：
        - 表情包 URL 可能不同，但内容相同（SHA256 相同）
        - 对于重复表情，只需处理一次（OCR/Caption/Triage）
        - 其他消息通过 SHA256 索引复用结果
        - 大幅减少 GPU 计算量（尤其是热门表情包）
    
    输出统计：
        - 总记录数
        - 解码成功数
        - 动图数量
        - 敏感内容数量
        - 有描述的记录数
        - 有意图的记录数
        - SHA256 复用数量
    """
    parser = argparse.ArgumentParser(description='表情包合并')
    args = parser.parse_args()
    
    # 设置路径
    before_dir = get_sticker_before_merge()
    after_dir = get_sticker_after_merge()
    after_dir.mkdir(parents=True, exist_ok=True)
    
    # 加载所有中间产物
    logger.info("加载中间产物...")
    
    download_data = load_jsonl_by_key(str(before_dir / "sticker_download_v1.jsonl"), 'msg_uid')
    sniff_data = load_jsonl_by_key(str(before_dir / "sticker_sniff_v1.jsonl"), 'msg_uid')
    qc_data = load_jsonl_by_key(str(before_dir / "sticker_decode_qc_v1.jsonl"), 'msg_uid')
    meta_data = load_jsonl_by_key(str(before_dir / "sticker_meta_v1.jsonl"), 'msg_uid')
    frames_data = load_jsonl_by_key(str(before_dir / "sticker_frames_v1.jsonl"), 'msg_uid')
    triage_data = load_jsonl_by_key(str(before_dir / "sticker_triage_v1.jsonl"), 'msg_uid')
    caption_data = load_jsonl_by_key(str(before_dir / "sticker_caption_v1.jsonl"), 'msg_uid')
    
    # 加载压缩数据（包含 intent 字段）
    compressed_file = before_dir / "sticker_compressed.jsonl"
    compressed_data = {}
    if compressed_file.exists():
        compressed_data = load_jsonl_by_key(str(compressed_file), 'msg_uid')
        logger.info(f"Compressed: {len(compressed_data)}")
    else:
        logger.warning(f"压缩文件不存在: {compressed_file}，跳过 intent 字段")
    
    logger.info(f"Download: {len(download_data)}, Sniff: {len(sniff_data)}, QC: {len(qc_data)}")
    logger.info(f"Meta: {len(meta_data)}, Frames: {len(frames_data)}, Triage: {len(triage_data)}")
    logger.info(f"Caption: {len(caption_data)}")
    
    # 构建 SHA256 -> caption 映射，用于复用重复表情的描述
    sha256_to_caption = {}
    for msg_uid, caption in caption_data.items():
        sha256 = caption.get('file_sha256')
        if sha256 and caption.get('caption'):
            sha256_to_caption[sha256] = caption
    
    # 构建 SHA256 -> compressed 映射，用于复用重复表情的意图
    sha256_to_compressed = {}
    for msg_uid, compressed in compressed_data.items():
        sha256 = compressed.get('file_sha256')
        if sha256 and compressed.get('intent'):
            sha256_to_compressed[sha256] = compressed
    
    # 构建 SHA256 -> 其他数据的映射，用于复用重复表情的元数据
    sha256_to_meta = {}
    sha256_to_frames = {}
    sha256_to_triage = {}
    sha256_to_sniff = {}
    sha256_to_qc = {}
    
    for msg_uid, meta in meta_data.items():
        sha256 = meta.get('file_sha256')
        if sha256:
            sha256_to_meta[sha256] = meta
    
    for msg_uid, frames in frames_data.items():
        sha256 = frames.get('file_sha256')
        if sha256:
            sha256_to_frames[sha256] = frames
    
    for msg_uid, triage in triage_data.items():
        sha256 = triage.get('file_sha256')
        if sha256:
            sha256_to_triage[sha256] = triage
    
    for msg_uid, sniff in sniff_data.items():
        sha256 = sniff.get('file_sha256')
        if sha256:
            sha256_to_sniff[sha256] = sniff
    
    for msg_uid, qc in qc_data.items():
        sha256 = qc.get('file_sha256')
        if sha256:
            sha256_to_qc[sha256] = qc
    
    logger.info(f"SHA256 去重: {len(sha256_to_caption)} 个唯一表情有描述")
    
    # 以 download 为基准合并
    merged_results = []
    reused_count = 0
    
    for msg_uid, download in download_data.items():
        file_sha256 = download.get('file_sha256')
        
        # 优先使用 msg_uid 匹配，如果没有则通过 SHA256 复用
        sniff = sniff_data.get(msg_uid, {})
        qc = qc_data.get(msg_uid, {})
        meta = meta_data.get(msg_uid, {})
        frames = frames_data.get(msg_uid, {})
        triage = triage_data.get(msg_uid, {})
        caption = caption_data.get(msg_uid, {})
        compressed = compressed_data.get(msg_uid, {})
        
        # 如果当前 msg_uid 没有数据，尝试通过 SHA256 复用
        is_reused = False
        if file_sha256:
            if not sniff and file_sha256 in sha256_to_sniff:
                sniff = sha256_to_sniff[file_sha256]
                is_reused = True
            if not qc and file_sha256 in sha256_to_qc:
                qc = sha256_to_qc[file_sha256]
                is_reused = True
            if not meta and file_sha256 in sha256_to_meta:
                meta = sha256_to_meta[file_sha256]
                is_reused = True
            if not frames and file_sha256 in sha256_to_frames:
                frames = sha256_to_frames[file_sha256]
                is_reused = True
            if not triage and file_sha256 in sha256_to_triage:
                triage = sha256_to_triage[file_sha256]
                is_reused = True
            if not caption and file_sha256 in sha256_to_caption:
                caption = sha256_to_caption[file_sha256]
                is_reused = True
            if not compressed and file_sha256 in sha256_to_compressed:
                compressed = sha256_to_compressed[file_sha256]
                is_reused = True
        
        if is_reused:
            reused_count += 1
        
        # 使用 build_common_header 构建公共字段
        merged = build_common_header(
            raw_record=download,
            schema_version=SCHEMA_VERSION,
            msg_uid=msg_uid,
            modality='sticker',
        )
        
        # 添加 sticker 特定字段
        merged.update({
            # 下载信息
            "url": download.get('url'),
            "file_sha256": download.get('file_sha256'),
            "http_status": download.get('http_status'),
            "bytes": download.get('bytes'),
            
            # 格式信息
            "detected_format": sniff.get('detected_format'),
            "content_type_reported": sniff.get('content_type_reported'),
            "mismatch": sniff.get('mismatch'),
            "final_path": sniff.get('final_path'),
            
            # QC 信息
            "decode_ok": qc.get('decode_ok'),
            "width": qc.get('width'),
            "height": qc.get('height'),
            
            # 分类信息
            "sticker_class": meta.get('sticker_class'),
            "is_animated": meta.get('is_animated'),
            "n_frames": meta.get('n_frames'),
            
            # 产物路径
            "thumb_path": meta.get('thumb_path'),
            "frame_paths": frames.get('frame_paths', []),
            "contact_sheet_path": frames.get('contact_sheet_path'),
            "n_sampled": frames.get('n_sampled'),
            "sample_indices": frames.get('sample_indices'),
            
            # Triage 信息
            "content_type": triage.get('content_type', 'TYPE_C_NORMAL'),
            "max_nsfw_score": triage.get('max_nsfw_score', 0.0),
            "max_gore_score": triage.get('max_gore_score', 0.0),
            "is_sensitive": triage.get('is_sensitive', False),
            "trigger_frames": triage.get('trigger_frames', []),
            
            # Caption 信息
            "caption": caption.get('caption', ''),
            "ocr_text": caption.get('ocr_text', ''),
            "expert_used": caption.get('expert_used', ''),
            
            # 压缩/意图信息
            "intent": compressed.get('intent', ''),
            "intent_confidence": compressed.get('intent_confidence', 0.0),
            "sticker_summary": compressed.get('sticker_summary', '')
        })
        
        # 使用 reorder_record 重排字段顺序
        merged = reorder_record(merged, 'sticker')
        
        merged_results.append(merged)
    
    # 统计
    total = len(merged_results)
    decode_ok = sum(1 for m in merged_results if m.get('decode_ok'))
    animated = sum(1 for m in merged_results if m.get('is_animated'))
    sensitive = sum(1 for m in merged_results if m.get('is_sensitive'))
    with_caption = sum(1 for m in merged_results if m.get('caption'))
    with_intent = sum(1 for m in merged_results if m.get('intent'))
    
    logger.info(f"合并统计:")
    logger.info(f"  总数: {total}")
    logger.info(f"  解码成功: {decode_ok}")
    logger.info(f"  动图: {animated}")
    logger.info(f"  敏感内容: {sensitive}")
    logger.info(f"  有描述: {with_caption}")
    logger.info(f"  有意图: {with_intent}")
    logger.info(f"  复用重复表情: {reused_count}")
    
    # 保存结果
    output_path = after_dir / "sticker_merged_final.jsonl"
    write_jsonl(str(output_path), merged_results)
    logger.info(f"合并结果已保存到: {output_path}")


if __name__ == '__main__':
    main()
