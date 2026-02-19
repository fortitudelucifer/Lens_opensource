#!/usr/bin/env python3
"""
GraphRAG 日期查询扩展模块

功能：
- 在 GraphRAGManager 基础上增加精确日期查询功能
- 支持 L1/L2 数据分离（L1 基础对话数据 / L2 多模态增强数据）
- 支持日期范围查询和单日查询
- 自动解析对话文本中的日期标记（第X天格式）

处理流程：
1. 加载 L1 和 L2 索引（分别对应不同数据层级）
2. 解析查询中的日期信息
3. 在对应日期范围内进行向量检索
4. 合并 L1/L2 结果并重排

输入：
- 日期字符串或日期范围
- 查询文本（可选）

输出：
- 指定日期范围内的相关对话检索结果

依赖：
- scripts.advisor.graph_rag: GraphRAGManager 基类

使用示例：
    from scripts.advisor.graph_rag_enhanced import EnhancedGraphRAGManager
    
    rag = EnhancedGraphRAGManager()
    rag.load_l1_index('path/to/l1_index')
    results = rag.query_by_date('2025-09-22', top_k=5)

注意事项：
- L1 和 L2 索引需要分别构建和加载
- 日期查询依赖对话文本中的 "第X天" 格式标记

作者：forcifer
更新于：2026-02-15
"""

import re
from datetime import datetime
from typing import List, Optional, Tuple
from pathlib import Path

from .graph_rag import GraphRAGManager, RetrievalResult
from .intent_classifier import IntentClassifier, IntentResult
from .query_rewriter import QueryRewriter, QueryContext


class EnhancedGraphRAGManager(GraphRAGManager):
    """增强版 GraphRAG 管理器，支持精确日期查询"""
    
    def __init__(self, config: Optional[dict] = None):
        super().__init__(config)
        self._l1_conversations = []  # L1 数据（真实日期）
        self._l2_conversations = []  # L2 数据（匿名日期）
        self._current_mode = 'l2'   # 默认使用 L2 数据
        
        # 新增组件
        self.intent_classifier = IntentClassifier()
        self.query_rewriter = QueryRewriter()
        self.conversation_history = []  # 存储对话历史
    
    def load_l1_data(self, l1_path: str):
        """加载 L1 数据（保留真实日期）"""
        l1_path = Path(l1_path)
        if not l1_path.exists():
            print(f"L1 数据文件不存在: {l1_path}")
            return False
        
        self._l1_conversations = []
        with open(l1_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    # 标准化时间戳格式
                    timestamp = self._normalize_timestamp(data.get('time', ''))
                    self._l1_conversations.append({
                        'conversation_id': data.get('id', ''),
                        'conversation_text': data.get('text_raw', ''),
                        'timestamp': timestamp,
                        'metadata': {
                            'speaker': data.get('speaker', ''),
                            'type': data.get('type', ''),
                            'day_index': data.get('day_index', 0),
                        },
                    })
                except json.JSONDecodeError:
                    continue
        
        print(f"已加载 {len(self._l1_conversations)} 条 L1 数据")
        return True
    
    def load_l2_data(self, l2_path: str):
        """加载 L2 数据（匿名日期）"""
        l2_path = Path(l2_path)
        if not l2_path.exists():
            print(f"L2 数据文件不存在: {l2_path}")
            return False
        
        self._l2_conversations = []
        with open(l2_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    self._l2_conversations.append({
                        'conversation_id': data.get('id', ''),
                        'conversation_text': data.get('text_raw', ''),
                        'timestamp': data.get('ts_relative', ''),
                        'metadata': {
                            'speaker': data.get('speaker', ''),
                            'type': data.get('type', ''),
                            'day_index': data.get('day_index', 0),
                        },
                    })
                except json.JSONDecodeError:
                    continue
        
        print(f"已加载 {len(self._l2_conversations)} 条 L2 数据")
        return True
    
    def set_mode(self, mode: str):
        """设置查询模式：'l1'（精确日期）或 'l2'（匿名日期）"""
        if mode not in ['l1', 'l2']:
            raise ValueError("模式必须是 'l1' 或 'l2'")
        self._current_mode = mode
        
        # 更新 GraphRAG 的对话数据
        conversations = self._l1_conversations if mode == 'l1' else self._l2_conversations
        self._conversations = conversations
    
    def _normalize_timestamp(self, timestamp: str) -> str:
        """标准化时间戳格式"""
        if not timestamp:
            return ''
        
        # 如果已经是完整格式，直接返回
        if re.match(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}', timestamp):
            return timestamp
        
        # 如果只有时间，添加默认日期
        if re.match(r'\d{2}:\d{2}', timestamp):
            return f"2025-01-01 {timestamp}"
        
        # 如果是其他格式，尝试解析
        try:
            # 尝试解析各种格式
            for fmt in ['%Y-%m-%d %H:%M', '%H:%M', '%Y-%m-%d']:
                try:
                    dt = datetime.strptime(timestamp, fmt)
                    if fmt == '%H:%M':
                        dt = dt.replace(year=2025, month=1, day=1)
                    return dt.strftime('%Y-%m-%d %H:%M')
                except ValueError:
                    continue
        except Exception:
            pass
        
        return timestamp
    
    def query_by_date(
        self,
        target_date: str,
        top_k: int = 10,
        fuzzy_days: int = 0
    ) -> List[RetrievalResult]:
        """
        按日期查询
        
        Args:
            target_date: 目标日期，格式如 '2025-09-22' 或 '第108天'
            top_k: 返回结果数量
            fuzzy_days: 模糊天数，允许前后 N 天内的结果
        
        Returns:
            检索结果列表
        """
        if self._current_mode == 'l1':
            return self._query_by_date_l1(target_date, top_k, fuzzy_days)
        else:
            return self._query_by_date_l2(target_date, top_k)
    
    def _query_by_date_l1(
        self,
        target_date: str,
        top_k: int,
        fuzzy_days: int
    ) -> List[RetrievalResult]:
        """L1 数据的日期查询（精确日期）"""
        results = []
        
        # 解析目标日期
        target_dt = self._parse_date(target_date)
        if not target_dt:
            return []
        
        for conv in self._l1_conversations:
            conv_date = self._parse_date(conv['timestamp'])
            if not conv_date:
                continue
            
            # 计算日期差
            date_diff = abs((target_dt - conv_date).days)
            
            if date_diff <= fuzzy_days:
                # 计算相关度（日期越近相关度越高）
                score = 1.0 / (1.0 + date_diff)
                
                results.append(RetrievalResult(
                    conversation_id=conv['conversation_id'],
                    conversation_text=conv['conversation_text'],
                    timestamp=conv['timestamp'],
                    score=score,
                    metadata=conv['metadata'],
                ))
        
        # 按相关度排序
        results.sort(key=lambda x: x.score, reverse=True)
        return results[:top_k]
    
    def _query_by_date_l2(
        self,
        target_date: str,
        top_k: int
    ) -> List[RetrievalResult]:
        """L2 数据的日期查询（匿名日期）"""
        results = []
        
        # 提取天数
        day_match = re.search(r'第(\d+)天', target_date)
        if not day_match:
            return []
        
        target_day = int(day_match.group(1))
        
        for conv in self._l2_conversations:
            conv_day = conv['metadata'].get('day_index', 0) + 1  # day_index 从 0 开始
            
            if conv_day == target_day:
                results.append(RetrievalResult(
                    conversation_id=conv['conversation_id'],
                    conversation_text=conv['conversation_text'],
                    timestamp=conv['timestamp'],
                    score=1.0,
                    metadata=conv['metadata'],
                ))
        
        return results[:top_k]
    
    def query_by_date_range(
        self,
        start_date: str,
        end_date: str,
        top_k: int = 50,
        mode: str = 'exact'
    ) -> List[RetrievalResult]:
        """
        按日期范围查询（支持多种模式）
        
        Args:
            start_date: 开始日期
            end_date: 结束日期
            top_k: 返回结果数量
            mode: 查询模式 - 'exact' (精确匹配), 'semantic' (语义相似), 'hybrid' (混合)
        
        Returns:
            检索结果列表
        """
        if self._current_mode == 'l1':
            return self._query_by_date_range_l1(start_date, end_date, top_k, mode)
        else:
            return self._query_by_date_range_l2(start_date, end_date, top_k, mode)
    
    def _query_by_date_range_l1(
        self,
        start_date: str,
        end_date: str,
        top_k: int,
        mode: str
    ) -> List[RetrievalResult]:
        """
        L1 数据的日期范围查询（支持多种模式）
        
        基于 RAG 增强检索最佳实践：
        1. 精确匹配：直接日期过滤
        2. 语义相似：结合向量相似度
        3. 混合模式：先过滤再向量检索
        """
        results = []
        
        start_dt = self._parse_date(start_date)
        end_dt = self._parse_date(end_date)
        
        if not start_dt or not end_dt:
            return []
        
        # 预过滤：先按日期范围筛选
        filtered_conversations = []
        for conv in self._l1_conversations:
            conv_dt = self._parse_date(conv['timestamp'])
            if not conv_dt:
                continue
            
            if start_dt <= conv_dt <= end_dt:
                filtered_conversations.append(conv)
        
        if mode == 'exact':
            # 精确匹配模式：只按日期过滤，按时间排序
            for conv in filtered_conversations:
                results.append(RetrievalResult(
                    conversation_id=conv['conversation_id'],
                    conversation_text=conv['conversation_text'],
                    timestamp=conv['timestamp'],
                    score=1.0,
                    metadata=conv['metadata'],
                ))
            results.sort(key=lambda x: x.timestamp)
            
        elif mode == 'semantic':
            # 语义相似模式：在日期范围内进行向量检索
            if not filtered_conversations:
                return results
            
            # 构建日期范围内的子索引
            temp_conversations = self._conversations
            self._conversations = filtered_conversations
            
            # 使用向量检索
            query_text = f"{start_date} 到 {end_date} 期间的对话"
            vector_results = self.query_related(query_text, top_k=top_k, use_reranker=True)
            
            # 恢复原索引
            self._conversations = temp_conversations
            
            results = vector_results
            
        elif mode == 'hybrid':
            # 混合模式：先过滤，再结合时间权重和语义相似度
            if not filtered_conversations:
                return results
            
            # 临时替换对话数据进行向量检索
            temp_conversations = self._conversations
            self._conversations = filtered_conversations
            
            query_text = f"{start_date} 到 {end_date} 期间的重要对话"
            semantic_results = self.query_related(query_text, top_k=top_k*2, use_reranker=True)
            
            # 恢复原索引
            self._conversations = temp_conversations
            
            # 计算混合分数：语义相似度 + 时间新鲜度
            for result in semantic_results:
                conv_dt = self._parse_date(result.timestamp)
                if conv_dt:
                    # 时间越近，权重越高
                    days_diff = (end_dt - conv_dt).days
                    time_weight = 1.0 / (1.0 + days_diff * 0.1)
                    
                    # 混合分数：70% 语义相似度 + 30% 时间权重
                    result.score = result.score * 0.7 + time_weight * 0.3
            
            results = sorted(semantic_results, key=lambda x: x.score, reverse=True)
        
        return results[:top_k]
    
    def _query_by_date_range_l2(
        self,
        start_date: str,
        end_date: str,
        top_k: int,
        mode: str
    ) -> List[RetrievalResult]:
        """
        L2 数据的日期范围查询（支持多种模式）
        
        对于匿名化数据，主要基于天数进行过滤
        """
        results = []
        
        # 提取天数
        start_match = re.search(r'第(\d+)天', start_date)
        end_match = re.search(r'第(\d+)天', end_date)
        
        if not start_match or not end_match:
            return []
        
        start_day = int(start_match.group(1))
        end_day = int(end_match.group(1))
        
        # 预过滤：先按天数范围筛选
        filtered_conversations = []
        for conv in self._l2_conversations:
            conv_day = conv['metadata'].get('day_index', 0) + 1  # day_index 从 0 开始
            
            if start_day <= conv_day <= end_day:
                filtered_conversations.append(conv)
        
        if mode == 'exact':
            # 精确匹配：按天数过滤，按时间排序
            for conv in filtered_conversations:
                results.append(RetrievalResult(
                    conversation_id=conv['conversation_id'],
                    conversation_text=conv['conversation_text'],
                    timestamp=conv['timestamp'],
                    score=1.0,
                    metadata=conv['metadata'],
                ))
            results.sort(key=lambda x: x.timestamp)
            
        elif mode == 'semantic':
            # 语义相似模式：在天数范围内进行向量检索
            if not filtered_conversations:
                return results
            
            # 临时替换对话数据进行向量检索
            temp_conversations = self._conversations
            self._conversations = filtered_conversations
            
            query_text = f"第{start_day}天到第{end_day}天期间的对话"
            vector_results = self.query_related(query_text, top_k=top_k, use_reranker=True)
            
            # 恢复原索引
            self._conversations = temp_conversations
            
            results = vector_results
            
        elif mode == 'hybrid':
            # 混合模式：先过滤，再结合时间权重和语义相似度
            if not filtered_conversations:
                return results
            
            # 临时替换对话数据进行向量检索
            temp_conversations = self._conversations
            self._conversations = filtered_conversations
            
            query_text = f"第{start_day}天到第{end_day}天期间的重要对话"
            semantic_results = self.query_related(query_text, top_k=top_k*2, use_reranker=True)
            
            # 恢复原索引
            self._conversations = temp_conversations
            
            # 计算混合分数：语义相似度 + 天数新鲜度
            for result in semantic_results:
                conv_day = result.metadata.get('day_index', 0) + 1
                days_diff = end_day - conv_day
                
                # 天数越近，权重越高
                time_weight = 1.0 / (1.0 + days_diff * 0.1)
                
                # 混合分数：70% 语义相似度 + 30% 时间权重
                result.score = result.score * 0.7 + time_weight * 0.3
            
            results = sorted(semantic_results, key=lambda x: x.score, reverse=True)
        
        return results[:top_k]
    
    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """解析日期字符串"""
        if not date_str:
            return None
        
        # 尝试多种格式
        formats = [
            '%Y-%m-%d %H:%M',
            '%Y-%m-%d',
            '%Y/%m/%d %H:%M',
            '%Y/%m/%d',
        ]
        
        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue
        
        return None
    
    def smart_query(
        self,
        query_text: str,
        top_k: int = 5,
        use_history: bool = True,
        enable_rewrite: bool = True
    ) -> Tuple[List[RetrievalResult], IntentResult]:
        """
        智能查询：结合意图分类和查询改写
        
        Args:
            query_text: 原始查询文本
            top_k: 返回结果数量
            use_history: 是否使用历史上下文
            enable_rewrite: 是否启用查询改写
        
        Returns:
            Tuple[检索结果, 意图分析结果]
        """
        # 1. 意图分类
        intent_result = self.intent_classifier.classify(query_text)
        
        # 2. 获取搜索策略
        search_strategy = self.intent_classifier.get_search_strategy(intent_result)
        
        # 3. 查询改写
        final_query = query_text
        if enable_rewrite:
            context = QueryContext(
                current_query=query_text,
                history=self.conversation_history if use_history else [],
                intent=intent_result.suggested_action,
                emotion_state=self._extract_emotion_from_keywords(intent_result.keywords)
            )
            final_query = self.query_rewriter.rewrite_query(context)
        
        # 4. 根据策略执行检索
        if search_strategy.get("speed_priority", False):
            # 快速模式：不使用重排
            results = self.query_fast(final_query, top_k=search_strategy.get("top_k", top_k))
        else:
            # 精确模式：使用重排
            results = self.query_related(
                final_query, 
                top_k=search_strategy.get("top_k", top_k),
                use_reranker=search_strategy.get("use_reranker", True)
            )
        
        # 5. 应用过滤策略
        if search_strategy.get("emotion_filter"):
            results = self._apply_emotion_filter(results, search_strategy["emotion_filter"])
        
        if search_strategy.get("conflict_filter"):
            results = self._apply_conflict_filter(results)
        
        # 6. 限制返回数量
        results = results[:top_k]
        
        # 7. 更新对话历史
        self.conversation_history.append(query_text)
        if len(self.conversation_history) > 10:  # 只保留最近10条
            self.conversation_history = self.conversation_history[-10:]
        
        return results, intent_result
    
    def _extract_emotion_from_keywords(self, keywords: List[str]) -> Optional[str]:
        """从关键词中提取情绪状态"""
        emotion_map = {
            "累": "累",
            "烦": "烦",
            "生气": "生气",
            "难过": "难过",
            "开心": "开心"
        }
        
        for keyword in keywords:
            for emotion, word in emotion_map.items():
                if emotion in keyword:
                    return word
        
        return None
    
    def _apply_emotion_filter(self, results: List[RetrievalResult], emotion_type: str) -> List[RetrievalResult]:
        """应用情感过滤"""
        # 简单的情感过滤实现
        if emotion_type == "supportive":
            # 优先选择支持性、安慰性的对话
            supportive_keywords = ["安慰", "支持", "理解", "关心", "体贴"]
            filtered_results = []
            
            for result in results:
                text = result.conversation_text.lower()
                if any(keyword in text for keyword in supportive_keywords):
                    result.score *= 1.2  # 提升权重
                filtered_results.append(result)
            
            return sorted(filtered_results, key=lambda x: x.score, reverse=True)
        
        return results
    
    def _apply_conflict_filter(self, results: List[RetrievalResult]) -> List[RetrievalResult]:
        """应用冲突过滤"""
        conflict_keywords = ["吵架", "争执", "冲突", "矛盾", "分歧"]
        filtered_results = []
        
        for result in results:
            text = result.conversation_text.lower()
            if any(keyword in text for keyword in conflict_keywords):
                filtered_results.append(result)
        
        return filtered_results
    
    def get_timeline_summary(self, date: str) -> dict:
        """
        获取特定日期的时间线摘要
        
        Args:
            date: 日期字符串
        
        Returns:
            时间线摘要字典
        """
        results = self.query_by_date(date, top_k=100)
        
        if not results:
            return {'date': date, 'events': [], 'summary': '没有找到相关记录'}
        
        # 按时间排序
        results.sort(key=lambda x: x.timestamp)
        
        events = []
        for result in results:
            events.append({
                'time': result.timestamp,
                'speaker': result.metadata.get('speaker', ''),
                'content': result.conversation_text[:100] + '...',
                'score': result.score,
            })
        
        summary = f"在 {date} 共有 {len(events)} 条对话记录"
        
        return {
            'date': date,
            'events': events,
            'summary': summary,
            'total_events': len(events),
        }
    
    def query_with_metadata_filter(
        self,
        query_text: str,
        date_filter: Optional[dict] = None,
        speaker_filter: Optional[str] = None,
        content_type_filter: Optional[str] = None,
        top_k: int = 10,
        use_reranker: bool = True
    ) -> List[RetrievalResult]:
        """
        基于元数据的增强检索
        
        Args:
            query_text: 查询文本
            date_filter: 日期过滤 {'start': '2025-09-22', 'end': '2025-09-25'}
            speaker_filter: 说话人过滤 ('ME' 或 'OTHER')
            content_type_filter: 内容类型过滤 ('text', 'image', 'voice')
            top_k: 返回结果数量
            use_reranker: 是否使用重排器
        
        Returns:
            检索结果列表
        """
        # 预过滤：根据元数据条件筛选
        filtered_conversations = []
        
        for conv in self._conversations:
            # 日期过滤
            if date_filter:
                conv_dt = self._parse_date(conv['timestamp'])
                if not conv_dt:
                    continue
                
                start_dt = self._parse_date(date_filter.get('start', ''))
                end_dt = self._parse_date(date_filter.get('end', ''))
                
                if start_dt and end_dt:
                    if not (start_dt <= conv_dt <= end_dt):
                        continue
            
            # 说话人过滤
            if speaker_filter:
                # 检查对话中是否包含指定说话人
                if self._current_mode == 'l1':
                    # L1 数据：检查 text_raw 中的说话人
                    if speaker_filter not in conv.get('metadata', {}).get('speaker', ''):
                        continue
                else:
                    # L2 数据：检查对话文本中的说话人标记
                    if f"{speaker_filter}:" not in conv.get('conversation_text', ''):
                        continue
            
            # 内容类型过滤
            if content_type_filter:
                content_type = conv.get('metadata', {}).get('type', 'text')
                if content_type != content_type_filter:
                    continue
            
            filtered_conversations.append(conv)
        
        if not filtered_conversations:
            return []
        
        # 临时替换对话数据进行向量检索
        temp_conversations = self._conversations
        self._conversations = filtered_conversations
        
        # 执行向量检索
        results = self.query_related(query_text, top_k=top_k, use_reranker=use_reranker)
        
        # 恢复原索引
        self._conversations = temp_conversations
        
        return results
    
    def query_temporal_patterns(
        self,
        pattern_type: str = 'conflict',
        time_window: int = 7,
        top_k: int = 20
    ) -> List[RetrievalResult]:
        """
        查询时间模式（如冲突模式、情绪模式等）
        
        Args:
            pattern_type: 模式类型 ('conflict', 'emotion', 'activity')
            time_window: 时间窗口（天数）
            top_k: 返回结果数量
        
        Returns:
            检索结果列表
        """
        # 模式关键词映射
        pattern_keywords = {
            'conflict': ['吵架', '生气', '愤怒', '不满', '争执', '冲突'],
            'emotion': ['开心', '高兴', '难过', '伤心', '委屈', '焦虑'],
            'activity': ['吃饭', '工作', '睡觉', '出门', '聚会', '运动'],
        }
        
        keywords = pattern_keywords.get(pattern_type, [])
        if not keywords:
            return []
        
        # 构建查询文本
        query_text = f" {' '.join(keywords)} "
        
        # 获取当前时间范围
        if self._current_mode == 'l1':
            # L1 数据：使用真实日期
            from datetime import datetime, timedelta
            end_date = datetime.now()
            start_date = end_date - timedelta(days=time_window)
            
            date_filter = {
                'start': start_date.strftime('%Y-%m-%d'),
                'end': end_date.strftime('%Y-%m-%d')
            }
        else:
            # L2 数据：使用相对天数
            # 假设当前是第200天
            current_day = 200
            start_day = max(1, current_day - time_window)
            end_day = current_day
            
            date_filter = {
                'start': f'第{start_day}天',
                'end': f'第{end_day}天'
            }
        
        # 执行带时间过滤的查询
        results = self.query_with_metadata_filter(
            query_text=query_text,
            date_filter=date_filter,
            top_k=top_k,
            use_reranker=True
        )
        
        return results


if __name__ == '__main__':
    # 测试代码
    rag = EnhancedGraphRAGManager()
    
    # 加载数据
    print("正在加载数据...")
    rag.load_l1_data('timeline_out/agent_sft_l1.jsonl')
    rag.load_l2_data('timeline_out/agent_sft_l2.jsonl')
    
    # 测试 L1 查询
    print("\n=== L1 查询测试 ===")
    rag.set_mode('l1')
    
    # 精确日期查询
    results = rag.query_by_date('2025-09-22', top_k=5)
    print(f"L1 精确日期查询结果 ({len(results)} 条):")
    for result in results:
        print(f"  {result.timestamp}: {result.conversation_text[:50]}...")
    
    # 日期范围查询（混合模式）
    results = rag.query_by_date_range('2025-09-22', '2025-09-25', top_k=5, mode='hybrid')
    print(f"\nL1 日期范围查询（混合模式）结果 ({len(results)} 条):")
    for result in results:
        print(f"  {result.timestamp}: {result.conversation_text[:50]}... (score: {result.score:.3f})")
    
    # 元数据过滤查询
    results = rag.query_with_metadata_filter(
        query_text="吃饭",
        date_filter={'start': '2025-09-22', 'end': '2025-09-25'},
        speaker_filter='ME',
        top_k=3
    )
    print(f"\nL1 元数据过滤查询结果 ({len(results)} 条):")
    for result in results:
        print(f"  {result.timestamp}: {result.conversation_text[:50]}...")
    
    # 测试 L2 查询
    print("\n=== L2 查询测试 ===")
    rag.set_mode('l2')
    
    # 匿名日期查询
    results = rag.query_by_date('第108天', top_k=5)
    print(f"L2 匿名日期查询结果 ({len(results)} 条):")
    for result in results:
        print(f"  {result.timestamp}: {result.conversation_text[:50]}...")
    
    # 日期范围查询（语义模式）
    results = rag.query_by_date_range('第108天', '第110天', top_k=5, mode='semantic')
    print(f"\nL2 日期范围查询（语义模式）结果 ({len(results)} 条):")
    for result in results:
        print(f"  {result.timestamp}: {result.conversation_text[:50]}... (score: {result.score:.3f})")
    
    # 时间模式查询
    results = rag.query_temporal_patterns('conflict', time_window=7, top_k=3)
    print(f"\n冲突模式查询结果 ({len(results)} 条):")
    for result in results:
        print(f"  {result.timestamp}: {result.conversation_text[:50]}...")
    
    # 时间线摘要
    timeline = rag.get_timeline_summary('第108天')
    print(f"\n时间线摘要:")
    print(f"  {timeline['summary']}")
    print(f"  事件数量: {timeline['total_events']}")
    
    print("\n=== 测试完成 ===")
