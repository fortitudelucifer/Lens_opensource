# -*- coding: utf-8 -*-
"""
时间轴后处理器测试

测试内容：
1. 消息合并逻辑
2. 时间间隔标记插入
3. 对话中断类型检测
4. 情绪感知合并
5. 快速连发检测
"""

import pytest
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.timeline.postprocess_timeline import TimelinePostprocessor


@pytest.fixture
def default_config():
    """默认配置"""
    return {
        'merge': {
            'enabled': True,
            'threshold_seconds': 60,
            'emotion_aware': True,
            'separator': ' | ',
            'skip_modalities': ['image', 'voice', 'video', 'sticker'],
            'emotion_conflicts': [['HAPPY', 'SAD'], ['HAPPY', 'ANGRY']]
        },
        'time_gap': {
            'enabled': True,
            'threshold_seconds': 7200  # 2小时
        },
        'break_detection': {
            'enabled': True,
            'cold_shoulder_keywords': ['哦', '嗯', '好'],
            'conflict_keywords': ['生气', '烦', '算了'],
            'cold_shoulder_threshold_hours': 4,
            'conflict_cooling_threshold_hours': 12
        },
        'rapid_fire': {
            'enabled': True,
            'threshold_seconds': 10,
            'min_messages': 3,
            'max_length': 20
        }
    }


@pytest.fixture
def processor(default_config):
    """创建处理器实例"""
    return TimelinePostprocessor(default_config)


class TestMessageMerge:
    """消息合并测试"""
    
    def test_merge_consecutive_text_messages(self, processor):
        """测试合并连续文本消息"""
        messages = [
            {'msg_uid': '1', 'speaker': 'ME', 'modality': 'text', 
             'text_raw': '你好', 'ts': 1000},
            {'msg_uid': '2', 'speaker': 'ME', 'modality': 'text', 
             'text_raw': '在吗', 'ts': 1030},  # 30秒后
            {'msg_uid': '3', 'speaker': 'ME', 'modality': 'text', 
             'text_raw': '有空吗', 'ts': 1050}  # 20秒后
        ]
        
        result = processor.process(messages)
        
        # 应该合并为1条消息
        assert len(result) == 1
        assert result[0]['text_raw'] == '你好 | 在吗 | 有空吗'
        assert result[0]['merged_count'] == 3
    
    def test_no_merge_different_speakers(self, processor):
        """测试不同 speaker 不合并"""
        messages = [
            {'msg_uid': '1', 'speaker': 'ME', 'modality': 'text', 
             'text_raw': '你好', 'ts': 1000},
            {'msg_uid': '2', 'speaker': 'OTHER', 'modality': 'text', 
             'text_raw': '你好', 'ts': 1030}
        ]
        
        result = processor.process(messages)
        
        # 不应该合并
        assert len(result) == 2
    
    def test_no_merge_multimodal(self, processor):
        """测试多模态消息不合并"""
        messages = [
            {'msg_uid': '1', 'speaker': 'ME', 'modality': 'text', 
             'text_raw': '看这个', 'ts': 1000},
            {'msg_uid': '2', 'speaker': 'ME', 'modality': 'image', 
             'image_summary': '一张图片', 'ts': 1030},
            {'msg_uid': '3', 'speaker': 'ME', 'modality': 'text', 
             'text_raw': '好看吗', 'ts': 1060}
        ]
        
        result = processor.process(messages)
        
        # 图片消息不参与合并，所以应该是3条
        assert len(result) == 3
    
    def test_no_merge_time_gap_exceeded(self, processor):
        """测试超过时间阈值不合并"""
        messages = [
            {'msg_uid': '1', 'speaker': 'ME', 'modality': 'text', 
             'text_raw': '你好', 'ts': 1000},
            {'msg_uid': '2', 'speaker': 'ME', 'modality': 'text', 
             'text_raw': '在吗', 'ts': 1100}  # 100秒后，超过60秒阈值
        ]
        
        result = processor.process(messages)
        
        # 不应该合并
        assert len(result) == 2


class TestTimeGapInsertion:
    """时间间隔标记测试"""
    
    def test_insert_time_gap(self, processor):
        """测试插入时间间隔标记"""
        messages = [
            {'msg_uid': '1', 'speaker': 'ME', 'modality': 'text', 
             'text_raw': '晚安', 'ts': 1000},
            {'msg_uid': '2', 'speaker': 'OTHER', 'modality': 'text', 
             'text_raw': '早上好', 'ts': 1000 + 8 * 3600}  # 8小时后
        ]
        
        result = processor.process(messages)
        
        # 应该有3条：原始2条 + 1条时间标记
        assert len(result) == 3
        
        # 中间应该是时间标记
        gap_marker = result[1]
        assert gap_marker['type'] == 'time_gap'
        assert gap_marker['modality'] == 'system'
        assert 'gap_description' in gap_marker
    
    def test_no_time_gap_below_threshold(self, processor):
        """测试低于阈值不插入时间标记"""
        messages = [
            {'msg_uid': '1', 'speaker': 'ME', 'modality': 'text', 
             'text_raw': '你好', 'ts': 1000},
            {'msg_uid': '2', 'speaker': 'OTHER', 'modality': 'text', 
             'text_raw': '你好', 'ts': 1000 + 3600}  # 1小时后，低于2小时阈值
        ]
        
        result = processor.process(messages)
        
        # 不应该插入时间标记
        assert len(result) == 2


class TestBreakTypeDetection:
    """对话中断类型检测测试"""
    
    def test_detect_normal_gap(self, processor):
        """测试检测正常间隔"""
        messages = [
            {'msg_uid': '1', 'speaker': 'ME', 'modality': 'text', 
             'text_raw': '晚安', 'ts': 1000},
            {'msg_uid': '2', 'speaker': 'OTHER', 'modality': 'text', 
             'text_raw': '早上好', 'ts': 1000 + 9 * 3600}  # 9小时后
        ]
        
        result = processor.process(messages)
        
        gap_marker = result[1]
        assert gap_marker['break_type'] == 'normal_gap'
    
    def test_detect_potential_cold_shoulder(self, processor):
        """测试检测潜在冷暴力"""
        messages = [
            {'msg_uid': '1', 'speaker': 'ME', 'modality': 'text', 
             'text_raw': '你在干嘛？', 'ts': 1000},
            {'msg_uid': '2', 'speaker': 'OTHER', 'modality': 'text', 
             'text_raw': '嗯', 'ts': 1000 + 5 * 3600}  # 5小时后，敷衍回复
        ]
        
        result = processor.process(messages)
        
        gap_marker = result[1]
        assert gap_marker['break_type'] == 'potential_cold_shoulder'
    
    def test_detect_conflict_cooling(self, processor):
        """测试检测冲突冷却期"""
        messages = [
            {'msg_uid': '1', 'speaker': 'ME', 'modality': 'text', 
             'text_raw': '我真的很生气！', 'ts': 1000, 'emotion_tags': ['ANGRY']},
            {'msg_uid': '2', 'speaker': 'OTHER', 'modality': 'text', 
             'text_raw': '我们谈谈吧', 'ts': 1000 + 24 * 3600}  # 24小时后
        ]
        
        result = processor.process(messages)
        
        gap_marker = result[1]
        assert gap_marker['break_type'] == 'conflict_cooling'


class TestEmotionAwareMerge:
    """情绪感知合并测试"""
    
    def test_no_merge_emotion_conflict(self, processor):
        """测试情绪冲突不合并"""
        messages = [
            {'msg_uid': '1', 'speaker': 'ME', 'modality': 'text', 
             'text_raw': '太开心了', 'ts': 1000, 'emotion_tags': ['HAPPY']},
            {'msg_uid': '2', 'speaker': 'ME', 'modality': 'text', 
             'text_raw': '好难过', 'ts': 1030, 'emotion_tags': ['SAD']}
        ]
        
        result = processor.process(messages)
        
        # 情绪冲突，不应该合并
        assert len(result) == 2
    
    def test_no_merge_emotion_burst(self, processor):
        """测试情绪爆发不合并"""
        messages = [
            {'msg_uid': '1', 'speaker': 'ME', 'modality': 'text', 
             'text_raw': '你到底在干嘛！！', 'ts': 1000},
            {'msg_uid': '2', 'speaker': 'ME', 'modality': 'text', 
             'text_raw': '为什么不回我', 'ts': 1030}
        ]
        
        result = processor.process(messages)
        
        # 情绪爆发（连续感叹号），不应该合并
        assert len(result) == 2


class TestRapidFireDetection:
    """快速连发检测测试"""
    
    def test_preserve_rapid_fire(self, processor):
        """测试保留快速连发消息"""
        messages = [
            {'msg_uid': '1', 'speaker': 'ME', 'modality': 'text', 
             'text_raw': '你', 'ts': 1000},
            {'msg_uid': '2', 'speaker': 'ME', 'modality': 'text', 
             'text_raw': '怎么', 'ts': 1005},  # 5秒后
            {'msg_uid': '3', 'speaker': 'ME', 'modality': 'text', 
             'text_raw': '不说话', 'ts': 1008}  # 3秒后
        ]
        
        result = processor.process(messages)
        
        # 快速连发的短消息应该保留，不合并
        assert len(result) == 3


class TestTimeGapFormatting:
    """时间间隔格式化测试 - 精确格式
    
    格式规则：
    - < 1小时: "X分钟"
    - 1小时 ~ 1天: "X小时Y分钟"（分钟为0时省略）
    - >= 1天: "X天Y小时"（小时为0时省略）
    
    Validates: Requirements 1.1, 1.2, 1.3
    """
    
    def test_format_minutes(self, processor):
        """测试分钟格式化（< 1小时）
        
        Validates: Requirements 1.1
        """
        # 30分钟
        gap_desc = processor._format_time_gap(1800)
        assert gap_desc == "30分钟"
        
        # 45分钟
        gap_desc = processor._format_time_gap(2700)
        assert gap_desc == "45分钟"
        
        # 1分钟
        gap_desc = processor._format_time_gap(60)
        assert gap_desc == "1分钟"
        
        # 59分钟
        gap_desc = processor._format_time_gap(3540)
        assert gap_desc == "59分钟"
    
    def test_format_hours(self, processor):
        """测试小时格式化（1小时 ~ 1天，整小时）
        
        Validates: Requirements 1.2
        """
        # 1小时整
        gap_desc = processor._format_time_gap(3600)
        assert gap_desc == "1小时"
        
        # 2小时整
        gap_desc = processor._format_time_gap(7200)
        assert gap_desc == "2小时"
        
        # 3小时整
        gap_desc = processor._format_time_gap(3 * 3600)
        assert gap_desc == "3小时"
        
        # 12小时整（原 test_format_half_day）
        gap_desc = processor._format_time_gap(12 * 3600)
        assert gap_desc == "12小时"
        
        # 23小时整
        gap_desc = processor._format_time_gap(23 * 3600)
        assert gap_desc == "23小时"
    
    def test_format_hours_with_minutes(self, processor):
        """测试小时+分钟格式化（1小时 ~ 1天，非整小时）
        
        Validates: Requirements 1.2
        """
        # 2小时30分钟
        gap_desc = processor._format_time_gap(9000)
        assert gap_desc == "2小时30分钟"
        
        # 1小时1分钟
        gap_desc = processor._format_time_gap(3660)
        assert gap_desc == "1小时1分钟"
        
        # 5小时45分钟
        gap_desc = processor._format_time_gap(5 * 3600 + 45 * 60)
        assert gap_desc == "5小时45分钟"
    
    def test_format_days(self, processor):
        """测试天数格式化（>= 1天，整天）
        
        Validates: Requirements 1.3
        """
        # 1天整
        gap_desc = processor._format_time_gap(86400)
        assert gap_desc == "1天"
        
        # 3天整
        gap_desc = processor._format_time_gap(3 * 86400)
        assert gap_desc == "3天"
        
        # 7天整
        gap_desc = processor._format_time_gap(7 * 86400)
        assert gap_desc == "7天"
    
    def test_format_days_with_hours(self, processor):
        """测试天数+小时格式化（>= 1天，非整天）
        
        Validates: Requirements 1.3
        """
        # 1天1小时
        gap_desc = processor._format_time_gap(90000)
        assert gap_desc == "1天1小时"
        
        # 2天5小时
        gap_desc = processor._format_time_gap(2 * 86400 + 5 * 3600)
        assert gap_desc == "2天5小时"
        
        # 1天12小时
        gap_desc = processor._format_time_gap(86400 + 12 * 3600)
        assert gap_desc == "1天12小时"
    
    def test_format_boundary_values(self, processor):
        """测试边界值
        
        Validates: Requirements 1.1, 1.2, 1.3
        """
        # 0秒 → "0分钟"
        gap_desc = processor._format_time_gap(0)
        assert gap_desc == "0分钟"
        
        # 负数 → "0分钟"
        gap_desc = processor._format_time_gap(-100)
        assert gap_desc == "0分钟"
        
        # 3599秒（刚好不到1小时）→ "59分钟"
        gap_desc = processor._format_time_gap(3599)
        assert gap_desc == "59分钟"
        
        # 3600秒（刚好1小时）→ "1小时"
        gap_desc = processor._format_time_gap(3600)
        assert gap_desc == "1小时"
        
        # 86399秒（刚好不到1天）→ "23小时59分钟"
        gap_desc = processor._format_time_gap(86399)
        assert gap_desc == "23小时59分钟"
        
        # 86400秒（刚好1天）→ "1天"
        gap_desc = processor._format_time_gap(86400)
        assert gap_desc == "1天"


class TestStatistics:
    """统计信息测试"""
    
    def test_stats_after_processing(self, processor):
        """测试处理后的统计信息"""
        messages = [
            {'msg_uid': '1', 'speaker': 'ME', 'modality': 'text', 
             'text_raw': '你好', 'ts': 1000},
            {'msg_uid': '2', 'speaker': 'ME', 'modality': 'text', 
             'text_raw': '在吗', 'ts': 1030},
            {'msg_uid': '3', 'speaker': 'OTHER', 'modality': 'text', 
             'text_raw': '在', 'ts': 1000 + 3 * 3600}  # 3小时后
        ]
        
        processor.process(messages)
        stats = processor.get_stats()
        
        assert stats['total_input'] == 3
        assert stats['merge_groups'] >= 0
        assert stats['time_gaps_inserted'] >= 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
