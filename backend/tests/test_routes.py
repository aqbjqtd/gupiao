"""路由层行为的单元测试（不发起真实网络请求）。"""

import asyncio

import pandas as pd

from app.routers import stocks as stocks_router


def test_financial_history_timeout_returns_empty(monkeypatch):
    """冷缓存时财报抓取很慢，详情页必须快速降级为空数组而不是卡死。"""
    async def slow_fetch():
        await asyncio.sleep(30)
        return pd.DataFrame()

    monkeypatch.setattr(stocks_router, "fetch_financial_data", slow_fetch)
    monkeypatch.setattr(stocks_router, "_FINANCIAL_FETCH_TIMEOUT", 0.05)

    result = asyncio.run(stocks_router._get_financial_history("600001"))
    assert result == []


def test_financial_history_returns_latest_first_and_sanitizes_nan(monkeypatch):
    """财务历史按年份倒序返回，NaN 转为 None 保证 JSON 合法。"""
    async def fake_fetch():
        return pd.DataFrame({
            "code": ["600001", "600001"],
            "year": [2024, 2025],
            "roe": [12.0, 15.0],
            "gross_margin": [38.0, 40.0],
            "revenue_growth": [8.0, 10.0],
            "profit_growth": [9.0, 12.0],
            "revenue": [9e8, 1e9],
            "profit": [float("nan"), 1.2e8],
            "cf_ps": [0.8, 1.0],
        })

    monkeypatch.setattr(stocks_router, "fetch_financial_data", fake_fetch)

    result = asyncio.run(stocks_router._get_financial_history("600001"))
    assert len(result) == 2
    assert result[0]["quarter"] == "2025年报"
    assert result[1]["quarter"] == "2024年报"
    assert result[0]["roe"] == 15.0
    assert result[1]["profit"] is None  # NaN → None


def test_financial_history_fetch_error_returns_empty(monkeypatch):
    async def broken_fetch():
        raise RuntimeError("akshare 挂了")

    monkeypatch.setattr(stocks_router, "fetch_financial_data", broken_fetch)

    result = asyncio.run(stocks_router._get_financial_history("600001"))
    assert result == []
