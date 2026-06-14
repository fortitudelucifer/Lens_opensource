import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { BookOpen, Database, Brain, Shield, Heart, Microscope, Sparkles, ExternalLink, ChevronDown, ChevronRight, Globe, FlaskConical } from 'lucide-react'

/* ─── Knowledge Category Type ─── */
interface KnowledgeItem {
  file: string
  entries: number
  description: string
}
interface KnowledgeCategory {
  id: string
  name: string
  icon: React.ElementType
  color: string
  hex: string
  description: string
  status: 'active' | 'planned'
  items: KnowledgeItem[]
}

/* ─── Knowledge Data ─── */
const CATEGORIES: KnowledgeCategory[] = [
  {
    id: 'perspectives', name: 'S6 跨学科视角', icon: Globe, color: 'from-violet-500 to-indigo-500', hex: '#8b5cf6',
    description: '社会学、哲学、博弈论、文化研究四大学科视角，为关系问题提供多维透镜',
    status: 'active',
    items: [
      { file: 'perspectives/sociology.jsonl', entries: 10, description: '布尔迪厄场域/资本、吉登斯反思性、戈夫曼拟剧论' },
      { file: 'perspectives/philosophy.jsonl', entries: 10, description: '存在主义、现象学、实用主义、儒家关怀伦理' },
      { file: 'perspectives/game_theory.jsonl', entries: 10, description: '纳什均衡、囚徒困境、沉没成本、损失厌恶' },
      { file: 'perspectives/cultural.jsonl', entries: 10, description: '差序格局、集体/个人主义、面子/人情/报' },
    ],
  },
  {
    id: 'communication', name: '沟通技巧', icon: Heart, color: 'from-rose-500 to-pink-500', hex: '#f43f5e',
    description: '非暴力沟通等核心沟通方法论',
    status: 'active',
    items: [
      { file: 'communication/nvc_four_steps.jsonl', entries: 5, description: 'Marshall Rosenberg 非暴力沟通四步法：观察→感受→需要→请求' },
    ],
  },
  {
    id: 'crisis', name: '危机干预', icon: Shield, color: 'from-amber-500 to-orange-500', hex: '#f59e0b',
    description: '接地技巧、安全稳定化等危机应对资源',
    status: 'active',
    items: [
      { file: 'crisis/grounding_techniques.jsonl', entries: 5, description: '5-4-3-2-1 感官接地、呼吸调节等即时安全技巧' },
    ],
  },
  {
    id: 'eft_resources', name: 'EFT 情绪聚焦', icon: Brain, color: 'from-cyan-500 to-teal-500', hex: '#06b6d4',
    description: 'Sue Johnson 情绪聚焦治疗 Tango 九步流程',
    status: 'active',
    items: [
      { file: 'eft_resources/tango_process.jsonl', entries: 5, description: 'EFT Tango 九步 move：镜像→影响→编舞→处理→整合' },
    ],
  },
  {
    id: 'therapy_manuals', name: '治疗手册', icon: Microscope, color: 'from-emerald-500 to-green-500', hex: '#10b981',
    description: '系统化的治疗方法手册（CBT、DBT 等）',
    status: 'planned',
    items: [],
  },
  {
    id: 'graphrag', name: 'GraphRAG 知识图谱', icon: FlaskConical, color: 'from-purple-500 to-fuchsia-500', hex: '#a855f7',
    description: '跨学科概念关联的多跳推理知识图谱（NetworkX → Neo4j）',
    status: 'planned',
    items: [],
  },
]

/* ─── Component ─── */
export function KnowledgeCenterPage() {
  const { t } = useTranslation()
  const [expandedId, setExpandedId] = useState<string | null>('perspectives')

  const totalEntries = CATEGORIES.reduce((sum, c) => sum + c.items.reduce((s, i) => s + i.entries, 0), 0)
  const activeCount = CATEGORIES.filter(c => c.status === 'active').length
  const plannedCount = CATEGORIES.filter(c => c.status === 'planned').length

  return (
    <div className="flex-1 overflow-y-auto" style={{ background: 'var(--bg-primary)' }}>
      <div className="max-w-5xl mx-auto px-6 py-8">

        {/* Header */}
        <div className="mb-8">
          <div className="flex items-center gap-3 mb-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center">
              <BookOpen size={20} className="text-white" />
            </div>
            <div>
              <h1 className="text-xl font-bold" style={{ color: 'var(--text-primary)' }}>{t('knowledgeCenter.title')}</h1>
              <p className="text-xs" style={{ color: 'var(--text-muted)' }}>{t('knowledgeCenter.subtitle')}</p>
            </div>
          </div>

          {/* Stats bar */}
          <div className="flex gap-4 mt-4">
            {[
              { label: t('knowledgeCenter.stats.entries'), value: totalEntries, icon: Database, color: '#8b5cf6' },
              { label: t('knowledgeCenter.stats.activeDomains'), value: activeCount, icon: Sparkles, color: '#10b981' },
              { label: t('knowledgeCenter.stats.planned'), value: plannedCount, icon: FlaskConical, color: '#f59e0b' },
            ].map(s => (
              <div key={s.label} className="flex items-center gap-2 px-4 py-2 rounded-xl border" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
                <s.icon size={14} style={{ color: s.color }} />
                <span className="text-lg font-bold" style={{ color: s.color }}>{s.value}</span>
                <span className="text-xs" style={{ color: 'var(--text-muted)' }}>{s.label}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Category cards */}
        <div className="space-y-3">
          {CATEGORIES.map(cat => {
            const isExpanded = expandedId === cat.id
            const Icon = cat.icon
            const Chevron = isExpanded ? ChevronDown : ChevronRight
            return (
              <div key={cat.id} className="rounded-xl border overflow-hidden transition-all" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
                {/* Category header */}
                <button
                  onClick={() => setExpandedId(isExpanded ? null : cat.id)}
                  className="w-full flex items-center gap-3 px-5 py-4 text-left hover:bg-[var(--bg-secondary)]/50 transition-colors"
                >
                  <div className={`w-9 h-9 rounded-lg bg-gradient-to-br ${cat.color} flex items-center justify-center flex-shrink-0`}>
                    <Icon size={18} className="text-white" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-semibold text-sm" style={{ color: 'var(--text-primary)' }}>{t(`knowledgeCenter.categories.${cat.id}.name`)}</span>
                      {cat.status === 'active' ? (
                        <span className="px-2 py-0.5 text-[10px] font-bold rounded-full bg-emerald-500/15 text-emerald-600 dark:text-emerald-400">{t('knowledgeCenter.status.active')}</span>
                      ) : (
                        <span className="px-2 py-0.5 text-[10px] font-bold rounded-full bg-amber-500/15 text-amber-600 dark:text-amber-400">{t('knowledgeCenter.status.planned')}</span>
                      )}
                      {cat.items.length > 0 && (
                        <span className="text-[10px] font-mono" style={{ color: 'var(--text-muted)' }}>
                          {cat.items.reduce((s, i) => s + i.entries, 0)} {t('knowledgeCenter.entriesSuffix')}
                        </span>
                      )}
                    </div>
                    <p className="text-xs mt-0.5 truncate" style={{ color: 'var(--text-muted)' }}>{t(`knowledgeCenter.categories.${cat.id}.description`)}</p>
                  </div>
                  <Chevron size={16} style={{ color: 'var(--text-muted)' }} />
                </button>

                {/* Expanded items */}
                {isExpanded && (
                  <div className="border-t px-5 py-3 space-y-2" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-secondary)' }}>
                    {cat.items.length === 0 ? (
                      <p className="text-xs py-3 text-center" style={{ color: 'var(--text-muted)' }}>
                        {t('knowledgeCenter.emptyState')}
                      </p>
                    ) : (
                      cat.items.map(item => (
                        <div key={item.file} className="flex items-start gap-3 px-3 py-2.5 rounded-lg" style={{ background: 'var(--bg-card)' }}>
                          <div className="w-1.5 h-1.5 rounded-full mt-1.5 flex-shrink-0" style={{ background: cat.hex }} />
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2">
                              <code className="text-[11px] font-mono px-1.5 py-0.5 rounded" style={{ background: 'var(--bg-secondary)', color: cat.hex }}>{item.file}</code>
                              <span className="text-[10px] font-mono" style={{ color: 'var(--text-muted)' }}>{item.entries} {t('knowledgeCenter.entriesSuffix')}</span>
                            </div>
                            <p className="text-xs mt-1" style={{ color: 'var(--text-secondary)' }}>{item.description}</p>
                          </div>
                        </div>
                      ))
                    )}

                    {/* RAG integration note */}
                    {cat.status === 'active' && (
                      <div className="flex items-center gap-2 px-3 py-2 rounded-lg text-[10px]" style={{ background: 'var(--bg-primary)', color: 'var(--text-muted)' }}>
                        <ExternalLink size={10} />
                        <span>{t('knowledgeCenter.ragNote')}</span>
                      </div>
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </div>

        {/* Future roadmap */}
        <div className="mt-8 px-5 py-4 rounded-xl border" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <h3 className="text-sm font-semibold mb-2" style={{ color: 'var(--text-primary)' }}>{t('knowledgeCenter.roadmap.title')}</h3>
          <div className="space-y-1.5 text-xs" style={{ color: 'var(--text-secondary)' }}>
            <div className="flex items-center gap-2"><span className="w-2 h-2 rounded-full bg-emerald-500" /> {t('knowledgeCenter.roadmap.current', { totalEntries, activeCount })}</div>
            <div className="flex items-center gap-2"><span className="w-2 h-2 rounded-full bg-amber-500" /> {t('knowledgeCenter.roadmap.near')}</div>
            <div className="flex items-center gap-2"><span className="w-2 h-2 rounded-full bg-purple-500" /> {t('knowledgeCenter.roadmap.future')}</div>
          </div>
        </div>
      </div>
    </div>
  )
}
