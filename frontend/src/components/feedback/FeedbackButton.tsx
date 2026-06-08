import { useState } from 'react'
import { MessageSquarePlus, X } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import { FeedbackForm } from './FeedbackForm'

export function FeedbackButton() {
  const [isOpen, setIsOpen] = useState(false)

  return (
    <>
      <div className="fixed bottom-6 right-6 z-[100]">
        <motion.button
          whileHover={{ scale: 1.05 }}
          whileTap={{ scale: 0.95 }}
          onClick={() => setIsOpen(true)}
          className="w-12 h-12 bg-[var(--bg-card)] border border-[var(--border-color)] text-[var(--text-secondary)] hover:text-emerald-500 rounded-full flex items-center justify-center shadow-lg hover:shadow-xl transition-all"
          title="问题与建议反馈"
        >
          <MessageSquarePlus className="w-5 h-5" />
        </motion.button>
      </div>

      <AnimatePresence>
        {isOpen && (
          <>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setIsOpen(false)}
              className="fixed inset-0 bg-black/40 backdrop-blur-sm z-[150]"
            />
            <motion.div
              initial={{ opacity: 0, scale: 0.95, y: 20 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: 20 }}
              className="fixed bottom-24 right-6 w-[320px] bg-[var(--bg-card)] border border-[var(--border-color)] rounded-2xl shadow-2xl z-[150] overflow-hidden"
            >
              <div className="px-4 py-3 border-b border-[var(--border-color)] flex items-center justify-between bg-[var(--bg-secondary)]">
                <h3 className="text-sm font-semibold text-[var(--text-primary)]">问题与建议反馈</h3>
                <button
                  onClick={() => setIsOpen(false)}
                  className="text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
              
              <div className="p-4">
                <FeedbackForm onSuccess={() => setIsOpen(false)} />
              </div>
            </motion.div>
          </>
        )}
      </AnimatePresence>
    </>
  )
}
