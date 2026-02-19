"""
路径管理工具模块 (Path Utilities)

功能：
- 统一管理项目所有路径配置
- 支持多工作空间切换（修改 configs/paths.yaml 中的 workspace_name）
- 支持变量引用（${root}, ${base_dir} 等）
- 为所有模态提供路径访问函数

核心功能：
1. 配置加载：load_paths(), load_*_config()
2. 变量解析：_resolve_variables() 支持 ${var} 格式
3. 路径访问：get_*() 系列函数

工作空间结构：
```
/path/to/data/root/{workspace_name}/
├── raw/                    # 原始数据
│   ├── P1_messages_raw.jsonl
│   ├── image/, voice/, video/, sticker/, file/
├── artifacts/
│   ├── before_merge/       # 单引擎输出
│   └── after_merge/        # 合并结果
├── timeline_out/           # 时间轴输出
│   ├── enriched_full.jsonl
│   └── enriched_slim.jsonl
```

配置文件：
- configs/paths.yaml: 路径配置（支持 ${root} 变量）
- configs/caption.yaml: 图片 VLM 配置
- configs/voice.yaml: 语音 ASR/情绪配置
- configs/video.yaml: 视频关键帧/VLM 配置
- configs/sticker.yaml: 表情包处理配置
- configs/linkfile.yaml: 链接与文件配置
- configs/media_filter.yaml: 媒体质量过滤规则

使用示例：
    from scripts._common.path_utils import (
        get_root, get_timeline_out, get_voice_dir,
        load_paths, PATHS
    )
    
    # 获取工作空间根目录
    root = get_root()
    
    # 获取语音文件目录
    voice_dir = get_voice_dir()
    
    # 访问完整配置
    print(PATHS['workspace_name'])

依赖：
- yaml: 配置文件解析
- pathlib: 路径操作

作者：forcifer
项目：CHAT_APP_DHA - CHAT_APP聊天记录多模态处理流水线
更新于：2026-02-02
"""
import yaml
import os
import re
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _resolve_variables(config: dict) -> dict:
    """
    解析配置中的变量引用（${var} 格式）
    
    支持的变量：
    - ${root}: 自动计算为 {base_dir}/{workspace_name}
    - ${base_dir}: 基础目录（默认：./data）
    - ${workspace_name}: 工作空间名称（默认：demo）
    - 其他顶级键也可作为变量引用
    
    Args:
        config: 原始配置字典
    
    Returns:
        dict: 解析后的配置字典（所有 ${var} 已替换）
    
    Example:
        >>> config = {
        ...     'base_dir': './data',
        ...     'workspace_name': 'demo',
        ...     'dirs': {
        ...         'voice': '${root}/raw/voice'
        ...     }
        ... }
        >>> resolved = _resolve_variables(config)
        >>> print(resolved['dirs']['voice'])
        ./data/demo/raw/voice
    """
    # 计算 root 路径
    base_dir = config.get('base_dir', './data')
    workspace_name = config.get('workspace_name', 'demo')
    root = f"{base_dir}/{workspace_name}"
    
    # 变量映射
    variables = {
        'root': root,
        'base_dir': base_dir,
        'workspace_name': workspace_name,
    }
    
    def replace_vars(value):
        """递归替换字符串中的变量"""
        if isinstance(value, str):
            # 替换 ${var} 格式的变量
            pattern = r'\$\{(\w+)\}'
            def replacer(match):
                var_name = match.group(1)
                return variables.get(var_name, match.group(0))
            return re.sub(pattern, replacer, value)
        elif isinstance(value, dict):
            return {k: replace_vars(v) for k, v in value.items()}
        elif isinstance(value, list):
            return [replace_vars(item) for item in value]
        return value
    
    # 替换所有变量
    resolved = replace_vars(config)
    
    # 添加计算后的 root 到配置
    resolved['root'] = root
    
    return resolved


def load_paths():
    """
    加载路径配置（自动解析变量）
    
    从 configs/paths.yaml 加载配置，并解析所有 ${var} 变量引用。
    
    Returns:
        dict: 解析后的路径配置字典
    
    Raises:
        FileNotFoundError: 如果 configs/paths.yaml 不存在
    
    Example:
        >>> paths = load_paths()
        >>> print(paths['workspace_name'])
        demo
        >>> print(paths['root'])
        ./data/demo
    """
    config_path = PROJECT_ROOT / "configs" / "paths.yaml"
    
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found at {config_path}")
        
    with open(config_path, 'r', encoding='utf-8') as f:
        raw_config = yaml.safe_load(f)
    
    # 解析变量
    return _resolve_variables(raw_config)


def load_voice_config():
    """
    加载语音模态配置
    
    Returns:
        dict: 语音配置字典，包含 FunASR/Whisper/SenseVoice 等引擎配置
    
    Raises:
        FileNotFoundError: 如果 configs/voice.yaml 不存在
    """
    config_path = PROJECT_ROOT / "configs" / "voice.yaml"
    
    if not config_path.exists():
        raise FileNotFoundError(f"Voice config not found at {config_path}")
        
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def load_caption_config():
    """
    加载图片描述配置
    
    Returns:
        dict: 图片 VLM 配置字典，包含专家路由、模型路径等
    
    Raises:
        FileNotFoundError: 如果 configs/caption.yaml 不存在
    """
    config_path = PROJECT_ROOT / "configs" / "caption.yaml"
    
    if not config_path.exists():
        raise FileNotFoundError(f"Caption config not found at {config_path}")
        
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


# Global PATHS object for easy access
try:
    PATHS = load_paths()
except Exception as e:
    print(f"Warning: Could not load paths.yaml: {e}")
    PATHS = {}


def get_path(*keys):
    """
    从嵌套配置字典中获取路径
    
    Args:
        *keys: 嵌套键序列
    
    Returns:
        路径值，如果键不存在则返回 None
    
    Example:
        >>> path = get_path('dirs', 'voice')
        >>> print(path)
        ./data/demo/raw/voice
    """
    val = PATHS
    for key in keys:
        if isinstance(val, dict):
            val = val.get(key)
        else:
            return None
    return val


def get_workspace_name():
    """
    获取当前工作空间名称
    
    Returns:
        str: 工作空间名称（默认：'demo'）
    """
    return PATHS.get('workspace_name', 'demo')


def get_root():
    """
    获取工作空间根目录
    
    Returns:
        Path: 工作空间根目录路径（例如：./data/demo）
    """
    return Path(PATHS.get('root', PROJECT_ROOT))


def get_voice_dir():
    """获取语音文件目录"""
    return Path(PATHS.get('dirs', {}).get('voice', PROJECT_ROOT / 'raw' / 'voice'))


def get_voice_before_merge():
    """获取语音 before_merge 目录"""
    return Path(PATHS.get('artifacts', {}).get('voice_before', PROJECT_ROOT / 'artifacts' / 'before_merge' / 'voice'))


def get_voice_after_merge():
    """获取语音 after_merge 目录"""
    return Path(PATHS.get('artifacts', {}).get('voice_after', PROJECT_ROOT / 'artifacts' / 'after_merge' / 'voice'))


def get_timeline_out():
    """获取 timeline_out 目录"""
    return Path(PATHS.get('timeline_out', PROJECT_ROOT / 'timeline_out'))


def get_messages_path():
    """获取原始消息文件路径"""
    return Path(PATHS.get('raw', {}).get('messages', PROJECT_ROOT / 'raw' / 'P1_messages_raw.jsonl'))


def get_export_dir():
    """获取导出文件目录 (HTML/CSV)"""
    return Path(PATHS.get('dirs', {}).get('export', PROJECT_ROOT / 'raw' / 'export'))


def get_file_dir():
    """获取文件传输目录"""
    return Path(PATHS.get('dirs', {}).get('file', PROJECT_ROOT / 'raw' / 'file'))


# ========== 视频模态路径函数 ==========

def load_video_config():
    """Load video configuration from configs/video.yaml"""
    config_path = PROJECT_ROOT / "configs" / "video.yaml"
    
    if not config_path.exists():
        raise FileNotFoundError(f"Video config not found at {config_path}")
        
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def get_video_dir():
    """获取视频文件目录"""
    return Path(PATHS.get('dirs', {}).get('video', PROJECT_ROOT / 'raw' / 'video'))


def get_video_before_merge():
    """获取视频 before_merge 目录"""
    return Path(PATHS.get('artifacts', {}).get('video_before', PROJECT_ROOT / 'artifacts' / 'before_merge' / 'video'))


def get_video_after_merge():
    """获取视频 after_merge 目录"""
    return Path(PATHS.get('artifacts', {}).get('video_after', PROJECT_ROOT / 'artifacts' / 'after_merge' / 'video'))


def get_video_keyframes_cache():
    """获取视频关键帧缓存目录"""
    return Path(PATHS.get('cache', {}).get('video_keyframes', '/data/cache/video_keyframes'))


def get_video_audio_cache():
    """获取视频音频缓存目录"""
    return Path(PATHS.get('cache', {}).get('video_audio', '/data/cache/video_audio'))


def get_video_normalized_cache():
    """获取视频归一化缓存目录"""
    return Path(PATHS.get('cache', {}).get('video_normalized', '/data/cache/video_normalized'))


def get_test_videos_dir():
    """获取测试视频目录"""
    return Path(PATHS.get('test', {}).get('manual_videos', PROJECT_ROOT / 'tests' / 'manual_videos'))


# ========== 表情包模态路径函数 ==========

def load_sticker_config():
    """Load sticker configuration from configs/sticker.yaml"""
    config_path = PROJECT_ROOT / "configs" / "sticker.yaml"
    
    if not config_path.exists():
        raise FileNotFoundError(f"Sticker config not found at {config_path}")
        
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def get_sticker_dir():
    """获取表情包文件目录"""
    return Path(PATHS.get('dirs', {}).get('sticker', PROJECT_ROOT / 'raw' / 'sticker'))


def get_sticker_before_merge():
    """获取表情包 before_merge 目录"""
    return Path(PATHS.get('artifacts', {}).get('sticker_before', PROJECT_ROOT / 'artifacts' / 'before_merge' / 'sticker'))


def get_sticker_after_merge():
    """获取表情包 after_merge 目录"""
    return Path(PATHS.get('artifacts', {}).get('sticker_after', PROJECT_ROOT / 'artifacts' / 'after_merge' / 'sticker'))


def get_sticker_thumbs_dir():
    """获取表情包缩略图目录"""
    return Path(PATHS.get('artifacts', {}).get('sticker_thumbs', PROJECT_ROOT / 'artifacts' / 'sticker' / 'thumbs'))


def get_sticker_frames_dir():
    """获取表情包关键帧目录"""
    return Path(PATHS.get('artifacts', {}).get('sticker_frames', PROJECT_ROOT / 'artifacts' / 'sticker' / 'frames'))


def get_sticker_temp_cache():
    """获取表情包下载临时缓存目录"""
    return Path(PATHS.get('cache', {}).get('sticker_temp', '/data/cache/sticker/temp'))


# ========== 链接与文件模态路径函数 ==========

def load_linkfile_config():
    """Load linkfile configuration from configs/linkfile.yaml"""
    config_path = PROJECT_ROOT / "configs" / "linkfile.yaml"
    
    if not config_path.exists():
        raise FileNotFoundError(f"Linkfile config not found at {config_path}")
        
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def get_linkfile_before_merge():
    """获取链接与文件 before_merge 目录"""
    return Path(PATHS.get('artifacts', {}).get('linkfile_before', PROJECT_ROOT / 'artifacts' / 'before_merge' / 'linkfile'))


def get_linkfile_after_merge():
    """获取链接与文件 after_merge 目录"""
    return Path(PATHS.get('artifacts', {}).get('linkfile_after', PROJECT_ROOT / 'artifacts' / 'after_merge' / 'linkfile'))


# ========== 媒体过滤配置 ==========

def load_media_filter_config():
    """Load media filter configuration from configs/media_filter.yaml"""
    config_path = PROJECT_ROOT / "configs" / "media_filter.yaml"
    
    if not config_path.exists():
        # 返回默认配置
        return {
            'common': {'min_file_size_bytes': 5120},
            'image': {
                'skip_max_dim': 64,
                'lite_max_dim': 300,
                'long_image_ratio': 5.0,
                'long_image_max_height': 5000,
            },
            'video': {
                'skip_duration_sec': 1.0,
                'single_frame_duration_sec': 3.0,
                'low_res_short_side': 240,
            },
            'sticker': {
                'skip_max_dim': 32,
                'lite_max_dim': 64,
            },
        }
        
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)
