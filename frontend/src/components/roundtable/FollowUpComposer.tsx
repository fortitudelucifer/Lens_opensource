/**
 * FollowUpComposer · 圆桌讨论 done 状态下的追问输入框（Day 6 · 形态 A）
 *
 * 设计要点：
 *   - 仅在 `currentPhase === 'done'` 时展示（只能在整轮结束后才追问）
 *   - 提交时调用 `api.continueRoundtableSession` → store.archiveCurrentRoundAndReset
 *     → hook 通过 streamNonce bump 自动重连 SSE
 *   - 右下角两个次要按钮占位（聊天记录注入 / 知识手册注入，Step 4 再实装）
 *   - 禁用条件：正在提交、输入为空、字数 <4（后端 pydantic 下限）
 */

import { useState } from 'react'
import { Send, BookOpen, MessagesSquare, Loader2, X, Sparkles, Zap } from 'lucide-react'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'
import { api } from '@/lib/api'
import { useRoundtableStore } from '@/stores/useRoundtableStore'
import { InjectionDrawer, type InjectionMode } from './InjectionDrawer'

interface FollowUpComposerProps {
  /** 当前 session id · 必须是 backend 格式才允许追问（本地 mock 禁用） */
  sessionId: string
  /** 是否禁用（若 sessionId 非 backend 格式、或外部主动禁用） */
  disabled?: boolean
}

const MIN_CHARS = 4
const MAX_CHARS = 2000

export function FollowUpComposer({
  sessionId,
  disabled = false,
}: FollowUpComposerProps) {
  const [value, setValue] = useState('')
  const [submitting, setSubmitting] = useState(false)

  // ── Day 6 · Step 4 · RAG 注入状态 ──
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [drawerTab, setDrawerTab] = useState<InjectionMode>('chat_history')
  const [injectContext, setInjectContext] = useState('')
  const [injectSummary, setInjectSummary] = useState<{ chat: number; kn: number } | null>(null)

  const archiveCurrentRoundAndReset = useRoundtableStore(
    (s) => s.archiveCurrentRoundAndReset,
  )
  // Day 7 · 深度模式（与 Setup 页共享同一个 store 字段 · continue 时透传给后端）
  const deepMode = useRoundtableStore((s) => s.deepMode)
  const setDeepMode = useRoundtableStore((s) => s.setDeepMode)

  const trimmed = value.trim()
  const tooShort = trimmed.length > 0 && trimmed.length < MIN_CHARS
  const tooLong = trimmed.length > MAX_CHARS
  const canSubmit = !disabled && !submitting && trimmed.length >= MIN_CHARS && !tooLong

  async function handleSubmit(e?: React.FormEvent) {
    e?.preventDefault()
    if (!canSubmit) return
    setSubmitting(true)
    try {
      await api.continueRoundtableSession(sessionId, {
        question: trimmed,
        inject_context: injectContext || null,
        // Day 7 · 本轮深度模式（由 store 控制 · Setup 页和此处共享）
        deep_mode: deepMode,
      })
      // 本地归档当前轮 + 把 question 更新为新追问 + 重置 agents + bump streamNonce
      archiveCurrentRoundAndReset(trimmed)
      setValue('')
      setInjectContext('')
      setInjectSummary(null)
      toast.success('已追问，圆桌重新开讨')
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      toast.error('追问失败', { description: msg.slice(0, 120) })
    } finally {
      setSubmitting(false)
    }
  }

  function openDrawer(tab: InjectionMode) {
    if (!trimmed || trimmed.length < 2) {
      toast.info('请先输入你的追问内容（至少 2 个字），再调用检索', {
        description: '会用你的追问作为检索关键词',
      })
      return
    }
    setDrawerTab(tab)
    setDrawerOpen(true)
  }

  function handleInjectConfirm(context: string, summary: { chat: number; kn: number }) {
    setInjectContext(context)
    setInjectSummary(summary.chat + summary.kn > 0 ? summary : null)
  }

  function clearInject() {
    setInjectContext('')
    setInjectSummary(null)
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    // Cmd/Ctrl + Enter 提交
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
      e.preventDefault()
      void handleSubmit()
    }
  }

  return (
    <>
    <form
      onSubmit={handleSubmit}
      className="mp-fade-up max-w-3xl mx-auto mt-10 rounded-2xl border border-primary/20 bg-card/70 backdrop-blur shadow-sm overflow-hidden"
      aria-label="追问输入框"
    >
      <div className="px-5 pt-4 pb-1 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-foreground/90">
          还想继续聊？
        </h3>
        <span className="text-[11px] text-muted-foreground">
          在这一轮的基础上追问，3 位顾问会带着上轮的记忆回应你
        </span>
      </div>

      <textarea
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={handleKeyDown}
        disabled={disabled || submitting}
        rows={3}
        maxLength={MAX_CHARS + 20}
        placeholder="想对上一轮的内容进一步追问，或带入一个新的细节……（Cmd/Ctrl + Enter 发送）"
        className={cn(
          'w-full resize-none bg-transparent px-5 py-3 text-sm leading-relaxed',
          'text-foreground placeholder:text-muted-foreground/60',
          'focus:outline-none',
          disabled && 'opacity-60 cursor-not-allowed',
        )}
      />

      {/* 注入状态提示（有选中片段时）*/}
      {injectSummary && (
        <div className="mx-5 mb-2 flex items-center gap-2 rounded-md border border-primary/30 bg-primary/5 px-3 py-1.5">
          <Sparkles className="w-3 h-3 text-primary shrink-0" />
          <span className="text-[11px] text-primary/90 flex-1 min-w-0 truncate">
            已注入 · 聊天片段 {injectSummary.chat} 条 · 知识条目 {injectSummary.kn} 条 · 共 {injectContext.length} 字
          </span>
          <button
            type="button"
            onClick={clearInject}
            className="inline-flex items-center rounded p-1 text-muted-foreground hover:text-foreground hover:bg-muted/60 transition"
            aria-label="清除注入"
          >
            <X className="w-3 h-3" />
          </button>
        </div>
      )}

      <div className="px-3 pb-3 pt-1 flex items-center justify-between gap-2 flex-wrap">
        {/* 左侧：Step 4 · RAG 注入按钮 + Day 7 深度模式切换 */}
        <div className="flex items-center gap-1.5 flex-wrap">
          <InjectButton
            icon={<MessagesSquare className="w-3.5 h-3.5" />}
            label="注入聊天记录"
            onClick={() => openDrawer('chat_history')}
            disabled={disabled || submitting}
            active={!!injectSummary && injectSummary.chat > 0}
          />
          <InjectButton
            icon={<BookOpen className="w-3.5 h-3.5" />}
            label="注入知识手册"
            onClick={() => openDrawer('knowledge')}
            disabled={disabled || submitting}
            active={!!injectSummary && injectSummary.kn > 0}
          />
          {/* Day 7 · 深度模式小 chip · 点击切换 · 与 Setup 页共享 store 状态 */}
          <button
            type="button"
            onClick={() => setDeepMode(!deepMode)}
            disabled={disabled || submitting}
            title={
              deepMode
                ? '深度模式：每位顾问 500-900 字的完整分析（点一下关闭）'
                : '开启深度模式：每位顾问输出更长更深入的分析'
            }
            className={cn(
              'inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-[11px] font-medium transition',
              deepMode
                ? 'border-primary/60 bg-primary/10 text-primary hover:bg-primary/15'
                : 'border-border/60 bg-muted/40 text-foreground hover:bg-muted hover:border-border',
              (disabled || submitting) && 'opacity-60 cursor-not-allowed',
            )}
            aria-pressed={deepMode}
          >
            <Zap className="w-3.5 h-3.5" />
            {deepMode ? '深度·开' : '深度模式'}
          </button>
        </div>

        {/* 右侧：字符计数 + 提交 */}
        <div className="flex items-center gap-3">
          <span
            className={cn(
              'text-[11px] tabular-nums',
              tooShort
                ? 'text-amber-600'
                : tooLong
                  ? 'text-red-600'
                  : 'text-muted-foreground/70',
            )}
          >
            {trimmed.length} / {MAX_CHARS}
          </span>
          <button
            type="submit"
            disabled={!canSubmit}
            className={cn(
              'inline-flex items-center gap-1.5 rounded-lg px-4 py-2 text-sm font-medium transition',
              canSubmit
                ? 'bg-primary text-primary-foreground hover:bg-primary/90'
                : 'bg-muted text-muted-foreground cursor-not-allowed',
            )}
          >
            {submitting ? (
              <>
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                正在追问…
              </>
            ) : (
              <>
                <Send className="w-3.5 h-3.5" />
                追问
              </>
            )}
          </button>
        </div>
      </div>
    </form>

    <InjectionDrawer
      open={drawerOpen}
      onClose={() => setDrawerOpen(false)}
      query={trimmed}
      defaultTab={drawerTab}
      onConfirm={handleInjectConfirm}
    />
    </>
  )
}

function InjectButton({
  icon,
  label,
  onClick,
  disabled,
  active = false,
}: {
  icon: React.ReactNode
  label: string
  onClick?: () => void
  disabled: boolean
  active?: boolean
}) {
  const available = !!onClick
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled || !available}
      title={available ? label : `${label}（即将开放）`}
      className={cn(
        'inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-[11px] font-medium transition',
        active
          ? 'border-primary/60 bg-primary/10 text-primary hover:bg-primary/15'
          : available && !disabled
            ? 'border-border/60 bg-muted/40 text-foreground hover:bg-muted hover:border-border'
            : 'border-border/60 bg-muted/40 text-muted-foreground/60 cursor-not-allowed',
      )}
    >
      {icon}
      {label}
    </button>
  )
}
