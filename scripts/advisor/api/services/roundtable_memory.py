"""
Day 4 · D4.8 / Day 5 · D5.2c · CrossRoundMemory — 圆桌讨论跨轮记忆压缩

目标：
  - 现状：`_build_prior_context_block` 只拿 `session.rounds[-1]` 的裸文本
    → 3 轮以上时，早期内容完全丢失；单轮过长时又会吃光 prompt token 预算
  - 新方案：**按优先级分档压缩**多轮 snapshot，在给定字符预算内 LIFO 截断

设计（执行方案 §D4.8）：
  - Tier-1（最近 1 轮，最详细 · 约 1800 字符）：
      · 用户问题（截断到 320）
      · persona 自己上轮 phase2 回应要点（截断到 600）
      · Moderator 「seen / limit」整段（各截断到 400）
  - Tier-2（次近 1 轮，中等压缩 · 约 800 字符）：
      · 用户问题（截断到 140）
      · persona 自己上轮结论一句（截断到 200）
      · Moderator seen（截断到 300）
  - Tier-3（更早 N 轮，极简摘要 · 每轮 ≤ 160 字符 · LIFO 累加）：
      · 「第 k 轮用户问：XXX → Moderator 一句话结论」

预算控制：
  - `char_budget` = 约 2000 token（中文 ≈ 3000-4000 char，默认 3800 char）
  - 从 Tier-1 → Tier-2 → Tier-3 依次填充；超预算则：
      a) Tier-3 先按 LIFO 丢弃更早的轮
      b) 若 Tier-1+Tier-2 已超，砍 Tier-2 的字段
      c) Tier-1 永远保留（至少 question + persona_self）

返回：
  - `build_memory_block(session, persona_id)` → (text, metrics)
  - `metrics` = {round_count, kept_rounds, dropped_rounds, char_count,
                 token_estimate, truncated}

接入：
  - 替换 `_build_prior_context_block` 中「上一轮讨论回顾」段的构造逻辑
  - 保留向后兼容：`session.rounds` 为空 → 返回 ("", metrics 空)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from ..core.models import (
    RoundtableAgentBuffer, RoundtableModeratorContent,
    RoundtableRoundSnapshot, RoundtableSession,
)

log = logging.getLogger(__name__)

# ── 预算参数 ───────────────────────────────────────────────
# 默认 3800 char ≈ 中文 2000 token · 留 prompt 剩余空间给 persona_core + 问题 + LLM 输出
DEFAULT_CHAR_BUDGET: int = 3800
# 粗略 token 估算系数：中文 1 token ≈ 1.7 char（GPT-style BPE）
CHAR_PER_TOKEN: float = 1.7

# Tier 内字段截断上限（基线，被预算压力触发时可再缩）
T1_QUESTION: int = 320
T1_SELF: int = 600
T1_SEEN: int = 400
T1_LIMIT: int = 400

T2_QUESTION: int = 140
T2_SELF: int = 200
T2_SEEN: int = 300

T3_PER_ROUND: int = 160  # 每个 Tier-3 轮总字符上限


# ═══════════════════════════════════════════════════════════
# 数据容器
# ═══════════════════════════════════════════════════════════

@dataclass
class MemoryMetrics:
    """memory 构建指标 · 供审计 / 日志使用"""
    round_count: int = 0
    kept_rounds: int = 0
    dropped_rounds: int = 0
    char_count: int = 0
    token_estimate: int = 0
    truncated: bool = False
    tier1_chars: int = 0
    tier2_chars: int = 0
    tier3_chars: int = 0
    tier3_rounds_kept: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "round_count": self.round_count,
            "kept_rounds": self.kept_rounds,
            "dropped_rounds": self.dropped_rounds,
            "char_count": self.char_count,
            "token_estimate": self.token_estimate,
            "truncated": self.truncated,
            "tier_breakdown": {
                "tier1_chars": self.tier1_chars,
                "tier2_chars": self.tier2_chars,
                "tier3_chars": self.tier3_chars,
                "tier3_rounds_kept": self.tier3_rounds_kept,
            },
        }


@dataclass
class _Section:
    """单个组装片段 · 带优先级 · LIFO 截断时可丢弃"""
    tier: int
    text: str
    round_index: int = -1  # Tier-3 用于 LIFO 排序
    droppable: bool = True  # Tier-1 question + self 设 False

    @property
    def length(self) -> int:
        return len(self.text)


# ═══════════════════════════════════════════════════════════
# 取数工具 · 单元可独立单测
# ═══════════════════════════════════════════════════════════

def _trim(text: Optional[str], limit: int, *, placeholder: str = "（本轮无记录）") -> str:
    """安全截断：None/空白 → placeholder；超长 → 加省略号"""
    text = (text or "").strip()
    if not text:
        return placeholder
    if len(text) > limit:
        return text[: max(limit - 1, 1)].rstrip() + "…"
    return text


def _find_self_phase2(
    snap: RoundtableRoundSnapshot, persona_id: str,
) -> Optional[RoundtableAgentBuffer]:
    """在 snapshot 里找出当前 persona 自己上轮的 phase2 buffer"""
    try:
        return next((b for b in snap.phase2 if b.persona_id == persona_id), None)
    except Exception:
        return None


def _moderator_part(mod: Optional[RoundtableModeratorContent], key: str, limit: int) -> str:
    """从 moderator 里挑出一段文本 · 失败回空"""
    if mod is None:
        return _trim("", limit)
    try:
        val = getattr(mod, key, None)
        if isinstance(val, list):
            # angles/tries/doubts/lens 类列表 · 合并成逗号分隔短句
            joined = "；".join(str(x).strip() for x in val if str(x).strip())
            return _trim(joined, limit)
        return _trim(str(val or ""), limit)
    except Exception:
        return _trim("", limit)


# ═══════════════════════════════════════════════════════════
# 主入口 · 组装 memory block
# ═══════════════════════════════════════════════════════════

def build_memory_block(
    session: RoundtableSession,
    persona_id: str,
    *,
    char_budget: int = DEFAULT_CHAR_BUDGET,
) -> tuple[str, MemoryMetrics]:
    """把 `session.rounds` 压缩成 prompt-friendly 的跨轮记忆段

    返回：(text, metrics)
      - text：可直接拼到 prompt 顶部（已带分隔线，不含尾部空行，由调用方补）
      - metrics：供审计 / UI 日志使用
    """
    metrics = MemoryMetrics()
    rounds = list(getattr(session, "rounds", []) or [])
    metrics.round_count = len(rounds)
    if not rounds:
        return "", metrics

    budget = max(char_budget, 600)  # 最少给到 600，否则 Tier-1 都塞不下
    sections: list[_Section] = []

    # ── Tier-1：最近 1 轮 ────────────────────────────────────
    last = rounds[-1]
    t1_self = _find_self_phase2(last, persona_id)
    t1_text = _format_tier1(last, t1_self, persona_id)
    sections.append(_Section(tier=1, text=t1_text, round_index=last.round_index, droppable=False))

    # ── Tier-2：次近 1 轮（如果存在） ────────────────────────
    if len(rounds) >= 2:
        prev = rounds[-2]
        t2_self = _find_self_phase2(prev, persona_id)
        t2_text = _format_tier2(prev, t2_self, persona_id)
        sections.append(_Section(tier=2, text=t2_text, round_index=prev.round_index, droppable=True))

    # ── Tier-3：更早的轮（LIFO · 新的在前、老的在后，老的先丢） ──
    if len(rounds) >= 3:
        older = rounds[:-2]  # 除最近两轮之外的全部 · 保持原顺序（从老到新）
        # 从新到老依次加入（即 reversed），这样 LIFO 截断时丢掉的是最老的
        for snap in reversed(older):
            t3_text = _format_tier3(snap)
            if not t3_text:
                continue
            sections.append(_Section(
                tier=3, text=t3_text, round_index=snap.round_index, droppable=True,
            ))

    # ── 按预算组装 + 压缩 ───────────────────────────────────
    assembled = _assemble_within_budget(sections, budget, metrics)
    text = assembled.strip("\n")
    metrics.char_count = len(text)
    metrics.token_estimate = int(round(metrics.char_count / CHAR_PER_TOKEN))
    return text, metrics


# ═══════════════════════════════════════════════════════════
# 分 Tier 格式化
# ═══════════════════════════════════════════════════════════

def _format_tier1(
    snap: RoundtableRoundSnapshot,
    self_buf: Optional[RoundtableAgentBuffer],
    persona_id: str,
) -> str:
    round_label = f"第 {snap.round_index + 1} 轮"
    question = _trim(snap.question, T1_QUESTION)
    self_text = _trim(self_buf.text if self_buf else "", T1_SELF)
    mod_seen = _moderator_part(snap.moderator, "seen", T1_SEEN)
    mod_limit = _moderator_part(snap.moderator, "limit", T1_LIMIT)

    return (
        f"━━━ 上一轮（{round_label}）讨论回顾 ━━━\n"
        f"【用户问的】{question}\n\n"
        f"【你（{persona_id}）在上一轮最终给出的回应要点】\n{self_text}\n\n"
        f"【Moderator · 她在听到什么（seen）】\n{mod_seen}\n\n"
        f"【Moderator · 这次对话的边界（limit）】\n{mod_limit}\n\n"
        "**继续下轮时**：承接你自己上轮的立场语气，但允许在新信息里发现新视角，"
        "不机械重复；若用户换话题就直接回新问题。"
    )


def _format_tier2(
    snap: RoundtableRoundSnapshot,
    self_buf: Optional[RoundtableAgentBuffer],
    persona_id: str,
) -> str:
    round_label = f"第 {snap.round_index + 1} 轮"
    question = _trim(snap.question, T2_QUESTION)
    self_text = _trim(self_buf.text if self_buf else "", T2_SELF)
    mod_seen = _moderator_part(snap.moderator, "seen", T2_SEEN)
    return (
        f"── 更早一轮（{round_label}）概要 ──\n"
        f"· 用户问：{question}\n"
        f"· 你当时的立场：{self_text}\n"
        f"· Moderator 综合：{mod_seen}"
    )


def _format_tier3(snap: RoundtableRoundSnapshot) -> str:
    round_label = f"第 {snap.round_index + 1} 轮"
    q = _trim(snap.question, 80, placeholder="")
    mod = _moderator_part(snap.moderator, "seen", 80)
    if not q and (not mod or mod == "（本轮无记录）"):
        return ""
    # 总长度不超过 T3_PER_ROUND
    line = f"· [{round_label}] 问：{q} → Moderator：{mod}"
    if len(line) > T3_PER_ROUND:
        line = line[: T3_PER_ROUND - 1].rstrip() + "…"
    return line


# ═══════════════════════════════════════════════════════════
# 预算装配 · 多级压缩策略
# ═══════════════════════════════════════════════════════════

def _assemble_within_budget(
    sections: list[_Section], budget: int, metrics: MemoryMetrics,
) -> str:
    """
    按 tier 优先级组装；超预算时按以下策略压缩：
      Step-A  先尝试直接拼 · 总长 ≤ budget → 直接返回
      Step-B  从 Tier-3 尾部（最老）LIFO 丢弃
      Step-C  若仍超，回落到 Tier-2 精简版（只保留 question + 结论一句）
      Step-D  再不行，最后只保留 Tier-1（且 Tier-1 question 段强制截短）
    """
    t1 = [s for s in sections if s.tier == 1]
    t2 = [s for s in sections if s.tier == 2]
    # Tier-3 按 round_index 从新到老排序（保持已 reversed 的顺序）
    t3 = [s for s in sections if s.tier == 3]

    def _total_len(segs: list[_Section]) -> int:
        if not segs:
            return 0
        return sum(s.length for s in segs) + 2 * (len(segs) - 1)  # \n\n 分隔

    # Step-A
    chosen: list[_Section] = [*t1, *t2, *t3]
    if _total_len(chosen) <= budget:
        metrics.kept_rounds = len(t1) + len(t2) + len(t3)
        metrics.dropped_rounds = 0
        metrics.truncated = False
        metrics.tier1_chars = sum(s.length for s in t1)
        metrics.tier2_chars = sum(s.length for s in t2)
        metrics.tier3_chars = sum(s.length for s in t3)
        metrics.tier3_rounds_kept = len(t3)
        return _join_sections(chosen)

    # Step-B: LIFO 丢 Tier-3（从最老 = 列表末尾弹）
    t3_kept = list(t3)
    dropped = 0
    while t3_kept and _total_len([*t1, *t2, *t3_kept]) > budget:
        t3_kept.pop()  # 丢最老
        dropped += 1

    if _total_len([*t1, *t2, *t3_kept]) <= budget:
        chosen = [*t1, *t2, *t3_kept]
        metrics.kept_rounds = len(t1) + len(t2) + len(t3_kept)
        metrics.dropped_rounds = len(t3) - len(t3_kept)
        metrics.truncated = metrics.dropped_rounds > 0
        metrics.tier1_chars = sum(s.length for s in t1)
        metrics.tier2_chars = sum(s.length for s in t2)
        metrics.tier3_chars = sum(s.length for s in t3_kept)
        metrics.tier3_rounds_kept = len(t3_kept)
        return _join_sections(chosen)

    # Step-C: Tier-2 替换为极简版
    t2_compact: list[_Section] = []
    for s in t2:
        # 极简 ≈ 只留一行
        head = s.text.split("\n", 1)[0]  # 保留 "── 更早一轮…" 标题行
        rest = ""
        for ln in s.text.split("\n")[1:]:
            if ln.startswith("· 用户问"):
                rest = ln
                break
        compact_text = head + ("\n" + rest if rest else "")
        t2_compact.append(_Section(tier=2, text=compact_text, round_index=s.round_index))

    if _total_len([*t1, *t2_compact]) <= budget:
        chosen = [*t1, *t2_compact]
        metrics.kept_rounds = len(t1) + len(t2_compact)
        metrics.dropped_rounds = len(t3)
        metrics.truncated = True
        metrics.tier1_chars = sum(s.length for s in t1)
        metrics.tier2_chars = sum(s.length for s in t2_compact)
        metrics.tier3_chars = 0
        metrics.tier3_rounds_kept = 0
        return _join_sections(chosen)

    # Step-D: 只留 Tier-1 · 必要时强制硬截
    # Tier-1 一定存在且 droppable=False
    t1_text = t1[0].text if t1 else ""
    if len(t1_text) > budget:
        t1_text = t1_text[: max(budget - 1, 100)].rstrip() + "…"
    metrics.kept_rounds = 1 if t1 else 0
    metrics.dropped_rounds = len(t2) + len(t3)
    metrics.truncated = True
    metrics.tier1_chars = len(t1_text)
    metrics.tier2_chars = 0
    metrics.tier3_chars = 0
    metrics.tier3_rounds_kept = 0
    return t1_text


def _join_sections(sections: list[_Section]) -> str:
    """按当前顺序拼接 · 段间两个空行"""
    return "\n\n".join(s.text for s in sections if s.text)


__all__ = [
    "MemoryMetrics",
    "build_memory_block",
    "DEFAULT_CHAR_BUDGET",
    "CHAR_PER_TOKEN",
]
