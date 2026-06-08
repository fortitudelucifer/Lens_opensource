# -*- coding: utf-8 -*-
"""
PrivacyShield 集成测试

测试 PrivacyShield 与两阶段 PII 检测的集成
"""

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest
import yaml

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.compression.privacy_shield import PrivacyShield


class TestPrivacyShieldBasic:
    """基础功能测试"""
    
    def test_init_without_two_stage_pii(self):
        """测试不使用两阶段 PII 初始化"""
        shield = PrivacyShield(use_two_stage_pii=False)
        assert shield is not None
        assert shield._use_two_stage_pii == False
    
    def test_detect_phone(self):
        """测试电话号码检测"""
        shield = PrivacyShield(use_two_stage_pii=False)
        matches = shield.detect_pii("我的电话是13812345678")
        
        phone_matches = [m for m in matches if m.type == 'phone']
        assert len(phone_matches) == 1
        assert phone_matches[0].value == '13812345678'
    
    def test_detect_email(self):
        """测试邮箱检测"""
        shield = PrivacyShield(use_two_stage_pii=False)
        matches = shield.detect_pii("邮箱是test@example.com")
        
        email_matches = [m for m in matches if m.type == 'email']
        assert len(email_matches) == 1
        assert email_matches[0].value == 'test@example.com'
    
    def test_detect_wechat_id(self):
        """测试微信ID检测"""
        shield = PrivacyShield(use_two_stage_pii=False)
        matches = shield.detect_pii("微信号是wxid_abc123xyz")
        
        wechat_matches = [m for m in matches if m.type == 'wechat_id']
        assert len(wechat_matches) == 1
        assert wechat_matches[0].value == 'wxid_abc123xyz'


class TestPrivacyShieldAnonymization:
    """匿名化测试"""
    
    def test_anonymize_l1_phone(self):
        """测试 L1 电话号码匿名化"""
        shield = PrivacyShield(use_two_stage_pii=False)
        message = {'text_raw': '我的电话是13812345678'}
        
        result = shield.anonymize_l1(message)
        
        assert '[电话号码]' in result['text_raw']
        assert '13812345678' not in result['text_raw']
    
    def test_anonymize_l1_email(self):
        """测试 L1 邮箱匿名化"""
        shield = PrivacyShield(use_two_stage_pii=False)
        message = {'text_raw': '邮箱是test@example.com'}
        
        result = shield.anonymize_l1(message)
        
        assert '[邮箱]' in result['text_raw']
        assert 'test@example.com' not in result['text_raw']
    
    def test_anonymize_l2_timestamp(self):
        """测试 L2 时间戳处理"""
        shield = PrivacyShield(use_two_stage_pii=False)
        shield.set_base_timestamp(1700000000)
        
        message = {
            'text_raw': '测试消息',
            'ts': 1700086400,  # 基准时间 + 1天
            'time_local': '2023-11-15 12:00:00'
        }
        
        result = shield.anonymize_l2(message)
        
        # 检查时间戳泛化
        assert 'ts_generalized' in result
        assert 'period' in result['ts_generalized']
        assert 'day_type' in result['ts_generalized']
        
        # 检查时间戳偏移
        assert 'ts_shifted' in result
        
        # 检查相对时间
        assert 'day_index' in result
        assert result['day_index'] == 1  # 第2天（索引从0开始）
    
    def test_anonymize_recall_message(self):
        """测试撤回消息匿名化"""
        shield = PrivacyShield(use_two_stage_pii=False)
        
        # 中文格式
        message = {'text_raw': '"张三" 撤回了一条消息'}
        result = shield.anonymize_l1(message)
        assert result['text_raw'] == 'OTHER 撤回了一条消息'
        
        # 英文格式
        message = {'text_raw': '"John" recalled a message'}
        result = shield.anonymize_l1(message)
        assert result['text_raw'] == 'OTHER recalled a message'


class TestPrivacyShieldWithTwoStagePII:
    """两阶段 PII 集成测试"""
    
    @pytest.fixture
    def temp_confirmed_names(self):
        """创建临时确认人名文件"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            data = {
                'version': '1.0',
                'generated_at': '2026-02-07T00:00:00',
                'source_file': 'test.jsonl',
                'confirmed_names': [
                    {'text': '张三', 'category': 'real_name', 'frequency': 5, 'contexts': []},
                    {'text': '李四', 'category': 'real_name', 'frequency': 3, 'contexts': []},
                    {'text': '王五', 'category': 'common', 'frequency': 2, 'contexts': []},  # 不是人名
                ]
            }
            yaml.dump(data, f, allow_unicode=True)
            temp_path = f.name
        
        yield temp_path
        
        # 清理
        os.unlink(temp_path)
    
    def test_two_stage_pii_detection(self, temp_confirmed_names):
        """测试两阶段 PII 检测"""
        shield = PrivacyShield(
            use_two_stage_pii=True,
            confirmed_names_path=temp_confirmed_names
        )
        
        # 检测人名
        matches = shield.detect_pii("张三和李四约好明天见面")
        
        person_matches = [m for m in matches if m.type == 'person']
        assert len(person_matches) == 2
        
        names = {m.value for m in person_matches}
        assert '张三' in names
        assert '李四' in names
    
    def test_two_stage_pii_only_real_names(self, temp_confirmed_names):
        """测试只检测真实人名，不检测常见词"""
        shield = PrivacyShield(
            use_two_stage_pii=True,
            confirmed_names_path=temp_confirmed_names
        )
        
        # 王五 被标记为 common，不应该被检测
        matches = shield.detect_pii("王五也来了")
        
        person_matches = [m for m in matches if m.type == 'person']
        assert len(person_matches) == 0
    
    def test_two_stage_pii_with_phone(self, temp_confirmed_names):
        """测试两阶段 PII 与电话号码同时检测"""
        shield = PrivacyShield(
            use_two_stage_pii=True,
            confirmed_names_path=temp_confirmed_names
        )
        
        matches = shield.detect_pii("张三的电话是13812345678")
        
        person_matches = [m for m in matches if m.type == 'person']
        phone_matches = [m for m in matches if m.type == 'phone']
        
        assert len(person_matches) == 1
        assert len(phone_matches) == 1
    
    def test_anonymize_with_two_stage_pii(self, temp_confirmed_names):
        """测试使用两阶段 PII 的匿名化"""
        shield = PrivacyShield(
            use_two_stage_pii=True,
            confirmed_names_path=temp_confirmed_names
        )
        
        message = {'text_raw': '张三和李四约好明天见面'}
        result = shield.anonymize_l1(message)
        
        # 人名应该被替换
        assert '张三' not in result['text_raw']
        assert '李四' not in result['text_raw']
        
        # 应该有替换标记
        assert '[' in result['text_raw']


class TestPrivacyShieldStats:
    """统计信息测试"""
    
    def test_stats_tracking(self):
        """测试统计信息跟踪"""
        shield = PrivacyShield(use_two_stage_pii=False)
        
        # 处理一些消息
        messages = [
            {'text_raw': '电话13812345678'},
            {'text_raw': '邮箱test@example.com'},
            {'text_raw': '普通消息'},
        ]
        
        for msg in messages:
            shield.anonymize_l1(msg)
        
        stats = shield.get_stats()
        
        assert stats['total_processed'] == 3
        assert stats['phones_replaced'] == 1
        assert stats['emails_replaced'] == 1


class TestPrivacyShieldEdgeCases:
    """边界情况测试"""
    
    def test_empty_message(self):
        """测试空消息"""
        shield = PrivacyShield(use_two_stage_pii=False)
        
        message = {'text_raw': ''}
        result = shield.anonymize_l1(message)
        
        assert result['text_raw'] == ''
    
    def test_none_text_raw(self):
        """测试 text_raw 为 None"""
        shield = PrivacyShield(use_two_stage_pii=False)
        
        message = {'text_raw': None}
        result = shield.anonymize_l1(message)
        
        assert result['text_raw'] is None
    
    def test_time_gap_message(self):
        """测试 time_gap 类型消息不被匿名化"""
        shield = PrivacyShield(use_two_stage_pii=False)
        
        message = {
            'type': 'time_gap',
            'text_raw': '[8天19小时后]'
        }
        result = shield.anonymize_l1(message)
        
        # time_gap 的 text_raw 不应该被修改
        assert result['text_raw'] == '[8天19小时后]'
    
    def test_link_quote_text_prefix_preserved(self):
        """测试引用文本的 ME:/OTHER: 前缀被保留"""
        shield = PrivacyShield(use_two_stage_pii=False)
        
        message = {'link_quote_text': 'ME: 我的电话是13812345678'}
        result = shield.anonymize_l1(message)
        
        assert result['link_quote_text'].startswith('ME: ')
        assert '[电话号码]' in result['link_quote_text']


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
