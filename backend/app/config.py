"""应用配置（pydantic-settings）"""

from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """应用配置，从环境变量/.env 文件加载"""

    # 数据库
    database_url: str = "sqlite+aiosqlite:///./data/gupiao.db"
    data_dir: str = "./data"

    # 缓存有效期（秒）
    cache_ttl_spot: int = 14400        # 行情 4 小时（双源+腾讯三源降级，短 TTL 安全）
    cache_ttl_financial: int = 604800  # 财报 7 天（季度数据，长缓存降低东财依赖/封禁风险）
    cache_ttl_dividend: int = 2592000  # 分红 30 天（年度数据）

    # akshare 调用间隔（秒）—— 基础值 3s，实际加 0-3s 随机抖动（最终 3-6s）
    # 东方财富源有严格的速率限制，间隔过低会被断开连接
    akshare_interval: float = 3.0
    akshare_interval_jitter: float = 3.0  # 随机抖动范围 0~3s

    # 重试参数——指数退避重试
    retry_max_attempts: int = 5       # 最大重试次数
    retry_base_delay: float = 5.0     # 指数退避基础延迟（秒）：5, 10, 20, 40, 80
    retry_max_delay: float = 120.0    # 退避上限（秒）

    # 连接超时
    akshare_timeout: int = 120        # 单次 akshare 调用超时（秒）

    # 硬过滤参数
    min_roe: float = 5.0           # 最小 ROE (%)
    min_dividend_yield: float = 0.3  # 最小股息率 (%)
    min_market_cap: float = 50.0   # 最小市值（亿元）
    top_n: int = 20                # 返回 Top N

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
