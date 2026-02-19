# 项目流水线全流程文档

本文档详细介绍了CHAT_APP聊天记录导出与处理项目（CHAT_APP Data Handling & Analysis）的数据处理流水线。
整个流程旨在将原始聊天记录（文本、图片、语音）转化为结构化、可检索、内容丰富的"数字记忆"时间轴。

---

## 📂 1. 数据准备 (Data Preparation)

一切始于原始数据。需将导出的CHAT_APP数据放置在 `raw/` 目录下：

*   **消息记录**: `raw/P1_messages_raw.jsonl` (包含所有聊天消息的 JSON Lines 文件)
*   **图片文件**: `raw/image/YYYY-MM/` (原始图片文件)
*   **语音文件**: `raw/voice/` (原始语音/视频音频文件，.mp3 格式)

---

## 🖼️ 2. 图片处理流水线 (Image Pipeline)

位于 `scripts/image/run_all/`，按顺序执行以下步骤：

### 第 1 步：OCR 文字识别 (`_01_run_ocr.py`)
*   **功能**: 扫描所有图片，提取其中的文字信息。
*   **智能路由**: 使用 `Router` 判断图片类型（如文本密集型、风景照、表情包）。
*   **处理逻辑**:
    *   **Text-Primary (文本为主)**: 重点进行高精度 OCR 识别。
    *   **Non-Text (非文本)**: 只进行轻量级检测，甚至跳过 OCR。
*   **产出**: `artifacts/before_merge/image/image_ocr_v1.jsonl`

### 第 2 步：智能描述生成 (`_02_run_caption.py`)
*   **功能**: 使用多模态大模型 (Qwen2.5-VL) "看懂" 图片内容并生成文字描述。
*   **安全机制**: 包含 NSFW 检测。发现敏感内容时，自动切换到专用模型处理。
*   **产出**: `artifacts/before_merge/image/image_caption_v1.jsonl`

### 第 3 步：数据合并 (`_03_merge_engine.py`)
*   **功能**: 将 OCR 结果（文字）和 Caption 结果（描述）与原始图片元数据合并。
*   **产出**: `artifacts/after_merge/image/image_merged_final.jsonl`

### 第 2.5 步：语义压缩 (`_02.5_run_compress.py`) [可选]
*   **功能**: 对图片描述进行语义压缩，减少冗余信息。
*   **压缩策略**: 移除重复描述、合并相似内容、保留关键信息。
*   **产出**: 更新 `image_caption_v1.jsonl` 中的 `caption` 字段

### 第 4 步：更新时间轴 (`_04_update_timeline.py`)
*   **功能**: 将处理好的图片信息回填到主时间轴文件中。
*   **产出**: 更新 `timeline_out/enriched_full.jsonl` 和 `enriched_slim.jsonl`

---

## 🎙️ 3. 语音处理流水线 (Voice Pipeline)

位于 `scripts/voice/run_all/`，按顺序执行：

### 第 1 步：ASR 转写

#### `_01_run_funasr.py`
*   **功能**: 运行阿里 FunASR 引擎，擅长中文识别。
*   **产出**: `artifacts/before_merge/voice/voice_funasr_v2.jsonl`

#### `_01b_run_whisper.py` (可选)
*   **功能**: 运行 OpenAI Whisper 引擎，多语言补充。
*   **产出**: `artifacts/before_merge/voice/voice_whisper_v2.jsonl`

### 第 2 步：情绪分析 (`_02_run_emotion.py`)

这是一个统一的情绪分析模块，包含四个阶段：

#### 阶段 1：SenseVoice 情绪检测
*   **功能**: 使用阿里 SenseVoice 模型检测语音情绪（SAD/HAPPY/ANGRY/NEUTRAL）和事件（哭泣/笑声）。
*   **模型**: `iic/SenseVoiceSmall` (自动从 ModelScope 下载)
*   **VRAM 优化**: 使用单例模式加载，处理完成后释放显存。

#### 阶段 2：Triage 关键词触发
*   **功能**: 基于关键词规则对语音进行筛选，识别需要深度分析的样本。
*   **触发类别**:
    - `A_Crisis`: 危机/压力词（累了、烦死了、无所谓...）
    - `B_Intimacy`: 亲密关系词（想你了、去找你...）
    - `C_Workplace`: 职场用语（收到、辛苦了...）
    - `D_Boundaries`: 边界/施压词（为你好、借我...）
    - `E_Sadness`: 伤心/无奈词（遗憾、后悔、没办法...）
    - `F_Confusion`: 疑惑/困惑词（是吧、为什么、不懂...）
    - `G_Helpless`: 无奈类词（没法、也没事、着急...）

#### 阶段 3：Qwen2-Audio 深度分析
*   **功能**: 对触发的样本进行心理声学分析，识别复杂情绪。
*   **模型**: Qwen2-Audio-7B (`/data/models`)
*   **情绪分类法**: 支持 6 大类 20+ 种情绪（毒性类、亲密类、痛苦类、掩饰类、基础类、认知类）
*   **输出**: JSON 格式的情绪标签、置信度、声学证据

#### 阶段 4：输出生成
*   **产出**:
    - `artifacts/before_merge/voice/voice_merged_v3.jsonl` (情绪分析结果)
    - `artifacts/before_merge/voice/voice_v3_labeling.md` (人工标注文件)

### 3.3 数据合并 (`_03_merge_engine.py`)
*   **功能**: 合并 FunASR + Whisper + v3 情绪分析 三路数据。
*   **策略**: FunASR 优先，Whisper 作为后备。
*   **产出**: 
    - `artifacts/after_merge/voice/voice_merged_final.jsonl`
    - `artifacts/before_merge/voice/voice_merged_qc_report.md` (QC报告)
*   **Schema 版本**: `merged_v3`

### 3.2.5 语义压缩 (`_02.5_run_compress.py`) [可选]
*   **功能**: 对语音转写文本进行语义压缩。
*   **压缩策略**: 移除口语化填充词、合并重复内容。
*   **产出**: 更新 `voice_merged_v3.jsonl` 中的转写文本

### 3.4 更新时间轴 (`_04_update_timeline.py`)
*   **功能**: 将转写文本和情绪分析结果回填到主时间轴。
*   **新增字段**:
    - `voice_to_text`: ASR 转写文本
    - `emotion_tags`: 情绪标签数组 (如 `["SAD"]`)
    - `event_tags`: 事件标签数组 (如 `["Cry"]`)
    - `trigger_reasons`: 触发原因 (如 `["F_Confusion:是吧"]`)
    - `voice_analysis`: Qwen 深度分析结果
*   **产出**: 
    - `artifacts/before_merge/voice/voice_alignment_audit.json` (QC/审计)
    - 更新 `timeline_out/enriched_full.jsonl` 和 `enriched_slim.jsonl`

---

## 🎨 4. 表情包处理流水线 (Sticker Pipeline)

位于 `scripts/sticker/run_all/`，按顺序执行以下步骤：

### 第 1 步：表情包下载 (`_01_run_download.py`)
*   **功能**: 从 `P1_messages_raw.jsonl` 提取表情包 URL 并下载。
*   **去重策略**: 使用 SHA256 哈希识别重复文件，避免重复下载。
*   **网络配置**: 支持超时重试（3次指数退避）、并发下载（默认5个）。
*   **产出**: `artifacts/before_merge/sticker/sticker_download_v1.jsonl`

### 第 2 步：格式嗅探与验证 (`_02_run_sniff.py`)
*   **功能**: 使用 Magic Bytes 识别真实格式，不信任 Content-Type。
*   **格式识别**:
    - GIF: `GIF87a` / `GIF89a`
    - WebP: `RIFF....WEBP`
    - PNG: `\x89PNG\r\n\x1a\n`
    - JPEG: `\xff\xd8`
*   **验证**: 使用 Pillow 解码验证文件完整性。
*   **产出**: `sticker_sniff_v1.jsonl`, `sticker_decode_qc_v1.jsonl`

### 第 3 步：分类与关键帧提取 (`_03_run_process.py`)
*   **功能**: 区分动图/静图，生成缩略图和关键帧。
*   **自适应采样** (根据帧数动态调整):
    - ≤12帧：采样 4 帧
    - 13-30帧：采样 8 帧
    - 31-60帧：采样 12 帧
    - >60帧：采样 16 帧
*   **Contact Sheet**: 将采样帧拼接成单张图片，供 VLM 单次理解完整动画。
*   **产出**: `sticker_meta_v1.jsonl`, `sticker_frames_v1.jsonl`

### 第 4 步：敏感内容检测 (`_04_run_triage.py`)
*   **功能**: 复用图片流水线的 NSFW Classifier 进行内容检测。
*   **检测策略**:
    - 动图：逐帧检测，取最高分
    - 静图：单帧检测
*   **分类结果**: TYPE_A_NSFW / TYPE_B_GORE / TYPE_C_NORMAL
*   **产出**: `sticker_triage_v1.jsonl`

### 第 5 步：语义描述生成 (`_05_run_caption.py`)
*   **功能**: 使用 Qwen2.5-VL-7B (bfloat16 + 4-bit动态量化) 生成描述。
*   **Expert Router 集成**: 
    - TYPE_A_NSFW → NSFW Expert (MiniCPM-V 4.5 Abliterated)
    - TYPE_B_GORE → Gore Expert (Qwen2.5-VL Abliterated)
    - TYPE_C_NORMAL → Qwen2.5-VL (主模型)
*   **OCR**: 使用 PaddleOCR 提取嵌入文字（可选）。
*   **输出格式**: `[表情包: 角色动作 + 文字内容 + 情绪]`
*   **产出**: `sticker_caption_v1.jsonl`

### 第 5.5 步：语义压缩 (`_05.5_run_compress.py`) [可选]
*   **功能**: 对表情包描述进行语义压缩。
*   **压缩策略**: 移除冗余描述、保留核心动作和情绪信息。
*   **产出**: 更新 `sticker_caption_v1.jsonl` 中的 `caption` 字段

### 第 6 步：数据合并 (`_06_merge_engine.py`)
*   **功能**: 合并下载、嗅探、分类、描述等所有结果。
*   **SHA256 复用**: 重复表情自动复用已有描述。
*   **产出**: `artifacts/after_merge/sticker/sticker_merged_final.jsonl`

### 第 7 步：更新时间轴 (`_07_update_timeline.py`)
*   **功能**: 将表情包数据回填到主时间轴。
*   **产出**: 更新 `timeline_out/enriched_full.jsonl` 和 `enriched_slim.jsonl`

### 表情包运行命令

```bash
# ========== 表情包流水线 ==========
python scripts/sticker/run_all/_01_run_download.py
python scripts/sticker/run_all/_02_run_sniff.py
python scripts/sticker/run_all/_03_run_process.py
python scripts/sticker/run_all/_04_run_triage.py
python scripts/sticker/run_all/_05_run_caption.py
python scripts/sticker/run_all/_06_merge_engine.py
python scripts/sticker/run_all/_07_update_timeline.py

# 测试模式
python scripts/sticker/run_all/_01_run_download.py --sample 10
python scripts/sticker/run_all/_05_run_caption.py --skip-ocr  # 跳过OCR
```

---

## 🎬 5. 视频处理流水线 (Video Pipeline)

位于 `scripts/video/run_all/`，按顺序执行以下步骤：

### 第 1 步：视频提取 (`_01_run_extract.py`)
*   **功能**: 提取视频元数据、分离音频、智能关键帧提取。
*   **自适应帧数策略** (2026-01-21 更新):
    - **运动检测**: 使用光流算法检测局部运动 (threshold=0.08)
    - **运动强度计算**: `intensity = avg × 0.3 + p90 × 0.4 + high_ratio × 0.3`
    - **内容类型判定**:
      - `high_motion` (≥0.25): 宠物活动等，最少8帧，最多16帧
      - `medium_motion` (0.12-0.25): 按时长计算
      - `low_motion` (<0.12): 按时长计算，上限12帧
*   **产出**: `artifacts/before_merge/video/video_extract_v1.jsonl`
*   **新增字段**: `motion_intensity`, `content_type`, `motion_frames_detected`

### 第 2 步：音频转写 (`_02_run_transcribe.py`)
*   **功能**: 使用 FunASR 转写视频音频，SenseVoice 检测情绪。
*   **产出**: `artifacts/before_merge/video/video_transcribe_v1.jsonl`

### 第 3 步：视频描述 (`_03_run_caption.py`)
*   **功能**: 使用 Qwen2.5-VL-7B 生成视频理解描述。
*   **Triage 分类**: NSFW/Gore/Normal 自动路由
*   **处理方式**: 支持视频直接输入和多帧图片模式
*   **LLaVA-NeXT-Video Fallback** (2026-01-21 新增):
    - 触发条件: 输出过短 (<50字) / 模型拒绝 / 输出为空
    - 先卸载主模型释放显存，再加载 LLaVA-NeXT-Video-7B
    - 使用 PyAV 读取 32 帧进行视频理解
*   **产出**: `artifacts/before_merge/video/video_caption_v1.jsonl`

### 第 3.5 步：语义压缩 (`_03.5_run_compress.py`) [可选]
*   **功能**: 对视频描述和转写文本进行语义压缩。
*   **压缩策略**: 移除冗余描述、合并重复内容、保留关键信息。
*   **产出**: 更新 `video_caption_v1.jsonl` 中的描述字段

### 第 4 步：数据合并 (`_04_merge_engine.py`)
*   **功能**: 合并提取、转写、描述三路数据。
*   **产出**: 
    - `artifacts/after_merge/video/video_merged_final.jsonl`
    - `artifacts/before_merge/video/video_merged_qc_report.md` (QC报告)

### 第 5 步：更新时间轴 (`_05_update_timeline.py`)
*   **功能**: 将视频数据回填到主时间轴。
*   **产出**: 更新 `timeline_out/enriched_full.jsonl` 和 `enriched_slim.jsonl`

### 性能参考 (RTX 5070 Ti 16GB)

| 步骤 | 单视频耗时 | 显存占用 |
|------|----------|---------|
| Step1 视频提取 | ~5s | <1GB |
| Step2 音频转写 | ~30s | ~3GB |
| Step3 视频描述 | ~6-7min | ~13GB |
| Step4 数据合并 | <1s | - |

### 视频运行命令

```bash
# ========== 视频流水线 ==========
python3 scripts/video/run_all/_01_run_extract.py --test-dir  # 测试模式
python3 scripts/video/run_all/_02_run_transcribe.py
python3 scripts/video/run_all/_03_run_caption.py --test-dir
python3 scripts/video/run_all/_04_merge_engine.py
python3 scripts/video/run_all/_05_update_timeline.py
```

---

## 📊 6. 最终产物 (Final Outputs)

经过两大数据流水线的洗礼，最终在 `timeline_out/` 目录下生成：

### `enriched_full.jsonl`
*   **全量版数据**。包含所有原始字段、OCR坐标、详细Caption、ASR置信度、情绪分析等。
*   适合：程序调用、深度分析、全备份。
*   **语音字段示例**:
```json
{
  "voice_to_text": "你也开始解决人不解决问题了是吧？",
  "emotion_tags": ["NEUTRAL"],
  "trigger_reasons": ["F_Confusion:是吧"],
  "voice_analysis": {"primary_tag": "Confused", "confidence": 7}
}
```

### `enriched_slim.jsonl`
*   **精简版数据**。去除冗余技术细节，只保留核心信息。
*   适合：快速浏览、搜索、**LLM 训练数据**。
*   **语音字段示例**:
```json
{
  "text": "你也开始解决人不解决问题了是吧？",
  "emotion_tags": ["NEUTRAL"],
  "emotion_desc": "语气中带有责备或批评的感觉，听起来像是在指责对方没有解决问题。"
}
```

---

## 🛡️ 7. 辅助与安全 (Utils & Security)

### 脱敏系统 (`configs/anonymization.yaml`)
*   在输出最终结果前，系统会根据配置策略，将真实人名、地名、机构名替换为代号（如 ME, OTHER, COLLEAGUE_A），保护隐私。

### Common 模块 (`scripts/_common/`)
*   `jsonl_utils.py`: JSONL 加载、写入和合并工具
*   `path_utils.py`: 路径管理和配置加载
*   `schema_utils.py`: 统一 Schema 定义和工具函数
*   `anonymizer.py`: 文本脱敏处理
*   `media_filter.py`: 媒体质量过滤
*   `text_normalize.py`: 文本规范化（繁简转换、标点处理）

---

## 🚀 8. 如何运行 (How to Run)

### 一键运行（推荐）

```bash
# 运行所有流水线（image → voice → video → sticker → linkfile）
python run_all_pipelines.py

# 只运行指定模态
python run_all_pipelines.py --only video sticker

# 跳过指定模态
python run_all_pipelines.py --skip image

# 从指定模态开始
python run_all_pipelines.py --start voice

# 跳过压缩步骤（加快处理速度）
python run_all_pipelines.py --skip-compression

# 只运行压缩步骤
python run_all_pipelines.py --compression-only

# 预览模式（不实际执行）
python run_all_pipelines.py --dry-run

# 遇到错误继续执行下一个模态
python run_all_pipelines.py --continue-on-error
```

### 完整流水线（分步运行）

```bash
# ========== 图片流水线 ==========
python3 scripts/image/run_all/_01_run_ocr.py
python3 scripts/image/run_all/_02_run_caption.py
python3 scripts/image/run_all/_02.5_run_compress.py    # 语义压缩（可选）
python3 scripts/image/run_all/_03_merge_engine.py
python3 scripts/image/run_all/_04_update_timeline.py

# ========== 语音流水线 ==========
python3 scripts/voice/run_all/_01_run_funasr.py
python3 scripts/voice/run_all/_01b_run_whisper.py   # 可选
python3 scripts/voice/run_all/_02_run_emotion.py
python3 scripts/voice/run_all/_02.5_run_compress.py    # 语义压缩（可选）
python3 scripts/voice/run_all/_03_merge_engine.py
python3 scripts/voice/run_all/_04_update_timeline.py

# ========== 表情包流水线 ==========
python3 scripts/sticker/run_all/_01_run_download.py
python3 scripts/sticker/run_all/_02_run_sniff.py
python3 scripts/sticker/run_all/_03_run_process.py
python3 scripts/sticker/run_all/_04_run_triage.py
python3 scripts/sticker/run_all/_05_run_caption.py
python3 scripts/sticker/run_all/_05.5_run_compress.py  # 语义压缩（可选）
python3 scripts/sticker/run_all/_06_merge_engine.py
python3 scripts/sticker/run_all/_07_update_timeline.py

# ========== 视频流水线 ==========
python3 scripts/video/run_all/_01_run_extract.py
python3 scripts/video/run_all/_02_run_transcribe.py
python3 scripts/video/run_all/_03_run_caption.py
python3 scripts/video/run_all/_03.5_run_compress.py    # 语义压缩（可选）
python3 scripts/video/run_all/_04_merge_engine.py
python3 scripts/video/run_all/_05_update_timeline.py

# ========== Linkfile 流水线 ==========
python3 scripts/linkfile/run_all/_01_extract_and_anonymize.py
python3 scripts/linkfile/run_all/_01.5_run_file_summary.py  # 文件摘要
python3 scripts/linkfile/run_all/_02_merge_engine.py
python3 scripts/linkfile/run_all/_03_update_timeline.py
```

### 语音情绪分析选项

```bash
# 全量分析
python3 scripts/voice/run_all/_02_run_emotion.py

# 采样测试 (10个)
python3 scripts/voice/run_all/_02_run_emotion.py --sample 10

# 仅 SenseVoice (跳过 Qwen)
python3 scripts/voice/run_all/_02_run_emotion.py --skip-qwen

# 限制 Qwen 分析数量
python3 scripts/voice/run_all/_02_run_emotion.py --qwen-limit 5
```

### 快速测试

```bash
# 测试 5 个样本
python3 scripts/voice/test/test_emotion.py

# 测试单个文件
python3 scripts/voice/test/test_emotion.py --file xxx.mp3 --with-qwen
```

---

## 📁 9. 目录结构

```
demo/
├── raw/                          # 原始数据
│   ├── P1_messages_raw.jsonl
│   ├── image/
│   ├── voice/
│   ├── video/
│   ├── sticker/
│   ├── file/                     # 文件（PDF、ZIP 等）
│   └── export/                   # 导出的 HTML/CSV/MD 文件
├── artifacts/
│   ├── before_merge/             # 单引擎处理结果
│   │   ├── image/
│   │   ├── voice/
│   │   │   ├── voice_funasr_v2.jsonl
│   │   │   ├── voice_whisper_v2.jsonl
│   │   │   ├── voice_merged_v3.jsonl    # 情绪分析结果
│   │   │   ├── voice_v3_labeling.md
│   │   │   ├── voice_alignment_audit.json  # QC/审计
│   │   │   └── voice_merged_qc_report.md   # QC报告
│   │   ├── video/
│   │   │   ├── video_extract_v1.jsonl
│   │   │   ├── video_transcribe_v1.jsonl
│   │   │   ├── video_caption_v1.jsonl
│   │   │   └── video_merged_qc_report.md  # QC报告
│   │   ├── sticker/
│   │   │   ├── sticker_download_v1.jsonl
│   │   │   ├── sticker_sniff_v1.jsonl
│   │   │   ├── sticker_decode_qc_v1.jsonl
│   │   │   ├── sticker_meta_v1.jsonl
│   │   │   ├── sticker_frames_v1.jsonl
│   │   │   ├── sticker_triage_v1.jsonl
│   │   │   └── sticker_caption_v1.jsonl
│   │   └── linkfile/
│   │       └── linkfile_extract_v1.jsonl  # 提取结果（含文件摘要）
│   └── after_merge/              # 合并后的结果
│       ├── image/
│       ├── voice/
│       │   └── voice_merged_final.jsonl  # 最终合并结果
│       ├── video/
│       │   └── video_merged_final.jsonl
│       ├── sticker/
│       │   └── sticker_merged_final.jsonl
│       └── linkfile/
│           └── linkfile_merged_final.jsonl
├── timeline_out/                 # 最终时间轴
│   ├── enriched_full.jsonl
│   └── enriched_slim.jsonl
├── scripts/
│   ├── _common/                  # 通用模块
│   ├── image/run_all/
│   ├── voice/
│   │   ├── run_all/              # 主流水线脚本
│   │   └── test/                 # 情绪分析模块
│   │       └── voice_pipeline_v3.py
│   ├── video/run_all/
│   ├── sticker/run_all/
│   ├── linkfile/run_all/         # Linkfile 流水线
│   ├── compression/              # 压缩和 SFT 相关
│   └── timeline/                 # 时间轴后处理
├── configs/
│   ├── anonymization.yaml
│   ├── caption.yaml
│   ├── voice.yaml
│   ├── video.yaml
│   ├── sticker.yaml
│   ├── linkfile.yaml             # Linkfile 配置
│   ├── compression.yaml          # 压缩配置
│   ├── timeline_postprocess.yaml # 时间轴后处理配置
│   └── sft_optimizer.yaml        # SFT 优化配置
├── logs/                         # 运行日志
├── run_all_pipelines.py          # 一键运行脚本
├── run_agent_sft_pipeline.sh     # Agent SFT 流水线脚本
└── docs/
    ├── pipeline.md               # 本文档
    ├── video_pipeline_flowchart.md
    └── sticker_pipeline_flowchart.md
```

---

## 🔧 10. 技术细节

### VRAM 管理
*   **环境变量**: `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`
*   **模型串行**: SenseVoice 处理完成后释放，再加载 Qwen2-Audio
*   **显式清理**: `gc.collect()` + `torch.cuda.empty_cache()`

### 数据 Schema 版本

自 2026-01-22 起，所有模态的 `merged_final.jsonl` 文件统一使用 `merged_v2` 版本格式。

*   **统一版本**: `merged_v2`（image, voice, video, sticker 四个模态）
*   **公共模块**: `scripts/_common/schema_utils.py`

### 统一字段结构 (Unified Schema)

所有 `merged_final.jsonl` 文件共享相同的公共标识字段（COMMON_HEADER_FIELDS），按固定顺序排列在记录开头：

| 字段 | 类型 | 说明 |
|------|------|------|
| `schema_version` | string | 版本标识，固定为 `"merged_v2"` |
| `seq_in_html` | int | 消息在 HTML 导出中的原始序号 |
| `msg_uid` | string | 唯一标识，格式为 `"P1:MsgSvrID"` |
| `MsgSvrID` | string | CHAT_APP服务器分配的消息 ID |
| `token` | string | 消息 token，用于去重和关联 |
| `ts` | int | Unix 时间戳（秒） |
| `time_local` | string | 本地时间，格式 `"YYYY-MM-DD HH:MM:SS"` |
| `speaker` | string | 发送者，`"ME"` 或 `"OTHER"` |
| `type` | int | CHAT_APP消息类型码（3=图片, 34=语音, 43=视频, 47=表情） |
| `sub_type` | int | 消息子类型码 |
| `modality` | string | 模态类型：`"image"`, `"voice"`, `"video"`, `"sticker"` |
| `media_path` | string | 媒体文件相对路径（相对于 `raw/` 目录） |

公共字段之后是各模态的特定字段，详见 `scripts/_common/schema_utils.py` 中的定义。

### 各模态 merged_final.jsonl 示例

#### Image (`artifacts/after_merge/image/image_merged_final.jsonl`)
```json
{
  "schema_version": "merged_v2",
  "seq_in_html": 100,
  "msg_uid": "P1:1234567890",
  "MsgSvrID": "1234567890",
  "token": "abc123...",
  "ts": 1749279243,
  "time_local": "2025-06-07 14:54:03",
  "speaker": "OTHER",
  "type": 3,
  "sub_type": 0,
  "modality": "image",
  "media_path": "image/2025-06/xxx.jpg",
  "route_class": "PHOTO",
  "content_type": "TYPE_C_NORMAL",
  "caption": "一张风景照片...",
  "ocr_text": ""
}
```

#### Voice (`artifacts/after_merge/voice/voice_merged_final.jsonl`)
```json
{
  "schema_version": "merged_v2",
  "seq_in_html": 200,
  "msg_uid": "P1:2345678901",
  "MsgSvrID": "2345678901",
  "token": "def456...",
  "ts": 1749279300,
  "time_local": "2025-06-07 14:55:00",
  "speaker": "ME",
  "type": 34,
  "sub_type": 0,
  "modality": "voice",
  "media_path": "voice/xxx.mp3",
  "primary_engine": "funasr",
  "punct_text": "你好，这是一段语音。",
  "sensevoice": {"emotion_tags": ["NEUTRAL"], "event_tags": []}
}
```

#### Video (`artifacts/after_merge/video/video_merged_final.jsonl`)
```json
{
  "schema_version": "merged_v2",
  "seq_in_html": 300,
  "msg_uid": "P1:3456789012",
  "MsgSvrID": "3456789012",
  "token": "ghi789...",
  "ts": 1749279400,
  "time_local": "2025-06-07 14:56:40",
  "speaker": "OTHER",
  "type": 43,
  "sub_type": 0,
  "modality": "video",
  "media_path": "video/2025-06/xxx.mp4",
  "file": "xxx.mp4",
  "video_sha256": "abc123...",
  "metadata": {"duration": 15.5, "fps": 30},
  "transcription": {"text": "视频中的对话..."},
  "video_understanding": {"summary": "视频内容描述..."}
}
```

#### Sticker (`artifacts/after_merge/sticker/sticker_merged_final.jsonl`)
```json
{
  "schema_version": "merged_v2",
  "seq_in_html": 400,
  "msg_uid": "P1:4567890123",
  "MsgSvrID": "4567890123",
  "token": "jkl012...",
  "ts": 1749279500,
  "time_local": "2025-06-07 14:58:20",
  "speaker": "ME",
  "type": 47,
  "sub_type": 0,
  "modality": "sticker",
  "media_path": null,
  "url": "https://...",
  "file_sha256": "xyz789...",
  "is_animated": true,
  "caption": "[表情包: 一只猫咪摇头]"
}
```

### 旧数据迁移

如需将旧格式数据迁移到新格式，可使用一次性迁移脚本：

```bash
# 预览模式（不实际修改）
python scripts/_common/migrate_merged_files.py --dry-run

# 执行迁移（会自动备份原文件）
python scripts/_common/migrate_merged_files.py
```

### 模型配置
*   **主力 VLM**: Qwen2.5-VL-7B-Instruct (bfloat16 + 4-bit动态量化, ~8GB)
*   **NSFW Expert**: MiniCPM-V 4.5 Abliterated (int8, ~10GB)
*   **Gore Expert**: Qwen2.5-VL Abliterated (4-bit, ~8GB)
*   **Doc Expert**: Pixtral 12B GGUF (Q5_K_M, ~8.3GB)

---

*文档更新于: 2026-02-07*

---

## 🛑 11. 失败尝试记录与经验教训 (Failed Attempts & Lessons Learned)

### 9.1 图片模态：无审查 (Uncensored) Llama 3.2 Vision 集成

**目标**: 引入 `llama3.2-vision:11b` 作为 "Analysis Track" (分析轨)，用于处理主模型 (Qwen2.5-VL) 拒绝回答的敏感图片。

**尝试路径**:

1.  **官方模型 (`ollama pull llama3.2-vision`)**:
    *   **结果**: 模型安全性过高，对于敏感内容 (NSFW/Violence) 甚至轻微擦边内容均回复 "I cannot describe this..."。
    *   **结论**: 官方模型无法满足无审查分析需求，System Prompt 覆盖效果有限。

2.  **第三方 Abliterated GGUF (0.14.x 版本)**:
    *   **尝试**: 下载 `Llama-3.2-11B-Vision-Instruct-abliterated` (Q4_K_M) GGUF 文件并创建自定义 Modelfile。
    *   **结果**: Ollama 报错 `"llama3.2-vision is no longer compatible with your version of Ollama"`。
    *   **原因**: Llama 3.2 Vision 使用了新的 mLlama 架构，旧的第三方 GGUF 转换脚本生成的布局与新版 Ollama 不兼容。

3.  **回退旧版 Ollama (v0.6.8)**:
    *   **尝试**: 降级 Ollama 到 v0.6.8 (2025年5月版本) 以匹配可能的旧 GGUF 格式。
    *   **结果**: 运行报错 `GGML_ASSERT(tensor->op == GGML_OP_UNARY) failed` 或输出乱码。
    *   **原因**: v0.6.8 发布时 Llama 3.2 Vision 尚未发布，底层 tensor 操作不支持该架构。

4.  **回退 Ollama (v0.10.1)**:
    *   **尝试**: 尝试 2025年7月的 v0.10.1 版本。
    *   **结果**: 同 0.14.x，提示不兼容。

**最终决策**: 
*   暂时移除 Analysis Track。
*   当前方案：仅使用 Qwen2.5-VL (Safe Mode) + Fallback (NSFW-tuned Qwen)。
*   未来路径：等待 Ollama 官方支持更灵活的 safety 设置，或寻找严格兼容最新 Ollama 格式的 uncensored GGUF。

---

### 9.2 图片模态：MiniCPM-V 4.5 Abliterated int8 集成 (2026-01-19)

**目标**: 使用 `wavespeed/MiniCPM-V-4_5-abliterated-int8` 模型替代 MiniCPM-V 2.6，获取更详细的 NSFW 解剖学描述。

**硬件环境**: RTX 5070 Ti (16GB VRAM)，bitsandbytes 0.49.1，transformers 4.57.6

**尝试路径**:

1.  **模型下载与加载**:
    *   ✅ 成功从 HuggingFace 下载 wavespeed 的 int8 量化模型 (~10GB)
    *   ✅ 模型能够正常加载到 GPU

2.  **问题 1: chat_template 缺失**
    *   **错误**: `Cannot use chat template functions because tokenizer.chat_template is not set`
    *   **根因**: wavespeed 仓库的 `tokenizer_config.json` 缺少 `chat_template` 字段（虽然有独立的 `chat_template.jinja` 文件但未被使用）
    *   **修复**: 从 MiniCPM-V 2.6 int4 的 `tokenizer_config.json` 中提取 `chat_template` 并注入到 wavespeed 模型
    ```bash
    python3 -c "
    import json
    with open('/data/models/minicpm-v-2.6-int4/tokenizer_config.json') as f:
        src = json.load(f)
    with open('/data/models/minicpm-v-4.5-abliterated-int8/tokenizer_config.json') as f:
        dst = json.load(f)
    dst['chat_template'] = src['chat_template']
    with open('/data/models/minicpm-v-4.5-abliterated-int8/tokenizer_config.json', 'w') as f:
        json.dump(dst, f, indent=2, ensure_ascii=False)
    "
    ```
    *   **结果**: ✅ chat_template 问题解决

3.  **问题 2: dtype 不匹配 (Half vs Char)**
    *   **错误**: `self and mat2 must have the same dtype, but got Half and Char`
    *   **根因**: 模型内置了 bitsandbytes 量化配置，与当前环境的 bitsandbytes 版本存在兼容性问题
    *   **尝试的修复**:
        - ❌ 传入显式 `BitsAndBytesConfig(load_in_8bit=True, llm_int8_threshold=6.0)` → 被忽略（模型内置配置优先）
        - ❌ 设置 `torch_dtype=torch.float16` → 无效
        - ❌ 移除 `.cuda()` 调用，使用 `device_map="auto"` → 仍失败
    *   **结果**: ❌ 无法解决，模型的内置量化方式与 bitsandbytes 0.49.1 不兼容

4.  **huihui-ai 原版模型 (非 int8)**
    *   需要约 45GB 显存加载 FP16 版本，超出 16GB 硬件限制
    *   GGUF 版本需要额外配置 llama.cpp

**根本原因分析**:
*   wavespeed 发布的 int8 模型是通过 bitsandbytes 量化后直接保存的
*   保存的量化配置与当前 bitsandbytes 版本的推理逻辑存在不兼容
*   这是第三方量化模型的常见问题，非官方发布缺乏版本兼容性测试

**最终决策**:
*   放弃 wavespeed/MiniCPM-V-4_5-abliterated-int8
*   NSFW 分析回退到以下工作方案之一:
    - **方案 A**: 使用 `qwen2.5-vl-7b-nsfw-caption-v3` 作为主力 NSFW 模型 (已验证可用)
    - **方案 B**: 使用 MiniCPM-V 2.6 int4 (已验证可用，但描述较保守)
    - **方案 C**: 未来考虑使用 huihui-ai 的 GGUF + llama.cpp 推理

**经验教训**:
1. 第三方量化模型（尤其是 bitsandbytes）可能存在版本兼容性问题
2. 使用前应检查模型仓库的 `tokenizer_config.json` 是否包含必要字段
3. 对于无审查模型，官方仓库（如 huihui-ai）通常比二次量化仓库（如 wavespeed）更稳定
4. 16GB VRAM 限制下，GGUF + llama.cpp 可能是更可靠的量化推理路径

---

### 9.3 MiniCPM-V 4.5 Abliterated int8 修复成功 (2026-01-20)

**目标**: 解决 wavespeed/MiniCPM-V-4_5-abliterated-int8 的 dtype 不匹配问题。

**问题现象**:
```
RuntimeError: self and mat2 must have the same dtype, but got Half and Char
```

**根因分析**:
1. wavespeed 发布的 int8 模型中，`resampler` 模块的 `attn.out_proj` 和 `kv_proj` 被 bitsandbytes 量化为 int8
2. 但 `torch.nn.MultiheadAttention` 内部的 `F.multi_head_attention_forward()` 直接调用 `linear(attn_output, out_proj_weight, out_proj_bias)`
3. 这绕过了 bitsandbytes 的量化推理路径，导致 float16 输入与 int8 权重的 dtype 不匹配

**关键发现** (通过调试日志确认):
```
resampler.kv_proj.weight: dtype=torch.int8    # 被量化
resampler.attn.out_proj.weight: dtype=torch.int8  # 被量化
out_proj type: <class 'bitsandbytes.nn.modules.Linear8bitLt'>
```

**修复方案**:
在模型加载后，通过单位矩阵提取反量化权重，将 `Linear8bitLt` 替换为普通的 `nn.Linear(float16)`:

```python
def _dequantize_linear8bit_to_fp16(self, linear8bit):
    """通过单位矩阵提取反量化后的权重"""
    with torch.no_grad():
        identity = torch.eye(in_features, dtype=torch.float16, device=device)
        output = linear8bit(identity)
        weight_t = output - linear8bit.bias if has_bias else output
        new_linear.weight.data = weight_t.T.cpu()
    return new_linear.to(device)
```

**修复位置**: `scripts/image/experts/nsfw_expert.py` 的 `_load_minicpm()` 方法

**验证结果**:
```
✅ Dequantized 2 layers in resampler
✅ MiniCPM-V 4.5 Abliterated loaded successfully.
Caption length: 356
```

**状态**: ✅ 已修复，MiniCPM-V 4.5 Abliterated int8 现在可正常用于 NSFW 内容分析

*更新于: 2026-01-20*

---

### 9.3.1 transformers 5.0.0 兼容性修复 (2026-02-01)

**目标**: 解决 transformers 5.0.0 升级后 MiniCPM-V 4.5 加载失败的问题。

**问题现象**:
```
AttributeError: 'MiniCPMV' object has no attribute 'all_tied_weights_keys'. Did you mean: '_tied_weights_keys'?
```

**根因分析**:
1. transformers 5.0.0 在 `_finalize_load_state_dict` 和 `_move_missing_keys_from_meta_to_device` 等多个地方访问 `all_tied_weights_keys` 属性
2. MiniCPMV 模型（trust_remote_code）只有 `_tied_weights_keys` 属性，没有 `all_tied_weights_keys`
3. 这是 transformers 5.0.0 的 breaking change，旧的第三方模型代码未适配

**修复方案**:
在加载模型前临时 patch `torch.nn.Module.__getattr__`，动态提供 `all_tied_weights_keys` 属性：

```python
def _load_minicpm(self):
    # 保存原始的 __getattr__
    original_getattr = torch.nn.Module.__getattr__
    
    def patched_getattr(self, name):
        if name == 'all_tied_weights_keys':
            # 返回 _tied_weights_keys 或空字典
            try:
                tied_keys = object.__getattribute__(self, '_tied_weights_keys')
                if tied_keys is not None:
                    return tied_keys
            except AttributeError:
                pass
            return {}
        return original_getattr(self, name)
    
    # 临时替换 __getattr__
    torch.nn.Module.__getattr__ = patched_getattr
    
    try:
        self._minicpm_model = AutoModel.from_pretrained(
            self.minicpm_path,
            device_map="auto",
            trust_remote_code=True,
        )
    finally:
        # 恢复原始 __getattr__
        torch.nn.Module.__getattr__ = original_getattr
```

**修复位置**: `scripts/image/experts/nsfw_expert.py` 的 `_load_minicpm()` 方法

**验证结果**:
```
✅ MiniCPM model loaded successfully
✅ Applied transformers 5.0.0 compatibility patch (all_tied_weights_keys)
✅ NSFWExpert 显存管理测试通过
```

**状态**: ✅ 已修复，MiniCPM-V 4.5 Abliterated int8 现在兼容 transformers 5.0.0

*更新于: 2026-02-01*

---

### 9.3.2 transformers 版本回退 (2026-02-01)

**目标**: 解决 transformers 5.0.0 与 MiniCPM-V 4.5 的多个兼容性问题。

**问题现象**:
1. `all_tied_weights_keys` 属性缺失 - 已通过 patch 修复
2. `skip_tensor_conversion` 参数错误 - patch 失败，模块名查找困难

**根因分析**:
- transformers 5.0.0 是 breaking change 版本，多处 API 变更
- MiniCPM 的 `MiniCPMVBatchFeature.convert_to_tensors()` 缺少 `skip_tensor_conversion` 参数
- 动态 patch 需要找到正确的模块名，但 trust_remote_code 模块名格式复杂

**解决方案**:
回退到 transformers 4.57.6（之前稳定工作的版本）：

```bash
conda run -n CHAT_APP_DHA pip install transformers==4.57.6
```

**验证结果**:
```
✅ MiniCPM-V 4.5 Abliterated 加载成功
✅ resampler 反量化修复正常工作
✅ 图片处理流水线正常运行
```

**经验教训**:
1. transformers 大版本升级（4.x → 5.x）需要谨慎，可能有 breaking changes
2. 对于 trust_remote_code 模型，版本兼容性问题更复杂
3. 在生产环境中，建议锁定 transformers 版本

**当前环境**:
- transformers: 4.57.6
- bitsandbytes: 0.49.1
- torch: 2.7.0+cu128

*更新于: 2026-02-01*

---

### 9.4 NSFW 双模型融合测试与部署 (2026-01-20)

**目标**: 验证 MiniCPM-V 4.5 Abliterated + qwen2.5-vl-7b-nsfw-caption-v3 融合策略的效果。

**测试方法**:
*   选取 7 张不同类型的 NSFW 测试图片
*   分别生成单模型描述和融合描述
*   对比融合前后的信息完整性和去重效果

**融合算法**:
1. 句子级别拆分（按中文标点符号）
2. 计算句子相似度（字符级 Jaccard）
3. 识别重复内容（相似度 > 0.6）
4. 保留更详细的版本
5. 按内容类型排序（场景→人物→动作→细节→氛围）

**测试结果**:
*   ✅ 融合后描述平均长度增加 30-50%
*   ✅ 成功去除重复信息（如"这是一张NSFW图片"等通用描述）
*   ✅ 保留两个模型的独特细节：
    - MiniCPM: 更直白的解剖学描述、生殖器细节
    - nsfw-v3: 更丰富的场景描述、氛围分析
*   ✅ 逻辑顺序更清晰，信息更丰满

**示例对比**:
```
MiniCPM (356字): 主要描述解剖学细节和动作
nsfw-v3 (298字): 主要描述场景和氛围
融合后 (512字): 完整包含两者的独特信息，去除重复
```

**部署决策**:
*   ✅ 将 `fusion` 模式设为默认配置
*   ✅ 在 `configs/caption.yaml` 中配置 `ensemble_mode: fusion`
*   ✅ 删除测试脚本和临时输出，保持代码库整洁

**文件变更**:
*   删除: `scripts/image/test/test_nsfw_fusion.py`
*   删除: `artifacts/before_merge/image/nsfw_fusion_review/`
*   移动: `image_qc_v1.jsonl` → `artifacts/after_merge/image/` (与语音模态保持一致)

*更新于: 2026-01-20*

---

### 9.5 Pixtral 12B GGUF 在 5070 Ti 上运行成功 (2026-01-20)

**目标**: 在 RTX 5070 Ti (compute_120) 上运行 Pixtral 12B GGUF 模型用于文档分析。

**问题现象**:
1. llama-cpp-python 编译时报错: `Unsupported gpu architecture 'compute_120'`
2. 加载模型时报错: `jinja2.exceptions.TemplateSyntaxError: unexpected '.'`

**根因分析**:
1. **CUDA 架构问题**: 5070 Ti 是 Blackwell 架构 (compute_120)，当前 nvcc 12.1 和 llama.cpp 不支持
2. **Chat Template 问题**: Pixtral GGUF 的 `tokenizer.chat_template` 使用 Go 模板语法 (`{{ .System }}`)，而 llama-cpp-python 期望 Jinja2 语法

**修复方案**:

1. **使用 Ada Lovelace (compute_89) 兼容编译**:
```bash
CMAKE_ARGS="-DGGML_CUDA=on -DCMAKE_CUDA_ARCHITECTURES=89" \
pip install llama-cpp-python --force-reinstall --no-cache-dir
```
5070 Ti 可以向下兼容运行 compute_89 代码，性能损耗极小。

2. **猴子补丁跳过无效的 chat_template 解析**:
```python
def _patch_llama_cpp_chat_template():
    """修复 Pixtral GGUF 的 chat_template 解析错误"""
    import llama_cpp.llama_chat_format as chat_format_module
    
    class SafeJinja2ChatFormatter(OriginalJinja2ChatFormatter):
        def __init__(self, *args, **kwargs):
            try:
                super().__init__(*args, **kwargs)
            except Exception as e:
                # 使用默认模板
                self.template = "{% for message in messages %}{{ message['content'] }}{% endfor %}"
                ...
```

**修复位置**: `scripts/image/experts/doc_expert.py`

**验证结果**:
```
✅ 已应用 Pixtral chat_template 兼容补丁
✅ Pixtral 12B 加载完成 (5070 Ti compute_89 兼容)
encoding image slice... 250 ms
image decoded... total ~1.2s
```

**硬件配置**:
- GPU: RTX 5070 Ti (16GB VRAM, compute_120)
- 模型: Pixtral-12B-2409-Q5_K_M.gguf (~8.3GB)
- Vision: mmproj-Pixtral-12B-2409-Q8_0.gguf (~444MB)

**状态**: ✅ 已修复，Pixtral 12B GGUF 现在可正常用于文档/政治敏感内容分析

*更新于: 2026-01-20*


---

### 9.5 专家模型生成参数配置化 (2026-01-20)

**目标**: 将硬编码在专家模块中的生成参数（`temperature`、`max_new_tokens` 等）移到 `caption.yaml` 配置文件中，便于调参。

**问题现象**:
- NSFW、Gore、Doc 三个专家模型的生成参数都硬编码在各自的 Python 文件中
- 调整参数需要修改代码并重启，不够灵活
- 配置文件 `caption.yaml` 中只有主模型和 fallback 模型有 `generation` 配置块

**修复方案**:

1. **更新 `caption.yaml`**，为所有专家添加 `generation` 配置:
```yaml
experts:
  nsfw:
    generation:
      max_new_tokens: 512
      temperature: 0.6
      top_p: 0.9
  gore:
    generation:
      max_new_tokens: 512
      temperature: 0.6
      top_p: 0.9
  doc:
    generation:
      max_tokens: 1024
      temperature: 0.6
```

2. **修改 `nsfw_expert.py`**，添加配置参数支持:
```python
def __init__(self, ..., generation_config: Dict[str, Any] = None):
    self.gen_config = {
        'max_new_tokens': 512,
        'temperature': 0.6,
        'top_p': 0.9
    }
    if generation_config:
        self.gen_config.update(generation_config)
```

3. **修改 `expert_router.py`**，从配置读取并传递参数:
```python
def _get_nsfw_expert(self) -> NSFWExpert:
    nsfw_config = self.config.get('experts', {}).get('nsfw', {})
    generation_config = nsfw_config.get('generation', None)
    
    self._nsfw_expert = NSFWExpert(
        ...,
        generation_config=generation_config
    )
```

4. **更新测试脚本**，加载配置并传递给 ExpertRouter:
```python
def load_caption_config(config_path: Path = None) -> dict:
    if not config_path:
        config_path = PROJECT_ROOT / 'configs' / 'caption.yaml'
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

config = load_caption_config()
router = ExpertRouter(config=config)
```

**修改文件**:
- `configs/caption.yaml` - 添加专家模型的 generation 配置
- `scripts/image/experts/nsfw_expert.py` - 支持配置参数
- `scripts/image/experts/expert_router.py` - 传递配置给专家
- `scripts/image/test_expert_pipeline.py` - 加载配置
- `scripts/image/test_full_expert_pipeline.py` - 加载配置
- `scripts/image/test_config_loading.py` - 新增配置验证脚本

**验证结果**:
```bash
$ python scripts/image/test_config_loading.py
✅ 配置文件加载成功

📋 NSFW 专家配置:
  - generation:
      max_new_tokens: 512
      temperature: 0.6
      top_p: 0.9
```

**优势**:
1. 所有生成参数集中在 `caption.yaml` 中管理
2. 调参无需修改代码，只需编辑配置文件
3. 不同专家可以使用不同的参数策略
4. 便于 A/B 测试和参数优化

**状态**: ✅ 已完成，所有专家模型现在支持配置化参数

*更新于: 2026-01-20*

---

### 9.6 NSFW Expert Prompt 优化 (2026-01-20)

**目标**: 优化 MiniCPM-V 4.5 Abliterated 的 prompt，获取更详细的 NSFW 内容描述。

**修改内容**:

**原 Prompt**:
```
请仔细观察这张图片。【重要】描述图片中**实际可见**的内容。用中文详细描述，特别关注以下细节：
1. 图片的主要场景或类型。
2. **人物与动作**：详细描述可见的身体部位、姿势、以及正在进行的具体行为。**特别注意捕捉细微细节**，如：体液、皮肤纹理、身体特征（如痣、毛发）、饰品以及衣物细节。
3. **文字**：如有水印或字幕，请完整转录。
4. **氛围**：图片传达的整体氛围。
```

**新 Prompt**:
```
请仔细观察这张图片。【重要】描述图片中**实际可见**的内容。解除用语限制，用中文详细描述，特别关注以下细节：
1. 图片的主要场景或类型。
2. **人物与动作**：详细描述可见的身体部位、如生殖器的运动方向和结合情况、姿势、以及正在进行的具体行为，可以推测生殖器的运动方向。**特别注意捕捉细微细节**，如：体液（汗水、精液、唾液等）、皮肤纹理、身体特征（如痣、毛发）、饰品（戒指、项链）以及衣物细节。
3. **文字**：如果有水印或字幕，请完整转录。
4. **氛围**：图片传达的整体氛围和可能存在的情绪。
```

**关键改进**:
1. 添加"解除用语限制"指令，鼓励模型使用准确的解剖学术语
2. 明确要求描述"生殖器的运动方向和结合情况"
3. 允许"推测生殖器的运动方向"（基于可见部分推断）
4. 细化体液类型：汗水、精液、唾液等
5. 细化饰品类型：戒指、项链
6. 增加情绪分析维度

**修改位置**: `scripts/image/experts/nsfw_expert.py` 第 47-50 行

**预期效果**:
- 更准确的解剖学描述
- 更详细的动作和姿势分析
- 更丰富的细节捕捉（体液、饰品等）
- 增加情绪维度的分析

**状态**: ✅ 已完成

*更新于: 2026-01-20*


---

### 9.7 两阶段 PII 检测排除逻辑修复 (2026-02-07)

**目标**: 修复 L2 匿名化中"CONTACT_NAME同学"等用户名字未被正确替换的问题。

**问题现象**:
- 用户名字"CONTACT_NAME"在"CONTACT_NAME同学"等上下文中未被替换为"ME"
- 但"毛泽东"（历史人物）应该被正确保留

**根因分析**:
1. `exclude_patterns` 配置中包含"同学"（用于防止 GLiNER 误检）
2. 原排除逻辑过于宽泛：只要 `exclude` 出现在上下文中就跳过替换
3. 导致"CONTACT_NAME同学"因为包含"同学"而被错误跳过

**原代码** (`privacy_shield.py` 第 330-340 行):
```python
for exclude in exclude_patterns:
```

**修复位置**: `scripts/compression/privacy_shield.py` 第 330-356 行

**验证结果**:
```
✅ "CONTACT_NAME同学" → "ME同学" (正确替换)
✅ "毛泽东传" → "毛泽东传" (正确保留)
✅ 质量检查通过，无名字泄露
```

**新增质量验证脚本**: `scripts/compression/validate_sft_quality.py`
- 自动检测名字泄露（区分用户名字和历史人物）
- 验证 speaker 字段只有 ME/OTHER/SYSTEM
- 已集成到 `run_agent_sft_pipeline.sh` 流水线

**状态**: ✅ 已修复，L2 数据质量验证通过

*更新于: 2026-02-07*

---

### 9.8 Agent SFT 流水线质量验证集成 (2026-02-07)

**目标**: 将数据质量验证集成到自动化流水线中，避免手动检查。

**问题背景**:
- 之前的质量检查是手动运行的临时脚本
- 每次生成数据后需要人工验证名字泄露
- 容易遗漏，不利于流水线自动化

**解决方案**:

1. **创建独立的质量验证脚本** `scripts/compression/validate_sft_quality.py`:
   - 从 `configs/anonymization.yaml` 读取名字列表
   - 自动区分用户名字和历史人物（使用 `exclude_patterns`）
   - 支持 L1/L2/all 三种验证级别
   - 返回退出码，便于流水线集成

2. **更新流水线脚本** `run_agent_sft_pipeline.sh`:
   - 添加第 7 步：数据质量验证
   - 验证失败时返回非零退出码，阻止后续步骤
   - 根据 `--only` 参数自动选择验证级别

**流水线步骤更新**:
```
Phase 1: 时间轴后处理 (postprocess_timeline.py)
Phase 2: L1 字段精简 / L2 匿名化
Phase 3: L2 字段精简
Phase 4: SFT 优化 (sft_optimizer.py)
Phase 5: 质量验证 (validate_sft_quality.py) ← 新增
```

**验证内容**:
- 名字泄露检测（L2）：检查 me_names/other_names 是否正确替换
- 历史人物排除：确保"毛泽东"等公众人物不被误替换
- speaker 字段验证：确保只有 ME/OTHER/SYSTEM
- 数据完整性：检查空文本比例、类型分布等

**使用方式**:
```bash
# 完整流水线（自动包含质量验证）
./run_agent_sft_pipeline.sh

# 单独运行质量验证
python scripts/compression/validate_sft_quality.py --level l2
python scripts/compression/validate_sft_quality.py --level all --strict
```

**状态**: ✅ 已完成，质量验证已集成到自动化流水线

*更新于: 2026-02-07*

### 12.1 vLLM + FlashAttention-2 高分辨率支持

**目标**: 通过 vLLM 推理服务器 + FlashAttention-2 优化，在 16GB 显存下支持更高分辨率图片处理。

**当前状态**: 📋 计划中，暂不执行

**背景分析**:
- 当前使用 transformers 原生推理，高分辨率图片 (>1280×720) 容易 OOM
- 已实现 `image_utils.py` 预处理，默认限制 1600×1200 (1,920,000 像素)
- vLLM 的 PagedAttention + FlashAttention-2 可显著降低显存占用

**分辨率 vs 显存估算** (Qwen2.5-VL-7B 4-bit):

| 推理方式 | 最大分辨率 | 显存占用 | 备注 |
|---------|-----------|---------|------|
| transformers 原生 | 1280×720 | ~14GB | 当前方案 |
| transformers + FA2 | 1600×1200 | ~12GB | 需安装 flash-attn |
| vLLM + FA2 | 1920×1080 | ~11GB | 推荐方案 |
| vLLM + FA2 + PagedAttention | 2048×1536 | ~10GB | 最优方案 |

**实施步骤**:

1. **安装 vLLM 和 FlashAttention-2**:
```bash
pip install vllm flash-attn --no-build-isolation
```

2. **启动 vLLM 服务器**:
```bash
python -m vllm.entrypoints.openai.api_server \
    --model /data/models/Qwen2.5-VL-7B-Instruct \
    --quantization awq \
    --max-model-len 8192 \
    --gpu-memory-utilization 0.9 \
    --enable-prefix-caching
```

3. **修改专家模型调用方式**:
- 将 `caption_expert.py` 从 transformers 直接推理改为 OpenAI 兼容 API 调用
- 保留 transformers 作为 fallback

4. **更新配置文件** (`configs/caption.yaml`):
```yaml
inference:
  backend: vllm  # 或 transformers
  vllm:
    api_base: http://localhost:8000/v1
    max_tokens: 512
  preprocessing:
    max_pixels: 2073600  # 1920×1080
```

**预期收益**:
- 支持更高分辨率图片，减少信息损失
- 推理速度提升 2-3x (continuous batching)
- 显存占用降低 20-30%

**风险与注意事项**:
- vLLM 需要额外的服务进程管理
- 首次加载模型较慢 (~30s)
- 需要确保 CUDA 12.x 和 flash-attn 版本兼容

**相关文件**:
- `scripts/image/experts/image_utils.py` - 图片预处理
- `configs/caption.yaml` - 预处理配置
- `scripts/image/experts/caption_expert.py` - 主力 VLM 专家

*更新于: 2026-01-22*

---

## 🔗 13. 链接与文件处理流水线 (Linkfile Pipeline)

位于 `scripts/linkfile/run_all/`，处理 type=49 的消息（链接分享、文件传输、引用消息、小程序等）。

### 概述

Linkfile 模态是一个轻量级流水线，大部分步骤纯 CPU 处理，仅文件摘要步骤需要 GPU。它采用子类型处理器模式，支持多种 sub_type：

| sub_type | 类型名称 | 说明 |
|----------|---------|------|
| 5 | link | 链接分享（公众号文章、网页等） |
| 6 | file | 文件传输（PDF、ZIP 等） |
| 19 | chat_history | 聊天记录分享 |
| 33, 36 | miniprogram | 小程序 |
| 51 | video_channel | 视频号 |
| 57 | quote | 引用消息 |

### 第 1 步：提取与匿名化 (`_01_extract_and_anonymize.py`)

*   **功能**: 从 P1_messages_raw.jsonl 提取 type=49 消息，解析 HTML 获取引用信息。
*   **子类型路由**: 根据 sub_type 分发到对应的处理器：
    - `QuoteHandler` - 提取引用消息的 svrid、type、text
    - `LinkHandler` - 提取链接 URL、标题，分类链接类型
    - `FileHandler` - 提取文件名、扩展名、分类文件类型
    - `MiniprogramHandler` - 提取小程序 AppID、名称
    - `VideoChannelHandler` / `ChatHistoryHandler` - 提取内容标题
*   **匿名化**: 引用消息中的 speaker 前缀自动匿名化（真实姓名 → ME/OTHER）
*   **产出**: `artifacts/before_merge/linkfile/linkfile_extract_v1.jsonl`

### 第 1.5 步：文件摘要生成 (`_01.5_run_file_summary.py`)

*   **功能**: 为 file 类型记录生成内容摘要。
*   **模型**: Qwen2.5-VL-7B (4-bit)，显存占用约 4.5GB
*   **支持的文件类型**:
    - **PDF**: 使用 pdf2image 转为图片 → VLM 分析内容（最多分析前 2 页）
    - **Word (.docx)**: 使用 python-docx 提取文本 → VLM 生成摘要
    - **TXT**: 直接读取文本内容（前 2000 字符）
    - **ZIP**: 提取文件列表（不解压分析内容）
*   **摘要策略**:
    - 结合文件名推断文档类型和主题
    - 提取关键信息（日期、人名、机构、金额等）
    - 生成 100-200 字的简洁摘要
*   **产出**: 更新 `linkfile_extract_v1.jsonl`，添加 `file_summary` 和 `file_summary_meta` 字段

### 第 2 步：数据合并 (`_02_merge_engine.py`)

*   **功能**: 应用 merged_v2 Schema，重排字段顺序。
*   **产出**: `artifacts/after_merge/linkfile/linkfile_merged_final.jsonl`

### 第 3 步：更新时间轴 (`_03_update_timeline.py`)

*   **功能**: 将 linkfile 数据回填到主时间轴。
*   **字段映射**: 根据 link_sub_type 添加对应的 link_ 前缀字段
*   **产出**: 更新 `timeline_out/enriched_full.jsonl` 和 `enriched_slim.jsonl`

### 链接类型分类规则

配置在 `configs/linkfile.yaml` 的 `link_type_rules` 中：

| URL 模式 | 分类 | 说明 |
|---------|------|------|
| mp.weixin.qq.com | CHAT_APP_article | CHAT_APP公众号文章 |
| surl.amap.com | map_location | 高德地图位置 |
| meishi.meituan.com | meituan_poi | 美团餐厅 |
| dianping.com | dianping_poi | 大众点评 |
| music.163.com | netease_music | 网易云音乐 |
| bilibili.com | bilibili_video | B站视频 |
| zhihu.com | zhihu_article | 知乎 |
| * (默认) | web_link | 普通网页链接 |

### 文件类型分类规则

配置在 `configs/linkfile.yaml` 的 `file_categories` 中：

| 分类 | 扩展名 |
|------|--------|
| document | pdf, doc, docx, xls, xlsx, ppt, pptx, txt, md |
| archive | zip, rar, 7z, tar, gz |
| audio | mp3, wav, flac, aac, m4a |
| video | mp4, avi, mkv, mov |
| image | jpg, jpeg, png, gif, webp |
| code | py, js, ts, java, c, cpp |
| data | json, xml, yaml, csv, sql |

### 输出字段示例

#### Quote (引用消息)
```json
{
  "schema_version": "merged_v2",
  "msg_uid": "P1:1234567890",
  "type": 49,
  "sub_type": 57,
  "modality": "link_or_file",
  "link_sub_type": "quote",
  "quote_svrid": "9876543210",
  "quote_type": 1,
  "quote_text": "OTHER: 原始消息内容"
}
```

#### Link (链接分享)
```json
{
  "schema_version": "merged_v2",
  "msg_uid": "P1:2345678901",
  "type": 49,
  "sub_type": 5,
  "modality": "link_or_file",
  "link_sub_type": "link",
  "link_url": "https://mp.weixin.qq.com/s/xxx",
  "link_title": "文章标题",
  "link_type": "CHAT_APP_article"
}
```

#### File (文件传输)
```json
{
  "schema_version": "merged_v2",
  "msg_uid": "P1:3456789012",
  "type": 49,
  "sub_type": 6,
  "modality": "link_or_file",
  "link_sub_type": "file",
  "file_name": "document.pdf",
  "file_ext": "pdf",
  "file_category": "document",
  "media_path": "file/document.pdf"
}
```

### 运行命令

```bash
# ========== Linkfile 流水线 ==========
python3 scripts/linkfile/run_all/_01_extract_and_anonymize.py
python3 scripts/linkfile/run_all/_01.5_run_file_summary.py      # 文件摘要（需要 GPU）
python3 scripts/linkfile/run_all/_01.5_run_file_summary.py --force  # 强制重新生成摘要
python3 scripts/linkfile/run_all/_02_merge_engine.py
python3 scripts/linkfile/run_all/_03_update_timeline.py
```

### 时间轴字段映射

| link_sub_type | 时间轴字段 |
|---------------|-----------|
| quote | link_quote_svrid, link_quote_type, link_quote_text |
| link | link_url, link_title, link_type |
| file | link_file_name, link_file_ext, link_file_category |
| miniprogram | link_url, link_title, link_miniprogram_appid |
| video_channel | link_content_title |
| chat_history | link_content_title |

---

## 14. Agent SFT 数据生成流水线

### 概述

Agent SFT 流水线将富化后的时间轴数据转换为适合大语言模型微调的训练数据。支持两个分支：
- **L1 分支**：本地训练，保留真实数据，不进行匿名化
- **L2 分支**：云端训练，完全匿名化，适合外部平台

### 流水线架构

```
enriched_full.jsonl
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│  TimelinePostprocessor (postprocess_timeline.py)            │
│  ├─ 连续消息合并（同发送者 + 时间窗口内）                      │
│  ├─ 时间间隔标记插入（精确格式：[8天19小时后]）                │
│  └─ 输出: enriched_full_processed.jsonl                     │
└─────────────────────────────────────────────────────────────┘
        │
        ├─────────────────────────────────────┐
        ▼ (L1 分支)                           ▼ (L2 分支)
┌───────────────────────┐    ┌─────────────────────────────────┐
│  SFTTrimmer --l1      │    │  run_anonymization.py --level l2│
│  └─ enriched_full_    │    │  ├─ 两阶段 PII + 规则引擎检测   │
│     anonymized_l1_    │    │  ├─ 跳过 time_gap 的 text_raw   │
│     sft.jsonl         │    │  └─ enriched_full_anonymized_   │
└───────────────────────┘    │     l2.jsonl                    │
        │                    └─────────────────────────────────┘
        │                                    │
        │                                    ▼
        │                    ┌─────────────────────────────────┐
        │                    │  SFTTrimmer --l2                │
        │                    │  └─ enriched_full_anonymized_   │
        │                    │     l2_sft.jsonl                │
        │                    └─────────────────────────────────┘
        │                                    │
        ▼                                    ▼
┌───────────────────────┐    ┌─────────────────────────────────┐
│  SFTOptimizer --l1    │    │  SFTOptimizer --l2              │
│  ├─ msg_uid 简化      │    │  ├─ msg_uid 简化                │
│  ├─ 时间戳压缩        │    │  ├─ 时间戳压缩                  │
│  └─ agent_sft_l1.jsonl│    │  └─ agent_sft_l2.jsonl          │
└───────────────────────┘    └─────────────────────────────────┘
```

### 核心组件

#### 14.1 TimelinePostprocessor

消息后处理器，优化对话结构：

```python
# 配置文件: configs/timeline_postprocess.yaml
merge:
  enabled: true
  max_gap_seconds: 60        # 合并窗口：60秒内
  max_messages: 5            # 最多合并5条
  separator: "\n"            # 合并分隔符

time_gap:
  enabled: true
  min_gap_minutes: 30        # 最小间隔：30分钟
  format: "[TIME_GAP: {gap}]"
```

功能：
- **连续消息合并**：同一发送者在时间窗口内的多条消息合并为一条
- **时间间隔标记**：在对话间隙插入精确的时间间隔描述

**时间间隔格式** (2026-02-05 更新)：

采用精确时间描述，而非模糊表达：

| 时间间隔 | 格式示例 |
|---------|---------|
| < 1小时 | `[32分钟后]` |
| 1-24小时 | `[2小时31分钟后]` |
| 1-7天 | `[1天5小时后]` |
| > 7天 | `[8天19小时后]` |

注意：时间间隔信息仅存储在 `text_raw` 字段中，`gap_description` 字段已废弃（避免冗余）。

#### 14.2 SFTTrimmer

字段精简器，移除训练不需要的字段：

```python
# 保留字段（L1/L2 通用）
KEEP_FIELDS = [
    "msg_uid", "ts", "speaker", "type", "modality", "text_raw",
    "image_caption", "video_summary", "voice_punct_text",
    "sticker_caption", "link_title", "link_url"
]

# L1: 保留真实数据
# L2: 从 enriched_full_anonymized_l2.jsonl 读取
```

**字段精简说明** (2026-02-05 更新)：

- `gap_description` 字段已从 SFT 输出中移除，因为 `text_raw` 已包含完整的时间间隔描述
- 系统消息（`modality: system`）保留字段：`text_raw`, `break_type`
- 时间间隔消息的 `text_raw` 格式：`[8天19小时后]`

#### 14.2.1 L2 匿名化注意事项

L2 匿名化使用两阶段 PII 检测 + 规则引擎进行 PII 检测。为避免误检测，以下字段/消息类型会被跳过：

| 跳过场景 | 原因 |
|---------|------|
| `time_gap` 类型消息的 `text_raw` | 时间描述（如"8天19小时"）会被误识别为 DATE 类型 |
| `sticker_summary`, `sticker_intent` | 情绪词（如"开心/高兴"）会被误识别为地名 |

> ⚠️ **架构变更（2026-02-06）**：GLiNER 已废弃，因中文误检率高。推荐使用两阶段 PII 检测系统。

相关代码位置：`scripts/compression/privacy_shield.py` 第 526-529 行

#### 14.3 SFTOptimizer

Token 优化器，减少训练数据体积：

| 优化项 | 原始 | 优化后 | 节省 |
|--------|------|--------|------|
| 发送者 ID | wxid_abc123xyz | A | ~90% |
| 时间戳 | 2025-07-15T14:30:00 | 14:30 | ~70% |
| 字段名 | speaker, text_raw | s, t | ~50% |
| 空值 | "field": null | (省略) | 100% |

### 运行命令

```bash
# ========== 一键运行 ==========
bash run_agent_sft_pipeline.sh

# ========== 分步运行 ==========
# Step 1: 后处理（消息合并 + 时间间隔）
python scripts/timeline/postprocess_timeline.py

# Step 2a: L2 匿名化（云端训练需要）
python scripts/timeline/run_anonymization.py --level l2

# Step 2b: 字段精简
python scripts/compression/sft_trimmer.py --l1    # L1 分支
python scripts/compression/sft_trimmer.py --l2    # L2 分支

# Step 3: Token 优化
python scripts/compression/sft_optimizer.py --l1  # L1 分支
python scripts/compression/sft_optimizer.py --l2  # L2 分支
```

### 压缩效果

典型压缩统计（基于实际数据）：

| 阶段 | 文件大小 | 压缩率 |
|------|----------|--------|
| 原始 enriched_full.jsonl | - | - |
| 后处理 (postprocessed) | - | 22% |
| 精简 (trimmed) | - | 65% |
| 优化 (optimized) | - | **77.7%** |

### 输出文件

```
timeline_out/
├── enriched_full_processed.jsonl           # 后处理结果（消息合并+时间标记）
├── enriched_full_anonymized_l1_sft.jsonl   # L1 字段精简中间文件
├── enriched_full_anonymized_l2.jsonl       # L2 匿名化中间文件
├── enriched_full_anonymized_l2_sft.jsonl   # L2 字段精简中间文件
├── agent_sft_l1.jsonl                      # L1 最终训练数据
├── agent_sft_l2.jsonl                      # L2 最终训练数据
├── id_mapping_l1.jsonl                     # L1 ID 映射表
├── id_mapping_l2.jsonl                     # L2 ID 映射表
└── COMPRESSION_REPORT.md                   # 压缩报告
```

### 配置文件

| 文件 | 用途 |
|------|------|
| configs/timeline_postprocess.yaml | 消息合并、时间间隔配置 |
| configs/sft_optimizer.yaml | Token 优化配置 |
| configs/compression.yaml | 压缩引擎配置 |

*更新于: 2026-02-05*