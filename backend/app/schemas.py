"""Pydantic 响应模型"""

from pydantic import BaseModel
from typing import Optional, List


class StockItem(BaseModel):
    """筛选结果项"""
    code: str
    name: str
    price: Optional[float] = None
    change_pct: Optional[float] = None
    pe: Optional[float] = None
    pb: Optional[float] = None
    roe: Optional[float] = None
    revenue_growth: Optional[float] = None
    profit_growth: Optional[float] = None
    gross_margin: Optional[float] = None
    dividend_yield: Optional[float] = None
    market_cap: Optional[float] = None
    industry: Optional[str] = None
    total_score: Optional[float] = None
    quality_score: Optional[float] = None
    dividend_score: Optional[float] = None
    value_score: Optional[float] = None
    growth_score: Optional[float] = None
    momentum_score: Optional[float] = None
    rank: Optional[int] = None

    class Config:
        from_attributes = True


class KlineItem(BaseModel):
    """K 线数据"""
    date: str
    open_: float
    high: float
    low: float
    close: float
    volume: float
    ma5: Optional[float] = None
    ma20: Optional[float] = None
    ma60: Optional[float] = None


class KlineResponse(BaseModel):
    """前复权 K 线响应"""
    code: str
    name: str
    adj_type: str = "前复权"
    data: List[KlineItem]


class StockDetail(BaseModel):
    """个股详情"""
    code: str
    name: str
    industry: Optional[str] = None
    price: Optional[float] = None
    change_pct: Optional[float] = None
    pe: Optional[float] = None
    pb: Optional[float] = None
    roe: Optional[float] = None
    market_cap: Optional[float] = None
    total_score: Optional[float] = None
    quality_score: Optional[float] = None
    dividend_score: Optional[float] = None
    value_score: Optional[float] = None
    growth_score: Optional[float] = None
    momentum_score: Optional[float] = None
    financials: List[dict] = []


class RefreshStatus(BaseModel):
    """刷新状态"""
    is_running: bool
    last_refresh: Optional[str] = None
    message: str = ""
