"""
test_image_schema.py
Image 模态 merged_final.jsonl 输出格式的属性测试

验证属性：
- Property 1: 字段完整性
- Property 2: 字段顺序
- Property 3: 字段命名一致性

Validates: Requirements 2.1, 2.2, 2.3, 2.4

运行方式：
    python -m pytest tests/test_image_schema.py -v
"""

import json
import os
import sys
from pathlib import Path

import pytest

# Setup paths
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts._common.schema_utils import (
    SCHEMA_VERSION,
    COMMON_HEADER_FIELDS,
    IMAGE_SPECIFIC_FIELDS,
)
from scripts._common.path_utils import PATHS


def load_image_merged_final():
    """加载 image_merged_final.jsonl 文件"""
    after_merge = PATHS.get('artifacts', {}).get('image_after', f'{PROJECT_ROOT}/artifacts/after_merge/image')
    output_file = os.path.join(after_merge, 'image_merged_final.jsonl')
    
    if not os.path.exists(output_file):
        pytest.skip(f"文件不存在: {output_file}")
    
    records = []
    with open(output_file, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))
    
    if not records:
        pytest.skip("文件为空")
    
    return records


class TestImageSchemaProperties:
    """Image 模态 Schema 属性测试"""
    
    @pytest.fixture(scope="class")
    def records(self):
        """加载测试数据"""
        return load_image_merged_final()
    
    def test_property1_field_completeness(self, records):
        """
        Property 1: 字段完整性
        
        For any merged_final.jsonl 记录，该记录 SHALL 包含所有 
        COMMON_HEADER_FIELDS 定义的字段。
        
        **Validates: Requirements 2.3**
        """
        for i, record in enumerate(records):
            for field in COMMON_HEADER_FIELDS:
                assert field in record, \
                    f"记录 {i} (msg_uid={record.get('msg_uid')}) 缺少公共字段: {field}"
    
    def test_property2_field_ordering(self, records):
        """
        Property 2: 字段顺序
        
        For any merged_final.jsonl 记录：
        1. schema_version SHALL 是第一个字段
        2. COMMON_HEADER_FIELDS SHALL 按定义顺序排列在前
        3. 模态特定字段 SHALL 排列在 COMMON_HEADER_FIELDS 之后
        
        **Validates: Requirements 2.4**
        """
        for i, record in enumerate(records):
            keys = list(record.keys())
            
            # 1. schema_version 应该是第一个字段
            assert keys[0] == 'schema_version', \
                f"记录 {i}: schema_version 应该是第一个字段，实际是 {keys[0]}"
            
            # 2. 公共字段应该按顺序排列
            common_indices = []
            for field in COMMON_HEADER_FIELDS:
                if field in keys:
                    common_indices.append(keys.index(field))
            
            assert common_indices == sorted(common_indices), \
                f"记录 {i}: 公共字段顺序不正确"
            
            # 3. 模态特定字段应该在公共字段之后
            if common_indices:
                max_common_idx = max(common_indices)
                for field in IMAGE_SPECIFIC_FIELDS:
                    if field in keys:
                        assert keys.index(field) > max_common_idx, \
                            f"记录 {i}: 特定字段 {field} 应该在公共字段之后"
    
    def test_property3_field_naming_consistency(self, records):
        """
        Property 3: 字段命名一致性
        
        For any merged_final.jsonl 记录：
        1. 时间戳字段 SHALL 命名为 "ts"（不是 "timestamp"）
        2. 发送者字段 SHALL 命名为 "speaker"（不是 "sender"）
        3. 不 SHALL 存在 "timestamp" 或 "sender" 字段
        
        **Validates: Requirements 2.1, 2.2**
        """
        for i, record in enumerate(records):
            # 不应存在旧字段名
            assert 'timestamp' not in record, \
                f"记录 {i}: 不应存在 'timestamp' 字段，应使用 'ts'"
            assert 'sender' not in record, \
                f"记录 {i}: 不应存在 'sender' 字段，应使用 'speaker'"
            
            # 应存在新字段名
            assert 'ts' in record, \
                f"记录 {i}: 应存在 'ts' 字段"
            assert 'speaker' in record, \
                f"记录 {i}: 应存在 'speaker' 字段"
    
    def test_schema_version_value(self, records):
        """测试 schema_version 值正确"""
        for i, record in enumerate(records):
            assert record.get('schema_version') == SCHEMA_VERSION, \
                f"记录 {i}: schema_version 应为 '{SCHEMA_VERSION}'，实际为 '{record.get('schema_version')}'"
    
    def test_modality_value(self, records):
        """测试 modality 值为 'image'"""
        for i, record in enumerate(records):
            assert record.get('modality') == 'image', \
                f"记录 {i}: modality 应为 'image'，实际为 '{record.get('modality')}'"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
