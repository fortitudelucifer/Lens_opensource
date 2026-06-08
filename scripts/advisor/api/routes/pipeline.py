"""routes/pipeline.py — 流水线控制"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException

from ..core import state
from ..core.models import PipelineRunRequest
from ..services import pipeline_service

router = APIRouter()


@router.get("/api/pipeline/status")
async def get_pipeline_status():
    """获取流水线状态"""
    return state.pipeline_state


@router.post("/api/pipeline/run/{phase}")
async def run_pipeline_phase(phase: int, req: PipelineRunRequest):
    """运行指定阶段"""
    if phase < 1 or phase > 8:
        raise HTTPException(status_code=400, detail="Phase must be 1-8")
    if state.pipeline_state["running_task"]:
        raise HTTPException(status_code=409, detail="已有任务在运行中")

    state.pipeline_state["phases"][phase]["status"] = "running"
    state.pipeline_state["running_task"] = phase

    # 在后台线程运行
    asyncio.get_event_loop().run_in_executor(
        None, pipeline_service.run_phase_sync, phase, req
    )

    return {"message": f"Phase {phase} 已启动", "phase": phase}
