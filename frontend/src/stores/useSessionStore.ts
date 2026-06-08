import { create } from 'zustand'

interface SessionState {
  currentSessionId: string | null
  setCurrentSessionId: (id: string | null) => void
}

export const useSessionStore = create<SessionState>((set) => ({
  currentSessionId: null,
  setCurrentSessionId: (id) => set({ currentSessionId: id }),
}))
