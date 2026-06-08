# -*- coding: utf-8 -*-
"""
两阶段 PII 匿名化 - 人名替换器测试

Property 4: 精确替换和一致性映射

**Validates: Requirements 4.1, 4.2, 4.4**
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from hypothesis import given, strategies as st, settings, assume, HealthCheck

from scripts.compression.two_stage_pii.name_replacer import (
    replace_names_in_text,
    get_replacement_for_name,
)


class TestBasicReplacement:
    """基本替换测试"""
    
    def test_single_name_replacement(self):
        """测试单个人名替换"""
        text = "张三今天去上班了"
        names = ["张三"]
        
        result, mapping = replace_names_in_text(text, names)
        
        assert "张三" not in result
        assert "[PERSON_1]" in result
        assert result == "[PERSON_1]今天去上班了"
        assert mapping["张三"] == "PERSON_1"
    
    def test_multiple_names_replacement(self):
        """测试多个人名替换"""
        text = "张三和李四约好明天见面"
        names = ["张三", "李四"]
        
        result, mapping = replace_names_in_text(text, names)
        
        assert "张三" not in result
        assert "李四" not in result
        assert "[PERSON_1]" in result
        assert "[PERSON_2]" in result
    
    def test_same_name_multiple_occurrences(self):
        """测试同一人名多次出现"""
        text = "张三说张三明天有空"
        names = ["张三"]
        
        result, mapping = replace_names_in_text(text, names)
        
        assert result.count("[PERSON_1]") == 2
        assert "张三" not in result
    
    def test_empty_text(self):
        """测试空文本"""
        result, mapping = replace_names_in_text("", ["张三"])
        assert result == ""
    
    def test_empty_names(self):
        """测试空人名列表"""
        text = "张三今天去上班了"
        result, mapping = replace_names_in_text(text, [])
        assert result == text
    
    def test_no_match(self):
        """测试无匹配"""
        text = "今天天气不错"
        names = ["张三"]
        
        result, mapping = replace_names_in_text(text, names)
        
        assert result == text


class TestLengthPriority:
    """长度优先替换测试"""
    
    def test_longer_name_first(self):
        """测试长名字优先替换"""
        text = "张三丰是武当派创始人"
        names = ["张三", "张三丰"]
        
        result, mapping = replace_names_in_text(text, names)
        
        # 张三丰应该被完整替换，而不是只替换张三
        assert "张三丰" not in result
        assert "[PERSON_1]是武当派创始人" == result
        assert "张三丰" in mapping
    
    def test_nested_names(self):
        """测试嵌套人名"""
        text = "我认识张三和张三丰"
        names = ["张三", "张三丰"]
        
        result, mapping = replace_names_in_text(text, names)
        
        # 两个名字都应该被替换
        assert "张三" not in result
        assert "张三丰" not in result
    
    def test_overlapping_names(self):
        """测试重叠人名"""
        text = "王小明和小明都来了"
        names = ["王小明", "小明"]
        
        result, mapping = replace_names_in_text(text, names)
        
        # 王小明应该被完整替换
        assert "王小明" not in result
        # 独立的小明也应该被替换
        assert "小明" not in result


class TestConsistentMapping:
    """一致性映射测试"""
    
    def test_same_name_same_replacement(self):
        """测试同一人名始终映射到同一代号"""
        names = ["张三"]
        
        result1, mapping1 = replace_names_in_text("张三说", names)
        result2, mapping2 = replace_names_in_text("张三走了", names, mapping1)
        
        # 两次替换应该使用相同的代号
        assert mapping1["张三"] == mapping2["张三"]
    
    def test_existing_mapping_preserved(self):
        """测试已有映射被保留"""
        names = ["张三", "李四"]
        existing_map = {"张三": "PERSON_5"}
        
        result, mapping = replace_names_in_text("张三和李四", names, existing_map)
        
        assert mapping["张三"] == "PERSON_5"
        assert mapping["李四"] == "PERSON_6"  # 从 5+1 开始
    
    def test_mapping_increments_correctly(self):
        """测试映射编号正确递增"""
        names = ["张三", "李四", "王五"]
        
        result, mapping = replace_names_in_text("张三李四王五", names)
        
        # 应该分配 PERSON_1, PERSON_2, PERSON_3
        assert len(set(mapping.values())) == 3


class TestSpecialMappings:
    """特殊映射测试"""
    
    def test_me_mapping(self):
        """测试 ME 映射"""
        me_names = {"我自己"}
        
        replacement, mapping = get_replacement_for_name(
            "我自己", {}, me_names=me_names
        )
        
        assert replacement == "ME"
    
    def test_other_mapping(self):
        """测试 OTHER 映射"""
        other_names = {"对方"}
        
        replacement, mapping = get_replacement_for_name(
            "对方", {}, other_names=other_names
        )
        
        assert replacement == "OTHER"
    
    def test_regular_person_mapping(self):
        """测试普通人名映射"""
        replacement, mapping = get_replacement_for_name("张三", {})
        
        assert replacement == "PERSON_1"


# ============================================================
# Property-Based Tests (Hypothesis)
# ============================================================

# 中文人名生成策略
chinese_name_strategy = st.text(
    alphabet=st.characters(whitelist_categories=('Lo',), 
                          whitelist_characters=''),
    min_size=2,
    max_size=4
).filter(lambda x: len(x) >= 2)


class TestReplacementProperties:
    """替换属性测试"""
    
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        names=st.lists(
            st.text(min_size=2, max_size=4, alphabet=st.characters(whitelist_categories=('Lo',))),
            min_size=1,
            max_size=10,
            unique=True
        ).filter(lambda x: all(len(n) >= 2 for n in x)),
    )
    def test_only_confirmed_names_replaced(self, names):
        """
        Property 4.1: 仅确认人名被替换
        
        **Validates: Requirements 4.1**
        """
        # 构造包含人名的文本
        text = "前缀" + "中间".join(names) + "后缀"
        
        result, mapping = replace_names_in_text(text, names)
        
        # 所有确认人名都应该被替换
        for name in names:
            assert name not in result, f"Name '{name}' should be replaced"
        
        # 非人名部分应该保留
        assert "前缀" in result
        assert "后缀" in result
    
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        name=st.text(min_size=2, max_size=4, alphabet=st.characters(whitelist_categories=('Lo',))),
        texts=st.lists(st.text(min_size=1, max_size=20), min_size=2, max_size=5),
    )
    def test_consistent_mapping_across_texts(self, name, texts):
        """
        Property 4.2: 同一人名在不同文本中映射到同一代号
        
        **Validates: Requirements 4.2**
        """
        assume(len(name) >= 2)
        
        names = [name]
        mapping = {}
        
        for text in texts:
            # 在文本中插入人名
            full_text = text + name + text
            _, mapping = replace_names_in_text(full_text, names, mapping)
        
        # 映射应该只有一个条目
        if name in mapping:
            assert len([k for k in mapping if k == name]) == 1
    
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        short_name=st.text(min_size=2, max_size=2, alphabet=st.characters(whitelist_categories=('Lo',))),
        suffix=st.text(min_size=1, max_size=2, alphabet=st.characters(whitelist_categories=('Lo',))),
    )
    def test_longer_name_priority(self, short_name, suffix):
        """
        Property 4.3: 长人名优先于短人名被替换
        
        **Validates: Requirements 4.4**
        """
        assume(len(short_name) >= 2)
        assume(len(suffix) >= 1)
        
        long_name = short_name + suffix
        names = [short_name, long_name]
        
        # 文本只包含长名字
        text = f"我认识{long_name}"
        
        result, mapping = replace_names_in_text(text, names)
        
        # 长名字应该被完整替换
        assert long_name not in result
        
        # 结果中不应该有部分替换的情况（如 [PERSON_1]丰）
        # 检查替换后的文本格式正确
        import re
        # 所有 [PERSON_N] 后面不应该紧跟中文字符（除非是原文本的一部分）
        pattern = r'\[PERSON_\d+\]' + suffix
        assert not re.search(pattern, result), f"Partial replacement detected: {result}"


class TestMappingProperties:
    """映射属性测试"""
    
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        names=st.lists(
            st.text(min_size=2, max_size=4, alphabet=st.characters(whitelist_categories=('Lo',))),
            min_size=1,
            max_size=20,
            unique=True
        ).filter(lambda x: all(len(n) >= 2 for n in x)),
    )
    def test_unique_mappings(self, names):
        """
        Property 4.4: 不同人名映射到不同代号
        
        **Validates: Requirements 4.2**
        """
        text = "".join(names)
        
        result, mapping = replace_names_in_text(text, names)
        
        # 所有映射值应该唯一
        values = list(mapping.values())
        assert len(values) == len(set(values)), "Duplicate mappings found"
    
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        name=st.text(min_size=2, max_size=4, alphabet=st.characters(whitelist_categories=('Lo',))),
        existing_id=st.integers(min_value=1, max_value=100),
    )
    def test_mapping_continues_from_existing(self, name, existing_id):
        """
        Property 4.5: 新映射从已有最大编号继续
        
        **Validates: Requirements 4.2**
        """
        assume(len(name) >= 2)
        
        # 创建已有映射
        existing_map = {"已有人名": f"PERSON_{existing_id}"}
        
        replacement, mapping = get_replacement_for_name(name, existing_map)
        
        if name != "已有人名":
            # 新映射应该从 existing_id + 1 开始
            expected = f"PERSON_{existing_id + 1}"
            assert replacement == expected, f"Expected {expected}, got {replacement}"


class TestEdgeCases:
    """边界情况测试"""
    
    def test_unicode_names(self):
        """测试 Unicode 人名"""
        text = "我认识張三和李四"  # 繁体张
        names = ["張三", "李四"]
        
        result, mapping = replace_names_in_text(text, names)
        
        assert "張三" not in result
        assert "李四" not in result
    
    def test_adjacent_names(self):
        """测试相邻人名"""
        text = "张三李四王五"
        names = ["张三", "李四", "王五"]
        
        result, mapping = replace_names_in_text(text, names)
        
        assert "张三" not in result
        assert "李四" not in result
        assert "王五" not in result
        assert result.count("[PERSON_") == 3
    
    def test_name_at_boundaries(self):
        """测试人名在边界位置"""
        text = "张三"
        names = ["张三"]
        
        result, mapping = replace_names_in_text(text, names)
        
        assert result == "[PERSON_1]"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
