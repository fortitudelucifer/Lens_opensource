import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { motion, AnimatePresence } from 'framer-motion'
import { AlertTriangle, X, Trash2, Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '../../lib/api'

const CONFIRM_PHRASE = '删除我的所有数据'

interface DataEraseDialogProps {
  open: boolean
  onClose: () => void
}

/**
 * 一键删除本地数据的二次确认 Modal
 *
 * 安全机制：
 *   1. 用户必须精确输入 "删除我的所有数据" 才能激活按钮
 *   2. 后端同样校验 confirm 短语（双重防护）
 *   3. 成功后清空 localStorage 并 2s 后 reload（用户看到 toast）
 */
export function DataEraseDialog({ open, onClose }: DataEraseDialogProps) {
  const { t } = useTranslation()
  const [confirmInput, setConfirmInput] = useState('')
  const [isDeleting, setIsDeleting] = useState(false)

  const canSubmit = confirmInput.trim() === CONFIRM_PHRASE && !isDeleting

  const handleErase = async () => {
    if (!canSubmit) return
    setIsDeleting(true)
    try {
      const res = await api.eraseAllUserData(confirmInput.trim())
      const kb = Math.round(res.total_bytes_removed / 1024)
      toast.success(
        t('dataErase.deleteSuccess', { items: res.total_items_removed, kb }),
        { duration: 2000 },
      )
      // 清空本地偏好（主题 / 上次模型等）
      try {
        localStorage.clear()
      } catch {
        // ignore
      }
      setTimeout(() => {
        window.location.reload()
      }, 2000)
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Error'
      toast.error(t('dataErase.deleteFailed', { msg: msg.replace(/^API \d+:\s*/, '') }))
      setIsDeleting(false)
    }
  }

  const handleClose = () => {
    if (isDeleting) return
    setConfirmInput('')
    onClose()
  }

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={handleClose}
            className="fixed inset-0 bg-black/60 backdrop-blur-sm z-[200]"
          />
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 20 }}
            className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 w-[90vw] max-w-md bg-[var(--bg-card)] border border-red-500/30 rounded-2xl shadow-2xl z-[201] overflow-hidden"
          >
            <div className="px-5 py-4 border-b border-[var(--border-color)] bg-red-500/5 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <div className="w-8 h-8 rounded-full bg-red-500/15 flex items-center justify-center">
                  <AlertTriangle className="w-4 h-4 text-red-500" />
                </div>
                <h3 className="text-sm font-semibold">{t('dataErase.title')}</h3>
              </div>
              <button
                onClick={handleClose}
                disabled={isDeleting}
                className="text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors disabled:opacity-30"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="p-5 space-y-4">
              <div className="text-sm text-[var(--text-secondary)] leading-relaxed space-y-2">
                <p className="font-medium text-[var(--text-primary)]">{t('dataErase.description')}</p>
                <ul className="list-disc pl-5 space-y-0.5 text-xs">
                  <li>{t('dataErase.items.chatSessions')}</li>
                  <li>{t('dataErase.items.arenaSessions')}</li>
                  <li>{t('dataErase.items.assessments')}</li>
                  <li>{t('dataErase.items.crisisRecords')}</li>
                  <li>{t('dataErase.items.feedback')}</li>
                  <li>{t('dataErase.items.preferences')}</li>
                </ul>
                <p className="text-xs text-[var(--text-muted)] pt-1">
                  {t('dataErase.retained')}
                </p>
              </div>

              <div className="p-3 rounded-lg bg-red-500/5 border border-red-500/20 text-xs text-red-500">
                {t('dataErase.warning')}
              </div>

              <div>
                <label className="text-xs text-[var(--text-secondary)] block mb-1.5">
                  {t('dataErase.confirmLabel')} <code className="bg-[var(--bg-secondary)] px-1.5 py-0.5 rounded text-red-500 font-mono">{CONFIRM_PHRASE}</code>
                </label>
                <input
                  type="text"
                  value={confirmInput}
                  onChange={(e) => setConfirmInput(e.target.value)}
                  disabled={isDeleting}
                  placeholder={CONFIRM_PHRASE}
                  autoFocus
                  className="w-full px-3 py-2 rounded-lg bg-[var(--bg-secondary)] border border-[var(--border-color)] text-sm text-[var(--text-primary)] placeholder-[var(--text-muted)] outline-none focus:border-red-500/50 focus:ring-2 focus:ring-red-500/10 transition-all disabled:opacity-50"
                />
              </div>

              <div className="flex items-center justify-end gap-2 pt-2">
                <button
                  onClick={handleClose}
                  disabled={isDeleting}
                  className="px-4 py-2 bg-[var(--bg-secondary)] hover:bg-[var(--bg-hover)] border border-[var(--border-color)] text-[var(--text-primary)] text-xs font-medium rounded-lg transition-colors disabled:opacity-50"
                >
                  {t('dataErase.cancel')}
                </button>
                <motion.button
                  whileHover={canSubmit ? { scale: 1.02 } : {}}
                  whileTap={canSubmit ? { scale: 0.98 } : {}}
                  disabled={!canSubmit}
                  onClick={handleErase}
                  className="flex items-center gap-1.5 px-4 py-2 bg-red-500 hover:bg-red-600 text-white text-xs font-semibold rounded-lg transition-colors shadow-sm disabled:opacity-30 disabled:cursor-not-allowed disabled:hover:bg-red-500"
                >
                  {isDeleting ? (
                    <><Loader2 className="w-3.5 h-3.5 animate-spin" /> {t('dataErase.deleting')}</>
                  ) : (
                    <><Trash2 className="w-3.5 h-3.5" /> {t('dataErase.confirmDelete')}</>
                  )}
                </motion.button>
              </div>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  )
}
