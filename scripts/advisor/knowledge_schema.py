#!/usr/bin/env python3
"""
知识中心 FAQ 条目 Schema v2 + 类目 Taxonomy（WS-A）

功能：
- 定义知识库 FAQ 条目的 Pydantic 校验模型（v2，向后兼容 v1）
- 定义类目 taxonomy（domain → category）与各枚举（证据强度/干预或透镜/风险级别/审核状态）
- 提供 CLI 校验器：递归校验 advisor_out/knowledge/ 下所有 .jsonl 条目

设计依据：
- plan_v5/Claude-知识中心全阶段设计与执行清单.md §WS-A
- 决策 D2（教育/反思级）：刻意不引入 GRADE/医疗分级等医疗级元数据；
  evidence_tier 仅为"诚实标签"，非医疗声明

v1 → v2 字段变化（生产条目需通过迁移脚本回填后再校验）：
- 新增必填：id / evidence_tier / intervention_or_lens
- 新增带默认值：risk_level / related / evidence_note / review_status / reviewed_by / review_date
- 沿用：question / answer / category / keywords / source / license

用法：
    # 校验全部知识库
    conda run -n wechatDHA python -m scripts.advisor.knowledge_schema
    # 校验指定目录
    conda run -n wechatDHA python -m scripts.advisor.knowledge_schema --dir advisor_out/knowledge

依赖：pydantic（仓库已用于 schemas.py / schema_validator.py）

作者：Claude (Opus 4.8)
创建于：2026-06-19
"""
from __future__ import annotations

import argparse
import json
import sys
from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# =============================================================================
# 枚举类型
# =============================================================================

class EvidenceTier(str, Enum):
    """证据强度标签（↔ Consensus 循证分级；教育级诚实标注，非医疗声明）

    Values:
        WELL_ESTABLISHED: 强 — APA "well-established"（EFT/CBCT/IBCT）
        MODERATE: 中 — ≥1 meta 或 ≥3 RCT（Gottman/DBT/ACT/SFBT 等）
        EMERGING: 弱·新兴 — <3 RCT 或探索性
        LENS: 透镜 — 无干预结局证据，提供理解视角（社会学/哲学/精神分析等）
    """
    WELL_ESTABLISHED = "well_established"
    MODERATE = "moderate"
    EMERGING = "emerging"
    LENS = "lens"


class InterventionOrLens(str, Enum):
    """干预 vs 透镜（Claude 提出、Consensus 证据印证的二分）

    Values:
        INTERVENTION: 干预 — 有可操作步骤与结局证据的技术
        LENS: 透镜 — 概念框架，提供理解视角但无干预 RCT
    """
    INTERVENTION = "intervention"
    LENS = "lens"


class FaqRiskLevel(str, Enum):
    """FAQ 条目的风险上下文级别（用于 WS-D 路由治理）

    注意：与 schemas.py 的 RiskLevel（对话分析输出，5 级中文）是不同的轴，勿混用。

    Values:
        GENERAL: 一般 — 可正常进入 RAG 概率召回
        ELEVATED: 偏高 — 焦虑/惊恐等强情绪的应对工具（如接地），可召回
        CRISIS: 危机 — 自杀/自伤/IPV 相关，绝不作危机首响，须由 WS-D 硬编码拦截
    """
    GENERAL = "general"
    ELEVATED = "elevated"
    CRISIS = "crisis"


class ReviewStatus(str, Enum):
    """临床审核状态（WS-C）。仅 approved 进入生产检索。"""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


# =============================================================================
# 类目 Taxonomy（domain → category）
# =============================================================================

KNOWLEDGE_TAXONOMY: dict[str, list[str]] = {
    "clinical_intervention": [
        "eft", "cbct", "ibct", "gottman", "dbt_skills",
        "act", "sfbt", "rebt", "mindfulness", "prep",
    ],
    "communication": ["communication"],
    "crisis_safety": ["crisis", "safety"],
    "perspectives": ["sociology", "philosophy", "game_theory", "cultural"],
    "clinical_lens": ["psychoanalytic", "bowen", "attachment"],
}

# 扁平化：category → domain
CATEGORY_TO_DOMAIN: dict[str, str] = {
    cat: domain for domain, cats in KNOWLEDGE_TAXONOMY.items() for cat in cats
}
VALID_CATEGORIES: frozenset[str] = frozenset(CATEGORY_TO_DOMAIN.keys())

# 默认 intervention/lens 归属（按 domain）
LENS_DOMAINS: frozenset[str] = frozenset({"perspectives", "clinical_lens"})


# =============================================================================
# 核心 Schema：KnowledgeEntry（v2）
# =============================================================================

class KnowledgeEntry(BaseModel):
    """知识库 FAQ 单条目（Schema v2）。

    v2 生产条目要求 id / evidence_tier / intervention_or_lens 必填；旧 v1 条目先由迁移脚本回填后再校验。
    答案长度不做硬上限（旧条目可能较长），150–350 字为质量软约束（另由 lint 检查）。
    """
    # ---- v2 新增 ----
    id: str = Field(
        ..., min_length=1, pattern=r"^[a-z0-9_]+$",
        description="稳定唯一 ID，建议 <category>_<topic>（小写/数字/下划线）",
    )
    # ---- v1 沿用 ----
    question: str = Field(..., min_length=1, description="口语化提问")
    answer: str = Field(..., min_length=1, description="①概念 ②生活例子 ③话术；150–350 字（软约束）")
    category: str = Field(..., min_length=1, description="见 VALID_CATEGORIES")
    keywords: list[str] = Field(default_factory=list, description="人工精选关键词")
    source: str = Field(default="", description="来源/文献")
    license: str = Field(default="", description="版权声明（见 license 三区规范）")
    # ---- v2 新增（标签 / 软链接 / 审核） ----
    evidence_tier: EvidenceTier = Field(..., description="证据强度标签")
    intervention_or_lens: InterventionOrLens = Field(..., description="干预 or 透镜")
    risk_level: FaqRiskLevel = Field(default=FaqRiskLevel.GENERAL, description="风险上下文级别")
    related: list[str] = Field(default_factory=list, description="软链接：相关条目 id（WS-E）")
    evidence_note: str = Field(default="", description="可选；证据有争议项的诚实标注")
    review_status: ReviewStatus = Field(default=ReviewStatus.PENDING, description="审核状态")
    reviewed_by: str = Field(default="", description="审核人")
    review_date: str = Field(default="", description="审核日期")

    @field_validator("category")
    @classmethod
    def _category_in_taxonomy(cls, v: str) -> str:
        if v not in VALID_CATEGORIES:
            raise ValueError(
                f"未知 category '{v}'，须属于 taxonomy：{sorted(VALID_CATEGORIES)}"
            )
        return v


# domain=lens 应 intervention_or_lens=lens；非硬错误，仅供 lint
def lens_domain_mismatch(entry: KnowledgeEntry) -> bool:
    """返回 True 表示透镜域条目却标了 intervention（建议核查，非硬错误）。"""
    domain = CATEGORY_TO_DOMAIN.get(entry.category, "")
    return domain in LENS_DOMAINS and entry.intervention_or_lens == InterventionOrLens.INTERVENTION


# =============================================================================
# 校验器
# =============================================================================

def _repo_root() -> Path:
    # scripts/advisor/knowledge_schema.py → parents[2] = 仓库根
    return Path(__file__).resolve().parents[2]


def validate_knowledge_dir(knowledge_dir: Path) -> tuple[int, list[str]]:
    """递归校验 knowledge_dir 下所有 .jsonl 条目。

    Returns: (有效条目数, 错误信息列表)
    """
    errors: list[str] = []
    valid = 0
    seen_ids: dict[str, str] = {}
    file_domains: dict[tuple[str, str], set[str]] = {}  # (folder, file) → {domain}
    if not knowledge_dir.exists():
        return 0, [f"目录不存在：{knowledge_dir}"]

    for p in sorted(knowledge_dir.rglob("*.jsonl")):
        rel = p.relative_to(knowledge_dir)
        folder = rel.parts[0] if len(rel.parts) > 1 else "(根)"
        for ln, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as e:
                errors.append(f"{rel}:{ln} JSON 解析失败：{e}")
                continue
            try:
                entry = KnowledgeEntry(**raw)
            except Exception as e:
                errors.append(f"{rel}:{ln} 校验失败：{e}")
                continue
            # 唯一性
            if entry.id in seen_ids:
                errors.append(f"{rel}:{ln} id 重复：'{entry.id}'（已见于 {seen_ids[entry.id]}）")
            else:
                seen_ids[entry.id] = f"{rel}:{ln}"
            # lint：透镜域一致性
            if lens_domain_mismatch(entry):
                errors.append(
                    f"{rel}:{ln} ⚠️ lint：category '{entry.category}' 属透镜域却标 intervention"
                )
            file_domains.setdefault((folder, p.name), set()).add(
                CATEGORY_TO_DOMAIN.get(entry.category, "?")
            )
            valid += 1

    # lint：folder=domain 一致性 —— ① 单文件单一 domain ② 每 domain 只落一个文件夹
    domain_folders: dict[str, set[str]] = {}
    for (folder, fname), doms in file_domains.items():
        if len(doms) > 1:
            errors.append(f"{folder}/{fname} ⚠️ lint：单文件混了多个 domain {sorted(doms)}")
        for d in doms:
            domain_folders.setdefault(d, set()).add(folder)
    for d, folders in sorted(domain_folders.items()):
        if len(folders) > 1:
            errors.append(
                f"⚠️ lint：domain '{d}' 散落在多个文件夹 {sorted(folders)}（应合并到一个，保持 folder=domain）"
            )
    return valid, errors


def main() -> int:
    ap = argparse.ArgumentParser(description="知识库 Schema v2 校验器")
    ap.add_argument(
        "--dir", default=str(_repo_root() / "advisor_out" / "knowledge"),
        help="知识库根目录（默认 advisor_out/knowledge）",
    )
    args = ap.parse_args()
    knowledge_dir = Path(args.dir)
    valid, errors = validate_knowledge_dir(knowledge_dir)

    print(f"[校验] 目录：{knowledge_dir}")
    print(f"[校验] 有效条目：{valid}")
    if errors:
        print(f"[校验] ❌ 发现 {len(errors)} 个问题：")
        for e in errors:
            print(f"   - {e}")
        return 1
    print("[校验] ✅ 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
