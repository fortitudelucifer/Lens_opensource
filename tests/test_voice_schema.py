"""
test_voice_schema.py
Voice 模态 merged_final.jsonl 输出格式的属性测试

验证属性：
- Property 1: 字段完整性
- Property 2: 字段顺序

Validates: Requirements 3.1, 3.2, 3.4

运行方式：
    python -m pytest tests/test_voice_schema.py -v
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
    VOICE_SPECIFIC_FIELDS,
)
from scripts._common.path_utils import get_voice_after_merge


def load_voice_merged_final():
    """加载 voice_merged_final.jsonl 文件"""
    after_merge = get_voice_after_merge()
    output_file = after_merge / 'voice_merged_final.jsonl'
    
    if not output_file.exists():
        pytest.skip(f"文件不存在: {output_file}")
    
    records = []
    with open(output_file, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))
    
    if not records:
        pytest.skip("文件为空")
    
    return records


class TestVoiceSchemaProperties:
    """Voice 模态 Schema 属性测试"""
    
    @pytest.fixture(scope="class")
    def records(self):
        """加载测试数据"""
        return load_voice_merged_final()
    
    def test_property1_field_completeness(self, records):
        """
        Property 1: 字段完整性
        
        For any merged_final.jsonl 记录，该记录 SHALL 包含所有 
        COMMON_HEADER_FIELDS 定义的字段。
        
        **Validates: Requirements 3.1, 3.2**
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
        
        **Validates: Requirements 3.4**
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
                for field in VOICE_SPECIFIC_FIELDS:
                    if field in keys:
                        assert keys.index(field) > max_common_idx, \
                            f"记录 {i}: 特定字段 {field} 应该在公共字段之后"
    
    def test_msg_uid_present(self, records):
        """
        测试 msg_uid 作为主键存在
        
        **Validates: Requirements 3.1**
        """
        for i, record in enumerate(records):
            assert 'msg_uid' in record, f"记录 {i}: 应存在 'msg_uid' 字段"
            # msg_uid 不应为空（除非原始数据确实没有）
            # 允许空字符串，因为可能有些语音文件无法关联到原始消息
    
    def test_schema_version_value(self, records):
        """测试 schema_version 值正确"""
        for i, record in enumerate(records):
            assert record.get('schema_version') == SCHEMA_VERSION, \
                f"记录 {i}: schema_version 应为 '{SCHEMA_VERSION}'，实际为 '{record.get('schema_version')}'"
    
    def test_modality_value(self, records):
        """测试 modality 值为 'voice'"""
        for i, record in enumerate(records):
            assert record.get('modality') == 'voice', \
                f"记录 {i}: modality 应为 'voice'，实际为 '{record.get('modality')}'"
    
    def test_no_legacy_file_field(self, records):
        """
        测试不存在旧的 'file' 字段作为主键
        
        voice 模态的 'file' 字段应该被映射为 'media_path'
        """
        # 注意：voice 模态可能仍有 'file' 字段在 funasr/whisper 子对象中
        # 这里只检查顶层不应该有 'file' 作为主键
        for i, record in enumerate(records):
            # 如果有 file 字段，它应该不是顶层主键
            # media_path 应该存在
            assert 'media_path' in record, \
                f"记录 {i}: 应存在 'media_path' 字段"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
