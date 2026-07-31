"""数据获取层标准化/工具函数单元测试（不发起网络请求）。"""

from datetime import datetime, timedelta

import pandas as pd

from app.services.data_fetcher import _normalize_dividend, _normalize_em_spot, _normalize_financial
from app.services.kline import (
    parse_sina_kline_row,
    symbol_sina,
    trim_cache,
)
from app.services.numeric import clean_float, safe_float
from app.schemas import KlineItem


def test_normalize_financial_maps_columns_and_keeps_year():
    raw = pd.DataFrame({
        "股票代码": ["1", "2"],
        "净资产收益率": [15.0, 20.0],
        "销售毛利率": [40.0, 50.0],
        "营业总收入-同比增长": [10.0, 15.0],
        "净利润-同比增长": [12.0, 18.0],
        "营业总收入": [1e9, 2e9],
        "净利润": [1e8, 3e8],
        "每股经营现金流量": [1.0, 2.0],
        "year": [2025, 2025],
    })
    result = _normalize_financial(raw)
    assert list(result["code"]) == ["000001", "000002"]  # 补零
    assert "year" in result.columns
    assert result["revenue"].tolist() == [1e9, 2e9]
    assert result["profit"].tolist() == [1e8, 3e8]
    assert result["cf_ps"].tolist() == [1.0, 2.0]
    assert result["roe"].tolist() == [15.0, 20.0]


def test_normalize_em_spot():
    raw = pd.DataFrame({
        "代码": [1, 2],
        "名称": ["甲", "乙"],
        "最新价": [10.0, 20.0],
        "涨跌幅": [1.0, -1.0],
        "市盈率-动态": [10.0, 20.0],
        "市净率": [1.5, 3.0],
        "总市值": [1e10, 2e10],  # 元 → 亿
        "行业": ["电子", "医药"],
        "换手率": [3.0, 2.0],
        "60日涨跌幅": [5.0, 10.0],
    })
    result = _normalize_em_spot(raw)
    assert list(result["code"]) == ["000001", "000002"]
    assert result["market_cap"].tolist() == [100.0, 200.0]
    assert set(result.columns) == {
        "code", "name", "price", "change_pct", "pe", "pb",
        "market_cap", "industry", "turnover_rate", "high_60d",
    }


def test_normalize_dividend():
    raw = pd.DataFrame({"代码": ["1"], "年均股息": [5.0]})
    result = _normalize_dividend(raw)
    assert result.iloc[0]["code"] == "000001"
    assert result.iloc[0]["avg_dividend_per_10"] == 5.0


def test_symbol_sina():
    assert symbol_sina("600001") == "sh600001"
    assert symbol_sina("000001") == "sz000001"
    assert symbol_sina("300001") == "sz300001"


def test_clean_float():
    assert clean_float("12.3") == 12.3
    assert clean_float(float("nan")) is None
    assert clean_float(float("inf")) is None
    assert clean_float(None) is None
    assert safe_float(float("-inf")) is None


def test_parse_sina_kline_row_uses_correct_ma_fields():
    """回归测试：MA20/MA60 必须使用新浪 ma_price20/ma_price60 字段。"""
    cutoff = datetime.now() - timedelta(days=30)
    item = {
        "day": datetime.now().strftime("%Y-%m-%d"),
        "open": "10.0",
        "high": "11.0",
        "low": "9.5",
        "close": "10.5",
        "volume": "10000",
        "ma_price5": "10.1",
        "ma_price10": "99.9",   # 旧实现误用的字段
        "ma_price20": "10.3",
        "ma_price30": "88.8",   # 旧实现误用的字段
        "ma_price60": "10.4",
    }
    row = parse_sina_kline_row(item, cutoff)
    assert row is not None
    assert row["ma20"] == 10.3
    assert row["ma60"] == 10.4


def test_parse_sina_kline_row_skips_old_dates():
    cutoff = datetime(2025, 1, 1)
    item = {"day": "2024-01-01", "open": "1", "high": "2",
            "low": "0.5", "close": "1.5", "volume": "1"}
    assert parse_sina_kline_row(item, cutoff) is None


def test_trim_cache_caps_size_fifo():
    cache = {f"k{i}": i for i in range(5)}
    result = trim_cache(cache, 2)
    assert len(result) == 2
    assert list(result.keys()) == ["k3", "k4"]  # 最早插入的先淘汰


def test_kline_schema_serializes_open_field():
    item = KlineItem(date="2025-01-01", open=1.0, high=2.0,
                     low=0.5, close=1.5, volume=100.0)
    data = item.model_dump()
    assert "open" in data
    assert "open_" not in data
