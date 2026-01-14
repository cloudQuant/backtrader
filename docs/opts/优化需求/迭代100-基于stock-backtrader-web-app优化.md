### 背景
backtrader已经比较完善了，我想要借鉴量化投资框架中其他项目的优势，继续改进优化backtrader。
### 任务
1. 阅读研究分析backtrader这个项目的源代码，了解这个项目。
2. 阅读研究分析/Users/yunjinqi/Documents/量化交易框架/stock-backtrader-web-app
3. 借鉴这个新项目的优点和功能，给backtrader优化改进提供新的建议
4. 写需规文档和设计文档放到这个文档的最下面，方便后续借鉴

### stock-backtrader-web-app项目简介
stock-backtrader-web-app是一个基于backtrader的股票回测Web应用，具有以下核心特点：
- **Web应用**: 基于Streamlit构建的交互式Web界面
- **股票回测**: 集成Backtrader进行策略回测
- **可视化**: 使用Pyecharts生成专业K线图和回测结果图表
- **数据获取**: 集成AkShare获取A股实时数据
- **策略配置化**: YAML配置策略参数，动态加载
- **缓存优化**: 使用Streamlit缓存装饰器优化性能

### 项目实际架构分析

**目录结构**:
```
stock-backtrader-web-app/
├── web/                      # Streamlit页面
│   ├── backtraderpage.py    # 回测页面 (91行)
│   ├── stockpage.py         # 股票分析页面
│   └── menu.py              # 菜单管理
├── internal/                 # 业务逻辑层
│   ├── service/
│   │   ├── backtraderservice.py  # 回测服务 (101行) ⭐核心
│   │   ├── akshareservice.py     # 数据服务
│   │   └── etfservice.py         # ETF服务
│   ├── pkg/
│   │   ├── charts/          # 图表组件
│   │   │   ├── stock.py     # K线图 (182行) ⭐重点借鉴
│   │   │   └── results.py   # 结果图表
│   │   ├── strategy/        # 策略实现
│   │   │   ├── base.py      # 策略基类
│   │   │   ├── macross.py   # 双均线策略
│   │   │   └── rsi.py       # RSI策略
│   │   └── frames/          # UI组件
│   └── domain/
│       └── schemas.py       # Pydantic数据模型
├── core/                     # 核心库
│   ├── factors/             # 因子/策略库 (29个文件)
│   │   ├── algorithm.py     # 技术指标算法
│   │   ├── ma/              # 均线因子
│   │   └── macd/            # MACD因子
│   ├── db/                  # 数据库管理
│   └── config/              # 配置管理
└── config/
    └── strategy.yaml        # 策略配置文件
```

### 核心代码亮点分析

**1. 回测服务封装** (`internal/service/backtraderservice.py`):
```python
@st.cache_data(hash_funcs={StrategyBase: model_hash_func})
def run_backtrader(stock_df: pd.DataFrame, strategy: StrategyBase, bt_params: BacktraderParams) -> pd.DataFrame:
    """运行回测 - 带缓存优化"""
    cerebro = bt.Cerebro()
    cerebro.adddata(bt.feeds.PandasData(dataname=stock_df, ...))
    cerebro.broker.setcash(bt_params.start_cash)
    cerebro.broker.setcommission(commission=bt_params.commission_fee)
    
    # 添加分析器
    cerebro.addanalyzer(btanalyzers.SharpeRatio, _name="sharpe")
    cerebro.addanalyzer(btanalyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(btanalyzers.Returns, _name="returns")
    
    # 动态导入策略
    strategy_cli = getattr(__import__("strategy"), f"{strategy.name}Strategy")
    cerebro.optstrategy(strategy_cli, **strategy.params)
    
    return cerebro.run()
```

**2. 专业K线图** (`internal/pkg/charts/stock.py`):
- K线+MA均线叠加
- 成交量分离显示
- DataZoom缩放支持
- 十字线联动

**3. 策略基类模式** (`internal/pkg/strategy/macross.py`):
```python
class MaCrossStrategy(BaseStrategy):
    params = (("fast_length", 10), ("slow_length", 50))
    
    def __init__(self):
        ma_fast = bt.ind.SMA(period=self.params.fast_length)
        ma_slow = bt.ind.SMA(period=self.params.slow_length)
        self.crossover = bt.ind.CrossOver(ma_fast, ma_slow)
```

### 重点借鉴方向
1. **缓存机制**: Redis缓存 + 本地缓存双层架构
2. **专业图表**: Echarts K线+均线+成交量组合Grid布局
3. **策略YAML配置**: 参数外部化，动态加载
4. **Pydantic数据模型**: 类型安全的请求/响应模型
5. **服务层封装**: 将Cerebro操作封装为可复用服务
6. **动态策略导入**: `getattr(__import__())`模式

---

## 技术栈规划 (行业最佳实践)

### 前端技术栈

| 技术 | 版本 | 用途 | 说明 |
|------|------|------|------|
| **Vue 3** | 3.4+ | 前端框架 | Composition API, 响应式系统 |
| **TypeScript** | 5.0+ | 类型系统 | 类型安全，IDE支持 |
| **Vite** | 5.0+ | 构建工具 | 快速HMR，ES模块 |
| **Pinia** | 2.1+ | 状态管理 | Vue3官方推荐 |
| **Vue Router** | 4.2+ | 路由管理 | 前端路由 |
| **Echarts** | 5.5+ | 图表库 | K线图、资金曲线 |
| **Element Plus** | 2.5+ | UI组件库 | 表单、表格、对话框 |
| **Axios** | 1.6+ | HTTP客户端 | API请求 |
| **TailwindCSS** | 3.4+ | CSS框架 | 原子化CSS |
| **VueUse** | 10.0+ | 工具库 | 常用Composition函数 |

### 后端技术栈

| 技术 | 版本 | 用途 | 说明 |
|------|------|------|------|
| **FastAPI** | 0.109+ | Web框架 | 高性能异步框架 |
| **Uvicorn** | 0.27+ | ASGI服务器 | 生产级服务器 |
| **Pydantic** | 2.6+ | 数据验证 | 模型验证、序列化 |
| **SQLAlchemy** | 2.0+ | ORM | 关系数据库映射 |
| **Celery** | 5.3+ | 任务队列 | 异步回测任务 |
| **Redis** | 5.0+ | 缓存/消息 | 缓存、Celery Broker |
| **Alembic** | 1.13+ | 数据库迁移 | Schema版本管理 |
| **Python-Jose** | 3.3+ | JWT | 用户认证 |
| **Passlib** | 1.7+ | 密码加密 | bcrypt哈希 |
| **Loguru** | 0.7+ | 日志 | 结构化日志 |
| **Pytest** | 8.0+ | 测试框架 | 单元测试、集成测试 |

### 数据库技术栈

| 数据库 | 版本 | 用途 | 数据类型 |
|--------|------|------|---------|
| **PostgreSQL** | 16+ | 主数据库 | 用户、策略、回测记录 |
| **MySQL** | 8.0+ | 备选主库 | 兼容已有系统 |
| **MongoDB** | 7.0+ | 文档存储 | 策略代码、回测详情 |
| **Redis** | 7.2+ | 缓存/队列 | 会话、缓存、任务队列 |
| **DolphinDB** | 2.0+ | 时序数据库 | 行情数据、Tick数据 |
| **ClickHouse** | 24.1+ | 分析数据库 | 交易记录、统计分析 |

### 基础设施

| 技术 | 用途 | 说明 |
|------|------|------|
| **Docker** | 容器化 | 开发/生产环境一致性 |
| **Docker Compose** | 编排 | 本地多服务编排 |
| **Nginx** | 反向代理 | 负载均衡、静态资源 |
| **MinIO** | 对象存储 | 回测报告、图表文件 |
| **Prometheus** | 监控 | 指标采集 |
| **Grafana** | 可视化 | 监控面板 |

---

## 架构对比分析

### Backtrader 核心特点

**优势:**
1. **成熟的回测引擎**: Cerebro统一管理策略、数据、经纪商、分析器
2. **完整的策略系统**: 灵活的Strategy基类
3. **丰富的指标库**: 60+内置技术指标
4. **Python原生**: 纯Python实现，易于集成

**局限:**
1. **命令行界面**: 主要通过脚本运行，缺少可视化界面
2. **无Web服务**: 没有内置的Web服务能力
3. **无用户系统**: 缺少用户认证和权限管理
4. **无持久化**: 回测结果无法自动保存
5. **无策略管理**: 缺少策略库管理和分享功能
6. **无协作功能**: 无法多人协作使用

### Stock-Backtrader-Web-App 核心特点

**优势:**
1. **双模式架构**: Streamlit Web界面 + FastAPI RESTful API
2. **分层设计**: 清晰的Web/API/Service/Repository四层架构
3. **可视化丰富**: Pyecharts专业图表、K线图、回测结果图
4. **策略配置化**: YAML配置策略参数，动态加载
5. **数据持久化**: 多数据库支持（MySQL/PostgreSQL/SQLite）
6. **缓存优化**: Streamlit缓存装饰器优化性能
7. **模块化设计**: 策略、图表、服务独立模块
8. **实时数据**: 集成AkShare获取A股实时数据
9. **参数优化**: 内置策略参数优化功能
10. **插件化扩展**: 易于添加新策略和功能

**局限:**
1. **依赖AkShare**: 数据源受限于A股市场
2. **单机部署**: 缺少分布式部署支持
3. **认证简陋**: 缺少完善的用户认证系统
4. **文档不足**: 缺少详细的开发文档
5. **无异步支持**: 回测任务同步执行，可能阻塞UI

---

## 核心借鉴价值总结

| 借鉴点 | 源码位置 | backtrader集成方案 | 优先级 |
|--------|---------|-------------------|--------|
| Vue3前端 | - | 新增`bt-web-ui`前端项目 | P0 |
| Echarts K线 | 参考`charts/stock.py` | 新增Vue组件库 | P0 |
| FastAPI后端 | - | 新增`bt.web.api`模块 | P0 |
| 多数据库支持 | - | 新增`bt.db`抽象层 | P0 |
| 策略YAML配置 | `config/strategy.yaml` | 扩展`bt.Strategy`支持配置 | P1 |
| Pydantic模型 | `domain/schemas.py` | 新增`bt.schemas`模块 | P1 |
| Celery异步 | - | 新增`bt.tasks`模块 | P1 |
| Redis缓存 | - | 新增`bt.cache`模块 | P2 |

---

## 需求规格文档

### 1. Web服务架构 (优先级: 高)

**需求描述:**
为Backtrader构建前后端分离的Web服务，前端Vue3 + 后端FastAPI架构。

**功能需求:**
1. **Vue3前端**: SPA单页应用，响应式设计
2. **FastAPI后端**: RESTful API + WebSocket实时推送
3. **前后端分离**: 独立部署，API版本管理
4. **异步处理**: Celery + Redis任务队列
5. **实时通知**: WebSocket推送回测进度
6. **多级缓存**: Redis缓存 + 本地缓存

**技术实现:**
```
前端 (Vue3)                    后端 (FastAPI)
┌─────────────┐              ┌─────────────────┐
│  Vue3 App   │──HTTP/WS───▶│  FastAPI App    │
│  + Echarts  │              │  + Pydantic     │
│  + Pinia    │              │  + SQLAlchemy   │
└─────────────┘              └────────┬────────┘
                                      │
                    ┌─────────────────┼─────────────────┐
                    ▼                 ▼                 ▼
              ┌─────────┐      ┌─────────┐      ┌─────────┐
              │  Redis  │      │Celery   │      │ 多DB    │
              │ 缓存    │      │Worker   │      │ 抽象层  │
              └─────────┘      └─────────┘      └─────────┘
```

**非功能需求:**
1. API响应时间P99 < 200ms
2. 支持并发用户 > 100
3. WebSocket连接稳定
4. 前端首屏加载 < 2s

### 2. 可视化系统 (优先级: 高)

**需求描述:**
基于Echarts构建专业金融图表组件库。

**功能需求:**
1. **K线图表**: 专业K线 + MA/BOLL/MACD叠加
2. **指标图表**: 技术指标独立图表
3. **资金曲线**: 权益曲线 + 回撤曲线
4. **交易信号**: 买卖点标记、止损止盈线
5. **性能图表**: 月度收益热力图、收益分布直方图
6. **交互功能**: DataZoom缩放、十字线联动、Tooltip详情

**Echarts组件设计:**
```typescript
// Vue3 Echarts组件
<KlineChart
  :data="ohlcvData"
  :indicators="['MA5', 'MA20', 'BOLL']"
  :signals="tradeSignals"
  :height="600"
  @range-change="handleRangeChange"
/>

<EquityCurve
  :equity="equityData"
  :drawdown="drawdownData"
  :benchmark="benchmarkData"
/>
```

**非功能需求:**
1. 100万根K线流畅渲染
2. 图表响应式适配
3. 支持主题切换

### 3. 策略管理系统 (优先级: 高)

**需求描述:**
建立策略库管理系统，支持策略的保存、加载和分享。

**功能需求:**
1. **策略保存**: 将策略代码和参数保存到数据库
2. **策略加载**: 从数据库加载策略
3. **策略分类**: 按类型分类管理策略
4. **策略分享**: 策略分享给其他用户
5. **策略版本**: 策略版本管理
6. **策略模板**: 提供常用策略模板

**非功能需求:**
1. 策略代码安全存储
2. 支持策略导入导出

### 4. 数据库持久化 (优先级: 高)

**需求描述:**
建立统一数据库抽象层，通过环境变量配置选择数据库类型，**单一数据库即可启动项目**，可选配置多数据库优化性能。

**设计原则:**
1. **统一接口**: 所有数据库操作通过统一Repository接口
2. **单库可用**: 默认使用一个数据库存储所有数据，快速启动
3. **可选优化**: 高级用户可配置不同数据库优化特定场景
4. **零侵入切换**: 切换数据库只需修改环境变量

**功能需求:**
1. **数据库抽象层**: 统一Repository接口，屏蔽底层差异
2. **环境变量配置**: 通过`.env`文件配置数据库类型
3. **连接池管理**: SQLAlchemy/Motor连接池
4. **数据迁移**: Alembic Schema管理
5. **可选缓存**: Redis缓存层（非必须）

**配置示例 (.env):**
```bash
# .env - 最简配置 (单数据库启动)
DATABASE_TYPE=postgresql          # 可选: postgresql, mysql, mongodb, sqlite
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/backtrader

# 可选: Redis缓存 (不配置则使用内存缓存)
# REDIS_URL=redis://localhost:6379/0

# 可选: Celery异步任务 (不配置则同步执行)
# CELERY_BROKER_URL=redis://localhost:6379/1
```

```bash
# .env - 高级配置 (多数据库优化性能)
DATABASE_TYPE=postgresql
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/backtrader

# 可选: 文档数据库 (存储回测详情、策略代码等大文档)
DOCUMENT_DB_TYPE=mongodb
DOCUMENT_DB_URL=mongodb://localhost:27017/backtrader

# 可选: 时序数据库 (存储行情数据，高性能查询)
TIMESERIES_DB_TYPE=dolphindb
TIMESERIES_DB_HOST=localhost
TIMESERIES_DB_PORT=8848

# 可选: 缓存
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/1
```

**支持的数据库:**

| 数据库 | DATABASE_TYPE | 适用场景 | 依赖包 |
|-------|---------------|---------|--------|
| PostgreSQL | `postgresql` | 推荐默认，功能全面 | `asyncpg` |
| MySQL | `mysql` | 广泛使用 | `aiomysql` |
| SQLite | `sqlite` | 开发测试，无需安装 | `aiosqlite` |
| MongoDB | `mongodb` | 文档存储（可选） | `motor` |
| DolphinDB | `dolphindb` | 时序数据（可选） | `dolphindb` |

**非功能需求:**
1. SQLite模式零配置启动
2. 数据库切换无需改代码
3. 连接池自动管理

### 5. 用户认证系统 (优先级: 中)

**需求描述:**
建立用户认证和权限管理系统。

**功能需求:**
1. **用户注册**: 新用户注册
2. **用户登录**: 用户登录认证
3. **权限管理**: 基于角色的权限控制
4. **API密钥**: API密钥管理
5. **操作日志**: 用户操作日志记录
6. **密码安全**: 密码加密存储

**非功能需求:**
1. 符合安全规范
2. 防止暴力破解

### 6. 参数优化系统 (优先级: 中)

**需求描述:**
建立策略参数优化系统，支持自动寻找最优参数。

**功能需求:**
1. **网格搜索**: 遍历参数组合
2. **遗传算法**: 遗传算法优化
3. **贝叶斯优化**: 贝叶斯优化
4. **多目标优化**: 同时优化多个目标
5. **优化结果**: 优化结果展示和对比
6. **并行优化**: 多进程并行优化

**非功能需求:**
1. 优化速度尽可能快
2. 内存占用可控

### 7. 报表导出系统 (优先级: 低)

**需求描述:**
建立报表导出系统，支持多种格式的报告导出。

**功能需求:**
1. **PDF报告**: 生成PDF格式报告
2. **Excel报告**: 生成Excel格式报告
3. **HTML报告**: 生成HTML格式报告
4. **报告模板**: 可自定义报告模板
5. **批量导出**: 批量导出多个报告
6. **报告发送**: 邮件发送报告

---

## 设计文档

### 1. Web服务架构设计

#### 1.1 整体架构 (Vue3 + FastAPI + 多数据库)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          前端层 (Vue3 SPA)                              │
├─────────────────────────────────────────────────────────────────────────┤
│  Vue3 + TypeScript + Vite + Pinia + Vue Router + Element Plus          │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐      │
│  │Dashboard│  │Backtest │  │Strategy │  │  Data   │  │ Settings│      │
│  │  Page   │  │  Page   │  │  Page   │  │  Page   │  │  Page   │      │
│  └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘      │
│       └────────────┴────────────┴────────────┴────────────┘            │
│                              │                                          │
│  ┌───────────────────────────┴───────────────────────────┐             │
│  │             Echarts 图表组件库                          │             │
│  │  KlineChart | EquityCurve | HeatmapChart | TradeList  │             │
│  └───────────────────────────────────────────────────────┘             │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │ HTTP/WebSocket (Axios)
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                          API网关层 (Nginx)                              │
│  负载均衡 | SSL终结 | 静态资源 | 限流 | 日志                             │
└────────────────────────────────┬────────────────────────────────────────┘
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     后端服务层 (FastAPI + Uvicorn)                       │
├─────────────────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐    │
│  │ Auth API    │  │Backtest API │  │Strategy API │  │  Data API   │    │
│  │ /api/auth/* │  │/api/backtest│  │/api/strategy│  │ /api/data/* │    │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘    │
│         └────────────────┴────────────────┴────────────────┘            │
│                              │                                          │
│  ┌───────────────────────────┴───────────────────────────┐             │
│  │              业务服务层 (Service Layer)                 │             │
│  │  AuthService | BacktestService | StrategyService | ... │             │
│  └───────────────────────────┬───────────────────────────┘             │
│                              │                                          │
│  ┌───────────────────────────┴───────────────────────────┐             │
│  │              数据访问层 (Repository Layer)              │             │
│  │  UserRepo | BacktestRepo | StrategyRepo | MarketRepo  │             │
│  └───────────────────────────────────────────────────────┘             │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
         ┌───────────────────────┼───────────────────────┐
         ▼                       ▼                       ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Celery Worker │    │   Redis Cluster │    │   多数据库层     │
│   异步任务处理    │    │   缓存+消息队列  │    │                 │
│   - 回测任务     │◄───│   - Session     │    │ ┌─────────────┐ │
│   - 优化任务     │    │   - Cache       │    │ │ PostgreSQL  │ │
│   - 报表生成     │    │   - Pub/Sub     │    │ │ MySQL       │ │
└─────────────────┘    └─────────────────┘    │ │ MongoDB     │ │
                                              │ │ DolphinDB   │ │
                                              │ │ ClickHouse  │ │
                                              │ └─────────────┘ │
                                              └─────────────────┘
```

#### 1.2 FastAPI服务设计

```python
# backtrader/web/api/app.py
from fastapi import FastAPI, APIRouter, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import uvicorn
from typing import List
import logging

from backtrader.web.service.backtest_service import BacktestService
from backtrader.web.service.strategy_service import StrategyService
from backtrader.web.domain.schemas import (
    BacktestRequest,
    BacktestResponse,
    StrategyCreate,
    StrategyResponse,
)

# 创建FastAPI应用
app = FastAPI(
    title="Backtrader Web API",
    description="Backtrader量化交易回测Web服务",
    version="1.0.0",
)

# CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境应限制具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 安全认证
security = HTTPBearer()

# 全局异常处理
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logging.error(f"API错误: {exc}")
    return JSONResponse(
        status_code=500,
        content={"error": str(exc)}
    )

# 依赖注入
def get_backtest_service():
    return BacktestService()

def get_strategy_service():
    return StrategyService()

# API路由
api_router = APIRouter(prefix="/api/v1")

# 健康检查
@api_router.get("/health")
async def health_check():
    return {"status": "healthy", "service": "backtrader-web"}

# 回测相关API
backtest_router = APIRouter(prefix="/backtest", tags=["backtest"])

@backtest_router.post("/run", response_model=BacktestResponse)
async def run_backtest(
    request: BacktestRequest,
    service: BacktestService = Depends(get_backtest_service),
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    运行回测

    Args:
        request: 回测请求参数
        service: 回测服务
        credentials: 认证凭据

    Returns:
        BacktestResponse: 回测结果
    """
    try:
        user_id = _get_user_id(credentials)
        result = await service.run_backtest(user_id, request)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@backtest_router.get("/result/{backtest_id}")
async def get_backtest_result(
    backtest_id: str,
    service: BacktestService = Depends(get_backtest_service),
):
    """获取回测结果"""
    result = service.get_result(backtest_id)
    if not result:
        raise HTTPException(status_code=404, detail="回测结果不存在")
    return result

@backtest_router.get("/results")
async def list_backtest_results(
    user_id: str,
    service: BacktestService = Depends(get_backtest_service),
    limit: int = 20,
    offset: int = 0,
):
    """列出用户的回测结果"""
    return service.list_results(user_id, limit, offset)

# 策略相关API
strategy_router = APIRouter(prefix="/strategy", tags=["strategy"])

@strategy_router.post("/create", response_model=StrategyResponse)
async def create_strategy(
    strategy: StrategyCreate,
    service: StrategyService = Depends(get_strategy_service),
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """创建策略"""
    user_id = _get_user_id(credentials)
    return service.create_strategy(user_id, strategy)

@strategy_router.get("/list")
async def list_strategies(
    user_id: str,
    service: StrategyService = Depends(get_strategy_service),
):
    """列出用户的策略"""
    return service.list_strategies(user_id)

@strategy_router.get("/{strategy_id}")
async def get_strategy(
    strategy_id: str,
    service: StrategyService = Depends(get_strategy_service),
):
    """获取策略详情"""
    strategy = service.get_strategy(strategy_id)
    if not strategy:
        raise HTTPException(status_code=404, detail="策略不存在")
    return strategy

# 注册路由
app.include_router(api_router)
api_router.include_router(backtest_router)
api_router.include_router(strategy_router)

def _get_user_id(credentials: HTTPAuthorizationCredentials) -> str:
    """从token获取用户ID（简化实现）"""
    # 实际应解析JWT token
    return credentials.credentials or "anonymous"

def start_server(host="0.0.0.0", port=8080):
    """启动Web服务"""
    uvicorn.run(
        "backtrader.web.api.app:app",
        host=host,
        port=port,
        reload=True,
        log_level="info"
    )
```

#### 1.3 数据模型设计

```python
# backtrader/web/domain/schemas.py
from pydantic import BaseModel, Field
from typing import Optional, List, Dict
from datetime import datetime
from enum import Enum

class TaskStatus(str, Enum):
    """任务状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

class BacktestRequest(BaseModel):
    """回测请求"""
    strategy_id: str = Field(..., description="策略ID")
    symbol: str = Field(..., description="股票代码")
    start_date: datetime = Field(..., description="开始日期")
    end_date: datetime = Field(..., description="结束日期")
    initial_cash: float = Field(100000.0, description="初始资金")
    commission: float = Field(0.001, description="手续费率")
    params: Dict[str, float] = Field(default_factory=dict, description="策略参数")

    class Config:
        json_schema_extra = {
            "example": {
                "strategy_id": "ma_cross",
                "symbol": "000001.SZ",
                "start_date": "2023-01-01T00:00:00",
                "end_date": "2024-01-01T00:00:00",
                "initial_cash": 100000,
                "commission": 0.001,
                "params": {"fast_period": 5, "slow_period": 20}
            }
        }

class BacktestResponse(BaseModel):
    """回测响应"""
    task_id: str = Field(..., description="任务ID")
    status: TaskStatus = Field(..., description="任务状态")
    message: Optional[str] = Field(None, description="状态消息")

class BacktestResult(BaseModel):
    """回测结果"""
    task_id: str
    strategy_id: str
    symbol: str
    start_date: datetime
    end_date: datetime

    # 性能指标
    total_return: float
    annual_return: float
    sharpe_ratio: float
    max_drawdown: float
    win_rate: float

    # 交易统计
    total_trades: int
    profitable_trades: int
    losing_trades: int

    # 资金曲线数据
    equity_curve: List[float]
    drawdown_curve: List[float]

    # 交易记录
    trades: List[Dict]

    created_at: datetime

class StrategyCreate(BaseModel):
    """创建策略"""
    name: str = Field(..., description="策略名称")
    description: Optional[str] = Field(None, description="策略描述")
    code: str = Field(..., description="策略代码")
    params: Dict[str, any] = Field(default_factory=dict, description="默认参数")
    category: Optional[str] = Field("custom", description="策略分类")

class StrategyResponse(BaseModel):
    """策略响应"""
    strategy_id: str
    user_id: str
    name: str
    description: Optional[str]
    code: str
    params: Dict[str, any]
    category: str
    created_at: datetime
    updated_at: datetime
```

### 2. 回测服务设计

```python
# backtrader/web/service/backtest_service.py
import asyncio
import uuid
import backtrader as bt
from datetime import datetime
from typing import Optional, Dict, List
import logging
import pandas as pd

from backtrader.web.domain.schemas import (
    BacktestRequest,
    BacktestResult,
    TaskStatus,
)
from backtrader.web.repository.backtest_repository import BacktestRepository
from backtrader.web.service.data_service import DataService

class BacktestService:
    """
    回测服务

    功能:
    1. 异步执行回测任务
    2. 回测结果存储
    3. 回测任务管理
    """
    def __init__(self, repository: BacktestRepository = None, data_service: DataService = None):
        self.repository = repository or BacktestRepository()
        self.data_service = data_service or DataService()
        self._running_tasks: Dict[str, asyncio.Task] = {}
        self._logger = logging.getLogger(__name__)

    async def run_backtest(self, user_id: str, request: BacktestRequest) -> Dict:
        """
        运行回测（异步）

        Args:
            user_id: 用户ID
            request: 回测请求

        Returns:
            dict: 任务信息
        """
        # 生成任务ID
        task_id = str(uuid.uuid4())

        # 创建任务记录
        task_info = {
            "task_id": task_id,
            "user_id": user_id,
            "status": TaskStatus.PENDING,
            "request": request.model_dump(),
            "created_at": datetime.now(),
        }

        # 保存任务
        await self.repository.create_task(task_info)

        # 创建异步任务
        task = asyncio.create_task(self._execute_backtest(task_id, user_id, request))
        self._running_tasks[task_id] = task

        return {
            "task_id": task_id,
            "status": TaskStatus.PENDING,
            "message": "回测任务已创建"
        }

    async def _execute_backtest(self, task_id: str, user_id: str, request: BacktestRequest):
        """
        执行回测任务

        Args:
            task_id: 任务ID
            user_id: 用户ID
            request: 回测请求
        """
        try:
            # 更新任务状态
            await self.repository.update_task_status(task_id, TaskStatus.RUNNING)

            # 获取数据
            self._logger.info(f"获取数据: {request.symbol}")
            data = await self.data_service.get_data(
                symbol=request.symbol,
                start_date=request.start_date,
                end_date=request.end_date,
            )

            # 创建Cerebro
            cerebro = bt.Cerebro()

            # 添加数据
            cerebro.adddata(data)

            # 设置初始资金和手续费
            cerebro.broker.setcash(request.initial_cash)
            cerebro.broker.setcommission(commission=request.commission)

            # 添加分析器
            cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
            cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
            cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
            cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')

            # 加载策略
            strategy = self._load_strategy(request.strategy_id, request.params)
            cerebro.addstrategy(strategy, **request.params)

            # 运行回测
            self._logger.info(f"开始回测: {task_id}")
            results = cerebro.run()
            strat = results[0]

            # 收集结果
            backtest_result = self._collect_results(cerebro, strat, request)

            # 保存结果
            await self.repository.save_result(task_id, backtest_result)

            # 更新任务状态
            await self.repository.update_task_status(task_id, TaskStatus.COMPLETED)

            self._logger.info(f"回测完成: {task_id}")

        except Exception as e:
            self._logger.error(f"回测失败: {task_id}, {e}")
            await self.repository.update_task_status(task_id, TaskStatus.FAILED)
            await self.repository.save_error(task_id, str(e))

    def _collect_results(self, cerebro, strat, request: BacktestRequest) -> BacktestResult:
        """收集回测结果"""
        # 获取分析器结果
        sharpe = strat.analyzers.sharpe.get_analysis()
        drawdown = strat.analyzers.drawdown.get_analysis()
        returns = strat.analyzers.returns.get_analysis()
        trades = strat.analyzers.trades.get_analysis()

        # 计算总收益率
        final_value = cerebro.broker.getvalue()
        total_return = (final_value / request.initial_cash - 1) * 100

        return BacktestResult(
            task_id="",
            strategy_id=request.strategy_id,
            symbol=request.symbol,
            start_date=request.start_date,
            end_date=request.end_date,
            total_return=round(total_return, 2),
            annual_return=round(returns.get('rnorm100', 0), 2) if returns else 0,
            sharpe_ratio=round(sharpe.get('sharperatio', 0), 2) if sharpe else 0,
            max_drawdown=round(drawdown.get('max', {}).get('drawdown', 0), 2) if drawdown else 0,
            win_rate=0,  # 计算胜率
            total_trades=trades.get('total', {}).get('total', 0) if trades else 0,
            profitable_trades=trades.get('won', {}).get('total', 0) if trades else 0,
            losing_trades=trades.get('lost', {}).get('total', 0) if trades else 0,
            equity_curve=[],
            drawdown_curve=[],
            trades=[],
            created_at=datetime.now(),
        )

    def _load_strategy(self, strategy_id: str, params: Dict):
        """加载策略类"""
        # 从策略库加载
        # 实际实现应从数据库加载策略代码并动态导入
        pass

    def get_result(self, backtest_id: str) -> Optional[BacktestResult]:
        """获取回测结果"""
        return self.repository.get_result(backtest_id)

    def list_results(self, user_id: str, limit: int = 20, offset: int = 0):
        """列出回测结果"""
        return self.repository.list_results(user_id, limit, offset)
```

### 3. 可视化系统设计

#### 3.1 K线图表生成

```python
# backtrader/web/charts/kline.py
from pyecharts import options as opts
from pyecharts.charts import Kline, Bar, Line, Grid
import pandas as pd

class KlineChart:
    """
    K线图生成器

    功能:
    1. 生成专业K线图
    2. 添加技术指标
    3. 添加交易信号
    4. 支持交互
    """
    def __init__(self):
        self.width = "100%"
        self.height = "600px"

    def generate(self, df: pd.DataFrame, indicators: List = None, signals: pd.DataFrame = None) -> Grid:
        """
        生成K线图

        Args:
            df: OHLCV数据
            indicators: 指标列表
            signals: 交易信号数据

        Returns:
            Grid: 组合图表
        """
        # 准备数据
        dates = df.index.strftime('%Y-%m-%d').tolist()
        kline_data = zip(
            df['open'].tolist(),
            df['close'].tolist(),
            df['low'].tolist(),
            df['high'].tolist()
        )
        kline_data = [list(d) for d in kline_data]

        # 创建K线图
        kline = (
            Kline(init_opts=opts.InitOpts(width=self.width, height=self.height))
            .add_xaxis(dates)
            .add_yaxis(
                series_name="K线",
                y_axis=kline_data,
                itemstyle_opts=opts.ItemStyleOpts(color="#ef232a", color0="#14b143"),
            )
            .set_series_opts(
                markarea_opts=[
                    opts.MarkAreaOpts(
                        is_silent=True,
                        label_opts=opts.LabelOpts(is_show=False),
                    )
                ]
            )
            .set_global_opts(
                title_opts=opts.TitleOpts(title="K线图"),
                datazoom_opts=[
                    opts.DataZoomOpts(
                        is_show=True,
                        type_="inside",
                        xaxis_index=[0, 1],
                        range_start=0,
                        range_end=100,
                    ),
                    opts.DataZoomOpts(
                        is_show=True,
                        xaxis_index=[0, 1],
                        type_="slider",
                        pos_top="90%",
                        range_start=0,
                        range_end=100,
                    )
                ],
                tooltip_opts=opts.TooltipOpts(
                    trigger="axis",
                    axis_pointer_type="cross",
                ),
                visualmap_opts=opts.VisualMapOpts(
                    is_show=False,
                    dimension=2,
                    series_index=0,
                    is_piecewise=True,
                    pieces=[
                        {"value": 1, "color": "#00da3c"},
                        {"value": -1, "color": "#ec0000"},
                    ],
                ),
                yaxis_opts=opts.AxisOpts(
                    is_scale=True,
                    splitarea_opts=opts.SplitAreaOpts(
                        is_show=True, areastyle_opts=opts.AreaStyleOpts(opacity=1)
                    ),
                ),
                xaxis_opts=opts.AxisOpts(
                    is_scale=True,
                    axislabel_opts=opts.LabelOpts(is_show=False),
                ),
                legend_opts=opts.LegendOpts(
                    is_show=True,
                    pos_left="left",
                    pos_top="top",
                ),
            )
        )

        # 添加成交量
        volume = (
            Bar(init_opts=opts.InitOpts(width=self.width, height="120px"))
            .add_xaxis(dates)
            .add_yaxis(
                "成交量",
                df['volume'].tolist(),
                itemstyle_opts=opts.ItemStyleOpts(color="#7fbe23"),
            )
            .set_global_opts(
                title_opts=opts.TitleOpts(title="成交量"),
                xaxis_opts=opts.AxisOpts(
                    axislabel_opts=opts.LabelOpts(is_show=False),
                ),
                legend_opts=opts.LegendOpts(is_show=False),
            )
        )

        # 添加指标
        if indicators:
            overlay = Line(init_opts=opts.InitOpts(width=self.width, height="200px"))
            overlay.add_xaxis(dates)

            for indicator in indicators:
                overlay.add_yaxis(indicator['name'], indicator['data'])

            overlay.set_global_opts(
                title_opts=opts.TitleOpts(title="指标"),
                xaxis_opts=opts.AxisOpts(
                    axislabel_opts=opts.LabelOpts(is_show=False),
                ),
                legend_opts=opts.LegendOpts(),
            )
        else:
            overlay = None

        # 组合图表
        charts = [kline, volume]
        if overlay:
            charts.append(overlay)

        grid = Grid(init_opts=opts.InitOpts(width=self.width))
        for i, chart in enumerate(charts):
            grid.add(
                chart,
                grid_opts=opts.GridOpts(
                    pos_left="10%",
                    pos_right="8%",
                    height=f"{70 - i*20 if i < 2 else 20}%",
                ),
            )

        return grid

    def to_html(self, chart: Grid) -> str:
        """导出HTML"""
        return chart.render_embed()

    def save_html(self, chart: Grid, filename: str):
        """保存HTML文件"""
        chart.render(filename)
```

#### 3.2 回测结果图表

```python
# backtrader/web/charts/result.py
from pyecharts.charts import Line, Bar, Pie, Tab
from pyecharts import options as opts
import pandas as pd

class ResultChart:
    """回测结果图表"""
    @staticmethod
    def equity_curve(equity: list, drawdown: list = None, dates: list = None) -> Line:
        """
        资金曲线图

        Args:
            equity: 资金曲线数据
            drawdown: 回撤数据
            dates: 日期列表
        """
        x_data = dates if dates else list(range(len(equity)))

        line = Line(init_opts=opts.InitOpts(width="100%", height="400px"))
        line.add_xaxis(x_data)
        line.add_yaxis("资金", equity, is_smooth=True)

        if drawdown:
            line.add_yaxis("回撤", drawdown, is_smooth=True, yaxis_index=1)

        line.set_global_opts(
            title_opts=opts.TitleOpts(title="资金曲线"),
            tooltip_opts=opts.TooltipOpts(trigger="axis"),
            xaxis_opts=opts.AxisOpts(type_="category"),
            yaxis_opts=opts.AxisOpts(
                is_scale=True,
                splitarea_opts=opts.SplitAreaOpts(),
            ),
        )

        return line

    @staticmethod
    def trade_distribution(trades: pd.DataFrame) -> Pie:
        """
        交易分布饼图

        Args:
            trades: 交易数据
        """
        # 统计盈亏分布
        profit_trades = len(trades[trades['pnl'] > 0])
        loss_trades = len(trades[trades['pnl'] < 0])
        break_even = len(trades[trades['pnl'] == 0])

        data = [
            {"value": profit_trades, "name": "盈利"},
            {"value": loss_trades, "name": "亏损"},
            {"value": break_even, "name": "持平"},
        ]

        pie = Pie(init_opts=opts.InitOpts(width="600px", height="400px"))
        pie.add(
            series_name="交易分布",
            data_pair=data,
            radius=["40%", "70%"],
        )
        pie.set_global_opts(
            title_opts=opts.TitleOpts(title="交易分布"),
            legend_opts=opts.LegendOpts(orient="vertical", pos_left="left"),
        )

        return pie

    @staticmethod
    def monthly_returns(returns: pd.Series) -> Bar:
        """
        月度收益柱状图

        Args:
            returns: 收益率序列
        """
        # 按月汇总
        monthly = returns.resample('M').apply(lambda x: (1 + x).prod() - 1) * 100

        bar = Bar(init_opts=opts.InitOpts(width="100%", height="400px"))
        bar.add_xaxis(monthly.index.strftime('%Y-%m').tolist())
        bar.add_yaxis("月度收益率(%)", monthly.round(2).tolist())

        bar.set_global_opts(
            title_opts=opts.TitleOpts(title="月度收益"),
            yaxis_opts=opts.AxisOpts(
                axislabel_opts=opts.LabelOpts(formatter="{value}%")
            ),
        )

        # 根据正负设置颜色
        bar.set_series_opts(
            itemstyle_opts=opts.ItemStyleOpts(
                color=lambda x: "#ef232a" if x < 0 else "#14b143"
            )
        )

        return bar

    @staticmethod
    def generate_report(result: BacktestResult) -> Tab:
        """生成完整报告"""
        tab = Tab()

        # 资金曲线
        equity_chart = ResultChart.equity_curve(
            result.equity_curve,
            result.drawdown_curve
        )
        tab.add(equity_chart, "资金曲线")

        # 交易分布
        if result.trades:
            trades_df = pd.DataFrame(result.trades)
            pie_chart = ResultChart.trade_distribution(trades_df)
            tab.add(pie_chart, "交易分布")

        return tab
```

### 4. Streamlit Web界面

```python
# backtrader/web/streamlit_app.py
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta

from backtrader.web.service.backtest_service import BacktestService
from backtrader.web.service.strategy_service import StrategyService
from backtrader.web.charts.kline import KlineChart
from backtrader.web.charts.result import ResultChart

# 页面配置
st.set_page_config(
    page_title="Backtrader Web",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# 初始化服务
@st.cache_resource
def get_services():
    return {
        'backtest': BacktestService(),
        'strategy': StrategyService(),
    }

services = get_services()

# 侧边栏
with st.sidebar:
    st.title("📈 Backtrader Web")
    st.markdown("---")

    page = st.radio(
        "选择页面",
        ["首页", "数据查询", "回测分析", "策略管理", "我的回测"],
    )

    st.markdown("---")
    st.markdown("### 设置")

# 首页
if page == "首页":
    st.title("欢迎使用 Backtrader Web")
    st.markdown("""
    这是一个基于 Backtrader 的量化交易回测 Web 应用。

    ## 功能特点

    - **数据查询**: 查询股票历史数据
    - **策略回测**: 快速回测交易策略
    - **结果可视化**: 专业的图表展示
    - **策略管理**: 保存和管理您的策略
    """)

# 数据查询页面
elif page == "数据查询":
    st.title("📊 数据查询")

    col1, col2 = st.columns(2)
    with col1:
        symbol = st.text_input("股票代码", value="000001.SZ")
    with col2:
        date_range = st.date_input(
            "日期范围",
            value=(datetime.now() - timedelta(days=365), datetime.now()),
        )

    if st.button("查询", type="primary"):
        with st.spinner("查询中..."):
            data = services['backtest'].data_service.get_data(
                symbol=symbol,
                start_date=date_range[0],
                end_date=date_range[1],
            )

            st.dataframe(data)

            # K线图
            chart = KlineChart()
            kline = chart.generate(data)
            st.pyecharts_chart(kline, height=600)

# 回测分析页面
elif page == "回测分析":
    st.title("🔬 回测分析")

    # 选择策略
    strategies = services['strategy'].list_strategies()
    strategy_names = [s['name'] for s in strategies]

    col1, col2, col3 = st.columns(3)
    with col1:
        strategy = st.selectbox("选择策略", strategy_names)
    with col2:
        symbol = st.text_input("股票代码", value="000001.SZ")
    with col3:
        cash = st.number_input("初始资金", value=100000, step=10000)

    st.markdown("---")

    # 策略参数
    strategy_params = services['strategy'].get_strategy_params(strategy)
    params = {}
    if strategy_params:
        st.markdown("### 策略参数")
        cols = st.columns(3)
        for i, (name, param) in enumerate(strategy_params.items()):
            with cols[i % 3]:
                if param['type'] == 'int':
                    params[name] = st.slider(
                        name,
                        param['min'],
                        param['max'],
                        param['default'],
                    )
                else:
                    params[name] = st.number_input(
                        name,
                        value=param['default'],
                    )

    if st.button("开始回测", type="primary"):
        with st.spinner("回测中..."):
            # 运行回测
            result = services['backtest'].run_backtest_sync(
                strategy=strategy,
                symbol=symbol,
                initial_cash=cash,
                params=params,
            )

            # 显示结果
            st.markdown("## 回测结果")

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("总收益率", f"{result['total_return']}%")
            m2.metric("年化收益", f"{result['annual_return']}%")
            m3.metric("夏普比率", f"{result['sharpe_ratio']}")
            m4.metric("最大回撤", f"{result['max_drawdown']}%")

            # 资金曲线
            chart = ResultChart()
            equity = chart.equity_curve(result['equity_curve'], result['drawdown_curve'])
            st.pyecharts_chart(equity, height=400)

# 策略管理页面
elif page == "策略管理":
    st.title("📝 策略管理")

    # 创建新策略
    with st.expander("创建新策略"):
        name = st.text_input("策略名称")
        description = st.text_area("策略描述")
        code = st.text_area("策略代码", height=300)

        if st.button("保存策略", type="primary"):
            services['strategy'].create_strategy(
                name=name,
                description=description,
                code=code,
            )
            st.success("策略已保存")

    # 策略列表
    st.markdown("### 我的策略")
    strategies = services['strategy'].list_strategies()

    for strategy in strategies:
        with st.expander(f"{strategy['name']} - {strategy['description']}"):
            st.code(strategy['code'], language="python")

# 运行应用
if __name__ == "__main__":
    pass  # 由 streamlit run 命令启动
```

### 5. 数据持久化设计

```python
# backtrader/web/repository/backtest_repository.py
from sqlalchemy import create_engine, Column, String, Float, Integer, DateTime, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from typing import List, Optional
from datetime import datetime

Base = declarative_base()

class BacktestTask(Base):
    """回测任务表"""
    __tablename__ = 'backtest_tasks'

    task_id = Column(String(64), primary_key=True)
    user_id = Column(String(64), index=True)
    strategy_id = Column(String(64), index=True)
    symbol = Column(String(20), index=True)
    status = Column(String(20))
    request_data = Column(Text)  # JSON
    error_msg = Column(Text)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)

class BacktestResult(Base):
    """回测结果表"""
    __tablename__ = 'backtest_results'

    result_id = Column(String(64), primary_key=True)
    task_id = Column(String(64), index=True)
    user_id = Column(String(64), index=True)

    # 性能指标
    total_return = Column(Float)
    annual_return = Column(Float)
    sharpe_ratio = Column(Float)
    max_drawdown = Column(Float)
    win_rate = Column(Float)

    # 交易统计
    total_trades = Column(Integer)
    profitable_trades = Column(Integer)
    losing_trades = Column(Integer)

    # 数据
    equity_curve = Column(Text)  # JSON
    drawdown_curve = Column(Text)  # JSON
    trades = Column(Text)  # JSON

    created_at = Column(DateTime)


class BacktestRepository:
    """回测数据仓库"""
    def __init__(self, db_url: str = None):
        self.engine = create_engine(db_url or "sqlite:///backtrader.db")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def create_task(self, task_info: dict):
        """创建任务记录"""
        session = self.Session()
        task = BacktestTask(**task_info)
        session.add(task)
        session.commit()
        session.close()

    def update_task_status(self, task_id: str, status: str):
        """更新任务状态"""
        session = self.Session()
        session.query(BacktestTask).filter(
            BacktestTask.task_id == task_id
        ).update({"status": status})
        session.commit()
        session.close()

    def save_result(self, task_id: str, result: BacktestResult):
        """保存回测结果"""
        session = self.Session()

        db_result = BacktestResult(
            result_id=str(uuid.uuid4()),
            task_id=task_id,
            user_id=result.user_id,
            total_return=result.total_return,
            annual_return=result.annual_return,
            sharpe_ratio=result.sharpe_ratio,
            max_drawdown=result.max_drawdown,
            win_rate=result.win_rate,
            total_trades=result.total_trades,
            profitable_trades=result.profitable_trades,
            losing_trades=result.losing_trades,
            equity_curve=json.dumps(result.equity_curve),
            drawdown_curve=json.dumps(result.drawdown_curve),
            trades=json.dumps(result.trades),
            created_at=datetime.now(),
        )

        session.add(db_result)
        session.commit()
        session.close()

    def get_result(self, result_id: str) -> Optional[BacktestResult]:
        """获取回测结果"""
        session = self.Session()
        result = session.query(BacktestResult).filter(
            BacktestResult.result_id == result_id
        ).first()
        session.close()
        return result

    def list_results(self, user_id: str, limit: int = 20, offset: int = 0) -> List[BacktestResult]:
        """列出回测结果"""
        session = self.Session()
        results = session.query(BacktestResult).filter(
            BacktestResult.user_id == user_id
        ).order_by(BacktestResult.created_at.desc()).offset(offset).limit(limit).all()
        session.close()
        return results
```

### 6. 使用示例

#### 6.1 启动服务

```python
# 启动FastAPI服务
from backtrader.web.api.app import start_server

if __name__ == "__main__":
    start_server(host="0.0.0.0", port=8080)
```

```bash
# 启动Streamlit应用
streamlit run backtrader/web/streamlit_app.py --server.port 8502
```

#### 6.2 API调用

```python
import requests

# 运行回测
response = requests.post(
    "http://localhost:8080/api/v1/backtest/run",
    json={
        "strategy_id": "ma_cross",
        "symbol": "000001.SZ",
        "start_date": "2023-01-01T00:00:00",
        "end_date": "2024-01-01T00:00:00",
        "initial_cash": 100000,
        "commission": 0.001,
        "params": {"fast_period": 5, "slow_period": 20}
    },
    headers={"Authorization": "Bearer your_token"}
)

task_id = response.json()["task_id"]

# 查询结果
result = requests.get(f"http://localhost:8080/api/v1/backtest/result/{task_id}")
print(result.json())
```

---

## 新增设计: Vue3前端架构

### 项目结构
```
bt-web-ui/
├── src/
│   ├── api/                    # API接口
│   │   ├── auth.ts
│   │   ├── backtest.ts
│   │   ├── strategy.ts
│   │   └── market.ts
│   ├── components/             # 通用组件
│   │   ├── charts/             # Echarts图表组件
│   │   │   ├── KlineChart.vue
│   │   │   ├── EquityCurve.vue
│   │   │   ├── DrawdownChart.vue
│   │   │   ├── MonthlyHeatmap.vue
│   │   │   └── TradeDistribution.vue
│   │   ├── common/
│   │   │   ├── AppHeader.vue
│   │   │   ├── AppSidebar.vue
│   │   │   └── DataTable.vue
│   │   └── form/
│   │       ├── StrategyParamsForm.vue
│   │       └── BacktestConfigForm.vue
│   ├── views/                  # 页面视图
│   │   ├── Dashboard.vue
│   │   ├── BacktestPage.vue
│   │   ├── StrategyPage.vue
│   │   ├── DataPage.vue
│   │   └── SettingsPage.vue
│   ├── stores/                 # Pinia状态管理
│   │   ├── auth.ts
│   │   ├── backtest.ts
│   │   └── strategy.ts
│   ├── composables/            # 组合式函数
│   │   ├── useWebSocket.ts
│   │   ├── useBacktest.ts
│   │   └── useChart.ts
│   ├── router/
│   │   └── index.ts
│   ├── types/                  # TypeScript类型
│   │   ├── backtest.d.ts
│   │   └── strategy.d.ts
│   ├── App.vue
│   └── main.ts
├── package.json
├── vite.config.ts
├── tsconfig.json
└── tailwind.config.js
```

### Echarts K线图组件

```vue
<!-- src/components/charts/KlineChart.vue -->
<template>
  <div ref="chartRef" :style="{ width: '100%', height: `${height}px` }"></div>
</template>

<script setup lang="ts">
import { ref, onMounted, watch, onUnmounted } from 'vue'
import * as echarts from 'echarts'
import type { EChartsType } from 'echarts'

interface Props {
  data: {
    dates: string[]
    ohlc: number[][]  // [open, close, low, high]
    volumes: number[]
  }
  indicators?: string[]
  signals?: { date: string; type: 'buy' | 'sell'; price: number }[]
  height?: number
}

const props = withDefaults(defineProps<Props>(), {
  height: 600,
  indicators: () => ['MA5', 'MA20'],
})

const emit = defineEmits<{
  (e: 'range-change', range: { start: number; end: number }): void
}>()

const chartRef = ref<HTMLDivElement>()
let chart: EChartsType | null = null

// 计算MA
const calculateMA = (data: number[][], period: number) => {
  const result: (number | '-')[] = []
  for (let i = 0; i < data.length; i++) {
    if (i < period - 1) {
      result.push('-')
    } else {
      let sum = 0
      for (let j = 0; j < period; j++) {
        sum += data[i - j][1] // close price
      }
      result.push(+(sum / period).toFixed(2))
    }
  }
  return result
}

const initChart = () => {
  if (!chartRef.value) return
  
  chart = echarts.init(chartRef.value)
  
  const option: echarts.EChartsOption = {
    animation: false,
    legend: {
      data: ['K线', ...props.indicators],
      top: 10,
    },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
    },
    axisPointer: {
      link: [{ xAxisIndex: 'all' }],
    },
    grid: [
      { left: '10%', right: '8%', height: '50%' },
      { left: '10%', right: '8%', top: '65%', height: '16%' },
    ],
    xAxis: [
      {
        type: 'category',
        data: props.data.dates,
        boundaryGap: false,
        axisLine: { onZero: false },
        splitLine: { show: false },
        min: 'dataMin',
        max: 'dataMax',
        axisPointer: { z: 100 },
      },
      {
        type: 'category',
        gridIndex: 1,
        data: props.data.dates,
        boundaryGap: false,
        axisLine: { onZero: false },
        axisTick: { show: false },
        splitLine: { show: false },
        axisLabel: { show: false },
      },
    ],
    yAxis: [
      {
        scale: true,
        splitArea: { show: true },
      },
      {
        scale: true,
        gridIndex: 1,
        splitNumber: 2,
        axisLabel: { show: false },
        axisLine: { show: false },
        axisTick: { show: false },
        splitLine: { show: false },
      },
    ],
    dataZoom: [
      { type: 'inside', xAxisIndex: [0, 1], start: 80, end: 100 },
      { show: true, xAxisIndex: [0, 1], type: 'slider', top: '85%', start: 80, end: 100 },
    ],
    series: [
      {
        name: 'K线',
        type: 'candlestick',
        data: props.data.ohlc,
        itemStyle: {
          color: '#ec0000',
          color0: '#00da3c',
          borderColor: '#ec0000',
          borderColor0: '#00da3c',
        },
        markPoint: props.signals ? {
          data: props.signals.map(s => ({
            coord: [s.date, s.price],
            value: s.type === 'buy' ? '买' : '卖',
            itemStyle: { color: s.type === 'buy' ? '#00da3c' : '#ec0000' },
          })),
        } : undefined,
      },
      // MA指标
      ...props.indicators.map(ind => {
        const period = parseInt(ind.replace('MA', ''))
        return {
          name: ind,
          type: 'line',
          data: calculateMA(props.data.ohlc, period),
          smooth: true,
          lineStyle: { opacity: 0.6, width: 2 },
        }
      }),
      // 成交量
      {
        name: '成交量',
        type: 'bar',
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: props.data.volumes,
        itemStyle: { color: '#7fbe23' },
      },
    ],
  }
  
  chart.setOption(option)
  
  // 监听缩放事件
  chart.on('datazoom', (params: any) => {
    emit('range-change', { start: params.start, end: params.end })
  })
}

onMounted(() => {
  initChart()
  window.addEventListener('resize', () => chart?.resize())
})

onUnmounted(() => {
  chart?.dispose()
  window.removeEventListener('resize', () => chart?.resize())
})

watch(() => props.data, () => {
  initChart()
}, { deep: true })
</script>
```

---

## 新增设计: 统一数据库抽象层

**设计目标**: 统一接口 + 环境变量配置 + 单库可启动

```python
# backtrader/db/base.py
"""
统一数据库抽象层 - 通过环境变量选择数据库实现
"""
from abc import ABC, abstractmethod
from typing import TypeVar, Generic, List, Optional, Dict, Any
from pydantic import BaseModel
import os

T = TypeVar('T', bound=BaseModel)

class BaseRepository(ABC, Generic[T]):
    """Repository基类 - 统一CRUD接口，所有数据库实现此接口"""
    
    @abstractmethod
    async def create(self, entity: T) -> T: pass
    
    @abstractmethod
    async def get_by_id(self, id: str) -> Optional[T]: pass
    
    @abstractmethod
    async def update(self, id: str, entity: T) -> T: pass
    
    @abstractmethod
    async def delete(self, id: str) -> bool: pass
    
    @abstractmethod
    async def list(self, filters: Dict[str, Any] = None, 
                   skip: int = 0, limit: int = 100) -> List[T]: pass


# backtrader/db/config.py
from pydantic_settings import BaseSettings
from functools import lru_cache

class DatabaseSettings(BaseSettings):
    """数据库配置 - 从环境变量读取"""
    
    # 主数据库 (必须)
    DATABASE_TYPE: str = "sqlite"  # postgresql, mysql, mongodb, sqlite
    DATABASE_URL: str = "sqlite+aiosqlite:///./backtrader.db"
    
    # 可选: 文档数据库 (大文档存储优化)
    DOCUMENT_DB_TYPE: Optional[str] = None
    DOCUMENT_DB_URL: Optional[str] = None
    
    # 可选: 时序数据库 (行情数据优化)
    TIMESERIES_DB_TYPE: Optional[str] = None
    TIMESERIES_DB_URL: Optional[str] = None
    
    # 可选: 缓存
    REDIS_URL: Optional[str] = None
    
    class Config:
        env_file = ".env"

@lru_cache
def get_settings() -> DatabaseSettings:
    return DatabaseSettings()


# backtrader/db/sql_repository.py
"""SQL数据库统一实现 - 支持PostgreSQL/MySQL/SQLite"""
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select, update, delete

class SQLRepository(BaseRepository[T]):
    """SQL数据库实现 - PostgreSQL/MySQL/SQLite共用"""
    
    def __init__(self, db_url: str, model_class):
        self.engine = create_async_engine(db_url, pool_pre_ping=True)
        self.async_session = sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )
        self.model_class = model_class
    
    async def create(self, entity: T) -> T:
        async with self.async_session() as session:
            db_obj = self.model_class(**entity.model_dump())
            session.add(db_obj)
            await session.commit()
            await session.refresh(db_obj)
            return entity
    
    async def get_by_id(self, id: str) -> Optional[T]:
        async with self.async_session() as session:
            result = await session.execute(
                select(self.model_class).where(self.model_class.id == id)
            )
            return result.scalar_one_or_none()
    
    async def list(self, filters=None, skip=0, limit=100) -> List[T]:
        async with self.async_session() as session:
            query = select(self.model_class).offset(skip).limit(limit)
            result = await session.execute(query)
            return result.scalars().all()


# backtrader/db/mongo_repository.py
"""MongoDB实现 - 可选，用于文档存储优化"""
from motor.motor_asyncio import AsyncIOMotorClient

class MongoRepository(BaseRepository[T]):
    def __init__(self, uri: str, collection: str):
        self.client = AsyncIOMotorClient(uri)
        self.collection = self.client.get_default_database()[collection]
    
    async def create(self, entity: T) -> T:
        await self.collection.insert_one(entity.model_dump())
        return entity
    
    async def get_by_id(self, id: str) -> Optional[T]:
        doc = await self.collection.find_one({"_id": id})
        return self.entity_class(**doc) if doc else None


# backtrader/db/cache.py
"""缓存层 - Redis可选，不配置则使用内存缓存"""
import json
from typing import Optional
from functools import lru_cache

class MemoryCache:
    """内存缓存 - 默认实现，无需Redis"""
    _cache: Dict[str, Any] = {}
    
    async def get(self, key: str) -> Optional[dict]:
        return self._cache.get(key)
    
    async def set(self, key: str, value: dict, ttl: int = 3600):
        self._cache[key] = value
    
    async def delete(self, key: str):
        self._cache.pop(key, None)

class RedisCache:
    """Redis缓存 - 可选，配置REDIS_URL后启用"""
    def __init__(self, url: str):
        import redis.asyncio as redis
        self.redis = redis.from_url(url)
    
    async def get(self, key: str) -> Optional[dict]:
        data = await self.redis.get(key)
        return json.loads(data) if data else None
    
    async def set(self, key: str, value: dict, ttl: int = 3600):
        await self.redis.setex(key, ttl, json.dumps(value))


# backtrader/db/factory.py
"""数据库工厂 - 根据环境变量创建Repository"""
from .config import get_settings

def get_repository(entity_name: str, model_class) -> BaseRepository:
    """
    获取Repository实例
    
    使用方法:
        user_repo = get_repository("user", UserModel)
        backtest_repo = get_repository("backtest", BacktestModel)
    """
    settings = get_settings()
    db_type = settings.DATABASE_TYPE
    db_url = settings.DATABASE_URL
    
    if db_type in ("postgresql", "mysql", "sqlite"):
        from .sql_repository import SQLRepository
        return SQLRepository(db_url, model_class)
    elif db_type == "mongodb":
        from .mongo_repository import MongoRepository
        return MongoRepository(db_url, entity_name)
    else:
        raise ValueError(f"不支持的数据库类型: {db_type}")

def get_cache():
    """获取缓存实例 - 有Redis用Redis，否则用内存"""
    settings = get_settings()
    if settings.REDIS_URL:
        from .cache import RedisCache
        return RedisCache(settings.REDIS_URL)
    else:
        from .cache import MemoryCache
        return MemoryCache()
```

**使用示例:**
```python
# 业务代码无需关心具体数据库类型
from backtrader.db import get_repository, get_cache

# 自动根据.env配置选择数据库
user_repo = get_repository("user", UserModel)
await user_repo.create(user)

# 缓存同样自动选择
cache = get_cache()
await cache.set("backtest:123", result)
```

---

## 新增设计: 策略配置加载器

借鉴stock-backtrader-web-app的YAML策略配置模式：

```python
# backtrader/loader/strategy_loader.py
"""
策略配置加载器 - 支持YAML/JSON配置

使用方法:
    from backtrader.loader import load_strategies
    strategies = load_strategies("config/strategies.yaml")
    cerebro.addstrategy(strategies['MaCross'], **strategies['MaCross'].params)
"""
import yaml
import importlib
from typing import Dict, Any, Type
from pathlib import Path

def load_strategies(config_path: str) -> Dict[str, Type]:
    """从配置文件加载策略"""
    path = Path(config_path)
    
    if path.suffix in ['.yaml', '.yml']:
        with open(path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
    elif path.suffix == '.json':
        import json
        with open(path, 'r', encoding='utf-8') as f:
            config = json.load(f)
    else:
        raise ValueError(f"不支持的配置格式: {path.suffix}")
    
    strategies = {}
    for name, spec in config.get('strategies', {}).items():
        module = importlib.import_module(spec['module'])
        strategy_cls = getattr(module, spec['class'])
        
        # 绑定默认参数
        strategy_cls.default_params = spec.get('params', {})
        strategy_cls.description = spec.get('description', '')
        
        strategies[name] = strategy_cls
    
    return strategies


# 策略配置示例 (config/strategies.yaml)
"""
strategies:
  MaCross:
    module: backtrader.strategies.ma
    class: MaCrossStrategy
    description: 双均线交叉策略
    params:
      fast_length:
        type: int
        default: 10
        min: 5
        max: 50
      slow_length:
        type: int
        default: 50
        min: 20
        max: 200
  
  RSI:
    module: backtrader.strategies.rsi
    class: RSIStrategy
    description: RSI超买超卖策略
    params:
      period:
        type: int
        default: 14
      overbought:
        type: int
        default: 70
      oversold:
        type: int
        default: 30
"""
```

---

## 实施路线图 (Vue3 + FastAPI + 多数据库)

### 阶段1: 基础设施搭建 (2周)
- [ ] Docker环境配置 (docker-compose.yml)
- [ ] PostgreSQL + MongoDB + Redis + DolphinDB容器
- [ ] FastAPI项目脚手架搭建
- [ ] Vue3 + Vite项目初始化
- [ ] CI/CD流水线配置

### 阶段2: 多数据库抽象层 (2周)
- [ ] Repository基类定义
- [ ] PostgreSQL Repository实现 (SQLAlchemy 2.0异步)
- [ ] MongoDB Repository实现 (Motor)
- [ ] DolphinDB Repository实现 (行情数据)
- [ ] Redis缓存层实现
- [ ] 数据库工厂和配置加载

### 阶段3: FastAPI后端核心 (3周)
- [ ] Pydantic数据模型 (schemas)
- [ ] 用户认证模块 (JWT + OAuth2)
- [ ] 回测服务 (BacktestService)
- [ ] 策略服务 (StrategyService)
- [ ] Celery异步任务集成
- [ ] WebSocket实时推送
- [ ] API版本管理 (/api/v1/)

### 阶段4: Vue3前端框架 (3周)
- [ ] 项目结构搭建 (Vite + TypeScript)
- [ ] Pinia状态管理
- [ ] Vue Router路由配置
- [ ] Element Plus组件集成
- [ ] Axios HTTP封装
- [ ] WebSocket连接管理

### 阶段5: Echarts图表组件 (2周)
- [ ] KlineChart组件 (K线+均线+成交量)
- [ ] EquityCurve组件 (资金曲线)
- [ ] DrawdownChart组件 (回撤曲线)
- [ ] MonthlyHeatmap组件 (月度收益热力图)
- [ ] TradeDistribution组件 (交易分布)
- [ ] 图表主题切换

### 阶段6: 核心页面开发 (2周)
- [ ] Dashboard仪表盘
- [ ] BacktestPage回测页面
- [ ] StrategyPage策略管理
- [ ] DataPage数据查询
- [ ] SettingsPage系统设置

### 阶段7: 策略配置系统 (1周)
- [ ] YAML/JSON策略配置加载
- [ ] 动态策略导入
- [ ] 参数验证和表单生成
- [ ] 策略模板管理

### 阶段8: 测试与部署 (2周)
- [ ] 后端单元测试 (Pytest)
- [ ] 前端单元测试 (Vitest)
- [ ] E2E测试 (Playwright)
- [ ] 性能压测
- [ ] Nginx反向代理配置
- [ ] 生产环境部署文档

### 时间线总览

```
Week 1-2:   基础设施 ████████
Week 3-4:   数据库层 ████████
Week 5-7:   后端核心 ████████████
Week 8-10:  前端框架 ████████████
Week 11-12: 图表组件 ████████
Week 13-14: 页面开发 ████████
Week 15:    策略配置 ████
Week 16-17: 测试部署 ████████
─────────────────────────────────
总计: 约17周 (4个月)
```

---

## 附录A: 关键文件路径

### Backtrader关键文件
- `cerebro.py`: 核心引擎
- `strategy.py`: 策略基类
- `broker.py`: 经纪商基类
- `plot/plot.py`: 现有matplotlib绑定

### Stock-Backtrader-Web-App关键文件
| 文件 | 行数 | 核心功能 | 借鉴价值 |
|------|------|---------|---------|
| `internal/service/backtraderservice.py` | 101 | 回测服务封装 | ⭐⭐⭐ |
| `internal/pkg/charts/stock.py` | 182 | Pyecharts K线图 | ⭐⭐⭐ |
| `web/backtraderpage.py` | 91 | Streamlit回测页面 | ⭐⭐ |
| `internal/pkg/strategy/macross.py` | 50 | 策略实现示例 | ⭐⭐ |
| `core/factors/algorithm.py` | 381 | 技术指标算法 | ⭐ |

---

## 附录B: 技术栈对比 (更新版)

| 层级 | 原参考项目 | 本迭代采用方案 | 说明 |
|------|-----------|---------------|------|
| **前端框架** | Streamlit | Vue 3 + TypeScript | SPA单页应用，更好的用户体验 |
| **构建工具** | - | Vite 5 | 快速HMR，ES模块 |
| **状态管理** | - | Pinia | Vue3官方推荐 |
| **UI组件** | - | Element Plus | 成熟的企业级组件库 |
| **图表库** | Pyecharts | Echarts 5 | 原生JS，性能更好 |
| **CSS框架** | - | TailwindCSS | 原子化CSS |
| **后端框架** | Streamlit+FastAPI | FastAPI | 高性能异步框架 |
| **ASGI服务** | - | Uvicorn | 生产级服务器 |
| **任务队列** | - | Celery + Redis | 异步回测任务 |
| **主数据库** | SQLite | PostgreSQL/MySQL | 生产级关系数据库 |
| **文档数据库** | - | MongoDB | 策略代码、回测详情 |
| **时序数据库** | - | DolphinDB | 行情Tick数据 |
| **分析数据库** | - | ClickHouse | OLAP统计分析 |
| **缓存** | @st.cache_data | Redis | 分布式缓存 |
| **数据验证** | Pydantic | Pydantic v2 | 类型安全 |
| **ORM** | - | SQLAlchemy 2.0 | 异步ORM |
| **认证** | 无 | JWT + OAuth2 | 企业级认证 |

---

## 附录C: 项目架构选择建议

### 方案对比

| 维度 | 方案A: 独立项目 (backtrader-web) | 方案B: 集成到backtrader |
|------|--------------------------------|------------------------|
| **代码结构** | 独立仓库，独立版本 | 作为backtrader子模块 |
| **安装方式** | `pip install backtrader-web` | `pip install backtrader[web]` |
| **依赖管理** | 独立requirements.txt | 可选依赖 (extras_require) |
| **发布周期** | 独立发布，灵活迭代 | 随backtrader版本发布 |
| **用户群体** | 需要Web功能的用户单独安装 | 所有用户可选启用 |

### 方案A: 独立项目 ✅ **推荐**

**优势:**
1. **轻量安装**: backtrader核心保持轻量，不引入Web依赖
2. **独立迭代**: Web功能可快速迭代，不受backtrader发布周期约束
3. **依赖隔离**: Vue3/FastAPI/SQLAlchemy等重依赖不污染核心包
4. **团队分工**: 前后端开发者可独立贡献
5. **可替换性**: 用户可选择其他Web方案

**劣势:**
1. 需要单独安装两个包
2. 版本兼容性需要维护

**项目结构:**
```
backtrader-web/               # 独立仓库
├── backend/                  # FastAPI后端
│   ├── app/
│   │   ├── api/
│   │   ├── services/
│   │   ├── db/
│   │   └── main.py
│   └── requirements.txt
├── frontend/                 # Vue3前端
│   ├── src/
│   └── package.json
├── pyproject.toml
└── README.md
```

**使用方式:**
```bash
pip install backtrader
pip install backtrader-web

# 启动
backtrader-web serve --port 8000
```

### 方案B: 集成到backtrader

**优势:**
1. **一站式安装**: `pip install backtrader[web]` 一条命令
2. **版本同步**: 保证兼容性
3. **代码共享**: 直接访问backtrader内部API

**劣势:**
1. **依赖膨胀**: Web相关依赖增加包体积
2. **发布耦合**: Web功能更新需等待backtrader发布
3. **维护复杂**: 前后端代码混在量化框架中

**项目结构:**
```
backtrader/
├── backtrader/
│   ├── cerebro.py
│   ├── strategy.py
│   └── web/                  # Web子模块
│       ├── api/
│       ├── frontend/         # 前端构建产物
│       └── __init__.py
├── setup.py                  # extras_require = {'web': [...]}
└── README.md
```

### 推荐结论

**建议采用方案A (独立项目)**，理由：

1. **backtrader定位**: 核心是回测引擎，应保持轻量和稳定
2. **Web技术栈差异大**: Vue3/TypeScript/FastAPI与量化Python代码风格差异大
3. **迭代速度不同**: Web功能需要快速响应用户反馈，独立项目更灵活
4. **社区实践**: 类似项目如 `zipline` + `zipline-trader` 也是分离的

**集成方式:**
```python
# backtrader-web 通过公开API与backtrader交互
from backtrader_web import WebServer
import backtrader as bt

cerebro = bt.Cerebro()
# ... 配置策略

# Web服务封装cerebro
server = WebServer(cerebro)
server.run(port=8000)
```

### 环境变量配置 (.env)
```bash
# .env.example
# 数据库配置
DATABASE_TYPE=sqlite              # postgresql, mysql, mongodb, sqlite
DATABASE_URL=sqlite:///./backtrader.db

# 可选: Redis缓存
# REDIS_URL=redis://localhost:6379/0

# 服务配置
HOST=0.0.0.0
PORT=8000
DEBUG=true
```

### 快速启动
```bash
# 后端
cd backend
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000

# 前端
cd frontend
npm install
npm run dev
```
