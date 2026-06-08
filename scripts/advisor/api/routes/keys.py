"""routes/keys.py — API Key Checker（集成自 api-key-checker 独立工具）"""
from __future__ import annotations

import asyncio
import time

import httpx
from fastapi import APIRouter

from ..core import state
from ..core.models import (
    KeyCheckerFetchRequest, KeyCheckerCheckRequest,
    KeyCheckerStopRequest, KeyCheckerBatchRequest,
)

router = APIRouter()

_KEY_CHECKER_RATE_LIMIT_S = 5.0


@router.post("/api/keys/fetch-models")
async def key_checker_fetch_models(req: KeyCheckerFetchRequest):
    """获取指定 API 端点的可用模型列表"""
    base = req.base_url.rstrip("/")
    url = f"{base}/v1/models" if "/v1" not in base else f"{base}/models"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            start = time.time()
            resp = await client.get(
                url, headers={"Authorization": f"Bearer {req.api_key}"}
            )
            duration = int((time.time() - start) * 1000)
            data = resp.json()
            raw = data.get("data", data) if isinstance(data, dict) else data
            models = []
            if isinstance(raw, list):
                for m in raw:
                    if isinstance(m, str):
                        models.append({"id": m})
                    elif isinstance(m, dict) and m.get("id"):
                        models.append({"id": m["id"]})
            return {"success": True, "models": models, "duration": duration}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/api/keys/check")
async def key_checker_check(req: KeyCheckerCheckRequest):
    """测试单个模型的连通性"""
    # Rate limit per key
    now = time.time()
    last = state.key_checker_rate_limits.get(req.api_key, 0)
    if now - last < _KEY_CHECKER_RATE_LIMIT_S:
        return {"success": False, "error": f"限速中，请等待 {_KEY_CHECKER_RATE_LIMIT_S}s"}
    state.key_checker_rate_limits[req.api_key] = now

    base = req.base_url.rstrip("/")
    url = f"{base}/v1/chat/completions" if "/v1" not in base else f"{base}/chat/completions"
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            start = time.time()
            resp = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {req.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": req.model,
                    "messages": [{"role": "user", "content": "Hi"}],
                    "max_tokens": 1,
                    "temperature": 0,
                    "stream": False,
                },
            )
            latency = int((time.time() - start) * 1000)
            data = resp.json()
            if resp.status_code == 200:
                return {
                    "success": True,
                    "latency": latency,
                    "model": data.get("model", req.model),
                    "usage": data.get("usage"),
                }
            else:
                err = data.get("error", {})
                return {
                    "success": False,
                    "error": err.get("message", str(data)[:300]),
                    "status": resp.status_code,
                    "details": data,
                }
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/api/keys/batch-check")
async def key_checker_batch_check(req: KeyCheckerBatchRequest):
    """批量检测多个模型（带 5s 间隔限速）"""
    results = {}
    detection_id = req.detection_id or f"{int(time.time())}"
    state.active_checks[detection_id] = [True]  # alive flag

    for i, model in enumerate(req.models):
        # Check if stopped
        if detection_id not in state.active_checks or not state.active_checks[detection_id][0]:
            break

        single = KeyCheckerCheckRequest(
            base_url=req.base_url,
            api_key=req.api_key,
            model=model,
            detection_id=detection_id,
        )
        # Reset rate limit for batch (we handle interval ourselves)
        state.key_checker_rate_limits.pop(req.api_key, None)
        result = await key_checker_check(single)
        results[model] = result

        # Wait between requests (except last)
        if i < len(req.models) - 1:
            await asyncio.sleep(_KEY_CHECKER_RATE_LIMIT_S)

    state.active_checks.pop(detection_id, None)
    return {"results": results, "tested": len(results), "total": len(req.models)}


@router.post("/api/keys/stop")
async def key_checker_stop(req: KeyCheckerStopRequest):
    """终止正在进行的批量检测"""
    if req.detection_id in state.active_checks:
        state.active_checks[req.detection_id][0] = False
        return {"success": True, "message": "已请求终止"}
    return {"success": False, "error": "未找到该检测任务"}
