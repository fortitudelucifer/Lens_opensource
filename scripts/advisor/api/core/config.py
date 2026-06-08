"""全局路径常量与目录初始化"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[4]

_env_file = PROJECT_ROOT / "local_secrets" / ".env.advisor"
if _env_file.exists():
    load_dotenv(_env_file, override=False)
    print(f"[env] 已加载 {_env_file}")
sys.path.insert(0, str(PROJECT_ROOT))

WORKSPACE = Path(os.environ.get("ADVISOR_WORKSPACE", PROJECT_ROOT))
USER_WORKSPACE = PROJECT_ROOT
ADVISOR_OUT = WORKSPACE / "advisor_out"
CHUNKS_DIR = ADVISOR_OUT / "chunks"
ANALYSIS_DIR = ADVISOR_OUT / "analysis"
REVIEW_DIR = ADVISOR_OUT / "review"
CHAT_DIR = ADVISOR_OUT / "chat_sessions"
VECTOR_INDEX_DIR = ADVISOR_OUT / "faiss_index"
FRONTEND_CHAT_SAMPLES_DIR = PROJECT_ROOT / "frontend" / "public" / "chat-samples"

ARENA_DIR = ADVISOR_OUT / "arena"
BATTLES_FILE = ARENA_DIR / "battles.jsonl"
ELO_FILE = ARENA_DIR / "elo_ratings.json"
ARENA_SESSION_DIR = ARENA_DIR / "sessions"

ASSESSMENT_DIR = ADVISOR_OUT / "assessments"

PREFS_PATH = ADVISOR_OUT / "model_preferences.json"

for d in [CHUNKS_DIR, ANALYSIS_DIR, REVIEW_DIR, CHAT_DIR, ARENA_DIR, ARENA_SESSION_DIR, ASSESSMENT_DIR]:
    d.mkdir(parents=True, exist_ok=True)
