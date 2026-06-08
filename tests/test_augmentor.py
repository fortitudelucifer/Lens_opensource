"""
数据增强与蒸馏测试

Property 16: 数据增强格式与质量
- 导入后样本格式正确（含 conversation, source）
- 蒸馏后样本包含必要字段
- 质量过滤有效去除低质量样本
- 输出 JSONL 格式正确

Requirements: 18.1, 18.2, 18.3, 18.4, 18.5, 18.6, 18.7, 18.8
"""

import json
import sys
import tempfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.advisor.augmentor import (
    AugmentedSample,
    AugmentationStats,
    DataAugmentor,
    PsyCLIENTAdapter,
    CPsDDAdapter,
    AuraDialAdapter,
    DATASET_ADAPTERS,
)


# ---------------------------------------------------------------------------
# 测试数据
# ---------------------------------------------------------------------------

MOCK_PSYCLIENT_DATA = [
    {
        "messages": [
            {"role": "client", "content": "最近和男朋友经常吵架，我不知道该怎么办"},
            {"role": "counselor", "content": "听起来你最近很烦恼，能具体说说是什么原因导致你们争吵吗？"},
            {"role": "client", "content": "就是他总是加班，回来很晚，我觉得他不关心我"},
            {"role": "counselor", "content": "你觉得被忽视了，这种感受是可以理解的"},
        ]
    },
    {
        "messages": [
            {"role": "client", "content": "我和老公冷战了三天了"},
            {"role": "counselor", "content": "冷战的感觉一定很难受"},
        ]
    },
]

MOCK_CPSDD_DATA = [
    {
        "dialog": [
            {"role": "seeker", "content": "工作压力太大了，我觉得自己快崩溃了"},
            {"role": "supporter", "content": "我能感受到你现在承受了很大的压力"},
        ]
    },
]

MOCK_AURADIAL_DATA = [
    {
        "messages": [
            {"role": "human", "content": "我最近心情很差"},
            {"role": "ai", "content": "能告诉我发生了什么吗？"},
        ]
    },
]


def _write_jsonl(path: Path, data: list[dict]):
    with open(path, 'w', encoding='utf-8') as f:
        for item in data:
            f.write(json.dumps(item, ensure_ascii=False) + '\n')


def _write_json(path: Path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 数据集适配器测试
# ---------------------------------------------------------------------------

class TestDatasetAdapters:
    """数据集适配器格式转换正确性"""

    def test_psyclient_adapter(self, tmp_path):
        f = tmp_path / "data.jsonl"
        _write_jsonl(f, MOCK_PSYCLIENT_DATA)

        samples = PsyCLIENTAdapter.load(str(tmp_path))
        assert len(samples) == 2
        assert samples[0]['source'] == 'PsyCLIENT-CP'
        assert 'ME:' in samples[0]['conversation']
        assert 'OTHER:' in samples[0]['conversation']

    def test_cpsdd_adapter(self, tmp_path):
        f = tmp_path / "data.jsonl"
        _write_jsonl(f, MOCK_CPSDD_DATA)

        samples = CPsDDAdapter.load(str(tmp_path))
        assert len(samples) == 1
        assert samples[0]['source'] == 'CPsDD'
        assert 'ME:' in samples[0]['conversation']

    def test_auradial_adapter(self, tmp_path):
        f = tmp_path / "data.jsonl"
        _write_jsonl(f, MOCK_AURADIAL_DATA)

        samples = AuraDialAdapter.load(str(tmp_path))
        assert len(samples) == 1
        assert samples[0]['source'] == 'AuraDial'
        assert 'ME:' in samples[0]['conversation']

    def test_psyclient_json_format(self, tmp_path):
        """JSON（非 JSONL）格式也能加载"""
        f = tmp_path / "data.json"
        _write_json(f, MOCK_PSYCLIENT_DATA)

        samples = PsyCLIENTAdapter.load(str(tmp_path))
        assert len(samples) == 2

    def test_empty_messages_skipped(self, tmp_path):
        f = tmp_path / "data.jsonl"
        _write_jsonl(f, [{"messages": []}])

        samples = PsyCLIENTAdapter.load(str(tmp_path))
        assert len(samples) == 0

    def test_adapter_registry(self):
        assert 'PsyCLIENT-CP' in DATASET_ADAPTERS
        assert 'CPsDD' in DATASET_ADAPTERS
        assert 'AuraDial' in DATASET_ADAPTERS


# ---------------------------------------------------------------------------
# DataAugmentor 基础功能
# ---------------------------------------------------------------------------

class TestDataAugmentorBasic:
    """DataAugmentor 基础功能测试"""

    def test_import_dataset(self, tmp_path):
        f = tmp_path / "data.jsonl"
        _write_jsonl(f, MOCK_PSYCLIENT_DATA)

        augmentor = DataAugmentor()
        count = augmentor.import_dataset('PsyCLIENT-CP', str(tmp_path))
        assert count == 2
        assert augmentor.get_stats().original_count == 2

    def test_import_unknown_dataset_raises(self):
        augmentor = DataAugmentor()
        with pytest.raises(ValueError, match="未知数据集"):
            augmentor.import_dataset('UnknownDataset', '/path')

    def test_import_jsonl(self, tmp_path):
        f = tmp_path / "data.jsonl"
        data = [
            {"conversation_text": "ME: hi\nOTHER: hello"},
            {"conversation_text": "ME: bye\nOTHER: see ya"},
        ]
        _write_jsonl(f, data)

        augmentor = DataAugmentor()
        count = augmentor.import_jsonl(str(f))
        assert count == 2

    def test_stats_initial(self):
        augmentor = DataAugmentor()
        stats = augmentor.get_stats()
        assert stats.original_count == 0
        assert stats.augmented_count == 0

    def test_multiple_imports_accumulate(self, tmp_path):
        f1 = tmp_path / "a.jsonl"
        f2 = tmp_path / "b.jsonl"
        _write_jsonl(f1, MOCK_PSYCLIENT_DATA)
        _write_jsonl(f2, MOCK_CPSDD_DATA)

        d1 = tmp_path / "dir1"
        d1.mkdir()
        (d1 / "data.jsonl").write_text(f1.read_text())

        d2 = tmp_path / "dir2"
        d2.mkdir()
        (d2 / "data.jsonl").write_text(f2.read_text())

        augmentor = DataAugmentor()
        augmentor.import_dataset('PsyCLIENT-CP', str(d1))
        augmentor.import_dataset('CPsDD', str(d2))
        assert augmentor.get_stats().original_count == 3


# ---------------------------------------------------------------------------
# 蒸馏测试（使用 mock LLM）
# ---------------------------------------------------------------------------

class TestDistillation:
    """蒸馏功能测试（mock LLM 调用）"""

    @staticmethod
    def _mock_llm(prompt: str, model_name: str) -> str:
        """Mock LLM 返回"""
        if 'logic' in model_name:
            return (
                "<think>用户因为伴侣加班太多感到被忽视，"
                "核心问题是沟通不足和期望不匹配</think>\n"
                "关系状态：冷淡期\n"
                "问题：沟通不足\n"
                "建议：增加日常交流"
            )
        else:
            return (
                "我能理解你的感受。当另一半经常加班回来很晚时，"
                "确实很容易让人觉得不被重视。\n"
                "建议你们找个轻松的时间好好聊聊，"
                "表达你的需要同时也听听对方的想法。"
            )

    def test_distill_with_mock(self, tmp_path):
        f = tmp_path / "data.jsonl"
        _write_jsonl(f, MOCK_PSYCLIENT_DATA)

        augmentor = DataAugmentor({
            'min_conversation_length': 10,
            'rate_limit_delay': 0,
        })
        augmentor.import_dataset('PsyCLIENT-CP', str(tmp_path))

        success = augmentor.distill(
            logic_teacher='mock_logic',
            style_teacher='mock_style',
            call_llm_fn=self._mock_llm,
        )
        assert success == 2
        assert augmentor.get_stats().augmented_count == 2

        samples = augmentor.get_samples()
        assert len(samples) == 2
        # 检查 thinking 被提取
        assert samples[0].thinking != ''
        assert '沟通不足' in samples[0].thinking or '被忽视' in samples[0].thinking
        # 检查 analysis 是风格教师的输出
        assert '理解你的感受' in samples[0].analysis

    def test_distill_preserves_source(self, tmp_path):
        f = tmp_path / "data.jsonl"
        _write_jsonl(f, MOCK_PSYCLIENT_DATA)

        augmentor = DataAugmentor({
            'min_conversation_length': 10,
            'rate_limit_delay': 0,
        })
        augmentor.import_dataset('PsyCLIENT-CP', str(tmp_path))
        augmentor.distill(
            logic_teacher='logic',
            style_teacher='style',
            call_llm_fn=self._mock_llm,
        )

        for sample in augmentor.get_samples():
            assert sample.source_dataset == 'PsyCLIENT-CP'
            assert sample.logic_teacher == 'logic'
            assert sample.style_teacher == 'style'

    def test_distill_empty_samples(self):
        augmentor = DataAugmentor()
        result = augmentor.distill(call_llm_fn=self._mock_llm)
        assert result == 0

    def test_distill_skips_short_conversations(self, tmp_path):
        f = tmp_path / "data.jsonl"
        _write_jsonl(f, [{"messages": [{"role": "client", "content": "hi"}]}])

        d = tmp_path / "dir"
        d.mkdir()
        (d / "data.jsonl").write_text(f.read_text())

        augmentor = DataAugmentor({
            'min_conversation_length': 100,  # 短于此的跳过
            'rate_limit_delay': 0,
        })
        augmentor.import_dataset('PsyCLIENT-CP', str(d))
        success = augmentor.distill(call_llm_fn=self._mock_llm)
        assert success == 0


# ---------------------------------------------------------------------------
# 质量过滤测试
# ---------------------------------------------------------------------------

class TestQualityFilter:
    """质量过滤正确性"""

    def test_high_quality_passes(self):
        augmentor = DataAugmentor()
        augmentor._augmented_samples = [
            AugmentedSample(
                conversation="ME: 最近和男朋友吵架了\nOTHER: 怎么回事",
                analysis="关系状态不太稳定，主要问题是沟通不够。建议增加日常交流，改善互动方式。需要双方共同努力。",
                thinking="用户因为沟通不足产生矛盾",
                source_dataset='test',
            ),
        ]
        remaining = augmentor.filter_quality()
        assert remaining == 1
        assert augmentor.get_samples()[0].quality_score > 0.5

    def test_low_quality_filtered(self):
        augmentor = DataAugmentor()
        augmentor._augmented_samples = [
            AugmentedSample(
                conversation="short",
                analysis="x",
                thinking="",
                source_dataset='test',
            ),
        ]
        remaining = augmentor.filter_quality()
        assert remaining == 0
        assert augmentor.get_stats().filtered_count == 1

    def test_filter_updates_stats(self):
        augmentor = DataAugmentor()
        augmentor._augmented_samples = [
            AugmentedSample(
                conversation="ME: 测试对话内容，长度需要超过最小值\nOTHER: 回复内容也需要有一定长度",
                analysis="这是一段关于关系问题的分析。建议双方增加沟通，改善相处方式。需要注意情绪管理。" * 3,
                thinking="分析推理过程",
                source_dataset='test',
            ),
            AugmentedSample(
                conversation="x",
                analysis="y",
                thinking="",
                source_dataset='test',
            ),
        ]
        augmentor.filter_quality()
        stats = augmentor.get_stats()
        assert stats.filtered_count >= 1
        assert 0 < stats.quality_pass_rate <= 1.0


# ---------------------------------------------------------------------------
# 输出格式测试
# ---------------------------------------------------------------------------

class TestOutputFormat:
    """输出 JSONL 格式正确性"""

    def test_save_jsonl_format(self, tmp_path):
        augmentor = DataAugmentor()
        augmentor._augmented_samples = [
            AugmentedSample(
                conversation="ME: 测试\nOTHER: 回复",
                analysis="这是分析结果",
                thinking="推理过程",
                source_dataset='PsyCLIENT-CP',
                logic_teacher='deepseek',
                style_teacher='claude',
                quality_score=0.8,
            ),
        ]

        output_path = str(tmp_path / "output.jsonl")
        augmentor.save(output_path)

        # 验证 JSONL 格式
        with open(output_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        assert len(lines) == 1
        record = json.loads(lines[0])

        # 验证必要字段
        assert 'messages' in record
        assert len(record['messages']) == 3
        assert record['messages'][0]['role'] == 'system'
        assert record['messages'][1]['role'] == 'user'
        assert record['messages'][2]['role'] == 'assistant'
        assert record['thinking'] == '推理过程'
        assert record['source_dataset'] == 'PsyCLIENT-CP'
        assert record['quality_score'] == 0.8

    def test_save_creates_directory(self, tmp_path):
        augmentor = DataAugmentor()
        augmentor._augmented_samples = [
            AugmentedSample(conversation="test", analysis="test"),
        ]
        output_path = str(tmp_path / "subdir" / "nested" / "output.jsonl")
        augmentor.save(output_path)
        assert Path(output_path).exists()
