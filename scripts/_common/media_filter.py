#!/usr/bin/env python3
"""
媒体质量过滤模块 (Media Quality Filter)

功能：
- 统一的媒体文件质量过滤（图片、视频、表情包）
- 根据分辨率、时长、文件大小等指标决定处理策略
- 生成跳过标记（用于最终输出）

处理级别 (FilterTier)：
- SKIP: 跳过，不处理（垃圾数据）
- LITE: 轻量处理（OCR/场景分类，不用 VLM）
- SINGLE_FRAME: 视频只取首帧当图片处理
- SLICE: 超长图需切片处理
- FULL: 完整 VLM 分析

跳过原因 (SkipReason)：
- FILE_TOO_SMALL: 文件过小，可能损坏
- IMAGE_TOO_SMALL: 图片分辨率过低
- IMAGE_TOO_LONG: 超长图片，需要切片处理
- VIDEO_TOO_SHORT: 视频时长过短（<1秒）
- VIDEO_LOW_RES: 视频分辨率过低
- STICKER_TOO_SMALL: 表情包分辨率过低

核心函数：
- filter_image(): 图片过滤决策
- filter_video(): 视频过滤决策
- filter_sticker(): 表情包过滤决策
- create_skip_marker(): 创建跳过标记（用于写入 JSONL）

使用示例：
    from scripts._common.media_filter import (
        filter_image, filter_video, filter_sticker,
        FilterTier, FilterDecision
    )
    
    # 图片过滤
    decision = filter_image(width=120, height=120, file_size=8000)
    if decision.should_skip:
        print(f"跳过: {decision.reason}")
        marker = decision.to_skip_marker()
        # 写入 JSONL: {'skipped': True, 'skip_reason': '...', ...}
    
    # 视频过滤
    decision = filter_video(width=1920, height=1080, duration_sec=2.5)
    if decision.tier == FilterTier.SINGLE_FRAME:
        print("短视频，只取首帧")

配置文件：
- configs/media_filter.yaml: 过滤阈值配置

依赖：
- yaml: 配置文件解析
- dataclasses: 数据类
- enum: 枚举类型

作者：forcifer
项目：CHAT_APP_DHA - CHAT_APP聊天记录多模态处理流水线
更新于：2026-02-02
"""

import os
import sys
from enum import Enum
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Dict, Any

import yaml

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))


class FilterTier(Enum):
    """处理级别"""
    SKIP = "skip"                    # 跳过，不处理
    LITE = "lite"                    # 轻量处理
    SINGLE_FRAME = "single_frame"    # 视频只取首帧
    SLICE = "slice"                  # 超长图需切片
    FULL = "full"                    # 完整分析


class SkipReason(Enum):
    """跳过原因（用于最终输出标记）"""
    # 通用
    FILE_TOO_SMALL = "file_too_small"
    FILE_NOT_FOUND = "file_not_found"
    DECODE_FAILED = "decode_failed"
    
    # 图片
    IMAGE_TOO_SMALL = "image_too_small"
    IMAGE_TOO_LONG = "image_too_long"
    
    # 视频
    VIDEO_TOO_SHORT = "video_too_short"
    VIDEO_LOW_RES = "video_low_res"
    
    # 表情包
    STICKER_TOO_SMALL = "sticker_too_small"
    STICKER_DOWNLOAD_FAILED = "sticker_download_failed"
    STICKER_FORMAT_UNKNOWN = "sticker_format_unknown"


# 跳过原因的中文描述（用于最终输出）
SKIP_REASON_DESCRIPTIONS = {
    SkipReason.FILE_TOO_SMALL: "文件过小，可能损坏",
    SkipReason.FILE_NOT_FOUND: "文件不存在",
    SkipReason.DECODE_FAILED: "文件解码失败",
    SkipReason.IMAGE_TOO_SMALL: "图片分辨率过低，无法分析",
    SkipReason.IMAGE_TOO_LONG: "超长图片，需要切片处理",
    SkipReason.VIDEO_TOO_SHORT: "视频时长过短（<1秒）",
    SkipReason.VIDEO_LOW_RES: "视频分辨率过低",
    SkipReason.STICKER_TOO_SMALL: "表情包分辨率过低",
    SkipReason.STICKER_DOWNLOAD_FAILED: "表情包下载失败",
    SkipReason.STICKER_FORMAT_UNKNOWN: "表情包格式无法识别",
}


def get_skip_description(reason: SkipReason) -> str:
    """获取跳过原因的中文描述"""
    return SKIP_REASON_DESCRIPTIONS.get(reason, str(reason.value))


@dataclass
class FilterDecision:
    """过滤决策结果"""
    tier: FilterTier
    reason: str
    skip_reason: Optional[SkipReason] = None  # 跳过原因枚举（用于标记）
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def should_skip(self) -> bool:
        return self.tier == FilterTier.SKIP
    
    @property
    def should_process(self) -> bool:
        return self.tier != FilterTier.SKIP
    
    def to_skip_marker(self) -> Dict[str, Any]:
        """生成跳过标记字典（用于写入JSONL）"""
        if not self.should_skip:
            return {}
        return {
            'skipped': True,
            'skip_reason': self.skip_reason.value if self.skip_reason else self.reason,
            'skip_description': get_skip_description(self.skip_reason) if self.skip_reason else self.reason,
            'filter_tier': self.tier.value,
            'filter_metadata': self.metadata
        }


# ========== 配置加载 ==========

_config_cache: Optional[dict] = None

def load_filter_config() -> dict:
    """加载媒体过滤配置"""
    global _config_cache
    if _config_cache is not None:
        return _config_cache
    
    config_path = PROJECT_ROOT / "configs" / "media_filter.yaml"
    if config_path.exists():
        with open(config_path, 'r', encoding='utf-8') as f:
            _config_cache = yaml.safe_load(f)
    else:
        # 默认配置
        _config_cache = {
            'common': {'min_file_size_bytes': 5120},
            'image': {
                'skip_max_dim': 64,
                'lite_max_dim': 300,
                'long_image_ratio': 5.0,
                'long_image_max_height': 5000,
                'slice_size': 1024,
                'ocr_min_char_height': 16,
            },
            'video': {
                'skip_duration_sec': 1.0,
                'single_frame_duration_sec': 3.0,
                'low_res_short_side': 240,
                'max_fps_for_analysis': 30,
                'target_fps': 5,
            },
            'sticker': {
                'skip_max_dim': 32,
                'lite_max_dim': 64,
                'max_frames_for_full': 100,
            },
        }
    return _config_cache


def get_config(section: str, key: str, default: Any = None) -> Any:
    """获取配置值"""
    config = load_filter_config()
    return config.get(section, {}).get(key, default)


# ========== 图片过滤 ==========

def filter_image(
    width: int,
    height: int,
    file_size: int = 0,
    file_path: Optional[str] = None
) -> FilterDecision:
    """
    图片过滤决策
    
    Args:
        width: 图片宽度（像素）
        height: 图片高度（像素）
        file_size: 文件大小（字节），0表示未知
        file_path: 文件路径（可选，用于获取文件大小）
    
    Returns:
        FilterDecision: 过滤决策
    """
    config = load_filter_config()
    common_cfg = config.get('common', {})
    image_cfg = config.get('image', {})
    
    # 获取文件大小
    if file_size == 0 and file_path and os.path.exists(file_path):
        file_size = os.path.getsize(file_path)
    
    # 1. 文件大小检查
    min_size = common_cfg.get('min_file_size_bytes', 5120)
    if file_size > 0 and file_size < min_size:
        return FilterDecision(
            tier=FilterTier.SKIP,
            reason=f"file_too_small ({file_size} < {min_size} bytes)",
            skip_reason=SkipReason.FILE_TOO_SMALL,
            metadata={'file_size': file_size}
        )
    
    # 2. 分辨率检查
    max_dim = max(width, height)
    min_dim = min(width, height)
    
    skip_threshold = image_cfg.get('skip_max_dim', 64)
    lite_threshold = image_cfg.get('lite_max_dim', 300)
    
    if max_dim < skip_threshold:
        return FilterDecision(
            tier=FilterTier.SKIP,
            reason=f"resolution_too_low (max_dim={max_dim} < {skip_threshold}px)",
            skip_reason=SkipReason.IMAGE_TOO_SMALL,
            metadata={'width': width, 'height': height, 'max_dim': max_dim}
        )
    
    # 3. 超长图检查（显存保护）
    long_ratio = image_cfg.get('long_image_ratio', 5.0)
    long_max_height = image_cfg.get('long_image_max_height', 5000)
    
    aspect_ratio = max_dim / min_dim if min_dim > 0 else 0
    is_long_image = (aspect_ratio > long_ratio) and (max_dim > long_max_height)
    
    if is_long_image:
        slice_size = image_cfg.get('slice_size', 1024)
        num_slices = (max_dim // slice_size) + 1
        return FilterDecision(
            tier=FilterTier.SLICE,
            reason=f"long_image_needs_slicing (ratio={aspect_ratio:.1f}, height={max_dim})",
            metadata={
                'width': width,
                'height': height,
                'aspect_ratio': round(aspect_ratio, 2),
                'suggested_slices': num_slices,
                'slice_size': slice_size
            }
        )
    
    # 4. 轻量处理判断
    if max_dim < lite_threshold:
        return FilterDecision(
            tier=FilterTier.LITE,
            reason=f"small_image_lite_processing (max_dim={max_dim} < {lite_threshold}px)",
            metadata={'width': width, 'height': height, 'max_dim': max_dim}
        )
    
    # 5. 完整处理
    return FilterDecision(
        tier=FilterTier.FULL,
        reason="standard_image",
        metadata={'width': width, 'height': height, 'max_dim': max_dim}
    )


# ========== 视频过滤 ==========

def filter_video(
    width: int,
    height: int,
    duration_sec: float,
    file_size: int = 0,
    fps: float = 30.0,
    file_path: Optional[str] = None
) -> FilterDecision:
    """
    视频过滤决策
    
    Args:
        width: 视频宽度（像素）
        height: 视频高度（像素）
        duration_sec: 视频时长（秒）
        file_size: 文件大小（字节），0表示未知
        fps: 帧率
        file_path: 文件路径（可选）
    
    Returns:
        FilterDecision: 过滤决策
    """
    config = load_filter_config()
    common_cfg = config.get('common', {})
    video_cfg = config.get('video', {})
    
    # 获取文件大小
    if file_size == 0 and file_path and os.path.exists(file_path):
        file_size = os.path.getsize(file_path)
    
    # 1. 文件大小检查
    min_size = common_cfg.get('min_file_size_bytes', 5120)
    if file_size > 0 and file_size < min_size:
        return FilterDecision(
            tier=FilterTier.SKIP,
            reason=f"file_too_small ({file_size} < {min_size} bytes)",
            skip_reason=SkipReason.FILE_TOO_SMALL,
            metadata={'file_size': file_size}
        )
    
    # 2. 时长检查
    skip_duration = video_cfg.get('skip_duration_sec', 1.0)
    single_frame_duration = video_cfg.get('single_frame_duration_sec', 3.0)
    
    if duration_sec < skip_duration:
        return FilterDecision(
            tier=FilterTier.SKIP,
            reason=f"duration_too_short ({duration_sec:.2f}s < {skip_duration}s)",
            skip_reason=SkipReason.VIDEO_TOO_SHORT,
            metadata={'duration_sec': duration_sec}
        )
    
    # 3. 分辨率检查
    short_side = min(width, height)
    low_res_threshold = video_cfg.get('low_res_short_side', 240)
    
    is_low_res = short_side <= low_res_threshold
    
    # 4. 短视频只取首帧
    if duration_sec < single_frame_duration:
        return FilterDecision(
            tier=FilterTier.SINGLE_FRAME,
            reason=f"short_video_single_frame ({duration_sec:.2f}s < {single_frame_duration}s)",
            metadata={
                'duration_sec': duration_sec,
                'width': width,
                'height': height,
                'is_low_res': is_low_res
            }
        )
    
    # 5. 低清视频轻量处理
    if is_low_res:
        return FilterDecision(
            tier=FilterTier.LITE,
            reason=f"low_resolution_video (short_side={short_side} < {low_res_threshold}px)",
            metadata={
                'width': width,
                'height': height,
                'short_side': short_side,
                'duration_sec': duration_sec
            }
        )
    
    # 6. 高帧率视频需要降采样
    max_fps = video_cfg.get('max_fps_for_analysis', 30)
    target_fps = video_cfg.get('target_fps', 5)
    needs_downsample = fps > max_fps
    
    # 7. 完整处理
    return FilterDecision(
        tier=FilterTier.FULL,
        reason="standard_video",
        metadata={
            'width': width,
            'height': height,
            'duration_sec': duration_sec,
            'fps': fps,
            'needs_fps_downsample': needs_downsample,
            'target_fps': target_fps if needs_downsample else None
        }
    )


# ========== 表情包过滤 ==========

def filter_sticker(
    width: int,
    height: int,
    file_size: int = 0,
    n_frames: int = 1,
    file_path: Optional[str] = None
) -> FilterDecision:
    """
    表情包过滤决策
    
    Args:
        width: 宽度（像素）
        height: 高度（像素）
        file_size: 文件大小（字节），0表示未知
        n_frames: 帧数（动图）
        file_path: 文件路径（可选）
    
    Returns:
        FilterDecision: 过滤决策
    """
    config = load_filter_config()
    common_cfg = config.get('common', {})
    sticker_cfg = config.get('sticker', {})
    
    # 获取文件大小
    if file_size == 0 and file_path and os.path.exists(file_path):
        file_size = os.path.getsize(file_path)
    
    # 1. 文件大小检查
    min_size = common_cfg.get('min_file_size_bytes', 5120)
    if file_size > 0 and file_size < min_size:
        return FilterDecision(
            tier=FilterTier.SKIP,
            reason=f"file_too_small ({file_size} < {min_size} bytes)",
            skip_reason=SkipReason.FILE_TOO_SMALL,
            metadata={'file_size': file_size}
        )
    
    # 2. 分辨率检查
    max_dim = max(width, height)
    
    skip_threshold = sticker_cfg.get('skip_max_dim', 32)
    lite_threshold = sticker_cfg.get('lite_max_dim', 64)
    
    if max_dim < skip_threshold:
        return FilterDecision(
            tier=FilterTier.SKIP,
            reason=f"resolution_too_low (max_dim={max_dim} < {skip_threshold}px)",
            skip_reason=SkipReason.STICKER_TOO_SMALL,
            metadata={'width': width, 'height': height, 'max_dim': max_dim}
        )
    
    if max_dim < lite_threshold:
        return FilterDecision(
            tier=FilterTier.LITE,
            reason=f"tiny_sticker_lite_processing (max_dim={max_dim} < {lite_threshold}px)",
            metadata={'width': width, 'height': height, 'max_dim': max_dim, 'n_frames': n_frames}
        )
    
    # 3. 超多帧动图特殊处理
    max_frames = sticker_cfg.get('max_frames_for_full', 100)
    if n_frames > max_frames:
        return FilterDecision(
            tier=FilterTier.LITE,
            reason=f"too_many_frames ({n_frames} > {max_frames}), sampling only",
            metadata={
                'width': width,
                'height': height,
                'n_frames': n_frames,
                'needs_sampling': True
            }
        )
    
    # 4. 完整处理
    return FilterDecision(
        tier=FilterTier.FULL,
        reason="standard_sticker",
        metadata={
            'width': width,
            'height': height,
            'max_dim': max_dim,
            'n_frames': n_frames,
            'is_animated': n_frames > 1
        }
    )


# ========== 便捷函数 ==========

def should_skip_image(width: int, height: int, file_size: int = 0) -> tuple[bool, str]:
    """
    快速判断图片是否应该跳过
    
    Returns:
        (should_skip, reason)
    """
    decision = filter_image(width, height, file_size)
    return decision.should_skip, decision.reason


def should_skip_video(width: int, height: int, duration_sec: float, file_size: int = 0) -> tuple[bool, str]:
    """
    快速判断视频是否应该跳过
    
    Returns:
        (should_skip, reason)
    """
    decision = filter_video(width, height, duration_sec, file_size)
    return decision.should_skip, decision.reason


def should_skip_sticker(width: int, height: int, file_size: int = 0, n_frames: int = 1) -> tuple[bool, str]:
    """
    快速判断表情包是否应该跳过
    
    Returns:
        (should_skip, reason)
    """
    decision = filter_sticker(width, height, file_size, n_frames)
    return decision.should_skip, decision.reason


# ========== 跳过/失败标记生成 ==========

def create_skip_marker(
    skip_reason: SkipReason,
    modality: str,
    metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    创建跳过标记字典（用于写入JSONL）
    
    Args:
        skip_reason: 跳过原因枚举
        modality: 模态类型 (image/video/sticker)
        metadata: 额外元数据
    
    Returns:
        标记字典，包含 skipped, skip_reason, skip_description 等字段
    """
    marker = {
        'skipped': True,
        'skip_reason': skip_reason.value,
        'skip_description': get_skip_description(skip_reason),
    }
    if metadata:
        marker['skip_metadata'] = metadata
    return marker


def create_download_failed_marker(
    url: str,
    http_status: Optional[int] = None,
    error_msg: Optional[str] = None
) -> Dict[str, Any]:
    """
    创建下载失败标记（专用于表情包）
    
    Args:
        url: 下载URL
        http_status: HTTP状态码
        error_msg: 错误信息
    
    Returns:
        标记字典
    """
    marker = {
        'skipped': True,
        'skip_reason': SkipReason.STICKER_DOWNLOAD_FAILED.value,
        'skip_description': get_skip_description(SkipReason.STICKER_DOWNLOAD_FAILED),
        'download_url': url,
    }
    if http_status:
        marker['http_status'] = http_status
    if error_msg:
        marker['error_msg'] = error_msg[:200]  # 限制长度
    return marker


def create_decode_failed_marker(
    file_path: str,
    error_msg: Optional[str] = None
) -> Dict[str, Any]:
    """
    创建解码失败标记
    
    Args:
        file_path: 文件路径
        error_msg: 错误信息
    
    Returns:
        标记字典
    """
    marker = {
        'skipped': True,
        'skip_reason': SkipReason.DECODE_FAILED.value,
        'skip_description': get_skip_description(SkipReason.DECODE_FAILED),
        'file_path': file_path,
    }
    if error_msg:
        marker['error_msg'] = error_msg[:200]
    return marker


# ========== 测试 ==========

if __name__ == '__main__':
    print("=" * 60)
    print("媒体质量过滤模块测试")
    print("=" * 60)
    
    # 图片测试
    print("\n[图片测试]")
    test_cases_image = [
        (32, 32, 1000, "极小图标"),
        (64, 64, 8000, "边界-刚好跳过"),
        (120, 120, 15000, "CHAT_STICKER_PACK"),
        (300, 300, 50000, "边界-刚好完整处理"),
        (1920, 1080, 500000, "标准照片"),
        (500, 8000, 2000000, "超长截图"),
    ]
    
    for w, h, size, desc in test_cases_image:
        decision = filter_image(w, h, size)
        print(f"  {desc} ({w}x{h}, {size}B): {decision.tier.value} - {decision.reason}")
    
    # 视频测试
    print("\n[视频测试]")
    test_cases_video = [
        (1920, 1080, 0.5, 100000, "极短视频"),
        (1920, 1080, 2.0, 500000, "短视频"),
        (320, 240, 10.0, 1000000, "低清视频"),
        (1920, 1080, 30.0, 50000000, "标准视频"),
    ]
    
    for w, h, dur, size, desc in test_cases_video:
        decision = filter_video(w, h, dur, size)
        print(f"  {desc} ({w}x{h}, {dur}s): {decision.tier.value} - {decision.reason}")
    
    # 表情包测试
    print("\n[表情包测试]")
    test_cases_sticker = [
        (24, 24, 500, 1, "极小静态"),
        (48, 48, 3000, 1, "小静态"),
        (120, 120, 50000, 1, "标准静态"),
        (240, 240, 500000, 50, "标准动图"),
        (240, 240, 2000000, 200, "超长动图"),
    ]
    
    for w, h, size, frames, desc in test_cases_sticker:
        decision = filter_sticker(w, h, size, frames)
        print(f"  {desc} ({w}x{h}, {frames}帧): {decision.tier.value} - {decision.reason}")
    
    print("\n✅ 测试完成")
