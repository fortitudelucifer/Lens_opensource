import { useState } from 'react'
import { motion } from 'framer-motion'
import {
  LayoutDashboard,
  MessageSquare,
  Settings,
  Sun,
  Moon,
  ShieldCheck,
  PanelLeftClose,
  BadgeCheck,
  SplitSquareHorizontal,
  Activity,
  UsersRound,
  BookOpen,
  ClipboardList,
  Phone,
} from 'lucide-react'
import lensLogo from '../../assets/lens_logo_high_precision.svg'
import type { NavItem } from '../../types'
import { EmergencyModal } from '../safety/EmergencyModal'

interface SidebarProps {
  active: string
  setActive: (id: string) => void
  theme: 'light' | 'dark'
  toggleTheme: () => void
  collapsed: boolean
  onToggleCollapsed: () => void
}

const navItems: NavItem[] = [
  { id: 'consent', label: '知情同意', icon: BadgeCheck, path: '/consent' },
  { id: 'dashboard', label: '总览', icon: LayoutDashboard, path: '/' },
  { id: 'chat', label: '沉浸式互动', icon: MessageSquare, path: '/chat' },
  { id: 'arena', label: '双镜对比', icon: SplitSquareHorizontal, path: '/arena' },
  { id: 'assessment', label: '交流测评', icon: ClipboardList, path: '/assessment' },
  { id: 'review', label: '审核', icon: ShieldCheck, path: '/review' },
  { id: 'settings', label: '设置', icon: Settings, path: '/settings' },
  { id: 'communication-status', label: '交流状态', icon: Activity, path: '/communication-status' },
  { id: 'roundtable', label: '圆桌讨论', icon: UsersRound, path: '/roundtable' },
  { id: 'knowledge-center', label: '知识中心', icon: BookOpen, path: '/knowledge-center' },
]

export function Sidebar({ active, setActive, theme, toggleTheme, collapsed, onToggleCollapsed }: SidebarProps) {
  const [showEmergency, setShowEmergency] = useState(false)

  return (
    <>
    <div
      className={`fixed inset-y-0 left-0 w-64 glass-sidebar flex flex-col z-40 transition-transform duration-300 ${
        collapsed ? '-translate-x-full' : 'translate-x-0'
      }`}
    >
      {/* Logo */}
      <div className="h-16 flex items-center justify-between px-6 border-b border-[var(--border-color)]">
        <div className="flex items-center gap-3 min-w-0">
          <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-emerald-500/20 to-teal-500/20 flex items-center justify-center border border-[var(--border-color)]">
            <img src={lensLogo} alt="Lens 聆诉" className="w-7 h-7 object-contain" style={{ filter: 'brightness(0) saturate(100%) invert(42%) sepia(93%) saturate(1382%) hue-rotate(119deg) brightness(96%) contrast(92%) drop-shadow(0 0 2px rgba(16, 185, 129, 0.4))' }} />
          </div>
          <span className="font-bold tracking-wide truncate">Lens 聆诉</span>
        </div>
        <button
          onClick={onToggleCollapsed}
          className="ml-2 rounded-lg p-2 text-[var(--text-secondary)] transition-colors hover:bg-[var(--bg-secondary)] hover:text-[var(--text-primary)]"
          title="收起侧边栏"
          aria-label="收起侧边栏"
        >
          <PanelLeftClose className="h-4 w-4" />
        </button>
      </div>

      {/* Navigation */}
      <div className="flex-1 py-6 px-4 space-y-2">
        {navItems.map((item) => {
          const Icon = item.icon
          const isActive = active === item.id

          return (
            <button
              key={item.id}
              onClick={() => setActive(item.id)}
              className={`w-full flex items-center gap-3 px-4 py-3 rounded-xl transition-all duration-300 relative overflow-hidden group ${
                isActive ? 'text-emerald-500' : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
              }`}
            >
              {isActive && (
                <motion.div
                  layoutId="activeNav"
                  className="absolute inset-0 bg-emerald-500/10 dark:bg-emerald-500/20 rounded-xl"
                  initial={false}
                  transition={{ type: 'spring', stiffness: 300, damping: 30 }}
                />
              )}
              <Icon className={`w-5 h-5 relative z-10 ${isActive ? 'text-emerald-500' : ''}`} />
              <span className="font-medium relative z-10">{item.label}</span>
              {item.id === 'roundtable' && (
                <span
                  className="relative z-10 ml-auto inline-flex items-center rounded-md bg-amber-500/15 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-amber-600 dark:text-amber-300 ring-1 ring-amber-500/30"
                  title="圆桌讨论功能处于 Beta 阶段"
                >
                  Beta
                </span>
              )}
            </button>
          )
        })}
      </div>

      {/* Footer */}
      <div className="p-4 border-t border-[var(--border-color)] space-y-2">
        <button onClick={() => setShowEmergency(true)}
          className="flex items-center justify-center gap-2 w-full px-4 py-2 rounded-xl bg-red-500/10 border border-red-500/20 text-red-500 text-xs font-medium hover:bg-red-500/20 transition-colors">
          <Phone className="w-3.5 h-3.5" /> 紧急求助
        </button>
        <button
          onClick={toggleTheme}
          className="w-full flex items-center justify-between px-4 py-3 rounded-xl hover:bg-[var(--bg-secondary)] transition-colors text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
        >
          <span className="font-medium">主题</span>
          {theme === 'dark' ? <Moon className="w-4 h-4" /> : <Sun className="w-4 h-4" />}
        </button>
        <button
          onClick={() => setActive('privacy')}
          className={`w-full flex items-center justify-center gap-1.5 px-2 py-1.5 text-[11px] text-[var(--text-muted)] hover:text-emerald-500 transition-colors ${
            active === 'privacy' ? 'text-emerald-500' : ''
          }`}
        >
          <ShieldCheck className="w-3 h-3" />
          <span>隐私政策</span>
        </button>
      </div>
    </div>
    <EmergencyModal isOpen={showEmergency} onClose={() => setShowEmergency(false)} />
    </>
  )
}
