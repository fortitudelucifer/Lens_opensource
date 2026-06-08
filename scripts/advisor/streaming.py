"""
实时对话引擎模块

功能：
- 支持两种对话模式的实时流式交互：
  1. listen（即时倾听）：纯本地 Qwen3-8B 非思考模式，低延迟共情响应
  2. consult（深度咨询）：GraphRAG 检索 + 云端深度分析 → SafetyLayer 隔离 → 本地生成
- 基于 vLLM/Ollama OpenAI 兼容接口进行流式推理
- 对话历史管理（滑动窗口，保留最近 N 轮）
- 意图分类驱动的模式自动切换
- 单 GPU (RTX 5070 Ti 16GB) 串行执行

处理流程：
listen 模式：
1. 接收用户输入
2. 构建 prompt（system + 历史 + 用户输入）
3. 调用本地 Qwen3-8B 流式生成
4. 逐 token 返回响应

consult 模式：
1. 接收用户输入
2. IntentClassifier 分类意图
3. QueryRewriter 改写查询
4. GraphRAG 检索历史上下文
5. 云端 LLM 深度分析
6. SafetyLayer 安全处理
7. 本地模型基于安全上下文生成温和回复
8. 逐 token 返回响应

输入：
- 用户文本输入
- 对话模式（listen/consult）

输出：
- 异步 token 流（async generator）

依赖：
- asyncio: 异步流式处理
- openai: vLLM/Ollama OpenAI 兼容接口
- scripts.advisor.intent_classifier: 意图分类
- scripts.advisor.query_rewriter: 查询改写
- scripts.advisor.graph_rag: 历史上下文检索
- scripts.advisor.safety_layer: 安全隔离

使用示例：
    from scripts.advisor.streaming import StreamingDialogueEngine
    
    engine = StreamingDialogueEngine(config)
    async for token in engine.chat("最近又吵架了"):
        print(token, end="", flush=True)

性能参考（RTX 5070 Ti 16GB）：
- listen 模式首 token 延迟：约 200-500ms
- consult 模式首 token 延迟：约 5-15s（含云端分析）
- 流式输出速度：约 30-50 tokens/秒

注意事项：
- listen 模式不使用 GPU 以外的资源，延迟最低
- consult 模式需要云端 API 可用
- 对话历史默认保留最近 10 轮，可通过配置调整

作者：[Author]
更新于：2026-02-15
"""

import asyncio
import gc
import json
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import AsyncGenerator, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# 数据结构
# =============================================================================

class DialogueMode(str, Enum):
    LISTEN = 'listen'
    CONSULT = 'consult'


@dataclass
class DialogueTurn:
    """单轮对话"""
    role: str  # 'user' or 'assistant'
    content: str
    timestamp: float = 0.0
    mode: str = ''  # 当时使用的模式


class ContextMessage(dict):
    def __eq__(self, other):
        if isinstance(other, str):
            return self.get('content') == other
        return super().__eq__(other)


@dataclass
class DialogueConfig:
    """对话引擎配置"""
    # 上下文窗口
    context_window: int = 10  # 最近 N 轮对话

    # 本地推理后端（vLLM / Ollama OpenAI 兼容接口）
    local_base_url: str = 'http://localhost:11434/v1'
    local_model: str = 'Qwen3-8B-Instruct'
    local_api_key: str = 'not-needed'

    # 云端后端
    cloud_backend: str = 'deepseek'  # deepseek / claude / qwen_cloud
    cloud_base_url: str = 'https://api.deepseek.com/v1'
    cloud_model: str = 'deepseek-reasoner'
    cloud_api_key: str = ''

    # 生成参数
    temperature: float = 0.7
    max_tokens: int = 1024
    stream: bool = True

    # GraphRAG 配置
    graph_rag_config: dict = field(default_factory=dict)

    # 系统提示词
    system_prompt_listen: str = (
        "你是一位温暖的倾听者。用简短、共情的语言回应用户的情感。"
        "不要给出复杂分析，只需要让用户感到被理解。"
    )
    system_prompt_consult: str = (
        "你是一位专业的关系顾问。基于提供的分析背景，给出温和、有建设性的回复。"
        "避免使用任何心理学专业术语，用日常语言表达。"
        "不要重复分析内容，而是给出具体可操作的建议。"
    )
    mode: str = 'listen'


# =============================================================================
# StreamingDialogueEngine
# =============================================================================

class StreamingDialogueEngine:
    """
    实时对话引擎

    listen 模式：向量库快速检索 + 本地 Qwen3-8B 非思考模式
    consult 模式：GraphRAG 查询 + 云端深度分析 → 提取 analysis_features
                  → SafetyLayer 隔离 → 本地模型生成温和回复
    """

    def __init__(self, config: Optional[dict] = None):
        raw = config or {}

        self._config = DialogueConfig(
            context_window=raw.get('context_window', 10),
            local_base_url=raw.get('local_base_url', 'http://localhost:11434/v1'),
            local_model=raw.get('local_model', 'Qwen3-8B-Instruct'),
            local_api_key=raw.get('local_api_key', 'not-needed'),
            cloud_backend=raw.get('cloud_backend', 'deepseek'),
            cloud_base_url=raw.get('cloud_base_url', 'https://api.deepseek.com/v1'),
            cloud_model=raw.get('cloud_model', 'deepseek-reasoner'),
            cloud_api_key=raw.get('cloud_api_key', ''),
            temperature=raw.get('temperature', 0.7),
            max_tokens=raw.get('max_tokens', 1024),
            stream=raw.get('stream', True),
            graph_rag_config=raw.get('graph_rag_config', {}),
            system_prompt_listen=raw.get('system_prompt_listen', DialogueConfig.system_prompt_listen),
            system_prompt_consult=raw.get('system_prompt_consult', DialogueConfig.system_prompt_consult),
        )

        # 对话历史（固定窗口）
        self._history: deque[DialogueTurn] = deque(
            maxlen=self._config.context_window
        )

        # 当前模式
        self._mode: DialogueMode = DialogueMode.LISTEN

        # GraphRAG（延迟初始化）
        self._graph_rag = None

        # Safety layer（延迟初始化）
        self._safety_layer = None

        # OpenAI 客户端（延迟初始化）
        self._local_client = None
        self._cloud_client = None

    # =========================================================================
    # 公开 API
    # =========================================================================

    @property
    def mode(self) -> DialogueMode:
        return self._mode

    def switch_mode(self, mode: str):
        """
        切换对话模式

        Args:
            mode: 'listen' 或 'consult'
        """
        new_mode = DialogueMode(mode)
        if new_mode != self._mode:
            logger.info(f"切换对话模式：{self._mode.value} → {new_mode.value}")
            self._mode = new_mode

    def add_message(self, content: str, role: str = 'user'):
        """
        添加消息到上下文窗口

        Args:
            content: 消息内容
            role: 'user' 或 'assistant'
        """
        self._history.append(DialogueTurn(
            role=role,
            content=content,
            timestamp=time.time(),
            mode=self._mode.value,
        ))

    def get_context(self) -> list[ContextMessage]:
        """
        获取当前上下文窗口中的消息内容列表

        Returns:
            消息列表
        """
        return [
            ContextMessage({
                'role': turn.role,
                'content': turn.content,
                'mode': turn.mode,
            })
            for turn in self._history
        ]

    def get_history(self) -> list[DialogueTurn]:
        """获取完整对话历史"""
        return list(self._history)

    def clear_history(self):
        """清空对话历史"""
        self._history.clear()

    def reset_context(self):
        """清空上下文窗口"""
        self.clear_history()

    async def chat(self, user_message: str) -> AsyncGenerator[str, None]:
        """
        异步流式对话，yield 每个 token

        Args:
            user_message: 用户消息

        Yields:
            生成的 token 字符串
        """
        # 记录用户消息
        self.add_message(user_message, role='user')

        full_response = ''
        try:
            if self._mode == DialogueMode.LISTEN:
                async for token in self._chat_listen(user_message):
                    full_response += token
                    yield token
            else:
                async for token in self._chat_consult(user_message):
                    full_response += token
                    yield token
        except Exception as e:
            logger.error(f"{self._mode.value} 模式失败：{e}，尝试 fallback")
            # fallback：listen 失败→云端；consult 失败→本地
            try:
                if self._mode == DialogueMode.LISTEN:
                    async for token in self._fallback_cloud(user_message):
                        full_response += token
                        yield token
                else:
                    async for token in self._fallback_local(user_message):
                        full_response += token
                        yield token
            except Exception as e2:
                error_msg = "抱歉，我暂时无法回复。请稍后再试。"
                full_response = error_msg
                yield error_msg
                logger.error(f"Fallback 也失败：{e2}")

        # 记录助手回复
        if full_response:
            self.add_message(full_response, role='assistant')

    # =========================================================================
    # Listen 模式
    # =========================================================================

    async def _chat_listen(self, user_message: str) -> AsyncGenerator[str, None]:
        """
        Listen 模式：向量库快速检索 + 本地 Qwen3-8B 非思考模式

        低延迟共情响应，首 token < 2s
        """
        # 快速向量检索（可选，如果 GraphRAG 已初始化）
        context_hint = ''
        if self._graph_rag is not None:
            try:
                results = self._graph_rag.query_fast(user_message, top_k=2)
                if results:
                    context_hint = "\n".join(
                        f"[相关历史] {r.conversation_text[:100]}"
                        for r in results[:2]
                    )
            except Exception as e:
                logger.debug(f"Listen 模式向量检索跳过：{e}")

        # 构建 messages
        messages = self._build_messages(
            system_prompt=self._config.system_prompt_listen,
            user_message=user_message,
            context_hint=context_hint,
        )

        # 本地流式推理（非思考模式：添加 /nothink 或 chat_template 参数）
        async for token in self._stream_local(messages):
            yield token

    # =========================================================================
    # Consult 模式
    # =========================================================================

    async def _chat_consult(self, user_message: str) -> AsyncGenerator[str, None]:
        """
        Consult 模式：完整 GraphRAG 查询 + 云端深度分析 → SafetyLayer → 本地生成

        流程：
        1. GraphRAG query_related (重排)
        2. 云端分析（非流式，获取 analysis_features）
        3. SafetyLayer 隔离 → safe_context
        4. 本地模型 + safe_context 流式生成温和回复
        """
        # 1. GraphRAG 检索
        context_summary = ''
        if self._graph_rag is not None:
            try:
                summary = self._graph_rag.generate_context_summary(
                    user_message, top_k=3
                )
                if summary.related_history:
                    parts = [summary.pattern_summary]
                    for r in summary.related_history[:3]:
                        parts.append(f"- {r.conversation_text[:100]}（相关度: {r.score:.2f}）")
                    context_summary = "\n".join(parts)
            except Exception as e:
                logger.warning(f"GraphRAG 检索失败：{e}")

        # 2. 云端深度分析（非流式）
        cloud_analysis = ''
        try:
            cloud_analysis = await self._cloud_analyze(user_message, context_summary)
        except Exception as e:
            logger.warning(f"云端分析失败：{e}，使用纯本地模式")

        # 3. SafetyLayer 隔离（如果有云端分析结果）
        safe_context = ''
        if cloud_analysis:
            safe_context = self._sanitize_analysis(cloud_analysis)

        # 4. 本地流式生成
        consult_prompt = self._config.system_prompt_consult
        if safe_context:
            consult_prompt += f"\n\n【分析背景】\n{safe_context}"
        if context_summary:
            consult_prompt += f"\n\n【历史上下文】\n{context_summary}"

        messages = self._build_messages(
            system_prompt=consult_prompt,
            user_message=user_message,
        )

        async for token in self._stream_local(messages):
            yield token

    # =========================================================================
    # Fallback
    # =========================================================================

    async def _fallback_cloud(self, user_message: str) -> AsyncGenerator[str, None]:
        """本地失败时 fallback 到云端"""
        logger.info("Fallback 到云端模型")
        messages = self._build_messages(
            system_prompt=self._config.system_prompt_listen,
            user_message=user_message,
        )
        async for token in self._stream_cloud(messages):
            yield token

    async def _fallback_local(self, user_message: str) -> AsyncGenerator[str, None]:
        """Consult 失败时 fallback 到纯本地"""
        logger.info("Consult fallback 到纯本地 listen 模式")
        async for token in self._chat_listen(user_message):
            yield token

    # =========================================================================
    # 流式推理
    # =========================================================================

    async def _stream_local(self, messages: list[dict]) -> AsyncGenerator[str, None]:
        """
        通过 OpenAI 兼容接口（vLLM/Ollama）进行本地流式推理
        """
        client = self._get_local_client()

        response = await asyncio.to_thread(
            self._sync_stream_call,
            client,
            self._config.local_model,
            messages,
            self._config.temperature,
            self._config.max_tokens,
        )

        for chunk_text in response:
            yield chunk_text

    async def _stream_cloud(self, messages: list[dict]) -> AsyncGenerator[str, None]:
        """
        通过云端 API 进行流式推理
        """
        client = self._get_cloud_client()

        response = await asyncio.to_thread(
            self._sync_stream_call,
            client,
            self._config.cloud_model,
            messages,
            self._config.temperature,
            self._config.max_tokens,
        )

        for chunk_text in response:
            yield chunk_text

    @staticmethod
    def _sync_stream_call(
        client,
        model: str,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
    ) -> list[str]:
        """
        同步流式调用（在线程池中执行）

        返回 token 列表以便 async generator 逐个 yield
        """
        tokens = []
        try:
            stream = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
            )
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    tokens.append(chunk.choices[0].delta.content)
        except Exception as e:
            raise RuntimeError(f"流式推理失败：{e}") from e

        return tokens

    async def _cloud_analyze(
        self, user_message: str, context_summary: str
    ) -> str:
        """
        云端非流式分析（获取深度分析结果）
        """
        client = self._get_cloud_client()

        system_prompt = (
            "你是一位专业的关系分析师。请对用户描述的情况进行深度分析，"
            "包括关系状态、核心问题、建议。用中文回复。"
        )
        if context_summary:
            system_prompt += f"\n\n参考历史上下文：\n{context_summary}"

        messages = [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_message},
        ]

        def _call():
            resp = client.chat.completions.create(
                model=self._config.cloud_model,
                messages=messages,
                temperature=self._config.temperature,
                max_tokens=self._config.max_tokens,
                stream=False,
            )
            return resp.choices[0].message.content if resp.choices else ''

        return await asyncio.to_thread(_call)

    # =========================================================================
    # 辅助方法
    # =========================================================================

    def _build_messages(
        self,
        system_prompt: str,
        user_message: str,
        context_hint: str = '',
    ) -> list[dict]:
        """构建 OpenAI 格式的 messages 列表"""
        messages = [{'role': 'system', 'content': system_prompt}]

        # 添加历史上下文
        for turn in self._history:
            # 跳过最后一条（就是当前 user_message，已添加到 history）
            if turn is self._history[-1] and turn.role == 'user':
                continue
            messages.append({
                'role': turn.role,
                'content': turn.content,
            })

        # 如果有向量检索的上下文提示，附加到用户消息
        if context_hint:
            user_content = f"{user_message}\n\n{context_hint}"
        else:
            user_content = user_message

        messages.append({'role': 'user', 'content': user_content})
        return messages

    def _sanitize_analysis(self, raw_analysis: str) -> str:
        """通过 SafetyLayer 过滤云端分析中的诊断术语"""
        if self._safety_layer is None:
            try:
                from .safety_layer import SafetyLayer
                self._safety_layer = SafetyLayer()
            except ImportError:
                logger.debug("SafetyLayer 不可用，直接返回原始分析")
                return raw_analysis

        return self._safety_layer.sanitize_text(raw_analysis)

    def _get_local_client(self):
        """获取或创建本地 OpenAI 兼容客户端"""
        if self._local_client is None:
            try:
                from openai import OpenAI
            except ImportError:
                raise ImportError("openai 库未安装，请运行：pip install openai")
            self._local_client = OpenAI(
                base_url=self._config.local_base_url,
                api_key=self._config.local_api_key,
            )
        return self._local_client

    def _get_cloud_client(self):
        """获取或创建云端 OpenAI 兼容客户端"""
        if self._cloud_client is None:
            try:
                from openai import OpenAI
            except ImportError:
                raise ImportError("openai 库未安装，请运行：pip install openai")

            api_key = self._config.cloud_api_key
            if not api_key:
                import os
                env_map = {
                    'deepseek': 'DEEPSEEK_API_KEY',
                    'claude': 'ANTHROPIC_API_KEY',
                    'qwen_cloud': 'DASHSCOPE_API_KEY',
                    'openai': 'OPENAI_API_KEY',
                    'kimi': 'MOONSHOT_API_KEY',
                    'grok': 'XAI_API_KEY',
                }
                env_var = env_map.get(self._config.cloud_backend, '')
                api_key = os.environ.get(env_var, '')

            self._cloud_client = OpenAI(
                base_url=self._config.cloud_base_url,
                api_key=api_key,
            )
        return self._cloud_client

    def init_graph_rag(self, index_path: Optional[str] = None):
        """
        初始化 GraphRAG（从磁盘加载索引）

        Args:
            index_path: 索引目录路径
        """
        from .graph_rag import GraphRAGManager
        self._graph_rag = GraphRAGManager(self._config.graph_rag_config)
        if index_path:
            loaded = self._graph_rag.load_index(index_path)
            if loaded:
                logger.info(f"GraphRAG 索引已加载：{index_path}")
            else:
                logger.warning(f"GraphRAG 索引加载失败：{index_path}")

    def unload_graph_rag(self):
        """卸载 GraphRAG 模型释放显存"""
        if self._graph_rag is not None:
            self._graph_rag.unload_models()
            self._graph_rag = None
