# 视频流水线设计概览

> 📌 **本文档定位**：这是 [多模态处理流水线文档](modality_fields_and_models.md) 的详细设计文档，专注于视频流水线的智能关键帧提取、专家路由、Fallback 机制和压缩策略。

## 1. 设计理念

### 1.1 核心目标

视频流水线处理微信聊天记录中的视频消息（`type=43`），是所有模态中最复杂的处理流程：

| 挑战 | 解决方案 |
|------|----------|
| 视频时长差异大（1s-10min） | 自适应帧数计算 |
| 内容类型多样（动物/人物/录屏） | Triage 分类 + 专家路由 |
| 运动检测困难（相机抖动 vs 真实运动） | 光流算法 + 场景变化感知 |
| 模型拒绝回答敏感内容 | LLaVA-NeXT-Video Fallback |
| Token 消耗巨大（1500-2500 tokens） | 多阶段压缩策略 |

### 1.2 设计原则

```
┌─────────────────────────────────────────────────────────────────┐
│                      设计原则                                    │
├─────────────────────────────────────────────────────────────────┤
│  1. 智能采样：根据运动强度和场景变化自适应调整帧数              │
│  2. 专家路由：复用图片流水线的 Triage + 专家模型                │
│  3. 双模式理解：直接视频输入 + 多帧图片回退                     │
│  4. 智能 Fallback：主模型失败时自动切换到 LLaVA                 │
│  5. 显存安全：16GB 约束下的串行加载策略                         │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. 五阶段流水线架构

### 2.1 整体流程图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          Video Pipeline                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐ │
│   │   Step 1     │   │   Step 2     │   │   Step 3     │   │   Step 3.5   │ │
│   │   Extract    │──▶│  Transcribe  │──▶│   Caption    │──▶│   Compress   │ │
│   │  关键帧提取  │   │  音频转写    │   │  描述生成    │   │  语义压缩    │ │
│   └──────────────┘   └──────────────┘   └──────────────┘   └──────────────┘ │
│          │                  │                  │                  │         │
│          ▼                  ▼                  ▼                  ▼         │
│   video_extract      video_transcribe   video_caption      video_compressed │
│   _v1.jsonl          _v1.jsonl          _v1.jsonl          .jsonl           │
│                                                                              │
│   ┌──────────────┐   ┌──────────────┐                                       │
│   │   Step 4     │   │   Step 5     │                                       │
│   │    Merge     │──▶│   Timeline   │                                       │
│   │   合并引擎   │   │  时间轴更新  │                                       │
│   └──────────────┘   └──────────────┘                                       │
│          │                  │                                               │
│          ▼                  ▼                                               │
│   video_merged       enriched_full.jsonl                                    │
│   _final.jsonl       enriched_slim.jsonl                                    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 各阶段详解

| 阶段 | 脚本 | 输入 | 输出 | 模型 |
|------|------|------|------|------|
| **Extract** | `_01_run_extract.py` | raw/video/*.mp4 | 关键帧 + 音频 | ffmpeg + OpenCV |
| **Transcribe** | `_02_run_transcribe.py` | 音频文件 | 转写 + 情绪 | FunASR + SenseVoice |
| **Caption** | `_03_run_caption.py` | 关键帧 + 视频 | 帧描述 + 视频理解 | Qwen2.5-VL + LLaVA |
| **Compress** | `_03.5_run_compress.py` | 多帧描述 | 压缩摘要 | Qwen2.5-7B |
| **Merge** | `_04_merge_engine.py` | 各阶段输出 | 合并结果 | - |
| **Timeline** | `_05_update_timeline.py` | 合并结果 | 时间轴 | - |

---

## 3. 智能关键帧提取（Step 1）

### 3.1 媒体质量过滤

在提取关键帧之前，先进行媒体质量过滤：

| FilterTier | 条件 | 处理方式 |
|------------|------|----------|
| **SKIP** | 时长 < 1s 或 文件 < 10KB | 跳过处理 |
| **SINGLE_FRAME** | 时长 < 3s | 仅提取首帧 |
| **LITE** | 分辨率 < 360p 或 时长 < 5s | 轻量处理（4帧） |
| **FULL** | 其他 | 完整处理 |

### 3.2 运动检测算法

使用 Farneback 光流算法检测视频中的运动：

```python
# 光流检测核心逻辑
def compute_motion_score(frame1, frame2):
    # 1. 转灰度 + 缩放（加速计算）
    img1 = cv2.resize(cv2.cvtColor(frame1, cv2.COLOR_BGR2GRAY), scale=0.5)
    img2 = cv2.resize(cv2.cvtColor(frame2, cv2.COLOR_BGR2GRAY), scale=0.5)
    
    # 2. 计算稠密光流 (Farneback)
    flow = cv2.calcOpticalFlowFarneback(img1, img2, ...)
    
    # 3. 计算光流幅度
    mag, _ = cv2.cartToPolar(flow[..., 0], flow[..., 1])
    
    # 4. 归一化运动分数 (0-1)
    motion_score = np.mean(mag) / diagonal * 10
    return min(1.0, motion_score)
```

### 3.3 场景变化感知

区分"真实场景变化"和"相机抖动/小幅运动"：

```
高运动 + 高场景变化 = 真实场景切换（如 vlog 多场景）
高运动 + 低场景变化 = 静态场景运动（如婚礼视频相机抖动）
低运动 + 低场景变化 = 静态视频（如风景延时）
```

**静态场景运动**的特殊处理：
- 不增加帧数（避免冗余）
- 使用更大的采样间隔
- 帧数上限使用普通值而非高动态值

### 3.4 自适应帧数计算

`calculate_adaptive_max_frames()` 函数整合了四种策略：

| 策略 | 说明 |
|------|------|
| **方案A: 动态帧数上限** | 根据运动强度调整 max_frames |
| **方案B: 分段自适应** | 返回建议的采样间隔 |
| **方案C: 内容类型检测** | 高动态内容特殊处理 |
| **方案D: 场景变化感知** | 区分真实场景变化和相机抖动 |

**内容类型分类**：

| content_type | 运动强度 | 场景变化 | 帧数上限 | 采样间隔 |
|--------------|----------|----------|----------|----------|
| `high_motion` | ≥ 0.15 | 高 | 16-20 | 0.5s |
| `medium_motion` | 0.08-0.15 | - | 10-14 | 0.7s |
| `static_scene_motion` | ≥ 0.15 | 低 | 12 | 1.2s |
| `low_motion` | < 0.08 | - | 8-12 | 1.0s |

### 3.5 关键帧提取流程

```
┌─────────────────────────────────────────────────────────────────┐
│                    关键帧提取流程                                │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. 场景检测 (mpdecimate + scene filter)                        │
│     └─ 提取全局画面变化帧                                       │
│                                                                  │
│  2. 光流运动帧检测                                              │
│     └─ 检测局部运动（如猫头摆动、手势）                         │
│                                                                  │
│  3. 均匀采样（保底）                                            │
│     └─ 确保有足够帧捕捉动态                                     │
│                                                                  │
│  4. 强制首尾帧                                                  │
│     └─ 始终保留第一帧和最后一帧                                 │
│                                                                  │
│  5. 合并去重                                                    │
│     └─ 按时间戳排序，过滤间隔过近的帧                           │
│                                                                  │
│  6. 硬上限截断                                                  │
│     └─ 确保不超过 VRAM 安全限制 (16帧)                          │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 3.6 输出字段

```json
{
  "schema_version": "video_v1",
  "file": "video_2025-07-01_001.mp4",
  "video_sha256": "abc123...",
  "metadata": {
    "duration_sec": 15.5,
    "width": 1920,
    "height": 1080,
    "fps": 30,
    "has_audio": true
  },
  "keyframes": [
    {
      "frame_id": 0,
      "timestamp_sec": 0.0,
      "frame_path": "/data/cache/video_keyframes/xxx/xxx_0000.jpg",
      "scene_score": 0.0,
      "is_forced": true,
      "source": "first"
    }
  ],
  "audio_path": "/data/cache/video_audio/xxx.wav",
  "extraction_params": {
    "motion_intensity": 0.23,
    "content_type": "high_motion",
    "max_frames": 14,
    "scene_change_count": 5
  },
  "filter_tier": "FULL"
}
```

---

## 4. 音频转写与情绪检测（Step 2）

### 4.1 处理流程

```
音频文件 (.wav)
     │
     ├──▶ FunASR (paraformer-zh) ──▶ punct_text (带标点转写)
     │
     └──▶ SenseVoice Small ──▶ emotion_tags + event_tags
                │
                ▼
          触发深度分析？
                │
         ┌──────┴──────┐
         │ 是          │ 否
         ▼             ▼
    Qwen2-Audio    直接输出
    深度情绪分析
```

### 4.2 深度分析触发条件

满足任一条件时触发 Qwen2-Audio 深度分析：

- 情绪标签包含：SAD、ANGRY、HAPPY
- 事件标签包含：Cry、Laughter
- 转写文本包含关键词（见 `configs/voice.yaml`）

### 4.3 情绪上下文融合

转写结果会注入到 VLM prompt 中，帮助模型理解视频的情感氛围：

```yaml
# configs/video.yaml
fusion:
  inject_emotion_to_prompt: true
  emotion_prompt_template: |
    【音频情绪信息】
    - 情绪标签: {emotion_tags}
    - 事件标签: {event_tags}
    - 转写文本: {transcript}
    
    【分析要点】
    1. 描述视频中的视觉内容
    2. 注意分析说话人的言行是否一致
    3. 如果音频情绪与视觉内容有冲突，请特别指出
```

---

## 5. Triage 分类与专家路由（Step 3）

### 5.1 复用图片流水线

视频的每个关键帧都会经过 `ImageTriage` 分类，复用图片流水线的 Triage 逻辑：

```python
from scripts.image.experts.image_triage import ImageTriage

triage = ImageTriage()
result = triage.classify(frame_path)
# result.content_type: TYPE_A_NSFW / TYPE_B_GORE / TYPE_C_NORMAL / TYPE_D_DOC
```

### 5.2 专家路由表

| content_type | 专家模块 | 模型组合 | 特殊处理 |
|--------------|----------|----------|----------|
| **TYPE_C_NORMAL** | CaptionExpert | Qwen2.5-VL-7B (4-bit) | 普通视频描述 |
| **TYPE_A_NSFW** | NSFWExpert | MiniCPM-V 4.5 + nsfw-v3 Ensemble | 复用图片流水线 |
| **TYPE_B_GORE** | GoreExpert | Qwen2.5-VL-abliterated + ⚠️ 标记 | 添加警告标记 |
| **TYPE_D_DOC** | DocExpert | Qwen2.5-VL + 高分辨率 | 1024px 分辨率 |

### 5.3 整体 Triage 结果

基于所有关键帧投票，优先级：NSFW > Gore > Doc > Normal

```python
content_types = [t.content_type for t in frame_triage_results]
if 'TYPE_A_NSFW' in content_types:
    overall_type = 'TYPE_A_NSFW'
elif 'TYPE_B_GORE' in content_types:
    overall_type = 'TYPE_B_GORE'
elif 'TYPE_D_DOC' in content_types:
    overall_type = 'TYPE_D_DOC'
else:
    overall_type = 'TYPE_C_NORMAL'
```

---

## 6. 视频理解双模式

### 6.1 主模式：直接视频输入

Qwen2.5-VL 原生支持视频输入，能理解时间序列和动态变化：

```python
from qwen_vl_utils import process_vision_info

messages = [
    {
        "role": "user",
        "content": [
            {"type": "video", "video": video_path, "max_pixels": 360*420, "fps": 1.0},
            {"type": "text", "text": prompt}
        ]
    }
]
```

**优点**：
- 模型能理解时间序列
- 适合动物运动、人物动作、场景转换

### 6.2 回退模式：多帧图片输入

当直接视频输入失败时，回退到多帧图片模式：

```python
content = []
for i, img in enumerate(images):
    content.append({"type": "image", "image": img})
    content.append({"type": "text", "text": f"[帧{i+1}]"})
content.append({"type": "text", "text": prompt})
```

**触发条件**：
- `qwen_vl_utils` 库不可用
- 视频文件读取失败
- 直接视频模式抛出异常

---

## 7. LLaVA-NeXT-Video Fallback 机制

### 7.1 触发条件

在 `configs/video.yaml` 中配置：

```yaml
fallback_vlm:
  name: LLaVA-NeXT-Video-7B
  path: /data/models/llava-next-video-7b
  uniform_frames: 32
  trigger_conditions:
    - output_quality_low      # 输出过短 (< 50 字符)
    - repeated_refusal        # 模型拒绝回答
    - critical_fields_missing # 关键字段缺失
```

### 7.2 Fallback 流程

```
主模型输出
     │
     ▼
检测触发条件
     │
     ├──▶ 未触发 ──▶ 使用主模型结果
     │
     └──▶ 触发 ──▶ 卸载主模型
                      │
                      ▼
                 加载 LLaVA-NeXT-Video
                      │
                      ▼
                 PyAV 均匀采样 32 帧
                      │
                      ▼
                 生成视频理解
                      │
                      ▼
                 卸载 LLaVA 模型
```

### 7.3 拒绝关键词检测

```python
refusal_keywords = [
    '无法', '不能', '无法描述', '不适合', '请勿',
    'cannot', 'unable', 'sorry', 'I cannot'
]
```

---

## 8. 压缩策略（Step 3.5）

### 8.1 压缩模式

根据关键帧数量选择不同的压缩策略：

| 帧数 | 压缩模式 | 说明 |
|------|----------|------|
| ≤ 5 帧 | `sequential` | 逐帧描述，保留时间顺序 |
| 6-10 帧 | `segmented` | 分段：开始/过程/结束 |
| 11-16 帧 | `key_changes` | 只保留关键变化帧 |

### 8.2 压缩效果

| 阶段 | Token 估算 | 说明 |
|------|------------|------|
| 原始（关键帧描述） | 1500-2500 tokens | 4-16帧 × 200-400字/帧 |
| 压缩后 | 150-250 tokens | LLM 合并为视频摘要 |
| **压缩比** | **10x** | 🔥🔥🔥 最高优先级 |

### 8.3 压缩 Prompt

```
你是一个视频内容压缩专家。以下是视频的关键帧描述序列：

{keyframe_captions}

请将这些描述合并为一段简洁的视频摘要（100-150字），要求：
1. 保留关键事件和时间顺序
2. 突出主体的动作变化
3. 保留情绪和氛围信息
4. 删除重复和冗余描述
```

---

## 9. 配置文件详解

### 9.1 configs/video.yaml 结构

```yaml
# Schema 版本
schema_version: video_v1

# 关键帧提取配置
keyframe_extraction:
  scene_threshold: 0.4           # 场景变化阈值
  motion_detection:
    enabled: true
    threshold: 0.08              # 运动检测阈值
    sample_interval: 0.3         # 采样间隔
    high_motion_threshold: 0.15  # 高动态判定阈值
  min_interval_sec: 1.0          # 最小帧间隔
  max_frames: 16                 # 普通模式上限
  max_frames_high_motion: 20     # 高动态上限
  min_frames: 6                  # 最小帧数
  vram_safe_max_frames: 16       # VRAM 安全限制

# 模型配置
models:
  primary_vlm:
    name: Qwen2.5-VL-7B-Instruct
    path: /data/models/qwen2.5-vl-7b/...
    precision: bfloat16
    generation:
      max_new_tokens: 512
      temperature: 0.6
  fallback_vlm:
    name: LLaVA-NeXT-Video-7B
    path: /data/models/llava-next-video-7b
    uniform_frames: 32
    trigger_conditions:
      - output_quality_low
      - repeated_refusal

# Triage 配置
triage:
  nsfw_threshold: 0.5
  gore_threshold: 0.5
  doc_text_ratio: 0.15

# 情绪融合配置
fusion:
  inject_emotion_to_prompt: true
  emotion_prompt_template: |
    【音频情绪信息】
    - 情绪标签: {emotion_tags}
    ...

# VRAM 管理
vram:
  budget_gb: 16
  serial_loading: true
  oom_fallback:
    reduce_max_frames: [8, 6, 4]
```

---

## 10. 运行命令

```bash
# 激活环境
conda activate wechatDHA

# 运行完整视频流水线
python run_all_pipelines.py --only video

# 或分步运行
python scripts/video/run_all/_01_run_extract.py              # 关键帧提取
python scripts/video/run_all/_02_run_transcribe.py           # 音频转写
python scripts/video/run_all/_03_run_caption.py              # 描述生成
python scripts/video/run_all/_03.5_run_compress.py           # 语义压缩
python scripts/video/run_all/_04_merge_engine.py             # 合并引擎
python scripts/video/run_all/_05_update_timeline.py          # 时间轴更新

# 测试模式
python scripts/video/run_all/_01_run_extract.py --test-dir --sample 3
python scripts/video/run_all/_03_run_caption.py --skip-triage  # 跳过 Triage

# 敏感模式（帧数 +50%）
python scripts/video/run_all/_01_run_extract.py --sensitive-first
```

---

## 11. 目录结构

```
scripts/video/
└── run_all/
    ├── _01_run_extract.py       # 关键帧提取 + 运动检测
    ├── _02_run_transcribe.py    # 音频转写 + 情绪检测
    ├── _03_run_caption.py       # Triage + 专家路由 + Fallback
    ├── _03.5_run_compress.py    # 多帧描述压缩
    ├── _04_merge_engine.py      # 合并引擎
    └── _05_update_timeline.py   # 时间轴更新

artifacts/before_merge/video/
├── video_extract_v1.jsonl       # 元数据 + 关键帧路径
├── video_transcribe_v1.jsonl    # 转写 + 情绪
├── video_triage_v1.jsonl        # Triage 分类结果
├── video_caption_v1.jsonl       # 帧描述 + 视频理解
└── video_compressed.jsonl       # 压缩后的描述

artifacts/after_merge/video/
└── video_merged_final.jsonl     # 最终合并结果

/data/cache/
├── video_keyframes/{msg_uid}/   # 关键帧图片缓存
└── video_audio/{msg_uid}.wav    # 音频文件缓存

configs/
└── video.yaml                   # 视频配置文件
```

---

## 12. 与其他模态的对比

| 特性 | Image | Voice | **Video** | Sticker | Linkfile |
|------|-------|-------|-----------|---------|----------|
| 需要 GPU | ✅ | ✅ | ✅ | ✅ | ❌ |
| 流水线步骤 | 4 | 4 | **5** | 8 | 3 |
| 原始 Token | 300-800 | 100-400 | **1500-2500** 🔥 | 50-200 | 20-200 |
| 压缩后 Token | 80-150 | 50-100 | **150-250** | 30-60 | 15-100 |
| 压缩比 | 5x | 3x | **10x** 🔥🔥🔥 | 3x | 2x |
| Triage 分类 | ✅ | ❌ | ✅ (复用图片) | ✅ | ❌ |
| 专家路由 | ✅ | ❌ | ✅ (复用图片) | ❌ | ❌ |
| Fallback 机制 | ✅ | ❌ | ✅ (LLaVA) | ❌ | ❌ |
| 运动检测 | ❌ | ❌ | ✅ (光流) | ❌ | ❌ |

---

## 13. 设计亮点

1. **智能关键帧提取**：整合场景检测、光流运动、均匀采样三种策略，自适应调整帧数

2. **场景变化感知**：区分"真实场景变化"和"相机抖动"，避免冗余帧

3. **专家路由复用**：复用图片流水线的 Triage + 专家模型，代码复用率高

4. **双模式视频理解**：直接视频输入 + 多帧图片回退，兼容性强

5. **智能 Fallback**：主模型失败时自动切换到 LLaVA-NeXT-Video，提高成功率

6. **显存安全**：16GB 约束下的串行加载策略，OOM 时自动降级

7. **情绪上下文融合**：音频情绪注入到 VLM prompt，提升理解准确性

---

## 14. 常见问题

### Q1: 为什么有些视频只提取了首帧？

**A**: 视频时长 < 3s 时，FilterTier 为 SINGLE_FRAME，只提取首帧以节省资源。

### Q2: 运动检测为什么有时不准确？

**A**: 光流算法对相机抖动敏感。我们通过"场景变化感知"来区分真实运动和相机抖动，但仍可能有误判。可以调整 `motion_detection.threshold` 参数。

### Q3: LLaVA Fallback 什么时候触发？

**A**: 当主模型输出过短（< 50 字符）、拒绝回答（包含"无法"等关键词）、或关键字段缺失时触发。

### Q4: 如何跳过 Triage 分类？

**A**: 使用 `--skip-triage` 参数：
```bash
python scripts/video/run_all/_03_run_caption.py --skip-triage
```

### Q5: 显存不足怎么办？

**A**: 配置文件中有 OOM 降级策略：
```yaml
vram:
  oom_fallback:
    reduce_max_frames: [8, 6, 4]
    reduce_max_dim: [512, 384]
```

---

**文档版本**: v1.0  
**创建时间**: 2026-02-05  
**作者**: [Author]
