"""
test_linkfile_subtype_routing.py
属性测试：子类型路由正确性

Property 1: 子类型路由正确性
For any type=49 消息，当 sub_type 在支持列表 [5, 6, 19, 33, 36, 51, 57] 中时，
输出记录的 link_sub_type 应与 sub_type 对应的类型名称匹配；
当 sub_type 不在支持列表中时，link_sub_type 应为 "unknown"。

**Validates: Requirements 1.1, 1.4**

运行方式：
    pytest tests/test_linkfile_subtype_routing.py -v
    python tests/test_linkfile_subtype_routing.py

Requirements: 1.1, 1.4
"""

import sys
from pathlib import Path
from hypothesis import given, strategies as st, settings

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.linkfile.extractor import LinkfileExtractor


# 支持的 sub_type 及其对应的 link_sub_type 映射
SUPPORTED_SUB_TYPES = {
    5: "link",
    6: "file",
    19: "chat_history",
    33: "miniprogram",
    36: "miniprogram",
    51: "video_channel",
    57: "quote",
}

# 所有支持的 sub_type 列表
SUPPORTED_SUB_TYPE_LIST = list(SUPPORTED_SUB_TYPES.keys())

# 不支持的 sub_type 示例（用于测试 unknown 路由）
UNSUPPORTED_SUB_TYPES = [0, 1, 2, 3, 4, 7, 8, 10, 20, 99, 100, 255]


def create_test_extractor() -> LinkfileExtractor:
    """创建测试用的 LinkfileExtractor 实例"""
    config = {
        'link_type_rules': [
            {'pattern': '*', 'type': 'web_link'}
        ],
        'file_categories': {
            'document': {'extensions': ['pdf', 'doc', 'docx']},
            'archive': {'extensions': ['zip', 'rar']},
        },
        'miniprogram_apps': {},
    }
    workspace_root = Path(__file__).parent.parent
    return LinkfileExtractor(config, workspace_root)


class TestSubTypeRoutingProperty:
    """
    Property 1: 子类型路由正确性
    
    Feature: linkfile-pipeline, Property 1: 子类型路由正确性
    **Validates: Requirements 1.1, 1.4**
    """
    
    @given(sub_type=st.sampled_from(SUPPORTED_SUB_TYPE_LIST))
    @settings(max_examples=100)
    def test_supported_sub_type_routes_correctly(self, sub_type: int):
        """
        Property: 支持的 sub_type 应路由到正确的 link_sub_type
        
        Feature: linkfile-pipeline, Property 1: 子类型路由正确性
        **Validates: Requirements 1.1, 1.4**
        """
        extractor = create_test_extractor()
        
        # 构造测试消息
        msg = {
            'type': 49,
            'sub_type': sub_type,
            'msg_uid': f'P1:test_{sub_type}',
            'MsgSvrID': f'test_{sub_type}',
            'link_url': 'https://example.com',
            'link_title': 'Test Title',
            'media_path': 'file/test.pdf',
        }
        
        result = extractor._extract_one(msg, {})
        
        # 验证 link_sub_type 与预期映射匹配
        expected_link_sub_type = SUPPORTED_SUB_TYPES[sub_type]
        assert result is not None, f"Result should not be None for sub_type={sub_type}"
        assert result['link_sub_type'] == expected_link_sub_type, \
            f"sub_type={sub_type} should route to '{expected_link_sub_type}', got '{result['link_sub_type']}'"
    
    @given(sub_type=st.sampled_from(UNSUPPORTED_SUB_TYPES))
    @settings(max_examples=100)
    def test_unsupported_sub_type_routes_to_unknown(self, sub_type: int):
        """
        Property: 不支持的 sub_type 应路由到 'unknown'
        
        Feature: linkfile-pipeline, Property 1: 子类型路由正确性
        **Validates: Requirements 1.1, 1.4**
        """
        extractor = create_test_extractor()
        
        # 构造测试消息
        msg = {
            'type': 49,
            'sub_type': sub_type,
            'msg_uid': f'P1:test_{sub_type}',
            'MsgSvrID': f'test_{sub_type}',
        }
        
        result = extractor._extract_one(msg, {})
        
        # 验证 link_sub_type 为 'unknown'
        assert result is not None, f"Result should not be None for sub_type={sub_type}"
        assert result['link_sub_type'] == 'unknown', \
            f"sub_type={sub_type} should route to 'unknown', got '{result['link_sub_type']}'"
    
    @given(sub_type=st.integers(min_value=-100, max_value=300))
    @settings(max_examples=100)
    def test_any_sub_type_produces_valid_link_sub_type(self, sub_type: int):
        """
        Property: 任意 sub_type 都应产生有效的 link_sub_type
        
        Feature: linkfile-pipeline, Property 1: 子类型路由正确性
        **Validates: Requirements 1.1, 1.4**
        """
        extractor = create_test_extractor()
        
        # 构造测试消息
        msg = {
            'type': 49,
            'sub_type': sub_type,
            'msg_uid': f'P1:test_{sub_type}',
            'MsgSvrID': f'test_{sub_type}',
            'link_url': 'https://example.com',
            'link_title': 'Test Title',
            'media_path': 'file/test.pdf',
        }
        
        result = extractor._extract_one(msg, {})
        
        # 验证结果不为 None
        assert result is not None, f"Result should not be None for sub_type={sub_type}"
        
        # 验证 link_sub_type 字段存在
        assert 'link_sub_type' in result, \
            f"Result should contain 'link_sub_type' field for sub_type={sub_type}"
        
        # 验证 link_sub_type 值有效
        valid_link_sub_types = {'quote', 'link', 'file', 'miniprogram', 'video_channel', 'chat_history', 'unknown', 'error'}
        assert result['link_sub_type'] in valid_link_sub_types, \
            f"link_sub_type '{result['link_sub_type']}' is not valid for sub_type={sub_type}"
        
        # 验证路由正确性
        if sub_type in SUPPORTED_SUB_TYPES:
            expected = SUPPORTED_SUB_TYPES[sub_type]
            assert result['link_sub_type'] == expected, \
                f"sub_type={sub_type} should route to '{expected}', got '{result['link_sub_type']}'"
        else:
            assert result['link_sub_type'] == 'unknown', \
                f"sub_type={sub_type} should route to 'unknown', got '{result['link_sub_type']}'"


# =============================================================================
# 运行测试
# =============================================================================

if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
