import { Sparkles, Heart, Brain } from 'lucide-react'
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
]
