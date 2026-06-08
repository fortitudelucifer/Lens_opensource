/**
 * D5.7 · 档 2 · E2E Spec 3 · Mobile 视口
 *
 * 场景：
 *   iPhone 13 视口（390×844）下圆桌讨论的基本可用性
 *   由 playwright.config.ts 的 `chromium-mobile` project + @mobile grep 拣选
 *
 * 场景：
 *   ① 侧栏导航可访问（移动端抽屉或直接按钮）
 *   ② 选 persona / 输入问题 / 开始圆桌流程可完成
 *   ③ agent grid 在窄屏默认单列（CSS 断点验证）
 */
import { test, expect } from '@playwright/test'
import {
  buildFullRoundEvents,
  fillQuestionAndStart,
  mockRoundtableSse,
  openRoundtablePage,
  selectPersonas,
} from './fixtures/sse'

const SESSION_ID = 'rt_e2e_mobile'
const PERSONAS = ['neutral', 'supportive', 'eft'] as const

test.describe('圆桌讨论 · Mobile @mobile', () => {
  test.beforeEach(async ({ page }) => {
    await mockRoundtableSse(page, SESSION_ID, buildFullRoundEvents([...PERSONAS]))
    await openRoundtablePage(page)
  })

  test('@mobile mobile 窄屏 · 基础流程可完成 · 进入 SessionPage', async ({ page }) => {
    await selectPersonas(page, ['中立顾问', '支持性顾问', 'EFT 情绪聚焦'])
    await fillQuestionAndStart(
      page,
      '移动端窄屏下的端到端可用性测试，问题描述需要满足三十字以上以避开质量门拦截',
    )

    // Session 页出现返回按钮（顶部导航）
    await expect(page.getByRole('button', { name: /返回/ })).toBeVisible({ timeout: 10_000 })
  })

  test('@mobile agent grid 类包含 grid-cols-1 + lg:grid-cols-3（mobile-first 响应式）', async ({
    page,
  }) => {
    await selectPersonas(page, ['中立顾问', '支持性顾问', 'EFT 情绪聚焦'])
    await fillQuestionAndStart(
      page,
      '响应式测试 · 验证 phase1 grid 在窄屏下是单列布局，宽屏才切到三列横向布局',
    )

    // 等 phase1 grid 渲染
    await page.waitForTimeout(1_500)

    // 抓所有 grid 容器 · 至少一个带 mobile-first 契约类
    const gridClasses = await page.evaluate(() =>
      Array.from(document.querySelectorAll('.grid')).map((el) => el.className),
    )
    const hasMobileFirst = gridClasses.some(
      (c) => c.includes('grid-cols-1') && c.includes('lg:grid-cols-3'),
    )
    expect(hasMobileFirst).toBe(true)
  })
})
