"""services/arena_service.py — Arena 双镜对比（S3）

从 server.py 迁移（Step 4）：
  - `_arena_communication_status`    → `arena_communication_status`
  - `_arena_session_path`            → `arena_session_path`
  - `_load_arena_session`            → `load_arena_session`
  - `_save_arena_session`            → `save_arena_session`  （§7.5 原子写入）
  - `_create_arena_session`          → `create_arena_session`
  - `_arena_generate_one`            → `arena_generate_one`
  - `_sanitize_with_crisis_guard`    → `sanitize_with_crisis_guard`
  - `_compute_elo_ratings`           → `compute_elo_ratings`
  - `_compute_annotator_consistency` → `compute_annotator_consistency`

依赖：
  - core/state.py：state.crisis_detector
  - core/config.py：ARENA_DIR / ARENA_SESSION_DIR / BATTLES_FILE
  - services/generator_service.py：get_generator
"""
from __future__ import annotations

import json
import math
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..core import state
from ..core.config import ARENA_DIR, ARENA_SESSION_DIR, BATTLES_FILE
from .generator_service import get_generator


# ══════════════════════════════════════════════════════════════
# Arena 会话 CRUD
# ══════════════════════════════════════════════════════════════

def arena_communication_status(session: dict) -> str:
    rounds = session.get("rounds") or []
    if not rounds:
        return "未开始"
    last = rounds[-1]
    if last.get("crisis_level") == "RED":
        return "危机干预"
    if last.get("vote"):
        return "已评分"
    if last.get("response_a") or last.get("response_b"):
        return "待评分"
    return "进行中"


def arena_session_path(sid: str) -> Path:
    return ARENA_SESSION_DIR / f"{sid}.json"


def load_arena_session(sid: str) -> Optional[dict]:
    p = arena_session_path(sid)
    if not p.exists():
        return None
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def save_arena_session(session: dict):
    """原子写入 Arena 会话（§7.5）：tmp + os.replace 防止半写文件。"""
    p = arena_session_path(session["id"])
    tmp = p.with_suffix(p.suffix + '.tmp')
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(session, f, ensure_ascii=False, indent=2)
    os.replace(str(tmp), str(p))


def create_arena_session(contestant_a: dict, contestant_b: dict, mode: str, use_rag: bool) -> dict:
    session = {
        "id": f"arena-{uuid.uuid4().hex[:8]}",
        "contestant_a": contestant_a,
        "contestant_b": contestant_b,
        "mode": mode,
        "use_rag": use_rag,
        "rounds": [],
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
    }
    save_arena_session(session)
    return session


# ══════════════════════════════════════════════════════════════
# Arena 生成 + 危机词过滤
# ══════════════════════════════════════════════════════════════

def arena_generate_one(backend: str, model: str, agent_type: str,
                       system: str, messages: list[dict]) -> str:
    """同步生成单条 Arena 回复（支持多轮历史）"""
    gen = get_generator(backend, model or None)
    kwargs = dict(
        model=gen.model,
        messages=[{"role": "system", "content": system}] + messages,
        max_tokens=gen.max_tokens,
    )
    if gen.temperature is not None and "think" not in gen.model.lower():
        kwargs["temperature"] = gen.temperature
    try:
        if gen.base_url:
            kwargs["stream"] = True
            stream = gen.client.chat.completions.create(**kwargs)
            collected = []
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    collected.append(chunk.choices[0].delta.content)
            result = "".join(collected)
        else:
            resp = gen.client.chat.completions.create(**kwargs)
            result = resp.choices[0].message.content or ""
        if result and "<think>" in result:
            result = re.sub(r"<think>.*?</think>", "", result, flags=re.DOTALL).strip()
        return result or ""
    except Exception as e:
        return f"（生成失败：{e}）"


def sanitize_with_crisis_guard(text: str) -> str:
    """使用 crisis_detector 过滤输出中的违禁词"""
    if not text:
        return text
    violations = state.crisis_detector.check_response_prohibited(text)
    for v in violations:
        word = v.split("] ", 1)[-1] if "] " in v else v
        text = text.replace(word, "（此处表述不当，已移除）")
    return text


# ══════════════════════════════════════════════════════════════
# Elo 评分（Bradley-Terry MLE）
# ══════════════════════════════════════════════════════════════

def compute_elo_ratings(mode_filter: str = "") -> dict:
    """Bradley-Terry MLE 全量重算 Elo（主 Elo + 五维 Elo），可按 mode 过滤"""
    if not BATTLES_FILE.exists():
        return {"updated_at": None, "total_battles": 0, "ratings": {}, "mode": mode_filter or "all"}

    # ── 2026-04-18：前端已合并"流派对比"与"视角碰撞"为统一的"视角碰撞"模式 ──
    # 统计桶对应关系：
    #   mode_filter="perspective"  → 纳入历史 agent_type 与新 perspective 的所有对局（按 agent_type 排名）
    #   mode_filter="agent_type"   → 仅保留老字段查询兼容性，等价于 "perspective"
    #   mode_filter="model"        → 仅模型对决
    #   mode_filter=""             → 全部
    def _mode_match(battle_mode: str) -> bool:
        if not mode_filter:
            return True
        if mode_filter in ("perspective", "agent_type"):
            return battle_mode in ("perspective", "agent_type")
        return battle_mode == mode_filter

    battles = []
    with open(BATTLES_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    b = json.loads(line)
                    if not _mode_match(b.get("mode", "model")):
                        continue
                    battles.append(b)
                except json.JSONDecodeError:
                    continue

    if not battles:
        return {"updated_at": None, "total_battles": 0, "ratings": {}, "mode": mode_filter or "all"}

    def model_key(c: dict) -> str:
        # 视角碰撞桶（含历史 agent_type）：按 agent_type 排名，跨模型归并
        if mode_filter in ("agent_type", "perspective"):
            return c.get("agent_type", "neutral")
        return f"{c.get('backend', '?')}::{c.get('model', '?')}"

    players: dict[str, dict] = {}
    dims = ["empathy", "depth", "practicality", "professionalism", "fluency"]

    for b in battles:
        ka = model_key(b.get("contestant_a", {}))
        kb = model_key(b.get("contestant_b", {}))
        for k in [ka, kb]:
            if k not in players:
                players[k] = {"elo": 1000.0, "battles": 0, "wins": 0, "losses": 0, "ties": 0,
                              **{d: 1000.0 for d in dims}, "contestant": {}}
        players[ka]["contestant"] = b.get("contestant_a", {})
        players[kb]["contestant"] = b.get("contestant_b", {})

        vote = b.get("vote", "tie")
        players[ka]["battles"] += 1
        players[kb]["battles"] += 1
        if vote == "a_win":
            players[ka]["wins"] += 1; players[kb]["losses"] += 1
        elif vote == "b_win":
            players[kb]["wins"] += 1; players[ka]["losses"] += 1
        else:
            players[ka]["ties"] += 1; players[kb]["ties"] += 1

    def bt_mle(win_matrix: dict[str, dict[str, float]], keys: list[str], n_iter: int = 50) -> dict[str, float]:
        r = {k: 1000.0 for k in keys}
        for _ in range(n_iter):
            for i in keys:
                numer, denom = 0.0, 0.0
                for j in keys:
                    if i == j:
                        continue
                    wij = win_matrix.get(i, {}).get(j, 0)
                    wji = win_matrix.get(j, {}).get(i, 0)
                    total = wij + wji
                    if total == 0:
                        continue
                    numer += wij
                    denom += total * r[j] / (r[i] + r[j]) if (r[i] + r[j]) > 0 else 0
                if denom > 0:
                    r[i] = max(100, r[i] * numer / denom)
        scale = 1000.0 / (sum(r.values()) / len(r)) if r else 1.0
        return {k: round(v * scale) for k, v in r.items()}

    keys = list(players.keys())
    main_wins: dict[str, dict[str, float]] = {k: {} for k in keys}
    dim_wins: dict[str, dict[str, dict[str, float]]] = {d: {k: {} for k in keys} for d in dims}

    for b in battles:
        ka = model_key(b.get("contestant_a", {}))
        kb = model_key(b.get("contestant_b", {}))
        vote = b.get("vote", "tie")
        if vote == "a_win":
            main_wins[ka][kb] = main_wins[ka].get(kb, 0) + 1.0
        elif vote == "b_win":
            main_wins[kb][ka] = main_wins[kb].get(ka, 0) + 1.0
        else:
            main_wins[ka][kb] = main_wins[ka].get(kb, 0) + 0.5
            main_wins[kb][ka] = main_wins[kb].get(ka, 0) + 0.5

        scores = b.get("scores") or {}
        sa = scores.get("a", {})
        sb = scores.get("b", {})
        for d in dims:
            va = sa.get(d, 5)
            vb = sb.get(d, 5)
            if va > vb:
                dim_wins[d][ka][kb] = dim_wins[d][ka].get(kb, 0) + 1.0
            elif vb > va:
                dim_wins[d][kb][ka] = dim_wins[d][kb].get(ka, 0) + 1.0
            else:
                dim_wins[d][ka][kb] = dim_wins[d][ka].get(kb, 0) + 0.5
                dim_wins[d][kb][ka] = dim_wins[d][kb].get(ka, 0) + 0.5

    main_elo = bt_mle(main_wins, keys)
    dim_elo = {d: bt_mle(dim_wins[d], keys) for d in dims}

    ratings = {}
    for k in keys:
        p = players[k]
        overall = main_elo.get(k, 1000)
        n = p["battles"]
        se = round(400 / math.sqrt(max(n, 1)))
        ci = [overall - 2 * se, overall + 2 * se]
        ratings[k] = {
            "overall": overall, "ci_95": ci,
            **{d: dim_elo[d].get(k, 1000) for d in dims},
            "battles": n, "wins": p["wins"], "losses": p["losses"], "ties": p["ties"],
            "contestant": p["contestant"],
        }

    result = {
        "updated_at": datetime.now().isoformat(),
        "total_battles": len(battles),
        "ratings": ratings,
        "mode": mode_filter or "all",
    }
    elo_path = ARENA_DIR / f"elo_ratings{'_' + mode_filter if mode_filter else ''}.json"
    with open(elo_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return result


# ══════════════════════════════════════════════════════════════
# am-ELO: 标注者一致性分析
# ══════════════════════════════════════════════════════════════

def compute_annotator_consistency() -> dict:
    """估算标注者一致性：通过五维评分的方差判断打分质量"""
    if not BATTLES_FILE.exists():
        return {"consistency_score": 1.0, "details": {}}

    session_scores: dict[str, list[dict]] = {}
    with open(BATTLES_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                b = json.loads(line)
            except json.JSONDecodeError:
                continue
            sid = b.get("arena_session_id", "unknown")
            scores = b.get("scores") or {}
            if scores.get("a") and scores.get("b"):
                session_scores.setdefault(sid, []).append(scores)

    if not session_scores:
        return {"consistency_score": 1.0, "details": {}}

    dims = ["empathy", "depth", "practicality", "professionalism", "fluency"]
    details = {}

    for sid, score_list in session_scores.items():
        diffs = []
        for s in score_list:
            for d in dims:
                diffs.append(abs(s["a"].get(d, 5) - s["b"].get(d, 5)))
        avg_diff = sum(diffs) / len(diffs) if diffs else 0
        all_same = all(
            all(s["a"].get(d, 5) == s["a"].get(dims[0], 5) for d in dims) and
            all(s["b"].get(d, 5) == s["b"].get(dims[0], 5) for d in dims)
            for s in score_list
        )
        if all_same and len(score_list) > 1:
            quality = 0.3
            label = "低质量（全维度评分相同，可能随意打分）"
        elif avg_diff < 0.5 and len(score_list) > 2:
            quality = 0.5
            label = "中等（维度间差异过小）"
        elif avg_diff > 5:
            quality = 0.6
            label = "中等（维度间差异过大，可能极端打分）"
        else:
            quality = 1.0
            label = "正常"

        details[sid] = {
            "rounds": len(score_list),
            "avg_diff": round(avg_diff, 2),
            "quality": round(quality, 2),
            "label": label,
        }

    avg_quality = sum(d["quality"] for d in details.values()) / len(details)

    return {
        "consistency_score": round(avg_quality, 3),
        "sessions_analyzed": len(details),
        "details": details,
    }
