/**
 * 圆桌讨论 · Session 页
 *
 * 改造自 MP 的 SessionPage.tsx：
 *   - Local useState/useRef → Zustand `useRoundtableStore`
 *   - Mock streaming 保留（Day 5 切换真实 SSE）
 *   - 两阶段真实展示（D1/D10）：Phase 1 完整 → 2s 过渡条 → Phase 2 完整
 *
 * 对齐执行方案 §2A 图 2（3-Phase 时序图）。
 */

import { useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { ArrowLeft, Quote, Share2, Pencil, Radio, FlaskConical, ChevronDown, MessagesSquare, Archive, RotateCcw } from 'lucide-react'
import { cn } from '@/lib/utils'
import { getPersona, type PersonaId } from '@/data/personas'
import { useRoundtableStore } from '@/stores/useRoundtableStore'
import { useRoundtableStream } from '@/hooks/useRoundtableStream'
import { useReducedMotion } from '@/hooks/useReducedMotion'
import { AgentMessage } from '@/components/roundtable/AgentMessage'
import { ModeratorCard } from '@/components/roundtable/ModeratorCard'
import { ModeratorThinking } from '@/components/roundtable/ModeratorThinking'
import { PhaseBanner } from '@/components/roundtable/PhaseBanner'
import { FollowUpComposer } from '@/components/roundtable/FollowUpComposer'
import { RoundHistoryCard } from '@/components/roundtable/RoundHistoryCard'
import {
  PHASE1_TEXTS,
  PHASE1_CONFIDENCE,
  PHASE2_TEXTS,
  PHASE2_CONFIDENCE,
  MOCK_MODERATOR,
} from '@/mocks/roundtableMock'

interface RoundtableSessionPageProps {
  onBack?: () => void
}

// ── Mock streaming 配置（Day 5 切换真实 SSE 后移除）──
const PHASE_TRANSITION_MS = 2000
const TYPING_DELAY_MIN = 400
const TYPING_DELAY_JITTER = 600
const STREAM_CHAR_INTERVAL_MS = 22
const STREAM_JITTER_MS = 8 // 错位让 3 列不同步完成，更像人在思考

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

export function RoundtableSessionPage({ onBack }: RoundtableSessionPageProps) {
  const { t } = useTranslation()
  const sessionId = useRoundtableStore((s) => s.sessionId)
  const question = useRoundtableStore((s) => s.question)
  const currentPhase = useRoundtableStore((s) => s.currentPhase)
  const phase1Agents = useRoundtableStore((s) => s.phase1Agents)
  const phase2Agents = useRoundtableStore((s) => s.phase2Agents)
  const moderator = useRoundtableStore((s) => s.moderator)
  const moderatorThinking = useRoundtableStore((s) => s.moderatorThinking)
  const moderatorFallbackReason = useRoundtableStore((s) => s.moderatorFallbackReason)
  // Day 7 · D7.1.f · 只读快照模式（phase != 'done' 的历史 session）
  const isReadOnlySnapshot = useRoundtableStore((s) => s.isReadOnlySnapshot)
  const resetSession = useRoundtableStore((s) => s.resetSession)
  const selectedPersonas = useRoundtableStore((s) => s.selectedPersonas)
  // Day 6 · 多轮
  const rounds = useRoundtableStore((s) => s.rounds)
  const roundIndex = useRoundtableStore((s) => s.roundIndex)
  const streamNonce = useRoundtableStore((s) => s.streamNonce)

  const advancePhase = useRoundtableStore((s) => s.advancePhase)
  const setAgentStatus = useRoundtableStore((s) => s.setAgentStatus)
  const appendAgentText = useRoundtableStore((s) => s.appendAgentText)
  const setAgentConfidence = useRoundtableStore((s) => s.setAgentConfidence)
  const setModerator = useRoundtableStore((s) => s.setModerator)

  const simStartedRef = useRef(false)
  const moderatorRef = useRef<HTMLDivElement>(null)
  // Day 7 · 追问入口 ref · Moderator 到位后滚动露出，避免用户误以为讨论已结束
  const followUpRef = useRef<HTMLDivElement>(null)

  // D5.4 / D7.1.i · reduced-motion 用户跳过 mock typing/streaming sleep + phase 过渡
  // 以及把 scrollIntoView 从 'smooth' 改成 'auto'（默认）
  const reducedMotion = useReducedMotion()
  const scrollBehavior: ScrollBehavior = reducedMotion ? 'auto' : 'smooth'

  // Backend session id 以 'rt_' 开头但不含 'rt_local_' 前缀
  // local 前缀意味着是 RoundtablePage 在 backend 不可用时生成的降级 id
  const isBackendSession = !!sessionId && sessionId.startsWith('rt_') && !sessionId.startsWith('rt_local_')

  // 真实 backend SSE 订阅（仅当 sessionId 为 backend 格式时启用）
  // Day 6 · streamNonce 每次 +1（continue 追问后）会触发重连
  // Day 6 · hydrate 历史 done session 不订阅（避免事件重放），continue 后 phase → 'setup' 会恢复
  // Day 7 · D7.1.f · 只读快照模式下也不订阅（phase != 'done' 的历史 session）·
  //         避免 EventSource 挂空连接（backend pipeline 可能已结束）
  const { status: streamStatus, error: streamError } = useRoundtableStream({
    enabled: isBackendSession && currentPhase !== 'done' && !isReadOnlySnapshot,
    sessionId,
    streamNonce,
    onError: (err) => {
      console.error('[Roundtable SSE]', err)
      toast.error('Roundtable interrupted', { description: err.message.slice(0, 100) })
    },
    onDone: () => {
      // backend 发送 done 后滚动到 Moderator（reduced-motion 时直接跳，不滚动延迟）
      setTimeout(() => {
        moderatorRef.current?.scrollIntoView({ behavior: scrollBehavior, block: 'start' })
      }, reducedMotion ? 0 : 200)
    },
  })

  // Day 7 · Moderator 到位后延迟 2s 把追问入口滚进视野中下部（提醒用户可继续）
  // 仅在首次变为 done 时触发，避免反复滚动干扰阅读
  useEffect(() => {
    if (currentPhase !== 'done') return
    if (!isBackendSession || !sessionId) return
    const t = setTimeout(() => {
      followUpRef.current?.scrollIntoView({
        behavior: scrollBehavior,
        block: 'end',
      })
    }, reducedMotion ? 0 : 1800)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentPhase, sessionId])

  // Mock 流式模拟（仅在 backend 降级（rt_local_*）时运行）
  useEffect(() => {
    if (simStartedRef.current) return
    if (!sessionId || selectedPersonas.length === 0) return
    if (isBackendSession) return // backend 上路不跑 mock
    simStartedRef.current = true
    void runMockStreaming()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, isBackendSession])

  /**
   * 单个 agent 的完整流式过程（typing → streaming → done）
   * 抽出后能被 Promise.all 并发调度，实现三列同时思考的视觉效果。
   */
  async function streamOneAgent(
    phase: 'phase1' | 'phase2',
    personaId: PersonaId,
    text: string,
    confidence: number,
  ) {
    // D5.4 · reduced-motion 直接跳过 typing/streaming 两段动画，直接 done
    if (reducedMotion) {
      setAgentStatus(phase, personaId, 'streaming')
      appendAgentText(phase, personaId, text)
      setAgentStatus(phase, personaId, 'done')
      setAgentConfidence(phase, personaId, confidence)
      return
    }

    // typing 阶段：随机 delay 让 3 人不同时启动
    setAgentStatus(phase, personaId, 'typing')
    await sleep(TYPING_DELAY_MIN + Math.random() * TYPING_DELAY_JITTER)

    // streaming 阶段：逐字流，加 jitter 错位 3 列
    setAgentStatus(phase, personaId, 'streaming')
    for (const ch of text) {
      appendAgentText(phase, personaId, ch)
      await sleep(STREAM_CHAR_INTERVAL_MS + Math.random() * STREAM_JITTER_MS)
    }

    // done 阶段
    setAgentStatus(phase, personaId, 'done')
    setAgentConfidence(phase, personaId, confidence)
  }

  async function runMockStreaming() {
    // ── Phase 1 · 3 位 agent 并发 ──
    if (!reducedMotion) await sleep(400)
    await Promise.all(
      selectedPersonas.map((personaId) =>
        streamOneAgent(
          'phase1',
          personaId,
          PHASE1_TEXTS[personaId] ?? '(No sample for this school)',
          PHASE1_CONFIDENCE[personaId] ?? 0.75,
        ),
      ),
    )

    // ── 过渡：Phase 1 → Phase 2（旧三列淑化 + PhaseBanner 出现）──
    advancePhase('phase2')
    if (!reducedMotion) await sleep(PHASE_TRANSITION_MS)

    // ── Phase 2 · 3 位 agent 并发 ──
    await Promise.all(
      selectedPersonas.map((personaId) =>
        streamOneAgent(
          'phase2',
          personaId,
          PHASE2_TEXTS[personaId] ?? '(No response yet)',
          PHASE2_CONFIDENCE[personaId] ?? 0.78,
        ),
      ),
    )

    // ── 过渡：Phase 2 → Phase 3（Moderator）──
    advancePhase('phase3')
    if (!reducedMotion) await sleep(PHASE_TRANSITION_MS)

    // ── Phase 3 · Moderator 居中单卡 ──
    setModerator(MOCK_MODERATOR)
    advancePhase('done')

    // 滚动到 Moderator（reduced-motion 时直接到位）
    if (!reducedMotion) await sleep(200)
    moderatorRef.current?.scrollIntoView({ behavior: scrollBehavior, block: 'start' })
  }

  if (!sessionId) {
    // D7.2.a · 空态文案打磨：更柔和的引导 + 视觉锚点（3 个顾问 emoji）
    return (
      <div className="max-w-2xl mx-auto px-4 pt-16 text-center mp-fade-up">
        <div
          className="inline-flex items-center gap-2 text-4xl leading-none select-none mb-4"
          role="img"
          aria-label="Three advisors are waiting for your roundtable"
        >
          <span>🧭</span>
          <span className="opacity-70">·</span>
          <span>🤗</span>
          <span className="opacity-70">·</span>
          <span>💗</span>
        </div>
        <h2 className="text-lg font-semibold text-foreground mb-2">
          {t('roundtable.session.notStarted')}
        </h2>
        <p className="text-sm text-muted-foreground leading-relaxed">
          {t('roundtable.session.notStartedDesc')}
        </p>
        {onBack && (
          <button
            onClick={onBack}
            className="mt-6 inline-flex items-center gap-2 rounded-full border border-border/60 bg-card/60 px-5 py-2 text-sm text-foreground hover:bg-card transition-colors"
          >
            <ArrowLeft className="h-4 w-4" strokeWidth={2} />
            {t('roundtable.session.backToSetup')}
          </button>
        )}
      </div>
    )
  }

  const personaNames = selectedPersonas
    .map((id) => getPersona(id)?.name ?? id)
    .join(' · ')

  // 旧 phase 是否应该淑化（当进入下一阶段后，旧阶段轻微变灰以引导视觉重心）
  const phase1Faded = currentPhase === 'phase2' || currentPhase === 'phase3' || currentPhase === 'done'
  const phase2Faded = currentPhase === 'phase3' || currentPhase === 'done'

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 pt-6 pb-32">
      {/* Top bar */}
      <div className="mp-fade-up flex items-center justify-between mb-6">
        <button
          onClick={onBack}
          className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition"
        >
          <ArrowLeft className="w-4 h-4" />
          {t('roundtable.session.backToSetup')}
        </button>
        <div className="flex items-center gap-2">
          {/* 源指示徽章（D3.6 · 让用户一眼看到是 Backend SSE 还是 Mock）*/}
          <SourceBadge isBackend={isBackendSession} status={streamStatus} hasError={!!streamError} />
          <button
            className="inline-flex items-center gap-1 rounded-lg border border-border bg-card px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground transition"
            disabled
            title={t('roundtable.session.shareTooltip')}
          >
            <Share2 className="w-3.5 h-3.5" />
            {t('roundtable.session.share')}
          </button>
          <button
            className="inline-flex items-center gap-1 rounded-lg border border-border bg-card px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground transition"
            disabled
            title={t('roundtable.session.editTooltip')}
          >
            <Pencil className="w-3.5 h-3.5" />
            {t('roundtable.session.edit')}
          </button>
        </div>
      </div>

      {/* Day 6 · 历史轮展示（按轮序从旧到新，默认全折叠） */}
      {rounds.length > 0 && (
        <div className="mp-fade-up mb-8 space-y-3">
          <h2 className="max-w-3xl mx-auto text-xs font-semibold text-muted-foreground uppercase tracking-wide">
            {t('roundtable.session.completedRounds', { count: rounds.length })}
          </h2>
          {rounds.map((snap) => (
            <RoundHistoryCard key={snap.roundIndex} snapshot={snap} />
          ))}
        </div>
      )}

      {/* Day 7 · D7.1.f · 只读快照 banner（phase != 'done' 的历史 session · 醒目 amber 提示 + 新开会话按钮） */}
      {isReadOnlySnapshot && (
        <div
          role="status"
          aria-live="polite"
          className="mp-fade-up max-w-3xl mx-auto mb-6 rounded-2xl border border-amber-400/60 bg-amber-50/80 dark:bg-amber-950/30 dark:border-amber-500/40 p-5"
        >
          <div className="flex items-start gap-3">
            <Archive
              className="w-5 h-5 shrink-0 mt-0.5 text-amber-600 dark:text-amber-400"
              aria-hidden="true"
            />
            <div className="flex-1 min-w-0">
              <p className="text-sm font-semibold text-amber-900 dark:text-amber-200">
                This is an unfinished historical discussion · Read-only snapshot
              </p>
              <p className="mt-1 text-xs text-amber-800/90 dark:text-amber-200/80 leading-relaxed">
                Current session stopped at <code className="rounded bg-amber-500/10 px-1.5 py-0.5 font-mono text-[11px]">{currentPhase}</code> phase. The backend discussion may have ended or been interrupted.
                No live updates to avoid content duplication.
                <br />
                <span className="text-amber-700/80 dark:text-amber-300/70">
                  Continue reading above · Start a new discussion to ask follow-up questions.
                </span>
              </p>
              <button
                type="button"
                onClick={() => {
                  resetSession()
                  onBack?.()
                }}
                className={cn(
                  'mt-3 inline-flex items-center gap-1.5 rounded-lg bg-amber-600 hover:bg-amber-700 text-white',
                  'px-3 py-1.5 text-xs font-semibold transition-colors',
                  'dark:bg-amber-500 dark:hover:bg-amber-400 dark:text-amber-950',
                )}
              >
                <RotateCcw className="w-3.5 h-3.5" aria-hidden="true" />
                {t('roundtable.session.newDiscussion')}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Question header · MP 融合：Quote 引用风格（让用户问题"被认真对待"） */}
      {/* 占位变量防止 lint 报"未使用"*/}
      <div className="mp-fade-up max-w-3xl mx-auto rounded-2xl border border-border/60 bg-muted/40 p-6 mb-8 backdrop-blur relative">
        <Quote
          className="absolute top-4 left-4 w-8 h-8 text-primary/20 rotate-180"
          aria-hidden="true"
        />
        <p className="text-base sm:text-lg leading-relaxed font-medium text-foreground/90 pl-10 relative z-10">
          {question}
        </p>
        <p className="mt-4 text-xs text-muted-foreground pl-10 flex items-center gap-2">
          <span>Discussing with {personaNames}</span>
          {roundIndex > 0 && (
            <span className="inline-flex items-center rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-semibold text-primary ring-1 ring-primary/20">
              Round {roundIndex + 1}
            </span>
          )}
        </p>
      </div>

      {/* Phase 1 · 三列并列 */}
      <section className="mb-8 flex flex-col gap-4">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">
            Phase 1 · Independent Analysis
          </h2>
          <span className="text-xs text-muted-foreground">
            {countDone(phase1Agents)} / {selectedPersonas.length}
          </span>
        </div>
        <div
          className={cn(
            'grid grid-cols-1 lg:grid-cols-3 gap-4 transition-all duration-700',
            phase1Faded && 'opacity-50 scale-[0.98] grayscale-[0.4]',
          )}
          aria-label={phase1Faded ? t('roundtable.session.phase1Completed') : t('roundtable.session.phase1InProgress')}
        >
          {phase1Agents.map((agent) => (
            <AgentMessage
              key={`p1-${agent.personaId}`}
              agent={agent}
              phaseLabel="🧠 Independent View"
              compact
            />
          ))}
        </div>
      </section>

      {/* Phase 过渡横幅（phase2 开始时渲染） */}
      {(currentPhase === 'phase2' || currentPhase === 'phase3' || currentPhase === 'done') && (
        <div className="mb-6">
          <PhaseBanner phase="phase2" />
        </div>
      )}

      {/* Phase 2 · 三列并列 */}
      {(currentPhase === 'phase2' || currentPhase === 'phase3' || currentPhase === 'done') && (
        <section className="mb-8 flex flex-col gap-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">
              {t('roundtable.session.phase2Title')}
            </h2>
            <span className="text-xs text-muted-foreground">
              {countDone(phase2Agents)} / {selectedPersonas.length}
            </span>
          </div>
          <div
            className={cn(
              'grid grid-cols-1 lg:grid-cols-3 gap-4 transition-all duration-700',
              phase2Faded && 'opacity-50 scale-[0.98] grayscale-[0.4]',
            )}
            aria-label={phase2Faded ? 'Phase 2 completed' : 'Phase 2 in progress'}
          >
            {phase2Agents.map((agent) => (
              <AgentMessage
                key={`p2-${agent.personaId}`}
                agent={agent}
                phaseLabel="🔄 Response after seeing peers"
                compact
              />
            ))}
          </div>
        </section>
      )}

      {/* Phase 过渡 → 综合（thinking 未到达时展示进度条，避免空白） */}
      {(currentPhase === 'phase3' || currentPhase === 'done') && !moderator && !moderatorThinking && (
        <div className="mb-6">
          <PhaseBanner phase="phase3" />
        </div>
      )}

      {/* Moderator 综合思考段（打字机 · 自动折叠） */}
      {moderatorThinking && (
        <div className="mb-5 max-w-3xl mx-auto">
          <ModeratorThinking
            text={moderatorThinking}
            moderatorDone={moderator !== null}
          />
        </div>
      )}

      {/* Phase 3 · Moderator 居中单卡 */}
      {moderator && (
        <div ref={moderatorRef} className="scroll-mt-8 max-w-3xl mx-auto">
          <ModeratorCard
            content={moderator}
            fallbackReason={moderatorFallbackReason}
            roundIndex={roundIndex}
          />
        </div>
      )}

      {/* Day 6 · 追问输入框（仅 done + backend session 允许）*/}
      {currentPhase === 'done' && isBackendSession && sessionId && (
        <div ref={followUpRef} className="scroll-mt-4">
          {/* Day 7 · 显眼「继续讨论」指示卡 · 引导用户注意到可以追问 */}
          <div className="max-w-3xl mx-auto mt-8 mb-3 flex flex-col items-center text-center">
            <div className="inline-flex items-center gap-2 rounded-full bg-primary/10 px-3 py-1 text-[12px] text-primary font-medium">
              <MessagesSquare className="w-3.5 h-3.5" />
              Discussion completed · You can continue asking
            </div>
            <ChevronDown
              className={cn(
                'w-5 h-5 text-primary/60 mt-2',
                !reducedMotion && 'animate-bounce',
              )}
              aria-hidden="true"
            />
            <p className="mt-1 text-[12px] text-muted-foreground">
              Continue asking in the input below · The 3 advisors will respond with memory from this round
            </p>
          </div>
          <FollowUpComposer sessionId={sessionId} />
        </div>
      )}

      {/* Debug panel（dev 环境） */}
      {import.meta.env.DEV && (
        <div className="mt-12 rounded-lg border border-dashed border-border/50 bg-muted/30 p-3 text-[11px] text-muted-foreground">
          <code>
            session={sessionId} · phase={currentPhase} · personas=
            {selectedPersonas.join(',')}
          </code>
        </div>
      )}
    </div>
  )
}

function countDone(agents: { status: string }[]): number {
  return agents.filter((a) => a.status === 'done').length
}

/**
 * 源指示徽章（D3.6 · 区分 Backend SSE / Mock 降级）
 */
function SourceBadge({
  isBackend,
  status,
  hasError,
}: {
  isBackend: boolean
  status: string
  hasError: boolean
}) {
  if (isBackend) {
    const statusColor = hasError
      ? 'bg-red-500/15 text-red-600 dark:text-red-300 ring-red-500/30'
      : status === 'streaming'
      ? 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-300 ring-emerald-500/30'
      : 'bg-blue-500/15 text-blue-600 dark:text-blue-300 ring-blue-500/30'
    const statusText = hasError
      ? '错误'
      : status === 'streaming'
      ? '流中'
      : status === 'connecting'
      ? '连接中'
      : status === 'closed'
      ? '已完成'
      : status
    return (
      <span
        className={cn(
          'inline-flex items-center gap-1 rounded-md px-2 py-1 text-[10px] font-semibold ring-1',
          statusColor,
        )}
        title={`后端 SSE · ${statusText}`}
      >
        <Radio className="w-3 h-3" />
        Backend SSE · {statusText}
      </span>
    )
  }
  return (
    <span
      className="inline-flex items-center gap-1 rounded-md bg-amber-500/15 px-2 py-1 text-[10px] font-semibold text-amber-600 dark:text-amber-300 ring-1 ring-amber-500/30"
      title="后端不可用，使用 mock 流式模拟"
    >
      <FlaskConical className="w-3 h-3" />
      Mock 演示
    </span>
  )
}
