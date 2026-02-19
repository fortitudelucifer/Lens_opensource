import { useState, useRef, useEffect, useCallback } from "react"
import { Send, Loader2, Sparkles, Heart, Brain, Plus, Trash2, MessageSquare, ChevronLeft, ChevronRight, ChevronDown, ChevronUp, Lightbulb } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"
import { api, type ModelPreferences, type ChatSession, type AvailableModel } from "@/lib/api"

interface Message {
  id: string
  role: "user" | "assistant" | "system"
  content: string
  thinking?: string
  thinkingDone?: boolean
  timestamp: Date
  agentType?: string
  backend?: string
  model?: string
}

const agentConfig = {
  neutral: { label: "中立顾问", icon: Sparkles, color: "text-blue-600", bg: "bg-blue-50" },
  supportive: { label: "支持性顾问", icon: Heart, color: "text-rose-600", bg: "bg-rose-50" },
  psychoanalytic: { label: "精神分析", icon: Brain, color: "text-violet-600", bg: "bg-violet-50" },
}

type AgentType = keyof typeof agentConfig

function stripThink(text: string): string {
  return text.replace(/<think>[\s\S]*?<\/think>\s*/g, "").replace(/<think>[\s\S]*$/g, "").trim()
}

function ThinkingBlock({ thinking, done }: { thinking: string; done: boolean }) {
  const [expanded, setExpanded] = useState(!done)

  // Auto-collapse when thinking finishes
  useEffect(() => {
    if (done) {
      const timer = setTimeout(() => setExpanded(false), 400)
      return () => clearTimeout(timer)
    }
  }, [done])

  if (!thinking.trim()) return null

  return (
    <div className="mb-2">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-1.5 text-[11px] text-muted-foreground hover:text-foreground transition-colors"
      >
        <Lightbulb className="w-3 h-3" />
        <span>{done ? "思考过程" : "正在思考..."}</span>
        {!done && <Loader2 className="w-3 h-3 animate-spin" />}
        {done && (expanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />)}
      </button>
      <div
        className={cn(
          "overflow-hidden transition-all duration-300 ease-in-out",
          expanded ? "max-h-[500px] opacity-100 mt-1.5" : "max-h-0 opacity-0"
        )}
      >
        <div className="text-xs text-muted-foreground bg-muted/60 rounded-lg px-3 py-2 leading-relaxed whitespace-pre-wrap border border-border/50">
          {thinking}
        </div>
      </div>
    </div>
  )
}

export default function ChatPanel() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState("")
  const [loading, setLoading] = useState(false)
  const [agentType, setAgentType] = useState<AgentType>("neutral")
  const [mode, setMode] = useState<"listen" | "consult">("listen")
  const [chatBackend, setChatBackend] = useState("grok")
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [sessions, setSessions] = useState<ChatSession[]>([])
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [availableBackends, setAvailableBackends] = useState<AvailableModel[]>([])
  const scrollRef = useRef<HTMLDivElement>(null)

  // Load preferences and available backends
  useEffect(() => {
    api.getModelPreferences()
      .then((p: ModelPreferences) => { if (p.chat_backend) setChatBackend(p.chat_backend) })
      .catch(() => {})
    api.getAvailableModels()
      .then((models) => setAvailableBackends(models.filter(m => m.suitable_for.includes("chat"))))
      .catch(() => {})
  }, [])

  // Load sessions list
  const refreshSessions = useCallback(() => {
    api.listSessions().then(setSessions).catch(() => {})
  }, [])

  useEffect(() => { refreshSessions() }, [refreshSessions])

  // Auto-scroll
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" })
  }, [messages])

  // Load a session's messages
  const loadSession = useCallback(async (sid: string) => {
    try {
      const detail = await api.getSession(sid)
      setSessionId(detail.id)
      setAgentType((detail.agent_type || "neutral") as AgentType)
      setMode((detail.mode || "listen") as "listen" | "consult")
      if (detail.backend) setChatBackend(detail.backend)
      const msgs: Message[] = detail.messages.map((m, i) => ({
        id: `${detail.id}-${i}`,
        role: m.role,
        content: m.content,
        timestamp: new Date(m.timestamp),
        agentType: m.role === "assistant" ? (detail.agent_type || "neutral") : undefined,
        backend: m.backend,
        model: m.model,
      }))
      setMessages(msgs)
    } catch {
      // session not found, start fresh
      setSessionId(null)
      setMessages([])
    }
  }, [])

  // New session
  const startNewSession = () => {
    setSessionId(null)
    setMessages([])
  }

  // Delete session
  const deleteSession = async (sid: string) => {
    await api.deleteSession(sid).catch(() => {})
    if (sessionId === sid) startNewSession()
    refreshSessions()
  }

  const handleSend = async () => {
    if (!input.trim() || loading) return
    const userMsg: Message = {
      id: crypto.randomUUID(),
      role: "user",
      content: input.trim(),
      timestamp: new Date(),
    }
    setMessages((prev) => [...prev, userMsg])
    setInput("")
    setLoading(true)

    const replyId = crypto.randomUUID()
    const replyMsg: Message = {
      id: replyId,
      role: "assistant",
      content: "",
      timestamp: new Date(),
      agentType,
    }
    setMessages((prev) => [...prev, replyMsg])

    try {
      for await (const chunk of api.chatStream({
        message: userMsg.content,
        agent_type: agentType,
        mode,
        backend: chatBackend,
        session_id: sessionId || undefined,
      })) {
        // Check for session_id event
        if (chunk.startsWith("__SESSION_ID__")) {
          const newSid = chunk.slice("__SESSION_ID__".length)
          setSessionId(newSid)
          refreshSessions()
          continue
        }
        if (chunk === "__THINKING_DONE__") {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === replyId ? { ...m, thinkingDone: true } : m
            )
          )
          continue
        }
        if (chunk.startsWith("__THINKING__")) {
          const thinkToken = chunk.slice("__THINKING__".length)
          setMessages((prev) =>
            prev.map((m) =>
              m.id === replyId ? { ...m, thinking: (m.thinking || "") + thinkToken } : m
            )
          )
          continue
        }
        setMessages((prev) =>
          prev.map((m) =>
            m.id === replyId ? { ...m, content: m.content + chunk } : m
          )
        )
      }
    } catch (e) {
      let errContent = `[错误: ${e instanceof Error ? e.message : "连接失败"}]`
      if (e instanceof Error && e.message.startsWith("__STRUCTURED__")) {
        try {
          const info = JSON.parse(e.message.slice("__STRUCTURED__".length))
          const alts = (info.available_backends || []) as string[]
          errContent = `⚠️ ${info.error || "模型调用失败"}`
          if (alts.length > 0) {
            errContent += `\n\n可用模型: ${alts.join(", ")}\n请在顶部切换后端重试。`
          }
        } catch { /* fallback to raw message */ }
      } else if (e instanceof Error && e.message.includes("Chat API")) {
        errContent = `⚠️ 服务端错误 (${e.message})，请切换后端重试。`
      }
      setMessages((prev) =>
        prev.map((m) =>
          m.id === replyId
            ? { ...m, content: m.content || errContent }
            : m
        )
      )
    } finally {
      setLoading(false)
    }
  }

  const cfg = agentConfig[agentType]
  const AgentIcon = cfg.icon

  return (
    <div className="flex h-full">
      {/* Session sidebar */}
      <div className={cn(
        "border-r border-border flex flex-col bg-muted/30 transition-all duration-200",
        sidebarOpen ? "w-64" : "w-0 overflow-hidden"
      )}>
        {sidebarOpen && (
          <>
            <div className="p-3 border-b border-border flex items-center justify-between">
              <span className="text-xs font-semibold text-muted-foreground">历史会话</span>
              <Button variant="ghost" size="sm" className="h-7 w-7 p-0" onClick={startNewSession}>
                <Plus className="w-4 h-4" />
              </Button>
            </div>
            <div className="flex-1 overflow-y-auto p-2 space-y-1">
              {sessions.length === 0 && (
                <div className="text-xs text-muted-foreground text-center py-8">暂无历史会话</div>
              )}
              {sessions.map((s) => (
                <div
                  key={s.id}
                  className={cn(
                    "group flex items-center gap-2 px-3 py-2 rounded-lg cursor-pointer text-sm hover:bg-muted transition-colors",
                    sessionId === s.id && "bg-muted font-medium"
                  )}
                  onClick={() => loadSession(s.id)}
                >
                  <MessageSquare className="w-3.5 h-3.5 shrink-0 text-muted-foreground" />
                  <div className="flex-1 min-w-0">
                    <div className="truncate text-xs">{s.title || "新会话"}</div>
                    <div className="text-[10px] text-muted-foreground">
                      {s.message_count} 条 · {new Date(s.updated_at).toLocaleDateString("zh-CN", { month: "short", day: "numeric" })}
                    </div>
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-6 w-6 p-0 opacity-0 group-hover:opacity-100 shrink-0"
                    onClick={(e) => { e.stopPropagation(); deleteSession(s.id) }}
                  >
                    <Trash2 className="w-3 h-3 text-muted-foreground" />
                  </Button>
                </div>
              ))}
            </div>
          </>
        )}
      </div>

      {/* Main chat area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Top bar */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-border">
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" className="h-7 w-7 p-0" onClick={() => setSidebarOpen(!sidebarOpen)}>
              {sidebarOpen ? <ChevronLeft className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
            </Button>
            <AgentIcon className={cn("w-5 h-5", cfg.color)} />
            <span className="font-semibold text-sm">{cfg.label}</span>
            <Badge variant={mode === "listen" ? "secondary" : "default"} className="text-[11px]">
              {mode === "listen" ? "倾听模式" : "深度咨询"}
            </Badge>
            {sessionId && (
              <span className="text-[10px] text-muted-foreground">#{sessionId}</span>
            )}
          </div>
          <div className="flex gap-1 items-center">
            {/* Backend selector */}
            <select
              value={chatBackend}
              onChange={(e) => setChatBackend(e.target.value)}
              className="h-8 text-xs rounded-md border border-input bg-background px-2 mr-1"
            >
              {availableBackends.map((m) => (
                <option key={m.backend} value={m.backend}>
                  {m.backend} ({m.model.split("/").pop()})
                </option>
              ))}
            </select>
            {(Object.keys(agentConfig) as AgentType[]).map((t) => {
              const Icon = agentConfig[t].icon
              return (
                <Button
                  key={t}
                  variant={agentType === t ? "default" : "ghost"}
                  size="sm"
                  className="h-8 px-2"
                  onClick={() => setAgentType(t)}
                >
                  <Icon className="w-4 h-4 mr-1" />
                  <span className="hidden sm:inline text-xs">{agentConfig[t].label}</span>
                </Button>
              )
            })}
            <div className="w-px bg-border mx-1" />
            <Button
              variant={mode === "listen" ? "secondary" : "outline"}
              size="sm"
              className="h-8 text-xs"
              onClick={() => setMode("listen")}
            >
              倾听
            </Button>
            <Button
              variant={mode === "consult" ? "secondary" : "outline"}
              size="sm"
              className="h-8 text-xs"
              onClick={() => setMode("consult")}
            >
              咨询
            </Button>
          </div>
        </div>

        {/* Messages */}
        <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-4">
          {messages.length === 0 && (
            <div className="flex items-center justify-center h-full">
              <div className="text-center text-muted-foreground">
                <AgentIcon className={cn("w-12 h-12 mx-auto mb-3 opacity-20", cfg.color)} />
                <p className="text-sm">开始新的对话</p>
                <p className="text-xs mt-1">选择顾问类型和模式，然后描述你的情况</p>
              </div>
            </div>
          )}
          {messages.map((msg) => (
            <div
              key={msg.id}
              className={cn(
                "flex",
                msg.role === "user" ? "justify-end" : "justify-start"
              )}
            >
              <div
                className={cn(
                  "max-w-[80%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed",
                  msg.role === "user"
                    ? "bg-primary text-primary-foreground rounded-br-md"
                    : msg.role === "system"
                    ? "bg-muted text-muted-foreground text-center max-w-full rounded-xl"
                    : cn(agentConfig[msg.agentType as AgentType]?.bg ?? "bg-muted", "rounded-bl-md")
                )}
              >
                {msg.role === "assistant" && msg.agentType && (
                  <div className="flex items-center gap-1.5 mb-1">
                    <span className={cn("text-[11px] font-medium", agentConfig[msg.agentType as AgentType]?.color)}>
                      {agentConfig[msg.agentType as AgentType]?.label}
                    </span>
                    {msg.backend && (
                      <span className="text-[9px] text-muted-foreground bg-muted/50 px-1 rounded">
                        {msg.backend}
                      </span>
                    )}
                  </div>
                )}
                {msg.thinking && (
                  <ThinkingBlock thinking={msg.thinking} done={!!msg.thinkingDone} />
                )}
                <div className="whitespace-pre-wrap">{stripThink(msg.content)}</div>
                <div className="text-[10px] opacity-50 mt-1 text-right">
                  {msg.timestamp.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}
                </div>
              </div>
            </div>
          ))}
          {loading && (
            <div className="flex justify-start">
              <div className={cn("rounded-2xl rounded-bl-md px-4 py-3", cfg.bg)}>
                <Loader2 className={cn("w-4 h-4 animate-spin", cfg.color)} />
              </div>
            </div>
          )}
        </div>

        {/* Input */}
        <div className="border-t border-border p-3">
          <div className="flex gap-2">
            <Textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="描述你的情况或提问..."
              className="min-h-[44px] max-h-[120px] resize-none text-sm"
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault()
                  handleSend()
                }
              }}
            />
            <Button onClick={handleSend} disabled={loading || !input.trim()} size="icon" className="shrink-0">
              {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
