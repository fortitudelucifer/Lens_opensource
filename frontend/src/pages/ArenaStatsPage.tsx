import { useEffect, useState } from 'react'
import { BarChart3, Trophy, Loader2, ArrowLeft } from 'lucide-react'

interface Rating {
  overall: number
  ci_95: [number, number]
  empathy: number
  depth: number
  practicality: number
  professionalism: number
  fluency: number
  battles: number
  wins: number
  losses: number
  ties: number
  contestant?: Record<string, string>
}

interface StatsData {
  updated_at: string | null
  total_battles: number
  ratings: Record<string, Rating>
}

interface SummaryData {
  total: number
  preference: Record<string, number>
}

interface QueryCategory {
  label: string
  battles: number
  models: Record<string, { battles: number; wins: number; win_rate: number }>
}

interface QueryStatsData {
  categories: Record<string, QueryCategory>
  total: number
}

interface AnnotatorData {
  consistency_score: number
  sessions_analyzed: number
  details: Record<string, { rounds: number; avg_diff: number; quality: number; label: string }>
}

const DIMS = ['empathy', 'depth', 'practicality', 'professionalism', 'fluency'] as const
const DIM_LABELS: Record<string, string> = {
  empathy: '共情', depth: '深度', practicality: '实用', professionalism: '专业', fluency: '流畅',
}

// 2026-04-18：前端合并"流派对比"与"视角碰撞"为统一的"视角碰撞"
// 后端 compute_elo_ratings 在 mode=perspective 时会同时包含历史 agent_type 对局
const STATS_MODES = [
  { value: '', label: '全部' },
  { value: 'model', label: '模型对决' },
  { value: 'perspective', label: '视角碰撞' },
] as const

export function ArenaStatsPage({ onBack }: { onBack: () => void }) {
  const [stats, setStats] = useState<StatsData | null>(null)
  const [summary, setSummary] = useState<SummaryData | null>(null)
  const [queryStats, setQueryStats] = useState<QueryStatsData | null>(null)
  const [annotator, setAnnotator] = useState<AnnotatorData | null>(null)
  const [loading, setLoading] = useState(true)
  const [sortKey, setSortKey] = useState<'overall' | typeof DIMS[number]>('overall')
  const [statsMode, setStatsMode] = useState('')

  const fetchStats = (mode: string) => {
    setLoading(true)
    const modeParam = mode ? `?mode=${mode}` : ''
    Promise.all([
      fetch(`/api/arena/stats${modeParam}`).then(r => r.json()),
      fetch('/api/arena/summary').then(r => r.json()),
      fetch('/api/arena/query-stats').then(r => r.json()),
      fetch('/api/arena/annotator-stats').then(r => r.json()),
    ]).then(([s, sm, qs, an]) => {
      setStats(s); setSummary(sm); setQueryStats(qs); setAnnotator(an)
    }).catch(() => {}).finally(() => setLoading(false))
  }

  useEffect(() => { fetchStats(statsMode) }, [statsMode])

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <Loader2 className="w-6 h-6 animate-spin text-emerald-500" />
      </div>
    )
  }

  const ratings = stats?.ratings || {}
  const entries = Object.entries(ratings).sort((a, b) => (b[1][sortKey] || 0) - (a[1][sortKey] || 0))
  const maxPref = summary ? Math.max(...Object.values(summary.preference), 1) : 1

  return (
    <div className="flex-1 overflow-y-auto scrollbar-fade p-6 space-y-6">
      <div className="flex items-center gap-3">
        <button onClick={onBack} className="p-2 rounded-xl text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-secondary)] transition-colors">
          <ArrowLeft className="w-5 h-5" />
        </button>
        <div>
          <h1 className="text-xl font-bold text-[var(--text-primary)] flex items-center gap-2">
            <BarChart3 className="w-5 h-5 text-emerald-500" /> Elo 排名
          </h1>
          <p className="text-xs text-[var(--text-muted)]">
            {stats?.total_battles || 0} 场对局 · {stats?.updated_at ? `更新于 ${new Date(stats.updated_at).toLocaleString('zh-CN')}` : '暂无数据'}
          </p>
        </div>
      </div>

      {/* Mode Tabs */}
      <div className="flex items-center gap-2">
        {STATS_MODES.map(m => (
          <button key={m.value} onClick={() => setStatsMode(m.value)}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${statsMode === m.value ? 'bg-emerald-500/20 text-emerald-600 dark:text-emerald-400 border border-emerald-500/30' : 'border border-[var(--border-color)] text-[var(--text-secondary)] hover:bg-[var(--bg-secondary)]'}`}>
            {m.label}
          </button>
        ))}
      </div>

      {entries.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-[var(--border-color)] bg-[var(--bg-card)]/70 p-12 text-center">
          <Trophy className="w-10 h-10 text-[var(--text-muted)] mx-auto mb-3" />
          <p className="text-[var(--text-muted)]">暂无排名数据，至少需要完成 1 场对局打分</p>
        </div>
      ) : (
        <>
          {/* Sort Tabs */}
          <div className="flex flex-wrap gap-2">
            {['overall', ...DIMS].map(k => (
              <button key={k} onClick={() => setSortKey(k as typeof sortKey)}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${sortKey === k ? 'bg-emerald-500/20 text-emerald-600 dark:text-emerald-400 border border-emerald-500/30' : 'border border-[var(--border-color)] text-[var(--text-secondary)] hover:bg-[var(--bg-secondary)]'}`}>
                {k === 'overall' ? '总分' : DIM_LABELS[k] || k}
              </button>
            ))}
          </div>

          {/* Leaderboard */}
          <div className="rounded-2xl border border-[var(--border-color)] bg-[var(--bg-card)] overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-[var(--bg-secondary)]/60">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-semibold text-[var(--text-muted)]">#</th>
                  <th className="px-4 py-3 text-left text-xs font-semibold text-[var(--text-muted)]">模型</th>
                  <th className="px-4 py-3 text-center text-xs font-semibold text-[var(--text-muted)]">Elo</th>
                  <th className="px-4 py-3 text-center text-xs font-semibold text-[var(--text-muted)]">95% CI</th>
                  {DIMS.map(d => (
                    <th key={d} className="px-3 py-3 text-center text-xs font-semibold text-[var(--text-muted)] hidden lg:table-cell">{DIM_LABELS[d]}</th>
                  ))}
                  <th className="px-4 py-3 text-center text-xs font-semibold text-[var(--text-muted)]">胜/负/平</th>
                </tr>
              </thead>
              <tbody>
                {entries.map(([key, r], idx) => {
                  const name = r.contestant?.model?.split('/').pop() || r.contestant?.backend || key
                  const isCold = r.battles < 10
                  return (
                    <tr key={key} className="border-t border-[var(--border-color)] hover:bg-[var(--bg-secondary)]/30 transition-colors">
                      <td className="px-4 py-3 font-bold text-[var(--text-muted)]">{idx + 1}</td>
                      <td className="px-4 py-3">
                        <span className="font-medium text-[var(--text-primary)]">{name}</span>
                        {isCold && <span className="ml-2 text-[10px] text-amber-500">未排名</span>}
                      </td>
                      <td className="px-4 py-3 text-center font-bold text-emerald-600 dark:text-emerald-400">{r.overall}</td>
                      <td className="px-4 py-3 text-center text-xs text-[var(--text-muted)]">{r.ci_95[0]}–{r.ci_95[1]}</td>
                      {DIMS.map(d => (
                        <td key={d} className="px-3 py-3 text-center text-xs text-[var(--text-secondary)] hidden lg:table-cell">{r[d]}</td>
                      ))}
                      <td className="px-4 py-3 text-center text-xs text-[var(--text-secondary)]">{r.wins}/{r.losses}/{r.ties}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          {/* Preference Summary */}
          {summary && summary.total > 0 && (
            <div className="rounded-2xl border border-[var(--border-color)] bg-[var(--bg-card)] p-6">
              <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-3">偏好统计</h3>
              <p className="text-xs text-[var(--text-muted)] mb-4">在 {summary.total} 轮对局中：</p>
              <div className="space-y-2">
                {Object.entries(summary.preference).sort((a, b) => b[1] - a[1]).map(([model, count]) => (
                  <div key={model} className="flex items-center gap-3">
                    <span className="w-32 text-xs text-[var(--text-secondary)] truncate">{model.split('/').pop()}</span>
                    <div className="flex-1 h-5 rounded-full bg-[var(--bg-secondary)] overflow-hidden">
                      <div className="h-full rounded-full bg-gradient-to-r from-emerald-500 to-teal-500 transition-all"
                        style={{ width: `${(count / maxPref) * 100}%` }} />
                    </div>
                    <span className="text-xs font-medium text-[var(--text-primary)] w-16 text-right">{count} 次 ({Math.round(count / summary.total * 100)}%)</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          {/* Query Stratification */}
          {queryStats && Object.keys(queryStats.categories).length > 0 && (
            <div className="rounded-2xl border border-[var(--border-color)] bg-[var(--bg-card)] p-6">
              <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-1">Query 分层统计</h3>
              <p className="text-xs text-[var(--text-muted)] mb-4">按问题类型统计各模型胜率，帮助发现薄弱场景</p>
              <div className="space-y-4">
                {Object.entries(queryStats.categories).map(([cat, data]) => (
                  <div key={cat} className="rounded-xl border border-[var(--border-color)] p-4">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-xs font-semibold text-[var(--text-primary)]">{data.label}</span>
                      <span className="text-[10px] text-[var(--text-muted)]">{data.battles} 场</span>
                    </div>
                    <div className="space-y-1.5">
                      {Object.entries(data.models).map(([model, m]) => (
                        <div key={model} className="flex items-center gap-2">
                          <span className="w-28 text-[11px] text-[var(--text-secondary)] truncate">{model.split('/').pop()}</span>
                          <div className="flex-1 h-4 rounded-full bg-[var(--bg-secondary)] overflow-hidden">
                            <div className="h-full rounded-full bg-gradient-to-r from-emerald-500 to-teal-500"
                              style={{ width: `${m.win_rate}%` }} />
                          </div>
                          <span className="text-[11px] font-medium text-[var(--text-primary)] w-12 text-right">{m.win_rate}%</span>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Annotator Consistency */}
          {annotator && annotator.sessions_analyzed > 0 && (
            <div className="rounded-2xl border border-[var(--border-color)] bg-[var(--bg-card)] p-6">
              <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-1">标注质量分析 (am-ELO)</h3>
              <p className="text-xs text-[var(--text-muted)] mb-4">
                评估打分一致性：全维度相同评分、极端差异等会降低质量分
              </p>
              <div className="flex items-center gap-4 mb-4">
                <div className="text-center">
                  <div className={`text-2xl font-bold ${annotator.consistency_score >= 0.8 ? 'text-emerald-500' : annotator.consistency_score >= 0.5 ? 'text-amber-500' : 'text-red-500'}`}>
                    {(annotator.consistency_score * 100).toFixed(0)}%
                  </div>
                  <div className="text-[10px] text-[var(--text-muted)]">整体一致性</div>
                </div>
                <div className="text-center">
                  <div className="text-lg font-semibold text-[var(--text-primary)]">{annotator.sessions_analyzed}</div>
                  <div className="text-[10px] text-[var(--text-muted)]">分析会话数</div>
                </div>
              </div>
              <div className="space-y-1.5">
                {Object.entries(annotator.details).map(([sid, d]) => (
                  <div key={sid} className="flex items-center gap-3 text-xs">
                    <span className="w-28 text-[var(--text-muted)] truncate">{sid}</span>
                    <span className="text-[var(--text-secondary)]">{d.rounds} 轮</span>
                    <div className="flex-1 h-3 rounded-full bg-[var(--bg-secondary)] overflow-hidden">
                      <div className={`h-full rounded-full ${d.quality >= 0.8 ? 'bg-emerald-500' : d.quality >= 0.5 ? 'bg-amber-500' : 'bg-red-500'}`}
                        style={{ width: `${d.quality * 100}%` }} />
                    </div>
                    <span className="text-[10px] text-[var(--text-muted)] w-40 text-right truncate">{d.label}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
