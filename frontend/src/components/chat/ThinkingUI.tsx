import { motion, AnimatePresence } from 'framer-motion'
import { BrainCircuit, ChevronDown, ChevronUp } from 'lucide-react'
import { useState } from 'react'

interface ThinkingUIProps {
  content: string
}

export function ThinkingUI({ content }: ThinkingUIProps) {
  const [expanded, setExpanded] = useState(false)

  if (!content) return null

  return (
    <div className="mb-3">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium text-[var(--text-secondary)] bg-[var(--bg-secondary)] border border-[var(--border-color)] hover:bg-[var(--bg-card-hover)] hover:text-[var(--text-primary)] transition-all duration-200"
      >
        <BrainCircuit size={14} className="text-violet-500 animate-pulse" />
        <span>模型思考过程</span>
        {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
      </button>

      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ opacity: 0, height: 0, marginTop: 0 }}
            animate={{ opacity: 1, height: 'auto', marginTop: 8 }}
            exit={{ opacity: 0, height: 0, marginTop: 0 }}
            className="overflow-hidden"
          >
            <div className="p-4 rounded-xl bg-[var(--bg-secondary)] border border-[var(--border-color)] border-l-2 border-l-violet-500/50 text-sm text-[var(--text-muted)] max-h-64 overflow-y-auto whitespace-pre-wrap font-mono leading-relaxed">
              {content}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
