import { useState, useRef, useEffect, useCallback, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { motion, AnimatePresence } from 'framer-motion'
import { defaultArenaScores, type ArenaVote, type ArenaScores } from '../stores/useArenaStore'
import { api, type AvailableModel } from '../lib/api'
import { toast } from 'sonner'
import { PERSONAS } from '../constants'
import type { Persona, ChatMode } from '../types'
import { MarkdownContent } from '../components/chat/MarkdownContent'
import { TypingIndicator } from '../components/chat/TypingIndicator'
import {
  Info, SplitSquareHorizontal, Send, Eye, EyeOff, Loader2,
  MoreHorizontal, Sparkles, Plus, Clock, Check, Download, BarChart3,
} from 'lucide-react'
import { ExportDialog, arenaToExportData } from '../components/shared/ExportDialog'
import { ArenaStatsPage } from './ArenaStatsPage'
import { SessionOptions } from '../components/shared/SessionOptions'
import { format } from 'date-fns'

const FALLBACK_CHAT_MODELS: AvailableModel[] = [
  { backend: 'deepseek', model: 'deepseek-ai/DeepSeek-V3.1', base_url: 'https://api.example.com/v1', suitable_for: ['chat'] },
]
const mkKey = (m: AvailableModel) => `${m.backend}::${m.model}`

// 2026-04-18：合并原「流派对比(agent_type)」与「视角碰撞(perspective)」为统一的「视角碰撞」
// 'agent_type' 字面量保留在类型中仅为兼容历史会话 JSON
type CompareMode = 'model' | 'perspective' | 'agent_type'
const COMPARE_MODES: { value: Exclude<CompareMode, 'agent_type'>; labelKey: string }[] = [
  { value: 'model', labelKey: 'arena.modeModel' },
  { value: 'perspective', labelKey: 'arena.modePerspective' },
]

const DIMENSIONS = [
  { key: 'empathy', labelKey: 'arena.dimensions.empathy' },
  { key: 'depth', labelKey: 'arena.dimensions.depth' },
  { key: 'practicality', labelKey: 'arena.dimensions.practicality' },
  { key: 'professionalism', labelKey: 'arena.dimensions.professionalism' },
  { key: 'fluency', labelKey: 'arena.dimensions.fluency' },
] as const

const VOTE_OPTIONS: { value: ArenaVote; labelKey: string }[] = [
  { value: 'a_win', labelKey: 'arena.voteOptions.aWin' },
  { value: 'b_win', labelKey: 'arena.voteOptions.bWin' },
  { value: 'tie', labelKey: 'arena.voteOptions.tie' },
  { value: 'both_good', labelKey: 'arena.voteOptions.bothGood' },
  { value: 'both_bad', labelKey: 'arena.voteOptions.bothBad' },
]

interface Round {
  query: string
  responseA: string
  responseB: string
  vote: ArenaVote | null
  scoresA: ArenaScores
  scoresB: ArenaScores
  remark: string | null
  crisisLevel: string | null
  submitted: boolean
  revealed: { a: Record<string, string>; b: Record<string, string> } | null
  timestamp: Date
}

interface ArenaSessionSummary { id: string; title: string; rounds: number; time: string }

type SoloSide = null | 'a' | 'b'

export function ArenaPage() {
  const { t } = useTranslation()
  const [compareMode, setCompareMode] = useState<CompareMode>('model')
  const [personaA, setPersonaA] = useState<Persona>(PERSONAS[0])
  const [personaB, setPersonaB] = useState<Persona>(PERSONAS.length > 1 ? PERSONAS[1] : PERSONAS[0])
  const [persona, setPersona] = useState<Persona>(PERSONAS[0])
  const [mode, setMode] = useState<ChatMode>('listen')
  const [useRag, setUseRag] = useState(true)
  const [useKnowledge, setUseKnowledge] = useState(true)
  const [chatModels, setChatModels] = useState<AvailableModel[]>(FALLBACK_CHAT_MODELS)
  const [modelKeyA, setModelKeyA] = useState(mkKey(FALLBACK_CHAT_MODELS[0]))
  const [modelKeyB, setModelKeyB] = useState('')

  const [arenaSessionId, setArenaSessionId] = useState<string | null>(null)
  const [rounds, setRounds] = useState<Round[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [pendingVoteIdx, setPendingVoteIdx] = useState(-1)
  const [selectedVote, setSelectedVote] = useState<ArenaVote | null>(null)
  const [voteRemark, setVoteRemark] = useState('')
  const [revealToggle, setRevealToggle] = useState(false)
  const [contestants, setContestants] = useState<{ a: Record<string, string>; b: Record<string, string> } | null>(null)
  const [menuOpen, setMenuOpen] = useState(false)
  const [soloSide, setSoloSide] = useState<SoloSide>(null)
  const [arenaSessions, setArenaSessions] = useState<ArenaSessionSummary[]>([])
  const [showExport, setShowExport] = useState(false)
  const [showStats, setShowStats] = useState(false)
  const [mobileTab, setMobileTab] = useState<'a' | 'b'>('a')

  const scrollRefA = useRef<HTMLDivElement>(null)
  const scrollRefB = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)

  const modelA = useMemo(() => chatModels.find(m => mkKey(m) === modelKeyA) || chatModels[0], [chatModels, modelKeyA])
  const modelB = useMemo(() => chatModels.find(m => mkKey(m) === modelKeyB) || chatModels[chatModels.length > 1 ? 1 : 0], [chatModels, modelKeyB])

  useEffect(() => {
    api.getAvailableModels().then((avail) => {
      const chat = avail.filter(m => m.suitable_for.includes('chat'))
      const all = Array.from(new Map([...chat, ...FALLBACK_CHAT_MODELS].map(m => [mkKey(m), m])).values())
      setChatModels(all)
      const ds = all.find(m => m.backend === 'deepseek')
      const gk = all.find(m => m.backend === 'grok')
      if (ds) setModelKeyA(mkKey(ds))
      if (gk) setModelKeyB(mkKey(gk))
      else if (all.length > 1) setModelKeyB(mkKey(all[1]))
    }).catch(() => {})
  }, [])

  const fetchArenaSessions = useCallback(() => {
    fetch('/api/arena/sessions').then(r => r.ok ? r.json() : []).then((list: ArenaSessionSummary[]) => {
      setArenaSessions(list)
    }).catch(() => {})
  }, [])
  useEffect(() => { fetchArenaSessions() }, [fetchArenaSessions])

  useEffect(() => {
    const prefill = sessionStorage.getItem('arena-prefill')
    const prefillPersona = sessionStorage.getItem('arena-prefill-persona')
    if (prefill) {
      sessionStorage.removeItem('arena-prefill')
      if (prefillPersona) {
        sessionStorage.removeItem('arena-prefill-persona')
        setCompareMode('perspective')
        const pA = PERSONAS.find(p => p.id === prefillPersona)
        if (pA) {
          setPersonaA(pA)
          // Find a different persona for B
          const optionsB = PERSONAS.filter(p => p.id !== pA.id && p.id !== 'neutral')
          setPersonaB(optionsB.length > 0 ? optionsB[Math.floor(Math.random() * optionsB.length)] : PERSONAS[0])
        }
      }
      setInput(prefill)
      toast.info('正在为您建立双镜对比，生成需要较长时间，请耐心等待...')
      setTimeout(() => {
        document.getElementById('arena-send-btn')?.click()
      }, 500)
    }
  }, [])

  const scrollToBottom = useCallback(() => {
    setTimeout(() => {
      scrollRefA.current?.scrollTo({ top: scrollRefA.current.scrollHeight, behavior: 'smooth' })
      scrollRefB.current?.scrollTo({ top: scrollRefB.current.scrollHeight, behavior: 'smooth' })
    }, 60)
  }, [])
  useEffect(() => { scrollToBottom() }, [rounds.length, scrollToBottom])

  useEffect(() => {
    const h = (e: MouseEvent) => { if (!menuRef.current?.contains(e.target as Node)) setMenuOpen(false) }
    document.addEventListener('mousedown', h); return () => document.removeEventListener('mousedown', h)
  }, [])

  useEffect(() => {
    if (inputRef.current) { inputRef.current.style.height = 'auto'; inputRef.current.style.height = Math.min(inputRef.current.scrollHeight, 200) + 'px' }
  }, [input])

  useEffect(() => {
    if (inputRef.current) { inputRef.current.style.height = 'auto'; inputRef.current.style.height = Math.min(inputRef.current.scrollHeight, 200) + 'px' }
  }, [input])

  const handleSend = async () => {
    const msg = input.trim()
    if (!msg || loading) return
    if (pendingVoteIdx >= 0 && !rounds[pendingVoteIdx]?.submitted) {
      toast.warning('请先完成当前轮的打分，或点击「跳过」'); return
    }
    setInput(''); setLoading(true); setPendingVoteIdx(-1); setSelectedVote(null); setVoteRemark('')
    try {
      const isPickMode = compareMode === 'agent_type' || compareMode === 'perspective'
      const contestantA = isPickMode
        ? { backend: modelA.backend, agent_type: personaA.id, model: modelA.model }
        : { backend: modelA.backend, agent_type: persona.id, model: modelA.model }
      const contestantB = isPickMode
        ? { backend: modelA.backend, agent_type: personaB.id, model: modelA.model }
        : { backend: modelB.backend, agent_type: persona.id, model: modelB.model }
      const res = await api.arenaChat({
        message: msg,
        arena_session_id: arenaSessionId ?? undefined,
        contestant_a: contestantA,
        contestant_b: contestantB,
        mode: compareMode, use_rag: useRag, use_knowledge: useKnowledge,
      })
      if (!arenaSessionId) { setArenaSessionId(res.arena_session_id); fetchArenaSessions() }
      setRounds(prev => [...prev, {
        query: msg, responseA: res.response_a, responseB: res.response_b,
        vote: null, scoresA: defaultArenaScores(), scoresB: defaultArenaScores(),
        remark: null, crisisLevel: res.crisis_level || null,
        submitted: res.requires_vote === false, revealed: null, timestamp: new Date(),
      }])
      if (res.requires_vote === false) {
        setPendingVoteIdx(-1)
        toast.info('已触发安全干预，本轮不参与评分')
      } else {
        setPendingVoteIdx(res.round_index)
      }
      scrollToBottom()
    } catch (e) {
      const errMessage = e instanceof Error ? e.message : String(e)
      toast.error(`系统异常: ${errMessage === 'Load failed' || errMessage === 'Failed to fetch' ? '网络连接异常，请检查后端服务' : errMessage}`)
      setRounds(prev => [...prev, {
        query: msg, responseA: `**[System Error]** ${errMessage}`, responseB: '',
        vote: null, scoresA: defaultArenaScores(), scoresB: defaultArenaScores(),
        remark: null, crisisLevel: null, submitted: true, revealed: null, timestamp: new Date(),
      }])
    } finally { setLoading(false); inputRef.current?.focus() }
  }

  const handleSubmitVote = async () => {
    if (!arenaSessionId || pendingVoteIdx < 0) return
    const rd = rounds[pendingVoteIdx]; if (!rd) return
    const vote = selectedVote ?? 'tie'
    try {
      const res = await api.arenaVote({
        arena_session_id: arenaSessionId, round_index: pendingVoteIdx, vote,
        scores_a: rd.scoresA as unknown as Record<string, number>,
        scores_b: rd.scoresB as unknown as Record<string, number>,
        remark: voteRemark.trim() || undefined,
      })
      const r = { a: res.contestant_a, b: res.contestant_b }
      setContestants(r)
      setRounds(prev => {
        const n = [...prev]
        n[pendingVoteIdx] = { ...n[pendingVoteIdx], vote, remark: voteRemark.trim() || null, submitted: true, revealed: r }
        return n
      })
      setPendingVoteIdx(-1); setSelectedVote(null); setVoteRemark('')
      toast.success(`已记录第 ${pendingVoteIdx + 1} 轮评分 ✓`)
    } catch { toast.error('提交失败，请重试') }
    fetchArenaSessions()
  }

  const handleSkipVote = () => {
    setRounds(prev => { const n = [...prev]; if (n[pendingVoteIdx]) n[pendingVoteIdx] = { ...n[pendingVoteIdx], submitted: true }; return n })
    setPendingVoteIdx(-1); setSelectedVote(null); setVoteRemark('')
  }

  const handleScoreChange = (side: 'a' | 'b', dim: keyof ArenaScores, val: number) => {
    setRounds(prev => {
      const n = [...prev]; const rd = n[pendingVoteIdx]; if (!rd) return prev
      const f = side === 'a' ? 'scoresA' : 'scoresB'
      n[pendingVoteIdx] = { ...rd, [f]: { ...rd[f], [dim]: Math.min(10, Math.max(1, val)) } }; return n
    })
  }

  const handleToggleReveal = async () => {
    if (revealToggle) { setRevealToggle(false); return }
    if (!arenaSessionId) return
    try {
      const s = await api.arenaSession(arenaSessionId) as { contestant_a: Record<string, string>; contestant_b: Record<string, string> }
      setContestants({ a: s.contestant_a, b: s.contestant_b }); setRevealToggle(true)
    } catch {}
  }

  const handleNewSession = () => {
    setArenaSessionId(null); setRounds([]); setPendingVoteIdx(-1); setSelectedVote(null)
    setRevealToggle(false); setContestants(null); setSoloSide(null); setVoteRemark('')
  }

  // 2026-04-18 合并：视角碰撞模式统一涵盖全部 9 个 PERSONAS（5 种流派 + 4 种跨学科视角）
  const isPerspectiveMode = compareMode === 'perspective' || compareMode === 'agent_type'
  const isPickerMode = isPerspectiveMode
  const pickerPersonas = PERSONAS
  const pickerLabel = '视角'

  const handleLoadSession = async (sid: string) => {
    try {
      const s = await api.arenaSession(sid) as {
        id: string; contestant_a: Record<string, string>; contestant_b: Record<string, string>
        rounds: Array<{ query: string; response_a: string; response_b: string; vote: string | null; scores: Record<string, Record<string, number>> | null; remark?: string; crisis_level?: string; timestamp: string }>
      }
      setArenaSessionId(s.id); setContestants({ a: s.contestant_a, b: s.contestant_b })
      setRounds(s.rounds.map(r => ({
        query: r.query, responseA: r.response_a, responseB: r.response_b,
        vote: (r.vote as ArenaVote) || null,
        scoresA: r.scores?.a ? r.scores.a as unknown as ArenaScores : defaultArenaScores(),
        scoresB: r.scores?.b ? r.scores.b as unknown as ArenaScores : defaultArenaScores(),
        remark: r.remark || null,
        crisisLevel: r.crisis_level || null,
        submitted: !!r.vote, revealed: r.vote ? { a: s.contestant_a, b: s.contestant_b } : null,
        timestamp: new Date(r.timestamp),
      })))
      setPendingVoteIdx(-1); setSelectedVote(null); setVoteRemark(''); setRevealToggle(false); setSoloSide(null)
    } catch { toast.error('加载失败') }
  }

  const handleSoloSelect = (side: 'a' | 'b') => {
    setSoloSide(side); setRevealToggle(true)
    if (!contestants && arenaSessionId) {
      api.arenaSession(arenaSessionId).then((s: any) => {
        setContestants({ a: s.contestant_a, b: s.contestant_b })
      }).catch(() => {})
    }
  }

  const lbl = (c: Record<string, string> | null | undefined, fb: string) => c ? (c.model || c.backend || fb) : fb
  const PIcon = persona.icon
  const curA = rounds[pendingVoteIdx]?.scoresA ?? defaultArenaScores()
  const curB = rounds[pendingVoteIdx]?.scoresB ?? defaultArenaScores()
  const hasPendingUnsubmitted = pendingVoteIdx >= 0 && !rounds[pendingVoteIdx]?.submitted
  const showA = soloSide === null || soloSide === 'a'
  const showB = soloSide === null || soloSide === 'b'

  const renderChatHeader = (side: 'a' | 'b') => {
    const isRevealed = revealToggle || rounds.some(r => r.revealed)
    const currentModel = side === 'a' ? modelA : modelB
    const sidePersona = side === 'a' ? personaA : personaB
    return (
      <div className="px-4 py-2 border-b border-[var(--border-color)] bg-[var(--bg-secondary)]/60 text-xs font-medium text-[var(--text-secondary)] flex items-center justify-between gap-2">
        <span className="shrink-0">{isPickerMode ? `${pickerLabel} ${side.toUpperCase()}` : side.toUpperCase()}</span>
        <div className="flex-1 flex items-center justify-center">
          {isPickerMode ? (
            isRevealed ? (
              <span className="text-[11px] text-emerald-500">{sidePersona.name}</span>
            ) : (
              <span className="text-[var(--text-muted)]">{isPerspectiveMode ? t('arena.anonymousPerspective') : t('arena.anonymousSchool')}</span>
            )
          ) : isRevealed && contestants ? (
            <select
              value={mkKey(currentModel)}
              onChange={(e) => {
                const found = chatModels.find(m => mkKey(m) === e.target.value)
                if (!found) return
                if (side === 'a') setModelKeyA(mkKey(found))
                else setModelKeyB(mkKey(found))
                toast.info(`${side.toUpperCase()} 模型已切换为 ${found.backend}，下一轮生效`)
              }}
              className="h-6 max-w-[200px] rounded-md border border-transparent bg-transparent px-1 text-[11px] text-emerald-500 outline-none hover:bg-[var(--bg-card)] focus:border-emerald-500/30 cursor-pointer text-center truncate"
            >
              {chatModels.map(m => (
                <option key={mkKey(m)} value={mkKey(m)}>{m.backend} · {m.model.split('/').pop()}</option>
              ))}
            </select>
          ) : (
            <span className="text-[var(--text-muted)]">{t('arena.anonymousModel')}</span>
          )}
        </div>
        <div className="flex items-center gap-1 shrink-0">
          {rounds.length >= 1 && soloSide === null && (
            <button onClick={() => handleSoloSelect(side)}
              className="text-[10px] px-1.5 py-0.5 rounded border border-[var(--border-color)] hover:bg-[var(--bg-card)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
              title={`Keep ${side.toUpperCase()} only`}>
              {t('arena.select')}
            </button>
          )}
        </div>
      </div>
    )
  }

  const renderMessages = (side: 'a' | 'b') => (
    <>
      {rounds.map((rd, i) => (
        <div key={i} className="space-y-4 mb-6">
          <div className="flex justify-end">
            <div className="max-w-[85%] md:max-w-[72%]">
              <div className="px-5 py-3 text-[15px] leading-relaxed bg-emerald-600 text-white rounded-2xl rounded-tr-sm shadow-sm shadow-emerald-600/20 break-words">{rd.query}</div>
              <span className="text-[10px] text-[var(--text-muted)] mt-1 block text-right pr-1">{format(rd.timestamp, 'HH:mm')}</span>
            </div>
          </div>
          <div className="flex justify-start gap-3">
            <div className="flex-shrink-0 mt-1">
              <div className="w-9 h-9 rounded-xl flex items-center justify-center border shadow-sm" style={{ backgroundColor: `${persona.hex}15`, borderColor: `${persona.hex}30` }}>
                <PIcon className="w-4 h-4" style={{ color: persona.hex }} />
              </div>
            </div>
            <div className="max-w-[90%] min-w-0">
              <span className="text-xs font-semibold px-1 mb-1 block" style={{ color: persona.hex }}>
                {soloSide ? persona.name : t('arena.reply', { side: side.toUpperCase() })}
              </span>
              <div className="px-5 py-4 text-[15px] leading-relaxed bg-[var(--bg-card)] border border-[var(--border-color)] text-[var(--text-primary)] rounded-2xl rounded-tl-sm shadow-sm break-words">
                <MarkdownContent content={side === 'a' ? rd.responseA : rd.responseB} isUser={false} />
              </div>
              {rd.crisisLevel === 'RED' && (
                <span className="text-[10px] text-red-500 mt-1 block pl-1">{t('arena.crisisTriggered')}</span>
              )}
              {rd.remark && side === 'a' && (
                <span className="text-[10px] text-[var(--text-muted)] mt-1 block pl-1">{t('arena.voteRemark', { remark: rd.remark })}</span>
              )}
              {(revealToggle || rd.revealed) && contestants && (
                <span className="text-[10px] text-emerald-500/70 mt-1 block pl-1">{side.toUpperCase()} = {lbl(side === 'a' ? contestants.a : contestants.b, '?')}</span>
              )}
            </div>
          </div>
        </div>
      ))}
      {loading && (
        <div className="flex justify-start gap-3 mt-4 animate-in fade-in slide-in-from-bottom-2 duration-500">
          <div className="flex-shrink-0 mt-1">
            <div className="w-9 h-9 rounded-xl flex items-center justify-center border shadow-sm" style={{ backgroundColor: `${persona.hex}10`, borderColor: `${persona.hex}20` }}>
              <Loader2 className="w-4 h-4 animate-spin" style={{ color: persona.hex }} />
            </div>
          </div>
          <div className="max-w-[85%] min-w-[80px]">
            <span className="text-[10px] font-semibold px-1 mb-1 block" style={{ color: persona.hex }}>
              {soloSide ? persona.name : t('arena.waitingFor', { side: side.toUpperCase() })}
            </span>
            <div className="px-5 py-3 h-[52px] flex items-center bg-[var(--bg-card)] border border-[var(--border-color)] rounded-2xl rounded-tl-sm shadow-sm">
              <TypingIndicator
                text={side === 'a' ? t('arena.viewpointConstructing') : t('arena.depthComparing')}
                color={persona.hex}
                compact
              />
            </div>
          </div>
        </div>
      )}
    </>
  )

  if (showStats) {
    return (
      <div className="flex-1 flex h-full overflow-hidden bg-[var(--bg-primary)] transition-all duration-300">
        <div className="w-56 border-r border-[var(--border-color)] bg-[var(--bg-card)] flex flex-col h-full z-10 shrink-0 hidden md:flex">
          <div className="p-4 border-b border-[var(--border-color)]">
            <button onClick={() => setShowStats(false)}
              className="w-full flex items-center justify-center gap-2 border border-[var(--border-color)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] rounded-xl transition-all py-2.5 px-4 hover:bg-[var(--bg-secondary)]">
              <SplitSquareHorizontal className="w-4 h-4" />
              <span className="text-sm font-medium">{t('arena.returnToCompare')}</span>
            </button>
          </div>
        </div>
        <div className="flex-1 flex flex-col min-w-0 bg-[var(--bg-card)] relative overflow-hidden">
          <ArenaStatsPage onBack={() => setShowStats(false)} />
        </div>
      </div>
    )
  }

  return (
    <div className="flex-1 flex h-full overflow-hidden bg-[var(--bg-primary)] transition-all duration-300">
      {/* Sidebar */}
      <div className="w-56 border-r border-[var(--border-color)] bg-[var(--bg-card)] flex flex-col h-full z-10 shrink-0 hidden md:flex">
        <div className="p-4 border-b border-[var(--border-color)] space-y-2">
          <button onClick={handleNewSession}
            className="w-full flex items-center justify-center gap-2 bg-gradient-to-r from-emerald-500/10 to-teal-500/10 hover:from-emerald-500/20 hover:to-teal-500/20 border border-emerald-500/20 text-emerald-600 rounded-xl transition-all py-2.5 px-4 shadow-sm group">
            <Plus className="w-4 h-4 group-hover:scale-110 transition-transform" />
            <span className="font-semibold text-sm">New Comparison</span>
          </button>
          <button onClick={() => setShowStats(true)}
            className="w-full flex items-center justify-center gap-2 border border-[var(--border-color)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] rounded-xl transition-all py-2 px-4 hover:bg-[var(--bg-secondary)]">
            <BarChart3 className="w-4 h-4" />
            <span className="text-xs font-medium">Elo Ranking</span>
          </button>
        </div>
        <div className="flex-1 overflow-y-auto scrollbar-thin p-4 space-y-1">
          <div className="px-2 mb-3 text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-wider">Comparison History</div>
          {arenaSessions.length === 0 && <p className="text-xs text-[var(--text-muted)] px-2">No history yet</p>}
          {arenaSessions.map(s => (
            <div key={s.id} onClick={() => handleLoadSession(s.id)}
              className={`group relative rounded-xl transition-all duration-300 cursor-pointer border p-3 flex items-start gap-3 ${arenaSessionId === s.id ? 'bg-emerald-500/5 border-emerald-500/20 shadow-sm' : 'bg-transparent border-transparent hover:bg-[var(--bg-secondary)]'}`}>
              <div className="mt-1.5 w-2 h-2 rounded-full shrink-0 bg-emerald-500" />
              <div className="flex-1 min-w-0">
                <div className="flex items-start justify-between">
                  <h3 className="text-sm font-medium truncate mb-1 pr-2 text-[var(--text-secondary)] group-hover:text-[var(--text-primary)]">{s.title || t('topNav.unnamed')}</h3>
                  <SessionOptions 
                    sessionId={s.id}
                    initialTitle={s.title || t('topNav.unnamed')}
                    onRename={async (id, title) => { await api.renameArenaSession(id, title); fetchArenaSessions(); }}
                    onDelete={async (id) => { await api.deleteArenaSession(id); fetchArenaSessions(); if (arenaSessionId === id) handleNewSession(); }}
                    className="-mt-1 -mr-1"
                  />
                </div>
                <div className="flex items-center justify-between text-xs">
                  <span className="text-[10px] text-[var(--text-muted)]">{s.rounds} rounds</span>
                  <div className="flex items-center gap-1 text-[var(--text-muted)]"><Clock className="w-3 h-3" /><span>{s.time}</span></div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Main */}
      <div className="flex-1 flex flex-col min-w-0 bg-[var(--bg-card)] relative overflow-hidden">
        <div className="absolute inset-0 pointer-events-none" style={{
          background: `radial-gradient(circle at 10% 0%, ${persona.hex}26, transparent 40%), radial-gradient(circle at 90% 20%, #14b8a620, transparent 38%)`,
        }} />

        {/* TopBar */}
        <div className="h-14 glass-nav flex items-center justify-between px-6 border-b border-[var(--border-color)] z-[60] sticky top-0 shrink-0 bg-gradient-to-r from-white/55 via-emerald-50/30 to-cyan-50/45 dark:from-stone-950/80 dark:via-emerald-950/20 dark:to-teal-950/20">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl flex items-center justify-center border shadow-sm" style={{ backgroundColor: `${persona.hex}15`, borderColor: `${persona.hex}40` }}>
              <SplitSquareHorizontal className="w-4 h-4" style={{ color: persona.hex }} />
            </div>
            <div>
              <h2 className="font-bold text-sm text-[var(--text-primary)] leading-tight flex items-center gap-2">
                {soloSide ? '双镜对比（单路模式）' : '双镜对比'}
                <span className="flex h-2 w-2 relative"><span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" /><span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" /></span>
              </h2>
              <p className="text-[10px] uppercase tracking-wider font-semibold" style={{ color: persona.hex }}>
                {isPickerMode ? `${personaA.name} vs ${personaB.name}` : persona.name}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            {/* Compare Mode */}
            <div className="hidden md:flex p-0.5 bg-[var(--bg-secondary)] rounded-lg border border-[var(--border-color)]">
              {COMPARE_MODES.map(cm => (
                <button key={cm.value} onClick={() => {
                  if (arenaSessionId) return
                  setCompareMode(cm.value)
                  // 2026-04-18：进入视角碰撞模式时默认选择两个不同 persona（A=中立顾问，B=支持性顾问）
                  if (cm.value === 'perspective') {
                    setPersonaA(PERSONAS[0])
                    const optB = PERSONAS.find(p => p.id !== PERSONAS[0].id && p.id !== 'neutral')
                    if (optB) setPersonaB(optB)
                    else if (PERSONAS.length > 1) setPersonaB(PERSONAS[1])
                  }
                }}
                  disabled={!!arenaSessionId}
                  className={`px-2.5 py-1 text-[10px] font-semibold rounded-md transition-colors ${compareMode === cm.value ? 'bg-emerald-500/20 text-emerald-600 dark:text-emerald-400' : 'text-[var(--text-muted)]'} ${arenaSessionId ? 'opacity-50 cursor-not-allowed' : ''}`}>
                  {t(cm.labelKey)}
                </button>
              ))}
            </div>
            {/* School/Perspective Picker */}
            {isPickerMode && !arenaSessionId && (
              <div className="hidden md:flex items-center gap-1.5 rounded-xl border border-[var(--border-color)] bg-[var(--bg-secondary)] px-2 py-1">
                <select value={personaA.id} onChange={e => { const p = pickerPersonas.find(x => x.id === e.target.value); if (p) setPersonaA(p) }}
                  className="h-5 rounded bg-transparent text-[10px] text-[var(--text-secondary)] outline-none cursor-pointer">
                  {pickerPersonas.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
                </select>
                <span className="text-[10px] text-[var(--text-muted)]">vs</span>
                <select value={personaB.id} onChange={e => { const p = pickerPersonas.find(x => x.id === e.target.value); if (p) setPersonaB(p) }}
                  className="h-5 rounded bg-transparent text-[10px] text-[var(--text-secondary)] outline-none cursor-pointer">
                  {pickerPersonas.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
                </select>
              </div>
            )}
            {/* Reveal Toggle */}
            {arenaSessionId && (
              <button onClick={handleToggleReveal}
                className={`p-2 rounded-xl transition-colors ${revealToggle ? 'text-emerald-500 bg-emerald-500/10' : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-secondary)]'}`}
                title={revealToggle ? '隐藏模型身份' : '揭示模型身份'}>
                {revealToggle ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            )}
            {/* Solo restore */}
            {soloSide && (
              <button onClick={() => setSoloSide(null)}
                className="flex items-center gap-1 px-2 py-1 rounded-lg border border-[var(--border-color)] text-xs text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-secondary)] transition-colors">
                <SplitSquareHorizontal className="w-3 h-3" /> 恢复双镜
              </button>
            )}
            {/* Settings/Menu */}
            <div ref={menuRef} className="relative">
              <button onClick={() => setMenuOpen(v => !v)} className="p-2 text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-secondary)] rounded-xl transition-colors shrink-0">
                <MoreHorizontal size={18} />
              </button>
              {menuOpen && (<>
                <div className="fixed inset-0 z-[199]" onClick={() => setMenuOpen(false)} />
                <div className="absolute right-0 mt-2 z-[200] min-w-[240px] rounded-xl border border-[var(--border-color)] bg-[var(--bg-card)] p-1 shadow-lg">
                  <button onClick={() => { handleNewSession(); setMenuOpen(false) }}
                    className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-xs text-[var(--text-secondary)] transition-colors hover:bg-[var(--bg-secondary)] hover:text-[var(--text-primary)]">
                    <Plus className="h-3.5 w-3.5" /> 新建对比会话
                  </button>
                  {rounds.length > 0 && (
                    <button onClick={() => { setShowExport(true); setMenuOpen(false) }}
                      className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-xs text-[var(--text-secondary)] transition-colors hover:bg-[var(--bg-secondary)] hover:text-[var(--text-primary)]">
                      <Download className="h-3.5 w-3.5" /> 导出对话
                    </button>
                  )}
                  
                  {!isPickerMode && (
                    <>
                      <div className="my-1.5 h-px bg-[var(--border-color)] mx-2" />
                      <p className="px-3 py-1 text-[10px] uppercase tracking-wider text-[var(--text-muted)] font-semibold">切换主控顾问</p>
                      <div className="max-h-48 overflow-y-auto scrollbar-thin">
                        {PERSONAS.map(p => {
                          const PIco = p.icon
                          return (
                            <button key={p.id} onClick={(e) => { e.stopPropagation(); setPersona(p); setMenuOpen(false) }}
                              className="flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-xs text-[var(--text-secondary)] transition-colors hover:bg-[var(--bg-secondary)] hover:text-[var(--text-primary)]">
                              <span className="flex items-center gap-2"><PIco className="h-3.5 w-3.5" style={{ color: p.hex }} />{p.name}</span>
                              {p.id === persona.id && <Sparkles className="h-3.5 w-3.5 text-emerald-500" />}
                            </button>
                          )
                        })}
                      </div>
                    </>
                  )}
                </div>
              </>)}
            </div>
          </div>
        </div>

        {/* Advanced Settings Bar — 2026-04-18 从菜单搬出，直接展示在 TopBar 下方 */}
        <div className="px-6 pt-2 shrink-0 relative z-10">
          <div className="flex flex-wrap items-center gap-2 md:gap-3 rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)]/60 backdrop-blur-sm px-3 py-1.5">
            {/* 对话深度 */}
            <div className="flex items-center gap-1.5">
              <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider">深度</span>
              <div className="flex p-0.5 bg-[var(--bg-secondary)] rounded-md border border-[var(--border-color)]">
                <button onClick={() => setMode('listen')}
                  className={`relative px-2 py-0.5 text-[10px] font-semibold rounded transition-colors z-10 ${mode === 'listen' ? 'text-white' : 'text-[var(--text-secondary)]'}`}>
                  {mode === 'listen' && <motion.div layoutId="arena-mode-topbar" className="absolute inset-0 bg-gradient-to-r from-emerald-500 to-teal-500 rounded -z-10 shadow-sm" transition={{ type: 'spring', stiffness: 300, damping: 30 }} />}
                  倾听
                </button>
                <button onClick={() => setMode('deep')}
                  className={`relative px-2 py-0.5 text-[10px] font-semibold rounded transition-colors z-10 ${mode === 'deep' ? 'text-white' : 'text-[var(--text-secondary)]'}`}>
                  {mode === 'deep' && <motion.div layoutId="arena-mode-topbar" className="absolute inset-0 bg-gradient-to-r from-violet-500 to-purple-500 rounded -z-10 shadow-sm" transition={{ type: 'spring', stiffness: 300, damping: 30 }} />}
                  咨询
                </button>
              </div>
            </div>
            {/* RAG Toggle */}
            <div className="flex items-center gap-1.5">
              <span className="text-[10px] text-[var(--text-muted)]">聊天记录 RAG</span>
              <button type="button" role="switch" aria-checked={useRag} onClick={() => setUseRag(!useRag)}
                className={`inline-flex h-4 w-7 items-center rounded-full border p-0.5 transition-all ${useRag ? 'border-emerald-500/40 bg-emerald-500/70' : 'border-[var(--border-color)] bg-[var(--bg-secondary)]'}`}>
                <span className={`h-3 w-3 rounded-full bg-white shadow transition-transform ${useRag ? 'translate-x-3' : 'translate-x-0'}`} />
              </button>
            </div>
            {/* Knowledge Toggle */}
            <div className="flex items-center gap-1.5">
              <span className="text-[10px] text-[var(--text-muted)]">专业知识库</span>
              <button type="button" role="switch" aria-checked={useKnowledge} onClick={() => setUseKnowledge(!useKnowledge)}
                className={`inline-flex h-4 w-7 items-center rounded-full border p-0.5 transition-all ${useKnowledge ? 'border-violet-500/40 bg-violet-500/70' : 'border-[var(--border-color)] bg-[var(--bg-secondary)]'}`}>
                <span className={`h-3 w-3 rounded-full bg-white shadow transition-transform ${useKnowledge ? 'translate-x-3' : 'translate-x-0'}`} />
              </button>
            </div>
            <div className="h-3 w-px bg-[var(--border-color)] hidden sm:block" />
            {/* Disclaimer inline */}
            <div className="flex items-center gap-1.5 text-[10px] text-[var(--text-muted)]">
              <Info className="w-3 h-3 shrink-0 text-amber-500" />
              <span>仅供探索参考，不构成诊断或治疗</span>
            </div>
          </div>
        </div>

        {/* Mobile Tab Switcher */}
        {!soloSide && (
          <div className="flex md:hidden px-6 pt-2 gap-2 shrink-0 relative z-10">
            {(['a', 'b'] as const).map(t => (
              <button key={t} onClick={() => setMobileTab(t)}
                className={`flex-1 py-1.5 rounded-lg text-xs font-semibold transition-colors ${mobileTab === t ? 'bg-emerald-500/20 text-emerald-600 border border-emerald-500/30' : 'border border-[var(--border-color)] text-[var(--text-secondary)]'}`}>
                回复 {t.toUpperCase()}
              </button>
            ))}
          </div>
        )}

        {/* Dual Chat (or Solo) */}
        <div className={`flex-1 flex gap-2 px-6 py-2 min-h-0 overflow-hidden relative z-10 ${soloSide ? 'justify-center' : ''}`}>
          {showA && (
            <div className={`flex-col rounded-2xl border border-[var(--border-color)] bg-[var(--bg-card)]/60 overflow-hidden backdrop-blur-sm ${soloSide ? 'flex w-full max-w-4xl' : !soloSide && mobileTab !== 'a' ? 'hidden md:flex flex-1' : 'flex flex-1'}`}>
              {renderChatHeader('a')}
              <div ref={scrollRefA} className="flex-1 overflow-y-auto scrollbar-fade px-4 py-4">
                {rounds.length === 0 && !loading && (
                  <div className="h-full flex flex-col items-center justify-center text-center">
                    <div className="w-16 h-16 rounded-2xl flex items-center justify-center mb-4" style={{ backgroundColor: `${persona.hex}12`, border: `1px solid ${persona.hex}25` }}>
                      <PIcon className="w-8 h-8" style={{ color: persona.hex }} />
                    </div>
                    <p className="text-sm text-[var(--text-muted)]">输入问题开始对比</p>
                  </div>
                )}
                {renderMessages('a')}
              </div>
            </div>
          )}
          {showB && (
            <div className={`flex-col rounded-2xl border border-[var(--border-color)] bg-[var(--bg-card)]/60 overflow-hidden backdrop-blur-sm ${soloSide ? 'flex w-full max-w-4xl' : !soloSide && mobileTab !== 'b' ? 'hidden md:flex flex-1' : 'flex flex-1'}`}>
              {renderChatHeader('b')}
              <div ref={scrollRefB} className="flex-1 overflow-y-auto scrollbar-fade px-4 py-4">
                {rounds.length === 0 && !loading && (
                  <div className="h-full flex flex-col items-center justify-center text-center">
                    <div className="w-16 h-16 rounded-2xl flex items-center justify-center mb-4" style={{ backgroundColor: `${persona.hex}12`, border: `1px solid ${persona.hex}25` }}>
                      <PIcon className="w-8 h-8" style={{ color: persona.hex }} />
                    </div>
                    <p className="text-sm text-[var(--text-muted)]">输入问题开始对比</p>
                  </div>
                )}
                {renderMessages('b')}
              </div>
            </div>
          )}
        </div>

        {/* Vote Panel */}
        <AnimatePresence>
          {hasPendingUnsubmitted && (
            <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 20 }}
              className="shrink-0 mx-6 mb-1 rounded-2xl border border-emerald-500/20 bg-[var(--bg-card)] p-4 space-y-3 shadow-lg relative z-10">
              <div className="flex items-center justify-between">
                <div>
                  <h4 className="text-sm font-semibold text-[var(--text-primary)]">Round {pendingVoteIdx + 1} Scoring</h4>
                  <p className="text-[10px] text-[var(--text-muted)] mt-0.5">Five-dimension range: 1-10</p>
                </div>
                <div className="flex items-center gap-2">
                  <button onClick={handleSkipVote} className="text-xs text-[var(--text-muted)] hover:text-[var(--text-primary)]">Skip</button>
                  <button onClick={handleSubmitVote}
                    className="flex items-center gap-1 px-3 py-1 rounded-lg bg-emerald-500 text-white text-xs font-medium hover:bg-emerald-600 transition-colors">
                    <Check className="w-3 h-3" /> Submit Vote
                  </button>
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                {VOTE_OPTIONS.map(opt => (
                  <button key={opt.value} onClick={() => setSelectedVote(opt.value)}
                    className={`px-3 py-1.5 rounded-lg border text-sm transition-colors ${selectedVote === opt.value ? 'border-emerald-500 bg-emerald-500/20 text-emerald-600 dark:text-emerald-400' : 'border-[var(--border-color)] hover:bg-[var(--bg-secondary)] text-[var(--text-secondary)]'}`}>
                    {t(opt.labelKey)}
                  </button>
                ))}
              </div>
              <div className={soloSide ? '' : 'grid grid-cols-2 gap-4'}>
                {(soloSide ? [soloSide] : ['a', 'b'] as const).map(side => (
                  <div key={side}>
                    <p className="text-xs text-[var(--text-muted)] mb-1">{side.toUpperCase()} Scoring <span className="text-[10px]">(1-10)</span></p>
                    {DIMENSIONS.map(d => (
                      <div key={d.key} className="flex items-center gap-2 mb-1">
                        <span className="w-8 text-[11px] text-[var(--text-secondary)]">{t(d.labelKey)}</span>
                        <input type="range" min={1} max={10} value={(side === 'a' ? curA : curB)[d.key]}
                          onChange={e => handleScoreChange(side as 'a' | 'b', d.key, parseInt(e.target.value, 10))}
                          className="flex-1 h-1.5 rounded-full appearance-none bg-[var(--border-color)] accent-emerald-500" />
                        <span className="w-4 text-[11px] font-medium text-[var(--text-primary)]">{(side === 'a' ? curA : curB)[d.key]}</span>
                      </div>
                    ))}
                  </div>
                ))}
              </div>
              <div>
                <p className="text-xs text-[var(--text-muted)] mb-1">评分备注（可选）</p>
                <textarea
                  value={voteRemark}
                  onChange={e => setVoteRemark(e.target.value)}
                  maxLength={240}
                  placeholder="可记录本轮偏好原因，如：A 更具体、B 更共情"
                  className="w-full rounded-lg border border-[var(--border-color)] bg-[var(--bg-secondary)]/40 px-3 py-2 text-xs text-[var(--text-primary)] outline-none focus:border-emerald-500/40 resize-none"
                  rows={2}
                />
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Bottom Input */}
        <div className="shrink-0 p-4 md:px-6 bg-[var(--bg-primary)] border-t border-[var(--border-color)] relative z-20">
          <div className={`mx-auto relative flex items-end gap-3 ${soloSide ? 'max-w-4xl' : 'max-w-5xl'}`}>
            <div className="flex-1 relative bg-[var(--bg-card)] border border-[var(--border-color)] rounded-2xl shadow-sm focus-within:border-emerald-500/50 focus-within:ring-4 focus-within:ring-emerald-500/10 transition-all">
              <textarea ref={inputRef} value={input} onChange={e => setInput(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() } }}
                disabled={loading}
                placeholder={loading ? '正在并行生成中…' : hasPendingUnsubmitted ? '请先完成打分或点击「跳过」' : soloSide ? '继续对话 (Enter 发送)' : '输入你的问题，左右同时回答 (Enter 发送)'}
                className="w-full max-h-[200px] min-h-[48px] py-3.5 pl-5 pr-14 bg-transparent resize-none outline-none text-[var(--text-primary)] placeholder-[var(--text-muted)] scrollbar-thin disabled:opacity-50"
                rows={1} />
              <motion.button id="arena-send-btn" whileHover={{ scale: 1.05 }} whileTap={{ scale: 0.95 }}
                onClick={handleSend} disabled={!input.trim() || loading}
                className="absolute right-2 bottom-2 p-2.5 rounded-xl bg-gradient-to-br from-emerald-500 to-teal-600 text-white disabled:opacity-50 disabled:from-[var(--bg-secondary)] disabled:to-[var(--bg-secondary)] disabled:text-[var(--text-muted)] transition-all shadow-md disabled:shadow-none">
                {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send size={18} className={input.trim() && !loading ? 'translate-x-0.5 -translate-y-0.5' : ''} />}
              </motion.button>
            </div>
          </div>
          <p className="text-center text-[10px] text-[var(--text-muted)] mt-2 hidden md:block">内容仅供参考，AI 顾问不能替代专业医疗建议。</p>
        </div>

        {/* Local toast removed in favor of global sonner Toaster */}
      </div>

      <ExportDialog
        open={showExport}
        onClose={() => setShowExport(false)}
        title="导出双镜对比"
        getData={() => arenaToExportData(
          rounds.map(r => ({ query: r.query, responseA: r.responseA, responseB: r.responseB, vote: r.vote, timestamp: r.timestamp })),
          contestants?.a, contestants?.b,
          rounds[0]?.query?.slice(0, 20),
        )}
      />
    </div>
  )
}
