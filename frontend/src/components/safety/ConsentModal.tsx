import { useTranslation } from 'react-i18next'
import { ShieldCheck, AlertTriangle, Lock, UserCheck, ClipboardList } from 'lucide-react'
import { useState, useEffect } from 'react'

const CONSENT_KEY = 'lens_consent_accepted'
const ASSESSMENT_PROMPT_KEY = 'lens_assessment_prompted'

const SECTION_META = [
  { icon: AlertTriangle, iconColor: 'text-amber-500', headingKey: 'consent.productPosition', contentKey: 'consent.productPositionContent' },
  { icon: ShieldCheck, iconColor: 'text-blue-500', headingKey: 'consent.aiBoundaries', contentKey: 'consent.aiBoundariesContent' },
  { icon: Lock, iconColor: 'text-emerald-500', headingKey: 'consent.privacy', contentKey: 'consent.privacyContent' },
  { icon: UserCheck, iconColor: 'text-violet-500', headingKey: 'consent.usageCommitment', contentKey: 'consent.usageCommitmentContent' },
]

export function ConsentModal() {
  const { t } = useTranslation()
  const [show, setShow] = useState(() => !localStorage.getItem(CONSENT_KEY))
  const [showAssessmentPrompt, setShowAssessmentPrompt] = useState(false)

  useEffect(() => {
    const accepted = localStorage.getItem(CONSENT_KEY)
    if (accepted) {
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
              <h3 className="font-bold text-[var(--text-primary)]">{t('consentModal.assessmentPrompt.title')}</h3>
              <p className="text-xs text-[var(--text-muted)]">{t('consentModal.assessmentPrompt.subtitle')}</p>
            </div>
          </div>
          <p className="text-sm text-[var(--text-secondary)]">
            {t('consentModal.assessmentPrompt.description')}
          </p>
          <div className="flex gap-3">
            <button onClick={handleSkipAssessment}
              className="flex-1 px-4 py-2.5 rounded-xl border border-[var(--border-color)] text-[var(--text-secondary)] hover:bg-[var(--bg-secondary)] transition-colors text-sm font-medium">
              {t('consentModal.assessmentPrompt.skip')}
            </button>
            <button onClick={handleGoAssessment}
              className="flex-1 px-4 py-2.5 rounded-xl bg-emerald-500 text-white hover:bg-emerald-600 transition-colors text-sm font-medium">
              {t('consentModal.assessmentPrompt.startNow')}
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
          <h2 className="text-xl font-bold text-[var(--text-primary)]">{t('consentModal.modalTitle')}</h2>
          <p className="text-sm text-[var(--text-muted)] mt-1">{t('consentModal.modalSubtitle')}</p>
        </div>

        <div className="p-6 space-y-5">
          {SECTION_META.map((s, i) => {
            const Icon = s.icon
            return (
              <div key={i} className="space-y-2">
                <div className="flex items-center gap-2">
                  <Icon size={18} className={s.iconColor} />
                  <h3 className="font-semibold text-[var(--text-primary)]">{t(s.headingKey)}</h3>
                </div>
                <p className="text-sm text-[var(--text-secondary)] whitespace-pre-line pl-6 leading-relaxed">
                  {t(s.contentKey)}
                </p>
              </div>
            )
          })}
        </div>

        <div className="sticky bottom-0 p-6 pt-4 bg-[var(--bg-card)] border-t border-[var(--border-color)] rounded-b-2xl flex gap-3">
          <button
            onClick={() => window.close()}
            className="flex-1 px-4 py-2.5 rounded-xl border border-[var(--border-color)] text-[var(--text-secondary)] hover:bg-[var(--bg-secondary)] transition-colors text-sm font-medium"
          >
            {t('consentModal.decline')}
          </button>
          <button
            onClick={handleAccept}
            className="flex-1 px-4 py-2.5 rounded-xl bg-emerald-500/90 text-white hover:bg-emerald-600 transition-colors text-sm font-medium"
          >
            {t('consentModal.accept')}
          </button>
        </div>
      </div>
    </div>
  )
}
