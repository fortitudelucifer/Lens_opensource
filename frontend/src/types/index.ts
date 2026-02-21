import type { LucideIcon } from 'lucide-react'

export type PersonaType = 'neutral' | 'supportive' | 'psychoanalytic'
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
  title: string
  time: string
  personaId: PersonaType
  active: boolean
}

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: Date
  personaId: PersonaType
  thinking?: string
}

export interface NavItem {
  id: string
  label: string
  icon: LucideIcon
  path: string
}
