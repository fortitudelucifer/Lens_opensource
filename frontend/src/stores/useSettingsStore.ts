import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { Locale } from '../i18n/supportedLocales'
import { DEFAULT_LOCALE } from '../i18n/supportedLocales'
import { DEFAULT_UI_MODE, type UiMode } from '../lib/uiMode'

export type Theme = 'light' | 'dark'

interface SettingsState {
  theme: Theme
  setTheme: (theme: Theme) => void
  toggleTheme: () => void
  locale: Locale
  setLocale: (locale: Locale) => void
  lastSelectedModelKey: string | null
  setLastSelectedModelKey: (key: string | null) => void
  // 用户 / 开发者模式（持久化，默认用户模式）
  uiMode: UiMode
  setUiMode: (mode: UiMode) => void
}

export const useSettingsStore = create<SettingsState>()(
  persist(
    (set) => ({
      theme: 'dark',
      setTheme: (theme) => set({ theme }),
      toggleTheme: () =>
        set((s) => ({ theme: s.theme === 'dark' ? 'light' : 'dark' })),
      locale: DEFAULT_LOCALE,
      setLocale: (locale) => set({ locale }),
      lastSelectedModelKey: null,
      setLastSelectedModelKey: (key) => set({ lastSelectedModelKey: key }),
      uiMode: DEFAULT_UI_MODE,
      setUiMode: (uiMode) => set({ uiMode }),
    }),
    { name: 'lens-settings' }
  )
)
