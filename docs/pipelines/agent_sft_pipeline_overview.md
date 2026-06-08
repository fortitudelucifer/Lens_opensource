# Agent SFT 流水线设计概览

> 📌 **本文档定位**：这是 [多模态处理流水线文档](modality_fields_and_models.md) 的详细设计文档，专注于 Agent SFT 数据生成的完整流程、L1/L2 分支策略、PII 检测和时间轴后处理。

## 1. 设计理念

### 1.1 核心目标

Agent SFT 流水线将多模态时间轴数据转化为高质量的训练数据，支持本地训练（L1）和云端训练（L2）两种场景：

| 挑战 | 解决方案 |
|------|----------|
| 数据量大，Token 消耗高 | 多阶段压缩（77%+ 压缩率） |
| 隐私保护（云端训练） | 三层混合 PII 检测 + 匿名化 |
| 连续消息冗余 | 情绪感知消息合并 |
| 时间信息丢失 | 精确时间间隔标记 |
| 字段冗余 | 智能字段精简 |

### 1.2 设计原则

```
┌─────────────────────────────────────────────────────────────────┐
│                      设计原则                                    │
├─────────────────────────────────────────────────────────────────┤
│  1. 分支策略：L1 保留真实数据，L2 完全匿名化                    │
│  2. 语义保留：压缩技术元数据，保留所有语义字段                  │
│  3. 情绪感知：合并时考虑情绪兼容性，避免破坏对话结构            │
│  4. 精确时间：使用精确时间间隔格式，而非模糊描述                │
│  5. 两阶段检测：规则引擎 + 两阶段 PII 检测（推荐）              │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. 六阶段流水线架构

### 2.1 整体流程图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Agent SFT Pipeline                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   ┌──────────────┐                                                          │
│   │   Phase 1    │                                                          │
│   │  时间轴后处理 │                                                          │
│   │ postprocess  │                                                          │
│   └──────┬───────┘                                                          │
│          │                                                                   │
│          ▼                                                                   │
│   enriched_full_processed.jsonl                                             │
│          │                                                                   │
│          ├─────────────────────────┬────────────────────────────┐           │
│          │                         │                            │           │
│          ▼                         ▼                            │           │
│   ┌──────────────┐          ┌──────────────┐                    │           │
│   │   Phase 2    │          │   Phase 2    │                    │           │
│   │  L1 字段精简  │          │  L2 匿名化   │                    │           │
│   │ sft_trimmer  │          │ anonymization│                    │           │
│   └──────┬───────┘          └──────┬───────┘                    │           │
│          │                         │                            │           │
│          │                         ▼                            │           │
│          │                  ┌──────────────┐                    │           │
│          │                  │   Phase 3    │                    │           │
│          │                  │  L2 字段精简  │                    │           │
│          │                  │ sft_trimmer  │                    │           │
│          │                  └──────┬───────┘                    │           │
│          │                         │                            │           │
│          ▼                         ▼                            │           │
│   ┌──────────────┐          ┌──────────────┐                    │           │
│   │   Phase 4    │          │   Phase 4    │                    │           │
│   │  L1 优化     │          │  L2 优化     │                    │           │
│   │ sft_optimizer│          │ sft_optimizer│                    │           │
│   └──────┬───────┘          └──────┬───────┘                    │           │
│          │                         │                            │           │
│          ▼                         ▼                            │           │
│   agent_sft_l1.jsonl        agent_sft_l2.jsonl                  │           │
│   (本地训练)                (云端训练)                   │           │
│          │                         │                            │           │
│          └─────────────┬───────────┘                            │           │
│                        ▼                                        │           │
│                 ┌──────────────┐                                │           │
│                 │   Phase 5    │                                │           │
│                 │  质量验证    │                                │           │
│                 │ validate_sft │                                │           │
│                 └──────────────┘                                │           │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 各阶段详解

| 阶段 | 脚本 | 输入 | 输出 | 功能 |
|------|------|------|------|------|
| **Phase 1** | `postprocess_timeline.py` | enriched_full.jsonl | enriched_full_processed.jsonl | 消息合并 + 时间标记 |
| **Phase 2 (L1)** | `sft_trimmer.py --l1` | processed.jsonl | l1_sft.jsonl | 字段精简 |
| **Phase 2 (L2)** | `run_anonymization.py --level l2` | processed.jsonl | l2.jsonl | PII 检测 + 匿名化 |
| **Phase 3 (L2)** | `sft_trimmer.py --l2` | l2.jsonl | l2_sft.jsonl | 字段精简 |
| **Phase 4** | `sft_optimizer.py` | *_sft.jsonl | agent_sft_*.jsonl | ID/时间压缩 |
| **Phase 5** | `validate_sft_quality.py` | agent_sft_*.jsonl | 验证报告 | 质量验证 |

---

## 3. 核心组件设计

### 3.1 TimelinePostprocessor（时间轴后处理器）

**位置**：`scripts/timeline/postprocess_timeline.py`

#### 3.1.1 消息合并策略

连续消息合并可以显著减少 Token 数量，但需要保持对话的自然结构：

```
合并条件（必须全部满足）：
├─ 同一 speaker
├─ 时间间隔 < 60 秒
├─ 都是文本消息（type=text）
└─ 情绪兼容（无冲突）

不合并场景：
├─ 多模态消息（图片、语音、视频等）
├─ 情绪冲突（如 开心 vs 生气）
├─ 快速连发短句（吵架/撒娇模式）
└─ 包含特殊标记的消息
```

#### 3.1.2 情绪感知合并

```python
# 情绪兼容性检查
def is_emotion_compatible(emotion1, emotion2):
    # 同类情绪可合并
    positive = {'开心', '高兴', '兴奋', '期待'}
    negative = {'生气', '难过', '失望', '焦虑'}
    neutral = {'平静', '中性', None}
    
    # 同组内可合并
    for group in [positive, negative, neutral]:
        if emotion1 in group and emotion2 in group:
            return True
    return False
```

#### 3.1.3 时间间隔标记

当消息间隔超过 2 小时，插入 `time_gap` 标记：

**时间间隔格式**（2026-02-05 更新）：

采用精确描述格式，而非模糊描述：

| 时间间隔 | 格式示例 | 说明 |
|----------|----------|------|
| < 1小时 | `[31分钟后]` | 仅显示分钟 |
| 1-24小时 | `[2小时31分钟后]` | 小时+分钟 |
| 1-7天 | `[2天5小时后]` | 天+小时 |
| > 7天 | `[8天19小时后]` | 天+小时 |

**重要**：`gap_description` 字段已废弃，时间信息仅在 `text_raw` 中。

#### 3.1.4 中断类型检测

```yaml
break_types:
  normal_gap: 正常时间间隔
  potential_cold_shoulder: 可能的冷战（单方面长时间不回复）
  topic_change: 话题转换
  conflict_cooling: 冲突后冷静期
```

### 3.2 SFTTrimmer（字段精简器）

**位置**：`scripts/compression/sft_trimmer.py`

#### 3.2.1 保留字段策略

```yaml
# 系统字段（始终保留）
system_fields:
  - msg_uid
  - ts
  - time_local
  - speaker
  - type
  - modality

# 语义字段（按模态保留）
semantic_fields:
  text: [text_raw]
  quote: [text_raw, link_quote_text]
  sticker: [sticker_summary, sticker_intent, sticker_ocr_text]
  image: [image_summary, image_intent, image_emotion_atmosphere]
  voice: [voice_to_text, emotion_tags, emotion_desc]
  video: [video_summary, video_voice_to_text, video_emotion_tags]
  link: [link_title, text_raw]
  miniprogram: [link_title, text_raw]
  time_gap: [text_raw, break_type]  # gap_description 已废弃

# 移除字段（技术元数据）
removed_fields:
  - image_path, video_path, voice_path
  - triage_*, metadata.*
  - extraction_params, processing_*
  - *_confidence, *_score
```

#### 3.2.2 压缩效果

| 优化项 | 节省字符数 | 说明 |
|--------|-----------|------|
| 字段精简 | 3,383,199 | 移除技术元数据 |
| 消息合并 | 516,005 | 合并连续同方向消息 |
| **总计** | **3,899,204** | **67.34% 压缩率** |

### 3.3 SFTOptimizer（Token 优化器）

**位置**：`scripts/compression/sft_optimizer.py`

#### 3.3.1 优化策略

| 优化项 | 原始格式 | 优化后 | 节省 |
|--------|----------|--------|------|
| msg_uid | `P1:8911054651869296902` | `{"id": 1}` | ~25 字符/条 |
| 时间戳 | `2025-06-07 14:54:03` | `14:54`（同天） | ~11 字符/条 |
| 消息类型 | `文本` | `text` | ~3 字符/条 |

#### 3.3.2 重要设计决策

**保留所有语义字段**：不压缩多模态内容字段（sticker_intent、image_summary、emotion_desc 等），分离字段比合成到统一 content 更利于模型学习结构化信息。

---

## 4. PII 检测（两阶段高精度架构）

> 📖 **详细指南**：[PII 检测使用指南](pii_detection_guide.md)

### 4.1 架构概览

```
┌─────────────────────────────────────────────────────────────────┐
│                    两阶段 PII 检测架构                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   Layer 1: 规则引擎                                              │
│   ├─ 正则匹配：手机号、邮箱、身份证号、微信 ID                   │
│   ├─ 配置映射：已知的 me_names/other_names                       │
│   └─ 排除列表：公众人物、历史人物                                │
│                                                                  │
│   两阶段 PII 检测（推荐）                                        │
│   ├─ Phase 1: 候选词提取 + LLM 验证（离线扫描）                  │
│   │   └─ 模型：Qwen2.5-7B-Instruct-AWQ (~4GB)                    │
│   ├─ Phase 2: 精确字符串匹配（匿名化时）                         │
│   └─ 优势：人工审核、精确匹配、无漏检                            │
│                                                                  │
│   注意：GLiNER 已废弃（2026-02-06），因中文误检率高              │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 4.2 跳过检测的字段/消息类型

为避免误检测，以下字段或消息类型会跳过 PII 检测：

| 字段/类型 | 跳过原因 | 示例 |
|-----------|----------|------|
| `sticker_summary` | 情绪描述词被误识别为地名 | `[开心/高兴]` |
| `sticker_intent` | 同上 | `撒娇/卖萌` |
| `time_gap` 的 `text_raw` | 时间描述被误识别为 DATE | `[8天19小时后]` |

**实现位置**：`scripts/compression/privacy_shield.py`

```python
# anonymize_l1() 方法中
for field in text_fields:
    if field in result and result[field]:
        # 跳过 time_gap 类型消息的 text_raw 字段
        if field == 'text_raw' and result.get('type') == 'time_gap':
            continue
        # ... 正常 PII 检测
```

### 4.3 L2 匿名化处理

| 处理项 | 方法 | 说明 |
|--------|------|------|
| 姓名 | 替换为 ME/OTHER 或 [PERSON_N] | 一致性伪匿名化 |
| 电话 | 替换为 `[电话号码]` | 正则匹配 |
| 地名 | 映射到附近城市 | 配置文件定义 |
| 时间戳泛化 | 保留时段（凌晨/上午/下午/晚上）、工作日/周末 | - |
| 时间戳偏移 | 所有时间戳向前偏移 100 天 | 防止时间定位 |
| 相对时间 | 输出 day_index 和 ts_relative | 第 1 天、第 2 天... |

#### 排除逻辑说明（2026-02-07 修复）

`exclude_patterns` 配置用于排除历史人物、公众人物等不应被替换的名字。排除逻辑如下：

```python
# 只有当排除模式包含当前名字，且排除模式出现在上下文中时才排除
# 例如："毛泽东"包含"泽东"，所以"毛泽东传"中的"泽东"会被排除
# 但"同学"不包含"张三"，所以"张三同学"中的"张三"会被替换为"ME同学"
if name in exclude and exclude in context:
    should_exclude = True
```

这确保了：
- ✅ "张三同学" → "ME同学"（用户名字正确替换）
- ✅ "毛泽东传" → "毛泽东传"（历史人物正确保留）

---

## 5. L1 vs L2 对比

### 5.1 特性对比

| 特性 | L1 (本地训练) | L2 (云端训练) |
|------|---------------|---------------|
| **用途** | 本地 GPU 训练 | 云端 API 训练 |
| **数据** | 真实数据 | 完全匿名化 |
| **姓名** | 保留真实姓名 | ME/OTHER 代号 |
| **电话** | 保留 | [电话号码] |
| **地名** | 保留 | 映射到附近城市 |
| **时间** | 真实时间 | 泛化+偏移 |
| **压缩率** | 77.71% | 76.91% |

### 5.2 输出格式示例

#### L1 本地训练格式

```jsonl
{"id":1,"time":"2025-06-07 14:54","speaker":"OTHER","type":"text","text":"I've accepted your friend request. Now let's chat!"}
{"id":2,"time":"15:12","speaker":"OTHER","type":"text","text":"UserB，OTHER，138xxxx5678"}
{"type":"time_gap","text_raw":"[9天3小时后]","break_type":"normal_gap"}
{"id":3,"time":"2025-06-16 10:23","speaker":"ME","type":"link","content":"依恋型人格ECR测试"}
```

#### L2 云端训练格式

```jsonl
{"id":1,"time":"2025-06-07 14:54","speaker":"OTHER","type":"text","text":"I've accepted your friend request. Now let's chat!"}
{"id":2,"time":"15:12","speaker":"OTHER","type":"text","text":"[PERSON_1]，OTHER，[电话号码]"}
{"type":"time_gap","text_raw":"[9天3小时后]","break_type":"normal_gap"}
{"id":3,"time":"2025-06-16 10:23","speaker":"ME","type":"link","content":"依恋型人格ECR测试"}
```

---

## 6. 配置文件

### 6.1 configs/timeline_postprocess.yaml

```yaml
# 消息合并
merge_messages: true
merge_threshold_seconds: 60  # 60秒内的连续消息可合并
emotion_aware_merge: true    # 启用情绪感知合并

# 时间间隔标记
add_time_gaps: true
time_gap_threshold_seconds: 7200  # 2小时以上插入标记

# 中断类型检测
detect_break_types: true
break_type_keywords:
  conflict: ["生气", "烦", "算了", "随便"]
  cold_shoulder: ["哦", "嗯", "好"]
```

### 6.2 configs/sft_optimizer.yaml

```yaml
# ID 简化：P1:xxx → 1
use_simple_id: true

# 时间戳压缩：同天内仅保留 HH:MM
compress_time: true

# 消息类型简化：中文 → 英文
simplify_type: true

# 重要：保留所有语义字段，不做内容压缩
```

### 6.3 configs/anonymization.yaml

```yaml
# 人名配置
me_names:
  - "王小明"
  - "小明"

other_names:
  - "UserB"
  - "NickNameB"

# 地名映射
location_mapping:
  深圳: 广州
  北京: 天津
  上海: 杭州

# 排除列表（公众人物等）
exclude_patterns:
  - "毛泽东"
  - "李白"

# L2 云端训练配置
l2_cloud:
  timestamp_shift:
    enabled: true
    shift_days: 100
  relative_time:
    enabled: true
  location_replacement:
    enabled: true
```

---

## 7. 运行命令

### 7.1 一键执行

```bash
# 运行完整 Agent SFT 流水线（包含质量验证）
./run_agent_sft_pipeline.sh

# 只生成 L1 数据
./run_agent_sft_pipeline.sh --only l1

# 只生成 L2 数据
./run_agent_sft_pipeline.sh --only l2

# 跳过后处理（使用已有的 processed 文件）
./run_agent_sft_pipeline.sh --skip-postprocess
```

### 7.2 分步执行

```bash
# Phase 1: 时间轴后处理
python scripts/timeline/postprocess_timeline.py

# Phase 2-4 (L1): 本地训练数据
python scripts/compression/sft_trimmer.py --l1
python scripts/compression/sft_optimizer.py --level l1

# Phase 2-4 (L2): 云端训练数据
python scripts/timeline/run_anonymization.py --level l2 --two-stage-pii
python scripts/compression/sft_trimmer.py --l2
python scripts/compression/sft_optimizer.py --level l2

# Phase 5: 质量验证
python scripts/compression/validate_sft_quality.py --level all
```

### 7.3 质量验证

```bash
# 验证所有数据
python scripts/compression/validate_sft_quality.py --level all

# 只验证 L2 数据
python scripts/compression/validate_sft_quality.py --level l2

# 严格模式（任何问题都返回非零退出码）
python scripts/compression/validate_sft_quality.py --level l2 --strict
```

验证内容：
- 名字泄露检测（L2）：检查 me_names/other_names 是否正确替换
- 历史人物排除：确保"毛泽东"等公众人物不被误替换
- speaker 字段验证：确保只有 ME/OTHER/SYSTEM
- 数据完整性：检查空文本比例、类型分布等

### 7.3 质量验证

```bash
# 验证所有数据
python scripts/compression/validate_sft_quality.py --level all

# 只验证 L2 数据
python scripts/compression/validate_sft_quality.py --level l2

# 严格模式（任何问题都返回非零退出码）
python scripts/compression/validate_sft_quality.py --level l2 --strict
```

验证内容：
- 名字泄露检测（L2）：检查 me_names/other_names 是否正确替换
- 历史人物排除：确保"毛泽东"等公众人物不被误替换
- speaker 字段验证：确保只有 ME/OTHER/SYSTEM
- 数据完整性：检查空文本比例、类型分布等

### 7.4 PII 扫描（两阶段 PII 检测）

```bash
# 扫描时间轴数据，生成候选人名
python scripts/compression/two_stage_pii.py scan

# 人工审核候选人名
python scripts/compression/two_stage_pii.py review

# 查看确认的人名列表
cat configs/confirmed_names.yaml
```

---

## 8. 输出文件结构

```
timeline_out/
├── enriched_full.jsonl                    # 原始时间轴
├── enriched_full_processed.jsonl          # 后处理时间轴
├── enriched_full_anonymized_l1_sft.jsonl  # L1 字段精简
├── enriched_full_anonymized_l2.jsonl      # L2 匿名化
├── enriched_full_anonymized_l2_sft.jsonl  # L2 字段精简
├── agent_sft_l1.jsonl                     # L1 最终训练数据 ✅
├── agent_sft_l2.jsonl                     # L2 最终训练数据 ✅
├── id_mapping.jsonl                       # ID 映射表（调试用）
└── COMPRESSION_REPORT.md                  # 压缩报告
```

---

## 9. 故障排查

### 9.1 两阶段 PII 检测问题

**问题**：`[WARN] 确认人名列表不存在`

**解决**：
```bash
# 先运行扫描生成确认人名列表
python scripts/compression/two_stage_pii.py scan

# 人工审核
python scripts/compression/two_stage_pii.py review
```

### 9.2 名字泄露问题（2026-02-07 修复）

**问题**：用户名字（如"张三同学"）未被正确替换

**原因**：排除逻辑过于宽泛，"同学"在 exclude_patterns 中导致跳过替换

**解决**：已修复排除逻辑，只有当排除模式包含当前名字时才排除
- ✅ "张三同学" → "ME同学"（正确替换）
- ✅ "毛泽东传" → "毛泽东传"（正确保留）

### 9.2 时间描述被误识别为日期

**问题**：`[8天19小时后]` 被替换为 `[日期]`

**解决**：已在 `privacy_shield.py` 中添加跳过逻辑，`time_gap` 类型消息的 `text_raw` 字段不进行 PII 检测。

### 9.3 情绪词被误识别为地名

**问题**：`[开心/高兴]` 中的"开心"被识别为地名

**解决**：`sticker_summary` 和 `sticker_intent` 字段已从 PII 检测字段列表中移除。

---

## 10. 成功指标

| 指标 | 目标 | 实际 | 状态 |
|------|------|------|------|
| **Token 节省率** | ≥ 25% (L1), ≥ 30% (L2) | **77.71% (L1), 76.91% (L2)** | ✅ 远超目标 |
| **数据完整性** | 100% 保留语义字段 | **100%** | ✅ 达标 |
| **处理速度** | ≤ 5 分钟 | **< 1 分钟** | ✅ 超额完成 |
| **错误率** | ≤ 0.1% | **0%** | ✅ 完美 |

---

**文档版本**: v1.1  
**创建时间**: 2026-02-05  
**最后更新**: 2026-02-07
