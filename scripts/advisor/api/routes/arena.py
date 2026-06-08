"""routes/arena.py — Arena 双镜对比 API（S3）

包含 11 个端点：
  - POST   /api/arena/chat
  - POST   /api/arena/vote
  - GET    /api/arena/sessions
  - PUT    /api/arena/sessions/{session_id}
  - DELETE /api/arena/sessions/{session_id}
  - GET    /api/arena/session/{session_id}
  - GET    /api/arena/stats
  - GET    /api/arena/leaderboard
  - GET    /api/arena/summary
  - GET    /api/arena/query-stats
  - GET    /api/arena/annotator-stats
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime

from fastapi import APIRouter, HTTPException

from scripts.advisor.api.crisis_detector import CrisisLevel
from scripts.advisor.api.supervision_agent import run_supervision_arena_async

from ..core import state
from ..core.config import (
    ARENA_DIR, ARENA_SESSION_DIR, ASSESSMENT_DIR,
    BATTLES_FILE, PROJECT_ROOT,
)
from ..core.models import (
    ArenaChatRequest, ArenaVoteRequest, SessionRenameRequest,
)
from ..core.prompts import CHAT_SYSTEM_PROMPTS
from ..services import arena_service, chat_service, rag_service

router = APIRouter()


@router.post("/api/arena/chat")
async def arena_chat(req: ArenaChatRequest):
    """多轮 Arena 对话：同一输入同时发送给 A/B，双路并发返回"""
    if req.arena_session_id:
        session = arena_service.load_arena_session(req.arena_session_id)
        if not session:
            raise HTTPException(404, f"Arena session {req.arena_session_id} not found")
    else:
        session = arena_service.create_arena_session(
            req.contestant_a.model_dump(),
            req.contestant_b.model_dump(),
            req.mode,
            req.use_rag,
        )

    recent_user_msgs = [r.get("query", "") for r in session.get("rounds", [])][-3:]
    crisis = state.crisis_detector.detect(req.message, recent_user_msgs)

    agent_type_a = session["contestant_a"].get("agent_type", "neutral")
    agent_type_b = session["contestant_b"].get("agent_type", "neutral")
    mode_key = "consult" if req.mode == "deep" else "listen"
    system_a = CHAT_SYSTEM_PROMPTS.get(agent_type_a, {}).get(mode_key, "")
    system_b = CHAT_SYSTEM_PROMPTS.get(agent_type_b, {}).get(mode_key, "")
    if crisis.level >= CrisisLevel.YELLOW:
        guard = state.crisis_detector.get_safety_prompt_injection(crisis.level)
        system_a += guard
        system_b += guard

    _assess_files = sorted(ASSESSMENT_DIR.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
    if _assess_files:
        try:
            with open(_assess_files[0], "r", encoding="utf-8") as _af:
                _assess_data = json.load(_af)
            if _assess_data.get("inject_enabled"):
                _assess_ctx = _assess_data.get("context_injection", "")
                if _assess_ctx:
                    system_a += "\n\n" + _assess_ctx
                    system_b += "\n\n" + _assess_ctx
        except Exception:
            pass

    if session.get("use_rag", True):
        rag_ctx = rag_service.build_rag_context(req.message, top_k=3, max_preview=500,
                                     agent_type=session["contestant_a"].get("agent_type", ""),
                                     use_knowledge=req.use_knowledge if hasattr(req, 'use_knowledge') else True)
        if rag_ctx:
            rag_suffix = (
                "\n\n以下是来自用户真实聊天记录的背景信息，请结合这些信息进行回复。"
                "注意：对话记录中 ME 指用户本人，OTHER 指对方。"
                "在你的回复中，请始终使用真实姓名，绝不要输出 ME、OTHER 这样的标记。\n\n"
            ) + rag_ctx[:800]
            system_a += rag_suffix
            system_b += rag_suffix

    history_a, history_b = [], []
    all_rounds = session.get("rounds", [])
    max_recent = 12
    old_rounds = all_rounds[:-max_recent] if len(all_rounds) > max_recent else []
    recent_rounds = all_rounds[-max_recent:] if len(all_rounds) > max_recent else all_rounds

    if old_rounds:
        summary_lines = []
        for rd in old_rounds:
            summary_lines.append(f"- 用户问: {rd['query'][:60]}")
        memory_summary = "\n\n【早期对话摘要】\n" + "\n".join(summary_lines[-8:])
        system_a += memory_summary
        system_b += memory_summary

    memory_facts = session.get("memory_facts", [])
    if memory_facts:
        facts_text = "\n\n【已确认的关键信息】\n" + "\n".join(f"- {f}" for f in memory_facts[-10:])
        system_a += facts_text
        system_b += facts_text

    for rd in recent_rounds:
        history_a.append({"role": "user", "content": rd["query"]})
        history_a.append({"role": "assistant", "content": rd["response_a"]})
        history_b.append({"role": "user", "content": rd["query"]})
        history_b.append({"role": "assistant", "content": rd["response_b"]})
    history_a.append({"role": "user", "content": req.message})
    history_b.append({"role": "user", "content": req.message})

    if crisis.level == CrisisLevel.RED:
        template = crisis.response_template or {}
        crisis_msg = template.get("message", "请立即拨打 400-161-9995（24小时心理援助热线）")
        new_round = {
            "round_index": len(session["rounds"]),
            "query": req.message,
            "response_a": crisis_msg,
            "response_b": crisis_msg,
            "vote": None,
            "scores": None,
            "crisis_level": "RED",
            "timestamp": datetime.now().isoformat(),
        }
        session["rounds"].append(new_round)
        if not session.get("title"):
            session["title"] = req.message[:20] + ("..." if len(req.message) > 20 else "")
        session["updated_at"] = datetime.now().isoformat()
        arena_service.save_arena_session(session)
        archive_dir = PROJECT_ROOT / "advisor_out" / "crisis_archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        archive = {
            "session_id": session["id"],
            "message": req.message,
            "matched": crisis.matched_keywords,
            "level": "RED",
            "timestamp": datetime.now().isoformat(),
            "source": "arena",
        }
        with open(archive_dir / f"{session['id']}.json", "a", encoding="utf-8") as f:
            f.write(json.dumps(archive, ensure_ascii=False) + "\n")
        return {
            "arena_session_id": session["id"],
            "round_index": new_round["round_index"],
            "response_a": crisis_msg,
            "response_b": crisis_msg,
            "crisis_level": "RED",
            "requires_vote": False,
        }

    ca = session["contestant_a"]
    cb = session["contestant_b"]
    loop = asyncio.get_event_loop()
    resp_a, resp_b = await asyncio.gather(
        loop.run_in_executor(None, lambda: arena_service.arena_generate_one(
            ca["backend"], ca.get("model", ""), ca.get("agent_type", "neutral"),
            system_a, history_a)),
        loop.run_in_executor(None, lambda: arena_service.arena_generate_one(
            cb["backend"], cb.get("model", ""), cb.get("agent_type", "neutral"),
            system_b, history_b)),
    )
    resp_a = arena_service.sanitize_with_crisis_guard(resp_a)
    resp_b = arena_service.sanitize_with_crisis_guard(resp_b)

    new_round = {
        "round_index": len(session["rounds"]),
        "query": req.message,
        "response_a": resp_a,
        "response_b": resp_b,
        "vote": None,
        "scores": None,
        "crisis_level": crisis.level.name,
        "timestamp": datetime.now().isoformat(),
    }
    session["rounds"].append(new_round)

    new_facts = chat_service.extract_memory_facts(resp_a) + chat_service.extract_memory_facts(resp_b)
    if new_facts:
        existing = session.get("memory_facts", [])
        existing.extend(new_facts)
        session["memory_facts"] = existing[-20:]

    if not session.get("title"):
        session["title"] = req.message[:20] + ("..." if len(req.message) > 20 else "")
    session["updated_at"] = datetime.now().isoformat()
    arena_service.save_arena_session(session)

    asyncio.create_task(asyncio.to_thread(run_supervision_arena_async, session["id"], ARENA_SESSION_DIR))

    return {
        "arena_session_id": session["id"],
        "round_index": new_round["round_index"],
        "response_a": resp_a,
        "response_b": resp_b,
        "crisis_level": crisis.level.name,
        "requires_vote": True,
    }


@router.post("/api/arena/vote")
async def arena_vote(req: ArenaVoteRequest):
    """提交某轮的投票与五维评分（1-10），写入 session + battles.jsonl"""
    session = arena_service.load_arena_session(req.arena_session_id)
    if not session:
        raise HTTPException(404, f"Arena session {req.arena_session_id} not found")

    idx = req.round_index if req.round_index >= 0 else len(session["rounds"]) - 1
    if idx < 0 or idx >= len(session["rounds"]):
        raise HTTPException(400, "Invalid round_index")
    rd = session["rounds"][idx]

    scores = {}
    if req.scores_a:
        scores["a"] = req.scores_a.model_dump()
    if req.scores_b:
        scores["b"] = req.scores_b.model_dump()

    rd["vote"] = req.vote
    rd["scores"] = scores if scores else None
    rd["remark"] = req.remark.strip() if req.remark else ""
    session["updated_at"] = datetime.now().isoformat()
    arena_service.save_arena_session(session)

    entry = {
        "arena_session_id": session["id"],
        "round_index": idx,
        "query": rd["query"],
        "mode": session.get("mode", "model"),
        "contestant_a": session["contestant_a"],
        "contestant_b": session["contestant_b"],
        "response_a": rd["response_a"],
        "response_b": rd["response_b"],
        "vote": req.vote,
        "scores": scores if scores else None,
        "remark": rd.get("remark", ""),
        "use_rag": session.get("use_rag", True),
        "timestamp": datetime.now().isoformat(),
    }
    with open(BATTLES_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return {
        "status": "ok",
        "message": "投票已记录",
        "contestant_a": session["contestant_a"],
        "contestant_b": session["contestant_b"],
    }


@router.get("/api/arena/sessions")
async def list_arena_sessions():
    """列出所有 Arena 会话摘要（侧边栏用）"""
    sessions = []
    for p in sorted(ARENA_SESSION_DIR.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True):
        try:
            with open(p, "r", encoding="utf-8") as f:
                s = json.load(f)
            sessions.append({
                "id": s["id"],
                "title": s.get("title", ""),
                "rounds": len(s.get("rounds", [])),
                "communication_status": arena_service.arena_communication_status(s),
                "time": datetime.fromisoformat(s.get("updated_at", s.get("created_at", ""))).strftime("%m-%d %H:%M") if s.get("updated_at") or s.get("created_at") else "",
            })
        except (json.JSONDecodeError, KeyError, ValueError):
            continue
    return sessions


@router.put("/api/arena/sessions/{session_id}")
async def rename_arena_session(session_id: str, req: SessionRenameRequest):
    """重命名 Arena 会话"""
    session = arena_service.load_arena_session(session_id)
    if not session:
        raise HTTPException(404, f"Arena session {session_id} not found")
    session["title"] = req.title
    session["updated_at"] = datetime.now().isoformat()
    arena_service.save_arena_session(session)
    return {"message": "会话已重命名", "title": req.title}


@router.delete("/api/arena/sessions/{session_id}")
async def delete_arena_session(session_id: str):
    """删除 Arena 会话"""
    p = arena_service.arena_session_path(session_id)
    if not p.exists():
        raise HTTPException(status_code=404, detail="Arena session not found")
    p.unlink()
    return {"message": "会话已删除"}


@router.get("/api/arena/session/{session_id}")
async def get_arena_session(session_id: str):
    """获取 Arena 会话详情（含全部轮次）"""
    session = arena_service.load_arena_session(session_id)
    if not session:
        raise HTTPException(404, f"Arena session {session_id} not found")
    return session


@router.get("/api/arena/stats")
async def arena_stats(mode: str = ""):
    """Elo 排名（总榜 + 五维分榜）+ 置信区间 + 对局数。mode 可选: model, agent_type, perspective, 空=全部"""
    current_count = 0
    if BATTLES_FILE.exists():
        with open(BATTLES_FILE, "r", encoding="utf-8") as f:
            current_count = sum(1 for line in f if line.strip())
    cache_key = mode or "all"
    last_count = state.elo_battle_counts.get(cache_key, 0)
    elo_path = ARENA_DIR / f"elo_ratings{'_' + mode if mode else ''}.json"
    if current_count > 0 and (current_count != last_count or not elo_path.exists()):
        result = arena_service.compute_elo_ratings(mode_filter=mode)
        state.elo_battle_counts[cache_key] = current_count
        state.elo_cache[cache_key] = result
        return result
    if cache_key in state.elo_cache:
        return state.elo_cache[cache_key]
    if elo_path.exists():
        with open(elo_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"updated_at": None, "total_battles": 0, "ratings": {}, "mode": cache_key}


@router.get("/api/arena/leaderboard")
async def arena_leaderboard(mode: str = "model"):
    """按模式筛选排行榜"""
    stats = await arena_stats()
    return stats


@router.get("/api/arena/summary")
async def arena_summary():
    """对话摘要：统计用户偏好"""
    if not BATTLES_FILE.exists():
        return {"total": 0, "preference": {}}
    wins: dict[str, int] = {}
    total = 0
    with open(BATTLES_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                b = json.loads(line)
            except json.JSONDecodeError:
                continue
            total += 1
            vote = b.get("vote", "")
            def mk(c: dict) -> str:
                return c.get("model") or c.get("backend", "?")
            if vote == "a_win":
                k = mk(b.get("contestant_a", {}))
                wins[k] = wins.get(k, 0) + 1
            elif vote == "b_win":
                k = mk(b.get("contestant_b", {}))
                wins[k] = wins.get(k, 0) + 1
    return {"total": total, "preference": wins}


# ── Query 分层统计 ────────────────────────────────────────────

_QUERY_CATEGORIES = {
    "emotional_support": ["难过", "伤心", "焦虑", "害怕", "紧张", "压力", "崩溃", "抑郁", "孤独", "失眠", "委屈", "哭", "心情", "情绪", "不开心", "烦"],
    "conflict_analysis": ["吵架", "冲突", "矛盾", "争吵", "分歧", "生气", "愤怒", "冷战", "冷暴力", "闹", "不理", "翻脸", "怼"],
    "advice_request": ["怎么办", "该怎么", "建议", "怎么改善", "如何", "应该", "帮我", "能不能", "要不要", "值不值"],
    "relationship_exploration": ["喜欢", "暧昧", "表白", "恋爱", "感情", "约会", "相处", "交往", "追", "聊天", "话题"],
}


def _classify_query(query: str) -> str:
    q = query.lower()
    scores = {}
    for cat, keywords in _QUERY_CATEGORIES.items():
        scores[cat] = sum(1 for kw in keywords if kw in q)
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "general"


@router.get("/api/arena/query-stats")
async def arena_query_stats():
    """Query 分层统计：按问题类型统计各模型表现"""
    if not BATTLES_FILE.exists():
        return {"categories": {}, "total": 0}

    cat_data: dict[str, dict[str, dict]] = {}

    with open(BATTLES_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                b = json.loads(line)
            except json.JSONDecodeError:
                continue

            cat = _classify_query(b.get("query", ""))
            if cat not in cat_data:
                cat_data[cat] = {}

            def model_key(c: dict) -> str:
                return c.get("model") or c.get("backend", "?")

            ka = model_key(b.get("contestant_a", {}))
            kb = model_key(b.get("contestant_b", {}))
            for k in [ka, kb]:
                if k not in cat_data[cat]:
                    cat_data[cat][k] = {"battles": 0, "wins": 0}

            cat_data[cat][ka]["battles"] += 1
            cat_data[cat][kb]["battles"] += 1
            vote = b.get("vote", "tie")
            if vote == "a_win":
                cat_data[cat][ka]["wins"] += 1
            elif vote == "b_win":
                cat_data[cat][kb]["wins"] += 1

    total = sum(sum(m["battles"] for m in models.values()) // 2 for models in cat_data.values())

    categories = {}
    cat_labels = {
        "emotional_support": "情绪支持",
        "conflict_analysis": "冲突分析",
        "advice_request": "建议请求",
        "relationship_exploration": "关系探索",
        "general": "一般对话",
    }
    for cat, models in cat_data.items():
        categories[cat] = {
            "label": cat_labels.get(cat, cat),
            "battles": sum(m["battles"] for m in models.values()) // 2,
            "models": {k: {"battles": v["battles"], "wins": v["wins"],
                          "win_rate": round(v["wins"] / max(v["battles"], 1) * 100, 1)}
                      for k, v in sorted(models.items(), key=lambda x: -x[1]["wins"])},
        }

    return {"categories": categories, "total": total}


# ── am-ELO: Annotator Ability Modeling ─────────────────────────

@router.get("/api/arena/annotator-stats")
async def arena_annotator_stats():
    """am-ELO 标注者一致性分析"""
    return arena_service.compute_annotator_consistency()
