"""前复权 K 线获取（akshare 东方财富源 → Sina 降级 + 内存缓存）。

从 data_fetcher.py 拆出，职责单一：K 线数据获取、MA 计算、JSON 安全清洗。
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Optional

import akshare as ak
import httpx
import pandas as pd

from app.config import settings
from app.services.numeric import clean_float, safe_float
from app.services.rate_limit import rate_limit, run_akshare

logger = logging.getLogger(__name__)

# 内存缓存：key "{code}_{months}",TTL 4h,上限 2 万条防长跑内存无限增长
_kline_cache: dict[str, tuple[float, list[dict]]] = {}
_KLINE_CACHE_TTL = 14400  # 4 小时
_KLINE_CACHE_MAX = 20000  # 5000 股 × 4 档周期 ≈ 2 万条


def trim_cache(cache: dict, max_size: int) -> dict:
    """超出上限时按插入顺序淘汰最旧条目（dict 保持插入序，近似 FIFO）。纯函数。"""
    while len(cache) > max_size:
        cache.pop(next(iter(cache)))
    return cache


async def fetch_kline_data(code: str, months: int = 12) -> Optional[list[dict]]:
    """获取个股前复权 K 线数据（含 MA5/MA20/MA60）。

    策略：内存缓存(4h) → akshare qfq → Sina K线 API → None
    """
    cache_key = f"{code}_{months}"

    # 1. 检查内存缓存
    now = time.monotonic()
    cached = _kline_cache.get(cache_key)
    if cached and (now - cached[0]) < _KLINE_CACHE_TTL:
        logger.debug(f"  {cache_key} K线缓存命中")
        return cached[1]

    code_z = code.zfill(6)
    end_date = datetime.now().strftime("%Y%m%d")
    start_dt = datetime.now() - timedelta(days=months * 31)
    start_date = start_dt.strftime("%Y%m%d")

    result = None

    # 2. 方案A: akshare 东方财富（前复权）
    async def _fetch_em():
        await rate_limit("kline")
        return await run_akshare(
            ak.stock_zh_a_hist,
            symbol=code_z,
            period="daily",
            start_date=start_date,
            end_date=end_date,
            adjust="qfq",
        )

    try:
        df = await _fetch_em()
        if df is not None and not df.empty:
            result = _build_kline(df, date_col="日期", open_col="开盘",
                                  high_col="最高", low_col="最低", close_col="收盘",
                                  volume_col="成交量")
    except Exception as e:
        logger.warning(f"  {code_z} 东方财富K线失败: {e}")

    # 3. 方案B: Sina K线 API（未复权，但稳定可用）
    if result is None:
        logger.info(f"  → 降级到 Sina K线: {code_z}")
        try:
            result = await _fetch_kline_sina(code_z, months)
        except Exception as e:
            logger.warning(f"  {code_z} Sina K线也失败: {e}")

    # 4. 写缓存（不管哪个源来的，都缓存 4h）
    if result is not None:
        trim_cache(_kline_cache, _KLINE_CACHE_MAX)
        _kline_cache[cache_key] = (time.monotonic(), result)

    return result


def symbol_sina(code: str) -> str:
    """A股代码转新浪symbol格式：sh600004 / sz000001"""
    if code.startswith("6") or code.startswith("9"):
        return f"sh{code}"
    return f"sz{code}"


async def _fetch_kline_sina(code: str, months: int) -> Optional[list[dict]]:
    """通过新浪日K线API获取数据（scale=240 = 日线）"""
    symbol = symbol_sina(code)
    # 最多取 1023 根日K（约4年）
    datalen = min(max(months * 20, 60), 1023)

    url = ("https://vip.stock.finance.sina.com.cn/quotes_service"
           "/api/json_v2.php/CN_MarketData.getKLineData")
    params = {"symbol": symbol, "scale": 240, "datalen": datalen}

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        raw = resp.json()

    if not isinstance(raw, list) or len(raw) == 0:
        return None

    # 解析并筛选时间范围
    cutoff = datetime.now() - timedelta(days=months * 31)

    rows = []
    for item in raw:
        row = parse_sina_kline_row(item, cutoff)
        if row is None:
            continue
        rows.append(row)

    # 按日期升序
    rows.sort(key=lambda r: r["date"])
    logger.info(f"  Sina K线 {code}: {len(rows)} 个交易日")
    return rows


def parse_sina_kline_row(item: dict, cutoff: datetime) -> Optional[dict]:
    """解析新浪 K 线单行数据（纯函数，便于测试）。

    注意：ma20/ma60 使用新浪接口真实提供的 ma_price20/ma_price60 字段，
    而不是早期实现的 ma_price10/ma_price30 近似值。
    """
    try:
        day = item.get("day", "")
        if not day or (len(day) >= 10 and datetime.strptime(day[:10], "%Y-%m-%d") < cutoff):
            return None
        return {
            "date": day[:10],
            "open": safe_float(item.get("open"), 0.0),
            "high": safe_float(item.get("high"), 0.0),
            "low": safe_float(item.get("low"), 0.0),
            "close": safe_float(item.get("close"), 0.0),
            "volume": safe_float(item.get("volume"), 0.0),
            "ma5": safe_float(item.get("ma_price5")),
            "ma20": safe_float(item.get("ma_price20")),
            "ma60": safe_float(item.get("ma_price60")),
        }
    except Exception:
        return None


def _build_kline(df: pd.DataFrame, **col_map) -> list[dict]:
    """从 DataFrame 构建标准 K 线输出，含 MA5/MA20/MA60。"""
    df = df.sort_values(col_map["date_col"])
    close_series = df[col_map["close_col"]].astype(float)

    def _ma(n: int) -> list:
        return (close_series.rolling(window=n).mean().round(2).tolist()
                if len(close_series) >= n else [None] * len(close_series))

    ma5 = _ma(5)
    ma20 = _ma(20)
    ma60 = _ma(60)

    rows = []
    for i in range(len(df)):
        r = df.iloc[i]
        rows.append({
            "date": str(r[col_map["date_col"]]),
            "open": clean_float(r[col_map["open_col"]]),
            "high": clean_float(r[col_map["high_col"]]),
            "low": clean_float(r[col_map["low_col"]]),
            "close": clean_float(r[col_map["close_col"]]),
            "volume": clean_float(r[col_map["volume_col"]]),
            "ma5": clean_float(ma5[i]),
            "ma20": clean_float(ma20[i]),
            "ma60": clean_float(ma60[i]),
        })
    return rows
