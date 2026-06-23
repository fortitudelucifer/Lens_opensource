#!/usr/bin/env python3
"""
知识库 v1 → v2 迁移脚本（WS-F · F3）

功能：
- 给 advisor_out/knowledge/ 下现有 FAQ 条目回填 v2 字段
  （id / evidence_tier / intervention_or_lens / risk_level / related
   / evidence_note / review_status / reviewed_by / review_date）
- 按 category 应用默认证据标签；幂等（已存在字段不覆盖）
- 回填后用 KnowledgeEntry 逐条校验；任一文件出错则不写该文件
- 现有线上条目标 review_status=approved（grandfathered），保持当前检索行为不变

默认 dry-run（仅预览），加 --apply 才写回。

用法：
    conda run -n wechatDHA python -m scripts.advisor.migrate_knowledge_v2            # 预览
    conda run -n wechatDHA python -m scripts.advisor.migrate_knowledge_v2 --apply    # 写回

作者：Claude (Opus 4.8) · 2026-06-19
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.advisor.knowledge_schema import KnowledgeEntry  # noqa: E402


# category → (evidence_tier, intervention_or_lens, risk_level)
CATEGORY_DEFAULTS: dict[str, tuple[str, str, str]] = {
    "sociology":   ("lens", "lens", "general"),
    "philosophy":  ("lens", "lens", "general"),
    "game_theory": ("lens", "lens", "general"),
    "cultural":    ("lens", "lens", "general"),
    "communication": ("moderate", "intervention", "general"),
    "crisis":      ("moderate", "intervention", "elevated"),
    "eft":         ("well_established", "intervention", "general"),
}

LEGACY_REVIEWER = "legacy_grandfathered"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def migrate_entry(entry: dict, file_stem: str, seq: int) -> dict:
    """回填单条目的 v2 字段（幂等：已存在不覆盖）。返回新 dict（id 在最前）。"""
    cat = entry.get("category", "")
    tier, iol, risk = CATEGORY_DEFAULTS.get(cat, ("moderate", "intervention", "general"))

    eid = entry.get("id") or f"{file_stem}_{seq:02d}"
    # id 优先，其后保留原字段顺序，再补 v2 新字段
    new: dict = {"id": eid}
    new.update(entry)
    new.setdefault("evidence_tier", tier)
    new.setdefault("intervention_or_lens", iol)
    new.setdefault("risk_level", risk)
    new.setdefault("related", [])
    new.setdefault("evidence_note", "")
    new.setdefault("review_status", "approved")  # grandfathered：保持线上行为
    new.setdefault("reviewed_by", LEGACY_REVIEWER)
    new.setdefault("review_date", "")
    return new


def main() -> int:
    ap = argparse.ArgumentParser(description="知识库 v1→v2 迁移")
    ap.add_argument("--dir", default=str(_repo_root() / "advisor_out" / "knowledge"))
    ap.add_argument("--apply", action="store_true", help="写回（默认仅预览）")
    args = ap.parse_args()

    knowledge_dir = Path(args.dir)
    files = sorted(knowledge_dir.rglob("*.jsonl"))
    if not files:
        print(f"[迁移] 未找到 .jsonl：{knowledge_dir}")
        return 1

    total, migrated_files, file_errors = 0, 0, []
    for p in files:
        rel = p.relative_to(knowledge_dir)
        lines = [l for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
        new_lines, errs, changed = [], [], 0
        for i, line in enumerate(lines, 1):
            raw = json.loads(line)
            had_id = "id" in raw
            new = migrate_entry(raw, p.stem, i)
            if not had_id:
                changed += 1
            try:
                KnowledgeEntry(**new)  # 校验
            except Exception as e:
                errs.append(f"{rel}:{i} {e}")
            new_lines.append(json.dumps(new, ensure_ascii=False))
        total += len(lines)
        if errs:
            file_errors.extend(errs)
            print(f"[迁移] ❌ {rel}: {len(errs)} 条校验失败，跳过写入")
            continue
        print(f"[迁移] {rel}: {len(lines)} 条（新回填 {changed}）")
        if args.apply:
            p.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
            migrated_files += 1

    print(f"\n[迁移] 合计 {total} 条；{'已写回 ' + str(migrated_files) + ' 文件' if args.apply else '预览模式（未写回，加 --apply 生效）'}")
    if file_errors:
        print(f"[迁移] ❌ {len(file_errors)} 条校验失败：")
        for e in file_errors:
            print(f"   - {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
