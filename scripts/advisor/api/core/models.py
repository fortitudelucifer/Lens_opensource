"""所有 Pydantic 数据模型（从 server.py 提取）"""

from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field


class ModelPreferences(BaseModel):
    analysis_backend: str = "qwen_cloud"
    analysis_model: str = ""
    review_backend: str = "grok"
    review_model: str = ""
    chat_backend: str = "grok"
    chat_model: str = ""


class SessionRenameRequest(BaseModel):
    title: str


class ChatRequest(BaseModel):
    message: str
    agent_type: str = "neutral"
    mode: str = "listen"
    backend: str = "grok"
    stream: bool = True
    session_id: Optional[str] = None
    use_rag: bool = True
    use_knowledge: bool = True
    # 编辑重发：仅保留会话里前 N 轮用户消息（连同其回复），其余截断后再处理本次消息。
    # None = 普通发送，不截断。
    edit_keep_user_turns: Optional[int] = None


class ChatFeedback(BaseModel):
    session_id: str
    message_index: int = -1
    rating: int
    comment: str = ""


class ModelTestRequest(BaseModel):
    backend: str
    model: str = ""
    prompt: str = "请用一句话回复：你好"


class PipelineRunRequest(BaseModel):
    input_type: str = "l2"
    input_file: Optional[str] = None
    backend: str = "claude"
    agent_type: str = "neutral"
    limit: Optional[int] = None
    num_chunks: int = 20
    fusion_mode: bool = True


class ReviewDecision(BaseModel):
    decision: str
    edited_analysis: Optional[str] = None
    notes: Optional[str] = None


class ArenaContestant(BaseModel):
    backend: str = "grok"
    agent_type: str = "neutral"
    model: str = ""


class ArenaScoresSchema(BaseModel):
    empathy: int = 5
    depth: int = 5
    practicality: int = 5
    professionalism: int = 5
    fluency: int = 5


class ArenaBattleRequest(BaseModel):
    query: str
    contestant_a: ArenaContestant
    contestant_b: ArenaContestant
    mode: str = "model"
    use_rag: bool = True


class ArenaChatRequest(BaseModel):
    message: str
    arena_session_id: Optional[str] = None
    contestant_a: ArenaContestant = ArenaContestant()
    contestant_b: ArenaContestant = ArenaContestant()
    mode: str = "model"
    use_rag: bool = True
    use_knowledge: bool = True


class ArenaVoteRequest(BaseModel):
    arena_session_id: str
    round_index: int = -1
    vote: str
    scores_a: Optional[ArenaScoresSchema] = None
    scores_b: Optional[ArenaScoresSchema] = None
    remark: Optional[str] = None


class RAGSearchRequest(BaseModel):
    query: str = ""
    day: Optional[int] = None
    day_range: Optional[str] = None
    chunk_type: Optional[str] = None
    top_k: int = 5


class KeyCheckerFetchRequest(BaseModel):
    base_url: str
    api_key: str


class KeyCheckerCheckRequest(BaseModel):
    base_url: str
    api_key: str
    model: str
    detection_id: str = ""


class KeyCheckerStopRequest(BaseModel):
    detection_id: str


class KeyCheckerBatchRequest(BaseModel):
    base_url: str
    api_key: str
    models: list[str]
    detection_id: str = ""


class AssessmentSubmission(BaseModel):
    answers: dict
    conflict_choice: Optional[str] = None
    inject_enabled: bool = False


class AssessmentToggleInject(BaseModel):
    inject_enabled: bool


class UIFeedback(BaseModel):
    """全局 UI / Bug 反馈（来自 FeedbackButton FAB）"""
    content: str
    page: str = ""
    user_agent: str = ""


class EraseUserDataRequest(BaseModel):
    """一键删除用户数据请求 — 二次确认短语必须精确匹配。"""
    confirm: str


class EraseUserDataResponse(BaseModel):
    """一键删除用户数据返回 — 含删除计数与分项明细。"""
    status: str
    total_items_removed: int
    total_bytes_removed: int
    details: dict  # { "chat_sessions": {"items_removed": N, "bytes_removed": B}, ... }
    message: str


# ═══════════════════════════════════════════════════════════════════
# Roundtable Discussion · 圆桌讨论（执行方案 §2 + Day 3 D3.1）
#
# 设计要点：
#   - **schema 与 frontend/src/hooks/useRoundtableStream.ts 严格一致**
#     （SSE event JSON 由 backend 生成，前端 dispatchRoundtableEvent 直接消费）
#   - persona_id 用 Lens 9 派别命名（neutral/supportive/psychoanalytic/eft/
#     bowen/sociology/philosophy/game_theory/cultural）
#   - phase 用 'phase1' / 'phase2'（与前端 store 的 PhaseAgentMessage 路径一致）
#   - parent_id 支持 DAG 分叉（USER_INTERRUPT → child session）
# ═══════════════════════════════════════════════════════════════════

# ── 9 个 persona 的字面量类型（与前端 PersonaId 严格一致）──
RoundtablePersonaId = Literal[
    "neutral", "supportive", "psychoanalytic", "eft", "bowen",
    "sociology", "philosophy", "game_theory", "cultural",
]

# ── Phase 字面量类型 ──
RoundtablePhase = Literal["setup", "phase1", "phase2", "phase3", "done"]
RoundtableAgentPhase = Literal["phase1", "phase2"]
RoundtableAgentStatus = Literal["pending", "typing", "streaming", "done", "error"]


class RoundtableStartRequest(BaseModel):
    """POST /api/roundtable/sessions 请求体"""
    personas: list[RoundtablePersonaId] = Field(
        ..., min_length=3, max_length=3,
        description="选中的 3 个 persona id（必须 3 个）",
    )
    question: str = Field(..., min_length=4, max_length=2000)
    parent_id: Optional[str] = Field(
        None,
        description="DAG 分叉：若 USER_INTERRUPT 触发 child session，传入 parent session id",
    )
    backend: Optional[str] = Field(
        None,
        description="Day 5 · E · 用户选定的 LLM backend（gemini/kimi/glm/...），None → 用服务器默认",
    )
    # Day 7 · D7.3 · 首轮也支持 RAG 注入（Setup 页选好后随 create 请求下发）
    inject_context: Optional[str] = Field(
        None,
        max_length=12000,
        description="前端在 Setup 页预览后拼好的 RAG 注入上下文字符串，后端原样注入首轮 phase1/phase2 prompt。"
                    "为空则不注入。超过 12000 字符会被后端截断。与 continue 端点同名同语义。",
    )
    # Day 7 · 深度模式：提高 max_tokens + 切换到「深度 prompt」模板（500-900 字）
    deep_mode: bool = Field(
        False,
        description="Day 7 · 深度模式：每 agent 生成 500-900 字的深入分析（否则 150-300 字简短回应）。"
                    "建议配合思考模型（claude-*-think / qwen-thinking）使用。",
    )


class RoundtableStartResponse(BaseModel):
    """POST /api/roundtable/sessions 响应"""
    session_id: str
    status: Literal["created"] = "created"
    created_at: str  # ISO 8601


class RoundtableModeratorContent(BaseModel):
    """6 段 Moderator 综合总结 — 与前端 ModeratorContent 严格一致"""
    seen: str
    angles: list[str]
    tries: list[str]
    doubts: list[str]
    lens: str
    limit: str


class RoundtableAgentBuffer(BaseModel):
    """单 agent 单 phase 的累积缓冲（用于 session 内部存储 + interrupt 恢复）"""
    persona_id: RoundtablePersonaId
    status: RoundtableAgentStatus = "pending"
    text: str = ""
    confidence: Optional[float] = None
    error: Optional[str] = None


# ═══════════════════════════════════════════════════════════════════
# Day 6 · 多轮对话形态 A · 单轮完整快照（存入 session.rounds[]）
# ═══════════════════════════════════════════════════════════════════

class RoundtableRoundSnapshot(BaseModel):
    """已完成一轮的快照（归档到 session.rounds[] 供历史展示 + 下一轮 context 注入）

    说明：
      - 首轮 round_index = 0；每次 continue 归档当前轮后自增
      - phase1/phase2 是**深拷贝**，不和 session 的当前轮共享引用
      - moderator_thinking 保留 LLM Moderator 的自然语言段（可能为空字符串）
    """
    round_index: int
    question: str
    phase1: list[RoundtableAgentBuffer] = []
    phase2: list[RoundtableAgentBuffer] = []
    moderator: Optional[RoundtableModeratorContent] = None
    moderator_thinking: str = ""
    created_at: datetime
    completed_at: datetime


class RoundtableContinueRequest(BaseModel):
    """POST /api/roundtable/sessions/{id}/continue 请求体（Day 6 形态 A · 追问）"""
    question: str = Field(..., min_length=4, max_length=2000)
    # Day 6 · Step 4 · RAG 注入
    inject_context: Optional[str] = Field(
        None,
        max_length=12000,
        description="前端预览后拼好的 RAG 注入上下文字符串，后端原样注入下一轮 phase1/phase2 prompt。"
                    "为空则不注入。超过 12000 字符会被后端截断。",
    )
    # Day 7 · 深度模式（同 Start 请求）· 可在每轮独立切换
    deep_mode: Optional[bool] = Field(
        None,
        description="Day 7 · 深度模式。None → 沿用上一轮设置；True/False → 本轮独立切换。",
    )


class RoundtableContinueResponse(BaseModel):
    session_id: str
    round_index: int  # 新一轮的 0-based index
    status: Literal["continued"] = "continued"
    started_at: str  # ISO 8601


# ═══════════════════════════════════════════════════════════════════
# Day 6 · Step 4 · RAG 预览（聊天记录 + 知识手册）
# ═══════════════════════════════════════════════════════════════════

class RoundtableInjectPreviewRequest(BaseModel):
    """POST /api/roundtable/inject/preview 请求体"""
    query: str = Field(..., min_length=2, max_length=2000)
    modes: list[Literal["chat_history", "knowledge"]] = Field(
        default_factory=lambda: ["chat_history", "knowledge"],
        description="选择哪些检索源。默认两者都查。",
    )
    top_k: int = Field(5, ge=1, le=20)


class RoundtableChatHistoryHit(BaseModel):
    """单条命中的聊天记录片段（用于前端预览 + 选择）"""
    chunk_id: str
    preview: str  # 片段文本预览（300-600 字）
    days: list[int] = []  # 命中的 day 列表
    chunk_type: str = "normal"  # conflict / sweet / normal
    analysis_summary: str = ""  # enriched analysis summary
    score: float = 0.0


class RoundtableKnowledgeHit(BaseModel):
    """单条命中的知识手册条目"""
    category: str = ""
    question: str = ""
    answer: str = ""
    keywords: list[str] = []
    score: float = 0.0


class RoundtableInjectPreviewResponse(BaseModel):
    chat_history: list[RoundtableChatHistoryHit] = []
    knowledge: list[RoundtableKnowledgeHit] = []
    # 可直接用于 inject_context 字段的拼好字符串（前端也可以自己拼）
    suggested_context: str = ""


class RoundtableSession(BaseModel):
    """圆桌讨论 session 状态（落盘 + 内存共享）"""
    id: str
    parent_id: Optional[str] = None  # DAG 分叉支持
    personas: list[RoundtablePersonaId]
    question: str
    # Day 5 · E · 可在 UI 选 backend（None → 用 _get_default_backend() 的 env/prefs/fallback）
    backend: Optional[str] = None
    phase: RoundtablePhase = "setup"
    phase1: list[RoundtableAgentBuffer] = []
    phase2: list[RoundtableAgentBuffer] = []
    moderator: Optional[RoundtableModeratorContent] = None
    # Day 5 · C · LLM Moderator 自然语言综合段（非 JSON 段），用于前端流式展示后折叠
    moderator_thinking: str = ""
    # Day 6 · 多轮形态 A · 已归档的历史轮快照（当前进行中的轮仍在 question/phase1/phase2/moderator 字段）
    rounds: list[RoundtableRoundSnapshot] = []
    round_index: int = 0  # 当前轮 0-based index（首轮 = 0）
    # Day 6 · Step 4 · 本轮用户预览后选定的 RAG 注入文本（随 continue 请求下发）
    current_inject_context: str = ""
    # Day 7 · 深度模式（首轮由 StartRequest 设定，后续 continue 可覆盖）
    deep_mode: bool = False
    # Day 7 · Moderator LLM 失败降级原因（None=LLM 成功或未执行；其余值代表降级到规则模板）
    # 值域参考：'llm_returned_none' / 'llm_disabled' / 'exception:XxxError'
    # 前端据此展示"无记忆降级"提示卡，让用户知晓本轮 Moderator 没走 LLM 路径。
    moderator_fallback_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    # 不在 schema 暴露：asyncio.Queue / Task 等运行时对象由 service 层管理
