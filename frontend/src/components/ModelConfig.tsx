import { useEffect, useState } from "react"
import { Cloud, Zap, Globe, Server, Brain, ShieldCheck, MessageCircle } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { api, type ModelInfo } from "@/lib/api"

const iconMap: Record<string, React.ElementType> = {
  openai: Globe, claude: Zap, gemini: Globe, kimi: Globe,
  grok: Zap, deepseek: Cloud, qwen_local: Server, qwen_cloud: Cloud, glm: Server,
}

const backendMeta: Record<string, { label: string; platform: string; role?: string }> = {
  openai:     { label: "OpenAI",   platform: "第三方代理",  role: "聊天" },
  claude:     { label: "Claude",   platform: "第三方代理",        role: "Phase 3 审核" },
  gemini:     { label: "Gemini",   platform: "第三方代理",        role: "聊天" },
  kimi:       { label: "Kimi",     platform: "第三方代理",        role: "聊天" },
  grok:       { label: "Grok",     platform: "第三方代理",        role: "聊天" },
  deepseek:   { label: "DeepSeek", platform: "第三方代理",        role: "聊天" },
  qwen_local: { label: "Qwen本地", platform: "本机",          role: "本地推理" },
  qwen_cloud: { label: "Qwen云端", platform: "第三方代理",        role: "Phase 2 分析" },
  glm:        { label: "GLM",      platform: "第三方代理",        role: "聊天" },
}

const roleIcon: Record<string, React.ElementType> = {
  "Phase\u00a02 分析": Brain,
  "Phase\u00a03 审核": ShieldCheck,
  "聊天": MessageCircle,
}

const roleColor: Record<string, string> = {
  "Phase\u00a02 分析": "bg-violet-100 text-violet-800",
  "Phase\u00a03 审核": "bg-sky-100 text-sky-800",
  "聊天": "bg-gray-100 text-gray-600",
  "本地推理": "bg-orange-100 text-orange-700",
}

const statusStyle = {
  connected: { label: "已连通", variant: "success" as const },
  configured: { label: "已配置", variant: "secondary" as const },
  offline: { label: "未配置", variant: "outline" as const },
}

export default function ModelConfig() {
  const [models, setModels] = useState<ModelInfo[]>([])

  useEffect(() => {
    api.getModels().then(setModels).catch(console.error)
  }, [])

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">模型后端</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-2">
          {models.map((m) => {
            const st = statusStyle[m.status]
            const meta = backendMeta[m.backend] || { label: m.backend, platform: "", role: "" }
            const Icon = iconMap[m.backend] || Globe
            const RoleIcon = meta.role ? (roleIcon[meta.role] || MessageCircle) : null
            const rc = meta.role ? (roleColor[meta.role] || "bg-gray-100 text-gray-600") : ""
            return (
              <div
                key={m.backend}
                className="flex items-center gap-3 rounded-lg border border-border px-3 py-2.5 text-sm hover:bg-muted/40 transition-colors"
              >
                <Icon className="w-4 h-4 shrink-0 text-muted-foreground" />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{meta.label}</span>
                    {meta.role && (
                      <span className={`inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded-full font-medium ${rc}`}>
                        {RoleIcon && <RoleIcon className="w-3 h-3" />}
                        {meta.role}
                      </span>
                    )}
                  </div>
                  <div className="text-xs text-muted-foreground truncate mt-0.5">
                    {m.model}
                    <span className="text-[10px] opacity-60 ml-2">via {meta.platform}</span>
                  </div>
                </div>
                <Badge variant={st.variant} className="text-[10px] shrink-0">
                  {st.label}
                </Badge>
              </div>
            )
          })}
        </div>
      </CardContent>
    </Card>
  )
}
