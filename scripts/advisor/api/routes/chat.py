"""routes/chat.py — 多轮 LLM 对话 + 会话 CRUD + 危机检测 + SSE 流式

包含 9 个端点：
  - POST   /api/chat/sessions
  - GET    /api/chat/sessions
  - GET    /api/chat/sessions/search
  - PUT    /api/chat/sessions/{session_id}
  - GET    /api/chat/sessions/{session_id}
  - GET    /api/supervision/session/{session_id}
  - DELETE /api/chat/sessions/{session_id}
  - POST   /api/chat/feedback
  - POST   /api/chat  （含 SSE 流式 / Response API / Chat Completions）
"""
from __future__ import annotations

import asyncio
import json
import os
import queue
import re
from datetime import datetime

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from scripts.advisor.api.crisis_detector import CrisisLevel
from scripts.advisor.api.supervision_agent import run_supervision_async

from ..core import state
from ..core.config import (
    ADVISOR_OUT, ASSESSMENT_DIR, CHAT_DIR,
    FRONTEND_CHAT_SAMPLES_DIR, PROJECT_ROOT,
)
from ..core.models import ChatFeedback, ChatRequest, SessionRenameRequest
from ..core.prompts import CHAT_SYSTEM_PROMPTS
from ..services import arena_service, chat_service, rag_service
from ..services.generator_service import (
    ensure_ollama_running, get_available_chat_backends, get_generator,
)

router = APIRouter()


@router.post("/api/chat/sessions")
async def create_session(
    agent_type: str = "neutral",
    mode: str = "listen",
    backend: str = "grok",
):
    """创建新会话"""
    session = chat_service.create_session(agent_type, mode, backend)
    return session


@router.get("/api/chat/sessions")
async def list_sessions():
    """列出所有会话"""
    return chat_service.list_sessions()


@router.get("/api/chat/sessions/search")
async def search_sessions(query: str = "", limit: int = 20):
    """搜索会话（标题匹配 + 全文匹配）"""
    if not query.strip():
        return {"query": query, "total": 0, "results": []}

    q = query.strip().lower()
    results = []

    for p in sorted(CHAT_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        title = (data.get("title") or "").lower()
        messages = data.get("messages") or []
        full_text = " ".join(m.get("content", "") for m in messages).lower()

        match_type = None
        excerpt = ""
        if q in title:
            match_type = "title"
            excerpt = data.get("title", "")
        if q in full_text:
            idx = full_text.find(q)
            start = max(0, idx - 40)
            end = min(len(full_text), idx + len(q) + 40)
            excerpt = ("..." if start > 0 else "") + full_text[start:end] + ("..." if end < len(full_text) else "")
            match_type = "title+fulltext" if match_type == "title" else "fulltext"

        if match_type:
            results.append({
                "id": data.get("id", p.stem),
                "title": data.get("title", "未命名"),
                "agent_type": data.get("agent_type", "neutral"),
                "mode": data.get("mode", "listen"),
                "backend": data.get("backend", ""),
                "message_count": len(messages),
                "created_at": data.get("created_at", ""),
                "updated_at": data.get("updated_at", ""),
                "match_type": match_type,
                "matched_excerpt": excerpt,
                "source": "chat",
                "communication_status": chat_service.chat_communication_status(data),
            })
        if len(results) >= limit:
            break

    # Arena sessions （导入 ARENA_SESSION_DIR 避免循环引用：延迟读取配置）
    from ..core.config import ARENA_SESSION_DIR
    for p in sorted(ARENA_SESSION_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        if len(results) >= limit:
            break
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        title = (data.get("title") or "").lower()
        rounds = data.get("rounds") or []
        full_text = " ".join(r.get("query", "") + " " + r.get("response_a", "") + " " + r.get("response_b", "") for r in rounds).lower()

        match_type = None
        excerpt = ""
        if q in title:
            match_type = "title"
            excerpt = data.get("title", "")
        if q in full_text:
            idx = full_text.find(q)
            start = max(0, idx - 40)
            end = min(len(full_text), idx + len(q) + 40)
            excerpt = ("..." if start > 0 else "") + full_text[start:end] + ("..." if end < len(full_text) else "")
            match_type = "title+fulltext" if match_type == "title" else "fulltext"

        if match_type:
            results.append({
                "id": data.get("id", p.stem),
                "title": data.get("title", "未命名"),
                "agent_type": "neutral",
                "mode": "arena",
                "backend": "",
                "message_count": len(rounds),
                "created_at": data.get("created_at", ""),
                "updated_at": data.get("updated_at", ""),
                "match_type": match_type,
                "matched_excerpt": excerpt,
                "source": "arena",
                "communication_status": arena_service.arena_communication_status(data),
            })

    if FRONTEND_CHAT_SAMPLES_DIR.is_dir():
        manifest = FRONTEND_CHAT_SAMPLES_DIR / "manifest.json"
        if manifest.exists():
            try:
                samples = json.loads(manifest.read_text(encoding="utf-8"))
                for s in samples:
                    name = (s.get("name") or "").lower()
                    if q in name:
                        results.append({
                            "id": s.get("id", ""),
                            "title": s.get("name", ""),
                            "agent_type": s.get("agent_type", "neutral"),
                            "mode": s.get("mode", "listen"),
                            "backend": "",
                            "message_count": s.get("message_count", 0),
                            "created_at": s.get("created_at", ""),
                            "updated_at": s.get("updated_at", ""),
                            "match_type": "title",
                            "matched_excerpt": s.get("name", ""),
                            "source": "sample",
                            "sample_file": s.get("file", ""),
                        })
            except Exception:
                pass

    return {"query": query, "total": len(results), "results": results[:limit]}


@router.put("/api/chat/sessions/{session_id}")
async def rename_session(session_id: str, req: SessionRenameRequest):
    """重命名会话"""
    session = chat_service.load_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    session["name"] = req.title
    session["updated_at"] = datetime.now().isoformat()
    chat_service.save_session(session)
    return {"message": "会话已重命名", "title": req.title}


@router.get("/api/chat/sessions/{session_id}")
async def get_session(session_id: str):
    """获取会话详情（含全部消息、supervision_log）"""
    session = chat_service.load_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    return session


@router.get("/api/supervision/session/{session_id}")
async def get_supervision_session(session_id: str):
    """§4.6 获取 Chat 会话的监督评估日志（对话进展分析专属入口）"""
    session = chat_service.load_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {
        "session_id": session_id,
        "supervision_log": session.get("supervision_log", []),
        "supervision_state": session.get("supervision_state", {}),
    }


@router.delete("/api/chat/sessions/{session_id}")
async def delete_session(session_id: str):
    """删除会话"""
    p = chat_service.session_path(session_id)
    if not p.exists():
        raise HTTPException(status_code=404, detail="会话不存在")
    p.unlink()
    return {"message": "会话已删除"}


@router.post("/api/chat/feedback")
async def chat_feedback(fb: ChatFeedback):
    """反馈闭环（维度4: 交互层面）— 收集用户对 RAG 检索质量的评价"""
    feedback_dir = ADVISOR_OUT / "feedback"
    feedback_dir.mkdir(parents=True, exist_ok=True)
    feedback_file = feedback_dir / "chat_feedback.jsonl"

    entry = {
        "session_id": fb.session_id,
        "message_index": fb.message_index,
        "rating": max(1, min(5, fb.rating)),
        "comment": fb.comment,
        "timestamp": datetime.now().isoformat(),
    }
    with open(feedback_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return {"status": "ok", "message": f"反馈已记录 (rating={entry['rating']})"}


@router.post("/api/chat")
async def chat(req: ChatRequest):
    """多轮 LLM 对话（支持流式，自动追加历史，注入 GraphRAG 上下文）"""

    # ── 四级危机检测（安全伦理 S2）──
    recent_user_msgs = []
    if req.session_id:
        sess = chat_service.load_session(req.session_id)
        if sess:
            recent_user_msgs = [
                m["content"] for m in sess.get("messages", [])
                if m["role"] == "user"
            ][-3:]
    crisis = state.crisis_detector.detect(req.message, recent_user_msgs)

    if crisis.level == CrisisLevel.RED:
        # 立即中断 AI，返回危机干预模板
        template = crisis.response_template or {}
        crisis_msg = template.get("message", "请立即拨打 400-161-9995（24小时心理援助热线）")
        session = chat_service.load_session(req.session_id) if req.session_id else None
        if not session:
            session = chat_service.create_session(req.agent_type, req.mode, req.backend)
        session["messages"].append({"role": "user", "content": req.message, "timestamp": datetime.now().isoformat()})
        session["messages"].append({
            "role": "assistant", "content": crisis_msg,
            "timestamp": datetime.now().isoformat(),
            "backend": "crisis_intervention", "crisis_level": "RED",
        })
        session["updated_at"] = datetime.now().isoformat()
        chat_service.save_session(session)
        # 归档到 crisis_archive
        archive_dir = PROJECT_ROOT / "advisor_out" / "crisis_archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        archive = {"session_id": session["id"], "message": req.message,
                    "matched": crisis.matched_keywords, "level": "RED",
                    "timestamp": datetime.now().isoformat()}
        with open(archive_dir / f"{session['id']}.json", "a", encoding="utf-8") as f:
            f.write(json.dumps(archive, ensure_ascii=False) + "\n")

        async def _crisis_stream():
            yield f"data: {json.dumps({'crisis_level': 'RED', 'content': crisis_msg, 'session_id': session['id']})}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(_crisis_stream(), media_type="text/event-stream")

    gen = get_generator(req.backend)
    system_prompt = CHAT_SYSTEM_PROMPTS.get(req.agent_type, {}).get(
        req.mode, CHAT_SYSTEM_PROMPTS["neutral"]["listen"]
    )

    # 危机级别 YELLOW/ORANGE：注入安全引导到 system prompt
    if crisis.level >= CrisisLevel.YELLOW:
        system_prompt += state.crisis_detector.get_safety_prompt_injection(crisis.level)

    # 交流前测评结果注入（仅在用户开启 inject_enabled 时注入）
    _assess_files = sorted(ASSESSMENT_DIR.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
    if _assess_files:
        try:
            with open(_assess_files[0], "r", encoding="utf-8") as _af:
                _assess_data = json.load(_af)
            if _assess_data.get("inject_enabled"):
                _ctx = _assess_data.get("context_injection", "")
                if _ctx:
                    system_prompt += "\n\n" + _ctx
        except Exception:
            pass

    # GraphRAG 上下文注入（仅在 use_rag=True 时启用）
    if req.use_rag:
        rag_top_k = 5 if req.mode == "consult" else 3
        rag_context = rag_service.build_rag_context(req.message, top_k=rag_top_k,
                                         max_preview=1000 if req.mode == "consult" else 500,
                                         agent_type=req.agent_type,
                                         use_knowledge=getattr(req, 'use_knowledge', True))
        if rag_context:
            rag_intro = (
                "\n\n以下是来自用户真实聊天记录的背景信息，请结合这些信息进行回复。"
                "注意：对话记录中 ME 指用户本人，OTHER 指对方。"
                "在你的回复中，请始终使用真实姓名，绝不要输出 ME、OTHER 这样的标记。\n\n"
            )
            if req.mode == "consult":
                rag_intro = (
                    "\n\n以下是来自用户真实聊天记录的详细背景信息。"
                    "请深度结合这些信息进行分析和建议，引用具体对话细节。"
                    "注意：对话记录中 ME 指用户本人，OTHER 指对方。"
                    "在你的回复中，请始终使用真实姓名，绝不要输出 ME、OTHER 这样的标记。\n\n"
                )
            system_prompt += rag_intro + rag_context

    # 加载或创建会话
    session = None
    if req.session_id:
        session = chat_service.load_session(req.session_id)
    if not session:
        session = chat_service.create_session(req.agent_type, req.mode, req.backend)

    # 自动生成会话标题（第一条消息的前 20 字）
    if not session.get("title"):
        session["title"] = req.message[:20] + ("..." if len(req.message) > 20 else "")

    # EFT 阶段注入
    if req.agent_type == "eft" and session.get("eft_stage"):
        _eft_stage_labels = {"exploration": "探索阶段（情绪镜像+深化）", "comforting": "安抚阶段（循环识别+需求澄清）", "action": "行动阶段（新脚本+强化）"}
        system_prompt += f"\n\n当前 EFT 阶段：{_eft_stage_labels.get(session['eft_stage'], session['eft_stage'])}，请优先使用对应阶段的对话动作。"
        if session.get("eft_round_count", 0) <= 3:
            system_prompt += "\n安全提醒：当前处于前 3 轮，请只做情绪镜像和深化，不要过早进入循环分析或行动建议。"

    # Bowen 第三方提及注入
    if req.agent_type == "bowen":
        _tp = session.get("bowen_third_parties", [])
        if _tp:
            system_prompt += f"\n\n【家庭系统上下文】用户提及的重要第三方：{', '.join(_tp)}。请关注可能的三角关系动力。"

    # ── 长对话记忆压缩：滑动窗口 + 摘要 ──
    history_summary, recent_history = chat_service.compress_history_messages(session)
    if history_summary:
        system_prompt += "\n\n" + history_summary

    # 构建多轮消息：system + 近期历史 + 当前
    raw_messages = [{"role": "system", "content": system_prompt}]
    for msg in recent_history:
        raw_messages.append({"role": msg["role"], "content": msg["content"]})
    raw_messages.append({"role": "user", "content": req.message})

    # 截断历史中过长的单条消息，节省 token 预算
    raw_messages = chat_service.truncate_history_messages(raw_messages)

    # 合并连续同角色消息
    messages = []
    for msg in raw_messages:
        if messages and msg["role"] == messages[-1]["role"] and msg["role"] != "system":
            messages[-1]["content"] += "\n" + msg["content"]
        else:
            messages.append(dict(msg))

    # 保存用户消息到会话
    session["messages"].append({
        "role": "user",
        "content": req.message,
        "timestamp": datetime.now().isoformat(),
    })

    # 本地 Qwen 自动启动 Ollama
    if req.backend == "qwen_local":
        if not ensure_ollama_running():
            session["updated_at"] = datetime.now().isoformat()
            chat_service.save_session(session)
            return StreamingResponse(
                iter([f"data: {json.dumps({'error': 'Ollama 服务启动失败，请检查是否已安装 ollama', 'session_id': session['id']})}\n\n"]),
                media_type="text/event-stream",
            )

    if req.stream and gen.base_url:
        collected_content = []
        _think_re = re.compile(r'<think>.*?</think>', re.DOTALL)
        in_think = False

        def _save_and_finalize(full_reply: str):
            """保存助手回复到会话，并提取关键事实到长期记忆"""
            violations = state.crisis_detector.check_response_prohibited(full_reply)
            if violations:
                for v in violations:
                    word = v.split("] ", 1)[-1] if "] " in v else v
                    full_reply = full_reply.replace(word, "（此处表述不当，已移除）")
            session["messages"].append({
                "role": "assistant",
                "content": full_reply,
                "timestamp": datetime.now().isoformat(),
                "backend": req.backend,
                "model": gen.model,
            })
            new_facts = chat_service.extract_memory_facts(full_reply)
            if new_facts:
                existing = session.get("memory_facts", [])
                existing.extend(new_facts)
                session["memory_facts"] = existing[-20:]
            session["updated_at"] = datetime.now().isoformat()
            session["agent_type"] = req.agent_type
            session["mode"] = req.mode
            session["backend"] = req.backend
            if req.agent_type == "eft":
                rc = session.get("eft_round_count", 0) + 1
                session["eft_round_count"] = rc
                if rc <= 3:
                    session["eft_stage"] = "exploration"
                elif rc <= 6:
                    session["eft_stage"] = "comforting"
                else:
                    session["eft_stage"] = "action"
            if req.agent_type == "bowen":
                _bowen_third_parties = session.get("bowen_third_parties", [])
                _tp_keywords = ["爸", "妈", "父亲", "母亲", "父母", "公婆", "婆婆", "公公", "岳父", "岳母", "前任", "前男友", "前女友", "孩子", "儿子", "女儿", "朋友", "闺蜜", "兄弟", "同事", "领导"]
                for _kw in _tp_keywords:
                    if _kw in req.message and _kw not in _bowen_third_parties:
                        _bowen_third_parties.append(_kw)
                session["bowen_third_parties"] = _bowen_third_parties
                if len(_bowen_third_parties) > 0:
                    session["bowen_triangles_detected"] = session.get("bowen_triangles_detected", 0) + 1
            chat_service.save_session(session)

        async def _stream_response_api():
            """GPT-5.2 Response API SSE 流式"""
            url = f"{gen.base_url.rstrip('/')}/responses"
            headers = {
                "Authorization": f"Bearer {gen.api_key}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            }
            system_text = ""
            history_parts = []
            current_user_msg = ""
            for i, msg in enumerate(messages):
                if msg["role"] == "system":
                    system_text = msg["content"]
                elif msg["role"] == "assistant":
                    history_parts.append(f"[你之前的回复]\n{msg['content'][:2000]}")
                elif msg["role"] == "user":
                    if i < len(messages) - 1:
                        history_parts.append(f"[用户之前的消息]\n{msg['content']}")
                    else:
                        current_user_msg = msg["content"]
            if history_parts:
                system_text += "\n\n【对话历史】\n" + "\n\n".join(history_parts)
            api_input = [
                {"role": "system", "content": [{"type": "input_text", "text": system_text}]},
                {"role": "user", "content": [{"type": "input_text", "text": current_user_msg}]},
            ]
            payload = {
                "model": gen.model,
                "input": api_input,
                "store": False,
                "stream": True,
            }
            prefix = gen._ENV_PREFIX.get(gen.backend, '')
            effort = os.environ.get(f'{prefix}_REASONING_EFFORT', '')
            if effort:
                payload["reasoning"] = {"effort": effort}

            timeout = httpx.Timeout(connect=30.0, read=300.0, write=30.0, pool=30.0)
            try:
                with httpx.Client(timeout=timeout) as client:
                    with client.stream("POST", url, headers=headers, json=payload) as response:
                        response.raise_for_status()
                        current_event = None
                        for line in response.iter_lines():
                            if not line:
                                current_event = None
                                continue
                            if line.startswith("event:"):
                                current_event = line.split(":", 1)[1].strip()
                                continue
                            if not line.startswith("data:"):
                                continue
                            data_str = line.split(":", 1)[1].strip()
                            if data_str == "[DONE]":
                                break
                            try:
                                obj = json.loads(data_str)
                            except json.JSONDecodeError:
                                continue
                            event_type = obj.get("type") or current_event
                            if event_type == "response.output_text.delta":
                                delta = obj.get("delta", "")
                                if delta:
                                    collected_content.append(delta)
                                    yield f"data: {json.dumps({'content': delta})}\n\n"
                            elif event_type in ("response.completed", "response.done"):
                                break

                full_reply = ''.join(collected_content)
                if not full_reply.strip():
                    full_reply = "抱歉，模型未返回有效内容，请切换其他后端重试。"
                    yield f"data: {json.dumps({'content': full_reply})}\n\n"
                _save_and_finalize(full_reply)
                asyncio.create_task(asyncio.to_thread(run_supervision_async, session["id"], CHAT_DIR))
                yield f"data: {json.dumps({'session_id': session['id']})}\n\n"
                yield "data: [DONE]\n\n"
            except Exception as e:
                err_msg = str(e)
                if '503' in err_msg or 'NO_AVAILABLE_TOKEN' in err_msg:
                    err_msg = f"{req.backend} 模型当前不可用 (额度耗尽/服务异常)"
                else:
                    err_msg = f"{req.backend} 调用失败: {err_msg[:150]}"
                alts = get_available_chat_backends(exclude=req.backend)
                session["updated_at"] = datetime.now().isoformat()
                chat_service.save_session(session)
                yield f"data: {json.dumps({'error': err_msg, 'failed_backend': req.backend, 'available_backends': alts, 'session_id': session['id']})}\n\n"

        async def _stream_chat_completions():
            """标准 Chat Completions 流式（Claude/Grok/DeepSeek/Qwen 等）"""
            nonlocal in_think
            try:
                _THINK_TAG_BACKENDS = {"qwen_cloud", "qwen_local", "deepseek", "glm", "grok"}
                is_thinking = (
                    req.backend in _THINK_TAG_BACKENDS
                    and "think" in gen.model.lower()
                )
                _is_any_thinking = any(p in gen.model.lower() for p in ['think', 'reason', 'o1', 'o3', 'o4'])
                effective_max = 16384 if _is_any_thinking else min(gen.max_tokens, 16384)
                kwargs = dict(
                    model=gen.model,
                    messages=messages,
                    stream=True,
                    max_tokens=effective_max,
                )
                if not is_thinking and not _is_any_thinking:
                    if gen.temperature is not None:
                        kwargs["temperature"] = gen.temperature

                token_queue: queue.Queue = queue.Queue()

                def _run_sync_stream():
                    """在线程中执行同步 OpenAI 流式调用"""
                    try:
                        stream = gen.client.chat.completions.create(**kwargs)
                        for chunk in stream:
                            delta = chunk.choices[0].delta if chunk.choices else None
                            if delta:
                                rc = getattr(delta, 'reasoning_content', None)
                                if rc:
                                    token_queue.put(('thinking', rc))
                                    continue
                                token = delta.content
                                if token:
                                    token_queue.put(('token', token))
                        token_queue.put(('done', None))
                    except Exception as exc:
                        token_queue.put(('error', str(exc)))

                loop = asyncio.get_event_loop()
                loop.run_in_executor(None, _run_sync_stream)

                raw_tokens = []
                got_first_content = False
                while True:
                    try:
                        msg_type, msg_val = token_queue.get_nowait()
                    except queue.Empty:
                        await asyncio.sleep(0.05)
                        continue

                    if msg_type == 'done':
                        break
                    if msg_type == 'error':
                        raise Exception(msg_val)

                    if msg_type == 'thinking':
                        if not in_think:
                            in_think = True
                        yield f"data: {json.dumps({'thinking': msg_val})}\n\n"
                        continue

                    token = msg_val
                    raw_tokens.append(token)

                    if is_thinking and not got_first_content and not in_think and '<think>' not in token:
                        if '</think>' not in token:
                            in_think = True
                            yield f"data: {json.dumps({'thinking': token})}\n\n"
                            continue

                    got_first_content = True

                    if '<think>' in token:
                        in_think = True
                        before = token.split('<think>', 1)[0]
                        if before.strip():
                            collected_content.append(before)
                            yield f"data: {json.dumps({'content': before})}\n\n"
                        think_part = token.split('<think>', 1)[1]
                        if '</think>' in think_part:
                            in_think = False
                            think_text = think_part.split('</think>', 1)[0]
                            if think_text.strip():
                                yield f"data: {json.dumps({'thinking': think_text})}\n\n"
                            yield f"data: {json.dumps({'thinking_done': True})}\n\n"
                            after = think_part.split('</think>', 1)[1]
                            if after.strip():
                                collected_content.append(after)
                                yield f"data: {json.dumps({'content': after})}\n\n"
                        elif think_part.strip():
                            yield f"data: {json.dumps({'thinking': think_part})}\n\n"
                        continue
                    if in_think:
                        if '</think>' in token:
                            in_think = False
                            before_end = token.split('</think>', 1)[0]
                            if before_end.strip():
                                yield f"data: {json.dumps({'thinking': before_end})}\n\n"
                            yield f"data: {json.dumps({'thinking_done': True})}\n\n"
                            after = token.split('</think>', 1)[-1]
                            if after.strip():
                                collected_content.append(after)
                                yield f"data: {json.dumps({'content': after})}\n\n"
                        else:
                            yield f"data: {json.dumps({'thinking': token})}\n\n"
                        continue

                    collected_content.append(token)
                    yield f"data: {json.dumps({'content': token})}\n\n"

                full_reply = ''.join(collected_content)
                if not full_reply.strip() and raw_tokens:
                    raw_full = ''.join(raw_tokens)
                    full_reply = _think_re.sub('', raw_full).strip()
                    full_reply = re.sub(r'<think>.*', '', full_reply, flags=re.DOTALL).strip()
                    if full_reply:
                        yield f"data: {json.dumps({'content': full_reply})}\n\n"

                if not full_reply.strip():
                    full_reply = "抱歉，模型未返回有效内容，请切换其他后端重试。"
                    yield f"data: {json.dumps({'content': full_reply})}\n\n"

                _save_and_finalize(full_reply)
                asyncio.create_task(asyncio.to_thread(run_supervision_async, session["id"], CHAT_DIR))
                yield f"data: {json.dumps({'session_id': session['id']})}\n\n"
                yield "data: [DONE]\n\n"
            except Exception as e:
                err_msg = str(e)
                err_code = ''
                if '503' in err_msg or 'NO_AVAILABLE_TOKEN' in err_msg:
                    err_code = '503'
                    err_msg = f"{req.backend} 模型当前不可用 (额度耗尽/服务异常)"
                elif '429' in err_msg:
                    err_code = '429'
                    err_msg = f"{req.backend} API 限流，请稍后重试"
                elif '400' in err_msg:
                    err_code = '400'
                    err_msg = f"{req.backend} 请求格式错误，可能不支持当前参数"
                elif '401' in err_msg or '403' in err_msg:
                    err_code = '401'
                    err_msg = f"{req.backend} 认证失败，API key 可能已过期"
                else:
                    err_msg = f"{req.backend} 调用失败: {err_msg[:150]}"
                alts = get_available_chat_backends(exclude=req.backend)
                session["updated_at"] = datetime.now().isoformat()
                chat_service.save_session(session)
                yield f"data: {json.dumps({'error': err_msg, 'error_code': err_code, 'failed_backend': req.backend, 'available_backends': alts, 'session_id': session['id']})}\n\n"

        # 根据后端选择流式方案
        if gen._use_response_api:
            stream_fn = _stream_response_api()
        else:
            stream_fn = _stream_chat_completions()

        return StreamingResponse(stream_fn, media_type="text/event-stream")
    else:
        try:
            full_prompt = f"{system_prompt}\n\n用户：{req.message}"
            result = gen._call_api(full_prompt)
            if result and '<think>' in result:
                result = re.sub(r'<think>.*?</think>', '', result, flags=re.DOTALL).strip()
                if not result:
                    result = re.sub(r'<think>.*', '', result, flags=re.DOTALL).strip()
            session["messages"].append({
                "role": "assistant",
                "content": result,
                "timestamp": datetime.now().isoformat(),
                "backend": req.backend,
                "model": gen.model,
            })
            session["updated_at"] = datetime.now().isoformat()
            chat_service.save_session(session)
            asyncio.create_task(asyncio.to_thread(run_supervision_async, session["id"], CHAT_DIR))
            return {
                "content": result,
                "model": gen.model,
                "backend": gen.backend,
                "session_id": session["id"],
            }
        except Exception as e:
            session["updated_at"] = datetime.now().isoformat()
            chat_service.save_session(session)
            raise HTTPException(status_code=500, detail=str(e))
