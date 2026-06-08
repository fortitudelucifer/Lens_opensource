/**
 * Day 6 · Step 4 · RAG 注入预览 · buildContextFromSelection 纯函数单测
 */

import { describe, expect, it } from 'vitest'
import {
  buildContextFromSelection,
} from '../InjectionDrawer'
import type {
  RoundtableInjectPreview,
  RoundtableChatHistoryHit,
  RoundtableKnowledgeHit,
} from '@/lib/api'

const makeChat = (overrides: Partial<RoundtableChatHistoryHit> = {}): RoundtableChatHistoryHit => ({
  chunk_id: 'c1',
  preview: '默认片段文本',
  days: [102, 103],
  chunk_type: 'conflict',
  analysis_summary: '',
  score: 0.85,
  ...overrides,
})

const makeKn = (overrides: Partial<RoundtableKnowledgeHit> = {}): RoundtableKnowledgeHit => ({
  category: 'psychology',
  question: '共情是什么？',
  answer: '能感受他人情绪。',
  keywords: ['共情'],
  score: 0.0,
  ...overrides,
})

describe('buildContextFromSelection', () => {
  it('全空 · 返回空串', () => {
    const preview: RoundtableInjectPreview = {
      chat_history: [],
      knowledge: [],
      suggested_context: '',
    }
    expect(buildContextFromSelection(preview, new Set(), new Set())).toBe('')
  })

  it('只选中 chat_history · 只出现历史段', () => {
    const preview: RoundtableInjectPreview = {
      chat_history: [makeChat({ preview: '第 102 天争吵' })],
      knowledge: [makeKn()],
      suggested_context: '',
    }
    const ctx = buildContextFromSelection(preview, new Set([0]), new Set())
    expect(ctx).toContain('【相关历史对话片段】')
    expect(ctx).toContain('第102,103天')
    expect(ctx).toContain('冲突')
    expect(ctx).toContain('第 102 天争吵')
    expect(ctx).not.toContain('【专业知识手册】')
  })

  it('只选中 knowledge · 只出现知识段', () => {
    const preview: RoundtableInjectPreview = {
      chat_history: [makeChat()],
      knowledge: [makeKn({ question: 'Q1', answer: 'A1' })],
      suggested_context: '',
    }
    const ctx = buildContextFromSelection(preview, new Set(), new Set([0]))
    expect(ctx).not.toContain('【相关历史对话片段】')
    expect(ctx).toContain('【专业知识手册】')
    expect(ctx).toContain('Q: Q1')
    expect(ctx).toContain('A: A1')
  })

  it('两部分都选 · 两段均出现', () => {
    const preview: RoundtableInjectPreview = {
      chat_history: [makeChat()],
      knowledge: [makeKn()],
      suggested_context: '',
    }
    const ctx = buildContextFromSelection(preview, new Set([0]), new Set([0]))
    expect(ctx).toContain('【相关历史对话片段】')
    expect(ctx).toContain('【专业知识手册】')
  })

  it('未选中的不会出现 · index 过滤正确', () => {
    const preview: RoundtableInjectPreview = {
      chat_history: [
        makeChat({ preview: '片段-A' }),
        makeChat({ preview: '片段-B' }),
        makeChat({ preview: '片段-C' }),
      ],
      knowledge: [],
      suggested_context: '',
    }
    const ctx = buildContextFromSelection(preview, new Set([0, 2]), new Set())
    expect(ctx).toContain('片段-A')
    expect(ctx).not.toContain('片段-B')
    expect(ctx).toContain('片段-C')
    // 片段序号按 selected 顺序 1,2
    expect(ctx.match(/片段 1/)?.length).toBe(1)
    expect(ctx.match(/片段 2/)?.length).toBe(1)
    expect(ctx).not.toContain('片段 3')
  })

  it('analysis_summary 存在时会注入到片段 header', () => {
    const preview: RoundtableInjectPreview = {
      chat_history: [makeChat({ analysis_summary: '冲突根源：沟通不足' })],
      knowledge: [],
      suggested_context: '',
    }
    const ctx = buildContextFromSelection(preview, new Set([0]), new Set())
    expect(ctx).toContain('分析：冲突根源：沟通不足')
  })

  it('days 为空时显示"时间未知"', () => {
    const preview: RoundtableInjectPreview = {
      chat_history: [makeChat({ days: [], preview: 'no-days' })],
      knowledge: [],
      suggested_context: '',
    }
    const ctx = buildContextFromSelection(preview, new Set([0]), new Set())
    expect(ctx).toContain('时间未知')
  })

  it('unknown chunk_type 保留原值', () => {
    const preview: RoundtableInjectPreview = {
      chat_history: [makeChat({ chunk_type: 'mystery' })],
      knowledge: [],
      suggested_context: '',
    }
    const ctx = buildContextFromSelection(preview, new Set([0]), new Set())
    expect(ctx).toContain('mystery')
  })

  it('knowledge item 问答均为空时不会生成空 Q:A: 行', () => {
    const preview: RoundtableInjectPreview = {
      chat_history: [],
      knowledge: [makeKn({ question: '', answer: '' })],
      suggested_context: '',
    }
    const ctx = buildContextFromSelection(preview, new Set(), new Set([0]))
    // 只出现 section header，没有空 Q/A
    expect(ctx.trim()).toBe('【专业知识手册】')
  })
})
