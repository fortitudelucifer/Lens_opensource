import type { LucideIcon } from 'lucide-react'

export type PersonaType = 'neutral' | 'supportive' | 'psychoanalytic' | 'eft' | 'bowen' | 'sociology' | 'philosophy' | 'game_theory' | 'cultural'
export type ChatMode = 'listen' | 'deep'

export interface Persona {
  id: PersonaType
  name: string
  color: string
  hex: string
  icon: LucideIcon
  description: string
}

export interface Session {
  id: number
  backendSessionId?: string
  title: string
  time: string
  personaId: PersonaType | string
  active: boolean
}

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: Date
  personaId: PersonaType | string
  thinking?: string
}

export interface NavItem {
  id: string
  label: string
  icon: LucideIcon
  path: string
}
