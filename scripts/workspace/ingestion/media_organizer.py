"""
media_organizer.py
媒体文件组织器 —— 将输入媒体文件按 raw/ 标准目录结构重新组织

目标结构：
  image  → raw/image/YYYY-MM/
  voice  → raw/voice/
  video  → raw/video/YYYY-MM/
  sticker → raw/sticker/
  其他   → raw/file/

运行方式：
    python -m pytest tests/workspace/ingestion/test_media_organizer.py -v
"""

from __future__ import annotations

import hashlib
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

from tqdm import tqdm

logger = logging.getLogger(__name__)

# 需要按 YYYY-MM 子目录组织的 modality
_DATED_MODALITIES = frozenset({"image", "video"})

# modality → 目录名映射（不在此表中的统一归入 file/）
_MODALITY_DIR_MAP: dict[str, str] = {
    "image": "image",
    "voice": "voice",
    "video": "video",
    "sticker": "sticker",
}


# ── 公开辅助函数（供属性测试直接调用） ─────────────────────────────────


def get_target_dir(modality: str, ts: int, raw_dir: Path) -> Path:
    """根据 modality 和时间戳确定目标目录。

    - image / video → raw/{modality}/YYYY-MM/
    - voice         → raw/voice/
    - sticker       → raw/sticker/
    - 其他          → raw/file/
    """
    dir_name = _MODALITY_DIR_MAP.get(modality, "file")
    base = raw_dir / dir_name

    if modality in _DATED_MODALITIES:
        dt = datetime.fromtimestamp(ts)
        yyyy_mm = dt.strftime("%Y-%m")
        return base / yyyy_mm

    return base


def file_hash(path: Path, algorithm: str = "sha256") -> str:
    """计算文件内容的十六进制哈希值。"""
    h = hashlib.new(algorithm)
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def copy_with_dedup(src: Path, dst: Path) -> Path:
    """复制文件到 *dst*，同名不同内容时添加哈希后缀。

    返回实际写入的目标路径。

    - 目标不存在 → 直接复制，返回 dst
    - 目标存在且内容相同 → 跳过复制，返回 dst
    - 目标存在但内容不同 → 添加 _<hash8> 后缀，复制到新路径
    """
    if dst.exists():
        src_hash = file_hash(src)
        dst_hash = file_hash(dst)
        if src_hash == dst_hash:
            # 内容相同，跳过
            return dst
        # 内容不同，添加哈希后缀
        short_hash = src_hash[:8]
        new_name = f"{dst.stem}_{short_hash}{dst.suffix}"
        dst = dst.parent / new_name

    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return dst


# ── MediaOrganizer 类 ─────────────────────────────────────────────────


class MediaOrganizer:
    """媒体文件组织器"""

    # 暴露为实例方法（内部委托给模块级函数，方便测试）
    _get_target_dir = staticmethod(get_target_dir)
    _copy_with_dedup = staticmethod(copy_with_dedup)

    def organize(
        self,
        records: list[dict],
        media_base_dir: Path,
        target_raw_dir: Path,
    ) -> list[dict]:
        """将媒体文件按标准目录结构组织，并更新 media_path。

        Parameters
        ----------
        records : list[dict]
            消息记录列表（每条记录至少包含 modality / ts / media_path）。
        media_base_dir : Path
            输入媒体文件的基础目录（源文件相对路径的根）。
        target_raw_dir : Path
            目标 raw/ 目录（复制后的文件将放在此目录下）。

        Returns
        -------
        list[dict]
            更新了 media_path 的消息记录列表。
        """
        media_records = [
            r for r in records if r.get("media_path") is not None
        ]

        for rec in tqdm(media_records, desc="组织媒体文件", unit="file"):
            media_path_str: Optional[str] = rec.get("media_path")
            if media_path_str is None:
                continue

            src = media_base_dir / media_path_str
            if not src.exists():
                logger.warning("源媒体文件不存在: %s，跳过", src)
                rec["media_path"] = None
                continue

            modality: str = rec.get("modality", "")
            ts: int = rec.get("ts", 0)

            target_dir = self._get_target_dir(modality, ts, target_raw_dir)
            target_dir.mkdir(parents=True, exist_ok=True)

            dst = target_dir / src.name
            actual_dst = self._copy_with_dedup(src, dst)

            # media_path 更新为相对于 raw/ 的路径
            rel = actual_dst.relative_to(target_raw_dir)
            rec["media_path"] = str(rel)

        return records
