import { useEffect, useState, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { motion } from 'framer-motion'
import { MessageSquare, CheckCircle, Users, Zap } from 'lucide-react'
import { StatsCard } from '../components/dashboard/StatsCard'
import { PipelinePanel } from '../components/dashboard/PipelinePanel'
import ModelPanel from '../components/ModelPanel'
import { ActivityFeed } from '../components/dashboard/ActivityFeed'
import { api, type DataStats } from '../lib/api'

export function Dashboard() {
  const { t } = useTranslation()
  const [stats, setStats] = useState<DataStats | null>(null)
  const [sessionCount, setSessionCount] = useState(0)

  const fetchData = useCallback(() => {
    api.getDataStats().then(setStats).catch(() => {})
    api.listSessions().then((s) => setSessionCount(s.length)).catch(() => {})
  }, [])

  useEffect(() => {
    fetchData()
    const timer = setInterval(fetchData, 15000)
    return () => clearInterval(timer)
  }, [fetchData])

  const totalMessages = stats ? stats.l1_lines + stats.l2_lines : 0
  const totalAnalyses = stats ? Object.values(stats.analyses).reduce((a, b) => a + b, 0) : 0
  const totalReviews = stats ? Object.values(stats.reviews).reduce((a, b) => a + b, 0) : 0
  const completionRate = totalAnalyses > 0 && stats?.chunks
    ? Math.round((totalAnalyses / stats.chunks) * 100)
    : 0

  const statsData = [
    {
      title: t('dashboard.stats.processedMessages'),
      value: totalMessages,
      change: `L1: ${stats?.l1_lines ?? 0} / L2: ${stats?.l2_lines ?? 0}`,
      changeType: 'up' as const,
      icon: MessageSquare,
      iconGradient: 'linear-gradient(135deg, #10b981, #14b8a6)',
      delay: 0.1,
      sparkline: [40, 55, 48, 72, 65, 88, 95, 82, 91, 100],
    },
    {
      title: t('dashboard.stats.completionRate'),
      value: completionRate,
      change: `${totalAnalyses} / ${stats?.chunks ?? 0} chunks`,
      changeType: 'up' as const,
      icon: CheckCircle,
      iconGradient: 'linear-gradient(135deg, #22c55e, #16a34a)',
      suffix: '%',
      delay: 0.2,
      sparkline: [78, 82, 80, 85, 88, 87, 91, 90, 93, 94],
    },
    {
      title: t('dashboard.stats.activeSessions'),
      value: sessionCount,
      change: t('dashboard.reviewCount', { count: totalReviews }),
      changeType: 'up' as const,
      icon: Users,
      iconGradient: 'linear-gradient(135deg, #14b8a6, #0ea5e9)',
      delay: 0.3,
      liveIndicator: true,
      sparkline: [3, 4, 5, 4, 6, 7, 6, 8, 9, sessionCount || 1],
    },
    {
      title: t('dashboard.stats.totalChunks'),
      value: stats?.chunks ?? 0,
      change: t('dashboard.testSet', { count: stats?.test_lines ?? 0 }),
      changeType: 'up' as const,
      icon: Zap,
      iconGradient: 'linear-gradient(135deg, #8b5cf6, #6d28d9)',
      delay: 0.4,
      sparkline: [10, 15, 18, 20, 22, 25, 28, 30, 32, stats?.chunks ?? 0],
    },
  ]

  return (
    <div className="flex-1 overflow-y-auto scrollbar-fade p-8 transition-all duration-300">
      <motion.div
        initial={{ opacity: 0, y: -16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
        className="mb-8"
      >
        <div className="flex items-center gap-2 mb-1">
          <h1 className="text-2xl font-bold text-[var(--text-primary)]">
            {t('dashboard.title')}
          </h1>
          <span
            className="text-xs font-medium px-2.5 py-1 rounded-full"
            style={{
              background: 'rgba(16,185,129,0.12)',
              color: '#059669',
            }}
          >
            {t('dashboard.realTimeMonitor')}
          </span>
        </div>
        <p className="text-sm text-[var(--text-muted)]">
          {t('dashboard.welcome')}
        </p>
      </motion.div>

      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-6 mb-8">
        {statsData.map((stat) => (
          <StatsCard key={stat.title} {...stat} />
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
        <PipelinePanel />
        <ModelPanel />
      </div>

      <ActivityFeed />
    </div>
  )
}
