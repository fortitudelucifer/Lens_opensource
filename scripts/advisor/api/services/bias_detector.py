"""
Day 4 · D4.7 · BiasDetector · 输出偏见检测 + 替换

与 `crisis_detector.check_response_prohibited` 的定位区分：
  - CrisisDetector.prohibited_words_in_response
      → 覆盖"绝对禁用"（诊断/处方/"你必须"）· 临床 / 边界违规
  - BiasDetector.output_bias_patterns
      → 覆盖"隐性偏见"（性别刻板、关系绝对化、受害者归咎、
        道德评判、病理化标签）· 5 类 × ~12 条 ≈ 60 规则

集成入口：`scripts/advisor/api/services/roundtable_service.py` 的
  `_sanitize_agent_output` · 由 `GuardedEmitter._flush` 在 flush 前调用，
保证偏见词不会在流式过程中被用户看到。

Audit log：命中时写入 logger.info · D5.2b 人工审核回归时可从日志提取
20 条偏见样本进行召回/误伤率评估。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

import yaml

CONFIG_DIR = Path(__file__).resolve().parents[4] / "configs"

log = logging.getLogger(__name__)

# 被命中时统一替换为的占位符（对齐 CrisisDetector 的风格）
DEFAULT_REPLACEMENT = "（此处表述调整）"


@dataclass
class BiasViolation:
    category: str          # gender_stereotype / relationship_absolutism / ...
    pattern: str           # 原始命中 pattern
    start: int = -1        # 在原文中的起始位置（可选，审核用）

    def as_audit_line(self) -> str:
        return f"[{self.category}] {self.pattern}"


@dataclass
class BiasSanitizeResult:
    text: str                                        # 替换后的文本
    violations: list[BiasViolation] = field(default_factory=list)

    @property
    def hit(self) -> bool:
        return bool(self.violations)


class BiasDetector:
    """加载 configs/crisis_keywords.yaml:output_bias_patterns

    提供：
      - detect(text) -> list[BiasViolation]  · 只检测不替换
      - sanitize(text) -> BiasSanitizeResult · 检测并替换
      - categories -> list[str]              · 暴露已加载类别（测试/调试用）
    """

    # 单例：避免每次 _flush 都重读 yaml
    _instance: Optional["BiasDetector"] = None

    def __init__(
        self,
        *,
        config_path: Optional[Path] = None,
        replacement: str = DEFAULT_REPLACEMENT,
    ) -> None:
        path = Path(config_path) if config_path else (CONFIG_DIR / "crisis_keywords.yaml")
        if not path.exists():
            log.warning("[bias_detector] config not found · path=%s · loading empty", path)
            self._patterns: dict[str, list[str]] = {}
        else:
            with open(path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            raw = cfg.get("output_bias_patterns", {}) or {}
            # 类别内按长度倒序（先匹配更长的 pattern，防"男人都"/"男人"重叠）
            self._patterns = {
                cat: sorted({p for p in patterns if isinstance(p, str) and p}, key=len, reverse=True)
                for cat, patterns in raw.items()
                if isinstance(patterns, list)
            }
        self._replacement = replacement
        # 预聚合的 (pattern, category) 列表 · 按长度倒序，一次扫描全分类
        self._flat: list[tuple[str, str]] = sorted(
            ((p, cat) for cat, patterns in self._patterns.items() for p in patterns),
            key=lambda kv: len(kv[0]),
            reverse=True,
        )
        log.info(
            "[bias_detector] loaded · categories=%d total_rules=%d",
            len(self._patterns), len(self._flat),
        )

    # ── 公共 API ────────────────────────────────────────────

    @classmethod
    def get_default(cls) -> "BiasDetector":
        """进程内单例 · 避免 flush hook 反复重载 yaml"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_default(cls) -> None:
        """测试用：清空单例"""
        cls._instance = None

    @property
    def categories(self) -> list[str]:
        return list(self._patterns.keys())

    @property
    def rule_count(self) -> int:
        return len(self._flat)

    def detect(self, text: str) -> list[BiasViolation]:
        """只检测，不替换。返回按首次出现位置排序的命中列表"""
        if not text or not self._flat:
            return []
        out: list[BiasViolation] = []
        for pattern, cat in self._flat:
            idx = text.find(pattern)
            if idx >= 0:
                out.append(BiasViolation(category=cat, pattern=pattern, start=idx))
        out.sort(key=lambda v: (v.start, -len(v.pattern)))
        return out

    def sanitize(
        self,
        text: str,
        *,
        audit_context: Optional[dict] = None,
    ) -> BiasSanitizeResult:
        """检测并替换所有命中。

        参数：
          audit_context: {"session_id": "...", "persona_id": "...", "phase": "..."}
                         命中时写 audit log · D5.2b 汇总
        返回：
          BiasSanitizeResult(text=替换后, violations=命中列表)
        """
        if not text or not self._flat:
            return BiasSanitizeResult(text=text)
        violations: list[BiasViolation] = []
        cleaned = text
        # 按长度倒序依次 replace · O(N · K) 但 K=60，text 通常 <100 字
        for pattern, cat in self._flat:
            if pattern in cleaned:
                violations.append(BiasViolation(category=cat, pattern=pattern))
                cleaned = cleaned.replace(pattern, self._replacement)
        if violations and log.isEnabledFor(logging.INFO):
            ctx = audit_context or {}
            log.info(
                "[bias_detector] hit · session=%s phase=%s persona=%s hits=%s",
                ctx.get("session_id", "-"),
                ctx.get("phase", "-"),
                ctx.get("persona_id", "-"),
                [v.as_audit_line() for v in violations],
            )
        return BiasSanitizeResult(text=cleaned, violations=violations)


# ── 便捷函数（roundtable_service 直接 import 使用）──────────

def sanitize_output_bias(
    text: str,
    *,
    audit_context: Optional[dict] = None,
) -> str:
    """给 `_sanitize_agent_output` 用的一行替换入口。

    命中时写 audit log；未命中时零开销（flat 规则表已缓存）。
    """
    return BiasDetector.get_default().sanitize(text, audit_context=audit_context).text


def detect_output_bias(text: str) -> list[BiasViolation]:
    """仅检测，用于测试 / 审核回归脚本"""
    return BiasDetector.get_default().detect(text)
