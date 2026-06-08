"""services/review_service.py — 人工审核缓存/持久化

从 server.py 迁移（Step 7）：
  - `_load_review_cache` → `load_review_cache`
  - `_save_review_cache` → `save_review_cache`

依赖：
  - core/state.py：state.review_cache
  - core/config.py：REVIEW_DIR
  - core/utils.py：load_jsonl
"""
from __future__ import annotations

import json
import uuid

from ..core import state
from ..core.config import REVIEW_DIR
from ..core.utils import load_jsonl


def load_review_cache(agent_type: str = "neutral"):
    """加载审核数据到 state.review_cache"""
    path = REVIEW_DIR / f"ai_review_{agent_type}.jsonl"
    if path.exists():
        items = load_jsonl(path)
        for item in items:
            item_id = item.get("id", str(uuid.uuid4()))
            item["id"] = item_id
            state.review_cache[item_id] = item


def save_review_cache(agent_type: str):
    """将审核缓存中某一 agent_type 的条目持久化到 ai_review_<agent_type>.jsonl"""
    path = REVIEW_DIR / f"ai_review_{agent_type}.jsonl"
    items = [
        item for item in state.review_cache.values()
        if item.get("agent_type") == agent_type
    ]
    with open(path, "w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
