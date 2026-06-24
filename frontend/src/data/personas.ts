/**
 * 圆桌讨论专用 persona 定义
 *
 * 对齐 Lens 现有 `constants.ts` 的 9 persona id；扩展 MP 评审方案推荐的
 *   - `subtitle`（流派标签）
 *   - `philosophy`（流派信条）
 *   - `PERSONA_COLOR_CLASSES`（Tailwind JIT 安全枚举）
 *   - `QUICK_PRESETS`（3 组一键预设）
 *
 * 与 `@/constants.ts` 的 `PERSONAS` 并存 — 后者给 chat/arena 页面继续使用，
 * 这里是圆桌讨论的 source of truth。
 */

import {
  Sparkles,
  Heart,
  Brain,
  HeartHandshake,
  UsersRound,
  Network,
  Lightbulb,
  Target,
  Globe,
  type LucideIcon,
} from 'lucide-react'
import type { PersonaType } from '@/types'

export type PersonaId = PersonaType
export type PersonaColor =
  | 'slate'
  | 'emerald'
  | 'violet'
  | 'pink'
  | 'orange'
  | 'teal'
  | 'indigo'
  | 'amber'
  | 'rose'

export type PersonaCategory = 'psychology' | 'interdisciplinary'

export interface RoundtablePersona {
  id: PersonaId
  name: string
  subtitle: string
  philosophy: string
  color: PersonaColor
  hex: string
  /** Lucide icon · 作为头像左上角装饰 / emoji 渲染失败时 fallback */
  icon: LucideIcon
  /**
   * D7.2.a · persona 头像 emoji（执行方案指定映射）
   * PersonaCard / AgentMessage 主头像位展示；丢失时润备用 icon
   */
  emoji: string
  description: string
  category: PersonaCategory
}

export const PERSONAS: RoundtablePersona[] = [
  {
    id: 'neutral',
    name: '中立顾问',
    subtitle: '客观 · 理性',
    philosophy: '让我们先看清楚正在发生什么',
    color: 'slate',
    hex: '#64748b',
    icon: Sparkles,
    emoji: '🧭',
    description: '客观理性，帮助你理清思绪，分析关系动态与沟通模式',
    category: 'psychology',
  },
  {
    id: 'supportive',
    name: '支持性顾问',
    subtitle: '温暖 · 陪伴',
    philosophy: '先停在这里陪你一会',
    color: 'emerald',
    hex: '#10b981',
    icon: Heart,
    emoji: '🤗',
    description: '温暖包容，给你情感支持，关注你的感受与情绪验证',
    category: 'psychology',
  },
  {
    id: 'psychoanalytic',
    name: '精神分析顾问',
    subtitle: '潜意识 · 防御',
    philosophy: '你感受到的，可能指向更深处',
    color: 'violet',
    hex: '#8b5cf6',
    icon: Brain,
    emoji: '🔍',
    description: '深度挖掘，探索潜意识防御机制与童年依附模式',
    category: 'psychology',
  },
  {
    id: 'eft',
    name: 'EFT 情绪聚焦',
    subtitle: '依恋 · 追逃',
    philosophy: '每个行为背后，都有一个想被看见的需求',
    color: 'pink',
    hex: '#ec4899',
    icon: HeartHandshake,
    emoji: '💗',
    description: '基于情绪聚焦疗法，探索依恋需求与追逃互动循环',
    category: 'psychology',
  },
  {
    id: 'bowen',
    name: '家庭系统顾问',
    subtitle: '代际 · 边界',
    philosophy: '你不只是你自己 — 你携带着家族的剧本',
    color: 'orange',
    hex: '#f97316',
    icon: UsersRound,
    emoji: '🌳',
    description: '基于 Bowen 家庭系统理论，分析代际模式与三角关系',
    category: 'psychology',
  },
  {
    id: 'sociology',
    name: '社会学视角',
    subtitle: '结构 · 权力',
    philosophy: '亲密关系也是一场社会剧',
    color: 'teal',
    hex: '#14b8a6',
    icon: Network,
    emoji: '🌐',
    description: '从社会结构出发，洞察关系中的权力场域、印象管理与制度性约束',
    category: 'interdisciplinary',
  },
  {
    id: 'philosophy',
    name: '哲学视角',
    subtitle: '存在 · 追问',
    philosophy: '为什么这件事让你这样？',
    color: 'indigo',
    hex: '#6366f1',
    icon: Lightbulb,
    emoji: '🤔',
    description: '苏格拉底式追问，引导你用存在主义、现象学、实用主义反思关系',
    category: 'interdisciplinary',
  },
  {
    id: 'game_theory',
    name: '博弈论视角',
    subtitle: '博弈 · 偏差',
    philosophy: '每一步选择都在影响下一步',
    color: 'amber',
    hex: '#f59e0b',
    icon: Target,
    emoji: '♟️',
    description: '理性分析关系博弈结构，识别沉没成本、损失厌恶等认知偏差',
    category: 'interdisciplinary',
  },
  {
    id: 'cultural',
    name: '文化视角',
    subtitle: '脚本 · 仪式',
    philosophy: '你以为是个人选择，其实是文化剧本',
    color: 'rose',
    hex: '#f43f5e',
    icon: Globe,
    emoji: '🏮',
    description: '关注文化脚本如何塑造关系期待，深入差序格局、代际责任与仪式象征',
    category: 'interdisciplinary',
  },
]

/**
 * Tailwind JIT 安全的 persona 色彩枚举
 *
 * 动态拼 `bg-${color}-100` 会被 Tailwind JIT purge — 必须**静态枚举**所有
 * class 字符串才能在产物中保留。这是 shadcn/ui 社区公认的最佳实践。
 */
export interface PersonaColorClasses {
  /** 卡片背景 */
  bg: string
  /** icon 填充色 */
  fg: string
  /** 激活态 ring */
  ring: string
  /** 边框 */
  border: string
  /** 标题文字色 */
  text: string
  /** 强调色（打字机游标等） */
  accent: string
  /**
   * Day 7 · D7.2.d · 文字色变体（与 accent 同色系但作为 text color，用于 currentColor 驱动 filter:drop-shadow）
   * 目的：让 typing 状态的 accent line 在脉动时光晕色跟随 persona 而非默认 foreground。
   */
  accentText: string
}

export const PERSONA_COLOR_CLASSES: Record<PersonaColor, PersonaColorClasses> = {
  slate: {
    bg: 'bg-slate-100 dark:bg-slate-500/15',
    fg: 'text-slate-600 dark:text-slate-300',
    ring: 'ring-slate-400/60 dark:ring-slate-400/40',
    border: 'border-slate-200/80 dark:border-slate-500/30',
    text: 'text-slate-700 dark:text-slate-200',
    accent: 'bg-slate-500 dark:bg-slate-400',
    accentText: 'text-slate-500 dark:text-slate-400',
  },
  emerald: {
    bg: 'bg-emerald-100 dark:bg-emerald-500/15',
    fg: 'text-emerald-600 dark:text-emerald-300',
    ring: 'ring-emerald-400/60 dark:ring-emerald-400/40',
    border: 'border-emerald-200/80 dark:border-emerald-500/30',
    text: 'text-emerald-700 dark:text-emerald-200',
    accent: 'bg-emerald-500 dark:bg-emerald-400',
    accentText: 'text-emerald-500 dark:text-emerald-400',
  },
  violet: {
    bg: 'bg-violet-100 dark:bg-violet-500/15',
    fg: 'text-violet-600 dark:text-violet-300',
    ring: 'ring-violet-400/60 dark:ring-violet-400/40',
    border: 'border-violet-200/80 dark:border-violet-500/30',
    text: 'text-violet-700 dark:text-violet-200',
    accent: 'bg-violet-500 dark:bg-violet-400',
    accentText: 'text-violet-500 dark:text-violet-400',
  },
  pink: {
    bg: 'bg-pink-100 dark:bg-pink-500/15',
    fg: 'text-pink-600 dark:text-pink-300',
    ring: 'ring-pink-400/60 dark:ring-pink-400/40',
    border: 'border-pink-200/80 dark:border-pink-500/30',
    text: 'text-pink-700 dark:text-pink-200',
    accent: 'bg-pink-500 dark:bg-pink-400',
    accentText: 'text-pink-500 dark:text-pink-400',
  },
  orange: {
    bg: 'bg-orange-100 dark:bg-orange-500/15',
    fg: 'text-orange-600 dark:text-orange-300',
    ring: 'ring-orange-400/60 dark:ring-orange-400/40',
    border: 'border-orange-200/80 dark:border-orange-500/30',
    text: 'text-orange-700 dark:text-orange-200',
    accent: 'bg-orange-500 dark:bg-orange-400',
    accentText: 'text-orange-500 dark:text-orange-400',
  },
  teal: {
    bg: 'bg-teal-100 dark:bg-teal-500/15',
    fg: 'text-teal-600 dark:text-teal-300',
    ring: 'ring-teal-400/60 dark:ring-teal-400/40',
    border: 'border-teal-200/80 dark:border-teal-500/30',
    text: 'text-teal-700 dark:text-teal-200',
    accent: 'bg-teal-500 dark:bg-teal-400',
    accentText: 'text-teal-500 dark:text-teal-400',
  },
  indigo: {
    bg: 'bg-indigo-100 dark:bg-indigo-500/15',
    fg: 'text-indigo-600 dark:text-indigo-300',
    ring: 'ring-indigo-400/60 dark:ring-indigo-400/40',
    border: 'border-indigo-200/80 dark:border-indigo-500/30',
    text: 'text-indigo-700 dark:text-indigo-200',
    accent: 'bg-indigo-500 dark:bg-indigo-400',
    accentText: 'text-indigo-500 dark:text-indigo-400',
  },
  amber: {
    bg: 'bg-amber-100 dark:bg-amber-500/15',
    fg: 'text-amber-600 dark:text-amber-300',
    ring: 'ring-amber-400/60 dark:ring-amber-400/40',
    border: 'border-amber-200/80 dark:border-amber-500/30',
    text: 'text-amber-700 dark:text-amber-200',
    accent: 'bg-amber-500 dark:bg-amber-400',
    accentText: 'text-amber-500 dark:text-amber-400',
  },
  rose: {
    bg: 'bg-rose-100 dark:bg-rose-500/15',
    fg: 'text-rose-600 dark:text-rose-300',
    ring: 'ring-rose-400/60 dark:ring-rose-400/40',
    border: 'border-rose-200/80 dark:border-rose-500/30',
    text: 'text-rose-700 dark:text-rose-200',
    accent: 'bg-rose-500 dark:bg-rose-400',
    accentText: 'text-rose-500 dark:text-rose-400',
  },
}

/** 一键预设组合（Setup 页 chips）*/
export interface QuickPreset {
  id: string
  label: string
  description: string
  ids: PersonaId[]
}

export const QUICK_PRESETS: QuickPreset[] = [
  {
    id: 'breakthrough',
    label: '🔥 破局行动组',
    description: '帮你在混乱中梳理对策、终止内耗',
    ids: ['neutral', 'game_theory', 'bowen'],
  },
  {
    id: 'embrace',
    label: '🫂 情绪拥抱组',
    description: '倾听你隐秘的委屈，接纳并陪你寻找意义',
    ids: ['supportive', 'eft', 'philosophy'],
  },
  {
    id: 'insight',
    label: '🔍 深度觉察组',
    description: '追根溯源，看见原生家庭与文化剧本里的你',
    ids: ['psychoanalytic', 'cultural', 'sociology'],
  },
]

/** 按 id 取 persona（找不到则 undefined） */
export function getPersona(id: PersonaId): RoundtablePersona | undefined {
  return PERSONAS.find((p) => p.id === id)
}

/** 批量取 persona（保持传入顺序） */
export function getPersonas(ids: readonly PersonaId[]): RoundtablePersona[] {
  return ids
    .map((id) => getPersona(id))
    .filter((p): p is RoundtablePersona => p !== undefined)
}
