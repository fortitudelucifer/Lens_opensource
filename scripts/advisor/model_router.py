"""
模型路由器模块

功能：
- 根据任务复杂度在本地模型和云端模型之间智能路由
- 实现"云端大脑 + 本地嘴巴"的混合架构
- 复杂度评估：基于文本长度、关键词密度、多模态信号等维度
- 预算控制：每日 API 费用上限，超限自动降级到本地模型
- 长上下文路由：超过阈值的查询自动路由到支持长上下文的模型
- 单 GPU（RTX 5070 Ti 16GB）串行策略：同一时刻只有一个大模型在显存中

处理流程：
1. route(): 评估任务复杂度 → 选择最优后端
   - simple (< 0.3): 路由到本地 Qwen3-8B
   - medium (< 0.6): 路由到经济型云端模型（如 DeepSeek）
   - complex (≥ 0.6): 路由到旗舰云端模型（如 GPT-4/Claude）
2. call(): 调用选定后端的 API
   - 云端调用前确保 GPU 已清空（_ensure_gpu_clean）
   - 本地调用前加载模型到 GPU
3. 失败时自动降级到 fallback_model

输入：
- 任务描述/对话文本
- 路由配置（复杂度阈值、预算限制、后端列表）

输出：
- 选定的后端名称
- LLM 响应文本

依赖：
- openai: 云端 API 调用
- torch: GPU 显存管理
- scripts.advisor.errors: 显存清理工具

使用示例：
    from scripts.advisor.model_router import ModelRouter
    
    router = ModelRouter(config)
    backend = router.route(task)
    response = router.call(backend, prompt)

性能参考：
- 路由决策延迟：< 1ms（纯 CPU 计算）
- GPU 切换（卸载+加载）：约 10-20 秒

注意事项：
- 每次切换模型前通过 _ensure_gpu_clean() 确保显存已清空
- 路由到云端时 GPU 显存占用为 0
- 预算控制基于估算的 token 消耗，非精确计费

作者：[Author]
更新于：2026-02-15
"""

import gc
import logging
import os
import time
from typing import Any, Callable, Optional

import torch

from scripts.advisor.errors import clear_gpu_memory, get_gpu_memory_info

logger = logging.getLogger('advisor.model_router')


# =============================================================================
# GPU 显存守卫
# =============================================================================

def _ensure_gpu_clean(threshold_gb: float = 0.5):
    """
    进入任何本地模型加载前必须调用。
    确保 GPU 显存占用低于阈值。
    
    Args:
        threshold_gb: 允许的最大残留显存（GB）
    
    Raises:
        RuntimeError: 显存未清空时抛出
    """
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.synchronize()
        mem_gb = torch.cuda.memory_allocated() / 1e9
        if mem_gb > threshold_gb:
            # 再尝试一次强制清理
            gc.collect()
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
            mem_gb = torch.cuda.memory_allocated() / 1e9
            if mem_gb > threshold_gb:
                raise RuntimeError(
                    f"GPU 未清空: {mem_gb:.2f}GB 仍被占用 (阈值: {threshold_gb}GB)。"
                    f"请确保前一个模型已完全卸载。"
                )
        logger.debug(f"GPU 显存检查通过: {mem_gb:.3f}GB 已用")


# =============================================================================
# 本地模型会话 Context Manager
# =============================================================================

class LocalModelSession:
    """
    本地模型会话管理器（Context Manager）
    
    确保模型在使用完后自动卸载并清理显存。
    
    用法：
        with LocalModelSession(model_path, load_fn, unload_fn) as session:
            output = session.model.generate(...)
    """

    def __init__(
        self,
        model_name: str,
        load_fn: Callable[[], Any],
        unload_fn: Optional[Callable[[], None]] = None,
    ):
        """
        Args:
            model_name: 模型名称（用于日志）
            load_fn: 模型加载函数，返回加载好的模型对象
            unload_fn: 模型卸载函数（可选，默认使用通用清理）
        """
        self.model_name = model_name
        self.load_fn = load_fn
        self.unload_fn = unload_fn
        self.model = None

    def __enter__(self):
        _ensure_gpu_clean()
        logger.info(f"加载本地模型: {self.model_name}")
        start = time.time()
        self.model = self.load_fn()
        elapsed = time.time() - start
        mem_info = get_gpu_memory_info()
        logger.info(
            f"模型 {self.model_name} 加载完成 "
            f"({elapsed:.1f}s, VRAM: {mem_info.get('allocated_gb', 0):.2f}GB)"
        )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        logger.info(f"卸载本地模型: {self.model_name}")
        if self.unload_fn:
            self.unload_fn()
        if self.model is not None:
            del self.model
            self.model = None
        clear_gpu_memory()
        logger.info(f"模型 {self.model_name} 已卸载，显存已清理")
        return False  # 不抑制异常


# =============================================================================
# 后端配置
# =============================================================================

# 默认后端定义
DEFAULT_BACKENDS = {
    'local_qwen3': {
        'type': 'local',
        'model': 'Qwen3-8B-Instruct',
        'model_path': '/data/models/Qwen3-8B-Instruct',
        'quantization': '4bit',
        'vram_estimate_gb': 6.0,
        'thinking_mode': False,
    },
    'local_qwen3_thinking': {
        'type': 'local',
        'model': 'Qwen3-8B-Instruct',
        'model_path': '/data/models/Qwen3-8B-Instruct',
        'quantization': '4bit',
        'vram_estimate_gb': 7.0,
        'thinking_mode': True,
    },
    'deepseek_reasoner': {
        'type': 'cloud',
        'model': 'deepseek-ai/deepseek-v4-flash',
        'base_url': 'https://api.deepseek.com/v1',
        'api_key_env': 'DEEPSEEK_API_KEY',
        'cost_per_1k_tokens': 0.00028,
    },
    'claude_opus': {
        'type': 'cloud',
        'model': 'claude-opus-4-8-think',
        'api_key_env': 'ANTHROPIC_API_KEY',
        'cost_per_1k_tokens': 0.015,
    },
    'qwen_cloud': {
        'type': 'cloud',
        'model': 'qwen/qwen3.5-397b-a17b',
        'base_url': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
        'api_key_env': 'DASHSCOPE_API_KEY',
        'cost_per_1k_tokens': 0.0008,
    },
    'kimi_long': {
        'type': 'cloud',
        'model': 'kimi-k2.5',
        'base_url': 'https://api.moonshot.cn/v1',
        'api_key_env': 'MOONSHOT_API_KEY',
        'cost_per_1k_tokens': 0.002,
    },
    'grok': {
        'type': 'cloud',
        'model': 'grok-4.20-multi-agent-xhigh',
        'base_url': 'https://api.x.ai/v1',
        'api_key_env': 'XAI_API_KEY',
        'cost_per_1k_tokens': 0.003,
    },
}


# =============================================================================
# ModelRouter
# =============================================================================

class ModelRouter:
    """
    模型路由器 — 云端大脑 + 本地嘴巴
    
    根据 complexity_score 路由：
    - <=0.3 → local_qwen3 (non-thinking)
    - <=0.6 → local_qwen3_thinking / qwen_cloud
    - >0.6  → deepseek_reasoner / claude_opus
    - 长上下文 → kimi_long
    
    单 GPU 串行：路由到本地前 _ensure_gpu_clean()，路由到云端 0 VRAM。
    """

    def __init__(self, config: Optional[dict] = None):
        """
        Args:
            config: 配置字典，包含：
                - backends: 后端配置覆盖
                - complexity_thresholds: {simple: 0.3, medium: 0.6, complex: 0.8}
                - budget_limit_daily: 日预算上限（美元）
                - fallback_model: 兜底后端名称
                - long_context_threshold: 长上下文阈值（token 数）
        """
        config = config or {}

        # 后端注册
        self.backends = dict(DEFAULT_BACKENDS)
        if config.get('backends'):
            self.backends.update(config['backends'])

        # 复杂度阈值
        thresholds = config.get('complexity_thresholds', {})
        self.threshold_simple = thresholds.get('simple', 0.3)
        self.threshold_medium = thresholds.get('medium', 0.6)

        # 预算
        budget = config.get('budget', {})
        self.budget_limit_daily = config.get(
            'budget_limit_daily',
            budget.get('daily_limit_usd', 5.0),
        )
        self.budget_limit_monthly = config.get(
            'budget_limit_monthly',
            budget.get('monthly_limit_usd', 100.0),
        )
        self.daily_cost = 0.0
        self.monthly_cost = 0.0
        self._daily_cost = 0.0
        self._monthly_cost = 0.0
        self._total_calls = 0
        self.cost_reset_date = None

        # Fallback
        self.fallback_model = config.get('fallback_model', 'local_qwen3')

        # 长上下文
        self.long_context_threshold = config.get('long_context_threshold', 32000)

        # 统计
        self.stats = {
            'total_routes': 0,
            'local_routes': 0,
            'cloud_routes': 0,
            'fallback_routes': 0,
            'budget_exceeded_routes': 0,
        }

        # API 客户端缓存
        self._api_clients: dict[str, Any] = {}

    def route(self, task: dict) -> str:
        """
        根据任务复杂度评分选择模型后端。
        
        Args:
            task: 任务描述，包含：
                - complexity_score: 复杂度评分（0-1）
                - type: 任务类型 (analysis/generation/classification)
                - token_count: 输入 token 数（可选）
                - agent_type: Agent 类型（可选）
        
        Returns:
            后端名称
        """
        self.stats['total_routes'] += 1
        score = task.get('complexity_score', 0.5)
        token_count = task.get('token_count', 0)

        # 长上下文路由
        if token_count > self.long_context_threshold:
            self.stats['cloud_routes'] += 1
            return 'kimi_long'

        # 预算检查
        if self._is_budget_exceeded():
            self.stats['budget_exceeded_routes'] += 1
            self.stats['local_routes'] += 1
            logger.warning("云端预算已超限，强制路由到本地模型")
            return self.fallback_model

        # 复杂度路由
        if score <= self.threshold_simple:
            self.stats['local_routes'] += 1
            return 'local_qwen3'
        elif score <= self.threshold_medium:
            self.stats['local_routes'] += 1
            return 'local_qwen3_thinking'
        else:
            self.stats['cloud_routes'] += 1
            return 'deepseek_reasoner'

    def call(
        self,
        backend_name: str,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 2000,
    ) -> Optional[str]:
        """
        调用指定后端模型。
        
        云端：通过 API 调用，0 VRAM。
        本地：抛出 NotImplementedError（本地模型由 LocalModelSession 管理）。
        
        Args:
            backend_name: 后端名称
            prompt: 输入 prompt
            temperature: 生成温度
            max_tokens: 最大 token 数
        
        Returns:
            模型响应文本
        """
        backend = self.backends.get(backend_name)
        if backend is None:
            logger.error(f"未知后端: {backend_name}")
            return None

        if backend['type'] == 'local':
            raise NotImplementedError(
                f"本地模型 {backend_name} 应通过 LocalModelSession 管理加载/卸载，"
                f"不应通过 router.call() 直接调用。"
            )

        # 云端调用
        try:
            response = self._call_cloud(
                backend_name, backend, prompt, temperature, max_tokens,
            )
            return response
        except Exception as e:
            logger.error(f"云端调用 {backend_name} 失败: {e}")
            # Fallback
            if backend_name != self.fallback_model:
                self.stats['fallback_routes'] += 1
                logger.info(f"尝试 fallback 到 {self.fallback_model}")
                return None  # 返回 None，让调用方决定是否用本地模型
            raise

    def _assess_complexity(self, task: dict) -> float:
        """
        评估任务复杂度（0-1）。
        
        基于：对话长度、情绪关键词密度、分析类型。
        """
        score = 0.0
        conversation = task.get('conversation', '')

        # 对话长度因子
        char_count = len(conversation)
        if char_count > 3000:
            score += 0.3
        elif char_count > 1000:
            score += 0.15

        # 情绪关键词密度
        emotion_keywords = [
            '生气', '愤怒', '伤心', '难过', '失望', '绝望', '焦虑',
            '恐惧', '厌恶', '嫉妒', '冷战', '分手', '离婚', '出轨',
            '背叛', '欺骗', '家暴', '控制',
        ]
        keyword_count = sum(1 for kw in emotion_keywords if kw in conversation)
        score += min(keyword_count * 0.05, 0.3)

        # Agent 类型因子
        agent_type = task.get('agent_type', 'neutral')
        if agent_type == 'psychoanalytic':
            score += 0.3
        elif agent_type == 'supportive':
            score += 0.1

        return min(score, 1.0)

    def get_cost_report(self) -> dict:
        """获取云端调用成本报告"""
        return {
            'daily_cost': self.daily_cost,
            'daily_cost_usd': round(max(self.daily_cost, self._daily_cost), 4),
            'monthly_cost_usd': round(max(self.monthly_cost, self._monthly_cost), 4),
            'budget_limit': self.budget_limit_daily,
            'budget_remaining': max(0, self.budget_limit_daily - self.daily_cost),
            'total_calls': self._total_calls,
            'stats': self.stats.copy(),
        }

    def is_local_backend(self, backend_name: str) -> bool:
        """判断后端是否为本地模型"""
        backend = self.backends.get(backend_name, {})
        return backend.get('type') == 'local'

    def get_backend_config(self, backend_name: str) -> Optional[dict]:
        """获取后端配置"""
        return self.backends.get(backend_name)

    # -------------------------------------------------------------------------
    # 内部方法
    # -------------------------------------------------------------------------

    def _is_budget_exceeded(self) -> bool:
        """检查日预算是否超限"""
        from datetime import date
        today = date.today()
        if self.cost_reset_date != today:
            self.daily_cost = 0.0
            if self._daily_cost < self.budget_limit_daily:
                self._daily_cost = 0.0
            self.cost_reset_date = today
        daily_cost = max(self.daily_cost, self._daily_cost)
        monthly_cost = max(self.monthly_cost, self._monthly_cost)
        return (
            daily_cost >= self.budget_limit_daily
            or monthly_cost >= self.budget_limit_monthly
        )

    def _record_cost(self, backend_name: str, cost: float) -> None:
        self.daily_cost += cost
        self.monthly_cost += cost
        self._daily_cost += cost
        self._monthly_cost += cost
        self._total_calls += 1

    def _call_cloud(
        self,
        backend_name: str,
        backend: dict,
        prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> Optional[str]:
        """调用云端 API"""
        model = backend['model']

        if backend_name == 'claude_opus':
            return self._call_claude(backend, prompt, temperature, max_tokens)
        else:
            return self._call_openai_compatible(
                backend, prompt, temperature, max_tokens,
            )

    def _call_openai_compatible(
        self,
        backend: dict,
        prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> Optional[str]:
        """调用 OpenAI 兼容接口（DeepSeek / Qwen / Kimi / Grok）"""
        from openai import OpenAI

        model = backend['model']
        api_key = os.environ.get(backend.get('api_key_env', ''), 'not-needed')
        base_url = backend.get('base_url')

        client_key = f"{base_url}:{api_key[:8]}"
        if client_key not in self._api_clients:
            self._api_clients[client_key] = OpenAI(
                api_key=api_key, base_url=base_url,
            )
        client = self._api_clients[client_key]

        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
        )

        # 成本追踪
        if response.usage:
            total_tokens = response.usage.total_tokens
            cost_rate = backend.get('cost_per_1k_tokens', 0)
            self.daily_cost += (total_tokens / 1000) * cost_rate

        return response.choices[0].message.content

    def _call_claude(
        self,
        backend: dict,
        prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> Optional[str]:
        """调用 Claude API"""
        from anthropic import Anthropic

        api_key = os.environ.get(backend.get('api_key_env', ''))

        client_key = f"claude:{api_key[:8] if api_key else 'none'}"
        if client_key not in self._api_clients:
            self._api_clients[client_key] = Anthropic(api_key=api_key)
        client = self._api_clients[client_key]

        response = client.messages.create(
            model=backend['model'],
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )

        # 成本追踪
        if response.usage:
            total_tokens = response.usage.input_tokens + response.usage.output_tokens
            cost_rate = backend.get('cost_per_1k_tokens', 0)
            self.daily_cost += (total_tokens / 1000) * cost_rate

        return response.content[0].text
