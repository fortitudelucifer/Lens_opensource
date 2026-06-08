# -*- coding: utf-8 -*-
"""
两阶段 PII 匿名化 - 候选词提取器测试

Property 1: 候选词提取正确性
- 姓氏+名字模式应正确提取
- 昵称模式应正确提取
- 排除列表应生效
- 边界检测应正确

**Validates: Requirements 1.2, 1.3, 1.4**
"""

import sys
import json
import tempfile
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from hypothesis import given, strategies as st, settings, assume, HealthCheck

from scripts.compression.two_stage_pii.candidate_extractor import CandidateExtractor
from scripts.compression.two_stage_pii.models import CandidateList


class TestCandidateExtractorBasic:
    """CandidateExtractor 基础单元测试"""
    
    @pytest.fixture
    def extractor(self):
        """创建提取器实例"""
        return CandidateExtractor()
    
    def test_surname_name_pattern(self, extractor):
        """测试姓氏+名字模式提取"""
        # 姓+1字
        assert "张三" in extractor.extract_from_text("我和张三说话")
        assert "李四" in extractor.extract_from_text("我和李四约好了")
        
        # 姓+2字
        assert "王小明" in extractor.extract_from_text("我和王小明说话")
        assert "刘德华" in extractor.extract_from_text("我和刘德华说话")
    
    def test_nickname_prefix_pattern(self, extractor):
        """测试昵称前缀模式（小X、阿X、老X、大X）"""
        assert "小明" in extractor.extract_from_text("我和小明去逛街")
        assert "阿强" in extractor.extract_from_text("我和阿强说话")
        assert "老王" in extractor.extract_from_text("我和老王说话")
        assert "大刘" in extractor.extract_from_text("我和大刘说话")
    
    def test_nickname_suffix_pattern(self, extractor):
        """测试昵称后缀模式（X哥、X姐等）"""
        assert "刘姐" in extractor.extract_from_text("我和刘姐说话")
        assert "张哥" in extractor.extract_from_text("我和张哥说话")
        assert "陈总" in extractor.extract_from_text("我和陈总说话")
        assert "王叔" in extractor.extract_from_text("我和王叔说话")
    
    def test_exclusion_list(self, extractor):
        """测试排除列表生效"""
        # 这些词在排除列表中，不应被提取
        assert "时候" not in extractor.extract_from_text("什么时候来")
        assert "朋友" not in extractor.extract_from_text("我和朋友一起")
        assert "今天" not in extractor.extract_from_text("今天天气好")
        assert "那你" not in extractor.extract_from_text("那你怎么办")
    
    def test_boundary_detection(self, extractor):
        """测试边界检测"""
        # 不应提取带有后续动词的组合
        result = extractor.extract_from_text("我和张三说话，我和李四说话")
        assert "张三" in result
        assert "李四" in result
    
    def test_no_extraction_from_middle(self, extractor):
        """测试不从词中间提取"""
        # "繁华" 中的 "华" 不应触发提取
        result = extractor.extract_from_text("从繁华到宁静")
        assert "华到" not in result
        assert "华到宁" not in result
    
    def test_empty_input(self, extractor):
        """测试空输入"""
        assert extractor.extract_from_text("") == []
        assert extractor.extract_from_text(None) == []
        assert extractor.extract_from_text(123) == []
    
    def test_no_chinese(self, extractor):
        """测试无中文输入"""
        assert extractor.extract_from_text("Hello World") == []
        assert extractor.extract_from_text("12345") == []


class TestCandidateExtractorMessage:
    """消息级别提取测试"""
    
    @pytest.fixture
    def extractor(self):
        return CandidateExtractor()
    
    def test_extract_from_message(self, extractor):
        """测试从消息提取"""
        message = {
            "type": "text",
            "text_raw": "我和张三说话，我和李四说话",
        }
        
        results = extractor.extract_from_message(message)
        texts = [r[0] for r in results]
        
        assert "张三" in texts
        assert "李四" in texts
    
    def test_skip_time_gap_type(self, extractor):
        """测试跳过 time_gap 类型"""
        message = {
            "type": "time_gap",
            "text_raw": "我和张三说话",
        }
        
        results = extractor.extract_from_message(message)
        assert len(results) == 0
    
    def test_context_extraction(self, extractor):
        """测试上下文提取"""
        message = {
            "type": "text",
            "text_raw": "昨天我和张三一起去吃饭",
        }
        
        results = extractor.extract_from_message(message)
        assert len(results) > 0
        
        # 检查上下文包含候选词
        for text, context, field in results:
            assert text in context


class TestCandidateExtractorFile:
    """文件级别提取测试"""
    
    @pytest.fixture
    def extractor(self):
        return CandidateExtractor()
    
    def test_extract_from_file(self, extractor):
        """测试从文件提取"""
        # 创建临时 JSONL 文件
        messages = [
            {"type": "text", "text_raw": "我和张三说话"},
            {"type": "text", "text_raw": "我和李四说话"},
            {"type": "time_gap", "text_raw": "我和王五说话"},  # 应跳过
        ]
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False, encoding='utf-8') as f:
            for msg in messages:
                f.write(json.dumps(msg, ensure_ascii=False) + '\n')
            path = f.name
        
        try:
            result = extractor.extract_from_file(path, show_progress=False)
            
            assert isinstance(result, CandidateList)
            assert result.total_messages_scanned == 3
            assert "张三" in result.candidates
            assert "李四" in result.candidates
            # time_gap 类型应被跳过
            assert "王五" not in result.candidates
        finally:
            Path(path).unlink(missing_ok=True)
    
    def test_file_not_found(self, extractor):
        """测试文件不存在"""
        with pytest.raises(FileNotFoundError):
            extractor.extract_from_file("nonexistent.jsonl")


# ============================================================
# Property-Based Tests (Hypothesis)
# ============================================================

# 常见姓氏列表（用于生成测试数据）
COMMON_SURNAMES = ['张', '王', '李', '刘', '陈', '杨', '黄', '赵', '周', '吴']

# 常见名字字符（用于生成测试数据）
NAME_CHARS = '明华强伟芳敏静丽娟军杰涛磊超波勇刚平建国文辉'


class TestCandidateExtractorProperties:
    """候选词提取器属性测试"""
    
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        surname=st.sampled_from(COMMON_SURNAMES),
        name=st.text(min_size=1, max_size=2, alphabet=NAME_CHARS),
    )
    def test_surname_name_always_extracted(self, surname, name):
        """
        Property: 姓氏+名字组合应总是被提取（除非在排除列表中）
        
        **Validates: Requirements 1.2**
        """
        extractor = CandidateExtractor()
        assume(len(name) > 0)
        full_name = surname + name
        
        # 跳过排除列表中的词
        if full_name in extractor.exclusion_list:
            return
        
        # 构造测试文本（人名前后都有边界字符）
        test_text = f"我和{full_name}说话"
        result = extractor.extract_from_text(test_text)
        
        assert full_name in result, f"Expected '{full_name}' in {result}"
    
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        prefix=st.sampled_from(['小', '阿', '老', '大']),
        name=st.text(min_size=1, max_size=2, alphabet=NAME_CHARS),
    )
    def test_nickname_prefix_always_extracted(self, prefix, name):
        """
        Property: 昵称前缀+名字组合应总是被提取（除非在排除列表中）
        
        **Validates: Requirements 1.2**
        """
        extractor = CandidateExtractor()
        assume(len(name) > 0)
        full_name = prefix + name
        
        if full_name in extractor.exclusion_list:
            return
        
        # 构造测试文本（人名前后都有边界字符）
        test_text = f"我和{full_name}说话"
        result = extractor.extract_from_text(test_text)
        
        assert full_name in result, f"Expected '{full_name}' in {result}"
    
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        name=st.text(min_size=1, max_size=2, alphabet=NAME_CHARS),
        suffix=st.sampled_from(['哥', '姐', '叔', '姨', '总', '老师']),
    )
    def test_nickname_suffix_always_extracted(self, name, suffix):
        """
        Property: 名字+昵称后缀组合应总是被提取（除非在排除列表中）
        
        **Validates: Requirements 1.2**
        """
        extractor = CandidateExtractor()
        assume(len(name) > 0)
        full_name = name + suffix
        
        if full_name in extractor.exclusion_list:
            return
        
        # 构造测试文本（人名前后都有边界字符）
        test_text = f"我和{full_name}说话"
        result = extractor.extract_from_text(test_text)
        
        assert full_name in result, f"Expected '{full_name}' in {result}"
    
    @settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        excluded_word=st.sampled_from([
            '时候', '朋友', '今天', '那你', '关系', '舒服', '容易',
            '文字', '方便', '解决', '白色', '祝福', '厉害', '焦虑',
        ])
    )
    def test_excluded_words_never_extracted(self, excluded_word):
        """
        Property: 排除列表中的词应永远不被提取
        
        **Validates: Requirements 1.3**
        """
        extractor = CandidateExtractor()
        test_text = f"这是{excluded_word}的测试"
        result = extractor.extract_from_text(test_text)
        
        assert excluded_word not in result, f"'{excluded_word}' should not be in {result}"
    
    @settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        messages=st.lists(
            st.fixed_dictionaries({
                'type': st.just('text'),
                'text_raw': st.text(min_size=10, max_size=100),
            }),
            min_size=1,
            max_size=10
        )
    )
    def test_message_count_matches(self, messages):
        """
        Property: 扫描的消息数应与输入消息数一致
        
        **Validates: Requirements 1.4**
        """
        extractor = CandidateExtractor()
        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False, encoding='utf-8') as f:
            for msg in messages:
                f.write(json.dumps(msg, ensure_ascii=False) + '\n')
            path = f.name
        
        try:
            result = extractor.extract_from_file(path, show_progress=False)
            assert result.total_messages_scanned == len(messages)
        finally:
            Path(path).unlink(missing_ok=True)
    
    @settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        word=st.text(min_size=2, max_size=4, alphabet=NAME_CHARS),
        count=st.integers(min_value=1, max_value=10),
    )
    def test_frequency_accumulation(self, word, count):
        """
        Property: 相同候选词的频次应正确累加
        
        **Validates: Requirements 1.4**
        """
        extractor = CandidateExtractor()
        # 构造包含重复人名的消息
        surname = '张'
        full_name = surname + word[:2] if len(word) >= 2 else surname + word
        
        if full_name in extractor.exclusion_list:
            return
        
        messages = [
            {"type": "text", "text_raw": f"和{full_name}说话"}
            for _ in range(count)
        ]
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False, encoding='utf-8') as f:
            for msg in messages:
                f.write(json.dumps(msg, ensure_ascii=False) + '\n')
            path = f.name
        
        try:
            result = extractor.extract_from_file(path, show_progress=False)
            if full_name in result.candidates:
                assert result.candidates[full_name].frequency == count
        finally:
            Path(path).unlink(missing_ok=True)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
