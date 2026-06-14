/**
 * D5.7 · 档 1 · 圆桌讨论 Mobile 375px 视口 + 暗色模式集成测试（Vitest + RTL）
 *
 * 目标：
 *   验证 RoundtableSessionPage 在小屏（375px）+ 暗色模式下：
 *     ① agent grid 使用 mobile-first `grid-cols-1 lg:grid-cols-3`（默认单列 · 大屏三列）
 *     ② reduced-motion 友好 · 不崩
 *     ③ 暗色模式 class 应用后组件可正常渲染（不因缺 var 崩溃）
 *     ④ 只读快照 banner 在暗色/移动端样式生效
 *
 * jsdom 不做真实 layout · 所以这里检查的是 DOM className 的 TailwindCSS 类·
 * 说明"mobile-first + lg breakpoint"的响应式契约被保留在源代码里。
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

function mockViewport(width: number, height = 800) {
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: width })
  Object.defineProperty(window, 'innerHeight', { configurable: true, value: height })
  window.dispatchEvent(new Event('resize'))
}

describe('D5.7 · Mobile 375px 视口 + 暗色模式', () => {
  beforeEach(() => {
    useRoundtableStore.getState().resetSession()
    useRoundtableStore.getState().resetSetup()
    useRoundtableStore.setState({
      selectedPersonas: [...PERSONAS],
      question: '我男友冷战三天',
    })
    useRoundtableStore.getState().startSession('rt_e2e_mobile')
    mockViewport(375)
  })

  afterEach(() => {
    document.body.innerHTML = ''
    document.documentElement.classList.remove('dark')
    mockViewport(1280)
  })

  it('phase1 agent grid · 使用 mobile-first grid-cols-1 + lg:grid-cols-3', () => {
    const { container } = render(<RoundtableSessionPage />)
    // 触发 phase1 出现 3 个 agent 卡
    const store = useRoundtableStore.getState()
    act(() => {
      for (const pid of PERSONAS) {
        dispatchRoundtableEvent(
          { type: 'agent_chunk', agent_id: pid, phase: 'phase1', delta: `${pid}` },
          store,
        )
      }
    })

    // 找到任一带 mobile-first grid 的容器
    const gridCandidates = container.querySelectorAll('.grid')
    const gotMobileFirst = Array.from(gridCandidates).some((el) => {
      const cls = el.className
      return cls.includes('grid-cols-1') && cls.includes('lg:grid-cols-3')
    })
    expect(gotMobileFirst).toBe(true)
  })

  it('phase2 进入后 · phase1 grid 仍保持响应式类·只是被淑化', () => {
    const store = useRoundtableStore.getState()
    act(() => {
      dispatchRoundtableEvent({ type: 'phase_advance', phase: 'phase2' }, store)
    })
    const { container } = render(<RoundtableSessionPage />)
    // aria-label 可定位到 phase1 的淑化容器
    const phase1Wrapper = container.querySelector('[aria-label*="第一阶段已完成"]')
    expect(phase1Wrapper).not.toBeNull()
    // 容器本身是响应式 grid
    const cls = (phase1Wrapper as HTMLElement).className
    expect(cls).toMatch(/grid-cols-1/)
    expect(cls).toMatch(/lg:grid-cols-3/)
  })

  it('暗色模式 class · document 应用后 · SessionPage 仍能正常渲染', () => {
    document.documentElement.classList.add('dark')
    expect(document.documentElement.classList.contains('dark')).toBe(true)

    const { container } = render(<RoundtableSessionPage />)
    // 不崩 · 关键文案仍可见
    expect(screen.getByText(/男友冷战三天/)).toBeInTheDocument()
    // 至少一个 agent grid 存在
    expect(container.querySelectorAll('.grid').length).toBeGreaterThan(0)
  })

  it('只读快照 banner · 在 mobile + dark 双条件下仍可见 · 有响应式 class', () => {
    useRoundtableStore.setState({
      isReadOnlySnapshot: true,
      currentPhase: 'phase2',
    })
    document.documentElement.classList.add('dark')
    const { container } = render(<RoundtableSessionPage />)

    // banner 容器存在且用了 dark: 变体（语言无关断言）
    const banner = container.querySelector('[role="status"]')
    expect(banner).not.toBeNull()
    expect((banner as HTMLElement).className).toMatch(/dark:/)
  })

  it('narrow 视口下 · 顶部 nav 按钮可渲染（responsive 无 crash）', () => {
    mockViewport(320) // 极小屏压测
    render(<RoundtableSessionPage />)
    // 返回按钮存在（语言无关断言）
    expect(screen.getByRole('button', { name: /Back|Setup|回到/ })).toBeInTheDocument()
  })
})
