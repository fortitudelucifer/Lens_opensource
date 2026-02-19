import { useEffect, useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { FileText, Layers, TestTubeDiagonal, Shield } from "lucide-react"
import { api, type DataStats as DataStatsType } from "@/lib/api"

export default function DataStats() {
  const [stats, setStats] = useState<DataStatsType | null>(null)

  useEffect(() => {
    api.getDataStats().then(setStats).catch(console.error)
    const timer = setInterval(() => {
      api.getDataStats().then(setStats).catch(console.error)
    }, 10000)
    return () => clearInterval(timer)
  }, [])

  const items = [
    { label: "L1 训练数据", value: stats?.l1_lines ?? "—", sub: "行 · 真实姓名", icon: FileText, color: "text-blue-600" },
    { label: "L2 匿名数据", value: stats?.l2_lines ?? "—", sub: "行 · ME/OTHER", icon: Shield, color: "text-emerald-600" },
    { label: "测试数据", value: stats?.test_lines ?? "—", sub: "行 · agent_sft_test", icon: TestTubeDiagonal, color: "text-violet-600" },
    { label: "已提取片段", value: stats?.chunks ?? "—", sub: `分析: ${stats ? Object.values(stats.analyses).reduce((a, b) => a + b, 0) : 0}`, icon: Layers, color: "text-rose-600" },
  ]

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
      {items.map((s) => {
        const Icon = s.icon
        return (
          <Card key={s.label} className="overflow-hidden">
            <CardHeader className="pb-2 pt-4 px-4">
              <CardTitle className="text-xs font-medium text-muted-foreground flex items-center gap-1.5">
                <Icon className={`w-3.5 h-3.5 ${s.color}`} />
                {s.label}
              </CardTitle>
            </CardHeader>
            <CardContent className="px-4 pb-4">
              <div className="text-2xl font-bold tracking-tight">{typeof s.value === "number" ? s.value.toLocaleString() : s.value}</div>
              <div className="text-[11px] text-muted-foreground mt-0.5">{s.sub}</div>
            </CardContent>
          </Card>
        )
      })}
    </div>
  )
}
