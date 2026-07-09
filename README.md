# A股量化选股系统

基于五维因子模型的 A 股量化选股全栈项目。

## 技术栈

| 层 | 技术 |
|---|------|
| 后端 | FastAPI + SQLAlchemy async + SQLite |
| 前端 | React 18 + Vite + TypeScript + ECharts |
| 数据源 | 东方财富 (akshare) → 新浪 API 自动降级 |
| 调度 | APScheduler（每日 16:30 自动刷新） |

## 项目结构

```
gupiao/
├── backend/                 # FastAPI 后端
│   ├── app/
│   │   ├── main.py         # 应用入口
│   │   ├── config.py       # 配置（速率限制/重试/过滤参数）
│   │   ├── database.py     # SQLAlchemy 模型
│   │   ├── schemas.py      # Pydantic 响应模型
│   │   ├── routers/
│   │   │   └── stocks.py   # API 路由
│   │   └── services/
│   │       ├── data_fetcher.py  # 双源数据获取（东方财富→新浪降级）
│   │       ├── screener.py      # 五维筛选引擎
│   │       └── scheduler.py     # 定时调度 + 刷新防抖
│   └── requirements.txt
├── frontend/                # React 前端
│   ├── src/
│   │   ├── pages/          # 页面：Home + StockDetail
│   │   ├── components/     # StockTable, KLineChart, StockCard
│   │   ├── api/            # API 封装
│   │   └── styles/         # 深色金融主题 CSS
│   └── package.json
├── docker-compose.yml       # backend(8000) + nginx(80)
├── nginx.conf               # 反代配置：/api/ → backend
└── README.md
```

## 五维因子模型

| 维度 | 权重 | 子因子 |
|------|------|--------|
| **质量** | **35%** | ROE 40% + 毛利率 35% + 经营现金流 25% |
| **分红** | **20%** | 股息率 60% + 分红持续性 40% |
| **估值** | **20%** | PE 50% + PB 30% + PS 20% |
| **成长** | **15%** | 营收增速 50% + 利润增速 50% |
| **动量** | **10%** | 60日涨幅 60% + 换手率质量 40% |

**硬过滤条件：** ROE≥5%, 股息率≥0.3%, 市值≥50亿, 排除ST/*ST, 排除金融股

## 快速开始

### Docker Compose（推荐）

```bash
docker compose up --build
# 首次启动等待 5-7 分钟自动拉取数据
```

前端: http://localhost:80（自动轮询等待数据就绪）
后端: http://localhost:8000

### 本地开发

```bash
# 后端
cd backend
uv venv --python 3.11
source .venv/bin/activate
uv pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# 前端（另一终端）
cd frontend
npm install
npm run dev
```

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| GET | `/api/stocks` | Top 20 筛选结果（含五维评分） |
| GET | `/api/stocks/{code}` | 个股详情 |
| GET | `/api/stocks/{code}/kline?months=12` | 前复权 K 线（支持 6/12/24/60月） |
| GET | `/api/stocks/{code}/financial` | 财务数据 |
| POST | `/api/refresh` | 手动触发刷新 |
| GET | `/api/refresh/status` | 刷新状态 |

## 数据源策略

| 数据 | 主源 | 降级 |
|------|------|------|
| 实时行情 | 东方财富 (akshare) | → 新浪 API 直连 |
| 财报 | 东方财富 (akshare stock_yjbb_em) | → 缓存兜底 |
| 分红 | 东方财富 (akshare stock_history_dividend) | — |
| K 线 | 东方财富前复权 (adjust='qfq') | → 新浪日K |

- 调用间隔 ≥ 3s + 随机 0~3s 抖动
- 失败后指数退避重试（5s → 10s → 20s → 40s → 80s）
- 全流程异常隔离：单源失败不影响整体

## 注意事项

- 分红数据 `年均股息` 单位是 **元/10股**，计算股息率需除以 10
- 所有股票代码自动补零至 6 位
- K 线使用前复权（东方财富）/ 近似前复权（新浪降级）
- 新浪源缺少行业字段（`industry: null`），金融股过滤依赖名称关键词
- 金融过滤关键词：银行|证券|保险|信托|期货|租赁|AMC|金融|基金|人保|太保|金租|人寿

## 免责声明

本系统仅供参考学习，不构成任何投资建议。股市有风险，投资需谨慎。
