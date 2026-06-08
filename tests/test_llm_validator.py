# -*- coding: utf-8 -*-
"""
两阶段 PII 匿名化 - LLM 验证器测试

Property 2: 批处理划分正确性
Property 3: LLM 输出解析正确性

**Validates: Requirements 2.1, 2.3**
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from hypothesis import given, strategies as st, settings, assume, HealthCheck

from scripts.compression.two_stage_pii.llm_validator import (
    split_into_batches,
    parse_llm_response,
)


class TestBatchSplitting:
    """批处理划分测试"""
    
    def test_basic_splitting(self):
        """测试基本分批"""
        items = ['a', 'b', 'c', 'd', 'e']
        batches = split_into_batches(items, 2)
        
        assert len(batches) == 3
        assert batches[0] == ['a', 'b']
        assert batches[1] == ['c', 'd']
        assert batches[2] == ['e']
    
    def test_exact_batch_size(self):
        """测试刚好整除的情况"""
        items = ['a', 'b', 'c', 'd']
        batches = split_into_batches(items, 2)
        
        assert len(batches) == 2
        assert batches[0] == ['a', 'b']
        assert batches[1] == ['c', 'd']
    
    def test_single_batch(self):
        """测试单批次"""
        items = ['a', 'b', 'c']
        batches = split_into_batches(items, 10)
        
        assert len(batches) == 1
        assert batches[0] == ['a', 'b', 'c']
    
    def test_empty_list(self):
        """测试空列表"""
        batches = split_into_batches([], 10)
        assert len(batches) == 0


class TestResponseParsing:
    """LLM 响应解析测试"""
    
    def test_valid_json_response(self):
        """测试有效 JSON 响应"""
        response = '''
        ```json
        {
            "real_name": ["张三", "李四"],
            "pronoun": ["朋友"],
            "animal": ["猫咪"],
            "common": ["北京"],
            "uncertain": []
        }
        ```
        '''
        candidates = ["张三", "李四", "朋友", "猫咪", "北京"]
        
        result = parse_llm_response(response, candidates)
        
        assert "张三" in result['real_name']
        assert "李四" in result['real_name']
        assert "朋友" in result['pronoun']
        assert "猫咪" in result['animal']
        assert "北京" in result['common']
    
    def test_alternative_field_names(self):
        """测试替代字段名"""
        response = '''
        {
            "real_names": ["张三"],
            "pronouns": ["朋友"],
            "animals": ["猫咪"],
            "common_words": ["北京"],
            "uncertain": []
        }
        '''
        candidates = ["张三", "朋友", "猫咪", "北京"]
        
        result = parse_llm_response(response, candidates)
        
        assert "张三" in result['real_name']
        assert "朋友" in result['pronoun']
        assert "猫咪" in result['animal']
        assert "北京" in result['common']
    
    def test_missing_candidates_added_to_uncertain(self):
        """测试遗漏的候选词被添加到 uncertain"""
        response = '''
        {
            "real_name": ["张三"],
            "pronoun": [],
            "animal": [],
            "common": [],
            "uncertain": []
        }
        '''
        candidates = ["张三", "李四", "王五"]
        
        result = parse_llm_response(response, candidates)
        
        assert "张三" in result['real_name']
        assert "李四" in result['uncertain']
        assert "王五" in result['uncertain']
    
    def test_invalid_json_response(self):
        """测试无效 JSON 响应"""
        response = "这不是有效的 JSON"
        candidates = ["张三", "李四"]
        
        result = parse_llm_response(response, candidates)
        
        # 所有候选词应该在 uncertain 中
        assert "张三" in result['uncertain']
        assert "李四" in result['uncertain']
    
    def test_partial_json_response(self):
        """测试部分 JSON 响应"""
        response = '''
        一些前缀文本
        {"real_name": ["张三"]}
        一些后缀文本
        '''
        candidates = ["张三", "李四"]
        
        result = parse_llm_response(response, candidates)
        
        assert "张三" in result['real_name']
        assert "李四" in result['uncertain']


# ============================================================
# Property-Based Tests (Hypothesis)
# ============================================================

class TestBatchSplittingProperties:
    """批处理划分属性测试"""
    
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        items=st.lists(st.text(min_size=1, max_size=10), min_size=0, max_size=200),
        batch_size=st.integers(min_value=1, max_value=100),
    )
    def test_all_items_included(self, items, batch_size):
        """
        Property 2.1: 所有候选词都被分配到某个批次
        
        **Validates: Requirements 2.1**
        """
        batches = split_into_batches(items, batch_size)
        
        # 展平所有批次
        flattened = []
        for batch in batches:
            flattened.extend(batch)
        
        assert flattened == items
    
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        items=st.lists(st.text(min_size=1, max_size=10), min_size=1, max_size=200),
        batch_size=st.integers(min_value=1, max_value=100),
    )
    def test_batch_size_limit(self, items, batch_size):
        """
        Property 2.2: 每批次包含的候选词数量不超过 batch_size
        
        **Validates: Requirements 2.1**
        """
        batches = split_into_batches(items, batch_size)
        
        for batch in batches:
            assert len(batch) <= batch_size
    
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        items=st.lists(st.text(min_size=1, max_size=10), min_size=0, max_size=200, unique=True),
        batch_size=st.integers(min_value=1, max_value=100),
    )
    def test_no_duplicates_across_batches(self, items, batch_size):
        """
        Property 2.3: 批次之间无重复
        
        **Validates: Requirements 2.1**
        """
        batches = split_into_batches(items, batch_size)
        
        seen = set()
        for batch in batches:
            for item in batch:
                assert item not in seen, f"Duplicate item: {item}"
                seen.add(item)


class TestResponseParsingProperties:
    """LLM 响应解析属性测试"""
    
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        candidates=st.lists(
            st.text(min_size=2, max_size=4, alphabet=st.characters(whitelist_categories=('Lo',))),
            min_size=1,
            max_size=20,
            unique=True
        ),
    )
    def test_all_candidates_classified(self, candidates):
        """
        Property 3.1: 所有候选词都被分配到某个类别
        
        **Validates: Requirements 2.3**
        """
        # 构造一个有效的 JSON 响应，只包含部分候选词
        import json
        response_data = {
            "real_name": candidates[:len(candidates)//2],
            "pronoun": [],
            "animal": [],
            "common": [],
            "uncertain": []
        }
        response = json.dumps(response_data, ensure_ascii=False)
        
        result = parse_llm_response(response, candidates)
        
        # 收集所有分类的词
        classified = set()
        for category in result.values():
            classified.update(category)
        
        # 所有候选词都应该被分类
        for candidate in candidates:
            assert candidate in classified, f"Candidate '{candidate}' not classified"
    
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        candidates=st.lists(
            st.text(min_size=2, max_size=4, alphabet=st.characters(whitelist_categories=('Lo',))),
            min_size=1,
            max_size=20,
            unique=True
        ),
    )
    def test_invalid_response_all_uncertain(self, candidates):
        """
        Property 3.2: 无效响应时所有候选词标记为 uncertain
        
        **Validates: Requirements 2.3**
        """
        response = "这不是有效的 JSON 响应"
        
        result = parse_llm_response(response, candidates)
        
        # 所有候选词都应该在 uncertain 中
        for candidate in candidates:
            assert candidate in result['uncertain'], f"Candidate '{candidate}' not in uncertain"
    
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        real_names=st.lists(st.text(min_size=2, max_size=4), min_size=0, max_size=5, unique=True),
        pronouns=st.lists(st.text(min_size=2, max_size=4), min_size=0, max_size=5, unique=True),
        animals=st.lists(st.text(min_size=2, max_size=4), min_size=0, max_size=5, unique=True),
        common=st.lists(st.text(min_size=2, max_size=4), min_size=0, max_size=5, unique=True),
    )
    def test_valid_response_preserves_classification(self, real_names, pronouns, animals, common):
        """
        Property 3.3: 有效响应时分类被正确保留
        
        **Validates: Requirements 2.3**
        """
        import json
        
        # 确保没有重复
        all_words = set(real_names) | set(pronouns) | set(animals) | set(common)
        if len(all_words) != len(real_names) + len(pronouns) + len(animals) + len(common):
            return  # 跳过有重复的情况
        
        candidates = list(all_words)
        
        response_data = {
            "real_name": real_names,
            "pronoun": pronouns,
            "animal": animals,
            "common": common,
            "uncertain": []
        }
        response = json.dumps(response_data, ensure_ascii=False)
        
        result = parse_llm_response(response, candidates)
        
        # 验证分类被正确保留
        for name in real_names:
            assert name in result['real_name']
        for pronoun in pronouns:
            assert pronoun in result['pronoun']
        for animal in animals:
            assert animal in result['animal']
        for word in common:
            assert word in result['common']


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
