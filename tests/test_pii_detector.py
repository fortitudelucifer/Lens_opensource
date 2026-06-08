# -*- coding: utf-8 -*-
"""
PII 检测器测试

测试规则引擎检测架构：
1. 正则规则（电话、邮箱、身份证等）
2. 配置映射（已知人名、地名）

注意：GLiNER 已废弃（2026-02-06），人名检测请使用两阶段 PII 系统
详见 tests/test_two_stage_pii_models.py

运行测试：
    pytest tests/test_pii_detector.py -v
"""

import pytest
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.compression.pii_detector import PIIDetector, PIIMatch


class TestPIIDetectorRegex:
    """测试规则引擎检测"""
    
    @pytest.fixture
    def detector(self):
        """创建检测器"""
        return PIIDetector()
    
    def test_phone_detection(self, detector):
        """测试手机号检测"""
        text = "我的电话是13812345678"
        matches = detector.detect(text)
        
        assert len(matches) >= 1
        phone_matches = [m for m in matches if m.type == 'PHONE']
        assert len(phone_matches) == 1
        assert phone_matches[0].value == "13812345678"
        assert phone_matches[0].confidence == 1.0
        assert phone_matches[0].source == 'regex'
    
    def test_email_detection(self, detector):
        """测试邮箱检测"""
        text = "邮箱是test@example.com"
        matches = detector.detect(text)
        
        email_matches = [m for m in matches if m.type == 'EMAIL']
        assert len(email_matches) == 1
        assert email_matches[0].value == "test@example.com"
    
    def test_wechat_id_detection(self, detector):
        """测试微信ID检测"""
        text = "微信号是wxid_abc123xyz"
        matches = detector.detect(text)
        
        wechat_matches = [m for m in matches if m.type == 'WECHAT_ID']
        assert len(wechat_matches) == 1
        assert wechat_matches[0].value == "wxid_abc123xyz"
    
    def test_id_card_detection(self, detector):
        """测试身份证号检测"""
        text = "身份证号是110101199001011234"
        matches = detector.detect(text)
        
        id_matches = [m for m in matches if m.type == 'ID_CARD']
        assert len(id_matches) == 1
        assert id_matches[0].value == "110101199001011234"
    
    def test_multiple_pii(self, detector):
        """测试多个 PII 检测"""
        text = "电话13812345678，邮箱test@example.com，微信wxid_abc123"
        matches = detector.detect(text)
        
        assert len(matches) >= 3
        types = {m.type for m in matches}
        assert 'PHONE' in types
        assert 'EMAIL' in types
        assert 'WECHAT_ID' in types
    
    def test_empty_text(self, detector):
        """测试空文本"""
        assert detector.detect("") == []
        assert detector.detect("   ") == []
    
    def test_no_pii(self, detector):
        """测试无 PII 文本"""
        text = "今天天气真好"
        matches = detector.detect(text)
        
        # 可能检测到日期，但不应该有其他 PII
        non_date_matches = [m for m in matches if m.type != 'DATE']
        assert len(non_date_matches) == 0


class TestPIIDetectorConfig:
    """测试配置映射检测"""
    
    @pytest.fixture
    def detector(self):
        """创建检测器"""
        detector = PIIDetector()
        # 添加测试用的已知实体
        detector.known_entities['PERSON'] = ['张三', '李四']
        detector.known_entities['LOCATION'] = ['北京', '上海']
        return detector
    
    def test_known_person_detection(self, detector):
        """测试已知人名检测"""
        text = "张三和李四约好见面"
        matches = detector.detect(text)
        
        person_matches = [m for m in matches if m.type == 'PERSON']
        assert len(person_matches) == 2
        values = {m.value for m in person_matches}
        assert '张三' in values
        assert '李四' in values
    
    def test_known_location_detection(self, detector):
        """测试已知地名检测"""
        text = "从北京到上海"
        matches = detector.detect(text)
        
        loc_matches = [m for m in matches if m.type == 'LOCATION']
        assert len(loc_matches) == 2


class TestPIIDetectorIntegration:
    """集成测试"""
    
    @pytest.fixture
    def detector(self):
        """创建完整检测器"""
        return PIIDetector()
    
    def test_mixed_detection(self, detector):
        """测试混合检测"""
        text = "电话是13812345678，邮箱是zhangsan@example.com"
        matches = detector.detect(text)
        
        types = {m.type for m in matches}
        assert 'PHONE' in types
        assert 'EMAIL' in types
    
    def test_deduplication(self, detector):
        """测试去重"""
        detector.known_entities['PERSON'] = ['张三']
        
        text = "张三说张三的电话是13812345678"
        matches = detector.detect(text)
        
        person_matches = [m for m in matches if m.type == 'PERSON']
        values = {m.value for m in person_matches}
        assert '张三' in values
    
    def test_stats(self, detector):
        """测试统计信息"""
        text = "电话13812345678，邮箱test@example.com"
        detector.detect(text)
        
        stats = detector.get_stats()
        assert stats["total_detections"] >= 2
        assert stats["regex_detections"] >= 2
    
    def test_unload_models(self, detector):
        """测试模型卸载（保留接口兼容性）"""
        detector.detect("测试文本")
        detector.unload_models()
        # 应该能正常调用（无操作）


class TestPIIDetectorEdgeCases:
    """边界情况测试"""
    
    @pytest.fixture
    def detector(self):
        """创建检测器"""
        return PIIDetector()
    
    def test_partial_phone(self, detector):
        """测试部分手机号"""
        text = "电话138123"  # 不完整的手机号
        matches = detector.detect(text)
        
        phone_matches = [m for m in matches if m.type == 'PHONE']
        assert len(phone_matches) == 0
    
    def test_special_characters(self, detector):
        """测试特殊字符"""
        text = "邮箱是test+tag@example.com"
        matches = detector.detect(text)
        
        email_matches = [m for m in matches if m.type == 'EMAIL']
        assert len(email_matches) == 1
    
    def test_unicode_text(self, detector):
        """测试 Unicode 文本"""
        text = "电话📱13812345678"
        matches = detector.detect(text)
        
        phone_matches = [m for m in matches if m.type == 'PHONE']
        assert len(phone_matches) == 1
    
    def test_long_text(self, detector):
        """测试长文本"""
        text = "这是一段很长的文本。" * 100 + "电话13812345678"
        matches = detector.detect(text)
        
        phone_matches = [m for m in matches if m.type == 'PHONE']
        assert len(phone_matches) == 1


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
