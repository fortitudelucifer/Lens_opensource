/**
 * 置信度 confidence 视觉分档（2026-04-19 · Day 5 方案①）
 *
 * 背景：LLM 自评 confidence 普遍落在 0.7-0.9 之间（心理安全区），
 * 纯百分比数字在心理场景里容易被用户过度解读（"80% 意味着我的问题不够严重吗？"）。
 *
 * 方案：同时展示「图标分档 + 百分比数字」——图标传递直觉，数字保留精度。
 *
 * 三档阈值（和 ChatGPT agent self-eval 分布经验对齐）：
 *   - `high`   · ≥ 0.85  实心星 · 高度契合
 *   - `medium` · 0.65-0.85  空心星 · 稳定视角
 *   - `low`    · < 0.65  圆点 · 尝试性视角
 */

export type ConfidenceTier = 'high' | 'medium' | 'low'

export interface ConfidenceMeta {
  tier: ConfidenceTier
  /** 中文 label，用于 tooltip / aria-label */
  label: string
  /** 百分比整数 0-100 */
  percent: number
}

export function getConfidenceMeta(raw: number | null | undefined): ConfidenceMeta | null {
  if (typeof raw !== 'number' || Number.isNaN(raw)) return null
  const clamped = Math.max(0, Math.min(1, raw))
  const percent = Math.round(clamped * 100)
  let tier: ConfidenceTier
  let label: string
  if (clamped >= 0.85) {
    tier = 'high'
    label = '高度契合'
  } else if (clamped >= 0.65) {
    tier = 'medium'
    label = '稳定视角'
  } else {
    tier = 'low'
    label = '尝试性视角'
  }
  return { tier, label, percent }
}
