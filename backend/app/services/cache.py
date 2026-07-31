"""数据缓存层：SQLite StockCache 表的读写（从 data_fetcher.py 拆出）。

每个 cache_type 只保留最新一条记录；支持“有效缓存”和“过期缓存兜底”两种读取。
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import delete, select

from app.database import StockCache, async_session

logger = logging.getLogger(__name__)


async def get_cache(cache_type: str) -> Optional[list]:
    """读取有效缓存（未过期）。"""
    return await _get_cache_impl(cache_type, check_expiry=True)


async def get_cache_stale(cache_type: str) -> Optional[list]:
    """读取任意缓存（即使已过期）。"""
    return await _get_cache_impl(cache_type, check_expiry=False)


async def _get_cache_impl(cache_type: str, check_expiry: bool) -> Optional[list]:
    async with async_session() as session:
        stmt = (
            select(StockCache)
            .where(StockCache.cache_type == cache_type)
            .order_by(StockCache.id.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        cache = result.scalar_one_or_none()
        if cache and (not check_expiry or cache.expires_at > datetime.now()):
            return json.loads(cache.data_json)
        return None


async def set_cache(cache_type: str, data: Any, ttl_seconds: int):
    """写入缓存（先清旧记录，同一类型只保留最新一条）。"""
    async with async_session() as session:
        await session.execute(
            delete(StockCache).where(StockCache.cache_type == cache_type)
        )
        expires_at = datetime.now() + timedelta(seconds=ttl_seconds)
        cache = StockCache(
            cache_type=cache_type,
            data_json=json.dumps(data, ensure_ascii=False, default=str),
            expires_at=expires_at,
        )
        session.add(cache)
        await session.commit()
