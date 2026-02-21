import { Bell, Search, User } from 'lucide-react'

interface TopNavProps {
  sidebarCollapsed: boolean
}

export function TopNav({ sidebarCollapsed }: TopNavProps) {
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
            placeholder="搜索记录、联系人..."
            className="w-full h-10 pl-10 pr-4 bg-[var(--bg-secondary)] border border-transparent focus:border-emerald-500/30 rounded-xl text-sm transition-all focus:bg-[var(--bg-card)] outline-none"
          />
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
