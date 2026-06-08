"""
schema_utils.py
统一的 merged_final.jsonl 字段定义和工具函数

本模块定义了 wechatDHA 项目中四个模态（image, voice, video, sticker）的
merged_final.jsonl 文件的统一字段结构。

核心功能：
1. 定义 SCHEMA_VERSION 版本常量
2. 定义 COMMON_HEADER_FIELDS 公共标识字段列表
3. 定义各模态特定字段列表
4. 提供字段重排和迁移工具函数（后续任务实现）

使用示例：
    from scripts._common.schema_utils import (
        SCHEMA_VERSION,
        COMMON_HEADER_FIELDS,
        IMAGE_SPECIFIC_FIELDS,
    )
"""

from typing import Dict, List, Any, Optional
from collections import OrderedDict


# =============================================================================
# Schema 版本
# =============================================================================

SCHEMA_VERSION = "merged_v2"
"""
Schema 版本标识符。

用于标识 merged_final.jsonl 文件的格式版本：
- "merged_v2": 统一化后的新格式，所有模态使用相同的公共字段顺序
- 无版本或其他值: 旧格式，需要通过 migrate_legacy_record() 迁移
"""


# =============================================================================
# 公共标识字段（按 P1_messages_raw.jsonl 顺序）
# =============================================================================

COMMON_HEADER_FIELDS: List[str] = [
    "schema_version",   # 版本控制，标识数据格式版本
    "seq_in_html",      # 原始序号，消息在 HTML 导出中的顺序
    "msg_uid",          # 唯一标识，格式为 "P1:MsgSvrID"
    "MsgSvrID",         # 服务器ID，微信服务器分配的消息ID
    "token",            # 消息token，用于去重和关联
    "ts",               # Unix时间戳，消息发送时间（秒）
    "time_local",       # 本地时间，格式为 "YYYY-MM-DD HH:MM:SS"
    "speaker",          # 发送者，"ME" 或 "OTHER"
    "type",             # 消息类型，微信消息类型码（如 3=图片, 34=语音, 43=视频, 47=表情）
    "sub_type",         # 子类型，消息子类型码
    "modality",         # 模态，"image", "voice", "video", "sticker" 之一
    "media_path",       # 媒体路径，相对于 raw/ 目录的文件路径
]
"""
所有模态共享的公共标识字段列表。

这些字段按照 P1_messages_raw.jsonl 的顺序排列，确保：
1. 所有 merged_final.jsonl 文件具有一致的字段顺序
2. 可以方便地与原始消息数据关联
3. schema_version 始终是第一个字段，便于版本识别
"""


# =============================================================================
# 各模态特定字段（按逻辑分组）
# =============================================================================

IMAGE_SPECIFIC_FIELDS: List[str] = [
    # 路由分类
    "route_class",          # 图片路由类别（PHOTO, SCREENSHOT, DOCUMENT 等）
    
    # 内容分类（Triage 结果）
    "content_type",         # 内容类型（TYPE_A_NSFW, TYPE_B_GORE, TYPE_C_NORMAL, TYPE_D_DOC）
    "triage_confidence",    # 分类置信度 [0, 1]
    
    # 分数
    "nsfw_score",           # NSFW 分数 [0, 1]
    "sfw_score",            # SFW 分数 [0, 1]
    "text_score",           # 文本密度分数 [0, 1]
    
    # QC（质量控制）
    "ok",                   # 图片是否可解码
    "width",                # 图片宽度（像素）
    "height",               # 图片高度（像素）
    "is_long_image",        # 是否为长图（高宽比 > 阈值）
    
    # OCR
    "ocr_text",             # OCR 识别的文本内容
    "need_ocr",             # 是否需要 OCR（基于 text_score）
    
    # Caption
    "caption",              # VLM 生成的图片描述
    "expert_used",          # 使用的专家模型名称
    "is_fallback",          # 是否使用了 fallback 模型
    
    # 融合元数据
    "ensemble_mode",        # 融合模式（如 "weighted_average"）
    "ensemble_used",        # 是否使用了融合
    
    # 兼容字段
    "caption_model",        # 旧版 caption 模型名称（兼容用）
]
"""
Image 模态特定字段列表。

字段按逻辑分组：
1. 路由分类 - 图片类型判断
2. 内容分类 - Triage 敏感内容检测结果
3. 分数 - 各类评分
4. QC - 图片质量信息
5. OCR - 文字识别结果
6. Caption - 图片描述
7. 融合元数据 - 多模型融合信息
8. 兼容字段 - 向后兼容
"""


VOICE_SPECIFIC_FIELDS: List[str] = [
    # 转写
    "primary_engine",       # 主转写引擎（"funasr" 或 "whisper"）
    "punct_text",           # 带标点的转写文本
    "raw_text",             # 原始转写文本（无标点）
    
    # 原始引擎数据
    "funasr",               # FunASR 引擎原始输出（dict）
    "whisper",              # Whisper 引擎原始输出（dict）
    
    # 情绪分析
    "sensevoice",           # SenseVoice 情绪检测结果（dict，含 emotion_tags, event_tags）
    "trigger_reasons",      # 触发深度分析的原因列表
    "voice_analysis",       # 深度语音分析结果（如有）
]
"""
Voice 模态特定字段列表。

字段按逻辑分组：
1. 转写 - ASR 转写结果
2. 原始引擎数据 - 各引擎的完整输出
3. 情绪分析 - 情绪检测和深度分析结果
"""


VIDEO_SPECIFIC_FIELDS: List[str] = [
    # 视频标识
    "file",                 # 视频文件名
    "video_sha256",         # 视频文件 SHA256 哈希
    
    # 元数据
    "metadata",             # 视频元数据（dict，含 duration, fps, resolution 等）
    
    # 转写
    "transcription",        # 音频转写结果（dict）
    
    # 情绪
    "emotion",              # 音频情绪分析结果（dict）
    
    # 视频理解
    "video_understanding",  # VLM 视频理解结果（dict，含 summary, keyframe_captions 等）
    
    # 关键帧
    "keyframes",            # 关键帧信息列表（list of dict）
    
    # 分类
    "content_type",         # 内容类型（TYPE_A_NSFW, TYPE_B_GORE, TYPE_C_NORMAL, TYPE_D_DOC）
    "triage_confidence",    # 分类置信度 [0, 1]
    
    # 审计
    "audit",                # 审计信息（dict，含处理时间、错误等）
]
"""
Video 模态特定字段列表。

字段按逻辑分组：
1. 视频标识 - 文件名和哈希
2. 元数据 - 视频技术参数
3. 转写 - 音频 ASR 结果
4. 情绪 - 音频情绪分析
5. 视频理解 - VLM 分析结果
6. 关键帧 - 提取的关键帧信息
7. 分类 - 敏感内容检测
8. 审计 - 处理过程记录
"""


STICKER_SPECIFIC_FIELDS: List[str] = [
    # 下载信息
    "url",                  # 表情包原始 URL
    "file_sha256",          # 文件 SHA256 哈希
    "http_status",          # HTTP 下载状态码
    "bytes",                # 文件大小（字节）
    
    # 格式信息
    "detected_format",      # 检测到的实际格式（gif, png, webp 等）
    "content_type_reported",# HTTP Content-Type 报告的格式
    "mismatch",             # 格式是否不匹配
    "final_path",           # 最终保存路径
    
    # QC（质量控制）
    "decode_ok",            # 是否可解码
    "width",                # 宽度（像素）
    "height",               # 高度（像素）
    
    # 分类
    "sticker_class",        # 表情包类别（static, animated 等）
    "is_animated",          # 是否为动图
    "n_frames",             # 总帧数
    
    # 产物路径
    "thumb_path",           # 缩略图路径
    "frame_paths",          # 提取的帧路径列表
    "contact_sheet_path",   # Contact Sheet 路径
    "n_sampled",            # 采样帧数
    "sample_indices",       # 采样帧索引列表
    
    # Triage（敏感内容检测）
    "content_type",         # 内容类型（TYPE_A_NSFW, TYPE_B_GORE, TYPE_C_NORMAL, TYPE_D_DOC）
    "max_nsfw_score",       # 最大 NSFW 分数
    "max_gore_score",       # 最大 Gore 分数
    "is_sensitive",         # 是否为敏感内容
    "trigger_frames",       # 触发敏感检测的帧索引
    
    # Caption
    "caption",              # VLM 生成的表情包描述
    "ocr_text",             # OCR 识别的文本
    "expert_used",          # 使用的专家模型名称
]
"""
Sticker 模态特定字段列表。

字段按逻辑分组：
1. 下载信息 - URL 和下载状态
2. 格式信息 - 文件格式检测
3. QC - 图片质量信息
4. 分类 - 表情包类型
5. 产物路径 - 处理产物位置
6. Triage - 敏感内容检测
7. Caption - 描述和 OCR
"""


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
    
    # 内容字段 (video_channel, chat_history)
    "content_title",        # 内容标题
    
    # 错误处理
    "error_message",        # 处理错误信息
]
"""
Linkfile 模态特定字段列表（type=49 消息）。

字段按逻辑分组：
1. 子类型标识 - link_sub_type
2. 引用消息字段 - quote_* (sub_type=57)
3. 链接字段 - link_* (sub_type=5, 33, 36)
4. 小程序字段 - miniprogram_* (sub_type=33, 36)
5. 文件字段 - file_* (sub_type=6)
6. 内容字段 - content_* (sub_type=19, 51)
7. 错误处理 - error_*
"""


# =============================================================================
# 模态字段映射（便于按模态获取特定字段）
# =============================================================================

MODALITY_SPECIFIC_FIELDS: Dict[str, List[str]] = {
    "image": IMAGE_SPECIFIC_FIELDS,
    "voice": VOICE_SPECIFIC_FIELDS,
    "video": VIDEO_SPECIFIC_FIELDS,
    "sticker": STICKER_SPECIFIC_FIELDS,
    "link_or_file": LINKFILE_SPECIFIC_FIELDS,
}
"""
模态到特定字段列表的映射。

使用示例：
    specific_fields = MODALITY_SPECIFIC_FIELDS.get("image", [])
"""


# =============================================================================
# 工具函数（后续任务实现）
# =============================================================================

def reorder_record(
    record: Dict[str, Any],
    modality: str,
    include_schema_version: bool = True
) -> OrderedDict:
    """
    按标准顺序重排记录字段。
    
    此函数将输入记录的字段按照统一的标准顺序重新排列：
    1. COMMON_HEADER_FIELDS（公共标识字段）
    2. MODALITY_SPECIFIC_FIELDS（模态特定字段）
    3. 其他未知字段（保持原顺序）
    
    同时处理字段名映射，将旧字段名转换为新字段名：
    - timestamp → ts
    - sender → speaker
    
    Args:
        record: 原始记录字典，可以包含任意字段
        modality: 模态类型，必须是 "image", "voice", "video", "sticker" 之一
        include_schema_version: 是否在输出中包含 schema_version 字段。
                               默认为 True。设为 False 可用于生成不含版本的记录。
    
    Returns:
        OrderedDict: 按标准顺序排列的记录。字段顺序为：
                    1. schema_version（如果 include_schema_version=True）
                    2. 其他 COMMON_HEADER_FIELDS
                    3. 模态特定字段
                    4. 其他未知字段
    
    Examples:
        # 基本用法
        >>> record = {'msg_uid': 'P1:123', 'caption': '测试', 'ts': 1749279243}
        >>> result = reorder_record(record, 'image')
        >>> list(result.keys())[:3]
        ['schema_version', 'seq_in_html', 'msg_uid']
        
        # 字段映射
        >>> record = {'timestamp': 1749279243, 'sender': 'ME'}
        >>> result = reorder_record(record, 'image')
        >>> 'ts' in result and 'timestamp' not in result
        True
        >>> 'speaker' in result and 'sender' not in result
        True
        
        # 不包含 schema_version
        >>> record = {'msg_uid': 'P1:123'}
        >>> result = reorder_record(record, 'image', include_schema_version=False)
        >>> 'schema_version' in result
        False
        
        # 保留未知字段
        >>> record = {'msg_uid': 'P1:123', 'custom_field': 'value'}
        >>> result = reorder_record(record, 'image')
        >>> 'custom_field' in result
        True
    
    Note:
        - 此函数不会丢失任何字段，所有输入字段都会出现在输出中
        - 字段映射会将旧字段名转换为新字段名，不会保留旧字段名
        - 如果输入记录中同时存在旧字段名和新字段名，新字段名的值优先
    """
    # 字段映射（旧名 -> 新名）
    field_mapping = {
        'timestamp': 'ts',
        'sender': 'speaker',
    }
    
    # 应用字段映射，将旧字段名转换为新字段名
    mapped_record = {}
    for key, value in record.items():
        new_key = field_mapping.get(key, key)
        # 如果新字段名已存在（即输入中同时有旧名和新名），保留新名的值
        if new_key not in mapped_record:
            mapped_record[new_key] = value
    
    # 获取模态特定字段列表
    specific_fields = MODALITY_SPECIFIC_FIELDS.get(modality, [])
    
    # 按顺序构建结果
    result = OrderedDict()
    
    # 1. 公共字段（按 COMMON_HEADER_FIELDS 顺序）
    for field in COMMON_HEADER_FIELDS:
        # 如果不包含 schema_version，跳过该字段
        if not include_schema_version and field == 'schema_version':
            continue
        # 只添加存在于 mapped_record 中的字段
        if field in mapped_record:
            result[field] = mapped_record[field]
    
    # 2. 模态特定字段（按定义顺序）
    for field in specific_fields:
        if field in mapped_record:
            result[field] = mapped_record[field]
    
    # 3. 其他未知字段（保持原顺序）
    # 计算已知字段集合
    known_fields = set(COMMON_HEADER_FIELDS) | set(specific_fields)
    for key, value in mapped_record.items():
        if key not in known_fields:
            result[key] = value
    
    return result


def build_common_header(
    raw_record: Optional[Dict[str, Any]] = None,
    **overrides
) -> Dict[str, Any]:
    """
    构建公共标识字段，缺失字段使用默认值。
    
    此函数用于构建 merged_final.jsonl 记录的公共标识字段部分。
    它会：
    1. 首先使用默认值初始化所有公共字段
    2. 如果提供了 raw_record，从中提取对应字段值
    3. 最后应用 overrides 参数覆盖任何字段
    
    Args:
        raw_record: P1_messages_raw.jsonl 中的原始记录，可选。
                   如果提供，将从中提取 COMMON_HEADER_FIELDS 中定义的字段。
        **overrides: 覆盖字段值。可以覆盖任何字段，包括：
                    - 公共字段（如 schema_version, msg_uid, ts 等）
                    - 任何其他需要添加的字段
    
    Returns:
        Dict[str, Any]: 包含所有公共标识字段的字典。
                       字段顺序不保证，如需排序请使用 reorder_record()。
    
    Examples:
        # 仅使用默认值
        >>> header = build_common_header()
        >>> header['schema_version']
        'merged_v2'
        >>> header['speaker']
        'UNKNOWN'
        
        # 从原始记录构建
        >>> raw = {'msg_uid': 'P1:123', 'ts': 1749279243, 'speaker': 'ME'}
        >>> header = build_common_header(raw_record=raw)
        >>> header['msg_uid']
        'P1:123'
        
        # 使用 overrides 覆盖
        >>> header = build_common_header(modality='image', media_path='image/test.jpg')
        >>> header['modality']
        'image'
        
        # 组合使用
        >>> raw = {'msg_uid': 'P1:123', 'ts': 1749279243}
        >>> header = build_common_header(raw_record=raw, modality='voice')
        >>> header['msg_uid']
        'P1:123'
        >>> header['modality']
        'voice'
    
    Note:
        - 默认值设计用于标识"未知"或"缺失"状态：
          - seq_in_html = -1 表示序号未知
          - ts = 0 表示时间戳未知
          - speaker = 'UNKNOWN' 表示发送者未知
        - overrides 优先级最高，可以覆盖 raw_record 中的值
    """
    # 定义所有公共字段的默认值
    defaults = {
        'schema_version': SCHEMA_VERSION,
        'seq_in_html': -1,      # -1 表示未知
        'msg_uid': '',
        'MsgSvrID': '',
        'token': '',
        'ts': 0,
        'time_local': '',
        'speaker': 'UNKNOWN',
        'type': 0,
        'sub_type': 0,
        'modality': '',
        'media_path': None,
    }
    
    # 从默认值开始
    result = defaults.copy()
    
    # 如果提供了原始记录，从中提取公共字段
    if raw_record:
        for field in COMMON_HEADER_FIELDS:
            if field in raw_record and raw_record[field] is not None:
                result[field] = raw_record[field]
    
    # 应用 overrides，覆盖任何字段
    result.update(overrides)
    
    return result


def migrate_legacy_record(
    record: Dict[str, Any],
    modality: str
) -> Dict[str, Any]:
    """
    将旧格式记录迁移到新格式（一次性迁移工具）。
    
    此函数用于将现有的旧格式 merged_final.jsonl 文件转换为新格式。
    
    使用场景：
    1. 首次部署时迁移现有 merged_final.jsonl 文件
    2. 处理意外的旧格式数据（防御性编程）
    
    正常流程中，merge_engine 直接生成新格式，不经过此函数。
    
    迁移逻辑：
    1. 检测是否已是新格式（schema_version == SCHEMA_VERSION）
    2. 应用字段映射（旧字段名 → 新字段名）
    3. 确保包含 schema_version
    4. 调用 reorder_record 重排字段顺序
    
    Args:
        record: 旧格式记录字典。可能的特征：
               - 无 schema_version 字段
               - schema_version != "merged_v2"
               - 使用旧字段名（timestamp, sender, file）
        modality: 模态类型，必须是 "image", "voice", "video", "sticker" 之一。
                 用于确定字段排序和特定的字段映射规则。
    
    Returns:
        Dict[str, Any]: 新格式记录，满足以下条件：
                       - schema_version = "merged_v2"
                       - 字段按标准顺序排列
                       - 使用新字段名（ts, speaker, media_path）
                       - 保留原记录的所有有效数据
    
    Examples:
        # 已是新格式，直接返回
        >>> record = {'schema_version': 'merged_v2', 'msg_uid': 'P1:123'}
        >>> result = migrate_legacy_record(record, 'image')
        >>> result == record
        True
        
        # 旧格式 image 记录迁移
        >>> record = {'timestamp': 1749279243, 'sender': 'ME', 'caption': '测试'}
        >>> result = migrate_legacy_record(record, 'image')
        >>> result['schema_version']
        'merged_v2'
        >>> 'ts' in result and 'timestamp' not in result
        True
        >>> 'speaker' in result and 'sender' not in result
        True
        
        # 旧格式 voice 记录迁移（file → media_path）
        >>> record = {'file': 'voice/test.mp3', 'punct_text': '你好'}
        >>> result = migrate_legacy_record(record, 'voice')
        >>> result['media_path']
        'voice/test.mp3'
        >>> 'file' not in result  # voice 模态下 file 被映射为 media_path
        True
        
        # 保留所有原始数据
        >>> record = {'timestamp': 1749279243, 'custom_field': 'value'}
        >>> result = migrate_legacy_record(record, 'image')
        >>> result['custom_field']
        'value'
    
    Note:
        - 如果记录已是新格式（schema_version == SCHEMA_VERSION），直接返回原记录
        - 字段映射规则：
          - timestamp → ts（所有模态）
          - sender → speaker（所有模态）
          - file → media_path（仅 voice 模态，因为 video 模态的 file 字段有不同含义）
        - 如果输入记录中同时存在旧字段名和新字段名，新字段名的值优先
        - 迁移后的记录会通过 reorder_record 重排字段顺序
    
    Validates: Requirements 7.2, 7.3
    """
    # 检测是否已是新格式
    if record.get('schema_version') == SCHEMA_VERSION:
        return record  # 已是新格式，直接返回
    
    # 字段映射（旧名 -> 新名）
    # 基础映射：所有模态通用
    field_mapping = {
        'timestamp': 'ts',
        'sender': 'speaker',
    }
    
    # voice 模态特殊映射：file → media_path
    # 注意：video 模态的 file 字段是视频文件名，不应映射为 media_path
    if modality == 'voice':
        field_mapping['file'] = 'media_path'
    
    # 应用字段映射
    migrated = {}
    for old_key, value in record.items():
        new_key = field_mapping.get(old_key, old_key)
        # 如果新字段名已存在（即输入中同时有旧名和新名），保留新名的值
        if new_key not in migrated:
            migrated[new_key] = value
    
    # 确保有 schema_version
    migrated['schema_version'] = SCHEMA_VERSION
    
    # 调用 reorder_record 重排字段顺序
    return reorder_record(migrated, modality)
