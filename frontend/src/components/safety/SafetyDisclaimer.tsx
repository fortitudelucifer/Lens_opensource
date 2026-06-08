import { Info } from 'lucide-react'

export function SafetyDisclaimer() {
  return (
    <div className="flex items-center justify-center gap-2 px-4 py-2 text-xs text-[var(--text-muted)] bg-[var(--bg-secondary)]/50 border-b border-[var(--border-color)]">
      <Info size={12} className="shrink-0 text-amber-500/70" />
      <span>本 AI 仅供自我探索参考，不能替代专业心理咨询或治疗。如需紧急帮助请拨打 400-161-9995</span>
    </div>
  )
}
