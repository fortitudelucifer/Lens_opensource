#!/usr/bin/env python3
"""
表情包处理模块 - 动图/静图分类 + 缩略图生成 + 自适应采样关键帧 + Contact Sheet

功能：
- 动图/静图分类（基于帧数）
- 生成缩略图（256x256，PNG 格式）
- 自适应采样关键帧（根据帧数动态调整采样数）
- 生成 Contact Sheet（多帧拼接图）
- 媒体质量过滤（区分静态和动态表情包）

处理流程：
1. 加载嗅探结果（sticker_sniff_v1.jsonl）和 QC 结果（sticker_decode_qc_v1.jsonl）
2. 筛选解码成功的记录
3. 分类表情包类型（静态/动态）
4. 媒体质量过滤（SKIP/LITE/FULL）
5. 生成缩略图（首帧，RGB 格式）
6. 动图提取关键帧（自适应采样）
7. 生成 Contact Sheet（2x2, 2x4, 3x4, 4x4 布局）
8. 输出 meta 和 frames 结果

输入：
- artifacts/before_merge/sticker/sticker_sniff_v1.jsonl
  * msg_uid, file_sha256, final_path, detected_format
- artifacts/before_merge/sticker/sticker_decode_qc_v1.jsonl
  * msg_uid, decode_ok, width, height

输出：
- artifacts/before_merge/sticker/sticker_meta_v1.jsonl
  * msg_uid, file_sha256, is_animated, n_frames, sticker_class
  * width, height, filter_tier, thumb_path, frames_ref
- artifacts/before_merge/sticker/sticker_frames_v1.jsonl
  * msg_uid, file_sha256, n_sampled, sample_indices
  * frame_paths, contact_sheet_path

存储：
- artifacts/sticker/thumbs/{msg_uid}_{sha256[:16]}.png
  * 缩略图（256x256）
- artifacts/sticker/frames/{msg_uid}_{sha256[:16]}_f{i:02d}.png
  * 关键帧（单独保存）
- artifacts/sticker/frames/{msg_uid}_{sha256[:16]}_contact.png
  * Contact Sheet（多帧拼接图）

依赖：
- scripts/_common/path_utils.py (load_sticker_config, get_sticker_thumbs_dir, get_sticker_frames_dir)
- scripts/_common/jsonl_utils.py (load_jsonl_by_key, write_jsonl)
- scripts/_common/media_filter.py (filter_sticker, FilterTier)
- PIL (Pillow) - 图片处理

使用示例：
    # 完整处理
    python scripts/sticker/run_all/_03_run_process.py
    
    # 测试模式（只处理前10个）
    python scripts/sticker/run_all/_03_run_process.py --sample 10
    
    # 跳过关键帧提取
    python scripts/sticker/run_all/_03_run_process.py --skip-frames

自适应采样策略：
- ≤12帧：采样4帧
- 13-30帧：采样8帧
- 31-60帧：采样12帧
- >60帧：采样16帧
- 均匀采样（step = n_frames / n_samples）

Contact Sheet 布局：
- ≤4帧：2x2 布局
- 5-8帧：4x2 布局
- 9-12帧：4x3 布局
- >12帧：4x4 布局
- 每个单元格 256x256，居中显示

媒体质量过滤：
- SKIP: 低质量表情包（尺寸过小、文件过小）
- LITE: 中等质量（生成缩略图，动图提取少量关键帧）
- FULL: 高质量（生成缩略图，动图提取完整关键帧）

作者：[Author]
更新于：2026-02-02
"""

import os
import sys
import argparse
import logging
from pathlib import Path
from typing import Dict, List, Tuple, Optional

from PIL import Image, ImageSequence
from tqdm import tqdm

# 确保 tqdm 输出到 stderr 以便实时显示
tqdm_kwargs = {"file": sys.stderr, "dynamic_ncols": True}

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from scripts._common.path_utils import (
    load_sticker_config, get_sticker_before_merge,
    get_sticker_thumbs_dir, get_sticker_frames_dir
)
from scripts._common.jsonl_utils import load_jsonl_by_key, load_jsonl_list, write_jsonl
from scripts._common.media_filter import (
    filter_sticker, FilterTier, SkipReason, create_skip_marker
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 设置 Pillow 解压炸弹保护
Image.MAX_IMAGE_PIXELS = 26000000


def classify_sticker(img_path: str, config: dict) -> Dict:
    """
    分类表情包类型（静态/动态）
    
    分类逻辑：
    - 帧数 > 1：动态表情包（sticker_animated）
    - 帧数 = 1：静态表情包（sticker_static）
    - 无法识别：未知类型（sticker_unknown）
    
    Args:
        img_path: 图片文件路径
        config: 配置字典（包含 frame_count_cap）
    
    Returns:
        分类结果字典：
        - sticker_class: "sticker_animated", "sticker_static", "sticker_unknown"
        - is_animated: 是否为动图
        - n_frames: 帧数
        - durations_ms: 每帧持续时间（毫秒，仅动图）
    
    Example:
        >>> result = classify_sticker("sticker.gif", config)
        >>> print(result["sticker_class"])
        "sticker_animated"
        >>> print(result["n_frames"])
        24
    """
    frame_cap = config.get('classification', {}).get('frame_count_cap', 3000)
    
    result = {
        "sticker_class": "sticker_unknown",
        "is_animated": False,
        "n_frames": 0,
        "durations_ms": None
    }
    
    try:
        with Image.open(img_path) as img:
            frames = list(ImageSequence.Iterator(img))
            n_frames = min(len(frames), frame_cap)
            
            if n_frames > 1:
                result["sticker_class"] = "sticker_animated"
                result["is_animated"] = True
                result["n_frames"] = n_frames
                # 获取每帧持续时间
                durations = []
                for i, frame in enumerate(frames[:n_frames]):
                    dur = frame.info.get('duration', 100)
                    durations.append(dur)
                result["durations_ms"] = durations
            else:
                result["sticker_class"] = "sticker_static"
                result["is_animated"] = False
                result["n_frames"] = 1
                
    except Exception as e:
        logger.debug(f"分类失败 {img_path}: {e}")
        result["sticker_class"] = "sticker_unknown"
    
    return result


def generate_thumbnail(img_path: str, out_path: str, config: dict) -> bool:
    """
    生成缩略图
    
    处理流程：
    1. 打开图片（动图取首帧）
    2. 转换为 RGB 格式（处理透明通道）
    3. 缩放到 256x256（保持宽高比）
    4. 保存为 PNG 格式
    
    Args:
        img_path: 原始图片路径
        out_path: 输出路径
        config: 配置字典（包含 thumbnail.size_px）
    
    Returns:
        是否成功生成缩略图
    
    Example:
        >>> success = generate_thumbnail("sticker.gif", "thumb.png", config)
        >>> print(success)
        True
    """
    thumb_cfg = config.get('thumbnail', {})
    size_px = thumb_cfg.get('size_px', 256)
    
    try:
        with Image.open(img_path) as img:
            # 动图取首帧
            if hasattr(img, 'n_frames') and img.n_frames > 1:
                img.seek(0)
            
            # 复制帧以避免修改原图
            frame = img.copy()
            
            # 转换为 RGB（处理透明通道）
            if frame.mode in ("RGBA", "P", "LA"):
                background = Image.new("RGB", frame.size, (255, 255, 255))
                if frame.mode == "P":
                    frame = frame.convert("RGBA")
                if frame.mode in ("RGBA", "LA"):
                    # 分离 alpha 通道
                    if frame.mode == "LA":
                        frame = frame.convert("RGBA")
                    background.paste(frame, mask=frame.split()[-1])
                    frame = background
            elif frame.mode != "RGB":
                frame = frame.convert("RGB")
            
            # 缩放
            frame.thumbnail((size_px, size_px), Image.Resampling.LANCZOS)
            
            # 保存
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            frame.save(out_path, "PNG")
            return True
            
    except Exception as e:
        logger.debug(f"缩略图生成失败 {img_path}: {e}")
        return False


def get_adaptive_sample_count(n_frames: int, config: dict) -> int:
    """
    根据帧数获取自适应采样数
    
    采样规则：
    - ≤12帧：采样4帧
    - 13-30帧：采样8帧
    - 31-60帧：采样12帧
    - >60帧：采样16帧
    
    Args:
        n_frames: 总帧数
        config: 配置字典（包含 frame_sampling.adaptive_rules）
    
    Returns:
        采样帧数
    
    Example:
        >>> get_adaptive_sample_count(24, config)
        8
        >>> get_adaptive_sample_count(100, config)
        16
    """
    rules = config.get('frame_sampling', {}).get('adaptive_rules', {})
    
    # 默认规则
    if n_frames <= 12:
        return min(4, n_frames)
    elif n_frames <= 30:
        return min(8, n_frames)
    elif n_frames <= 60:
        return min(12, n_frames)
    else:
        return min(16, n_frames)


def extract_frames(img_path: str, out_dir: str, msg_uid: str, sha256: str, config: dict) -> Dict:
    """
    提取动图的代表帧 + 生成 Contact Sheet
    
    处理流程：
    1. 打开动图，获取所有帧
    2. 计算自适应采样数
    3. 均匀采样（step = n_frames / n_samples）
    4. 提取单独帧（转换为 RGB，保存为 PNG）
    5. 生成 Contact Sheet（多帧拼接图）
    
    Args:
        img_path: 动图文件路径
        out_dir: 输出目录
        msg_uid: 消息 UID（用于文件名）
        sha256: SHA256 哈希（用于文件名）
        config: 配置字典
    
    Returns:
        帧提取结果字典：
        - frame_paths: 单独帧路径列表
        - contact_sheet_path: Contact Sheet 路径
        - n_sampled: 采样帧数
        - sample_indices: 采样索引列表
    
    Example:
        >>> result = extract_frames("sticker.gif", "frames/", "msg_123", "abc...", config)
        >>> print(result["n_sampled"])
        8
        >>> print(len(result["frame_paths"]))
        8
    """
    result = {
        "frame_paths": [],
        "contact_sheet_path": None,
        "n_sampled": 0,
        "sample_indices": []
    }
    
    try:
        with Image.open(img_path) as img:
            frames = list(ImageSequence.Iterator(img))
            n_frames = len(frames)
            
            if n_frames <= 1:
                return result
            
            # 自适应采样数
            n_samples = get_adaptive_sample_count(n_frames, config)
            
            # 计算均匀采样索引
            if n_frames <= n_samples:
                indices = list(range(n_frames))
            else:
                step = n_frames / n_samples
                indices = [int(i * step) for i in range(n_samples)]
            
            result["sample_indices"] = indices
            result["n_sampled"] = len(indices)
            
            # 确保输出目录存在
            Path(out_dir).mkdir(parents=True, exist_ok=True)
            
            safe_uid = msg_uid.replace(':', '_')
            sampled_frames = []
            
            # 提取单独帧
            for i, idx in enumerate(indices):
                frame = frames[idx].copy()
                
                # 转换为 RGB
                if frame.mode in ("RGBA", "P", "LA"):
                    background = Image.new("RGB", frame.size, (255, 255, 255))
                    if frame.mode == "P":
                        frame = frame.convert("RGBA")
                    if frame.mode in ("RGBA", "LA"):
                        if frame.mode == "LA":
                            frame = frame.convert("RGBA")
                        background.paste(frame, mask=frame.split()[-1])
                        frame = background
                elif frame.mode != "RGB":
                    frame = frame.convert("RGB")
                
                out_path = f"{out_dir}/{safe_uid}_{sha256[:16]}_f{i:02d}.png"
                frame.save(out_path, "PNG")
                
                result["frame_paths"].append(out_path)
                sampled_frames.append(frame)
            
            # 生成 Contact Sheet
            contact_cfg = config.get('contact_sheet', {})
            if contact_cfg.get('enabled', True):
                contact_path = f"{out_dir}/{safe_uid}_{sha256[:16]}_contact.png"
                cell_size = contact_cfg.get('cell_size', 256)
                
                contact_sheet = create_contact_sheet(sampled_frames, cell_size)
                contact_sheet.save(contact_path, "PNG")
                result["contact_sheet_path"] = contact_path
                
    except Exception as e:
        logger.debug(f"帧提取失败 {img_path}: {e}")
    
    return result


def create_contact_sheet(frames: List[Image.Image], cell_size: int = 256) -> Image.Image:
    """
    创建 Contact Sheet（多帧拼接图）
    
    布局规则：
    - ≤4帧：2x2 布局
    - 5-8帧：4x2 布局
    - 9-12帧：4x3 布局
    - >12帧：4x4 布局
    
    处理流程：
    1. 根据帧数选择布局（cols x rows）
    2. 创建白色背景画布
    3. 逐帧缩放并居中粘贴
    
    Args:
        frames: 帧图片列表
        cell_size: 单元格大小（默认256）
    
    Returns:
        Contact Sheet 图片对象
    
    Example:
        >>> frames = [Image.open(f"frame_{i}.png") for i in range(8)]
        >>> contact = create_contact_sheet(frames, 256)
        >>> contact.save("contact.png")
    """
    n = len(frames)
    
    # 自动选择布局
    if n <= 4:
        cols, rows = 2, 2
    elif n <= 8:
        cols, rows = 4, 2
    elif n <= 12:
        cols, rows = 4, 3
    else:
        cols, rows = 4, 4
    
    width = cols * cell_size
    height = rows * cell_size
    
    contact = Image.new("RGB", (width, height), (255, 255, 255))
    
    for i, frame in enumerate(frames):
        if i >= rows * cols:
            break
        row = i // cols
        col = i % cols
        
        # 缩放到 cell_size
        frame_resized = frame.copy()
        frame_resized.thumbnail((cell_size, cell_size), Image.Resampling.LANCZOS)
        
        # 居中粘贴
        x = col * cell_size + (cell_size - frame_resized.width) // 2
        y = row * cell_size + (cell_size - frame_resized.height) // 2
        contact.paste(frame_resized, (x, y))
    
    return contact


def main():
    """
    主函数：表情包处理流程
    
    处理步骤：
    1. 解析命令行参数
    2. 加载配置和路径
    3. 加载嗅探结果和 QC 结果
    4. 筛选解码成功的记录
    5. 逐个处理：
       - 分类（静态/动态）
       - 媒体质量过滤
       - 生成缩略图
       - 提取关键帧（动图）
       - 生成 Contact Sheet
    6. 保存 meta 和 frames 结果
    7. 打印统计信息（分类、过滤、关键帧提取）
    
    命令行参数：
        --sample: 只处理前 N 个（测试用）
        --skip-frames: 跳过关键帧提取
    
    输出统计：
        - 分类统计：静态数、动态数、未知数
        - 过滤统计：SKIP, LITE, FULL（区分静态和动态）
        - 跳过处理数
        - 提取关键帧数
    
    Example:
        >>> python scripts/sticker/run_all/_03_run_process.py --sample 10
        加载嗅探结果: artifacts/before_merge/sticker/sticker_sniff_v1.jsonl
        加载 QC 结果: artifacts/before_merge/sticker/sticker_decode_qc_v1.jsonl
        有效记录: 480 条
        采样模式: 仅处理前 10 个
        处理表情包: 100%|████████| 10/10 [00:02<00:00, 5.00it/s]
        分类统计: 静态 4, 动态 6, 未知 0
        过滤统计: SKIP 0, LITE 2, FULL 8
          静态: SKIP 0, LITE 1, FULL 3
          动态: SKIP 0, LITE 1, FULL 5
        跳过处理: 0 个
        提取关键帧: 6 个动图
        Meta 结果已保存到: artifacts/before_merge/sticker/sticker_meta_v1.jsonl
        Frames 结果已保存到: artifacts/before_merge/sticker/sticker_frames_v1.jsonl
    """
    parser = argparse.ArgumentParser(description='表情包处理')
    parser.add_argument('--sample', type=int, help='仅处理前 N 个')
    parser.add_argument('--skip-frames', action='store_true', help='跳过关键帧提取')
    args = parser.parse_args()
    
    # 加载配置
    config = load_sticker_config()
    
    # 设置路径
    output_dir = get_sticker_before_merge()
    thumbs_dir = get_sticker_thumbs_dir()
    frames_dir = get_sticker_frames_dir()
    
    thumbs_dir.mkdir(parents=True, exist_ok=True)
    frames_dir.mkdir(parents=True, exist_ok=True)
    
    # 加载嗅探结果和 QC 结果
    sniff_path = output_dir / "sticker_sniff_v1.jsonl"
    qc_path = output_dir / "sticker_decode_qc_v1.jsonl"
    
    logger.info(f"加载嗅探结果: {sniff_path}")
    sniff_data = load_jsonl_by_key(str(sniff_path), 'msg_uid')
    
    logger.info(f"加载 QC 结果: {qc_path}")
    qc_data = load_jsonl_by_key(str(qc_path), 'msg_uid')
    
    # 筛选解码成功的记录
    valid_records = []
    for msg_uid, sniff in sniff_data.items():
        qc = qc_data.get(msg_uid, {})
        if qc.get('decode_ok') and sniff.get('final_path'):
            # 保留所有原始字段
            record = sniff.copy()
            record['width'] = qc.get('width')
            record['height'] = qc.get('height')
            valid_records.append(record)
    
    logger.info(f"有效记录: {len(valid_records)} 条")
    
    if args.sample:
        valid_records = valid_records[:args.sample]
        logger.info(f"采样模式: 仅处理前 {args.sample} 个")
    
    # 处理统计
    meta_results = []
    frames_results = []
    filter_stats = {
        'skip': 0,
        'lite': 0,
        'full': 0,
        'static_skip': 0,
        'static_lite': 0,
        'static_full': 0,
        'animated_skip': 0,
        'animated_lite': 0,
        'animated_full': 0,
    }
    
    for record in tqdm(valid_records, desc="处理表情包", **tqdm_kwargs):
        msg_uid = record['msg_uid']
        file_sha256 = record['file_sha256']
        img_path = record['final_path']
        width = record.get('width', 0) or 0
        height = record.get('height', 0) or 0
        
        # 先分类（获取帧数）
        classify_result = classify_sticker(img_path, config)
        is_animated = classify_result['is_animated']
        n_frames = classify_result['n_frames']
        
        # 获取文件大小
        file_size = 0
        if img_path and os.path.exists(img_path):
            file_size = os.path.getsize(img_path)
        
        # 媒体质量过滤（区分静态和动态）
        filter_decision = filter_sticker(
            width=width,
            height=height,
            file_size=file_size,
            n_frames=n_frames
        )
        
        # 更新统计
        tier_key = filter_decision.tier.value
        if tier_key in ('skip', 'lite', 'full'):
            filter_stats[tier_key] += 1
            anim_prefix = 'animated' if is_animated else 'static'
            filter_stats[f'{anim_prefix}_{tier_key}'] += 1
        
        # 构建 meta 结果（保留原始字段）
        meta = {
            "schema_version": "sticker_meta_v1",
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
            "detected_format": record.get('detected_format'),
            "is_animated": is_animated,
            "n_frames": n_frames,
            "sticker_class": classify_result['sticker_class'],
            "width": width,
            "height": height,
            "final_path": record.get('final_path'),
            "filter_tier": filter_decision.tier.value,
            "filter_reason": filter_decision.reason,
        }
        
        # 如果跳过，添加跳过标记
        if filter_decision.should_skip:
            skip_marker = filter_decision.to_skip_marker()
            meta.update(skip_marker)
            meta["thumb_path"] = None
            meta["frames_ref"] = None
            meta_results.append(meta)
            continue
        
        # 生成缩略图
        safe_uid = msg_uid.replace(':', '_')
        thumb_filename = f"{safe_uid}_{file_sha256[:16]}.png"
        thumb_path = thumbs_dir / thumb_filename
        thumb_ok = generate_thumbnail(img_path, str(thumb_path), config)
        meta["thumb_path"] = str(thumb_path) if thumb_ok else None
        meta["frames_ref"] = None
        
        # 动图提取关键帧（LITE 模式也提取，但采样更少）
        if is_animated and not args.skip_frames:
            frames_result = extract_frames(
                img_path, str(frames_dir), msg_uid, file_sha256, config
            )
            
            if frames_result['frame_paths']:
                meta["frames_ref"] = "sticker_frames_v1.jsonl"
                
                frames_record = {
                    "schema_version": "sticker_frames_v1",
                    "msg_uid": msg_uid,
                    "file_sha256": file_sha256,
                    "n_sampled": frames_result['n_sampled'],
                    "sample_indices": frames_result['sample_indices'],
                    "frame_paths": frames_result['frame_paths'],
                    "contact_sheet_path": frames_result['contact_sheet_path']
                }
                frames_results.append(frames_record)
        
        meta_results.append(meta)
    
    # 统计
    static_count = sum(1 for m in meta_results if m['sticker_class'] == 'sticker_static')
    animated_count = sum(1 for m in meta_results if m['sticker_class'] == 'sticker_animated')
    unknown_count = sum(1 for m in meta_results if m['sticker_class'] == 'sticker_unknown')
    skipped_count = sum(1 for m in meta_results if m.get('skipped'))
    
    logger.info(f"分类统计: 静态 {static_count}, 动态 {animated_count}, 未知 {unknown_count}")
    logger.info(f"过滤统计: SKIP {filter_stats['skip']}, LITE {filter_stats['lite']}, FULL {filter_stats['full']}")
    logger.info(f"  静态: SKIP {filter_stats['static_skip']}, LITE {filter_stats['static_lite']}, FULL {filter_stats['static_full']}")
    logger.info(f"  动态: SKIP {filter_stats['animated_skip']}, LITE {filter_stats['animated_lite']}, FULL {filter_stats['animated_full']}")
    logger.info(f"跳过处理: {skipped_count} 个")
    logger.info(f"提取关键帧: {len(frames_results)} 个动图")
    
    # 保存结果
    meta_path = output_dir / "sticker_meta_v1.jsonl"
    frames_path = output_dir / "sticker_frames_v1.jsonl"
    
    write_jsonl(str(meta_path), meta_results)
    logger.info(f"Meta 结果已保存到: {meta_path}")
    
    if frames_results:
        write_jsonl(str(frames_path), frames_results)
        logger.info(f"Frames 结果已保存到: {frames_path}")


if __name__ == '__main__':
    main()
