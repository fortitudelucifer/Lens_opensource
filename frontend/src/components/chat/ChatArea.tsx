import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { SplitSquareHorizontal, Copy, Check, Pencil, X } from 'lucide-react'
import type { Message, Persona } from '../../types'
import { ThinkingUI } from './ThinkingUI'
import { MarkdownContent } from './MarkdownContent'
import { TypingIndicator } from './TypingIndicator'
import { format } from 'date-fns'

interface ChatAreaProps {
  messages: Message[]
  currentPersona: Persona
  onSendToArena?: (content: string) => void
  onEditMessage?: (id: string, content: string) => void
}

export function ChatArea({ messages, currentPersona, onSendToArena, onEditMessage }: ChatAreaProps) {
  const { t } = useTranslation()
  const bottomRef = useRef<HTMLDivElement>(null)
  const Icon = currentPersona.icon
  const [copiedId, setCopiedId] = useState<string | null>(null)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [draft, setDraft] = useState('')

  const handleCopy = async (id: string, text: string) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopiedId(id)
      setTimeout(() => setCopiedId((cur) => (cur === id ? null : cur)), 1500)
    } catch {
      /* clipboard 不可用时静默 */
    }
  }

  const startEdit = (id: string, text: string) => {
    setEditingId(id)
    setDraft(text)
  }

  const saveEdit = (id: string) => {
    const text = draft.trim()
    setEditingId(null)
    if (text) onEditMessage?.(id, text)
  }

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  return (
    <div className="flex-1 overflow-y-auto scrollbar-fade px-4 py-8 md:px-12">
      <div className="max-w-5xl mx-auto space-y-8">
        {messages.map((msg) => {
          const isUser = msg.role === 'user'
          const bubbleWidthClass = isUser
            ? 'max-w-[90%] md:max-w-[72%]'
            : 'max-w-[95%] md:max-w-[90%]'

          return (
            <div
              key={msg.id}
              className={`flex w-full ${isUser ? 'justify-end' : 'justify-start'} animate-in fade-in slide-in-from-bottom-4 duration-500`}
            >
              <div className={`flex ${bubbleWidthClass} gap-4 ${isUser ? 'flex-row-reverse' : 'flex-row'}`}>
                {/* Avatar */}
                {!isUser && (
                  <div className="flex-shrink-0 mt-1">
                    <div
                      className="w-10 h-10 rounded-2xl flex items-center justify-center border shadow-sm"
                      style={{
                        backgroundColor: `${currentPersona.hex}15`,
                        borderColor: `${currentPersona.hex}30`,
                      }}
                    >
                      <Icon className="w-5 h-5" style={{ color: currentPersona.hex }} />
                    </div>
                  </div>
                )}

                {/* Bubble Container */}
                <div className="flex flex-col gap-1 min-w-0">
                  {/* Name Tag for AI */}
                  {!isUser && (
                    <span className="text-xs font-semibold px-1 mb-1" style={{ color: currentPersona.hex }}>
                      {currentPersona.name}
                    </span>
                  )}

                  {/* Thinking Process (if any) */}
                  {!isUser && msg.thinking && (
                    <ThinkingUI content={msg.thinking} />
                  )}

                  <div
                    className={`px-5 py-4 text-[15px] leading-relaxed shadow-sm break-words min-h-[56px] ${
                      isUser
                        ? 'bg-emerald-600 text-white rounded-2xl rounded-tr-sm shadow-emerald-600/20'
                        : 'bg-[var(--bg-card)] border border-[var(--border-color)] text-[var(--text-primary)] rounded-2xl rounded-tl-sm'
                    }`}
                  >
                    {!isUser && !msg.content ? (
                      <div className="flex items-center h-full pt-1">
                        <TypingIndicator personaName={currentPersona.name} color={currentPersona.hex} />
                      </div>
                    ) : editingId === msg.id ? (
                      <div className="flex flex-col gap-2 min-w-[260px]">
                        <textarea
                          autoFocus
                          value={draft}
                          onChange={(e) => setDraft(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.nativeEvent.isComposing || e.keyCode === 229) return
                            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); saveEdit(msg.id) }
                            if (e.key === 'Escape') setEditingId(null)
                          }}
                          className="w-full min-h-[72px] rounded-lg bg-white/10 text-white placeholder-white/60 p-2 text-[15px] outline-none resize-y border border-white/20"
                        />
                        <div className="flex items-center justify-end gap-2">
                          <button onClick={() => setEditingId(null)}
                            className="text-[11px] px-2 py-1 rounded-md bg-white/10 hover:bg-white/20 flex items-center gap-1">
                            <X className="w-3 h-3" /> {t('chat.actions.cancel')}
                          </button>
                          <button onClick={() => saveEdit(msg.id)}
                            className="text-[11px] px-2 py-1 rounded-md bg-white text-emerald-700 hover:bg-white/90 flex items-center gap-1">
                            <Check className="w-3 h-3" /> {t('chat.actions.saveResend')}
                          </button>
                        </div>
                      </div>
                    ) : (
                      <MarkdownContent content={msg.content} isUser={isUser} />
                    )}
                  </div>

                  {/* Timestamp + Actions (复制 / 编辑 / 双镜) */}
                  {editingId !== msg.id && (
                  <div className={`flex items-center gap-2 mt-1 ${isUser ? 'justify-end pr-1' : 'justify-start pl-1'}`}>
                    <span className="text-[10px] text-[var(--text-muted)]">
                      {format(msg.timestamp, 'HH:mm')}
                    </span>
                    {msg.content && (
                      <button onClick={() => handleCopy(msg.id, msg.content)}
                        className="text-[10px] text-[var(--text-muted)] hover:text-emerald-500 flex items-center gap-0.5 transition-colors"
                        title={t('chat.actions.copy')}>
                        {copiedId === msg.id
                          ? <><Check className="w-3 h-3" /> {t('chat.actions.copied')}</>
                          : <Copy className="w-3 h-3" />}
                      </button>
                    )}
                    {isUser && onEditMessage && (
                      <button onClick={() => startEdit(msg.id, msg.content)}
                        className="text-[10px] text-[var(--text-muted)] hover:text-emerald-500 flex items-center gap-0.5 transition-colors"
                        title={t('chat.actions.edit')}>
                        <Pencil className="w-3 h-3" />
                      </button>
                    )}
                    {isUser && onSendToArena && (
                      <button onClick={() => onSendToArena(msg.content)}
                        className="text-[10px] text-[var(--text-muted)] hover:text-emerald-500 flex items-center gap-0.5 transition-colors"
                        title={t('chat.actions.sendToArena')}>
                        <SplitSquareHorizontal className="w-3 h-3" />
                      </button>
                    )}
                  </div>
                  )}
                </div>
              </div>
            </div>
          )
        })}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
