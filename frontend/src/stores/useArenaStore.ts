import { create } from 'zustand'

/** 五维评分（1-10） */
export interface ArenaScores {
  empathy: number
  depth: number
  practicality: number
  professionalism: number
  fluency: number
}

export type ArenaVote = 'a_win' | 'b_win' | 'tie' | 'both_good' | 'both_bad'

// 2026-04-18：前端仅暴露两种对比模式 —— 模型对决 / 视角碰撞（流派+视角合并）
// 'agent_type' 保留为类型联合以兼容历史会话 JSON 中的老字段
export type ArenaMode = 'model' | 'perspective' | 'agent_type'

interface ArenaState {
  query: string
  setQuery: (q: string) => void
  mode: ArenaMode
  setMode: (m: ArenaMode) => void
  battleId: string | null
  contestantA: { backend: string; agent_type?: string; model?: string } | null
  contestantB: { backend: string; agent_type?: string; model?: string } | null
  useRag: boolean
  responseA: string
  responseB: string
  setResponseA: (s: string) => void
  setResponseB: (s: string) => void
  setBattle: (p: {
    battleId: string
    contestantA: Record<string, string>
    contestantB: Record<string, string>
    mode: string
    useRag: boolean
  }) => void
  vote: ArenaVote | null
  scoresA: ArenaScores | null
  scoresB: ArenaScores | null
  setVote: (v: ArenaVote | null) => void
  setScoresA: (s: ArenaScores | null) => void
  setScoresB: (s: ArenaScores | null) => void
  revealed: boolean
  setRevealed: (v: boolean) => void
  reset: () => void
}

export const defaultArenaScores = (): ArenaScores => ({
  empathy: 5,
  depth: 5,
  practicality: 5,
  professionalism: 5,
  fluency: 5,
})

export const useArenaStore = create<ArenaState>((set) => ({
  query: '',
  setQuery: (query) => set({ query }),
  mode: 'model',
  setMode: (mode) => set({ mode }),
  battleId: null,
  contestantA: null,
  contestantB: null,
  useRag: true,
  responseA: '',
  responseB: '',
  setResponseA: (responseA) => set({ responseA }),
  setResponseB: (responseB) => set({ responseB }),
  setBattle: (p) =>
    set({
      battleId: p.battleId,
      contestantA: {
        backend: (p.contestantA as Record<string, string>).backend ?? 'deepseek',
        agent_type: (p.contestantA as Record<string, string>).agent_type,
        model: (p.contestantA as Record<string, string>).model,
      },
      contestantB: {
        backend: (p.contestantB as Record<string, string>).backend ?? 'deepseek',
        agent_type: (p.contestantB as Record<string, string>).agent_type,
        model: (p.contestantB as Record<string, string>).model,
      },
      mode: p.mode as ArenaMode,
      useRag: p.useRag,
    }),
  vote: null,
  scoresA: null,
  scoresB: null,
  setVote: (vote) => set({ vote }),
  setScoresA: (scoresA) => set({ scoresA }),
  setScoresB: (scoresB) => set({ scoresB }),
  revealed: false,
  setRevealed: (revealed) => set({ revealed }),
  reset: () =>
    set({
      battleId: null,
      contestantA: null,
      contestantB: null,
      responseA: '',
      responseB: '',
      vote: null,
      scoresA: null,
      scoresB: null,
      revealed: false,
    }),
}))
