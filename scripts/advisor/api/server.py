#!/usr/bin/env python3
"""
Advisor Pipeline — FastAPI 后端服务

功能：
- 提供 Advisor 系统的完整 REST API 接口
- 支持实时 LLM 对话（SSE 流式响应，多轮会话管理）
- 流水线控制（运行 MoA 分析流水线、查看状态）
- 人工审核接口（列表/批准/拒绝/编辑分析结果）
- 数据统计和模型状态查询
- 模型连通性测试

API 端点：
1. /api/chat          — 真实 LLM 对话（SSE 流式，支持多轮会话和历史上下文）
2. /api/chat/sessions — 会话管理（列表/查看/删除/重命名）
3. /api/pipeline/*    — 流水线控制（运行/暂停/状态查询）
4. /api/review/*      — 人工审核（列表/批准/拒绝/编辑/批量操作）
5. /api/data/stats    — 数据统计（chunk 数量、分析完成率、训练数据量）
6. /api/models        — 模型后端状态（各后端可用性、显存占用）
7. /api/models/test   — 模型连通性测试（验证 API Key 和网络连接）

处理流程（/api/chat）：
1. 接收用户消息和会话 ID
2. 加载会话历史
3. IntentClassifier 分类意图 → 选择对话模式（listen/consult）
4. listen 模式：直接调用本地模型流式生成
5. consult 模式：GraphRAG 检索 → 云端分析 → SafetyLayer → 本地生成
6. SSE 流式返回 token

输入：
- HTTP 请求（JSON body）

输出：
- HTTP 响应（JSON 或 SSE 流）

依赖：
- fastapi: Web 框架
- uvicorn: ASGI 服务器
- scripts.advisor.*: 所有 Advisor 核心模块

使用示例：
    # 启动服务
    source /path/to/your/workspace/local_secrets/.env.advisor
    conda run -n CHAT_APP_DHA uvicorn scripts.advisor.api.server:app --reload --port 8787
    
    # 调用 API
    curl -X POST http://localhost:8787/api/chat \\
        -H "Content-Type: application/json" \\
        -d '{"message": "最近总是吵架怎么办", "session_id": "test"}'

注意事项：
- 启动前需要加载环境变量（API Key 等）
- 默认端口 8787，可通过 uvicorn 参数修改
- SSE 流式响应需要客户端支持 EventSource
- 会话数据存储在内存中，重启后丢失

作者：forcifer
更新于：2026-02-15
"""

import asyncio
import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from scripts.advisor.intent_classifier import IntentClassifier

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parents[3]

# 自动加载环境变量（API keys 等）
_env_file = PROJECT_ROOT / "local_secrets" / ".env.advisor"
if _env_file.exists():
    load_dotenv(_env_file, override=False)
    print(f"[env] 已加载 {_env_file}")
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.advisor.generator import AnalysisGenerator
from scripts.advisor.extractor import ConversationExtractor
from scripts.advisor.chunk_based_rag import ChunkAwareRAG

# ── App ──────────────────────────────────────────────────────
app = FastAPI(title="Advisor Pipeline API", version="2.2")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 全局路径 ─────────────────────────────────────────────────
WORKSPACE = Path(os.environ.get("ADVISOR_WORKSPACE", PROJECT_ROOT))
USER_WORKSPACE = Path("/path/to/your/workspace")
ADVISOR_OUT = WORKSPACE / "advisor_out"
CHUNKS_DIR = ADVISOR_OUT / "chunks"
ANALYSIS_DIR = ADVISOR_OUT / "analysis"
REVIEW_DIR = ADVISOR_OUT / "review"

CHAT_DIR = ADVISOR_OUT / "chat_sessions"
VECTOR_INDEX_DIR = ADVISOR_OUT / "faiss_index"
FRONTEND_CHAT_SAMPLES_DIR = PROJECT_ROOT / "frontend" / "public" / "chat-samples"

# 确保目录存在
for d in [CHUNKS_DIR, ANALYSIS_DIR, REVIEW_DIR, CHAT_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ── GraphRAG 轻量上下文 ──────────────────────────────────────
# 加载预构建的向量索引元数据（不需要 GPU，仅用于关键词检索）
_rag_conversations: list[dict] = []
_rag_user_profile: dict = {}
# ChunkAwareRAG enriched 数据（分析元数据 + 日期索引）
_enriched_chunks: list[dict] = []
_enriched_day_index: dict[int, list[int]] = {}  # day → conv indices
_enriched_type_index: dict[str, list[int]] = {}  # type → conv indices
_enriched_max_day: int = 0
_chunk_id_to_idx: dict[str, int] = {}  # chunk_id → index
# ChunkAwareRAG 语义检索实例（FAISS + BGE-M3，后台初始化）
_semantic_rag: Optional[ChunkAwareRAG] = None
_semantic_rag_ready: bool = False

def _load_rag_metadata():
    """加载预构建索引的元数据和用户档案（启动时调用一次）"""
    global _rag_conversations, _rag_user_profile
    global _enriched_chunks, _enriched_day_index, _enriched_type_index
    global _enriched_max_day, _chunk_id_to_idx
    meta_file = VECTOR_INDEX_DIR / "metadata.json"
    profile_file = VECTOR_INDEX_DIR / "user_profile.json"
    enriched_file = VECTOR_INDEX_DIR / "enriched_metadata.json"
    if meta_file.exists():
        try:
            with open(meta_file, 'r', encoding='utf-8') as f:
                meta = json.load(f)
            _rag_conversations = meta.get("conversations", [])
            print(f"[GraphRAG] 加载 {len(_rag_conversations)} 条对话元数据")
        except Exception as e:
            print(f"[GraphRAG] 元数据加载失败: {e}")
    if profile_file.exists():
        try:
            with open(profile_file, 'r', encoding='utf-8') as f:
                _rag_user_profile = json.load(f)
            print(f"[GraphRAG] 用户档案已加载")
        except Exception as e:
            print(f"[GraphRAG] 用户档案加载失败: {e}")
    # 加载 enriched metadata（ChunkAwareRAG 构建）
    if enriched_file.exists():
        try:
            with open(enriched_file, 'r', encoding='utf-8') as f:
                edata = json.load(f)
            _enriched_chunks = edata.get("chunks", [])
            _enriched_max_day = edata.get("max_day", 0)
            _enriched_day_index = {int(k): v for k, v in edata.get("day_index", {}).items()}
            _enriched_type_index = edata.get("type_index", {})
            _chunk_id_to_idx = {c["chunk_id"]: i for i, c in enumerate(_enriched_chunks)}
            print(f"[ChunkAwareRAG] 加载 {len(_enriched_chunks)} 条增强元数据, "
                  f"{len(_enriched_day_index)} 天, 最大第{_enriched_max_day}天")
        except Exception as e:
            print(f"[ChunkAwareRAG] 增强元数据加载失败: {e}")

_load_rag_metadata()


def _init_semantic_rag_background():
    """后台线程初始化 ChunkAwareRAG 语义检索（加载/构建 FAISS 索引）"""
    global _semantic_rag, _semantic_rag_ready
    try:
        faiss_index_dir = ADVISOR_OUT / "faiss_index"
        chunks_file = CHUNKS_DIR / "conversation_chunks.jsonl"
        # 优先使用反匿名化后的分析文件
        analysis_deanon = ANALYSIS_DIR / "fused_analysis_neutral_moa_deanon.jsonl"
        analysis_file = analysis_deanon if analysis_deanon.exists() else ANALYSIS_DIR / "fused_analysis_neutral_moa.jsonl"

        rag = ChunkAwareRAG({
            'embedding_model': '/data/models/bge-m3',
            'index_dir': str(faiss_index_dir),
            'use_gpu_for_embedding': True,
        })

        # 优先从磁盘加载已保存的 FAISS 索引
        if (faiss_index_dir / 'index.faiss').exists():
            if rag.load_index(str(faiss_index_dir)):
                _semantic_rag = rag
                _semantic_rag_ready = True
                print(f"[SemanticRAG] ✅ 从磁盘加载 FAISS 索引 ({rag._faiss_index.ntotal} 向量)")
                return

        # 无已保存索引 → 从原始数据构建
        if not chunks_file.exists():
            print("[SemanticRAG] ⚠️ conversation_chunks.jsonl 不存在，跳过语义索引")
            return

        print("[SemanticRAG] 🔧 首次构建 FAISS 索引（加载 BGE-M3 + 编码 500 chunks）...")
        rag.build_enriched_index(
            chunks_file=str(chunks_file),
            analysis_file=str(analysis_file) if analysis_file.exists() else None,
            show_progress=True,
        )
        # 保存到磁盘，下次启动直接加载
        rag.save_index(str(faiss_index_dir))
        _semantic_rag = rag
        _semantic_rag_ready = True
        print(f"[SemanticRAG] ✅ FAISS 索引构建并保存完成 ({rag._faiss_index.ntotal} 向量)")
    except Exception as e:
        print(f"[SemanticRAG] ❌ 初始化失败: {e}")
        import traceback
        traceback.print_exc()


# 后台线程启动语义 RAG（不阻塞服务启动）
_semantic_init_thread = threading.Thread(target=_init_semantic_rag_background, daemon=True)
_semantic_init_thread.start()


def _rag_search(query: str, top_k: int = 3) -> list[dict]:
    """
    轻量级关键词检索：从预构建索引的元数据中查找相关对话片段。
    不需要 GPU，使用关键词重叠度评分。
    """
    if not _rag_conversations:
        return []

    import re
    # 提取查询中的关键词（去除停用词）
    stop_words = {'的', '了', '是', '在', '我', '你', '他', '她', '它', '们',
                  '这', '那', '有', '和', '与', '对', '吗', '呢', '吧', '啊',
                  '不', '也', '都', '就', '会', '能', '要', '把', '被', '让',
                  '到', '说', '想', '看', '一个', '什么', '怎么', '为什么',
                  '觉得', '认为', '一种', '什么样', '怎样', '如何'}
    query_words = set(re.findall(r'[\u4e00-\u9fff]+', query))
    # 也保留长度 >= 2 的词
    keywords = {w for w in query_words if len(w) >= 2 and w not in stop_words}
    # 添加特殊人称标记
    if 'OTHER' in query.upper() or '对方' in query or '她' in query or '他' in query:
        keywords.add('OTHER')
    if 'ME' in query.upper() or '自己' in query:
        keywords.add('ME')

    if not keywords:
        return []

    scored = []
    for conv in _rag_conversations:
        text = conv.get("conversation_text", "")
        # 计算关键词命中数
        hits = sum(1 for kw in keywords if kw in text)
        if hits > 0:
            scored.append((hits, conv))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [item[1] for item in scored[:top_k]]


# ── Ollama 自动启动/停止管理 ────────────────────────────
_ollama_lock = threading.Lock()
_ollama_proc: Optional[subprocess.Popen] = None
_ollama_last_use: float = 0.0
_OLLAMA_IDLE_TIMEOUT = 300  # 5 分钟无输入则 kill


def _ensure_ollama_running() -> bool:
    """确保 Ollama 服务运行中。如果未启动则自动启动，返回是否成功。"""
    global _ollama_proc, _ollama_last_use
    _ollama_last_use = time.time()

    # 检查是否已运行
    try:
        r = httpx.get("http://localhost:11434/api/tags", timeout=2)
        if r.status_code == 200:
            return True
    except Exception:
        pass

    # 启动 Ollama
    with _ollama_lock:
        # 双重检查
        try:
            r = httpx.get("http://localhost:11434/api/tags", timeout=2)
            if r.status_code == 200:
                return True
        except Exception:
            pass

        print("[🚀 Ollama] 自动启动 Ollama 服务...")
        try:
            _ollama_proc = subprocess.Popen(
                ["ollama", "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            # 等待启动
            for _ in range(15):
                time.sleep(1)
                try:
                    r = httpx.get("http://localhost:11434/api/tags", timeout=2)
                    if r.status_code == 200:
                        print("[✅ Ollama] 服务已启动")
                        _start_ollama_watchdog()
                        return True
                except Exception:
                    continue
            print("[❌ Ollama] 启动超时")
            return False
        except FileNotFoundError:
            print("[❌ Ollama] 未安装 ollama 命令")
            return False
        except Exception as e:
            print(f"[❌ Ollama] 启动失败: {e}")
            return False


def _stop_ollama():
    """kill Ollama 进程"""
    global _ollama_proc
    if _ollama_proc and _ollama_proc.poll() is None:
        print("[🛑 Ollama] 空闲超时，关闭服务")
        _ollama_proc.terminate()
        try:
            _ollama_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _ollama_proc.kill()
        _ollama_proc = None


def _start_ollama_watchdog():
    """启动后台线程，空闲超时后自动 kill Ollama"""
    def _watchdog():
        while True:
            time.sleep(60)
            if time.time() - _ollama_last_use > _OLLAMA_IDLE_TIMEOUT:
                _stop_ollama()
                break
            if _ollama_proc is None or _ollama_proc.poll() is not None:
                break
    t = threading.Thread(target=_watchdog, daemon=True)
    t.start()


# ── 姓名映射（从 PII 基础设施加载）───────────────────────────
_name_mapping: dict[str, str] = {}  # 真名/昵称 → ME/OTHER
_name_reverse: dict[str, str] = {}  # ME/OTHER → 主名
_me_names: list[str] = []
_other_names: list[str] = []

def _load_name_mapping():
    """从 configs/anonymization.yaml 加载姓名映射（PII 基础设施的权威来源）"""
    global _name_mapping, _name_reverse, _me_names, _other_names
    import yaml
    anon_config = PROJECT_ROOT / "configs" / "anonymization.yaml"
    if not anon_config.exists():
        # 回退到 user_profile.json 中的 participants
        participants = _rag_user_profile.get("participants", {})
        for role, info in participants.items():
            real_name = info.get("name", "")
            if real_name:
                _name_reverse[role] = real_name
                _name_mapping[real_name] = role
                for alias in info.get("aliases", []):
                    _name_mapping[alias] = role
        return

    try:
        with open(anon_config, 'r', encoding='utf-8') as f:
            cfg = yaml.safe_load(f) or {}
        _me_names = cfg.get("me_names", [])
        _other_names = cfg.get("other_names", [])
        if _me_names:
            _name_reverse["ME"] = _me_names[0]  # 主名
            for name in _me_names:
                _name_mapping[name] = "ME"
        if _other_names:
            _name_reverse["OTHER"] = _other_names[0]  # 主名
            for name in _other_names:
                _name_mapping[name] = "OTHER"
        print(f"[PII] 姓名映射已加载: ME={_me_names}, OTHER={_other_names}")
    except Exception as e:
        print(f"[PII] 姓名映射加载失败: {e}")

_load_name_mapping()

# 意图分类器（维度2: 理解层面）
_intent_classifier = IntentClassifier()


def _parse_query_days(query: str) -> list[int]:
    """
    从用户查询中解析所有日期引用，支持:
    - 单日: 第108天, 2025年10月8日, 10月8日, 2025-10-08
    - 范围: 第108天到第110天, 第108-110天, 9月22日到9月25日
    - 相对: 最近一周, 最近三天, 上个月, 上周, 最后X天
    返回排序去重后的 day 列表
    """
    from datetime import datetime as _dt, timedelta as _td
    _day1 = _dt(2025, 6, 8)
    today_day = (_dt.now() - _day1).days + 1
    max_day = _enriched_max_day or today_day

    query_days = []

    def _date_to_day(year, month, day_of_month):
        try:
            d = (_dt(year, month, day_of_month) - _day1).days + 1
            if 1 <= d <= max_day + 30:
                return d
        except ValueError:
            pass
        return None

    def _expand_range(start, end):
        if start and end and start <= end:
            return list(range(start, min(end, max_day + 30) + 1))
        return []

    # ── 范围: 第X天到第Y天 / 第X-Y天 ──
    for m in re.finditer(r'第(\d+)[天日]?[到至\-~]第?(\d+)天', query):
        query_days.extend(_expand_range(int(m.group(1)), int(m.group(2))))
    for m in re.finditer(r'第(\d+)-(\d+)天', query):
        query_days.extend(_expand_range(int(m.group(1)), int(m.group(2))))

    # ── 范围: X月Y日到X月Z日 / X月Y日到Z日 ──
    for m in re.finditer(r'(\d{1,2})月(\d{1,2})[日号]?[到至\-~](\d{1,2})月(\d{1,2})[日号]?', query):
        s = _date_to_day(2025, int(m.group(1)), int(m.group(2)))
        e = _date_to_day(2025, int(m.group(3)), int(m.group(4)))
        query_days.extend(_expand_range(s, e))
    for m in re.finditer(r'(\d{1,2})月(\d{1,2})[日号]?[到至\-~](\d{1,2})[日号]', query):
        s = _date_to_day(2025, int(m.group(1)), int(m.group(2)))
        e = _date_to_day(2025, int(m.group(1)), int(m.group(3)))
        query_days.extend(_expand_range(s, e))

    # ── 范围: YYYY-MM-DD 到 YYYY-MM-DD ──
    for m in re.finditer(r'(\d{4})-(\d{1,2})-(\d{1,2})\s*[到至~]\s*(\d{4})-(\d{1,2})-(\d{1,2})', query):
        s = _date_to_day(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        e = _date_to_day(int(m.group(4)), int(m.group(5)), int(m.group(6)))
        query_days.extend(_expand_range(s, e))

    # ── 相对日期: 最近X天/周/月, 上个月, 上周 ──
    rel_patterns = {
        r'最近(\d+)天': lambda m: list(range(max(1, max_day - int(m.group(1)) + 1), max_day + 1)),
        r'最[后近]一周|上周': lambda m: list(range(max(1, max_day - 6), max_day + 1)),
        r'最[后近]两周': lambda m: list(range(max(1, max_day - 13), max_day + 1)),
        r'最[后近](\d+)周': lambda m: list(range(max(1, max_day - int(m.group(1)) * 7 + 1), max_day + 1)),
        r'上个月|最近一个月': lambda m: list(range(max(1, max_day - 29), max_day + 1)),
        r'最近(\d+)个月': lambda m: list(range(max(1, max_day - int(m.group(1)) * 30 + 1), max_day + 1)),
    }
    for pat, gen_fn in rel_patterns.items():
        m = re.search(pat, query)
        if m:
            query_days.extend(gen_fn(m))

    # ── 单日: 第X天 (排除已被范围捕获的) ──
    if not query_days:
        for d in re.findall(r'(?:第)?(\d+)天', query):
            d = int(d)
            if 1 <= d <= max_day:
                query_days.append(d)

    # ── 单日: YYYY年M月D日 ──
    if not query_days:
        for m in re.finditer(r'(\d{4})年(\d{1,2})月(\d{1,2})[日号]?', query):
            d = _date_to_day(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            if d:
                query_days.append(d)

    # ── 单日: M月D日 (默认 2025) ──
    if not query_days:
        for m in re.finditer(r'(\d{1,2})月(\d{1,2})[日号]', query):
            d = _date_to_day(2025, int(m.group(1)), int(m.group(2)))
            if d:
                query_days.append(d)

    # ── 单日: YYYY-MM-DD ──
    if not query_days:
        for m in re.finditer(r'(\d{4})-(\d{1,2})-(\d{1,2})', query):
            d = _date_to_day(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            if d:
                query_days.append(d)

    return sorted(set(query_days))


def _day_index_lookup(days: list[int], max_results: int = 20) -> list[dict]:
    """按 day 列表查 enriched index，返回 [{conv, enriched, score}]，去重"""
    results = []
    seen = set()
    for day in days:
        for idx in _enriched_day_index.get(day, []):
            if idx < len(_rag_conversations) and idx not in seen:
                conv = _rag_conversations[idx]
                echunk = _enriched_chunks[idx] if idx < len(_enriched_chunks) else {}
                results.append({'conv': conv, 'enriched': echunk, 'score': 10.0, '_idx': idx})
                seen.add(idx)
                if len(results) >= max_results:
                    return results
    return results


def _enriched_search(query: str, top_k: int = 3) -> list[dict]:
    """
    混合检索：日期精确 + FAISS 语义 → 合并去重 → 关键词回退。
    支持日期范围 (第X天到第Y天) 和相对日期 (最近一周/上个月)。
    返回 [{conv, enriched, score}]
    """
    if not _rag_conversations:
        return []

    # ── Level 1: 日期精确/范围命中 ──
    query_days = _parse_query_days(query)
    day_results = []
    if query_days and _enriched_day_index:
        day_results = _day_index_lookup(query_days, max_results=top_k * 2)

    # ── Level 2: FAISS 语义检索（如果已就绪）──
    semantic_results_list = []
    if _semantic_rag_ready and _semantic_rag is not None:
        try:
            semantic_results = _semantic_rag.query_enhanced(
                query_text=query, top_k=top_k, use_reranker=True,
            )
            if semantic_results:
                for sr in semantic_results:
                    idx = _chunk_id_to_idx.get(sr.chunk_id)
                    if idx is not None and idx < len(_rag_conversations):
                        conv = _rag_conversations[idx]
                        echunk = _enriched_chunks[idx] if idx < len(_enriched_chunks) else {}
                        semantic_results_list.append({
                            'conv': conv, 'enriched': echunk,
                            'score': sr.semantic_score, '_idx': idx,
                        })
        except Exception as e:
            print(f"[SemanticRAG] 语义检索异常，回退关键词: {e}")

    # ── 合并去重: 日期优先 + 语义补充 ──
    if day_results or semantic_results_list:
        merged = []
        seen_idx = set()
        # 日期命中排在前面（高置信度精确匹配）
        for r in day_results:
            idx = r.pop('_idx', None)
            if idx is not None:
                seen_idx.add(idx)
            merged.append(r)
        # 语义补充（去掉已被日期命中的）
        for r in semantic_results_list:
            idx = r.pop('_idx', None)
            if idx not in seen_idx:
                merged.append(r)
                seen_idx.add(idx)
        if merged:
            return merged[:top_k]

    # ── Level 3: 关键词回退 ──
    return _keyword_search(query, top_k)


def _keyword_search(query: str, top_k: int = 3) -> list[dict]:
    """纯关键词检索（语义检索不可用时的回退）"""
    stop_words = {'的', '了', '是', '在', '我', '你', '他', '她', '它', '们',
                  '这', '那', '有', '和', '与', '对', '吗', '呢', '吧', '啊',
                  '不', '也', '都', '就', '会', '能', '要', '把', '被', '让',
                  '到', '说', '想', '看', '一个', '什么', '怎么', '为什么',
                  '觉得', '认为', '一种', '什么样', '怎样', '如何'}
    query_words = set(re.findall(r'[\u4e00-\u9fff]+', query))
    keywords = {w for w in query_words if len(w) >= 2 and w not in stop_words}
    if 'OTHER' in query.upper() or '对方' in query:
        keywords.add('OTHER')
    if 'ME' in query.upper() or '自己' in query:
        keywords.add('ME')

    if not keywords:
        return []

    def _to_str(v):
        if isinstance(v, str):
            return v
        if isinstance(v, dict):
            return v.get('level', '') or str(v)
        if isinstance(v, list):
            return ' '.join(_to_str(x) for x in v)
        return str(v) if v else ''

    scored = []
    for i, conv in enumerate(_rag_conversations):
        text = conv.get("conversation_text", "")
        hits = sum(1 for kw in keywords if kw in text)
        if hits == 0:
            continue
        echunk = _enriched_chunks[i] if i < len(_enriched_chunks) else {}
        analysis = echunk.get('analysis', {})
        if analysis:
            analysis_text = ' '.join([
                _to_str(analysis.get('relationship_status', '')),
                _to_str(analysis.get('overall_assessment', '')),
                _to_str(analysis.get('key_issues', [])),
                _to_str(analysis.get('conflict_root_causes', [])),
            ])
            hits += sum(0.5 for kw in keywords if kw in analysis_text)
        scored.append({'conv': conv, 'enriched': echunk, 'score': hits})

    scored.sort(key=lambda x: x['score'], reverse=True)
    return scored[:top_k]


def _fmt_enriched_summary(echunk: dict) -> str:
    """格式化 enriched chunk 的分析摘要"""
    a = echunk.get('analysis', {})
    if not a:
        return ''
    parts = []
    if a.get('relationship_status'):
        parts.append(f"状态:{a['relationship_status']}")
    if a.get('risk_level'):
        parts.append(f"风险:{a['risk_level']}")
    if a.get('communication_quality'):
        parts.append(f"沟通:{a['communication_quality'][:20]}")
    if a.get('key_issues'):
        parts.append(f"核心:{a['key_issues'][0][:40]}...")
    return ' | '.join(parts)


def _extract_focus_sentences(text: str, query: str, max_sentences: int = 5) -> str:
    """维度5: 粒度控制 — 从 chunk 中提取与 query 最相关的句子（sentence focus mode）"""
    # 按消息行切分（对话格式: [时间] SPEAKER: 内容）
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    if len(lines) <= max_sentences:
        return text

    # 提取查询关键词
    query_words = set(re.findall(r'[\u4e00-\u9fff]{2,}', query))
    if not query_words:
        return '\n'.join(lines[:max_sentences])

    # 对每行评分
    scored = []
    for line in lines:
        hits = sum(1 for w in query_words if w in line)
        scored.append((hits, line))
    scored.sort(key=lambda x: x[0], reverse=True)

    # 取 top-N 且保持原始顺序
    top_lines = set(l for _, l in scored[:max_sentences])
    focused = [l for l in lines if l in top_lines]
    return '\n'.join(focused)


# 维度5: 多源融合 — FAQ 知识库（可扩展）
_faq_entries: list[dict] = []

def _load_faq_knowledge():
    """加载 FAQ 知识库（如果存在）"""
    global _faq_entries
    faq_path = ADVISOR_OUT / "knowledge" / "faq.jsonl"
    if not faq_path.exists():
        return
    try:
        with open(faq_path, 'r', encoding='utf-8') as f:
            _faq_entries = [json.loads(l) for l in f if l.strip()]
        print(f"[FAQ] 已加载 {len(_faq_entries)} 条 FAQ 知识")
    except Exception as e:
        print(f"[FAQ] 加载失败: {e}")

_load_faq_knowledge()


def _search_faq(query: str, top_k: int = 2) -> list[dict]:
    """从 FAQ 知识库检索"""
    if not _faq_entries:
        return []
    query_words = set(re.findall(r'[\u4e00-\u9fff]{2,}', query))
    scored = []
    for entry in _faq_entries:
        q_text = entry.get('question', '') + ' ' + entry.get('answer', '')
        hits = sum(1 for w in query_words if w in q_text)
        if hits > 0:
            scored.append(entry)
    scored.sort(key=lambda e: sum(1 for w in query_words
                                  if w in e.get('question', '')), reverse=True)
    return scored[:top_k]


def _build_rag_context(query: str, top_k: int = 3, max_preview: int = 500) -> str:
    """构建 GraphRAG 上下文注入文本（使用 ChunkAwareRAG 增强数据 + 意图分类）"""
    parts = []

    # ── 维度2: 意图分类 → 动态调整检索策略 ──
    intent_result = _intent_classifier.classify(query)
    strategy = _intent_classifier.get_search_strategy(intent_result)
    effective_top_k = max(top_k, strategy.get("top_k", top_k))

    # 姓名映射（让模型知道 ME/OTHER 对应的真实姓名）
    if _name_reverse:
        name_lines = []
        if _me_names:
            name_lines.append(f"ME = {_me_names[0]}（所有名称：{'、'.join(_me_names)}）")
        if _other_names:
            name_lines.append(f"OTHER = {_other_names[0]}（所有名称：{'、'.join(_other_names)}）")
        if name_lines:
            parts.append("【人物对照】\n" + "\n".join(name_lines)
                          + "\n注意：对话记录中使用 ME/OTHER 标记，分别对应上述真实身份。")

    # 用户档案
    if _rag_user_profile:
        profile_parts = []
        if _rag_user_profile.get("recurring_topics"):
            profile_parts.append(f"反复话题：{', '.join(_rag_user_profile['recurring_topics'])}")
        if _rag_user_profile.get("recurring_conflicts"):
            profile_parts.append(f"反复冲突：{', '.join(_rag_user_profile['recurring_conflicts'])}")
        if _rag_user_profile.get("top_emotions"):
            profile_parts.append(f"主要情绪：{', '.join(_rag_user_profile['top_emotions'])}")
        if _rag_user_profile.get("relationship_trend"):
            profile_parts.append(f"关系趋势：{_rag_user_profile['relationship_trend']}")
        if profile_parts:
            parts.append("【用户关系档案】\n" + "\n".join(profile_parts))

    # 意图提示（让 LLM 知道用户意图，优化回复策略）
    intent_hint_map = {
        "emotional_support": "用户正在宣泄情绪，请先共情再给建议",
        "urgent_emotional_support": "用户情绪强烈，请优先安抚",
        "moderate_emotional_support": "用户情绪低落，请温和关怀",
        "conflict_analysis": "用户讨论冲突，请引用相关对话细节进行分析",
        "relationship_guidance": "用户寻求建议，请给出具体可操作的建议",
        "factual_search": "用户查询具体信息，请精确回答",
    }
    hint = intent_hint_map.get(intent_result.suggested_action)
    if hint:
        parts.append(f"【交互提示】{hint}")

    # 增强检索（将真名替换为 ME/OTHER 以提升命中率）
    search_query = query
    for real_name, role in _name_mapping.items():
        search_query = search_query.replace(real_name, role)
    results = _enriched_search(search_query, top_k=effective_top_k)
    if not results:
        results = _enriched_search(query, top_k=effective_top_k)

    if results:
        # 历史模式（从分析中提取冲突根源）
        from collections import Counter
        cause_counter = Counter()
        for r in results:
            a = r.get('enriched', {}).get('analysis', {})
            for c in a.get('conflict_root_causes', []):
                short = c.split('：')[0] if '：' in c else c[:50]
                cause_counter[short] += 1
        if cause_counter:
            top_causes = [c for c, _ in cause_counter.most_common(3)]
            parts.append(f"【历史模式】反复冲突根源: {'; '.join(top_causes)}")

        # 相关对话片段（带分析摘要）
        # 维度5: factual_search 使用句级 focus mode，其余用段级预览
        use_focus = intent_result.suggested_action == "factual_search"
        type_label = {'conflict': '冲突', 'sweet': '甜蜜', 'normal': '日常'}
        history_parts = []
        for i, r in enumerate(results, 1):
            conv = r['conv']
            echunk = r.get('enriched', {})
            text = conv.get("conversation_text", "")
            days = echunk.get('days', [])
            ctype = echunk.get('chunk_type', conv.get('metadata', {}).get('chunk_type', 'unknown'))
            day_str = f"第{','.join(str(d) for d in days)}天" if days else '未知时间'
            tl = type_label.get(ctype, ctype)
            summary = _fmt_enriched_summary(echunk)

            header = f"片段{i}（{day_str} [{tl}]）"
            if summary:
                header += f"\n  分析: {summary}"
            if use_focus:
                preview = _extract_focus_sentences(text, query, max_sentences=8)
            else:
                preview = text[:max_preview] + ("..." if len(text) > max_preview else "")
            history_parts.append(f"{header}\n{preview}")
        parts.append("【相关历史对话片段】\n" + "\n\n".join(history_parts))

    # 维度5: 多源融合 — FAQ 知识库补充
    faq_results = _search_faq(query, top_k=2)
    if faq_results:
        faq_parts = []
        for fq in faq_results:
            faq_parts.append(f"Q: {fq.get('question', '')}\nA: {fq.get('answer', '')}")
        parts.append("【参考知识】\n" + "\n\n".join(faq_parts))

    return "\n\n".join(parts)

def _get_available_chat_backends(exclude: str = "") -> list[str]:
    """快速返回已配置 key 的 chat 后端列表（不做实际连通测试）"""
    env_prefix_map = AnalysisGenerator._ENV_PREFIX
    chat_capable = {"DeepSeek", "Kimi", "kimi", "Qwen", "deepseek", "qwen_cloud", "qwen_local", "glm"}
    available = []
    for backend, prefix in env_prefix_map.items():
        if backend == exclude or backend not in chat_capable:
            continue
        api_key = os.environ.get(f"{prefix}_API_KEY", "")
        if backend == "qwen_local" or (api_key and api_key != "not-needed"):
            available.append(backend)
    return available


# ── 全局状态 ─────────────────────────────────────────────────
pipeline_state = {
    "phases": {
        1: {"name": "对话片段提取", "status": "idle", "detail": ""},
        2: {"name": "LLM 分析生成", "status": "idle", "detail": ""},
        3: {"name": "AI 辅助审核", "status": "idle", "detail": ""},
        4: {"name": "人工审核", "status": "idle", "detail": ""},
        5: {"name": "训练数据格式化", "status": "idle", "detail": ""},
        6: {"name": "QLoRA 微调", "status": "idle", "detail": ""},
        7: {"name": "模型推理", "status": "idle", "detail": ""},
        8: {"name": "实时对话", "status": "idle", "detail": ""},
    },
    "running_task": None,
}

# 人工审核数据缓存
review_cache: dict[str, dict] = {}


# ── Pydantic 模型 ────────────────────────────────────────────
class ModelPreferences(BaseModel):
    analysis_backend: str = "qwen_cloud"
    analysis_model: str = ""
    review_backend: str = "Qwen"
    review_model: str = ""
    chat_backend: str = "DeepSeek"
    chat_model: str = ""


class ChatRequest(BaseModel):
    message: str
    agent_type: str = "neutral"
    mode: str = "listen"
    backend: str = "Qwen"
    stream: bool = True
    session_id: Optional[str] = None
    use_rag: bool = True


class ChatFeedback(BaseModel):
    session_id: str
    message_index: int = -1
    rating: int  # 1-5
    comment: str = ""


class ModelTestRequest(BaseModel):
    backend: str
    model: str = ""
    prompt: str = "请用一句话回复：你好"


class PipelineRunRequest(BaseModel):
    input_type: str = "l2"
    input_file: Optional[str] = None
    backend: str = "DeepSeek"
    agent_type: str = "neutral"
    limit: Optional[int] = None
    num_chunks: int = 20
    fusion_mode: bool = True  # True = 多专家并行融合 (DeepSeek+GLM+Kimi+Qwen)


class ReviewDecision(BaseModel):
    decision: str  # "approve" | "reject" | "edit"
    edited_analysis: Optional[str] = None
    notes: Optional[str] = None


# ── 长对话记忆压缩 ─────────────────────────────────────────────
# 解决深度对话中 agent 遗忘和编造问题：
# 1. 滑动窗口：保留最近 N 条完整消息
# 2. 历史摘要：将更早的消息压缩为摘要注入 system prompt
# 3. 关键事实：从 assistant 回复中提取关键信息持久存储

MAX_RECENT_MESSAGES = 20       # 保留最近 20 条完整消息
MAX_MSG_CHARS = 3000           # 历史中单条消息最大字符数（超过截断）
MAX_SUMMARY_ITEMS = 15         # 摘要中最多保留 15 条要点


def _compress_history_messages(session: dict) -> tuple[str, list[dict]]:
    """将超长对话历史压缩为 (摘要文本, 近期消息列表)
    
    Returns:
        summary: 旧消息摘要（空字符串表示无需压缩）
        recent: 近期消息列表（保留完整内容）
    """
    all_msgs = session.get("messages", [])
    if len(all_msgs) <= MAX_RECENT_MESSAGES:
        return "", all_msgs

    older = all_msgs[:-MAX_RECENT_MESSAGES]
    recent = all_msgs[-MAX_RECENT_MESSAGES:]

    # 从旧消息中提取要点
    summary_lines = []
    for msg in older:
        role_label = "你" if msg["role"] == "assistant" else "用户"
        content = msg["content"]
        if msg["role"] == "assistant":
            # 提取 assistant 回复的第一段有效内容（跳过空行和标题）
            for line in content.split('\n'):
                line = line.strip()
                if line and not line.startswith('#') and not line.startswith('---') and len(line) > 10:
                    summary_lines.append(f"- {role_label}回复: {line[:120]}")
                    break
        else:
            summary_lines.append(f"- {role_label}问: {content[:80]}")

    if not summary_lines:
        return "", all_msgs

    summary = (
        f"【对话历史摘要】（共 {len(older)} 条旧消息已压缩，以下为要点）\n"
        + "\n".join(summary_lines[-MAX_SUMMARY_ITEMS:])
    )

    # 从 session 中提取累积的关键事实
    facts = session.get("memory_facts", [])
    if facts:
        summary += "\n\n【本次对话已确认的关键信息】\n" + "\n".join(f"- {f}" for f in facts[-10:])

    return summary, recent


def _truncate_history_messages(messages: list[dict]) -> list[dict]:
    """截断历史中过长的单条消息，节省 token 预算"""
    result = []
    for msg in messages:
        if msg["role"] != "system" and len(msg.get("content", "")) > MAX_MSG_CHARS:
            truncated = dict(msg)
            truncated["content"] = msg["content"][:MAX_MSG_CHARS] + "\n...[回复过长已截断，完整内容已记录在会话中]"
            result.append(truncated)
        else:
            result.append(msg)
    return result


def _extract_memory_facts(assistant_response: str) -> list[str]:
    """从 assistant 回复中提取可持久化的关键事实
    
    提取规则：
    - 明确的日期+事件对（如 "9月24日发生了..."）
    - 标记为结论/建议的内容
    - 对用户关系状态的判断
    """
    facts = []
    # 日期事件对
    for m in re.finditer(
        r'(\d{1,2}月\d{1,2}[日号]?|第\d+天)[^。\n]{5,80}[。]?', assistant_response
    ):
        fact = m.group(0).strip()
        if len(fact) > 15:
            facts.append(fact[:120])
    # 关系状态判断
    for m in re.finditer(
        r'(?:关系状态|核心问题|根本原因|关键转折)[：:]\s*([^。\n]{5,100})', assistant_response
    ):
        facts.append(m.group(0)[:120])
    # 去重
    seen = set()
    unique = []
    for f in facts:
        key = f[:30]
        if key not in seen:
            seen.add(key)
            unique.append(f)
    return unique[:5]  # 每次最多提取 5 条


# ── 辅助函数 ─────────────────────────────────────────────────
def _get_generator(backend: str = "DeepSeek", model: str = None,
                   max_tokens: int = 65536) -> AnalysisGenerator:
    """根据后端创建 generator，自动从 env 读取配置"""
    config = {
        "backend": backend,
        "max_tokens": max_tokens,
        "rate_limit_delay": 5.0,
        "retry_delay": 15.0,
        "max_retries": 5,
    }
    if model:
        config["model"] = model
    return AnalysisGenerator(config)


def _mirror_to_user_workspace():
    """将 advisor_out/ 镜像到用户可访问的工作空间"""
    import shutil
    dest = USER_WORKSPACE / "advisor_out"
    for subdir in ["chunks", "analysis", "review"]:
        src = ADVISOR_OUT / subdir
        dst = dest / subdir
        dst.mkdir(parents=True, exist_ok=True)
        if src.exists():
            for f in src.iterdir():
                if f.is_file():
                    shutil.copy2(str(f), str(dst / f.name))


def _count_jsonl_lines(path: Path) -> int:
    if not path.exists():
        return 0
    with open(path, "r", encoding="utf-8") as f:
        return sum(1 for line in f if line.strip())


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    items = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


# ══════════════════════════════════════════════════════════════
# 1. CHAT — 多轮会话对话
# ══════════════════════════════════════════════════════════════

CHAT_SYSTEM_PROMPTS = {
    "neutral": {
        "listen": (
            "你是一位专业的中立关系顾问，立场客观、不偏向任何一方。当前模式是倾听模式。\n\n"
            "回复风格：\n"
            "- 用温和、支持的语气回应，展现真诚的共情和理解\n"
            "- 复述并映射对方的核心感受，让对方感到被真正听见\n"
            "- 提出 1-2 个开放性问题引导对方深入表达\n"
            "- 可以提供初步观察（如沟通模式、情绪特征），但避免过度分析\n"
            "- 如果有历史对话上下文，适当引用其中的模式帮助对方建立连接\n\n"
            "回复长度：请回复 5-7 句话，充分展开，让对方感受到被认真对待。不要在回复中提及字数。"
        ),
        "consult": (
            "你是一位专业的中立关系顾问，立场客观、不偏向任何一方。当前模式是深度互动。\n\n"
            "回复结构（必须严格按以下框架组织，每个部分都要充分展开）：\n"
            "1. **共情回应**：先回应对方的情绪和处境，让对方感到被真正听见。要具体、不要泛泛而谈。\n"
            "2. **多维分析**（核心部分，请用最大篇幅展开）：从以下维度中选择 2-3 个最相关的，每个维度写一段详细分析：\n"
            "   - 沟通模式（回避型/追逐型/攻击型/被动攻击型）\n"
            "   - 情绪管理（情绪识别、表达方式、调节策略）\n"
            "   - 依附风格（安全型/焦虑型/回避型/混乱型）\n"
            "   - 权力动态（谁主导、谁退让、决策模式）\n"
            "   - 家庭系统（原生家庭如何影响当前关系模式）\n"
            "   - 非暴力沟通视角（观察/感受/需要/请求）\n"
            "   每个维度必须引用具体的对话细节或行为举例，不要只给抽象结论。\n"
            "3. **具体建议**：给出 2-3 条可立即实践的行动建议，每条要包含具体操作步骤和示例话术\n"
            "4. **小结**：用一两句话总结核心洞察和下一步方向\n\n"
            "重要：如果有历史对话上下文，必须深度结合其中的具体对话、行为模式和情绪趋势进行分析。\n"
            "回复长度：请充分展开，写一篇 1500-3000 字的完整互动分析。不要在回复中提及字数。"
        ),
    },
    "supportive": {
        "listen": (
            "你是一位支持性关系顾问，始终站在用户（ME）这一方，提供无条件的情感支持和验证。当前模式是倾听模式。\n\n"
            "核心原则：\n"
            "- 首先验证用户的情感体验——你的感受完全合理\n"
            "- 从用户的角度理解问题，而不是\"两边都有道理\"\n"
            "- 绝不评判用户的情绪或行为\n"
            "- 让用户感到安全、被理解、被陪伴、不孤单\n"
            "- 用温暖真诚的语言鼓励用户继续表达\n"
            "- 如果有历史对话上下文，指出用户一直以来付出的努力和闪光点\n\n"
            "回复长度：请回复 5-7 句话，充分展开。不要在回复末尾标注字数或任何元信息。"
        ),
        "consult": (
            "你是一位支持性关系顾问，始终站在用户（ME）这一方，提供无条件的情感支持。当前模式是深度互动。\n\n"
            "回复结构：\n"
            "1. **情感验证**：充分肯定用户的感受和已做的努力，指出他们的勇气和不易\n"
            "2. **用户视角分析**：从用户的角度出发，分析当前困境：\n"
            "   - 用户的核心需求是什么？这些需求是否合理？（当然合理）\n"
            "   - 对方的行为如何影响了用户？\n"
            "   - 用户在关系中展现了哪些优秀品质？\n"
            "3. **保护性建议**：提供保护用户利益和情感健康的建议：\n"
            "   - 如何设立健康边界\n"
            "   - 如何表达自己的需求而不委屈自己\n"
            "   - 如何在关系中照顾好自己\n"
            "4. **鼓励与赋能**：强调用户的内在力量和成长空间\n\n"
            "如果有历史对话上下文，结合其中用户的正面互动和成长瞬间进行分析。\n"
            "回复长度：请充分展开，写一篇完整的支持性分析。不要在回复中提及字数。"
        ),
    },
    "psychoanalytic": {
        "listen": (
            "你是一位精神分析取向的关系顾问，整合客体关系理论和拉康派精神分析视角。当前模式是倾听模式。\n\n"
            "回复风格：\n"
            "- 以分析师的\"均匀悬浮注意力\"倾听，关注话语中的潜意识线索\n"
            "- 注意口误、重复、矛盾——这些往往是通往无意识的入口\n"
            "- 用好奇而非判断的语气探索：\"我注意到一个有趣的地方……\"\n"
            "- 适时指出可能的防御机制运作（投射、否认、合理化、理想化等）\n"
            "- 关注话语背后的欲望结构：对方真正想要的是什么？\n"
            "- 如果有历史对话上下文，指出反复出现的无意识模式\n\n"
            "回复长度：请回复 5-7 句话，充分展开。保持温和的探索式语气，像是在邀请对方一起好奇地审视自己。不要标注字数。"
        ),
        "consult": (
            "你是一位资深精神分析取向的关系顾问，整合客体关系理论和拉康派精神分析。当前模式是深度互动。\n\n"
            "请从以下理论框架进行深度分析（选择最相关的 3-4 个维度）：\n\n"
            "**客体关系维度：**\n"
            "- 依附风格分析：双方各自的依附类型（安全型/焦虑型/回避型/混乱型）及其互动模式\n"
            "- 早期客体关系：早年养育经历如何塑造了当前的关系期待和行为模式\n"
            "- 内在客体：对方在用户内心世界中扮演什么角色？是严厉的父母、理想化的拯救者、还是被贬低的客体？\n\n"
            "**防御机制维度：**\n"
            "- 识别双方的核心防御机制：分裂、投射、投射性认同、理想化/贬低、否认、合理化、反向形成等\n"
            "- 防御的功能：这些防御保护了什么？回避了什么焦虑？\n\n"
            "**拉康派维度：**\n"
            "- 三界动态：想象界（镜像认同、自我理想）、象征界（语言秩序、大他者的欲望）、实在界（创伤性内核、不可言说之物）\n"
            "- 欲望结构：\"你的欲望是大他者的欲望\"——用户真正渴望的是什么？这个欲望从何而来？\n"
            "- 主体位置：用户在关系中处于什么主体位置（歇斯底里主体/强迫症主体/倒错主体）？\n\n"
            "**关系动力维度：**\n"
            "- 无意识契约：双方之间是否存在未言说的\"交易\"？\n"
            "- 移情/反移情模式：双方如何将过去的关系模式投射到当前关系中？\n"
            "- 重复强迫：哪些痛苦的模式在反复上演？\n\n"
            "回复结构：\n"
            "1. 共情回应\n"
            "2. 理论框架分析（选择最相关的维度深入展开）\n"
            "3. 深层洞察（连接表面行为与无意识动力）\n"
            "4. 反思引导（温和地邀请对方思考）\n\n"
            "语气：像一位温和但深刻的分析师，呈现洞察时避免诊断式语言，用\"我观察到\"\"也许\"\"似乎\"等探索性表达。\n"
            "如果有历史对话上下文，从中发现深层关系动力、重复模式和无意识主题。\n"
            "回复长度：请充分展开，写一篇完整的精神分析式互动回复。不要标注字数。"
        ),
    },
}

# ── 会话管理 ─────────────────────────────────────────────────

def _session_path(session_id: str) -> Path:
    return CHAT_DIR / f"{session_id}.json"


def _load_session(session_id: str) -> Optional[dict]:
    p = _session_path(session_id)
    if not p.exists():
        return None
    with open(p, 'r', encoding='utf-8') as f:
        return json.load(f)


def _save_session(session: dict):
    p = _session_path(session['id'])
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(session, f, ensure_ascii=False, indent=2)


def _create_session(agent_type: str = "neutral", mode: str = "listen",
                    backend: str = "Qwen") -> dict:
    session = {
        "id": str(uuid.uuid4())[:8],
        "title": "",
        "agent_type": agent_type,
        "mode": mode,
        "backend": backend,
        "messages": [],
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
    }
    _save_session(session)
    return session


def _list_sessions() -> list[dict]:
    sessions = []
    for p in sorted(CHAT_DIR.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True):
        try:
            with open(p, 'r', encoding='utf-8') as f:
                s = json.load(f)
            sessions.append({
                "id": s["id"],
                "title": s.get("title", ""),
                "agent_type": s.get("agent_type", "neutral"),
                "mode": s.get("mode", "listen"),
                "backend": s.get("backend", ""),
                "message_count": len(s.get("messages", [])),
                "created_at": s.get("created_at", ""),
                "updated_at": s.get("updated_at", ""),
            })
        except (json.JSONDecodeError, KeyError):
            continue
    return sessions


def _build_text_snippet(text: str, keyword: str, radius: int = 45) -> str:
    """构建包含关键词的短摘录，便于前端展示全文命中上下文。"""
    if not text:
        return ""
    compact = re.sub(r"\s+", " ", text).strip()
    if not compact:
        return ""
    lower_compact = compact.lower()
    lower_keyword = keyword.lower()
    idx = lower_compact.find(lower_keyword)
    if idx < 0:
        return compact[: radius * 2 + 10]
    start = max(0, idx - radius)
    end = min(len(compact), idx + len(keyword) + radius)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(compact) else ""
    return f"{prefix}{compact[start:end]}{suffix}"


def _search_sessions(query: str, limit: int = 20) -> list[dict]:
    """搜索会话（标题匹配 + 全文匹配）。"""
    keyword = query.strip()
    if not keyword:
        return []

    keyword_lower = keyword.lower()
    matches: list[dict] = []
    for p in sorted(CHAT_DIR.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True):
        try:
            with open(p, 'r', encoding='utf-8') as f:
                s = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue

        title = s.get("title", "") or ""
        messages = s.get("messages", []) or []
        full_text_parts = []
        for msg in messages:
            content = msg.get("content", "") if isinstance(msg, dict) else ""
            if content:
                full_text_parts.append(str(content))
        full_text = "\n".join(full_text_parts)

        title_hit = keyword_lower in title.lower()
        full_hit = keyword_lower in full_text.lower() if full_text else False
        if not (title_hit or full_hit):
            continue

        if title_hit and full_hit:
            match_type = "title+fulltext"
        elif title_hit:
            match_type = "title"
        else:
            match_type = "fulltext"

        matches.append({
            "id": s.get("id", p.stem),
            "title": title,
            "agent_type": s.get("agent_type", "neutral"),
            "mode": s.get("mode", "listen"),
            "backend": s.get("backend", ""),
            "message_count": len(messages),
            "created_at": s.get("created_at", ""),
            "updated_at": s.get("updated_at", ""),
            "source": "chat",
            "match_type": match_type,
            "matched_excerpt": _build_text_snippet(full_text, keyword) if full_hit else "",
        })

        if len(matches) >= limit:
            break
    return matches


def _extract_sample_full_text(payload) -> str:
    """提取 chat-samples JSON 的对话文本，用于全文检索。"""
    if isinstance(payload, list):
        turns = payload
    elif isinstance(payload, dict):
        turns = payload.get("messages") or payload.get("conversation") or payload.get("turns") or []
    else:
        turns = []

    parts = []
    for item in turns:
        if not isinstance(item, dict):
            continue
        content = item.get("content") or item.get("text") or item.get("message")
        if content:
            parts.append(str(content))
    return "\n".join(parts)


def _search_sample_sessions(query: str, limit: int = 20) -> list[dict]:
    """搜索 frontend/public/chat-samples 下的会话样例（标题 + 全文）。"""
    keyword = query.strip()
    if not keyword:
        return []
    manifest_path = FRONTEND_CHAT_SAMPLES_DIR / "manifest.json"
    if not manifest_path.exists():
        return []

    keyword_lower = keyword.lower()
    results: list[dict] = []
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            file_list = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []

    if not isinstance(file_list, list):
        return []

    for file_name in file_list:
        if not isinstance(file_name, str):
            continue
        sample_path = FRONTEND_CHAT_SAMPLES_DIR / file_name
        if not sample_path.exists() or not sample_path.is_file():
            continue

        try:
            with open(sample_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue

        title = Path(file_name).stem
        full_text = _extract_sample_full_text(payload)
        title_hit = keyword_lower in title.lower()
        full_hit = keyword_lower in full_text.lower() if full_text else False
        if not (title_hit or full_hit):
            continue

        if title_hit and full_hit:
            match_type = "title+fulltext"
        elif title_hit:
            match_type = "title"
        else:
            match_type = "fulltext"

        results.append({
            "id": f"sample:{file_name}",
            "title": f"[样例] {title}",
            "agent_type": "neutral",
            "mode": "listen",
            "backend": "sample",
            "message_count": full_text.count("\n") + 1 if full_text else 0,
            "created_at": "",
            "updated_at": "",
            "source": "sample",
            "sample_file": file_name,
            "match_type": match_type,
            "matched_excerpt": _build_text_snippet(full_text, keyword) if full_hit else "",
        })

        if len(results) >= limit:
            break

    return results


@app.post("/api/chat/sessions")
async def create_session(
    agent_type: str = "neutral",
    mode: str = "listen",
    backend: str = "Qwen",
):
    """创建新会话"""
    session = _create_session(agent_type, mode, backend)
    return session


@app.get("/api/chat/sessions")
async def list_sessions():
    """列出所有会话"""
    return _list_sessions()


@app.get("/api/chat/sessions/search")
async def search_sessions(query: str, limit: int = 20):
    """会话搜索：支持标题匹配和全文匹配。"""
    safe_limit = max(1, min(limit, 100))
    chat_results = _search_sessions(query, limit=safe_limit)
    remain = max(0, safe_limit - len(chat_results))
    sample_results = _search_sample_sessions(query, limit=remain) if remain > 0 else []
    results = chat_results + sample_results
    return {
        "query": query,
        "total": len(results),
        "results": results,
    }


@app.get("/api/chat/sessions/{session_id}")
async def get_session(session_id: str):
    """获取会话详情（含全部消息）"""
    session = _load_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    return session


@app.delete("/api/chat/sessions/{session_id}")
async def delete_session(session_id: str):
    """删除会话"""
    p = _session_path(session_id)
    if not p.exists():
        raise HTTPException(status_code=404, detail="会话不存在")
    p.unlink()
    return {"message": "会话已删除"}


@app.post("/api/chat/feedback")
async def chat_feedback(fb: ChatFeedback):
    """反馈闭环（维度4: 交互层面）— 收集用户对 RAG 检索质量的评价"""
    feedback_dir = ADVISOR_OUT / "feedback"
    feedback_dir.mkdir(parents=True, exist_ok=True)
    feedback_file = feedback_dir / "chat_feedback.jsonl"

    entry = {
        "session_id": fb.session_id,
        "message_index": fb.message_index,
        "rating": max(1, min(5, fb.rating)),
        "comment": fb.comment,
        "timestamp": datetime.now().isoformat(),
    }
    with open(feedback_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return {"status": "ok", "message": f"反馈已记录 (rating={entry['rating']})"}


@app.post("/api/chat")
async def chat(req: ChatRequest):
    """多轮 LLM 对话（支持流式，自动追加历史，注入 GraphRAG 上下文）"""
    gen = _get_generator(req.backend)
    system_prompt = CHAT_SYSTEM_PROMPTS.get(req.agent_type, {}).get(
        req.mode, CHAT_SYSTEM_PROMPTS["neutral"]["listen"]
    )

    # GraphRAG 上下文注入（consult 模式注入更多 context，可通过 use_rag 显式关闭）
    if req.use_rag:
        rag_top_k = 5 if req.mode == "consult" else 3
        rag_context = _build_rag_context(req.message, top_k=rag_top_k,
                                         max_preview=1000 if req.mode == "consult" else 500)
        if rag_context:
            rag_intro = (
                "\n\n以下是来自用户真实聊天记录的背景信息，请结合这些信息进行回复。"
                "注意：ME 指用户本人，OTHER 指用户的伴侣/对方。\n\n"
            )
            if req.mode == "consult":
                rag_intro = (
                    "\n\n以下是来自用户真实聊天记录的详细背景信息。"
                    "请深度结合这些信息进行分析和建议，引用具体对话细节。"
                    "注意：ME 指用户本人，OTHER 指用户的伴侣/对方。\n\n"
                )
            system_prompt += rag_intro + rag_context

    # 加载或创建会话
    session = None
    if req.session_id:
        session = _load_session(req.session_id)
    if not session:
        session = _create_session(req.agent_type, req.mode, req.backend)

    # 自动生成会话标题（第一条消息的前 20 字）
    if not session.get("title"):
        session["title"] = req.message[:20] + ("..." if len(req.message) > 20 else "")

    # ── 长对话记忆压缩：滑动窗口 + 摘要 ──
    history_summary, recent_history = _compress_history_messages(session)
    if history_summary:
        system_prompt += "\n\n" + history_summary

    # 构建多轮消息：system + 近期历史 + 当前
    raw_messages = [{"role": "system", "content": system_prompt}]
    for msg in recent_history:
        raw_messages.append({"role": msg["role"], "content": msg["content"]})
    raw_messages.append({"role": "user", "content": req.message})

    # 截断历史中过长的单条消息，节省 token 预算
    raw_messages = _truncate_history_messages(raw_messages)

    # 合并连续同角色消息（用户多次重试会积累连续 user 消息，
    # 导致 DeepSeek/OpenAI 等要求交替角色的 API 返回 400）
    messages = []
    for msg in raw_messages:
        if messages and msg["role"] == messages[-1]["role"] and msg["role"] != "system":
            messages[-1]["content"] += "\n" + msg["content"]
        else:
            messages.append(dict(msg))

    # 保存用户消息到会话
    session["messages"].append({
        "role": "user",
        "content": req.message,
        "timestamp": datetime.now().isoformat(),
    })

    # 本地 Qwen 自动启动 Ollama
    if req.backend == "qwen_local":
        if not _ensure_ollama_running():
            session["updated_at"] = datetime.now().isoformat()
            _save_session(session)
            return StreamingResponse(
                iter([f"data: {json.dumps({'error': 'Ollama 服务启动失败，请检查是否已安装 ollama', 'session_id': session['id']})}\n\n"]),
                media_type="text/event-stream",
            )

    if req.stream and gen.base_url:
        collected_content = []
        _think_re = re.compile(r'<think>.*?</think>', re.DOTALL)
        in_think = False

        def _save_and_finalize(full_reply: str):
            """保存助手回复到会话，并提取关键事实到长期记忆"""
            session["messages"].append({
                "role": "assistant",
                "content": full_reply,
                "timestamp": datetime.now().isoformat(),
                "backend": req.backend,
                "model": gen.model,
            })
            # 提取关键事实到长期记忆
            new_facts = _extract_memory_facts(full_reply)
            if new_facts:
                existing = session.get("memory_facts", [])
                existing.extend(new_facts)
                # 保留最近 30 条事实，避免无限增长
                session["memory_facts"] = existing[-30:]
            session["updated_at"] = datetime.now().isoformat()
            session["agent_type"] = req.agent_type
            session["mode"] = req.mode
            session["backend"] = req.backend
            _save_session(session)

        async def _stream_response_api():
            """GLM-4.7 Response API SSE 流式
            
            第三方代理 代理特性（经多轮测试确认）:
            - 不支持多轮 input（assistant 在 input 中 → 400）
            - 忽略 instructions 参数（system 上下文丢失）
            - 支持 "system" role 在 input 中（单轮已验证 ✓）
            
            方案: system(含RAG+历史摘要) + user 的双消息单轮 input。
            """
            url = f"{gen.base_url.rstrip('/')}/responses"
            headers = {
                "Authorization": f"Bearer {gen.api_key}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            }
            # 合并：system prompt + 历史 → 一条 system 消息
            system_text = ""
            history_parts = []
            current_user_msg = ""
            for i, msg in enumerate(messages):
                if msg["role"] == "system":
                    system_text = msg["content"]
                elif msg["role"] == "assistant":
                    history_parts.append(f"[你之前的回复]\n{msg['content'][:2000]}")
                elif msg["role"] == "user":
                    if i < len(messages) - 1:
                        history_parts.append(f"[用户之前的消息]\n{msg['content']}")
                    else:
                        current_user_msg = msg["content"]
            if history_parts:
                system_text += "\n\n【对话历史】\n" + "\n\n".join(history_parts)
            api_input = [
                {"role": "system", "content": [{"type": "input_text", "text": system_text}]},
                {"role": "user", "content": [{"type": "input_text", "text": current_user_msg}]},
            ]
            payload = {
                "model": gen.model,
                "input": api_input,
                "store": False,
                "stream": True,
            }
            prefix = gen._ENV_PREFIX.get(gen.backend, '')
            effort = os.environ.get(f'{prefix}_REASONING_EFFORT', '')
            if effort:
                payload["reasoning"] = {"effort": effort}

            timeout = httpx.Timeout(connect=30.0, read=300.0, write=30.0, pool=30.0)
            try:
                with httpx.Client(timeout=timeout) as client:
                    with client.stream("POST", url, headers=headers, json=payload) as response:
                        response.raise_for_status()
                        current_event = None
                        for line in response.iter_lines():
                            if not line:
                                current_event = None
                                continue
                            if line.startswith("event:"):
                                current_event = line.split(":", 1)[1].strip()
                                continue
                            if not line.startswith("data:"):
                                continue
                            data_str = line.split(":", 1)[1].strip()
                            if data_str == "[DONE]":
                                break
                            try:
                                obj = json.loads(data_str)
                            except json.JSONDecodeError:
                                continue
                            event_type = obj.get("type") or current_event
                            if event_type == "response.output_text.delta":
                                delta = obj.get("delta", "")
                                if delta:
                                    collected_content.append(delta)
                                    yield f"data: {json.dumps({'content': delta})}\n\n"
                            elif event_type in ("response.completed", "response.done"):
                                break

                full_reply = ''.join(collected_content)
                if not full_reply.strip():
                    full_reply = "抱歉，模型未返回有效内容，请切换其他后端重试。"
                    yield f"data: {json.dumps({'content': full_reply})}\n\n"
                _save_and_finalize(full_reply)
                yield f"data: {json.dumps({'session_id': session['id']})}\n\n"
                yield "data: [DONE]\n\n"
            except Exception as e:
                err_msg = str(e)
                if '503' in err_msg or 'NO_AVAILABLE_TOKEN' in err_msg:
                    err_msg = f"{req.backend} 模型当前不可用 (额度耗尽/服务异常)"
                else:
                    err_msg = f"{req.backend} 调用失败: {err_msg[:150]}"
                alts = _get_available_chat_backends(exclude=req.backend)
                session["updated_at"] = datetime.now().isoformat()
                _save_session(session)
                yield f"data: {json.dumps({'error': err_msg, 'failed_backend': req.backend, 'available_backends': alts, 'session_id': session['id']})}\n\n"

        async def _stream_chat_completions():
            """标准 Chat Completions 流式（DeepSeek/Qwen/DeepSeek/Qwen 等）"""
            nonlocal in_think
            try:
                # 只有 Qwen/DeepSeek/GLM 等模型在 content 流中使用 <think> 标签
                # DeepSeek thinking 通过 reasoning_content 字段发送（已在上面单独处理）
                # 因此 auto-detect 只对 <think> 标签模型生效
                _THINK_TAG_BACKENDS = {"qwen_cloud", "qwen_local", "deepseek", "glm"}
                is_thinking = (
                    req.backend in _THINK_TAG_BACKENDS
                    and "think" in gen.model.lower()
                )
                # thinking 模型需要更大 max_tokens 预算
                # 但第三方代理 (第三方代理) 对 max_tokens 有上限，不能无限大
                _is_any_thinking = any(p in gen.model.lower() for p in ['think', 'reason', 'o1', 'o3', 'o4'])
                effective_max = 16384 if _is_any_thinking else min(gen.max_tokens, 16384)
                kwargs = dict(
                    model=gen.model,
                    messages=messages,
                    stream=True,
                    max_tokens=effective_max,
                )
                if not is_thinking and not _is_any_thinking:
                    if gen.temperature is not None:
                        kwargs["temperature"] = gen.temperature

                # 在线程中运行同步流，避免阻塞事件循环
                import asyncio
                import queue
                token_queue: queue.Queue = queue.Queue()
                _SENTINEL = object()

                def _run_sync_stream():
                    """在线程中执行同步 OpenAI 流式调用"""
                    try:
                        stream = gen.client.chat.completions.create(**kwargs)
                        for chunk in stream:
                            delta = chunk.choices[0].delta if chunk.choices else None
                            if delta:
                                # reasoning_content 单独作为 thinking 发送
                                rc = getattr(delta, 'reasoning_content', None)
                                if rc:
                                    token_queue.put(('thinking', rc))
                                    continue
                                token = delta.content
                                if token:
                                    token_queue.put(('token', token))
                        token_queue.put(('done', None))
                    except Exception as exc:
                        token_queue.put(('error', str(exc)))

                loop = asyncio.get_event_loop()
                loop.run_in_executor(None, _run_sync_stream)

                raw_tokens = []
                got_first_content = False
                while True:
                    # 非阻塞轮询，让出事件循环
                    try:
                        msg_type, msg_val = token_queue.get_nowait()
                    except queue.Empty:
                        await asyncio.sleep(0.05)
                        continue

                    if msg_type == 'done':
                        break
                    if msg_type == 'error':
                        raise Exception(msg_val)

                    # reasoning_content 直接作为 thinking 发送
                    if msg_type == 'thinking':
                        if not in_think:
                            in_think = True
                        yield f"data: {json.dumps({'thinking': msg_val})}\n\n"
                        continue

                    token = msg_val
                    raw_tokens.append(token)

                    # thinking 模型：如果代理剥离了 <think> 开头标签，
                    # 首个 content token 自动进入 thinking 模式
                    if is_thinking and not got_first_content and not in_think and '<think>' not in token:
                        if '</think>' not in token:
                            in_think = True
                            yield f"data: {json.dumps({'thinking': token})}\n\n"
                            continue

                    got_first_content = True

                    # 处理 <think> 标签：发送为单独的 thinking 字段
                    if '<think>' in token:
                        in_think = True
                        # 发送 <think> 之前的内容
                        before = token.split('<think>', 1)[0]
                        if before.strip():
                            collected_content.append(before)
                            yield f"data: {json.dumps({'content': before})}\n\n"
                        # 发送 <think> 之后的思考内容
                        think_part = token.split('<think>', 1)[1]
                        if '</think>' in think_part:
                            # 同一 token 内完成思考
                            in_think = False
                            think_text = think_part.split('</think>', 1)[0]
                            if think_text.strip():
                                yield f"data: {json.dumps({'thinking': think_text})}\n\n"
                            yield f"data: {json.dumps({'thinking_done': True})}\n\n"
                            after = think_part.split('</think>', 1)[1]
                            if after.strip():
                                collected_content.append(after)
                                yield f"data: {json.dumps({'content': after})}\n\n"
                        elif think_part.strip():
                            yield f"data: {json.dumps({'thinking': think_part})}\n\n"
                        continue
                    if in_think:
                        if '</think>' in token:
                            in_think = False
                            before_end = token.split('</think>', 1)[0]
                            if before_end.strip():
                                yield f"data: {json.dumps({'thinking': before_end})}\n\n"
                            yield f"data: {json.dumps({'thinking_done': True})}\n\n"
                            after = token.split('</think>', 1)[-1]
                            if after.strip():
                                collected_content.append(after)
                                yield f"data: {json.dumps({'content': after})}\n\n"
                        else:
                            # 仍在思考中，发送 thinking token
                            yield f"data: {json.dumps({'thinking': token})}\n\n"
                        continue

                    collected_content.append(token)
                    yield f"data: {json.dumps({'content': token})}\n\n"

                full_reply = ''.join(collected_content)
                if not full_reply.strip() and raw_tokens:
                    raw_full = ''.join(raw_tokens)
                    full_reply = _think_re.sub('', raw_full).strip()
                    full_reply = re.sub(r'<think>.*', '', full_reply, flags=re.DOTALL).strip()
                    if full_reply:
                        yield f"data: {json.dumps({'content': full_reply})}\n\n"

                if not full_reply.strip():
                    full_reply = "抱歉，模型未返回有效内容，请切换其他后端重试。"
                    yield f"data: {json.dumps({'content': full_reply})}\n\n"

                _save_and_finalize(full_reply)
                yield f"data: {json.dumps({'session_id': session['id']})}\n\n"
                yield "data: [DONE]\n\n"
            except Exception as e:
                err_msg = str(e)
                err_code = ''
                if '503' in err_msg or 'NO_AVAILABLE_TOKEN' in err_msg:
                    err_code = '503'
                    err_msg = f"{req.backend} 模型当前不可用 (额度耗尽/服务异常)"
                elif '429' in err_msg:
                    err_code = '429'
                    err_msg = f"{req.backend} API 限流，请稍后重试"
                elif '400' in err_msg:
                    err_code = '400'
                    err_msg = f"{req.backend} 请求格式错误，可能不支持当前参数"
                elif '401' in err_msg or '403' in err_msg:
                    err_code = '401'
                    err_msg = f"{req.backend} 认证失败，API key 可能已过期"
                else:
                    err_msg = f"{req.backend} 调用失败: {err_msg[:150]}"
                # 附带可用后端列表
                alts = _get_available_chat_backends(exclude=req.backend)
                session["updated_at"] = datetime.now().isoformat()
                _save_session(session)
                yield f"data: {json.dumps({'error': err_msg, 'error_code': err_code, 'failed_backend': req.backend, 'available_backends': alts, 'session_id': session['id']})}\n\n"

        # 根据后端选择流式方案
        # GLM-4.7 (第三方代理) 必须用 Response API；其余走 Chat Completions
        if gen._use_response_api:
            stream_fn = _stream_response_api()
        else:
            stream_fn = _stream_chat_completions()

        return StreamingResponse(stream_fn, media_type="text/event-stream")
    else:
        try:
            full_prompt = f"{system_prompt}\n\n用户：{req.message}"
            result = gen._call_api(full_prompt)
            # 剥离 <think> 标签（Qwen 等 thinking 模型在 non-stream 也会返回）
            if result and '<think>' in result:
                result = re.sub(r'<think>.*?</think>', '', result, flags=re.DOTALL).strip()
                if not result:
                    result = re.sub(r'<think>.*', '', result, flags=re.DOTALL).strip()
            session["messages"].append({
                "role": "assistant",
                "content": result,
                "timestamp": datetime.now().isoformat(),
                "backend": req.backend,
                "model": gen.model,
            })
            session["updated_at"] = datetime.now().isoformat()
            _save_session(session)
            return {
                "content": result,
                "model": gen.model,
                "backend": gen.backend,
                "session_id": session["id"],
            }
        except Exception as e:
            session["updated_at"] = datetime.now().isoformat()
            _save_session(session)
            raise HTTPException(status_code=500, detail=str(e))


# ── 模型连通性测试 ───────────────────────────────────────────

@app.post("/api/models/test")
async def test_model(req: ModelTestRequest):
    """测试模型连通性：发送一条简短消息验证 API 是否可用"""
    import asyncio
    start = time.time()
    try:
        gen = _get_generator(req.backend, req.model or None)
        messages = [
            {"role": "system", "content": "你是一个助手。"},
            {"role": "user", "content": req.prompt},
        ]
        kwargs = dict(
            model=gen.model,
            messages=messages,
            stream=False,
            max_tokens=200,
        )
        if not ("think" in gen.model.lower()):
            kwargs["temperature"] = 0.3

        # 在线程中运行同步调用，避免阻塞事件循环
        def _sync_call():
            return gen.client.chat.completions.create(**kwargs)

        resp = await asyncio.get_event_loop().run_in_executor(None, _sync_call)
        # 兼容 reasoning_content (GLM等)
        msg = resp.choices[0].message if resp.choices else None
        content = "(empty)"
        if msg:
            content = msg.content or getattr(msg, 'reasoning_content', None) or "(empty)"
        elapsed = time.time() - start

        return {
            "status": "ok",
            "backend": req.backend,
            "model": gen.model,
            "base_url": gen.base_url or "(default)",
            "response": content[:500],
            "latency_ms": round(elapsed * 1000),
        }
    except Exception as e:
        elapsed = time.time() - start
        return {
            "status": "error",
            "backend": req.backend,
            "model": req.model or "(default)",
            "error": str(e)[:500],
            "latency_ms": round(elapsed * 1000),
        }


# ── 增量更新 RAG 索引 ────────────────────────────────────────

@app.post("/api/rag/incremental-update")
async def rag_incremental_update(
    chunks_file: Optional[str] = None,
    analysis_file: Optional[str] = None,
):
    """
    增量更新 RAG 索引：添加新 chunks 到现有 FAISS 索引（无需全量重建）

    Args:
        chunks_file: 新 chunks 的 JSONL 文件路径（默认: conversation_chunks.jsonl）
        analysis_file: 对应的分析文件路径（可选）

    流程: 读取新 chunks → 过滤已存在的 → 追加到 FAISS + enriched_metadata → 保存
    """
    if not _semantic_rag_ready or _semantic_rag is None:
        raise HTTPException(status_code=503, detail="语义 RAG 未就绪，请等待初始化完成")

    chunks_path = Path(chunks_file) if chunks_file else ADVISOR_OUT / "chunks" / "conversation_chunks.jsonl"
    if not chunks_path.exists():
        raise HTTPException(status_code=404, detail=f"chunks 文件不存在: {chunks_path}")

    # 加载新 chunks
    new_chunks = []
    with open(chunks_path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                new_chunks.append(json.loads(line))

    # 加载分析数据（如有）
    analysis_map = {}
    if analysis_file:
        ap = Path(analysis_file)
        if ap.exists():
            with open(ap, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        a = json.loads(line)
                        cid = a.get('chunk_id', '')
                        if cid:
                            analysis_map[cid] = a.get('analysis_features', {})

    # 执行增量更新
    added = _semantic_rag.add_chunks_incremental(new_chunks, analysis_map)

    # 同步更新 server 级缓存
    if added > 0:
        _semantic_rag.save_index()
        # 重新加载 server 级 enriched data 以保持一致
        _reload_enriched_data()

    return {
        "status": "ok",
        "chunks_scanned": len(new_chunks),
        "chunks_added": added,
        "total_chunks": len(_rag_conversations),
    }


def _reload_enriched_data():
    """重新加载 server 级 enriched 缓存（增量更新后调用）"""
    global _rag_conversations, _enriched_chunks, _enriched_day_index, _enriched_max_day
    global _chunk_id_to_idx

    faiss_dir = ADVISOR_OUT / "faiss_index"
    meta_file = faiss_dir / "metadata.json"
    enriched_file = faiss_dir / "enriched_metadata.json"

    if meta_file.exists():
        with open(meta_file, 'r', encoding='utf-8') as f:
            meta = json.load(f)
        _rag_conversations = meta.get('conversations', [])
        _chunk_id_to_idx = {
            c.get('metadata', {}).get('chunk_id', c.get('conversation_id', '')): i
            for i, c in enumerate(_rag_conversations)
        }

    if enriched_file.exists():
        with open(enriched_file, 'r', encoding='utf-8') as f:
            edata = json.load(f)
        _enriched_chunks = edata.get('chunks', [])
        _enriched_day_index = {int(k): v for k, v in edata.get('day_index', {}).items()}
        _enriched_max_day = edata.get('max_day', 0)

    print(f"[RAG] 缓存已刷新: {len(_rag_conversations)} conversations, max_day={_enriched_max_day}")


# ══════════════════════════════════════════════════════════════
# 2. PIPELINE — 流水线控制
# ══════════════════════════════════════════════════════════════

@app.get("/api/pipeline/status")
async def get_pipeline_status():
    """获取流水线状态"""
    return pipeline_state


@app.post("/api/pipeline/run/{phase}")
async def run_pipeline_phase(phase: int, req: PipelineRunRequest):
    """运行指定阶段"""
    if phase < 1 or phase > 8:
        raise HTTPException(status_code=400, detail="Phase must be 1-8")
    if pipeline_state["running_task"]:
        raise HTTPException(status_code=409, detail="已有任务在运行中")

    pipeline_state["phases"][phase]["status"] = "running"
    pipeline_state["running_task"] = phase

    # 在后台线程运行
    asyncio.get_event_loop().run_in_executor(
        None, _run_phase_sync, phase, req
    )

    return {"message": f"Phase {phase} 已启动", "phase": phase}


def _run_phase_sync(phase: int, req: PipelineRunRequest):
    """同步执行 pipeline 阶段"""
    try:
        if phase == 1:
            _run_phase1_extract(req)
        elif phase == 2:
            _run_phase2_generate(req)
        elif phase == 3:
            _run_phase3_ai_review(req)
        else:
            pipeline_state["phases"][phase]["detail"] = "该阶段暂未实现自动化"
            pipeline_state["phases"][phase]["status"] = "idle"
            pipeline_state["running_task"] = None
            return

        pipeline_state["phases"][phase]["status"] = "done"
    except Exception as e:
        pipeline_state["phases"][phase]["status"] = "error"
        pipeline_state["phases"][phase]["detail"] = str(e)[:200]
    finally:
        pipeline_state["running_task"] = None


def _run_phase1_extract(req: PipelineRunRequest):
    """Phase 1: 提取对话片段"""
    if req.input_file:
        input_path = req.input_file
    elif req.input_type == "l1":
        input_path = str(USER_WORKSPACE / "timeline_out" / "agent_sft_l1.jsonl")
    else:
        input_path = str(USER_WORKSPACE / "timeline_out" / "agent_sft_l2.jsonl")

    # 也尝试本地工作空间
    if not Path(input_path).exists():
        alt = WORKSPACE / "timeline_out" / f"agent_sft_{req.input_type}.jsonl"
        if alt.exists():
            input_path = str(alt)

    output_path = str(CHUNKS_DIR / "conversation_chunks.jsonl")

    pipeline_state["phases"][1]["detail"] = f"提取中... input={Path(input_path).name}"

    config = {
        "window_size": 20,
        "step_size": 10,
        "min_messages": 5,
        "exclude_system": True,
        "exclude_types": [],
    }
    extractor = ConversationExtractor(config)
    chunks = extractor.extract_chunks(input_path, num_chunks=req.num_chunks)
    extractor.save_chunks(chunks, output_path)

    stats = extractor.get_stats()
    pipeline_state["phases"][1]["detail"] = (
        f"已提取 {stats['filtered_chunks']} 个片段 "
        f"(冲突:{stats['conflict_chunks']} 甜蜜:{stats['sweet_chunks']} 普通:{stats['normal_chunks']})"
    )
    _mirror_to_user_workspace()


def _run_phase2_generate(req: PipelineRunRequest):
    """Phase 2: LLM 分析生成

    fusion_mode=True (默认): 多专家并行融合 (DeepSeek+GLM+Kimi+Qwen)
    fusion_mode=False: 单后端生成 (向后兼容)
    """
    input_path = str(CHUNKS_DIR / "conversation_chunks.jsonl")

    if not Path(input_path).exists():
        raise FileNotFoundError("请先运行 Phase 1 提取对话片段")

    chunks = _load_jsonl(Path(input_path))
    if req.limit:
        chunks = chunks[: req.limit]

    if req.fusion_mode:
        # ── 融合模式: 并行调用 DeepSeek+GLM+(Kimi)+Qwen ──
        from scripts.advisor.run_all._02c_fusion_pipeline import (
            _create_generator, process_single_chunk, scan_completed,
        )

        output_path = str(ANALYSIS_DIR / f"fused_analysis_{req.agent_type}.jsonl")
        pipeline_state["phases"][2]["detail"] = (
            f"融合生成中... agent={req.agent_type} n={len(chunks)} (DeepSeek+GLM+Qwen)"
        )

        generators = {
            "DeepSeek": _create_generator("DeepSeek"),
            "GLM": _create_generator("GLM"),
            "Kimi": _create_generator("Kimi"),
            "Qwen": _create_generator("Qwen"),
        }

        completed_ids = scan_completed(output_path)
        pending = [c for c in chunks if c.get("chunk_id", "") not in completed_ids]

        success = 0
        failed = 0
        with open(output_path, "a", encoding="utf-8") as f:
            for i, chunk in enumerate(pending):
                pipeline_state["phases"][2]["detail"] = (
                    f"融合中... [{i+1}/{len(pending)}] {chunk.get('chunk_id','')} "
                    f"(ok={success} fail={failed})"
                )
                result = process_single_chunk(
                    chunk, req.agent_type, generators,
                    skip_Kimi_non_multimodal=True,
                    skip_review=False,
                )
                mq = result.get("merge_quality", "failed")
                if mq != "failed":
                    success += 1
                else:
                    failed += 1
                f.write(json.dumps(result, ensure_ascii=False) + "\n")
                f.flush()
                import time as _time
                _time.sleep(3.0)

        pipeline_state["phases"][2]["detail"] = (
            f"融合完成: 成功={success} 失败={failed} (共{len(completed_ids)+success+failed}条)"
        )
    else:
        # ── 单后端模式 (向后兼容) ──
        output_path = str(ANALYSIS_DIR / f"raw_analysis_{req.agent_type}.jsonl")
        pipeline_state["phases"][2]["detail"] = (
            f"生成中... backend={req.backend} agent={req.agent_type} n={len(chunks)}"
        )
        gen = _get_generator(req.backend)
        gen.batch_generate(chunks, req.agent_type, output_path)

        stats = gen.get_stats()
        pipeline_state["phases"][2]["detail"] = (
            f"完成: 成功={stats['success']} 失败={stats['failed']} tokens={stats['total_tokens']}"
        )

    _mirror_to_user_workspace()


def _run_phase3_ai_review(req: PipelineRunRequest):
    """Phase 3: AI 辅助审核"""
    # 优先使用融合分析结果，否则回退到单后端结果
    fused_path = ANALYSIS_DIR / f"fused_analysis_{req.agent_type}.jsonl"
    raw_path = ANALYSIS_DIR / f"raw_analysis_{req.agent_type}.jsonl"
    input_path = str(fused_path if fused_path.exists() else raw_path)
    output_path = str(REVIEW_DIR / f"ai_review_{req.agent_type}.jsonl")

    if not Path(input_path).exists():
        raise FileNotFoundError("请先运行 Phase 2 生成分析")

    items = _load_jsonl(Path(input_path))
    if req.limit:
        items = items[: req.limit]

    pipeline_state["phases"][3]["detail"] = (
        f"审核中... backend={req.backend} n={len(items)}"
    )

    # 导入审核函数
    from scripts.advisor.run_all._03b_ai_review import review_single

    reviewer = _get_generator(req.backend)
    results = []
    passed = 0
    failed = 0

    with open(output_path, "w", encoding="utf-8") as f:
        for i, item in enumerate(items):
            pipeline_state["phases"][3]["detail"] = f"审核中 {i+1}/{len(items)}"
            review = review_single(reviewer, item)

            if review.get("passed"):
                passed += 1
            else:
                failed += 1

            output_item = {
                "id": str(uuid.uuid4()),
                "chunk_id": item.get("chunk_id", ""),
                "conversation": item.get("conversation", ""),
                "analysis_features": item.get("analysis_features", {}),
                "agent_type": item.get("agent_type", req.agent_type),
                "review": review,
                "human_decision": None,  # 等待人工审核
            }
            results.append(output_item)
            f.write(json.dumps(output_item, ensure_ascii=False) + "\n")
            time.sleep(5.0)

    pipeline_state["phases"][3]["detail"] = (
        f"完成: 通过={passed} 不通过={failed}"
    )

    # 加载到审核缓存
    _load_review_cache(req.agent_type)
    _mirror_to_user_workspace()


# ══════════════════════════════════════════════════════════════
# 3. REVIEW — 人工审核
# ══════════════════════════════════════════════════════════════

def _load_review_cache(agent_type: str = "neutral"):
    """加载审核数据到缓存"""
    global review_cache
    path = REVIEW_DIR / f"ai_review_{agent_type}.jsonl"
    if path.exists():
        items = _load_jsonl(path)
        for item in items:
            item_id = item.get("id", str(uuid.uuid4()))
            item["id"] = item_id
            review_cache[item_id] = item


@app.get("/api/review/items")
async def get_review_items(
    agent_type: str = "neutral",
    filter: str = "all",  # all | pending | passed | failed
):
    """获取审核条目列表"""
    # 确保缓存已加载
    if not review_cache:
        _load_review_cache(agent_type)

    items = list(review_cache.values())

    # 过滤
    if filter == "pending":
        items = [i for i in items if i.get("human_decision") is None]
    elif filter == "passed":
        items = [
            i for i in items
            if i.get("review", {}).get("passed") or i.get("human_decision") == "approve"
        ]
    elif filter == "failed":
        items = [
            i for i in items
            if not i.get("review", {}).get("passed") and i.get("human_decision") != "approve"
        ]

    # 返回摘要列表
    summary = []
    for item in items:
        review = item.get("review", {})
        summary.append({
            "id": item.get("id"),
            "chunk_id": item.get("chunk_id"),
            "agent_type": item.get("agent_type"),
            "ai_passed": review.get("passed", False),
            "ai_score": review.get("total_score", 0),
            "ai_summary": review.get("summary", ""),
            "human_decision": item.get("human_decision"),
            "conversation_preview": (item.get("conversation", "") or "")[:200],
        })

    return {
        "total": len(summary),
        "items": summary,
        "stats": {
            "total": len(review_cache),
            "ai_passed": sum(1 for i in review_cache.values() if i.get("review", {}).get("passed")),
            "ai_failed": sum(1 for i in review_cache.values() if not i.get("review", {}).get("passed")),
            "human_approved": sum(1 for i in review_cache.values() if i.get("human_decision") == "approve"),
            "human_rejected": sum(1 for i in review_cache.values() if i.get("human_decision") == "reject"),
            "pending": sum(1 for i in review_cache.values() if i.get("human_decision") is None),
        },
    }


@app.get("/api/review/items/{item_id}")
async def get_review_item(item_id: str):
    """获取单条审核详情"""
    if item_id not in review_cache:
        raise HTTPException(status_code=404, detail="审核条目不存在")
    return review_cache[item_id]


@app.post("/api/review/items/{item_id}")
async def submit_review_decision(item_id: str, decision: ReviewDecision):
    """提交人工审核决定"""
    if item_id not in review_cache:
        raise HTTPException(status_code=404, detail="审核条目不存在")

    item = review_cache[item_id]
    item["human_decision"] = decision.decision
    item["human_notes"] = decision.notes
    if decision.edited_analysis:
        try:
            item["edited_analysis"] = json.loads(decision.edited_analysis)
        except json.JSONDecodeError:
            item["edited_analysis"] = decision.edited_analysis

    # 持久化
    _save_review_cache(item.get("agent_type", "neutral"))

    return {"message": "审核结果已保存", "item_id": item_id, "decision": decision.decision}


def _save_review_cache(agent_type: str):
    """将审核缓存持久化"""
    path = REVIEW_DIR / f"ai_review_{agent_type}.jsonl"
    items = [
        item for item in review_cache.values()
        if item.get("agent_type") == agent_type
    ]
    with open(path, "w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


# ══════════════════════════════════════════════════════════════
# 4. DATA — 数据统计
# ══════════════════════════════════════════════════════════════

@app.get("/api/data/stats")
async def get_data_stats():
    """获取数据统计"""
    # 检查用户工作空间和项目工作空间的数据
    l1_path = USER_WORKSPACE / "timeline_out" / "agent_sft_l1.jsonl"
    l2_path = USER_WORKSPACE / "timeline_out" / "agent_sft_l2.jsonl"
    test_path = USER_WORKSPACE / "timeline_out" / "agent_sft_test.jsonl"

    if not l1_path.exists():
        l1_path = WORKSPACE / "timeline_out" / "agent_sft_l1.jsonl"
    if not l2_path.exists():
        l2_path = WORKSPACE / "timeline_out" / "agent_sft_l2.jsonl"
    if not test_path.exists():
        test_path = WORKSPACE / "timeline_out" / "agent_sft_test.jsonl"

    chunks_path = CHUNKS_DIR / "conversation_chunks.jsonl"

    return {
        "l1_lines": _count_jsonl_lines(l1_path),
        "l2_lines": _count_jsonl_lines(l2_path),
        "test_lines": _count_jsonl_lines(test_path),
        "chunks": _count_jsonl_lines(chunks_path),
        "analyses": {
            "neutral": _count_jsonl_lines(ANALYSIS_DIR / "raw_analysis_neutral.jsonl"),
            "supportive": _count_jsonl_lines(ANALYSIS_DIR / "raw_analysis_supportive.jsonl"),
            "psychoanalytic": _count_jsonl_lines(ANALYSIS_DIR / "raw_analysis_psychoanalytic.jsonl"),
        },
        "reviews": {
            "neutral": _count_jsonl_lines(REVIEW_DIR / "ai_review_neutral.jsonl"),
            "supportive": _count_jsonl_lines(REVIEW_DIR / "ai_review_supportive.jsonl"),
            "psychoanalytic": _count_jsonl_lines(REVIEW_DIR / "ai_review_psychoanalytic.jsonl"),
        },
    }


# ══════════════════════════════════════════════════════════════
# 5. MODELS — 模型后端信息
# ══════════════════════════════════════════════════════════════

@app.get("/api/models")
async def get_models():
    """获取所有模型后端的状态"""
    env_prefix_map = AnalysisGenerator._ENV_PREFIX
    models_info = []

    default_models = {
        "openai": "GLM-4.7",
        "DeepSeek": "DeepSeek-V3.2",
        "Kimi": "Kimi-K2.5",
        "kimi": "kimi-k2.5",
        "Qwen": "Qwen3",
        "deepseek": "deepseek-ai/DeepSeek-V3.1",
        "qwen_local": "Qwen3-8B-Instruct",
        "qwen_cloud": "Qwen/Qwen3-235B-A22B-Thinking-2507",
        "glm": "z-ai/glm4.7",
    }

    for backend, prefix in env_prefix_map.items():
        api_key = os.environ.get(f"{prefix}_API_KEY", "")
        base_url = os.environ.get(f"{prefix}_BASE_URL", "")
        model = os.environ.get(f"{prefix}_MODEL", "") or default_models.get(backend, "")

        has_key = bool(api_key and api_key != "not-needed")
        if backend == "qwen_local":
            has_key = True  # 本地不需要 key

        status = "offline"
        if has_key and base_url:
            status = "connected"
        elif has_key:
            status = "configured"

        models_info.append({
            "backend": backend,
            "model": model,
            "base_url": base_url or "(默认)",
            "status": status,
            "has_key": has_key,
        })

    return models_info


# ══════════════════════════════════════════════════════════════
# 6. MODEL PREFERENCES — 模型偏好
# ══════════════════════════════════════════════════════════════

PREFS_PATH = ADVISOR_OUT / "model_preferences.json"


def _load_prefs() -> dict:
    if PREFS_PATH.exists():
        with open(PREFS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return ModelPreferences().model_dump()


def _save_prefs(prefs: dict):
    PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(PREFS_PATH, "w", encoding="utf-8") as f:
        json.dump(prefs, f, ensure_ascii=False, indent=2)


@app.get("/api/models/preferences")
async def get_model_preferences():
    """获取模型偏好设置"""
    return _load_prefs()


@app.post("/api/models/preferences")
async def set_model_preferences(prefs: ModelPreferences):
    """保存模型偏好设置"""
    data = prefs.model_dump()
    _save_prefs(data)
    return {"message": "模型偏好已保存", "preferences": data}


@app.get("/api/models/available")
async def get_available_models():
    """获取所有可用模型（按用途分组）"""
    env_prefix_map = AnalysisGenerator._ENV_PREFIX
    available = []

    default_models = {
        "openai": "GLM-4.7",
        "DeepSeek": "DeepSeek-V3.2",
        "Kimi": "Kimi-K2.5",
        "kimi": "kimi-k2.5",
        "Qwen": "Qwen3",
        "deepseek": "deepseek-ai/DeepSeek-V3.1",
        "qwen_local": "Qwen3-8B-Instruct",
        "qwen_cloud": "Qwen/Qwen3-235B-A22B-Thinking-2507",
        "glm": "z-ai/glm4.7",
    }

    for backend, prefix in env_prefix_map.items():
        api_key = os.environ.get(f"{prefix}_API_KEY", "")
        base_url = os.environ.get(f"{prefix}_BASE_URL", "")
        model = os.environ.get(f"{prefix}_MODEL", "") or default_models.get(backend, "")
        has_key = bool(api_key and api_key != "not-needed")
        if backend == "qwen_local":
            has_key = True

        if has_key:
            available.append({
                "backend": backend,
                "model": model,
                "base_url": base_url or "(默认)",
                "suitable_for": _get_suitable_roles(backend),
            })

    return available


def _get_suitable_roles(backend: str) -> list[str]:
    """Returns which roles a backend is suitable for"""
    roles_map = {
        "openai": ["analysis", "review", "chat"],
        "DeepSeek": ["analysis", "review", "chat"],
        "Kimi": ["analysis", "review", "chat"],
        "kimi": ["analysis", "chat"],
        "Qwen": ["analysis", "review", "chat"],
        "deepseek": ["analysis", "review", "chat"],
        "qwen_local": ["chat"],
        "qwen_cloud": ["analysis", "review", "chat"],
        "glm": ["analysis", "chat"],
    }
    return roles_map.get(backend, ["chat"])


# ══════════════════════════════════════════════════════════════
# 8. RAG — ChunkAwareRAG 增强检索 API
# ══════════════════════════════════════════════════════════════

class RAGSearchRequest(BaseModel):
    query: str = ""
    day: Optional[int] = None
    day_range: Optional[str] = None  # "100-120"
    chunk_type: Optional[str] = None  # conflict/sweet/normal
    top_k: int = 5


@app.post("/api/rag/search")
async def rag_search(req: RAGSearchRequest):
    """
    RAG 增强检索（无 GPU，使用预构建 enriched_metadata）

    支持:
    - 精确日期: day=109
    - 日期范围: day_range="100-120"
    - 关键词语义: query="我们为什么吵架"
    - 类型过滤: chunk_type="conflict"
    """
    results = []

    # 日期检索
    if req.day is not None:
        indices = _enriched_day_index.get(req.day, [])
        for idx in indices:
            if idx < len(_rag_conversations) and idx < len(_enriched_chunks):
                results.append(_build_rag_result(idx))

    # 日期范围
    elif req.day_range:
        try:
            s, e = req.day_range.split('-')
            start_day, end_day = int(s), int(e)
            seen = set()
            for d in range(start_day, end_day + 1):
                for idx in _enriched_day_index.get(d, []):
                    if idx not in seen and idx < len(_rag_conversations):
                        results.append(_build_rag_result(idx))
                        seen.add(idx)
        except (ValueError, IndexError):
            raise HTTPException(400, "day_range 格式错误，应为 '100-120'")

    # 关键词检索
    elif req.query:
        search_query = req.query
        for real_name, role in _name_mapping.items():
            search_query = search_query.replace(real_name, role)
        hits = _enriched_search(search_query, top_k=req.top_k)
        if not hits:
            hits = _enriched_search(req.query, top_k=req.top_k)
        for h in hits:
            conv = h['conv']
            echunk = h.get('enriched', {})
            idx = _chunk_id_to_idx.get(conv.get('conversation_id', ''))
            if idx is not None:
                results.append(_build_rag_result(idx, score=h['score']))
            else:
                results.append({
                    'chunk_id': conv.get('conversation_id', ''),
                    'conversation_preview': conv.get('conversation_text', '')[:500],
                    'score': h['score'],
                })

    # 类型过滤
    if req.chunk_type:
        results = [r for r in results if r.get('chunk_type') == req.chunk_type]

    return {
        'results': results[:req.top_k],
        'total': len(results),
        'enriched_available': bool(_enriched_chunks),
        'max_day': _enriched_max_day,
        'total_chunks': len(_rag_conversations),
    }


@app.get("/api/rag/day/{day_num}")
async def rag_day(day_num: int):
    """精确日期检索: 返回指定天的所有 chunks 及分析"""
    indices = _enriched_day_index.get(day_num, [])
    results = []
    for idx in indices:
        if idx < len(_rag_conversations) and idx < len(_enriched_chunks):
            results.append(_build_rag_result(idx))
    return {
        'day': day_num,
        'chunks': results,
        'count': len(results),
    }


@app.get("/api/rag/chunk/{chunk_id}")
async def rag_chunk_detail(chunk_id: str):
    """获取单个 chunk 的完整信息（对话 + 分析 + 跨天关联）"""
    idx = _chunk_id_to_idx.get(chunk_id)
    if idx is None:
        raise HTTPException(404, f"chunk {chunk_id} 不存在")

    result = _build_rag_result(idx, full_text=True)

    # 跨天关联
    echunk = _enriched_chunks[idx]
    associations = []
    days = set(echunk.get('days', []))
    analysis = echunk.get('analysis', {})

    # 策略1: time_patterns 引用
    if analysis.get('time_patterns'):
        import re
        dp = re.compile(r'第(\d+)天')
        ref_days = set()
        for pat in analysis['time_patterns']:
            ref_days.update(int(d) for d in dp.findall(pat))
        for d in ref_days - days:
            for nidx in _enriched_day_index.get(d, []):
                if nidx != idx and nidx < len(_enriched_chunks):
                    nc = _enriched_chunks[nidx]
                    associations.append({
                        'chunk_id': nc['chunk_id'],
                        'reason': f'time_patterns 引用第{d}天',
                        'days': nc.get('days', []),
                        'chunk_type': nc.get('chunk_type', ''),
                    })

    # 策略2: 相邻天 + 类型变化
    for day in days:
        for offset in [-1, 1]:
            nbr = day + offset
            for nidx in _enriched_day_index.get(nbr, []):
                if nidx != idx and nidx < len(_enriched_chunks):
                    nc = _enriched_chunks[nidx]
                    if nc.get('chunk_type') != echunk.get('chunk_type'):
                        associations.append({
                            'chunk_id': nc['chunk_id'],
                            'reason': f'第{day}→第{nbr}天 {echunk.get("chunk_type")}→{nc.get("chunk_type")}',
                            'days': nc.get('days', []),
                            'chunk_type': nc.get('chunk_type', ''),
                        })

    result['associations'] = associations[:5]
    return result


@app.get("/api/rag/stats")
async def rag_stats():
    """RAG 索引统计"""
    type_dist = {}
    status_dist = {}
    risk_dist = {}
    for ec in _enriched_chunks:
        ct = ec.get('chunk_type', 'unknown')
        type_dist[ct] = type_dist.get(ct, 0) + 1
        a = ec.get('analysis', {})
        if a:
            st = a.get('relationship_status', '未知')
            if not isinstance(st, str):
                st = st.get('level', str(st)) if isinstance(st, dict) else str(st)
            status_dist[st] = status_dist.get(st, 0) + 1
            rl = a.get('risk_level', '未知')
            if not isinstance(rl, str):
                rl = rl.get('level', str(rl)) if isinstance(rl, dict) else str(rl)
            risk_dist[rl] = risk_dist.get(rl, 0) + 1

    return {
        'total_chunks': len(_rag_conversations),
        'enriched_chunks': len(_enriched_chunks),
        'total_days': len(_enriched_day_index),
        'day_range': [min(_enriched_day_index.keys(), default=0),
                      _enriched_max_day] if _enriched_day_index else [0, 0],
        'type_distribution': type_dist,
        'status_distribution': status_dist,
        'risk_distribution': risk_dist,
        'user_profile': _rag_user_profile,
    }


def _build_rag_result(idx: int, score: float = 0.0, full_text: bool = False) -> dict:
    """构建单条 RAG 检索结果"""
    conv = _rag_conversations[idx] if idx < len(_rag_conversations) else {}
    echunk = _enriched_chunks[idx] if idx < len(_enriched_chunks) else {}
    text = conv.get('conversation_text', '')

    result = {
        'chunk_id': echunk.get('chunk_id', conv.get('conversation_id', '')),
        'chunk_type': echunk.get('chunk_type', ''),
        'days': echunk.get('days', []),
        'message_count': echunk.get('message_count', 0),
        'conversation_preview': text if full_text else (text[:500] + ('...' if len(text) > 500 else '')),
        'score': score,
        'analysis_summary': _fmt_enriched_summary(echunk),
    }
    a = echunk.get('analysis', {})
    if a:
        result['analysis'] = {
            'relationship_status': a.get('relationship_status', ''),
            'communication_quality': a.get('communication_quality', ''),
            'risk_level': a.get('risk_level', ''),
            'key_issues': a.get('key_issues', []),
            'conflict_root_causes': a.get('conflict_root_causes', []),
            'overall_assessment': a.get('overall_assessment', ''),
            'time_patterns': a.get('time_patterns', []),
        }
    return result


# ══════════════════════════════════════════════════════════════
# API Key Checker — 集成自 api-key-checker 独立工具
# ══════════════════════════════════════════════════════════════

_key_checker_rate_limits: dict[str, float] = {}
_KEY_CHECKER_RATE_LIMIT_S = 5.0
_active_checks: dict[str, list] = {}


class KeyCheckerFetchRequest(BaseModel):
    base_url: str
    api_key: str


class KeyCheckerCheckRequest(BaseModel):
    base_url: str
    api_key: str
    model: str
    detection_id: str = ""


class KeyCheckerStopRequest(BaseModel):
    detection_id: str


class KeyCheckerBatchRequest(BaseModel):
    base_url: str
    api_key: str
    models: list[str]
    detection_id: str = ""


@app.post("/api/keys/fetch-models")
async def key_checker_fetch_models(req: KeyCheckerFetchRequest):
    """获取指定 API 端点的可用模型列表"""
    base = req.base_url.rstrip("/")
    url = f"{base}/v1/models" if "/v1" not in base else f"{base}/models"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            start = time.time()
            resp = await client.get(
                url, headers={"Authorization": f"Bearer {req.api_key}"}
            )
            duration = int((time.time() - start) * 1000)
            data = resp.json()
            raw = data.get("data", data) if isinstance(data, dict) else data
            models = []
            if isinstance(raw, list):
                for m in raw:
                    if isinstance(m, str):
                        models.append({"id": m})
                    elif isinstance(m, dict) and m.get("id"):
                        models.append({"id": m["id"]})
            return {"success": True, "models": models, "duration": duration}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/api/keys/check")
async def key_checker_check(req: KeyCheckerCheckRequest):
    """测试单个模型的连通性"""
    # Rate limit per key
    now = time.time()
    last = _key_checker_rate_limits.get(req.api_key, 0)
    if now - last < _KEY_CHECKER_RATE_LIMIT_S:
        return {"success": False, "error": f"限速中，请等待 {_KEY_CHECKER_RATE_LIMIT_S}s"}
    _key_checker_rate_limits[req.api_key] = now

    base = req.base_url.rstrip("/")
    url = f"{base}/v1/chat/completions" if "/v1" not in base else f"{base}/chat/completions"
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            start = time.time()
            resp = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {req.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": req.model,
                    "messages": [{"role": "user", "content": "Hi"}],
                    "max_tokens": 1,
                    "temperature": 0,
                    "stream": False,
                },
            )
            latency = int((time.time() - start) * 1000)
            data = resp.json()
            if resp.status_code == 200:
                return {
                    "success": True,
                    "latency": latency,
                    "model": data.get("model", req.model),
                    "usage": data.get("usage"),
                }
            else:
                err = data.get("error", {})
                return {
                    "success": False,
                    "error": err.get("message", str(data)[:300]),
                    "status": resp.status_code,
                    "details": data,
                }
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/api/keys/batch-check")
async def key_checker_batch_check(req: KeyCheckerBatchRequest):
    """批量检测多个模型（带 5s 间隔限速）"""
    results = {}
    detection_id = req.detection_id or f"{int(time.time())}"
    _active_checks[detection_id] = [True]  # alive flag

    for i, model in enumerate(req.models):
        # Check if stopped
        if detection_id not in _active_checks or not _active_checks[detection_id][0]:
            break

        single = KeyCheckerCheckRequest(
            base_url=req.base_url,
            api_key=req.api_key,
            model=model,
            detection_id=detection_id,
        )
        # Reset rate limit for batch (we handle interval ourselves)
        _key_checker_rate_limits.pop(req.api_key, None)
        result = await key_checker_check(single)
        results[model] = result

        # Wait between requests (except last)
        if i < len(req.models) - 1:
            await asyncio.sleep(_KEY_CHECKER_RATE_LIMIT_S)

    _active_checks.pop(detection_id, None)
    return {"results": results, "tested": len(results), "total": len(req.models)}


@app.post("/api/keys/stop")
async def key_checker_stop(req: KeyCheckerStopRequest):
    """终止正在进行的批量检测"""
    if req.detection_id in _active_checks:
        _active_checks[req.detection_id][0] = False
        return {"success": True, "message": "已请求终止"}
    return {"success": False, "error": "未找到该检测任务"}


# ══════════════════════════════════════════════════════════════
# Health check
# ══════════════════════════════════════════════════════════════

@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "2.2"}
