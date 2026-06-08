import { useState } from 'react'
import { Send } from 'lucide-react'
import { motion } from 'framer-motion'
import { toast } from 'sonner'
import { api } from '../../lib/api'

interface FeedbackFormProps {
  /** 提交成功后执行（例如关闭 Modal） */
  onSuccess?: () => void
  /** textarea 高度类（默认 h-28，设置页可传 h-40） */
  textareaClassName?: string
  /** 占位符文案 */
  placeholder?: string
  /** 是否在提交成功后清空输入（默认 true） */
  clearOnSuccess?: boolean
  /** 按钮是否靠右对齐（默认 true） */
  alignRight?: boolean
}

/**
 * 反馈表单（textarea + 提交按钮）。由 FeedbackButton（FAB Modal）与设置页共用。
 *
 * 数据流向：`POST /api/feedback` → `advisor_out/feedback/ui_feedback.jsonl`
 * 失败时保留输入内容，便于重试。
 */
export function FeedbackForm({
  onSuccess,
  textareaClassName = 'h-28',
  placeholder = '在这里输入遇到的 Bug 或产品建议...',
  clearOnSuccess = true,
  alignRight = true,
}: FeedbackFormProps) {
  const [feedback, setFeedback] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!feedback.trim()) return

    setIsSubmitting(true)
    try {
      await api.submitFeedback({
        content: feedback.trim(),
        page: typeof window !== 'undefined' ? window.location.pathname : '',
        user_agent: typeof navigator !== 'undefined' ? navigator.userAgent : '',
      })
      toast.success('感谢您的反馈，我们已收到并会跟进处理。')
      if (clearOnSuccess) setFeedback('')
      onSuccess?.()
    } catch (err) {
      const msg = err instanceof Error ? err.message : '未知错误'
      toast.error(`提交失败：${msg.replace(/^API \d+:\s*/, '')}`)
      // 保留 feedback 内容，便于用户重试
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <textarea
        value={feedback}
        onChange={(e) => setFeedback(e.target.value)}
        placeholder={placeholder}
        className={`w-full ${textareaClassName} p-3 rounded-xl bg-[var(--bg-secondary)] border border-[var(--border-color)] text-sm text-[var(--text-primary)] placeholder-[var(--text-muted)] resize-none outline-none focus:border-emerald-500/50 focus:ring-2 focus:ring-emerald-500/10 transition-all scrollbar-thin`}
        required
      />
      <div className={`flex items-center gap-3 ${alignRight ? 'justify-end' : 'justify-start'}`}>
        <span className="text-[11px] text-[var(--text-muted)]">
          {feedback.length > 0 ? `${feedback.length} 字` : ''}
        </span>
        <motion.button
          whileHover={{ scale: 1.02 }}
          whileTap={{ scale: 0.98 }}
          disabled={!feedback.trim() || isSubmitting}
          type="submit"
          className="flex items-center gap-1.5 px-4 py-2 bg-emerald-500 hover:bg-emerald-600 text-white text-xs font-semibold rounded-lg transition-colors shadow-sm disabled:opacity-50 disabled:hover:bg-emerald-500"
        >
          {isSubmitting ? '提交中...' : <><Send className="w-3.5 h-3.5" /> 提交反馈</>}
        </motion.button>
      </div>
    </form>
  )
}
