import { useEffect, useRef, useState } from 'react'
import { motion } from 'framer-motion'
import { MoreHorizontal, Trash2, ArrowLeft, Sparkles, Download } from 'lucide-react'
import type { Persona, ChatMode } from '../../types'

interface ChatModelOption {
  key: string
  backend: string
  model: string
  baseUrl: string
}

interface ChatTopBarProps {
  persona: Persona
  personaOptions: Persona[]
  mode: ChatMode
  onModeChange: (mode: ChatMode) => void
  useRag: boolean
  onUseRagChange: (enabled: boolean) => void
  useKnowledge: boolean
  onUseKnowledgeChange: (enabled: boolean) => void
  models: ChatModelOption[]
  selectedModelKey: string
  onModelChange: (modelKey: string) => void
  onClearMessages: () => void
  onBackToAdvisors: () => void
  onSwitchPersona: (personaId: Persona['id']) => void
  onExport?: () => void
  hasMessages?: boolean
  eftStage?: string | null
}

export function ChatTopBar({
  persona,
  personaOptions,
  mode,
  onModeChange,
  useRag,
  onUseRagChange,
  useKnowledge,
  onUseKnowledgeChange,
  models,
  selectedModelKey,
  onModelChange,
  onClearMessages,
  onBackToAdvisors,
  onSwitchPersona,
  onExport,
  hasMessages,
  eftStage,
}: ChatTopBarProps) {
  const Icon = persona.icon
  const EFT_STAGE_LABELS: Record<string, string> = {
    exploration: '探索阶段',
    comforting: '安抚阶段',
    action: '行动阶段',
  }
  const selectedModel = models.find((m) => m.key === selectedModelKey)
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handleOutside = (event: MouseEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) {
        setMenuOpen(false)
      }
    }

    document.addEventListener('mousedown', handleOutside)
    return () => document.removeEventListener('mousedown', handleOutside)
  }, [])

  const groupedModels = {
    local: models.filter((m) => m.backend.includes('local') || m.baseUrl.includes('127.0.0.1') || m.baseUrl.includes('localhost')),
    cloudOfficial: models.filter((m) => !(m.backend.includes('local') || m.baseUrl.includes('127.0.0.1') || m.baseUrl.includes('localhost')) && (m.baseUrl === '(默认)' || m.baseUrl.includes('api.deepseek.com'))),
    cloudProxy: models.filter((m) => !(m.backend.includes('local') || m.baseUrl.includes('127.0.0.1') || m.baseUrl.includes('localhost')) && !(m.baseUrl === '(默认)' || m.baseUrl.includes('api.deepseek.com'))),
  }

  return (
    <div className="h-16 glass-nav flex items-center justify-between px-6 border-b border-[var(--border-color)] z-10 sticky top-0 bg-gradient-to-r from-white/55 via-emerald-50/30 to-cyan-50/45 dark:from-stone-950/80 dark:via-emerald-950/20 dark:to-teal-950/20">
      {/* Left: Persona Info */}
      <div className="flex items-center gap-3">
        <div
          className="w-10 h-10 rounded-2xl flex items-center justify-center border shadow-sm"
          style={{
            backgroundColor: `${persona.hex}15`,
            borderColor: `${persona.hex}40`,
          }}
        >
          <Icon className="w-5 h-5" style={{ color: persona.hex }} />
        </div>
        <div>
          <h2 className="font-bold text-[var(--text-primary)] leading-tight flex items-center gap-2">
            {persona.name}
            {eftStage && EFT_STAGE_LABELS[eftStage] && (
              <span className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-pink-500/15 text-pink-600 dark:text-pink-400 border border-pink-500/20">
                {EFT_STAGE_LABELS[eftStage]}
              </span>
            )}
            <span className="flex h-2 w-2 relative">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
              <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
            </span>
          </h2>
          <p className="text-[10px] uppercase tracking-wider font-semibold" style={{ color: persona.hex }}>
            Online Assistant
          </p>
        </div>
      </div>

      {/* Right: Mode Toggle & Actions */}
      <div className="flex items-center gap-4">
        <div className="hidden md:flex items-center gap-2 rounded-xl border border-[var(--border-color)] bg-[var(--bg-secondary)] px-3 py-1.5">
          <span className="text-[10px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">
            模型
          </span>
          <select
            value={selectedModelKey}
            onChange={(e) => onModelChange(e.target.value)}
            className="h-7 rounded-md border border-transparent bg-transparent px-2 text-xs text-[var(--text-primary)] outline-none transition-colors hover:bg-[var(--bg-card)] focus:border-emerald-500/30"
          >
            {groupedModels.local.length > 0 && (
              <optgroup label="本地模型">
                {groupedModels.local.map((m) => (
                  <option key={m.key} value={m.key}>
                    {m.backend} · {m.model}
                  </option>
                ))}
              </optgroup>
            )}
            {groupedModels.cloudOfficial.length > 0 && (
              <optgroup label="云端官方">
                {groupedModels.cloudOfficial.map((m) => (
                  <option key={m.key} value={m.key}>
                    {m.backend} · {m.model}
                  </option>
                ))}
              </optgroup>
            )}
            {groupedModels.cloudProxy.length > 0 && (
              <optgroup label="云端代理">
                {groupedModels.cloudProxy.map((m) => (
                  <option key={m.key} value={m.key}>
                    {m.backend} · {m.model}
                  </option>
                ))}
              </optgroup>
            )}
          </select>
          {selectedModel && (
            <span className="max-w-[180px] truncate rounded-md bg-[var(--bg-card)] px-2 py-1 text-[10px] text-[var(--text-muted)]">
              {selectedModel.baseUrl}
            </span>
          )}
        </div>

        <div className="hidden md:flex items-center gap-2 rounded-xl border border-[var(--border-color)] bg-[var(--bg-secondary)] px-3 py-1.5">
          <span className="text-[10px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">
            聊天记录
          </span>
          <button
            type="button"
            role="switch"
            aria-checked={useRag}
            onClick={() => onUseRagChange(!useRag)}
            className={`inline-flex h-6 w-11 items-center rounded-full border p-0.5 transition-all ${
              useRag ? 'border-emerald-500/40 bg-emerald-500/70' : 'border-[var(--border-color)] bg-[var(--bg-card)]'
            }`}
          >
            <span
              className={`h-4 w-4 rounded-full bg-white shadow transition-transform ${
                useRag ? 'translate-x-5' : 'translate-x-0'
              }`}
            />
          </button>
        </div>
        <div className="hidden md:flex items-center gap-2 rounded-xl border border-[var(--border-color)] bg-[var(--bg-secondary)] px-3 py-1.5">
          <span className="text-[10px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">
            专业知识
          </span>
          <button
            type="button"
            role="switch"
            aria-checked={useKnowledge}
            onClick={() => onUseKnowledgeChange(!useKnowledge)}
            className={`inline-flex h-6 w-11 items-center rounded-full border p-0.5 transition-all ${
              useKnowledge ? 'border-violet-500/40 bg-violet-500/70' : 'border-[var(--border-color)] bg-[var(--bg-card)]'
            }`}
          >
            <span
              className={`h-4 w-4 rounded-full bg-white shadow transition-transform ${
                useKnowledge ? 'translate-x-5' : 'translate-x-0'
              }`}
            />
          </button>
        </div>

        <div className="flex p-1 bg-[var(--bg-secondary)] rounded-xl border border-[var(--border-color)]">
          <button
            onClick={() => onModeChange('listen')}
            className={`relative px-4 py-1.5 text-xs font-semibold rounded-lg transition-colors z-10 ${
              mode === 'listen' ? 'text-white' : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
            }`}
          >
            {mode === 'listen' && (
              <motion.div
                layoutId="mode-bg"
                className="absolute inset-0 bg-gradient-to-r from-emerald-500 to-teal-500 rounded-lg -z-10 shadow-sm"
                transition={{ type: "spring", stiffness: 300, damping: 30 }}
              />
            )}
            倾听模式
          </button>
          <button
            onClick={() => onModeChange('deep')}
            className={`relative px-4 py-1.5 text-xs font-semibold rounded-lg transition-colors z-10 ${
              mode === 'deep' ? 'text-white' : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
            }`}
          >
            {mode === 'deep' && (
              <motion.div
                layoutId="mode-bg"
                className="absolute inset-0 bg-gradient-to-r from-violet-500 to-purple-500 rounded-lg -z-10 shadow-sm"
                transition={{ type: "spring", stiffness: 300, damping: 30 }}
              />
            )}
            深度互动
          </button>
        </div>

        <div className="w-px h-6 bg-[var(--border-color)]" />

        <div ref={menuRef} className="relative">
          <button
            onClick={() => setMenuOpen((v) => !v)}
            className="p-2 text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-secondary)] rounded-xl transition-colors"
          >
            <MoreHorizontal size={20} />
          </button>

          {menuOpen && (
            <div className="absolute right-0 top-11 z-30 min-w-[220px] rounded-xl border border-[var(--border-color)] bg-[var(--bg-card)] p-1 shadow-lg">
              <button
                onClick={() => {
                  onClearMessages()
                  setMenuOpen(false)
                }}
                className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-xs text-[var(--text-secondary)] transition-colors hover:bg-[var(--bg-secondary)] hover:text-[var(--text-primary)]"
              >
                <Trash2 className="h-3.5 w-3.5" />
                清空当前对话
              </button>
              <button
                onClick={() => {
                  onBackToAdvisors()
                  setMenuOpen(false)
                }}
                className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-xs text-[var(--text-secondary)] transition-colors hover:bg-[var(--bg-secondary)] hover:text-[var(--text-primary)]"
              >
                <ArrowLeft className="h-3.5 w-3.5" />
                返回顾问选择
              </button>
              {hasMessages && onExport && (
                <button
                  onClick={() => { onExport(); setMenuOpen(false) }}
                  className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-xs text-[var(--text-secondary)] transition-colors hover:bg-[var(--bg-secondary)] hover:text-[var(--text-primary)]"
                >
                  <Download className="h-3.5 w-3.5" />
                  导出对话
                </button>
              )}
              <div className="my-1 h-px bg-[var(--border-color)]" />
              <p className="px-3 py-1 text-[10px] uppercase tracking-wider text-[var(--text-muted)]">切换顾问类型</p>
              {personaOptions.map((p) => {
                const PersonaIcon = p.icon
                return (
                  <button
                    key={p.id}
                    onClick={() => {
                      onSwitchPersona(p.id)
                      setMenuOpen(false)
                    }}
                    className="flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-xs text-[var(--text-secondary)] transition-colors hover:bg-[var(--bg-secondary)] hover:text-[var(--text-primary)]"
                  >
                    <span className="flex items-center gap-2">
                      <PersonaIcon className="h-3.5 w-3.5" style={{ color: p.hex }} />
                      {p.name}
                    </span>
                    {p.id === persona.id && <Sparkles className="h-3.5 w-3.5 text-emerald-500" />}
                  </button>
                )
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
