# Roundtable v1.0 · Release Notes

> **发布范围**：圆桌讨论（Multi-Agent Roundtable Discussion）模块  
> **发布日期**：**2026-04-30（v1.0.0 · Day 7 收尾）** · 2026-04-23（v1.0.0-beta · Day 1-6 首版）  
> **版本号**：**v1.0.0** · 灰度候选  
> **代号**：Deluxe Build · Day 1 → Day 7 完整收口  
> **状态**：✅ **Backend + Frontend 功能闭环 · 视觉档 A 完成 · SLO 分层定稿 · 只读快照 · Moderator 跨轮记忆** · 可进入 Beta 灰度（D7.4.b/c）

---

## 1. 摘要 · TL;DR

`圆桌讨论` 是 Lens 项目在「关系咨询」纵深方向新增的**多 Agent 异构协作**能力，把传统单顾问 1:1 对话升级为**3 个流派顾问 + 1 位 Moderator** 的圆桌式群答。  
核心价值：

- **3 视角并发** · 用户一次提问 · 同时拿到「破局行动」「情绪拥抱」「深度觉察」三种立场的回应（流式输出）
- **Moderator 收束 + 跨轮记忆**（Day 7 D7.1.j 新增）· 中立角色对 3 路输出做「她在听到什么 / 不同视角 / 你可以尝试 / 仍然存疑 / Lens 寄语 / 局限声明」六段结构化总结 · Moderator 的 prompt **从 Day 7 起也注入 `_build_moderator_prior_context_block`** · 修复第 2 轮综合卡"失忆"bug
- **多轮闭环** · `done → 继续追问` 形态 A · 跨轮记忆压缩注入到下一轮 prompt（Tier-1/2/3 三档优先级 · token ≤ 2000）
- **只读快照恢复**（Day 7 D7.1.f 新增）· phase1/2/3 中途 session 点历史可**只读回顾**（`isReadOnlySnapshot=true`）· 不触发 SSE 重放污染
- **RAG 注入** · 追问时可从「聊天记录 / 知识手册」勾选片段注入到下一轮 prompt
- **安全护栏** · GuardedEmitter（chunk 级 sanitize）+ CrisisDetector（自杀 / 求助）+ BiasDetector（5 类 60 条偏见模式）+ Prompt-Injection XML 封装
- **降级可见**（Day 7 D7.1.k 新增）· Moderator LLM timeout → 规则 fallback 时前端显式 amber banner 说明"降级原因 + 建议"· 不再默默降级
- **可观测性** · `RoundtableAuditor` 11 类事件 JSONL 落盘 · 支持离线审计 / 性能分析 / 偏见统计
- **视觉人性化档 A**（Day 7 D7.2 新增）· 9 persona emoji 组合头像 + ModeratorCard SVG 桌角装饰 + Typing breathing glow + PersonaCard sparkle 悬停

---

## 2. 关键能力清单（Features）

### 2.1 Backend · 后端编排 + 流式 SSE

| 能力 | 模块 | 状态 |
|---|---|---|
| 3 phase pipeline 编排（phase1 并发 → phase2 交叉回应 → phase3 Moderator） | `roundtable_service.py::_run_pipeline` | ✅ |
| 异步 TaskGroup 并发 3 agent · 单 SSE 多路复用 | `_stream_one_agent_via_llm` / `subscribe` | ✅ |
| **GuardedEmitter** chunk 级 sanitize（≥16 字符或句末标点 flush） | `roundtable_service.py::GuardedEmitter` | ✅ |
| **ConfidenceWeightedAggregator** · phase3 按 `【置信度】0.0-1.0` 加权排序 | `roundtable_service.py::_render_phase3_table` | ✅ |
| **Echo Chamber 防御** · persona_bleaching 检测（缺本流派关键词时 retry） | `roundtable_service.py::_persona_bleaching_check` | ✅ |
| **Prompt-Injection XML 封装** · phase2 `peer_views` 标签化 + `peer_text_is_data` 提示 | `_render_phase2_context` | ✅ |
| **CrisisDetector 双检** · input check + 每 chunk + 每 full_text 三段防护 | `crisis_detector.py` + GuardedEmitter | ✅ |
| **BiasDetector** · 5 类 × 12 条 = 60 条规则 · sanitize 时按长度倒序匹配避免子串吞字 | `bias_detector.py` + `crisis_keywords.yaml::output_bias_patterns` | ✅ |
| LLM Moderator 主路（两段式 thinking + JSON）+ 规则 fallback | `_run_moderator_llm` / `_run_moderator_rule` | ✅ |
| Mock 路径（`ROUNDTABLE_USE_LLM=0` + `ROUNDTABLE_MODERATOR_LLM=0`）· 测试 / benchmark 用 | `_stream_one_agent_via_mock` | ✅ |

### 2.2 Backend · 多轮 / RAG 注入（Day 6 形态 A）

| 能力 | 模块 | 状态 |
|---|---|---|
| `Session.rounds[]` 归档 · 当前轮快照 · `round_index` 自增 | `core/models.py::RoundtableRoundSnapshot` | ✅ |
| `POST /sessions/{id}/continue` · done session 追问入口 · `inject_context` 字段透传 | `routes/roundtable.py::continue_roundtable_session` | ✅ |
| `GET /sessions/{id}` · 完整快照恢复（含 rounds[] · phase 状态 · phase2 缓存） | `routes/roundtable.py::get_roundtable_session` | ✅ |
| `POST /inject/preview` · RAG 预览端点 · BGE-M3 + 关键词 + rerank | `roundtable_service.py::build_inject_preview` | ✅ |
| **CrossRoundMemory** · Tier-1/2/3 三档优先级压缩 · char_budget=3800（≈2000 token） | `roundtable_memory.py::build_memory_block` | ✅ |
| 4-Step 预算策略：A 直塞 → B LIFO 丢 Tier-3 → C Tier-2 精简 → D 仅 Tier-1 强截 | `roundtable_memory.py::_assemble_within_budget` | ✅ |

### 2.3 Backend · 可观测性（Day 5 · D5.5）

`RoundtableAuditor` 单例 · Pydantic `AuditEvent` · JSONL 落盘到 `advisor_out/roundtable/audit/{YYYYMMDD}/{session_id}.jsonl` · 线程安全。

支持的 **11 类事件**：

```
session_created · phase_start · phase_end
agent_streaming_start · agent_done · agent_error
moderator_start · moderator_done
bias_hit · crisis_hit
memory_built · session_done
```

每事件携带：`session_id` / `persona_id` / `phase` / `round_index` / 自定义 metrics（duration_s / text_len / confidence / hits / token_estimate / truncated 等）。

### 2.4 Frontend · React + Vite + Tailwind v4 + shadcn

| 能力 | 模块 | 状态 |
|---|---|---|
| `RoundtablePage.tsx` setup 页（3 persona 选择 · 问题输入 · 历史 session 列表） | `pages/RoundtablePage.tsx` | ✅ |
| `RoundtableSessionPage.tsx` · 三栏并排 + Moderator 仪式感卡片 + 历史折叠 | `pages/RoundtableSessionPage.tsx` | ✅ |
| `useRoundtableStream` hook · EventSource + agent_id 分流 + 重连保护 | `hooks/useRoundtableStream.ts` | ✅ |
| `useRoundtableStore` Zustand · session / buffers / phase / moderator 状态机 | `stores/useRoundtableStore.ts` | ✅ |
| `InjectionDrawer.tsx` · 追问时勾选 RAG 片段（聊天记录 / 知识手册） | `components/roundtable/InjectionDrawer.tsx` | ✅ |
| `FollowUpComposer.tsx` · 追问输入框 + 注入按钮 + 发送 | `components/roundtable/FollowUpComposer.tsx` | ✅ |
| `SessionHistoryList.tsx` · 历史 session hydrate（done + Day 7 起非 done 只读） | `components/roundtable/SessionHistoryList.tsx` | ✅ |
| Moderator 流式思考打字机 + 折叠（CoT 行为透明化）+ 降级原因 amber banner（D7.1.k） | `components/roundtable/ModeratorCard.tsx` | ✅ |
| 置信度三档视觉（高 / 中 / 低 不同色环 + 字号） | `components/roundtable/AgentMessage.tsx` | ✅ |
| Phase 过渡 1500ms delay + scrollIntoView + 其他卡片 `opacity-40 grayscale` 淡出 | `components/roundtable/PhaseBanner.tsx` | ✅ |
| 9 persona 完整定义（id/name/color/icon/**emoji** · 与后端 prompts.yaml 同步） | `data/personas.ts` | ✅ |
| Mobile 375px 响应式 + 暗色模式（继承 Lens 主题） | 全栈 | ✅ |
| `prefers-reduced-motion` 三档 CSS 兜底 + `useReducedMotion` hook（D7.1.i） | `index.css` + `hooks/useReducedMotion.ts` | ✅ |

### 2.5 Day 7 新增能力 · 收尾 + 视觉档 A

| ID | 能力 | 关键文件 | Section |
|---|---|---|---|
| **D7.1.f** | 非 done session 只读快照模式 · `isReadOnlySnapshot` state + amber banner + SSE 挂起 | `stores/useRoundtableStore.ts` + `pages/RoundtableSessionPage.tsx` | §79 |
| **D7.1.j** | Moderator 跨轮记忆注入 · `_build_moderator_prior_context_block` · YAML 新增 `{prior_context_block}` 占位符 | `services/roundtable_service.py` + `configs/roundtable_prompts.yaml` | §77 |
| **D7.1.k** | Moderator 降级可见提示条 · 3 层（timeout 放宽 / `fallback_reason` 全链路 / 前端 banner） · 分 `session.deep_mode` 选 timeout（180s/240s） | `services/roundtable_service.py` + `stores/useRoundtableStore.ts` + `ModeratorCard.tsx` | §78 |
| **D7.1.c** | 真 LLM benchmark + SLO 分层定稿 · `--real-llm --backend <name>` 双模式 · Claude 单线 10/10 · p95 = 5.82s PASS | `scripts/benchmark_roundtable.py` | §83 |
| **D7.2.a** | 9 persona emoji 组合 icon（🧭🤗🔍💗🌳🌐🤔♟️🏮） | `data/personas.ts` | — |
| **D7.2.b** | AgentMessage/PersonaCard 头像增强 · emoji 主 + Lucide 徽标 | 多组件 | — |
| **D7.2.c** | ModeratorCard 桌面 SVG 装饰 · 内联 600B · amber→rose 渐变 | `ModeratorCard.tsx:74-119` | — |
| **D7.2.d** | Typing breathing glow · `.mp-breathe-glow` + accentText per persona | `index.css:302-331` + `AgentMessage.tsx` | — |
| **D7.2.e** | PersonaCard 悬停 sparkle · lucide Sparkles + animate-pulse + reduced-motion 降级 | `PersonaCard.tsx:64-77` | — |

---

## 3. 架构总览

```
┌──────────────────────────────────────────────────────────────┐
│  Frontend · React + Vite + Tailwind v4 + Zustand            │
│   RoundtablePage  →  RoundtableSessionPage  ←  EventSource  │
│   useRoundtableStream + useRoundtableStore                  │
└──────────────────────────┬───────────────────────────────────┘
                           │ POST /sessions  GET /stream/{id}
                           │ POST /sessions/{id}/continue
                           │ POST /inject/preview
                           ▼
┌──────────────────────────────────────────────────────────────┐
│  L1 · API Gateway · FastAPI (main.py · routes/roundtable.py)│
└──────────────────────────┬───────────────────────────────────┘
                           ▼
┌──────────────────────────────────────────────────────────────┐
│  L2 · 编排 · roundtable_service.py                          │
│   - create_session / continue_session                       │
│   - subscribe → SSE async generator                         │
│   - _run_pipeline (phase1 → phase2 → phase3)               │
└──────────────────────────┬───────────────────────────────────┘
                           ▼
┌──────────────────────────────────────────────────────────────┐
│  L3 · 安全 · prompt 拼装 · 跨轮记忆                         │
│   - GuardedEmitter (chunk-level sanitize)                  │
│   - CrossRoundMemory (Tier-1/2/3 压缩)                     │
│   - PromptInjection XML 封装                                │
└──────────────────────────┬───────────────────────────────────┘
                           ▼
┌──────────────────────────────────────────────────────────────┐
│  L4 · 检测 / 防御                                            │
│   - CrisisDetector (input + chunk + full_text)             │
│   - BiasDetector (5 类 × 12 条 · 软化替换)                  │
│   - ConfidenceWeightedAggregator (phase3 加权)              │
└──────────────────────────┬───────────────────────────────────┘
                           ▼
┌──────────────────────────────────────────────────────────────┐
│  L5 · 模型层                                                 │
│   - Phase 1/2 → 9 persona heterogeneous LLM call            │
│   - Phase 3 → LLM Moderator (主) + 规则 fallback            │
│   - Backends: gemini · kimi · deepseek · qwen · glm · ...   │
└──────────────────────────┬───────────────────────────────────┘
                           ▼
┌──────────────────────────────────────────────────────────────┐
│  L6 · 可观测性                                               │
│   - RoundtableAuditor (11 类事件 · JSONL)                    │
│   - advisor_out/roundtable/audit/{YYYYMMDD}/{id}.jsonl      │
└──────────────────────────────────────────────────────────────┘
```

---

## 4. API 端点一览

| Method | Path | 用途 | 入参核心字段 |
|---|---|---|---|
| `POST` | `/api/roundtable/sessions` | 创建 session（不立即触发 pipeline） | `personas[3]` · `question` · `parent_id?` · `backend?` |
| `GET` | `/api/roundtable/stream/{session_id}` | SSE 订阅 + 首次订阅触发 pipeline | — |
| `POST` | `/api/roundtable/sessions/{id}/interrupt` | 中断 pipeline（取消所有 active tasks） | — |
| `GET` | `/api/roundtable/sessions` | 列出所有 session 摘要（按 updated_at 倒序） | — |
| `GET` | `/api/roundtable/sessions/{id}` | 完整快照（含 rounds[] · phase 状态） | — |
| `POST` | `/api/roundtable/sessions/{id}/continue` | done session 追问 | `question` · `inject_context?` |
| `POST` | `/api/roundtable/inject/preview` | RAG 注入预览 | `query` · `modes[]` · `top_k` |

### SSE 协议

```
data: {"type":"agent_status","agent_id":"neutral","phase":"phase1","status":"typing"}
data: {"type":"agent_chunk","agent_id":"neutral","phase":"phase1","delta":"听"}
data: {"type":"agent_done","agent_id":"neutral","phase":"phase1","confidence":0.78}
data: {"type":"phase_advance","phase":"phase2"}
data: {"type":"moderator_chunk","delta":"..."}
data: {"type":"moderator","content":{"seen":"...","angles":[...],"tries":[...],"doubts":[...],"lens":"...","limit":"..."}}
data: {"type":"done"}
data: [DONE]
```

---

## 5. 测试覆盖

**后端**（pytest · Day 7 复核 **210/210** 全绿 · 0.57s）：

| 模块 | 测试文件 | Cases | 关键场景 |
|---|---|---|---|
| 主编排 / phase pipeline / DAG / Moderator 跨轮 | `tests/test_roundtable_service.py` | **54** | phase1 并发 / peer_views 注入 / moderator JSON 解析 / 规则 fallback / inject_context 透传 / 历史轮恢复 / `_build_moderator_prior_context_block` (Day 7 D7.1.j) |
| 审计 / JSONL / 并发 | `tests/test_roundtable_audit.py` | **20** | 11 事件类型 / 50 线程 × 20 写入 / env override / 截断容错 |
| 跨轮记忆 / 三档压缩 | `tests/test_roundtable_memory.py` | **15** | 空轮 / 单轮 / 双轮 / 五轮 LIFO / 紧预算 / persona 隔离 |
| 偏见检测 / 5 类规则 | `tests/test_bias_detector.py` | **42** | 5 类全覆盖 / 长优先 / 单例 / 20 偏见样本 100% 召回 + 20 清洁样本 0 误伤 |
| GuardedEmitter / chunk flush | `tests/test_guarded_emitter.py` | **51** | 阈值累积 / 句末标点 / sanitize 前置 / finalize 残留 / audit 透传 |
| Prompt YAML 契约 + 情境感知 + Moderator 占位符 | `tests/test_roundtable_prompts.py` | **20** | 9 personas / neutral 【情境感知】5 条 / phase1 规则 #4 / phase2 同步 / Moderator `{prior_context_block}` 契约（D7.1.j）|
| **后端总计** | | **210** | **全绿 · 0.57s**（2026-04-30 23:30 复核 · 含 D7.1.j+ 跨轮记忆降级路径 8 新测试） |

**前端测试**（vitest · **70/70** 全绿 · 含 D7.1.j++ RoundtableRouter 6 新测试）：

| 模块 | 测试文件 | Cases | 状态 |
|---|---|---|---|
| `dispatchRoundtableEvent` 事件分流 | `frontend/src/hooks/__tests__/dispatchRoundtableEvent.test.ts` | — | ✅ |
| `useRoundtableStore` 状态机 + `isReadOnlySnapshot` | `frontend/src/stores/__tests__/roundtableStore.test.ts` | 16 (+9 Day 7) | ✅ |
| RAG 注入流 | `frontend/src/components/roundtable/__tests__/injection.test.ts` | — | ✅ |
| reduced-motion hook | `frontend/src/hooks/__tests__/useReducedMotion.test.ts` | — | ✅ |
| `RoundtableRouter` 路由逻辑（D7.1.j++） | `frontend/src/__tests__/RoundtableRouter.test.tsx` | 6 | ✅ |
| **前端总计** | | **70** | **全绿 · 2026-04-30 23:55 复核 · 含 D7.1.j++ 路由 + D7.1.j+ banner 文案** |

**E2E 验证脚本**：

- `scripts/verify_roundtable_e2e.py` — 真 LLM · 3 轮端到端（Day 4 收尾 · D7.1.j 复验）
- `scripts/verify_roundtable_memory_e2e.py` — CrossRoundMemory 3 轮模拟 · **8/8 checks 全绿**
- `scripts/benchmark_roundtable.py` — **Day 7 升级为双模式**：`--real-llm --backend <name>` 启用真 LLM · 自动 load `.env.advisor` · SLO 自适应

**性能 SLO · 三层分层定稿**（Day 7 · Section 83）：

| 层 | 路径 | 首 token p95 SLO | 最近数据 | 状态 |
|:---|:---|:---:|:---:|:---:|
| **L1** | Mock pipeline 基线（CI 回归） | ≤ **3s** | 1.03-1.16s | ✅ PASS |
| **L2** | 真 LLM 单 backend（Claude via OpenAI-compatible proxy） | ≤ **6s** | **5.82s** (10/10 runs) | ✅ PASS |
| L3 | 真 LLM 多 backend 并发 | ≤ 4s | — | ⏳ 待换直连 key 后复测 |

**L2 详细数据**（`--real-llm --backend claude --runs 10 --concurrency 1` · 2026-04-30）：

| 指标 | p50 | p95 | p99 | avg |
|---|---|---|---|---|
| first_token | 4.77s | **5.82s** | 6.20s | 4.92s |
| session_done | 63.6s | 70.1s | 70.5s | 61.9s |
| agent_chunks/run | — | — | — | 55-107 |

> 结果 JSON：`@<PROJECT_ROOT>/advisor_out/benchmarks/roundtable_latency_c1_20260430_163113.json`

---

## 6. 配置文件清单

| 文件 | 行数 | 用途 |
|---|---|---|
| `configs/roundtable_prompts.yaml` | 288 | 9 persona phase1/2/3 system prompt + Moderator prompt + DISCOURSE_BANLIST + ETHICS_BANLIST |
| `configs/crisis_keywords.yaml` | 268 | CrisisDetector 触发词 + `output_bias_patterns`（5 类 × 12 条 · BiasDetector 数据源） |

### 关键 ENV 变量

```bash
# ─── Backend · Pipeline 开关 ───
ROUNDTABLE_USE_LLM=1                     # 0 = mock 文本（测试 / benchmark）
ROUNDTABLE_MODERATOR_LLM=1               # 0 = 规则 Moderator
ROUNDTABLE_BACKEND=gemini                # 默认 backend（fallback 链 gemini → kimi → deepseek）
ROUNDTABLE_FLUSH_THRESHOLD=16            # GuardedEmitter chunk 字符阈值
ROUNDTABLE_AUDIT_ROOT=advisor_out/roundtable/audit   # 审计落盘根

# ─── Backend · Moderator Timeout（Day 7 · D7.1.k 变更）───
ROUNDTABLE_MODERATOR_TIMEOUT=180         # 普通 Moderator · 90s → 180s
ROUNDTABLE_DEEP_MODERATOR_TIMEOUT=240    # deep_mode 专属 · 新增

# ─── Backend · Benchmark（Day 7 · D7.1.c 新增）───
ROUNDTABLE_SLO_P95=6.0                   # 真 LLM 默认 6s · mock 默认 3s · 自适应
ROUNDTABLE_BENCH_FIRST_TOKEN_TIMEOUT=20  # 真 LLM 模式自动覆盖
ROUNDTABLE_BENCH_TOTAL_TIMEOUT=120       # 真 LLM 模式自动覆盖

# ─── Frontend ───
VITE_USE_MOCK=false                      # 切换 mock / 真后端
```

---

## 7. 已知风险 · 限制 · Trade-off

### 7.1 安全护栏的「最后一里」

- **Token 级泄漏窗口** · GuardedEmitter 阈值 16 字符 · 极端情况下「禁止词跨 chunk 边界」可能短暂可见后被替换；缓解措施：CrisisDetector 在每 chunk + full_text 双检 · BiasDetector 在 flush 前置；监控 `bias_hit / crisis_hit` 事件比率
- **BiasDetector 规则集** · 当前 60 条覆盖 5 类高频模式 · 可能漏掉新颖措辞；建议每周 review `audit/{YYYYMMDD}/*.jsonl` 中的 bias_hit 事件，季度更新规则
- **Prompt-Injection** · phase2 已 XML 封装 + `peer_text_is_data` 提示 · 仍建议在前 50 场会话人工抽样 5% 审计

### 7.2 性能与扩展性

- **内存态 session 存储** · 当前 `roundtable_service._sessions: dict` 是单进程内存字典 · **重启即丢**；多 worker 部署需要共享存储（Redis / SQLite） · 推迟到 V2
- **RAG 注入延迟** · `inject/preview` 调用 BGE-M3 + rerank · 首次冷加载 2-3s · 后续 < 200ms · 已通过 lazy init 优化
- ~~**真 LLM 首 token p95 SLO 需复测**~~ · ✅ **已完成 2026-04-30（D7.1.c / Section 83）** · SLO 三层分层定稿（L1 mock ≤ 3s ✅ / L2 单 backend ≤ 6s · Claude 5.82s ✅ / L3 多 backend 并发 ≤ 4s ⏳ 待直连 key）
- **代理生态脆弱性**（新 · 2026-04-30 观察） · OpenAI-compatible proxy / jiuuij.de5 / backup provider 等代理在过去 4 天内（Section 80 → Section 83）陆续限流 / 下架 / 吊销 key · **只剩 Claude 单线稳定**；生产前必须：① 至少申请 1 个直连 provider key（Gemini AI Studio Free Tier / Kimi 直连 / OpenAI Tier 1）② 避免多 backend 共用同一 key · 以免一起失效

### 7.3 多轮 / DAG / 历史

- ~~**非 done session hydrate 受限**~~ · ✅ **已完成 2026-04-25（D7.1.f）** · `isReadOnlySnapshot=true` 时前端显式 amber banner + SSE 挂起 · 不会事件重放污染
- **形态 B · DAG 分叉未实现** · 当前 `interrupt` 端点仅取消 task 不创建 child session · 形态 A 已覆盖 ~90% 追问场景，形态 B 推迟到 V2
- **CrossRoundMemory 自适应** · 当前阈值固定（T1=600/T2=200/T3=160 char）· 长对话场景（>10 轮）建议 V2 引入「滚动摘要」（compress oldest 3 → summary）
- ~~**Moderator 跨轮无记忆 bug**~~ · ✅ **已修复 2026-04-24（D7.1.j）** · `moderator_llm_prompt` + `deep_moderator_llm_prompt` 加 `{prior_context_block}` 占位符 · `_build_moderator_prior_context_block` 专供 Moderator 视角（Tier-1 完整 seen/angles/lens + Tier-2 一行摘要）
- ~~**Moderator 降级路径跨轮无记忆 bug**~~ · ✅ **已修复 2026-04-30（D7.1.j+ · 灰度前实战发现）** · 23:00 代理 RPM 限流时 Moderator 退回 `_build_rule_moderator()` · 而该函数原本是**完全静态模板**（`tries / lens` 写死）· 第 2/N 轮看起来无记忆；修复：rule template 也读 `session.rounds[-1].moderator` · 在 `seen / tries[0] / doubts[0] / lens` 注入上轮承接段（"上一轮我们建议过 ... ；这是我们的第 N 轮陪伴"）· 8 个新 unit test 覆盖首轮兼容 / 二轮承接 / 三轮 round_n / 上轮 moderator 缺失兜底
- ~~**Continue 第 2 轮 SSE 未重连 bug**~~ · ✅ **已修复 2026-04-30（D7.1.j++ · E2E 测试发现）** · 用户点 FollowUpComposer 追问后 `archiveCurrentRoundAndReset` 把 `currentPhase` 设为 `'setup'` · 而 `@<PROJECT_ROOT>/frontend/src/App.tsx::RoundtableRouter` 原先仅按 `currentPhase === 'setup'` 跳回 `RoundtablePage` · `RoundtableSessionPage` 被 unmount → `useRoundtableStream` cleanup → SSE 关闭 → 第 2 轮 phase pipeline 永不启动；修复：Router 加 `sessionId` 判断 · `sessionId` 仍存在时保持 SessionPage；6 个新 vitest 测试覆盖初始/开始/continue/reset/done/phase2 五种转换分支
- ~~**Fallback banner 文案过时**~~ · ✅ **已修复 2026-04-30（D7.1.j+ 配套）** · `ModeratorCard::explainFallbackReason()` 原先写死"无跨轮记忆" · D7.1.j+ 后规则模板已有记忆 · 文案误导；修复：按 roundIndex 分支文案（首轮"无历史可承接" / 多轮"已自动承接上轮综合"）· `RoundtableSessionPage` 调用处传 `roundIndex` prop

### 7.4 视觉 / 交互

- ~~**`prefers-reduced-motion` 兜底**~~ · ✅ 已完成 2026-04-23（D5.4 / D7.1.i）· CSS 三档兜底 + `useReducedMotion` hook + 打字机 / mock streaming / breathing glow / sparkle 全路径感知
- ~~**9 persona 头像**~~ · ✅ 已完成 2026-04-23（D7.2.a/b）· emoji 组合头像 + Lucide 徽标 · 零资产成本；深度 MP 卡通立绘推迟到档 B（D7.3 · 需 Beta 反馈触发）
- **Playwright E2E** · 仅 vitest unit · Playwright 3 场景（正常流 / 打断 / mobile 375px）推迟到 D5.7
- **D7.1.f E2E 浏览器验收** · 只读快照 banner 已通过 vitest 64/64，但浏览器实机"点历史 phase2 中途 session → 进页面看 banner → 点开新会话按钮"串联**尚未用户实机验收** · 灰度前建议手动点 5 分钟

### 7.5 模型 & 成本

- **9 persona 同质化风险** · 9 个 prompt 在同一 backend 时风格易趋同 · 建议 phase1 用异构 backend（gemini / kimi / deepseek 各承一类）· 但 **2026-04-30 代理生态现状下只有 claude 可用** · 异构暂无法做到 · 待直连 key 恢复后启用
- **Token 成本** · 单场 3 phase ≈ 3-5k input + 1-2k output × 3 agent + Moderator ≈ **18-25k tokens / session** · 多轮场景 N 轮线性增长
- **Moderator thinking 模型长耗时** · Claude/Gemini thinking 深度模式首 token 可到 10-15s · 已通过 `ROUNDTABLE_MODERATOR_TIMEOUT=180s` + `ROUNDTABLE_DEEP_MODERATOR_TIMEOUT=240s` + 前端 amber banner 可见降级 · 非阻塞体验

---

## 8. V2 候选 / 未实现项

### Day 7 灰度前 · 已全部收口 ✅

- [x] **D7.1.a** GuardedEmitter（随 D4.1 · 2026-04-22）
- [x] **D7.1.b** BiasDetector 60 条规则（随 D4.7 · 2026-04-22）
- [x] **D7.1.c** 真 LLM 并发 benchmark + SLO 三层分层定稿（2026-04-30 · Section 83）
- [x] **D7.1.d** RoundtableAuditor 11 事件（随 D5.5 · 2026-04-23）
- [x] **D7.1.e** 偏见样本回归测试（随 D5.2b · 2026-04-22）
- [x] **D7.1.f** 非 done session 只读快照模式（2026-04-25 · Section 79）
- [x] **D7.1.g** CrossRoundMemory 压缩精修（提前 · 随 D4.8 · 2026-04-23）
- [x] **D7.1.h** neutral 顾问【情境感知】三档分支（2026-04-23）
- [x] **D7.1.i** `prefers-reduced-motion` 三档兜底（2026-04-23 · D5.4 / D7.1.i）
- [x] **D7.1.j** Moderator 跨轮记忆注入（2026-04-24 · Section 77）
- [x] **D7.1.k** Moderator 降级可见提示条（2026-04-24 · Section 78）
- [x] **D7.2.a/b/c/d/e** 视觉人性化档 A 全部 5 项（2026-04-23 到 2026-04-30）

### 灰度中 / 待开启

- [ ] **D7.4.b** 挑选 10 个 Beta 用户 · 开放 RoundtablePage 入口 · **下一步**
- [ ] **D7.4.c** 观测指标：完成率 / 多轮深度 / RAG 使用率 / 首 token p95 / crisis+bias 命中率
- [ ] **D7.1.f E2E 实机验收** · 5 分钟人工点检快照 banner 串联
- [ ] **D5.7 Playwright E2E** · 3 场景（正常流 / 打断 / mobile 375px）· 需 `@playwright/test` 安装 ≈ 200MB

### 灰度后 · 按需启动

- [ ] **D7.3 档 B · MP 深度卡通立绘**（需 ≥ 10 Beta 用户反馈"还想更活泼"触发 · 3-5 天）
  - D7.3.a Magic Patterns 生成 9 persona 卡通立绘候选
  - D7.3.b 挑选 + 微调 + code review
  - D7.3.c 集成到 `PersonaCard / AgentMessage / ModeratorCard`
  - D7.3.d 动效联调（Lottie / Framer Motion）
  - D7.3.e visual regression + a11y 检查

### V2 候选（长期）

- [ ] **形态 B · DAG 分叉** · `interrupt` 创建 child session · `inherit_mode = refine|replace`
- [ ] **持久化 session 存储** · Redis / SQLite · 支持多 worker
- [ ] **CrossRoundMemory 滚动摘要** · 10+ 轮场景压缩最旧 N-3 轮为 ≤300 字摘要
- [ ] **Shadow Rater UI** · 已取消（被主路 LLM Moderator 取代）· 如需 A/B 实验再启
- [ ] **跨场景 persona 学习** · 把高 confidence 的回应反哺到训练集
- [ ] **多语言扩展** · 当前仅中文 prompt · 英文版需要重新调 banlist
- [ ] **可视化偏见仪表盘** · 把 `bias_hit / crisis_hit` 事件聚合成 Grafana / Web 看板
- [ ] **直连 provider key 迁移** · 替换 OpenAI-compatible proxy 代理 · 跑 L3 SLO（p95 ≤ 4s）复测

---

## 9. 部署 / 升级注意事项

### 9.1 Backend 启动

```bash
# 进入 conda 环境
conda activate wechatDHA

# 加载 LLM 密钥
source local_secrets/.env.advisor

# 启动 FastAPI
cd <PROJECT_ROOT>
uvicorn scripts.advisor.api.main:app --host 0.0.0.0 --port 8787 --reload
```

### 9.2 Frontend 启动

```bash
cd frontend
npm install
VITE_USE_MOCK=false npm run dev   # 接真后端
# 或
VITE_USE_MOCK=true npm run dev    # 用 mock 数据
```

### 9.3 验证清单

```bash
# 1. 全量回归（210 backend tests · 0.57s · 2026-04-30 复核 · 含 D7.1.j+）
conda run -n wechatDHA python -m pytest \
  tests/test_roundtable_service.py \
  tests/test_roundtable_audit.py \
  tests/test_roundtable_memory.py \
  tests/test_bias_detector.py \
  tests/test_guarded_emitter.py \
  tests/test_roundtable_prompts.py -q

# 2. 前端回归（64 vitest · 2026-04-25 复核）
cd frontend && npm test -- --run

# 3. CrossRoundMemory E2E
conda run -n wechatDHA python scripts/verify_roundtable_memory_e2e.py

# 4. mock 路径并发 benchmark（L1 SLO · p95 ≤ 3s）
conda run -n wechatDHA python scripts/benchmark_roundtable.py \
  --runs 20 --concurrency 1

# 5. 真 LLM benchmark（L2 SLO · p95 ≤ 6s · 需 .env.advisor）
conda run -n wechatDHA python scripts/benchmark_roundtable.py \
  --real-llm --backend claude --runs 10 --concurrency 1

# 6. 真 LLM E2E · 3 轮多轮（需 backend 在 :8787）
conda run -n wechatDHA python scripts/verify_roundtable_e2e.py
```

### 9.4 监控建议

- **每日 grep**：`grep -c '"event_type":"crisis_hit"' advisor_out/roundtable/audit/$(date +%Y%m%d)/*.jsonl`
- **每周回顾**：`bias_hit` 事件采样 50 条人工 review · 决定是否更新 `crisis_keywords.yaml::output_bias_patterns`
- **每月**：`memory_built` 事件统计 truncated 比率 · 若 > 10% 考虑 V2 滚动摘要
- **Day 7 新增 · Moderator fallback 监控**：`grep -c '"fallback_reason"' advisor_out/roundtable/audit/$(date +%Y%m%d)/*.jsonl` · 若 > 10% 说明 LLM timeout 严重 · 需排查代理或换 key

---

## 10. 致谢 · 时间线

```
Day 1 (前端 P1) ─ 2026-04-XX    脚手架 + 9 组件移植
Day 2 (前端 P2) ─ 2026-04-XX    路由 + mock 流 + Phase 过渡动画
Day 3 (后端 P1) ─ 2026-04-XX    基础 pipeline + SSE + 9 persona prompt
Day 4 (后端 P2) ─ 2026-04-22    GuardedEmitter + 置信度加权 + Bleaching 防御 + BiasDetector
Day 4 收尾   ──── 2026-04-22    并发 benchmark · mock 首 token p95 1138ms
Day 4.8     ──── 2026-04-23    CrossRoundMemory 三档压缩（Tier-1/2/3）
Day 5 (联调)  ─── 2026-04-22~23 RoundtableAuditor 11 事件 + 162 → 177 tests
Day 5 · D5.6 ─── 2026-04-23    RELEASE_NOTES.md v1.0.0-beta（Day 1-6）
Day 6 (多轮)  ─── 2026-04-XX    Session.rounds + continue + RAG 注入 + InjectionDrawer
Day 6.N.d   ──── 2026-04-23    neutral 顾问【情境感知】三档分支 + 197 tests
────────────────────────── Day 7 · 灰度前最后一棒 ──────────────────────────
Day 7 · D7.1.j ── 2026-04-24    Moderator 跨轮记忆注入（fix 第 2 轮失忆 bug · Section 77）
Day 7 · D7.1.j+── 2026-04-30    rule_moderator 降级路径加跨轮记忆（灰度前实战发现 · Section 85）
Day 7 · D7.1.j++ 2026-04-30   RoundtableRouter 路由 fix + banner 文案修正（E2E 测试发现 · Section 86）
Day 7 · D7.1.k ── 2026-04-24    Moderator 降级可见提示条（timeout 90→180/240s · Section 78）
Day 7 · D7.1.f ── 2026-04-25    非 done session 只读快照模式（Section 79）
Day 7 · D7.2.a/b  2026-04-23    9 persona emoji + 头像增强
Day 7 · D7.2.c   2026-04-30    ModeratorCard 桌面 SVG 装饰
Day 7 · D7.2.d   2026-04-30    Typing breathing glow（mp-breathe-glow）
Day 7 · D7.2.e   2026-04-30    PersonaCard 悬停 sparkle
Day 7 · D7.1.c   2026-04-30    真 LLM benchmark + SLO 三层定稿（p95 = 5.82s PASS · Section 83）
Day 7 · D7.4.a   2026-04-30    本 RELEASE_NOTES.md 更新到 v1.0.0
Day 7 · D7.4.b   2026-05-02    Beta 邀请文档 docs/beta_invitation.md（Section 87）
Day 7 · D7.4.c   2026-05-02    Beta 观测 Dashboard scripts/roundtable_beta_dashboard.py（Section 87）
Day 7 · D7.4.b/c  ──────────    Beta 灰度 10 用户执行期（工具就绪 · 下一步挑选用户）
```

**关键 Commit / 文件交付物**：

**Backend**
- `@<PROJECT_ROOT>/scripts/advisor/api/services/roundtable_service.py` (主编排 · Moderator 跨轮 · fallback_reason · deep_mode timeout)
- `@<PROJECT_ROOT>/scripts/advisor/api/services/roundtable_memory.py` (跨轮记忆 · Tier-1/2/3)
- `@<PROJECT_ROOT>/scripts/advisor/api/services/roundtable_audit.py` (11 事件审计)
- `@<PROJECT_ROOT>/scripts/advisor/api/services/bias_detector.py` (5 类 60 规则)
- `@<PROJECT_ROOT>/scripts/advisor/api/routes/roundtable.py` (7 端点)
- `@<PROJECT_ROOT>/configs/roundtable_prompts.yaml` (9 persona + Moderator `{prior_context_block}` 占位符 · Day 7 新增)
- `@<PROJECT_ROOT>/configs/crisis_keywords.yaml` (5 类偏见规则 + crisis 词)

**Frontend**
- `@<PROJECT_ROOT>/frontend/src/pages/RoundtablePage.tsx` (setup 页 + 历史入口)
- `@<PROJECT_ROOT>/frontend/src/pages/RoundtableSessionPage.tsx` (Session 主页 · 只读快照 banner · Day 7 D7.1.f)
- `@<PROJECT_ROOT>/frontend/src/hooks/useRoundtableStream.ts` (SSE dispatcher · fallback_reason 透传)
- `@<PROJECT_ROOT>/frontend/src/stores/useRoundtableStore.ts` (Zustand · isReadOnlySnapshot / moderatorFallbackReason · Day 7)
- `@<PROJECT_ROOT>/frontend/src/components/roundtable/ModeratorCard.tsx` (桌面 SVG + 降级 banner · Day 7 D7.1.k / D7.2.c)
- `@<PROJECT_ROOT>/frontend/src/components/roundtable/AgentMessage.tsx` (breathing glow · Day 7 D7.2.d)
- `@<PROJECT_ROOT>/frontend/src/components/roundtable/PersonaCard.tsx` (sparkle hover · Day 7 D7.2.e)
- `@<PROJECT_ROOT>/frontend/src/data/personas.ts` (9 persona + emoji + accentText · Day 7 D7.2.a/d)
- `@<PROJECT_ROOT>/frontend/src/index.css` (reduced-motion 三档兜底 + mp-breathe-glow · Day 7 D7.1.i / D7.2.d)

**工具 / 文档**
- `@<PROJECT_ROOT>/scripts/benchmark_roundtable.py` (mock + `--real-llm --backend` 双模式 · Day 7 D7.1.c)
- `@<PROJECT_ROOT>/scripts/verify_roundtable_memory_e2e.py` (8/8 checks)
- `@<PROJECT_ROOT>/research/big_plan/plan_v3/圆桌讨论_执行方案.md` (1400+ 行 · 完整执行轨迹 · Day 1→7)
- `@<PROJECT_ROOT>/advisor_out/comparison/pipeline_plan.md` (Section 75-83 · Day 7 技术备忘)
- `@<PROJECT_ROOT>/advisor_out/benchmarks/roundtable_latency_c1_20260430_163113.json` (L2 SLO benchmark 结果)
- `@<PROJECT_ROOT>/scripts/roundtable_beta_dashboard.py` (Beta 观测 Dashboard · 8 维度 · 0 第三方依赖 · Day 7 D7.4.c)
- `@<PROJECT_ROOT>/docs/beta_invitation.md` (Beta 用户邀请文档 · 8 段 · 多轮 continue 指引 + FAQ · Day 7 D7.4.b)

---

## 11. License & Privacy

- **数据隐私** · 用户对话**不持久化** · 仅存内存 session · 重启即清；审计 JSONL 仅含 metrics（不含原文）
- **PII 脱敏** · 跟现有 `configs/anonymization.yaml` 保持一致 · 已知人名映射后再入 prompt
- **第三方 LLM 调用** · 走现有 `generator.py` 多 backend 路由 · 受 `local_secrets/.env.advisor` 密钥配置约束

---

## 附录 A · 术语表

| 术语 | 解释 |
|---|---|
| **Persona** | 9 种顾问流派之一（neutral / supportive / eft / cbt / structural / narrative / 等） |
| **Phase 1** | 3 agent 独立首次回应（不看其他 agent） |
| **Phase 2** | 3 agent 看到 peer_views 后交叉补充 / 反驳 / 整合 |
| **Phase 3** | Moderator（中立角色）对 3 路输出做六段结构化总结 |
| **Tier-1/2/3** | CrossRoundMemory 三档优先级 · 最新轮详细 / 次新轮中度 / 更早轮 LIFO 极简 |
| **GuardedEmitter** | chunk 级 sanitize 流式发射器 · 阈值 16 字符或句末标点触发 flush |
| **形态 A** | 多轮追问（done → continue · 同 session_id） |
| **形态 B** | DAG 分叉（interrupt → 创建 child session）· **V2 候选** |
| **deep_mode** | Moderator 深度思考模式 · 触发 `deep_moderator_llm_prompt` 模板 · timeout 240s |
| **isReadOnlySnapshot** | Day 7 · 非 done session 点历史时的只读快照状态 · SSE 挂起 · 显式 banner |
| **fallback_reason** | Day 7 · Moderator LLM timeout/error 时走规则 fallback 的原因字符串 · 全链路透传到前端 banner |
| **SLO L1 / L2 / L3** | Day 7 · mock pipeline ≤ 3s / 单 backend ≤ 6s / 多 backend 并发 ≤ 4s |
| **mp-breathe-glow** | Day 7 · Typing 状态 accent line 的 `drop-shadow` 呼吸光晕动画类 |

---

## 附录 B · 版本历史

| 版本 | 日期 | 状态 | 里程碑 |
|:---:|:---|:---:|:---|
| v1.0.0-beta | 2026-04-23 | ✅ | Day 1-6 完整闭环 · 177 backend + 47 frontend tests · mock SLO PASS |
| **v1.0.0** | **2026-04-30** | ✅ | **Day 7 收尾** · 210 backend + 70 frontend tests · 视觉档 A + 只读快照 + 跨轮记忆 Moderator（LLM 路径 + 降级路径双闭环） + continue SSE 重连修复 + 真 LLM SLO L2 PASS · **灰度候选** |
| v1.0.1 (planned) | — | ⏳ | D7.4.b/c 10 Beta 用户观测 · 完成率 / 首 token p95 / 降级率 监控数据 |
| v1.1.0 (planned) | — | ⏳ | 档 B 深度 MP 卡通立绘 + 直连 key L3 SLO 复测 |

---

**Lens · Roundtable Module · 2026-04-30 · v1.0.0 · `feat(roundtable): Day 7 收尾 · SLO 三层定稿 · 灰度候选`**
