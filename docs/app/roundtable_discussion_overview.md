# 圆桌讨论系统设计

> 📌 **文档范围**：本文档描述 Lens 圆桌讨论子系统，包括人格选择、三阶段多智能体编排、SSE 多路复用、多轮延续、RAG 上下文注入、安全治理、持久化以及前后端契约。
>
> 更新时间：2026-06-13

---

## 目录

- [1. 设计目标](#1-设计目标)
- [2. 用户体验模型](#2-用户体验模型)
- [3. 系统架构](#3-系统架构)
- [4. 人格模型](#4-人格模型)
- [5. 三阶段讨论流程](#5-三阶段讨论流程)
- [6. 后端 API 契约](#6-后端-api-契约)
- [7. SSE 事件协议](#7-sse-事件协议)
- [8. 前端状态机](#8-前端状态机)
- [9. 多轮延续](#9-多轮延续)
- [10. 跨轮记忆压缩与传递](#10-跨轮记忆压缩与传递)
- [11. RAG 上下文注入](#11-rag-上下文注入)
- [12. 提示词与模型配置](#12-提示词与模型配置)
- [13. 安全与偏见治理](#13-安全与偏见治理)
- [14. 持久化与恢复](#14-持久化与恢复)
- [15. 用户体验组件](#15-用户体验组件)
- [16. 已知限制与演进方向](#16-已知限制与演进方向)
- [17. 文件索引](#17-文件索引)

---

## 1. 设计目标

### 1.1 产品定位

圆桌讨论是 Lens 的多智能体反思界面。不同于返回单一顾问回复，它要求用户恰好选择三个人格，让他们从不同的理论立场讨论同一个关系问题。

该模块专为受益于视角多样性的问题而设计：

- 模糊的恋爱决策，
- 存在多种解读的情感冲突，
- 反复出现的沟通模式，
- 涉及个人心理与社会情境的问题，
- 单一顾问风格可能显得过于狭隘的情境。

### 1.2 核心目标

| 目标 | 方法 | 输出 |
|------|------|------|
| 多视角反思 | 三个选定的人格回答同一问题 | 第一阶段独立观点 |
| 跨视角综合 | 每个人格在看到同伴摘要后回应 | 第二阶段交叉回应 |
| 降低认知负荷 | 主持人将观点整合为六个结构化部分 | 第三阶段主持人总结 |
| 保留用户主体性 | 系统提供观点而非决策 | 开放式建议与不确定性陈述 |
| 支持连续性 | 已完成的会话可以通过后续问题继续 | 已归档轮次 + 当前轮次状态 |
| 实现情境锚定 | 可选的聊天记录与知识注入 | 用户选定的提示词上下文块 |

### 1.3 设计原则

```text
┌──────────────────────────────────────────────────────────────────────┐
│                        圆桌讨论设计原则                                │
├──────────────────────────────────────────────────────────────────────┤
│ 1. 每会话恰好三个人格                                                │
│ 2. 第二阶段交叉回应之前，第一阶段保持独立                              │
│ 3. 一个 SSE 端点，通过 agent_id 和 phase 多路复用                      │
│ 4. 用户可见的流式传输，而非隐藏的批量生成                              │
│ 5. 主持人综合必须承认不确定性与限制                                    │
│ 6. 安全与偏见检查在生成之前和期间运行                                  │
│ 7. 多轮延续在新轮次之前归档旧轮次                                    │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 2. 用户体验模型

### 2.1 主流程

```text
圆桌设置页面
  ├─ 选择恰好 3 个人格
  ├─ 输入关系问题
  ├─ 可选选择 LLM 后端
  ├─ 可选预览并注入上下文
  ├─ 可选启用深度模式
  └─ 创建后端会话
        ↓
圆桌会话页面
  ├─ 订阅 SSE 流
  ├─ 渲染第一阶段智能体输出
  ├─ 渲染第二阶段交叉回应
  ├─ 渲染主持人思考与最终综合
  └─ 完成后允许后续提问
```

### 2.2 设置用户体验

设置页面位于 [`frontend/src/pages/RoundtablePage.tsx`](../../frontend/src/pages/RoundtablePage.tsx)。它处理：

| 用户体验元素 | 用途 |
|------------|------|
| 人格卡片 | 从心理学与跨学科组中选择三个视角 |
| 快速预设 | 从推荐的人格组合开始 |
| 问题质量阈值 | 阻止非常短的提示词不必要地使用圆桌讨论 |
| 后端下拉框 | 让用户选择支持聊天的模型后端 |
| 上下文注入抽屉 | 在添加上下文之前预览聊天记录和知识库命中 |
| 深度模式开关 | 增加令牌预算并切换到更深的提示词模板 |
| 会话历史列表 | 重新打开之前的会话和快照 |

### 2.3 会话用户体验

会话页面位于 [`frontend/src/pages/RoundtableSessionPage.tsx`](../../frontend/src/pages/RoundtableSessionPage.tsx)。它渲染：

- 阶段横幅与阶段转换。
- 三个平行的智能体列。
- 按人格的流式文本块。
- 智能体置信度标记。
- 主持人思考流。
- 最终主持人卡片。
- 已归档轮次卡片。
- 后续提问编辑器。
- 当会话无法安全恢复时的只读快照横幅。

---

## 3. 系统架构

### 3.1 高层架构

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                              React 前端                                     │
│                                                                             │
│  RoundtablePage              RoundtableSessionPage                          │
│  ├─ 人格选择                ├─ useRoundtableStream                         │
│  ├─ 后端选择器              ├─ AgentMessage 组件                           │
│  ├─ 注入预览                ├─ ModeratorCard / ModeratorThinking            │
│  └─ 创建会话                └─ FollowUpComposer / 历史卡片                  │
│              │                                  ▲                           │
│              ▼                                  │                           │
│        frontend/src/lib/api.ts          Zustand 圆桌讨论 Store              │
└─────────────────────────────────────────────────────────────────────────────┘
              │                                  ▲
              │ REST                             │ SSE 事件
              ▼                                  │
┌─────────────────────────────────────────────────────────────────────────────┐
│                         FastAPI 圆桌讨论路由                                │
│                                                                             │
│  scripts/advisor/api/routes/roundtable.py                                    │
│  ├─ 创建会话                                                                 │
│  ├─ 流式会话                                                                 │
│  ├─ 继续会话                                                                 │
│  ├─ 注入预览                                                                 │
│  ├─ 列表/获取会话                                                            │
│  └─ 中断会话                                                                 │
└─────────────────────────────────────────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                       圆桌讨论服务编排器                                     │
│                                                                             │
│  scripts/advisor/api/services/roundtable_service.py                          │
│  ├─ 内存中的会话、队列、任务                                                 │
│  ├─ 持久化的会话快照                                                         │
│  ├─ 第一阶段 / 第二阶段 / 主持人编排                                         │
│  ├─ generator_service 后端调用                                               │
│  ├─ RAG 预览与注入上下文                                                     │
│  ├─ 危机与偏见清理                                                           │
│  └─ 审计事件                                                                 │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 运行时对象

| 对象 | 后端所有者 | 用途 |
|------|-----------|------|
| `_sessions` | `roundtable_service.py` | 按键为会话 id 的内存会话状态 |
| `_queues` | `roundtable_service.py` | 每会话异步事件队列，用于 SSE |
| `_tasks` | `roundtable_service.py` | 运行中的流程任务 |
| `_subscribed` | `roundtable_service.py` | 触发门控，使生成在 SSE 订阅后开始 |
| `RoundtableSession` | `core/models.py` | 可持久化的会话数据模型 |
| `RoundtableRoundSnapshot` | `core/models.py` | 已归档的完成轮次 |
| Zustand store | `useRoundtableStore.ts` | 跨设置、流、历史和延续的前端状态 |

---

## 4. 人格模型

### 4.1 人格真实来源

圆桌讨论使用 [`frontend/src/data/personas.ts`](../../frontend/src/data/personas.ts) 作为显示元数据的前端真实来源，使用 [`configs/roundtable_prompts.yaml`](../../configs/roundtable_prompts.yaml) 作为后端提示词来源。

人格 id 与后端字面类型 `RoundtablePersonaId` 匹配，定义于 [`scripts/advisor/api/core/models.py`](../../scripts/advisor/api/core/models.py)。

### 4.2 人格清单

| 人格 ID | 显示名称 | 类别 | 核心视角 |
|------------|--------------|----------|-----------|
| `neutral` | 中立顾问 | 心理学 | 事实、解读、需求、可能的行动 |
| `supportive` | 支持性顾问 | 心理学 | 情感确认与用户侧支持 |
| `psychoanalytic` | 精神分析顾问 | 心理学 | 无意识脚本、防御机制、早期依恋 |
| `eft` | EFT 情绪聚焦 | 心理学 | 依恋需求与追-避循环 |
| `bowen` | 家庭系统顾问 | 心理学 | 家庭系统、分化、三角化 |
| `sociology` | 社会学视角 | 跨学科 | 性别脚本、阶层、权力、社会结构 |
| `philosophy` | 哲学视角 | 跨学科 | 存在问题与反思性探究 |
| `game_theory` | 博弈论视角 | 跨学科 | 重复博弈、激励、可信信号 |
| `cultural` | 文化视角 | 跨学科 | 文化脚本、代际责任、仪式 |

### 4.3 选择约束

会话要求恰好三个不同的人格 id。后端在 `create_roundtable_session()` 中强制执行此约束，拒绝重复选择。

---

## 5. 三阶段讨论流程

### 5.1 阶段概览

| 阶段 | 后端阶段 | 描述 | 前端渲染 |
|------|----------|------|----------|
| 设置 | `setup` | 会话存在但生成尚未开始 | 设置页面或流前会话页面 |
| 第一阶段 | `phase1` | 三个人格独立回答问题 | 三个流式智能体列 |
| 第二阶段 | `phase2` | 每个人格在看到同伴的第一阶段观点后回应 | 三个交叉回应列 |
| 第三阶段 | `phase3` | 主持人思考并综合 | 主持人思考 + 最终卡片 |
| 完成 | `done` | 会话完成 | 启用后续提问编辑器 |

### 5.2 第一阶段：独立分析

第一阶段使用 [`configs/roundtable_prompts.yaml`](../../configs/roundtable_prompts.yaml) 中的 `phase1_template` 或 `deep_phase1_template`。每个选定的人格接收：

- 用户问题，
- 人格核心描述，
- 可选的前一轮上下文，
- 可选的注入上下文。

该人格此时还看不到其他两个智能体。这可以防止过早收敛，并保持三种视角的鲜明差异。

### 5.3 第二阶段：交叉回应

第二阶段使用 `phase2_template` 或其深度模式等效模板。每个智能体接收：

- 原始用户问题，
- 其人格核心描述，
- 其他两个第一阶段回应的摘要，
- 可选的前一轮和注入上下文。

该人格在承认其他观点的同时保持自己的视角。

### 5.4 第三阶段：主持人综合

主持人生成一个结构化的 `RoundtableModeratorContent` 对象，包含六个部分：

| 字段 | 含义 |
|------|------|
| `seen` | 系统对用户情境的理解 |
| `angles` | 三个视角之间的关键差异 |
| `tries` | 用户可以尝试的行动或反思 |
| `doubts` | 剩余的不确定性与不过度断言的警告 |
| `lens` | Lens 风格的结束信息 |
| `limit` | 局限性声明与非医疗边界 |

如果 LLM 主持人生成失败或被禁用，后端可以回退到基于规则的模板，并将 `moderator_fallback_reason` 暴露给前端。

---

## 6. 后端 API 契约

### 6.1 端点摘要

所有端点由 [`scripts/advisor/api/routes/roundtable.py`](../../scripts/advisor/api/routes/roundtable.py) 注册。

| 方法 | 路径 | 用途 |
|------|------|------|
| `POST` | `/api/roundtable/sessions` | 创建会话，不立即开始生成 |
| `GET` | `/api/roundtable/stream/{session_id}` | 订阅 SSE 并在首次订阅时触发流程 |
| `POST` | `/api/roundtable/sessions/{session_id}/interrupt` | 取消运行中的流程任务 |
| `GET` | `/api/roundtable/sessions` | 列出的会话摘要 |
| `GET` | `/api/roundtable/sessions/{session_id}` | 加载完整会话快照 |
| `POST` | `/api/roundtable/sessions/{session_id}/continue` | 在已完成的会话后开始新一轮 |
| `POST` | `/api/roundtable/inject/preview` | 预览聊天记录和知识命中，用于上下文注入 |

### 6.2 创建会话

请求模型：`RoundtableStartRequest`

| 字段 | 类型 | 约束 | 含义 |
|------|------|------|------|
| `personas` | list | 恰好 3 个 | 选定的人格 id |
| `question` | string | 4-2000 字符 | 用户问题 |
| `parent_id` | string 或 null | 可选 | 未来 DAG 分支父节点 |
| `backend` | string 或 null | 可选 | 用户选择的 LLM 后端 |
| `inject_context` | string 或 null | 最多 12000 字符 | 用户选定的上下文块 |
| `deep_mode` | boolean | 默认 false | 使用更深的提示词和令牌预算 |

响应模型：`RoundtableStartResponse`

```json
{
  "session_id": "rt_xxxxxxxxxxxx",
  "status": "created",
  "created_at": "2026-06-13T00:00:00"
}
```

### 6.3 继续会话

延续要求当前会话阶段为 `done`。后端将完成的轮次归档到 `rounds[]`，重置当前缓冲区，更新 `question`，并等待新的 SSE 订阅触发。

请求模型：`RoundtableContinueRequest`

| 字段 | 类型 | 含义 |
|------|------|------|
| `question` | string | 新的后续问题 |
| `inject_context` | string 或 null | 新一轮的可选上下文 |
| `deep_mode` | boolean 或 null | 覆盖或继承深度模式设置 |

### 6.4 注入预览

注入预览端点返回候选上下文来源：

- 富化聊天记录检索，
- 知识库 FAQ 搜索。

前端让用户检查并选择要注入的内容，而非静默添加隐藏上下文。

---

## 7. SSE 事件协议

### 7.1 传输

流端点返回 `text/event-stream`。每个后端事件序列化为：

```text
data: {"type":"agent_chunk","agent_id":"neutral","phase":"phase1","delta":"..."}

```

流以以下内容结束：

```text
data: [DONE]

```

### 7.2 事件类型

前端事件类型定义于 [`frontend/src/hooks/useRoundtableStream.ts`](../../frontend/src/hooks/useRoundtableStream.ts)。

| 事件 | 载荷 | 前端效果 |
|------|------|----------|
| `agent_status` | `agent_id`, `phase`, `status` | 设置一个人格的状态 |
| `agent_chunk` | `agent_id`, `phase`, `delta` | 追加流式文本 |
| `agent_strip_tail` | `agent_id`, `phase`, `strip_chars` | 从文本中移除置信度标记尾部 |
| `agent_done` | `agent_id`, `phase`, `confidence` | 标记人格完成并存储置信度 |
| `agent_error` | `agent_id`, `phase`, `error` | 标记人格错误 |
| `phase_advance` | `phase` | 将用户界面移至下一阶段 |
| `moderator_thinking` | `text` | 流式主持人推理文本 |
| `moderator` | `content`, `fallback_reason` | 渲染最终主持人卡片 |
| `crisis` | level and resources | 显示安全横幅 / 危机状态 |
| `done` | none | 关闭流并启用后续提问 |
| `error` | message | 设置错误状态 |

### 7.3 为何使用单一 SSE 端点

圆桌讨论使用一个 SSE 端点，并通过 `agent_id` 和 `phase` 进行多路复用，因为：

- 浏览器连接管理更简单，
- 后端可以保留全局阶段顺序，
- 前端可以通过一个钩子分发所有事件，
- 故障更容易作为单一的流状态呈现。

---

## 8. 前端状态机

### 8.1 Store 位置

状态位于 [`frontend/src/stores/useRoundtableStore.ts`](../../frontend/src/stores/useRoundtableStore.ts)。

### 8.2 核心状态字段

| 字段 | 含义 |
|------|------|
| `selectedPersonas` | 三个选定的人格 id |
| `question` | 当前轮次问题 |
| `deepMode` | 是否启用深度提示词/令牌预算 |
| `sessionId` | 后端或本地回退会话 id |
| `currentPhase` | `setup`, `phase1`, `phase2`, `phase3`, `done`, 或 `error` |
| `phase1Agents` | 第一阶段的智能体缓冲区 |
| `phase2Agents` | 第二阶段的智能体缓冲区 |
| `moderator` | 最终结构化的主持人内容 |
| `moderatorThinking` | 流式主持人思考文本 |
| `moderatorFallbackReason` | 主持人是否回退到规则模板 |
| `rounds` | 已归档的完成轮次 |
| `roundIndex` | 当前从零开始的轮次索引 |
| `streamNonce` | 在延续后强制重建 EventSource |
| `isReadOnlySnapshot` | 防止重新连接到过期的未完成会话 |
| `crisis` | 功能本地危机事件 |
| `error` | 功能本地错误信息 |

### 8.3 状态转换

```text
setup
  ├─ 创建会话
  └─ startSession(session_id)
        ↓
phase1
  ├─ agent_status / agent_chunk / agent_done
  └─ phase_advance phase2
        ↓
phase2
  ├─ agent_status / agent_chunk / agent_done
  └─ phase_advance phase3
        ↓
phase3
  ├─ moderator_thinking
  └─ moderator
        ↓
done
  ├─ 后续提问继续
  └─ archiveCurrentRoundAndReset()
        ↓
setup with existing sessionId
  └─ streamNonce 递增且会话页面重新连接
```

### 8.4 只读快照模式

当加载历史会话且其后端阶段既不是 `done` 也不是 `setup` 时，前端将其标记为 `isReadOnlySnapshot`。这防止为可能已不存在于当前后端进程中的流程打开 EventSource。

---

## 9. 多轮延续

### 9.1 延续策略

圆桌讨论使用延续形式 A：

- 保持相同的会话 id，
- 将完成的轮次归档到 `rounds[]`，
- 重置当前缓冲区，
- 递增 `round_index`，
- 将新问题作为当前轮次，
- 通过 `streamNonce` 强制新的 EventSource 连接。

### 9.2 已归档轮次形态

每个 `RoundtableRoundSnapshot` 存储：

- `round_index`，
- `question`，
- 第一阶段智能体缓冲区，
- 第二阶段智能体缓冲区，
- 主持人内容，
- 主持人思考，
- 创建和完成时间戳。

这使得旧轮次即使在当前轮次更改后仍可渲染。

### 9.3 为何在重置前归档

后端在重置之前深拷贝当前缓冲区。这避免了已归档轮次与新当前轮次之间的引用共享。

---

---

## 10. 跨轮记忆压缩与传递

### 10.1 设计动机

多轮延续（Multi-Round Continuation）归档了每轮的完整 `RoundtableRoundSnapshot`，但如果直接把全部历史轮裸文本注入下一轮 prompt，会面临两个问题：

- **早期内容丢失**：3 轮以上时，`_build_prior_context_block` 如果只取最近一轮，早期讨论要点会被完全遗忘。
- **Token 预算吃光**：单轮过长时，未经压缩的历史文本会挤占 persona_core + 用户问题 + LLM 输出的剩余空间。

因此系统引入 **CrossRoundMemory** 模块，按优先级分档压缩已归档的 `session.rounds`，在可控字符预算内为每个 persona 和 Moderator 构造差异化的历史回顾 prompt。

### 10.2 三档压缩策略

`scripts/advisor/api/services/roundtable_memory.py` 实现分档压缩逻辑：

| 档位 | 覆盖范围 | 详细程度 | 字段保留 |
|------|----------|----------|----------|
| **Tier-1** | 最近 1 轮 | 最详细，约 1800 字符 | 用户问题（≤320）、该 persona 上轮 phase2 要点（≤600）、Moderator `seen`（≤400）、Moderator `limit`（≤400） |
| **Tier-2** | 次近 1 轮 | 中等压缩，约 800 字符 | 用户问题（≤140）、该 persona 上轮结论一句（≤200）、Moderator `seen`（≤300） |
| **Tier-3** | 更早 N 轮 | 极简摘要，每轮 ≤160 字符 | 「第 k 轮 · 用户问：XXX → Moderator 一句话结论」 |

默认字符预算 `DEFAULT_CHAR_BUDGET = 3800`，约等于中文 2000 token（按 1 token ≈ 1.7 char 估算）。

### 10.3 预算控制与组装策略

`build_memory_block()` 从 Tier-1 → Tier-2 → Tier-3 依次填充，超预算时按以下策略压缩：

1. **Step-A**：直接拼接全部三档；总长 ≤ budget → 直接返回。
2. **Step-B**：从 Tier-3 尾部（最老的轮）LIFO 丢弃，直到总长在预算内。
3. **Step-C**：若仍超预算，将 Tier-2 替换为极简版（只保留标题行 + "· 用户问" 一行）。
4. **Step-D**：最后只保留 Tier-1；若 Tier-1 本身仍超 budget，则强制硬截到 budget。

Tier-1 的 question 与 persona_self 段标记为 `droppable=False`，确保至少保留最近一轮的核心上下文。

### 10.4 Moderator 视角的记忆

除了 agent 视角的 `_build_prior_context_block`，系统还为 Moderator 单独实现了 `_build_moderator_prior_context_block`：

- **Tier-1（最近一轮）**：以 Moderator 自己的视角回顾 —— 上轮用户问什么、Moderator 自己给的 `seen` / `angles` / `lens` 核心结论。
- **Tier-2（更早轮）**：每轮保留一行「用户问 → Moderator 一句话结论」，LIFO 保留最近的。

与 agent 视角不同，Moderator 的记忆强调「自己上一轮对该用户说过的话」，让新一轮 Moderator 能**承接**自己的历史输出，避免每次都像第一次见面。

### 10.5 Metrics 与审计

每次构建记忆块都会返回 `MemoryMetrics`：

| 字段 | 含义 |
|------|------|
| `round_count` | 已归档总轮数 |
| `kept_rounds` | 本次保留的轮数 |
| `dropped_rounds` | 因预算被丢弃的轮数 |
| `char_count` | 输出文本字符数 |
| `token_estimate` | 估算 token 数 |
| `truncated` | 是否发生过截断 |
| `tier1_chars` / `tier2_chars` / `tier3_chars` | 各档字符数 |
| `tier3_rounds_kept` | Tier-3 实际保留的轮数 |

这些指标通过 `audit.emit_memory_built()` 写入审计日志，供后端诊断和前端调试面板使用。

### 10.6 接入点

- **Agent prompt 构造**：`_build_prior_context_block()` 在 Phase 1 / Phase 2 的 prompt 顶部拼接跨轮记忆 + RAG 注入上下文。
- **Moderator prompt 构造**：`_build_moderator_prior_context_block()` 在 Moderator 模板中插入「历史轮回顾」段。
- **首轮兼容**：`session.rounds` 为空时返回空串，不影响模板结构。

### 10.7 关键文件

| 文件 | 职责 |
|------|------|
| [`scripts/advisor/api/services/roundtable_memory.py`](../../scripts/advisor/api/services/roundtable_memory.py) | CrossRoundMemory 三档压缩、预算装配、metrics |
| [`scripts/advisor/api/services/roundtable_service.py`](../../scripts/advisor/api/services/roundtable_service.py) | `_build_prior_context_block` / `_build_moderator_prior_context_block` 调用入口 |
| [`tests/test_roundtable_memory.py`](../../tests/test_roundtable_memory.py) | 空轮、单轮 Tier-1、多轮 LIFO 丢弃、超大预算截断等单测 |

## 11. RAG 上下文注入

### 11.1 注入来源

注入预览端点可以搜索：

| 模式 | 后端搜索 | 返回的 DTO |
|------|----------|------------|
| `chat_history` | 富化时间线搜索 | `RoundtableChatHistoryHit` |
| `knowledge` | FAQ / 知识库搜索 | `RoundtableKnowledgeHit` |

### 11.2 用户控制

前端预览抽屉有意保持注入对用户可见：

1. 用户输入问题。
2. 用户打开注入抽屉。
3. 后端返回候选命中。
4. 用户审查建议的上下文。
5. 选定的上下文作为 `inject_context` 发送。

这防止了隐藏检索在用户不知情的情况下改变圆桌讨论回应。

### 11.3 提示词放置

注入的上下文存储在 `session.current_inject_context` 中，并在第一阶段和第二阶段的提示词构建中使用。它是轮次范围的：延续可以为下一轮替换或清除上下文。

---

## 12. 提示词与模型配置

### 12.1 提示词文件

提示词位于 [`configs/roundtable_prompts.yaml`](../../configs/roundtable_prompts.yaml)。

| 部分 | 用途 |
|------|------|
| `personas` | 每个人格的核心理论与回应风格 |
| `phase1_template` | 独立简短回应 |
| `deep_phase1_template` | 更长的独立回应 |
| `phase2_template` | 在同伴摘要后的交叉回应 |
| 深度模式模板 | 更高的令牌预算和更深的分析 |
| 主持人模板 | 结构化综合与回退行为 |

### 12.2 环境变量

| 变量 | 默认值 | 含义 |
|------|--------|------|
| `ROUNDTABLE_USE_LLM` | enabled | 切换真实 LLM 生成与模拟/回退行为 |
| `ROUNDTABLE_MAX_TOKENS` | `1024` | 普通智能体令牌预算 |
| `ROUNDTABLE_DEEP_MAX_TOKENS` | `2560` | 深度模式智能体令牌预算 |
| `ROUNDTABLE_MODERATOR_LLM` | enabled | 切换 LLM 主持人 |
| `ROUNDTABLE_MODERATOR_TIMEOUT` | `180` | 普通主持人超时 |
| `ROUNDTABLE_MODERATOR_MAX_TOKENS` | `2048` | 普通主持人令牌预算 |
| `ROUNDTABLE_DEEP_MODERATOR_TIMEOUT` | `240` | 深度模式主持人超时 |
| `ROUNDTABLE_DEEP_MODERATOR_MAX_TOKENS` | `3584` | 深度模式主持人令牌预算 |

### 12.3 后端选择

设置页面可以将 `backend` 发送到创建会话请求。如果省略，后端通过生成器服务偏好回退到配置的默认聊天后端。

---

## 13. 安全与偏见治理

### 13.1 输入危机检测

在运行完整流程之前，后端对用户问题调用危机检测。如果级别为：

| 级别 | 行为 |
|------|------|
| GREEN | 正常继续 |
| YELLOW | 发出危机事件并谨慎继续 |
| ORANGE | 发出危机事件和热线，谨慎继续 |
| RED | 发出危机事件并中断流程 |

### 13.2 输出清理

智能体输出通过 [`roundtable_service.py`](../../scripts/advisor/api/services/roundtable_service.py) 中的 `_sanitize_agent_output()`，它应用：

- 来自危机检测器的禁止回应措辞检查，
- 针对刻板印象、指责受害者、绝对关系主张、道德说教和病理化语言的偏见清理，
- 危机和偏见命中的审计发出。

### 13.3 主持人限制

主持人内容包含一个 `limit` 字段，以便最终卡片可以声明 Lens 不是医疗诊断、心理治疗、危机咨询或紧急干预。

---

## 14. 持久化与恢复

### 14.1 持久化位置

后端通过服务级 `ROUNDTABLE_DIR` 将圆桌讨论会话存储在 `advisor_out/roundtable/sessions` 下。

### 14.2 快照加载

前端可以列出摘要并加载完整会话详情：

- `api.listRoundtableSessions()`
- `api.getRoundtableSession(sessionId)`

完整快照包含当前轮次和已归档的 `rounds[]`。

### 14.3 恢复策略

| 情境 | 前端行为 |
|------|----------|
| 已完成会话 | 水合并允许后续提问 |
| 设置会话 | 水合并作为可恢复的设置/当前轮次 |
| 未完成的历史会话 | 标记为只读以避免过期的 SSE 重新连接 |
| 后端流错误 | 显示提示并存储错误状态 |
| 主持人 LLM 回退 | 渲染带有已显示回退原因的主持人卡片 |

---

## 15. 用户体验组件

| 组件 | 文件 | 职责 |
|------|------|------|
| PersonaCard | [`PersonaCard.tsx`](../../frontend/src/components/roundtable/PersonaCard.tsx) | 人格选择卡片 |
| SessionHistoryList | [`SessionHistoryList.tsx`](../../frontend/src/components/roundtable/SessionHistoryList.tsx) | 历史会话条目 |
| InjectionDrawer | [`InjectionDrawer.tsx`](../../frontend/src/components/roundtable/InjectionDrawer.tsx) | 上下文预览与选择 |
| AgentMessage | [`AgentMessage.tsx`](../../frontend/src/components/roundtable/AgentMessage.tsx) | 流式智能体输出 |
| PhaseBanner | [`PhaseBanner.tsx`](../../frontend/src/components/roundtable/PhaseBanner.tsx) | 当前阶段说明 |
| ModeratorThinking | [`ModeratorThinking.tsx`](../../frontend/src/components/roundtable/ModeratorThinking.tsx) | 流式主持人思考显示 |
| ModeratorCard | [`ModeratorCard.tsx`](../../frontend/src/components/roundtable/ModeratorCard.tsx) | 最终结构化综合 |
| FollowUpComposer | [`FollowUpComposer.tsx`](../../frontend/src/components/roundtable/FollowUpComposer.tsx) | 用新问题继续 |
| RoundHistoryCard | [`RoundHistoryCard.tsx`](../../frontend/src/components/roundtable/RoundHistoryCard.tsx) | 已归档轮次显示 |
| TypingDots | [`TypingDots.tsx`](../../frontend/src/components/roundtable/TypingDots.tsx) | 打字/流式指示 |

---

## 16. 已知限制与演进方向

| 领域 | 当前状态 | 演进方向 |
|------|----------|----------|
| 事件回放 | SSE 在断开后不回放错过的事件 | 添加序列 id 和 `Last-Event-ID` 支持 |
| 运行时状态 | 活动队列/任务是进程本地的 | 如果运行多个工作进程，添加持久任务注册表 |
| 人格数量 | 恰好三个人格 | 在用户体验测试后考虑可变规模的专家小组 |
| 主持人回退 | 当 LLM 失败时可使用规则回退 | 为主持人输出添加显式质量评分 |
| 上下文注入 | 用户选定的上下文是纯文本 | 添加结构化引用和来源开关 |
| 会话分支 | `parent_id` 存在以支持 DAG | 添加可见的分支树和分支比较 |
| 深度模式 | 令牌预算和提示词模板切换 | 添加每个人格的深度控制 |
| 审计可见性 | 审计事件在后端 | 为测试诊断添加用户界面审计面板 |

---

## 17. 文件索引

| 文件 | 职责 |
|------|------|
| [`frontend/src/pages/RoundtablePage.tsx`](../../frontend/src/pages/RoundtablePage.tsx) | 设置页面：人格选择、问题输入、后端选择、注入预览 |
| [`frontend/src/pages/RoundtableSessionPage.tsx`](../../frontend/src/pages/RoundtableSessionPage.tsx) | 会话页面：阶段渲染、SSE 连接、主持人和后续提问用户体验 |
| [`frontend/src/stores/useRoundtableStore.ts`](../../frontend/src/stores/useRoundtableStore.ts) | 共享的圆桌讨论前端状态机 |
| [`frontend/src/hooks/useRoundtableStream.ts`](../../frontend/src/hooks/useRoundtableStream.ts) | EventSource 客户端和 SSE 分发 |
| [`frontend/src/data/personas.ts`](../../frontend/src/data/personas.ts) | 圆桌讨论人格元数据 |
| [`frontend/src/lib/api.ts`](../../frontend/src/lib/api.ts) | 圆桌讨论 REST 客户端 DTO 和方法 |
| [`scripts/advisor/api/routes/roundtable.py`](../../scripts/advisor/api/routes/roundtable.py) | FastAPI 端点 |
| [`scripts/advisor/api/services/roundtable_service.py`](../../scripts/advisor/api/services/roundtable_service.py) | 会话生命周期、队列、生成流程、RAG 注入、安全检查 |
| [`scripts/advisor/api/core/models.py`](../../scripts/advisor/api/core/models.py) | Pydantic 请求/响应/会话模型 |
| [`configs/roundtable_prompts.yaml`](../../configs/roundtable_prompts.yaml) | 人格和阶段提示词模板 |

---

**文档版本**：v1.0  
**创建日期**：2026-06-13  
**相关文档**：[Advisor Web Application System Design](web_app_overview.md)、[Advisor Service Overview](../advisor/advisor_service_overview.md)、[Knowledge RAG Upgrade](../pipelines/knowledge_rag_upgrade_overview.md)、[Safety Crisis System](../pipelines/safety_crisis_overview.md)

---

# Roundtable Discussion System Design

> 📌 **Document scope**: This document describes the Lens Roundtable Discussion subsystem, including persona selection, three-phase multi-agent orchestration, SSE multiplexing, multi-round continuation, RAG context injection, safety governance, persistence, and frontend/backend contracts.
>
> Updated: 2026-06-13

---

## Table of Contents

- [1. Design Goals](#1-design-goals)
- [2. User Experience Model](#2-user-experience-model)
- [3. System Architecture](#3-system-architecture)
- [4. Persona Model](#4-persona-model)
- [5. Three-Phase Discussion Pipeline](#5-three-phase-discussion-pipeline)
- [6. Backend API Contract](#6-backend-api-contract)
- [7. SSE Event Protocol](#7-sse-event-protocol)
- [8. Frontend State Machine](#8-frontend-state-machine)
- [9. Multi-Round Continuation](#9-multi-round-continuation)
- [10. Cross-Round Memory Compression and Transfer](#10-cross-round-memory-compression-and-transfer)
- [11. RAG Context Injection](#11-rag-context-injection)
- [12. Prompt and Model Configuration](#12-prompt-and-model-configuration)
- [13. Safety and Bias Governance](#13-safety-and-bias-governance)
- [14. Persistence and Recovery](#14-persistence-and-recovery)
- [15. UX Components](#15-ux-components)
- [16. Known Limits and Evolution](#16-known-limits-and-evolution)
- [17. File Index](#17-file-index)

---

## 1. Design Goals

### 1.1 Product Role

Roundtable Discussion is the Lens multi-agent reflection surface. Instead of returning one advisor response, it asks the user to select exactly three personas and lets them discuss the same relationship question from different theoretical positions.

The module is designed for questions that benefit from perspective diversity:

- ambiguous relationship decisions,
- emotional conflicts with multiple interpretations,
- recurring communication patterns,
- questions involving personal psychology and social context,
- situations where a single advisor style may feel too narrow.

### 1.2 Core Goals

| Goal | Method | Output |
|------|--------|--------|
| Multi-perspective reflection | Three selected personas answer the same question | Phase 1 independent views |
| Cross-perspective synthesis | Each persona sees peer summaries and responds | Phase 2 cross responses |
| Reduce cognitive overload | Moderator consolidates perspectives into six structured sections | Phase 3 moderator summary |
| Preserve user agency | The system offers viewpoints, not decisions | Open-ended suggestions and uncertainty statements |
| Support continuity | Completed sessions can continue with follow-up questions | Archived rounds + current round state |
| Enable contextual grounding | Optional chat-history and knowledge injection | User-selected context block in prompts |

### 1.3 Design Principles

```text
┌──────────────────────────────────────────────────────────────────────┐
│                    Roundtable Design Principles                      │
├──────────────────────────────────────────────────────────────────────┤
│ 1. Exactly three personas per session                                │
│ 2. Phase 1 independence before Phase 2 cross-response                 │
│ 3. One SSE endpoint, multiplexed by agent_id and phase                │
│ 4. User-visible streaming, not hidden batch generation                │
│ 5. Moderator synthesis must acknowledge uncertainty and limits        │
│ 6. Safety and bias checks run before and during generation            │
│ 7. Multi-round continuation archives old rounds before new ones       │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 2. User Experience Model

### 2.1 Primary Flow

```text
Roundtable Setup Page
  ├─ choose exactly 3 personas
  ├─ enter a relationship question
  ├─ optionally select LLM backend
  ├─ optionally preview and inject context
  ├─ optionally enable deep mode
  └─ create backend session
        ↓
Roundtable Session Page
  ├─ subscribe to SSE stream
  ├─ render Phase 1 agent outputs
  ├─ render Phase 2 cross responses
  ├─ render Moderator thinking and final synthesis
  └─ allow follow-up after completion
```

### 2.2 Setup UX

The setup page lives in [`frontend/src/pages/RoundtablePage.tsx`](../../frontend/src/pages/RoundtablePage.tsx). It handles:

| UX Element | Purpose |
|------------|---------|
| Persona cards | Select three perspectives from psychology and interdisciplinary groups |
| Quick presets | Start from recommended persona combinations |
| Question quality threshold | Discourage very short prompts from using Roundtable unnecessarily |
| Backend dropdown | Let the user choose a chat-capable model backend |
| Context injection drawer | Preview chat-history and knowledge-base hits before adding context |
| Deep mode toggle | Increase token budget and switch to deeper prompt templates |
| Session history list | Reopen previous sessions and snapshots |

### 2.3 Session UX

The session page lives in [`frontend/src/pages/RoundtableSessionPage.tsx`](../../frontend/src/pages/RoundtableSessionPage.tsx). It renders:

- Phase banners and phase transitions.
- Three parallel agent columns.
- Streaming text chunks by persona.
- Agent confidence markers.
- Moderator thinking stream.
- Final moderator card.
- Archived round cards.
- Follow-up composer.
- Read-only snapshot banner when a session cannot safely resume.

---

## 3. System Architecture

### 3.1 High-Level Architecture

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                            React Frontend                                   │
│                                                                             │
│  RoundtablePage              RoundtableSessionPage                          │
│  ├─ persona selection        ├─ useRoundtableStream                         │
│  ├─ backend selector         ├─ AgentMessage components                     │
│  ├─ injection preview        ├─ ModeratorCard / ModeratorThinking           │
│  └─ create session           └─ FollowUpComposer / history cards            │
│              │                                  ▲                           │
│              ▼                                  │                           │
│        frontend/src/lib/api.ts          Zustand Roundtable Store            │
└─────────────────────────────────────────────────────────────────────────────┘
              │                                  ▲
              │ REST                             │ SSE events
              ▼                                  │
┌─────────────────────────────────────────────────────────────────────────────┐
│                         FastAPI Roundtable Router                            │
│                                                                             │
│  scripts/advisor/api/routes/roundtable.py                                    │
│  ├─ create session                                                           │
│  ├─ stream session                                                           │
│  ├─ continue session                                                         │
│  ├─ inject preview                                                           │
│  ├─ list/get sessions                                                        │
│  └─ interrupt session                                                        │
└─────────────────────────────────────────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                      Roundtable Service Orchestrator                         │
│                                                                             │
│  scripts/advisor/api/services/roundtable_service.py                          │
│  ├─ in-memory sessions, queues, tasks                                        │
│  ├─ persisted session snapshots                                              │
│  ├─ phase1 / phase2 / moderator orchestration                                │
│  ├─ generator_service backend calls                                          │
│  ├─ RAG preview and injected context                                         │
│  ├─ crisis and bias sanitation                                               │
│  └─ audit events                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 Runtime Objects

| Object | Backend Owner | Purpose |
|--------|---------------|---------|
| `_sessions` | `roundtable_service.py` | In-memory session state keyed by session id |
| `_queues` | `roundtable_service.py` | Per-session async event queue for SSE |
| `_tasks` | `roundtable_service.py` | Running pipeline tasks |
| `_subscribed` | `roundtable_service.py` | Trigger gate so generation starts after SSE subscription |
| `RoundtableSession` | `core/models.py` | Persistable session data model |
| `RoundtableRoundSnapshot` | `core/models.py` | Archived completed round |
| Zustand store | `useRoundtableStore.ts` | Frontend state across setup, stream, history, and continuation |

---

## 4. Persona Model

### 4.1 Persona Source of Truth

Roundtable uses [`frontend/src/data/personas.ts`](../../frontend/src/data/personas.ts) as the frontend source of truth for display metadata and [`configs/roundtable_prompts.yaml`](../../configs/roundtable_prompts.yaml) as the backend prompt source.

The persona ids match the backend literal type `RoundtablePersonaId` in [`scripts/advisor/api/core/models.py`](../../scripts/advisor/api/core/models.py).

### 4.2 Persona Inventory

| Persona ID | Display Name | Category | Core Lens |
|------------|--------------|----------|-----------|
| `neutral` | 中立顾问 | psychology | Facts, interpretations, needs, possible actions |
| `supportive` | 支持性顾问 | psychology | Emotional validation and user-side support |
| `psychoanalytic` | 精神分析顾问 | psychology | Unconscious scripts, defenses, early attachment |
| `eft` | EFT 情绪聚焦 | psychology | Attachment needs and pursue-withdraw cycles |
| `bowen` | 家庭系统顾问 | psychology | Family systems, differentiation, triangulation |
| `sociology` | 社会学视角 | interdisciplinary | Gender scripts, class, power, social structure |
| `philosophy` | 哲学视角 | interdisciplinary | Existential questions and reflective inquiry |
| `game_theory` | 博弈论视角 | interdisciplinary | Repeated games, incentives, credible signals |
| `cultural` | 文化视角 | interdisciplinary | Cultural scripts, intergenerational duties, rituals |

### 4.3 Selection Constraint

A session requires exactly three different persona ids. The backend enforces this in `create_roundtable_session()` by rejecting duplicate selections.

---

## 5. Three-Phase Discussion Pipeline

### 5.1 Phase Overview

| Phase | Backend Phase | Description | Frontend Rendering |
|-------|---------------|-------------|--------------------|
| Setup | `setup` | Session exists but generation has not started | Setup page or pre-stream session page |
| Phase 1 | `phase1` | Three personas independently answer the question | Three streaming agent columns |
| Phase 2 | `phase2` | Each persona responds after seeing peers' Phase 1 views | Three cross-response columns |
| Phase 3 | `phase3` | Moderator thinks and synthesizes | Moderator thinking + final card |
| Done | `done` | Session complete | Follow-up composer enabled |

### 5.2 Phase 1: Independent Analysis

Phase 1 uses `phase1_template` or `deep_phase1_template` from [`configs/roundtable_prompts.yaml`](../../configs/roundtable_prompts.yaml). Each selected persona receives:

- the user question,
- the persona core description,
- optional prior-round context,
- optional injected context.

The persona does not see the other two agents yet. This prevents premature convergence and keeps the three perspectives distinct.

### 5.3 Phase 2: Cross Response

Phase 2 uses `phase2_template` or deep-mode equivalent. Each persona receives:

- the original user question,
- its persona core description,
- summaries of the other two Phase 1 responses,
- optional prior-round and injected context.

The persona keeps its own lens while acknowledging other views.

### 5.4 Phase 3: Moderator Synthesis

The moderator produces a structured `RoundtableModeratorContent` object with six sections:

| Field | Meaning |
|-------|---------|
| `seen` | What the system understood about the user's situation |
| `angles` | Key differences between the three perspectives |
| `tries` | Actions or reflections the user may try |
| `doubts` | Remaining uncertainty and non-overclaiming caveats |
| `lens` | Lens-style closing message |
| `limit` | Limitation statement and non-medical boundary |

If LLM moderator generation fails or is disabled, the backend can fall back to a rule-based template and expose `moderator_fallback_reason` to the frontend.

---

## 6. Backend API Contract

### 6.1 Endpoint Summary

All endpoints are registered by [`scripts/advisor/api/routes/roundtable.py`](../../scripts/advisor/api/routes/roundtable.py).

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/roundtable/sessions` | Create a session without immediately starting generation |
| `GET` | `/api/roundtable/stream/{session_id}` | Subscribe to SSE and trigger the pipeline on first subscription |
| `POST` | `/api/roundtable/sessions/{session_id}/interrupt` | Cancel a running pipeline task |
| `GET` | `/api/roundtable/sessions` | List session summaries |
| `GET` | `/api/roundtable/sessions/{session_id}` | Load a full session snapshot |
| `POST` | `/api/roundtable/sessions/{session_id}/continue` | Start a new round after a completed session |
| `POST` | `/api/roundtable/inject/preview` | Preview chat-history and knowledge hits for context injection |

### 6.2 Create Session

Request model: `RoundtableStartRequest`

| Field | Type | Constraint | Meaning |
|-------|------|------------|---------|
| `personas` | list | exactly 3 | Selected persona ids |
| `question` | string | 4-2000 chars | User question |
| `parent_id` | string or null | optional | Future DAG branch parent |
| `backend` | string or null | optional | User-selected LLM backend |
| `inject_context` | string or null | max 12000 chars | User-selected context block |
| `deep_mode` | boolean | default false | Use deeper prompt and token budget |

Response model: `RoundtableStartResponse`

```json
{
  "session_id": "rt_xxxxxxxxxxxx",
  "status": "created",
  "created_at": "2026-06-13T00:00:00"
}
```

### 6.3 Continue Session

Continuation requires the current session phase to be `done`. The backend archives the completed round into `rounds[]`, resets current buffers, updates `question`, and waits for a new SSE subscription trigger.

Request model: `RoundtableContinueRequest`

| Field | Type | Meaning |
|-------|------|---------|
| `question` | string | New follow-up question |
| `inject_context` | string or null | Optional context for the new round |
| `deep_mode` | boolean or null | Override or inherit deep-mode setting |

### 6.4 Injection Preview

The injection preview endpoint returns candidate context from:

- enriched chat-history retrieval,
- knowledge-base FAQ search.

The frontend lets the user inspect and choose what to inject, rather than silently adding hidden context.

---

## 7. SSE Event Protocol

### 7.1 Transport

The stream endpoint returns `text/event-stream`. Every backend event is serialized as:

```text
data: {"type":"agent_chunk","agent_id":"neutral","phase":"phase1","delta":"..."}

```

The stream ends with:

```text
data: [DONE]

```

### 7.2 Event Types

Frontend event types are defined in [`frontend/src/hooks/useRoundtableStream.ts`](../../frontend/src/hooks/useRoundtableStream.ts).

| Event | Payload | Frontend Effect |
|-------|---------|-----------------|
| `agent_status` | `agent_id`, `phase`, `status` | Set one persona's status |
| `agent_chunk` | `agent_id`, `phase`, `delta` | Append streamed text |
| `agent_strip_tail` | `agent_id`, `phase`, `strip_chars` | Remove confidence marker tail from text |
| `agent_done` | `agent_id`, `phase`, `confidence` | Mark persona done and store confidence |
| `agent_error` | `agent_id`, `phase`, `error` | Mark persona error |
| `phase_advance` | `phase` | Move UI to next phase |
| `moderator_thinking` | `text` | Stream moderator reasoning text |
| `moderator` | `content`, `fallback_reason` | Render final moderator card |
| `crisis` | level and resources | Show safety banner / crisis state |
| `done` | none | Close stream and enable follow-up |
| `error` | message | Set error state |

### 7.3 Why One SSE Endpoint

Roundtable uses one SSE endpoint and multiplexes by `agent_id` and `phase` because:

- browser connection management is simpler,
- backend can preserve global phase ordering,
- frontend can dispatch all events through one hook,
- failures are easier to surface as one stream status.

---

## 8. Frontend State Machine

### 8.1 Store Location

State lives in [`frontend/src/stores/useRoundtableStore.ts`](../../frontend/src/stores/useRoundtableStore.ts).

### 8.2 Core State Fields

| Field | Meaning |
|-------|---------|
| `selectedPersonas` | Three chosen persona ids |
| `question` | Current round question |
| `deepMode` | Whether deep prompt/token budget is enabled |
| `sessionId` | Backend or local fallback session id |
| `currentPhase` | `setup`, `phase1`, `phase2`, `phase3`, `done`, or `error` |
| `phase1Agents` | Persona buffers for Phase 1 |
| `phase2Agents` | Persona buffers for Phase 2 |
| `moderator` | Final structured moderator content |
| `moderatorThinking` | Streaming moderator thinking text |
| `moderatorFallbackReason` | Whether moderator fell back to rule template |
| `rounds` | Archived completed rounds |
| `roundIndex` | Current zero-based round index |
| `streamNonce` | Forces EventSource reconstruction after continuation |
| `isReadOnlySnapshot` | Prevents reconnecting to stale unfinished sessions |
| `crisis` | Feature-local crisis event |
| `error` | Feature-local error message |

### 8.3 State Transitions

```text
setup
  ├─ create session
  └─ startSession(session_id)
        ↓
phase1
  ├─ agent_status / agent_chunk / agent_done
  └─ phase_advance phase2
        ↓
phase2
  ├─ agent_status / agent_chunk / agent_done
  └─ phase_advance phase3
        ↓
phase3
  ├─ moderator_thinking
  └─ moderator
        ↓
done
  ├─ follow-up continue
  └─ archiveCurrentRoundAndReset()
        ↓
setup with existing sessionId
  └─ streamNonce increments and session page reconnects
```

### 8.4 Read-Only Snapshot Mode

When a historical session is loaded and its backend phase is neither `done` nor `setup`, the frontend marks it as `isReadOnlySnapshot`. This prevents opening an EventSource for a pipeline that may no longer exist in the current backend process.

---

## 9. Multi-Round Continuation

### 9.1 Continuation Strategy

Roundtable uses continuation form A:

- keep the same session id,
- archive the completed round into `rounds[]`,
- reset current buffers,
- increment `round_index`,
- start a new question as the current round,
- force a new EventSource connection through `streamNonce`.

### 9.2 Archived Round Shape

Each `RoundtableRoundSnapshot` stores:

- `round_index`,
- `question`,
- Phase 1 agent buffers,
- Phase 2 agent buffers,
- moderator content,
- moderator thinking,
- creation and completion timestamps.

This makes old rounds renderable even after the current round changes.

### 9.3 Why Archive Before Reset

The backend deep-copies current buffers before resetting them. This avoids reference sharing between archived rounds and the new current round.

---

---

## 10. Cross-Round Memory Compression and Transfer

### 10.1 Design Motivation

Multi-Round Continuation archives each round's full `RoundtableRoundSnapshot`, but injecting all historical round raw text into the next round's prompt faces two problems:

- **Early content loss**: When there are more than 3 rounds, `_build_prior_context_block` only taking the most recent round completely forgets earlier discussion points.
- **Token budget exhaustion**: When a single round is long, uncompressed historical text crowds out the remaining space for persona_core + user question + LLM output.

Therefore the system introduces the **CrossRoundMemory** module, which compresses archived `session.rounds` by priority tiers, constructing differentiated historical review prompts for each persona and the Moderator within a controllable character budget.

### 10.2 Three-Tier Compression Strategy

`scripts/advisor/api/services/roundtable_memory.py` implements the tiered compression logic:

| Tier | Scope | Detail Level | Fields Retained |
|------|-------|--------------|-----------------|
| **Tier-1** | Most recent 1 round | Most detailed, ~1800 chars | User question (≤320), this persona's last phase2 highlights (≤600), Moderator `seen` (≤400), Moderator `limit` (≤400) |
| **Tier-2** | Second most recent 1 round | Medium compression, ~800 chars | User question (≤140), this persona's last conclusion in one sentence (≤200), Moderator `seen` (≤300) |
| **Tier-3** | Earlier N rounds | Minimal summary, ≤160 chars per round | "Round k · User asked: XXX → Moderator one-sentence conclusion" |

Default character budget `DEFAULT_CHAR_BUDGET = 3800`, approximately 2000 Chinese tokens (estimated at 1 token ≈ 1.7 chars).

### 10.3 Budget Control and Assembly Strategy

`build_memory_block()` fills from Tier-1 → Tier-2 → Tier-3 in order. When exceeding budget, it compresses using the following strategy:

1. **Step-A**: Concatenate all three tiers directly; if total length ≤ budget, return immediately.
2. **Step-B**: From the tail of Tier-3 (oldest rounds), LIFO discard until total length is within budget.
3. **Step-C**: If still over budget, replace Tier-2 with an ultra-compact version (only keep the header line + "· User asked" line).
4. **Step-D**: As a last resort, keep only Tier-1; if Tier-1 itself still exceeds budget, force hard truncation to budget.

The question and persona_self segments in Tier-1 are marked `droppable=False`, ensuring at least the core context of the most recent round is retained.

### 10.4 Moderator-View Memory

In addition to the agent-view `_build_prior_context_block`, the system separately implements `_build_moderator_prior_context_block` for the Moderator:

- **Tier-1 (most recent round)**: Reviewed from the Moderator's own perspective — what the user asked last round, and the Moderator's own core conclusions (`seen` / `angles` / `lens`).
- **Tier-2 (earlier rounds)**: Each round keeps one line "User asked → Moderator one-sentence conclusion", with the most recent preserved via LIFO.

Unlike the agent view, the Moderator's memory emphasizes "what the Moderator itself said to this user last round", allowing the new round's Moderator to **carry forward** its historical output rather than sounding like a first meeting every time.

### 10.5 Metrics and Audit

Each memory block build returns `MemoryMetrics`:

| Field | Meaning |
|-------|---------|
| `round_count` | Total archived rounds |
| `kept_rounds` | Rounds retained this time |
| `dropped_rounds` | Rounds dropped due to budget |
| `char_count` | Output text character count |
| `token_estimate` | Estimated token count |
| `truncated` | Whether truncation occurred |
| `tier1_chars` / `tier2_chars` / `tier3_chars` | Character count per tier |
| `tier3_rounds_kept` | Tier-3 rounds actually retained |

These metrics are written to the audit log via `audit.emit_memory_built()` for backend diagnostics and frontend debugging panels.

### 10.6 Integration Points

- **Agent prompt construction**: `_build_prior_context_block()` prepends cross-round memory + RAG injected context at the top of Phase 1 / Phase 2 prompts.
- **Moderator prompt construction**: `_build_moderator_prior_context_block()` inserts a "historical round review" segment into the Moderator template.
- **First-round compatibility**: When `session.rounds` is empty, returns an empty string without affecting template structure.

### 10.7 Key Files

| File | Responsibility |
|------|----------------|
| [`scripts/advisor/api/services/roundtable_memory.py`](../../scripts/advisor/api/services/roundtable_memory.py) | CrossRoundMemory three-tier compression, budget assembly, metrics |
| [`scripts/advisor/api/services/roundtable_service.py`](../../scripts/advisor/api/services/roundtable_service.py) | Call entry points for `_build_prior_context_block` / `_build_moderator_prior_context_block` |
| [`tests/test_roundtable_memory.py`](../../tests/test_roundtable_memory.py) | Unit tests for empty rounds, single-round Tier-1, multi-round LIFO drop, oversized budget truncation |

## 11. RAG Context Injection

### 11.1 Injection Sources

The injection preview endpoint can search:

| Mode | Backend Search | Returned DTO |
|------|----------------|--------------|
| `chat_history` | enriched timeline search | `RoundtableChatHistoryHit` |
| `knowledge` | FAQ / knowledge-base search | `RoundtableKnowledgeHit` |

### 11.2 User Control

The frontend preview drawer intentionally keeps injection user-visible:

1. User enters a question.
2. User opens injection drawer.
3. Backend returns candidate hits.
4. User reviews the suggested context.
5. Selected context is sent as `inject_context`.

This prevents hidden retrieval from changing a Roundtable response without user awareness.

### 11.3 Prompt Placement

Injected context is stored in `session.current_inject_context` and used by prompt construction for Phase 1 and Phase 2. It is round-scoped: continuation can replace or clear the context for the next round.

---

## 12. Prompt and Model Configuration

### 12.1 Prompt File

Prompts live in [`configs/roundtable_prompts.yaml`](../../configs/roundtable_prompts.yaml).

| Section | Purpose |
|---------|---------|
| `personas` | Core theory and response style per persona |
| `phase1_template` | Independent short response |
| `deep_phase1_template` | Longer independent response |
| `phase2_template` | Cross-response after peer summaries |
| Deep mode templates | Higher token budget and deeper analysis |
| Moderator templates | Structured synthesis and fallback behavior |

### 12.2 Environment Variables

| Variable | Default | Meaning |
|----------|---------|---------|
| `ROUNDTABLE_USE_LLM` | enabled | Toggle real LLM generation vs mock/fallback behavior |
| `ROUNDTABLE_MAX_TOKENS` | `1024` | Normal agent token budget |
| `ROUNDTABLE_DEEP_MAX_TOKENS` | `2560` | Deep-mode agent token budget |
| `ROUNDTABLE_MODERATOR_LLM` | enabled | Toggle LLM moderator |
| `ROUNDTABLE_MODERATOR_TIMEOUT` | `180` | Normal moderator timeout |
| `ROUNDTABLE_MODERATOR_MAX_TOKENS` | `2048` | Normal moderator token budget |
| `ROUNDTABLE_DEEP_MODERATOR_TIMEOUT` | `240` | Deep-mode moderator timeout |
| `ROUNDTABLE_DEEP_MODERATOR_MAX_TOKENS` | `3584` | Deep-mode moderator token budget |

### 12.3 Backend Selection

The setup page can send `backend` to the create-session request. If omitted, the backend falls back to the configured default chat backend through generator service preferences.

---

## 13. Safety and Bias Governance

### 13.1 Input Crisis Detection

Before running the full pipeline, the backend calls crisis detection on the user question. If the level is:

| Level | Behavior |
|-------|----------|
| GREEN | Continue normally |
| YELLOW | Emit crisis event and continue with caution |
| ORANGE | Emit crisis event and hotlines, continue with caution |
| RED | Emit crisis event and interrupt the pipeline |

### 13.2 Output Sanitization

Agent output passes through `_sanitize_agent_output()` in [`roundtable_service.py`](../../scripts/advisor/api/services/roundtable_service.py), which applies:

- prohibited response wording checks from the crisis detector,
- bias sanitization for stereotypes, victim blaming, absolute relationship claims, moralizing, and pathologizing language,
- audit emission for crisis and bias hits.

### 13.3 Moderator Limits

The moderator content includes a `limit` field so the final card can state that Lens is not medical diagnosis, psychotherapy, crisis counseling, or emergency intervention.

---

## 14. Persistence and Recovery

### 14.1 Persistence Location

The backend stores Roundtable sessions under `advisor_out/roundtable/sessions` through the service-level `ROUNDTABLE_DIR`.

### 14.2 Snapshot Loading

The frontend can list summaries and load full session details:

- `api.listRoundtableSessions()`
- `api.getRoundtableSession(sessionId)`

The full snapshot contains the current round and archived `rounds[]`.

### 14.3 Recovery Policy

| Situation | Frontend Behavior |
|-----------|-------------------|
| Completed session | Hydrate and allow follow-up |
| Setup session | Hydrate as resumable setup/current round |
| Unfinished historical session | Mark read-only to avoid stale SSE reconnect |
| Backend stream error | Show toast and store error state |
| Moderator LLM fallback | Render moderator card with fallback reason surfaced |

---

## 15. UX Components

| Component | File | Responsibility |
|-----------|------|----------------|
| PersonaCard | [`PersonaCard.tsx`](../../frontend/src/components/roundtable/PersonaCard.tsx) | Persona selection card |
| SessionHistoryList | [`SessionHistoryList.tsx`](../../frontend/src/components/roundtable/SessionHistoryList.tsx) | Historical session entry |
| InjectionDrawer | [`InjectionDrawer.tsx`](../../frontend/src/components/roundtable/InjectionDrawer.tsx) | Context preview and selection |
| AgentMessage | [`AgentMessage.tsx`](../../frontend/src/components/roundtable/AgentMessage.tsx) | Streaming persona output |
| PhaseBanner | [`PhaseBanner.tsx`](../../frontend/src/components/roundtable/PhaseBanner.tsx) | Current phase explanation |
| ModeratorThinking | [`ModeratorThinking.tsx`](../../frontend/src/components/roundtable/ModeratorThinking.tsx) | Streaming moderator thinking display |
| ModeratorCard | [`ModeratorCard.tsx`](../../frontend/src/components/roundtable/ModeratorCard.tsx) | Final structured synthesis |
| FollowUpComposer | [`FollowUpComposer.tsx`](../../frontend/src/components/roundtable/FollowUpComposer.tsx) | Continue with a new question |
| RoundHistoryCard | [`RoundHistoryCard.tsx`](../../frontend/src/components/roundtable/RoundHistoryCard.tsx) | Archived round display |
| TypingDots | [`TypingDots.tsx`](../../frontend/src/components/roundtable/TypingDots.tsx) | Typing/streaming affordance |

---

## 16. Known Limits and Evolution

| Area | Current State | Evolution Direction |
|------|---------------|--------------------|
| Event replay | SSE does not replay missed events after disconnect | Add sequence ids and `Last-Event-ID` support |
| Runtime state | Active queues/tasks are process-local | Add durable task registry if running multiple workers |
| Persona count | Exactly three personas | Consider expert panels with variable size after UX testing |
| Moderator fallback | Rule fallback is available when LLM fails | Add explicit quality scoring for moderator outputs |
| Context injection | User-selected context is plain text | Add structured citations and source toggles |
| Session branching | `parent_id` exists for DAG support | Add visible branch tree and compare branches |
| Deep mode | Token budget and prompt template switch | Add per-persona depth controls |
| Audit visibility | Audit events are backend-side | Add UI audit panel for beta diagnostics |

---

## 17. File Index

| File | Responsibility |
|------|----------------|
| [`frontend/src/pages/RoundtablePage.tsx`](../../frontend/src/pages/RoundtablePage.tsx) | Setup page: persona selection, question entry, backend selection, injection preview |
| [`frontend/src/pages/RoundtableSessionPage.tsx`](../../frontend/src/pages/RoundtableSessionPage.tsx) | Session page: phase rendering, SSE connection, moderator and follow-up UX |
| [`frontend/src/stores/useRoundtableStore.ts`](../../frontend/src/stores/useRoundtableStore.ts) | Shared Roundtable frontend state machine |
| [`frontend/src/hooks/useRoundtableStream.ts`](../../frontend/src/hooks/useRoundtableStream.ts) | EventSource client and SSE dispatch |
| [`frontend/src/data/personas.ts`](../../frontend/src/data/personas.ts) | Roundtable persona metadata |
| [`frontend/src/lib/api.ts`](../../frontend/src/lib/api.ts) | Roundtable REST client DTOs and methods |
| [`scripts/advisor/api/routes/roundtable.py`](../../scripts/advisor/api/routes/roundtable.py) | FastAPI endpoints |
| [`scripts/advisor/api/services/roundtable_service.py`](../../scripts/advisor/api/services/roundtable_service.py) | Session lifecycle, queues, generation pipeline, RAG injection, safety checks |
| [`scripts/advisor/api/core/models.py`](../../scripts/advisor/api/core/models.py) | Pydantic request/response/session models |
| [`configs/roundtable_prompts.yaml`](../../configs/roundtable_prompts.yaml) | Persona and phase prompt templates |

---

**Document version**: v1.0  
**Created**: 2026-06-13  
**Related documents**: [Advisor Web Application System Design](web_app_overview.md), [Advisor Service Overview](../advisor/advisor_service_overview.md), [Knowledge RAG Upgrade](../pipelines/knowledge_rag_upgrade_overview.md), [Safety Crisis System](../pipelines/safety_crisis_overview.md)
