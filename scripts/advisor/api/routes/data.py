"""routes/data.py — 数据统计"""
from __future__ import annotations

from fastapi import APIRouter

from ..core.config import (
    ANALYSIS_DIR, CHUNKS_DIR, REVIEW_DIR,
    USER_WORKSPACE, WORKSPACE,
)
from ..core.utils import count_jsonl_lines

router = APIRouter()


@router.get("/api/data/stats")
async def get_data_stats():
    """获取数据统计"""
    # 检查用户工作空间和项目工作空间的数据
    l1_path = USER_WORKSPACE / "timeline_out" / "agent_sft_l1.jsonl"
    l2_path = USER_WORKSPACE / "timeline_out" / "agent_sft_l2.jsonl"
    test_path = USER_WORKSPACE / "timeline_out" / "agent_sft_test.jsonl"

    if not l1_path.exists():
        l1_path = WORKSPACE / "timeline_out" / "agent_sft_l1.jsonl"
    if not l2_path.exists():
        l2_path = WORKSPACE / "timeline_out" / "agent_sft_l2.jsonl"
    if not test_path.exists():
        test_path = WORKSPACE / "timeline_out" / "agent_sft_test.jsonl"

    chunks_path = CHUNKS_DIR / "conversation_chunks.jsonl"

    return {
        "l1_lines": count_jsonl_lines(l1_path),
        "l2_lines": count_jsonl_lines(l2_path),
        "test_lines": count_jsonl_lines(test_path),
        "chunks": count_jsonl_lines(chunks_path),
        "analyses": {
            "neutral": count_jsonl_lines(ANALYSIS_DIR / "raw_analysis_neutral.jsonl"),
            "supportive": count_jsonl_lines(ANALYSIS_DIR / "raw_analysis_supportive.jsonl"),
            "psychoanalytic": count_jsonl_lines(ANALYSIS_DIR / "raw_analysis_psychoanalytic.jsonl"),
        },
        "reviews": {
            "neutral": count_jsonl_lines(REVIEW_DIR / "ai_review_neutral.jsonl"),
            "supportive": count_jsonl_lines(REVIEW_DIR / "ai_review_supportive.jsonl"),
            "psychoanalytic": count_jsonl_lines(REVIEW_DIR / "ai_review_psychoanalytic.jsonl"),
        },
    }
