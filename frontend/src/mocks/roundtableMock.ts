/**
 * 圆桌讨论前端 mock 数据
 *
 * ⚠️ 本数据仅用于前端占位与 Storybook-style 独立渲染 — 真实 LLM 输出
 * 不必对标此质量。Day 5 切换真实 API 后，本文件仅作为开发环境 fallback。
 *
 * 使用 case：用户问「和男友冷战三天，不知道该不该先服软」
 */

import type { PersonaId } from '@/data/personas'
import type { AgentMessageData, ModeratorContent } from '@/stores/useRoundtableStore'

export const MOCK_QUESTION = '和男友冷战三天，不知道该不该先服软'

/** Phase 1 · 8 persona 独立分析（来自 MP 原版，id 已映射到 Lens） */
export const PHASE1_TEXTS: Record<PersonaId, string> = {
  neutral:
    '让我先帮你拆解现在的情况：冷战已经持续三天，双方都在等对方先开口。先把"对方不在乎我"和"对方不知道怎么表达"这两个假设分开——它们会带来完全不同的下一步。关键不是谁先服软，而是这次冲突的根本诉求是否被双方听见了。',
  supportive:
    '听起来你此刻又委屈又疲惫。冷战三天，其实你一直在独自承担关系里的不确定感。我想先停在这里陪你一会——你愿意告诉我，这三天里最难熙的是哪一个瞬间？',
  psychoanalytic:
    '你对"是不是我太敏感"的自我怀疑，值得被认真对待。它可能不是此刻才出现的——回想童年里，当你表达需要时，身边的人通常怎么回应你？有时我们在伴侣身上重演的，是更早那段关系里没被接住的部分。',
  eft: '"敏感"之下，可能藏着一个更底层的需求：我想确认——在你眼里，我是重要的吗？愤怒和冷漠常常是依恋受伤时的保护层。如果把它们轻轻掰开，你想让 ta 看见的是什么？',
  bowen:
    '从系统的视角看，冷战往往不是两个人的事，而是整个情绪系统在降温。你家庭里处理冲突的方式是什么？这段关系里，谁更容易先退开一步——这个模式，是不是早已存在？',
  sociology:
    '"我是不是太敏感"这个疑问本身，带着社会脚本的痕迹——女性常被规训要"懂事"，男性常被规训要"冷静"。你们之间的冷战，有多少是个人选择，有多少是这套脚本在替你们选？',
  philosophy:
    '在问"ta 是否在乎我"之前，也许可以先问：我希望被如何在乎？存在主义会提醒我们——没有一段关系能给出终极答案，但我们可以选择用什么方式承担这份不确定。',
  game_theory:
    '冷战是一次"先退让就输"的博弈——但如果关系是长期重复博弈，短期赢了反而会输掉信任资本。先开口的人并不是弱者，而是愿意付出"可信承诺"的那一方。',
  cultural:
    '在许多东亚家庭里，"不说"被当作一种美德："成熟的人不计较"。但这套叙事并不适用于所有关系。先看看你们之间的文化默契，再决定是否要打破它。',
}

/** Phase 2 · 8 persona 交叉回应（来自 MP 原版，id 已映射到 Lens） */
export const PHASE2_TEXTS: Record<PersonaId, string> = {
  neutral:
    '阅读了几位同事的视角后，我更倾向于这个整合：问题不是"你敏感或不敏感"，而是"你们之间缺少一个安全谈论感受的渠道"。这是可以被具体设计的。',
  supportive:
    '我听见了其他顾问在梓理结构，但我想再为你留一点空间——先允许自己难过，再谈怎么办。你不必立刻变得理性。',
  psychoanalytic:
    '与 EFT 的视角可以互补：依恋需求浮上来的那一刻，也常常是童年剧本重新上演的时刻。值得做的不是压下它，而是认出它。',
  eft: '精神分析和 Bowen 谈到的早期/系统性因素，其实都会在"当下这一次冷战"中具象化——情绪是最诚实的信号。',
  bowen:
    '社会学同事说得对，脚本确实在场。但系统视角会补充：这套脚本通常由家庭代际传递下来。你有机会成为"打断它"的那一代。',
  sociology:
    '博弈论把冷战描述为策略，我想加一层：策略的选择不是中立的，它被性别与阶层的剧本塑造着。看清结构，选择才真正自由。',
  philosophy:
    '所有顾问都在做一件事：帮你把"模糊的难受"翻译成"可以选择的问题"。这本身就是一种存在主义式的赋权。',
  game_theory:
    '同意 EFT——可信承诺的前提是情绪被看见。否则任何"策略"都只是新一层的防御。',
  cultural:
    '听到哲学同事说"自由选择"，我想温柔地提醒：选择从来不是在真空里发生的。先看见你身处的文化水，再决定要不要游向别处。',
}

/** Phase 1 mock confidence 值（全部 8 persona）*/
export const PHASE1_CONFIDENCE: Record<PersonaId, number> = {
  neutral: 0.78,
  supportive: 0.82,
  psychoanalytic: 0.75,
  eft: 0.80,
  bowen: 0.72,
  sociology: 0.76,
  philosophy: 0.70,
  game_theory: 0.74,
  cultural: 0.73,
}

/** Phase 2 mock confidence 值（全部 8 persona）*/
export const PHASE2_CONFIDENCE: Record<PersonaId, number> = {
  neutral: 0.82,
  supportive: 0.85,
  psychoanalytic: 0.79,
  eft: 0.83,
  bowen: 0.77,
  sociology: 0.80,
  philosophy: 0.75,
  game_theory: 0.78,
  cultural: 0.76,
}

/** Moderator 6 段输出（根据 MP 原版 + 执行方案 K2 结构文案）*/
export const MOCK_MODERATOR: ModeratorContent = {
  seen:
    '你的"敏感"不是缺陷——它是一个在告诉你"这段关系里有未被看见的东西"的信号。冷战本身是一种需要被理解的沟通方式，而不是需要被审判的对错。无论从哪个视角切入，结论都指向同一件事：先被听见，再谈如何改变。',
  angles: [
    '情感支持视角希望你先停下来感受；博弈论和社会学视角则鼓励你尽早打破僵局。两种节奏都成立，取决于你此刻更需要什么。',
    '精神分析把根源放在早期经验，而系统家庭视角更看重当下的关系结构——你可以两者都听一听，但不必被任何一种解释绑定。',
  ],
  tries: [
    '今晚不急着解决问题。先写下三句话：我此刻的感受是什么 / 我希望 ta 听见的是什么 / 我能承担的是什么。',
    '如果要打破冷战，用"邀请"而不是"质问"开头。例如："我想聊聊这几天，但我不想又吵起来，你愿意吗？"',
    '如果对方不回应，也允许自己把注意力暂时移回自己——这不是放弃关系，而是先把自己照顾好。',
  ],
  doubts: [
    '如果他听到你的诉求后仍然沉默，接下来你会怎么办？这个问题现在无法回答，需要真正开口后才知道',
    '"服软"这个词本身是否带着你原生家庭的某种剧本？这值得在更长的时间里觉察',
  ],
  lens:
    '你不是一个人在面对这场冷战。我们不会替你决定该不该继续这段关系，但我们会一直在你愿意回来思考的时候在这里。',
  limit:
    'Lens 聘诉是非诊断性的探索工具，以上内容不能替代专业心理咨询或医疗评估。如果你正在经历严重情绪困扰，请拨打 24 小时心理援助热线 400-161-9995。',
}

/** 构造一个完整的 mock agent message（用于 Storybook-like 独立渲染） */
export function mockAgentMessage(
  personaId: PersonaId,
  phase: 'phase1' | 'phase2',
  overrides: Partial<AgentMessageData> = {},
): AgentMessageData {
  const text = phase === 'phase1' ? PHASE1_TEXTS[personaId] : PHASE2_TEXTS[personaId]
  const confidence =
    phase === 'phase1' ? PHASE1_CONFIDENCE[personaId] : PHASE2_CONFIDENCE[personaId]
  return {
    personaId,
    status: text ? 'done' : 'pending',
    text: text ?? '',
    confidence: confidence || undefined,
    ...overrides,
  }
}

/** 默认 demo 场景：3 位顾问 × 2 阶段 + Moderator */
export const DEMO_PERSONAS: PersonaId[] = ['neutral', 'supportive', 'psychoanalytic']

export const DEMO_PHASE1_AGENTS: AgentMessageData[] = DEMO_PERSONAS.map((id) =>
  mockAgentMessage(id, 'phase1'),
)

export const DEMO_PHASE2_AGENTS: AgentMessageData[] = DEMO_PERSONAS.map((id) =>
  mockAgentMessage(id, 'phase2'),
)
