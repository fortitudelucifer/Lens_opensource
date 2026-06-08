/**
 * 打字中动画（3 个 breathing dots）
 *
 * 用 CSS keyframe `mp-breathe`（已在 `index.css` 定义）避免 Framer Motion 依赖。
 * 3 点 stagger 节奏通过 `animationDelay` 实现。
 */

import { cn } from '@/lib/utils'

interface TypingDotsProps {
  /** 点的颜色 class，如 `bg-emerald-500` */
  colorClass?: string
  className?: string
}

export function TypingDots({ colorClass = 'bg-muted-foreground', className }: TypingDotsProps) {
  return (
    <div
      className={cn('inline-flex items-center gap-1', className)}
      role="status"
      aria-label="正在输入"
    >
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className={cn('mp-typing-dot inline-block h-1.5 w-1.5 rounded-full', colorClass)}
          style={{ animationDelay: `${i * 0.16}s` }}
        />
      ))}
    </div>
  )
}
