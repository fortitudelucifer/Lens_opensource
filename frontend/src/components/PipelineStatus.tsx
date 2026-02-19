import { useEffect, useState, useCallback } from "react"
import {
  FileText, Cpu, ShieldCheck, ClipboardCheck,
  Database, GraduationCap, Play, MessageCircle, Loader2,
} from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { api, type PipelineState, type ModelPreferences } from "@/lib/api"

const phasesMeta = [
  { id: 1, name: "对话片段提取", icon: FileText, desc: "从 SFT 数据中提取代表性对话片段", runnable: true },
  { id: 2, name: "LLM 分析生成", icon: Cpu, desc: "使用云端模型生成关系分析", runnable: true },
  { id: 3, name: "AI 辅助审核", icon: ShieldCheck, desc: "Claude 交叉审核分析质量", runnable: true },
  { id: 4, name: "人工审核", icon: ClipboardCheck, desc: "在前端审核 AI 标记的低分项", runnable: false },
  { id: 5, name: "训练数据格式化", icon: Database, desc: "转为 SFT 训练格式", runnable: false },
  { id: 6, name: "QLoRA 微调", icon: GraduationCap, desc: "Qwen3-8B + LoRA r=32", runnable: false },
  { id: 7, name: "模型推理", icon: Play, desc: "测试训练后的模型", runnable: false },
  { id: 8, name: "实时对话", icon: MessageCircle, desc: "listen / consult 双模式", runnable: false },
]

const statusMap = {
  idle: { label: "待执行", variant: "outline" as const, dotClass: "bg-gray-300" },
  running: { label: "运行中", variant: "warning" as const, dotClass: "bg-amber-500 animate-pulse" },
  done: { label: "已完成", variant: "success" as const, dotClass: "bg-emerald-500" },
  error: { label: "错误", variant: "destructive" as const, dotClass: "bg-red-500" },
}

interface Props {
  onRunPhase?: (phase: number) => void
}

export default function PipelineStatus({ onRunPhase }: Props) {
  const [state, setState] = useState<PipelineState | null>(null)
  const [prefs, setPrefs] = useState<ModelPreferences | null>(null)

  const refresh = useCallback(() => {
    api.getPipelineStatus().then(setState).catch(console.error)
  }, [])

  useEffect(() => {
    api.getModelPreferences().then(setPrefs).catch(() => {})
  }, [])

  useEffect(() => {
    refresh()
    const timer = setInterval(refresh, 3000)
    return () => clearInterval(timer)
  }, [refresh])

  const handleRun = async (phaseId: number) => {
    try {
      const backend = phaseId === 2
        ? (prefs?.analysis_backend || "qwen_cloud")
        : phaseId === 3
        ? (prefs?.review_backend || "grok")
        : "claude"
      await api.runPipelinePhase(phaseId, {
        input_type: "l2",
        backend,
        agent_type: "neutral",
        num_chunks: 5,
        limit: 5,
      })
      refresh()
      onRunPhase?.(phaseId)
    } catch (e) {
      console.error(e)
    }
  }

  const isRunning = state?.running_task != null

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">流水线状态</CardTitle>
      </CardHeader>
      <CardContent className="space-y-1">
        {phasesMeta.map((meta, idx) => {
          const phaseState = state?.phases[meta.id]
          const status = phaseState?.status ?? "idle"
          const detail = phaseState?.detail ?? ""
          const st = statusMap[status]
          const Icon = meta.icon
          return (
            <div key={meta.id}>
              <div
                className={cn(
                  "flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition-colors",
                  status === "running" ? "bg-amber-50" : "hover:bg-muted/50"
                )}
              >
                <div className={cn("w-2 h-2 rounded-full shrink-0", st.dotClass)} />
                {status === "running" ? (
                  <Loader2 className="w-4 h-4 shrink-0 text-amber-600 animate-spin" />
                ) : (
                  <Icon className="w-4 h-4 shrink-0 text-muted-foreground" />
                )}
                <div className="flex-1 min-w-0">
                  <div className="font-medium truncate">
                    Phase {meta.id}: {meta.name}
                  </div>
                  <div className="text-xs text-muted-foreground truncate">
                    {detail || meta.desc}
                  </div>
                </div>
                {meta.runnable && status !== "running" && (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 px-2 text-xs shrink-0"
                    disabled={isRunning}
                    onClick={() => handleRun(meta.id)}
                  >
                    <Play className="w-3 h-3 mr-1" />
                    运行
                  </Button>
                )}
                <Badge variant={st.variant} className="shrink-0 text-[10px]">
                  {st.label}
                </Badge>
              </div>
              {idx < phasesMeta.length - 1 && (
                <div className="ml-[22px] h-3 border-l border-dashed border-border" />
              )}
            </div>
          )
        })}
      </CardContent>
    </Card>
  )
}
