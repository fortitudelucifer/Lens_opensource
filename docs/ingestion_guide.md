# 归一化输入指南（Universal Ingestion Guide）

本文档说明如何使用归一化输入接口，将不同来源的聊天记录导入 CHAT_APP_DHA 项目。

归一化输入接口支持 5 种数据来源：

| 来源类型 | 标识 | 输入格式 |
|---------|------|---------|
| CHAT_APP | `CHAT_APP_html` | HTML + CSV 导出文件 |
| Telegram | `telegram_json` | JSON 导出文件（Telegram Desktop） |
| WhatsApp | `whatsapp_txt` | TXT 导出文件 |
| 通用 CSV | `generic_csv` | 任意 CSV，需配置字段映射 |
| 通用 JSONL | `generic_jsonl` | 任意 JSONL，需配置字段映射 |

---

## 快速开始

### 场景一：全新工作空间（推荐）

使用 `init_workspace.py` 一步完成目录创建 + 数据导入：

```bash
# ⚠️ 以下命令中的 "new_chat" 是占位符，请替换为你的实际工作空间名称
#    例如：素材文件夹叫 lwq，就把所有 new_chat 替换为 lwq

# 1. 将原始素材文件夹放到项目目录下
cp -r ~/new_chat /data/CHAT_APP_DHA/new_chat        # ← 替换 new_chat 为你的文件夹名

# 2. 从模板工作空间复制 scripts（init_workspace.py 在 scripts/ 里，必须先有）
cp -r /data/CHAT_APP_DHA/lwy/scripts /data/CHAT_APP_DHA/new_chat/scripts  # ← 同上

# 3. 运行初始化（自动检测来源类型）
cd /data/CHAT_APP_DHA/new_chat                       # ← 同上
python scripts/workspace/init_workspace.py --contact-name "联系人名"  # ← 替换为对方真实名字

# 预览模式（不执行实际操作）
python scripts/workspace/init_workspace.py --dry-run --contact-name "联系人名"

# 或指定来源类型
python scripts/workspace/init_workspace.py --source-type CHAT_APP_html --contact-name "联系人名"
```

`init_workspace.py` 会自动执行：
1. 创建标准目录结构（`raw/`, `artifacts/`, `timeline_out/` 等）
2. 迁移原始文件到 `raw/` 目录（HTML/CSV → `raw/export/`，媒体 → `raw/image/` 等）
3. 从模板工作空间复制配置文件
4. 生成 `source_manifest.yaml` 并运行归一化转换 → 生成 `raw/P1_messages_raw.jsonl`
5. 清理根目录下的旧文件夹

初始化完成后，手动更新以下配置：
- `configs/anonymization.yaml` — 填入双方真实名字和昵称
- `configs/hotword.txt` — 填入 ASR 热词（双方名字）
- 确认 `configs/paths.yaml` 中 `workspace_name` 正确

### 场景二：已有工作空间，重新导入数据

使用 `run_ingest.py` 独立运行：

```bash
# ⚠️ "new_chat" 是占位符，替换为你的实际工作空间名称（例如 lwq）

# 1. 编辑 raw/source_manifest.yaml（见下方配置说明）
# 2. 预检
python scripts/workspace/run_ingest.py --workspace new_chat --dry-run  # ← 替换 new_chat

# 3. 执行转换
python scripts/workspace/run_ingest.py --workspace new_chat            # ← 同上
```

---

## source_manifest.yaml 配置

每个工作空间的 `raw/source_manifest.yaml` 定义了数据来源和转换规则。

### 生成模板

```bash
# ⚠️ "new_chat" 是占位符，替换为你的实际工作空间名称（例如 lwq）
python scripts/workspace/run_ingest.py --init-manifest --source-type telegram_json --workspace new_chat  # ← 替换 new_chat
```

模板会写入 `{workspace}/raw/source_manifest.yaml`。

### 基本结构

```yaml
# [必填] 来源类型
source_type: CHAT_APP_html

# [必填] 输入文件路径（相对于 raw/ 目录）
input_paths:
  - ./export.html

# [可选] 参与者映射
participant_map:
  "CONTACT_NAME": "ME"
  "CONTACT_NAME_B": "OTHER"

# [可选] 时区（默认 Asia/Shanghai）
timezone: Asia/Shanghai

# [可选] 媒体文件基础目录
# media_base_dir: ./media
```

---

## 各来源类型配置示例

### CHAT_APP（CHAT_APP_html）

```yaml
source_type: CHAT_APP_html
input_paths:
  - ./export/联系人.html
participant_map:
  "我的昵称": "ME"
  "对方昵称": "OTHER"
timezone: Asia/Shanghai
```

CHAT_APP适配器会自动：
- 解析 HTML 中的消息记录
- 如果同目录下有同名 CSV 文件，自动补充元数据（MsgSvrID、token 等）
- 识别媒体文件路径（image/、voice/、video/ 等）

### Telegram（telegram_json）

```yaml
source_type: telegram_json
input_paths:
  - ./result.json
participant_map:
  "My Name": "ME"
  "Friend": "OTHER"
timezone: Asia/Shanghai
```

Telegram Desktop 导出时选择 JSON 格式，导出文件通常为 `result.json`。

### WhatsApp（whatsapp_txt）

```yaml
source_type: whatsapp_txt
input_paths:
  - ./chat.txt
participant_map:
  "+86 138xxxx1234": "ME"
  "+86 139xxxx5678": "OTHER"
timezone: Asia/Shanghai
```

WhatsApp 导出的 TXT 文件格式为每行一条消息，包含时间戳和发送者。

### 通用 CSV（generic_csv）

```yaml
source_type: generic_csv
input_paths:
  - ./data.csv
participant_map:
  "Alice": "ME"
  "Bob": "OTHER"
timezone: Asia/Shanghai

field_mapping:
  timestamp: ts
  sender_name: speaker
  content: text_raw
  msg_type: type
  _const:text: modality
  _const:GEN: _source_prefix
  _default:0: sub_type
```

### 通用 JSONL（generic_jsonl）

```yaml
source_type: generic_jsonl
input_paths:
  - ./data.jsonl
participant_map:
  "Alice": "ME"
  "Bob": "OTHER"

field_mapping:
  timestamp: ts
  sender: speaker
  message: text_raw
  _const:text: modality
  _const:GEN: _source_prefix
```

---

## 字段映射语法（field_mapping）

通用适配器（`generic_csv` / `generic_jsonl`）需要通过 `field_mapping` 告诉系统如何将源字段映射到标准 Schema。

| 语法 | 说明 | 示例 |
|------|------|------|
| `source: target` | 直接映射 | `timestamp: ts` |
| `_const:value: target` | 常量值（所有记录使用此值） | `_const:text: modality` |
| `_default:value: target` | 默认值（仅源字段缺失时使用） | `_default:0: sub_type` |

标准 Schema 的必填字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `ts` | int | Unix 时间戳（秒） |
| `speaker` | str | 发送者（ME / OTHER） |
| `type` | int | 消息类型码 |
| `modality` | str | 模态类型（text/image/voice/video/sticker） |
| `text_raw` | str | 原始文本内容 |

---

## CLI 参考

### run_ingest.py

```bash
# ⚠️ <name> 是占位符，替换为你的实际工作空间名称（例如 lwq）

# 完整转换
python scripts/workspace/run_ingest.py --workspace <name>

# 预检模式（扫描前 N 条记录，生成覆盖率报告）
python scripts/workspace/run_ingest.py --workspace <name> --dry-run

# 查看标准 Schema 字段说明
python scripts/workspace/run_ingest.py --show-schema

# 列出所有已注册适配器
python scripts/workspace/run_ingest.py --show-adapters

# 查看指定适配器详情
python scripts/workspace/run_ingest.py --show-adapters --source-type telegram_json

# 生成 manifest 模板
python scripts/workspace/run_ingest.py --init-manifest --source-type telegram_json --workspace <name>
```

### init_workspace.py 新增参数

| 参数 | 说明 |
|------|------|
| `--source-type` | 指定来源类型（不指定则自动检测） |
| `--skip-ingest` | 跳过归一化导入步骤 |
| `--ingest-dry-run` | 仅预检归一化，不执行实际转换 |

---

## 导入后的操作

归一化完成后，`raw/P1_messages_raw.jsonl` 已生成，可以直接运行后续流水线：

```bash
# 一键运行所有模态流水线
python run_all_pipelines.py

# 或按模态分步运行
python run_all_pipelines.py --only image
python run_all_pipelines.py --only voice
python run_all_pipelines.py --only video sticker
```

详细的流水线说明参见 [pipeline.md](pipeline.md)。

---

## 常见问题

### Q: 预检报告显示必填字段覆盖率不足？

检查 `source_manifest.yaml` 中的 `field_mapping` 是否正确映射了所有必填字段。使用 `--show-schema` 查看完整字段列表。

### Q: 媒体文件没有被正确复制？

确认 `media_base_dir` 配置正确，或者媒体文件路径相对于输入文件所在目录是可访问的。

### Q: 如何处理群聊数据？

在 `participant_map` 中为每个群成员指定映射：

```yaml
participant_map:
  "我": "ME"
  "群友A": "OTHER:群友A"
  "群友B": "OTHER:群友B"
```

### Q: 如何添加新的数据来源适配器？

在 `scripts/workspace/ingestion/adapters/` 目录下创建新的 Python 文件，继承 `BaseAdapter` 基类并实现 `parse()` 方法。适配器会被自动发现和注册。

---

*文档更新于: 2026-02-13*
