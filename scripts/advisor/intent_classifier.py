#!/usr/bin/env python3
"""
意图分类器模块

功能：
- 识别用户查询的真实意图，用于对话引擎的路由决策
- 基于关键词匹配的轻量级分类（无需 GPU）
- 支持 5 种意图类型的识别和置信度评分

意图类型：
- emotional_venting: 情绪宣泄（"好累"、"烦死了"、"受不了"）
- information_query: 信息查询（"什么时候"、"在哪里"、"怎么回事"）
- casual_chat: 闲聊（"在干嘛"、"吃饭了吗"、"今天天气"）
- conflict_discussion: 冲突讨论（"又吵架了"、"为什么这样"、"他总是"）
- relationship_advice: 关系建议（"我该怎么办"、"怎么处理"、"有什么建议"）

处理流程：
1. 对输入文本进行关键词匹配
2. 计算每种意图的匹配分数
3. 返回最高分意图及置信度

输入：
- 用户查询文本（str）

输出：
- 意图分类结果（IntentType + 置信度分数）

使用示例：
    from scripts.advisor.intent_classifier import IntentClassifier
    
    classifier = IntentClassifier()
    result = classifier.classify("我该怎么办，他总是不理我")
    print(f"意图: {result.intent}, 置信度: {result.confidence}")

注意事项：
- 纯关键词匹配，无需模型加载，延迟极低（< 1ms）
- 多意图重叠时返回最高分意图
- 可通过配置扩展关键词列表

作者：[Author]
更新于：2026-02-15
"""

import re
from typing import Dict, List, Tuple
from dataclasses import dataclass
from enum import Enum


class IntentType(Enum):
    EMOTIONAL_VENTING = "emotional_venting"
    INFORMATION_QUERY = "information_query"
    CASUAL_CHAT = "casual_chat"
    CONFLICT_DISCUSSION = "conflict_discussion"
    RELATIONSHIP_ADVICE = "relationship_advice"


@dataclass
class IntentResult:
    intent: IntentType
    confidence: float
    keywords: List[str]
    suggested_action: str


class IntentClassifier:
    def __init__(self):
        # 意图关键词映射
        self.intent_keywords = {
            IntentType.EMOTIONAL_VENTING: [
                "累", "烦", "烦死了", "好累", "疲惫", "压力大", "崩溃",
                "生气", "愤怒", "委屈", "难过", "伤心", "痛苦", "焦虑",
                "不想", "受不了", "撑不住", "要疯了", "无语", "绝望"
            ],
            IntentType.INFORMATION_QUERY: [
                "什么时候", "在哪", "哪里", "几点", "什么时间", "如何",
                "怎么", "怎样", "为什么", "是什么", "谁", "哪个",
                "多少", "几个", "多久", "多长时间", "还有吗"
            ],
            IntentType.CASUAL_CHAT: [
                "在干嘛", "干嘛呢", "吃饭了吗", "睡了没", "忙吗",
                "你好", "哈喽", "嗨", "早上好", "晚上好", "晚安",
                "今天", "明天", "昨天", "周末", "天气", "最近"
            ],
            IntentType.CONFLICT_DISCUSSION: [
                "吵架", "争执", "冲突", "矛盾", "分歧", "不和",
                "又这样", "总是", "每次都", "又不理", "冷战",
                "生气了", "不开心", "闹脾气", "发脾气", "情绪化"
            ],
            IntentType.RELATIONSHIP_ADVICE: [
                "怎么办", "怎么处理", "如何解决", "建议", "意见",
                "应该", "不该", "对吗", "好吗", "可以吗",
                "帮我", "救救我", "求助", "指导", "分析"
            ]
        }
        
        # 情绪强度词汇
        self.emotion_intensity = {
            "高": ["崩溃", "绝望", "要疯了", "受不了", "撑不住"],
            "中": ["生气", "难过", "焦虑", "压力大", "委屈"],
            "低": ["累", "烦", "无语", "不想", "不开心"]
        }
    
    def classify(self, query: str) -> IntentResult:
        """
        分类用户查询意图
        
        Args:
            query: 用户查询文本
            
        Returns:
            IntentResult: 分类结果
        """
        query = query.strip().lower()
        
        # 计算每个意图的匹配分数
        intent_scores = {}
        matched_keywords = {}
        
        for intent, keywords in self.intent_keywords.items():
            score = 0
            matches = []
            
            for keyword in keywords:
                if keyword in query:
                    # 精确匹配得分更高
                    if keyword == query:
                        score += 10
                    elif query.startswith(keyword):
                        score += 5
                    elif keyword in query:
                        score += 3
                    
                    matches.append(keyword)
            
            intent_scores[intent] = score
            matched_keywords[intent] = matches
        
        # 找到最高分的意图
        if not any(intent_scores.values()):
            # 默认为闲聊
            return IntentResult(
                intent=IntentType.CASUAL_CHAT,
                confidence=0.5,
                keywords=[],
                suggested_action="general_chat"
            )
        
        best_intent = max(intent_scores, key=intent_scores.get)
        best_score = intent_scores[best_intent]
        
        # 计算置信度
        total_score = sum(intent_scores.values())
        confidence = best_score / total_score if total_score > 0 else 0.5
        
        # 生成建议动作
        suggested_action = self._get_suggested_action(best_intent, query)
        
        return IntentResult(
            intent=best_intent,
            confidence=confidence,
            keywords=matched_keywords[best_intent],
            suggested_action=suggested_action
        )
    
    def _get_suggested_action(self, intent: IntentType, query: str) -> str:
        """根据意图生成建议动作"""
        action_map = {
            IntentType.EMOTIONAL_VENTING: "emotional_support",
            IntentType.INFORMATION_QUERY: "factual_search",
            IntentType.CASUAL_CHAT: "general_chat",
            IntentType.CONFLICT_DISCUSSION: "conflict_analysis",
            IntentType.RELATIONSHIP_ADVICE: "relationship_guidance"
        }
        
        base_action = action_map.get(intent, "general_chat")
        
        # 根据情绪强度调整
        if intent == IntentType.EMOTIONAL_VENTING:
            for level, words in self.emotion_intensity.items():
                if any(word in query for word in words):
                    if level == "高":
                        return "urgent_emotional_support"
                    elif level == "中":
                        return "moderate_emotional_support"
        
        return base_action
    
    def get_search_strategy(self, intent_result: IntentResult) -> Dict:
        """
        根据意图返回搜索策略
        
        Args:
            intent_result: 意图分类结果
            
        Returns:
            Dict: 搜索策略配置
        """
        strategy_map = {
            "emotional_support": {
                "top_k": 5,
                "use_reranker": True,
                "emotion_filter": "supportive",
                "time_weight": 0.3,
                "semantic_weight": 0.7
            },
            "factual_search": {
                "top_k": 3,
                "use_reranker": True,
                "precision_filter": True,
                "time_weight": 0.1,
                "semantic_weight": 0.9
            },
            "general_chat": {
                "top_k": 2,
                "use_reranker": False,
                "speed_priority": True,
                "time_weight": 0.2,
                "semantic_weight": 0.8
            },
            "conflict_analysis": {
                "top_k": 8,
                "use_reranker": True,
                "conflict_filter": True,
                "time_weight": 0.4,
                "semantic_weight": 0.6
            },
            "relationship_guidance": {
                "top_k": 6,
                "use_reranker": True,
                "advice_filter": True,
                "time_weight": 0.3,
                "semantic_weight": 0.7
            }
        }
        
        return strategy_map.get(
            intent_result.suggested_action,
            strategy_map["general_chat"]
        )


if __name__ == '__main__':
    # 测试代码
    classifier = IntentClassifier()
    
    test_queries = [
        "今天工作好累啊",
        "什么时候吃饭",
        "在干嘛呢",
        "我们又吵架了",
        "我该怎么办",
        "要疯了，压力太大了",
        "明天几点开会"
    ]
    
    print("=== 意图分类测试 ===")
    for query in test_queries:
        result = classifier.classify(query)
        strategy = classifier.get_search_strategy(result)
        
        print(f"\n查询: {query}")
        print(f"意图: {result.intent.value}")
        print(f"置信度: {result.confidence:.2f}")
        print(f"关键词: {result.keywords}")
        print(f"建议动作: {result.suggested_action}")
        print(f"搜索策略: {strategy}")
