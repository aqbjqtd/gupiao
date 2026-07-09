"""APScheduler 定时任务调度"""

import time
import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import settings
from app.services.data_fetcher import fetch_spot_data, fetch_financial_data, fetch_dividend_data
from app.services.screener import run_screener, save_results

logger = logging.getLogger(__name__)

# 全局调度器
scheduler = AsyncIOScheduler()

# 刷新状态
_refresh_status: dict = {
    "is_running": False,
    "last_refresh": None,
    "message": "",
}
# 防抖：两次全刷新之间至少间隔 5 分钟
_last_full_attempt: float = 0.0
_MIN_REFRESH_COOLDOWN = 300  # 5 秒改成 300 秒（5 分钟）


async def run_full_refresh():
    """执行完整数据刷新：行情 → 财报 → 分红 → 筛选"""
    global _refresh_status, _last_full_attempt
    if _refresh_status["is_running"]:
        logger.warning("刷新任务已在运行，跳过")
        return

    # 防抖：距上次全量刷新不足 5 分钟则跳过
    now = time.monotonic()
    if now - _last_full_attempt < _MIN_REFRESH_COOLDOWN:
        remaining = int(_MIN_REFRESH_COOLDOWN - (now - _last_full_attempt))
        logger.warning(f"距上次刷新仅 {remaining}s，跳过（冷却期 {_MIN_REFRESH_COOLDOWN}s）")
        _refresh_status["message"] = f"冷却中（{remaining}s 后可重试）"
        return

    _last_full_attempt = now
    _refresh_status["is_running"] = True
    _refresh_status["message"] = "正在获取数据……"
    logger.info("=== 开始自动数据刷新 ===")

    try:
        # 1. 获取实时行情（每日必拉，收盘后价格已变）
        spot_df = await fetch_spot_data(force=True)
        if spot_df is None or spot_df.empty:
            _refresh_status["message"] = "获取行情失败"
            return

        # 2. 财报（季度数据，缓存未过期则不重复拉取）
        fin_df = await fetch_financial_data(force=False)
        if fin_df is None or fin_df.empty:
            _refresh_status["message"] = "获取财报失败"
            return

        # 3. 分红（年度数据，缓存未过期则不重复拉取）
        div_df = await fetch_dividend_data(force=False)
        if div_df is None or div_df.empty:
            _refresh_status["message"] = "获取分红失败"
            return

        # 4. 运行五维筛选
        _refresh_status["message"] = "正在计算因子评分……"
        result = run_screener(spot_df, fin_df, div_df)

        # 5. 保存结果
        await save_results(result)
        _refresh_status["last_refresh"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _refresh_status["message"] = "刷新完成"

        logger.info(f"=== 数据刷新完成，共筛选 {len(result)} 只股票 ===")
    except Exception as e:
        logger.error(f"刷新失败: {e}", exc_info=True)
        _refresh_status["message"] = f"刷新失败: {str(e)}"
    finally:
        _refresh_status["is_running"] = False


def start_scheduler():
    """启动 APScheduler"""
    # 每日 16:30 自动刷新
    scheduler.add_job(
        run_full_refresh,
        CronTrigger(hour=settings.refresh_hour, minute=settings.refresh_minute),
        id="daily_refresh",
        replace_existing=True,
    )
    logger.info(f"定时任务已注册：每日 {settings.refresh_hour}:{settings.refresh_minute:02d} 刷新")

    # 启动前检查是否有缓存，无缓存则立即执行首次刷新
    scheduler.start()
    logger.info("调度器已启动")


async def shutdown_scheduler():
    """关闭调度器"""
    scheduler.shutdown(wait=False)


def get_refresh_status() -> dict:
    """获取刷新状态"""
    return _refresh_status.copy()
