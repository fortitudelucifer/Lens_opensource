from __future__ import annotations

import json
from collections import Counter
from datetime import datetime

from fastapi import APIRouter

from scripts.advisor.knowledge_schema import CATEGORY_TO_DOMAIN

from ..core.config import ADVISOR_OUT

router = APIRouter()


@router.get("/api/knowledge/stats")
async def get_knowledge_stats():
    knowledge_dir = ADVISOR_OUT / "knowledge"
    files = []
    categories: Counter[str] = Counter()
    domains: Counter[str] = Counter()
    review_status: Counter[str] = Counter()
    risk_level: Counter[str] = Counter()
    errors = []
    total_entries = 0
    approved_entries = 0
    searchable_entries = 0

    if knowledge_dir.exists():
        for p in sorted(knowledge_dir.rglob("*.jsonl")):
            rel = p.relative_to(knowledge_dir).as_posix()
            file_categories: Counter[str] = Counter()
            file_domains: Counter[str] = Counter()
            file_entries = 0
            file_approved = 0
            file_searchable = 0
            for ln, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError as e:
                    errors.append({"file": rel, "line": ln, "error": str(e)})
                    continue

                category = entry.get("category") or "unknown"
                domain = CATEGORY_TO_DOMAIN.get(category, "unknown")
                status = entry.get("review_status") or "missing"
                risk = entry.get("risk_level") or "general"
                is_approved = status == "approved"
                is_searchable = is_approved and risk != "crisis"

                file_entries += 1
                total_entries += 1
                if is_approved:
                    file_approved += 1
                    approved_entries += 1
                if is_searchable:
                    file_searchable += 1
                    searchable_entries += 1
                file_categories[category] += 1
                file_domains[domain] += 1
                categories[category] += 1
                domains[domain] += 1
                review_status[status] += 1
                risk_level[risk] += 1

            files.append({
                "path": rel,
                "entries": file_entries,
                "approved_entries": file_approved,
                "searchable_entries": file_searchable,
                "categories": dict(sorted(file_categories.items())),
                "domains": dict(sorted(file_domains.items())),
            })

    return {
        "total_entries": total_entries,
        "approved_entries": approved_entries,
        "searchable_entries": searchable_entries,
        "total_files": len(files),
        "active_files": sum(1 for f in files if f["entries"] > 0),
        "categories": dict(sorted(categories.items())),
        "domains": dict(sorted(domains.items())),
        "review_status": dict(sorted(review_status.items())),
        "risk_level": dict(sorted(risk_level.items())),
        "files": files,
        "errors": errors,
        "generated_at": datetime.now().isoformat(),
    }
