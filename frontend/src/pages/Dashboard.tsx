import { motion } from 'framer-motion'
import { MessageSquare, CheckCircle, Users, Zap } from 'lucide-react'
import { StatsCard } from '../components/dashboard/StatsCard'
import { PipelinePanel } from '../components/dashboard/PipelinePanel'
import { ModelConfig } from '../components/dashboard/ModelConfig'
import { ActivityFeed } from '../components/dashboard/ActivityFeed'

const statsData = [
  {
    title: '处理消息数',
    value: 32847,
    change: '+18.2% 本周',
    changeType: 'up' as const,
    icon: MessageSquare,
    iconGradient: 'linear-gradient(135deg, #10b981, #14b8a6)',
    delay: 0.1,
    sparkline: [40, 55, 48, 72, 65, 88, 95, 82, 91, 100],
  },
  {
    title: '完成率',
    value: 90,
    change: '+2.1% 提升',
    changeType: 'up' as const,
    icon: CheckCircle,
    iconGradient: 'linear-gradient(135deg, #22c55e, #16a34a)',
    suffix: '%',
    delay: 0.2,
    sparkline: [78, 82, 80, 85, 88, 87, 91, 90, 93, 94],
  },
  {
    title: '活跃会话',
    value: 9,
    change: '今日新增 3',
    changeType: 'up' as const,
    icon: Users,
    iconGradient: 'linear-gradient(135deg, #14b8a6, #0ea5e9)',
    delay: 0.3,
    liveIndicator: true,
    sparkline: [180, 195, 210, 198, 220, 235, 228, 240, 245, 247],
  },
  {
    title: '平均响应时间',
    value: 15,
    change: '-0.3s 更快',
    changeType: 'down' as const,
    icon: Zap,
    iconGradient: 'linear-gradient(135deg, #8b5cf6, #6d28d9)',
    suffix: 's',
    delay: 0.4,
    sparkline: [2.1, 1.9, 1.8, 1.7, 1.6, 1.5, 1.4, 1.3, 1.2, 1.2],
  },
]

export function Dashboard() {
  return (
    <div className="flex-1 overflow-y-auto p-8 transition-all duration-300">
      {/* Page header */}
      <motion.div
        initial={{ opacity: 0, y: -16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
        className="mb-8"
      >
        <div className="flex items-center gap-2 mb-1">
          <h1 className="text-2xl font-bold text-[var(--text-primary)]">
            系统总览
          </h1>
          <span
            className="text-xs font-medium px-2.5 py-1 rounded-full"
            style={{
              background: 'rgba(16,185,129,0.12)',
              color: '#059669',
            }}
          >
            实时监控
          </span>
        </div>
        <p className="text-sm text-[var(--text-muted)]">
          欢迎回来，今天关系顾问系统运行状态良好 ✨
        </p>
      </motion.div>

      {/* Stats grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-6 mb-8">
        {statsData.map((stat) => (
          <StatsCard key={stat.title} {...stat} />
        ))}
      </div>

      {/* Middle row: Pipeline + Model Config */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
        <PipelinePanel />
        <ModelConfig />
      </div>

      {/* Activity feed */}
      <ActivityFeed />
    </div>
  )
}
