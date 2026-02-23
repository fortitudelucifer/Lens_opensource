import { useCallback, useEffect, useMemo, useState } from 'react'
import { Sidebar } from './components/layout/Sidebar'
import { TopNav } from './components/layout/TopNav'
import { Dashboard } from './pages/Dashboard'
import { ChatPage } from './pages/ChatPage'
import { WelcomeScreen } from './pages/WelcomeScreen'
import ModelSelector from './components/ModelSelector'
import ModelTester from './components/ModelTester'
import ApiKeyChecker from './components/ApiKeyChecker'
import ReviewPanel from './components/ReviewPanel'
import { PERSONAS } from './constants'
import type { Persona } from './types'
import type { ChatSessionSearchResult } from './lib/api'
import { PanelLeftOpen } from 'lucide-react'

export function App() {
  const normalizePath = (path: string) => {
    if (path === '/') return '/dashboard'
    return path
  }

  const [theme, setTheme] = useState<'light' | 'dark'>(() => {
    if (typeof window !== 'undefined') {
      return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
    }
    return 'dark'
  })
  const [currentPath, setCurrentPath] = useState<string>(() =>
    typeof window !== 'undefined' ? normalizePath(window.location.pathname) : '/dashboard',
  )
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [searchTargetSession, setSearchTargetSession] = useState<ChatSessionSearchResult | null>(null)

  const navigate = useCallback((path: string, replace = false) => {
    const target = normalizePath(path)
    if (typeof window === 'undefined') return
    if (window.location.pathname !== target) {
      if (replace) {
        window.history.replaceState(null, '', target)
      } else {
        window.history.pushState(null, '', target)
      }
    }
    setCurrentPath(target)
  }, [])

  useEffect(() => {
    if (typeof window === 'undefined') return

    if (window.location.pathname === '/') {
      window.history.replaceState(null, '', '/dashboard')
    }

    const onPopState = () => {
      setCurrentPath(normalizePath(window.location.pathname))
    }

    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [navigate])

  const selectedPersona = useMemo<Persona | null>(() => {
    if (!currentPath.startsWith('/chat')) return null
    const parts = currentPath.split('/').filter(Boolean)
    const maybePersonaId = parts[1]
    return PERSONAS.find((p) => p.id === maybePersonaId) || null
  }, [currentPath])

  const activeNav = useMemo(() => {
    if (currentPath.startsWith('/consent')) return 'consent'
    if (currentPath.startsWith('/chat')) return 'chat'
    if (currentPath.startsWith('/review')) return 'review'
    if (currentPath.startsWith('/dual-mirror')) return 'dual-mirror'
    if (currentPath.startsWith('/communication-status')) return 'communication-status'
    if (currentPath.startsWith('/roundtable')) return 'roundtable'
    if (currentPath.startsWith('/knowledge-center')) return 'knowledge-center'
    if (currentPath.startsWith('/settings')) return 'settings'
    return 'dashboard'
  }, [currentPath])

  // Apply theme class
  useEffect(() => {
    if (theme === 'dark') {
      document.documentElement.classList.add('dark')
    } else {
      document.documentElement.classList.remove('dark')
    }
  }, [theme])

  const toggleTheme = () => {
    setTheme(prev => prev === 'dark' ? 'light' : 'dark')
  }

  const handleNavChange = (id: string) => {
    if (id === 'chat') {
      navigate('/chat/select-advisor')
      return
    }

    const navRouteMap: Record<string, string> = {
      consent: '/consent',
      dashboard: '/dashboard',
      review: '/review',
      settings: '/settings',
      'dual-mirror': '/dual-mirror',
      'communication-status': '/communication-status',
      roundtable: '/roundtable',
      'knowledge-center': '/knowledge-center',
    }

    const path = navRouteMap[id] || '/dashboard'
    navigate(path)
  }

  const handlePersonaSelect = (persona: Persona) => {
    navigate(`/chat/${persona.id}`)
  }

  const handleOpenSessionFromSearch = useCallback((session: ChatSessionSearchResult) => {
    const matchedPersona = PERSONAS.find((p) => p.id === session.agent_type)
    const targetPersona = matchedPersona || PERSONAS[0]
    setSearchTargetSession(session)
    navigate(`/chat/${targetPersona.id}`)
  }, [navigate])

  return (
    <div className="relative flex h-screen bg-[var(--bg-primary)] text-[var(--text-primary)] transition-colors duration-300 overflow-hidden">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_8%_12%,rgba(16,185,129,0.2),transparent_32%),radial-gradient(circle_at_85%_8%,rgba(6,182,212,0.16),transparent_30%),linear-gradient(145deg,#d4e6d080,#eef5ec80,#fdf8f05e)] dark:bg-[radial-gradient(circle_at_8%_12%,rgba(16,185,129,0.16),transparent_30%),radial-gradient(circle_at_85%_8%,rgba(20,184,166,0.12),transparent_28%),linear-gradient(145deg,rgba(12,10,9,0.82),rgba(28,25,23,0.78),rgba(10,16,18,0.74))]" />
      <Sidebar 
        active={activeNav} 
        setActive={handleNavChange} 
        theme={theme} 
        toggleTheme={toggleTheme} 
        collapsed={sidebarCollapsed}
        onToggleCollapsed={() => setSidebarCollapsed((v) => !v)}
      />

      {sidebarCollapsed && (
        <button
          onClick={() => setSidebarCollapsed(false)}
          className="fixed left-4 top-4 z-50 rounded-xl border border-[var(--border-color)] bg-[var(--bg-card)] p-2.5 text-[var(--text-secondary)] shadow-sm transition-colors hover:text-[var(--text-primary)] hover:bg-[var(--bg-secondary)]"
          title="展开侧边栏"
          aria-label="展开侧边栏"
        >
          <PanelLeftOpen className="h-4 w-4" />
        </button>
      )}
      
      <div className="relative z-10 flex-1 flex flex-col min-w-0">
        <TopNav
          sidebarCollapsed={sidebarCollapsed}
          onOpenSessionFromSearch={handleOpenSessionFromSearch}
        />
        
        <main
          className={`flex-1 flex flex-col relative overflow-hidden h-full pt-16 transition-all duration-300 ${
            sidebarCollapsed ? 'lg:pl-0' : 'lg:pl-64'
          }`}
        >
          {activeNav === 'consent' && (
            <div className="flex-1 p-8">
              <div className="h-full rounded-2xl border border-dashed border-[var(--border-color)] bg-[var(--bg-card)]/70" />
            </div>
          )}

          {activeNav === 'dashboard' && <Dashboard />}
          
          {activeNav === 'chat' && !selectedPersona && (
            <WelcomeScreen onSelect={handlePersonaSelect} />
          )}
          
          {activeNav === 'chat' && selectedPersona && (
            <ChatPage
              initialPersona={selectedPersona}
              onReturnToWelcome={() => navigate('/chat/select-advisor')}
              onPersonaRouteChange={(personaId) => navigate(`/chat/${personaId}`)}
              searchTargetSession={searchTargetSession}
              onSearchTargetConsumed={() => setSearchTargetSession(null)}
            />
          )}

          {activeNav === 'review' && (
            <div className="flex-1 overflow-hidden flex flex-col p-6">
              <div className="bg-[var(--bg-card)] border border-[var(--border-color)] rounded-xl shadow-sm flex-1 flex flex-col min-h-0">
                <ReviewPanel />
              </div>
            </div>
          )}
          
          {activeNav === 'settings' && (
            <div className="flex-1 overflow-y-auto p-6 space-y-8">
              {/* Header */}
              <div className="relative">
                <div className="absolute inset-0 bg-gradient-to-r from-emerald-500/10 to-teal-500/10 rounded-2xl" />
                <div className="relative p-6">
                  <h1 className="text-3xl font-bold tracking-tight text-[var(--text-primary)]">
                    设置
                  </h1>
                  <p className="text-sm text-[var(--text-muted)] mt-2 max-w-2xl">
                    API 密钥与模型配置 • 系统参数管理
                  </p>
                </div>
              </div>

              {/* Settings Sections */}
              <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
                <div className="space-y-6">
                  <div className="flex items-center gap-2">
                    <div className="w-1 h-6 bg-blue-500 rounded-full" />
                    <h2 className="text-lg font-semibold">模型选择</h2>
                  </div>
                  <div className="bg-[var(--bg-card)] border border-[var(--border-color)] rounded-xl shadow-sm p-1">
                    <ModelSelector />
                  </div>
                </div>
                
                <div className="space-y-6">
                  <div className="flex items-center gap-2">
                    <div className="w-1 h-6 bg-green-500 rounded-full" />
                    <h2 className="text-lg font-semibold">连接测试</h2>
                  </div>
                  <div className="bg-[var(--bg-card)] border border-[var(--border-color)] rounded-xl shadow-sm p-1">
                    <ModelTester />
                  </div>
                </div>
              </div>

              <div className="space-y-6">
                <div className="flex items-center gap-2">
                  <div className="w-1 h-6 bg-purple-500 rounded-full" />
                  <h2 className="text-lg font-semibold">API 密钥管理</h2>
                </div>
                <div className="bg-[var(--bg-card)] border border-[var(--border-color)] rounded-xl shadow-sm p-1">
                  <ApiKeyChecker />
                </div>
              </div>

              {/* Configuration Info */}
              <div className="rounded-2xl border border-[var(--border-color)] bg-[var(--bg-card)] p-6 space-y-6 shadow-sm">
                <h2 className="font-semibold text-sm flex items-center gap-2">
                  <div className="w-1 h-4 bg-gray-500 rounded-full" />
                  配置文件路径
                </h2>
                <div className="space-y-3 text-sm">
                  {[
                    { label: "API Key 配置", path: "/data/wechatDHA/ls_windsurf/local_secrets/.env.advisor", color: "text-blue-500" },
                    { label: "模型配置", path: "configs/advisor.yaml", color: "text-emerald-500" },
                    { label: "L1 训练数据", path: "timeline_out/agent_sft_l1.jsonl", color: "text-purple-500" },
                    { label: "L2 匿名数据", path: "timeline_out/agent_sft_l2.jsonl", color: "text-orange-500" },
                  ].map((item, index) => (
                    <div key={index} className="flex justify-between items-center py-3 border-b border-[var(--border-color)] last:border-0">
                      <span className="text-[var(--text-secondary)] font-medium">{item.label}</span>
                      <code className={`text-xs bg-[var(--bg-secondary)] px-3 py-1.5 rounded-lg ${item.color} font-mono border border-[var(--border-color)]`}>
                        {item.path}
                      </code>
                    </div>
                  ))}
                </div>
                <div className="pt-4 p-4 bg-blue-500/10 rounded-lg border border-blue-500/20">
                  <p className="text-xs text-blue-600 dark:text-blue-400">
                    <strong className="font-semibold">提示：</strong> 编辑 <code className="bg-blue-500/20 px-1 rounded">.env.advisor</code> 后运行{" "}
                    <code className="bg-blue-500/20 px-1 rounded">source .env.advisor</code> 加载到环境。
                  </p>
                </div>
              </div>

              {/* Privacy Policy */}
              <div className="rounded-2xl border border-[var(--border-color)] bg-[var(--bg-card)] p-6 space-y-4 shadow-sm">
                <h2 className="font-semibold text-sm flex items-center gap-2">
                  <div className="w-1 h-4 bg-emerald-500 rounded-full" />
                  隐私策略
                </h2>
                <div className="text-sm space-y-3">
                  <div className="flex items-start gap-3 p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/20">
                    <div className="w-2 h-2 bg-emerald-500 rounded-full mt-1.5 shrink-0" />
                    <div>
                      <strong className="text-emerald-600 dark:text-emerald-400">Phase 2 云端分析</strong>
                      <p className="text-[var(--text-secondary)] mt-1">使用 L2（匿名化）数据，云端只看到 ME/OTHER</p>
                    </div>
                  </div>
                  <div className="flex items-start gap-3 p-3 rounded-lg bg-blue-500/10 border border-blue-500/20">
                    <div className="w-2 h-2 bg-blue-500 rounded-full mt-1.5 shrink-0" />
                    <div>
                      <strong className="text-blue-600 dark:text-blue-400">Phase 6 本地训练</strong>
                      <p className="text-[var(--text-secondary)] mt-1">使用 L1（真实姓名）数据，数据不离开本机</p>
                    </div>
                  </div>
                  <div className="flex items-start gap-3 p-3 rounded-lg bg-purple-500/10 border border-purple-500/20">
                    <div className="w-2 h-2 bg-purple-500 rounded-full mt-1.5 shrink-0" />
                    <div>
                      <strong className="text-purple-600 dark:text-purple-400">SafetyLayer P0</strong>
                      <p className="text-[var(--text-secondary)] mt-1">云端 rationale_private 不注入本地上下文</p>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}

          {activeNav === 'dual-mirror' && (
            <div className="flex-1 p-8">
              <div className="h-full rounded-2xl border border-dashed border-[var(--border-color)] bg-[var(--bg-card)]/70" />
            </div>
          )}

          {activeNav === 'communication-status' && (
            <div className="flex-1 p-8">
              <div className="h-full rounded-2xl border border-dashed border-[var(--border-color)] bg-[var(--bg-card)]/70" />
            </div>
          )}

          {activeNav === 'roundtable' && (
            <div className="flex-1 p-8">
              <div className="h-full rounded-2xl border border-dashed border-[var(--border-color)] bg-[var(--bg-card)]/70" />
            </div>
          )}

          {activeNav === 'knowledge-center' && (
            <div className="flex-1 p-8">
              <div className="h-full rounded-2xl border border-dashed border-[var(--border-color)] bg-[var(--bg-card)]/70" />
            </div>
          )}
        </main>
      </div>
    </div>
  )
}

export default App
