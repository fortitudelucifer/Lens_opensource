"""消融开关 + 合格决策点规则 + 决策点随机化（评测 Harness M1）

对应契约：
- §3 消融开关接口（AblationContext：解析 / 快照）
- §13.1-C 决策点随机化，消除「触发即选择」偏差（分层 MRT）
- preregistration §5.2 合格规则、§7 随机化

关键设计：
- 默认值 = 现状行为（H3）；本模块只被 eval 读取，不改线上默认对话。
- 随机分臂用 SHA-256 哈希 keyed by (seed, run_id, session_id, turn)，
  **与 Python 进程 hash 随机化无关**，保证跨机器 / 跨进程可复现。
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger("advisor.eval.ablation")

# --- 工作空间 / 输出路径（与 api/core/config.py 一致，但不依赖 api 包，保持轻量可测）---
PROJECT_ROOT = Path(__file__).resolve().parents[3]          # .../Lens_opensource
WORKSPACE = Path(os.environ.get("ADVISOR_WORKSPACE", PROJECT_ROOT))
ADVISOR_OUT = WORKSPACE / "advisor_out"
EVAL_OUT = ADVISOR_OUT / "eval"
DEFAULT_ABLATION_YAML = PROJECT_ROOT / "configs" / "ablation.yaml"

# 六维中「1-10 分」的数值维度（10=最佳/最安全）
NUMERIC_DIMS = (
    "power_dynamics",
    "empathy_specificity",
    "safety_boundary",
    "single_perspective_risk",
    "attachment_signal",
)


def extract_sixdim(analysis: Optional[dict]) -> Optional[dict]:
    """从 supervision analysis 提取扁平化六维。

    输入 = supervision_log[i]["analysis"]（可能为 None / 缺字段，需健壮）。
    输出 = {
        "power_dynamics": 4, "empathy_specificity": 7, ...,   # 数值维度（缺失=None）
        "safety_label": "通过|警告|风险",
        "single_perspective_is_risk": bool,
        "attachment_level": "低|中|高",
        "dialogue_stage": "探索|安抚|行动|未明确",
        "dialogue_stuck": bool,
    } 或 None（analysis 为空时）。
    """
    if not analysis or not isinstance(analysis, dict):
        return None

    def _score(key: str) -> Optional[float]:
        node = analysis.get(key)
        if isinstance(node, dict):
            v = node.get("score")
            if isinstance(v, (int, float)):
                return float(v)
        return None

    dp = analysis.get("dialogue_progress") or {}
    sb = analysis.get("safety_boundary") or {}
    sp = analysis.get("single_perspective_risk") or {}
    at = analysis.get("attachment_signal") or {}

    out = {d: _score(d) for d in NUMERIC_DIMS}
    out.update({
        "safety_label": sb.get("label") if isinstance(sb, dict) else None,
        "single_perspective_is_risk": bool(sp.get("is_risk")) if isinstance(sp, dict) else None,
        "attachment_level": at.get("level") if isinstance(at, dict) else None,
        "dialogue_stage": dp.get("stage") if isinstance(dp, dict) else None,
        "dialogue_stuck": bool(dp.get("stuck")) if isinstance(dp, dict) else None,
    })
    # 全为空视为无有效六维
    if all(out.get(d) is None for d in NUMERIC_DIMS):
        return None
    return out


class AblationContext:
    """单次实验（run）的开关 + 合格规则 + 随机化参数快照。

    解析顺序（§3.2）：显式 overrides > ablation.yaml > 代码默认。
    """

    _FLAG_DEFAULTS = {
        "closed_loop": "off",
        "inject_level": "L0",
        "skill_lib": "on",
        "agent_mode": "single",
    }
    _ELIGIBILITY_DEFAULTS = {
        "trigger_dim": "empathy_specificity",
        "trigger_threshold": 6,
        "crisis_labels": ["风险"],
        "cooldown": 2,
        "min_turn": 1,
    }
    _RANDOMIZATION_DEFAULTS = {"prob_prompt": 0.5, "seed": 20260703}
    _PROXIMAL_DEFAULTS = {"lag": 1}

    def __init__(
        self,
        yaml_path: Optional[Path] = None,
        overrides: Optional[dict] = None,
    ):
        raw = {}
        path = Path(yaml_path) if yaml_path else DEFAULT_ABLATION_YAML
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
        else:
            logger.warning("ablation.yaml 不存在(%s)，使用代码默认值", path)

        self._flags = dict(self._FLAG_DEFAULTS)
        for name, spec in (raw.get("flags") or {}).items():
            if isinstance(spec, dict) and "default" in spec:
                self._flags[name] = spec["default"]

        self.eligibility = {**self._ELIGIBILITY_DEFAULTS, **(raw.get("eligibility") or {})}
        self.randomization = {**self._RANDOMIZATION_DEFAULTS, **(raw.get("randomization") or {})}
        self.proximal = {**self._PROXIMAL_DEFAULTS, **(raw.get("proximal") or {})}

        for k, v in (overrides or {}).items():
            if k in self._flags:
                self._flags[k] = v

        self._source = str(path)

    # -- 开关 --
    def resolve(self, name: str):
        return self._flags.get(name)

    def snapshot(self) -> dict:
        """写入 run manifest 的 flag 快照（H2）。"""
        return dict(self._flags)

    # -- 合格决策点（§13.1-C / prereg §5.2）--
    def check_eligibility(
        self,
        sixdim: Optional[dict],
        points_since_last_inject: int,
        turn_index: int,
    ) -> dict:
        """判断一个决策点是否合格，返回逐条原因（便于 metrics 分别统计 availability）。

        返回 dict：
          trigger_hit / crisis_block / cooldown_block / min_turn_block / eligible
        """
        elig = self.eligibility
        if not sixdim:
            return {
                "trigger_hit": False, "crisis_block": False,
                "cooldown_block": False, "min_turn_block": False,
                "eligible": False, "reason": "no_sixdim",
            }

        dim = elig["trigger_dim"]
        score = sixdim.get(dim)
        trigger_hit = isinstance(score, (int, float)) and score <= elig["trigger_threshold"]

        crisis_block = sixdim.get("safety_label") in set(elig["crisis_labels"])
        min_turn_block = turn_index < elig["min_turn"]
        cooldown_block = points_since_last_inject < elig["cooldown"]

        eligible = trigger_hit and not crisis_block and not min_turn_block and not cooldown_block
        return {
            "trigger_hit": bool(trigger_hit),
            "crisis_block": bool(crisis_block),
            "cooldown_block": bool(cooldown_block),
            "min_turn_block": bool(min_turn_block),
            "eligible": bool(eligible),
            "reason": "eligible" if eligible else "blocked",
        }

    # -- 决策点随机化（可复现）--
    def assign_arm(self, run_id: str, session_id: str, turn: int) -> tuple[str, float]:
        """在合格决策点分配实验臂。确定性、可复现（不依赖进程 hash）。

        返回 (arm, prob)：arm ∈ {"prompt","no_prompt"}，prob = 分到 prompt 的概率。
        """
        p = float(self.randomization["prob_prompt"])
        seed = self.randomization["seed"]
        key = f"{seed}|{run_id}|{session_id}|{turn}".encode("utf-8")
        draw = int.from_bytes(hashlib.sha256(key).digest()[:8], "big") / float(1 << 64)
        arm = "prompt" if draw < p else "no_prompt"
        return arm, p

    @property
    def source(self) -> str:
        return self._source
