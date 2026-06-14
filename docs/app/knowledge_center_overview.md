# 知识中心系统设计

> 📌 **文档范围**：本文档描述 Lens 知识中心子系统，包括知识库分类架构、FAQ 条目格式、前端索引页面、后端检索与注入机制、FAISS 索引集成以及扩展路线。
>
> 更新时间：2026-06-14

---

## 目录

- [1. 设计目标](#1-设计目标)
- [2. 知识架构](#2-知识架构)
- [3. 知识分类与内容](#3-知识分类与内容)
- [4. FAQ 条目格式](#4-faq-条目格式)
- [5. 前端体验](#5-前端体验)
- [6. 后端检索与注入](#6-后端检索与注入)
- [7. RAG 集成与三开关控制](#7-rag-集成与三开关控制)
- [8. FAISS 索引升级](#8-faiss-索引升级)
- [9. 扩展路线](#9-扩展路线)
- [10. 关键文件](#10-关键文件)

---

## 1. 设计目标

### 1.1 产品定位

知识中心是 Lens 的专业知识库索引界面。它不是简单的文档列表，而是面向 AI 对话场景的**结构化 FAQ 资产**——每条知识都经过人工摘要，包含问题、答案、分类标签和关键词，可被后端 `_search_faq()` 实时检索并注入到对话上下文中。

该模块服务于两个目标：

- **对用户**：浏览系统已内置的专业知识领域（沟通技巧、危机干预、EFT 治疗、跨学科视角等），了解 Lens 的理论基础。
- **对系统**：为 Chat、Arena、Roundtable 等对话模块提供 RAG-ready 的知识注入，让顾问回复具备专业理论支撑。

### 1.2 设计原则

| 原则 | 说明 |
|------|------|
| **结构化** | 所有知识以 JSONL FAQ 格式存储，可被程序自动解析和检索 |
| **可扩展** | 新增 JSONL 文件后重启后端即生效，无需修改代码 |
| **分类加权** | 顾问人格类型（agent_type）与知识分类自动匹配，优先注入相关领域知识 |
| **渐进激活** | 已激活的领域在前端展示完整条目，规划中的领域展示占位卡片 |

---

## 2. 知识架构

```
┌─────────────────────────────────────────────────────────────────┐
│                      知识中心系统架构                            │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  前端                                                          │
│  ┌───────────────────────────────────────────────────────┐   │
│  │  KnowledgeCenterPage                                    │   │
│  │  ├─ 分类卡片（可展开/折叠）                            │   │
│  │  ├─ 条目列表（文件路径、条目数、描述）                  │   │
│  │  ├─ 统计面板（总条目数、激活领域数）                    │   │
│  │  └─ 扩展路线（当前/近期/远期）                        │   │
│  └───────────────────────────────────────────────────────┘   │
│                                                             │
│  后端                                                          │
│  ┌───────────────────────────────────────────────────────┐   │
│  │  _load_faq_knowledge() → 启动时扫描 advisor_out/knowledge/ │ │
│  │  _search_faq(query, top_k, agent_type) → 关键词 + 分类加权 │ │
│  │  build_rag_context() → 整合聊天记录 + 知识 + 测评注入    │   │
│  │  _create_faiss_index() → BGE-M3 向量索引（graph_rag.py）  │   │
│  └───────────────────────────────────────────────────────┘   │
│                                                             │
│  数据                                                          │
│  ┌───────────────────────────────────────────────────────┐   │
│  │  advisor_out/knowledge/                                 │   │
│  │  ├── communication/nvc_four_steps.jsonl                 │   │
│  │  ├── crisis/grounding_techniques.jsonl                  │   │
│  │  ├── eft_resources/tango_process.jsonl                  │   │
│  │  ├── perspectives/sociology.jsonl                     │   │
│  │  ├── perspectives/philosophy.jsonl                     │   │
│  │  ├── perspectives/game_theory.jsonl                    │   │
│  │  └── perspectives/cultural.jsonl                       │   │
│  └───────────────────────────────────────────────────────┘   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. 知识分类与内容

### 3.1 已激活领域

| 分类 | ID | 图标 | 条目数 | 描述 |
|------|-----|------|--------|------|
| **S6 跨学科视角** | `perspectives` | 🌐 Globe | 40 | 社会学、哲学、博弈论、文化研究四大学科视角 |
| **沟通技巧** | `communication` | ❤️ Heart | 5 | Marshall Rosenberg 非暴力沟通四步法 |
| **危机干预** | `crisis` | 🛡️ Shield | 5 | 5-4-3-2-1 感官接地、蝴蝶拥抱、呼吸法 |
| **EFT 情绪聚焦** | `eft_resources` | 🧠 Brain | 5 | Sue Johnson EFT Tango 九步流程、追逃循环 |

### 3.2 跨学科视角详情

| 文件 | 学科 | 核心概念 |
|------|------|----------|
| `perspectives/sociology.jsonl` | 社会学 | 布尔迪厄场域/资本/惯习、吉登斯反思性、戈夫曼拟剧论 |
| `perspectives/philosophy.jsonl` | 哲学 | 存在主义、现象学、实用主义、儒家关怀伦理 |
| `perspectives/game_theory.jsonl` | 博弈论 | 纳什均衡、囚徒困境、沉没成本、损失厌恶、信号理论 |
| `perspectives/cultural.jsonl` | 文化研究 | 差序格局、集体/个人主义、面子/人情/报、仪式与过渡 |

### 3.3 规划中的领域

| 领域 | 状态 | 计划内容 |
|------|------|----------|
| **治疗手册** | `planned` | WHO PM+、ACT 接纳承诺疗法、Gottman 方法 |
| **GraphRAG** | `planned` | FAQ > 200 条后启用知识图谱多跳推理 |

---

## 4. FAQ 条目格式

每条知识以独立 JSON 对象存储在 `.jsonl` 文件中：

```json
{
  "question": "什么是非暴力沟通（NVC）？",
  "answer": "非暴力沟通包含四个步骤：1) 观察——描述事实而不评判；2) 感受——表达情绪而非想法；3) 需要——识别背后的核心需求；4) 请求——提出具体、可行的请求。",
  "category": "communication",
  "keywords": ["NVC", "非暴力沟通", "四要素", "观察", "感受", "需要", "请求"],
  "source": "Marshall Rosenberg, Nonviolent Communication",
  "license": "人工摘要"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `question` | string | 问题标题，用于检索匹配 |
| `answer` | string | 答案正文，注入到 system prompt |
| `category` | string | 分类标识，用于 agent_type 匹配加权 |
| `keywords` | string[] | 关键词列表，命中时加分 |
| `source` | string | 理论来源 |
| `license` | string | 授权方式 |

---

## 5. 前端体验

### 5.1 页面结构

```
KnowledgeCenterPage
├── 顶部标题栏（Lens 图标 + "知识中心" + 副标题）
├── 统计卡片（总条目数 / 激活领域数 / 规划领域数）
├── 分类列表（可折叠手风琴）
│   ├── 分类头部（图标 + 名称 + 状态标签 + 展开箭头）
│   │   └── 展开后：条目列表 + 注入说明
│   └── 条目项（文件路径 + 条目数 + 描述）
└── 底部扩展路线（当前/近期/远期里程碑）
```

### 5.2 交互设计

- **默认展开**：`perspectives`（跨学科视角）分类默认展开，其余折叠
- **状态标签**：`active` 显示绿色圆点，`planned` 显示琥珀色圆点
- **注入提示**：激活的分类底部显示 `"通过 _search_faq() 自动注入对话上下文"`
- **响应式**：三列统计卡片在窄屏下自动堆叠

---

## 6. 后端检索与注入

### 6.1 启动加载

`_load_faq_knowledge()` 在后端启动时执行：

1. 递归扫描 `advisor_out/knowledge/**/*.jsonl`
2. 逐行解析 JSON，加载到内存字典 `FAQ_KNOWLEDGE[]`
3. 打印分类统计日志：
   ```
   [knowledge] Loaded 55 FAQ entries from 8 files
   ```

### 6.2 检索算法

`_search_faq(query, top_k=3, agent_type="")`：

| 匹配方式 | 基础分 | 说明 |
|----------|--------|------|
| 中文关键词命中 answer/question | +1/词 | 提取 query 中 2 字以上中文词组匹配 |
| keywords 列表命中 | +2/词 | 条目自带的关键词优先匹配 |
| category 匹配 agent_type | 总分 ×2 | EFT 顾问优先匹配 `eft_resources` 类条目 |

返回 top_k 条最高分的 FAQ，按 `"Q: ...\nA: ..."` 格式拼接后注入 system prompt。

### 6.3 注入格式

```
【专业知识】
Q: 什么是非暴力沟通（NVC）？
A: 非暴力沟通包含四个步骤：1) 观察 2) 感受 3) 需要 4) 请求...

Q: 什么是追逃循环？
A: 追逃循环是 EFT 中的核心概念，描述了伴侣一方追求亲密、另一方逃避压力的互动模式...
```

与 `【历史摘要】`、`【已确认的关键信息】`、`【用户交流前测评结果】` 平行，各占独立段落。

---

## 7. RAG 集成与三开关控制

知识注入受三个独立开关控制，用户可在 ChatTopBar 和 ArenaPage 中自由组合：

| 开关 | 控制字段 | 前端位置 | 默认 | 颜色 |
|------|---------|---------|------|------|
| 聊天记录 | `use_rag` | ChatTopBar / ArenaPage | 开 | 绿色 |
| 专业知识 | `use_knowledge` | ChatTopBar / ArenaPage | 开 | 紫色 |
| 测评注入 | `inject_enabled` | 测评结果页 | 关 | 绿色 |

`use_knowledge=false` 时，`_build_rag_context()` 内的 `_search_faq()` 被跳过，但聊天记录检索不受影响。

---

## 8. FAISS 索引升级

知识中心的数据不仅支持关键词检索，还通过 `graph_rag.py` 的 FAISS 索引支持语义向量检索：

| 索引类型 | 行为 | 适用场景 |
|----------|------|---------|
| `"auto"` | N < 2000 → FlatIP，否则 → IVFFlat | 默认，自动选择 |
| `"flat"` | 强制 FlatIP | 需要 100% 召回率时 |
| `"ivf"` | 强制 IVFFlat（nlist=√N, nprobe=10） | 大数据集优化 |
| `"hnsw"` | 预留，当前 fallback 到 FlatIP | 未来迁移到 Qdrant |

嵌入模型使用 **BGE-M3**（~2GB 显存），支持多语言跨语种检索。

---

## 9. 扩展路线

```
当前（v1.0）          近期（v1.1）              远期（v2.0）
   │                    │                        │
   ├─ 55 条 FAQ        ├─ CBT/DBT/Gottman       ├─ GraphRAG
   ├─ 4 个 active       ├─ 治疗手册 FAQ          ├─ 知识图谱
   ├─ 2 个 planned      ├─ 条目数 > 100          ├─ 多跳推理
   └─ 关键词检索        └─ 混合检索（关键词+向量） └─ 跨学科概念关联
```

---

## 10. 关键文件

| 文件 | 职责 |
|------|------|
| [`frontend/src/pages/KnowledgeCenterPage.tsx`](../../frontend/src/pages/KnowledgeCenterPage.tsx) | 前端知识中心页面（React + Tailwind） |
| [`scripts/advisor/api/services/rag_service.py`](../../scripts/advisor/api/services/rag_service.py) | `_search_faq()`、`build_rag_context()` 实现 |
| [`scripts/advisor/api/core/graph_rag.py`](../../scripts/advisor/api/core/graph_rag.py) | FAISS 索引工厂、BGE-M3 嵌入、混合检索 |
| [`docs/pipelines/knowledge_rag_upgrade_overview.md`](../../docs/pipelines/knowledge_rag_upgrade_overview.md) | RAG 知识注入与 FAISS 索引升级的详细设计 |
| `advisor_out/knowledge/**` | FAQ JSONL 数据文件（运行时加载） |

---

# Knowledge Center System Design

> 📌 **Scope**: This document describes the Lens Knowledge Center subsystem, including knowledge base taxonomy, FAQ entry format, frontend index page, backend search/injection mechanism, FAISS index integration, and expansion roadmap.
>
> Updated: 2026-06-14

---

## Table of Contents

- [1. Design Goals](#1-design-goals)
- [2. Knowledge Architecture](#2-knowledge-architecture)
- [3. Categories and Content](#3-categories-and-content)
- [4. FAQ Entry Format](#4-faq-entry-format)
- [5. Frontend Experience](#5-frontend-experience)
- [6. Backend Search and Injection](#6-backend-search-and-injection)
- [7. RAG Integration and Triple-Switch Control](#7-rag-integration-and-triple-switch-control)
- [8. FAISS Index Upgrade](#8-faiss-index-upgrade)
- [9. Expansion Roadmap](#9-expansion-roadmap)
- [10. Key Files](#10-key-files)

---

## 1. Design Goals

### 1.1 Product Positioning

The Knowledge Center is Lens's professional knowledge base index. It is not a simple document list, but **structured FAQ assets** designed for AI dialogue scenarios — each entry is human-summarized with question, answer, category tags, and keywords, searchable in real time by the backend `_search_faq()` and injected into the conversation context.

This module serves two goals:

- **For users**: Browse the built-in professional knowledge domains (communication skills, crisis intervention, EFT therapy, interdisciplinary perspectives, etc.) to understand Lens's theoretical foundations.
- **For the system**: Provide RAG-ready knowledge injection for Chat, Arena, and Roundtable modules, giving advisor responses professional theoretical grounding.

### 1.2 Design Principles

| Principle | Description |
|-----------|-------------|
| **Structured** | All knowledge stored in JSONL FAQ format, automatically parseable and searchable |
| **Extensible** | New JSONL files take effect after backend restart without code changes |
| **Category-weighted** | Advisor persona type (agent_type) auto-matches knowledge category for priority injection |
| **Progressive activation** | Active domains show full entries; planned domains show placeholder cards |

---

## 2. Knowledge Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Knowledge Center Architecture                │
├─────────────────────────────────────────────────────────────┤
│                                                                 │
│  Frontend                                                        │
│  ┌───────────────────────────────────────────────────────┐     │
│  │  KnowledgeCenterPage                                    │     │
│  │  ├─ Category cards (expandable/collapsible)           │     │
│  │  ├─ Entry list (file path, count, description)        │     │
│  │  ├─ Stats panel (total entries, active domains)        │     │
│  │  └─ Expansion roadmap (current/near/future)             │     │
│  └───────────────────────────────────────────────────────┘     │
│                                                                 │
│  Backend                                                         │
│  ┌───────────────────────────────────────────────────────┐     │
│  │  _load_faq_knowledge() → scan advisor_out/knowledge/ at boot │
│  │  _search_faq(query, top_k, agent_type) → keyword + cat boost │
│  │  build_rag_context() → merge chat history + knowledge + test │
│  │  _create_faiss_index() → BGE-M3 vector index (graph_rag.py)│
│  └───────────────────────────────────────────────────────┘     │
│                                                                 │
│  Data                                                            │
│  ┌───────────────────────────────────────────────────────┐     │
│  │  advisor_out/knowledge/                               │     │
│  │  ├── communication/nvc_four_steps.jsonl               │     │
│  │  ├── crisis/grounding_techniques.jsonl                │     │
│  │  ├── eft_resources/tango_process.jsonl                │     │
│  │  ├── perspectives/sociology.jsonl                   │     │
│  │  ├── perspectives/philosophy.jsonl                  │     │
│  │  ├── perspectives/game_theory.jsonl                   │     │
│  │  └── perspectives/cultural.jsonl                      │     │
│  └───────────────────────────────────────────────────────┘     │
│                                                                 │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. Categories and Content

### 3.1 Active Domains

| Category | ID | Icon | Entries | Description |
|----------|-----|------|---------|-------------|
| **S6 Interdisciplinary Perspectives** | `perspectives` | 🌐 Globe | 40 | Sociology, philosophy, game theory, cultural studies |
| **Communication Skills** | `communication` | ❤️ Heart | 5 | Marshall Rosenberg NVC four-step model |
| **Crisis Intervention** | `crisis` | 🛡️ Shield | 5 | 5-4-3-2-1 grounding, butterfly hug, breathing |
| **EFT Emotion Focused** | `eft_resources` | 🧠 Brain | 5 | Sue Johnson EFT Tango nine-step process, pursue-withdraw cycle |

### 3.2 Interdisciplinary Perspective Details

| File | Discipline | Core Concepts |
|------|------------|---------------|
| `perspectives/sociology.jsonl` | Sociology | Bourdieu field/capital/habitus, Giddens reflexivity, Goffman dramaturgy |
| `perspectives/philosophy.jsonl` | Philosophy | Existentialism, phenomenology, pragmatism, Confucian care ethics |
| `perspectives/game_theory.jsonl` | Game Theory | Nash equilibrium, prisoner's dilemma, sunk cost, loss aversion, signaling |
| `perspectives/cultural.jsonl` | Cultural Studies | Differential mode of association, collectivism/individualism, face/favor/reciprocity, rituals |

### 3.3 Planned Domains

| Domain | Status | Planned Content |
|--------|--------|-----------------|
| **Therapy Manuals** | `planned` | WHO PM+, ACT, Gottman Method |
| **GraphRAG** | `planned` | Knowledge graph multi-hop reasoning after FAQ > 200 entries |

---

## 4. FAQ Entry Format

Each knowledge entry is stored as an independent JSON object in `.jsonl` files:

```json
{
  "question": "What is Nonviolent Communication (NVC)?",
  "answer": "NVC consists of four steps: 1) Observation — describe facts without judgment; 2) Feeling — express emotions rather than thoughts; 3) Need — identify underlying core needs; 4) Request — make specific, actionable requests.",
  "category": "communication",
  "keywords": ["NVC", "nonviolent communication", "four steps", "observation", "feeling", "need", "request"],
  "source": "Marshall Rosenberg, Nonviolent Communication",
  "license": "Human summary"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `question` | string | Question title for search matching |
| `answer` | string | Answer body injected into system prompt |
| `category` | string | Category ID for agent_type matching boost |
| `keywords` | string[] | Keyword list for scoring bonus |
| `source` | string | Theoretical source |
| `license` | string | License type |

---

## 5. Frontend Experience

### 5.1 Page Structure

```
KnowledgeCenterPage
├── Top title bar (Lens icon + "Knowledge Center" + subtitle)
├── Stats cards (total entries / active domains / planned domains)
├── Category list (collapsible accordion)
│   ├── Category header (icon + name + status tag + expand arrow)
│   │   └── When expanded: entry list + injection note
│   └── Entry item (file path + entry count + description)
└── Bottom expansion roadmap (current/near/future milestones)
```

### 5.2 Interaction Design

- **Default expanded**: `perspectives` category is expanded by default, others collapsed
- **Status tag**: `active` shows green dot, `planned` shows amber dot
- **Injection hint**: Active categories show `"Automatically injected into dialogue context via _search_faq()"`
- **Responsive**: Three-column stats cards stack on narrow screens

---

## 6. Backend Search and Injection

### 6.1 Boot Loading

`_load_faq_knowledge()` runs at backend startup:

1. Recursively scan `advisor_out/knowledge/**/*.jsonl`
2. Parse JSON line by line, load into in-memory dict `FAQ_KNOWLEDGE[]`
3. Print category stats log:
   ```
   [knowledge] Loaded 55 FAQ entries from 8 files
   ```

### 6.2 Search Algorithm

`_search_faq(query, top_k=3, agent_type="")`:

| Match Type | Base Score | Description |
|------------|------------|-------------|
| Chinese keyword hit in answer/question | +1/word | Extract 2+ char Chinese phrases from query |
| keywords list hit | +2/word | Entry's own keywords get priority matching |
| category matches agent_type | total ×2 | EFT advisor prioritizes `eft_resources` entries |

Returns top_k highest-scoring FAQs, concatenated in `"Q: ...\nA: ..."` format and injected into system prompt.

### 6.3 Injection Format

```
[Professional Knowledge]
Q: What is Nonviolent Communication (NVC)?
A: NVC consists of four steps: 1) Observation 2) Feeling 3) Need 4) Request...

Q: What is the pursue-withdraw cycle?
A: The pursue-withdraw cycle is a core EFT concept describing the interaction pattern where one partner pursues intimacy while the other withdraws under pressure...
```

Parallel to `[Historical Summary]`, `[Confirmed Key Information]`, and `[Pre-Chat Assessment Results]`, each occupying an independent paragraph.

---

## 7. RAG Integration and Triple-Switch Control

Knowledge injection is controlled by three independent switches, which users can freely combine in ChatTopBar and ArenaPage:

| Switch | Control Field | Frontend Location | Default | Color |
|--------|---------------|-------------------|---------|-------|
| Chat history | `use_rag` | ChatTopBar / ArenaPage | On | Green |
| Professional knowledge | `use_knowledge` | ChatTopBar / ArenaPage | On | Purple |
| Assessment injection | `inject_enabled` | Assessment results page | Off | Green |

When `use_knowledge=false`, `_search_faq()` inside `_build_rag_context()` is skipped, but chat history retrieval remains unaffected.

---

## 8. FAISS Index Upgrade

The Knowledge Center supports not only keyword search but also semantic vector retrieval via the FAISS index in `graph_rag.py`:

| Index Type | Behavior | Use Case |
|------------|----------|----------|
| `"auto"` | N < 2000 → FlatIP, else → IVFFlat | Default, auto-select |
| `"flat"` | Force FlatIP | When 100% recall is required |
| `"ivf"` | Force IVFFlat (nlist=√N, nprobe=10) | Large dataset optimization |
| `"hnsw"` | Reserved, currently fallback to FlatIP | Future migration to Qdrant |

Embedding model: **BGE-M3** (~2GB VRAM), supporting multilingual cross-lingual retrieval.

---

## 9. Expansion Roadmap

```
Current (v1.0)       Near-term (v1.1)        Long-term (v2.0)
   │                    │                        │
   ├─ 55 FAQ entries    ├─ CBT/DBT/Gottman        ├─ GraphRAG
   ├─ 4 active domains  ├─ Therapy manual FAQ      ├─ Knowledge graph
   ├─ 2 planned domains ├─ Entries > 100           ├─ Multi-hop reasoning
   └─ Keyword search    └─ Hybrid (keyword+vector) └─ Cross-disciplinary concept linkage
```

---

## 10. Key Files

| File | Responsibility |
|------|----------------|
| [`frontend/src/pages/KnowledgeCenterPage.tsx`](../../frontend/src/pages/KnowledgeCenterPage.tsx) | Frontend Knowledge Center page (React + Tailwind) |
| [`scripts/advisor/api/services/rag_service.py`](../../scripts/advisor/api/services/rag_service.py) | `_search_faq()`, `build_rag_context()` implementation |
| [`scripts/advisor/api/core/graph_rag.py`](../../scripts/advisor/api/core/graph_rag.py) | FAISS index factory, BGE-M3 embedding, hybrid retrieval |
| [`docs/pipelines/knowledge_rag_upgrade_overview.md`](../../docs/pipelines/knowledge_rag_upgrade_overview.md) | Detailed design of RAG knowledge injection and FAISS index upgrade |
| `advisor_out/knowledge/**` | FAQ JSONL data files (loaded at runtime) |
