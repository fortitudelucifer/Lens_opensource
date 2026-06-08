"""routes/health.py — 健康检查"""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/api/health")
async def health():
    return {"status": "ok", "version": "2.3"}
