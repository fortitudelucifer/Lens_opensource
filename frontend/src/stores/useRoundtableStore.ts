/**
 * 圆桌讨论 Zustand store
 *
 * 覆盖两个页面的共享状态：
 * - `RoundtablePage`（setup）— 选 persona + 输入问题
 * - `RoundtableSessionPage`（session）— 3-phase 流式讨论
 *
 * Store 设计对齐执行方案 § 2A 图 3（SSE 多路复用）+ 图 4（DAG 状态机）。
 */

import { create } from 'zustand'
import type { PersonaId } from '@/data/personas'

export type Phase = 'setup' | 'phase1' | 'phase2' | 'phase3' | 'done' | 'error'
export type AgentStatus = 'pending' | 'typing' | 'streaming' | 'done' | 'error'

export interface AgentMessageData {
  personaId: PersonaId
  status: AgentStatus
  text: string
  confidence?: number
  error?: string
}

export interface ModeratorContent {
  /** 【看到你】 */
  seen: string
  /** 【不同视角】 */
  angles: string[]
  /** 【你可以尝试】 */
  tries: string[]
  /** 【仍然存疑】 */
  doubts: string[]
  /** 【Lens 寄语】 */
  lens: string
  /** 【局限声明】 */
  limit: string
}

export type CrisisLevel = 'yellow' | 'orange' | 'red'

export interface CrisisEvent {
  level: CrisisLevel
  message: string
}

/** Day 6 · 形态 A · 已完成一轮的快照（与 backend RoundtableRoundSnapshot 对齐） */
export interface RoundSnapshot {
  roundIndex: number
  question: string
  phase1: AgentMessageData[]
  phase2: AgentMessageData[]
  moderator: ModeratorContent | null
  moderatorThinking: string
  createdAt: string
  completedAt: string
}

interface RoundtableState {
  // ── setup ──
  selectedPersonas: PersonaId[]
  question: string
  /** Day 7 · 深度模式（Setup 页 + FollowUpComposer 共享）· 首轮 create 时下发给后端 */
  deepMode: boolean

  // ── session ──
  sessionId: string | null
  currentPhase: Phase
  phase1Agents: AgentMessageData[]
  phase2Agents: AgentMessageData[]
  moderator: ModeratorContent | null
  /** Moderator LLM 的「综合思考」段（Day 5 方案① · 流式展示再折叠）· 规则 fallback 时为空 */
  moderatorThinking: string | null
  /**
   * Day 7 · Moderator LLM 失败降级原因（null = LLM 成功或未执行；其余值代表本轮走了规则模板）
   * 值域：'llm_returned_none' | 'llm_disabled' | 'exception:XxxError' | null
   * 前端据此在 ModeratorCard 上方显示"降级/无记忆"提示条。
   */
  moderatorFallbackReason: string | null
  /**
   * Day 7 · D7.1.f · 只读快照模式
   * - true：用户从 SessionHistoryList 打开了一个 `phase != 'done'` 的历史会话（backend 可能已崩溃 / orphan / 还在跑但当前进程无法继续）
   * - 此标志关闭 SSE 订阅（避免挂空连接）+ 前端渲染醒目 banner 解释"此会话未完成，重新开一局即可"
   * - 正常新 session / continue 新一轮 / done 会话 hydrate 都应为 false
   */
  isReadOnlySnapshot: boolean
  crisis: CrisisEvent | null
  error: string | null

  // ── Day 6 · 多轮对话形态 A ──
  /** 已归档的历史轮快照（当前进行中的轮仍在 phase1Agents/phase2Agents/moderator 字段上） */
  rounds: RoundSnapshot[]
  /** 当前轮 0-based index（首轮 = 0），continue 后 +1 */
  roundIndex: number
  /** SSE stream 重建触发器：每次 continue 后 +1 · hook 依赖此值重建 EventSource */
  streamNonce: number

  // ── setup actions ──
  togglePersona: (id: PersonaId) => void
  setPersonas: (ids: PersonaId[]) => void
  setQuestion: (q: string) => void
  setDeepMode: (v: boolean) => void
  resetSetup: () => void

  // ── session lifecycle ──
  startSession: (sessionId: string) => void
  advancePhase: (phase: Phase) => void
  resetSession: () => void

  // ── Day 6 · 多轮 actions ──
  /** 把当前轮归档到 rounds[] 并重置当前轮字段（给新一轮留空白）· 同时 bump streamNonce */
  archiveCurrentRoundAndReset: (nextQuestion: string) => void
  /** 用 backend 返回的 session detail 恢复全部状态（含 rounds / 当前轮 / streamNonce）*/
  hydrateFromDetail: (detail: {
    id: string
    question: string
    phase: Phase
    phase1: Array<{ persona_id: string; status: AgentStatus; text: string; confidence: number | null; error: string | null }>
    phase2: Array<{ persona_id: string; status: AgentStatus; text: string; confidence: number | null; error: string | null }>
    moderator: ModeratorContent | null
    moderator_thinking: string
    moderator_fallback_reason?: string | null
    rounds: Array<{
      round_index: number
      question: string
      phase1: Array<{ persona_id: string; status: AgentStatus; text: string; confidence: number | null; error: string | null }>
      phase2: Array<{ persona_id: string; status: AgentStatus; text: string; confidence: number | null; error: string | null }>
      moderator: ModeratorContent | null
      moderator_thinking: string
      created_at: string
      completed_at: string
    }>
    round_index: number
    personas: string[]
  }) => void

  // ── streaming handlers（SSE 事件回调）──
  setAgentStatus: (phase: 'phase1' | 'phase2', personaId: PersonaId, status: AgentStatus) => void
  appendAgentText: (phase: 'phase1' | 'phase2', personaId: PersonaId, chunk: string) => void
  /** 从末尾裁掉 n 个字符（backend 发送 agent_strip_tail 事件触发，用于剥离 [置信度: 0.xx] 标记）*/
  stripAgentTail: (phase: 'phase1' | 'phase2', personaId: PersonaId, n: number) => void
  setAgentConfidence: (phase: 'phase1' | 'phase2', personaId: PersonaId, value: number) => void
  setAgentError: (phase: 'phase1' | 'phase2', personaId: PersonaId, error: string) => void
  setModerator: (content: ModeratorContent, fallbackReason?: string | null) => void
  setModeratorSection: (section: keyof ModeratorContent, value: string | string[]) => void
  setModeratorThinking: (text: string) => void

  // ── safety ──
  setCrisis: (event: CrisisEvent | null) => void
  setError: (message: string | null) => void
}

const initialAgents = (personaIds: PersonaId[]): AgentMessageData[] =>
  personaIds.map((id) => ({ personaId: id, status: 'pending' as AgentStatus, text: '' }))

export const useRoundtableStore = create<RoundtableState>((set) => ({
  // setup
  selectedPersonas: [],
  question: '',
  deepMode: false,

  // session
  sessionId: null,
  currentPhase: 'setup',
  phase1Agents: [],
  phase2Agents: [],
  moderator: null,
  moderatorThinking: null,
  moderatorFallbackReason: null,
  isReadOnlySnapshot: false,
  crisis: null,
  error: null,

  // Day 6 · 多轮默认
  rounds: [],
  roundIndex: 0,
  streamNonce: 0,

  togglePersona: (id) =>
    set((state) => {
      const exists = state.selectedPersonas.includes(id)
      if (exists) {
        return { selectedPersonas: state.selectedPersonas.filter((p) => p !== id) }
      }
      if (state.selectedPersonas.length >= 3) return state
      return { selectedPersonas: [...state.selectedPersonas, id] }
    }),

  setPersonas: (ids) => set({ selectedPersonas: ids.slice(0, 3) }),

  setQuestion: (q) => set({ question: q }),

  setDeepMode: (v) => set({ deepMode: v }),

  resetSetup: () => set({ selectedPersonas: [], question: '', deepMode: false }),

  startSession: (sessionId) =>
    set((state) => ({
      sessionId,
      currentPhase: 'phase1',
      phase1Agents: initialAgents(state.selectedPersonas),
      phase2Agents: initialAgents(state.selectedPersonas),
      moderator: null,
      moderatorThinking: null,
      moderatorFallbackReason: null,
      isReadOnlySnapshot: false,
      crisis: null,
      error: null,
      // Day 6 · 新 session 起点 · rounds 清空、round_index=0、streamNonce=0
      rounds: [],
      roundIndex: 0,
      streamNonce: 0,
    })),

  advancePhase: (phase) => set({ currentPhase: phase }),

  resetSession: () =>
    set({
      sessionId: null,
      currentPhase: 'setup',
      phase1Agents: [],
      phase2Agents: [],
      moderator: null,
      moderatorThinking: null,
      moderatorFallbackReason: null,
      isReadOnlySnapshot: false,
      crisis: null,
      error: null,
      // Day 6 · 多轮重置
      rounds: [],
      roundIndex: 0,
      streamNonce: 0,
    }),

  // ── Day 6 · 多轮 actions 实现 ──

  archiveCurrentRoundAndReset: (nextQuestion) =>
    set((state) => {
      const nowIso = new Date().toISOString()
      const snapshot: RoundSnapshot = {
        roundIndex: state.roundIndex,
        question: state.question,
        phase1: state.phase1Agents.map((a) => ({ ...a })),
        phase2: state.phase2Agents.map((a) => ({ ...a })),
        moderator: state.moderator,
        moderatorThinking: state.moderatorThinking ?? '',
        // 前端无法精确知道 createdAt/completedAt，用当前时间作为 completedAt；
        // 若后续从 backend hydrate 则会被覆盖为精确时间。
        createdAt: nowIso,
        completedAt: nowIso,
      }
      return {
        rounds: [...state.rounds, snapshot],
        roundIndex: state.roundIndex + 1,
        question: nextQuestion,
        // 当前轮字段清空，等 SSE 推 phase_advance / agent_chunk 重新填充
        currentPhase: 'setup',
        phase1Agents: initialAgents(state.selectedPersonas),
        phase2Agents: initialAgents(state.selectedPersonas),
        moderator: null,
        moderatorThinking: null,
        moderatorFallbackReason: null,
        // 新一轮肯定不是只读快照
        isReadOnlySnapshot: false,
        crisis: null,
        error: null,
        // 关键：bump streamNonce 触发 hook 重建 EventSource
        streamNonce: state.streamNonce + 1,
      }
    }),

  hydrateFromDetail: (detail) => {
    const toAgent = (
      b: { persona_id: string; status: AgentStatus; text: string; confidence: number | null; error: string | null },
    ): AgentMessageData => ({
      personaId: b.persona_id as PersonaId,
      status: b.status,
      text: b.text,
      confidence: b.confidence ?? undefined,
      error: b.error ?? undefined,
    })
    set((state) => ({
      sessionId: detail.id,
      selectedPersonas: detail.personas as PersonaId[],
      question: detail.question,
      currentPhase: detail.phase,
      phase1Agents: detail.phase1.map(toAgent),
      phase2Agents: detail.phase2.map(toAgent),
      moderator: detail.moderator,
      moderatorThinking: detail.moderator_thinking || null,
      moderatorFallbackReason: detail.moderator_fallback_reason ?? null,
      // Day 7 · D7.1.f · 非 done 进入只读快照模式（避免 EventSource 挂空连接 + UI 卡住）
      // 'done' 和 'setup' 都视为可继续（setup 基本不会出现在 hydrate 结果中 · 防御性包含）
      isReadOnlySnapshot: detail.phase !== 'done' && detail.phase !== 'setup',
      rounds: detail.rounds.map((r) => ({
        roundIndex: r.round_index,
        question: r.question,
        phase1: r.phase1.map(toAgent),
        phase2: r.phase2.map(toAgent),
        moderator: r.moderator,
        moderatorThinking: r.moderator_thinking || '',
        createdAt: r.created_at,
        completedAt: r.completed_at,
      })),
      roundIndex: detail.round_index,
      crisis: null,
      error: null,
      // hydrate 时不 bump streamNonce（页面首屏不重连）
      streamNonce: state.streamNonce,
    }))
  },

  setAgentStatus: (phase, personaId, status) =>
    set((state) => ({
      [phase === 'phase1' ? 'phase1Agents' : 'phase2Agents']: (
        phase === 'phase1' ? state.phase1Agents : state.phase2Agents
      ).map((a) => (a.personaId === personaId ? { ...a, status } : a)),
    })),

  appendAgentText: (phase, personaId, chunk) =>
    set((state) => ({
      [phase === 'phase1' ? 'phase1Agents' : 'phase2Agents']: (
        phase === 'phase1' ? state.phase1Agents : state.phase2Agents
      ).map((a) => (a.personaId === personaId ? { ...a, text: a.text + chunk } : a)),
    })),

  stripAgentTail: (phase, personaId, n) =>
    set((state) => ({
      [phase === 'phase1' ? 'phase1Agents' : 'phase2Agents']: (
        phase === 'phase1' ? state.phase1Agents : state.phase2Agents
      ).map((a) =>
        a.personaId === personaId
          ? { ...a, text: a.text.length >= n ? a.text.slice(0, a.text.length - n).trimEnd() : a.text }
          : a,
      ),
    })),

  setAgentConfidence: (phase, personaId, value) =>
    set((state) => ({
      [phase === 'phase1' ? 'phase1Agents' : 'phase2Agents']: (
        phase === 'phase1' ? state.phase1Agents : state.phase2Agents
      ).map((a) => (a.personaId === personaId ? { ...a, confidence: value } : a)),
    })),

  setAgentError: (phase, personaId, error) =>
    set((state) => ({
      [phase === 'phase1' ? 'phase1Agents' : 'phase2Agents']: (
        phase === 'phase1' ? state.phase1Agents : state.phase2Agents
      ).map((a) =>
        a.personaId === personaId ? { ...a, status: 'error' as AgentStatus, error } : a,
      ),
    })),

  setModerator: (content, fallbackReason = null) =>
    set({ moderator: content, moderatorFallbackReason: fallbackReason ?? null }),

  setModeratorThinking: (text) => set({ moderatorThinking: text }),

  setModeratorSection: (section, value) =>
    set((state) => ({
      moderator: state.moderator
        ? ({ ...state.moderator, [section]: value } as ModeratorContent)
        : null,
    })),

  setCrisis: (event) => set({ crisis: event }),

  setError: (message) => set({ error: message }),
}))
