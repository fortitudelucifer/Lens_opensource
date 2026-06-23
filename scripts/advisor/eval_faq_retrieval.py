#!/usr/bin/env python3
"""FAQ 检索评测（WS-B · B2/B6）：纯关键词 baseline vs 关键词×语义 hybrid。

指标：Recall@3 / Recall@5 / MRR（在 top-10 内）。对 hybrid 扫不同 α。
CPU 编码（use_gpu=False），可在无 GPU 环境运行。

用法：conda run -n wechatDHA python -m scripts.advisor.eval_faq_retrieval
"""
from __future__ import annotations

import json
from pathlib import Path

from scripts.advisor.api.services import rag_service as R
from scripts.advisor.graph_rag import GraphRAGManager

EVAL = Path(__file__).resolve().parent / "faq_eval_set.jsonl"


def _metrics(rank_fn, items):
    r3 = r5 = mrr = 0.0
    n = len(items)
    for it in items:
        ranked = rank_fn(it["query"])  # list[id]，长度≤10
        hit_rank = next((i + 1 for i, rid in enumerate(ranked) if rid in it["expect"]), 0)
        if hit_rank and hit_rank <= 3:
            r3 += 1
        if hit_rank and hit_rank <= 5:
            r5 += 1
        if hit_rank:
            mrr += 1.0 / hit_rank
    return r3 / n, r5 / n, mrr / n


def main() -> int:
    items = [json.loads(l) for l in EVAL.read_text(encoding="utf-8").splitlines() if l.strip()]
    R.load_faq_knowledge()
    print(f"[eval] 评测 query: {len(items)} | searchable FAQ: "
          f"{sum(1 for e in R.state.faq_entries if R._faq_searchable(e))}")

    # baseline：纯关键词
    def baseline_rank(q):
        return [e.get("id") for e in R.search_faq(q, top_k=10)]

    b3, b5, bmrr = _metrics(baseline_rank, items)
    print(f"\n  baseline(关键词)   Recall@3={b3:.2%}  Recall@5={b5:.2%}  MRR={bmrr:.3f}")

    # 加载 BGE-M3（CPU），挂到 state，启用语义
    print("\n[eval] 加载 BGE-M3（CPU）+ 构建 FAQ 语义索引……")
    mgr = GraphRAGManager({"use_gpu_for_embedding": False})
    mgr._load_embedding_model()
    R.state.semantic_rag = mgr
    R.state.semantic_rag_ready = True
    R.USE_FAQ_SEMANTIC = True
    R.build_faq_index()

    print()
    # 纯语义参照（仅语义排名）
    def sem_rank(q):
        qv = R._faq_encode([q])
        if qv is None:
            return []
        sims = R.state.faq_index_mat @ qv[0]
        order = sorted(range(len(R.state.faq_index_ids)), key=lambda i: -sims[i])
        return [R.state.faq_index_ids[i] for i in order if sims[i] >= R.FAQ_SEMANTIC_FLOOR][:10]

    s3, s5, smrr = _metrics(sem_rank, items)
    print(f"  纯语义(参照)     Recall@3={s3:.2%}  Recall@5={s5:.2%}  MRR={smrr:.3f}")

    # 生产 hybrid（search_faq_hybrid = RRF 排名融合）
    R.USE_FAQ_SEMANTIC = True

    def hybrid_rank(q):
        return [e.get("id") for e in R.search_faq_hybrid(q, top_k=10)]

    h3, h5, hmrr = _metrics(hybrid_rank, items)
    print(f"  hybrid(RRF·生产) Recall@3={h3:.2%}  Recall@5={h5:.2%}  MRR={hmrr:.3f}")

    # 按 tag 拆分（gap=词汇鸿沟，最能看出语义增益）
    print("\n[eval] 按 tag 拆分:")
    for tg in ("gap", "direct"):
        sub = [it for it in items if it.get("tag") == tg]
        if not sub:
            continue
        bb = _metrics(baseline_rank, sub)
        hh = _metrics(hybrid_rank, sub)
        print(f"  [{tg:6}] n={len(sub):2}  baseline R@3={bb[0]:.0%} MRR={bb[2]:.2f}  |  "
              f"hybrid R@3={hh[0]:.0%} MRR={hh[2]:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
