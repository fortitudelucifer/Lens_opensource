import { Plus, Clock } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type { Session } from '../../types'

type SessionWithStatus = Session & { communication_status?: string }
import { PERSONAS } from '../../constants'
import { SessionOptions } from '../shared/SessionOptions'

interface ChatSidebarProps {
  sessions: Session[]
  currentSessionId: number | null
  onSessionSelect: (id: number) => void
  onNewChat: () => void
  onRenameSession: (backendId: string, newTitle: string) => Promise<void>
  onDeleteSession: (backendId: string) => Promise<void>
}

export function ChatSidebar({ sessions, currentSessionId, onSessionSelect, onNewChat, onRenameSession, onDeleteSession }: ChatSidebarProps) {
  const { t } = useTranslation()
  return (
    <div className="w-72 border-r border-[var(--border-color)] bg-[var(--bg-card)] flex flex-col h-full z-10 hidden lg:flex">
      {/* New Chat Button */}
      <div className="p-4 border-b border-[var(--border-color)]">
        <button
          onClick={onNewChat}
          className="w-full flex items-center justify-center gap-2 bg-gradient-to-r from-emerald-500/10 to-teal-500/10 hover:from-emerald-500/20 hover:to-teal-500/20 border border-emerald-500/20 text-emerald-600 rounded-xl transition-all py-3 px-4 shadow-sm group"
        >
          <Plus className="w-4 h-4 group-hover:scale-110 transition-transform" />
          <span className="font-semibold text-sm">{t('chat.sidebar.newChat')}</span>
        </button>
      </div>

      {/* Session List */}
      <div className="flex-1 overflow-y-auto scrollbar-thin p-4 space-y-1">
        <div className="px-2 mb-3 text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-wider">
          {t('chat.sidebar.recentSessions')}
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
                <div className="flex items-start justify-between">
                  <h3 className={`text-sm font-medium truncate mb-1 pr-2 ${isActive ? 'text-[var(--text-primary)]' : 'text-[var(--text-secondary)] group-hover:text-[var(--text-primary)]'}`}>
                    {session.title}
                  </h3>
                  {session.backendSessionId && (
                    <SessionOptions
                      sessionId={session.backendSessionId}
                      initialTitle={session.title}
                      onRename={onRenameSession}
                      onDelete={onDeleteSession}
                      className="-mt-1 -mr-1"
                    />
                  )}
                </div>
                <div className="flex items-center justify-between text-xs">
                  <span className="truncate text-[10px] uppercase font-semibold" style={{ color: persona.hex }}>
                    {t('persona.' + persona.id + '.name')}
                  </span>
                  <div className="flex items-center gap-1 text-[var(--text-muted)]">
                    <Clock className="w-3 h-3" />
                    <span>{session.time}</span>
                  </div>
                </div>
                {(session as SessionWithStatus).communication_status && (
                  <p className="text-[10px] text-[var(--text-muted)] mt-1">
                    {t('chat.sidebar.commStatus', { status: (session as SessionWithStatus).communication_status })}
                  </p>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
