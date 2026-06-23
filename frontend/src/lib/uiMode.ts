// 用户 / 开发者 模式 —— 信息架构重排的骨架（见 docs/app/settings_reorganization_plan.md）
// 用户模式：普通用户/公开访客所见，运维内容隐藏。
// 开发者模式：额外显示运维台（流水线 + 模型 + API Key + 训练数据）。
export type UiMode = 'user' | 'developer'

export const DEFAULT_UI_MODE: UiMode = 'user'

// 仅在开发者模式可见的导航页（用户模式下隐藏并重定向）。
// 注：arena / communication-status 暂留用户可见，待产品确认后再决定是否归运维。
export const OPERATOR_NAV_IDS = new Set<string>(['dashboard', 'review'])

// 用户模式的默认落地页（替代运维 dashboard）。
export const USER_HOME_PATH = '/chat/select-advisor'

export function isOperatorNav(id: string): boolean {
  return OPERATOR_NAV_IDS.has(id)
}
