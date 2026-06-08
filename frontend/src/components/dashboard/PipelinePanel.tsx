import { useEffect, useState, useCallback } from 'react'
import { motion } from 'framer-motion'
import { Activity, Brain, Zap, ShieldCheck, FileInput, Database, Layers, Image, Mic } from 'lucide-react'
import { api, type PipelineState } from '@/lib/api'

const PHASE_META: Record<number, { name: string; icon: React.ElementType }> = {
  0: { name: '数据导入 (Ingestion)', icon: FileInput },
  1: { name: '多模态处理 (Multimodal)', icon: Image },
  2: { name: '语义压缩 (Compression)', icon: Layers },
  3: { name: '合并 & 时间轴 (Merge)', icon: Database },
  4: { name: 'L1/L2 分支 & SFT', icon: ShieldCheck },
  5: { name: 'MoA 融合分析', icon: Brain },
  6: { name: 'QLoRA 训练', icon: Mic },
  7: { name: 'RAG 索引 (FAISS)', icon: Zap },
}

export function PipelinePanel() {
  const [pipeline, setPipeline] = useState<PipelineState | null>(null)

  const fetchStatus = useCallback(() => {
    api.getPipelineStatus().then(setPipeline).catch(() => {})
  }, [])

  useEffect(() => {
    fetchStatus()
    const timer = setInterval(fetchStatus, 5000)
    return () => clearInterval(timer)
  }, [fetchStatus])

  const pipelineStages = pipeline
    ? Object.entries(pipeline.phases).map(([key, phase]) => {
        const phaseNum = parseInt(key)
        const meta = PHASE_META[phaseNum] || { name: phase.name, icon: Database }
        const isRunning = phase.status === 'running'
        const isDone = phase.status === 'done'
        return {
          id: phaseNum,
          name: meta.name,
          icon: meta.icon,
          status: isDone ? 'completed' as const : isRunning ? 'processing' as const : 'waiting' as const,
          time: isRunning ? '进行中' : isDone ? '完成' : '-',
          throughput: phase.detail || '-',
          progress: isDone ? 100 : isRunning ? 50 : 0,
          metrics: [{ label: '状态', value: phase.status }, { label: '详情', value: phase.detail || '--' }],
          active: isRunning,
        }
      })
    : Object.entries(PHASE_META).map(([key, meta]) => ({
        id: parseInt(key),
        name: meta.name,
        icon: meta.icon,
        status: 'waiting' as const,
        time: '-',
        throughput: '-',
        progress: 0,
        metrics: [{ label: '状态', value: '等待中' }, { label: '详情', value: '--' }],
        active: false,
      }))
  return (
    <motion.div
      initial={{ opacity: 0, y: 24 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, delay: 0.4 }}
      className="glass-card rounded-2xl p-6"
    >
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-base font-bold mb-1 text-[var(--text-primary)]">
            Agent SFT & MoA 流水线
          </h2>
          <p className="text-xs text-[var(--text-muted)]">
            实时监控多模态融合处理状态
          </p>
        </div>
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-emerald-500/10 border border-emerald-500/20">
          <Activity size={14} className="text-emerald-500 animate-pulse" />
          <span className="text-xs font-semibold text-emerald-500">
            System Healthy
          </span>
        </div>
      </div>

      <div className="space-y-4 relative">
        <div className="absolute left-6 top-8 bottom-8 w-px bg-[var(--border-color)]" />

        {pipelineStages.map((stage, i) => {
          const Icon = stage.icon
          const isProcessing = stage.status === 'processing'
          const isCompleted = stage.status === 'completed'

          return (
            <motion.div
              key={stage.id}
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: 0.5 + i * 0.1 }}
              className="relative flex items-start gap-4"
            >
              <div
                className={`relative z-10 w-12 h-12 rounded-2xl flex items-center justify-center flex-shrink-0 transition-colors duration-500
                  ${
                    isCompleted
                      ? 'bg-emerald-500/10 text-emerald-500 shadow-[0_0_15px_rgba(16,185,129,0.2)] border border-emerald-500/20'
                      : isProcessing
                        ? 'bg-teal-500/10 text-teal-500 shadow-[0_0_20px_rgba(20,184,166,0.25)] border border-teal-500/30'
                        : 'bg-[var(--bg-secondary)] text-[var(--text-muted)] border border-[var(--border-color)]'
                  }
                `}
              >
                <Icon size={20} className={isProcessing ? 'animate-pulse' : ''} />
              </div>

              <div
                className={`flex-1 rounded-2xl p-4 transition-all duration-300 ${
                  stage.active
                    ? 'bg-[var(--bg-card)] border border-teal-500/20 shadow-[0_4px_20px_rgba(20,184,166,0.08)]'
                    : 'bg-[var(--bg-secondary)] border border-transparent hover:border-[var(--border-color)]'
                }`}
              >
                <div className="flex items-center justify-between mb-3">
                  <h3
                    className={`font-semibold text-sm ${
                      stage.active ? 'text-teal-600' : 'text-[var(--text-primary)]'
                    }`}
                  >
                    {stage.name}
                  </h3>
                  <div className="flex items-center gap-3 text-xs font-mono">
                    <span className="text-[var(--text-secondary)]">{stage.throughput}</span>
                    <span className={stage.active ? 'text-teal-600' : 'text-[var(--text-muted)]'}>
                      {stage.time}
                    </span>
                  </div>
                </div>

                <div className="flex items-center gap-4 mb-3">
                  {stage.metrics.map((metric, idx) => (
                    <div key={idx} className="flex-1">
                      <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider mb-1">
                        {metric.label}
                      </p>
                      <p className="text-sm font-medium text-[var(--text-primary)]">
                        {metric.value}
                      </p>
                    </div>
                  ))}
                </div>

                <div className="h-1.5 w-full bg-[var(--border-color)] rounded-full overflow-hidden">
                  <motion.div
                    className="h-full rounded-full"
                    style={{
                      background: isCompleted
                        ? '#10b981'
                        : 'linear-gradient(90deg, #14b8a6, #10b981)',
                    }}
                    initial={{ width: 0 }}
                    animate={{ width: `${stage.progress}%` }}
                    transition={{ duration: 1.2, delay: 0.6 + i * 0.1, ease: [0.4, 0, 0.2, 1] }}
                  />
                </div>
              </div>
            </motion.div>
          )
        })}
      </div>
    </motion.div>
  )
}
