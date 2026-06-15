import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Activity, MessageSquare } from 'lucide-react'
import { api } from '../lib/api'
import type { ChatSession } from '../lib/api'
import { DialogueProgressAnalysis } from '../components/supervision/DialogueProgressAnalysis'
import { PERSONAS } from '../constants'
import { SessionOptions } from '../components/shared/SessionOptions'

export function CommunicationStatusPage() {
  const { t } = useTranslation()
  const [sessions, setSessions] = useState<ChatSession[]>([])
  const [loading, setLoading] = useState(true)

  const fetchSessions = () => {
    api.listSessions()
      .then((list) => {
        // 按更新时间倒序排序，最多显示最近 10 条有关联对话进展的数据
        const sorted = list.sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())
        setSessions(sorted.slice(0, 10))
      })
      .catch((err) => console.error('Failed to load sessions:', err))
      .finally(() => {
        setLoading(false)
      })
  }

  useEffect(() => {
    fetchSessions()
  }, [])

  return (
    <div className="flex-1 overflow-y-auto w-full h-full p-6">
      <div className="max-w-6xl mx-auto space-y-8">
        
        {/* Header */}
        <div className="relative">
          <div className="absolute inset-0 bg-gradient-to-r from-blue-500/10 to-violet-500/10 rounded-3xl" />
          <div className="relative p-8">
            <div className="flex items-center gap-3 mb-3">
              <div className="p-2.5 rounded-xl bg-blue-500/20 border border-blue-500/30">
                <Activity className="w-6 h-6 text-blue-500" />
              </div>
              <h1 className="text-3xl font-bold tracking-tight text-[var(--text-primary)]">
                {t('communicationStatus.title')}
              </h1>
            </div>
            <p className="text-[var(--text-secondary)] text-lg max-w-3xl leading-relaxed">
              {t('communicationStatus.subtitle')}
            </p>
          </div>
        </div>

        {/* Content */}
        {loading ? (
          <div className="flex justify-center items-center py-20 px-4 text-[var(--text-muted)] animate-pulse">
            {t('communicationStatus.loading')}
          </div>
        ) : sessions.length === 0 ? (
          <div className="flex flex-col items-center justify-center p-16 text-center bg-[var(--bg-card)] rounded-2xl border border-dashed border-[var(--border-color)]">
            <MessageSquare className="w-12 h-12 text-[var(--text-muted)] mb-4 opacity-50" />
            <h3 className="text-xl font-semibold text-[var(--text-primary)] mb-2">{t('communicationStatus.noRecords')}</h3>
            <p className="text-[var(--text-secondary)]">
              {t('communicationStatus.noRecordsDesc')}
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
            {sessions.map((session) => {
              const persona = PERSONAS.find(p => p.id === session.agent_type) || PERSONAS[0]
              
              return (
                <div key={session.id} className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border-color)] overflow-hidden shadow-sm hover:shadow-md transition-shadow flex flex-col">
                  {/* Card Header */}
                  <div className="p-5 border-b border-[var(--border-color)]/50 bg-[var(--bg-secondary)]/30">
                    <div className="flex items-start justify-between gap-4">
                      <div className="min-w-0 flex-1">
                        <h3 className="text-lg font-bold text-[var(--text-primary)] truncate mb-1">
                          {session.title || t('chat.unnamedSession')}
                        </h3>
                        <div className="flex items-center gap-3 text-xs text-[var(--text-muted)]">
                          <div className="flex items-center gap-1">
                            <persona.icon className="w-3.5 h-3.5" style={{ color: persona.hex }} />
                            <span className="font-medium px-1" style={{ color: persona.hex }}>{t('persona.' + persona.id + '.name')}</span>
                          </div>
                          <span>·</span>
                          <span>{new Date(session.updated_at).toLocaleString('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</span>
                          {session.communication_status && (
                            <>
                              <span>·</span>
                              <span className="px-1.5 py-0.5 rounded bg-[var(--text-primary)]/5 font-medium">
                                {t('communicationStatus.status', { status: session.communication_status })}
                              </span>
                            </>
                          )}
                        </div>
                      </div>
                      <SessionOptions
                        sessionId={session.id}
                        initialTitle={session.title || t('chat.unnamedSession')}
                        onRename={async (id, title) => { await api.renameSession(id, title); fetchSessions(); }}
                        onDelete={async (id) => { await api.deleteSession(id); fetchSessions(); }}
                      />
                    </div>
                  </div>
                  
                  {/* Card Body - Dialogue Progress Analysis */}
                  <div className="flex-1 p-5 min-h-0 bg-[var(--bg-card)]">
                    <DialogueProgressAnalysis sessionId={session.id} defaultExpanded={true} />
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
