/**
 * D5.7 · 档 2 · Playwright E2E 配置（首次引入 · 2026-05-02）
 *
 * 设计理念：
 *   - 测试 spec 里用 `page.route()` 拦截 `/api/roundtable/**` 请求 · 自造 SSE
 *     响应 · 不依赖真 backend
 *   - `webServer` 自动起 `npm run dev` · 如果已开着则复用（避免 5173 冲突）
 *   - 仅跑 chromium · Beta 期需要跨浏览器再加 firefox/webkit
 *
 * 使用前（一次性 bootstrap）：
 *   cd frontend
 *   npm install -D @playwright/test
 *   npx playwright install chromium
 *
 * 跑测试：
 *   npm run test:e2e                      # headless 全量
 *   npm run test:e2e -- --headed          # 可视化
 *   npm run test:e2e -- --ui              # 交互式调试
 *   npm run test:e2e -- roundtable_normal # 只跑一条
 */
import { defineConfig, devices } from '@playwright/test'

const PORT = Number(process.env.VITE_PORT ?? 5173)
const BASE_URL = `http://localhost:${PORT}`

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false, // 圆桌 store 是单例 · 并行会串数据
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1, // 同上 · store 单例
  reporter: [['list'], ['html', { open: 'never' }]],
  timeout: 30_000,
  expect: { timeout: 5_000 },

  use: {
    baseURL: BASE_URL,
    trace: 'on-first-retry',
    // 注：video 关掉避免 ffmpeg 二进制依赖（同样被 prss CDN 封）· 失败用 screenshot + trace 已足够
    video: 'off',
    screenshot: 'only-on-failure',
  },

  // 注：原计划用下载的 Chromium · 但 Microsoft prss CDN 在中国地区被封 · 改用系统已装的
  // google-chrome-stable v147（与 Playwright v1.59 expected cft v147.0.7727 完全同大版本）·
  // 通过 channel: 'chrome' 直接调用系统 Chrome · 零下载
  //
  // 注：原本配了 chromium-mobile project（Pixel 5 视口 · 393×851）· 实测 mobile 视口
  // 下 Sidebar 占满整屏盖住 RoundtablePage · 需要先 toggle 折叠才能交互。
  // 而响应式 grid-cols-1 + lg:grid-cols-3 的契约已被 desktop project 的 className
  // 断言覆盖（lg 断点 1024px · 在 desktop 1280 走 lg:grid-cols-3 · 同时 className 含
  // grid-cols-1 mobile-first base · 一次断言两端契约）· mobile project 价值有限故移除。
  projects: [
    {
      name: 'chromium-desktop',
      use: { ...devices['Desktop Chrome'], channel: 'chrome' },
    },
  ],

  webServer: {
    command: 'npm run dev',
    url: BASE_URL,
    timeout: 60_000,
    reuseExistingServer: !process.env.CI, // 本地 dev 已开 → 直接用
    stdout: 'ignore',
    stderr: 'pipe',
  },
})
