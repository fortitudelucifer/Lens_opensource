# 关系顾问 Agent 流水线 — 分步执行指南

> 详细讲解完整流水线的每一步操作，包括前后端交互。
>
> **版本**: v3.0 | **最后更新**: 2026-02-10

---

## 目录

- [0. 前置条件](#0-前置条件)
- [1. 整体流程概览](#1-整体流程概览)
- [2. 环境准备](#2-环境准备)
- [3. 输入数据说明](#3-输入数据说明)
- [4. Phase 1: 对话片段提取](#4-phase-1-对话片段提取)
- [5. Phase 2: LLM 分析生成](#5-phase-2-llm-分析生成)
- [6. Phase 3a: AI 辅助审核](#6-phase-3a-ai-辅助审核)
- [6b. Phase 3b: 人工审核](#6b-phase-3b-人工审核)
- [7. Phase 4: 导入审核结果](#7-phase-4-导入审核结果)
- [8. Phase 5: 训练数据格式化](#8-phase-5-训练数据格式化)
- [9. Phase 6: 模型训练 (QLoRA)](#9-phase-6-模型训练-qlora)
- [10. Phase 7: 模型推理](#10-phase-7-模型推理)
- [11. Phase 8: 实时对话服务](#11-phase-8-实时对话服务)
- [12. 前后端交互详解](#12-前后端交互详解)
- [13. 附加: GraphRAG 索引构建](#13-附加-graphrag-索引构建)
- [14. 附加: 数据增强与蒸馏](#14-附加-数据增强与蒸馏)
- [15. 云端模型配置参考](#15-云端模型配置参考)
- [16. 隐私策略与数据分流](#16-隐私策略与数据分流)
- [17. 云端训练费用估算](#17-云端训练费用估算)
- [18. 常见问题](#18-常见问题)

---

## 0. 前置条件

### 硬件要求

| 用途 | 推荐 GPU | 显存 |
|------|----------|------|
| 训练 | RTX 3080 Laptop / RTX 4070+ | >= 16GB |
| 推理 | RTX 5070 Ti | 16GB |
| 辅助 | RTX 3070 Ti Laptop | 8GB |

### 软件要求

- Python 3.10+
- Conda 环境 `wechatDHA`
- CUDA 12.x
- Node.js v20+ (前端, 通过 nvm 安装)
- Ollama（本地 LLM, 可选）

### 上游数据（必须先完成）

```
原始微信数据
  → 多模态处理（图片/语音/视频/表情包/链接）
  → 语义压缩 → 时间轴合并 → SFT 字段精简
  → agent_sft_l1.jsonl / agent_sft_l2.jsonl   ← advisor 流水线的输入
```

详见 [modality_fields_and_models.md](../pipelines/modality_fields_and_models.md) 和 [agent_sft_pipeline_overview.md](../pipelines/agent_sft_pipeline_overview.md)。

---

## 1. 整体流程概览

```
agent_sft_l1.jsonl / agent_sft_l2.jsonl
         │
         ▼
[Phase 1] 对话片段提取  (_01_extract_conversations.py)
         │  ← 滑动窗口(20,10), 按冲突/甜蜜/普通评分排序
         ▼
[Phase 2] LLM 分析生成  (_02_generate_analysis.py)
         │  ← 9 后端 × 3 Agent, SchemaValidator 自动校验 + 2 轮自修复
         ▼
[Phase 3a] AI 辅助审核 (_03b_ai_review.py)
         │  ← 5 维度 50 分制, AI 审核通过率 ≥ 70% (≥36/50 分), 安全 ≤4 一票否决
         ▼
[Phase 3b] 人工审核    (前端 ReviewPanel / _03_export_for_review.py)
         │
         ▼
[Phase 4] 导入审核结果  (_04_import_reviewed.py)
         │
         ▼
[Phase 5] 训练数据格式化 (_05_format_training_data.py)
         │  ← JSONL SFT 格式, 含多模态字段
         ▼
[Phase 6] QLoRA 微调    (_06_train_model.py)
         │  ← Qwen3-8B + LoRA r=32 + 4-bit NF4
         ▼
[Phase 7] 模型推理      (_07_run_inference.py)
         │
         ▼
[Phase 8] 实时对话服务   (api/server.py + 前端 ChatPanel)
         │  ← 三 Agent × 两模式, GraphRAG 上下文注入
         │  ← SSE 流式 + 多轮会话持久化
         ▼
      [可选] Phase 9: GraphRAG 索引构建  (_09_build_graph.py)
      [可选] Phase 10: 数据增强与蒸馏   (_10_augment_data.py)
```

---

## 2. 环境准备

### 2.1 激活环境

```bash
conda activate wechatDHA
```

### 2.2 设置 API Key

**方法一（推荐）：使用预配置文件**

```bash
# 1. 编辑配置文件，填写你的 API Key 和首选模型
vim local_secrets/.env.advisor

# 2. 加载到环境
source local_secrets/.env.advisor
```

每个后端需要 3 个环境变量：`{PREFIX}_API_KEY`、`{PREFIX}_BASE_URL`、`{PREFIX}_MODEL`。

**方法二：手动设置**

```bash
export DEEPSEEK_API_KEY="sk-..."      # 性价比最高，推荐优先配置
export ANTHROPIC_API_KEY="sk-ant-..."  # Claude 审核用
export OPENAI_API_KEY="sk-..."        # 可选
# ... 其他后端按需配置
```

> **注意**: 你不需要配置所有 API Key。推荐至少配置 **DeepSeek**（生成）+ **Claude**（审核）。

### 2.3 确认输入数据存在

```bash
ls -la timeline_out/agent_sft_l1.jsonl
ls -la timeline_out/agent_sft_l2.jsonl
```

### 2.4 安装前端依赖（首次）

```bash
cd frontend && npm install
```

---

## 3. 输入数据说明

### 输入文件

| 文件 | 说明 | 用途 |
|------|------|------|
| `timeline_out/agent_sft_l1.jsonl` | 保留真实姓名 | **本地训练 + 推理** |
| `timeline_out/agent_sft_l2.jsonl` | ME/OTHER 匿名化 | **云端分析（隐私安全）** |

### 数据格式

每行一个 JSON，包含：`id`, `time`, `speaker` (ME/OTHER), `type` (text/sticker/image/voice/video/link/file/miniprogram/quote/time_gap), `text_raw` 等。

### L1 vs L2 怎么选？

- **L1**：本地 GPU 训练，数据不上传 → 用 L1
- **L2**：发送到云端 LLM 分析 → 用 L2

---

## 4. Phase 1: 对话片段提取

从 SFT 数据中提取有代表性的对话片段（冲突/甜蜜/普通）。

### CLI 执行

```bash
# 从 L1 数据提取 100 个片段（默认）
python scripts/advisor/run_all/_01_extract_conversations.py

# 从 L2 数据提取
python scripts/advisor/run_all/_01_extract_conversations.py --input l2

# 自定义参数
python scripts/advisor/run_all/_01_extract_conversations.py \
    --num 200 --window-size 30 --step-size 15
```

### 通过前端 API 执行

前端仪表盘 → PipelineStatus 面板 → 点击 Phase 1「运行」按钮。

后端调用: `POST /api/pipeline/run/1`

```json
{
  "input_type": "l2",
  "num_chunks": 100
}
```

### 输出

```
advisor_out/chunks/conversation_chunks.jsonl
```

每个片段包含 10-20 条消息，已格式化为 `[MM月DD日 HH:MM] ME/OTHER: ...` 格式。

---

## 5. Phase 2: LLM 分析生成

使用云端大模型为每个对话片段生成关系分析。**这是最核心的步骤。**

### 支持的 9 个后端

| 后端 | 默认模型 | base_url | 适用角色 |
|------|----------|----------|----------|
| `openai` | gpt-5.2-high | 第三方代理 (backup provider-codex) | analysis, review, chat |
| `claude` | claude-sonnet-4.5-thinking | 第三方代理 | analysis, review, chat |
| `gemini` | gemini-3-pro-preview | Google AI Studio | analysis, review, chat |
| `kimi` | kimi-k2.5 | https://api.moonshot.cn/v1 | analysis, chat |
| `grok` | grok-4.1-thinking | https://api.x.ai/v1 | analysis, review, chat |
| `deepseek` | DeepSeek-V3.2 | https://api.deepseek.com/v1 | analysis, review, chat |
| `qwen_cloud` | Qwen3-235B-A22B-Thinking | DashScope | analysis, review, chat |
| `glm` | glm4.7 | https://open.bigmodel.cn/api/paas/v4 | analysis, chat |
| `qwen_local` | qwen3:8b (Ollama) | http://localhost:11434/v1 | chat |

> 所有后端均通过 OpenAI 兼容接口调用。思考模型（模型名含 `think`）自动检测，不限制 `max_tokens`。

### CLI 执行

```bash
# 使用 Grok 生成中立分析
python scripts/advisor/run_all/_02_generate_analysis.py \
    --backend grok --agent-type neutral

# 三种 Agent 都生成
for t in neutral supportive psychoanalytic; do
    python scripts/advisor/run_all/_02_generate_analysis.py --backend grok --agent-type $t
done

# 测试模式（只处理前 5 个片段）
python scripts/advisor/run_all/_02_generate_analysis.py \
    --backend grok --agent-type neutral --limit 5
```

### 通过前端 API 执行

前端仪表盘 → PipelineStatus 面板 → Phase 2「运行」。

后端调用: `POST /api/pipeline/run/2`

```json
{
  "backend": "grok",
  "agent_type": "neutral",
  "limit": 10
}
```

> Phase 2 通过 API 运行时，Claude 后端默认使用 `claude-sonnet-4.5-thinking`。

### 输出

```
advisor_out/analysis/
├── raw_analysis_neutral.jsonl
├── raw_analysis_supportive.jsonl
└── raw_analysis_psychoanalytic.jsonl
```

---

## 6. Phase 3a: AI 辅助审核

用另一个云端模型对分析结果进行 5 维度自动质量评估。

### 审核维度（5 维度 × 10 分 = 50 分制）

| 维度 | 说明 | 分值 |
|------|------|------|
| **准确性** | 分析是否准确反映对话内容 | 1-10 |
| **深度** | 洞察力是否足够 | 1-10 |
| **平衡性** | 对双方评价是否公正 | 1-10 |
| **安全性** | 有无有害建议（≤4 一票否决） | 1-10 |
| **结构化** | JSON 格式是否完整 | 1-10 |

总分 ≤ 35 自动标记为需人工复查。安全性 ≤ 4 一票否决。

### CLI 执行

```bash
# 使用 Claude 审核中立分析（推荐）
python scripts/advisor/run_all/_03b_ai_review.py --agent-type neutral

# 使用 DeepSeek 审核（更便宜）
python scripts/advisor/run_all/_03b_ai_review.py --agent-type neutral --review-backend deepseek

# 审核所有类型
for t in neutral supportive psychoanalytic; do
    python scripts/advisor/run_all/_03b_ai_review.py --agent-type $t
done
```

### 通过前端 API 执行

`POST /api/pipeline/run/3`

```json
{
  "backend": "claude",
  "agent_type": "neutral"
}
```

### 输出

```
advisor_out/review/
├── ai_review_neutral.jsonl
├── ai_review_supportive.jsonl
└── ai_review_psychoanalytic.jsonl
```

---

## 6b. Phase 3b: 人工审核

两种方式进行人工审核：

### 方式一：前端 ReviewPanel（推荐）

1. 启动后端和前端（见 [Phase 8](#11-phase-8-实时对话服务)）
2. 打开 http://localhost:5173 → 侧边栏「人工审核」
3. ReviewPanel 功能：
   - **过滤**: all / pending / passed / failed
   - **详情**: 查看对话原文 + 分析结果 + AI 评分 + 问题列表
   - **决策**: approve（通过）/ reject（拒绝）/ edit（编辑后通过）
4. 决策自动持久化到 `ai_review_{type}.jsonl`

**前端 → 后端 API 调用链:**

```
GET  /api/review/items?agent_type=neutral&filter=pending  → 条目列表
GET  /api/review/items/{id}                                → 单条详情
POST /api/review/items/{id}  {decision, notes}             → 提交决定
```

### 方式二：导出 Markdown

```bash
python scripts/advisor/run_all/_03_export_for_review.py
```

输出 `advisor_out/review/review_neutral_001.md`，人工编辑后导入。

---

## 7. Phase 4: 导入审核结果

将人工修改后的 Markdown 文件导入回系统。

```bash
python scripts/advisor/run_all/_04_import_reviewed.py
```

> 如果使用前端 ReviewPanel 审核，此步骤可跳过（决策已自动持久化）。

---

## 8. Phase 5: 训练数据格式化

将分析结果格式化为 SFT 训练所需的 JSONL 格式。

```bash
# 格式化中立分析
python scripts/advisor/run_all/_05_format_training_data.py --agent-type neutral

# 格式化所有类型
for t in neutral supportive psychoanalytic; do
    python scripts/advisor/run_all/_05_format_training_data.py --agent-type $t
done
```

输出格式含多模态字段：【关系状态】【沟通质量】【情绪平衡】【时间模式】【冲突根源】【多模态信号】【修复尝试】【人格动态】等。

### 输出

```
advisor_out/training/
├── train_neutral.jsonl
├── train_supportive.jsonl
└── train_psychoanalytic.jsonl
```

---

## 9. Phase 6: 模型训练 (QLoRA)

使用 QLoRA 在 Qwen3-8B 上微调关系顾问模型。

### 前置条件

- 至少 16GB 显存的 GPU
- 本地已下载 Qwen3-8B-Instruct 到 `/data/models/Qwen3-8B-Instruct`

### 执行

```bash
# 训练中立顾问
python scripts/advisor/run_all/_06_train_model.py --agent-type neutral --epochs 5

# 训练支持性顾问
python scripts/advisor/run_all/_06_train_model.py --agent-type supportive --epochs 5

# 断点续训
python scripts/advisor/run_all/_06_train_model.py --agent-type neutral --resume
```

### 训练参数

| 参数 | 值 |
|------|-----|
| 基座模型 | Qwen3-8B-Instruct |
| LoRA rank | 32 |
| LoRA alpha | 64 |
| 量化 | 4-bit NF4 |
| 学习率 | 1e-4 |
| 批次大小 | 1 × 16 (梯度累积) |
| max_seq_length | 4096 |
| 优化器 | paged_adamw_32bit |
| 显存使用 | ~5-6 GB |

### 输出

```
advisor_out/models/
├── relationship_advisor_neutral/
├── relationship_advisor_supportive/
└── relationship_advisor_psychoanalytic/
```

---

## 10. Phase 7: 模型推理

使用微调后的模型进行推理测试。

```bash
# 单次推理（思考模式）
python scripts/advisor/run_all/_07_run_inference.py --agent-type neutral --thinking

# 批量推理
python scripts/advisor/run_all/_07_run_inference.py --agent-type neutral --batch
```

---

## 11. Phase 8: 实时对话服务

实时对话是离线流水线的最终产出。通过 **FastAPI 后端 + React 前端** 提供 Web 界面。

### 11.1 启动服务

**步骤 1: 启动后端**

```bash
# 加载 API Key
source local_secrets/.env.advisor

# 启动 FastAPI 后端 (端口 8787)
conda run -n wechatDHA uvicorn scripts.advisor.api.server:app --reload --port 8787
```

**步骤 2: 启动前端**

```bash
cd frontend && npm run dev
# → http://localhost:5173
```

**步骤 3 (可选): 启动本地 LLM**

```bash
ollama run qwen3:8b
# → http://localhost:11434 (OpenAI 兼容 API at /v1)
```

### 11.2 三种 Agent × 两种模式

#### Agent 类型

| 类型 | 系统提示核心 | 适用场景 |
|------|-------------|----------|
| `neutral` 中立顾问 | 客观分析，不偏向任何一方。listen 用 NVC + 开放性问题；consult 用沟通模式/依附风格/权力动态/家庭系统多维分析 | 需要理性分析 |
| `supportive` 支持性顾问 | 无条件站在用户（ME）一方。验证情感、不评判。consult 提供保护性建议和边界设立 | 需要情感支持 |
| `psychoanalytic` 精神分析顾问 | 整合客体关系和拉康派视角。listen 用均匀悬浮注意力；consult 从依附/防御/三界/欲望/移情多维度深度分析 | 深度心理洞察 |

#### 对话模式

| 模式 | 回复长度 | 特点 |
|------|----------|------|
| `listen` 倾听 | 5-7 句话 | 共情 + 映射感受 + 开放性问题 |
| `consult` 咨询 | 完整分析（500-2500 字） | 结构化多维度 + 具体建议 |

### 11.3 GraphRAG 上下文注入

服务器启动时自动加载预构建的 GraphRAG 元数据（无需 GPU）:

- `advisor_out/vector_index/metadata.json` — 对话片段元数据
- `advisor_out/vector_index/user_profile.json` — 用户关系档案

每次对话请求触发 `_build_rag_context(query)`:

1. **用户档案注入**: 反复话题、反复冲突、主要情绪、关系趋势
2. **检索**: 当前使用轻量关键词匹配，计划升级为 Emotion-aware Hybrid 检索（见下方路线图）
3. **注入 system prompt**: 追加到 Agent 系统提示末尾

#### RAG 检索升级路线图

| 阶段 | 方案 | 资源需求 | 状态 |
|------|------|----------|------|
| v0（当前） | 纯关键词匹配 `_rag_search()` | 无 GPU | ✅ 已实现 |
| v1 | BGE-M3 Dense 向量检索 (FAISS) | GPU ~1.3GB | Phase 9 已就绪 |
| **v2（目标）** | **Emotion-aware Hybrid**: BGE-M3 dense + sparse + 情绪 metadata 过滤 + RRF 融合 | GPU ~1.3GB | 📋 计划中 |

**v2 Emotion-aware Hybrid 检索流程**:

```
用户查询
  ├─ BGE-M3 编码 → dense vector (1024d) + sparse vector (同时生成，无额外成本)
  ├─ FAISS dense search → top-20 候选
  ├─ Sparse keyword match → top-20 候选
  ├─ RRF 融合排序 (k=60, sparse_boost=1.2)
  ├─ 情绪 metadata 加权 (chunk 已有 emotion_tags/conflict_root_cause)
  └─ 返回 top-3 最终结果
```

预计提升: MRR +18%, Recall@5 +7%（基于 Hybrid RAG benchmark 数据），延迟增量 ~200ms。

### 11.4 会话管理

每个会话持久化为 `advisor_out/chat_sessions/{session_id}.json`:

```json
{
  "id": "abc12345",
  "title": "我最近和她吵了一架...",
  "agent_type": "neutral",
  "mode": "listen",
  "backend": "grok",
  "messages": [
    {"role": "user", "content": "...", "timestamp": "..."},
    {"role": "assistant", "content": "...", "timestamp": "...", "backend": "grok", "model": "grok-4.1-thinking"}
  ],
  "created_at": "...",
  "updated_at": "..."
}
```

功能:
- 自动创建会话（首次对话时）
- 多轮历史自动追加到 LLM messages
- 自动生成标题（第一条消息的前 20 字）
- 切换 Agent/模式/后端 时保持会话上下文

### 11.5 思考模型处理

后端自动检测思考模型（模型名含 `think`）:
- **不限制 `max_tokens`**: 思考模型将大量 token 用于内部 `<think>` 推理，设置 max_tokens 会导致回复被截断
- **不设置 temperature**: 思考模型有自己的采样策略

### 11.6 CLI 方式（无需前端）

```bash
# listen 模式
python scripts/advisor/run_all/_08_run_dialogue.py

# consult 模式 + GraphRAG
python scripts/advisor/run_all/_08_run_dialogue.py --mode consult --index-path advisor_out/vector_index
```

CLI 对话命令: `/listen`, `/consult`, `/clear`, `/history`, `/quit`

---

## 12. 前后端交互详解

### 12.1 技术栈

| 层 | 技术 | 端口 |
|----|------|------|
| 前端 | React 18 + Vite + TailwindCSS v4 + shadcn/ui 风格 | 5173 |
| 后端 | Python FastAPI + uvicorn (--reload) | 8787 |
| 本地 LLM | Ollama (qwen3:8b) | 11434 |
| 向量索引 | FAISS + BGE-M3 | — |

> 前端通过 Vite proxy 将 `/api/*` 请求代理到 `http://localhost:8787`。

### 12.2 完整 REST API 端点

#### 实时对话

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/chat` | 多轮对话（SSE 流式/非流式） |
| `GET` | `/api/chat/sessions` | 列出所有会话 |
| `POST` | `/api/chat/sessions?agent_type=&mode=&backend=` | 创建新会话 |
| `GET` | `/api/chat/sessions/{id}` | 获取会话详情（含全部消息） |
| `DELETE` | `/api/chat/sessions/{id}` | 删除会话 |

**ChatRequest 参数:**

```json
{
  "message": "我最近和她吵了一架",
  "agent_type": "neutral",         // neutral | supportive | psychoanalytic
  "mode": "listen",                // listen | consult
  "backend": "grok",              // 9 后端之一
  "stream": true,                  // SSE 流式
  "session_id": "abc12345"         // 可选，续接已有会话
}
```

**SSE 流式响应格式:**

```
data: {"content": "我"}
data: {"content": "能"}
data: {"content": "感受到你现在..."}
...
data: {"session_id": "abc12345"}
data: [DONE]
```

前端 `api.ts` 中的 `chatStream()` 解析 SSE 事件:
- `{"content": "..."}` → 逐 token 渲染到 ChatPanel
- `{"session_id": "..."}` → 保存到组件 state，用于后续消息续接
- `{"error": "..."}` → 显示错误
- `[DONE]` → 流结束

#### 流水线控制

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/pipeline/status` | 获取 Phase 1-8 状态 (idle/running/done/error) |
| `POST` | `/api/pipeline/run/{phase}` | 运行指定阶段（Phase 1-3 已自动化） |

**PipelineRunRequest:**

```json
{
  "input_type": "l2",       // l1 | l2
  "backend": "grok",
  "agent_type": "neutral",
  "limit": 10,              // 可选，限制处理数量
  "num_chunks": 100          // Phase 1 专用
}
```

> Phase 4-7 需通过 CLI 运行（涉及 GPU / 文件系统操作）。

#### 人工审核

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/review/items?agent_type=neutral&filter=all` | 审核条目列表 + 统计 |
| `GET` | `/api/review/items/{id}` | 单条审核详情 |
| `POST` | `/api/review/items/{id}` | 提交决定: `{decision, notes, edited_analysis}` |

**ReviewDecision:**

```json
{
  "decision": "approve",     // approve | reject | edit
  "notes": "补充说明",       // 可选
  "edited_analysis": "..."   // edit 时提供修改后的分析
}
```

#### 模型管理

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/models` | 9 后端状态（connected/configured/offline） |
| `GET` | `/api/models/available` | 有 API Key 的可用模型列表 |
| `GET` | `/api/models/preferences` | 获取模型偏好 |
| `POST` | `/api/models/preferences` | 保存偏好（analysis/review/chat 各选一个后端） |
| `POST` | `/api/models/test` | 测试单个后端连通性 |

**ModelTestRequest:**

```json
{
  "backend": "grok",
  "model": "",              // 空 = 用默认模型
  "prompt": "请用一句话回复：你好"
}
```

#### 数据统计 / 健康

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/data/stats` | L1/L2/test 行数, chunks 数, 各类 analysis/review 数 |
| `GET` | `/api/health` | `{"status": "ok", "version": "2.1"}` |

### 12.3 前端页面详解

#### 仪表盘 (DashboardPage)

```
┌─────────────────────────────────────────────┐
│  DataStats                                   │
│  ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐  │
│  │ L1  │ │ L2  │ │Test │ │Chunk│ │Anal │  │
│  │  N  │ │  N  │ │ 20  │ │ 10  │ │ 10  │  │
│  └─────┘ └─────┘ └─────┘ └─────┘ └─────┘  │
├────────────────────┬────────────────────────┤
│  PipelineStatus    │  ModelConfig           │
│  Phase 1: done ✅  │  grok: connected ✅    │
│  Phase 2: idle     │  claude: connected ✅   │
│  Phase 3: idle     │  deepseek: connected ✅ │
│  [运行 Phase 1]    │  qwen_local: offline ❌ │
│  [运行 Phase 2]    │  ...                    │
│  [运行 Phase 3]    │                         │
└────────────────────┴────────────────────────┘
```

- `GET /api/data/stats` → DataStats 卡片
- `GET /api/pipeline/status` → PipelineStatus 面板
- `GET /api/models` → ModelConfig 表格

#### 实时对话 (ChatPage)

```
┌──────────┬─────────────────────────────────┐
│ 会话列表  │  Agent: [neutral ▼]             │
│          │  Mode:  [listen ▼]              │
│ > 新对话  │  Backend: [grok ▼]             │
│   会话1   │─────────────────────────────────│
│   会话2   │  对方: 我最近和她吵了一架        │
│          │                                  │
│          │  顾问: 我能感受到你现在的情绪...   │
│          │  (逐 token 流式渲染)              │
│          │─────────────────────────────────│
│          │  [输入消息...]          [发送]   │
└──────────┴─────────────────────────────────┘
```

数据流:
1. 选择 Agent/Mode/Backend → `api.chatStream({message, agent_type, mode, backend, session_id})`
2. SSE 逐 token → ChatPanel state 追加 → 实时渲染
3. 流结束 → 收到 `session_id` → 下次消息续接
4. 会话列表 → `api.listSessions()` → 点击切换 → `api.getSession(id)`

#### 人工审核 (ReviewPage)

```
┌─────────────────────┬──────────────────────────┐
│ 过滤: [all ▼]       │ 详情                      │
│ agent: [neutral ▼]  │ Chunk ID: chunk_001       │
│─────────────────────│ AI Score: 22/25 ✅         │
│ ☑ chunk_001 22/25 ✅│ 问题: 无                   │
│ ☐ chunk_002 15/25 ❌│─────────────────────────── │
│ ☐ chunk_003 20/25 ✅│ 对话原文:                  │
│                     │ ME: ...                    │
│                     │ OTHER: ...                 │
│                     │─────────────────────────── │
│                     │ 分析结果:                  │
│                     │ 【关系状态】...             │
│                     │─────────────────────────── │
│                     │ [✅ Approve] [❌ Reject]   │
└─────────────────────┴──────────────────────────┘
```

#### 设置 (SettingsPage)

- **ModelSelector**: 为 analysis / review / chat 三种角色分别选择首选后端
- **ModelTester**: 逐个后端发送测试 prompt，显示响应 + 延迟
- 配置文件路径、隐私策略说明

### 12.4 后端对话处理完整流程

```
1. 前端 POST /api/chat {message, agent_type, mode, backend, stream, session_id}
          │
2. server.py: chat(req)
   ├─ gen = _get_generator(req.backend)         # 创建 LLM 客户端
   ├─ system_prompt = CHAT_SYSTEM_PROMPTS[agent_type][mode]  # 选择系统提示
   │
3. GraphRAG 上下文注入
   ├─ _build_rag_context(req.message)
   │   ├─ 用户档案: 反复话题/冲突/情绪/趋势
   │   └─ 关键词检索: 匹配 metadata.json 中的对话 top-3
   └─ system_prompt += "\n\n以下是来自用户真实聊天记录的背景信息...\n" + rag_context
          │
4. 会话管理
   ├─ 有 session_id → _load_session(id)
   ├─ 无 session_id → _create_session(agent_type, mode, backend)
   └─ 自动标题 = message[:20]
          │
5. 组装多轮 messages
   messages = [
     {"role": "system", "content": system_prompt + rag_context},
     {"role": "user", "content": "历史消息1"},
     {"role": "assistant", "content": "历史回复1"},
     ...
     {"role": "user", "content": req.message}      # 当前消息
   ]
          │
6. 保存用户消息到会话
          │
7. 调用 LLM
   ├─ 思考模型 (think in model name): 不设 max_tokens/temperature
   └─ 普通模型: max_tokens=65536, temperature=gen.temperature
          │
8. SSE 流式推送
   ├─ 逐 token: data: {"content": "..."}
   ├─ 保存完整回复到会话 JSON
   ├─ 推送 session_id: data: {"session_id": "..."}
   └─ data: [DONE]
          │
9. 前端 ChatPanel 逐 token 渲染 → 保存 session_id 用于下次续接
```

---

## 13. 附加: GraphRAG 索引构建

构建向量索引用于历史对话检索（**需要 GPU**，BGE-M3 嵌入模型 fp16 推理约 1.3 GB）。

```bash
# 构建完整索引
python scripts/advisor/run_all/_09_build_graph.py

# 从自定义输入构建
python scripts/advisor/run_all/_09_build_graph.py \
    --input advisor_out/chunks/conversation_chunks.jsonl \
    --output advisor_out/vector_index

# 增量更新
python scripts/advisor/run_all/_09_build_graph.py --incremental
```

### 输出

```
advisor_out/vector_index/
├── index.faiss            # FAISS 向量索引
├── metadata.json          # 对话片段元数据（含 conversation_text）
└── user_profile.json      # 用户关系档案
```

`user_profile.json` 内容示例:

```json
{
  "total_conversations": 100,
  "date_range": {"start": "2025-06-01", "end": "2025-12-31"},
  "recurring_topics": ["工作压力", "未来规划", "生活琐事"],
  "recurring_conflicts": ["沟通方式", "时间分配"],
  "relationship_trend": "fluctuating",
  "top_emotions": ["焦虑", "委屈", "甜蜜"],
  "communication_styles": {"ME": "追逐型", "OTHER": "回避型"}
}
```

> 构建索引后，Phase 8 实时对话服务会在启动时自动加载 metadata.json 和 user_profile.json，无需 GPU。

---

## 14. 附加: 数据增强与蒸馏

从外部心理咨询数据集导入数据，通过多教师模型蒸馏扩充训练集。

```bash
# 从 PsyCLIENT-CP 数据集蒸馏
python scripts/advisor/run_all/_10_augment_data.py \
    --dataset PsyCLIENT-CP \
    --data-path /path/to/dataset

# 指定教师模型
python scripts/advisor/run_all/_10_augment_data.py \
    --dataset CPsDD \
    --data-path /path/to/data \
    --logic-teacher deepseek \
    --style-teacher grok
```

教师模型配置从环境变量读取（与 Phase 2 共用 `.env.advisor`）。

---

## 15. 云端模型配置参考

### 当前实际可用模型（已测试）

| 平台 | 可用模型 |
|------|----------|
| **example proxy** (key1 Claude专用) | claude-sonnet-4.5-think ✅, claude-sonnet-4 ✅, claude-haiku-4.5 ✅ |
| **example proxy** (key2/3 通用) | DeepSeek-V3.2 ✅, grok-4.1-thinking ✅, Qwen3-235B ✅, glm4.7 ✅, gemini-3-pro ✅ |
| **backup provider.com** | gpt-5 ✅, deepseek-v3.1 ✅, gemini-2.5-pro ✅, grok-4.1-thinking ✅ |
| **websee.top** | claude-sonnet-4.5-thinking ✅, grok-4.1-thinking ✅, grok-4-fast ✅ |
| **本地** | Ollama qwen3:8b ✅ |

### 推荐组合

| 场景 | 推荐 | 原因 |
|------|------|------|
| **日常生成** | DeepSeek V3.2 / Grok 4.1 | 性价比高，思考链强 |
| **质量审核** | Claude Sonnet 4.5 | 推理深度最好 |
| **精神分析** | Claude Sonnet 4.5 | 复杂心理分析洞察力 |
| **实时对话** | Grok 4.1 thinking | 流式快，质量高 |
| **测试/调试** | Ollama qwen3:8b | 免费，离线 |

---

## 16. 隐私策略与数据分流

### 核心原则

> **云端分析 → L2 数据（ME/OTHER 匿名）**
> **本地训练 → L1 数据（真实姓名）**

| 阶段 | 数据 | 原因 |
|------|------|------|
| Phase 1 提取 | **L2** | 片段将发送到云端 |
| Phase 2 分析 | **L2** | 云端 LLM 只看到 ME/OTHER |
| Phase 3 审核 | L2 分析结果 | 不含真实姓名 |
| Phase 5 格式化 | **L1 + L2 分析** | 合并真实上下文 + 匿名分析 |
| Phase 6 训练 | **L1** | 本地 GPU，数据不离开本机 |
| Phase 8 对话 | **L1** | 本地推理或云端匿名 |

### SafetyLayer P0

- 云端 `rationale_private` **不注入**本地模型上下文
- 仅 `analysis_features` 经 `sanitize_for_local()` 过滤后进入本地

---

## 17. 云端训练费用估算

基于实测: L1 ≈ ~1.4M tokens, L2 ≈ ~1.9M tokens

### Phase 2 分析费用（100 片段 × 3 Agent）

| 后端 | 3 种合计 |
|------|----------|
| DeepSeek V3.2 | **~$1.45** ⭐ |
| GLM | ~$0.42 |
| Qwen Cloud | ~$1.39 |
| GPT-5 | ~$6.60 |
| Claude 4.5 | ~$9.72 |

**推荐**: DeepSeek 生成 + Claude 审核 ≈ **$6.40 总计**

---

## 18. 常见问题

### Q: 如何快速验证整条链路？

```bash
# 1. 提取 5 个测试片段
python scripts/advisor/run_all/_01_extract_conversations.py \
    --input-file timeline_out/agent_sft_test.jsonl --num 5

# 2. 用 Grok 生成分析
python scripts/advisor/run_all/_02_generate_analysis.py \
    --backend grok --agent-type neutral --limit 5

# 3. AI 审核
python scripts/advisor/run_all/_03b_ai_review.py --agent-type neutral --limit 5

# 4. 启动前端验证
source local_secrets/.env.advisor
uvicorn scripts.advisor.api.server:app --reload --port 8787 &
cd frontend && npm run dev
# → 打开 http://localhost:5173 验证仪表盘、对话、审核
```

### Q: Connection error 使用本地 qwen3

确保 Ollama 正在运行，且 `.env.advisor` 配置正确:

```bash
export QWEN_LOCAL_API_KEY="not-needed"
export QWEN_LOCAL_BASE_URL="http://localhost:11434/v1"
export QWEN_LOCAL_MODEL="qwen3:8b"
```

### Q: 对话回复被截断

思考模型（如 grok-4.1-thinking）的 `<think>` 推理过程消耗大量 token。后端已自动处理：检测到模型名含 `think` 时不设置 `max_tokens`，让模型用满上下文窗口。

### Q: Agent 回复末尾出现字数

系统提示已优化为「不要在回复中提及字数」，如仍出现，检查是否使用了最新的 system prompt。

### Q: 用哪个后端最划算？

**DeepSeek V3.2** 性价比最高。对话推荐 **Grok 4.1 thinking**（流式快、质量高）。

### Q: 显存不够怎么办？

- 训练: `batch_size=1` + `gradient_accumulation=16` + 4-bit NF4
- 推理: 4-bit 量化（已默认）
- 切换模型: `gc.collect()` + `torch.cuda.empty_cache()`

---

**文档版本**: v3.0
**创建时间**: 2026-07-15
**最后更新**: 2026-02-10
