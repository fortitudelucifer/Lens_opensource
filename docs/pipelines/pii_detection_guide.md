# PII 检测使用指南

> 📌 **本文档定位**：这是 [多模态处理流水线文档](modality_fields_and_models.md) 的详细实现指南，专注于 PII 检测的代码示例、配置管理和故障排查。

## 流程图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        两阶段 PII 检测架构                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   ┌──────────────────────────────────────────────────────────────────────┐  │
│   │                      Layer 1: 规则引擎                                │  │
│   │  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐     │  │
│   │  │ 正则匹配   │  │ 配置映射   │  │ 排除列表   │  │ 快速检测   │     │  │
│   │  │ 手机/邮箱  │  │ me_names   │  │ 公众人物   │  │ <1ms/文本  │     │  │
│   │  │ 身份证/微信│  │ other_names│  │ 历史人物   │  │ 置信度 1.0 │     │  │
│   │  └────────────┘  └────────────┘  └────────────┘  └────────────┘     │  │
│   └──────────────────────────────────────────────────────────────────────┘  │
│                                    │                                         │
│                                    ▼                                         │
│   ┌──────────────────────────────────────────────────────────────────────┐  │
│   │                 两阶段 PII 检测（推荐）                               │  │
│   │                                                                       │  │
│   │   Phase 1: 离线扫描                    Phase 2: 匿名化时              │  │
│   │   ┌────────────────────────┐          ┌────────────────────────┐     │  │
│   │   │                        │          │                        │     │  │
│   │   │  ┌──────────────────┐  │          │  ┌──────────────────┐  │     │  │
│   │   │  │ 候选词提取       │  │          │  │ 加载确认列表     │  │     │  │
│   │   │  │ (规则 + 启发式)  │  │          │  │ confirmed_names  │  │     │  │
│   │   │  └────────┬─────────┘  │          │  └────────┬─────────┘  │     │  │
│   │   │           │            │          │           │            │     │  │
│   │   │           ▼            │          │           ▼            │     │  │
│   │   │  ┌──────────────────┐  │          │  ┌──────────────────┐  │     │  │
│   │   │  │ LLM 验证         │  │          │  │ 精确字符串匹配   │  │     │  │
│   │   │  │ Qwen2.5-7B-AWQ   │  │   ───▶   │  │ 无漏检           │  │     │  │
│   │   │  │ (~4GB 显存)      │  │          │  │ 高性能           │  │     │  │
│   │   │  └────────┬─────────┘  │          │  └────────┬─────────┘  │     │  │
│   │   │           │            │          │           │            │     │  │
│   │   │           ▼            │          │           ▼            │     │  │
│   │   │  ┌──────────────────┐  │          │  ┌──────────────────┐  │     │  │
│   │   │  │ 人工审核         │  │          │  │ 替换为占位符     │  │     │  │
│   │   │  │ 确认/排除人名    │  │          │  │ ME/OTHER/[PERSON]│  │     │  │
│   │   │  └──────────────────┘  │          │  └──────────────────┘  │     │  │
│   │   │                        │          │                        │     │  │
│   │   └────────────────────────┘          └────────────────────────┘     │  │
│   │                                                                       │  │
│   └──────────────────────────────────────────────────────────────────────┘  │
│                                                                              │ 
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## 概述

本系统实现了两层 PII（个人身份信息）检测架构：

1. **规则引擎**：正则表达式 + 配置映射（电话、邮箱、身份证等）
2. **两阶段 PII 检测**（推荐）：高精度人名检测

## 快速开始

### 1. 基本使用（规则引擎）

```python
from scripts.compression.pii_detector import PIIDetector

# 创建检测器
detector = PIIDetector()

# 检测 PII
text = "我的电话是13812345678，邮箱是test@example.com"
matches = detector.detect(text)

# 查看结果
for match in matches:
    print(f"[{match.source}] {match.type}: '{match.value}'")

# 输出:
# [regex] PHONE: '13812345678'
# [regex] EMAIL: 'test@example.com'
```

### 2. 两阶段 PII 检测（推荐）

```bash
# Phase 1: 扫描并生成候选人名
python scripts/compression/two_stage_pii.py scan

# 人工审核确认人名列表
# 编辑 configs/confirmed_names.yaml

# Phase 2: 匿名化时自动使用确认列表
python scripts/timeline/run_anonymization.py --level l2
```

### 3. 集成到匿名化流程

```python
from scripts.compression.privacy_shield import PrivacyShield

# 推荐：使用两阶段 PII 检测
shield = PrivacyShield(use_two_stage_pii=True)

# L1 匿名化（本地训练用）
message = {
    'text_raw': '我的电话是13812345678',
    'ts': 1752503924
}

anonymized = shield.anonymize_l1(message)
print(anonymized['text_raw'])
# 输出: 我的电话是[电话号码]

# L2 匿名化（云端训练用）
shield.set_base_timestamp(1752417524)
anonymized_l2 = shield.anonymize_l2(message)
```

## 检测架构

### Layer 1: 规则引擎（正则 + 配置映射）

**特点**：
- 快速（<1ms/文本）
- 确定性（置信度 1.0）
- 无显存占用

**检测类型**：
- 手机号：`1[3-9]\d{9}`
- 邮箱：`[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}`
- 身份证号：`\d{17}[\dXx]`
- 微信ID：`wxid_[a-zA-Z0-9]+`
- 日期：`(?:19|20)\d{2}[-/年]\d{1,2}[-/月]\d{1,2}[日号]?`
- 已知人名、地名（从配置加载）

### 两阶段 PII 检测（推荐）

**架构**：
- Phase 1: 候选词提取 + LLM 验证（离线扫描，生成确认人名列表）
- Phase 2: 精确字符串匹配（匿名化时使用确认列表）

**模型**：`Qwen2.5-7B-Instruct-AWQ`（~4GB 显存）

**优势**：
- 人工审核环节，避免误检
- 精确匹配，无漏检
- 支持增量更新

**使用**：
```bash
# 扫描并生成候选人名
python scripts/compression/two_stage_pii.py scan

# 人工审核
python scripts/compression/two_stage_pii.py review

# 匿名化时自动使用确认列表
python scripts/timeline/run_anonymization.py --level l2
```

**配置**：
```yaml
two_stage_pii:
  enabled: true
  confirmed_names_path: "configs/confirmed_names.yaml"
  phase1:
    model:
      path: "/data/models/Qwen2.5-7B-Instruct-AWQ"
```

### GLiNER（已废弃）

> ⚠️ **注意**：GLiNER 已于 2026-02-06 废弃，因中文误检率高，需要大量排除列表维护。请使用两阶段 PII 检测系统替代。

## 配置管理

### 1. 添加已知实体

编辑 `configs/anonymization.yaml`：

```yaml
# 人名
me_names:
  - "王小明"
  - "小明"

other_names:
  - "UserB"
  - "NickNameB"

# 地名
location_mapping:
  "北京": "天津"
  "上海": "杭州"

# 排除列表（公众人物、历史人物等）
exclude_patterns:
  - "毛泽东"
  - "李白"
  - "杜甫"
```

### 2. 确认人名列表

编辑 `configs/confirmed_names.yaml`：

```yaml
# 两阶段 PII 检测确认的人名
confirmed_names:
  ME:
    - "[NAME]"
    - "[NAME]"
  OTHER:
    - "[NAME]"
    - "[NAME]"
```

## 测试和验证

### 1. 运行单元测试

```bash
# 运行所有测试
pytest tests/test_pii_detector.py -v

# 运行两阶段 PII 测试
pytest tests/test_two_stage_pii_models.py -v
```

### 2. 手动测试

```python
# 测试规则引擎
python scripts/compression/pii_detector.py

# 测试 PrivacyShield
python scripts/compression/privacy_shield.py
```

## 跳过检测的字段/消息类型

为避免误检测，以下字段或消息类型会跳过 PII 检测：

| 字段/类型 | 原因 |
|-----------|------|
| `sticker_summary` | 包含情绪描述词 |
| `sticker_intent` | 情绪意图描述 |
| `time_gap` 的 `text_raw` | 时间描述会被误识别 |

## 最佳实践

1. **新数据集**：先运行 `two_stage_pii.py scan` 生成确认人名列表
2. **配置优先**：对于频繁出现的实体，添加到配置映射
3. **定期审查**：定期运行 PII 扫描，更新配置

## 参考资料

- [两阶段 PII 检测脚本](../scripts/compression/two_stage_pii.py)
- [测试用例](../tests/test_pii_detector.py)
- [配置文件](../configs/compression.yaml)
