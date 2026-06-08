"""routes/feedback.py — 全局 UI / Bug 反馈端点

与 /api/chat/feedback（面向 RAG 质量评价）区分：
  - /api/feedback        → UI/Bug 反馈 → advisor_out/feedback/ui_feedback.jsonl
  - /api/chat/feedback   → RAG 质量评价 → advisor_out/feedback/chat_feedback.jsonl
"""
from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter

from ..core.config import ADVISOR_OUT
from ..core.models import UIFeedback

router = APIRouter()


@router.post("/api/feedback")
async def submit_ui_feedback(fb: UIFeedback):
    """收集全局 UI / Bug 反馈并追加写入 JSONL。"""
    feedback_dir = ADVISOR_OUT / "feedback"
    feedback_dir.mkdir(parents=True, exist_ok=True)
    feedback_file = feedback_dir / "ui_feedback.jsonl"

    entry = {
        "content": fb.content.strip(),
        "page": fb.page,
        "user_agent": fb.user_agent,
        "timestamp": datetime.now().isoformat(),
    }
    with open(feedback_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return {"status": "ok", "message": "反馈已记录"}
