# 个人信息占位符替换指南

## 概述

项目中的真实个人信息已被替换为占位符，新用户需要根据自己的实际情况进行替换。

## 需要替换的文件和占位符

### 1. `/configs/anonymization.yaml`

**占位符：**
- `YOUR_REAL_NAME` - 您的真实姓名
- `YOUR_NICKNAME` - 您的昵称
- `PARTNER_REAL_NAME` - 对方的真实姓名  
- `PARTNER_NICKNAME` - 对方的昵称

**替换示例：**
```yaml
me_names:
  - "张三"
  - "小三"

other_names:
  - "李四"
  - "四四"
```

### 2. `/configs/confirmed_names.yaml`

**占位符：**
- `[PHONE_NUMBER_1]` - 手机号码1
- `[PHONE_NUMBER_2]` - 手机号码2
- `[PHONE_NUMBER_3]` - 手机号码3

**替换示例：**
```yaml
- '[PHONE_NUMBER_1]
...
- 你好，XX，[PHONE_NUMBER_2]
...
- XXX [PHONE_NUMBER_3] 某某省某某市...
```

### 2. `/configs/confirmed_names.yaml`

**说明**：此文件由两阶段 PII 检测系统生成，用于高精度人名匿名化。

**处理方式**：
- **开源版本**：当前为模板文件，不含真实个人信息
- **使用方法**：运行以下命令生成确认列表：
  ```bash
  python scripts/compression/two_stage_pii.py scan timeline_out/agent_sft_l1.jsonl
  ```

**文件结构说明**：
```yaml
confirmed_names:
  # 真实姓名（会被匿名化）
  - text: "张三"
    category: real_name
    frequency: 5
    contexts:
    - '张三今天来找我讨论项目'
  
  # 常见词（不会被替换）
  - text: "大家"
    category: common
    frequency: 12
    contexts:
    - '大家都觉得这个方案不错'
```

**分类说明**：
- `real_name`：真实人名，L2 训练时会被替换为 `[PERSON_N]`
- `common`：常见词，不会被替换
- `uncertain`：不确定词汇，需要人工判断
- `pronoun`：代词，通常不替换

**模板内容**：
- 包含 5 类示例：真实人名、昵称、亲属称谓、常见词、不确定词汇
- 用户可根据自己的数据生成真实列表
- 如不使用，可忽略两阶段 PII 检测功能

### 3. `/docs/linkfile_pipeline_overview.md`

**占位符：**
- `[SERVER_ID]` - 服务器ID（可选替换）

**人工审核步骤**：
1. **运行扫描**：`python scripts/compression/two_stage_pii.py scan`
2. **查看候选词**：编辑生成的 `configs/confirmed_names.yaml`
3. **分类确认**：
   - 保留 `real_name`：确定是真实人名
   - 改为 `common`：常见词误判
   - 删除：明显错误的识别
4. **重新运行**：`python scripts/timeline/run_anonymization.py --level l2`

## 替换步骤

1. **备份原文件**
   ```bash
   cp configs/anonymization.yaml configs/anonymization.yaml.backup
   cp configs/confirmed_names.yaml configs/confirmed_names.yaml.backup
   ```

2. **编辑配置文件**
   ```bash
   # 使用您喜欢的编辑器
   vim configs/anonymization.yaml
   vim configs/confirmed_names.yaml
   ```

3. **验证替换**
   - 确保所有占位符都被替换为真实信息
   - 检查格式正确性（YAML语法）

## 注意事项

- **隐私保护**：这些信息仅用于本地训练（L1数据），L2云端训练数据会自动匿名化
- **格式要求**：姓名和手机号码请使用真实格式，避免影响数据处理
- **一致性**：确保在所有相关文件中保持信息一致

## 环境变量配置

如果需要配置API密钥等敏感信息，请创建：
```
local_secrets/.env.advisor
```

参考项目文档中的环境变量配置说明。

## 开源注意事项

### 已处理的敏感信息
- ✅ 手机号码已替换为 `[PHONE_NUMBER_X]` 占位符
- ✅ 真实姓名已替换为 `YOUR_*` 占位符
- ✅ `confirmed_names.yaml` 已替换为模板文件
- ✅ 绝对路径已替换为通用路径示例：`/path/to/data/root`, `/path/to/your/workspace`
- ✅ 具体地名映射已替换为通用示例：`"城市A": "城市B"`
- ✅ 示例邮箱和微信号已标准化：`example@domain.com`, `wxid_example123`
- ✅ API端点已添加注释说明为公开信息

### 两阶段 PII 检测
- **模板文件**：`configs/confirmed_names.yaml` 为开源模板
- **生成方法**：用户需运行扫描命令生成自己的确认列表
- **替代方案**：可使用基础 PII 检测（精度较低）

### 验证配置

配置完成后，可以运行以下命令验证：
```bash
python scripts/timeline/run_anonymization.py --level l1 --dry-run
```

确保个人信息正确识别和处理。
