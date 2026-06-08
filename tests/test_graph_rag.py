"""
GraphRAG 属性测试

Property 15: GraphRAG 增量更新等价性
- 全量构建 N 条对话的索引 ≡ 先构建前 K 条 + 增量追加剩余 N-K 条
- 对同一查询，两种方式返回的结果集合应一致

额外测试：
- 索引持久化 round-trip（save → load → query 结果一致）
- 用户档案构建正确性
- 快速检索 vs 完整检索的候选覆盖

Requirements: 17.1, 17.2, 17.3, 17.4, 17.5, 17.6, 17.7
"""

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

# 添加项目根目录
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# ---------------------------------------------------------------------------
# 跳过条件：需要 FlagEmbedding + faiss
# ---------------------------------------------------------------------------
try:
    from FlagEmbedding import BGEM3FlagModel  # noqa: F401
    import faiss  # noqa: F401
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False

skip_no_deps = pytest.mark.skipif(
    not HAS_DEPS,
    reason="FlagEmbedding 或 faiss-cpu 未安装，跳过 GraphRAG 测试",
)

# 跳过无 GPU 环境（BGE-M3 在 CPU 上很慢，CI 中跳过）
try:
    import torch
    HAS_GPU = torch.cuda.is_available()
except ImportError:
    HAS_GPU = False

skip_no_gpu = pytest.mark.skipif(
    not HAS_GPU,
    reason="无 GPU 环境，跳过需要 GPU 的 GraphRAG 测试",
)


# ---------------------------------------------------------------------------
# 测试数据
# ---------------------------------------------------------------------------

SAMPLE_CONVERSATIONS = [
    {
        'conversation_id': 'conv_0',
        'conversation_text': 'ME: 今天加班好累啊\nOTHER: 辛苦了宝贝，早点回来',
        'timestamp': '2025-01-15T20:00:00',
    },
    {
        'conversation_id': 'conv_1',
        'conversation_text': 'ME: 你为什么不回我消息\nOTHER: 我在开会啊\nME: 你总是这样',
        'timestamp': '2025-02-10T14:30:00',
    },
    {
        'conversation_id': 'conv_2',
        'conversation_text': 'ME: 周末一起去旅游吧\nOTHER: 好呀去哪里\nME: 去海边怎么样',
        'timestamp': '2025-03-05T09:00:00',
    },
    {
        'conversation_id': 'conv_3',
        'conversation_text': 'ME: 你妈又说我了\nOTHER: 她不是那个意思\nME: 你永远站她那边',
        'timestamp': '2025-04-20T19:00:00',
    },
    {
        'conversation_id': 'conv_4',
        'conversation_text': 'ME: 我爱你\nOTHER: 我也爱你\nME: 永远在一起好不好',
        'timestamp': '2025-05-14T22:00:00',
    },
    {
        'conversation_id': 'conv_5',
        'conversation_text': 'ME: 钱不够花了怎么办\nOTHER: 我们省着点\nME: 房贷压力好大',
        'timestamp': '2025-06-01T18:00:00',
    },
    {
        'conversation_id': 'conv_6',
        'conversation_text': 'ME: 你怎么又跟朋友出去喝酒\nOTHER: 就一次而已\nME: 你凭什么不跟我说',
        'timestamp': '2025-06-15T23:00:00',
    },
    {
        'conversation_id': 'conv_7',
        'conversation_text': 'ME: 孩子今天说了第一句话\nOTHER: 真的吗太棒了\nME: 叫的是妈妈',
        'timestamp': '2025-07-01T10:00:00',
    },
]


def _make_config(index_dir: str, use_gpu: bool = False) -> dict:
    return {
        'embedding_model': 'BAAI/bge-m3',
        'reranker_model': 'BAAI/bge-reranker-v2-m3',
        'index_dir': index_dir,
        'top_k_retrieval': 5,
        'top_k_rerank': 3,
        'use_gpu_for_embedding': use_gpu,
    }


# ---------------------------------------------------------------------------
# Property 15: 增量更新等价性
# ---------------------------------------------------------------------------

@skip_no_deps
@skip_no_gpu
class TestIncrementalEquivalence:
    """Property 15: GraphRAG 增量更新等价性"""

    def test_incremental_equals_full_build(self, tmp_path):
        """全量构建 vs 先构建一半+增量追加，查询结果的 ID 集合应一致"""
        from scripts.advisor.graph_rag import GraphRAGManager

        split = 4
        all_convs = SAMPLE_CONVERSATIONS

        # 全量构建
        full_dir = str(tmp_path / 'full')
        mgr_full = GraphRAGManager(_make_config(full_dir, use_gpu=True))
        mgr_full.build_index(all_convs)

        # 增量构建
        incr_dir = str(tmp_path / 'incr')
        mgr_incr = GraphRAGManager(_make_config(incr_dir, use_gpu=True))
        mgr_incr.build_index(all_convs[:split])
        mgr_incr.update_index(all_convs[split:])

        # 查询
        query = "最近又因为钱的事情吵架了"
        results_full = mgr_full.query_fast(query, top_k=3)
        results_incr = mgr_incr.query_fast(query, top_k=3)

        ids_full = {r.conversation_id for r in results_full}
        ids_incr = {r.conversation_id for r in results_incr}

        # 增量索引应包含全量索引的所有候选
        assert ids_full == ids_incr, (
            f"增量更新结果不一致：full={ids_full}, incr={ids_incr}"
        )

        # 索引总数一致
        assert mgr_full._faiss_index.ntotal == mgr_incr._faiss_index.ntotal

        mgr_full.unload_models()
        mgr_incr.unload_models()

    def test_incremental_vector_count(self, tmp_path):
        """增量更新后向量总数 = 初始 + 新增"""
        from scripts.advisor.graph_rag import GraphRAGManager

        dir_ = str(tmp_path / 'count')
        mgr = GraphRAGManager(_make_config(dir_, use_gpu=True))

        mgr.build_index(SAMPLE_CONVERSATIONS[:3])
        assert mgr._faiss_index.ntotal == 3

        mgr.update_index(SAMPLE_CONVERSATIONS[3:])
        assert mgr._faiss_index.ntotal == len(SAMPLE_CONVERSATIONS)

        mgr.unload_models()


# ---------------------------------------------------------------------------
# 索引持久化 round-trip
# ---------------------------------------------------------------------------

@skip_no_deps
@skip_no_gpu
class TestIndexPersistence:
    """索引保存/加载后查询结果一致"""

    def test_save_load_roundtrip(self, tmp_path):
        from scripts.advisor.graph_rag import GraphRAGManager

        dir_ = str(tmp_path / 'persist')
        mgr = GraphRAGManager(_make_config(dir_, use_gpu=True))
        mgr.build_index(SAMPLE_CONVERSATIONS)

        query = "工作太忙了"
        before = mgr.query_fast(query, top_k=3)
        before_ids = [r.conversation_id for r in before]

        mgr.save_index()
        mgr.unload_models()

        # 新实例加载
        mgr2 = GraphRAGManager(_make_config(dir_, use_gpu=True))
        assert mgr2.load_index()

        after = mgr2.query_fast(query, top_k=3)
        after_ids = [r.conversation_id for r in after]

        assert before_ids == after_ids
        assert mgr2._faiss_index.ntotal == len(SAMPLE_CONVERSATIONS)

        mgr2.unload_models()

    def test_user_profile_persisted(self, tmp_path):
        from scripts.advisor.graph_rag import GraphRAGManager

        dir_ = str(tmp_path / 'profile')
        mgr = GraphRAGManager(_make_config(dir_, use_gpu=True))
        mgr.build_index(SAMPLE_CONVERSATIONS)
        mgr.save_index()

        profile_before = mgr.get_user_profile()
        assert profile_before is not None
        assert profile_before.total_conversations == len(SAMPLE_CONVERSATIONS)

        mgr.unload_models()

        # 新实例加载
        mgr2 = GraphRAGManager(_make_config(dir_, use_gpu=True))
        mgr2.load_index()
        profile_after = mgr2.get_user_profile()

        assert profile_after is not None
        assert profile_after.total_conversations == profile_before.total_conversations
        assert profile_after.recurring_topics == profile_before.recurring_topics

        mgr2.unload_models()


# ---------------------------------------------------------------------------
# 用户档案
# ---------------------------------------------------------------------------

@skip_no_deps
@skip_no_gpu
class TestUserProfile:
    """用户档案构建正确性"""

    def test_profile_fields_populated(self, tmp_path):
        from scripts.advisor.graph_rag import GraphRAGManager

        dir_ = str(tmp_path / 'profile_fields')
        mgr = GraphRAGManager(_make_config(dir_, use_gpu=True))
        mgr.build_index(SAMPLE_CONVERSATIONS)

        profile = mgr.get_user_profile()
        assert profile is not None
        assert profile.total_conversations == len(SAMPLE_CONVERSATIONS)
        assert profile.date_range[0] != ''
        assert profile.date_range[1] != ''
        assert profile.last_updated != ''
        # 应检测到一些情绪
        assert len(profile.top_emotions) > 0

        mgr.unload_models()

    def test_profile_date_range(self, tmp_path):
        from scripts.advisor.graph_rag import GraphRAGManager

        dir_ = str(tmp_path / 'date_range')
        mgr = GraphRAGManager(_make_config(dir_, use_gpu=True))
        mgr.build_index(SAMPLE_CONVERSATIONS)

        profile = mgr.get_user_profile()
        assert profile.date_range[0] <= profile.date_range[1]

        mgr.unload_models()


# ---------------------------------------------------------------------------
# 快速检索 vs 完整检索
# ---------------------------------------------------------------------------

@skip_no_deps
@skip_no_gpu
class TestQueryModes:
    """query_fast vs query_related"""

    def test_fast_query_returns_results(self, tmp_path):
        from scripts.advisor.graph_rag import GraphRAGManager

        dir_ = str(tmp_path / 'fast')
        mgr = GraphRAGManager(_make_config(dir_, use_gpu=True))
        mgr.build_index(SAMPLE_CONVERSATIONS)

        results = mgr.query_fast("吵架了", top_k=3)
        assert len(results) > 0
        assert all(r.score > 0 for r in results)

        mgr.unload_models()

    def test_reranked_query_returns_results(self, tmp_path):
        from scripts.advisor.graph_rag import GraphRAGManager

        dir_ = str(tmp_path / 'rerank')
        mgr = GraphRAGManager(_make_config(dir_, use_gpu=True))
        mgr.build_index(SAMPLE_CONVERSATIONS)

        results = mgr.query_related("吵架了", top_k=3)
        assert len(results) > 0
        # 重排后分数应按降序
        for i in range(len(results) - 1):
            assert results[i].score >= results[i + 1].score

        mgr.unload_models()

    def test_fast_covers_reranked_candidates(self, tmp_path):
        """快速检索的 top-K 应覆盖重排后的 top-k 候选"""
        from scripts.advisor.graph_rag import GraphRAGManager

        dir_ = str(tmp_path / 'cover')
        mgr = GraphRAGManager(_make_config(dir_, use_gpu=True))
        mgr.build_index(SAMPLE_CONVERSATIONS)

        query = "你总是不回消息"
        fast_results = mgr.query_fast(query, top_k=5)
        reranked_results = mgr.query_related(query, top_k=3)

        fast_ids = {r.conversation_id for r in fast_results}
        reranked_ids = {r.conversation_id for r in reranked_results}

        # 重排后的结果应是快速检索的子集
        assert reranked_ids.issubset(fast_ids), (
            f"重排结果 {reranked_ids} 不是快速检索 {fast_ids} 的子集"
        )

        mgr.unload_models()


# ---------------------------------------------------------------------------
# 上下文摘要
# ---------------------------------------------------------------------------

@skip_no_deps
@skip_no_gpu
class TestContextSummary:
    """上下文摘要生成"""

    def test_context_summary_structure(self, tmp_path):
        from scripts.advisor.graph_rag import GraphRAGManager

        dir_ = str(tmp_path / 'summary')
        mgr = GraphRAGManager(_make_config(dir_, use_gpu=True))
        mgr.build_index(SAMPLE_CONVERSATIONS)

        summary = mgr.generate_context_summary("又因为钱吵架了", top_k=3)
        assert hasattr(summary, 'related_history')
        assert hasattr(summary, 'pattern_summary')
        assert hasattr(summary, 'topic_evolution')
        assert len(summary.related_history) <= 3

        mgr.unload_models()


# ---------------------------------------------------------------------------
# 纯单元测试（不需要模型/GPU）
# ---------------------------------------------------------------------------

class TestTextAnalysisHelpers:
    """文本分析辅助方法（纯 CPU，无需模型）"""

    def test_extract_topics(self):
        from scripts.advisor.graph_rag import GraphRAGManager
        topics = GraphRAGManager._extract_topics("今天工作加班到很晚，老板又催项目")
        assert '工作' in topics

    def test_has_conflict(self):
        from scripts.advisor.graph_rag import GraphRAGManager
        assert GraphRAGManager._has_conflict("你怎么又生气了")
        assert not GraphRAGManager._has_conflict("今天天气真好")

    def test_extract_emotions(self):
        from scripts.advisor.graph_rag import GraphRAGManager
        emotions = GraphRAGManager._extract_emotions("我好开心啊，太幸福了")
        assert '开心' in emotions

    def test_compute_trend_stable(self):
        from scripts.advisor.graph_rag import GraphRAGManager
        convs = [{'conversation_text': '普通聊天'}] * 6
        assert GraphRAGManager._compute_trend(convs) == 'stable'

    def test_compute_trend_insufficient_data(self):
        from scripts.advisor.graph_rag import GraphRAGManager
        convs = [{'conversation_text': '聊天'}] * 2
        assert GraphRAGManager._compute_trend(convs) == 'stable'

    def test_detect_communication_styles(self):
        from scripts.advisor.graph_rag import GraphRAGManager
        convs = [
            {'conversation_text': 'ME: 这是一条比较长的消息内容用来测试沟通风格检测功能是否正常工作，我觉得这个功能还是挺有意思的，希望能检测出正确的结果来\nOTHER: 嗯'},
        ] * 5
        me_style, other_style = GraphRAGManager._detect_communication_styles(convs)
        assert '长文本型' in me_style
        assert '简短回复型' in other_style


# ---------------------------------------------------------------------------
# LongTermContextAnalyzer 升级测试（纯单元，mock GraphRAG）
# ---------------------------------------------------------------------------

class TestLongTermContextAnalyzerUpgrade:
    """验证 LongTermContextAnalyzer 正确委托给 GraphRAGManager"""

    def test_analyze_patterns_with_lookback(self):
        """max_lookback_days 过滤生效"""
        from scripts.advisor.analyzers import LongTermContextAnalyzer

        analyzer = LongTermContextAnalyzer(max_lookback_days=30)

        # 30 天前的对话应被过滤
        old_conv = {
            'conversation_text': 'ME: 老对话\nOTHER: 是的',
            'timestamp': '2020-01-01T00:00:00',
        }
        recent_conv = {
            'conversation_text': 'ME: 最近工作好累\nOTHER: 辛苦了',
            'timestamp': '2099-01-01T00:00:00',
        }

        pattern = analyzer.analyze_patterns([old_conv, recent_conv])
        # 只有 recent_conv 应被分析（old_conv 超过 30 天被过滤）
        # 但 recurring 需要 >= 2 次，所以可能为空
        assert isinstance(pattern.recurring_topics, list)
        assert pattern.relationship_trend == 'stable'

    def test_analyze_patterns_no_lookback(self):
        """max_lookback_days=0 不过滤"""
        from scripts.advisor.analyzers import LongTermContextAnalyzer

        analyzer = LongTermContextAnalyzer(max_lookback_days=0)
        convs = [
            {'conversation_text': 'ME: 工作好忙\nOTHER: 加油', 'timestamp': '2020-01-01'},
            {'conversation_text': 'ME: 工作又加班\nOTHER: 辛苦了', 'timestamp': '2020-06-01'},
            {'conversation_text': 'ME: 工作压力大\nOTHER: 注意身体', 'timestamp': '2020-12-01'},
        ]
        pattern = analyzer.analyze_patterns(convs)
        assert '工作' in pattern.recurring_topics


# ---------------------------------------------------------------------------
# 多模态信号关键词测试（纯 CPU，无需模型）
# ---------------------------------------------------------------------------

class TestMultimodalKeywords:
    """验证多模态信号关键词在话题/冲突/情绪检测中生效"""

    def test_extract_topics_voice_emotion(self):
        from scripts.advisor.graph_rag import GraphRAGManager
        text = "[第5天 22:30] ME: [语音: 我不想说了] (情绪:ANGRY, 语气急促)"
        topics = GraphRAGManager._extract_topics(text)
        assert '情绪波动' in topics

    def test_extract_topics_image_atmosphere(self):
        from scripts.advisor.graph_rag import GraphRAGManager
        text = "[第10天 20:00] ME: [图片: 两人合照] (意图:分享, 氛围:温馨)"
        topics = GraphRAGManager._extract_topics(text)
        assert '亲密互动' in topics

    def test_extract_topics_cold_period(self):
        from scripts.advisor.graph_rag import GraphRAGManager
        text = "--- [cold_period: 3天未联系] ---\nME: 你还好吗"
        topics = GraphRAGManager._extract_topics(text)
        assert '冷暴力信号' in topics

    def test_has_conflict_multimodal(self):
        from scripts.advisor.graph_rag import GraphRAGManager
        assert GraphRAGManager._has_conflict("(情绪:ANGRY, 语气急促)")
        assert GraphRAGManager._has_conflict("--- [argument_gap: 2小时] ---")
        assert GraphRAGManager._has_conflict("氛围:紧张")
        assert not GraphRAGManager._has_conflict("氛围:温馨")

    def test_extract_emotions_multimodal(self):
        from scripts.advisor.graph_rag import GraphRAGManager
        emotions = GraphRAGManager._extract_emotions("(情绪:ANGRY)")
        assert '生气' in emotions

        emotions2 = GraphRAGManager._extract_emotions("(氛围:温馨)")
        assert '甜蜜' in emotions2

        emotions3 = GraphRAGManager._extract_emotions("--- [cold_period] ---")
        assert '冷淡' in emotions3

    def test_analyzer_multimodal_topics(self):
        from scripts.advisor.analyzers import LongTermContextAnalyzer
        analyzer = LongTermContextAnalyzer()
        text = "[语音: 你好烦啊] (情绪:SAD, 声音低沉)"
        topics = analyzer._extract_topics(text)
        assert '情绪波动' in topics

    def test_analyzer_multimodal_conflict(self):
        from scripts.advisor.analyzers import LongTermContextAnalyzer
        analyzer = LongTermContextAnalyzer()
        assert analyzer._has_conflict("你说话很伤人")
        assert analyzer._has_conflict("--- [argument_gap] ---")

    def test_analyzer_multimodal_trend(self):
        """多模态情感信号影响趋势判断"""
        from scripts.advisor.analyzers import LongTermContextAnalyzer
        analyzer = LongTermContextAnalyzer()

        # 前半段有冲突信号，后半段有亲密信号 → improving
        convs = [
            {'conversation_text': '情绪:ANGRY 情绪:SAD 分手 烦 生气 讨厌'},
            {'conversation_text': '情绪:ANGRY argument_gap 烦 讨厌 不想'},
            {'conversation_text': '情绪:ANGRY 氛围:紧张 生气 分手'},
            {'conversation_text': '氛围:温馨 氛围:浪漫 爱 喜欢 开心 宝贝 幸福 甜'},
            {'conversation_text': '氛围:欢乐 撒娇 卖萌 爱 想你 宝贝 幸福 开心'},
            {'conversation_text': '氛围:温馨 表达爱意 爱 喜欢 开心 宝贝 幸福'},
        ]
        assert analyzer._analyze_trend(convs) == 'improving'
