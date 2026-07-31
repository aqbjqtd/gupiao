# A股量化选股系统

基于五维因子模型的 A 股量化选股全栈项目。

## 技术栈

| 层 | 技术 |
|---|------|
| 后端 | FastAPI + SQLAlchemy async + SQLite |
| 前端 | React 18 + Vite + TypeScript + ECharts |
| 数据获取 | akshare（接入东方财富）→ 新浪 API 自动降级 |
| 调度 | APScheduler（工作日 11:30 午盘 + 14:00 午后刷新） |

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
│   │       ├── data_fetcher.py  # 行情/财报/分红抓取（akshare→新浪降级）
│   │       ├── kline.py         # 前复权 K 线 + 内存缓存
│   │       ├── screener.py      # 五维筛选引擎
│   │       ├── scheduler.py     # 定时调度 + 刷新防抖
│   │       ├── cache.py         # SQLite 缓存读写
│   │       ├── rate_limit.py    # 限速 + 指数退避重试
│   │       └── numeric.py       # 数值清洗（NaN/Inf 安全）
│   ├── tests/                 # pytest 单元测试
│   └── requirements.txt
├── frontend/                # React 前端
│   ├── src/
│   │   ├── pages/          # 页面：Home + StockDetail
│   │   ├── components/     # StockTable, KLineChart, StockCard
│   │   ├── api/            # API 封装
│   │   ├── lib/            # echarts 按需注册
│   │   └── styles/         # 深色金融主题 CSS
│   └── package.json
├── docker-compose.yml       # 单容器部署（默认）
├── Dockerfile.allinone      # 多阶段构建（前端+后端合并）
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

## 投资风格：中长期持仓（1-6个月）

五维因子权重分布决定了本系统的投资风格：

| 维度 | 权重 | 属性 | 适合周期 |
|------|------|------|----------|
| **质量** | 35% | ROE/毛利率/现金流 | 长期 |
| **分红** | 20% | 股息率/持续性 | 长期 |
| **估值** | 20% | PE/PB/PS | 中长期 |
| **成长** | 15% | 营收/利润增速 | 中期 |
| **动量** | 10% | 60日涨幅/换手率 | 短期 |

**结论：75% 权重（质量+分红+估值）是典型价值投资因子，适合选好股票拿几周到几个月。**

> 如需短线交易，建议调整权重：动量提到30-40%，加入技术指标（MACD/KDJ/布林带），缩短数据周期（日线→分钟线）。

## 快速开始

### 单容器部署（推荐，VPS 友好）

```bash
docker compose up --build
# 首次启动等待 5-7 分钟自动拉取数据
```

访问 http://localhost:18080（默认端口）

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

### 运行测试

```bash
cd backend
uv pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| GET | `/api/stocks` | Top 20 筛选结果（含五维评分） |
| GET | `/api/stocks/{code}` | 个股详情 |
| GET | `/api/stocks/{code}/kline?months=12` | 前复权 K 线（支持 6/12/24/60月） |
| GET | `/api/stocks/{code}/financial` | 财务数据 |
| GET | `/api/refresh/status` | 刷新状态 |

## 数据源策略

| 数据 | 获取方式 | 降级 |
|------|----------|------|
| 实时行情 | akshare（接入东方财富） | → 新浪 API 直连 |
| 财报 | akshare（接入东方财富） | → 缓存兜底 |
| 分红 | akshare（接入东方财富） | — |
| K 线 | akshare 前复权（adjust='qfq'） | → 新浪日K |

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
