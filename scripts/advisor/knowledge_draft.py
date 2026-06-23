#!/usr/bin/env python3
"""知识库批量起草脚本（WS-C · C3）

把 `knowledge_worklist.py` 的工单条目交给 LLM 起草为 **schema v2 草稿**
（`review_status="draft"`，等待 C4 三级人工审核后才置 approved）。

设计要点：
  - 工单元数据（evidence_tier / intervention_or_lens / risk_level / license_zone /
    evidence_note）是**确定的、不交给 LLM 决定**——脚本直接回填，LLM 只负责
    question / answer / keywords / source 这些文本字段。
  - house style 与起草要求集中在 `PROMPT_TEMPLATE`（C2 的权威模板，治理文档引用此处）。
  - 每条草稿过 `knowledge_schema.KnowledgeEntry` 结构校验；失败的丢进 *.rejected.jsonl。
  - 复用 `model_router.ModelRouter`（云端 0 VRAM）；`--dry-run` 不调 LLM，只导出拼好的
    prompt，便于无 key 环境检查或人工/外部 LLM 起草。

用法：
    # 干跑：导出某波次的 prompt，不调用 LLM
    conda run -n wechatDHA python -m scripts.advisor.knowledge_draft --wave W1 --dry-run

    # 实跑：用 deepseek 起草 eft 这一类，输出草稿 JSONL
    conda run -n wechatDHA python -m scripts.advisor.knowledge_draft \
        --category eft --backend deepseek_reasoner --out advisor_out/knowledge/_drafts/eft.jsonl
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from scripts.advisor.knowledge_worklist import iter_worklist

# license_zone → 标准 license 串（与 治理规范 §A4 / 台账一致）
LICENSE_BY_ZONE = {
    "green": "原创讲解（基于公共领域心理学概念）",
    "green_academic": "原创讲解（基于公开学术概念）",
    "red_to_green": "原创讲解（学术通用概念，未引用专有材料）",
    "open": "公共领域/开放工具",
}

# 透镜类 category 用"学术概念"措辞
LENS_CATEGORIES = {"psychoanalytic", "bowen", "attachment"}

# ── C2 权威起草模板（house style）────────────────────────────────────
PROMPT_TEMPLATE = """你是一位中文关系咨询知识库的内容撰稿人。请为下面的主题写**一条** FAQ 词条。

【主题】{topic}
【所属类别】{category}（{iol_cn}）
【证据强度】{evidence_tier}{note_cn}

【house style（务必遵守）】
1. question：一句**口语化、第一人称**的真实困惑（如"为什么我一提需求，TA 就觉得我在指责？"），不要书面术语堆砌。
2. answer：150–350 字，三段式自然融合——①一句话点出概念 ②一个具体生活化例子 ③一句可以照着说的话术（"你可以试着说：……"）。
3. **非诊断**：不出现"你有 XX 症/障碍"，不下诊断、不开药、不承诺疗效；保持教育与反思口吻。
4. **原创表达**：用自己的话讲通用概念，**严禁**复制任何手册原文、讲义、worksheet、问卷条目或专有图示。{redzone_cn}
5. 中文书写，温暖、平等、不说教；避免"必须/应该"等命令语气。

【输出格式】只输出一个 JSON 对象，不要 markdown 代码块，字段：
{{"question": "...", "answer": "...", "keywords": ["3-6个中文关键词"], "source": "概念综述（写明所依据的通用概念，不要指向具体页码/专有材料）"}}
"""

IOL_CN = {"intervention": "干预技能，需给可操作话术", "lens": "理解透镜，不冒充疗法"}


def _license_for(row: dict) -> str:
    zone = row["license_zone"]
    if zone == "green" and row["category"] in LENS_CATEGORIES:
        return LICENSE_BY_ZONE["green_academic"]
    return LICENSE_BY_ZONE.get(zone, "")


def build_prompt(row: dict) -> str:
    note = row.get("evidence_note") or ""
    redzone = ("\n   ⚠️ 本类受版权/商标保护：只讲学术界通用概念，禁用\"官方/认证/Method™/®\"等表述，"
               "禁抄任何 worksheet 与商标化术语。") if row["license_zone"] == "red_to_green" else ""
    return PROMPT_TEMPLATE.format(
        topic=row["topic"],
        category=row["category"],
        iol_cn=IOL_CN.get(row["intervention_or_lens"], row["intervention_or_lens"]),
        evidence_tier=row["evidence_tier"],
        note_cn=f"（限定：{note}）" if note else "",
        redzone_cn=redzone,
    )


def _parse_llm_json(text: str) -> dict | None:
    """从 LLM 输出里抽第一个 JSON 对象（容忍 ```json 包裹）。"""
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def assemble_entry(row: dict, llm: dict) -> dict:
    """工单确定字段 + LLM 文本字段 → schema v2 草稿（review_status=draft）。"""
    return {
        "id": row["id"],
        "question": llm.get("question", "").strip(),
        "answer": llm.get("answer", "").strip(),
        "category": row["category"],
        "keywords": llm.get("keywords", [])[:6],
        "source": llm.get("source", "概念综述"),
        "license": _license_for(row),
        "evidence_tier": row["evidence_tier"],
        "intervention_or_lens": row["intervention_or_lens"],
        "risk_level": row["risk_level"],
        "related": [],                       # 软链接由人工/后续标注（WS-E）
        "evidence_note": row.get("evidence_note", ""),
        "review_status": "draft",            # 关键：草稿不进检索，待 C4 审核
        "reviewed_by": "",
        "review_date": "",
    }


def _validate(entry: dict) -> list[str]:
    try:
        from scripts.advisor.knowledge_schema import KnowledgeEntry
        KnowledgeEntry(**entry)
        return []
    except Exception as e:  # pydantic ValidationError 或缺字段
        return [str(e).split("\n")[0]]


def main() -> int:
    ap = argparse.ArgumentParser(description="知识库批量起草（C3）")
    ap.add_argument("--wave", help="只起草某波次（W1/W2/W3/Safety/Lens）")
    ap.add_argument("--category", help="只起草某 category（如 eft）")
    ap.add_argument("--limit", type=int, default=0, help="最多起草几条（0=不限）")
    ap.add_argument("--backend", default="deepseek_reasoner", help="model_router 后端名")
    ap.add_argument("--out", default="advisor_out/knowledge/_drafts/draft.jsonl")
    ap.add_argument("--dry-run", action="store_true", help="只导出 prompt，不调 LLM")
    args = ap.parse_args()

    rows = [r for r in iter_worklist()
            if (not args.wave or r["wave"] == args.wave)
            and (not args.category or r["category"] == args.category)]
    if args.limit:
        rows = rows[:args.limit]
    if not rows:
        print("没有匹配的工单条目。"); return 1

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    if args.dry_run:
        pf = out.with_suffix(".prompts.txt")
        with open(pf, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(f"### {r['id']}\n{build_prompt(r)}\n\n{'='*60}\n\n")
        print(f"[dry-run] {len(rows)} 条 prompt → {pf}（未调用 LLM）")
        return 0

    from scripts.advisor.model_router import ModelRouter
    router = ModelRouter()

    ok, rej = [], []
    for r in rows:
        resp = router.call(args.backend, build_prompt(r), temperature=0.7, max_tokens=1200)
        llm = _parse_llm_json(resp or "")
        if not llm:
            rej.append({**r, "_error": "LLM 输出无法解析为 JSON", "_raw": resp}); continue
        entry = assemble_entry(r, llm)
        errs = _validate(entry)
        if errs:
            rej.append({**entry, "_error": errs[0]}); continue
        ok.append(entry)
        print(f"  ✓ {r['id']}  ({len(entry['answer'])}字)")

    with open(out, "w", encoding="utf-8") as fh:
        for e in ok:
            fh.write(json.dumps(e, ensure_ascii=False) + "\n")
    print(f"[草稿] {len(ok)}/{len(rows)} → {out}（review_status=draft，待 C4 审核）")
    if rej:
        rf = out.with_suffix(".rejected.jsonl")
        with open(rf, "w", encoding="utf-8") as fh:
            for e in rej:
                fh.write(json.dumps(e, ensure_ascii=False) + "\n")
        print(f"⚠️ {len(rej)} 条未通过 → {rf}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
