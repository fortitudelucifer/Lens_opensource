/**
 * Day 6 · 多轮对话形态 A · Roundtable store 回归单测
 *
 * 覆盖：
 *   - `archiveCurrentRoundAndReset` · 归档当前轮 + 重置 agents + bump streamNonce + 更新 question
 *   - `hydrateFromDetail` · 从 backend detail 恢复完整状态（包含 rounds[] + 当前轮）
 *   - `resetSession` · 多轮字段一并清空
 */

import { beforeEach, describe, expect, it } from 'vitest'
import { useRoundtableStore } from '../useRoundtableStore'
import type { ModeratorContent } from '../useRoundtableStore'

const MOCK_MODERATOR: ModeratorContent = {
  seen: '我看到你承担了很多情绪。',
  angles: ['中立：拆事实/解读', '支持：先接住情绪', 'EFT：依恋需求'],
  tries: ['先写日记', '用邀请非质问', '1 小时自我照顾'],
  doubts: ['他会回应吗？', '还有未说的细节？'],
  lens: '你不是一个人。',
  limit: '非诊断性工具。',
}

function primeDoneRoundState(question = '测试问题：我们为什么老吵架？') {
  const store = useRoundtableStore.getState()
  // setup
  store.setPersonas(['neutral', 'supportive', 'eft'])
  store.setQuestion(question)
  store.startSession('rt_test_123')
  // fill phase1/phase2
  for (const pid of ['neutral', 'supportive', 'eft'] as const) {
    store.setAgentStatus('phase1', pid, 'done')
    store.appendAgentText('phase1', pid, `${pid} phase1 回应`)
    store.setAgentStatus('phase2', pid, 'done')
    store.appendAgentText('phase2', pid, `${pid} phase2 交叉回应`)
    store.setAgentConfidence('phase2', pid, 0.8)
  }
  store.setModerator(MOCK_MODERATOR)
  store.setModeratorThinking('三方共识：先被看见。')
  store.advancePhase('done')
}

describe('useRoundtableStore · Day 6 多轮 actions', () => {
  beforeEach(() => {
    // 每个 case 先完全重置
    useRoundtableStore.getState().resetSession()
    useRoundtableStore.getState().resetSetup()
  })

  describe('archiveCurrentRoundAndReset', () => {
    it('把当前轮 snapshot 归档到 rounds[]，更新 question，重置 agents', () => {
      primeDoneRoundState('第一轮问题')
      const before = useRoundtableStore.getState()
      expect(before.rounds).toHaveLength(0)
      expect(before.roundIndex).toBe(0)

      useRoundtableStore.getState().archiveCurrentRoundAndReset('第二轮追问')
      const after = useRoundtableStore.getState()

      expect(after.rounds).toHaveLength(1)
      const snap = after.rounds[0]
      expect(snap.roundIndex).toBe(0)
      expect(snap.question).toBe('第一轮问题')
      expect(snap.moderator).toEqual(MOCK_MODERATOR)
      expect(snap.moderatorThinking).toBe('三方共识：先被看见。')
      expect(snap.phase2).toHaveLength(3)
      expect(snap.phase2[0].text).toContain('phase2 交叉回应')

      // 当前轮字段被重置
      expect(after.roundIndex).toBe(1)
      expect(after.question).toBe('第二轮追问')
      expect(after.currentPhase).toBe('setup')
      expect(after.moderator).toBeNull()
      expect(after.moderatorThinking).toBeNull()
      expect(after.phase1Agents).toHaveLength(3)
      expect(after.phase1Agents.every((a) => a.status === 'pending' && a.text === '')).toBe(true)
      expect(after.phase2Agents.every((a) => a.status === 'pending' && a.text === '')).toBe(true)
    })

    it('bumps streamNonce so hook can re-subscribe SSE', () => {
      primeDoneRoundState('Q1')
      const before = useRoundtableStore.getState().streamNonce
      useRoundtableStore.getState().archiveCurrentRoundAndReset('Q2')
      const after = useRoundtableStore.getState().streamNonce
      expect(after).toBe(before + 1)
    })

    it('多次 archive 后 rounds 按 roundIndex 单调递增', () => {
      primeDoneRoundState('Q1')
      useRoundtableStore.getState().archiveCurrentRoundAndReset('Q2')
      // 手工填一轮再归档
      const s = useRoundtableStore.getState()
      for (const pid of ['neutral', 'supportive', 'eft'] as const) {
        s.setAgentStatus('phase2', pid, 'done')
        s.appendAgentText('phase2', pid, `${pid} r2`)
      }
      s.setModerator(MOCK_MODERATOR)
      s.advancePhase('done')
      useRoundtableStore.getState().archiveCurrentRoundAndReset('Q3')

      const { rounds, roundIndex } = useRoundtableStore.getState()
      expect(rounds).toHaveLength(2)
      expect(rounds.map((r) => r.roundIndex)).toEqual([0, 1])
      expect(roundIndex).toBe(2)
    })
  })

  describe('hydrateFromDetail', () => {
    it('从 backend detail 恢复完整状态（含 rounds）', () => {
      const detail = {
        id: 'rt_hydrate_1',
        question: '当前轮问题',
        phase: 'done' as const,
        phase1: [
          { persona_id: 'neutral', status: 'done' as const, text: 'n1', confidence: 0.8, error: null },
          { persona_id: 'supportive', status: 'done' as const, text: 's1', confidence: 0.75, error: null },
          { persona_id: 'eft', status: 'done' as const, text: 'e1', confidence: 0.9, error: null },
        ],
        phase2: [
          { persona_id: 'neutral', status: 'done' as const, text: 'n2', confidence: 0.8, error: null },
          { persona_id: 'supportive', status: 'done' as const, text: 's2', confidence: 0.75, error: null },
          { persona_id: 'eft', status: 'done' as const, text: 'e2', confidence: 0.9, error: null },
        ],
        moderator: MOCK_MODERATOR,
        moderator_thinking: 'thinking text',
        rounds: [
          {
            round_index: 0,
            question: '历史第 1 轮问题',
            phase1: [
              { persona_id: 'neutral', status: 'done' as const, text: 'r0n1', confidence: 0.7, error: null },
            ],
            phase2: [
              { persona_id: 'neutral', status: 'done' as const, text: 'r0n2', confidence: 0.7, error: null },
            ],
            moderator: MOCK_MODERATOR,
            moderator_thinking: 'r0 thinking',
            created_at: '2026-04-20T10:00:00',
            completed_at: '2026-04-20T10:05:00',
          },
        ],
        round_index: 1,
        personas: ['neutral', 'supportive', 'eft'],
      }

      useRoundtableStore.getState().hydrateFromDetail(detail)
      const s = useRoundtableStore.getState()

      expect(s.sessionId).toBe('rt_hydrate_1')
      expect(s.question).toBe('当前轮问题')
      expect(s.currentPhase).toBe('done')
      expect(s.selectedPersonas).toEqual(['neutral', 'supportive', 'eft'])
      expect(s.phase1Agents).toHaveLength(3)
      expect(s.phase1Agents[0].text).toBe('n1')
      expect(s.phase1Agents[0].confidence).toBe(0.8)
      expect(s.moderator).toEqual(MOCK_MODERATOR)
      expect(s.moderatorThinking).toBe('thinking text')
      expect(s.rounds).toHaveLength(1)
      expect(s.rounds[0].question).toBe('历史第 1 轮问题')
      expect(s.rounds[0].moderatorThinking).toBe('r0 thinking')
      expect(s.rounds[0].createdAt).toBe('2026-04-20T10:00:00')
      expect(s.roundIndex).toBe(1)
    })

    it('hydrate 不 bump streamNonce（首屏不重连）', () => {
      // set streamNonce to a known value
      useRoundtableStore.setState({ streamNonce: 42 })
      useRoundtableStore.getState().hydrateFromDetail({
        id: 'rt_x',
        question: 'Q',
        phase: 'done',
        phase1: [],
        phase2: [],
        moderator: null,
        moderator_thinking: '',
        rounds: [],
        round_index: 0,
        personas: ['neutral', 'supportive', 'eft'],
      })
      expect(useRoundtableStore.getState().streamNonce).toBe(42)
    })
  })

  describe('resetSession', () => {
    it('清空 rounds / roundIndex / streamNonce', () => {
      primeDoneRoundState('Q1')
      useRoundtableStore.getState().archiveCurrentRoundAndReset('Q2')
      expect(useRoundtableStore.getState().rounds.length).toBeGreaterThan(0)

      useRoundtableStore.getState().resetSession()
      const s = useRoundtableStore.getState()
      expect(s.rounds).toEqual([])
      expect(s.roundIndex).toBe(0)
      expect(s.streamNonce).toBe(0)
      expect(s.sessionId).toBeNull()
      expect(s.currentPhase).toBe('setup')
    })
  })

  describe('startSession', () => {
    it('重置多轮字段为新 session 起点', () => {
      // 先制造一些多轮垃圾状态
      useRoundtableStore.setState({
        rounds: [
          {
            roundIndex: 0,
            question: 'old',
            phase1: [],
            phase2: [],
            moderator: null,
            moderatorThinking: '',
            createdAt: 'old',
            completedAt: 'old',
          },
        ],
        roundIndex: 5,
        streamNonce: 99,
      })
      useRoundtableStore.getState().setPersonas(['neutral', 'supportive', 'eft'])
      useRoundtableStore.getState().startSession('rt_new')
      const s = useRoundtableStore.getState()
      expect(s.rounds).toEqual([])
      expect(s.roundIndex).toBe(0)
      expect(s.streamNonce).toBe(0)
      expect(s.sessionId).toBe('rt_new')
      expect(s.currentPhase).toBe('phase1')
    })
  })

  // ═══════════════════════════════════════════════════════════════════
  // Day 7 · D7.1.f · 只读快照模式（isReadOnlySnapshot）
  // ═══════════════════════════════════════════════════════════════════

  describe('isReadOnlySnapshot (Day 7 · D7.1.f)', () => {
    const emptyDetailBase = {
      id: 'rt_readonly',
      question: 'Q',
      phase1: [],
      phase2: [],
      moderator: null,
      moderator_thinking: '',
      rounds: [],
      round_index: 0,
      personas: ['neutral', 'supportive', 'eft'] as string[],
    }

    it('默认初始状态为 false（正常新 session）', () => {
      expect(useRoundtableStore.getState().isReadOnlySnapshot).toBe(false)
    })

    it.each(['phase1', 'phase2', 'phase3'] as const)(
      'hydrateFromDetail(phase="%s") → isReadOnlySnapshot = true',
      (phase) => {
        useRoundtableStore.getState().hydrateFromDetail({
          ...emptyDetailBase,
          phase,
        })
        expect(useRoundtableStore.getState().isReadOnlySnapshot).toBe(true)
        expect(useRoundtableStore.getState().currentPhase).toBe(phase)
      },
    )

    it('hydrateFromDetail(phase="done") → isReadOnlySnapshot = false', () => {
      useRoundtableStore.getState().hydrateFromDetail({
        ...emptyDetailBase,
        phase: 'done',
      })
      expect(useRoundtableStore.getState().isReadOnlySnapshot).toBe(false)
    })

    it('hydrateFromDetail(phase="setup") → isReadOnlySnapshot = false（防御性）', () => {
      useRoundtableStore.getState().hydrateFromDetail({
        ...emptyDetailBase,
        phase: 'setup',
      })
      expect(useRoundtableStore.getState().isReadOnlySnapshot).toBe(false)
    })

    it('startSession 把 isReadOnlySnapshot 重置为 false', () => {
      // 先 hydrate 一个 phase1 session → 进入只读
      useRoundtableStore.getState().hydrateFromDetail({
        ...emptyDetailBase,
        phase: 'phase1',
      })
      expect(useRoundtableStore.getState().isReadOnlySnapshot).toBe(true)

      // startSession 应重置
      useRoundtableStore.getState().setPersonas(['neutral', 'supportive', 'eft'])
      useRoundtableStore.getState().startSession('rt_new')
      expect(useRoundtableStore.getState().isReadOnlySnapshot).toBe(false)
    })

    it('resetSession 把 isReadOnlySnapshot 重置为 false', () => {
      useRoundtableStore.getState().hydrateFromDetail({
        ...emptyDetailBase,
        phase: 'phase2',
      })
      expect(useRoundtableStore.getState().isReadOnlySnapshot).toBe(true)

      useRoundtableStore.getState().resetSession()
      expect(useRoundtableStore.getState().isReadOnlySnapshot).toBe(false)
    })

    it('archiveCurrentRoundAndReset 把 isReadOnlySnapshot 重置为 false（新一轮必须能订阅 SSE）', () => {
      // 先模拟"历史 done session hydrate"的正常场景（phase='done' → isReadOnlySnapshot=false）
      primeDoneRoundState('Q1')
      // 但有人手动把 isReadOnlySnapshot 弄成 true · 确认 archive 会强制重置
      useRoundtableStore.setState({ isReadOnlySnapshot: true })

      useRoundtableStore.getState().archiveCurrentRoundAndReset('Q2')
      expect(useRoundtableStore.getState().isReadOnlySnapshot).toBe(false)
      // 顺便确认 streamNonce bump（新一轮能重新订阅）
      expect(useRoundtableStore.getState().streamNonce).toBeGreaterThan(0)
    })
  })
})
