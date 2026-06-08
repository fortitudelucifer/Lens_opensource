# -*- coding: utf-8 -*-
"""
两阶段 PII 匿名化 - 数据模型测试

Property 1: 候选词提取正确性（序列化部分）
- YAML 序列化/反序列化保持数据一致性
"""

import sys
import tempfile
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from hypothesis import given, strategies as st, settings

from scripts.compression.two_stage_pii.models import (
    CandidateWord, CandidateList, ValidationResult, 
    ConfirmedName, ConfirmedNames
)


class TestCandidateWord:
    """CandidateWord 单元测试"""
    
    def test_basic_creation(self):
        """测试基本创建"""
        word = CandidateWord(text="张三")
        assert word.text == "张三"
        assert word.frequency == 1
        assert word.contexts == []
        assert word.source_fields == set()
    
    def test_add_context(self):
        """测试添加上下文"""
        word = CandidateWord(text="张三")
        word.add_context("张三说今天天气不错")
        word.add_context("我和张三约好了")
        word.add_context("张三的电话是...")
        word.add_context("第四个上下文不应该被添加")
        
        assert len(word.contexts) == 3
    
    def test_context_truncation(self):
        """测试长上下文截断"""
        word = CandidateWord(text="张三")
        long_context = "a" * 200
        word.add_context(long_context)
        
        assert len(word.contexts[0]) <= 103  # 100 + "..."
    
    def test_to_dict_from_dict(self):
        """测试序列化/反序列化"""
        word = CandidateWord(
            text="张三",
            frequency=5,
            contexts=["上下文1", "上下文2"],
            source_fields={"text_raw", "image_caption"}
        )
        
        data = word.to_dict()
        restored = CandidateWord.from_dict(data)
        
        assert restored.text == word.text
        assert restored.frequency == word.frequency
        assert restored.contexts == word.contexts
        assert restored.source_fields == word.source_fields


class TestCandidateList:
    """CandidateList 单元测试"""
    
    def test_add_candidate(self):
        """测试添加候选词"""
        cl = CandidateList()
        cl.add_candidate("张三", "张三说...", "text_raw")
        cl.add_candidate("张三", "和张三一起", "image_caption")
        cl.add_candidate("李四", "李四来了", "text_raw")
        
        assert len(cl) == 2
        assert cl.candidates["张三"].frequency == 2
        assert cl.candidates["李四"].frequency == 1
        assert "text_raw" in cl.candidates["张三"].source_fields
        assert "image_caption" in cl.candidates["张三"].source_fields
    
    def test_to_list_sorted(self):
        """测试按频次排序"""
        cl = CandidateList()
        cl.add_candidate("张三")
        cl.add_candidate("李四")
        cl.add_candidate("李四")
        cl.add_candidate("李四")
        cl.add_candidate("王五")
        cl.add_candidate("王五")
        
        sorted_list = cl.to_list()
        assert sorted_list[0].text == "李四"
        assert sorted_list[0].frequency == 3
        assert sorted_list[1].text == "王五"
        assert sorted_list[2].text == "张三"
    
    def test_save_load(self):
        """测试保存和加载"""
        cl = CandidateList(
            total_texts_scanned=100,
            total_messages_scanned=50,
            source_file="test.jsonl"
        )
        cl.add_candidate("张三", "张三说...", "text_raw")
        cl.add_candidate("李四", "李四来了", "text_raw")
        
        with tempfile.NamedTemporaryFile(suffix='.yaml', delete=False) as f:
            path = f.name
        
        try:
            cl.save(path)
            restored = CandidateList.load(path)
            
            assert len(restored) == len(cl)
            assert restored.total_texts_scanned == cl.total_texts_scanned
            assert restored.total_messages_scanned == cl.total_messages_scanned
            assert "张三" in restored.candidates
            assert "李四" in restored.candidates
        finally:
            Path(path).unlink(missing_ok=True)


class TestValidationResult:
    """ValidationResult 单元测试"""
    
    def test_all_classified(self):
        """测试获取所有分类词汇"""
        vr = ValidationResult(
            real_names=["张三", "李四"],
            pronouns=["朋友", "同学"],
            animal_names=["猫咪"],
            common_words=["东西"],
            uncertain=["小明"]
        )
        
        all_words = vr.all_classified()
        assert len(all_words) == 7
        assert "张三" in all_words
        assert "猫咪" in all_words
    
    def test_save_load(self):
        """测试保存和加载"""
        vr = ValidationResult(
            real_names=["张三", "李四"],
            pronouns=["朋友"],
            llm_calls=5,
            total_candidates=10
        )
        
        with tempfile.NamedTemporaryFile(suffix='.yaml', delete=False) as f:
            path = f.name
        
        try:
            vr.save(path)
            restored = ValidationResult.load(path)
            
            assert restored.real_names == vr.real_names
            assert restored.pronouns == vr.pronouns
            assert restored.llm_calls == vr.llm_calls
        finally:
            Path(path).unlink(missing_ok=True)


class TestConfirmedNames:
    """ConfirmedNames 单元测试"""
    
    def test_add_remove_name(self):
        """测试添加和移除人名"""
        cn = ConfirmedNames()
        cn.add_name("张三", alias="OTHER")
        cn.add_name("李四", alias="OTHER")
        
        assert len(cn.confirmed_names) == 2
        assert cn.get_all_names() == ["张三", "李四"]
        
        cn.remove_name("张三")
        assert len(cn.confirmed_names) == 1
        assert cn.get_all_names() == ["李四"]
    
    def test_get_name_to_alias_map(self):
        """测试获取人名到别名映射"""
        cn = ConfirmedNames()
        cn.add_name("张三", alias="ME")
        cn.add_name("李四", alias="OTHER")
        cn.add_name("王五")  # 无别名
        
        mapping = cn.get_name_to_alias_map()
        assert mapping == {"张三": "ME", "李四": "OTHER"}
    
    def test_save_load(self):
        """测试保存和加载"""
        cn = ConfirmedNames(source_file="test.jsonl")
        cn.add_name("张三", alias="ME", frequency=10)
        cn.add_name("李四", alias="OTHER", frequency=5)
        cn.excluded = [{"text": "朋友", "category": "pronoun"}]
        
        with tempfile.NamedTemporaryFile(suffix='.yaml', delete=False) as f:
            path = f.name
        
        try:
            cn.save(path)
            restored = ConfirmedNames.load(path)
            
            assert len(restored.confirmed_names) == 2
            assert restored.get_all_names() == ["张三", "李四"]
            assert restored.excluded == cn.excluded
        finally:
            Path(path).unlink(missing_ok=True)


# ============================================================
# Property-Based Tests (Hypothesis)
# ============================================================

class TestCandidateWordProperties:
    """CandidateWord 属性测试"""
    
    @settings(max_examples=50)
    @given(
        text=st.text(min_size=2, max_size=4, alphabet=st.characters(whitelist_categories=('Lo',))),
        frequency=st.integers(min_value=1, max_value=1000),
    )
    def test_serialization_roundtrip(self, text, frequency):
        """Property: 序列化后反序列化应保持数据一致"""
        word = CandidateWord(text=text, frequency=frequency)
        data = word.to_dict()
        restored = CandidateWord.from_dict(data)
        
        assert restored.text == word.text
        assert restored.frequency == word.frequency


class TestCandidateListProperties:
    """CandidateList 属性测试"""
    
    @settings(max_examples=30)
    @given(
        words=st.lists(
            st.text(min_size=2, max_size=4, alphabet=st.characters(whitelist_categories=('Lo',))),
            min_size=1,
            max_size=20
        )
    )
    def test_frequency_accumulation(self, words):
        """Property: 相同词汇的频次应正确累加"""
        cl = CandidateList()
        for word in words:
            cl.add_candidate(word)
        
        # 验证频次累加正确
        from collections import Counter
        expected_counts = Counter(words)
        
        for word, count in expected_counts.items():
            assert cl.candidates[word].frequency == count
    
    @settings(max_examples=30)
    @given(
        words=st.lists(
            st.text(min_size=2, max_size=4, alphabet=st.characters(whitelist_categories=('Lo',))),
            min_size=1,
            max_size=20,
            unique=True
        )
    )
    def test_no_duplicates(self, words):
        """Property: 候选词列表应无重复"""
        cl = CandidateList()
        for word in words:
            cl.add_candidate(word)
        
        assert len(cl) == len(words)
        assert len(cl.to_list()) == len(words)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
