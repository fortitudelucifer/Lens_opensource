"""
test_linkfile_schema.py
属性测试：输出记录 Schema 合规性

Property 8: 输出记录 Schema 合规性
For any Merge_Engine 输出的记录，schema_version 应为 "merged_v2"，
modality 应为 "link_or_file"，且字段顺序应符合 COMMON_HEADER_FIELDS 定义
（公共字段在前，linkfile 特定字段在后）。

**Validates: Requirements 6.1, 6.2, 6.3, 6.4**

运行方式：
    pytest tests/test_linkfile_schema.py -v
    python tests/test_linkfile_schema.py

Requirements: 6.1, 6.2, 6.3, 6.4
"""

import sys
from pathlib import Path
from collections import OrderedDict
from hypothesis import given, strategies as st, settings

# 添加项目根目录到 Python 路径
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts._common.schema_utils import (
    SCHEMA_VERSION,
    COMMON_HEADER_FIELDS,
    LINKFILE_SPECIFIC_FIELDS,
)
from scripts.linkfile.run_all._02_merge_engine import (
    reorder_linkfile_record,
    LINKFILE_SPECIFIC_FIELDS as MERGE_LINKFILE_FIELDS,
)


# =============================================================================
# 测试数据生成策略
# =============================================================================

# 有效的 link_sub_type 值
VALID_LINK_SUB_TYPES = ['quote', 'link', 'file', 'miniprogram', 'video_channel', 'chat_history', 'unknown']

# 生成基础消息记录的策略
@st.composite
def linkfile_record_strategy(draw):
    """生成随机的 linkfile 记录用于测试"""
    link_sub_type = draw(st.sampled_from(VALID_LINK_SUB_TYPES))
    
    record = {
        'seq_in_html': draw(st.integers(min_value=1, max_value=10000)),
        'msg_uid': f"P1:{draw(st.integers(min_value=1000000, max_value=9999999999))}",
        'MsgSvrID': str(draw(st.integers(min_value=1000000, max_value=9999999999))),
        'token': draw(st.text(alphabet='abcdef0123456789', min_size=8, max_size=16)),
        'ts': draw(st.integers(min_value=1600000000, max_value=1800000000)),
        'time_local': '2025-06-07 14:54:03',
        'speaker': draw(st.sampled_from(['ME', 'OTHER'])),
        'type': 49,
        'sub_type': draw(st.sampled_from([5, 6, 19, 33, 36, 51, 57, 99])),
        'modality': 'link_or_file',
        'media_path': draw(st.one_of(st.none(), st.just('file/test.pdf'))),
        'link_sub_type': link_sub_type,
    }
    
    # 根据 link_sub_type 添加特定字段
    if link_sub_type == 'quote':
        record['quote_svrid'] = str(draw(st.integers(min_value=1000000, max_value=9999999999)))
        record['quote_type'] = draw(st.integers(min_value=1, max_value=50))
        record['quote_text'] = draw(st.text(min_size=0, max_size=100))
    elif link_sub_type == 'link':
        record['link_url'] = f"https://example.com/{draw(st.text(alphabet='abcdef', min_size=5, max_size=10))}"
        record['link_title'] = draw(st.text(min_size=1, max_size=50))
        record['link_type'] = draw(st.sampled_from(['web_link', 'wechat_article', 'bilibili_video']))
    elif link_sub_type == 'file':
        record['file_name'] = f"test.{draw(st.sampled_from(['pdf', 'doc', 'zip']))}"
        record['file_ext'] = draw(st.sampled_from(['pdf', 'doc', 'zip']))
        record['file_category'] = draw(st.sampled_from(['document', 'archive', 'other']))
    elif link_sub_type == 'miniprogram':
        record['link_url'] = f"https://mp.weixin.qq.com/{draw(st.text(alphabet='abcdef', min_size=5, max_size=10))}"
        record['link_title'] = draw(st.text(min_size=1, max_size=50))
        record['miniprogram_appid'] = f"wx{draw(st.text(alphabet='abcdef0123456789', min_size=16, max_size=16))}"
    elif link_sub_type in ['video_channel', 'chat_history']:
        record['content_title'] = draw(st.text(min_size=1, max_size=50))
    
    return record


class TestLinkfileSchemaProperty:
    """
    Property 8: 输出记录 Schema 合规性
    
    Feature: linkfile-pipeline, Property 8: 输出记录 Schema 合规性
    **Validates: Requirements 6.1, 6.2, 6.3, 6.4**
    """
    
    @given(record=linkfile_record_strategy())
    @settings(max_examples=100)
    def test_schema_version_is_merged_v2(self, record: dict):
        """
        Property 8.1: schema_version 应为 "merged_v2"
        
        Feature: linkfile-pipeline, Property 8: 输出记录 Schema 合规性
        **Validates: Requirements 6.2**
        """
        # 添加 schema_version 并重排字段（模拟 merge_engine 行为）
        record['schema_version'] = SCHEMA_VERSION
        merged = reorder_linkfile_record(record)
        
        assert merged.get('schema_version') == 'merged_v2', \
            f"schema_version 应为 'merged_v2'，实际为 '{merged.get('schema_version')}'"
    
    @given(record=linkfile_record_strategy())
    @settings(max_examples=100)
    def test_modality_is_link_or_file(self, record: dict):
        """
        Property 8.2: modality 应为 "link_or_file"
        
        Feature: linkfile-pipeline, Property 8: 输出记录 Schema 合规性
        **Validates: Requirements 6.3**
        """
        record['schema_version'] = SCHEMA_VERSION
        merged = reorder_linkfile_record(record)
        
        assert merged.get('modality') == 'link_or_file', \
            f"modality 应为 'link_or_file'，实际为 '{merged.get('modality')}'"
    
    @given(record=linkfile_record_strategy())
    @settings(max_examples=100)
    def test_common_header_fields_present(self, record: dict):
        """
        Property 8.3: 输出记录应包含所有 COMMON_HEADER_FIELDS
        
        Feature: linkfile-pipeline, Property 8: 输出记录 Schema 合规性
        **Validates: Requirements 6.1**
        """
        record['schema_version'] = SCHEMA_VERSION
        merged = reorder_linkfile_record(record)
        
        for field in COMMON_HEADER_FIELDS:
            assert field in merged, \
                f"输出记录缺少公共字段: {field}"
    
    @given(record=linkfile_record_strategy())
    @settings(max_examples=100)
    def test_field_ordering_schema_version_first(self, record: dict):
        """
        Property 8.4: schema_version 应为第一个字段
        
        Feature: linkfile-pipeline, Property 8: 输出记录 Schema 合规性
        **Validates: Requirements 6.4**
        """
        record['schema_version'] = SCHEMA_VERSION
        merged = reorder_linkfile_record(record)
        
        keys = list(merged.keys())
        assert keys[0] == 'schema_version', \
            f"schema_version 应为第一个字段，实际第一个字段为 '{keys[0]}'"
    
    @given(record=linkfile_record_strategy())
    @settings(max_examples=100)
    def test_field_ordering_common_fields_in_order(self, record: dict):
        """
        Property 8.5: COMMON_HEADER_FIELDS 应按定义顺序排列
        
        Feature: linkfile-pipeline, Property 8: 输出记录 Schema 合规性
        **Validates: Requirements 6.4**
        """
        record['schema_version'] = SCHEMA_VERSION
        merged = reorder_linkfile_record(record)
        
        keys = list(merged.keys())
        
        # 获取公共字段在输出中的索引
        common_indices = []
        for field in COMMON_HEADER_FIELDS:
            if field in keys:
                common_indices.append(keys.index(field))
        
        # 验证公共字段索引是递增的（即按顺序排列）
        assert common_indices == sorted(common_indices), \
            f"公共字段顺序不正确，索引为 {common_indices}"
    
    @given(record=linkfile_record_strategy())
    @settings(max_examples=100)
    def test_field_ordering_specific_fields_after_common(self, record: dict):
        """
        Property 8.6: linkfile 特定字段应在公共字段之后
        
        Feature: linkfile-pipeline, Property 8: 输出记录 Schema 合规性
        **Validates: Requirements 6.4**
        """
        record['schema_version'] = SCHEMA_VERSION
        merged = reorder_linkfile_record(record)
        
        keys = list(merged.keys())
        
        # 获取公共字段的最大索引
        common_indices = [keys.index(f) for f in COMMON_HEADER_FIELDS if f in keys]
        if not common_indices:
            return  # 没有公共字段，跳过
        
        max_common_idx = max(common_indices)
        
        # 验证所有 linkfile 特定字段都在公共字段之后
        for field in LINKFILE_SPECIFIC_FIELDS:
            if field in keys:
                field_idx = keys.index(field)
                assert field_idx > max_common_idx, \
                    f"特定字段 '{field}' (索引 {field_idx}) 应在公共字段之后 (最大索引 {max_common_idx})"
    
    @given(record=linkfile_record_strategy())
    @settings(max_examples=100)
    def test_no_legacy_field_names(self, record: dict):
        """
        Property 8.7: 不应存在旧字段名 (timestamp, sender)
        
        Feature: linkfile-pipeline, Property 8: 输出记录 Schema 合规性
        **Validates: Requirements 6.1**
        """
        record['schema_version'] = SCHEMA_VERSION
        merged = reorder_linkfile_record(record)
        
        # 不应存在旧字段名
        assert 'timestamp' not in merged, \
            "不应存在 'timestamp' 字段，应使用 'ts'"
        assert 'sender' not in merged, \
            "不应存在 'sender' 字段，应使用 'speaker'"
    
    @given(record=linkfile_record_strategy())
    @settings(max_examples=100)
    def test_link_sub_type_is_valid(self, record: dict):
        """
        Property 8.8: link_sub_type 应为有效值
        
        Feature: linkfile-pipeline, Property 8: 输出记录 Schema 合规性
        **Validates: Requirements 6.4**
        """
        record['schema_version'] = SCHEMA_VERSION
        merged = reorder_linkfile_record(record)
        
        link_sub_type = merged.get('link_sub_type')
        valid_types = {'quote', 'link', 'file', 'miniprogram', 'video_channel', 'chat_history', 'unknown', 'error'}
        
        assert link_sub_type in valid_types, \
            f"link_sub_type '{link_sub_type}' 不是有效值，有效值为 {valid_types}"


# =============================================================================
# 运行测试
# =============================================================================

if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
