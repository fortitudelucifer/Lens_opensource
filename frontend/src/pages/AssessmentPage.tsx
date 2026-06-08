import { useState, useEffect, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { api, type AssessmentResult } from '../lib/api'
import {
  Info, ChevronRight, ChevronLeft, Check,
  Heart, Brain, Shield, Swords, RotateCcw, Loader2, MessageSquareShare,
} from 'lucide-react'

type Step = 'loading' | string | 'result'

const ICON_MAP: Record<string, typeof Heart> = {
  phq2: Brain,
  gad2: Shield,
  attachment: Heart,
  conflict: Swords,
}
const COLOR_MAP: Record<string, string> = {
  phq2: 'text-violet-500',
  gad2: 'text-amber-500',
  attachment: 'text-rose-500',
  conflict: 'text-sky-500',
}

interface ScaleSection {
  title: string
  description: string
  disclaimer: string
  type?: string
  options?: { value: number; label: string }[]
  items: { id: string; text: string; dimension?: string; mode?: string; label?: string }[]
}

export function AssessmentPage() {
  const [sections, setSections] = useState<Record<string, ScaleSection>>({})
  const [sectionKeys, setSectionKeys] = useState<string[]>([])
  const [step, setStep] = useState<Step>('loading')
  const [answers, setAnswers] = useState<Record<string, number>>({})
  const [conflictChoice, setConflictChoice] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState<AssessmentResult | null>(null)
  const [injectEnabled, setInjectEnabled] = useState(false)
  const [togglingInject, setTogglingInject] = useState(false)

  useEffect(() => {
    let cancelled = false
    async function init() {
      try {
        const [qs, latest] = await Promise.all([
          api.getAssessmentQuestions() as Promise<Record<string, ScaleSection>>,
          api.getLatestAssessment(),
        ])
        if (cancelled) return
        setSections(qs)
        const keys = Object.keys(qs)
        setSectionKeys(keys)

        if (latest.exists && latest.id) {
          setResult(latest as unknown as AssessmentResult)
          setInjectEnabled(!!(latest as unknown as AssessmentResult).inject_enabled)
          setStep('result')
        } else {
          setStep(keys[0] || 'result')
        }
      } catch {
        setStep('result')
      }
    }
    init()
    return () => { cancelled = true }
  }, [])

  const setAnswer = useCallback((id: string, value: number) => {
    setAnswers(prev => ({ ...prev, [id]: value }))
  }, [])

  const allSteps = [...sectionKeys, 'result']
  const stepIdx = allSteps.indexOf(step)
  const currentSection = step !== 'result' && step !== 'loading' ? sections[step] : null
  const isConflict = currentSection?.type === 'single_choice'

  const canNext = (): boolean => {
    if (!currentSection) return false
    if (isConflict) return conflictChoice !== null
    return currentSection.items.every(i => answers[i.id] !== undefined)
  }

  const isLastSection = stepIdx === sectionKeys.length - 1

  const handleNext = async () => {
    if (isLastSection) {
      setSubmitting(true)
      try {
        const res = await api.submitAssessment({
          answers,
          conflict_choice: conflictChoice || undefined,
          inject_enabled: injectEnabled,
        })
        setResult(res)
        setStep('result')
      } catch { /* */ } finally { setSubmitting(false) }
      return
    }
    const nextIdx = stepIdx + 1
    if (nextIdx < allSteps.length) setStep(allSteps[nextIdx])
  }

  const handlePrev = () => {
    if (stepIdx > 0) setStep(allSteps[stepIdx - 1])
  }

  const handleRetake = () => {
    setAnswers({})
    setConflictChoice(null)
    setResult(null)
    setInjectEnabled(false)
    if (sectionKeys.length > 0) setStep(sectionKeys[0])
  }

  const handleToggleInject = async (val: boolean) => {
    setTogglingInject(true)
    try {
      await api.toggleAssessmentInject(val)
      setInjectEnabled(val)
    } catch { /* */ } finally { setTogglingInject(false) }
  }

  if (step === 'loading') {
    return (
      <div className="flex-1 flex items-center justify-center">
        <Loader2 className="w-6 h-6 animate-spin text-emerald-500" />
      </div>
    )
  }

  const renderScaleQuestion = (section: ScaleSection) => (
    <div className="space-y-6">
      {section.items.map(item => (
        <div key={item.id} className="space-y-3">
          <p className="text-sm font-medium text-[var(--text-primary)]">{item.text}</p>
          <div className="flex flex-wrap gap-2">
            {(section.options || []).map(opt => (
              <button key={opt.value} onClick={() => setAnswer(item.id, opt.value)}
                className={`px-4 py-2 rounded-xl text-sm transition-all border ${answers[item.id] === opt.value ? 'border-emerald-500 bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 font-medium shadow-sm' : 'border-[var(--border-color)] text-[var(--text-secondary)] hover:bg-[var(--bg-secondary)]'}`}>
                {opt.label}
              </button>
            ))}
          </div>
        </div>
      ))}
    </div>
  )

  const renderSingleChoice = (section: ScaleSection) => (
    <div className="space-y-3">
      <p className="text-sm text-[var(--text-secondary)] mb-4">{section.description}</p>
      {section.items.map(item => (
        <button key={item.id} onClick={() => setConflictChoice(item.id)}
          className={`w-full text-left px-5 py-4 rounded-xl transition-all border flex items-start gap-3 ${conflictChoice === item.id ? 'border-emerald-500 bg-emerald-500/10 shadow-sm' : 'border-[var(--border-color)] hover:bg-[var(--bg-secondary)]'}`}>
          <div className={`w-5 h-5 rounded-full border-2 flex items-center justify-center mt-0.5 shrink-0 transition-colors ${conflictChoice === item.id ? 'border-emerald-500 bg-emerald-500' : 'border-[var(--border-color)]'}`}>
            {conflictChoice === item.id && <Check className="w-3 h-3 text-white" />}
          </div>
          <div>
            <p className="text-sm font-medium text-[var(--text-primary)]">{item.text}</p>
            {item.label && <p className="text-[11px] text-[var(--text-muted)] mt-0.5">{item.label}</p>}
          </div>
        </button>
      ))}
    </div>
  )

  const renderResult = () => {
    if (!result) return null
    const resultSections = [
      { key: 'phq2', icon: Brain, color: 'violet', title: '抑郁筛查 (PHQ-2)', label: result.phq2.label, score: `${result.phq2.total}/6`, desc: result.phq2.suggestion, level: result.phq2.level },
      { key: 'gad2', icon: Shield, color: 'amber', title: '焦虑筛查 (GAD-2)', label: result.gad2.label, score: `${result.gad2.total}/6`, desc: result.gad2.suggestion, level: result.gad2.level },
      { key: 'att', icon: Heart, color: 'rose', title: '依恋风格', label: result.attachment.label, score: '', desc: result.attachment.description, level: result.attachment.dominant },
      { key: 'conf', icon: Swords, color: 'sky', title: '冲突处理模式', label: result.conflict.label, score: '', desc: result.conflict.description, level: result.conflict.mode },
    ]
    return (
      <div className="space-y-4">
        <div className="text-center mb-4">
          <div className="w-16 h-16 rounded-2xl bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center mx-auto mb-3">
            <Check className="w-8 h-8 text-emerald-500" />
          </div>
          <h3 className="text-lg font-bold text-[var(--text-primary)]">测评完成</h3>
        </div>

        {/* Inject toggle */}
        <div className="rounded-xl border border-[var(--border-color)] bg-[var(--bg-secondary)]/40 px-5 py-4 flex items-center justify-between gap-4">
          <div className="flex items-start gap-3 min-w-0">
            <MessageSquareShare className="w-5 h-5 text-emerald-500 shrink-0 mt-0.5" />
            <div>
              <p className="text-sm font-medium text-[var(--text-primary)]">将测评结果注入对话</p>
              <p className="text-[11px] text-[var(--text-muted)] mt-0.5">开启后，AI 顾问会参考你的筛查和风格信息来调整回复方式。关闭后对话不受测评结果影响。</p>
            </div>
          </div>
          <button type="button" role="switch" aria-checked={injectEnabled}
            disabled={togglingInject}
            onClick={() => handleToggleInject(!injectEnabled)}
            className={`inline-flex h-6 w-11 items-center rounded-full border p-0.5 transition-all shrink-0 ${injectEnabled ? 'border-emerald-500/40 bg-emerald-500/70' : 'border-[var(--border-color)] bg-[var(--bg-card)]'} ${togglingInject ? 'opacity-50' : ''}`}>
            <span className={`h-4 w-4 rounded-full bg-white shadow transition-transform ${injectEnabled ? 'translate-x-5' : 'translate-x-0'}`} />
          </button>
        </div>

        {resultSections.map(s => {
          const SIcon = s.icon
          const isPositive = s.level === 'positive'
          return (
            <div key={s.key} className={`rounded-xl border p-4 ${isPositive ? 'border-amber-500/30 bg-amber-500/5' : 'border-[var(--border-color)] bg-[var(--bg-card)]'}`}>
              <div className="flex items-center gap-2 mb-2">
                <SIcon className={`w-4 h-4 text-${s.color}-500`} />
                <span className="text-sm font-semibold text-[var(--text-primary)]">{s.title}</span>
                <span className={`ml-auto text-xs font-medium px-2 py-0.5 rounded-full ${isPositive ? 'bg-amber-500/20 text-amber-600 dark:text-amber-400' : 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400'}`}>
                  {s.label}{s.score ? ` (${s.score})` : ''}
                </span>
              </div>
              <p className="text-xs text-[var(--text-secondary)] leading-relaxed">{s.desc}</p>
            </div>
          )
        })}
        <button onClick={handleRetake}
          className="w-full flex items-center justify-center gap-2 mt-4 py-3 rounded-xl border border-[var(--border-color)] text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-secondary)] transition-colors">
          <RotateCcw className="w-4 h-4" /> 重新测评
        </button>
      </div>
    )
  }

  const StepIcon = currentSection ? (ICON_MAP[step] || Brain) : Check
  const stepColor = currentSection ? (COLOR_MAP[step] || 'text-violet-500') : 'text-emerald-500'

  return (
    <div className="flex-1 overflow-y-auto scrollbar-fade p-6 md:p-8">
      <div className="max-w-2xl mx-auto space-y-6">
        <div className="rounded-xl border border-amber-500/20 bg-amber-500/5 px-4 py-3 text-[12px] text-[var(--text-secondary)] flex items-start gap-3">
          <Info className="w-4 h-4 shrink-0 text-amber-500 mt-0.5" />
          <span>本测评仅供筛查参考，不构成诊断。筛查阳性建议进一步评估，必要时寻求专业帮助。</span>
        </div>

        {step !== 'result' && sectionKeys.length > 0 && (
          <div className="flex items-center gap-1">
            {sectionKeys.map((s, i) => (
              <div key={s} className={`flex-1 h-1.5 rounded-full transition-colors ${i <= stepIdx ? 'bg-emerald-500' : 'bg-[var(--border-color)]'}`} />
            ))}
          </div>
        )}

        <AnimatePresence mode="wait">
          <motion.div key={step} initial={{ opacity: 0, x: 30 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -30 }} transition={{ duration: 0.2 }}
            className="rounded-2xl border border-[var(--border-color)] bg-[var(--bg-card)] p-6 shadow-sm">
            {currentSection && (
              <>
                <div className="flex items-center gap-3 mb-6">
                  <div className="w-10 h-10 rounded-xl flex items-center justify-center bg-[var(--bg-secondary)] border border-[var(--border-color)]">
                    <StepIcon className={`w-5 h-5 ${stepColor}`} />
                  </div>
                  <div>
                    <h2 className="text-base font-bold text-[var(--text-primary)]">{currentSection.title}</h2>
                    <p className="text-[11px] text-[var(--text-muted)]">第 {stepIdx + 1} / {sectionKeys.length} 步</p>
                  </div>
                </div>
                {!isConflict && (
                  <>
                    <p className="text-sm text-[var(--text-secondary)] mb-5">{currentSection.description}</p>
                    {renderScaleQuestion(currentSection)}
                  </>
                )}
                {isConflict && renderSingleChoice(currentSection)}
              </>
            )}
            {step === 'result' && renderResult()}
          </motion.div>
        </AnimatePresence>

        {step !== 'result' && (
          <div className="flex items-center justify-between">
            <button onClick={handlePrev} disabled={stepIdx === 0}
              className="flex items-center gap-1 px-4 py-2 rounded-xl text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)] disabled:opacity-30 transition-colors">
              <ChevronLeft className="w-4 h-4" /> 上一步
            </button>
            <button onClick={handleNext} disabled={!canNext() || submitting}
              className="flex items-center gap-1 px-5 py-2.5 rounded-xl text-sm font-medium bg-emerald-500 text-white hover:bg-emerald-600 disabled:opacity-50 transition-colors shadow-sm">
              {submitting ? <Loader2 className="w-4 h-4 animate-spin" /> : isLastSection ? <><Check className="w-4 h-4" /> 提交测评</> : <>下一步 <ChevronRight className="w-4 h-4" /></>}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
