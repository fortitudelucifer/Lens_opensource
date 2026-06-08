#!/usr/bin/env python3
"""
CPU 流水线式并行执行器模块

功能：
- 四级异步流水线并行执行 MoA（Mixture of Analysts）分析
- S1 多模型并行分析（Claude + GPT + Gemini 同时调用）
- S2-S4 使用 Grok API 进行融合、审核和修复
- Rich 终端实时可视化（显示每个 chunk 在流水线中的位置和状态）
- 自动降级策略（Claude 失败 → GPT+Gemini 双分析）

四级流水线：
  S1 Analysis (Claude+GPT+Gemini 并行) → S2 MoA Fusion (Grok)
  → S3 Review (Grok) → S4 Remediation (Grok)

并行策略：
- S1 使用 Claude/GPT/Gemini API，S2-S4 使用 Grok API — 天然不竞争
- 当 chunk[i] 进入 S2 时，chunk[i+1] 可立即开始 S1

降级策略：
- Claude 失败 → GPT+Gemini 双分析（非 GPT-only）
- Grok MoA 失败 → Kimi 备用 → v1 程序合并

处理流程：
1. 将所有 chunks 放入 S1 队列
2. S1: 并行调用 3 个云端模型生成初始分析
3. S2: Grok 融合 3 个分析结果（MoA 策略）
4. S3: Grok 审核融合结果的质量和一致性
5. S4: 对审核不通过的结果进行修复
6. 输出最终分析结果

输入：
- 对话 chunks 列表
- 各后端的 AnalysisGenerator 实例

输出：
- 融合后的分析结果列表

依赖：
- asyncio: 异步并行执行
- rich: 终端实时可视化
- scripts.advisor.generator: AnalysisGenerator

使用示例：
    executor = PipelineExecutor(generators, ...)
    results = await executor.run(chunks)

性能参考：
- 流水线吞吐量：约 1 chunk/10s（受 S1 并行 API 调用限制）
- 相比串行执行提速约 2-3x

注意事项：
- 需要配置 Claude、GPT、Gemini、Grok 四个后端的 API Key
- Rich 可视化需要终端支持 ANSI 颜色
- 异步执行，需要在 asyncio 事件循环中运行

作者：[Author]
更新于：2026-02-15
"""

import asyncio
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


# ── 流水线阶段状态 ──────────────────────────────────────────
class StageStatus:
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    DEGRADED = "degraded"


class ChunkState:
    """单个 chunk 在流水线中的状态追踪"""

    def __init__(self, chunk_id: str, idx: int):
        self.chunk_id = chunk_id
        self.idx = idx
        self.stages = {
            "s1_analysis": StageStatus.PENDING,
            "s2_moa":      StageStatus.PENDING,
            "s3_review":   StageStatus.PENDING,
            "s4_remediation": StageStatus.PENDING,
        }
        self.timings = {}  # stage -> elapsed_seconds
        self.details = {}  # stage -> detail string
        self.result = None
        self.start_time = None
        self.end_time = None

    def set_stage(self, stage: str, status: str, elapsed: float = 0, detail: str = ""):
        self.stages[stage] = status
        if elapsed > 0:
            self.timings[stage] = elapsed
        if detail:
            self.details[stage] = detail

    @property
    def total_elapsed(self) -> float:
        if self.start_time is None:
            return 0
        end = self.end_time or time.time()
        return end - self.start_time

    @property
    def is_done(self) -> bool:
        return all(
            s in (StageStatus.SUCCESS, StageStatus.FAILED, StageStatus.SKIPPED, StageStatus.DEGRADED)
            for s in self.stages.values()
        )


# ── 终端可视化 ──────────────────────────────────────────────
class PipelineVisualizer:
    """四级流水线终端实时可视化"""

    STAGE_NAMES = ["S1:Analysis", "S2:MoA", "S3:Review", "S4:Remed."]
    STAGE_KEYS = ["s1_analysis", "s2_moa", "s3_review", "s4_remediation"]

    STATUS_SYMBOLS = {
        StageStatus.PENDING:  ("⬜", "dim"),
        StageStatus.RUNNING:  ("🔄", "bold cyan"),
        StageStatus.SUCCESS:  ("✅", "green"),
        StageStatus.FAILED:   ("❌", "red"),
        StageStatus.SKIPPED:  ("⏭️", "dim"),
        StageStatus.DEGRADED: ("⚠️", "yellow"),
    }

    def __init__(self, total_chunks: int, use_rich: bool = True):
        self.total = total_chunks
        self.states: list[ChunkState] = []
        self._lock = threading.Lock()
        self._start_time = time.time()
        self._use_rich = use_rich
        self._live = None
        self._console = None

    def add_chunk(self, state: ChunkState):
        with self._lock:
            self.states.append(state)

    def start(self):
        """启动 live 刷新"""
        if self._use_rich:
            try:
                from rich.console import Console
                from rich.live import Live
                self._console = Console()
                self._live = Live(
                    self._render_rich(),
                    console=self._console,
                    refresh_per_second=4,
                    transient=False,
                )
                self._live.start()
                return
            except ImportError:
                self._use_rich = False

        # Fallback: no rich
        print(self._render_plain())

    def update(self):
        """刷新显示"""
        if self._use_rich and self._live:
            self._live.update(self._render_rich())
        # plain mode: print on stage transitions (handled in executor)

    def stop(self):
        """停止 live 刷新"""
        if self._use_rich and self._live:
            self._live.update(self._render_rich())
            self._live.stop()

    def print_stage_change(self, chunk_id: str, stage: str, status: str, detail: str = ""):
        """plain mode: 每次阶段变更时打印一行"""
        if not self._use_rich:
            sym = self.STATUS_SYMBOLS.get(status, ("?", ""))[0]
            stage_name = dict(zip(self.STAGE_KEYS, self.STAGE_NAMES)).get(stage, stage)
            elapsed_total = time.time() - self._start_time
            line = f"[{elapsed_total:6.1f}s] {chunk_id} {stage_name} {sym} {detail}"
            print(line, flush=True)

    def _render_rich(self):
        """生成 rich Table 用于 live 更新"""
        from rich.table import Table
        from rich.text import Text
        from rich.panel import Panel
        from rich.columns import Columns

        elapsed = time.time() - self._start_time
        done = sum(1 for s in self.states if s.is_done)
        rate = done / elapsed * 60 if elapsed > 0 and done > 0 else 0

        # Header
        header = Text()
        header.append("🚀 Pipeline ", style="bold white")
        header.append(f"{done}/{self.total} ", style="bold green")
        header.append(f"({elapsed:.0f}s, {rate:.1f}/min)", style="dim")

        # Pipeline table
        table = Table(
            title=None,
            show_header=True,
            header_style="bold",
            border_style="dim",
            padding=(0, 1),
            expand=False,
        )
        table.add_column("Chunk", style="cyan", width=14)
        for name in self.STAGE_NAMES:
            table.add_column(name, justify="center", width=14)
        table.add_column("Total", justify="right", width=8)

        with self._lock:
            # Show last N chunks that are active or recently done
            visible = self.states[-8:] if len(self.states) > 8 else self.states

        for cs in visible:
            row = [cs.chunk_id[:13]]
            for sk in self.STAGE_KEYS:
                status = cs.stages[sk]
                sym, style = self.STATUS_SYMBOLS.get(status, ("?", ""))
                t = cs.timings.get(sk, 0)
                cell = Text()
                cell.append(f"{sym}", style=style)
                if t > 0:
                    cell.append(f" {t:.0f}s", style="dim")
                elif status == StageStatus.RUNNING:
                    cell.append(" ...", style="dim italic")
                detail = cs.details.get(sk, "")
                if detail:
                    cell.append(f"\n{detail[:12]}", style="dim")
                row.append(cell)
            row.append(f"{cs.total_elapsed:.0f}s")
            table.add_row(*row)

        return Panel(
            Columns([table], padding=(0, 0)),
            title=f"[bold]🔧 四级流水线[/bold] {header}",
            border_style="blue",
        )

    def _render_plain(self) -> str:
        """纯文本渲染"""
        lines = ["=" * 70, "🔧 四级流水线启动", "=" * 70]
        return "\n".join(lines)


# ── 流水线执行器 ──────────────────────────────────────────────
class PipelineExecutor:
    """
    CPU 指令流水线式并行执行器。

    S1 (Analysis) 和 S2-S4 (Grok) 使用不同的 API provider，
    天然不竞争，因此 chunk[i] 的 S2 和 chunk[i+1] 的 S1 可并行。
    """

    def __init__(
        self,
        generators: dict,
        agent_type: str = "neutral",
        claude_backup: object = None,
        moa_backup: object = None,
        grok_backup_gen: object = None,
        skip_review: bool = False,
        skip_gemini_non_multimodal: bool = True,
        max_concurrent_s1: int = 2,
        max_concurrent_grok: int = 3,
        use_rich: bool = True,
        # 降级策略: Claude Opus 失败 → Sonnet 4.5 Think → GPT+Gemini 双分析
        claude_degradation_to_dual: bool = True,
        # Claude 降级 generator (sonnet-4.5-think)
        claude_degraded_gen: object = None,
    ):
        self.generators = generators
        self.agent_type = agent_type
        self.claude_backup = claude_backup
        self.moa_backup = moa_backup
        self.grok_backup_gen = grok_backup_gen
        self.skip_review = skip_review
        self.skip_gemini_non_multimodal = skip_gemini_non_multimodal
        self.claude_degradation_to_dual = claude_degradation_to_dual
        self.claude_degraded_gen = claude_degraded_gen

        # Semaphores: 控制每个阶段的并发度
        self._s1_sem = asyncio.Semaphore(max_concurrent_s1)
        self._grok_sem = asyncio.Semaphore(max_concurrent_grok)

        # Thread pool for running sync API calls in async context
        self._thread_pool = ThreadPoolExecutor(max_workers=max_concurrent_s1 + max_concurrent_grok + 2)

        self.use_rich = use_rich
        self.viz: Optional[PipelineVisualizer] = None

        # Stats
        self.stats = {
            "success": 0, "failed": 0,
            "moa_full": 0, "moa_fallback": 0,
            "claude_degraded_to_sonnet": 0,
            "claude_degraded_to_dual": 0,
            "remediation_triggered": 0,
            "total_time": 0,
        }
        self._stats_lock = threading.Lock()

    async def run(self, chunks: list[dict], output_path: str) -> list[dict]:
        """
        运行四级流水线处理所有 chunks。

        Returns:
            处理结果列表
        """
        # Lazy imports to avoid circular dependency
        from scripts.advisor.run_all._02c_fusion_pipeline import (
            _run_step_analysis, moa_merge_analyses, merge_analyses,
            run_grok_review, run_grok_remediation, _summarize_step,
            _is_multimodal, REMEDIATION_THRESHOLD,
        )

        total = len(chunks)
        self.viz = PipelineVisualizer(total, use_rich=self.use_rich)
        results = [None] * total
        file_lock = threading.Lock()

        self.viz.start()

        async def process_chunk(idx: int, chunk: dict):
            chunk_id = chunk.get("chunk_id", f"chunk_{idx:04d}")
            conversation = chunk.get("conversation_text", "")
            is_mm = _is_multimodal(conversation)

            cs = ChunkState(chunk_id, idx)
            self.viz.add_chunk(cs)
            cs.start_time = time.time()

            # ── S1: Analysis (Claude + GPT + Gemini 并行) ──
            async with self._s1_sem:
                cs.set_stage("s1_analysis", StageStatus.RUNNING)
                self.viz.update()
                self.viz.print_stage_change(chunk_id, "s1_analysis", StageStatus.RUNNING)

                s1_start = time.time()
                loop = asyncio.get_event_loop()

                # Run Claude, GPT, (Gemini) concurrently in thread pool
                claude_fut = loop.run_in_executor(
                    self._thread_pool,
                    _run_step_analysis, self.generators["claude"], conversation, self.agent_type, "claude"
                )
                gpt_fut = loop.run_in_executor(
                    self._thread_pool,
                    _run_step_analysis, self.generators["gpt"], conversation, self.agent_type, "gpt"
                )

                gemini_fut = None
                run_gemini = (self.generators.get("gemini") and
                              (is_mm or not self.skip_gemini_non_multimodal))
                if run_gemini:
                    gemini_fut = loop.run_in_executor(
                        self._thread_pool,
                        _run_step_analysis, self.generators["gemini"], conversation, self.agent_type, "gemini"
                    )

                # Await all S1 results
                claude_result, gpt_result = await asyncio.gather(claude_fut, gpt_fut)
                gemini_result = await gemini_fut if gemini_fut else None

                # Claude Opus 失败 → 降级 Sonnet 4.5 Think
                if not claude_result or not claude_result.get("success"):
                    if self.claude_degraded_gen:
                        logger.info(f"[{chunk_id}] Claude Opus 失败，降级到 {self.claude_degraded_gen.model}...")
                        claude_result = await loop.run_in_executor(
                            self._thread_pool,
                            _run_step_analysis, self.claude_degraded_gen, conversation, self.agent_type, "claude_degraded"
                        )
                        if claude_result and claude_result.get("success"):
                            claude_result["step"] = "claude"
                            claude_result["model"] = f"{self.claude_degraded_gen.model} (degraded)"
                            with self._stats_lock:
                                self.stats["claude_degraded_to_sonnet"] += 1

                # Claude 仍然失败 → 降级: GPT+Gemini 双分析
                if (not claude_result or not claude_result.get("success")) and self.claude_degradation_to_dual:
                    # 强制跑 Gemini (即使非多模态)
                    if not gemini_result and self.generators.get("gemini"):
                        logger.info(f"[{chunk_id}] Claude 降级 → GPT+Gemini 双分析")
                        gemini_result = await loop.run_in_executor(
                            self._thread_pool,
                            _run_step_analysis, self.generators["gemini"], conversation, self.agent_type, "gemini_degraded"
                        )
                    with self._stats_lock:
                        self.stats["claude_degraded_to_dual"] += 1

                s1_elapsed = time.time() - s1_start

                # S1 details
                c_ok = claude_result and claude_result.get("success")
                g_ok = gpt_result and gpt_result.get("success")
                gem_ok = gemini_result and gemini_result.get("success") if gemini_result else False
                detail = f"C:{'✓' if c_ok else '✗'} G:{'✓' if g_ok else '✗'} Gem:{'✓' if gem_ok else '⏭'}"
                cs.set_stage("s1_analysis", StageStatus.SUCCESS if (c_ok or g_ok) else StageStatus.FAILED,
                             s1_elapsed, detail)
                self.viz.update()
                self.viz.print_stage_change(chunk_id, "s1_analysis",
                                           StageStatus.SUCCESS if (c_ok or g_ok) else StageStatus.FAILED,
                                           f"{detail} ({s1_elapsed:.0f}s)")

            # S1 semaphore released — next chunk's S1 can start now!

            # ── S2: MoA Fusion (Grok) ──
            async with self._grok_sem:
                cs.set_stage("s2_moa", StageStatus.RUNNING)
                self.viz.update()
                self.viz.print_stage_change(chunk_id, "s2_moa", StageStatus.RUNNING)

                s2_start = time.time()
                merged = await loop.run_in_executor(
                    self._thread_pool,
                    lambda: moa_merge_analyses(
                        self.generators["grok"], claude_result, gpt_result, gemini_result,
                        conversation, backup_gen=self.moa_backup, grok_backup_gen=self.grok_backup_gen,
                    ),
                )
                s2_elapsed = time.time() - s2_start

                mq = merged.get("merge_quality", "failed")
                cs.set_stage("s2_moa",
                             StageStatus.SUCCESS if mq != "failed" else StageStatus.FAILED,
                             s2_elapsed, mq)
                self.viz.update()
                self.viz.print_stage_change(chunk_id, "s2_moa",
                                           StageStatus.SUCCESS if mq != "failed" else StageStatus.FAILED,
                                           f"{mq} ({s2_elapsed:.0f}s)")

            # ── S3: Review (Grok) ──
            review = None
            async with self._grok_sem:
                if self.skip_review or mq == "failed":
                    cs.set_stage("s3_review", StageStatus.SKIPPED, detail="skip")
                    self.viz.update()
                    self.viz.print_stage_change(chunk_id, "s3_review", StageStatus.SKIPPED)
                else:
                    cs.set_stage("s3_review", StageStatus.RUNNING)
                    self.viz.update()
                    self.viz.print_stage_change(chunk_id, "s3_review", StageStatus.RUNNING)

                    s3_start = time.time()
                    analysis_text = json.dumps(merged["merged_features"], ensure_ascii=False)
                    review = await loop.run_in_executor(
                        self._thread_pool,
                        lambda conv=conversation, atxt=analysis_text: run_grok_review(
                            self.generators["grok"], conv, atxt,
                            backup_gen=self.grok_backup_gen,
                            kimi_gen=self.moa_backup,
                        ),
                    )
                    s3_elapsed = time.time() - s3_start
                    verdict = review.get("verdict", "?") if review else "fail"
                    cs.set_stage("s3_review", StageStatus.SUCCESS, s3_elapsed, verdict)
                    self.viz.update()
                    self.viz.print_stage_change(chunk_id, "s3_review", StageStatus.SUCCESS,
                                               f"{verdict} ({s3_elapsed:.0f}s)")

            # ── S4: Remediation (Grok) ──
            remediation_rounds = 0
            async with self._grok_sem:
                if (not review or not review.get("scores") or mq == "failed"
                        or self.skip_review):
                    cs.set_stage("s4_remediation", StageStatus.SKIPPED, detail="n/a")
                    self.viz.update()
                    self.viz.print_stage_change(chunk_id, "s4_remediation", StageStatus.SKIPPED)
                else:
                    low_dims = {d: s for d, s in review["scores"].items()
                                if isinstance(s, (int, float)) and s <= REMEDIATION_THRESHOLD}
                    if not low_dims:
                        cs.set_stage("s4_remediation", StageStatus.SKIPPED, detail="all≥8")
                        self.viz.update()
                        self.viz.print_stage_change(chunk_id, "s4_remediation", StageStatus.SKIPPED, "all≥8")
                    else:
                        cs.set_stage("s4_remediation", StageStatus.RUNNING,
                                     detail=f"{len(low_dims)} dims")
                        self.viz.update()
                        self.viz.print_stage_change(chunk_id, "s4_remediation", StageStatus.RUNNING,
                                                   f"{len(low_dims)} low dims")

                        s4_start = time.time()
                        _mf = merged["merged_features"]
                        _rs = review["scores"]
                        new_features, remediation_rounds = await loop.run_in_executor(
                            self._thread_pool,
                            lambda: run_grok_remediation(
                                self.generators["grok"], _mf, _rs, conversation,
                                backup_gen=self.grok_backup_gen,
                                gemini_gen=self.generators.get("gemini"),
                                kimi_gen=self.moa_backup,
                            ),
                        )
                        if remediation_rounds > 0:
                            merged["merged_features"] = new_features
                            # Re-review after remediation
                            _nf_json = json.dumps(new_features, ensure_ascii=False)
                            re_review = await loop.run_in_executor(
                                self._thread_pool,
                                lambda: run_grok_review(
                                    self.generators["grok"], conversation, _nf_json,
                                    backup_gen=self.grok_backup_gen,
                                    kimi_gen=self.moa_backup,
                                ),
                            )
                            if re_review and re_review.get("success"):
                                review = re_review

                        s4_elapsed = time.time() - s4_start
                        cs.set_stage("s4_remediation", StageStatus.SUCCESS, s4_elapsed,
                                     f"×{remediation_rounds}")
                        self.viz.update()
                        self.viz.print_stage_change(chunk_id, "s4_remediation", StageStatus.SUCCESS,
                                                   f"×{remediation_rounds} ({s4_elapsed:.0f}s)")
                        with self._stats_lock:
                            self.stats["remediation_triggered"] += 1

            # ── Assemble result ──
            cs.end_time = time.time()
            result = {
                "chunk_id": chunk_id,
                "agent_type": self.agent_type,
                "conversation": conversation,
                "is_multimodal": is_mm,
                "analysis_features": merged.get("merged_features", {}),
                "merge_source": merged.get("source", ""),
                "merge_quality": merged.get("merge_quality", "failed"),
                "step_details": {
                    "claude": _summarize_step(claude_result),
                    "gpt": _summarize_step(gpt_result),
                    "gemini": _summarize_step(gemini_result) if gemini_result else {"skipped": True},
                    "review": review if review else {"skipped": True},
                },
                "timestamp": datetime.now().isoformat(),
                "pipeline_mode": True,
                "pipeline_elapsed": cs.total_elapsed,
            }

            # MoA extras
            if claude_result and claude_result.get("success"):
                result["claude_raw"] = claude_result["features"]
            if gpt_result and gpt_result.get("success"):
                result["gpt_raw"] = gpt_result["features"]
            result["moa_elapsed"] = merged.get("moa_elapsed", 0)
            result["remediation_rounds"] = remediation_rounds
            if merged.get("moa_fallback"):
                result["moa_fallback"] = True

            if review and review.get("success") and review.get("scores"):
                result["review_scores"] = review["scores"]
                result["review_verdict"] = review.get("verdict", "unknown")
                result["review_total"] = review.get("total_score", 0)

            cs.result = result
            results[idx] = result

            # Update stats
            with self._stats_lock:
                mq = result["merge_quality"]
                if mq == "moa_full":
                    self.stats["moa_full"] += 1
                    self.stats["success"] += 1
                elif mq in ("full", "partial", "degraded"):
                    self.stats["success"] += 1
                else:
                    self.stats["failed"] += 1
                if result.get("moa_fallback"):
                    self.stats["moa_fallback"] += 1
                if result.get("remediation_rounds", 0) > 0:
                    self.stats["remediation_triggered"] += 1
                self.stats["total_time"] = time.time() - self.viz._start_time

            # Write to file
            with file_lock:
                with open(output_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(result, ensure_ascii=False) + "\n")
                    f.flush()

            # 进度持久化 (每 5 个 chunk 写一次)
            done_count = self.stats["success"] + self.stats["failed"]
            if done_count % 5 == 0 or done_count == total:
                self._save_progress(output_path, total)

            self.viz.update()

        # ── 启动所有 chunk 任务 ──
        tasks = [process_chunk(i, chunk) for i, chunk in enumerate(chunks)]
        await asyncio.gather(*tasks)

        self.viz.stop()
        self._print_summary(total)
        return [r for r in results if r is not None]

    def _save_progress(self, output_path: str, total: int):
        """持久化进度到 pipeline_progress.json"""
        try:
            from pathlib import Path
            progress_path = Path(output_path).parent / "pipeline_progress.json"
            s = self.stats
            done = s["success"] + s["failed"]
            elapsed = s["total_time"]
            progress = {
                "done": done,
                "total": total,
                "pct": round(done / total * 100, 1) if total > 0 else 0,
                "success": s["success"],
                "failed": s["failed"],
                "moa_full": s["moa_full"],
                "moa_fallback": s["moa_fallback"],
                "remediation_triggered": s["remediation_triggered"],
                "claude_degraded_to_sonnet": s["claude_degraded_to_sonnet"],
                "claude_degraded_to_dual": s["claude_degraded_to_dual"],
                "elapsed_s": round(elapsed, 1),
                "avg_per_chunk_s": round(elapsed / done, 1) if done > 0 else 0,
                "throughput_per_min": round(done / elapsed * 60, 1) if elapsed > 0 else 0,
                "updated_at": datetime.now().isoformat(),
            }
            with open(progress_path, "w", encoding="utf-8") as f:
                json.dump(progress, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"进度持久化失败: {e}")

    def _print_summary(self, total: int):
        """打印最终统计"""
        s = self.stats
        print()
        print("=" * 60)
        print("🔧 流水线统计:")
        print(f"  总处理: {s['success'] + s['failed']} / {total}")
        print(f"  成功: {s['success']}  失败: {s['failed']}")
        print(f"  MoA融合: {s['moa_full']}  MoA回退: {s['moa_fallback']}")
        print(f"  Claude降级→Sonnet: {s['claude_degraded_to_sonnet']}  Claude降级→GPT+Gemini: {s['claude_degraded_to_dual']}")
        print(f"  补齐触发: {s['remediation_triggered']}")
        print(f"  总耗时: {s['total_time']:.0f}s ({s['total_time']/60:.1f}min)")
        if s['success'] + s['failed'] > 0:
            avg = s['total_time'] / (s['success'] + s['failed'])
            print(f"  平均/chunk: {avg:.1f}s")
            tput = (s['success'] + s['failed']) / s['total_time'] * 60 if s['total_time'] > 0 else 0
            print(f"  吞吐: {tput:.1f} chunk/min")
        print("=" * 60)
