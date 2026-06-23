"""services/rag_service.py — RAG 检索 + 上下文组装 + FAQ + 语义索引

从 server.py 迁移（Step 2，🔴 风险最高）：
  - `_load_rag_metadata`          → `load_rag_metadata`
  - `_init_semantic_rag_background` → `init_semantic_rag_background`
  - `_rag_search`                 → `rag_search`（关键词兜底，目前未被直接调用）
  - `_load_name_mapping`          → `load_name_mapping`
  - `_parse_query_days`           → `parse_query_days`
  - `_day_index_lookup`           → `day_index_lookup`
  - `_enriched_search`            → `enriched_search`
  - `_keyword_search`             → `keyword_search`
  - `_fmt_enriched_summary`       → `fmt_enriched_summary`
  - `_extract_focus_sentences`    → `extract_focus_sentences`
  - `_load_faq_knowledge`         → `load_faq_knowledge`
  - `_search_faq`                 → `search_faq`
  - `_build_rag_context`          → `build_rag_context`
  - `_reload_enriched_data`       → `reload_enriched_data`

另外提供统一启动入口：
  - `init_rag()` 同步加载元数据 + 姓名映射 + FAQ，启动后台语义索引线程。
    server.py 在模块加载时调用一次。

依赖：
  - core/state.py：所有可变状态
  - core/config.py：路径常量（VECTOR_INDEX_DIR / ADVISOR_OUT / CHUNKS_DIR / ANALYSIS_DIR / PROJECT_ROOT）
"""
from __future__ import annotations

import json
import os
import re
import threading
from collections import Counter
from pathlib import Path
from typing import Optional

import numpy as np

from scripts.advisor.chunk_based_rag import ChunkAwareRAG
from ..core import state
from ..core.config import (
    ADVISOR_OUT, ANALYSIS_DIR, CHUNKS_DIR,
    PROJECT_ROOT, VECTOR_INDEX_DIR,
)


# ══════════════════════════════════════════════════════════════
# 启动加载（元数据 / 语义索引 / 姓名映射 / FAQ）
# ══════════════════════════════════════════════════════════════

def load_rag_metadata():
    """加载预构建索引的元数据和用户档案（启动时调用一次）"""
    meta_file = VECTOR_INDEX_DIR / "metadata.json"
    profile_file = VECTOR_INDEX_DIR / "user_profile.json"
    enriched_file = VECTOR_INDEX_DIR / "enriched_metadata.json"
    if meta_file.exists():
        try:
            with open(meta_file, 'r', encoding='utf-8') as f:
                meta = json.load(f)
            state.rag_conversations = meta.get("conversations", [])
            print(f"[GraphRAG] 加载 {len(state.rag_conversations)} 条对话元数据")
        except Exception as e:
            print(f"[GraphRAG] 元数据加载失败: {e}")
    if profile_file.exists():
        try:
            with open(profile_file, 'r', encoding='utf-8') as f:
                state.rag_user_profile = json.load(f)
            print(f"[GraphRAG] 用户档案已加载")
        except Exception as e:
            print(f"[GraphRAG] 用户档案加载失败: {e}")
    # 加载 enriched metadata（ChunkAwareRAG 构建）
    if enriched_file.exists():
        try:
            with open(enriched_file, 'r', encoding='utf-8') as f:
                edata = json.load(f)
            state.enriched_chunks = edata.get("chunks", [])
            state.enriched_max_day = edata.get("max_day", 0)
            state.enriched_day_index = {int(k): v for k, v in edata.get("day_index", {}).items()}
            state.enriched_type_index = edata.get("type_index", {})
            state.chunk_id_to_idx = {c["chunk_id"]: i for i, c in enumerate(state.enriched_chunks)}
            print(f"[ChunkAwareRAG] 加载 {len(state.enriched_chunks)} 条增强元数据, "
                  f"{len(state.enriched_day_index)} 天, 最大第{state.enriched_max_day}天")
        except Exception as e:
            print(f"[ChunkAwareRAG] 增强元数据加载失败: {e}")


def init_semantic_rag_background():
    """后台线程初始化 ChunkAwareRAG 语义检索（加载/构建 FAISS 索引）"""
    try:
        faiss_index_dir = ADVISOR_OUT / "faiss_index"
        chunks_file = CHUNKS_DIR / "conversation_chunks.jsonl"
        # 优先使用反匿名化后的分析文件
        analysis_deanon = ANALYSIS_DIR / "fused_analysis_neutral_moa_deanon.jsonl"
        analysis_file = analysis_deanon if analysis_deanon.exists() else ANALYSIS_DIR / "fused_analysis_neutral_moa.jsonl"

        rag = ChunkAwareRAG({
            'embedding_model': '/data/models/bge-m3',
            'index_dir': str(faiss_index_dir),
            'use_gpu_for_embedding': True,
        })

        # 优先从磁盘加载已保存的 FAISS 索引
        if (faiss_index_dir / 'index.faiss').exists():
            if rag.load_index(str(faiss_index_dir)):
                state.semantic_rag = rag
                state.semantic_rag_ready = True
                print(f"[SemanticRAG] ✅ 从磁盘加载 FAISS 索引 ({rag._faiss_index.ntotal} 向量)")
                return

        # 无已保存索引 → 从原始数据构建
        if not chunks_file.exists():
            print("[SemanticRAG] ⚠️ conversation_chunks.jsonl 不存在，跳过语义索引")
            return

        print("[SemanticRAG] 🔧 首次构建 FAISS 索引（加载 BGE-M3 + 编码 500 chunks）...")
        rag.build_enriched_index(
            chunks_file=str(chunks_file),
            analysis_file=str(analysis_file) if analysis_file.exists() else None,
            show_progress=True,
        )
        # 保存到磁盘，下次启动直接加载
        rag.save_index(str(faiss_index_dir))
        state.semantic_rag = rag
        state.semantic_rag_ready = True
        print(f"[SemanticRAG] ✅ FAISS 索引构建并保存完成 ({rag._faiss_index.ntotal} 向量)")
    except Exception as e:
        print(f"[SemanticRAG] ❌ 初始化失败: {e}")
        import traceback
        traceback.print_exc()


def load_name_mapping():
    """从 configs/anonymization.yaml 加载姓名映射（PII 基础设施的权威来源）"""
    import yaml
    anon_config = PROJECT_ROOT / "configs" / "anonymization.yaml"
    if not anon_config.exists():
        # 回退到 user_profile.json 中的 participants
        participants = state.rag_user_profile.get("participants", {})
        for role, info in participants.items():
            real_name = info.get("name", "")
            if real_name:
                state.name_reverse[role] = real_name
                state.name_mapping[real_name] = role
                for alias in info.get("aliases", []):
                    state.name_mapping[alias] = role
        return

    try:
        with open(anon_config, 'r', encoding='utf-8') as f:
            cfg = yaml.safe_load(f) or {}
        state.me_names = cfg.get("me_names", [])
        state.other_names = cfg.get("other_names", [])
        if state.me_names:
            state.name_reverse["ME"] = state.me_names[0]  # 主名
            for name in state.me_names:
                state.name_mapping[name] = "ME"
        if state.other_names:
            state.name_reverse["OTHER"] = state.other_names[0]  # 主名
            for name in state.other_names:
                state.name_mapping[name] = "OTHER"
        print(f"[PII] 姓名映射已加载: ME={state.me_names}, OTHER={state.other_names}")
    except Exception as e:
        print(f"[PII] 姓名映射加载失败: {e}")


def load_faq_knowledge():
    """递归加载 advisor_out/knowledge/ 下所有 .jsonl 文件"""
    knowledge_dir = ADVISOR_OUT / "knowledge"
    if not knowledge_dir.exists():
        return
    entries = []
    for p in sorted(knowledge_dir.rglob("*.jsonl")):
        try:
            with open(p, 'r', encoding='utf-8') as f:
                file_entries = [json.loads(l) for l in f if l.strip()]
                entries.extend(file_entries)
        except Exception as e:
            print(f"[Knowledge] 加载失败 {p.name}: {e}")
    state.faq_entries = entries
    if entries:
        categories = {}
        for e in entries:
            cat = e.get("category", "general")
            categories[cat] = categories.get(cat, 0) + 1
        cat_str = ", ".join(f"{k}:{v}" for k, v in sorted(categories.items()))
        print(f"[Knowledge] 已加载 {len(entries)} 条专业知识（{cat_str}）")


def reload_enriched_data():
    """重新加载 server 级 enriched 缓存（增量更新后调用）"""
    faiss_dir = ADVISOR_OUT / "faiss_index"
    meta_file = faiss_dir / "metadata.json"
    enriched_file = faiss_dir / "enriched_metadata.json"

    if meta_file.exists():
        with open(meta_file, 'r', encoding='utf-8') as f:
            meta = json.load(f)
        state.rag_conversations = meta.get('conversations', [])
        state.chunk_id_to_idx = {
            c.get('metadata', {}).get('chunk_id', c.get('conversation_id', '')): i
            for i, c in enumerate(state.rag_conversations)
        }

    if enriched_file.exists():
        with open(enriched_file, 'r', encoding='utf-8') as f:
            edata = json.load(f)
        state.enriched_chunks = edata.get('chunks', [])
        state.enriched_day_index = {int(k): v for k, v in edata.get('day_index', {}).items()}
        state.enriched_max_day = edata.get('max_day', 0)

    print(f"[RAG] 缓存已刷新: {len(state.rag_conversations)} conversations, max_day={state.enriched_max_day}")


def init_rag():
    """统一启动入口：加载元数据 + 姓名映射 + FAQ，启动后台语义索引线程。

    由 server.py 在模块加载时调用一次（替代原先散落的 4 个顶层调用）。
    """
    load_rag_metadata()
    t = threading.Thread(target=init_semantic_rag_background, daemon=True)
    t.start()
    # 姓名映射需要 rag_user_profile（load_rag_metadata 已加载），故在其后
    load_name_mapping()
    load_faq_knowledge()


# ══════════════════════════════════════════════════════════════
# 检索：日期 / 关键词 / 语义 / 融合
# ══════════════════════════════════════════════════════════════

def rag_search(query: str, top_k: int = 3) -> list[dict]:
    """
    轻量级关键词检索：从预构建索引的元数据中查找相关对话片段。
    不需要 GPU，使用关键词重叠度评分。（legacy，目前未被主路径调用）
    """
    if not state.rag_conversations:
        return []

    # 提取查询中的关键词（去除停用词）
    stop_words = {'的', '了', '是', '在', '我', '你', '他', '她', '它', '们',
                  '这', '那', '有', '和', '与', '对', '吗', '呢', '吧', '啊',
                  '不', '也', '都', '就', '会', '能', '要', '把', '被', '让',
                  '到', '说', '想', '看', '一个', '什么', '怎么', '为什么',
                  '觉得', '认为', '一种', '什么样', '怎样', '如何'}
    query_words = set(re.findall(r'[\u4e00-\u9fff]+', query))
    # 也保留长度 >= 2 的词
    keywords = {w for w in query_words if len(w) >= 2 and w not in stop_words}
    # 添加特殊人称标记
    if 'OTHER' in query.upper() or '对方' in query or '她' in query or '他' in query:
        keywords.add('OTHER')
    if 'ME' in query.upper() or '自己' in query:
        keywords.add('ME')

    if not keywords:
        return []

    scored = []
    for conv in state.rag_conversations:
        text = conv.get("conversation_text", "")
        # 计算关键词命中数
        hits = sum(1 for kw in keywords if kw in text)
        if hits > 0:
            scored.append((hits, conv))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [item[1] for item in scored[:top_k]]


def parse_query_days(query: str) -> list[int]:
    """
    从用户查询中解析所有日期引用，支持:
    - 单日: 第108天, 2025年10月8日, 10月8日, 2025-10-08
    - 范围: 第108天到第110天, 第108-110天, 9月22日到9月25日
    - 相对: 最近一周, 最近三天, 上个月, 上周, 最后X天
    返回排序去重后的 day 列表
    """
    from datetime import datetime as _dt, timedelta as _td
    _day1 = _dt(2025, 6, 8)
    today_day = (_dt.now() - _day1).days + 1
    max_day = state.enriched_max_day or today_day

    query_days = []

    def _date_to_day(year, month, day_of_month):
        try:
            d = (_dt(year, month, day_of_month) - _day1).days + 1
            if 1 <= d <= max_day + 30:
                return d
        except ValueError:
            pass
        return None

    def _expand_range(start, end):
        if start and end and start <= end:
            return list(range(start, min(end, max_day + 30) + 1))
        return []

    # ── 范围: 第X天到第Y天 / 第X-Y天 ──
    for m in re.finditer(r'第(\d+)[天日]?[到至\-~]第?(\d+)天', query):
        query_days.extend(_expand_range(int(m.group(1)), int(m.group(2))))
    for m in re.finditer(r'第(\d+)-(\d+)天', query):
        query_days.extend(_expand_range(int(m.group(1)), int(m.group(2))))

    # ── 范围: X月Y日到X月Z日 / X月Y日到Z日 ──
    for m in re.finditer(r'(\d{1,2})月(\d{1,2})[日号]?[到至\-~](\d{1,2})月(\d{1,2})[日号]?', query):
        s = _date_to_day(2025, int(m.group(1)), int(m.group(2)))
        e = _date_to_day(2025, int(m.group(3)), int(m.group(4)))
        query_days.extend(_expand_range(s, e))
    for m in re.finditer(r'(\d{1,2})月(\d{1,2})[日号]?[到至\-~](\d{1,2})[日号]', query):
        s = _date_to_day(2025, int(m.group(1)), int(m.group(2)))
        e = _date_to_day(2025, int(m.group(1)), int(m.group(3)))
        query_days.extend(_expand_range(s, e))

    # ── 范围: YYYY-MM-DD 到 YYYY-MM-DD ──
    for m in re.finditer(r'(\d{4})-(\d{1,2})-(\d{1,2})\s*[到至~]\s*(\d{4})-(\d{1,2})-(\d{1,2})', query):
        s = _date_to_day(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        e = _date_to_day(int(m.group(4)), int(m.group(5)), int(m.group(6)))
        query_days.extend(_expand_range(s, e))

    # ── 相对日期: 最近X天/周/月, 上个月, 上周 ──
    rel_patterns = {
        r'最近(\d+)天': lambda m: list(range(max(1, max_day - int(m.group(1)) + 1), max_day + 1)),
        r'最[后近]一周|上周': lambda m: list(range(max(1, max_day - 6), max_day + 1)),
        r'最[后近]两周': lambda m: list(range(max(1, max_day - 13), max_day + 1)),
        r'最[后近](\d+)周': lambda m: list(range(max(1, max_day - int(m.group(1)) * 7 + 1), max_day + 1)),
        r'上个月|最近一个月': lambda m: list(range(max(1, max_day - 29), max_day + 1)),
        r'最近(\d+)个月': lambda m: list(range(max(1, max_day - int(m.group(1)) * 30 + 1), max_day + 1)),
    }
    for pat, gen_fn in rel_patterns.items():
        m = re.search(pat, query)
        if m:
            query_days.extend(gen_fn(m))

    # ── 单日: 第X天 (排除已被范围捕获的) ──
    if not query_days:
        for d in re.findall(r'(?:第)?(\d+)天', query):
            d = int(d)
            if 1 <= d <= max_day:
                query_days.append(d)

    # ── 单日: YYYY年M月D日 ──
    if not query_days:
        for m in re.finditer(r'(\d{4})年(\d{1,2})月(\d{1,2})[日号]?', query):
            d = _date_to_day(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            if d:
                query_days.append(d)

    # ── 单日: M月D日 (默认 2025) ──
    if not query_days:
        for m in re.finditer(r'(\d{1,2})月(\d{1,2})[日号]', query):
            d = _date_to_day(2025, int(m.group(1)), int(m.group(2)))
            if d:
                query_days.append(d)

    # ── 单日: YYYY-MM-DD ──
    if not query_days:
        for m in re.finditer(r'(\d{4})-(\d{1,2})-(\d{1,2})', query):
            d = _date_to_day(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            if d:
                query_days.append(d)

    return sorted(set(query_days))


def day_index_lookup(days: list[int], max_results: int = 20) -> list[dict]:
    """按 day 列表查 enriched index，返回 [{conv, enriched, score}]，去重"""
    results = []
    seen = set()
    for day in days:
        for idx in state.enriched_day_index.get(day, []):
            if idx < len(state.rag_conversations) and idx not in seen:
                conv = state.rag_conversations[idx]
                echunk = state.enriched_chunks[idx] if idx < len(state.enriched_chunks) else {}
                results.append({'conv': conv, 'enriched': echunk, 'score': 10.0, '_idx': idx})
                seen.add(idx)
                if len(results) >= max_results:
                    return results
    return results


def enriched_search(query: str, top_k: int = 3) -> list[dict]:
    """
    混合检索：日期精确 + FAISS 语义 → 合并去重 → 关键词回退。
    支持日期范围 (第X天到第Y天) 和相对日期 (最近一周/上个月)。
    返回 [{conv, enriched, score}]
    """
    if not state.rag_conversations:
        return []

    # ── Level 1: 日期精确/范围命中 ──
    query_days = parse_query_days(query)
    day_results = []
    if query_days and state.enriched_day_index:
        day_results = day_index_lookup(query_days, max_results=top_k * 2)

    # ── Level 2: FAISS 语义检索（如果已就绪）──
    semantic_results_list = []
    if state.semantic_rag_ready and state.semantic_rag is not None:
        try:
            semantic_results = state.semantic_rag.query_enhanced(
                query_text=query, top_k=top_k, use_reranker=True,
            )
            if semantic_results:
                for sr in semantic_results:
                    idx = state.chunk_id_to_idx.get(sr.chunk_id)
                    if idx is not None and idx < len(state.rag_conversations):
                        conv = state.rag_conversations[idx]
                        echunk = state.enriched_chunks[idx] if idx < len(state.enriched_chunks) else {}
                        semantic_results_list.append({
                            'conv': conv, 'enriched': echunk,
                            'score': sr.semantic_score, '_idx': idx,
                        })
        except Exception as e:
            print(f"[SemanticRAG] 语义检索异常，回退关键词: {e}")

    # ── 合并去重: 日期优先 + 语义补充 ──
    if day_results or semantic_results_list:
        merged = []
        seen_idx = set()
        # 日期命中排在前面（高置信度精确匹配）
        for r in day_results:
            idx = r.pop('_idx', None)
            if idx is not None:
                seen_idx.add(idx)
            merged.append(r)
        # 语义补充（去掉已被日期命中的）
        for r in semantic_results_list:
            idx = r.pop('_idx', None)
            if idx not in seen_idx:
                merged.append(r)
                seen_idx.add(idx)
        if merged:
            return merged[:top_k]

    # ── Level 3: 关键词回退 ──
    return keyword_search(query, top_k)


def keyword_search(query: str, top_k: int = 3) -> list[dict]:
    """纯关键词检索（语义检索不可用时的回退）"""
    stop_words = {'的', '了', '是', '在', '我', '你', '他', '她', '它', '们',
                  '这', '那', '有', '和', '与', '对', '吗', '呢', '吧', '啊',
                  '不', '也', '都', '就', '会', '能', '要', '把', '被', '让',
                  '到', '说', '想', '看', '一个', '什么', '怎么', '为什么',
                  '觉得', '认为', '一种', '什么样', '怎样', '如何'}
    query_words = set(re.findall(r'[\u4e00-\u9fff]{2,}', query))
    keywords = {w for w in query_words if len(w) >= 2 and w not in stop_words}
    if 'OTHER' in query.upper() or '对方' in query:
        keywords.add('OTHER')
    if 'ME' in query.upper() or '自己' in query:
        keywords.add('ME')

    if not keywords:
        return []

    def _to_str(v):
        if isinstance(v, str):
            return v
        if isinstance(v, dict):
            return v.get('level', '') or str(v)
        if isinstance(v, list):
            return ' '.join(_to_str(x) for x in v)
        return str(v) if v else ''

    scored = []
    for i, conv in enumerate(state.rag_conversations):
        text = conv.get("conversation_text", "")
        hits = sum(1 for kw in keywords if kw in text)
        if hits == 0:
            continue
        echunk = state.enriched_chunks[i] if i < len(state.enriched_chunks) else {}
        analysis = echunk.get('analysis', {})
        if analysis:
            analysis_text = ' '.join([
                _to_str(analysis.get('relationship_status', '')),
                _to_str(analysis.get('overall_assessment', '')),
                _to_str(analysis.get('key_issues', [])),
                _to_str(analysis.get('conflict_root_causes', [])),
            ])
            hits += sum(0.5 for kw in keywords if kw in analysis_text)
        scored.append({'conv': conv, 'enriched': echunk, 'score': hits})

    scored.sort(key=lambda x: x['score'], reverse=True)
    return scored[:top_k]


def fmt_enriched_summary(echunk: dict) -> str:
    """格式化 enriched chunk 的分析摘要"""
    a = echunk.get('analysis', {})
    if not a:
        return ''
    parts = []
    if a.get('relationship_status'):
        parts.append(f"状态:{a['relationship_status']}")
    if a.get('risk_level'):
        parts.append(f"风险:{a['risk_level']}")
    if a.get('communication_quality'):
        parts.append(f"沟通:{a['communication_quality'][:20]}")
    if a.get('key_issues'):
        parts.append(f"核心:{a['key_issues'][0][:40]}...")
    return ' | '.join(parts)


def extract_focus_sentences(text: str, query: str, max_sentences: int = 5) -> str:
    """维度5: 粒度控制 — 从 chunk 中提取与 query 最相关的句子（sentence focus mode）"""
    # 按消息行切分（对话格式: [时间] SPEAKER: 内容）
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    if len(lines) <= max_sentences:
        return text

    # 提取查询关键词
    query_words = set(re.findall(r'[\u4e00-\u9fff]{2,}', query))
    if not query_words:
        return '\n'.join(lines[:max_sentences])

    # 对每行评分
    scored = []
    for line in lines:
        hits = sum(1 for w in query_words if w in line)
        scored.append((hits, line))
    scored.sort(key=lambda x: x[0], reverse=True)

    # 取 top-N 且保持原始顺序
    top_lines = set(l for _, l in scored[:max_sentences])
    focused = [l for l in lines if l in top_lines]
    return '\n'.join(focused)


def _tokenize_zh(text: str) -> set[str]:
    """中文 + 英文混合分词（用于 FAQ 检索关键词匹配）。

    问题历史：原实现 `re.findall(r'[\u4e00-\u9fff]{2,}', text)` 把整段连续汉字
    当成 1 个 token，导致 `"我和伴侣最近经常吵架"` → `{'我和伴侣最近经常吵架'}`
    无法命中 entry.keywords 里的 `伴侣`/`吵架` 等单词。

    修复方案：
      - 优先用 jieba 分词（已安装在 conda env wechatDHA 里）
      - 退化方案：若 jieba 不可用 → 同时取 `\u4e00-\u9fff` 全段 +
        其内部 2-gram，最大限度提升召回
      - 同时支持英文小写 token（>= 2 字符）· 例如 NVC / EFT 等术语

    返回去重后的 token set，供调用方做关键词重叠度评分。
    """
    tokens: set[str] = set()
    if not text:
        return tokens
    # 英文 token（2 字符以上字母数字）
    for w in re.findall(r'[A-Za-z][A-Za-z0-9]+', text):
        tokens.add(w.lower())
    # 中文：优先 jieba
    try:
        import jieba  # type: ignore
        for w in jieba.cut(text):
            w = w.strip()
            # 单字虚词无意义；2 字以上才计入
            if len(w) >= 2 and re.fullmatch(r'[\u4e00-\u9fff]+', w):
                tokens.add(w)
    except Exception:
        # 退化：连续汉字段 + 2-gram
        for run in re.findall(r'[\u4e00-\u9fff]+', text):
            if len(run) >= 2:
                tokens.add(run)
                # 2-gram 子串
                for i in range(len(run) - 1):
                    tokens.add(run[i:i + 2])
    return tokens


# WS-E E3: 1-hop 软链接关联注入的上限（0 = 关闭）
FAQ_RELATED_MAX = 3

# B 视角保底：当 agent_type 本身是某知识 category（如 game_theory/sociology/philosophy/
# cultural）时，保证该视角至少有这么多条知识被注入——即便用户口语与抽象概念条目字面/
# 语义没撞上。修复"博弈论对话却不引用博弈论知识"（概念全靠人设提示词背诵）的问题。
FAQ_PERSPECTIVE_FLOOR = 2


def _faq_searchable(entry: dict) -> bool:
    """常规检索门控：仅 review_status=approved 且 risk_level!=crisis 可进入召回/关联注入。"""
    return entry.get("review_status") == "approved" and entry.get("risk_level", "general") != "crisis"


# WS-B: FAQ 语义/混合检索（默认关闭；环境变量 USE_FAQ_SEMANTIC=1 开启）
# 评测结论（196 条语料 / 36 query）：关键词 baseline 已很强（R@3 94%、MRR 0.90）；
# RRF 排名融合最稳——召回持平、MRR 提升至 0.919，且不像加权融合那样拉低 R@3。
USE_FAQ_SEMANTIC = os.getenv("USE_FAQ_SEMANTIC", "0") == "1"
FAQ_SEMANTIC_FLOOR = 0.30   # 语义相似度下限，低于此值不参与融合（防小语料误召）
FAQ_RRF_K = 60              # RRF 融合常数（越大越平滑）


def _faq_lexical_scores(query: str, agent_type: str = "") -> dict[str, float]:
    """对所有 searchable FAQ 计算关键词命中分，返回 {id: score}（未截断、未归一化）。

    评分（与历史一致）：命中 question+answer 每 token +1；命中 keywords 每 token +2；
    agent_type 与 entry.category 匹配则 ×2。
    """
    out: dict[str, float] = {}
    query_words = _tokenize_zh(query)
    if not query_words:
        return out
    for entry in state.faq_entries:
        if not _faq_searchable(entry):
            continue
        q_text_lower = (entry.get('question', '') + ' ' + entry.get('answer', '')).lower()
        entry_kws_lower = [str(k).lower() for k in entry.get("keywords", [])]
        hits = sum(1 for w in query_words if w in q_text_lower)
        hits += sum(2 for w in query_words if w in entry_kws_lower)
        if agent_type and entry.get("category") == agent_type:
            hits = hits * 2
        if hits > 0:
            out[entry.get("id", "")] = float(hits)
    return out


def search_faq(query: str, top_k: int = 2, agent_type: str = "") -> list[dict]:
    """专业知识库关键词检索（门控 + agent_type ×2）。语义混合见 search_faq_hybrid。"""
    if not state.faq_entries:
        return []
    scores = _faq_lexical_scores(query, agent_type)
    if not scores:
        return []
    by_id = {e.get("id"): e for e in state.faq_entries}
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    return [by_id[i] for i, _ in ranked[:top_k] if i in by_id]


def _faq_encode(texts: list[str]):
    """用已加载的 semantic_rag（BGE-M3）编码并 L2 归一化，返回 np.ndarray 或 None。"""
    rag = state.semantic_rag
    if rag is None:
        return None
    try:
        vec = rag._encode_texts(texts, show_progress=False)
    except Exception as e:
        print(f"[FAQ-Hybrid] 编码失败: {e}")
        return None
    if vec is None:
        return None
    norms = np.linalg.norm(vec, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (vec / norms).astype("float32")


def build_faq_index() -> bool:
    """对 searchable FAQ 编码建内存索引（懒构建，需 semantic_rag 就绪）。"""
    if not state.semantic_rag_ready or state.semantic_rag is None:
        return False
    entries = [e for e in state.faq_entries if _faq_searchable(e)]
    if not entries:
        state.faq_index_ids, state.faq_index_mat, state.faq_index_n = [], None, 0
        return False
    texts = [
        f"{e.get('question', '')}\n{e.get('answer', '')[:120]}\n{' '.join(str(k) for k in e.get('keywords', []))}"
        for e in entries
    ]
    mat = _faq_encode(texts)
    if mat is None:
        return False
    state.faq_index_ids = [e.get("id", "") for e in entries]
    state.faq_index_mat = mat
    state.faq_index_n = len(entries)
    print(f"[FAQ-Hybrid] 语义索引已构建：{len(entries)} 条")
    return True


def _ensure_faq_index() -> bool:
    """懒构建 / 失效重建（searchable 条数变化时重建）。"""
    cur_n = sum(1 for e in state.faq_entries if _faq_searchable(e))
    if state.faq_index_mat is not None and state.faq_index_n == cur_n:
        return True
    return build_faq_index()


def search_faq_hybrid(query: str, top_k: int = 2, agent_type: str = "") -> list[dict]:
    """关键词 × 语义 混合检索。flag 关闭 / 语义未就绪 / 编码失败 → 回退纯关键词。"""
    _active = USE_FAQ_SEMANTIC and state.semantic_rag_ready and state.semantic_rag is not None
    state.faq_retrieval_log["hybrid" if _active else "keyword"] += 1  # WS-B8 监控
    if not USE_FAQ_SEMANTIC or not state.semantic_rag_ready or state.semantic_rag is None:
        return search_faq(query, top_k, agent_type)
    if not _ensure_faq_index() or state.faq_index_mat is None:
        return search_faq(query, top_k, agent_type)
    qv = _faq_encode([query])
    if qv is None:
        return search_faq(query, top_k, agent_type)

    # 关键词排名
    lex = _faq_lexical_scores(query, agent_type)
    lex_ids = [i for i, _ in sorted(lex.items(), key=lambda kv: kv[1], reverse=True)]
    # 语义排名（过相似度下限）
    sims = state.faq_index_mat @ qv[0]   # 余弦（双方已 L2 归一化）
    sem_sorted = sorted(
        ((state.faq_index_ids[i], float(sims[i])) for i in range(len(state.faq_index_ids))),
        key=lambda kv: kv[1], reverse=True,
    )
    sem_ids = [i for i, s in sem_sorted if s >= FAQ_SEMANTIC_FLOOR]
    # RRF 排名融合（对分数尺度鲁棒；评测中召回持平关键词、MRR 更优）
    fused: dict[str, float] = {}
    for r, i in enumerate(lex_ids):
        fused[i] = fused.get(i, 0.0) + 1.0 / (FAQ_RRF_K + r + 1)
    for r, i in enumerate(sem_ids):
        fused[i] = fused.get(i, 0.0) + 1.0 / (FAQ_RRF_K + r + 1)
    if not fused:
        return []
    by_id = {e.get("id"): e for e in state.faq_entries}
    ranked = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)
    return [by_id[i] for i, _ in ranked[:top_k] if i in by_id]


def perspective_floor(query: str, agent_type: str, exclude_ids: set, already: int) -> list[dict]:
    """B 视角保底：补足 category==agent_type 的知识至 FAQ_PERSPECTIVE_FLOOR 条。

    按与 query 的语义相似度挑（hybrid 就绪时），否则回退关键词分。agent_type 不是
    知识 category（如 neutral）时候选为空 → 自然空操作。
    """
    need = FAQ_PERSPECTIVE_FLOOR - already
    if not agent_type or need <= 0:
        return []
    cands = [e for e in state.faq_entries
             if e.get("category") == agent_type and _faq_searchable(e)
             and e.get("id") not in exclude_ids]
    if not cands:
        return []
    # 语义排序（hybrid 就绪）
    if (USE_FAQ_SEMANTIC and state.semantic_rag_ready and state.semantic_rag is not None
            and _ensure_faq_index() and state.faq_index_mat is not None):
        qv = _faq_encode([query])
        if qv is not None:
            row = {fid: i for i, fid in enumerate(state.faq_index_ids)}
            cands.sort(
                key=lambda e: float(state.faq_index_mat[row[e["id"]]] @ qv[0]) if e.get("id") in row else -1.0,
                reverse=True,
            )
            return cands[:need]
    # 关键词回退
    lex = _faq_lexical_scores(query, agent_type=agent_type)
    cands.sort(key=lambda e: lex.get(e.get("id", ""), 0.0), reverse=True)
    return cands[:need]


def e3_related_neighbors(query: str, faq_results: list[dict]) -> list[dict]:
    """E3 关联概念注入：对称池 + qsim 选择（门控、去重、限 FAQ_RELATED_MAX）。

    对称池 = 命中条目的 outgoing related ∪ incoming（别处 related 指向命中条目的）。
    实验（eval_e3_selection）：只跟 outgoing 时桥接概念封顶 33%；对称池+qsim → 50%。
    qsim = hybrid 就绪时按与 query 的语义相似度排；否则保留作者顺序（outgoing 在前）。
    """
    if FAQ_RELATED_MAX <= 0 or not faq_results:
        return []
    seen = {fq.get("id") for fq in faq_results}
    by_id = {e.get("id"): e for e in state.faq_entries}
    pool: list[str] = []
    # outgoing：命中条目自己标的 related（作者顺序）
    for fq in faq_results:
        for rid in fq.get("related", []):
            if rid not in seen and rid not in pool:
                pool.append(rid)
    # incoming：别处 related 指向命中条目的（对称补全 —— 关系是双向的）
    for e in state.faq_entries:
        eid = e.get("id")
        if eid not in seen and eid not in pool and (seen & set(e.get("related", []))):
            pool.append(eid)
    cands = [rid for rid in pool if rid in by_id and _faq_searchable(by_id[rid])]
    if not cands:
        return []
    # qsim 排序（hybrid 就绪），否则保留作者顺序
    if (USE_FAQ_SEMANTIC and state.semantic_rag_ready and state.semantic_rag is not None
            and _ensure_faq_index() and state.faq_index_mat is not None):
        qv = _faq_encode([query])
        if qv is not None:
            row = {fid: i for i, fid in enumerate(state.faq_index_ids)}
            cands.sort(
                key=lambda rid: float(state.faq_index_mat[row[rid]] @ qv[0]) if rid in row else -1.0,
                reverse=True,
            )
    return [by_id[rid] for rid in cands[:FAQ_RELATED_MAX]]


def get_faq_by_ids(ids: list[str]) -> list[dict]:
    """按 id 从已加载的 FAQ 中取条目（含被 search_faq 门控挡住的 crisis 条目）。

    供危机流程 D2 使用：crisis_resources.yaml 的 knowledge_refs 列出 id，
    本函数从 state.faq_entries 解析对应条目（单一事实源——内容只存 JSONL）。
    """
    if not ids or not state.faq_entries:
        return []
    by_id = {e.get("id"): e for e in state.faq_entries if e.get("id")}
    return [by_id[i] for i in ids if i in by_id]


def build_rag_context(query: str, top_k: int = 3, max_preview: int = 500,
                      agent_type: str = "", use_knowledge: bool = True) -> str:
    """构建 GraphRAG 上下文注入文本（使用 ChunkAwareRAG 增强数据 + 意图分类）"""
    parts = []

    # ── 维度2: 意图分类 → 动态调整检索策略 ──
    intent_result = state.intent_classifier.classify(query)
    strategy = state.intent_classifier.get_search_strategy(intent_result)
    effective_top_k = max(top_k, strategy.get("top_k", top_k))

    # 姓名映射（让模型知道 ME/OTHER 对应的真实姓名）
    if state.name_reverse:
        name_lines = []
        if state.me_names:
            name_lines.append(f"ME = {state.me_names[0]}（所有名称：{'、'.join(state.me_names)}）")
        if state.other_names:
            name_lines.append(f"OTHER = {state.other_names[0]}（所有名称：{'、'.join(state.other_names)}）")
        if name_lines:
            parts.append("【人物对照】\n" + "\n".join(name_lines)
                          + "\n注意：对话记录中使用 ME/OTHER 标记，分别对应上述真实身份。")

    # 用户档案
    if state.rag_user_profile:
        profile_parts = []
        if state.rag_user_profile.get("recurring_topics"):
            profile_parts.append(f"反复话题：{', '.join(state.rag_user_profile['recurring_topics'])}")
        if state.rag_user_profile.get("recurring_conflicts"):
            profile_parts.append(f"反复冲突：{', '.join(state.rag_user_profile['recurring_conflicts'])}")
        if state.rag_user_profile.get("top_emotions"):
            profile_parts.append(f"主要情绪：{', '.join(state.rag_user_profile['top_emotions'])}")
        if state.rag_user_profile.get("relationship_trend"):
            profile_parts.append(f"关系趋势：{state.rag_user_profile['relationship_trend']}")
        if profile_parts:
            parts.append("【用户关系档案】\n" + "\n".join(profile_parts))

    # 意图提示（让 LLM 知道用户意图，优化回复策略）
    intent_hint_map = {
        "emotional_support": "用户正在宣泄情绪，请先共情再给建议",
        "urgent_emotional_support": "用户情绪强烈，请优先安抚",
        "moderate_emotional_support": "用户情绪低落，请温和关怀",
        "conflict_analysis": "用户讨论冲突，请引用相关对话细节进行分析",
        "relationship_guidance": "用户寻求建议，请给出具体可操作的建议",
        "factual_search": "用户查询具体信息，请精确回答",
    }
    hint = intent_hint_map.get(intent_result.suggested_action)
    if hint:
        parts.append(f"【交互提示】{hint}")

    # 增强检索（将真名替换为 ME/OTHER 以提升命中率）
    search_query = query
    for real_name, role in state.name_mapping.items():
        search_query = search_query.replace(real_name, role)
    results = enriched_search(search_query, top_k=effective_top_k)
    if not results:
        results = enriched_search(query, top_k=effective_top_k)

    if results:
        # 历史模式（从分析中提取冲突根源）
        cause_counter = Counter()
        for r in results:
            a = r.get('enriched', {}).get('analysis', {})
            for c in a.get('conflict_root_causes', []):
                short = c.split('：')[0] if '：' in c else c[:50]
                cause_counter[short] += 1
        if cause_counter:
            top_causes = [c for c, _ in cause_counter.most_common(3)]
            parts.append(f"【历史模式】反复冲突根源: {'; '.join(top_causes)}")

        # 相关对话片段（带分析摘要）
        # 维度5: factual_search 使用句级 focus mode，其余用段级预览
        use_focus = intent_result.suggested_action == "factual_search"
        type_label = {'conflict': '冲突', 'sweet': '甜蜜', 'normal': '日常'}
        history_parts = []
        for i, r in enumerate(results, 1):
            conv = r['conv']
            echunk = r.get('enriched', {})
            text = conv.get("conversation_text", "")
            days = echunk.get('days', [])
            ctype = echunk.get('chunk_type', conv.get('metadata', {}).get('chunk_type', 'unknown'))
            day_str = f"第{','.join(str(d) for d in days)}天" if days else '未知时间'
            tl = type_label.get(ctype, ctype)
            summary = fmt_enriched_summary(echunk)

            header = f"片段{i}（{day_str} [{tl}]）"
            if summary:
                header += f"\n  分析: {summary}"
            if use_focus:
                preview = extract_focus_sentences(text, query, max_sentences=8)
            else:
                preview = text[:max_preview] + ("..." if len(text) > max_preview else "")
            history_parts.append(f"{header}\n{preview}")
        parts.append("【相关历史对话片段】\n" + "\n\n".join(history_parts))

    # 维度5: 多源融合 — 专业知识库补充（受 use_knowledge 开关控制）
    faq_results = search_faq_hybrid(query, top_k=3, agent_type=agent_type) if use_knowledge else []
    # B 视角保底：用户处于某知识视角时，保证该视角知识有代表（不靠口语恰好撞上抽象概念）
    if use_knowledge and agent_type:
        floor = perspective_floor(
            query, agent_type,
            exclude_ids={e.get("id") for e in faq_results},
            already=sum(1 for e in faq_results if e.get("category") == agent_type),
        )
        faq_results = faq_results + floor
    if faq_results:
        faq_parts = []
        for fq in faq_results:
            faq_parts.append(f"Q: {fq.get('question', '')}\nA: {fq.get('answer', '')}")
        # D4: 非诊断 guard —— 临床知识仅作教育参考，避免诊断/治疗口吻
        guard = "（以下为教育性参考，请用通俗、非诊断的语言自然融入回应，不要照搬原文，不要下诊断或给医疗结论）"
        parts.append("【专业知识】" + guard + "\n" + "\n\n".join(faq_parts))

        # WS-E E3: 关联概念注入 —— 对称池 + qsim 选择（门控、去重、限量）
        # 作为"跨学科延伸"补充注入，让概念之间的关联在回应中可被点到
        neighbors = e3_related_neighbors(query, faq_results)
        if neighbors:
            rel_lines = [f"· {e.get('question', '')} —— {e.get('answer', '')[:60]}…" for e in neighbors]
            parts.append("【相关概念（跨学科延伸，点到为止即可）】\n" + "\n".join(rel_lines))

    result = "\n\n".join(parts)

    # 将对话片段中的 ME/OTHER 标记替换为真实姓名，避免模型原样输出
    if state.name_reverse:
        me_name = state.name_reverse.get("ME", "")
        other_name = state.name_reverse.get("OTHER", "")
        if me_name:
            result = result.replace("ME:", f"{me_name}:").replace("ME：", f"{me_name}：")
            result = result.replace(" ME ", f" {me_name} ").replace("| ME", f"| {me_name}")
            result = result.replace('"ME"', f'"{me_name}"').replace("'ME'", f"'{me_name}'")
        if other_name:
            result = result.replace("OTHER:", f"{other_name}:").replace("OTHER：", f"{other_name}：")
            result = result.replace(" OTHER ", f" {other_name} ").replace("| OTHER", f"| {other_name}")
            result = result.replace('"OTHER"', f'"{other_name}"').replace("'OTHER'", f"'{other_name}'")

    return result
