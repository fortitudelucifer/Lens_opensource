import { useCallback, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Toaster } from 'sonner'
import { Sidebar } from './components/layout/Sidebar'
import { TopNav } from './components/layout/TopNav'
import { Dashboard } from './pages/Dashboard'
import { ChatPage } from './pages/ChatPage'
import { WelcomeScreen } from './pages/WelcomeScreen'
import { ArenaPage } from './pages/ArenaPage'
import { FeedbackButton } from './components/feedback/FeedbackButton'
import { FeedbackForm } from './components/feedback/FeedbackForm'
import { DataEraseDialog } from './components/settings/DataEraseDialog'
import { AssessmentPage } from './pages/AssessmentPage'
import { CommunicationStatusPage } from './pages/CommunicationStatusPage'
import { KnowledgeCenterPage } from './pages/KnowledgeCenterPage'
import { ConsentPage } from './pages/ConsentPage'
import { PrivacyPage } from './pages/PrivacyPage'
import { RoundtablePage } from './pages/RoundtablePage'
import { RoundtableSessionPage } from './pages/RoundtableSessionPage'
import { useRoundtableStore } from './stores/useRoundtableStore'
import ModelSelector from './components/ModelSelector'
import ModelTester from './components/ModelTester'
import ApiKeyChecker from './components/ApiKeyChecker'
import ReviewPanel from './components/ReviewPanel'
import { CrisisBanner } from './components/safety/CrisisBanner'
import { ConsentModal } from './components/safety/ConsentModal'
import { PERSONAS } from './constants'
import type { Persona } from './types'
import type { ChatSessionSearchResult } from './lib/api'
import { PanelLeftOpen } from 'lucide-react'

/**
 * 圆桌讨论路由壳 · 按 `currentPhase` + `sessionId` 组合切换：
 *   - `setup` 且无 sessionId → `RoundtablePage`（选 persona + 输入问题）
 *   - `setup` 但 sessionId 仍存在 → **保持在** `RoundtableSessionPage`
 *     （`continue` 新一轮场景 · `archiveCurrentRoundAndReset` 会把 phase 置回
 *      'setup' 以重置当前轮 UI · 此时若 unmount SessionPage 会导致 SSE 关闭 ·
 *      第 2 轮 phase pipeline 无法启动 · D7.1.j++ bug fix · 2026-04-30）
 *   - 其他（phase1/phase2/phase3/done）→ `RoundtableSessionPage`
 * `onBack` 调 `resetSession` 回到 setup（会同时清空 sessionId）。
 * `onNavigateToChat` · 引导用户去沉浸式互动（轻量问题降级路径）。
 */
function RoundtableRouter({ onNavigateToChat }: { onNavigateToChat: () => void }) {
  const currentPhase = useRoundtableStore((s) => s.currentPhase)
  const sessionId = useRoundtableStore((s) => s.sessionId)
  const resetSession = useRoundtableStore((s) => s.resetSession)

  // D7.1.j++ · continue 新一轮时 currentPhase='setup' 但 sessionId 仍存在 · 不跳回 setup 页
  if (currentPhase === 'setup' && !sessionId) {
    return <RoundtablePage onNavigateToChat={onNavigateToChat} />
  }
  return <RoundtableSessionPage onBack={resetSession} />
}

// 导出供单测（__tests__/RoundtableRouter.test.tsx）使用 · 非 App 外部 API
export { RoundtableRouter as _RoundtableRouter }

export function App() {
  const { t } = useTranslation()
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
  const [showDataErase, setShowDataErase] = useState(false)

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
      setCurrentPath('/dashboard')
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
    if (currentPath.startsWith('/arena') || currentPath.startsWith('/dual-mirror')) return 'arena'
    if (currentPath.startsWith('/assessment')) return 'assessment'
    if (currentPath.startsWith('/communication-status')) return 'communication-status'
    if (currentPath.startsWith('/roundtable')) return 'roundtable'
    if (currentPath.startsWith('/knowledge-center')) return 'knowledge-center'
    if (currentPath.startsWith('/settings')) return 'settings'
    if (currentPath.startsWith('/privacy')) return 'privacy'
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
      arena: '/arena',
      'dual-mirror': '/arena',
      assessment: '/assessment',
      'communication-status': '/communication-status',
      roundtable: '/roundtable',
      'knowledge-center': '/knowledge-center',
      privacy: '/privacy',
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
          title={t('sidebar.expand')}
          aria-label={t('sidebar.expand')}
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
          {activeNav === 'consent' && <ConsentPage />}

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
            <div className="flex-1 overflow-y-auto scrollbar-fade p-6 space-y-8">
              {/* Header */}
              <div className="relative">
                <div className="absolute inset-0 bg-gradient-to-r from-emerald-500/10 to-teal-500/10 rounded-2xl" />
                <div className="relative p-6">
                  <h1 className="text-3xl font-bold tracking-tight text-[var(--text-primary)]">
                    {t('settings.title')}
                  </h1>
                  <p className="text-sm text-[var(--text-muted)] mt-2 max-w-2xl">
                    {t('settings.subtitle')}
                  </p>
                </div>
              </div>

              {/* Settings Sections */}
              <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
                <div className="space-y-6">
                  <div className="flex items-center gap-2">
                    <div className="w-1 h-6 bg-blue-500 rounded-full" />
                    <h2 className="text-lg font-semibold">{t('settings.modelSelection')}</h2>
                  </div>
                  <div className="bg-[var(--bg-card)] border border-[var(--border-color)] rounded-xl shadow-sm p-1">
                    <ModelSelector />
                  </div>
                </div>
                
                <div className="space-y-6">
                  <div className="flex items-center gap-2">
                    <div className="w-1 h-6 bg-green-500 rounded-full" />
                    <h2 className="text-lg font-semibold">{t('settings.connectionTest')}</h2>
                  </div>
                  <div className="bg-[var(--bg-card)] border border-[var(--border-color)] rounded-xl shadow-sm p-1">
                    <ModelTester />
                  </div>
                </div>
              </div>

              <div className="space-y-6">
                <div className="flex items-center gap-2">
                  <div className="w-1 h-6 bg-purple-500 rounded-full" />
                  <h2 className="text-lg font-semibold">{t('settings.apiKeyManagement')}</h2>
                </div>
                <div className="bg-[var(--bg-card)] border border-[var(--border-color)] rounded-xl shadow-sm p-1">
                  <ApiKeyChecker />
                </div>
              </div>

              {/* Configuration Info */}
              <div className="rounded-2xl border border-[var(--border-color)] bg-[var(--bg-card)] p-6 space-y-6 shadow-sm">
                <h2 className="font-semibold text-sm flex items-center gap-2">
                  <div className="w-1 h-4 bg-gray-500 rounded-full" />
                  {t('settings.configPaths')}
                </h2>
                <div className="space-y-3 text-sm">
                  {[
                    { label: t('settings.apiKeyConfig'), path: "local_secrets/.env.advisor", color: "text-blue-500" },
                    { label: t('settings.modelConfig'), path: "configs/advisor.yaml", color: "text-emerald-500" },
                    { label: t('settings.l1TrainingData'), path: "timeline_out/agent_sft_l1.jsonl", color: "text-purple-500" },
                    { label: t('settings.l2AnonymizedData'), path: "timeline_out/agent_sft_l2.jsonl", color: "text-orange-500" },
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
                    <strong className="font-semibold">{t('settings.envHint')}</strong>
                  </p>
                </div>
              </div>

              {/* Problem & Suggestion Feedback */}
              <div className="space-y-6">
                <div className="flex items-center gap-2">
                  <div className="w-1 h-6 bg-pink-500 rounded-full" />
                  <h2 className="text-lg font-semibold">{t('settings.feedbackTitle')}</h2>
                </div>
                <div className="rounded-2xl border border-[var(--border-color)] bg-[var(--bg-card)] p-6 space-y-4 shadow-sm">
                  <p className="text-sm text-[var(--text-secondary)] leading-relaxed">
                    {t('settings.feedbackDesc')}
                    <br />
                    <span className="text-xs text-[var(--text-muted)]">
                      {t('settings.feedbackPath')}
                    </span>
                  </p>
                  <FeedbackForm
                    textareaClassName="h-40"
                    placeholder={t('settings.feedbackPlaceholder')}
                    alignRight={false}
                  />
                </div>
              </div>

              {/* Data Erase (GDPR / CCPA compliance) */}
              <div className="space-y-6">
                <div className="flex items-center gap-2">
                  <div className="w-1 h-6 bg-red-500 rounded-full" />
                  <h2 className="text-lg font-semibold">{t('settings.dataErase.title')}</h2>
                </div>
                <div className="rounded-2xl border border-red-500/20 bg-[var(--bg-card)] p-6 space-y-4 shadow-sm">
                  <p className="text-sm text-[var(--text-secondary)] leading-relaxed">
                    {t('settings.dataErase.description')}
                  </p>
                  <p className="text-xs text-[var(--text-muted)]">
                    {t('settings.dataErase.note')}
                  </p>
                  <button
                    onClick={() => setShowDataErase(true)}
                    className="flex items-center gap-1.5 px-4 py-2 bg-red-500/10 hover:bg-red-500/20 border border-red-500/30 text-red-500 text-xs font-semibold rounded-lg transition-colors"
                  >
                    {t('settings.dataErase.button')}
                  </button>
                </div>
              </div>

              {/* Privacy Policy */}
              <div className="rounded-2xl border border-[var(--border-color)] bg-[var(--bg-card)] p-6 space-y-4 shadow-sm">
                <h2 className="font-semibold text-sm flex items-center gap-2">
                  <div className="w-1 h-4 bg-emerald-500 rounded-full" />
                  {t('settings.privacyPolicy')}
                </h2>
                <div className="text-sm space-y-3">
                  <div className="flex items-start gap-3 p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/20">
                    <div className="w-2 h-2 bg-emerald-500 rounded-full mt-1.5 shrink-0" />
                    <div>
                      <strong className="text-emerald-600 dark:text-emerald-400">{t('settings.phase2Cloud')}</strong>
                      <p className="text-[var(--text-secondary)] mt-1">{t('settings.phase2Desc')}</p>
                    </div>
                  </div>
                  <div className="flex items-start gap-3 p-3 rounded-lg bg-blue-500/10 border border-blue-500/20">
                    <div className="w-2 h-2 bg-blue-500 rounded-full mt-1.5 shrink-0" />
                    <div>
                      <strong className="text-blue-600 dark:text-blue-400">{t('settings.phase6Local')}</strong>
                      <p className="text-[var(--text-secondary)] mt-1">{t('settings.phase6Desc')}</p>
                    </div>
                  </div>
                  <div className="flex items-start gap-3 p-3 rounded-lg bg-purple-500/10 border border-purple-500/20">
                    <div className="w-2 h-2 bg-purple-500 rounded-full mt-1.5 shrink-0" />
                    <div>
                      <strong className="text-purple-600 dark:text-purple-400">{t('settings.safetyLayerP0')}</strong>
                      <p className="text-[var(--text-secondary)] mt-1">{t('settings.safetyLayerDesc')}</p>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}

          {activeNav === 'arena' && <ArenaPage />}

          {activeNav === 'assessment' && <AssessmentPage />}

          {activeNav === 'communication-status' && <CommunicationStatusPage />}

          {activeNav === 'roundtable' && (
            <div className="flex-1 overflow-y-auto scrollbar-fade">
              <RoundtableRouter onNavigateToChat={() => navigate('/chat/select-advisor')} />
            </div>
          )}

          {activeNav === 'knowledge-center' && <KnowledgeCenterPage />}

          {activeNav === 'privacy' && <PrivacyPage onBack={() => navigate('/settings')} />}
        </main>
      </div>

      <CrisisBanner />
      <ConsentModal />
      <FeedbackButton />
      <DataEraseDialog open={showDataErase} onClose={() => setShowDataErase(false)} />
      <Toaster position="top-center" richColors />
    </div>
  )
}

export default App
