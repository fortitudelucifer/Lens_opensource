"""routes/assessment.py — 交流前测评系统（S3.3）"""
from __future__ import annotations

import json
import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException

from ..core.config import ASSESSMENT_DIR
from ..core.models import AssessmentSubmission, AssessmentToggleInject
from ..services import assessment_service

router = APIRouter()


@router.get("/api/assessment/questions")
async def get_assessment_questions():
    return assessment_service.ASSESSMENT_QUESTIONS


@router.post("/api/assessment/submit")
async def submit_assessment(submission: AssessmentSubmission):
    answers = submission.answers
    phq2_total = sum(answers.get(f"phq2_{i}", 0) for i in [1, 2])
    gad2_total = sum(answers.get(f"gad2_{i}", 0) for i in [1, 2])
    phq2_result = assessment_service.interpret_phq2(phq2_total)
    gad2_result = assessment_service.interpret_gad2(gad2_total)
    attachment_result = assessment_service.interpret_attachment(answers)
    conflict_result = assessment_service.interpret_conflict(submission.conflict_choice or "")

    result = {
        "id": f"assess-{uuid.uuid4().hex[:8]}",
        "timestamp": datetime.now().isoformat(),
        "answers": answers,
        "conflict_choice": submission.conflict_choice,
        "inject_enabled": submission.inject_enabled,
        "phq2": {"total": phq2_total, **phq2_result},
        "gad2": {"total": gad2_total, **gad2_result},
        "attachment": attachment_result,
        "conflict": conflict_result,
        "context_injection": assessment_service.build_assessment_context(
            phq2_result, gad2_result, attachment_result, conflict_result,
        ),
    }
    p = ASSESSMENT_DIR / f"{result['id']}.json"
    with open(p, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return result


@router.post("/api/assessment/toggle-inject")
async def toggle_assessment_inject(body: AssessmentToggleInject):
    files = sorted(ASSESSMENT_DIR.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
    if not files:
        raise HTTPException(404, "No assessment found")
    with open(files[0], "r", encoding="utf-8") as f:
        data = json.load(f)
    data["inject_enabled"] = body.inject_enabled
    with open(files[0], "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return {"status": "ok", "inject_enabled": body.inject_enabled}


@router.get("/api/assessment/latest")
async def get_latest_assessment():
    files = sorted(ASSESSMENT_DIR.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
    if not files:
        return {"exists": False}
    with open(files[0], "r", encoding="utf-8") as f:
        data = json.load(f)
    return {"exists": True, **data}


@router.get("/api/assessment/{assessment_id}")
async def get_assessment(assessment_id: str):
    p = ASSESSMENT_DIR / f"{assessment_id}.json"
    if not p.exists():
        raise HTTPException(404, "Assessment not found")
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)
