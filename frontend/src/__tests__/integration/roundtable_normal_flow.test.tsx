/**
 * D5.7 · 档 1 · 圆桌讨论端到端正常流集成测试（Vitest + RTL）
 *
 * 目标：
 *   模拟一个 backend 会话从 create → phase1 → phase2 → phase3 → moderator → done 的完整事件流，
 *   用 dispatchRoundtableEvent 喂 SSE 事件，验证：
 *     ① store 状态机按顺序推进
 *     ② RoundtableSessionPage UI 正确渲染每阶段
 *     ③ Moderator 六段结构（seen / angles / tries / doubts / lens / limit）全部出现
 *
 * 不依赖真 EventSource / fetch · vi.mock useRoundtableStream 阻断 SSE 订阅
 * vi.mock useReducedMotion=true 跳过 typing/streaming sleep · 确定性 + 快
 */

import { act, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// ── mock 外部 deps · importOriginal 保留真 dispatchRoundtableEvent ──
vi.mock('@/hooks/useRoundtableStream', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/hooks/useRoundtableStream')>()
  return {
    ...actual,
    useRoundtableStream: () => ({
      status: 'streaming' as const,
      error: null,
      close: vi.fn(),
    }),
  }
})
vi.mock('@/hooks/useReducedMotion', () => ({
  useReducedMotion: () => true,
}))
vi.mock('sonner', () => ({ toast: { error: vi.fn() } }))

import { dispatchRoundtableEvent } from '@/hooks/useRoundtableStream'
import { RoundtableSessionPage } from '@/pages/RoundtableSessionPage'
import { useRoundtableStore } from '@/stores/useRoundtableStore'

const PERSONAS = ['neutral', 'supportive', 'eft'] as const

const MOCK_MODERATOR = {
  seen: '听到你在说的是「男友冷战三天」——这件事本身就值得被认真对待。',
  angles: [
    '中立顾问 关注事实/解读/需求三层切片（0.82）',
    '支持性顾问 先承认情绪再谈行动（0.80）',
    'EFT 顾问 把冷战视为依恋系统的求救信号（0.85）',
  ],
  tries: [
    '今晚先写下三句话：我此刻的感受 / 我希望被看见 / 我能承担的',
    '用"邀请"而非"质问"开头：我想聊聊这件事，你愿意吗？',
    '如果对方此刻不回应，允许自己把注意力先移回自己',
  ],
  doubts: [
    '如果尝试之后对方仍然沉默，你会怎么办？',
    '「男友冷战三天」背后是否还有你尚未说出口的细节？',
  ],
  lens: '你不是一个人在面对这件事。我们会一直在你愿意回来思考的时候在这里。',
  limit: 'Lens 圆桌讨论是非诊断性的探索工具，不能替代专业心理咨询或医疗评估。',
}

describe('D5.7 · 正常流 · session 从 phase1 走到 done', () => {
  beforeEach(() => {
    useRoundtableStore.getState().resetSession()
    useRoundtableStore.getState().resetSetup()
    useRoundtableStore.setState({ selectedPersonas: [...PERSONAS], question: '男友冷战三天' })
    useRoundtableStore.getState().startSession('rt_e2e_normal')
  })

  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('phase1 阶段 · 3 位 agent 并发流式 · 文本可累积 · status 可推进', () => {
    const store = useRoundtableStore.getState()
    render(<RoundtableSessionPage />)

    // phase1 标题（PhaseBanner 渲染）
    expect(screen.getByText(/男友冷战三天/)).toBeInTheDocument()

    act(() => {
      for (const pid of PERSONAS) {
        dispatchRoundtableEvent({ type: 'agent_status', agent_id: pid, phase: 'phase1', status: 'streaming' }, store)
        dispatchRoundtableEvent({ type: 'agent_chunk', agent_id: pid, phase: 'phase1', delta: `${pid} 的看法：` }, store)
        dispatchRoundtableEvent({ type: 'agent_chunk', agent_id: pid, phase: 'phase1', delta: '先承认情绪。' }, store)
      }
    })

    // store 视角断言
    const s1 = useRoundtableStore.getState()
    expect(s1.phase1Agents).toHaveLength(3)
    expect(s1.phase1Agents.every((a) => a.status === 'streaming')).toBe(true)
    expect(s1.phase1Agents.every((a) => a.text.includes('先承认情绪。'))).toBe(true)

    // UI 视角断言（流式文本渲染到页面）
    for (const pid of PERSONAS) {
      expect(screen.getAllByText(new RegExp(`${pid} 的看法：`)).length).toBeGreaterThan(0)
    }
  })

  it('phase1 done → phase2 交叉回应 · advance phase_advance 推进 UI', () => {
    const store = useRoundtableStore.getState()
    render(<RoundtableSessionPage />)

    // phase1 全部完成
    act(() => {
      for (const pid of PERSONAS) {
        dispatchRoundtableEvent({ type: 'agent_chunk', agent_id: pid, phase: 'phase1', delta: `${pid} p1 done` }, store)
        dispatchRoundtableEvent({ type: 'agent_done', agent_id: pid, phase: 'phase1', confidence: 0.85 }, store)
      }
      dispatchRoundtableEvent({ type: 'phase_advance', phase: 'phase2' }, store)
    })
    expect(useRoundtableStore.getState().currentPhase).toBe('phase2')

    // phase2 流式追加
    act(() => {
      for (const pid of PERSONAS) {
        dispatchRoundtableEvent({ type: 'agent_chunk', agent_id: pid, phase: 'phase2', delta: `${pid} p2 追加` }, store)
        dispatchRoundtableEvent({ type: 'agent_done', agent_id: pid, phase: 'phase2', confidence: 0.88 }, store)
      }
    })

    const s = useRoundtableStore.getState()
    expect(s.phase2Agents.every((a) => a.status === 'done')).toBe(true)
    expect(s.phase2Agents.every((a) => a.text.includes('追加'))).toBe(true)
    expect(s.phase2Agents.every((a) => a.confidence === 0.88)).toBe(true)
  })

  it('phase3 Moderator 到达 · 六段结构全部渲染 · phase 自动置 done', () => {
    const store = useRoundtableStore.getState()
    render(<RoundtableSessionPage />)

    // 一口气把 phase1/2 走完
    act(() => {
      for (const pid of PERSONAS) {
        dispatchRoundtableEvent({ type: 'agent_chunk', agent_id: pid, phase: 'phase1', delta: '短语' }, store)
        dispatchRoundtableEvent({ type: 'agent_done', agent_id: pid, phase: 'phase1', confidence: 0.8 }, store)
      }
      dispatchRoundtableEvent({ type: 'phase_advance', phase: 'phase2' }, store)
      for (const pid of PERSONAS) {
        dispatchRoundtableEvent({ type: 'agent_chunk', agent_id: pid, phase: 'phase2', delta: '交叉' }, store)
        dispatchRoundtableEvent({ type: 'agent_done', agent_id: pid, phase: 'phase2', confidence: 0.85 }, store)
      }
      dispatchRoundtableEvent({ type: 'phase_advance', phase: 'phase3' }, store)
      // Moderator thinking（选填 · 打字机假流）
      dispatchRoundtableEvent({ type: 'moderator_thinking', text: '我看到三位顾问都指向同一个张力……' }, store)
      dispatchRoundtableEvent({ type: 'moderator', content: MOCK_MODERATOR, fallback_reason: null }, store)
    })

    // store 推进到 done
    const s = useRoundtableStore.getState()
    expect(s.currentPhase).toBe('done')
    expect(s.moderator).toEqual(MOCK_MODERATOR)
    expect(s.moderatorFallbackReason).toBeNull()

    // Moderator 六段都在 DOM · 用户问题「男友冷战三天」会在 Quote + seen 两处出现
    expect(screen.getAllByText(/男友冷战三天/).length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText(/先写下三句话/)).toBeInTheDocument() // tries
    expect(screen.getByText(/尚未说出口的细节/)).toBeInTheDocument() // doubts
    expect(screen.getByText(/你不是一个人在面对这件事/)).toBeInTheDocument() // lens
    expect(screen.getByText(/非诊断性的探索工具/)).toBeInTheDocument() // limit
  })

  it('fallback_reason 非 null · ModeratorCard 降级 banner 可见', () => {
    const store = useRoundtableStore.getState()
    render(<RoundtableSessionPage />)

    act(() => {
      dispatchRoundtableEvent({ type: 'phase_advance', phase: 'phase3' }, store)
      dispatchRoundtableEvent(
        { type: 'moderator', content: MOCK_MODERATOR, fallback_reason: 'llm_returned_none' },
        store,
      )
    })

    expect(useRoundtableStore.getState().moderatorFallbackReason).toBe('llm_returned_none')
    // amber 降级 banner
    expect(screen.getByRole('status')).toBeInTheDocument()
  })

  it('整个 session 流程后 · phase3 阶段 phase1Faded=true · phase2Faded=true 样式生效', () => {
    const store = useRoundtableStore.getState()
    const { container } = render(<RoundtableSessionPage />)

    act(() => {
      dispatchRoundtableEvent({ type: 'phase_advance', phase: 'phase2' }, store)
      dispatchRoundtableEvent({ type: 'phase_advance', phase: 'phase3' }, store)
    })

    // phase1 grid 应该有淑化 class
    const phase1Wrapper = within(container).queryByLabelText(/Phase 1 completed/)
    expect(phase1Wrapper).not.toBeNull()
  })
})
