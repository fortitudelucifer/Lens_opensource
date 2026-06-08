"""routes/user_data.py — 一键删除用户所有本地数据（GDPR/CCPA 合规支撑）

清除范围（用户产生的个人数据）：
  - chat_sessions/           沉浸式互动会话
  - arena/sessions/          双镜对比会话（battles.jsonl / elo_ratings.json 保留，
                             因为这些是系统级聚合数据，删除会破坏统计连续性，
                             实际无 PII 风险——若用户要求彻底抹除，可走导出+人工脱敏通道）
  - assessments/             测评记录
  - crisis_archive/          危机事件归档（⚠️ 法律/伦理需求允许用户要求删除）
  - feedback/ui_feedback.jsonl   UI 反馈
  - feedback/chat_feedback.jsonl RAG 评价

**保留范围**（非个人数据）：
  - configs/**, knowledge/**, models/**, training/**, chunks/**, faiss_index/**

安全设计：
  1. 后端二次确认：body 必须包含 `confirm=="删除我的所有数据"` 字段，避免误触
  2. 返回删除计数与大小汇总，便于审计
  3. 不递归 rm 整个目录，仅删除内部文件（目录结构保留，避免下次启动 mkdir 报错）
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from ..core.config import ADVISOR_OUT
from ..core.models import EraseUserDataRequest, EraseUserDataResponse

router = APIRouter()

# 用户产生的数据子目录（相对 ADVISOR_OUT）
# 每项 (path, is_dir) — 目录清空内部文件，文件直接删除
USER_DATA_TARGETS: list[tuple[str, bool]] = [
    ("chat_sessions", True),
    ("arena/sessions", True),
    ("assessments", True),
    ("crisis_archive", True),
    ("feedback/ui_feedback.jsonl", False),
    ("feedback/chat_feedback.jsonl", False),
]

CONFIRM_PHRASE = "删除我的所有数据"


def _clear_dir_contents(dir_path: Path) -> tuple[int, int]:
    """清空目录内文件（不删目录本身）。返回 (删除数, 总字节)。"""
    removed, total_bytes = 0, 0
    if not dir_path.exists() or not dir_path.is_dir():
        return 0, 0
    for child in dir_path.iterdir():
        try:
            if child.is_file() or child.is_symlink():
                total_bytes += child.stat().st_size
                child.unlink()
                removed += 1
            elif child.is_dir():
                # 统计并删除子目录内全部内容
                for f in child.rglob("*"):
                    if f.is_file():
                        total_bytes += f.stat().st_size
                shutil.rmtree(child)
                removed += 1
        except OSError:
            # 忽略单文件失败，继续处理其他
            continue
    return removed, total_bytes


def _remove_file(file_path: Path) -> tuple[int, int]:
    """删除单个文件。返回 (1, 字节) 或 (0, 0)。"""
    if not file_path.exists() or not file_path.is_file():
        return 0, 0
    try:
        size = file_path.stat().st_size
        file_path.unlink()
        return 1, size
    except OSError:
        return 0, 0


@router.delete("/api/user-data/all", response_model=EraseUserDataResponse)
async def erase_all_user_data(req: EraseUserDataRequest) -> Any:
    """一键删除当前部署下所有用户产生的数据。

    **二次确认**：请求体必须传 `confirm="删除我的所有数据"`，否则拒绝。
    """
    if req.confirm != CONFIRM_PHRASE:
        raise HTTPException(
            status_code=400,
            detail=f"二次确认短语不匹配，需要精确输入：{CONFIRM_PHRASE}",
        )

    details: dict[str, dict[str, int]] = {}
    total_removed = 0
    total_bytes = 0

    for rel_path, is_dir in USER_DATA_TARGETS:
        target = ADVISOR_OUT / rel_path
        if is_dir:
            removed, size = _clear_dir_contents(target)
        else:
            removed, size = _remove_file(target)
        details[rel_path] = {"items_removed": removed, "bytes_removed": size}
        total_removed += removed
        total_bytes += size

    return EraseUserDataResponse(
        status="ok",
        total_items_removed=total_removed,
        total_bytes_removed=total_bytes,
        details=details,
        message=f"已删除 {total_removed} 项用户数据（共 {total_bytes} 字节）",
    )
