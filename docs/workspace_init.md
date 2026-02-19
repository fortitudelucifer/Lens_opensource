# 工作空间初始化指南

本文档说明如何从CHAT_APP导出的原始材料库创建一个符合 CHAT_APP_DHA 项目结构的新工作空间。

## 原始材料库结构

CHAT_APP导出工具通常会生成以下目录结构：

```
{联系人名}/
├── {联系人名}.html          # HTML 导出文件（核心数据源）
├── {联系人名}.csv           # CSV 导出文件
├── {联系人名}.md            # Markdown 导出文件
├── avatar/                  # 头像文件
├── emoji/                   # 表情包文件
├── file/                    # 文件传输
├── icon/                    # 图标文件
├── image/                   # 图片文件（可能按月份分类）
│   ├── 2025-06/
│   ├── 2025-07/
│   └── ...
├── music/                   # 音乐文件
├── video/                   # 视频文件（可能按月份分类）
│   ├── 2025-07/
│   └── ...
└── voice/                   # 语音消息
```

## 目标项目结构

CHAT_APP_DHA 项目要求的标准结构：

```
{workspace_name}/
├── .kiro/                   # Kiro 配置
│   ├── specs/               # 功能规格文档
│   └── steering/            # 项目指导文档
│       ├── behavior.md
│       ├── product.md
│       ├── structure.md
│       └── tech.md
├── raw/                     # 原始数据（迁移后）
│   ├── export/              # 导出文件
│   ├── image/               # 图片
│   ├── voice/               # 语音
│   ├── video/               # 视频
│   ├── sticker/             # 表情包
│   ├── file/                # 文件传输
│   ├── avatar/              # 头像
│   ├── emoji/               # 原始表情包
│   ├── icon/                # 图标
│   └── music/               # 音乐
├── artifacts/               # 处理中间产物
│   ├── before_merge/
│   │   ├── image/
│   │   ├── voice/
│   │   ├── video/
│   │   ├── sticker/
│   │   │   ├── thumbs/      # 缩略图
│   │   │   └── frames/      # Contact Sheet
│   │   └── linkfile/
│   └── after_merge/
│       ├── image/
│       ├── voice/
│       ├── video/
│       └── sticker/
├── timeline_out/            # 最终输出
├── configs/                 # 配置文件
├── scripts/                 # 处理脚本
├── docs/                    # 文档
├── logs/                    # 日志
└── tests/                   # 测试文件
```

## 初始化步骤

### 方法一：使用初始化脚本（推荐）

```bash
# 1. 将原始材料库放到 /data/CHAT_APP_DHA/{workspace_name}/
# 2. 运行初始化脚本
cd /data/CHAT_APP_DHA/{workspace_name}
python scripts/workspace/init_workspace.py --dry-run  # 预览
python scripts/workspace/init_workspace.py            # 执行
```

### 方法二：手动初始化

1. **创建目录结构**
```bash
mkdir -p raw/{export,image,voice,video,sticker,file,avatar,emoji,icon,music}
mkdir -p artifacts/before_merge/{image,voice,video,sticker,linkfile}
mkdir -p artifacts/before_merge/sticker/{thumbs,frames}
mkdir -p artifacts/after_merge/{image,voice,video,sticker}
mkdir -p timeline_out configs docs logs tests/{manual_images,manual_videos}
mkdir -p .kiro/{specs,steering}
```

2. **迁移原始文件**
```bash
# 导出文件
mv *.html *.csv *.md raw/export/

# 媒体文件
mv image/* raw/image/
mv voice/* raw/voice/
mv video/* raw/video/
mv file/* raw/file/
mv avatar/* raw/avatar/
mv emoji/* raw/emoji/
mv icon/* raw/icon/
mv music/* raw/music/

# 表情包（emoji 复制到 sticker）
cp raw/emoji/* raw/sticker/
```

3. **复制配置和脚本**
```bash
# 从模板工作空间复制（真实文件，非软链接）
cp -r ../demo/scripts .
cp ../demo/configs/*.yaml configs/
cp -r ../demo/.kiro/steering .kiro/
cp -r ../demo/docs .
```

**重要提示**：
- 所有文件必须是真实文件，不能使用软链接
- 这样可以确保工作空间完全独立，可以独立运行
- 每个工作空间都有自己的完整脚本和配置副本

4. **更新工作空间特定配置**

编辑 `configs/paths.yaml`：
```yaml
workspace_name: demo
```

编辑 `configs/anonymization.yaml`：
```yaml
me_names:
  - "你的真名"
  - "你的昵称"
other_names:
  - "对方真名"
  - "对方昵称"
```

编辑 `configs/hotword.txt`：
```
对方真名
你的真名
```

5. **清理旧目录**
```bash
rm -rf avatar emoji icon music file voice image video
rm -f *.html *.csv *.md
```

## 初始化后的操作

### 1. 提取消息数据

```bash
# 从 HTML+CSV 提取消息到 P1_messages_raw.jsonl
python scripts/extract/extract_html_to_jsonl.py

# 可选参数：
python scripts/extract/extract_html_to_jsonl.py --dry-run     # 仅分析不写入
python scripts/extract/extract_html_to_jsonl.py --no-csv      # 不使用 CSV 补充元数据
python scripts/extract/extract_html_to_jsonl.py --me-names "UserA,MyNickName"  # 指定我的名称
```

### P1_messages_raw.jsonl 输出字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| seq_in_html | int | HTML 中的消息序号（从 0 开始） |
| msg_uid | str | 消息唯一标识符，格式 `P1:{MsgSvrID}` |
| MsgSvrID | str | 服务器消息ID |
| token | str | 消息 token |
| ts | int | Unix 时间戳 |
| time_local | str | 本地时间字符串 (YYYY-MM-DD HH:MM:SS) |
| speaker | str | 发送者 (ME/OTHER) |
| type | int | 消息类型 |
| sub_type | int | 子类型 |
| modality | str | 模态类型 |
| text_raw | str | 原始文本内容 |
| media_path | str | 媒体文件路径 |
| voice_length | int | 语音时长（毫秒） |
| voice_to_text | str | 语音转文字 |

**消息类型 (type) 说明：**
- 1: 文本 (text)
- 3: 图片 (image)
- 34: 语音 (voice)
- 43: 视频 (video)
- 47: 表情包 (sticker)
- 48: 位置 (location)
- 42: 名片 (contact)
- 49: 复合消息 (link_or_file)
- 0/10000: 系统消息 (system)

**type=49 的 sub_type 说明：**
- 5: 链接分享
- 6: 文件传输
- 19: 合并转发
- 33/36: 小程序
- 51: 视频号
- 57: 引用/回复

**引用消息 (sub_type=57) 额外字段：**
- quote_svrid: 引用消息的 MsgSvrID
- quote_type: 引用消息的类型
- quote_text: 引用消息的文本

### 2. 运行各模态流水线
```bash
# 图片流水线
python scripts/image/run_all/_01_run_ocr.py
python scripts/image/run_all/_02_run_caption.py
# ...

# 语音流水线
python scripts/voice/run_all/_01_run_funasr.py
# ...
```

## 注意事项

- 确保 `workspace_name` 与目录名一致
- 更新 `anonymization.yaml` 中的名字映射
- 模型路径 `/data/models/` 和缓存路径 `/data/cache/` 是全局共享的
- 每次开新终端务必 `conda activate CHAT_APP_DHA`
