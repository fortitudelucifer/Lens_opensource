"""core/state.py — 全局可变单例

所有 services/ 和 routes/ 通过 `from ..core import state` 统一访问。
不在此文件 import services/routes（避免循环引用）。

命名约定：从 server.py 迁移的变量一律去掉前导下划线。
  - `_rag_conversations` → `state.rag_conversations`
  - `_semantic_rag` → `state.semantic_rag`
  - `pipeline_state` → `state.pipeline_state`（原本就没下划线，保留）

在函数中修改全局状态的方式：
  ```python
  from ..core import state
  state.rag_conversations = new_list  # 直接赋值，不需要 global
  ```
"""
from __future__ import annotations

import threading
from typing import Any, Optional

# ── RAG 数据（server.py L126-L136 迁移）────────────────────────────
rag_conversations: list[dict] = []
rag_user_profile: dict = {}
enriched_chunks: list[dict] = []
enriched_day_index: dict[int, list[int]] = {}   # day → conv indices
enriched_type_index: dict[str, list[int]] = {}  # type → conv indices
enriched_max_day: int = 0
chunk_id_to_idx: dict[str, int] = {}            # chunk_id → index

# ChunkAwareRAG 语义检索实例（FAISS + BGE-M3，后台初始化）
semantic_rag: Optional[Any] = None              # ChunkAwareRAG 实例
semantic_rag_ready: bool = False

# ── Ollama 生命周期（server.py L270-L272）─────────────────────────
ollama_lock: threading.Lock = threading.Lock()
ollama_proc: Optional[Any] = None               # subprocess.Popen 实例
ollama_last_use: float = 0.0

# ── 姓名映射（server.py L355-L358）────────────────────────────────
name_mapping: dict[str, str] = {}  # 真名/昵称 → ME/OTHER
name_reverse: dict[str, str] = {}  # ME/OTHER → 主名
me_names: list[str] = []
other_names: list[str] = []

# ── 安全/意图（server.py L398, L402）──────────────────────────────
crisis_detector: Optional[Any] = None  # CrisisDetector 实例
intent_classifier: Optional[Any] = None  # IntentClassifier 实例

# ── FAQ 知识库（server.py L666）───────────────────────────────────
faq_entries: list[dict] = []

# ── 流水线状态（server.py L850-L862）──────────────────────────────
pipeline_state: dict = {
    "phases": {
        1: {"name": "对话片段提取", "status": "idle", "detail": ""},
        2: {"name": "LLM 分析生成", "status": "idle", "detail": ""},
        3: {"name": "AI 自审", "status": "idle", "detail": ""},
        4: {"name": "人工审核", "status": "idle", "detail": ""},
        5: {"name": "训练数据格式化", "status": "idle", "detail": ""},
        6: {"name": "LoRA 微调", "status": "idle", "detail": ""},
        7: {"name": "GraphRAG 增量索引", "status": "idle", "detail": ""},
        8: {"name": "部署验证", "status": "idle", "detail": ""},
    },
    "current_phase": None,
    "last_update": None,
}

# ── 人工审核缓存（server.py L865）─────────────────────────────────
review_cache: dict[str, dict] = {}

# ── KeyChecker（server.py L2749-L2751）────────────────────────────
key_checker_rate_limits: dict[str, float] = {}
active_checks: dict[str, list] = {}

# ── Arena Elo 缓存（server.py L3411-L3412）────────────────────────
elo_cache: dict[str, dict] = {}
elo_battle_counts: dict[str, int] = {}
