/**
 * InjectionDrawer · Day 6 · Step 4 · RAG 注入预览 + 勾选面板
 *
 * 从 FollowUpComposer 打开，根据当前草稿 question 调 /roundtable/inject/preview，
 * 展示聊天记录命中片段 + 知识手册命中条目；用户勾选后本地拼一段 context 字符串，
 * 返回给父组件（父组件会把它作为 inject_context 一起发给 continue）。
 */

import { useEffect, useMemo, useState } from 'react'
import {
  X, BookOpen, MessagesSquare, Loader2, Search, CheckSquare, Square,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import {
  api,
  type RoundtableInjectPreview,
  type RoundtableChatHistoryHit,
  type RoundtableKnowledgeHit,
} from '@/lib/api'
import { toast } from 'sonner'

export type InjectionMode = 'chat_history' | 'knowledge'

interface InjectionDrawerProps {
  open: boolean
  onClose: () => void
  query: string
  defaultTab: InjectionMode
  onConfirm: (context: string, summary: { chat: number; kn: number }) => void
  topK?: number
}

export function InjectionDrawer({
  open,
  onClose,
  query,
  defaultTab,
  onConfirm,
  topK = 5,
}: InjectionDrawerProps) {
  const [tab, setTab] = useState<InjectionMode>(defaultTab)
  const [loading, setLoading] = useState(false)
  const [preview, setPreview] = useState<RoundtableInjectPreview | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [selectedChat, setSelectedChat] = useState<Set<number>>(new Set())
  const [selectedKn, setSelectedKn] = useState<Set<number>>(new Set())

  // ESC 关闭
  useEffect(() => {
    if (!open) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [open, onClose])

  // 打开时拉预览
  useEffect(() => {
    if (!open) return
    if (!query.trim() || query.trim().length < 2) {
      setError('请先在输入框里写点内容（至少 2 个字）再打开注入面板')
      setPreview(null)
      return
    }
    let cancelled = false
    ;(async () => {
      setLoading(true)
      setError(null)
      try {
        const data = await api.previewRoundtableInjection({
          query: query.trim(),
          modes: ['chat_history', 'knowledge'],
          top_k: topK,
        })
        if (cancelled) return
        setPreview(data)
        setSelectedChat(new Set(data.chat_history.map((_, i) => i)))
        setSelectedKn(new Set(data.knowledge.map((_, i) => i)))
      } catch (err) {
        if (cancelled) return
        const msg = err instanceof Error ? err.message : String(err)
        setError(msg)
        setPreview(null)
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [open, query, topK])

  function toggleChat(i: number) {
    setSelectedChat((prev) => {
      const next = new Set(prev)
      if (next.has(i)) next.delete(i); else next.add(i)
      return next
    })
  }
  function toggleKn(i: number) {
    setSelectedKn((prev) => {
      const next = new Set(prev)
      if (next.has(i)) next.delete(i); else next.add(i)
      return next
    })
  }
  function toggleAllChat() {
    if (!preview) return
    if (selectedChat.size === preview.chat_history.length) setSelectedChat(new Set())
    else setSelectedChat(new Set(preview.chat_history.map((_, i) => i)))
  }
  function toggleAllKn() {
    if (!preview) return
    if (selectedKn.size === preview.knowledge.length) setSelectedKn(new Set())
    else setSelectedKn(new Set(preview.knowledge.map((_, i) => i)))
  }

  const context = useMemo(() => {
    if (!preview) return ''
    return buildContextFromSelection(preview, selectedChat, selectedKn)
  }, [preview, selectedChat, selectedKn])

  function handleConfirm() {
    onConfirm(context, { chat: selectedChat.size, kn: selectedKn.size })
    toast.success('已选好注入内容', {
      description: `聊天记录 ${selectedChat.size} 片段 · 知识手册 ${selectedKn.size} 条`,
    })
    onClose()
  }

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center sm:justify-center bg-black/40 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="injection-drawer-title"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div className="bg-card w-full max-w-2xl max-h-[85vh] sm:rounded-2xl rounded-t-2xl shadow-2xl border border-border/60 flex flex-col animate-in fade-in slide-in-from-bottom-2 duration-200">
        <div className="flex items-center justify-between px-5 py-4 border-b border-border/40">
          <div className="flex items-center gap-2">
            <Search className="w-4 h-4 text-primary/80" />
            <h2
              id="injection-drawer-title"
              className="text-base font-semibold text-foreground"
            >
              选择要注入的参考资料
            </h2>
          </div>
          <button
            onClick={onClose}
            className="rounded-md p-1 text-muted-foreground hover:text-foreground hover:bg-muted/60 transition"
            aria-label="关闭"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="flex items-center gap-1 px-3 pt-2 border-b border-border/40">
          <TabButton
            active={tab === 'chat_history'}
            onClick={() => setTab('chat_history')}
            icon={<MessagesSquare className="w-3.5 h-3.5" />}
            label="聊天记录"
            badge={preview?.chat_history.length ?? 0}
            checked={selectedChat.size}
          />
          <TabButton
            active={tab === 'knowledge'}
            onClick={() => setTab('knowledge')}
            icon={<BookOpen className="w-3.5 h-3.5" />}
            label="知识手册"
            badge={preview?.knowledge.length ?? 0}
            checked={selectedKn.size}
          />
        </div>

        <div className="flex-1 overflow-y-auto p-5 space-y-3">
          {loading && (
            <div className="flex items-center justify-center py-12 text-sm text-muted-foreground gap-2">
              <Loader2 className="w-4 h-4 animate-spin" />
              正在检索…
            </div>
          )}
          {error && !loading && (
            <div className="rounded-lg bg-amber-500/10 border border-amber-500/30 px-4 py-3 text-sm text-amber-700 dark:text-amber-200">
              {error}
            </div>
          )}
          {!loading && !error && preview && tab === 'chat_history' && (
            <ChatHistoryList
              hits={preview.chat_history}
              selected={selectedChat}
              onToggle={toggleChat}
              onToggleAll={toggleAllChat}
            />
          )}
          {!loading && !error && preview && tab === 'knowledge' && (
            <KnowledgeList
              hits={preview.knowledge}
              selected={selectedKn}
              onToggle={toggleKn}
              onToggleAll={toggleAllKn}
            />
          )}
        </div>

        <div className="px-5 py-3 border-t border-border/40 bg-muted/30 flex items-center justify-between gap-3">
          <div className="text-[11px] text-muted-foreground">
            共选中 <span className="font-semibold text-foreground">{selectedChat.size + selectedKn.size}</span> 条 · 将注入约 <span className="tabular-nums">{context.length}</span> 字
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-md border border-border bg-background px-3 py-1.5 text-xs text-foreground hover:bg-muted transition"
            >
              取消
            </button>
            <button
              type="button"
              onClick={handleConfirm}
              disabled={loading}
              className="rounded-md bg-primary px-4 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 transition disabled:opacity-50"
            >
              应用注入
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── 子组件 ──

function TabButton({
  active, onClick, icon, label, badge, checked,
}: {
  active: boolean
  onClick: () => void
  icon: React.ReactNode
  label: string
  badge: number
  checked: number
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'inline-flex items-center gap-1.5 px-3 py-2 text-sm border-b-2 transition',
        active
          ? 'border-primary text-foreground font-medium'
          : 'border-transparent text-muted-foreground hover:text-foreground',
      )}
    >
      {icon}
      {label}
      {badge > 0 && (
        <span className="ml-1 inline-flex items-center rounded-full bg-primary/10 px-1.5 py-0.5 text-[10px] font-semibold text-primary">
          {checked}/{badge}
        </span>
      )}
    </button>
  )
}

function ChatHistoryList({
  hits, selected, onToggle, onToggleAll,
}: {
  hits: RoundtableChatHistoryHit[]
  selected: Set<number>
  onToggle: (i: number) => void
  onToggleAll: () => void
}) {
  if (hits.length === 0) {
    return (
      <p className="text-sm text-muted-foreground text-center py-8">
        没有在历史聊天中找到相关片段。
        <br />
        <span className="text-[11px]">（需要你之前接入过 WeChat 对话 + 构建 FAISS 索引）</span>
      </p>
    )
  }
  const allChecked = selected.size === hits.length
  return (
    <>
      <div className="flex items-center justify-between pb-2 border-b border-border/40">
        <span className="text-[11px] text-muted-foreground">
          共 {hits.length} 条命中 · 按语义相似度排序
        </span>
        <button
          type="button"
          onClick={onToggleAll}
          className="inline-flex items-center gap-1 text-[11px] text-primary hover:underline"
        >
          {allChecked ? (
            <><Square className="w-3 h-3" /> 全不选</>
          ) : (
            <><CheckSquare className="w-3 h-3" /> 全选</>
          )}
        </button>
      </div>
      {hits.map((hit, i) => {
        const isChecked = selected.has(i)
        const dayTag = hit.days.length > 0
          ? `第 ${hit.days.join(', ')} 天`
          : '时间未知'
        const typeLabel = (
          { conflict: '冲突', sweet: '甜蜜', normal: '日常' } as Record<string, string>
        )[hit.chunk_type] ?? hit.chunk_type
        return (
          <label
            key={`${hit.chunk_id}-${i}`}
            className={cn(
              'block rounded-lg border cursor-pointer transition p-3',
              isChecked
                ? 'border-primary/60 bg-primary/5'
                : 'border-border/50 bg-background/60 hover:border-primary/30',
            )}
          >
            <div className="flex items-start gap-2">
              <input
                type="checkbox"
                checked={isChecked}
                onChange={() => onToggle(i)}
                className="mt-0.5 accent-primary"
              />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-1.5 flex-wrap text-[11px] mb-1">
                  <span className="inline-flex items-center rounded bg-muted/70 px-1.5 py-0.5 text-muted-foreground">
                    {dayTag}
                  </span>
                  <span
                    className={cn(
                      'inline-flex items-center rounded px-1.5 py-0.5',
                      hit.chunk_type === 'conflict'
                        ? 'bg-red-500/10 text-red-700 dark:text-red-300'
                        : hit.chunk_type === 'sweet'
                          ? 'bg-pink-500/10 text-pink-700 dark:text-pink-300'
                          : 'bg-muted/70 text-muted-foreground',
                    )}
                  >
                    {typeLabel}
                  </span>
                  <span className="text-muted-foreground/70">
                    相似度 {(hit.score * 100).toFixed(0)}%
                  </span>
                </div>
                {hit.analysis_summary && (
                  <p className="text-[11px] text-muted-foreground/80 leading-relaxed mb-1.5">
                    {hit.analysis_summary}
                  </p>
                )}
                <p className="text-xs text-foreground/85 leading-relaxed line-clamp-4">
                  {hit.preview}
                </p>
              </div>
            </div>
          </label>
        )
      })}
    </>
  )
}

function KnowledgeList({
  hits, selected, onToggle, onToggleAll,
}: {
  hits: RoundtableKnowledgeHit[]
  selected: Set<number>
  onToggle: (i: number) => void
  onToggleAll: () => void
}) {
  if (hits.length === 0) {
    return (
      <p className="text-sm text-muted-foreground text-center py-8">
        没有在知识手册里找到相关条目。
        <br />
        <span className="text-[11px]">（知识手册来源：advisor_out/knowledge/*.jsonl）</span>
      </p>
    )
  }
  const allChecked = selected.size === hits.length
  return (
    <>
      <div className="flex items-center justify-between pb-2 border-b border-border/40">
        <span className="text-[11px] text-muted-foreground">
          共 {hits.length} 条命中 · 按关键词匹配得分排序
        </span>
        <button
          type="button"
          onClick={onToggleAll}
          className="inline-flex items-center gap-1 text-[11px] text-primary hover:underline"
        >
          {allChecked ? (
            <><Square className="w-3 h-3" /> 全不选</>
          ) : (
            <><CheckSquare className="w-3 h-3" /> 全选</>
          )}
        </button>
      </div>
      {hits.map((hit, i) => {
        const isChecked = selected.has(i)
        return (
          <label
            key={`${hit.category}-${i}`}
            className={cn(
              'block rounded-lg border cursor-pointer transition p-3',
              isChecked
                ? 'border-primary/60 bg-primary/5'
                : 'border-border/50 bg-background/60 hover:border-primary/30',
            )}
          >
            <div className="flex items-start gap-2">
              <input
                type="checkbox"
                checked={isChecked}
                onChange={() => onToggle(i)}
                className="mt-0.5 accent-primary"
              />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-1.5 flex-wrap text-[11px] mb-1">
                  {hit.category && (
                    <span className="inline-flex items-center rounded bg-primary/10 px-1.5 py-0.5 text-primary font-medium">
                      {hit.category}
                    </span>
                  )}
                  {hit.keywords.slice(0, 4).map((k) => (
                    <span
                      key={k}
                      className="inline-flex items-center rounded bg-muted/70 px-1.5 py-0.5 text-muted-foreground"
                    >
                      #{k}
                    </span>
                  ))}
                </div>
                <p className="text-sm text-foreground/90 font-medium mb-1 line-clamp-2">
                  Q: {hit.question}
                </p>
                <p className="text-xs text-muted-foreground leading-relaxed line-clamp-3">
                  A: {hit.answer}
                </p>
              </div>
            </div>
          </label>
        )
      })}
    </>
  )
}

// ── context 拼接 · 导出供 composer 回显使用 ──
export function buildContextFromSelection(
  preview: RoundtableInjectPreview,
  selectedChat: Set<number>,
  selectedKn: Set<number>,
): string {
  const parts: string[] = []
  const chatSel = preview.chat_history.filter((_, i) => selectedChat.has(i))
  if (chatSel.length > 0) {
    const lines: string[] = ['【相关历史对话片段】']
    chatSel.forEach((h, i) => {
      const dayTag = h.days.length > 0 ? `第${h.days.join(',')}天` : '时间未知'
      const typeLabel = (
        { conflict: '冲突', sweet: '甜蜜', normal: '日常' } as Record<string, string>
      )[h.chunk_type] ?? h.chunk_type
      let header = `片段 ${i + 1}（${dayTag} · ${typeLabel}）`
      if (h.analysis_summary) header += `\n分析：${h.analysis_summary}`
      lines.push(`${header}\n${h.preview}`)
    })
    parts.push(lines.join('\n\n'))
  }
  const knSel = preview.knowledge.filter((_, i) => selectedKn.has(i))
  if (knSel.length > 0) {
    const lines: string[] = ['【专业知识手册】']
    knSel.forEach((e) => {
      if (e.question || e.answer) {
        lines.push(`Q: ${e.question.trim()}\nA: ${e.answer.trim()}`)
      }
    })
    parts.push(lines.join('\n\n'))
  }
  return parts.join('\n\n')
}
