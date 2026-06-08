/**
 * D7.1.j++ · RoundtableRouter 路由逻辑回归单测（2026-04-30）
 *
 * 背景：
 *   灰度前实战发现 · 用户点击 FollowUpComposer 的"追问"按钮后：
 *   1. archiveCurrentRoundAndReset 把 currentPhase 设为 'setup' 以重置当前轮 UI
 *   2. 旧版 RoundtableRouter 只按 `currentPhase === 'setup'` 跳回 RoundtablePage
 *   3. RoundtableSessionPage 被 unmount → useRoundtableStream cleanup → SSE 关闭
 *   4. 第 2 轮 phase pipeline 永远不启动（backend 没收到新 GET /stream）
 *
 * 修复：增加 sessionId 判断 · sessionId 存在时保持在 SessionPage。
 *
 * 本测试覆盖 4 种路由转换：
 *   - 初始（无 sessionId + setup）→ RoundtablePage
 *   - 开始 session（startSession 后 phase1 + sessionId）→ SessionPage
 *   - continue 新一轮（archiveCurrentRoundAndReset 后 phase=setup + sessionId 仍存在）→ SessionPage（修复关键）
 *   - resetSession（清空 sessionId + setup）→ RoundtablePage
 */

import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// ── Mock RoundtablePage / RoundtableSessionPage · 用 data-testid 区分 ──
vi.mock('../pages/RoundtablePage', () => ({
  RoundtablePage: () => <div data-testid="roundtable-setup-page">SETUP_PAGE</div>,
}))
vi.mock('../pages/RoundtableSessionPage', () => ({
  RoundtableSessionPage: () => <div data-testid="roundtable-session-page">SESSION_PAGE</div>,
}))

// 只 import _RoundtableRouter · 避免 render 整个 App
import { _RoundtableRouter } from '../App'
import { useRoundtableStore } from '../stores/useRoundtableStore'

const MOCK_MODERATOR = {
  seen: '看到你。',
  angles: ['中立：拆事实', '支持：接情绪', 'EFT：依恋'],
  tries: ['写日记', '邀请对话', '自我照顾'],
  doubts: ['他会回应吗？', '还有未说的细节？'],
  lens: '你不是一个人。',
  limit: '非诊断性工具。',
}

describe('RoundtableRouter · D7.1.j++ 路由逻辑', () => {
  beforeEach(() => {
    // 每个 case 完全复位
    useRoundtableStore.getState().resetSession()
    useRoundtableStore.getState().resetSetup()
  })

  afterEach(() => {
    // 清 DOM（避免跨 case 污染）
    document.body.innerHTML = ''
  })

  it('初始状态（sessionId=null, phase=setup）→ 渲染 RoundtablePage', () => {
    render(<_RoundtableRouter onNavigateToChat={() => {}} />)
    expect(screen.getByTestId('roundtable-setup-page')).toBeInTheDocument()
    expect(screen.queryByTestId('roundtable-session-page')).not.toBeInTheDocument()
  })

  it('startSession 后（sessionId 存在, phase=phase1）→ 渲染 SessionPage', () => {
    act(() => {
      useRoundtableStore.getState().setPersonas(['neutral', 'supportive', 'eft'])
      useRoundtableStore.getState().startSession('rt_test_abc')
    })
    render(<_RoundtableRouter onNavigateToChat={() => {}} />)
    expect(screen.getByTestId('roundtable-session-page')).toBeInTheDocument()
    expect(screen.queryByTestId('roundtable-setup-page')).not.toBeInTheDocument()
  })

  it('continue 新一轮 · archiveCurrentRoundAndReset 后（sessionId 仍存在 + phase=setup）→ 仍在 SessionPage（D7.1.j++ 关键修复）', () => {
    // 模拟已完成第 1 轮
    act(() => {
      const s = useRoundtableStore.getState()
      s.setPersonas(['neutral', 'supportive', 'eft'])
      s.startSession('rt_test_abc')
      for (const pid of ['neutral', 'supportive', 'eft'] as const) {
        s.setAgentStatus('phase1', pid, 'done')
        s.appendAgentText('phase1', pid, `${pid} phase1`)
        s.setAgentStatus('phase2', pid, 'done')
        s.appendAgentText('phase2', pid, `${pid} phase2`)
      }
      s.setModerator(MOCK_MODERATOR)
      s.advancePhase('done')
      // 关键：模拟用户点"追问"
      s.archiveCurrentRoundAndReset('第二轮追问的问题')
    })

    const state = useRoundtableStore.getState()
    expect(state.sessionId).toBe('rt_test_abc') // sessionId 保留
    expect(state.currentPhase).toBe('setup') // phase 被重置
    expect(state.streamNonce).toBeGreaterThan(0) // streamNonce 已 bump

    render(<_RoundtableRouter onNavigateToChat={() => {}} />)

    // D7.1.j++ 核心断言：此时不能跳回 setup 页
    expect(screen.getByTestId('roundtable-session-page')).toBeInTheDocument()
    expect(screen.queryByTestId('roundtable-setup-page')).not.toBeInTheDocument()
  })

  it('resetSession 后（sessionId=null + phase=setup）→ 回到 RoundtablePage', () => {
    // 先起一个 session · 再 reset
    act(() => {
      useRoundtableStore.getState().setPersonas(['neutral', 'supportive', 'eft'])
      useRoundtableStore.getState().startSession('rt_test_abc')
      useRoundtableStore.getState().resetSession()
    })

    const state = useRoundtableStore.getState()
    expect(state.sessionId).toBeNull()
    expect(state.currentPhase).toBe('setup')

    render(<_RoundtableRouter onNavigateToChat={() => {}} />)
    expect(screen.getByTestId('roundtable-setup-page')).toBeInTheDocument()
    expect(screen.queryByTestId('roundtable-session-page')).not.toBeInTheDocument()
  })

  it('done 状态（sessionId 存在, phase=done）→ 渲染 SessionPage', () => {
    act(() => {
      useRoundtableStore.getState().setPersonas(['neutral', 'supportive', 'eft'])
      useRoundtableStore.getState().startSession('rt_test_abc')
      useRoundtableStore.getState().advancePhase('done')
    })
    render(<_RoundtableRouter onNavigateToChat={() => {}} />)
    expect(screen.getByTestId('roundtable-session-page')).toBeInTheDocument()
  })

  it('phase2 流中（sessionId 存在, phase=phase2）→ 渲染 SessionPage', () => {
    act(() => {
      useRoundtableStore.getState().setPersonas(['neutral', 'supportive', 'eft'])
      useRoundtableStore.getState().startSession('rt_test_abc')
      useRoundtableStore.getState().advancePhase('phase2')
    })
    render(<_RoundtableRouter onNavigateToChat={() => {}} />)
    expect(screen.getByTestId('roundtable-session-page')).toBeInTheDocument()
  })
})
