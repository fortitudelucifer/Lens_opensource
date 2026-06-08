/**
 * D5.7 · 档 2 · Playwright SSE 伪造工具
 *
 * 用 page.route() 拦截圆桌讨论相关 API + SSE endpoint，
 * 让 e2e spec 不依赖真 backend 运行。
 *
 * 三个可 mock 的端点：
 *   POST /api/roundtable/sessions              → 创建 session
 *   GET  /api/roundtable/sessions/{id}          → 拉取 session detail（hydrate）
 *   GET  /api/roundtable/stream/{id}            → SSE 事件流
 *   POST /api/roundtable/sessions/{id}/continue → continue 追问
 *
 * 约束：必须在 page.goto() 之前注册 route · 否则 EventSource 已建立连接
 */
import type { Page, Route } from '@playwright/test'

// ── SSE 事件类型（与 backend / useRoundtableStream 一致）──
export type SseEvent =
  | { type: 'agent_status'; agent_id: string; phase: 'phase1' | 'phase2'; status: string }
  | { type: 'agent_chunk'; agent_id: string; phase: 'phase1' | 'phase2'; delta: string }
  | { type: 'agent_done'; agent_id: string; phase: 'phase1' | 'phase2'; confidence: number }
  | { type: 'phase_advance'; phase: string }
  | { type: 'moderator_thinking'; text: string }
  | { type: 'moderator'; content: Record<string, unknown>; fallback_reason?: string | null }
  | { type: 'done' }
  | { type: 'error'; message: string }

/** 把 SSE 事件数组序列化为 EventSource 可读的 body 字符串 */
export function encodeSseBody(events: SseEvent[]): string {
  return events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join('') + 'event: close\ndata: bye\n\n'
}

/**
 * 注册路由：SSE 流 · session 创建 · continue
 *
 * @param page         Playwright Page
 * @param sessionId    约定好的 session id（如 `rt_e2e_001`）
 * @param events       要吐回来的 SSE 事件序列
 * @param detail       可选 · 当 e2e 里触发 hydrate（从历史列表进入）时返回的 session detail
 */
export async function mockRoundtableSse(
  page: Page,
  sessionId: string,
  events: SseEvent[],
  detail?: Record<string, unknown>,
): Promise<void> {
  // ⓪ 绕过首访 ConsentModal（「使用须知与知情同意」）· 否则挡住全部 UI
  // 双保险：addInitScript + context 级别 storageState · 保证 localStorage 在 React useEffect
  // 读取之前已经落盘。单用 addInitScript 在某些 Vite dev server 场景下可能没 catch 到初次 navigation
  await page.addInitScript(() => {
    try {
      window.localStorage.setItem('lens_consent_accepted', new Date().toISOString())
      window.localStorage.setItem('lens_assessment_prompted', 'true')
    } catch {
      // ignore
    }
  })
  // 兜底：如果 init script 因 origin 切换没落上 · 提供一个辅助函数让 spec 在 goto 后主动调
  ;(page as Page & { _ensureConsent?: () => Promise<void> })._ensureConsent = async () => {
    await page.evaluate(() => {
      window.localStorage.setItem('lens_consent_accepted', new Date().toISOString())
      window.localStorage.setItem('lens_assessment_prompted', 'true')
    })
  }

  // ① 创建 session · backend POST /api/roundtable/sessions 返回 { session_id, status, created_at }
  await page.route('**/api/roundtable/sessions', async (route: Route) => {
    const req = route.request()
    if (req.method() === 'POST') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          session_id: sessionId,
          status: 'created',
          created_at: new Date().toISOString(),
        }),
      })
      return
    }
    // GET /api/roundtable/sessions（历史列表）· backend 返回 Array<RoundtableSessionSummary> · 默认空
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([]),
    })
  })

  // ② SSE 流 · 返回 text/event-stream + 预编码 body
  await page.route(`**/api/roundtable/stream/${sessionId}*`, async (route: Route) => {
    await route.fulfill({
      status: 200,
      headers: {
        'content-type': 'text/event-stream; charset=utf-8',
        'cache-control': 'no-cache',
        connection: 'keep-alive',
      },
      body: encodeSseBody(events),
    })
  })

  // ③ session detail（hydrate 用）
  if (detail) {
    await page.route(`**/api/roundtable/sessions/${sessionId}`, async (route: Route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ id: sessionId, ...detail }),
      })
    })
  }

  // ④ continue 端点 · 返回成功
  await page.route(`**/api/roundtable/sessions/${sessionId}/continue`, async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ id: sessionId, round_index: 1 }),
    })
  })
}

/** 常用的 Moderator 默认内容（六段结构） */
export const SAMPLE_MODERATOR = {
  seen: '听到你说这件事·我们一起往下走一段。',
  angles: ['中立（0.80）', '支持性（0.82）', 'EFT（0.85）'],
  tries: ['先写下三句话', '用邀请而非质问开头', '允许自己把注意力移回自己'],
  doubts: ['对方若沉默你会怎么办？', '是否还有尚未说出口的细节？'],
  lens: '你不是一个人在面对这件事。',
  limit: 'Lens 圆桌讨论是非诊断性的探索工具。',
}

/**
 * 三段式打开圆桌页 · 用于所有 e2e spec：
 *   ① goto / 建立 origin
 *   ② evaluate 写入 lens_consent_accepted localStorage（绕过 ConsentModal）
 *   ③ goto /roundtable + 等"心理学流派"标题落地（确保 React 已挂载）
 */
export async function openRoundtablePage(page: Page): Promise<void> {
  await page.goto('/')
  await page.evaluate(() => {
    window.localStorage.setItem('lens_consent_accepted', new Date().toISOString())
    window.localStorage.setItem('lens_assessment_prompted', 'true')
  })
  await page.goto('/roundtable')
  await page.waitForSelector('text=心理学流派', { timeout: 10_000 })
}

/**
 * 稳定地选 3 位 persona · 用原生 DOM click 绕过 React 重渲染 detach
 */
export async function selectPersonas(page: Page, names: string[]): Promise<void> {
  for (const name of names) {
    await page.evaluate((nm) => {
      const btns = Array.from(document.querySelectorAll('button[aria-pressed="false"]'))
      const target = btns.find((b) => (b.textContent ?? '').includes(nm)) as HTMLButtonElement | undefined
      target?.click()
    }, name)
    await page.waitForTimeout(120)
  }
  await page.waitForFunction(() => document.querySelectorAll('[aria-pressed="true"]').length >= 3)
}

/**
 * 启动圆桌：填问题（≥30 字避开 isLightweight）+ 点「开启圆桌」
 */
export async function fillQuestionAndStart(page: Page, question: string): Promise<void> {
  await page.locator('textarea').first().fill(question)
  await page.getByRole('button', { name: /开启圆桌/ }).first().waitFor({ state: 'visible' })
  await page.getByRole('button', { name: /开启圆桌/ }).first().click({ force: true })
}

/** 一个完整的单轮事件流 · 覆盖 phase1 → phase2 → moderator → done */
export function buildFullRoundEvents(personas: string[]): SseEvent[] {
  const events: SseEvent[] = []
  for (const pid of personas) {
    events.push({ type: 'agent_status', agent_id: pid, phase: 'phase1', status: 'streaming' })
    events.push({ type: 'agent_chunk', agent_id: pid, phase: 'phase1', delta: `${pid} 的 phase1 回应。` })
    events.push({ type: 'agent_done', agent_id: pid, phase: 'phase1', confidence: 0.85 })
  }
  events.push({ type: 'phase_advance', phase: 'phase2' })
  for (const pid of personas) {
    events.push({ type: 'agent_status', agent_id: pid, phase: 'phase2', status: 'streaming' })
    events.push({ type: 'agent_chunk', agent_id: pid, phase: 'phase2', delta: `${pid} 的 phase2 交叉回应。` })
    events.push({ type: 'agent_done', agent_id: pid, phase: 'phase2', confidence: 0.88 })
  }
  events.push({ type: 'phase_advance', phase: 'phase3' })
  events.push({ type: 'moderator_thinking', text: '我看到三位顾问都指向同一个张力……' })
  events.push({ type: 'moderator', content: SAMPLE_MODERATOR, fallback_reason: null })
  events.push({ type: 'done' })
  return events
}
