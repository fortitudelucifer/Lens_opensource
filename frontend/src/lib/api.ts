const API_BASE = "/api"

// ── Generic fetch helper ──────────────────────────────────────
async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  })
  if (!res.ok) {
    const body = await res.text()
    throw new Error(`API ${res.status}: ${body}`)
  }
  return res.json()
}

// ── Types ─────────────────────────────────────────────────────
export interface ModelInfo {
  backend: string
  model: string
  base_url: string
  status: "connected" | "configured" | "offline"
  has_key: boolean
  suitable_for: string[]
}

export interface ModelPreferences {
  analysis_backend: string
  analysis_model: string
  review_backend: string
  review_model: string
  chat_backend: string
  chat_model: string
}

export interface AvailableModel {
  backend: string
  model: string
  base_url: string
  suitable_for: string[]
}

export interface ChatSession {
  id: string
  title: string
  agent_type: string
  mode: string
  backend: string
  message_count: number
  created_at: string
  updated_at: string
  /** 未开始 | 待回复 | 进行中 | 危机干预 */
  communication_status?: string
}

export interface ChatSessionSearchResult extends ChatSession {
  match_type: "title" | "fulltext" | "title+fulltext"
  matched_excerpt: string
  source?: "chat" | "sample" | "arena"
  communication_status?: string
  sample_file?: string
}

export interface ChatSessionSearchResponse {
  query: string
  total: number
  results: ChatSessionSearchResult[]
}

export interface ChatSessionDetail {
  id: string
  title: string
  agent_type: string
  mode: string
  backend: string
  messages: Array<{
    role: "user" | "assistant"
    content: string
    timestamp: string
    backend?: string
    model?: string
  }>
  created_at: string
  updated_at: string
  eft_stage?: string
  eft_round_count?: number
  bowen_third_parties?: string[]
  bowen_triangles_detected?: number
  [key: string]: unknown
}

export interface ModelTestResult {
  status: "ok" | "error"
  backend: string
  model: string
  base_url?: string
  response?: string
  error?: string
  latency_ms: number
}

export interface DataStats {
  l1_lines: number
  l2_lines: number
  test_lines: number
  chunks: number
  analyses: Record<string, number>
  reviews: Record<string, number>
}

export interface KnowledgeStatsFile {
  path: string
  entries: number
  approved_entries: number
  searchable_entries: number
  categories: Record<string, number>
  domains: Record<string, number>
}

export interface KnowledgeStats {
  total_entries: number
  approved_entries: number
  searchable_entries: number
  total_files: number
  active_files: number
  categories: Record<string, number>
  domains: Record<string, number>
  review_status: Record<string, number>
  risk_level: Record<string, number>
  files: KnowledgeStatsFile[]
  errors: Array<{ file: string; line: number; error: string }>
  generated_at: string
}

export interface PipelinePhase {
  name: string
  status: "idle" | "running" | "done" | "error"
  detail: string
}

export interface PipelineState {
  phases: Record<number, PipelinePhase>
  running_task: number | null
}

export interface ReviewItemSummary {
  id: string
  chunk_id: string
  agent_type: string
  ai_passed: boolean
  ai_score: number
  ai_summary: string
  human_decision: string | null
  conversation_preview: string
}

export interface ReviewListResponse {
  total: number
  items: ReviewItemSummary[]
  stats: {
    total: number
    ai_passed: number
    ai_failed: number
    human_approved: number
    human_rejected: number
    pending: number
  }
}

export interface ReviewItemDetail {
  id: string
  chunk_id: string
  conversation: string
  analysis_features: Record<string, unknown>
  agent_type: string
  review: {
    scores: Record<string, number>
    total_score: number
    passed: boolean
    issues: Array<{
      dimension: string
      severity: string
      description: string
      suggestion: string
    }>
    summary: string
  }
  human_decision: string | null
  human_notes?: string
  edited_analysis?: unknown
}

// ── API calls ─────────────────────────────────────────────────

export const api = {
  // Health
  health: () => apiFetch<{ status: string }>("/health"),

  // Models
  getModels: () => apiFetch<ModelInfo[]>("/models"),
  getReachable: () => apiFetch<Record<string, boolean>>("/models/reachable"),
  getAvailableModels: () => apiFetch<AvailableModel[]>("/models/available"),
  getModelPreferences: () => apiFetch<ModelPreferences>("/models/preferences"),
  setModelPreferences: (prefs: ModelPreferences) =>
    apiFetch<{ message: string; preferences: ModelPreferences }>("/models/preferences", {
      method: "POST",
      body: JSON.stringify(prefs),
    }),

  // Data stats
  getDataStats: () => apiFetch<DataStats>("/data/stats"),
  getKnowledgeStats: () => apiFetch<KnowledgeStats>("/knowledge/stats"),

  // Pipeline
  getPipelineStatus: () => apiFetch<PipelineState>("/pipeline/status"),

  runPipelinePhase: (phase: number, body: {
    input_type?: string
    backend?: string
    agent_type?: string
    limit?: number
    num_chunks?: number
  }) =>
    apiFetch<{ message: string; phase: number }>(`/pipeline/run/${phase}`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  // Chat (streaming) — yields content tokens + final { session_id } event
  chatStream: async function* (body: {
    message: string
    agent_type?: string
    mode?: string
    backend?: string
    session_id?: string
    use_rag?: boolean
    use_knowledge?: boolean
    edit_keep_user_turns?: number
  }) {
    const res = await fetch(`${API_BASE}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...body, stream: true }),
    })
    if (!res.ok) throw new Error(`Chat API ${res.status}`)
    const reader = res.body?.getReader()
    if (!reader) return
    const decoder = new TextDecoder()
    let buf = ""
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      const lines = buf.split("\n")
      buf = lines.pop() || ""
      for (const line of lines) {
        if (line.startsWith("data: ")) {
          const data = line.slice(6)
          if (data === "[DONE]") return
          let parsed: { content?: string; thinking?: string; thinking_done?: boolean; error?: string; error_code?: string; failed_backend?: string; available_backends?: string[]; session_id?: string }
          try {
            parsed = JSON.parse(data)
          } catch { continue }
          if (parsed.error) {
            const errPayload = JSON.stringify({ error: parsed.error, error_code: parsed.error_code, failed_backend: parsed.failed_backend, available_backends: parsed.available_backends })
            throw new Error(`__STRUCTURED__${errPayload}`)
          }
          if (parsed.session_id && !parsed.content) {
            yield `__SESSION_ID__${parsed.session_id}`
            continue
          }
          if (parsed.thinking_done) yield "__THINKING_DONE__"
          if (parsed.thinking) yield `__THINKING__${parsed.thinking}`
          if (parsed.content) yield parsed.content
        }
      }
    }
  },

  // Chat sessions
  listSessions: () => apiFetch<ChatSession[]>('/chat/sessions'),

  searchSessions: (query: string, limit = 20) =>
    apiFetch<ChatSessionSearchResponse>(
      `/chat/sessions/search?query=${encodeURIComponent(query)}&limit=${limit}`,
    ),

  getSession: (id: string) => apiFetch<ChatSessionDetail>(`/chat/sessions/${id}`),

  /** §4.6 监督评估：获取对话进展分析 */
  getSupervisionSession: (sessionId: string) =>
    apiFetch<{
      session_id: string
      supervision_log: Array<{
        round: number
        timestamp: string
        judge_backend: string
        analysis: Record<string, unknown>
      }>
      supervision_state: Record<string, unknown>
    }>(`/supervision/session/${sessionId}`),

  createSession: (agentType = "neutral", mode = "listen", backend = "grok") =>
    apiFetch<ChatSessionDetail>(`/chat/sessions?agent_type=${agentType}&mode=${mode}&backend=${backend}`, {
      method: "POST",
    }),

  deleteSession: (id: string) =>
    apiFetch<{ message: string }>(`/chat/sessions/${id}`, { method: "DELETE" }),

  renameSession: (id: string, title: string) =>
    apiFetch<{ message: string; title: string }>(`/chat/sessions/${id}`, {
      method: "PUT",
      body: JSON.stringify({ title }),
    }),

  // Model connectivity test
  testModel: (backend: string, model = "", prompt = "请用一句话回复：你好") =>
    apiFetch<ModelTestResult>("/models/test", {
      method: "POST",
      body: JSON.stringify({ backend, model, prompt }),
    }),

  // Review
  getReviewItems: (agentType = "neutral", filter = "all") =>
    apiFetch<ReviewListResponse>(`/review/items?agent_type=${agentType}&filter=${filter}`),

  getReviewItem: (id: string) =>
    apiFetch<ReviewItemDetail>(`/review/items/${id}`),

  submitReviewDecision: (id: string, body: {
    decision: "approve" | "reject" | "edit"
    edited_analysis?: string
    notes?: string
  }) =>
    apiFetch<{ message: string }>(`/review/items/${id}`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  // ── API Key Checker ──────────────────────────────────────────
  keysFetchModels: (baseUrl: string, apiKey: string) =>
    apiFetch<{ success: boolean; models: KeyCheckerModel[]; duration?: number; error?: string }>(
      "/keys/fetch-models",
      { method: "POST", body: JSON.stringify({ base_url: baseUrl, api_key: apiKey }) }
    ),

  keysCheck: (baseUrl: string, apiKey: string, model: string, detectionId = "") =>
    apiFetch<KeyCheckerResult>("/keys/check", {
      method: "POST",
      body: JSON.stringify({ base_url: baseUrl, api_key: apiKey, model, detection_id: detectionId }),
    }),

  keysBatchCheck: (baseUrl: string, apiKey: string, models: string[], detectionId = "") =>
    apiFetch<KeyCheckerBatchResult>("/keys/batch-check", {
      method: "POST",
      body: JSON.stringify({ base_url: baseUrl, api_key: apiKey, models, detection_id: detectionId }),
    }),

  keysStop: (detectionId: string) =>
    apiFetch<{ success: boolean; message?: string }>("/keys/stop", {
      method: "POST",
      body: JSON.stringify({ detection_id: detectionId }),
    }),

  // Arena 双镜对比（S3 — 多轮并行沉浸式互动）
  arenaChat: (body: {
    message: string
    arena_session_id?: string
    contestant_a?: { backend: string; agent_type?: string; model?: string }
    contestant_b?: { backend: string; agent_type?: string; model?: string }
    mode?: string
    use_rag?: boolean
    use_knowledge?: boolean
  }) =>
    apiFetch<{
      arena_session_id: string
      round_index: number
      response_a: string
      response_b: string
      crisis_level?: string
      requires_vote?: boolean
    }>("/arena/chat", { method: "POST", body: JSON.stringify(body) }),

  arenaVote: (body: {
    arena_session_id: string
    round_index?: number
    vote: string
    scores_a?: Record<string, number>
    scores_b?: Record<string, number>
    remark?: string
  }) =>
    apiFetch<{
      status: string
      message: string
      contestant_a: Record<string, string>
      contestant_b: Record<string, string>
    }>("/arena/vote", { method: "POST", body: JSON.stringify(body) }),

  arenaSession: (id: string) =>
    apiFetch<Record<string, unknown>>(`/arena/session/${id}`),

  renameArenaSession: (id: string, title: string) =>
    apiFetch<{ message: string; title: string }>(`/arena/sessions/${id}`, {
      method: "PUT",
      body: JSON.stringify({ title }),
    }),

  deleteArenaSession: (id: string) =>
    apiFetch<{ message: string }>(`/arena/sessions/${id}`, { method: "DELETE" }),

  arenaStats: () => apiFetch<{ updated_at?: string; total_battles?: number; ratings?: Record<string, unknown> }>("/arena/stats"),

  // Assessment
  getAssessmentQuestions: () => apiFetch<Record<string, unknown>>("/assessment/questions"),
  submitAssessment: (body: { answers: Record<string, number>; conflict_choice?: string; inject_enabled?: boolean }) =>
    apiFetch<AssessmentResult>("/assessment/submit", { method: "POST", body: JSON.stringify(body) }),
  toggleAssessmentInject: (inject_enabled: boolean) =>
    apiFetch<{ status: string; inject_enabled: boolean }>("/assessment/toggle-inject", { method: "POST", body: JSON.stringify({ inject_enabled }) }),
  getLatestAssessment: () => apiFetch<AssessmentResult & { exists: boolean }>("/assessment/latest"),

  // 全局 UI / Bug 反馈（FeedbackButton FAB）
  submitFeedback: (body: { content: string; page?: string; user_agent?: string }) =>
    apiFetch<{ status: string; message: string }>("/feedback", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  // 一键删除本地所有用户数据（GDPR / CCPA 合规）
  // 后端要求 confirm === "删除我的所有数据"，前端侧同样做二次确认
  eraseAllUserData: (confirm: string) =>
    apiFetch<{
      status: string
      total_items_removed: number
      total_bytes_removed: number
      details: Record<string, { items_removed: number; bytes_removed: number }>
      message: string
    }>("/user-data/all", {
      method: "DELETE",
      body: JSON.stringify({ confirm }),
    }),

  // ── Roundtable Discussion · 圆桌讨论（Day 3 backend）────────
  /** 创建 session（不立即触发 pipeline，等 SSE 订阅触发）
   *
   *  `backend` 为 Day 5 · E 新增：用户在 UI 下拉选定的 LLM backend
   *  （gemini/kimi/glm/...），留空时用服务器默认 chat_backend。
   */
  createRoundtableSession: (body: {
    personas: string[]
    question: string
    parent_id?: string
    backend?: string
    /** Day 7 · Setup 页 RAG 注入（聊天记录 + 知识手册预览后拼好的上下文） */
    inject_context?: string | null
    /** Day 7 · 深度模式：每 agent 500-900 字的深入分析（否则 150-300 字） */
    deep_mode?: boolean
  }) =>
    apiFetch<{ session_id: string; status: "created"; created_at: string }>(
      "/roundtable/sessions",
      { method: "POST", body: JSON.stringify(body) },
    ),

  /** 中断 pipeline 任务（DAG 分叉前置） */
  interruptRoundtableSession: (sessionId: string) =>
    apiFetch<{ session_id: string; interrupted: boolean; interrupted_at: string }>(
      `/roundtable/sessions/${encodeURIComponent(sessionId)}/interrupt`,
      { method: "POST" },
    ),

  /** Day 6 · 形态 A · 在已 done 的 session 上追问新问题（多轮对话）
   *
   *  `inject_context` · Step 4 · RAG 注入字符串（预览选择后前端拼好发送）
   */
  continueRoundtableSession: (
    sessionId: string,
    body: {
      question: string
      inject_context?: string | null
      /** Day 7 · 深度模式切换 · null/undefined → 沿用上一轮；true/false → 本轮独立切换 */
      deep_mode?: boolean | null
    },
  ) =>
    apiFetch<{ session_id: string; round_index: number; status: "continued"; started_at: string }>(
      `/roundtable/sessions/${encodeURIComponent(sessionId)}/continue`,
      { method: "POST", body: JSON.stringify(body) },
    ),

  /** Day 6 · Step 4 · RAG 注入预览（聊天记录 + 知识手册） */
  previewRoundtableInjection: (body: {
    query: string
    modes?: Array<"chat_history" | "knowledge">
    top_k?: number
  }) =>
    apiFetch<RoundtableInjectPreview>("/roundtable/inject/preview", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  /** Day 6 · 列出历史 session 摘要（按 updated_at 倒序，用于 RoundtablePage 顶部历史入口） */
  listRoundtableSessions: () =>
    apiFetch<Array<RoundtableSessionSummary>>("/roundtable/sessions"),

  /** Day 6 · 获取 session 完整快照（含 rounds[]，用于刷新后恢复历史 UI） */
  getRoundtableSession: (sessionId: string) =>
    apiFetch<RoundtableSessionDetail>(
      `/roundtable/sessions/${encodeURIComponent(sessionId)}`,
    ),
}

// ── Roundtable · Day 6 多轮对话形态 A 类型 ─────────────────────
export interface RoundtableSessionSummary {
  id: string
  phase: "setup" | "phase1" | "phase2" | "phase3" | "done"
  personas: string[]
  question: string
  question_excerpt: string
  backend: string | null
  round_index: number
  rounds_count: number
  created_at: string
  updated_at: string
}

export interface RoundtableAgentBufferDTO {
  persona_id: string
  status: "pending" | "typing" | "streaming" | "done" | "error"
  text: string
  confidence: number | null
  error: string | null
}

export interface RoundtableModeratorContentDTO {
  seen: string
  angles: string[]
  tries: string[]
  doubts: string[]
  lens: string
  limit: string
}

export interface RoundtableRoundSnapshotDTO {
  round_index: number
  question: string
  phase1: RoundtableAgentBufferDTO[]
  phase2: RoundtableAgentBufferDTO[]
  moderator: RoundtableModeratorContentDTO | null
  moderator_thinking: string
  created_at: string
  completed_at: string
}

export interface RoundtableSessionDetail {
  id: string
  parent_id: string | null
  personas: string[]
  question: string
  backend: string | null
  phase: "setup" | "phase1" | "phase2" | "phase3" | "done"
  phase1: RoundtableAgentBufferDTO[]
  phase2: RoundtableAgentBufferDTO[]
  moderator: RoundtableModeratorContentDTO | null
  moderator_thinking: string
  rounds: RoundtableRoundSnapshotDTO[]
  round_index: number
  current_inject_context?: string
  created_at: string
  updated_at: string
}

// ── Day 6 · Step 4 · RAG 注入预览 ─────────────────────────────
export interface RoundtableChatHistoryHit {
  chunk_id: string
  preview: string
  days: number[]
  chunk_type: string
  analysis_summary: string
  score: number
}

export interface RoundtableKnowledgeHit {
  category: string
  question: string
  answer: string
  keywords: string[]
  score: number
}

export interface RoundtableInjectPreview {
  chat_history: RoundtableChatHistoryHit[]
  knowledge: RoundtableKnowledgeHit[]
  suggested_context: string
}

export interface AssessmentResult {
  id: string
  timestamp: string
  inject_enabled: boolean
  phq2: { total: number; level: string; label: string; suggestion: string }
  gad2: { total: number; level: string; label: string; suggestion: string }
  attachment: { dominant: string; label: string; scores: Record<string, number>; description: string }
  conflict: { mode: string; label: string; description: string }
  context_injection: string
}

// ── API Key Checker Types ─────────────────────────────────────
export interface KeyCheckerModel {
  id: string
}

export interface KeyCheckerResult {
  success: boolean
  latency?: number
  model?: string
  usage?: Record<string, number>
  error?: string
  status?: number
  details?: unknown
}

export interface KeyCheckerBatchResult {
  results: Record<string, KeyCheckerResult>
  tested: number
  total: number
}

export type { ModelTestResult as ModelTestResultType }
