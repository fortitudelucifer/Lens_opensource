import { motion } from 'framer-motion'
import { ChevronRight } from 'lucide-react'
import lensLogo from '../assets/lens_logo_high_precision.svg'
import type { Persona } from '../types'
import { PERSONAS } from '../constants'

interface WelcomeScreenProps {
  onSelect: (persona: Persona) => void
}

export function WelcomeScreen({ onSelect }: WelcomeScreenProps) {
  return (
    <div className="flex-1 flex flex-col items-center justify-center p-8 min-h-full">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6 }}
        className="text-center mb-12"
      >
        <div className="inline-flex items-center justify-center w-24 h-24 rounded-2xl bg-gradient-to-br from-emerald-500/20 to-teal-500/20 border border-[var(--border-color)] mb-6 shadow-lg">
          <img src={lensLogo} alt="Lens 聆诉" className="w-16 h-16 object-contain" style={{ filter: 'brightness(0) saturate(100%) invert(42%) sepia(93%) saturate(1382%) hue-rotate(119deg) brightness(96%) contrast(92%) drop-shadow(0 0 4px rgba(16, 185, 129, 0.5))' }} />
        </div>
        <h1 className="text-4xl font-bold mb-4 tracking-tight text-[var(--text-primary)]">
          欢迎来到 Lens 聆诉
        </h1>
        <p className="text-lg text-[var(--text-muted)] max-w-xl mx-auto leading-relaxed">
          这里有三位不同风格的专业 AI 顾问。请选择最适合你当下需求的顾问开始互动。
        </p>
      </motion.div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 w-full max-w-5xl">
        {PERSONAS.map((persona, i) => {
          const Icon = persona.icon
          
          return (
            <motion.button
              key={persona.id}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.2 + i * 0.1, duration: 0.5 }}
              onClick={() => onSelect(persona)}
              className="group relative flex flex-col items-center p-8 rounded-3xl transition-all duration-300 glass-card text-center hover:-translate-y-2 hover:shadow-[0_20px_40px_rgba(0,0,0,0.1)]"
              style={{
                borderTopColor: `var(--border-color)`,
                borderBottomColor: `var(--border-color)`,
              }}
            >
              <div 
                className="absolute inset-0 opacity-0 group-hover:opacity-5 transition-opacity duration-500 rounded-3xl"
                style={{ background: persona.hex }}
              />
              
              <div 
                className="w-20 h-20 rounded-2xl flex items-center justify-center mb-6 transition-transform duration-500 group-hover:scale-110 group-hover:rotate-3 shadow-md"
                style={{ 
                  backgroundColor: `${persona.hex}15`,
                  border: `1px solid ${persona.hex}30` 
                }}
              >
                <Icon className="w-10 h-10" style={{ color: persona.hex }} />
              </div>
              
              <h3 className="text-xl font-bold mb-3 text-[var(--text-primary)] transition-colors group-hover:text-emerald-600">
                {persona.name}
              </h3>
              
              <p className="text-sm leading-relaxed text-[var(--text-secondary)] mb-8 flex-1">
                {persona.description}
              </p>
              
              <div className="flex items-center gap-2 text-sm font-medium transition-colors" style={{ color: persona.hex }}>
                选择该顾问 <ChevronRight className="w-4 h-4 group-hover:translate-x-1 transition-transform" />
              </div>
            </motion.button>
          )
        })}
      </div>
    </div>
  )
}
