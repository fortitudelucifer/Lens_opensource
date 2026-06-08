/**
 * Persona 选择卡片（Setup 页）
 *
 * 3 选 3 的选择器，色彩来自 `PERSONA_COLOR_CLASSES` 静态枚举（避免 JIT purge）。
 * 激活态用 `ring` + `bg`；非激活态保留 hover 反馈但色彩不饱和。
 */

import { Check, Sparkles } from 'lucide-react'
import { cn } from '@/lib/utils'
import { PERSONA_COLOR_CLASSES, type RoundtablePersona } from '@/data/personas'

interface PersonaCardProps {
  persona: RoundtablePersona
  selected: boolean
  disabled?: boolean
  onToggle: () => void
  /** 入场 stagger 索引，用于 mp-fade-up 动画延迟（80ms × index）*/
  index?: number
  className?: string
}

export function PersonaCard({
  persona,
  selected,
  disabled,
  onToggle,
  index = 0,
  className,
}: PersonaCardProps) {
  const colors = PERSONA_COLOR_CLASSES[persona.color]
  const Icon = persona.icon

  return (
    <button
      type="button"
      aria-pressed={selected}
      aria-disabled={disabled}
      onClick={() => !disabled && onToggle()}
      style={{ animationDelay: `${index * 60}ms` }}
      className={cn(
        'mp-fade-up group relative flex flex-col gap-2 rounded-2xl border p-4 text-left transition-all duration-200',
        'focus:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
        selected
          ? cn('ring-2', colors.ring, colors.bg, colors.border)
          : 'border-border/60 bg-card/60 hover:bg-card/90 hover:border-border',
        disabled && !selected && 'opacity-40 cursor-not-allowed hover:bg-card/60',
        className,
      )}
    >
      {/* 选中指示 */}
      {selected && (
        <span
          className={cn(
            'absolute right-3 top-3 inline-flex h-5 w-5 items-center justify-center rounded-full',
            colors.accent,
            'text-white shadow-sm',
          )}
          aria-hidden="true"
        >
          <Check className="h-3 w-3" strokeWidth={3} />
        </span>
      )}

      {/* Day 7 · D7.2.e · 未选中 & 未禁用时，悬停右上角浮现 Sparkles 微闪
       * 目的：提升"挑选这张卡"的仪式感 + 柔和暗示卡片可交互
       * animate-pulse 受 index.css 的 prefers-reduced-motion 通用兜底自动降级为 0.01ms */}
      {!selected && !disabled && (
        <Sparkles
          aria-hidden="true"
          className={cn(
            'absolute right-3 top-3 h-3.5 w-3.5 text-amber-400/80 dark:text-amber-300/70',
            'pointer-events-none opacity-0 transition-opacity duration-300',
            'group-hover:opacity-90 group-hover:animate-pulse',
          )}
          strokeWidth={2}
        />
      )}

      {/* D7.2.a 头像：emoji 主体（18px）+ 右下角 Lucide icon 小章（12px 装饰徽标） */}
      <div className="flex items-center gap-3">
        <div
          className={cn(
            'relative flex h-10 w-10 shrink-0 items-center justify-center rounded-xl',
            colors.bg,
          )}
        >
          <span
            className="text-[22px] leading-none select-none"
            role="img"
            aria-label={`${persona.name} emoji`}
          >
            {persona.emoji}
          </span>
          <span
            aria-hidden="true"
            className={cn(
              'absolute -bottom-0.5 -right-0.5 flex h-4 w-4 items-center justify-center rounded-full',
              'bg-card ring-1 ring-border/60 shadow-sm',
              colors.fg,
            )}
          >
            <Icon className="h-2.5 w-2.5" strokeWidth={2} />
          </span>
        </div>
        <div className="flex flex-col gap-0.5 min-w-0">
          <div className={cn('text-sm font-semibold', selected ? colors.text : 'text-foreground')}>
            {persona.name}
          </div>
          <div className="text-xs text-muted-foreground">{persona.subtitle}</div>
        </div>
      </div>

      {/* philosophy（斜体，小字） */}
      <p className="text-xs italic text-muted-foreground leading-relaxed">
        「{persona.philosophy}」
      </p>
    </button>
  )
}
