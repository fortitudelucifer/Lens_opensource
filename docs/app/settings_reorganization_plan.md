# 设置页信息架构重排设计方案

> 📌 **文档范围**：本文档诊断当前「设置」页与 Dashboard 在信息架构（IA）上的受众混淆问题，并给出以「用户/开发者模式开关」为骨架的重排设计、模型面板合一、原材料流水线归位，以及分阶段执行方案。面向未来执行代理。
>
> 🎯 **核心决策**：新增一个「开发者/用户模式」切换开关（做法对标中/英语言切换），默认用户模式，把运维内容对普通用户（尤其公开镜像访客）隐藏。
>
> ✅ **状态**：已实现并通过验证；本文档保留为信息架构设计与验收依据。
>
> 更新时间：2026-06-23

---

## 目录

- [1. 执行摘要](#1-执行摘要)
- [2. 现状与问题诊断](#2-现状与问题诊断)
- [3. 设计原则](#3-设计原则)
- [4. 目标信息架构（模式开关为骨架）](#4-目标信息架构模式开关为骨架)
- [5. 模型与连通面板（合一）](#5-模型与连通面板合一)
- [6. 原材料流水线呈现](#6-原材料流水线呈现)
- [7. 用户模式下的设置页](#7-用户模式下的设置页)
- [8. 模式开关实现设计（镜像语言切换）](#8-模式开关实现设计镜像语言切换)
- [9. 分阶段执行方案](#9-分阶段执行方案)
- [10. 验收标准](#10-验收标准)
- [11. 风险与回退](#11-风险与回退)
- [12. 文件索引](#12-文件索引)

---

## 1. 执行摘要

Lens 同时服务两类用户——**终端用户**（来做关系咨询的人）与**运维/开发者**（跑数据流水线、配模型、查 key 的人）。当前前端把这两类人的功能**混在同一层级**：「设置」页是一条 7 段长滚动，既有模型后端配置/连通测试/API Key/训练数据路径，又有反馈/数据删除/隐私政策；而 `Dashboard` 才是真正的运维主页。

后果：① 模型配置「设置页编辑 / Dashboard 只读显示」两处割裂；② **原材料流水线被劈成两半**（控制在 Dashboard、L1/L2 数据路径却列在用户设置）；③ 公开镜像（Lens_opensource）把 API Key、流水线、训练数据路径暴露给任意访客——对关系咨询类产品是认知 + 信任双重问题。

**推荐方案**：引入一个**「用户/开发者模式」全局开关**（对标中/英语言切换的交互），默认用户模式：

- **用户模式**：只见对话、知识中心、圆桌、评估，以及一个**简洁的用户设置**（语言/主题、隐私、删除数据、反馈）。
- **开发者模式**：在此之上显示**运维台**（流水线 + 统计 + 合一的「模型与连通」面板 + API Key + L1/L2 数据路径）。

同时把三个分散的模型组件**合一**，把流水线及其 L1/L2 路径**整块归到运维台**。本次为纯前端 IA 改动，可分阶段独立落地与回退。

---

## 2. 现状与问题诊断

### 2.1 设置页现状（`App.tsx` `activeNav==='settings'`，约 L236–387）

一条 7 段平铺长滚动，受众交替跳跃：

| 段 | 组件 | 面向 |
|----|------|------|
| 模型选择 | `ModelSelector` | 🔧 运维 |
| 连通测试 | `ModelTester` | 🔧 运维 |
| API Key 管理 | `ApiKeyChecker` | 🔧 运维 |
| 配置路径（含 **L1/L2 训练数据**路径） | 内联 | 🔧 运维 |
| 问题反馈 | `FeedbackForm` | 👤 用户 |
| 数据删除（GDPR/CCPA） | 内联 | 👤 用户 |
| 隐私政策 | 内联 | 👤 用户 |

### 2.2 Dashboard 才是真正的运维台（`pages/Dashboard.tsx`）

`PipelinePanel`（流水线控制）+ `dashboard/ModelConfig`（模型只读摘要）+ `StatsCard`（处理量/完成率/分片统计）+ `ActivityFeed`。`web_app_overview.md` 已自述系统服务「开发者和测试用户」，但 IA 未对此分流。

### 2.3 三个具体问题

1. **模型配置割裂**：`ModelSelector` 在设置页**编辑**，`dashboard/ModelConfig` 在 Dashboard**只读显示**（标注"来自设置"）。用户/运维都不清楚"到底哪个才是改模型的地方"。
2. **原材料流水线劈成两半**：流水线**控制**（`PipelinePanel`）在 Dashboard，流水线**产物路径**（`timeline_out/agent_sft_l1.jsonl` / `_l2.jsonl`）却作为「配置路径」列在用户设置。一个流程横跨两页，概念是断的。
3. **公开镜像暴露运维内幕**：Lens_opensource 是公开版，普通访客**不该**看到 API Key、流水线、训练数据机制。咨询类产品尤其不该把"对话→训练数据"裸露在用户设置里（该说明属于 ConsentPage，且需明确同意语境）。

---

## 3. 设计原则

| 原则 | 含义 |
|------|------|
| **受众分离** | 用户功能与运维功能分两个面，不在同一层级混排 |
| **单一事实源** | 模型配置只有一个权威入口（合一面板），别"一处改一处显示" |
| **渐进式披露** | 默认呈现最简洁的用户视图，运维内容按需（开关）展开 |
| **公开镜像安全优先** | 默认隐藏一切运维内幕；公开访客零暴露 |

---

## 4. 目标信息架构（模式开关为骨架）

### 4.1 模式开关（主脊）

新增一个全局「用户 / 开发者」模式开关，**交互对标中/英语言切换**：小控件、即时切换、localStorage 持久化、放在侧栏（与语言切换同处）。**默认 = 用户模式**。

```
侧栏底部控件:   [ 🌐 中 / EN ]   [ 👤 用户 / 🔧 开发者 ]
                  语言切换            新增的模式切换（本方案）
```

### 4.2 两种模式可见的内容

```
┌─ 用户模式（默认，公开访客所见）──────────────┐
│  导航:  对话 · 知识中心 · 圆桌 · 评估 · 设置  │
│  设置:  语言/主题 · 隐私政策 · Consent ·      │
│         删除我的数据 · 反馈                    │
└───────────────────────────────────────────────┘

┌─ 开发者模式（切换开关后）────────────────────┐
│  导航:  以上 + 运维台(Dashboard)              │
│  运维台: 数据流水线(8阶段) + 统计 +           │
│          「模型与连通」面板(合一) +           │
│          API Key + L1/L2 数据路径            │
│  设置:  用户设置(同上) + 运维设置区           │
└───────────────────────────────────────────────┘
```

### 4.3 导航与设置随模式显隐

- 导航项（`layout/Sidebar.tsx`）打 `user | operator` 标签，按当前模式过滤渲染。
- 设置页（`App.tsx`）拆为 `<UserSettings/>`（始终渲染）+ `<OperatorSettings/>`（仅开发者模式渲染）。
- 运维专属页（Dashboard 及其子面板）仅开发者模式出现在导航中。

---

## 5. 模型与连通面板（合一）

把三个（实为四处）分散的模型相关组件合并成**一个权威面板**：

| 现状（分散） | 合一后 |
|--------------|--------|
| `ModelSelector`（角色选型：chat/analysis/review） | 「模型与连通」面板 · 选型区 |
| `ModelTester`（连通测试） | 同面板 · 连通区（自动显示 + 单测） |
| `ApiKeyChecker`（自定义 key 检查） | 同面板 · Key 检查区 |
| `dashboard/ModelConfig`（只读摘要） | 由合一面板取代，Dashboard 引用同一组件 |

**复用已建能力**：
- 自动连通状态 ← `GET /api/models/reachable`（真探 `GET /models`，缓存 5 分钟；连通下拉与设置页连通组件已统一到此来源）。
- 单后端深测（延迟 + 回复预览）← `GET /api/models/test`。
- 选型偏好读写 ← `/api/models/preferences`。

收益：单一事实源；连通状态在「面板」「聊天模型下拉」「Dashboard 摘要」三处一致。

---

## 6. 原材料流水线呈现

流水线整块归运维台，**不再劈成两半**：

- `PipelinePanel`（控制）+ 8 阶段 `pipeline_state` 进度可视化 + **L1/L2 数据路径**（从用户设置移来）三者**放在一起**。
- 8 阶段（来自后端 `pipeline_state`）：① 片段提取 ② LLM 分析 ③ AI 自审 ④ 人工审核 ⑤ 训练数据格式化 ⑥ LoRA 微调 ⑦ GraphRAG 增量索引 ⑧ 部署验证。
- 对**终端用户**："数据 → 训练"的说明只在 `ConsentPage` / `PrivacyPage` 以明确同意语境呈现，绝不以"配置路径"形式裸露在设置里。

---

## 7. 用户模式下的设置页

瘦身后仅保留终端用户真正需要的：

| 段 | 来源 |
|----|------|
| 语言 / 主题 | `LanguageSwitcher` + 主题切换 |
| 隐私政策 | 现内联段 / `PrivacyPage` 入口 |
| Consent 入口 | `ConsentPage` |
| 删除我的数据（GDPR/CCPA） | 现 DataErase 段 |
| 反馈 | `FeedbackForm` |

**移除**（移入开发者模式运维台）：模型选择、连通测试、API Key、配置路径（含 L1/L2）。

---

## 8. 模式开关实现设计（镜像语言切换）

直接对标 `frontend/src/components/settings/LanguageSwitcher.tsx`：

| 维度 | 语言切换（现有，样板） | 模式切换（新增） |
|------|------------------------|------------------|
| 组件 | `settings/LanguageSwitcher.tsx` | `settings/ModeSwitcher.tsx`（新） |
| 状态源 | `i18n.language`（i18next） | `useUiMode()` hook + React context（新） |
| 持久化 | i18next localStorage 探测 | `localStorage['lens-ui-mode']` |
| 默认值 | 跟随检测 | **`user`**（公开安全） |
| 挂载点 | `layout/Sidebar.tsx` ~L148 | 紧邻 `<LanguageSwitcher/>` |
| 消费方 | 各组件 `t()` | 导航过滤 + 设置分区 + 运维页 gate |

要点：
- `useUiMode()` 返回 `{ mode, setMode }`，用法类比 `useTranslation()`。
- 公开构建可加一个构建/环境开关（如 `VITE_ALLOW_OPERATOR_MODE`），彻底锁死开发者模式入口；默认仍是运行时开关即可。
- i18n：`zh-CN.json` / `en-US.json` 增 `mode.user` / `mode.developer` 等键。

---

## 9. 分阶段执行方案

| 阶段 | 内容 | 关键文件 |
|------|------|----------|
| **P1 模式骨架** | `ModeSwitcher` + `useUiMode` + 持久化；挂到 Sidebar（语言切换旁）；导航项打 `user/operator` 标签按模式过滤 | `settings/ModeSwitcher.tsx`(新)、`layout/Sidebar.tsx`、`App.tsx` |
| **P2 设置拆分** | 设置页拆 `UserSettings`（始终）+ `OperatorSettings`（仅开发者）；L1/L2 路径移入运维台/流水线区 | `App.tsx`、新增两个 settings 子组件 |
| **P3 模型面板合一** | 合并 `ModelSelector`+`ModelTester`+`ApiKeyChecker`（+取代 `ModelConfig`）为「模型与连通」面板，复用 reachable/test 端点 | `ModelSelector/ModelTester/ApiKeyChecker.tsx`、`dashboard/ModelConfig.tsx` |
| **P4 流水线呈现** | 运维台内流水线 8 阶段视图打磨 + L1/L2 路径并入 | `dashboard/PipelinePanel.tsx`、`pages/Dashboard.tsx` |
| 贯穿 | i18n 键（zh-CN/en-US）；公开构建默认用户模式 | `i18n/locales/*.json` |

各阶段可独立上线/回退；P1 是其余阶段的前置。

---

## 10. 验收标准

- 切换「用户 ↔ 开发者」模式后，导航项与设置分区**随之显隐**，刷新后**保持**（localStorage）。
- **用户模式**下：无任何模型后端、API Key、流水线、训练数据路径可见；设置页仅 5 项用户内容。
- **开发者模式**下：运维台出现，「模型与连通」面板显示**真实连通**状态（reachable），流水线与 L1/L2 仅在此可见。
- 公开构建默认进入用户模式；普通访客零暴露运维内幕。
- 模型配置改一处，聊天下拉 / 面板 / Dashboard 摘要三处一致（单一事实源）。
- `npx tsc -b --noEmit` 通过；前后端启动后人工走查上述路径。

---

## 11. 风险与回退

| 风险 | 应对 |
|------|------|
| 模式开关被普通用户误开 | 默认用户模式；公开构建可加 `VITE_ALLOW_OPERATOR_MODE` 彻底锁死 |
| 合并模型组件引入回归 | 分阶段（P3 独立）；保留 reachable/test 端点不变 |
| L1/L2 路径迁移遗漏引用 | 全局搜 `agent_sft_l1/l2` 引用点统一迁移 |
| 持久化影响后端 | 纯前端 localStorage，不触后端；可随时切回 |

---

## 12. 文件索引

**前端（实现时涉及）**
- `frontend/src/App.tsx` — 设置渲染（~L236–387）、nav 渲染、模式 gate
- `frontend/src/components/layout/Sidebar.tsx` — 导航项定义、~L148 挂载点
- `frontend/src/components/settings/LanguageSwitcher.tsx` — **镜像样板**
- `frontend/src/components/settings/ModeSwitcher.tsx` — **新增**（模式开关）
- `frontend/src/components/{ModelSelector,ModelTester,ApiKeyChecker}.tsx` — 合一来源
- `frontend/src/components/dashboard/{ModelConfig,PipelinePanel,StatsCard,ActivityFeed}.tsx`
- `frontend/src/pages/Dashboard.tsx` — 运维台
- `frontend/src/i18n/locales/{zh-CN,en-US}.json` — `settings.*` + 新 `mode.*` 键

**后端（仅引用，无需改）**
- `GET /api/models`、`GET /api/models/reachable`（已新增）、`GET /api/models/test`、`/api/models/preferences`、`/api/pipeline/status`

---

*本文档为设计交付物；代码实现（ModeSwitcher、设置拆分、模型面板合并）为后续独立任务。*
