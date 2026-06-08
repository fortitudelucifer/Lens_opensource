#!/usr/bin/env python3
"""
MoA 重融合/修复脚本 — 复用已有分析，只跑融合+审核+补齐

功能：
- 从已有结果文件中提取 Claude/GPT 独立分析（claude_raw / gpt_raw）
- 对有独立分析的 chunk → Grok MoA 有机融合 + 审核 + 补齐
- 对只有 v1 合并结果的 chunk → 直接审核 + 补齐
- 支持完整重跑模式（重新调用 Claude/GPT 分析）
- 零 Claude/GPT API 调用（默认模式），仅调用 Grok/Kimi/Gemini

处理流程：
1. 加载主输出文件中的所有已有结果
2. 根据过滤条件确定待处理 chunk（按 verdict、chunk_id 或全量）
3. 对每个 chunk：
   a. MoA 融合（有 raw 数据时）或复用已有分析
   b. 审核评分（Kimi 主审 → Gemini 备 → Grok 兜底）
   c. 低分维度补齐（Gemini 主补 → Kimi 备 → Grok 兜底）
4. 原地更新主结果集，每 10 条自动保存

三种运行模式：
- 默认模式：MoA 重融合（复用 claude_raw + gpt_raw）
- --review-only：仅重跑审核+补齐，复用已有 analysis_features
- --full-rerun：完整重跑 S1→S4（需要 Claude/GPT 重新分析）

输入：
- advisor_out/analysis/fused_analysis_neutral_moa.jsonl: 主输出文件（已有结果）
- 或自定义 --sources 文件列表

输出：
- advisor_out/analysis/fused_analysis_neutral_moa.jsonl: 更新后的融合分析结果
  * 原子写入（先写 tmp 再 rename），防止数据丢失

依赖：
- scripts/advisor/generator.py: AnalysisGenerator 分析生成器
- scripts/advisor/run_all/_02c_fusion_pipeline.py: 核心融合函数（MoA、审核、补齐）
- local_secrets/key_pool.yaml: 多 API Key 配置

使用示例：
    # 默认：重融合所有 chunk
    source local_secrets/.env.advisor
    python scripts/advisor/run_all/_02c_rerun_moa.py

    # 仅修复审核失败的 chunk
    python scripts/advisor/run_all/_02c_rerun_moa.py --filter-verdict parse_error

    # 仅重跑审核+补齐
    python scripts/advisor/run_all/_02c_rerun_moa.py --review-only

    # 指定 chunk 完整重跑
    python scripts/advisor/run_all/_02c_rerun_moa.py --chunk-ids chunk_1,chunk_5 --full-rerun

    # 限制处理数量
    python scripts/advisor/run_all/_02c_rerun_moa.py --limit 20

性能参考：
- MoA 重融合：约 20-30 秒/chunk
- 仅审核+补齐：约 10-20 秒/chunk
- 完整重跑：约 30-50 秒/chunk

注意事项：
- 默认模式不调用 Claude/GPT，仅消耗 Grok/Kimi/Gemini 配额
- --full-rerun 模式会重新调用 Claude/GPT，注意 API 费用
- 原子写入保证中断后数据不丢失
- 审核 verdict 总分 ≥44 自动强制 pass（Grok verdict 偏严）

作者：[Author]
更新于：2026-02-15
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.advisor.generator import AnalysisGenerator

# 复用 _02c 中的核心函数
from scripts.advisor.run_all._02c_fusion_pipeline import (
    STEP_CONFIGS,
    REMEDIATION_THRESHOLD,
    MAX_REMEDIATION_ROUNDS,
    _create_generator,
    _create_generators_from_pool,
    _strip_thinking_tags,
    _extract_json_robust,
    _try_moa_with_gen,
    moa_merge_analyses,
    run_grok_review,
    run_grok_remediation,
    MOA_AGGREGATOR_PROMPT,
    GEMINI_SECTION_TEMPLATE,
    _run_step_analysis,
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(message)s")


def collect_raw_analyses(source_files: list[str]) -> dict:
    """
    从多个已有结果文件中收集每个 chunk 的最佳数据
    
    优先保留有 claude_raw + gpt_raw 独立分析的版本，
    其次保留 v1 merged 结果。
    
    Args:
        source_files (list[str]): 源文件路径列表
    
    Returns:
        dict: {chunk_id: chunk_data} 映射，chunk_data 包含：
        - claude_raw (dict, 可选): Claude 独立分析结果
        - gpt_raw (dict, 可选): GPT 独立分析结果
        - analysis_features (dict): 分析特征
        - conversation (str): 对话文本
    """
    chunks = {}
    
    for fpath in source_files:
        if not Path(fpath).exists():
            logger.warning(f"文件不存在，跳过: {fpath}")
            continue
        
        with open(fpath, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                r = json.loads(line)
                cid = r.get("chunk_id", "")
                if not cid:
                    continue
                
                has_raw = "claude_raw" in r and "gpt_raw" in r
                existing = chunks.get(cid)
                existing_has_raw = existing and "claude_raw" in existing and "gpt_raw" in existing
                
                # 优先保留有 raw 数据的版本
                if not existing or (has_raw and not existing_has_raw):
                    chunks[cid] = {
                        "chunk_id": cid,
                        "agent_type": r.get("agent_type", "neutral"),
                        "conversation": r.get("conversation", ""),
                        "is_multimodal": r.get("is_multimodal", False),
                        "analysis_features": r.get("analysis_features", {}),
                    }
                    if has_raw:
                        chunks[cid]["claude_raw"] = r["claude_raw"]
                        chunks[cid]["gpt_raw"] = r["gpt_raw"]
    
    return chunks


def rerun_moa_single(
    chunk_data: dict,
    grok_gen: AnalysisGenerator,
    moa_backup: Optional[AnalysisGenerator],
    grok_backup_gen: Optional[AnalysisGenerator] = None,
    gemini_gen: Optional[AnalysisGenerator] = None,
    review_only: bool = False,
    generators: Optional[dict] = None,
) -> dict:
    """
    对单个 chunk 重跑 MoA 融合 + 审核 + 补齐
    
    三种模式：
    - review_only=True: 复用已有 analysis_features，只跑审核+补齐
    - review_only=False + has raw: 完整 MoA 融合 + 审核 + 补齐
    - review_only=False + no raw + generators: 完整 S1→S4 重跑
    
    Args:
        chunk_data (dict): chunk 数据（含 conversation, claude_raw, gpt_raw 等）
        grok_gen (AnalysisGenerator): Grok 主生成器
        moa_backup (AnalysisGenerator): Kimi 备用生成器
        grok_backup_gen (AnalysisGenerator, optional): Grok 备用生成器
        gemini_gen (AnalysisGenerator, optional): Gemini 生成器
        review_only (bool): 是否仅审核+补齐模式
        generators (dict, optional): 完整重跑所需的生成器集合
    
    Returns:
        dict: 完整的融合分析结果，包含 analysis_features, review_scores, 
              review_verdict, merge_quality, remediation_rounds 等
    """
    chunk_id = chunk_data["chunk_id"]
    conversation = chunk_data["conversation"]
    has_raw = "claude_raw" in chunk_data and "gpt_raw" in chunk_data
    
    # ── Step 1: MoA 融合 or 复用 ──
    moa_elapsed = 0
    moa_fallback = False
    analysis_features = chunk_data.get("analysis_features", {})
    merge_quality = chunk_data.get("merge_quality", "unknown")
    merge_source = chunk_data.get("merge_source", "existing")
    step_details = chunk_data.get("step_details", {})
    
    if review_only:
        # 复用已有分析，仅审核+补齐
        pass
    elif has_raw:
        claude_result = {"success": True, "features": chunk_data["claude_raw"]}
        gpt_result = {"success": True, "features": chunk_data["gpt_raw"]}
        merged = moa_merge_analyses(
            grok_gen, claude_result, gpt_result, None,
            conversation, backup_gen=moa_backup, grok_backup_gen=grok_backup_gen,
        )
        analysis_features = merged["merged_features"]
        moa_elapsed = merged.get("moa_elapsed", 0)
        moa_fallback = merged.get("moa_fallback", False)
        merge_quality = merged["merge_quality"]
        merge_source = merged["source"]
    elif generators:
        # 完整重跑 S1 分析
        from concurrent.futures import ThreadPoolExecutor
        agent_type = chunk_data.get("agent_type", "neutral")
        futures = {}
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures["claude"] = pool.submit(
                _run_step_analysis, generators["claude"], conversation, agent_type, "claude"
            )
            futures["gpt"] = pool.submit(
                _run_step_analysis, generators["gpt"], conversation, agent_type, "gpt"
            )
        claude_result = futures["claude"].result()
        gpt_result = futures["gpt"].result()
        step_details = {
            "claude": {"success": claude_result and claude_result.get("success"), "elapsed": claude_result.get("elapsed", 0) if claude_result else 0},
            "gpt": {"success": gpt_result and gpt_result.get("success"), "elapsed": gpt_result.get("elapsed", 0) if gpt_result else 0},
        }
        merged = moa_merge_analyses(
            grok_gen, claude_result, gpt_result, None,
            conversation, backup_gen=moa_backup, grok_backup_gen=grok_backup_gen,
        )
        analysis_features = merged["merged_features"]
        moa_elapsed = merged.get("moa_elapsed", 0)
        moa_fallback = merged.get("moa_fallback", False)
        merge_quality = merged["merge_quality"]
        merge_source = merged["source"]
    else:
        merge_quality = "v1_reuse"
        merge_source = "v1_existing"
    
    # ── Step 2: 审核 — Kimi 主审 → Gemini 备 → Grok-jiuuij 兜底 ──
    review = None
    _review_gen = moa_backup or grok_gen  # Kimi; 若不可用回退 Grok
    if analysis_features:
        analysis_text = json.dumps(analysis_features, ensure_ascii=False)
        review = run_grok_review(
            _review_gen, conversation, analysis_text,
            backup_gen=gemini_gen, kimi_gen=grok_backup_gen,
        )
    
    # ── Step 3: 补齐 — Gemini 主补 → Kimi 备 → Grok-jiuuij 兜底 ──
    remediation_rounds = 0
    if review and review.get("scores") and analysis_features:
        low_dims = {d: s for d, s in review["scores"].items()
                    if isinstance(s, (int, float)) and s <= REMEDIATION_THRESHOLD}
        if low_dims:
            logger.info(f"  [{chunk_id}] 低分维度: {low_dims}, 启动补齐...")
            _rem_primary = gemini_gen or moa_backup or grok_gen
            _rem_backup = moa_backup if gemini_gen else grok_backup_gen
            analysis_features, remediation_rounds = run_grok_remediation(
                _rem_primary, analysis_features, review["scores"], conversation,
                backup_gen=_rem_backup, gemini_gen=grok_backup_gen, kimi_gen=None,
            )
            if remediation_rounds > 0:
                re_review = run_grok_review(
                    _review_gen, conversation,
                    json.dumps(analysis_features, ensure_ascii=False),
                    backup_gen=gemini_gen, kimi_gen=grok_backup_gen,
                )
                if re_review and re_review.get("success"):
                    review = re_review
    
    # ── 组装结果 ──
    result = {
        "chunk_id": chunk_id,
        "agent_type": chunk_data.get("agent_type", "neutral"),
        "conversation": conversation,
        "is_multimodal": chunk_data.get("is_multimodal", False),
        "analysis_features": analysis_features,
        "merge_source": merge_source,
        "merge_quality": merge_quality,
        "moa_elapsed": moa_elapsed,
        "remediation_rounds": remediation_rounds,
        "timestamp": datetime.now().isoformat(),
        "rerun": True,
    }
    if step_details:
        result["step_details"] = step_details
    
    if has_raw:
        result["claude_raw"] = chunk_data["claude_raw"]
        result["gpt_raw"] = chunk_data["gpt_raw"]
    if moa_fallback:
        result["moa_fallback"] = True
    
    if review and review.get("success") and review.get("scores"):
        result["review_scores"] = review["scores"]
        result["review_verdict"] = review.get("verdict", "unknown")
        result["review_total"] = review.get("total_score", 0)
        # 分数覆盖: 总分 ≥44 强制 pass (Grok verdict 偏严)
        if result["review_total"] >= 44 and result["review_verdict"] != "pass":
            result["review_verdict"] = "pass"
    else:
        # 回退: 从 step_details.review 提升到顶层 (兼容旧数据)
        sd_review = step_details.get("review", {}) if step_details else {}
        if sd_review.get("scores") and isinstance(sd_review["scores"], dict) and len(sd_review["scores"]) >= 3:
            result["review_scores"] = sd_review["scores"]
            result["review_verdict"] = sd_review.get("verdict", "unknown")
            total = sd_review.get("total_score", 0)
            if not total:
                total = sum(v for v in sd_review["scores"].values() if isinstance(v, (int, float)))
            result["review_total"] = total
            # 确保 verdict 有效
            if not result["review_verdict"] or result["review_verdict"] in ("parse_error", "unknown"):
                result["review_verdict"] = "pass" if total >= 36 else "needs_revision" if total >= 20 else "fail"
            # 分数覆盖: 总分 ≥44 强制 pass
            if total >= 44 and result["review_verdict"] != "pass":
                result["review_verdict"] = "pass"
    
    return result


def load_main_results(path: str) -> dict:
    """
    从主输出文件加载所有结果，按 chunk_id 去重（保留最新）
    
    Args:
        path (str): JSONL 文件路径
    
    Returns:
        dict: {chunk_id: result_dict} 映射
    """
    by_id = {}
    if not Path(path).exists():
        return by_id
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                by_id[r.get("chunk_id", "")] = r
    return by_id


def save_main_results(by_id: dict, path: str):
    """
    原子写入结果文件：先写 tmp 再 rename，防止中断导致数据丢失
    
    结果按 chunk_id 数字排序输出。
    
    Args:
        by_id (dict): {chunk_id: result_dict} 映射
        path (str): 输出文件路径
    """
    tmp = path + ".tmp"
    sorted_ids = sorted(by_id.keys(), key=lambda x: int(x.replace("chunk_", "")) if x.replace("chunk_", "").isdigit() else 0)
    with open(tmp, "w", encoding="utf-8") as f:
        for cid in sorted_ids:
            f.write(json.dumps(by_id[cid], ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def main():
    parser = argparse.ArgumentParser(description="MoA 重融合/修复 — 复用已有分析或完整重跑")
    parser.add_argument("--sources", type=str, nargs="+", default=None,
                        help="源文件列表 (包含 claude_raw/gpt_raw 或 v1 结果)")
    parser.add_argument("--output", type=str, default=None,
                        help="输出文件 (默认: 主 MoA 输出文件)")
    parser.add_argument("--grok-model", type=str, default=None,
                        help="Grok 模型 (默认从 key_pool 读取)")
    parser.add_argument("--limit", type=int, default=None,
                        help="限制处理数量")
    parser.add_argument("--delay", type=float, default=3.0,
                        help="chunk 之间间隔秒数")
    # 新增过滤参数
    parser.add_argument("--filter-verdict", type=str, default=None,
                        help="只处理指定 verdict 的 chunk (如 parse_error)")
    parser.add_argument("--chunk-ids", type=str, default=None,
                        help="只处理指定 chunk_id 列表 (逗号分隔)")
    parser.add_argument("--review-only", action="store_true",
                        help="仅重跑审核+补齐，复用已有 analysis_features")
    parser.add_argument("--full-rerun", action="store_true",
                        help="完整重跑 S1→S4 (需要 Claude/GPT 重新分析)")
    
    args = parser.parse_args()
    
    workspace = PROJECT_ROOT
    main_output = str(workspace / "advisor_out" / "analysis" / "fused_analysis_neutral_moa.jsonl")
    output_path = args.output or main_output
    
    # ── 加载主输出文件 ──
    print("加载已有结果...")
    all_results = load_main_results(main_output)
    print(f"  已有: {len(all_results)} 条")
    
    # ── 确定待处理 chunk ──
    target_ids = []
    if args.chunk_ids:
        target_ids = [cid.strip() for cid in args.chunk_ids.split(",") if cid.strip()]
        print(f"  指定 chunk: {len(target_ids)} 条")
    elif args.filter_verdict:
        for cid, r in all_results.items():
            v = r.get("review_verdict", "") or ""
            if not v:
                v = r.get("step_details", {}).get("review", {}).get("verdict", "") or ""
            # 支持 "no_verdict" 匹配空/None verdict
            if args.filter_verdict == "no_verdict" and not v:
                target_ids.append(cid)
            elif v == args.filter_verdict:
                target_ids.append(cid)
        target_ids.sort(key=lambda x: int(x.replace("chunk_", "")) if x.replace("chunk_", "").isdigit() else 0)
        print(f"  筛选 verdict={args.filter_verdict}: {len(target_ids)} 条")
    else:
        # 未指定过滤 → 从 sources 收集
        if args.sources is None:
            args.sources = [main_output]
        src_chunks = collect_raw_analyses(args.sources)
        target_ids = sorted(src_chunks.keys(), key=lambda x: int(x.replace("chunk_", "")) if x.replace("chunk_", "").isdigit() else 0)
    
    if args.limit:
        target_ids = target_ids[:args.limit]
    
    if not target_ids:
        print("没有待处理的 chunks")
        return
    
    # 收集 chunk_data
    chunks_to_process = []
    for cid in target_ids:
        if cid in all_results:
            chunks_to_process.append(all_results[cid])
        else:
            logger.warning(f"  {cid} 不在主输出中，跳过")
    
    if not chunks_to_process:
        print("没有可处理的 chunks")
        return
    
    mode_str = "仅审核+补齐" if args.review_only else ("完整重跑" if args.full_rerun else "MoA重融合")
    print(f"  模式: {mode_str}")
    print(f"  待处理: {len(chunks_to_process)}")
    print()
    
    # ── 初始化生成器 ──
    print("初始化生成器...")
    
    # 尝试从 key_pool 加载
    pool_config = None
    pool_path = workspace / "local_secrets" / "key_pool.yaml"
    if pool_path.exists():
        import yaml
        with open(pool_path, "r") as f:
            pool_config = yaml.safe_load(f)
    
    grok_gen = _create_generator("grok", model=args.grok_model)
    print(f"  Grok: {grok_gen.model}")
    
    # Grok 备用 (jiuuij)
    grok_backup_gen = None
    if pool_config and "grok_backup" in pool_config:
        gb_cfg = pool_config["grok_backup"]
        gb_keys = gb_cfg.get("keys", [])
        if gb_keys:
            grok_backup_gen = _create_generator(
                "grok_backup",
                api_key=gb_keys[0],
                base_url=gb_cfg.get("base_url"),
                model=gb_cfg.get("model"),
            )
            print(f"  Grok 备用: {grok_backup_gen.model} @ {grok_backup_gen.base_url}")
    
    # Kimi 备用 (优先从 key_pool 读取)
    moa_backup = None
    kimi_cfg = pool_config.get("kimi", {}) if pool_config else {}
    kimi_keys = kimi_cfg.get("keys", [])
    try:
        if kimi_keys:
            moa_backup = _create_generator(
                "kimi",
                api_key=kimi_keys[0],
                base_url=kimi_cfg.get("base_url"),
                model=kimi_cfg.get("model"),
            )
        else:
            moa_backup = _create_generator("kimi")
        print(f"  Kimi: {moa_backup.model} @ {moa_backup.base_url}")
    except Exception as e:
        logger.warning(f"  Kimi 创建失败 (非致命): {e}")
    
    # Gemini (补齐 fallback, 优先从 key_pool 读取)
    gemini_gen = None
    gemini_cfg = pool_config.get("gemini", {}) if pool_config else {}
    gemini_keys = gemini_cfg.get("keys", [])
    try:
        if gemini_keys:
            gemini_gen = _create_generator(
                "gemini",
                api_key=gemini_keys[0],
                base_url=gemini_cfg.get("base_url"),
                model=gemini_cfg.get("model"),
            )
        else:
            gemini_gen = _create_generator("gemini")
        print(f"  Gemini: {gemini_gen.model} @ {gemini_gen.base_url}")
    except Exception as e:
        logger.warning(f"  Gemini 创建失败 (非致命): {e}")
    
    # 完整重跑需要 Claude + GPT
    generators = None
    if args.full_rerun:
        generators = {
            "claude": _create_generator("claude"),
            "gpt": _create_generator("gpt"),
            "grok": grok_gen,
            "gemini": gemini_gen,
        }
        print(f"  Claude: {generators['claude'].model}")
        print(f"  GPT: {generators['gpt'].model}")
    
    print()
    
    # ── 统计 ──
    stats = {
        "moa_full": 0, "v1_reuse": 0, "moa_fallback": 0,
        "review_pass": 0, "review_needs_revision": 0, "review_fail": 0,
        "review_parse_error": 0, "remediation_triggered": 0, "total_time": 0,
    }
    
    # ── 处理 ──
    updated_count = 0
    for i, chunk_data in enumerate(chunks_to_process):
        cid = chunk_data["chunk_id"]
        has_raw = "claude_raw" in chunk_data
        if args.review_only:
            mode = "审核+补齐"
        elif args.full_rerun:
            mode = "完整重跑"
        else:
            mode = "MoA融合" if has_raw else "审核+补齐"
        
        print(f"[{i+1}/{len(chunks_to_process)}] {cid} ({mode})...", end=" ", flush=True)
        
        start = time.time()
        result = rerun_moa_single(
            chunk_data, grok_gen, moa_backup,
            grok_backup_gen=grok_backup_gen,
            gemini_gen=gemini_gen,
            review_only=args.review_only,
            generators=generators if args.full_rerun else None,
        )
        elapsed = time.time() - start
        stats["total_time"] += elapsed
        
        # 统计
        mq = result.get("merge_quality", "?")
        if mq == "moa_full":
            stats["moa_full"] += 1
        elif mq == "v1_reuse":
            stats["v1_reuse"] += 1
        if result.get("moa_fallback"):
            stats["moa_fallback"] += 1
        if result.get("remediation_rounds", 0) > 0:
            stats["remediation_triggered"] += 1
        
        verdict = result.get("review_verdict", "")
        if verdict == "pass":
            stats["review_pass"] += 1
        elif verdict == "needs_revision":
            stats["review_needs_revision"] += 1
        elif verdict == "fail":
            stats["review_fail"] += 1
        else:
            stats["review_parse_error"] += 1
        
        # 打印
        moa_t = result.get("moa_elapsed", 0)
        rem_r = result.get("remediation_rounds", 0)
        total_score = result.get("review_total", 0)
        moa_str = f" MoA({moa_t:.0f}s)" if moa_t else ""
        rem_str = f" Rem×{rem_r}" if rem_r else ""
        fb_str = " [FB]" if result.get("moa_fallback") else ""
        
        print(f"{moa_str} Rev:{verdict}({total_score}){rem_str}{fb_str} [{mq}] ({elapsed:.0f}s)")
        
        # 原地更新主结果集
        all_results[cid] = result
        updated_count += 1
        
        # 每 10 条保存一次
        if updated_count % 10 == 0:
            save_main_results(all_results, output_path)
            print(f"  [已保存 {updated_count} 条更新]")
        
        # 间隔
        if i < len(chunks_to_process) - 1:
            time.sleep(args.delay)
    
    # 最终保存
    save_main_results(all_results, output_path)
    
    # ── 汇总 ──
    total = len(chunks_to_process)
    print()
    print("=" * 60)
    print(f"修复统计 ({mode_str}):")
    print(f"  总处理: {total}")
    print(f"  MoA融合: {stats['moa_full']}  v1复用: {stats['v1_reuse']}  MoA回退: {stats['moa_fallback']}")
    print(f"  审核通过: {stats['review_pass']}  需修改: {stats['review_needs_revision']}  不合格: {stats['review_fail']}  解析失败: {stats['review_parse_error']}")
    print(f"  补齐触发: {stats['remediation_triggered']}")
    print(f"  总耗时: {stats['total_time']:.0f}s ({stats['total_time']/60:.1f}min)")
    print(f"  输出: {output_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
