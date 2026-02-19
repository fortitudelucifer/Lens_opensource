#!/usr/bin/env python3
"""
表情包格式嗅探模块 - Magic Bytes 识别 + Pillow 解码验证

功能：
- 使用 Magic Bytes 识别文件格式（GIF/WebP/PNG/JPEG）
- Pillow 解码验证（检查文件完整性和尺寸）
- 检测 Content-Type 不匹配
- 移动文件到 raw/sticker/ 并重命名（添加正确的扩展名）
- 生成 QC 报告（解码成功/失败统计）

处理流程：
1. 加载下载结果（sticker_download_v1.jsonl）
2. 筛选成功下载的记录（有 raw_path 和 file_sha256）
3. 读取文件头（前12字节）
4. Magic Bytes 检测：
   - GIF: "GIF87a" 或 "GIF89a"
   - WebP: RIFF 容器 + "WEBP" 标识
   - PNG: \x89PNG\r\n\x1a\n
   - JPEG: \xff\xd8
5. Pillow 解码验证：
   - img.verify() 验证完整性
   - 获取尺寸（width, height, megapixels）
   - 检测解压炸弹（DecompressionBombWarning）
6. 检查 Content-Type 是否匹配
7. 移动文件到 raw/sticker/ 并重命名（{msg_uid}_{sha256[:16]}.{ext}）
8. 输出嗅探结果和 QC 报告

输入：
- artifacts/before_merge/sticker/sticker_download_v1.jsonl
  * msg_uid, file_sha256, raw_path, content_type_reported

输出：
- artifacts/before_merge/sticker/sticker_sniff_v1.jsonl
  * msg_uid, file_sha256, detected_format, detected_ext
  * sniff_rule, content_type_reported, mismatch, final_path
- artifacts/before_merge/sticker/sticker_decode_qc_v1.jsonl
  * msg_uid, file_sha256, decode_ok, width, height, megapixels
  * exception_type, exception_message, decompression_bomb_flag

存储：
- raw/sticker/{msg_uid}_{sha256[:16]}.{ext}
  * 使用 msg_uid 和 SHA256 前16位作为文件名
  * 扩展名根据 Magic Bytes 检测结果确定

依赖：
- scripts/_common/path_utils.py (load_sticker_config, get_sticker_dir)
- scripts/_common/jsonl_utils.py (load_jsonl_list, write_jsonl)
- PIL (Pillow) - 图片解码验证

使用示例：
    # 完整处理
    python scripts/sticker/run_all/_02_run_sniff.py
    
    # 测试模式（只处理前10个）
    python scripts/sticker/run_all/_02_run_sniff.py --sample 10

Magic Bytes 检测规则：
- GIF: 文件头为 "GIF87a" 或 "GIF89a"（6字节）
- WebP: 文件头为 "RIFF" + 4字节长度 + "WEBP"（12字节）
- PNG: 文件头为 \x89PNG\r\n\x1a\n（8字节）
- JPEG: 文件头为 \xff\xd8（2字节）
- Unknown: 无法识别的格式（保存为 .bin）

Content-Type 不匹配检测：
- 比较 Magic Bytes 检测结果与 HTTP Content-Type 头
- 如果不匹配，设置 mismatch=True
- 示例：Content-Type 为 "image/jpeg"，但 Magic Bytes 检测为 "gif"

Pillow 解码验证：
- img.verify(): 验证文件完整性（不加载像素数据）
- 重新打开获取尺寸（verify 后需要重新打开）
- 计算 megapixels（width * height / 1,000,000）
- 捕获异常：DecompressionBombWarning, IOError, OSError 等

作者：forcifer
更新于：2026-02-02
"""

import os
import sys
import json
import shutil
import argparse
import logging
from pathlib import Path
from typing import Optional, Dict, Tuple

from PIL import Image
from tqdm import tqdm

# 确保 tqdm 输出到 stderr 以便实时显示
tqdm_kwargs = {"file": sys.stderr, "dynamic_ncols": True}

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from scripts._common.path_utils import (
    load_sticker_config, get_sticker_dir, get_sticker_before_merge,
    get_sticker_temp_cache
)
from scripts._common.jsonl_utils import load_jsonl_list, write_jsonl

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 设置 Pillow 解压炸弹保护
Image.MAX_IMAGE_PIXELS = 26000000


def detect_format_by_magic(data: bytes) -> Tuple[str, str]:
    """
    通过 magic bytes 检测文件格式
    
    检测规则：
    - GIF: 文件头为 "GIF87a" 或 "GIF89a"（6字节）
    - WebP: 文件头为 "RIFF" + 4字节长度 + "WEBP"（12字节）
    - PNG: 文件头为 \x89PNG\r\n\x1a\n（8字节）
    - JPEG: 文件头为 \xff\xd8（2字节）
    - Unknown: 无法识别的格式
    
    Args:
        data: 文件头数据（至少12字节）
    
    Returns:
        (format_name, extension) 元组
        - format_name: "gif", "webp", "png", "jpeg", "unknown"
        - extension: ".gif", ".webp", ".png", ".jpg", ".bin"
    
    Example:
        >>> with open("sticker.gif", "rb") as f:
        ...     header = f.read(12)
        >>> detect_format_by_magic(header)
        ("gif", ".gif")
    """
    if len(data) < 12:
        return "unknown", ".bin"
    
    # GIF: "GIF87a" 或 "GIF89a"
    if data[:6] in [b"GIF87a", b"GIF89a"]:
        return "gif", ".gif"
    
    # WebP: RIFF 容器，bytes[0:4]="RIFF" 且 bytes[8:12]="WEBP"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp", ".webp"
    
    # PNG: \x89PNG\r\n\x1a\n
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png", ".png"
    
    # JPEG: \xff\xd8
    if data[:2] == b"\xff\xd8":
        return "jpeg", ".jpg"
    
    return "unknown", ".bin"


def validate_with_pillow(filepath: Path) -> Dict:
    """
    使用 Pillow 验证图片文件
    
    验证流程：
    1. 使用 img.verify() 验证文件完整性
    2. 重新打开获取尺寸（verify 后需要重新打开）
    3. 计算 megapixels（width * height / 1,000,000）
    4. 捕获异常（DecompressionBombWarning, IOError 等）
    
    Args:
        filepath: 图片文件路径
    
    Returns:
        验证结果字典：
        - decode_ok: 是否解码成功
        - width: 图片宽度（像素）
        - height: 图片高度（像素）
        - megapixels: 百万像素数
        - exception_type: 异常类型（如果失败）
        - exception_message: 异常信息（如果失败）
        - decompression_bomb_flag: 是否触发解压炸弹警告
    
    Example:
        >>> result = validate_with_pillow(Path("sticker.gif"))
        >>> print(result["decode_ok"])
        True
        >>> print(result["width"], result["height"])
        512 512
    """
    result = {
        "decode_ok": False,
        "width": None,
        "height": None,
        "megapixels": None,
        "exception_type": None,
        "exception_message": None,
        "decompression_bomb_flag": False
    }
    
    try:
        with Image.open(filepath) as img:
            img.verify()  # 验证完整性
        
        # 重新打开获取尺寸（verify 后需要重新打开）
        with Image.open(filepath) as img:
            result["decode_ok"] = True
            result["width"] = img.width
            result["height"] = img.height
            result["megapixels"] = round(img.width * img.height / 1_000_000, 3)
            
    except Image.DecompressionBombWarning:
        result["decompression_bomb_flag"] = True
        result["exception_type"] = "DecompressionBombWarning"
        result["exception_message"] = "Image exceeds pixel limit"
    except Exception as e:
        result["exception_type"] = type(e).__name__
        result["exception_message"] = str(e)
    
    return result


def process_sticker(record: dict, temp_dir: Path, raw_dir: Path, config: dict) -> Tuple[Dict, Dict]:
    """
    处理单个表情包：格式嗅探 + 解码验证 + 移动文件
    
    处理流程：
    1. 读取文件头（前12字节）
    2. Magic Bytes 检测格式
    3. 检查 Content-Type 是否匹配
    4. Pillow 解码验证
    5. 如果验证通过，移动文件到 raw/sticker/ 并重命名
    
    Args:
        record: 下载记录（包含 msg_uid, file_sha256, raw_path 等）
        temp_dir: 临时缓存目录
        raw_dir: 最终存储目录（raw/sticker/）
        config: 配置字典
    
    Returns:
        (sniff_result, qc_result) 元组
        - sniff_result: 嗅探结果（格式、扩展名、是否匹配等）
        - qc_result: QC 结果（解码状态、尺寸、异常等）
    
    Example:
        >>> record = {"msg_uid": "msg_123", "file_sha256": "abc...", "raw_path": "/tmp/file.bin"}
        >>> sniff, qc = process_sticker(record, temp_dir, raw_dir, config)
        >>> print(sniff["detected_format"])
        "gif"
        >>> print(qc["decode_ok"])
        True
    """
    msg_uid = record.get('msg_uid', '')
    file_sha256 = record.get('file_sha256', '')
    raw_path = record.get('raw_path', '')
    content_type = record.get('content_type_reported', '')
    
    sniff_result = {
        "schema_version": "sticker_sniff_v1",
        "msg_uid": msg_uid,
        "seq_in_html": record.get('seq_in_html', -1),
        "MsgSvrID": record.get('MsgSvrID', ''),
        "token": record.get('token', ''),
        "ts": record.get('ts', 0),
        "time_local": record.get('time_local', ''),
        "speaker": record.get('speaker', 'UNKNOWN'),
        "type": record.get('type', 47),
        "sub_type": record.get('sub_type', 0),
        "modality": 'sticker',
        "file_sha256": file_sha256,
        "raw_path": raw_path,
        "detected_format": None,
        "detected_ext": None,
        "sniff_rule": None,
        "content_type_reported": content_type,
        "mismatch": False,
        "final_path": None
    }
    
    qc_result = {
        "schema_version": "sticker_decode_qc_v1",
        "msg_uid": msg_uid,
        "seq_in_html": record.get('seq_in_html', -1),
        "file_sha256": file_sha256
    }
    
    # 检查文件是否存在
    if not raw_path or not Path(raw_path).exists():
        sniff_result["detected_format"] = "error"
        sniff_result["detected_ext"] = ".bin"
        qc_result["decode_ok"] = False
        qc_result["exception_type"] = "FileNotFoundError"
        qc_result["exception_message"] = f"File not found: {raw_path}"
        return sniff_result, qc_result
    
    # 读取文件头
    with open(raw_path, 'rb') as f:
        header = f.read(12)
    
    # Magic bytes 检测
    detected_format, detected_ext = detect_format_by_magic(header)
    sniff_result["detected_format"] = detected_format
    sniff_result["detected_ext"] = detected_ext
    sniff_result["sniff_rule"] = "magic_bytes"
    
    # 检查 Content-Type 是否匹配
    content_type_lower = content_type.lower() if content_type else ''
    expected_types = {
        "gif": ["image/gif"],
        "webp": ["image/webp"],
        "png": ["image/png"],
        "jpeg": ["image/jpeg", "image/jpg"]
    }
    if detected_format in expected_types:
        if not any(t in content_type_lower for t in expected_types[detected_format]):
            sniff_result["mismatch"] = True
    
    # Pillow 解码验证
    pillow_result = validate_with_pillow(Path(raw_path))
    qc_result.update(pillow_result)
    
    # 如果验证通过，移动文件到 raw/sticker/ 并重命名
    if pillow_result["decode_ok"]:
        safe_uid = msg_uid.replace(':', '_')
        new_filename = f"{safe_uid}_{file_sha256[:16]}{detected_ext}"
        new_path = raw_dir / new_filename
        
        # 确保目录存在
        raw_dir.mkdir(parents=True, exist_ok=True)
        
        # 移动文件
        if not new_path.exists():
            shutil.move(raw_path, new_path)
        sniff_result["final_path"] = str(new_path)
    else:
        sniff_result["final_path"] = raw_path
    
    return sniff_result, qc_result


def main():
    """
    主函数：表情包格式嗅探流程
    
    处理步骤：
    1. 解析命令行参数
    2. 加载配置和路径
    3. 加载下载结果
    4. 筛选成功下载的记录
    5. 逐个处理（格式嗅探 + 解码验证）
    6. 保存嗅探结果和 QC 报告
    7. 打印统计信息（解码成功/失败、格式分布、Content-Type 不匹配数）
    
    命令行参数：
        --sample: 只处理前 N 个（测试用）
    
    输出统计：
        - 解码验证：成功数、失败数
        - 格式分布：gif, webp, png, jpeg, unknown
        - Content-Type 不匹配数
    
    Example:
        >>> python scripts/sticker/run_all/_02_run_sniff.py --sample 10
        加载下载结果: artifacts/before_merge/sticker/sticker_download_v1.jsonl
        共加载 500 条记录
        有效记录: 480 条
        采样模式: 仅处理前 10 个
        格式嗅探: 100%|████████| 10/10 [00:01<00:00, 10.00it/s]
        解码验证: 成功 10, 失败 0
        格式分布: {'gif': 6, 'png': 3, 'webp': 1}
        Content-Type 不匹配: 0 条
        嗅探结果已保存到: artifacts/before_merge/sticker/sticker_sniff_v1.jsonl
        QC 结果已保存到: artifacts/before_merge/sticker/sticker_decode_qc_v1.jsonl
    """
    parser = argparse.ArgumentParser(description='表情包格式嗅探')
    parser.add_argument('--sample', type=int, help='仅处理前 N 个')
    args = parser.parse_args()
    
    # 加载配置
    config = load_sticker_config()
    
    # 设置路径
    temp_dir = get_sticker_temp_cache()
    raw_dir = get_sticker_dir()
    output_dir = get_sticker_before_merge()
    
    raw_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 加载下载结果
    download_path = output_dir / "sticker_download_v1.jsonl"
    logger.info(f"加载下载结果: {download_path}")
    downloads = load_jsonl_list(str(download_path))
    logger.info(f"共加载 {len(downloads)} 条记录")
    
    # 筛选成功下载的记录
    valid_downloads = [d for d in downloads if d.get('raw_path') and d.get('file_sha256')]
    logger.info(f"有效记录: {len(valid_downloads)} 条")
    
    if args.sample:
        valid_downloads = valid_downloads[:args.sample]
        logger.info(f"采样模式: 仅处理前 {args.sample} 个")
    
    # 处理
    sniff_results = []
    qc_results = []
    
    for record in tqdm(valid_downloads, desc="格式嗅探", **tqdm_kwargs):
        sniff_result, qc_result = process_sticker(record, temp_dir, raw_dir, config)
        sniff_results.append(sniff_result)
        qc_results.append(qc_result)
    
    # 统计
    decode_ok = sum(1 for r in qc_results if r.get('decode_ok'))
    decode_fail = len(qc_results) - decode_ok
    logger.info(f"解码验证: 成功 {decode_ok}, 失败 {decode_fail}")
    
    format_stats = {}
    for r in sniff_results:
        fmt = r.get('detected_format', 'unknown')
        format_stats[fmt] = format_stats.get(fmt, 0) + 1
    logger.info(f"格式分布: {format_stats}")
    
    mismatch_count = sum(1 for r in sniff_results if r.get('mismatch'))
    logger.info(f"Content-Type 不匹配: {mismatch_count} 条")
    
    # 保存结果
    sniff_path = output_dir / "sticker_sniff_v1.jsonl"
    qc_path = output_dir / "sticker_decode_qc_v1.jsonl"
    
    write_jsonl(str(sniff_path), sniff_results)
    write_jsonl(str(qc_path), qc_results)
    
    logger.info(f"嗅探结果已保存到: {sniff_path}")
    logger.info(f"QC 结果已保存到: {qc_path}")


if __name__ == '__main__':
    main()
