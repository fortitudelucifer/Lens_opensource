"""services/chat_service.py — 会话 CRUD + 记忆压缩 + 事实提取 + 原子写入

从 server.py 迁移（Step 3，🔴 高风险）：
  - `_compress_history_messages` → `compress_history_messages`
  - `_truncate_history_messages` → `truncate_history_messages`
  - `_extract_memory_facts`      → `extract_memory_facts`
  - `_session_path`              → `session_path`
  - `_load_session`              → `load_session`
  - `_save_session`              → `save_session`  （§7.5 改为原子写入）
  - `_create_session`            → `create_session`
  - `_list_sessions`             → `list_sessions`
  - `_chat_communication_status` → `chat_communication_status`

常量：`MAX_RECENT_MESSAGES`, `MAX_MSG_CHARS`, `MAX_SUMMARY_ITEMS`

§7.5 原子写入：`save_session` 使用 `<file>.tmp` + `os.replace` 保证崩溃时不产生半写文件。
"""
from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..core.config import CHAT_DIR


# ── 长对话记忆压缩参数 ──────────────────────────────
# 1. 滑动窗口：保留最近 N 条完整消息
# 2. 历史摘要：将更早的消息压缩为摘要注入 system prompt
# 3. 关键事实：从 assistant 回复中提取关键信息持久存储

MAX_RECENT_MESSAGES = 16       # 保留最近 16 条完整消息（约 8 轮问答）
MAX_MSG_CHARS = 2500           # 历史中单条消息最大字符数（保留核心分析，截掉尾部示例话术）
MAX_SUMMARY_ITEMS = 12         # 摘要中最多保留 12 条要点


# ══════════════════════════════════════════════════════════════
# 记忆压缩 / 截断 / 事实提取
# ══════════════════════════════════════════════════════════════

def compress_history_messages(session: dict) -> tuple[str, list[dict]]:
    """将超长对话历史压缩为 (摘要文本, 近期消息列表)

    Returns:
        summary: 旧消息摘要（空字符串表示无需压缩）
        recent: 近期消息列表（保留完整内容）
    """
    all_msgs = session.get("messages", [])
    if len(all_msgs) <= MAX_RECENT_MESSAGES:
        return "", all_msgs

    older = all_msgs[:-MAX_RECENT_MESSAGES]
    recent = all_msgs[-MAX_RECENT_MESSAGES:]

    # 从旧消息中提取要点
    summary_lines = []
    for msg in older:
        role_label = "你" if msg["role"] == "assistant" else "用户"
        content = msg["content"]
        if msg["role"] == "assistant":
            # 提取 assistant 回复的第一段有效内容（跳过空行和标题）
            for line in content.split('\n'):
                line = line.strip()
                if line and not line.startswith('#') and not line.startswith('---') and len(line) > 10:
                    summary_lines.append(f"- {role_label}回复: {line[:120]}")
                    break
        else:
            summary_lines.append(f"- {role_label}问: {content[:80]}")

    if not summary_lines:
        return "", all_msgs

    summary = (
        f"【对话历史摘要】（共 {len(older)} 条旧消息已压缩，以下为要点）\n"
        + "\n".join(summary_lines[-MAX_SUMMARY_ITEMS:])
    )

    # 从 session 中提取累积的关键事实
    facts = session.get("memory_facts", [])
    if facts:
        summary += "\n\n【本次对话已确认的关键信息】\n" + "\n".join(f"- {f}" for f in facts[-10:])

    return summary, recent


def truncate_history_messages(messages: list[dict]) -> list[dict]:
    """截断历史中过长的单条消息，节省 token 预算"""
    result = []
    for msg in messages:
        if msg["role"] != "system" and len(msg.get("content", "")) > MAX_MSG_CHARS:
            truncated = dict(msg)
            truncated["content"] = msg["content"][:MAX_MSG_CHARS] + "\n...[回复过长已截断，完整内容已记录在会话中]"
            result.append(truncated)
        else:
            result.append(msg)
    return result


def extract_memory_facts(assistant_response: str) -> list[str]:
    """从 assistant 回复中提取可持久化的关键事实

    提取规则：
    - 明确的日期+事件对（如 "9月24日发生了..."）
    - 标记为结论/建议的内容
    - 对用户关系状态的判断
    """
    facts = []
    # 日期事件对
    for m in re.finditer(
        r'(\d{1,2}月\d{1,2}[日号]?|第\d+天)[^。\n]{5,80}[。]?', assistant_response
    ):
        fact = m.group(0).strip()
        if len(fact) > 15:
            facts.append(fact[:120])
    # 关系状态判断
    for m in re.finditer(
        r'(?:关系状态|核心问题|根本原因|关键转折)[：:]\s*([^。\n]{5,100})', assistant_response
    ):
        facts.append(m.group(0)[:120])
    # 去重
    seen = set()
    unique = []
    for f in facts:
        key = f[:30]
        if key not in seen:
            seen.add(key)
            unique.append(f)
    return unique[:5]  # 每次最多提取 5 条


# ══════════════════════════════════════════════════════════════
# 会话 CRUD
# ══════════════════════════════════════════════════════════════

def session_path(session_id: str) -> Path:
    return CHAT_DIR / f"{session_id}.json"


def load_session(session_id: str) -> Optional[dict]:
    p = session_path(session_id)
    if not p.exists():
        return None
    with open(p, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_session(session: dict):
    """原子写入会话文件（§7.5 数据完整性保护）

    写到 `<id>.json.tmp` 后 `os.replace` 原子覆盖，避免进程崩溃造成半写文件损坏。
    """
    p = session_path(session['id'])
    tmp = p.with_suffix(p.suffix + '.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(session, f, ensure_ascii=False, indent=2)
    os.replace(str(tmp), str(p))


def create_session(agent_type: str = "neutral", mode: str = "listen",
                   backend: str = "grok") -> dict:
    session = {
        "id": str(uuid.uuid4())[:8],
        "title": "",
        "agent_type": agent_type,
        "mode": mode,
        "backend": backend,
        "messages": [],
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
    }
    if agent_type == "eft":
        session["eft_stage"] = "exploration"
        session["eft_round_count"] = 0
    if agent_type == "bowen":
        session["bowen_third_parties"] = []
        session["bowen_triangles_detected"] = 0
    save_session(session)
    return session


def list_sessions() -> list[dict]:
    sessions = []
    for p in sorted(CHAT_DIR.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True):
        try:
            with open(p, 'r', encoding='utf-8') as f:
                s = json.load(f)
            sessions.append({
                "id": s["id"],
                "title": s.get("title", ""),
                "agent_type": s.get("agent_type", "neutral"),
                "mode": s.get("mode", "listen"),
                "backend": s.get("backend", ""),
                "message_count": len(s.get("messages", [])),
                "created_at": s.get("created_at", ""),
                "updated_at": s.get("updated_at", ""),
                "communication_status": chat_communication_status(s),
            })
        except (json.JSONDecodeError, KeyError):
            continue
    return sessions


def chat_communication_status(session: dict) -> str:
    messages = session.get("messages") or []
    if not messages:
        return "未开始"
    for msg in reversed(messages):
        if msg.get("role") == "assistant" and msg.get("crisis_level") == "RED":
            return "危机干预"

    # 如果有监督分析数据，优先返回对话阶段（如 "探索", "建立连接" 等）
    supervision_state = session.get("supervision_state", {})
    if supervision_state:
        last_analysis = supervision_state.get("last_judge_analysis", {})
        if last_analysis and "dialogue_progress" in last_analysis:
            stage = last_analysis["dialogue_progress"].get("stage")
            if stage:
                return stage

    if messages[-1].get("role") == "user":
        return "待回复"
    return "进行中"
