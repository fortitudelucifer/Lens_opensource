import { ShieldCheck, AlertTriangle, Lock, UserCheck, ClipboardList } from 'lucide-react'
import { useState, useEffect } from 'react'

const CONSENT_KEY = 'lens_consent_accepted'
const ASSESSMENT_PROMPT_KEY = 'lens_assessment_prompted'

const SECTIONS = [
  {
    icon: AlertTriangle,
    iconColor: 'text-amber-500',
    heading: '产品定位声明',
    content:
      'Lens 是一款基于人工智能的关系模式分析与情感支持工具。\n\n' +
      '⚠️ 本工具不是医疗器械，不提供任何形式的心理诊断、治疗或处方建议。\n' +
      '⚠️ 如果您正在经历严重的心理困扰，请寻求持证心理咨询师或精神科医生的帮助。',
  },
  {
    icon: ShieldCheck,
    iconColor: 'text-blue-500',
    heading: 'AI 能力边界',
    content:
      '· AI 的分析基于有限的文本信息，无法替代面对面的专业评估\n' +
      '· AI 可能产生不准确或不恰当的回应，请以您自身判断为准\n' +
      '· 所有建议均不构成专业心理咨询意见',
  },
  {
    icon: Lock,
    iconColor: 'text-emerald-500',
    heading: '隐私保护',
    content:
      '· 您的对话内容仅保存在本地设备，不会上传到任何服务器\n' +
      '· 您可以随时删除所有对话记录\n' +
      '· 匿名化处理确保原始聊天记录中的真实身份信息不会泄露',
  },
  {
    icon: UserCheck,
    iconColor: 'text-violet-500',
    heading: '使用承诺',
    content:
      '继续使用即表示您：\n' +
      '✓ 理解本工具的非医疗定位\n' +
      '✓ 理解 AI 分析仅供参考，不替代专业服务\n' +
      '✓ 同意在遇到紧急心理危机时拨打专业热线\n' +
      '✓ 年满 18 周岁（或已获监护人同意）',
  },
]

export function ConsentModal() {
  const [show, setShow] = useState(false)
  const [showAssessmentPrompt, setShowAssessmentPrompt] = useState(false)

  useEffect(() => {
    const accepted = localStorage.getItem(CONSENT_KEY)
    if (!accepted) {
      setShow(true)
    } else {
      const prompted = localStorage.getItem(ASSESSMENT_PROMPT_KEY)
      if (!prompted) {
        fetch('/api/assessment/latest')
          .then(r => r.json())
          .then(d => { if (!d.exists) setShowAssessmentPrompt(true) })
          .catch(() => {})
      }
    }
  }, [])

  const handleAccept = () => {
    localStorage.setItem(CONSENT_KEY, new Date().toISOString())
    setShow(false)
    fetch('/api/assessment/latest')
      .then(r => r.json())
      .then(d => { if (!d.exists) setShowAssessmentPrompt(true) })
      .catch(() => {})
  }

  const handleGoAssessment = () => {
    localStorage.setItem(ASSESSMENT_PROMPT_KEY, 'true')
    setShowAssessmentPrompt(false)
    window.history.pushState(null, '', '/assessment')
    window.dispatchEvent(new PopStateEvent('popstate'))
  }

  const handleSkipAssessment = () => {
    localStorage.setItem(ASSESSMENT_PROMPT_KEY, 'true')
    setShowAssessmentPrompt(false)
  }

  if (showAssessmentPrompt) {
    return (
      <div className="fixed inset-0 z-[200] flex items-center justify-center bg-black/50 backdrop-blur-sm">
        <div className="mx-4 max-w-md w-full rounded-2xl bg-[var(--bg-card)] border border-[var(--border-color)] shadow-2xl p-6 space-y-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center">
              <ClipboardList className="w-5 h-5 text-emerald-500" />
            </div>
            <div>
              <h3 className="font-bold text-[var(--text-primary)]">建议先完成交流测评</h3>
              <p className="text-xs text-[var(--text-muted)]">约 1 分钟，帮助 AI 更好地理解你</p>
            </div>
          </div>
          <p className="text-sm text-[var(--text-secondary)]">
            完成简短的 PHQ-2 + GAD-2 筛查与依恋/冲突模式自评后，AI 顾问将根据你的特点调整回复风格。你可以随时跳过或稍后完成。
          </p>
          <div className="flex gap-3">
            <button onClick={handleSkipAssessment}
              className="flex-1 px-4 py-2.5 rounded-xl border border-[var(--border-color)] text-[var(--text-secondary)] hover:bg-[var(--bg-secondary)] transition-colors text-sm font-medium">
              稍后再说
            </button>
            <button onClick={handleGoAssessment}
              className="flex-1 px-4 py-2.5 rounded-xl bg-emerald-500 text-white hover:bg-emerald-600 transition-colors text-sm font-medium">
              立即测评
            </button>
          </div>
        </div>
      </div>
    )
  }

  if (!show) return null

  return (
    <div className="fixed inset-0 z-[200] flex items-center justify-center bg-black/70 backdrop-blur-md">
      <div className="mx-4 max-w-lg w-full max-h-[90vh] overflow-y-auto scrollbar-thin rounded-2xl bg-[var(--bg-card)] border border-[var(--border-color)] shadow-2xl">
        <div className="sticky top-0 p-6 pb-4 bg-[var(--bg-card)] border-b border-[var(--border-color)] rounded-t-2xl">
          <h2 className="text-xl font-bold text-[var(--text-primary)]">使用须知与知情同意</h2>
          <p className="text-sm text-[var(--text-muted)] mt-1">请仔细阅读以下内容后再继续使用</p>
        </div>

        <div className="p-6 space-y-5">
          {SECTIONS.map((s, i) => (
            <div key={i} className="space-y-2">
              <div className="flex items-center gap-2">
                <s.icon size={18} className={s.iconColor} />
                <h3 className="font-semibold text-[var(--text-primary)]">{s.heading}</h3>
              </div>
              <p className="text-sm text-[var(--text-secondary)] whitespace-pre-line pl-6 leading-relaxed">
                {s.content}
              </p>
            </div>
          ))}
        </div>

        <div className="sticky bottom-0 p-6 pt-4 bg-[var(--bg-card)] border-t border-[var(--border-color)] rounded-b-2xl flex gap-3">
          <button
            onClick={() => window.close()}
            className="flex-1 px-4 py-2.5 rounded-xl border border-[var(--border-color)] text-[var(--text-secondary)] hover:bg-[var(--bg-secondary)] transition-colors text-sm font-medium"
          >
            暂不使用
          </button>
          <button
            onClick={handleAccept}
            className="flex-1 px-4 py-2.5 rounded-xl bg-emerald-500/90 text-white hover:bg-emerald-600 transition-colors text-sm font-medium"
          >
            我已阅读并理解上述内容
          </button>
        </div>
      </div>
    </div>
  )
}
