import { useState, useRef, useEffect } from 'react'
import { MoreHorizontal, Edit2, Trash2, Check, X } from 'lucide-react'

export interface SessionOptionsProps {
  sessionId: string
  initialTitle: string
  onRename: (id: string, newTitle: string) => Promise<void>
  onDelete: (id: string) => Promise<void>
  className?: string
}

export function SessionOptions({ sessionId, initialTitle, onRename, onDelete, className = '' }: SessionOptionsProps) {
  const [open, setOpen] = useState(false)
  const [isRenaming, setIsRenaming] = useState(false)
  const [isDeleting, setIsDeleting] = useState(false)
  const [title, setTitle] = useState(initialTitle)
  const [working, setWorking] = useState(false)
  
  const menuRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setOpen(false)
        setIsDeleting(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  useEffect(() => {
    if (isRenaming && inputRef.current) {
      inputRef.current.focus()
    }
  }, [isRenaming])

  const handleRenameConfirm = async () => {
    if (title.trim() === '' || title.trim() === initialTitle) {
      setIsRenaming(false)
      setTitle(initialTitle)
      return
    }
    setWorking(true)
    try {
      await onRename(sessionId, title.trim())
      setIsRenaming(false)
    } catch {
      setTitle(initialTitle)
    } finally {
      setWorking(false)
    }
  }

  const handleDeleteConfirm = async () => {
    setWorking(true)
    try {
      await onDelete(sessionId)
    } finally {
      // Typically the parent component will handle removing it from UI, so we don't necessarily need to reset state here
      setWorking(false)
      setOpen(false)
    }
  }

  if (isRenaming) {
    return (
      <div className={`flex items-center gap-1 bg-[var(--bg-secondary)] rounded-md p-1 ${className}`} onClick={e => e.stopPropagation()}>
        <input 
          ref={inputRef}
          value={title}
          onChange={e => setTitle(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Enter') handleRenameConfirm()
            if (e.key === 'Escape') { setIsRenaming(false); setTitle(initialTitle) }
          }}
          disabled={working}
          className="bg-transparent border-none outline-none text-xs w-28 px-1 text-[var(--text-primary)] disabled:opacity-50"
        />
        <button onClick={handleRenameConfirm} disabled={working} className="p-1 hover:bg-emerald-500/20 text-emerald-500 rounded transition-colors disabled:opacity-50"><Check className="w-3 h-3" /></button>
        <button onClick={() => { setIsRenaming(false); setTitle(initialTitle) }} disabled={working} className="p-1 hover:bg-red-500/20 text-red-500 rounded transition-colors disabled:opacity-50"><X className="w-3 h-3" /></button>
      </div>
    )
  }

  return (
    <div className={`relative ${className}`} ref={menuRef} onClick={e => e.stopPropagation()}>
      <button 
        onClick={(e) => { e.preventDefault(); e.stopPropagation(); setOpen(!open); setIsDeleting(false) }}
        className="p-1.5 text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-secondary)] rounded-lg transition-colors opacity-0 group-hover:opacity-100 focus:opacity-100 data-[state=open]:opacity-100"
        data-state={open ? 'open' : 'closed'}
      >
        <MoreHorizontal className="w-4 h-4" />
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-1 w-32 rounded-xl border border-[var(--border-color)] bg-[var(--bg-card)] p-1 shadow-lg z-50 animate-in fade-in slide-in-from-top-2">
          {!isDeleting ? (
            <>
              <button 
                onClick={(e) => { e.preventDefault(); e.stopPropagation(); setIsRenaming(true); setOpen(false) }}
                className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-xs text-[var(--text-secondary)] transition-colors hover:bg-[var(--bg-secondary)] hover:text-[var(--text-primary)]"
              >
                <Edit2 className="h-3.5 w-3.5" /> 重命名
              </button>
              <button 
                onClick={(e) => { e.preventDefault(); e.stopPropagation(); setIsDeleting(true) }}
                className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-xs text-red-500/80 transition-colors hover:bg-red-500/10 hover:text-red-500"
              >
                <Trash2 className="h-3.5 w-3.5" /> 删除会话
              </button>
            </>
          ) : (
            <div className="p-2">
              <p className="text-xs text-center text-[var(--text-secondary)] mb-2">确定删除？</p>
              <div className="flex items-center gap-2">
                <button 
                  onClick={(e) => { e.preventDefault(); e.stopPropagation(); setOpen(false); setIsDeleting(false) }}
                  disabled={working}
                  className="flex-1 rounded-md px-2 py-1 text-xs bg-[var(--bg-secondary)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] disabled:opacity-50"
                >
                  取消
                </button>
                <button 
                  onClick={(e) => { e.preventDefault(); e.stopPropagation(); handleDeleteConfirm() }}
                  disabled={working}
                  className="flex-1 rounded-md px-2 py-1 text-xs bg-red-500 text-white hover:bg-red-600 disabled:opacity-50 flex justify-center"
                >
                  {working ? '...' : '删除'}
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
