#!/usr/bin/env python3
"""
知识中心内容生产工单（WS-A · A5）

把 §A.3 内容蓝图拆成逐条目工单：每条 = (稳定 id, 中文主题方向, 元数据)。
供 WS-C 内容生产流水线遍历：LLM 起草 question/answer → 临床审核 → 写入对应目录。

每个 category 的元数据（证据标签/干预或透镜/风险/许可区/波次）集中定义，
条目只需给 (slug, 主题)；id = f"{category}_{slug}"。

用法：
    conda run -n wechatDHA python -m scripts.advisor.knowledge_worklist            # 打印汇总
    conda run -n wechatDHA python -m scripts.advisor.knowledge_worklist --emit DIR  # 生成 stub jsonl

作者：Claude (Opus 4.8) · 2026-06-19
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.advisor.knowledge_schema import KnowledgeEntry, VALID_CATEGORIES  # noqa: E402


# category → (evidence_tier, intervention_or_lens, risk_level, license_zone, wave, evidence_note)
CATEGORY_META: dict[str, tuple[str, str, str, str, str, str]] = {
    "eft":        ("well_established", "intervention", "general",  "green", "W1", ""),
    "cbct":       ("well_established", "intervention", "general",  "green", "W1", ""),
    "ibct":       ("well_established", "intervention", "general",  "green", "W1", ""),
    "gottman":    ("moderate", "intervention", "general", "red_to_green", "W2", "预测模型社区样本未完全复现，按教育概念使用"),
    "dbt_skills": ("moderate", "intervention", "general", "red_to_green", "W2", "个体情绪调节证据扎实，伴侣应用证据初步"),
    "act":        ("moderate", "intervention", "general",  "green", "W2", ""),
    "sfbt":       ("moderate", "intervention", "general",  "green", "W3", ""),
    "rebt":       ("moderate", "intervention", "general",  "green", "W3", ""),
    "mindfulness":("moderate", "intervention", "general",  "green", "W3", ""),
    "prep":       ("moderate", "intervention", "general",  "green", "W3", ""),
    "communication":("moderate", "intervention", "general","green", "W3", ""),
    "safety":     ("moderate", "intervention", "crisis",   "open",  "Safety", ""),
    "crisis":     ("moderate", "intervention", "elevated", "open",  "Safety", ""),
    "psychoanalytic":("lens", "lens", "general", "green", "Lens", ""),
    "bowen":      ("lens", "lens", "general", "green", "Lens", ""),
    "attachment": ("lens", "lens", "general", "green", "Lens", ""),
}

# category → [(slug, 中文主题方向)]
WORKLIST: dict[str, list[tuple[str, str]]] = {
    # ---- W1 循证一线 ----
    "eft": [
        ("pursue_withdraw_deep", "追逃循环深化：追者焦虑/逃者回避的底层恐惧"),
        ("primary_vs_secondary_emotion", "初级情绪 vs 次级情绪"),
        ("attachment_injury", "依恋创伤（关系中的背叛/失联时刻）"),
        ("demon_dialogues", "三种恶魔对话：找坏人/抗议探戈/僵住逃离"),
        ("eft_tango", "EFT Tango 五动作流程"),
        ("stage_deescalation", "阶段一：去稳定化（看见循环）"),
        ("stage_restructuring", "阶段二：重建联结（表达依恋需求）"),
        ("stage_consolidation", "阶段三：巩固整合"),
        ("are_framework", "A.R.E.：可及/回应/投入"),
        ("hold_me_tight", "抱紧我对话结构"),
        ("raw_spots", "原始敏感点（raw spots）识别"),
        ("softening", "软化（softening）时刻"),
        ("attachment_longings_fears", "依恋渴望与依恋恐惧"),
        ("emotional_attunement", "情绪同调（attunement）"),
        ("cycle_externalization", "把循环外化为共同敌人"),
        ("secure_base", "安全基地与安全港"),
        ("hug_exercise", "拥抱/身体联结练习"),
    ],
    "cbct": [
        ("cognitive_triangle", "认知三角：想法-情绪-行为"),
        ("distortion_mind_reading", "认知扭曲：读心术"),
        ("distortion_catastrophizing", "认知扭曲：灾难化"),
        ("distortion_all_or_nothing", "认知扭曲：非黑即白"),
        ("distortion_should", "认知扭曲：应该陈述"),
        ("distortion_labeling", "认知扭曲：贴标签"),
        ("distortion_emotional_reasoning", "认知扭曲：情绪推理"),
        ("distortion_overgeneralization", "认知扭曲：以偏概全"),
        ("automatic_thoughts", "自动思维识别"),
        ("thought_record", "思维记录表"),
        ("socratic_questioning", "苏格拉底式提问挑战负面想法"),
        ("behavior_exchange", "行为交换（caring days）"),
        ("speaker_listener", "说者-听者沟通训练"),
        ("problem_solving_training", "问题解决训练"),
        ("relationship_standards", "关系标准与假设"),
        ("attribution_styles", "归因：关系增强型 vs 困扰维持型"),
        ("behavioral_experiment", "行为实验设计"),
        ("downward_arrow", "向下箭头技术（核心信念）"),
        ("cbct_not_applicable", "CBCT 不适用场景（危机/人格障碍→转介）"),
        ("cognitive_restructuring", "认知重构整体流程"),
    ],
    "ibct": [
        ("acceptance_vs_change", "接纳与改变的平衡"),
        ("deep_analysis", "DEEP 分析：差异/情绪敏感点/外部压力/沟通模式"),
        ("unified_detachment", "统一抽离：把'它/模式'当对象而非指责对方"),
        ("empathic_joining", "共情联结：硬情绪下的软情绪"),
        ("tolerance_building", "容忍建立（tolerance building）"),
        ("mutual_trap", "相互陷阱与两极化过程"),
        ("theme_formulation", "主题（theme）个案概念化"),
        ("natural_vs_rule_governed", "自然强化 vs 规则驱动行为"),
        ("self_care_in_tolerance", "容忍中的自我照顾"),
        ("perpetual_problem_acceptance", "永久性问题的接纳路径"),
        ("incompatibility_reframe", "不兼容差异的重构"),
        ("emotional_acceptance", "情感接纳作为改变基础"),
        ("soft_disclosure", "脆弱性的软性表达"),
        ("polarization_exit", "走出两极化的具体方法"),
        ("ibct_vs_tbct", "IBCT 与传统行为伴侣治疗的区别"),
    ],
    # ---- W2 高可操作·加证据标签 ----
    "gottman": [
        ("horseman_criticism", "末日四骑士：批评"),
        ("horseman_contempt", "末日四骑士：蔑视"),
        ("horseman_defensiveness", "末日四骑士：防御"),
        ("horseman_stonewalling", "末日四骑士：筑墙/冷战"),
        ("antidote_gentle_startup", "解药：温和开场白"),
        ("antidote_appreciation", "解药：建立欣赏文化"),
        ("antidote_responsibility", "解药：承担责任"),
        ("antidote_self_soothing", "解药：生理自我安抚"),
        ("srh_love_maps", "健全关系之屋：爱情地图"),
        ("srh_fondness_admiration", "健全关系之屋：喜爱与赞赏"),
        ("srh_turning_towards", "健全关系之屋：转向而非转离"),
        ("srh_positive_perspective", "健全关系之屋：积极视角"),
        ("srh_manage_conflict", "健全关系之屋：管理冲突"),
        ("srh_life_dreams", "健全关系之屋：实现人生梦想"),
        ("srh_shared_meaning", "健全关系之屋：创造共同意义"),
        ("bids_for_connection", "情感联结请求（转向 86% vs 33%）"),
        ("repair_attempts", "修复尝试"),
        ("flooding", "情绪淹没（flooding）与暂停"),
        ("magic_ratio", "5:1 积极/消极比例"),
        ("solvable_vs_perpetual", "可解决 vs 永久问题"),
    ],
    "dbt_skills": [
        ("mindfulness_wise_mind", "正念：智慧心（理智×情绪）"),
        ("mindfulness_what_skills", "正念：观察-描述-参与"),
        ("mindfulness_how_skills", "正念：不评判-专注-有效"),
        ("dt_tipp", "痛苦耐受：TIPP 生理降温"),
        ("dt_stop", "痛苦耐受：STOP 冲动控制"),
        ("dt_accepts", "痛苦耐受：ACCEPTS 分散注意"),
        ("dt_self_soothe", "痛苦耐受：五感自我安抚"),
        ("dt_radical_acceptance", "痛苦耐受：彻底接纳"),
        ("dt_pros_cons", "痛苦耐受：利弊清单"),
        ("er_identify_emotion", "情绪调节：识别与命名情绪"),
        ("er_opposite_action", "情绪调节：相反行动"),
        ("er_check_the_facts", "情绪调节：核对事实"),
        ("er_please", "情绪调节：PLEASE 身体照护"),
        ("er_accumulate_positives", "情绪调节：积累正性事件"),
        ("er_cope_ahead", "情绪调节：提前应对"),
        ("ie_dear_man", "人际效能：DEAR MAN 提要求"),
        ("ie_give", "人际效能：GIVE 维护关系"),
        ("ie_fast", "人际效能：FAST 自我尊重"),
        ("ie_priorities", "人际效能：目标/关系/自尊优先级"),
        ("dialectics", "辩证思维：两极的'与'而非'或'"),
    ],
    "act": [
        ("defusion", "认知解离（与想法拉开距离）"),
        ("acceptance", "接纳（为情绪腾出空间）"),
        ("present_moment", "接触当下"),
        ("self_as_context", "以己为景（观察性自我）"),
        ("values_clarification", "关系中的价值澄清"),
        ("committed_action", "承诺行动"),
        ("experiential_avoidance", "经验性回避的代价"),
        ("cognitive_fusion", "认知融合在冲突中的表现"),
        ("willingness", "意愿（willingness）"),
        ("struggle_switch", "挣扎开关"),
        ("values_vs_goals", "价值 vs 目标"),
        ("creative_hopelessness", "创造性无望（放下无效控制）"),
    ],
    # ---- W3 技术补充 ----
    "sfbt": [
        ("miracle_question", "奇迹问句"),
        ("scaling_question", "刻度化问句"),
        ("exception_finding", "例外找寻"),
        ("coping_question", "应对问句"),
        ("presuppositional_language", "预设性语言"),
        ("small_steps", "下一小步"),
        ("compliments", "肯定与赞美"),
        ("preferred_future", "偏好的未来描绘"),
    ],
    "rebt": [
        ("abcde_model", "ABC(DE) 模型"),
        ("irrational_demands", "非理性信念：绝对化要求"),
        ("irrational_awfulizing", "非理性信念：糟糕至极"),
        ("irrational_lft", "非理性信念：低挫折容忍"),
        ("disputing", "反驳非理性信念"),
        ("unconditional_acceptance", "无条件自我/他人接纳"),
    ],
    "mindfulness": [
        ("mindful_breathing", "正念呼吸"),
        ("loving_kindness", "慈心练习"),
        ("mindful_listening", "正念倾听"),
        ("co_regulation_body_scan", "共调身体扫描"),
        ("mbre_partner_exercise", "MBRE 伴侣联结练习"),
        ("daily_awareness", "日常觉察微练习"),
    ],
    "prep": [
        ("speaker_listener_technique", "说者-听者技术"),
        ("time_out_rule", "暂停（time-out）规则"),
        ("fair_fight_rules", "公平争吵守则"),
        ("expectation_management", "期待管理"),
        ("friendship_fun", "友谊与乐趣维系"),
        ("prevention_vs_repair", "预防 vs 修复框架"),
    ],
    "communication": [
        ("al_paraphrase", "积极倾听：复述"),
        ("al_reflect_feeling", "积极倾听：映射感受"),
        ("al_validate", "积极倾听：验证理解"),
        ("al_open_question", "积极倾听：开放式提问"),
        ("al_summarize", "积极倾听：总结"),
        ("repair_apology", "修复：有效道歉"),
        ("repair_humor", "修复：幽默缓和"),
        ("repair_pause", "修复：主动暂停"),
        ("repair_touch", "修复：身体接触"),
        ("repair_shared_memory", "修复：唤起共同回忆"),
        ("deesc_20min_break", "冲突降级：20 分钟生理冷静"),
        ("deesc_soft_startup", "冲突降级：软化开场"),
        ("deesc_time_window", "冲突降级：约定谈话时间窗"),
        ("deesc_i_message", "冲突降级：'我'信息表达"),
        ("deesc_one_topic", "冲突降级：一次只谈一件事"),
    ],
    # ---- 安全层（独立，crisis 不进常规召回） ----
    "safety": [
        ("cssrs_brief", "C-SSRS 简化自杀风险筛查问句"),
        ("safety_plan_6step", "Stanley-Brown 安全计划 6 步"),
        ("hotline_templates", "危机热线转介模板（复用现有）"),
        ("ipv_safety", "亲密伴侣暴力（IPV）安全要点"),
        ("when_to_seek_help", "何时必须求助（自伤念头/两周抑郁/物质依赖）"),
    ],
    "crisis": [
        ("grounding_more", "扩充接地技巧（冰握/强感官）"),
        ("paced_breathing", "节律呼吸快速平复"),
        ("urge_surfing", "冲动冲浪（延迟自伤）"),
        ("self_compassion_break", "自我关怀暂停"),
        ("safe_place_visualization", "安全地意象"),
    ],
    # ---- 透镜桶（lens） ----
    "psychoanalytic": [
        ("object_relations", "客体关系：内化的关系模板"),
        ("projective_identification", "投射认同"),
        ("repetition_compulsion", "重复强迫（重演旧模式）"),
        ("transference_in_relationship", "关系中的移情"),
    ],
    "bowen": [
        ("differentiation_of_self", "自我分化"),
        ("triangulation", "三角化"),
        ("emotional_cutoff", "情感截断"),
    ],
    "attachment": [
        ("style_secure", "安全型依恋"),
        ("style_anxious", "焦虑型依恋"),
        ("style_avoidant_disorganized", "回避型与紊乱型依恋"),
    ],
}


def iter_worklist():
    """生成 (id, category, topic, meta_dict)。"""
    for cat, items in WORKLIST.items():
        tier, iol, risk, lic_zone, wave, note = CATEGORY_META[cat]
        for slug, topic in items:
            yield {
                "id": f"{cat}_{slug}",
                "category": cat,
                "topic": topic,
                "evidence_tier": tier,
                "intervention_or_lens": iol,
                "risk_level": risk,
                "license_zone": lic_zone,
                "wave": wave,
                "evidence_note": note,
            }


def _self_check() -> list[str]:
    """校验：category 合法、id 唯一、id 符合 schema 模式。"""
    errs, seen = [], set()
    import re
    for row in iter_worklist():
        if row["category"] not in VALID_CATEGORIES:
            errs.append(f"{row['id']}: 非法 category {row['category']}")
        if not re.fullmatch(r"[a-z0-9_]+", row["id"]):
            errs.append(f"{row['id']}: id 不符合模式")
        if row["id"] in seen:
            errs.append(f"{row['id']}: id 重复")
        seen.add(row["id"])
    return errs


def main() -> int:
    ap = argparse.ArgumentParser(description="内容生产工单")
    ap.add_argument("--emit", metavar="DIR", help="把 stub jsonl 写到 DIR（review_status=pending）")
    args = ap.parse_args()

    rows = list(iter_worklist())
    errs = _self_check()

    # 汇总
    from collections import Counter
    by_wave, by_cat = Counter(), Counter()
    for r in rows:
        by_wave[r["wave"]] += 1
        by_cat[r["category"]] += 1
    print(f"[工单] 总条目：{len(rows)}")
    print("[工单] 按波次：" + " | ".join(f"{w}:{by_wave[w]}" for w in ["W1","W2","W3","Safety","Lens"]))
    print("[工单] 按类目：" + ", ".join(f"{c}:{n}" for c, n in by_cat.items()))
    if errs:
        print(f"[工单] ❌ 自检 {len(errs)} 个问题：")
        for e in errs:
            print("   -", e)
        return 1
    print("[工单] ✅ 自检通过（category 合法 / id 唯一且合规）")

    if args.emit:
        out = Path(args.emit)
        out.mkdir(parents=True, exist_ok=True)
        n = 0
        for cat in WORKLIST:
            cat_rows = [r for r in rows if r["category"] == cat]
            lines = []
            for r in cat_rows:
                stub = {
                    "id": r["id"], "question": r["topic"], "answer": "",
                    "category": cat, "keywords": [],
                    "evidence_tier": r["evidence_tier"],
                    "intervention_or_lens": r["intervention_or_lens"],
                    "risk_level": r["risk_level"], "related": [],
                    "evidence_note": r["evidence_note"],
                    "source": "", "license": "",
                    "review_status": "pending", "reviewed_by": "", "review_date": "",
                }
                lines.append(json.dumps(stub, ensure_ascii=False))
                n += 1
            (out / f"{cat}.worklist.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"[工单] 已写出 {n} 条 stub 到 {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
