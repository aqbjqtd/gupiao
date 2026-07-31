"""五维因子筛选引擎"""

import logging
from typing import List, Dict, Tuple
import pandas as pd
import numpy as np

from app.database import ScreenResult, async_session
from app.config import settings
from sqlalchemy import select

logger = logging.getLogger(__name__)

# 金融行业关键词
FINANCIAL_KEYWORDS = r"银行|证券|保险|信托|期货|租赁|AMC|金融|基金|人保|太保|金租|人寿|财险|再保险|投资保险"

# 因子权重
FACTOR_WEIGHTS = {
    "quality": 0.35,
    "dividend": 0.20,
    "value": 0.20,
    "growth": 0.15,
    "momentum": 0.10,
}

SUB_WEIGHTS = {
    "quality": {"roe": 0.40, "gross_margin": 0.35, "cf_quality": 0.25},
    "dividend": {"dividend_yield": 0.60, "dividend_consistency": 0.40},
    "value": {"pe": 0.50, "pb": 0.30, "ps": 0.20},
    "growth": {"revenue_growth": 0.50, "profit_growth": 0.50},
    "momentum": {"return_60d": 0.60, "turnover_quality": 0.40},
}


def _check_financial(name: str, industry: str) -> bool:
    """检查是否金融股"""
    import re
    if industry and re.search(FINANCIAL_KEYWORDS, str(industry), re.IGNORECASE):
        return True
    if name and re.search(FINANCIAL_KEYWORDS, str(name), re.IGNORECASE):
        return True
    return False


def _check_st(name: str) -> bool:
    """检查是否 ST 股"""
    if name and ("ST" in name.upper() or "*ST" in name.upper()):
        return True
    return False


def _winsorize(series: pd.Series, lower: float = 0.01, upper: float = 0.99) -> pd.Series:
    """缩尾处理（winsorize）：将极端值截断到指定分位数"""
    low_q = series.quantile(lower)
    high_q = series.quantile(upper)
    return series.clip(lower=low_q, upper=high_q)


def _percentile_rank(series: pd.Series) -> pd.Series:
    """百分位排名（0-100），NaN 保持 NaN"""
    if series.dropna().empty:
        return pd.Series(np.nan, index=series.index)
    ranks = series.rank(method="average", pct=True) * 100
    return ranks


def _reverse_percentile_rank(series: pd.Series) -> pd.Series:
    """反向百分位排名（越低越好），0-100"""
    if series.dropna().empty:
        return pd.Series(np.nan, index=series.index)
    ranks = (1 - series.rank(method="average", pct=True)) * 100
    return ranks


def run_screener(spot_df: pd.DataFrame, fin_df: pd.DataFrame,
                 div_df: pd.DataFrame) -> pd.DataFrame:
    """五维选股主流程：合并数据 → 硬过滤 → 评分 → TopN"""
    logger.info("=== 开始五维筛选 ===")

    # ---------- 1. 数据合并 ----------
    # 保留下游需要的列
    spot_cols = ["code", "name", "price", "change_pct", "pe", "pb", "market_cap",
                 "industry", "turnover_rate", "high_60d"]
    spot_df = spot_df[[c for c in spot_cols if c in spot_df.columns]].copy()

    # 财报取最新一期（按报告年份倒序，每组取第一条）
    if "year" in fin_df.columns:
        fin_latest = (
            fin_df.sort_values(["code", "year"], ascending=[True, False])
            .groupby("code").first().reset_index()
        )
    else:
        fin_latest = fin_df.sort_values("code").groupby("code").first().reset_index()
    fin_cols = ["code", "roe", "gross_margin", "revenue_growth",
                "profit_growth", "revenue", "cf_ps"]
    fin_latest = fin_latest[[c for c in fin_cols if c in fin_latest.columns]]

    # 分红数据：取各股年均股息均值
    div_agg = div_df.groupby("code")["avg_dividend_per_10"].mean().reset_index()
    div_agg.rename(columns={"avg_dividend_per_10": "avg_dividend"}, inplace=True)

    # 合并
    merged = spot_df.merge(fin_latest, on="code", how="left")
    merged = merged.merge(div_agg, on="code", how="left")

    # PS = 市值 / 营收（市值单位为亿元，营收单位为元）
    merged["ps"] = merged["market_cap"] * 1e8 / merged["revenue"]
    # 缺失营收数据时回退用 PE 近似（避免估值因子整列 NaN）
    bad_ps = merged["ps"].isna() | np.isinf(merged["ps"])
    merged["ps"] = merged["ps"].where(~bad_ps, merged["pe"])

    # ---------- 2. 硬过滤 ----------
    logger.info("应用硬过滤条件……")
    mask = pd.Series(True, index=merged.index)

    # ST 过滤
    st_mask = merged["name"].apply(lambda x: not _check_st(str(x)))
    mask = mask & st_mask

    # 金融股过滤
    fin_mask = merged.apply(
        lambda r: not _check_financial(str(r.get("name", "")), str(r.get("industry", ""))),
        axis=1
    )
    mask = mask & fin_mask

    # ROE ≥ 5%
    mask = mask & (merged["roe"].fillna(-1) >= settings.min_roe)

    # 股息率计算后过滤
    merged["dividend_yield"] = merged["avg_dividend"].fillna(0) / 10.0 / merged["price"].fillna(1) * 100
    mask = mask & (merged["dividend_yield"] >= settings.min_dividend_yield)

    # 市值 ≥ 50 亿
    mask = mask & (merged["market_cap"].fillna(0) >= settings.min_market_cap)

    filtered = merged[mask].copy()
    logger.info(f"硬过滤后剩余 {len(filtered)} 只股票")

    if filtered.empty:
        logger.warning("硬过滤后无股票剩余！")
        return pd.DataFrame()

    # ---------- 3. 增长率缩尾处理 ----------
    for col in ["revenue_growth", "profit_growth", "roe"]:
        if col in filtered.columns:
            filtered[col] = _winsorize(filtered[col].astype(float))

    # ---------- 4. 计算评分 ----------
    scores = _calculate_scores(filtered)
    filtered["quality_score"] = scores["quality"]
    filtered["dividend_score"] = scores["dividend"]
    filtered["value_score"] = scores["value"]
    filtered["growth_score"] = scores["growth"]
    filtered["momentum_score"] = scores["momentum"]
    filtered["total_score"] = (
        scores["quality"] * FACTOR_WEIGHTS["quality"]
        + scores["dividend"] * FACTOR_WEIGHTS["dividend"]
        + scores["value"] * FACTOR_WEIGHTS["value"]
        + scores["growth"] * FACTOR_WEIGHTS["growth"]
        + scores["momentum"] * FACTOR_WEIGHTS["momentum"]
    )

    # 排序取 Top N
    filtered = filtered.sort_values("total_score", ascending=False).head(settings.top_n).reset_index(drop=True)
    filtered["rank"] = filtered.index + 1

    logger.info(f"筛选完成，Top {len(filtered)} 总评分最高: {filtered.iloc[0]['name']} ({filtered.iloc[0]['total_score']:.1f})")
    return filtered


def _calculate_scores(df: pd.DataFrame) -> Dict[str, pd.Series]:
    """计算五个维度的评分"""
    result = {}

    # ---- 质量评分（越高越好） ----
    roe_score = _percentile_rank(df["roe"].fillna(df["roe"].median()))
    gm_score = _percentile_rank(df["gross_margin"].fillna(df["gross_margin"].median()))
    if df["cf_ps"].notna().any():
        cf_score = _percentile_rank(df["cf_ps"].fillna(df["cf_ps"].median()))
    else:
        # 现金流数据缺失时回退用 ROE 近似
        cf_score = roe_score
    result["quality"] = (roe_score * SUB_WEIGHTS["quality"]["roe"]
                         + gm_score * SUB_WEIGHTS["quality"]["gross_margin"]
                         + cf_score * SUB_WEIGHTS["quality"]["cf_quality"])

    # ---- 分红评分（越高越好） ----
    dy_score = _percentile_rank(df["dividend_yield"].fillna(0))
    div_consistency = _percentile_rank(df["avg_dividend"].fillna(0))
    result["dividend"] = (dy_score * SUB_WEIGHTS["dividend"]["dividend_yield"]
                          + div_consistency * SUB_WEIGHTS["dividend"]["dividend_consistency"])

    # ---- 估值评分（越低越好） ----
    pe_score = _reverse_percentile_rank(df["pe"].clip(upper=df["pe"].quantile(0.95)))
    pb_score = _reverse_percentile_rank(df["pb"].clip(upper=df["pb"].quantile(0.95)))
    ps_col = df["ps"] if df["ps"].notna().any() else df["pe"]
    ps_score = _reverse_percentile_rank(ps_col.clip(upper=ps_col.quantile(0.95)))
    result["value"] = (pe_score * SUB_WEIGHTS["value"]["pe"]
                       + pb_score * SUB_WEIGHTS["value"]["pb"]
                       + ps_score * SUB_WEIGHTS["value"]["ps"])

    # ---- 成长评分（越高越好） ----
    rev_score = _percentile_rank(df["revenue_growth"].fillna(df["revenue_growth"].median()))
    pro_score = _percentile_rank(df["profit_growth"].fillna(df["profit_growth"].median()))
    result["growth"] = (rev_score * SUB_WEIGHTS["growth"]["revenue_growth"]
                        + pro_score * SUB_WEIGHTS["growth"]["profit_growth"])

    # ---- 动量评分 ----
    ret60_score = _percentile_rank(df["high_60d"].fillna(0))
    tr = df["turnover_rate"].fillna(0)
    tr_score = _percentile_rank(
        tr.where((tr >= 0.5) & (tr <= 20), other=tr * 0.5)
    )
    result["momentum"] = (ret60_score * SUB_WEIGHTS["momentum"]["return_60d"]
                          + tr_score * SUB_WEIGHTS["momentum"]["turnover_quality"])

    return result


async def save_results(df: pd.DataFrame):
    """将筛选结果存入数据库"""
    if df.empty:
        return
    async with async_session() as session:
        # 清空旧结果
        from sqlalchemy import delete as sa_delete
        await session.execute(sa_delete(ScreenResult))

        for _, row in df.iterrows():
            record = ScreenResult(
                code=row.get("code", ""),
                name=row.get("name", ""),
                industry=row.get("industry", None),
                price=_safe_float(row.get("price")),
                change_pct=_safe_float(row.get("change_pct")),
                pe=_safe_float(row.get("pe")),
                pb=_safe_float(row.get("pb")),
                roe=_safe_float(row.get("roe")),
                revenue_growth=_safe_float(row.get("revenue_growth")),
                profit_growth=_safe_float(row.get("profit_growth")),
                gross_margin=_safe_float(row.get("gross_margin")),
                dividend_yield=_safe_float(row.get("dividend_yield")),
                market_cap=_safe_float(row.get("market_cap")),
                total_score=_safe_float(row.get("total_score")),
                quality_score=_safe_float(row.get("quality_score")),
                dividend_score=_safe_float(row.get("dividend_score")),
                value_score=_safe_float(row.get("value_score")),
                growth_score=_safe_float(row.get("growth_score")),
                momentum_score=_safe_float(row.get("momentum_score")),
                rank=int(row.get("rank", 0)),
            )
            session.add(record)
        await session.commit()
    logger.info(f"筛选结果已保存 {len(df)} 条记录到数据库")


def _safe_float(val, default=None):
    if val is None:
        return default
    try:
        v = float(val)
        if np.isnan(v) or np.isinf(v):
            return default
        return round(v, 4)
    except (ValueError, TypeError):
        return default
