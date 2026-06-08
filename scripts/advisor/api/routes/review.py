"""routes/review.py — 人工审核"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException

from ..core import state
from ..core.models import ReviewDecision
from ..services import review_service

router = APIRouter()


@router.get("/api/review/items")
async def get_review_items(
    agent_type: str = "neutral",
    filter: str = "all",  # all | pending | passed | failed
):
    """获取审核条目列表"""
    # 确保缓存已加载
    if not state.review_cache:
        review_service.load_review_cache(agent_type)

    items = list(state.review_cache.values())

    # 过滤
    if filter == "pending":
        items = [i for i in items if i.get("human_decision") is None]
    elif filter == "passed":
        items = [
            i for i in items
            if i.get("review", {}).get("passed") or i.get("human_decision") == "approve"
        ]
    elif filter == "failed":
        items = [
            i for i in items
            if not i.get("review", {}).get("passed") and i.get("human_decision") != "approve"
        ]

    # 返回摘要列表
    summary = []
    for item in items:
        review = item.get("review", {})
        summary.append({
            "id": item.get("id"),
            "chunk_id": item.get("chunk_id"),
            "agent_type": item.get("agent_type"),
            "ai_passed": review.get("passed", False),
            "ai_score": review.get("total_score", 0),
            "ai_summary": review.get("summary", ""),
            "human_decision": item.get("human_decision"),
            "conversation_preview": (item.get("conversation", "") or "")[:200],
        })

    return {
        "total": len(summary),
        "items": summary,
        "stats": {
            "total": len(state.review_cache),
            "ai_passed": sum(1 for i in state.review_cache.values() if i.get("review", {}).get("passed")),
            "ai_failed": sum(1 for i in state.review_cache.values() if not i.get("review", {}).get("passed")),
            "human_approved": sum(1 for i in state.review_cache.values() if i.get("human_decision") == "approve"),
            "human_rejected": sum(1 for i in state.review_cache.values() if i.get("human_decision") == "reject"),
            "pending": sum(1 for i in state.review_cache.values() if i.get("human_decision") is None),
        },
    }


@router.get("/api/review/items/{item_id}")
async def get_review_item(item_id: str):
    """获取单条审核详情"""
    if item_id not in state.review_cache:
        raise HTTPException(status_code=404, detail="审核条目不存在")
    return state.review_cache[item_id]


@router.post("/api/review/items/{item_id}")
async def submit_review_decision(item_id: str, decision: ReviewDecision):
    """提交人工审核决定"""
    if item_id not in state.review_cache:
        raise HTTPException(status_code=404, detail="审核条目不存在")

    item = state.review_cache[item_id]
    item["human_decision"] = decision.decision
    item["human_notes"] = decision.notes
    if decision.edited_analysis:
        try:
            item["edited_analysis"] = json.loads(decision.edited_analysis)
        except json.JSONDecodeError:
            item["edited_analysis"] = decision.edited_analysis

    # 持久化
    review_service.save_review_cache(item.get("agent_type", "neutral"))

    return {"message": "审核结果已保存", "item_id": item_id, "decision": decision.decision}
