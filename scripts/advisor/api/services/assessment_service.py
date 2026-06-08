"""services/assessment_service.py — 交流前测评（S3.3）

从 server.py 迁移（Step 5）：
  - `ASSESSMENT_QUESTIONS`       题库字典（常量）
  - `_interpret_phq2`            → `interpret_phq2`
  - `_interpret_gad2`            → `interpret_gad2`
  - `_interpret_attachment`      → `interpret_attachment`
  - `_interpret_conflict`        → `interpret_conflict`
  - `_build_assessment_context`  → `build_assessment_context`

无外部状态依赖，纯计算函数 + 常量字典。
"""
from __future__ import annotations


ASSESSMENT_QUESTIONS = {
    "phq2": {
        "title": "PHQ-2 抑郁筛查",
        "description": "过去两周内，你是否受到以下问题的困扰？",
        "disclaimer": "本筛查仅供参考，不构成诊断。筛查阳性建议进一步评估。",
        "options": [
            {"value": 0, "label": "完全没有"},
            {"value": 1, "label": "有几天"},
            {"value": 2, "label": "一半以上的天数"},
            {"value": 3, "label": "几乎每天"},
        ],
        "items": [
            {"id": "phq2_1", "text": "做事时提不起劲或没有兴趣"},
            {"id": "phq2_2", "text": "感到心情低落、沮丧或绝望"},
        ],
    },
    "gad2": {
        "title": "GAD-2 焦虑筛查",
        "description": "过去两周内，你是否受到以下问题的困扰？",
        "disclaimer": "本筛查仅供参考，不构成诊断。筛查阳性建议进一步评估。",
        "options": [
            {"value": 0, "label": "完全没有"},
            {"value": 1, "label": "有几天"},
            {"value": 2, "label": "一半以上的天数"},
            {"value": 3, "label": "几乎每天"},
        ],
        "items": [
            {"id": "gad2_1", "text": "感到紧张、焦虑或烦躁"},
            {"id": "gad2_2", "text": "不能停止或控制担忧"},
        ],
    },
    "attachment": {
        "title": "依恋风格（简化版）",
        "description": "请选择最符合你在亲密关系中感受的选项。",
        "disclaimer": "结果仅作参考，不代表诊断。",
        "options": [
            {"value": 1, "label": "完全不符合"},
            {"value": 2, "label": "有点不符合"},
            {"value": 3, "label": "不确定"},
            {"value": 4, "label": "有点符合"},
            {"value": 5, "label": "非常符合"},
        ],
        "items": [
            {"id": "att_1", "text": "我觉得和伴侣亲近是一件轻松自在的事", "dimension": "secure"},
            {"id": "att_2", "text": "我常常担心伴侣不够爱我或会离开我", "dimension": "anxious"},
            {"id": "att_3", "text": "当关系变得太亲密时，我会不自觉地想要拉开距离", "dimension": "avoidant"},
        ],
    },
    "conflict": {
        "title": "冲突处理模式（Thomas-Kilmann 简化版）",
        "description": "当与伴侣发生分歧时，你最常采用哪种方式？",
        "disclaimer": "结果仅作参考。",
        "type": "single_choice",
        "items": [
            {"id": "conflict_competing", "text": "坚持自己的立场，说服对方接受", "mode": "competing", "label": "竞争型"},
            {"id": "conflict_accommodating", "text": "放弃自己的想法，优先满足对方", "mode": "accommodating", "label": "迁就型"},
            {"id": "conflict_avoiding", "text": "回避冲突，尽量不讨论分歧话题", "mode": "avoiding", "label": "回避型"},
            {"id": "conflict_collaborating", "text": "和对方一起想办法，寻找双赢方案", "mode": "collaborating", "label": "合作型"},
            {"id": "conflict_compromising", "text": "各退一步，找一个折中方案", "mode": "compromising", "label": "妥协型"},
        ],
    },
}


def interpret_phq2(total: int) -> dict:
    if total >= 3:
        return {"level": "positive", "label": "筛查阳性", "suggestion": "PHQ-2 得分 ≥3，建议进一步完成 PHQ-9 全量筛查或咨询专业人士。这不代表诊断，仅提示需关注。"}
    return {"level": "negative", "label": "筛查阴性", "suggestion": "PHQ-2 得分较低，目前抑郁风险较小。如有持续困扰，仍建议关注自身感受。"}


def interpret_gad2(total: int) -> dict:
    if total >= 3:
        return {"level": "positive", "label": "筛查阳性", "suggestion": "GAD-2 得分 ≥3，建议进一步完成 GAD-7 全量筛查或咨询专业人士。这不代表诊断，仅提示需关注。"}
    return {"level": "negative", "label": "筛查阴性", "suggestion": "GAD-2 得分较低，目前焦虑风险较小。如有持续困扰，仍建议关注自身感受。"}


def interpret_attachment(answers: dict) -> dict:
    secure = answers.get("att_1", 3)
    anxious = answers.get("att_2", 3)
    avoidant = answers.get("att_3", 3)
    scores = {"secure": secure, "anxious": anxious, "avoidant": avoidant}
    dominant = max(scores, key=scores.get)
    labels = {"secure": "安全型", "anxious": "焦虑型", "avoidant": "回避型"}
    descriptions = {
        "secure": "你在亲密关系中倾向于安全型依恋，能较自在地与伴侣亲近。这是一种健康的关系模式。",
        "anxious": "你在亲密关系中可能偏向焦虑型依恋，容易担心被抛弃或不被爱。这种模式很常见，觉察是改变的第一步。",
        "avoidant": "你在亲密关系中可能偏向回避型依恋，当关系变得亲密时倾向拉开距离。觉察这种模式有助于建立更深的连接。",
    }
    return {"dominant": dominant, "label": labels[dominant], "scores": scores, "description": descriptions[dominant]}


def interpret_conflict(choice_id: str) -> dict:
    modes = {i["id"]: {"mode": i["mode"], "label": i["label"]} for i in ASSESSMENT_QUESTIONS["conflict"]["items"]}
    info = modes.get(choice_id, {"mode": "unknown", "label": "未知"})
    descriptions = {
        "competing": "你倾向于在冲突中坚持自己的立场。适度的坚持有助于维护边界，但过度使用可能让对方感到不被尊重。",
        "accommodating": "你倾向于在冲突中优先满足对方。这体现了你的体贴，但长期压抑自己的需求可能积累不满。",
        "avoiding": "你倾向于回避冲突。在某些情况下这是智慧的选择，但重要议题的长期回避可能让问题恶化。",
        "collaborating": "你倾向于寻找双赢方案。这是非常健康的冲突处理模式，能促进关系的深层理解和信任。",
        "compromising": "你倾向于各退一步。妥协是务实的策略，但要注意核心需求不宜总是打折。",
    }
    return {**info, "description": descriptions.get(info["mode"], "")}


def build_assessment_context(phq2: dict, gad2: dict, attachment: dict, conflict: dict) -> str:
    parts = ["【用户交流前测评结果（仅供参考，非诊断）】"]
    parts.append(f"- 抑郁筛查(PHQ-2): {phq2['label']}")
    parts.append(f"- 焦虑筛查(GAD-2): {gad2['label']}")
    parts.append(f"- 依恋风格倾向: {attachment['label']}（安全{attachment['scores']['secure']}/焦虑{attachment['scores']['anxious']}/回避{attachment['scores']['avoidant']}）")
    parts.append(f"- 冲突处理模式: {conflict['label']}")
    parts.append("请结合以上信息调整回复策略，但不要直接告诉用户具体得分或评估结果标签。")
    return "\n".join(parts)
