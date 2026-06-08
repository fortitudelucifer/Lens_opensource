"""
Day 5 · D5.5 · RoundtableAuditor — 圆桌讨论结构化审计日志

目标：
  - 每场 session 落一份 JSONL 审计文件，供离线分析 / 回归 / 告警
  - 关键事件（phase/agent/sanitize/moderator）全部结构化
  - 日志路径：`advisor_out/roundtable/audit/{YYYYMMDD}/{session_id}.jsonl`
  - 与 logger.info 双写 · 方便 tail 实时观察

设计约束：
  - 线程安全（pipeline 多 task 并发）
  - 零依赖：纯 stdlib + pydantic（项目已有）
  - 失败不影响主流程：任何 emit 异常只 log.warning
  - 轻量：每事件 < 1KB，单轮会话约 30-50 事件 · 写盘开销忽略

使用方式：
    from .roundtable_audit import get_auditor, AuditEventType
    auditor = get_auditor()
    auditor.emit(
        session_id="rt_xxx",
        event_type="agent_done",
        persona_id="neutral", phase="phase1",
        data={"duration_s": 12.3, "chunk_count": 28, "confidence": 0.85},
    )
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

# ── 审计目录（env override · 单测用） ───────────────────────
PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_AUDIT_ROOT: Path = (
    PROJECT_ROOT / "advisor_out" / "roundtable" / "audit"
)

# 事件类型字面量 · 新增时也在此登记
AuditEventType = Literal[
    "session_created",
    "phase_start",
    "phase_end",
    "agent_streaming_start",
    "agent_done",
    "agent_error",
    "bias_hit",
    "crisis_hit",
    "moderator_start",
    "moderator_done",
    "session_done",
    "memory_built",
]

_VALID_EVENT_TYPES: frozenset[str] = frozenset({
    "session_created", "phase_start", "phase_end",
    "agent_streaming_start", "agent_done", "agent_error",
    "bias_hit", "crisis_hit",
    "moderator_start", "moderator_done",
    "session_done",
    "memory_built",
})


class AuditEvent(BaseModel):
    """单条审计事件 · JSONL 一行 = 一个 AuditEvent"""
    ts: str                               # ISO 8601（含毫秒）
    session_id: str
    round_index: int = 0
    event_type: str                        # 不用 Literal 以便运行时扩展
    persona_id: Optional[str] = None
    phase: Optional[str] = None
    data: dict[str, Any] = Field(default_factory=dict)

    def to_jsonl_line(self) -> str:
        return self.model_dump_json(exclude_none=False) + "\n"


# ═══════════════════════════════════════════════════════════════
# Auditor 单例
# ═══════════════════════════════════════════════════════════════


class RoundtableAuditor:
    """进程级单例 · 线程安全（asyncio tasks 共享同一事件循环但可能并发写）

    文件句柄缓存：
      同一 session_id 复用 open 文件 · 退出时可手动 close_session()
      或进程结束时 GC 自动关闭
    """

    def __init__(self, audit_root: Optional[Path] = None) -> None:
        self._root: Path = Path(audit_root) if audit_root else DEFAULT_AUDIT_ROOT
        self._root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        # session_id → 已经为其创建过的文件路径（用于快速路径查询）
        self._paths: dict[str, Path] = {}

    # ── 路径规则 ───────────────────────────────────────────
    def _path_for(self, session_id: str, created_at: Optional[datetime] = None) -> Path:
        """文件路径：{root}/{YYYYMMDD}/{session_id}.jsonl

        YYYYMMDD 取首次 emit 时的日期（避免跨午夜 session 路径分裂）。
        """
        if session_id in self._paths:
            return self._paths[session_id]
        dt = created_at or datetime.now()
        day = dt.strftime("%Y%m%d")
        sub = self._root / day
        sub.mkdir(parents=True, exist_ok=True)
        path = sub / f"{session_id}.jsonl"
        self._paths[session_id] = path
        return path

    # ── 核心 emit ──────────────────────────────────────────
    def emit(
        self,
        *,
        session_id: str,
        event_type: str,
        round_index: int = 0,
        persona_id: Optional[str] = None,
        phase: Optional[str] = None,
        data: Optional[dict[str, Any]] = None,
    ) -> Optional[AuditEvent]:
        """写一条审计事件（同步 · JSONL append + logger.info）

        失败回落：任何异常只 warning，不抛出，不影响主流程。
        返回写入的 AuditEvent（便于测试 assert），失败返回 None。
        """
        try:
            if event_type not in _VALID_EVENT_TYPES:
                # 不 raise · 只 warn · 未来扩展留余地
                log.warning("[rt_audit] unknown event_type=%r · still recording", event_type)

            ev = AuditEvent(
                ts=datetime.now().isoformat(timespec="milliseconds"),
                session_id=session_id,
                round_index=round_index,
                event_type=event_type,
                persona_id=persona_id,
                phase=phase,
                data=data or {},
            )
            line = ev.to_jsonl_line()
            path = self._path_for(session_id)
            with self._lock:
                with open(path, "a", encoding="utf-8") as f:
                    f.write(line)

            # 双写到 logger · uvicorn stdout tail 也能看到结构化事件
            log.info(
                "[rt_audit] session=%s round=%d type=%s persona=%s phase=%s data=%s",
                session_id, round_index, event_type,
                persona_id or "-", phase or "-",
                json.dumps(data or {}, ensure_ascii=False, default=str),
            )
            return ev
        except Exception:
            log.exception("[rt_audit] emit failed · event_type=%s session=%s",
                          event_type, session_id)
            return None

    # ── 读回放（供测试 + 离线回放） ────────────────────────
    def read(self, session_id: str) -> list[AuditEvent]:
        """读回 session 的所有事件（按写入顺序）"""
        path = self._path_for(session_id)
        if not path.exists():
            return []
        out: list[AuditEvent] = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(AuditEvent.model_validate_json(line))
                except Exception:
                    log.warning("[rt_audit] skipped malformed line · session=%s", session_id)
        return out

    # ── 辅助：定位文件路径 ────────────────────────────────
    def path_for(self, session_id: str) -> Optional[Path]:
        """公开版本 · 只返回已缓存的路径（不创建目录）"""
        return self._paths.get(session_id)


# ═══════════════════════════════════════════════════════════════
# 进程级单例
# ═══════════════════════════════════════════════════════════════

_default_auditor: Optional[RoundtableAuditor] = None
_default_lock = threading.Lock()


def get_auditor() -> RoundtableAuditor:
    """获取进程级单例 · 支持 env `ROUNDTABLE_AUDIT_ROOT` override（测试用）"""
    global _default_auditor
    if _default_auditor is not None:
        return _default_auditor
    with _default_lock:
        if _default_auditor is None:
            root_override = os.environ.get("ROUNDTABLE_AUDIT_ROOT", "").strip()
            root = Path(root_override) if root_override else None
            _default_auditor = RoundtableAuditor(audit_root=root)
    return _default_auditor


def reset_auditor() -> None:
    """单测/重置用 · 清掉缓存 · 下次 get_auditor 会重新读 env"""
    global _default_auditor
    with _default_lock:
        _default_auditor = None


# ═══════════════════════════════════════════════════════════════
# 便捷 emit_xxx 系列（避免调用方拼参数出错）
# ═══════════════════════════════════════════════════════════════


def emit_session_created(
    *, session_id: str, personas: list[str], question: str,
    backend: Optional[str] = None, parent_id: Optional[str] = None,
    round_index: int = 0,
) -> None:
    get_auditor().emit(
        session_id=session_id,
        event_type="session_created",
        round_index=round_index,
        data={
            "personas": personas,
            "question_len": len(question),
            "question_head": question[:100],
            "backend": backend,
            "parent_id": parent_id,
        },
    )


def emit_phase_start(*, session_id: str, phase: str, round_index: int = 0) -> None:
    get_auditor().emit(
        session_id=session_id, event_type="phase_start", round_index=round_index,
        phase=phase, data={},
    )


def emit_phase_end(
    *, session_id: str, phase: str, duration_s: float, round_index: int = 0,
) -> None:
    get_auditor().emit(
        session_id=session_id, event_type="phase_end", round_index=round_index,
        phase=phase, data={"duration_s": round(duration_s, 3)},
    )


def emit_agent_done(
    *, session_id: str, phase: str, persona_id: str,
    duration_s: float, chunk_count: int, text_len: int,
    confidence: Optional[float] = None, round_index: int = 0,
) -> None:
    get_auditor().emit(
        session_id=session_id, event_type="agent_done", round_index=round_index,
        persona_id=persona_id, phase=phase,
        data={
            "duration_s": round(duration_s, 3),
            "chunk_count": chunk_count,
            "text_len": text_len,
            "confidence": confidence,
        },
    )


def emit_agent_error(
    *, session_id: str, phase: str, persona_id: str, error: str,
    round_index: int = 0,
) -> None:
    get_auditor().emit(
        session_id=session_id, event_type="agent_error", round_index=round_index,
        persona_id=persona_id, phase=phase,
        data={"error": str(error)[:500]},
    )


def emit_bias_hit(
    *, session_id: str, phase: Optional[str], persona_id: Optional[str],
    categories: list[str], patterns: list[str],
    raw_snippet: str = "", round_index: int = 0,
) -> None:
    get_auditor().emit(
        session_id=session_id, event_type="bias_hit", round_index=round_index,
        persona_id=persona_id, phase=phase,
        data={
            "categories": categories,
            "patterns": patterns,
            "raw_snippet": raw_snippet[:80],
        },
    )


def emit_crisis_hit(
    *, session_id: str, phase: Optional[str], persona_id: Optional[str],
    hit_type: str, keywords: list[str], round_index: int = 0,
) -> None:
    """hit_type: 'input'（用户问题触发）| 'prohibited'（agent 输出触发 sanitize）"""
    get_auditor().emit(
        session_id=session_id, event_type="crisis_hit", round_index=round_index,
        persona_id=persona_id, phase=phase,
        data={"hit_type": hit_type, "keywords": keywords},
    )


def emit_moderator_done(
    *, session_id: str, duration_s: float, fallback_reason: Optional[str],
    thinking_len: int, content_keys: list[str], round_index: int = 0,
) -> None:
    get_auditor().emit(
        session_id=session_id, event_type="moderator_done", round_index=round_index,
        data={
            "duration_s": round(duration_s, 3),
            "fallback_reason": fallback_reason,
            "thinking_len": thinking_len,
            "content_keys": content_keys,
        },
    )


def emit_memory_built(
    *, session_id: str, persona_id: str, round_index: int,
    round_count: int, kept_rounds: int, dropped_rounds: int,
    char_count: int, token_estimate: int, truncated: bool,
    tier_breakdown: Optional[dict[str, Any]] = None,
) -> None:
    """D5.2c · 记录 CrossRoundMemory 构建指标（每次 prompt 拼装前一次）"""
    get_auditor().emit(
        session_id=session_id, event_type="memory_built",
        round_index=round_index, persona_id=persona_id,
        data={
            "round_count": round_count,
            "kept_rounds": kept_rounds,
            "dropped_rounds": dropped_rounds,
            "char_count": char_count,
            "token_estimate": token_estimate,
            "truncated": truncated,
            "tier_breakdown": tier_breakdown or {},
        },
    )


def emit_session_done(
    *, session_id: str, total_duration_s: float, first_agent_chunk_s: Optional[float],
    total_events: int, errors_count: int, rewrite_count_total: int,
    round_index: int = 0,
) -> None:
    get_auditor().emit(
        session_id=session_id, event_type="session_done", round_index=round_index,
        data={
            "total_duration_s": round(total_duration_s, 3),
            "first_agent_chunk_s": (
                round(first_agent_chunk_s, 3) if first_agent_chunk_s else None
            ),
            "total_events": total_events,
            "errors_count": errors_count,
            "rewrite_count_total": rewrite_count_total,
        },
    )
