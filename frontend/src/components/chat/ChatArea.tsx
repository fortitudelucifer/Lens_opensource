import { useEffect, useRef } from 'react'
import type { Message, Persona } from '../../types'
import { ThinkingUI } from './ThinkingUI'
import { MarkdownContent } from './MarkdownContent'
import { format } from 'date-fns'

interface ChatAreaProps {
  messages: Message[]
  currentPersona: Persona
}

export function ChatArea({ messages, currentPersona }: ChatAreaProps) {
  const bottomRef = useRef<HTMLDivElement>(null)
  const Icon = currentPersona.icon

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  return (
    <div className="flex-1 overflow-y-auto px-4 py-8 md:px-12 scrollbar-thin scrollbar-thumb-[var(--border-color)] scrollbar-track-transparent">
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

                  {/* Message Bubble */}
                  <div
                    className={`px-5 py-4 text-[15px] leading-relaxed shadow-sm break-words ${
                      isUser
                        ? 'bg-emerald-600 text-white rounded-2xl rounded-tr-sm shadow-emerald-600/20'
                        : 'bg-[var(--bg-card)] border border-[var(--border-color)] text-[var(--text-primary)] rounded-2xl rounded-tl-sm'
                    }`}
                  >
                    <MarkdownContent content={msg.content} isUser={isUser} />
                  </div>

                  {/* Timestamp */}
                  <span
                    className={`text-[10px] text-[var(--text-muted)] mt-1 ${isUser ? 'text-right pr-1' : 'text-left pl-1'}`}
                  >
                    {format(msg.timestamp, 'HH:mm')}
                  </span>
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
