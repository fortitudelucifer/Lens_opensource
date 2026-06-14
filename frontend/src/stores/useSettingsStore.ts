import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { Locale } from '../i18n/supportedLocales'
import { DEFAULT_LOCALE } from '../i18n/supportedLocales'

export type Theme = 'light' | 'dark'

interface SettingsState {
  theme: Theme
  setTheme: (theme: Theme) => void
  toggleTheme: () => void
  locale: Locale
  setLocale: (locale: Locale) => void
  lastSelectedModelKey: string | null
  setLastSelectedModelKey: (key: string | null) => void
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
    }),
    { name: 'lens-settings' }
  )
)
