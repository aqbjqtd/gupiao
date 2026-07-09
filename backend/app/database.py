"""数据库：SQLAlchemy async + SQLite"""

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Float, Integer, DateTime, Text, func
from app.config import settings

engine = create_async_engine(settings.database_url, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


# ---- 模型 ----

class StockCache(Base):
    """数据缓存表——存储各接口的原始数据"""
    __tablename__ = "stock_cache"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    cache_type: Mapped[str] = mapped_column(String(32), index=True)  # spot / financial / dividend
    data_json: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
    expires_at: Mapped[DateTime] = mapped_column(DateTime)


class ScreenResult(Base):
    """筛选结果表"""
    __tablename__ = "screen_results"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(6), index=True)
    name: Mapped[str] = mapped_column(String(64))
    industry: Mapped[str] = mapped_column(String(64), nullable=True)
    price: Mapped[float] = mapped_column(Float, nullable=True)
    change_pct: Mapped[float] = mapped_column(Float, nullable=True)
    pe: Mapped[float] = mapped_column(Float, nullable=True)
    pb: Mapped[float] = mapped_column(Float, nullable=True)
    roe: Mapped[float] = mapped_column(Float, nullable=True)
    revenue_growth: Mapped[float] = mapped_column(Float, nullable=True)
    profit_growth: Mapped[float] = mapped_column(Float, nullable=True)
    gross_margin: Mapped[float] = mapped_column(Float, nullable=True)
    dividend_yield: Mapped[float] = mapped_column(Float, nullable=True)
    market_cap: Mapped[float] = mapped_column(Float, nullable=True)
    total_score: Mapped[float] = mapped_column(Float, nullable=True)
    quality_score: Mapped[float] = mapped_column(Float, nullable=True)
    dividend_score: Mapped[float] = mapped_column(Float, nullable=True)
    value_score: Mapped[float] = mapped_column(Float, nullable=True)
    growth_score: Mapped[float] = mapped_column(Float, nullable=True)
    momentum_score: Mapped[float] = mapped_column(Float, nullable=True)
    rank: Mapped[int] = mapped_column(Integer)
    refreshed_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())


class FinancialData(Base):
    """个股季度财务数据"""
    __tablename__ = "financial_data"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(6), index=True)
    quarter: Mapped[str] = mapped_column(String(16))  # e.g. "2024Q1"
    revenue: Mapped[float] = mapped_column(Float, nullable=True)
    profit: Mapped[float] = mapped_column(Float, nullable=True)
    roe: Mapped[float] = mapped_column(Float, nullable=True)
    gross_margin: Mapped[float] = mapped_column(Float, nullable=True)
    revenue_growth: Mapped[float] = mapped_column(Float, nullable=True)
    profit_growth: Mapped[float] = mapped_column(Float, nullable=True)


async def init_db():
    """创建表"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncSession:
    """获取数据库会话"""
    async with async_session() as session:
        yield session
