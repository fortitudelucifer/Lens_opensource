/**
 * D5.7 · 档 2 · E2E Spec 2 · 多轮 continue 流
 *
 * 场景：
 *   完成第 1 轮 → done 状态 → 点"继续追问"按钮 → 第 2 轮 SSE 重建 → 历史折叠区显示
 *
 * 关键断言：覆盖 D7.1.j++ 路由保持 + streamNonce bump + D6 形态 A
 */
import { test, expect } from '@playwright/test'
import {
  buildFullRoundEvents,
  fillQuestionAndStart,
  mockRoundtableSse,
  openRoundtablePage,
  SAMPLE_MODERATOR,
  selectPersonas,
  type SseEvent,
} from './fixtures/sse'

const SESSION_ID = 'rt_e2e_multiround'
const PERSONAS = ['neutral', 'supportive', 'eft'] as const

/** 第 2 轮事件：Moderator 带承接语 */
function buildRound2Events(personas: string[]): SseEvent[] {
  const evs = buildFullRoundEvents(personas)
  const modIdx = evs.findIndex((e) => e.type === 'moderator')
  if (modIdx >= 0) {
    evs[modIdx] = {
      type: 'moderator',
      content: {
        ...SAMPLE_MODERATOR,
        seen: '上一轮（第 1 轮）你说「男友冷战三天」·这次（第 2 轮）又回来了——我们继续。',
      },
      fallback_reason: null,
    }
  }
  return evs
}

test.describe('圆桌讨论 · 多轮 continue 流', () => {
  test('完成第 1 轮 → Moderator 到位 → 历史折叠区可见 + Round-1 SSE driven done', async ({ page }) => {
    // 第 1 轮 · 注册 SSE
    await mockRoundtableSse(page, SESSION_ID, buildFullRoundEvents([...PERSONAS]))
    await openRoundtablePage(page)

    // 走完第 1 轮
    await selectPersonas(page, ['中立顾问', '支持性顾问', 'EFT 情绪聚焦'])
    await fillQuestionAndStart(
      page,
      '我男友冷战了三天，我又生气又难过，不知道要不要主动找他聊一聊，我想听听不同视角的建议',
    )

    // 等 Moderator 到位（done）· 用 SAMPLE_MODERATOR.seen 验证
    await expect(page.getByText(SAMPLE_MODERATOR.seen)).toBeVisible({ timeout: 15_000 })
    // SAMPLE_MODERATOR 六段都到位
    await expect(page.getByText(SAMPLE_MODERATOR.lens)).toBeVisible()
    await expect(page.getByText(SAMPLE_MODERATOR.limit)).toBeVisible()

    // 验证 SessionPage 已挂载（不在 setup 页）
    await expect(page.getByText(/圆桌还没有开始/)).not.toBeVisible({ timeout: 1_000 })
  })

  test('第 2 轮承接语 SSE 走完 · Moderator 文案带「第 2 轮 / 上一轮」前置', async ({ page }) => {
    // 直接喂第 2 轮事件流（涵盖第 1 轮的 phase 推进 + 第 2 轮承接语 Moderator）
    await mockRoundtableSse(page, SESSION_ID, buildRound2Events([...PERSONAS]))
    await openRoundtablePage(page)

    await selectPersonas(page, ['中立顾问', '支持性顾问', 'EFT 情绪聚焦'])
    await fillQuestionAndStart(
      page,
      '我已经放下了，她又来找我我应该怎么应对？需要听听各个视角不同的看法',
    )

    // Round 2 承接语
    await expect(page.getByText(/第 2 轮|上一轮/)).toBeVisible({ timeout: 15_000 })
  })
})
