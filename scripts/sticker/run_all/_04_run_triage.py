#!/usr/bin/env python3
"""
表情包 Triage 模块 - NSFW/Gore 检测

功能：
- NSFW/Gore 内容检测（复用图片流水线的 ImageTriage）
- 动图逐帧检测（取最高分）
- 静图单帧检测（使用缩略图）
- 支持敏感内容标记

处理流程：
1. 加载 Meta 结果（sticker_meta_v1.jsonl）和 Frames 结果（sticker_frames_v1.jsonl）
2. 初始化 NSFW Classifier（ImageTriage）
3. 根据表情包类型选择检测策略：
   - 静图：单帧检测（使用缩略图）
   - 动图：逐帧检测（使用提取的关键帧）
4. 计算最高 NSFW/Gore 分数
5. 判断是否触发敏感内容阈值
6. 输出 Triage 结果

输入：
- artifacts/before_merge/sticker/sticker_meta_v1.jsonl
  * msg_uid, sticker_class, thumb_path, is_animated, n_frames
- artifacts/before_merge/sticker/sticker_frames_v1.jsonl
  * msg_uid, frame_paths

输出：
- artifacts/before_merge/sticker/sticker_triage_v1.jsonl
  * msg_uid, triage_method, max_nsfw_score, max_gore_score
  * is_sensitive, trigger_frames, content_type

依赖：
- scripts/_common/path_utils.py (load_sticker_config, get_sticker_before_merge)
- scripts/_common/jsonl_utils.py (load_jsonl_by_key, load_jsonl_list, write_jsonl)
- scripts/image/experts/image_triage.py (ImageTriage)

使用示例：
    # 完整处理
    python scripts/sticker/run_all/_04_run_triage.py
    
    # 测试模式（只处理前10个）
    python scripts/sticker/run_all/_04_run_triage.py --sample 10

检测策略：
- 静图（single_frame）：
  * 使用缩略图进行单次检测
  * 直接判断是否敏感
- 动图（per_frame_max）：
  * 逐帧检测所有关键帧
  * 取最高 NSFW/Gore 分数
  * 记录触发阈值的帧（trigger_frames）

敏感内容判断：
- NSFW 阈值：0.5（可配置）
- Gore 阈值：0.5（可配置）
- 超过阈值标记为 TYPE_A_NSFW 或 TYPE_B_GORE
- 否则标记为 TYPE_C_NORMAL

作者：forcifer
更新于：2026-02-02
"""

import os
import sys
import gc
import argparse
import logging
from pathlib import Path
from typing import Dict, List, Optional

import torch
from tqdm import tqdm

# 确保 tqdm 输出到 stderr 以便实时显示
tqdm_kwargs = {"file": sys.stderr, "dynamic_ncols": True}

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from scripts._common.path_utils import (
    load_sticker_config, get_sticker_before_merge
)
from scripts._common.jsonl_utils import load_jsonl_by_key, load_jsonl_list, write_jsonl

# 复用图片流水线的 Triage
from scripts.image.experts.image_triage import ImageTriage

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def triage_static_sticker(thumb_path: str, triage: ImageTriage, config: dict) -> Dict:
    """
    静态表情包 Triage：单帧检测
    
    处理流程：
    1. 使用 ImageTriage 对缩略图进行分类
    2. 获取 NSFW/Gore 分数
    3. 判断是否超过阈值
    4. 返回检测结果
    
    Args:
        thumb_path: 缩略图路径
        triage: ImageTriage 实例
        config: 配置字典（包含阈值）
    
    Returns:
        检测结果字典：
        - triage_method: "single_frame"
        - max_nsfw_score: NSFW 分数
        - max_gore_score: Gore 分数
        - is_sensitive: 是否敏感
        - trigger_frames: 触发帧列表（静图为空）
        - content_type: 内容类型
    
    Example:
        >>> result = triage_static_sticker("thumb.png", triage, config)
        >>> print(result["max_nsfw_score"])
        0.12
        >>> print(result["is_sensitive"])
        False
    """
    result = {
        "triage_method": "single_frame",
        "max_nsfw_score": 0.0,
        "max_gore_score": 0.0,
        "is_sensitive": False,
        "trigger_frames": [],
        "content_type": "TYPE_C_NORMAL"
    }
    
    if not thumb_path or not Path(thumb_path).exists():
        return result
    
    try:
        triage_result = triage.classify(thumb_path)
        result["max_nsfw_score"] = triage_result.nsfw_score
        result["content_type"] = triage_result.content_type
        
        nsfw_threshold = config.get('triage', {}).get('nsfw_threshold', 0.5)
        gore_threshold = config.get('triage', {}).get('gore_threshold', 0.5)
        
        if triage_result.nsfw_score > nsfw_threshold:
            result["is_sensitive"] = True
            result["content_type"] = "TYPE_A_NSFW"
        
    except Exception as e:
        logger.debug(f"Triage 失败 {thumb_path}: {e}")
    
    return result


def triage_animated_sticker(frame_paths: List[str], triage: ImageTriage, config: dict) -> Dict:
    """
    动态表情包 Triage：逐帧检测，取最高分
    
    处理流程：
    1. 逐帧检测所有关键帧
    2. 记录每帧的 NSFW/Gore 分数
    3. 取最高分作为整体分数
    4. 记录触发阈值的帧
    5. 判断整体是否敏感
    
    Args:
        frame_paths: 关键帧路径列表
        triage: ImageTriage 实例
        config: 配置字典（包含阈值）
    
    Returns:
        检测结果字典：
        - triage_method: "per_frame_max"
        - max_nsfw_score: 最高 NSFW 分数
        - max_gore_score: 最高 Gore 分数
        - is_sensitive: 是否敏感
        - trigger_frames: 触发帧列表（frame_seq, nsfw_score, content_type）
        - content_type: 内容类型
    
    Example:
        >>> frame_paths = ["frame_00.png", "frame_01.png", "frame_02.png"]
        >>> result = triage_animated_sticker(frame_paths, triage, config)
        >>> print(result["max_nsfw_score"])
        0.65
        >>> print(result["is_sensitive"])
        True
        >>> print(len(result["trigger_frames"]))
        2
    """
    result = {
        "triage_method": "per_frame_max",
        "max_nsfw_score": 0.0,
        "max_gore_score": 0.0,
        "is_sensitive": False,
        "trigger_frames": [],
        "content_type": "TYPE_C_NORMAL"
    }
    
    if not frame_paths:
        return result
    
    nsfw_threshold = config.get('triage', {}).get('nsfw_threshold', 0.5)
    gore_threshold = config.get('triage', {}).get('gore_threshold', 0.5)
    
    for i, frame_path in enumerate(frame_paths):
        if not Path(frame_path).exists():
            continue
        
        try:
            triage_result = triage.classify(frame_path)
            
            if triage_result.nsfw_score > result["max_nsfw_score"]:
                result["max_nsfw_score"] = triage_result.nsfw_score
            
            # 检查是否触发阈值
            if triage_result.nsfw_score > nsfw_threshold:
                result["trigger_frames"].append({
                    "frame_seq": i,
                    "nsfw_score": triage_result.nsfw_score,
                    "content_type": triage_result.content_type
                })
                
        except Exception as e:
            logger.debug(f"帧 Triage 失败 {frame_path}: {e}")
    
    # 判断整体是否敏感
    if result["max_nsfw_score"] > nsfw_threshold:
        result["is_sensitive"] = True
        result["content_type"] = "TYPE_A_NSFW"
    
    return result


def main():
    """
    主函数：表情包 Triage 流程
    
    处理步骤：
    1. 解析命令行参数
    2. 加载配置和路径
    3. 加载 Meta 和 Frames 结果
    4. 初始化 NSFW Classifier（ImageTriage）
    5. 逐个处理：
       - 静图：单帧检测
       - 动图：逐帧检测
    6. 卸载模型释放显存
    7. 保存 Triage 结果
    8. 打印统计信息（敏感数、NSFW 数、Gore 数、Normal 数）
    
    命令行参数：
        --sample: 只处理前 N 个（测试用）
    
    输出统计：
        - 敏感内容数
        - NSFW 数
        - Gore 数
        - Normal 数
    
    Example:
        >>> python scripts/sticker/run_all/_04_run_triage.py --sample 10
        加载 Meta 结果: artifacts/before_merge/sticker/sticker_meta_v1.jsonl
        加载 Frames 结果: artifacts/before_merge/sticker/sticker_frames_v1.jsonl
        共 480 条记录
        采样模式: 仅处理前 10 个
        初始化 NSFW Classifier...
        Triage检测: 100%|████████| 10/10 [00:05<00:00, 2.00it/s]
        Triage 统计: 敏感 2, NSFW 2, Gore 0, Normal 8
        Triage 结果已保存到: artifacts/before_merge/sticker/sticker_triage_v1.jsonl
    """
    parser = argparse.ArgumentParser(description='表情包 Triage')
    parser.add_argument('--sample', type=int, help='仅处理前 N 个')
    args = parser.parse_args()
    
    # 加载配置
    config = load_sticker_config()
    
    # 设置路径
    output_dir = get_sticker_before_merge()
    
    # 加载 meta 和 frames 结果
    meta_path = output_dir / "sticker_meta_v1.jsonl"
    frames_path = output_dir / "sticker_frames_v1.jsonl"
    
    logger.info(f"加载 Meta 结果: {meta_path}")
    meta_list = load_jsonl_list(str(meta_path))
    
    logger.info(f"加载 Frames 结果: {frames_path}")
    frames_data = load_jsonl_by_key(str(frames_path), 'msg_uid')
    
    logger.info(f"共 {len(meta_list)} 条记录")
    
    if args.sample:
        meta_list = meta_list[:args.sample]
        logger.info(f"采样模式: 仅处理前 {args.sample} 个")
    
    # 初始化 Triage
    logger.info("初始化 NSFW Classifier...")
    triage = ImageTriage()
    
    # 处理
    triage_results = []
    
    for meta in tqdm(meta_list, desc="Triage检测", **tqdm_kwargs):
        msg_uid = meta.get('msg_uid')
        file_sha256 = meta.get('file_sha256')
        sticker_class = meta.get('sticker_class')
        thumb_path = meta.get('thumb_path')
        
        result = {
            "schema_version": "sticker_triage_v1",
            "msg_uid": msg_uid,
            "seq_in_html": meta.get('seq_in_html', -1),
            "MsgSvrID": meta.get('MsgSvrID', ''),
            "token": meta.get('token', ''),
            "ts": meta.get('ts', 0),
            "time_local": meta.get('time_local', ''),
            "speaker": meta.get('speaker', 'UNKNOWN'),
            "type": meta.get('type', 47),
            "sub_type": meta.get('sub_type', 0),
            "modality": 'sticker',
            "file_sha256": file_sha256,
            "sticker_class": sticker_class,
            "final_path": meta.get('final_path'),
            "thumb_path": thumb_path,
            "width": meta.get('width'),
            "height": meta.get('height'),
            "is_animated": meta.get('is_animated'),
            "n_frames": meta.get('n_frames'),
            "detected_format": meta.get('detected_format')
        }
        
        if sticker_class == "sticker_animated":
            # 动图：逐帧检测
            frames_record = frames_data.get(msg_uid, {})
            frame_paths = frames_record.get('frame_paths', [])
            triage_data = triage_animated_sticker(frame_paths, triage, config)
        else:
            # 静图：单帧检测
            triage_data = triage_static_sticker(thumb_path, triage, config)
        
        result.update(triage_data)
        triage_results.append(result)
    
    # 卸载模型
    triage.unload()
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    
    # 统计
    sensitive_count = sum(1 for r in triage_results if r.get('is_sensitive'))
    nsfw_count = sum(1 for r in triage_results if r.get('content_type') == 'TYPE_A_NSFW')
    gore_count = sum(1 for r in triage_results if r.get('content_type') == 'TYPE_B_GORE')
    normal_count = sum(1 for r in triage_results if r.get('content_type') == 'TYPE_C_NORMAL')
    
    logger.info(f"Triage 统计: 敏感 {sensitive_count}, NSFW {nsfw_count}, Gore {gore_count}, Normal {normal_count}")
    
    # 保存结果
    triage_path = output_dir / "sticker_triage_v1.jsonl"
    write_jsonl(str(triage_path), triage_results)
    logger.info(f"Triage 结果已保存到: {triage_path}")


if __name__ == '__main__':
    main()
