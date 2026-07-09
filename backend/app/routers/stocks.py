"""股票相关 API 路由"""

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select, func

from app.database import async_session, ScreenResult, init_db
from app.services.data_fetcher import fetch_kline_data
from app.services.scheduler import run_full_refresh, get_refresh_status
from app.schemas import StockItem, KlineResponse, KlineItem, StockDetail, RefreshStatus

logger = logging.getLogger(__name__)
router = APIRouter()


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
    """获取个股详情（含五维评分）"""
    code = code.zfill(6)
    async with async_session() as session:
        stmt = select(ScreenResult).where(ScreenResult.code == code)
        result = await session.execute(stmt)
        stock = result.scalar_one_or_none()

    if not stock:
        raise HTTPException(status_code=404, detail="股票不存在")

    # 查询财务数据（从缓存财务表取最近4季）
    financials = []
    # 这个项目暂时用相同财务表的历史数据，简单返回空或示例
    # 实际可以做更复杂的财务历史查询

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


@router.get("/stocks/{code}/kline")
async def get_kline(code: str, months: int = Query(12, ge=1, le=60)):
    """获取前复权 K 线数据"""
    code = code.zfill(6)
    async with async_session() as session:
        stmt = select(ScreenResult).where(ScreenResult.code == code)
        result = await session.execute(stmt)
        stock = result.scalar_one_or_none()

    if not stock:
        raise HTTPException(status_code=404, detail="股票不存在")

    data = await fetch_kline_data(code, months=months)
    if data is None:
        raise HTTPException(status_code=500, detail="获取 K 线数据失败")

    return {
        "code": code,
        "name": stock.name,
        "adj_type": "前复权",
        "data": data,
    }


@router.get("/stocks/{code}/financial")
async def get_financial(code: str):
    """获取个股财务数据"""
    code = code.zfill(6)
    # 从财报缓存中获取
    from app.services.data_fetcher import fetch_financial_data
    fin_df = await fetch_financial_data()
    if fin_df is not None and not fin_df.empty:
        stock_fin = fin_df[fin_df["code"] == code]
        if not stock_fin.empty:
            return stock_fin.head(4).to_dict(orient="records")
    return []


@router.post("/refresh")
async def trigger_refresh():
    """手动触发刷新"""
    import asyncio
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
