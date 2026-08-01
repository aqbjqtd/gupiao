"""五维筛选引擎单元测试。"""

import numpy as np
import pandas as pd
import pytest

from app.services.screener import (
    FACTOR_WEIGHTS,
    SUB_WEIGHTS,
    _calculate_scores,
    _safe_float,
    _winsorize,
    run_screener,
)


def _spot_df() -> pd.DataFrame:
    return pd.DataFrame({
        "code": ["600001", "600002", "000003", "600004", "600005"],
        "name": ["优质电子", "银行股份", "ST退风险", "低质制造", "医药龙头"],
        "price": [10.0, 8.0, 5.0, 10.0, 20.0],
        "change_pct": [1.2, -0.5, 0.0, 0.8, 2.1],
        "pe": [10.0, 6.0, 50.0, 15.0, 20.0],
        "pb": [1.5, 0.8, 3.0, 1.2, 3.0],
        "market_cap": [100.0, 500.0, 200.0, 80.0, 200.0],
        "industry": ["电子", "银行", "化工", "机械", "医药"],
        "turnover_rate": [3.0, 0.8, 8.0, 1.5, 2.0],
        "high_60d": [10.0, 5.0, -8.0, 3.0, 15.0],
    })


def _fin_df() -> pd.DataFrame:
    return pd.DataFrame({
        "code": ["600001", "600001", "600002", "600004", "600005", "600005"],
        "year": [2025, 2024, 2025, 2025, 2025, 2024],
        "roe": [15.0, 12.0, 10.0, 2.0, 20.0, 18.0],
        "gross_margin": [40.0, 38.0, 45.0, 12.0, 50.0, 48.0],
        "revenue_growth": [10.0, 8.0, 5.0, -3.0, 15.0, 12.0],
        "profit_growth": [12.0, 9.0, 4.0, -5.0, 18.0, 15.0],
        "revenue": [1e9, 0.9e9, 5e9, 0.8e9, 2e9, 1.8e9],
        "cf_ps": [1.0, 0.8, 3.0, 0.1, 2.0, 1.5],
    })


def _div_df() -> pd.DataFrame:
    return pd.DataFrame({
        "code": ["600001", "600002", "600004", "600005"],
        "avg_dividend_per_10": [5.0, 2.0, 0.0, 8.0],
    })


def test_hard_filters_exclude_st_financial_low_roe():
    result = run_screener(_spot_df(), _fin_df(), _div_df())
    codes = set(result["code"])
    assert "600001" in codes   # 优质电子：通过全部硬过滤
    assert "600005" in codes   # 医药龙头：通过全部硬过滤
    assert "600002" not in codes  # 金融股
    assert "000003" not in codes  # ST
    assert "600004" not in codes  # ROE 不足 + 无分红


def test_rank_assigned_sequentially():
    result = run_screener(_spot_df(), _fin_df(), _div_df())
    assert list(result["rank"]) == list(range(1, len(result) + 1))


def test_latest_financial_year_selected():
    """同一股票多期财报时，应选择最新年份的数据。"""
    result = run_screener(_spot_df(), _fin_df(), _div_df())
    stock = result[result["code"] == "600005"].iloc[0]
    # 2025 年 ROE=20，而非 2024 年的 18（缩尾处理后略微下移，放宽容差）
    assert stock["roe"] == pytest.approx(20.0, abs=0.5)


def test_cf_ps_affects_quality_score():
    """回归测试：质量因子必须使用真实现金流，而不是用 ROE 顶替。"""
    spot = pd.DataFrame({
        "code": ["600001", "600002"],
        "name": ["甲", "乙"],
        "price": [10.0, 10.0],
        "change_pct": [0.0, 0.0],
        "pe": [10.0, 10.0],
        "pb": [1.5, 1.5],
        "market_cap": [100.0, 100.0],
        "industry": ["电子", "电子"],
        "turnover_rate": [3.0, 3.0],
        "high_60d": [5.0, 5.0],
    })
    fin = pd.DataFrame({
        "code": ["600001", "600002"],
        "year": [2025, 2025],
        "roe": [15.0, 15.0],
        "gross_margin": [40.0, 40.0],
        "revenue_growth": [10.0, 10.0],
        "profit_growth": [12.0, 12.0],
        "revenue": [1e9, 1e9],
        "cf_ps": [5.0, 0.5],  # 现金流差异显著
    })
    div = pd.DataFrame({
        "code": ["600001", "600002"],
        "avg_dividend_per_10": [5.0, 5.0],
    })
    result = run_screener(spot, fin, div)
    q1 = result[result["code"] == "600001"]["quality_score"].iloc[0]
    q2 = result[result["code"] == "600002"]["quality_score"].iloc[0]
    assert q1 != pytest.approx(q2)


def test_revenue_affects_value_score():
    """回归测试：估值因子必须使用真实 PS（市值/营收），而不是用 PE 顶替。"""
    spot = pd.DataFrame({
        "code": ["600001", "600002"],
        "name": ["甲", "乙"],
        "price": [10.0, 10.0],
        "change_pct": [0.0, 0.0],
        "pe": [10.0, 10.0],
        "pb": [1.5, 1.5],
        "market_cap": [100.0, 100.0],
        "industry": ["电子", "电子"],
        "turnover_rate": [3.0, 3.0],
        "high_60d": [5.0, 5.0],
    })
    fin = pd.DataFrame({
        "code": ["600001", "600002"],
        "year": [2025, 2025],
        "roe": [15.0, 15.0],
        "gross_margin": [40.0, 40.0],
        "revenue_growth": [10.0, 10.0],
        "profit_growth": [12.0, 12.0],
        "revenue": [5e9, 0.5e9],  # 营收差异 → PS 差异
        "cf_ps": [1.0, 1.0],
    })
    div = pd.DataFrame({
        "code": ["600001", "600002"],
        "avg_dividend_per_10": [5.0, 5.0],
    })
    result = run_screener(spot, fin, div)
    v1 = result[result["code"] == "600001"]["value_score"].iloc[0]
    v2 = result[result["code"] == "600002"]["value_score"].iloc[0]
    assert v1 != pytest.approx(v2)


def test_empty_result_when_nothing_passes():
    spot = pd.DataFrame({
        "code": ["600001"],
        "name": ["无分红低质股"],
        "price": [10.0],
        "change_pct": [0.0],
        "pe": [30.0],
        "pb": [2.0],
        "market_cap": [10.0],
        "industry": ["机械"],
        "turnover_rate": [1.0],
        "high_60d": [1.0],
    })
    fin = pd.DataFrame({
        "code": ["600001"],
        "year": [2025],
        "roe": [1.0],
        "gross_margin": [5.0],
        "revenue_growth": [0.0],
        "profit_growth": [0.0],
        "revenue": [1e8],
        "cf_ps": [0.1],
    })
    div = pd.DataFrame({
        "code": ["600001"],
        "avg_dividend_per_10": [0.0],
    })
    result = run_screener(spot, fin, div)
    assert result.empty


def test_factor_weights_sum_to_one():
    assert sum(FACTOR_WEIGHTS.values()) == pytest.approx(1.0)
    for sub in SUB_WEIGHTS.values():
        assert sum(sub.values()) == pytest.approx(1.0)


def test_winsorize_clips_extremes():
    s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0])
    clipped = _winsorize(s, lower=0.2, upper=0.8)
    assert clipped.max() <= 8.2
    assert clipped.min() >= 2.8


def test_safe_float_handles_nan_inf():
    assert _safe_float(float("nan")) is None
    assert _safe_float(float("inf")) is None
    assert _safe_float("12.5") == 12.5
    assert _safe_float(None) is None


def test_scores_return_same_length_as_input():
    df = _spot_df().merge(
        _fin_df().sort_values(["code", "year"], ascending=[True, False])
        .groupby("code").first().reset_index(),
        on="code", how="left",
    ).merge(
        _div_df().groupby("code")["avg_dividend_per_10"].mean()
        .reset_index()
        .rename(columns={"avg_dividend_per_10": "avg_dividend"}),
        on="code", how="left",
    )
    df["dividend_yield"] = df["avg_dividend"].fillna(0) / 10.0 / df["price"] * 100
    df["ps"] = df["market_cap"] * 1e8 / df["revenue"]
    bad_ps = df["ps"].isna() | np.isinf(df["ps"])
    df["ps"] = df["ps"].where(~bad_ps, df["pe"])
    scores = _calculate_scores(df)
    for key, series in scores.items():
        assert len(series) == len(df)
        assert series.isna().sum() == 0


def test_np_import_available():
    # 防止未来误删 numpy 依赖导致筛选引擎崩溃
    assert np is not None


def test_negative_pe_gets_worst_value_score():
    """回归：负 PE（亏损股）在 pe 子因子必须垫底，不能反向拿满分。"""
    from app.services.screener import _reverse_percentile_rank, _value_factor_series

    pe = pd.Series([10.0, 6.0, 50.0, 15.0, -5.0])  # 600005 改为负 PE
    processed = _value_factor_series(pe)
    # 负值被映射为大于所有有效值的占位
    assert processed.max() == processed.iloc[4]
    assert processed.iloc[4] > processed.iloc[0]
    score = _reverse_percentile_rank(processed)
    # 负 PE 股反向排名垫底（0 分），最小 PE 股得最高分
    assert score.iloc[4] == 0
    assert score.iloc[1] == score.max()  # pe=6 最小 → 反向最高分


def test_momentum_fallback_when_high_60d_missing():
    """回归：high_60d 全缺失（新浪降级源）时动量子因子用 change_pct 近似，不静默失效。"""
    df = _spot_df().copy()
    df["high_60d"] = None  # 模拟新浪降级：无 60 日涨跌幅
    df = df.merge(
        _fin_df().sort_values(["code", "year"], ascending=[True, False])
        .groupby("code").first().reset_index(),
        on="code", how="left",
    ).merge(
        _div_df().groupby("code")["avg_dividend_per_10"].mean()
        .reset_index()
        .rename(columns={"avg_dividend_per_10": "avg_dividend"}),
        on="code", how="left",
    )
    df["dividend_yield"] = df["avg_dividend"].fillna(0) / 10.0 / df["price"] * 100
    df["ps"] = df["market_cap"] * 1e8 / df["revenue"]
    bad_ps = df["ps"].isna() | np.isinf(df["ps"])
    df["ps"] = df["ps"].where(~bad_ps, df["pe"])

    scores = _calculate_scores(df)
    # 降级后动量分仍是有区分度的排名（非全并列），且无 NaN
    mom = scores["momentum"]
    assert mom.isna().sum() == 0
    assert mom.nunique() > 1  # 有区分度，说明不是静默 fillna(0) 全并列


def test_turnover_u_shape_penalty():
    """回归：换手率 U 型惩罚——远离最优区间 [0.5, 20] 单调递减，40% 归零。"""
    from app.services.screener import _turnover_quality_score

    tr = pd.Series([0.2, 1.0, 8.0, 19.0, 25.0, 40.0])
    scored = _turnover_quality_score(tr)
    # 区间内保持原值
    assert scored.iloc[2] == 8.0
    assert scored.iloc[3] == 19.0
    # 高端单调衰减：25 → 15，40 → 0（离 20 越远越低）
    assert scored.iloc[4] == 15.0
    assert scored.iloc[4] > scored.iloc[5]
    assert scored.iloc[5] == 0
    # 低端线性爬升：0.2 保持低值，低于区间内
    assert scored.iloc[0] < scored.iloc[1] < scored.iloc[2]
