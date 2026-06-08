"""core/utils.py — 共享文件工具（跨 service 使用）

从 server.py 迁移（Step 6 辅助）：
  - `_count_jsonl_lines`       → `count_jsonl_lines`
  - `_load_jsonl`              → `load_jsonl`
  - `_mirror_to_user_workspace` → `mirror_to_user_workspace`
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from .config import ADVISOR_OUT, USER_WORKSPACE


def count_jsonl_lines(path: Path) -> int:
    if not path.exists():
        return 0
    with open(path, "r", encoding="utf-8") as f:
        return sum(1 for line in f if line.strip())


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    items = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


def mirror_to_user_workspace():
    """将 advisor_out/ 镜像到用户可访问的工作空间"""
    dest = USER_WORKSPACE / "advisor_out"
    for subdir in ["chunks", "analysis", "review"]:
        src = ADVISOR_OUT / subdir
        dst = dest / subdir
        dst.mkdir(parents=True, exist_ok=True)
        if src.exists():
            for f in src.iterdir():
                if f.is_file():
                    shutil.copy2(str(f), str(dst / f.name))
