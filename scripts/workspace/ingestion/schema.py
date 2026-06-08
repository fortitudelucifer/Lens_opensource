"""
schema.py
标准消息 Schema 定义、验证和序列化

定义 Canonical_Schema：
- REQUIRED_FIELDS / VALID_MODALITIES / VALID_SPEAKER_PREFIXES 常量
- CanonicalMessage dataclass
- validate_message() 验证函数
- to_jsonl_line() / from_jsonl_line() 序列化函数

运行方式：
    python -m pytest tests/workspace/ingestion/test_schema.py -v
"""

from dataclasses import dataclass, field, asdict
from typing import Optional
import json


# ── 常量 ──────────────────────────────────────────────────────────────

VALID_MODALITIES = frozenset({
    "text", "image", "voice", "video", "sticker",
    "link_or_file", "location", "contact", "system",
})

VALID_SPEAKER_PREFIXES = ("ME", "OTHER")

REQUIRED_FIELDS = ("msg_uid", "ts", "speaker", "type", "modality", "text_raw")


# ── 数据类 ────────────────────────────────────────────────────────────

@dataclass
class CanonicalMessage:
    """标准消息记录"""

    # 必填字段
    msg_uid: str                    # {source_prefix}:{unique_id}
    ts: int                         # Unix 时间戳（秒）
    speaker: str                    # ME | OTHER | OTHER:{name}
    type: int                       # 消息类型码
    modality: str                   # text/image/voice/video/...
    text_raw: str                   # 原始文本内容

    # 可选字段
    seq_in_html: int = -1
    MsgSvrID: str = ""
    token: str = ""
    time_local: str = ""
    sub_type: int = 0
    media_path: Optional[str] = None
    voice_length: Optional[int] = None
    voice_to_text: Optional[str] = None
    link_url: Optional[str] = None
    link_title: Optional[str] = None
    miniprogram_appid: Optional[str] = None
    quote_svrid: Optional[str] = None
    quote_type: Optional[int] = None
    quote_text: Optional[str] = None
    file_name: Optional[str] = None
    file_size: Optional[str] = None
    location_x: Optional[float] = None
    location_y: Optional[float] = None
    location_label: Optional[str] = None
    contact_nickname: Optional[str] = None
    contact_username: Optional[str] = None


# ── 验证 ──────────────────────────────────────────────────────────────

def validate_message(record: dict) -> list[str]:
    """验证消息记录，返回错误列表（空列表=通过）"""
    errors: list[str] = []

    # 必填字段检查
    for f in REQUIRED_FIELDS:
        if f not in record or record[f] is None:
            errors.append(f"缺少必填字段: {f}")

    # ts 类型与范围检查
    if "ts" in record and record["ts"] is not None:
        if not isinstance(record["ts"], int) or record["ts"] <= 0:
            errors.append(f"ts 必须为正整数，实际值: {record.get('ts')}")

    # modality 取值检查
    if "modality" in record and record["modality"] is not None:
        if record["modality"] not in VALID_MODALITIES:
            errors.append(f"modality 值无效: {record.get('modality')}")

    # speaker 格式检查
    if "speaker" in record and record["speaker"] is not None:
        s = record["speaker"]
        if not any(s == p or s.startswith(p + ":") for p in VALID_SPEAKER_PREFIXES):
            errors.append(f"speaker 格式无效: {s}")

    return errors


# ── 序列化 ────────────────────────────────────────────────────────────

def to_jsonl_line(record: dict) -> str:
    """序列化为单行 JSON（ensure_ascii=False 保留中文/Unicode）"""
    return json.dumps(record, ensure_ascii=False)


def from_jsonl_line(line: str) -> dict:
    """反序列化单行 JSON"""
    return json.loads(line.strip())
