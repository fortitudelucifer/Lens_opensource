import { useState, useEffect } from "react"
import { Loader2, CheckCircle2, XCircle, Zap, Clock } from "lucide-react"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { api, type AvailableModel, type ModelTestResult } from "@/lib/api"

interface TestState {
  loading: boolean
  result: ModelTestResult | null
}

const FALLBACK_TEST_MODELS: AvailableModel[] = [
  { backend: "deepseek", model: "DeepSeek-V3.2", base_url: "https://api.deepseek.com", suitable_for: ["analysis", "review", "chat"] },
  { backend: "qwen_local", model: "Qwen3-8B-Instruct", base_url: "http://localhost:8000/v1", suitable_for: ["analysis", "review", "chat"] },
  { backend: "glm", model: "z-ai/glm4.7", base_url: "(默认)", suitable_for: ["analysis", "chat"] },
  { backend: "kimi", model: "Kimi-K2.5", base_url: "(默认)", suitable_for: ["analysis", "chat"] },
  { backend: "qwen_cloud", model: "Qwen/Qwen3-235B-A22B-Thinking-2507", base_url: "(默认)", suitable_for: ["analysis", "review", "chat"] },
]

export default function ModelTester() {
  const [backends, setBackends] = useState<AvailableModel[]>([])
  const [testStates, setTestStates] = useState<Record<string, TestState>>({})
  const [testAllLoading, setTestAllLoading] = useState(false)

  useEffect(() => {
    api.getAvailableModels()
      .then((models) => {
        const merged = [...models]
        const existingBackends = new Set(models.map((m) => m.backend))
        FALLBACK_TEST_MODELS.forEach((m) => {
          if (!existingBackends.has(m.backend)) {
            merged.push(m)
          }
        })
        setBackends(merged)
      })
      .catch(() => {
        setBackends(FALLBACK_TEST_MODELS)
      })
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
            error: e instanceof Error ? e.message : "请求失败",
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

  const getStatusIcon = (state: TestState | undefined) => {
    if (!state) return null
    if (state.loading) return <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />
    if (state.result?.status === "ok") return <CheckCircle2 className="w-4 h-4 text-green-500" />
    return <XCircle className="w-4 h-4 text-red-500" />
  }

  return (
    <div className="rounded-xl border border-border bg-card p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="font-semibold text-sm flex items-center gap-2">
            <Zap className="w-4 h-4" />
            模型连通性测试
          </h2>
          <p className="text-xs text-muted-foreground mt-1">
            向每个后端发送简短测试消息，验证 API Key 和模型是否可用
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
              测试中...
            </>
          ) : (
            "全部测试"
          )}
        </Button>
      </div>

      {backends.length === 0 && (
        <div className="text-xs text-muted-foreground text-center py-4">
          未发现已配置的模型后端
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
                result?.status === "ok" && "border-green-200 bg-green-50/50",
                result?.status === "error" && "border-red-200 bg-red-50/50",
                !result && "border-border"
              )}
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3 min-w-0">
                  {getStatusIcon(state)}
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
                      "测试"
                    )}
                  </Button>
                </div>
              </div>

              {/* Result details */}
              {result && (
                <div className="mt-2 pt-2 border-t border-border/50">
                  {result.status === "ok" ? (
                    <div className="text-xs text-green-700">
                      <span className="font-medium">回复：</span>
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
                      <span className="font-medium">错误：</span>
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
            {Object.values(testStates).filter((s) => s.result?.status === "ok").length} 通过
          </span>
          <span>
            <XCircle className="w-3 h-3 inline mr-1 text-red-500" />
            {Object.values(testStates).filter((s) => s.result?.status === "error").length} 失败
          </span>
        </div>
      )}
    </div>
  )
}
