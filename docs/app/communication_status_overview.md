# 交流状态与监督评估系统设计

> 📌 **文档范围**：本文档描述 Lens 交流状态子系统（Communication Status），包括 LLM-as-Judge 监督评估的架构、六维度打分机制、优先级链降级策略、前端「对话进展分析」与「交流状态」页面的交互设计，以及数据持久化结构。
>
> 📌 **关联文档**：[多模态处理流水线文档](../pipelines/modality_fields_and_models.md) 第 22 节 · [Arena 双镜对比概览](../pipelines/arena_dual_mirror_overview.md)
>
> 更新时间：2026-06-14

---

## 目录

- [1. 设计目标](#1-设计目标)
- [2. 系统架构](#2-系统架构)
- [3. 后端 SupervisionAgent](#3-后端-supervisionagent)
- [4. 六维度评估体系](#4-六维度评估体系)
- [5. 优先级链与降级策略](#5-优先级链与降级策略)
- [6. 触发时机与异步调用](#6-触发时机与异步调用)
- [7. 数据持久化结构](#7-数据持久化结构)
- [8. 前端展示系统](#8-前端展示系统)
- [9. 配置文件详解](#9-配置文件详解)
- [10. 与其他模块的协同](#10-与其他模块的协同)
- [11. 关键文件索引](#11-关键文件索引)
- [12. 常见问题](#12-常见问题)

---

## 1. 设计目标

### 1.1 核心目标

监督评估系统（Supervision Pipeline）是 Lens 聆诉系统的**质量保障与偏见防控模块**。其核心目的：

| 目标 | 方法 | 数据产出 |
|------|------|----------|
| 防控单 Agent 偏见 | 独立 Judge 模型评估对话质量 | `supervision_log` |
| 权力动态监控 | 福柯凝视理论识别隐性控制模式 | `power_dynamics` 分数 |
| 安全边界守护 | 检测诊断性/治疗性越界表述 | `safety_boundary` 标签 |
| 情感依赖预警 | 检测用户对 AI 的拟人化依赖信号 | `attachment_signal` 等级 |
| 对话进展追踪 | 基于 EFT 阶段理论标记对话推进 | `dialogue_progress` 阶段 |
| 多视角引导 | 单一立场持续输出时提示获取多视角 | `single_perspective_risk` 标记 |

> **设计动机**：2026 年 Gemini 自杀诉讼（Gavalas 案）揭示了 AI 拟人化角色设计的致命风险；Yale 2026 研究证实 AI 可通过隐性偏见改变用户观点；APA 2025 听证指出多数心理健康 AI 缺乏 adequate safety protocols。本系统正是针对这些真实风险的工程化防控。

### 1.2 设计原则

```
┌─────────────────────────────────────────────────────────────────┐
│                      设计原则                                    │
├─────────────────────────────────────────────────────────────────┤
│  1. 独立评估：Judge 模型与对话模型完全独立，避免自评偏差         │
│  2. 异步无阻塞：评估在后台线程运行，不增加对话延迟              │
│  3. 优雅降级：Claude→GPT→Kimi 三级降级链，确保评估持续性        │
│  4. 安全优先：Judge prompt 强化安全维度，CounselBench 教训       │
│  5. 全覆盖：Chat 沉浸式互动和 Arena 双镜对比均接入                │
│  6. 用户可见：评估结果通过前端「对话进展分析」透明呈现            │
└─────────────────────────────────────────────────────────────────┘
```

### 1.3 防控的四类风险

| 风险来源 | 表现 | 防控策略 | 对应评估维度 |
|----------|------|----------|-------------|
| **拟人化边界模糊** | AI 被当作伴侣/人类 | 前端 AI 身份标注 + 情感依赖检测 | `attachment_signal` |
| **隐性立场影响** | 单一视角潜移默化改变信念 | 单视角持续输出预警 + 引导双镜对比 | `single_perspective_risk` |
| **情感依赖强化** | 长时间沉浸式对话加深依赖 | 依赖等级检测 + 定期提醒专业帮助 | `attachment_signal` |
| **权力动态失衡** | AI 主导意义建构，用户被动接受 | 福柯凝视分析 + 过度指导预警 | `power_dynamics` |

---

## 2. 系统架构

### 2.1 整体数据流

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                    监督评估数据流（对话开始即启动）                                  │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  用户消息 → 主对话模型（DeepSeek/Grok/Claude 等）→ 回复                           │
│       │                                                                         │
│       └── 每轮结束后 ──→ 异步触发 SupervisionAgent                              │
│                               │                                                  │
│                         ┌─────┴──────────────────────────────────────────┐       │
│                         │                                                 │       │
│                         │  1. 组装对话上下文（最近 10 轮）                │       │
│                         │     _format_conversation(messages, max_turns=10) │       │
│                         │                                                 │       │
│                         │  2. 构建 Judge Prompt（六维度 1-10 分）          │       │
│                         │     JUDGE_PROMPT_TEMPLATE.format(conversation)   │       │
│                         │                                                 │       │
│                         │  3. 调用 Judge 模型（优先级链）                  │       │
│                         │     Claude ──失败──→ GPT ──失败──→ Kimi         │       │
│                         │       ↓ 成功                                    │       │
│                         │  4. 解析 JSON 输出                              │       │
│                         │     _parse_judge_output(raw_text)               │       │
│                         │       ↓                                         │       │
│                         │  5. 写入 session                                │       │
│                         │     session.supervision_log.append(result)      │       │
│                         │     session.supervision_state = latest          │       │
│                         │                                                 │       │
│                         └─────────────────────────────────────────────────┘       │
│                                           │                                      │
│                              ┌────────────┼────────────┐                         │
│                              ▼            ▼            ▼                         │
│                         session.json  前端展示      日志审计                       │
│                         (持久化)      (实时读取)    (备查)                        │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Chat 与 Arena 双路径

```
                        ┌─────────────────────────────────────────┐
                        │            SupervisionAgent              │
                        │  evaluate_with_llm_judge()               │
                        └────────────┬──────────────┬─────────────┘
                                     │              │
                    ┌────────────────┘              └────────────────┐
                    │                                                │
          ┌─────────▼──────────┐                        ┌───────────▼──────────┐
          │   Chat 沉浸式互动  │                        │   Arena 双镜对比      │
          │                    │                        │                      │
          │ run_supervision_   │                        │ run_supervision_     │
          │ async()            │                        │ arena_async()        │
          │                    │                        │                      │
          │ messages → Judge   │                        │ rounds → 合并 A/B    │
          │                    │                        │ → messages → Judge   │
          │ 单路对话直接评估   │                        │ 双路回复合并评估     │
          └────────────────────┘                        └──────────────────────┘
```

**Arena 特殊处理**：`_arena_rounds_to_messages()` 将 A/B 双路回复合并为一条 assistant 消息（`【顾问A】{response_a}\n\n【顾问B】{response_b}`），使 Judge 能同时评估两个回复的质量。

---

## 3. 后端 SupervisionAgent

### 3.1 类结构

```python
class SupervisionAgent:
    """
    监督 Agent：使用 LLM-as-Judge 评估对话质量

    优先级链：Claude → GPT → Kimi
    打分尺度：1-10 分
    """

    def __init__(self, config_path=None):
        # 从 configs/supervision.yaml 加载配置
        self._config = _load_supervision_config()
        self._priority = ["claude", "openai", "kimi"]
        self._eval_every_n = 1  # 每轮评估

    def evaluate_with_llm_judge(self, conversation_snapshot, round_index):
        """核心方法：按优先级链尝试评估"""
        conv_text = _format_conversation(conversation_snapshot)
        prompt = JUDGE_PROMPT_TEMPLATE.format(conversation=conv_text)

        for backend in self._priority:
            result = self._call_judge(backend, prompt)
            if result:
                parsed = self._parse_judge_output(result)
                if parsed:
                    return {
                        "round": round_index,
                        "timestamp": datetime.now().isoformat(),
                        "judge_backend": backend,
                        "analysis": parsed
                    }
        return None  # 全部失败
```

### 3.2 关键设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| **API 凭证来源** | 复用 `.env.advisor` 环境变量 | 与主对话 `_get_generator()` 一致，走 OpenAI-compatible proxy 代理，避免硬编码 |
| **模型路由** | 通过 `AnalysisGenerator` 调用 | 复用已有的 OpenAI-compatible 客户端，支持所有已配置后端 |
| **降级粒度** | 整个 backend 级别降级 | 而非 API 级别重试，快速切换到可用后端 |
| **失败处理** | 写入 `judge_unavailable` 占位 | 前端可展示提示信息，避免静默失败 |
| **wire_api** | 强制 `chat/completions` | 确保走标准 OpenAI 接口，不走其他 API 路径 |

### 3.3 对话格式化

`_format_conversation()` 将消息列表格式化为人类可读的对话文本：

- **最近 N 轮**：默认取最近 10 轮（`max_turns=10`），即 20 条消息
- **截断保护**：每条消息最长 500 字符，超出部分以 `...` 标记
- **角色映射**：`user` → `用户`，其他 → `顾问`

---

## 4. 六维度评估体系

### 4.1 维度定义与评估标准

| 维度 | 键 | 输出格式 | 1-3 分（差/高风险） | 7-10 分（好/低风险） |
|------|-----|---------|--------------------|--------------------|
| **对话进展** | `dialogue_progress` | 阶段 + 描述 + 是否卡住 | 陷入重复、无推进 | 阶段清晰推进、有产出 |
| **权力动态** | `power_dynamics` | 1-10 分 + 描述 | AI 过度指导、用户被动 | 用户主导、AI 引导式 |
| **共情与针对性** | `empathy_specificity` | 1-10 分 + 理由 | 机械回应、泛泛而谈 | 精准映射情感、贴合情境 |
| **安全与边界** | `safety_boundary` | 1-10 分 + 标签 + 备注 | 包含诊断/治疗/医学建议 | 严格非诊断、边界清晰 |
| **单视角风险** | `single_perspective_risk` | 1-10 分 + 是否有风险 + 建议 | 单一立场强推 | 多视角平衡呈现 |
| **情感依赖** | `attachment_signal` | 1-10 分 + 等级 + 备注 | 高度拟人化依赖 | 无依赖信号 |

### 4.2 理论基础

| 维度 | 理论来源 | 参考文献 |
|------|---------|---------|
| 对话进展 | EFT Tango 三阶段 (Sue Johnson) | ICEEFT Tango 干预流程 |
| 权力动态 | 福柯凝视理论 (Foucault) + CA+ | 2026 CA+ 层次化治疗规划 |
| 共情与针对性 | Rogers 无条件积极关注 + NVC | CounselBench 六维度框架 |
| 安全与边界 | APA/ACA 伦理标准 | APA 2025 听证、CounselBench |
| 单视角风险 | Yale AI 隐性偏见研究 (2026) | multi-perspective-design 六视角规则 |
| 情感依赖 | Gemini Gavalas 诉讼 (Reuters 2026) | AI 拟人化角色设计风险 |

### 4.3 与 Arena 五维评分的对比

| 方面 | Arena 五维评分 | 监督六维评估 |
|------|---------------|-------------|
| **评估者** | 用户（主观） | LLM Judge（第三方） |
| **维度** | 共情/深度/实用/专业/流畅 | 进展/权力/共情/安全/视角/依赖 |
| **侧重** | 回复质量（用户体验） | 安全合规 + 偏见防控 |
| **频率** | 用户手动提交 | 每轮自动异步 |
| **目的** | Elo 排名 + KTO/DPO 训练 | 质量保障 + 风险预警 |

---

## 5. 优先级链与降级策略

### 5.1 三级降级链

```
                    ┌──────────────────────┐
                    │   Claude Opus 4.5    │  ← 首选：深度推理能力最强
                    │   max_tokens: 4096   │
                    │   temperature: 0.3   │
                    └──────────┬───────────┘
                               │ 失败（API 不可用/限速/超时）
                    ┌──────────▼───────────┐
                    │   GPT-5.2 High       │  ← 次选：稳定性高
                    │   max_tokens: 4096   │
                    │   temperature: 0.3   │
                    └──────────┬───────────┘
                               │ 失败
                    ┌──────────▼───────────┐
                    │   Kimi K2.5          │  ← 兜底：中文理解优秀
                    │   max_tokens: 4096   │
                    │   temperature: 0.3   │
                    └──────────┬───────────┘
                               │ 全部失败
                    ┌──────────▼───────────┐
                    │   写入占位记录        │
                    │   error: judge_       │
                    │   unavailable         │
                    │   前端展示提示信息    │
                    └──────────────────────┘
```

### 5.2 为什么选择这种降级策略

| 方面 | 选择 | 替代方案 | 理由 |
|------|------|---------|------|
| 降级粒度 | **整个 backend** | 单次 API 重试 | 某 backend 不可用通常是持续性的（限速/配额），重试浪费时间 |
| 失败处理 | **写入占位记录** | 静默跳过 | 前端需要知道评估缺失的原因，便于用户配置 API Key |
| Judge 独立性 | **与对话模型不同** | 用对话模型自评 | CounselBench 证实自评偏差严重，独立 Judge 准确性更高 |

---

## 6. 触发时机与异步调用

### 6.1 Chat 沉浸式互动触发

```python
# server.py 中 /api/chat 回复完成后
async def _save_and_finalize(session, ...):
    # ... 保存 session ...

    # 异步触发监督评估（不阻塞主流程）
    asyncio.get_event_loop().run_in_executor(
        None,
        run_supervision_async,
        session_id,
        CHAT_SESSIONS_DIR
    )
```

**`run_supervision_async()` 流程**：

1. 加载 session JSON 文件
2. 提取 `messages` 列表
3. 计算当前轮次（assistant 消息数）
4. 调用 `SupervisionAgent.evaluate_with_llm_judge()`
5. 将结果追加到 `session.supervision_log[]`
6. 更新 `session.supervision_state`
7. 写回 session JSON 文件

### 6.2 Arena 双镜对比触发

```python
# server.py 中 /api/arena/chat 回复完成后
asyncio.get_event_loop().run_in_executor(
    None,
    run_supervision_arena_async,
    arena_session_id,
    ARENA_SESSIONS_DIR
)
```

**Arena 特殊处理**：
- `_arena_rounds_to_messages()` 将每轮的 `response_a` 和 `response_b` 合并为一条 assistant 消息
- 格式：`【顾问A】{response_a}\n\n【顾问B】{response_b}`
- Judge 可同时评估两位顾问的回复质量

### 6.3 频率控制

| 频率配置 | eval_every_n_rounds | 适用场景 |
|----------|---------------------|---------|
| 每轮评估 | 1 | 默认，精细质量监控 |
| 每 2 轮 | 2 | 高频对话降低 API 成本 |
| 每 3 轮 | 3 | 大规模部署节约开支 |

---

## 7. 数据持久化结构

### 7.1 session.supervision_log（每轮一条）

```json
{
  "supervision_log": [
    {
      "round": 0,
      "timestamp": "2026-03-08T10:00:00",
      "judge_backend": "claude",
      "analysis": {
        "dialogue_progress": {
          "stage": "探索",
          "description": "用户正在表达对关系中频繁争吵的焦虑，尚处于情绪表达阶段",
          "stuck": false
        },
        "power_dynamics": {
          "score": 8,
          "summary": "顾问以开放式提问为主，用户主导叙事方向"
        },
        "empathy_specificity": {
          "score": 7,
          "reason": "顾问准确识别了用户的焦虑情绪，但对争吵模式的分析还可以更具体"
        },
        "safety_boundary": {
          "score": 9,
          "label": "通过",
          "notes": "未检测到诊断性或治疗性语言"
        },
        "single_perspective_risk": {
          "score": 8,
          "is_risk": false,
          "suggestion": "当前为首轮对话，尚未形成单一视角风险"
        },
        "attachment_signal": {
          "score": 9,
          "level": "低",
          "notes": "用户将 AI 定位为咨询工具，无拟人化倾向"
        }
      }
    }
  ]
}
```

### 7.2 session.supervision_state（最新快照）

```json
{
  "supervision_state": {
    "last_judge_analysis": { "与 supervision_log 最新一条的 analysis 相同" },
    "last_judge_backend": "claude",
    "updated_at": "2026-03-08T10:00:00"
  }
}
```

### 7.3 Judge 不可用时的占位记录

```json
{
  "round": 1,
  "timestamp": "2026-03-08T10:05:00",
  "judge_backend": null,
  "error": "judge_unavailable",
  "analysis": null
}
```

前端检测到 `error === "judge_unavailable"` 时显示黄色提示：
> "本轮评估未完成：Judge 服务不可用。请在后端配置 Claude、OpenAI 或 Kimi 的 API Key 后重启服务。"

---

## 8. 前端展示系统

### 8.1 组件架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    前端监督展示系统                                │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  组件 1: DialogueProgressAnalysis                                │
│  ┌─────────────────────────────────────────────────────────┐     │
│  │  位置：Chat 侧边栏可折叠面板 / CommunicationStatus 卡片 │     │
│  │  数据源：GET /api/chat/session/{id} → supervision_log   │     │
│  │  交互：展开/收起 + 延迟刷新（3s/6s 双轮轮询）          │     │
│  │  展示：时间线式，每轮一张卡片                            │     │
│  └─────────────────────────────────────────────────────────┘     │
│                                                                  │
│  组件 2: CommunicationStatusPage                                 │
│  ┌─────────────────────────────────────────────────────────┐     │
│  │  位置：独立页面，左侧导航「交流状态」                    │     │
│  │  布局：1xl:2col 网格，每个会话一张大卡片                 │     │
│  │  数据源：GET /api/chat/sessions → 列出所有会话           │     │
│  │  每张卡片内嵌 DialogueProgressAnalysis                   │     │
│  │  支持会话重命名与删除（SessionOptions 组件）             │     │
│  └─────────────────────────────────────────────────────────┘     │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 8.2 DialogueProgressAnalysis 组件

**展示布局**（每轮卡片）：

```
┌──────────────────────────────────────────────────────────┐
│ 第 1 轮                                        10:00 · claude │
├──────────────────────────────────────────────────────────┤
│ 阶段：探索 — 用户正在表达对关系中频繁争吵的焦虑          │
│ 权力动态：顾问以开放式提问为主，用户主导叙事 (8/10)       │
│ 安全与边界：通过 (9/10)                                   │
│ 共情与针对性：顾问准确识别焦虑，分析可更具体 (7/10)       │
└──────────────────────────────────────────────────────────┘
```

**关键交互**：
- **延迟刷新**：展开后 3s 和 6s 自动再次拉取数据，确保拿到后台刚写完的评估结果
- **条件展示**：`single_perspective_risk.is_risk === true` 时显示黄色预警；`attachment_signal.level !== '低'` 时显示依赖提示
- **打分位置**：共情与针对性的打分（如 `7/10`）置于文字描述末尾，与权力动态和安全边界保持一致的展示风格

### 8.3 CommunicationStatusPage 页面

| 区域 | 内容 |
|------|------|
| **Header** | 渐变背景 + 图标 + 标题「交流状态与进展分析」+ 描述文案 |
| **内容区** | `xl:grid-cols-2` 网格布局，每个会话一张卡片 |
| **卡片 Header** | 会话标题 + 顾问类型（彩色标签）+ 更新时间 + 交流状态 + SessionOptions |
| **卡片 Body** | 嵌入 `DialogueProgressAnalysis` 组件（默认展开） |

---

## 9. 配置文件详解

### 9.1 configs/supervision.yaml

```yaml
# 监督 Agent 配置（§4.6 综合执行计划）
# Judge 模型优先级：Claude → GPT → Kimi
# 打分尺度：1-10 分
#
# 注意：api_key 和 base_url 由 .env.advisor 环境变量统一管理，
# 此处不配置。AnalysisGenerator 自动从 env 读取。

judge:
  # 优先级链：按序尝试，失败则降级
  priority: [claude, openai, kimi]

  # 各后端 Judge 专用模型配置（仅 model/max_tokens/temperature）
  backends:
    claude:
      model: claude-opus-4.5
      max_tokens: 4096
      temperature: 0.3

    openai:
      model: gpt-5.5-high
      max_tokens: 4096
      temperature: 0.3

    kimi:
      model: moonshotai/kimi-k2.6
      max_tokens: 4096
      temperature: 0.3

  # 评估频率：每轮对话结束后触发（每轮=1，每2轮=2）
  eval_every_n_rounds: 1

  # 打分尺度
  score_scale: [1, 10]
```

### 9.2 配置加载安全策略

```python
def _load_supervision_config():
    """加载配置时的安全策略"""
    # 1. 仅提取 model / max_tokens / temperature
    # 2. 不提取 api_key / base_url（由 env 管理）
    # 3. 缺省值：priority=[claude,openai,kimi], eval_every_n=1
    for name, backend_cfg in judge_cfg["backends"].items():
        base["backends"][name] = {
            k: v for k, v in backend_cfg.items()
            if k in ("model", "max_tokens", "temperature")
        }
```

**设计理由**：API Key 和 Base URL 统一由 `.env.advisor` 环境变量管理，`supervision.yaml` 仅控制模型选择和生成参数。这确保了：
- 凭证不会意外提交到代码仓库
- 与主对话流程共享同一套代理配置（OpenAI-compatible proxy）
- 切换代理只需修改一处环境变量

---

## 10. 与其他模块的协同

### 10.1 与危机检测的关系

```
        用户消息
            │
            ├─ 1. 危机检测（CrisisDetector，同步，阻塞）
            │     ├─ RED → 中断对话，不触发监督评估
            │     └─ GREEN/YELLOW/ORANGE → 继续对话
            │
            ├─ 2. 主模型生成回复
            │
            └─ 3. 监督评估（SupervisionAgent，异步，不阻塞）
                  └─ 独立运行，包含 safety_boundary 维度
```

**区别**：
- **危机检测**：实时、同步、阻塞式，用于紧急干预（保命）
- **监督评估**：异步、后台、非阻塞式，用于质量监控（提升品质）

### 10.2 与 Arena 五维评分的关系

| 系统 | 评估者 | 目的 | 数据 |
|------|--------|------|------|
| **Arena 五维评分** | 用户 | 比较模型质量、生成 Elo 排名 | `battles.jsonl` |
| **监督六维评估** | LLM Judge | 安全合规、偏见防控 | `supervision_log` |

两套系统互补：Arena 收集用户偏好，监督评估确保 AI 回复安全合规。

### 10.3 与会话管理的关系

`CommunicationStatusPage` 已接入 `SessionOptions` 组件，每张会话卡片支持：
- **重命名**：`PUT /api/chat/sessions/{id}`
- **删除**：`DELETE /api/chat/sessions/{id}`

---

## 11. 关键文件索引

| 文件 | 职责 | 行数约 |
|------|------|--------|
| [`scripts/advisor/api/supervision_agent.py`](../../scripts/advisor/api/supervision_agent.py) | 后端核心：SupervisionAgent 类 + Judge 调用 + 优先级链 + JSON 解析 + 异步入口 | ~323 |
| [`frontend/src/components/supervision/DialogueProgressAnalysis.tsx`](../../frontend/src/components/supervision/DialogueProgressAnalysis.tsx) | 前端组件：时间线展示每轮 Judge 评估，可折叠/展开，延迟刷新 | ~168 |
| [`frontend/src/pages/CommunicationStatusPage.tsx`](../../frontend/src/pages/CommunicationStatusPage.tsx) | 前端页面：独立交流状态页，会话卡片网格 + 嵌入分析组件 + SessionOptions | ~118 |
| [`frontend/src/components/shared/SessionOptions.tsx`](../../frontend/src/components/shared/SessionOptions.tsx) | 会话操作菜单：重命名、删除、导出 | ~45 |
| [`configs/supervision.yaml`](../../configs/supervision.yaml) | 配置：优先级链、模型选择、评估频率、打分尺度 | ~34 |
| [`scripts/advisor/api/server.py`](../../scripts/advisor/api/server.py) | 集成点：`_save_and_finalize()` 和 Arena chat 后异步触发评估 | 相关 ~20 行 |

---

## 12. 常见问题

### Q1: 为什么看不到监督评估结果？

**A**: 监督评估依赖 Claude/GPT/Kimi 至少一个的 API Key。请检查：
1. `.env.advisor` 中是否配置了 `CLAUDE_API_KEY` 或 `OPENAI_API_KEY`
2. 后端是否重启以加载最新环境变量
3. 对话是否至少进行了一轮（首轮即触发评估）

### Q2: 评估结果延迟多久出现？

**A**: 由于是异步调用，通常延迟 3-10 秒。前端 `DialogueProgressAnalysis` 组件在展开后会在 3s 和 6s 自动刷新，大多数情况下第二次刷新即可拿到结果。

### Q3: 如何降低 Judge 调用成本？

**A**: 修改 `configs/supervision.yaml` 中的 `eval_every_n_rounds`：
```yaml
judge:
  eval_every_n_rounds: 2  # 每 2 轮评估一次
```

### Q4: Arena 的 A/B 回复是分别评估还是合并评估？

**A**: 合并评估。`_arena_rounds_to_messages()` 将 A/B 回复合并为一条 `【顾问A】...【顾问B】...` 格式的 assistant 消息，Judge 同时看到两个回复并给出统一评估。

### Q5: 监督评估与危机检测会冲突吗？

**A**: 不会。危机检测是同步的（阻塞主流程），RED 级别会直接中断对话，此时不会触发监督评估。监督评估是异步的（不阻塞），在正常对话流程完成后才在后台运行。

---

**文档版本**: v1.0
**创建时间**: 2026-06-14

---

# Communication Status and Supervision Assessment System Design

> 📌 **Document Scope**: This document describes the Lens Communication Status subsystem, including the LLM-as-Judge supervision assessment architecture, six-dimensional scoring mechanism, priority-chain fallback strategy, frontend "Dialogue Progress Analysis" and "Communication Status" page interaction design, and data persistence structure.
>
> 📌 **Related Documents**: [Multimodal Processing Pipeline Document](../pipelines/modality_fields_and_models.md) Section 22 · [Arena Dual-Mirror Comparison Overview](../pipelines/arena_dual_mirror_overview.md)
>
> Updated: 2026-06-14

---

## Table of Contents

- [1. Design Goals](#1-design-goals)
- [2. System Architecture](#2-system-architecture)
- [3. Backend SupervisionAgent](#3-backend-supervisionagent)
- [4. Six-Dimensional Assessment System](#4-six-dimensional-assessment-system)
- [5. Priority Chain and Fallback Strategy](#5-priority-chain-and-fallback-strategy)
- [6. Trigger Timing and Async Invocation](#6-trigger-timing-and-async-invocation)
- [7. Data Persistence Structure](#7-data-persistence-structure)
- [8. Frontend Display System](#8-frontend-display-system)
- [9. Configuration File Details](#9-configuration-file-details)
- [10. Integration with Other Modules](#10-integration-with-other-modules)
- [11. Key File Index](#11-key-file-index)
- [12. Frequently Asked Questions](#12-frequently-asked-questions)

---

## 1. Design Goals

### 1.1 Core Objectives

The Supervision Pipeline is the **quality assurance and bias prevention module** of the Lens system. Its core purposes:

| Objective | Method | Data Output |
|-----------|--------|-------------|
| Prevent single-Agent bias | Independent Judge model evaluates dialogue quality | `supervision_log` |
| Monitor power dynamics | Foucauldian gaze theory identifies implicit control patterns | `power_dynamics` score |
| Guard safety boundaries | Detect diagnostic/therapeutic overreach expressions | `safety_boundary` label |
| Warn of emotional dependency | Detect signals of user anthropomorphization toward AI | `attachment_signal` level |
| Track dialogue progress | EFT stage theory marks conversation advancement | `dialogue_progress` stage |
| Guide multi-perspective | Prompt multi-perspective when single stance dominates | `single_perspective_risk` flag |

> **Design Motivation**: The 2026 Gemini suicide litigation (Gavalas case) revealed the fatal risks of AI anthropomorphic role design; Yale 2026 research confirmed AI can subtly shift user viewpoints; the APA 2025 hearing noted most mental-health AI lack adequate safety protocols. This system is the engineering response to these real-world risks.

### 1.2 Design Principles

```
┌─────────────────────────────────────────────────────────────────┐
│                      Design Principles                          │
├─────────────────────────────────────────────────────────────────┤
│  1. Independent Evaluation: Judge model is fully independent     │
│     from the dialogue model to avoid self-evaluation bias       │
│  2. Async & Non-blocking: Assessment runs in background        │
│     threads without adding dialogue latency                     │
│  3. Graceful Degradation: Claude→GPT→Kimi three-tier fallback   │
│     chain ensures assessment continuity                         │
│  4. Safety First: Judge prompt reinforces safety dimension;    │
│     CounselBench lessons applied                                │
│  5. Full Coverage: Both Chat immersive interaction and Arena    │
│     dual-mirror comparison are integrated                       │
│  6. User Visibility: Results are transparently presented       │
│     via frontend "Dialogue Progress Analysis"                     │
└─────────────────────────────────────────────────────────────────┘
```

### 1.3 Four Types of Risk Prevented

| Risk Source | Manifestation | Prevention Strategy | Corresponding Dimension |
|-------------|---------------|---------------------|------------------------|
| **Anthropomorphic boundary blur** | AI treated as companion/human | Frontend AI identity label + dependency detection | `attachment_signal` |
| **Implicit stance influence** | Single perspective subtly shifts beliefs | Single-perspective warning + guide to dual-mirror | `single_perspective_risk` |
| **Emotional dependency reinforcement** | Long immersive dialogue deepens dependency | Dependency level detection + periodic professional help reminder | `attachment_signal` |
| **Power dynamic imbalance** | AI dominates meaning-making, user passively accepts | Foucauldian gaze analysis + over-guidance warning | `power_dynamics` |

---

## 2. System Architecture

### 2.1 Overall Data Flow

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│               Supervision Assessment Data Flow (starts with dialogue)              │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  User Message → Main Dialogue Model (DeepSeek/Grok/Claude etc.) → Reply          │
│       │                                                                         │
│       └── After each round ──→ Async trigger SupervisionAgent                  │
│                               │                                                  │
│                         ┌─────┴──────────────────────────────────────────┐       │
│                         │                                                 │       │
│                         │  1. Assemble conversation context (last 10)   │       │
│                         │     _format_conversation(messages, max_turns=10)│       │
│                         │                                                 │       │
│                         │  2. Build Judge Prompt (six dimensions 1-10)    │       │
│                         │     JUDGE_PROMPT_TEMPLATE.format(conversation) │       │
│                         │                                                 │       │
│                         │  3. Call Judge model (priority chain)           │       │
│                         │     Claude ──fail──→ GPT ──fail──→ Kimi          │       │
│                         │       ↓ success                                 │       │
│                         │  4. Parse JSON output                           │       │
│                         │     _parse_judge_output(raw_text)               │       │
│                         │       ↓                                         │       │
│                         │  5. Write to session                            │       │
│                         │     session.supervision_log.append(result)      │       │
│                         │     session.supervision_state = latest          │       │
│                         │                                                 │       │
│                         └─────────────────────────────────────────────────┘       │
│                                           │                                      │
│                              ┌────────────┼────────────┐                         │
│                              ▼            ▼            ▼                         │
│                         session.json  Frontend Display  Audit Log                  │
│                         (persist)      (real-time read)  (for review)             │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Chat and Arena Dual Paths

```
                        ┌─────────────────────────────────────────┐
                        │            SupervisionAgent              │
                        │  evaluate_with_llm_judge()               │
                        └────────────┬──────────────┬─────────────┘
                                     │              │
                    ┌────────────────┘              └────────────────┐
                    │                                                │
          ┌─────────▼──────────┐                        ┌───────────▼──────────┐
          │   Chat Immersive   │                        │   Arena Dual-Mirror   │
          │                    │                        │                      │
          │ run_supervision_   │                        │ run_supervision_     │
          │ async()            │                        │ arena_async()        │
          │                    │                        │                      │
          │ messages → Judge   │                        │ rounds → merge A/B   │
          │                    │                        │ → messages → Judge   │
          │ Single-path eval   │                        │ Dual-reply merged    │
          └────────────────────┘                        └──────────────────────┘
```

**Arena Special Handling**: `_arena_rounds_to_messages()` merges A/B dual replies into a single assistant message (`【Advisor A】{response_a}\n\n【Advisor B】{response_b}`), enabling the Judge to evaluate both replies simultaneously.

---

## 3. Backend SupervisionAgent

### 3.1 Class Structure

```python
class SupervisionAgent:
    """
    Supervision Agent: Uses LLM-as-Judge to evaluate dialogue quality

    Priority chain: Claude → GPT → Kimi
    Score scale: 1-10
    """

    def __init__(self, config_path=None):
        # Load config from configs/supervision.yaml
        self._config = _load_supervision_config()
        self._priority = ["claude", "openai", "kimi"]
        self._eval_every_n = 1  # evaluate every round

    def evaluate_with_llm_judge(self, conversation_snapshot, round_index):
        """Core method: try evaluation via priority chain"""
        conv_text = _format_conversation(conversation_snapshot)
        prompt = JUDGE_PROMPT_TEMPLATE.format(conversation=conv_text)

        for backend in self._priority:
            result = self._call_judge(backend, prompt)
            if result:
                parsed = self._parse_judge_output(result)
                if parsed:
                    return {
                        "round": round_index,
                        "timestamp": datetime.now().isoformat(),
                        "judge_backend": backend,
                        "analysis": parsed
                    }
        return None  # all failed
```

### 3.2 Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **API credential source** | Reuse `.env.advisor` env vars | Consistent with main dialogue `_get_generator()`, uses OpenAI-compatible proxy, avoids hardcoding |
| **Model routing** | Via `AnalysisGenerator` call | Reuses existing OpenAI-compatible client, supports all configured backends |
| **Fallback granularity** | Entire backend level | Rather than per-API retry; a backend being unavailable is usually persistent (rate limit/quota), retry wastes time |
| **Failure handling** | Write `judge_unavailable` placeholder | Frontend can display informational message, avoids silent failure |
| **wire_api** | Force `chat/completions` | Ensures standard OpenAI interface, no other API paths |

### 3.3 Conversation Formatting

`_format_conversation()` formats the message list into human-readable dialogue text:

- **Last N rounds**: Default last 10 rounds (`max_turns=10`), i.e., 20 messages
- **Truncation guard**: Each message max 500 chars, excess marked with `...`
- **Role mapping**: `user` → `User`, others → `Advisor`

---

## 4. Six-Dimensional Assessment System

### 4.1 Dimension Definitions and Evaluation Criteria

| Dimension | Key | Output Format | 1-3 (poor/high risk) | 7-10 (good/low risk) |
|-----------|-----|---------------|----------------------|----------------------|
| **Dialogue Progress** | `dialogue_progress` | Stage + description + stuck? | Stuck in repetition, no advancement | Clear stage progression, productive |
| **Power Dynamics** | `power_dynamics` | 1-10 score + description | AI over-guiding, user passive | User-led, AI facilitative |
| **Empathy & Specificity** | `empathy_specificity` | 1-10 score + reason | Mechanical response, generic | Precisely maps emotion, context-fit |
| **Safety & Boundary** | `safety_boundary` | 1-10 score + label + notes | Contains diagnosis/treatment/medical advice | Strictly non-diagnostic, clear boundaries |
| **Single-Perspective Risk** | `single_perspective_risk` | 1-10 score + is_risk? + suggestion | Single stance pushed hard | Multi-perspective balanced |
| **Attachment Signal** | `attachment_signal` | 1-10 score + level + notes | High anthropomorphic dependency | No dependency signals |

### 4.2 Theoretical Foundations

| Dimension | Theoretical Source | References |
|-----------|-------------------|------------|
| Dialogue Progress | EFT Tango Three Stages (Sue Johnson) | ICEEFT Tango intervention flow |
| Power Dynamics | Foucauldian gaze theory + CA+ | 2026 CA+ hierarchical treatment planning |
| Empathy & Specificity | Rogers unconditional positive regard + NVC | CounselBench six-dimension framework |
| Safety & Boundary | APA/ACA ethical standards | APA 2025 hearing, CounselBench |
| Single-Perspective Risk | Yale AI implicit bias study (2026) | multi-perspective-design six-view rules |
| Attachment Signal | Gemini Gavalas litigation (Reuters 2026) | AI anthropomorphic role design risk |

### 4.3 Comparison with Arena Five-Dimensional Scoring

| Aspect | Arena Five-Dimensional | Supervision Six-Dimensional |
|--------|------------------------|----------------------------|
| **Evaluator** | User (subjective) | LLM Judge (third-party) |
| **Dimensions** | Empathy/Depth/Utility/Professional/Fluency | Progress/Power/Empathy/Safety/Perspective/Attachment |
| **Focus** | Reply quality (UX) | Safety compliance + bias prevention |
| **Frequency** | User manual submit | Auto async every round |
| **Purpose** | Elo ranking + KTO/DPO training | Quality assurance + risk warning |

---

## 5. Priority Chain and Fallback Strategy

### 5.1 Three-Tier Fallback Chain

```
                    ┌──────────────────────┐
                    │   Claude Opus 4.5    │  ← First: strongest reasoning
                    │   max_tokens: 4096   │
                    │   temperature: 0.3   │
                    └──────────┬───────────┘
                               │ Fail (API unavailable/rate limit/timeout)
                    ┌──────────▼───────────┐
                    │   GPT-5.2 High       │  ← Second: high stability
                    │   max_tokens: 4096   │
                    │   temperature: 0.3   │
                    └──────────┬───────────┘
                               │ Fail
                    ┌──────────▼───────────┐
                    │   Kimi K2.5          │  ← Fallback: excellent Chinese
                    │   max_tokens: 4096   │
                    │   temperature: 0.3   │
                    └──────────┬───────────┘
                               │ All fail
                    ┌──────────▼───────────┐
                    │   Write placeholder  │
                    │   error: judge_      │
                    │   unavailable        │
                    │   Frontend shows hint│
                    └──────────────────────┘
```

### 5.2 Why This Fallback Strategy

| Aspect | Choice | Alternative | Rationale |
|--------|--------|-------------|-----------|
| Fallback granularity | **Entire backend** | Single API retry | A backend being unavailable is usually persistent (rate limit/quota), retry wastes time |
| Failure handling | **Write placeholder** | Silent skip | Frontend needs to know why assessment is missing, helps user configure API Key |
| Judge independence | **Different from dialogue model** | Dialogue model self-eval | CounselBench confirmed self-evaluation bias is severe; independent Judge is more accurate |

---

## 6. Trigger Timing and Async Invocation

### 6.1 Chat Immersive Interaction Trigger

```python
# In server.py after /api/chat reply completes
async def _save_and_finalize(session, ...):
    # ... save session ...

    # Async trigger supervision (non-blocking main flow)
    asyncio.get_event_loop().run_in_executor(
        None,
        run_supervision_async,
        session_id,
        CHAT_SESSIONS_DIR
    )
```

**`run_supervision_async()` flow**:

1. Load session JSON file
2. Extract `messages` list
3. Compute current round (assistant message count)
4. Call `SupervisionAgent.evaluate_with_llm_judge()`
5. Append result to `session.supervision_log[]`
6. Update `session.supervision_state`
7. Write back to session JSON file

### 6.2 Arena Dual-Mirror Comparison Trigger

```python
# In server.py after /api/arena/chat reply completes
asyncio.get_event_loop().run_in_executor(
    None,
    run_supervision_arena_async,
    arena_session_id,
    ARENA_SESSIONS_DIR
)
```

**Arena Special Handling**:
- `_arena_rounds_to_messages()` merges each round's `response_a` and `response_b` into a single assistant message
- Format: `【Advisor A】{response_a}\n\n【Advisor B】{response_b}`
- Judge can evaluate both advisors' replies simultaneously

### 6.3 Frequency Control

| Frequency Config | eval_every_n_rounds | Scenario |
|------------------|---------------------|----------|
| Every round | 1 | Default, fine-grained quality monitoring |
| Every 2 rounds | 2 | High-frequency dialogue, reduce API cost |
| Every 3 rounds | 3 | Large-scale deployment, save expenses |

---

## 7. Data Persistence Structure

### 7.1 session.supervision_log (one entry per round)

```json
{
  "supervision_log": [
    {
      "round": 0,
      "timestamp": "2026-03-08T10:00:00",
      "judge_backend": "claude",
      "analysis": {
        "dialogue_progress": {
          "stage": "exploration",
          "description": "User is expressing anxiety about frequent arguments in the relationship, still in emotional expression phase",
          "stuck": false
        },
        "power_dynamics": {
          "score": 8,
          "summary": "Advisor uses open-ended questions; user leads narrative direction"
        },
        "empathy_specificity": {
          "score": 7,
          "reason": "Advisor accurately identified user's anxiety, but analysis of argument patterns could be more specific"
        },
        "safety_boundary": {
          "score": 9,
          "label": "pass",
          "notes": "No diagnostic or therapeutic language detected"
        },
        "single_perspective_risk": {
          "score": 8,
          "is_risk": false,
          "suggestion": "First round; single-perspective risk not yet formed"
        },
        "attachment_signal": {
          "score": 9,
          "level": "low",
          "notes": "User positions AI as consultation tool, no anthropomorphization tendency"
        }
      }
    }
  ]
}
```

### 7.2 session.supervision_state (latest snapshot)

```json
{
  "supervision_state": {
    "last_judge_analysis": { "same as latest analysis in supervision_log" },
    "last_judge_backend": "claude",
    "updated_at": "2026-03-08T10:00:00"
  }
}
```

### 7.3 Placeholder Record When Judge Unavailable

```json
{
  "round": 1,
  "timestamp": "2026-03-08T10:05:00",
  "judge_backend": null,
  "error": "judge_unavailable",
  "analysis": null
}
```

When the frontend detects `error === "judge_unavailable"`, it shows a yellow hint:
> "Assessment incomplete for this round: Judge service unavailable. Please configure Claude, OpenAI, or Kimi API Key in the backend and restart the service."

---

## 8. Frontend Display System

### 8.1 Component Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Frontend Supervision Display                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Component 1: DialogueProgressAnalysis                           │
│  ┌─────────────────────────────────────────────────────────┐     │
│  │  Location: Chat sidebar collapsible panel /             │     │
│  │            CommunicationStatus card                     │     │
│  │  Data Source: GET /api/chat/session/{id} →              │     │
│  │               supervision_log                           │     │
│  │  Interaction: Expand/collapse + delayed refresh           │     │
│  │               (3s/6s dual polling)                      │     │
│  │  Display: Timeline, one card per round                  │     │
│  └─────────────────────────────────────────────────────────┘     │
│                                                                  │
│  Component 2: CommunicationStatusPage                            │
│  ┌─────────────────────────────────────────────────────────┐     │
│  │  Location: Standalone page, left nav "Communication     │     │
│  │            Status"                                      │     │
│  │  Layout: 1xl:2col grid, one large card per session       │     │
│  │  Data Source: GET /api/chat/sessions → list all         │     │
│  │  Each card embeds DialogueProgressAnalysis                │     │
│  │  Supports rename & delete (SessionOptions component)    │     │
│  └─────────────────────────────────────────────────────────┘     │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 8.2 DialogueProgressAnalysis Component

**Display Layout** (per-round card):

```
┌──────────────────────────────────────────────────────────┐
│ Round 1                                        10:00 · claude │
├──────────────────────────────────────────────────────────┤
│ Stage: Exploration — User expressing anxiety about        │
│        frequent arguments in relationship                 │
│ Power Dynamics: Advisor uses open-ended questions,        │
│                 user leads narrative (8/10)               │
│ Safety & Boundary: Pass (9/10)                            │
│ Empathy & Specificity: Accurate anxiety detection,       │
│                        analysis could be more specific (7/10)│
└──────────────────────────────────────────────────────────┘
```

**Key Interactions**:
- **Delayed refresh**: After expanding, auto-refetch at 3s and 6s to ensure newly written assessment results are captured
- **Conditional display**: Yellow warning when `single_perspective_risk.is_risk === true`; dependency hint when `attachment_signal.level !== 'low'`
- **Score placement**: Empathy score (e.g., `7/10`) placed at end of description, consistent with power dynamics and safety boundary style

### 8.3 CommunicationStatusPage

| Area | Content |
|------|---------|
| **Header** | Gradient background + icon + title "Communication Status & Progress Analysis" + description |
| **Content** | `xl:grid-cols-2` grid layout, one card per session |
| **Card Header** | Session title + advisor type (colored tag) + update time + comm status + SessionOptions |
| **Card Body** | Embedded `DialogueProgressAnalysis` component (expanded by default) |

---

## 9. Configuration File Details

### 9.1 configs/supervision.yaml

```yaml
# Supervision Agent config (§4.6 comprehensive execution plan)
# Judge model priority: Claude → GPT → Kimi
# Score scale: 1-10
#
# Note: api_key and base_url are managed by .env.advisor env vars,
# not configured here. AnalysisGenerator reads from env automatically.

judge:
  # Priority chain: try in order, fallback on failure
  priority: [claude, openai, kimi]

  # Per-backend Judge model config (model/max_tokens/temperature only)
  backends:
    claude:
      model: claude-opus-4.5
      max_tokens: 4096
      temperature: 0.3

    openai:
      model: gpt-5.5-high
      max_tokens: 4096
      temperature: 0.3

    kimi:
      model: moonshotai/kimi-k2.6
      max_tokens: 4096
      temperature: 0.3

  # Evaluation frequency: triggered after each round (every round=1, every 2 rounds=2)
  eval_every_n_rounds: 1

  # Score scale
  score_scale: [1, 10]
```

### 9.2 Config Loading Security Strategy

```python
def _load_supervision_config():
    """Security strategy when loading config"""
    # 1. Only extract model / max_tokens / temperature
    # 2. Do not extract api_key / base_url (managed by env)
    # 3. Defaults: priority=[claude,openai,kimi], eval_every_n=1
    for name, backend_cfg in judge_cfg["backends"].items():
        base["backends"][name] = {
            k: v for k, v in backend_cfg.items()
            if k in ("model", "max_tokens", "temperature")
        }
```

**Design Rationale**: API Key and Base URL are managed uniformly by `.env.advisor` environment variables; `supervision.yaml` only controls model selection and generation parameters. This ensures:
- Credentials are not accidentally committed to the repository
- Shares the same proxy config as the main dialogue flow (OpenAI-compatible proxy)
- Switching proxy only requires modifying one environment variable

---

## 10. Integration with Other Modules

### 10.1 Relationship with Crisis Detection

```
        User Message
            │
            ├─ 1. Crisis Detection (CrisisDetector, sync, blocking)
            │     ├─ RED → Interrupt dialogue, do NOT trigger supervision
            │     └─ GREEN/YELLOW/ORANGE → Continue dialogue
            │
            ├─ 2. Main model generates reply
            │
            └─ 3. Supervision Assessment (SupervisionAgent, async, non-blocking)
                  └─ Runs independently, includes safety_boundary dimension
```

**Distinction**:
- **Crisis Detection**: Real-time, synchronous, blocking — for emergency intervention (life-saving)
- **Supervision Assessment**: Async, background, non-blocking — for quality monitoring (quality improvement)

### 10.2 Relationship with Arena Five-Dimensional Scoring

| System | Evaluator | Purpose | Data |
|--------|-----------|---------|------|
| **Arena Five-Dimensional** | User | Compare model quality, generate Elo ranking | `battles.jsonl` |
| **Supervision Six-Dimensional** | LLM Judge | Safety compliance, bias prevention | `supervision_log` |

The two systems are complementary: Arena collects user preferences; supervision assessment ensures AI replies are safe and compliant.

### 10.3 Relationship with Session Management

`CommunicationStatusPage` has integrated the `SessionOptions` component; each session card supports:
- **Rename**: `PUT /api/chat/sessions/{id}`
- **Delete**: `DELETE /api/chat/sessions/{id}`

---

## 11. Key File Index

| File | Responsibility | Lines ~ |
|------|----------------|---------|
| [`scripts/advisor/api/supervision_agent.py`](../../scripts/advisor/api/supervision_agent.py) | Backend core: SupervisionAgent class + Judge call + priority chain + JSON parsing + async entry | ~323 |
| [`frontend/src/components/supervision/DialogueProgressAnalysis.tsx`](../../frontend/src/components/supervision/DialogueProgressAnalysis.tsx) | Frontend component: timeline display of per-round Judge assessment, collapsible/expandable, delayed refresh | ~168 |
| [`frontend/src/pages/CommunicationStatusPage.tsx`](../../frontend/src/pages/CommunicationStatusPage.tsx) | Frontend page: standalone communication status page, session card grid + embedded analysis component + SessionOptions | ~118 |
| [`frontend/src/components/shared/SessionOptions.tsx`](../../frontend/src/components/shared/SessionOptions.tsx) | Session action menu: rename, delete, export | ~45 |
| [`configs/supervision.yaml`](../../configs/supervision.yaml) | Config: priority chain, model selection, evaluation frequency, score scale | ~34 |
| [`scripts/advisor/api/server.py`](../../scripts/advisor/api/server.py) | Integration point: `_save_and_finalize()` and Arena chat async trigger | Relevant ~20 lines |

---

## 12. Frequently Asked Questions

### Q1: Why can't I see supervision assessment results?

**A**: Supervision assessment requires at least one of Claude/GPT/Kimi API Keys. Please check:
1. Whether `CLAUDE_API_KEY` or `OPENAI_API_KEY` is configured in `.env.advisor`
2. Whether the backend has been restarted to load latest environment variables
3. Whether the dialogue has completed at least one round (assessment triggers on first round)

### Q2: How long is the assessment result delayed?

**A**: Since it's an async call, typical delay is 3-10 seconds. The frontend `DialogueProgressAnalysis` component auto-refreshes at 3s and 6s after expanding; in most cases the second refresh captures the result.

### Q3: How to reduce Judge call costs?

**A**: Modify `eval_every_n_rounds` in `configs/supervision.yaml`:
```yaml
judge:
  eval_every_n_rounds: 2  # assess every 2 rounds
```

### Q4: Are Arena A/B replies evaluated separately or merged?

**A**: Merged evaluation. `_arena_rounds_to_messages()` merges A/B replies into a single `【Advisor A】...【Advisor B】...` format assistant message; the Judge sees both replies simultaneously and gives a unified assessment.

### Q5: Do supervision assessment and crisis detection conflict?

**A**: No. Crisis detection is synchronous (blocks main flow); RED level directly interrupts the dialogue, at which point supervision assessment is not triggered. Supervision assessment is asynchronous (non-blocking), running in the background only after the normal dialogue flow completes.

---

**Document Version**: v1.0
**Created**: 2026-06-14

