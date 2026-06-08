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
    <div className="flex-1 overflow-y-auto w-full" style={{ background: 'var(--bg-primary)' }}>
      <div className="min-h-full flex flex-col p-4 sm:p-8 w-full max-w-[1600px] mx-auto">
        {/* Spacer to push content down for centering, shrinks if height is small */}
        <div className="flex-grow flex-shrink"></div>

        <div className="flex flex-col items-center w-full py-8">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6 }}
            className="text-center mb-8 sm:mb-12 max-w-2xl mx-auto px-4"
          >
            <div className="inline-flex items-center justify-center w-20 h-20 sm:w-24 sm:h-24 rounded-2xl bg-gradient-to-br from-emerald-500/20 to-teal-500/20 border border-[var(--border-color)] mb-6 shadow-lg">
              <img src={lensLogo} alt="Lens 聆诉" className="w-12 h-12 sm:w-16 sm:h-16 object-contain" style={{ filter: 'brightness(0) saturate(100%) invert(42%) sepia(93%) saturate(1382%) hue-rotate(119deg) brightness(96%) contrast(92%) drop-shadow(0 0 4px rgba(16, 185, 129, 0.5))' }} />
            </div>
            <h1 className="text-3xl sm:text-4xl lg:text-5xl font-bold mb-4 tracking-tight text-[var(--text-primary)]">
              欢迎来到 Lens 聆诉
            </h1>
            <p className="text-base sm:text-lg lg:text-xl text-[var(--text-muted)] leading-relaxed">
              这里有九位不同风格的专业 AI / 跨学科顾问。请选择最适合你当下需求的顾问开始互动。
            </p>
          </motion.div>

          <div className="flex flex-wrap justify-center gap-4 sm:gap-6 w-full max-w-[1400px]">
            {PERSONAS.map((persona, i) => {
          const Icon = persona.icon

          return (
            <motion.button
              key={persona.id}
              initial={{ opacity: 0, scale: 0.95, y: 10 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              transition={{ delay: 0.1 + i * 0.05, duration: 0.4 }}
              onClick={() => onSelect(persona)}
              className="group relative flex flex-col items-center p-6 sm:p-8 rounded-3xl transition-all duration-300 glass-card text-center hover:-translate-y-1.5 hover:shadow-[0_20px_40px_rgba(0,0,0,0.1)] w-full sm:w-[calc(50%-12px)] md:w-[calc(33.333%-16px)] lg:w-[calc(25%-18px)] xl:min-w-[200px] xl:max-w-[260px] flex-shrink-0"
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
                className="w-16 h-16 sm:w-20 sm:h-20 rounded-2xl flex items-center justify-center mb-4 sm:mb-6 transition-transform duration-500 group-hover:scale-110 group-hover:rotate-3 shadow-md shrink-0"
                style={{
                  backgroundColor: `${persona.hex}15`,
                  border: `1px solid ${persona.hex}30`
                }}
              >
                <Icon className="w-8 h-8 sm:w-10 sm:h-10" style={{ color: persona.hex }} />
              </div>

              <h3 className="text-lg sm:text-xl font-bold mb-2 sm:mb-3 text-[var(--text-primary)] transition-colors group-hover:text-emerald-600 break-words whitespace-normal px-2">
                {persona.name}
              </h3>

              <p className="text-xs sm:text-sm leading-relaxed text-[var(--text-secondary)] mb-6 sm:mb-8 flex-1 w-full break-words px-1">
                {persona.description}
              </p>

              <div className="flex justify-center items-center gap-2 text-xs sm:text-sm font-medium transition-colors w-full mt-auto" style={{ color: persona.hex }}>
                <span>选择该顾问</span> <ChevronRight className="w-4 h-4 group-hover:translate-x-1 transition-transform shrink-0" />
              </div>
            </motion.button>
          )
        })}
          </div>
        </div>

        {/* Spacer to push content up for centering */}
        <div className="flex-grow flex-shrink"></div>
      </div>
    </div>
  )
}
