#!/usr/bin/env python3
"""
视频预处理步骤（元数据提取 + 音频分离 + 智能关键帧提取）

功能：
- 提取视频元数据（时长、分辨率、编码格式）
- 分离音频轨道（用于后续转写）
- 智能关键帧提取（自适应帧数策略）
- 运动检测算法（避免提取相似帧）

处理流程：
1. 扫描 raw/video/ 目录下的所有视频文件
2. 对每个视频：
   a. 使用 ffprobe 提取元数据
   b. 使用 ffmpeg 分离音频（AAC 格式）
   c. 计算自适应帧数（基于时长和运动强度）
   d. 提取关键帧（均匀采样 + 运动检测）
   e. 保存到 /data/cache/video_keyframes/
3. 输出元数据到 video_extract_v1.jsonl

自适应帧数策略：
- 短视频（<30s）：3-5 帧
- 中等视频（30s-2min）：5-8 帧
- 长视频（>2min）：8-12 帧
- 敏感模式（--sensitive-first）：帧数 +50%

运动检测算法：
- 计算相邻帧的直方图差异
- 过滤相似帧（差异 < 阈值）
- 保留运动变化明显的关键帧

输入：
- raw/video/YYYY-MM/*.mp4: 原始视频文件
- configs/video.yaml: 视频配置（帧数策略、运动阈值）

输出：
- artifacts/before_merge/video/video_extract_v1.jsonl: 元数据
  * 包含：msg_uid, duration, width, height, fps, codec, keyframe_count
- /data/cache/video_keyframes/{msg_uid}/: 关键帧图片
- /data/cache/video_audio/{msg_uid}.aac: 音频文件

依赖：
- ffmpeg: 视频处理
- ffprobe: 元数据提取
- opencv-python: 运动检测
- scripts._common.path_utils: 路径工具

使用示例：
    python scripts/video/run_all/_01_run_extract.py                    # 处理全部
    python scripts/video/run_all/_01_run_extract.py --test-dir         # 测试目录
    python scripts/video/run_all/_01_run_extract.py --sample 3         # 仅处理前3个
    python scripts/video/run_all/_01_run_extract.py --sensitive-first  # 敏感优先模式

注意事项：
- 确保 ffmpeg 和 ffprobe 已安装
- 关键帧会缓存到 /data/cache/，注意磁盘空间
- 运动检测可能耗时，建议使用 --sample 测试

作者：[Author]
更新于：2026-02-02
"""
import os
import sys
import json
import argparse
import hashlib
import subprocess
from pathlib import Path
from datetime import datetime
from tqdm import tqdm

# 确保 tqdm 输出到 stderr 以便实时显示
tqdm_kwargs = {"file": sys.stderr, "dynamic_ncols": True}

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts._common.path_utils import (
    get_video_dir, get_video_before_merge,
    get_video_keyframes_cache, get_video_audio_cache,
    get_test_videos_dir, load_video_config
)
from scripts._common.media_filter import (
    filter_video, FilterTier, SkipReason,
    create_skip_marker, create_decode_failed_marker
)

# ========== 加载配置 ==========
video_config = load_video_config()
kf_config = video_config.get('keyframe_extraction', {})
SCHEMA_VERSION = video_config.get('schema_version', 'video_v1')


def compute_motion_intensity(motion_results: list) -> float:
    """
    计算视频整体运动强度
    
    Args:
        motion_results: [(timestamp, motion_score), ...]
    
    Returns:
        motion_intensity: 0.0-1.0 之间的运动强度值
    """
    if not motion_results:
        return 0.0
    
    import numpy as np
    scores = [score for _, score in motion_results]
    
    # 使用多个指标综合评估
    avg_score = np.mean(scores)
    p90_score = np.percentile(scores, 90)
    high_motion_ratio = sum(1 for s in scores if s > 0.2) / len(scores)
    
    # 综合计算强度值
    intensity = (avg_score * 0.3 + p90_score * 0.4 + high_motion_ratio * 0.3)
    return min(1.0, intensity)


def calculate_adaptive_max_frames(
    duration: float,
    motion_intensity: float,
    sensitive_mode: bool = False,
    scene_change_count: int = 0
) -> tuple[int, float, str]:
    """
    自适应计算最大帧数（整合ABC三方案 + 场景变化感知）
    
    方案A: 动态帧数上限 - 根据运动强度调整
    方案B: 分段自适应 - 返回建议的采样间隔
    方案C: 内容类型检测 - 高动态内容特殊处理
    方案D: 场景变化感知 - 区分"真实场景变化"和"相机抖动/小幅运动"
    
    Args:
        duration: 视频时长（秒）
        motion_intensity: 运动强度 (0.0-1.0)
        sensitive_mode: 是否敏感模式
        scene_change_count: 场景检测到的变化帧数（用于区分真实场景变化和相机抖动）
    
    Returns:
        (max_frames, min_interval, content_type)
    """
    # 获取配置的上限值
    base_max = kf_config.get('max_frames', 12)
    sensitive_max = kf_config.get('max_frames_sensitive', 16)
    high_motion_max = kf_config.get('max_frames_high_motion', 16)
    vram_safe_max = kf_config.get('vram_safe_max_frames', 16)
    
    high_motion_threshold = kf_config.get('motion_detection', {}).get('high_motion_threshold', 0.15)
    medium_motion_threshold = 0.08  # 中等运动阈值
    
    # 判断内容类型（更细致的分类）
    # 新增：检测"高运动但低场景变化"的情况（如婚礼视频：相机抖动但场景不变）
    is_static_scene_with_motion = (
        motion_intensity >= high_motion_threshold and 
        scene_change_count <= 2 and  # 场景变化很少
        duration > 5.0  # 视频足够长
    )
    
    if is_static_scene_with_motion:
        # 特殊情况：高运动但场景不变（相机抖动、人物小幅移动等）
        content_type = 'static_scene_motion'
    elif motion_intensity >= high_motion_threshold:
        content_type = 'high_motion'
    elif motion_intensity >= medium_motion_threshold:
        content_type = 'medium_motion'  # 有局部运动，如猫头摆动
    else:
        content_type = 'low_motion'
    
    # 方案A: 基于运动强度的动态帧数
    if sensitive_mode:
        base_frames = sensitive_max
    elif content_type == 'static_scene_motion':
        # 静态场景+运动：不需要太多帧，场景内容变化不大
        base_frames = base_max  # 使用普通上限，不用高动态上限
    elif content_type == 'high_motion':
        base_frames = high_motion_max
    elif content_type == 'medium_motion':
        base_frames = int((base_max + high_motion_max) / 2)  # 中等运动取平均值
    else:
        base_frames = base_max
    
    # 根据时长和配置的采样间隔调整
    if content_type == 'static_scene_motion':
        # 静态场景+运动：使用较大间隔，避免过多冗余帧
        base_interval = kf_config.get('min_interval_sec', 1.0) * 1.2  # 比普通更稀疏
    elif content_type == 'high_motion':
        base_interval = kf_config.get('min_interval_sec_high_motion', 0.5)
    elif content_type == 'medium_motion':
        base_interval = kf_config.get('min_interval_sec', 1.0) * 0.7  # 中等运动：比普通密集30%
    elif sensitive_mode:
        base_interval = kf_config.get('min_interval_sec_sensitive', 0.8)
    else:
        base_interval = kf_config.get('min_interval_sec', 1.0)
    
    min_frames = kf_config.get('min_frames', 4)
    duration_based = max(min_frames, int(duration / base_interval) + 2)
    
    # 方案A: 运动强度加成（静态场景+运动不加成）
    if content_type == 'static_scene_motion':
        motion_bonus = 0  # 不加成
    else:
        motion_bonus = int(duration_based * motion_intensity * 0.5)
    target_frames = min(base_frames, duration_based + motion_bonus)
    
    # 最小帧数保障
    if content_type == 'high_motion':
        target_frames = max(target_frames, 10)  # 高动态至少10帧
    elif content_type == 'medium_motion':
        target_frames = max(target_frames, 8)   # 中等运动至少8帧
    elif content_type == 'static_scene_motion':
        target_frames = max(target_frames, 6)   # 静态场景+运动至少6帧
    
    # 确保不超过VRAM安全限制
    target_frames = min(target_frames, vram_safe_max)
    
    # 方案B: 计算建议采样间隔
    if content_type == 'static_scene_motion':
        min_interval = kf_config.get('min_interval_sec', 1.0) * 1.2  # 更稀疏
    elif content_type == 'high_motion':
        min_interval = kf_config.get('min_interval_sec_high_motion', 0.5)
    elif content_type == 'medium_motion':
        min_interval = kf_config.get('min_interval_sec', 1.0) * 0.7  # 中等运动更密集
    elif sensitive_mode:
        min_interval = kf_config.get('min_interval_sec_sensitive', 0.8)
    else:
        min_interval = kf_config.get('min_interval_sec', 1.0)
    
    # 根据运动强度进一步微调间隔（静态场景+运动不微调）
    if content_type != 'static_scene_motion':
        if motion_intensity > 0.3:
            min_interval *= 0.6  # 高动态视频更密集采样
        elif motion_intensity > 0.1:
            min_interval *= 0.8  # 中等运动适度密集
    
    return (target_frames, min_interval, content_type)

def get_video_metadata(video_path: Path) -> dict:
    """使用 ffprobe 提取视频元数据"""
    cmd = [
        'ffprobe', '-v', 'quiet', '-print_format', 'json',
        '-show_format', '-show_streams', str(video_path)
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
        
        # 解析视频流
        video_stream = None
        audio_stream = None
        for stream in data.get('streams', []):
            if stream.get('codec_type') == 'video' and not video_stream:
                video_stream = stream
            elif stream.get('codec_type') == 'audio' and not audio_stream:
                audio_stream = stream
        
        format_info = data.get('format', {})
        
        metadata = {
            'duration_sec': float(format_info.get('duration', 0)),
            'width': int(video_stream.get('width', 0)) if video_stream else 0,
            'height': int(video_stream.get('height', 0)) if video_stream else 0,
            'fps': eval(video_stream.get('r_frame_rate', '0/1')) if video_stream else 0,
            'codec': video_stream.get('codec_name', '') if video_stream else '',
            'has_audio': audio_stream is not None,
            'audio_sample_rate': int(audio_stream.get('sample_rate', 0)) if audio_stream else 0,
            'audio_channels': int(audio_stream.get('channels', 0)) if audio_stream else 0,
        }
        return metadata
    except Exception as e:
        return {'error': str(e)}


def extract_audio(video_path: Path, output_dir: Path) -> str | None:
    """提取音频轨道为 wav 文件"""
    output_dir.mkdir(parents=True, exist_ok=True)
    audio_path = output_dir / f"{video_path.stem}.wav"
    
    cmd = [
        'ffmpeg', '-y', '-i', str(video_path),
        '-vn', '-acodec', 'pcm_s16le', '-ar', '16000', '-ac', '1',
        str(audio_path)
    ]
    try:
        subprocess.run(cmd, capture_output=True, check=True)
        return str(audio_path) if audio_path.exists() else None
    except subprocess.CalledProcessError:
        return None


def compute_motion_score(frame1_path: Path, frame2_path: Path) -> float:
    """
    计算两帧之间的运动分数（基于光流）
    返回值范围 0-1，越大表示运动越剧烈
    """
    try:
        import cv2
        import numpy as np
        
        # 读取帧并转灰度
        img1 = cv2.imread(str(frame1_path), cv2.IMREAD_GRAYSCALE)
        img2 = cv2.imread(str(frame2_path), cv2.IMREAD_GRAYSCALE)
        
        if img1 is None or img2 is None:
            return 0.0
        
        # 缩小尺寸加速计算
        scale = 0.5
        img1 = cv2.resize(img1, None, fx=scale, fy=scale)
        img2 = cv2.resize(img2, None, fx=scale, fy=scale)
        
        # 计算稠密光流 (Farneback)
        flow = cv2.calcOpticalFlowFarneback(
            img1, img2, None,
            pyr_scale=0.5, levels=3, winsize=15,
            iterations=3, poly_n=5, poly_sigma=1.2, flags=0
        )
        
        # 计算光流幅度
        mag, _ = cv2.cartToPolar(flow[..., 0], flow[..., 1])
        
        # 归一化：取平均幅度，除以图像对角线长度
        diag = np.sqrt(img1.shape[0]**2 + img1.shape[1]**2)
        motion_score = np.mean(mag) / diag * 10  # 放大系数
        
        return min(1.0, motion_score)
    except Exception as e:
        print(f"  Warning: Motion detection failed: {e}")
        return 0.0


def detect_motion_frames(
    video_path: Path,
    output_dir: Path,
    motion_threshold: float = 0.15,
    sample_interval: float = 0.5,
    max_dim: int = 512
) -> list[tuple[float, float]]:
    """
    基于光流检测局部运动帧
    返回: [(timestamp, motion_score), ...]
    """
    import tempfile
    
    # 获取视频时长
    metadata = get_video_metadata(video_path)
    duration = metadata.get('duration_sec', 0)
    if duration <= 0:
        return []
    
    # 采样时间点
    timestamps = []
    t = 0.0
    while t < duration:
        timestamps.append(t)
        t += sample_interval
    
    if len(timestamps) < 2:
        return []
    
    # 提取采样帧到临时目录
    temp_dir = Path(tempfile.mkdtemp(prefix='motion_'))
    temp_frames = []
    
    for i, ts in enumerate(timestamps):
        temp_path = temp_dir / f"sample_{i:04d}.jpg"
        cmd = [
            'ffmpeg', '-y', '-ss', str(ts), '-i', str(video_path),
            '-vf', f"scale='min({max_dim},iw)':min'({max_dim},ih)':force_original_aspect_ratio=decrease",
            '-frames:v', '1', '-q:v', '3', str(temp_path)
        ]
        try:
            subprocess.run(cmd, capture_output=True, check=True, timeout=10)
            if temp_path.exists():
                temp_frames.append((ts, temp_path))
        except:
            pass
    
    # 计算相邻帧的运动分数
    motion_results = []
    for i in range(1, len(temp_frames)):
        ts_prev, path_prev = temp_frames[i-1]
        ts_curr, path_curr = temp_frames[i]
        
        motion_score = compute_motion_score(path_prev, path_curr)
        
        if motion_score >= motion_threshold:
            # 取两帧中间时间点
            mid_ts = (ts_prev + ts_curr) / 2
            motion_results.append((mid_ts, motion_score))
    
    # 清理临时文件
    for _, path in temp_frames:
        path.unlink(missing_ok=True)
    temp_dir.rmdir()
    
    return motion_results


def extract_keyframes(
    video_path: Path,
    output_dir: Path,
    scene_threshold: float = 0.4,
    max_frames: int = 8,
    min_interval_sec: float = 2.0,
    max_dim: int = 512,
    enable_motion_detection: bool = True
) -> list[dict]:
    """
    智能关键帧提取：
    1. 场景检测提取变化帧（全局画面变化）
    2. 光流检测提取运动帧（局部运动，如猫头摆动）
    3. 均匀采样作为保底（确保有足够帧捕捉动态）
    4. 合并去重
    5. 强制首尾帧
    6. 硬上限截断
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 获取视频时长
    metadata = get_video_metadata(video_path)
    duration = metadata.get('duration_sec', 0)
    if duration <= 0:
        return []
    
    # 计算目标帧数（基于时长，每1.5秒至少1帧，但不超过max_frames）
    target_frames = min(max_frames, max(4, int(duration / 1.5) + 2))
    
    # Step 1: 场景检测提取变化帧（全局画面变化）
    mpdecimate_cfg = kf_config.get('mpdecimate', {})
    hi = mpdecimate_cfg.get('hi', 768)
    lo = mpdecimate_cfg.get('lo', 320)
    frac = mpdecimate_cfg.get('frac', 0.33)
    
    filter_chain = (
        f"mpdecimate=hi={hi}:lo={lo}:frac={frac},"
        f"select='gt(scene,{scene_threshold})',"
        f"scale='min({max_dim},iw)':min'({max_dim},ih)':force_original_aspect_ratio=decrease"
    )
    
    temp_pattern = output_dir / f"{video_path.stem}_scene_%04d.jpg"
    
    cmd = [
        'ffmpeg', '-y', '-i', str(video_path),
        '-vf', filter_chain,
        '-vsync', 'vfr',
        '-q:v', '2',
        str(temp_pattern)
    ]
    
    try:
        subprocess.run(cmd, capture_output=True, check=True, timeout=120)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        print(f"  Warning: Scene detection failed for {video_path.name}: {e}")
    
    scene_frames = sorted(output_dir.glob(f"{video_path.stem}_scene_*.jpg"))
    
    # Step 2: 光流检测局部运动帧（如猫头摆动、手势等）
    motion_frames_info = []
    if enable_motion_detection and duration > 1.0:
        motion_cfg = kf_config.get('motion_detection', {})
        motion_threshold = motion_cfg.get('threshold', 0.15)
        sample_interval = motion_cfg.get('sample_interval', 0.5)
        
        print(f"    Detecting local motion (threshold={motion_threshold})...")
        motion_results = detect_motion_frames(
            video_path, output_dir,
            motion_threshold=motion_threshold,
            sample_interval=sample_interval,
            max_dim=max_dim
        )
        
        # 提取运动帧
        for ts, score in motion_results:
            motion_path = output_dir / f"{video_path.stem}_motion_{int(ts*100):06d}.jpg"
            cmd = [
                'ffmpeg', '-y', '-ss', str(ts), '-i', str(video_path),
                '-vf', f"scale='min({max_dim},iw)':min'({max_dim},ih)':force_original_aspect_ratio=decrease",
                '-frames:v', '1', '-q:v', '2', str(motion_path)
            ]
            try:
                subprocess.run(cmd, capture_output=True, check=True, timeout=30)
                if motion_path.exists():
                    motion_frames_info.append((ts, motion_path, score))
            except:
                pass
        
        if motion_frames_info:
            print(f"    Found {len(motion_frames_info)} motion frames")
    
    # Step 3: 均匀采样作为保底（确保有足够的帧捕捉动态）
    uniform_timestamps = []
    if target_frames > 2:
        interval = duration / (target_frames - 1)
        for i in range(target_frames):
            ts = i * interval
            uniform_timestamps.append(round(ts, 2))
    else:
        uniform_timestamps = [0.0, round(duration, 2)]
    
    # 提取均匀采样帧（跳过首尾，它们单独处理）
    uniform_frames = []
    for i, ts in enumerate(uniform_timestamps):
        if ts <= 0.1 or ts >= duration - 0.1:
            continue  # 首尾帧单独处理
        
        uniform_path = output_dir / f"{video_path.stem}_uniform_{i:04d}.jpg"
        cmd = [
            'ffmpeg', '-y', '-ss', str(ts), '-i', str(video_path),
            '-vf', f"scale='min({max_dim},iw)':min'({max_dim},ih)':force_original_aspect_ratio=decrease",
            '-frames:v', '1', '-q:v', '2', str(uniform_path)
        ]
        try:
            subprocess.run(cmd, capture_output=True, check=True, timeout=30)
            if uniform_path.exists():
                uniform_frames.append((ts, uniform_path))
        except:
            pass
    
    # Step 4: 提取首帧和尾帧（强制保留）
    first_frame_path = output_dir / f"{video_path.stem}_first.jpg"
    last_frame_path = output_dir / f"{video_path.stem}_last.jpg"
    
    subprocess.run([
        'ffmpeg', '-y', '-i', str(video_path),
        '-vf', f"scale='min({max_dim},iw)':min'({max_dim},ih)':force_original_aspect_ratio=decrease",
        '-frames:v', '1', '-q:v', '2', str(first_frame_path)
    ], capture_output=True)
    
    subprocess.run([
        'ffmpeg', '-y', '-sseof', '-0.5', '-i', str(video_path),
        '-vf', f"scale='min({max_dim},iw)':min'({max_dim},ih)':force_original_aspect_ratio=decrease",
        '-frames:v', '1', '-q:v', '2', str(last_frame_path)
    ], capture_output=True)
    
    # Step 5: 合并所有候选帧，按时间戳排序
    all_candidates = []
    
    # 添加场景检测帧（估算时间戳）
    for i, frame_path in enumerate(scene_frames):
        estimated_ts = (i + 1) / (len(scene_frames) + 1) * duration
        all_candidates.append({
            'timestamp': estimated_ts,
            'path': frame_path,
            'source': 'scene',
            'score': scene_threshold
        })
    
    # 添加均匀采样帧
    for ts, frame_path in uniform_frames:
        all_candidates.append({
            'timestamp': ts,
            'path': frame_path,
            'source': 'uniform',
            'score': 0.0
        })
    
    # 添加光流运动帧
    for ts, frame_path, motion_score in motion_frames_info:
        all_candidates.append({
            'timestamp': ts,
            'path': frame_path,
            'source': 'motion',
            'score': motion_score
        })
    
    # 按时间戳排序
    all_candidates.sort(key=lambda x: x['timestamp'])
    
    # Step 6: 去重（时间间隔过滤，允许更密集的采样）
    filtered_candidates = []
    last_ts = 0.0
    min_gap = min(min_interval_sec * 0.5, 1.0)  # 最小间隔0.5-1秒
    
    for cand in all_candidates:
        if cand['timestamp'] - last_ts >= min_gap:
            filtered_candidates.append(cand)
            last_ts = cand['timestamp']
        else:
            # 删除重复帧
            cand['path'].unlink(missing_ok=True)
    
    # Step 6: 构建最终帧列表
    keyframes = []
    frame_idx = 0
    
    # 添加首帧
    if first_frame_path.exists():
        final_first = output_dir / f"{video_path.stem}_{frame_idx:04d}.jpg"
        first_frame_path.rename(final_first)
        keyframes.append({
            'frame_id': frame_idx,
            'timestamp_sec': 0.0,
            'frame_path': str(final_first),
            'scene_score': 0.0,
            'is_forced': True,
            'source': 'first'
        })
        frame_idx += 1
    
    # 添加中间帧（限制数量）
    max_middle_frames = max_frames - 2  # 留位置给首尾帧
    for cand in filtered_candidates[:max_middle_frames]:
        final_path = output_dir / f"{video_path.stem}_{frame_idx:04d}.jpg"
        cand['path'].rename(final_path)
        keyframes.append({
            'frame_id': frame_idx,
            'timestamp_sec': round(cand['timestamp'], 2),
            'frame_path': str(final_path),
            'scene_score': cand['score'],
            'is_forced': False,
            'source': cand['source']
        })
        frame_idx += 1
    
    # 添加尾帧
    if last_frame_path.exists() and duration > 0:
        final_last = output_dir / f"{video_path.stem}_{frame_idx:04d}.jpg"
        last_frame_path.rename(final_last)
        keyframes.append({
            'frame_id': frame_idx,
            'timestamp_sec': round(duration, 2),
            'frame_path': str(final_last),
            'scene_score': 0.0,
            'is_forced': True,
            'source': 'last'
        })
    
    # 清理未使用的临时帧
    for f in output_dir.glob(f"{video_path.stem}_scene_*.jpg"):
        f.unlink(missing_ok=True)
    for f in output_dir.glob(f"{video_path.stem}_uniform_*.jpg"):
        f.unlink(missing_ok=True)
    for f in output_dir.glob(f"{video_path.stem}_first.jpg"):
        f.unlink(missing_ok=True)
    for f in output_dir.glob(f"{video_path.stem}_last.jpg"):
        f.unlink(missing_ok=True)
    
    return keyframes


def compute_file_hash(file_path: Path) -> str:
    """计算文件 SHA256 哈希"""
    sha256 = hashlib.sha256()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            sha256.update(chunk)
    return sha256.hexdigest()


def process_video(video_path: Path, keyframes_dir: Path, audio_dir: Path, sensitive_mode: bool = False) -> dict:
    """处理单个视频（使用自适应帧数策略）"""
    # 提取元数据
    metadata = get_video_metadata(video_path)
    
    if 'error' in metadata:
        # 元数据提取失败
        result = {
            'schema_version': SCHEMA_VERSION,
            'file': video_path.name,
            'error': metadata['error']
        }
        result.update(create_decode_failed_marker(str(video_path), metadata['error']))
        return result
    
    duration = metadata.get('duration_sec', 0)
    width = metadata.get('width', 0)
    height = metadata.get('height', 0)
    fps = metadata.get('fps', 30)
    
    # === 媒体质量过滤 ===
    file_size = video_path.stat().st_size if video_path.exists() else 0
    filter_decision = filter_video(width, height, duration, file_size, fps)
    
    if filter_decision.should_skip:
        # 视频被跳过（时长过短或文件过小）
        result = {
            'schema_version': SCHEMA_VERSION,
            'file': video_path.name,
            'metadata': metadata,
            'filter_tier': filter_decision.tier.value,
            'filter_reason': filter_decision.reason,
        }
        result.update(filter_decision.to_skip_marker())
        return result
    
    # 计算视频哈希
    video_sha256 = compute_file_hash(video_path)
    
    # 确定分辨率
    resize_cfg = kf_config.get('resize', {})
    max_dim = resize_cfg.get('normal_max_dim', 512)
    
    # === 短视频只取首帧处理 ===
    if filter_decision.tier == FilterTier.SINGLE_FRAME:
        # 只提取首帧，不做完整视频分析
        video_keyframes_dir = keyframes_dir / video_path.stem
        video_keyframes_dir.mkdir(parents=True, exist_ok=True)
        
        first_frame_path = video_keyframes_dir / f"{video_path.stem}_0000.jpg"
        subprocess.run([
            'ffmpeg', '-y', '-i', str(video_path),
            '-vf', f"scale='min({max_dim},iw)':min'({max_dim},ih)':force_original_aspect_ratio=decrease",
            '-frames:v', '1', '-q:v', '2', str(first_frame_path)
        ], capture_output=True)
        
        keyframes = []
        if first_frame_path.exists():
            keyframes = [{
                'frame_id': 0,
                'timestamp_sec': 0.0,
                'frame_path': str(first_frame_path),
                'scene_score': 0.0,
                'is_forced': True,
                'source': 'single_frame_mode',
                'frame_sha256': compute_file_hash(first_frame_path)
            }]
        
        # 提取音频（如果有）
        audio_path = None
        if metadata.get('has_audio'):
            audio_path = extract_audio(video_path, audio_dir)
        
        return {
            'schema_version': SCHEMA_VERSION,
            'file': video_path.name,
            'video_sha256': video_sha256,
            'metadata': metadata,
            'keyframes': keyframes,
            'audio_path': audio_path,
            'filter_tier': filter_decision.tier.value,
            'filter_reason': filter_decision.reason,
            'extraction_params': {
                'mode': 'single_frame',
                'resize_max_dim': max_dim,
            }
        }
    
    # === 低清视频轻量处理 ===
    if filter_decision.tier == FilterTier.LITE:
        # 低清视频：只提取少量关键帧，不做深度分析
        video_keyframes_dir = keyframes_dir / video_path.stem
        keyframes = extract_keyframes(
            video_path,
            video_keyframes_dir,
            scene_threshold=0.5,  # 更高阈值，减少帧数
            max_frames=4,  # 最多4帧
            min_interval_sec=3.0,  # 更大间隔
            max_dim=max_dim
        )
        
        for kf in keyframes:
            kf_path = Path(kf['frame_path'])
            if kf_path.exists():
                kf['frame_sha256'] = compute_file_hash(kf_path)
        
        audio_path = None
        if metadata.get('has_audio'):
            audio_path = extract_audio(video_path, audio_dir)
        
        return {
            'schema_version': SCHEMA_VERSION,
            'file': video_path.name,
            'video_sha256': video_sha256,
            'metadata': metadata,
            'keyframes': keyframes,
            'audio_path': audio_path,
            'filter_tier': filter_decision.tier.value,
            'filter_reason': filter_decision.reason,
            'extraction_params': {
                'mode': 'lite',
                'scene_threshold': 0.5,
                'max_frames': 4,
                'resize_max_dim': max_dim,
            }
        }
    
    # === 完整处理（原有逻辑）===
    
    # === 自适应帧数计算（整合ABC三方案 + 场景变化感知）===
    
    # Step 1: 先进行运动检测（用于计算运动强度）
    motion_cfg = kf_config.get('motion_detection', {})
    motion_threshold = motion_cfg.get('threshold', 0.08)
    sample_interval = motion_cfg.get('sample_interval', 0.3)
    
    motion_results = []
    if motion_cfg.get('enabled', True) and duration > 1.0:
        try:
            video_keyframes_temp = keyframes_dir / f"{video_path.stem}_temp"
            motion_results = detect_motion_frames(
                video_path, video_keyframes_temp,
                motion_threshold=motion_threshold,
                sample_interval=sample_interval,
                max_dim=max_dim
            )
        except Exception as e:
            print(f"  Warning: Motion detection failed: {e}")
    
    # Step 2: 计算运动强度
    motion_intensity = compute_motion_intensity(motion_results)
    
    # Step 2.5: 快速场景变化检测（用于区分真实场景变化和相机抖动）
    scene_change_count = 0
    if motion_intensity >= 0.15 and duration > 3.0:  # 只对高运动视频做场景检测
        try:
            import tempfile
            temp_scene_dir = Path(tempfile.mkdtemp(prefix='scene_check_'))
            scene_threshold = kf_config.get('scene_threshold', 0.4)
            mpdecimate_cfg = kf_config.get('mpdecimate', {})
            hi = mpdecimate_cfg.get('hi', 768)
            lo = mpdecimate_cfg.get('lo', 320)
            frac = mpdecimate_cfg.get('frac', 0.33)
            
            filter_chain = (
                f"mpdecimate=hi={hi}:lo={lo}:frac={frac},"
                f"select='gt(scene,{scene_threshold})',"
                f"scale='min(256,iw)':min'(256,ih)':force_original_aspect_ratio=decrease"
            )
            temp_pattern = temp_scene_dir / "scene_%04d.jpg"
            
            cmd = [
                'ffmpeg', '-y', '-i', str(video_path),
                '-vf', filter_chain,
                '-vsync', 'vfr',
                '-q:v', '5',  # 低质量，只用于计数
                str(temp_pattern)
            ]
            subprocess.run(cmd, capture_output=True, timeout=30)
            scene_change_count = len(list(temp_scene_dir.glob("scene_*.jpg")))
            
            # 清理临时文件
            for f in temp_scene_dir.glob("*.jpg"):
                f.unlink(missing_ok=True)
            temp_scene_dir.rmdir()
            
            print(f"    Scene changes detected: {scene_change_count}")
        except Exception as e:
            print(f"  Warning: Scene detection failed: {e}")
    
    # Step 3: 自适应计算帧数和采样间隔
    max_frames, min_interval, content_type = calculate_adaptive_max_frames(
        duration=duration,
        motion_intensity=motion_intensity,
        sensitive_mode=sensitive_mode,
        scene_change_count=scene_change_count
    )
    
    print(f"    Motion: intensity={motion_intensity:.3f}, type={content_type}, "
          f"max_frames={max_frames}, interval={min_interval:.2f}s")
    
    # === 提取关键帧 ===
    video_keyframes_dir = keyframes_dir / video_path.stem
    keyframes = extract_keyframes(
        video_path,
        video_keyframes_dir,
        scene_threshold=kf_config.get('scene_threshold', 0.4),
        max_frames=max_frames,
        min_interval_sec=min_interval,
        max_dim=max_dim
    )
    
    # 计算关键帧哈希
    for kf in keyframes:
        kf_path = Path(kf['frame_path'])
        if kf_path.exists():
            kf['frame_sha256'] = compute_file_hash(kf_path)
    
    # 提取音频
    audio_path = None
    if metadata.get('has_audio'):
        audio_path = extract_audio(video_path, audio_dir)
    
    return {
        'schema_version': SCHEMA_VERSION,
        'file': video_path.name,
        'video_sha256': video_sha256,
        'metadata': metadata,
        'keyframes': keyframes,
        'audio_path': audio_path,
        'extraction_params': {
            'scene_threshold': kf_config.get('scene_threshold', 0.4),
            'min_interval_sec': min_interval,
            'max_frames': max_frames,
            'resize_max_dim': max_dim,
            'sensitive_mode': sensitive_mode,
            # 新增自适应参数
            'motion_intensity': round(motion_intensity, 4),
            'content_type': content_type,
            'motion_frames_detected': len(motion_results),
            'scene_change_count': scene_change_count
        },
        'filter_tier': filter_decision.tier.value,
        'filter_reason': filter_decision.reason,
    }


def main():
    parser = argparse.ArgumentParser(description='Video Extraction Pipeline')
    parser.add_argument('--sample', type=int, default=0, help='仅处理前N个文件')
    parser.add_argument('--test-dir', action='store_true', help='使用测试目录')
    parser.add_argument('--sensitive-first', action='store_true', help='敏感优先模式')
    args = parser.parse_args()
    
    print("=" * 60)
    print("Video Extraction Pipeline")
    print("=" * 60)
    
    # 确定输入目录
    if args.test_dir:
        video_dir = get_test_videos_dir()
        print(f"  Mode: Test (using tests/manual_videos/)")
        # 测试模式：从文件系统扫描
        video_extensions = ['.mp4', '.avi', '.mov', '.mkv', '.webm']
        video_files = []
        for ext in video_extensions:
            video_files.extend(video_dir.rglob(f'*{ext}'))
            video_files.extend(video_dir.rglob(f'*{ext.upper()}'))
        video_files = sorted(set(video_files))
        # 构造消息记录（测试模式无原始消息）
        video_messages = []
        for vf in video_files:
            video_messages.append({
                'msg_uid': f"test:{vf.stem}",
                'seq_in_html': -1,
                'MsgSvrID': '',
                'token': '',
                'ts': 0,
                'time_local': '',
                'speaker': 'UNKNOWN',
                'type': 43,
                'sub_type': 0,
                'modality': 'video',
                'media_path': str(vf.relative_to(PROJECT_ROOT)),
                '_video_path': vf
            })
    else:
        video_dir = get_video_dir()
        print(f"  Mode: Production (using raw/video/)")
        # 生产模式：从 P1_messages_raw.jsonl 获取视频消息
        from scripts._common.path_utils import get_messages_path
        messages_file = get_messages_path()
        print(f"  Messages File: {messages_file}")
        
        video_messages = []
        with messages_file.open('r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    msg = json.loads(line)
                    if msg.get('modality') == 'video' or msg.get('type') == 43:
                        media_path = msg.get('media_path', '')
                        if media_path:
                            # 解析实际文件路径
                            video_path = PROJECT_ROOT / media_path
                            if video_path.exists():
                                msg['_video_path'] = video_path
                                video_messages.append(msg)
                            else:
                                print(f"  ⚠️ Video not found: {video_path}")
    
    print(f"  Video Dir: {video_dir}")
    
    # 输出目录
    output_dir = get_video_before_merge()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / "video_extract_v1.jsonl"
    
    # 缓存目录
    keyframes_dir = get_video_keyframes_cache()
    audio_dir = get_video_audio_cache()
    keyframes_dir.mkdir(parents=True, exist_ok=True)
    audio_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"  Output: {output_file}")
    print(f"  Keyframes Cache: {keyframes_dir}")
    print(f"  Audio Cache: {audio_dir}")
    
    if args.sensitive_first:
        print(f"  Sensitive Mode: ON (max_frames={kf_config.get('max_frames_sensitive', 12)})")
    
    total = len(video_messages)
    print(f"\n[1/2] Found {total} video messages.")
    
    if args.sample > 0:
        video_messages = video_messages[:args.sample]
        print(f"      Sample mode: processing only {len(video_messages)} messages")
    
    # 处理视频
    print("\n[2/2] Processing videos...")
    
    # 统计
    stats = {
        'total': 0,
        'full': 0,
        'single_frame': 0,
        'lite': 0,
        'skipped': 0,
        'error': 0,
    }
    
    with output_file.open('w', encoding='utf-8') as f:
        for msg in tqdm(video_messages, desc="视频提取", **tqdm_kwargs):
            video_path = msg.get('_video_path')
            if not video_path:
                continue
            
            stats['total'] += 1
            
            result = process_video(
                video_path,
                keyframes_dir,
                audio_dir,
                sensitive_mode=args.sensitive_first
            )
            
            # 统计处理结果
            if result.get('skipped'):
                stats['skipped'] += 1
            elif result.get('error'):
                stats['error'] += 1
            elif result.get('filter_tier') == 'single_frame':
                stats['single_frame'] += 1
            elif result.get('filter_tier') == 'lite':
                stats['lite'] += 1
            else:
                stats['full'] += 1
            
            # 保留原始消息的关键字段
            result['msg_uid'] = msg.get('msg_uid', '')
            result['seq_in_html'] = msg.get('seq_in_html', -1)
            result['MsgSvrID'] = msg.get('MsgSvrID', '')
            result['token'] = msg.get('token', '')
            result['ts'] = msg.get('ts', 0)
            result['time_local'] = msg.get('time_local', '')
            result['speaker'] = msg.get('speaker', 'UNKNOWN')
            result['type'] = msg.get('type', 43)
            result['sub_type'] = msg.get('sub_type', 0)
            result['modality'] = 'video'
            result['media_path'] = msg.get('media_path', '')
            
            f.write(json.dumps(result, ensure_ascii=False) + '\n')
    
    print(f"\n✅ Done. Wrote {stats['total']} records to: {output_file}")
    print(f"   Full processing: {stats['full']}")
    print(f"   Single frame: {stats['single_frame']}")
    print(f"   Lite processing: {stats['lite']}")
    print(f"   Skipped: {stats['skipped']}")
    print(f"   Errors: {stats['error']}")


if __name__ == "__main__":
    main()
