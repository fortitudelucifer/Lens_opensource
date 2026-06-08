/**
 * §4.6 监督状态面板
 * 展示：身份边界、单视角提醒、情感依赖提醒
 */
import { useState } from 'react'
import { ChevronDown, ChevronRight, Info, AlertTriangle, SplitSquareHorizontal } from 'lucide-react'

interface SupervisionStatePanelProps {
  /** 是否显示单视角风险提醒 */
  singlePerspectiveRisk?: boolean
  /** 情感依赖等级：低/中/高 */
  attachmentLevel?: '低' | '中' | '高'
  /** 前往双镜对比回调 */
  onGoToArena?: () => void
  /** 默认是否折叠 */
  defaultCollapsed?: boolean
}

export function SupervisionStatePanel({
  singlePerspectiveRisk = false,
  attachmentLevel,
  onGoToArena,
  defaultCollapsed = false,
}: SupervisionStatePanelProps) {
  const [collapsed, setCollapsed] = useState(defaultCollapsed)

  return (
    <div className="rounded-xl border border-[var(--border-color)] bg-[var(--bg-secondary)]/50 overflow-hidden">
      {/* 身份边界（常驻，可折叠） */}
      <button
        type="button"
        onClick={() => setCollapsed(!collapsed)}
        className="w-full flex items-center gap-2 px-4 py-2.5 text-left text-sm hover:bg-[var(--bg-hover)] transition-colors"
      >
        {collapsed ? (
          <ChevronRight className="w-4 h-4 text-[var(--text-muted)] shrink-0" />
        ) : (
          <ChevronDown className="w-4 h-4 text-[var(--text-muted)] shrink-0" />
        )}
        <Info size={14} className="text-amber-500/80 shrink-0" />
        <span className="text-[var(--text-secondary)]">
          本 AI 仅供自我探索参考，非人类、非伴侣，建议结合双镜对比获取多视角
        </span>
      </button>

      {!collapsed && (
        <div className="px-4 pb-3 space-y-2 border-t border-[var(--border-color)]/50 pt-2">
          {singlePerspectiveRisk && (
            <div className="flex items-start gap-2 p-2 rounded-lg bg-amber-500/10 border border-amber-500/20">
              <AlertTriangle size={16} className="text-amber-500 shrink-0 mt-0.5" />
              <div className="flex-1 min-w-0">
                <p className="text-sm text-[var(--text-primary)]">
                  当前为单一顾问视角，不同流派可能有不同理解。
                </p>
                {onGoToArena && (
                  <button
                    type="button"
                    onClick={onGoToArena}
                    className="mt-2 flex items-center gap-1.5 text-xs font-medium text-amber-600 hover:text-amber-500"
                  >
                    <SplitSquareHorizontal size={14} />
                    前往双镜对比
                  </button>
                )}
              </div>
            </div>
          )}
          {(attachmentLevel === '高' || attachmentLevel === '中') && (
            <div className="flex items-start gap-2 p-2 rounded-lg bg-blue-500/10 border border-blue-500/20">
              <Info size={16} className="text-blue-500 shrink-0 mt-0.5" />
              <p className="text-sm text-[var(--text-primary)]">
                若感到过度依赖本对话，建议与亲友或专业咨询师交流。
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
