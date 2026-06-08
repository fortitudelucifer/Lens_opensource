/**
 * Phase 过渡横幅
 *
 * 对齐执行方案 §2A 图 2（Fig 2）的 2s 真实过渡条（D1/D10）：
 *   - Phase 1→2：「3 个视角已完成，现在让他们相互回应」
 *   - Phase 2→3：「正在综合 3 个观点...」
 *
 * 用 CSS `mp-line-grow` 从左向右 800ms 生长，确定性进度而非动画遮掐。
 */

import { Sparkles } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { Phase } from '@/stores/useRoundtableStore'

interface PhaseBannerProps {
  /** 当前 phase */
  phase: Extract<Phase, 'phase1' | 'phase2' | 'phase3' | 'done'>
  /**
   * 视觉类型（MP 融合）：
   *   - `progress` 进度条（phase1→2 默认，强调"完成 → 推进"）
   *   - `sparkle` 旋转 sparkles 图标（phase2→3 默认，强调"综合中"的魔法感）
   * 不传则按 phase 自动选择
   */
  type?: 'progress' | 'sparkle'
  className?: string
}

const PHASE_CONFIG: Record<PhaseBannerProps['phase'], { title: string; subtitle: string; step: string }> = {
  phase1: {
    title: '独立分析',
    subtitle: '3 位顾问各自从本流派视角看这个问题',
    step: '第一阶段 · 1/3',
  },
  phase2: {
    title: '相互回应',
    subtitle: '3 个视角已完成，现在让他们相互回应',
    step: '第二阶段 · 2/3',
  },
  phase3: {
    title: '圆桌讨论中',
    subtitle: '三位顾问的观点在碰撞、补充、收束为一份综合',
    step: '第三阶段 · 3/3',
  },
  done: {
    title: '讨论完成',
    subtitle: '圆桌总结已就绪',
    step: '完成',
  },
}

export function PhaseBanner({ phase, type, className }: PhaseBannerProps) {
  const cfg = PHASE_CONFIG[phase]
  // 自动选择 type：phase3（综合中）默认 sparkle，其他默认 progress
  const effectiveType = type ?? (phase === 'phase3' ? 'sparkle' : 'progress')

  return (
    <div
      className={cn(
        'mp-fade-up flex flex-col gap-2 rounded-xl border border-border/60 bg-card/60 px-4 py-3 backdrop-blur',
        className,
      )}
      role="region"
      aria-label={`${cfg.title} 阶段`}
    >
      <div className="flex items-center justify-between text-xs font-medium text-muted-foreground">
        <span className="inline-flex items-center gap-1.5">
          {effectiveType === 'sparkle' && (
            <Sparkles
              className="h-3.5 w-3.5 text-amber-500"
              style={{ animation: 'spin 4s linear infinite' }}
              aria-hidden="true"
            />
          )}
          {cfg.step}
        </span>
        <span>{cfg.title}</span>
      </div>
      <div className="text-sm text-foreground/80">{cfg.subtitle}</div>
      {effectiveType === 'progress' && (
        <div className="mt-1 h-0.5 w-full rounded-full bg-muted/60">
          <div
            className={cn(
              'mp-line-grow h-full rounded-full bg-gradient-to-r from-emerald-400 via-teal-400 to-amber-400',
            )}
          />
        </div>
      )}
    </div>
  )
}
