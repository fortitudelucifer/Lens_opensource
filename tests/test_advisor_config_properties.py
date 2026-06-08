"""
test_advisor_config_properties.py
配置管理属性测试

**Property 10: 配置管理正确性**
**Validates: Requirements 7.2, 7.3**

For any 配置参数：
- 如果同时在配置文件和命令行中指定，命令行参数的值必须优先于配置文件的值
- 对于无效的配置文件（缺少必需字段或字段类型错误），系统必须拒绝加载并给出明确的错误信息

运行方式：
    conda activate wechatDHA
    python -m pytest tests/test_advisor_config_properties.py -v
"""

import argparse
import tempfile
from pathlib import Path

import pytest
import yaml
from hypothesis import given, settings, strategies as st, assume

from scripts.advisor.config import (
    AdvisorConfig,
    ExtractionConfig,
    TrainingConfig,
    InferenceConfig,
    load_config,
    merge_cli_args,
    validate_config,
    validate_config_file,
    _resolve_variables,
)


# =============================================================================
# Hypothesis 策略
# =============================================================================

# 合法的训练参数范围
valid_epochs = st.integers(min_value=1, max_value=100)
valid_batch_size = st.integers(min_value=1, max_value=64)
valid_learning_rate = st.floats(min_value=1e-7, max_value=1.0, allow_nan=False, allow_infinity=False)
valid_temperature = st.floats(min_value=0.0, max_value=2.0, allow_nan=False, allow_infinity=False)
valid_top_p = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)
valid_max_tokens = st.integers(min_value=1, max_value=8192)
valid_num_chunks = st.integers(min_value=1, max_value=10000)
valid_max_seq_length = st.integers(min_value=128, max_value=32768)

# 分段策略
valid_strategy = st.sampled_from(['event_based', 'sliding_window'])


@st.composite
def cli_args_strategy(draw):
    """生成随机的命令行参数（模拟 argparse.Namespace）"""
    args = argparse.Namespace()

    # 随机决定哪些参数被设置（非 None 表示命令行指定了）
    args.epochs = draw(st.one_of(st.none(), valid_epochs))
    args.batch_size = draw(st.one_of(st.none(), valid_batch_size))
    args.learning_rate = draw(st.one_of(st.none(), valid_learning_rate))
    args.temperature = draw(st.one_of(st.none(), valid_temperature))
    args.top_p = draw(st.one_of(st.none(), valid_top_p))
    args.max_tokens = draw(st.one_of(st.none(), valid_max_tokens))
    args.num = draw(st.one_of(st.none(), valid_num_chunks))
    args.strategy = draw(st.one_of(st.none(), valid_strategy))
    args.thinking = draw(st.one_of(st.none(), st.booleans()))
    args.max_seq_length = draw(st.one_of(st.none(), valid_max_seq_length))
    args.base_model = None  # 不随机生成路径

    return args


@st.composite
def yaml_config_strategy(draw):
    """生成随机的 YAML 配置字典"""
    config = {
        'extraction': {
            'num_chunks': draw(valid_num_chunks),
            'segmentation_strategy': draw(valid_strategy),
        },
        'training': {
            'base_model': '/data/models/Qwen3-8B-Instruct',
            'num_epochs': draw(valid_epochs),
            'batch_size': draw(valid_batch_size),
            'learning_rate': draw(valid_learning_rate),
            'max_seq_length': draw(valid_max_seq_length),
        },
        'inference': {
            'temperature': draw(valid_temperature),
            'top_p': draw(valid_top_p),
            'max_new_tokens': draw(valid_max_tokens),
            'thinking_mode': draw(st.booleans()),
        },
    }
    return config


# =============================================================================
# Property 10: 配置管理正确性
# =============================================================================

class TestProperty10ConfigManagement:
    """
    **Feature: relationship-advisor-agent, Property 10: 配置管理正确性**
    **Validates: Requirements 7.2, 7.3**
    """

    # -----------------------------------------------------------------
    # Property 10a: 命令行参数覆盖配置文件值
    # -----------------------------------------------------------------

    @settings(max_examples=100)
    @given(yaml_config=yaml_config_strategy(), cli_args=cli_args_strategy())
    def test_cli_args_override_config_values(self, yaml_config, cli_args):
        """
        **Feature: relationship-advisor-agent, Property 10: 配置管理正确性**
        **Validates: Requirements 7.2**

        对于任意配置文件值和命令行参数，当命令行参数非 None 时，
        合并后的配置必须使用命令行参数的值。
        """
        # 写入临时 YAML 配置
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(yaml_config, f)
            tmp_path = f.name

        try:
            # 加载配置（使用虚拟 workspace 避免路径验证）
            config = load_config(config_path=tmp_path, workspace='/tmp')

            # 记录合并前的值
            pre_merge = {
                'epochs': config.training.num_epochs,
                'batch_size': config.training.batch_size,
                'learning_rate': config.training.learning_rate,
                'temperature': config.inference.temperature,
                'top_p': config.inference.top_p,
                'max_tokens': config.inference.max_new_tokens,
                'num': config.extraction.num_chunks,
                'strategy': config.extraction.segmentation_strategy,
                'thinking': config.inference.thinking_mode,
                'max_seq_length': config.training.max_seq_length,
            }

            # 合并命令行参数
            config = merge_cli_args(config, cli_args)

            # 验证：非 None 的命令行参数必须覆盖配置文件值
            if cli_args.epochs is not None:
                assert config.training.num_epochs == cli_args.epochs
            else:
                assert config.training.num_epochs == pre_merge['epochs']

            if cli_args.batch_size is not None:
                assert config.training.batch_size == cli_args.batch_size
            else:
                assert config.training.batch_size == pre_merge['batch_size']

            if cli_args.learning_rate is not None:
                assert config.training.learning_rate == cli_args.learning_rate
            else:
                assert config.training.learning_rate == pre_merge['learning_rate']

            if cli_args.temperature is not None:
                assert config.inference.temperature == cli_args.temperature
            else:
                assert config.inference.temperature == pre_merge['temperature']

            if cli_args.top_p is not None:
                assert config.inference.top_p == cli_args.top_p
            else:
                assert config.inference.top_p == pre_merge['top_p']

            if cli_args.max_tokens is not None:
                assert config.inference.max_new_tokens == cli_args.max_tokens
            else:
                assert config.inference.max_new_tokens == pre_merge['max_tokens']

            if cli_args.num is not None:
                assert config.extraction.num_chunks == cli_args.num
            else:
                assert config.extraction.num_chunks == pre_merge['num']

            if cli_args.strategy is not None:
                assert config.extraction.segmentation_strategy == cli_args.strategy
            else:
                assert config.extraction.segmentation_strategy == pre_merge['strategy']

            if cli_args.thinking is not None:
                assert config.inference.thinking_mode == cli_args.thinking
            else:
                assert config.inference.thinking_mode == pre_merge['thinking']

            if cli_args.max_seq_length is not None:
                assert config.training.max_seq_length == cli_args.max_seq_length
            else:
                assert config.training.max_seq_length == pre_merge['max_seq_length']

        finally:
            Path(tmp_path).unlink(missing_ok=True)

    # -----------------------------------------------------------------
    # Property 10b: 无效配置拒绝加载并给出明确错误
    # -----------------------------------------------------------------

    @settings(max_examples=100)
    @given(
        missing_sections=st.lists(
            st.sampled_from(['extraction', 'training', 'inference']),
            min_size=1,
            max_size=3,
            unique=True,
        )
    )
    def test_missing_required_sections_detected(self, missing_sections):
        """
        **Feature: relationship-advisor-agent, Property 10: 配置管理正确性**
        **Validates: Requirements 7.3**

        对于缺少必需配置节的 YAML，validate_config_file 必须返回非空错误列表，
        且每个缺失的节都有对应的错误消息。
        """
        # 构建一个完整配置然后删除指定节
        raw = {
            'extraction': {'num_chunks': 100},
            'training': {'base_model': '/data/models/Qwen3-8B-Instruct'},
            'inference': {'temperature': 0.7},
        }
        for section in missing_sections:
            del raw[section]

        errors = validate_config_file(raw)

        # 必须检测到错误
        assert len(errors) > 0, f"缺少 {missing_sections} 但未检测到错误"

        # 每个缺失的节都应有对应错误
        for section in missing_sections:
            assert any(section in e for e in errors), \
                f"缺少 {section} 但错误消息中未提及"

    @settings(max_examples=100)
    @given(st.booleans())
    def test_missing_training_base_model_detected(self, has_other_fields):
        """
        **Feature: relationship-advisor-agent, Property 10: 配置管理正确性**
        **Validates: Requirements 7.3**

        training 节缺少 base_model 时必须报错。
        """
        raw = {
            'extraction': {'num_chunks': 100},
            'training': {},  # 缺少 base_model
            'inference': {'temperature': 0.7},
        }
        if has_other_fields:
            raw['training']['num_epochs'] = 5

        errors = validate_config_file(raw)
        assert any('base_model' in e for e in errors), \
            "training 缺少 base_model 但未检测到错误"

    # -----------------------------------------------------------------
    # Property 10c: 变量解析正确性
    # -----------------------------------------------------------------

    @settings(max_examples=100)
    @given(
        workspace=st.text(
            alphabet=st.characters(whitelist_categories=('L', 'N'), whitelist_characters='/_-'),
            min_size=1,
            max_size=50,
        ),
    )
    def test_variable_resolution(self, workspace):
        """
        **Feature: relationship-advisor-agent, Property 10: 配置管理正确性**
        **Validates: Requirements 7.1**

        ${workspace} 变量在所有字符串值中被正确替换。
        """
        assume(len(workspace.strip()) > 0)

        variables = {'workspace': workspace}
        test_cases = {
            'simple': '${workspace}/output',
            'nested_dict': {'path': '${workspace}/data', 'name': 'test'},
            'nested_list': ['${workspace}/a', '${workspace}/b'],
            'no_var': 'plain_string',
        }

        resolved = _resolve_variables(test_cases, variables)

        assert resolved['simple'] == f'{workspace}/output'
        assert resolved['nested_dict']['path'] == f'{workspace}/data'
        assert resolved['nested_dict']['name'] == 'test'
        assert resolved['nested_list'][0] == f'{workspace}/a'
        assert resolved['nested_list'][1] == f'{workspace}/b'
        assert resolved['no_var'] == 'plain_string'

    # -----------------------------------------------------------------
    # Property 10d: 配置验证参数范围
    # -----------------------------------------------------------------

    @settings(max_examples=100)
    @given(
        batch_size=st.integers(min_value=-10, max_value=0),
    )
    def test_invalid_training_params_detected(self, batch_size):
        """
        **Feature: relationship-advisor-agent, Property 10: 配置管理正确性**
        **Validates: Requirements 7.3**

        无效的训练参数（batch_size < 1）必须被 validate_config 检测到。
        """
        config = AdvisorConfig()
        config.training.batch_size = batch_size
        # 跳过路径检查（使用空 workspace）
        config.workspace = ''
        config.training.base_model = ''

        errors = validate_config(config)
        assert any('batch_size' in e for e in errors), \
            f"batch_size={batch_size} 应被检测为无效"

    @settings(max_examples=100)
    @given(
        temperature=st.floats(min_value=2.01, max_value=100.0, allow_nan=False, allow_infinity=False),
    )
    def test_invalid_inference_temperature_detected(self, temperature):
        """
        **Feature: relationship-advisor-agent, Property 10: 配置管理正确性**
        **Validates: Requirements 7.3**

        无效的推理温度（> 2.0）必须被 validate_config 检测到。
        """
        config = AdvisorConfig()
        config.inference.temperature = temperature
        config.workspace = ''
        config.training.base_model = ''

        errors = validate_config(config)
        assert any('temperature' in e for e in errors), \
            f"temperature={temperature} 应被检测为无效"
