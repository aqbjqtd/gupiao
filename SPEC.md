# gupiao — A股量化选股全栈项目

## 项目概述

从 A 股 5000+ 只股票中，通过多因子量化模型筛选出 Top 20 优质股，提供可视化展示 + 前复权 K 线详情。

## 技术栈

| 层 | 技术 | 理由 |
|---|------|------|
| 后端 | FastAPI + Python 3.11 | 数据获取层原生 Python，FastAPI async 高效 |
| 前端 | React 18 + Vite + TypeScript | 数据可视化生态好，ECharts 集成成熟 |
| 图表 | Apache ECharts | 金融 K 线图业界标准 |
| 数据库 | SQLite (aiosqlite) | 零运维，单机够用 |
| 调度 | APScheduler | 每日收盘后自动刷新数据 |
| 数据获取 | akshare（接入东方财富）→ 新浪 API 自动降级 | 双源保障稳定性 |

## 多因子选股策略（五维模型）

专为普通股民设计，质量+分红占 55% 权重，确保选出的都是好公司且有现金回报：

| 维度 | 权重 | 子因子 | 评分方向 |
|------|------|--------|----------|
| **质量** | **35%** | ROE 40% + 毛利率 35% + 经营现金流 25% | 越高越好 |
| **分红** | **20%** | 股息率 60% + 分红持续性 40% | 越高越好 |
| **估值** | **20%** | PE 50% + PB 30% + PS 20% | 越低越好 |
| **成长** | **15%** | 营收增速 50% + 利润增速 50% | 越高越好 |
| **动量** | **10%** | 60日涨幅 60% + 换手率质量 40% | 涨幅高好/换手适中好 |

**硬过滤条件：**
- ROE ≥ 5%（排除不赚钱公司）
- 股息率 ≥ 0.3%（排除铁公鸡）
- 总市值 ≥ 50亿（排除小市值妖股）
- 排除 ST / *ST 股
- 排除金融股（名称关键词过滤）

**前复权处理：** K 线图使用前复权价格（东方财富 qfq）/ 新浪日K降级

## 数据源架构

```
fetch_spot_data()
├─ [主源] ak.stock_zh_a_spot_em() 接入东方财富
│    └─ 失败 → 日志记录
├─ [降级] Sina API 直连（vf stock.finance.sina.com.cn）
│    └─ 5528只股票，含PE/PB/市值/换手率
└─ [兜底] 过期缓存

fetch_kline_data(code)
├─ [主源] ak.stock_zh_a_hist(adjust='qfq') 前复权
│    └─ 失败一次 → 立即降级
└─ [降级] Sina CN_MarketData.getKLineData(scale=240)
     └─ 日K线，含MA5/MA10/MA30

fetch_financial_data()
└─ ak.stock_yjbb_em() 财报（含重试）

fetch_dividend_data()
└─ ak.stock_history_dividend() 分红（含重试）
```

## 速率限制与重试

- 基础间隔：3s + 随机 0~3s 抖动（有效间隔 3~6s）
- 指数退避：5s → 10s → 20s → 40s → 80s（上限 120s）
- 最大重试：5 次（全抖动退避）
- 全流程防抖：两次全刷新至少间隔 5 分钟
- 超时保护：120s

## 已知限制

- 新浪源降级时 `industry` 字段为 null（金融股过滤依赖名称关键词匹配）
- 新浪源降级时 `high_60d` 为 null（动量因子中的60日涨幅不评分）
- 新浪K线为未复权数据，非严格前复权

## 项目结构

```
~/z-my-project/gupiao/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py              # FastAPI 入口 + CORS + 生命周期
│   │   ├── config.py            # Settings (pydantic-settings)
│   │   ├── database.py          # SQLAlchemy async engine + models
│   │   ├── schemas.py           # Pydantic 请求/响应模型
│   │   ├── routers/
│   │   │   ├── __init__.py
│   │   │   └── stocks.py        # /api/stocks 路由
│   │   └── services/
│   │       ├── __init__.py
│   │       ├── data_fetcher.py  # 双源数据获取（akshare→新浪）+ 重试
│   │       ├── screener.py      # 五维因子计算 + 评分 + 筛选
│   │       └── scheduler.py     # APScheduler + 防抖
│   ├── requirements.txt
│   ├── Dockerfile
│   ├── .env
│   └── .gitignore
├── frontend/
│   ├── src/
│   │   ├── App.tsx
│   │   ├── main.tsx
│   │   ├── pages/
│   │   │   ├── Home.tsx             # Top 20 列表页
│   │   │   └── StockDetail.tsx      # 个股详情 + K 线
│   │   ├── components/
│   │   │   ├── StockTable.tsx       # 筛选结果表格
│   │   │   ├── KLineChart.tsx       # 前复权 K 线图 (ECharts)
│   │   │   ├── StockCard.tsx        # 概览卡片
│   │   │   └── Layout.tsx           # 布局框架
│   │   ├── api/
│   │   │   └── stocks.ts            # API 调用封装
│   │   └── styles/
│   │       └── index.css
│   ├── dist/                      # 构建产物
│   ├── package.json
│   └── vite.config.ts
├── docker-compose.yml       # 单容器部署（默认）
├── Dockerfile.allinone      # 多阶段构建（前端+后端合并）
├── SPEC.md
└── README.md
```

## API 路由设计

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| GET | `/api/stocks` | 获取 Top 20 筛选结果（含评分详情） |
| GET | `/api/stocks/{code}` | 个股详情页数据 |
| GET | `/api/stocks/{code}/kline?months=12` | 前复权 K 线数据（支持 6/12/24/60） |
| GET | `/api/stocks/{code}/financial` | 财务数据 |
| POST | `/api/refresh` | 手动触发数据刷新 |
| GET | `/api/refresh/status` | 刷新状态 |

## K线返回格式（数组格式）

```json
{
  "code": "601083",
  "name": "锦江航运",
  "adj_type": "前复权",
  "data": [
    {"date": "2026-01-07", "open": 11.45, "high": 11.52,
     "low": 11.39, "close": 11.41, "volume": 7182514,
     "ma5": 11.27, "ma20": 11.354, "ma60": 11.328},
    ...
  ]
}
```

## 前端页面设计

### 设计风格
- **风格**：深色金融主题，金色(#F0B90B)为主色，黑底深灰
- **字体**：Noto Sans SC + JetBrains Mono（数字）
- **签名元素**：K 线图十字光标 + 表格行 hover 发光效果

### 页面 1：首页（Top 20 筛选结果）
- 顶部：标题 + 上次更新时间 + 刷新按钮
- 表格：排名/代码/名称/行业/现价/涨跌幅/PE/PB/ROE/营收增速/利润增速/股息率/评分
- 评分色条、点击跳转详情、按列排序

### 页面 2：个股详情页
- 概览卡片 + 前复权 K 线图（MA5/20/60 + 成交量 + 时间切换）
- 五维评分雷达图
- 财务数据历史表

## 调度策略

- 每日 11:30 午盘 + 14:00 午后自动刷新（APScheduler）
- 启动时 5s 后后台首次刷新（不阻塞启动）
- 缓存有效期：行情 4h、财报 24h、分红 24h
- 两次全刷新最小间隔 5 分钟（防抖）
- POST /api/refresh 手动触发（异步）

## 部署方式

```bash
docker compose up --build
# 首次启动等待 5-7 分钟数据同步
```

访问 http://localhost:18080（默认端口）

## 验收结果（已通过）

- ✅ `docker compose up` 启动无报错
- ✅ `/api/health` 返回 200
- ✅ `/api/stocks` 返回 20 只股票数据（评分 0-100）
- ✅ `/api/stocks/{code}/kline` 返回 K 线数据（含 MA5/20/60）
- ✅ 全流程：启动 → 自动刷新 → API 就绪 → K 线图数据
- ✅ 费率限制：间隔 ≥3s + 抖动 0~3s
- ✅ 降级机制：akshare 失败 → 新浪自动降级
- ✅ 单容器部署：host:18080 → container:8000（前后端合一）
