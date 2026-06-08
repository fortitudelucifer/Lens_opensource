# -*- coding: utf-8 -*-
"""
两阶段 PII 匿名化 - 扫描器测试

Property 5: 增量扫描正确性
Property 6: 接口兼容性

**Validates: Requirements 5.4, 6.1**
"""

import json
import sys
import tempfile
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from hypothesis import given, strategies as st, settings, assume, HealthCheck

from scripts.compression.two_stage_pii.scanner import (
    TwoStagePIIScanner,
    PIIMatch,
)
from scripts.compression.two_stage_pii.models import (
    ConfirmedName,
    ConfirmedNames,
)


class TestPIIMatchInterface:
    """PIIMatch 接口测试"""
    
    def test_pii_match_fields(self):
        """测试 PIIMatch 包含所有必需字段"""
        match = PIIMatch(
            type="PERSON",
            value="张三",
            start=0,
            end=2,
            confidence=1.0,
            source="two_stage_pii",
        )
        
        assert hasattr(match, 'type')
        assert hasattr(match, 'value')
        assert hasattr(match, 'start')
        assert hasattr(match, 'end')
        assert hasattr(match, 'confidence')
        assert hasattr(match, 'source')
    
    def test_pii_match_values(self):
        """测试 PIIMatch 值正确"""
        match = PIIMatch(
            type="PERSON",
            value="张三",
            start=5,
            end=7,
            confidence=0.95,
            source="two_stage_pii",
        )
        
        assert match.type == "PERSON"
        assert match.value == "张三"
        assert match.start == 5
        assert match.end == 7
        assert match.confidence == 0.95
        assert match.source == "two_stage_pii"


class TestScannerDetect:
    """扫描器检测测试"""
    
    @pytest.fixture
    def scanner_with_names(self, tmp_path):
        """创建带有确认人名的扫描器"""
        # 创建确认人名文件
        confirmed = ConfirmedNames()
        confirmed.add_name(ConfirmedName(text="张三", category="real_name", frequency=10))
        confirmed.add_name(ConfirmedName(text="李四", category="real_name", frequency=5))
        confirmed.add_name(ConfirmedName(text="王小明", category="real_name", frequency=3))
        
        config_path = tmp_path / "confirmed_names.yaml"
        confirmed.save(str(config_path))
        
        scanner = TwoStagePIIScanner(
            confirmed_names_path=str(config_path),
        )
        return scanner
    
    def test_detect_single_name(self, scanner_with_names):
        """测试检测单个人名"""
        text = "张三今天去上班了"
        
        matches = scanner_with_names.detect(text)
        
        assert len(matches) == 1
        assert matches[0].type == "PERSON"
        assert matches[0].value == "张三"
        assert matches[0].start == 0
        assert matches[0].end == 2
    
    def test_detect_multiple_names(self, scanner_with_names):
        """测试检测多个人名"""
        text = "张三和李四约好明天见面"
        
        matches = scanner_with_names.detect(text)
        
        assert len(matches) == 2
        values = [m.value for m in matches]
        assert "张三" in values
        assert "李四" in values
    
    def test_detect_no_match(self, scanner_with_names):
        """测试无匹配"""
        text = "今天天气不错"
        
        matches = scanner_with_names.detect(text)
        
        assert len(matches) == 0
    
    def test_detect_empty_text(self, scanner_with_names):
        """测试空文本"""
        matches = scanner_with_names.detect("")
        assert len(matches) == 0
    
    def test_detect_position_accuracy(self, scanner_with_names):
        """测试位置准确性"""
        text = "我认识张三"
        
        matches = scanner_with_names.detect(text)
        
        assert len(matches) == 1
        match = matches[0]
        assert text[match.start:match.end] == "张三"


class TestScannerAnonymize:
    """扫描器匿名化测试"""
    
    @pytest.fixture
    def scanner_with_names(self, tmp_path):
        """创建带有确认人名的扫描器"""
        confirmed = ConfirmedNames()
        confirmed.add_name(ConfirmedName(text="张三", category="real_name", frequency=10))
        confirmed.add_name(ConfirmedName(text="李四", category="real_name", frequency=5))
        
        config_path = tmp_path / "confirmed_names.yaml"
        confirmed.save(str(config_path))
        
        scanner = TwoStagePIIScanner(
            confirmed_names_path=str(config_path),
        )
        return scanner
    
    def test_anonymize_single_name(self, scanner_with_names):
        """测试匿名化单个人名"""
        text = "张三今天去上班了"
        
        result = scanner_with_names.anonymize(text)
        
        assert "张三" not in result
        assert "[PERSON_" in result
    
    def test_anonymize_multiple_names(self, scanner_with_names):
        """测试匿名化多个人名"""
        text = "张三和李四约好明天见面"
        
        result = scanner_with_names.anonymize(text)
        
        assert "张三" not in result
        assert "李四" not in result


class TestScannerStatistics:
    """扫描器统计测试"""
    
    def test_stats_not_initialized(self, tmp_path):
        """测试未初始化时的统计"""
        config_path = tmp_path / "nonexistent.yaml"
        
        scanner = TwoStagePIIScanner(
            confirmed_names_path=str(config_path),
        )
        
        stats = scanner.get_statistics()
        
        assert stats.get("status") == "not_initialized"
    
    def test_stats_with_data(self, tmp_path):
        """测试有数据时的统计"""
        confirmed = ConfirmedNames()
        confirmed.add_name(ConfirmedName(text="张三", category="real_name", frequency=10))
        confirmed.add_name(ConfirmedName(text="李四", category="real_name", frequency=5))
        confirmed.add_name(ConfirmedName(text="小明", category="uncertain", frequency=3))
        
        config_path = tmp_path / "confirmed_names.yaml"
        confirmed.save(str(config_path))
        
        scanner = TwoStagePIIScanner(
            confirmed_names_path=str(config_path),
        )
        
        stats = scanner.get_statistics()
        
        assert stats["total_names"] == 3
        assert stats["by_category"]["real_name"] == 2
        assert stats["by_category"]["uncertain"] == 1


# ============================================================
# Property-Based Tests (Hypothesis)
# ============================================================

class TestDetectProperties:
    """检测属性测试"""
    
    @pytest.fixture
    def scanner_factory(self, tmp_path):
        """创建扫描器工厂"""
        def create_scanner(names):
            confirmed = ConfirmedNames()
            for name in names:
                confirmed.add_name(ConfirmedName(
                    text=name, 
                    category="real_name", 
                    frequency=1
                ))
            
            config_path = tmp_path / "confirmed_names.yaml"
            confirmed.save(str(config_path))
            
            return TwoStagePIIScanner(
                confirmed_names_path=str(config_path),
            )
        return create_scanner
    
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        name=st.text(min_size=2, max_size=4, alphabet=st.characters(whitelist_categories=('Lo',))),
        prefix=st.text(min_size=0, max_size=10),
        suffix=st.text(min_size=0, max_size=10),
    )
    def test_position_matches_text(self, scanner_factory, name, prefix, suffix):
        """
        Property 6.1: start/end 位置与原文中的实际位置一致
        
        **Validates: Requirements 6.1**
        """
        assume(len(name) >= 2)
        
        scanner = scanner_factory([name])
        text = prefix + name + suffix
        
        matches = scanner.detect(text)
        
        for match in matches:
            # 验证位置正确
            extracted = text[match.start:match.end]
            assert extracted == match.value, f"Position mismatch: '{extracted}' != '{match.value}'"
    
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        names=st.lists(
            st.text(min_size=2, max_size=4, alphabet=st.characters(whitelist_categories=('Lo',))),
            min_size=1,
            max_size=5,
            unique=True
        ).filter(lambda x: all(len(n) >= 2 for n in x)),
    )
    def test_all_names_detected(self, scanner_factory, names):
        """
        Property 6.2: 所有确认人名都被检测到
        
        **Validates: Requirements 6.1**
        """
        scanner = scanner_factory(names)
        
        # 构造包含所有人名的文本
        text = "前缀" + "中间".join(names) + "后缀"
        
        matches = scanner.detect(text)
        detected_values = {m.value for m in matches}
        
        for name in names:
            assert name in detected_values, f"Name '{name}' not detected"
    
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        name=st.text(min_size=2, max_size=4, alphabet=st.characters(whitelist_categories=('Lo',))),
    )
    def test_return_type_is_list_of_pii_match(self, scanner_factory, name):
        """
        Property 6.3: 返回类型为 List[PIIMatch]
        
        **Validates: Requirements 6.1**
        """
        assume(len(name) >= 2)
        
        scanner = scanner_factory([name])
        text = f"测试{name}文本"
        
        matches = scanner.detect(text)
        
        assert isinstance(matches, list)
        for match in matches:
            assert isinstance(match, PIIMatch)
            assert hasattr(match, 'type')
            assert hasattr(match, 'value')
            assert hasattr(match, 'start')
            assert hasattr(match, 'end')
            assert hasattr(match, 'confidence')
            assert hasattr(match, 'source')


class TestAnonymizeProperties:
    """匿名化属性测试"""
    
    @pytest.fixture
    def scanner_factory(self, tmp_path):
        """创建扫描器工厂"""
        def create_scanner(names):
            confirmed = ConfirmedNames()
            for name in names:
                confirmed.add_name(ConfirmedName(
                    text=name, 
                    category="real_name", 
                    frequency=1
                ))
            
            config_path = tmp_path / "confirmed_names.yaml"
            confirmed.save(str(config_path))
            
            return TwoStagePIIScanner(
                confirmed_names_path=str(config_path),
            )
        return create_scanner
    
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        names=st.lists(
            st.text(min_size=2, max_size=4, alphabet=st.characters(whitelist_categories=('Lo',))),
            min_size=1,
            max_size=5,
            unique=True
        ).filter(lambda x: all(len(n) >= 2 for n in x)),
    )
    def test_all_names_anonymized(self, scanner_factory, names):
        """
        Property 6.4: 所有确认人名都被匿名化
        
        **Validates: Requirements 6.1**
        """
        scanner = scanner_factory(names)
        
        # 构造包含所有人名的文本
        text = "前缀" + "中间".join(names) + "后缀"
        
        result = scanner.anonymize(text)
        
        for name in names:
            assert name not in result, f"Name '{name}' not anonymized"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
