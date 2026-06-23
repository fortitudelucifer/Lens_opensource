#!/usr/bin/env python3
"""scripts/advisor/api/main.py — FastAPI app 组装入口（Phase 3 Step 11）

职责：
- 创建 FastAPI app 实例
- 加载环境变量（.env.advisor）
- 初始化全局状态（crisis_detector / intent_classifier）
- 启动 RAG 后台索引线程
- 注册所有 routers
- 挂接全局异常中间件

启动命令：
    conda run -n wechatDHA uvicorn scripts.advisor.api.main:app --reload --port 8787
（旧命令 scripts.advisor.api.server:app 仍然兼容，由 server.py 做 shim）
"""
from __future__ import annotations

import logging
import sys
import traceback
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# 项目根目录（main.py 位于 scripts/advisor/api/）
_PROJECT_ROOT = Path(__file__).resolve().parents[3]

# 自动加载环境变量（API keys 等）
_env_file = _PROJECT_ROOT / "local_secrets" / ".env.advisor"
if _env_file.exists():
    load_dotenv(_env_file, override=False)
    print(f"[env] 已加载 {_env_file}")
sys.path.insert(0, str(_PROJECT_ROOT))


# ─────────────────────────────────────────────────────────────
# Day 5 · D5.5 · 结构化日志配置
# ─────────────────────────────────────────────────────────────
# 问题：uvicorn 默认 root logger 不带 handler，INFO 级别被丢弃
#       → `bias_detector.log.info` / `roundtable_audit.log.info` 等看不到
# 方案：给 `scripts.advisor.api.services` 专设一个 handler，
#       propagate=False 以免与 uvicorn 的 access log 重复。
def _configure_services_logger() -> None:
    services_logger = logging.getLogger("scripts.advisor.api.services")
    if services_logger.handlers:
        return  # 已配置 · 幂等
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(name)s] %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    services_logger.addHandler(handler)
    services_logger.setLevel(logging.INFO)
    services_logger.propagate = False


_configure_services_logger()


# ── App ──────────────────────────────────────────────────────
app = FastAPI(title="Advisor Pipeline API", version="2.3")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── 全局异常处理中间件（§0 Step 11 + §5.2 安全加固）─────────
@app.middleware("http")
async def catch_all_exceptions(request: Request, call_next):
    """未捕获异常的最后防线：返回 500 JSON，不泄露 stack trace；服务端保留详细日志。"""
    try:
        return await call_next(request)
    except Exception as exc:
        # 服务端详细日志
        print(f"[ERROR] {request.method} {request.url.path} — {type(exc).__name__}: {exc}")
        traceback.print_exc()
        # 客户端精简错误
        return JSONResponse(
            status_code=500,
            content={"detail": f"Internal Server Error ({type(exc).__name__})"},
        )


# ── 初始化全局状态 ───────────────────────────────────────────
# 顺序很关键：
#   1. crisis_detector     safety routes + chat/arena 依赖
#   2. intent_classifier   rag_service.build_rag_context 依赖
#   3. rag_service.init_rag  加载元数据 + 姓名映射 + FAQ + 后台语义索引线程
from scripts.advisor.api.core import state
from scripts.advisor.api.crisis_detector import CrisisDetector
from scripts.advisor.intent_classifier import IntentClassifier
from scripts.advisor.api.services import rag_service

state.crisis_detector = CrisisDetector()
print("[Safety] 危机检测器已加载")

state.intent_classifier = IntentClassifier()

rag_service.init_rag()


# ── 挂载所有 routers ─────────────────────────────────────────
from scripts.advisor.api.routes import (  # noqa: E402
    arena, assessment, chat, data, feedback, health, keys, knowledge,
    models_routes, pipeline, rag, review, roundtable, safety, user_data,
)

for _module in (
    health, safety, keys,
    pipeline, review, data, knowledge, models_routes, rag, assessment,
    chat, arena, roundtable, feedback, user_data,
):
    app.include_router(_module.router)


__all__ = ["app"]
