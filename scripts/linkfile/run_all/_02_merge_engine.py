#!/usr/bin/env python3
"""
Linkfile 数据合并和 Schema 标准化步骤

功能：
- 加载 linkfile_extract_v1.jsonl
- 使用 schema_utils.py 的标准化工具重排字段
- 添加 schema_version 字段
- 输出到 linkfile_merged_final.jsonl

处理流程：
1. 加载提取阶段的输出（linkfile_extract_v1.jsonl）
2. 对每条记录：
   a. 添加 schema_version 字段
   b. 使用 reorder_linkfile_record() 重排字段顺序
3. 输出到 linkfile_merged_final.jsonl
4. 打印统计信息（link_sub_type 分布）

字段顺序规则：
1. 公共字段（COMMON_HEADER_FIELDS）：
   - schema_version, msg_uid, ts, speaker, type, modality, media_path
2. Linkfile 特定字段（LINKFILE_SPECIFIC_FIELDS）：
   - link_sub_type: 子类型标识
   - quote_*: 引用消息字段
   - link_*: 链接字段
   - miniprogram_*: 小程序字段
   - file_*: 文件字段
   - content_*: 内容字段
   - error_*: 错误处理
3. 其他未知字段（保持原顺序）

Schema 版本：
- merged_v2: 统一字段结构
- 公共字段：schema_version, msg_uid, ts, speaker, type, modality, media_path
- Linkfile 字段：link_sub_type, quote_*, link_*, file_*, etc.

输入：
- artifacts/before_merge/linkfile/linkfile_extract_v1.jsonl: 提取结果

输出：
- artifacts/after_merge/linkfile/linkfile_merged_final.jsonl: 合并结果

依赖：
- scripts/_common/schema_utils.py: Schema 工具
- scripts/_common/path_utils.py: 路径工具

使用示例：
    python scripts/linkfile/run_all/_02_merge_engine.py

输出统计：
- 合并的记录数
- link_sub_type 分布

作者：[Author]
更新于：2026-02-02
"""

import json
import logging
import sys
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List

from tqdm import tqdm

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts._common.path_utils import (
    get_linkfile_before_merge,
    get_linkfile_after_merge,
    load_linkfile_config,
)
from scripts._common.schema_utils import (
    SCHEMA_VERSION,
    COMMON_HEADER_FIELDS,
)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# =============================================================================
# Linkfile 特定字段定义
# =============================================================================

LINKFILE_SPECIFIC_FIELDS: List[str] = [
    # 子类型标识
    "link_sub_type",        # 子类型名称（quote, link, file, miniprogram, video_channel, chat_history）
    
    # 引用消息字段 (quote)
    "quote_svrid",          # 被引用消息的 MsgSvrID
    "quote_type",           # 被引用消息的类型
    "quote_text",           # 被引用消息的文本（已匿名化）
    
    # 链接字段 (link, miniprogram)
    "link_url",             # 链接 URL
    "link_title",           # 链接标题
    "link_type",            # 链接类型分类
    
    # 小程序字段 (miniprogram)
    "miniprogram_appid",    # 小程序 AppID
    "miniprogram_name",     # 小程序名称
    
    # 文件字段 (file)
    "file_name",            # 文件名
    "file_ext",             # 文件扩展名
    "file_category",        # 文件类型分类
    "file_size_bytes",      # 文件大小（字节）
    "file_summary",         # 文件内容摘要（PDF/ZIP）
    "file_summary_meta",    # 摘要生成元数据
    
    # 内容字段 (video_channel, chat_history)
    "content_title",        # 内容标题
    
    # 错误处理
    "error_message",        # 处理错误信息
]
"""
Linkfile 模态特定字段列表。

字段按逻辑分组：
1. 子类型标识 - link_sub_type
2. 引用消息字段 - quote_*
3. 链接字段 - link_*
4. 小程序字段 - miniprogram_*
5. 文件字段 - file_*
6. 内容字段 - content_*
7. 错误处理 - error_*
"""


def reorder_linkfile_record(
    record: Dict[str, Any],
    include_schema_version: bool = True
) -> OrderedDict:
    """
    按标准顺序重排 linkfile 记录字段
    
    Args:
        record: 原始记录字典
        include_schema_version: 是否包含 schema_version 字段
        
    Returns:
        OrderedDict: 按标准顺序排列的记录
    
    字段顺序：
        1. 公共字段（COMMON_HEADER_FIELDS）
        2. Linkfile 特定字段（LINKFILE_SPECIFIC_FIELDS）
        3. 其他未知字段（保持原顺序）
    
    Example:
        >>> record = {"msg_uid": "123", "link_sub_type": "quote", ...}
        >>> ordered = reorder_linkfile_record(record)
        >>> print(list(ordered.keys())[:3])
        ['schema_version', 'msg_uid', 'ts']
    """
    result = OrderedDict()
    
    # 1. 公共字段（按 COMMON_HEADER_FIELDS 顺序）
    for field in COMMON_HEADER_FIELDS:
        if not include_schema_version and field == 'schema_version':
            continue
        if field in record:
            result[field] = record[field]
    
    # 2. Linkfile 特定字段（按定义顺序）
    for field in LINKFILE_SPECIFIC_FIELDS:
        if field in record:
            result[field] = record[field]
    
    # 3. 其他未知字段（保持原顺序）
    known_fields = set(COMMON_HEADER_FIELDS) | set(LINKFILE_SPECIFIC_FIELDS)
    for key, value in record.items():
        if key not in known_fields:
            result[key] = value
    
    return result


def load_extract_records(input_path: Path) -> List[Dict[str, Any]]:
    """
    加载提取阶段的输出记录
    
    Args:
        input_path: linkfile_extract_v1.jsonl 路径
        
    Returns:
        list: 记录列表
    
    说明：
        - 跳过空行
        - 跳过解析失败的行
        - 返回所有成功解析的记录
    
    Example:
        >>> records = load_extract_records(Path("linkfile_extract_v1.jsonl"))
        >>> print(len(records))
        567
    """
    records = []
    with open(input_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def main():
    """
    主函数：执行 Linkfile 数据合并和 Schema 标准化
    
    流程：
    1. 加载 linkfile_extract_v1.jsonl
    2. 对每条记录：
       - 添加 schema_version 字段
       - 使用 reorder_linkfile_record() 重排字段顺序
    3. 输出到 linkfile_merged_final.jsonl
    4. 打印统计信息（link_sub_type 分布）
    
    输出统计：
        - 合并的记录数
        - link_sub_type 分布
    
    Raises:
        FileNotFoundError: 如果 linkfile_extract_v1.jsonl 不存在
    """
    logger.info("=" * 60)
    logger.info("Linkfile Pipeline - Step 2: Merge Engine")
    logger.info("=" * 60)
    
    # 加载配置
    config = load_linkfile_config()
    
    # 输入路径
    input_dir = get_linkfile_before_merge()
    input_filename = config.get('output_files', {}).get('extract', 'linkfile_extract_v1.jsonl')
    input_path = input_dir / input_filename
    
    if not input_path.exists():
        logger.error(f"Input file not found: {input_path}")
        logger.error("Please run _01_extract_and_anonymize.py first.")
        return
    
    logger.info(f"Loading from {input_path}...")
    records = load_extract_records(input_path)
    logger.info(f"  Loaded {len(records)} records")
    
    if not records:
        logger.warning("No records to process. Exiting.")
        return
    
    # 处理记录
    logger.info("Reordering fields and adding schema_version...")
    merged_records = []
    for record in tqdm(records, desc="Merging"):
        # 添加 schema_version
        record['schema_version'] = SCHEMA_VERSION
        
        # 重排字段
        merged = reorder_linkfile_record(record)
        merged_records.append(merged)
    
    # 输出路径
    output_dir = get_linkfile_after_merge()
    output_dir.mkdir(parents=True, exist_ok=True)
    
    output_filename = config.get('output_files', {}).get('merged', 'linkfile_merged_final.jsonl')
    output_path = output_dir / output_filename
    
    logger.info(f"Writing to {output_path}...")
    with open(output_path, "w", encoding="utf-8") as f:
        for record in merged_records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    
    logger.info(f"Done. Wrote {len(merged_records)} records.")
    
    # 统计 link_sub_type 分布
    link_sub_type_counts = {}
    for r in merged_records:
        lst = r.get('link_sub_type', 'unknown')
        link_sub_type_counts[lst] = link_sub_type_counts.get(lst, 0) + 1
    logger.info(f"Output link_sub_type distribution: {link_sub_type_counts}")


if __name__ == "__main__":
    main()
