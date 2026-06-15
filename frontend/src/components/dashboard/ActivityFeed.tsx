import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { motion } from 'framer-motion'
import { MessageSquare, CheckCircle, AlertTriangle, RefreshCw, Star, UserPlus } from 'lucide-react'
import { api } from '@/lib/api'

interface Activity {
  id: number
  type: 'message' | 'review' | 'alert' | 'update' | 'rating' | 'user'
  user: string
  initials: string
  avatarColor: string
  description: string
  time: string
  badge?: {
    label: string
    color: string
    bg: string
  }
}

const SAMPLE_ACTIVITIES: Activity[] = [
  {
    id: 1,
    type: 'message',
    user: 'User_412',
    initials: '412',
    avatarColor: 'linear-gradient(135deg,#10b981,#14b8a6)',
    description: '完成了一次深度情感互动对话，共 18 轮交互',
    time: '2 分钟前',
    badge: {
      label: '已完成',
      color: '#22c55e',
      bg: 'rgba(34,197,94,0.12)',
    },
  },
  {
    id: 2,
    type: 'review',
    user: 'System',
    initials: 'SYS',
    avatarColor: 'linear-gradient(135deg,#3b82f6,#8b5cf6)',
    description: '检测到大段多模态记录上传，触发 Kimi 专家分析',
    time: '8 分钟前',
    badge: {
      label: '多模态',
      color: '#8b5cf6',
      bg: 'rgba(139,92,246,0.12)',
    },
  },
  {
    id: 3,
    type: 'rating',
    user: 'User_89',
    initials: '089',
    avatarColor: 'linear-gradient(135deg,#14b8a6,#0ea5e9)',
    description: '对话质量评分：满意 (Thumbs Up)',
    time: '15 分钟前',
    badge: {
      label: '👍 满意',
      color: '#f59e0b',
      bg: 'rgba(245,158,11,0.12)',
    },
  },
  {
    id: 4,
    type: 'alert',
    user: 'SafetyLayer',
    initials: 'SFT',
    avatarColor: 'linear-gradient(135deg,#ef4444,#dc2626)',
    description: '拦截了一次潜在的 PII 泄露风险',
    time: '23 分钟前',
    badge: {
      label: '已拦截',
      color: '#ef4444',
      bg: 'rgba(239,68,68,0.12)',
    },
  },
  {
    id: 5,
    type: 'update',
    user: 'RAG Indexer',
    initials: 'IDX',
    avatarColor: 'linear-gradient(135deg,#22c55e,#16a34a)',
    description: '增量更新了 45 条记忆节点和索引向量',
    time: '41 分钟前',
    badge: {
      label: '已同步',
      color: '#22c55e',
      bg: 'rgba(34,197,94,0.12)',
    },
  },
]

const typeIcons = {
  message: MessageSquare,
  review: CheckCircle,
  alert: AlertTriangle,
  update: RefreshCw,
  rating: Star,
  user: UserPlus,
}

export function ActivityFeed() {
  const { t } = useTranslation()
  const [activities, setActivities] = useState<Activity[]>(SAMPLE_ACTIVITIES)

  useEffect(() => {
    let mounted = true

    const timeAgo = (iso: string) => {
      const diffMs = Date.now() - new Date(iso).getTime()
      const mins = Math.max(1, Math.floor(diffMs / 60000))
      if (mins < 60) return t('time.minutesAgo', { count: mins })
      const hours = Math.floor(mins / 60)
      if (hours < 24) return t('time.hoursAgo', { count: hours })
      return t('time.daysAgo', { count: Math.floor(hours / 24) })
    }

    const load = async () => {
      try {
        const [sessions, pipeline, review] = await Promise.all([
          api.listSessions().catch(() => []),
          api.getPipelineStatus().catch(() => null),
          api.getReviewItems().catch(() => null),
        ])

        const live: Activity[] = []

        sessions
          .slice()
          .sort((a, b) => +new Date(b.updated_at) - +new Date(a.updated_at))
          .slice(0, 3)
          .forEach((s, idx) => {
            live.push({
              id: idx + 1,
              type: 'message',
              user: `Session ${s.id.slice(0, 6)}`,
              initials: 'CHT',
              avatarColor: 'linear-gradient(135deg,#10b981,#14b8a6)',
              description: `${s.title || t('chat.unnamedSession')} · ${s.message_count} ${t('dashboard.messages')} · ${s.backend}`,
              time: timeAgo(s.updated_at),
              badge: {
                label: s.mode === 'consult' ? t('chat.modeDeep') : t('chat.modeListen'),
                color: '#059669',
                bg: 'rgba(16,185,129,0.12)',
              },
            })
          })

        if (pipeline?.phases) {
          Object.values(pipeline.phases)
            .filter((p) => p.status === 'running' || p.status === 'error')
            .forEach((p, idx) => {
              live.push({
                id: 100 + idx,
                type: p.status === 'error' ? 'alert' : 'update',
                user: 'Pipeline',
                initials: p.status === 'error' ? 'ERR' : 'RUN',
                avatarColor:
                  p.status === 'error'
                    ? 'linear-gradient(135deg,#ef4444,#dc2626)'
                    : 'linear-gradient(135deg,#14b8a6,#0ea5e9)',
                description: `${p.name} · ${p.detail || t('dashboard.processing')}`,
                time: t('common.justNow'),
                badge: {
                  label: p.status === 'error' ? t('common.error') : t('dashboard.inProgress'),
                  color: p.status === 'error' ? '#dc2626' : '#0891b2',
                  bg: p.status === 'error' ? 'rgba(239,68,68,0.12)' : 'rgba(14,165,233,0.12)',
                },
              })
            })
        }

        if (review?.stats) {
          live.push({
            id: 200,
            type: 'review',
            user: 'Review Queue',
            initials: 'REV',
            avatarColor: 'linear-gradient(135deg,#3b82f6,#8b5cf6)',
            description: t('dashboard.reviewStats', { pending: review.stats.pending, aiPassed: review.stats.ai_passed }),
            time: t('common.justNow'),
            badge: {
              label: t('dashboard.reviewStatus'),
              color: '#6366f1',
              bg: 'rgba(99,102,241,0.12)',
            },
          })
        }

        if (!mounted) return
        setActivities(live.length > 0 ? live.slice(0, 8) : SAMPLE_ACTIVITIES)
      } catch {
        if (mounted) setActivities(SAMPLE_ACTIVITIES)
      }
    }

    load()
    const timer = window.setInterval(load, 15000)
    return () => {
      mounted = false
      window.clearInterval(timer)
    }
  }, [])

  const rendered = useMemo(() => activities, [activities])

  return (
    <motion.div
      initial={{ opacity: 0, y: 24 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, delay: 0.6 }}
      className="glass-card rounded-2xl p-6"
    >
      <div className="flex items-center justify-between mb-5">
        <div>
          <h2 className="text-base font-bold mb-1 text-[var(--text-primary)]">
            {t('dashboard.activityFeed')}
          </h2>
          <p className="text-xs text-[var(--text-muted)]">
            {t('dashboard.activityFeedDesc')}
          </p>
        </div>
        <button
          className="text-xs font-medium px-3 py-1.5 rounded-xl transition-all hover:scale-105 bg-[var(--bg-secondary)] text-[var(--text-secondary)] border border-[var(--border-color)]"
        >
          {t('dashboard.viewAll')}
        </button>
      </div>

      <div className="space-y-2">
        {rendered.map((activity, i) => {
          const TypeIcon = typeIcons[activity.type]
          
          return (
            <motion.div
              key={activity.id}
              initial={{ opacity: 0, x: -12 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: 0.7 + i * 0.07 }}
              className="group flex items-start gap-3 p-3 rounded-xl cursor-pointer transition-all duration-200 hover:bg-[var(--bg-secondary)] hover:scale-[1.01]"
            >
              <div
                className="w-10 h-10 rounded-xl flex items-center justify-center text-white text-xs font-bold flex-shrink-0 shadow-md"
                style={{ background: activity.avatarColor }}
              >
                {activity.initials}
              </div>

              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-sm font-semibold text-[var(--text-primary)] group-hover:text-emerald-600 transition-colors">
                    {activity.user}
                  </span>
                  {activity.badge && (
                    <span
                      className="text-[10px] font-bold px-2 py-0.5 rounded-full uppercase tracking-wider"
                      style={{ background: activity.badge.bg, color: activity.badge.color }}
                    >
                      {activity.badge.label}
                    </span>
                  )}
                </div>
                <p className="text-xs leading-relaxed text-[var(--text-secondary)]">
                  {activity.description}
                </p>
                <div className="flex items-center gap-2 mt-1.5">
                  <TypeIcon size={12} className="text-[var(--text-muted)]" />
                  <p className="text-[10px] font-medium text-[var(--text-muted)]">
                    {activity.time}
                  </p>
                </div>
              </div>
            </motion.div>
          )
        })}
      </div>
    </motion.div>
  )
}
