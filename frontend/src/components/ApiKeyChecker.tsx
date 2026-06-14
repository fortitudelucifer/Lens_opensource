import { useMemo, useRef, useState } from "react"
import { useTranslation } from "react-i18next"
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
  const { t } = useTranslation()
  const [baseUrl, setBaseUrl] = useState("https://api.deepseek.com")
  const [apiKey, setApiKey] = useState("")
  const [manualModel, setManualModel] = useState("deepseek-chat")
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
    if (!apiKey) { addLog(t('apiKeyChecker.enterApiKey')); return }
    setLoadingModels(true)
    addLog(t('apiKeyChecker.fetchingModels'))
    try {
      const data = await api.keysFetchModels(baseUrl, apiKey)
      if (data.success && data.models) {
        setDiscoveredModels(data.models)
        setSelectedModels(new Set())
        setResults({})
        addLog(t('apiKeyChecker.fetchedModels', { count: data.models.length, duration: data.duration }))
      } else {
        addLog(t('apiKeyChecker.fetchFailed', { error: data.error || 'Unknown error' }))
      }
    } catch (e: unknown) {
      addLog(t('apiKeyChecker.requestFailed', { msg: e instanceof Error ? e.message : String(e) }))
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
    if (!name) { addLog(t('apiKeyChecker.enterGroupName')); return }
    const list = Array.from(selectedModels)
    if (list.length === 0) { addLog(t('apiKeyChecker.selectModelsFirst')); return }
    setCustomGroups((prev) => ({ ...prev, [name]: list }))
    setCustomGroupName("")
    addLog(t('apiKeyChecker.groupCreated', { name, count: list.length }))
  }

  const runTests = async () => {
    if (!apiKey) { addLog(t('apiKeyChecker.enterApiKey')); return }
    const targets = selectedModels.size > 0 ? Array.from(selectedModels) : manualModel ? [manualModel] : []
    if (targets.length === 0) { addLog(t('apiKeyChecker.noModelsSelected')); return }

    stopRef.current = false
    const dId = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
    detectionIdRef.current = dId
    setIsTesting(true)
    addLog(t('apiKeyChecker.startTesting', { count: targets.length }))

    for (let i = 0; i < targets.length; i++) {
      if (stopRef.current) break
      const model = targets[i]
      setResults((prev) => ({ ...prev, [model]: { checkStatus: "loading" } }))
      addLog(t('apiKeyChecker.testingModel', { current: i + 1, total: targets.length, model }))

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
          addLog(t('apiKeyChecker.testFailed', { model, error: res.error || 'Failed' }) + (res.status ? ` (${res.status})` : ''))
        }
      } catch (e: unknown) {
        setResults((prev) => ({
          ...prev,
          [model]: { checkStatus: "error", error: e instanceof Error ? e.message : String(e) },
        }))
      }

      // Wait between requests (server rate limits, but also UI delay)
      if (i < targets.length - 1 && !stopRef.current) {
        addLog(t('apiKeyChecker.wait5s'))
        await new Promise((r) => setTimeout(r, 5200))
      }
    }

    addLog(stopRef.current ? t('apiKeyChecker.testTerminated') : t('apiKeyChecker.testComplete'))
    setIsTesting(false)
  }

  const stopTests = async () => {
    stopRef.current = true
    addLog(t('apiKeyChecker.stopping'))
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
        <h2 className="font-semibold text-sm">{t('apiKeyChecker.title')}</h2>
        <p className="text-xs text-muted-foreground mt-1">
          {t('apiKeyChecker.description')}
        </p>
      </div>

      {/* Input row */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-3">
        <div className="lg:col-span-5">
          <label className="text-xs font-medium text-muted-foreground">{t('apiKeyChecker.proxyLabel')}</label>
          <input
            className="mt-1 w-full border border-border rounded-lg px-3 py-2 text-sm bg-background focus:outline-none focus:ring-2 focus:ring-ring"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            placeholder="https://api.deepseek.com"
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
            {loadingModels ? t('apiKeyChecker.fetching') : t('apiKeyChecker.fetchModels')}
          </Button>
        </div>
      </div>

      {/* Main area: model list + results */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Left: model selection */}
        <div className="lg:col-span-1 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium">{t('apiKeyChecker.modelSelection')}</span>
            <div className="flex gap-1">
              <Button variant="outline" size="sm" className="h-6 text-[10px] px-2"
                onClick={() => setSelectedModels(new Set(discoveredModels.map((m) => m.id)))}>
                {t('apiKeyChecker.selectAll')}
              </Button>
              <Button variant="outline" size="sm" className="h-6 text-[10px] px-2"
                onClick={() => setSelectedModels(new Set())}>
                {t('apiKeyChecker.clear')}
              </Button>
            </div>
          </div>

          {discoveredModels.length === 0 ? (
            <div className="border border-border rounded-lg p-3 bg-muted/30 space-y-2">
              <p className="text-xs text-muted-foreground">{t('apiKeyChecker.noModels')}</p>
              <input
                className="w-full border border-border rounded px-2 py-1.5 text-xs bg-background"
                value={manualModel}
                onChange={(e) => setManualModel(e.target.value)}
                placeholder="deepseek-chat"
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
                <span className="text-xs font-medium text-muted-foreground">{t('apiKeyChecker.customGroup')}</span>
                <div className="flex gap-1">
                  <input
                    className="flex-1 border border-border rounded px-2 py-1 text-xs bg-background"
                    placeholder={t('apiKeyChecker.groupNamePlaceholder')}
                    value={customGroupName}
                    onChange={(e) => setCustomGroupName(e.target.value)}
                  />
                  <Button variant="outline" size="sm" className="h-7 text-[10px]" onClick={createCustomGroup}>
                    <FolderOpen className="w-3 h-3 mr-1" />{t('apiKeyChecker.createGroup')}
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
              {isTesting ? t('apiKeyChecker.testing') : t('apiKeyChecker.startTest')}
            </Button>
            <Button onClick={stopTests} disabled={!isTesting} variant="destructive" size="sm" className="w-20">
              <Square className="w-3 h-3 mr-1" />{t('apiKeyChecker.stop')}
            </Button>
          </div>
        </div>

        {/* Right: results + logs */}
        <div className="lg:col-span-2 space-y-3">
          {/* Results */}
          <div className="border border-border rounded-lg p-3 bg-muted/20 min-h-[280px] max-h-[360px] overflow-y-auto">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-medium">{t('apiKeyChecker.testResults')}</span>
              {(successCount > 0 || errorCount > 0) && (
                <span className="text-[10px] text-muted-foreground">
                  ✅ {successCount} | ❌ {errorCount} | {t('apiKeyChecker.total')} {Object.keys(results).length}
                </span>
              )}
            </div>
            {Object.keys(results).length === 0 && (
              <p className="text-xs text-muted-foreground">Results will appear here</p>
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
            <span className="text-[10px] text-slate-400">{t('apiKeyChecker.systemLogs')}</span>
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
