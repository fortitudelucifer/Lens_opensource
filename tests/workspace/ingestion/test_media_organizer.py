"""
test_media_organizer.py
MediaOrganizer 单元测试

运行方式：
    conda run -n wechatDHA python -m pytest tests/workspace/ingestion/test_media_organizer.py -x -v
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import pytest

from scripts.workspace.ingestion.media_organizer import (
    MediaOrganizer,
    copy_with_dedup,
    get_target_dir,
)


# ── get_target_dir 测试 ──────────────────────────────────────────────


class TestGetTargetDir:
    """_get_target_dir 路由逻辑"""

    def test_image_returns_dated_subdir(self, tmp_path: Path):
        ts = int(datetime(2025, 6, 15).timestamp())
        result = get_target_dir("image", ts, tmp_path)
        assert result == tmp_path / "image" / "2025-06"

    def test_video_returns_dated_subdir(self, tmp_path: Path):
        ts = int(datetime(2024, 1, 1).timestamp())
        result = get_target_dir("video", ts, tmp_path)
        assert result == tmp_path / "video" / "2024-01"

    def test_voice_returns_flat_dir(self, tmp_path: Path):
        result = get_target_dir("voice", 1000000000, tmp_path)
        assert result == tmp_path / "voice"

    def test_sticker_returns_flat_dir(self, tmp_path: Path):
        result = get_target_dir("sticker", 1000000000, tmp_path)
        assert result == tmp_path / "sticker"

    def test_unknown_modality_returns_file_dir(self, tmp_path: Path):
        result = get_target_dir("link_or_file", 1000000000, tmp_path)
        assert result == tmp_path / "file"

    def test_text_modality_returns_file_dir(self, tmp_path: Path):
        result = get_target_dir("text", 1000000000, tmp_path)
        assert result == tmp_path / "file"

    def test_location_modality_returns_file_dir(self, tmp_path: Path):
        result = get_target_dir("location", 1000000000, tmp_path)
        assert result == tmp_path / "file"


# ── copy_with_dedup 测试 ─────────────────────────────────────────────


class TestCopyWithDedup:
    """_copy_with_dedup 去重复制逻辑"""

    def test_copy_new_file(self, tmp_path: Path):
        src = tmp_path / "src" / "photo.jpg"
        src.parent.mkdir()
        src.write_bytes(b"image data")

        dst = tmp_path / "dst" / "photo.jpg"
        result = copy_with_dedup(src, dst)

        assert result == dst
        assert dst.read_bytes() == b"image data"

    def test_skip_same_content(self, tmp_path: Path):
        src = tmp_path / "src" / "photo.jpg"
        src.parent.mkdir()
        src.write_bytes(b"same content")

        dst = tmp_path / "dst" / "photo.jpg"
        dst.parent.mkdir()
        dst.write_bytes(b"same content")

        result = copy_with_dedup(src, dst)
        assert result == dst
        # 只有一个文件，没有新文件产生
        assert len(list(dst.parent.iterdir())) == 1

    def test_dedup_different_content(self, tmp_path: Path):
        src = tmp_path / "src" / "photo.jpg"
        src.parent.mkdir()
        src.write_bytes(b"new content")

        dst = tmp_path / "dst" / "photo.jpg"
        dst.parent.mkdir()
        dst.write_bytes(b"old content")

        result = copy_with_dedup(src, dst)

        # 应该生成带哈希后缀的新文件
        assert result != dst
        assert result.parent == dst.parent
        assert result.suffix == ".jpg"
        assert "_" in result.stem
        assert result.read_bytes() == b"new content"
        # 原文件不变
        assert dst.read_bytes() == b"old content"

    def test_creates_parent_dirs(self, tmp_path: Path):
        src = tmp_path / "src" / "file.txt"
        src.parent.mkdir()
        src.write_text("hello")

        dst = tmp_path / "a" / "b" / "c" / "file.txt"
        result = copy_with_dedup(src, dst)
        assert result == dst
        assert dst.read_text() == "hello"


# ── MediaOrganizer.organize 测试 ─────────────────────────────────────


class TestOrganize:
    """organize() 主方法"""

    def _make_media(self, base: Path, rel_path: str, content: bytes = b"data") -> None:
        """在 base 下创建媒体文件"""
        p = base / rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)

    def test_image_organized_to_dated_dir(self, tmp_path: Path):
        media_base = tmp_path / "input"
        raw_dir = tmp_path / "raw"
        self._make_media(media_base, "photo.jpg")

        ts = int(datetime(2025, 3, 20).timestamp())
        records = [
            {"msg_uid": "T:1", "ts": ts, "modality": "image", "media_path": "photo.jpg", "text_raw": ""},
        ]

        organizer = MediaOrganizer()
        result = organizer.organize(records, media_base, raw_dir)

        assert result[0]["media_path"] == os.path.join("image", "2025-03", "photo.jpg")
        assert (raw_dir / "image" / "2025-03" / "photo.jpg").exists()

    def test_voice_organized_to_flat_dir(self, tmp_path: Path):
        media_base = tmp_path / "input"
        raw_dir = tmp_path / "raw"
        self._make_media(media_base, "audio.opus")

        records = [
            {"msg_uid": "T:2", "ts": 1700000000, "modality": "voice", "media_path": "audio.opus", "text_raw": ""},
        ]

        organizer = MediaOrganizer()
        result = organizer.organize(records, media_base, raw_dir)

        assert result[0]["media_path"] == os.path.join("voice", "audio.opus")

    def test_sticker_organized_to_flat_dir(self, tmp_path: Path):
        media_base = tmp_path / "input"
        raw_dir = tmp_path / "raw"
        self._make_media(media_base, "sticker.gif")

        records = [
            {"msg_uid": "T:3", "ts": 1700000000, "modality": "sticker", "media_path": "sticker.gif", "text_raw": ""},
        ]

        organizer = MediaOrganizer()
        result = organizer.organize(records, media_base, raw_dir)

        assert result[0]["media_path"] == os.path.join("sticker", "sticker.gif")

    def test_video_organized_to_dated_dir(self, tmp_path: Path):
        media_base = tmp_path / "input"
        raw_dir = tmp_path / "raw"
        self._make_media(media_base, "clip.mp4")

        ts = int(datetime(2024, 12, 5).timestamp())
        records = [
            {"msg_uid": "T:4", "ts": ts, "modality": "video", "media_path": "clip.mp4", "text_raw": ""},
        ]

        organizer = MediaOrganizer()
        result = organizer.organize(records, media_base, raw_dir)

        assert result[0]["media_path"] == os.path.join("video", "2024-12", "clip.mp4")

    def test_unknown_modality_goes_to_file(self, tmp_path: Path):
        media_base = tmp_path / "input"
        raw_dir = tmp_path / "raw"
        self._make_media(media_base, "doc.pdf")

        records = [
            {"msg_uid": "T:5", "ts": 1700000000, "modality": "link_or_file", "media_path": "doc.pdf", "text_raw": ""},
        ]

        organizer = MediaOrganizer()
        result = organizer.organize(records, media_base, raw_dir)

        assert result[0]["media_path"] == os.path.join("file", "doc.pdf")

    def test_none_media_path_skipped(self, tmp_path: Path):
        media_base = tmp_path / "input"
        raw_dir = tmp_path / "raw"

        records = [
            {"msg_uid": "T:6", "ts": 1700000000, "modality": "text", "media_path": None, "text_raw": "hello"},
        ]

        organizer = MediaOrganizer()
        result = organizer.organize(records, media_base, raw_dir)

        assert result[0]["media_path"] is None

    def test_missing_source_file_sets_none(self, tmp_path: Path):
        media_base = tmp_path / "input"
        media_base.mkdir()
        raw_dir = tmp_path / "raw"

        records = [
            {"msg_uid": "T:7", "ts": 1700000000, "modality": "image", "media_path": "missing.jpg", "text_raw": ""},
        ]

        organizer = MediaOrganizer()
        result = organizer.organize(records, media_base, raw_dir)

        assert result[0]["media_path"] is None

    def test_dedup_same_content_skips(self, tmp_path: Path):
        media_base = tmp_path / "input"
        raw_dir = tmp_path / "raw"
        content = b"same image data"
        self._make_media(media_base, "photo.jpg", content)

        # 预先放一个同名同内容文件
        target = raw_dir / "voice" / "photo.jpg"
        target.parent.mkdir(parents=True)
        target.write_bytes(content)

        records = [
            {"msg_uid": "T:8", "ts": 1700000000, "modality": "voice", "media_path": "photo.jpg", "text_raw": ""},
        ]

        organizer = MediaOrganizer()
        result = organizer.organize(records, media_base, raw_dir)

        assert result[0]["media_path"] == os.path.join("voice", "photo.jpg")
        # 目录下仍然只有一个文件
        assert len(list((raw_dir / "voice").iterdir())) == 1

    def test_dedup_different_content_adds_hash(self, tmp_path: Path):
        media_base = tmp_path / "input"
        raw_dir = tmp_path / "raw"
        self._make_media(media_base, "photo.jpg", b"new version")

        # 预先放一个同名但不同内容的文件
        target = raw_dir / "voice" / "photo.jpg"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"old version")

        records = [
            {"msg_uid": "T:9", "ts": 1700000000, "modality": "voice", "media_path": "photo.jpg", "text_raw": ""},
        ]

        organizer = MediaOrganizer()
        result = organizer.organize(records, media_base, raw_dir)

        new_path = result[0]["media_path"]
        assert new_path != os.path.join("voice", "photo.jpg")
        assert new_path.startswith("voice")
        assert new_path.endswith(".jpg")
        # 目录下有两个文件
        assert len(list((raw_dir / "voice").iterdir())) == 2

    def test_records_without_media_path_key_untouched(self, tmp_path: Path):
        media_base = tmp_path / "input"
        raw_dir = tmp_path / "raw"

        records = [
            {"msg_uid": "T:10", "ts": 1700000000, "modality": "text", "text_raw": "no media"},
        ]

        organizer = MediaOrganizer()
        result = organizer.organize(records, media_base, raw_dir)

        assert "media_path" not in result[0] or result[0].get("media_path") is None

    def test_multiple_records_mixed(self, tmp_path: Path):
        media_base = tmp_path / "input"
        raw_dir = tmp_path / "raw"
        self._make_media(media_base, "a.jpg", b"img")
        self._make_media(media_base, "b.opus", b"audio")

        ts = int(datetime(2025, 1, 15).timestamp())
        records = [
            {"msg_uid": "T:11", "ts": ts, "modality": "image", "media_path": "a.jpg", "text_raw": ""},
            {"msg_uid": "T:12", "ts": 1700000000, "modality": "text", "media_path": None, "text_raw": "hi"},
            {"msg_uid": "T:13", "ts": 1700000000, "modality": "voice", "media_path": "b.opus", "text_raw": ""},
        ]

        organizer = MediaOrganizer()
        result = organizer.organize(records, media_base, raw_dir)

        assert result[0]["media_path"] == os.path.join("image", "2025-01", "a.jpg")
        assert result[1]["media_path"] is None
        assert result[2]["media_path"] == os.path.join("voice", "b.opus")

    def test_returns_same_list_object(self, tmp_path: Path):
        """organize 应返回同一个列表对象（原地更新）"""
        media_base = tmp_path / "input"
        raw_dir = tmp_path / "raw"
        records: list[dict] = []

        organizer = MediaOrganizer()
        result = organizer.organize(records, media_base, raw_dir)
        assert result is records

    def test_subdirectory_media_path(self, tmp_path: Path):
        """media_path 可以包含子目录"""
        media_base = tmp_path / "input"
        raw_dir = tmp_path / "raw"
        self._make_media(media_base, "photos/2025/pic.png", b"png data")

        ts = int(datetime(2025, 7, 1).timestamp())
        records = [
            {"msg_uid": "T:14", "ts": ts, "modality": "image", "media_path": "photos/2025/pic.png", "text_raw": ""},
        ]

        organizer = MediaOrganizer()
        result = organizer.organize(records, media_base, raw_dir)

        # 文件名应该是 pic.png，放在 image/2025-07/ 下
        assert result[0]["media_path"] == os.path.join("image", "2025-07", "pic.png")


# ── Property-Based Tests (hypothesis) ────────────────────────────────

import tempfile
from hypothesis import given, settings, assume, HealthCheck
import hypothesis.strategies as st

from scripts.workspace.ingestion.media_organizer import file_hash
from scripts.workspace.ingestion.schema import VALID_MODALITIES

# 已知 modality 列表 + 一些未知值
_KNOWN_MODALITIES = sorted(VALID_MODALITIES)
_UNKNOWN_MODALITIES = ["pdf", "archive", "unknown", "doc", "spreadsheet", "other"]
_ALL_MODALITIES = _KNOWN_MODALITIES + _UNKNOWN_MODALITIES

# 非 image/video/voice/sticker 的 modality（应路由到 file/）
_FILE_ROUTED_MODALITIES = _UNKNOWN_MODALITIES + [
    m for m in _KNOWN_MODALITIES if m not in ("image", "video", "voice", "sticker")
]

# 合理的 Unix 时间戳范围：2000-01-01 ~ 2030-01-01
_TS_MIN = 946684800
_TS_MAX = 1893456000


class TestPropertyGetTargetDir:
    """Property 11: 媒体文件目标目录路由

    *For any* modality 值和 Unix 时间戳，get_target_dir(modality, ts, raw_dir)
    应返回正确的目标目录。

    **Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.5**
    """

    @given(
        ts=st.integers(min_value=_TS_MIN, max_value=_TS_MAX),
    )
    @settings(max_examples=200)
    def test_image_returns_correct_dated_dir(self, ts: int):
        """image modality 返回 raw/image/YYYY-MM/。 **Validates: Requirements 8.1**"""
        raw_dir = Path("/fake/raw")
        result = get_target_dir("image", ts, raw_dir)
        dt = datetime.fromtimestamp(ts)
        expected = raw_dir / "image" / dt.strftime("%Y-%m")
        assert result == expected

    @given(
        ts=st.integers(min_value=_TS_MIN, max_value=_TS_MAX),
    )
    @settings(max_examples=200)
    def test_video_returns_correct_dated_dir(self, ts: int):
        """video modality 返回 raw/video/YYYY-MM/。 **Validates: Requirements 8.3**"""
        raw_dir = Path("/fake/raw")
        result = get_target_dir("video", ts, raw_dir)
        dt = datetime.fromtimestamp(ts)
        expected = raw_dir / "video" / dt.strftime("%Y-%m")
        assert result == expected

    @given(
        ts=st.integers(min_value=_TS_MIN, max_value=_TS_MAX),
    )
    @settings(max_examples=200)
    def test_voice_returns_flat_dir(self, ts: int):
        """voice modality 返回 raw/voice/（无日期子目录）。 **Validates: Requirements 8.2**"""
        raw_dir = Path("/fake/raw")
        result = get_target_dir("voice", ts, raw_dir)
        assert result == raw_dir / "voice"

    @given(
        ts=st.integers(min_value=_TS_MIN, max_value=_TS_MAX),
    )
    @settings(max_examples=200)
    def test_sticker_returns_flat_dir(self, ts: int):
        """sticker modality 返回 raw/sticker/（无日期子目录）。 **Validates: Requirements 8.4**"""
        raw_dir = Path("/fake/raw")
        result = get_target_dir("sticker", ts, raw_dir)
        assert result == raw_dir / "sticker"

    @given(
        modality=st.sampled_from(_FILE_ROUTED_MODALITIES),
        ts=st.integers(min_value=_TS_MIN, max_value=_TS_MAX),
    )
    @settings(max_examples=200)
    def test_other_modalities_return_file_dir(self, modality: str, ts: int):
        """非 image/video/voice/sticker 的 modality 返回 raw/file/。 **Validates: Requirements 8.5**"""
        raw_dir = Path("/fake/raw")
        result = get_target_dir(modality, ts, raw_dir)
        assert result == raw_dir / "file"

    @given(
        modality=st.sampled_from(_ALL_MODALITIES),
        ts=st.integers(min_value=_TS_MIN, max_value=_TS_MAX),
    )
    @settings(max_examples=200)
    def test_result_always_under_raw_dir(self, modality: str, ts: int):
        """返回路径始终在 raw_dir 下。 **Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.5**"""
        raw_dir = Path("/fake/raw")
        result = get_target_dir(modality, ts, raw_dir)
        assert str(result).startswith(str(raw_dir))


class TestPropertyCopyWithDedup:
    """Property 12: 媒体文件去重——相同内容跳过

    *For any* 两个内容相同的文件，当目标路径已存在时，copy_with_dedup 应跳过复制
    并返回已存在文件的路径。当内容不同时，应添加哈希后缀生成新路径。

    **Validates: Requirements 8.7**
    """

    @given(
        content=st.binary(min_size=1, max_size=4096),
    )
    @settings(max_examples=200)
    def test_same_content_skips_copy(self, content: bytes):
        """相同内容的文件应跳过复制，返回已存在路径。 **Validates: Requirements 8.7**"""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            src = base / "src" / "file.dat"
            src.parent.mkdir(parents=True, exist_ok=True)
            src.write_bytes(content)

            dst = base / "dst" / "file.dat"
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(content)

            result = copy_with_dedup(src, dst)

            # 应返回原始 dst 路径（跳过复制）
            assert result == dst
            # 目录下仍然只有一个文件
            assert len(list(dst.parent.iterdir())) == 1
            # 内容不变
            assert dst.read_bytes() == content

    @given(
        content_src=st.binary(min_size=1, max_size=4096),
        content_dst=st.binary(min_size=1, max_size=4096),
    )
    @settings(max_examples=200)
    def test_different_content_creates_new_file(self, content_src: bytes, content_dst: bytes):
        """不同内容的文件应添加哈希后缀生成新路径。 **Validates: Requirements 8.7**"""
        assume(content_src != content_dst)

        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            src = base / "src" / "file.dat"
            src.parent.mkdir(parents=True, exist_ok=True)
            src.write_bytes(content_src)

            dst = base / "dst" / "file.dat"
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(content_dst)

            result = copy_with_dedup(src, dst)

            # 应返回不同于 dst 的新路径
            assert result != dst
            # 新文件在同一目录
            assert result.parent == dst.parent
            # 保留原始扩展名
            assert result.suffix == dst.suffix
            # 新文件包含源文件内容
            assert result.read_bytes() == content_src
            # 原文件内容不变
            assert dst.read_bytes() == content_dst
            # 目录下有两个文件
            assert len(list(dst.parent.iterdir())) == 2

    @given(
        content=st.binary(min_size=1, max_size=4096),
    )
    @settings(max_examples=200)
    def test_new_file_copies_directly(self, content: bytes):
        """目标不存在时直接复制。 **Validates: Requirements 8.7**"""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            src = base / "src" / "file.dat"
            src.parent.mkdir(parents=True, exist_ok=True)
            src.write_bytes(content)

            dst = base / "dst" / "file.dat"
            # dst 不存在

            result = copy_with_dedup(src, dst)

            assert result == dst
            assert dst.exists()
            assert dst.read_bytes() == content
