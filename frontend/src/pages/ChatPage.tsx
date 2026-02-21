import { useState, useCallback, useEffect, useMemo, type ChangeEvent } from 'react'
import { ChatSidebar } from '../components/chat/ChatSidebar'
import { ChatTopBar } from '../components/chat/ChatTopBar'
import { ChatArea } from '../components/chat/ChatArea'
import { BottomInput } from '../components/chat/BottomInput'
import type { Message, Persona, ChatMode, Session } from '../types'
import { PERSONAS } from '../constants'
import { api, type AvailableModel, type ModelPreferences } from '../lib/api'

const MOCK_SESSIONS: Session[] = [
  { id: 1, title: '关于伴侣沟通边界的困扰', time: '2小时前', personaId: 'supportive', active: true },
  { id: 2, title: '与父母的关系问题', time: '昨天', personaId: 'neutral', active: false },
  { id: 3, title: '自我价值感的探索', time: '3天前', personaId: 'psychoanalytic', active: false },
]

const FALLBACK_CHAT_MODELS: AvailableModel[] = [
  { backend: 'deepseek', model: 'DeepSeek-V3.2', base_url: 'https://api.deepseek.com', suitable_for: ['chat'] },
  { backend: 'qwen_local', model: 'Qwen3-8B-Instruct', base_url: 'http://localhost:8000/v1', suitable_for: ['chat'] },
  { backend: 'glm', model: 'z-ai/glm4.7', base_url: '(默认)', suitable_for: ['chat'] },
  { backend: 'kimi', model: 'Kimi-K2.5', base_url: '(默认)', suitable_for: ['chat'] },
  { backend: 'qwen_cloud', model: 'Qwen/Qwen3-235B-A22B-Thinking-2507', base_url: '(默认)', suitable_for: ['chat'] },
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
}

export function ChatPage({ initialPersona, onReturnToWelcome, onPersonaRouteChange }: ChatPageProps) {
  const [currentPersona, setCurrentPersona] = useState<Persona>(initialPersona || PERSONAS[0])
  const [currentSessionId, setCurrentSessionId] = useState<number | null>(1)
  const [mode, setMode] = useState<ChatMode>('listen')
  const [messages, setMessages] = useState<Message[]>([])
  const [isTyping, setIsTyping] = useState(false)
  const [backendSessionId, setBackendSessionId] = useState<string | null>(null)
  const [chatModels, setChatModels] = useState<AvailableModel[]>(FALLBACK_CHAT_MODELS)
  const [selectedModelKey, setSelectedModelKey] = useState(modelKey(FALLBACK_CHAT_MODELS[0]))
  const [useRag, setUseRag] = useState(true)
  const [sampleConversations, setSampleConversations] = useState<SampleConversationEntry[]>([])
  const [loadingSample, setLoadingSample] = useState<string | null>(null)

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
      const selected = unique.find((m) => m.backend === preferred) || unique[0]

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
            time: '样例',
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
  }, [])

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
            time: '本地导入',
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
  }, [])

  const recentSessions = useMemo<Session[]>(() => {
    const importedSessions: Session[] = sampleConversations.map((entry) => ({
      id: entry.sessionId,
      title: `[${entry.source === 'local' ? '本地' : '样例'}] ${entry.title}`,
      time: entry.time,
      personaId: currentPersona.id,
      active: currentSessionId === entry.sessionId,
    }))

    const defaults = MOCK_SESSIONS.map((session) => ({
      ...session,
      active: currentSessionId === session.id,
    }))

    return [...importedSessions, ...defaults]
  }, [currentPersona.id, currentSessionId, sampleConversations])

  const handleSessionSelect = useCallback((id: number) => {
    setCurrentSessionId(id)
    const sample = sampleConversations.find((item) => item.sessionId === id)
    if (sample) {
      void loadSampleConversation(sample)
      return
    }
    setMessages([])
    setBackendSessionId(null)
  }, [loadSampleConversation, sampleConversations])

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
      })) {
        if (token.startsWith('__SESSION_ID__')) {
          setBackendSessionId(token.replace('__SESSION_ID__', ''))
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
        updateAssistant({ content: '模型未返回内容，请切换模型后重试。' })
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
      }

      updateAssistant({ content: message })
    } finally {
      setIsTyping(false)
    }
  }, [backendSessionId, currentPersona, mode, selectedModel, useRag])

  const handleClearMessages = useCallback(() => {
    setMessages([])
    setBackendSessionId(null)
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

  return (
    <div className="flex-1 flex h-full overflow-hidden bg-[var(--bg-primary)] transition-all duration-300">
      <ChatSidebar
        sessions={recentSessions}
        currentSessionId={currentSessionId}
        onSessionSelect={handleSessionSelect}
        onNewChat={handleNewChat}
      />

      <div className="flex-1 flex flex-col min-w-0 bg-[var(--bg-card)] relative overflow-hidden">
        {/* Subtle Background Gradient */}
        <div
          className="absolute inset-0 pointer-events-none"
          style={{
            background: `radial-gradient(circle at 10% 0%, ${currentPersona.hex}26, transparent 40%), radial-gradient(circle at 90% 20%, #14b8a620, transparent 38%)`,
          }}
        />

        <ChatTopBar 
          persona={currentPersona} 
          personaOptions={PERSONAS}
          mode={mode} 
          onModeChange={setMode} 
          useRag={useRag}
          onUseRagChange={setUseRag}
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
              我是你的{currentPersona.name}
            </h3>
            <p className="text-[var(--text-secondary)] max-w-md">
              {currentPersona.description}
            </p>
            <div className="mt-6 w-full max-w-2xl rounded-2xl border border-[var(--border-color)] bg-[var(--bg-card)] p-4 text-left">
              <div className="mb-3 flex items-center justify-between gap-3">
                <p className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                  导入真实交流 JSON
                </p>
                <label className="cursor-pointer rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-1.5 text-[11px] font-medium text-emerald-700 transition-colors hover:bg-emerald-500/20">
                  上传本地 JSON
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
                      <p className="text-[10px] text-[var(--text-muted)]">{entry.source === 'local' ? '本地导入' : '来自 public/chat-samples'}</p>
                    </button>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-[var(--text-muted)]">先上传本地 JSON，或在 public/chat-samples/manifest.json 中登记样例文件。</p>
              )}
            </div>
          </div>
        ) : (
          <ChatArea messages={messages} currentPersona={currentPersona} />
        )}

        <BottomInput onSend={handleSendMessage} disabled={isTyping} isThinking={isTyping} />
      </div>
    </div>
  )
}
