"""routes/models_routes.py — 模型后端信息 + 模型偏好 + 连通性测试"""
from __future__ import annotations

import asyncio
import json
import os
import time

import httpx
from fastapi import APIRouter

from scripts.advisor.generator import AnalysisGenerator

from ..core.config import PREFS_PATH
from ..core.models import ModelPreferences, ModelTestRequest
from ..services.generator_service import get_generator

router = APIRouter()


_DEFAULT_MODELS = {
    "openai": "gpt-5.3-codex-spark",
    "claude": "claude-sonnet-4.6-think",
    "gemini": "gemini-3.1-pro-preview",
    "kimi": "gemini-3-flash",
    "grok": "grok-4.1-thinking",
    "deepseek": "gemini-2.5-flash",
    "qwen_local": "qwen3:8b",
    "qwen_cloud": "gemini-2.5-flash",
    "glm": "gemini-2.5-flash",
}


def _load_prefs() -> dict:
    if PREFS_PATH.exists():
        with open(PREFS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return ModelPreferences().model_dump()


def _save_prefs(prefs: dict):
    PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(PREFS_PATH, "w", encoding="utf-8") as f:
        json.dump(prefs, f, ensure_ascii=False, indent=2)


def _get_suitable_roles(backend: str) -> list[str]:
    """Returns which roles a backend is suitable for"""
    roles_map = {
        "openai": ["analysis", "review", "chat"],
        "claude": ["analysis", "review", "chat"],
        "gemini": ["analysis", "review", "chat"],
        "kimi": ["analysis", "chat"],
        "grok": ["analysis", "review", "chat"],
        "deepseek": ["analysis", "review", "chat"],
        "qwen_local": ["chat"],
        "qwen_cloud": ["analysis", "review", "chat"],
        "glm": ["analysis", "chat"],
    }
    return roles_map.get(backend, ["chat"])


@router.get("/api/models")
async def get_models():
    """获取所有模型后端的状态"""
    env_prefix_map = AnalysisGenerator._ENV_PREFIX
    models_info = []

    for backend, prefix in env_prefix_map.items():
        api_key = os.environ.get(f"{prefix}_API_KEY", "")
        base_url = os.environ.get(f"{prefix}_BASE_URL", "")
        model = os.environ.get(f"{prefix}_MODEL", "") or _DEFAULT_MODELS.get(backend, "")

        has_key = bool(api_key and api_key != "not-needed")
        if backend == "qwen_local":
            has_key = True  # 本地不需要 key

        status = "offline"
        if has_key and base_url:
            status = "connected"
        elif has_key:
            status = "configured"

        models_info.append({
            "backend": backend,
            "model": model,
            "base_url": base_url or "(默认)",
            "status": status,
            "has_key": has_key,
        })

    return models_info


@router.get("/api/models/preferences")
async def get_model_preferences():
    """获取模型偏好设置"""
    return _load_prefs()


@router.post("/api/models/preferences")
async def set_model_preferences(prefs: ModelPreferences):
    """保存模型偏好设置"""
    data = prefs.model_dump()
    _save_prefs(data)
    return {"message": "模型偏好已保存", "preferences": data}


@router.get("/api/models/available")
async def get_available_models():
    """获取所有可用模型（按用途分组）"""
    env_prefix_map = AnalysisGenerator._ENV_PREFIX
    available = []

    for backend, prefix in env_prefix_map.items():
        api_key = os.environ.get(f"{prefix}_API_KEY", "")
        base_url = os.environ.get(f"{prefix}_BASE_URL", "")
        model = os.environ.get(f"{prefix}_MODEL", "") or _DEFAULT_MODELS.get(backend, "")
        has_key = bool(api_key and api_key != "not-needed")
        if backend == "qwen_local":
            has_key = True

        if has_key:
            available.append({
                "backend": backend,
                "model": model,
                "base_url": base_url or "(默认)",
                "suitable_for": _get_suitable_roles(backend),
            })

    return available


@router.post("/api/models/test")
async def test_model(req: ModelTestRequest):
    """测试模型连通性：发送一条简短消息验证 API 是否可用"""
    start = time.time()
    try:
        gen = get_generator(req.backend, req.model or None)
        messages = [
            {"role": "system", "content": "你是一个助手。"},
            {"role": "user", "content": req.prompt},
        ]
        kwargs = dict(
            model=gen.model,
            messages=messages,
            stream=False,
            max_tokens=200,
        )
        if not ("think" in gen.model.lower()):
            kwargs["temperature"] = 0.3

        wire_api = os.environ.get("OPENAI_WIRE_API", "").lower()
        use_responses_api = (req.backend == "openai" and wire_api == "responses")

        def _sync_call():
            if use_responses_api:
                url = f"{gen.base_url.rstrip('/')}/responses"
                headers = {
                    "Authorization": f"Bearer {gen.api_key}",
                    "Content-Type": "application/json",
                    "Accept": "text/event-stream",
                }
                api_input = [
                    {"role": "user", "content": [{"type": "input_text", "text": req.prompt}]},
                ]
                payload = {"model": gen.model, "input": api_input, "store": False, "stream": True}
                text = ""
                timeout = httpx.Timeout(connect=15.0, read=30.0, write=15.0, pool=15.0)
                with httpx.Client(timeout=timeout) as client:
                    with client.stream("POST", url, headers=headers, json=payload) as r:
                        r.raise_for_status()
                        for line in r.iter_lines():
                            if not line.startswith("data: "):
                                continue
                            raw = line[6:]
                            if raw == "[DONE]":
                                break
                            try:
                                evt = json.loads(raw)
                            except Exception:
                                continue
                            if evt.get("type") == "response.output_text.delta":
                                text += evt.get("delta", "")
                return text or "(empty)"
            return gen.client.chat.completions.create(**kwargs)

        result = await asyncio.get_event_loop().run_in_executor(None, _sync_call)
        if use_responses_api:
            content = result[:500] if isinstance(result, str) else "(empty)"
        else:
            resp = result
            msg = resp.choices[0].message if resp.choices else None
            content = "(empty)"
            if msg:
                content = msg.content or getattr(msg, 'reasoning_content', None) or "(empty)"
        elapsed = time.time() - start

        return {
            "status": "ok",
            "backend": req.backend,
            "model": gen.model,
            "base_url": gen.base_url or "(default)",
            "response": content[:500],
            "latency_ms": round(elapsed * 1000),
        }
    except Exception as e:
        elapsed = time.time() - start
        return {
            "status": "error",
            "backend": req.backend,
            "model": req.model or "(default)",
            "error": str(e)[:500],
            "latency_ms": round(elapsed * 1000),
        }
