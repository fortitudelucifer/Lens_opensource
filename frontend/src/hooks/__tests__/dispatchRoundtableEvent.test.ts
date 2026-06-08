/**
 * Day 5 · D · dispatchRoundtableEvent 单测
 *
 * 覆盖所有 8 种 SSE event 类型正确分发到 Zustand store actions。
 * dispatchRoundtableEvent 是纯函数，单测不需要 mock React。
 */
import { describe, expect, it, beforeEach, vi } from 'vitest'
import { dispatchRoundtableEvent } from '../useRoundtableStream'
import { useRoundtableStore } from '@/stores/useRoundtableStore'

// 每次测试前重置 store 并填充 3 个 persona，方便模拟 startSession
beforeEach(() => {
  useRoundtableStore.setState({
    selectedPersonas: ['neutral', 'bowen', 'eft'],
    question: 'test',
    sessionId: 'rt_test',
    currentPhase: 'phase1',
    phase1Agents: [
      { personaId: 'neutral', status: 'pending', text: '' },
      { personaId: 'bowen', status: 'pending', text: '' },
      { personaId: 'eft', status: 'pending', text: '' },
    ],
    phase2Agents: [
      { personaId: 'neutral', status: 'pending', text: '' },
      { personaId: 'bowen', status: 'pending', text: '' },
      { personaId: 'eft', status: 'pending', text: '' },
    ],
    moderator: null,
    crisis: null,
    error: null,
  })
})

describe('dispatchRoundtableEvent', () => {
  it('agent_status → 更新对应 persona status', () => {
    dispatchRoundtableEvent(
      { type: 'agent_status', agent_id: 'bowen', phase: 'phase1', status: 'typing' },
      useRoundtableStore.getState(),
    )
    const agent = useRoundtableStore
      .getState()
      .phase1Agents.find((a) => a.personaId === 'bowen')!
    expect(agent.status).toBe('typing')
  })

  it('agent_chunk → 追加 delta 到 text', () => {
    const store = useRoundtableStore.getState()
    dispatchRoundtableEvent(
      { type: 'agent_chunk', agent_id: 'neutral', phase: 'phase1', delta: '你好' },
      store,
    )
    dispatchRoundtableEvent(
      { type: 'agent_chunk', agent_id: 'neutral', phase: 'phase1', delta: '，' },
      store,
    )
    dispatchRoundtableEvent(
      { type: 'agent_chunk', agent_id: 'neutral', phase: 'phase1', delta: '世界' },
      store,
    )
    const agent = useRoundtableStore
      .getState()
      .phase1Agents.find((a) => a.personaId === 'neutral')!
    expect(agent.text).toBe('你好，世界')
  })

  it('agent_strip_tail → 从末尾裁掉 n 个字符 + trimEnd 余白', () => {
    const store = useRoundtableStore.getState()
    // 先填充文本
    dispatchRoundtableEvent(
      { type: 'agent_chunk', agent_id: 'eft', phase: 'phase2', delta: '分析正文 [置信度: 0.82]' },
      store,
    )
    // 只裁标记本身 "[置信度: 0.82]" = 11 chars，前面的空格由 trimEnd 清理
    dispatchRoundtableEvent(
      { type: 'agent_strip_tail', agent_id: 'eft', phase: 'phase2', strip_chars: 11 },
      store,
    )
    const agent = useRoundtableStore
      .getState()
      .phase2Agents.find((a) => a.personaId === 'eft')!
    expect(agent.text).toBe('分析正文')
  })

  it('agent_strip_tail · strip_chars > text.length 时保持原文不变', () => {
    const store = useRoundtableStore.getState()
    dispatchRoundtableEvent(
      { type: 'agent_chunk', agent_id: 'eft', phase: 'phase2', delta: '短' },
      store,
    )
    dispatchRoundtableEvent(
      { type: 'agent_strip_tail', agent_id: 'eft', phase: 'phase2', strip_chars: 100 },
      store,
    )
    const agent = useRoundtableStore
      .getState()
      .phase2Agents.find((a) => a.personaId === 'eft')!
    // 防护：n > len 时保留原文
    expect(agent.text).toBe('短')
  })

  it('agent_done → status=done + 填 confidence', () => {
    dispatchRoundtableEvent(
      { type: 'agent_done', agent_id: 'bowen', phase: 'phase2', confidence: 0.88 },
      useRoundtableStore.getState(),
    )
    const agent = useRoundtableStore
      .getState()
      .phase2Agents.find((a) => a.personaId === 'bowen')!
    expect(agent.status).toBe('done')
    expect(agent.confidence).toBe(0.88)
  })

  it('agent_error → status=error + 填 error msg', () => {
    dispatchRoundtableEvent(
      { type: 'agent_error', agent_id: 'neutral', phase: 'phase1', error: 'LLM timeout' },
      useRoundtableStore.getState(),
    )
    const agent = useRoundtableStore
      .getState()
      .phase1Agents.find((a) => a.personaId === 'neutral')!
    expect(agent.status).toBe('error')
    expect(agent.error).toBe('LLM timeout')
  })

  it('phase_advance → 切 currentPhase', () => {
    dispatchRoundtableEvent(
      { type: 'phase_advance', phase: 'phase2' },
      useRoundtableStore.getState(),
    )
    expect(useRoundtableStore.getState().currentPhase).toBe('phase2')
  })

  it('moderator_thinking → 填 moderatorThinking · 不推进 phase', () => {
    useRoundtableStore.setState({ currentPhase: 'phase3' })
    dispatchRoundtableEvent(
      { type: 'moderator_thinking', text: '我看到三位顾问都指向同一个张力……' },
      useRoundtableStore.getState(),
    )
    const s = useRoundtableStore.getState()
    expect(s.moderatorThinking).toContain('三位顾问')
    // thinking 事件本身不应推进 phase（要等 moderator 事件）
    expect(s.currentPhase).toBe('phase3')
    expect(s.moderator).toBeNull()
  })

  it('moderator → 填 moderator + 自动推进到 done', () => {
    const content = {
      seen: 'seen text',
      angles: ['A', 'B', 'C'],
      tries: ['T1', 'T2', 'T3'],
      doubts: ['D1', 'D2'],
      lens: 'lens text',
      limit: 'limit text',
    }
    dispatchRoundtableEvent(
      { type: 'moderator', content },
      useRoundtableStore.getState(),
    )
    const s = useRoundtableStore.getState()
    expect(s.moderator).toEqual(content)
    expect(s.currentPhase).toBe('done')
  })

  it('crisis → 填 crisis state（level 小写）', () => {
    dispatchRoundtableEvent(
      {
        type: 'crisis',
        level: 'RED',
        matched_keywords: ['不想活'],
        template: { banner: '请立即拨打心理援助热线' },
        hotlines: [],
      },
      useRoundtableStore.getState(),
    )
    const crisis = useRoundtableStore.getState().crisis
    expect(crisis?.level).toBe('red')
    expect(crisis?.message).toContain('请立即拨打心理援助热线')
  })

  it('crisis · 无 template 时用默认 message', () => {
    dispatchRoundtableEvent(
      { type: 'crisis', level: 'YELLOW' },
      useRoundtableStore.getState(),
    )
    const crisis = useRoundtableStore.getState().crisis
    expect(crisis?.level).toBe('yellow')
    expect(crisis?.message).toContain('YELLOW')
  })

  it('done → 不改变 store（只是 SSE 结束信号）', () => {
    const before = { ...useRoundtableStore.getState() }
    dispatchRoundtableEvent(
      { type: 'done' },
      useRoundtableStore.getState(),
    )
    const after = useRoundtableStore.getState()
    expect(after.currentPhase).toBe(before.currentPhase)
    expect(after.moderator).toBe(before.moderator)
  })

  it('error → 只打 console.error，不炸', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
    expect(() =>
      dispatchRoundtableEvent(
        { type: 'error', message: 'backend crashed' },
        useRoundtableStore.getState(),
      ),
    ).not.toThrow()
    expect(spy).toHaveBeenCalledWith(
      expect.stringContaining('backend reported error'),
      'backend crashed',
    )
    spy.mockRestore()
  })

  it('agent_chunk 不影响其他 persona', () => {
    const store = useRoundtableStore.getState()
    dispatchRoundtableEvent(
      { type: 'agent_chunk', agent_id: 'bowen', phase: 'phase1', delta: 'only bowen' },
      store,
    )
    const neutral = useRoundtableStore
      .getState()
      .phase1Agents.find((a) => a.personaId === 'neutral')!
    expect(neutral.text).toBe('')
  })

  it('agent_chunk 不影响另一个 phase', () => {
    const store = useRoundtableStore.getState()
    dispatchRoundtableEvent(
      { type: 'agent_chunk', agent_id: 'neutral', phase: 'phase2', delta: 'phase2 only' },
      store,
    )
    const p1 = useRoundtableStore
      .getState()
      .phase1Agents.find((a) => a.personaId === 'neutral')!
    const p2 = useRoundtableStore
      .getState()
      .phase2Agents.find((a) => a.personaId === 'neutral')!
    expect(p1.text).toBe('')
    expect(p2.text).toBe('phase2 only')
  })
})
