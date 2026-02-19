#!/usr/bin/env python3
"""
API Key 轮换器与全局限流模块

功能：
- GlobalRateLimiter: 全局 RPM（每分钟请求数）限流器，确保不超过账户总限制
- KeyRotator: 多 API Key 轮换管理，支持故障自动切换和紧急备用 Key
- 线程安全设计，支持多线程并发调用

处理流程：
1. KeyRotator.acquire(): 从可用 Key 池中获取下一个 Key
2. GlobalRateLimiter.wait_if_needed(): 检查 RPM 限制，必要时等待冷却
3. 调用 API 后标记成功/失败（mark_success/mark_failed）
4. 失败的 Key 自动进入冷却期，冷却结束后重新加入可用池
5. 所有常规 Key 不可用时自动切换到紧急备用 Key

约束条件：
- 第三方代理 代理商约束: 所有 Key 合计 RPM ≤ 20（账户总限制）
- 单个 Key 连续失败 3 次后进入 60 秒冷却期

输入：
- API Key 列表（常规 + 紧急备用）
- RPM 限制参数

输出：
- 可用的 API Key（自动等待限流冷却）

依赖：
- threading: 线程安全锁

使用示例：
    from scripts.advisor.key_rotator import GlobalRateLimiter, KeyRotator
    
    limiter = GlobalRateLimiter(max_rpm=20)
    rotator = KeyRotator(
        keys=["sk-abc", "sk-def", "sk-ghi"],
        emergency_keys=["sk-emg1"],
        global_limiter=limiter,
    )
    key = rotator.acquire()    # 获取下一个可用 Key（自动等待 RPM 冷却）
    try:
        result = call_api(key)
        rotator.mark_success(key)
    except Exception:
        rotator.mark_failed(key)

注意事项：
- acquire() 可能阻塞等待 RPM 冷却，最长等待时间约 60 秒
- 紧急备用 Key 仅在所有常规 Key 不可用时使用
- 线程安全，可在多线程环境中安全使用

作者：forcifer
更新于：2026-02-15
"""

import threading
import time
import logging
from typing import Optional
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


class GlobalRateLimiter:
    """全局 RPM 限制器 — 第三方代理 账户总限制 (所有 key/model 合计)"""

    def __init__(self, max_rpm: int = 19):
        self.max_rpm = max_rpm
        self._timestamps: list[float] = []
        self._lock = threading.Lock()

    def record_call(self):
        """记录一次 API 调用"""
        with self._lock:
            self._timestamps.append(time.time())

    def wait_if_needed(self):
        """如果 60s 内调用次数 >= max_rpm，sleep 到窗口过期"""
        while True:
            now = time.time()
            with self._lock:
                self._timestamps = [t for t in self._timestamps if t > now - 60.0]
                count = len(self._timestamps)

            if count < self.max_rpm:
                return

            oldest = self._timestamps[0]
            wait = oldest + 60.0 - now + 0.1
            if wait > 0:
                logger.info(
                    f"[GlobalRPM] {count}/{self.max_rpm} RPM, 等待 {wait:.1f}s"
                )
                time.sleep(wait)

    def current_rpm(self) -> int:
        """返回当前 60s 窗口内的调用次数"""
        now = time.time()
        with self._lock:
            return sum(1 for t in self._timestamps if t > now - 60.0)


class KeyRotator:
    """线程安全 API key 轮换器 — 全局 RPM 硬限制 + 故障切换 + emergency 降级"""

    MAX_FAIL_BEFORE_BLACKLIST = 3  # 连续失败 N 次进入黑名单

    def __init__(
        self,
        keys: list[str],
        emergency_keys: list[str] | None = None,
        global_limiter: GlobalRateLimiter | None = None,
        name: str = "default",
    ):
        if not keys:
            raise ValueError(f"[KeyRotator:{name}] 至少需要 1 个 key")

        self.name = name
        self.keys = list(keys)
        self.emergency = list(emergency_keys or [])
        self.global_limiter = global_limiter

        self._idx = 0
        self._lock = threading.Lock()
        self._blacklist: set[str] = set()
        self._fail_counts: dict[str, int] = {}
        self._emergency_active = False

        logger.info(
            f"[KeyRotator:{name}] 初始化: {len(self.keys)} keys + {len(self.emergency)} emergency"
        )

    def acquire(self) -> str:
        """
        获取下一个可用 key。

        - 跳过黑名单中的 key
        - 如果所有普通 key 黑名单，切换到 emergency
        - 自动等待全局 RPM 冷却（60s 滑动窗口）

        Returns:
            可用的 API key

        Raises:
            RuntimeError: 所有 key（含 emergency）均不可用
        """
        # 全局 RPM 等待在锁外执行（避免长时间持锁）
        if self.global_limiter:
            self.global_limiter.wait_if_needed()
        with self._lock:
            key = self._select_next_key()
        return key

    def mark_success(self, key: str):
        """标记调用成功，记录全局时间戳，清除失败计数"""
        with self._lock:
            self._fail_counts[key] = 0
        if self.global_limiter:
            self.global_limiter.record_call()

    def mark_failed(self, key: str):
        """
        标记调用失败。连续失败 >= MAX_FAIL_BEFORE_BLACKLIST 次进入黑名单。
        """
        with self._lock:
            self._fail_counts[key] = self._fail_counts.get(key, 0) + 1
            count = self._fail_counts[key]
            if count >= self.MAX_FAIL_BEFORE_BLACKLIST:
                self._blacklist.add(key)
                logger.warning(
                    f"[KeyRotator:{self.name}] key ...{key[-6:]} 连续失败 {count} 次，加入黑名单 "
                    f"(黑名单: {len(self._blacklist)}/{len(self.keys)})"
                )
                # 检查是否需要启用 emergency
                active_keys = [k for k in self.keys if k not in self._blacklist]
                if not active_keys and self.emergency and not self._emergency_active:
                    self._emergency_active = True
                    logger.warning(
                        f"[KeyRotator:{self.name}] ⚠️ 所有普通 key 黑名单！启用 {len(self.emergency)} 个 emergency key"
                    )

    def get_stats(self) -> dict:
        """返回当前状态统计"""
        with self._lock:
            active = [k for k in self.keys if k not in self._blacklist]
            return {
                "name": self.name,
                "total_keys": len(self.keys),
                "active_keys": len(active),
                "blacklisted": len(self._blacklist),
                "emergency_active": self._emergency_active,
                "emergency_count": len(self.emergency),
            }

    # ── 内部方法 ──────────────────────────────────────────────

    def _select_next_key(self) -> str:
        """选择下一个可用 key（round-robin，跳过黑名单）。需在锁内调用。"""
        pool = self.keys if not self._emergency_active else self.emergency
        blacklist = self._blacklist

        for _ in range(len(pool)):
            key = pool[self._idx % len(pool)]
            self._idx += 1
            if key not in blacklist:
                return key

        # 所有 pool 中的 key 都被黑名单了
        if not self._emergency_active and self.emergency:
            self._emergency_active = True
            logger.warning(f"[KeyRotator:{self.name}] 切换到 emergency pool")
            self._idx = 0
            return self.emergency[0]

        raise RuntimeError(
            f"[KeyRotator:{self.name}] 所有 key（含 emergency）均不可用！"
            f" 黑名单: {len(blacklist)}"
        )



def load_key_pool(yaml_path: str | Path) -> dict:
    """
    加载 key_pool.yaml，返回结构:
    {
        "DeepSeek": {"keys": [...], "base_url": ..., "model": ..., ...},
        "GLM": {...},
        ...
        "emergency": {"keys": [...], ...},
    }
    """
    path = Path(yaml_path)
    if not path.exists():
        raise FileNotFoundError(f"Key pool 配置不存在: {path}")

    with open(path, 'r', encoding='utf-8') as f:
        pool = yaml.safe_load(f)

    if not isinstance(pool, dict):
        raise ValueError(f"Key pool 格式错误: 期望 dict, 得到 {type(pool)}")

    # 验证每个 agent 至少有 1 个 key
    for agent, config in pool.items():
        if agent == 'emergency':
            continue
        keys = config.get('keys', [])
        if not keys:
            logger.warning(f"[key_pool] agent '{agent}' 没有配置 key")

    return pool


def create_rotators_from_pool(
    pool: dict, max_rpm: int = 19
) -> tuple[dict[str, KeyRotator], GlobalRateLimiter]:
    """
    从 key_pool 配置创建每个 agent 的 KeyRotator + 全局限速器。

    第三方代理 账户总 RPM ≤ max_rpm，所有 agent 共享。

    Returns:
        ({"DeepSeek": KeyRotator, "GLM": KeyRotator, ...}, GlobalRateLimiter)
    """
    emergency_keys = pool.get("emergency", {}).get("keys", [])
    global_limiter = GlobalRateLimiter(max_rpm=max_rpm)
    rotators = {}

    for agent, config in pool.items():
        if agent == "emergency":
            continue
        keys = config.get("keys", [])
        if keys:
            rotators[agent] = KeyRotator(
                keys=keys,
                emergency_keys=emergency_keys,
                global_limiter=global_limiter,
                name=agent,
            )

    logger.info(f"[key_pool] 创建 {len(rotators)} 个 rotator, 全局 RPM≤{max_rpm}")
    return rotators, global_limiter
