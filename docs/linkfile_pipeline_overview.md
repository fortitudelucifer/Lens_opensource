# Linkfile 流水线设计概览

> 📌 **本文档定位**：这是 [多模态处理流水线文档](modality_fields_and_models.md) 的详细设计文档，专注于 Linkfile 流水线的 Handler 模式、扩展指南和实际案例。

## 1. 设计理念

### 1.1 核心目标

Linkfile 流水线处理CHAT_APP聊天记录中 `type=49` 的消息，这类消息包含多种子类型：

| sub_type | 类型名称 | 说明 |
|----------|----------|------|
| 57 | quote | 引用消息（回复某条消息） |
| 5 | link | 链接分享（网页链接） |
| 6 | file | 文件传输（PDF、ZIP 等） |
| 33, 36 | miniprogram | 小程序分享 |
| 51 | video_channel | 视频号分享 |
| 19 | chat_history | 聊天记录转发 |

### 1.2 设计原则

```
┌─────────────────────────────────────────────────────────────────┐
│                      设计原则                                    │
├─────────────────────────────────────────────────────────────────┤
│  1. 统一处理：所有 sub_type 在同一流水线中处理                    │
│  2. 策略模式：通过路由分发到对应处理器（Handler）                 │
│  3. Schema 兼容：输出符合 merged_v2 Schema                       │
│  4. 轻量级：纯 CPU 处理，无需 GPU 模型                           │
│  5. 三阶段架构：提取 → 合并 → 更新时间轴                         │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. 架构设计

### 2.1 三阶段流水线

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        Linkfile Pipeline                                 │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│   ┌──────────────────┐   ┌──────────────────┐   ┌──────────────────┐    │
│   │     Step 1       │   │     Step 2       │   │     Step 3       │    │
│   │     Extract      │──▶│     Merge        │──▶│    Timeline      │    │
│   │   & Anonymize    │   │     Engine       │   │     Update       │    │
│   └──────────────────┘   └──────────────────┘   └──────────────────┘    │
│           │                      │                      │               │
│           ▼                      ▼                      ▼               │
│   linkfile_extract       linkfile_merged        enriched_full.jsonl    │
│   _v1.jsonl              _final.jsonl           enriched_slim.jsonl    │
│                                                                          │
│   artifacts/before_merge  artifacts/after_merge   timeline_out/         │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.2 数据流详解

```
raw/P1_messages_raw.jsonl (type=49 消息)
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│  _01_extract_and_anonymize.py                                    │
│  ├─ 加载 P1_messages_raw.jsonl                                   │
│  ├─ 过滤 type=49 消息                                            │
│  ├─ 从 HTML 解析引用信息（quote_svrid, quote_text 等）           │
│  ├─ 路由到子类型处理器 (Handler Pattern)                         │
│  │   ├─ QuoteHandler (sub_type=57)                               │
│  │   ├─ LinkHandler (sub_type=5)                                 │
│  │   ├─ FileHandler (sub_type=6)                                 │
│  │   ├─ MiniprogramHandler (sub_type=33,36)                      │
│  │   ├─ VideoChannelHandler (sub_type=51)                        │
│  │   └─ ChatHistoryHandler (sub_type=19)                         │
│  └─ 输出 linkfile_extract_v1.jsonl                               │
└─────────────────────────────────────────────────────────────────┘
         │
         ▼
artifacts/before_merge/linkfile/linkfile_extract_v1.jsonl
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│  _02_merge_engine.py                                             │
│  ├─ 加载 linkfile_extract_v1.jsonl                               │
│  ├─ 添加 schema_version = "merged_v2"                            │
│  ├─ 使用 reorder_record() 重排字段顺序                           │
│  │   ├─ COMMON_HEADER_FIELDS（公共字段在前）                     │
│  │   └─ LINKFILE_SPECIFIC_FIELDS（特定字段在后）                 │
│  └─ 输出 linkfile_merged_final.jsonl                             │
└─────────────────────────────────────────────────────────────────┘
         │
         ▼
artifacts/after_merge/linkfile/linkfile_merged_final.jsonl
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│  _03_update_timeline.py                                          │
│  ├─ 加载 linkfile_merged_final.jsonl                             │
│  ├─ 加载 enriched_full.jsonl / enriched_slim.jsonl               │
│  ├─ 按 msg_uid 匹配并更新时间轴记录                              │
│  ├─ 根据 link_sub_type 添加对应的 link_ 前缀字段                 │
│  └─ 输出更新后的时间轴                                           │
└─────────────────────────────────────────────────────────────────┘
         │
         ▼
timeline_out/enriched_full.jsonl
timeline_out/enriched_slim.jsonl
```

---

## 3. 策略模式（Handler Pattern）

### 3.1 类图

```
                    ┌─────────────────────────┐
                    │   SubTypeHandler        │
                    │   (Abstract Base)       │
                    ├─────────────────────────┤
                    │ + sub_types: List[int]  │
                    │ + link_sub_type: str    │
                    │ + extract(msg, lookup)  │
                    └───────────┬─────────────┘
                                │
        ┌───────────────────────┼───────────────────────┐
        │           │           │           │           │
        ▼           ▼           ▼           ▼           ▼
┌───────────┐ ┌───────────┐ ┌───────────┐ ┌───────────┐ ┌───────────┐
│ Quote     │ │ Link      │ │ File      │ │Miniprogram│ │ Content   │
│ Handler   │ │ Handler   │ │ Handler   │ │ Handler   │ │ Handler   │
├───────────┤ ├───────────┤ ├───────────┤ ├───────────┤ ├───────────┤
│sub_type=57│ │sub_type=5 │ │sub_type=6 │ │sub_type=  │ │sub_type=  │
│           │ │           │ │           │ │ 33, 36    │ │ 19, 51    │
└───────────┘ └───────────┘ └───────────┘ └───────────┘ └───────────┘
```

### 3.2 抽象基类定义

```python
# scripts/linkfile/handlers/base.py

class SubTypeHandler(ABC):
    """子类型处理器抽象基类"""
    
    @property
    @abstractmethod
    def sub_types(self) -> List[int]:
        """返回此处理器支持的 sub_type 列表"""
        pass
    
    @property
    @abstractmethod
    def link_sub_type(self) -> str:
        """返回统一的 link_sub_type 值"""
        pass
    
    @abstractmethod
    def extract(self, msg: Dict, html_quote_lookup: Dict) -> Dict:
        """从消息中提取特定字段"""
        pass
```

### 3.3 路由机制

```python
# scripts/linkfile/extractor.py

class LinkfileExtractor:
    """主提取器 - 负责路由到对应处理器"""
    
    def __init__(self, config, workspace_root):
        self.handlers: Dict[int, SubTypeHandler] = {}
        self._register_handlers()
    
    def _register_handlers(self):
        """注册所有子类型处理器"""
        handlers = [
            QuoteHandler(),
            LinkHandler(self.config.get('link_type_rules', [])),
            FileHandler(self.config.get('file_categories', {}), self.workspace_root),
            MiniprogramHandler(self.config.get('miniprogram_apps', {})),
            VideoChannelHandler(),
            ChatHistoryHandler(),
        ]
        for handler in handlers:
            for sub_type in handler.sub_types:
                self.handlers[sub_type] = handler  # sub_type -> handler 映射
    
    def _extract_one(self, msg, html_quote_lookup):
        """处理单条消息"""
        sub_type = msg.get('sub_type')
        handler = self.handlers.get(sub_type)
        
        if handler is None:
            return {'link_sub_type': 'unknown', ...}  # 未知类型
        
        return handler.extract(msg, html_quote_lookup)  # 委托给具体处理器
```

---

## 4. 各子类型处理器详解

### 4.1 QuoteHandler（引用消息）

**功能**：处理 `sub_type=57` 的引用消息，提取被引用消息的元数据

**输出字段**：
| 字段 | 类型 | 说明 |
|------|------|------|
| link_sub_type | str | 固定为 "quote" |
| quote_svrid | str | 被引用消息的 MsgSvrID |
| quote_type | int | 被引用消息的类型 |
| quote_text | str | 被引用消息的文本（已匿名化） |

**匿名化处理**：
```python
# 原始文本: "UserB：你好啊"
# 匿名化后: "OTHER: 你好啊"

# 原始文本: "我自己：收到"
# 匿名化后: "ME: 收到"
```

**示例输出**：
```json
{
  "link_sub_type": "quote",
  "quote_svrid": "9876543210",
  "quote_type": 1,
  "quote_text": "OTHER: 原始消息内容"
}
```

---

### 4.2 LinkHandler（链接分享）

**功能**：处理 `sub_type=5` 的链接分享，提取 URL 并分类

**输出字段**：
| 字段 | 类型 | 说明 |
|------|------|------|
| link_sub_type | str | 固定为 "link" |
| link_url | str | 链接 URL |
| link_title | str | 链接标题 |
| link_type | str | 链接类型分类 |

**链接类型分类规则**（来自 `configs/linkfile.yaml`）：
| URL 模式 | link_type | 说明 |
|----------|-----------|------|
| mp.weixin.qq.com | CHAT_APP_article | CHAT_APP公众号文章 |
| bilibili.com | bilibili_video | B站视频 |
| meishi.meituan.com | meituan_poi | 美团餐厅 |
| dianping.com | dianping_poi | 大众点评 |
| music.163.com | netease_music | 网易云音乐 |
| y.qq.com | qq_music | QQ音乐 |
| douyin.com | douyin_video | 抖音视频 |
| zhihu.com | zhihu_article | 知乎 |
| weibo.com | weibo_post | 微博 |
| surl.amap.com | map_location | 高德地图位置 |
| * (默认) | web_link | 普通网页链接 |

**示例输出**：
```json
{
  "link_sub_type": "link",
  "link_url": "https://mp.weixin.qq.com/s/abc123",
  "link_title": "一篇公众号文章",
  "link_type": "CHAT_APP_article"
}
```

---

### 4.3 FileHandler（文件传输）

**功能**：处理 `sub_type=6` 的文件传输，提取文件名并分类

**输出字段**：
| 字段 | 类型 | 说明 |
|------|------|------|
| link_sub_type | str | 固定为 "file" |
| file_name | str | 文件名 |
| file_ext | str | 文件扩展名（小写） |
| file_category | str | 文件类型分类 |
| media_path | str | 媒体文件路径 |
| file_size_bytes | int | 文件大小（可选） |

**文件类型分类规则**（来自 `configs/linkfile.yaml`）：
| file_category | 扩展名 |
|---------------|--------|
| document | pdf, doc, docx, xls, xlsx, ppt, pptx, txt, md |
| archive | zip, rar, 7z, tar, gz |
| audio | mp3, wav, flac, aac, m4a |
| video | mp4, avi, mkv, mov |
| image | jpg, jpeg, png, gif, bmp, webp |
| code | py, js, ts, java, c, cpp |
| data | json, xml, yaml, csv, sql |
| executable | exe, msi, dmg, apk |
| other | 其他未知扩展名 |

**示例输出**：
```json
{
  "link_sub_type": "file",
  "file_name": "报告.pdf",
  "file_ext": "pdf",
  "file_category": "document",
  "media_path": "file/2025-01/报告.pdf",
  "file_size_bytes": 1048576
}
```

---

### 4.4 MiniprogramHandler（小程序）

**功能**：处理 `sub_type=33,36` 的小程序分享

**输出字段**：
| 字段 | 类型 | 说明 |
|------|------|------|
| link_sub_type | str | 固定为 "miniprogram" |
| link_url | str | 小程序链接 |
| link_title | str | 小程序标题 |
| miniprogram_appid | str | 小程序 AppID |
| miniprogram_name | str | 小程序名称（从映射表获取） |

**示例输出**：
```json
{
  "link_sub_type": "miniprogram",
  "link_url": "https://mp.weixin.qq.com/mp/waerrpage?...",
  "link_title": "美团外卖",
  "miniprogram_appid": "wx14f2622c01a98fbb",
  "miniprogram_name": "美团"
}
```

---

### 4.5 VideoChannelHandler / ChatHistoryHandler（内容类）

**功能**：处理 `sub_type=51`（视频号）和 `sub_type=19`（聊天记录分享）

**输出字段**：
| 字段 | 类型 | 说明 |
|------|------|------|
| link_sub_type | str | "video_channel" 或 "chat_history" |
| content_title | str | 内容标题 |

**示例输出**：
```json
{
  "link_sub_type": "video_channel",
  "content_title": "某视频号的视频标题"
}
```

---

## 5. Schema 设计

### 5.1 公共字段（COMMON_HEADER_FIELDS）

所有模态共享的字段，按固定顺序排列：

```python
COMMON_HEADER_FIELDS = [
    "schema_version",   # 版本控制
    "seq_in_html",      # 原始序号
    "msg_uid",          # 唯一标识 (P1:MsgSvrID)
    "MsgSvrID",         # 服务器ID
    "token",            # 消息token
    "ts",               # Unix时间戳
    "time_local",       # 本地时间
    "speaker",          # 发送者 (ME/OTHER)
    "type",             # 消息类型 (49)
    "sub_type",         # 子类型
    "modality",         # 模态 (link_or_file)
    "media_path",       # 媒体路径
]
```

### 5.2 Linkfile 特定字段（LINKFILE_SPECIFIC_FIELDS）

```python
LINKFILE_SPECIFIC_FIELDS = [
    # 子类型标识
    "link_sub_type",        # quote, link, file, miniprogram, video_channel, chat_history
    
    # 引用消息字段 (quote)
    "quote_svrid",
    "quote_type",
    "quote_text",
    
    # 链接字段 (link, miniprogram)
    "link_url",
    "link_title",
    "link_type",
    
    # 小程序字段 (miniprogram)
    "miniprogram_appid",
    "miniprogram_name",
    
    # 文件字段 (file)
    "file_name",
    "file_ext",
    "file_category",
    "file_size_bytes",
    
    # 内容字段 (video_channel, chat_history)
    "content_title",
    
    # 错误处理
    "error_message",
]
```

### 5.3 完整输出示例

```json
{
  "schema_version": "merged_v2",
  "seq_in_html": 100,
  "msg_uid": "P1:1234567890",
  "MsgSvrID": "1234567890",
  "token": "abc123",
  "ts": 1749279243,
  "time_local": "2025-06-07 14:54:03",
  "speaker": "OTHER",
  "type": 49,
  "sub_type": 57,
  "modality": "link_or_file",
  "media_path": null,
  "link_sub_type": "quote",
  "quote_svrid": "9876543210",
  "quote_type": 1,
  "quote_text": "OTHER: 原始消息内容"
}
```

---

## 6. 时间轴字段映射

### 6.1 映射规则

不同 `link_sub_type` 映射到时间轴的字段不同：

| link_sub_type | 源字段 | 时间轴字段 |
|---------------|--------|------------|
| quote | quote_text | link_quote_text |
| quote | quote_svrid | link_quote_svrid |
| link | link_url | link_url |
| link | link_title | link_title |
| link | link_type | link_type |
| file | file_name | link_file_name |
| file | file_category | link_file_category |
| miniprogram | miniprogram_appid | link_miniprogram_appid |
| video_channel | content_title | link_content_title |
| chat_history | content_title | link_content_title |

### 6.2 Slim 版本字段

精简版（用于 LLM RAG）只包含核心字段：

```python
SLIM_FIELDS = {
    'link_sub_type',
    'link_quote_text',
    'link_url',
    'link_title',
    'link_type',
    'link_file_name',
    'link_file_category',
    'link_content_title',
}
```

---

## 7. 配置文件

### 7.1 configs/linkfile.yaml

```yaml
# sub_type 映射
sub_type_map:
  5: "link_share"
  6: "file"
  19: "chat_history"
  33: "miniprogram_link"
  36: "miniprogram"
  51: "video_channel"
  57: "quote"

# 链接类型识别规则 (按优先级排序)
link_type_rules:
  - pattern: "mp.weixin.qq.com"
    type: "CHAT_APP_article"
  - pattern: "bilibili.com"
    type: "bilibili_video"
  - pattern: "*"
    type: "web_link"  # 默认

# 文件类型分类
file_categories:
  document:
    extensions: ["pdf", "doc", "docx", ...]
  archive:
    extensions: ["zip", "rar", "7z", ...]
  # ...

# 小程序 AppID 映射
miniprogram_apps:
  wx14f2622c01a98fbb: "美团"
  # ...

# 输出文件名
output_files:
  extract: "linkfile_extract_v1.jsonl"
  merged: "linkfile_merged_final.jsonl"
```

---

## 8. 运行命令

```bash
# 激活环境
conda activate CHAT_APP_DHA

# 运行完整流水线
python run_all_pipelines.py --only linkfile

# 或分步运行
python scripts/linkfile/run_all/_01_extract_and_anonymize.py
python scripts/linkfile/run_all/_02_merge_engine.py
python scripts/linkfile/run_all/_03_update_timeline.py
```

---

## 9. 目录结构

```
scripts/linkfile/
├── handlers/
│   ├── __init__.py
│   ├── base.py              # SubTypeHandler 抽象基类
│   ├── quote_handler.py     # 引用消息处理器
│   ├── link_handler.py      # 链接分享处理器
│   ├── file_handler.py      # 文件传输处理器
│   ├── miniprogram_handler.py  # 小程序处理器
│   └── content_handler.py   # 视频号/聊天记录处理器
├── extractor.py             # 主提取器（路由）
└── run_all/
    ├── _01_extract_and_anonymize.py  # 提取阶段
    ├── _02_merge_engine.py           # 合并阶段
    └── _03_update_timeline.py        # 时间轴更新

artifacts/
├── before_merge/linkfile/
│   └── linkfile_extract_v1.jsonl
└── after_merge/linkfile/
    └── linkfile_merged_final.jsonl

configs/
└── linkfile.yaml            # 配置文件
```

---

## 10. 与其他模态的对比

| 特性 | Image | Voice | Video | Sticker | Linkfile |
|------|-------|-------|-------|---------|----------|
| 需要 GPU | ✅ | ✅ | ✅ | ✅ | ❌ |
| 流水线步骤 | 4 | 4 | 5 | 8 | 3 |
| 子类型处理 | ❌ | ❌ | ❌ | ❌ | ✅ (6种) |
| 策略模式 | ❌ | ❌ | ❌ | ❌ | ✅ |
| 匿名化 | ❌ | ❌ | ❌ | ❌ | ✅ |
| Schema 版本 | merged_v2 | merged_v2 | merged_v2 | merged_v2 | merged_v2 |

---

## 11. 设计亮点

1. **策略模式**：通过 Handler 抽象基类和路由机制，实现了子类型的解耦处理，易于扩展新的子类型

2. **配置驱动**：链接类型规则、文件分类规则都通过 YAML 配置，无需修改代码即可调整

3. **Schema 统一**：与其他模态使用相同的 `merged_v2` Schema，保证数据格式一致性

4. **三阶段架构**：提取 → 合并 → 时间轴更新，与其他模态保持一致的流水线结构

5. **轻量级**：纯 CPU 处理，无需 GPU 资源，适合快速处理大量消息


---

## 12. 实际案例

以下是从实际数据中提取的案例，展示各子类型的输出格式：

### 12.1 引用消息（quote）案例

```json
{
  "schema_version": "merged_v2",
  "msg_uid": "P1:5107033433851233941",
  "sub_type": 57,
  "link_sub_type": "quote",
  "quote_svrid": "[SERVER_ID]",
  "quote_type": 1,
  "quote_text": "OTHER: 觉得，还是有一丢丢准的..."
}
```

**说明**：
- `quote_svrid` 指向被引用消息的 MsgSvrID
- `quote_type=1` 表示被引用的是文本消息
- `quote_text` 中的 speaker 前缀已匿名化为 "OTHER:"

### 12.2 链接分享（link）案例

**CHAT_APP公众号文章**：
```json
{
  "link_sub_type": "link",
  "link_url": "https://mp.weixin.qq.com/s?__biz=MzIzNDYxNTcxOA==&mid=2247799350...",
  "link_title": "暴雨蓝色预警！贵州启动四级应急响应",
  "link_type": "CHAT_APP_article"
}
```

**小红书链接**：
```json
{
  "link_sub_type": "link",
  "link_url": "https://www.xiaohongshu.com/discovery/item/example_item_id",
  "link_title": "轻松实现马蹄爆爆珠自由",
  "link_type": "web_link"
}
```

**说明**：
- CHAT_APP公众号链接被识别为 `CHAT_APP_article` 类型
- 小红书链接因未配置规则，归类为默认的 `web_link`

### 12.3 文件传输（file）案例

**压缩包**：
```json
{
  "link_sub_type": "file",
  "file_name": "example_archive.zip",
  "file_ext": "zip",
  "file_category": "archive",
  "media_path": "raw/file/example_archive.zip"
}
```

**PDF 文档**：
```json
{
  "link_sub_type": "file",
  "file_name": "项目需求文档_v1.0.pdf",
  "file_ext": "pdf",
  "file_category": "document",
  "media_path": "raw/file/项目需求文档_v1.0.pdf"
}
```

**说明**：
- `.zip` 文件被分类为 `archive`（压缩包）
- `.pdf` 文件被分类为 `document`（文档）

### 12.4 小程序（miniprogram）案例

```json
{
  "schema_version": "merged_v2",
  "msg_uid": "P1:2345678901",
  "sub_type": 33,
  "link_sub_type": "miniprogram",
  "link_title": "示例小程序",
  "miniprogram_appid": "wx1234567890abcdef"
}
```

**说明**：
- `sub_type=33` 是小程序链接类型
- `miniprogram_appid` 是小程序的唯一标识

---

## 13. 扩展指南

### 13.1 添加新的链接类型规则

编辑 `configs/linkfile.yaml`：

```yaml
link_type_rules:
  # 添加小红书规则
  - pattern: "xiaohongshu.com"
    type: "xiaohongshu_post"
    description: "小红书笔记"
  
  # 添加抖音规则
  - pattern: "douyin.com"
    type: "douyin_video"
    description: "抖音视频"
  
  # 默认规则放最后
  - pattern: "*"
    type: "web_link"
```

### 13.2 添加新的文件类型分类

编辑 `configs/linkfile.yaml`：

```yaml
file_categories:
  # 添加电子书分类
  ebook:
    extensions: ["epub", "mobi", "azw3"]
    description: "电子书"
```

### 13.3 添加新的子类型处理器

1. 创建新的 Handler 类：

```python
# scripts/linkfile/handlers/new_handler.py

class NewHandler(SubTypeHandler):
    @property
    def sub_types(self) -> List[int]:
        return [99]  # 新的 sub_type
    
    @property
    def link_sub_type(self) -> str:
        return "new_type"
    
    def extract(self, msg, html_quote_lookup):
        return {
            "link_sub_type": self.link_sub_type,
            # 提取特定字段...
        }
```

2. 在 `extractor.py` 中注册：

```python
def _register_handlers(self):
    handlers = [
        # ... 现有处理器
        NewHandler(),  # 添加新处理器
    ]
```

3. 更新 `LINKFILE_SPECIFIC_FIELDS` 添加新字段

---

## 14. 总结

Linkfile 流水线是 CHAT_APP_DHA 项目中最轻量但功能最丰富的模态处理流水线：

- **轻量级**：纯 CPU 处理，无需 GPU
- **可扩展**：策略模式支持轻松添加新的子类型
- **配置驱动**：通过 YAML 配置调整分类规则
- **Schema 统一**：与其他模态保持一致的数据格式

通过这个流水线，可以将CHAT_APP聊天中的引用、链接、文件、小程序等多种消息类型统一处理，为后续的数据分析和 LLM RAG 提供结构化的数据支持。
