#!/usr/bin/env python3
"""
ChunkAwareRAG — 分析增强的多维检索系统

功能：
- 在 GraphRAGManager 基础上增加多维评分重加权和结构化上下文组装
- 将 MoA 分析元数据（analysis_features）注入 chunk 索引
- 支持日期级精确索引（第X天 → chunk 映射）
- 多维评分公式：语义相似度×0.5 + 时间相关性×0.2 + 情感匹配度×0.3
- 跨天关联检测（利用 analysis 中的 time_patterns）
- 输出结构化上下文（用于 Chat prompt injection）

架构:
  Layer 1: FAISS 向量召回 (top-20)       ← 继承 GraphRAGManager
  Layer 2: BGE-Reranker 重排 (top-10)    ← 继承 GraphRAGManager
  Layer 3: 多维评分重加权 (top-5)         ← 本模块新增
  Layer 4: 上下文组装                      ← 本模块新增

处理流程：
1. 接收用户查询
2. Layer 1-2: 调用父类 GraphRAGManager 进行向量召回和重排
3. Layer 3: 对重排结果进行多维评分（语义/时间/情感）
4. Layer 4: 将 top-5 结果组装为结构化上下文文本
5. 返回上下文文本供 LLM prompt 注入

输入：
- 用户查询文本
- 已索引的对话 chunks（含 analysis_features 元数据）

输出：
- 结构化上下文文本（用于注入 LLM prompt）
- 检索结果列表（含多维评分）

依赖：
- scripts.advisor.graph_rag: GraphRAGManager 基类
- FAISS: 向量索引
- BGE-M3: 嵌入模型
- BGE-Reranker-V2-M3: 重排模型

使用示例：
    from scripts.advisor.chunk_based_rag import ChunkAwareRAG
    
    rag = ChunkAwareRAG(config)
    rag.build_index(chunks_with_analysis)
    context = rag.query("最近总是吵架", top_k=5)

注意事项：
- 需要先通过 MoA 分析生成 analysis_features 后才能构建增强索引
- 多维评分中的情感匹配度依赖 chunk 的 analysis_features.relationship_status
- GPU 显存占用与 GraphRAGManager 相同（BGE-M3 约 2GB）

作者：forcifer
更新于：2026-02-15
"""

import json
import logging
from datetime import datetime
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import sys

import numpy as np

# 支持作为 module 和 standalone script 两种运行方式
_project_root = str(Path(__file__).resolve().parents[2])
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from scripts.advisor.graph_rag import GraphRAGManager, RetrievalResult

logger = logging.getLogger(__name__)


# =============================================================================
# 数据结构
# =============================================================================

@dataclass
class ChunkAnalysis:
    """Chunk 的 MoA 分析元数据"""
    relationship_status: str = ''
    communication_quality: str = ''
    emotional_balance: str = ''
    key_issues: list[str] = field(default_factory=list)
    advice: list[str] = field(default_factory=list)
    time_patterns: list[str] = field(default_factory=list)
    conflict_root_causes: list[str] = field(default_factory=list)
    multimodal_signals: str = ''
    repair_attempts: str = ''
    personality_dynamics: str = ''
    overall_assessment: str = ''
    risk_level: str = ''
    criticism: dict = field(default_factory=dict)


@dataclass
class EnrichedChunkMetadata:
    """带分析增强的 Chunk 元数据"""
    chunk_id: str = ''
    chunk_type: str = 'normal'
    days: list[int] = field(default_factory=list)
    message_count: int = 0
    start_time: str = ''
    end_time: str = ''
    score: float = 0.0
    mm_density: dict = field(default_factory=dict)
    analysis: Optional[ChunkAnalysis] = None


@dataclass
class EnhancedRetrievalResult:
    """多维检索结果"""
    chunk_id: str = ''
    conversation_text: str = ''
    metadata: EnrichedChunkMetadata = field(default_factory=EnrichedChunkMetadata)
    semantic_score: float = 0.0
    temporal_score: float = 0.0
    emotional_score: float = 0.0
    final_score: float = 0.0
    analysis_summary: str = ''


# =============================================================================
# ChunkAwareRAG
# =============================================================================

class ChunkAwareRAG(GraphRAGManager):
    """
    分析增强的多维 RAG 系统

    继承 GraphRAGManager 的 BGE-M3 + FAISS + Reranker 基础设施，
    新增 MoA 分析元数据索引、日期精确检索、多维评分和上下文组装。

    使用方法:
        rag = ChunkAwareRAG(config)
        rag.build_enriched_index(
            chunks_file='advisor_out/chunks/conversation_chunks.jsonl',
            analysis_file='advisor_out/analysis/fused_analysis_neutral_moa.jsonl',
        )
        results = rag.query_enhanced("我们为什么总是吵架", top_k=5)
        results = rag.query_by_day(109)
        context = rag.assemble_context(results)
    """

    WEIGHT_SEMANTIC = 0.5
    WEIGHT_TEMPORAL = 0.2
    WEIGHT_EMOTIONAL = 0.3

    def __init__(self, config: Optional[dict] = None):
        super().__init__(config)
        self._day_to_indices: dict[int, list[int]] = defaultdict(list)
        self._type_to_indices: dict[str, list[int]] = defaultdict(list)
        self._enriched_metadata: list[EnrichedChunkMetadata] = []
        self._chunk_id_to_idx: dict[str, int] = {}
        self._max_day: int = 0
        self._day_pattern = re.compile(r'第(\d+)天')
        self._date_pattern = re.compile(r'(\d{4}-\d{2}-\d{2})')
        # Day 1 = 2025-06-08 (从多个数据点交叉验证)
        self._day1_date = datetime(2025, 6, 8)
        # 查询中的中文日期模式: "10月8日", "2025年10月8日", "2025-10-08"
        self._query_date_patterns = [
            re.compile(r'(\d{4})年(\d{1,2})月(\d{1,2})[日号]?'),  # 2025年10月8日
            re.compile(r'(\d{1,2})月(\d{1,2})[日号]'),             # 10月8日
            re.compile(r'(\d{4})-(\d{1,2})-(\d{1,2})'),           # 2025-10-08
        ]

    # =========================================================================
    # 索引构建
    # =========================================================================

    def build_enriched_index(
        self,
        chunks_file: str,
        analysis_file: Optional[str] = None,
        show_progress: bool = True,
    ):
        """
        构建分析增强的向量索引

        Args:
            chunks_file: conversation_chunks.jsonl 路径
            analysis_file: fused_analysis_neutral_moa.jsonl 路径 (可选)
            show_progress: 是否显示进度条
        """
        chunks = []
        with open(chunks_file, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    chunks.append(json.loads(line))

        if not chunks:
            logger.warning("空 chunks 文件")
            return

        logger.info(f"加载 {len(chunks)} 个 chunks")

        # 加载分析数据
        analysis_map: dict[str, dict] = {}
        if analysis_file and Path(analysis_file).exists():
            with open(analysis_file, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        a = json.loads(line)
                        cid = a.get('chunk_id', '')
                        if cid:
                            analysis_map[cid] = a.get('analysis_features', {})
            logger.info(f"加载 {len(analysis_map)} 条分析数据")

        conversations = []
        self._enriched_metadata = []
        self._chunk_id_to_idx = {}
        self._day_to_indices.clear()
        self._type_to_indices.clear()
        self._max_day = 0

        for i, chunk in enumerate(chunks):
            chunk_id = chunk.get('chunk_id', f'chunk_{i:04d}')
            conv_text = chunk.get('conversation', '') or chunk.get('conversation_text', '')

            # 提取天数：支持 "第X天" 和 "YYYY-MM-DD" 两种格式
            day_nums = set(int(d) for d in self._day_pattern.findall(conv_text))
            for date_str in self._date_pattern.findall(conv_text):
                try:
                    dt = datetime.strptime(date_str, '%Y-%m-%d')
                    day_num = (dt - self._day1_date).days + 1
                    if day_num > 0:
                        day_nums.add(day_num)
                except ValueError:
                    pass
            days = sorted(day_nums)
            if days:
                self._max_day = max(self._max_day, max(days))

            # 构建增强元数据
            af = analysis_map.get(chunk_id, {})
            chunk_analysis = self._parse_analysis(af) if af else None

            enriched = EnrichedChunkMetadata(
                chunk_id=chunk_id,
                chunk_type=chunk.get('chunk_type', 'normal'),
                days=days,
                message_count=chunk.get('message_count', 0),
                start_time=chunk.get('start_time', ''),
                end_time=chunk.get('end_time', ''),
                score=chunk.get('score', 0.0),
                mm_density=chunk.get('mm_density', {}),
                analysis=chunk_analysis,
            )
            self._enriched_metadata.append(enriched)
            self._chunk_id_to_idx[chunk_id] = i

            for day in days:
                self._day_to_indices[day].append(i)
            self._type_to_indices[enriched.chunk_type].append(i)

            # GraphRAGManager conversation dict
            metadata_dict = {
                'chunk_id': chunk_id,
                'chunk_type': enriched.chunk_type,
                'days': days,
                'message_count': enriched.message_count,
                'start_time': enriched.start_time,
                'end_time': enriched.end_time,
                'score': enriched.score,
                'mm_density': enriched.mm_density,
            }
            if chunk_analysis:
                metadata_dict['relationship_status'] = chunk_analysis.relationship_status
                metadata_dict['risk_level'] = chunk_analysis.risk_level
                metadata_dict['communication_quality'] = chunk_analysis.communication_quality

            conversations.append({
                'conversation_id': chunk_id,
                'conversation_text': conv_text,
                'timestamp': enriched.start_time,
                'metadata': metadata_dict,
            })

        # 调用父类构建 FAISS 索引
        self.build_index(conversations, show_progress=show_progress)

        type_dist = dict(Counter(m.chunk_type for m in self._enriched_metadata))
        analysis_count = sum(1 for m in self._enriched_metadata if m.analysis)
        logger.info(
            f"增强索引构建完成: {len(self._enriched_metadata)} chunks, "
            f"覆盖第{min(self._day_to_indices.keys(), default=0)}~"
            f"第{self._max_day}天 ({len(self._day_to_indices)}天), "
            f"类型: {type_dist}, 有分析: {analysis_count}"
        )

    # =========================================================================
    # 增量更新
    # =========================================================================

    def add_chunks_incremental(
        self,
        new_chunks: list[dict],
        analysis_map: Optional[dict[str, dict]] = None,
    ) -> int:
        """
        增量添加新 chunks 到现有索引（无需全量重建）

        Args:
            new_chunks: 新 chunk 列表，格式同 conversation_chunks.jsonl
            analysis_map: {chunk_id: analysis_features} 可选分析数据

        Returns:
            实际新增的 chunk 数量（跳过已存在的）
        """
        if not new_chunks:
            return 0

        analysis_map = analysis_map or {}
        added = 0
        new_conversations = []

        base_idx = len(self._enriched_metadata)

        for chunk in new_chunks:
            chunk_id = chunk.get('chunk_id', f'chunk_{base_idx + added:04d}')

            # 跳过已存在的 chunk
            if chunk_id in self._chunk_id_to_idx:
                logger.debug(f"跳过已存在的 chunk: {chunk_id}")
                continue

            conv_text = chunk.get('conversation', '') or chunk.get('conversation_text', '')

            # 提取天数
            day_nums = set(int(d) for d in self._day_pattern.findall(conv_text))
            for date_str in self._date_pattern.findall(conv_text):
                try:
                    dt = datetime.strptime(date_str, '%Y-%m-%d')
                    day_num = (dt - self._day1_date).days + 1
                    if day_num > 0:
                        day_nums.add(day_num)
                except ValueError:
                    pass
            days = sorted(day_nums)
            if days:
                self._max_day = max(self._max_day, max(days))

            # 构建增强元数据
            af = analysis_map.get(chunk_id, {})
            chunk_analysis = self._parse_analysis(af) if af else None

            idx = base_idx + added
            enriched = EnrichedChunkMetadata(
                chunk_id=chunk_id,
                chunk_type=chunk.get('chunk_type', 'normal'),
                days=days,
                message_count=chunk.get('message_count', 0),
                start_time=chunk.get('start_time', ''),
                end_time=chunk.get('end_time', ''),
                score=chunk.get('score', 0.0),
                mm_density=chunk.get('mm_density', {}),
                analysis=chunk_analysis,
            )
            self._enriched_metadata.append(enriched)
            self._chunk_id_to_idx[chunk_id] = idx

            for day in days:
                self._day_to_indices[day].append(idx)
            self._type_to_indices[enriched.chunk_type].append(idx)

            metadata_dict = {
                'chunk_id': chunk_id,
                'chunk_type': enriched.chunk_type,
                'days': days,
                'message_count': enriched.message_count,
                'start_time': enriched.start_time,
                'end_time': enriched.end_time,
                'score': enriched.score,
                'mm_density': enriched.mm_density,
            }
            if chunk_analysis:
                metadata_dict['relationship_status'] = chunk_analysis.relationship_status
                metadata_dict['risk_level'] = chunk_analysis.risk_level
                metadata_dict['communication_quality'] = chunk_analysis.communication_quality

            new_conversations.append({
                'conversation_id': chunk_id,
                'conversation_text': conv_text,
                'timestamp': enriched.start_time,
                'metadata': metadata_dict,
            })
            added += 1

        # 调用父类增量更新 FAISS 索引
        if new_conversations:
            self.update_index(new_conversations, show_progress=False)
            logger.info(
                f"增量更新完成: +{added} chunks, 总计 {len(self._enriched_metadata)} chunks, "
                f"max_day={self._max_day}"
            )

        return added

    # =========================================================================
    # 多维检索
    # =========================================================================

    def query_enhanced(
        self,
        query_text: str,
        top_k: int = 5,
        time_filter: Optional[str] = None,
        emotion_filter: Optional[str] = None,
        topic_filter: Optional[str] = None,
        use_reranker: bool = True,
    ) -> list[EnhancedRetrievalResult]:
        """
        多维增强检索

        Layer 1: FAISS 向量召回 (top-20)
        Layer 2: BGE-Reranker 重排 (top-10)
        Layer 3: 多维评分重加权 + 过滤

        Args:
            query_text: 查询文本
            top_k: 最终返回数量
            time_filter: 'recent' | 'day_108' | 'days_100-120'
            emotion_filter: 'conflict' | 'sweet' | 'normal'
            topic_filter: 话题关键词
            use_reranker: 是否使用重排器
        """
        query_days = self._extract_query_days(query_text)
        query_emotion = self._detect_query_emotion(query_text)

        # 精确日期查询: 优先日期索引 + 语义补充
        if query_days and len(query_days) <= 3:
            day_results = []
            for day in query_days:
                day_results.extend(self.query_by_day(day))
            if day_results:
                semantic = self._get_base_results(query_text, use_reranker, 10)
                seen = {r.chunk_id for r in day_results}
                for sr in semantic:
                    if sr.conversation_id not in seen:
                        day_results.append(self._base_to_enhanced(sr))
                        seen.add(sr.conversation_id)
                return self._apply_multidim_scoring(
                    day_results, query_days, query_emotion,
                    time_filter, emotion_filter, topic_filter, top_k,
                )

        # 常规路径
        base = self._get_base_results(query_text, use_reranker, self.top_k_retrieval)
        enhanced = [self._base_to_enhanced(r) for r in base]
        return self._apply_multidim_scoring(
            enhanced, query_days, query_emotion,
            time_filter, emotion_filter, topic_filter, top_k,
        )

    def query_by_day(self, day_num: int) -> list[EnhancedRetrievalResult]:
        """精确日期检索: 返回指定天的所有 chunks"""
        indices = self._day_to_indices.get(day_num, [])
        results = []
        for idx in indices:
            if idx >= len(self._conversations) or idx >= len(self._enriched_metadata):
                continue
            conv = self._conversations[idx]
            meta = self._enriched_metadata[idx]
            results.append(EnhancedRetrievalResult(
                chunk_id=meta.chunk_id,
                conversation_text=conv.get('conversation_text', ''),
                metadata=meta,
                semantic_score=1.0,
                temporal_score=1.0,
                emotional_score=0.5,
                final_score=1.0,
                analysis_summary=self._fmt_summary(meta.analysis),
            ))
        results.sort(key=lambda r: r.metadata.score, reverse=True)
        return results

    def query_by_day_range(self, start_day: int, end_day: int) -> list[EnhancedRetrievalResult]:
        """日期范围检索"""
        results, seen = [], set()
        for day in range(start_day, end_day + 1):
            for r in self.query_by_day(day):
                if r.chunk_id not in seen:
                    results.append(r)
                    seen.add(r.chunk_id)
        return results

    def query_by_type(self, chunk_type: str) -> list[EnhancedRetrievalResult]:
        """按类型检索 (conflict/sweet/normal)"""
        indices = self._type_to_indices.get(chunk_type, [])
        results = []
        for idx in indices:
            if idx >= len(self._conversations) or idx >= len(self._enriched_metadata):
                continue
            conv = self._conversations[idx]
            meta = self._enriched_metadata[idx]
            results.append(EnhancedRetrievalResult(
                chunk_id=meta.chunk_id,
                conversation_text=conv.get('conversation_text', ''),
                metadata=meta,
                semantic_score=0.5,
                final_score=meta.score,
                analysis_summary=self._fmt_summary(meta.analysis),
            ))
        return results

    # =========================================================================
    # 跨天关联
    # =========================================================================

    def find_cross_day_associations(
        self, chunk_id: str, max_associations: int = 3,
    ) -> list[dict]:
        """
        查找与指定 chunk 跨天关联的 chunks

        策略:
        1. analysis.time_patterns 中的跨天引用
        2. 时间相邻 + 类型互补 (conflict→sweet 等)
        3. 共享冲突根源 (前缀匹配)
        """
        target_idx = self._chunk_id_to_idx.get(chunk_id)
        if target_idx is None:
            return []

        target = self._enriched_metadata[target_idx]
        target_days = set(target.days)
        associations = []
        seen_ids = {chunk_id}

        # 策略1: time_patterns 引用
        if target.analysis and target.analysis.time_patterns:
            ref_days = set()
            for pat in target.analysis.time_patterns:
                for d in self._day_pattern.findall(pat):
                    ref_days.add(int(d))
            for day in ref_days - target_days:
                for idx in self._day_to_indices.get(day, []):
                    m = self._enriched_metadata[idx]
                    if m.chunk_id not in seen_ids:
                        associations.append({
                            'chunk_id': m.chunk_id,
                            'reason': f'time_patterns 引用第{day}天',
                            'days': m.days,
                            'relationship_status': m.analysis.relationship_status if m.analysis else '',
                        })
                        seen_ids.add(m.chunk_id)

        # 策略2: 时间相邻 + 类型变化
        for day in target_days:
            for offset in [-1, 1, -2, 2]:
                nbr = day + offset
                for idx in self._day_to_indices.get(nbr, []):
                    m = self._enriched_metadata[idx]
                    if m.chunk_id in seen_ids:
                        continue
                    if m.chunk_type != target.chunk_type:
                        associations.append({
                            'chunk_id': m.chunk_id,
                            'reason': f'第{day}→第{nbr}天 {target.chunk_type}→{m.chunk_type}',
                            'days': m.days,
                            'relationship_status': m.analysis.relationship_status if m.analysis else '',
                        })
                        seen_ids.add(m.chunk_id)

        # 策略3: 冲突根源前缀匹配
        if target.analysis and target.analysis.conflict_root_causes:
            target_prefixes = {c[:20] for c in target.analysis.conflict_root_causes if len(c) >= 20}
            if target_prefixes:
                for i, m in enumerate(self._enriched_metadata):
                    if m.chunk_id in seen_ids or not m.analysis:
                        continue
                    for cause in m.analysis.conflict_root_causes:
                        if cause[:20] in target_prefixes:
                            associations.append({
                                'chunk_id': m.chunk_id,
                                'reason': f'共享冲突根源: {cause[:40]}...',
                                'days': m.days,
                                'relationship_status': m.analysis.relationship_status,
                            })
                            seen_ids.add(m.chunk_id)
                            break

        return associations[:max_associations]

    # =========================================================================
    # 上下文组装
    # =========================================================================

    def assemble_context(
        self,
        results: list[EnhancedRetrievalResult],
        include_profile: bool = True,
        include_associations: bool = True,
        max_conv_chars: int = 500,
    ) -> str:
        """
        组装结构化上下文 (用于 Chat prompt injection)

        输出:
          【用户档案】...
          【历史模式】...
          【相关对话1】第X天 [冲突] (相关度0.87)
          【跨天关联】...
        """
        parts = []

        # 用户档案
        if include_profile and self._user_profile:
            p = self._user_profile
            lines = [f'【用户档案】共{p.total_conversations}段对话']
            if p.recurring_topics:
                lines.append(f'  反复话题: {", ".join(p.recurring_topics[:5])}')
            if p.recurring_conflicts:
                lines.append(f'  反复冲突: {", ".join(p.recurring_conflicts[:3])}')
            if p.relationship_trend:
                lines.append(f'  关系趋势: {p.relationship_trend}')
            if p.communication_style_me:
                lines.append(f'  ME风格: {p.communication_style_me}')
            if p.communication_style_other:
                lines.append(f'  OTHER风格: {p.communication_style_other}')
            parts.append('\n'.join(lines))

        # 历史模式
        cause_counter = Counter()
        for r in results:
            if r.metadata.analysis and r.metadata.analysis.conflict_root_causes:
                for c in r.metadata.analysis.conflict_root_causes:
                    short = c.split('：')[0] if '：' in c else c[:50]
                    cause_counter[short] += 1
        if cause_counter:
            top = [c for c, _ in cause_counter.most_common(3)]
            parts.append(f'【历史模式】反复冲突根源: {"; ".join(top)}')

        # 相关对话
        type_label = {'conflict': '冲突', 'sweet': '甜蜜', 'normal': '日常'}
        for i, r in enumerate(results, 1):
            day_str = f'第{",".join(str(d) for d in r.metadata.days)}天' if r.metadata.days else '未知'
            tl = type_label.get(r.metadata.chunk_type, '日常')
            lines = [f'【相关对话{i}】{day_str} [{tl}] (相关度{r.final_score:.2f})']
            if r.analysis_summary:
                lines.append(f'  {r.analysis_summary}')
            preview = r.conversation_text[:max_conv_chars]
            if len(r.conversation_text) > max_conv_chars:
                preview += '...'
            lines.append(f'  对话: {preview}')
            parts.append('\n'.join(lines))

        # 跨天关联
        if include_associations and results:
            all_assoc = []
            for r in results[:3]:
                for a in self.find_cross_day_associations(r.chunk_id, 2):
                    ds = f'第{",".join(str(d) for d in a["days"])}天' if a.get('days') else ''
                    all_assoc.append(f'  {r.chunk_id}→{a["chunk_id"]} ({ds}): {a["reason"]}')
            if all_assoc:
                parts.append('【跨天关联】\n' + '\n'.join(all_assoc[:5]))

        return '\n\n'.join(parts)

    # =========================================================================
    # 持久化扩展
    # =========================================================================

    def save_index(self, path: Optional[str] = None):
        """保存索引 + 增强元数据"""
        super().save_index(path)
        save_dir = Path(path) if path else self.index_dir

        enriched_data = []
        for meta in self._enriched_metadata:
            d = {
                'chunk_id': meta.chunk_id, 'chunk_type': meta.chunk_type,
                'days': meta.days, 'message_count': meta.message_count,
                'start_time': meta.start_time, 'end_time': meta.end_time,
                'score': meta.score,
            }
            if meta.analysis:
                d['analysis'] = {
                    'relationship_status': meta.analysis.relationship_status,
                    'communication_quality': meta.analysis.communication_quality,
                    'emotional_balance': meta.analysis.emotional_balance,
                    'key_issues': meta.analysis.key_issues,
                    'time_patterns': meta.analysis.time_patterns,
                    'conflict_root_causes': meta.analysis.conflict_root_causes,
                    'risk_level': meta.analysis.risk_level,
                    'overall_assessment': meta.analysis.overall_assessment,
                }
            enriched_data.append(d)

        with open(save_dir / 'enriched_metadata.json', 'w', encoding='utf-8') as f:
            json.dump({
                'chunks': enriched_data,
                'max_day': self._max_day,
                'day_index': {str(k): v for k, v in self._day_to_indices.items()},
                'type_index': dict(self._type_to_indices),
            }, f, ensure_ascii=False, indent=2)
        logger.info(f"增强元数据已保存到 {save_dir / 'enriched_metadata.json'}")

    def load_index(self, path: Optional[str] = None) -> bool:
        """加载索引 + 增强元数据"""
        if not super().load_index(path):
            return False

        load_dir = Path(path) if path else self.index_dir
        enriched_file = load_dir / 'enriched_metadata.json'

        if enriched_file.exists():
            with open(enriched_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            self._max_day = data.get('max_day', 0)
            self._day_to_indices = defaultdict(list, {
                int(k): v for k, v in data.get('day_index', {}).items()
            })
            self._type_to_indices = defaultdict(list, data.get('type_index', {}))

            self._enriched_metadata = []
            self._chunk_id_to_idx = {}
            for i, d in enumerate(data.get('chunks', [])):
                analysis = None
                if 'analysis' in d:
                    a = d['analysis']
                    analysis = ChunkAnalysis(
                        relationship_status=a.get('relationship_status', ''),
                        communication_quality=a.get('communication_quality', ''),
                        emotional_balance=a.get('emotional_balance', ''),
                        key_issues=a.get('key_issues', []),
                        time_patterns=a.get('time_patterns', []),
                        conflict_root_causes=a.get('conflict_root_causes', []),
                        risk_level=a.get('risk_level', ''),
                        overall_assessment=a.get('overall_assessment', ''),
                    )
                meta = EnrichedChunkMetadata(
                    chunk_id=d.get('chunk_id', ''),
                    chunk_type=d.get('chunk_type', 'normal'),
                    days=d.get('days', []),
                    message_count=d.get('message_count', 0),
                    start_time=d.get('start_time', ''),
                    end_time=d.get('end_time', ''),
                    score=d.get('score', 0.0),
                    mm_density=d.get('mm_density', {}),
                    analysis=analysis,
                )
                self._enriched_metadata.append(meta)
                self._chunk_id_to_idx[meta.chunk_id] = i

            logger.info(
                f"增强元数据已加载: {len(self._enriched_metadata)} chunks, "
                f"{len(self._day_to_indices)} 天"
            )
        else:
            logger.warning(f"增强元数据文件不存在: {enriched_file}，仅基础索引")
        return True

    # =========================================================================
    # 内部方法
    # =========================================================================

    @staticmethod
    def _parse_analysis(features: dict) -> ChunkAnalysis:
        """解析 analysis_features dict → ChunkAnalysis"""
        def _lst(v):
            return v if isinstance(v, list) else ([v] if isinstance(v, str) and v else [])

        return ChunkAnalysis(
            relationship_status=features.get('relationship_status', ''),
            communication_quality=features.get('communication_quality', ''),
            emotional_balance=features.get('emotional_balance', ''),
            key_issues=_lst(features.get('key_issues', [])),
            advice=_lst(features.get('advice', [])),
            time_patterns=_lst(features.get('time_patterns', [])),
            conflict_root_causes=_lst(features.get('conflict_root_causes', [])),
            multimodal_signals=features.get('multimodal_signals', ''),
            repair_attempts=features.get('repair_attempts', ''),
            personality_dynamics=features.get('personality_dynamics', ''),
            overall_assessment=features.get('overall_assessment', ''),
            risk_level=features.get('risk_level', ''),
            criticism=features.get('criticism', {}),
        )

    def _date_to_day_num(self, dt: datetime) -> int:
        """将日期转换为 enriched_metadata 中的 day number"""
        return (dt - self._day1_date).days + 1

    def _extract_query_days(self, query: str) -> list[int]:
        """从查询中提取天数引用，支持 第X天 / X月Y日 / YYYY-MM-DD 等格式"""
        days = set(int(d) for d in self._day_pattern.findall(query))

        # 中文日期: 2025年10月8日
        for m in self._query_date_patterns[0].finditer(query):
            try:
                dt = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                d = self._date_to_day_num(dt)
                if 1 <= d <= self._max_day + 30:
                    days.add(d)
            except ValueError:
                pass

        # 中文日期: 10月8日 (默认 2025 年)
        for m in self._query_date_patterns[1].finditer(query):
            try:
                dt = datetime(2025, int(m.group(1)), int(m.group(2)))
                d = self._date_to_day_num(dt)
                if 1 <= d <= self._max_day + 30:
                    days.add(d)
            except ValueError:
                pass

        # ISO 日期: 2025-10-08
        for m in self._query_date_patterns[2].finditer(query):
            try:
                dt = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                d = self._date_to_day_num(dt)
                if 1 <= d <= self._max_day + 30:
                    days.add(d)
            except ValueError:
                pass

        return sorted(days)

    @staticmethod
    def _detect_query_emotion(query: str) -> str:
        """检测查询情感意图"""
        mapping = {
            'conflict': ['吵架', '生气', '烦', '冲突', '分手', '不理', '吵', '闹'],
            'sweet': ['甜蜜', '开心', '幸福', '浪漫', '爱', '想你', '高兴'],
            'sad': ['难过', '伤心', '哭', '委屈', '失望', '心痛'],
            'anxious': ['担心', '焦虑', '不安', '害怕', '紧张'],
        }
        for emo, kws in mapping.items():
            if any(kw in query for kw in kws):
                return emo
        return ''

    def _get_base_results(
        self, query_text: str, use_reranker: bool, recall_k: int = 20,
    ) -> list[RetrievalResult]:
        """Layer 1 + Layer 2 基础检索"""
        if self._faiss_index is None or self._faiss_index.ntotal == 0:
            return []
        candidates = self._vector_search(query_text, top_k=recall_k)
        if not candidates:
            return []
        if use_reranker and len(candidates) > 1:
            candidates = self._rerank(query_text, candidates, top_k=min(10, len(candidates)))
        return candidates

    def _base_to_enhanced(self, result: RetrievalResult) -> EnhancedRetrievalResult:
        """RetrievalResult → EnhancedRetrievalResult"""
        idx = self._chunk_id_to_idx.get(result.conversation_id)
        meta = self._enriched_metadata[idx] if idx is not None else EnrichedChunkMetadata()
        return EnhancedRetrievalResult(
            chunk_id=result.conversation_id,
            conversation_text=result.conversation_text,
            metadata=meta,
            semantic_score=result.score,
            analysis_summary=self._fmt_summary(meta.analysis),
        )

    def _apply_multidim_scoring(
        self,
        results: list[EnhancedRetrievalResult],
        query_days: list[int],
        query_emotion: str,
        time_filter: Optional[str],
        emotion_filter: Optional[str],
        topic_filter: Optional[str],
        top_k: int,
    ) -> list[EnhancedRetrievalResult]:
        """Layer 3: 过滤 + 多维评分"""
        filtered = []
        for r in results:
            if time_filter and not self._pass_time_filter(r.metadata, time_filter):
                continue
            if emotion_filter and r.metadata.chunk_type != emotion_filter:
                continue
            if topic_filter:
                haystack = r.conversation_text
                if r.metadata.analysis:
                    haystack += ' '.join(r.metadata.analysis.key_issues)
                if topic_filter not in haystack:
                    continue
            filtered.append(r)

        for r in filtered:
            r.temporal_score = self._compute_temporal_score(r.metadata.days, query_days)
            r.emotional_score = self._compute_emotional_score(r.metadata, query_emotion)
            sem = min(max(r.semantic_score, 0.0), 1.0)
            r.final_score = (
                sem * self.WEIGHT_SEMANTIC
                + r.temporal_score * self.WEIGHT_TEMPORAL
                + r.emotional_score * self.WEIGHT_EMOTIONAL
            )

        filtered.sort(key=lambda r: r.final_score, reverse=True)
        return filtered[:top_k]

    def _pass_time_filter(self, meta: EnrichedChunkMetadata, tf: str) -> bool:
        """时间过滤"""
        if tf == 'recent':
            return bool(meta.days) and max(meta.days) >= self._max_day - 30
        if tf.startswith('day_'):
            try:
                return int(tf.split('_')[1]) in meta.days
            except (ValueError, IndexError):
                return True
        if tf.startswith('days_'):
            try:
                s, e = tf.split('_')[1].split('-')
                return any(int(s) <= d <= int(e) for d in meta.days)
            except (ValueError, IndexError):
                return True
        return True

    def _compute_temporal_score(self, chunk_days: list[int], query_days: list[int]) -> float:
        """时间相关性: 精确匹配→1.0, 距离衰减, 越近越高"""
        if not chunk_days:
            return 0.3
        if query_days:
            if set(chunk_days) & set(query_days):
                return 1.0
            min_dist = min(abs(cd - qd) for cd in chunk_days for qd in query_days)
            return max(0.1, float(np.exp(-min_dist / 10.0)))
        if self._max_day > 0:
            return 0.3 + 0.7 * (max(chunk_days) / self._max_day)
        return 0.5

    @staticmethod
    def _compute_emotional_score(meta: EnrichedChunkMetadata, query_emotion: str) -> float:
        """情感匹配: chunk_type + analysis 状态"""
        if not query_emotion:
            return 0.5
        score = 0.3
        type_map = {'conflict': ['conflict', 'sad', 'anxious'], 'sweet': ['sweet']}
        if query_emotion in type_map.get(meta.chunk_type, []):
            score += 0.4
        if meta.analysis:
            st = meta.analysis.relationship_status
            rl = meta.analysis.risk_level
            if query_emotion == 'conflict' and ('冲突' in st or '高' in rl):
                score += 0.3
            elif query_emotion == 'sweet' and ('甜蜜' in st or '稳定' in st):
                score += 0.3
            elif query_emotion in ('sad', 'anxious') and ('冲突' in st or '冷' in st):
                score += 0.2
        return min(score, 1.0)

    @staticmethod
    def _fmt_summary(analysis: Optional[ChunkAnalysis]) -> str:
        """格式化分析摘要 (简短版)"""
        if not analysis:
            return ''
        def _s(v, maxlen=20):
            if isinstance(v, str):
                return v[:maxlen]
            if isinstance(v, dict):
                return str(v.get('level', v.get('summary', str(v))))[:maxlen]
            return str(v)[:maxlen] if v else ''
        parts = []
        if analysis.relationship_status:
            parts.append(f'状态:{_s(analysis.relationship_status)}')
        if analysis.risk_level:
            parts.append(f'风险:{_s(analysis.risk_level)}')
        if analysis.communication_quality:
            parts.append(f'沟通:{_s(analysis.communication_quality)}')
        if analysis.key_issues:
            first = analysis.key_issues[0] if isinstance(analysis.key_issues, list) else str(analysis.key_issues)
            parts.append(f'核心:{_s(first, 30)}...')
        return ' | '.join(parts)


# =============================================================================
# CLI
# =============================================================================

if __name__ == '__main__':
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    import argparse

    parser = argparse.ArgumentParser(description='ChunkAwareRAG')
    parser.add_argument('--chunks', default='advisor_out/chunks/conversation_chunks.jsonl')
    parser.add_argument('--analysis', default='advisor_out/analysis/fused_analysis_neutral_moa.jsonl')
    parser.add_argument('--index-dir', default='advisor_out/vector_index')
    parser.add_argument('--query', type=str, help='语义检索')
    parser.add_argument('--day', type=int, help='按天数检索')
    parser.add_argument('--day-range', type=str, help='日期范围 e.g. 100-120')
    parser.add_argument('--build', action='store_true', help='重建索引')
    parser.add_argument('--no-gpu', action='store_true')
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(levelname)s %(message)s')

    config = {
        'index_dir': args.index_dir,
        'embedding_model': '/data/models/bge-m3',
        'use_gpu_for_embedding': not args.no_gpu,
    }
    rag = ChunkAwareRAG(config)

    if args.build:
        rag.build_enriched_index(args.chunks, args.analysis)
        rag.save_index()
        rag.unload_models()
        print(f"\n索引已保存到 {args.index_dir}")
    else:
        if not rag.load_index():
            print("索引不存在，请先 --build")
            exit(1)

        if args.day:
            print(f"\n=== 按日期检索: 第{args.day}天 ===")
            for r in rag.query_by_day(args.day):
                print(f"  {r.chunk_id} [{r.metadata.chunk_type}] {r.analysis_summary}")
                print(f"  对话: {r.conversation_text[:200]}...")
                for a in rag.find_cross_day_associations(r.chunk_id):
                    print(f"  → {a['chunk_id']}: {a['reason']}")

        if args.day_range:
            s, e = args.day_range.split('-')
            print(f"\n=== 日期范围: 第{s}~第{e}天 ===")
            for r in rag.query_by_day_range(int(s), int(e)):
                ds = ','.join(str(d) for d in r.metadata.days)
                print(f"  {r.chunk_id} [第{ds}天] [{r.metadata.chunk_type}] {r.analysis_summary}")

        if args.query:
            print(f"\n=== 多维检索: {args.query} ===")
            rag._load_embedding_model()
            results = rag.query_enhanced(args.query, top_k=5)
            for i, r in enumerate(results, 1):
                ds = ','.join(str(d) for d in r.metadata.days) if r.metadata.days else '?'
                print(f"\n  {i}. {r.chunk_id} [第{ds}天] [{r.metadata.chunk_type}]")
                print(f"     分数: final={r.final_score:.3f} sem={r.semantic_score:.3f} "
                      f"tmp={r.temporal_score:.3f} emo={r.emotional_score:.3f}")
                print(f"     {r.analysis_summary}")

            print(f"\n=== 组装上下文 ===")
            print(rag.assemble_context(results))
            rag.unload_models()
