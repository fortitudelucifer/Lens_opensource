#!/usr/bin/env python3
"""知识图谱原型（WS-E · E5 prototype）

把 208 条 FAQ 的 `related` 软链接物化成一张内存图（networkx），用于**关系型检索的
原型实验**——回答 §E4 的 go/no-go 问题：「多跳图遍历能否在关系型查询上显著超过
hybrid + E3(1-hop)？」若能 → Neo4j 立项有据；若不能 → 1-hop 软链接已够，永久关闭。

这是**原型**，不是生产组件：纯内存、零额外 GPU、不写盘。生产检索仍走 rag_service。

用法：
    conda run -n wechatDHA python -m scripts.advisor.knowledge_graph          # 自检/统计
    conda run -n wechatDHA python -m scripts.advisor.knowledge_graph --edges  # 导出跨域边
"""
from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path

import networkx as nx

try:
    from scripts.advisor.knowledge_schema import CATEGORY_TO_DOMAIN
except Exception:
    CATEGORY_TO_DOMAIN = {}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _searchable(d: dict) -> bool:
    """与 rag_service._faq_searchable 同义：approved 且非 crisis。"""
    return d.get("review_status") == "approved" and d.get("risk_level", "general") != "crisis"


def build_graph(knowledge_dir: Path | None = None) -> nx.Graph:
    """从 related 软链接构建无向图。无向 = 相关性对称（A↔B）。

    节点属性：category / domain / question / searchable。
    只保留两端都已解析的边（丢弃悬挂 related）。
    """
    knowledge_dir = knowledge_dir or (_repo_root() / "advisor_out" / "knowledge")
    G = nx.Graph()
    raw: list[dict] = []
    for f in glob.glob(str(knowledge_dir / "**" / "*.jsonl"), recursive=True):
        for line in Path(f).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                raw.append(json.loads(line))

    for d in raw:
        cat = d.get("category", "")
        G.add_node(
            d["id"],
            category=cat,
            domain=CATEGORY_TO_DOMAIN.get(cat, "unknown"),
            question=d.get("question", ""),
            searchable=_searchable(d),
        )
    for d in raw:
        for r in d.get("related", []):
            if G.has_node(r) and r != d["id"]:
                G.add_edge(d["id"], r)
    return G


def expand(G: nx.Graph, seed_ids: list[str], hops: int = 1, cap: int = 3,
           gated: bool = True) -> list[str]:
    """从种子节点按跳数扩展，返回去重后的邻居 id（不含种子）。

    排序：先按到任一种子的最短跳数，再按节点度数（中心概念优先）。
    gated=True 时只返回 searchable 节点（与生产 E3 一致）。
    """
    seeds = [s for s in seed_ids if G.has_node(s)]
    if not seeds:
        return []
    dist: dict[str, int] = {}
    for s in seeds:
        for nid, dd in nx.single_source_shortest_path_length(G, s, cutoff=hops).items():
            if dd == 0:
                continue
            dist[nid] = min(dist.get(nid, 99), dd)
    cands = [n for n in dist if n not in set(seeds)]
    if gated:
        cands = [n for n in cands if G.nodes[n].get("searchable")]
    cands.sort(key=lambda n: (dist[n], -G.degree(n)))
    return cands[:cap]


def main() -> int:
    ap = argparse.ArgumentParser(description="知识图谱原型 自检/统计")
    ap.add_argument("--edges", action="store_true", help="导出跨域边（供作者写关系型评测）")
    args = ap.parse_args()

    G = build_graph()
    n, m = G.number_of_nodes(), G.number_of_edges()
    comps = list(nx.connected_components(G))
    degs = [d for _, d in G.degree()]
    iso = [x for x in G.nodes if G.degree(x) == 0]
    print(f"[图] 节点 {n} · 边 {m} · 平均度 {2*m/n:.2f}")
    print(f"[图] 连通分量 {len(comps)} · 最大分量 {max(len(c) for c in comps)} 节点 · 孤立点 {len(iso)}")
    print(f"[图] 度 max={max(degs)} median={sorted(degs)[len(degs)//2]}")

    cross = [(u, v) for u, v in G.edges
             if G.nodes[u]["domain"] != G.nodes[v]["domain"]]
    print(f"[图] 跨域边 {len(cross)}")
    if args.edges:
        print("\n跨域边（u —[域]— v）：")
        for u, v in sorted(cross, key=lambda e: -(G.degree(e[0]) + G.degree(e[1])))[:40]:
            print(f"  {u} [{G.nodes[u]['domain']}] — {v} [{G.nodes[v]['domain']}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
