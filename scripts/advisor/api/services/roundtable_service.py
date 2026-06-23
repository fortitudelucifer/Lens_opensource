"""services/roundtable_service.py — 圆桌讨论 3-phase 编排器（Day 3 D3.2）

核心职责：
  - **session 生命周期**：create_session / get_session / interrupt_session
  - **SSE 多路复用**：单 endpoint 通过 `agent_id` 字段分流（执行方案 §1.2 决议）
  - **3-phase pipeline**：phase1 并发分析 → phase2 交叉回应 → phase3 规则 Moderator
  - **DAG 分叉**：parent_id 链支持 interrupt → child session（Day 4 完善）

设计要点（执行方案 §2 + ChatGPT 4 大隐患防范）：
  - asyncio.gather 并发 3 agent（不是串行），提高响应速度
  - asyncio.Queue 作为 producer-consumer 缓冲，订阅断开不丢事件
  - Phase 切换用 `phase_advance` 事件而不是 sleep（前端动画时序由 UI 决定）
  - **Day 3 用 mock LLM**（带上用户问题关键词，让用户感知 agent 看见了问题）
    Day 4 切换为真实 generator + roundtable_prompts.yaml
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import queue as sync_queue
import random
import re
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import AsyncIterator, Optional

import yaml

from ..core import state
from ..core.config import ADVISOR_OUT
from ..core.models import (
    RoundtableAgentBuffer, RoundtableAgentPhase, RoundtableAgentStatus,
    RoundtableModeratorContent, RoundtablePersonaId, RoundtablePhase,
    RoundtableRoundSnapshot, RoundtableSession,
)
from . import roundtable_audit as audit  # Day 5 · D5.5 · 结构化审计
from . import roundtable_memory as memory  # Day 4 · D4.8 · CrossRoundMemory 压缩
from .generator_service import get_generator

log = logging.getLogger(__name__)

# ── 持久化目录（与 chat_service 风格一致）──
ROUNDTABLE_DIR: Path = ADVISOR_OUT / "roundtable" / "sessions"
ROUNDTABLE_DIR.mkdir(parents=True, exist_ok=True)

# ── 内存运行时状态（进程级单例）──
_sessions: dict[str, RoundtableSession] = {}
_queues: dict[str, asyncio.Queue] = {}
_tasks: dict[str, asyncio.Task] = {}
_subscribed: dict[str, asyncio.Event] = {}  # subscribe 后才 trigger pipeline

# ── 事件流配置 ──
SENTINEL_DONE = {"__sentinel__": "done"}  # 队列结束信号
TYPING_DELAY_MIN = 0.4
TYPING_DELAY_JITTER = 0.6
STREAM_CHAR_INTERVAL = 0.018
STREAM_JITTER = 0.008
PHASE_PAUSE = 1.5  # phase1→2、phase2→3 之间的真实暂停（D1/D10）

# ── 9 persona 的中文名（与前端 personas.ts 严格一致）──
PERSONA_NAMES: dict[str, str] = {
    "neutral": "中立顾问",
    "supportive": "支持性顾问",
    "psychoanalytic": "精神分析顾问",
    "eft": "EFT 情绪聚焦",
    "bowen": "家庭系统顾问",
    "sociology": "社会学视角",
    "philosophy": "哲学视角",
    "game_theory": "博弈论视角",
    "cultural": "文化视角",
}

# ── 每个 persona 的 Moderator angles 描述（固定绑定，避免错配）──
PERSONA_ANGLES: dict[str, str] = {
    "neutral": "关注问题的结构与选择空间",
    "supportive": "提醒你别忽略此刻的感受本身",
    "psychoanalytic": "指向更早的剧本和未被接住的部分",
    "eft": "帮你看清愤怒之下的依恋需求",
    "bowen": "从家庭系统的代际模式切入",
    "sociology": "看见性别 / 阶层 / 社会脚本的影子",
    "philosophy": "把这件事放到更大的存在追问里",
    "game_theory": "把它当作可被设计的重复博弈",
    "cultural": "温柔地提醒文化水对你的塑造",
}

# ═══════════════════════════════════════════════════════════════════
# Day 4 · Prompts yaml 加载 + LLM 调用 + 置信度 regex
# ═══════════════════════════════════════════════════════════════════

# 配置文件路径 + 环境变量开关
_CONFIG_DIR: Path = Path(__file__).resolve().parents[4] / "configs"
_PROMPTS_PATH: Path = _CONFIG_DIR / "roundtable_prompts.yaml"

# ROUNDTABLE_USE_LLM=1 → 走真 LLM；未设置或 =0 → 走 mock（Day 3 风格）
USE_LLM: bool = os.environ.get("ROUNDTABLE_USE_LLM", "1") != "0"
DEFAULT_MAX_TOKENS: int = int(os.environ.get("ROUNDTABLE_MAX_TOKENS", "1024"))
# Day 7 · 深度模式 · 每 agent token 预算（约 1500 汉字）
DEEP_MAX_TOKENS: int = int(os.environ.get("ROUNDTABLE_DEEP_MAX_TOKENS", "2560"))
# ROUNDTABLE_MODERATOR_LLM=1 → Moderator 走真 LLM（失败 fallback 规则模板）· Day 5 · C
MODERATOR_USE_LLM: bool = os.environ.get("ROUNDTABLE_MODERATOR_LLM", "1") != "0"
MODERATOR_LLM_TIMEOUT: float = float(os.environ.get("ROUNDTABLE_MODERATOR_TIMEOUT", "180"))
MODERATOR_MAX_TOKENS: int = int(os.environ.get("ROUNDTABLE_MODERATOR_MAX_TOKENS", "2048"))
# Day 7 · 深度模式 · Moderator token 预算（约 2000 汉字）
DEEP_MODERATOR_MAX_TOKENS: int = int(os.environ.get("ROUNDTABLE_DEEP_MODERATOR_MAX_TOKENS", "3584"))
# Day 7 · 深度模式 · Moderator timeout（thinking 模型 + 大 token 预算需要更长）
# 独立于普通 timeout，避免"深度 + 思考模型"下频繁 90s 超时降级到规则模板
DEEP_MODERATOR_LLM_TIMEOUT: float = float(os.environ.get("ROUNDTABLE_DEEP_MODERATOR_TIMEOUT", "240"))


def _get_default_backend() -> str:
    """默认 backend 读取优先级：
      1. env `ROUNDTABLE_BACKEND`（显式 override）
      2. Lens UI 的 model_preferences.json `chat_backend`
      3. fallback → "grok"
    """
    env_bk = os.environ.get("ROUNDTABLE_BACKEND", "").strip()
    if env_bk:
        return env_bk
    try:
        from ..core.config import PREFS_PATH
        if PREFS_PATH.exists():
            with open(PREFS_PATH, "r", encoding="utf-8") as f:
                prefs = json.load(f)
            bk = (prefs.get("chat_backend") or "").strip()
            if bk:
                return bk
    except Exception:
        pass
    return "grok"

# LLM 流式推送给前端的节流间隔（真 LLM token 通常以 "词"/"短字" 粒度来）
LLM_STREAM_INTERVAL: float = 0.008
# phase2 末尾「[置信度: 0.xx]」提取正则
_CONFIDENCE_RE = re.compile(
    r"\[?\s*(?:置信度|confidence)\s*[:：]\s*([01](?:\.\d+)?)\s*\]?",
    re.IGNORECASE,
)

# prompt yaml cache（进程级）
_PROMPTS_CACHE: Optional[dict] = None


def _load_prompts() -> dict:
    """加载 roundtable_prompts.yaml（首次调用后缓存）"""
    global _PROMPTS_CACHE
    if _PROMPTS_CACHE is None:
        if not _PROMPTS_PATH.exists():
            log.warning(
                "[roundtable] prompts yaml not found at %s · 将使用 mock 文本",
                _PROMPTS_PATH,
            )
            _PROMPTS_CACHE = {}
        else:
            try:
                with open(_PROMPTS_PATH, "r", encoding="utf-8") as f:
                    _PROMPTS_CACHE = yaml.safe_load(f) or {}
                log.info(
                    "[roundtable] prompts loaded · %d personas",
                    len(_PROMPTS_CACHE.get("personas", {})),
                )
            except Exception:
                log.exception("[roundtable] failed to load prompts yaml")
                _PROMPTS_CACHE = {}
    return _PROMPTS_CACHE


def _build_prior_context_block(
    session: RoundtableSession,
    persona_id: str,
    *,
    char_budget: int = memory.DEFAULT_CHAR_BUDGET,
) -> str:
    """Day 6 · 形态 A + Day 4 · D4.8 · 构造「往轮压缩记忆 + RAG 注入」prompt 片段

    两部分内容，任一为空时该部分会被跳过：
      1. 跨轮压缩记忆（若 session.rounds 非空）· 由 CrossRoundMemory 按优先级 + 预算裁切
      2. Step 4 · RAG 注入的 chat_history / knowledge 片段（若 session.current_inject_context 非空）

    返回拼好的字符串，首轮无历史、无注入则返回空串。
    """
    parts: list[str] = []

    # ── 1. 跨轮压缩记忆（D4.8） ──
    if getattr(session, "rounds", None):
        try:
            mem_text, mem_metrics = memory.build_memory_block(
                session, persona_id, char_budget=char_budget,
            )
        except Exception:
            log.exception("[roundtable] CrossRoundMemory build failed · persona=%s", persona_id)
            mem_text, mem_metrics = "", memory.MemoryMetrics()

        if mem_text:
            parts.append(mem_text)
            # 审计事件（D5.2c · memory_built）· 失败不影响主流程
            try:
                audit.emit_memory_built(
                    session_id=session.id,
                    persona_id=persona_id,
                    round_index=session.round_index,
                    round_count=mem_metrics.round_count,
                    kept_rounds=mem_metrics.kept_rounds,
                    dropped_rounds=mem_metrics.dropped_rounds,
                    char_count=mem_metrics.char_count,
                    token_estimate=mem_metrics.token_estimate,
                    truncated=mem_metrics.truncated,
                    tier_breakdown={
                        "tier1_chars": mem_metrics.tier1_chars,
                        "tier2_chars": mem_metrics.tier2_chars,
                        "tier3_chars": mem_metrics.tier3_chars,
                        "tier3_rounds_kept": mem_metrics.tier3_rounds_kept,
                    },
                )
            except Exception:
                log.warning("[roundtable] emit_memory_built failed", exc_info=True)

    # ── 2. RAG 注入（Step 4） ──
    inject = (getattr(session, "current_inject_context", "") or "").strip()
    if inject:
        # 截断保护（models 层已 max_length=12000，这里再兜底）
        if len(inject) > 12000:
            inject = inject[:12000] + "…"
        parts.append(
            "━━━ 用户追加注入的参考资料 ━━━\n"
            + inject
            + "\n\n请把这些资料作为背景参考，**但不要原样引用或暴露**——你仍以顾问人设回应，不是转述资料。"
        )

    if not parts:
        return ""
    # 段之间空两行，段末保留两个换行隔开后续 persona_core
    return "\n\n".join(parts) + "\n\n"


def _build_moderator_prior_context_block(
    session: RoundtableSession,
    *,
    max_chars: int = 1600,
) -> str:
    """Day 7 · 修复「Moderator 对追问无记忆」bug · 构造 Moderator 视角的历史轮回顾。

    和 `_build_prior_context_block`（agent 视角）不同，这里以 Moderator 自己的视角拼：
      - 上一轮用户问了什么
      - 上一轮 Moderator 自己给的 seen / angles / lens 核心结论
      - 更早轮只保留「第 k 轮 · 问 → 一句话结论」

    这样新一轮 Moderator 能**承接**自己上一轮对该用户说过的话，不再像第一次见面。
    首轮（session.rounds 空）返回空串 · 不影响模板结构。
    """
    rounds = list(getattr(session, "rounds", []) or [])
    if not rounds:
        return ""

    parts: list[str] = []
    last = rounds[-1]

    # ── Tier-1 · 最近一轮的 Moderator 自述 ──
    last_q = (last.question or "").strip()
    if len(last_q) > 200:
        last_q = last_q[:199].rstrip() + "…"

    last_mod = last.moderator
    if last_mod is not None:
        seen = (last_mod.seen or "").strip()
        if len(seen) > 280:
            seen = seen[:279].rstrip() + "…"
        angles = "；".join(str(a).strip() for a in (last_mod.angles or []) if str(a).strip())
        if len(angles) > 240:
            angles = angles[:239].rstrip() + "…"
        lens = (last_mod.lens or "").strip()
        if len(lens) > 160:
            lens = lens[:159].rstrip() + "…"

        t1 = (
            f"━━━ 上一轮（第 {last.round_index + 1} 轮）你对该用户说过的话 ━━━\n"
            f"【当时用户问的】{last_q or '（无记录）'}\n"
            f"【你上轮【seen】】{seen or '（无记录）'}\n"
            f"【你上轮【angles】】{angles or '（无记录）'}\n"
            f"【你上轮【lens】】{lens or '（无记录）'}\n\n"
            "**这一轮输出请遵循**：\n"
            "  · 不要重复上一轮的 angles / lens 原话——改用新措辞、新角度\n"
            "  · seen 必须承接用户**这次**问题的新细节，不能抄上一轮\n"
            "  · 如果用户这轮其实在延续同一件事，请体现出「她上次说过 X，这次是 X 的进展/反复」\n"
        )
        parts.append(t1)
    else:
        parts.append(
            f"━━━ 上一轮（第 {last.round_index + 1} 轮）回顾 ━━━\n"
            f"【用户当时问的】{last_q or '（无记录）'}\n（上一轮 Moderator 输出缺失）\n"
        )

    # ── Tier-2 · 更早轮（每轮一行，LIFO 保留最近的）──
    older = rounds[:-1]
    if older:
        t2_lines: list[str] = []
        # 从新到老遍历
        for snap in reversed(older):
            q = (snap.question or "").strip()
            if len(q) > 70:
                q = q[:69].rstrip() + "…"
            summary = ""
            if snap.moderator is not None:
                summary = (snap.moderator.seen or "").strip()
                if len(summary) > 90:
                    summary = summary[:89].rstrip() + "…"
            if not q and not summary:
                continue
            t2_lines.append(f"· 第 {snap.round_index + 1} 轮 · 用户问：{q or '—'} → 你说：{summary or '—'}")
        if t2_lines:
            parts.append("── 更早的历史轮 ──\n" + "\n".join(t2_lines) + "\n")

    block = "\n".join(parts)
    # 整块兜底截断（极端情况下多轮太多）
    if len(block) > max_chars:
        block = block[: max_chars - 1].rstrip() + "…\n"
    return block + "\n"


def _build_phase1_prompt(persona_id: str, session: RoundtableSession) -> Optional[str]:
    """构造 Phase 1 的 LLM prompt（独立分析）

    Day 6 · 多轮形态 A · 若 session.rounds 非空，在 prompt 顶部注入往轮摘要。
    Day 7 · 深度模式 · 当 session.deep_mode=True 时用 deep_phase1_template
            （500-900 字）替代普通模板（150-300 字）。
    """
    prompts = _load_prompts()
    # Day 7 · 按 deep_mode 选择模板；深度模板缺失时 fallback 回普通模板
    tmpl_key = "deep_phase1_template" if getattr(session, "deep_mode", False) else "phase1_template"
    tmpl = prompts.get(tmpl_key) or prompts.get("phase1_template")
    persona = prompts.get("personas", {}).get(persona_id)
    if not tmpl or not persona:
        return None
    try:
        return tmpl.format(
            persona_name=persona.get("name", persona_id),
            persona_core=persona.get("core", ""),
            question=session.question,
            prior_context_block=_build_prior_context_block(session, persona_id),
        )
    except Exception:
        log.exception("[roundtable] failed to render phase1 prompt · persona=%s", persona_id)
        return None


def _build_phase2_prompt(
    persona_id: str,
    session: RoundtableSession,
) -> Optional[str]:
    """构造 Phase 2 的 LLM prompt（看到 peer 的 phase1 摘要后回应）

    Day 7 · 深度模式 · 当 session.deep_mode=True 时用 deep_phase2_template
            （500-900 字）替代普通模板（150-300 字）。
    """
    prompts = _load_prompts()
    tmpl_key = "deep_phase2_template" if getattr(session, "deep_mode", False) else "phase2_template"
    tmpl = prompts.get(tmpl_key) or prompts.get("phase2_template")
    persona = prompts.get("personas", {}).get(persona_id)
    if not tmpl or not persona:
        return None

    # peer = 除自己外的 phase1 buffer（按 personas 顺序取前 2 个）
    peer_buffers = [
        b for b in session.phase1 if b.persona_id != persona_id
    ][:2]
    # 用前 400 字作为 peer summary（避免过长的 prompt）
    def _summarize(buf: RoundtableAgentBuffer) -> str:
        text = (buf.text or "").strip()
        if not text:
            return "（暂未给出观点）"
        if len(text) > 400:
            return text[:400] + "…"
        return text

    # 有 2 个 peer 则正常；只有 1 个时复用；没有时用 placeholder
    if len(peer_buffers) >= 2:
        peer0_id, peer1_id = peer_buffers[0].persona_id, peer_buffers[1].persona_id
        peer0_summary = _summarize(peer_buffers[0])
        peer1_summary = _summarize(peer_buffers[1])
    elif len(peer_buffers) == 1:
        peer0_id = peer1_id = peer_buffers[0].persona_id
        peer0_summary = peer1_summary = _summarize(peer_buffers[0])
    else:
        peer0_id = peer1_id = persona_id
        peer0_summary = peer1_summary = "（暂无 peer 观点）"

    try:
        return tmpl.format(
            persona_name=persona.get("name", persona_id),
            persona_core=persona.get("core", ""),
            question=session.question,
            peer0_name=PERSONA_NAMES.get(peer0_id, peer0_id),
            peer1_name=PERSONA_NAMES.get(peer1_id, peer1_id),
            peer0_summary=peer0_summary,
            peer1_summary=peer1_summary,
            # Day 6 · 多轮形态 A · 往轮上下文注入（首轮为空串）
            prior_context_block=_build_prior_context_block(session, persona_id),
        )
    except Exception:
        log.exception("[roundtable] failed to render phase2 prompt · persona=%s", persona_id)
        return None


def _extract_confidence(text: str) -> Optional[float]:
    """从 agent 输出末尾抽取 [置信度: 0.xx] 或 [confidence: 0.xx]

    返回 0.0-1.0 的浮点数；未找到或超出范围返回 None
    """
    if not text:
        return None
    # 用 finditer 拿最后一个匹配（防止 agent 在正文中提到"置信度"字样）
    last_match = None
    for m in _CONFIDENCE_RE.finditer(text):
        last_match = m
    if not last_match:
        return None
    try:
        val = float(last_match.group(1))
        if 0.0 <= val <= 1.0:
            return round(val, 2)
    except (ValueError, IndexError):
        pass
    return None


def _strip_confidence_marker(text: str) -> str:
    """把 agent 输出末尾的 [置信度: 0.xx] 标记从显示文本中移除（前端不需看到）

    仅清理**最后出现**的那一个标记，避免误删正文中的提及。
    """
    if not text:
        return text
    last_match = None
    for m in _CONFIDENCE_RE.finditer(text):
        last_match = m
    if last_match is None:
        return text
    # 截掉最后一个匹配 + 其前后的空白/换行
    cut_start = last_match.start()
    cleaned = text[:cut_start].rstrip()
    # 可能还有最后一行的 "置信度：" 前缀被独立成行，裁掉空行
    return cleaned


async def _call_llm_stream(
    backend: str,
    prompt: str,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> AsyncIterator[str]:
    """调用 LLM 流式接口，yield 每个 token（async generator）

    用 queue.Queue + run_in_executor 把同步 OpenAI 客户端流式输出转 async。
    与 chat.py `_stream_chat_completions` 模式一致。

    如果 backend 为 Claude 官方（_claude_native=True），抛 RuntimeError 走 fallback。
    """
    gen = get_generator(backend)

    # Claude 官方 SDK 不走 OpenAI 兼容（Day 4 暂不支持，fallback 到 mock）
    if getattr(gen, "_claude_native", False):
        raise RuntimeError("claude_native not supported in roundtable (fallback to mock)")

    kwargs: dict = dict(
        model=gen.model,
        messages=[{"role": "user", "content": prompt}],
        stream=True,
        max_tokens=min(gen.max_tokens, max_tokens),
    )
    if gen.temperature is not None and "think" not in gen.model.lower():
        kwargs["temperature"] = gen.temperature

    # 线程间 token 队列
    tq: sync_queue.Queue = sync_queue.Queue()
    stop_event = asyncio.Event()

    def _run_sync_stream() -> None:
        """在线程中执行同步 OpenAI 流式调用"""
        try:
            stream = gen.client.chat.completions.create(**kwargs)
            for chunk in stream:
                if stop_event.is_set():
                    break
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    tq.put(("token", delta.content))
            tq.put(("done", None))
        except Exception as exc:
            tq.put(("error", str(exc)))

    loop = asyncio.get_event_loop()
    fut = loop.run_in_executor(None, _run_sync_stream)

    try:
        while True:
            # 非阻塞 poll + 短暂 await 让 event loop 轮转
            try:
                kind, val = tq.get_nowait()
            except sync_queue.Empty:
                await asyncio.sleep(LLM_STREAM_INTERVAL)
                continue
            if kind == "done":
                break
            if kind == "error":
                raise RuntimeError(f"LLM stream error: {val}")
            if kind == "token" and val:
                yield val
    except asyncio.CancelledError:
        # 订阅或 pipeline 被取消 · 让线程知道停
        stop_event.set()
        raise
    finally:
        # 等待底层线程结束
        try:
            await asyncio.wait_for(fut, timeout=2.0)
        except Exception:
            pass


def _sanitize_agent_output(text: str, audit_context: Optional[dict] = None) -> str:
    """Agent 流式输出的统一 sanitize 入口。

    两段检查（Day 4 · D4.1 + D4.7）：
      ① CrisisDetector.check_response_prohibited
          → 替换诊断/处方/边界违规等"绝对禁用"词
          → 占位符："（此处表述不当，已移除）"
      ② BiasDetector.sanitize（D4.7 新增）
          → 替换性别刻板 / 关系绝对化 / 受害者归咎 / 道德评判 / 病理化标签
          → 占位符："（此处表述调整）"
          → 命中写 audit log（持 session/phase/persona 上下文）

    调用方：
      - GuardedEmitter._flush（token 级 · 携带 audit_context）
      - _stream_one_agent 末尾 buf.text 兜底（整段复核 · 无 context）
    """
    if not text:
        return text
    # Day 5 · D5.5 · audit 上下文提前解开供命中事件使用
    _ctx = audit_context or {}
    _sid = _ctx.get("session_id") or ""
    _phase = _ctx.get("phase")
    _persona = _ctx.get("persona_id")
    _round = int(_ctx.get("round_index") or 0)
    # ── ① 危机禁用词（诊断 / 处方 / 边界） ──
    crisis = getattr(state, "crisis_detector", None)
    if crisis is not None:
        try:
            violations = crisis.check_response_prohibited(text)
        except Exception:
            violations = []
        if violations and _sid:
            try:
                audit.emit_crisis_hit(
                    session_id=_sid, phase=_phase, persona_id=_persona,
                    hit_type="prohibited",
                    keywords=[v.split("] ", 1)[-1] if "] " in v else v for v in violations],
                    round_index=_round,
                )
            except Exception:
                log.debug("[roundtable] crisis_hit audit emit failed", exc_info=True)
        for v in violations:
            word = v.split("] ", 1)[-1] if "] " in v else v
            text = text.replace(word, "（此处表述不当，已移除）")
    # ── ② 偏见话术（5 类 × ~12 条） ──
    try:
        from .bias_detector import BiasDetector  # 延迟 import 避免循环
        result = BiasDetector.get_default().sanitize(text, audit_context=audit_context)
        if result.hit and _sid:
            try:
                audit.emit_bias_hit(
                    session_id=_sid, phase=_phase, persona_id=_persona,
                    categories=sorted({v.category for v in result.violations}),
                    patterns=[v.pattern for v in result.violations],
                    raw_snippet=text[:80],
                    round_index=_round,
                )
            except Exception:
                log.debug("[roundtable] bias_hit audit emit failed", exc_info=True)
        text = result.text
    except Exception:
        log.exception("[roundtable] bias sanitize failed · falling back to pre-bias text")
    return text


async def _run_crisis_check(session_id: str, question: str) -> bool:
    """检测用户问题的危机级别，推送 crisis SSE 事件

    返回：
      - True  · RED（自杀自伤）→ pipeline 应该中断
      - False · 其他级别 → pipeline 继续（YELLOW/ORANGE 已推安全引导）
    """
    detector = getattr(state, "crisis_detector", None)
    if detector is None:
        return False
    try:
        result = detector.detect(question)
    except Exception:
        log.exception("[roundtable] crisis detection failed")
        return False

    if result.level.name == "GREEN":
        return False

    # 发出 crisis 事件（前端 CrisisBanner 消费）
    payload: dict = {
        "type": "crisis",
        "level": result.level.name,  # "YELLOW" / "ORANGE" / "RED"
        "matched_keywords": result.matched_keywords,
    }
    if result.response_template:
        payload["template"] = result.response_template
    if result.level.name in ("ORANGE", "RED"):
        payload["hotlines"] = detector.get_hotlines(3)
    await _emit(session_id, payload)

    log.info(
        "[roundtable] crisis detected · session=%s level=%s kw=%s",
        session_id, result.level.name, result.matched_keywords,
    )
    # Day 5 · D5.5 · audit
    try:
        _sess = _sessions.get(session_id)
        audit.emit_crisis_hit(
            session_id=session_id, phase=None, persona_id=None,
            hit_type=f"input_{result.level.name.lower()}",
            keywords=list(result.matched_keywords or []),
            round_index=getattr(_sess, "round_index", 0) if _sess else 0,
        )
    except Exception:
        log.debug("[roundtable] crisis input audit emit failed", exc_info=True)
    return result.level.name == "RED"


# ═══════════════════════════════════════════════════════════════════
# Session 生命周期
# ═══════════════════════════════════════════════════════════════════

def create_session(
    personas: list[str],
    question: str,
    parent_id: Optional[str] = None,
    backend: Optional[str] = None,
    inject_context: Optional[str] = None,
    deep_mode: bool = False,
) -> RoundtableSession:
    """创建新的圆桌讨论 session（仅建状态，不启动 pipeline）。

    pipeline 由 SSE 订阅触发（GET /api/roundtable/stream/{id}），
    避免无人订阅却产生事件丢失。

    Args:
        backend: Day 5 · E · 用户选定的 LLM backend（gemini/kimi/glm/...）；
            None 则在 _stream_one_agent_via_llm 里回退到 _get_default_backend()。
        inject_context: Day 7 · 首轮 RAG 注入的上下文字符串（前端在 Setup 页
            预览后拼好传入）。存入 session.current_inject_context 后会在
            `_build_prior_context_block` 里随 prompt 注入所有 3 agent 的
            phase1/phase2 调用。仅对首轮生效，后续 continue 会用新的覆盖。
    """
    session_id = f"rt_{uuid.uuid4().hex[:12]}"
    now = datetime.now()
    session = RoundtableSession(
        id=session_id,
        parent_id=parent_id,
        personas=personas,
        question=question,
        backend=backend,
        phase="setup",
        phase1=[RoundtableAgentBuffer(persona_id=p) for p in personas],
        phase2=[RoundtableAgentBuffer(persona_id=p) for p in personas],
        moderator=None,
        current_inject_context=(inject_context or "").strip(),
        deep_mode=deep_mode,
        created_at=now,
        updated_at=now,
    )
    _sessions[session_id] = session
    _queues[session_id] = asyncio.Queue()
    _subscribed[session_id] = asyncio.Event()
    _save_session(session)
    log.info(
        "[roundtable] session created · id=%s personas=%s parent=%s backend=%s inject=%dchars deep=%s",
        session_id, personas, parent_id, backend or "(default)",
        len(session.current_inject_context), deep_mode,
    )
    # Day 5 · D5.5 · audit
    try:
        audit.emit_session_created(
            session_id=session_id, personas=list(personas), question=question,
            backend=backend, parent_id=parent_id,
            round_index=getattr(session, "round_index", 0),
        )
    except Exception:
        log.debug("[roundtable] session_created audit emit failed", exc_info=True)
    return session


def get_session(session_id: str) -> Optional[RoundtableSession]:
    """从内存获取 session（落盘恢复留待 Day 4 完善）"""
    return _sessions.get(session_id)


async def interrupt_session(session_id: str) -> bool:
    """中断 session 的 pipeline 任务（DAG 分叉的前置步骤）

    Returns:
        True 表示成功中断；False 表示 session 不存在或已完成
    """
    task = _tasks.get(session_id)
    if not task or task.done():
        return False
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    log.info("[roundtable] session interrupted · id=%s", session_id)
    return True


# ═══════════════════════════════════════════════════════════════════
# Day 6 · 多轮对话形态 A · 继续追问（归档当前轮 → 重置 → 等 SSE trigger）
# ═══════════════════════════════════════════════════════════════════

def continue_session(
    session_id: str,
    question: str,
    *,
    inject_context: Optional[str] = None,
    deep_mode: Optional[bool] = None,
) -> RoundtableSession:
    """把 session 的当前轮归档到 rounds[]，然后用新 question 重置为 setup 状态。

    调用前提：
      - session.phase 必须是 `done`（避免打断进行中的讨论）
      - 新 question 经过 pydantic 校验（4-2000 字符，在 Request 层完成）

    Args:
        inject_context: Step 4 · 用户从「聊天记录/知识手册」预览界面选好的注入文本；
            为空则本轮不注入。存储在 session.current_inject_context，prompt 构造时读取。

    副作用：
      - session.rounds 追加一个 RoundtableRoundSnapshot
      - session.round_index += 1
      - session.question = 新问题
      - session.phase = "setup"
      - session.phase1/phase2/moderator/moderator_thinking 重置为空白
      - session.current_inject_context = inject_context or ""
      - `_queues[session_id]` 替换为新 Queue（旧 subscriber 已因 SENTINEL 退出）
      - `_subscribed[session_id]` 替换为新 Event，等新 SSE 订阅 trigger pipeline
      - `_tasks` 清除旧 task 引用

    Raises:
        KeyError · session 不存在
        ValueError · session 当前不处于 "done" 状态
    """
    session = _sessions.get(session_id)
    if session is None:
        raise KeyError(f"session {session_id} not found")
    if session.phase != "done":
        raise ValueError(
            f"session {session_id} is not done (current phase={session.phase}); "
            "cannot continue"
        )

    now = datetime.now()

    # ── 1. 把当前轮 snapshot 归档 ──
    snapshot = RoundtableRoundSnapshot(
        round_index=session.round_index,
        question=session.question,
        # 深拷贝 buffer（避免归档后又被新轮覆盖）
        phase1=[b.model_copy(deep=True) for b in session.phase1],
        phase2=[b.model_copy(deep=True) for b in session.phase2],
        moderator=session.moderator.model_copy(deep=True) if session.moderator else None,
        moderator_thinking=session.moderator_thinking or "",
        created_at=session.created_at,
        completed_at=session.updated_at,
    )
    session.rounds.append(snapshot)

    # ── 2. 重置为新一轮的 setup 状态 ──
    session.round_index = snapshot.round_index + 1
    session.question = question
    session.phase = "setup"
    session.phase1 = [RoundtableAgentBuffer(persona_id=p) for p in session.personas]
    session.phase2 = [RoundtableAgentBuffer(persona_id=p) for p in session.personas]
    session.moderator = None
    session.moderator_thinking = ""
    # Day 7 · 新一轮开始前重置降级标记（否则会把上一轮的 fallback_reason 带到新一轮）
    session.moderator_fallback_reason = None
    # Step 4 · 本轮的 RAG 注入（仅对本轮生效，下轮 continue 会被覆盖）
    session.current_inject_context = (inject_context or "").strip()
    # Day 7 · 深度模式 · None → 沿用上一轮；True/False → 本轮独立切换
    if deep_mode is not None:
        session.deep_mode = bool(deep_mode)
    session.updated_at = now

    # ── 3. 运行时状态重置 · 让新 SSE 订阅能重新 trigger pipeline ──
    _queues[session_id] = asyncio.Queue()
    _subscribed[session_id] = asyncio.Event()
    _tasks.pop(session_id, None)

    _save_session(session)
    log.info(
        "[roundtable] session continued · id=%s round_index=%d (rounds=%d) inject=%dchars deep=%s q=%r",
        session_id, session.round_index, len(session.rounds),
        len(session.current_inject_context), session.deep_mode, question[:60],
    )
    # Day 5 · D5.5 · audit · 新一轮也算 session_created（同一 session_id 下 round_index 递增）
    try:
        audit.emit_session_created(
            session_id=session_id, personas=list(session.personas),
            question=question, backend=session.backend, parent_id=session.parent_id,
            round_index=session.round_index,
        )
    except Exception:
        log.debug("[roundtable] continue audit emit failed", exc_info=True)
    return session


# ═══════════════════════════════════════════════════════════════════
# Day 6 · Step 4 · RAG 注入预览（聊天记录 + 知识手册）
# ═══════════════════════════════════════════════════════════════════

# 延迟 import · 避免循环：rag_service 引用了 state，不需要 service ↔ service 联动
def _rag() -> object:
    """延迟 import rag_service，避免模块加载序带来的循环或重量化"""
    from . import rag_service  # noqa: WPS433
    return rag_service


def build_inject_preview(
    query: str,
    modes: list[str],
    *,
    top_k: int = 5,
    chat_preview_chars: int = 400,
) -> dict:
    """Day 6 · Step 4 · 给定查询，返回聊天记录 + 知识手册的命中预览。

    返回结构与 RoundtableInjectPreviewResponse 对齐，但直接返回 dict 便于路由层 model_validate。

    不改 session 状态；前端可以根据返回的 hits 让用户勾选，然后在 continue 请求里把
    拼好的 context 以 `inject_context` 字段传回。
    """
    rag = _rag()

    chat_hits: list[dict] = []
    knowledge_hits: list[dict] = []

    # ── 1. 聊天记录（enriched_search） ──
    if "chat_history" in modes:
        try:
            results = rag.enriched_search(query, top_k=top_k)  # type: ignore[attr-defined]
        except Exception:
            log.exception("[roundtable] inject preview · chat_history search failed")
            results = []
        for r in results:
            conv = r.get("conv", {}) or {}
            enriched = r.get("enriched", {}) or {}
            text = conv.get("conversation_text", "") or ""
            preview = text[:chat_preview_chars] + ("…" if len(text) > chat_preview_chars else "")
            # chunk_id 兜底：conv.metadata.chunk_id 或 conv.conversation_id
            chunk_id = (
                (conv.get("metadata") or {}).get("chunk_id")
                or conv.get("conversation_id")
                or ""
            )
            analysis_summary = ""
            try:
                analysis_summary = rag.fmt_enriched_summary(enriched)  # type: ignore[attr-defined]
            except Exception:
                analysis_summary = ""
            chat_hits.append({
                "chunk_id": str(chunk_id),
                "preview": preview,
                "days": enriched.get("days", []) or [],
                "chunk_type": enriched.get("chunk_type")
                    or (conv.get("metadata") or {}).get("chunk_type", "normal"),
                "analysis_summary": analysis_summary,
                "score": float(r.get("score", 0.0)),
            })

    # ── 2. 知识手册（search_faq） ──
    if "knowledge" in modes:
        try:
            faq_results = rag.search_faq(query, top_k=top_k)  # type: ignore[attr-defined]
        except Exception:
            log.exception("[roundtable] inject preview · knowledge search failed")
            faq_results = []
        for e in faq_results:
            knowledge_hits.append({
                "category": e.get("category", ""),
                "question": e.get("question", ""),
                "answer": e.get("answer", ""),
                "keywords": e.get("keywords", []) or [],
                "score": 0.0,  # search_faq 目前不返回 score
            })

    # ── 3. 建议的 context（把 top 命中拼成 markdown 格式）──
    suggested_parts: list[str] = []
    if chat_hits:
        chat_lines = ["【相关历史对话片段】"]
        for i, h in enumerate(chat_hits[:top_k], start=1):
            day_tag = f"第{','.join(str(d) for d in h['days'])}天" if h["days"] else "时间未知"
            type_tag = {"conflict": "冲突", "sweet": "甜蜜", "normal": "日常"}.get(
                h.get("chunk_type", "normal"), h.get("chunk_type", "normal"),
            )
            header = f"片段 {i}（{day_tag} · {type_tag}）"
            if h["analysis_summary"]:
                header += f"\n分析：{h['analysis_summary']}"
            chat_lines.append(f"{header}\n{h['preview']}")
        suggested_parts.append("\n\n".join(chat_lines))

    if knowledge_hits:
        kn_lines = ["【专业知识手册】"]
        for e in knowledge_hits[:top_k]:
            q = e.get("question", "").strip()
            a = e.get("answer", "").strip()
            if q or a:
                kn_lines.append(f"Q: {q}\nA: {a}")
        suggested_parts.append("\n\n".join(kn_lines))

    suggested_context = "\n\n".join(suggested_parts)

    return {
        "chat_history": chat_hits,
        "knowledge": knowledge_hits,
        "suggested_context": suggested_context,
    }


# ═══════════════════════════════════════════════════════════════════
# SSE 订阅 + Pipeline trigger
# ═══════════════════════════════════════════════════════════════════

async def subscribe(session_id: str) -> AsyncIterator[dict]:
    """SSE 订阅器：yield 每个 backend event（dict）。

    第一次订阅时 trigger pipeline（避免无人订阅丢失事件）。
    断线重连：当前不支持事件回放，Day 4 加 seq + Last-Event-ID。
    """
    session = _sessions.get(session_id)
    if session is None:
        # 推一个 error event 后立即结束
        yield {"type": "error", "message": f"Session {session_id} not found"}
        return

    queue = _queues[session_id]

    # Trigger pipeline（仅一次）
    sub_event = _subscribed[session_id]
    if not sub_event.is_set():
        sub_event.set()
        _tasks[session_id] = asyncio.create_task(_run_pipeline(session_id))

    # 持续读取队列直到 SENTINEL
    try:
        while True:
            event = await queue.get()
            if event is SENTINEL_DONE:
                break
            yield event
    except asyncio.CancelledError:
        log.info("[roundtable] subscriber disconnected · session=%s", session_id)
        raise


async def _emit(session_id: str, event: dict) -> None:
    """把 event 推入 session 的 queue（非阻塞）"""
    queue = _queues.get(session_id)
    if queue is not None:
        await queue.put(event)


# ═══════════════════════════════════════════════════════════════════
# Pipeline 主流程
# ═══════════════════════════════════════════════════════════════════

async def _run_pipeline(session_id: str) -> None:
    """3-phase pipeline 主任务（在 subscribe 触发后台运行）"""
    session = _sessions[session_id]
    # Day 5 · D5.5 · 记录整个 pipeline 时间
    _pipeline_t0 = time.perf_counter()
    _round = getattr(session, "round_index", 0)
    _errors = 0  # session_done 聚合计数
    try:
        # ── D4.3 · 危机检测（入口）──
        # RED → 直接中断 pipeline + 推 safety banner + done
        # ORANGE/YELLOW → 推 safety banner（前端 CrisisBanner 显示），继续 pipeline
        red_crisis = await _run_crisis_check(session_id, session.question)
        if red_crisis:
            await _advance_phase(session_id, "done")
            return

        # ── Phase 1 · 3 agent 并发独立分析 ──
        await _advance_phase(session_id, "phase1")
        _p1_t0 = time.perf_counter()
        audit.emit_phase_start(session_id=session_id, phase="phase1", round_index=_round)
        await asyncio.gather(*[
            _stream_one_agent(session_id, "phase1", pid)
            for pid in session.personas
        ])
        audit.emit_phase_end(
            session_id=session_id, phase="phase1",
            duration_s=time.perf_counter() - _p1_t0, round_index=_round,
        )
        await asyncio.sleep(PHASE_PAUSE)

        # ── Phase 2 · 3 agent 并发交叉回应 ──
        await _advance_phase(session_id, "phase2")
        _p2_t0 = time.perf_counter()
        audit.emit_phase_start(session_id=session_id, phase="phase2", round_index=_round)
        await asyncio.gather(*[
            _stream_one_agent(session_id, "phase2", pid)
            for pid in session.personas
        ])
        audit.emit_phase_end(
            session_id=session_id, phase="phase2",
            duration_s=time.perf_counter() - _p2_t0, round_index=_round,
        )
        await asyncio.sleep(PHASE_PAUSE)

        # ── Phase 3 · Moderator 综合（优先 LLM，失败 fallback 规则）──
        await _advance_phase(session_id, "phase3")
        _mod_t0 = time.perf_counter()
        audit.emit_phase_start(session_id=session_id, phase="phase3", round_index=_round)
        moderator: Optional[RoundtableModeratorContent] = None
        thinking_text: str = ""
        fallback_reason: Optional[str] = None  # D5.5 · moderator fallback 原因
        if USE_LLM and MODERATOR_USE_LLM:
            try:
                audit.get_auditor().emit(
                    session_id=session_id, event_type="moderator_start",
                    round_index=_round, phase="phase3",
                    data={"backend": session.backend or _get_default_backend()},
                )
            except Exception:
                log.debug("[roundtable] moderator_start audit emit failed", exc_info=True)
            try:
                result = await _build_llm_moderator(session)
            except Exception as _exc:
                log.exception(
                    "[roundtable] moderator LLM unexpected error · session=%s · fallback",
                    session_id,
                )
                result = None
                fallback_reason = f"exception:{type(_exc).__name__}"
            if result is not None:
                moderator, thinking_text = result
            elif fallback_reason is None:
                # _build_llm_moderator 返回 None · 一般是 timeout 或 JSON 解析失败
                fallback_reason = "llm_returned_none"
        else:
            fallback_reason = "llm_disabled"
        if moderator is None:
            log.info("[roundtable] moderator using rule template · session=%s", session_id)
            moderator = _build_rule_moderator(session)
            thinking_text = ""  # 规则模板无 thinking 段
        # 先 emit 思考段（前端做打字机假流式），再 emit 最终 JSON
        if thinking_text:
            await _emit(session_id, {
                "type": "moderator_thinking",
                "text": thinking_text,
            })
        session.moderator = moderator
        # Day 6 · thinking 持久化到 session，供 snapshot + 刷新恢复
        session.moderator_thinking = thinking_text or ""
        # Day 7 · 持久化降级原因 · 前端据此显示"无记忆模式"提示条
        session.moderator_fallback_reason = fallback_reason
        session.updated_at = datetime.now()
        _save_session(session)
        await _emit(session_id, {
            "type": "moderator",
            "content": moderator.model_dump(),
            # Day 7 · 前端据此在 ModeratorCard 上方渲染「LLM 失败 · 规则模板 · 本轮无记忆」提示条
            "fallback_reason": fallback_reason,
        })
        audit.emit_moderator_done(
            session_id=session_id,
            duration_s=time.perf_counter() - _mod_t0,
            fallback_reason=fallback_reason,
            thinking_len=len(thinking_text or ""),
            content_keys=list(moderator.model_dump().keys()),
            round_index=_round,
        )
        audit.emit_phase_end(
            session_id=session_id, phase="phase3",
            duration_s=time.perf_counter() - _mod_t0, round_index=_round,
        )

        # ── 完成 ──
        await _advance_phase(session_id, "done")
        await _emit(session_id, {"type": "done"})

    except asyncio.CancelledError:
        log.info("[roundtable] pipeline cancelled · session=%s", session_id)
        await _emit(session_id, {"type": "error", "message": "讨论已被用户中断"})
        _errors += 1
        raise
    except Exception as exc:
        log.exception("[roundtable] pipeline crashed · session=%s", session_id)
        _errors += 1
        await _emit(session_id, {
            "type": "error",
            "message": f"内部错误：{type(exc).__name__}",
        })
    finally:
        # Day 5 · D5.5 · session 总结事件
        try:
            _err_bufs = sum(
                1 for bufs in (session.phase1, session.phase2)
                for b in bufs if b.status == "error"
            )
            audit.emit_session_done(
                session_id=session_id,
                total_duration_s=time.perf_counter() - _pipeline_t0,
                first_agent_chunk_s=None,  # 该指标由调用方/SSE 侧测量
                total_events=0,           # 同上，audit 不统计 SSE 事件数
                errors_count=_errors + _err_bufs,
                rewrite_count_total=0,    # 如需统计，GuardedEmitter.rewrite_count 可累加暴露
                round_index=_round,
            )
        except Exception:
            log.debug("[roundtable] session_done audit emit failed", exc_info=True)
        # 推 sentinel 让所有 subscriber 优雅退出
        await _emit(session_id, SENTINEL_DONE)


async def _advance_phase(session_id: str, phase: RoundtablePhase) -> None:
    """推进 phase 状态 + 推送 phase_advance 事件"""
    session = _sessions[session_id]
    session.phase = phase
    session.updated_at = datetime.now()
    await _emit(session_id, {"type": "phase_advance", "phase": phase})


async def _stream_one_agent(
    session_id: str,
    phase: RoundtableAgentPhase,
    persona_id: str,
) -> None:
    """单 agent 完整流式过程：typing → streaming（逐字/逐 token）→ done

    优先走真 LLM（USE_LLM=1 + prompts.yaml 渲染成功）；任何失败 fallback 到 mock。
    Phase 2 末尾提取 `[置信度: 0.xx]`（缺失则用 0.75 默认 + log warning）。
    """
    session = _sessions[session_id]
    _round = getattr(session, "round_index", 0)
    _agent_t0 = time.perf_counter()  # Day 5 · D5.5 · 单 agent 总耗时

    try:
        # ── typing 阶段 ──
        await _set_agent_status(session_id, phase, persona_id, "typing")
        await asyncio.sleep(TYPING_DELAY_MIN + random.random() * TYPING_DELAY_JITTER)

        # ── 构造 prompt ──
        prompt: Optional[str] = None
        if USE_LLM:
            if phase == "phase1":
                prompt = _build_phase1_prompt(persona_id, session)
            else:
                prompt = _build_phase2_prompt(persona_id, session)

        # ── streaming 阶段 ──
        await _set_agent_status(session_id, phase, persona_id, "streaming")
        buf = _get_agent_buffer(session, phase, persona_id)
        # Day 5 · D5.5 · audit
        try:
            audit.get_auditor().emit(
                session_id=session_id,
                event_type="agent_streaming_start",
                round_index=_round,
                persona_id=persona_id,
                phase=phase,
            )
        except Exception:
            log.debug("[roundtable] agent_streaming_start audit emit failed", exc_info=True)

        used_llm = False
        if prompt:
            try:
                await _stream_one_agent_via_llm(
                    session_id, phase, persona_id, prompt, buf,
                )
                used_llm = True
            except Exception as exc:
                log.warning(
                    "[roundtable] LLM failed · session=%s phase=%s persona=%s · fallback to mock · %s",
                    session_id, phase, persona_id, exc,
                )
                # fallback 前清空 buf.text（避免部分 LLM 输出 + mock 拼接）
                buf.text = ""

        if not used_llm:
            await _stream_one_agent_via_mock(
                session_id, phase, persona_id, session, buf,
            )

        # ── 置信度处理 ──
        if phase == "phase2":
            extracted = _extract_confidence(buf.text)
            if extracted is not None:
                # 从显示文本里移除 [置信度: 0.xx] 标记（前端不需看到）
                cleaned = _strip_confidence_marker(buf.text)
                if cleaned != buf.text:
                    # 通知前端清理最后一行（发送一个 strip_tail 事件）
                    strip_len = len(buf.text) - len(cleaned)
                    buf.text = cleaned
                    await _emit(session_id, {
                        "type": "agent_strip_tail",
                        "agent_id": persona_id,
                        "phase": phase,
                        "strip_chars": strip_len,
                    })
                confidence = extracted
            else:
                confidence = round(0.70 + random.random() * 0.20, 2)
                log.info(
                    "[roundtable] phase2 confidence missing · persona=%s · default=%.2f",
                    persona_id, confidence,
                )
        else:
            # phase1 暂不抽 confidence（mock 保留随机值，用于 agent_done 事件）
            confidence = round(0.70 + random.random() * 0.20, 2)

        # ── 输出 sanitize（诊断词/绝对化/处方替换）──
        # Day 5 · D5.5 · 兜底复核也带 audit_context，命中走 bias_hit / crisis_hit 事件
        clean_text = _sanitize_agent_output(
            buf.text,
            audit_context={
                "session_id": session_id, "persona_id": persona_id,
                "phase": phase, "round_index": _round,
            },
        )
        if clean_text != buf.text:
            buf.text = clean_text  # 仅更新 buffer（前端已收 chunk，后面 rerun 才会看到）

        # ── done 阶段 ──
        buf.status = "done"
        buf.confidence = confidence
        await _emit(session_id, {
            "type": "agent_done",
            "agent_id": persona_id,
            "phase": phase,
            "confidence": confidence,
        })
        # Day 5 · D5.5 · audit
        try:
            audit.emit_agent_done(
                session_id=session_id, phase=phase, persona_id=persona_id,
                duration_s=time.perf_counter() - _agent_t0,
                chunk_count=0,  # GuardedEmitter 内部统计 · 可未来 wire 出来
                text_len=len(buf.text),
                confidence=confidence,
                round_index=_round,
            )
        except Exception:
            log.debug("[roundtable] agent_done audit emit failed", exc_info=True)

    except asyncio.CancelledError:
        # 父 pipeline 被取消时一并中断
        raise
    except Exception as exc:
        log.exception(
            "[roundtable] agent crashed · session=%s phase=%s persona=%s",
            session_id, phase, persona_id,
        )
        buf = _get_agent_buffer(session, phase, persona_id)
        buf.status = "error"
        buf.error = str(exc)
        await _emit(session_id, {
            "type": "agent_error",
            "agent_id": persona_id,
            "phase": phase,
            "error": f"{type(exc).__name__}: {exc}",
        })
        # Day 5 · D5.5 · audit
        try:
            audit.emit_agent_error(
                session_id=session_id, phase=phase, persona_id=persona_id,
                error=f"{type(exc).__name__}: {exc}",
                round_index=_round,
            )
        except Exception:
            log.debug("[roundtable] agent_error audit emit failed", exc_info=True)


# ═══════════════════════════════════════════════════════════════════
# Day 4 · D4.1 · GuardedEmitter · 安全 chunk 流
# ═══════════════════════════════════════════════════════════════════

# 触发 flush 的累积字符阈值（token 级流式收敛为"有意义短语"后再展示）
GUARDED_FLUSH_THRESHOLD: int = int(os.environ.get("ROUNDTABLE_FLUSH_THRESHOLD", "16"))

# 句末标点（任一出现即立刻 flush，避免"刚好在危险词前截断"的错位）
# 中英混用常见：。！？；. ! ? ; 换行
_SENTENCE_ENDERS: frozenset[str] = frozenset("。！？；.!?;\n")


class GuardedEmitter:
    """流式输出的"安全闸门"。

    调用方按 token 喂进 `feed(token)`；emitter 累积到
      ① ≥ `flush_threshold` 字符，或
      ② 结尾遇到句末标点（SENTENCE_ENDERS）
    时调用 `_flush()` → 对待 flush 的 chunk 跑 `sanitize_fn`（默认 crisis 词替换；
    D4.7 BiasDetector 集成后会在这里叠加一层偏见规则过滤）→ 更新 `buf.text` →
    emit `agent_chunk` SSE 事件。

    Day 4 设计要点：
      - **flush 前替换**：不让危险词在流式过程中被用户看到（即使极短延迟）
      - **跨 chunk 兜底**：`_stream_one_agent` 末尾仍对 `buf.text` 跑一次整段
        `_sanitize_agent_output`，捕获被 chunk 边界切开的禁用词
      - **可测试**：`sanitize_fn` 为可替换注入点 · 单测里可以用 identity
    """

    def __init__(
        self,
        session_id: str,
        phase: RoundtableAgentPhase,
        persona_id: str,
        buf: RoundtableAgentBuffer,
        *,
        sanitize_fn: Optional["callable"] = None,  # type: ignore[name-defined]
        flush_threshold: int = GUARDED_FLUSH_THRESHOLD,
    ) -> None:
        self._session_id = session_id
        self._phase = phase
        self._persona_id = persona_id
        self._buf = buf
        self._sanitize_fn = sanitize_fn or _sanitize_agent_output
        self._flush_threshold = flush_threshold
        self._pending: str = ""
        # 统计：flush 次数 / 被改写次数（for audit log · D7.1.d 引用）
        self.flush_count: int = 0
        self.rewrite_count: int = 0

    async def feed(self, token: str) -> None:
        """喂入一个 token（可以是单字或多字）"""
        if not token:
            return
        self._pending += token
        if self._should_flush():
            await self._flush()

    def _should_flush(self) -> bool:
        if not self._pending:
            return False
        if len(self._pending) >= self._flush_threshold:
            return True
        return self._pending[-1] in _SENTENCE_ENDERS

    async def _flush(self) -> None:
        """把 pending 交给 sanitize_fn → 更新 buf → emit

        sanitize_fn 支持两种签名：
          - `(text) -> str`                        （向后兼容 · 单测注入 identity）
          - `(text, audit_context=dict) -> str`    （默认 `_sanitize_agent_output`）
        """
        if not self._pending:
            return
        raw = self._pending
        audit_ctx = {
            "session_id": self._session_id,
            "persona_id": self._persona_id,
            "phase": self._phase,
        }
        try:
            try:
                chunk = self._sanitize_fn(raw, audit_context=audit_ctx)  # type: ignore[call-arg]
            except TypeError:
                chunk = self._sanitize_fn(raw)
        except Exception:
            log.exception("[roundtable] GuardedEmitter sanitize failed · falling back to raw")
            chunk = raw
        if chunk != raw:
            self.rewrite_count += 1
        if chunk:
            self._buf.text += chunk
            await _emit(self._session_id, {
                "type": "agent_chunk",
                "agent_id": self._persona_id,
                "phase": self._phase,
                "delta": chunk,
            })
        self.flush_count += 1
        self._pending = ""

    async def finalize(self) -> None:
        """流结束时调用 · 把残留 pending flush 掉"""
        await self._flush()


async def _stream_one_agent_via_llm(
    session_id: str,
    phase: RoundtableAgentPhase,
    persona_id: str,
    prompt: str,
    buf: RoundtableAgentBuffer,
) -> None:
    """真 LLM 路径：调 _call_llm_stream · 通过 GuardedEmitter 安全推送

    backend 解析优先级（Day 5 · E）：
      1. session.backend （用户在 UI 下拉选定）
      2. env `ROUNDTABLE_BACKEND`
      3. model_preferences.json chat_backend
      4. fallback 链（gemini → kimi → deepseek → ...）

    Day 4 · D4.1：token 经 GuardedEmitter 累积 + sanitize 后再 emit，
    避免 token 级禁用词流式泄漏。
    """
    session = _sessions.get(session_id)
    backend = (session and session.backend) or _get_default_backend()
    # Day 7 · 深度模式 · token 预算翻倍（DEFAULT_MAX_TOKENS → DEEP_MAX_TOKENS）
    max_tokens = DEEP_MAX_TOKENS if (session and session.deep_mode) else DEFAULT_MAX_TOKENS
    emitter = GuardedEmitter(session_id, phase, persona_id, buf)
    try:
        async for token in _call_llm_stream(backend, prompt, max_tokens=max_tokens):
            if not token:
                continue
            await emitter.feed(token)
            # token 间加极短 jitter，保持 3 列错位视觉
            if random.random() < 0.25:
                await asyncio.sleep(random.random() * 0.015)
    finally:
        await emitter.finalize()


async def _stream_one_agent_via_mock(
    session_id: str,
    phase: RoundtableAgentPhase,
    persona_id: str,
    session: RoundtableSession,
    buf: RoundtableAgentBuffer,
) -> None:
    """Mock 路径：用 _generate_mock_text 的预制文本 · 通过 GuardedEmitter 逐字推送"""
    text = _generate_mock_text(session, phase, persona_id)
    emitter = GuardedEmitter(session_id, phase, persona_id, buf)
    try:
        for ch in text:
            await emitter.feed(ch)
            await asyncio.sleep(STREAM_CHAR_INTERVAL + random.random() * STREAM_JITTER)
    finally:
        await emitter.finalize()


async def _set_agent_status(
    session_id: str,
    phase: RoundtableAgentPhase,
    persona_id: str,
    status: RoundtableAgentStatus,
) -> None:
    """更新 agent 状态 + 推送 agent_status 事件"""
    session = _sessions[session_id]
    buf = _get_agent_buffer(session, phase, persona_id)
    buf.status = status
    await _emit(session_id, {
        "type": "agent_status",
        "agent_id": persona_id,
        "phase": phase,
        "status": status,
    })


def _get_agent_buffer(
    session: RoundtableSession,
    phase: RoundtableAgentPhase,
    persona_id: str,
) -> RoundtableAgentBuffer:
    bufs = session.phase1 if phase == "phase1" else session.phase2
    for b in bufs:
        if b.persona_id == persona_id:
            return b
    raise KeyError(f"agent buffer not found · phase={phase} persona={persona_id}")


# ═══════════════════════════════════════════════════════════════════
# Mock 文本生成（Day 3 临时方案 · Day 4 切真实 LLM）
# ═══════════════════════════════════════════════════════════════════

def _generate_mock_text(
    session: RoundtableSession,
    phase: RoundtableAgentPhase,
    persona_id: str,
) -> str:
    """生成 mock agent 文本（带上用户问题关键词，让用户感知 agent 看见了问题）

    Day 4 替换为：真实 LLM 调用 + roundtable_prompts.yaml 的 system prompt
    """
    name = PERSONA_NAMES.get(persona_id, persona_id)
    question_excerpt = session.question[:60].replace("\n", " ")
    if len(session.question) > 60:
        question_excerpt += "…"

    if phase == "phase1":
        templates: dict[str, str] = {
            "neutral": (
                f"我先帮你把现在的情况拆开看：你提到「{question_excerpt}」。"
                f"这里有几层需要分别看：先把「事实」和「你对事实的解读」分开，"
                f"再把「想要的结果」和「能做到的下一步」分开。这两次拆解之后，"
                f"你会发现真正卡住你的可能不是问题本身，而是某个被反复确认的恐惧。"
            ),
            "supportive": (
                f"听到你说「{question_excerpt}」，我能感受到你此刻是带着委屈和疲惫的。"
                f"先别急着寻找答案——你愿意告诉我，这件事里最让你心酸的瞬间是哪一个吗？"
                f"我想先在那里陪你一会，再一起想接下来怎么办。"
            ),
            "psychoanalytic": (
                f"你描述的「{question_excerpt}」，让我想问一个更早的问题：在你成长的过程中，"
                f"当你感到被忽视或不被理解时，身边的人通常怎么回应你？"
                f"我们在伴侣身上常常重演的，是更早那段关系里没被接住的部分。"
            ),
            "eft": (
                f"在「{question_excerpt}」之下，可能藏着一个更底层的依恋需求："
                f"我想确认——在 ta 眼里，我是被在乎的吗？"
                f"愤怒和疏离常常是依恋受伤时的保护层。如果暂时把它们放下，"
                f"你想让 ta 看见的是什么？"
            ),
            "bowen": (
                f"从家庭系统的视角看你说的「{question_excerpt}」，我想问："
                f"在你原生家庭里，处理冲突的方式通常是什么？"
                f"现在你和 ta 之间的这个模式，是不是某种代际剧本的延续？"
            ),
            "sociology": (
                f"「{question_excerpt}」这件事本身，带着社会脚本的痕迹——"
                f"性别、阶层、教育背景都在替你们「写台词」。"
                f"先看清结构，你才有可能从「应该怎样」的剧本里走出来，"
                f"做出一个更属于自己的选择。"
            ),
            "philosophy": (
                f"在问「{question_excerpt}」之前，也许可以先问自己："
                f"我希望被如何在乎？什么样的关系才算「值得」？"
                f"存在主义会提醒我们：没有一段关系能给出终极答案，"
                f"但你可以选择用什么方式承担这份不确定。"
            ),
            "game_theory": (
                f"把「{question_excerpt}」放到博弈框架里看，关键不是单步输赢，"
                f"而是这是不是一次「长期重复博弈」。如果是，短期赢了反而会输掉信任资本。"
                f"先开口示弱的一方常常不是弱者，而是愿意付出「可信承诺」的那一方。"
            ),
            "cultural": (
                f"听到「{question_excerpt}」，我想温柔地提醒：在许多东亚家庭文化里，"
                f"「不说」「不计较」被当作美德。但这套叙事并不适用于所有关系。"
                f"先看清你身处的文化水，再决定要不要游向别处。"
            ),
        }
    else:  # phase2 · 动态引用实际在场的 peer（修复「幻觉引用」bug）
        # 拿到除自己外的 peer 名称（应为 2 个，因为 persona 强制 3 个）
        peer_ids = [p for p in session.personas if p != persona_id]
        peer_names = [PERSONA_NAMES.get(p, p) for p in peer_ids]
        if len(peer_names) >= 2:
            peer0, peer1 = peer_names[0], peer_names[1]
        elif len(peer_names) == 1:
            peer0 = peer1 = peer_names[0]
        else:
            peer0 = peer1 = "另一位同事"

        templates = {
            "neutral": (
                f"听了 {peer0} 和 {peer1} 从各自角度的解读后，我想做一个收敛的整合："
                f"问题不在你「太敏感」或「不够理性」，而在「{question_excerpt}」这件事里，"
                f"双方缺少一个安全谈论感受的渠道。这是可以被具体设计的。"
            ),
            "supportive": (
                f"我听见 {peer0} 和 {peer1} 都在帮你梳理结构，但我想再为你留一点空间——"
                f"先允许自己难过，再谈怎么办。「{question_excerpt}」很重要，"
                f"但你的感受比答案更重要。"
            ),
            "psychoanalytic": (
                f"和 {peer0} 的视角互补：在「{question_excerpt}」中，某种更早的剧本浮上来的那一刻，"
                f"也常常是防御机制重新启动的时刻。{peer1} 点出的那一层也值得深挖——"
                f"值得做的不是压下它，而是认出它。"
            ),
            "eft": (
                f"{peer0} 和 {peer1} 谈到的因素，其实都会在「{question_excerpt}」"
                f"这次具体的事件里具象化——情绪是最诚实的信号。"
                f"如果暂时放下那些分析，你想让 ta 看见的是什么？"
            ),
            "bowen": (
                f"{peer0} 的角度很重要。但系统视角会补充：这套互动模式通常由家庭代际传递。"
                f"在「{question_excerpt}」里，你有机会成为「打断它」的那一代。"
                f"{peer1} 提到的方向也值得继续探索。"
            ),
            "sociology": (
                f"{peer0} 把「{question_excerpt}」描述得很清楚，我想加一层："
                f"任何描述本身都不是中立的，它被性别与阶层的剧本塑造着。"
                f"{peer1} 提供的视角，也需要放进结构里校准——看清结构，选择才真正自由。"
            ),
            "philosophy": (
                f"{peer0} 和 {peer1} 都在做一件事：帮你把「{question_excerpt}」从模糊的难受，"
                f"翻译成可以选择的问题。这本身就是一种存在主义式的赋权。"
            ),
            "game_theory": (
                f"同意 {peer0} 的看法——任何行动的前提是情绪先被看见。"
                f"否则在「{question_excerpt}」里，任何「策略」都只是新一层的防御。"
                f"{peer1} 谈到的也可以被视为一种长期博弈的语境。"
            ),
            "cultural": (
                f"听到 {peer0} 谈到某种「选择」的可能性，我想温柔地提醒："
                f"在「{question_excerpt}」这件事里，选择从来不是在真空里发生的。"
                f"{peer1} 的看法也需要放进文化水中校准。"
            ),
        }

    return templates.get(persona_id, f"{name}：（暂无该流派的样本回应）")


# ═══════════════════════════════════════════════════════════════════
# LLM Moderator（Day 5 · C · 2026-04-19）· 主路
# 基于用户原问题 + 三位顾问 phase2 实际回应，让 LLM 生成真正贴合情境的综合
# 失败 fallback 到规则模板 _build_rule_moderator
# ═══════════════════════════════════════════════════════════════════

# 匹配 ```json ... ``` 或 ``` ... ``` 代码块围栏（容错 LLM 误包 markdown）
_JSON_FENCE_RE = re.compile(
    r"```(?:json)?\s*(\{[\s\S]*?\})\s*```",
    re.IGNORECASE,
)

# Moderator 两段式输出的分隔符（yaml prompt 约定）
_MODERATOR_SEP = "---JSON---"
# 匹配【综合思考】/ 【思考】 等常见 header（LLM 可能加，前端展示时去掉）
_THINKING_HEADER_RE = re.compile(
    r"^\s*(?:【(?:综合思考|思考|Thinking|Reasoning)】|#{1,3}\s*(?:综合思考|思考|Thinking))\s*",
    re.IGNORECASE,
)


def _split_moderator_output(raw: str) -> tuple[str, str]:
    """把 Moderator LLM 原始输出拆成 (thinking_text, json_payload)。

    支持三种情况：
      1. 含 `---JSON---` 分隔符（理想情况）
      2. 无分隔符但前半自然语言 + 后半 `{...}`（退化情况）
      3. 纯 JSON（LLM 没按两段式指令走）· thinking 为空

    永远返回 (thinking, json_str)；两者都可能是空字符串。
    """
    if not raw:
        return "", ""
    text = raw.strip()

    # 情况 1 · 有 `---JSON---` 分隔符
    if _MODERATOR_SEP in text:
        thinking_part, _, json_part = text.partition(_MODERATOR_SEP)
        thinking_clean = _THINKING_HEADER_RE.sub("", thinking_part.strip()).strip()
        return thinking_clean, json_part.strip()

    # 情况 3 · 纯 JSON（以 { 开头）
    if text.startswith("{"):
        return "", text

    # 情况 2 · 前半是自然语言，后半是 `{...}` · 找第一个 '{'
    brace_idx = text.find("{")
    if brace_idx > 0:
        thinking_clean = _THINKING_HEADER_RE.sub("", text[:brace_idx].strip()).strip()
        return thinking_clean, text[brace_idx:].strip()

    # 兜底：全部当 thinking，json 为空（上层会 fallback）
    return text, ""


def _parse_moderator_json(raw: str) -> Optional[RoundtableModeratorContent]:
    """从 LLM 原始输出里解析出 RoundtableModeratorContent。

    容错三种常见包装：
      1. 纯 JSON（理想情况）
      2. ```json ... ``` 代码块围栏
      3. 前后有多余的说明文字 · 尝试找第一个 '{' 到最后一个 '}'

    字段校验交给 Pydantic（model_validate）。失败返回 None → 上层 fallback。
    """
    if not raw:
        return None
    raw = raw.strip()

    # 若被代码块围栏包裹，提取内部 JSON
    m = _JSON_FENCE_RE.search(raw)
    if m:
        raw = m.group(1)

    # 若仍有前后多余文字，裁到第一个 { 和最后一个 }
    if not raw.startswith("{"):
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            raw = raw[start : end + 1]

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None

    if not isinstance(data, dict):
        return None

    # 基本字段完整性 + 非空检查
    for key in ("seen", "angles", "tries", "doubts", "lens", "limit"):
        if key not in data:
            return None
    if not (isinstance(data["angles"], list) and len(data["angles"]) >= 2):
        return None
    if not (isinstance(data["tries"], list) and len(data["tries"]) >= 2):
        return None
    if not (isinstance(data["doubts"], list) and len(data["doubts"]) >= 1):
        return None

    try:
        return RoundtableModeratorContent.model_validate(data)
    except Exception:
        return None


async def _build_llm_moderator(
    session: RoundtableSession,
    backend: Optional[str] = None,
) -> Optional[tuple[RoundtableModeratorContent, str]]:
    """LLM 一次性生成 Moderator 综合（非流式）。

    成功返回 `(content, thinking_text)` tuple；任何失败/超时/解析失败 → None（上层 fallback）。

    - `content`：6 段 JSON 解析后的 RoundtableModeratorContent
    - `thinking_text`：LLM 先写的自然语言综合思考段（可能为空字符串，用于前端流式展示）

    使用 session.backend > 参数 backend > _get_default_backend() 的优先级。
    """
    prompts = _load_prompts()
    # Day 7 · 按 deep_mode 选择模板；深度模板缺失时 fallback 回普通模板
    tmpl_key = "deep_moderator_llm_prompt" if getattr(session, "deep_mode", False) else "moderator_llm_prompt"
    tmpl = prompts.get(tmpl_key) or prompts.get("moderator_llm_prompt")
    if not tmpl:
        log.warning("[roundtable] moderator_llm_prompt missing in yaml · fallback to rule")
        return None

    # ── 构造 peers_block · 按 phase2 confidence 降序 ──
    phase2_conf: dict[str, float] = {}
    for b in session.phase2:
        phase2_conf[b.persona_id] = b.confidence if b.confidence is not None else 0.75
    sorted_bufs = sorted(
        session.phase2,
        key=lambda b: phase2_conf.get(b.persona_id, 0.75),
        reverse=True,
    )
    peers_lines: list[str] = []
    for b in sorted_bufs:
        name = PERSONA_NAMES.get(b.persona_id, b.persona_id)
        conf = phase2_conf.get(b.persona_id, 0.75)
        text = (b.text or "").strip()
        if not text:
            text = "（此位顾问未能给出回应）"
        peers_lines.append(f"【{name}】（自评 {conf:.2f}）\n{text}")
    peers_block = "\n\n".join(peers_lines)

    # Day 7 · Moderator 视角的历史轮记忆（修复追问时 Moderator 像失忆的 bug）
    # 首轮 session.rounds=[] → 返回空串，不影响模板结构
    prior_context_block = _build_moderator_prior_context_block(session)

    try:
        prompt = tmpl.format(
            question=session.question,
            peers_block=peers_block,
            prior_context_block=prior_context_block,
        )
    except Exception:
        log.exception("[roundtable] failed to render moderator prompt")
        return None

    # ── backend 解析（与 _stream_one_agent_via_llm 同优先级）──
    bk = (
        getattr(session, "backend", None)
        or backend
        or _get_default_backend()
    )
    try:
        gen = get_generator(bk)
    except Exception as exc:
        log.warning("[roundtable] moderator LLM backend unavailable · backend=%s · %s", bk, exc)
        return None

    # Claude 官方 SDK 不支持 OpenAI 兼容（Day 4 遗留）· 直接 fallback
    if getattr(gen, "_claude_native", False):
        log.info("[roundtable] claude_native not supported for moderator · fallback to rule")
        return None

    # Day 7 · 深度模式 · Moderator token 预算也翻倍
    mod_max = DEEP_MODERATOR_MAX_TOKENS if getattr(session, "deep_mode", False) else MODERATOR_MAX_TOKENS
    kwargs: dict = dict(
        model=gen.model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=min(gen.max_tokens, mod_max),
    )
    if gen.temperature is not None and "think" not in gen.model.lower():
        kwargs["temperature"] = gen.temperature

    def _sync_call() -> str:
        """同步 OpenAI 客户端调用，返回 message content"""
        resp = gen.client.chat.completions.create(**kwargs)
        if not resp.choices:
            return ""
        return resp.choices[0].message.content or ""

    # Day 7 · 深度模式 timeout 独立（thinking 模型 + 3584 token 在 90s 内很容易超时 → 降级规则模板）
    mod_timeout = DEEP_MODERATOR_LLM_TIMEOUT if getattr(session, "deep_mode", False) else MODERATOR_LLM_TIMEOUT
    log.info(
        "[roundtable] moderator LLM call · session=%s · backend=%s · model=%s · deep=%s · timeout=%.0fs · max_tokens=%d",
        session.id, bk, gen.model, getattr(session, "deep_mode", False),
        mod_timeout, kwargs["max_tokens"],
    )
    loop = asyncio.get_event_loop()
    try:
        raw = await asyncio.wait_for(
            loop.run_in_executor(None, _sync_call),
            timeout=mod_timeout,
        )
    except asyncio.TimeoutError:
        log.warning(
            "[roundtable] moderator LLM timeout (%.0fs) · session=%s · backend=%s · model=%s · "
            "这会触发降级到规则模板 · 规则模板无跨轮记忆 · "
            "建议: 换用更快的 backend（如 kimi/deepseek）· 或导出 ROUNDTABLE_MODERATOR_TIMEOUT=300",
            mod_timeout, session.id, bk, gen.model,
        )
        return None
    except Exception as exc:
        log.warning(
            "[roundtable] moderator LLM call failed · session=%s · backend=%s · %s",
            session.id, bk, exc,
        )
        return None

    # 两段式拆分：thinking + JSON
    thinking_text, json_payload = _split_moderator_output(raw or "")

    content = _parse_moderator_json(json_payload)
    if content is None:
        log.warning(
            "[roundtable] moderator JSON parse failed · session=%s · raw[:200]=%r",
            session.id, (raw or "")[:200],
        )
        return None

    log.info(
        "[roundtable] moderator LLM success · session=%s · thinking=%d chars · angles=%d tries=%d doubts=%d",
        session.id, len(thinking_text), len(content.angles), len(content.tries), len(content.doubts),
    )
    return content, thinking_text


# ═══════════════════════════════════════════════════════════════════
# 规则 Moderator（Day 3 模板版 · Day 4 接 ConfidenceWeightedAggregator · Day 5 降级为 fallback）
# ═══════════════════════════════════════════════════════════════════

def _build_rule_moderator(session: RoundtableSession) -> RoundtableModeratorContent:
    """规则模板化的 Moderator 综合（Day 4 升级为置信度加权 · Day 7 加跨轮记忆承接）

    angles 按 phase2 的 confidence 降序排列（高置信度 persona 前置）。

    Day 7 · D7.1.j+ · 跨轮记忆降级路径修复（2026-04-30）：
      - 首轮（session.rounds 为空）→ 输出原静态模板（保持兼容）
      - 多轮（session.rounds 非空）→ seen/tries/doubts/lens 注入对上轮 Moderator
        自述的承接，避免「降级到规则模板」时第 2/3/N 轮看起来完全没记忆的体验落差。
      - LLM Moderator 路径走 `{prior_context_block}` 占位符（D7.1.j 已修）；本函数补
        全降级路径的同等承接能力，使任意 backend 失败时用户仍能感知到「这是第 N 轮」。
    """
    persona_names = [
        PERSONA_NAMES.get(p, p) for p in session.personas
    ]

    # ── D4.4 · 置信度加权排序 ──
    # 从 phase2 buffer 拿每个 persona 的 confidence（缺失用 0.75 默认）
    phase2_conf: dict[str, float] = {}
    for buf in session.phase2:
        phase2_conf[buf.persona_id] = (
            buf.confidence if buf.confidence is not None else 0.75
        )
    # 按 confidence 降序排序 personas
    sorted_personas = sorted(
        session.personas,
        key=lambda pid: phase2_conf.get(pid, 0.75),
        reverse=True,
    )
    # 生成 angles 时带上 confidence badge（可选小字体）
    angles = []
    for pid in sorted_personas:
        name = PERSONA_NAMES.get(pid, pid)
        angle = PERSONA_ANGLES.get(pid, "给出自己的视角")
        conf = phase2_conf.get(pid, 0.75)
        angles.append(f"{name} {angle}（自评 {conf:.2f}）；")

    # ── Day 7 · 跨轮记忆 · 检测是否有归档轮 ──
    rounds = list(getattr(session, "rounds", []) or [])
    is_continuation = len(rounds) > 0

    if is_continuation:
        last = rounds[-1]
        last_q = (last.question or "").strip()
        if len(last_q) > 60:
            last_q = last_q[:59].rstrip() + "…"

        # 上轮 Moderator 自述的关键摘要（lens / 第一条 tries / 第一条 doubts）
        last_lens_brief = ""
        last_first_try = ""
        last_first_doubt = ""
        if last.moderator is not None:
            last_lens_brief = (last.moderator.lens or "").strip()
            if len(last_lens_brief) > 80:
                last_lens_brief = last_lens_brief[:79].rstrip() + "…"
            tries_list = list(last.moderator.tries or [])
            if tries_list:
                last_first_try = str(tries_list[0]).strip()
                if len(last_first_try) > 80:
                    last_first_try = last_first_try[:79].rstrip() + "…"
            doubts_list = list(last.moderator.doubts or [])
            if doubts_list:
                last_first_doubt = str(doubts_list[0]).strip()
                if len(last_first_doubt) > 70:
                    last_first_doubt = last_first_doubt[:69].rstrip() + "…"

        cur_q = (session.question or "").strip()
        if len(cur_q) > 60:
            cur_q = cur_q[:59].rstrip() + "…"

        round_n = session.round_index + 1  # 1-based 给人看
        last_round_n = last.round_index + 1

        seen = (
            f"上一轮（第 {last_round_n} 轮）你跟我们聊到「{last_q or '上一件事'}」，"
            f"这次（第 {round_n} 轮）又带回了「{cur_q}」——这件事还在你心里持续发酵，"
            f"我们听到了。{persona_names[0]}、{persona_names[1]}、{persona_names[2]} "
            f"这次给出的视角和上一轮相比，有些可以承接，有些是新提醒。"
        )

        tries = []
        if last_first_try:
            tries.append(
                f"上轮我们建议过：{last_first_try}——如果还没试，这次可以先试一下；"
                f"如果已经试过了，我们可以聊聊它对你和对方各自产生了什么。"
            )
        else:
            tries.append(
                "先把上一轮和这一轮放在一起对比看：什么变了？什么还在原地？"
                "这种对比本身就是有用的信号。"
            )
        tries.append(
            "如果这次的事和上次本质相关——记住一个原则：不要一次解决所有，"
            "先选一个最能撬动的小动作（一句话、一个问题、一个停顿）。"
        )
        tries.append(
            "如果对方此刻不回应，也允许自己把注意力暂时移回自己——"
            "这不是放弃关系，而是先把自己照顾好。"
        )

        doubts = []
        if last_first_doubt:
            doubts.append(
                f"上轮我们一起留下过这个问题：{last_first_doubt} "
                "现在它有进展了吗？还是又被覆盖回去了？"
            )
        else:
            doubts.append(
                f"我们已经一起走过 {last_round_n} 轮了——你内心是否有一个"
                "还没说出口的核心问题，因为它太大或太脆弱，所以一直在外围打转？"
                "这不急着回答。"
            )
        doubts.append(
            f"「{cur_q}」和「{last_q}」之间，是同一件事的两个切面，"
            "还是两件不同的事？这个区分会影响下一步的方向。"
        )

        if last_lens_brief:
            lens = (
                f"这是我们的第 {round_n} 轮陪伴。上次我们说过：「{last_lens_brief}」"
                "——这句话现在仍然有效。你回到这里继续思考，本身就是一种力量，"
                "我们一直在。"
            )
        else:
            lens = (
                f"这是我们的第 {round_n} 轮陪伴。你回到这里继续思考，"
                "本身就是一种力量。我们不会替你决定该怎么做，但我们一直在。"
            )

    else:
        seen = (
            f"听了你说的「{session.question[:80]}…」之后，{persona_names[0]}、"
            f"{persona_names[1]}、{persona_names[2]} 共同看到了一件事："
            f"你不是在抱怨，也不是「想太多」。你是在认真寻找一种"
            f"被看见、被理解的方式。这件事值得我们一起往下走一段。"
        )
        tries = [
            "今晚不急着做决定。先写下三句话：我此刻的感受是什么 / 我希望被怎么看见 / 我能承担的是什么。",
            "如果要打破僵局，用「邀请」而不是「质问」开头。例如：「我想聊聊这件事，但我不想又吵起来，你愿意吗？」",
            "如果对方此刻不回应，也允许自己把注意力暂时移回自己——这不是放弃关系，而是先把自己照顾好。",
        ]
        doubts = [
            "如果尝试之后对方仍然沉默，你会怎么办？这个问题现在无法回答，需要真正开口后才知道。",
            f"「{session.question[:30]}」这件事是否还有你尚未告诉我们的细节？这值得在更长的时间里慢慢觉察。",
        ]
        lens = (
            "你不是一个人在面对这件事。我们不会替你决定该怎么做，"
            "但我们会一直在你愿意回来思考的时候在这里。"
        )

    return RoundtableModeratorContent(
        seen=seen,
        angles=angles,
        tries=tries,
        doubts=doubts,
        lens=lens,
        limit=(
            "Lens 圆桌讨论是非诊断性的探索工具，以上内容不能替代专业心理咨询或医疗评估。"
            "如果你正在经历严重情绪困扰，请拨打 24 小时心理援助热线 400-161-9995。"
        ),
    )


# ═══════════════════════════════════════════════════════════════════
# 持久化（最小落盘 · Day 4 加 atomic write + 错误恢复）
# ═══════════════════════════════════════════════════════════════════

def _save_session(session: RoundtableSession) -> None:
    path = ROUNDTABLE_DIR / f"{session.id}.json"
    try:
        path.write_text(
            session.model_dump_json(indent=2),
            encoding="utf-8",
        )
    except Exception:
        log.exception("[roundtable] failed to save session · id=%s", session.id)


# ═══════════════════════════════════════════════════════════════════
# 调试辅助
# ═══════════════════════════════════════════════════════════════════

def list_sessions() -> list[dict]:
    """返回所有内存 session 摘要（运维 + 前端历史入口用）。

    Day 6 · 暴露 `round_index` 与 `rounds_count` 供前端在 RoundtablePage 顶部
    列出历史会话时，能显示"已进行 N 轮"的徽章。
    """
    return [
        {
            "id": s.id,
            "phase": s.phase,
            "personas": s.personas,
            "question": s.question,
            "question_excerpt": s.question[:50],
            "backend": s.backend,  # Day 5 · E
            "round_index": s.round_index,  # Day 6 · 当前轮（0-based）
            "rounds_count": len(s.rounds),  # Day 6 · 已归档轮数（= round_index 除非异常）
            "created_at": s.created_at.isoformat(),
            "updated_at": s.updated_at.isoformat(),
        }
        # 按 updated_at 倒序 · 最近活跃的排前面
        for s in sorted(
            _sessions.values(),
            key=lambda s: s.updated_at,
            reverse=True,
        )
    ]


def get_session_detail(session_id: str) -> Optional[dict]:
    """GET /api/roundtable/sessions/{id} 的实现：返回 session 完整 snapshot（含 rounds）。

    前端在访问 RoundtableSessionPage 时，若 store 里没有该 session，会先拉这个接口
    恢复出所有历史轮 + 当前轮状态（包括 moderator_thinking），以便正确渲染折叠历史 + done 输入框。
    """
    s = _sessions.get(session_id)
    if s is None:
        return None
    return s.model_dump(mode="json")
