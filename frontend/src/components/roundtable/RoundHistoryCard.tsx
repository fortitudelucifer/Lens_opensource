/**
 * RoundHistoryCard · 已归档历史轮的折叠展示（Day 6 · 形态 A）
 *
 * 展示一个已完成的 round：
 *   - 默认折叠 · 只显示轮序 + 当时的用户问题 excerpt + 展开按钮
 *   - 展开后：当时的 3 位顾问 phase2 回应卡片 + Moderator 6 段综合
 */

import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronDown, Quote, Sparkles } from 'lucide-react'
import { cn } from '@/lib/utils'
import { getPersona } from '@/data/personas'
import type { RoundSnapshot } from '@/stores/useRoundtableStore'
import { AgentMessage } from './AgentMessage'
import { ModeratorCard } from './ModeratorCard'

interface RoundHistoryCardProps {
  snapshot: RoundSnapshot
  /** 默认是否展开（首次进入 detail 页时可把倒数第 N 轮默认展开） */
  defaultExpanded?: boolean
}

export function RoundHistoryCard({
  snapshot,
  defaultExpanded = false,
}: RoundHistoryCardProps) {
  const { t } = useTranslation()
  const [expanded, setExpanded] = useState(defaultExpanded)

  const roundLabel = t('roundtable.session.roundLabel', { round: snapshot.roundIndex + 1 })
  const excerpt =
    snapshot.question.length > 72
      ? snapshot.question.slice(0, 72) + '…'
      : snapshot.question

  const personaNames = snapshot.phase2
    .map((b) => {
      const persona = getPersona(b.personaId)
      return persona ? t('persona.' + persona.id + '.name') : b.personaId
    })
    .join(' · ')

  return (
    <section
      className={cn(
        'max-w-3xl mx-auto rounded-2xl border border-border/50 bg-muted/30 overflow-hidden transition-all',
        expanded ? 'bg-card/60 shadow-sm' : 'hover:bg-muted/50',
      )}
      aria-expanded={expanded}
      aria-label={`${roundLabel} ${t('roundtable.session.history')}`}
    >
      {/* Header · 可点击折叠 */}
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-start gap-3 px-5 py-4 text-left"
      >
        <div
          className={cn(
            'mt-0.5 inline-flex items-center justify-center w-8 h-8 rounded-full text-xs font-semibold shrink-0',
            'bg-primary/10 text-primary ring-1 ring-primary/20',
          )}
          aria-hidden
        >
          {snapshot.roundIndex + 1}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-xs font-semibold text-muted-foreground tracking-wide uppercase">
              {roundLabel} · 历史
            </span>
            <span className="text-[10px] text-muted-foreground/70">
              与 {personaNames}
            </span>
          </div>
          <p className="mt-1 text-sm text-foreground/85 leading-relaxed line-clamp-2">
            <Quote className="inline w-3.5 h-3.5 text-primary/40 mr-1 -mt-0.5 rotate-180" />
            {excerpt}
          </p>
        </div>
        <ChevronDown
          className={cn(
            'w-4 h-4 text-muted-foreground shrink-0 mt-2 transition-transform duration-200',
            expanded && 'rotate-180',
          )}
        />
      </button>

      {/* Body · 展开后的内容 */}
      {expanded && (
        <div className="px-5 pb-5 space-y-4 animate-in fade-in slide-in-from-top-1 duration-200">
          {/* 原始问题完整版 */}
          {snapshot.question.length > 72 && (
            <div className="rounded-lg bg-background/70 border border-border/50 px-4 py-3 text-sm leading-relaxed text-foreground/85">
              <Quote className="inline w-3.5 h-3.5 text-primary/40 mr-1 -mt-0.5 rotate-180" />
              {snapshot.question}
            </div>
          )}

          {/* 3 位顾问的 phase2 最终回应（省略 phase1，避免历史太冗长） */}
          <div>
            <h4 className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wide mb-2">
              <Sparkles className="inline w-3 h-3 mr-1 text-primary/70" />
              三位顾问的回应
            </h4>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              {snapshot.phase2.map((agent) => (
                <AgentMessage
                  key={`hist-${snapshot.roundIndex}-p2-${agent.personaId}`}
                  agent={agent}
                  compact
                />
              ))}
            </div>
          </div>

          {/* Moderator 综合（若有） */}
          {snapshot.moderator && (
            <div>
              <h4 className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wide mb-2">
                Moderator 综合
              </h4>
              <ModeratorCard content={snapshot.moderator} />
            </div>
          )}
        </div>
      )}
    </section>
  )
}
