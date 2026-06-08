#!/usr/bin/env python3
"""
多专家并行融合流水线 — Phase 2 升级版

功能：
- 并行调用 Claude / GPT / Gemini 三个 LLM 生成独立关系分析
- 使用 Grok 作为 MoA（Mixture of Agents）聚合器进行有机融合
- Grok 审核校验融合结果，低分维度自动补齐
- 支持多 API Key 轮转、全局限速、断点续跑

处理流程（每个 chunk）：
1. Step 1-3（并行）：
   a. Claude Opus 4.6 Think — 深度心理分析（主分析师）
   b. GPT-5.2 xhigh — 批判性审视（独立审视）
   c. Gemini 3 Pro — 多模态信号分析（可选，仅多模态对话触发）
2. Step 4: MoA 有机融合（Grok 聚合器重写两份独立分析）
   - Fallback 链：Grok(OpenAI-compatible proxy) → Grok(backup provider) → Kimi → v1 程序合并
3. Step 5: Grok 审核校验（5 维度 1-10 分评分）
4. Step 6: 低分维度补齐（≤7 分触发，最多 3 轮）
5. 输出最终融合分析 JSONL

并行策略：
- Steps 1/2/3 使用不同 API Key → ThreadPoolExecutor 真并行
- 账户总 RPM ≤ 20（OpenAI-compatible proxy 所有 key 合计），全局限速器控制
- 整体吞吐：约 3 chunks/min（瓶颈为单步最慢的模型）

MoA 融合策略：
- v2（默认）：Grok 聚合器有机重写，取两家之长、去冗余、补盲点、解决冲突
- v1（回退）：程序合并规则（Claude 主体 + GPT 补充 + Gemini 多模态覆盖）

审核维度：
- 准确性（1-10）：分析是否准确反映对话内容
- 深度（1-10）：是否有深层心理洞察
- 多模态（1-10）：是否正确解读语音/表情/图片信号
- 结构（1-10）：JSON 格式是否完整规范
- 中文质量（1-10）：语言是否自然流畅有共情感

输入：
- advisor_out/chunks/conversation_chunks.jsonl: 对话片段
- local_secrets/key_pool.yaml: 多 API Key 配置（可选）
- local_secrets/platforms.yaml: API 平台配置

输出：
- advisor_out/analysis/fused_analysis_neutral_moa.jsonl: 融合分析结果
  * 包含：analysis_features, claude_raw, gpt_raw, review_scores, merge_quality 等

依赖：
- scripts/advisor/generator.py: AnalysisGenerator 分析生成器
- scripts/advisor/key_rotator.py: KeyRotator API Key 轮转器（多 worker 模式）
- concurrent.futures: 并行执行

使用示例：
    # 加载环境变量并运行
    source local_secrets/.env.advisor
    python scripts/advisor/run_all/_02c_fusion_pipeline.py --limit 10

    # 全量处理 500 个 chunks
    python scripts/advisor/run_all/_02c_fusion_pipeline.py

    # 跳过 Gemini（非多模态对话不需要）
    python scripts/advisor/run_all/_02c_fusion_pipeline.py --skip-gemini

性能参考：
- 单个 chunk 完整流程：约 20-40 秒（取决于最慢的模型）
- 全量 500 chunks：约 2.5-4 小时
- MoA 融合：约 10-20 秒/chunk
- 审核+补齐：约 10-15 秒/chunk

注意事项：
- 需要配置多个 API Key（Claude、GPT、Gemini、Grok）
- 建议先用 --limit 10 测试小批量
- Grok thinking 模型可能出现截断，已内置自动检测和备用切换
- Cloudflare HTML 错误页面已内置检测和重试机制
- 断点续跑通过检查输出文件已有记录实现

作者：[Author]
更新于：2026-02-15
"""

import argparse
import json
import logging
import os
import signal
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.advisor.generator import AnalysisGenerator

logger = logging.getLogger(__name__)

# KeyRotator 延迟导入（仅 --workers > 1 时使用）
_KeyRotator = None
_load_key_pool = None
_create_rotators_from_pool = None

def _init_key_rotator():
    """延迟加载 KeyRotator 模块"""
    global _KeyRotator, _load_key_pool, _create_rotators_from_pool
    if _KeyRotator is None:
        from scripts.advisor.key_rotator import KeyRotator, load_key_pool, create_rotators_from_pool
        _KeyRotator = KeyRotator
        _load_key_pool = load_key_pool
        _create_rotators_from_pool = create_rotators_from_pool

# ── 融合步骤配置 ─────────────────────────────────────────────
STEP_CONFIGS = {
    "claude": {
        "backend": "claude",
        "role": "主分析师 (深度心理分析)",
        "max_tokens": 65536,
        "rate_limit_delay": 5.0,
        "retry_delay": 18.0,
        "max_retries": 7,
    },
    "gpt": {
        "backend": "openai",
        "role": "独立审视 (批判性分析)",
        "max_tokens": 65536,
        "rate_limit_delay": 5.0,
        "retry_delay": 18.0,
        "max_retries": 7,
    },
    "gemini": {
        "backend": "gemini",
        "role": "多模态专家",
        "max_tokens": 65536,
        "rate_limit_delay": 5.0,
        "retry_delay": 18.0,
        "max_retries": 5,
    },
    "grok": {
        "backend": "grok",
        "role": "审核校验",
        "max_tokens": 65536,
        "rate_limit_delay": 5.0,
        "retry_delay": 18.0,
        "max_retries": 7,
    },
    "kimi": {
        "backend": "kimi",
        "role": "MoA 备用聚合器",
        "max_tokens": 65536,
        "rate_limit_delay": 5.0,
        "retry_delay": 18.0,
        "max_retries": 5,
    },
    "grok_backup": {
        "backend": "grok",
        "role": "Grok 备用 (backup provider)",
        "max_tokens": 65536,
        "rate_limit_delay": 5.0,
        "retry_delay": 18.0,
        "max_retries": 5,
    },
}

# 多模态触发关键词
MULTIMODAL_TRIGGERS = ["[图片:", "[语音:", "[表情:", "情绪:"]
MULTIMODAL_THRESHOLD = 3  # 多模态标记数量 >= 此值才触发 Gemini


def _is_multimodal(conversation: str, mm_density: dict | None = None) -> bool:
    """判断对话是否包含足够的多模态信号（D1: 优先使用 mm_density 元数据）"""
    if mm_density and mm_density.get('total_multimodal', 0) > 0:
        return mm_density['total_multimodal'] >= MULTIMODAL_THRESHOLD
    count = sum(conversation.count(tag) for tag in MULTIMODAL_TRIGGERS)
    return count >= MULTIMODAL_THRESHOLD


def _is_html_error(response: str) -> bool:
    """检测 API 返回是否为 Cloudflare HTML 错误页面（502/503/429 等）"""
    if not response:
        return False
    head = response[:200].lower()
    return any(marker in head for marker in (
        "<!doctype", "<html", "502 bad gateway", "503 service",
        "cloudflare", "just a moment", "error 502", "error 503",
    ))


def _create_generator(
    step_key: str,
    api_key: str = None,
    base_url: str = None,
    model: str = None,
    backend: str = None,
) -> AnalysisGenerator:
    """为指定步骤创建 generator (自动从 env 读取 key/url/model, 或使用显式参数)"""
    cfg = STEP_CONFIGS[step_key]
    config = {
        "backend": backend or cfg["backend"],
        "max_tokens": cfg["max_tokens"],
        "rate_limit_delay": cfg["rate_limit_delay"],
        "retry_delay": cfg["retry_delay"],
        "max_retries": cfg["max_retries"],
    }
    if api_key:
        config["api_key"] = api_key
    if base_url:
        config["base_url"] = base_url
    if model:
        config["model"] = model
    return AnalysisGenerator(config)


def _create_generators_from_pool(
    pool_config: dict,
    rotators: dict,
    skip_gemini: bool = False,
    grok_model: str = None,
    grok_backend: str = None,
) -> dict:
    """
    从 key_pool 配置创建 generators 集合。
    每个 generator 使用 pool 中的第一个 key 初始化，后续由 rotator 动态切换。
    """
    generators = {}
    for step_key in ("claude", "gpt", "grok"):
        agent_cfg = pool_config.get(step_key, {})
        keys = agent_cfg.get("keys", [])
        if keys:
            generators[step_key] = _create_generator(
                step_key,
                api_key=keys[0],
                base_url=agent_cfg.get("base_url"),
                model=grok_model if step_key == "grok" and grok_model else agent_cfg.get("model"),
                backend=grok_backend if step_key == "grok" and grok_backend else None,
            )
        else:
            generators[step_key] = _create_generator(
                step_key,
                model=grok_model if step_key == "grok" else None,
                backend=grok_backend if step_key == "grok" else None,
            )

    if not skip_gemini:
        agent_cfg = pool_config.get("gemini", {})
        keys = agent_cfg.get("keys", [])
        if keys:
            generators["gemini"] = _create_generator(
                "gemini",
                api_key=keys[0],
                base_url=agent_cfg.get("base_url"),
                model=agent_cfg.get("model"),
            )
        else:
            generators["gemini"] = _create_generator("gemini")
    else:
        generators["gemini"] = None

    return generators


def _run_step_analysis(
    gen: AnalysisGenerator,
    conversation: str,
    agent_type: str,
    step_name: str,
) -> Optional[dict]:
    """运行单步分析，返回 features dict 或 None"""
    start = time.time()
    try:
        result = gen.generate_analysis(conversation, agent_type)
        elapsed = time.time() - start
        if result:
            features = result.get_features_for_local()
            safe_context = gen.safety.sanitize_for_local(result)
            return {
                "success": True,
                "step": step_name,
                "elapsed": elapsed,
                "features": features.model_dump(),
                "safe_context": safe_context,
                "repair_attempts": result.rationale_private.repair_attempts,
                "model": gen.model,
            }
        else:
            logger.warning(f"[{step_name}] 返回为空 ({elapsed:.1f}s)")
            return {"success": False, "step": step_name, "elapsed": elapsed, "error": "返回为空"}
    except Exception as e:
        elapsed = time.time() - start
        logger.error(f"[{step_name}] 异常: {e} ({elapsed:.1f}s)")
        return {"success": False, "step": step_name, "elapsed": elapsed, "error": str(e)[:200]}


# ── Step 4 v1: 程序合并规则 (保留作为 fallback) ───────────────
def merge_analyses(
    claude_result: Optional[dict],
    gpt_result: Optional[dict],
    gemini_result: Optional[dict] = None,
) -> dict:
    """
    v1 程序合并: Claude 主体 + GPT 补充 + Gemini 多模态覆盖。
    """
    # 如果 Claude 失败，降级到 GPT
    if not claude_result or not claude_result.get("success"):
        if gpt_result and gpt_result.get("success"):
            return {
                "merged_features": gpt_result["features"],
                "source": "gpt_only (claude_failed)",
                "merge_quality": "degraded",
            }
        return {"merged_features": {}, "source": "all_failed", "merge_quality": "failed"}

    base = dict(claude_result["features"])

    # GPT 补充
    if gpt_result and gpt_result.get("success"):
        gpt_f = gpt_result["features"]

        # key_issues: 合并去重 top 4
        base_issues = base.get("key_issues", [])
        gpt_issues = gpt_f.get("key_issues", [])
        merged_issues = _merge_string_lists(base_issues, gpt_issues, max_items=4)
        base["key_issues"] = merged_issues

        # criticism: 合并
        base_crit = base.get("criticism", {})
        gpt_crit = gpt_f.get("criticism", {})
        if isinstance(base_crit, dict) and isinstance(gpt_crit, dict):
            for party in ["party_a", "party_b"]:
                base_list = base_crit.get(party, [])
                gpt_list = gpt_crit.get(party, [])
                if isinstance(base_list, list) and isinstance(gpt_list, list):
                    base_crit[party] = _merge_string_lists(base_list, gpt_list, max_items=4)
            base["criticism"] = base_crit

        # advice: 合并去重
        base_advice = base.get("advice", [])
        gpt_advice = gpt_f.get("advice", [])
        base["advice"] = _merge_string_lists(base_advice, gpt_advice, max_items=4)

        # time_patterns: Claude 主导, GPT 补充漏检
        base_tp = base.get("time_patterns", [])
        gpt_tp = gpt_f.get("time_patterns", [])
        base["time_patterns"] = _merge_string_lists(base_tp, gpt_tp, max_items=4)

        # conflict_root_causes: 取并集 top 3
        base_crc = base.get("conflict_root_causes", [])
        gpt_crc = gpt_f.get("conflict_root_causes", [])
        base["conflict_root_causes"] = _merge_string_lists(base_crc, gpt_crc, max_items=3)

        # risk_level: 取更高风险
        risk_order = {"低": 0, "中": 1, "高": 2, "极高": 3, "low": 0, "medium": 1, "high": 2, "critical": 3}
        base_risk = base.get("risk_level", "低")
        gpt_risk = gpt_f.get("risk_level", "低")
        if risk_order.get(gpt_risk, 0) > risk_order.get(base_risk, 0):
            base["risk_level"] = gpt_risk

        # overall_assessment: 融合
        base_oa = base.get("overall_assessment", "")
        gpt_oa = gpt_f.get("overall_assessment", "")
        if gpt_oa and base_oa and gpt_oa != base_oa:
            base["overall_assessment"] = (
                f"{base_oa}\n\n【GPT 补充视角】{gpt_oa}"
            )

    # Gemini 多模态覆盖
    if gemini_result and gemini_result.get("success"):
        gem_f = gemini_result["features"]
        gem_mm = gem_f.get("multimodal_signals", [])
        if gem_mm:
            base["multimodal_signals"] = gem_mm

    source_parts = ["claude"]
    if gpt_result and gpt_result.get("success"):
        source_parts.append("gpt")
    if gemini_result and gemini_result.get("success"):
        source_parts.append("gemini")

    return {
        "merged_features": base,
        "source": "+".join(source_parts),
        "merge_quality": "full" if len(source_parts) >= 2 else "partial",
    }


# ── Step 4 v2: MoA 有机融合 (Grok Aggregator) ────────────────

MOA_AGGREGATOR_PROMPT = """你是一位资深关系心理学专家。现在需要将两位独立分析师的报告有机融合成一份更完整、更精确的关系分析。

【分析师 A (Claude — 擅长深层心理洞察) 的独立分析】
{claude_analysis}

【分析师 B (GPT — 擅长结构化批判) 的独立分析】
{gpt_analysis}

{gemini_section}

【原始对话】
{conversation}

【融合要求】
1. 取两家之长：整合 Claude 的心理深度洞察和 GPT 的结构化批判视角
2. 去除冗余：两家重复的观点只保留表述更精准、更有证据支撑的版本
3. 补盲点：一家遗漏而另一家发现的重要洞察，必须纳入
4. 冲突解决：如两家判断矛盾，结合原始对话给出你的独立判断，并说明理由
5. 质量提升：融合后的每个字段应比任何单一来源都更丰富、更有深度
6. **只输出纯 JSON 对象。不要代码块标记（不要```）、不要解释、不要前后文字。直接以 {{ 开头，以 }} 结尾。**

输出格式:
{{
  "relationship_status": "健康期|甜蜜期|平淡期|冷淡期|冲突期",
  "communication_quality": "优秀|良好|一般|较差|很差",
  "emotional_balance": "详细描述情绪投入对等性",
  "key_issues": ["问题1（含证据引用）", "问题2", "问题3"],
  "advice": ["可操作建议1", "建议2", "建议3"],
  "criticism": {{"ME": "基于具体行为的批评", "OTHER": "基于具体行为的批评"}},
  "time_patterns": ["模式1: 具体描述和证据", "模式2"],
  "conflict_root_causes": ["根源①: 证据描述", "根源②"],
  "multimodal_signals": "多模态情感信号的综合解读",
  "repair_attempts": "修复尝试的识别与效果评估",
  "personality_dynamics": "双方沟通风格与依附倾向描述",
  "overall_assessment": "关系现状、核心矛盾、发展趋势",
  "risk_level": "无|低|中|高|紧急"
}}

再次强调：只输出一个纯 JSON 对象，不要任何其他文字。"""

GEMINI_SECTION_TEMPLATE = """【分析师 C (Gemini — 多模态专家) 的补充分析】
{gemini_analysis}
"""

REMEDIATION_THRESHOLD = 7   # 单项 ≤ 此值触发补齐
MAX_REMEDIATION_ROUNDS = 3  # 最大补齐轮次

REMEDIATION_PROMPT = """以下关系分析在 {low_dims} 维度评分偏低 (≤7)。请针对这些维度进行定向改进，使其达到 ≥8 的水平。
保持其他维度的内容不变，仅改进指出的缺陷部分。

【低分维度详情】
{low_dims_detail}

【当前分析 JSON】
{fused_analysis}

【原始对话】
{conversation}

只输出改进后的完整 JSON，格式与输入完全一致。直接以 {{ 开头，以 }} 结尾。不要代码块标记、不要解释、不要其他文字。"""


def _try_moa_with_gen(gen: AnalysisGenerator, prompt: str, label: str) -> tuple:
    """尝试用指定 generator 执行 MoA 融合，返回 (fused_dict, elapsed) 或 (None, elapsed)"""
    start = time.time()
    raw = None
    max_attempts = 3
    attempt = 0
    while attempt < max_attempts:
        try:
            raw = gen._call_api(prompt)
            if raw and _is_html_error(raw):
                logger.warning(f"[MoA {label}] Cloudflare HTML 响应，等待 30s 重试 (不计入重试次数)")
                raw = None
                time.sleep(30)
                continue
            # 检测 thinking 模型截断: <think> 后实际内容不足
            if raw and '</think>' in raw:
                after_think = raw[raw.index('</think>') + len('</think>'):]
                if len(after_think.strip()) < 100:
                    logger.warning(f"[MoA {label}] thinking 截断 ({len(after_think.strip())} chars)，切换备用")
                    raw = None
                    break  # 直接跳到备用，不再重试主线
            if raw:
                break
        except Exception as e:
            logger.warning(f"[MoA {label}] attempt {attempt+1} failed: {e}")
            time.sleep(10)
        attempt += 1
    elapsed = time.time() - start

    if not raw:
        logger.warning(f"[MoA {label}] 返回为空")
        return None, elapsed

    text = _strip_thinking_tags(raw)
    fused = _extract_json_robust(text)
    if fused is None:
        logger.warning(f"[MoA {label}] JSON 解析失败 (raw_len={len(raw)})")
        debug_path = PROJECT_ROOT / "advisor_out" / "analysis" / "_moa_debug_fail.txt"
        try:
            with open(debug_path, "a", encoding="utf-8") as df:
                df.write(f"\n{'='*60}\n[{label}] RAW (len={len(raw)}):\n{raw[:3000]}\n")
                df.write(f"\nSTRIPPED (len={len(text)}):\n{text[:3000]}\n")
        except Exception:
            pass
        return None, elapsed

    # 字段数校验: MoA 融合结果至少 6 个字段才算有效 (防止截断后自动修复出 3 字段)
    _MIN_MOA_FIELDS = 6
    if isinstance(fused, dict) and len(fused) < _MIN_MOA_FIELDS:
        logger.warning(f"[MoA {label}] 字段不足 ({len(fused)}/{_MIN_MOA_FIELDS})，判定为截断: {list(fused.keys())}")
        return None, elapsed

    return fused, elapsed


def moa_merge_analyses(
    grok_gen: AnalysisGenerator,
    claude_result: Optional[dict],
    gpt_result: Optional[dict],
    gemini_result: Optional[dict],
    conversation: str,
    backup_gen: Optional[AnalysisGenerator] = None,
    grok_backup_gen: Optional[AnalysisGenerator] = None,
) -> dict:
    """
    v2 MoA 有机融合: Grok Aggregator 重写两份独立分析。
    Fallback 链: Grok(OpenAI-compatible proxy) → Grok(backup provider) → Kimi → v1 程序合并。

    即使一方失败，另一方的完整分析仍可独立使用。
    双方都成功时，Grok 做有机融合重写。
    """
    claude_ok = claude_result and claude_result.get("success")
    gpt_ok = gpt_result and gpt_result.get("success")
    gemini_ok = gemini_result and gemini_result.get("success")

    # 都失败
    if not claude_ok and not gpt_ok:
        return {"merged_features": {}, "source": "all_failed", "merge_quality": "failed"}

    # 仅一方成功 → 直接用该方结果（不需要 Grok 融合）
    if claude_ok and not gpt_ok:
        return {
            "merged_features": claude_result["features"],
            "source": "claude_only (gpt_failed)",
            "merge_quality": "partial",
        }
    if gpt_ok and not claude_ok:
        return {
            "merged_features": gpt_result["features"],
            "source": "gpt_only (claude_failed)",
            "merge_quality": "partial",
        }

    # 双方都成功 → MoA 有机融合
    claude_json = json.dumps(claude_result["features"], ensure_ascii=False, indent=2)
    gpt_json = json.dumps(gpt_result["features"], ensure_ascii=False, indent=2)

    gemini_section = ""
    if gemini_ok:
        gemini_json = json.dumps(gemini_result["features"], ensure_ascii=False, indent=2)
        gemini_section = GEMINI_SECTION_TEMPLATE.format(gemini_analysis=gemini_json)

    prompt = MOA_AGGREGATOR_PROMPT.format(
        claude_analysis=claude_json,
        gpt_analysis=gpt_json,
        gemini_section=gemini_section,
        conversation=conversation[:4000],
    )

    # 主聚合器 (Grok OpenAI-compatible proxy)
    fused, elapsed = _try_moa_with_gen(grok_gen, prompt, f"Grok({grok_gen.model})")

    # 备用聚合器 1: Grok (backup provider)
    if fused is None and grok_backup_gen is not None:
        logger.info(f"[MoA] Grok 主线失败，切换到 backup provider {grok_backup_gen.model}...")
        fused, backup_elapsed = _try_moa_with_gen(grok_backup_gen, prompt, f"GrokBackup({grok_backup_gen.model})")
        elapsed += backup_elapsed

    # 备用聚合器 2: Kimi
    if fused is None and backup_gen is not None:
        logger.info(f"[MoA] Grok 全线失败，切换到 Kimi {backup_gen.model}...")
        fused, backup_elapsed = _try_moa_with_gen(backup_gen, prompt, f"Kimi({backup_gen.model})")
        elapsed += backup_elapsed

    # 全部失败 → v1 程序合并
    if fused is None:
        logger.warning("[MoA] 主备聚合器均失败，回退到 v1 程序合并")
        v1_result = merge_analyses(claude_result, gpt_result, gemini_result)
        v1_result["moa_fallback"] = True
        return v1_result

    source_parts = ["moa(claude+gpt)"]
    if gemini_ok:
        source_parts.append("gemini")

    return {
        "merged_features": fused,
        "source": "+".join(source_parts),
        "merge_quality": "moa_full",
        "moa_elapsed": round(elapsed, 1),
    }


def run_grok_remediation(
    grok_gen: AnalysisGenerator,
    fused_features: dict,
    review_scores: dict,
    conversation: str,
    backup_gen: Optional[AnalysisGenerator] = None,
    gemini_gen: Optional[AnalysisGenerator] = None,
    kimi_gen: Optional[AnalysisGenerator] = None,
) -> tuple[dict, int]:
    """
    Grok 补齐循环: 单项 ≤ REMEDIATION_THRESHOLD 的维度定向补齐。
    Fallback 链: Grok(OpenAI-compatible proxy) → Grok(jiuuij) → Gemini → Kimi

    Returns:
        (补齐后的 features, 实际补齐轮次)
    """
    current = fused_features
    total_rounds = 0

    for round_num in range(1, MAX_REMEDIATION_ROUNDS + 1):
        low_dims = {dim: score for dim, score in review_scores.items()
                    if isinstance(score, (int, float)) and score <= REMEDIATION_THRESHOLD}
        if not low_dims:
            break

        # 保存补齐前的完整版本，防止截断覆盖
        pre_remediation = current.copy()
        total_rounds = round_num
        low_dims_detail = "\n".join(
            f"- {dim}: 当前 {score}/10 (需 ≥8)" for dim, score in low_dims.items()
        )

        prompt = REMEDIATION_PROMPT.format(
            low_dims=", ".join(low_dims.keys()),
            low_dims_detail=low_dims_detail,
            fused_analysis=json.dumps(current, ensure_ascii=False, indent=2),
            conversation=conversation[:3000],
        )

        # 主 Grok (OpenAI-compatible proxy) — HTML / 截断检测
        raw = None
        attempt = 0
        while attempt < 4:
            try:
                raw = grok_gen._call_api(prompt)
                if raw and _is_html_error(raw):
                    logger.warning(f"[Remediation R{round_num}] Cloudflare HTML，等待 30s (不计入重试)")
                    raw = None
                    time.sleep(30)
                    continue
                # 检测 thinking 模型截断
                if raw and '</think>' in raw:
                    after_think = raw[raw.index('</think>') + len('</think>'):]
                    if len(after_think.strip()) < 100:
                        logger.warning(f"[Remediation R{round_num}] thinking 截断 ({len(after_think.strip())} chars)，切换备用")
                        raw = None
                        break
                if raw:
                    break
            except Exception as e:
                logger.warning(f"[Remediation R{round_num}] attempt {attempt+1}: {e}")
            attempt += 1
            time.sleep(18)

        # 备用 1: Grok (jiuuij) — 非 thinking 模型
        if not raw and backup_gen is not None:
            logger.info(f"[Remediation R{round_num}] 主线失败，切换到备用 Grok...")
            for att in range(3):
                try:
                    raw = backup_gen._call_api(prompt)
                    if raw and not _is_html_error(raw):
                        break
                    raw = None
                except Exception as e:
                    logger.warning(f"[Remediation R{round_num} Backup] attempt {att+1}: {e}")
                    time.sleep(18)

        # 备用 2: Gemini
        if not raw and gemini_gen is not None:
            logger.info(f"[Remediation R{round_num}] Grok 全线失败，切换到 Gemini...")
            for att in range(3):
                try:
                    raw = gemini_gen._call_api(prompt)
                    if raw and not _is_html_error(raw):
                        break
                    raw = None
                except Exception as e:
                    logger.warning(f"[Remediation R{round_num} Gemini] attempt {att+1}: {e}")
                    time.sleep(15)

        # 备用 3: Kimi (最后手段)
        if not raw and kimi_gen is not None:
            logger.info(f"[Remediation R{round_num}] Gemini 也失败，切换到 Kimi...")
            for att in range(3):
                try:
                    raw = kimi_gen._call_api(prompt)
                    if raw and not _is_html_error(raw):
                        break
                    raw = None
                except Exception as e:
                    logger.warning(f"[Remediation R{round_num} Kimi] attempt {att+1}: {e}")
                    time.sleep(15)

        if not raw:
            logger.warning(f"[Remediation R{round_num}] 空响应，停止补齐")
            break

        text = _strip_thinking_tags(raw)
        updated = _extract_json_robust(text)
        if updated is None:
            logger.warning(f"[Remediation R{round_num}] JSON 解析失败，回滚到补齐前版本")
            current = pre_remediation
            break

        # 检查补齐结果字段数是否合理 (防止截断)
        if len(updated) < len(pre_remediation) * 0.5:
            logger.warning(f"[Remediation R{round_num}] 补齐结果字段不足 ({len(updated)} vs {len(pre_remediation)})，回滚")
            current = pre_remediation
            break

        current = updated

        # 重新审核以检查是否达标
        re_review = run_grok_review(
            grok_gen, conversation, json.dumps(current, ensure_ascii=False),
            backup_gen=backup_gen, kimi_gen=kimi_gen,
        )
        if re_review and re_review.get("scores"):
            review_scores = re_review["scores"]
        else:
            break

    return current, total_rounds


def _merge_string_lists(base: list, extra: list, max_items: int = 4) -> list:
    """合并两个字符串列表，去重保留 top N"""
    if not isinstance(base, list):
        base = [base] if base else []
    if not isinstance(extra, list):
        extra = [extra] if extra else []

    seen = set()
    merged = []
    for item in base + extra:
        s = str(item).strip()
        if s and s not in seen:
            seen.add(s)
            merged.append(item)
        if len(merged) >= max_items:
            break
    return merged


# ── Step 5: Grok 审核 ────────────────────────────────────────
import re


def _strip_thinking_tags(text: str) -> str:
    """剥离 thinking 模型的 <think>...</think> 标签，只保留正文"""
    # 处理 <think>...</think> (贪婪匹配，可能跨行)
    stripped = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
    # 处理未闭合的 <think> (模型输出被截断)
    stripped = re.sub(r'<think>.*', '', stripped, flags=re.DOTALL).strip()
    return stripped or text  # 如果全部被剥离则返回原文


def _extract_json_robust(text: str) -> dict | None:
    """多策略 JSON 提取 — 处理 Grok 各种输出格式"""
    # 策略 1: ```json ... ``` 代码块
    if '```json' in text:
        try:
            json_str = text.split('```json')[1].split('```')[0]
            return json.loads(json_str.strip())
        except (json.JSONDecodeError, IndexError):
            pass

    # 策略 2: ``` ... ``` 普通代码块
    if '```' in text:
        try:
            json_str = text.split('```')[1].split('```')[0]
            return json.loads(json_str.strip())
        except (json.JSONDecodeError, IndexError):
            pass

    # 策略 3: 直接解析整个文本
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass

    # 策略 4: 查找第一个 { 到最后一个 } 的范围
    first_brace = text.find('{')
    last_brace = text.rfind('}')
    if first_brace != -1 and last_brace > first_brace:
        try:
            return json.loads(text[first_brace:last_brace + 1])
        except json.JSONDecodeError:
            pass

    # 策略 5: 用正则找最大的 JSON 对象 (处理截断)
    import re as _re
    candidates = _re.findall(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text)
    for candidate in sorted(candidates, key=len, reverse=True):
        try:
            obj = json.loads(candidate)
            # 至少要有 relationship_status 或 key_issues 才算有效
            if isinstance(obj, dict) and ('relationship_status' in obj or 'key_issues' in obj):
                return obj
        except json.JSONDecodeError:
            continue

    # 策略 6: 按行扫描找关键字段，向上回溯到 {，向下找匹配 }
    _KEY_FIELDS = ('relationship_status', 'key_issues', 'communication_quality')
    lines = text.split('\n')
    for i, line in enumerate(lines):
        if any(f'"{kf}"' in line for kf in _KEY_FIELDS):
            # 向上找第一个含 { 的行
            start_line = i
            for j in range(i, -1, -1):
                if '{' in lines[j]:
                    start_line = j
                    break
            # 向下找最后一个含 } 的行
            end_line = i
            for j in range(i, len(lines)):
                if '}' in lines[j]:
                    end_line = j
            block = '\n'.join(lines[start_line:end_line + 1])
            # 提取从第一个 { 到最后一个 }
            fb = block.find('{')
            lb = block.rfind('}')
            if fb != -1 and lb > fb:
                try:
                    return json.loads(block[fb:lb + 1])
                except json.JSONDecodeError:
                    pass
            break  # 只尝试第一次找到关键字段的位置

    # 策略 7: 截断 JSON 自动补全（缺失的 "、] 和 }）
    first_brace2 = text.find('{')
    if first_brace2 != -1:
        fragment = text[first_brace2:]
        open_braces = fragment.count('{') - fragment.count('}')
        open_brackets = fragment.count('[') - fragment.count(']')
        if open_braces > 0 or open_brackets > 0:
            # 方案A: 截断到最后一个完整的 key-value 对
            last_comma = fragment.rfind(',')
            last_close = max(fragment.rfind('}'), fragment.rfind(']'))
            if last_comma > 0 and last_comma > last_close:
                trimmed = fragment[:last_comma]
                # 重新计算
                ob = trimmed.count('{') - trimmed.count('}')
                obrk = trimmed.count('[') - trimmed.count(']')
                repair = trimmed + ']' * max(0, obrk) + '}' * max(0, ob)
                try:
                    obj = json.loads(repair)
                    if isinstance(obj, dict) and len(obj) >= 3:
                        return obj
                except json.JSONDecodeError:
                    pass
            # 方案B: 闭合未完成的字符串，然后补全括号
            # 检测未闭合引号（简单计数，不考虑转义——足够实用）
            in_string = False
            for ch in fragment:
                if ch == '"':
                    in_string = not in_string
            suffix = ""
            if in_string:
                suffix += '"'
            ob2 = fragment.count('{') - fragment.count('}')
            obrk2 = fragment.count('[') - fragment.count(']')
            suffix += ']' * max(0, obrk2) + '}' * max(0, ob2)
            try:
                obj = json.loads(fragment + suffix)
                if isinstance(obj, dict) and len(obj) >= 3:
                    return obj
            except json.JSONDecodeError:
                pass

    return None


def _try_repair_review_json(raw: str) -> dict | None:
    """尝试从截断/残缺的 JSON 中提取审核关键字段 (scores, verdict 等)"""
    text = raw
    if '```json' in text:
        text = text.split('```json')[1]
    elif '```' in text:
        text = text.split('```')[1]

    # 提取 scores 对象
    scores_match = re.search(r'"scores"\s*:\s*\{([^}]+)\}', text)
    if not scores_match:
        return None

    try:
        scores_str = '{' + scores_match.group(1) + '}'
        scores = json.loads(scores_str)
    except json.JSONDecodeError:
        return None

    # 提取 total_score
    total_match = re.search(r'"total_score"\s*:\s*(\d+)', text)
    total_score = int(total_match.group(1)) if total_match else sum(scores.values())

    # 提取 verdict
    verdict_match = re.search(r'"verdict"\s*:\s*"([^"]+)"', text)
    if verdict_match:
        verdict = verdict_match.group(1)
    else:
        # 兼容 _03b 的 passed 字段
        passed_match = re.search(r'"passed"\s*:\s*(true|false)', text)
        if passed_match:
            verdict = 'pass' if passed_match.group(1) == 'true' else 'needs_revision'
        else:
            verdict = 'pass' if total_score >= 36 else 'needs_revision'

    # 提取 issues
    issues = []
    issues_match = re.search(r'"issues"\s*:\s*\[(.*)', text, re.DOTALL)
    if issues_match:
        for m in re.finditer(r'\{[^{}]+\}', issues_match.group(1)):
            try:
                issue = json.loads(m.group())
                issues.append(issue)
            except json.JSONDecodeError:
                continue

    # 提取 suggestions
    suggestions = []
    sug_match = re.search(r'"suggestions"\s*:\s*\[(.*?)\]', text, re.DOTALL)
    if sug_match:
        for m in re.finditer(r'"([^"]+)"', sug_match.group(1)):
            suggestions.append(m.group(1))

    return {
        'scores': scores,
        'total_score': total_score,
        'verdict': verdict,
        'issues': issues,
        'suggestions': suggestions,
        'repaired': True,
        'skipped': False,
        'success': True,
    }


REVIEW_PROMPT_TEMPLATE = """你是一位资深的关系心理学审核专家。请审核以下由 AI 生成的关系分析，给出评分和修改建议。

【审核标准】
1. 准确性 (1-10): 分析是否准确反映对话内容？
2. 深度 (1-10): 是否有深层心理洞察？
3. 多模态 (1-10): 是否正确解读了语音/表情/图片信号？
4. 结构 (1-10): JSON 字段是否齐全、格式是否规范？
5. 流畅度 (1-10): 中文表达是否自然流畅？

【对话原文】
{conversation}

【AI 分析结果】
{analysis}

请以 JSON 格式输出审核结果:
{{
  "scores": {{
    "accuracy": <1-10>,
    "depth": <1-10>,
    "multimodal": <1-10>,
    "structure": <1-10>,
    "fluency": <1-10>
  }},
  "total_score": <5-50>,
  "issues": ["问题1", "问题2"],
  "suggestions": ["建议1", "建议2"],
  "verdict": "pass" | "needs_revision" | "fail"
}}"""


def run_grok_review(
    gen: AnalysisGenerator,
    conversation: str,
    analysis_text: str,
    max_retries: int = 5,
    retry_delay: float = 18.0,
    backup_gen: Optional[AnalysisGenerator] = None,
    kimi_gen: Optional[AnalysisGenerator] = None,
) -> Optional[dict]:
    """审核 (3 级 fallback: gen → backup_gen → kimi_gen)
    架构 v2: Kimi 主审 → Gemini 备 → Grok-jiuuij 兜底"""
    prompt = REVIEW_PROMPT_TEMPLATE.format(
        conversation=conversation[:3000],
        analysis=analysis_text[:4000],
    )
    start = time.time()

    # 主 Grok (OpenAI-compatible proxy) — HTML / 截断检测
    raw = None
    attempt = 0
    while attempt < max_retries:
        try:
            raw = gen._call_api(prompt)
            if raw and _is_html_error(raw):
                logger.warning(f"[Grok 审核] Cloudflare HTML，等待 30s (不计入重试)")
                raw = None
                time.sleep(30)
                continue
            # 检测 thinking 模型截断: <think> 后实际内容不足
            if raw and '</think>' in raw:
                after_think = raw[raw.index('</think>') + len('</think>'):]
                if len(after_think.strip()) < 80:
                    logger.warning(f"[Grok 审核] thinking 模型输出截断 ({len(after_think.strip())} chars)，切换备用")
                    raw = None
                    break  # 直接跳到备用，不再重试主线
            if raw:
                break
        except Exception as e:
            logger.warning(f"[Grok 审核] API 异常 (attempt {attempt+1}): {e}")
        attempt += 1
        if attempt < max_retries:
            time.sleep(retry_delay)

    # 备用 1: Grok (jiuuij) — 非 thinking 模型，不会截断
    if not raw and backup_gen is not None:
        logger.info(f"[Grok 审核] 主线失败，切换到备用 {backup_gen.model}...")
        for att in range(1, 4):
            try:
                raw = backup_gen._call_api(prompt)
                if raw and not _is_html_error(raw):
                    break
                raw = None
            except Exception as e:
                logger.warning(f"[Grok 审核 Backup] attempt {att}: {e}")
            if att < 3:
                time.sleep(retry_delay)

    # 备用 2: Kimi
    if not raw and kimi_gen is not None:
        logger.info(f"[Grok 审核] Grok 全线失败，切换到 Kimi {kimi_gen.model}...")
        for att in range(1, 4):
            try:
                raw = kimi_gen._call_api(prompt)
                if raw and not _is_html_error(raw):
                    break
                raw = None
            except Exception as e:
                logger.warning(f"[Grok 审核 Kimi] attempt {att}: {e}")
            if att < 3:
                time.sleep(15)

    elapsed = time.time() - start

    if not raw:
        return {"success": False, "skipped": False, "elapsed": elapsed, "error": "空响应"}

    # 剥离 thinking 模型的 <think> 标签
    text = _strip_thinking_tags(raw)

    # 提取 JSON 块 — 多策略
    review = None

    # 策略 1: 标准代码块提取
    try:
        json_str = text
        if '```json' in json_str:
            json_str = json_str.split('```json')[1].split('```')[0]
        elif '```' in json_str:
            json_str = json_str.split('```')[1].split('```')[0]
        parsed = json.loads(json_str.strip())
        if isinstance(parsed, dict) and parsed.get("scores") and isinstance(parsed["scores"], dict) and len(parsed["scores"]) >= 3:
            review = parsed
    except (json.JSONDecodeError, IndexError):
        pass

    # 策略 2: _extract_json_robust (处理截断、嵌套等)
    if review is None:
        parsed = _extract_json_robust(text)
        if parsed and isinstance(parsed, dict) and parsed.get("scores") and isinstance(parsed["scores"], dict) and len(parsed["scores"]) >= 3:
            review = parsed

    # 策略 3: 正则逐字段提取
    if review is None:
        review = _try_repair_review_json(text)

    # 全部失败
    if review is None:
        return {
            "success": True,
            "skipped": False,
            "elapsed": elapsed,
            "raw_response": raw[:2000],
            "scores": {},
            "verdict": "parse_error",
        }

    # 确保 verdict 字段存在 (Grok 未返回 verdict 时自动推导)
    if not review.get("verdict") or review["verdict"] == "parse_error":
        total = review.get("total_score", 0)
        if not total and review.get("scores"):
            total = sum(v for v in review["scores"].values() if isinstance(v, (int, float)))
            review["total_score"] = total
        review["verdict"] = "pass" if total >= 36 else "needs_revision" if total >= 20 else "fail"

    # 分数覆盖: Grok 审核 verdict 偏严，总分 ≥44 强制判 pass
    total = review.get("total_score", 0)
    if not total and review.get("scores"):
        total = sum(v for v in review["scores"].values() if isinstance(v, (int, float)))
        review["total_score"] = total
    if total >= 44 and review.get("verdict") != "pass":
        logger.debug(f"[审核覆盖] 总分 {total} ≥44，verdict {review['verdict']} → pass")
        review["verdict"] = "pass"

    review["elapsed"] = elapsed
    review["success"] = True
    review["skipped"] = False
    return review


# ── 主流程 ────────────────────────────────────────────────────
def process_single_chunk(
    chunk: dict,
    agent_type: str,
    generators: dict,
    skip_gemini_non_multimodal: bool = True,
    skip_review: bool = False,
    use_moa: bool = False,
    claude_backup: Optional[AnalysisGenerator] = None,
    moa_backup: Optional[AnalysisGenerator] = None,
    grok_backup_gen: Optional[AnalysisGenerator] = None,
) -> dict:
    """
    处理单个 chunk 的完整融合流程。

    Args:
        chunk: 对话片段
        agent_type: neutral / supportive / psychoanalytic
        generators: {"claude": gen, "gpt": gen, "gemini": gen, "grok": gen}
        skip_gemini_non_multimodal: 非多模态 chunk 跳过 Gemini
        skip_review: 跳过 Grok 审核 (用于快速测试)
        use_moa: True=v2 MoA 有机融合, False=v1 程序合并
        claude_backup: Claude 备用 generator (backup provider)
        moa_backup: MoA 备用聚合器 (Kimi)
        grok_backup_gen: Grok 备用 (backup provider grok-4.1)

    Returns:
        融合结果 dict
    """
    chunk_id = chunk.get("chunk_id", "unknown")
    conversation = chunk.get("conversation_text", "")
    is_mm = _is_multimodal(conversation)

    # Step 1-3: 并行独立分析
    futures = {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures["claude"] = pool.submit(
            _run_step_analysis, generators["claude"], conversation, agent_type, "claude"
        )
        futures["gpt"] = pool.submit(
            _run_step_analysis, generators["gpt"], conversation, agent_type, "gpt"
        )
        if generators.get("gemini") and (is_mm or not skip_gemini_non_multimodal):
            futures["gemini"] = pool.submit(
                _run_step_analysis, generators["gemini"], conversation, agent_type, "gemini"
            )

    claude_result = futures["claude"].result()
    gpt_result = futures["gpt"].result()
    gemini_result = futures.get("gemini", None)
    if gemini_result is not None:
        gemini_result = gemini_result.result()

    # Claude 备用: 如果主 Claude 失败且有备用，自动重试
    if claude_backup and (not claude_result or not claude_result.get("success")):
        logger.info(f"[{chunk_id}] Claude 主线失败，切换备用 ({claude_backup.model})...")
        claude_result = _run_step_analysis(claude_backup, conversation, agent_type, "claude_backup")
        if claude_result and claude_result.get("success"):
            claude_result["step"] = "claude"  # 统一标识
            claude_result["model"] = f"{claude_backup.model} (backup)"

    # Step 4: 融合
    if use_moa:
        merged = moa_merge_analyses(
            generators["grok"], claude_result, gpt_result, gemini_result,
            conversation, backup_gen=moa_backup, grok_backup_gen=grok_backup_gen,
        )
    else:
        merged = merge_analyses(claude_result, gpt_result, gemini_result)

    # Step 5: 审核 — Kimi 主审 → Gemini 备 → Grok-jiuuij 兜底
    review = None
    if not skip_review and merged["merge_quality"] != "failed":
        analysis_text = json.dumps(merged["merged_features"], ensure_ascii=False)
        _review_gen = moa_backup or generators["grok"]  # Kimi; 若不可用回退 Grok
        review = run_grok_review(
            _review_gen, conversation, analysis_text,
            backup_gen=generators.get("gemini"),
            kimi_gen=grok_backup_gen,
        )

    # Step 5b: 补齐 — Gemini 主补 → Kimi 备 → Grok-jiuuij 兜底
    remediation_rounds = 0
    if use_moa and review and review.get("scores") and merged["merge_quality"] != "failed":
        low_dims = {d: s for d, s in review["scores"].items()
                    if isinstance(s, (int, float)) and s <= REMEDIATION_THRESHOLD}
        if low_dims:
            logger.info(f"[{chunk_id}] 低分维度: {low_dims}, 启动补齐...")
            _rem_primary = generators.get("gemini") or moa_backup or generators["grok"]
            _rem_backup = moa_backup if generators.get("gemini") else grok_backup_gen
            merged["merged_features"], remediation_rounds = run_grok_remediation(
                _rem_primary, merged["merged_features"], review["scores"], conversation,
                backup_gen=_rem_backup,
                gemini_gen=grok_backup_gen,
                kimi_gen=None,
            )
            # 补齐后重新审核 (Kimi → Gemini → Grok-jiuuij)
            if remediation_rounds > 0:
                re_review = run_grok_review(
                    _review_gen, conversation,
                    json.dumps(merged["merged_features"], ensure_ascii=False),
                    backup_gen=generators.get("gemini"),
                    kimi_gen=grok_backup_gen,
                )
                if re_review and re_review.get("success"):
                    review = re_review

    # Step 6: 组装最终输出
    result = {
        "chunk_id": chunk_id,
        "agent_type": agent_type,
        "conversation": conversation,
        "is_multimodal": is_mm,
        "analysis_features": merged["merged_features"],
        "merge_source": merged["source"],
        "merge_quality": merged["merge_quality"],
        "step_details": {
            "claude": _summarize_step(claude_result),
            "gpt": _summarize_step(gpt_result),
            "gemini": _summarize_step(gemini_result) if gemini_result else {"skipped": True},
            "review": review if review else {"skipped": True, "reason": "skip_flag" if skip_review else "no_analysis"},
        },
        "timestamp": datetime.now().isoformat(),
    }

    # MoA: 保留原始独立分析供审核
    if use_moa:
        if claude_result and claude_result.get("success"):
            result["claude_raw"] = claude_result["features"]
        if gpt_result and gpt_result.get("success"):
            result["gpt_raw"] = gpt_result["features"]
        result["moa_elapsed"] = merged.get("moa_elapsed", 0)
        result["remediation_rounds"] = remediation_rounds
        if merged.get("moa_fallback"):
            result["moa_fallback"] = True

    # 审核评分摘要
    if review and review.get("success") and review.get("scores"):
        result["review_scores"] = review["scores"]
        result["review_verdict"] = review.get("verdict", "unknown")
        result["review_total"] = review.get("total_score", 0)

    return result


def _process_chunk_with_rotation(
    chunk: dict,
    agent_type: str,
    generators: dict,
    rotators: dict,
    skip_gemini_non_multimodal: bool = True,
    skip_review: bool = False,
    use_moa: bool = False,
    claude_backup: Optional[AnalysisGenerator] = None,
    moa_backup: Optional[AnalysisGenerator] = None,
    grok_backup_gen: Optional[AnalysisGenerator] = None,
) -> dict:
    """
    带 key 轮换的 chunk 处理。
    在调用 process_single_chunk 之前，从 rotator 获取 key 并 swap。
    """
    # 为每个 agent 获取下一个可用 key 并切换
    acquired_keys = {}
    for agent_name in ("claude", "gpt", "grok"):
        if agent_name in rotators and generators.get(agent_name):
            key = rotators[agent_name].acquire()
            generators[agent_name].swap_api_key(key)
            acquired_keys[agent_name] = key
    if "gemini" in rotators and generators.get("gemini"):
        key = rotators["gemini"].acquire()
        generators["gemini"].swap_api_key(key)
        acquired_keys["gemini"] = key

    result = process_single_chunk(
        chunk, agent_type, generators,
        skip_gemini_non_multimodal=skip_gemini_non_multimodal,
        skip_review=skip_review,
        use_moa=use_moa,
        claude_backup=claude_backup,
        moa_backup=moa_backup,
        grok_backup_gen=grok_backup_gen,
    )

    # 根据结果标记 key 成功/失败
    step_details = result.get("step_details", {})
    for agent_name, key in acquired_keys.items():
        step = step_details.get(agent_name, {})
        if step.get("success"):
            rotators[agent_name].mark_success(key)
        elif not step.get("skipped", True):
            rotators[agent_name].mark_failed(key)

    return result


def _summarize_step(step_result: Optional[dict]) -> dict:
    """精简步骤结果 (不保存完整 features，节省空间)"""
    if not step_result:
        return {"success": False, "error": "not_run"}
    return {
        "success": step_result.get("success", False),
        "elapsed": round(step_result.get("elapsed", 0), 1),
        "model": step_result.get("model", ""),
        "repair_attempts": step_result.get("repair_attempts", 0),
        "error": step_result.get("error", ""),
    }


def load_chunks(path: str) -> list[dict]:
    """加载 JSONL"""
    chunks = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                chunks.append(json.loads(line))
    return chunks


def scan_completed(output_path: str) -> set:
    """扫描已完成的 chunk_id"""
    completed = set()
    p = Path(output_path)
    if not p.exists():
        return completed
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                cid = data.get("chunk_id", "")
                if cid:
                    completed.add(cid)
            except json.JSONDecodeError:
                continue
    return completed


def main():
    parser = argparse.ArgumentParser(description="多专家并行融合流水线")
    parser.add_argument("--agent-type", type=str, default="neutral",
                        choices=["neutral", "supportive", "psychoanalytic"],
                        help="Agent 类型")
    parser.add_argument("--input", type=str, default=None,
                        help="输入 chunks 文件")
    parser.add_argument("--output", type=str, default=None,
                        help="输出文件路径")
    parser.add_argument("--limit", type=int, default=None,
                        help="限制处理数量（用于测试）")
    parser.add_argument("--no-resume", action="store_true",
                        help="禁用断点续跑")
    parser.add_argument("--skip-review", action="store_true",
                        help="跳过 Grok 审核 (快速测试)")
    parser.add_argument("--skip-gemini", action="store_true",
                        help="跳过 Gemini (即使多模态)")
    parser.add_argument("--delay", type=float, default=2.0,
                        help="chunk 间隔秒数 (避免 RPM 超限)")
    parser.add_argument("--moa", action="store_true",
                        help="启用 MoA v2 有机融合 (Grok Aggregator + 补齐循环)")
    parser.add_argument("--workers", type=int, default=1,
                        help="并发 Worker 数 (需要 --key-pool, 默认 1=串行)")
    parser.add_argument("--key-pool", type=str, default=None,
                        help="key_pool.yaml 路径 (多 key 轮换, 默认 local_secrets/key_pool.yaml)")
    parser.add_argument("--max-rpm", type=int, default=16,
                        help="账户总 RPM 硬限制 (默认 16, OpenAI-compatible proxy 总限 20 留余量+前端)")
    parser.add_argument("--grok-backend", type=str, default="grok",
                        choices=["grok", "kimi"],
                        help="MoA 聚合器后端 (grok 或 kimi) — grok-thinking 不稳定时可切换")
    parser.add_argument("--grok-model", type=str, default=None,
                        help="MoA 聚合器模型名覆盖 (例如 grok-4 / grok-4.1-thinking / moonshotai/Kimi-K2-Instruct)")
    parser.add_argument("--pipeline", action="store_true",
                        help="启用 CPU 流水线式并行 (S1 与 S2-S4 并行, 强制启用 --moa)")
    parser.add_argument("--max-s1", type=int, default=2,
                        help="流水线模式: S1 最大并发数 (默认 2)")
    parser.add_argument("--max-grok", type=int, default=3,
                        help="流水线模式: Grok 最大并发数 (默认 3)")
    parser.add_argument("--no-rich", action="store_true",
                        help="流水线模式: 禁用 rich 可视化 (用纯文本输出)")

    args = parser.parse_args()

    # Pipeline 模式强制启用 MoA
    if args.pipeline:
        args.moa = True

    # MoA 模式默认用 grok-4 普通 (thinking 模型 JSON 不稳定)
    if args.moa and args.grok_model is None:
        args.grok_model = "grok-4"

    workspace = PROJECT_ROOT
    input_path = args.input or str(workspace / "advisor_out" / "chunks" / "conversation_chunks.jsonl")
    # MoA 模式输出到不同文件以支持 v1/v2 对比
    suffix = "_moa" if args.moa else ""
    output_path = args.output or str(
        workspace / "advisor_out" / "analysis" / f"fused_analysis_{args.agent_type}{suffix}.jsonl"
    )

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    # 加载 chunks
    chunks = load_chunks(input_path)
    print(f"加载了 {len(chunks)} 个对话片段")

    if args.limit:
        chunks = chunks[: args.limit]
        print(f"限制处理 {args.limit} 个片段")

    # 断点续跑
    completed_ids = set()
    if not args.no_resume:
        completed_ids = scan_completed(output_path)
        if completed_ids:
            print(f"断点续跑：已完成 {len(completed_ids)}/{len(chunks)} 条")

    pending = [c for c in chunks if c.get("chunk_id", "") not in completed_ids]
    if not pending:
        print("所有 chunks 已处理完毕")
        return

    print(f"待处理: {len(pending)} 个片段")
    print()

    # ── 初始化 generators ──────────────────────────────────────
    use_key_pool = args.workers > 1 or args.key_pool or args.pipeline
    pool_config = None
    rotators = {}

    if use_key_pool:
        _init_key_rotator()
        pool_path = args.key_pool or str(workspace / "local_secrets" / "key_pool.yaml")
        print(f"加载 key pool: {pool_path}")
        pool_config = _load_key_pool(pool_path)
        rotators, global_limiter = _create_rotators_from_pool(pool_config, max_rpm=args.max_rpm)
        for name, rot in rotators.items():
            s = rot.get_stats()
            print(f"  {name}: {s['total_keys']} keys")
        print(f"  全局 RPM 限制: ≤{args.max_rpm} (所有 key/model 合计)")

    # 多 Worker 模式：每个 Worker 需要独立的 generator 集合
    num_workers = max(1, args.workers)
    worker_generators = []

    print("初始化模型连接...")
    for w in range(num_workers):
        if pool_config:
            gens = _create_generators_from_pool(
                pool_config,
                rotators,
                skip_gemini=args.skip_gemini,
                grok_model=args.grok_model,
                grok_backend=args.grok_backend,
            )
        else:
            gens = {
                "claude": _create_generator("claude"),
                "gpt": _create_generator("gpt"),
                "grok": _create_generator(
                    "grok",
                    model=args.grok_model,
                    backend=args.grok_backend,
                ),
            }
            if not args.skip_gemini:
                gens["gemini"] = _create_generator("gemini")
            else:
                gens["gemini"] = None
        worker_generators.append(gens)

    # ── 备用 generators (优先从 key_pool.yaml 读取, 回退 env) ────────
    # Claude 备用 (backup provider): OpenAI-compatible proxy 不稳定时自动 fallback
    claude_backup = None
    cb_cfg = pool_config.get("claude_backup", {}) if pool_config else {}
    cb_keys = cb_cfg.get("keys", [])
    if cb_keys:
        claude_backup = _create_generator(
            "claude",
            api_key=cb_keys[0],
            base_url=cb_cfg.get("base_url"),
            model=cb_cfg.get("model"),
        )
        print(f"  Claude 备用: {claude_backup.model} ({cb_cfg.get('base_url', '?')})")
    else:
        backup_key = os.environ.get("ANTHROPIC_BACKUP_API_KEY")
        if backup_key:
            claude_backup = _create_generator(
                "claude",
                api_key=backup_key,
                base_url=os.environ.get("ANTHROPIC_BACKUP_BASE_URL"),
                model=os.environ.get("ANTHROPIC_BACKUP_MODEL"),
            )
            print(f"  Claude 备用: {claude_backup.model} ({os.environ.get('ANTHROPIC_BACKUP_BASE_URL', '?')})")

    # Kimi 备用 (MoA 聚合器): grok MoA 失败时自动 fallback
    moa_backup = None
    if args.moa:
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
            print(f"  MoA 备用: {moa_backup.model} @ {moa_backup.base_url}")
        except Exception as e:
            logger.warning(f"Kimi 备用创建失败 (非致命): {e}")

    # Grok 备用 (backup provider): OpenAI-compatible proxy Grok 失败时自动 fallback
    grok_backup_gen = None
    grok_backup_cfg = pool_config.get("grok_backup", {}) if pool_config else {}
    grok_backup_keys = grok_backup_cfg.get("keys", [])
    if grok_backup_keys:
        try:
            grok_backup_gen = _create_generator(
                "grok_backup",
                api_key=grok_backup_keys[0],
                base_url=grok_backup_cfg.get("base_url"),
                model=grok_backup_cfg.get("model", "grok-4.1"),
            )
            print(f"  Grok 备用: {grok_backup_gen.model} ({grok_backup_cfg.get('base_url', '?')})")
        except Exception as e:
            logger.warning(f"Grok 备用创建失败 (非致命): {e}")

    # 打印配置信息（使用第一个 worker 的 generators）
    g0 = worker_generators[0]
    print(f"  Claude: {g0['claude'].model}")
    print(f"  GPT:    {g0['gpt'].model} (ResponseAPI={g0['gpt']._use_response_api})")
    if g0.get("gemini"):
        print(f"  Gemini: {g0['gemini'].model}")
    print(f"  Grok:   {g0['grok'].model}")
    print(f"  模式:   {'MoA v2 有机融合' if args.moa else 'v1 程序合并'}")
    if args.moa:
        print(f"  补齐阈值: 单项 ≤{REMEDIATION_THRESHOLD} → 补齐到 ≥8 (最多 {MAX_REMEDIATION_ROUNDS} 轮)")
    if num_workers > 1:
        print(f"  Workers: {num_workers} (并发模式, RPM≤{args.max_rpm}/key)")
    print()

    # ── Pipeline 模式: asyncio 四级流水线 ──────────────────────
    if args.pipeline:
        import asyncio
        from scripts.advisor.pipeline_executor import PipelineExecutor

        # 创建 Claude 降级 generator (sonnet-4.5-think)
        claude_degraded_gen = None
        claude_cfg = pool_config.get("claude", {}) if pool_config else {}
        degraded_model = claude_cfg.get("degraded_model", "claude-sonnet-4.5-think")
        if degraded_model:
            try:
                claude_degraded_gen = _create_generator(
                    "claude",
                    model=degraded_model,
                )
                print(f"  Claude 降级: {degraded_model} (Opus 失败时自动切换)")
            except Exception as e:
                logger.warning(f"Claude 降级 generator 创建失败: {e}")

        executor = PipelineExecutor(
            generators=g0,
            agent_type=args.agent_type,
            claude_backup=claude_backup,
            moa_backup=moa_backup,
            grok_backup_gen=grok_backup_gen,
            skip_review=args.skip_review,
            skip_gemini_non_multimodal=True,
            max_concurrent_s1=args.max_s1,
            max_concurrent_grok=args.max_grok,
            use_rich=not args.no_rich,
            claude_degradation_to_dual=True,
            claude_degraded_gen=claude_degraded_gen,
        )

        print(f"  🔧 流水线模式: S1×{args.max_s1} Grok×{args.max_grok}")
        print()

        results = asyncio.run(executor.run(pending, output_path))

        print(f"\n  输出文件: {output_path}")
        return

    # 统计
    stats = {
        "success": 0, "failed": 0,
        "full_fusion": 0, "partial_fusion": 0, "degraded": 0,
        "moa_full": 0, "moa_fallback": 0,
        "multimodal_chunks": 0,
        "review_pass": 0, "review_needs_revision": 0, "review_fail": 0,
        "remediation_triggered": 0, "remediation_total_rounds": 0,
        "total_time": 0,
    }
    stats_lock = threading.Lock()
    file_lock = threading.Lock()

    def _update_stats_and_write(result, f_out, chunk_idx, total, is_mm):
        """线程安全地更新统计和写入结果"""
        mq = result.get("merge_quality", "failed")

        with stats_lock:
            if mq == "moa_full":
                stats["moa_full"] += 1; stats["success"] += 1
            elif mq == "full":
                stats["full_fusion"] += 1; stats["success"] += 1
            elif mq == "partial":
                stats["partial_fusion"] += 1; stats["success"] += 1
            elif mq == "degraded":
                stats["degraded"] += 1; stats["success"] += 1
            else:
                stats["failed"] += 1

            if result.get("moa_fallback"):
                stats["moa_fallback"] += 1
            rem_rounds = result.get("remediation_rounds", 0)
            if rem_rounds > 0:
                stats["remediation_triggered"] += 1
                stats["remediation_total_rounds"] += rem_rounds
            if is_mm:
                stats["multimodal_chunks"] += 1

            verdict = result.get("review_verdict", "")
            if verdict == "pass": stats["review_pass"] += 1
            elif verdict == "needs_revision": stats["review_needs_revision"] += 1
            elif verdict == "fail": stats["review_fail"] += 1

        # 打印摘要
        step_d = result.get("step_details", {})
        c_ok = "✅" if step_d.get("claude", {}).get("success") else "❌"
        g_ok = "✅" if step_d.get("gpt", {}).get("success") else "❌"
        gem_status = "⏭"
        if not step_d.get("gemini", {}).get("skipped", True):
            gem_status = "✅" if step_d["gemini"].get("success") else "❌"
        rev_status = "⏭"
        review_d = step_d.get("review", {})
        if review_d.get("success") or (not review_d.get("skipped", True)):
            rev_status = result.get("review_verdict", "") or review_d.get("verdict", "?")

        c_time = step_d.get("claude", {}).get("elapsed", 0)
        g_time = step_d.get("gpt", {}).get("elapsed", 0)
        moa_t = result.get("moa_elapsed", 0)
        rem_r = result.get("remediation_rounds", 0)

        moa_str = f" MoA({moa_t:.0f}s)" if moa_t else ""
        rem_str = f" Rem×{rem_r}" if rem_r else ""
        fb_str = " [FB]" if result.get("moa_fallback") else ""

        print(f"[{chunk_idx}/{total}] {result.get('chunk_id','')} "
              f"C{c_ok}({c_time:.0f}s) G{g_ok}({g_time:.0f}s) "
              f"Gem{gem_status}{moa_str} Rev:{rev_status}{rem_str}{fb_str} "
              f"[{mq}]")

        # 线程安全写入
        with file_lock:
            f_out.write(json.dumps(result, ensure_ascii=False) + "\n")
            f_out.flush()

    # ── 处理循环 ──────────────────────────────────────────────
    with open(output_path, "a", encoding="utf-8") as f:
        if num_workers <= 1:
            # ── 串行模式 (向后兼容) ──
            generators = worker_generators[0]
            for i, chunk in enumerate(pending):
                chunk_id = chunk.get("chunk_id", "")
                chunk_type = chunk.get("chunk_type", "normal")
                is_mm = _is_multimodal(chunk.get("conversation_text", ""))

                print(f"[{i+1}/{len(pending)}] {chunk_id} ({chunk_type}"
                      f"{', 多模态' if is_mm else ''})...", end=" ", flush=True)

                start = time.time()

                if rotators:
                    result = _process_chunk_with_rotation(
                        chunk, args.agent_type, generators, rotators,
                        skip_gemini_non_multimodal=True,
                        skip_review=args.skip_review,
                        use_moa=args.moa,
                        claude_backup=claude_backup,
                        moa_backup=moa_backup,
                        grok_backup_gen=grok_backup_gen,
                    )
                else:
                    result = process_single_chunk(
                        chunk, args.agent_type, generators,
                        skip_gemini_non_multimodal=True,
                        skip_review=args.skip_review,
                        use_moa=args.moa,
                        claude_backup=claude_backup,
                        moa_backup=moa_backup,
                        grok_backup_gen=grok_backup_gen,
                    )

                elapsed = time.time() - start
                with stats_lock:
                    stats["total_time"] += elapsed

                _update_stats_and_write(result, f, i + 1, len(pending), is_mm)

                if i < len(pending) - 1:
                    time.sleep(args.delay)
        else:
            # ── 多 Worker 并发模式 ──
            from queue import Queue
            chunk_queue = Queue()
            for i, chunk in enumerate(pending):
                chunk_queue.put((i, chunk))

            def worker_fn(worker_id: int):
                gens = worker_generators[worker_id]
                while True:
                    try:
                        idx, chunk = chunk_queue.get_nowait()
                    except Exception:
                        break

                    start = time.time()
                    result = _process_chunk_with_rotation(
                        chunk, args.agent_type, gens, rotators,
                        skip_gemini_non_multimodal=True,
                        skip_review=args.skip_review,
                        use_moa=args.moa,
                        claude_backup=claude_backup,
                        moa_backup=moa_backup,
                        grok_backup_gen=grok_backup_gen,
                    )
                    elapsed = time.time() - start
                    with stats_lock:
                        stats["total_time"] += elapsed

                    is_mm = _is_multimodal(chunk.get("conversation_text", ""))
                    _update_stats_and_write(result, f, idx + 1, len(pending), is_mm)

            threads = []
            for w in range(num_workers):
                t = threading.Thread(target=worker_fn, args=(w,), daemon=True)
                t.start()
                threads.append(t)
            for t in threads:
                t.join()

            # 打印 rotator 最终状态
            for name, rot in rotators.items():
                s = rot.get_stats()
                if s["blacklisted"] > 0 or s["emergency_active"]:
                    print(f"  ⚠️ {name}: {s['blacklisted']} blacklisted, emergency={'ON' if s['emergency_active'] else 'OFF'}")

    # 最终统计
    total = len(completed_ids) + stats["success"] + stats["failed"]
    print()
    print("=" * 60)
    print("融合流水线统计:")
    print(f"  总处理: {stats['success'] + stats['failed']} (本次) / {total} (含续跑)")
    print(f"  成功: {stats['success']}  失败: {stats['failed']}")
    if args.moa:
        print(f"  MoA融合: {stats['moa_full']}  MoA回退: {stats['moa_fallback']}  部分融合: {stats['partial_fusion']}")
        print(f"  补齐触发: {stats['remediation_triggered']}  总补齐轮次: {stats['remediation_total_rounds']}")
    else:
        print(f"  完整融合: {stats['full_fusion']}  部分融合: {stats['partial_fusion']}  降级: {stats['degraded']}")
    print(f"  多模态: {stats['multimodal_chunks']}")
    if not args.skip_review:
        print(f"  审核通过: {stats['review_pass']}  需修改: {stats['review_needs_revision']}  不合格: {stats['review_fail']}")
    print(f"  总耗时: {stats['total_time']:.0f}s ({stats['total_time']/60:.1f}min)")
    if stats["success"] + stats["failed"] > 0:
        avg = stats["total_time"] / (stats["success"] + stats["failed"])
        print(f"  平均/chunk: {avg:.1f}s")
    print(f"  输出文件: {output_path}")
    print("=" * 60)


def _sigint_handler(sig, frame):
    """Ctrl+C 立即退出 (绕过 asyncio/ThreadPool 信号屏蔽)"""
    print("\n\n⚠️  收到中断信号，强制退出... (已完成的 chunk 已保存)")
    os._exit(1)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, _sigint_handler)
    signal.signal(signal.SIGTERM, _sigint_handler)
    main()
