import { motion } from 'framer-motion'
import { useTranslation } from 'react-i18next'

interface TypingIndicatorProps {
  /** 顾问名字；传入时文案为 `{personaName} 正在思考中...` */
  personaName?: string
  /** 完全自定义文案；优先级高于 personaName */
  text?: string
  /** Dots 与文案颜色（默认 emerald-500） */
  color?: string
  /** 紧凑模式：减小文案 margin，气泡高度与 ArenaPage 52px loader 对齐 */
  compact?: boolean
}

/**
 * 通用 Typing Indicator：三跳点 + 可选呼吸文案。
 *
 * 使用场景：
 * - ChatArea 首 token 未到或 thinking 模式下内容未流入时（content 为空）
 * - ArenaPage 双镜等待（视点建构中 / 深度对比中）
 */
export function TypingIndicator({
  personaName,
  text,
  color = '#10b981', // emerald-500
  compact = false,
}: TypingIndicatorProps) {
  const { t } = useTranslation()
  const label = text ?? (personaName ? t('chat.typingIndicator.advisorThinking', { name: personaName }) : t('chat.typingIndicator.thinking'))
  const dotColor = `${color}99` // ~60% alpha
  const dotSize = compact ? 'w-1.5 h-1.5' : 'w-2 h-2'

  return (
    <motion.div
      className="flex items-center gap-1.5"
      animate={{ opacity: [0.75, 1, 0.75] }}
      transition={{ duration: 1.5, repeat: Infinity, ease: 'easeInOut' }}
    >
      <motion.div
        className={`${dotSize} rounded-full`}
        style={{ backgroundColor: dotColor }}
        animate={{ y: [0, -4, 0] }}
        transition={{ duration: 0.6, repeat: Infinity, delay: 0 }}
      />
      <motion.div
        className={`${dotSize} rounded-full`}
        style={{ backgroundColor: dotColor }}
        animate={{ y: [0, -4, 0] }}
        transition={{ duration: 0.6, repeat: Infinity, delay: 0.2 }}
      />
      <motion.div
        className={`${dotSize} rounded-full`}
        style={{ backgroundColor: dotColor }}
        animate={{ y: [0, -4, 0] }}
        transition={{ duration: 0.6, repeat: Infinity, delay: 0.4 }}
      />
      <span
        className={`text-xs ml-2 ${compact ? '' : 'tracking-wide'}`}
        style={{ color: 'var(--text-muted)' }}
      >
        {label}
      </span>
    </motion.div>
  )
}
