"""股票相关 API 路由"""

import asyncio
import logging
import math
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.database import async_session, ScreenResult
from app.services.data_fetcher import fetch_financial_data
from app.services.kline import fetch_kline_data
from app.services.scheduler import run_full_refresh, get_refresh_status
from app.schemas import StockItem, KlineResponse, StockDetail, RefreshStatus

logger = logging.getLogger(__name__)
router = APIRouter()

# 冷缓存下网络抓取可能很慢，详情页/图表接口不应被阻塞：
# 财报历史超时则返回空数组，K 线超时则返回明确的 504
_FINANCIAL_FETCH_TIMEOUT = 10.0  # 秒
_KLINE_FETCH_TIMEOUT = 15.0      # 秒


@router.get("/health")
async def health():
    """健康检查"""
    return {"status": "ok", "time": datetime.now().isoformat()}


@router.get("/stocks", response_model=list[StockItem])
async def get_stocks():
    """获取 Top 20 筛选结果"""
    async with async_session() as session:
        stmt = select(ScreenResult).order_by(ScreenResult.rank).limit(20)
        result = await session.execute(stmt)
        stocks = result.scalars().all()
        return stocks


@router.get("/stocks/{code}", response_model=StockDetail)
async def get_stock_detail(code: str):
    """获取个股详情（含五维评分 + 财务历史）"""
    code = code.zfill(6)
    async with async_session() as session:
        stmt = select(ScreenResult).where(ScreenResult.code == code)
        result = await session.execute(stmt)
        stock = result.scalar_one_or_none()

    if not stock:
        raise HTTPException(status_code=404, detail="股票不存在")

    # 财务历史由前端单独请求 /financial，避免冷缓存抓取阻塞详情页
    financials = []

    return StockDetail(
        code=stock.code,
        name=stock.name,
        industry=stock.industry,
        price=stock.price,
        change_pct=stock.change_pct,
        pe=stock.pe,
        pb=stock.pb,
        roe=stock.roe,
        market_cap=stock.market_cap,
        total_score=stock.total_score,
        quality_score=stock.quality_score,
        dividend_score=stock.dividend_score,
        value_score=stock.value_score,
        growth_score=stock.growth_score,
        momentum_score=stock.momentum_score,
        financials=financials,
    )


@router.get("/stocks/{code}/kline", response_model=KlineResponse)
async def get_kline(code: str, months: int = Query(12, ge=1, le=60)):
    """获取前复权 K 线数据"""
    code = code.zfill(6)
    async with async_session() as session:
        stmt = select(ScreenResult).where(ScreenResult.code == code)
        result = await session.execute(stmt)
        stock = result.scalar_one_or_none()

    if not stock:
        raise HTTPException(status_code=404, detail="股票不存在")

    try:
        data = await asyncio.wait_for(
            fetch_kline_data(code, months=months), timeout=_KLINE_FETCH_TIMEOUT
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="获取 K 线数据超时，请稍后重试")
    if data is None:
        raise HTTPException(status_code=500, detail="获取 K 线数据失败")

    # Final safety: sanitize any remaining NaN/Inf values
    for row in data:
        for k, v in row.items():
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                row[k] = None

    return {
        "code": code,
        "name": stock.name,
        "adj_type": "前复权",
        "data": data,
    }


@router.get("/stocks/{code}/financial")
async def get_financial(code: str):
    """获取个股财务数据（最近几期）"""
    code = code.zfill(6)
    return await _get_financial_history(code)


@router.post("/refresh")
async def trigger_refresh():
    """手动触发刷新"""
    asyncio.ensure_future(run_full_refresh())
    return {"message": "刷新任务已启动", "status": get_refresh_status()}


@router.get("/refresh/status", response_model=RefreshStatus)
async def refresh_status():
    """获取刷新状态"""
    status = get_refresh_status()
    return RefreshStatus(
        is_running=status["is_running"],
        last_refresh=status["last_refresh"],
        message=status["message"],
    )


def _clean_json_float(val):
    """NaN/Inf → None，保证 JSON 合法。"""
    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
        return None
    return val


async def _get_financial_history(code: str) -> list[dict]:
    """从财报缓存取该股最近几期数据（含报告年份）。"""
    try:
        fin_df = await asyncio.wait_for(
            fetch_financial_data(), timeout=_FINANCIAL_FETCH_TIMEOUT
        )
    except asyncio.TimeoutError:
        logger.warning(f"财报历史获取超时（>{_FINANCIAL_FETCH_TIMEOUT}s），详情页跳过财务数据")
        return []
    except Exception as e:
        logger.warning(f"财报历史获取失败: {e}")
        return []
    if fin_df is None or fin_df.empty or "year" not in fin_df.columns:
        return []
    stock_fin = fin_df[fin_df["code"] == code]
    if stock_fin.empty:
        return []
    stock_fin = stock_fin.sort_values("year", ascending=False).head(4)

    records = []
    for _, row in stock_fin.iterrows():
        records.append({
            "quarter": f"{int(row['year'])}年报",
            "revenue": _clean_json_float(row.get("revenue")),
            "profit": _clean_json_float(row.get("profit")),
            "roe": _clean_json_float(row.get("roe")),
            "gross_margin": _clean_json_float(row.get("gross_margin")),
            "revenue_growth": _clean_json_float(row.get("revenue_growth")),
            "profit_growth": _clean_json_float(row.get("profit_growth")),
        })
    return records
