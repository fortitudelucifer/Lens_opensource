# 关系顾问 Agent 流水线设计概览

> 完整设计文档：离线训练 + 实时对话 + 前后端交互
>
> **版本**: v4.0 | **最后更新**: 2026-02-15

---

## 1. 系统总览

### 1.1 核心目标

基于微信聊天记录训练的 AI 关系顾问系统：

- **离线流水线**（Phase 0-7）：数据提取 → MoA 融合分析 → 质量审核 → QLoRA 微调 → 推理
- **在线服务**（Phase 8）：三 Agent × 两模式实时多轮对话，Hybrid RAG 上下文增强
- **辅助模块**（Phase 9-10）：向量索引构建、数据增强蒸馏
- **Web 前端**：React + Vite 仪表盘，REST API 控制全流程

| 挑战 | 解决方案 |
|------|----------|
| 标注成本高 | MoA 多模型融合标注 + AI 审核 + 自动补齐 |
| 显存限制 16GB | QLoRA 4-bit NF4（~5-6 GB） |
| 分析角度单一 | 三种 Agent（中立/支持性/精神分析） |
| 上下文理解 | 滑动窗口 + Hybrid RAG (日期精确 + 语义向量 + 关键词) |
| 长对话记忆 | 滑动窗口(20条) + 历史摘要 + 关键事实提取(memory_facts) |
| 多模型适配 | 9 后端统一 OpenAI 兼容接口 + KeyRotator 轮换 |
| 隐私保护 | L1/L2 数据分流 + SafetyLayer P0 |
| API 限速 | GlobalRateLimiter RPM≤19 + 故障自动降级 |
| 代理兼容 | Response API 单轮适配 + max_tokens 上限 + 连续消息合并 |

### 1.2 三种 Agent × 两种模式

| 类型 | 名称 | 特点 | 理论框架 |
|------|------|------|----------|
| `neutral` | 中立顾问 | 客观多维分析 | 沟通模式、依附风格、NVC、权力动态、家庭系统 |
| `supportive` | 支持性顾问 | 无条件站在用户一方 | 情感验证、保护性建议、边界设立 |
| `psychoanalytic` | 精神分析顾问 | 无意识层面深度分析 | 客体关系、拉康三界、防御机制、欲望结构、移情 |

| 模式 | 回复特征 |
|------|----------|
| `listen` 倾听 | 5-7 句，共情为主，开放性问题引导 |
| `consult` 咨询 | 完整深度分析（500-2500 字），结构化多维度 |

---

## 2. 系统架构图

```
┌───────────────────────────────────────────────────────────────────┐
│                   Relationship Advisor System                      │
│                                                                    │
│  ┌──────────────┐    REST API (:8787)    ┌──────────────────┐     │
│  │  Frontend     │ ◄════════════════════► │  Backend FastAPI  │     │
│  │  React+Vite   │                        │  uvicorn :8787    │     │
│  │  :5173        │                        │                   │     │
│  │               │   /api/chat (SSE) ───► │ Chat Engine       │     │
│  │ ┌───────────┐ │   /api/pipeline ─────► │ Pipeline Engine   │     │
│  │ │ Dashboard  │ │   /api/review ──────► │ Review Engine     │     │
│  │ │ Chat      │ │   /api/models ──────► │ Model Manager     │     │
│  │ │ Review    │ │   /api/data ────────► │ Data Stats        │     │
│  │ │ Settings  │ │                        │                   │     │
│  │ └───────────┘ │                        │ GraphRAG Context  │     │
│  └──────────────┘                        │ Session Manager   │     │
│                                           └────────┬─────────┘     │
│                                                    │               │
│  ┌─────────────────── LLM 后端 ──────────────────┐ │               │
│  │ Cloud: GPT-5.2 | Claude 4.5 | Gemini 3 | Grok 4 │◄┘               │
│  │        DeepSeek V3.2 | Qwen 235B | GLM 4.7    │                │
│  │ Local: Ollama qwen3:8b (:11434)               │                │
│  └────────────────────────────────────────────────┘                │
│                                                                    │
│  ┌─────────── 离线流水线 (CLI + API) ────────────────────────┐    │
│  │ Phase 0 环境验证 → Phase 1 对话提取 → Phase 2 LLM分析    │    │
│  │ → Phase 3 AI审核+人工审核 → Phase 4 导入 → Phase 5 格式化 │    │
│  │ → Phase 6 QLoRA微调 → Phase 7 推理 → Phase 8 实时对话     │    │
│  │ → [Phase 9 GraphRAG] → [Phase 10 数据增强]                │    │
│  └───────────────────────────────────────────────────────────┘    │
└───────────────────────────────────────────────────────────────────┘
```

---

## 3. 前后端交互架构

### 3.1 技术栈

| 层 | 技术 | 端口 |
|----|------|------|
| 前端 | React 18 + Vite + TailwindCSS v4 + shadcn/ui 风格 | 5173 |
| 后端 | Python FastAPI + uvicorn (--reload) | 8787 |
| 本地 LLM | Ollama (qwen3:8b) | 11434 |
| 向量索引 | FAISS + BGE-M3 | — |

### 3.2 REST API 端点

#### 实时对话

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/chat` | 多轮对话（SSE 流式/非流式） |
| `GET` | `/api/chat/sessions` | 列出所有会话 |
| `POST` | `/api/chat/sessions` | 创建新会话 |
| `GET` | `/api/chat/sessions/{id}` | 获取会话详情 |
| `DELETE` | `/api/chat/sessions/{id}` | 删除会话 |

ChatRequest:
```json
{
  "message": "...",
  "agent_type": "neutral|supportive|psychoanalytic",
  "mode": "listen|consult",
  "backend": "grok",
  "stream": true,
  "session_id": "abc12345"
}
```

SSE 响应: `data: {"content":"token"}` → `data: {"session_id":"..."}` → `data: [DONE]`

#### 流水线 / 审核 / 模型 / 数据

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/pipeline/status` | 所有阶段状态 |
| `POST` | `/api/pipeline/run/{phase}` | 运行 Phase 1-3 |
| `GET` | `/api/review/items` | 审核条目列表 |
| `GET/POST` | `/api/review/items/{id}` | 详情 / 提交决定 |
| `GET` | `/api/models` | 后端状态 |
| `GET` | `/api/models/available` | 可用模型（按角色） |
| `GET/POST` | `/api/models/preferences` | 模型偏好 |
| `POST` | `/api/models/test` | 连通性测试 |
| `GET` | `/api/data/stats` | 数据统计 |
| `GET` | `/api/health` | 健康检查 |

#### RAG / 反馈

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/rag/search` | RAG 综合检索（语义/日期/类型/范围） |
| `GET` | `/api/rag/day/{day_num}` | 精确日期检索 |
| `GET` | `/api/rag/chunk/{chunk_id}` | 单 chunk 详情 + 关联分析 |
| `GET` | `/api/rag/stats` | RAG 索引统计 |
| `POST` | `/api/rag/incremental-update` | 增量更新索引（无需全量重建） |
| `POST` | `/api/chat/feedback` | 用户反馈评分回收 |

### 3.3 前端页面结构

```
App.tsx
├── 仪表盘: DataStats + PipelineStatus + ModelConfig
├── 实时对话: ChatPanel (Agent选择 + 模式切换 + 会话管理 + SSE渲染)
├── 人工审核: ReviewPanel (过滤 + 详情 + approve/reject/edit)
└── 设置: ModelSelector + ModelTester + 配置路径 + 隐私策略
```

### 3.4 对话数据流

```
用户输入 → ChatPanel → POST /api/chat
  → server.py: 选择 system_prompt[agent_type][mode]
  → IntentClassifier: 识别用户意图 (情绪/信息/冲突/建议)
  → _parse_query_days: 解析日期引用 (单日/范围/相对)
  → _enriched_search: 混合检索 (日期精确 + FAISS语义 + 关键词)
  → _build_rag_context: 组装上下文
     [人物对照] ME/OTHER 的真实姓名
     [用户关系档案] 反复话题/冲突/情绪/趋势
     [历史模式] 反复冲突根源
     [相关历史对话片段] 带分析摘要
     [参考知识] FAQ 知识库
     [交互提示] 意图引导
  → 注入到 system prompt
  → 加载/创建会话
  → _compress_history_messages: 滑动窗口(20条) + 旧消息摘要
  → _truncate_history_messages: 单条过长截断(3000字)
  → 合并连续同角色消息 (防止 Claude/OpenAI 400)
  → 调用 LLM (max_tokens ≤ 16384)
  → SSE 逐 token 推送
  → _save_and_finalize: 保存 + _extract_memory_facts → session.memory_facts
  → ChatPanel 逐 token 渲染
```

---

## 4. 离线流水线各阶段

### Phase 1: 对话片段提取
- **组件**: `extractor.py` → `ConversationExtractor`
- 滑动窗口 (window=20, step=10)，按冲突/甜蜜/普通分类评分

### Phase 2: MoA 融合分析
- **组件**: `generator.py` + `_02c_fusion_pipeline.py` + `pipeline_executor.py`
- **MoA 架构**: Claude(S1) + GPT(S1) + Gemini(S1) 并行分析 → Grok MoA 融合(S2) → Grok 审核(S3) → Grok 补齐(S4)
- **CPU 流水线**: 4 级 asyncio 流水线 (PipelineExecutor):
  - chunk[i] 进入 S2 时，chunk[i+1] 可立即开始 S1
  - S1 和 S2-S4 使用不同 API provider，天然不竞争
- **Key 轮换**: `key_rotator.py` (KeyRotator + GlobalRateLimiter RPM≤19)
- **降级策略**: Claude Opus 失败 → Sonnet Think → GPT+Gemini 双分析; Grok 失败 → Kimi 备用 → v1 程序合并
- 断点续传、SchemaValidator 2 轮自修复、rich 实时可视化

### Phase 3: 质量审核 + 自动补齐
- **3a AI 审核 (Grok Review)**: 5 维度 50 分制（准确/深度/平衡/安全/结构，各 1-10）
- **3a+ 自动补齐 (Remediation)**: 得分 ≤7 的维度自动修复（最多 3 轮），直到全部 ≥8
- **3b 人工审核**: 前端 ReviewPanel 或导出 Markdown

### Phase 4-5: 导入审核 → 格式化训练数据
- **5b 数据过滤与划分**: 过滤低质量样本（~3%），按 80/10/10 划分 train/val/test
- **5c 反匿名化**: L1 真实姓名恢复 + 30+ 地名双向映射
- JSONL SFT 格式，含多模态字段（时间模式/冲突根源/多模态信号/修复尝试/人格动态）

### Phase 6: QLoRA 微调
- **组件**: `trainer.py`
- Qwen3-8B-Instruct + LoRA r=32 alpha=64 + 4-bit NF4
- max_seq_length=4096, paged_adamw_32bit, ~5-6 GB 显存

### Phase 7: 模型推理
- **组件**: `inference.py`
- 双模推理（思考/非思考），4-bit 量化，单条/批量
- 无输入长度截断（允许长对话完整输入，由 RAG 在上游控制上下文量）

### Phase 8: 实时对话服务
- **组件**: `api/server.py` + Ollama + Hybrid RAG
- 多轮会话持久化 + SSE 流式
- **长对话记忆压缩**:
  - 滑动窗口: 保留最近 20 条完整消息
  - 历史摘要: 超 20 条时旧消息自动压缩为要点注入 system prompt
  - 关键事实提取: assistant 回复中自动提取日期事件/关系状态，持久化到 `session.memory_facts`（上限 30 条）
  - 单条消息截断: 历史中超 3000 字的消息自动截断
- **API 兼容层**:
  - Response API (GPT-5.2): 单轮 system+user input（OpenAI-compatible proxy 不支持多轮/instructions）
  - Chat Completions (Claude/Gemini/Grok 等): max_tokens ≤ 16384
  - 连续同角色消息自动合并（用户重试积累的重复消息）
- **Hybrid RAG 上下文注入**:
  - 日期精确查询 (第108天, 10月22日, 2025-10-08)
  - 日期范围查询 (第108天到第110天, 9月22日到25日)
  - 相对日期 (最近一周, 上个月, 最近三天)
  - FAISS 语义检索 + 关键词回退
  - 日期优先 + 语义补充混合去重
- **意图分类** (IntentClassifier): 情绪宣泄/信息查询/冲突讨论/关系建议 → 动态调整检索策略
- **反馈闭环**: `/api/chat/feedback` 用户评分回收
- **增量更新**: `POST /api/rag/incremental-update` 无需全量重建

### Phase 9: Hybrid RAG 索引
- **组件**: `graph_rag.py` + `chunk_based_rag.py` + `graph_rag_enhanced.py`
- **Layer 1**: FAISS 向量召回 (BGE-M3, top-20)
- **Layer 2**: BGE-Reranker-V2-M3 精排 (top-10)
- **Layer 3**: 多维评分重加权 (语义×0.5 + 时间×0.2 + 情感×0.3)
- **Layer 4**: 上下文组装 (用户档案 + 历史模式 + 对话片段 + FAQ)
- 输出: index.faiss + metadata.json + enriched_metadata.json + user_profile.json

### Phase 10: 数据增强蒸馏 (可选)
- **组件**: `augmentor.py`
- 多教师模型蒸馏，扩充训练集

---

## 5. 辅助组件

| 组件 | 文件 | 功能 |
|------|------|------|
| ResponseTimeAnalyzer | analyzers.py | 冷暴力/争吵检测（回复时间模式） |
| ConflictRootCauseAnalyzer | analyzers.py | 10 种冲突根源 + 8 种缓和原因 |
| LongTermContextAnalyzer | analyzers.py | 话题嵌入索引，反复模式识别 |
| NeutralityChecker | analyzers.py | ME/OTHER 批评平衡度 |
| PsychoanalyticDetector | analyzers.py | 依附风格、防御机制、拉康三界 |
| SchemaValidator | schema_validator.py | JSON 校验 + 2 轮自修复 |
| SafetyLayer | safety_layer.py | P0: 云端 rationale 不注入本地 |
| ModelRouter | model_router.py | 多模型路由、fallback、成本控制 |
| IntentClassifier | intent_classifier.py | 用户查询意图识别 (5 类) |
| QueryRewriter | query_rewriter.py | 查询改写、时间上下文补充 |
| KeyRotator | key_rotator.py | API key 轮换 + 故障降级 + RPM 硬限制 |
| PipelineExecutor | pipeline_executor.py | 4 级流水线 + rich 实时可视化 |
| ChunkAwareRAG | chunk_based_rag.py | 多维检索 + 日期索引 + 跨天关联 |

---

## 6. 目录结构

```
scripts/advisor/
├── extractor.py, generator.py, formatter.py    # 核心管线
├── trainer.py, inference.py                     # 训练/推理
├── graph_rag.py, chunk_based_rag.py              # RAG 基础 + 多维检索
├── graph_rag_enhanced.py                         # 增强 RAG (日期/元数据查询)
├── intent_classifier.py, query_rewriter.py       # 意图识别 + 查询改写
├── key_rotator.py, pipeline_executor.py          # Key 轮换 + 流水线执行器
├── analyzers.py, model_router.py                 # 分析/路由
├── schema_validator.py, schemas.py               # 校验
├── safety_layer.py, config.py, errors.py         # 安全/配置
├── augmentor.py, streaming.py                    # 数据增强/流式
├── api/server.py                                # FastAPI 后端
└── run_all/_00 ~ _10                             # CLI 脚本
    ├── _02b_model_comparison.py                  # 8 模型 A/B 对比
    ├── _02c_fusion_pipeline.py                   # MoA 融合流水线 (主入口)
    ├── _05b_filter_split_training.py             # 数据过滤划分
    └── _05c_deanonymize_training.py              # 反匿名化

frontend/src/
├── App.tsx                                      # 4 页面路由
├── lib/api.ts, lib/utils.ts                     # API 客户端 + 工具
└── components/                                  # 8 个组件
    ChatPanel / PipelineStatus / DataStats / ModelConfig
    ModelSelector / ModelTester / ReviewPanel / ApiKeyChecker
    ui/ {badge, button, card, textarea}           # shadcn/ui 基础组件

local_secrets/
├── .env.advisor                                 # API Key 环境变量
├── key_pool.yaml                                # 流水线 Key 池配置
└── platforms.yaml                               # 测试脚本平台配置

advisor_out/
├── chunks/conversation_chunks.jsonl
├── analysis/fused_analysis_{type}_moa.jsonl      # MoA 融合结果
├── review/ai_review_{type}.jsonl
├── training/advisor_training_{type}.jsonl        # SFT 训练数据
├── models/relationship_advisor_{type}_deanon_unsloth/
├── faiss_index/{index.faiss, metadata.json, enriched_metadata.json, user_profile.json}
├── chat_sessions/{session_id}.json
└── comparison/pipeline_plan.md                   # 进度记录
```

---

## 7. 配置

### API Key 管理

| 文件 | 用途 |
|------|------|
| `local_secrets/.env.advisor` | 后端环境变量 ({PREFIX}_API_KEY / _BASE_URL / _MODEL) |
| `local_secrets/key_pool.yaml` | 流水线 Key 池 (KeyRotator RPM≤19 + emergency) |
| `local_secrets/platforms.yaml` | 测试脚本平台配置 (7 平台) |

### 流水线 (`configs/advisor.yaml`)
```yaml
extraction: {window_size: 20, step_size: 10, num_chunks: 500}
training: {base_model: Qwen3-8B-Instruct, lora: {r: 32, alpha: 64}, lr: 1e-4, epochs: 5}
inference: {quantization: 4bit, temperature: 0.7}
```

---

## 8. 启动命令

```bash
# 1. 后端
source local_secrets/.env.advisor
conda run -n wechatDHA uvicorn scripts.advisor.api.server:app --reload --port 8787

# 2. 前端
cd frontend && npm run dev    # → http://localhost:5173

# 3. 本地 LLM (可选)
ollama run qwen3:8b           # → http://localhost:11434
```

---

## 9. 成功指标

| 指标 | 目标 | 实际 |
|------|------|------|
| 训练数据量 | ≥ 50 样本/Agent | N chunks (MoA 融合) |
| 训练 loss | < 1.0 | eval_loss=1.3696 |
| 推理显存 | < 8 GB (4-bit) | ~5-6 GB |
| 对话延迟 | < 2s 首 token (云端) | Kimi 2.5s, DeepSeek 3s |
| 倾听回复 | 5-7 句 | ✅ |
| 咨询回复 | 500-2500 字 | ✅ |
| AI 审核通过率 | ≥ 70% | MoA 融合 ≥ 85%, 补齐后 ≥97% |
| 模型连通 | 9/9 后端 | 9/9 ✅ (GPT-5.2 Response API 单轮适配) |
