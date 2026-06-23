import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { BookOpen, Database, Brain, Shield, Heart, Microscope, Sparkles, ExternalLink, ChevronDown, ChevronRight, Globe, FlaskConical, ShieldCheck } from 'lucide-react'
import { api, type KnowledgeStats } from '../lib/api'

/* ─── Types ─── */
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

/* ─── Domain 展示元数据（仅图标/配色；名称与描述走 i18n）─── */
const DOMAIN_META: Record<string, { icon: React.ElementType; color: string; hex: string }> = {
  clinical_intervention: { icon: Brain, color: 'from-cyan-500 to-teal-500', hex: '#06b6d4' },
  communication: { icon: Heart, color: 'from-rose-500 to-pink-500', hex: '#f43f5e' },
  crisis_safety: { icon: Shield, color: 'from-amber-500 to-orange-500', hex: '#f59e0b' },
  perspectives: { icon: Globe, color: 'from-violet-500 to-indigo-500', hex: '#8b5cf6' },
  clinical_lens: { icon: Microscope, color: 'from-emerald-500 to-green-500', hex: '#10b981' },
}
const DOMAIN_ORDER = ['clinical_intervention', 'communication', 'crisis_safety', 'perspectives', 'clinical_lens']

/* 文件路径 → i18n 安全 key（描述存 locale；未登记的文件回退到路径） */
const fileDescKey = (path: string) => path.replace(/\.jsonl$/, '').replace(/[^a-zA-Z0-9]+/g, '_')

/* ─── Component ─── */
export function KnowledgeCenterPage() {
  const { t } = useTranslation()
  const [expandedId, setExpandedId] = useState<string | null>('clinical_intervention')
  const [knowledgeStats, setKnowledgeStats] = useState<KnowledgeStats | null>(null)
  const [statsError, setStatsError] = useState('')

  useEffect(() => {
    let mounted = true
    api.getKnowledgeStats()
      .then(stats => {
        if (mounted) {
          setKnowledgeStats(stats)
          setStatsError('')
        }
      })
      .catch(err => {
        if (mounted) setStatsError(err instanceof Error ? err.message : t('knowledgeCenter.statsErrorGeneric'))
      })
    return () => { mounted = false }
  }, [t])

  // 从 /api/knowledge/stats 的 files 按 domain 动态分组渲染
  const categories = useMemo<KnowledgeCategory[]>(() => {
    const files = knowledgeStats?.files ?? []
    const byDomain: Record<string, KnowledgeItem[]> = {}
    for (const f of files) {
      if (!f.entries) continue
      const dom = Object.entries(f.domains ?? {}).sort((a, b) => b[1] - a[1])[0]?.[0] ?? 'unknown'
      const list = byDomain[dom] ?? (byDomain[dom] = [])
      list.push({
        file: f.path,
        entries: f.entries,
        description: t('knowledgeCenter.files.' + fileDescKey(f.path), { defaultValue: f.path }),
      })
    }
    const cats: KnowledgeCategory[] = DOMAIN_ORDER.flatMap((d): KnowledgeCategory[] => {
      const meta = DOMAIN_META[d]
      const items = byDomain[d]
      if (!meta || !items || items.length === 0) return []
      return [{
        id: d,
        name: t('knowledgeCenter.domains.' + d + '.name'),
        icon: meta.icon, color: meta.color, hex: meta.hex,
        description: t('knowledgeCenter.domains.' + d + '.description'),
        status: 'active', items: items.slice().sort((a, b) => b.entries - a.entries),
      }]
    })
    // 未在 DOMAIN_META 中登记的 domain 兜底显示
    for (const [d, items] of Object.entries(byDomain)) {
      if (d !== 'unknown' && !DOMAIN_META[d]) {
        cats.push({ id: d, name: d, icon: BookOpen, color: 'from-slate-500 to-gray-500', hex: '#64748b', description: d, status: 'active', items })
      }
    }
    cats.push({
      id: 'graphrag', name: t('knowledgeCenter.domains.graphrag.name'), icon: FlaskConical, color: 'from-purple-500 to-fuchsia-500', hex: '#a855f7',
      description: t('knowledgeCenter.domains.graphrag.description'), status: 'planned', items: [],
    })
    return cats
  }, [knowledgeStats, t])

  const totalEntries = knowledgeStats?.total_entries ?? 0
  const searchableEntries = knowledgeStats?.searchable_entries ?? 0
  const activeCount = categories.filter(c => c.status === 'active' && c.items.length > 0).length
  const plannedCount = categories.filter(c => c.status === 'planned').length

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
          <div className="flex flex-wrap gap-4 mt-4">
            {[
              { label: t('knowledgeCenter.stats.entries'), value: totalEntries, icon: Database, color: '#8b5cf6' },
              { label: t('knowledgeCenter.stats.searchable'), value: searchableEntries, icon: ShieldCheck, color: '#06b6d4' },
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
          {statsError && (
            <p className="text-xs mt-2" style={{ color: 'var(--text-muted)' }}>{t('knowledgeCenter.statsError', { error: statsError })}</p>
          )}
        </div>

        {/* Category cards */}
        <div className="space-y-3">
          {categories.map(cat => {
            const isExpanded = expandedId === cat.id
            const Icon = cat.icon
            const Chevron = isExpanded ? ChevronDown : ChevronRight
            const effectiveStatus = cat.items.some(i => i.entries > 0) ? 'active' : cat.status
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
                      <span className="font-semibold text-sm" style={{ color: 'var(--text-primary)' }}>{cat.name}</span>
                      {effectiveStatus === 'active' ? (
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
                    <p className="text-xs mt-0.5 truncate" style={{ color: 'var(--text-muted)' }}>{cat.description}</p>
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
                    {effectiveStatus === 'active' && (
                      <div className="flex items-center gap-2 px-3 py-2 rounded-lg text-[10px]" style={{ background: 'var(--bg-primary)', color: 'var(--text-muted)' }}>
                        <ExternalLink size={10} />
                        <span>{t('knowledgeCenter.ragNotePrefix')} <code className="font-mono px-1 rounded" style={{ background: 'var(--bg-secondary)' }}>search_faq()</code> {t('knowledgeCenter.ragNoteSuffix')}</span>
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
            <div className="flex items-center gap-2"><span className="w-2 h-2 rounded-full bg-emerald-500" /> {t('knowledgeCenter.roadmap.current', { totalEntries, searchableEntries, activeCount })}</div>
            <div className="flex items-center gap-2"><span className="w-2 h-2 rounded-full bg-cyan-500" /> {t('knowledgeCenter.roadmap.ready')}</div>
            <div className="flex items-center gap-2"><span className="w-2 h-2 rounded-full bg-purple-500" /> {t('knowledgeCenter.roadmap.future')}</div>
          </div>
        </div>
      </div>
    </div>
  )
}
