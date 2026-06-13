# Arena 双镜对比系统设计概览

> 📌 **本文档定位**：这是 [多模态处理流水线文档](modality_fields_and_models.md) §21 的详细设计文档，专注于双镜对比系统的交互设计、打分机制、Elo 排名算法、安全治理、数据流与前端实现。
>
> 更新于：2026-03-08 v2.1（新增 S6 视角碰撞模式）

---

## 目录

- [1. 设计理念](#1-设计理念)
- [2. 系统架构总览](#2-系统架构总览)
- [3. 核心交互流程](#3-核心交互流程)
- [4. 后端 API 完整参考](#4-后端-api-完整参考)
- [5. 打分机制详解](#5-打分机制详解)
- [6. Bradley-Terry Elo 排名算法](#6-bradley-terry-elo-排名算法)
- [7. 安全治理](#7-安全治理)
- [8. 长对话记忆机制](#8-长对话记忆机制)
- [9. 高级分析功能](#9-高级分析功能)
- [10. 前端实现](#10-前端实现)
- [11. 数据结构与持久化](#11-数据结构与持久化)
- [12. UX 功能清单](#12-ux-功能清单)
- [13. 数据流向与下游消费](#13-数据流向与下游消费)
- [14. 配置参数与可调整项](#14-配置参数与可调整项)
- [15. 已知限制与演进方向](#15-已知限制与演进方向)

---

## 1. 设计理念

### 1.1 核心目标

双镜对比（Arena）是 Lens 聆诉系统的 A/B 测试模块，核心目的是让用户在**盲评**场景下对比不同 LLM 的关系咨询质量，从而：

| 目标 | 方法 | 数据产出 |
|------|------|----------|
| 帮用户发现偏好 | 同一问题、双路匿名回答、用户投票 | 投票日志 |
| 量化模型能力 | 五维评分 + Bradley-Terry Elo 排名 | Elo 排名快照 |
| 收集偏好数据 | 投票 → `battles.jsonl` → KTO/DPO 训练 | chosen/rejected 对 |
| 发现薄弱场景 | Query 分层统计各模型胜率 | 类别×模型胜率矩阵 |
| 评估评分质量 | am-ELO 标注一致性分析 | 质量分 + 降权策略 |

> "对话即真理的生成过程——通过不同视角的碰撞，用户在选择中发现自己的真实倾向"

### 1.2 设计原则

```
┌────────────────────────────────────────────────────────────────────────┐
│                           设计原则                                      │
├────────────────────────────────────────────────────────────────────────┤
│  1. 匿名优先：A/B 身份默认隐藏，减少品牌偏见                           │
│  2. 并行沉浸式：与沉浸式互动同构（流式输出、多轮对话、RAG、记忆）       │
│  3. 安全一致性：Arena 路径与主对话共享四级危机检测                       │
│  4. 评分可解释：五维 + 备注，而非简单的"好/坏"                         │
│  5. 数据闭环：投票直接反哺 Elo 排名和 KTO/DPO 偏好对齐                 │
│  6. 用户自主权：模型揭示可开可关、单路退化可选、注入开关用户控制         │
└────────────────────────────────────────────────────────────────────────┘
```

### 1.3 三种对比模式

| 模式 | 选手 A vs B | 对比焦点 | 实现状态 |
|------|-------------|---------|---------|
| **模型对决** | DeepSeek vs Grok vs GPT vs Claude | 同一 prompt，不同模型的回答质量 | ✅ 已实现 |
| **流派对比** | 中立 vs 支持性 vs 精神分析 vs EFT 情绪聚焦 vs 家庭系统 | 同一模型，不同 Agent 类型的风格差异 | ✅ 已实现（5 种流派） |
| **视角碰撞** | 社会学视角 vs 哲学视角 vs 博弈论视角 vs 文化视角 | Phase II 跨学科引擎的效果对比 | ✅ 已实现（S6 跨学科理论引擎） |

### 1.4 五种顾问流派（Agent Type）

| agent_type | 前端名称 | 理论框架 | 核心特色 | 新增版本 |
|-----------|---------|---------|---------|---------|
| `neutral` | 中立顾问 | 多维分析（NVC/依附/权力动态） | 客观不偏向，结构化分析 | v1.0 |
| `supportive` | 支持性顾问 | 无条件积极关注（Rogers） | 始终站在用户一方，情感验证 | v1.0 |
| `psychoanalytic` | 精神分析顾问 | 客体关系 + 拉康（三界/欲望/防御） | 深层无意识探索，均匀悬浮注意力 | v1.0 |
| `eft` | EFT 情绪聚焦 | Sue Johnson Tango（9 步 move） | 追逃循环识别 + 依恋需求 + 阶段推进 | v2.5 |
| `bowen` | 家庭系统顾问 | Murray Bowen 八大概念 | 三角关系 + 自我分化 + 情绪切断 + 代际传递 | v2.5 |

#### S6 跨学科理论引擎视角（v2.8 新增）

| agent_type | 前端名称 | 理论框架 | 核心特色 | 知识库条目 |
|-----------|---------|---------|---------|---------|
| `sociology` | 社会学视角 | 布尔迪厄场域/资本 + 吉登斯反思性 + 戈夫曼拟剧论 | 权力场域分析、印象管理、面子工作 | 10 条 |
| `philosophy` | 哲学视角 | 存在主义 + 现象学 + 实用主义 + 儒家关怀伦理 | 苏格拉底式追问，不给答案引导思考 | 10 条 |
| `game_theory` | 博弈论视角 | 纳什均衡 + 囚徒困境 + 行为经济学(沉没成本/损失厌恶) | 理性分析关系博弈结构 | 10 条 |
| `cultural` | 文化视角 | 差序格局 + 集体/个人主义 + 亲属系统 + 仪式象征 | 文化脚本如何塑造关系期待 | 10 条 |

每种顾问在 `core/prompts.py` 中有 `listen`（倾听模式，5-7 句）和 `consult`（咨询模式，800-1500 字）两套 System Prompt。

#### EFT 特有机制

- **阶段推进**：session 记录 `eft_stage`（exploration → comforting → action），按轮次自动推进
- **Prompt 动态注入**：每轮将当前阶段名称和对应 move 建议注入 system prompt
- **前端阶段标签**：ChatTopBar 显示粉色 badge（探索阶段/安抚阶段/行动阶段），每轮结束后实时更新
- **安全阀**：前 3 轮限制只做情绪镜像和深化，Prompt 内嵌接地技巧指令

#### Bowen 特有机制

- **第三方检测**：21 个关键词扫描用户消息，自动追踪 `bowen_third_parties`
- **三角关系注入**：检测到第三方后，system prompt 追加三角关系分析指令
- **输出格式**：所有分析强制"假设+证据+验证问题"三段式

#### 新增顾问的步骤（开发者指南）

新增一种顾问只需修改 3 个文件，无需改动 server.py 核心逻辑：

1. **`core/prompts.py`**：在 `CHAT_SYSTEM_PROMPTS` 字典中增加一个新 key（如 `"cbt"`），包含 `listen` 和 `consult` 两个 prompt
2. **`frontend/src/types/index.ts`**：在 `PersonaType` 联合类型中增加新值
3. **`frontend/src/constants.ts`**：在 `PERSONAS` 数组中增加一项（id/name/color/hex/icon/description）

如果新顾问需要特殊的 session 元数据（如 EFT 的阶段追踪），还需在 `server.py` 的 `_create_session()` 和 `_save_and_finalize()` 中增加对应逻辑。

### 1.5 为什么选择这种设计而非传统的"投票式"

传统 A/B 对比仅收集"谁更好"的二元信号。我们的设计增加了三层信息密度：

| 信息层 | 传统 Arena | Lens Arena |
|--------|-----------|------------|
| **胜负信号** | a_win / b_win | a_win / b_win / tie / both_good / both_bad（5 种） |
| **维度信号** | 无 | 5 维度 × 2 侧 × 1-10 分 = 50 个数值/轮 |
| **自然语言解释** | 无 | 评分备注（最多 240 字，解释偏好原因） |

这使得：
- Elo 排名不仅有总分，还有维度级排名（发现"共情强但深度弱"的模型）
- KTO/DPO 训练可以区分"深度不足"和"共情不足"两种不同的 reject 原因
- 备注数据可以做后续的自然语言偏好分析

---

## 2. 系统架构总览

### 2.1 整体数据流

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                          Arena 双镜对比系统                                       │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│   ┌──────────────┐   ┌──────────────────┐   ┌─────────────────┐                │
│   │   用户输入    │──▶│  危机检测（四级）  │──▶│  RED → 中断      │               │
│   │  （同一条）   │   │  GREEN/YELLOW/    │   │  YELLOW/ORANGE   │               │
│   │              │   │  ORANGE/RED       │   │  → 安全引导注入  │               │
│   └──────────────┘   └──────────────────┘   └────────┬────────┘               │
│                                                       │                        │
│                                               ┌───────▼───────┐                │
│                                               │  System Prompt │                │
│                                               │  构建层         │                │
│                                               │  ┌────────────┐│                │
│                                               │  │Agent prompt ││                │
│                                               │  │+ 安全引导   ││                │
│                                               │  │+ 测评注入   ││                │
│                                               │  │+ RAG 上下文 ││                │
│                                               │  │+ 记忆摘要   ││                │
│                                               │  │+ 关键事实   ││                │
│                                               │  └────────────┘│                │
│                                               └───────┬───────┘                │
│                                                       │                        │
│                              ┌─────────────────────────┼────────────────────┐   │
│                              │                         │                    │   │
│                         ┌────▼─────┐             ┌─────▼────┐              │   │
│                         │  模型 A   │             │  模型 B   │              │   │
│                         │ (并发生成) │             │ (并发生成) │              │   │
│                         └────┬─────┘             └─────┬────┘              │   │
│                              │                         │                    │   │
│                         ┌────▼─────┐             ┌─────▼────┐              │   │
│                         │ 禁用词    │             │ 禁用词    │              │   │
│                         │ 后处理    │             │ 后处理    │              │   │
│                         └────┬─────┘             └─────┬────┘              │   │
│                              │                         │                    │   │
│                              └────────────┬────────────┘                    │   │
│                                           │                                │   │
│                                    ┌──────▼──────┐                         │   │
│                                    │  打分面板    │                         │   │
│                                    │ (§5 详解)    │                         │   │
│                                    └──────┬──────┘                         │   │
│                                           │                                │   │
│                              ┌────────────┼────────────┐                   │   │
│                              ▼            ▼            ▼                   │   │
│                         session.json  battles.jsonl  elo_ratings.json      │   │
│                         (轮次持久化)   (Elo 数据源)   (排名缓存)            │   │
│                                                                            │   │
│                                    ┌──────────────┐                        │   │
│                                    │  Elo MLE     │                        │   │
│                                    │  全量重算    │                        │   │
│                                    │ (§6 详解)    │                        │   │
│                                    └──────┬───────┘                        │   │
│                                           │                                │   │
│                              ┌────────────┼────────────┐                   │   │
│                              ▼            ▼            ▼                   │   │
│                         排行榜       偏好统计     KTO/DPO 训练             │   │
│                         展示         柱状图       数据源                    │   │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 关键文件索引

| 文件 | 职责 | 行数约 |
|------|------|--------|
| `scripts/advisor/api/server.py` | Arena 全部后端 API（session CRUD + chat + vote + stats + Elo MLE） | ~600 行 Arena 相关 |
| `frontend/src/pages/ArenaPage.tsx` | 双镜对比主页面（双路聊天 + 打分面板 + 侧边栏 + 导出） | ~630 行 |
| `frontend/src/pages/ArenaStatsPage.tsx` | Elo 排行榜 + 偏好统计 + Query 分层 + 标注质量 | ~240 行 |
| `frontend/src/stores/useArenaStore.ts` | Zustand 状态管理 | ~105 行 |
| `frontend/src/components/shared/ExportDialog.tsx` | JSON/Markdown 导出（Arena + Chat 共用） | ~118 行 |
| `frontend/src/lib/api.ts` | 前端 API 客户端（Arena 相关方法） | ~40 行 Arena 相关 |
| `advisor_out/arena/battles.jsonl` | 对局日志（每轮一行 JSONL） | 增量追加 |
| `advisor_out/arena/sessions/*.json` | Arena 会话持久化 | 每会话一个文件 |
| `advisor_out/arena/elo_ratings.json` | Elo 排名快照缓存 | 自动重算 |

---

## 3. 核心交互流程

### 3.1 用户操作全流程

```
用户进入 /arena
    │
    ├─ 侧边栏：新建对比 / 加载历史 / Elo 排名入口
    │
    ▼
用户输入问题（Enter 发送）
    │
    ├─ 前端同时发送给 A/B 模型 → POST /api/arena/chat
    │   ├─ 后端危机检测
    │   │   ├─ RED → 中断，返回危机干预文案，requires_vote=false
    │   │   ├─ YELLOW/ORANGE → 注入安全引导到 system prompt
    │   │   └─ GREEN → 正常生成
    │   ├─ 构建 system prompt（基础 + 安全引导 + 测评注入 + RAG + 记忆）
    │   ├─ asyncio.gather 并发调用 A/B 模型
    │   ├─ 禁用词后处理
    │   └─ 返回 { response_a, response_b, crisis_level, requires_vote }
    │
    ▼
左右双栏同时显示 A/B 回复
    │
    ├─ 如果 requires_vote=true → 弹出打分面板（§5 详解）
    │   ├─ Step 1: 胜负投票（5 选 1）
    │   ├─ Step 2: 五维评分（1-10 滑块 × 2 侧）
    │   ├─ Step 3: 评分备注（可选，最多 240 字）
    │   ├─ 「提交评分」→ POST /api/arena/vote
    │   │   ├─ 写入 session 对应轮次（vote + scores + remark）
    │   │   ├─ 追加到 battles.jsonl（完整对局快照）
    │   │   └─ 返回 contestant 身份 → 揭示模型
    │   └─ 「跳过」→ 标记 submitted=true，不写 vote（不影响 Elo）
    │
    ├─ 如果 requires_vote=false（RED 危机）→ 显示干预提示，不弹打分
    │
    ▼
继续下一轮提问（循环）
    │
    ├─ 可随时：揭示/隐藏模型身份（Toggle）
    ├─ 可随时：管理会话（三点菜单：重名名/删除）
    ├─ 可随时：单路退化（选择只保留 A 或 B）
    ├─ 可随时：切换模型（揭示后可用，下一轮生效）
    └─ 可随时：导出对话（JSON / Markdown）
    └─ 自动跳转：沉浸式互动快速跳转，预选 persona 自动进入 `agent_type` 对比
```

### 3.2 模型身份揭示策略

| 策略 | 说明 | 何时展示 | 实现 |
|------|------|----------|------|
| **投票后自动揭示** | 提交评分后，后端返回 `contestant_a/b` 信息 | 每轮投票完成后 | ✅ 默认行为 |
| **Toggle 手动揭示** | 顶栏 Eye/EyeOff 按钮 | 用户手动开关 | ✅ 可开可关 |
| **揭示后模型切换** | A/B 标题栏展示 `<select>` 下拉框 | 揭示状态时 | ✅ 下一轮生效 |

**为什么默认匿名？** 研究表明用户对知名品牌有认知偏差（如"Claude 就是更专业"），匿名化后投票更反映实际回复质量。

### 3.3 单路退化

| 条件 | 操作 | 效果 | 设计意图 |
|------|------|------|----------|
| ≥1 轮对话后 | 点击 A/B 标题栏的「选择」按钮 | 关闭另一侧，保留侧居中，标题变为"双镜对比（单路模式）" | 用户已有明确偏好，想继续深聊 |
| 退化后 | 继续对话 | 仅单模型生成，打分面板变为单侧自评 | 打分数据仍有价值 |
| 恢复 | 顶栏「恢复双镜」按钮 | 回到双栏模式 | 用户可能改变想法 |

---

## 4. 后端 API 完整参考

### 4.1 数据模型

```python
class ArenaContestant(BaseModel):
    backend: str = "deepseek"        # 模型后端标识（deepseek/grok/claude/gpt/...）
    agent_type: str = "neutral"      # 顾问类型（neutral/supportive/psychoanalytic）
    model: str = ""                  # 具体模型名（如 deepseek-ai/DeepSeek-V3.1）

class ArenaScoresSchema(BaseModel):
    empathy: int = 5                 # 共情 1-10
    depth: int = 5                   # 深度 1-10
    practicality: int = 5            # 实用 1-10
    professionalism: int = 5         # 专业 1-10
    fluency: int = 5                 # 流畅 1-10

class ArenaChatRequest(BaseModel):
    message: str                     # 用户消息
    arena_session_id: Optional[str]  # 已有 session ID（为空则新建）
    contestant_a: ArenaContestant    # A 方配置
    contestant_b: ArenaContestant    # B 方配置
    mode: str = "model"              # 对比模式（model/agent_type/perspective）
    use_rag: bool = True             # 是否注入 RAG 上下文

class ArenaVoteRequest(BaseModel):
    arena_session_id: str            # session ID
    round_index: int = -1            # 轮次索引（-1 = 最新一轮）
    vote: str                        # a_win | b_win | tie | both_good | both_bad
    scores_a: Optional[ArenaScoresSchema]
    scores_b: Optional[ArenaScoresSchema]
    remark: Optional[str]            # 评分备注（最多 240 字符）
```

### 4.2 端点清单

| 方法 | 路径 | 功能 | 返回关键字段 |
|------|------|------|-------------|
| `POST` | `/api/arena/chat` | 多轮对话：双路并发生成 | `arena_session_id, round_index, response_a, response_b, crisis_level, requires_vote` |
| `POST` | `/api/arena/vote` | 提交投票 + 五维评分 + 备注 | `status, contestant_a, contestant_b` |
| `GET` | `/api/arena/sessions` | 列出所有会话摘要 | `[{ id, title, rounds, communication_status, time }]` |
| `GET` | `/api/arena/session/{id}` | 获取会话详情（含全部轮次） | 完整 session JSON |
| `GET` | `/api/arena/stats` | Elo 排名（惰性重算） | `{ updated_at, total_battles, ratings }` |
| `PUT` | `/api/arena/sessions/{id}` | 重命名会话 | `{"message": "会话已重命名", "title": "..."}` |
| `DELETE` | `/api/arena/sessions/{id}` | 物理删除会话 | `{"message": "会话已删除"}` |
| `GET` | `/api/arena/leaderboard` | 排行榜别名 | 同 stats |
| `GET` | `/api/arena/summary` | 偏好统计 | `{ total, preference: { model: count } }` |
| `GET` | `/api/arena/query-stats` | Query 分层统计 | `{ categories, total }` |
| `PUT` | `/api/arena/sessions/{id}` | 重命名会话（v2.0 新增） | `{ status: "ok" }` |
| `DELETE` | `/api/arena/sessions/{id}` | 删除会话（v2.0 新增） | `{ status: "ok" }` |
| `GET` | `/api/arena/annotator-stats` | 标注质量分析（am-ELO） | `{ consistency_score, sessions_analyzed, details }` |

### 4.3 `/api/arena/chat` 处理流水线（8 步）

```
请求到达
  │
  ├─ 1. Session 管理
  │     ├─ 有 arena_session_id → _load_arena_session(id)
  │     └─ 无 → _create_arena_session(contestant_a, contestant_b, mode, use_rag)
  │           └─ ID 格式: arena-{uuid4.hex[:8]}，如 arena-27635ec8
  │
  ├─ 2. 危机检测（_crisis_detector.detect）
  │     ├─ 输入：当前消息 + session 最近 3 轮用户 query
  │     ├─ RED → 写入危机轮（response_a=response_b=固定文案）
  │     │        + 写入 crisis_archive/ + 返回 requires_vote=false
  │     ├─ YELLOW/ORANGE → 注入安全引导到 system_a 和 system_b
  │     └─ GREEN → 继续
  │
  ├─ 3. System Prompt 构建（A/B 独立构建，内容可能不同）
  │     ├─ 基础 prompt：CHAT_SYSTEM_PROMPTS[agent_type][mode]
  │     │   mode 映射: "deep" → "consult", 其他 → "listen"
  │     ├─ + 安全引导（if crisis >= YELLOW）
  │     ├─ + 测评注入（if 最新 assessment 的 inject_enabled=true）
  │     ├─ + RAG 上下文（if use_rag=true）
  │     │   └─ _build_rag_context(query, top_k=3, max_preview=500) → 截断至 800 字符
  │     ├─ + 早期对话摘要（if rounds > 12）
  │     │   └─ 旧轮次: 提取 query 前 60 字符 → "【早期对话摘要】"
  │     └─ + 关键事实（session.memory_facts，最近 10 条）
  │         └─ "【已确认的关键信息】\n- fact1\n- fact2\n..."
  │
  ├─ 4. 历史消息构建
  │     ├─ A 路: [{user: rd.query}, {assistant: rd.response_a}] × 最近 12 轮 + 当前 user 消息
  │     └─ B 路: [{user: rd.query}, {assistant: rd.response_b}] × 最近 12 轮 + 当前 user 消息
  │
  ├─ 5. 双路并发生成
  │     └─ asyncio.gather(
  │           loop.run_in_executor(None, _arena_generate_one(A)),
  │           loop.run_in_executor(None, _arena_generate_one(B)),
  │        )
  │     _arena_generate_one 内部:
  │       ├─ _get_generator(backend, model) → 获取 OpenAI-compatible client
  │       ├─ stream=True 流式收集所有 token
  │       ├─ 移除 <think>...</think> 标签（Grok 等 CoT 输出）
  │       └─ temperature 控制（thinking 模型不设 temperature）
  │
  ├─ 6. 禁用词后处理（_sanitize_with_crisis_guard）
  │     ├─ 扫描 A/B 回复中的 18 个禁用词
  │     └─ 命中 → 替换为"（此处表述不当，已移除）"
  │
  ├─ 7. 关键事实提取（_extract_memory_facts）
  │     └─ 从 A 和 B 的回复中提取日期事件、关系状态等
  │        → append 到 session.memory_facts（上限 20 条）
  │
  └─ 8. 保存 session + 返回响应
        ├─ session.rounds.append(new_round)
        ├─ session.title = query[:20]（首轮自动生成标题）
        └─ _save_arena_session(session)
```

---

## 5. 打分机制详解

> 这是双镜对比系统的核心。打分机制决定了收集的数据质量，直接影响 Elo 排名准确性和 KTO/DPO 训练效果。

### 5.1 打分面板触发条件

| 条件 | 打分面板行为 | `requires_vote` |
|------|-------------|-----------------|
| 正常双路生成完成 | 弹出，等待用户操作 | `true` |
| RED 危机中断 | **不弹出**，显示危机提示 | `false` |
| 用户点击「跳过」 | 关闭面板，标记 `submitted=true` | — |
| 已有未提交的上一轮打分 | 阻止发送新消息，提示"请先完成打分或跳过" | — |

### 5.2 三层打分结构

打分面板由三层组成，信息密度从粗到细：

```
┌────────────────────────────────────────────────────────────────┐
│                        打分面板                                  │
├────────────────────────────────────────────────────────────────┤
│                                                                │
│  Layer 1: 胜负投票（必选其一，默认 tie）                        │
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐      │
│  │ A 更好  │ │ B 更好  │ │  平局   │ │  都好   │ │  都差   │      │
│  └────────┘ └────────┘ └────────┘ └────────┘ └────────┘      │
│                                                                │
│  Layer 2: 五维评分（各维度 1-10 滑块，默认 5）                  │
│  ┌─────────────────────┐  ┌─────────────────────┐             │
│  │      A 的评分        │  │      B 的评分        │             │
│  │  共情  ━━━━○━━━━━ 7  │  │  共情  ━━━○━━━━━━ 6  │             │
│  │  深度  ━━━━━━━○━━ 8  │  │  深度  ━━━━━○━━━━ 6  │             │
│  │  实用  ━━━━○━━━━━ 7  │  │  实用  ━━━━━━○━━━ 7  │             │
│  │  专业  ━━━━━○━━━━ 7  │  │  专业  ━━━━━━━○━━ 8  │             │
│  │  流畅  ━━━━━━━━○━ 9  │  │  流畅  ━━━━━━○━━━ 7  │             │
│  └─────────────────────┘  └─────────────────────┘             │
│                                                                │
│  Layer 3: 评分备注（可选文本框）                                │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ 可记录本轮偏好原因，如：A 更具体、B 更共情               │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                │
│  ┌────────┐                              ┌──────────────────┐  │
│  │  跳过   │                              │   ✓ 提交评分     │  │
│  └────────┘                              └──────────────────┘  │
└────────────────────────────────────────────────────────────────┘
```

### 5.3 五维评分体系

#### 5.3.1 维度定义与评估标准

| 维度 | 键 | 1-3 分（差） | 4-6 分（中） | 7-10 分（好） |
|------|-----|-------------|-------------|--------------|
| **共情** | `empathy` | 忽视/误读情绪，机械回应 | 识别到情绪但共情不够深入 | 精准映射情感，用户感到被真正理解 |
| **深度** | `depth` | 表面应答，无洞察 | 有一定分析但缺乏新视角 | 多维度洞察，引用理论，识别深层模式 |
| **实用** | `practicality` | 空泛建议，无法执行 | 有方向但缺具体步骤 | 具体行动步骤 + 示例话术，可直接使用 |
| **专业** | `professionalism` | 使用诊断性语言，越界 | 基本规范但偶有疏漏 | 严格的非诊断表达，清晰的边界意识 |
| **流畅** | `fluency` | 逻辑混乱，断句奇怪 | 基本流畅但结构松散 | 条理清晰，语言自然精炼，阅读体验好 |

#### 5.3.2 为什么选择 1-10 而非 1-5

| 范围 | 优点 | 缺点 |
|------|------|------|
| 1-5 | 选择快速 | 区分度不足，中间选项("3"="一般")占比过高 |
| **1-10** | **区分度好**，允许精细对比 | 用户可能犹豫于 6 和 7 |
| 0-100 | 极致区分 | 决策成本过高，实际精度无意义 |

1-10 是人因研究中最常用的主观评分量表，兼顾区分度和认知负担。

#### 5.3.3 默认值与交互设计

| 参数 | 值 | 设计意图 |
|------|-----|----------|
| 默认值 | 5 | 滑块居中，避免锚定效应偏向高分或低分 |
| 最小值 | 1 | 不用 0，避免"零分"的挫败感联想 |
| 最大值 | 10 | 直觉化量表（"1 到 10 分你给几分"） |
| 输入方式 | Range slider | 连续拖动比点击按钮更快，适合批量打分 |
| 数值展示 | 滑块右侧实时显示当前值 | 明确反馈 |
| 维度 tooltip | 悬停显示评估焦点 | 降低认知负担 |

### 5.4 投票选项设计

| 值 | 标签 | 使用场景 | Elo 处理 | KTO/DPO 用途 |
|----|------|---------|----------|-------------|
| `a_win` | A 更好 | A 明显优于 B | A 胜 1.0，B 败 | chosen=A, rejected=B |
| `b_win` | B 更好 | B 明显优于 A | B 胜 1.0，A 败 | chosen=B, rejected=A |
| `tie` | 平局 | 难以区分 | 各计 0.5 | 跳过（无偏好信号） |
| `both_good` | 都好 | 两个都很满意 | 各计 0.5 | 跳过 |
| `both_bad` | 都差 | 两个都不满意 | 各计 0.5 | 可作为双 reject 负样本 |

**为什么有 5 种而非 3 种？** `both_good` 和 `both_bad` 虽然在 Elo 计算中等同于 `tie`，但在下游训练中有不同价值：`both_bad` 对应的 response 对可以作为负样本对（DPO 的 double-reject），`both_good` 则表示模型能力上限已达到用户期望。

### 5.5 评分备注

| 属性 | 值 |
|------|-----|
| 最大长度 | 240 字符 |
| 是否必填 | 否（可选） |
| 持久化 | session.rounds[i].remark + battles.jsonl.remark |
| 回显 | 历史轮次加载后，在 A 侧消息下方显示 |
| 前端占位 | "可记录本轮偏好原因，如：A 更具体、B 更共情" |

**备注的下游价值**：
- 人工审查偏好数据质量时，备注提供判断依据
- 可用于构建自然语言偏好数据集（user preference NL description）
- 辅助 am-ELO 标注质量评估（有备注的打分通常质量更高）

### 5.6 打分数据流（提交后发生了什么）

```
用户点击「提交评分」
    │
    ├─ 1. 前端构建 ArenaVoteRequest
    │     { arena_session_id, round_index, vote, scores_a, scores_b, remark }
    │
    ├─ 2. POST /api/arena/vote
    │     ├─ 加载 session
    │     ├─ 写入 rounds[idx].vote = "a_win"
    │     ├─ 写入 rounds[idx].scores = { a: {...}, b: {...} }
    │     ├─ 写入 rounds[idx].remark = "A 更具体"
    │     ├─ _save_arena_session(session)
    │     │
    │     ├─ 构建 battle entry（完整对局快照）
    │     │   包含: session_id, round_index, query, mode,
    │     │         contestant_a/b, response_a/b, vote, scores, remark,
    │     │         use_rag, timestamp
    │     ├─ 追加到 battles.jsonl（JSONL 格式，一行一条）
    │     │
    │     └─ 返回 { status: "ok", contestant_a: {...}, contestant_b: {...} }
    │
    ├─ 3. 前端接收响应
    │     ├─ 设置 contestants → 揭示模型身份
    │     ├─ 更新轮次状态: submitted=true, revealed=contestants
    │     ├─ Toast: "已记录第 N 轮评分 ✓"
    │     └─ 刷新侧边栏会话列表
    │
    └─ 4. 下次访问 /api/arena/stats 时
          └─ 惰性触发 Elo MLE 全量重算（§6）
```

### 5.7 跳过打分的处理

| 行为 | 后端 | Elo 影响 | battles.jsonl |
|------|------|----------|--------------|
| 用户点击「跳过」 | rounds[idx].submitted=true, vote=null | **无影响**（不写入 battles） | **不追加** |
| 用户不打分直接提问 | 被阻止（Toast 提示"请先完成打分或跳过"） | — | — |

这样保证 battles.jsonl 中的每条记录都有明确的投票意向，Elo 计算不会被"无意见"的数据污染。

---

## 6. Bradley-Terry Elo 排名算法

### 6.1 算法选型

采用 **Bradley-Terry 模型 + MLE（最大似然估计）全量重算**，而非传统增量 Elo（K-factor 方式）。

| 对比 | 传统增量 Elo | Bradley-Terry MLE |
|------|-------------|-------------------|
| 更新方式 | 每局后 K-factor 增量更新 | 全量对局矩阵重算 |
| 顺序依赖 | 对局顺序影响最终结果 | **无顺序依赖** |
| 收敛性 | 受 K 值选择影响 | MLE 全局最优 |
| 参考 | 国际象棋 Elo | **LMSYS Chatbot Arena** |
| 适用场景 | 大量用户实时对战 | 离线/准实时批量重算 |

**为什么选 BT-MLE？** 我们的场景是单用户多轮对局，数据量不大（几十到几百条），MLE 全量重算的计算成本可以忽略，但消除了增量 Elo 的顺序偏差问题。

### 6.2 数学原理

Bradley-Terry 模型假设选手 $i$ 赢 $j$ 的概率为：

$$P(i > j) = \frac{r_i}{r_i + r_j}$$

其中 $r_i$ 是选手 $i$ 的实力参数。MLE 通过最大化对局结果的似然函数求解最优 $r$：

$$\hat{r}_i = r_i \cdot \frac{\sum_j w_{ij}}{\sum_j n_{ij} \cdot \frac{r_j}{r_i + r_j}}$$

其中 $w_{ij}$ 是 $i$ 赢 $j$ 的次数，$n_{ij}$ 是 $i$ 和 $j$ 的总对局数。

### 6.3 MLE 求解实现

```python
def bt_mle(win_matrix, keys, n_iter=50):
    """
    Bradley-Terry 最大似然估计

    输入:
      win_matrix[i][j] = i 对 j 的胜场数
        - a_win → win_matrix[A][B] += 1.0
        - b_win → win_matrix[B][A] += 1.0
        - tie/both_good/both_bad → win_matrix[A][B] += 0.5, win_matrix[B][A] += 0.5
    输出:
      各选手的 Elo 评分（均值归一化到 1000）
    """
    r = {k: 1000.0 for k in keys}     # 初始：所有选手 1000
    for _ in range(n_iter):            # 迭代 50 次（通常 20 次即收敛）
        for i in keys:
            numer, denom = 0.0, 0.0
            for j in keys:
                if i == j: continue
                wij = win_matrix[i][j]  # i 赢 j 的次数
                wji = win_matrix[j][i]  # j 赢 i 的次数
                total = wij + wji       # i 与 j 的总对局数
                if total == 0: continue
                numer += wij                              # 分子：i 的总胜场
                denom += total * r[j] / (r[i] + r[j])    # 分母：期望胜场
            if denom > 0:
                r[i] = max(100, r[i] * numer / denom)     # 更新（下限 100 防退化）

    # 归一化：所有选手均值 → 1000
    scale = 1000.0 / (sum(r.values()) / len(r))
    return {k: round(v * scale) for k, v in r.items()}
```

### 6.4 对局矩阵构建

从 `battles.jsonl` 构建两类对局矩阵：

#### 主 Elo 矩阵（基于 vote）

| vote | A → B 列 | B → A 列 |
|------|---------|---------|
| `a_win` | +1.0 | — |
| `b_win` | — | +1.0 |
| `tie` | +0.5 | +0.5 |
| `both_good` | +0.5 | +0.5 |
| `both_bad` | +0.5 | +0.5 |

#### 五维 Elo 矩阵（基于 scores，每维度独立）

对于维度 $d$（如 `empathy`）：

| 条件 | A → B 列 | B → A 列 |
|------|---------|---------|
| `scores.a[d] > scores.b[d]` | +1.0 | — |
| `scores.a[d] < scores.b[d]` | — | +1.0 |
| `scores.a[d] == scores.b[d]` | +0.5 | +0.5 |
| 无 scores 数据 | 默认 5 vs 5 → +0.5 | +0.5 |

### 6.5 95% 置信区间

```
SE = 400 / √n       （n = 对局数，400 是 Elo 体系的标准差常数）
CI_95 = [Elo - 2×SE, Elo + 2×SE]
```

| 对局数 n | SE | 95% CI 宽度 | 排名可信度 |
|----------|-----|------------|-----------|
| 1 | 400 | ±800 | 极不可信 |
| 5 | 179 | ±358 | 低 |
| 10 | 127 | ±253 | 中等 |
| 25 | 80 | ±160 | 较可信 |
| 50 | 57 | ±113 | 可信 |
| 100 | 40 | ±80 | 高 |

前端在排行榜中展示 CI：差距 < 30 分视为实力相当，避免过度解读噪声。

### 6.6 冷启动处理

| 条件 | 处理 |
|------|------|
| 对局数 < 10 | 前端标记「未排名」（amber 色标签），MLE 仍参与计算 |
| 初始 Elo | 所有模型起始 1000（MLE 先验均值） |
| 新模型加入 | 自动 1000 起始，对局后迅速调整 |

### 6.7 重算触发机制

```python
_elo_battle_count_at_last_compute = 0  # 上次重算时的对局数

async def arena_stats():
    current_count = count_lines(BATTLES_FILE)
    # 惰性重算：仅当对局数变化时触发
    if current_count != _elo_battle_count_at_last_compute:
        _compute_elo_ratings()   # 全量 MLE 重算 → 写入 elo_ratings.json
        _elo_battle_count_at_last_compute = current_count
    # 直接返回缓存
    return load(ELO_FILE)
```

**为什么不实时重算？** MLE 是 O(n × m²) 复杂度（n=迭代次数，m=选手数），虽然计算量不大，但无需每次请求都重复。惰性策略保证了数据一致性的同时避免冗余计算。

---

## 7. 安全治理

### 7.1 四级危机检测接入

Arena 路径完整接入了与主对话相同的 `CrisisDetector`：

| 级别 | Arena 行为 | 技术实现 |
|------|-----------|---------|
| 🟢 GREEN | 正常双路生成 | 无额外处理 |
| 🟡 YELLOW | 向 A/B 双方 system prompt 注入安全引导 | `system_a += safety_prompt; system_b += safety_prompt` |
| 🟠 ORANGE | 同 YELLOW，措辞更强（引导至专业资源） | 同上，但注入文本包含热线号码 |
| 🔴 RED | **立即中断生成**，双方均返回危机干预固定文案 | `requires_vote=false`，写入 `crisis_archive/` |

### 7.2 回复禁用词后处理

```python
def _sanitize_with_crisis_guard(text):
    violations = _crisis_detector.check_response_prohibited(text)
    for v in violations:
        word = v.split("] ", 1)[-1]
        text = text.replace(word, "（此处表述不当，已移除）")
    return text
```

每次 A/B 回复生成后均经过此函数，确保 18 个禁用词（"诊断为""处方""你有心理疾病"等）不出现在用户面前。

### 7.3 危机归档结构

```json
{
  "session_id": "arena-xxxx",
  "message": "用户原始消息",
  "matched": ["匹配到的关键词"],
  "level": "RED",
  "timestamp": "2026-03-07T...",
  "source": "arena"
}
```

---

## 8. 长对话记忆机制

Arena 复用了沉浸式互动的三层记忆架构，但针对双路特点做了适配：

### 8.1 三层记忆概览

```
┌─────────────────────────────────────────────────────────────┐
│                    Arena 记忆架构                              │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Layer 1: 滑动窗口（最近 12 轮）                             │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  A 路: [user→rd.query, asst→rd.response_a] × 12    │    │
│  │  B 路: [user→rd.query, asst→rd.response_b] × 12    │    │
│  │  ← A/B 各自独立的历史，保证回复连贯性 →              │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                             │
│  Layer 2: 早期对话摘要（rounds > 12 时）                     │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  "【早期对话摘要】\n- 用户问: xxx\n- 用户问: yyy"   │    │
│  │  ← 注入到 A/B 双方 system prompt，共享相同摘要 →     │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                             │
│  Layer 3: 关键事实（跨轮次累积）                             │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  session.memory_facts (≤20 条)                      │    │
│  │  从 A 和 B 的回复中均提取，去重后合并               │    │
│  │  "【已确认的关键信息】\n- fact1\n- fact2"            │    │
│  │  ← 注入到 A/B 双方 system prompt →                  │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 8.2 与沉浸式互动的差异

| 方面 | 沉浸式互动 | Arena |
|------|-----------|-------|
| 历史消息 | 单路 user/assistant | **双路独立**（A 看 A 的历史，B 看 B 的） |
| 滑动窗口 | 20 条消息（MAX_RECENT_MESSAGES） | 12 轮（`max_recent=12`，每轮 2 条 = 24 条） |
| 事实提取来源 | 单个 assistant 回复 | A + B 双方回复均提取 |
| RAG 注入 | top_k=3 或 5，max_preview=500 或 1000 | top_k=3，max_preview=500，截断至 800 字符 |

---

## 9. 高级分析功能

### 9.1 偏好统计（`GET /api/arena/summary`）

从 `battles.jsonl` 统计各模型被选择（a_win/b_win）的总次数和占比。

```python
# 统计逻辑
for battle in battles:
    if vote == "a_win":
        wins[contestant_a.model] += 1
    elif vote == "b_win":
        wins[contestant_b.model] += 1
    # tie/both_good/both_bad → 不计入偏好
return { "total": len(battles), "preference": wins }
```

### 9.2 Query 分层统计（`GET /api/arena/query-stats`）

#### 9.2.1 自动分类算法

对每个 query 用关键词匹配计分，取最高分类别：

```python
_QUERY_CATEGORIES = {
    "emotional_support":        ["难过","伤心","焦虑","害怕","紧张","压力","崩溃","抑郁","孤独","失眠","委屈","哭","心情","情绪","不开心","烦"],  # 16 词
    "conflict_analysis":        ["吵架","冲突","矛盾","争吵","分歧","生气","愤怒","冷战","冷暴力","闹","不理","翻脸","怼"],                      # 13 词
    "advice_request":           ["怎么办","该怎么","建议","怎么改善","如何","应该","帮我","能不能","要不要","值不值"],                              # 10 词
    "relationship_exploration": ["喜欢","暧昧","表白","恋爱","感情","约会","相处","交往","追","聊天","话题"],                                    # 11 词
}

def _classify_query(query):
    scores = {cat: sum(1 for kw in keywords if kw in query) for cat, keywords in _QUERY_CATEGORIES.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "general"
```

| 类别 | 中文标签 | 关键词数 | 典型 query |
|------|---------|----------|-----------|
| `emotional_support` | 情绪支持 | 16 | "我最近很焦虑，失眠好几天了" |
| `conflict_analysis` | 冲突分析 | 13 | "我们又吵架了，她开始冷暴力" |
| `advice_request` | 建议请求 | 10 | "我该怎么回复她这条消息" |
| `relationship_exploration` | 关系探索 | 11 | "我们这算暧昧吗" |
| `general` | 一般对话 | — | 兜底 |

#### 9.2.2 统计输出

按 `类别 × 模型` 计算胜率：

```json
{
  "categories": {
    "emotional_support": {
      "label": "情绪支持",
      "battles": 15,
      "models": {
        "deepseek-ai/DeepSeek-V3.1": { "battles": 15, "wins": 9, "win_rate": 60.0 },
        "grok-4.1-thinking":          { "battles": 15, "wins": 5, "win_rate": 33.3 }
      }
    }
  }
}
```

### 9.3 标注质量分析（`GET /api/arena/annotator-stats`，am-ELO）

#### 9.3.1 设计动机

用户可能存在"随意打分"行为（全部给 5 分、不看回复直接投票）。am-ELO（Annotator Modeling for ELO）通过分析五维评分的分布模式检测这类行为。

#### 9.3.2 检测逻辑

对每个 session 的所有打分轮次做以下分析：

```python
for sid, score_list in session_scores.items():
    # 1. 计算 A/B 之间的维度差异
    diffs = [abs(s["a"][dim] - s["b"][dim]) for s in score_list for dim in dims]
    avg_diff = mean(diffs)

    # 2. 检查是否所有维度评分完全相同
    all_same = all(
        all(s["a"][d] == s["a"]["empathy"] for d in dims) and
        all(s["b"][d] == s["b"]["empathy"] for d in dims)
        for s in score_list
    )

    # 3. 分类
    if all_same and len(score_list) > 1:
        quality = 0.3   # 低质量：全维度相同
    elif avg_diff < 0.5:
        quality = 0.5   # 中等：差异过小
    elif avg_diff > 5:
        quality = 0.6   # 中等：差异过大（极端打分）
    else:
        quality = 1.0   # 正常
```

| 模式 | 质量分 | 含义 | 示例 |
|------|--------|------|------|
| 全维度相同 | 0.3 | 用户没有区分维度，可能随意打分 | A: 全 5 分，B: 全 5 分 |
| 差异 < 0.5 | 0.5 | 维度间差异过小，区分度不够 | A 和 B 每个维度差 0-1 分 |
| 差异 > 5 | 0.6 | 极端打分，可能对某模型有偏见 | A 全 10 分，B 全 3 分 |
| 正常 | 1.0 | 维度间有合理差异 | 共情 8/6，深度 7/8，实用 6/5 |

#### 9.3.3 整体一致性分数

所有 session 的质量分取平均：

```python
consistency_score = mean(quality for session in sessions)
```

前端展示：≥ 80% 绿色，≥ 50% 黄色，< 50% 红色。

---

## 10. 前端实现

### 10.1 `ArenaPage.tsx` 组件结构

```
ArenaPage
├── Sidebar（左侧 224px 宽，md 以下隐藏）
│   ├── 新建对比（按钮）
│   ├── Elo 排名（按钮 → showStats=true）
│   └── 对比历史列表
│       └── 每条: 标题 · 轮数 · 时间 · 点击 → handleLoadSession
│
├── Main（右侧主区域）
│   ├── TopBar（h-14，sticky top）
│   │   ├── 图标 + 标题（双镜对比 / 单路模式）
│   │   ├── RAG 开关 Toggle（hidden md:flex）
│   │   ├── 模式切换（倾听 motion.div / 咨询 motion.div）
│   │   ├── 揭示 Toggle（Eye/EyeOff，仅 arenaSessionId 存在时显示）
│   │   ├── 恢复双镜按钮（仅 soloSide 时显示）
│   │   └── 菜单 MoreHorizontal（fixed z-200 + 遮罩 z-199）
│   │       ├── 新建对比会话
│   │       ├── 导出对话（→ ExportDialog）
│   │       └── 切换顾问类型（PERSONAS map）
│   │
│   ├── Disclaimer（非诊断声明，amber 色卡片）
│   │
│   ├── Mobile Tab Switcher（< md：回复 A / 回复 B 两个 tab）
│   │
│   ├── Dual Chat Area（flex gap-2，soloSide 时 justify-center）
│   │   ├── Panel A（flex-1 或 max-w-4xl 居中）
│   │   │   ├── renderChatHeader('a')
│   │   │   │   ├── "A" 标签
│   │   │   │   ├── 匿名模型 / <select> 模型切换器（揭示后显示）
│   │   │   │   └── 「选择」按钮（≥1 轮且 soloSide===null 时显示）
│   │   │   └── renderMessages('a')
│   │   │       └── rounds.map → 用户气泡 + AI 回复 + 危机标签 + 备注回显 + 揭示标签
│   │   └── Panel B（同 A）
│   │
│   ├── Vote Panel（AnimatePresence，hasPendingUnsubmitted 时显示）
│   │   ├── 标题 "第 N 轮打分" + "五维评分范围：1-10 分"
│   │   ├── 投票按钮组 × 5（selectedVote 高亮）
│   │   ├── 五维评分 grid（soloSide ? 单列 : grid-cols-2）
│   │   │   └── DIMENSIONS.map → label + <input range> + 当前值
│   │   ├── 评分备注 textarea
│   │   └── 跳过 / ✓ 提交评分
│   │
│   └── Bottom Input（textarea + Send 按钮）
│       └── placeholder 根据状态变化
│
├── Toast（AnimatePresence，fixed bottom-24 z-200）
└── ExportDialog（open=showExport，arenaToExportData）
```

### 10.2 `ArenaStatsPage.tsx` 展示结构

```
ArenaStatsPage
├── 返回按钮 + 标题（N 场对局 · 更新于 xxx）
├── 排序 Tab（总分 / 共情 / 深度 / 实用 / 专业 / 流畅）
├── 排行榜表格
│   └── 每行：# · 模型名(冷启动标记) · Elo · 95%CI · 五维分(lg:table-cell) · 胜/负/平
├── 偏好统计（柱状图：各模型被选择次数和占比）
├── Query 分层统计
│   └── 按类别折叠卡片 → 每类内模型胜率水平条
└── 标注质量分析（am-ELO）
    ├── 整体一致性百分比 + 分析会话数
    └── 每个 session 质量条（绿/黄/红 + 质量标签）
```

### 10.3 关键状态变量

| 变量 | 类型 | 说明 |
|------|------|------|
| `step` / `rounds` | `Round[]` | 所有轮次数据（query, responseA/B, vote, scores, remark, crisisLevel） |
| `pendingVoteIdx` | `number` | 当前待打分的轮次索引（-1 = 无待打分） |
| `selectedVote` | `ArenaVote \| null` | 当前选中的投票选项 |
| `voteRemark` | `string` | 当前输入的评分备注 |
| `revealToggle` | `boolean` | 是否揭示模型身份 |
| `soloSide` | `'a' \| 'b' \| null` | 单路退化状态 |
| `contestants` | `{ a: Record, b: Record } \| null` | A/B 模型身份信息 |

---

## 11. 数据结构与持久化

### 11.1 Arena Session（`advisor_out/arena/sessions/arena-{uuid8}.json`）

```jsonc
{
  "id": "arena-27635ec8",
  "contestant_a": { "backend": "deepseek", "agent_type": "neutral", "model": "deepseek-ai/DeepSeek-V3.1" },
  "contestant_b": { "backend": "grok", "agent_type": "neutral", "model": "grok-4.1-thinking" },
  "mode": "model",
  "use_rag": true,
  "rounds": [
    {
      "round_index": 0,
      "query": "用户的提问",
      "response_a": "模型 A 的回复",
      "response_b": "模型 B 的回复",
      "vote": "a_win",           // null = 未投票（跳过）
      "scores": {
        "a": { "empathy": 8, "depth": 7, "practicality": 7, "professionalism": 8, "fluency": 9 },
        "b": { "empathy": 6, "depth": 6, "practicality": 5, "professionalism": 7, "fluency": 7 }
      },
      "remark": "A 的共情更到位，B 的分析偏表面",
      "crisis_level": "GREEN",
      "timestamp": "2026-03-07T12:21:57.355561"
    }
  ],
  "memory_facts": ["用户与前女友曾是情侣关系", "对方表现出回避型依恋特征"],
  "title": "你好，我今天心情还不错...",
  "created_at": "2026-03-07T12:21:45.663642",
  "updated_at": "2026-03-07T13:29:58.189101"
}
```

### 11.2 对局日志（`advisor_out/arena/battles.jsonl`）

每行一条 JSONL，是 Elo 计算和 KTO/DPO 训练的核心数据源：

```jsonc
{
  "arena_session_id": "arena-27635ec8",
  "round_index": 0,
  "query": "用户的提问",
  "mode": "model",
  "contestant_a": { "backend": "deepseek", "agent_type": "neutral", "model": "deepseek-ai/DeepSeek-V3.1" },
  "contestant_b": { "backend": "grok", "agent_type": "neutral", "model": "grok-4.1-thinking" },
  "response_a": "A 的完整回复...",
  "response_b": "B 的完整回复...",
  "vote": "a_win",
  "scores": {
    "a": { "empathy": 8, "depth": 7, "practicality": 7, "professionalism": 8, "fluency": 9 },
    "b": { "empathy": 6, "depth": 6, "practicality": 5, "professionalism": 7, "fluency": 7 }
  },
  "remark": "A 的共情更到位",
  "use_rag": true,
  "timestamp": "2026-03-07T12:54:19.038220"
}
```

### 11.3 Elo 排名快照（`advisor_out/arena/elo_ratings.json`）

```jsonc
{
  "updated_at": "2026-03-07T14:10:46.869889",
  "total_battles": 5,
  "ratings": {
    "deepseek::deepseek-ai/DeepSeek-V3.1": {
      "overall": 1032,
      "ci_95": [798, 1266],
      "empathy": 1045, "depth": 1060, "practicality": 1010,
      "professionalism": 1028, "fluency": 1050,
      "battles": 5, "wins": 3, "losses": 1, "ties": 1,
      "contestant": { "backend": "deepseek", "agent_type": "neutral", "model": "deepseek-ai/DeepSeek-V3.1" }
    }
  }
}
```

---

## 12. UX 功能清单

| 功能 | 状态 | 说明 |
|------|------|------|
| 左右分屏双路对话 | ✅ | 桌面端并排，移动端 Tab 切换 |
| 投票 + 五维评分 + 备注 | ✅ | 三层打分面板，AnimatePresence 弹出 |
| 对比历史侧边栏 | ✅ | 加载历史轮次和投票状态 |
| 模型身份揭示 Toggle | ✅ | Eye/EyeOff 可开可关 |
| 模型切换器 | ✅ | 揭示后标题栏下拉切换，下一轮生效 |
| 单路退化 + 恢复 | ✅ | 选择按钮 → 关闭一侧 → 恢复双镜 |
| 对话导出 | ✅ | JSON / Markdown 格式 |
| Elo 排行榜 | ✅ | 可按总分/五维排序，95% CI |
| 偏好统计 | ✅ | 柱状图展示各模型被选次数 |
| Query 分层统计 | ✅ | 5 类 × 模型胜率条形图 |
| 标注质量分析 | ✅ | am-ELO 一致性检测，质量分可视化 |
| 快速复用 | ✅ | 沉浸式互动 → 双镜对比预填问题 |
| 移动端适配 | ✅ | Tab 切换 A/B |
| 伦理声明 | ✅ | 顶部固定"非诊断非治疗" |
| 紧急求助 | ✅ | 侧边栏底部居中，tel: 直拨 |
| CJK 断行修复 | ✅ | MarkdownContent 智能合并被错误换行的中文 |
| 评分备注回显 | ✅ | 历史轮次 A 侧消息下方展示 |
| 危机轮标记 | ✅ | RED 轮次红色提示，不参与评分 |

---

## 13. 数据流向与下游消费

```
用户打分
    │
    ▼
POST /api/arena/vote
    │
    ├─ session JSON（追加 vote/scores/remark 到对应轮次）
    │
    └─ battles.jsonl（追加一行完整对局快照）
            │
            ├──▶ Elo 重算（Bradley-Terry MLE）
            │       ├─ 主 Elo：基于 vote
            │       ├─ 五维 Elo：基于 scores 逐维度胜负
            │       └─ 输出 → elo_ratings.json → 排行榜展示
            │
            ├──▶ KTO/DPO 偏好对齐训练（S8）
            │       ├─ vote=a_win → chosen=response_a, rejected=response_b
            │       ├─ vote=b_win → chosen=response_b, rejected=response_a
            │       ├─ tie/both_good → 跳过（无偏好信号）
            │       ├─ both_bad → 双 reject 负样本（特殊处理）
            │       └─ scores 可用于 reward model 训练（维度级偏好）
            │
            ├──▶ Query 分层统计
            │       └─ _classify_query(query) × 模型胜率 → 薄弱场景发现
            │
            ├──▶ am-ELO 标注质量
            │       └─ 低质量 session 的投票可降权
            │
            ├──▶ 维度短板分析
            │       └─ 某模型"深度"长期 < 对手 → 针对性优化 prompt
            │
            └──▶ 评分备注分析（未来）
                    └─ NLP 聚类偏好原因 → 自动标签
```

---

## 14. 配置参数与可调整项

| 参数 | 位置 | 默认值 | 说明 | 调整建议 |
|------|------|--------|------|----------|
| 初始 Elo | `bt_mle` | 1000 | MLE 先验 | 通常不需要改 |
| MLE 迭代次数 | `bt_mle` | 50 | 收敛轮数 | 选手 > 10 个时可增加到 100 |
| 冷启动阈值 | 前端 `ArenaStatsPage` | 10 场 | < 10 显示"未排名" | 可按需调整 |
| CI 差异阈值 | 文档约定 | 30 | 差距 < 30 视为相当 | 数据量大后可收紧到 20 |
| 滑动窗口 | `arena_chat` | 12 轮 | 最近保留轮数 | token 预算紧张时可降到 8 |
| RAG top_k | `arena_chat` | 3 | 检索条数 | consult 模式可增到 5 |
| RAG 最大字符 | `arena_chat` | 800 | 注入长度 | 不建议超过 1200 |
| memory_facts 上限 | `arena_chat` | 20 条 | 累积事实数 | 长期用户可增到 30 |
| 备注最大长度 | 前端 | 240 字符 | textarea maxLength | 根据用户反馈调整 |
| 评分默认值 | `defaultArenaScores()` | 各维度 5 | 滑块初始位置 | 保持 5（居中锚点） |
| 禁用词库 | `configs/crisis_keywords.yaml` | 18 词 | 诊断/治疗/处方类 | 根据实际 case 增补 |
| Query 分类词表 | `_QUERY_CATEGORIES` | 50 词 | 分类关键词 | 可根据数据分布调整 |

---

## 15. 已知限制与演进方向

| 限制 | 影响 | 严重度 | 计划解决方案 |
|------|------|--------|-------------|
| 非流式双路生成 | 用户需等待两个模型都生成完毕（平均 20-50s） | 中 | 改为双路 SSE 流式，各自独立渲染 |
| 单用户 Elo | 仅一个用户的投票数据，Elo 反映个人偏好而非客观质量 | 低 | 多用户后引入 am-ELO 加权 |
| 无视角碰撞模式 | 跨学科视角对比未实现 | 低 | Phase II S6 完成后接入 |
| server.py 单文件 | Arena 代码嵌在 3800+ 行文件中 | 中 | S4.1 拆分到 `routes/arena.py` |
| 五维权重固定等权 | 用户无法自定义"我更看重共情" | 低 | 设置页增加权重滑块 |
| Query 分类基于规则 | 关键词匹配有误分类风险 | 低 | 后续可用 LLM 做 zero-shot 分类 |
| 无导出偏好数据脚本 | KTO/DPO 构造需手动处理 battles.jsonl | 中 | S8 阶段提供 `export_preference_pairs.py` |

---

**文档版本**: v2.0
**创建时间**: 2026-03-07
**作者**: AI 工程团队
**关联文档**: 综合执行计划 v2（`research/big_plan/plan_v1/综合执行计划_v2.md`）, [modality_fields_and_models.md](modality_fields_and_models.md) §21, [safety_crisis_overview.md](safety_crisis_overview.md) §8
