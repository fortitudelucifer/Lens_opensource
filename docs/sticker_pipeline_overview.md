# 表情包流水线设计概览

> 📌 **本文档定位**：这是 [多模态处理流水线文档](modality_fields_and_models.md) 的详细设计文档，专注于表情包流水线的格式检测、动图处理、Contact Sheet 生成和 Triage 分类策略。

## 1. 设计理念

### 1.1 核心目标

表情包流水线处理CHAT_APP聊天记录中的表情包消息（`type=47`），是所有模态中步骤最多的处理流程：

| 挑战 | 解决方案 |
|------|----------|
| 格式多样（GIF/WebP/PNG/JPEG） | Magic Bytes 检测 |
| 动图帧数差异大（1-3000帧） | 自适应采样策略 |
| 敏感内容检测 | 逐帧 Triage + 最高分 |
| 动图理解困难 | Contact Sheet 拼接 |
| 文件来源不可靠 | Pillow 解码验证 |

### 1.2 设计原则

```
┌─────────────────────────────────────────────────────────────────┐
│                      设计原则                                    │
├─────────────────────────────────────────────────────────────────┤
│  1. 格式嗅探：Magic Bytes 检测，不信任 Content-Type             │
│  2. 解码验证：Pillow 验证文件完整性，防止损坏文件               │
│  3. 自适应采样：根据帧数动态调整采样数（4-16帧）                │
│  4. Contact Sheet：多帧拼接为单图，便于 VLM 理解                │
│  5. 逐帧 Triage：动图逐帧检测，取最高分判断敏感性               │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. 八阶段流水线架构

### 2.1 整体流程图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          Sticker Pipeline                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐     │
│   │  Step 1  │  │  Step 2  │  │  Step 3  │  │  Step 4  │  │  Step 5  │     │
│   │ Download │─▶│  Sniff   │─▶│ Process  │─▶│ Triage   │─▶│ Caption  │     │
│   │  下载    │  │ 格式嗅探 │  │ 帧处理   │  │ 敏感检测 │  │ 描述生成 │     │
│   └──────────┘  └──────────┘  └──────────┘  └──────────┘  └──────────┘     │
│        │             │             │             │             │            │
│        ▼             ▼             ▼             ▼             ▼            │
│   download_v1   sniff_v1      meta_v1       triage_v1    caption_v1        │
│                 decode_qc     frames_v1                                     │
│                                                                              │
│   ┌──────────┐  ┌──────────┐  ┌──────────┐                                 │
│   │  Step 6  │  │  Step 7  │  │  Step 8  │                                 │
│   │  Merge   │─▶│ Timeline │─▶│ Cleanup  │                                 │
│   │ 合并引擎 │  │ 时间轴   │  │ 清理帧   │                                 │
│   └──────────┘  └──────────┘  └──────────┘                                 │
│        │             │             │                                        │
│        ▼             ▼             ▼                                        │
│   merged_final  enriched_full  删除临时帧                                   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 各阶段详解

| 阶段 | 脚本 | 输入 | 输出 | 说明 |
|------|------|------|------|------|
| **Download** | `_01_run_download.py` | 表情包 URL | 原始文件 | 下载表情包文件 |
| **Sniff** | `_02_run_sniff.py` | 原始文件 | 格式信息 | Magic Bytes 检测 |
| **Process** | `_03_run_process.py` | 格式信息 | 缩略图 + 关键帧 | 动图处理 |
| **Triage** | `_04_run_triage.py` | 关键帧 | 敏感分类 | NSFW/Gore 检测 |
| **Caption** | `_05_run_caption.py` | Contact Sheet | 描述文本 | VLM 描述生成 |
| **Compress** | `_05.5_run_compress.py` | 描述文本 | 压缩描述 | 语义压缩 |
| **Merge** | `_06_merge_engine.py` | 各阶段输出 | 合并结果 | 数据合并 |
| **Timeline** | `_07_update_timeline.py` | 合并结果 | 时间轴 | 更新时间轴 |
| **Cleanup** | `_08_cleanup_frames.py` | 临时帧 | - | 清理临时文件 |

---

## 3. 格式嗅探（Step 2）

### 3.1 Magic Bytes 检测

不信任 HTTP Content-Type，使用 Magic Bytes 检测真实格式：

| 格式 | Magic Bytes | 字节数 | 说明 |
|------|-------------|--------|------|
| **GIF** | `GIF87a` 或 `GIF89a` | 6 | GIF 动图/静图 |
| **WebP** | `RIFF` + 4字节 + `WEBP` | 12 | WebP 动图/静图 |
| **PNG** | `\x89PNG\r\n\x1a\n` | 8 | PNG 静图 |
| **JPEG** | `\xff\xd8` | 2 | JPEG 静图 |
| **Unknown** | - | - | 无法识别，保存为 .bin |

### 3.2 Pillow 解码验证

使用 Pillow 验证文件完整性：

```python
def validate_with_pillow(filepath):
    with Image.open(filepath) as img:
        img.verify()  # 验证完整性（不加载像素）
    
    # 重新打开获取尺寸
    with Image.open(filepath) as img:
        return {
            "decode_ok": True,
            "width": img.width,
            "height": img.height,
            "megapixels": img.width * img.height / 1_000_000
        }
```

### 3.3 Content-Type 不匹配检测

比较 Magic Bytes 检测结果与 HTTP Content-Type：

```
Content-Type: image/jpeg
Magic Bytes: GIF89a
→ mismatch: True（实际是 GIF，不是 JPEG）
```

---

## 4. 动图处理（Step 3）

### 4.1 动图/静图分类

根据帧数分类表情包类型：

| 类型 | 条件 | 说明 |
|------|------|------|
| **sticker_animated** | 帧数 > 1 | 动态表情包 |
| **sticker_static** | 帧数 = 1 | 静态表情包 |
| **sticker_unknown** | 无法识别 | 未知类型 |

### 4.2 媒体质量过滤

区分静态和动态表情包的过滤规则：

| FilterTier | 静态条件 | 动态条件 | 处理方式 |
|------------|----------|----------|----------|
| **SKIP** | 尺寸 < 32px | 尺寸 < 32px | 完全跳过 |
| **LITE** | 尺寸 < 64px | 尺寸 < 64px 或 帧数 < 4 | 轻量处理 |
| **FULL** | 其他 | 其他 | 完整处理 |

### 4.3 自适应采样策略

根据帧数动态调整采样数：

| 帧数范围 | 采样数 | 说明 |
|----------|--------|------|
| ≤ 12 帧 | 4 帧 | 短动图 |
| 13-30 帧 | 8 帧 | 普通动图 |
| 31-60 帧 | 12 帧 | 长动图 |
| > 60 帧 | 16 帧 | 超长动图 |

**均匀采样算法**：
```python
step = n_frames / n_samples
indices = [int(i * step) for i in range(n_samples)]
```

### 4.4 Contact Sheet 生成

将多帧拼接为单图，便于 VLM 理解动图内容：

| 帧数 | 布局 | 尺寸 |
|------|------|------|
| ≤ 4 帧 | 2×2 | 512×512 |
| 5-8 帧 | 4×2 | 1024×512 |
| 9-12 帧 | 4×3 | 1024×768 |
| > 12 帧 | 4×4 | 1024×1024 |

**Contact Sheet 示例**：
```
┌─────┬─────┬─────┬─────┐
│ F0  │ F1  │ F2  │ F3  │
├─────┼─────┼─────┼─────┤
│ F4  │ F5  │ F6  │ F7  │
└─────┴─────┴─────┴─────┘
```

---

## 5. Triage 敏感检测（Step 4）

### 5.1 检测策略

复用图片流水线的 ImageTriage，根据表情包类型选择检测策略：

| 类型 | 策略 | 说明 |
|------|------|------|
| **静图** | single_frame | 使用缩略图单次检测 |
| **动图** | per_frame_max | 逐帧检测，取最高分 |

### 5.2 动图逐帧检测

```
┌─────────────────────────────────────────────────────────────────┐
│  动图 Triage 流程                                                │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  关键帧列表 [F0, F1, F2, ..., Fn]                               │
│       │                                                          │
│       ▼                                                          │
│  逐帧检测 NSFW/Gore 分数                                        │
│       │                                                          │
│       ├─ F0: nsfw=0.12, gore=0.01                               │
│       ├─ F1: nsfw=0.08, gore=0.02                               │
│       ├─ F2: nsfw=0.65, gore=0.01  ← 触发阈值                   │
│       └─ ...                                                     │
│       │                                                          │
│       ▼                                                          │
│  取最高分：max_nsfw=0.65                                        │
│       │                                                          │
│       ▼                                                          │
│  判断：0.65 > 0.5 → is_sensitive=True                           │
│       │                                                          │
│       ▼                                                          │
│  记录触发帧：trigger_frames=[{frame_seq: 2, nsfw: 0.65}]        │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 5.3 敏感内容判断

| 条件 | content_type | 说明 |
|------|--------------|------|
| max_nsfw > 0.5 | TYPE_A_NSFW | 成人内容 |
| max_gore > 0.5 | TYPE_B_GORE | 暴力血腥 |
| 其他 | TYPE_C_NORMAL | 普通内容 |

---

## 6. 描述生成（Step 5）

### 6.1 输入选择

根据表情包类型选择 VLM 输入：

| 类型 | 输入 | 说明 |
|------|------|------|
| **静图** | 缩略图 | 单张图片 |
| **动图** | Contact Sheet | 多帧拼接图 |

### 6.2 专家路由

复用图片流水线的专家路由系统：

| content_type | 专家 | 说明 |
|--------------|------|------|
| TYPE_A_NSFW | NSFWExpert | 敏感内容专家 |
| TYPE_B_GORE | GoreExpert | 暴力内容专家 |
| TYPE_C_NORMAL | CaptionExpert | 普通内容专家 |

### 6.3 输出格式

```
[表情包: {action} + {text} + 情绪:{emotion}]
```

**示例**：
```
[表情包: 一只猫咪摇头 + "不要" + 情绪:拒绝/无奈]
```

---

## 7. 输出字段

### 7.1 嗅探输出（sticker_sniff_v1.jsonl）

```json
{
  "schema_version": "sticker_sniff_v1",
  "msg_uid": "P1:1234567890",
  "file_sha256": "abc123...",
  "detected_format": "gif",
  "detected_ext": ".gif",
  "sniff_rule": "magic_bytes",
  "content_type_reported": "image/gif",
  "mismatch": false,
  "final_path": "raw/sticker/P1_1234567890_abc123.gif"
}
```

### 7.2 Meta 输出（sticker_meta_v1.jsonl）

```json
{
  "schema_version": "sticker_meta_v1",
  "msg_uid": "P1:1234567890",
  "file_sha256": "abc123...",
  "is_animated": true,
  "n_frames": 24,
  "sticker_class": "sticker_animated",
  "width": 256,
  "height": 256,
  "filter_tier": "full",
  "thumb_path": "artifacts/sticker/thumbs/P1_1234567890_abc123.png",
  "frames_ref": "sticker_frames_v1.jsonl"
}
```

### 7.3 Frames 输出（sticker_frames_v1.jsonl）

```json
{
  "schema_version": "sticker_frames_v1",
  "msg_uid": "P1:1234567890",
  "file_sha256": "abc123...",
  "n_sampled": 8,
  "sample_indices": [0, 3, 6, 9, 12, 15, 18, 21],
  "frame_paths": ["frames/P1_1234567890_abc123_f00.png", ...],
  "contact_sheet_path": "frames/P1_1234567890_abc123_contact.png"
}
```

### 7.4 Triage 输出（sticker_triage_v1.jsonl）

```json
{
  "schema_version": "sticker_triage_v1",
  "msg_uid": "P1:1234567890",
  "triage_method": "per_frame_max",
  "max_nsfw_score": 0.12,
  "max_gore_score": 0.01,
  "is_sensitive": false,
  "trigger_frames": [],
  "content_type": "TYPE_C_NORMAL"
}
```

### 7.5 合并输出（sticker_merged_final.jsonl）

```json
{
  "schema_version": "merged_v2",
  "msg_uid": "P1:1234567890",
  "modality": "sticker",
  "sticker_caption": "[表情包: 猫咪摇头 + 不要 + 情绪:拒绝]",
  "sticker_ocr_text": "不要",
  "sticker_content_type": "TYPE_C_NORMAL",
  "sticker_is_animated": true,
  "sticker_n_frames": 24
}
```

---

## 8. 配置文件详解

### 8.1 configs/sticker.yaml 结构

```yaml
# Schema 版本
schema_version: "sticker_v1"

# 网络配置
networking:
  timeout:
    connect_sec: 10
    read_sec: 30
  retries:
    max: 3
    backoff: exponential
  concurrency: 5

# 格式检测
detection:
  trust_content_type: false
  max_header_bytes: 12
  pillow_max_pixels: 26000000

# 分类配置
classification:
  frame_count_cap: 3000

# 缩略图配置
thumbnail:
  size_px: 256
  format: "PNG"

# 关键帧配置
frame_sampling:
  strategy: "adaptive"
  min_frames: 4
  default_frames: 8
  max_frames: 16
  adaptive_rules:
    short:
      threshold: 12
      sample: 4
    normal:
      threshold: 30
      sample: 8
    long:
      threshold: 60
      sample: 12
    very_long:
      threshold: null
      sample: 16

# Contact Sheet 配置
contact_sheet:
  enabled: true
  layout: "auto"
  cell_size: 256
  max_width: 1024

# Triage 配置
triage:
  enabled: true
  nsfw_threshold: 0.5
  gore_threshold: 0.5
  method: "per_frame_max"

# 描述生成配置
caption:
  enabled: true
  model: "Qwen2.5-VL-7B-AWQ"
  ocr_enabled: true
  output_format: "[表情包: {action} + {text} + 情绪:{emotion}]"
  generation:
    max_new_tokens: 128
    temperature: 0.4
  use_expert_router: true
```

---

## 9. 运行命令

```bash
# 激活环境
conda activate CHAT_APP_DHA

# 运行完整表情包流水线
python run_all_pipelines.py --only sticker

# 或分步运行
python scripts/sticker/run_all/_01_run_download.py       # 下载
python scripts/sticker/run_all/_02_run_sniff.py          # 格式嗅探
python scripts/sticker/run_all/_03_run_process.py        # 帧处理
python scripts/sticker/run_all/_04_run_triage.py         # Triage
python scripts/sticker/run_all/_05_run_caption.py        # 描述生成
python scripts/sticker/run_all/_05.5_run_compress.py     # 语义压缩
python scripts/sticker/run_all/_06_merge_engine.py       # 合并引擎
python scripts/sticker/run_all/_07_update_timeline.py    # 时间轴更新
python scripts/sticker/run_all/_08_cleanup_frames.py     # 清理帧

# 测试模式
python scripts/sticker/run_all/_02_run_sniff.py --sample 10
python scripts/sticker/run_all/_03_run_process.py --skip-frames
```

---

## 10. 目录结构

```
scripts/sticker/
└── run_all/
    ├── _01_run_download.py      # 下载表情包
    ├── _02_run_sniff.py         # 格式嗅探
    ├── _03_run_process.py       # 帧处理
    ├── _04_run_triage.py        # Triage 检测
    ├── _05_run_caption.py       # 描述生成
    ├── _05.5_run_compress.py    # 语义压缩
    ├── _06_merge_engine.py      # 合并引擎
    ├── _07_update_timeline.py   # 时间轴更新
    └── _08_cleanup_frames.py    # 清理帧

artifacts/before_merge/sticker/
├── sticker_download_v1.jsonl    # 下载结果
├── sticker_sniff_v1.jsonl       # 嗅探结果
├── sticker_decode_qc_v1.jsonl   # 解码 QC
├── sticker_meta_v1.jsonl        # Meta 信息
├── sticker_frames_v1.jsonl      # 帧信息
├── sticker_triage_v1.jsonl      # Triage 结果
└── sticker_caption_v1.jsonl     # 描述结果

artifacts/after_merge/sticker/
└── sticker_merged_final.jsonl   # 最终合并结果

artifacts/sticker/
├── thumbs/                      # 缩略图目录
└── frames/                      # 关键帧目录

raw/sticker/
└── {msg_uid}_{sha256[:16]}.{ext}  # 原始表情包文件

configs/
└── sticker.yaml                 # 表情包配置文件
```

---

## 11. 与其他模态的对比

| 特性 | Image | Voice | Video | **Sticker** | Linkfile |
|------|-------|-------|-------|-------------|----------|
| 需要 GPU | ✅ | ✅ | ✅ | ✅ | ❌ |
| 流水线步骤 | 4 | 4 | 5 | **8** | 3 |
| 原始 Token | 300-800 | 100-400 | 1500-2500 | **50-200** | 20-200 |
| 压缩后 Token | 80-150 | 50-100 | 150-250 | **30-60** | 15-100 |
| Triage 分类 | ✅ | ✅ | ✅ | ✅ (逐帧) | ❌ |
| 动图处理 | ❌ | ❌ | ❌ | ✅ | ❌ |
| Contact Sheet | ❌ | ❌ | ❌ | ✅ | ❌ |
| 格式嗅探 | ❌ | ❌ | ❌ | ✅ | ❌ |

---

## 12. 设计亮点

1. **Magic Bytes 检测**：不信任 Content-Type，使用文件头检测真实格式

2. **Pillow 解码验证**：验证文件完整性，防止损坏文件进入流水线

3. **自适应采样策略**：根据帧数动态调整采样数，平衡质量和效率

4. **Contact Sheet 生成**：将多帧拼接为单图，便于 VLM 理解动图内容

5. **逐帧 Triage**：动图逐帧检测敏感内容，取最高分判断整体敏感性

6. **专家路由复用**：复用图片流水线的专家模型，处理敏感内容

7. **八阶段流水线**：完整覆盖下载、检测、处理、分类、描述、合并全流程

---

## 13. 常见问题

### Q1: 为什么有些表情包被跳过？

**A**: 表情包被跳过可能是因为：
- 下载失败（网络问题或 URL 失效）
- 解码失败（文件损坏）
- FilterTier 为 SKIP（尺寸过小）

### Q2: Contact Sheet 为什么有空白格？

**A**: 当采样帧数少于布局格数时，会有空白格。例如 4 帧使用 2×2 布局，刚好填满；但 3 帧使用 2×2 布局会有 1 个空白格。

### Q3: 动图 Triage 为什么比静图慢？

**A**: 动图需要逐帧检测，每帧都要调用 NSFW Classifier。可以通过减少采样帧数来加速。

### Q4: 如何跳过关键帧提取？

**A**: 使用 `--skip-frames` 参数：
```bash
python scripts/sticker/run_all/_03_run_process.py --skip-frames
```

### Q5: 如何清理临时帧文件？

**A**: 运行清理脚本：
```bash
python scripts/sticker/run_all/_08_cleanup_frames.py
```

---

## 14. 压缩策略

### 14.1 压缩目标

表情包压缩器将 Caption 和 OCR 压缩为语用功能/意图标签，支持字典化压缩：

| 阶段 | Token 估算 | 说明 |
|------|------------|------|
| 原始（Caption + OCR） | 50-200 tokens | VLM 生成的描述 |
| 压缩后 | 30-60 tokens | 意图标签 + 文字 |
| **压缩比** | **2-3x** | 适度压缩 |

### 14.2 意图映射

压缩器使用 `configs/sticker_intent_map.yaml` 将表情包描述映射到意图标签：

**高置信度映射**（confidence ≥ 0.8）：

| 意图 | 触发关键词 | 示例 |
|------|------------|------|
| 开心 | 笑、开心、高兴、哈哈 | `[开心]` |
| 难过 | 哭、难过、伤心、流泪 | `[难过]` |
| 生气 | 生气、愤怒、怒、发火 | `[生气]` |
| 无语 | 无语、无奈、翻白眼 | `[无语]` |
| 可爱 | 可爱、萌、卖萌 | `[可爱]` |
| 赞同 | 点头、赞、OK、好的 | `[赞同]` |
| 拒绝 | 摇头、不要、拒绝 | `[拒绝]` |

**中置信度映射**（confidence 0.5-0.8）：

| 意图 | 触发关键词 |
|------|------------|
| 思考 | 思考、想、疑惑 |
| 期待 | 期待、等待、盼望 |
| 害羞 | 害羞、脸红、不好意思 |

**OCR 文字优先映射**：

| OCR 文字 | 意图 | 置信度 |
|----------|------|--------|
| 好的、OK、收到 | 赞同 | 0.9 |
| 不要、拒绝、NO | 拒绝 | 0.9 |
| 谢谢、感谢 | 感谢 | 0.9 |
| 加油、冲 | 鼓励 | 0.85 |

### 14.3 输出格式

**明确意图**（非兜底）：

```
[{意图}]
[{意图}] (文字: {OCR文字})
```

**兜底意图**（"表达情绪"）：

```
[表情包: {压缩后的视觉描述}]
[表情包: {压缩后的视觉描述}] (文字: {OCR文字})
```

### 14.4 Caption 压缩

对于兜底情况，压缩 Caption 保留核心视觉特征：

```python
# 原始 Caption
"[表情包: 绿色青蛙戴着墨镜，露出大笑，显得非常自信和酷炫。]"

# 压缩后
"绿色青蛙戴墨镜大笑"
```

**移除的冗余词汇**：

```python
remove_words = [
    "显得", "非常", "十分", "特别", "似乎", "好像",
    "的样子", "的表情", "的动作", "的姿态",
    "表示", "表达", "传达", "展示",
    "一个", "一只", "一位"
]
```

### 14.5 字典化压缩

对于重复出现的表情包，使用字典引用减少冗余：

**字典构建**：

```json
{
  "sticker_id": "abc123...",
  "sticker_summary": "[开心]",
  "intent": "开心",
  "intent_confidence": 0.85,
  "is_animated": true,
  "occurrence_count": 5
}
```

**引用格式**：

```
[REF:abc12345]
```

**触发条件**：

- 同一表情包出现 ≥ 2 次
- 字典中已有该表情包的摘要

### 14.6 输出字段

```json
{
  "msg_uid": "P1:1234567890",
  "schema_version": "sticker_compressed_v1",
  "sticker_id": "abc123...",
  "sticker_summary": "[开心] (文字: 哈哈)",
  "is_animated": true,
  "intent": "开心",
  "intent_confidence": 0.85,
  "compression_ratio": 3.2,
  "original_length": 150,
  "compressed_length": 47
}
```

### 14.7 压缩效果示例

| 场景 | 原始 | 压缩后 | 压缩比 |
|------|------|--------|--------|
| 明确意图 | 150字 Caption | `[开心]` | 15x |
| 明确意图+OCR | 150字 Caption + 10字 OCR | `[开心] (文字: 哈哈)` | 8x |
| 兜底意图 | 150字 Caption | `[表情包: 青蛙戴墨镜大笑]` | 5x |
| 字典引用 | 150字 Caption | `[REF:abc12345]` | 10x |

### 14.8 意图映射配置

意图映射配置位于 `configs/sticker_intent_map.yaml`：

```yaml
high_confidence:
  happy:
    keywords: ["笑", "开心", "高兴", "哈哈", "嘻嘻"]
    intent: "开心"
    confidence: 0.85
  sad:
    keywords: ["哭", "难过", "伤心", "流泪", "呜呜"]
    intent: "难过"
    confidence: 0.85
  # ...

ocr_text_mapping:
  - patterns: ["好的", "OK", "收到", "了解"]
    intent: "赞同"
    confidence: 0.9
  - patterns: ["不要", "拒绝", "NO", "不行"]
    intent: "拒绝"
    confidence: 0.9
  # ...

fallback:
  default_intent: "表达情绪"
  default_confidence: 0.3
```

---

**文档版本**: v1.0  
**创建时间**: 2026-02-05  
**作者**: forcifer
