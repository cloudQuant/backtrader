# Backtrader 架构文档

> 更新日期: 2026-02-24

## 1. 系统架构总览

```
┌─────────────────────────────────────────────────────────┐
│                      Cerebro (主引擎)                     │
│  ┌─────────┐  ┌──────────┐  ┌──────────┐  ┌─────────┐  │
│  │  Data    │  │ Strategy │  │  Broker  │  │Analyzer │  │
│  │  Feeds   │→ │          │→ │          │→ │         │  │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └─────────┘  │
│       │             │             │                       │
│  ┌────▼─────────────▼─────────────▼──────┐               │
│  │           Line System                  │               │
│  │  LineRoot → LineBuffer → LineSeries    │               │
│  │         → LineIterator                 │               │
│  └────────────────────────────────────────┘               │
└─────────────────────────────────────────────────────────┘
```

## 2. 核心模块依赖关系

```
metabase.py (BaseMixin, findowner, donew)
    │
    ├── lineroot.py (LineRoot, LineSingle, LineMultiple)
    │       │
    │       ├── linebuffer.py (LineBuffer, LinesOperation)
    │       │       │
    │       │       └── lineseries.py (Lines, LineSeries)
    │       │               │
    │       │               └── dataseries.py (DataSeries, OHLC)
    │       │
    │       └── lineiterator.py (LineIterator, DataAccessor)
    │               │
    │               ├── indicator.py (Indicator, IndicatorBase)
    │               │       │
    │               │       └── indicators/* (SMA, EMA, RSI, MACD...)
    │               │
    │               ├── observer.py (Observer)
    │               │       │
    │               │       └── observers/* (TradeLogger, Broker...)
    │               │
    │               └── strategy.py (Strategy, SignalStrategy)
    │
    ├── feed.py (DataBase, CSVDataBase)
    │       │
    │       └── feeds/* (CCXTFeed, PandasData, GenericCSV...)
    │
    ├── broker.py (BrokerBase)
    │       │
    │       └── brokers/* (CCXTBroker, IBBroker, CTPBroker...)
    │
    ├── analyzer.py (Analyzer)
    │       │
    │       └── analyzers/* (SharpeRatio, DrawDown, Returns...)
    │
    ├── order.py (Order, OrderBase)
    ├── trade.py (Trade)
    ├── position.py (Position)
    ├── comminfo.py (CommInfoBase)
    │
    └── cerebro.py (Cerebro) ← 顶层协调器，依赖以上所有模块
```

## 3. 执行流程

### 3.1 回测执行流程

```
cerebro.run()
    │
    ├── 1. _runonce() / _runnext()
    │       │
    │       ├── 数据预加载: data.preload() / data.start()
    │       │
    │       ├── 策略实例化: Strategy.__init__()
    │       │       │
    │       │       └── 指标自动注册到 strategy._lineiterators
    │       │
    │       ├── 最小周期计算: strategy._minperiod
    │       │
    │       └── 主循环 (每个 bar):
    │               │
    │               ├── data.advance()           # 推进数据
    │               ├── indicator._once()/_next() # 更新指标
    │               ├── strategy.next()          # 执行策略
    │               │       │
    │               │       ├── buy() / sell()   # 下单
    │               │       │       │
    │               │       │       └── broker._submit()
    │               │       │
    │               │       └── cancel()         # 撤单
    │               │
    │               ├── broker.next()            # 撮合/检查订单
    │               ├── observer._next()         # 更新观察器
    │               └── analyzer._next()         # 更新分析器
    │
    └── 2. 返回策略实例列表
```

### 3.2 三阶段执行模型

```
┌──────────┐    ┌────────────┐    ┌────────┐
│ prenext  │ →  │ nextstart  │ →  │  next  │
│ (预热)    │    │ (首次满足)   │    │ (正常)  │
└──────────┘    └────────────┘    └────────┘
  bar 0..N-1       bar N            bar N+1..

N = max(所有指标的 minperiod)
```

### 3.3 实盘执行流程 (CCXT)

```
cerebro.run(live=True)
    │
    ├── CCXTFeed.start()
    │       │
    │       ├── 历史数据回补 (_ST_HISTORBACK)
    │       │
    │       ├── WebSocket 连接 (可选)
    │       │       │
    │       │       ├── CCXTWebSocketManager.start()
    │       │       │       │
    │       │       │       └── asyncio 事件循环 (后台线程)
    │       │       │               │
    │       │       │               ├── watch_ohlcv()
    │       │       │               ├── watch_ticker()
    │       │       │               └── watch_trades()
    │       │       │
    │       │       └── _on_websocket_ohlcv() ← 回调
    │       │
    │       └── REST 轮询回退
    │               │
    │               └── _fetch_ohlcv_with_retry()
    │
    ├── CCXTBroker.next() (每 3 秒)
    │       │
    │       ├── 连接检查 (store.is_connected())
    │       │
    │       ├── 模式 A: ThreadedOrderManager
    │       │       └── _process_threaded_updates()
    │       │
    │       └── 模式 B: 直接轮询
    │               └── _retry_api_call(store.fetch_order)
    │
    └── ConnectionManager (后台)
            │
            ├── 健康检查 (fetch_time)
            ├── 断线回调
            └── 自动重连 (指数退避)
```

## 4. CCXT 模块架构

```
backtrader/ccxt/
├── __init__.py          # 公共 API 导出
│
├── websocket.py         # CCXTWebSocketManager
│   ├── asyncio 事件循环 (后台线程)
│   ├── 多频道订阅 (OHLCV/Ticker/Trades/OrderBook/FundingRate)
│   ├── 自动重连 (指数退避 5s → 60s)
│   └── 订阅恢复
│
├── threading.py         # 多线程管理
│   ├── ThreadedDataManager (后台数据拉取)
│   ├── ThreadedOrderManager (后台订单检查)
│   └── DataUpdate / OrderUpdate (线程安全队列)
│
├── connection.py        # ConnectionManager
│   ├── 健康检查线程 (fetch_time)
│   ├── 断线/重连回调
│   └── 数据回补
│
├── ratelimit.py         # 限流
│   ├── RateLimiter (固定 RPM)
│   ├── AdaptiveRateLimiter (动态调整)
│   └── retry_with_backoff (装饰器)
│
├── config.py            # ExchangeConfig
│   └── 交易所特定配置 (订单类型/时间周期/费率)
│
├── config_helper.py     # .env 配置加载
│
└── orders/
    └── bracket.py       # BracketOrderManager (OCO 条件单)

外部集成:
├── brokers/ccxtbroker.py  ← 使用 threading + ratelimit + connection
├── feeds/ccxtfeed.py      ← 使用 websocket + threading
├── feeds/ccxtfeed_funding.py ← 使用 websocket (资金费率)
└── stores/ccxtstore.py    ← 使用 ratelimit + connection + config
```

## 5. Line 系统 (核心数据结构)

### 5.1 类层次

```
LineRoot (接口: 周期管理, 操作管理)
    │
    ├── LineSingle (单条线, 用于操作结果)
    │
    └── LineMultiple (多条线)
            │
            ├── LineBuffer (循环缓冲区存储)
            │       │
            │       └── 关键属性:
            │           ├── array: deque 数据存储
            │           ├── idx: 当前位置
            │           ├── lencount: 数据长度
            │           └── extension: 延伸缓冲
            │
            └── LineSeries (时间序列操作)
                    │
                    ├── lines: Lines 对象 (包含多个 LineBuffer)
                    ├── 数学运算重载 (__add__, __mul__, etc.)
                    └── 比较运算重载 (__gt__, __lt__, etc.)
```

### 5.2 数据访问模式

```python
# 相对位置访问 (最常用)
self.data.close[0]     # 当前 bar 收盘价
self.data.close[-1]    # 前一 bar 收盘价
self.data.close[-2]    # 前两 bar 收盘价

# Line 对象
self.lines.datetime[0] # 当前时间
self.lines.open[0]     # 当前开盘价

# 简写
self.data0              # 第一个数据源
self.datas[1]           # 第二个数据源
```

## 6. 参数系统

### 6.1 参数定义

```python
class MyStrategy(bt.Strategy):
    params = (
        ('fast_period', 10),
        ('slow_period', 30),
        ('stake', 100),
    )
```

### 6.2 参数访问

```python
def __init__(self):
    super().__init__()
    # 通过 self.p 或 self.params 访问
    self.fast_sma = bt.indicators.SMA(period=self.p.fast_period)
    self.slow_sma = bt.indicators.SMA(period=self.p.slow_period)
```

### 6.3 参数传递 (Cerebro)

```python
cerebro.addstrategy(MyStrategy, fast_period=5, slow_period=20)
cerebro.optstrategy(MyStrategy, fast_period=range(5, 20))
```

## 7. 错误处理架构 (CCXT)

```
API 调用
    │
    ├── NetworkError / ExchangeNotAvailable
    │       → _retry_api_call() (最多 3 次, 指数退避)
    │           │
    │           ├── 成功 → 重置 _consecutive_failures
    │           └── 全部失败 → 记录错误, 跳过本轮
    │
    ├── ExchangeError (业务错误)
    │       → 不重试, 直接抛出/处理
    │       → "order not found" → 标记订单取消
    │       → "insufficient balance" → 拒绝订单
    │
    └── 连接状态检测
            │
            ├── store.is_connected() == False
            │       → 跳过 API 调用
            │       → _consecutive_failures++
            │
            └── _consecutive_failures >= 10
                    → 轮询间隔从 3s 退避到 30s
```

## 8. 内存管理

| 模式 | exactbars 值 | 行为 |
|------|-------------|------|
| 完整 | `False` (默认) | 保留所有 bar 数据 |
| 有限 | `True` / `1` | 仅保留 minperiod 个 bar |
| 节省 | `-1` | 保留 minperiod，但保留指标缓冲 |
| 最小 | `-2` | 最小缓冲，指标也受限 |

```python
cerebro = bt.Cerebro(exactbars=True)  # 内存优化模式
```
