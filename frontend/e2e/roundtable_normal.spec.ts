/**
 * D5.7 · 档 2 · E2E Spec 1 · 正常流
 *
 * 场景：
 *   用户打开圆桌页 → 选 3 persona → 输入问题 → 点"开始圆桌" →
 *   观察 phase1/2/3 流式输出 → Moderator 卡片出现
 *
 * 对应档 1 的 `roundtable_normal_flow.test.tsx` · 此处是真浏览器验证
 */
import { test, expect } from '@playwright/test'
import {
  buildFullRoundEvents,
  fillQuestionAndStart,
  mockRoundtableSse,
  openRoundtablePage,
  SAMPLE_MODERATOR,
  selectPersonas,
} from './fixtures/sse'

const SESSION_ID = 'rt_e2e_normal'
const PERSONAS = ['neutral', 'supportive', 'eft'] as const

test.describe('圆桌讨论 · 正常流 · 单轮端到端', () => {
  test.beforeEach(async ({ page }) => {
    // 先注册 route · 再 goto
    await mockRoundtableSse(page, SESSION_ID, buildFullRoundEvents([...PERSONAS]))
    await openRoundtablePage(page)
  })

  test('选 persona → 开始 → phase1/2/3 UI 依次渲染 → Moderator 六段到位', async ({ page }) => {
    await selectPersonas(page, ['中立顾问', '支持性顾问', 'EFT 情绪聚焦'])
    await fillQuestionAndStart(
      page,
      '我男友最近冷战了三天，我不知道是我太敏感，还是 ta 确实没把我放在心上，越想越觉得心累，希望听听不同视角',
    )

    // Phase1 agent 卡出现 · 等流式文本到位（每位 phase1 回应包含 persona id 前缀）
    for (const pid of PERSONAS) {
      await expect(page.getByText(`${pid} 的 phase1 回应。`)).toBeVisible({ timeout: 10_000 })
    }

    // Phase2 交叉回应
    for (const pid of PERSONAS) {
      await expect(page.getByText(`${pid} 的 phase2 交叉回应。`)).toBeVisible({ timeout: 10_000 })
    }

    // Moderator 六段可见
    await expect(page.getByText(SAMPLE_MODERATOR.seen)).toBeVisible({ timeout: 10_000 })
    await expect(page.getByText(SAMPLE_MODERATOR.tries[0])).toBeVisible()
    await expect(page.getByText(SAMPLE_MODERATOR.doubts[0])).toBeVisible()
    await expect(page.getByText(SAMPLE_MODERATOR.lens)).toBeVisible()
    await expect(page.getByText(SAMPLE_MODERATOR.limit)).toBeVisible()

    // 返回按钮可见（Session 页顶部）
    await expect(page.getByRole('button', { name: /返回/ })).toBeVisible()
  })

  test('fallback_reason 非 null · amber banner 可见', async ({ page }) => {
    // 重新注册带 fallback_reason 的事件流（覆盖 beforeEach）
    const evs = buildFullRoundEvents([...PERSONAS])
    // 找到 moderator 事件 · 塞 fallback_reason
    const modIdx = evs.findIndex((e) => e.type === 'moderator')
    if (modIdx >= 0 && evs[modIdx].type === 'moderator') {
      ;(evs[modIdx] as { fallback_reason: string }).fallback_reason = 'llm_returned_none'
    }
    await mockRoundtableSse(page, SESSION_ID, evs)
    await openRoundtablePage(page)

    await selectPersonas(page, ['中立顾问', '支持性顾问', 'EFT 情绪聚焦'])
    await fillQuestionAndStart(
      page,
      '测试降级路径的问题描述需要满足三十字以上才能避开 isLightweight 轻量限制让按钮启用',
    )

    // amber banner
    await expect(page.getByText(/Moderator 已降级/)).toBeVisible({ timeout: 15_000 })
  })
})
