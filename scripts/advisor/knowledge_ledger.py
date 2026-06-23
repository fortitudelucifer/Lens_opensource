#!/usr/bin/env python3
"""知识库台账 / 基线快照（WS-F · F4+F5）

扫描 advisor_out/knowledge/ 全部条目，导出审核/合规台账 CSV（每条的来源、许可、
证据档、风险、审核状态），并打印汇总。既是 F4 当前内容基线快照，也是 F5 审核台账。

用法：
    conda run -n wechatDHA python -m scripts.advisor.knowledge_ledger
    conda run -n wechatDHA python -m scripts.advisor.knowledge_ledger --out PATH.csv
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

try:
    from scripts.advisor.knowledge_schema import CATEGORY_TO_DOMAIN
except Exception:  # 允许脱离包直接运行
    CATEGORY_TO_DOMAIN = {}

FIELDS = ["file", "id", "category", "domain", "evidence_tier", "intervention_or_lens",
          "risk_level", "review_status", "reviewed_by", "review_date", "license", "source"]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def collect(knowledge_dir: Path) -> list[dict]:
    rows = []
    for f in sorted(glob.glob(str(knowledge_dir / "**" / "*.jsonl"), recursive=True)):
        rel = Path(f).relative_to(knowledge_dir).as_posix()
        for line in Path(f).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            rows.append({
                "file": rel,
                "id": d.get("id", ""),
                "category": d.get("category", ""),
                "domain": CATEGORY_TO_DOMAIN.get(d.get("category", ""), "unknown"),
                "evidence_tier": d.get("evidence_tier", ""),
                "intervention_or_lens": d.get("intervention_or_lens", ""),
                "risk_level": d.get("risk_level", "general"),
                "review_status": d.get("review_status", ""),
                "reviewed_by": d.get("reviewed_by", ""),
                "review_date": d.get("review_date", ""),
                "license": d.get("license", ""),
                "source": d.get("source", ""),
            })
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description="知识库台账 / 基线快照")
    ap.add_argument("--dir", default=str(_repo_root() / "advisor_out" / "knowledge"))
    ap.add_argument("--out", default=str(_repo_root() / "research" / "big_plan" / "plan_v5" / "knowledge_ledger.csv"))
    args = ap.parse_args()

    rows = collect(Path(args.dir))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)

    print(f"[台账] 条目 {len(rows)} → {out}")
    print(f"[台账] 生成时间 {datetime.now().isoformat(timespec='seconds')}")

    def dist(key):
        c = Counter(r[key] for r in rows)
        return " · ".join(f"{k}:{v}" for k, v in sorted(c.items()))

    print(f"  domain        : {dist('domain')}")
    print(f"  evidence_tier : {dist('evidence_tier')}")
    print(f"  intervention/lens: {dist('intervention_or_lens')}")
    print(f"  risk_level    : {dist('risk_level')}")
    print(f"  review_status : {dist('review_status')}")
    print(f"  license(前40字): {dist('license')}")
    # 合规自检：approved 但 reviewed_by 空；或 license 空
    flags = [r['id'] for r in rows if r['review_status'] == 'approved' and not r['reviewed_by']]
    nolic = [r['id'] for r in rows if not r['license']]
    if flags:
        print(f"  ⚠️ approved 但无 reviewed_by: {len(flags)} 条 → {flags[:5]}")
    if nolic:
        print(f"  ⚠️ 无 license: {len(nolic)} 条 → {nolic[:5]}")
    if not flags and not nolic:
        print("  ✅ 合规自检通过：approved 均有审核人、license 均非空")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
