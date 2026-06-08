import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export type Theme = 'light' | 'dark'

interface SettingsState {
  theme: Theme
  setTheme: (theme: Theme) => void
  toggleTheme: () => void
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
      lastSelectedModelKey: null,
      setLastSelectedModelKey: (key) => set({ lastSelectedModelKey: key }),
    }),
    { name: 'lens-settings' }
  )
)
