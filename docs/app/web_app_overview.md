# 顾问 Web 应用系统设计

> 📌 **文档范围**：本文档描述 Lens 顾问 Web 应用作为应用层系统，包括前端路由、页面职责、API 集成、状态边界、安全界面、隐私控制和操作约束。
>
> 更新时间：2026-06-13

---

## 目录

- [1. 设计目标](#1-设计目标)
- [2. 系统架构](#2-系统架构)
- [3. 前端应用外壳](#3-前端应用外壳)
- [4. 页面与模块职责](#4-页面与模块职责)
- [5. API 集成模型](#5-api-集成模型)
- [6. 状态管理边界](#6-状态管理边界)
- [7. 流式与实时交互](#7-流式与实时交互)
- [8. 安全、同意与隐私界面](#8-安全同意与隐私界面)
- [9. 仪表板与操作用户体验](#9-仪表板与操作用户体验)
- [10. 按功能的数据流](#10-按功能的数据流)
- [11. 前端构建与运行时](#11-前端构建与运行时)
- [12. 集成点](#12-集成点)
- [13. 已知限制与演进方向](#13-已知限制与演进方向)
- [14. 文件索引](#14-文件索引)

---

## 1. 设计目标

### 1.1 产品定位

Web 应用是 Lens 顾问系统的交互界面。它将离线时间线处理、关系分析、RAG 检索、模型管理、安全控制、竞技场评估和圆桌讨论整合为一个可导航的单一界面。

| 目标 | 实现策略 | 面向用户的结果 |
|------|----------|----------------|
| 统一的关系工作空间 | 一个 React 外壳，配备专用页面 | 用户可以在聊天、审阅、竞技场、圆桌讨论和隐私工具之间切换，无需切换应用 |
| 流式优先的顾问体验 | Fetch 流式传输和 SSE 事件流 | 聊天和多智能体回应逐步呈现 |
| 隐私优先的本地操作 | 本地 API 边界、显式数据擦除、无提交的运行时数据 | 敏感用户数据保留在源代码管理之外 |
| 默认安全 | 同意、紧急访问、危机横幅、红线检查 | 高风险交互被拦截并路由到更安全的用户界面状态 |
| 操作可见性 | 仪表板卡片、流程状态、模型测试器、审阅面板 | 开发者和测试用户可以检查系统就绪状态 |

### 1.2 设计原则

```text
┌──────────────────────────────────────────────────────────────────────┐
│                         Web 应用设计原则                             │
├──────────────────────────────────────────────────────────────────────┤
│ 1. 一个外壳，多个有界界面                                              │
│ 2. API 客户端通过 frontend/src/lib/api.ts 集中化                      │
│ 3. 流式传输作为一等交互模式                                            │
│ 4. 隐私控制在产品中可见，而非隐藏在文档中                              │
│ 5. 安全用户界面全局可用，独立于活动功能                                │
│ 6. 功能特定状态保持在其功能边界附近                                    │
└──────────────────────────────────────────────────────────────────────┘
```

### 1.3 应用范围

Web 应用涵盖以下功能区域：

- 仪表板和运行时概览
- 沉浸式顾问聊天
- 人工审阅和分析检查
- 模型配置和模型连通性测试
- 同意、隐私政策和紧急帮助
- 评估和沟通状态
- 知识中心
- 双镜竞技场
- 圆桌讨论
- 本地用户数据擦除
- 反馈收集

---

## 2. 系统架构

### 2.1 高层架构

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                              浏览器运行时                                   │
│                                                                             │
│  React + Vite 应用                                                          │
│  ├─ 应用外壳 / 路径路由                                                     │
│  ├─ 侧边栏 / 顶部导航 / 全局安全控制                                       │
│  ├─ 功能页面                                                              │
│  ├─ 功能存储和本地组件状态                                                  │
│  └─ frontend/src/lib/api.ts API 客户端                                    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      │ HTTP / fetch 流式传输 / EventSource
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            FastAPI 顾问 API                                  │
│                                                                             │
│  scripts/advisor/api/main.py                                                 │
│  ├─ health, data, pipeline, review, models, keys                            │
│  ├─ chat, rag, assessment, safety                                            │
│  ├─ arena, roundtable                                                        │
│  ├─ feedback, user-data                                                      │
│  └─ 全局异常中间件 + CORS                                                   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                      本地运行时数据和模型后端                                │
│                                                                             │
│  advisor_out/ · artifacts/ · timeline_out/ · local_secrets/ · configs/       │
│  OpenAI 兼容 API · 本地 Ollama · RAG 索引 · 审阅工件                        │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 技术栈

| 层级 | 技术 | 主要角色 |
|------|------|----------|
| 前端框架 | React 19 + TypeScript | 组件驱动的单页应用 |
| 构建系统 | Vite | 开发服务器、HMR、生产打包 |
| 样式 | Tailwind CSS + CSS 变量 | 响应式布局、主题感知界面 |
| 动画 | Framer Motion | 导航和仪表板过渡 |
| 图标 | Lucide React | 导航、卡片、控制、安全提示 |
| 通知 | Sonner | 错误、状态变化、用户反馈的提示 |
| 后端 | FastAPI | REST、流式聊天、SSE、本地编排 |
| 流式传输 | Fetch reader + EventSource | 聊天令牌流和圆桌讨论事件多路复用 |

### 2.3 后端路由边界

前端通过 `/api/*` 端点与后端通信。后端在 `scripts/advisor/api/main.py` 中注册路由：

| 路由 | Web 应用使用者 | 职责 |
|------|----------------|------|
| `health` | 应用启动 / 检查 | 服务就绪状态 |
| `data` | 仪表板 | 时间线和分析统计 |
| `pipeline` | 流程面板 | 启动和检查流程阶段 |
| `models_routes` | 模型配置 / 测试器 | 可用模型和偏好 |
| `keys` | API 密钥检查器 | 模型列表获取、批量密钥/模型检查 |
| `review` | 审阅面板 | 人工审阅工作流 |
| `chat` | 聊天页面 | 流式顾问交互 |
| `rag` | 聊天 / 检索界面 | 上下文检索 |
| `assessment` | 评估页面 | 关系评估和注入控制 |
| `arena` | 竞技场页面 | 双重回应比较和投票 |
| `roundtable` | 圆桌讨论页面 | 多智能体讨论和 SSE |
| `safety` | 安全组件 | 危机资源和安全文本 |
| `feedback` | 反馈按钮 | 用户反馈捕获 |
| `user_data` | 数据擦除对话框 | 本地数据删除工作流 |

---

## 3. 前端应用外壳

### 3.1 路由策略

Web 应用使用在 [`frontend/src/App.tsx`](../../frontend/src/App.tsx) 中实现的轻量级浏览器路径路由器。它不依赖完整的路由器库。相反，它将 `window.location.pathname` 映射到 `activeNav` 值并渲染相关页面。

| 路径族 | 活动导航 | 渲染界面 |
|----------|----------|----------|
| `/dashboard` 或 `/` | `dashboard` | 仪表板 |
| `/chat/select-advisor` | `chat` | 欢迎顾问选择 |
| `/chat/:persona` | `chat` | 沉浸式顾问聊天 |
| `/review` | `review` | 人工审阅面板 |
| `/arena` 或 `/dual-mirror` | `arena` | 双镜竞技场 |
| `/assessment` | `assessment` | 沟通评估 |
| `/communication-status` | `communication-status` | 监督状态 |
| `/roundtable` | `roundtable` | 圆桌讨论路由器 |
| `/knowledge-center` | `knowledge-center` | 知识中心 |
| `/consent` | `consent` | 同意页面 |
| `/privacy` | `privacy` | 隐私页面 |
| `/settings` | `settings` | 设置和本地数据控制 |

### 3.2 布局组件

应用外壳由三个持久区域构成：

| 区域 | 文件 | 职责 |
|------|------|------|
| 侧边栏 | [`frontend/src/components/layout/Sidebar.tsx`](../../frontend/src/components/layout/Sidebar.tsx) | 主导航、主题切换、紧急帮助入口、隐私链接 |
| 顶部导航 | `frontend/src/components/layout/TopNav.tsx` | 搜索、会话查找、全局顶部控制 |
| 主内容 | [`frontend/src/App.tsx`](../../frontend/src/App.tsx) | 活动页面渲染和路由状态协调 |

### 3.3 主题与布局状态

外壳维护：

- `theme`: `light` 或 `dark`，应用于 `document.documentElement`。
- `currentPath`: 规范化的浏览器路径。
- `sidebarCollapsed`: 可折叠的导航状态。
- `searchTargetSession`: 来自全局搜索的选定会话，注入到聊天页面。
- `showDataErase`: 设置级别的本地数据擦除对话框状态。

---

## 4. 页面与模块职责

### 4.1 页面清单

| 页面 | 文件 | 主要职责 |
|------|------|----------|
| 仪表板 | [`frontend/src/pages/Dashboard.tsx`](../../frontend/src/pages/Dashboard.tsx) | 系统概览、处理统计、流程/模型面板、活动动态 |
| 欢迎 | [`frontend/src/pages/WelcomeScreen.tsx`](../../frontend/src/pages/WelcomeScreen.tsx) | 顾问选择入口 |
| 聊天 | [`frontend/src/pages/ChatPage.tsx`](../../frontend/src/pages/ChatPage.tsx) | 沉浸式顾问对话、聊天流式传输、会话历史 |
| 竞技场 | [`frontend/src/pages/ArenaPage.tsx`](../../frontend/src/pages/ArenaPage.tsx) | 盲测 A/B 模型或人格比较 |
| 竞技场统计 | [`frontend/src/pages/ArenaStatsPage.tsx`](../../frontend/src/pages/ArenaStatsPage.tsx) | 竞技场排名和 battle 统计 |
| 评估 | [`frontend/src/pages/AssessmentPage.tsx`](../../frontend/src/pages/AssessmentPage.tsx) | 沟通评估和 RAG 注入设置 |
| 沟通状态 | [`frontend/src/pages/CommunicationStatusPage.tsx`](../../frontend/src/pages/CommunicationStatusPage.tsx) | LLM-as-Judge 状态和对话质量信号 |
| 知识中心 | [`frontend/src/pages/KnowledgeCenterPage.tsx`](../../frontend/src/pages/KnowledgeCenterPage.tsx) | 知识库索引和计划资源目录 |
| 同意 | [`frontend/src/pages/ConsentPage.tsx`](../../frontend/src/pages/ConsentPage.tsx) | 知情同意和非医疗范围确认 |
| 隐私 | [`frontend/src/pages/PrivacyPage.tsx`](../../frontend/src/pages/PrivacyPage.tsx) | 隐私政策和数据边界说明 |
| 圆桌讨论设置 | [`frontend/src/pages/RoundtablePage.tsx`](../../frontend/src/pages/RoundtablePage.tsx) | 人格选择、问题输入、后端选择、上下文注入 |
| 圆桌讨论会话 | [`frontend/src/pages/RoundtableSessionPage.tsx`](../../frontend/src/pages/RoundtableSessionPage.tsx) | SSE 驱动的多智能体讨论显示 |

### 4.2 功能分组

| 组 | 页面 / 组件 | 后端依赖 |
|------|--------------------|----------------------|
| 操作 | 仪表板、PipelinePanel、ModelConfig、ActivityFeed | `data`, `pipeline`, `models_routes` |
| 顾问交互 | WelcomeScreen、ChatPage、会话搜索 | `chat`, `rag`, `models_routes`, `safety` |
| 评估 | ArenaPage、ArenaStatsPage、CommunicationStatusPage | `arena`, `assessment`, 监督服务 |
| 审阅 | ReviewPanel | `review` |
| 安全与隐私 | ConsentPage、PrivacyPage、CrisisBanner、EmergencyModal、DataEraseDialog | `safety`, `user_data` |
| 知识 | KnowledgeCenterPage | RAG 资源和静态前端目录 |
| 多智能体讨论 | RoundtablePage、RoundtableSessionPage、圆桌讨论组件 | `roundtable`, `rag`, `models_routes`, `safety` |

---

## 5. API 集成模型

### 5.1 集中式 API 客户端

所有标准 JSON API 调用都集中在 [`frontend/src/lib/api.ts`](../../frontend/src/lib/api.ts) 中。该文件定义：

- 共享的 `apiFetch<T>()` 辅助函数。
- 会话、模型、审阅项、圆桌讨论快照和注入预览的 DTO 类型。
- 功能方法，分组在单个 `api` 对象下。

这避免了跨页面散布端点字符串，并使后端契约变更易于审计。

### 5.2 请求类型

| 交互类型 | 前端模式 | 示例 |
|------------------|------------------|---------|
| JSON 请求/响应 | `apiFetch<T>()` | 模型偏好、审阅决策、评估提交 |
| Fetch 流式传输 | `ReadableStream` reader | 聊天令牌流式传输 |
| EventSource SSE | `new EventSource(...)` | 圆桌讨论事件流 |
| 带确认正文的 DELETE | `apiFetch()` with `DELETE` | 本地数据擦除 |

### 5.3 API 错误策略

共享的 fetch 辅助函数在 `res.ok` 为 false 时抛出包含 HTTP 状态和响应正文的错误。功能页面通常将这些失败转换为：

- 可恢复的用户界面失败的提示通知。
- 功能本地降级状态的内联横幅。
- 持久化会话无法安全恢复时的只读快照。
- 流式聊天后端故障切换场景的结构化错误载荷。

---

## 6. 状态管理边界

### 6.1 状态所有权模型

| 状态类型 | 所有者 | 原因 |
|------------|-------|------|
| 主题、活动路径、侧边栏折叠 | `App.tsx` | 全局外壳问题 |
| 仪表板指标 | 仪表板本地状态 | 定期轮询和页面本地显示 |
| 来自搜索的聊天会话目标 | `App.tsx` → `ChatPage` prop | 跨页面交接 |
| 圆桌讨论会话生命周期 | Zustand store | 由设置页面、会话页面、SSE 钩子和历史恢复共享 |
| 功能表单和抽屉 | 本地组件状态 | 避免不必要的全局耦合 |

### 6.2 圆桌讨论例外

圆桌讨论是使用专用全局存储的主要功能，因为其状态跨越：

- 设置页面，
- 会话页面，
- SSE 事件处理，
- 多轮历史，
- 只读快照模式，
- 危机事件，
- 主持人输出。

有关完整状态机，请参阅 [Roundtable Discussion System Design](roundtable_discussion_overview.md)。

---

## 7. 流式与实时交互

### 7.1 聊天流式传输

聊天通过 [`frontend/src/lib/api.ts`](../../frontend/src/lib/api.ts) 中的 `api.chatStream()` 使用 fetch 流式传输。读取器解析 `data: ...` 行并产出：

- 助手内容令牌，
- 思考令牌，
- 思考完成标记，
- 最终会话 id 标记，
- 结构化错误载荷。

### 7.2 圆桌讨论 SSE

圆桌讨论通过 [`frontend/src/hooks/useRoundtableStream.ts`](../../frontend/src/hooks/useRoundtableStream.ts) 使用 EventSource。后端通过一个 SSE 端点发送类型化的 JSON 事件，前端将它们分发到特定人格的缓冲区。

### 7.3 轮询

仪表板每 15 秒轮询一次数据统计和会话，以保持操作卡片更新，而无需持久 WebSocket。

---

## 8. 安全、同意与隐私界面

### 8.1 同意界面

同意页面和模态框说明 Lens 是关系反思和数据处理工具，而非医疗、心理治疗、危机咨询或紧急干预服务。

### 8.2 危机界面

安全用户界面出现在多个层级：

| 界面 | 角色 |
|---------|------|
| 侧边栏紧急按钮 | 始终可用的紧急资源入口 |
| CrisisBanner | 显示后端检测到的危机级别状态 |
| 安全路由 | 提供危机资源和固定安全回应 |
| 聊天 / 竞技场 / 圆桌讨论集成 | 将危机事件路由到功能特定的中断或警告状态 |

### 8.3 隐私界面

隐私控制包括：

- 描述数据边界的隐私页面。
- 用于本地用户数据删除的数据擦除对话框。
- 代码和运行时数据之间的 `.gitignore` 分离。
- 本地密钥保存在 `local_secrets/` 下并置于公开提交之外。

---

## 9. 仪表板与操作用户体验

### 9.1 仪表板卡片

[`Dashboard.tsx`](../../frontend/src/pages/Dashboard.tsx) 导出四个高级指标：

| 卡片 | 数据来源 | 含义 |
|------|-------------|---------|
| 已处理消息 | L1/L2 行计数 | 可用的规范化数据量 |
| 分析完成度 | 分析与块数对比 | 离线分析覆盖率 |
| 活动会话 | 聊天会话列表 | 在线交互足迹 |
| 总块数 | 块数和测试行数 | 训练/评估数据规模 |

### 9.2 操作面板

仪表板包括：

- `PipelinePanel`：流程状态和启动控制。
- `ModelConfig`：模型偏好控制。
- `ActivityFeed`：近期系统活动。

这些面板有意放置在第一屏，因为测试用户通常需要在使用聊天或评估功能之前诊断后端就绪状态。

---

## 10. 按功能的数据流

### 10.1 仪表板数据流

```text
仪表板挂载
  ├─ api.getDataStats()
  ├─ api.listSessions()
  ├─ 派生卡片
  └─ 每 15 秒重复
```

### 10.2 聊天数据流

```text
用户选择顾问人格
  └─ ChatPage 构建聊天请求
      └─ POST /api/chat with stream=true
          ├─ 内容令牌
          ├─ 思考令牌
          ├─ 结构化后端错误
          └─ 最终会话 id
```

### 10.3 审阅数据流

```text
ReviewPanel
  ├─ GET /api/review/items
  ├─ GET /api/review/items/{id}
  └─ POST /api/review/items/{id}
      └─ 批准 / 拒绝 / 编辑
```

### 10.4 竞技场数据流

```text
ArenaPage
  ├─ POST /api/arena/chat
  ├─ 默认不揭示身份渲染回应 A/B
  ├─ 收集投票和分数
  └─ POST /api/arena/vote
```

### 10.5 圆桌讨论数据流

圆桌讨论有自己的多阶段状态机和 SSE 协议。请参阅 [Roundtable Discussion System Design](roundtable_discussion_overview.md)。

---

## 11. 前端构建与运行时

### 11.1 开发运行时

前端是 `frontend/` 下的 Vite 应用。后端 API 期望浏览器在 `/api/*` 下调用。在本地开发中，这通常由 Vite 开发服务器代理处理，或者通过在共享本地来源后提供前端和 API 来处理。

### 11.2 生产构建

前端构建输出静态资源。API 保持为单独的 FastAPI 进程。Electron 打包在 [Electron Build](../ELECTRON_BUILD.md) 中单独记录。

### 11.3 样式运行时

用户界面使用 CSS 变量表示主题颜色，Tailwind 类用于布局和组件。在需要时静态枚举人格和圆桌讨论颜色类，以便 Tailwind 可以在生产构建期间保留它们。

---

## 12. 集成点

| 集成 | 前端文件 | 后端 / 配置文件 | 备注 |
|-------------|---------------|------------------------|-------|
| 应用外壳 | [`frontend/src/App.tsx`](../../frontend/src/App.tsx) | [`scripts/advisor/api/main.py`](../../scripts/advisor/api/main.py) | 浏览器路径映射到 FastAPI 支持的功能页面 |
| API 客户端 | [`frontend/src/lib/api.ts`](../../frontend/src/lib/api.ts) | `scripts/advisor/api/routes/` | 集中端点契约 |
| 聊天 | `frontend/src/pages/ChatPage.tsx` | `scripts/advisor/api/routes/chat.py` | 流式顾问回应 |
| 仪表板 | [`frontend/src/pages/Dashboard.tsx`](../../frontend/src/pages/Dashboard.tsx) | `data.py`, `pipeline.py`, `models_routes.py` | 运行时和流程可见性 |
| 竞技场 | [`frontend/src/pages/ArenaPage.tsx`](../../frontend/src/pages/ArenaPage.tsx) | `arena.py` | A/B 评估和投票 |
| 圆桌讨论 | [`frontend/src/pages/RoundtablePage.tsx`](../../frontend/src/pages/RoundtablePage.tsx) | [`scripts/advisor/api/routes/roundtable.py`](../../scripts/advisor/api/routes/roundtable.py) | 多智能体 SSE 讨论 |
| 安全 | `CrisisBanner`, `EmergencyModal`, 同意界面 | `safety.py`, `crisis_detector.py` | 高风险语言检测和资源 |
| 用户数据删除 | `DataEraseDialog` | `user_data.py` | 确认的本地删除工作流 |

---

## 13. 已知限制与演进方向

| 领域 | 当前状态 | 演进方向 |
|------|----------|----------|
| 路由 | 轻量级路径状态路由器 | 如果嵌套路由增长，可以迁移到正式路由器 |
| 全局状态 | 大部分是本地状态，圆桌讨论使用 Zustand | 仅在状态跨越多个页面/钩子时添加功能存储 |
| API 契约 | TypeScript DTO 手动镜像后端模型 | 如果端点稳定，从 OpenAPI 生成 API 类型 |
| 流式恢复 | 聊天和圆桌讨论按功能处理错误 | 添加共享的流式诊断和重试策略 |
| 仪表板轮询 | 固定 15 秒轮询 | 如果需要，移至服务器发送的操作事件 |
| 访问控制 | 面向本地测试的应用 | 仅在部署到本地/私有环境之外时添加身份验证 |
| 文档 | 按子系统拆分的架构文档 | 在用户界面稳定后添加截图和序列图 |

---

## 14. 文件索引

| 文件 | 职责 |
|------|------|
| [`frontend/src/App.tsx`](../../frontend/src/App.tsx) | 应用外壳、路径路由、活动页面渲染 |
| [`frontend/src/components/layout/Sidebar.tsx`](../../frontend/src/components/layout/Sidebar.tsx) | 主导航、主题切换、紧急入口 |
| [`frontend/src/lib/api.ts`](../../frontend/src/lib/api.ts) | 集中式前端 API 客户端和 DTO 定义 |
| [`frontend/src/pages/Dashboard.tsx`](../../frontend/src/pages/Dashboard.tsx) | 运行时概览和仪表板组合 |
| [`frontend/src/pages/ChatPage.tsx`](../../frontend/src/pages/ChatPage.tsx) | 沉浸式顾问聊天 |
| [`frontend/src/pages/ArenaPage.tsx`](../../frontend/src/pages/ArenaPage.tsx) | 双镜竞技场用户界面 |
| [`frontend/src/pages/RoundtablePage.tsx`](../../frontend/src/pages/RoundtablePage.tsx) | 圆桌讨论设置用户界面 |
| [`frontend/src/pages/RoundtableSessionPage.tsx`](../../frontend/src/pages/RoundtableSessionPage.tsx) | 圆桌讨论 SSE 会话用户界面 |
| [`scripts/advisor/api/main.py`](../../scripts/advisor/api/main.py) | FastAPI 应用组装和路由注册 |
| [`scripts/advisor/api/routes/roundtable.py`](../../scripts/advisor/api/routes/roundtable.py) | 圆桌讨论 API 端点 |

---

**文档版本**：v1.0  
**创建日期**：2026-06-13  
**相关文档**：[Advisor Service Overview](../advisor/advisor_service_overview.md)、[Arena Dual-Mirror System](../pipelines/arena_dual_mirror_overview.md)、[Roundtable Discussion System Design](roundtable_discussion_overview.md)

---

# Advisor Web Application System Design

> 📌 **Document scope**: This document describes the Lens Advisor Web Application as an application-layer system, including frontend routing, page responsibilities, API integration, state boundaries, safety surfaces, privacy controls, and operational constraints.
>
> Updated: 2026-06-13

---

## Table of Contents

- [1. Design Goals](#1-design-goals)
- [2. System Architecture](#2-system-architecture)
- [3. Frontend Application Shell](#3-frontend-application-shell)
- [4. Page and Module Responsibilities](#4-page-and-module-responsibilities)
- [5. API Integration Model](#5-api-integration-model)
- [6. State Management Boundaries](#6-state-management-boundaries)
- [7. Streaming and Real-Time Interactions](#7-streaming-and-real-time-interactions)
- [8. Safety, Consent, and Privacy Surfaces](#8-safety-consent-and-privacy-surfaces)
- [9. Dashboard and Operations UX](#9-dashboard-and-operations-ux)
- [10. Data Flow by Feature](#10-data-flow-by-feature)
- [11. Frontend Build and Runtime](#11-frontend-build-and-runtime)
- [12. Integration Points](#12-integration-points)
- [13. Known Limits and Evolution](#13-known-limits-and-evolution)
- [14. File Index](#14-file-index)

---

## 1. Design Goals

### 1.1 Product Role

The Web App is the interactive surface of the Lens Advisor system. It turns offline timeline processing, relationship analysis, RAG retrieval, model management, safety controls, Arena evaluation, and Roundtable discussion into a single navigable interface.

| Goal | Implementation Strategy | User-Facing Result |
|------|-------------------------|--------------------|
| Unified relationship workspace | One React shell with dedicated pages | Users can move between chat, review, Arena, Roundtable, and privacy tools without switching apps |
| Stream-first advisor experience | Fetch streaming and SSE event streams | Chat and multi-agent responses appear incrementally |
| Privacy-first local operation | Local API boundary, explicit data erase, no committed runtime data | Sensitive user data remains outside source control |
| Safety by default | Consent, emergency access, crisis banners, red-line checks | High-risk interactions are intercepted and routed to safer UI states |
| Operational visibility | Dashboard cards, pipeline status, model tester, review panels | Developers and beta users can inspect system readiness |

### 1.2 Design Principles

```text
┌──────────────────────────────────────────────────────────────────────┐
│                         Web App Design Principles                    │
├──────────────────────────────────────────────────────────────────────┤
│ 1. One shell, many bounded surfaces                                  │
│ 2. API-client centralization through frontend/src/lib/api.ts          │
│ 3. Streaming as a first-class interaction pattern                    │
│ 4. Privacy controls visible in the product, not hidden in docs        │
│ 5. Safety UI available globally, independent of the active feature    │
│ 6. Feature-specific state stays close to its feature boundary         │
└──────────────────────────────────────────────────────────────────────┘
```

### 1.3 Application Scope

The Web App covers these functional areas:

- Dashboard and runtime overview
- Immersive advisor chat
- Human review and analysis inspection
- Model configuration and model connectivity testing
- Consent, privacy policy, and emergency help
- Assessment and communication status
- Knowledge Center
- Dual-Mirror Arena
- Roundtable Discussion
- Local user-data erasure
- Feedback collection

---

## 2. System Architecture

### 2.1 High-Level Architecture

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Browser Runtime                                │
│                                                                             │
│  React + Vite App                                                           │
│  ├─ App shell / path routing                                                │
│  ├─ Sidebar / top navigation / global safety controls                       │
│  ├─ Feature pages                                                           │
│  ├─ Feature stores and local component state                                │
│  └─ frontend/src/lib/api.ts API client                                      │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      │ HTTP / fetch streaming / EventSource
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            FastAPI Advisor API                               │
│                                                                             │
│  scripts/advisor/api/main.py                                                 │
│  ├─ health, data, pipeline, review, models, keys                            │
│  ├─ chat, rag, assessment, safety                                            │
│  ├─ arena, roundtable                                                        │
│  ├─ feedback, user-data                                                      │
│  └─ global exception middleware + CORS                                       │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                      Local Runtime Data and Model Backends                   │
│                                                                             │
│  advisor_out/ · artifacts/ · timeline_out/ · local_secrets/ · configs/       │
│  OpenAI-compatible APIs · local Ollama · RAG indexes · review artifacts      │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Technology Stack

| Layer | Technology | Primary Role |
|-------|------------|--------------|
| Frontend framework | React 19 + TypeScript | Component-driven single-page application |
| Build system | Vite | Dev server, HMR, production bundling |
| Styling | Tailwind CSS + CSS variables | Responsive layout, theme-aware surfaces |
| Animation | Framer Motion | Navigation and dashboard transitions |
| Icons | Lucide React | Navigation, cards, controls, safety affordances |
| Notifications | Sonner | Toasts for errors, state changes, user feedback |
| Backend | FastAPI | REST, streaming chat, SSE, local orchestration |
| Streaming | Fetch reader + EventSource | Chat token streaming and Roundtable event multiplexing |

### 2.3 Backend Router Boundary

The frontend talks to the backend through `/api/*` endpoints. The backend registers routers in `scripts/advisor/api/main.py`:

| Router | Web App Consumer | Responsibility |
|--------|------------------|----------------|
| `health` | app startup / checks | Service readiness |
| `data` | Dashboard | Timeline and analysis statistics |
| `pipeline` | Pipeline panel | Launch and inspect pipeline phases |
| `models_routes` | Model config / tester | Available models and preferences |
| `keys` | API key checker | Model-list fetch, batch key/model checks |
| `review` | Review panel | Human review workflow |
| `chat` | Chat page | Streaming advisor interaction |
| `rag` | Chat / retrieval surfaces | Context retrieval |
| `assessment` | Assessment page | Relationship assessment and injection control |
| `arena` | Arena page | Dual response comparison and voting |
| `roundtable` | Roundtable pages | Multi-agent discussion and SSE |
| `safety` | Safety components | Crisis resources and safety text |
| `feedback` | Feedback button | User feedback capture |
| `user_data` | Data erase dialog | Local data deletion workflow |

---

## 3. Frontend Application Shell

### 3.1 Routing Strategy

The Web App uses a lightweight browser-path router implemented in [`frontend/src/App.tsx`](../../frontend/src/App.tsx). It does not depend on a full router library. Instead, it maps `window.location.pathname` to an `activeNav` value and renders the relevant page.

| Path Family | Active Nav | Rendered Surface |
|-------------|------------|------------------|
| `/dashboard` or `/` | `dashboard` | Dashboard |
| `/chat/select-advisor` | `chat` | Welcome advisor selection |
| `/chat/:persona` | `chat` | Immersive advisor chat |
| `/review` | `review` | Human review panel |
| `/arena` or `/dual-mirror` | `arena` | Dual-Mirror Arena |
| `/assessment` | `assessment` | Communication assessment |
| `/communication-status` | `communication-status` | Supervision status |
| `/roundtable` | `roundtable` | Roundtable router |
| `/knowledge-center` | `knowledge-center` | Knowledge Center |
| `/consent` | `consent` | Consent page |
| `/privacy` | `privacy` | Privacy page |
| `/settings` | `settings` | Settings and local data controls |

### 3.2 Layout Components

The application shell is built from three persistent zones:

| Zone | File | Responsibility |
|------|------|----------------|
| Sidebar | [`frontend/src/components/layout/Sidebar.tsx`](../../frontend/src/components/layout/Sidebar.tsx) | Primary navigation, theme toggle, emergency help entry, privacy link |
| Top navigation | `frontend/src/components/layout/TopNav.tsx` | Search, session lookup, global top controls |
| Main content | [`frontend/src/App.tsx`](../../frontend/src/App.tsx) | Active page rendering and route-state coordination |

### 3.3 Theme and Layout State

The shell maintains:

- `theme`: `light` or `dark`, applied to `document.documentElement`.
- `currentPath`: normalized browser path.
- `sidebarCollapsed`: collapsible navigation state.
- `searchTargetSession`: selected session from global search, injected into Chat page.
- `showDataErase`: settings-level local data erase dialog state.

---

## 4. Page and Module Responsibilities

### 4.1 Page Inventory

| Page | File | Primary Responsibility |
|------|------|------------------------|
| Dashboard | [`frontend/src/pages/Dashboard.tsx`](../../frontend/src/pages/Dashboard.tsx) | System overview, processing statistics, pipeline/model panels, activity feed |
| Welcome | [`frontend/src/pages/WelcomeScreen.tsx`](../../frontend/src/pages/WelcomeScreen.tsx) | Advisor selection entry |
| Chat | [`frontend/src/pages/ChatPage.tsx`](../../frontend/src/pages/ChatPage.tsx) | Immersive advisor conversation, chat streaming, session history |
| Arena | [`frontend/src/pages/ArenaPage.tsx`](../../frontend/src/pages/ArenaPage.tsx) | Blind A/B model or persona comparison |
| Arena Stats | [`frontend/src/pages/ArenaStatsPage.tsx`](../../frontend/src/pages/ArenaStatsPage.tsx) | Arena ranking and battle statistics |
| Assessment | [`frontend/src/pages/AssessmentPage.tsx`](../../frontend/src/pages/AssessmentPage.tsx) | Communication assessment and RAG injection settings |
| Communication Status | [`frontend/src/pages/CommunicationStatusPage.tsx`](../../frontend/src/pages/CommunicationStatusPage.tsx) | LLM-as-Judge status and conversation quality signals |
| Knowledge Center | [`frontend/src/pages/KnowledgeCenterPage.tsx`](../../frontend/src/pages/KnowledgeCenterPage.tsx) | Knowledge-base index and planned resource catalog |
| Consent | [`frontend/src/pages/ConsentPage.tsx`](../../frontend/src/pages/ConsentPage.tsx) | Informed consent and non-medical scope acknowledgement |
| Privacy | [`frontend/src/pages/PrivacyPage.tsx`](../../frontend/src/pages/PrivacyPage.tsx) | Privacy policy and data boundary explanation |
| Roundtable Setup | [`frontend/src/pages/RoundtablePage.tsx`](../../frontend/src/pages/RoundtablePage.tsx) | Persona selection, question entry, backend selection, context injection |
| Roundtable Session | [`frontend/src/pages/RoundtableSessionPage.tsx`](../../frontend/src/pages/RoundtableSessionPage.tsx) | SSE-driven multi-agent discussion display |

### 4.2 Feature Grouping

| Group | Pages / Components | Backend Dependencies |
|-------|--------------------|----------------------|
| Operations | Dashboard, PipelinePanel, ModelConfig, ActivityFeed | `data`, `pipeline`, `models_routes` |
| Advisor interaction | WelcomeScreen, ChatPage, session search | `chat`, `rag`, `models_routes`, `safety` |
| Evaluation | ArenaPage, ArenaStatsPage, CommunicationStatusPage | `arena`, `assessment`, supervision services |
| Review | ReviewPanel | `review` |
| Safety and privacy | ConsentPage, PrivacyPage, CrisisBanner, EmergencyModal, DataEraseDialog | `safety`, `user_data` |
| Knowledge | KnowledgeCenterPage | RAG resources and static frontend catalog |
| Multi-agent discussion | RoundtablePage, RoundtableSessionPage, roundtable components | `roundtable`, `rag`, `models_routes`, `safety` |

---

## 5. API Integration Model

### 5.1 Central API Client

All standard JSON API calls are centralized in [`frontend/src/lib/api.ts`](../../frontend/src/lib/api.ts). The file defines:

- Shared `apiFetch<T>()` helper.
- DTO types for sessions, models, review items, Roundtable snapshots, and injection previews.
- Feature methods grouped under a single `api` object.

This avoids scattering endpoint strings across pages and keeps backend contract changes easy to audit.

### 5.2 Request Types

| Interaction Type | Frontend Pattern | Example |
|------------------|------------------|---------|
| JSON request/response | `apiFetch<T>()` | model preferences, review decisions, assessment submission |
| Fetch streaming | `ReadableStream` reader | chat token streaming |
| EventSource SSE | `new EventSource(...)` | Roundtable event stream |
| DELETE with confirmation body | `apiFetch()` with `DELETE` | local data erasure |

### 5.3 API Error Strategy

The shared fetch helper throws an error with HTTP status and response body when `res.ok` is false. Feature pages generally translate these failures into:

- Toast notifications for recoverable UI failures.
- Inline banners for feature-local degraded state.
- Read-only snapshots when a persisted session cannot safely resume.
- Structured error payloads for streaming chat backend failover cases.

---

## 6. State Management Boundaries

### 6.1 State Ownership Model

| State Type | Owner | Reason |
|------------|-------|--------|
| Theme, active path, sidebar collapse | `App.tsx` | Global shell concerns |
| Dashboard metrics | Dashboard local state | Periodic polling and page-local display |
| Chat session target from search | `App.tsx` → `ChatPage` prop | Cross-page handoff |
| Roundtable session lifecycle | Zustand store | Shared by setup page, session page, SSE hook, and history restore |
| Feature forms and drawers | Local component state | Avoid unnecessary global coupling |

### 6.2 Roundtable Exception

Roundtable is the main feature that uses a dedicated global store because its state spans:

- setup page,
- session page,
- SSE event handling,
- multi-round history,
- read-only snapshot mode,
- crisis events,
- moderator output.

See [Roundtable Discussion System Design](roundtable_discussion_overview.md) for the full state machine.

---

## 7. Streaming and Real-Time Interactions

### 7.1 Chat Streaming

Chat uses fetch streaming through `api.chatStream()` in [`frontend/src/lib/api.ts`](../../frontend/src/lib/api.ts). The reader parses `data: ...` lines and yields:

- assistant content tokens,
- thinking tokens,
- thinking completion markers,
- final session id markers,
- structured error payloads.

### 7.2 Roundtable SSE

Roundtable uses EventSource via [`frontend/src/hooks/useRoundtableStream.ts`](../../frontend/src/hooks/useRoundtableStream.ts). The backend sends typed JSON events through one SSE endpoint, and the frontend dispatches them into persona-specific buffers.

### 7.3 Polling

Dashboard polls data stats and sessions every 15 seconds to keep operational cards fresh without requiring a persistent WebSocket.

---

## 8. Safety, Consent, and Privacy Surfaces

### 8.1 Consent Surface

The Consent page and modal communicate that Lens is a relationship reflection and data-processing tool, not a medical, psychotherapy, crisis counseling, or emergency intervention service.

### 8.2 Crisis Surface

Safety UI appears at multiple levels:

| Surface | Role |
|---------|------|
| Sidebar emergency button | Always-available emergency resource entry |
| CrisisBanner | Shows crisis-level state detected by backend |
| Safety routes | Provide crisis resources and fixed safety responses |
| Chat / Arena / Roundtable integrations | Route crisis events into feature-specific interruption or warning states |

### 8.3 Privacy Surface

Privacy controls include:

- Privacy page describing data boundaries.
- Data erase dialog for local user data deletion.
- `.gitignore` separation between code and runtime data.
- Local secrets kept under `local_secrets/` and outside public commits.

---

## 9. Dashboard and Operations UX

### 9.1 Dashboard Cards

[`Dashboard.tsx`](../../frontend/src/pages/Dashboard.tsx) derives four high-level indicators:

| Card | Data Source | Meaning |
|------|-------------|---------|
| Processed messages | L1/L2 line counts | Amount of normalized data available |
| Analysis completion | analyses vs chunks | Offline analysis coverage |
| Active sessions | chat session list | Online interaction footprint |
| Chunks total | chunk count and test lines | Training/evaluation data scale |

### 9.2 Operations Panels

Dashboard includes:

- `PipelinePanel`: pipeline status and launch controls.
- `ModelConfig`: model preference controls.
- `ActivityFeed`: recent system activity.

These panels are intentionally placed on the first screen because beta users often need to diagnose backend readiness before using chat or evaluation features.

---

## 10. Data Flow by Feature

### 10.1 Dashboard Data Flow

```text
Dashboard mount
  ├─ api.getDataStats()
  ├─ api.listSessions()
  ├─ derive cards
  └─ repeat every 15 seconds
```

### 10.2 Chat Data Flow

```text
User selects advisor persona
  └─ ChatPage builds chat request
      └─ POST /api/chat with stream=true
          ├─ content tokens
          ├─ thinking tokens
          ├─ structured backend errors
          └─ final session id
```

### 10.3 Review Data Flow

```text
ReviewPanel
  ├─ GET /api/review/items
  ├─ GET /api/review/items/{id}
  └─ POST /api/review/items/{id}
      └─ approve / reject / edit
```

### 10.4 Arena Data Flow

```text
ArenaPage
  ├─ POST /api/arena/chat
  ├─ render response A/B without revealing identity by default
  ├─ collect vote and scores
  └─ POST /api/arena/vote
```

### 10.5 Roundtable Data Flow

Roundtable has its own multi-phase state machine and SSE protocol. See [Roundtable Discussion System Design](roundtable_discussion_overview.md).

---

## 11. Frontend Build and Runtime

### 11.1 Development Runtime

The frontend is a Vite app under `frontend/`. The backend API expects browser calls under `/api/*`. In local development this is typically handled by the Vite dev server proxy or by serving the frontend and API behind a shared local origin.

### 11.2 Production Build

The frontend build outputs static assets. The API remains a separate FastAPI process. Electron packaging is documented separately in [Electron Build](../ELECTRON_BUILD.md).

### 11.3 Styling Runtime

The UI uses CSS variables for theme colors and Tailwind classes for layout and components. Persona and Roundtable color classes are statically enumerated where needed so Tailwind can preserve them during production builds.

---

## 12. Integration Points

| Integration | Frontend File | Backend / Config File | Notes |
|-------------|---------------|------------------------|-------|
| App shell | [`frontend/src/App.tsx`](../../frontend/src/App.tsx) | [`scripts/advisor/api/main.py`](../../scripts/advisor/api/main.py) | Browser path mapped to FastAPI-backed feature pages |
| API client | [`frontend/src/lib/api.ts`](../../frontend/src/lib/api.ts) | `scripts/advisor/api/routes/` | Central endpoint contract |
| Chat | `frontend/src/pages/ChatPage.tsx` | `scripts/advisor/api/routes/chat.py` | Streaming advisor responses |
| Dashboard | [`frontend/src/pages/Dashboard.tsx`](../../frontend/src/pages/Dashboard.tsx) | `data.py`, `pipeline.py`, `models_routes.py` | Runtime and pipeline visibility |
| Arena | [`frontend/src/pages/ArenaPage.tsx`](../../frontend/src/pages/ArenaPage.tsx) | `arena.py` | A/B evaluation and voting |
| Roundtable | [`frontend/src/pages/RoundtablePage.tsx`](../../frontend/src/pages/RoundtablePage.tsx) | [`scripts/advisor/api/routes/roundtable.py`](../../scripts/advisor/api/routes/roundtable.py) | Multi-agent SSE discussion |
| Safety | `CrisisBanner`, `EmergencyModal`, consent surfaces | `safety.py`, `crisis_detector.py` | High-risk language detection and resources |
| User data deletion | `DataEraseDialog` | `user_data.py` | Confirmed local deletion workflow |

---

## 13. Known Limits and Evolution

| Area | Current State | Evolution Direction |
|------|---------------|--------------------|
| Routing | Lightweight path-state router | Could migrate to a formal router if nested routes grow |
| Global state | Mostly local state, Roundtable uses Zustand | Add feature stores only when state spans multiple pages/hooks |
| API contract | TypeScript DTOs manually mirror backend models | Generate API types from OpenAPI if endpoints stabilize |
| Streaming recovery | Chat and Roundtable handle errors feature-by-feature | Add shared streaming diagnostics and retry policy |
| Dashboard polling | Fixed 15-second polling | Move to server-sent operational events if needed |
| Access control | Local beta-oriented app | Add auth only if deployed beyond local/private environments |
| Documentation | Architecture docs split by subsystem | Add screenshots and sequence diagrams after UI stabilizes |

---

## 14. File Index

| File | Responsibility |
|------|----------------|
| [`frontend/src/App.tsx`](../../frontend/src/App.tsx) | Application shell, path routing, active page rendering |
| [`frontend/src/components/layout/Sidebar.tsx`](../../frontend/src/components/layout/Sidebar.tsx) | Primary navigation, theme toggle, emergency entry |
| [`frontend/src/lib/api.ts`](../../frontend/src/lib/api.ts) | Central frontend API client and DTO definitions |
| [`frontend/src/pages/Dashboard.tsx`](../../frontend/src/pages/Dashboard.tsx) | Runtime overview and dashboard composition |
| [`frontend/src/pages/ChatPage.tsx`](../../frontend/src/pages/ChatPage.tsx) | Immersive advisor chat |
| [`frontend/src/pages/ArenaPage.tsx`](../../frontend/src/pages/ArenaPage.tsx) | Dual-Mirror Arena UI |
| [`frontend/src/pages/RoundtablePage.tsx`](../../frontend/src/pages/RoundtablePage.tsx) | Roundtable setup UI |
| [`frontend/src/pages/RoundtableSessionPage.tsx`](../../frontend/src/pages/RoundtableSessionPage.tsx) | Roundtable SSE session UI |
| [`scripts/advisor/api/main.py`](../../scripts/advisor/api/main.py) | FastAPI app assembly and router registration |
| [`scripts/advisor/api/routes/roundtable.py`](../../scripts/advisor/api/routes/roundtable.py) | Roundtable API endpoints |

---

**Document version**: v1.0  
**Created**: 2026-06-13  
**Related documents**: [Advisor Service Overview](../advisor/advisor_service_overview.md), [Arena Dual-Mirror System](../pipelines/arena_dual_mirror_overview.md), [Roundtable Discussion System Design](roundtable_discussion_overview.md)
