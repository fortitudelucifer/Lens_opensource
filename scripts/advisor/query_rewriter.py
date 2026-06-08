#!/usr/bin/env python3
"""
查询改写器模块

功能：
- 基于对话上下文和用户意图优化查询文本，提升 GraphRAG 检索效果
- 补充隐含意图（将模糊查询转化为明确的检索需求）
- 添加时序信息（结合对话历史中的时间线索）
- 情感色彩调整（根据当前情绪状态调整查询权重）
- 关键词扩展（添加同义词和相关概念）

处理流程：
1. 分析当前查询的意图类型
2. 结合对话历史提取上下文信息
3. 根据意图和上下文改写查询
4. 扩展关键词提升召回率

输入：
- 用户原始查询文本
- 对话历史（最近 N 轮）
- 意图分类结果
- 情绪状态（可选）

输出：
- 改写后的查询文本（优化后的检索 query）

依赖：
- scripts.advisor.intent_classifier: 意图分类结果

使用示例：
    from scripts.advisor.query_rewriter import QueryRewriter
    
    rewriter = QueryRewriter()
    rewritten = rewriter.rewrite(
        query="又吵架了",
        history=["上次也是因为这个"],
        intent="conflict_discussion"
    )

注意事项：
- 纯规则引擎，无需模型加载，延迟极低
- 改写结果用于 GraphRAG 检索，不直接展示给用户

作者：[Author]
更新于：2026-02-15
"""

import re
from typing import List, Dict, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass
class QueryContext:
    current_query: str
    history: List[str]
    intent: str
    emotion_state: Optional[str] = None
    time_context: Optional[str] = None


class QueryRewriter:
    def __init__(self):
        # 时间表达式映射
        self.time_expressions = {
            "今天": "今天",
            "昨天": "昨天",
            "明天": "明天",
            "刚才": "刚才",
            "之前": "之前",
            "上次": "上次",
            "最近": "最近",
            "这几天": "这几天",
            "那段时间": "那段时间"
        }
        
        # 情感词汇扩展
        self.emotion_expansions = {
            "累": ["疲惫", "劳累", "疲倦", "筋疲力尽"],
            "烦": ["烦躁", "烦恼", "郁闷", "心烦"],
            "生气": ["愤怒", "气愤", "恼火", "不高兴"],
            "难过": ["伤心", "悲伤", "痛苦", "难受"],
            "开心": ["高兴", "快乐", "愉快", "兴奋"]
        }
        
        # 关系词汇扩展
        self.relationship_expansions = {
            "吵架": ["争执", "冲突", "矛盾", "分歧"],
            "聊天": ["谈话", "交流", "沟通", "对话"],
            "关心": ["关爱", "照顾", "体贴", "呵护"],
            "理解": ["体谅", "包容", "支持", "认同"]
        }
    
    def rewrite_query(self, context: QueryContext) -> str:
        """
        改写查询，补充上下文信息
        
        Args:
            context: 查询上下文
            
        Returns:
            str: 改写后的查询
        """
        original_query = context.current_query.strip()
        
        # 1. 添加时间上下文
        time_enhanced = self._add_time_context(original_query, context)
        
        # 2. 扩展情感词汇
        emotion_enhanced = self._expand_emotion_words(time_enhanced, context)
        
        # 3. 添加历史上下文
        history_enhanced = self._add_history_context(emotion_enhanced, context)
        
        # 4. 根据意图调整
        intent_enhanced = self._adjust_for_intent(history_enhanced, context)
        
        # 5. 清理和格式化
        final_query = self._clean_query(intent_enhanced)
        
        return final_query
    
    def _add_time_context(self, query: str, context: QueryContext) -> str:
        """添加时间上下文"""
        # 检查是否包含时间表达式
        for expr, meaning in self.time_expressions.items():
            if expr in query:
                # 如果有历史记录，尝试确定具体时间
                if context.history and context.time_context:
                    return f"{meaning} {query} {context.time_context}"
                return f"{meaning} {query}"
        
        # 如果没有明确时间，从历史中推断
        if context.history:
            last_time = self._extract_time_from_history(context.history)
            if last_time:
                return f"{query} {last_time}"
        
        return query
    
    def _expand_emotion_words(self, query: str, context: QueryContext) -> str:
        """扩展情感词汇"""
        if not context.emotion_state:
            return query
        
        # 找到情感词并扩展
        words = query.split()
        expanded_words = []
        
        for word in words:
            expanded_words.append(word)
            
            # 如果是情感词，添加同义词
            for emotion, synonyms in self.emotion_expansions.items():
                if emotion in word and context.emotion_state == emotion:
                    # 添加1-2个同义词
                    expanded_words.extend(synonyms[:1])
                    break
        
        return " ".join(expanded_words)
    
    def _add_history_context(self, query: str, context: QueryContext) -> str:
        """添加历史上下文"""
        if not context.history:
            return query
        
        # 提取历史中的关键词
        history_keywords = self._extract_keywords_from_history(context.history)
        
        # 如果查询很短，添加历史关键词
        if len(query) < 10 and history_keywords:
            relevant_keywords = self._filter_relevant_keywords(query, history_keywords)
            if relevant_keywords:
                return f"{query} {' '.join(relevant_keywords[:2])}"
        
        return query
    
    def _adjust_for_intent(self, query: str, context: QueryContext) -> str:
        """根据意图调整查询"""
        intent_adjustments = {
            "emotional_support": f"如何安慰 {query}",
            "conflict_analysis": f"关于{query}的冲突分析",
            "relationship_guidance": f"针对{query}的关系建议",
            "factual_search": query,  # 信息查询不需要调整
            "general_chat": query   # 闲聊不需要调整
        }
        
        return intent_adjustments.get(context.intent, query)
    
    def _clean_query(self, query: str) -> str:
        """清理查询格式"""
        # 移除多余空格
        query = re.sub(r'\s+', ' ', query)
        
        # 移除重复词汇
        words = query.split()
        unique_words = []
        seen = set()
        
        for word in words:
            if word not in seen:
                unique_words.append(word)
                seen.add(word)
        
        return " ".join(unique_words)
    
    def _extract_time_from_history(self, history: List[str]) -> Optional[str]:
        """从历史中提取时间信息"""
        # 简单的时间提取逻辑
        time_patterns = [
            r'第(\d+)天',
            r'(\d{4}-\d{2}-\d{2})',
            r'(\d{1,2}月\d{1,2}日)',
            r'(昨天|今天|明天|前天|后天)'
        ]
        
        for msg in reversed(history[-3:]):  # 只看最近3条
            for pattern in time_patterns:
                match = re.search(pattern, msg)
                if match:
                    return match.group(1)
        
        return None
    
    def _extract_keywords_from_history(self, history: List[str]) -> List[str]:
        """从历史中提取关键词"""
        # 简单的关键词提取
        keywords = []
        
        for msg in history[-5:]:  # 只看最近5条
            # 提取名词和动词（简单实现）
            words = re.findall(r'[\u4e00-\u9fff]+', msg)
            keywords.extend([w for w in words if len(w) >= 2])
        
        return list(set(keywords))
    
    def _filter_relevant_keywords(self, query: str, keywords: List[str]) -> List[str]:
        """过滤相关关键词"""
        relevant = []
        
        for keyword in keywords:
            # 简单的相关性判断
            if any(word in keyword for word in query.split()):
                relevant.append(keyword)
        
        return relevant
    
    def batch_rewrite(self, queries: List[str], context: QueryContext) -> List[str]:
        """批量改写查询"""
        results = []
        
        for query in queries:
            temp_context = QueryContext(
                current_query=query,
                history=context.history,
                intent=context.intent,
                emotion_state=context.emotion_state,
                time_context=context.time_context
            )
            rewritten = self.rewrite_query(temp_context)
            results.append(rewritten)
        
        return results


if __name__ == '__main__':
    # 测试代码
    rewriter = QueryRewriter()
    
    # 模拟上下文
    context = QueryContext(
        current_query="好累啊",
        history=[
            "[第108天 13:03] ME: 今天工作好累",
            "[第108天 13:05] OTHER: 辛苦了",
            "[第108天 13:06] ME: 项目压力很大"
        ],
        intent="emotional_support",
        emotion_state="累",
        time_context="第108天"
    )
    
    print("=== 查询改写测试 ===")
    print(f"原始查询: {context.current_query}")
    
    rewritten = rewriter.rewrite_query(context)
    print(f"改写后: {rewritten}")
    
    # 批量测试
    test_queries = ["烦死了", "在干嘛", "怎么办"]
    batch_results = rewriter.batch_rewrite(test_queries, context)
    
    print("\n=== 批量改写测试 ===")
    for original, rewritten in zip(test_queries, batch_results):
        print(f"{original} → {rewritten}")
