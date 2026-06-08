"""
Day 4 · D4.1 · GuardedEmitter 单测

覆盖：
- feed() 增量累计 · 未到阈值不 flush（buf 为空）
- 累计字数 ≥ flush_threshold 时自动 flush
- 句末标点触发 flush（无视 threshold）
- sanitize_fn 在 flush 前执行（禁用词不会先进 buf 再被改）
- finalize() 把残留 pending 推出
- sanitize_fn 抛异常时回落原文，不丢 chunk
- audit_context 传给 sanitize_fn（双签名兼容）

使用 `asyncio.run(...)` 包裹异步逻辑 · 避免额外依赖 pytest-asyncio
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Callable

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.advisor.api.core.models import RoundtableAgentBuffer  # noqa: E402
from scripts.advisor.api.services import roundtable_service as rs  # noqa: E402


# ── Helpers ──────────────────────────────────────────────────

def _fresh_buf(persona_id: str = "neutral") -> RoundtableAgentBuffer:
    return RoundtableAgentBuffer(persona_id=persona_id, status="streaming", text="")


def _run(coro_factory: Callable[[asyncio.Queue], asyncio.Future]) -> tuple[asyncio.Queue, list[dict]]:
    """创建 queue + 跑 coroutine + 排空 queue 一次性拿事件列表"""
    async def _wrap():
        q: asyncio.Queue = asyncio.Queue()
        # session_id 由调用方在 coro_factory 里约定 · 这里不绑死
        await coro_factory(q)
        out: list[dict] = []
        while not q.empty():
            out.append(await q.get())
        return q, out
    return asyncio.run(_wrap())


def _mk_emitter(session_id: str, queue: asyncio.Queue, *, persona_id="neutral",
                phase="phase1", sanitize_fn=None, flush_threshold=16):
    """把 queue 塞进 rs._queues[session_id]，构造 emitter"""
    rs._queues[session_id] = queue
    return rs.GuardedEmitter(
        session_id, phase, persona_id, _fresh_buf(persona_id),
        sanitize_fn=sanitize_fn or (lambda t: t),
        flush_threshold=flush_threshold,
    )


@pytest.fixture(autouse=True)
def _clear_queues():
    """每个测试前后都清空 _queues，避免互相污染"""
    rs._queues.clear()
    yield
    rs._queues.clear()


# ═════════════════════════════════════════════════════════════
# 增量累计 + 阈值触发
# ═════════════════════════════════════════════════════════════


class TestAccumulation:
    def test_below_threshold_does_not_flush(self):
        """喂 8 字 < 阈值 16 · 无 flush · buf 依然空"""
        captured: dict = {}

        async def _scenario(q: asyncio.Queue):
            emitter = _mk_emitter("sess-a", q, flush_threshold=16)
            captured["buf"] = emitter._buf
            captured["emitter"] = emitter
            for ch in "八个字符abcd":  # 8 字符
                await emitter.feed(ch)

        _, events = _run(_scenario)
        assert captured["buf"].text == ""
        assert captured["emitter"].flush_count == 0
        assert events == []

    def test_reaches_threshold_auto_flush(self):
        """喂到 16 字符即 flush 出去"""
        captured: dict = {}
        text16 = "一二三四五六七八九十abcdef"
        assert len(text16) == 16

        async def _scenario(q: asyncio.Queue):
            emitter = _mk_emitter("sess-b", q, flush_threshold=16)
            captured["emitter"] = emitter
            for ch in text16:
                await emitter.feed(ch)

        _, events = _run(_scenario)
        emitter = captured["emitter"]
        assert emitter.flush_count == 1
        assert emitter._buf.text == text16
        assert len(events) == 1
        assert events[0]["type"] == "agent_chunk"
        assert events[0]["delta"] == text16
        assert events[0]["phase"] == "phase1"

    def test_multi_flush_sequence(self):
        """32 字符 · 两次 flush（阈值 16）"""
        captured: dict = {}

        async def _scenario(q: asyncio.Queue):
            emitter = _mk_emitter(
                "sess-c", q, flush_threshold=16, phase="phase2", persona_id="supportive",
            )
            captured["emitter"] = emitter
            for ch in "A" * 32:
                await emitter.feed(ch)

        _, events = _run(_scenario)
        emitter = captured["emitter"]
        assert emitter.flush_count == 2
        assert emitter._buf.text == "A" * 32
        assert len(events) == 2
        assert events[0]["phase"] == "phase2"
        assert events[0]["agent_id"] == "supportive"


# ═════════════════════════════════════════════════════════════
# 句末标点触发 flush
# ═════════════════════════════════════════════════════════════


class TestSentenceEnder:
    @pytest.mark.parametrize("ender", ["。", "！", "？", "；", ".", "!", "?", ";", "\n"])
    def test_each_ender_triggers_flush(self, ender):
        """任一句末标点在任意字数都立即 flush（忽略 threshold）"""
        captured: dict = {}
        sid = f"sess-ender-{ender.encode().hex()}"

        async def _scenario(q: asyncio.Queue):
            # 故意把阈值调得巨大 · 只能靠 ender 触发
            emitter = _mk_emitter(sid, q, flush_threshold=999)
            captured["emitter"] = emitter
            for ch in f"短{ender}":
                await emitter.feed(ch)

        _, events = _run(_scenario)
        emitter = captured["emitter"]
        assert emitter.flush_count == 1
        assert emitter._buf.text == f"短{ender}"
        assert len(events) == 1 and events[0]["delta"] == f"短{ender}"

    def test_mid_punct_not_triggering(self):
        """中文逗号 / 顿号 不应触发 flush"""
        captured: dict = {}

        async def _scenario(q: asyncio.Queue):
            emitter = _mk_emitter("sess-mid", q, flush_threshold=999)
            captured["emitter"] = emitter
            for ch in "第一部分，第二部分、":
                await emitter.feed(ch)

        _, events = _run(_scenario)
        emitter = captured["emitter"]
        assert emitter.flush_count == 0
        assert emitter._buf.text == ""
        assert events == []


# ═════════════════════════════════════════════════════════════
# Sanitize 在 flush 前
# ═════════════════════════════════════════════════════════════


class TestSanitizeBeforeFlush:
    def test_forbidden_replaced_before_buf_updated(self):
        """sanitize 替换后的文本才进 buf · 原始禁用词绝不出现在 buf 或事件里"""
        captured: dict = {}

        def _mock_sanitize(text: str) -> str:
            return text.replace("你必须", "（替换）")

        async def _scenario(q: asyncio.Queue):
            emitter = _mk_emitter(
                "sess-san", q, sanitize_fn=_mock_sanitize, flush_threshold=8,
            )
            captured["emitter"] = emitter
            for ch in "你必须放下这件事":  # 8 字 · 触发 flush
                await emitter.feed(ch)

        _, events = _run(_scenario)
        emitter = captured["emitter"]
        assert "你必须" not in emitter._buf.text, "禁用词不应出现在 buf（应在 flush 前替换）"
        assert "（替换）" in emitter._buf.text
        assert len(events) == 1
        assert "你必须" not in events[0]["delta"]
        assert "（替换）" in events[0]["delta"]
        assert emitter.rewrite_count == 1

    def test_sanitize_no_change_zero_rewrite(self):
        """sanitize 未改动 · rewrite_count 保持 0"""
        captured: dict = {}

        async def _scenario(q: asyncio.Queue):
            emitter = _mk_emitter("sess-san2", q, flush_threshold=4)
            captured["emitter"] = emitter
            for ch in "平常内容":
                await emitter.feed(ch)

        _run(_scenario)
        emitter = captured["emitter"]
        assert emitter.flush_count == 1
        assert emitter.rewrite_count == 0

    def test_sanitize_returns_empty_skips_emit(self):
        """sanitize 结果为空串 · 不 emit chunk（避免空 delta 干扰前端）"""
        captured: dict = {}

        async def _scenario(q: asyncio.Queue):
            emitter = _mk_emitter(
                "sess-san3", q, sanitize_fn=lambda t: "", flush_threshold=4,
            )
            captured["emitter"] = emitter
            for ch in "被整段移除":
                await emitter.feed(ch)

        _, events = _run(_scenario)
        emitter = captured["emitter"]
        assert emitter._buf.text == ""
        assert events == [], "空 chunk 不应 emit"
        # flush_count 仍然累加（表示 flush 已走过）
        assert emitter.flush_count >= 1

    def test_sanitize_exception_falls_back_to_raw(self):
        """sanitize 异常 · 回落原文，不丢 chunk"""
        captured: dict = {}

        def _boom(text: str) -> str:
            raise RuntimeError("sanitize crashed")

        async def _scenario(q: asyncio.Queue):
            emitter = _mk_emitter(
                "sess-san-err", q, sanitize_fn=_boom, flush_threshold=4,
            )
            captured["emitter"] = emitter
            for ch in "原文内容":
                await emitter.feed(ch)

        _, events = _run(_scenario)
        emitter = captured["emitter"]
        assert emitter._buf.text == "原文内容"
        assert len(events) == 1 and events[0]["delta"] == "原文内容"


# ═════════════════════════════════════════════════════════════
# finalize()
# ═════════════════════════════════════════════════════════════


class TestFinalize:
    def test_finalize_drains_pending(self):
        """finalize 应把不满阈值的残留推出去"""
        captured: dict = {}

        async def _scenario(q: asyncio.Queue):
            emitter = _mk_emitter("sess-fin", q, flush_threshold=16)
            captured["emitter"] = emitter
            for ch in "残留":  # 2 字，远小于阈值
                await emitter.feed(ch)
            # 还没 flush
            assert emitter._buf.text == ""
            await emitter.finalize()

        _, events = _run(_scenario)
        emitter = captured["emitter"]
        assert emitter._buf.text == "残留"
        assert len(events) == 1 and events[0]["delta"] == "残留"

    def test_finalize_noop_when_empty(self):
        """pending 为空时 finalize 不 emit 事件"""

        async def _scenario(q: asyncio.Queue):
            emitter = _mk_emitter("sess-fin2", q)
            await emitter.finalize()

        _, events = _run(_scenario)
        assert events == []


# ═════════════════════════════════════════════════════════════
# audit_context 透传（双签名兼容）
# ═════════════════════════════════════════════════════════════


class TestAuditContext:
    def test_sanitize_fn_receives_audit_context(self):
        """默认签名 (text, audit_context=...) · emitter 应传入 session/persona/phase"""
        captured: dict = {}

        def _spy(text: str, *, audit_context: dict) -> str:
            captured.update(audit_context)
            return text

        async def _scenario(q: asyncio.Queue):
            emitter = _mk_emitter(
                "sess-audit", q, persona_id="eft", phase="phase2",
                sanitize_fn=_spy, flush_threshold=4,
            )
            for ch in "abcd":
                await emitter.feed(ch)

        _run(_scenario)
        assert captured == {
            "session_id": "sess-audit",
            "persona_id": "eft",
            "phase": "phase2",
        }

    def test_legacy_single_arg_sanitize_still_works(self):
        """老签名 (text) -> str · 不接 audit_context 也不应报错"""
        captured: dict = {}

        def _legacy(text: str) -> str:
            return text.upper()

        async def _scenario(q: asyncio.Queue):
            emitter = _mk_emitter(
                "sess-legacy", q, sanitize_fn=_legacy, flush_threshold=4,
            )
            captured["emitter"] = emitter
            for ch in "abcd":
                await emitter.feed(ch)

        _run(_scenario)
        assert captured["emitter"]._buf.text == "ABCD"
