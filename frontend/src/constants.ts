import { Sparkles, Heart, Brain, HeartHandshake, UsersRound, Network, Lightbulb, Target, Globe } from 'lucide-react'
import type { Persona } from './types'

export const PERSONAS: Persona[] = [
  {
    id: 'neutral',
    name: '中立顾问',
    color: 'sky-400',
    hex: '#38bdf8',
    icon: Sparkles,
    description: '客观理性，帮助你理清思绪，分析关系动态与沟通模式',
  },
  {
    id: 'supportive',
    name: '支持性顾问',
    color: 'emerald-400',
    hex: '#34d399',
    icon: Heart,
    description: '温暖包容，给你情感支持，关注你的感受与情绪验证',
  },
  {
    id: 'psychoanalytic',
    name: '精神分析顾问',
    color: 'violet-400',
    hex: '#a78bfa',
    icon: Brain,
    description: '深度挖掘，探索潜意识防御机制与童年依附模式',
  },
  {
    id: 'eft',
    name: 'EFT 情绪聚焦',
    color: 'pink-400',
    hex: '#f472b6',
    icon: HeartHandshake,
    description: '基于情绪聚焦疗法，探索依恋需求与追逃互动循环',
  },
  {
    id: 'bowen',
    name: '家庭系统顾问',
    color: 'orange-400',
    hex: '#fb923c',
    icon: UsersRound,
    description: '基于 Bowen 家庭系统理论，分析代际模式与三角关系',
  },
  // ── S6 跨学科理论引擎 ──
  {
    id: 'sociology',
    name: '社会学视角',
    color: 'teal-400',
    hex: '#2dd4bf',
    icon: Network,
    description: '从社会结构出发，洞察关系中的权力场域、印象管理与制度性约束',
  },
  {
    id: 'philosophy',
    name: '哲学视角',
    color: 'indigo-400',
    hex: '#818cf8',
    icon: Lightbulb,
    description: '苏格拉底式追问，引导你用存在主义、现象学、实用主义反思关系',
  },
  {
    id: 'game_theory',
    name: '博弈论视角',
    color: 'amber-400',
    hex: '#fbbf24',
    icon: Target,
    description: '理性分析关系博弈结构，识别沉没成本、损失厌恶等认知偏差',
  },
  {
    id: 'cultural',
    name: '文化视角',
    color: 'rose-400',
    hex: '#fb7185',
    icon: Globe,
    description: '关注文化脚本如何塑造关系期待，深入差序格局、代际责任与仪式象征',
  },
]
