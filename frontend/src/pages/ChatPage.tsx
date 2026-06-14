import { useState, useCallback, useEffect, useMemo, type ChangeEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { ChatSidebar } from '../components/chat/ChatSidebar'
import { ChatTopBar } from '../components/chat/ChatTopBar'
import { ChatArea } from '../components/chat/ChatArea'
import { BottomInput } from '../components/chat/BottomInput'
import type { Message, Persona, ChatMode, Session } from '../types'
import { PERSONAS } from '../constants'
import { api, type AvailableModel, type ChatSessionSearchResult, type ModelPreferences } from '../lib/api'
import { SafetyDisclaimer } from '../components/safety/SafetyDisclaimer'
import { ExportDialog, chatToExportData } from '../components/shared/ExportDialog'
import { SupervisionStatePanel } from '../components/supervision/SupervisionStatePanel'
import { DialogueProgressAnalysis } from '../components/supervision/DialogueProgressAnalysis'

const FALLBACK_CHAT_MODELS: AvailableModel[] = [
  { backend: 'deepseek', model: 'deepseek-ai/DeepSeek-V3.1', base_url: 'https://api.example.com/v1', suitable_for: ['chat'] },
]

const modelKey = (m: AvailableModel) => `${m.backend}::${m.model}`

type RawConversationTurn = {
  role?: string
  speaker?: string
  content?: string
  text?: string
  message?: string
  thinking?: string
  timestamp?: string | number
}

type RawConversationPayload =
  | RawConversationTurn[]
  | {
    messages?: RawConversationTurn[]
    conversation?: RawConversationTurn[]
    turns?: RawConversationTurn[]
  }

interface SampleConversationEntry {
  id: string
  sessionId: number
  title: string
  time: string
  source: 'public' | 'local'
  fileName?: string
  payload?: RawConversationPayload
}

interface ChatPageProps {
  initialPersona: Persona | null
  onReturnToWelcome: () => void
  onPersonaRouteChange?: (personaId: Persona['id']) => void
  searchTargetSession?: ChatSessionSearchResult | null
  onSearchTargetConsumed?: () => void
}

export function ChatPage({
  initialPersona,
  onReturnToWelcome,
  onPersonaRouteChange,
  searchTargetSession,
  onSearchTargetConsumed,
}: ChatPageProps) {
  const { t } = useTranslation()
  const [currentPersona, setCurrentPersona] = useState<Persona>(initialPersona || PERSONAS[0])
  const [currentSessionId, setCurrentSessionId] = useState<number | null>(1)
  const [mode, setMode] = useState<ChatMode>('listen')
  const [messages, setMessages] = useState<Message[]>([])
  const [isTyping, setIsTyping] = useState(false)
  const [backendSessionId, setBackendSessionId] = useState<string | null>(null)
  const [chatModels, setChatModels] = useState<AvailableModel[]>(FALLBACK_CHAT_MODELS)
  const [selectedModelKey, setSelectedModelKey] = useState(modelKey(FALLBACK_CHAT_MODELS[0]))
  const [useRag, setUseRag] = useState(true)
  const [useKnowledge, setUseKnowledge] = useState(true)
  const [eftStage, setEftStage] = useState<string | null>(null)
  const [sampleConversations, setSampleConversations] = useState<SampleConversationEntry[]>([])
  const [loadingSample, setLoadingSample] = useState<string | null>(null)
  const [remoteSessions, setRemoteSessions] = useState<Session[]>([])
  const [showExport, setShowExport] = useState(false)
  const [supervisionState, setSupervisionState] = useState<{ singlePerspectiveRisk?: boolean; attachmentLevel?: '低' | '中' | '高' } | null>(null)

  const fetchRemoteSessions = useCallback(() => {
    api.listSessions().then((list) => {
      setRemoteSessions(
        list.map((s) => ({
          id: parseInt(s.id, 16) || Math.abs(s.id.split('').reduce((h, c) => ((h << 5) - h + c.charCodeAt(0)) | 0, 0)),
          backendSessionId: s.id,
          title: s.title || t('chat.unnamedSession'),
          time: s.updated_at ? new Date(s.updated_at).toLocaleString('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '',
          personaId: s.agent_type || 'neutral',
          active: false,
          communication_status: s.communication_status,
        } as Session & { backendSessionId: string; communication_status?: string }))
      )
    }).catch(() => {})
  }, [t])

  useEffect(() => {
    fetchRemoteSessions()
    const timer = setInterval(fetchRemoteSessions, 10000)
    return () => clearInterval(timer)
  }, [fetchRemoteSessions])

  // §4.6 监督状态：有 backendSessionId 时轮询 supervision
  useEffect(() => {
    if (!backendSessionId) {
      setSupervisionState(null)
      return
    }
    const fetchSupervision = () => {
      api.getSupervisionSession(backendSessionId!).then((res) => {
        const last = res.supervision_state?.last_judge_analysis as Record<string, unknown> | undefined
        if (!last) return
        const sp = last.single_perspective_risk as { is_risk?: boolean } | undefined
        const att = last.attachment_signal as { level?: string } | undefined
        setSupervisionState({
          singlePerspectiveRisk: sp?.is_risk === true,
          attachmentLevel: (att?.level as '低' | '中' | '高') || undefined,
        })
      }).catch(() => {})
    }
    fetchSupervision()
    const timer = setInterval(fetchSupervision, 15000)
    return () => clearInterval(timer)
  }, [backendSessionId])

  useEffect(() => {
    setCurrentPersona(initialPersona || PERSONAS[0])
  }, [initialPersona])

  useEffect(() => {
    let mounted = true

    Promise.all([
      api.getAvailableModels().catch(() => [] as AvailableModel[]),
      api.getModelPreferences().catch(() => null as ModelPreferences | null),
    ]).then(([available, prefs]) => {
      if (!mounted) return

      const candidates = available.filter((m) => m.suitable_for.includes('chat'))
      const unique = Array.from(
        new Map([...candidates, ...FALLBACK_CHAT_MODELS].map((m) => [modelKey(m), m])).values(),
      )
      const preferred = prefs?.chat_backend
      const selected = unique.find((m) => m.backend === preferred)
        || unique.find((m) => m.backend === 'deepseek')
        || unique[0]

      setChatModels(unique)
      setSelectedModelKey(modelKey(selected))
    })

    return () => {
      mounted = false
    }
  }, [])

  useEffect(() => {
    let mounted = true

    fetch('/chat-samples/manifest.json')
      .then((res) => {
        if (!res.ok) throw new Error('manifest missing')
        return res.json() as Promise<string[]>
      })
      .then((files) => {
        if (!mounted || !Array.isArray(files)) return
        const publicSamples = files
          .filter((f) => typeof f === 'string')
          .map((file, idx) => ({
            id: `public:${file}`,
            sessionId: 1000 + idx,
            title: file.replace(/\.json$/i, ''),
            time: t('chat.sampleTag'),
            source: 'public' as const,
            fileName: file,
          }))

        setSampleConversations((prev) => {
          const locals = prev.filter((item) => item.source === 'local')
          return [...publicSamples, ...locals]
        })
      })
      .catch(() => {
        if (mounted) setSampleConversations((prev) => prev.filter((item) => item.source === 'local'))
      })

    return () => {
      mounted = false
    }
  }, [t])

  const selectedModel = useMemo(
    () => chatModels.find((m) => modelKey(m) === selectedModelKey) || chatModels[0],
    [chatModels, selectedModelKey],
  )

  const parseConversationPayload = useCallback((payload: RawConversationPayload): Message[] => {
    const list = Array.isArray(payload)
      ? payload
      : payload.messages || payload.conversation || payload.turns || []

    return list
      .filter((item) => item && (item.content || item.text || item.message))
      .map((item, idx) => {
        const rawRole = (item.role || item.speaker || '').toLowerCase()
        const isAssistant = rawRole.includes('assistant') || rawRole.includes('advisor') || rawRole.includes('ai')
        const content = item.content || item.text || item.message || ''
        const ts = item.timestamp ? new Date(item.timestamp) : new Date(Date.now() + idx * 1000)

        return {
          id: `sample-${idx}-${Math.random().toString(16).slice(2)}`,
          role: isAssistant ? 'assistant' : 'user',
          content,
          timestamp: Number.isNaN(ts.getTime()) ? new Date() : ts,
          personaId: currentPersona.id,
          thinking: item.thinking,
        } as Message
      })
  }, [currentPersona.id])

  const applyConversationPayload = useCallback((payload: RawConversationPayload) => {
    const parsed = parseConversationPayload(payload)
    if (parsed.length > 0) {
      setMessages(parsed)
      setBackendSessionId(null)
    }
  }, [parseConversationPayload])

  const loadSampleConversation = useCallback(async (entry: SampleConversationEntry) => {
    setLoadingSample(entry.id)
    try {
      if (entry.source === 'local' && entry.payload) {
        applyConversationPayload(entry.payload)
      } else if (entry.fileName) {
        const res = await fetch(`/chat-samples/${entry.fileName}`)
        if (!res.ok) throw new Error(`加载失败: ${entry.fileName}`)
        const payload = await res.json() as RawConversationPayload
        applyConversationPayload(payload)
      }
    } catch {
      // swallow and keep current chat state
    } finally {
      setLoadingSample(null)
    }
  }, [applyConversationPayload])

  const handleUploadSampleFiles = useCallback(async (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files || [])
    if (files.length === 0) return

    const now = Date.now()
    const parsed = await Promise.all(
      files.map(async (file, idx) => {
        try {
          const text = await file.text()
          const payload = JSON.parse(text) as RawConversationPayload
          return {
            id: `local:${file.name}:${now}:${idx}`,
            sessionId: 2000 + now + idx,
            title: file.name.replace(/\.json$/i, ''),
            time: t('chat.localTag'),
            source: 'local' as const,
            payload,
          } as SampleConversationEntry
        } catch {
          return null
        }
      }),
    )

    const nextEntries = parsed.filter((item): item is SampleConversationEntry => Boolean(item))
    if (nextEntries.length > 0) {
      setSampleConversations((prev) => {
        const withoutSameTitle = prev.filter(
          (existing) => !nextEntries.some((item) => item.title === existing.title && existing.source === 'local'),
        )
        return [...nextEntries, ...withoutSameTitle]
      })
    }

    event.target.value = ''
  }, [t])

  const recentSessions = useMemo<Session[]>(() => {
    const importedSessions: Session[] = sampleConversations.map((entry) => ({
      id: entry.sessionId,
      title: `[${entry.source === 'local' ? t('chat.localTag') : t('chat.sampleTag')}] ${entry.title}`,
      time: entry.time,
      personaId: currentPersona.id,
      active: currentSessionId === entry.sessionId,
    }))

    const backendSessions = remoteSessions.map((session) => ({
      ...session,
      active: currentSessionId === session.id,
    }))

    return [...importedSessions, ...backendSessions]
  }, [currentPersona.id, currentSessionId, sampleConversations, remoteSessions, t])

  const handleSessionSelect = useCallback((id: number) => {
    setCurrentSessionId(id)
    const sample = sampleConversations.find((item) => item.sessionId === id)
    if (sample) {
      void loadSampleConversation(sample)
      return
    }
    const remoteSession = remoteSessions.find((s) => s.id === id) as (Session & { backendSessionId?: string }) | undefined
    if (remoteSession?.backendSessionId) {
      setIsTyping(true)
      api.getSession(remoteSession.backendSessionId).then((detail) => {
        const loaded: Message[] = (detail.messages || []).map((msg, idx) => {
          const ts = msg.timestamp ? new Date(msg.timestamp) : new Date(Date.now() + idx * 1000)
          return {
            id: `${detail.id}-${idx}`,
            role: msg.role,
            content: msg.content || '',
            timestamp: Number.isNaN(ts.getTime()) ? new Date() : ts,
            personaId: detail.agent_type || currentPersona.id,
          }
        })
        setMessages(loaded)
        setBackendSessionId(detail.id)
        setMode(detail.mode === 'consult' ? 'deep' : 'listen')
      }).catch(() => {}).finally(() => setIsTyping(false))
      return
    }
    setMessages([])
    setBackendSessionId(null)
  }, [loadSampleConversation, sampleConversations, remoteSessions, currentPersona.id])

  const handleSendMessage = useCallback(async (content: string) => {
    if (!content.trim()) return

    const assistantId = `${Date.now()}-assistant`
    const newMessage: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: content,
      timestamp: new Date(),
      personaId: currentPersona.id,
    }

    setMessages((prev) => [
      ...prev,
      newMessage,
      {
        id: assistantId,
        role: 'assistant',
        content: '',
        timestamp: new Date(),
        personaId: currentPersona.id,
      },
    ])
    setIsTyping(true)

    const updateAssistant = (patch: Partial<Message>) => {
      setMessages((prev) =>
        prev.map((msg) => (msg.id === assistantId ? { ...msg, ...patch } : msg)),
      )
    }

    let answerBuffer = ''
    let thinkingBuffer = ''

    try {
      for await (const token of api.chatStream({
        message: content,
        agent_type: currentPersona.id,
        mode: mode === 'deep' ? 'consult' : 'listen',
        backend: selectedModel?.backend || 'deepseek',
        session_id: backendSessionId || undefined,
        use_rag: useRag,
        use_knowledge: useKnowledge,
      })) {
        if (token.startsWith('__SESSION_ID__')) {
          const sid = token.replace('__SESSION_ID__', '')
          setBackendSessionId(sid)
          fetchRemoteSessions()
          if (currentPersona.id === 'eft') {
            api.getSession(sid).then(s => setEftStage(s.eft_stage ?? null)).catch(() => {})
          }
          continue
        }

        if (token === '__THINKING_DONE__') {
          continue
        }

        if (token.startsWith('__THINKING__')) {
          thinkingBuffer += token.replace('__THINKING__', '')
          updateAssistant({ thinking: thinkingBuffer })
          continue
        }

        answerBuffer += token
        updateAssistant({ content: answerBuffer })
      }

      if (!answerBuffer.trim()) {
        updateAssistant({ content: t('chat.noModelResponse') })
      }
    } catch (error) {
      const raw = error instanceof Error ? error.message : String(error)
      let message = raw

      if (raw.startsWith('__STRUCTURED__')) {
        try {
          const payload = JSON.parse(raw.replace('__STRUCTURED__', '')) as {
            error?: string
            failed_backend?: string
            available_backends?: string[]
          }
          const alternatives = (payload.available_backends || []).join(' / ')
          message = payload.error || '模型调用失败'
          if (alternatives) {
            message += `\n可切换后端：${alternatives}`
          }
        } catch {
          message = '模型调用失败，请稍后重试。'
        }
      } else {
        // Fallback for native errors like NetworkError or 500
        message = `系统异常: ${raw === 'Load failed' || raw === 'Failed to fetch' ? '网络连接异常，请检查后端服务' : raw}`
      }

      updateAssistant({ content: `**[System Error]** ${message}` })
      toast.error(message)
    } finally {
      setIsTyping(false)
      if (currentPersona.id === 'eft' && backendSessionId) {
        api.getSession(backendSessionId).then(s => setEftStage(s.eft_stage ?? null)).catch(() => {})
      }
    }
  }, [backendSessionId, currentPersona, mode, selectedModel, useRag, useKnowledge, fetchRemoteSessions, t])

  const handleClearMessages = useCallback(() => {
    setMessages([])
    setBackendSessionId(null)
    setEftStage(null)
  }, [])

  const handleNewChat = () => {
    handleClearMessages()
    onReturnToWelcome()
  }

  const handleSwitchPersona = useCallback((personaId: Persona['id']) => {
    const next = PERSONAS.find((p) => p.id === personaId)
    if (!next || next.id === currentPersona.id) return
    setCurrentPersona(next)
    handleClearMessages()
    onPersonaRouteChange?.(next.id)
  }, [currentPersona.id, handleClearMessages, onPersonaRouteChange])

  useEffect(() => {
    if (!searchTargetSession) return

    const matchedPersona = PERSONAS.find((p) => p.id === searchTargetSession.agent_type)
    const targetPersonaId = matchedPersona?.id || PERSONAS[0].id
    if (matchedPersona && matchedPersona.id !== currentPersona.id) {
      setCurrentPersona(matchedPersona)
      onPersonaRouteChange?.(matchedPersona.id)
    }

    let active = true
    setIsTyping(true)
    const loadPromise = searchTargetSession.source === 'sample' && searchTargetSession.sample_file
      ? fetch(`/chat-samples/${searchTargetSession.sample_file}`)
        .then(async (res) => {
          if (!res.ok) throw new Error('sample missing')
          const payload = await res.json() as RawConversationPayload
          const parsed = parseConversationPayload(payload).map((m) => ({ ...m, personaId: targetPersonaId }))
          if (!active) return
          setMessages(parsed)
          setBackendSessionId(null)
          setMode('listen')
        })
      : api.getSession(searchTargetSession.id)
        .then((session) => {
          if (!active) return
          const nextMessages: Message[] = (session.messages || []).map((msg, idx) => {
            const rawTime = msg.timestamp ? new Date(msg.timestamp) : new Date(Date.now() + idx * 1000)
            return {
              id: `${searchTargetSession.id}-${idx}`,
              role: msg.role,
              content: msg.content || '',
              timestamp: Number.isNaN(rawTime.getTime()) ? new Date() : rawTime,
              personaId: targetPersonaId,
            }
          })
          setMessages(nextMessages)
          setBackendSessionId(session.id)
          setMode(session.mode === 'consult' ? 'deep' : 'listen')
        })

    loadPromise
      .catch(() => {
        if (!active) return
      })
      .finally(() => {
        if (!active) return
        setIsTyping(false)
        onSearchTargetConsumed?.()
      })

    return () => {
      active = false
    }
  }, [onPersonaRouteChange, onSearchTargetConsumed, parseConversationPayload, searchTargetSession])

  return (
    <div className="flex-1 flex h-full overflow-hidden bg-[var(--bg-primary)] transition-all duration-300">
      <ChatSidebar
        sessions={recentSessions}
        currentSessionId={currentSessionId}
        onSessionSelect={handleSessionSelect}
        onNewChat={handleNewChat}
        onRenameSession={async (id, title) => { await api.renameSession(id, title); fetchRemoteSessions(); }}
        onDeleteSession={async (id) => { await api.deleteSession(id); fetchRemoteSessions(); if (backendSessionId === id) handleNewChat(); }}
      />

      <div className="flex-1 flex flex-col min-w-0 bg-[var(--bg-card)] relative overflow-hidden">
        {/* Subtle Background Gradient */}
        <div
          className="absolute inset-0 pointer-events-none"
          style={{
            background: `radial-gradient(circle at 10% 0%, ${currentPersona.hex}26, transparent 40%), radial-gradient(circle at 90% 20%, #14b8a620, transparent 38%)`,
          }}
        />

        <SafetyDisclaimer />

        <ChatTopBar 
          persona={currentPersona} 
          personaOptions={PERSONAS}
          mode={mode} 
          onModeChange={setMode} 
          useRag={useRag}
          onUseRagChange={setUseRag}
          useKnowledge={useKnowledge}
          onUseKnowledgeChange={setUseKnowledge}
          eftStage={currentPersona.id === 'eft' ? eftStage : null}
          models={chatModels.map((m) => ({
            key: modelKey(m),
            backend: m.backend,
            model: m.model,
            baseUrl: m.base_url,
          }))}
          selectedModelKey={selectedModelKey}
          onModelChange={setSelectedModelKey}
          onClearMessages={handleClearMessages}
          onBackToAdvisors={handleNewChat}
          onSwitchPersona={handleSwitchPersona}
          onExport={() => setShowExport(true)}
          hasMessages={messages.length > 0}
        />

        {messages.length === 0 ? (
          <div className="flex-1 flex flex-col items-center justify-center p-8 text-center animate-in fade-in duration-700">
            <div 
              className="w-24 h-24 rounded-3xl flex items-center justify-center mb-6 shadow-xl"
              style={{ backgroundColor: `${currentPersona.hex}15`, border: `1px solid ${currentPersona.hex}30` }}
            >
              <currentPersona.icon className="w-12 h-12" style={{ color: currentPersona.hex }} />
            </div>
            <h3 className="text-2xl font-bold text-[var(--text-primary)] mb-2">
              {t('welcomeScreen.title', { appName: t('app.name') })} — {currentPersona.name}
            </h3>
            <p className="text-[var(--text-secondary)] max-w-md">
              {currentPersona.description}
            </p>
            <div className="mt-6 w-full max-w-2xl rounded-2xl border border-[var(--border-color)] bg-[var(--bg-card)] p-4 text-left">
              <div className="mb-3 flex items-center justify-between gap-3">
                <p className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                  {t('chat.importRealJSON')}
                </p>
                <label className="cursor-pointer rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-1.5 text-[11px] font-medium text-emerald-700 transition-colors hover:bg-emerald-500/20">
                  {t('chat.uploadLocalJSON')}
                  <input
                    type="file"
                    accept=".json,application/json"
                    multiple
                    onChange={handleUploadSampleFiles}
                    className="hidden"
                  />
                </label>
              </div>
              {sampleConversations.length > 0 ? (
                <div className="grid gap-2 sm:grid-cols-2">
                  {sampleConversations.map((entry) => (
                    <button
                      key={entry.id}
                      onClick={() => {
                        setCurrentSessionId(entry.sessionId)
                        void loadSampleConversation(entry)
                      }}
                      disabled={loadingSample === entry.id}
                      className="rounded-xl border border-emerald-500/20 bg-gradient-to-r from-emerald-500/10 to-teal-500/10 px-3 py-2 text-left text-xs text-[var(--text-primary)] transition-all hover:from-emerald-500/20 hover:to-teal-500/20 disabled:opacity-50"
                    >
                      <p className="truncate font-medium">{entry.title}</p>
                      <p className="text-[10px] text-[var(--text-muted)]">{entry.source === 'local' ? t('chat.localTag') : t('chat.fromPublicSamples')}</p>
                    </button>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-[var(--text-muted)]">{t('chat.uploadHint')}</p>
              )}
            </div>
          </div>
        ) : (
          <div className="flex-1 flex flex-col overflow-hidden">
            {backendSessionId && (
              <div className="shrink-0 px-4 pt-4 grid grid-cols-1 xl:grid-cols-2 gap-3 items-start">
                <SupervisionStatePanel
                  singlePerspectiveRisk={supervisionState?.singlePerspectiveRisk}
                  attachmentLevel={supervisionState?.attachmentLevel}
                  onGoToArena={() => {
                    const lastUser = [...messages].reverse().find((m) => m.role === 'user')
                    if (lastUser?.content) {
                      sessionStorage.setItem('arena-prefill', lastUser.content)
                      sessionStorage.setItem('arena-prefill-persona', currentPersona.id)
                    }
                    window.history.pushState(null, '', '/arena')
                    window.dispatchEvent(new PopStateEvent('popstate'))
                  }}
                />
                <DialogueProgressAnalysis sessionId={backendSessionId} />
              </div>
            )}
            <div className="flex-1 overflow-y-auto">
              <ChatArea messages={messages} currentPersona={currentPersona}
                onSendToArena={(content) => {
                  sessionStorage.setItem('arena-prefill', content)
                  sessionStorage.setItem('arena-prefill-persona', currentPersona.id)
                  window.history.pushState(null, '', '/arena')
                  window.dispatchEvent(new PopStateEvent('popstate'))
                }}
              />
            </div>
          </div>
        )}

        <BottomInput onSend={handleSendMessage} disabled={isTyping} isThinking={isTyping} />
      </div>

      <ExportDialog
        open={showExport}
        onClose={() => setShowExport(false)}
        title={t('chat.exportDialogTitle')}
        getData={() => chatToExportData(
          messages.map(m => ({ role: m.role, content: m.content, timestamp: m.timestamp })),
          messages[0]?.content?.slice(0, 20),
        )}
      />
    </div>
  )
}
