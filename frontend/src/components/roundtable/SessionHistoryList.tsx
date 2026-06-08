/**
 * SessionHistoryList · 圆桌讨论历史入口（Day 6 · Step 3）
 *
 * 在 RoundtablePage 顶部展示一个可折叠的卡片，列出过往 N 条 session 摘要，
 * 点击即可 hydrate 到 Store 并跳转到 RoundtableSessionPage 继续查看 / 追问。
 *
 * 设计要点：
 *   - 默认折叠（不打扰首次使用的用户）· 有历史时才显示"查看历史"按钮
 *   - 顶部 refresh 按钮（轻量），不自动轮询
 *   - 按 updated_at 倒序（backend `list_sessions` 已保证）
 *   - 显示 question_excerpt、轮数徽章、更新时间
 *   - 错误状态：显示错误卡，允许重试
 */

import { useEffect, useState } from 'react'
import {
  ChevronDown, History, RefreshCw, Loader2, AlertCircle,
  MessagesSquare,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { api, type RoundtableSessionSummary } from '@/lib/api'
import { useRoundtableStore } from '@/stores/useRoundtableStore'
import { getPersona, type PersonaId } from '@/data/personas'
import { toast } from 'sonner'

interface SessionHistoryListProps {
  /** 点击历史 session 后切换到 SessionPage 的回调（由父级驱动路由） */
  onOpenSession?: () => void
  /** 最多展示条数，默认 10 */
  limit?: number
}

export function SessionHistoryList({
  onOpenSession,
  limit = 10,
}: SessionHistoryListProps) {
  const [expanded, setExpanded] = useState(false)
  const [sessions, setSessions] = useState<RoundtableSessionSummary[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [openingId, setOpeningId] = useState<string | null>(null)

  const hydrateFromDetail = useRoundtableStore((s) => s.hydrateFromDetail)

  async function fetchSessions() {
    setLoading(true)
    setError(null)
    try {
      const list = await api.listRoundtableSessions()
      setSessions(list)
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      setError(msg)
      setSessions([])
    } finally {
      setLoading(false)
    }
  }

  // 组件首次挂载时拉一次（但保持折叠默认；展开时不重拉，点 refresh 才重拉）
  useEffect(() => {
    void fetchSessions()
  }, [])

  const totalCount = sessions.length

  async function handleOpen(summary: RoundtableSessionSummary) {
    if (openingId) return
    setOpeningId(summary.id)
    try {
      const detail = await api.getRoundtableSession(summary.id)
      hydrateFromDetail(detail)
      toast.success('已恢复历史讨论', {
        description: `第 ${detail.round_index + 1} 轮 · ${summary.phase}`,
      })
      onOpenSession?.()
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      toast.error('载入历史会话失败', { description: msg.slice(0, 120) })
    } finally {
      setOpeningId(null)
    }
  }

  // 无历史 + 无加载 + 无错误 → 不渲染任何卡片
  if (!loading && !error && totalCount === 0) {
    return null
  }

  const displayList = sessions.slice(0, limit)

  return (
    <section
      className="mp-fade-up mt-8 max-w-3xl mx-auto rounded-2xl border border-border/60 bg-card/60 backdrop-blur overflow-hidden"
      aria-label="圆桌讨论历史"
    >
      <div className="flex items-center justify-between px-5 py-3 border-b border-border/40">
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="flex items-center gap-2 text-left"
        >
          <History className="w-4 h-4 text-primary/80" />
          <h3 className="text-sm font-semibold text-foreground">
            历史圆桌讨论
          </h3>
          {totalCount > 0 && (
            <span className="inline-flex items-center rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-semibold text-primary ring-1 ring-primary/20">
              {totalCount}
            </span>
          )}
          <ChevronDown
            className={cn(
              'w-3.5 h-3.5 text-muted-foreground transition-transform ml-0.5',
              expanded && 'rotate-180',
            )}
          />
        </button>

        <button
          type="button"
          onClick={fetchSessions}
          disabled={loading}
          className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] text-muted-foreground hover:text-foreground hover:bg-muted/50 transition disabled:opacity-40"
          title="刷新列表"
        >
          {loading ? (
            <Loader2 className="w-3 h-3 animate-spin" />
          ) : (
            <RefreshCw className="w-3 h-3" />
          )}
          刷新
        </button>
      </div>

      {expanded && (
        <div className="p-4 space-y-2 animate-in fade-in slide-in-from-top-1 duration-150">
          {error && (
            <div className="rounded-lg bg-red-500/10 border border-red-500/30 px-3 py-2 text-[12px] text-red-700 dark:text-red-300 flex items-start gap-2">
              <AlertCircle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
              <span>载入失败：{error}</span>
            </div>
          )}

          {loading && sessions.length === 0 && (
            <div className="flex items-center justify-center py-8 text-sm text-muted-foreground gap-2">
              <Loader2 className="w-4 h-4 animate-spin" />
              载入中…
            </div>
          )}

          {displayList.map((s) => (
            <SessionRow
              key={s.id}
              summary={s}
              opening={openingId === s.id}
              disabled={openingId !== null && openingId !== s.id}
              onClick={() => void handleOpen(s)}
            />
          ))}

          {totalCount > limit && (
            <p className="pt-2 text-[11px] text-muted-foreground text-center">
              仅显示最近 {limit} 条 · 更多历史已在后台保留
            </p>
          )}
        </div>
      )}
    </section>
  )
}

// ── 单行展示 ──

function SessionRow({
  summary,
  opening,
  disabled,
  onClick,
}: {
  summary: RoundtableSessionSummary
  opening: boolean
  disabled: boolean
  onClick: () => void
}) {
  const updatedAgo = formatRelative(summary.updated_at)
  const rounds = summary.rounds_count + 1 // 已归档 + 当前轮
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled || opening}
      className={cn(
        'w-full rounded-lg border border-border/50 bg-background/60 px-3 py-2.5 text-left transition',
        'hover:border-primary/40 hover:bg-muted/50',
        (disabled || opening) && 'opacity-60 cursor-wait',
      )}
    >
      <div className="flex items-center gap-2 mb-1">
        <MessagesSquare className="w-3.5 h-3.5 text-primary/70 shrink-0" />
        <span className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide">
          {summary.phase === 'done' ? '已完成' : `进行中 · ${summary.phase}`}
        </span>
        <span className="text-[10px] text-muted-foreground/70">·</span>
        <span className="text-[10px] text-muted-foreground/70">{updatedAgo}</span>
        <span className="ml-auto inline-flex items-center rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-semibold text-primary ring-1 ring-primary/20">
          {rounds} 轮
        </span>
        {opening && <Loader2 className="w-3 h-3 animate-spin text-primary ml-1" />}
      </div>
      <p className="text-sm text-foreground/85 leading-snug line-clamp-2">
        {summary.question_excerpt || summary.question}
      </p>
      <div className="mt-1 flex items-center gap-1 flex-wrap">
        {summary.personas.slice(0, 3).map((p) => {
          const persona = getPersona(p as PersonaId)
          return (
            <span
              key={p}
              className="inline-flex items-center gap-1 rounded bg-muted/60 px-1.5 py-0.5 text-[10px] text-muted-foreground"
              title={persona?.name ?? p}
            >
              {persona ? (
                <>
                  <span role="img" aria-hidden="true" className="text-[12px] leading-none">
                    {persona.emoji}
                  </span>
                  <span>{persona.name}</span>
                </>
              ) : (
                p
              )}
            </span>
          )
        })}
        {summary.backend && (
          <span className="inline-flex items-center rounded bg-muted/60 px-1.5 py-0.5 text-[10px] text-muted-foreground/80">
            ⚙︎ {summary.backend}
          </span>
        )}
      </div>
    </button>
  )
}

// ── 相对时间格式化（小字段，不引 date-fns 依赖） ──
function formatRelative(iso: string): string {
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return ''
  const diff = Date.now() - then
  const mins = Math.floor(diff / 60_000)
  if (mins < 1) return '刚刚'
  if (mins < 60) return `${mins} 分钟前`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours} 小时前`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days} 天前`
  return new Date(iso).toLocaleDateString('zh-CN')
}
