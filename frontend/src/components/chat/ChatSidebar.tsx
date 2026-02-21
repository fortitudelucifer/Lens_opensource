import { Plus, Clock } from 'lucide-react'
import type { Session } from '../../types'
import { PERSONAS } from '../../constants'

interface ChatSidebarProps {
  sessions: Session[]
  currentSessionId: number | null
  onSessionSelect: (id: number) => void
  onNewChat: () => void
}

export function ChatSidebar({ sessions, currentSessionId, onSessionSelect, onNewChat }: ChatSidebarProps) {
  return (
    <div className="w-72 border-r border-[var(--border-color)] bg-[var(--bg-card)] flex flex-col h-full z-10 hidden lg:flex">
      {/* New Chat Button */}
      <div className="p-4 border-b border-[var(--border-color)]">
        <button
          onClick={onNewChat}
          className="w-full flex items-center justify-center gap-2 bg-gradient-to-r from-emerald-500/10 to-teal-500/10 hover:from-emerald-500/20 hover:to-teal-500/20 border border-emerald-500/20 text-emerald-600 rounded-xl transition-all py-3 px-4 shadow-sm group"
        >
          <Plus className="w-4 h-4 group-hover:scale-110 transition-transform" />
          <span className="font-semibold text-sm">开始新互动</span>
        </button>
      </div>

      {/* Session List */}
      <div className="flex-1 overflow-y-auto p-4 space-y-1 scrollbar-thin">
        <div className="px-2 mb-3 text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-wider">
          近期会话
        </div>

        {sessions.map((session) => {
          const persona = PERSONAS.find((p) => p.id === session.personaId) || PERSONAS[0]
          const isActive = currentSessionId === session.id

          return (
            <div
              key={session.id}
              onClick={() => onSessionSelect(session.id)}
              className={`group relative rounded-xl transition-all duration-300 cursor-pointer border p-3 flex items-start gap-3 ${
                isActive 
                  ? 'bg-emerald-500/5 border-emerald-500/20 shadow-sm' 
                  : 'bg-transparent border-transparent hover:bg-[var(--bg-secondary)]'
              }`}
            >
              <div
                className={`mt-1.5 w-2 h-2 rounded-full shrink-0 shadow-sm`}
                style={{ backgroundColor: persona.hex }}
              />
              <div className="flex-1 min-w-0">
                <h3 className={`text-sm font-medium truncate mb-1 ${isActive ? 'text-[var(--text-primary)]' : 'text-[var(--text-secondary)] group-hover:text-[var(--text-primary)]'}`}>
                  {session.title}
                </h3>
                <div className="flex items-center justify-between text-xs">
                  <span className="truncate text-[10px] uppercase font-semibold" style={{ color: persona.hex }}>
                    {persona.name}
                  </span>
                  <div className="flex items-center gap-1 text-[var(--text-muted)]">
                    <Clock className="w-3 h-3" />
                    <span>{session.time}</span>
                  </div>
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
