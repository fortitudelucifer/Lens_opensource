# 安全伦理与四级危机干预系统

> 📌 **本文档定位**：这是 [多模态处理流水线文档](modality_fields_and_models.md) Section 20 的详细设计文档，专注于四级危机检测、知情同意、用词红线、前端安全组件、自助/专业资源体系和 Arena 安全治理。
>
> 更新于：2026-03-07

---

## 目录

- [1. 设计理念](#1-设计理念)
- [2. 四级危机检测架构](#2-四级危机检测架构)
- [3. 关键词配置详解](#3-关键词配置详解)
- [4. 用词红线（双重拦截）](#4-用词红线双重拦截)
- [5. 分级资源体系](#5-分级资源体系)
- [6. 知情同意与免责声明](#6-知情同意与免责声明)
- [7. 前端安全组件](#7-前端安全组件)
- [8. Arena 安全治理](#8-arena-安全治理)
- [9. 交流前测评系统集成](#9-交流前测评系统集成)
- [10. API 端点](#10-api-端点)
- [11. 配置文件清单与结构](#11-配置文件清单与结构)
- [12. 函数参考](#12-函数参考)
- [13. 集成点矩阵](#13-集成点矩阵)
- [14. 测试与验证](#14-测试与验证)

---

## 1. 设计理念

### 1.1 核心目标

安全伦理系统是产品上线前的**硬性 blocker**——没有通过安全审查的版本不允许对外发布。

| 挑战 | 解决方案 |
|------|----------|
| 自杀/自伤意念实时检测 | 四级关键词匹配 + 上下文累积感知 |
| 单字组合误触发（"猫想死"） | 第一人称主语前置检测 + 完整短语匹配 |
| 新闻/影视/他人经历误报 | 误触发排除规则 → 自动降级 |
| AI 生成不当诊断用语 | 用词红线后处理：双重拦截（prompt 层 + 输出扫描层） |
| 产品定位模糊（医疗 vs 工具） | 知情同意弹窗 + 永久可见免责条 |
| 危机时用户无法获取资源 | 侧边栏固定应急按钮 + 分级资源推送 |
| Arena 路径绕过安全检查 | Arena 完整接入四级危机检测 + 禁用词后处理 |

### 1.2 设计原则

```
┌─────────────────────────────────────────────────────────────────┐
│                      安全设计原则                                 │
├─────────────────────────────────────────────────────────────────┤
│  1. 宁可误报不可漏报：危机检测倾向高敏感，通过降级机制控制误报  │
│  2. AI 不替代人类：RED 级别完全中断 AI，只展示人工审核过的模板   │
│  3. 模板固定措辞：危机响应文本写在 YAML 中，不经过模型生成       │
│  4. 分层递进：GREEN→YELLOW→ORANGE→RED，引导强度逐级上升         │
│  5. 可审计：RED 级别事件全量归档到 crisis_archive/               │
│  6. 全路径覆盖：Chat 和 Arena 共享同一个 CrisisDetector 实例    │
│  7. 用户主权：知情同意前不可使用，测评注入开关用户自主控制       │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. 四级危机检测架构

### 2.1 整体流程图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       Crisis Detection Pipeline                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   用户消息                                                                   │
│      │                                                                       │
│      ▼                                                                       │
│   ┌──────────────────┐                                                       │
│   │  Step 1: 精确匹配 │──── "不想活了" "自杀" "割腕" 等 20+ 词              │
│   │  (exact)          │     无歧义直接命中                                    │
│   └────────┬─────────┘                                                       │
│            │ 未命中                                                           │
│            ▼                                                                  │
│   ┌──────────────────┐                                                       │
│   │  Step 2: 第一人称 │──── "想死" "去死" "不想活"                           │
│   │  受限匹配         │     需"我/自己/本人/俺/咱"在前 5 字符内              │
│   │  (first_person)   │     "猫想死" → 不触发 ✅                             │
│   └────────┬─────────┘                                                       │
│            │ 未命中                                                           │
│            ▼                                                                  │
│   ┌──────────────────┐                                                       │
│   │  Step 3: 完整短语 │──── "想去死" "不想再活" "永远睡过去" 等              │
│   │  匹配(proximity)  │     require_first_person 可选                        │
│   └────────┬─────────┘                                                       │
│            │ 未命中                                                           │
│            ▼                                                                  │
│   ┌──────────────────┐                                                       │
│   │  Step 4: 上下文   │──── 最近 3 轮消息累积检测                            │
│   │  累积感知         │     yellow×3 → ORANGE                                │
│   │  (context)        │     orange×2 → RED                                   │
│   └────────┬─────────┘                                                       │
│            │                                                                  │
│            ▼                                                                  │
│   ┌──────────────────┐                                                       │
│   │  Step 5: 误触发   │──── "新闻里说" "电影里" "开玩笑" 等                  │
│   │  排除 + 降级      │     命中排除模式 → 级别 -1                           │
│   └──────────────────┘                                                       │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 四级响应矩阵

| 级别 | 触发条件 | AI 行为 | 前端表现 | 归档 |
|------|----------|---------|----------|------|
| 🟢 **GREEN** | 正常对话 | 正常生成 | 标准界面 | 否 |
| 🟡 **YELLOW** | 焦虑/失眠/崩溃等（22 个精确词） | 正常生成 + safety prompt 注入 | 显示自助资源卡片 | 否 |
| 🟠 **ORANGE** | 绝望/自残/家暴等（22 个精确词 + 6 短语） | 正常生成 + 高风险引导注入 | 强制显示热线 + 专业引导 | 否 |
| 🔴 **RED** | 自杀/自伤意念（20 个精确词 + 3 第一人称词 + 9 短语） | **完全中断** → 固定模板 | 全屏危机干预 | ✅ `crisis_archive/` |

### 2.3 第一人称主语前置检测算法

解决 `"那只猫想死"` 类误触发：

```python
_FIRST_PERSON = re.compile(r"(我|自己|本人|俺|咱)")

def _match_first_person_keywords(self, text, keywords, matched):
    for kw in keywords:
        idx = text.find(kw)
        if idx < 0:
            continue
        prefix = text[max(0, idx - 5):idx]   # 前 5 字符窗口
        if self._FIRST_PERSON.search(prefix):
            matched.append(kw)
            hit = True
```

| 输入 | 关键词 | 前缀窗口 | 匹配结果 | 原因 |
|------|--------|----------|----------|------|
| "我想死" | 想死 | "我" | ✅ RED | "我"在窗口内 |
| "我真的想死" | 想死 | "真的" → 再扩展含"我" | ✅ RED | "我"在前 5 字符 |
| "那只猫想死" | 想死 | "只猫" | ❌ 不触发 | 无第一人称 |
| "他说他想死" | 想死 | "说他" | ❌ 不触发 | "他"不是第一人称 |
| "想死" (无主语) | 想死 | "" | ❌ 不触发 | 空前缀 |

### 2.4 上下文累积感知

单条消息未达高级别，但连续多轮出现困扰信号时自动升级：

```python
def _check_context_escalation(self, recent_messages):
    yellow_count, orange_count = 0, 0
    for msg in recent_messages[-3:]:  # 最近 3 轮
        if self._match_exact(msg, self._yellow_exact, []):
            yellow_count += 1
        if self._match_exact(msg, self._orange_exact, []):
            orange_count += 1
    if orange_count >= 2: return CrisisLevel.RED
    if yellow_count >= 3: return CrisisLevel.ORANGE
    if yellow_count >= 2: return CrisisLevel.YELLOW
    return CrisisLevel.GREEN
```

| 累积条件 | 升级结果 | 设计意图 |
|----------|----------|----------|
| 最近 3 轮中 yellow ≥ 2 次 | → YELLOW | 持续低度困扰需关注 |
| 最近 3 轮中 yellow ≥ 3 次 | → ORANGE | 困扰强度在升级 |
| 最近 3 轮中 orange ≥ 2 次 | → RED | 高风险信号反复出现 |

### 2.5 误触发排除与降级

当消息匹配以下模式时，自动降级一级（RED→ORANGE, ORANGE→YELLOW）：

| 排除模式 | 说明 |
|----------|------|
| "新闻里说" | 讨论社会事件 |
| "电影里" / "电视剧" | 影视内容 |
| "小说里" | 文学作品 |
| "听说有人" / "朋友说" / "别人家" | 转述他人 |
| "历史上" | 历史事件 |
| "如果假设" | 假设性讨论 |
| "开玩笑" | 明确的非严肃语境 |
| "角色扮演" | 游戏/创作场景 |

```python
downgraded = False
if is_false_positive and level >= CrisisLevel.ORANGE:
    level = CrisisLevel(level - 1)  # RED→ORANGE 或 ORANGE→YELLOW
    downgraded = True
```

---

## 3. 关键词配置详解

**核心文件**: `configs/crisis_keywords.yaml`

### 3.1 RED 信号词库（自杀/自伤意念）

| 匹配类型 | 数量 | 示例 | 触发条件 |
|----------|------|------|----------|
| **精确匹配** | 20 词 | "不想活了" "自杀" "割腕" "跳桥" "烧炭" "上吊" "活不下去" | 消息中包含即触发 |
| **第一人称受限** | 3 词 | "想死" "去死" "不想活" | 前 5 字符内需有"我/自己/本人/俺/咱" |
| **完整短语** | 9 短语 | "想去死" "不想再活" "永远睡过去" "不想醒来" "了断一切" | 完整短语匹配，部分需第一人称 |

### 3.2 ORANGE 信号词库（高风险）

| 匹配类型 | 数量 | 示例 |
|----------|------|------|
| **精确匹配** | 22 词 | "绝望" "自残" "家暴" "他打了我" "是多余的" "我是废物" "消失就好了" "不配被爱" |
| **完整短语** | 6 短语 | "打我打得" "控制我的生活" "想伤害自己" "好想消失" |

### 3.3 YELLOW 信号词库（中度困扰）

| 数量 | 示例 |
|------|------|
| 22 词 | "很焦虑" "严重失眠" "情绪崩溃" "好想哭" "喘不过气" "恐慌发作" "暴饮暴食" "酒精依赖" "不想见人" |

### 3.4 词库统计

| 级别 | 精确词 | 第一人称受限 | 短语 | 合计触发条件 |
|------|--------|-------------|------|-------------|
| RED | 20 | 3 | 9 | 32 |
| ORANGE | 22 | 0 | 6 | 28 |
| YELLOW | 22 | 0 | 0 | 22 |
| **总计** | **64** | **3** | **15** | **82** |

---

## 4. 用词红线（双重拦截）

### 4.1 第一层：System Prompt 指令

所有 Agent 的 system prompt 中隐含安全边界指令：

> "你不是医生，不提供诊断、治疗或用药建议。绝不使用'你患有XX症'等诊断性表述。"

### 4.2 第二层：输出后处理扫描

AI 回复生成后，经过 `check_response_prohibited()` 逐词扫描：

```python
def check_response_prohibited(self, ai_response):
    violations = []
    for category, words in self._prohibited.items():
        for w in words:
            if w in ai_response:
                violations.append(f"[{category}] {w}")
    return violations
```

命中后替换处理：

```python
for v in violations:
    word = v.split("] ", 1)[-1]
    full_reply = full_reply.replace(word, "（此处表述不当，已移除）")
```

### 4.3 禁用词分类

| 类别 | 禁用词 | 数量 |
|------|--------|------|
| **临床术语** | "诊断你为" "你患有" "你的症状是" "确诊" "病历" "处方" "开药" "用药建议" "治疗方案" "临床表现" | 10 |
| **边界越权** | "你必须" "你应该马上去" "你的问题很严重" "你有心理疾病" "你需要吃药" "你是抑郁症" "你是焦虑症" "你有人格障碍" | 8 |
| **合计** | | **18** |

---

## 5. 分级资源体系

### 5.1 资源触发矩阵

| 级别 | 自助资源 | 专业引导 | 热线 | 展示方式 |
|------|----------|----------|------|----------|
| GREEN | — | — | — | — |
| YELLOW | ✅ | — | 末尾提及 | 卡片 + system prompt 提示 |
| ORANGE | — | ✅ | ✅ 强制显示 | 回复中 + 浮动面板 |
| RED | — | — | ✅ 全屏 | AI 中断 + 固定模板 |

### 5.2 自助资源清单（YELLOW 级别，`GET /api/safety/self-help`）

| 模块 | 图标 | 技巧 | 适用场景 |
|------|------|------|---------|
| 🌬️ **呼吸放松** | wind | 4-4-6 呼吸法：吸4秒→屏4秒→呼6秒 | 焦虑、紧张、心跳加速 |
| | | 腹式呼吸：双手放在腹部，5 分钟 | 入睡困难、情绪激动 |
| ⚓ **接地技巧** | anchor | 5-4-3-2-1 感官法：5 看 4 听 3 触 2 闻 1 尝 | 恐慌发作、思绪失控 |
| | | 冰块法：握冰块集中注意力 | 极度波动、自伤冲动 |
| ✍️ **情绪书写** | pen-line | "此刻我的感受是_____，因为_____" | 情绪识别、自我觉察 |
| | | "如果我的情绪是一种天气，现在是_____" | |
| 💓 **身体照顾** | heart-pulse | 喝温水、伸展 2 分钟、洗热水脸、散步 10 分钟 | 低能量、不想动 |
| 🦋 **紧急安抚** | shield-heart | 蝴蝶拥抱：双臂交叉轻拍肩膀 | 极度悲伤或害怕 |
| | | 安全空间想象：闭眼想象安全放松的地方 | 需要暂时抽离 |

### 5.3 专业资源引导（ORANGE 级别，`GET /api/safety/professional`）

| 资源 | 内容 |
|------|------|
| **如何找咨询师** | 5 步指引：确定需求 → 选平台 → 查资质（国家二/三级证书） → 首次咨询（50 分钟，300-800 元） → 不合适可换 |
| **第一次咨询** | 降低门槛说明：可以沉默、严格保密、不急着解决、建立信任就好 |
| **在线平台** | 壹心理 · 简单心理 · KnowYourself |

### 5.4 热线资源（ORANGE/RED 级别，`GET /api/safety/hotlines`）

**全国性热线**：

| 优先级 | 名称 | 号码 | 时间 | 说明 |
|--------|------|------|------|------|
| 1 | 全国心理援助热线 | 400-161-9995 | 24h | 免费、保密 |
| 2 | 北京危机干预热线 | 010-82951332 | 24h | 回龙观医院 |
| 3 | 生命热线 | 400-821-1215 | 8:00-22:00 | 希望24热线 |

**地区性机构**：

| 地区 | 机构 | 号码 | 时间 |
|------|------|------|------|
| 上海 | 精神卫生中心 | 021-64383562 | 工作日 8-17 |
| 广州 | 心理援助热线 | 020-81899120 | 24h |
| 深圳 | 心理危机干预热线 | 0755-25629459 | 24h |
| 武汉 | 心理援助热线 | 027-85844666 | 8:00-22:00 |
| 成都 | 心理援助热线 | 028-87577510 | 9:00-21:00 |
| 南京 | 心理危机干预中心 | 025-83712977 | 24h |

**特殊群体资源**：

| 热线 | 号码 | 适用 | 触发标签 |
|------|------|------|----------|
| 妇女维权专线 | 12338 | 家暴、婚姻权益 | 家暴、暴力 |
| 未成年人保护热线 | 12355 | 青少年心理、校园暴力 | 未成年、校园暴力 |

### 5.5 RED 级别响应模板

```yaml
red:
  title: "你现在的感受很重要，请让专业人士帮助你"
  message: |
    我感受到你现在正经历着很大的痛苦。这种感受是真实的，你不需要独自面对。

    请现在就拨打以下热线，会有专业的人倾听你、陪伴你：

    📞 全国心理援助热线：400-161-9995（24小时）
    📞 北京危机干预热线：010-82951332（24小时）

    他们受过专业训练，你说的每一句话都会被保密和尊重。
    拨打电话不需要做任何准备，打过去就好。
  stop_ai: true    # ← 完全中断 AI 生成
```

### 5.6 YELLOW 级别 System Prompt 注入

```python
def get_safety_prompt_injection(self, level):
    if level == CrisisLevel.YELLOW:
        return (
            "\n\n【安全引导】用户当前可能正在经历中度情绪困扰。"
            "请优先共情和倾听，适当建议放松技巧（如深呼吸），"
            "但不要使用诊断性语言，不要说'你有XX症'。"
            "可以温和地提及如果持续困扰可以寻求专业帮助。"
        )
    if level == CrisisLevel.ORANGE:
        return (
            "\n\n【安全引导-高风险】用户可能正在经历严重困扰。"
            "请优先表达关心和陪伴，避免任何可能加重负面情绪的分析。"
            "在回复末尾温和地引导用户联系专业资源（全国心理援助热线 400-161-9995）。"
            "绝不要使用诊断性语言或给出治疗建议。"
        )
```

---

## 6. 知情同意与免责声明

### 6.1 首次使用弹窗（`ConsentModal`）

**核心文件**: `configs/consent_text.yaml`

用户首次访问时必须阅读并确认的 4 个板块：

| 板块 | 图标 | 核心内容 |
|------|------|---------|
| ⚠️ 产品定位声明 | AlertTriangle | 非医疗器械，不提供诊断/治疗/处方 |
| 🛡️ AI 能力边界 | ShieldCheck | 分析基于有限文本，可能不准确，仅供参考 |
| 🔒 隐私保护 | Lock | 数据仅本地保存，可随时删除，匿名化处理 |
| ✅ 使用承诺 | UserCheck | 理解非医疗定位 + 同意危机时拨热线 + 年满 18 岁 |

确认状态持久化到 `localStorage('lens_consent_accepted')`，刷新不再弹出。

### 6.2 测评引导弹窗

知情同意完成后，若用户尚未完成交流前测评，自动弹出测评引导：

| 元素 | 内容 |
|------|------|
| 标题 | "建议先完成交流测评" |
| 说明 | 约 1 分钟，帮助 AI 更好地理解你 |
| 操作 | 「立即测评」跳转 `/assessment`，「稍后再说」关闭 |
| 频率 | 仅弹出一次（`localStorage('lens_assessment_prompted')`） |

### 6.3 永久可见免责条

Chat 页面与 Arena 页面顶部始终显示：

> ⚠️ 本功能仅供探索与参考，不构成诊断或治疗。如有需要，请寻求专业帮助。

### 6.4 底部提示

输入框下方显示：

> 内容仅供参考，AI 顾问不能替代专业医疗建议。

---

## 7. 前端安全组件

### 7.1 组件清单

| 组件 | 文件 | 位置 | 功能 |
|------|------|------|------|
| **CrisisBanner** | `components/safety/CrisisBanner.tsx` | 侧边栏底部固定 | 紧急求助按钮，点击直拨 400-161-9995 |
| **ConsentModal** | `components/safety/ConsentModal.tsx` | 全局遮罩层 (z-200) | 知情同意弹窗 + 测评引导弹窗 |
| **Disclaimer** | ArenaPage / ChatArea 内嵌 | 页面顶部 | 永久可见非诊断声明 |

### 7.2 紧急求助按钮位置

```
Sidebar
├── Navigation Items
│   ├── 知情同意
│   ├── 总览
│   ├── 沉浸式互动
│   ├── 双镜对比
│   ├── 交流测评
│   ├── ...
├── ─── 分隔线 ───
├── [📞 紧急求助]     ← 红色按钮，居中，tel: 链接
└── [主题切换]
```

---

## 8. Arena 安全治理

Arena（双镜对比）路径完整复用了 Chat 的安全架构，确保无安全盲区。

### 8.1 Arena 危机检测流程

```
POST /api/arena/chat
  │
  ├─ 从 session 最近 3 轮提取 user query
  ├─ _crisis_detector.detect(message, recent_user_msgs)
  │
  ├─ RED → 中断双路生成
  │   ├─ response_a = response_b = 危机模板文案
  │   ├─ crisis_level = "RED"
  │   ├─ requires_vote = false（前端不弹打分面板）
  │   ├─ 写入 crisis_archive/{session_id}.json（source: "arena"）
  │   └─ 提前返回
  │
  ├─ YELLOW/ORANGE → 注入安全引导
  │   ├─ system_a += safety_prompt_injection
  │   └─ system_b += safety_prompt_injection
  │
  └─ GREEN → 正常并发生成
      ├─ asyncio.gather(A, B)
      └─ _sanitize_with_crisis_guard(resp_a/resp_b)  ← 禁用词后处理
```

### 8.2 Arena 危机轮前端表现

| 元素 | 行为 |
|------|------|
| 双路回复 | 均显示相同的危机干预文案 |
| 消息下方 | 红色标签"已触发危机干预（本轮不参与评分）" |
| 打分面板 | 不弹出（`requires_vote=false`） |
| Toast | "已触发安全干预，本轮不参与评分" |
| 后续 | 用户可继续输入下一条消息 |

---

## 9. 交流前测评系统集成

测评结果可选注入 system prompt，增强 AI 对用户特点的理解：

### 9.1 注入控制

| 控制项 | 默认值 | 说明 |
|--------|--------|------|
| `inject_enabled` | `false` | 用户在测评结果页手动开启 |
| 注入范围 | Chat + Arena | 两个路径均检查最新测评的 `inject_enabled` |
| 注入内容 | 筛查结果 + 依恋风格 + 冲突模式（不含具体分数） | |

### 9.2 注入文本示例

```
【用户交流前测评结果（仅供参考，非诊断）】
- 抑郁筛查(PHQ-2): 筛查阴性
- 焦虑筛查(GAD-2): 筛查阳性
- 依恋风格倾向: 焦虑型（安全2/焦虑4/回避3）
- 冲突处理模式: 回避型
请结合以上信息调整回复策略，但不要直接告诉用户具体得分或评估结果标签。
```

---

## 10. API 端点

| 端点 | 方法 | 功能 | 数据源 |
|------|------|------|--------|
| `/api/safety/hotlines` | GET | 热线资源列表（按优先级排序） | `crisis_resources.yaml` |
| `/api/safety/consent` | GET | 知情同意文本 | `consent_text.yaml` |
| `/api/safety/self-help` | GET | 自助资源（呼吸/接地/书写/身体/安抚） | `crisis_resources.yaml` |
| `/api/safety/professional` | GET | 专业引导（找咨询师/首次咨询/平台） | `crisis_resources.yaml` |
| `/api/assessment/questions` | GET | 测评量表结构 | server.py 内置字典 |
| `/api/assessment/submit` | POST | 提交测评 + 计算解读 | → `advisor_out/assessments/` |
| `/api/assessment/toggle-inject` | POST | 开/关注入开关 | 修改最新测评 JSON |
| `/api/assessment/latest` | GET | 最新测评结果 | `advisor_out/assessments/` |

---

## 11. 配置文件清单与结构

```
configs/
├── crisis_keywords.yaml       # 82 条触发词 + 11 条排除模式 + 18 条禁用词
│   ├── red_signals            # exact(20) + first_person_only(3) + proximity_phrases(9)
│   ├── orange_signals         # exact(22) + proximity_phrases(6)
│   ├── yellow_signals         # exact(22)
│   ├── false_positive_patterns # 11 条误触发排除
│   └── prohibited_words       # clinical_terms(10) + boundary_violations(8)
│
├── crisis_resources.yaml      # 热线 + 地区机构 + 自助 + 专业引导 + 响应模板
│   ├── national_hotlines      # 4 条全国热线（含优先级）
│   ├── regional_resources     # 6 个城市机构
│   ├── special_resources      # 2 条特殊群体热线
│   ├── professional_guidance  # 找咨询师 + 首次咨询 + 3 个在线平台
│   ├── self_help_resources    # 5 大模块（呼吸/接地/书写/身体/安抚）
│   └── response_templates     # RED/ORANGE/YELLOW 三级固定文案
│
└── consent_text.yaml          # 知情同意 4 板块

advisor_out/
├── crisis_archive/            # RED 级别事件归档
│   └── {session_id}.json      # JSONL，每行 {session_id, message, matched, level, timestamp, source}
└── assessments/               # 交流前测评结果
    └── assess-{uuid8}.json    # 完整答案 + 解读 + context_injection + inject_enabled
```

---

## 12. 函数参考

### 12.1 `crisis_detector.py` — `CrisisDetector` 类

| 方法 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| `__init__()` | — | — | 加载 crisis_keywords.yaml + crisis_resources.yaml |
| `detect(message, recent_messages)` | str, list[str] | `CrisisResult` | 四级检测主入口（五步流水线） |
| `check_response_prohibited(ai_response)` | str | list[str] | 用词红线扫描，返回违规列表 |
| `get_safety_prompt_injection(level)` | CrisisLevel | str | 生成 YELLOW/ORANGE 注入文本 |
| `get_hotlines(top_n)` | int | list[dict] | 按优先级返回热线 |
| `_match_exact(text, keywords, matched)` | ... | bool | 精确匹配 |
| `_match_first_person_keywords(text, keywords, matched)` | ... | bool | 第一人称前置约束 |
| `_match_proximity(text, phrases, matched)` | ... | bool | 完整短语匹配 |
| `_check_false_positive(text)` | str | bool | 误触发排除检测 |
| `_check_context_escalation(recent_messages)` | list[str] | CrisisLevel | 上下文累积升级 |

### 12.2 数据类

```python
class CrisisLevel(IntEnum):
    GREEN = 0
    YELLOW = 1
    ORANGE = 2
    RED = 3

@dataclass
class CrisisResult:
    level: CrisisLevel
    matched_keywords: list[str]        # 命中的关键词列表
    response_template: Optional[dict]  # RED/ORANGE/YELLOW 的展示模板
    downgraded: bool                   # 是否因误触发排除而降级
```

---

## 13. 集成点矩阵

| 调用位置 | 文件 | 调用方法 | 行为 |
|----------|------|----------|------|
| `/api/chat` 入口 | server.py | `_crisis_detector.detect()` | RED→中断返回模板；YELLOW/ORANGE→注入safety prompt |
| `/api/chat` 回复后 | server.py | `check_response_prohibited()` | 扫描禁用词→替换 |
| `/api/arena/chat` 入口 | server.py | `_crisis_detector.detect()` | RED→中断，requires_vote=false；YELLOW/ORANGE→注入 |
| `/api/arena/chat` 回复后 | server.py | `_sanitize_with_crisis_guard()` | 双路回复禁用词后处理 |
| 前端 ConsentModal | ConsentModal.tsx | — | localStorage 检查→弹窗 |
| 前端 Sidebar | Sidebar.tsx | — | 紧急求助 tel: 按钮 |
| 前端 ArenaPage | ArenaPage.tsx | 检查 `requires_vote` | RED轮不弹评分面板 |
| 前端 ArenaPage | ArenaPage.tsx | 检查 `crisisLevel` | 显示红色危机标签 |

---

## 14. 测试与验证

### 14.1 已验证场景

| 场景 | 输入 | 预期 | 实际 | 状态 |
|------|------|------|------|------|
| RED 精确匹配 | "我想自杀" | RED，中断 AI | ✅ RED | ✅ |
| RED 第一人称受限 | "我想死" | RED | ✅ RED | ✅ |
| 误触发排除 | "猫想死" | 不触发 | ✅ GREEN | ✅ |
| 误触发降级 | "电影里有人自杀" | RED→ORANGE | ✅ ORANGE | ✅ |
| Arena RED | "我想自杀"（Arena 路径） | requires_vote=false | ✅ | ✅ |
| 禁用词后处理 | AI 输出"你患有抑郁症" | 替换为"已移除" | ✅ | ✅ |
| 上下文累积 | 3 轮连续 YELLOW 词 | → ORANGE | ✅ | ✅ |
| 知情同意 | 首次访问 | 弹窗显示 | ✅ | ✅ |

---

**文档版本**: v2.0
**创建时间**: 2026-03-06
**最后更新**: 2026-03-07
**关联主文档**: [modality_fields_and_models.md](modality_fields_and_models.md) Section 20
**核心脚本**: `scripts/advisor/api/crisis_detector.py`
**配置文件**: `configs/crisis_keywords.yaml`, `configs/crisis_resources.yaml`, `configs/consent_text.yaml`
**前端组件**: `frontend/src/components/safety/`
