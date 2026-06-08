"""routes/rag.py — RAG 检索 API + 增量更新"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException

from ..core import state
from ..core.config import ADVISOR_OUT
from ..core.models import RAGSearchRequest
from ..services import rag_service

router = APIRouter()


def _build_rag_result(idx: int, score: float = 0.0, full_text: bool = False) -> dict:
    """构建单条 RAG 检索结果"""
    conv = state.rag_conversations[idx] if idx < len(state.rag_conversations) else {}
    echunk = state.enriched_chunks[idx] if idx < len(state.enriched_chunks) else {}
    text = conv.get('conversation_text', '')

    result = {
        'chunk_id': echunk.get('chunk_id', conv.get('conversation_id', '')),
        'chunk_type': echunk.get('chunk_type', ''),
        'days': echunk.get('days', []),
        'message_count': echunk.get('message_count', 0),
        'conversation_preview': text if full_text else (text[:500] + ('...' if len(text) > 500 else '')),
        'score': score,
        'analysis_summary': rag_service.fmt_enriched_summary(echunk),
    }
    a = echunk.get('analysis', {})
    if a:
        result['analysis'] = {
            'relationship_status': a.get('relationship_status', ''),
            'communication_quality': a.get('communication_quality', ''),
            'risk_level': a.get('risk_level', ''),
            'key_issues': a.get('key_issues', []),
            'conflict_root_causes': a.get('conflict_root_causes', []),
            'overall_assessment': a.get('overall_assessment', ''),
            'time_patterns': a.get('time_patterns', []),
        }
    return result


@router.post("/api/rag/incremental-update")
async def rag_incremental_update(
    chunks_file: Optional[str] = None,
    analysis_file: Optional[str] = None,
):
    """
    增量更新 RAG 索引：添加新 chunks 到现有 FAISS 索引（无需全量重建）

    Args:
        chunks_file: 新 chunks 的 JSONL 文件路径（默认: conversation_chunks.jsonl）
        analysis_file: 对应的分析文件路径（可选）

    流程: 读取新 chunks → 过滤已存在的 → 追加到 FAISS + enriched_metadata → 保存
    """
    if not state.semantic_rag_ready or state.semantic_rag is None:
        raise HTTPException(status_code=503, detail="语义 RAG 未就绪，请等待初始化完成")

    chunks_path = Path(chunks_file) if chunks_file else ADVISOR_OUT / "chunks" / "conversation_chunks.jsonl"
    if not chunks_path.exists():
        raise HTTPException(status_code=404, detail=f"chunks 文件不存在: {chunks_path}")

    # 加载新 chunks
    new_chunks = []
    with open(chunks_path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                new_chunks.append(json.loads(line))

    # 加载分析数据（如有）
    analysis_map = {}
    if analysis_file:
        ap = Path(analysis_file)
        if ap.exists():
            with open(ap, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        a = json.loads(line)
                        cid = a.get('chunk_id', '')
                        if cid:
                            analysis_map[cid] = a.get('analysis_features', {})

    # 执行增量更新
    added = state.semantic_rag.add_chunks_incremental(new_chunks, analysis_map)

    # 同步更新 server 级缓存
    if added > 0:
        state.semantic_rag.save_index()
        # 重新加载 server 级 enriched data 以保持一致
        rag_service.reload_enriched_data()

    return {
        "status": "ok",
        "chunks_scanned": len(new_chunks),
        "chunks_added": added,
        "total_chunks": len(state.rag_conversations),
    }


@router.post("/api/rag/search")
async def rag_search(req: RAGSearchRequest):
    """
    RAG 增强检索（无 GPU，使用预构建 enriched_metadata）

    支持:
    - 精确日期: day=109
    - 日期范围: day_range="100-120"
    - 关键词语义: query="我们为什么吵架"
    - 类型过滤: chunk_type="conflict"
    """
    results = []

    # 日期检索
    if req.day is not None:
        indices = state.enriched_day_index.get(req.day, [])
        for idx in indices:
            if idx < len(state.rag_conversations) and idx < len(state.enriched_chunks):
                results.append(_build_rag_result(idx))

    # 日期范围
    elif req.day_range:
        try:
            s, e = req.day_range.split('-')
            start_day, end_day = int(s), int(e)
            seen = set()
            for d in range(start_day, end_day + 1):
                for idx in state.enriched_day_index.get(d, []):
                    if idx not in seen and idx < len(state.rag_conversations):
                        results.append(_build_rag_result(idx))
                        seen.add(idx)
        except (ValueError, IndexError):
            raise HTTPException(400, "day_range 格式错误，应为 '100-120'")

    # 关键词检索
    elif req.query:
        search_query = req.query
        for real_name, role in state.name_mapping.items():
            search_query = search_query.replace(real_name, role)
        hits = rag_service.enriched_search(search_query, top_k=req.top_k)
        if not hits:
            hits = rag_service.enriched_search(req.query, top_k=req.top_k)
        for h in hits:
            conv = h['conv']
            echunk = h.get('enriched', {})
            idx = state.chunk_id_to_idx.get(conv.get('conversation_id', ''))
            if idx is not None:
                results.append(_build_rag_result(idx, score=h['score']))
            else:
                results.append({
                    'chunk_id': conv.get('conversation_id', ''),
                    'conversation_preview': conv.get('conversation_text', '')[:500],
                    'score': h['score'],
                })

    # 类型过滤
    if req.chunk_type:
        results = [r for r in results if r.get('chunk_type') == req.chunk_type]

    return {
        'results': results[:req.top_k],
        'total': len(results),
        'enriched_available': bool(state.enriched_chunks),
        'max_day': state.enriched_max_day,
        'total_chunks': len(state.rag_conversations),
    }


@router.get("/api/rag/day/{day_num}")
async def rag_day(day_num: int):
    """精确日期检索: 返回指定天的所有 chunks 及分析"""
    indices = state.enriched_day_index.get(day_num, [])
    results = []
    for idx in indices:
        if idx < len(state.rag_conversations) and idx < len(state.enriched_chunks):
            results.append(_build_rag_result(idx))
    return {
        'day': day_num,
        'chunks': results,
        'count': len(results),
    }


@router.get("/api/rag/chunk/{chunk_id}")
async def rag_chunk_detail(chunk_id: str):
    """获取单个 chunk 的完整信息（对话 + 分析 + 跨天关联）"""
    idx = state.chunk_id_to_idx.get(chunk_id)
    if idx is None:
        raise HTTPException(404, f"chunk {chunk_id} 不存在")

    result = _build_rag_result(idx, full_text=True)

    # 跨天关联
    echunk = state.enriched_chunks[idx]
    associations = []
    days = set(echunk.get('days', []))
    analysis = echunk.get('analysis', {})

    # 策略1: time_patterns 引用
    if analysis.get('time_patterns'):
        dp = re.compile(r'第(\d+)天')
        ref_days = set()
        for pat in analysis['time_patterns']:
            ref_days.update(int(d) for d in dp.findall(pat))
        for d in ref_days - days:
            for nidx in state.enriched_day_index.get(d, []):
                if nidx != idx and nidx < len(state.enriched_chunks):
                    nc = state.enriched_chunks[nidx]
                    associations.append({
                        'chunk_id': nc['chunk_id'],
                        'reason': f'time_patterns 引用第{d}天',
                        'days': nc.get('days', []),
                        'chunk_type': nc.get('chunk_type', ''),
                    })

    # 策略2: 相邻天 + 类型变化
    for day in days:
        for offset in [-1, 1]:
            nbr = day + offset
            for nidx in state.enriched_day_index.get(nbr, []):
                if nidx != idx and nidx < len(state.enriched_chunks):
                    nc = state.enriched_chunks[nidx]
                    if nc.get('chunk_type') != echunk.get('chunk_type'):
                        associations.append({
                            'chunk_id': nc['chunk_id'],
                            'reason': f'第{day}→第{nbr}天 {echunk.get("chunk_type")}→{nc.get("chunk_type")}',
                            'days': nc.get('days', []),
                            'chunk_type': nc.get('chunk_type', ''),
                        })

    result['associations'] = associations[:5]
    return result


@router.get("/api/rag/stats")
async def rag_stats():
    """RAG 索引统计"""
    type_dist = {}
    status_dist = {}
    risk_dist = {}
    for ec in state.enriched_chunks:
        ct = ec.get('chunk_type', 'unknown')
        type_dist[ct] = type_dist.get(ct, 0) + 1
        a = ec.get('analysis', {})
        if a:
            st = a.get('relationship_status', '未知')
            if not isinstance(st, str):
                st = st.get('level', str(st)) if isinstance(st, dict) else str(st)
            status_dist[st] = status_dist.get(st, 0) + 1
            rl = a.get('risk_level', '未知')
            if not isinstance(rl, str):
                rl = rl.get('level', str(rl)) if isinstance(rl, dict) else str(rl)
            risk_dist[rl] = risk_dist.get(rl, 0) + 1

    return {
        'total_chunks': len(state.rag_conversations),
        'enriched_chunks': len(state.enriched_chunks),
        'total_days': len(state.enriched_day_index),
        'day_range': [min(state.enriched_day_index.keys(), default=0),
                      state.enriched_max_day] if state.enriched_day_index else [0, 0],
        'type_distribution': type_dist,
        'status_distribution': status_dist,
        'risk_distribution': risk_dist,
        'user_profile': state.rag_user_profile,
    }
