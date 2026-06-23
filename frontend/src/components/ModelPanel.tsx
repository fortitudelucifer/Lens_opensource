import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { SlidersHorizontal, Zap, KeyRound } from 'lucide-react'
import ModelSelector from './ModelSelector'
import ModelTester from './ModelTester'
import ApiKeyChecker from './ApiKeyChecker'

type Tab = 'select' | 'connectivity' | 'keycheck'

// 「模型与连通」合一面板（运维台）——把原来分散的三块合到一个面板的三个标签里：
//   选型(ModelSelector) · 连通(ModelTester，自动探测) · Key 检查(ApiKeyChecker)
// 连通来源统一于 /api/models/reachable（与聊天下拉一致）。
export default function ModelPanel() {
  const { t } = useTranslation()
  const [tab, setTab] = useState<Tab>('select')

  const tabs = [
    { id: 'select' as const, label: t('settings.modelSelection'), icon: SlidersHorizontal },
    { id: 'connectivity' as const, label: t('settings.connectionTest'), icon: Zap },
    { id: 'keycheck' as const, label: t('settings.apiKeyManagement'), icon: KeyRound },
  ]

  return (
    <div className="bg-[var(--bg-card)] border border-[var(--border-color)] rounded-xl shadow-sm overflow-hidden">
      <div className="flex items-center gap-1 p-1.5 border-b border-[var(--border-color)] overflow-x-auto">
        {tabs.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium whitespace-nowrap transition-colors ${
              tab === id
                ? 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-300'
                : 'text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-secondary)]'
            }`}
          >
            <Icon className="w-4 h-4" />
            {label}
          </button>
        ))}
      </div>
      <div className="p-1">
        {tab === 'select' && <ModelSelector />}
        {tab === 'connectivity' && <ModelTester />}
        {tab === 'keycheck' && <ApiKeyChecker />}
      </div>
    </div>
  )
}
