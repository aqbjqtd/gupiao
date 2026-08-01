"""健壮的数据获取层：akshare（东方财富源）优先 + Sina API 降级

策略：
  1. akshare 东方财富源优先（全字段，含行业/60日涨跌幅）
  2. Sina API 直连降级（缺少 industry/high_60d 字段，但稳定可用）
  3. 严格速率限制：全局 ≥3s 间隔 + 随机 0-3s 抖动
  4. 指数退避重试：5次重试，基础间隔 5s，上限 120s
  5. 连接超时保护：120s
  6. 全流程异常保护：单 endpoint 失败不影响整体
"""

import logging
from datetime import datetime
from typing import Optional

import akshare as ak
import pandas as pd
import httpx

from app.config import settings
from app.services.cache import get_cache, get_cache_stale, set_cache
from app.services.numeric import safe_float
from app.services.rate_limit import (
    rate_limit,
    async_retry,
    run_akshare,
    akshare_with_retry,
)

logger = logging.getLogger(__name__)


# ========================================================================
# 1. 全市场实时行情：东方财富（akshare）优先 → Sina API 降级 → 腾讯降级
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
    df = await akshare_with_retry("spot_em", ak.stock_zh_a_spot_em)
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
            await rate_limit("sina_spot")
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
        all_stocks = await async_retry(_fetch_all)
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
                "price": safe_float(item.get("trade")),
                "change_pct": safe_float(item.get("changepercent")),
                "pe": safe_float(item.get("per")),
                "pb": safe_float(item.get("pb")),
                # mktcap 单位是万元 → 亿
                "market_cap": (
                    safe_float(item.get("mktcap"), 0) / 10000
                    if safe_float(item.get("mktcap"))
                    else None
                ),
                "turnover_rate": safe_float(item.get("turnoverratio")),
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


# ---- 腾讯源（第二降级，字段较全含 60 日涨跌幅，仅缺行业）----

TENCENT_RANK_URL = (
    "https://proxy.finance.qq.com/cgi/cgi-bin/rank/hs/getBoardRankList"
)


async def _fetch_spot_tencent() -> Optional[pd.DataFrame]:
    """通过腾讯财经获取全市场行情（第二降级方案）。

    与新浪相比：含 60 日涨跌幅（zdf_d60），但同样缺行业字段。
    board_code=aStock 全 A 股，分页拉取。
    """
    logger.info("[腾讯源] 开始获取全市场实时行情（第二降级方案）……")
    all_stocks: list[dict] = []
    offset = 0
    page_size = 100

    async def _fetch_all():
        nonlocal all_stocks, offset
        while True:
            await rate_limit("tencent_spot")
            params = {
                "board_code": "aStock",
                "sort_type": "price",
                "direct": "down",
                "offset": offset,
                "count": page_size,
            }
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(TENCENT_RANK_URL, params=params)
                resp.raise_for_status()
                data = resp.json()
            ranks = data.get("data", {}).get("rank_list") or []
            if not ranks:
                break
            all_stocks.extend(ranks)
            total = data.get("data", {}).get("total", 0)
            offset += len(ranks)
            logger.debug(f"  腾讯第{offset // page_size}页: {len(ranks)} 只 (共{total})")
            if offset >= total:
                break
        return all_stocks

    try:
        all_stocks = await async_retry(_fetch_all)
    except Exception as e:
        logger.error(f"[腾讯源] 完全失败: {e}")
        return None

    if not all_stocks:
        return None

    logger.info(f"[腾讯源] 成功获取 {len(all_stocks)} 只股票原始数据")
    return _normalize_tencent_spot(all_stocks)


def _normalize_tencent_spot(data: list[dict]) -> pd.DataFrame:
    """标准化腾讯行情数据。

    注意：腾讯不返回行业(industry)，设为 None；其余字段齐全。
      code: sh600519 → 600519
      zxj: 最新价, zdf: 涨跌幅, pe_ttm: PE, pn: 市净率
      zsz: 总市值(亿), hsl: 换手率, zdf_d60: 60日涨跌幅
    """
    rows = []
    for item in data:
        try:
            raw_code = str(item.get("code", ""))
            code = raw_code[-6:] if len(raw_code) >= 6 else raw_code.zfill(6)
            rows.append({
                "code": code,
                "name": str(item.get("name", "")),
                "price": safe_float(item.get("zxj")),
                "change_pct": safe_float(item.get("zdf")),
                "pe": safe_float(item.get("pe_ttm")),
                "pb": safe_float(item.get("pn")),
                "market_cap": safe_float(item.get("zsz")),   # 单位已是亿
                "turnover_rate": safe_float(item.get("hsl")),
                "industry": None,   # 腾讯不返回行业
                "high_60d": safe_float(item.get("zdf_d60")),  # 60日涨跌幅
            })
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
      4. Sina 失败 → 腾讯源降级（缺少行业，含60日涨跌幅）
      5. 全失败 → 过期缓存兜底
    """
    # 检查缓存
    if not force:
        cached = await get_cache("spot")
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

    # —— 降级1：新浪源 ——
    if not em_ok:
        logger.info("→ 降级到新浪源……")
        try:
            result = await _fetch_spot_sina()
            if result is not None and not result.empty:
                logger.info(f"✓ 新浪源成功：{len(result)} 只股票（缺少 industry/high_60d 字段）")
        except Exception as e:
            logger.error(f"✗ 新浪源失败: {e}")
            result = None

    # —— 降级2：腾讯源 ——
    if result is None or result.empty:
        logger.info("→ 降级到腾讯源……")
        try:
            result = await _fetch_spot_tencent()
            if result is not None and not result.empty:
                logger.info(f"✓ 腾讯源成功：{len(result)} 只股票（缺少 industry 字段）")
        except Exception as e:
            logger.error(f"✗ 腾讯源失败: {e}")
            result = None

    # —— 兜底：过期缓存 ——
    if result is None or result.empty:
        logger.warning("三路源均失败，尝试过期缓存兜底……")
        stale = await get_cache_stale("spot")
        if stale is not None:
            logger.warning("使用过期缓存兜底")
            return pd.DataFrame(stale)
        return None

    # 缓存并返回
    records = result.to_dict(orient="records")
    await set_cache("spot", records, settings.cache_ttl_spot)
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
      营业总收入   → revenue
      净利润       → profit
      每股经营现金流量 → cf_ps
    """
    # 检查缓存（v2：缓存内容新增 year/revenue/profit/cf_ps 字段，版本号避免旧缓存缺列）
    if not force:
        cached = await get_cache("financial_v2")
        if cached is not None:
            logger.info(f"使用缓存财报数据 ({len(cached)} 条, 有效期内)")
            return pd.DataFrame(cached)

    logger.info("开始获取季度财报数据……")
    current_year = datetime.now().year
    # 年报披露截止次年 4 月 30 日：任何时候当前年的年报都尚未披露，
    # 直接拉 current_year 必然返回空（akshare 抛 TypeError 且重试 5 次浪费 30s）。
    # 用最近两个已披露年报：current_year-1 和 current_year-2。
    years = [current_year - 1, current_year - 2]

    all_dfs: list[pd.DataFrame] = []
    for year in years:
        try:
            df = await akshare_with_retry(
                "financial", ak.stock_yjbb_em, date=f"{year}1231"
            )
            if df is not None and not df.empty:
                df = df.copy()
                df["year"] = year  # 标记报告年份，供筛选/详情页选择最新一期
                all_dfs.append(df)
                logger.info(f"  财报 {year} 年: {len(df)} 条")
            else:
                logger.warning(f"  财报 {year} 年返回空数据")
        except Exception as e:
            logger.warning(f"  财报 {year} 年获取失败: {e}")

    if not all_dfs:
        logger.error("所有年份财报获取失败")
        stale = await get_cache_stale("financial_v2")
        if stale is not None:
            logger.warning("使用过期财报缓存兜底")
            return pd.DataFrame(stale)
        return None

    df_all = pd.concat(all_dfs, ignore_index=True)
    result = _normalize_financial(df_all)
    records = result.to_dict(orient="records")
    await set_cache("financial_v2", records, settings.cache_ttl_financial)
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
    # 营收（用于 PS 估值因子）——兼容不同版本列名
    rev_col = (
        "营业总收入-营业总收入" if "营业总收入-营业总收入" in result.columns
        else "营业总收入" if "营业总收入" in result.columns
        else "营业收入" if "营业收入" in result.columns
        else None
    )
    result["revenue"] = (
        pd.to_numeric(result[rev_col], errors="coerce")
        if rev_col else None
    )
    # 净利润（用于个股财务历史展示）——兼容不同版本列名
    profit_col = (
        "净利润-净利润" if "净利润-净利润" in result.columns
        else "净利润" if "净利润" in result.columns
        else None
    )
    result["profit"] = (
        pd.to_numeric(result[profit_col], errors="coerce")
        if profit_col else None
    )
    # 每股经营现金流量（质量因子中的现金流子因子）
    result["cf_ps"] = pd.to_numeric(
        result.get("每股经营现金流量", None), errors="coerce"
    )
    keep = ["code", "year", "roe", "gross_margin", "revenue_growth",
            "profit_growth", "revenue", "profit", "cf_ps"]
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
        cached = await get_cache("dividend")
        if cached is not None:
            logger.info(f"使用缓存分红数据 ({len(cached)} 条, 有效期内)")
            return pd.DataFrame(cached)

    logger.info("开始获取分红数据……")
    try:
        df = await akshare_with_retry("dividend", ak.stock_history_dividend)
    except Exception as e:
        logger.error(f"获取分红数据完全失败: {e}")
        stale = await get_cache_stale("dividend")
        if stale is not None:
            logger.warning("使用过期分红缓存兜底")
            return pd.DataFrame(stale)
        return None

    if df is None or df.empty:
        logger.warning("分红数据返回空")
        return None

    result = _normalize_dividend(df)
    records = result.to_dict(orient="records")
    await set_cache("dividend", records, settings.cache_ttl_dividend)
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

