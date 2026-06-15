import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { motion } from 'framer-motion'
import { Cpu, Sliders, Layers, Hash, Maximize2, CheckCircle2, AlertCircle, ChevronRight } from 'lucide-react'
import { api, type AvailableModel, type ModelPreferences } from '@/lib/api'

const SAMPLE_MODELS = [
  { label: '主模型', value: 'Qwen3-8B (LoRA)', icon: Cpu, status: 'active' as const, detail: 'Local GPU' },
  { label: '融合模型', value: 'DeepSeek / GLM', icon: Cpu, status: 'standby' as const, detail: 'Cloud API' },
  { label: '检索索引', value: 'BGE-M3 1024d', icon: Layers, status: 'active' as const, detail: 'FAISS' },
]

const params = [
  { label: 'Temperature', value: 0.3, max: 1, icon: Sliders, color: '#10b981' },
  { label: 'Max Tokens', value: 4096, max: 4096, icon: Hash, color: '#3b82f6' },
  { label: 'Context Window', value: 16384, max: 128000, icon: Maximize2, color: '#8b5cf6' },
]

const statusConfig: Record<string, { labelKey: string; bg: string; color: string; icon: typeof CheckCircle2 }> = {
  active: { labelKey: 'dashboard.statusActive', bg: 'rgba(34,197,94,0.12)', color: '#22c55e', icon: CheckCircle2 },
  standby: { labelKey: 'dashboard.statusStandby', bg: 'rgba(245,158,11,0.12)', color: '#f59e0b', icon: AlertCircle },
}

export function ModelConfig() {
  const { t } = useTranslation()
  const [temperature, setTemperature] = useState(0.3)
  const [prefs, setPrefs] = useState<ModelPreferences | null>(null)
  const [available, setAvailable] = useState<AvailableModel[]>([])

  useEffect(() => {
    let mounted = true

    Promise.all([
      api.getModelPreferences().catch(() => null as ModelPreferences | null),
      api.getAvailableModels().catch(() => [] as AvailableModel[]),
    ]).then(([p, a]) => {
      if (!mounted) return
      setPrefs(p)
      setAvailable(a)
    })

    return () => {
      mounted = false
    }
  }, [])

  const models = useMemo(() => {
    if (!prefs) return SAMPLE_MODELS

    const findModel = (backend?: string, preferredModel?: string) => {
      if (!backend) return null
      return (
        available.find((m) => m.backend === backend && (!preferredModel || m.model === preferredModel))
        || available.find((m) => m.backend === backend)
        || null
      )
    }

    const chatModel = findModel(prefs.chat_backend, prefs.chat_model)
    const analysisModel = findModel(prefs.analysis_backend, prefs.analysis_model)
    const reviewModel = findModel(prefs.review_backend, prefs.review_model)

    const statusOf = (backend?: string) => {
      if (!backend) return 'standby' as const
      return available.some((m) => m.backend === backend) ? 'active' as const : 'standby' as const
    }

    return [
      {
        label: t('dashboard.primaryModel'),
        value: chatModel?.model || prefs.chat_model || prefs.chat_backend || SAMPLE_MODELS[0].value,
        icon: Cpu,
        status: statusOf(prefs.chat_backend),
        detail: chatModel?.base_url || t('dashboard.fromSettings'),
      },
      {
        label: t('dashboard.fusionModel'),
        value: `${analysisModel?.model || prefs.analysis_model || prefs.analysis_backend || 'N/A'} / ${reviewModel?.model || prefs.review_model || prefs.review_backend || 'N/A'}`,
        icon: Cpu,
        status: statusOf(prefs.analysis_backend),
        detail: `${analysisModel?.base_url || t('dashboard.preference')} + ${reviewModel?.base_url || t('dashboard.preference')}`,
      },
      SAMPLE_MODELS[2],
    ]
  }, [available, prefs])

  return (
    <motion.div
      initial={{ opacity: 0, y: 24 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, delay: 0.5 }}
      className="glass-card rounded-2xl p-6 flex flex-col"
    >
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-base font-bold mb-1 text-[var(--text-primary)]">{t('dashboard.modelConfig')}</h2>
          <p className="text-xs text-[var(--text-muted)]">{t('dashboard.modelConfigDesc')}</p>
        </div>
        <button
          className="text-xs font-semibold px-3 py-1.5 rounded-xl transition-all hover:scale-105 active:scale-95 text-white shadow-[0_4px_12px_rgba(16,185,129,0.3)]"
          style={{ background: 'linear-gradient(135deg, #10b981, #14b8a6)' }}
        >
          {t('dashboard.saveSettings')}
        </button>
      </div>

      <div className="space-y-3 mb-6">
        {models.map((model, i) => {
          const Icon = model.icon
          const sc = statusConfig[model.status]
          const StatusIcon = sc.icon

          return (
            <motion.div
              key={model.label}
              initial={{ opacity: 0, x: 16 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: 0.6 + i * 0.08 }}
              className="flex items-center gap-3 p-3 rounded-xl transition-all hover:scale-[1.01] bg-[var(--bg-secondary)] border border-[var(--border-color)]"
            >
              <div className="w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0 bg-emerald-500/10">
                <Icon size={18} className="text-emerald-600" />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-[10px] uppercase tracking-wider text-[var(--text-muted)]">{model.label}</p>
                <p className="text-sm font-semibold text-[var(--text-primary)]">{model.value}</p>
              </div>
              <div className="flex flex-col items-end gap-1">
                <span className="text-xs font-mono text-[var(--text-secondary)]">{model.detail}</span>
                <span
                  className="flex items-center gap-1 text-[10px] font-medium px-2 py-0.5 rounded-full"
                  style={{ background: sc.bg, color: sc.color }}
                >
                  <StatusIcon size={10} />
                  {t(sc.labelKey)}
                </span>
              </div>
            </motion.div>
          )
        })}
      </div>

      <div className="pt-5 border-t border-[var(--border-color)] flex-1 flex flex-col justify-end">
        <p className="text-xs font-semibold uppercase tracking-wider mb-4 text-[var(--text-muted)]">
          {t('dashboard.inferenceParams')}
        </p>
        <div className="space-y-5">
          {params.map((param, i) => {
            const Icon = param.icon
            const displayVal = param.label === 'Temperature' ? temperature.toFixed(1) : param.value.toLocaleString()
            const pct = param.label === 'Temperature' ? (temperature / param.max) * 100 : (param.value / param.max) * 100

            return (
              <motion.div
                key={param.label}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: 0.8 + i * 0.08 }}
              >
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <Icon size={14} style={{ color: param.color }} />
                    <span className="text-xs font-medium text-[var(--text-secondary)]">{param.label}</span>
                  </div>
                  <span className="text-xs font-bold text-[var(--text-primary)]">{displayVal}</span>
                </div>
                {param.label === 'Temperature' ? (
                  <input
                    type="range"
                    min={0}
                    max={1}
                    step={0.1}
                    value={temperature}
                    onChange={(e) => setTemperature(parseFloat(e.target.value))}
                    className="w-full h-1.5 rounded-full appearance-none cursor-pointer"
                    style={{ background: `linear-gradient(to right, ${param.color} ${pct}%, var(--border-color) ${pct}%)` }}
                  />
                ) : (
                  <div className="h-1.5 w-full bg-[var(--border-color)] rounded-full overflow-hidden">
                    <motion.div
                      className="h-full rounded-full"
                      style={{ background: `linear-gradient(90deg, ${param.color}, ${param.color}99)` }}
                      initial={{ width: 0 }}
                      animate={{ width: `${pct}%` }}
                      transition={{ duration: 1, delay: 0.9 + i * 0.1 }}
                    />
                  </div>
                )}
              </motion.div>
            )
          })}
        </div>

        <motion.button
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 1.1 }}
          className="mt-6 w-full flex items-center justify-center gap-2 py-3 rounded-xl text-sm font-medium transition-all hover:bg-emerald-500/10 text-emerald-600 border border-emerald-500/20"
        >
          {t('dashboard.viewAdvancedParams')} <ChevronRight size={14} />
        </motion.button>
      </div>
    </motion.div>
  )
}
