"""services/pipeline_service.py — 流水线阶段执行（Phase 1/2/3）

从 server.py 迁移（Step 6）：
  - `_run_phase_sync`        → `run_phase_sync`
  - `_run_phase1_extract`    → `run_phase1_extract`
  - `_run_phase2_generate`   → `run_phase2_generate`
  - `_run_phase3_ai_review`  → `run_phase3_ai_review`

Phase 3 执行完后调用 review_service.load_review_cache 刷新审核缓存。
"""
from __future__ import annotations

import json
import time as _time
import uuid
from pathlib import Path

from scripts.advisor.extractor import ConversationExtractor

from ..core import state
from ..core.config import (
    ANALYSIS_DIR, CHUNKS_DIR, REVIEW_DIR,
    USER_WORKSPACE, WORKSPACE,
)
from ..core.models import PipelineRunRequest
from ..core.utils import load_jsonl, mirror_to_user_workspace
from .generator_service import get_generator


def run_phase_sync(phase: int, req: PipelineRunRequest):
    """同步执行 pipeline 阶段"""
    try:
        if phase == 1:
            run_phase1_extract(req)
        elif phase == 2:
            run_phase2_generate(req)
        elif phase == 3:
            run_phase3_ai_review(req)
        else:
            state.pipeline_state["phases"][phase]["detail"] = "该阶段暂未实现自动化"
            state.pipeline_state["phases"][phase]["status"] = "idle"
            state.pipeline_state["running_task"] = None
            return

        state.pipeline_state["phases"][phase]["status"] = "done"
    except Exception as e:
        state.pipeline_state["phases"][phase]["status"] = "error"
        state.pipeline_state["phases"][phase]["detail"] = str(e)[:200]
    finally:
        state.pipeline_state["running_task"] = None


def run_phase1_extract(req: PipelineRunRequest):
    """Phase 1: 提取对话片段"""
    if req.input_file:
        input_path = req.input_file
    elif req.input_type == "l1":
        input_path = str(USER_WORKSPACE / "timeline_out" / "agent_sft_l1.jsonl")
    else:
        input_path = str(USER_WORKSPACE / "timeline_out" / "agent_sft_l2.jsonl")

    # 也尝试本地工作空间
    if not Path(input_path).exists():
        alt = WORKSPACE / "timeline_out" / f"agent_sft_{req.input_type}.jsonl"
        if alt.exists():
            input_path = str(alt)

    output_path = str(CHUNKS_DIR / "conversation_chunks.jsonl")

    state.pipeline_state["phases"][1]["detail"] = f"提取中... input={Path(input_path).name}"

    config = {
        "window_size": 20,
        "step_size": 10,
        "min_messages": 5,
        "exclude_system": True,
        "exclude_types": [],
    }
    extractor = ConversationExtractor(config)
    chunks = extractor.extract_chunks(input_path, num_chunks=req.num_chunks)
    extractor.save_chunks(chunks, output_path)

    stats = extractor.get_stats()
    state.pipeline_state["phases"][1]["detail"] = (
        f"已提取 {stats['filtered_chunks']} 个片段 "
        f"(冲突:{stats['conflict_chunks']} 甜蜜:{stats['sweet_chunks']} 普通:{stats['normal_chunks']})"
    )
    mirror_to_user_workspace()


def run_phase2_generate(req: PipelineRunRequest):
    """Phase 2: LLM 分析生成

    fusion_mode=True (默认): 多专家并行融合 (Claude+GPT+Gemini+Grok)
    fusion_mode=False: 单后端生成 (向后兼容)
    """
    input_path = str(CHUNKS_DIR / "conversation_chunks.jsonl")

    if not Path(input_path).exists():
        raise FileNotFoundError("请先运行 Phase 1 提取对话片段")

    chunks = load_jsonl(Path(input_path))
    if req.limit:
        chunks = chunks[: req.limit]

    if req.fusion_mode:
        # ── 融合模式: 并行调用 Claude+GPT+(Gemini)+Grok ──
        from scripts.advisor.run_all._02c_fusion_pipeline import (
            _create_generator, process_single_chunk, scan_completed,
        )

        output_path = str(ANALYSIS_DIR / f"fused_analysis_{req.agent_type}.jsonl")
        state.pipeline_state["phases"][2]["detail"] = (
            f"融合生成中... agent={req.agent_type} n={len(chunks)} (Claude+GPT+Grok)"
        )

        generators = {
            "claude": _create_generator("claude"),
            "gpt": _create_generator("gpt"),
            "gemini": _create_generator("gemini"),
            "grok": _create_generator("grok"),
        }

        completed_ids = scan_completed(output_path)
        pending = [c for c in chunks if c.get("chunk_id", "") not in completed_ids]

        success = 0
        failed = 0
        with open(output_path, "a", encoding="utf-8") as f:
            for i, chunk in enumerate(pending):
                state.pipeline_state["phases"][2]["detail"] = (
                    f"融合中... [{i+1}/{len(pending)}] {chunk.get('chunk_id','')} "
                    f"(ok={success} fail={failed})"
                )
                result = process_single_chunk(
                    chunk, req.agent_type, generators,
                    skip_gemini_non_multimodal=True,
                    skip_review=False,
                )
                mq = result.get("merge_quality", "failed")
                if mq != "failed":
                    success += 1
                else:
                    failed += 1
                f.write(json.dumps(result, ensure_ascii=False) + "\n")
                f.flush()
                _time.sleep(3.0)

        state.pipeline_state["phases"][2]["detail"] = (
            f"融合完成: 成功={success} 失败={failed} (共{len(completed_ids)+success+failed}条)"
        )
    else:
        # ── 单后端模式 (向后兼容) ──
        output_path = str(ANALYSIS_DIR / f"raw_analysis_{req.agent_type}.jsonl")
        state.pipeline_state["phases"][2]["detail"] = (
            f"生成中... backend={req.backend} agent={req.agent_type} n={len(chunks)}"
        )
        gen = get_generator(req.backend)
        gen.batch_generate(chunks, req.agent_type, output_path)

        stats = gen.get_stats()
        state.pipeline_state["phases"][2]["detail"] = (
            f"完成: 成功={stats['success']} 失败={stats['failed']} tokens={stats['total_tokens']}"
        )

    mirror_to_user_workspace()


def run_phase3_ai_review(req: PipelineRunRequest):
    """Phase 3: AI 辅助审核

    执行完后调用 review_service.load_review_cache 刷新缓存。
    """
    # 优先使用融合分析结果，否则回退到单后端结果
    fused_path = ANALYSIS_DIR / f"fused_analysis_{req.agent_type}.jsonl"
    raw_path = ANALYSIS_DIR / f"raw_analysis_{req.agent_type}.jsonl"
    input_path = str(fused_path if fused_path.exists() else raw_path)
    output_path = str(REVIEW_DIR / f"ai_review_{req.agent_type}.jsonl")

    if not Path(input_path).exists():
        raise FileNotFoundError("请先运行 Phase 2 生成分析")

    items = load_jsonl(Path(input_path))
    if req.limit:
        items = items[: req.limit]

    state.pipeline_state["phases"][3]["detail"] = (
        f"审核中... backend={req.backend} n={len(items)}"
    )

    # 导入审核函数
    from scripts.advisor.run_all._03b_ai_review import review_single

    reviewer = get_generator(req.backend)
    results = []
    passed = 0
    failed = 0

    with open(output_path, "w", encoding="utf-8") as f:
        for i, item in enumerate(items):
            state.pipeline_state["phases"][3]["detail"] = f"审核中 {i+1}/{len(items)}"
            review = review_single(reviewer, item)

            if review.get("passed"):
                passed += 1
            else:
                failed += 1

            output_item = {
                "id": str(uuid.uuid4()),
                "chunk_id": item.get("chunk_id", ""),
                "conversation": item.get("conversation", ""),
                "analysis_features": item.get("analysis_features", {}),
                "agent_type": item.get("agent_type", req.agent_type),
                "review": review,
                "human_decision": None,  # 等待人工审核
            }
            results.append(output_item)
            f.write(json.dumps(output_item, ensure_ascii=False) + "\n")
            _time.sleep(5.0)

    state.pipeline_state["phases"][3]["detail"] = (
        f"完成: 通过={passed} 不通过={failed}"
    )

    # 加载到审核缓存（避免循环引用：延迟 import）
    from . import review_service
    review_service.load_review_cache(req.agent_type)
    mirror_to_user_workspace()
