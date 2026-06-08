import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface ChatState {
  selectedModelKey: string | null
  setSelectedModelKey: (key: string | null) => void
  useRag: boolean
  setUseRag: (v: boolean) => void
}

export const useChatStore = create<ChatState>()(
  persist(
    (set) => ({
      selectedModelKey: null,
      setSelectedModelKey: (key) => set({ selectedModelKey: key }),
      useRag: true,
      setUseRag: (useRag) => set({ useRag }),
    }),
    { name: 'lens-chat' }
  )
)
