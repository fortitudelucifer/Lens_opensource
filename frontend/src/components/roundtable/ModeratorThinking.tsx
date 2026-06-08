/**
 * Moderator「综合思考」段（Day 5 方案① · 2026-04-19）
 *
 * 职责：
 *   - 在 phase3 / done 阶段展示 LLM Moderator 写的一段自然语言综合思考
 *   - 用打字机效果（"假流式"）让用户看到"思考过程"
 *   - 最终 moderator 6 段 JSON 到达后，1.2s 延迟自动折叠成 "▶ 查看综合过程" 按钮
 *   - 点击按钮可再次展开（心理场景用户常需要回看"老师当时怎么想的"）
 *
 * 受控方式：
 *   - `text` 从 store.moderatorThinking 传入；null/空串时组件不渲染
 *   - `moderatorDone` 表示最终 JSON 已到达，用来触发自动折叠
 */

import { useEffect, useRef, useState } from 'react'
import { Brain, ChevronRight } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useReducedMotion } from '@/hooks/useReducedMotion'

interface ModeratorThinkingProps {
  /** 思考段全文（backend 一次性塞入，组件内做打字机） */
  text: string | null
  /** 最终 Moderator JSON 是否已到达 · 到达后若打字机也完成则自动折叠 */
  moderatorDone: boolean
  className?: string
}

/** 打字机效果 · 返回当前应显示的前缀和是否打字完毕
 *
 * D5.4 / D7.1.i · `instant=true` 时跳过 setInterval，直接全文显示
 * 用于 `prefers-reduced-motion: reduce` 场景（OS 或用户偏好关闭动画）
 */
function useTypewriter(full: string, speedMs = 28, instant = false): { shown: string; done: boolean } {
  const [shown, setShown] = useState('')
  const [done, setDone] = useState(false)
  useEffect(() => {
    if (!full) {
      setShown('')
      setDone(true)
      return
    }
    // 辅助功能模式：直接全文到达，跳过打字机
    if (instant) {
      setShown(full)
      setDone(true)
      return
    }
    setShown('')
    setDone(false)
    let i = 0
    const id = window.setInterval(() => {
      i += 1
      if (i >= full.length) {
        setShown(full)
        setDone(true)
        window.clearInterval(id)
      } else {
        setShown(full.slice(0, i))
      }
    }, speedMs)
    return () => window.clearInterval(id)
  }, [full, speedMs, instant])
  return { shown, done }
}

export function ModeratorThinking({
  text,
  moderatorDone,
  className,
}: ModeratorThinkingProps) {
  // D5.4 / D7.1.i · reduced-motion 用户跳过打字机 & 自动折叠延迟，直接到终态
  const reducedMotion = useReducedMotion()
  const { shown, done: typedDone } = useTypewriter(text ?? '', 28, reducedMotion)
  const [collapsed, setCollapsed] = useState(false)
  /** 记录「是否用户手动展开过」——手动展开后就不再自动折叠，避免抖动 */
  const userOverrideRef = useRef(false)

  // moderator 到达 + 打字机结束 → 1.2s 延迟自动折叠（给用户读完时间）
  // reduced-motion 下直接折叠，不等 1.2s
  useEffect(() => {
    if (!text || userOverrideRef.current) return
    if (moderatorDone && typedDone && !collapsed) {
      if (reducedMotion) {
        setCollapsed(true)
        return
      }
      const id = window.setTimeout(() => {
        if (!userOverrideRef.current) setCollapsed(true)
      }, 1200)
      return () => window.clearTimeout(id)
    }
  }, [moderatorDone, typedDone, text, collapsed, reducedMotion])

  if (!text) return null

  const handleToggle = () => {
    userOverrideRef.current = true
    setCollapsed((c) => !c)
  }

  if (collapsed) {
    return (
      <button
        type="button"
        onClick={handleToggle}
        className={cn(
          'mp-fade-up group flex items-center gap-1.5 self-start rounded-full',
          'border border-border/60 bg-card/60 px-3 py-1.5',
          'text-xs text-muted-foreground hover:text-foreground hover:bg-muted/60',
          'transition-colors',
          className,
        )}
        aria-label="展开查看综合思考过程"
      >
        <ChevronRight
          className="h-3 w-3 transition-transform group-hover:translate-x-0.5"
          strokeWidth={2.2}
          aria-hidden="true"
        />
        <Brain className="h-3 w-3" strokeWidth={2} aria-hidden="true" />
        <span>查看综合思考过程</span>
      </button>
    )
  }

  const isTyping = !typedDone

  return (
    <section
      className={cn(
        'mp-fade-up relative flex flex-col gap-2 rounded-2xl border p-5',
        'border-amber-200/50 bg-amber-50/40 dark:border-amber-400/20 dark:bg-amber-950/15',
        className,
      )}
      role="region"
      aria-label="Moderator 综合思考过程"
      aria-live="polite"
    >
      <header className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <div
            className={cn(
              'flex h-7 w-7 shrink-0 items-center justify-center rounded-lg',
              'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300',
            )}
          >
            <Brain className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />
          </div>
          <div className="flex flex-col gap-0.5">
            <h3 className="text-sm font-semibold text-amber-900 dark:text-amber-200">
              {isTyping ? '正在整理三位顾问的观点…' : '综合思考'}
            </h3>
            <p className="text-[11px] text-muted-foreground">
              {isTyping
                ? '看到共同点、张力与最需要被接住的需求'
                : '最终综合已展开在下方 · 点击右上可折叠'}
            </p>
          </div>
        </div>
        {/* moderator 已完成时才允许手动折叠（打字还没完时折叠会丢内容） */}
        {moderatorDone && (
          <button
            type="button"
            onClick={handleToggle}
            className="text-[11px] text-muted-foreground hover:text-foreground transition-colors"
            aria-label="折叠综合思考过程"
          >
            折叠 ▲
          </button>
        )}
      </header>

      <p className="text-sm leading-[1.75] text-foreground/85 whitespace-pre-wrap break-words">
        {shown}
        {isTyping && (
          <span
            className="ml-0.5 inline-block h-4 w-0.5 align-middle animate-pulse bg-amber-500 dark:bg-amber-300"
            aria-hidden="true"
          />
        )}
      </p>
    </section>
  )
}
