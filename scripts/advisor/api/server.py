"""scripts/advisor/api/server.py — 兼容性入口（Phase 3 Step 11）

旧启动命令 `uvicorn scripts.advisor.api.server:app` 仍然可用。
真正的 FastAPI app 组装逻辑已迁移到 `scripts.advisor.api.main`。

推荐使用新入口：
    conda run -n wechatDHA uvicorn scripts.advisor.api.main:app --port 8787
"""
from scripts.advisor.api.main import app  # noqa: F401

__all__ = ["app"]
