import { motion } from 'framer-motion'
import { Activity, Brain, Zap, ShieldCheck, FileInput } from 'lucide-react'

const pipelineStages = [
  {
    id: 1,
    name: 'Ingestion & Triage',
    icon: FileInput,
    status: 'completed' as const,
    time: '120ms',
    throughput: '342/s',
    progress: 100,
    metrics: [{ label: '媒体解析', value: '100%' }, { label: 'OCR', value: '99.8%' }],
  },
  {
    id: 2,
    name: 'MoA Fusion (S1/S2)',
    icon: Brain,
    status: 'processing' as const,
    time: '24s',
    throughput: '12/s',
    progress: 68,
    metrics: [{ label: 'DeepSeek', value: '85%' }, { label: 'GLM-4.7', value: '60%' }],
    active: true,
  },
  {
    id: 3,
    name: 'Review & Remediation (S3/S4)',
    icon: ShieldCheck,
    status: 'waiting' as const,
    time: '-',
    throughput: '-',
    progress: 0,
    metrics: [{ label: '通过率', value: '--' }, { label: '补齐率', value: '--' }],
  },
  {
    id: 4,
    name: 'Vector Indexing',
    icon: Zap,
    status: 'waiting' as const,
    time: '-',
    throughput: '-',
    progress: 0,
    metrics: [{ label: 'FAISS', value: '--' }, { label: 'BGE-M3', value: '--' }],
  },
]

export function PipelinePanel() {
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
