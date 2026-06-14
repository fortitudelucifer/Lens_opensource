import { useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { Globe } from 'lucide-react'
import { useSettingsStore } from '../../stores/useSettingsStore'
import { SUPPORTED_LOCALES, LOCALE_LABELS, type Locale } from '../../i18n/supportedLocales'

export function LanguageSwitcher() {
  const { i18n } = useTranslation()
  const locale = useSettingsStore((s) => s.locale)
  const setLocale = useSettingsStore((s) => s.setLocale)

  const handleChange = useCallback(
    (next: Locale) => {
      i18n.changeLanguage(next)
      setLocale(next)
      document.documentElement.lang = next
    },
    [i18n, setLocale]
  )

  return (
    <div className="flex items-center justify-between px-4 py-3 rounded-xl hover:bg-[var(--bg-secondary)] transition-colors text-[var(--text-secondary)] hover:text-[var(--text-primary)]">
      <div className="flex items-center gap-2">
        <Globe className="w-4 h-4" />
        <span className="font-medium">{LOCALE_LABELS[locale]}</span>
      </div>
      <div className="flex items-center gap-1">
        {SUPPORTED_LOCALES.map((loc) => (
          <button
            key={loc}
            onClick={() => handleChange(loc)}
            className={`px-2 py-1 rounded-md text-xs font-medium transition-colors ${
              locale === loc
                ? 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-300'
                : 'text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-secondary)]'
            }`}
            aria-label={`Switch to ${LOCALE_LABELS[loc]}`}
          >
            {loc}
          </button>
        ))}
      </div>
    </div>
  )
}
