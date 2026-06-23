#!/usr/bin/env python3
"""红区合规自动扫描（WS-C · C4 辅助）

对知识库 JSONL 做**机器初筛**，给人工三级审核当前置过滤。不替代人工，只把
高风险条目顶到审核员面前。检查项：

  1. 商标/专有冒用：出现"官方/认证/Method™/®/™"等可能冒用专有体系的表述。
  2. 专有材料指纹：疑似抄 worksheet/问卷条目（量表式编号、版权页措辞）。
  3. 证据限定缺失：red_to_green / 有 evidence_note 的条目，answer 却用了绝对化因果断言
     （"必然/一定会/证明了/治愈"）而无任何缓和措辞。
  4. license 与 category 不一致：Gottman/DBT 必须是"未引用专有材料"那一档。

用法：
    conda run -n wechatDHA python -m scripts.advisor.knowledge_redzone_lint
    conda run -n wechatDHA python -m scripts.advisor.knowledge_redzone_lint --dir advisor_out/knowledge/_drafts
"""
from __future__ import annotations

import argparse
import glob
import json
import re
from pathlib import Path

RED_CATEGORIES = {"gottman", "dbt_skills"}
RED_LICENSE = "原创讲解（学术通用概念，未引用专有材料）"

# 1. 商标/专有冒用
TRADEMARK = re.compile(r"(官方认证|认证治疗师|Method\s*™|Gottman\s*Method|™|®|官方版|授权使用)")
# 2. 专有材料指纹（量表条目/版权页）
PROPRIETARY = re.compile(r"(第\s*\d+\s*题|条目\s*\d+|版权所有|All rights reserved|请勿翻印|©)")
# 3. 绝对化因果断言（证据限定场景下需缓和）
ABSOLUTE = re.compile(r"(必然|一定会|百分百|证明了|可治愈|彻底解决|永久)")
HEDGE = re.compile(r"(可能|往往|通常|有助于|倾向于|研究提示|经验法则|观察性|不一定|因人而异)")


def _scan_entry(d: dict) -> list[str]:
    flags = []
    text = f"{d.get('question','')} {d.get('answer','')}"
    cat = d.get("category", "")
    lic = d.get("license", "")

    if TRADEMARK.search(text):
        flags.append("商标/官方冒用措辞")
    if PROPRIETARY.search(text):
        flags.append("疑似专有材料指纹(量表/版权页)")
    if cat in RED_CATEGORIES and lic != RED_LICENSE:
        flags.append(f"红区 license 不符（应为「{RED_LICENSE}」，实为「{lic}」）")
    needs_hedge = cat in RED_CATEGORIES or bool(d.get("evidence_note"))
    if needs_hedge and ABSOLUTE.search(text) and not HEDGE.search(text):
        flags.append("绝对化断言但缺缓和措辞")
    if not lic:
        flags.append("license 为空")
    return flags


def main() -> int:
    ap = argparse.ArgumentParser(description="红区合规自动扫描（C4）")
    ap.add_argument("--dir", default="advisor_out/knowledge")
    args = ap.parse_args()

    files = sorted(glob.glob(str(Path(args.dir) / "**" / "*.jsonl"), recursive=True))
    total, flagged = 0, 0
    for f in files:
        for line in Path(f).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            total += 1
            fl = _scan_entry(d)
            if fl:
                flagged += 1
                print(f"  ⚠️ {d.get('id','?'):<32} {Path(f).name}")
                for x in fl:
                    print(f"      - {x}")

    print(f"\n[红区扫描] 共 {total} 条，命中 {flagged} 条需人工复核。")
    print("  注：命中 ≠ 违规，仅提示审核员重点看。零命中也仍需三级人工审核。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
