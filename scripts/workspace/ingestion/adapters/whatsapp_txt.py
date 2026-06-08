"""
whatsapp_txt.py
WhatsApp TXT 导出适配器

解析 WhatsApp 的文本导出格式，将消息转换为 Canonical Schema 格式。

- 正则解析 WhatsApp 行格式（支持多种本地化变体：US/EU/German 等）
- 多行消息续行处理（不匹配行格式的行视为前一条消息的续行）
- 媒体占位符识别（<Media omitted> 等）
- 文件扩展名 → modality 映射
- 时区感知的时间戳转换
- msg_uid 格式：WA:{行号}

Requirements: 6.1, 6.2, 6.3, 6.4
"""

import re
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional

import pytz

from scripts.workspace.ingestion.adapters.base import SourceAdapter
from scripts.workspace.ingestion.manifest import SourceManifest

# WhatsApp 行格式正则（支持多种本地化变体）
WHATSAPP_LINE_RE = re.compile(
    r'^(\d{1,2}/\d{1,2}/\d{2,4},?\s+\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM|am|pm)?)'
    r'\s*[-–]\s*'
    r'(.+?):\s*(.*)',
    re.DOTALL,
)

# 媒体占位符模式
MEDIA_OMITTED_RE = re.compile(
    r'<(?:Media|media|image|video|audio|document|sticker)\s*(?:omitted|省略)>',
    re.IGNORECASE,
)

# 文件扩展名 → modality 映射
IMAGE_EXTENSIONS = frozenset({'.jpg', '.jpeg', '.png', '.gif', '.webp'})
VOICE_EXTENSIONS = frozenset({'.opus', '.mp3', '.ogg', '.m4a'})
VIDEO_EXTENSIONS = frozenset({'.mp4', '.3gp', '.mov'})

# 常见 WhatsApp 时间格式
DATETIME_FORMATS = [
    "%m/%d/%y, %I:%M %p",      # US: 1/15/25, 10:30 AM
    "%m/%d/%Y, %I:%M %p",      # US long year: 1/15/2025, 10:30 AM
    "%d/%m/%y, %H:%M",         # EU: 15/01/25, 10:30
    "%d/%m/%Y, %H:%M",         # EU long year: 15/01/2025, 10:30
    "%m/%d/%y, %I:%M:%S %p",   # US with seconds
    "%d/%m/%y, %H:%M:%S",      # EU with seconds
    "%d.%m.%y, %H:%M",         # German: 15.01.25, 10:30
    "%d.%m.%Y, %H:%M",         # German long year
]


def ext_to_modality(ext: str) -> str:
    """文件扩展名 → modality"""
    ext = ext.lower()
    if ext in IMAGE_EXTENSIONS:
        return "image"
    if ext in VOICE_EXTENSIONS:
        return "voice"
    if ext in VIDEO_EXTENSIONS:
        return "video"
    return "link_or_file"


def parse_whatsapp_datetime(date_str: str, tz_name: str = "Asia/Shanghai") -> int:
    """解析 WhatsApp 时间戳为 Unix 时间戳

    支持多种本地化格式（US 12h、EU 24h、German 等），
    使用 manifest 中的 timezone 配置进行时区转换。

    Args:
        date_str: WhatsApp 导出中的日期时间字符串
        tz_name: 时区标识（如 Asia/Shanghai、America/New_York）

    Returns:
        Unix 时间戳（秒），解析失败返回 0
    """
    date_str = date_str.strip().replace('\u202f', ' ').replace('\xa0', ' ')
    tz = pytz.timezone(tz_name)
    for fmt in DATETIME_FORMATS:
        try:
            dt = datetime.strptime(date_str, fmt)
            dt = tz.localize(dt)
            return int(dt.timestamp())
        except ValueError:
            continue
    return 0


def parse_whatsapp_line(line: str):
    """解析单行 WhatsApp 消息，返回 (date_str, sender, text) 或 None"""
    m = WHATSAPP_LINE_RE.match(line)
    if m:
        return m.group(1), m.group(2), m.group(3)
    return None


class WhatsAppAdapter(SourceAdapter):
    """WhatsApp TXT 导出适配器"""

    def supported_source_type(self) -> str:
        return "whatsapp_txt"

    def parse(self, input_path: Path, manifest: SourceManifest) -> Iterator[dict]:
        tz_name = manifest.timezone if manifest else "Asia/Shanghai"
        participant_map = manifest.participant_map if manifest else {}

        with open(input_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        # 第一遍：将行分组为消息（处理多行续行）
        messages = []  # list of (line_no, date_str, sender, text)
        for i, line in enumerate(lines):
            parsed = parse_whatsapp_line(line.rstrip('\n'))
            if parsed:
                messages.append((i + 1, parsed[0], parsed[1], parsed[2]))
            elif messages:
                # 续行：追加到前一条消息
                prev = messages[-1]
                messages[-1] = (prev[0], prev[1], prev[2],
                                prev[3] + "\n" + line.rstrip('\n'))

        # 第二遍：转换为标准记录
        for line_no, date_str, sender, text in messages:
            ts = parse_whatsapp_datetime(date_str, tz_name)

            # 映射 speaker
            if sender in participant_map:
                speaker = participant_map[sender]
            else:
                speaker = f"OTHER:{sender}"

            # 判断 modality
            modality = "text"
            media_path = None
            if MEDIA_OMITTED_RE.search(text):
                modality = "image"  # 媒体占位符默认为 image

            # 检查附件文件引用（WhatsApp 格式：filename.ext (file attached)）
            attached_match = re.search(
                r'([\w\-]+\.\w+)\s*\(file attached\)', text, re.IGNORECASE
            )
            if attached_match:
                filename = attached_match.group(1)
                ext = Path(filename).suffix
                modality = ext_to_modality(ext)
                media_path = filename

            record = {
                "msg_uid": f"WA:{line_no}",
                "ts": ts,
                "speaker": speaker,
                "type": 1,
                "modality": modality,
                "text_raw": text,
                "media_path": media_path,
            }
            yield record

    def validate_input(self, input_path: Path) -> list[str]:
        errors = super().validate_input(input_path)
        if errors:
            return errors
        if input_path.is_file() and input_path.suffix.lower() != ".txt":
            errors.append(f"期望 TXT 文件，实际: {input_path}")
        return errors

    def detect_media_files(self, input_path: Path) -> list[Path]:
        """检测 WhatsApp 导出目录中的媒体文件"""
        base_dir = input_path.parent if input_path.is_file() else input_path
        media_files = []
        all_exts = [*IMAGE_EXTENSIONS, *VOICE_EXTENSIONS, *VIDEO_EXTENSIONS,
                    '.pdf', '.doc', '.docx']
        for ext in all_exts:
            media_files.extend(base_dir.glob(f"*{ext}"))
        return [f for f in media_files if f.is_file() and f.suffix.lower() != '.txt']

    def describe(self) -> dict:
        return {
            "source_type": "whatsapp_txt",
            "description": "WhatsApp TXT 导出适配器",
            "expected_files": ["*.txt (WhatsApp 导出文件)", "附件文件（与 .txt 同目录）"],
            "field_mapping_example": {},
        }
