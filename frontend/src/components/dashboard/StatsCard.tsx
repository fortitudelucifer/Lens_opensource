import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { TrendingUp, TrendingDown } from 'lucide-react'

interface StatsCardProps {
  title: string
  value: string | number
  change: string
  changeType: 'up' | 'down' | 'neutral'
  icon: React.ElementType
  iconGradient: string
  suffix?: string
  delay?: number
  sparkline?: number[]
  liveIndicator?: boolean
}

function useCountUp(target: number, duration: number = 1500, delay: number = 0) {
  const [count, setCount] = useState(0)

  useEffect(() => {
    const timer = setTimeout(() => {
      const start = Date.now()
      const step = () => {
        const elapsed = Date.now() - start
        const progress = Math.min(elapsed / duration, 1)
        const eased = 1 - Math.pow(1 - progress, 3)
        setCount(Math.floor(eased * target))
        if (progress < 1) requestAnimationFrame(step)
      }
      requestAnimationFrame(step)
    }, delay)
    return () => clearTimeout(timer)
  }, [target, duration, delay])

  return count
}

function Sparkline({ data }: { data: number[] }) {
  const max = Math.max(...data)
  const min = Math.min(...data)
  const range = max - min || 1
  const w = 80
  const h = 32
  const points = data
    .map((v, i) => {
      const x = (i / (data.length - 1)) * w
      const y = h - ((v - min) / range) * h
      return `${x},${y}`
    })
    .join(' ')

  return (
    <svg width={w} height={h} className="opacity-60">
      <polyline
        points={points}
        fill="none"
        stroke="url(#sparkGrad)"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <defs>
        <linearGradient id="sparkGrad" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor="#14b8a6" />
          <stop offset="100%" stopColor="#10b981" />
        </linearGradient>
      </defs>
    </svg>
  )
}

export function StatsCard({
  title,
  value,
  change,
  changeType,
  icon: Icon,
  iconGradient,
  suffix = '',
  delay = 0,
  sparkline,
  liveIndicator,
}: StatsCardProps) {
  const numericValue = typeof value === 'number' ? value : parseFloat(String(value).replace(/[^0-9.]/g, ''))
  const isFloat = String(value).includes('.')
  const displayCount = useCountUp(numericValue, 1500, delay * 1000)
  const displayValue = isFloat ? (displayCount / (numericValue > 100 ? 1 : 10)).toFixed(1) : displayCount.toLocaleString()

  return (
    <motion.div
      initial={{ opacity: 0, y: 24 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, delay, ease: [0.4, 0, 0.2, 1] }}
      className="glass-card rounded-2xl p-5 relative overflow-hidden"
    >
      <div className="absolute inset-0 opacity-5 rounded-2xl" style={{ background: iconGradient }} />

      <div className="relative">
        <div className="flex items-start justify-between mb-4">
          <div>
            <p className="text-xs font-medium uppercase tracking-wider mb-1 text-[var(--text-muted)]">
              {title}
            </p>
            <div className="flex items-end gap-1">
              <span className="text-3xl font-bold text-[var(--text-primary)]">
                {displayValue}
              </span>
              {suffix && (
                <span className="text-lg font-semibold mb-0.5 text-[var(--text-secondary)]">
                  {suffix}
                </span>
              )}
            </div>
          </div>
          <div className="w-11 h-11 rounded-xl flex items-center justify-center flex-shrink-0 shadow-lg" style={{ background: iconGradient }}>
            <Icon size={20} className="text-white" />
          </div>
        </div>

        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            {changeType === 'up' && <TrendingUp size={13} className="text-emerald-500" />}
            {changeType === 'down' && <TrendingDown size={13} className="text-teal-600" />}
            <span
              className="text-xs font-semibold"
              style={{
                color: changeType === 'up' ? '#22c55e' : changeType === 'down' ? '#0f766e' : 'var(--text-muted)',
              }}
            >
              {change}
            </span>
          </div>
          <div className="flex items-center gap-2">
            {liveIndicator && (
              <div className="flex items-center gap-1.5">
                <div className="live-dot" />
                <span className="text-xs text-[var(--text-muted)]">实时</span>
              </div>
            )}
            {sparkline && <Sparkline data={sparkline} />}
          </div>
        </div>
      </div>
    </motion.div>
  )
}
