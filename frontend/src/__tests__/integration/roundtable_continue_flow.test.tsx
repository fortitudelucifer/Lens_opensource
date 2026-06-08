/**
 * D5.7 · 档 1 · 圆桌讨论多轮 continue 流集成测试（Vitest + RTL）
 *
 * 目标：
 *   模拟 Day 6 形态 A 的多轮追问 + D7.1.j++ 路由 / streamNonce 修复 · 验证：
 *     ① 第 1 轮跑完 → archiveCurrentRoundAndReset → rounds[0] 归档 + streamNonce +1 + phase='setup' + sessionId 保留
 *     ② 第 2 轮 SSE 事件被正确分发到当前轮 agent buffer（不污染 rounds[0]）
 *     ③ 第 2 轮 Moderator 降级路径（fallback_reason 非空）UI 可见 amber banner（承接 D7.1.j+ 降级记忆修复）
 *     ④ rounds.length=1 · roundIndex=1 后，RoundtableSessionPage 顶部显示「已完成 · 1 轮讨论」折叠区
 */

import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

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
vi.mock('@/hooks/useReducedMotion', () => ({ useReducedMotion: () => true }))
vi.mock('sonner', () => ({ toast: { error: vi.fn() } }))

import { dispatchRoundtableEvent } from '@/hooks/useRoundtableStream'
import { RoundtableSessionPage } from '@/pages/RoundtableSessionPage'
import { useRoundtableStore } from '@/stores/useRoundtableStore'

const PERSONAS = ['neutral', 'supportive', 'eft'] as const

const ROUND1_MODERATOR = {
  seen: '听到你说「我男友冷战三天」·看到你正在认真寻找一种被看见的方式。',
  angles: ['中立（0.80）', '支持性（0.82）', 'EFT（0.85）'],
  tries: ['今晚先写下三句话', '用邀请而非质问开头', '允许自己把注意力先移回自己'],
  doubts: ['如果对方仍然沉默，你会怎么办？', '这件事是否还有尚未说出口的细节？'],
  lens: '你不是一个人在面对这件事。',
  limit: 'Lens 圆桌讨论是非诊断性的探索工具。',
}

const ROUND2_MODERATOR = {
  seen: '上一轮（第 1 轮）你说「男友冷战三天」·这次（第 2 轮）又带回「我们对话后我已经放下了」——这件事还在发酵。',
  angles: ['中立（0.80）', '支持性（0.85）', 'EFT（0.82）'],
  tries: ['上轮我们建议过先写下三句话·如果没试可以先试', '不要一次解决所有·先选一个最能撬动的小动作'],
  doubts: ['上轮我们一起留下过这个问题·现在它有进展了吗？'],
  lens: '这是我们的第 2 轮陪伴·你回到这里继续思考本身就是一种力量。',
  limit: 'Lens 圆桌讨论是非诊断性的探索工具。',
}

describe('D5.7 · 多轮 continue 流 · rounds 归档 + streamNonce bump + 历史折叠区', () => {
  beforeEach(() => {
    useRoundtableStore.getState().resetSession()
    useRoundtableStore.getState().resetSetup()
    useRoundtableStore.setState({
      selectedPersonas: [...PERSONAS],
      question: '我男友冷战三天',
    })
    useRoundtableStore.getState().startSession('rt_e2e_continue')
  })

  afterEach(() => {
    document.body.innerHTML = ''
  })

  /** 一轮完整 SSE 事件流 · 从 phase1 走到 done */
  function runOneRoundEvents(mod: typeof ROUND1_MODERATOR, fallbackReason: string | null = null) {
    const store = useRoundtableStore.getState()
    act(() => {
      for (const pid of PERSONAS) {
        dispatchRoundtableEvent(
          { type: 'agent_chunk', agent_id: pid, phase: 'phase1', delta: `${pid}-p1` },
          store,
        )
        dispatchRoundtableEvent(
          { type: 'agent_done', agent_id: pid, phase: 'phase1', confidence: 0.8 },
          store,
        )
      }
      dispatchRoundtableEvent({ type: 'phase_advance', phase: 'phase2' }, store)
      for (const pid of PERSONAS) {
        dispatchRoundtableEvent(
          { type: 'agent_chunk', agent_id: pid, phase: 'phase2', delta: `${pid}-p2` },
          store,
        )
        dispatchRoundtableEvent(
          { type: 'agent_done', agent_id: pid, phase: 'phase2', confidence: 0.85 },
          store,
        )
      }
      dispatchRoundtableEvent({ type: 'phase_advance', phase: 'phase3' }, store)
      dispatchRoundtableEvent(
        { type: 'moderator', content: mod, fallback_reason: fallbackReason },
        store,
      )
    })
  }

  it('完成第 1 轮 → archive → rounds[0] 归档 + streamNonce=1 + phase=setup + sessionId 保留', () => {
    runOneRoundEvents(ROUND1_MODERATOR)

    // 归档前确认第 1 轮 done
    let s = useRoundtableStore.getState()
    expect(s.currentPhase).toBe('done')
    expect(s.rounds).toHaveLength(0)
    expect(s.roundIndex).toBe(0)
    expect(s.streamNonce).toBe(0)

    // 用户点"继续追问" · 触发归档 + bump streamNonce
    act(() => {
      useRoundtableStore.getState().archiveCurrentRoundAndReset('我已经放下了·她来找我该怎么应对？')
    })

    s = useRoundtableStore.getState()
    expect(s.rounds).toHaveLength(1) // 归档成功
    expect(s.rounds[0].roundIndex).toBe(0)
    expect(s.rounds[0].moderator).toEqual(ROUND1_MODERATOR)
    expect(s.rounds[0].phase1).toHaveLength(3)
    expect(s.rounds[0].phase1.every((a) => a.status === 'done')).toBe(true)
    expect(s.roundIndex).toBe(1) // 进入第 2 轮
    expect(s.currentPhase).toBe('setup') // 当前轮 UI 重置
    expect(s.sessionId).toBe('rt_e2e_continue') // ⭐ D7.1.j++ 关键：sessionId 必须保留
    expect(s.streamNonce).toBe(1) // hook 依赖 nonce 重连 EventSource
    expect(s.question).toBe('我已经放下了·她来找我该怎么应对？') // 第 2 轮问题已设置
    expect(s.moderator).toBeNull() // 当前轮 moderator 清空
  })

  it('第 2 轮 SSE 事件 · 不污染 rounds[0] · 只填当前轮 buffer', () => {
    runOneRoundEvents(ROUND1_MODERATOR)
    act(() => {
      useRoundtableStore.getState().archiveCurrentRoundAndReset('第 2 轮问题')
    })

    // 第 2 轮 phase1 启动（backend 在 streamNonce bump 后重建 EventSource）
    const store = useRoundtableStore.getState()
    act(() => {
      dispatchRoundtableEvent({ type: 'phase_advance', phase: 'phase1' }, store)
      for (const pid of PERSONAS) {
        dispatchRoundtableEvent(
          { type: 'agent_chunk', agent_id: pid, phase: 'phase1', delta: `r2-${pid}-p1` },
          store,
        )
      }
    })

    const s = useRoundtableStore.getState()
    // 当前轮 buffer 填入第 2 轮内容
    expect(s.phase1Agents.every((a) => a.text.includes('r2-'))).toBe(true)
    // rounds[0] 保持不变（归档快照不可变）
    expect(s.rounds[0].phase1.every((a) => a.text.includes('-p1'))).toBe(true)
    expect(s.rounds[0].phase1.every((a) => !a.text.includes('r2-'))).toBe(true)
  })

  it('第 2 轮 Moderator 降级路径 · fallback_reason 非 null · amber banner 可见（D7.1.j+ 记忆承接语）', () => {
    runOneRoundEvents(ROUND1_MODERATOR)
    act(() => {
      useRoundtableStore.getState().archiveCurrentRoundAndReset('我已经放下了')
    })

    // 第 2 轮走降级（规则模板承接 · D7.1.j+ 修复）
    runOneRoundEvents(ROUND2_MODERATOR, 'llm_returned_none')

    const s = useRoundtableStore.getState()
    expect(s.moderatorFallbackReason).toBe('llm_returned_none')
    expect(s.moderator?.seen).toMatch(/第 2 轮|第 2 轮|上一轮/) // 承接语
    expect(s.rounds).toHaveLength(1) // 当前轮未归档

    // 挂载 SessionPage · 验证 amber banner 渲染
    render(<RoundtableSessionPage />)
    expect(screen.getByText(/Moderator 已降级/)).toBeInTheDocument()
    // 历史折叠区（rounds.length=1）
    expect(screen.getByText(/已完成.*1.*轮/)).toBeInTheDocument()
  })

  it('连续 2 次 continue · rounds 正确堆叠 2 轮 · streamNonce=2', () => {
    runOneRoundEvents(ROUND1_MODERATOR)
    act(() => {
      useRoundtableStore.getState().archiveCurrentRoundAndReset('第 2 轮')
    })
    runOneRoundEvents(ROUND2_MODERATOR)
    act(() => {
      useRoundtableStore.getState().archiveCurrentRoundAndReset('第 3 轮')
    })

    const s = useRoundtableStore.getState()
    expect(s.rounds).toHaveLength(2)
    expect(s.rounds[0].roundIndex).toBe(0)
    expect(s.rounds[1].roundIndex).toBe(1)
    expect(s.roundIndex).toBe(2)
    expect(s.streamNonce).toBe(2) // 每次 continue +1
    expect(s.sessionId).toBe('rt_e2e_continue')
    expect(s.question).toBe('第 3 轮')
  })
})
