import { useMemo, useRef, useState } from "react"
import { api } from "@/lib/api"
import type { KeyCheckerModel } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { cn } from "@/lib/utils"
import {
  CheckCircle2,
  XCircle,
  Loader2,
  Search,
  Square,
  Play,
  FolderOpen,
  Trash2,
} from "lucide-react"

interface CheckResult {
  checkStatus: "loading" | "success" | "error"
  latency?: number
  model?: string
  error?: string
  httpStatus?: number
}

function groupByPrefix(models: KeyCheckerModel[]) {
  const groups: Record<string, string[]> = {}
  models.forEach((m) => {
    const id = m.id || ""
    const prefix = id.split(/[-:/]/)[0] || "other"
    if (!groups[prefix]) groups[prefix] = []
    groups[prefix].push(id)
  })
  Object.values(groups).forEach((list) => list.sort((a, b) => a.localeCompare(b)))
  return groups
}

export default function ApiKeyChecker() {
  const [baseUrl, setBaseUrl] = useState("https://ai.hybgzs.com")
  const [apiKey, setApiKey] = useState("")
  const [manualModel, setManualModel] = useState("gpt-5.2")
  const [discoveredModels, setDiscoveredModels] = useState<KeyCheckerModel[]>([])
  const [selectedModels, setSelectedModels] = useState<Set<string>>(new Set())
  const [customGroups, setCustomGroups] = useState<Record<string, string[]>>({})
  const [customGroupName, setCustomGroupName] = useState("")
  const [results, setResults] = useState<Record<string, CheckResult>>({})
  const [logs, setLogs] = useState<string[]>([])
  const [isTesting, setIsTesting] = useState(false)
  const [loadingModels, setLoadingModels] = useState(false)
  const stopRef = useRef(false)
  const detectionIdRef = useRef("")

  const autoGroups = useMemo(() => groupByPrefix(discoveredModels), [discoveredModels])

  const addLog = (msg: string) => {
    setLogs((prev) => [`[${new Date().toLocaleTimeString()}] ${msg}`, ...prev].slice(0, 200))
  }

  const fetchModels = async () => {
    if (!apiKey) { addLog("请先输入 API Key"); return }
    setLoadingModels(true)
    addLog("开始获取模型列表...")
    try {
      const data = await api.keysFetchModels(baseUrl, apiKey)
      if (data.success && data.models) {
        setDiscoveredModels(data.models)
        setSelectedModels(new Set())
        setResults({})
        addLog(`获取到 ${data.models.length} 个模型 (${data.duration}ms)`)
      } else {
        addLog(`获取失败: ${data.error || "未知错误"}`)
      }
    } catch (e: unknown) {
      addLog(`请求失败: ${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setLoadingModels(false)
    }
  }

  const toggleModel = (id: string) => {
    setSelectedModels((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id); else next.add(id)
      return next
    })
  }

  const toggleGroup = (ids: string[]) => {
    setSelectedModels((prev) => {
      const next = new Set(prev)
      const allSelected = ids.every((id) => next.has(id))
      ids.forEach((id) => { if (allSelected) next.delete(id); else next.add(id) })
      return next
    })
  }

  const createCustomGroup = () => {
    const name = customGroupName.trim()
    if (!name) { addLog("请输入分组名称"); return }
    const list = Array.from(selectedModels)
    if (list.length === 0) { addLog("请先选择模型"); return }
    setCustomGroups((prev) => ({ ...prev, [name]: list }))
    setCustomGroupName("")
    addLog(`已创建分组「${name}」(${list.length} 个模型)`)
  }

  const runTests = async () => {
    if (!apiKey) { addLog("请先输入 API Key"); return }
    const targets = selectedModels.size > 0 ? Array.from(selectedModels) : manualModel ? [manualModel] : []
    if (targets.length === 0) { addLog("未选择任何模型"); return }

    stopRef.current = false
    const dId = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
    detectionIdRef.current = dId
    setIsTesting(true)
    addLog(`开始检测 ${targets.length} 个模型`)

    for (let i = 0; i < targets.length; i++) {
      if (stopRef.current) break
      const model = targets[i]
      setResults((prev) => ({ ...prev, [model]: { checkStatus: "loading" } }))
      addLog(`[${i + 1}/${targets.length}] 检测 ${model}`)

      try {
        const res = await api.keysCheck(baseUrl, apiKey, model, dId)
        if (res.success) {
          setResults((prev) => ({
            ...prev,
            [model]: { checkStatus: "success", latency: res.latency, model: res.model },
          }))
          addLog(`  ✅ ${model} (${res.latency}ms)`)
        } else {
          setResults((prev) => ({
            ...prev,
            [model]: { checkStatus: "error", error: res.error, httpStatus: res.status },
          }))
          addLog(`  ❌ ${model}: ${res.error || "失败"}${res.status ? ` (${res.status})` : ""}`)
        }
      } catch (e: unknown) {
        setResults((prev) => ({
          ...prev,
          [model]: { checkStatus: "error", error: e instanceof Error ? e.message : String(e) },
        }))
      }

      // Wait between requests (server rate limits, but also UI delay)
      if (i < targets.length - 1 && !stopRef.current) {
        addLog("  等待 5s...")
        await new Promise((r) => setTimeout(r, 5200))
      }
    }

    addLog(stopRef.current ? "检测已终止" : "检测完成")
    setIsTesting(false)
  }

  const stopTests = async () => {
    stopRef.current = true
    addLog("正在终止...")
    try {
      await api.keysStop(detectionIdRef.current)
    } catch { /* ignore */ }
  }

  // Stats
  const successCount = Object.values(results).filter((r) => r.checkStatus === "success").length
  const errorCount = Object.values(results).filter((r) => r.checkStatus === "error").length

  return (
    <Card className="p-6 space-y-5">
      <div>
        <h2 className="font-semibold text-sm">API Key 可用性检查</h2>
        <p className="text-xs text-muted-foreground mt-1">
          输入代理地址和 Key，获取模型列表并批量检测连通性
        </p>
      </div>

      {/* Input row */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-3">
        <div className="lg:col-span-5">
          <label className="text-xs font-medium text-muted-foreground">代理或官方地址</label>
          <input
            className="mt-1 w-full border border-border rounded-lg px-3 py-2 text-sm bg-background focus:outline-none focus:ring-2 focus:ring-ring"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            placeholder="https://api.openai.com"
          />
        </div>
        <div className="lg:col-span-5">
          <label className="text-xs font-medium text-muted-foreground">API Key</label>
          <input
            className="mt-1 w-full border border-border rounded-lg px-3 py-2 text-sm bg-background focus:outline-none focus:ring-2 focus:ring-ring"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            type="password"
            placeholder="sk-..."
          />
        </div>
        <div className="lg:col-span-2 flex items-end">
          <Button onClick={fetchModels} disabled={loadingModels} className="w-full" size="sm">
            {loadingModels ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <Search className="w-4 h-4 mr-1" />}
            {loadingModels ? "获取中" : "获取模型"}
          </Button>
        </div>
      </div>

      {/* Main area: model list + results */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Left: model selection */}
        <div className="lg:col-span-1 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium">模型选择</span>
            <div className="flex gap-1">
              <Button variant="outline" size="sm" className="h-6 text-[10px] px-2"
                onClick={() => setSelectedModels(new Set(discoveredModels.map((m) => m.id)))}>
                全选
              </Button>
              <Button variant="outline" size="sm" className="h-6 text-[10px] px-2"
                onClick={() => setSelectedModels(new Set())}>
                清空
              </Button>
            </div>
          </div>

          {discoveredModels.length === 0 ? (
            <div className="border border-border rounded-lg p-3 bg-muted/30 space-y-2">
              <p className="text-xs text-muted-foreground">暂无模型，手动输入或点击「获取模型」</p>
              <input
                className="w-full border border-border rounded px-2 py-1.5 text-xs bg-background"
                value={manualModel}
                onChange={(e) => setManualModel(e.target.value)}
                placeholder="gpt-5.2"
              />
            </div>
          ) : (
            <div className="max-h-[420px] overflow-y-auto space-y-2 pr-1">
              {/* Auto groups */}
              {Object.entries(autoGroups).map(([name, ids]) => (
                <div key={name} className="border border-border rounded-lg overflow-hidden">
                  <button
                    className="w-full text-left px-3 py-1.5 text-xs font-medium bg-muted/50 hover:bg-muted flex justify-between"
                    onClick={() => toggleGroup(ids)}
                  >
                    <span>{name}</span>
                    <span className="text-muted-foreground">({ids.length})</span>
                  </button>
                  <div className="p-2 space-y-0.5">
                    {ids.map((id) => (
                      <label key={id} className="flex items-center gap-2 text-xs cursor-pointer hover:bg-muted/30 px-1 py-0.5 rounded">
                        <input type="checkbox" checked={selectedModels.has(id)} onChange={() => toggleModel(id)} className="rounded" />
                        <span className="truncate">{id}</span>
                      </label>
                    ))}
                  </div>
                </div>
              ))}

              {/* Custom groups */}
              <div className="border border-border rounded-lg p-2 space-y-2">
                <span className="text-xs font-medium text-muted-foreground">手动分组</span>
                <div className="flex gap-1">
                  <input
                    className="flex-1 border border-border rounded px-2 py-1 text-xs bg-background"
                    placeholder="分组名"
                    value={customGroupName}
                    onChange={(e) => setCustomGroupName(e.target.value)}
                  />
                  <Button variant="outline" size="sm" className="h-7 text-[10px]" onClick={createCustomGroup}>
                    <FolderOpen className="w-3 h-3 mr-1" />创建
                  </Button>
                </div>
                {Object.entries(customGroups).map(([name, ids]) => (
                  <div key={name} className="border border-border rounded p-2">
                    <div className="flex items-center justify-between">
                      <button className="text-xs font-medium" onClick={() => toggleGroup(ids)}>
                        {name} ({ids.length})
                      </button>
                      <button className="text-xs text-destructive" onClick={() => {
                        setCustomGroups((prev) => { const n = { ...prev }; delete n[name]; return n })
                      }}>
                        <Trash2 className="w-3 h-3" />
                      </button>
                    </div>
                    <p className="text-[10px] text-muted-foreground mt-1 truncate">{ids.join(", ")}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="flex gap-2">
            <Button onClick={runTests} disabled={isTesting} className="flex-1" size="sm">
              {isTesting ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <Play className="w-4 h-4 mr-1" />}
              {isTesting ? "检测中" : "开始检测"}
            </Button>
            <Button onClick={stopTests} disabled={!isTesting} variant="destructive" size="sm" className="w-20">
              <Square className="w-3 h-3 mr-1" />终止
            </Button>
          </div>
        </div>

        {/* Right: results + logs */}
        <div className="lg:col-span-2 space-y-3">
          {/* Results */}
          <div className="border border-border rounded-lg p-3 bg-muted/20 min-h-[280px] max-h-[360px] overflow-y-auto">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-medium">检测结果</span>
              {(successCount > 0 || errorCount > 0) && (
                <span className="text-[10px] text-muted-foreground">
                  ✅ {successCount} | ❌ {errorCount} | 共 {Object.keys(results).length}
                </span>
              )}
            </div>
            {Object.keys(results).length === 0 && (
              <p className="text-xs text-muted-foreground">结果将在这里显示</p>
            )}
            <div className="space-y-1">
              {Object.entries(results).map(([model, result]) => (
                <div
                  key={model}
                  className={cn(
                    "px-3 py-1.5 rounded border flex items-center justify-between text-xs",
                    result.checkStatus === "success" && "border-green-500/30 bg-green-500/5",
                    result.checkStatus === "error" && "border-red-500/30 bg-red-500/5",
                    result.checkStatus === "loading" && "border-border bg-background"
                  )}
                >
                  <span className="font-medium truncate max-w-[60%]">{model}</span>
                  <span className="flex items-center gap-1 shrink-0">
                    {result.checkStatus === "loading" && <Loader2 className="w-3 h-3 animate-spin" />}
                    {result.checkStatus === "success" && (
                      <>
                        <CheckCircle2 className="w-3 h-3 text-green-600" />
                        <span className="text-green-700">{result.latency}ms</span>
                      </>
                    )}
                    {result.checkStatus === "error" && (
                      <>
                        <XCircle className="w-3 h-3 text-red-600" />
                        <span className="text-red-700 truncate max-w-[150px]">
                          {result.error}{result.httpStatus ? ` (${result.httpStatus})` : ""}
                        </span>
                      </>
                    )}
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* Logs */}
          <div className="border border-border rounded-lg p-3 bg-slate-950 text-slate-100 min-h-[120px] max-h-[160px] overflow-y-auto">
            <span className="text-[10px] text-slate-400">系统日志</span>
            <div className="mt-1 space-y-0.5 text-[11px] font-mono">
              {logs.map((log, i) => (
                <div key={`${log}-${i}`} className="text-slate-300">{log}</div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </Card>
  )
}
