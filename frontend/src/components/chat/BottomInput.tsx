import { motion } from 'framer-motion'
import { Send, Paperclip } from 'lucide-react'
import { useState, useRef, useEffect } from 'react'

interface BottomInputProps {
  onSend: (content: string) => void
  disabled?: boolean
  isThinking?: boolean
}

export function BottomInput({ onSend, disabled, isThinking }: BottomInputProps) {
  const [content, setContent] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  // Auto-resize textarea
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
      textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 200) + 'px'
    }
  }, [content])

  const handleSend = () => {
    if (content.trim() && !disabled) {
      onSend(content.trim())
      setContent('')
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="p-4 md:p-6 bg-[var(--bg-primary)] border-t border-[var(--border-color)] relative z-20">
      <div className="max-w-5xl mx-auto relative flex items-end gap-3">
        <button
          disabled={disabled}
          className="p-3.5 rounded-2xl bg-[var(--bg-secondary)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-card)] border border-[var(--border-color)] transition-all flex-shrink-0 disabled:opacity-50"
        >
          <Paperclip size={20} />
        </button>

        <div className="flex-1 relative bg-[var(--bg-card)] border border-[var(--border-color)] rounded-2xl shadow-sm focus-within:border-emerald-500/50 focus-within:ring-4 focus-within:ring-emerald-500/10 transition-all">
          <textarea
            ref={textareaRef}
            value={content}
            onChange={(e) => setContent(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={disabled}
            placeholder={isThinking ? '顾问正在思考中...' : '输入你的问题或感受 (Enter 发送, Shift+Enter 换行)'}
            className="w-full max-h-[200px] min-h-[56px] py-4 pl-5 pr-14 bg-transparent resize-none outline-none text-[var(--text-primary)] placeholder-[var(--text-muted)] scrollbar-thin disabled:opacity-50"
            rows={1}
          />

          <motion.button
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.95 }}
            onClick={handleSend}
            disabled={!content.trim() || disabled}
            className="absolute right-2 bottom-2 p-2.5 rounded-xl bg-gradient-to-br from-emerald-500 to-teal-600 text-white disabled:opacity-50 disabled:from-[var(--bg-secondary)] disabled:to-[var(--bg-secondary)] disabled:text-[var(--text-muted)] transition-all shadow-md disabled:shadow-none"
          >
            <Send size={18} className={content.trim() && !disabled ? 'translate-x-0.5 -translate-y-0.5' : ''} />
          </motion.button>
        </div>
      </div>
      <p className="text-center text-[10px] text-[var(--text-muted)] mt-3 hidden md:block">
        内容仅供参考，AI 顾问不能替代专业医疗建议。
      </p>
    </div>
  )
}
