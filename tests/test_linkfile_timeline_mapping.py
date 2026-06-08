"""
test_linkfile_timeline_mapping.py
属性测试：时间轴字段映射

Property 9: 时间轴字段映射
For any 更新到时间轴的 linkfile 记录，应使用 msg_uid 作为连接键，
且根据 link_sub_type 包含对应的字段：
- quote 类型包含 link_quote_text
- link 类型包含 link_url/link_title/link_type
- file 类型包含 link_file_name/link_file_category

**Validates: Requirements 8.1, 8.2, 8.3, 8.4**

运行方式：
    pytest tests/test_linkfile_timeline_mapping.py -v
    python tests/test_linkfile_timeline_mapping.py

Requirements: 8.1, 8.2, 8.3, 8.4
"""

import sys
from pathlib import Path
from typing import Dict, Any, List
from hypothesis import given, strategies as st, settings, assume

# 添加项目根目录到 Python 路径
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.linkfile.run_all._03_update_timeline import (
    build_timeline_fields,
    update_timeline,
    TIMELINE_FIELD_MAPPING,
    COMMON_TIMELINE_FIELDS,
    SLIM_FIELDS,
)


# =============================================================================
# 测试数据生成策略
# =============================================================================

# 有效的 link_sub_type 值
VALID_LINK_SUB_TYPES = ['quote', 'link', 'file', 'miniprogram', 'video_channel', 'chat_history']


@st.composite
def quote_record_strategy(draw):
    """生成 quote 类型的 linkfile 记录"""
    return {
        'msg_uid': f"P1:{draw(st.integers(min_value=1000000, max_value=9999999999))}",
        'link_sub_type': 'quote',
        'quote_svrid': str(draw(st.integers(min_value=1000000, max_value=9999999999))),
        'quote_type': draw(st.integers(min_value=1, max_value=50)),
        'quote_text': draw(st.text(min_size=1, max_size=100)),
    }


@st.composite
def link_record_strategy(draw):
    """生成 link 类型的 linkfile 记录"""
    return {
        'msg_uid': f"P1:{draw(st.integers(min_value=1000000, max_value=9999999999))}",
        'link_sub_type': 'link',
        'link_url': f"https://example.com/{draw(st.text(alphabet='abcdef', min_size=5, max_size=10))}",
        'link_title': draw(st.text(min_size=1, max_size=50)),
        'link_type': draw(st.sampled_from(['web_link', 'wechat_article', 'bilibili_video', 'meituan_poi'])),
    }


@st.composite
def file_record_strategy(draw):
    """生成 file 类型的 linkfile 记录"""
    ext = draw(st.sampled_from(['pdf', 'doc', 'docx', 'zip', 'rar', 'mp3', 'mp4']))
    return {
        'msg_uid': f"P1:{draw(st.integers(min_value=1000000, max_value=9999999999))}",
        'link_sub_type': 'file',
        'file_name': f"document.{ext}",
        'file_ext': ext,
        'file_category': draw(st.sampled_from(['document', 'archive', 'audio', 'video', 'other'])),
        'file_size_bytes': draw(st.integers(min_value=100, max_value=10000000)),
    }


@st.composite
def miniprogram_record_strategy(draw):
    """生成 miniprogram 类型的 linkfile 记录"""
    return {
        'msg_uid': f"P1:{draw(st.integers(min_value=1000000, max_value=9999999999))}",
        'link_sub_type': 'miniprogram',
        'link_url': f"https://mp.weixin.qq.com/{draw(st.text(alphabet='abcdef', min_size=5, max_size=10))}",
        'link_title': draw(st.text(min_size=1, max_size=50)),
        'miniprogram_appid': f"wx{draw(st.text(alphabet='abcdef0123456789', min_size=16, max_size=16))}",
        'miniprogram_name': draw(st.text(min_size=1, max_size=20)),
    }


@st.composite
def video_channel_record_strategy(draw):
    """生成 video_channel 类型的 linkfile 记录"""
    return {
        'msg_uid': f"P1:{draw(st.integers(min_value=1000000, max_value=9999999999))}",
        'link_sub_type': 'video_channel',
        'content_title': draw(st.text(min_size=1, max_size=100)),
    }


@st.composite
def chat_history_record_strategy(draw):
    """生成 chat_history 类型的 linkfile 记录"""
    return {
        'msg_uid': f"P1:{draw(st.integers(min_value=1000000, max_value=9999999999))}",
        'link_sub_type': 'chat_history',
        'content_title': draw(st.text(min_size=1, max_size=100)),
    }


@st.composite
def any_linkfile_record_strategy(draw):
    """生成任意类型的 linkfile 记录"""
    link_sub_type = draw(st.sampled_from(VALID_LINK_SUB_TYPES))
    
    if link_sub_type == 'quote':
        return draw(quote_record_strategy())
    elif link_sub_type == 'link':
        return draw(link_record_strategy())
    elif link_sub_type == 'file':
        return draw(file_record_strategy())
    elif link_sub_type == 'miniprogram':
        return draw(miniprogram_record_strategy())
    elif link_sub_type == 'video_channel':
        return draw(video_channel_record_strategy())
    else:  # chat_history
        return draw(chat_history_record_strategy())


@st.composite
def timeline_record_strategy(draw, msg_uid: str = None):
    """生成时间轴记录"""
    if msg_uid is None:
        msg_uid = f"P1:{draw(st.integers(min_value=1000000, max_value=9999999999))}"
    
    return {
        'msg_uid': msg_uid,
        'ts': draw(st.integers(min_value=1600000000, max_value=1800000000)),
        'speaker': draw(st.sampled_from(['ME', 'OTHER'])),
        'type': 49,
        'modality': 'link_or_file',
        'text_raw': draw(st.text(min_size=0, max_size=50)),
    }


# =============================================================================
# Property 9: 时间轴字段映射测试
# =============================================================================

class TestTimelineFieldMappingProperty:
    """
    Property 9: 时间轴字段映射
    
    Feature: linkfile-pipeline, Property 9: 时间轴字段映射
    **Validates: Requirements 8.1, 8.2, 8.3, 8.4**
    """
    
    @given(record=quote_record_strategy())
    @settings(max_examples=100)
    def test_quote_message_includes_link_quote_text(self, record: Dict[str, Any]):
        """
        Property 9.1: quote 消息应包含 link_quote_text 字段
        
        Feature: linkfile-pipeline, Property 9: 时间轴字段映射
        **Validates: Requirements 8.1**
        """
        timeline_fields = build_timeline_fields(record, is_slim=False)
        
        # 验证 link_sub_type 被正确映射
        assert timeline_fields.get('link_sub_type') == 'quote', \
            f"link_sub_type 应为 'quote'，实际为 '{timeline_fields.get('link_sub_type')}'"
        
        # 验证 link_quote_text 字段存在
        assert 'link_quote_text' in timeline_fields, \
            "quote 消息应包含 link_quote_text 字段"
        
        # 验证值正确映射
        assert timeline_fields['link_quote_text'] == record['quote_text'], \
            f"link_quote_text 值不匹配: 期望 '{record['quote_text']}'，实际 '{timeline_fields['link_quote_text']}'"
    
    @given(record=link_record_strategy())
    @settings(max_examples=100)
    def test_link_message_includes_url_title_type(self, record: Dict[str, Any]):
        """
        Property 9.2: link 消息应包含 link_url, link_title, link_type 字段
        
        Feature: linkfile-pipeline, Property 9: 时间轴字段映射
        **Validates: Requirements 8.2**
        """
        timeline_fields = build_timeline_fields(record, is_slim=False)
        
        # 验证 link_sub_type 被正确映射
        assert timeline_fields.get('link_sub_type') == 'link', \
            f"link_sub_type 应为 'link'，实际为 '{timeline_fields.get('link_sub_type')}'"
        
        # 验证必需字段存在
        assert 'link_url' in timeline_fields, \
            "link 消息应包含 link_url 字段"
        assert 'link_title' in timeline_fields, \
            "link 消息应包含 link_title 字段"
        assert 'link_type' in timeline_fields, \
            "link 消息应包含 link_type 字段"
        
        # 验证值正确映射
        assert timeline_fields['link_url'] == record['link_url'], \
            f"link_url 值不匹配"
        assert timeline_fields['link_title'] == record['link_title'], \
            f"link_title 值不匹配"
        assert timeline_fields['link_type'] == record['link_type'], \
            f"link_type 值不匹配"
    
    @given(record=file_record_strategy())
    @settings(max_examples=100)
    def test_file_message_includes_file_name_category(self, record: Dict[str, Any]):
        """
        Property 9.3: file 消息应包含 link_file_name, link_file_category 字段
        
        Feature: linkfile-pipeline, Property 9: 时间轴字段映射
        **Validates: Requirements 8.3**
        """
        timeline_fields = build_timeline_fields(record, is_slim=False)
        
        # 验证 link_sub_type 被正确映射
        assert timeline_fields.get('link_sub_type') == 'file', \
            f"link_sub_type 应为 'file'，实际为 '{timeline_fields.get('link_sub_type')}'"
        
        # 验证必需字段存在
        assert 'link_file_name' in timeline_fields, \
            "file 消息应包含 link_file_name 字段"
        assert 'link_file_category' in timeline_fields, \
            "file 消息应包含 link_file_category 字段"
        
        # 验证值正确映射
        assert timeline_fields['link_file_name'] == record['file_name'], \
            f"link_file_name 值不匹配"
        assert timeline_fields['link_file_category'] == record['file_category'], \
            f"link_file_category 值不匹配"
    
    @given(record=any_linkfile_record_strategy())
    @settings(max_examples=100)
    def test_msg_uid_as_join_key(self, record: Dict[str, Any]):
        """
        Property 9.4: 应使用 msg_uid 作为连接键
        
        Feature: linkfile-pipeline, Property 9: 时间轴字段映射
        **Validates: Requirements 8.4**
        """
        msg_uid = record['msg_uid']
        
        # 创建时间轴记录
        timeline_record = {
            'msg_uid': msg_uid,
            'ts': 1700000000,
            'speaker': 'ME',
            'type': 49,
            'modality': 'link_or_file',
        }
        
        # 创建 linkfile 查找表
        linkfile_lookup = {msg_uid: record}
        
        # 执行更新
        updated_records, update_count = update_timeline(
            [timeline_record], 
            linkfile_lookup, 
            is_slim=False
        )
        
        # 验证更新成功
        assert update_count == 1, \
            f"应更新 1 条记录，实际更新 {update_count} 条"
        
        # 验证 msg_uid 匹配
        assert updated_records[0]['msg_uid'] == msg_uid, \
            f"msg_uid 不匹配: 期望 '{msg_uid}'，实际 '{updated_records[0]['msg_uid']}'"
        
        # 验证 link_sub_type 被添加
        assert 'link_sub_type' in updated_records[0], \
            "更新后的记录应包含 link_sub_type 字段"
    
    @given(record=any_linkfile_record_strategy())
    @settings(max_examples=100)
    def test_non_matching_msg_uid_not_updated(self, record: Dict[str, Any]):
        """
        Property 9.5: 不匹配的 msg_uid 不应被更新
        
        Feature: linkfile-pipeline, Property 9: 时间轴字段映射
        **Validates: Requirements 8.4**
        """
        # 创建不匹配的时间轴记录
        timeline_record = {
            'msg_uid': 'P1:non_matching_uid',
            'ts': 1700000000,
            'speaker': 'ME',
            'type': 49,
            'modality': 'link_or_file',
        }
        
        # 创建 linkfile 查找表（使用不同的 msg_uid）
        linkfile_lookup = {record['msg_uid']: record}
        
        # 执行更新
        updated_records, update_count = update_timeline(
            [timeline_record], 
            linkfile_lookup, 
            is_slim=False
        )
        
        # 验证没有更新
        assert update_count == 0, \
            f"不匹配的记录不应被更新，实际更新 {update_count} 条"
        
        # 验证记录未被修改
        assert 'link_sub_type' not in updated_records[0], \
            "不匹配的记录不应包含 link_sub_type 字段"
    
    @given(record=miniprogram_record_strategy())
    @settings(max_examples=100)
    def test_miniprogram_message_fields(self, record: Dict[str, Any]):
        """
        Property 9.6: miniprogram 消息应包含正确的字段
        
        Feature: linkfile-pipeline, Property 9: 时间轴字段映射
        **Validates: Requirements 8.2**
        """
        timeline_fields = build_timeline_fields(record, is_slim=False)
        
        # 验证 link_sub_type 被正确映射
        assert timeline_fields.get('link_sub_type') == 'miniprogram', \
            f"link_sub_type 应为 'miniprogram'，实际为 '{timeline_fields.get('link_sub_type')}'"
        
        # 验证字段存在
        assert 'link_url' in timeline_fields, \
            "miniprogram 消息应包含 link_url 字段"
        assert 'link_title' in timeline_fields, \
            "miniprogram 消息应包含 link_title 字段"
        assert 'link_miniprogram_appid' in timeline_fields, \
            "miniprogram 消息应包含 link_miniprogram_appid 字段"
    
    @given(record=video_channel_record_strategy())
    @settings(max_examples=100)
    def test_video_channel_message_fields(self, record: Dict[str, Any]):
        """
        Property 9.7: video_channel 消息应包含 content_title 字段
        
        Feature: linkfile-pipeline, Property 9: 时间轴字段映射
        **Validates: Requirements 8.2**
        """
        timeline_fields = build_timeline_fields(record, is_slim=False)
        
        # 验证 link_sub_type 被正确映射
        assert timeline_fields.get('link_sub_type') == 'video_channel', \
            f"link_sub_type 应为 'video_channel'，实际为 '{timeline_fields.get('link_sub_type')}'"
        
        # 验证 content_title 字段存在
        assert 'link_content_title' in timeline_fields, \
            "video_channel 消息应包含 link_content_title 字段"
        
        # 验证值正确映射
        assert timeline_fields['link_content_title'] == record['content_title'], \
            f"link_content_title 值不匹配"
    
    @given(record=chat_history_record_strategy())
    @settings(max_examples=100)
    def test_chat_history_message_fields(self, record: Dict[str, Any]):
        """
        Property 9.8: chat_history 消息应包含 content_title 字段
        
        Feature: linkfile-pipeline, Property 9: 时间轴字段映射
        **Validates: Requirements 8.2**
        """
        timeline_fields = build_timeline_fields(record, is_slim=False)
        
        # 验证 link_sub_type 被正确映射
        assert timeline_fields.get('link_sub_type') == 'chat_history', \
            f"link_sub_type 应为 'chat_history'，实际为 '{timeline_fields.get('link_sub_type')}'"
        
        # 验证 content_title 字段存在
        assert 'link_content_title' in timeline_fields, \
            "chat_history 消息应包含 link_content_title 字段"
        
        # 验证值正确映射
        assert timeline_fields['link_content_title'] == record['content_title'], \
            f"link_content_title 值不匹配"


class TestSlimTimelineFieldMapping:
    """
    测试精简版时间轴字段映射
    
    Feature: linkfile-pipeline, Property 9: 时间轴字段映射
    **Validates: Requirements 8.1, 8.2, 8.3, 8.4**
    """
    
    @given(record=any_linkfile_record_strategy())
    @settings(max_examples=100)
    def test_slim_version_only_includes_slim_fields(self, record: Dict[str, Any]):
        """
        Property 9.9: 精简版只包含 SLIM_FIELDS 中定义的字段
        
        Feature: linkfile-pipeline, Property 9: 时间轴字段映射
        **Validates: Requirements 8.1, 8.2, 8.3**
        """
        timeline_fields = build_timeline_fields(record, is_slim=True)
        
        # 验证所有字段都在 SLIM_FIELDS 中
        for field in timeline_fields.keys():
            assert field in SLIM_FIELDS, \
                f"精简版不应包含字段 '{field}'，该字段不在 SLIM_FIELDS 中"
    
    @given(record=quote_record_strategy())
    @settings(max_examples=100)
    def test_slim_quote_includes_link_quote_text(self, record: Dict[str, Any]):
        """
        Property 9.10: 精简版 quote 消息应包含 link_quote_text
        
        Feature: linkfile-pipeline, Property 9: 时间轴字段映射
        **Validates: Requirements 8.1**
        """
        timeline_fields = build_timeline_fields(record, is_slim=True)
        
        # link_quote_text 应在精简版中
        assert 'link_quote_text' in timeline_fields, \
            "精简版 quote 消息应包含 link_quote_text 字段"
    
    @given(record=link_record_strategy())
    @settings(max_examples=100)
    def test_slim_link_includes_essential_fields(self, record: Dict[str, Any]):
        """
        Property 9.11: 精简版 link 消息应包含 link_url, link_title, link_type
        
        Feature: linkfile-pipeline, Property 9: 时间轴字段映射
        **Validates: Requirements 8.2**
        """
        timeline_fields = build_timeline_fields(record, is_slim=True)
        
        # 这些字段应在精简版中
        assert 'link_url' in timeline_fields, \
            "精简版 link 消息应包含 link_url 字段"
        assert 'link_title' in timeline_fields, \
            "精简版 link 消息应包含 link_title 字段"
        assert 'link_type' in timeline_fields, \
            "精简版 link 消息应包含 link_type 字段"
    
    @given(record=file_record_strategy())
    @settings(max_examples=100)
    def test_slim_file_includes_essential_fields(self, record: Dict[str, Any]):
        """
        Property 9.12: 精简版 file 消息应包含 link_file_name, link_file_category
        
        Feature: linkfile-pipeline, Property 9: 时间轴字段映射
        **Validates: Requirements 8.3**
        """
        timeline_fields = build_timeline_fields(record, is_slim=True)
        
        # 这些字段应在精简版中
        assert 'link_file_name' in timeline_fields, \
            "精简版 file 消息应包含 link_file_name 字段"
        assert 'link_file_category' in timeline_fields, \
            "精简版 file 消息应包含 link_file_category 字段"


# =============================================================================
# 运行测试
# =============================================================================

if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
