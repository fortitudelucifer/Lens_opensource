/**
 * Moderator 综合总结卡片（Phase 3）
 *
 * 仪式感设计（对齐 MP 评审 §2.2）：
 *   - `rounded-3xl border-2 border-amber-200/70` 加粗边框
 *   - amber → rose 渐变底 + 🎙️ + Sparkles 装饰
 *   - warmClose 独立 `bg-rose-50/70` 小卡片锚定情感
 *
 * 6 段（对齐执行方案 K2 + D1-D10）：
 *   【看到你】【不同视角】【你可以尝试】【仍然存疑】【Lens 寄语】【局限】
 */

import { useTranslation } from 'react-i18next'
import { Mic, Sparkles, Eye, Compass, Footprints, HelpCircle, Heart, ShieldAlert, AlertTriangle } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { ModeratorContent } from '@/stores/useRoundtableStore'

interface ModeratorCardProps {
  content: ModeratorContent
  className?: string
  /**
   * Day 7 · Moderator LLM 降级原因 · null=LLM 成功（或历史轮）· 其余值代表规则模板
   * 非空时，卡片顶部渲染一条 amber 提示条告知用户本轮走了规则模板。
   * D7.1.j+ 后：规则模板在多轮场景会自动承接上轮 Moderator 总结（seen/tries[0]/doubts[0]/lens）。
   */
  fallbackReason?: string | null
  /**
   * Day 7 · D7.1.j+ · 当前轮 0-based index · 供降级 banner 文案区分首轮（无历史可承接）vs 多轮（已自动承接）。
   * 默认 0（首轮）· 仅在 `fallbackReason` 非空时影响 banner 文案。
   */
  roundIndex?: number
}

/**
 * 把 backend 的降级原因枚举翻译成用户能懂的中文说明。
 *
 * D7.1.j+ （2026-04-30）：规则模板现在会自动承接上轮 Moderator 总结 · 文案随轮切换：
 *   - 首轮（roundIndex=0）· “首轮·无历史可承接”
 *   - 多轮（roundIndex>0）· “已自动承接上轮总结”
 */
function explainFallbackReason(
  reason: string,
  roundIndex: number,
  t: (key: string, options?: Record<string, unknown>) => string,
): { title: string; detail: string } {
  // D7.1.j+ · 多轮场景 · 提示“已自动承接”以区分与首轮静态模板
  const memorySuffix =
    roundIndex > 0
      ? t('moderator.memorySuffixMulti')
      : t('moderator.memorySuffixFirst')
  if (reason === 'llm_returned_none') {
    return {
      title: t('moderator.fallbackTitle'),
      detail: t('moderator.fallbackDetailTimeout', { memorySuffix }),
    }
  }
  if (reason === 'llm_disabled') {
    return {
      title: t('moderator.fallbackTitleDisabled'),
      detail: t('moderator.fallbackDetailDisabled', { memorySuffix }),
    }
  }
  if (reason.startsWith('exception:')) {
    return {
      title: t('moderator.fallbackTitle'),
      detail: t('moderator.fallbackDetailException', { reason: reason.slice(10), memorySuffix }),
    }
  }
  return {
    title: t('moderator.fallbackTitle'),
    detail: t('moderator.fallbackDetailGeneric', { reason, memorySuffix }),
  }
}

export function ModeratorCard({
  content,
  className,
  fallbackReason = null,
  roundIndex = 0,
}: ModeratorCardProps) {
  const { t } = useTranslation()
  const fallbackInfo = fallbackReason ? explainFallbackReason(fallbackReason, roundIndex, t) : null
  return (
    <article
      className={cn(
        'mp-fade-up relative flex flex-col gap-5 rounded-3xl border-2 p-6 shadow-sm sm:p-8',
        'border-amber-200/70 dark:border-amber-400/25',
        'bg-gradient-to-br from-amber-50/60 via-background to-rose-50/40',
        'dark:from-amber-950/20 dark:via-background dark:to-rose-950/10',
        className,
      )}
      role="region"
      aria-label={t('moderator.ariaLabel')}
    >
      {/* MP 融合：背景渐变装饰（amber→rose轻薄）增强仪式感 */}
      <div
        className="absolute inset-0 rounded-3xl bg-gradient-to-br from-amber-500/[0.04] via-transparent to-rose-500/[0.05] pointer-events-none"
        aria-hidden="true"
      />
      {/* Day 7 · D7.2.c · "桌面边缘" SVG 装饰：强化"圆桌讨论"的隐喻
       * 设计：一条柔和的抛物线代表木桌弧形 + 两端小桌角短线 · 仅顶部渲染
       * 色调：amber→rose 渐变描边 · 低饱和 · 不抢主视觉
       * 大小：~ 600 bytes inline SVG · 无任何动画 · reduced-motion 天然兼容 */}
      <svg
        viewBox="0 0 600 14"
        preserveAspectRatio="none"
        className="pointer-events-none absolute top-0 left-0 right-0 h-[14px] w-full rounded-t-3xl overflow-visible"
        aria-hidden="true"
      >
        <defs>
          <linearGradient id="table-edge-gradient" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor="rgb(251 191 36)" stopOpacity="0" />
            <stop offset="25%" stopColor="rgb(251 191 36)" stopOpacity="0.45" />
            <stop offset="50%" stopColor="rgb(244 114 182)" stopOpacity="0.55" />
            <stop offset="75%" stopColor="rgb(251 191 36)" stopOpacity="0.45" />
            <stop offset="100%" stopColor="rgb(251 191 36)" stopOpacity="0" />
          </linearGradient>
        </defs>
        {/* 主弧线：轻微下凹 · 模拟桌面弧形 */}
        <path
          d="M 6 10 Q 300 3 594 10"
          fill="none"
          stroke="url(#table-edge-gradient)"
          strokeWidth="1.5"
          strokeLinecap="round"
        />
        {/* 左桌角短线 */}
        <path
          d="M 10 11 L 18 7"
          fill="none"
          stroke="rgb(251 191 36)"
          strokeOpacity="0.35"
          strokeWidth="1.25"
          strokeLinecap="round"
        />
        {/* 右桌角短线 */}
        <path
          d="M 590 11 L 582 7"
          fill="none"
          stroke="rgb(251 191 36)"
          strokeOpacity="0.35"
          strokeWidth="1.25"
          strokeLinecap="round"
        />
      </svg>
      {/* 装饰 sparkles */}
      <Sparkles
        className="absolute top-4 right-6 h-4 w-4 text-amber-400/60 dark:text-amber-300/40"
        aria-hidden="true"
      />

      {/* Day 7 · 降级提示条（LLM fallback 到规则模板时显示，用户知晓本轮无跨轮记忆）*/}
      {fallbackInfo && (
        <div
          role="status"
          aria-live="polite"
          className={cn(
            'relative flex items-start gap-3 rounded-xl border px-4 py-3 text-[13px]',
            'border-amber-300/80 bg-amber-50/80 text-amber-900',
            'dark:border-amber-400/40 dark:bg-amber-950/30 dark:text-amber-200',
          )}
        >
          <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" strokeWidth={2} />
          <div className="flex flex-col gap-0.5">
            <p className="font-medium leading-snug">{fallbackInfo.title}</p>
            <p className="text-[12px] leading-relaxed text-amber-800/80 dark:text-amber-200/70">
              {fallbackInfo.detail}
            </p>
          </div>
        </div>
      )}

      {/* header：🎙️ + title + subtitle */}
      <header className="flex items-center gap-3">
        <div
          className={cn(
            'flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl',
            'bg-gradient-to-br from-amber-400 to-rose-400 text-white shadow-sm',
          )}
        >
          <Mic className="h-5 w-5" strokeWidth={1.8} />
        </div>
        <div className="flex flex-col">
          <h2 className="text-base font-semibold text-foreground">{t('moderator.title')}</h2>
          <p className="text-xs text-muted-foreground">{t('moderator.subtitle')}</p>
        </div>
      </header>

      {/* § 看到你 · stagger 0ms */}
      <Section icon={Eye} title={t('moderator.section.seen')} tone="seen" delayMs={0}>
        <p className="text-sm leading-relaxed text-foreground/90">{content.seen}</p>
      </Section>

      {/* § 不同视角 · stagger 600ms */}
      <Section icon={Compass} title={t('moderator.section.angles')} tone="angles" delayMs={600}>
        <ul className="flex flex-col gap-1.5 text-sm leading-relaxed text-foreground/90">
          {content.angles.map((angle, i) => (
            <li
              key={i}
              className="mp-char-in pl-4 border-l-2 border-amber-300/50 dark:border-amber-400/30"
              style={{ animationDelay: `${i * 80}ms` }}
            >
              {angle}
            </li>
          ))}
        </ul>
      </Section>

      {/* § 你可以尝试 · stagger 1200ms */}
      <Section icon={Footprints} title={t('moderator.section.tries')} tone="tries" delayMs={1200}>
        <ol className="flex flex-col gap-2 text-sm leading-relaxed text-foreground/90">
          {content.tries.map((item, i) => (
            <li
              key={i}
              className="mp-char-in flex gap-3"
              style={{ animationDelay: `${i * 80}ms` }}
            >
              <span
                className={cn(
                  'flex h-5 w-5 shrink-0 items-center justify-center rounded-full',
                  'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/20 dark:text-emerald-300',
                  'text-xs font-semibold',
                )}
              >
                {i + 1}
              </span>
              <span>{item}</span>
            </li>
          ))}
        </ol>
      </Section>

      {/* § 仍然存疑 · stagger 1800ms */}
      {content.doubts.length > 0 && (
        <Section icon={HelpCircle} title={t('moderator.section.doubts')} tone="doubts" delayMs={1800}>
          <ul className="flex flex-col gap-1.5 text-sm leading-relaxed text-muted-foreground italic">
            {content.doubts.map((d, i) => (
              <li key={i}>· {d}</li>
            ))}
          </ul>
        </Section>
      )}

      {/* § Lens 寄语（warmClose · 独立高亮卡 · stagger 2400ms · amber→rose 渐变强化） */}
      <div
        className={cn(
          'mp-fade-up rounded-2xl border p-5',
          'border-rose-300/60 dark:border-rose-400/30',
          'bg-gradient-to-br from-rose-50/80 to-amber-50/60',
          'dark:from-rose-950/30 dark:to-amber-950/20',
        )}
        style={{ animationDelay: '2400ms', animationFillMode: 'both' }}
      >
        <div className="flex items-center gap-2 mb-2">
          <Heart
            className="h-4 w-4 text-rose-500 dark:text-rose-300"
            strokeWidth={2.2}
            fill="currentColor"
            fillOpacity={0.15}
          />
          <h3 className="text-sm font-semibold text-rose-700 dark:text-rose-200">{t('moderator.section.lens')}</h3>
        </div>
        <p className="text-sm leading-relaxed text-foreground/90 font-medium">
          {content.lens}
        </p>
      </div>

      {/* § 局限声明 · stagger 3000ms */}
      <div
        className="mp-fade-up flex gap-2 rounded-xl border border-border/40 bg-muted/40 p-3"
        style={{ animationDelay: '3000ms', animationFillMode: 'both' }}
      >
        <ShieldAlert className="h-3.5 w-3.5 shrink-0 text-muted-foreground mt-0.5" strokeWidth={2} />
        <p className="text-xs leading-relaxed text-muted-foreground">{content.limit}</p>
      </div>
    </article>
  )
}

// ── 内部：统一的 section 外壳 ──

interface SectionProps {
  icon: React.ComponentType<{ className?: string; strokeWidth?: number }>
  title: string
  tone: 'seen' | 'angles' | 'tries' | 'doubts'
  /** 逐段揭晓的 stagger 延迟（ms，MP 融合）*/
  delayMs?: number
  children: React.ReactNode
}

function Section({ icon: Icon, title, children, delayMs = 0 }: SectionProps) {
  return (
    <section
      className="mp-fade-up flex flex-col gap-2"
      style={{ animationDelay: `${delayMs}ms`, animationFillMode: 'both' }}
    >
      <div className="flex items-center gap-2">
        <Icon className="h-4 w-4 text-amber-600 dark:text-amber-400" strokeWidth={2} />
        <h3 className="text-sm font-semibold text-foreground">{title}</h3>
      </div>
      {children}
    </section>
  )
}
