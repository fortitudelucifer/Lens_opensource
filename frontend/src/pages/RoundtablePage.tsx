/**
 * 圆桌讨论 · Setup 页
 *
 * 改造自 MP 的 SetupPage.tsx：
 *   - Local useState → Zustand `useRoundtableStore`
 *   - `onStart` prop → 直接调 `startSession` + 通过 `activeNav` 切换到 session 页
 *   - 分组：按 `RoundtablePersona.category`（psychology / interdisciplinary）
 *
 * 对齐执行方案 §2A 图 1（UI 呈现层）+ 图 2（3-Phase 时序图）。
 */

import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import {
  Sparkles, ArrowRight, UsersRound, Info, Loader2,
  CheckCircle2, AlertCircle, MessageSquareText, Cpu,
  BookOpen, MessagesSquare, X,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import {
  PERSONAS,
  QUICK_PRESETS,
  type PersonaId,
  type RoundtablePersona,
} from '@/data/personas'
import { useRoundtableStore } from '@/stores/useRoundtableStore'
import { PersonaCard } from '@/components/roundtable/PersonaCard'
import { SessionHistoryList } from '@/components/roundtable/SessionHistoryList'
import {
  InjectionDrawer,
  type InjectionMode,
} from '@/components/roundtable/InjectionDrawer'
import { api, type AvailableModel } from '@/lib/api'

// Day 5 · E · backend 中文展示名（与 ModelSelector.tsx 保持一致）
const BACKEND_LABELS: Record<string, string> = {
  openai: 'OpenAI',
  claude: 'Claude',
  gemini: 'Gemini',
  kimi: 'Kimi',
  grok: 'Grok',
  deepseek: 'DeepSeek',
  qwen_local: 'Qwen 本地',
  qwen_cloud: 'Qwen 云端',
  glm: 'GLM',
}

// 问题质量阈值（UX Layer 2）
const QUESTION_LIGHT_THRESHOLD = 30   // 下不推荐圆桌
const QUESTION_DEEP_THRESHOLD = 100   // 上推荐圆桌充分
const MAX_PERSONAS = 3 as const
const MIN_QUESTION_LEN = 4
const MAX_QUESTION_LEN = 1000

interface RoundtablePageProps {
  /** 开启圆桌的回调（父级切换 activeNav 到 'roundtable-session'）*/
  onStart?: () => void
  /** 引导轻量问题去「沉浸式互动」（UX Layer 1+2 降级路径）*/
  onNavigateToChat?: () => void
}

export function RoundtablePage({ onStart, onNavigateToChat }: RoundtablePageProps) {
  const { t } = useTranslation()
  const selectedPersonas = useRoundtableStore((s) => s.selectedPersonas)
  const question = useRoundtableStore((s) => s.question)
  const deepMode = useRoundtableStore((s) => s.deepMode)
  const togglePersona = useRoundtableStore((s) => s.togglePersona)
  const setPersonas = useRoundtableStore((s) => s.setPersonas)
  const setQuestion = useRoundtableStore((s) => s.setQuestion)
  const setDeepMode = useRoundtableStore((s) => s.setDeepMode)
  const startSession = useRoundtableStore((s) => s.startSession)

  const psychology = useMemo(
    () => PERSONAS.filter((p) => p.category === 'psychology'),
    [],
  )
  const interdisc = useMemo(
    () => PERSONAS.filter((p) => p.category === 'interdisciplinary'),
    [],
  )

  // 「仍要开启」逃生通道：允许用户绕过质量门槛（仍保留自主权）
  const [bypassQuality, setBypassQuality] = useState(false)

  // Day 5 · E · LLM backend 下拉（null → 服务器默认 chat_backend）
  const [availableBackends, setAvailableBackends] = useState<AvailableModel[]>([])
  const [selectedBackend, setSelectedBackend] = useState<string | null>(null)
  const [backendsLoaded, setBackendsLoaded] = useState(false)

  // 首次挂载拉可用 backends（仅保留 chat-capable，与 roundtable 的 LLM 流式 chat 调用一致）
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const list = await api.getAvailableModels()
        if (cancelled) return
        const chatCapable = list.filter((m) => m.suitable_for.includes('chat'))
        setAvailableBackends(chatCapable)
      } catch (err) {
        console.warn('[Roundtable] failed to load available backends:', err)
        setAvailableBackends([])
      } finally {
        if (!cancelled) setBackendsLoaded(true)
      }
    })()
    return () => { cancelled = true }
  }, [])

  const isFull = selectedPersonas.length === MAX_PERSONAS
  const trimmedLen = question.trim().length
  const meetsMinLen = trimmedLen >= MIN_QUESTION_LEN
  const isLightweight = trimmedLen < QUESTION_LIGHT_THRESHOLD
  // 门槛逻辑：< 30 字默认阻断，除非用户主动点「仍要开启」
  const canStart = isFull && meetsMinLen && (!isLightweight || bypassQuality)

  // 问题字数跨过 30 字门槛后自动重置 bypass（避免不必要的"已绕过"残留状态）
  useEffect(() => {
    if (!isLightweight && bypassQuality) {
      setBypassQuality(false)
    }
  }, [isLightweight, bypassQuality])

  const activePreset = QUICK_PRESETS.find((p) => {
    if (p.ids.length !== selectedPersonas.length) return false
    return p.ids.every((id) => selectedPersonas.includes(id))
  })?.id

  const [creating, setCreating] = useState(false)

  // Day 7 · Setup 页 RAG 注入状态
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [drawerTab, setDrawerTab] = useState<InjectionMode>('chat_history')
  const [injectContext, setInjectContext] = useState('')
  const [injectSummary, setInjectSummary] = useState<{ chat: number; kn: number } | null>(null)

  function openInjectDrawer(tab: InjectionMode) {
    const trimmedQ = question.trim()
    if (trimmedQ.length < 2) {
      toast.info('请先写下你想讨论的问题（至少 2 个字），再调用检索', {
        description: '检索会用你的问题作为关键词',
      })
      return
    }
    setDrawerTab(tab)
    setDrawerOpen(true)
  }

  function handleInjectConfirm(context: string, summary: { chat: number; kn: number }) {
    setInjectContext(context)
    setInjectSummary(summary.chat + summary.kn > 0 ? summary : null)
  }

  function clearInject() {
    setInjectContext('')
    setInjectSummary(null)
  }

  const handleStart = async () => {
    if (!canStart || creating) return
    setCreating(true)
    try {
      // 优先走 backend：拿到真实 session_id 用于 SSE 订阅
      const { session_id } = await api.createRoundtableSession({
        personas: selectedPersonas,
        question: question.trim(),
        backend: selectedBackend ?? undefined,
        inject_context: injectContext || null,
        deep_mode: deepMode,
      })
      startSession(session_id)
      // session 已创建成功 · 清空 Setup 页的注入暂存（避免返回首页后残留给下一次）
      setInjectContext('')
      setInjectSummary(null)
      onStart?.()
    } catch (err) {
      // backend 不可用时降级到 mock（local 前缀让 SessionPage 走 runMockStreaming）
      const msg = err instanceof Error ? err.message : String(err)
      console.warn('[Roundtable] backend unavailable, falling back to mock:', msg)
      toast.warning('后端不可用，已降级到 mock 演示模式', {
        description: msg.slice(0, 80),
      })
      startSession(`rt_local_${Date.now()}`)
      onStart?.()
    } finally {
      setCreating(false)
    }
  }

  return (
    <div className="max-w-5xl mx-auto px-4 sm:px-6 pt-8 pb-28">
      {/* Hero */}
      <div className="mp-fade-up text-center max-w-2xl mx-auto">
        <div className="inline-flex items-center gap-1.5 text-[11px] uppercase tracking-[0.18em] text-muted-foreground mb-4">
          <Sparkles className="w-3.5 h-3.5 text-primary" />
          Roundtable · Beta
        </div>
        <h1 className="text-[28px] sm:text-[34px] font-semibold tracking-tight leading-tight">
          {t('roundtable.setup.heading')}
        </h1>
        <p className="mt-4 text-[15px] sm:text-base text-muted-foreground leading-relaxed">
          {t('roundtable.setup.description')}
        </p>
      </div>

      {/* Layer 1 · 引导卡：什么时候开圆桌 vs 建议走沉浸式互动 */}
      <GuidanceCard onNavigateToChat={onNavigateToChat} />

      {/* Day 6 · 历史圆桌会话入口（默认折叠 · 有历史时才出现卡片） */}
      <SessionHistoryList onOpenSession={onStart} />

      {/* Day 7 · RAG 注入面板（受 drawerOpen 控制，不占布局） */}
      <InjectionDrawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        query={question}
        defaultTab={drawerTab}
        onConfirm={handleInjectConfirm}
      />

      {/* Presets */}
      <div className="mt-10">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-[13px] font-semibold text-muted-foreground tracking-wide uppercase">
            {t('roundtable.setup.quickSelect')}
          </h2>
          {selectedPersonas.length > 0 && (
            <button
              onClick={() => setPersonas([])}
              className="text-[12px] text-muted-foreground hover:text-foreground transition"
            >
              {t('roundtable.setup.clear')}
            </button>
          )}
        </div>
        <div className="grid sm:grid-cols-3 gap-3">
          {QUICK_PRESETS.map((p) => {
            const active = activePreset === p.id
            return (
              <button
                key={p.id}
                onClick={() => setPersonas(p.ids)}
                className={cn(
                  'text-left p-4 rounded-2xl border bg-card transition-all',
                  active
                    ? 'border-primary/60 ring-2 ring-primary/20 shadow-sm'
                    : 'border-border hover:border-foreground/20',
                )}
              >
                <div className="flex items-center justify-between">
                  <span className="font-medium text-sm">{p.label}</span>
                  <UsersRound
                    className={cn(
                      'w-4 h-4',
                      active ? 'text-primary' : 'text-muted-foreground',
                    )}
                  />
                </div>
                <p className="text-[12px] text-muted-foreground mt-1.5">{p.description}</p>
              </button>
            )
          })}
        </div>
      </div>

      {/* Grid groups */}
      <div className="mt-10 space-y-8">
        <PersonaGroup
          title={t('roundtable.setup.psychologyGroup')}
          subtitle="Psychology"
          personas={psychology}
          selected={selectedPersonas}
          onToggle={togglePersona}
          full={isFull}
        />
        <PersonaGroup
          title={t('roundtable.setup.interdisciplinaryGroup')}
          subtitle="Interdisciplinary"
          personas={interdisc}
          selected={selectedPersonas}
          onToggle={togglePersona}
          full={isFull}
          indexOffset={psychology.length}
        />
      </div>

      {/* Counter */}
      <div
        className="mt-8 flex items-center justify-center gap-3 text-sm"
        aria-live="polite"
      >
        <div className="flex items-center gap-1.5">
          {[0, 1, 2].map((i) => (
            <span
              key={i}
              className={cn(
                'w-2.5 h-2.5 rounded-full transition-all',
                i < selectedPersonas.length ? 'bg-primary scale-110' : 'bg-muted',
              )}
            />
          ))}
        </div>
        <span className="text-muted-foreground">
          {t('roundtable.setup.selected', { count: selectedPersonas.length, max: MAX_PERSONAS })}
        </span>
      </div>

      {/* Question */}
      <div className="mt-10">
        <label className="block text-sm font-medium mb-2">{t('roundtable.setup.questionLabel')}</label>
        <div
          className={cn(
            'rounded-2xl border bg-card transition-all',
            canStart ? 'border-primary/40 ring-2 ring-primary/10' : 'border-border',
          )}
        >
          <textarea
            value={question}
            onChange={(e) => setQuestion(e.target.value.slice(0, MAX_QUESTION_LEN))}
            placeholder={t('roundtable.setup.questionPlaceholder')}
            rows={5}
            className="w-full resize-none bg-transparent p-4 text-[14.5px] leading-[1.75] outline-none placeholder:text-muted-foreground"
          />
          <div className="flex items-center justify-between px-4 py-2.5 border-t border-border/70 text-[11px] text-muted-foreground">
            <span className="inline-flex items-center gap-1.5">
              <Info className="w-3 h-3" />
              内容仅供探索参考，不构成诊断或治疗
            </span>
            <span>
              {question.length} / {MAX_QUESTION_LEN}
            </span>
          </div>
        </div>
        {/* Layer 2 · 实时质量信号 */}
        <QuestionQualityHint
          length={trimmedLen}
          onNavigateToChat={onNavigateToChat}
        />
      </div>

      {/* Day 7 · 注入参考资料（聊天记录 / 知识手册）· 纯视觉：不强制使用 */}
      <InjectionPicker
        injectSummary={injectSummary}
        injectCharCount={injectContext.length}
        onOpen={openInjectDrawer}
        onClear={clearInject}
        disabled={trimmedLen < 2}
      />

      {/* Day 7 · 深度模式 toggle */}
      <DepthModeToggle
        enabled={deepMode}
        onChange={setDeepMode}
        selectedBackend={selectedBackend}
        availableBackends={availableBackends}
      />

      {/* Backend 选择器 · Day 5 · E */}
      <BackendPicker
        available={availableBackends}
        loaded={backendsLoaded}
        value={selectedBackend}
        onChange={setSelectedBackend}
      />

      {/* CTA */}
      <div className="mt-6 flex flex-col sm:flex-row sm:items-center sm:justify-end gap-3">
        <p className="text-[12px] text-muted-foreground sm:mr-auto">
          开启后将进入 2 轮讨论（独立分析 → 交叉回应 → 综合总结）
        </p>

        {/* 「仍要开启」逃生通道：仅当问题轻量且其他条件均满足时显示 */}
        {isFull && meetsMinLen && isLightweight && !bypassQuality && (
          <button
            type="button"
            onClick={() => setBypassQuality(true)}
            className="text-[11px] text-muted-foreground hover:text-foreground underline underline-offset-4 transition"
            title="不推荐，但允许用户跳过质量门槛主动开启圆桌"
          >
            仍要开启 →
          </button>
        )}

        <button
          disabled={!canStart || creating}
          onClick={handleStart}
          title={
            !isFull
              ? `请先选择 ${MAX_PERSONAS} 位顾问`
              : !meetsMinLen
              ? '请输入你想讨论的问题'
              : isLightweight && !bypassQuality
              ? `问题太短（${trimmedLen} 字），请补充背景或点左侧「仍要开启」绕过`
              : ''
          }
          className={cn(
            'group inline-flex items-center justify-center gap-2 h-12 px-6 rounded-2xl font-medium text-sm transition-all',
            canStart && !creating
              ? 'bg-primary text-primary-foreground hover:shadow-md hover:-translate-y-0.5'
              : 'bg-muted text-muted-foreground cursor-not-allowed',
          )}
        >
          {creating ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" />
              Creating...
            </>
          ) : (
            <>
              {t('roundtable.setup.startButton')}
              <ArrowRight className="w-4 h-4 group-hover:translate-x-0.5 transition-transform" />
            </>
          )}
        </button>
      </div>
    </div>
  )
}

// ──────────────────────────────────────────────────────────────
// Day 5 · E · Backend Picker
// 一条横向 chip 行：默认、gemini、kimi、glm... 可点击切换
// ──────────────────────────────────────────────────────────────
interface BackendPickerProps {
  available: AvailableModel[]
  loaded: boolean
  value: string | null
  onChange: (next: string | null) => void
}

function BackendPicker({ available, loaded, value, onChange }: BackendPickerProps) {
  // 未加载完之前不占空间，避免跳动
  if (!loaded) return null
  // 没拉到任何 chat-capable backend：隐藏（仅用服务器默认）
  if (available.length === 0) return null

  return (
    <div className="mt-5 rounded-2xl border border-border/40 bg-muted/30 p-3.5 sm:p-4">
      <div className="flex items-center gap-2 mb-2.5">
        <Cpu className="w-3.5 h-3.5 text-muted-foreground" strokeWidth={1.8} />
        <span className="text-[12px] text-muted-foreground">
          讨论引擎 · 留空用服务器默认（<span className="font-medium text-foreground/70">chat_backend</span>）
        </span>
      </div>
      <div className="flex flex-wrap gap-2">
        <BackendChip
          active={value === null}
          onClick={() => onChange(null)}
          label="服务器默认"
          sub="env / prefs"
        />
        {available.map((m) => (
          <BackendChip
            key={m.backend}
            active={value === m.backend}
            onClick={() => onChange(m.backend)}
            label={BACKEND_LABELS[m.backend] ?? m.backend}
            sub={m.model.split('/').pop() ?? m.model}
          />
        ))}
      </div>
    </div>
  )
}

function BackendChip({
  active,
  onClick,
  label,
  sub,
}: {
  active: boolean
  onClick: () => void
  label: string
  sub: string
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'flex flex-col items-start gap-0.5 px-3 py-1.5 rounded-lg border text-left transition',
        active
          ? 'border-primary/60 bg-primary/10 ring-1 ring-primary/30'
          : 'border-border/60 bg-background hover:border-border hover:bg-muted/50',
      )}
      title={`${label} · ${sub}`}
    >
      <span className={cn('text-[12px] font-medium', active ? 'text-primary' : 'text-foreground/80')}>
        {label}
      </span>
      <span className="text-[10px] text-muted-foreground max-w-[160px] truncate">{sub}</span>
    </button>
  )
}

// ──────────────────────────────────────────────────────────────
// Day 7 · InjectionPicker · Setup 页 RAG 注入入口
// 两个按钮：聊天记录 / 知识手册 · 点击时打开同一个 InjectionDrawer
// 已选后显示 chip + 清除按钮
// ──────────────────────────────────────────────────────────────
interface InjectionPickerProps {
  injectSummary: { chat: number; kn: number } | null
  injectCharCount: number
  onOpen: (tab: InjectionMode) => void
  onClear: () => void
  /** 问题太短时禁用（需要 query 才能检索） */
  disabled: boolean
}

function InjectionPicker({
  injectSummary,
  injectCharCount,
  onOpen,
  onClear,
  disabled,
}: InjectionPickerProps) {
  const hasInjection = injectSummary !== null

  return (
    <div className="mt-5 rounded-2xl border border-border/40 bg-muted/30 p-3.5 sm:p-4">
      <div className="flex items-center gap-2 mb-2.5">
        <Sparkles className="w-3.5 h-3.5 text-muted-foreground" strokeWidth={1.8} />
        <span className="text-[12px] text-muted-foreground">
          注入参考资料 · <span className="text-foreground/70">可选</span>
        </span>
        <span className="ml-auto text-[11px] text-muted-foreground/70 hidden sm:inline">
          让 3 位顾问参考你过去的对话片段或专业知识
        </span>
      </div>

      <div className="flex flex-wrap gap-2 items-center">
        <button
          type="button"
          onClick={() => onOpen('chat_history')}
          disabled={disabled}
          title={
            disabled
              ? '请先写下至少 2 个字的问题作为检索关键词'
              : '检索过去聊天记录中与当前问题相关的片段'
          }
          className={cn(
            'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-[12px] transition',
            disabled
              ? 'border-border/40 bg-background/40 text-muted-foreground/50 cursor-not-allowed'
              : 'border-border/60 bg-background text-foreground/80 hover:border-primary/40 hover:bg-muted/50',
          )}
        >
          <MessagesSquare className="w-3.5 h-3.5" />
          聊天记录
        </button>
        <button
          type="button"
          onClick={() => onOpen('knowledge')}
          disabled={disabled}
          title={
            disabled
              ? '请先写下至少 2 个字的问题作为检索关键词'
              : '检索专业知识手册中与当前问题相关的条目'
          }
          className={cn(
            'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-[12px] transition',
            disabled
              ? 'border-border/40 bg-background/40 text-muted-foreground/50 cursor-not-allowed'
              : 'border-border/60 bg-background text-foreground/80 hover:border-primary/40 hover:bg-muted/50',
          )}
        >
          <BookOpen className="w-3.5 h-3.5" />
          知识手册
        </button>

        {hasInjection && (
          <div className="inline-flex items-center gap-2 ml-1 px-2.5 py-1 rounded-full bg-primary/10 ring-1 ring-primary/30 text-[11px] text-primary">
            <CheckCircle2 className="w-3 h-3" strokeWidth={2.5} />
            <span>
              已选 {injectSummary!.chat} 片段 · {injectSummary!.kn} 知识 ·{' '}
              <span className="tabular-nums">{injectCharCount}</span> 字
            </span>
            <button
              type="button"
              onClick={onClear}
              className="inline-flex items-center justify-center -mr-1 rounded-full p-0.5 hover:bg-primary/20 transition"
              title="清除已选"
              aria-label="清除已选注入"
            >
              <X className="w-3 h-3" strokeWidth={2.5} />
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

// ──────────────────────────────────────────────────────────────
// Day 7 · DepthModeToggle · 深度讨论模式开关
// 开启后：每 agent 500-900 字的深入分析（否则 150-300 字），max_tokens
// 翻倍；同时提示用户推荐使用思考模型（claude-*-think / qwen-thinking）
// ──────────────────────────────────────────────────────────────
interface DepthModeToggleProps {
  enabled: boolean
  onChange: (v: boolean) => void
  selectedBackend: string | null
  availableBackends: AvailableModel[]
}

function DepthModeToggle({
  enabled,
  onChange,
  selectedBackend,
  availableBackends,
}: DepthModeToggleProps) {
  // 判断当前选的 backend 是否是"思考模型"（通过 model 名/backend 名粗略匹配）
  const isThinkingBackend = (() => {
    if (!selectedBackend) return null // 未选 → 未知
    const hit = availableBackends.find((m) => m.backend === selectedBackend)
    if (!hit) return null
    const modelLower = (hit.model || '').toLowerCase()
    const bkLower = selectedBackend.toLowerCase()
    return (
      modelLower.includes('think') ||
      modelLower.includes('reason') ||
      modelLower.includes('o1') ||
      modelLower.includes('o3') ||
      bkLower.includes('qwen_cloud')
    )
  })()

  // 深度模式 + 非思考模型时给温柔提示（不阻塞）
  const showThinkingHint = enabled && isThinkingBackend === false

  return (
    <div
      className={cn(
        'mt-5 rounded-2xl border p-3.5 sm:p-4 transition-all',
        enabled
          ? 'border-primary/40 bg-primary/5 ring-1 ring-primary/15'
          : 'border-border/40 bg-muted/30',
      )}
    >
      <div className="flex items-start gap-3">
        {/* Toggle switch */}
        <button
          type="button"
          role="switch"
          aria-checked={enabled}
          onClick={() => onChange(!enabled)}
          className={cn(
            'relative shrink-0 mt-0.5 inline-flex h-5 w-9 items-center rounded-full transition-colors',
            'focus:outline-none focus:ring-2 focus:ring-primary/30 focus:ring-offset-1',
            enabled ? 'bg-primary' : 'bg-muted-foreground/30',
          )}
        >
          <span
            className={cn(
              'inline-block h-3.5 w-3.5 rounded-full bg-white shadow-sm transition-transform',
              enabled ? 'translate-x-[18px]' : 'translate-x-[3px]',
            )}
          />
        </button>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span
              className={cn(
                'text-sm font-medium',
                enabled ? 'text-primary' : 'text-foreground/80',
              )}
            >
              深度讨论模式
            </span>
            <span className="text-[11px] text-muted-foreground">
              {enabled
                ? '每位顾问 500-900 字 · 带流派解释 + 落点动作'
                : '默认：每位顾问 150-300 字的简短视角'}
            </span>
          </div>
          <p className="mt-1 text-[11.5px] text-muted-foreground leading-relaxed">
            开启后每个 agent 的 max_tokens 翻倍（1024 → 2560），Moderator 也会输出更长的综合。
            生成速度会更慢，但分析更完整。
            {enabled && (
              <>
                <br />
                <span className="text-primary/80">
                  推荐配合「思考模型」使用 ·
                </span>{' '}
                例如 claude-sonnet-think、qwen3-235B-thinking、gemini-think 等。
              </>
            )}
          </p>

          {showThinkingHint && (
            <div className="mt-2 flex items-center gap-1.5 rounded-md bg-amber-500/10 border border-amber-500/30 px-2.5 py-1.5 text-[11px] text-amber-700 dark:text-amber-200">
              <AlertCircle className="w-3 h-3 shrink-0" />
              <span>
                当前 backend「
                <span className="font-medium">{selectedBackend}</span>
                」可能不是思考模型 · 建议切到 claude/qwen 的 thinking 变体以获得更好效果
              </span>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

interface PersonaGroupProps {
  title: string
  subtitle: string
  personas: RoundtablePersona[]
  selected: PersonaId[]
  onToggle: (id: PersonaId) => void
  full: boolean
  indexOffset?: number
}

function PersonaGroup({
  title,
  subtitle,
  personas,
  selected,
  onToggle,
  full,
  indexOffset = 0,
}: PersonaGroupProps) {
  return (
    <section>
      <div className="flex items-baseline gap-2 mb-3">
        <h2 className="text-sm font-semibold">{title}</h2>
        <span className="text-[11px] text-muted-foreground font-mono tracking-wide">
          {subtitle}
        </span>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {personas.map((p, i) => (
          <PersonaCard
            key={p.id}
            persona={p}
            selected={selected.includes(p.id)}
            disabled={full && !selected.includes(p.id)}
            onToggle={() => onToggle(p.id)}
            index={indexOffset + i}
          />
        ))}
      </div>
    </section>
  )
}

// ═══════════════════════════════════════════════════════════════════
// UX Layer 1 · 引导卡：什么时候开圆桌 vs 不合适
// ═══════════════════════════════════════════════════════════════════

function GuidanceCard({ onNavigateToChat }: { onNavigateToChat?: () => void }) {
  return (
    <div className="mp-fade-up mt-8 grid grid-cols-1 md:grid-cols-2 gap-3">
      {/* 适合圆桌 */}
      <div className="rounded-2xl border border-emerald-200/60 bg-emerald-50/40 dark:border-emerald-400/20 dark:bg-emerald-950/15 p-4">
        <div className="flex items-center gap-2 mb-2">
          <CheckCircle2 className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
          <h3 className="text-sm font-semibold text-emerald-700 dark:text-emerald-200">
            适合开圆桌
          </h3>
        </div>
        <ul className="text-[12.5px] leading-[1.7] text-foreground/85 space-y-1">
          <li>· 复杂关系困境（涉及多人 / 多原因 / 反复纠结）</li>
          <li>· 想被多个视角"看见"，而不是只听一种声音</li>
          <li>· 有充分背景描述（建议 ≥ 100 字）</li>
        </ul>
      </div>

      {/* 不适合圆桌 → 推荐沉浸式 */}
      <div className="rounded-2xl border border-amber-200/60 bg-amber-50/40 dark:border-amber-400/20 dark:bg-amber-950/15 p-4">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <AlertCircle className="w-4 h-4 text-amber-600 dark:text-amber-400" />
            <h3 className="text-sm font-semibold text-amber-700 dark:text-amber-200">
              这些情况建议走沉浸式
            </h3>
          </div>
          {onNavigateToChat && (
            <button
              onClick={onNavigateToChat}
              className="inline-flex items-center gap-1 text-[11px] font-medium text-amber-700 dark:text-amber-200 hover:underline underline-offset-4"
              title="跳转到沉浸式互动单 agent 对话"
            >
              <MessageSquareText className="w-3 h-3" />
              沉浸式互动 →
            </button>
          )}
        </div>
        <ul className="text-[12.5px] leading-[1.7] text-foreground/85 space-y-1">
          <li>· 一句话问答（信息片段化）</li>
          <li>· 求快速建议（"今晚约会穿什么"）</li>
          <li>· 只想要单一专业视角（如只想心理咨询）</li>
        </ul>
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════════
// UX Layer 2 · textarea 实时质量信号
// ═══════════════════════════════════════════════════════════════════

function QuestionQualityHint({
  length,
  onNavigateToChat,
}: {
  length: number
  onNavigateToChat?: () => void
}) {
  // 空文本不显示
  if (length === 0) return null

  // < 30 字：amber 警告 + 转向按钮
  if (length < QUESTION_LIGHT_THRESHOLD) {
    return (
      <div
        className="mt-2 flex items-start gap-2 rounded-lg border border-amber-300/40 bg-amber-50/40 dark:border-amber-400/25 dark:bg-amber-950/15 px-3 py-2"
        role="alert"
      >
        <AlertCircle className="w-3.5 h-3.5 mt-0.5 shrink-0 text-amber-600 dark:text-amber-300" />
        <div className="flex-1 text-[12px] leading-[1.7] text-amber-800 dark:text-amber-200">
          <span className="font-medium">问题较短，圆桌讨论可能流于表面。</span>{' '}
          建议补充背景细节（发生了什么 / 你的感受 / 期待的结果），或者
          {onNavigateToChat && (
            <button
              onClick={onNavigateToChat}
              className="ml-1 inline-flex items-center gap-0.5 font-medium text-amber-700 dark:text-amber-300 hover:underline underline-offset-2"
            >
              <MessageSquareText className="w-3 h-3" />
              转向沉浸式互动 →
            </button>
          )}
        </div>
      </div>
    )
  }

  // 30-100 字：中性 OK
  if (length < QUESTION_DEEP_THRESHOLD) {
    return (
      <div className="mt-2 flex items-center gap-1.5 px-3 py-1.5 text-[11.5px] text-muted-foreground">
        <CheckCircle2 className="w-3 h-3 text-muted-foreground" />
        <span>问题清晰，可以开启圆桌。补充更多背景会让讨论更深入。</span>
      </div>
    )
  }

  // ≥ 100 字：绿色优秀
  return (
    <div className="mt-2 flex items-center gap-1.5 rounded-lg border border-emerald-300/40 bg-emerald-50/40 dark:border-emerald-400/25 dark:bg-emerald-950/15 px-3 py-1.5">
      <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-300" />
      <span className="text-[12px] font-medium text-emerald-700 dark:text-emerald-200">
        问题信息充分，圆桌讨论将更有深度 ✨
      </span>
    </div>
  )
}
