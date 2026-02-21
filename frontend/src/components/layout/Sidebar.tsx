import { motion } from 'framer-motion'
import {
  LayoutDashboard,
  MessageSquare,
  Settings,
  Heart,
  Sun,
  Moon,
  ShieldCheck,
  PanelLeftClose,
  BadgeCheck,
  SplitSquareHorizontal,
  Activity,
  UsersRound,
  BookOpen,
} from 'lucide-react'
import type { NavItem } from '../../types'

interface SidebarProps {
  active: string
  setActive: (id: string) => void
  theme: 'light' | 'dark'
  toggleTheme: () => void
  collapsed: boolean
  onToggleCollapsed: () => void
}

const navItems: NavItem[] = [
  { id: 'consent', label: '交流测评与知情同意', icon: BadgeCheck, path: '/consent' },
  { id: 'dashboard', label: '总览', icon: LayoutDashboard, path: '/' },
  { id: 'chat', label: '沉浸式互动', icon: MessageSquare, path: '/chat' },
  { id: 'review', label: '审核', icon: ShieldCheck, path: '/review' },
  { id: 'settings', label: '设置', icon: Settings, path: '/settings' },
  { id: 'dual-mirror', label: '双镜对比', icon: SplitSquareHorizontal, path: '/dual-mirror' },
  { id: 'communication-status', label: '交流状态', icon: Activity, path: '/communication-status' },
  { id: 'roundtable', label: '圆桌讨论', icon: UsersRound, path: '/roundtable' },
  { id: 'knowledge-center', label: '知识中心', icon: BookOpen, path: '/knowledge-center' },
]

export function Sidebar({ active, setActive, theme, toggleTheme, collapsed, onToggleCollapsed }: SidebarProps) {
  return (
    <div
      className={`fixed inset-y-0 left-0 w-64 glass-sidebar flex flex-col z-40 transition-transform duration-300 ${
        collapsed ? '-translate-x-full' : 'translate-x-0'
      }`}
    >
      {/* Logo */}
      <div className="h-16 flex items-center justify-between px-6 border-b border-[var(--border-color)]">
        <div className="flex items-center gap-3 min-w-0">
          <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-emerald-500/20 to-teal-500/20 flex items-center justify-center border border-[var(--border-color)]">
            <Heart className="w-4 h-4 text-emerald-500" />
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
            </button>
          )
        })}
      </div>

      {/* Footer / Theme Toggle */}
      <div className="p-4 border-t border-[var(--border-color)]">
        <button
          onClick={toggleTheme}
          className="w-full flex items-center justify-between px-4 py-3 rounded-xl hover:bg-[var(--bg-secondary)] transition-colors text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
        >
          <span className="font-medium">主题</span>
          {theme === 'dark' ? <Moon className="w-4 h-4" /> : <Sun className="w-4 h-4" />}
        </button>
      </div>
    </div>
  )
}
