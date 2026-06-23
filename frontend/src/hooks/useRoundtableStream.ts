/**
 * `useRoundtableStream` · 圆桌讨论真实 SSE 订阅 Hook
 *
 * **职责**：连接 backend 的单 SSE endpoint，按 `agent_id` 字段分流到
 * Zustand store 的对应 phase agent buffer，处理 phase 切换 + Moderator
 * 综合输出 + 错误。
 *
 * **设计依据**（执行方案 §1.2 共识）：
 *   - 「单 SSE endpoint + `agent_id` 事件字段」（ChatGPT 多路复用）
 *   - 「Zustand Record / agent buffers」（Gemini 状态管理）
 *   - 「AgentStatus 状态机」（MP UI）
 *
 * **Day 5 接入说明**：
 *   - Day 1-4 此 Hook **默认 disabled**（`enabled=false`），Mock streaming
 *     仍由 `RoundtableSessionPage` 内部的 `runMockStreaming()` 负责
 *   - Day 5 切换：把 `RoundtableSessionPage` 的 `runMockStreaming` 移除，
 *     改为 `useRoundtableStream({ enabled: true, sessionId })`，store actions
 *     自动被事件驱动
 *
 * **SSE Event Schema**（与 backend `app/api/roundtable.py` 对齐）：
 *   - `agent_status` { agent_id, phase, status }
 *   - `agent_chunk`  { agent_id, phase, delta }（字符级增量）
 *   - `agent_done`   { agent_id, phase, confidence }
 *   - `agent_error`  { agent_id, phase, error }
 *   - `phase_advance` { phase }
 *   - `moderator`    { content }
 *   - `done`         {}
 *   - `error`        { message }
 */

import { useEffect, useRef, useState } from 'react'
import type { PersonaId } from '@/data/personas'
import {
  useRoundtableStore,
  type AgentStatus,
  type ModeratorContent,
  type Phase,
} from '@/stores/useRoundtableStore'

// ── SSE Event 类型定义（与 backend schema 严格一致）──

export type RoundtablePhase = Extract<Phase, 'phase1' | 'phase2'>

export type RoundtableSseEvent =
  | { type: 'agent_status'; agent_id: PersonaId; phase: RoundtablePhase; status: AgentStatus }
  | { type: 'agent_chunk'; agent_id: PersonaId; phase: RoundtablePhase; delta: string }
  | {
      type: 'agent_strip_tail'
      agent_id: PersonaId
      phase: RoundtablePhase
      strip_chars: number
    }
  | { type: 'agent_done'; agent_id: PersonaId; phase: RoundtablePhase; confidence: number }
  | { type: 'agent_error'; agent_id: PersonaId; phase: RoundtablePhase; error: string }
  | { type: 'phase_advance'; phase: Phase }
  | { type: 'moderator_thinking'; text: string }
  | {
      type: 'moderator'
      content: ModeratorContent
      /**
       * Day 7 · Moderator LLM 失败降级原因 · null=LLM 成功 · 其余值代表本轮走了规则模板（无跨轮记忆）
       * 值域参考：'llm_returned_none' | 'llm_disabled' | 'exception:XxxError'
       */
      fallback_reason?: string | null
    }
  | {
      type: 'crisis'
      level: 'YELLOW' | 'ORANGE' | 'RED'
      matched_keywords?: string[]
      template?: Record<string, unknown>
      hotlines?: Array<Record<string, unknown>>
    }
  | { type: 'done' }
  | { type: 'error'; message: string }

// ── Hook 接口 ──

export type StreamStatus = 'idle' | 'connecting' | 'streaming' | 'closed' | 'error'

interface UseRoundtableStreamOptions {
  /** 是否启用订阅。Day 5 之前默认 false（mock streaming 在 Session 页内）*/
  enabled?: boolean
  /** Session ID，用于构造 endpoint URL（必需） */
  sessionId: string | null
  /** 自定义 endpoint。默认 `/api/roundtable/stream/${sessionId}` */
  endpoint?: string
  /** 错误回调 */
  onError?: (err: Error) => void
  /** 完成回调（done 事件触发） */
  onDone?: () => void
  /**
   * Day 6 · 多轮重连 nonce · 每次 +1 会重建 EventSource 连接。
   * 调用方一般从 store 的 streamNonce 传入；sessionId 不变但 continue 后重连时必须 bump。
   */
  streamNonce?: number
}

interface UseRoundtableStreamReturn {
  status: StreamStatus
  error: Error | null
  /** 手动关闭连接（清理 EventSource） */
  close: () => void
}

// ── 纯函数 dispatcher（独立可单测）──

/**
 * 把单个 SSE 事件分发到 store 的对应 action。
 * 设计为纯函数（不依赖 React），方便单元测试不需要 mock React。
 */
export function dispatchRoundtableEvent(
  event: RoundtableSseEvent,
  store: ReturnType<typeof useRoundtableStore.getState>,
): void {
  switch (event.type) {
    case 'agent_status':
      store.setAgentStatus(event.phase, event.agent_id, event.status)
      break

    case 'agent_chunk':
      store.appendAgentText(event.phase, event.agent_id, event.delta)
      break

    case 'agent_strip_tail':
      // 剥离 agent 输出末尾的 [置信度: 0.xx] 标记（backend regex 提取后触发）
      store.stripAgentTail(event.phase, event.agent_id, event.strip_chars)
      break

    case 'crisis':
      // 危机检测：backend 发出 YELLOW/ORANGE/RED 级别
      store.setCrisis({
        level: event.level.toLowerCase() as 'yellow' | 'orange' | 'red',
        message:
          (event.template as { banner?: string } | undefined)?.banner ??
          `检测到 ${event.level} 级别的情绪信号`,
      })
      break

    case 'agent_done':
      store.setAgentStatus(event.phase, event.agent_id, 'done')
      store.setAgentConfidence(event.phase, event.agent_id, event.confidence)
      break

    case 'agent_error':
      store.setAgentError(event.phase, event.agent_id, event.error)
      break

    case 'phase_advance':
      store.advancePhase(event.phase)
      break

    case 'moderator_thinking':
      // LLM Moderator 的「综合思考」段（Day 5 方案① · 前端做打字机假流式）
      store.setModeratorThinking(event.text)
      break

    case 'moderator':
      // Day 7 · 接 fallback_reason · 前端据此在 ModeratorCard 上方渲染降级提示条
      store.setModerator(event.content, event.fallback_reason ?? null)
      // moderator 到达时自动推进到 done（与 mock 流程一致）
      if (store.currentPhase !== 'done') {
        store.advancePhase('done')
      }
      break

    case 'done':
      // backend 主动结束信号，store 此时不需要变更
      break

    case 'error':
      // backend 报错信号，由 hook 上层处理（onError 回调）
      console.error('[useRoundtableStream] backend reported error:', event.message)
      break

    default: {
      // 类型穷举检查（TypeScript exhaustiveness）
      const _exhaustive: never = event
      console.warn('[useRoundtableStream] unknown event type:', _exhaustive)
    }
  }
}

// ── Hook 主体 ──

/**
 * 订阅 backend 圆桌讨论 SSE 流，自动驱动 Zustand store。
 *
 * **使用示例**（Day 5 后）：
 * ```tsx
 * const { status, error } = useRoundtableStream({
 *   enabled: !!sessionId,
 *   sessionId,
 *   onError: (err) => toast.error(`圆桌讨论中断：${err.message}`),
 * })
 * ```
 */
export function useRoundtableStream({
  enabled = false,
  sessionId,
  endpoint,
  onError,
  onDone,
  streamNonce = 0,
}: UseRoundtableStreamOptions): UseRoundtableStreamReturn {
  const [status, setStatus] = useState<StreamStatus>('idle')
  const [error, setError] = useState<Error | null>(null)
  const esRef = useRef<EventSource | null>(null)

  // 用 ref 包裹回调，避免回调身份变化导致 useEffect 重新订阅
  const onErrorRef = useRef(onError)
  const onDoneRef = useRef(onDone)
  useEffect(() => {
    onErrorRef.current = onError
    onDoneRef.current = onDone
  }, [onError, onDone])

  const close = () => {
    if (esRef.current) {
      esRef.current.close()
      esRef.current = null
      setStatus('closed')
    }
  }

  useEffect(() => {
    if (!enabled || !sessionId) {
      return
    }

    const url = endpoint ?? `/api/roundtable/stream/${encodeURIComponent(sessionId)}`
    let active = true
    queueMicrotask(() => {
      if (!active) return
      setStatus('connecting')
      setError(null)
    })

    const es = new EventSource(url)
    esRef.current = es

    es.onopen = () => {
      setStatus('streaming')
    }

    es.onmessage = (msg) => {
      try {
        const event: RoundtableSseEvent = JSON.parse(msg.data)
        const store = useRoundtableStore.getState()
        dispatchRoundtableEvent(event, store)

        if (event.type === 'done') {
          es.close()
          esRef.current = null
          setStatus('closed')
          onDoneRef.current?.()
        } else if (event.type === 'error') {
          const err = new Error(event.message)
          setError(err)
          setStatus('error')
          onErrorRef.current?.(err)
        }
      } catch (parseErr) {
        const err =
          parseErr instanceof Error
            ? parseErr
            : new Error(`Failed to parse SSE message: ${String(parseErr)}`)
        console.error('[useRoundtableStream] parse error:', err, 'raw:', msg.data)
        setError(err)
        // 单条解析失败不中断订阅
      }
    }

    es.onerror = () => {
      // EventSource 自动重连，但若服务器关闭则 readyState === CLOSED
      if (es.readyState === EventSource.CLOSED) {
        const err = new Error('SSE connection closed unexpectedly')
        setError(err)
        setStatus('error')
        onErrorRef.current?.(err)
      }
      // 否则浏览器会自动重连，不必处理
    }

    return () => {
      active = false
      es.close()
      esRef.current = null
      setStatus('closed')
    }
    // Day 6 · streamNonce 每次 +1 会触发重连（continue 多轮场景）
  }, [enabled, sessionId, endpoint, streamNonce])

  return { status, error, close }
}
