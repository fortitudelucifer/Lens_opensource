#!/usr/bin/env python3
"""
Linkfile 提取和匿名化步骤

功能：
- 提取 type=49 消息（链接/文件/小程序/引用等）
- 从 HTML 文件解析引用消息信息
- 调用 LinkfileExtractor 处理所有消息
- 匿名化引用文本中的说话人前缀
- 输出结构化的 linkfile 数据

处理流程：
1. 查找导出目录中的 HTML 文件（自动识别）
2. 从 HTML 提取消息 JSON 对象（包含引用信息）
3. 构建引用查找表（MsgSvrID -> quote_info）
4. 加载 P1_messages_raw.jsonl 并过滤 type=49 消息
5. 对每条消息：
   a. 匹配引用信息（通过 MsgSvrID）
   b. 调用 LinkfileExtractor 提取元数据
   c. 匿名化说话人前缀
6. 输出到 linkfile_extract_v1.jsonl

支持的 sub_type：
- 57: 引用消息（quote）
- 5: 链接分享（link）
- 6: 文件（file）
- 33: 小程序（miniprogram）
- 51: 视频号（video_channel）
- 19: 聊天记录（chat_history）

匿名化策略：
- 引用文本中的说话人前缀（"用户A: 你好" -> "P1: 你好"）
- 使用 anonymizer.py 的 anonymize_speaker_prefix() 函数
- 保护隐私，避免泄露真实姓名

输入：
- raw/P1_messages_raw.jsonl: 原始消息
- raw/export/*.html: 导出的 HTML 文件（包含引用信息）

输出：
- artifacts/before_merge/linkfile/linkfile_extract_v1.jsonl: 提取结果

依赖：
- scripts/linkfile/extractor.py: LinkfileExtractor
- scripts/_common/anonymizer.py: 匿名化工具
- scripts/_common/path_utils.py: 路径工具

使用示例：
    python scripts/linkfile/run_all/_01_extract_and_anonymize.py

输出统计：
- 提取的记录数
- sub_type 分布
- link_sub_type 分布

作者：forcifer
更新于：2026-02-02
"""

import json
import logging
import re
import sys
from pathlib import Path

from tqdm import tqdm

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts._common.path_utils import (
    get_messages_path,
    get_export_dir,
    get_linkfile_before_merge,
    get_root,
    load_linkfile_config,
)
from scripts._common.anonymizer import anonymize_speaker_prefix
from scripts.linkfile.extractor import LinkfileExtractor

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def find_html_file() -> Path:
    """
    自动查找导出目录中的 HTML 文件
    
    优先查找与工作空间名称匹配的文件，否则返回第一个 .html 文件
    
    Returns:
        Path: HTML 文件路径
    
    Raises:
        FileNotFoundError: 如果导出目录不存在或没有 HTML 文件
    
    Example:
        >>> html_file = find_html_file()
        >>> print(html_file.name)
        chat.html
    """
    export_dir = get_export_dir()
    
    if not export_dir.exists():
        raise FileNotFoundError(f"Export directory not found: {export_dir}")
    
    html_files = list(export_dir.glob("*.html"))
    
    if not html_files:
        raise FileNotFoundError(f"No HTML files found in {export_dir}")
    
    # 如果只有一个 HTML 文件，直接返回
    if len(html_files) == 1:
        return html_files[0]
    
    # 多个文件时，返回第一个（按字母顺序）
    html_files.sort()
    logger.info(f"Found {len(html_files)} HTML files, using: {html_files[0].name}")
    return html_files[0]


def extract_messages_from_html(html_path: Path) -> list:
    """
    从 HTML 文件中提取所有消息 JSON 对象
    
    Args:
        html_path: HTML 文件路径
    
    Returns:
        list: 消息对象列表
    
    说明：
        - 使用正则表达式匹配 HTML 中嵌入的 JSON 对象
        - 跳过解析失败的对象
        - 返回所有成功解析的消息
    
    Example:
        >>> messages = extract_messages_from_html(Path("export.html"))
        >>> print(len(messages))
        1234
    """
    with open(html_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    # 匹配 HTML 中的 JSON 消息对象
    pattern = r'\{"type":\s*\d+,\s*"sub_type":\s*\d+[^}]+\}'
    matches = re.findall(pattern, content)
    
    messages = []
    for match in matches:
        try:
            msg = json.loads(match)
            messages.append(msg)
        except json.JSONDecodeError:
            continue
    
    return messages


def build_quote_lookup(html_messages: list) -> dict:
    """
    构建引用消息查找表
    
    Args:
        html_messages: HTML 中提取的消息列表
        
    Returns:
        dict: MsgSvrID -> quote_info 的映射字典
            quote_info 包含：
                - quote_svrid: 被引用消息的 svrid
                - quote_type: 被引用消息的类型
                - quote_text: 被引用消息的文本（已匿名化）
    
    匿名化策略：
        - 使用 anonymize_speaker_prefix() 处理引用文本
        - 将 "用户A: 你好" 转换为 "P1: 你好"
        - 保护隐私，避免泄露真实姓名
    
    Example:
        >>> lookup = build_quote_lookup(html_messages)
        >>> print(lookup["123456"])
        {'quote_svrid': '789', 'quote_type': 1, 'quote_text': 'P1: 你好'}
    """
    lookup = {}
    for msg in html_messages:
        if msg.get("type") == 49 and msg.get("sub_type") == 57:
            msg_svr_id = msg.get("MsgSvrID")
            if msg_svr_id:
                # 匿名化引用文本
                raw_quote_text = msg.get("refer_text")
                anonymized_quote_text = anonymize_speaker_prefix(raw_quote_text)
                
                lookup[msg_svr_id] = {
                    "quote_svrid": msg.get("svrid"),
                    "quote_type": msg.get("refermsg_type"),
                    "quote_text": anonymized_quote_text,
                }
    return lookup


def load_type49_messages(messages_path: Path) -> list:
    """
    加载 P1_messages_raw.jsonl 并过滤 type=49 消息
    
    Args:
        messages_path: 消息文件路径
        
    Returns:
        list: type=49 的消息列表
    
    说明：
        - type=49 包含：链接、文件、小程序、引用、视频号等
        - 跳过解析失败的行
        - 返回所有 type=49 的消息
    
    Example:
        >>> messages = load_type49_messages(Path("P1_messages_raw.jsonl"))
        >>> print(len(messages))
        567
    """
    messages = []
    with open(messages_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
                if msg.get("type") == 49:
                    messages.append(msg)
            except json.JSONDecodeError:
                continue
    return messages


def main():
    """
    主函数：执行 Linkfile 提取和匿名化
    
    流程：
    1. 查找导出目录中的 HTML 文件
    2. 从 HTML 提取消息 JSON 对象
    3. 构建引用查找表（MsgSvrID -> quote_info）
    4. 加载 P1_messages_raw.jsonl 并过滤 type=49 消息
    5. 初始化 LinkfileExtractor
    6. 对每条消息：
       - 匹配引用信息（通过 MsgSvrID）
       - 调用 extractor._extract_one() 提取元数据
       - 匿名化说话人前缀
    7. 输出到 linkfile_extract_v1.jsonl
    8. 打印统计信息
    
    输出统计：
        - 提取的记录数
        - sub_type 分布
        - link_sub_type 分布
    
    Raises:
        FileNotFoundError: 如果 HTML 文件或消息文件不存在
    """
    logger.info("=" * 60)
    logger.info("Linkfile Pipeline - Step 1: Extract and Anonymize")
    logger.info("=" * 60)
    
    # 加载配置
    config = load_linkfile_config()
    workspace_root = get_root()
    logger.info(f"Workspace: {workspace_root}")
    
    # 查找 HTML 文件
    logger.info("Finding HTML file...")
    html_file = find_html_file()
    logger.info(f"  Using: {html_file}")
    
    # 从 HTML 提取消息
    logger.info("Extracting messages from HTML...")
    html_messages = extract_messages_from_html(html_file)
    logger.info(f"  Extracted {len(html_messages)} messages from HTML")
    
    # 构建引用查找表
    logger.info("Building quote lookup...")
    quote_lookup = build_quote_lookup(html_messages)
    logger.info(f"  Found {len(quote_lookup)} quote references")
    
    # 加载 type=49 消息
    messages_path = get_messages_path()
    logger.info(f"Loading type=49 messages from {messages_path}...")
    type49_messages = load_type49_messages(messages_path)
    logger.info(f"  Found {len(type49_messages)} type=49 messages")
    
    if not type49_messages:
        logger.warning("No type=49 messages found. Exiting.")
        return
    
    # 初始化提取器
    extractor = LinkfileExtractor(config, workspace_root)
    logger.info(f"Supported sub_types: {extractor.get_supported_sub_types()}")
    
    # 统计各 sub_type 数量
    sub_type_counts = {}
    for msg in type49_messages:
        st = msg.get('sub_type', 'unknown')
        sub_type_counts[st] = sub_type_counts.get(st, 0) + 1
    logger.info(f"Sub-type distribution: {sub_type_counts}")
    
    # 处理消息
    logger.info("Extracting linkfile metadata...")
    results = []
    for msg in tqdm(type49_messages, desc="Extracting"):
        # 获取 MsgSvrID 用于查找引用信息
        msg_uid = msg.get("msg_uid", "")
        if ":" in msg_uid:
            msg_svr_id = msg_uid.split(":")[1]
        else:
            msg_svr_id = msg.get("MsgSvrID")
        
        # 构建该消息的引用查找表
        msg_quote_lookup = {}
        if msg_svr_id and msg_svr_id in quote_lookup:
            msg_quote_lookup[msg_svr_id] = quote_lookup[msg_svr_id]
        
        result = extractor._extract_one(msg, msg_quote_lookup)
        if result:
            results.append(result)
    
    logger.info(f"  Extracted {len(results)} records")
    
    # 输出结果
    output_dir = get_linkfile_before_merge()
    output_dir.mkdir(parents=True, exist_ok=True)
    
    output_filename = config.get('output_files', {}).get('extract', 'linkfile_extract_v1.jsonl')
    output_path = output_dir / output_filename
    
    logger.info(f"Writing to {output_path}...")
    with open(output_path, "w", encoding="utf-8") as f:
        for record in results:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    
    logger.info(f"Done. Wrote {len(results)} records.")
    
    # 统计输出的 link_sub_type 分布
    link_sub_type_counts = {}
    for r in results:
        lst = r.get('link_sub_type', 'unknown')
        link_sub_type_counts[lst] = link_sub_type_counts.get(lst, 0) + 1
    logger.info(f"Output link_sub_type distribution: {link_sub_type_counts}")


if __name__ == "__main__":
    main()
