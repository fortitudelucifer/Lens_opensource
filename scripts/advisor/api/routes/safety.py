"""routes/safety.py — 安全伦理 API（S2）"""
from __future__ import annotations

import yaml
from fastapi import APIRouter

from ..core import state
from ..core.config import PROJECT_ROOT

router = APIRouter()


@router.get("/api/safety/hotlines")
async def get_hotlines():
    """获取危机热线资源"""
    return {"hotlines": state.crisis_detector.get_hotlines(top_n=5)}


@router.get("/api/safety/consent")
async def get_consent_text():
    """获取知情同意文本"""
    consent_path = PROJECT_ROOT / "configs" / "consent_text.yaml"
    if consent_path.exists():
        with open(consent_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {"error": "consent config not found"}


@router.get("/api/safety/self-help")
async def get_self_help_resources():
    """获取自助资源（黄色级别展示）"""
    res_path = PROJECT_ROOT / "configs" / "crisis_resources.yaml"
    if res_path.exists():
        with open(res_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        return {"self_help": cfg.get("self_help_resources", {})}
    return {"self_help": {}}


@router.get("/api/safety/professional")
async def get_professional_resources():
    """获取专业资源引导（橙色级别展示）"""
    res_path = PROJECT_ROOT / "configs" / "crisis_resources.yaml"
    if res_path.exists():
        with open(res_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        return {
            "guidance": cfg.get("professional_guidance", {}),
            "hotlines": cfg.get("national_hotlines", []),
            "regional": cfg.get("regional_resources", []),
            "special": cfg.get("special_resources", []),
        }
    return {"guidance": {}, "hotlines": []}
