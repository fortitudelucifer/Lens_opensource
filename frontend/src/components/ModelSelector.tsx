import { useEffect, useState, useCallback } from "react"
import { useTranslation } from "react-i18next"
import { Save, Check, Loader2, Brain, ShieldCheck, MessageCircle, RefreshCw } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { api, type ModelPreferences, type AvailableModel } from "@/lib/api"

interface RoleConfig {
  key: "analysis" | "review" | "chat"
  label: string
  description: string
  icon: React.ElementType
  color: string
  filterRole: string
}

const ROLES: RoleConfig[] = [
  {
    key: "analysis",
    label: "Phase 2 Analysis",
    description: "Dialogue fragments → Cloud deep analysis",
    icon: Brain,
    color: "text-violet-600",
    filterRole: "analysis",
  },
  {
    key: "review",
    label: "Phase 3 Review",
    description: "AI-assisted quality review",
    icon: ShieldCheck,
    color: "text-sky-600",
    filterRole: "review",
  },
  {
    key: "chat",
    label: "Real-time Chat",
    description: "Model used for frontend chat",
    icon: MessageCircle,
    color: "text-emerald-600",
    filterRole: "chat",
  },
]

const backendLabels: Record<string, string> = {
  openai: "OpenAI",
  claude: "Claude",
  gemini: "Gemini",
  kimi: "Kimi",
  grok: "Grok",
  deepseek: "DeepSeek",
  qwen_local: "Qwen Local",
  qwen_cloud: "Qwen Cloud",
  glm: "GLM",
}

export default function ModelSelector() {
  const { t } = useTranslation()
  const [prefs, setPrefs] = useState<ModelPreferences | null>(null)
  const [available, setAvailable] = useState<AvailableModel[]>([])
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [p, a] = await Promise.all([
        api.getModelPreferences(),
        api.getAvailableModels(),
      ])
      setPrefs(p)
      setAvailable(a)
    } catch (e) {
      console.error("Failed to load model preferences:", e)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const handleChange = (role: RoleConfig["key"], backend: string) => {
    if (!prefs) return
    const model = available.find((m) => m.backend === backend)
    setPrefs({
      ...prefs,
      [`${role}_backend`]: backend,
      [`${role}_model`]: model?.model || "",
    } as ModelPreferences)
    setSaved(false)
  }

  const handleSave = async () => {
    if (!prefs) return
    setSaving(true)
    try {
      await api.setModelPreferences(prefs)
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } catch (e) {
      console.error("Failed to save:", e)
    } finally {
      setSaving(false)
    }
  }

  if (loading || !prefs) {
    return (
      <Card>
        <CardContent className="flex items-center justify-center py-12">
          <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
          <span className="ml-2 text-sm text-muted-foreground">{t('modelSelector.loading')}</span>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="text-base">{t('modelSelector.title')}</CardTitle>
            <p className="text-xs text-muted-foreground mt-1">
              {t('modelSelector.description')}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={load} className="h-8 px-2">
              <RefreshCw className="w-3.5 h-3.5" />
            </Button>
            <Button
              size="sm"
              onClick={handleSave}
              disabled={saving || saved}
              className="h-8 gap-1.5"
            >
              {saving ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : saved ? (
                <Check className="w-3.5 h-3.5" />
              ) : (
                <Save className="w-3.5 h-3.5" />
              )}
              <span className="text-xs">{saved ? t('modelSelector.saved') : t('modelSelector.save')}</span>
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {ROLES.map((role) => {
          const Icon = role.icon
          const backendKey = `${role.key}_backend` as keyof ModelPreferences
          const currentBackend = prefs[backendKey]
          const candidates = available.filter((m) =>
            m.suitable_for.includes(role.filterRole)
          )
          const currentModel = available.find((m) => m.backend === currentBackend)

          return (
            <div
              key={role.key}
              className="rounded-lg border border-border p-4 space-y-3"
            >
              <div className="flex items-center gap-2">
                <Icon className={`w-4 h-4 ${role.color}`} />
                <span className="font-medium text-sm">{role.label}</span>
                <span className="text-xs text-muted-foreground">— {role.description}</span>
              </div>

              <div className="flex items-center gap-3">
                <select
                  value={currentBackend}
                  onChange={(e) => handleChange(role.key, e.target.value)}
                  className="flex-1 h-9 rounded-md border border-border bg-background px-3 text-sm outline-none focus:ring-2 focus:ring-ring focus:ring-offset-1 transition-colors"
                >
                  {candidates.length === 0 && (
                    <option value="">{t('modelSelector.noBackend')}</option>
                  )}
                  {candidates.map((m) => (
                    <option key={m.backend} value={m.backend}>
                      {backendLabels[m.backend] || m.backend} — {m.model}
                    </option>
                  ))}
                </select>

                {currentModel && (
                  <Badge variant="secondary" className="text-[10px] shrink-0">
                    {currentModel.base_url === "(默认)" ? t('modelSelector.official') : t('modelSelector.proxy')}
                  </Badge>
                )}
              </div>

              {currentModel && (
                <div className="text-[11px] text-muted-foreground pl-1">
                  {t('modelSelector.modelLabel')} <code className="bg-muted px-1 py-0.5 rounded">{currentModel.model}</code>
                  {currentModel.base_url !== "(默认)" && (
                    <span className="ml-2">
                      via <code className="bg-muted px-1 py-0.5 rounded">{currentModel.base_url}</code>
                    </span>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </CardContent>
    </Card>
  )
}
