#!/usr/bin/env python3
"""
图片数据合并步骤

功能：
- 合并 QC、OCR、Caption、Compress 四路数据
- 构建统一的 Schema v2 格式
- 保留完整的回溯线索（分数、置信度、专家信息）
- 生成按路由分类的中间文件（用于调试）

处理流程：
1. 加载原始消息（获取基础字段）
2. 加载四路数据：
   - QC: 质量检查和路由分类
   - OCR: 文字识别结果
   - Caption: 图片描述（含专家元数据）
   - Compress: 语义压缩结果
3. 对每条消息：
   a. 使用 build_common_header 构建公共字段
   b. 合并图片特定字段
   c. 使用 reorder_record 重排字段顺序
4. 按时间戳排序
5. 输出最终合并文件和分类中间文件

输出字段设计原则：
1. **保留所有关键线索**：便于回溯和分析
2. **专家信息**：content_type, expert_used, triage_confidence
3. **分数/元数据**：nsfw_score, sfw_score, text_score
4. **Caption**：动作/对象/部位/场景等关键事实
5. **OCR**：政治符号/标语/仇恨口号/组织标识等硬证据

Schema 版本：
- merged_v2: 统一字段结构
- 公共字段：schema_version, msg_uid, ts, speaker, type, modality, media_path
- 图片字段：route_class, content_type, caption, ocr_text, nsfw_score, etc.

输入：
- artifacts/before_merge/image/image_qc_v1.jsonl: QC 结果
- artifacts/before_merge/image/image_ocr_v1.jsonl: OCR 结果
- artifacts/before_merge/image/image_caption_v1.jsonl: Caption 结果
- artifacts/before_merge/image/image_compressed.jsonl: 压缩结果（可选）
- raw/P1_messages_raw.jsonl: 原始消息

输出：
- artifacts/after_merge/image/image_merged_final.jsonl: 最终合并文件
- artifacts/before_merge/image/by_class/*.jsonl: 按路由分类的中间文件

依赖：
- scripts/_common/schema_utils.py: Schema 工具
- scripts/_common/jsonl_utils.py: JSONL 工具

使用示例：
    python scripts/image/run_all/_03_merge_engine.py

输出统计：
- 总记录数
- 有 OCR 的记录数
- 有 Caption 的记录数
- NSFW Fallback 数量
- 专家使用分布
- 内容类型分布

作者：[Author]
更新于：2026-02-02
"""

import os
import sys
import json
import logging
from pathlib import Path
from tqdm import tqdm

# 确保 tqdm 输出到 stderr 以便实时显示
tqdm_kwargs = {"file": sys.stderr, "dynamic_ncols": True}

# Setup paths
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts._common.path_utils import PATHS
from scripts._common.jsonl_utils import load_jsonl_by_key
from scripts._common.schema_utils import (
    SCHEMA_VERSION,
    build_common_header,
    reorder_record,
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def main():
    """
    主函数：执行图片数据合并
    
    流程：
    1. 加载原始消息和四路数据（QC/OCR/Caption/Compress）
    2. 对每条消息：
       - 构建公共字段（使用 build_common_header）
       - 合并图片特定字段
       - 重排字段顺序（使用 reorder_record）
    3. 按时间戳排序
    4. 生成分类中间文件（by_class/*.jsonl）
    5. 输出最终合并文件
    6. 打印统计信息
    
    输出统计：
        - 总记录数
        - 有 OCR/Caption 的记录数
        - NSFW Fallback 数量
        - 专家使用分布
        - 内容类型分布
    """
    # Paths
    before_merge = PATHS.get('artifacts', {}).get('image_before', f'{PROJECT_ROOT}/artifacts/before_merge/image')
    after_merge = PATHS.get('artifacts', {}).get('image_after', f'{PROJECT_ROOT}/artifacts/after_merge/image')
    raw_messages_file = PATHS.get('raw', {}).get('messages', f'{PROJECT_ROOT}/raw/P1_messages_raw.jsonl')
    
    qc_file = os.path.join(before_merge, 'image_qc_v1.jsonl')
    ocr_file = os.path.join(before_merge, 'image_ocr_v1.jsonl')
    caption_file = os.path.join(before_merge, 'image_caption_v1.jsonl')
    compressed_file = os.path.join(before_merge, 'image_compressed.jsonl')  # 压缩后的数据
    output_file = os.path.join(after_merge, 'image_merged_final.jsonl')
    
    os.makedirs(after_merge, exist_ok=True)
    
    # Load raw messages for original fields
    logger.info("Loading raw messages...")
    raw_messages = load_jsonl_by_key(raw_messages_file)
    logger.info(f"  Loaded {len(raw_messages)} raw message records")
    
    # Load all data
    logger.info("Loading QC data...")
    qc_data = load_jsonl_by_key(qc_file)
    logger.info(f"  Loaded {len(qc_data)} QC records")
    
    logger.info("Loading OCR data...")
    ocr_data = load_jsonl_by_key(ocr_file)
    logger.info(f"  Loaded {len(ocr_data)} OCR records")
    
    logger.info("Loading Caption data...")
    caption_data = load_jsonl_by_key(caption_file) if os.path.exists(caption_file) else {}
    logger.info(f"  Loaded {len(caption_data)} Caption records")
    
    # Load compressed data (if exists)
    logger.info("Loading Compressed data...")
    compressed_data = load_jsonl_by_key(compressed_file) if os.path.exists(compressed_file) else {}
    if compressed_data:
        logger.info(f"  ✅ Loaded {len(compressed_data)} Compressed records")
    else:
        logger.info(f"  ⚠️ No compressed data found, using original captions")
    
    # Merge
    logger.info("Merging data...")
    all_items = []
    
    for msg_uid, qc_item in tqdm(qc_data.items(), desc="合并记录", **tqdm_kwargs):
        ocr_item = ocr_data.get(msg_uid, {})
        caption_item = caption_data.get(msg_uid, {})
        compressed_item = compressed_data.get(msg_uid, {})
        raw_record = raw_messages.get(msg_uid, {})
        
        # 提取 caption 元数据（来自 ExpertRouter）
        caption_metadata = caption_item.get('metadata', {})
        
        # 使用 build_common_header 构建公共字段
        merged = build_common_header(
            raw_record=raw_record,
            schema_version=SCHEMA_VERSION,
            msg_uid=msg_uid,
            media_path=qc_item.get('media_path'),
            modality='image',
        )
        
        # 添加 image 特定字段
        merged.update({
            # === 路由分类 (L1/L2 Router) ===
            'route_class': qc_item.get('route_class'),
            
            # === 内容分类 (Triage) ===
            'content_type': caption_item.get('content_type', ''),
            'triage_confidence': caption_item.get('triage_confidence', 0.0),
            
            # === 分数/置信度 (关键回溯线索) ===
            'nsfw_score': caption_metadata.get('nsfw_score', 0.0),
            'sfw_score': caption_metadata.get('sfw_score', 0.0),
            'text_score': caption_metadata.get('text_score', 0.0),
            
            # === QC 字段 ===
            'ok': qc_item.get('qc', {}).get('ok') if isinstance(qc_item.get('qc'), dict) else qc_item.get('ok'),
            'width': qc_item.get('qc', {}).get('width') if isinstance(qc_item.get('qc'), dict) else qc_item.get('width'),
            'height': qc_item.get('qc', {}).get('height') if isinstance(qc_item.get('qc'), dict) else qc_item.get('height'),
            'is_long_image': qc_item.get('qc', {}).get('is_long_image') if isinstance(qc_item.get('qc'), dict) else qc_item.get('is_long_image'),
            
            # === OCR 字段 (硬证据：政治符号/标语/仇恨口号) ===
            'ocr_text': ocr_item.get('full_text', '') or (qc_item.get('ocr_result') or {}).get('full_text', ''),
            'need_ocr': qc_item.get('need_ocr'),
            
            # === Caption 字段 (动作/对象/部位/场景) ===
            'caption': caption_item.get('caption', ''),
            'expert_used': caption_item.get('expert_used', ''),
            'is_fallback': caption_metadata.get('is_fallback', False),
            
            # === NSFW 融合元数据 (如果使用了 fusion 模式) ===
            'ensemble_mode': caption_metadata.get('ensemble_mode', ''),
            'ensemble_used': caption_metadata.get('ensemble_used', False),
            
            # === 兼容旧格式 ===
            'caption_model': caption_item.get('model', ''),
            
            # === 压缩字段 (如果有压缩数据) ===
            'image_summary': compressed_item.get('image_summary', ''),
            'scene_focus': compressed_item.get('scene_focus', ''),
            'emotion_atmosphere': compressed_item.get('emotion_atmosphere', ''),
            'intent': compressed_item.get('intent', ''),
            'compression_ratio': compressed_item.get('compression_ratio', 0),
            'is_compressed': bool(compressed_item),
        })
        
        # 使用 reorder_record 重排字段顺序
        merged = reorder_record(merged, 'image')
        all_items.append(merged)
    
    # Sort by timestamp
    all_items.sort(key=lambda x: int(x.get('ts') or 0))
    
    # === Write by_class intermediate files (for debugging) ===
    by_class_dir = os.path.join(before_merge, 'by_class')
    os.makedirs(by_class_dir, exist_ok=True)
    
    class_groups = {}
    for item in all_items:
        route_class = item.get('route_class', 'UNKNOWN')
        if route_class not in class_groups:
            class_groups[route_class] = []
        class_groups[route_class].append(item)
    
    for route_class, items in class_groups.items():
        class_file = os.path.join(by_class_dir, f'{route_class}.jsonl')
        with open(class_file, 'w', encoding='utf-8') as f:
            for item in items:
                f.write(json.dumps(item, ensure_ascii=False) + '\n')
        logger.info(f"  Wrote {len(items)} items to by_class/{route_class}.jsonl")
    
    # === Write final merged output ===
    logger.info(f"Writing {len(all_items)} items to {output_file}...")
    with open(output_file, 'w', encoding='utf-8') as f:
        for item in all_items:
            f.write(json.dumps(item, ensure_ascii=False) + '\n')
    
    # Stats
    has_ocr = sum(1 for x in all_items if x.get('ocr_text'))
    has_caption = sum(1 for x in all_items if x.get('caption'))
    fallback_count = sum(1 for x in all_items if x.get('is_fallback'))
    
    # 专家统计
    expert_stats = {}
    for item in all_items:
        expert = item.get('expert_used', 'unknown')
        expert_stats[expert] = expert_stats.get(expert, 0) + 1
    
    # 内容类型统计
    content_stats = {}
    for item in all_items:
        ct = item.get('content_type', 'unknown')
        content_stats[ct] = content_stats.get(ct, 0) + 1
    
    logger.info("=" * 50)
    logger.info("Merge Complete!")
    logger.info(f"  Total: {len(all_items)}")
    logger.info(f"  With OCR: {has_ocr}")
    logger.info(f"  With Caption: {has_caption}")
    logger.info(f"  NSFW Fallback: {fallback_count}")
    logger.info(f"  By-class files: {len(class_groups)}")
    
    logger.info("  Expert Usage:")
    for expert, count in sorted(expert_stats.items()):
        logger.info(f"    - {expert}: {count}")
    
    logger.info("  Content Types:")
    for ct, count in sorted(content_stats.items()):
        logger.info(f"    - {ct}: {count}")


if __name__ == '__main__':
    main()
