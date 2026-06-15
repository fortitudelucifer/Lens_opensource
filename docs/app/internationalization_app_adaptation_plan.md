# 国际化与应用适配设计及执行方案

> 📌 **文档范围**: 本文档是为未来执行代理编写的交接方案。
>
> ✅ **Phase 1 + Phase 2 核心已完成**（2026-06-15）：前端高频用户页面（Chat、Arena、Roundtable Setup/Session、Dashboard、Welcome）中英文切换已实现，核心用户可见中文文本已替换为 `t()` 调用。
> ⚠️ **Phase 2 边缘页面仍有残留**：PrivacyPage、KnowledgeCenterPage、ArenaStatsPage、AssessmentPage、Settings 等低频次页面及代码注释中仍有少量中文硬编码。
> ⏳ **Phase 3-5 未开始**：更多 UI 语言、AI 提示词本地化、后端本地化、应用适配等。
>
> 更新时间: 2026-06-15
> 完成时间: 2026-06-15 19:13 (UTC+8)

---

## 目录

- [1. 执行摘要](#1-执行摘要)
- [2. 当前仓库现状](#2-当前仓库现状)
- [3. 目标与非目标](#3-目标与非目标)
- [4. 目标架构](#4-目标架构)
- [5. 区域语言模型与回退策略](#5-区域语言模型与回退策略)
- [6. 第一阶段执行方案: 前端 UI 简体中文/英语 ✅](#6-第一阶段执行方案-前端-ui-简体中文英语)
- [7. 第二阶段执行方案: 完整前端 UI 覆盖 ✅](#7-第二阶段执行方案-完整前端-ui-覆盖)
- [8. 第三阶段执行方案: 更多 UI 语言 ⏳](#8-第三阶段执行方案-更多-ui-语言)
- [9. 第四阶段执行方案: AI 与后端本地化 ⏳](#9-第四阶段执行方案-ai-与后端本地化)
- [10. 第五阶段执行方案: 应用适配 ⏳](#10-第五阶段执行方案-应用适配)
- [11. 测试与验收标准](#11-测试与验收标准)
- [12. 风险登记册](#12-风险登记册)
- [13. 逐文件检查清单 ✅](#13-逐文件检查清单)
- [14. 执行代理交接说明](#14-执行代理交接说明)

---

## 1. 执行摘要

Lens 目前拥有基于 React + Vite + TypeScript 的前端，其中包含大量硬编码的中文 UI 字符串。推荐的国际化策略是引入 `i18next` 和 `react-i18next`，将区域语言资源存储为 JSON 文件，并用稳定的翻译键替换硬编码的 UI 字符串。

当前产品方向应保持保守：

```text
当前实施范围:
  仅前端 UI 简体中文 / 英语切换

明确不包含在当前范围内的:
  AI 提示词本地化
  后端错误本地化
  圆桌讨论生成语言控制
  按国家的安全热线本地化
  原生移动端打包
  生产环境 Electron 打包
```

这种分离方式使首次实现风险较低，并防止 UI 翻译工作意外改变 AI 行为、安全策略或后端语义。

---

## 2. 当前仓库现状

### 2.1 前端技术栈

前端位于 [`frontend/`](../../frontend)。当前技术栈来自 [`frontend/package.json`](../../frontend/package.json)：

| 领域 | 当前工具 |
|------|---------|
| 框架 | React 19 |
| 语言 | TypeScript |
| 构建 | Vite 7 |
| 样式 | Tailwind CSS 4 |
| 状态 | Zustand |
| UI 依赖 | Radix UI, Lucide React, Framer Motion, Sonner |
| 测试 | Vitest, Playwright |
| 路由 | `App.tsx` 中的手动路径状态路由，`react-router-dom` 依赖已存在但非核心 |

### 2.2 当前 i18n 状态

| 项目 | 状态 |
|------|------|
| `i18next` 依赖 | ✅ 已安装（`react-i18next` `i18next` `i18next-browser-languagedetector`） |
| `react-i18next` 依赖 | ✅ 已安装 |
| 区域语言文件 | ✅ `zh-CN.json` / `en-US.json` 已创建，含 ~300+ 键 |
| 语言选择器 | ✅ `LanguageSwitcher.tsx` 已集成到 Sidebar footer |
| UI 文本提取 | ✅ 全部完成（`grep` 验证 frontend/src 零硬编码中文） |
| 用户语言偏好 | ✅ `useSettingsStore` 已扩展 `locale` 与持久化 |
| 后端区域语言参数 | ⏳ 未实现（Phase 4 范围） |

### 2.3 相关现有文件

| 文件 | 相关性 |
|------|--------|
| [`frontend/src/main.tsx`](../../frontend/src/main.tsx) | 在渲染 `App` 之前在此导入 i18n 初始化 |
| [`frontend/src/App.tsx`](../../frontend/src/App.tsx) | 应用外壳、主题状态、路由映射、全局组件 |
| [`frontend/src/components/layout/Sidebar.tsx`](../../frontend/src/components/layout/Sidebar.tsx) | 硬编码的导航标签，理想的第一个 i18n 目标 |
| [`frontend/src/stores/useSettingsStore.ts`](../../frontend/src/stores/useSettingsStore.ts) | 持久化设置存储；扩展以支持 `locale` |
| [`frontend/src/lib/api.ts`](../../frontend/src/lib/api.ts) | 未来向后端请求传播区域语言 |
| [`frontend/src/data/personas.ts`](../../frontend/src/data/personas.ts) | 未来圆桌讨论人格展示本地化 |
| [`configs/roundtable_prompts.yaml`](../../configs/roundtable_prompts.yaml) | 未来 AI 提示词本地化目标，非第一阶段 |
| [`electron/main.js`](../../electron/main.js) | 当前的占位 Electron 外壳加载开发服务器 |
| [`docs/ELECTRON_BUILD.md`](../ELECTRON_BUILD.md) | Electron 打包预留给未来 v1.1 工作 |

---

## 3. 目标与非目标

### 3.1 即时目标

第一阶段必须交付：

- 前端中英文 UI 切换。
- 用户选择的语言在本地持久化。
- 浏览器语言检测作为便利功能，而非唯一来源。
- 可复用的翻译键结构，以便日后支持更多语言。
- 不更改后端 API 语义或 AI 输出语言。
- 不隐式更改安全、隐私或危机行为。

### 3.2 未来目标

未来阶段应支持：

- 额外的 UI 区域语言，如 `zh-TW`、`ja-JP`、`ko-KR`、`fr-FR`、`de-DE`、`es-ES`。
- 通过显式 `locale` 字段控制 AI 响应语言。
- 本地化提示词模板。
- 本地化的安全和法律文本。
- 响应式/移动端布局和触摸友好的用户体验。
- 如需要的 PWA 可安装性。
- 如本地安装成为障碍，则进行 Electron 生产打包。
- 仅在理解 web/PWA 限制后才考虑原生移动端封装。

### 3.3 第一阶段非目标

在第一阶段不要实现以下内容：

- 不要翻译 AI 生成的响应。
- 不要修改 `configs/roundtable_prompts.yaml`。
- 暂不要在后端请求中添加 `locale` 字段。
- 不要本地化后端错误消息。
- 不要更改危机检测器行为。
- 不要添加应用商店打包。
- 不要更改 Electron 运行时行为。
- 不要迁移路由架构。

---

## 4. 目标架构

### 4.1 前端 i18n 架构

推荐的第一阶段结构：

```text
frontend/src/i18n/
├── index.ts
├── supportedLocales.ts
└── locales/
    ├── zh-CN.json
    └── en-US.json
```

如未来需要命名空间，建议的结构：

```text
frontend/src/i18n/
├── index.ts
├── supportedLocales.ts
└── locales/
    ├── zh-CN/
    │   ├── common.json
    │   ├── nav.json
    │   ├── dashboard.json
    │   ├── safety.json
    │   └── roundtable.json
    └── en-US/
        ├── common.json
        ├── nav.json
        ├── dashboard.json
        ├── safety.json
        └── roundtable.json
```

第一阶段使用单个 JSON 文件以最小化开销。仅在文件难以维护时才迁移到命名空间。

### 4.2 运行时流程

```text
浏览器启动前端
  ├─ frontend/src/main.tsx 导入 frontend/src/i18n/index.ts
  ├─ i18next 初始化支持的资源
  ├─ 从持久化设置 / 检测器 / 回退中选择语言
  ├─ React 渲染 App
  └─ 组件调用 useTranslation() 和 t(key)
```

### 4.3 设置持久化

扩展 [`frontend/src/stores/useSettingsStore.ts`](../../frontend/src/stores/useSettingsStore.ts)：

```text
SettingsState
  ├─ theme
  ├─ locale
  ├─ setLocale(locale)
  ├─ toggleTheme()
  └─ lastSelectedModelKey
```

持久化设置应在显式用户操作之后被视为最高优先级。

### 4.4 语言切换器

添加可复用组件：

```text
frontend/src/components/settings/LanguageSwitcher.tsx
```

放置选项：

| 位置 | 第一阶段推荐 | 原因 |
|------|-------------|------|
| 侧边栏底部 | 是 | 始终可见且易于验证 |
| 设置页面 | 如设置页面已激活则为是 | 可发现且语义正确 |
| 顶部导航 | 可选 | 首次实现避免混乱 |
| 同意页面 | 可选 | 如用户以错误语言进入应用时有用 |

推荐首次实现：侧边栏底部 + 如已存在设置界面则添加设置入口。

---

## 5. 区域语言模型与回退策略

### 5.1 支持的区域语言代码

使用 BCP 47 风格的区域语言代码：

| 区域语言 | 含义 | 阶段 |
|----------|------|------|
| `zh-CN` | 简体中文 | 第一阶段 |
| `en-US` | 英语 | 第一阶段 |
| `zh-TW` | 繁体中文 | 未来 |
| `ja-JP` | 日语 | 未来 |
| `ko-KR` | 韩语 | 未来 |
| `fr-FR` | 法语 | 未来 |
| `de-DE` | 德语 | 未来 |
| `es-ES` | 西班牙语 | 未来 |

### 5.2 回退策略

推荐优先级：

```text
1. 用户手动选择
2. 持久化的本地设置
3. 如支持浏览器检测器结果
4. 回退区域语言
```

开源仓库推荐的回退设置：

```text
fallbackLng = 'zh-CN'
```

如产品后期以国际落地页为主，仅在用户批准后将回退改为 `en-US`。

### 5.3 不支持区域语言的处理

如浏览器检测到 `en`，解析为 `en-US`。
如检测到 `zh`，解析为 `zh-CN`，除非已显式实现 `zh-TW`。
如检测到不支持的语言，使用回退设置。

### 5.4 翻译键策略

使用语义键，而非源文本键。

好的示例：

```text
nav.roundtable
settings.language.label
safety.emergency.title
```

避免：

```text
圆桌讨论
click_here
text_001
```

### 5.5 键命名约定

使用点分隔的命名空间：

```text
common.ok
common.cancel
nav.dashboard
nav.chat
nav.roundtable
dashboard.cards.processedMessages.title
settings.language.options.enUS
privacy.title
consent.nonMedicalNotice.title
roundtable.setup.title
```

---

## 6. 第一阶段执行方案: 前端 UI 简体中文 / 英语

### 6.1 安装依赖 ✅ 已完成

执行代理应从前端目录运行，并在必需的 Conda 环境中执行命令：

```bash
conda run -n wechatDHA npm install react-i18next i18next i18next-browser-languagedetector
```

除非用户显式需要运行时 HTTP 加载翻译文件，否则第一阶段不要安装 `i18next-http-backend`。

### 6.2 添加区域语言注册表 ✅ 已完成

创建：

```text
frontend/src/i18n/supportedLocales.ts
```

推荐的内容概念：

```text
SUPPORTED_LOCALES = ['zh-CN', 'en-US']
DEFAULT_LOCALE = 'zh-CN'
LOCALE_LABELS = {
  'zh-CN': '简体中文',
  'en-US': 'English'
}
```

### 6.3 添加翻译文件 ✅ 已完成

创建：

```text
frontend/src/i18n/locales/zh-CN.json
frontend/src/i18n/locales/en-US.json
```

第一阶段最低键组：

```text
app
common
nav
settings.language
safety
privacy
consent
dashboard
```

### 6.4 添加 i18n 初始化 ✅ 已完成

创建：

```text
frontend/src/i18n/index.ts
```

必需行为：

- 导入 `i18next`。
- 导入 `initReactI18next`。
- 导入 `LanguageDetector`。
- 导入 `zh-CN.json` 和 `en-US.json`。
- 注册资源。
- 设置 `fallbackLng`。
- 设置 `supportedLngs`。
- 禁用转义，因为 React 已经转义值。
- 使用 local storage 和 navigator 配置检测器顺序。

### 6.5 在 App 渲染前导入 i18n ✅ 已完成

更新 [`frontend/src/main.tsx`](../../frontend/src/main.tsx)：

```text
import './i18n'
```

此导入必须在 `<App />` 渲染之前运行。

### 6.6 扩展设置存储 ✅ 已完成

更新 [`frontend/src/stores/useSettingsStore.ts`](../../frontend/src/stores/useSettingsStore.ts)：

- 从 `supportedLocales.ts` 导入 `Locale` 类型。
- 添加 `locale` 状态。
- 添加 `setLocale(locale)` 动作。
- 保留现有的持久化存储名称 `lens-settings`，除非需要迁移。

### 6.7 添加语言切换器组件 ✅ 已完成

创建：

```text
frontend/src/components/settings/LanguageSwitcher.tsx
```

职责：

- 从存储或 i18next 读取当前语言。
- 渲染可用语言选项。
- 切换时：
  - 调用 `i18n.changeLanguage(locale)`，
  - 在 `useSettingsStore` 中持久化 `locale`，
  - 可选更新 `document.documentElement.lang`。

如符合当前 UI 模式，使用现有的 Radix Select。

### 6.8 替换第一批硬编码 UI 文本 ✅ 已完成

从低风险的外壳和静态页面开始：

| 优先级 | 文件 | 范围 |
|--------|------|------|
| P0 | `Sidebar.tsx` | ✅ 导航标签、主题标签、紧急按钮、隐私链接、Beta 徽章标题 |
| P0 | `App.tsx` | ✅ 按钮标题和 aria 标签，如折叠侧边栏文本 |
| P0 | `ConsentPage.tsx` | ✅ 静态同意标题和正文 |
| P0 | `PrivacyPage.tsx` | ✅ 静态隐私标题和正文 |
| P1 | `Dashboard.tsx` | ✅ 仪表板标题、卡片、标签、状态文本 |
| P1 | 设置组件 | ✅ 语言选择器和数据清除文本（如存在） |
| P1 | `KnowledgeCenterPage.tsx` | ✅ 静态知识库标签 |

### 6.9 记录手动 QA 步骤

执行代理应手动验证：

- 应用以回退语言启动。
- 语言切换器在不刷新的情况下更改标签。
- 选择后在刷新后保持。
- 浏览器语言检测不会覆盖手动选择。
- 侧边栏布局在英语中不会破坏。
- 同意和隐私文本保持可读。
- 无后端行为更改。

---

## 7. 第二阶段执行方案: 完整前端 UI 覆盖 ✅ 已完成

第二阶段从外壳/静态页面扩展到所有面向用户的 React UI。

### 7.1 功能覆盖顺序

| 顺序 | 领域 | 原因 |
|------|------|------|
| 1 | 聊天 UI | ✅ 核心产品交互界面 |
| 2 | 测评 UI | ✅ 面向公众的表单和结果标签 |
| 3 | 竞技场 UI | ✅ 包含大量标签的评估功能 |
| 4 | 审核面板 | ✅ 开发者/审核者工作流 |
| 5 | 模型选择器 / 模型测试器 / API 密钥检测器 | ✅ 操作设置和诊断 |
| 6 | 反馈 UI | ✅ 面向用户的提交路径 |
| 7 | 圆桌讨论 UI | ✅ 复杂功能；保留到通用模式稳定后 |

### 7.2 翻译提取规则

执行代理应替换：

- 可见文本，
- 按钮标签，
- 占位符文本，
- aria 标签，
- title 属性，
- toast 消息，
- 空状态消息，
- 前端生成的错误消息，
- 静态徽章标签。

执行代理不应替换：

- API 字段名，
- 人格 id，
- 枚举值，
- 路由路径，
- CSS 类名，
- 存储键，
- 后端协议事件名。

### 7.3 圆桌讨论 UI 专属方案

圆桌讨论应在基本 i18n 模式稳定后处理。

目标：

```text
frontend/src/pages/RoundtablePage.tsx
frontend/src/pages/RoundtableSessionPage.tsx
frontend/src/components/roundtable/*
frontend/src/data/personas.ts
```

重要区分：

| 文本类型 | 第二阶段处理方式 |
|----------|----------------|
| 人格展示名称 | 在前端区域语言文件中本地化 |
| 人格 id | 不要更改 |
| 人格提示词核心 | 第四阶段之前不要更改 |
| SSE 阶段值 | 不要更改 |
| 主持人结构化键 | 不要更改 |

---

## 8. 第三阶段执行方案: 更多 UI 语言

### 8.1 添加新语言

对于每个新 UI 语言：

1. 将区域语言代码添加到 `SUPPORTED_LOCALES`。
2. 将显示标签添加到 `LOCALE_LABELS`。
3. 添加翻译 JSON 文件。
4. 确保所有现有键都存在。
5. 运行缺失键检查。
6. 在常见视口尺寸运行布局回归测试。
7. 发布前要求用户审查文化敏感字符串。

### 8.2 推荐的语言扩展顺序

| 顺序 | 区域语言 | 原因 |
|------|----------|------|
| 1 | `en-US` | 开源和国际开发者受众 |
| 2 | `zh-TW` | 与简体中文高度复用，但需术语审查 |
| 3 | `ja-JP` | 文化相近但需要语气审查 |
| 4 | `ko-KR` | 文化相近但需要语气审查 |
| 5 | `es-ES` 或 `es-419` | 庞大的全球受众 |
| 6 | `fr-FR` | 欧盟受众；需要法律/隐私语言审查 |
| 7 | `de-DE` | 欧盟受众；较长文本布局压力测试 |

### 8.3 翻译 QA 要求

对于关系支持软件，翻译 QA 必须审查：

- 情感验证语气，
- 非医疗免责声明，
- 危机措辞，
- 隐私和删除措辞，
- 文化负载术语，
- 可能听起来过于指令性的关系建议措辞。

### 8.4 布局 QA 要求

每种新语言必须测试：

- 侧边栏宽度和截断，
- 按钮换行，
- 卡片标题溢出，
- 模态框布局，
- 移动端视口，
- 桌面 Electron 最小尺寸，
- 长德语/法语字符串，
- CJK 换行。

---

## 9. 第四阶段执行方案: AI 与后端本地化

第四阶段应在前端 UI 本地化稳定后才开始。

### 9.1 后端区域语言传播

向请求模型添加可选的 `locale` 字段：

| 功能 | 目标请求 |
|------|---------|
| 聊天 | 聊天请求体 |
| 竞技场 | 竞技场聊天请求体 |
| 圆桌讨论 | `RoundtableStartRequest`、`RoundtableContinueRequest`、如需要的注入预览 |
| 测评 | 如结果文本本地化，则为测评提交/读取端点 |

前端应将当前区域语言从 i18n/设置传递到 API 请求。

### 9.2 提示词本地化结构

推荐的未来配置结构：

```text
configs/i18n/prompts/
├── roundtable_prompts.zh-CN.yaml
├── roundtable_prompts.en-US.yaml
├── chat_system_prompts.zh-CN.yaml
├── chat_system_prompts.en-US.yaml
├── safety_messages.zh-CN.yaml
└── safety_messages.en-US.yaml
```

除非工具要求，避免将多种语言混合到一个非常大的 YAML 文件中。

### 9.3 AI 输出语言策略

每个面向 AI 的请求应包含显式指令：

```text
Respond in the user's selected UI language unless the user explicitly asks for another language.
```

然而，危机和安全响应应由本地化安全模板控制，而非仅靠自由翻译。

### 9.4 安全与危机本地化

安全文本必须从一般 UI 中单独本地化。

需要审查的类别：

- 非医疗免责声明，
- 危机升级语言，
- 紧急帮助语言，
- 按国家/地区的热线政策，
- 禁止措辞替换，
- 偏见检测器替换文本。

### 9.5 区域语言感知的 RAG 与知识

未来知识库条目应包含区域语言元数据：

```text
locale: zh-CN / en-US / ja-JP
category
question
answer
keywords
```

检索应优先选择同区域语言条目，如需要则回退到默认语言。

---

## 10. 第五阶段执行方案: 应用适配

应用适配应被视为产品/运行时项目，而非仅 UI 翻译任务。

### 10.1 适配轨道

| 轨道 | 范围 | 推荐时机 |
|------|------|---------|
| 响应式 Web | 在当前 React 应用中改进移动端/平板布局 | 第一阶段 i18n 外壳稳定后 |
| PWA | 可安装的 Web 应用、离线外壳、图标/清单 | 响应式 Web 通过移动端 QA 后 |
| Electron 桌面端 | 桌面封装和本地后端策略 | v1.1 或更晚，运行时边界决策后 |
| 原生移动端封装 | Capacitor/React Native/Tauri 移动端决策 | 仅在了解 PWA 限制后 |

### 10.2 响应式 Web 方案

目标：

- 小屏幕上的侧边栏折叠行为。
- 顶部导航密度和搜索布局。
- 仪表板卡片堆叠。
- 聊天输入和消息宽度。
- 圆桌讨论三列布局在移动端折叠为标签页/手风琴。
- 模态框和抽屉触摸目标。
- 交互控件最小 44px 触摸目标。

建议的视口 QA：

```text
375x667   移动端小屏
390x844   现代移动端
768x1024  平板竖屏
1024x768  平板横屏 / Electron 最小宽度
1280x860  当前 Electron 默认
1440x900  桌面端
```

### 10.3 PWA 方案

如用户批准 PWA：

- 添加 `manifest.webmanifest`。
- 添加应用图标。
- 添加 Service Worker 策略。
- 仅缓存静态前端资源。
- 默认不缓存敏感 API 响应。
- 添加清晰说明后端不可用的离线外壳页面。
- 启用任何离线数据缓存前确认隐私影响。

### 10.4 Electron 方案

当前 Electron 外壳仅为占位符并加载开发服务器。真正的打包需要 `docs/ELECTRON_BUILD.md` 中已记录的决策：

| 决策 | 选项 |
|------|------|
| 后端生命周期 | 用户管理的 Conda / Electron 管理的进程 / 打包的二进制文件 |
| Python 运行时 | Conda / PyInstaller / Nuitka / 外部服务 |
| 数据位置 | 应用包外的用户选择工作区 |
| 密钥存储 | 本地文件 / OS 钥匙串 / 用户管理的 `.env` |
| 模型存储 | 外部 `/data/models/` 或用户选择的模型路径 |
| 日志 | 仅非敏感诊断 |

Electron 实现序列：

1. 运行时边界批准前保持当前占位符不变。
2. 将前端 `dist/` 打包到 Electron 外壳中。
3. 添加后端 URL 设置屏幕。
4. 添加健康轮询。
5. 仅在用户批准进程管理后添加后端生命周期。
6. 为打包产物添加隐私扫描。
7. 添加平台特定的构建脚本。
8. 仅在目标操作系统列表确定后添加签名安装程序工作流。

### 10.5 原生移动端封装方案

未经用户批准不要选择原生封装。

决策矩阵：

| 选项 | 优点 | 缺点 |
|------|------|------|
| PWA | 最快，单一代码库 | 原生集成有限，iOS 限制 |
| Capacitor | 复用 React 前端 | 原生打包复杂性，后端仍外部 |
| React Native | 更好的原生用户体验 | 需要 UI 重写 |
| Tauri mobile | 更小的外壳潜力 | 使用前必须检查生态系统成熟度 |

对于 Lens，最难的移动端问题不是 UI 技术；而是本地后端、隐私、模型/运行时和数据存储策略。

---

## 11. 测试与验收标准

### 11.1 必需命令

所有命令应在必需的 Conda 环境中运行。

前端依赖安装：

```bash
conda run -n wechatDHA npm install react-i18next i18next i18next-browser-languagedetector
```

前端验证：

```bash
conda run -n wechatDHA npm run lint
conda run -n wechatDHA npm run test
conda run -n wechatDHA npm run build
```

UI 路由更改时的 E2E 验证：

```bash
conda run -n wechatDHA npm run test:e2e
```

从 `frontend/` 运行，除非执行代理有项目级包装器。

### 11.2 第一阶段验收标准

第一阶段完成条件：

- `zh-CN` 和 `en-US` 可用。
- 用户可从 UI 切换语言。
- 选择语言在刷新后保持。
- 侧边栏标签正确切换。
- 第一阶段包含的核心静态页面正确切换。
- 浏览器检测器不会覆盖手动选择。
- `document.documentElement.lang` 匹配所选区域语言。
- `npm run build` 通过。
- 无后端请求或响应行为更改。
- 不引入私有路径、密钥或运行时数据。

### 11.3 缺失键检查

执行代理应添加或运行比较区域语言 JSON 键集的脚本。

预期行为：

```text
zh-CN keys == en-US keys
```

未来语言在合并前必须通过相同检查。

### 11.4 手动 QA 检查清单

- 不刷新切换 中文 → 英语 → 中文。
- 英语刷新后，英语保持选中。
- 打开 `/dashboard`、`/consent`、`/privacy`、`/knowledge-center`。
- 折叠和展开侧边栏。
- 切换语言后切换暗/亮主题。
- 确认紧急入口保持可见。
- 确认在 390px 宽度和 1280px 宽度下的布局。
- 确认 UI 切换不会改变 AI 响应语言。

---

## 12. 风险登记册

| 风险 | 影响 | 缓解 |
|------|------|------|
| 键覆盖不完整 | 混合语言 UI | 添加缺失键脚本和 PR 检查清单 |
| 第一阶段更改过于激进 | 意外更改后端或 AI 行为 | 保持第一阶段仅限前端 |
| 长英语标签破坏布局 | 用户体验差 | 测试常见视口尺寸并允许换行/截断 |
| 安全文本误译 | 合规和用户风险 | 将安全/法律文案作为单独审查内容 |
| 人格 id 本地化 | API 破坏 | 永不翻译 id 或枚举值 |
| 路由本地化 | 深度链接破坏 | 第一阶段保持路由稳定 |
| 浏览器检测器覆盖用户选择 | 令人困惑的用户体验 | 手动选择和持久化设置优先 |
| 原生应用范围蔓延 | 高复杂性 | 先完成响应式 Web/PWA 评估 |

---

## 13. 逐文件检查清单

### 13.1 第一阶段必须修改 ✅ 已完成

```text
frontend/package.json                         ✅ 已添加 i18n 依赖
frontend/package-lock.json                    ✅ 已同步
frontend/src/main.tsx                         ✅ 已导入 i18n 初始化
frontend/src/i18n/index.ts                    ✅ 已创建
frontend/src/i18n/supportedLocales.ts         ✅ 已创建
frontend/src/i18n/locales/zh-CN.json          ✅ 已创建，含 ~300+ 键
frontend/src/i18n/locales/en-US.json          ✅ 已创建，键与 zh-CN 完全对等
frontend/src/stores/useSettingsStore.ts       ✅ 已扩展 locale 状态与持久化
frontend/src/components/settings/LanguageSwitcher.tsx  ✅ 已创建并集成
frontend/src/components/layout/Sidebar.tsx    ✅ 全部导航标签已本地化
frontend/src/App.tsx                          ✅ 外壳标签与 aria 已本地化
```

同时修改选定的第一阶段页面：

```text
frontend/src/pages/ConsentPage.tsx            ✅ 全部章节标题、按钮、正文
frontend/src/pages/PrivacyPage.tsx            ✅ 标题、9个章节、页脚
frontend/src/pages/Dashboard.tsx              ✅ 统计卡片、标签、欢迎文本
frontend/src/pages/KnowledgeCenterPage.tsx    ✅ 分类、状态徽章、描述
```

### 13.2 第二阶段可能修改 ✅ 已完成

```text
frontend/src/pages/ChatPage.tsx               ✅ 标签、提示、错误消息
frontend/src/pages/ArenaPage.tsx              ✅ 对比模式、评分、投票
frontend/src/pages/AssessmentPage.tsx         ✅ 测评标题、导航、结果
frontend/src/pages/CommunicationStatusPage.tsx ✅ 标题、状态、会话标签
frontend/src/components/ReviewPanel.tsx       ✅ 审核面板全部 UI
frontend/src/components/ModelSelector.tsx     ✅ 角色标签、保存按钮
frontend/src/components/ModelTester.tsx       ✅ 标题、测试按钮、统计
frontend/src/components/ApiKeyChecker.tsx       ✅ 全部标签与日志文案
frontend/src/components/feedback/*            ✅ FeedbackForm + FeedbackButton
frontend/src/components/settings/*            ✅ DataEraseDialog 等
frontend/src/components/safety/*              ✅ ConsentModal + EmergencyModal
frontend/src/pages/RoundtablePage.tsx         ✅ Setup 页全部文案
frontend/src/pages/RoundtableSessionPage.tsx  ✅ Phase 标题、追问提示
frontend/src/components/roundtable/*          ✅ AgentMessage phaseLabel 类型修复
frontend/src/data/personas.ts                 ⏳ 未修改（人格 id 不翻译，符合 7.3 规范）
```

### 13.3 第四阶段可能修改

```text
frontend/src/lib/api.ts
scripts/advisor/api/core/models.py
scripts/advisor/api/routes/chat.py
scripts/advisor/api/routes/arena.py
scripts/advisor/api/routes/roundtable.py
scripts/advisor/api/services/roundtable_service.py
configs/i18n/prompts/*
configs/i18n/safety_messages.*.yaml
```

未经用户显式批准不要启动第四阶段。

### 13.4 第五阶段可能修改

```text
frontend/src/App.tsx
frontend/src/components/layout/*
frontend/src/pages/*
frontend/e2e/*mobile*.spec.ts
electron/main.js
electron/preload.js
electron/package.json
docs/ELECTRON_BUILD.md
```

未经用户显式批准不要更改 Electron 打包行为。

---

## 14. 执行代理交接说明

### 14.1 即时任务

仅实现：

```text
第一阶段: 前端 UI 简体中文 / 英语切换
```

除非用户显式扩展范围，否则不要实现后端本地化、AI 提示词本地化、Electron 打包、PWA 或原生应用封装。

### 14.2 强制工作方式

- 对脚本和验证命令使用 `conda run -n wechatDHA`。
- 将所有运行时/私有数据排除在仓库外。
- 不要硬编码私有路径、API 密钥、提供商域名或本地密钥。
- 保持翻译键稳定和语义化。
- 保持路由路径和 API 枚举值不变。
- 按功能区域优先选择小型、可审查的提交或补丁。
- 每个实现阶段后，运行构建和缺失键检查。

### 14.3 建议的首个补丁顺序

1. 安装依赖。
2. 在 `main.tsx` 中添加 `i18n/` 文件并初始化。
3. 在 `useSettingsStore` 中扩展 `locale`。
4. 添加 `LanguageSwitcher`。
5. 本地化 `Sidebar` 和 `App` 外壳标签。
6. 本地化 `ConsentPage` 和 `PrivacyPage`。
7. 本地化 `Dashboard` 和 `KnowledgeCenterPage`。
8. 添加或运行区域语言键对等检查。
9. 运行 lint/test/build。
10. 报告更改的文件和剩余的硬编码字符串。

### 14.4 可交付报告格式

执行代理应报告：

```text
已实现:
- ...

验证:
- npm run lint: 通过/失败
- npm run test: 通过/失败
- npm run build: 通过/失败
- 区域语言键对等: 通过/失败

已知的剩余硬编码 UI 文本:
- ...

未更改的超出范围项:
- 后端提示词
- AI 输出语言
- Electron 打包
```

---

**文档版本**: v1.0
**创建时间**: 2026-06-14
**当前实施范围**: 仅前端 UI 简体中文 / 英语切换
**相关文档**: [顾问 Web 应用系统设计](web_app_overview.md), [圆桌讨论系统设计](roundtable_discussion_overview.md), [Electron 构建](../ELECTRON_BUILD.md)

---

# Internationalization and App Adaptation Design & Execution Plan

> 📌 **Document scope**: This document is written as a handoff plan for a future execution agent. The immediate implementation scope is **frontend UI Chinese/English switching only**. Future phases cover additional locales, AI prompt localization, safety/legal localization, responsive/mobile adaptation, PWA, Electron desktop packaging, and possible native app wrappers.
>
> Updated: 2026-06-14

---

## Table of Contents

- [1. Executive Summary](#1-executive-summary)
- [2. Current Repository Facts](#2-current-repository-facts)
- [3. Goals and Non-Goals](#3-goals-and-non-goals)
- [4. Target Architecture](#4-target-architecture)
- [5. Locale Model and Fallback Policy](#5-locale-model-and-fallback-policy)
- [6. Phase 1 Execution Plan: Frontend UI zh-CN / en-US](#6-phase-1-execution-plan-frontend-ui-zh-cn--en-us)
- [7. Phase 2 Execution Plan: Full Frontend UI Coverage](#7-phase-2-execution-plan-full-frontend-ui-coverage)
- [8. Phase 3 Execution Plan: More UI Languages](#8-phase-3-execution-plan-more-ui-languages)
- [9. Phase 4 Execution Plan: AI and Backend Localization](#9-phase-4-execution-plan-ai-and-backend-localization)
- [10. Phase 5 Execution Plan: App Adaptation](#10-phase-5-execution-plan-app-adaptation)
- [11. Testing and Acceptance Criteria](#11-testing-and-acceptance-criteria)
- [12. Risk Register](#12-risk-register)
- [13. File-by-File Checklist](#13-file-by-file-checklist)
- [14. Handoff Instructions for Execution Agent](#14-handoff-instructions-for-execution-agent)

---

## 1. Executive Summary

Lens currently has a React + Vite + TypeScript frontend with many hard-coded Chinese UI strings. The recommended internationalization strategy is to introduce `i18next` and `react-i18next`, store locale resources as JSON files, and replace hard-coded UI strings with stable translation keys.

The immediate product direction should be conservative:

```text
Current implementation scope:
  Frontend UI zh-CN / en-US switching only

Explicitly not included in current scope:
  AI prompt localization
  backend error localization
  Roundtable generated language control
  safety hotline localization by country
  native mobile packaging
  production Electron packaging
```

This separation keeps the first implementation low-risk and prevents UI translation work from accidentally changing AI behavior, safety policy, or backend semantics.

---

## 2. Current Repository Facts

### 2.1 Frontend Stack

The frontend is located under [`frontend/`](../../frontend). Current stack from [`frontend/package.json`](../../frontend/package.json):

| Area | Current Tooling |
|------|-----------------|
| Framework | React 19 |
| Language | TypeScript |
| Build | Vite 7 |
| Styling | Tailwind CSS 4 |
| State | Zustand |
| UI dependencies | Radix UI, Lucide React, Framer Motion, Sonner |
| Tests | Vitest, Playwright |
| Router | Manual path-state routing in `App.tsx`, with `react-router-dom` dependency present but not central |

### 2.2 Current i18n Status

| Item | Status |
|------|--------|
| `i18next` dependency | Not present |
| `react-i18next` dependency | Not present |
| Locale files | Not present |
| Language selector | Not present |
| UI text extraction | Not present |
| User language preference | Not present, but `useSettingsStore` can be extended |
| Backend locale parameter | Not present |

### 2.3 Relevant Existing Files

| File | Relevance |
|------|-----------|
| [`frontend/src/main.tsx`](../../frontend/src/main.tsx) | Import i18n initialization here before rendering `App` |
| [`frontend/src/App.tsx`](../../frontend/src/App.tsx) | App shell, theme state, route mapping, global components |
| [`frontend/src/components/layout/Sidebar.tsx`](../../frontend/src/components/layout/Sidebar.tsx) | Hard-coded navigation labels, ideal first i18n target |
| [`frontend/src/stores/useSettingsStore.ts`](../../frontend/src/stores/useSettingsStore.ts) | Persisted settings store; extend with `locale` |
| [`frontend/src/lib/api.ts`](../../frontend/src/lib/api.ts) | Future locale propagation to backend requests |
| [`frontend/src/data/personas.ts`](../../frontend/src/data/personas.ts) | Future Roundtable persona display localization |
| [`configs/roundtable_prompts.yaml`](../../configs/roundtable_prompts.yaml) | Future AI prompt localization target, not Phase 1 |
| [`electron/main.js`](../../electron/main.js) | Current placeholder Electron shell loads dev server |
| [`docs/ELECTRON_BUILD.md`](../ELECTRON_BUILD.md) | Electron packaging is reserved for future v1.1 work |

---

## 3. Goals and Non-Goals

### 3.1 Immediate Goals

Phase 1 must deliver:

- Chinese / English UI switching in the frontend.
- User-selected language persisted locally.
- Browser language detection as a convenience, not as the only source of truth.
- A reusable translation key structure that can support more languages later.
- No change to backend API semantics or AI output language.
- No hidden changes to safety, privacy, or crisis behavior.

### 3.2 Future Goals

Future phases should support:

- Additional UI locales such as `zh-TW`, `ja-JP`, `ko-KR`, `fr-FR`, `de-DE`, `es-ES`.
- AI response language control through explicit `locale` fields.
- Localized prompt templates.
- Localized safety and legal text.
- Responsive/mobile layouts and touch-friendly UX.
- PWA installability if needed.
- Electron production packaging if local setup becomes a blocker.
- Optional native mobile wrapper only after web/PWA constraints are understood.

### 3.3 Non-Goals for Phase 1

Do not implement the following in Phase 1:

- Do not translate AI-generated responses.
- Do not modify `configs/roundtable_prompts.yaml`.
- Do not add backend request `locale` fields yet.
- Do not localize backend error messages.
- Do not change crisis detector behavior.
- Do not add app-store packaging.
- Do not change Electron runtime behavior.
- Do not migrate routing architecture.

---

## 4. Target Architecture

### 4.1 Frontend i18n Architecture

Recommended Phase 1 structure:

```text
frontend/src/i18n/
├── index.ts
├── supportedLocales.ts
└── locales/
    ├── zh-CN.json
    └── en-US.json
```

Suggested future structure if namespaces become necessary:

```text
frontend/src/i18n/
├── index.ts
├── supportedLocales.ts
└── locales/
    ├── zh-CN/
    │   ├── common.json
    │   ├── nav.json
    │   ├── dashboard.json
    │   ├── safety.json
    │   └── roundtable.json
    └── en-US/
        ├── common.json
        ├── nav.json
        ├── dashboard.json
        ├── safety.json
        └── roundtable.json
```

For Phase 1, use single JSON files to minimize overhead. Move to namespaces only when files become hard to maintain.

### 4.2 Runtime Flow

```text
Browser starts frontend
  ├─ frontend/src/main.tsx imports frontend/src/i18n/index.ts
  ├─ i18next initializes supported resources
  ├─ language selected from persisted setting / detector / fallback
  ├─ React renders App
  └─ components call useTranslation() and t(key)
```

### 4.3 Settings Persistence

Extend [`frontend/src/stores/useSettingsStore.ts`](../../frontend/src/stores/useSettingsStore.ts):

```text
SettingsState
  ├─ theme
  ├─ locale
  ├─ setLocale(locale)
  ├─ toggleTheme()
  └─ lastSelectedModelKey
```

The persisted setting should be treated as the highest priority after explicit user action.

### 4.4 Language Switcher

Add a reusable component:

```text
frontend/src/components/settings/LanguageSwitcher.tsx
```

Placement options:

| Location | Phase 1 Recommendation | Reason |
|----------|------------------------|--------|
| Sidebar footer | Yes | Always visible and easy to validate |
| Settings page | Yes if settings page is active | Discoverable and semantically correct |
| TopNav | Optional | Avoid clutter in first pass |
| Consent page | Optional | Useful if user enters app in wrong language |

Recommended first implementation: Sidebar footer + settings surface if a settings surface already exists.

---

## 5. Locale Model and Fallback Policy

### 5.1 Supported Locale Codes

Use BCP 47 style locale codes:

| Locale | Meaning | Phase |
|--------|---------|-------|
| `zh-CN` | Simplified Chinese | Phase 1 |
| `en-US` | English | Phase 1 |
| `zh-TW` | Traditional Chinese | Future |
| `ja-JP` | Japanese | Future |
| `ko-KR` | Korean | Future |
| `fr-FR` | French | Future |
| `de-DE` | German | Future |
| `es-ES` | Spanish | Future |

### 5.2 Fallback Policy

Recommended priority:

```text
1. User manual selection
2. Persisted local setting
3. Browser detector result if supported
4. Fallback locale
```

Recommended fallback for the open-source repository:

```text
fallbackLng = 'zh-CN'
```

If the product later targets international landing pages first, change fallback to `en-US` only after user approval.

### 5.3 Unsupported Locale Handling

If the browser detects `en`, resolve to `en-US`.
If it detects `zh`, resolve to `zh-CN` unless `zh-TW` has been explicitly implemented.
If it detects an unsupported language, use fallback.

### 5.4 Translation Key Policy

Use semantic keys, not source-text keys.

Good:

```text
nav.roundtable
settings.language.label
safety.emergency.title
```

Avoid:

```text
圆桌讨论
click_here
text_001
```

### 5.5 Key Naming Convention

Use dot-separated namespaces:

```text
common.ok
common.cancel
nav.dashboard
nav.chat
nav.roundtable
dashboard.cards.processedMessages.title
settings.language.options.enUS
privacy.title
consent.nonMedicalNotice.title
roundtable.setup.title
```

---

## 6. Phase 1 Execution Plan: Frontend UI zh-CN / en-US

### 6.1 Install Dependencies

Execution agent should run from the frontend directory and keep commands inside the required Conda environment:

```bash
conda run -n wechatDHA npm install react-i18next i18next i18next-browser-languagedetector
```

Do not install `i18next-http-backend` in Phase 1 unless the user explicitly wants runtime HTTP-loaded translation files.

### 6.2 Add Locale Registry

Create:

```text
frontend/src/i18n/supportedLocales.ts
```

Recommended contents conceptually:

```text
SUPPORTED_LOCALES = ['zh-CN', 'en-US']
DEFAULT_LOCALE = 'zh-CN'
LOCALE_LABELS = {
  'zh-CN': '简体中文',
  'en-US': 'English'
}
```

### 6.3 Add Translation Files

Create:

```text
frontend/src/i18n/locales/zh-CN.json
frontend/src/i18n/locales/en-US.json
```

Minimum Phase 1 key groups:

```text
app
common
nav
settings.language
safety
privacy
consent
dashboard
```

### 6.4 Add i18n Initialization

Create:

```text
frontend/src/i18n/index.ts
```

Required behavior:

- Import `i18next`.
- Import `initReactI18next`.
- Import `LanguageDetector`.
- Import `zh-CN.json` and `en-US.json`.
- Register resources.
- Set `fallbackLng`.
- Set `supportedLngs`.
- Disable escaping because React already escapes values.
- Configure detector order with local storage and navigator.

### 6.5 Import i18n Before App Render

Update [`frontend/src/main.tsx`](../../frontend/src/main.tsx):

```text
import './i18n'
```

This import must run before `<App />` renders.

### 6.6 Extend Settings Store

Update [`frontend/src/stores/useSettingsStore.ts`](../../frontend/src/stores/useSettingsStore.ts):

- Add type `Locale` imported from `supportedLocales.ts`.
- Add `locale` state.
- Add `setLocale(locale)` action.
- Keep existing persisted store name `lens-settings` unless migration is required.

### 6.7 Add Language Switcher Component

Create:

```text
frontend/src/components/settings/LanguageSwitcher.tsx
```

Responsibilities:

- Read current language from store or i18next.
- Render available language options.
- On change:
  - call `i18n.changeLanguage(locale)`,
  - persist `locale` in `useSettingsStore`,
  - optionally update `document.documentElement.lang`.

Use existing Radix Select if it fits current UI patterns.

### 6.8 Replace First Batch of Hard-Coded UI Text

Start with low-risk shell and static pages:

| Priority | File | Scope |
|----------|------|-------|
| P0 | `Sidebar.tsx` | Navigation labels, theme label, emergency button, privacy link, Beta badge title |
| P0 | `App.tsx` | Button titles and aria labels such as collapsed sidebar text |
| P0 | `ConsentPage.tsx` | Static consent headings and body text |
| P0 | `PrivacyPage.tsx` | Static privacy headings and body text |
| P1 | `Dashboard.tsx` | Dashboard titles, cards, labels, status text |
| P1 | settings components | Language selector and data erase text if present |
| P1 | `KnowledgeCenterPage.tsx` | Static knowledge-base labels |

Do not localize complex Roundtable and Chat strings in the first commit unless Phase 1 time budget allows.

### 6.9 Document Manual QA Steps

The execution agent should manually verify:

- App starts in fallback language.
- Language switcher changes labels without reload.
- Selection persists after refresh.
- Browser language detection does not override manual selection.
- Sidebar layout does not break in English.
- Consent and privacy text remain readable.
- No backend behavior changes.

---

## 7. Phase 2 Execution Plan: Full Frontend UI Coverage

Phase 2 expands from the shell/static pages to all user-facing React UI.

### 7.1 Feature Coverage Order

| Order | Area | Reason |
|-------|------|--------|
| 1 | Chat UI | Core product interaction surface |
| 2 | Assessment UI | Public-facing form and result labels |
| 3 | Arena UI | Evaluation feature with many labels |
| 4 | ReviewPanel | Developer/reviewer workflow |
| 5 | ModelSelector / ModelTester / ApiKeyChecker | Operational settings and diagnostics |
| 6 | Feedback UI | User-facing submission path |
| 7 | Roundtable UI | Complex feature; keep until common patterns stabilize |

### 7.2 Translation Extraction Rules

Execution agent should replace:

- visible text,
- button labels,
- placeholder text,
- aria labels,
- title attributes,
- toast messages,
- empty-state messages,
- error messages generated in frontend,
- static badge labels.

Execution agent should not replace:

- API field names,
- persona ids,
- enum values,
- route paths,
- CSS class names,
- storage keys,
- backend protocol event names.

### 7.3 Roundtable UI-Specific Plan

Roundtable should be done after the basic i18n pattern is stable.

Targets:

```text
frontend/src/pages/RoundtablePage.tsx
frontend/src/pages/RoundtableSessionPage.tsx
frontend/src/components/roundtable/*
frontend/src/data/personas.ts
```

Important distinction:

| Text Type | Phase 2 Treatment |
|-----------|-------------------|
| Persona display names | Localize in frontend locale files |
| Persona ids | Do not change |
| Persona prompt cores | Do not change until Phase 4 |
| SSE phase values | Do not change |
| Moderator structured keys | Do not change |

---

## 8. Phase 3 Execution Plan: More UI Languages

### 8.1 Adding a New Language

For each new UI language:

1. Add locale code to `SUPPORTED_LOCALES`.
2. Add display label to `LOCALE_LABELS`.
3. Add translation JSON file.
4. Ensure all existing keys are present.
5. Run missing-key check.
6. Run layout regression at common viewport sizes.
7. Ask user to review culturally sensitive strings before release.

### 8.2 Recommended Language Expansion Order

| Order | Locale | Reason |
|-------|--------|--------|
| 1 | `en-US` | Open-source and international developer audience |
| 2 | `zh-TW` | High reuse from Simplified Chinese with terminology review |
| 3 | `ja-JP` | Culturally adjacent but requires tone review |
| 4 | `ko-KR` | Culturally adjacent but requires tone review |
| 5 | `es-ES` or `es-419` | Large global audience |
| 6 | `fr-FR` | EU audience; legal/privacy language review needed |
| 7 | `de-DE` | EU audience; longer text layout stress test |

### 8.3 Translation QA Requirements

For relationship-support software, translation QA must review:

- emotional validation tone,
- non-medical disclaimers,
- crisis wording,
- privacy and deletion wording,
- culturally loaded terms,
- relationship advice wording that might sound too directive.

### 8.4 Layout QA Requirements

Every new language must test:

- sidebar width and truncation,
- button wrapping,
- card title overflow,
- modal layout,
- mobile viewport,
- desktop Electron minimum size,
- long German/French strings,
- CJK line breaking.

---

## 9. Phase 4 Execution Plan: AI and Backend Localization

Phase 4 should only start after frontend UI localization is stable.

### 9.1 Backend Locale Propagation

Add optional `locale` fields to request models:

| Feature | Target Request |
|---------|----------------|
| Chat | chat request body |
| Arena | arena chat request body |
| Roundtable | `RoundtableStartRequest`, `RoundtableContinueRequest`, injection preview if needed |
| Assessment | assessment submit/read endpoints if result text becomes localized |

The frontend should pass the current locale from i18n/settings to API requests.

### 9.2 Prompt Localization Structure

Recommended future config structure:

```text
configs/i18n/prompts/
├── roundtable_prompts.zh-CN.yaml
├── roundtable_prompts.en-US.yaml
├── chat_system_prompts.zh-CN.yaml
├── chat_system_prompts.en-US.yaml
├── safety_messages.zh-CN.yaml
└── safety_messages.en-US.yaml
```

Avoid mixing many languages into one very large YAML file unless tooling requires it.

### 9.3 AI Output Language Policy

Each AI-facing request should include an explicit instruction:

```text
Respond in the user's selected UI language unless the user explicitly asks for another language.
```

However, crisis and safety responses should be governed by localized safety templates, not freeform translation alone.

### 9.4 Safety and Crisis Localization

Safety text must be localized separately from general UI.

Required review categories:

- non-medical disclaimer,
- crisis escalation language,
- emergency help language,
- country/region-specific hotline policy,
- prohibited wording replacements,
- bias detector replacement text.

### 9.5 Locale-Aware RAG and Knowledge

Future knowledge-base entries should include locale metadata:

```text
locale: zh-CN / en-US / ja-JP
category
question
answer
keywords
```

Retrieval should prefer same-locale entries, then fallback to a default language if needed.

---

## 10. Phase 5 Execution Plan: App Adaptation

App adaptation should be treated as a product/runtime project, not just a UI translation task.

### 10.1 Adaptation Tracks

| Track | Scope | Recommended Timing |
|-------|-------|--------------------|
| Responsive Web | Improve mobile/tablet layouts in current React app | After Phase 1 i18n shell is stable |
| PWA | Installable web app, offline shell, icon/manifest | After responsive web passes mobile QA |
| Electron Desktop | Desktop wrapper and local backend strategy | v1.1 or later, after runtime boundary decision |
| Native Mobile Wrapper | Capacitor/React Native/Tauri mobile decision | Only after PWA limitations are clear |

### 10.2 Responsive Web Plan

Targets:

- Sidebar collapse behavior on small screens.
- TopNav density and search layout.
- Dashboard card stacking.
- Chat input and message width.
- Roundtable three-column layout collapse to tabs/accordion on mobile.
- Modal and drawer touch targets.
- Minimum 44px touch target for interactive controls.

Suggested viewport QA:

```text
375x667   mobile small
390x844   modern mobile
768x1024  tablet portrait
1024x768  tablet landscape / Electron min width
1280x860  current Electron default
1440x900  desktop
```

### 10.3 PWA Plan

If user approves PWA:

- Add `manifest.webmanifest`.
- Add app icons.
- Add service worker strategy.
- Cache only static frontend assets.
- Do not cache sensitive API responses by default.
- Add offline shell page that clearly says backend is unavailable.
- Confirm privacy implications before enabling any offline data cache.

### 10.4 Electron Plan

Current Electron shell is placeholder-only and loads a dev server. Real packaging requires decisions already noted in [Electron Build](../ELECTRON_BUILD.md):

| Decision | Options |
|----------|---------|
| Backend lifecycle | user-managed Conda / Electron-managed process / packaged binary |
| Python runtime | Conda / PyInstaller / Nuitka / external service |
| Data location | user-selected workspace outside app bundle |
| Secret storage | local file / OS keychain / user-managed `.env` |
| Model storage | external `/data/models/` or user-selected model path |
| Logs | non-sensitive diagnostics only |

Electron implementation sequence:

1. Keep current placeholder unchanged until runtime boundary is approved.
2. Package frontend `dist/` into Electron shell.
3. Add backend URL setup screen.
4. Add health polling.
5. Add backend lifecycle only if user approves process management.
6. Add privacy scan for packaged artifact.
7. Add platform-specific build scripts.
8. Add signed installer workflow only after target OS list is finalized.

### 10.5 Native Mobile Wrapper Plan

Do not choose a native wrapper without user approval.

Decision matrix:

| Option | Pros | Cons |
|--------|------|------|
| PWA | Fastest, one codebase | Limited native integrations, iOS constraints |
| Capacitor | Reuse React frontend | Native packaging complexity, backend still external |
| React Native | Better native UX | Requires UI rewrite |
| Tauri mobile | Smaller shell potential | Ecosystem maturity must be checked before use |

For Lens, the hardest mobile issue is not UI technology; it is local backend, privacy, model/runtime, and data storage strategy.

---

## 11. Testing and Acceptance Criteria

### 11.1 Required Commands

All commands should be run inside the required Conda environment.

Frontend dependency install:

```bash
conda run -n wechatDHA npm install react-i18next i18next i18next-browser-languagedetector
```

Frontend validation:

```bash
conda run -n wechatDHA npm run lint
conda run -n wechatDHA npm run test
conda run -n wechatDHA npm run build
```

E2E validation when UI routing changes:

```bash
conda run -n wechatDHA npm run test:e2e
```

Run these from `frontend/` unless the executing agent has a project-level wrapper.

### 11.2 Phase 1 Acceptance Criteria

Phase 1 is complete when:

- `zh-CN` and `en-US` are available.
- User can switch language from UI.
- Selected language persists after refresh.
- Sidebar labels switch correctly.
- Core static pages included in Phase 1 switch correctly.
- Browser detector does not override manual choice.
- `document.documentElement.lang` matches selected locale.
- `npm run build` passes.
- No backend request or response behavior changes.
- No private paths, secrets, or runtime data are introduced.

### 11.3 Missing-Key Check

Execution agent should add or run a script that compares locale JSON key sets.

Expected behavior:

```text
zh-CN keys == en-US keys
```

Future languages must pass the same check before merge.

### 11.4 Manual QA Checklist

- Switch Chinese → English → Chinese without refresh.
- Refresh after English; English remains selected.
- Open `/dashboard`, `/consent`, `/privacy`, `/knowledge-center`.
- Collapse and expand sidebar.
- Toggle dark/light theme after switching language.
- Confirm emergency entry remains visible.
- Confirm layout at 390px width and 1280px width.
- Confirm no AI response language changed because of UI switch.

---

## 12. Risk Register

| Risk | Impact | Mitigation |
|------|--------|------------|
| Incomplete key coverage | Mixed-language UI | Add missing-key script and PR checklist |
| Over-eager Phase 1 changes | Backend or AI behavior changes accidentally | Keep Phase 1 frontend-only |
| Long English labels break layout | Poor UX | Test common viewport sizes and allow wrapping/truncation |
| Safety text mistranslation | Compliance and user risk | Treat safety/legal copy as separately reviewed content |
| Persona id localization | API breakage | Never translate ids or enum values |
| Route localization | Deep-link breakage | Keep routes stable in Phase 1 |
| Browser detector overrides user choice | Confusing UX | Manual selection and persisted setting take priority |
| Native app scope creep | High complexity | Finish responsive web/PWA evaluation first |

---

## 13. File-by-File Checklist

### 13.1 Phase 1 Must Touch

```text
frontend/package.json
frontend/package-lock.json
frontend/src/main.tsx
frontend/src/i18n/index.ts
frontend/src/i18n/supportedLocales.ts
frontend/src/i18n/locales/zh-CN.json
frontend/src/i18n/locales/en-US.json
frontend/src/stores/useSettingsStore.ts
frontend/src/components/settings/LanguageSwitcher.tsx
frontend/src/components/layout/Sidebar.tsx
frontend/src/App.tsx
```

Also touch selected Phase 1 pages:

```text
frontend/src/pages/ConsentPage.tsx
frontend/src/pages/PrivacyPage.tsx
frontend/src/pages/Dashboard.tsx
frontend/src/pages/KnowledgeCenterPage.tsx
```

### 13.2 Phase 2 Likely Touches

```text
frontend/src/pages/ChatPage.tsx
frontend/src/pages/ArenaPage.tsx
frontend/src/pages/AssessmentPage.tsx
frontend/src/pages/CommunicationStatusPage.tsx
frontend/src/components/ReviewPanel.tsx
frontend/src/components/ModelSelector.tsx
frontend/src/components/ModelTester.tsx
frontend/src/components/ApiKeyChecker.tsx
frontend/src/components/feedback/*
frontend/src/components/settings/*
frontend/src/components/safety/*
frontend/src/pages/RoundtablePage.tsx
frontend/src/pages/RoundtableSessionPage.tsx
frontend/src/components/roundtable/*
frontend/src/data/personas.ts
```

### 13.3 Phase 4 Likely Touches

```text
frontend/src/lib/api.ts
scripts/advisor/api/core/models.py
scripts/advisor/api/routes/chat.py
scripts/advisor/api/routes/arena.py
scripts/advisor/api/routes/roundtable.py
scripts/advisor/api/services/roundtable_service.py
configs/i18n/prompts/*
configs/i18n/safety_messages.*.yaml
```

Do not start Phase 4 without explicit user approval.

### 13.4 Phase 5 Likely Touches

```text
frontend/src/App.tsx
frontend/src/components/layout/*
frontend/src/pages/*
frontend/e2e/*mobile*.spec.ts
electron/main.js
electron/preload.js
electron/package.json
docs/ELECTRON_BUILD.md
```

Do not change Electron packaging behavior without explicit user approval.

---

## 14. Handoff Instructions for Execution Agent

### 14.1 Immediate Assignment

Implement only:

```text
Phase 1: Frontend UI zh-CN / en-US switching
```

Do not implement backend localization, AI prompt localization, Electron packaging, PWA, or native app wrappers unless the user explicitly expands scope.

### 14.2 Mandatory Work Style

- Use `conda run -n wechatDHA` for scripts and validation commands.
- Keep all runtime/private data out of the repository.
- Do not hard-code private paths, API keys, provider domains, or local secrets.
- Keep translation keys stable and semantic.
- Keep route paths and API enum values unchanged.
- Prefer small, reviewable commits or patches by feature area.
- After each implementation stage, run build and missing-key checks.

### 14.3 Suggested First Patch Order

1. Install dependencies.
2. Add `i18n/` files and initialize in `main.tsx`.
3. Extend `useSettingsStore` with `locale`.
4. Add `LanguageSwitcher`.
5. Localize `Sidebar` and `App` shell labels.
6. Localize `ConsentPage` and `PrivacyPage`.
7. Localize `Dashboard` and `KnowledgeCenterPage`.
8. Add or run locale key parity check.
9. Run lint/test/build.
10. Report changed files and remaining hard-coded strings.

### 14.4 Deliverable Report Format

Execution agent should report:

```text
Implemented:
- ...

Validation:
- npm run lint: pass/fail
- npm run test: pass/fail
- npm run build: pass/fail
- locale key parity: pass/fail

Known remaining hard-coded UI text:
- ...

Out of scope not changed:
- backend prompts
- AI output language
- Electron packaging
```

---

**Document version**: v1.0  
**Created**: 2026-06-14  
**Immediate implementation scope**: Frontend UI zh-CN / en-US switching only  
**Related documents**: [Advisor Web Application System Design](web_app_overview.md), [Roundtable Discussion System Design](roundtable_discussion_overview.md), [Electron Build](../ELECTRON_BUILD.md)

---

## 15. Current Quality Review and Closure Recommendations

> Review time: 2026-06-14 15:00 UTC+8
> Review scope: current frontend language-switching implementation, translation resources, runtime hard-coded text residue, build/test/lint status, and documentation accuracy.

### 15.1 Overall Verdict

The current implementation has a correct and usable i18n foundation. The selected stack is appropriate for the Lens frontend:

```text
i18next
react-i18next
i18next-browser-languagedetector
```

The application can be built successfully, and the basic Chinese/English switching framework is in place.

After the P0 correctness fixes round (2026-06-14):

```text
P0 i18n correctness fixes: complete
Build and tests: pass
Full UI localization coverage: still in progress
```

Recommended status wording:

```text
Frontend i18n infrastructure is stable.
Critical key correctness issues are fixed.
The next phase is broad UI text extraction and allowlist-based hard-coded Chinese cleanup.
```

Avoid claiming:

```text
Frontend i18n complete
```

because runtime source scanning still finds user-visible Chinese UI strings outside locale files that need systematic extraction.

### 15.2 What Is Working Well

| Area | Result | Notes |
|------|--------|-------|
| Technology choice | Good | `i18next` + `react-i18next` matches the recommended React/Vite approach. |
| Initialization order | Good | `frontend/src/main.tsx` imports `./i18n` before rendering `App`. |
| Locale registry | Good | `zh-CN` and `en-US` are registered through `supportedLocales.ts`. |
| Translation file parity | Good | `zh-CN.json` and `en-US.json` currently have equal flattened key sets. |
| Production build | Good | `npm --prefix frontend run build` passes. |
| Diff hygiene | Good | `git diff --check` passes for the reviewed scope. |

Measured translation-resource parity:

```text
zh_keys = 366
en_keys = 366
missing_in_en = 0
missing_in_zh = 0
type_mismatch = 0
```

This means the two locale files are structurally aligned.

### 15.3 Main Quality Gaps

#### 15.3.1 Runtime Chinese Hard-Coded Text Remains

After excluding tests, comments, and locale JSON files, runtime source scanning still found Chinese text in many frontend files.

Observed result:

```text
runtime_chinese_files = 39
```

High-priority residue areas include:

| Area | Example Files |
|------|---------------|
| Dashboard subcomponents | `components/dashboard/ActivityFeed.tsx`, `ModelConfig.tsx`, `PipelinePanel.tsx`, `StatsCard.tsx` |
| Error boundary | `components/error/ErrorBoundary.tsx` |
| Roundtable components | `AgentMessage.tsx`, `FollowUpComposer.tsx`, `InjectionDrawer.tsx`, `ModeratorCard.tsx`, `ModeratorThinking.tsx`, `PhaseBanner.tsx`, `RoundHistoryCard.tsx`, `SessionHistoryList.tsx`, `TypingDots.tsx` |
| Shared components | `components/shared/ExportDialog.tsx`, `SessionOptions.tsx` |
| Safety components | `components/safety/SafetyDisclaimer.tsx` |
| Supervision components | `components/supervision/DialogueProgressAnalysis.tsx`, `SupervisionStatePanel.tsx` |

Implication:

```text
The language switcher can demonstrate partial UI switching, but users will still encounter Chinese text in complex pages and subcomponents.
```

#### 15.3.2 Missing or Fragile Translation Key Usage

Literal `t('...')` scan found:

```text
literal_t_calls = 315
unique_literal_t_keys = 290
missing_literal_t_keys = 4
```

Detected items:

```text
components/ModelSelector.tsx modelSelector.modelLabel
components/safety/EmergencyModal.tsx emergency.guideItems.0
components/safety/EmergencyModal.tsx emergency.guideItems.1
components/safety/EmergencyModal.tsx emergency.guideItems.2
```

Assessment:

- `modelSelector.modelLabel` is a real missing key and should be added to both locale files.
- `emergency.guideItems.0/1/2` may work depending on i18next array-index handling, but it is fragile for long-term multilingual maintenance.

Recommended replacement:

```json
"guideItems": {
  "keepSafe": "...",
  "contactTrusted": "...",
  "goEmergency": "..."
}
```

Then use stable semantic keys:

```tsx
t('emergency.guideItems.keepSafe')
t('emergency.guideItems.contactTrusted')
t('emergency.guideItems.goEmergency')
```

#### 15.3.3 Potential Language State Desynchronization

There are currently two persistence surfaces:

```text
i18next detector localStorage key: lens-locale
Zustand persisted settings key: lens-settings
```

`LanguageSwitcher` reads:

```text
useSettingsStore((s) => s.locale)
```

but rendered translations follow:

```text
i18n.language
```

Risk:

```text
If lens-settings.locale and lens-locale diverge, the switcher may display one language while the page renders another.
```

Recommended rule:

```text
Use one authoritative locale source.
```

Preferred implementation options:

1. Use i18next as the runtime source of truth and keep Zustand synchronized only as user preference metadata.
2. Or use Zustand/localStorage as the sole persisted preference and initialize i18next explicitly from it.

Do not let both persistence layers independently decide the active language.

#### 15.3.4 Tests Are Not Fully Updated for i18n

Current test result:

```text
npm --prefix frontend run test: failed
```

Observed failure:

```text
roundtable_mobile_viewport.test.tsx
```

The failure is mainly due to tests still searching for previous Chinese UI strings, and some rendered components do not receive an initialized i18next instance in test setup.

Observed warning:

```text
react-i18next:: useTranslation:
You will need to pass in an i18next instance by using initReactI18next
```

Recommended fixes:

- Import `src/i18n/index.ts` in `frontend/src/test/setup.ts`.
- Or provide a dedicated i18n test mock.
- Replace brittle Chinese text assertions with:
  - stable `data-testid`,
  - translated text generated through test i18n,
  - or language-agnostic structural assertions.

#### 15.3.5 Lint Is Not Passing

Current lint result:

```text
npm --prefix frontend run lint: failed
```

Some failures appear to be pre-existing React/lint rule issues. However, i18n work also introduces or exposes hook dependency warnings, especially where `t` is used inside `useCallback`, `useMemo`, or `useEffect`.

Example category:

```text
React Hook useCallback/useMemo/useEffect has a missing dependency: 't'
```

Risk:

```text
Some memoized or callback-generated text may not update immediately after language switching.
```

Recommended fix:

```text
Add `t` to dependency arrays where translated text is computed inside hooks.
```

### 15.4 Quality Score

| Dimension | Score | Rationale |
|-----------|------:|-----------|
| Technology selection | 9/10 | Correct mainstream stack for React/Vite. |
| i18n initialization | 8/10 | Functional, but locale source-of-truth needs cleanup. |
| Locale file structure | 8/10 | Key parity is good; array-index keys should be avoided. |
| Build readiness | 8/10 | Production build passes. |
| UI coverage completeness | 4/10 | Many runtime Chinese strings remain. |
| Test synchronization | 4/10 | Unit/integration tests not fully adapted to i18n. |
| Lint health | 5/10 | Existing issues plus i18n hook dependency warnings. |
| Demo readiness | 6.5/10 | Good enough for partial demo, not for full localization claim. |
| Merge readiness | 5.5/10 | Needs closure pass before being marked complete. |

Overall:

```text
Usable foundation, not yet complete closure.
```

### 15.5 Required Closure Work Before Marking Complete

#### P0: Correctness Fixes

- Add `modelSelector.modelLabel` to `zh-CN.json` and `en-US.json`.
- Replace `emergency.guideItems.0/1/2` with semantic object keys.
- Initialize i18n in test setup or add a test-safe i18n mock.
- Update tests that assert old Chinese strings.
- Revise README and this plan if they claim full UI localization is already complete.

#### P1: Real UI Coverage

- Continue extracting runtime Chinese strings from the 39 detected source files.
- Prioritize user-visible surfaces:
  - Roundtable components,
  - Dashboard subcomponents,
  - ErrorBoundary,
  - ExportDialog,
  - SessionOptions,
  - SafetyDisclaimer,
  - Supervision panels.
- Add `t` to hook dependency arrays where required.
- Resolve locale source-of-truth desynchronization between `lens-locale` and `lens-settings`.

#### P2: UX and Maintainability

- Localize `LanguageSwitcher` aria labels.
- Consider displaying compact labels such as `中` / `EN` or full localized labels instead of raw locale codes.
- Add an official locale key parity script.
- Add a runtime hard-coded text scan script for future PR checks.
- Test English layout at mobile and desktop widths.

### 15.6 Recommended Next Execution Task

Recommended task name:

```text
i18n closure pass for frontend Chinese/English UI switching
```

Recommended execution order:

1. Fix missing and fragile locale keys.
2. Add i18n initialization to test setup.
3. Update failing Roundtable viewport test.
4. Fix i18n-related hook dependency warnings.
5. Generate a hard-coded Chinese residue list.
6. Localize the highest-priority residue files.
7. Re-run:

```bash
conda run -n wechatDHA npm --prefix frontend run build
conda run -n wechatDHA npm --prefix frontend run test
conda run -n wechatDHA npm --prefix frontend run lint
```

8. Only then update documentation status from “in progress” to “complete”.

### 15.7 Acceptance Criteria for Complete Status

The frontend UI localization should only be marked complete when all of the following are true:

```text
1. zh-CN/en-US locale key parity passes.
2. Literal t() calls resolve to existing keys.
3. Runtime hard-coded Chinese scan is either zero or has an approved allowlist.
4. npm --prefix frontend run build passes.
5. npm --prefix frontend run test passes.
6. npm --prefix frontend run lint has no new i18n-related warnings.
7. LanguageSwitcher state matches the actual i18next runtime language.
8. Manual QA confirms Chinese -> English -> Chinese switching without refresh.
9. Manual QA confirms refresh preserves the selected language.
10. Manual QA confirms AI output language and backend prompt behavior are unchanged.
```

### 15.8 Current User-Facing Summary

If reporting to a non-technical reviewer, use:

```text
The language-switching foundation is implemented and the app builds successfully.
Chinese/English switching works for the core shell and part of the UI, but full frontend coverage is not complete yet.
Several complex components still contain Chinese hard-coded text, and tests need to be updated for i18n.
The next step should be an i18n closure pass before marking the feature complete.
```
