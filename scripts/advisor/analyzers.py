"""
辅助分析组件模块

功能：
- 提供 5 个独立的分析器，从不同维度深入分析对话数据：
  1. ResponseTimeAnalyzer — 回复时间分析：计算双方回复速度、检测冷暴力和争吵模式
  2. ConflictRootCauseAnalyzer — 冲突根源分析：从 10 种根源中识别适用的冲突原因
  3. LongTermContextAnalyzer — 长期上下文分析：基于 GraphRAG 的历史模式识别和语义聚类
  4. NeutralityChecker — 中立性检查：评估分析文本的客观性和双方批评平衡度
  5. PsychoanalyticDetector — 精神分析检测：依附风格、防御机制、拉康三界分析

处理流程：
- ResponseTimeAnalyzer: 解析时间戳 → 计算回复间隔 → 检测冷暴力/争吵模式
- ConflictRootCauseAnalyzer: 关键词匹配 → 10 种根源评分 → 返回 top 3
- LongTermContextAnalyzer: GraphRAG 索引构建 → 语义检索 → 聚类分析 → 趋势判断
- NeutralityChecker: 情感词统计 → 偏向性评分 → 平衡度计算
- PsychoanalyticDetector: 依附关键词匹配 → 防御机制识别 → 拉康三界分析

输入：
- 消息列表（list[dict]）：包含 speaker, time, text_raw, emotion_tags 等字段
- 分析文本（str）：NeutralityChecker 的输入

输出：
- 各分析器返回对应的 dataclass 结果对象

依赖：
- scripts.advisor.graph_rag: GraphRAGManager（LongTermContextAnalyzer 使用）
- datetime: 时间戳解析
- collections: Counter, defaultdict

使用示例：
    from scripts.advisor.analyzers import (
        ResponseTimeAnalyzer,
        ConflictRootCauseAnalyzer,
        LongTermContextAnalyzer,
        NeutralityChecker,
        PsychoanalyticDetector,
    )
    
    # 回复时间分析
    rta = ResponseTimeAnalyzer()
    stats = rta.analyze(messages)
    print(f"冷暴力检测: {stats.cold_treatment_detected}")
    
    # 冲突根源分析
    cra = ConflictRootCauseAnalyzer()
    analysis = cra.analyze(messages)
    print(f"冲突根源: {analysis.root_causes}")
    
    # 中立性检查
    nc = NeutralityChecker()
    score = nc.check(analysis_text)
    print(f"中立性评分: {score.overall_score}")

注意事项：
- LongTermContextAnalyzer 依赖 GraphRAG，首次使用需要构建索引（耗时较长）
- ResponseTimeAnalyzer 支持多种时间戳格式（ISO 8601, 中文日期等）
- NeutralityChecker 的评分范围 0-1，低于 0.6 建议人工审核
- PsychoanalyticDetector 的分析结果需经 SafetyLayer 处理后才能下发用户

作者：forcifer
更新于：2026-02-15
"""

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional


# =============================================================================
# 回复时间分析器
# =============================================================================

@dataclass
class ResponseTimeStats:
    """回复时间统计结果
    
    ResponseTimeAnalyzer.analyze() 的返回值，包含双方回复速度统计和异常模式检测。
    
    Attributes:
        avg_response_time_me (float): ME 平均回复时间（秒）
        avg_response_time_other (float): OTHER 平均回复时间（秒）
        max_response_time_me (float): ME 最大回复时间（秒）
        max_response_time_other (float): OTHER 最大回复时间（秒）
        response_asymmetry (float): 回复不对称性（正值表示 ME 回复更快）
        cold_treatment_detected (bool): 是否检测到冷暴力模式
        argument_detected (bool): 是否检测到争吵模式
        cold_treatment_periods (list): 冷暴力时段列表
        argument_periods (list): 争吵时段列表
    """
    avg_response_time_me: float = 0.0  # ME 平均回复时间（秒）
    avg_response_time_other: float = 0.0  # OTHER 平均回复时间（秒）
    max_response_time_me: float = 0.0
    max_response_time_other: float = 0.0
    response_asymmetry: float = 0.0  # 回复不对称性（正值表示 ME 回复更快）
    cold_treatment_detected: bool = False  # 是否检测到冷暴力
    argument_detected: bool = False  # 是否检测到争吵
    cold_treatment_periods: list = field(default_factory=list)
    argument_periods: list = field(default_factory=list)


class ResponseTimeAnalyzer:
    """回复时间分析器
    
    分析对话中双方的回复速度模式，检测冷暴力（长时间不回复+冷淡回复）
    和争吵（快速来回+冲突关键词密集）两种异常模式。
    
    Attributes:
        COLD_KEYWORDS (list[str]): 冷暴力特征关键词（如 '哦', '嗯', '随便'）
        ARGUMENT_KEYWORDS (list[str]): 争吵特征关键词（如 '你怎么', '受不了', '分手'）
    
    Example:
        >>> analyzer = ResponseTimeAnalyzer()
        >>> stats = analyzer.analyze(messages)
        >>> if stats.cold_treatment_detected:
        ...     print("检测到冷暴力模式")
    """
    
    # 冷暴力关键词
    COLD_KEYWORDS = ['哦', '嗯', '好', '知道了', '随便', '都行', '无所谓', '你说呢']
    
    # 争吵关键词
    ARGUMENT_KEYWORDS = [
        '你怎么', '你为什么', '你总是', '你从来', '你能不能',
        '烦死了', '受不了', '够了', '别说了', '不想说',
        '你有病', '神经病', '滚', '分手', '离婚',
        '凭什么', '你凭什么', '你算什么', '你以为',
    ]
    
    def __init__(
        self,
        cold_threshold_hours: float = 6.0,  # 冷暴力阈值（小时）
        argument_threshold_minutes: float = 2.0,  # 争吵阈值（分钟）
        min_cold_messages: int = 3,  # 最少连续冷淡消息数
    ):
        """
        初始化分析器
        
        Args:
            cold_threshold_hours: 冷暴力判定的时间阈值（小时）
            argument_threshold_minutes: 争吵判定的快速回复阈值（分钟）
            min_cold_messages: 判定冷暴力需要的最少连续冷淡消息数
        """
        self.cold_threshold = cold_threshold_hours * 3600  # 转换为秒
        self.argument_threshold = argument_threshold_minutes * 60  # 转换为秒
        self.min_cold_messages = min_cold_messages
    
    def analyze(self, messages: list[dict]) -> ResponseTimeStats:
        """
        分析消息列表的回复时间模式
        
        Args:
            messages: 消息列表，每条消息包含 ts, speaker, text_raw 字段
        
        Returns:
            ResponseTimeStats 对象
        """
        stats = ResponseTimeStats()
        
        if len(messages) < 2:
            return stats
        
        # 计算回复时间
        me_response_times = []
        other_response_times = []
        
        for i in range(1, len(messages)):
            prev_msg = messages[i - 1]
            curr_msg = messages[i]
            
            # 跳过系统消息
            if curr_msg.get('type') == 'time_gap' or prev_msg.get('type') == 'time_gap':
                continue
            
            # 计算时间差
            try:
                prev_ts = self._parse_timestamp(prev_msg.get('ts'))
                curr_ts = self._parse_timestamp(curr_msg.get('ts'))
                if prev_ts is None or curr_ts is None:
                    continue
                time_diff = (curr_ts - prev_ts).total_seconds()
            except Exception:
                continue
            
            # 只统计回复（不同说话人）
            prev_speaker = prev_msg.get('speaker', '')
            curr_speaker = curr_msg.get('speaker', '')
            
            if prev_speaker != curr_speaker:
                if curr_speaker == 'ME':
                    me_response_times.append(time_diff)
                else:
                    other_response_times.append(time_diff)
        
        # 计算统计数据
        if me_response_times:
            stats.avg_response_time_me = sum(me_response_times) / len(me_response_times)
            stats.max_response_time_me = max(me_response_times)
        
        if other_response_times:
            stats.avg_response_time_other = sum(other_response_times) / len(other_response_times)
            stats.max_response_time_other = max(other_response_times)
        
        # 计算不对称性
        if stats.avg_response_time_me > 0 and stats.avg_response_time_other > 0:
            stats.response_asymmetry = (
                stats.avg_response_time_other - stats.avg_response_time_me
            ) / max(stats.avg_response_time_me, stats.avg_response_time_other)
        
        # 检测冷暴力
        cold_periods = self._detect_cold_treatment(messages)
        if cold_periods:
            stats.cold_treatment_detected = True
            stats.cold_treatment_periods = cold_periods
        
        # 检测争吵
        argument_periods = self._detect_arguments(messages)
        if argument_periods:
            stats.argument_detected = True
            stats.argument_periods = argument_periods
        
        return stats
    
    def _parse_timestamp(self, ts) -> Optional[datetime]:
        """解析时间戳"""
        if ts is None:
            return None
        if isinstance(ts, datetime):
            return ts
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(ts)
        if isinstance(ts, str):
            # 尝试多种格式
            for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%Y/%m/%d %H:%M:%S']:
                try:
                    return datetime.strptime(ts, fmt)
                except ValueError:
                    continue
        return None
    
    def _is_cold_message(self, text: str) -> bool:
        """判断是否是冷淡消息"""
        if not text:
            return False
        text = text.strip()
        # 短消息且包含冷淡关键词
        if len(text) <= 5 and any(kw in text for kw in self.COLD_KEYWORDS):
            return True
        return False
    
    def _detect_cold_treatment(self, messages: list[dict]) -> list[dict]:
        """检测冷暴力时期"""
        cold_periods = []
        
        i = 0
        while i < len(messages):
            msg = messages[i]
            
            # 跳过系统消息
            if msg.get('type') == 'time_gap':
                i += 1
                continue
            
            # 检查是否是长时间不回复后的冷淡消息
            if i > 0:
                prev_msg = messages[i - 1]
                if prev_msg.get('type') != 'time_gap':
                    try:
                        prev_ts = self._parse_timestamp(prev_msg.get('ts'))
                        curr_ts = self._parse_timestamp(msg.get('ts'))
                        if prev_ts and curr_ts:
                            time_diff = (curr_ts - prev_ts).total_seconds()
                            
                            # 长时间不回复 + 冷淡消息
                            if time_diff > self.cold_threshold:
                                text = msg.get('text_raw', '')
                                if self._is_cold_message(text):
                                    # 检查后续消息是否也是冷淡的
                                    cold_count = 1
                                    speaker = msg.get('speaker')
                                    
                                    for j in range(i + 1, min(i + 10, len(messages))):
                                        next_msg = messages[j]
                                        if next_msg.get('speaker') == speaker:
                                            if self._is_cold_message(next_msg.get('text_raw', '')):
                                                cold_count += 1
                                    
                                    if cold_count >= self.min_cold_messages:
                                        cold_periods.append({
                                            'start_index': i,
                                            'speaker': speaker,
                                            'delay_hours': time_diff / 3600,
                                            'cold_messages': cold_count,
                                        })
                    except Exception:
                        pass
            
            i += 1
        
        return cold_periods
    
    def _detect_arguments(self, messages: list[dict]) -> list[dict]:
        """检测争吵时期"""
        argument_periods = []
        
        i = 0
        while i < len(messages) - 2:
            # 检查快速来回
            rapid_exchange = True
            argument_keywords_found = 0
            
            for j in range(i, min(i + 6, len(messages) - 1)):
                msg = messages[j]
                next_msg = messages[j + 1]
                
                if msg.get('type') == 'time_gap' or next_msg.get('type') == 'time_gap':
                    rapid_exchange = False
                    break
                
                # 检查时间间隔
                try:
                    ts1 = self._parse_timestamp(msg.get('ts'))
                    ts2 = self._parse_timestamp(next_msg.get('ts'))
                    if ts1 and ts2:
                        time_diff = (ts2 - ts1).total_seconds()
                        if time_diff > self.argument_threshold:
                            rapid_exchange = False
                            break
                except Exception:
                    rapid_exchange = False
                    break
                
                # 检查是否是不同说话人
                if msg.get('speaker') == next_msg.get('speaker'):
                    rapid_exchange = False
                    break
                
                # 检查争吵关键词
                text = msg.get('text_raw', '')
                if any(kw in text for kw in self.ARGUMENT_KEYWORDS):
                    argument_keywords_found += 1
            
            if rapid_exchange and argument_keywords_found >= 2:
                argument_periods.append({
                    'start_index': i,
                    'keyword_count': argument_keywords_found,
                })
                i += 6  # 跳过这段争吵
            else:
                i += 1
        
        return argument_periods


# =============================================================================
# 冲突根源分析器
# =============================================================================

@dataclass
class ConflictAnalysis:
    """冲突分析结果
    
    ConflictRootCauseAnalyzer.analyze() 的返回值。
    
    Attributes:
        root_causes (list[str]): 识别到的冲突根源列表（按评分排序，最多 3 个）
        resolution_factors (list[str]): 识别到的缓和因素列表（按评分排序，最多 3 个）
        root_cause_scores (dict): 各冲突根源的评分字典（类别名→分数）
        resolution_scores (dict): 各缓和因素的评分字典（类别名→分数）
    """
    root_causes: list[str] = field(default_factory=list)
    resolution_factors: list[str] = field(default_factory=list)
    root_cause_scores: dict = field(default_factory=dict)
    resolution_scores: dict = field(default_factory=dict)


class ConflictRootCauseAnalyzer:
    """冲突根源分析器
    
    基于关键词匹配从 10 种预定义冲突根源和 8 种缓和因素中
    识别对话中存在的冲突原因和修复尝试。
    
    冲突根源类别：沟通不畅、期望落差、信任危机、价值观冲突、
    时间分配、金钱问题、家庭关系、生活习惯、情感需求、外部压力
    
    缓和因素类别：主动道歉、情感表达、承诺改变、理解共情、
    转移话题、幽默化解、实际行动、冷静期
    
    Example:
        >>> analyzer = ConflictRootCauseAnalyzer()
        >>> result = analyzer.analyze(messages)
        >>> print(f"冲突根源: {result.root_causes}")
    """
    
    # 10 种冲突根源类别及其关键词
    ROOT_CAUSE_PATTERNS = {
        '沟通不畅': ['不说', '不讲', '不告诉', '不沟通', '不理', '不回', '已读不回'],
        '期望落差': ['以为', '本来', '应该', '怎么不', '为什么不', '说好的'],
        '信任危机': ['骗', '撒谎', '不信', '怀疑', '偷偷', '背着', '瞒着'],
        '价值观冲突': ['不理解', '不懂', '不明白', '你觉得', '我觉得', '不同意'],
        '时间分配': ['没时间', '太忙', '加班', '工作', '陪', '等'],
        '金钱问题': ['钱', '花', '买', '贵', '省', '存', '借'],
        '家庭关系': ['父母', '妈', '爸', '婆婆', '公公', '家里人'],
        '生活习惯': ['总是', '每次', '老是', '习惯', '改', '受不了'],
        '情感需求': ['不爱', '不在乎', '不关心', '冷', '敷衍', '不重视'],
        '外部压力': ['压力', '累', '烦', '焦虑', '抑郁', '崩溃'],
    }
    
    # 8 种缓和原因类别及其关键词
    RESOLUTION_PATTERNS = {
        '主动道歉': ['对不起', '抱歉', '是我不好', '我错了', '原谅'],
        '情感表达': ['爱你', '想你', '在乎', '重要', '心疼'],
        '承诺改变': ['以后', '下次', '保证', '一定', '会改'],
        '理解共情': ['理解', '明白', '知道你', '辛苦', '不容易'],
        '转移话题': ['算了', '不说了', '吃饭', '睡觉', '明天'],
        '幽默化解': ['哈哈', '笑', '傻', '可爱', '宝贝'],
        '实际行动': ['买', '做', '去', '陪', '接'],
        '冷静期': ['冷静', '想想', '考虑', '时间'],
    }
    
    def analyze(self, messages: list[dict]) -> ConflictAnalysis:
        """
        分析冲突根源和缓和因素
        
        Args:
            messages: 消息列表
        
        Returns:
            ConflictAnalysis 对象
        """
        result = ConflictAnalysis()
        
        # 统计根源关键词
        root_cause_counts = Counter()
        for msg in messages:
            text = msg.get('text_raw', '')
            for cause, keywords in self.ROOT_CAUSE_PATTERNS.items():
                if any(kw in text for kw in keywords):
                    root_cause_counts[cause] += 1
        
        # 统计缓和关键词
        resolution_counts = Counter()
        for msg in messages:
            text = msg.get('text_raw', '')
            for factor, keywords in self.RESOLUTION_PATTERNS.items():
                if any(kw in text for kw in keywords):
                    resolution_counts[factor] += 1
        
        # 计算得分（归一化）
        total_root = sum(root_cause_counts.values()) or 1
        total_resolution = sum(resolution_counts.values()) or 1
        
        result.root_cause_scores = {
            cause: count / total_root
            for cause, count in root_cause_counts.items()
        }
        result.resolution_scores = {
            factor: count / total_resolution
            for factor, count in resolution_counts.items()
        }
        
        # 提取主要根源和缓和因素
        result.root_causes = [
            cause for cause, score in sorted(
                result.root_cause_scores.items(),
                key=lambda x: x[1],
                reverse=True
            )[:3] if score > 0.1
        ]
        
        result.resolution_factors = [
            factor for factor, score in sorted(
                result.resolution_scores.items(),
                key=lambda x: x[1],
                reverse=True
            )[:3] if score > 0.1
        ]
        
        return result


# =============================================================================
# 长期上下文分析器
# =============================================================================

@dataclass
class LongTermPattern:
    """长期模式分析结果
    
    LongTermContextAnalyzer.analyze_patterns() 的返回值。
    
    Attributes:
        recurring_topics (list[str]): 反复出现的话题列表
        conflict_frequency (float): 冲突频率（0-1）
        trend (str): 关系趋势描述（改善/恶化/稳定）
        semantic_clusters (list[dict]): 语义聚类结果列表
    """
    recurring_topics: list[str] = field(default_factory=list)
    recurring_conflicts: list[str] = field(default_factory=list)
    relationship_trend: str = ''  # 'improving', 'declining', 'stable'
    similar_conversations: list[dict] = field(default_factory=list)


class LongTermContextAnalyzer:
    """长期上下文分析器
    
    基于 GraphRAG（BGE-M3 + FAISS + BGE-Reranker）的历史对话分析器。
    支持语义检索、聚类分析、趋势判断和用户画像生成。
    
    底层使用 GraphRAGManager 替代原有 sentence-transformers 索引，
    支持最大回溯天数配置（默认 3650 天 ≈ 10 年）。
    
    Attributes:
        max_lookback_days (int): 最大回溯天数
        _graph_rag: GraphRAGManager 实例（延迟初始化）
        _conversations (list[dict]): 已索引的对话列表
    
    Example:
        >>> analyzer = LongTermContextAnalyzer({'embedding_model': 'BAAI/bge-m3'})
        >>> analyzer.build_index(conversations)
        >>> similar = analyzer.find_similar("最近总是吵架", top_k=5)
        >>> patterns = analyzer.analyze_patterns(conversations)
    """
    
    def __init__(
        self,
        graph_rag_config: Optional[dict] = None,
        max_lookback_days: int = 3650,
    ):
        """
        初始化分析器
        
        Args:
            graph_rag_config: GraphRAGManager 配置字典（含 embedding_model, 
                             reranker_model, index_dir 等）
            max_lookback_days: 最大回溯天数（默认 3650 = ~10 年）
        """
        self.max_lookback_days = max_lookback_days
        self._graph_rag = None
        self._graph_rag_config = graph_rag_config or {}
        self._conversations: list[dict] = []
    
    def _ensure_graph_rag(self):
        """延迟初始化 GraphRAGManager"""
        if self._graph_rag is None:
            from .graph_rag import GraphRAGManager
            self._graph_rag = GraphRAGManager(self._graph_rag_config)
        return True
    
    def build_index(self, conversations: list[dict]):
        """
        构建对话索引（委托给 GraphRAGManager）
        
        Args:
            conversations: 对话列表，每个对话包含 conversation_text 字段
        """
        self._ensure_graph_rag()
        
        # 按时间过滤
        filtered = self._filter_by_lookback(conversations)
        self._conversations = filtered
        
        self._graph_rag.build_index(filtered)
    
    def update_index(self, new_conversations: list[dict]):
        """
        增量更新索引
        
        Args:
            new_conversations: 新增对话列表
        """
        self._ensure_graph_rag()
        filtered = self._filter_by_lookback(new_conversations)
        self._conversations.extend(filtered)
        self._graph_rag.update_index(filtered)
    
    def find_similar(self, conversation_text: str, top_k: int = 5) -> list[dict]:
        """
        查找相似对话（使用 GraphRAG 向量检索 + 重排）
        
        Args:
            conversation_text: 对话文本
            top_k: 返回数量
        
        Returns:
            相似对话列表
        """
        self._ensure_graph_rag()
        
        results = self._graph_rag.query_related(conversation_text, top_k=top_k)
        return [
            {
                'conversation_id': r.conversation_id,
                'conversation_text': r.conversation_text,
                'timestamp': r.timestamp,
                'similarity': r.score,
                'metadata': r.metadata,
            }
            for r in results
        ]
    
    def find_similar_fast(self, conversation_text: str, top_k: int = 5) -> list[dict]:
        """
        快速向量检索（< 100ms，无重排），供 listen 模式使用
        
        Args:
            conversation_text: 对话文本
            top_k: 返回数量
        
        Returns:
            相似对话列表
        """
        self._ensure_graph_rag()
        
        results = self._graph_rag.query_fast(conversation_text, top_k=top_k)
        return [
            {
                'conversation_id': r.conversation_id,
                'conversation_text': r.conversation_text,
                'timestamp': r.timestamp,
                'similarity': r.score,
                'metadata': r.metadata,
            }
            for r in results
        ]
    
    def generate_context_summary(self, current_conversation: str, top_k: int = 5) -> dict:
        """
        为当前对话生成长期上下文摘要
        
        Args:
            current_conversation: 当前对话文本
            top_k: 检索相关历史数量
        
        Returns:
            上下文摘要字典
        """
        self._ensure_graph_rag()
        
        summary = self._graph_rag.generate_context_summary(
            current_conversation, top_k=top_k
        )
        return {
            'related_count': len(summary.related_history),
            'pattern_summary': summary.pattern_summary,
            'topic_evolution': summary.topic_evolution,
            'related_conversations': [
                {
                    'conversation_id': r.conversation_id,
                    'score': r.score,
                    'timestamp': r.timestamp,
                    'text_preview': r.conversation_text[:200],
                }
                for r in summary.related_history
            ],
        }
    
    def analyze_patterns(self, conversations: list[dict]) -> LongTermPattern:
        """
        分析长期模式（使用 GraphRAG 语义聚类 + 关键词统计混合策略）
        
        Args:
            conversations: 对话列表（按时间排序）
        
        Returns:
            LongTermPattern 对象
        """
        result = LongTermPattern()
        
        filtered = self._filter_by_lookback(conversations)
        
        # 统计话题频率（含多模态信号）
        topic_counter = Counter()
        conflict_counter = Counter()
        
        for conv in filtered:
            text = conv.get('conversation_text', '')
            
            topics = self._extract_topics(text)
            topic_counter.update(topics)
            
            if self._has_conflict(text):
                conflicts = self._extract_conflict_topics(text)
                conflict_counter.update(conflicts)
        
        result.recurring_topics = [
            topic for topic, count in topic_counter.most_common(5)
            if count >= 2
        ]
        
        result.recurring_conflicts = [
            conflict for conflict, count in conflict_counter.most_common(3)
            if count >= 2
        ]
        
        # 语义聚类：使用 GraphRAG 找跨时间重复出现的语义相似对话
        if self._graph_rag is not None and len(filtered) >= 3:
            similar_clusters = self._find_semantic_clusters(filtered)
            result.similar_conversations = similar_clusters
        
        result.relationship_trend = self._analyze_trend(filtered)
        
        return result
    
    def _find_semantic_clusters(
        self, conversations: list[dict], similarity_threshold: float = 0.65,
    ) -> list[dict]:
        """
        使用 GraphRAG 向量检索发现语义相似的对话聚类
        
        Returns:
            聚类列表，每项含 {topic_hint, conversation_ids, count}
        """
        clusters: list[dict] = []
        seen_pairs: set[tuple] = set()
        
        for conv in conversations:
            text = conv.get('conversation_text', '')
            conv_id = conv.get('conversation_id', conv.get('chunk_id', ''))
            if not text:
                continue
            
            try:
                results = self._graph_rag.query_fast(text, top_k=5)
            except Exception:
                continue
            
            for r in results:
                if r.conversation_id == conv_id:
                    continue
                if r.score < similarity_threshold:
                    continue
                pair = tuple(sorted([conv_id, r.conversation_id]))
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                
                topics_a = self._extract_topics(text)
                topics_b = self._extract_topics(r.conversation_text)
                shared = set(topics_a) & set(topics_b)
                
                clusters.append({
                    'conversation_ids': list(pair),
                    'similarity': round(r.score, 3),
                    'shared_topics': list(shared) if shared else ['（语义相似）'],
                    'timestamps': [conv.get('timestamp', ''), r.timestamp],
                })
        
        clusters.sort(key=lambda c: c['similarity'], reverse=True)
        return clusters[:10]
    
    def get_user_profile(self) -> Optional[dict]:
        """获取跨会话长期用户档案"""
        if self._graph_rag is None:
            return None
        profile = self._graph_rag.get_user_profile()
        if profile is None:
            return None
        return {
            'total_conversations': profile.total_conversations,
            'date_range': profile.date_range,
            'recurring_topics': profile.recurring_topics,
            'recurring_conflicts': profile.recurring_conflicts,
            'relationship_trend': profile.relationship_trend,
            'top_emotions': profile.top_emotions,
            'communication_style_me': profile.communication_style_me,
            'communication_style_other': profile.communication_style_other,
            'last_updated': profile.last_updated,
        }
    
    def save_index(self, path: Optional[str] = None):
        """保存索引到磁盘"""
        if self._graph_rag:
            self._graph_rag.save_index(path)
    
    def load_index(self, path: Optional[str] = None) -> bool:
        """从磁盘加载索引"""
        self._ensure_graph_rag()
        return self._graph_rag.load_index(path)
    
    def unload_models(self):
        """卸载嵌入/重排模型释放显存"""
        if self._graph_rag:
            self._graph_rag.unload_models()
    
    def _filter_by_lookback(self, conversations: list[dict]) -> list[dict]:
        """按最大回溯天数过滤对话"""
        if self.max_lookback_days <= 0:
            return conversations
        
        cutoff = datetime.now() - timedelta(days=self.max_lookback_days)
        cutoff_str = cutoff.isoformat()
        
        filtered = []
        for conv in conversations:
            ts = conv.get('timestamp', '')
            if not ts or ts >= cutoff_str:
                filtered.append(conv)
        
        return filtered
    
    # 扩展话题关键词（含多模态信号标记）
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
    
    def _extract_topics(self, text: str) -> list[str]:
        """提取话题（含多模态信号）"""
        topics = []
        for topic, keywords in self._TOPIC_KEYWORDS.items():
            if any(kw in text for kw in keywords):
                topics.append(topic)
        return topics
    
    def _has_conflict(self, text: str) -> bool:
        """检测是否有冲突（含多模态信号）"""
        return any(ind in text for ind in self._CONFLICT_INDICATORS)
    
    def _extract_conflict_topics(self, text: str) -> list[str]:
        """提取冲突话题"""
        return self._extract_topics(text)
    
    def _analyze_trend(self, conversations: list[dict]) -> str:
        """分析关系趋势（含多模态情感信号）"""
        if len(conversations) < 3:
            return 'stable'
        
        positive_signals = [
            '爱', '喜欢', '开心', '幸福', '甜', '想你', '宝贝',
            '氛围:温馨', '氛围:浪漫', '氛围:欢乐',
            '撒娇', '卖萌', '开心/高兴', '表达爱意',
            '情绪:HAPPY',
        ]
        negative_signals = [
            '烦', '累', '生气', '讨厌', '分手', '不想', '算了',
            '情绪:ANGRY', '情绪:SAD', '情绪:DISGUSTED',
            '氛围:紧张', '氛围:压抑',
            'cold_period', 'argument_gap',
        ]
        
        mid = len(conversations) // 2
        first_half = conversations[:mid]
        second_half = conversations[mid:]
        
        def sentiment_score(convs):
            pos = neg = 0
            for conv in convs:
                text = conv.get('conversation_text', '')
                pos += sum(1 for w in positive_signals if w in text)
                neg += sum(1 for w in negative_signals if w in text)
            return pos - neg
        
        first_score = sentiment_score(first_half)
        second_score = sentiment_score(second_half)
        
        diff = second_score - first_score
        if diff > 3:
            return 'improving'
        elif diff < -3:
            return 'declining'
        return 'stable'


# =============================================================================
# 中立性检查器
# =============================================================================

@dataclass
class NeutralityScore:
    """中立性评分结果
    
    NeutralityChecker.check() 的返回值。
    
    Attributes:
        overall_score (float): 总体中立性评分（0-1，1 表示完全中立）
        me_bias (float): 对 ME 的偏向程度（正值偏向 ME，负值偏向 OTHER）
        criticism_balance (float): 批评平衡度（0-1，1 表示双方批评完全平衡）
        suggestions (list[str]): 改善中立性的建议列表
    """
    overall_score: float = 0.0  # 0-1，1 表示完全中立
    me_criticism_ratio: float = 0.0  # 对 ME 的批评比例
    other_criticism_ratio: float = 0.0  # 对 OTHER 的批评比例
    balance_score: float = 0.0  # 批评平衡度
    suggestions: list[str] = field(default_factory=list)


class NeutralityChecker:
    """中立性检查器
    
    评估分析文本的客观性和双方批评平衡度。
    用于确保 neutral Agent 的输出不偏袒任何一方。
    
    检查维度：
    - 情感词汇偏向（对 ME/OTHER 的正面/负面描述比例）
    - 批评平衡度（双方批评的长度和严厉程度）
    - 建议方向性（建议是否偏向某一方）
    
    Example:
        >>> checker = NeutralityChecker()
        >>> score = checker.check(analysis_text)
        >>> if score.overall_score < 0.6:
        ...     balanced = checker.balance_analysis(analysis_text)
    """
    
    # 批评性词汇
    CRITICISM_PATTERNS = [
        r'应该', r'不应该', r'问题', r'错误', r'不对',
        r'需要改', r'需要注意', r'建议.*改',
    ]
    
    # ME 相关词汇
    ME_PATTERNS = [r'你', r'ME', r'用户']
    
    # OTHER 相关词汇
    OTHER_PATTERNS = [r'对方', r'OTHER', r'伴侣', r'他/她']
    
    def check(self, analysis_text: str) -> NeutralityScore:
        """
        检查分析文本的中立性
        
        Args:
            analysis_text: 分析文本
        
        Returns:
            NeutralityScore 对象
        """
        result = NeutralityScore()
        
        # 分句
        sentences = re.split(r'[。！？\n]', analysis_text)
        sentences = [s.strip() for s in sentences if s.strip()]
        
        me_criticism = 0
        other_criticism = 0
        
        for sentence in sentences:
            # 检查是否是批评性句子
            is_criticism = any(re.search(p, sentence) for p in self.CRITICISM_PATTERNS)
            
            if is_criticism:
                # 检查批评对象
                has_me = any(re.search(p, sentence) for p in self.ME_PATTERNS)
                has_other = any(re.search(p, sentence) for p in self.OTHER_PATTERNS)
                
                if has_me and not has_other:
                    me_criticism += 1
                elif has_other and not has_me:
                    other_criticism += 1
                elif has_me and has_other:
                    me_criticism += 0.5
                    other_criticism += 0.5
        
        total_criticism = me_criticism + other_criticism
        
        if total_criticism > 0:
            result.me_criticism_ratio = me_criticism / total_criticism
            result.other_criticism_ratio = other_criticism / total_criticism
            
            # 计算平衡度（越接近 0.5 越平衡）
            result.balance_score = 1 - abs(result.me_criticism_ratio - 0.5) * 2
        else:
            result.balance_score = 1.0  # 没有批评，视为平衡
        
        # 计算总体中立性分数
        result.overall_score = result.balance_score
        
        # 生成建议
        if result.me_criticism_ratio > 0.7:
            result.suggestions.append("分析偏向批评用户（ME），建议增加对对方（OTHER）的分析")
        elif result.other_criticism_ratio > 0.7:
            result.suggestions.append("分析偏向批评对方（OTHER），建议增加对用户（ME）的分析")
        
        if total_criticism == 0:
            result.suggestions.append("分析缺少具体的问题指出，建议增加建设性批评")
        
        return result
    
    def balance_analysis(self, analysis_text: str) -> str:
        """
        尝试平衡分析文本（返回建议）
        
        Args:
            analysis_text: 分析文本
        
        Returns:
            平衡建议
        """
        score = self.check(analysis_text)
        
        if score.overall_score >= 0.8:
            return "分析已经比较中立，无需调整"
        
        suggestions = []
        
        if score.me_criticism_ratio > 0.6:
            suggestions.append("建议增加对 OTHER 行为的分析和建议")
            suggestions.append("可以指出 OTHER 在沟通中可能存在的问题")
        
        if score.other_criticism_ratio > 0.6:
            suggestions.append("建议增加对 ME 的反思性建议")
            suggestions.append("可以指出 ME 在互动中可以改进的地方")
        
        return "\n".join(suggestions) if suggestions else "分析基本平衡"


# =============================================================================
# 精神分析检测指标
# =============================================================================

@dataclass
class PsychoanalyticIndicators:
    """精神分析指标结果
    
    PsychoanalyticDetector.detect() 的返回值。
    
    Attributes:
        attachment_style_me (str): ME 的依附风格（安全型/焦虑型/回避型/混乱型）
        attachment_style_other (str): OTHER 的依附风格
        defense_mechanisms_me (list[str]): ME 的防御机制列表
        defense_mechanisms_other (list[str]): OTHER 的防御机制列表
        lacanian_analysis (dict): 拉康三界分析（想象界/象征界/实在界）
    """
    attachment_style_me: str = ''  # 依附风格
    attachment_style_other: str = ''
    defense_mechanisms_me: list[str] = field(default_factory=list)
    defense_mechanisms_other: list[str] = field(default_factory=list)
    lacanian_analysis: dict = field(default_factory=dict)


class PsychoanalyticDetector:
    """精神分析检测器
    
    基于客体关系理论（Klein, Winnicott）和拉康派精神分析，
    从对话文本中检测依附风格、防御机制和无意识动态。
    
    分析维度：
    - 依附风格：通过关键词匹配判断安全型/焦虑型/回避型/混乱型
    - 防御机制：识别投射、否认、理智化、反向形成、分裂等
    - 拉康三界：想象界（镜像认同）、象征界（语言秩序）、实在界（创伤核心）
    
    Example:
        >>> detector = PsychoanalyticDetector()
        >>> indicators = detector.detect(messages)
        >>> print(f"ME 依附风格: {indicators.attachment_style_me}")
    """
    
    # 依附风格文本模式
    ATTACHMENT_PATTERNS = {
        '焦虑型': [
            '你是不是不爱我', '你在干嘛', '为什么不回我', '你是不是生气了',
            '我好担心', '你会离开我吗', '我需要你',
        ],
        '回避型': [
            '我需要空间', '别烦我', '我想一个人', '太累了',
            '随便', '无所谓', '你自己决定',
        ],
        '安全型': [
            '我理解', '没关系', '我们一起', '相信你',
            '支持你', '慢慢来',
        ],
        '混乱型': [
            '我不知道', '我很矛盾', '又想又怕',
            '爱你但是', '想靠近又想逃',
        ],
    }
    
    # 防御机制语言标记
    DEFENSE_PATTERNS = {
        '否认': ['没有', '不是', '我没', '才不是'],
        '投射': ['你才是', '你自己', '你不也是'],
        '合理化': ['因为', '所以', '只是', '不得不'],
        '分裂': ['完全', '总是', '从来', '永远'],
        '理想化': ['最好', '完美', '最爱'],
        '贬低': ['最差', '最烦', '讨厌死'],
        '退行': ['不管了', '随便', '爱咋咋'],
        '压抑': ['算了', '不说了', '没什么'],
    }
    
    def detect(self, messages: list[dict]) -> PsychoanalyticIndicators:
        """
        检测精神分析指标
        
        Args:
            messages: 消息列表
        
        Returns:
            PsychoanalyticIndicators 对象
        """
        result = PsychoanalyticIndicators()
        
        # 分离 ME 和 OTHER 的消息
        me_texts = []
        other_texts = []
        
        for msg in messages:
            text = msg.get('text_raw', '')
            speaker = msg.get('speaker', '')
            
            if speaker == 'ME':
                me_texts.append(text)
            else:
                other_texts.append(text)
        
        me_combined = ' '.join(me_texts)
        other_combined = ' '.join(other_texts)
        
        # 检测依附风格
        result.attachment_style_me = self._detect_attachment(me_combined)
        result.attachment_style_other = self._detect_attachment(other_combined)
        
        # 检测防御机制
        result.defense_mechanisms_me = self._detect_defenses(me_combined)
        result.defense_mechanisms_other = self._detect_defenses(other_combined)
        
        # 拉康三界分析
        result.lacanian_analysis = self._lacanian_analysis(messages)
        
        return result
    
    def _detect_attachment(self, text: str) -> str:
        """检测依附风格"""
        scores = {}
        
        for style, patterns in self.ATTACHMENT_PATTERNS.items():
            score = sum(1 for p in patterns if p in text)
            scores[style] = score
        
        if not any(scores.values()):
            return '未检测到明显特征'
        
        return max(scores, key=scores.get)
    
    def _detect_defenses(self, text: str) -> list[str]:
        """检测防御机制"""
        detected = []
        
        for defense, patterns in self.DEFENSE_PATTERNS.items():
            if any(p in text for p in patterns):
                detected.append(defense)
        
        return detected[:3]  # 返回最多 3 个
    
    def _lacanian_analysis(self, messages: list[dict]) -> dict:
        """拉康三界分析"""
        return {
            '想象界': self._analyze_imaginary(messages),
            '象征界': self._analyze_symbolic(messages),
            '实在界': self._analyze_real(messages),
        }
    
    def _analyze_imaginary(self, messages: list[dict]) -> str:
        """分析想象界（镜像关系、自我认同）"""
        # 检测自我形象相关表达
        self_image_words = ['我觉得我', '我是', '我不是', '你觉得我']
        
        for msg in messages:
            text = msg.get('text_raw', '')
            if any(w in text for w in self_image_words):
                return "存在自我形象的投射和认同需求"
        
        return "未检测到明显的想象界动态"
    
    def _analyze_symbolic(self, messages: list[dict]) -> str:
        """分析象征界（语言、规则、社会秩序）"""
        # 检测规则/应该相关表达
        symbolic_words = ['应该', '必须', '规矩', '正常', '别人都']
        
        for msg in messages:
            text = msg.get('text_raw', '')
            if any(w in text for w in symbolic_words):
                return "存在对社会规范和期望的参照"
        
        return "未检测到明显的象征界参照"
    
    def _analyze_real(self, messages: list[dict]) -> str:
        """分析实在界（创伤、无法言说的）"""
        # 检测创伤/无法表达相关
        real_words = ['说不出', '不知道怎么说', '太痛', '受不了', '崩溃']
        
        for msg in messages:
            text = msg.get('text_raw', '')
            if any(w in text for w in real_words):
                return "存在难以言说的情感创伤"
        
        return "未检测到明显的实在界创伤"
