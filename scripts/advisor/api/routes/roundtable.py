"""routes/roundtable.py — 圆桌讨论 API（Day 3 D3.3）

包含 4 个端点：
  - POST   /api/roundtable/sessions              创建 session（不立即触发 pipeline）
  - GET    /api/roundtable/stream/{session_id}   SSE 订阅 + 首次订阅 trigger pipeline
  - POST   /api/roundtable/sessions/{id}/interrupt   中断 pipeline（DAG 分叉前置步骤）
  - GET    /api/roundtable/sessions              列出所有 session（运维 / 调试用）

SSE 协议（与 frontend/src/hooks/useRoundtableStream.ts 严格一致）：
  data: {"type":"agent_status","agent_id":"neutral","phase":"phase1","status":"typing"}
  data: {"type":"agent_chunk","agent_id":"neutral","phase":"phase1","delta":"听"}
  data: {"type":"agent_done","agent_id":"neutral","phase":"phase1","confidence":0.78}
  data: {"type":"phase_advance","phase":"phase2"}
  data: {"type":"moderator","content":{"seen":"...","angles":[...],...}}
  data: {"type":"done"}
  data: {"type":"error","message":"..."}
"""
from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from ..core.models import (
    RoundtableContinueRequest, RoundtableContinueResponse,
    RoundtableInjectPreviewRequest, RoundtableInjectPreviewResponse,
    RoundtableStartRequest, RoundtableStartResponse,
)
from ..services import roundtable_service

router = APIRouter()


@router.post(
    "/api/roundtable/sessions",
    response_model=RoundtableStartResponse,
    status_code=201,
)
async def create_roundtable_session(req: RoundtableStartRequest) -> RoundtableStartResponse:
    """创建圆桌讨论 session（不启动 pipeline，等 SSE 订阅触发）。

    - personas: 必须 3 个 Lens persona id
    - question: 4-2000 字符的用户问题
    - parent_id: 可选，DAG 分叉时传入父 session id
    """
    # 防重复（同样的 personas）
    if len(set(req.personas)) != 3:
        raise HTTPException(400, "personas 必须是 3 个不同的 persona id")

    # 校验 parent_id 存在性（如有）
    if req.parent_id is not None and roundtable_service.get_session(req.parent_id) is None:
        raise HTTPException(404, f"parent session {req.parent_id} not found")

    session = roundtable_service.create_session(
        personas=list(req.personas),
        question=req.question,
        parent_id=req.parent_id,
        backend=req.backend,
        inject_context=req.inject_context,
        deep_mode=req.deep_mode,
    )

    return RoundtableStartResponse(
        session_id=session.id,
        status="created",
        created_at=session.created_at.isoformat(),
    )


@router.get("/api/roundtable/stream/{session_id}")
async def stream_roundtable(session_id: str):
    """SSE 订阅 session 的事件流。第一次订阅时 trigger pipeline。

    前端用 EventSource：
        const es = new EventSource(`/api/roundtable/stream/${sessionId}`)
        es.onmessage = (msg) => dispatchRoundtableEvent(JSON.parse(msg.data), store)
    """
    # 提前校验 session 存在（避免在 stream 内部才报错）
    if roundtable_service.get_session(session_id) is None:
        raise HTTPException(404, f"Session {session_id} not found")

    async def _event_stream():
        async for event in roundtable_service.subscribe(session_id):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        # 显式 [DONE]，与 chat.py SSE 风格一致
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            # 关键：禁用 Nginx / proxy 缓冲，让事件实时下发
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.post("/api/roundtable/sessions/{session_id}/interrupt")
async def interrupt_roundtable(session_id: str) -> dict:
    """中断 session 的 pipeline 任务（DAG 分叉前置步骤）"""
    if roundtable_service.get_session(session_id) is None:
        raise HTTPException(404, f"Session {session_id} not found")

    interrupted = await roundtable_service.interrupt_session(session_id)
    return {
        "session_id": session_id,
        "interrupted": interrupted,
        "interrupted_at": datetime.now().isoformat(),
    }


@router.get("/api/roundtable/sessions")
async def list_roundtable_sessions() -> list[dict]:
    """列出当前内存中的所有 session 摘要（Day 6 · 前端 RoundtablePage 历史入口）。

    返回值包含 round_index / rounds_count / updated_at，按 updated_at 倒序。
    """
    return roundtable_service.list_sessions()


@router.get("/api/roundtable/sessions/{session_id}")
async def get_roundtable_session(session_id: str) -> dict:
    """Day 6 · 获取 session 完整快照（含 rounds[]），供前端恢复历史对话 UI。"""
    detail = roundtable_service.get_session_detail(session_id)
    if detail is None:
        raise HTTPException(404, f"Session {session_id} not found")
    return detail


@router.post(
    "/api/roundtable/sessions/{session_id}/continue",
    response_model=RoundtableContinueResponse,
    status_code=200,
)
async def continue_roundtable_session(
    session_id: str,
    req: RoundtableContinueRequest,
) -> RoundtableContinueResponse:
    """Day 6 · 多轮对话形态 A · 在已 done 的 session 上追问新问题。

    - session 必须存在 · 404
    - session 必须 phase == "done" · 409（否则会打断进行中的讨论）
    - 成功后：把当前轮归档到 rounds[]，重置为 setup，等前端**重新**
      订阅 `GET /api/roundtable/stream/{session_id}` 才 trigger 新轮 pipeline。
    """
    if roundtable_service.get_session(session_id) is None:
        raise HTTPException(404, f"Session {session_id} not found")

    try:
        session = roundtable_service.continue_session(
            session_id,
            req.question,
            inject_context=req.inject_context,
            deep_mode=req.deep_mode,
        )
    except ValueError as exc:
        # phase != "done"（进行中/已中断）→ 409 Conflict
        raise HTTPException(409, str(exc)) from exc

    return RoundtableContinueResponse(
        session_id=session.id,
        round_index=session.round_index,
        status="continued",
        started_at=session.updated_at.isoformat(),
    )


@router.post(
    "/api/roundtable/inject/preview",
    response_model=RoundtableInjectPreviewResponse,
)
async def preview_roundtable_injection(
    req: RoundtableInjectPreviewRequest,
) -> RoundtableInjectPreviewResponse:
    """Day 6 · Step 4 · RAG 注入预览（聊天记录 + 知识手册）。

    前端在追问输入框里点「注入聊天记录 / 注入知识手册」按钮时调用本接口，
    根据当前草稿问题做 FAISS + rerank 检索 + 关键词检索，返回命中片段供用户勾选。
    用户勾选后把拼好的 context 字符串通过 `continue` 的 `inject_context` 字段下发。
    """
    result = roundtable_service.build_inject_preview(
        query=req.query,
        modes=list(req.modes),
        top_k=req.top_k,
    )
    return RoundtableInjectPreviewResponse.model_validate(result)
