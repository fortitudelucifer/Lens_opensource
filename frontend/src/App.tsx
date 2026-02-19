import { useState } from "react"
import { Heart, LayoutDashboard, MessageCircle, Settings, ClipboardCheck } from "lucide-react"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import ChatPanel from "@/components/ChatPanel"
import PipelineStatus from "@/components/PipelineStatus"
import ModelConfig from "@/components/ModelConfig"
import ModelSelector from "@/components/ModelSelector"
import DataStats from "@/components/DataStats"
import ReviewPanel from "@/components/ReviewPanel"
import ModelTester from "@/components/ModelTester"
import ApiKeyChecker from "@/components/ApiKeyChecker"
import "./App.css"

type Page = "dashboard" | "chat" | "review" | "settings"

function App() {
  const [page, setPage] = useState<Page>("dashboard")

  return (
    <div className="flex h-screen bg-background">
      {/* Sidebar */}
      <aside className="w-16 lg:w-56 border-r border-border flex flex-col shrink-0">
        <div className="flex items-center gap-2 px-4 py-4 border-b border-border">
          <Heart className="w-6 h-6 text-rose-500 shrink-0" />
          <span className="hidden lg:block font-bold text-sm">关系顾问 Agent</span>
        </div>
        <nav className="flex-1 p-2 space-y-1">
          {([
            { id: "dashboard" as Page, label: "仪表盘", icon: LayoutDashboard },
            { id: "chat" as Page, label: "对话", icon: MessageCircle },
            { id: "review" as Page, label: "人工审核", icon: ClipboardCheck },
            { id: "settings" as Page, label: "设置", icon: Settings },
          ]).map((item) => {
            const Icon = item.icon
            return (
              <Button
                key={item.id}
                variant={page === item.id ? "secondary" : "ghost"}
                className={cn(
                  "w-full justify-start gap-2",
                  page === item.id && "font-semibold"
                )}
                onClick={() => setPage(item.id)}
              >
                <Icon className="w-4 h-4 shrink-0" />
                <span className="hidden lg:inline text-sm">{item.label}</span>
              </Button>
            )
          })}
        </nav>
        <div className="p-3 border-t border-border">
          <div className="text-[10px] text-muted-foreground text-center hidden lg:block">
            Advisor Pipeline v2.2
          </div>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-hidden flex flex-col">
        {page === "dashboard" && <DashboardPage />}
        {page === "chat" && <ChatPage />}
        {page === "review" && <ReviewPage />}
        {page === "settings" && <SettingsPage />}
      </main>
    </div>
  )
}

function DashboardPage() {
  return (
    <div className="flex-1 overflow-y-auto p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">仪表盘</h1>
        <p className="text-sm text-muted-foreground mt-1">关系顾问 Agent 流水线运行状态总览</p>
      </div>
      <DataStats />
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <PipelineStatus />
        <ModelConfig />
      </div>
    </div>
  )
}

function ChatPage() {
  return (
    <div className="flex-1 overflow-hidden flex flex-col">
      <div className="px-6 py-4 border-b border-border">
        <h1 className="text-lg font-bold tracking-tight">实时对话</h1>
        <p className="text-xs text-muted-foreground">与关系顾问 Agent 进行对话咨询</p>
      </div>
      <div className="flex-1 overflow-hidden">
        <ChatPanel />
      </div>
    </div>
  )
}

function ReviewPage() {
  return (
    <div className="flex-1 overflow-hidden flex flex-col">
      <ReviewPanel />
    </div>
  )
}

function SettingsPage() {
  return (
    <div className="flex-1 overflow-y-auto p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">设置</h1>
        <p className="text-sm text-muted-foreground mt-1">API 密钥与模型配置</p>
      </div>
      <ModelSelector />
      <ModelTester />
      <ApiKeyChecker />
      <div className="rounded-xl border border-border bg-card p-6 space-y-4">
        <h2 className="font-semibold text-sm">配置文件路径</h2>
        <div className="space-y-2 text-sm">
          <div className="flex justify-between items-center py-2 border-b border-border/50">
            <span className="text-muted-foreground">API Key 配置</span>
            <code className="text-xs bg-muted px-2 py-1 rounded">/data/wechatDHA/ls_windsurf/local_secrets/.env.advisor</code>
          </div>
          <div className="flex justify-between items-center py-2 border-b border-border/50">
            <span className="text-muted-foreground">模型配置</span>
            <code className="text-xs bg-muted px-2 py-1 rounded">configs/advisor.yaml</code>
          </div>
          <div className="flex justify-between items-center py-2 border-b border-border/50">
            <span className="text-muted-foreground">L1 训练数据</span>
            <code className="text-xs bg-muted px-2 py-1 rounded">timeline_out/agent_sft_l1.jsonl</code>
          </div>
          <div className="flex justify-between items-center py-2">
            <span className="text-muted-foreground">L2 匿名数据</span>
            <code className="text-xs bg-muted px-2 py-1 rounded">timeline_out/agent_sft_l2.jsonl</code>
          </div>
        </div>
        <div className="pt-2">
          <p className="text-xs text-muted-foreground">
            编辑 <code className="bg-muted px-1 rounded">.env.advisor</code> 后运行{" "}
            <code className="bg-muted px-1 rounded">source .env.advisor</code> 加载到环境。
          </p>
        </div>
      </div>
      <div className="rounded-xl border border-border bg-card p-6 space-y-4">
        <h2 className="font-semibold text-sm">隐私策略</h2>
        <div className="text-sm space-y-2 text-muted-foreground">
          <p><strong className="text-foreground">Phase 2 云端分析</strong> — 使用 L2（匿名化）数据，云端只看到 ME/OTHER</p>
          <p><strong className="text-foreground">Phase 6 本地训练</strong> — 使用 L1（真实姓名）数据，数据不离开本机</p>
          <p><strong className="text-foreground">SafetyLayer P0</strong> — 云端 rationale_private 不注入本地上下文</p>
        </div>
      </div>
    </div>
  )
}

export default App
