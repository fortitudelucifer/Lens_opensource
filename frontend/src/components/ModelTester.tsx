import { useState, useEffect } from "react"
import { useTranslation } from "react-i18next"
import { Loader2, CheckCircle2, XCircle, Zap, Clock } from "lucide-react"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { api, type AvailableModel, type ModelTestResult } from "@/lib/api"

interface TestState {
  loading: boolean
  result: ModelTestResult | null
}

export default function ModelTester() {
  const { t } = useTranslation()
  const [backends, setBackends] = useState<AvailableModel[]>([])
  const [testStates, setTestStates] = useState<Record<string, TestState>>({})
  const [testAllLoading, setTestAllLoading] = useState(false)
  // 自动连通探测（复用 /api/models/reachable，与聊天下拉同一来源）：进页面即显示绿/红
  const [reachable, setReachable] = useState<Record<string, boolean>>({})

  useEffect(() => {
    api.getAvailableModels()
      .then(setBackends)
      .catch(() => {})
    api.getReachable()
      .then(setReachable)
      .catch(() => {})
  }, [])

  const testSingle = async (backend: string) => {
    setTestStates((prev) => ({
      ...prev,
      [backend]: { loading: true, result: null },
    }))
    try {
      const result = await api.testModel(backend)
      setTestStates((prev) => ({
        ...prev,
        [backend]: { loading: false, result },
      }))
    } catch (e) {
      setTestStates((prev) => ({
        ...prev,
        [backend]: {
          loading: false,
          result: {
            status: "error",
            backend,
            model: "(unknown)",
            error: e instanceof Error ? e.message : t('modelTester.requestFailed'),
            latency_ms: 0,
          },
        },
      }))
    }
  }

  const testAll = async () => {
    setTestAllLoading(true)
    for (const b of backends) {
      await testSingle(b.backend)
    }
    setTestAllLoading(false)
  }

  const getStatusIcon = (backend: string, state: TestState | undefined) => {
    if (state?.loading) return <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />
    // 手动深度测试结果优先
    if (state?.result) return state.result.status === "ok"
      ? <CheckCircle2 className="w-4 h-4 text-green-500" />
      : <XCircle className="w-4 h-4 text-red-500" />
    // 否则用自动连通探测结果（绿=连通 / 红=不通）
    if (backend in reachable) return reachable[backend]
      ? <CheckCircle2 className="w-4 h-4 text-green-500" />
      : <XCircle className="w-4 h-4 text-red-500" />
    return <Loader2 className="w-4 h-4 animate-spin text-muted-foreground/40" />
  }

  return (
    <div className="rounded-xl border border-border bg-card p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="font-semibold text-sm flex items-center gap-2">
            <Zap className="w-4 h-4" />
            {t('modelTester.title')}
          </h2>
          <p className="text-xs text-muted-foreground mt-1">
            {t('modelTester.description')}
          </p>
        </div>
        <Button
          onClick={testAll}
          disabled={testAllLoading || backends.length === 0}
          size="sm"
        >
          {testAllLoading ? (
            <>
              <Loader2 className="w-3.5 h-3.5 animate-spin mr-1" />
              {t('modelTester.testing')}
            </>
          ) : (
            t('modelTester.testAll')
          )}
        </Button>
      </div>

      {backends.length === 0 && (
        <div className="text-xs text-muted-foreground text-center py-4">
          {t('modelTester.noBackends')}
        </div>
      )}

      <div className="space-y-2">
        {backends.map((b) => {
          const state = testStates[b.backend]
          const result = state?.result
          return (
            <div
              key={b.backend}
              className={cn(
                "rounded-lg border p-3 transition-colors",
                (result?.status === "ok" || (!result && reachable[b.backend] === true)) && "border-green-200 bg-green-50/50",
                (result?.status === "error" || (!result && reachable[b.backend] === false)) && "border-red-200 bg-red-50/50",
                !result && reachable[b.backend] === undefined && "border-border"
              )}
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3 min-w-0">
                  {getStatusIcon(b.backend, state)}
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-sm">{b.backend}</span>
                      <span className="text-[10px] text-muted-foreground bg-muted px-1.5 py-0.5 rounded">
                        {b.model.split("/").pop()}
                      </span>
                    </div>
                    <div className="text-[10px] text-muted-foreground truncate">
                      {b.base_url}
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  {result && (
                    <div className="flex items-center gap-1 text-[10px] text-muted-foreground">
                      <Clock className="w-3 h-3" />
                      {result.latency_ms}ms
                    </div>
                  )}
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-7 text-xs"
                    onClick={() => testSingle(b.backend)}
                    disabled={state?.loading}
                  >
                    {state?.loading ? (
                      <Loader2 className="w-3 h-3 animate-spin" />
                    ) : (
                      t('modelTester.test')
                    )}
                  </Button>
                </div>
              </div>

              {/* Result details */}
              {result && (
                <div className="mt-2 pt-2 border-t border-border/50">
                  {result.status === "ok" ? (
                    <div className="text-xs text-green-700">
                      <span className="font-medium">{t('modelTester.response')}</span>
                      <span className="ml-1">
                        {(result.response || "")
                          .replace(/<think>[\s\S]*?<\/think>\s*/g, "")
                          .replace(/<think>[\s\S]*$/g, "")
                          .trim()
                          .slice(0, 200)}
                      </span>
                    </div>
                  ) : (
                    <div className="text-xs text-red-700">
                      <span className="font-medium">{t('modelTester.error')}</span>
                      <span className="ml-1 break-all">{result.error?.slice(0, 300)}</span>
                    </div>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>

      {/* Summary */}
      {Object.keys(testStates).length > 0 && !testAllLoading && (
        <div className="flex items-center gap-4 pt-2 text-xs text-muted-foreground">
          <span>
            <CheckCircle2 className="w-3 h-3 inline mr-1 text-green-500" />
            {Object.values(testStates).filter((s) => s.result?.status === "ok").length} {t('modelTester.pass')}
          </span>
          <span>
            <XCircle className="w-3 h-3 inline mr-1 text-red-500" />
            {Object.values(testStates).filter((s) => s.result?.status === "error").length} {t('modelTester.fail')}
          </span>
        </div>
      )}
    </div>
  )
}
