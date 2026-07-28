"""FastAPI 应用入口"""

import os
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from app.database import init_db
from app.routers.stocks import router as stocks_router
from app.services.scheduler import start_scheduler, shutdown_scheduler, run_full_refresh
from app.config import settings

# 单容器模式下提供前端静态文件服务
_FRONTEND_DIR = os.getenv("FRONTEND_DIR", "")
if _FRONTEND_DIR and os.path.isdir(_FRONTEND_DIR):
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse as _FileResponse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def _initial_refresh():
    """首次启动的延迟刷新——避让 lifespan 阻塞，5s 后开始"""
    await asyncio.sleep(5)
    try:
        await run_full_refresh()
    except Exception as e:
        logger.warning(f"首次刷新未成功，API 已就绪，下次定时刷新或在 5 分钟后可重试: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info("应用启动中……")

    # 确保 data 目录存在
    os.makedirs(settings.data_dir, exist_ok=True)

    # 初始化数据库 + 建表
    await init_db()
    logger.info("数据库初始化完成")

    # 启动调度器（每日 16:30 自动刷新）
    start_scheduler()

    # 后台首次刷新（不阻塞启动）
    asyncio.create_task(_initial_refresh())
    logger.info("首次刷新任务已排入后台（5s 后执行）")

    yield

    # 关闭时
    await shutdown_scheduler()
    logger.info("应用关闭")


app = FastAPI(
    title="A股量化选股系统",
    description="五维因子模型筛选 Top 20 优质 A 股",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(stocks_router, prefix="/api", tags=["股票"])

# 单容器模式：服务前端静态文件（仅在 FRONTEND_DIR 有效时启用）
if _FRONTEND_DIR and os.path.isdir(_FRONTEND_DIR):
    assets_dir = os.path.join(_FRONTEND_DIR, "assets")
    if os.path.isdir(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")
    logger.info("前端静态文件服务已启用: %s", _FRONTEND_DIR)

    @app.get("/{full_path:path}")
    async def _serve_frontend(full_path: str):
        file_path = os.path.join(_FRONTEND_DIR, full_path)
        if full_path and os.path.isfile(file_path):
            return _FileResponse(file_path, headers={"Cache-Control": "public, max-age=3600"})
        return _FileResponse(os.path.join(_FRONTEND_DIR, "index.html"))


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
