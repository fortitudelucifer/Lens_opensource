import { useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { UserRound, Wrench } from 'lucide-react'
import { useSettingsStore } from '../../stores/useSettingsStore'
import type { UiMode } from '../../lib/uiMode'

const MODES: { id: UiMode; icon: typeof UserRound; labelKey: string }[] = [
  { id: 'user', icon: UserRound, labelKey: 'mode.user' },
  { id: 'developer', icon: Wrench, labelKey: 'mode.developer' },
]

// 用户 / 开发者 模式切换 —— 交互对标 LanguageSwitcher（小开关 + 持久化）。
// 开发者模式才显示运维台（流水线/模型/API Key/训练数据）。
export function ModeSwitcher() {
  const { t } = useTranslation()
  const uiMode = useSettingsStore((s) => s.uiMode)
  const setUiMode = useSettingsStore((s) => s.setUiMode)

  const handleChange = useCallback((next: UiMode) => setUiMode(next), [setUiMode])
  const ActiveIcon = uiMode === 'developer' ? Wrench : UserRound

  return (
    <div className="flex items-center justify-between px-4 py-3 rounded-xl hover:bg-[var(--bg-secondary)] transition-colors text-[var(--text-secondary)] hover:text-[var(--text-primary)]">
      <div className="flex items-center gap-2">
        <ActiveIcon className="w-4 h-4" />
        <span className="font-medium">{t('mode.label')}</span>
      </div>
      <div className="flex items-center gap-1">
        {MODES.map(({ id, icon: Icon, labelKey }) => (
          <button
            key={id}
            onClick={() => handleChange(id)}
            className={`flex items-center gap-1 px-2 py-1 rounded-md text-xs font-medium transition-colors ${
              uiMode === id
                ? 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-300'
                : 'text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-secondary)]'
            }`}
            aria-label={t('mode.switchTo', { mode: t(labelKey) })}
            title={t('mode.switchTo', { mode: t(labelKey) })}
          >
            <Icon className="w-3 h-3" />
            {t(labelKey)}
          </button>
        ))}
      </div>
    </div>
  )
}
