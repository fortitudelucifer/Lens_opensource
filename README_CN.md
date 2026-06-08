# wechatDHA — 微信多模态数据集与关系顾问流水线

> 将微信聊天记录转化为高质量多模态数据集，用于大语言模型微调，并集成 AI 关系顾问系统。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)

[English](README.md) | 中文

## 概述

wechatDHA 是一个端到端的数据处理流水线，将微信聊天导出的原始数据（文本、图片、语音、视频、表情包、链接和文件）转化为结构化、隐私安全的 JSONL 数据集，适用于大语言模型的监督微调（SFT）。在数据流水线之上，还包含一个基于处理后数据训练的全栈 AI 关系顾问系统。

### 核心能力

- **多模态处理**：五条专用子流水线分别处理图片、语音、视频、表情包和链接/文件消息
- **通用数据接入**：插件式适配器架构，支持微信、Telegram、WhatsApp 及通用 CSV/JSONL 导入
- **隐私优先设计**：两级匿名化（L1 可逆 / L2 不可逆），两阶段 PII 检测（规则引擎 + LLM 验证）
- **智能分析**：OCR 路由、VLM 描述生成、ASR 转写、情绪检测、语义压缩，覆盖所有模态
- **专家模型路由**：内容感知的分诊系统，将 NSFW、暴力和文档图片路由到专用的无审查模型
- **关系顾问 Agent**：MoA（多模型融合）分析、QLoRA 微调、Hybrid RAG 实时对话，支持 3 种 Agent 人格
- **Web 仪表盘**：React + Vite 前端，支持流水线控制、实时对话、人工审核和模型管理

---

## 系统架构

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           wechatDHA 流水线                                  │
│                                                                             │
│  ┌─────────────┐   ┌──────────────────────────────────────────────────┐    │
│  │  通用数据    │   │           多模态处理流水线                       │    │
│  │  接入引擎    │──▶│  图片 │ 语音 │ 视频 │ 表情包 │ 链接/文件       │    │
│  │  (5种适配器) │   └────────────────────┬───────────────────────────┘    │
│  └─────────────┘                         │                                │
│                                          ▼                                │
│                              ┌──────────────────────┐                     │
│                              │  统一时间轴            │                     │
│                              │  enriched_full.jsonl   │                     │
│                              └──────────┬───────────┘                     │
│                                         │                                 │
│                          ┌──────────────┼──────────────┐                  │
│                          ▼              ▼              ▼                  │
│                   ┌────────────┐ ┌────────────┐ ┌────────────┐           │
│                   │ Agent SFT  │ │ 关系顾问   │ │ Web        │           │
│                   │ 数据流水线  │ │ 流水线     │ │ 仪表盘     │           │
│                   │ L1/L2 数据 │ │ MoA+QLoRA  │ │ React+Vite │           │
│                   └────────────┘ └────────────┘ └────────────┘           │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 多模态处理流水线

每个模态都有专用的子流水线，位于 `scripts/<模态>/run_all/`。所有流水线遵循相同模式：**提取 → 分析 → 压缩（可选）→ 合并 → 更新时间轴**。

### 图片流水线（4 步）

| 步骤 | 脚本 | 描述 | 模型 |
|------|------|------|------|
| 1. OCR | `_01_run_ocr.py` | 智能路由（文本密集/照片/混合）+ PaddleOCR PP-OCRv4，检测框复用加速 30-40% | PaddleOCR v4 |
| 2. 描述 | `_02_run_caption.py` | 分诊分类（NSFW/暴力/普通/文档）→ 专家路由分发到专用模型 | Qwen2.5-VL-7B, MiniCPM-V 4.5, Pixtral 12B |
| 2.5. 压缩 | `_02.5_run_compress.py` | 语义压缩（4-5 倍压缩比） | Qwen2.5-7B |
| 3. 合并 | `_03_merge_engine.py` | 合并 OCR + 描述结果 | — |
| 4. 时间轴 | `_04_update_timeline.py` | 回写主时间轴 | — |

**专家模型路由：**
- `TYPE_C_NORMAL` → Qwen2.5-VL-7B-Instruct（主力描述模型）
- `TYPE_A_NSFW` → 双模型融合：MiniCPM-V 4.5 Abliterated (int8) + qwen2.5-vl-7b-nsfw-caption-v3
- `TYPE_B_GORE` → Qwen2.5-VL Abliterated (4-bit)，添加警告标记
- `TYPE_D_DOC` → Pixtral 12B GGUF (Q5_K_M)，用于文档/截图分析

### 语音流水线（4 步）

| 步骤 | 脚本 | 描述 | 模型 |
|------|------|------|------|
| 1. ASR | `_01_run_funasr.py` | FunASR（paraformer-zh + VAD + 标点），支持热词增强；可选 Whisper 备用 | FunASR, Whisper |
| 2. 情绪 | `_02_run_emotion.py` | 四阶段：SenseVoice 快速检测 → 关键词分诊 → Qwen2-Audio 深度分析 → 人工审核文件 | SenseVoice, Qwen2-Audio-7B |
| 2.5. 压缩 | `_02.5_run_compress.py` | 压缩冗余情感分析，保留转写文本 | Qwen2.5-7B |
| 3. 合并 | `_03_merge_engine.py` | 合并 FunASR + Whisper + 情绪结果 | — |
| 4. 时间轴 | `_04_update_timeline.py` | 回写主时间轴 | — |

**情绪分类体系：** 6 大类、20+ 种细粒度标签（有毒、亲密、痛苦、掩饰、基础、认知）。

### 视频流水线（5 步）

| 步骤 | 脚本 | 描述 | 模型 |
|------|------|------|------|
| 1. 提取 | `_01_run_extract.py` | 自适应关键帧提取，使用光流运动检测 + 场景变化分析 | ffmpeg, OpenCV |
| 2. 转写 | `_02_run_transcribe.py` | 音频转写 + 情绪检测（复用语音流水线） | FunASR, SenseVoice |
| 3. 描述 | `_03_run_caption.py` | 逐帧分诊 + 专家路由；模型拒绝时自动切换 LLaVA-NeXT-Video | Qwen2.5-VL-7B, LLaVA-NeXT-Video-7B |
| 3.5. 压缩 | `_03.5_run_compress.py` | 多帧描述压缩（10 倍压缩比） | Qwen2.5-7B |
| 4. 合并 | `_04_merge_engine.py` | 合并提取 + 转写 + 描述结果 | — |
| 5. 时间轴 | `_05_update_timeline.py` | 回写主时间轴 | — |

### 表情包流水线（8 步）

| 步骤 | 脚本 | 描述 |
|------|------|------|
| 1. 下载 | `_01_run_download.py` | 从 URL 下载表情包，SHA256 去重 |
| 2. 嗅探 | `_02_run_sniff.py` | Magic Bytes 格式检测（GIF/WebP/PNG/JPEG），Pillow 解码验证 |
| 3. 处理 | `_03_run_process.py` | 动图/静图分类，自适应帧采样（4-16 帧），Contact Sheet 生成 |
| 4. 分诊 | `_04_run_triage.py` | 逐帧 NSFW/暴力检测，取最高分聚合 |
| 5. 描述 | `_05_run_caption.py` | VLM 描述生成，敏感内容使用专家路由 |
| 5.5. 压缩 | `_05.5_run_compress.py` | 意图映射 + 字典化压缩（重复表情包最高 15 倍压缩） |
| 6. 合并 | `_06_merge_engine.py` | 合并所有阶段结果，SHA256 去重 |
| 7. 时间轴 | `_07_update_timeline.py` | 回写主时间轴 |
| 8. 清理 | `_08_cleanup_frames.py` | 删除临时帧文件 |

### 链接/文件流水线（3 步，纯 CPU）

| 步骤 | 脚本 | 描述 |
|------|------|------|
| 1. 提取 | `_01_extract_and_anonymize.py` | 策略模式路由：引用 / 链接 / 文件 / 小程序 / 视频号 / 聊天记录 |
| 1.5. 摘要 | `_01.5_run_file_summary.py` | 生成文件内容摘要 |
| 2. 合并 | `_02_merge_engine.py` | 统一 Schema 合并 |
| 3. 时间轴 | `_03_update_timeline.py` | 回写主时间轴 |

---

## 共享工具库（`scripts/_common/`）

所有模态流水线共享一组通用工具模块，处理跨模态的公共逻辑：

### 文本归一化（`text_normalize.py`）

多阶段文本归一化流水线，主要用于 ASR 转写后处理：

```
原始文本 → to_simplified() → strip_punc() → ct-punc → dedup_punc() → apply_patches() → fix_false_question()
```

| 函数 | 功能 | 示例 |
|------|------|------|
| `to_simplified()` | 繁体→简体转换（OpenCC `t2s`，短语级） | `雲頂之弈` → `云顶之弈` |
| `strip_punc()` | 移除现有标点（ct-punc 前清洗，避免双重标点） | `你好，世界！` → `你好 世界` |
| `dedup_punc()` | 去重重复标点（ct-punc 后清洗） | `你好，，世界。。` → `你好，世界。` |
| `apply_patches()` | 可控纠错：ASR 专名错误修正（附审计日志） | `云顶之翼` → `云顶之弈` |
| `fix_false_question()` | 保守式标点修复：仅修正特定"非疑问语气"句末问号 | `什么的？` → `什么的。` |
| `prepare_for_punc()` | 一键流水线辅助：繁简转换 + 标点清洗 | 输出可直接送入 ct-punc |

### 匿名化工具（`anonymizer.py`）

统一的姓名匿名化处理，4 种策略：

| 函数 | 作用范围 | 示例 |
|------|----------|------|
| `anonymize_speaker_prefix()` | 引用消息说话人前缀 | `UserB：是考在职吗` → `OTHER: 是考在职吗` |
| `anonymize_text()` | 通用文本姓名替换 | `UserB recalled a message` → `OTHER recalled a message` |
| `anonymize_recalled_message()` | 撤回消息模式 | `"UserB 某大学" recalled a message` → `OTHER recalled a message` |
| `anonymize_message_text()` | 统一入口（按 msg_type 自动选择策略） | 自动路由到合适的函数 |

通过 `configs/anonymization.yaml` 配置 `me_names` / `other_names` 列表。未知说话人默认为 `OTHER`（隐私安全）。

### 媒体质量过滤（`media_filter.py`）

4 级质量过滤系统，覆盖图片、视频和表情包：

| 级别 | 决策 | 描述 |
|------|------|------|
| `PROCESS` | 正常处理 | 满足所有质量阈值 |
| `SKIP_LOW_QUALITY` | 跳过并标记 | 低于最低分辨率/时长/大小 |
| `SKIP_DOWNLOAD_FAILED` | 跳过并标记 | 媒体文件下载或解码失败 |
| `SKIP_DECODE_FAILED` | 跳过并标记 | 媒体文件无法解码 |

每个模态有独立的过滤函数（`filter_image()`、`filter_video()`、`filter_sticker()`），阈值通过 `configs/media_filter.yaml` 配置。

### 其他共享模块

| 模块 | 功能 |
|------|------|
| `schema_utils.py` | 统一 `merged_v2` Schema 构建器、字段排序、旧版记录迁移 |
| `jsonl_utils.py` | JSONL 读写：`load_jsonl_by_key()`（字典模式）、`load_jsonl_list()`、`write_jsonl()`、`update_jsonl_in_place()`（原子操作+自动备份） |
| `path_utils.py` | 集中式路径管理：加载 `configs/paths.yaml`，提供 `get_path()`，各模态目录 getter |
| `check_paths.py` | 工作空间路径验证 |
| `download_models.py` | 一键模型下载器，下载所有必需模型 |

---

## Agent SFT 数据流水线

多模态处理完成后，Agent SFT 流水线将富化时间轴转化为训练数据：

```
enriched_full.jsonl
       │
       ▼
  时间轴后处理（消息合并、时间间隔标记）
       │
       ├──── L1 分支（本地训练）────┐
       │     字段精简 → SFT 优化    │──▶ agent_sft_l1.jsonl
       │                            │
       ├──── L2 分支（云端训练）────┐│
       │     两阶段 PII 匿名化     ││
       │     → 字段精简             ││──▶ agent_sft_l2.jsonl
       │     → SFT 优化            │
       │                            │
       └──── 质量验证 ──────────────┘
```

运行方式：
```bash
./run_agent_sft_pipeline.sh              # L1 和 L2 都生成
./run_agent_sft_pipeline.sh --only l1    # 仅 L1
./run_agent_sft_pipeline.sh --only l2    # 仅 L2
```

---

## 关系顾问系统

基于处理后聊天数据构建的全栈 AI 关系顾问：

### 离线流水线（10+ 阶段，16 个脚本）

| 阶段 | 脚本 | 描述 | 模型 / 工具 |
|------|------|------|-------------|
| 0 | `_00_verify_environment.py` | 验证 Python 依赖（torch、transformers、peft、bitsandbytes、trl、datasets、accelerate）、CUDA/GPU、基座模型文件、测试 4-bit 量化加载+推理 | Qwen3-8B-Instruct (NF4) |
| 1 | `_01_extract_conversations.py` | 从 SFT 数据（L1/L2）滑动窗口提取对话片段。窗口 20 条，步长 10，最少 10 条。自动分类：冲突/甜蜜/普通 | — |
| 2a | `_02_generate_analysis.py` | 单后端 LLM 分析。支持 9 种后端（OpenAI、Claude、Gemini、Kimi、Grok、DeepSeek、Qwen 本地/云端、GLM）。断点续跑 | 9 种 LLM 后端任选 |
| 2b | `_02b_model_comparison.py` | 多后端并排对比，在代表性片段上生成 Markdown 对比报告 | 多后端 |
| 2c | `_02c_fusion_pipeline.py` | **MoA（多模型融合）流水线** — 核心分析引擎（详见下方） | Claude + GPT + Gemini + Grok |
| 2c' | `_02c_rerun_moa.py` | 对失败/低质量片段重新运行 MoA 融合 | 同 2c |
| 3a | `_03_export_for_review.py` | 导出分析结果供人工审核 | — |
| 3b | `_03b_ai_review.py` | AI 辅助质量审核，逐维度评分。弱维度自动补齐 | Grok / Kimi |
| 4 | `_04_import_reviewed.py` | 导入人工审核通过的分析结果 | — |
| 5a | `_05_format_training_data.py` | 转换为 SFT 格式（JSONL 或 Alpaca）。数据源优先级：MoA > 审核后 > 原始。自动剥离冗余字段（claude_raw、gpt_raw） | — |
| 5b | `_05b_filter_split_training.py` | 质量过滤（最少 13 个【】字段）+ OTHERHER bug 修正 + 按关系状态分层采样划分 train/val/test（80/10/10） | — |
| 5c | `_05c_deanonymize_training.py` | 反匿名化：ME/OTHER → 真实姓名，Day N → 真实日期，时间范围提取 | — |
| 6 | `_06_train_model.py` | QLoRA 微调（4-bit NF4，LoRA r=16 α=32）。支持 HuggingFace 标准和 Unsloth（快 2 倍）两种后端。断点续训，val_loss 监控 | Qwen3-8B-Instruct |
| 7a | `_07_run_inference.py` | 交互/单条/批量推理。自动检测最佳 LoRA（Unsloth deanon > HF deanon > 旧版） | Qwen3-8B + LoRA |
| 7b | `_07b_eval_compare.py` | 评估：ROUGE-L F1、字段完整性、基座 vs 微调对比 | — |
| 8 | `_08_run_dialogue.py` | 实时终端对话，listen/consult 双模式，流式输出，GraphRAG 上下文检索 | Ollama（本地）/ DeepSeek（云端） |
| 9 | `_09_build_graph.py` | 构建 FAISS 向量索引（BGE-M3 嵌入 + BGE-Reranker-V2-M3 重排）。全量/增量模式。生成用户档案（反复话题、冲突模式、关系趋势） | BGE-M3, BGE-Reranker-V2-M3 |
| 10 | `_10_augment_data.py` | 多教师蒸馏，从外部数据集（PsyCLIENT-CP、CPsDD、AuraDial）导入。逻辑教师（DeepSeek Reasoner）+ 风格教师（Claude Opus）双教师架构。质量过滤 | DeepSeek Reasoner, Claude Opus |

### MoA 融合流水线（阶段 2c）— 详解

MoA（Mixture of Agents）融合流水线是核心分析引擎，编排多个前沿 LLM 进行 4 阶段处理：

```
                    ┌─────────────────────────────────────────────┐
                    │           MoA 融合流水线                     │
                    │                                             │
  对话片段 ──────▶  │  S1: 并行专家分析                            │
                    │    ├── Claude Opus → 结构化分析              │
                    │    ├── GPT → 结构化分析                      │
                    │    └── Gemini → 结构化分析（仅多模态片段）    │
                    │                         │                   │
                    │  S2: MoA 聚合           ▼                   │
                    │    └── Grok 融合所有专家输出                  │
                    │         为统一 JSON（6+ 字段）               │
                    │                         │                   │
                    │  S3: 质量审核           ▼                   │
                    │    └── Grok 逐维度评分（1-10 分）            │
                    │         通过 / 需修改 / 不合格               │
                    │                         │                   │
                    │  S4: 补齐循环           ▼                   │
                    │    └── 定向补齐 ≤7 分的维度                  │
                    │         最多 3 轮，每轮重新审核              │
                    │         降级链: Grok → Gemini → Kimi         │
                    └─────────────────────────────────────────────┘
```

**核心特性：**
- **多模型降级链**：Claude（主线）→ Claude 备用 → Claude 降级（Sonnet）；Grok（主线）→ Grok 备用 → Gemini → Kimi
- **多模态感知**：Gemini 仅在片段包含多模态内容（图片、语音、视频描述）时调用
- **Thinking 模型截断检测**：检测 `<think>` 标签截断，自动切换到非 thinking 备用
- **Cloudflare HTML 错误检测**：代理返回 HTML 时自动等待 30s 重试
- **Key Pool 轮换**：多 Key 轮询，支持单 Key 黑名单、紧急模式、全局 RPM 限制（≤19）
- **流水线模式**：异步 4 级流水线，可配置 S1 并发和 Grok 并发（`--pipeline --max-s1 2 --max-grok 3`）
- **断点续跑**：扫描输出文件已完成的 chunk_id，跳过已处理片段

```bash
# 标准 MoA 融合（串行）
python scripts/advisor/run_all/_02c_fusion_pipeline.py --moa --agent-type neutral

# 流水线模式（并发）
python scripts/advisor/run_all/_02c_fusion_pipeline.py --pipeline --max-s1 2 --max-grok 3

# 多 Worker + Key Pool
python scripts/advisor/run_all/_02c_fusion_pipeline.py --moa --workers 3 --key-pool local_secrets/key_pool.yaml

# 切换 MoA 聚合器到 Kimi（Grok 不稳定时）
python scripts/advisor/run_all/_02c_fusion_pipeline.py --moa --grok-backend kimi
```

### 三种 Agent 人格 × 两种模式

| Agent | 方法 | 理论框架 |
|-------|------|----------|
| 中立顾问 | 客观多维分析 | 沟通模式、依附风格、NVC、权力动态 |
| 支持性顾问 | 无条件站在用户一方 | 情感验证、保护性建议、边界设立 |
| 精神分析顾问 | 无意识层面深度分析 | 客体关系、拉康三界、防御机制、移情 |

| 模式 | 回复风格 |
|------|----------|
| 倾听 | 5-7 句，共情为主，开放性问题引导 |
| 咨询 | 完整结构化分析（500-2500 字），多维度 |

### 在线服务

- **后端：** FastAPI（端口 8787），SSE 流式响应，多轮会话管理，对话历史压缩
- **前端：** React 19 + Vite + Tailwind CSS 仪表盘，支持对话、流水线控制、人工审核、模型管理、API Key 检测
- **RAG：** 三层检索 — 日期精确查找（Day Index）+ FAISS 语义搜索（BGE-M3）+ 关键词回退 + FAQ 知识库
- **LLM 后端：** 9 种后端统一 OpenAI 兼容接口（GPT、Claude、Gemini、Grok、DeepSeek、Qwen、GLM、Kimi、本地 Ollama）
- **安全：** SafetyLayer P0、GlobalRateLimiter（RPM≤19）、后端自动故障转移、Ollama 看门狗自动重启
- **会话管理：** 持久化会话，支持 Agent 类型/模式切换、记忆事实提取、历史截断

---

## 通用数据接入

插件式适配器架构，支持从多个平台导入聊天数据：

| 适配器 | 数据源 | 格式 |
|--------|--------|------|
| `wechat_html` | 微信桌面版导出 | HTML + CSV |
| `telegram_json` | Telegram 桌面版导出 | result.json |
| `whatsapp_txt` | WhatsApp 导出 | *.txt（8 种日期格式） |
| `generic_csv` | 任意 CSV | field_mapping DSL |
| `generic_jsonl` | 任意 JSONL | field_mapping DSL |

所有适配器输出统一的 Canonical Schema（`P1_messages_raw.jsonl`），直接进入下游模态处理流水线。

```bash
# 自动检测数据源类型并接入
python scripts/workspace/run_ingest.py --workspace /path/to/workspace

# 指定数据源类型
python scripts/workspace/run_ingest.py --workspace /path/to/workspace --source-type telegram_json

# 预检模式（预览不写入）
python scripts/workspace/run_ingest.py --dry-run
```

---

## 隐私与匿名化

### 两级系统

| 级别 | 用途 | 可逆 | PII 处理 |
|------|------|------|----------|
| **L1** | 本地训练 | 是（本地保险库） | 姓名 → ME/OTHER，时间戳保留 |
| **L2** | 云端训练 | 否 | 完全 PII 清洗，时间戳偏移，地名替换 |

### 两阶段 PII 检测

1. **阶段一（离线扫描）：** 规则候选词提取 → LLM 验证（Qwen2.5-7B-AWQ）→ 人工审核 → 确认人名列表
2. **阶段二（运行时）：** 基于确认列表的精确字符串匹配 — 零漏检，高性能

### 配置

```yaml
# configs/anonymization.yaml
me_names:
  - "你的真实姓名"
  - "你的昵称"
other_names:
  - "对方真实姓名"
  - "对方昵称"
me_alias: "ME"
other_alias: "OTHER"

# 地名映射（仅 L2）
location_mapping:
  "北京": "天津"
  "上海": "杭州"

# 排除列表（公众人物等）
exclude_patterns:
  - "毛泽东"
  - "李白"
```

---

## 快速开始

### 环境要求

- Python 3.10+
- NVIDIA GPU，16GB+ 显存（推荐 RTX 4070 Ti / 5070 Ti 及以上）
- CUDA 12.x
- Conda

### 安装

```bash
git clone https://github.com/your-repo/wechatDHA.git
cd wechatDHA

# 创建 conda 环境
conda create -n wechatDHA python=3.10
conda activate wechatDHA

# 安装依赖
pip install -r requirements.txt

# 下载所需模型（PaddleOCR、FunASR、Qwen2.5-VL 等）
python scripts/_common/download_models.py
```

### 工作空间初始化

```bash
# 初始化新工作空间
python scripts/workspace/init_workspace.py \
    --template demo \
    --contact-name "对方姓名"
```

将导出的微信数据放入工作空间的 `raw/` 目录。

### 配置

1. 编辑 `configs/anonymization.yaml` 设置身份映射
2. 编辑 `configs/paths.yaml` 设置工作空间名称
3. （可选）编辑 `configs/` 下的各模态配置文件

### 运行流水线

```bash
# 运行所有模态流水线（图片 → 语音 → 视频 → 表情包 → 链接/文件）
python run_all_pipelines.py

# 运行指定模态
python run_all_pipelines.py --only voice video

# 跳过压缩步骤（更快）
python run_all_pipelines.py --skip-compression

# 预览模式（不实际执行）
python run_all_pipelines.py --dry-run

# 遇到错误继续执行
python run_all_pipelines.py --continue-on-error
```

### 生成 SFT 训练数据

```bash
./run_agent_sft_pipeline.sh
```

### 启动顾问服务

```bash
# 加载 API Key
source local_secrets/.env.advisor

# 启动后端
conda run -n wechatDHA uvicorn scripts.advisor.api.server:app --reload --port 8787

# 启动前端（另一个终端）
cd frontend && npm run dev
```

---

## 硬件要求

| 组件 | 最低 | 推荐 |
|------|------|------|
| GPU | 8GB 显存 | 16GB 显存（RTX 4070 Ti / 5070 Ti） |
| 内存 | 16GB | 32GB |
| 存储 | 50GB | 200GB+（取决于媒体量） |
| CUDA | 12.0 | 12.8+ |

**显存管理：** 所有模型串行加载（同一时间只加载一个），切换时显式清理显存。流水线设计在 16GB 显存约束下运行。

---

## 使用的模型

| 模型 | 用途 | 显存 | 量化 |
|------|------|------|------|
| PaddleOCR PP-OCRv4 | 中文 OCR | ~2GB | — |
| Qwen2.5-VL-7B-Instruct | 主力 VLM 描述 | ~8GB | bfloat16 |
| MiniCPM-V 4.5 Abliterated | NSFW 内容分析 | ~10GB | int8 |
| Pixtral 12B | 文档分析 | ~8.3GB | GGUF Q5_K_M |
| FunASR (paraformer-zh) | 中文 ASR | ~2GB | — |
| SenseVoice Small | 语音情绪检测 | ~1GB | — |
| Qwen2-Audio-7B | 深度语音情绪分析 | ~8GB | float16 |
| LLaVA-NeXT-Video-7B | 视频理解备用 | ~8GB | — |
| Qwen2.5-7B-Instruct-AWQ | 语义压缩 & PII | ~4GB | AWQ 4-bit |
| BGE-M3 | 语义嵌入（RAG） | ~2GB | — |

---

## 测试

项目使用 [Hypothesis](https://hypothesis.readthedocs.io/) 进行属性测试，配合标准单元测试：

```bash
# 运行所有测试
conda run -n wechatDHA python -m pytest tests/ -v

# 运行特定测试文件
conda run -n wechatDHA python -m pytest tests/test_advisor_analyzers_properties.py -v
```

---

## 文档

各子系统的详细文档位于 `docs/` 目录：

- [完整流水线参考](docs/pipeline.md)
- [图片流水线设计](docs/image_pipeline_overview.md)
- [语音流水线设计](docs/voice_pipeline_overview.md)
- [视频流水线设计](docs/video_pipeline_overview.md)
- [表情包流水线设计](docs/sticker_pipeline_overview.md)
- [链接/文件流水线设计](docs/linkfile_pipeline_overview.md)
- [通用数据接入](docs/ingestion_pipeline_overview.md)
- [Agent SFT 流水线](docs/agent_sft_pipeline_overview.md)
- [顾问系统](docs/advisor_pipeline_overview.md)
- [隐私与 PII 指南](docs/pii_detection_guide.md)
- [隐私映射](docs/privacy_mapping.md)

---

## 隐私声明

本项目严格分离代码与数据：

- **代码**（`scripts/`、`configs/`、`frontend/`）：可安全公开分享
- **数据**（`raw/`、`artifacts/`、`timeline_out/`）：包含个人聊天记录 — **绝不提交**
- **密钥**（`local_secrets/`）：包含 API Key 和身份保险库 — **绝不提交**

`.gitignore` 已配置排除所有数据和密钥目录。

---

## 许可证

[MIT License](LICENSE)

---

## 致谢

本项目基于以下开源模型和工具构建：

- [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) — OCR 引擎
- [FunASR](https://github.com/modelscope/FunASR) — 中文 ASR
- [SenseVoice](https://github.com/FunAudioLLM/SenseVoice) — 语音情绪检测
- [Qwen2.5-VL](https://github.com/QwenLM/Qwen2.5-VL) — 视觉语言模型
- [Qwen2-Audio](https://github.com/QwenLM/Qwen2-Audio) — 音频理解
- [LLaVA-NeXT](https://github.com/LLaVA-VL/LLaVA-NeXT) — 视频理解
- [Pixtral](https://mistral.ai/) — 文档分析
- [BGE-M3](https://github.com/FlagOpen/FlagEmbedding) — 多语言嵌入
- [Hypothesis](https://hypothesis.readthedocs.io/) — 属性测试
