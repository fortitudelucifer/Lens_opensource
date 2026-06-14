import { useTranslation } from 'react-i18next'
import { ShieldCheck, AlertTriangle, Lock, UserCheck, CheckCircle2 } from 'lucide-react'

const SECTION_META = [
  { icon: AlertTriangle, iconColor: 'text-amber-500', headingKey: 'consent.productPosition', contentKey: 'consent.productPositionContent' },
  { icon: ShieldCheck, iconColor: 'text-blue-500', headingKey: 'consent.aiBoundaries', contentKey: 'consent.aiBoundariesContent' },
  { icon: Lock, iconColor: 'text-emerald-500', headingKey: 'consent.privacy', contentKey: 'consent.privacyContent' },
  { icon: UserCheck, iconColor: 'text-violet-500', headingKey: 'consent.usageCommitment', contentKey: 'consent.usageCommitmentContent' },
]

export function ConsentPage() {
  const { t } = useTranslation()
  return (
    <div className="flex-1 overflow-y-auto w-full p-6 sm:p-10" style={{ background: 'var(--bg-primary)' }}>
      <div className="max-w-4xl mx-auto space-y-8">

        {/* Header */}
        <div className="flex flex-col sm:flex-row items-start sm:items-center gap-5 border-b pb-6" style={{ borderColor: 'var(--border-color)' }}>
          <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-emerald-500/20 to-teal-500/20 border border-[var(--border-color)] flex items-center justify-center shrink-0 shadow-sm">
            <ShieldCheck className="w-7 h-7 text-emerald-500 drop-shadow-sm" />
          </div>
          <div>
            <h1 className="text-2xl font-bold tracking-tight" style={{ color: 'var(--text-primary)' }}>{t('consent.title')}</h1>
            <p className="text-sm mt-1.5" style={{ color: 'var(--text-muted)' }}>{t('app.name')} — {t('app.tagline')}</p>
          </div>
        </div>

        {/* Content Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {SECTION_META.map((s, i) => {
            const bgClass = s.iconColor.replace('text-', 'bg-').concat('/10')
            const Icon = s.icon
            return (
              <div key={i} className="p-6 rounded-2xl border transition-shadow hover:shadow-md" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
                <div className="flex items-center gap-3 mb-4">
                  <div className={`p-2.5 rounded-xl ${bgClass} border`} style={{ borderColor: 'var(--border-color)' }}>
                     <Icon className={`w-5 h-5 ${s.iconColor}`} />
                  </div>
                  <h3 className="text-lg font-bold" style={{ color: 'var(--text-primary)' }}>{t(s.headingKey)}</h3>
                </div>
                <p className="text-sm leading-relaxed whitespace-pre-line" style={{ color: 'var(--text-secondary)' }}>
                  {t(s.contentKey)}
                </p>
              </div>
            )
          })}
        </div>

        {/* Status Box */}
        <div className="mt-8 p-6 rounded-2xl border shadow-sm" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <div className="flex items-start gap-4">
            <CheckCircle2 className="w-6 h-6 text-emerald-500 shrink-0 mt-0.5" />
            <div>
              <h4 className="text-base font-semibold mb-2" style={{ color: 'var(--text-primary)' }}>{t('consent.userStatus')}</h4>
              <p className="text-sm leading-relaxed mb-3" style={{ color: 'var(--text-secondary)' }}>
                {t('consent.userStatusContent')}
              </p>
              <div className="flex items-center gap-2">
                <span className="text-xs" style={{ color: 'var(--text-muted)' }}>{t('consent.localStorageStatus')}</span>
                <code className="text-xs px-2 py-1 rounded-md font-mono border" style={{ background: 'var(--bg-secondary)', borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}>
                  lens_consent_accepted = true
                </code>
              </div>
            </div>
          </div>
        </div>

      </div>
    </div>
  )
}
