"""
四级危机检测模块

级别：GREEN → YELLOW → ORANGE → RED
- GREEN:  正常对话
- YELLOW: 中度困扰，注入安全引导
- ORANGE: 高风险，引导至专业资源
- RED:    自杀/自伤意念，立即中断 AI 并展示危机干预
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Optional

import yaml

CONFIG_DIR = Path(__file__).resolve().parents[3] / "configs"


class CrisisLevel(IntEnum):
    GREEN = 0
    YELLOW = 1
    ORANGE = 2
    RED = 3


@dataclass
class CrisisResult:
    level: CrisisLevel
    matched_keywords: list[str] = field(default_factory=list)
    response_template: Optional[dict] = None
    downgraded: bool = False  # 因误触发排除规则降级


class CrisisDetector:

    def __init__(self):
        kw_path = CONFIG_DIR / "crisis_keywords.yaml"
        res_path = CONFIG_DIR / "crisis_resources.yaml"

        with open(kw_path, "r", encoding="utf-8") as f:
            kw_cfg = yaml.safe_load(f) or {}
        with open(res_path, "r", encoding="utf-8") as f:
            self._resources = yaml.safe_load(f) or {}

        self._red_exact = kw_cfg.get("red_signals", {}).get("exact", [])
        self._red_fp_only = kw_cfg.get("red_signals", {}).get("first_person_only", [])
        self._red_proximity = kw_cfg.get("red_signals", {}).get("proximity_phrases", [])
        self._orange_exact = kw_cfg.get("orange_signals", {}).get("exact", [])
        self._orange_fp_only = kw_cfg.get("orange_signals", {}).get("first_person_only", [])
        self._orange_proximity = kw_cfg.get("orange_signals", {}).get("proximity_phrases", [])
        self._yellow_exact = kw_cfg.get("yellow_signals", {}).get("exact", [])
        self._false_positive = kw_cfg.get("false_positive_patterns", [])
        self._prohibited = kw_cfg.get("prohibited_words_in_response", {})
        self._templates = self._resources.get("response_templates", {})

    def detect(self, message: str, recent_messages: list[str] | None = None) -> CrisisResult:
        """检测用户消息的危机级别"""
        text = message.strip()
        if not text:
            return CrisisResult(level=CrisisLevel.GREEN)

        is_fp = self._check_false_positive(text)

        matched = []
        level = CrisisLevel.GREEN

        if (self._match_exact(text, self._red_exact, matched)
                or self._match_first_person_keywords(text, self._red_fp_only, matched)
                or self._match_proximity(text, self._red_proximity, matched)):
            level = CrisisLevel.RED
        elif (self._match_exact(text, self._orange_exact, matched)
                or self._match_first_person_keywords(text, self._orange_fp_only, matched)
                or self._match_proximity(text, self._orange_proximity, matched)):
            level = CrisisLevel.ORANGE
        elif self._match_exact(text, self._yellow_exact, matched):
            level = CrisisLevel.YELLOW

        # 上下文感知：检查最近消息中是否有累积信号
        if level == CrisisLevel.GREEN and recent_messages:
            escalated_level = self._check_context_escalation(recent_messages)
            if escalated_level > level:
                level = escalated_level
                matched.append("[上下文累积信号]")

        downgraded = False
        if is_fp and level >= CrisisLevel.ORANGE:
            level = CrisisLevel(level - 1)
            downgraded = True

        template = self._templates.get(level.name.lower()) if level > CrisisLevel.GREEN else None

        return CrisisResult(
            level=level,
            matched_keywords=matched,
            response_template=template,
            downgraded=downgraded,
        )

    def check_response_prohibited(self, ai_response: str) -> list[str]:
        """检查 AI 回复是否包含禁用词"""
        violations = []
        for category, words in self._prohibited.items():
            if isinstance(words, list):
                for w in words:
                    if w in ai_response:
                        violations.append(f"[{category}] {w}")
        return violations

    def get_safety_prompt_injection(self, level: CrisisLevel) -> str:
        """根据危机级别生成注入到 system prompt 的安全引导"""
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
        return ""

    def get_hotlines(self, top_n: int = 3) -> list[dict]:
        """获取优先展示的热线"""
        hotlines = self._resources.get("national_hotlines", [])
        hotlines.sort(key=lambda h: h.get("priority", 99))
        return hotlines[:top_n]

    def _match_exact(self, text: str, keywords: list[str], matched: list[str]) -> bool:
        hit = False
        for kw in keywords:
            if kw in text:
                matched.append(kw)
                hit = True
        return hit

    _FIRST_PERSON = re.compile(r"(我|自己|本人|俺|咱)")

    def _match_first_person_keywords(self, text: str, keywords: list[str], matched: list[str]) -> bool:
        """匹配需要第一人称主语的关键词：第一人称须在关键词前 5 字符内"""
        hit = False
        for kw in keywords:
            idx = text.find(kw)
            if idx < 0:
                continue
            prefix = text[max(0, idx - 5):idx]
            if self._FIRST_PERSON.search(prefix):
                matched.append(kw)
                hit = True
        return hit

    def _match_proximity(self, text: str, phrases: list[dict], matched: list[str]) -> bool:
        """短语匹配：完整短语存在于消息中，可选第一人称约束"""
        hit = False
        for entry in phrases:
            phrase = entry.get("phrase", "")
            need_fp = entry.get("require_first_person", False)
            if phrase and phrase in text:
                if need_fp and not self._FIRST_PERSON.search(text):
                    continue
                matched.append(phrase)
                hit = True
        return hit

    def _check_false_positive(self, text: str) -> bool:
        return any(pat in text for pat in self._false_positive)

    def _check_context_escalation(self, recent_messages: list[str]) -> CrisisLevel:
        """检查最近消息中是否有累积的困扰信号"""
        yellow_count = 0
        orange_count = 0
        for msg in recent_messages[-3:]:
            dummy: list[str] = []
            if self._match_exact(msg, self._yellow_exact, dummy):
                yellow_count += 1
            if self._match_exact(msg, self._orange_exact, dummy):
                orange_count += 1

        if orange_count >= 2:
            return CrisisLevel.RED
        if yellow_count >= 3:
            return CrisisLevel.ORANGE
        if yellow_count >= 2:
            return CrisisLevel.YELLOW
        return CrisisLevel.GREEN
