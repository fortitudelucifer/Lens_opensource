"""services/generator_service.py — 模型路由器 + Ollama 生命周期

从 server.py 迁移（Step 1）：
  - `_ensure_ollama_running` → `ensure_ollama_running`
  - `_stop_ollama`           → `stop_ollama`
  - `_start_ollama_watchdog` → `start_ollama_watchdog`
  - `_get_available_chat_backends` → `get_available_chat_backends`
  - `_get_generator`         → `get_generator`
  - `_OLLAMA_IDLE_TIMEOUT`   → `OLLAMA_IDLE_TIMEOUT`

依赖：core/state.py（state.ollama_proc / state.ollama_lock / state.ollama_last_use）
"""
from __future__ import annotations

import os
import subprocess
import threading
import time
from typing import Optional

import httpx

from scripts.advisor.generator import AnalysisGenerator
from ..core import state

# 5 分钟无输入则 kill Ollama 进程
OLLAMA_IDLE_TIMEOUT = 300


def ensure_ollama_running() -> bool:
    """确保 Ollama 服务运行中。如果未启动则自动启动，返回是否成功。"""
    state.ollama_last_use = time.time()

    # 检查是否已运行
    try:
        r = httpx.get("http://localhost:11434/api/tags", timeout=2)
        if r.status_code == 200:
            return True
    except Exception:
        pass

    # 启动 Ollama
    with state.ollama_lock:
        # 双重检查
        try:
            r = httpx.get("http://localhost:11434/api/tags", timeout=2)
            if r.status_code == 200:
                return True
        except Exception:
            pass

        print("[🚀 Ollama] 自动启动 Ollama 服务...")
        try:
            state.ollama_proc = subprocess.Popen(
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
                        start_ollama_watchdog()
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


def stop_ollama():
    """kill Ollama 进程"""
    if state.ollama_proc and state.ollama_proc.poll() is None:
        print("[🛑 Ollama] 空闲超时，关闭服务")
        state.ollama_proc.terminate()
        try:
            state.ollama_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            state.ollama_proc.kill()
        state.ollama_proc = None


def start_ollama_watchdog():
    """启动后台线程，空闲超时后自动 kill Ollama"""
    def _watchdog():
        while True:
            time.sleep(60)
            if time.time() - state.ollama_last_use > OLLAMA_IDLE_TIMEOUT:
                stop_ollama()
                break
            if state.ollama_proc is None or state.ollama_proc.poll() is not None:
                break
    t = threading.Thread(target=_watchdog, daemon=True)
    t.start()


def get_available_chat_backends(exclude: str = "") -> list[str]:
    """快速返回已配置 key 的 chat 后端列表（不做实际连通测试）"""
    env_prefix_map = AnalysisGenerator._ENV_PREFIX
    chat_capable = {"claude", "gemini", "kimi", "grok", "deepseek", "qwen_cloud", "qwen_local", "glm"}
    available = []
    for backend, prefix in env_prefix_map.items():
        if backend == exclude or backend not in chat_capable:
            continue
        api_key = os.environ.get(f"{prefix}_API_KEY", "")
        if backend == "qwen_local" or (api_key and api_key != "not-needed"):
            available.append(backend)
    return available


def get_generator(backend: str = "claude", model: Optional[str] = None,
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
