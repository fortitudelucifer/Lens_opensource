#!/usr/bin/env python3
"""
表情包下载模块 - URL 去重 + SHA256 哈希

功能：
- 从原始消息中筛选表情包消息（modality == "sticker", type == 47）
- URL 去重（相同 URL 只下载一次）
- 并发下载表情包文件
- 计算 SHA256 哈希（用于后续去重）
- 支持重试机制（最多3次，指数退避）
- 支持跳过已下载文件

处理流程：
1. 加载原始消息（P1_messages_raw.jsonl）
2. 筛选表情包消息（modality == "sticker"）
3. 提取 URL（从 text_raw 或 media_path 字段）
4. URL 去重（相同 URL 只下载一次，但为每个 msg_uid 创建记录）
5. 并发下载（默认5个并发）
6. 计算 SHA256 哈希
7. 保存到临时缓存目录（/data/cache/sticker/temp/）
8. 输出下载记录（sticker_download_v1.jsonl）

输入：
- raw/P1_messages_raw.jsonl
  * msg_uid, ts, speaker, type, modality, text_raw, media_path

输出：
- artifacts/before_merge/sticker/sticker_download_v1.jsonl
  * msg_uid, url, http_status, bytes, elapsed_ms, retry_count
  * content_type_reported, raw_path, file_sha256, error
  * 保留所有原始消息字段（seq_in_html, MsgSvrID, token等）

存储：
- /data/cache/sticker/temp/{msg_uid}_{sha256[:16]}.bin
  * 使用 msg_uid 和 SHA256 前16位作为文件名
  * 二进制格式存储（.bin）

依赖：
- scripts/_common/path_utils.py (load_sticker_config, get_sticker_temp_cache)
- scripts/_common/jsonl_utils.py (load_jsonl_list, write_jsonl)
- scripts/_common/media_filter.py (create_download_failed_marker)
- configs/sticker.yaml (网络配置：超时、重试、User-Agent)

使用示例：
    # 完整处理
    python scripts/sticker/run_all/_01_run_download.py
    
    # 测试模式（只处理前10个）
    python scripts/sticker/run_all/_01_run_download.py --sample 10
    
    # 增加并发数（10个并发）
    python scripts/sticker/run_all/_01_run_download.py --concurrency 10
    
    # 跳过已下载的文件
    python scripts/sticker/run_all/_01_run_download.py --skip-existing

URL 去重策略：
- 相同 URL 只下载一次（节省带宽和时间）
- 但为每个 msg_uid 创建独立的记录（保留消息关联）
- 示例：
  * msg_123 和 msg_456 使用相同的表情包 URL
  * 只下载一次，但输出两条记录（msg_123 和 msg_456）
  * 两条记录的 file_sha256 和 raw_path 相同

SHA256 哈希用途：
- 用于后续的内容去重（_06_merge_engine.py）
- 相同内容的表情包（即使 URL 不同）可以复用处理结果
- 文件名包含 SHA256 前16位，便于识别

重试机制：
- 最多重试3次（可配置）
- 指数退避：1秒、2秒、4秒
- 超时设置：连接10秒、读取30秒（可配置）

作者：[Author]
更新于：2026-02-02
"""

import os
import sys
import json
import hashlib
import argparse
import time
import logging
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, Dict, List, Tuple

import requests
from tqdm import tqdm

# 确保 tqdm 输出到 stderr 以便实时显示
tqdm_kwargs = {"file": sys.stderr, "dynamic_ncols": True}

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from scripts._common.path_utils import (
    load_sticker_config, get_sticker_dir, get_sticker_before_merge,
    get_sticker_temp_cache, get_messages_path
)
from scripts._common.jsonl_utils import load_jsonl_list, write_jsonl
from scripts._common.media_filter import (
    SkipReason, create_download_failed_marker
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def extract_url(record: dict) -> Optional[str]:
    """
    从记录中提取 URL，去除 raw/ 前缀
    
    提取逻辑：
    1. 优先从 text_raw 字段提取
    2. 如果 text_raw 为空，从 media_path 字段提取
    3. 去除 "raw/" 前缀（如果存在）
    
    Args:
        record: 消息记录
    
    Returns:
        URL 字符串，如果未找到则返回 None
    
    Example:
        >>> record = {"text_raw": "raw/https://example.com/sticker.gif"}
        >>> extract_url(record)
        "https://example.com/sticker.gif"
        
        >>> record = {"media_path": "https://example.com/sticker.gif"}
        >>> extract_url(record)
        "https://example.com/sticker.gif"
    """
    for field in ['text_raw', 'media_path']:
        value = record.get(field, '')
        if value and value.startswith('raw/http'):
            return value[4:]  # 去除 "raw/" 前缀
        elif value and value.startswith('http'):
            return value
    return None


def calculate_sha256(data: bytes) -> str:
    """
    计算数据的 SHA256 哈希
    
    Args:
        data: 二进制数据
    
    Returns:
        SHA256 哈希字符串（64位十六进制）
    
    Example:
        >>> data = b"Hello, World!"
        >>> calculate_sha256(data)
        "dffd6021bb2bd5b0af676290809ec3a53191dd81c7f70a4b28688a362182986f"
    """
    return hashlib.sha256(data).hexdigest()


def download_sticker(
    url: str,
    msg_uid: str,
    temp_dir: Path,
    config: dict,
    skip_existing: bool = False
) -> Dict:
    """
    下载单个表情包
    
    下载流程：
    1. 从配置中读取网络参数（超时、重试、User-Agent）
    2. 发送 HTTP GET 请求（带重试机制）
    3. 检查 HTTP 状态码（只接受200）
    4. 读取内容并计算 SHA256 哈希
    5. 构建文件名：{msg_uid}_{sha256[:16]}.bin
    6. 保存到临时缓存目录
    7. 返回下载结果
    
    重试机制：
    - 最多重试3次（可配置）
    - 指数退避：1秒、2秒、4秒
    - 超时异常和请求异常都会触发重试
    
    Args:
        url: 表情包 URL
        msg_uid: 消息 UID（用于文件名）
        temp_dir: 临时缓存目录
        config: 配置字典（包含网络参数）
        skip_existing: 是否跳过已存在的文件
    
    Returns:
        下载结果字典：
        - schema_version: "sticker_download_v1"
        - msg_uid: 消息 UID
        - url: 表情包 URL
        - http_status: HTTP 状态码
        - bytes: 文件大小（字节）
        - elapsed_ms: 下载耗时（毫秒）
        - retry_count: 重试次数
        - content_type_reported: Content-Type 头
        - raw_path: 文件路径
        - file_sha256: SHA256 哈希
        - error: 错误信息（如果失败）
    
    Example:
        >>> config = load_sticker_config()
        >>> temp_dir = Path("/data/cache/sticker/temp")
        >>> result = download_sticker(
        ...     "https://example.com/sticker.gif",
        ...     "msg_123",
        ...     temp_dir,
        ...     config
        ... )
        >>> print(result["file_sha256"])
        "a1b2c3d4e5f6..."
        >>> print(result["raw_path"])
        "/data/cache/sticker/temp/msg_123_a1b2c3d4e5f6.bin"
    """
    result = {
        "schema_version": "sticker_download_v1",
        "msg_uid": msg_uid,
        "url": url,
        "http_status": None,
        "bytes": 0,
        "elapsed_ms": 0,
        "retry_count": 0,
        "content_type_reported": None,
        "raw_path": None,
        "file_sha256": None,
        "error": None
    }
    
    net_cfg = config.get('networking', {})
    timeout = (
        net_cfg.get('timeout', {}).get('connect_sec', 10),
        net_cfg.get('timeout', {}).get('read_sec', 30)
    )
    max_retries = net_cfg.get('retries', {}).get('max', 3)
    base_sec = net_cfg.get('retries', {}).get('base_sec', 1.0)
    user_agent = net_cfg.get('headers', {}).get('user_agent', 'sticker-fetcher/1.0')
    
    headers = {'User-Agent': user_agent}
    
    start_time = time.time()
    
    for attempt in range(max_retries):
        try:
            response = requests.get(url, headers=headers, timeout=timeout, stream=True)
            result["http_status"] = response.status_code
            result["content_type_reported"] = response.headers.get('Content-Type', '')
            
            if response.status_code != 200:
                result["error"] = f"HTTP {response.status_code}"
                result["retry_count"] = attempt
                continue
            
            # 读取内容
            content = response.content
            result["bytes"] = len(content)
            
            # 计算 SHA256
            file_sha256 = calculate_sha256(content)
            result["file_sha256"] = file_sha256
            
            # 构建文件名（使用 msg_uid 的安全版本）
            safe_uid = msg_uid.replace(':', '_')
            filename = f"{safe_uid}_{file_sha256[:16]}.bin"
            filepath = temp_dir / filename
            
            # 检查是否已存在
            if skip_existing and filepath.exists():
                result["raw_path"] = str(filepath)
                result["elapsed_ms"] = int((time.time() - start_time) * 1000)
                return result
            
            # 保存文件
            with open(filepath, 'wb') as f:
                f.write(content)
            
            result["raw_path"] = str(filepath)
            result["elapsed_ms"] = int((time.time() - start_time) * 1000)
            result["retry_count"] = attempt
            return result
            
        except requests.exceptions.Timeout:
            result["error"] = "Timeout"
            result["retry_count"] = attempt + 1
            if attempt < max_retries - 1:
                time.sleep(base_sec * (2 ** attempt))
        except requests.exceptions.RequestException as e:
            result["error"] = str(e)
            result["retry_count"] = attempt + 1
            if attempt < max_retries - 1:
                time.sleep(base_sec * (2 ** attempt))
    
    result["elapsed_ms"] = int((time.time() - start_time) * 1000)
    
    # 下载失败，添加跳过标记
    if result.get("error"):
        skip_marker = create_download_failed_marker(
            url=url,
            http_status=result.get("http_status"),
            error_msg=result.get("error")
        )
        result.update(skip_marker)
    
    return result


def filter_sticker_messages(messages: List[dict]) -> List[dict]:
    """
    筛选 sticker 消息，保留所有原始字段
    
    筛选条件：
    - modality == "sticker"
    - type == 47（微信表情包消息类型）
    - 必须包含有效的 URL
    
    Args:
        messages: 原始消息列表
    
    Returns:
        表情包消息列表（包含 url 字段）
    
    Example:
        >>> messages = [
        ...     {"msg_uid": "msg_1", "modality": "text", "type": 1},
        ...     {"msg_uid": "msg_2", "modality": "sticker", "type": 47, "text_raw": "https://..."},
        ...     {"msg_uid": "msg_3", "modality": "image", "type": 3}
        ... ]
        >>> stickers = filter_sticker_messages(messages)
        >>> len(stickers)
        1
        >>> stickers[0]["msg_uid"]
        "msg_2"
    """
    stickers = []
    for msg in messages:
        if msg.get('modality') == 'sticker' and msg.get('type') == 47:
            url = extract_url(msg)
            if url:
                # 保留所有原始字段
                sticker = msg.copy()
                sticker['url'] = url
                stickers.append(sticker)
    return stickers


def main():
    """
    主函数：表情包下载流程
    
    处理步骤：
    1. 解析命令行参数
    2. 加载配置和路径
    3. 加载原始消息
    4. 筛选表情包消息
    5. URL 去重（相同 URL 只下载一次）
    6. 并发下载（ThreadPoolExecutor）
    7. 为每个 msg_uid 创建记录（即使 URL 相同）
    8. 保存下载结果
    9. 打印统计信息（成功数、失败数）
    
    命令行参数：
        --sample: 只处理前 N 个（测试用）
        --concurrency: 并发下载数（默认5）
        --skip-existing: 跳过已下载的文件
    
    输出统计：
        - 成功下载数
        - 失败下载数
    
    Example:
        >>> python scripts/sticker/run_all/_01_run_download.py --sample 10 --concurrency 3
        加载消息文件: raw/P1_messages_raw.jsonl
        共加载 5000 条消息
        筛选出 500 条 sticker 消息
        采样模式: 仅处理前 10 个
        去重后 8 个唯一 URL
        下载表情包: 100%|████████| 8/8 [00:02<00:00, 4.00it/s]
        下载完成: 成功 8, 失败 0
        结果已保存到: artifacts/before_merge/sticker/sticker_download_v1.jsonl
    """
    parser = argparse.ArgumentParser(description='下载表情包')
    parser.add_argument('--sample', type=int, help='仅处理前 N 个')
    parser.add_argument('--concurrency', type=int, default=5, help='并发下载数')
    parser.add_argument('--skip-existing', action='store_true', help='跳过已下载的文件')
    args = parser.parse_args()
    
    # 加载配置
    config = load_sticker_config()
    
    # 设置路径
    messages_path = get_messages_path()
    temp_dir = get_sticker_temp_cache()
    output_dir = get_sticker_before_merge()
    
    temp_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 加载消息
    logger.info(f"加载消息文件: {messages_path}")
    messages = load_jsonl_list(str(messages_path))
    logger.info(f"共加载 {len(messages)} 条消息")
    
    # 筛选 sticker 消息
    stickers = filter_sticker_messages(messages)
    logger.info(f"筛选出 {len(stickers)} 条 sticker 消息")
    
    if args.sample:
        stickers = stickers[:args.sample]
        logger.info(f"采样模式: 仅处理前 {args.sample} 个")
    
    # URL 去重（相同 URL 只下载一次）
    url_to_stickers = {}
    for s in stickers:
        url = s['url']
        if url not in url_to_stickers:
            url_to_stickers[url] = []
        url_to_stickers[url].append(s)
    
    unique_urls = list(url_to_stickers.keys())
    logger.info(f"去重后 {len(unique_urls)} 个唯一 URL")
    
    # 下载
    results = []
    
    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = {}
        for url in unique_urls:
            # 使用第一个 msg_uid 作为文件名
            first_sticker = url_to_stickers[url][0]
            future = executor.submit(
                download_sticker,
                url,
                first_sticker['msg_uid'],
                temp_dir,
                config,
                args.skip_existing
            )
            futures[future] = url_to_stickers[url]
        
        with tqdm(total=len(futures), desc="下载表情包", **tqdm_kwargs) as pbar:
            for future in as_completed(futures):
                sticker_list = futures[future]
                try:
                    result = future.result()
                    # 为每个使用相同 URL 的消息创建记录
                    for s in sticker_list:
                        record = result.copy()
                        # 保留所有原始消息字段
                        record['msg_uid'] = s.get('msg_uid', '')
                        record['seq_in_html'] = s.get('seq_in_html', -1)
                        record['MsgSvrID'] = s.get('MsgSvrID', '')
                        record['token'] = s.get('token', '')
                        record['ts'] = s.get('ts', 0)
                        record['time_local'] = s.get('time_local', '')
                        record['speaker'] = s.get('speaker', 'UNKNOWN')
                        record['type'] = s.get('type', 47)
                        record['sub_type'] = s.get('sub_type', 0)
                        record['modality'] = 'sticker'
                        record['text_raw'] = s.get('text_raw', '')
                        record['media_path'] = s.get('media_path', '')
                        results.append(record)
                except Exception as e:
                    logger.error(f"下载失败: {e}")
                    for s in sticker_list:
                        results.append({
                            "schema_version": "sticker_download_v1",
                            "msg_uid": s.get('msg_uid', ''),
                            "seq_in_html": s.get('seq_in_html', -1),
                            "MsgSvrID": s.get('MsgSvrID', ''),
                            "token": s.get('token', ''),
                            "ts": s.get('ts', 0),
                            "time_local": s.get('time_local', ''),
                            "speaker": s.get('speaker', 'UNKNOWN'),
                            "type": s.get('type', 47),
                            "sub_type": s.get('sub_type', 0),
                            "modality": 'sticker',
                            "text_raw": s.get('text_raw', ''),
                            "media_path": s.get('media_path', ''),
                            "url": s.get('url', ''),
                            "error": str(e)
                        })
                pbar.update(1)
    
    # 统计
    success = sum(1 for r in results if r.get('raw_path'))
    failed = len(results) - success
    logger.info(f"下载完成: 成功 {success}, 失败 {failed}")
    
    # 保存结果
    output_path = output_dir / "sticker_download_v1.jsonl"
    write_jsonl(str(output_path), results)
    logger.info(f"结果已保存到: {output_path}")


if __name__ == '__main__':
    main()
