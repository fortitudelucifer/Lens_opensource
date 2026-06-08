"""
test_schema.py
Canonical Schema 的单元测试和属性测试

属性测试：
- Property 1: JSONL 序列化往返一致性
  Validates: Requirements 12.3
- Property 2: Schema 验证——合法记录通过
  Validates: Requirements 1.4, 1.5, 1.6
- Property 3: Schema 验证——非法记录被拒绝
  Validates: Requirements 1.4, 1.5, 1.6, 11.2, 11.3, 11.4

运行方式：
    python -m pytest tests/workspace/ingestion/test_schema.py -v
"""

import json
import sys
from dataclasses import asdict
from pathlib import Path

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

# Setup paths
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.workspace.ingestion.schema import (
    REQUIRED_FIELDS,
    VALID_MODALITIES,
    VALID_SPEAKER_PREFIXES,
    CanonicalMessage,
    validate_message,
    to_jsonl_line,
    from_jsonl_line,
)


# ── 测试策略（Hypothesis Strategies）──────────────────────────────────

# 合法的 source_prefix
source_prefixes = st.sampled_from(["P1", "TG", "WA", "GEN", "QQ", "WXWORK"])

# 合法的 unique_id
unique_ids = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_-"),
    min_size=1,
    max_size=30,
)

# 合法的 msg_uid
valid_msg_uids = st.builds(
    lambda prefix, uid: f"{prefix}:{uid}",
    source_prefixes,
    unique_ids,
)

# 合法的 ts（正整数，合理范围）
valid_ts = st.integers(min_value=1, max_value=2_000_000_000)

# 合法的 speaker
valid_speakers = st.one_of(
    st.just("ME"),
    st.just("OTHER"),
    st.builds(
        lambda name: f"OTHER:{name}",
        st.text(min_size=1, max_size=20).filter(lambda s: s.strip() != ""),
    ),
)

# 合法的 modality
valid_modalities = st.sampled_from(sorted(VALID_MODALITIES))

# 合法的 type
valid_types = st.integers(min_value=0, max_value=100000)

# 合法的 text_raw（包含中文、Unicode 表情、特殊字符）
valid_text_raw = st.text(min_size=0, max_size=200)

# 合法的消息记录字典
valid_record_strategy = st.fixed_dictionaries({
    "msg_uid": valid_msg_uids,
    "ts": valid_ts,
    "speaker": valid_speakers,
    "type": valid_types,
    "modality": valid_modalities,
    "text_raw": valid_text_raw,
})

# 带可选字段的合法记录
optional_fields_strategy = st.fixed_dictionaries({}, optional={
    "media_path": st.one_of(st.none(), st.text(min_size=1, max_size=50)),
    "voice_length": st.one_of(st.none(), st.integers(min_value=0, max_value=600000)),
    "voice_to_text": st.one_of(st.none(), st.text(max_size=100)),
    "link_url": st.one_of(st.none(), st.text(min_size=1, max_size=100)),
    "link_title": st.one_of(st.none(), st.text(max_size=50)),
    "sub_type": st.integers(min_value=0, max_value=1000),
    "seq_in_html": st.integers(min_value=-1, max_value=100000),
})

valid_record_with_optional = st.builds(
    lambda base, opt: {**base, **opt},
    valid_record_strategy,
    optional_fields_strategy,
)


# ── 单元测试 ─────────────────────────────────────────────────────────

class TestConstants:
    """常量定义测试"""

    def test_required_fields_content(self):
        """必填字段应包含 msg_uid, ts, speaker, type, modality, text_raw"""
        expected = {"msg_uid", "ts", "speaker", "type", "modality", "text_raw"}
        assert set(REQUIRED_FIELDS) == expected

    def test_valid_modalities_content(self):
        """modality 应包含 9 种取值"""
        expected = {
            "text", "image", "voice", "video", "sticker",
            "link_or_file", "location", "contact", "system",
        }
        assert VALID_MODALITIES == expected

    def test_valid_speaker_prefixes(self):
        """speaker 前缀应为 ME 和 OTHER"""
        assert set(VALID_SPEAKER_PREFIXES) == {"ME", "OTHER"}


class TestCanonicalMessage:
    """CanonicalMessage dataclass 测试"""

    def test_create_with_required_fields(self):
        """仅必填字段即可创建实例"""
        msg = CanonicalMessage(
            msg_uid="P1:123",
            ts=1700000000,
            speaker="ME",
            type=1,
            modality="text",
            text_raw="你好",
        )
        assert msg.msg_uid == "P1:123"
        assert msg.ts == 1700000000
        assert msg.media_path is None

    def test_optional_fields_defaults(self):
        """可选字段应有正确的默认值"""
        msg = CanonicalMessage(
            msg_uid="TG:456",
            ts=1700000000,
            speaker="OTHER:张三",
            type=1,
            modality="text",
            text_raw="",
        )
        assert msg.seq_in_html == -1
        assert msg.MsgSvrID == ""
        assert msg.sub_type == 0
        assert msg.voice_length is None
        assert msg.location_x is None

    def test_asdict_roundtrip(self):
        """dataclass 可以正确转为字典"""
        msg = CanonicalMessage(
            msg_uid="P1:789",
            ts=1700000000,
            speaker="ME",
            type=1,
            modality="image",
            text_raw="",
            media_path="image/2025-06/photo.jpg",
        )
        d = asdict(msg)
        assert d["msg_uid"] == "P1:789"
        assert d["media_path"] == "image/2025-06/photo.jpg"


class TestValidateMessage:
    """validate_message 单元测试"""

    def test_valid_record_passes(self):
        """合法记录应返回空错误列表"""
        record = {
            "msg_uid": "P1:123",
            "ts": 1700000000,
            "speaker": "ME",
            "type": 1,
            "modality": "text",
            "text_raw": "你好",
        }
        assert validate_message(record) == []

    def test_missing_required_field(self):
        """缺少必填字段应报错"""
        record = {"ts": 1700000000, "speaker": "ME", "type": 1, "modality": "text", "text_raw": ""}
        errors = validate_message(record)
        assert any("msg_uid" in e for e in errors)

    def test_none_required_field(self):
        """必填字段为 None 应报错"""
        record = {
            "msg_uid": None,
            "ts": 1700000000,
            "speaker": "ME",
            "type": 1,
            "modality": "text",
            "text_raw": "",
        }
        errors = validate_message(record)
        assert any("msg_uid" in e for e in errors)

    def test_ts_not_positive_integer(self):
        """ts 为非正整数应报错"""
        record = {
            "msg_uid": "P1:1",
            "ts": -1,
            "speaker": "ME",
            "type": 1,
            "modality": "text",
            "text_raw": "",
        }
        errors = validate_message(record)
        assert any("ts" in e for e in errors)

    def test_ts_zero(self):
        """ts 为 0 应报错"""
        record = {
            "msg_uid": "P1:1",
            "ts": 0,
            "speaker": "ME",
            "type": 1,
            "modality": "text",
            "text_raw": "",
        }
        errors = validate_message(record)
        assert any("ts" in e for e in errors)

    def test_ts_float_rejected(self):
        """ts 为浮点数应报错"""
        record = {
            "msg_uid": "P1:1",
            "ts": 1700000000.5,
            "speaker": "ME",
            "type": 1,
            "modality": "text",
            "text_raw": "",
        }
        errors = validate_message(record)
        assert any("ts" in e for e in errors)

    def test_invalid_modality(self):
        """无效 modality 应报错"""
        record = {
            "msg_uid": "P1:1",
            "ts": 1700000000,
            "speaker": "ME",
            "type": 1,
            "modality": "unknown_type",
            "text_raw": "",
        }
        errors = validate_message(record)
        assert any("modality" in e for e in errors)

    def test_invalid_speaker_format(self):
        """无效 speaker 格式应报错"""
        record = {
            "msg_uid": "P1:1",
            "ts": 1700000000,
            "speaker": "SOMEONE",
            "type": 1,
            "modality": "text",
            "text_raw": "",
        }
        errors = validate_message(record)
        assert any("speaker" in e for e in errors)

    def test_speaker_other_with_name(self):
        """OTHER:{name} 格式应通过"""
        record = {
            "msg_uid": "P1:1",
            "ts": 1700000000,
            "speaker": "OTHER:张三",
            "type": 1,
            "modality": "text",
            "text_raw": "",
        }
        assert validate_message(record) == []

    def test_multiple_errors(self):
        """多个错误应全部报告"""
        record = {"ts": -1, "modality": "bad"}
        errors = validate_message(record)
        # 至少应有：缺少 msg_uid, speaker, type, text_raw + ts 无效 + modality 无效
        assert len(errors) >= 4


class TestSerialization:
    """序列化/反序列化单元测试"""

    def test_to_jsonl_line_basic(self):
        """基本序列化"""
        record = {"msg_uid": "P1:1", "text_raw": "你好"}
        line = to_jsonl_line(record)
        assert '"msg_uid"' in line
        assert "你好" in line  # ensure_ascii=False

    def test_from_jsonl_line_basic(self):
        """基本反序列化"""
        line = '{"msg_uid": "P1:1", "text_raw": "你好"}\n'
        result = from_jsonl_line(line)
        assert result["msg_uid"] == "P1:1"
        assert result["text_raw"] == "你好"

    def test_roundtrip_chinese(self):
        """中文往返一致性"""
        record = {"msg_uid": "P1:1", "text_raw": "你好世界🌍"}
        assert from_jsonl_line(to_jsonl_line(record)) == record

    def test_ensure_ascii_false(self):
        """序列化不应转义中文字符"""
        record = {"text_raw": "测试"}
        line = to_jsonl_line(record)
        assert "\\u" not in line
        assert "测试" in line


# ── 属性测试 ─────────────────────────────────────────────────────────

class TestProperty1RoundTrip:
    """
    Property 1: JSONL 序列化往返一致性
    Feature: universal-ingestion, Property 1: JSONL 序列化往返一致性

    **Validates: Requirements 12.3**
    """

    @given(record=valid_record_with_optional)
    @settings(max_examples=200)
    def test_roundtrip_consistency(self, record: dict):
        """from_jsonl_line(to_jsonl_line(record)) 应与原始记录等价"""
        result = from_jsonl_line(to_jsonl_line(record))
        assert result == record

    @given(record=valid_record_strategy)
    @settings(max_examples=100)
    def test_roundtrip_required_only(self, record: dict):
        """仅必填字段的记录也应保持往返一致性"""
        result = from_jsonl_line(to_jsonl_line(record))
        assert result == record

    @given(text=st.text(min_size=0, max_size=200))
    @settings(max_examples=100)
    def test_unicode_preserved(self, text: str):
        """任意 Unicode 文本应在序列化后保持不变"""
        record = {"text_raw": text}
        result = from_jsonl_line(to_jsonl_line(record))
        assert result["text_raw"] == text


class TestProperty2ValidRecordPasses:
    """
    Property 2: Schema 验证——合法记录通过
    Feature: universal-ingestion, Property 2: Schema 验证——合法记录通过

    **Validates: Requirements 1.4, 1.5, 1.6**
    """

    @given(record=valid_record_strategy)
    @settings(max_examples=200)
    def test_valid_record_no_errors(self, record: dict):
        """包含所有必填字段且值类型正确的记录应通过验证"""
        errors = validate_message(record)
        assert errors == [], f"合法记录验证失败: {errors}, record={record}"

    @given(record=valid_record_with_optional)
    @settings(max_examples=100)
    def test_valid_record_with_optional_no_errors(self, record: dict):
        """带可选字段的合法记录也应通过验证"""
        errors = validate_message(record)
        assert errors == [], f"合法记录验证失败: {errors}"


class TestProperty3InvalidRecordRejected:
    """
    Property 3: Schema 验证——非法记录被拒绝
    Feature: universal-ingestion, Property 3: Schema 验证——非法记录被拒绝

    **Validates: Requirements 1.4, 1.5, 1.6, 11.2, 11.3, 11.4**
    """

    @given(
        record=valid_record_strategy,
        field_to_remove=st.sampled_from(list(REQUIRED_FIELDS)),
    )
    @settings(max_examples=200)
    def test_missing_required_field_rejected(self, record: dict, field_to_remove: str):
        """缺少任一必填字段的记录应被拒绝"""
        record = dict(record)  # 复制
        del record[field_to_remove]
        errors = validate_message(record)
        assert len(errors) > 0, f"缺少 {field_to_remove} 但未报错"

    @given(
        record=valid_record_strategy,
        bad_ts=st.one_of(
            st.integers(max_value=0),
            st.floats(allow_nan=False, allow_infinity=False),
        ),
    )
    @settings(max_examples=200)
    def test_invalid_ts_rejected(self, record: dict, bad_ts):
        """ts 为非正整数应被拒绝"""
        # 跳过 float 值恰好是正整数的情况（如 1.0 在 Python 中 isinstance(1.0, int) 为 False）
        record = dict(record)
        record["ts"] = bad_ts
        errors = validate_message(record)
        assert any("ts" in e for e in errors), f"ts={bad_ts} 未被拒绝"

    @given(
        record=valid_record_strategy,
        bad_modality=st.text(min_size=1, max_size=20).filter(
            lambda s: s not in VALID_MODALITIES
        ),
    )
    @settings(max_examples=200)
    def test_invalid_modality_rejected(self, record: dict, bad_modality: str):
        """无效 modality 应被拒绝"""
        record = dict(record)
        record["modality"] = bad_modality
        errors = validate_message(record)
        assert any("modality" in e for e in errors), f"modality={bad_modality} 未被拒绝"

    @given(
        record=valid_record_strategy,
        bad_speaker=st.text(min_size=1, max_size=20).filter(
            lambda s: not any(s == p or s.startswith(p + ":") for p in VALID_SPEAKER_PREFIXES)
        ),
    )
    @settings(max_examples=200)
    def test_invalid_speaker_rejected(self, record: dict, bad_speaker: str):
        """无效 speaker 格式应被拒绝"""
        record = dict(record)
        record["speaker"] = bad_speaker
        errors = validate_message(record)
        assert any("speaker" in e for e in errors), f"speaker={bad_speaker} 未被拒绝"
