"""健壮的数据获取层：akshare（东方财富源）优先 + Sina API 降级

策略：
  1. akshare 东方财富源优先（全字段，含行业/60日涨跌幅）
  2. Sina API 直连降级（缺少 industry/high_60d 字段，但稳定可用）
  3. 严格速率限制：全局 ≥3s 间隔 + 随机 0-3s 抖动
  4. 指数退避重试：5次重试，基础间隔 5s，上限 120s
  5. 连接超时保护：120s
  6. 全流程异常保护：单 endpoint 失败不影响整体
"""

import json
import asyncio
import random
import time
import logging
from datetime import datetime, timedelta
from typing import Optional, Any, Callable

import akshare as ak
import pandas as pd
import httpx
from sqlalchemy import delete

from app.database import StockCache, async_session
from app.config import settings

logger = logging.getLogger(__name__)

# ========================================================================
# 全局速率限制器（每个 endpoint 独立追踪）
# ========================================================================
_last_call_times: dict[str, float] = {}
_lock = asyncio.Lock()


async def _rate_limit(endpoint: str = "default"):
    """等待直到可以安全调用。间隔 ≥3s + 随机 0~3s 抖动防检测。"""
    async with _lock:
        now = time.monotonic()
        base = settings.akshare_interval  # 3s
        jitter = random.uniform(0, settings.akshare_interval_jitter)  # 0~3s
        min_interval = base + jitter  # 3~6s

        # 检查所有 endpoint 的上次调用时间（全局协调）
        wait = 0.0
        for name, last in list(_last_call_times.items()):
            elapsed = now - last
            needed = min_interval - elapsed
            if needed > wait:
                wait = needed

        if wait > 0:
            logger.debug(f"速率限制：等待 {wait:.1f}s (endpoint={endpoint})")
            await asyncio.sleep(wait)
        _last_call_times[endpoint] = time.monotonic()


# ========================================================================
# 指数退避 + 全抖动重试
# ========================================================================
async def _async_retry(fn: Callable, *args, **kwargs):
    """指数退避 + 全抖动重试包装器。
    
    退避序列：5s, 10s, 20s, 40s, 80s（上限 120s）
    """
    max_attempts = settings.retry_max_attempts  # 5
    base_delay = settings.retry_base_delay      # 5s
    max_delay = settings.retry_max_delay         # 120s
    last_exc = None
    for attempt in range(1, max_attempts + 1):
        try:
            return await fn(*args, **kwargs)
        except Exception as e:
            last_exc = e
            if attempt < max_attempts:
                # 指数退避，全抖动（full jitter）
                cap = min(max_delay, base_delay * (2 ** (attempt - 1)))
                sleep_sec = random.uniform(0, cap)
                logger.warning(
                    f"请求失败 (attempt {attempt}/{max_attempts}): {str(e)[:120]} "
                    f"— 等待 {sleep_sec:.1f}s 后重试"
                )
                await asyncio.sleep(sleep_sec)
    # 所有重试均失败
    raise last_exc


# ========================================================================
# akshare 阻塞函数桥接（在 executor 中运行）
# ========================================================================
async def _run_akshare(func: Callable, *args, **kwargs):
    """在线程池 executor 中运行阻塞的 akshare 调用，带超时保护。"""
    loop = asyncio.get_running_loop()
    return await asyncio.wait_for(
        loop.run_in_executor(None, lambda: func(*args, **kwargs)),
        timeout=settings.akshare_timeout,  # 120s
    )


async def _akshare_with_retry(endpoint: str, func: Callable, *args, **kwargs):
    """akshare 统一调用：速率限制 + 指数退避重试。"""
    async def _call():
        await _rate_limit(endpoint)
        return await _run_akshare(func, *args, **kwargs)
    return await _async_retry(_call)


# ========================================================================
# 1. 全市场实时行情：东方财富（akshare）优先 → Sina API 降级
# ========================================================================

# ---- 东方财富源（主）----

def _normalize_em_spot(df: pd.DataFrame) -> pd.DataFrame:
    """标准化东方财富行情数据。
    
    stock_zh_a_spot_em 返回列名对照：
      代码 → code, 名称 → name, 最新价 → price, 涨跌幅 → change_pct
      市盈率-动态 → pe, 市净率 → pb
      总市值 → market_cap (元 → 亿)
      行业 → industry, 换手率 → turnover_rate
      60日涨跌幅 → high_60d
    """
    # 列名映射
    col_map = {
        "代码": "code",
        "名称": "name",
        "最新价": "price",
        "涨跌幅": "change_pct",
        "市盈率-动态": "pe",
        "市净率": "pb",
        "总市值": "market_cap",
        "行业": "industry",
        "换手率": "turnover_rate",
        "60日涨跌幅": "high_60d",
    }
    result = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})

    # 类型转换
    if "code" in result.columns:
        result["code"] = result["code"].astype(str).str.zfill(6)
    for col in ["price", "change_pct", "pe", "pb", "turnover_rate", "high_60d"]:
        if col in result.columns:
            result[col] = pd.to_numeric(result[col], errors="coerce")
    # 总市值从元转换为亿
    if "market_cap" in result.columns:
        result["market_cap"] = pd.to_numeric(result["market_cap"], errors="coerce") / 1e8

    # 只保留已知列
    known = list(col_map.values())
    return result[[c for c in known if c in result.columns]]


async def _fetch_spot_em() -> Optional[pd.DataFrame]:
    """通过 akshare 获取东方财富全市场行情。"""
    logger.info("[东方财富源] 开始获取全市场实时行情……")
    df = await _akshare_with_retry("spot_em", ak.stock_zh_a_spot_em)
    if df is None or df.empty:
        logger.warning("[东方财富源] 返回空数据")
        return None
    logger.info(f"[东方财富源] 成功获取 {len(df)} 只股票行情数据")
    return _normalize_em_spot(df)


# ---- Sina 源（降级）----

SINA_HQ_URL = (
    "https://vip.stock.finance.sina.com.cn/quotes_service/api/"
    "json_v2.php/Market_Center.getHQNodeData"
)


async def _fetch_sina_page(page: int, num: int = 100) -> list[dict]:
    """获取新浪行情一页数据。"""
    params = {
        "page": page,
        "num": num,
        "sort": "symbol",
        "asc": "1",
        "node": "hs_a",
        "_s_r_a": "init",
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.get(SINA_HQ_URL, params=params)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list):
            raise ValueError(f"新浪返回非列表: {data}")
        return data


async def _fetch_spot_sina() -> Optional[pd.DataFrame]:
    """通过 Sina API 直连获取全市场行情（降级方案）。"""
    logger.info("[新浪源] 开始获取全市场实时行情（降级方案）……")
    all_stocks: list[dict] = []

    async def _fetch_all():
        first = await _fetch_sina_page(1, 100)
        all_stocks.extend(first)
        if not first:
            return all_stocks
        for page in range(2, 60):
            await _rate_limit("sina_spot")
            try:
                data = await _fetch_sina_page(page, 100)
                if not data:
                    break
                all_stocks.extend(data)
                logger.debug(f"  新浪第{page}页: {len(data)} 只")
            except Exception as e:
                logger.warning(f"  新浪第{page}页失败: {e}")
                continue
        return all_stocks

    try:
        all_stocks = await _async_retry(_fetch_all)
    except Exception as e:
        logger.error(f"[新浪源] 完全失败: {e}")
        return None

    if not all_stocks:
        return None

    logger.info(f"[新浪源] 成功获取 {len(all_stocks)} 只股票原始数据")
    return _normalize_sina_spot(all_stocks)


def _normalize_sina_spot(data: list[dict]) -> pd.DataFrame:
    """标准化新浪行情数据为 DataFrame。
    
    注意：新浪不返回行业(industry)和60日涨跌幅(high_60d)，设为 None。
    """
    rows = []
    for item in data:
        try:
            row = {
                "code": str(item.get("code", "")).zfill(6),
                "name": str(item.get("name", "")),
                "price": _safe_float(item.get("trade")),
                "change_pct": _safe_float(item.get("changepercent")),
                "pe": _safe_float(item.get("per")),
                "pb": _safe_float(item.get("pb")),
                # mktcap 单位是万元 → 亿
                "market_cap": (
                    _safe_float(item.get("mktcap"), 0) / 10000
                    if _safe_float(item.get("mktcap"))
                    else None
                ),
                "turnover_rate": _safe_float(item.get("turnoverratio")),
                "industry": None,   # 新浪不返回行业
                "high_60d": None,   # 新浪不返回60日涨跌幅
            }
            rows.append(row)
        except Exception:
            continue

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df[df["code"].notna() & df["name"].notna()]
    return df


# ---- 对外接口 ----

async def fetch_spot_data(force: bool = False) -> Optional[pd.DataFrame]:
    """获取全市场实时行情。
    
    策略：
      1. 缓存有效 → 直接返回
      2. 东方财富源（akshare）优先，全字段含行业/60日涨跌幅
      3. 东方财富失败 → Sina API 降级（缺少行业/60日涨跌幅）
      4. 全失败 → 过期缓存兜底
    """
    # 检查缓存
    if not force:
        cached = await _get_cache("spot")
        if cached is not None and len(cached) > 100:
            logger.info(f"使用缓存行情数据 ({len(cached)} 只, 有效期内)")
            return pd.DataFrame(cached)

    # —— 主源：东方财富 ——
    result: Optional[pd.DataFrame] = None
    em_ok = False
    try:
        result = await _fetch_spot_em()
        if result is not None and not result.empty:
            em_ok = True
            logger.info(f"✓ 东方财富源成功：{len(result)} 只股票")
    except Exception as e:
        logger.warning(f"✗ 东方财富源失败: {e}")

    # —— 降级：新浪源 ——
    if not em_ok:
        logger.info("→ 降级到新浪源……")
        try:
            result = await _fetch_spot_sina()
            if result is not None and not result.empty:
                logger.info(f"✓ 新浪源成功：{len(result)} 只股票（缺少 industry/high_60d 字段）")
        except Exception as e:
            logger.error(f"✗ 新浪源也失败: {e}")
            result = None

    # —— 兜底：过期缓存 ——
    if result is None or result.empty:
        logger.warning("两路源均失败，尝试过期缓存兜底……")
        stale = await _get_cache_stale("spot")
        if stale is not None:
            logger.warning("使用过期缓存兜底")
            return pd.DataFrame(stale)
        return None

    # 缓存并返回
    records = result.to_dict(orient="records")
    await _set_cache("spot", records, settings.cache_ttl_spot)
    logger.info(f"全市场行情已缓存：{len(result)} 只股票")
    return result


# ========================================================================
# 2. 季度财报数据（akshare 东方财富源 stock_yjbb_em）
# ========================================================================
async def fetch_financial_data(force: bool = False) -> Optional[pd.DataFrame]:
    """获取季度财报数据——最近 2 年。
    
    stock_yjbb_em 列名对照：
      净资产收益率 → roe
      销售毛利率   → gross_margin
      营业总收入-同比增长 → revenue_growth
      净利润-同比增长 → profit_growth
    """
    # 检查缓存
    if not force:
        cached = await _get_cache("financial")
        if cached is not None:
            logger.info(f"使用缓存财报数据 ({len(cached)} 条, 有效期内)")
            return pd.DataFrame(cached)

    logger.info("开始获取季度财报数据……")
    current_year = datetime.now().year
    years = [current_year, current_year - 1]

    all_dfs: list[pd.DataFrame] = []
    for year in years:
        try:
            df = await _akshare_with_retry(
                "financial", ak.stock_yjbb_em, date=f"{year}1231"
            )
            if df is not None and not df.empty:
                all_dfs.append(df)
                logger.info(f"  财报 {year} 年: {len(df)} 条")
            else:
                logger.warning(f"  财报 {year} 年返回空数据")
        except Exception as e:
            logger.warning(f"  财报 {year} 年获取失败: {e}")

    if not all_dfs:
        logger.error("所有年份财报获取失败")
        stale = await _get_cache_stale("financial")
        if stale is not None:
            logger.warning("使用过期财报缓存兜底")
            return pd.DataFrame(stale)
        return None

    df_all = pd.concat(all_dfs, ignore_index=True)
    result = _normalize_financial(df_all)
    records = result.to_dict(orient="records")
    await _set_cache("financial", records, settings.cache_ttl_financial)
    logger.info(f"财报数据已缓存：{len(result)} 条记录")
    return result


def _normalize_financial(df_all: pd.DataFrame) -> pd.DataFrame:
    """标准化财报数据。"""
    result = df_all.copy()
    result["code"] = (
        result["股票代码"].astype(str).str.zfill(6)
        if "股票代码" in result.columns
        else result.get("code", result.index.astype(str))
    )
    # ROE
    result["roe"] = pd.to_numeric(
        result.get("净资产收益率", None), errors="coerce"
    )
    # 毛利率（兼容不同版本的列名）
    gross_col = (
        "销售毛利率" if "销售毛利率" in result.columns
        else "毛利率" if "毛利率" in result.columns
        else None
    )
    result["gross_margin"] = (
        pd.to_numeric(result[gross_col], errors="coerce")
        if gross_col else None
    )
    # 营收增速
    rev_col = (
        "营业总收入-同比增长" if "营业总收入-同比增长" in result.columns
        else "营业收入同比增长" if "营业收入同比增长" in result.columns
        else None
    )
    result["revenue_growth"] = (
        pd.to_numeric(result[rev_col], errors="coerce")
        if rev_col else None
    )
    # 利润增速
    profit_col = (
        "净利润-同比增长" if "净利润-同比增长" in result.columns
        else "净利润同比增长" if "净利润同比增长" in result.columns
        else None
    )
    result["profit_growth"] = (
        pd.to_numeric(result[profit_col], errors="coerce")
        if profit_col else None
    )
    keep = ["code", "roe", "gross_margin", "revenue_growth", "profit_growth"]
    return result[[c for c in keep if c in result.columns]]


# ========================================================================
# 3. 分红数据（akshare 东方财富源 stock_history_dividend）
# ========================================================================
async def fetch_dividend_data(force: bool = False) -> Optional[pd.DataFrame]:
    """获取分红数据。
    
    stock_history_dividend 列名：
      代码 → code
      年均股息 → avg_dividend_per_10（单位：元/10股）
    """
    if not force:
        cached = await _get_cache("dividend")
        if cached is not None:
            logger.info(f"使用缓存分红数据 ({len(cached)} 条, 有效期内)")
            return pd.DataFrame(cached)

    logger.info("开始获取分红数据……")
    try:
        df = await _akshare_with_retry("dividend", ak.stock_history_dividend)
    except Exception as e:
        logger.error(f"获取分红数据完全失败: {e}")
        stale = await _get_cache_stale("dividend")
        if stale is not None:
            logger.warning("使用过期分红缓存兜底")
            return pd.DataFrame(stale)
        return None

    if df is None or df.empty:
        logger.warning("分红数据返回空")
        return None

    result = _normalize_dividend(df)
    records = result.to_dict(orient="records")
    await _set_cache("dividend", records, settings.cache_ttl_dividend)
    logger.info(f"分红数据已缓存：{len(result)} 条记录")
    return result


def _normalize_dividend(df: pd.DataFrame) -> pd.DataFrame:
    """标准化分红数据。年均股息单位：元/10股。"""
    result = df.copy()
    result["code"] = (
        result["代码"].astype(str).str.zfill(6)
        if "代码" in result.columns
        else result.get("code", result.index.astype(str))
    )
    result["avg_dividend_per_10"] = pd.to_numeric(
        result.get("年均股息", None), errors="coerce"
    )
    return result[["code", "avg_dividend_per_10"]]


# ========================================================================
# 4. 前复权 K 线（akshare 东方财富源 stock_zh_a_hist → Sina 降级）
#    缓存 key: "{code}_{months}", TTL: 4h
# ========================================================================
_kline_cache: dict[str, tuple[float, list[dict]]] = {}
_KLINE_CACHE_TTL = 14400  # 4 秒改成 4小时

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
        await _rate_limit("kline")
        return await _run_akshare(
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
        _kline_cache[cache_key] = (time.monotonic(), result)

    return result


def _symbol_sina(code: str) -> str:
    """A股代码转新浪symbol格式：sh600004 / sz000001"""
    if code.startswith("6") or code.startswith("9"):
        return f"sh{code}"
    return f"sz{code}"


async def _fetch_kline_sina(code: str, months: int) -> Optional[list[dict]]:
    """通过新浪日K线API获取数据（scale=240 = 日线）"""
    symbol = _symbol_sina(code)
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
    from datetime import datetime as dt
    cutoff = datetime.now() - timedelta(days=months * 31)

    rows = []
    for item in raw:
        try:
            day = item.get("day", "")
            if not day or (len(day) >= 10 and dt.strptime(day[:10], "%Y-%m-%d") < cutoff):
                continue
            rows.append({
                "date": day[:10],
                "open": _safe_float(item.get("open"), 0.0),
                "high": _safe_float(item.get("high"), 0.0),
                "low": _safe_float(item.get("low"), 0.0),
                "close": _safe_float(item.get("close"), 0.0),
                "volume": _safe_float(item.get("volume"), 0.0),
                "ma5": _safe_float(item.get("ma_price5")),
                "ma20": _safe_float(item.get("ma_price10")),  # Sina MA10 ≈ MA20
                "ma60": _safe_float(item.get("ma_price30")),  # Sina MA30 ≈ MA60
            })
        except Exception:
            continue

    # 按日期升序
    rows.sort(key=lambda r: r["date"])
    logger.info(f"  Sina K线 {code}: {len(rows)} 个交易日")
    return rows


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
            "open": _clean_float(r[col_map["open_col"]]),
            "high": _clean_float(r[col_map["high_col"]]),
            "low": _clean_float(r[col_map["low_col"]]),
            "close": _clean_float(r[col_map["close_col"]]),
            "volume": _clean_float(r[col_map["volume_col"]]),
            "ma5": _clean_float(ma5[i]),
            "ma20": _clean_float(ma20[i]),
            "ma60": _clean_float(ma60[i]),
        })
    return rows


def _clean_float(val) -> Optional[float]:
    """转换为 float，NaN/Inf → None（JSON 安全）"""
    try:
        v = float(val)
        if v != v or v == float("inf") or v == float("-inf"):
            return None
        return round(v, 4)
    except (ValueError, TypeError):
        return None


# ========================================================================
# 5. 缓存操作
# ========================================================================
async def _get_cache(cache_type: str) -> Optional[list]:
    """读取有效缓存（未过期）。"""
    return await _get_cache_impl(cache_type, check_expiry=True)


async def _get_cache_stale(cache_type: str) -> Optional[list]:
    """读取任意缓存（即使已过期）。"""
    return await _get_cache_impl(cache_type, check_expiry=False)


async def _get_cache_impl(cache_type: str, check_expiry: bool) -> Optional[list]:
    from sqlalchemy import select as sa_select
    async with async_session() as session:
        stmt = (
            sa_select(StockCache)
            .where(StockCache.cache_type == cache_type)
            .order_by(StockCache.id.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        cache = result.scalar_one_or_none()
        if cache and (not check_expiry or cache.expires_at > datetime.now()):
            return json.loads(cache.data_json)
        return None


async def _set_cache(cache_type: str, data: Any, ttl_seconds: int):
    """写入缓存（先清旧记录）。"""
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


# ========================================================================
# 工具函数
# ========================================================================
def _safe_float(val, default=None):
    """安全的浮点数转换，处理 NaN、Inf 等边界情况。"""
    if val is None:
        return default
    try:
        v = float(val)
        if v != v or v == float("inf") or v == float("-inf"):
            return default
        return v
    except (ValueError, TypeError):
        return default
