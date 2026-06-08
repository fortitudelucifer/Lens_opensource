import { X, PhoneCall, AlertCircle, HeartHandshake } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'

interface EmergencyModalProps {
  isOpen: boolean
  onClose: () => void
}

export function EmergencyModal({ isOpen, onClose }: EmergencyModalProps) {
  return (
    <AnimatePresence>
      {isOpen && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="fixed inset-0 bg-black/60 backdrop-blur-sm z-[200]"
          />
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 10 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 10 }}
            className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 w-full max-w-md bg-[var(--bg-card)] border border-[var(--border-color)] rounded-2xl shadow-2xl z-[200] overflow-hidden"
          >
            <div className="bg-red-500/10 border-b border-red-500/20 px-6 py-4 flex items-start justify-between">
              <div className="flex items-center gap-3">
                <div className="p-2 bg-red-500/20 rounded-xl text-red-500">
                  <AlertCircle className="w-6 h-6" />
                </div>
                <div>
                  <h2 className="text-lg font-bold text-[var(--text-primary)]">紧急求助与支持</h2>
                  <p className="text-xs text-[var(--text-secondary)] mt-0.5">当您感到无法承受或有危机情况时，请立即联络专业人士</p>
                </div>
              </div>
              <button
                onClick={onClose}
                className="text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors p-1"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="p-6 space-y-6">
              <div className="space-y-4">
                <h3 className="text-sm font-semibold text-[var(--text-primary)] flex items-center gap-2">
                  <PhoneCall className="w-4 h-4 text-emerald-500" /> 24小时全国干预热线
                </h3>
                <div className="bg-[var(--bg-secondary)] rounded-xl p-4 border border-[var(--border-color)]">
                  <div className="text-2xl font-bold tracking-wider text-emerald-600 dark:text-emerald-400 mb-1">
                    400-161-9995
                  </div>
                  <p className="text-xs text-[var(--text-muted)]">
                    希望24小时心理危机干预热线（此号码仅供参考，请根据您所在的具体省市拨打当地专业机构电话，如 120 医疗急救 / 110 报警求助）
                  </p>
                </div>
              </div>

              <div className="space-y-3">
                <h3 className="text-sm font-semibold text-[var(--text-primary)] flex items-center gap-2">
                  <HeartHandshake className="w-4 h-4 text-violet-500" /> 获取帮助指南
                </h3>
               <ul className="text-sm text-[var(--text-secondary)] space-y-2 list-disc list-inside bg-[var(--bg-secondary)]/50 p-4 rounded-xl">
                  <li>保持安全，不要做出任何冲动性伤害行为。</li>
                  <li>联系身边可以信任的家人或朋友，告诉他们您现在的感受。</li>
                  <li>如果您认为自己无法控制可能发生的危险，请立即前往最近的急诊室。</li>
                </ul>
              </div>
            </div>

            <div className="p-4 bg-[var(--bg-secondary)] border-t border-[var(--border-color)] flex justify-end">
              <button
                onClick={onClose}
                className="px-6 py-2 bg-[var(--bg-card)] border border-[var(--border-color)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-secondary)] rounded-xl text-sm font-semibold transition-colors"
              >
                我已了解，关闭
              </button>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  )
}
