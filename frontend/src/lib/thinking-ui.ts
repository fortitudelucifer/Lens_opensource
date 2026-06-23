/**
 * Thinking UI 纯工具：elapsed 秒表 hook + 动态文案。
 *
 * 独立文件便于：
 * 1. 跨组件复用（未来给 ModeratorSection 也加渐进文案）
 * 2. 单测不依赖组件文件
 * 3. 满足 React Fast Refresh 「文件只导出组件」约束
 */
import { useEffect, useState } from 'react'

/** 只在 active=true 时启动 500ms 秒表；active 切 false 时归零 */
export function useElapsedSeconds(active: boolean): number {
  const [elapsed, setElapsed] = useState(0)
  useEffect(() => {
    if (!active) return
    const start = Date.now()
    const tick = () => setElapsed(Math.floor((Date.now() - start) / 1000))
    const id = window.setInterval(tick, 500)
    return () => window.clearInterval(id)
  }, [active])
  return active ? elapsed : 0
}

/**
 * 根据等待时长给出渐进式文案。
 * 让用户理解真 LLM 8-15s 首 token 是常态，降低「卡死了吗」的焦虑。
 */
export function getThinkingLabel(elapsed: number): string {
  if (elapsed < 3) return '正在思考'
  if (elapsed < 8) return '深度分析中'
  if (elapsed < 15) return '正在深入推敲'
  if (elapsed < 25) return '仍在思考中，请稍等'
  return '正在完成最后的整合'
}
