# Lens — 四条流水线主干文件清单

> **创建时间**: 2026-02-16
> **来源**: `/data/CHAT_APP_DHA/ls/`（仅复制运行框架脚本和必要配置，不含数据/模型/输出/缓存）
> **用途**: 独立修改计划空间，不影响主仓库

---

## 文件统计

| 类别 | 文件数 | 大小 |
|------|--------|------|
| 顶层入口 + 依赖 | 4 | ~24KB |
| scripts/ | ~140 | ~2.2MB |
| configs/ | 16 | ~75KB |
| frontend/src/ | ~15 | ~30KB |
| **总计** | **~166** | **~2.5MB** |

---

## 流水线 0: 归一化数据处理（Universal Ingestion）

**入口**: `scripts/workspace/init_workspace.py` + `scripts/workspace/run_ingest.py`

**功能**: 将来自不同即时通讯平台的异构导出数据，统一转换为下游流水线可消费的标准格式 `P1_messages_raw.jsonl` 及标准媒体目录

**执行顺序**:

```
source_manifest.yaml 配置 → AdapterRegistry 自动发现适配器 → adapter.parse 逐条解析
→ validate_message Schema 校验 → MediaOrganizer 媒体归类+去重 → ts 时间排序
→ P1_messages_raw.jsonl + raw/ 标准媒体目录
```

| 目录/文件 | 说明 |
|-----------|------|
| `scripts/workspace/init_workspace.py` | 工作空间初始化，生成 `source_manifest.yaml` 模板 |
| `scripts/workspace/run_ingest.py` | 归一化引擎入口，驱动 AdapterRegistry + IngestionEngine |

**支持的数据源适配器**:

| source_type | 适配器 | 输入格式 | msg_uid 前缀 |
|-------------|--------|----------|-------------|
| `CHAT_APP_html` | CHAT_APPAdapter | HTML + CSV | `P1:` |
| `telegram_json` | TelegramAdapter | result.json | `TG:` |
| `whatsapp_txt` | WhatsAppAdapter | *.txt | `WA:` |
| `generic_csv` | GenericCSVAdapter | *.csv | 自定义 |
| `generic_jsonl` | GenericJSONLAdapter | *.jsonl | 自定义 |

**输出**:
- `P1_messages_raw.jsonl` — 统一 Canonical Schema（msg_uid / ts / speaker / modality / text_raw 等 27 个字段）
- `raw/image/`, `raw/voice/`, `raw/video/`, `raw/sticker/`, `raw/file/` — 标准媒体目录（SHA-256 去重）

**依赖配置**: `source_manifest.yaml`（用户自定义，不纳入版本控制）

---

## 流水线 1: 多模态数据处理（Multimodal Processing）

**入口**: `run_all_pipelines.py`

**功能**: 将原始聊天数据（图片/语音/视频/表情包/链接文件）处理为统一的 enriched timeline

**执行顺序**: image → voice → video → sticker → linkfile

| 目录 | 文件数 | 说明 |
|------|--------|------|
| `scripts/image/run_all/` | 5 | OCR → Caption → Compress → Merge → Update Timeline |
| `scripts/image/` | 2 | router.py, loader.py（支撑模块） |
| `scripts/voice/run_all/` | 6 | FunASR → Emotion → Compress → Merge → Update Timeline |
| `scripts/video/run_all/` | 6 | Extract → Transcribe → Caption → Compress → Merge → Update Timeline |
| `scripts/video/` | 1 | sync_video_to_slim.py |
| `scripts/sticker/run_all/` | 9 | Download → Sniff → Process → Triage → Caption → Compress → Merge → Update → Cleanup |
| `scripts/linkfile/run_all/` | 4 | Extract+Anonymize → File Summary → Merge → Update Timeline |
| `scripts/linkfile/` | 1 | extractor.py |
| `scripts/_common/` | 9 | 共享工具（anonymizer, jsonl_utils, path_utils, schema_utils, text_normalize, media_filter...） |
| `scripts/timeline/` | 5 | 时间轴后处理 + 匿名化 |
| `scripts/extract/` | 3 | 原始数据提取 |
| `scripts/workspace/` | 2 | 工作空间管理 |

**依赖配置**: `configs/paths.yaml`, `configs/caption.yaml`, `configs/voice.yaml`, `configs/video.yaml`, `configs/sticker.yaml`, `configs/linkfile.yaml`, `configs/media_filter.yaml`, `configs/hotword.txt`, `configs/timeline_postprocess.yaml`, `configs/confirmed_names.yaml.template`

---

## 流水线 2: Agent 分析 + SFT 训练（Analysis + Training）

**入口**: `run_agent_sft_pipeline.sh`

**功能**: 从 enriched timeline → LLM 分析 → MoA 融合 → 审核 → SFT 数据格式化 → QLoRA 训练 → 评估

**执行顺序**:

```
_00 环境验证 → _01 提取对话 → _02 生成分析 → _02b 多模型对比 → _02c MoA 融合
→ _03 导出审核 → _03b AI 审核 → _04 导入审核 → _05 格式化 SFT → _05b 过滤分层
→ _05c 反匿名化 → _06 QLoRA 训练 → _07 推理 → _07b 评估对比
```

| 目录 | 文件数 | 说明 |
|------|--------|------|
| `scripts/advisor/run_all/` | 19 | _00 ~ _10 全部步骤脚本 |
| `scripts/advisor/` | 25 | 核心模块（config, schemas, analyzers, generator, formatter, extractor, augmentor, pipeline_executor, model_router, key_rotator, schema_validator, errors, trainer, safety_layer...） |
| `scripts/compression/` | 18 | SFT trimmer, optimizer, PII detector, privacy shield, quality validator |
| `scripts/compression/two_stage_pii/` | 6 | 两阶段 PII 扫描子模块 |
| `scripts/timeline/` | 5 | postprocess + anonymization（与流水线 1 共享） |

**依赖配置**: `configs/advisor.yaml`, `configs/anonymization.yaml`, `configs/compression.yaml`, `configs/sft_optimizer.yaml`, `configs/router.yaml`

---

## 流水线 3: 推理 + RAG + API 服务（Inference + RAG + Serving）

**入口**: `python scripts/advisor/api/server.py`（FastAPI 端口 8787）

**功能**: 加载 SFT 模型 → RAG 检索增强 → API 服务 → 前端交互（listen/consult 模式）

| 目录 | 文件数 | 说明 |
|------|--------|------|
| `scripts/advisor/api/server.py` | 1 | FastAPI 主服务（~112KB，核心入口） |
| `scripts/advisor/inference.py` | 1 | 模型推理引擎 |
| `scripts/advisor/chunk_based_rag.py` | 1 | FAISS + BGE-M3 + Reranker RAG |
| `scripts/advisor/graph_rag.py` | 1 | GraphRAG 向量索引 |
| `scripts/advisor/graph_rag_enhanced.py` | 1 | 增强版 GraphRAG |
| `scripts/advisor/intent_classifier.py` | 1 | 意图分类（5 类） |
| `scripts/advisor/query_rewriter.py` | 1 | 查询改写 |
| `scripts/advisor/safety_layer.py` | 1 | 安全层（危机检测） |
| `scripts/advisor/streaming.py` | 1 | SSE 流式响应 |
| `frontend/` | ~15 | React 18 + TypeScript + Vite + TailwindCSS 前端 |

**依赖配置**: `configs/advisor.yaml`, `configs/paths.yaml`

---

## 共享文件

| 文件 | 说明 |
|------|------|
| `requirements.txt` | Python 依赖 |
| `environment.yml` | Conda 环境定义 |
| `configs/` (16 files) | 所有 YAML 配置 |
| `scripts/_common/` (9 files) | 匿名化、JSONL 工具、路径工具、Schema 工具等 |

---

## 未包含的文件（有意排除）

| 类别 | 原因 |
|------|------|
| `data/`, `raw/` | 原始聊天数据（隐私） |
| `timeline_out/`, `advisor_out/` | 流水线输出（数据文件） |
| `artifacts/` | 中间处理结果 |
| `/data/models/` | 模型权重（太大） |
| `node_modules/`, `dist/` | 前端构建产物 |
| `__pycache__/` | Python 缓存 |
| `.git/` | Git 历史 |
| `tests/` | 测试文件（非运行框架） |
| `docs/` | 文档 |
| `research/` | 调研资料 |
| `logs/`, `local_secrets/` | 日志/密钥 |
| `unsloth_compiled_cache/` | Unsloth 编译缓存 |
