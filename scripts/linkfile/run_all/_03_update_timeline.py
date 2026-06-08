#!/usr/bin/env python3
"""
Linkfile 时间轴更新步骤

功能：
- 将 linkfile 处理结果合并到主时间轴
- 更新 enriched_full.jsonl（完整版，包含所有字段）
- 更新 enriched_slim.jsonl（精简版，仅保留 LLM RAG 所需字段）
- 根据 link_sub_type 添加对应的 link_ 前缀字段

处理流程：
1. 加载 linkfile_merged_final.jsonl
2. 加载 enriched_full.jsonl 和 enriched_slim.jsonl
3. 对每条消息：
   a. 按 msg_uid 匹配 linkfile 数据
   b. 根据 link_sub_type 构建时间轴字段
   c. 更新记录
4. 保存更新后的时间轴文件
5. 打印统计信息

字段映射策略：
- **完整版（enriched_full.jsonl）**：
  * 保留所有 linkfile 字段
  * 用于数据分析、调试、回溯
  
- **精简版（enriched_slim.jsonl）**：
  * 仅保留 LLM RAG 所需字段（SLIM_FIELDS）：
    - link_sub_type: 子类型标识
    - link_quote_text: 引用文本
    - link_url: 链接 URL
    - link_title: 链接标题
    - link_type: 链接类型
    - link_file_name: 文件名
    - link_file_category: 文件类型
    - link_file_summary: 文件摘要
    - link_content_title: 内容标题
  * 减少 Token 消耗，提升 RAG 效率

时间轴字段命名规则：
- 所有字段添加 link_ 前缀（避免与其他模态冲突）
- 根据 link_sub_type 映射不同的字段：
  * quote: link_quote_svrid, link_quote_type, link_quote_text
  * link: link_url, link_title, link_type
  * file: link_file_name, link_file_ext, link_file_category, link_file_summary
  * miniprogram: link_url, link_title, link_miniprogram_appid, link_miniprogram_name
  * video_channel: link_content_title
  * chat_history: link_content_title

输入：
- artifacts/after_merge/linkfile/linkfile_merged_final.jsonl: 合并结果
- timeline_out/enriched_full.jsonl: 现有时间轴（完整版）
- timeline_out/enriched_slim.jsonl: 现有时间轴（精简版）

输出：
- timeline_out/enriched_full.jsonl: 更新后的完整版时间轴
- timeline_out/enriched_slim.jsonl: 更新后的精简版时间轴

依赖：
- scripts/_common/path_utils.py: 路径工具

使用示例：
    python scripts/linkfile/run_all/_03_update_timeline.py

输出统计：
- 更新的记录数（full 和 slim）

作者：[Author]
更新于：2026-02-02
"""

import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from tqdm import tqdm

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts._common.path_utils import (
    get_linkfile_after_merge,
    get_timeline_out,
    load_linkfile_config,
)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# =============================================================================
# 时间轴字段映射
# =============================================================================

# 各 link_sub_type 对应的时间轴字段
TIMELINE_FIELD_MAPPING = {
    'quote': {
        'quote_svrid': 'link_quote_svrid',
        'quote_type': 'link_quote_type',
        'quote_text': 'link_quote_text',
    },
    'link': {
        'link_url': 'link_url',
        'link_title': 'link_title',
        'link_type': 'link_type',
    },
    'file': {
        'file_name': 'link_file_name',
        'file_ext': 'link_file_ext',
        'file_category': 'link_file_category',
        'file_size_bytes': 'link_file_size_bytes',
        'file_summary': 'link_file_summary',
    },
    'miniprogram': {
        'link_url': 'link_url',
        'link_title': 'link_title',
        'miniprogram_appid': 'link_miniprogram_appid',
        'miniprogram_name': 'link_miniprogram_name',
    },
    'video_channel': {
        'content_title': 'link_content_title',
    },
    'chat_history': {
        'content_title': 'link_content_title',
    },
}

# 所有 link_sub_type 共享的字段
COMMON_TIMELINE_FIELDS = {
    'link_sub_type': 'link_sub_type',
}

# Slim 版本包含的字段（精简版，用于 LLM RAG）
SLIM_FIELDS = {
    'link_sub_type',
    'link_quote_text',
    'link_url',
    'link_title',
    'link_type',
    'link_file_name',
    'link_file_category',
    'link_file_summary',
    'link_content_title',
}


def load_merged_records(input_path: Path) -> Dict[str, Dict[str, Any]]:
    """
    加载合并后的记录，构建 msg_uid -> record 映射
    
    Args:
        input_path: linkfile_merged_final.jsonl 路径
        
    Returns:
        dict: msg_uid -> record 的映射字典
    
    说明：
        - 跳过空行
        - 跳过解析失败的行
        - 跳过没有 msg_uid 的记录
        - 返回 msg_uid -> record 的映射
    
    Example:
        >>> lookup = load_merged_records(Path("linkfile_merged_final.jsonl"))
        >>> print(len(lookup))
        567
    """
    records = {}
    with open(input_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                msg_uid = record.get('msg_uid')
                if msg_uid:
                    records[msg_uid] = record
            except json.JSONDecodeError:
                continue
    return records


def load_timeline(timeline_path: Path) -> List[Dict[str, Any]]:
    """
    加载时间轴文件
    
    Args:
        timeline_path: enriched_*.jsonl 路径
        
    Returns:
        list: 时间轴记录列表
    
    说明：
        - 如果文件不存在，返回空列表
        - 跳过空行
        - 跳过解析失败的行
        - 返回所有成功解析的记录
    
    Example:
        >>> records = load_timeline(Path("enriched_full.jsonl"))
        >>> print(len(records))
        12345
    """
    records = []
    if not timeline_path.exists():
        return records
    
    with open(timeline_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def build_timeline_fields(
    linkfile_record: Dict[str, Any],
    is_slim: bool = False
) -> Dict[str, Any]:
    """
    从 linkfile 记录构建时间轴字段
    
    Args:
        linkfile_record: linkfile_merged_final.jsonl 中的记录
        is_slim: 是否为精简版（只包含 SLIM_FIELDS）
        
    Returns:
        dict: 时间轴字段字典（带 link_ 前缀）
    
    字段映射规则：
        - 根据 link_sub_type 选择对应的字段映射表
        - 所有字段添加 link_ 前缀
        - 跳过空值（None 或空字符串）
        - 精简版只包含 SLIM_FIELDS 中的字段
    
    Example:
        >>> record = {"link_sub_type": "quote", "quote_text": "你好"}
        >>> fields = build_timeline_fields(record)
        >>> print(fields)
        {'link_sub_type': 'quote', 'link_quote_text': '你好'}
    """
    result = {}
    link_sub_type = linkfile_record.get('link_sub_type', 'unknown')
    
    # 添加公共字段
    for src_field, dst_field in COMMON_TIMELINE_FIELDS.items():
        if src_field in linkfile_record:
            if not is_slim or dst_field in SLIM_FIELDS:
                result[dst_field] = linkfile_record[src_field]
    
    # 添加子类型特定字段
    field_mapping = TIMELINE_FIELD_MAPPING.get(link_sub_type, {})
    for src_field, dst_field in field_mapping.items():
        if src_field in linkfile_record:
            value = linkfile_record[src_field]
            # 跳过空值
            if value is None or value == '':
                continue
            if not is_slim or dst_field in SLIM_FIELDS:
                result[dst_field] = value
    
    return result


def update_timeline(
    timeline_records: List[Dict[str, Any]],
    linkfile_lookup: Dict[str, Dict[str, Any]],
    is_slim: bool = False
) -> tuple:
    """
    更新时间轴记录
    
    Args:
        timeline_records: 时间轴记录列表
        linkfile_lookup: msg_uid -> linkfile_record 映射
        is_slim: 是否为精简版
        
    Returns:
        tuple: (updated_records, update_count)
            - updated_records: 更新后的记录列表
            - update_count: 更新的记录数量
    
    说明：
        - 按 msg_uid 匹配 linkfile 数据
        - 如果匹配成功，构建时间轴字段并更新记录
        - 如果匹配失败，保持原记录不变
        - 返回更新后的记录列表和更新数量
    
    Example:
        >>> updated, count = update_timeline(timeline_records, linkfile_lookup)
        >>> print(f"Updated {count} records")
        Updated 567 records
    """
    updated_records = []
    update_count = 0
    
    for record in timeline_records:
        msg_uid = record.get('msg_uid')
        
        if msg_uid and msg_uid in linkfile_lookup:
            linkfile_record = linkfile_lookup[msg_uid]
            timeline_fields = build_timeline_fields(linkfile_record, is_slim)
            
            # 更新记录
            record.update(timeline_fields)
            update_count += 1
        
        updated_records.append(record)
    
    return updated_records, update_count


def save_timeline(records: List[Dict[str, Any]], output_path: Path):
    """
    保存时间轴文件
    
    Args:
        records: 时间轴记录列表
        output_path: 输出文件路径
    
    说明：
        - 每条记录写入一行 JSON
        - 使用 ensure_ascii=False 保留中文
        - 自动创建父目录（如果不存在）
    
    Example:
        >>> save_timeline(records, Path("enriched_full.jsonl"))
    """
    with open(output_path, "w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def main():
    """
    主函数：执行 Linkfile 时间轴更新
    
    流程：
    1. 加载 linkfile_merged_final.jsonl
    2. 加载 enriched_full.jsonl 和 enriched_slim.jsonl
    3. 对每条消息：
       - 按 msg_uid 匹配 linkfile 数据
       - 根据 link_sub_type 构建时间轴字段
       - 更新记录
    4. 保存更新后的时间轴文件
    5. 打印统计信息
    
    输出统计：
        - 更新的记录数（full 和 slim）
    
    Raises:
        FileNotFoundError: 如果 linkfile_merged_final.jsonl 不存在
    """
    logger.info("=" * 60)
    logger.info("Linkfile Pipeline - Step 3: Update Timeline")
    logger.info("=" * 60)
    
    # 加载配置
    config = load_linkfile_config()
    
    # 输入路径
    input_dir = get_linkfile_after_merge()
    input_filename = config.get('output_files', {}).get('merged', 'linkfile_merged_final.jsonl')
    input_path = input_dir / input_filename
    
    if not input_path.exists():
        logger.error(f"Input file not found: {input_path}")
        logger.error("Please run _02_merge_engine.py first.")
        return
    
    logger.info(f"Loading linkfile records from {input_path}...")
    linkfile_lookup = load_merged_records(input_path)
    logger.info(f"  Loaded {len(linkfile_lookup)} linkfile records")
    
    if not linkfile_lookup:
        logger.warning("No linkfile records to process. Exiting.")
        return
    
    # 时间轴路径
    timeline_dir = get_timeline_out()
    full_path = timeline_dir / "enriched_full.jsonl"
    slim_path = timeline_dir / "enriched_slim.jsonl"
    
    # 更新 enriched_full.jsonl
    if full_path.exists():
        logger.info(f"Updating {full_path}...")
        full_records = load_timeline(full_path)
        logger.info(f"  Loaded {len(full_records)} timeline records")
        
        updated_full, full_count = update_timeline(full_records, linkfile_lookup, is_slim=False)
        save_timeline(updated_full, full_path)
        logger.info(f"  Updated {full_count} records in enriched_full.jsonl")
    else:
        logger.warning(f"Timeline file not found: {full_path}")
    
    # 更新 enriched_slim.jsonl
    if slim_path.exists():
        logger.info(f"Updating {slim_path}...")
        slim_records = load_timeline(slim_path)
        logger.info(f"  Loaded {len(slim_records)} timeline records")
        
        updated_slim, slim_count = update_timeline(slim_records, linkfile_lookup, is_slim=True)
        save_timeline(updated_slim, slim_path)
        logger.info(f"  Updated {slim_count} records in enriched_slim.jsonl")
    else:
        logger.warning(f"Timeline file not found: {slim_path}")
    
    logger.info("Done.")


if __name__ == "__main__":
    main()
