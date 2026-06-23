/**
 * useReducedMotion · 检测 OS / 浏览器「减少动态效果」设置（D5.4 / D7.1.i · 2026-04-23）
 *
 * 用途：
 *   - JS 侧联动 CSS 的 `prefers-reduced-motion` · 跳过打字机 / sleep / smooth scroll
 *   - CSS 只能降级「CSS 动画」，JS 驱动的 setTimeout/setInterval 必须靠这个 hook
 *
 * 使用：
 *   const reduced = useReducedMotion()
 *   if (reduced) {
 *     // 直接显示全文，跳过打字机
 *   } else {
 *     // 用打字机效果
 *   }
 *
 * 兼容性：
 *   - SSR 友好：window 不存在时默认返回 false
 *   - 事件订阅：使用 addEventListener/removeEventListener（现代浏览器）
 *     对 Safari 14- 等老版本 fallback 到 addListener/removeListener
 */
import { useEffect, useState } from 'react'

const MEDIA_QUERY = '(prefers-reduced-motion: reduce)'

/** 读当前值 · SSR 或 matchMedia 缺失时返回 false */
function getInitialPreference(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return false
  }
  return window.matchMedia(MEDIA_QUERY).matches
}

export function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState<boolean>(getInitialPreference)

  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
      return
    }
    const mql = window.matchMedia(MEDIA_QUERY)

    const handleChange = (e: MediaQueryListEvent) => setReduced(e.matches)

    // 现代浏览器用 addEventListener；老版本 Safari < 14 fallback（addListener 已废弃但仍有类型）
    if (typeof mql.addEventListener === 'function') {
      mql.addEventListener('change', handleChange)
      return () => mql.removeEventListener('change', handleChange)
    }
    mql.addListener(handleChange)
    return () => mql.removeListener(handleChange)
  }, [])

  return reduced
}

export default useReducedMotion
