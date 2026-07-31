"""速率限制与指数退避工具的单元测试（纯函数部分，不触碰网络）。"""

import pytest

from app.services.rate_limit import backoff_cap, rate_limit_wait


def test_rate_limit_wait_zero_when_no_recent_calls():
    assert rate_limit_wait({}, now=1000.0, min_interval=3.0) == 0.0
    # 上次调用在间隔之外
    assert rate_limit_wait({"a": 990.0}, now=1000.0, min_interval=3.0) == 0.0


def test_rate_limit_wait_global_coordination():
    """所有 endpoint 全局协调：取最大的剩余等待时间。"""
    # a 在 1s 前调用（还需等 2s），b 在 0.5s 前调用（还需等 2.5s）→ 2.5s
    wait = rate_limit_wait({"a": 999.0, "b": 999.5}, now=1000.0, min_interval=3.0)
    assert wait == pytest.approx(2.5)


def test_rate_limit_wait_never_negative():
    assert rate_limit_wait({"a": 999.9}, now=1000.0, min_interval=3.0) >= 0.0
    assert rate_limit_wait({"a": 990.0}, now=1000.0, min_interval=3.0) == 0.0


def test_backoff_cap_sequence():
    assert backoff_cap(1, 5.0, 120.0) == 5.0
    assert backoff_cap(2, 5.0, 120.0) == 10.0
    assert backoff_cap(3, 5.0, 120.0) == 20.0
    assert backoff_cap(4, 5.0, 120.0) == 40.0
    assert backoff_cap(5, 5.0, 120.0) == 80.0


def test_backoff_cap_ceiling():
    """退避上限封顶，不会无限翻倍。"""
    assert backoff_cap(6, 5.0, 120.0) == 120.0
    assert backoff_cap(10, 5.0, 120.0) == 120.0
