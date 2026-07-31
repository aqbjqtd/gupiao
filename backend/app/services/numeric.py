"""数值清洗工具：NaN/Inf → None，保证 JSON 合法。"""

from typing import Optional


def safe_float(val, default=None):
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


def clean_float(val) -> Optional[float]:
    """转换为 float，NaN/Inf → None，保留 4 位小数（JSON 安全）。"""
    try:
        v = float(val)
        if v != v or v == float("inf") or v == float("-inf"):
            return None
        return round(v, 4)
    except (ValueError, TypeError):
        return None
