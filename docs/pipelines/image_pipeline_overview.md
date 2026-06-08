# 图片流水线设计概览

> 📌 **本文档定位**：这是 [多模态处理流水线文档](modality_fields_and_models.md) 的详细设计文档，专注于图片流水线的路由分类、专家系统、OCR 优化和显存管理策略。

## 1. 设计理念

### 1.1 核心目标

图片流水线处理微信聊天记录中的图片消息（`type=3`），是所有模态中最核心的处理流程：

| 挑战 | 解决方案 |
|------|----------|
| 图片类型多样（截图/照片/文档） | ImageRouter 智能路由 |
| 敏感内容处理（NSFW/Gore） | Triage 分类 + 专家路由 |
| 文字密集型图片 | OCR + VLM 双引擎 |
| 模型拒绝回答敏感内容 | 专用 Abliterated 模型 |
| 16GB 显存约束 | 串行加载 + 定期清理 |

### 1.2 设计原则

```
┌─────────────────────────────────────────────────────────────────┐
│                      设计原则                                    │
├─────────────────────────────────────────────────────────────────┤
│  1. 智能路由：根据图片特征决定处理策略（OCR/Caption/跳过）      │
│  2. 专家系统：不同内容类型使用专用模型，提高准确性              │
│  3. 媒体过滤：四层级过滤，跳过低质量图片节省资源                │
│  4. OCR 优化：检测框复用，节省 30-40% 处理时间                  │
│  5. 显存安全：16GB 约束下的串行加载策略                         │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. 四阶段流水线架构

### 2.1 整体流程图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          Image Pipeline                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐ │
│   │   Step 1     │   │   Step 2     │   │   Step 3     │   │   Step 4     │ │
│   │     OCR      │──▶│   Caption    │──▶│    Merge     │──▶│   Timeline   │ │
│   │  文字识别    │   │  描述生成    │   │   合并引擎   │   │  时间轴更新  │ │
│   └──────────────┘   └──────────────┘   └──────────────┘   └──────────────┘ │
│          │                  │                  │                  │         │
│          ▼                  ▼                  ▼                  ▼         │
│   image_ocr_v1       image_caption      image_merged       enriched_full   │
│   image_qc_v1        _v1.jsonl          _final.jsonl       .jsonl          │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 各阶段详解

| 阶段 | 脚本 | 输入 | 输出 | 模型 |
|------|------|------|------|------|
| **OCR** | `_01_run_ocr.py` | raw/image/*.jpg | OCR 结果 + QC 报告 | PaddleOCR PP-OCRv4 |
| **Caption** | `_02_run_caption.py` | QC 报告 + 图片 | 图片描述 | Triage + 专家模型 |
| **Merge** | `_03_merge_engine.py` | OCR + Caption | 合并结果 | - |
| **Timeline** | `_04_update_timeline.py` | 合并结果 | 时间轴 | - |

---

## 3. 媒体质量过滤（FilterTier）

### 3.1 四层级过滤

在处理图片之前，先进行媒体质量过滤，避免浪费资源处理低质量图片：

| FilterTier | 条件 | 处理方式 | 说明 |
|------------|------|----------|------|
| **SKIP** | 尺寸 < 50px 或 文件 < 1KB | 完全跳过 | 极低质量，无法识别 |
| **LITE** | 尺寸 < 200px 或 文件 < 10KB | 仅 OCR，不做 VLM | 低质量，节省 GPU |
| **SLICE** | 尺寸 > 4096px 或 文件 > 10MB | 建议切片处理 | 超大图片，防止 OOM |
| **FULL** | 其他 | 完整处理 | 正常质量 |

### 3.2 过滤流程

```
图片加载
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│  媒体质量检查                                                    │
│  ├─ 尺寸检查：width, height                                      │
│  ├─ 文件大小检查：file_size                                      │
│  └─ 返回 FilterTier + 处理建议                                   │
└─────────────────────────────────────────────────────────────────┘
    │
    ├──▶ SKIP ──▶ 写入跳过标记，结束
    │
    ├──▶ LITE ──▶ 仅执行 OCR，跳过 VLM Caption
    │
    ├──▶ SLICE ──▶ 添加切片元数据，继续处理
    │
    └──▶ FULL ──▶ 完整处理流程
```

---

## 4. ImageRouter 路由分类（Step 1）

### 4.1 路由类别

ImageRouter 根据图片特征将图片分为以下类别：

| 路由类别 | 特征 | OCR | Caption | 说明 |
|----------|------|-----|---------|------|
| **TEXT_HEAVY** | 文本密集型 | ✅ 完整 | ✅ | 截图、文档、聊天记录 |
| **GRAY** | 灰度图片 | ✅ | ✅ | 黑白照片、扫描件 |
| **PHOTO** | 纯视觉 | ❌ | ✅ | 风景、人物照片 |
| **VISUAL_ONLY** | 纯视觉 | ❌ | ✅ | 无文字的图片 |
| **VISUAL_PRIMARY** | 视觉为主 | ✅ 轻量 | ✅ | 少量文字的图片 |
| **HYBRID_VISUAL_MAIN** | 混合（视觉主） | ✅ | ✅ | 图文混合，视觉为主 |
| **HYBRID_TEXT_MAIN** | 混合（文字主） | ✅ 完整 | ✅ | 图文混合，文字为主 |
| **SKIPPED** | 跳过 | ❌ | ❌ | 低质量图片 |
| **ERROR** | 错误 | ❌ | ❌ | 加载失败 |

### 4.2 路由决策流程

```
图片加载
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│  ImageRouter.route()                                             │
│  ├─ 1. 检测文本框（PaddleOCR det）                               │
│  ├─ 2. 计算 text_area_ratio（文本区域占比）                      │
│  ├─ 3. 检测灰度图片                                              │
│  ├─ 4. 根据特征决定路由类别                                      │
│  └─ 5. 返回 RouteDecision（包含 boxes 用于 OCR 复用）            │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼
RouteDecision:
  - route_class: 路由类别
  - need_ocr: 是否需要 OCR
  - need_caption: 是否需要 Caption
  - why: 决策依据（包含 boxes）
```

### 4.3 OCR 检测框复用优化

**核心优化**：Router 在路由时已经执行了文本检测，OCR 阶段可以复用这些检测框，只做识别（recognize_only），节省 30-40% 时间。

```python
# 传统方式：检测 + 识别（两次检测）
ocr_result = ocr_expert.extract_text(img_path)  # 内部会再次检测

# 优化方式：复用检测框，只做识别
router_boxes = decision.why.get('boxes')
if router_boxes:
    ocr_result = ocr_expert.recognize_only(img_path, router_boxes)
else:
    ocr_result = ocr_expert.extract_text(img_path)
```

---

## 5. Triage 分类与专家路由（Step 2）

### 5.1 Triage 分类器

Triage 分类器使用 NSFW Classifier 对图片进行内容分类：

| content_type | 触发条件 | 说明 |
|--------------|----------|------|
| **TYPE_A_NSFW** | nsfw_score ≥ 0.5 | 成人内容 |
| **TYPE_B_GORE** | gore_score ≥ 0.5 | 暴力血腥内容 |
| **TYPE_C_NORMAL** | 默认 | 普通图片 |
| **TYPE_D_DOC** | text_area_ratio ≥ 0.15 | 文档/截图 |

### 5.2 专家路由表

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          Expert Router                                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   Triage 分类                                                                │
│        │                                                                     │
│        ├──▶ TYPE_A_NSFW ──▶ NSFWExpert (Ensemble 双模型)                    │
│        │                    ├─ MiniCPM-V 4.5 Abliterated (int8)             │
│        │                    └─ qwen2.5-vl-7b-nsfw-caption-v3                │
│        │                                                                     │
│        ├──▶ TYPE_B_GORE ──▶ GoreExpert                                      │
│        │                    └─ Qwen2.5-VL Abliterated (4-bit)               │
│        │                                                                     │
│        ├──▶ TYPE_C_NORMAL ──▶ CaptionExpert                                 │
│        │                      └─ Qwen2.5-VL-7B-Instruct                     │
│        │                                                                     │
│        └──▶ TYPE_D_DOC ──▶ DocExpert                                        │
│                            └─ Pixtral 12B GGUF (Q5_K_M)                     │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 6. 专家模型详解

### 6.1 NSFWExpert（成人内容专家）

**设计目标**：处理成人内容图片，生成详细、准确的描述。

**双模型 Ensemble 架构**：

| 模型 | 路径 | 量化 | 显存 | 特点 |
|------|------|------|------|------|
| **MiniCPM-V 4.5 Abliterated** | `/data/models/minicpm-v-4.5-abliterated-int8` | int8 | ~10GB | 无审查版本，诚实描述 |
| **nsfw-caption-v3** | `/data/models/qwen2.5-vl-7b-nsfw-caption-v3` | bfloat16 | ~8GB | 专业 NSFW 描述模型 |

**Ensemble 策略**：

| 模式 | 说明 | 适用场景 |
|------|------|----------|
| **Serial** | MiniCPM 优先，输出太短时补充 nsfw-v3 | 默认模式，平衡质量和速度 |
| **Parallel** | 两个模型都生成，选择更详细的 | 追求最佳质量 |
| **Dynamic** | 根据图片复杂度动态选择 | 智能适配 |
| **Fusion** | 两个模型都生成，智能融合去重 | 最高质量（推荐） |

**关键修复**：MiniCPM-V 4.5 int8 量化版本存在 resampler dtype 不匹配问题，需要在加载时进行反量化修复：

```python
# MiniCPM resampler 反量化修复
# 问题：int8 量化后 resampler 层的 dtype 不匹配
# 解决：加载后将 resampler 转换为 float16
model.resampler = model.resampler.to(torch.float16)
```

### 6.2 GoreExpert（暴力内容专家）

**设计目标**：处理暴力、血腥内容，添加警告标记。

| 配置项 | 值 |
|--------|-----|
| 模型 | Qwen2.5-VL Abliterated |
| 路径 | `/data/models/qwen2.5-vl-abliterated` |
| 量化 | 4-bit (bitsandbytes) |
| 显存 | ~8GB |

**输出格式**：
```
⚠️ [警告：暴力内容]
图片描述内容...
```

### 6.3 CaptionExpert（普通图片专家）

**设计目标**：处理普通图片（风景、人物、物品等），是主力模型。

| 配置项 | 值 |
|--------|-----|
| 模型 | Qwen2.5-VL-7B-Instruct |
| 路径 | `/data/models/qwen2.5-vl-7b/Qwen/Qwen2___5-VL-7B-Instruct` |
| 精度 | bfloat16 |
| 显存 | ~8GB |

**Prompt 模板**：
```
请仔细观察这张图片。用中文详细描述图片中的内容，包括：
1. 图片的主要场景或类型（如截图、照片、海报等）。
2. 画面中的关键人物、动作或物体。
3. 如果有显著的文字，请概括文字内容。
4. 图片传达的整体氛围，并推测分享者当时可能想表达的情绪。
```

### 6.4 DocExpert（文档专家）

**设计目标**：处理文档、截图、政治敏感内容，完整提取文字信息。

| 配置项 | 值 |
|--------|-----|
| 模型 | Pixtral 12B |
| 格式 | GGUF (Q5_K_M 量化) |
| 路径 | `/data/models/pixtral-12b-gguf` |
| 显存 | ~8.3GB |
| 上下文 | 4096 tokens |

**为什么使用 Pixtral**：
1. GGUF 格式支持 CPU offload，显存更灵活
2. 12B 参数量，文档理解能力强
3. 对政治敏感内容不会拒绝回答

**Prompt 模板**：
```
请仔细分析这张文档/截图图片，详细提取以下信息：
1. 【文字内容】完整转录图片中所有可见的文字内容
2. 【文档类型】判断文档类型（如聊天记录、网页截图、文章、表格等）
3. 【关键信息】提取关键信息点（日期、人名、数字、网址等）
4. 【情感倾向】分析文字内容的情感倾向
5. 【敏感内容】标记任何敏感词汇或符号
```

---

## 7. 显存管理策略

### 7.1 16GB 显存约束

RTX 5070 Ti 只有 16GB 显存，需要精细管理：

| 模型 | 显存占用 | 说明 |
|------|----------|------|
| PaddleOCR | ~2GB | OCR 阶段 |
| NSFW Classifier | ~0.5GB | Triage 分类 |
| MiniCPM-V 4.5 int8 | ~10GB | NSFW 专家 |
| nsfw-caption-v3 | ~8GB | NSFW 专家 |
| Qwen2.5-VL 4-bit | ~8GB | Gore/Caption 专家 |
| Pixtral 12B GGUF | ~8.3GB | Doc 专家 |

### 7.2 串行加载策略

**核心原则**：单次只加载一个专家模型，避免显存溢出。

```
┌─────────────────────────────────────────────────────────────────┐
│  显存管理流程                                                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. 处理图片前：检查当前加载的专家                               │
│  2. 如果需要切换专家：                                           │
│     a. 卸载当前专家模型                                          │
│     b. gc.collect()                                              │
│     c. torch.cuda.empty_cache()                                  │
│     d. 加载新专家模型                                            │
│  3. 每处理 20 张图片：主动清理显存                               │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 7.3 定期清理

```python
CLEANUP_INTERVAL = 20  # 每 20 张图片清理一次

for idx, item in enumerate(targets, 1):
    # 处理图片...
    
    if idx % CLEANUP_INTERVAL == 0:
        router._unload_all_experts()
        gc.collect()
        torch.cuda.empty_cache()
        torch.cuda.synchronize()
```

### 7.4 环境变量

```bash
# 减少 CUDA 内存碎片
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
```

---

## 8. 图片预处理配置

### 8.1 防止 OOM

高分辨率图片可能导致 OOM，需要限制最大像素数：

```yaml
# configs/caption.yaml
preprocessing:
  max_pixels: 1920000  # 1600×1200
```

| max_pixels | 分辨率 | 说明 |
|------------|--------|------|
| 921600 | 1280×720 | 保守，适合无 FlashAttention |
| 1920000 | 1600×1200 | 适中，需要 FlashAttention-2 |
| 2073600 | 1920×1080 | 激进，需要 vLLM + FlashAttention-2 |

### 8.2 生成参数

```yaml
generation:
  max_new_tokens: 512
  temperature: 0.7
  top_p: 0.9
```

---

## 9. 输出字段

### 9.1 OCR 输出（image_ocr_v1.jsonl）

```json
{
  "msg_uid": "P1:1234567890",
  "route_class": "TEXT_HEAVY",
  "full_text": "识别到的文字内容...",
  "box_count": 15,
  "avg_confidence": 0.9234
}
```

### 9.2 QC 输出（image_qc_v1.jsonl）

```json
{
  "msg_uid": "P1:1234567890",
  "media_path": "image/2025-07/xxx.jpg",
  "qc": {
    "ok": true,
    "width": 1920,
    "height": 1080,
    "format": "JPEG"
  },
  "route_class": "VISUAL_PRIMARY",
  "filter_tier": "FULL",
  "filter_reason": null,
  "need_ocr": true,
  "need_caption": true,
  "det_features": {
    "text_area_ratio": 0.05,
    "boxes": [...]
  },
  "ocr_result": {
    "ok": true,
    "full_text": "...",
    "box_count": 3,
    "avg_confidence": 0.85
  }
}
```

### 9.3 Caption 输出（image_caption_v1.jsonl）

```json
{
  "msg_uid": "P1:1234567890",
  "content_type": "TYPE_C_NORMAL",
  "caption": "这是一张风景照片，展示了...",
  "model_used": "Qwen2.5-VL-7B-Instruct",
  "generation_time": 12.5
}
```

### 9.4 合并输出（image_merged_final.jsonl）

```json
{
  "schema_version": "merged_v2",
  "msg_uid": "P1:1234567890",
  "modality": "image",
  "image_ocr_text": "识别到的文字...",
  "image_caption": "图片描述...",
  "image_content_type": "TYPE_C_NORMAL",
  "image_nsfw_score": 0.02
}
```

---

## 10. 配置文件详解

### 10.1 configs/caption.yaml 结构

```yaml
# 主模型配置
model:
  path: "/data/models/qwen2.5-vl-7b/Qwen/Qwen2___5-VL-7B-Instruct"
  device: "cuda"
  torch_dtype: "bfloat16"

# 图片预处理
preprocessing:
  max_pixels: 1920000

# 生成参数
generation:
  max_new_tokens: 512
  temperature: 0.7
  top_p: 0.9

# Prompt 模板
prompt:
  zh: "请仔细观察这张图片..."

# Triage 配置
triage:
  enabled: true
  model_path: "/data/models/nsfw-classifier"
  thresholds:
    nsfw: 0.5
    text_heavy: 0.15

# 专家模型配置
experts:
  nsfw:
    enabled: true
    ensemble_mode: "serial"
    minicpm_path: "/data/models/minicpm-v-4.5-abliterated-int8"
    nsfw_v3_path: "/data/models/qwen2.5-vl-7b-nsfw-caption-v3"
    
  gore:
    enabled: true
    model_path: "/data/models/qwen2.5-vl-abliterated"
    quantize_4bit: true
    
  doc:
    enabled: true
    model_dir: "/data/models/pixtral-12b-gguf"
    model_file: "Pixtral-12B-2409-Q5_K_M.gguf"
    n_gpu_layers: -1
```

### 10.2 configs/router.yaml 结构

```yaml
# PaddleOCR 配置
models:
  paddleocr:
    det_model_dir: "/data/models/paddleocr/det"
    rec_model_dir: "/data/models/paddleocr/rec"
    cls_model_dir: "/data/models/paddleocr/cls"
    lang: "ch"
    use_gpu: true

# 路由阈值
routing:
  text_heavy_threshold: 0.15
  gray_detection: true
```

---

## 11. 运行命令

```bash
# 激活环境
conda activate wechatDHA

# 运行完整图片流水线
python run_all_pipelines.py --only image

# 或分步运行
python scripts/image/run_all/_01_run_ocr.py              # OCR + 路由
python scripts/image/run_all/_02_run_caption.py          # 描述生成
python scripts/image/run_all/_03_merge_engine.py         # 合并引擎
python scripts/image/run_all/_04_update_timeline.py      # 时间轴更新

# 测试模式
python scripts/image/run_all/_02_run_caption.py --sample 10  # 仅处理前 10 张
```

---

## 12. 目录结构

```
scripts/image/
├── loader.py                    # 图片加载器
├── router.py                    # ImageRouter 路由器
├── experts/
│   ├── expert_router.py         # 专家路由器
│   ├── image_triage.py          # Triage 分类器
│   ├── nsfw_expert.py           # NSFW 专家
│   ├── gore_expert.py           # Gore 专家
│   ├── caption_expert.py        # 普通图片专家
│   └── doc_expert.py            # 文档专家
└── run_all/
    ├── _01_run_ocr.py           # OCR 处理
    ├── _02_run_caption.py       # 描述生成
    ├── _03_merge_engine.py      # 合并引擎
    └── _04_update_timeline.py   # 时间轴更新

artifacts/before_merge/image/
├── image_ocr_v1.jsonl           # OCR 结果
├── image_qc_v1.jsonl            # QC 报告
└── image_caption_v1.jsonl       # 描述结果

artifacts/after_merge/image/
└── image_merged_final.jsonl     # 最终合并结果

configs/
├── caption.yaml                 # Caption 配置
├── router.yaml                  # Router 配置
└── media_filter.yaml            # 媒体过滤配置
```

---

## 13. 与其他模态的对比

| 特性 | **Image** | Voice | Video | Sticker | Linkfile |
|------|-----------|-------|-------|---------|----------|
| 需要 GPU | ✅ | ✅ | ✅ | ✅ | ❌ |
| 流水线步骤 | **4** | 4 | 5 | 8 | 3 |
| 原始 Token | **300-800** | 100-400 | 1500-2500 | 50-200 | 20-200 |
| 压缩后 Token | **80-150** | 50-100 | 150-250 | 30-60 | 15-100 |
| Triage 分类 | ✅ | ❌ | ✅ (复用) | ✅ | ❌ |
| 专家路由 | ✅ (4种) | ❌ | ✅ (复用) | ❌ | ❌ |
| OCR 处理 | ✅ | ❌ | ❌ | ✅ | ❌ |
| 媒体过滤 | ✅ (4层) | ✅ | ✅ | ✅ | ❌ |

---

## 14. 设计亮点

1. **智能路由系统**：ImageRouter 根据图片特征自动决定处理策略，避免不必要的计算

2. **专家模型架构**：不同内容类型使用专用模型，提高准确性和安全性

3. **双模型 Ensemble**：NSFW 专家使用两个模型互补，提高描述质量

4. **OCR 检测框复用**：复用 Router 的检测框，节省 30-40% 处理时间

5. **四层级媒体过滤**：跳过低质量图片，节省 GPU 资源

6. **显存安全管理**：串行加载 + 定期清理，适配 16GB 显卡

7. **Abliterated 模型**：使用无审查版本处理敏感内容，避免模型拒绝

---

## 15. 常见问题

### Q1: 为什么有些图片被跳过？

**A**: 图片被跳过可能是因为：
- FilterTier 为 SKIP（尺寸 < 50px 或 文件 < 1KB）
- 加载失败（文件损坏或格式不支持）
- 路由类别为 PHOTO 且不需要 OCR

### Q2: NSFW 图片描述不够详细？

**A**: 尝试以下方法：
1. 在 `configs/caption.yaml` 中将 `ensemble_mode` 改为 `fusion`
2. 检查 MiniCPM resampler 反量化修复是否生效
3. 调低 `temperature` 参数

### Q3: 显存不足怎么办？

**A**: 
1. 减少 `preprocessing.max_pixels` 值
2. 增加 `CLEANUP_INTERVAL` 频率
3. 使用更激进的量化（如 4-bit）

### Q4: OCR 识别不准确？

**A**: 
1. 检查图片质量（FilterTier 是否为 LITE）
2. 调整 PaddleOCR 的置信度阈值
3. 对于特殊字体，考虑使用专用 OCR 模型

### Q5: 如何跳过 Triage 分类？

**A**: 目前不支持跳过 Triage，因为专家路由依赖 Triage 结果。如果需要强制使用某个专家，可以修改 `expert_router.py` 中的路由逻辑。

---

## 16. 视频流水线复用

视频流水线（`scripts/video/`）复用了图片流水线的以下组件：

| 组件 | 复用方式 |
|------|----------|
| ImageTriage | 直接导入，对每个关键帧进行分类 |
| 专家模型 | 复用 NSFWExpert、GoreExpert、CaptionExpert |
| 显存管理 | 复用串行加载策略 |

```python
# 视频流水线中复用图片 Triage
from scripts.image.experts.image_triage import ImageTriage

triage = ImageTriage()
for frame_path in keyframes:
    result = triage.classify(frame_path)
    # result.content_type: TYPE_A_NSFW / TYPE_B_GORE / TYPE_C_NORMAL / TYPE_D_DOC
```

---

## 17. 压缩策略

### 17.1 压缩目标

图片压缩器将 Caption + OCR 合并为简洁摘要，目标是在保留关键信息的同时大幅减少 Token 消耗：

| 阶段 | Token 估算 | 说明 |
|------|------------|------|
| 原始（Caption + OCR） | 300-800 tokens | VLM 生成的详细描述 |
| 压缩后 | 80-150 tokens | 规则压缩后的摘要 |
| **压缩比** | **4-5x** | 显著减少 Token 消耗 |

### 17.2 场景分类

压缩器首先对图片进行场景分类，决定压缩策略：

| scene_focus | 触发条件 | 压缩策略 |
|-------------|----------|----------|
| **food** | 包含美食关键词 | 保留食材、菜品名称 |
| **person** | 包含人物关键词 | 保留人物特征、表情 |
| **scene** | 包含风景关键词 | 保留场景类型、氛围 |
| **object** | 包含物品关键词 | 保留物品名称、特征 |
| **document** | route_class=TEXT_PRIMARY | 保留文档类型、关键文字 |
| **other** | 默认 | 通用压缩策略 |

### 17.3 TEXT_PRIMARY 图片处理

对于文字为主的图片（截图、文档等），采用特殊压缩策略：

**文档类型识别**：

| 文档类型 | 触发关键词 | 输出格式 |
|----------|------------|----------|
| 聊天截图 | 微信、聊天、消息 | `[聊天截图] 关键内容` |
| 英语学习 | 单词、词汇、雅思 | `[英语学习] 学习内容` |
| 旅游信息 | 携程、景点、门票 | `[旅游信息] 地点信息` |
| 美食分享 | 美食、餐厅、外卖 | `[美食分享] 美食内容` |
| 购物截图 | 淘宝、京东、订单 | `[购物截图] 购物信息` |
| 社交截图 | 朋友圈、微博、抖音 | `[社交截图] 内容摘要` |
| 日常分享 | 默认 | `[日常分享] 内容摘要` |

**情感内容保留**：

对于包含情感表达的截图（如名言、感叹句），会保留核心表达：

```python
# 情感内容检测
emotional_markers = ['开心', '难过', '感动', '哈哈', '呜呜', '！！', '？？']
famous_markers = ['此心光明', '知行合一', '致良知']  # 名言

# 保留引号内的短内容
short_quotes = re.findall(r'[""「」]([^""「」]{2,15})[""「」]', text)
```

### 17.4 VISUAL_PRIMARY 图片处理

对于视觉为主的图片，从 VLM Caption 中提取关键信息：

**提取优先级**：

1. **关键物体部分**：提取 `**关键人物、动作或物体**` 章节的列表项
2. **画面关键物体**：提取 `**画面中的关键物体**` 章节
3. **场景描述**：提取"展示了"、"记录了"等描述
4. **兜底**：清理后的 Caption 首段

**输出格式**：

```
{场景类型}，{关键内容1}，{关键内容2}，...
```

**示例**：

```
输入 Caption:
这张图片是一张美食照片。
1. **图片类型**：美食照片
2. **关键物体**：
   - 一盘红烧肉，色泽红亮
   - 配菜有青菜和萝卜
3. **氛围**：温馨的家庭聚餐

输出 Summary:
美食照片，一盘红烧肉色泽红亮，配菜有青菜和萝卜
```

### 17.5 OCR 文字处理

根据 route_class 决定 OCR 文字的处理方式：

| route_class | OCR 处理 | 说明 |
|-------------|----------|------|
| TEXT_PRIMARY | 完整保留 | 文字是主要内容 |
| HYBRID_TEXT_MAIN | 保留前 50% | 文字较重要 |
| VISUAL_PRIMARY | 简短摘要 | 仅作为补充 |
| VISUAL_ONLY | 忽略 | 无文字 |

### 17.6 敏感内容处理

敏感内容图片会保留标签前缀：

```python
if content_type in ['TYPE_A_NSFW', 'TYPE_B_GORE']:
    image_summary = f"[{content_type}] {image_summary}"
```

### 17.7 输出字段

```json
{
  "msg_uid": "P1:1234567890",
  "schema_version": "image_compressed_v1",
  "image_summary": "美食照片，红烧肉色泽红亮，配菜青菜萝卜",
  "content_type": "TYPE_C_NORMAL",
  "route_class": "VISUAL_PRIMARY",
  "scene_focus": "food",
  "emotion_atmosphere": "温馨",
  "intent": "分享日常",
  "compression_ratio": 4.5,
  "original_length": 450,
  "compressed_length": 100
}
```

### 17.8 压缩效果示例

| 原始内容 | 压缩后 | 压缩比 |
|----------|--------|--------|
| 500字 VLM Caption + 100字 OCR | 80字 Summary | 7.5x |
| 300字 Caption（无 OCR） | 60字 Summary | 5x |
| 200字 OCR（TEXT_PRIMARY） | 50字 Summary | 4x |

---

**文档版本**: v1.0  
**创建时间**: 2026-02-05  
**作者**: [Author]
