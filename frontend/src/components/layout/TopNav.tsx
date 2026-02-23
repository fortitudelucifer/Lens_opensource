import { useEffect, useState } from 'react'
import { Bell, FileText, Search, User } from 'lucide-react'
import { api, type ChatSessionSearchResult } from '../../lib/api'

interface TopNavProps {
  sidebarCollapsed: boolean
  onOpenSessionFromSearch: (session: ChatSessionSearchResult) => void
}

export function TopNav({ sidebarCollapsed, onOpenSessionFromSearch }: TopNavProps) {
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(false)
  const [results, setResults] = useState<ChatSessionSearchResult[]>([])

  useEffect(() => {
    const keyword = query.trim()
    if (!keyword) {
      setResults([])
      setLoading(false)
      return
    }

    const timer = window.setTimeout(async () => {
      setLoading(true)
      try {
        const data = await api.searchSessions(keyword, 12)
        setResults(data.results || [])
      } catch {
        setResults([])
      } finally {
        setLoading(false)
      }
    }, 250)

    return () => window.clearTimeout(timer)
  }, [query])

  return (
    <div
      className={`fixed top-0 right-0 h-16 glass-nav z-30 flex items-center justify-between px-8 transition-[left] duration-300 ${
        sidebarCollapsed ? 'left-0' : 'left-64'
      }`}
    >
      {/* Search */}
      <div className="flex-1 max-w-xl">
        <div className="relative group">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[var(--text-muted)] group-focus-within:text-emerald-500 transition-colors" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索记录、联系人..."
            className="w-full h-10 pl-10 pr-4 bg-[var(--bg-secondary)] border border-transparent focus:border-emerald-500/30 rounded-xl text-sm transition-all focus:bg-[var(--bg-card)] outline-none"
          />

          {query.trim() && (
            <div className="absolute left-0 right-0 mt-2 rounded-xl border border-[var(--border-color)] bg-[var(--bg-card)] shadow-lg overflow-hidden max-h-96 overflow-y-auto">
              {loading && <div className="px-4 py-3 text-xs text-[var(--text-muted)]">搜索中...</div>}

              {!loading && results.length === 0 && (
                <div className="px-4 py-3 text-xs text-[var(--text-muted)]">未找到匹配会话（支持标题和全文匹配）</div>
              )}

              {!loading && results.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => {
                    onOpenSessionFromSearch(item)
                    setQuery('')
                  }}
                  className="w-full px-4 py-3 text-left border-b last:border-b-0 border-[var(--border-color)] hover:bg-[var(--bg-secondary)] transition-colors"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-[var(--text-primary)] truncate">{item.title || '未命名会话'}</p>
                      {item.matched_excerpt && (
                        <p className="text-xs text-[var(--text-muted)] mt-1 line-clamp-2">{item.matched_excerpt}</p>
                      )}
                    </div>
                    <span className="shrink-0 inline-flex items-center gap-1 rounded-full bg-emerald-500/10 px-2 py-0.5 text-[10px] text-emerald-700 dark:text-emerald-300">
                      <FileText className="w-3 h-3" />
                      {item.match_type === 'title' ? '标题' : item.match_type === 'fulltext' ? '全文' : '标题+全文'}
                    </span>
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Right Actions */}
      <div className="flex items-center gap-4 ml-4">
        <button className="w-10 h-10 rounded-xl flex items-center justify-center text-[var(--text-secondary)] hover:text-emerald-500 hover:bg-emerald-500/10 transition-colors relative">
          <Bell className="w-5 h-5" />
          <span className="absolute top-2 right-2 w-2 h-2 bg-emerald-500 rounded-full border-2 border-[var(--bg-card)]" />
        </button>
        
        <div className="w-px h-6 bg-[var(--border-color)] mx-2" />
        
        <button className="flex items-center gap-3 hover:opacity-80 transition-opacity">
          <div className="w-9 h-9 rounded-full bg-gradient-to-br from-emerald-400 to-teal-600 flex items-center justify-center text-white shadow-md">
            <User className="w-5 h-5" />
          </div>
          <div className="hidden md:block text-left">
            <p className="text-sm font-semibold">User</p>
            <p className="text-xs text-[var(--text-muted)]">Premium Plan</p>
          </div>
        </button>
      </div>
    </div>
  )
}
