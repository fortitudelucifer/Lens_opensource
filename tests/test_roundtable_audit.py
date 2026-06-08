"""
Day 5 · D5.5 · RoundtableAuditor 单测

覆盖：
- emit() 创建 JSONL 文件 + 正确目录（{YYYYMMDD}/{session_id}.jsonl）
- AuditEvent round-trip（JSON 序列化/反序列化 · 字段完整）
- 单例 `get_auditor()` / `reset_auditor()` 行为
- `ROUNDTABLE_AUDIT_ROOT` env override 生效
- 未知 event_type 不 raise（只 warn · 允许未来扩展）
- 并发安全（多线程同时写同一 session）
- 所有便捷函数（emit_session_created / emit_phase_start 等）都能写入预期的 event_type
- emit_xxx 系列在 None 参数 / 异常时不抛异常（主流程绝不中断）
"""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.advisor.api.services import roundtable_audit as ra  # noqa: E402


@pytest.fixture()
def audit_tmp(tmp_path, monkeypatch):
    """每个 test 用独立 tmp_path · 自动清掉单例 + env"""
    monkeypatch.setenv("ROUNDTABLE_AUDIT_ROOT", str(tmp_path))
    ra.reset_auditor()
    yield tmp_path
    ra.reset_auditor()


# ═════════════════════════════════════════════════════════════
# 基础 emit + 文件落盘
# ═════════════════════════════════════════════════════════════


class TestEmitBasic:
    def test_emit_creates_jsonl_file(self, audit_tmp):
        auditor = ra.get_auditor()
        ev = auditor.emit(
            session_id="rt_test_A",
            event_type="session_created",
            data={"personas": ["neutral", "supportive", "eft"]},
        )
        assert ev is not None
        assert ev.session_id == "rt_test_A"
        assert ev.event_type == "session_created"

        # 文件路径：{tmp}/{YYYYMMDD}/rt_test_A.jsonl
        candidates = list(audit_tmp.rglob("rt_test_A.jsonl"))
        assert len(candidates) == 1
        path = candidates[0]
        # 上级目录就是 YYYYMMDD
        assert len(path.parent.name) == 8 and path.parent.name.isdigit()

        content = path.read_text(encoding="utf-8")
        assert content.endswith("\n")
        parsed = json.loads(content.splitlines()[0])
        assert parsed["session_id"] == "rt_test_A"
        assert parsed["event_type"] == "session_created"
        assert parsed["data"]["personas"] == ["neutral", "supportive", "eft"]

    def test_multiple_events_append(self, audit_tmp):
        auditor = ra.get_auditor()
        for i in range(5):
            auditor.emit(
                session_id="rt_multi", event_type="phase_start",
                phase="phase1", data={"i": i},
            )
        paths = list(audit_tmp.rglob("rt_multi.jsonl"))
        assert len(paths) == 1
        lines = paths[0].read_text(encoding="utf-8").splitlines()
        assert len(lines) == 5
        for i, line in enumerate(lines):
            assert json.loads(line)["data"]["i"] == i

    def test_round_trip_via_read(self, audit_tmp):
        auditor = ra.get_auditor()
        auditor.emit(session_id="rt_rt", event_type="session_created")
        auditor.emit(session_id="rt_rt", event_type="phase_start", phase="phase1")
        auditor.emit(session_id="rt_rt", event_type="phase_end",
                     phase="phase1", data={"duration_s": 12.3})
        events = auditor.read("rt_rt")
        assert len(events) == 3
        assert [e.event_type for e in events] == [
            "session_created", "phase_start", "phase_end",
        ]
        assert events[2].data["duration_s"] == 12.3


# ═════════════════════════════════════════════════════════════
# 单例 + env override
# ═════════════════════════════════════════════════════════════


class TestSingleton:
    def test_get_auditor_cached(self, audit_tmp):
        a = ra.get_auditor()
        b = ra.get_auditor()
        assert a is b

    def test_reset_creates_new_instance(self, audit_tmp):
        a = ra.get_auditor()
        ra.reset_auditor()
        b = ra.get_auditor()
        assert a is not b

    def test_env_override_root(self, tmp_path, monkeypatch):
        custom = tmp_path / "custom_root"
        monkeypatch.setenv("ROUNDTABLE_AUDIT_ROOT", str(custom))
        ra.reset_auditor()
        auditor = ra.get_auditor()
        auditor.emit(session_id="rt_env", event_type="session_created")
        assert (custom).exists()
        assert list(custom.rglob("rt_env.jsonl"))
        ra.reset_auditor()


# ═════════════════════════════════════════════════════════════
# 容错
# ═════════════════════════════════════════════════════════════


class TestResilience:
    def test_unknown_event_type_does_not_raise(self, audit_tmp, caplog):
        with caplog.at_level("WARNING", logger="scripts.advisor.api.services.roundtable_audit"):
            ev = ra.get_auditor().emit(
                session_id="rt_unk", event_type="future_event_type",
            )
        assert ev is not None  # 依然写入
        assert any("unknown event_type" in r.getMessage() for r in caplog.records)

    def test_read_missing_returns_empty(self, audit_tmp):
        """read() 一个没写过的 session_id → 返回空列表，不 raise"""
        assert ra.get_auditor().read("rt_never_written") == []

    def test_read_skips_malformed_lines(self, audit_tmp):
        auditor = ra.get_auditor()
        auditor.emit(session_id="rt_bad", event_type="session_created")
        path = audit_tmp.rglob("rt_bad.jsonl").__next__()
        # 追加一行非法 JSON
        with open(path, "a", encoding="utf-8") as f:
            f.write("this is not valid json\n")
        auditor.emit(session_id="rt_bad", event_type="session_done")
        events = auditor.read("rt_bad")
        assert [e.event_type for e in events] == ["session_created", "session_done"]


# ═════════════════════════════════════════════════════════════
# 并发安全
# ═════════════════════════════════════════════════════════════


class TestConcurrency:
    def test_concurrent_writes_same_session(self, audit_tmp):
        """50 线程 × 20 次写同一 session · 总行数 = 1000 · JSONL 格式仍然合法"""
        N_THREADS = 50
        N_PER = 20
        auditor = ra.get_auditor()

        def _worker(tid: int) -> None:
            for i in range(N_PER):
                auditor.emit(
                    session_id="rt_concurrent", event_type="phase_start",
                    phase="phase1", data={"tid": tid, "i": i},
                )

        threads = [threading.Thread(target=_worker, args=(i,)) for i in range(N_THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        events = auditor.read("rt_concurrent")
        assert len(events) == N_THREADS * N_PER
        # 每条都能解析
        for e in events:
            assert e.event_type == "phase_start"
            assert "tid" in e.data and "i" in e.data


# ═════════════════════════════════════════════════════════════
# 便捷函数都能覆盖预期 event_type
# ═════════════════════════════════════════════════════════════


class TestHelpers:
    def test_emit_session_created(self, audit_tmp):
        ra.emit_session_created(
            session_id="rt_h1", personas=["neutral", "eft", "bowen"],
            question="some long question text here", backend="deepseek",
        )
        events = ra.get_auditor().read("rt_h1")
        assert len(events) == 1
        e = events[0]
        assert e.event_type == "session_created"
        assert e.data["personas"] == ["neutral", "eft", "bowen"]
        assert e.data["backend"] == "deepseek"
        assert e.data["question_len"] == len("some long question text here")

    def test_emit_phase_round_trip(self, audit_tmp):
        ra.emit_phase_start(session_id="rt_h2", phase="phase1")
        ra.emit_phase_end(session_id="rt_h2", phase="phase1", duration_s=12.3456)
        events = ra.get_auditor().read("rt_h2")
        assert [e.event_type for e in events] == ["phase_start", "phase_end"]
        assert events[1].data["duration_s"] == 12.346  # 3 位精度

    def test_emit_agent_done_done(self, audit_tmp):
        ra.emit_agent_done(
            session_id="rt_h3", phase="phase2", persona_id="eft",
            duration_s=5.5, chunk_count=24, text_len=812, confidence=0.87,
        )
        e = ra.get_auditor().read("rt_h3")[0]
        assert e.event_type == "agent_done"
        assert e.persona_id == "eft"
        assert e.phase == "phase2"
        assert e.data["chunk_count"] == 24
        assert e.data["confidence"] == 0.87

    def test_emit_agent_error_truncates_long_error(self, audit_tmp):
        long_err = "X" * 2000
        ra.emit_agent_error(
            session_id="rt_h4", phase="phase1", persona_id="neutral",
            error=long_err,
        )
        e = ra.get_auditor().read("rt_h4")[0]
        assert e.event_type == "agent_error"
        assert len(e.data["error"]) == 500  # 截断

    def test_emit_bias_hit(self, audit_tmp):
        ra.emit_bias_hit(
            session_id="rt_h5", phase="phase1", persona_id="supportive",
            categories=["gender_stereotype"], patterns=["男人都"],
            raw_snippet="他说男人都这样，你别当真",
        )
        e = ra.get_auditor().read("rt_h5")[0]
        assert e.event_type == "bias_hit"
        assert e.data["categories"] == ["gender_stereotype"]
        assert "男人都" in e.data["patterns"]

    def test_emit_crisis_hit(self, audit_tmp):
        ra.emit_crisis_hit(
            session_id="rt_h6", phase=None, persona_id=None,
            hit_type="input_red",
            keywords=["想死"],
        )
        e = ra.get_auditor().read("rt_h6")[0]
        assert e.event_type == "crisis_hit"
        assert e.data["hit_type"] == "input_red"

    def test_emit_moderator_done(self, audit_tmp):
        ra.emit_moderator_done(
            session_id="rt_h7", duration_s=8.5,
            fallback_reason="timeout", thinking_len=520,
            content_keys=["seen", "angles", "tries", "doubts", "lens", "limit"],
        )
        e = ra.get_auditor().read("rt_h7")[0]
        assert e.event_type == "moderator_done"
        assert e.data["fallback_reason"] == "timeout"
        assert len(e.data["content_keys"]) == 6

    def test_emit_session_done(self, audit_tmp):
        ra.emit_session_done(
            session_id="rt_h8", total_duration_s=72.04,
            first_agent_chunk_s=3.78, total_events=217,
            errors_count=0, rewrite_count_total=2,
        )
        e = ra.get_auditor().read("rt_h8")[0]
        assert e.event_type == "session_done"
        assert e.data["total_duration_s"] == 72.04
        assert e.data["first_agent_chunk_s"] == 3.78


# ═════════════════════════════════════════════════════════════
# 日期分目录 · 同日同 session 落同一文件
# ═════════════════════════════════════════════════════════════


class TestPathRules:
    def test_path_consistent_for_same_session(self, audit_tmp):
        auditor = ra.get_auditor()
        auditor.emit(session_id="rt_same", event_type="session_created")
        p1 = auditor.path_for("rt_same")
        auditor.emit(session_id="rt_same", event_type="session_done")
        p2 = auditor.path_for("rt_same")
        assert p1 == p2
        assert p1.exists()
        assert len(p1.read_text(encoding="utf-8").splitlines()) == 2

    def test_different_sessions_different_files(self, audit_tmp):
        auditor = ra.get_auditor()
        auditor.emit(session_id="rt_A", event_type="session_created")
        auditor.emit(session_id="rt_B", event_type="session_created")
        pa = auditor.path_for("rt_A")
        pb = auditor.path_for("rt_B")
        assert pa != pb
        assert pa.exists() and pb.exists()
