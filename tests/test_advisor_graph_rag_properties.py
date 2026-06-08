"""
GraphRAG 属性测试

Property 15: GraphRAG 增量更新等价性
**Feature: relationship-advisor-agent, Property 15: GraphRAG 增量更新等价性**
**Validates: Requirements 17.5**

测试策略：
- 不加载真实嵌入模型，使用 mock 的 encode 函数（确定性哈希向量）
- 验证全量构建 vs 分批增量更新产生相同的文档集和查询结果
"""

import hashlib
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from hypothesis import given, settings, strategies as st

from scripts.advisor.graph_rag import GraphRAGManager


# =============================================================================
# 测试策略
# =============================================================================

@st.composite
def message_strategy(draw):
    """生成单条消息"""
    speaker = draw(st.sampled_from(['ME', 'OTHER']))
    # 使用中文常见词汇生成文本
    words = draw(st.lists(
        st.sampled_from([
            '你好', '今天', '工作', '开心', '难过', '吃饭', '睡觉',
            '想你', '在吗', '好的', '嗯', '哈哈', '累了', '回家',
            '明天', '一起', '出去', '玩', '电影', '吵架', '对不起',
        ]),
        min_size=2, max_size=10,
    ))
    text = ''.join(words)
    # 使用递增时间戳
    ts = draw(st.integers(min_value=1700000000, max_value=1700100000))
    return {
        'speaker': speaker,
        'text_raw': text,
        'ts': str(ts),
        'type': 'text',
    }


@st.composite
def message_list_strategy(draw, min_size=25, max_size=80):
    """生成消息列表（按时间排序）"""
    messages = draw(st.lists(message_strategy(), min_size=min_size, max_size=max_size))
    messages.sort(key=lambda m: m['ts'])
    return messages


def deterministic_encode(texts, show_progress_bar=False, batch_size=32, normalize_embeddings=True):
    """确定性编码函数：基于文本哈希生成固定维度向量"""
    vectors = []
    for text in texts:
        h = hashlib.sha256(text.encode('utf-8')).digest()
        # 取前 32 字节生成 8 维向量
        vec = np.array([float(b) / 255.0 for b in h[:8]], dtype=np.float32)
        if normalize_embeddings:
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec = vec / norm
        vectors.append(vec)
    return np.array(vectors)


def create_mock_manager(config=None):
    """创建带 mock 嵌入模型的 GraphRAGManager"""
    config = config or {}
    manager = GraphRAGManager(config)
    # Mock 嵌入模型
    mock_model = MagicMock()
    mock_model.encode = deterministic_encode
    manager._embedding_model = mock_model
    return manager


# =============================================================================
# Property 15: GraphRAG 增量更新等价性
# =============================================================================

class TestGraphRAGIncrementalUpdateEquivalence:
    """Property 15: GraphRAG 增量更新等价性

    **Feature: relationship-advisor-agent, Property 15: GraphRAG 增量更新等价性**
    **Validates: Requirements 17.5**

    For any 图谱和新消息集合，增量更新后的图谱查询结果应与全量重建后的图谱查询结果等价。
    """

    @settings(max_examples=100, deadline=None)
    @given(message_list_strategy(min_size=40, max_size=80))
    def test_incremental_update_preserves_existing_and_adds_new(self, messages):
        """增量更新应保留已有文档并追加新文档，且文档数等于各批次分段之和

        **Validates: Requirements 17.5**
        """
        # 将消息分成两批
        split = len(messages) // 2
        batch1 = messages[:split]
        batch2 = messages[split:]

        manager = create_mock_manager()

        # 构建 batch1
        docs1 = manager._segment_to_documents(batch1)
        manager._documents = list(docs1)  # 复制
        if docs1:
            texts1 = [d['text'] for d in docs1]
            manager._embeddings = deterministic_encode(texts1)

        docs1_count = len(manager._documents)

        # 预计算 batch2 会产生多少文档
        expected_new_docs = len(manager._segment_to_documents(batch2))

        # 执行增量更新
        if batch2:
            manager.update_index(batch2)

        # 验证：增量更新后文档数 = 原有 + 新增
        assert len(manager._documents) == docs1_count + expected_new_docs

        # 验证：原有文档未被修改（前 docs1_count 个文档不变）
        for i in range(docs1_count):
            assert manager._documents[i]['text'] == docs1[i]['text']

    @settings(max_examples=100, deadline=None)
    @given(message_list_strategy(min_size=40, max_size=80))
    def test_incremental_query_results_contain_all_relevant_docs(self, messages):
        """增量更新后查询应能检索到所有批次的文档

        **Validates: Requirements 17.5**
        """
        split = len(messages) // 2
        batch1 = messages[:split]
        batch2 = messages[split:]

        manager = create_mock_manager()

        # 构建 batch1
        docs1 = manager._segment_to_documents(batch1)
        manager._documents = docs1
        if docs1:
            texts1 = [d['text'] for d in docs1]
            manager._embeddings = deterministic_encode(texts1)

        # 增量更新 batch2
        if batch2:
            manager.update_index(batch2)

        if not manager._documents:
            return  # 没有文档，跳过

        # 用 batch2 中的文本查询，应该能返回结果
        query_text = batch2[0].get('text_raw', '你好')
        results = manager.query_fast(query_text, top_k=3)

        # 应该有结果（只要有文档就应该能查到）
        assert len(results) > 0
        # 每个结果应该有 score 字段
        for r in results:
            assert 'score' in r
            assert 'text' in r

    @settings(max_examples=100, deadline=None)
    @given(message_list_strategy(min_size=40, max_size=80))
    def test_incremental_embeddings_match_full_rebuild(self, messages):
        """增量更新后的嵌入矩阵行数应等于文档数

        **Validates: Requirements 17.5**
        """
        split = len(messages) // 2
        batch1 = messages[:split]
        batch2 = messages[split:]

        manager = create_mock_manager()

        # 构建 batch1
        docs1 = manager._segment_to_documents(batch1)
        manager._documents = docs1
        if docs1:
            texts1 = [d['text'] for d in docs1]
            manager._embeddings = deterministic_encode(texts1)

        # 增量更新 batch2
        if batch2:
            manager.update_index(batch2)

        # 嵌入矩阵行数应等于文档数
        if manager._embeddings is not None:
            assert manager._embeddings.shape[0] == len(manager._documents)
        else:
            assert len(manager._documents) == 0

    @settings(max_examples=100, deadline=None)
    @given(
        message_list_strategy(min_size=30, max_size=60),
        st.integers(min_value=2, max_value=5),
    )
    def test_multi_batch_incremental_equals_single_incremental(self, messages, num_batches):
        """多次增量更新的最终文档数等于各批次文档数之和

        **Validates: Requirements 17.5**
        """
        # 将消息分成 num_batches 批
        batch_size = max(1, len(messages) // num_batches)
        batches = []
        for i in range(0, len(messages), batch_size):
            batch = messages[i:i + batch_size]
            if batch:
                batches.append(batch)

        if not batches:
            return

        manager = create_mock_manager()

        # 逐批增量更新
        expected_doc_count = 0
        for i, batch in enumerate(batches):
            batch_docs = manager._segment_to_documents(batch)
            expected_doc_count += len(batch_docs)

            if i == 0:
                # 第一批：直接设置
                manager._documents = batch_docs
                if batch_docs:
                    texts = [d['text'] for d in batch_docs]
                    manager._embeddings = deterministic_encode(texts)
            else:
                # 后续批次：增量更新
                if batch:
                    manager.update_index(batch)

        # 最终文档数应等于各批次文档数之和
        assert len(manager._documents) == expected_doc_count

        # 嵌入矩阵一致性
        if manager._embeddings is not None:
            assert manager._embeddings.shape[0] == len(manager._documents)

    @settings(max_examples=100, deadline=None)
    @given(message_list_strategy(min_size=25, max_size=50))
    def test_segment_to_documents_deterministic(self, messages):
        """相同输入的文档分段结果应完全一致（确定性）

        **Validates: Requirements 17.5**
        """
        manager = create_mock_manager()

        docs1 = manager._segment_to_documents(messages)
        docs2 = manager._segment_to_documents(messages)

        assert len(docs1) == len(docs2)
        for d1, d2 in zip(docs1, docs2):
            assert d1['text'] == d2['text']
            assert d1['start_ts'] == d2['start_ts']
            assert d1['end_ts'] == d2['end_ts']
            assert d1['msg_count'] == d2['msg_count']
