/**
 * Day 5 · D · Thinking UI 纯函数 & hook 单测
 *
 * 覆盖：
 * - `getThinkingLabel(elapsed)` · 5 阶段文案边界
 * - `useElapsedSeconds(active)` · 激活/挂起 500ms 计时
 */
import { describe, expect, it, beforeEach, afterEach, vi } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import {
  getThinkingLabel,
  useElapsedSeconds,
} from '@/lib/thinking-ui'

describe('getThinkingLabel', () => {
  it.each<[number, string]>([
    [0, '正在思考'],
    [2, '正在思考'],
    [3, '深度分析中'],
    [7, '深度分析中'],
    [8, '正在深入推敲'],
    [14, '正在深入推敲'],
    [15, '仍在思考中，请稍等'],
    [24, '仍在思考中，请稍等'],
    [25, '正在完成最后的整合'],
    [60, '正在完成最后的整合'],
    [9999, '正在完成最后的整合'],
  ])('elapsed=%i → %s', (elapsed, expected) => {
    expect(getThinkingLabel(elapsed)).toBe(expected)
  })

  it('negative elapsed 应落入第一段（防御性）', () => {
    expect(getThinkingLabel(-1)).toBe('正在思考')
  })
})

describe('useElapsedSeconds', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('active=false 时始终返回 0', () => {
    const { result } = renderHook(() => useElapsedSeconds(false))
    expect(result.current).toBe(0)
    act(() => {
      vi.advanceTimersByTime(5000)
    })
    expect(result.current).toBe(0)
  })

  it('active=true 时 500ms tick 递增', () => {
    const { result } = renderHook(() => useElapsedSeconds(true))
    // 初始 tick
    expect(result.current).toBe(0)

    act(() => {
      vi.advanceTimersByTime(1000)
    })
    expect(result.current).toBe(1)

    act(() => {
      vi.advanceTimersByTime(2500)
    })
    expect(result.current).toBe(3)

    act(() => {
      vi.advanceTimersByTime(11500)
    })
    expect(result.current).toBe(15)
  })

  it('active 从 true 切到 false 时立即归零', () => {
    const { result, rerender } = renderHook(
      ({ on }: { on: boolean }) => useElapsedSeconds(on),
      { initialProps: { on: true } },
    )
    act(() => {
      vi.advanceTimersByTime(4000)
    })
    expect(result.current).toBe(4)

    rerender({ on: false })
    // useEffect 的清理 + 重新运行会把 elapsed 置 0
    expect(result.current).toBe(0)
  })

  it('unmount 后 interval 被清理（不泄漏）', () => {
    const clearSpy = vi.spyOn(window, 'clearInterval')
    const { unmount } = renderHook(() => useElapsedSeconds(true))
    unmount()
    expect(clearSpy).toHaveBeenCalled()
  })
})
