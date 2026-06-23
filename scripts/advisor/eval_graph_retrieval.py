#!/usr/bin/env python3
"""关系型检索 三臂对照评测（WS-E · E5 决策实验）

回答 §E4 的 go/no-go：在**关系型/多跳查询**上，更深的图遍历能否显著超过现有
hybrid + E3(1-hop)？三臂在**相同投放预算（6 概念）**下对比，隔离「reach」而非预算：

  A  hybrid-only          : hybrid top-6
  B  hybrid + E3 (1-hop)  : hybrid top-3 种子 ∪ 图 1-hop 邻居(cap 3)   ← 生产现状
  C  hybrid + graph 2-hop : hybrid top-3 种子 ∪ 图 2-hop 邻居(cap 3)   ← GraphRAG 候选

指标：
  full   = 命中全部 gold 概念的比例（整体关系召回）
  bridge = 命中「关系型补全概念」（lexically 远、靠图才到）的比例 ← 最关键

判据：C.bridge 相对 B.bridge 有显著提升（≥ +10pp）→ Neo4j 立项有据；
       否则 1-hop 软链接已够 → 永久关闭 GraphRAG。

用法：conda run -n wechatDHA python -m scripts.advisor.eval_graph_retrieval
"""
from __future__ import annotations

import json
from pathlib import Path

import scripts.advisor.api.services.rag_service as R
from scripts.advisor.graph_rag import GraphRAGManager
from scripts.advisor.knowledge_graph import build_graph, expand

EVAL = Path(__file__).resolve().parent / "graph_eval_set.jsonl"
BUDGET = 6      # 每臂投放概念上限
SEEDS = 3       # 扩展臂的种子数（hybrid top-3）
CAP = 3         # 扩展臂的邻居上限


def _recall(delivered: list[str], gold: list[str]) -> float:
    g = set(gold)
    return len(set(delivered) & g) / len(g) if g else 0.0


def main() -> int:
    items = [json.loads(l) for l in EVAL.read_text(encoding="utf-8").splitlines() if l.strip()]
    R.load_faq_knowledge()
    print(f"[eval] 关系型 query: {len(items)} | searchable FAQ: "
          f"{sum(1 for e in R.state.faq_entries if R._faq_searchable(e))}")

    print("[eval] 加载 BGE-M3（CPU）+ 构建 FAQ 语义索引……")
    mgr = GraphRAGManager({"use_gpu_for_embedding": False})
    mgr._load_embedding_model()
    R.state.semantic_rag = mgr
    R.state.semantic_rag_ready = True
    R.USE_FAQ_SEMANTIC = True
    R.build_faq_index()

    G = build_graph()
    print(f"[eval] 图：{G.number_of_nodes()} 节点 · {G.number_of_edges()} 边\n")

    def hybrid_ids(q, k):
        return [e.get("id") for e in R.search_faq_hybrid(q, top_k=k)]

    # ── 可达性诊断：bridge 概念距 hybrid 种子的最短图距离 ──────────────
    # 这是 §E4 的结构性证据：若所有 bridge 都 ≤1 跳，则 2-hop/深度图遍历
    # 没有可作用的对象（C==B 不是 cap 伪影，而是图本身没有 2-hop 的 gold）。
    import networkx as nx
    from collections import Counter
    hist = Counter()
    for it in items:
        seeds = hybrid_ids(it["query"], SEEDS)
        for b in it.get("bridge", []):
            if b in seeds:
                hist["0·已在种子"] += 1; continue
            dmin = min((nx.shortest_path_length(G, s, b)
                        for s in seeds if G.has_node(s) and G.has_node(b)
                        and nx.has_path(G, s, b)), default=99)
            hist[f"{dmin}跳" if dmin < 99 else "不可达"] += 1
    print("[可达性] bridge 概念 距 hybrid 种子 的最短图距离：")
    for k in sorted(hist):
        print(f"    {k}: {hist[k]}")
    beyond1 = sum(v for k, v in hist.items() if k not in ("0·已在种子", "1跳"))
    print(f"    → 距离 ≥2 或不可达的 bridge: {beyond1} 个"
          f"（=0 则深度图遍历无可作用对象）\n")

    def arm_A(q):
        return hybrid_ids(q, BUDGET)

    def arm_B(q):
        seeds = hybrid_ids(q, SEEDS)
        return (seeds + expand(G, seeds, hops=1, cap=CAP))[:BUDGET]

    def arm_C(q):
        seeds = hybrid_ids(q, SEEDS)
        return (seeds + expand(G, seeds, hops=2, cap=CAP))[:BUDGET]

    arms = {"A hybrid-only": arm_A, "B +E3 1-hop": arm_B, "C +graph 2-hop": arm_C}
    agg = {name: {"full": 0.0, "bridge": 0.0} for name in arms}

    print(f"{'query':<26} | " + " | ".join(f"{n.split()[0]}桥" for n in arms))
    print("-" * 60)
    for it in items:
        gold, bridge = it["expect"], it.get("bridge", [])
        row = []
        for name, fn in arms.items():
            got = fn(it["query"])
            agg[name]["full"] += _recall(got, gold)
            br = _recall(got, bridge)
            agg[name]["bridge"] += br
            row.append("✓" if br >= 0.999 else ("半" if br > 0 else "✗"))
        print(f"{it['query'][:24]:<26} | " + "  | ".join(f" {r} " for r in row))

    n = len(items)
    print("\n=== 汇总（均值）===")
    print(f"{'臂':<16} {'full 关系召回':>14} {'bridge 桥接召回':>16}")
    for name in arms:
        print(f"{name:<16} {agg[name]['full']/n:>13.1%} {agg[name]['bridge']/n:>15.1%}")

    b, c = agg["B +E3 1-hop"]["bridge"]/n, agg["C +graph 2-hop"]["bridge"]/n
    delta = c - b
    print(f"\n[§E4 判据]")
    print(f"  C 桥接召回 − B 桥接召回 = {delta:+.1%}")
    print(f"  距种子 ≥2 跳的 bridge   = {beyond1} 个")
    if beyond1 == 0:
        print("  → 结构性结论：关系型 gold 全部 ≤1 跳，**深度图遍历无可作用对象**；"
              "GraphRAG(Neo4j) 不立项（§E4 关闭）。")
        print("  → 真正的杠杆是 E3 邻居『选择』(scoring/cap)，非图深度——廉价调参，无需新基建。")
    elif delta >= 0.10:
        print("  → 2-hop 图遍历显著优于 1-hop：GraphRAG(Neo4j) 立项有据。")
    else:
        print("  → 2-hop 未显著超过 1-hop：E3 软链接已捕获关系价值，GraphRAG 留 Q4。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
