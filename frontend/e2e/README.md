# D5.7 · 档 2 · Playwright E2E 测试

> 首次引入：2026-05-02（D5.7 · Beta 前收尾）
> 补位策略：档 1 的 Vitest 集成测试（`src/__tests__/integration/`）已覆盖 14 个场景·档 2 提供真浏览器级验证路径·按需激活。

---

## 目录结构

```
frontend/
  playwright.config.ts         配置：testDir=./e2e · 单 worker · webServer=dev
  e2e/
    README.md                  本文档
    fixtures/
      sse.ts                   SSE 事件流伪造工具（page.route 拦截）
    roundtable_normal.spec.ts  正常流：选 persona → 提问 → phase1/2/3 → Moderator
    roundtable_multiround.spec.ts  多轮 continue：完成 1 轮 → 继续追问 → 第 2 轮
    roundtable_mobile.spec.ts  Mobile 视口：iPhone 13 · 单列 agent grid
```

---

## 一次性 bootstrap（首次跑前）

```bash
cd frontend
npm install -D @playwright/test     # ~50 MB
npx playwright install chromium     # ~150 MB · 一次性下载 Chromium
```

> 如果网络慢：`PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright/ npx playwright install chromium`

---

## 跑测试

```bash
# 全量 headless（CI 模式）
npm run test:e2e

# 可视化（能看到浏览器实际点击）
npm run test:e2e -- --headed

# 交互式调试（推荐开发期用）
npm run test:e2e -- --ui

# 只跑单文件
npm run test:e2e -- roundtable_normal

# 只跑 mobile 项目
npm run test:e2e -- --project=chromium-mobile
```

---

## 设计决策

### 1. 不依赖真 backend · 用 `page.route` 拦截

圆桌讨论的 SSE 流（`GET /api/roundtable/stream/:id`）在 e2e 里用 `fixtures/sse.ts` 的 `mockRoundtableSse(page, events)` 伪造·每条 spec 构造自己的事件序列。

好处：
- 不用起 uvicorn · 启动快 3 秒
- 确定性（不受 LLM 限流影响）
- 可以专注测**前端响应**而不是**backend 输出**

### 2. 单 worker · 禁用并行

zustand store 是进程级单例·多 worker 并行会互相污染。选用 `workers: 1 + fullyParallel: false`。

### 3. 两个 project · desktop + mobile

- `chromium-desktop` · Desktop Chrome 默认 viewport (1280×720)
- `chromium-mobile` · iPhone 13 · 390×844 · 只跑带 `@mobile` grep 标签的 case

### 4. webServer 自动管理

`webServer.reuseExistingServer = !CI`：本地开着 dev 就复用，避免端口冲突；CI 里强制独立启动。

---

## 与档 1 的关系

| 维度 | 档 1（Vitest 集成） | 档 2（Playwright） |
|:---|:---|:---|
| 启动成本 | 几秒 | 10+ 秒（浏览器启动） |
| 依赖 | 仅 Node | Node + Chromium 二进制 |
| 验证层 | 组件 + store + dispatcher | 真 DOM + 真 SSE + 真 routing |
| CI 友好 | ✅ 秒级反馈 | 🟡 1-2 分钟 |
| 覆盖点 | 内部状态 / 组件渲染 | 用户视角端到端 |

**建议节奏**：
- PR 每次提交跑档 1（~1 秒）
- 每周或版本发布前跑档 2（~2 分钟）
- Beta 期新功能进档 2 · 未来可以加 webkit / firefox

---

## 问题排查

| 症状 | 可能原因 | 修复 |
|:---|:---|:---|
| `Executable doesn't exist at .../chromium/...` | 没跑 `npx playwright install chromium` | 装一次即可 |
| `Error: webServer didn't start in time` | 5173 端口被占 | `lsof -i:5173` 杀进程或改 `VITE_PORT` |
| `page.route` 拦截没生效 | spec 里 route 注册在 goto 之后 | 必须先 route 再 goto |
| SSE 事件收不到 | fixture 没正确模拟 `text/event-stream` content-type | 确保 header + `data: ...\n\n` 格式 |

---

## 参考

- Playwright 官方文档：<https://playwright.dev>
- 档 1 实现：`@<PROJECT_ROOT>/frontend/src/__tests__/integration/`
- SSE 协议规范：`@<PROJECT_ROOT>/scripts/advisor/api/services/roundtable_service.py`（`_emit` 函数族）
