# wechatDHA — WeChat Multi-Modal Dataset & Relationship Advisor Pipeline

> **Version:** v1.0.0-beta · **Phase II:** Lens Advisor roundtable released · **Status:** Beta cleanup candidate

> Transform WeChat chat history into high-quality multi-modal datasets for LLM fine-tuning, with an integrated AI relationship advisor system.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)

English | [中文](README_CN.md)

**Beta docs**: [Release Notes](RELEASE_NOTES.md) · [Quick Start](docs/QUICKSTART.md) · [Beta User Guide](docs/BETA_USER_GUIDE.md) · [Contributing](docs/CONTRIBUTING.md) · [Security](docs/SECURITY.md) · [Beta Invitation](docs/beta_invitation.md) · [Main Plan](research/big_plan/plan_v2/综合执行计划_v2.md)

## Overview

wechatDHA is an end-to-end data processing pipeline that converts raw WeChat chat exports (text, images, voice messages, videos, stickers, links, and files) into structured, privacy-safe JSONL datasets suitable for Supervised Fine-Tuning (SFT) of Large Language Models. On top of the data pipeline, it includes a full-stack AI Relationship Advisor system trained on the processed data.

### Key Capabilities

- **Multi-Modal Processing**: Five dedicated sub-pipelines for Image, Voice, Video, Sticker, and Link/File messages
- **Universal Ingestion**: Plugin-based adapter architecture supporting WeChat, Telegram, WhatsApp, and generic CSV/JSONL imports
- **Privacy-First Design**: Two-tier anonymization (L1 reversible / L2 irreversible) with two-stage PII detection (rule engine + LLM validation)
- **Intelligent Analysis**: OCR routing, VLM captioning, ASR transcription, emotion detection, and semantic compression across all modalities
- **Expert Model Routing**: Content-aware triage system that routes NSFW, gore, and document images to specialized abliterated/uncensored models
- **Lens Advisor Agent**: MoA (Mixture of Agents) fusion analysis, QLoRA fine-tuning, Hybrid RAG real-time dialogue, and multi-agent roundtable discussion
- **Web Dashboard**: React + Vite frontend for pipeline control, real-time chat, human review, and model management

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           wechatDHA Pipeline                                │
│                                                                             │
│  ┌─────────────┐   ┌──────────────────────────────────────────────────┐    │
│  │  Universal   │   │         Multi-Modal Processing Pipelines        │    │
│  │  Ingestion   │──▶│  Image │ Voice │ Video │ Sticker │ Linkfile    │    │
│  │  (5 adapters)│   └────────────────────┬───────────────────────────┘    │
│  └─────────────┘                         │                                │
│                                          ▼                                │
│                              ┌──────────────────────┐                     │
│                              │  Unified Timeline     │                     │
│                              │  enriched_full.jsonl   │                     │
│                              └──────────┬───────────┘                     │
│                                         │                                 │
│                          ┌──────────────┼──────────────┐                  │
│                          ▼              ▼              ▼                  │
│                   ┌────────────┐ ┌────────────┐ ┌────────────┐           │
│                   │ Agent SFT  │ │ Lens       │ │ Web        │           │
│                   │ Pipeline   │ │ Advisor    │ │ Dashboard  │           │
│                   │ L1/L2 data │ │ Roundtable │ │ React+Vite │           │
│                   └────────────┘ └────────────┘ └────────────┘           │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Multi-Modal Processing Pipelines

Each modality has a dedicated sub-pipeline under `scripts/<modality>/run_all/`. All pipelines follow the same pattern: **Extract → Analyze → Compress (optional) → Merge → Update Timeline**.

### Image Pipeline (4 steps)

| Step | Script | Description | Models |
|------|--------|-------------|--------|
| 1. OCR | `_01_run_ocr.py` | Smart routing (TEXT_HEAVY / PHOTO / HYBRID) + PaddleOCR PP-OCRv4 with detection box reuse (30-40% speedup) | PaddleOCR v4 |
| 2. Caption | `_02_run_caption.py` | Triage classification (NSFW/Gore/Normal/Doc) → Expert Router dispatches to specialized models | Qwen2.5-VL-7B, MiniCPM-V 4.5 Abliterated, Pixtral 12B GGUF |
| 2.5. Compress | `_02.5_run_compress.py` | Semantic compression of captions (4-5x ratio) | Qwen2.5-7B |
| 3. Merge | `_03_merge_engine.py` | Merge OCR + Caption results into unified schema | — |
| 4. Timeline | `_04_update_timeline.py` | Write back to main timeline | — |

**Expert Model Routing:**
- `TYPE_C_NORMAL` → Qwen2.5-VL-7B-Instruct (main captioning model)
- `TYPE_A_NSFW` → Dual-model ensemble: MiniCPM-V 4.5 Abliterated (int8) + qwen2.5-vl-7b-nsfw-caption-v3 with intelligent fusion
- `TYPE_B_GORE` → Qwen2.5-VL Abliterated (4-bit) with warning labels
- `TYPE_D_DOC` → Pixtral 12B GGUF (Q5_K_M) for document/screenshot analysis

### Voice Pipeline (4 steps)

| Step | Script | Description | Models |
|------|--------|-------------|--------|
| 1. ASR | `_01_run_funasr.py` | FunASR (paraformer-zh + VAD + punctuation) with hotword boosting; optional Whisper fallback | FunASR, Whisper |
| 2. Emotion | `_02_run_emotion.py` | 4-phase: SenseVoice fast detection → Keyword triage → Qwen2-Audio deep analysis → Human review file | SenseVoice, Qwen2-Audio-7B |
| 2.5. Compress | `_02.5_run_compress.py` | Compress verbose emotion analysis, preserve transcription | Qwen2.5-7B |
| 3. Merge | `_03_merge_engine.py` | Merge FunASR + Whisper + emotion results | — |
| 4. Timeline | `_04_update_timeline.py` | Write back to main timeline | — |

**Emotion Taxonomy:** 6 categories, 20+ fine-grained labels (Toxic, Intimacy, Distress, Masking, Basic, Cognitive).

### Video Pipeline (5 steps)

| Step | Script | Description | Models |
|------|--------|-------------|--------|
| 1. Extract | `_01_run_extract.py` | Adaptive keyframe extraction using optical flow motion detection + scene change analysis | ffmpeg, OpenCV |
| 2. Transcribe | `_02_run_transcribe.py` | Audio transcription + emotion detection (reuses voice pipeline) | FunASR, SenseVoice |
| 3. Caption | `_03_run_caption.py` | Per-frame triage + expert routing; LLaVA-NeXT-Video fallback for refusals | Qwen2.5-VL-7B, LLaVA-NeXT-Video-7B |
| 3.5. Compress | `_03.5_run_compress.py` | Multi-frame description compression (10x ratio) | Qwen2.5-7B |
| 4. Merge | `_04_merge_engine.py` | Merge extract + transcribe + caption results | — |
| 5. Timeline | `_05_update_timeline.py` | Write back to main timeline | — |

### Sticker Pipeline (8 steps)

| Step | Script | Description |
|------|--------|-------------|
| 1. Download | `_01_run_download.py` | Download stickers from URLs with SHA256 deduplication |
| 2. Sniff | `_02_run_sniff.py` | Magic bytes format detection (GIF/WebP/PNG/JPEG), Pillow decode verification |
| 3. Process | `_03_run_process.py` | Animated/static classification, adaptive frame sampling (4-16 frames), Contact Sheet generation |
| 4. Triage | `_04_run_triage.py` | Per-frame NSFW/Gore detection, max-score aggregation |
| 5. Caption | `_05_run_caption.py` | VLM description with expert routing for sensitive content |
| 5.5. Compress | `_05.5_run_compress.py` | Intent mapping + dictionary compression (up to 15x for repeated stickers) |
| 6. Merge | `_06_merge_engine.py` | Merge all stage results with SHA256-based deduplication |
| 7. Timeline | `_07_update_timeline.py` | Write back to main timeline |
| 8. Cleanup | `_08_cleanup_frames.py` | Remove temporary frame files |

### Linkfile Pipeline (3 steps, CPU-only)

| Step | Script | Description |
|------|--------|-------------|
| 1. Extract | `_01_extract_and_anonymize.py` | Strategy pattern routing: Quote / Link / File / Miniprogram / VideoChannel / ChatHistory handlers |
| 1.5. Summary | `_01.5_run_file_summary.py` | Generate file content summaries |
| 2. Merge | `_02_merge_engine.py` | Merge with unified schema |
| 3. Timeline | `_03_update_timeline.py` | Write back to main timeline |

---

## Shared Utilities (`scripts/_common/`)

All modality pipelines share a set of common utilities that handle cross-cutting concerns:

### Text Normalization (`text_normalize.py`)

A multi-stage text normalization pipeline primarily used for ASR post-processing:

```
Raw Text → to_simplified() → strip_punc() → ct-punc → dedup_punc() → apply_patches() → fix_false_question()
```

| Function | Purpose | Example |
|----------|---------|---------|
| `to_simplified()` | Traditional → Simplified Chinese conversion (OpenCC `t2s`) | `雲頂之弈` → `云顶之弈` |
| `strip_punc()` | Remove existing punctuation before ct-punc re-punctuation | `你好，世界！` → `你好 世界` |
| `dedup_punc()` | Deduplicate repeated punctuation after ct-punc | `你好，，世界。。` → `你好，世界。` |
| `apply_patches()` | Controlled error correction for ASR proper-noun mistakes | `云顶之翼` → `云顶之弈` (with audit log) |
| `fix_false_question()` | Conservative punctuation fix for false question marks | `什么的？` → `什么的。` (only specific patterns) |
| `prepare_for_punc()` | One-shot pipeline helper: simplify + strip punctuation | Ready for ct-punc input |

### Anonymizer (`anonymizer.py`)

Unified name anonymization with 4 strategies:

| Function | Scope | Example |
|----------|-------|---------|
| `anonymize_speaker_prefix()` | Quote message speaker prefix | `UserB：是考在职吗` → `OTHER: 是考在职吗` |
| `anonymize_text()` | General text name replacement | `UserB recalled a message` → `OTHER recalled a message` |
| `anonymize_recalled_message()` | Recalled message pattern | `"UserB 某大学" recalled a message` → `OTHER recalled a message` |
| `anonymize_message_text()` | Unified entry point (auto-selects strategy by msg_type) | Routes to appropriate function |

Configuration via `configs/anonymization.yaml` with `me_names` / `other_names` lists. Unknown speakers default to `OTHER` for privacy safety.

### Media Quality Filter (`media_filter.py`)

4-tier quality filtering system for images, videos, and stickers:

| Tier | Decision | Description |
|------|----------|-------------|
| `PROCESS` | Full processing | Meets all quality thresholds |
| `SKIP_LOW_QUALITY` | Skip with marker | Below minimum resolution/duration/size |
| `SKIP_DOWNLOAD_FAILED` | Skip with marker | Media file download or decode failure |
| `SKIP_DECODE_FAILED` | Skip with marker | Media file cannot be decoded |

Per-modality filter functions (`filter_image()`, `filter_video()`, `filter_sticker()`) with configurable thresholds via `configs/media_filter.yaml`.

### Other Shared Modules

| Module | Purpose |
|--------|---------|
| `schema_utils.py` | Unified `merged_v2` schema builder, field ordering, legacy record migration |
| `jsonl_utils.py` | JSONL I/O: `load_jsonl_by_key()` (dict mode), `load_jsonl_list()`, `write_jsonl()`, `update_jsonl_in_place()` (atomic with backup) |
| `path_utils.py` | Centralized path management: loads `configs/paths.yaml`, provides `get_path()`, per-modality directory getters |
| `check_paths.py` | Workspace path validation |
| `download_models.py` | One-click model downloader for all required models |

---

## Agent SFT Data Pipeline

After multi-modal processing, the Agent SFT pipeline transforms the enriched timeline into training-ready data:

```
enriched_full.jsonl
       │
       ▼
  Timeline Postprocessing (message merging, time gap markers)
       │
       ├──── L1 Branch (local training) ────┐
       │     Field trimming → SFT optimizer  │──▶ agent_sft_l1.jsonl
       │                                     │
       ├──── L2 Branch (cloud training) ────┐│
       │     Two-stage PII anonymization     ││
       │     → Field trimming                ││──▶ agent_sft_l2.jsonl
       │     → SFT optimizer                 │
       │                                     │
       └──── Quality Validation ─────────────┘
```

**L1 (Local):** Reversible anonymization, real names preserved in local vault. For on-device training.

**L2 (Cloud):** Irreversible anonymization with two-stage PII detection (regex + LLM validation), timestamp shifting, location replacement. Safe for cloud training.

Run with:
```bash
./run_agent_sft_pipeline.sh              # Both L1 and L2
./run_agent_sft_pipeline.sh --only l1    # L1 only
./run_agent_sft_pipeline.sh --only l2    # L2 only
```

---

## Relationship Advisor System

A full-stack AI relationship advisor built on the processed chat data:

### Offline Pipeline (16 scripts across 10+ phases)

| Phase | Script | Description | Models / Tools |
|-------|--------|-------------|----------------|
| 0 | `_00_verify_environment.py` | Verify Python deps (torch, transformers, peft, bitsandbytes, trl, datasets, accelerate), CUDA/GPU, base model files, test 4-bit quantized loading + inference | Qwen3-8B-Instruct (NF4) |
| 1 | `_01_extract_conversations.py` | Sliding window extraction from SFT data (L1/L2). Window size 20, step 10, min 10 messages. Auto-classifies chunks: conflict / sweet / normal | — |
| 2a | `_02_generate_analysis.py` | Single-backend LLM analysis. 9 backends (OpenAI, Claude, Gemini, Kimi, Grok, DeepSeek, Qwen local/cloud, GLM). Checkpoint resume support | Any of 9 LLM backends |
| 2b | `_02b_model_comparison.py` | Side-by-side multi-backend comparison on representative chunks. Generates Markdown comparison reports | Multiple backends |
| 2c | `_02c_fusion_pipeline.py` | **MoA (Mixture of Agents) fusion pipeline** — the core analysis engine (see details below) | Claude + GPT + Gemini + Grok |
| 2c' | `_02c_rerun_moa.py` | Re-run MoA fusion for specific failed/low-quality chunks | Same as 2c |
| 3a | `_03_export_for_review.py` | Export analyses for human review | — |
| 3b | `_03b_ai_review.py` | AI-assisted quality review with per-dimension scoring. Auto-remediation for weak dimensions | Grok / Kimi |
| 4 | `_04_import_reviewed.py` | Import human-reviewed and approved analyses | — |
| 5a | `_05_format_training_data.py` | Convert to SFT format (JSONL or Alpaca). Data source priority: MoA > reviewed > raw. Auto-strips redundant fields (claude_raw, gpt_raw) | — |
| 5b | `_05b_filter_split_training.py` | Quality filter (min 13 `【】` fields) + OTHERHER bug fix + stratified train/val/test split (80/10/10) by relationship status | — |
| 5c | `_05c_deanonymize_training.py` | Reverse anonymization for local training: ME/OTHER → real names, Day N → real dates, time range extraction | — |
| 6 | `_06_train_model.py` | QLoRA fine-tuning (4-bit NF4, LoRA r=16 α=32). Supports HuggingFace standard and Unsloth (2x speedup) backends. Checkpoint resume, val_loss monitoring | Qwen3-8B-Instruct |
| 7a | `_07_run_inference.py` | Interactive / single / batch inference. Auto-detects best LoRA (Unsloth deanon > HF deanon > legacy) | Qwen3-8B + LoRA |
| 7b | `_07b_eval_compare.py` | Evaluation: ROUGE-L F1, field completeness, base vs fine-tuned comparison | — |
| 8 | `_08_run_dialogue.py` | Real-time terminal dialogue with listen/consult modes, streaming output, GraphRAG context retrieval | Ollama (local) / DeepSeek (cloud) |
| 9 | `_09_build_graph.py` | Build FAISS vector index with BGE-M3 embeddings + BGE-Reranker-V2-M3. Full/incremental modes. Generates user profile (recurring topics, conflict patterns, relationship trends) | BGE-M3, BGE-Reranker-V2-M3 |
| 10 | `_10_augment_data.py` | Multi-teacher distillation from external datasets (PsyCLIENT-CP, CPsDD, AuraDial). Logic teacher (DeepSeek Reasoner) + Style teacher (Claude Opus) dual architecture. Quality filtering | DeepSeek Reasoner, Claude Opus |

### MoA Fusion Pipeline (Phase 2c) — Deep Dive

The MoA (Mixture of Agents) fusion pipeline is the core analysis engine. It orchestrates multiple frontier LLMs in a 4-stage process:

```
                    ┌─────────────────────────────────────────────┐
                    │           MoA Fusion Pipeline                │
                    │                                             │
  Conversation ──▶  │  S1: Parallel Expert Analysis               │
  Chunk             │    ├── Claude Opus → structured analysis    │
                    │    ├── GPT → structured analysis            │
                    │    └── Gemini → structured analysis (if MM) │
                    │                         │                   │
                    │  S2: MoA Aggregation    ▼                   │
                    │    └── Grok fuses all expert outputs        │
                    │         into unified JSON (6+ fields)       │
                    │                         │                   │
                    │  S3: Quality Review     ▼                   │
                    │    └── Grok scores each dimension (1-10)    │
                    │         Pass / Needs Revision / Fail        │
                    │                         │                   │
                    │  S4: Remediation Loop   ▼                   │
                    │    └── Targeted fix for dimensions ≤ 7/10   │
                    │         Up to 3 rounds, re-review each      │
                    │         Fallback: Grok → Gemini → Kimi      │
                    └─────────────────────────────────────────────┘
```

**Key features:**
- **Multi-model fallback chains**: Claude (primary) → Claude backup → Claude degraded (Sonnet); Grok (primary) → Grok backup → Gemini → Kimi
- **Multimodal awareness**: Gemini is only invoked for chunks containing multi-modal content (images, voice, video descriptions)
- **Thinking model truncation detection**: Detects `<think>` tag truncation and auto-switches to non-thinking fallback
- **Cloudflare HTML error detection**: Auto-retries with 30s backoff on proxy HTML responses
- **Key pool rotation**: Multi-key round-robin with per-key blacklisting, emergency mode, and global RPM limiting (≤19)
- **Pipeline mode**: Async 4-stage pipeline with configurable S1 concurrency and Grok concurrency (`--pipeline --max-s1 2 --max-grok 3`)
- **Checkpoint resume**: Scans output file for completed chunk_ids, skips already-processed chunks

```bash
# Standard MoA fusion (serial)
python scripts/advisor/run_all/_02c_fusion_pipeline.py --moa --agent-type neutral

# Pipeline mode with concurrency
python scripts/advisor/run_all/_02c_fusion_pipeline.py --pipeline --max-s1 2 --max-grok 3

# Multi-worker with key pool
python scripts/advisor/run_all/_02c_fusion_pipeline.py --moa --workers 3 --key-pool local_secrets/key_pool.yaml

# Switch MoA aggregator to Kimi (when Grok is unstable)
python scripts/advisor/run_all/_02c_fusion_pipeline.py --moa --grok-backend kimi
```

### Three Agent Personas × Two Modes

| Agent | Approach | Theoretical Framework |
|-------|----------|----------------------|
| Neutral | Objective multi-dimensional analysis | Communication patterns, attachment styles, NVC, power dynamics |
| Supportive | Unconditionally on the user's side | Emotional validation, protective advice, boundary setting |
| Psychoanalytic | Unconscious-level deep analysis | Object relations, Lacanian registers, defense mechanisms, transference |

| Mode | Response Style |
|------|---------------|
| Listen | 5-7 sentences, empathy-first, open-ended questions |
| Consult | Full structured analysis (500-2500 words), multi-dimensional |

### Online Service

- **Backend:** FastAPI (port 8787) with SSE streaming, multi-turn session management, conversation history compression
- **Frontend:** React 19 + Vite + Tailwind CSS dashboard with chat, pipeline control, human review, model management, and API key checker
- **RAG:** Triple-layer retrieval — date-precise day index lookup + FAISS semantic search (BGE-M3) + keyword fallback + FAQ knowledge base
- **LLM Backends:** 9 backends via unified OpenAI-compatible interface (GPT, Claude, Gemini, Grok, DeepSeek, Qwen, GLM, Kimi, local Ollama)
- **Safety:** SafetyLayer P0, GlobalRateLimiter (RPM≤19), auto-failover between backends, Ollama watchdog auto-restart
- **Session Management:** Persistent sessions with agent type, mode switching, memory fact extraction, history truncation

---

## Universal Ingestion

Plugin-based adapter architecture for importing chat data from multiple platforms:

| Adapter | Source | Format |
|---------|--------|--------|
| `wechat_html` | WeChat Desktop export | HTML + CSV |
| `telegram_json` | Telegram Desktop export | result.json |
| `whatsapp_txt` | WhatsApp export | *.txt (8 date formats) |
| `generic_csv` | Any CSV | field_mapping DSL |
| `generic_jsonl` | Any JSONL | field_mapping DSL |

All adapters output to a unified Canonical Schema (`P1_messages_raw.jsonl`) that feeds into the downstream modality pipelines.

```bash
# Auto-detect source type and ingest
python scripts/workspace/run_ingest.py --workspace /path/to/workspace

# Specify source type
python scripts/workspace/run_ingest.py --workspace /path/to/workspace --source-type telegram_json

# Dry run (preview without writing)
python scripts/workspace/run_ingest.py --dry-run
```

---

## Privacy & Anonymization

### Two-Tier System

| Level | Use Case | Reversible | PII Handling |
|-------|----------|------------|--------------|
| **L1** | Local training | Yes (vault) | Names → ME/OTHER, timestamps preserved |
| **L2** | Cloud training | No | Full PII scrub, timestamp shift, location replacement |

### Two-Stage PII Detection

1. **Phase 1 (Offline Scan):** Rule-based candidate extraction → LLM validation (Qwen2.5-7B-AWQ) → Human review → Confirmed names list
2. **Phase 2 (Runtime):** Exact string matching against confirmed list — zero false negatives, high performance

### Configuration

```yaml
# configs/anonymization.yaml
me_names:
  - "YourRealName"
  - "YourNickname"
other_names:
  - "PartnerRealName"
  - "PartnerNickname"
me_alias: "ME"
other_alias: "OTHER"

# Location mapping (L2 only)
location_mapping:
  "Beijing": "Tianjin"
  "Shanghai": "Hangzhou"

# Exclusion list (public figures, etc.)
exclude_patterns:
  - "Einstein"
  - "Shakespeare"
```

---

## Quick Start

### Prerequisites

- Python 3.10+
- NVIDIA GPU with 16GB+ VRAM (RTX 4070 Ti / 5070 Ti or above recommended)
- CUDA 12.x
- Conda

### Installation

```bash
git clone https://github.com/your-repo/wechatDHA.git
cd wechatDHA

# Create conda environment
conda create -n wechatDHA python=3.10
conda activate wechatDHA

# Install dependencies
pip install -r requirements.txt

# Download required models (PaddleOCR, FunASR, Qwen2.5-VL, etc.)
python scripts/_common/download_models.py
```

### Workspace Setup

```bash
# Initialize a new workspace
python scripts/workspace/init_workspace.py \
    --template demo \
    --contact-name "PartnerName"
```

Place your exported WeChat data into the workspace `raw/` directory.

### Configuration

1. Edit `configs/anonymization.yaml` with your identity mapping
2. Edit `configs/paths.yaml` to set your workspace name
3. (Optional) Edit modality-specific configs in `configs/`

### Run the Pipeline

```bash
# Run all modality pipelines (image → voice → video → sticker → linkfile)
python run_all_pipelines.py

# Run specific modalities
python run_all_pipelines.py --only voice video

# Skip compression steps (faster)
python run_all_pipelines.py --skip-compression

# Dry run (preview plan without executing)
python run_all_pipelines.py --dry-run

# Continue on error
python run_all_pipelines.py --continue-on-error
```

### Generate SFT Training Data

```bash
./run_agent_sft_pipeline.sh
```

### Start the Advisor Service

```bash
# Load API keys
source local_secrets/.env.advisor

# Start backend
conda run -n wechatDHA uvicorn scripts.advisor.api.server:app --reload --port 8787

# Start frontend (in another terminal)
cd frontend && npm run dev
```

---

## Project Structure

```
wechatDHA/
├── run_all_pipelines.py              # One-click pipeline runner
├── run_agent_sft_pipeline.sh         # Agent SFT data generation
├── requirements.txt                  # Python dependencies
├── environment.yml                   # Conda environment
│
├── configs/                          # All configuration files
│   ├── paths.yaml                    # Workspace paths
│   ├── anonymization.yaml            # Identity mapping & PII rules
│   ├── compression.yaml              # Semantic compression settings
│   ├── router.yaml                   # Image routing thresholds
│   ├── caption.yaml                  # VLM captioning config
│   ├── voice.yaml                    # ASR & emotion config
│   ├── video.yaml                    # Video extraction config
│   ├── sticker.yaml                  # Sticker processing config
│   ├── linkfile.yaml                 # Link/file handler rules
│   ├── advisor.yaml                  # Advisor system config
│   ├── sft_optimizer.yaml            # SFT optimization rules
│   └── timeline_postprocess.yaml     # Message merging & time gaps
│
├── scripts/
│   ├── _common/                      # Shared utilities
│   │   ├── anonymizer.py             # Text anonymization
│   │   ├── schema_utils.py           # Unified schema (merged_v2)
│   │   ├── jsonl_utils.py            # JSONL I/O utilities
│   │   ├── path_utils.py             # Path management
│   │   ├── media_filter.py           # Media quality filtering (4 tiers)
│   │   └── text_normalize.py         # Text normalization (CJK)
│   │
│   ├── image/                        # Image pipeline
│   │   ├── router.py                 # ImageRouter (smart classification)
│   │   ├── loader.py                 # Image loader
│   │   ├── experts/                  # Expert model system
│   │   │   ├── expert_router.py      # Triage → Expert dispatch
│   │   │   ├── image_triage.py       # NSFW/Gore classifier
│   │   │   ├── nsfw_expert.py        # Dual-model NSFW ensemble
│   │   │   ├── gore_expert.py        # Violence content expert
│   │   │   ├── caption_expert.py     # General captioning
│   │   │   └── doc_expert.py         # Document/screenshot expert
│   │   └── run_all/                  # Pipeline scripts
│   │
│   ├── voice/run_all/                # Voice pipeline scripts
│   ├── video/run_all/                # Video pipeline scripts
│   ├── sticker/run_all/              # Sticker pipeline scripts
│   ├── linkfile/                     # Linkfile pipeline
│   │   ├── handlers/                 # Strategy pattern handlers
│   │   └── run_all/                  # Pipeline scripts
│   │
│   ├── compression/                  # Compression & PII
│   │   ├── engine.py                 # Semantic compression engine
│   │   ├── pii_detector.py           # Rule-based PII detection
│   │   ├── privacy_shield.py         # Privacy shield integration
│   │   ├── two_stage_pii/            # Two-stage PII system
│   │   │   ├── candidate_extractor.py
│   │   │   ├── llm_validator.py
│   │   │   ├── scanner.py
│   │   │   └── name_replacer.py
│   │   ├── sft_trimmer.py            # Field trimming (L1/L2)
│   │   └── sft_optimizer.py          # SFT format optimization
│   │
│   ├── timeline/                     # Timeline postprocessing
│   │   ├── postprocess_timeline.py   # Message merging & time gaps
│   │   └── run_anonymization.py      # L2 anonymization runner
│   │
│   ├── extract/                      # Raw data extraction
│   │   └── extract_html_to_jsonl.py  # WeChat HTML → JSONL
│   │
│   ├── workspace/                    # Workspace management
│   │   ├── init_workspace.py         # Workspace initialization
│   │   ├── run_ingest.py             # Universal ingestion CLI
│   │   └── ingestion/                # Ingestion engine & adapters
│   │
│   └── advisor/                      # Relationship Advisor system
│       ├── run_all/                  # 16-script offline pipeline
│       │   ├── _00_verify_environment.py
│       │   ├── _01_extract_conversations.py
│       │   ├── _02_generate_analysis.py
│       │   ├── _02b_model_comparison.py
│       │   ├── _02c_fusion_pipeline.py  # MoA core engine
│       │   ├── _02c_rerun_moa.py
│       │   ├── _03_export_for_review.py
│       │   ├── _03b_ai_review.py
│       │   ├── _04_import_reviewed.py
│       │   ├── _05_format_training_data.py
│       │   ├── _05b_filter_split_training.py
│       │   ├── _05c_deanonymize_training.py
│       │   ├── _06_train_model.py
│       │   ├── _07_run_inference.py
│       │   ├── _07b_eval_compare.py
│       │   ├── _08_run_dialogue.py
│       │   ├── _09_build_graph.py
│       │   └── _10_augment_data.py
│       ├── api/server.py             # FastAPI backend (60+ endpoints)
│       ├── generator.py              # MoA analysis generator
│       ├── extractor.py              # Conversation extractor
│       ├── formatter.py              # Training data formatter
│       ├── augmentor.py              # Multi-teacher data augmentor
│       ├── chunk_based_rag.py        # Hybrid RAG engine
│       ├── graph_rag.py              # Graph RAG (FAISS + BGE-M3)
│       ├── graph_rag_enhanced.py     # Enhanced Graph RAG
│       ├── trainer.py                # QLoRA training (HF + Unsloth)
│       ├── inference.py              # Model inference
│       ├── streaming.py              # SSE streaming dialogue engine
│       ├── pipeline_executor.py      # Async pipeline executor
│       ├── intent_classifier.py      # User intent classification
│       ├── query_rewriter.py         # Query rewriting for RAG
│       ├── model_router.py           # LLM backend routing
│       ├── safety_layer.py           # Safety & privacy layer
│       ├── key_rotator.py            # API key rotation & pool
│       ├── schema_validator.py       # Analysis schema validation
│       ├── schemas.py                # Pydantic data models
│       ├── config.py                 # Advisor configuration
│       └── errors.py                 # Error definitions
│
├── frontend/                         # React + Vite web dashboard
│   └── src/
│       └── components/               # Dashboard, Chat, Review, Settings
│
├── docs/                             # Detailed documentation
│   ├── QUICKSTART.md
│   ├── BETA_USER_GUIDE.md
│   ├── CONTRIBUTING.md
│   ├── SECURITY.md
│   ├── advisor/                      # Lens Advisor documentation
│   └── pipelines/                    # Pipeline and privacy references
│
├── tests/                            # Test suite
│   ├── test_*_properties.py          # Property-based tests (Hypothesis)
│   └── test_*.py                     # Unit tests
│
├── artifacts/                        # Intermediate processing results
│   ├── before_merge/                 # Per-engine outputs
│   └── after_merge/                  # Merged results (merged_v2 schema)
│
├── timeline_out/                     # Final outputs
│   ├── enriched_full.jsonl           # Full timeline (all fields)
│   ├── enriched_slim.jsonl           # Slim timeline (LLM-ready)
│   ├── agent_sft_l1.jsonl            # L1 SFT training data
│   └── agent_sft_l2.jsonl            # L2 SFT training data (anonymized)
│
└── local_secrets/                    # API keys & identity vault (gitignored)
```

---

## Unified Schema

All modality pipelines output to a unified `merged_v2` schema with common header fields:

| Field | Type | Description |
|-------|------|-------------|
| `schema_version` | string | Always `"merged_v2"` |
| `seq_in_html` | int | Original sequence number |
| `msg_uid` | string | Unique ID (`P1:MsgSvrID`) |
| `ts` | int | Unix timestamp (seconds) |
| `time_local` | string | Local time `YYYY-MM-DD HH:MM:SS` |
| `speaker` | string | `ME` or `OTHER` |
| `type` | int | WeChat message type code |
| `modality` | string | `image` / `voice` / `video` / `sticker` / `link_or_file` |
| `media_path` | string | Relative path to media file |

Modality-specific fields follow the common header. See `scripts/_common/schema_utils.py` for full definitions.

---

## Hardware Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| GPU | 8GB VRAM | 16GB VRAM (RTX 4070 Ti / 5070 Ti) |
| RAM | 16GB | 32GB |
| Storage | 50GB | 200GB+ (depends on media volume) |
| CUDA | 12.0 | 12.8+ |

**VRAM Management:** All models are loaded serially (one at a time) with explicit cleanup between switches. The pipeline is designed to run within 16GB VRAM constraints.

---

## Models Used

| Model | Purpose | VRAM | Quantization |
|-------|---------|------|-------------|
| PaddleOCR PP-OCRv4 | Chinese OCR | ~2GB | — |
| Qwen2.5-VL-7B-Instruct | Main VLM captioning | ~8GB | bfloat16 |
| MiniCPM-V 4.5 Abliterated | NSFW content analysis | ~10GB | int8 |
| Pixtral 12B | Document analysis | ~8.3GB | GGUF Q5_K_M |
| FunASR (paraformer-zh) | Chinese ASR | ~2GB | — |
| SenseVoice Small | Voice emotion detection | ~1GB | — |
| Qwen2-Audio-7B | Deep voice emotion analysis | ~8GB | float16 |
| LLaVA-NeXT-Video-7B | Video understanding fallback | ~8GB | — |
| Qwen2.5-7B-Instruct-AWQ | Semantic compression & PII | ~4GB | AWQ 4-bit |
| BGE-M3 | Semantic embedding (RAG) | ~2GB | — |

---

## Testing

The project uses [Hypothesis](https://hypothesis.readthedocs.io/) for property-based testing alongside standard unit tests:

```bash
# Run all tests
conda run -n wechatDHA python -m pytest tests/ -v

# Run specific test file
conda run -n wechatDHA python -m pytest tests/test_advisor_analyzers_properties.py -v
```

---

## Documentation

Detailed documentation for each subsystem is available in the `docs/` directory:

- [Full Pipeline Reference](docs/pipelines/pipeline.md)
- [Image Pipeline Design](docs/pipelines/image_pipeline_overview.md)
- [Voice Pipeline Design](docs/pipelines/voice_pipeline_overview.md)
- [Video Pipeline Design](docs/pipelines/video_pipeline_overview.md)
- [Sticker Pipeline Design](docs/pipelines/sticker_pipeline_overview.md)
- [Linkfile Pipeline Design](docs/pipelines/linkfile_pipeline_overview.md)
- [Universal Ingestion](docs/pipelines/ingestion_pipeline_overview.md)
- [Agent SFT Pipeline](docs/pipelines/agent_sft_pipeline_overview.md)
- [Advisor System](docs/advisor/advisor_pipeline_overview.md)
- [Privacy & PII Guide](docs/pipelines/pii_detection_guide.md)
- [Privacy Mapping](docs/pipelines/privacy_mapping.md)

---

## Privacy Notice

This project strictly separates code from data:

- **Code** (`scripts/`, `configs/`, `frontend/`): Safe to share publicly
- **Data** (`raw/`, `artifacts/`, `timeline_out/`): Contains personal chat history — **NEVER commit**
- **Secrets** (`local_secrets/`): Contains API keys and identity vaults — **NEVER commit**

The `.gitignore` is configured to exclude all data and secret directories.

---

## License

[MIT License](LICENSE)

---

## Acknowledgments

This project builds on the following open-source models and tools:

- [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) — OCR engine
- [FunASR](https://github.com/modelscope/FunASR) — Chinese ASR
- [SenseVoice](https://github.com/FunAudioLLM/SenseVoice) — Voice emotion detection
- [Qwen2.5-VL](https://github.com/QwenLM/Qwen2.5-VL) — Vision-Language model
- [Qwen2-Audio](https://github.com/QwenLM/Qwen2-Audio) — Audio understanding
- [LLaVA-NeXT](https://github.com/LLaVA-VL/LLaVA-NeXT) — Video understanding
- [Pixtral](https://mistral.ai/) — Document analysis
- [BGE-M3](https://github.com/FlagOpen/FlagEmbedding) — Multilingual embeddings
- [Hypothesis](https://hypothesis.readthedocs.io/) — Property-based testing
