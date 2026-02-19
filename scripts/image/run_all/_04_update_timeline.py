#!/usr/bin/env python3
"""
时间轴更新步骤（图片）

功能：
- 将图片处理结果更新到时间轴文件
- 支持 Full 和 Slim 两个版本
- Full 版本保留完整元数据（分析/回溯用）
- Slim 版本精简关键信息（LLM RAG 用）

处理流程：
1. 加载图片合并结果（image_merged_final.jsonl）
2. 更新 enriched_full.jsonl：
   - 添加所有图片字段（20+ 字段）
   - 保留分数、置信度、专家信息
   - 用于深度分析和回溯
3. 更新 enriched_slim.jsonl：
   - 合并 caption 和 OCR 到 text 字段
   - 只保留关键分类信息
   - 添加敏感内容标记
   - 优化 LLM 上下文使用

输出设计：

**enriched_full.jsonl（完整版）**：
- 所有原始字段 + 完整的图片处理结果
- 包括：
  * 路由分类：image_route_class
  * 内容分类：image_content_type, image_triage_confidence
  * 分数：image_nsfw_score, image_sfw_score, image_text_score
  * QC 字段：image_ok, image_width, image_height
  * OCR 字段：image_ocr_text, image_need_ocr
  * Caption 字段：image_caption, image_expert_used, image_is_fallback
  * NSFW 融合：image_ensemble_mode, image_ensemble_used
  * 压缩字段：image_summary, image_scene_focus, image_emotion_atmosphere

**enriched_slim.jsonl（精简版）**：
- 只保留关键信息：
  * text: 合并后的描述/文字（优先使用 image_summary）
  * image_class: 路由分类
  * content_type: 内容类型
  * sensitive: 敏感内容标记（NSFW/Gore）
  * image_scene_focus, image_emotion, image_intent（如有压缩数据）

字段合并策略（Slim 版本）：
1. 优先使用压缩后的 image_summary
2. 如果无压缩数据：
   - 有 caption 和 OCR：合并为 "[图片描述] ... \n[图片文字] ..."
   - 只有 caption：使用 "[图片描述] ..."
   - 只有 OCR：使用 "[图片文字] ..."
3. 添加敏感内容标记（TYPE_A_NSFW, TYPE_B_GORE）

输入：
- artifacts/after_merge/image/image_merged_final.jsonl: 图片合并结果
- timeline_out/enriched_full.jsonl: 现有时间轴（Full）
- timeline_out/enriched_slim.jsonl: 现有时间轴（Slim）

输出：
- timeline_out/enriched_full.jsonl: 更新后的时间轴（Full）
- timeline_out/enriched_slim.jsonl: 更新后的时间轴（Slim）

依赖：
- scripts/_common/path_utils.py: 路径工具

使用示例：
    python scripts/image/run_all/_04_update_timeline.py

注意事项：
- 确保先运行 _03_merge_engine.py
- 如果时间轴文件不存在，会从原始消息创建
- 更新过程中会创建临时文件，完成后替换原文件

作者：forcifer
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

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def load_image_data(file_path):
    """
    加载图片处理结果数据，按 msg_uid 索引
    
    从 image_merged_final.jsonl 加载所有图片处理结果，
    构建 msg_uid -> 图片数据 的字典，用于后续时间轴更新。
    
    Args:
        file_path: 图片合并结果文件路径（image_merged_final.jsonl）
    
    Returns:
        dict: 以 msg_uid 为键的图片数据字典
            键: msg_uid (str)
            值: 图片处理结果 (dict)，包含所有字段：
                - route_class: 路由分类
                - content_type: 内容类型
                - caption: 图片描述
                - ocr_text: OCR 文字
                - nsfw_score: NSFW 分数
                - 等 20+ 字段
    
    Example:
        >>> data = load_image_data('artifacts/after_merge/image/image_merged_final.jsonl')
        >>> print(len(data))
        1234
        >>> print(data['msg_123']['caption'])
        '一张风景照片'
    """
    data = {}
    if not os.path.exists(file_path):
        return data
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            if not line.strip():
                continue
            try:
                item = json.loads(line)
                uid = item.get('msg_uid')
                if uid:
                    data[uid] = item
            except json.JSONDecodeError:
                pass
    return data


def merge_into_full(input_file, output_file, image_data):
    """
    将图片数据合并到 enriched_full.jsonl（完整版）
    
    保留所有图片处理的完整元数据（20+ 字段），用于深度分析和回溯。
    包括分数、置信度、专家信息、QC 字段等。
    
    合并字段：
    - 路由分类：image_route_class
    - 内容分类：image_content_type, image_triage_confidence
    - 分数：image_nsfw_score, image_sfw_score, image_text_score
    - QC 字段：image_ok, image_width, image_height, image_is_long
    - OCR 字段：image_ocr_text, image_need_ocr
    - Caption 字段：image_caption, image_expert_used, image_is_fallback
    - NSFW 融合：image_ensemble_mode, image_ensemble_used
    - 压缩字段：image_summary, image_scene_focus, image_emotion_atmosphere
    
    Args:
        input_file: 输入时间轴文件路径（enriched_full.jsonl 或 P1_messages_raw.jsonl）
        output_file: 输出临时文件路径（enriched_full_merged.jsonl）
        image_data: 图片数据字典（msg_uid -> 图片数据）
    
    Returns:
        tuple: (更新记录数, 总记录数)
    
    Example:
        >>> updated, total = merge_into_full(
        ...     'timeline_out/enriched_full.jsonl',
        ...     'timeline_out/enriched_full_merged.jsonl',
        ...     image_data
        ... )
        >>> print(f"Updated {updated}/{total} records")
        Updated 1234/5678 records
    """
    updated_count = 0
    total_count = 0
    
    # 先统计总行数
    with open(input_file, 'r', encoding='utf-8') as f:
        total_lines = sum(1 for _ in f)
    
    with open(input_file, 'r', encoding='utf-8') as fin, \
         open(output_file, 'w', encoding='utf-8') as fout:
        for line in tqdm(fin, total=total_lines, desc="更新Full", **tqdm_kwargs):
            total_count += 1
            try:
                item = json.loads(line)
                uid = item.get('msg_uid')
                
                if uid in image_data:
                    img = image_data[uid]
                    
                    # === 完整元数据 ===
                    # 路由分类
                    item['image_route_class'] = img.get('route_class', '')
                    
                    # 内容分类 (Triage)
                    item['image_content_type'] = img.get('content_type', '')
                    item['image_triage_confidence'] = img.get('triage_confidence', 0.0)
                    
                    # 分数/置信度 (关键回溯线索)
                    item['image_nsfw_score'] = img.get('nsfw_score', 0.0)
                    item['image_sfw_score'] = img.get('sfw_score', 0.0)
                    item['image_text_score'] = img.get('text_score', 0.0)
                    
                    # QC 字段
                    item['image_ok'] = img.get('ok')
                    item['image_width'] = img.get('width')
                    item['image_height'] = img.get('height')
                    item['image_is_long'] = img.get('is_long_image')
                    
                    # OCR 字段
                    item['image_ocr_text'] = img.get('ocr_text', '')
                    item['image_need_ocr'] = img.get('need_ocr', False)
                    
                    # Caption 字段
                    item['image_caption'] = img.get('caption', '')
                    item['image_expert_used'] = img.get('expert_used', '')
                    item['image_is_fallback'] = img.get('is_fallback', False)
                    
                    # NSFW 融合元数据
                    item['image_ensemble_mode'] = img.get('ensemble_mode', '')
                    item['image_ensemble_used'] = img.get('ensemble_used', False)
                    
                    # 兼容旧格式
                    item['image_caption_model'] = img.get('caption_model', '')
                    
                    # 压缩字段
                    item['image_summary'] = img.get('image_summary', '')
                    item['image_scene_focus'] = img.get('scene_focus', '')
                    item['image_emotion_atmosphere'] = img.get('emotion_atmosphere', '')
                    item['image_intent'] = img.get('intent', '')
                    item['image_compression_ratio'] = img.get('compression_ratio', 0)
                    item['image_is_compressed'] = img.get('is_compressed', False)
                    
                    updated_count += 1
                    
                fout.write(json.dumps(item, ensure_ascii=False) + '\n')
            except Exception as e:
                logger.warning(f"Error processing line: {e}")
                fout.write(line)
                
    return updated_count, total_count


def merge_into_slim(input_file, output_file, image_data):
    """
    将图片数据合并到 enriched_slim.jsonl（精简版）
    
    只保留关键信息，优化 LLM RAG 使用的上下文长度。
    
    字段合并策略：
    1. text 字段（优先级）：
       - 优先使用压缩后的 image_summary
       - 如果无压缩数据：
         * 有 caption 和 OCR：合并为 "[图片描述] ... \n[图片文字] ..."
         * 只有 caption：使用 "[图片描述] ..."
         * 只有 OCR：使用 "[图片文字] ..."
    
    2. 分类信息：
       - image_class: 路由分类（route_class）
       - content_type: 内容类型
       - sensitive: 敏感内容标记（TYPE_A_NSFW, TYPE_B_GORE）
    
    3. 压缩字段（如有）：
       - image_scene_focus: 场景焦点
       - image_emotion: 情绪氛围
       - image_intent: 意图
    
    Args:
        input_file: 输入时间轴文件路径（enriched_slim.jsonl 或 P1_messages_raw.jsonl）
        output_file: 输出临时文件路径（enriched_slim_merged.jsonl）
        image_data: 图片数据字典（msg_uid -> 图片数据）
    
    Returns:
        tuple: (更新记录数, 总记录数)
    
    Example:
        >>> updated, total = merge_into_slim(
        ...     'timeline_out/enriched_slim.jsonl',
        ...     'timeline_out/enriched_slim_merged.jsonl',
        ...     image_data
        ... )
        >>> print(f"Updated {updated}/{total} records")
        Updated 1234/5678 records
    
    Note:
        - 精简版用于 LLM RAG，减少 token 消耗
        - 敏感内容会被标记但不会被过滤
        - 压缩数据优先级高于原始 caption/OCR
    """
    updated_count = 0
    total_count = 0
    
    # 先统计总行数
    with open(input_file, 'r', encoding='utf-8') as f:
        total_lines = sum(1 for _ in f)
    
    with open(input_file, 'r', encoding='utf-8') as fin, \
         open(output_file, 'w', encoding='utf-8') as fout:
        for line in tqdm(fin, total=total_lines, desc="更新Slim", **tqdm_kwargs):
            total_count += 1
            try:
                item = json.loads(line)
                uid = item.get('msg_uid')
                
                if uid in image_data:
                    img = image_data[uid]
                    image_summary = img.get('image_summary', '').strip()
                    caption = img.get('caption', '').strip()
                    ocr = img.get('ocr_text', '').strip()
                    content_type = img.get('content_type', '')
                    route_class = img.get('route_class', '')
                    
                    # === 精简版：只保留关键信息 ===
                    
                    # 1. 优先使用压缩后的 image_summary
                    if image_summary:
                        item['text'] = image_summary
                        item['image_summary'] = image_summary
                        # 添加压缩相关字段
                        scene_focus = img.get('scene_focus', '')
                        emotion = img.get('emotion_atmosphere', '')
                        intent = img.get('intent', '')
                        if scene_focus:
                            item['image_scene_focus'] = scene_focus
                        if emotion:
                            item['image_emotion'] = emotion
                        if intent:
                            item['image_intent'] = intent
                    elif caption and ocr:
                        # 两者都有，合并
                        item['text'] = f"[图片描述] {caption}\n[图片文字] {ocr}"
                    elif caption:
                        item['text'] = f"[图片描述] {caption}"
                    elif ocr:
                        item['text'] = f"[图片文字] {ocr}"
                    # 如果都没有，保持原有 text 字段
                    
                    # 2. 添加分类信息（简化）
                    item['image_class'] = route_class
                    
                    # 3. 添加内容类型（用于过滤敏感内容）
                    if content_type:
                        item['content_type'] = content_type
                    
                    # 4. 如果是 NSFW/Gore，添加标记
                    if content_type in ['TYPE_A_NSFW', 'TYPE_B_GORE']:
                        item['sensitive'] = True
                    
                    updated_count += 1
                    
                fout.write(json.dumps(item, ensure_ascii=False) + '\n')
            except Exception as e:
                logger.warning(f"Error processing line: {e}")
                fout.write(line)
                
    return updated_count, total_count


def main():
    """
    主函数：更新时间轴文件
    
    处理流程：
    1. 加载图片合并结果（image_merged_final.jsonl）
    2. 确定输入源：
       - 如果 enriched_full.jsonl 存在，使用现有时间轴
       - 否则从原始消息（P1_messages_raw.jsonl）创建新时间轴
    3. 更新 enriched_full.jsonl（完整版）
    4. 更新 enriched_slim.jsonl（精简版）
    5. 使用临时文件 + os.replace() 确保原子性更新
    
    输出文件：
    - timeline_out/enriched_full.jsonl: 完整版（20+ 图片字段）
    - timeline_out/enriched_slim.jsonl: 精简版（LLM RAG 用）
    
    Raises:
        FileNotFoundError: 如果 image_merged_final.jsonl 不存在
        FileNotFoundError: 如果原始消息文件不存在且时间轴文件也不存在
    
    Example:
        $ python scripts/image/run_all/_04_update_timeline.py
        Loading image enrichment data...
        Loaded 1234 image records
        Processing enriched_full.jsonl...
        Updated 1234/5678 records
        Processing enriched_slim.jsonl...
        Updated 1234/5678 records
        Timeline Update Complete!
    """
    # Paths
    image_enriched = PROJECT_ROOT / 'artifacts/after_merge/image/image_merged_final.jsonl'
    timeline_dir = PROJECT_ROOT / 'timeline_out'
    messages_file = PROJECT_ROOT / 'raw' / 'P1_messages_raw.jsonl'
    
    full_input = timeline_dir / 'enriched_full.jsonl'
    slim_input = timeline_dir / 'enriched_slim.jsonl'
    
    if not image_enriched.exists():
        logger.error(f"Image enriched file not found: {image_enriched}")
        logger.info("Please run _03_merge_engine.py first.")
        return
    
    # Load image data
    logger.info(f"Loading image enrichment data from {image_enriched}...")
    image_data = load_image_data(image_enriched)
    logger.info(f"Loaded {len(image_data)} image records")
    
    if len(image_data) == 0:
        logger.warning("No image data to merge!")
        return
    
    # 确定输入源：优先使用已有的 enriched_full.jsonl，否则使用原始消息
    if full_input.exists():
        logger.info(f"\nUpdating existing timeline: {full_input}")
        input_full = full_input
        input_slim = slim_input
    else:
        logger.info(f"\nCreating new timeline from: {messages_file}")
        if not messages_file.exists():
            logger.error(f"Messages file not found: {messages_file}")
            return
        input_full = messages_file
        input_slim = messages_file
    
    # Merge into full
    logger.info(f"\nProcessing enriched_full.jsonl...")
    full_output = timeline_dir / 'enriched_full_merged.jsonl'
    updated, total = merge_into_full(input_full, full_output, image_data)
    logger.info(f"  Updated {updated}/{total} records")
    os.replace(full_output, full_input)
    
    # Merge into slim
    logger.info(f"\nProcessing enriched_slim.jsonl...")
    slim_output = timeline_dir / 'enriched_slim_merged.jsonl'
    updated, total = merge_into_slim(input_slim, slim_output, image_data)
    logger.info(f"  Updated {updated}/{total} records")
    os.replace(slim_output, slim_input)
    
    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("Timeline Update Complete!")
    logger.info("=" * 60)
    logger.info(f"  Image records merged: {len(image_data)}")
    logger.info(f"  Full output: {full_input}")
    logger.info(f"  Slim output: {slim_input}")
    
    # 显示字段差异
    logger.info("\n字段设计:")
    logger.info("  enriched_full.jsonl: 完整元数据（20+ 图片字段）")
    logger.info("    - 分数: nsfw_score, sfw_score, text_score")
    logger.info("    - 分类: route_class, content_type, triage_confidence")
    logger.info("    - 专家: expert_used, ensemble_mode, is_fallback")
    logger.info("    - 内容: caption, ocr_text")
    logger.info("  enriched_slim.jsonl: 精简版（LLM RAG用）")
    logger.info("    - text: 合并后的描述/文字")
    logger.info("    - image_class: 路由分类")
    logger.info("    - content_type: 内容类型")
    logger.info("    - sensitive: 敏感内容标记")


if __name__ == '__main__':
    main()
