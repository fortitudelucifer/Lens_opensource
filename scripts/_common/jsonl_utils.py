#!/usr/bin/env python3
"""
JSONL 工具模块 (JSONL Utilities)

功能：
- 提供统一的 JSONL 文件读写接口
- 支持按键加载（字典模式）和列表加载
- 支持原地更新和备份
- 被所有模态的流水线脚本共用

核心函数：
- load_jsonl_by_key(): 加载为字典（按 msg_uid 索引）
- load_jsonl_list(): 加载为列表
- write_jsonl(): 写入 JSONL 文件
- backup_file(): 创建备份
- update_jsonl_in_place(): 原地更新（自动备份）

使用场景：
1. 加载引擎输出：load_jsonl_by_key(ocr_v1.jsonl, key_field='msg_uid')
2. 合并多引擎结果：update_jsonl_in_place() 或自定义 merge_fn
3. 更新时间轴：load_jsonl_list() + 遍历 + write_jsonl()

依赖：
- 标准库：json, os, shutil, logging

作者：forcifer
项目：CHAT_APP_DHA - CHAT_APP聊天记录多模态处理流水线
更新于：2026-02-02
"""

import os
import json
import shutil
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional, Callable

logger = logging.getLogger(__name__)


def load_jsonl_by_key(file_path: str, key_field: str = 'msg_uid', key: str = None) -> Dict[str, dict]:
    """
    加载 JSONL 文件为字典（按指定字段索引）
    
    用于快速查找和合并场景，例如：
    - 按 msg_uid 索引消息记录
    - 合并多引擎输出（OCR + Caption）
    - 更新时间轴（按 msg_uid 匹配）
    
    Args:
        file_path: JSONL 文件路径
        key_field: 用作字典键的字段名（默认：'msg_uid'）
        key: key_field 的别名（向后兼容 merge_utils）
    
    Returns:
        Dict[str, dict]: 字典，键为 key_field 的值，值为记录字典
        如果文件不存在，返回空字典 {}
    
    Example:
        >>> data = load_jsonl_by_key('image_ocr_v1.jsonl')
        >>> print(data['msg_123'])
        {'msg_uid': 'msg_123', 'ocr_text': '你好', ...}
        
        >>> # 按自定义字段索引
        >>> by_path = load_jsonl_by_key('records.jsonl', key_field='media_path')
    """
    # Support both 'key' and 'key_field' parameter names
    if key is not None:
        key_field = key
    data = {}
    if not os.path.exists(file_path):
        logger.warning(f"File not found: {file_path}")
        return data
        
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
                key = item.get(key_field)
                if key:
                    data[key] = item
            except json.JSONDecodeError as e:
                logger.debug(f"Skipping invalid JSON line: {e}")
    return data


def load_jsonl_list(file_path: str) -> List[dict]:
    """
    加载 JSONL 文件为列表（保持原始顺序）
    
    用于需要遍历所有记录的场景，例如：
    - 时间轴更新（按时间戳顺序）
    - 批量处理（逐条处理）
    - 统计分析
    
    Args:
        file_path: JSONL 文件路径
    
    Returns:
        List[dict]: 记录列表，按文件中的顺序
        如果文件不存在，返回空列表 []
    
    Example:
        >>> messages = load_jsonl_list('P1_messages_raw.jsonl')
        >>> for msg in messages:
        ...     print(msg['ts'], msg['text_raw'])
        
        >>> # 统计
        >>> total = len(messages)
        >>> image_count = sum(1 for m in messages if m['modality'] == 'image')
    """
    items = []
    if not os.path.exists(file_path):
        logger.warning(f"File not found: {file_path}")
        return items
        
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return items


def write_jsonl(file_path: str, items: List[dict], ensure_ascii: bool = False) -> int:
    """
    写入记录列表到 JSONL 文件
    
    自动创建目录，覆盖已存在的文件。
    
    Args:
        file_path: 输出文件路径
        items: 要写入的记录列表
        ensure_ascii: 是否转义非 ASCII 字符（默认 False，保留中文）
    
    Returns:
        int: 写入的记录数
    
    Example:
        >>> records = [
        ...     {'msg_uid': 'msg_1', 'text': '你好'},
        ...     {'msg_uid': 'msg_2', 'text': '世界'}
        ... ]
        >>> count = write_jsonl('output.jsonl', records)
        >>> print(f"写入 {count} 条记录")
        
        >>> # 写入 ASCII 转义格式（用于兼容性）
        >>> write_jsonl('output_ascii.jsonl', records, ensure_ascii=True)
    """
    os.makedirs(os.path.dirname(file_path) or '.', exist_ok=True)
    with open(file_path, 'w', encoding='utf-8') as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=ensure_ascii) + '\n')
    return len(items)


def backup_file(file_path: str, suffix: str = '.bak') -> Optional[str]:
    """
    创建文件备份
    
    用于原地更新前保护原始数据。
    
    Args:
        file_path: 要备份的文件路径
        suffix: 备份文件后缀（默认：'.bak'）
    
    Returns:
        Optional[str]: 备份文件路径，如果原文件不存在则返回 None
    
    Example:
        >>> backup_path = backup_file('timeline.jsonl')
        >>> print(f"备份到: {backup_path}")
        备份到: timeline.jsonl.bak
        
        >>> # 自定义后缀
        >>> backup_file('data.jsonl', suffix='.20260202')
    """
    if not os.path.exists(file_path):
        return None
        
    backup_path = str(file_path) + suffix
    shutil.copy(file_path, backup_path)
    logger.info(f"Backed up {file_path} -> {backup_path}")
    return backup_path


def update_jsonl_in_place(
    file_path: str,
    update_data: Dict[str, dict],
    key_field: str = 'msg_uid',
    merge_fn: Optional[Callable[[dict, dict], dict]] = None
) -> int:
    """
    原地更新 JSONL 文件（自动备份）
    
    根据 key_field 匹配记录，合并更新数据。
    自动创建 .bak 备份，使用临时文件保证原子性。
    
    Args:
        file_path: 要更新的 JSONL 文件路径
        update_data: 更新数据字典，键为 key_field 的值，值为更新记录
        key_field: 用于匹配的字段名（默认：'msg_uid'）
        merge_fn: 可选的合并函数 (original, update) -> merged
                  默认：item.update(update_rec)，即更新字段覆盖原字段
    
    Returns:
        int: 更新的记录数
    
    Example:
        >>> # 更新 OCR 结果到时间轴
        >>> ocr_data = load_jsonl_by_key('image_ocr_v1.jsonl')
        >>> updates = {
        ...     uid: {'image_ocr_text': rec['ocr_text']}
        ...     for uid, rec in ocr_data.items()
        ... }
        >>> count = update_jsonl_in_place('timeline.jsonl', updates)
        >>> print(f"更新了 {count} 条记录")
        
        >>> # 自定义合并逻辑
        >>> def merge_scores(orig, upd):
        ...     orig['scores'] = {**orig.get('scores', {}), **upd.get('scores', {})}
        ...     return orig
        >>> update_jsonl_in_place('data.jsonl', updates, merge_fn=merge_scores)
    """
    if not os.path.exists(file_path):
        logger.warning(f"File not found: {file_path}")
        return 0
        
    backup_file(file_path)
    
    temp_path = str(file_path) + '.tmp'
    updated_count = 0
    
    with open(file_path, 'r', encoding='utf-8') as fin, \
         open(temp_path, 'w', encoding='utf-8') as fout:
        for line in fin:
            try:
                item = json.loads(line)
                key = item.get(key_field)
                
                if key and key in update_data:
                    update_rec = update_data[key]
                    if merge_fn:
                        item = merge_fn(item, update_rec)
                    else:
                        item.update(update_rec)
                    updated_count += 1
                    
                fout.write(json.dumps(item, ensure_ascii=False) + '\n')
            except json.JSONDecodeError:
                fout.write(line)
                
    os.replace(temp_path, file_path)
    return updated_count
