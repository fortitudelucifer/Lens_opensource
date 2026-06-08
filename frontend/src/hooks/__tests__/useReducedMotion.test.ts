/**
 * useReducedMotion · vitest
 *
 * 覆盖：
 *   - 初始 matchMedia → initial boolean 被正确读取
 *   - matchMedia 不存在时降级为 false（SSR / old browser）
 *   - mql 的 change 事件触发后 hook 重新返回新值
 *   - unmount 时正确清理订阅
 */
import { describe, it, expect, afterEach, vi } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import { useReducedMotion } from '../useReducedMotion'

type Handler = (e: MediaQueryListEvent) => void

function createMockMql(initial: boolean) {
  const handlers = new Set<Handler>()
  const mql = {
    matches: initial,
    media: '(prefers-reduced-motion: reduce)',
    onchange: null,
    addEventListener: vi.fn((_: string, h: Handler) => handlers.add(h)),
    removeEventListener: vi.fn((_: string, h: Handler) => handlers.delete(h)),
    // legacy API（保留以测试兼容分支）
    addListener: vi.fn((h: Handler) => handlers.add(h)),
    removeListener: vi.fn((h: Handler) => handlers.delete(h)),
    dispatchEvent: vi.fn(() => true),
    // helper：测试里用来模拟用户切换系统偏好
    __fire(next: boolean) {
      this.matches = next
      handlers.forEach((h) => h({ matches: next } as MediaQueryListEvent))
    },
  }
  return mql
}

describe('useReducedMotion', () => {
  const originalMatchMedia = window.matchMedia

  afterEach(() => {
    Object.defineProperty(window, 'matchMedia', {
      configurable: true,
      writable: true,
      value: originalMatchMedia,
    })
  })

  describe('初始值读取', () => {
    it('matchMedia → matches=false 时返回 false', () => {
      const mql = createMockMql(false)
      window.matchMedia = vi.fn().mockReturnValue(mql) as unknown as typeof window.matchMedia
      const { result } = renderHook(() => useReducedMotion())
      expect(result.current).toBe(false)
    })

    it('matchMedia → matches=true 时返回 true', () => {
      const mql = createMockMql(true)
      window.matchMedia = vi.fn().mockReturnValue(mql) as unknown as typeof window.matchMedia
      const { result } = renderHook(() => useReducedMotion())
      expect(result.current).toBe(true)
    })

    it('window.matchMedia 不存在时降级为 false（SSR 兼容）', () => {
      // @ts-expect-error · 故意删除 matchMedia 模拟老环境
      delete window.matchMedia
      const { result } = renderHook(() => useReducedMotion())
      expect(result.current).toBe(false)
    })
  })

  describe('change 事件响应', () => {
    it('mql.__fire(true) 触发后 hook 返回 true', () => {
      const mql = createMockMql(false)
      window.matchMedia = vi.fn().mockReturnValue(mql) as unknown as typeof window.matchMedia

      const { result } = renderHook(() => useReducedMotion())
      expect(result.current).toBe(false)

      act(() => {
        mql.__fire(true)
      })
      expect(result.current).toBe(true)
    })

    it('连续切换 false→true→false 都被正确追踪', () => {
      const mql = createMockMql(false)
      window.matchMedia = vi.fn().mockReturnValue(mql) as unknown as typeof window.matchMedia

      const { result } = renderHook(() => useReducedMotion())

      act(() => mql.__fire(true))
      expect(result.current).toBe(true)

      act(() => mql.__fire(false))
      expect(result.current).toBe(false)

      act(() => mql.__fire(true))
      expect(result.current).toBe(true)
    })
  })

  describe('订阅清理', () => {
    it('unmount 时调用 removeEventListener（防止内存泄漏）', () => {
      const mql = createMockMql(false)
      window.matchMedia = vi.fn().mockReturnValue(mql) as unknown as typeof window.matchMedia

      const { unmount } = renderHook(() => useReducedMotion())
      expect(mql.addEventListener).toHaveBeenCalledTimes(1)

      unmount()
      expect(mql.removeEventListener).toHaveBeenCalledTimes(1)
    })

    it('Safari < 14 老 API fallback · unmount 调用 removeListener', () => {
      const mql = createMockMql(false)
      // 模拟老 Safari：没有 addEventListener
      // @ts-expect-error · 故意置为 undefined 测 fallback 分支
      mql.addEventListener = undefined
      window.matchMedia = vi.fn().mockReturnValue(mql) as unknown as typeof window.matchMedia

      const { unmount } = renderHook(() => useReducedMotion())
      expect(mql.addListener).toHaveBeenCalledTimes(1)

      unmount()
      expect(mql.removeListener).toHaveBeenCalledTimes(1)
    })
  })

  describe('多实例隔离', () => {
    it('两个组件分别订阅 · 状态互不影响', () => {
      const mql = createMockMql(false)
      window.matchMedia = vi.fn().mockReturnValue(mql) as unknown as typeof window.matchMedia

      const hook1 = renderHook(() => useReducedMotion())
      const hook2 = renderHook(() => useReducedMotion())

      expect(hook1.result.current).toBe(false)
      expect(hook2.result.current).toBe(false)

      act(() => mql.__fire(true))

      expect(hook1.result.current).toBe(true)
      expect(hook2.result.current).toBe(true)

      hook1.unmount()
      // hook2 的订阅应当仍在
      expect(mql.removeEventListener).toHaveBeenCalledTimes(1)
    })
  })
})
