"""指标报告：合格点占比 + 六维分布 + 臂平衡 + 近端结局差（评测 Harness M1）

对应契约 §6 指标层 / §13 效度。MVP 报告回答预注册需要冻结的输入：
- availability（合格点占比）→ 功效计算输入（prereg §6）
- 六维分布 / 近端结局差的方差 → 效应量与样本量输入
- 臂平衡（观察到的 prompt 比例 ≈ p）→ 随机化健全性

注意：事后抽取（post_hoc）里 arm 是 counterfactual、未真正注入，故臂间差异**不是效应**，
仅用于打通指标代码路径。真实效应需 live 注入 + WCLS（§13.1-D，后续增量）。

用法：python -m scripts.advisor.eval.metrics --run <run_id>
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Optional

from scripts.advisor.eval.ablation import EVAL_OUT, NUMERIC_DIMS


def _stats(values: list[float]) -> dict:
    vals = [v for v in values if isinstance(v, (int, float))]
    n = len(vals)
    if n == 0:
        return {"n": 0, "mean": None, "sd": None}
    mean = sum(vals) / n
    sd = math.sqrt(sum((v - mean) ** 2 for v in vals) / (n - 1)) if n > 1 else 0.0
    return {"n": n, "mean": round(mean, 3), "sd": round(sd, 3)}


def _load_traces(run_id: str, base_dir: Optional[Path] = None) -> list[dict]:
    base = Path(base_dir) if base_dir else EVAL_OUT
    tdir = base / "traces" / run_id
    rows = []
    for p in sorted(tdir.glob("*.jsonl")):
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def compute_report(run_id: str, base_dir: Optional[Path] = None) -> dict:
    base = Path(base_dir) if base_dir else EVAL_OUT
    traces = _load_traces(run_id, base_dir=base)
    n = len(traces)

    manifest = {}
    mpath = base / "runs" / run_id / "manifest.json"
    if mpath.exists():
        manifest = json.loads(mpath.read_text(encoding="utf-8"))

    if n == 0:
        return {"run_id": run_id, "n_decision_points": 0, "manifest": manifest}

    sessions = {t["session_id"] for t in traces}

    # availability
    trigger = sum(1 for t in traces if t["eligibility"].get("trigger_hit"))
    crisis = sum(1 for t in traces if t["eligibility"].get("crisis_block"))
    eligible = [t for t in traces if t["eligibility"].get("eligible")]
    cooldown_block = sum(1 for t in traces if t["eligibility"].get("cooldown_block"))
    min_turn_block = sum(1 for t in traces if t["eligibility"].get("min_turn_block"))

    # 六维分布
    sixdim = {
        d: _stats([t["metrics"]["supervision"].get(d) for t in traces])
        for d in NUMERIC_DIMS
    }

    # 臂平衡
    n_prompt = sum(1 for t in eligible if t.get("arm") == "prompt")
    n_noprompt = sum(1 for t in eligible if t.get("arm") == "no_prompt")
    arm_balance = {
        "n_eligible": len(eligible),
        "n_prompt": n_prompt,
        "n_no_prompt": n_noprompt,
        "observed_prob_prompt": round(n_prompt / len(eligible), 3) if eligible else None,
    }

    # 近端结局差（有 lag 后继的决策点）
    prox_available = [t for t in traces if t["outcome"]["proximal"].get("available")]
    proximal = {
        "n_with_proximal": len(prox_available),
        "delta_by_dim": {
            d: _stats([t["outcome"]["proximal"]["delta"].get(d) for t in prox_available])
            for d in NUMERIC_DIMS
        },
    }

    return {
        "run_id": run_id,
        "n_sessions": len(sessions),
        "n_decision_points": n,
        "availability": {
            "trigger_rate": round(trigger / n, 3),
            "eligible_rate": round(len(eligible) / n, 3),
            "n_trigger_hit": trigger,
            "n_eligible": len(eligible),
            "blocks": {
                "crisis": crisis,
                "cooldown": cooldown_block,
                "min_turn": min_turn_block,
            },
        },
        "sixdim_distribution": sixdim,
        "arm_balance": arm_balance,
        "proximal": proximal,
        "manifest": manifest,
    }


def _fmt_report(r: dict) -> str:
    lines = []
    lines.append(f"══ 评测 Harness 报告 · run={r['run_id']} ══")
    if r.get("n_decision_points", 0) == 0:
        lines.append("（无决策点：session 里没有带六维的 supervision 记录。")
        lines.append(" 请先在配置好 Judge 的情况下产生若干带督导评估的对话再抽取。）")
        return "\n".join(lines)

    lines.append(f"会话数 {r['n_sessions']} · 决策点 {r['n_decision_points']}")
    a = r["availability"]
    lines.append("")
    lines.append("── 合格点占比 availability（功效计算输入）──")
    lines.append(f"  触发率 trigger_rate = {a['trigger_rate']}  (τ 触发 {a['n_trigger_hit']}/{r['n_decision_points']})")
    lines.append(f"  合格率 eligible_rate = {a['eligible_rate']}  (合格 {a['n_eligible']})")
    lines.append(f"  拦截明细：危机 {a['blocks']['crisis']} · 冷却 {a['blocks']['cooldown']} · 起始轮 {a['blocks']['min_turn']}")

    lines.append("")
    lines.append("── 六维分布（1-10；效应量/方差输入）──")
    for d in NUMERIC_DIMS:
        s = r["sixdim_distribution"][d]
        lines.append(f"  {d:<26} n={s['n']:>3}  mean={s['mean']}  sd={s['sd']}")

    ab = r["arm_balance"]
    lines.append("")
    lines.append("── 臂平衡（随机化健全性）──")
    lines.append(f"  合格 {ab['n_eligible']} → prompt {ab['n_prompt']} / no_prompt {ab['n_no_prompt']}  "
                 f"观察 p(prompt)={ab['observed_prob_prompt']}")

    p = r["proximal"]
    lines.append("")
    lines.append(f"── 近端结局差 Δ（lag，可算 {p['n_with_proximal']} 个）──")
    for d in NUMERIC_DIMS:
        s = p["delta_by_dim"][d]
        lines.append(f"  Δ{d:<25} n={s['n']:>3}  mean={s['mean']}  sd={s['sd']}")

    lines.append("")
    lines.append("注：事后抽取的 arm 为 counterfactual，臂间差异非效应；真实效应需 live 注入 + WCLS。")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="评测 Harness 指标报告（M1 MVP）")
    ap.add_argument("--run", required=True)
    ap.add_argument("--json", action="store_true", help="输出原始 JSON")
    args = ap.parse_args()

    report = compute_report(args.run)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(_fmt_report(report))


if __name__ == "__main__":
    main()
