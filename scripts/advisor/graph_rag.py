"""
GraphRAG 知识层管理器模块

功能：
- 基于 BGE-M3 嵌入模型 + FAISS 向量索引 + BGE-Reranker-V2-M3 重排的检索系统
- 为对话分析提供历史上下文检索能力
- 支持索引构建、增量更新、语义查询和模型卸载
- 单 GPU (RTX 5070 Ti 16GB) 串行执行：嵌入模型与 LLM 不同时加载

处理流程：
1. build_index(): 加载 BGE-M3 → 对所有对话文本计算嵌入 → 构建 FAISS 索引
2. query_related(): 查询文本嵌入 → FAISS 召回 top-20 → BGE-Reranker 重排 → 返回 top-5
3. unload_models(): 卸载嵌入模型和重排模型 → 清理 GPU 显存

输入：
- 对话文本列表（用于构建索引）
- 查询文本（用于检索）

输出：
- 检索结果列表（包含相似对话文本和相似度分数）

依赖：
- sentence-transformers: BGE-M3 嵌入模型加载
- faiss-gpu / faiss-cpu: 向量索引
- torch: GPU 显存管理

使用示例：
    from scripts.advisor.graph_rag import GraphRAGManager
    
    manager = GraphRAGManager(config)
    manager.build_index(conversations)
    results = manager.query_related("最近又吵架了")
    manager.unload_models()  # 用完必须卸载，释放显存给 LLM

性能参考（RTX 5070 Ti 16GB）：
- BGE-M3 显存占用：约 2GB
- 索引构建速度：约 100 条/秒
- 查询+重排延迟：约 200-500ms

注意事项：
- 使用完毕后必须调用 unload_models() 释放显存
- 索引支持保存到磁盘和从磁盘加载（save_index/load_index）
- 嵌入模型和重排模型延迟加载，首次查询时自动初始化

作者：forcifer
更新于：2026-02-15
"""

import gc
import json
import logging
import os
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


# =============================================================================
# 数据结构
# =============================================================================

@dataclass
class RetrievalResult:
    """单条检索结果"""
    conversation_id: str = ''
    conversation_text: str = ''
    timestamp: str = ''
    score: float = 0.0
    metadata: dict = field(default_factory=dict)


@dataclass
class UserProfile:
    """跨会话长期用户档案"""
    total_conversations: int = 0
    date_range: tuple[str, str] = ('', '')
    recurring_topics: list[str] = field(default_factory=list)
    recurring_conflicts: list[str] = field(default_factory=list)
    relationship_trend: str = ''  # improving / declining / stable
    top_emotions: list[str] = field(default_factory=list)
    communication_style_me: str = ''
    communication_style_other: str = ''
    last_updated: str = ''


@dataclass
class ContextSummary:
    """长期上下文摘要"""
    related_history: list[RetrievalResult] = field(default_factory=list)
    pattern_summary: str = ''
    topic_evolution: str = ''


# =============================================================================
# GraphRAGManager
# =============================================================================

class GraphRAGManager:
    """
    GraphRAG 知识层管理器
    
    第一阶段实现：纯向量库
    - BGE-M3 (BAAI/bge-m3) dense embedding
    - FAISS IndexFlatIP (cosine similarity via L2-normalized vectors)
    - BGE-Reranker-V2-M3 重排
    - 增量更新（无需全量重建）
    - 跨会话用户档案
    """
    
    def __init__(self, config: Optional[dict] = None):
        config = config or {}
        
        # 模型配置
        self.embedding_model_name = config.get('embedding_model', '/data/models/bge-m3')
        self.reranker_model_name = config.get('reranker_model', '/data/models/bge-reranker-v2-m3')
        
        # 索引配置
        self.index_dir = Path(config.get('index_dir', 'data/advisor/faiss_index'))
        self.top_k_retrieval = config.get('top_k_retrieval', 20)
        self.top_k_rerank = config.get('top_k_rerank', 5)
        self.use_gpu = config.get('use_gpu_for_embedding', True)
        
        # 内部状态
        self._embedding_model = None
        self._reranker = None
        self._faiss_index = None
        self._conversations: list[dict] = []  # 元数据存储
        self._embedding_dim: int = 0
        self._user_profile: Optional[UserProfile] = None
    
    # =========================================================================
    # 索引构建
    # =========================================================================
    
    def build_index(self, conversations: list[dict], show_progress: bool = True):
        """
        从对话列表构建向量索引
        
        Args:
            conversations: 对话列表，每个对话需含 conversation_text 字段，
                          可选 conversation_id, timestamp, metadata
            show_progress: 是否显示 tqdm 进度条
        """
        import faiss
        
        if not conversations:
            logger.warning("空对话列表，跳过索引构建")
            return
        
        logger.info(f"开始构建向量索引，共 {len(conversations)} 条对话")
        
        # 加载嵌入模型
        self._load_embedding_model()
        
        # 提取文本
        texts = [conv.get('conversation_text', '') for conv in conversations]
        
        # 批量编码
        embeddings = self._encode_texts(texts, show_progress=show_progress)
        
        if embeddings is None or len(embeddings) == 0:
            logger.error("嵌入编码失败")
            return
        
        # L2 归一化（cosine similarity via inner product）
        faiss.normalize_L2(embeddings)
        
        # 构建 FAISS 索引
        self._embedding_dim = embeddings.shape[1]
        self._faiss_index = faiss.IndexFlatIP(self._embedding_dim)
        self._faiss_index.add(embeddings)
        
        # 存储元数据
        self._conversations = []
        for i, conv in enumerate(conversations):
            self._conversations.append({
                'conversation_id': conv.get('conversation_id', f'conv_{i}'),
                'conversation_text': conv.get('conversation_text', ''),
                'timestamp': conv.get('timestamp', ''),
                'metadata': conv.get('metadata', {}),
            })
        
        # 构建用户档案
        self._user_profile = self._build_user_profile(conversations)
        
        logger.info(
            f"索引构建完成：{self._faiss_index.ntotal} 条向量，"
            f"维度 {self._embedding_dim}"
        )
    
    def update_index(self, new_conversations: list[dict], show_progress: bool = True):
        """
        增量更新索引（无需全量重建）
        
        Args:
            new_conversations: 新增对话列表
            show_progress: 是否显示进度条
        """
        import faiss
        
        if not new_conversations:
            return
        
        logger.info(f"增量更新索引，新增 {len(new_conversations)} 条对话")
        
        # 确保嵌入模型已加载
        self._load_embedding_model()
        
        # 编码新文本
        texts = [conv.get('conversation_text', '') for conv in new_conversations]
        new_embeddings = self._encode_texts(texts, show_progress=show_progress)
        
        if new_embeddings is None or len(new_embeddings) == 0:
            logger.error("新文本嵌入编码失败")
            return
        
        faiss.normalize_L2(new_embeddings)
        
        # 如果索引不存在，创建新索引
        if self._faiss_index is None:
            self._embedding_dim = new_embeddings.shape[1]
            self._faiss_index = faiss.IndexFlatIP(self._embedding_dim)
        
        # 追加到索引
        self._faiss_index.add(new_embeddings)
        
        # 追加元数据
        base_idx = len(self._conversations)
        for i, conv in enumerate(new_conversations):
            self._conversations.append({
                'conversation_id': conv.get('conversation_id', f'conv_{base_idx + i}'),
                'conversation_text': conv.get('conversation_text', ''),
                'timestamp': conv.get('timestamp', ''),
                'metadata': conv.get('metadata', {}),
            })
        
        # 更新用户档案
        self._user_profile = self._build_user_profile(self._conversations)
        
        logger.info(f"索引更新完成：总计 {self._faiss_index.ntotal} 条向量")
    
    # =========================================================================
    # 检索
    # =========================================================================
    
    def query_related(
        self,
        query_text: str,
        top_k: Optional[int] = None,
        use_reranker: bool = True,
    ) -> list[RetrievalResult]:
        """
        向量检索 + 重排，返回相关历史对话
        
        Args:
            query_text: 查询文本
            top_k: 最终返回数量（默认使用配置值）
            use_reranker: 是否使用重排器
        
        Returns:
            排序后的检索结果列表
        """
        if self._faiss_index is None or self._faiss_index.ntotal == 0:
            logger.warning("索引为空，无法检索")
            return []
        
        top_k = top_k or self.top_k_rerank
        recall_k = self.top_k_retrieval
        
        # 阶段一：向量召回
        candidates = self._vector_search(query_text, top_k=recall_k)
        
        if not candidates:
            return []
        
        # 阶段二：重排
        if use_reranker and len(candidates) > 1:
            candidates = self._rerank(query_text, candidates, top_k=top_k)
        else:
            candidates = candidates[:top_k]
        
        return candidates
    
    def query_fast(
        self,
        query_text: str,
        top_k: int = 5,
    ) -> list[RetrievalResult]:
        """
        快速向量检索（< 100ms），供 listen 模式使用
        不加载重排器，纯 FAISS 检索
        
        Args:
            query_text: 查询文本
            top_k: 返回数量
        
        Returns:
            检索结果列表
        """
        return self._vector_search(query_text, top_k=top_k)
    
    # =========================================================================
    # 上下文与档案
    # =========================================================================
    
    def generate_context_summary(
        self,
        current_conversation: str,
        top_k: int = 5,
    ) -> ContextSummary:
        """
        为当前对话生成长期上下文摘要
        
        Args:
            current_conversation: 当前对话文本
            top_k: 检索相关历史数量
        
        Returns:
            ContextSummary 对象
        """
        summary = ContextSummary()
        
        # 检索相关历史
        related = self.query_related(current_conversation, top_k=top_k)
        summary.related_history = related
        
        # 生成模式摘要
        if related:
            topics = []
            for r in related:
                topics.extend(self._extract_topics(r.conversation_text))
            topic_counts = Counter(topics)
            top_topics = [t for t, _ in topic_counts.most_common(5)]
            summary.pattern_summary = (
                f"相关历史中反复出现的话题：{', '.join(top_topics)}"
                if top_topics else "未检测到明显模式"
            )
        
        # 话题演变
        if len(related) >= 2:
            sorted_results = sorted(
                [r for r in related if r.timestamp],
                key=lambda r: r.timestamp,
            )
            if sorted_results:
                first_topics = set(self._extract_topics(sorted_results[0].conversation_text))
                last_topics = set(self._extract_topics(sorted_results[-1].conversation_text))
                new_topics = last_topics - first_topics
                gone_topics = first_topics - last_topics
                parts = []
                if new_topics:
                    parts.append(f"新出现：{', '.join(new_topics)}")
                if gone_topics:
                    parts.append(f"已消退：{', '.join(gone_topics)}")
                summary.topic_evolution = '；'.join(parts) if parts else "话题基本稳定"
        
        return summary
    
    def get_user_profile(self) -> Optional[UserProfile]:
        """
        获取跨会话长期用户档案
        
        Returns:
            UserProfile 对象，索引为空时返回 None
        """
        return self._user_profile
    
    # =========================================================================
    # 持久化
    # =========================================================================
    
    def save_index(self, path: Optional[str] = None):
        """
        保存索引和元数据到磁盘
        
        Args:
            path: 保存目录（默认使用 self.index_dir）
        """
        import faiss
        
        save_dir = Path(path) if path else self.index_dir
        save_dir.mkdir(parents=True, exist_ok=True)
        
        if self._faiss_index is None:
            logger.warning("索引为空，跳过保存")
            return
        
        # 保存 FAISS 索引
        faiss.write_index(self._faiss_index, str(save_dir / 'index.faiss'))
        
        # 保存元数据
        meta = {
            'conversations': self._conversations,
            'embedding_dim': self._embedding_dim,
            'embedding_model': self.embedding_model_name,
            'total_vectors': self._faiss_index.ntotal,
            'saved_at': datetime.now().isoformat(),
        }
        with open(save_dir / 'metadata.json', 'w', encoding='utf-8') as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        
        # 保存用户档案
        if self._user_profile:
            profile_dict = {
                'total_conversations': self._user_profile.total_conversations,
                'date_range': list(self._user_profile.date_range),
                'recurring_topics': self._user_profile.recurring_topics,
                'recurring_conflicts': self._user_profile.recurring_conflicts,
                'relationship_trend': self._user_profile.relationship_trend,
                'top_emotions': self._user_profile.top_emotions,
                'communication_style_me': self._user_profile.communication_style_me,
                'communication_style_other': self._user_profile.communication_style_other,
                'last_updated': self._user_profile.last_updated,
            }
            with open(save_dir / 'user_profile.json', 'w', encoding='utf-8') as f:
                json.dump(profile_dict, f, ensure_ascii=False, indent=2)
        
        logger.info(f"索引已保存到 {save_dir}（{self._faiss_index.ntotal} 条向量）")
    
    def load_index(self, path: Optional[str] = None) -> bool:
        """
        从磁盘加载索引和元数据
        
        Args:
            path: 加载目录（默认使用 self.index_dir）
        
        Returns:
            是否加载成功
        """
        import faiss
        
        load_dir = Path(path) if path else self.index_dir
        
        index_file = load_dir / 'index.faiss'
        meta_file = load_dir / 'metadata.json'
        
        if not index_file.exists() or not meta_file.exists():
            logger.warning(f"索引文件不存在：{load_dir}")
            return False
        
        # 加载 FAISS 索引
        self._faiss_index = faiss.read_index(str(index_file))
        
        # 加载元数据
        with open(meta_file, 'r', encoding='utf-8') as f:
            meta = json.load(f)
        
        self._conversations = meta.get('conversations', [])
        self._embedding_dim = meta.get('embedding_dim', 0)
        
        # 加载用户档案
        profile_file = load_dir / 'user_profile.json'
        if profile_file.exists():
            with open(profile_file, 'r', encoding='utf-8') as f:
                p = json.load(f)
            self._user_profile = UserProfile(
                total_conversations=p.get('total_conversations', 0),
                date_range=tuple(p.get('date_range', ['', ''])),
                recurring_topics=p.get('recurring_topics', []),
                recurring_conflicts=p.get('recurring_conflicts', []),
                relationship_trend=p.get('relationship_trend', ''),
                top_emotions=p.get('top_emotions', []),
                communication_style_me=p.get('communication_style_me', ''),
                communication_style_other=p.get('communication_style_other', ''),
                last_updated=p.get('last_updated', ''),
            )
        
        logger.info(
            f"索引已加载：{self._faiss_index.ntotal} 条向量，"
            f"{len(self._conversations)} 条元数据"
        )
        return True
    
    # =========================================================================
    # 模型管理（单 GPU 串行）
    # =========================================================================
    
    def _load_embedding_model(self):
        """加载 BGE-M3 嵌入模型"""
        if self._embedding_model is not None:
            return
        
        logger.info(f"加载嵌入模型：{self.embedding_model_name}")
        
        try:
            from FlagEmbedding import BGEM3FlagModel
        except ImportError:
            raise ImportError(
                "FlagEmbedding 未安装，请运行：pip install FlagEmbedding"
            )
        
        self._embedding_model = BGEM3FlagModel(
            self.embedding_model_name,
            use_fp16=True,
            device='cuda' if self.use_gpu else 'cpu',
        )
        
        logger.info("嵌入模型加载完成")
    
    def _load_reranker(self):
        """加载 BGE-Reranker-V2-M3"""
        if self._reranker is not None:
            return
        
        logger.info(f"加载重排模型：{self.reranker_model_name}")
        
        try:
            from FlagEmbedding import FlagReranker
        except ImportError:
            raise ImportError(
                "FlagEmbedding 未安装，请运行：pip install FlagEmbedding"
            )
        
        self._reranker = FlagReranker(
            self.reranker_model_name,
            use_fp16=True,
            device='cuda' if self.use_gpu else 'cpu',
        )
        
        logger.info("重排模型加载完成")
    
    def unload_embedding_model(self):
        """卸载嵌入模型释放显存"""
        if self._embedding_model is not None:
            del self._embedding_model
            self._embedding_model = None
            self._gpu_cleanup()
            logger.info("嵌入模型已卸载")
    
    def unload_reranker(self):
        """卸载重排模型释放显存"""
        if self._reranker is not None:
            del self._reranker
            self._reranker = None
            self._gpu_cleanup()
            logger.info("重排模型已卸载")
    
    def unload_models(self):
        """卸载所有模型释放显存（单 GPU 串行策略：用完必须调用）"""
        self.unload_embedding_model()
        self.unload_reranker()
    
    @staticmethod
    def _gpu_cleanup():
        """GPU 显存清理"""
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
        except ImportError:
            pass
    
    # =========================================================================
    # 内部方法
    # =========================================================================
    
    def _encode_texts(
        self,
        texts: list[str],
        show_progress: bool = True,
        batch_size: int = 32,
    ) -> Optional[np.ndarray]:
        """
        使用 BGE-M3 编码文本为 dense embedding
        
        Args:
            texts: 文本列表
            show_progress: 是否显示进度条
            batch_size: 编码批次大小
        
        Returns:
            numpy array of shape (n, dim), float32
        """
        if self._embedding_model is None:
            logger.error("嵌入模型未加载")
            return None
        
        try:
            result = self._embedding_model.encode(
                texts,
                batch_size=batch_size,
                max_length=8192,
                return_dense=True,
                return_sparse=False,
                return_colbert_vecs=False,
            )
            # BGE-M3 返回 dict: {'dense_vecs': ndarray}
            embeddings = result['dense_vecs']
            return embeddings.astype(np.float32)
        except Exception as e:
            logger.error(f"文本编码失败：{e}")
            return None
    
    def _vector_search(
        self,
        query_text: str,
        top_k: int = 20,
    ) -> list[RetrievalResult]:
        """
        纯 FAISS 向量检索
        
        Args:
            query_text: 查询文本
            top_k: 返回数量
        
        Returns:
            检索结果列表（按相似度降序）
        """
        import faiss
        
        if self._faiss_index is None or self._faiss_index.ntotal == 0:
            return []
        
        # 确保嵌入模型已加载
        self._load_embedding_model()
        
        # 编码查询
        query_embedding = self._encode_texts([query_text], show_progress=False)
        if query_embedding is None:
            return []
        
        faiss.normalize_L2(query_embedding)
        
        # 检索
        actual_k = min(top_k, self._faiss_index.ntotal)
        scores, indices = self._faiss_index.search(query_embedding, actual_k)
        
        # 构建结果
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0 or idx >= len(self._conversations):
                continue
            conv = self._conversations[idx]
            results.append(RetrievalResult(
                conversation_id=conv.get('conversation_id', ''),
                conversation_text=conv.get('conversation_text', ''),
                timestamp=conv.get('timestamp', ''),
                score=float(score),
                metadata=conv.get('metadata', {}),
            ))
        
        return results
    
    def _rerank(
        self,
        query_text: str,
        candidates: list[RetrievalResult],
        top_k: int = 5,
    ) -> list[RetrievalResult]:
        """
        使用 BGE-Reranker-V2-M3 对候选结果重排
        
        Args:
            query_text: 查询文本
            candidates: 候选结果列表
            top_k: 最终返回数量
        
        Returns:
            重排后的结果列表
        """
        if not candidates:
            return []
        
        # 加载重排器
        self._load_reranker()
        
        if self._reranker is None:
            logger.warning("重排器加载失败，返回原始排序")
            return candidates[:top_k]
        
        # 构建 query-passage pairs
        pairs = [
            [query_text, c.conversation_text]
            for c in candidates
        ]
        
        try:
            rerank_scores = self._reranker.compute_score(
                pairs,
                normalize=True,
            )
            
            # compute_score 可能返回单个 float 或 list
            if isinstance(rerank_scores, (int, float)):
                rerank_scores = [rerank_scores]
            
            # 用重排分数替换原始分数
            for candidate, score in zip(candidates, rerank_scores):
                candidate.score = float(score)
            
            # 按重排分数降序排列
            candidates.sort(key=lambda c: c.score, reverse=True)
            
        except Exception as e:
            logger.error(f"重排失败：{e}，返回原始排序")
        
        return candidates[:top_k]
    
    # =========================================================================
    # 用户档案
    # =========================================================================
    
    def _build_user_profile(self, conversations: list[dict]) -> UserProfile:
        """从对话集合构建用户档案"""
        profile = UserProfile()
        profile.total_conversations = len(conversations)
        profile.last_updated = datetime.now().isoformat()
        
        # 时间范围
        timestamps = [
            c.get('timestamp', '') for c in conversations if c.get('timestamp')
        ]
        if timestamps:
            sorted_ts = sorted(timestamps)
            profile.date_range = (sorted_ts[0], sorted_ts[-1])
        
        # 话题和冲突统计
        topic_counter = Counter()
        conflict_counter = Counter()
        emotion_counter = Counter()
        
        for conv in conversations:
            text = conv.get('conversation_text', '')
            topics = self._extract_topics(text)
            topic_counter.update(topics)
            
            if self._has_conflict(text):
                conflicts = self._extract_topics(text)
                conflict_counter.update(conflicts)
            
            emotions = self._extract_emotions(text)
            emotion_counter.update(emotions)
        
        profile.recurring_topics = [
            t for t, c in topic_counter.most_common(5) if c >= 2
        ]
        profile.recurring_conflicts = [
            t for t, c in conflict_counter.most_common(3) if c >= 2
        ]
        profile.top_emotions = [
            e for e, _ in emotion_counter.most_common(5)
        ]
        
        # 关系趋势
        profile.relationship_trend = self._compute_trend(conversations)
        
        # 沟通风格
        me_style, other_style = self._detect_communication_styles(conversations)
        profile.communication_style_me = me_style
        profile.communication_style_other = other_style
        
        return profile
    
    # =========================================================================
    # 文本分析辅助
    # =========================================================================
    
    _TOPIC_KEYWORDS = {
        '工作': ['工作', '上班', '加班', '公司', '老板', '同事', '项目', '面试', '录取'],
        '家庭': ['家', '父母', '妈', '爸', '孩子', '婆婆', '公公', '家里'],
        '金钱': ['钱', '买', '花', '存', '贵', '借', '还'],
        '感情': ['爱', '喜欢', '想', '在乎', '心疼', '舍不得'],
        '生活': ['吃', '睡', '玩', '出去', '旅游', '做饭'],
        '未来': ['以后', '将来', '计划', '打算', '结婚', '房子'],
        '社交': ['朋友', '聚会', '饭局', '同学', '闺蜜', '兄弟'],
        '健康': ['身体', '累', '病', '头疼', '失眠', '压力'],
        # 多模态信号话题
        '情绪波动': ['情绪:ANGRY', '情绪:SAD', '情绪:FEARFUL', '情绪:DISGUSTED',
                    '氛围:紧张', '氛围:压抑'],
        '亲密互动': ['撒娇', '卖萌', '开心/高兴', '氛围:温馨', '氛围:浪漫',
                    '氛围:欢乐', '表达爱意'],
        '冷暴力信号': ['cold_period', '长时间未回复', '情绪:冷淡'],
    }
    
    _CONFLICT_INDICATORS = [
        '生气', '烦', '吵', '闹', '不理', '分手',
        '你怎么', '你为什么', '凭什么', '受不了', '够了',
        # 多模态冲突信号
        '情绪:ANGRY', '氛围:紧张', '氛围:压抑',
        'argument_gap', '伤人',
    ]
    
    _EMOTION_KEYWORDS = {
        '开心': ['开心', '高兴', '快乐', '幸福', '哈哈', '嘻嘻', '情绪:HAPPY'],
        '生气': ['生气', '愤怒', '烦', '气死', '火大', '情绪:ANGRY'],
        '伤心': ['伤心', '难过', '哭', '心痛', '委屈', '情绪:SAD'],
        '焦虑': ['担心', '焦虑', '紧张', '害怕', '不安', '情绪:FEARFUL'],
        '甜蜜': ['爱你', '想你', '宝贝', '亲爱的', '抱抱', '氛围:温馨', '氛围:浪漫'],
        '冷淡': ['随便', '无所谓', '都行', '不想说', '算了', 'cold_period'],
    }
    
    @classmethod
    def _extract_topics(cls, text: str) -> list[str]:
        """提取话题"""
        topics = []
        for topic, keywords in cls._TOPIC_KEYWORDS.items():
            if any(kw in text for kw in keywords):
                topics.append(topic)
        return topics
    
    @classmethod
    def _has_conflict(cls, text: str) -> bool:
        """检测是否有冲突"""
        return any(ind in text for ind in cls._CONFLICT_INDICATORS)
    
    @classmethod
    def _extract_emotions(cls, text: str) -> list[str]:
        """提取情绪"""
        emotions = []
        for emotion, keywords in cls._EMOTION_KEYWORDS.items():
            if any(kw in text for kw in keywords):
                emotions.append(emotion)
        return emotions
    
    @classmethod
    def _compute_trend(cls, conversations: list[dict]) -> str:
        """计算关系趋势"""
        if len(conversations) < 3:
            return 'stable'
        
        positive_words = ['爱', '喜欢', '开心', '幸福', '甜', '想你', '宝贝']
        negative_words = ['烦', '累', '生气', '讨厌', '分手', '不想', '算了']
        
        mid = len(conversations) // 2
        
        def sentiment(convs):
            pos = neg = 0
            for c in convs:
                text = c.get('conversation_text', '')
                pos += sum(1 for w in positive_words if w in text)
                neg += sum(1 for w in negative_words if w in text)
            return pos - neg
        
        first_score = sentiment(conversations[:mid])
        second_score = sentiment(conversations[mid:])
        diff = second_score - first_score
        
        if diff > 3:
            return 'improving'
        elif diff < -3:
            return 'declining'
        return 'stable'
    
    @staticmethod
    def _detect_communication_styles(conversations: list[dict]) -> tuple[str, str]:
        """检测 ME 和 OTHER 的沟通风格"""
        me_lengths = []
        other_lengths = []
        me_emoji = 0
        other_emoji = 0
        
        import re
        emoji_pattern = re.compile(
            r'[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF]'
        )
        
        for conv in conversations:
            text = conv.get('conversation_text', '')
            for line in text.split('\n'):
                line = line.strip()
                if line.startswith('ME:'):
                    content = line[3:].strip()
                    me_lengths.append(len(content))
                    me_emoji += len(emoji_pattern.findall(content))
                elif line.startswith('OTHER:'):
                    content = line[6:].strip()
                    other_lengths.append(len(content))
                    other_emoji += len(emoji_pattern.findall(content))
        
        def style_label(lengths, emoji_count):
            if not lengths:
                return '未知'
            avg_len = sum(lengths) / len(lengths)
            emoji_ratio = emoji_count / max(len(lengths), 1)
            parts = []
            if avg_len > 50:
                parts.append('长文本型')
            elif avg_len < 10:
                parts.append('简短回复型')
            else:
                parts.append('适中型')
            if emoji_ratio > 0.3:
                parts.append('表情丰富')
            return '，'.join(parts)
        
        return style_label(me_lengths, me_emoji), style_label(other_lengths, other_emoji)
