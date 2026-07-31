"""速率限制 + 指数退避重试工具（从 data_fetcher.py 拆出）。

设计要点：
  1. 全局限速：所有 endpoint 共享等待窗口，间隔 = 基础值 + 随机抖动
  2. 全抖动指数退避：每次重试在 [0, cap] 区间均匀采样
  3. 阻塞的 akshare 调用在线程池中运行，带超时保护
"""

import asyncio
import logging
import random
import time
from typing import Any, Callable

from app.config import settings

logger = logging.getLogger(__name__)

# 全局速率限制器（每个 endpoint 独立追踪）
_last_call_times: dict[str, float] = {}
_lock = asyncio.Lock()


def rate_limit_wait(last_call_times: dict[str, float], now: float, min_interval: float) -> float:
    """计算距下一次安全调用还需等待的秒数（纯函数，便于测试）。

    所有 endpoint 全局协调：任何一个 endpoint 的最近调用都会推迟其他 endpoint。
    """
    wait = 0.0
    for last in last_call_times.values():
        needed = min_interval - (now - last)
        if needed > wait:
            wait = needed
    return max(wait, 0.0)


async def rate_limit(endpoint: str = "default"):
    """等待直到可以安全调用。间隔 ≥基础值 + 随机抖动（默认 3~6s）防检测。"""
    async with _lock:
        now = time.monotonic()
        min_interval = settings.akshare_interval + random.uniform(
            0, settings.akshare_interval_jitter
        )
        wait = rate_limit_wait(_last_call_times, now, min_interval)
        if wait > 0:
            logger.debug(f"速率限制：等待 {wait:.1f}s (endpoint={endpoint})")
            await asyncio.sleep(wait)
        _last_call_times[endpoint] = time.monotonic()


def backoff_cap(attempt: int, base_delay: float, max_delay: float) -> float:
    """第 attempt 次重试的退避上限（纯函数，便于测试）。"""
    return min(max_delay, base_delay * (2 ** (attempt - 1)))


async def async_retry(fn: Callable, *args, **kwargs):
    """指数退避 + 全抖动重试包装器。

    退避序列：5s, 10s, 20s, 40s, 80s（上限 120s）。每次等待在 [0, cap]
    区间均匀采样（full jitter），避免重试风暴。
    """
    max_attempts = settings.retry_max_attempts  # 5
    base_delay = settings.retry_base_delay      # 5s
    max_delay = settings.retry_max_delay        # 120s
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return await fn(*args, **kwargs)
        except Exception as e:  # noqa: BLE001 - 重试语义需要捕获全部异常
            last_exc = e
            if attempt < max_attempts:
                cap = backoff_cap(attempt, base_delay, max_delay)
                sleep_sec = random.uniform(0, cap)
                logger.warning(
                    f"请求失败 (attempt {attempt}/{max_attempts}): {str(e)[:120]} "
                    f"— 等待 {sleep_sec:.1f}s 后重试"
                )
                await asyncio.sleep(sleep_sec)
    # 所有重试均失败
    raise last_exc  # type: ignore[misc]


async def run_akshare(func: Callable, *args, **kwargs):
    """在线程池 executor 中运行阻塞的 akshare 调用，带超时保护。"""
    loop = asyncio.get_running_loop()
    return await asyncio.wait_for(
        loop.run_in_executor(None, lambda: func(*args, **kwargs)),
        timeout=settings.akshare_timeout,  # 120s
    )


async def akshare_with_retry(endpoint: str, func: Callable, *args, **kwargs):
    """akshare 统一调用：速率限制 + 指数退避重试。"""
    async def _call():
        await rate_limit(endpoint)
        return await run_akshare(func, *args, **kwargs)
    return await async_retry(_call)
