/**
 * §4.6 对话进展分析（专属条目）
 * 时间线展示每轮 Judge 评估
 */
import { useEffect, useState } from 'react'
import { ChevronDown, ChevronRight, BarChart3 } from 'lucide-react'
import { api } from '../../lib/api'
import { format } from 'date-fns'

interface SupervisionLogEntry {
  round: number
  timestamp: string
  judge_backend: string | null
  error?: string
  analysis: {
    dialogue_progress?: { stage?: string; description?: string; stuck?: boolean }
    power_dynamics?: { score?: number; summary?: string }
    empathy_specificity?: { score?: number; reason?: string }
    safety_boundary?: { score?: number; label?: string; notes?: string }
    single_perspective_risk?: { score?: number; is_risk?: boolean; suggestion?: string }
    attachment_signal?: { score?: number; level?: string; notes?: string }
  } | null
}

interface DialogueProgressAnalysisProps {
  sessionId: string | null
  /** 是否默认展开 */
  defaultExpanded?: boolean
}

export function DialogueProgressAnalysis({
  sessionId,
  defaultExpanded = false,
}: DialogueProgressAnalysisProps) {
  const [expanded, setExpanded] = useState(defaultExpanded)
  const [log, setLog] = useState<SupervisionLogEntry[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!sessionId || !expanded) return
    const fetchLog = () => {
      setLoading(true)
      api
        .getSupervisionSession(sessionId)
        .then((res) => setLog(res.supervision_log || []))
        .catch(() => setLog([]))
        .finally(() => setLoading(false))
    }
    fetchLog()
    // 展开后 3s、6s 再拉一次，以便拿到后台刚写完的评估
    const t1 = window.setTimeout(fetchLog, 3000)
    const t2 = window.setTimeout(fetchLog, 6000)
    return () => {
      clearTimeout(t1)
      clearTimeout(t2)
    }
  }, [sessionId, expanded])

  if (!sessionId) return null

  return (
    <div className="rounded-xl border border-[var(--border-color)] bg-[var(--bg-secondary)]/50 overflow-hidden">
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-2 px-4 py-2.5 text-left text-sm hover:bg-[var(--bg-hover)] transition-colors"
      >
        {expanded ? (
          <ChevronDown className="w-4 h-4 text-[var(--text-muted)] shrink-0" />
        ) : (
          <ChevronRight className="w-4 h-4 text-[var(--text-muted)] shrink-0" />
        )}
        <BarChart3 size={16} className="text-violet-500/80 shrink-0" />
        <span className="text-[var(--text-secondary)]">对话进展分析</span>
        {log.length > 0 && (
          <span className="text-xs text-[var(--text-muted)]">({log.length} 轮)</span>
        )}
      </button>

      {expanded && (
        <div className="px-4 pb-4 pt-2 border-t border-[var(--border-color)]/50 space-y-3 max-h-80 overflow-y-auto">
          {loading ? (
            <p className="text-sm text-[var(--text-muted)]">加载中...</p>
          ) : log.length === 0 ? (
            <p className="text-sm text-[var(--text-muted)]">
              暂无评估数据，对话进行中会自动生成。
            </p>
          ) : (
            log.map((entry, idx) => (
              <div
                key={`${entry.round}-${idx}`}
                className="p-3 rounded-lg bg-[var(--bg-card)] border border-[var(--border-color)]/50 text-sm"
              >
                <div className="flex items-center justify-between mb-2">
                  <span className="font-medium text-[var(--text-primary)]">第 {entry.round + 1} 轮</span>
                  <span className="text-xs text-[var(--text-muted)]">
                    {format(new Date(entry.timestamp), 'HH:mm')}
                    {entry.judge_backend ? ` · ${entry.judge_backend}` : ''}
                  </span>
                </div>
                {entry.error === 'judge_unavailable' || !entry.analysis ? (
                  <p className="text-amber-600 text-sm">
                    本轮评估未完成：Judge 服务不可用。请在后端配置 Claude、OpenAI 或 Kimi 的 API Key 后重启服务。
                  </p>
                ) : (
                <div className="space-y-1.5 text-[var(--text-secondary)]">
                  {entry.analysis.dialogue_progress?.stage && (
                    <p>
                      <span className="text-[var(--text-muted)]">阶段：</span>
                      {entry.analysis.dialogue_progress.stage}
                      {entry.analysis.dialogue_progress.description && (
                        <> — {entry.analysis.dialogue_progress.description}</>
                      )}
                    </p>
                  )}
                  {entry.analysis.power_dynamics?.summary && (
                    <p>
                      <span className="text-[var(--text-muted)]">权力动态：</span>
                      {entry.analysis.power_dynamics.summary}
                      {typeof entry.analysis.power_dynamics.score === 'number' && (
                        <span className="ml-1 text-violet-500">
                          ({entry.analysis.power_dynamics.score}/10)
                        </span>
                      )}
                    </p>
                  )}
                  {typeof entry.analysis.empathy_specificity?.score === 'number' && (
                    <p>
                      <span className="text-[var(--text-muted)]">共情与针对性：</span>
                      {entry.analysis.empathy_specificity.reason && (
                        <>{entry.analysis.empathy_specificity.reason}</>
                      )}
                      <span className="ml-1 text-violet-500">
                        ({entry.analysis.empathy_specificity.score}/10)
                      </span>
                    </p>
                  )}
                  {entry.analysis.safety_boundary?.label && (
                    <p>
                      <span className="text-[var(--text-muted)]">安全与边界：</span>
                      {entry.analysis.safety_boundary.label}
                      {typeof entry.analysis.safety_boundary.score === 'number' && (
                        <span className="ml-1">({entry.analysis.safety_boundary.score}/10)</span>
                      )}
                    </p>
                  )}
                  {entry.analysis.single_perspective_risk?.is_risk && (
                    <p className="text-amber-600">
                      建议获取多视角
                    </p>
                  )}
                  {entry.analysis.attachment_signal?.level && entry.analysis.attachment_signal.level !== '低' && (
                    <p>
                      <span className="text-[var(--text-muted)]">情感依赖：</span>
                      {entry.analysis.attachment_signal.level}
                    </p>
                  )}
                </div>
                )}
              </div>
            ))
          )}
        </div>
      )}
    </div>
  )
}
