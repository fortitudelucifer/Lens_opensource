# 语音流水线设计概览

> 📌 **本文档定位**：这是 [多模态处理流水线文档](modality_fields_and_models.md) 的详细设计文档，专注于语音流水线的 ASR 转写、情绪分析、Triage 筛选和深度分析策略。

## 1. 设计理念

### 1.1 核心目标

语音流水线处理微信聊天记录中的语音消息（`type=34`），提取文字内容和情感信息：

| 挑战 | 解决方案 |
|------|----------|
| 语音转写准确度 | FunASR + 热词增强 |
| 情绪检测 | SenseVoice 快速检测 |
| 深度情感分析 | Qwen2-Audio 按需触发 |
| 计算资源优化 | Triage 筛选机制 |
| 显存约束 | 模型串行加载 |

### 1.2 设计原则

```
┌─────────────────────────────────────────────────────────────────┐
│                      设计原则                                    │
├─────────────────────────────────────────────────────────────────┤
│  1. 双引擎转写：FunASR（主）+ Whisper（备）                     │
│  2. 四阶段情绪：SenseVoice → Triage → Qwen2-Audio → 人工审核   │
│  3. 按需深度分析：只对触发的样本使用 Qwen2-Audio                │
│  4. 文本后处理：繁简转换 + 标点修复 + 误判修正                  │
│  5. 显存安全：模型串行加载，避免 OOM                            │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. 四阶段流水线架构

### 2.1 整体流程图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          Voice Pipeline                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐ │
│   │   Step 1     │   │   Step 2     │   │   Step 3     │   │   Step 4     │ │
│   │   FunASR     │──▶│   Emotion    │──▶│    Merge     │──▶│   Timeline   │ │
│   │  语音转写    │   │  情绪分析    │   │   合并引擎   │   │  时间轴更新  │ │
│   └──────────────┘   └──────────────┘   └──────────────┘   └──────────────┘ │
│          │                  │                  │                  │         │
│          ▼                  ▼                  ▼                  ▼         │
│   voice_funasr       voice_merged        voice_merged       enriched_full   │
│   _v2.jsonl          _v3.jsonl           _final.jsonl       .jsonl          │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 各阶段详解

| 阶段 | 脚本 | 输入 | 输出 | 模型 |
|------|------|------|------|------|
| **FunASR** | `_01_run_funasr.py` | raw/voice/*.mp3 | 转写文本 | FunASR (paraformer-zh) |
| **Emotion** | `_02_run_emotion.py` | 转写 + 音频 | 情绪标签 | SenseVoice + Qwen2-Audio |
| **Compress** | `_02.5_run_compress.py` | 情绪结果 | 压缩描述 | Qwen2.5-7B |
| **Merge** | `_03_merge_engine.py` | 各阶段输出 | 合并结果 | - |
| **Timeline** | `_04_update_timeline.py` | 合并结果 | 时间轴 | - |

---

## 3. ASR 语音转写（Step 1）

### 3.1 FunASR 三合一模型

FunASR 集成了三个模型，一次调用完成全部处理：

| 模型 | 功能 | 说明 |
|------|------|------|
| **paraformer-zh** | ASR 转写 | 阿里达摩院中文语音识别 |
| **fsmn-vad** | VAD 检测 | 语音活动检测，分割语音段 |
| **ct-punc** | 标点恢复 | 自动添加标点符号 |

### 3.2 热词增强

通过热词（hotword）提高特定词汇的识别准确度：

```yaml
# configs/voice.yaml
asr:
  funasr:
    hotword: "云顶之弈 金铲铲"
    hotword_file: "configs/hotword.txt"
```

热词适用场景：
- 游戏名称、专有名词
- 人名、地名
- 行业术语

### 3.3 文本后处理

转写完成后进行多步后处理：

```
原始转写
    │
    ├──▶ 繁体转简体 (OpenCC t2s)
    │
    ├──▶ 去除标点 (为后续标点模型准备)
    │
    ├──▶ 标点去重 (修复重复标点)
    │
    ├──▶ 应用文本补丁 (修正常见错误)
    │
    └──▶ 修复误判问句 (修正错误的问号)
```

### 3.4 输出字段

```json
{
  "schema_version": "voice_v3",
  "file": "20250618-130037-132076-1.mp3",
  "engine": "FunASR paraformer-zh + fsmn-vad + ct-punc",
  "raw_text": "原始转写文本",
  "raw_text_s": "简体转换后的文本",
  "raw_for_punc": "去除标点后的文本",
  "punct_text": "最终标点文本",
  "patches": ["应用的补丁列表"],
  "prep_meta": {
    "simplified": true,
    "opencc_config": "t2s",
    "strip_punc_applied": true,
    "punc_model": "ct-punc",
    "punc_from_engine": true
  }
}
```

---

## 4. 情绪分析四阶段流程（Step 2）

### 4.1 整体流程

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      Emotion Analysis Pipeline                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐ │
│   │  Phase 1     │   │  Phase 2     │   │  Phase 3     │   │  Phase 4     │ │
│   │ SenseVoice   │──▶│   Triage     │──▶│ Qwen2-Audio  │──▶│  人工审核    │ │
│   │ 快速检测     │   │  筛选触发    │   │  深度分析    │   │  标注文件    │ │
│   └──────────────┘   └──────────────┘   └──────────────┘   └──────────────┘ │
│          │                  │                  │                  │         │
│          ▼                  ▼                  ▼                  ▼         │
│   所有样本          触发样本          深度分析结果      voice_v3_labeling.md │
│   emotion_tags      trigger_reasons   voice_analysis                        │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 4.2 Phase 1: SenseVoice 快速检测

**模型**：SenseVoice Small (`iic/SenseVoiceSmall`)

**功能**：
- 情绪标签检测：SAD / HAPPY / ANGRY / NEUTRAL
- 声音事件检测：Cry / Laughter / Applause / Music / BGM

**输出格式**：
```
<|EMOTION|><|EVENT|><|sil|>text
```

**示例**：
```
<|SAD|><|Cry|><|sil|>我真的很难过
```

### 4.3 Phase 2: Triage 筛选

Triage 基于规则筛选需要深度分析的样本，减少 Qwen2-Audio 的计算量。

**触发条件**（满足任一即触发）：

| 触发类型 | 条件 | 示例 |
|----------|------|------|
| **情绪触发** | emotion_tags 包含 SAD/ANGRY/HAPPY | `['SAD']` |
| **事件触发** | event_tags 包含 Cry/Laughter | `['Cry']` |
| **关键词触发** | 文本包含配置的敏感词 | "累了"、"想你了" |

**关键词分类**（来自 `configs/voice.yaml`）：

| 类别 | 关键词示例 | 说明 |
|------|------------|------|
| A_Crisis | 随便、累了、烦死了、算了 | 危机/压力类 |
| B_Intimacy | 在干嘛、想你了、想见你 | 亲密关系类 |
| C_Workplace | 收到、辛苦了、原则上 | 职场类 |
| D_Boundaries | 为你好、借我、帮个忙 | 边界/施压类 |
| E_Sadness | 残酷、遗憾、后悔、不舍 | 伤心/无奈类 |
| F_Confusion | 是吧、为什么、不懂 | 疑惑/困惑类 |
| G_Helpless | 没法、着急、挺烦 | 无奈类 |

### 4.4 Phase 3: Qwen2-Audio 深度分析

**模型**：Qwen2-Audio-7B-Instruct

**触发条件**：只对 Triage 触发的样本进行深度分析

**分析维度**：

| 维度 | 说明 | 示例 |
|------|------|------|
| **语调特征** | 音调、语速、停顿 | "语速较慢，有明显停顿" |
| **情绪状态** | 详细情绪描述 | "表面平静但略带疲惫" |
| **潜台词** | 隐含意图 | "可能在掩饰真实情绪" |
| **情绪标签** | 细粒度标签 | 中性/伤心/愤怒/期待/无奈/疑惑/诱惑/兴奋/遗憾/担忧/委屈 |

**系统提示词**：
```
你是语音情感分析专家。请仔细听这段语音，分析说话人的真实情绪。

【分析要点】
1. 注意语调起伏、语速变化、停顿位置
2. 关注呼吸声、叹气、颤音等非语言信号
3. 区分表面情绪和深层情绪

【请用以下格式输出】
语调特征：（描述语调高低、语速快慢、是否有停顿/颤音/叹气）
情绪状态：（用2-3句话描述说话人的情绪）
潜台词：（一句话概括说话人真正想表达的意思）
情绪标签：（从以下选1-2个：中性/伤心/愤怒/期待/无奈/疑惑/诱惑/兴奋/遗憾/担忧/委屈）
```

### 4.5 Phase 4: 人工审核

生成 Markdown 标注文件供人工审核：

```markdown
# 语音情绪标注表 v3

**生成时间**: 2026-02-05 14:30
**总样本**: 100
**触发样本**: 25

---

## 1. 20250618-130037-132076-1.mp3

> 我真的很难过

| SenseVoice | Triage |
|------------|--------|
| ['SAD'] | ✅ 触发 |

**你的标注**: 

---
```

---

## 5. 情绪分类法

### 5.1 完整情绪分类体系

```yaml
emotion_taxonomy:
  A_Toxic:           # 有毒情绪
    - Contempt       # 轻蔑：冷笑、鼻音重
    - Sarcastic      # 讽刺：夸张语调、假性热情
    - Passive-Aggressive  # 冷暴力：表面平静、潜台词攻击
  
  B_Intimacy:        # 亲密情绪
    - Longing        # 思念：气音、轻柔、拉长音
    - Seductive      # 诱惑：低沉气声、若有若无的笑意
    - Playful        # 调情/撒娇：音调上扬、轻快节奏
    - Anticipation   # 期待：语速加快、音调升高
  
  C_Distress:        # 痛苦情绪
    - Resigned       # 无奈：叹气、能量下降
    - Helpless       # 无助：颤抖、长停顿、哽咽前兆
    - Hurt           # 受伤/委屈：哭腔、气息不稳
    - Regret         # 遗憾：停顿多、自我责备语调
  
  D_Masking:         # 掩饰情绪
    - Suppressed-Anger  # 隐忍：咬字用力、气息紧绷
    - Fake-Cheerful     # 强颜欢笑：笑声空洞
  
  E_Basic:           # 基础情绪
    - Happy          # 开心
    - Sad            # 悲伤
    - Angry          # 愤怒
    - Neutral        # 中性
  
  F_Cognitive:       # 认知情绪
    - Confused       # 困惑：音调上扬的疑问，无攻击性
    - Skeptical      # 怀疑：拖长音、不信任
```

---

## 6. 显存管理策略

### 6.1 模型显存占用

| 模型 | 显存占用 | 使用阶段 |
|------|----------|----------|
| FunASR (paraformer-zh) | ~2GB | Step 1 转写 |
| SenseVoice Small | ~1GB | Step 2 情绪检测 |
| Qwen2-Audio-7B | ~8GB | Step 2 深度分析 |

### 6.2 串行加载策略

```
┌─────────────────────────────────────────────────────────────────┐
│  显存管理流程                                                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Step 1: FunASR 转写                                            │
│  ├─ 加载 FunASR 模型                                            │
│  ├─ 处理所有语音文件                                            │
│  └─ 卸载 FunASR 模型                                            │
│                                                                  │
│  Step 2: SenseVoice 情绪检测                                    │
│  ├─ 加载 SenseVoice 模型                                        │
│  ├─ 处理所有语音文件                                            │
│  └─ 卸载 SenseVoice 模型                                        │
│                                                                  │
│  Step 2.5: Qwen2-Audio 深度分析（仅触发样本）                   │
│  ├─ 对每个触发样本：                                            │
│  │   ├─ 加载 Qwen2-Audio 模型                                   │
│  │   ├─ 分析单个样本                                            │
│  │   └─ 卸载 Qwen2-Audio 模型                                   │
│  └─ 释放显存                                                    │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 6.3 显存释放代码

```python
def cleanup_model():
    global _model
    import torch
    
    if _model is not None:
        del _model
        _model = None
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.synchronize()
```

---

## 7. 输出字段

### 7.1 情绪分析输出（voice_merged_v3.jsonl）

```json
{
  "schema_version": "v3",
  "file": "20250618-130037-132076-1.mp3",
  "punct_text": "我真的很难过",
  "sensevoice": {
    "emotion_tags": ["SAD"],
    "event_tags": ["Cry"],
    "clean_text": "我真的很难过"
  },
  "trigger_reasons": ["emotion:SAD", "event:Cry"],
  "voice_analysis": {
    "emotion_desc": "说话人声音低沉，带有明显的哽咽感",
    "tonal_features": "语速缓慢，有多处停顿",
    "subtext": "可能正在经历情感上的困难",
    "emotion_tags": ["伤心", "无助"]
  }
}
```

### 7.2 合并输出（voice_merged_final.jsonl）

```json
{
  "schema_version": "merged_v2",
  "msg_uid": "P1:1234567890",
  "modality": "voice",
  "voice_punct_text": "我真的很难过",
  "voice_emotion_tags": ["SAD"],
  "voice_event_tags": ["Cry"],
  "voice_analysis": {
    "emotion_desc": "说话人声音低沉，带有明显的哽咽感",
    "tonal_features": "语速缓慢，有多处停顿",
    "subtext": "可能正在经历情感上的困难"
  }
}
```

---

## 8. 配置文件详解

### 8.1 configs/voice.yaml 结构

```yaml
# Schema 版本
schema_version: "voice_v3"

# ASR 引擎配置
asr:
  funasr:
    model: "paraformer-zh"
    vad_model: "fsmn-vad"
    punc_model: "ct-punc"
    hotword: "云顶之弈 金铲铲"
    hotword_file: "configs/hotword.txt"
  
  whisper:
    model_path: "/data/models/faster-whisper-large-v3"
    device: "cuda"
    compute_type: "float16"

# 文本后处理
text_processing:
  opencc_config: "t2s"
  strip_punc: true
  dedup_punc: true
  apply_patches: true
  fix_false_question: true

# 情绪分析配置
emotion:
  sensevoice:
    model_id: "iic/SenseVoiceSmall"
    device: "cuda:0"
    batch_size_s: 60
  
  qwen_audio:
    model_path: "/data/models/qwen2-audio-7b-instruct"
    device_map: "auto"
    torch_dtype: "float16"
    generation:
      max_new_tokens: 300

# Triage 配置
triage:
  emotion_triggers: ["SAD", "ANGRY", "HAPPY"]
  event_triggers: ["Cry", "Laughter"]
  keywords:
    A_Crisis: ["随便", "累了", "烦死了"]
    B_Intimacy: ["在干嘛", "想你了"]
    # ...

# 系统提示词
prompts:
  qwen_system: |
    你是语音情感分析专家...
```

---

## 9. 运行命令

```bash
# 激活环境
conda activate wechatDHA

# 运行完整语音流水线
python run_all_pipelines.py --only voice

# 或分步运行
python scripts/voice/run_all/_01_run_funasr.py              # FunASR 转写
python scripts/voice/run_all/_02_run_emotion.py             # 情绪分析
python scripts/voice/run_all/_02.5_run_compress.py          # 语义压缩
python scripts/voice/run_all/_03_merge_engine.py            # 合并引擎
python scripts/voice/run_all/_04_update_timeline.py         # 时间轴更新

# 测试模式
python scripts/voice/run_all/_01_run_funasr.py --sample 10  # 仅处理前 10 条
python scripts/voice/run_all/_02_run_emotion.py --skip-qwen # 跳过 Qwen 分析
python scripts/voice/run_all/_02_run_emotion.py --qwen-limit 5  # 限制 Qwen 数量
```

---

## 10. 目录结构

```
scripts/voice/
└── run_all/
    ├── _01_run_funasr.py        # FunASR 转写
    ├── _01b_run_whisper.py      # Whisper 转写（备用）
    ├── _02_run_emotion.py       # 情绪分析
    ├── _02.5_run_compress.py    # 语义压缩
    ├── _03_merge_engine.py      # 合并引擎
    └── _04_update_timeline.py   # 时间轴更新

artifacts/before_merge/voice/
├── voice_funasr_v2.jsonl        # FunASR 转写结果
├── voice_whisper_v2.jsonl       # Whisper 转写结果（可选）
├── voice_merged_v3.jsonl        # 情绪分析合并结果
├── voice_qwen_analysis.jsonl    # Qwen 深度分析结果
└── voice_v3_labeling.md         # 人工标注文件

artifacts/after_merge/voice/
└── voice_merged_final.jsonl     # 最终合并结果

configs/
├── voice.yaml                   # 语音配置文件
└── hotword.txt                  # 热词列表
```

---

## 11. 与其他模态的对比

| 特性 | Image | **Voice** | Video | Sticker | Linkfile |
|------|-------|-----------|-------|---------|----------|
| 需要 GPU | ✅ | ✅ | ✅ | ✅ | ❌ |
| 流水线步骤 | 4 | **4** | 5 | 8 | 3 |
| 原始 Token | 300-800 | **100-400** | 1500-2500 | 50-200 | 20-200 |
| 压缩后 Token | 80-150 | **50-100** | 150-250 | 30-60 | 15-100 |
| Triage 分类 | ✅ | ✅ | ✅ | ✅ | ❌ |
| 情绪分析 | ❌ | ✅ (深度) | ✅ (融合) | ❌ | ❌ |
| 深度分析 | ❌ | ✅ (Qwen2-Audio) | ❌ | ❌ | ❌ |

---

## 12. 设计亮点

1. **双引擎转写**：FunASR（主）+ Whisper（备），提高转写准确度

2. **四阶段情绪分析**：SenseVoice 快速检测 → Triage 筛选 → Qwen2-Audio 深度分析 → 人工审核

3. **Triage 筛选机制**：基于规则筛选，只对触发的样本使用 Qwen2-Audio，节省计算资源

4. **细粒度情绪分类**：支持 20+ 种情绪标签，覆盖有毒、亲密、痛苦、掩饰等多种情绪类型

5. **热词增强**：通过热词提高特定词汇的识别准确度

6. **文本后处理**：繁简转换 + 标点修复 + 误判修正，提高文本质量

7. **人工审核支持**：生成 Markdown 标注文件，便于人工审核和标注

---

## 13. 常见问题

### Q1: FunASR 转写不准确？

**A**: 尝试以下方法：
1. 添加热词到 `configs/hotword.txt`
2. 检查音频质量（采样率、噪音）
3. 使用 Whisper 作为备用引擎

### Q2: Qwen2-Audio 分析太慢？

**A**: 
1. 使用 `--qwen-limit N` 限制分析数量
2. 调整 Triage 规则，减少触发样本
3. 使用 `--skip-qwen` 跳过深度分析

### Q3: 情绪检测不准确？

**A**: 
1. 检查 SenseVoice 输出的原始标签
2. 调整 Triage 关键词配置
3. 人工审核标注文件，修正错误

### Q4: 显存不足怎么办？

**A**: 
1. 确保模型串行加载（不要同时加载多个模型）
2. 减少 `batch_size_s` 参数
3. 使用 `--skip-qwen` 跳过 Qwen2-Audio

### Q5: 如何添加新的触发关键词？

**A**: 编辑 `configs/voice.yaml` 中的 `triage.keywords` 部分：
```yaml
triage:
  keywords:
    新类别:
      - "关键词1"
      - "关键词2"
```

---

## 14. 压缩策略

### 14.1 压缩目标

语音压缩器保留转写文本和情绪标签，压缩冗余的情感分析描述：

| 阶段 | Token 估算 | 说明 |
|------|------------|------|
| 原始（转写 + 分析） | 100-400 tokens | 转写文本 + Qwen2-Audio 分析 |
| 压缩后 | 50-100 tokens | 保留核心信息 |
| **压缩比** | **2-3x** | 适度压缩 |

### 14.2 字段保留策略

| 字段 | 处理方式 | 说明 |
|------|----------|------|
| `punct_text` | **完整保留** | 转写文本是核心内容 |
| `emotion_tags` | **完整保留** | SenseVoice 情绪标签 |
| `voice_analysis.emotion_desc` | **压缩/删除** | 根据价值判断 |
| `voice_analysis.subtext` | **保留** | 潜台词有价值 |

### 14.3 分析价值判断

压缩器会判断 Qwen2-Audio 的情感分析是否有价值：

**低价值分析（删除）**：

```python
low_value_patterns = [
    r'^语气.*平静',      # "语气平静，没有明显情绪"
    r'^没有明显.*情绪',  # "没有明显的情绪波动"
    r'^情绪.*中性',      # "情绪中性"
    r'^语气.*中性'       # "语气中性"
]
```

**高价值分析（保留）**：

```python
valuable_keywords = [
    '自信', '自豪', '歉意', '内疚', '焦虑', '担心', '开心', '兴奋',
    '失望', '沮丧', '愤怒', '不满', '疑惑', '困惑', '期待', '渴望',
    '自嘲', '幽默', '讽刺', '无奈', '委屈', '撒娇', '真诚', '诚恳'
]
```

### 14.4 分析压缩

对于有价值的分析，提取关键情感词：

```python
# 原始分析
emotion_desc = "根据语音内容，可以感受到说话人语气中带有明显的焦虑和担心，整体上表现出对未来的不确定感。"

# 压缩后
analysis_summary = "焦虑，担心，对未来不确定"
```

### 14.5 意图推断

从转写文本推断发送意图：

| 意图 | 触发条件 | 示例 |
|------|----------|------|
| 解释说明 | 包含"因为"、"所以" | "因为今天下雨所以没去" |
| 分享经历 | 包含"我"+"经历"/"那次" | "我那次去北京的时候" |
| 表达观点 | 包含"我觉得"、"我认为" | "我觉得这样不太好" |
| 询问 | 包含"吗？"、"呢？" | "你在干嘛呢？" |
| 抱怨 | 包含"不满"、"烦" | "真的好烦啊" |
| 道歉 | 包含"对不起"、"抱歉" | "对不起让你等了" |

### 14.6 输出字段

```json
{
  "file": "20250618-130037-132076-1.mp3",
  "schema_version": "voice_compressed_v1",
  "punct_text": "我真的很难过",
  "emotion_tags": ["SAD"],
  "analysis_summary": "声音低沉，带有哽咽感",
  "possible_intent": "表达",
  "possible_subtext": "可能正在经历情感困难",
  "compression_ratio": 2.5,
  "original_length": 200,
  "compressed_length": 80
}
```

### 14.7 压缩效果示例

| 场景 | 原始 | 压缩后 | 压缩比 |
|------|------|--------|--------|
| 有深度分析 | 转写50字 + 分析150字 | 转写50字 + 摘要30字 | 2.5x |
| 无深度分析 | 转写50字 | 转写50字 | 1x |
| 低价值分析 | 转写50字 + 分析100字 | 转写50字（删除分析） | 3x |

---

**文档版本**: v1.0  
**创建时间**: 2026-02-05  
**作者**: [Author]
