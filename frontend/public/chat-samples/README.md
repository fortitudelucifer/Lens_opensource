# Chat Samples

把真实对话 JSON 放到当前目录，并在 `manifest.json` 中维护文件名数组。

## 支持的 JSON 结构

1. 顶层数组（推荐）

```json
[
  { "role": "user", "content": "...", "timestamp": "2026-02-21T11:20:00Z" },
  { "role": "assistant", "content": "..." }
]
```

2. 顶层对象，字段之一为 `messages` / `conversation` / `turns`

```json
{
  "messages": [
    { "speaker": "user", "text": "..." },
    { "speaker": "assistant", "text": "..." }
  ]
}
```

## 字段兼容

- 角色字段：`role` 或 `speaker`
- 内容字段：`content` / `text` / `message`
- 时间字段：`timestamp`（可选）
- 思考字段：`thinking`（可选）

`role/speaker` 包含 `assistant`/`advisor`/`ai` 会被视为 AI，其余视为用户。
