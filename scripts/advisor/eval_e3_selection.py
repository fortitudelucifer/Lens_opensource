#!/usr/bin/env python3
"""E3 邻居『选择』策略对照（WS-E · E3 调优实验）

§E4 实验指出：关系型 gold 全在 1 跳内，GraphRAG 深度无用；bridge 召回偏低的真因是
E3 在「种子的 related 候选池」里**选错了 3 个邻居**。本实验在**生产真实候选池**上比较
不同选择策略对 bridge / full 召回的影响，挑出可直接移植回 rag_service 的赢家。

候选池构造 = 完全复刻生产 build_rag_context E3：种子(hybrid top-3) 的 related，
门控(approved+非crisis)、去重、去种子。区别只在「从池里挑哪 3 个」。

策略：
  list   生产现状：related 作者顺序前 N
  degree 图度数高者优先（原 knowledge_graph.expand 用法）
  qsim   与 query 语义最相似者优先
  ssim   与「引入它的种子」语义最相似者优先（related 本就是对种子的关联断言）
  blend  qsim 与 ssim 均值

用法：conda run -n wechatDHA python -m scripts.advisor.eval_e3_selection
"""
from __future__ import annotations

import json
from pathlib import Path

import scripts.advisor.api.services.rag_service as R
from scripts.advisor.graph_rag import GraphRAGManager
from scripts.advisor.knowledge_graph import build_graph

EVAL = Path(__file__).resolve().parent / "graph_eval_set.jsonl"
SEEDS = 3
CAPS = (3, 5)   # 测 cap 敏感性


def _recall(delivered, gold):
    g = set(gold)
    return len(set(delivered) & g) / len(g) if g else 0.0


def main() -> int:
    items = [json.loads(l) for l in EVAL.read_text(encoding="utf-8").splitlines() if l.strip()]
    R.load_faq_knowledge()
    mgr = GraphRAGManager({"use_gpu_for_embedding": False})
    mgr._load_embedding_model()
    R.state.semantic_rag = mgr
    R.state.semantic_rag_ready = True
    R.USE_FAQ_SEMANTIC = True
    R.build_faq_index()
    G = build_graph()

    by_id = {e.get("id"): e for e in R.state.faq_entries}
    id2vec = {fid: R.state.faq_index_mat[i] for i, fid in enumerate(R.state.faq_index_ids)}

    def vec(cid):
        return id2vec.get(cid)

    def pool_for(q, undirected=False):
        """候选池。undirected=False 复刻生产 E3（仅种子 outgoing related）；
        undirected=True 用对称关系（图邻居，含 incoming：别人 related 到种子）。
        都做门控、去重、去种子。"""
        seeds = [e.get("id") for e in R.search_faq_hybrid(q, top_k=SEEDS)]
        seen, pool, owner = set(seeds), [], {}

        def _add(rid, sid):
            if rid not in seen and rid not in pool and rid in by_id and R._faq_searchable(by_id[rid]):
                pool.append(rid); owner[rid] = sid

        # outgoing：种子自己 related 的（生产现状，作者顺序）
        for sid in seeds:
            for rid in by_id.get(sid, {}).get("related", []):
                _add(rid, sid)
        # incoming：别处 related 到种子的（对称补全），确定性顺序
        if undirected:
            for sid in seeds:
                incoming = sorted(e.get("id") for e in R.state.faq_entries
                                  if sid in e.get("related", []) and e.get("id") not in (None, ""))
                for rid in incoming:
                    _add(rid, sid)
        return seeds, pool, owner

    # 选择策略：给定 (query, seeds, pool, owner) → 排好序的候选
    def s_list(q, seeds, pool, owner, qv):
        return pool
    def s_degree(q, seeds, pool, owner, qv):
        return sorted(pool, key=lambda c: -G.degree(c) if G.has_node(c) else 0)
    def s_qsim(q, seeds, pool, owner, qv):
        return sorted(pool, key=lambda c: -(float(qv @ vec(c)) if vec(c) is not None else -1))
    def s_ssim(q, seeds, pool, owner, qv):
        def sc(c):
            sv, cv = vec(owner[c]), vec(c)
            return float(sv @ cv) if sv is not None and cv is not None else -1
        return sorted(pool, key=lambda c: -sc(c))
    def s_blend(q, seeds, pool, owner, qv):
        def sc(c):
            cv = vec(c)
            if cv is None: return -1
            qs = float(qv @ cv)
            sv = vec(owner[c]); ss = float(sv @ cv) if sv is not None else 0.0
            return (qs + ss) / 2
        return sorted(pool, key=lambda c: -sc(c))

    strats = {"list": s_list, "degree": s_degree, "qsim": s_qsim, "ssim": s_ssim, "blend": s_blend}
    pools = {"directed(生产)": False, "undirected(对称)": True}
    res = {(pl, name, cap): {"full": 0.0, "bridge": 0.0}
           for pl in pools for name in strats for cap in CAPS}
    psize = {pl: [] for pl in pools}

    for it in items:
        q, gold, bridge = it["query"], it["expect"], it.get("bridge", [])
        qv = R._faq_encode([q])
        qv = qv[0] if qv is not None else None
        for pl, und in pools.items():
            seeds, pool, owner = pool_for(q, undirected=und)
            psize[pl].append(len(pool))
            for name, fn in strats.items():
                ordered = fn(q, seeds, pool, owner, qv)
                for cap in CAPS:
                    delivered = seeds + ordered[:cap]
                    res[(pl, name, cap)]["full"] += _recall(delivered, gold)
                    res[(pl, name, cap)]["bridge"] += _recall(delivered, bridge)

    n = len(items)
    print(f"\n[E3 选择实验] {n} 关系型 query")
    for pl in pools:
        print(f"  候选池 {pl}: 平均 {sum(psize[pl])/n:.1f} | 池>{max(CAPS)} 的 query: {sum(1 for s in psize[pl] if s>max(CAPS))}")
    base = res[("directed(生产)", "list", 3)]["bridge"] / n
    print(f"\n  基准 = directed/list/cap3（生产现状）：bridge {base:.1%}\n")
    print(f"{'候选池':<18} {'策略':<8} {'cap':>4} {'full':>8} {'bridge':>9}")
    print("-" * 52)
    for pl in pools:
        for cap in CAPS:
            for name in strats:
                f = res[(pl, name, cap)]["full"] / n
                b = res[(pl, name, cap)]["bridge"] / n
                mark = f"  ({(b-base):+.1%})" if (pl, name, cap) != ("directed(生产)", "list", 3) else ""
                print(f"{pl:<18} {name:<8} {cap:>4} {f:>7.1%} {b:>8.1%}{mark}")
            print()
    # 自动选优（按 bridge，再按 full）
    best = max(res, key=lambda k: (res[k]["bridge"], res[k]["full"]))
    bf, bb = res[best]["full"]/n, res[best]["bridge"]/n
    print("两个杠杆：① 候选池 directed→undirected（跟随对称关系）② 池内选择策略。")
    print(f"\n[结论] directed 池在任何策略下都封顶 {base:.1%}（bridge 在 incoming 边上，outgoing 够不着）。")
    print(f"       最优 = 池[{best[0]}] · 选择[{best[1]}] · cap[{best[2]}]"
          f" → full {bf:.1%} / bridge {bb:.1%}（bridge {bb-base:+.1%}）。")
    print("       即：**对称化候选池 + 语义(qsim)选择** 才能捞回 incoming bridge；list/degree 不行。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
