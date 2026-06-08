# 专业知识库注入与 RAG 索引升级

> 📌 **本文档定位**：覆盖 S4.4（RAG 知识库注入）和 S4.5（FAISS 索引升级）的设计与实现。
>
> 更新于：2026-03-07

---

## 1. 专业知识库注入（S4.4）

### 1.1 目录结构

```
advisor_out/knowledge/
├── communication/
│   └── nvc_four_steps.jsonl      # NVC 四要素 + 我信息 + 积极倾听（4 条）
├── crisis/
│   └── grounding_techniques.jsonl # 5-4-3-2-1 接地 + 蝴蝶拥抱 + 呼吸法（3 条）
├── eft_resources/
│   └── tango_process.jsonl       # 追逃循环 + 三阶段 + 依恋需求（3 条）
├── therapy_manuals/              # 待填充：WHO PM+、ACT、mhGAP
└── perspectives/                 # S6 跨学科知识（Phase II）
    ├── sociology.jsonl           # 待填充
    ├── philosophy.jsonl          # 待填充
    ├── game_theory.jsonl         # 待填充
    └── cultural.jsonl            # 待填充
```

### 1.2 FAQ 条目格式

```jsonc
{
  "question": "什么是非暴力沟通（NVC）？",
  "answer": "非暴力沟通包含四个步骤：1) 观察 2) 感受 3) 需要 4) 请求...",
  "category": "communication",     // 用于 agent_type 匹配加权
  "keywords": ["NVC", "非暴力沟通", "四要素"],
  "source": "Marshall Rosenberg, Nonviolent Communication",
  "license": "人工摘要"
}
```

### 1.3 加载机制

`_load_faq_knowledge()` 使用 `rglob("*.jsonl")` 递归扫描 `knowledge/` 下所有子目录，启动时自动加载，打印分类统计。新增 JSONL 文件后**重启后端即生效**。

### 1.4 检索策略

`_search_faq(query, top_k=3, agent_type="")`:

| 匹配方式 | 基础分 | 说明 |
|----------|--------|------|
| 中文关键词命中 answer/question | +1/词 | `re.findall(r'[\u4e00-\u9fff]{2,}', query)` |
| keywords 列表命中 | +2/词 | 条目自带的关键词优先匹配 |
| category 匹配 agent_type | 总分 ×2 | 如 EFT 顾问优先匹配 eft 类条目 |

### 1.5 注入控制（三开关独立）

| 开关 | 控制字段 | 前端位置 | 默认 | 颜色 |
|------|---------|---------|------|------|
| 聊天记录 | `use_rag` | ChatTopBar / ArenaPage | 开 | 绿色 |
| 专业知识 | `use_knowledge` | ChatTopBar / ArenaPage | 开 | 紫色 |
| 测评注入 | `inject_enabled` | 测评结果页 | 关 | 绿色 |

`use_knowledge=false` 时，`_build_rag_context()` 内的 `_search_faq()` 被跳过，但 RAG 检索（聊天记录）不受影响。

### 1.6 注入格式

知识库命中时注入 system prompt 的格式：

```
【专业知识】
Q: 什么是追逃循环？
A: 追逃循环是 EFT 中的核心概念...

Q: 什么是 4-4-6 呼吸法？
A: 吸气 4 秒 → 屏住 4 秒 → 呼气 6 秒...
```

与 `【历史摘要】`、`【已确认的关键信息】`、`【用户交流前测评结果】` 平行，各占独立段落。

---

## 2. FAISS 索引升级（S4.5）

### 2.1 索引工厂

`graph_rag.py` 中的 `_create_faiss_index(dim, n_vectors, index_type="auto")`：

| index_type | 行为 | 适用场景 |
|-----------|------|---------|
| `"auto"` | N < 2000 → FlatIP，否则 → IVFFlat | 默认，自动选择 |
| `"flat"` | 强制 FlatIP | 需要 100% 召回率时 |
| `"ivf"` | 强制 IVFFlat（nlist=√N, nprobe=10） | 大数据集优化 |
| `"hnsw"` | 预留，当前 fallback 到 FlatIP | 未来迁移到 Qdrant |

### 2.2 IVFFlat 参数

| 参数 | 值 | 说明 |
|------|-----|------|
| nlist | √N | 聚类中心数，自动计算 |
| nprobe | 10 | 查询时搜索的聚类数 |
| METRIC | INNER_PRODUCT | 与 FlatIP 一致（L2 归一化后等价 cosine） |
| 训练 | 自动 | `index.train(embeddings)` 在 `add()` 前调用 |

### 2.3 蓝绿部署

`save_index()` 使用原子写入：

```python
tmp_path = save_dir / 'index.faiss.new'
final_path = save_dir / 'index.faiss'
faiss.write_index(index, str(tmp_path))  # 先写临时文件
tmp_path.rename(final_path)              # 原子 rename 替换
```

### 2.4 构建脚本

```bash
# 默认（自动选择索引类型）
python scripts/advisor/run_all/_09_build_graph.py

# 强制 IVFFlat
python scripts/advisor/run_all/_09_build_graph.py --index-type ivf

# 强制 FlatIP（测试用）
python scripts/advisor/run_all/_09_build_graph.py --index-type flat

# HNSW（预留，当前 fallback）
python scripts/advisor/run_all/_09_build_graph.py --index-type hnsw
```

---

## 3. EFT 阶段追踪（附 S4.2 前端增强）

### 3.1 Session 元数据

EFT 顾问（`agent_type="eft"`）的 session 包含额外字段：

```json
{
  "eft_stage": "exploration",
  "eft_round_count": 3
}
```

### 3.2 阶段推进规则

| 轮次 | eft_stage | 对话动作 |
|------|-----------|---------|
| 1-3 | exploration | 情绪镜像 + 情绪深化 |
| 4-6 | comforting | 循环识别 + 需求澄清 + 伴侣视角 |
| 7+ | action | 新互动脚本 + 积极强化 + 预防复发 |

### 3.3 前端阶段标签

ChatTopBar 在 EFT 顾问模式下显示粉色 badge：

- `探索阶段`（轮次 1-3）
- `安抚阶段`（轮次 4-6）
- `行动阶段`（轮次 7+）

每轮回复完成后，前端 fetch session 获取最新 `eft_stage` 并更新标签。

---

**文档版本**: v1.0
**创建时间**: 2026-03-07
**关联文档**: [综合执行计划](../research/big_plan/plan_v1/综合执行计划_v2.md) §4.4/§4.5, [arena_dual_mirror_overview.md](arena_dual_mirror_overview.md)
