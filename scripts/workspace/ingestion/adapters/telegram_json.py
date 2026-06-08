"""
telegram_json.py
Telegram Desktop JSON 导出适配器

解析 Telegram Desktop 导出的 result.json 文件，将消息转换为 Canonical Schema 格式。

- 解析 messages 数组，过滤 type="message" 的消息
- media_type 映射：sticker/animation → sticker, voice_message → voice, video_message/video_file → video
- 无 media_type 且有 photo → image，有 file → link_or_file，无媒体 → text
- participant_map 映射 from → speaker
- 富文本数组展平为纯文本
- msg_uid 格式：TG:{id}

Requirements: 5.1, 5.2, 5.3, 5.4
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Iterator

from scripts.workspace.ingestion.adapters.base import SourceAdapter
from scripts.workspace.ingestion.manifest import SourceManifest


# media_type → modality 映射
TELEGRAM_MEDIA_TYPE_MAP = {
    "sticker": "sticker",
    "animation": "sticker",       # GIF 动图
    "voice_message": "voice",
    "video_message": "video",
    "video_file": "video",
}


def flatten_text(text_field) -> str:
    """将 Telegram 的 text 字段展平为纯文本。

    text 可能是字符串或富文本数组（list of str/dict）。
    """
    if isinstance(text_field, str):
        return text_field
    if isinstance(text_field, list):
        parts = []
        for item in text_field:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(item.get("text", ""))
        return "".join(parts)
    return str(text_field) if text_field is not None else ""


def get_telegram_modality(msg: dict) -> str:
    """根据 Telegram 消息字段推断 modality"""
    media_type = msg.get("media_type")
    if media_type and media_type in TELEGRAM_MEDIA_TYPE_MAP:
        return TELEGRAM_MEDIA_TYPE_MAP[media_type]
    if msg.get("photo"):
        return "image"
    if msg.get("file"):
        return "link_or_file"
    return "text"


def get_telegram_media_path(msg: dict) -> str | None:
    """提取媒体文件路径"""
    if msg.get("photo"):
        return msg["photo"]
    if msg.get("file"):
        return msg["file"]
    return None


def map_speaker(from_name: str | None, participant_map: dict[str, str]) -> str:
    """将 from 字段映射为 speaker

    如果 from_name 在 participant_map 中有映射，返回映射值；
    否则返回 OTHER:{from_name}。
    """
    if not from_name:
        return "OTHER"
    if from_name in participant_map:
        return participant_map[from_name]
    return f"OTHER:{from_name}"


class TelegramAdapter(SourceAdapter):
    """Telegram Desktop JSON 导出适配器"""

    def supported_source_type(self) -> str:
        return "telegram_json"

    def parse(self, input_path: Path, manifest: SourceManifest) -> Iterator[dict]:
        with open(input_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        messages = data.get("messages", [])
        participant_map = manifest.participant_map if manifest else {}

        for msg in messages:
            if msg.get("type") != "message":
                continue

            msg_id = msg.get("id", 0)
            date_str = msg.get("date", "")
            from_name = msg.get("from", "")

            # 解析时间戳
            ts = 0
            if date_str:
                try:
                    dt = datetime.fromisoformat(date_str)
                    ts = int(dt.timestamp())
                except (ValueError, OSError):
                    ts = 0

            text_raw = flatten_text(msg.get("text", ""))
            modality = get_telegram_modality(msg)
            media_path = get_telegram_media_path(msg)
            speaker = map_speaker(from_name, participant_map)

            record = {
                "msg_uid": f"TG:{msg_id}",
                "ts": ts,
                "speaker": speaker,
                "type": 1,
                "modality": modality,
                "text_raw": text_raw,
                "media_path": media_path,
            }
            yield record

    def validate_input(self, input_path: Path) -> list[str]:
        errors = super().validate_input(input_path)
        if errors:
            return errors
        if input_path.is_file() and input_path.suffix.lower() != ".json":
            errors.append(f"期望 JSON 文件，实际: {input_path}")
        return errors

    def detect_media_files(self, input_path: Path) -> list[Path]:
        base_dir = input_path.parent if input_path.is_file() else input_path
        media_files = []
        for pattern in ["photos/**/*", "stickers/**/*", "voice_messages/**/*",
                        "video_files/**/*", "files/**/*", "round_video_messages/**/*"]:
            media_files.extend(base_dir.glob(pattern))
        return [f for f in media_files if f.is_file()]

    def describe(self) -> dict:
        return {
            "source_type": "telegram_json",
            "description": "Telegram Desktop JSON 导出适配器",
            "expected_files": ["result.json (Telegram Desktop 导出文件)"],
            "field_mapping_example": {},
        }
