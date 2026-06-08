# 反匿名化与 QLoRA 训练工程实践

> 📌 **本文档定位**：这是 [多模态处理流水线文档](modality_fields_and_models.md) Sections 13-14 的详细设计文档，专注于反匿名化数据工程和 16GB 显卡 QLoRA 训练的完整实践。

## 1. 设计理念

### 1.1 核心目标

训练一个能用真实姓名、真实日期、真实地名进行关系咨询的本地模型。上游 SFT 数据采用 L2 匿名化策略保护隐私，但训练时需要还原为真实信息（策略 B），使模型学习到自然的对话风格。

| 挑战 | 解决方案 |
|------|----------|
| L2 匿名化丢失真实语境 | 六层反匿名化映射还原 |
| 名称替换导致 OTHERHER Bug | 按长度降序排列替换列表 |
| 日期格式多样（`第X天`/ISO/月日） | 四种正则模式匹配 |
| 地名映射不完整 | 与 PII 扫描器同步 30+ 组映射 |
| 16GB 显存限制 | Unsloth 优化 + 4-bit NF4 量化 |
| 训练/推理策略选择 | A/B 对比实验 + 自动化评估 |

### 1.2 设计原则

```
┌─────────────────────────────────────────────────────────────────┐
│                      设计原则                                    │
├─────────────────────────────────────────────────────────────────┤
│  1. 完整还原：六层映射覆盖所有 PII 类型（姓名/地名/日期/Bug）  │
│  2. 递归处理：分析文本中嵌套引用的匿名标记也需反匿名           │
│  3. 防御性编程：替换前后字段数校验，异常回滚                    │
│  4. 数据隔离：train/val/test 分层抽样，day 分布一致             │
│  5. 显存安全：Unsloth 释放 38% 显存给更长序列                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. 六层反匿名化映射

### 2.1 整体流程

**核心脚本**: `scripts/advisor/run_all/_05c_deanonymize_training.py`

```
输入: advisor_training_neutral.jsonl (匿名化)
  │
  ├── 1. ME → 真实姓名 (anonymization.yaml)
  ├── 2. OTHER → 真实姓名 (anonymization.yaml)
  ├── 3. [PERSON_N] → 真实姓名 (identity_map.json, 34条)
  ├── 4. 映射地名 → 真实地名 (反向映射, 30+组)
  ├── 5. 第X天 → YYYY-MM-DD (基准日+偏移)
  └── 6. OTHERHER → 真实姓名 (全局修复)
  │
输出: advisor_training_neutral_deanon.jsonl (反匿名化)
```

### 2.2 各层映射详解

| 层级 | PII 类型 | 匿名格式 | 反匿名目标 | 映射来源 |
|------|----------|----------|------------|----------|
| **L1** | 用户姓名 | `ME` | 真实姓名 | `configs/anonymization.yaml` → `me_name` |
| **L2** | 对方姓名 | `OTHER` | 真实姓名 | `configs/anonymization.yaml` → `other_name` |
| **L3** | 第三方人名 | `[PERSON_1]`…`[PERSON_N]` | 真实姓名 | `configs/identity_map.json` (34 条映射) |
| **L4** | 地名 | 映射城市 | 真实地名 | `configs/anonymization.yaml` → `location_mapping` 反向 |
| **L5** | 日期 | `第X天 HH:MM` | `YYYY-MM-DD HH:MM` | 基准日 `2025-06-07` + (N-1) 天 |
| **L6** | 残留 Bug | `OTHERHER` | 对方姓名 | 硬编码替换 |

### 2.3 OTHERHER Bug 深度分析

**根因**: `privacy_shield.py` 的名称替换对"东东"这类重叠姓名进行了双重替换——先将"东东"替换为 `OTHER`，然后 `OTHER` 中的"东"又被匹配为"东东"的一部分，导致 `OTHERHER`。

**修复方案**:

```python
# privacy_shield.py 修复后的替换逻辑
def _replace_names(text, name_map):
    # 按名称长度降序排列，避免子串重叠
    sorted_names = sorted(name_map.items(), key=lambda x: len(x[0]), reverse=True)
    for real_name, anon_name in sorted_names:
        text = text.replace(real_name, anon_name)
    return text
```

同时对所有已生成数据执行全局 `OTHERHER → 真实姓名` 替换，确保无残留。

### 2.4 四种日期格式匹配

```python
# _05c_deanonymize_training.py
PATTERNS = [
    r'第(\d+)天\s*(\d{1,2}):(\d{2})',     # 第108天 14:30 → 2025-09-22 14:30
    r'第(\d+)天',                            # 第108天 → 2025-09-22
    r'Day\s*(\d+)\s*(\d{1,2}):(\d{2})',     # Day 108 14:30
    r'Day\s*(\d+)',                           # Day 108
]

BASE_DATE = datetime(2025, 6, 7)  # Day 1 = 2025-06-07
# Day N → 2025-06-07 + (N-1) 天

def _day_to_date(day_num: int) -> str:
    return (BASE_DATE + timedelta(days=day_num - 1)).strftime('%Y-%m-%d')
```

### 2.5 地名映射修复

**问题**: `configs/anonymization.yaml` 中的 `location_mapping` 最初仅有 5 组城市级映射，但 `llm_pii_scanner.py` 的 `LOCATION_MAPPING_TEMPLATE` 有 30+ 组省/市/区/国家映射。

**修复**: 同步补充到 `anonymization.yaml`：

```yaml
# configs/anonymization.yaml (修复后)
location_mapping:
  # 城市级
  上海: 杭州
  北京: 天津
  # 省级
  上海市: 杭州市
  浙江省: 江苏省
  # 区级
  浦东新区: 西湖区
  # 国际
  日本: 韩国
  # ... 共 30+ 组
```

### 2.6 递归嵌套反匿名

`analysis_text` 字段中包含多层嵌套引用（分析文本引用了对话原文中的匿名标记）。`--deanon-analysis` 模式对所有文本字段递归执行反匿名化：

```python
def deanonymize_recursive(obj, mapping):
    """递归遍历所有字符串字段，执行反匿名化"""
    if isinstance(obj, str):
        for anon, real in mapping.items():
            obj = obj.replace(anon, real)
        return obj
    elif isinstance(obj, dict):
        return {k: deanonymize_recursive(v, mapping) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [deanonymize_recursive(item, mapping) for item in obj]
    return obj
```

---

## 3. Formatter 13 字段完整性修复

### 3.1 问题

**核心文件**: `scripts/advisor/formatter.py`

`generate_review_markdown()` 和 `export_training_data()` 使用了错误的 key (`analysis_features` vs `analysis`)，导致部分字段丢失——约 40% 的 chunk 只有 8-10 个 `【】` 字段。

### 3.2 修复

```python
# formatter.py 修复
def export_training_data(item):
    # 修复前: features = item.get('analysis_features', {})  ← 错误 key
    # 修复后: 兼容两种 key
    features = item.get('analysis', item.get('analysis_features', {}))
```

新增 5 个多模态字段渲染：

| 字段 | 格式 | 来源 |
|------|------|------|
| 【时间模式】 | `time_patterns` | MoA 分析 |
| 【冲突根源】 | `conflict_root_causes` | MoA 分析 |
| 【多模态信号】 | `multimodal_signals` | Gemini 专家 |
| 【修复尝试】 | `repair_attempts` | MoA 分析 |
| 【人格动态】 | `personality_dynamics` | Claude 专家 |

**验证**: 修复后所有 chunks 均 ≥13 个 `【】` 字段。

---

## 4. 数据过滤与分层划分

### 4.1 过滤流程

**核心脚本**: `scripts/advisor/run_all/_05b_filter_split_training.py`

```
反匿名化训练数据
    │
    ├── 过滤: verdict != pass → 移除 (~3%)
    ├── 格式化: → messages 格式 (system + user + assistant)
    └── 分层划分: 80/10/10 按 day 分布分层抽样
    │
输出: splits_deanon/
    ├── train.jsonl  (80%)
    ├── val.jsonl    (10%)
    └── test.jsonl   (10%)
```

### 4.2 messages 格式

```json
{
  "messages": [
    {"role": "system", "content": "你是一位专业的关系心理顾问..."},
    {"role": "user", "content": "【对话片段】\n[2025-09-22 14:30] 东东: ..."},
    {"role": "assistant", "content": "【总体评估】...\n【关键问题】...\n【建议】..."}
  ]
}
```

---

## 5. QLoRA 训练工程实践

### 5.1 硬件约束

单卡 RTX 5070 Ti（16GB VRAM）需同时承担训练和推理。核心约束：

| 组件 | 显存占用 |
|------|----------|
| 8B 模型 4-bit 底座 | ~5 GB |
| LoRA 可训练参数 (87.3M) | ~0.3 GB |
| 优化器状态 (AdamW) | ~0.7 GB |
| 梯度 + 激活值缓存 | 随 seq_len 变化 |
| KV cache | 随 seq_len 变化 |

### 5.2 三策略对比

| 参数 | 策略 A (HF) | 策略 B (HF) | 策略 B (Unsloth) |
|------|------------|------------|-----------------|
| 基座 | Qwen3-8B-Instruct | Qwen3-8B-Instruct | Qwen3-8B-Instruct |
| 数据 | 匿名 (ME/OTHER) | 反匿名 (真实姓名) | 反匿名 (真实姓名) |
| LoRA r / α | 16 / 32 | 32 / 64 | 32 / 64 |
| 可训练参数 | 43.6M | 87.3M | 87.3M |
| 量化 | 4-bit NF4 | 4-bit NF4 | 4-bit NF4 |
| seq_len | 1536 | 1664 | **4096** |
| VRAM | ~14.5 GB | ~14.5 GB | **~8.9 GB** |
| 训练时长 | ~43 min | ~52 min | **~3h50m** |
| eval_loss (best) | 1.530 | 1.404 | **1.3696** |
| 推理字段完整率 | 93.9% | 100% | **100%** |
| ROUGE-L | 0.2705 | — | **0.2849** |

**结论**: 策略 B + Unsloth 为最佳配置（eval_loss 最低，字段完整率 100%）。

### 5.3 Unsloth 集成

**核心文件**: `scripts/advisor/run_all/_06_train_model.py`

Unsloth 通过手写 CUDA kernel 和内存优化实现显存节省：

```python
# _06_train_model.py --backend unsloth
from unsloth import FastLanguageModel

model, tokenizer = FastLanguageModel.from_pretrained(
    model_name="/data/models/Qwen3-8B-Instruct",
    max_seq_length=4096,
    dtype=None,       # auto-detect
    load_in_4bit=True,
)

model = FastLanguageModel.get_peft_model(
    model,
    r=32,
    lora_alpha=64,
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                     "gate_proj", "up_proj", "down_proj"],
    lora_dropout=0,
    bias="none",
)
```

**关键改动**:
- `--backend unsloth` CLI 选项切换到 Unsloth 后端
- 独立 conda 环境 `wechatDHA_unsloth`（Unsloth 与 HF transformers 版本冲突）
- `FastLanguageModel.from_pretrained()` 替代 `AutoModelForCausalLM`
- 训练命令需要 `HF_HUB_OFFLINE=1` 前缀

### 5.4 LoRA 参数调优

| 配置 | r | α | 可训练参数 | target_modules | eval_loss |
|------|---|---|-----------|---------------|-----------|
| 基线 | 16 | 32 | 43.6M | q/k/v/o/gate/up/down | 1.465 |
| **最优** | **32** | **64** | **87.3M** | q/k/v/o/gate/up/down | **1.3696** |
| 过拟合探索 | 64 | 128 | 174.6M | q/k/v/o/gate/up/down | 1.38 |

### 5.5 OOM 管理策略

```python
# _06_train_model.py 训练参数
training_args = TrainingArguments(
    per_device_train_batch_size=1,     # 最小 batch
    gradient_accumulation_steps=4,      # 等效 batch_size=4
    gradient_checkpointing=True,        # 用计算换显存
    bf16=True,                          # RTX 5070 Ti 支持
    max_steps=-1,
    num_train_epochs=5,
    learning_rate=2e-4,
    warmup_steps=10,
    save_strategy="epoch",
    eval_strategy="epoch",
    load_best_model_at_end=True,
    metric_for_best_model="eval_loss",
)

# 训练完成后即时释放
del model
del trainer
torch.cuda.empty_cache()
gc.collect()
```

### 5.6 评估结果

| 指标 | 目标 | 实际值 | 说明 |
|------|------|--------|------|
| eval_loss | < 1.5 | **1.3696** | epoch 4 checkpoint-204 |
| token_accuracy (train) | — | 69.7% | |
| token_accuracy (eval) | — | 67.9% | 无明显过拟合 |
| 推理字段完整率 | ≥ 90% | **100%** (≥13 字段) | 49 条 test set |
| 推理 ROUGE-L | > 0.2 | **0.2849** | 策略 B vs 参考 |
| PII 泄露 | 0 | **0** | 49 条 test 集检测 |
| 推理显存 | < 8 GB | **~5-6 GB** | 4-bit 底座 + LoRA |
| 推理平均字数 | — | 1910 chars | 比策略 A 更简洁 |

---

## 6. 函数参考

### 6.1 `_05c_deanonymize_training.py`

| 函数 | 参数 | 说明 |
|------|------|------|
| `build_reverse_mapping()` | anonymization_yaml | 构建反向映射表 |
| `deanonymize_text()` | text, mapping | 执行六层替换 |
| `deanonymize_recursive()` | obj, mapping | 递归反匿名化 |
| `convert_day_to_date()` | text, base_date | 四种日期格式转换 |
| `main()` | --input, --output, --deanon-analysis | CLI 入口 |

### 6.2 `_05b_filter_split_training.py`

| 函数 | 参数 | 说明 |
|------|------|------|
| `filter_by_verdict()` | items | 过滤非 pass 样本 |
| `format_messages()` | item, agent_type | 转为 messages 格式 |
| `stratified_split()` | items, ratios | 按 day 分布分层抽样 |

### 6.3 `_06_train_model.py`

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--agent-type` | neutral | Agent 类型 |
| `--backend` | hf | hf / unsloth |
| `--use-splits` | False | 使用预分割数据 |
| `--splits-dir` | — | 分割数据目录 |
| `--lora-r` | 32 | LoRA 秩 |
| `--lora-alpha` | 64 | LoRA 缩放因子 |
| `--max-seq-length` | 4096 | 最大序列长度 |
| `--epochs` | 5 | 训练轮数 |

### 6.4 `_07b_eval_compare.py`

| 函数 | 说明 |
|------|------|
| `run_inference()` | 批量推理 test set |
| `compute_rouge()` | ROUGE-L 计算 |
| `count_fields()` | 统计 `【】` 字段数 |
| `compare_strategies()` | A/B 对比报告生成 |

---

## 7. 运行命令

```bash
# 1. 反匿名化（含分析文本）
conda run -n wechatDHA python scripts/advisor/run_all/_05c_deanonymize_training.py \
  --input advisor_out/training/advisor_training_neutral.jsonl \
  --output advisor_out/training/advisor_training_neutral_deanon.jsonl \
  --deanon-analysis

# 2. 过滤 + 分割
conda run -n wechatDHA python scripts/advisor/run_all/_05b_filter_split_training.py \
  --input advisor_out/training/advisor_training_neutral_deanon.jsonl \
  --output-dir advisor_out/training/splits_deanon

# 3. 训练（Unsloth 后端）
HF_HUB_OFFLINE=1 conda run -n wechatDHA_unsloth python scripts/advisor/run_all/_06_train_model.py \
  --agent-type neutral --use-splits --splits-dir advisor_out/training/splits_deanon \
  --backend unsloth --lora-r 32 --lora-alpha 64 --max-seq-length 4096 --epochs 5

# 4. 评估
conda run -n wechatDHA python scripts/advisor/run_all/_07b_eval_compare.py \
  --model-a advisor_out/models/relationship_advisor_neutral/ \
  --model-b advisor_out/models/relationship_advisor_neutral_deanon_unsloth_r32/
```

---

**文档版本**: v1.0
**创建时间**: 2026-02-15
**关联主文档**: [modality_fields_and_models.md](modality_fields_and_models.md) Sections 13-14
**核心脚本**: `_05c_deanonymize_training.py`, `_05b_filter_split_training.py`, `_06_train_model.py`, `_07b_eval_compare.py`
