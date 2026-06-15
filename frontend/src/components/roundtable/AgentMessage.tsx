/**
 * Agent 发言卡片（Session 页 Phase 1 / Phase 2）
 *
 * 5 种状态（对齐 `AgentStatus` 状态机）：
 *   - `pending` · 「等待发言...」 灰色静态
 *   - `typing` · TypingDots 3 点跳动 + elapsed timer + 动态文案（承载真 LLM 10-15s 首 token 延迟）
 *   - `streaming` · 流式文本 + 末尾游标
 *   - `done` · 纯文本 + confidence badge（如有）
 *   - `error` · 虚线灰卡 + 错误消息
 */

import { Circle, Star } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { cn } from '@/lib/utils'
import { PERSONA_COLOR_CLASSES, getPersona } from '@/data/personas'
import { getThinkingLabel, useElapsedSeconds } from '@/lib/thinking-ui'
import { getConfidenceMeta } from '@/lib/confidence'
import type { AgentMessageData } from '@/stores/useRoundtableStore'
import { TypingDots } from './TypingDots'

interface AgentMessageProps {
  agent: AgentMessageData
  /** phase 标签 */
  phaseLabel?: string
  /** 紧凑模式：三列并列布局下使用，卸载 phaseLabel、变小 padding */
  compact?: boolean
  className?: string
}

export function AgentMessage({ agent, phaseLabel, compact = false, className }: AgentMessageProps) {
  const { t } = useTranslation()
  const persona = getPersona(agent.personaId)
  if (!persona) {
    return (
      <div className="rounded-2xl border border-dashed border-border/60 bg-muted/30 p-4 text-sm text-muted-foreground">
        {t('roundtable.session.unknownPersona')}: {agent.personaId}
      </div>
    )
  }

  const colors = PERSONA_COLOR_CLASSES[persona.color]
  const Icon = persona.icon

  return (
    <article
      className={cn(
        'mp-fade-up flex flex-col rounded-2xl border transition-all overflow-hidden',
        agent.status === 'error'
          ? 'border-dashed border-muted-foreground/40 bg-muted/30 text-muted-foreground'
          : cn(colors.border, 'bg-card/70 backdrop-blur'),
        // 在三列下让 streaming 有文本时卡片轻微发亮（加强 ring）
        compact && agent.status === 'streaming' && agent.text && cn('ring-2', colors.ring),
        // typing 或 streaming 空窗（等首 token）都加淡色 ring + 呼吸
        compact &&
          (agent.status === 'typing' ||
            (agent.status === 'streaming' && !agent.text)) &&
          cn('ring-1', colors.ring, 'ring-opacity-50'),
        className,
      )}
      aria-label={`${t('persona.' + persona.id + '.name')} ${t('roundtable.session.speaking')}`}
    >
      {/* MP 融合：顶部彩色 accent 线（仅在 compact 三列布局显示，提供视觉分隔） */}
      {compact && agent.status !== 'error' && (
        <div
          className={cn(
            'h-1 w-full',
            colors.accent,
            // Day 7 · D7.2.d · 叠加 persona 同色 text · 让 mp-breathe-glow 的 currentColor 正确染色
            colors.accentText,
            // typing 或 streaming 空窗（等首 token）都脉冲呼吸 + filter drop-shadow 光晕
            // 原 animate-pulse 只做 opacity 脉动 · 叠加 mp-breathe-glow 增加"呼吸出光"的质感
            (agent.status === 'typing' ||
              (agent.status === 'streaming' && !agent.text)) &&
              'animate-pulse mp-breathe-glow',
          )}
          aria-hidden="true"
        />
      )}

      <div className={cn('flex flex-col', compact ? 'gap-2.5 p-3.5 sm:p-4' : 'gap-3 p-4 sm:p-5')}>
      {/* D7.2.a header：emoji 主头像 + 右下角 Lucide icon 徽标 · error 态降级为 Lucide only */}
      <header className="flex items-center gap-3">
        <div
          className={cn(
            'relative flex shrink-0 items-center justify-center rounded-xl',
            compact ? 'h-8 w-8' : 'h-9 w-9',
            agent.status === 'error' ? 'bg-muted' : colors.bg,
            agent.status === 'error' ? 'text-muted-foreground' : colors.fg,
          )}
        >
          {agent.status === 'error' ? (
            <Icon className={compact ? 'h-4 w-4' : 'h-[18px] w-[18px]'} strokeWidth={1.8} />
          ) : (
            <>
              <span
                className={cn(
                  'leading-none select-none',
                  compact ? 'text-[17px]' : 'text-[19px]',
                )}
                role="img"
                aria-label={`${t('persona.' + persona.id + '.name')} emoji`}
              >
                {persona.emoji}
              </span>
              <span
                aria-hidden="true"
                className={cn(
                  'absolute flex items-center justify-center rounded-full',
                  'bg-card ring-1 ring-border/50 shadow-sm',
                  colors.fg,
                  compact ? '-bottom-0.5 -right-0.5 h-3.5 w-3.5' : '-bottom-0.5 -right-0.5 h-4 w-4',
                )}
              >
                <Icon className={compact ? 'h-2 w-2' : 'h-2.5 w-2.5'} strokeWidth={2} />
              </span>
            </>
          )}
        </div>
        <div className="flex flex-col gap-0.5 min-w-0 flex-1">
          <div
            className={cn(
              'font-semibold truncate',
              compact ? 'text-[13px]' : 'text-sm',
              agent.status === 'error' ? 'text-muted-foreground' : colors.text,
            )}
          >
            {t('persona.' + persona.id + '.name')}
          </div>
          <div className="text-[11px] text-muted-foreground flex items-center gap-1.5 truncate">
            <span className="truncate">{t('persona.' + persona.id + '.subtitle')}</span>
            {phaseLabel && !compact && (
              <>
                <span aria-hidden="true">·</span>
                <span>{phaseLabel}</span>
              </>
            )}
          </div>
        </div>

        {/* confidence badge（done 时显示）· 三档视觉 + 百分比 */}
        {agent.status === 'done' && (() => {
          const meta = getConfidenceMeta(agent.confidence)
          if (!meta) return null
          const isHigh = meta.tier === 'high'
          const isMedium = meta.tier === 'medium'
          const isLow = meta.tier === 'low'
          // 图标：high = 实心星 · medium = 空心星 · low = 小圆点
          const iconEl = isLow ? (
            <Circle className="h-3 w-3" strokeWidth={2} aria-hidden="true" />
          ) : (
            <Star
              className="h-3 w-3"
              strokeWidth={isHigh ? 0 : 1.8}
              fill={isHigh ? 'currentColor' : 'none'}
              aria-hidden="true"
            />
          )
          return (
            <span
              className={cn(
                'shrink-0 inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium',
                // 颜色：high/medium 用 persona 配色；low 用灰
                isLow
                  ? 'bg-muted text-muted-foreground'
                  : cn(colors.bg, colors.text),
              )}
              title={`${t('confidence.' + meta.tier)} · ${t('arena.selfEval')} ${meta.percent}%`}
              aria-label={`${t('arena.confidence')} ${t('confidence.' + meta.tier)}，${meta.percent}%`}
            >
              {iconEl}
              <span className="tabular-nums">{meta.percent}%</span>
              {(isHigh || isMedium) && (
                <span className="opacity-70">· {t('confidence.' + meta.tier)}</span>
              )}
            </span>
          )
        })()}
      </header>

      {/* body */}
      <div
        className={cn(
          'leading-relaxed text-foreground/90',
          compact ? 'text-[13.5px] leading-[1.7]' : 'text-sm',
        )}
      >
        {agent.status === 'pending' && (
          <span className="text-xs text-muted-foreground italic">等待发言...</span>
        )}

        {/*
          Fix · 动画空窗 bug（2026-04-19）
          backend 在 LLM 调用前就把 status 切到 streaming，首 token 可能 5-20s 才到。
          若只按 status 分支 streaming 要求 text 非空，用户会看到纯空白卡片。
          → 把「status=typing」或「status=streaming 且 text 为空」都归类为 TypingBlock 视觉，
            确保用户在等 LLM 首 token 时始终能看到 dots + elapsed + shimmer。
        */}
        {(agent.status === 'typing' ||
          (agent.status === 'streaming' && !agent.text)) && (
          <TypingBlock colorClass={colors.accent} />
        )}

        {(agent.status === 'streaming' || agent.status === 'done') && agent.text && (
          <p className="whitespace-pre-wrap break-words">
            {agent.text}
            {agent.status === 'streaming' && (
              <span
                className={cn('ml-0.5 inline-block h-4 w-0.5 align-middle animate-pulse', colors.accent)}
                aria-hidden="true"
              />
            )}
          </p>
        )}

        {agent.status === 'error' && (
          <div className="text-xs italic text-muted-foreground">
            {agent.error ?? '这位顾问暂时无法发言，其他视角继续进行'}
          </div>
        )}
      </div>
      </div>
    </article>
  )
}

/** Typing 状态的完整呈现块：dots + 动态文案 + elapsed 秒表 + skeleton shimmer 占位 */
function TypingBlock({ colorClass }: { colorClass: string }) {
  const elapsed = useElapsedSeconds(true)
  const label = getThinkingLabel(elapsed)
  const showTimer = elapsed >= 3

  return (
    <div className="flex flex-col gap-2.5" role="status" aria-live="polite">
      {/* 第一行：dots + 动态文案 + 秒表 */}
      <div className="flex items-center gap-2">
        <TypingDots colorClass={colorClass} />
        <span className="text-xs text-muted-foreground flex items-center gap-1.5">
          <span>{label}</span>
          {showTimer && (
            <span className="tabular-nums font-mono text-[10px] opacity-60">
              · {elapsed}s
            </span>
          )}
        </span>
      </div>

      {/* Skeleton shimmer 占位（3 条宽度不一的条纹，视觉上"占住"未来文本的空间） */}
      <div className="flex flex-col gap-1.5 pt-1 opacity-60" aria-hidden="true">
        <div className="h-2 w-[90%] rounded-full bg-muted shimmer" />
        <div className="h-2 w-[75%] rounded-full bg-muted shimmer" />
        <div className="h-2 w-[60%] rounded-full bg-muted shimmer" />
      </div>

      {/* 15 秒后加一句温和提示（让用户知道真 LLM 响应是正常需要时间的） */}
      {elapsed >= 15 && (
        <p className="text-[11px] text-muted-foreground/80 italic leading-relaxed">
          真实 LLM 响应通常需要 10-20 秒 · 请稍等
        </p>
      )}
    </div>
  )
}
