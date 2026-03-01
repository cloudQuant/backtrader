# Backtrader Tick级回测与实盘交易架构设计

> 版本: v1.1 | 日期: 2026-02-28 | 状态: 设计阶段（已优化）

---

## 1. 需求概述

### 1.1 当前能力
- Strategy只有`next()`回调，每根K线触发一次
- 数据源基于`OHLCDateTime`固定7条lines
- Broker用bar的OHLC进行订单撮合

### 1.2 新增需求

| 需求 | 说明 |
|------|------|
| Tick数据 | 逐笔成交(price,volume,direction)，毫秒级 |
| OrderBook数据 | 盘口深度(bids/asks多档)，100ms级 |
| FundingRate数据 | 资金费率，8小时级 |
| 自定义数据通道 | 用户可注册任意数据类型 |
| 纯Tick回测 | 无K线，纯tick驱动 |
| 混合模式 | K线+Tick/OrderBook共存 |
| 纯K线模式 | 向后兼容（不变） |
| Tick级Broker | 用tick/orderbook撮合订单 |

---

## 2. 现有架构分析

### 2.1 LineSeries体系核心链路

```
LineBuffer (array.array存储, idx指针)
  → LineSingle → LineRoot
    → LineSeries (多行容器, Lines管理命名访问)
      → DataSeries (OHLCV标准lines + timeframe)
        → OHLCDateTime (datetime line)
          → AbstractDataBase (数据加载/过滤)
            → DataBase (replay/resample)
```

### 2.2 LineSeries核心约束

| 约束 | 说明 |
|------|------|
| 定长时间序列 | 每条line是等长array.array('d')，通过idx同步 |
| 标量值 | 每个时间点每条line只有一个float值 |
| forward/rewind | 所有lines同步前进/后退，由clock驱动 |
| minperiod | 基于历史数据量的最小周期管理 |
| idx=0语义 | 当前活跃值始终在index 0 |
| runonce | 向量化预计算，要求数据可预加载 |

### 2.3 Cerebro主循环

**_runnext**: while循环 → 每个data.next() → dt0=min(dts) → _brokernotify() → strategy._next()

**_runonce**: strat._once()预计算 → for循环advance → _brokernotify() → strat._oncepost(dt)

关键: **主循环以bar为单位驱动**，所有data同步推进到dt0。

---

## 3. Channel是否参与LineSeries体系：深度分析

### 3.1 方案A：参与LineSeries

将Tick/OrderBook作为特殊DataBase子类，每个数据点作为一个"bar"。

#### 优势
- **复用基础设施**: forward/rewind/qbuffer/bindings全部可用
- **指标直接可用**: `bt.indicators.SMA(tick_data.price, period=100)`
- **Observer/Analyzer可用**: TradeAnalyzer、SharpeRatio无需修改
- **数据同步已有**: Cerebro时间排序、rewind机制可处理多频率对齐
- **内存管理已有**: qbuffer、exactbars直接可用
- **绘图可用**: plot系统可绘制tick数据
- **学习成本低**: 用户只需现有API

#### 劣势
- **OrderBook无法表达**: 2D结构(档位×bid/ask)无法用固定float lines表达完整深度，只能退化为best_bid/best_ask摘要
- **性能开销巨大**: 每tick执行forward→filter链→check→advance，每秒数千tick不可接受
- **语义不匹配**: tick是append-only流，不需要rewind；OrderBook是snapshot覆盖语义
- **minperiod冲突**: tick的minperiod语义与bar完全不同
- **时间对齐困难**: tick频率远高于bar，导致bar数据大量rewind
- **runonce不兼容**: tick百万级数据预加载不现实
- **数据类型受限**: 只能存float，无法存string(trade_id)、嵌套结构
- **clock污染**: tick作为datas[]成员干扰bar时间同步

#### 性能定量分析

```
BTC/USDT, 1分钟K线, tick约200/秒, 每分钟12000 tick

LineSeries.forward() 每条line: ~220ns
4条line(datetime,price,vol,dir) × 12000 tick = ~10.6ms/分钟
加上filter链、_check: 估计50-100ms/分钟
一天1440分钟: 72-144秒 overhead

对比 deque.append: ~30ns/tick
12000 × 30ns = 0.36ms/分钟, 一天0.5秒

LineSeries的overhead约为deque的200倍。
```

### 3.2 方案B：完全独立

DataChannel不继承LineSeries，用deque作缓冲。

#### 优势
- 数据结构自由（OrderBook完整多档、trade_id字符串）
- 极低overhead（deque.append）
- 语义清晰、不污染现有系统、零回归风险
- 支持可变长数据、C++移植接口清晰

#### 劣势
- 无法直接使用指标系统
- Observer/Analyzer不兼容，需适配
- 绘图、Writer不兼容
- 用户需学习两套概念

### 3.3 方案C（推荐）：独立DataChannel + LineSeries桥接

Channel本身独立，提供**可选桥接**机制投影到LineSeries。

```python
# Channel本身独立高性能
tick_channel = TickChannel(symbol='BTC/USDT', dataname='ticks.csv')

# 可选桥接到LineSeries使用指标
tick_as_data = tick_channel.to_lineseries()
sma = bt.indicators.SMA(tick_as_data.price, period=100)

# 或直接用Channel内置高性能计算
vwap = tick_channel.vwap(period=100)
```

### 3.4 综合对比

| 维度 | A:完全参与 | B:完全独立 | C:独立+桥接 |
|------|:---------:|:---------:|:----------:|
| OrderBook完整表达 | ❌ | ✅ | ✅ |
| Tick性能 | ❌慢200× | ✅最优 | ✅最优 |
| 指标可用 | ✅直接 | ❌ | ✅可选桥接 |
| 自定义数据结构 | ❌仅float | ✅ | ✅ |
| 向后兼容 | ⚠️有风险 | ✅零风险 | ✅零风险 |
| runonce兼容 | ❌ | ✅不参与 | ✅不参与 |
| C++移植 | ❌耦合重 | ✅接口清晰 | ✅接口清晰 |
| 实现复杂度 | ⚠️中等 | ✅简单 | ⚠️中等 |

### 3.5 最终决策

**推荐方案C：独立DataChannel + 可选LineSeries桥接**

理由: 性能是硬约束(200×差距)、OrderBook是2D数据、桥接按需使用零开销、零回归风险、C++友好。

### 3.6 优化补充（v1.1更新）

**核心设计决策**：

1. **流式EventQueue**：使用StreamingEventQueue替代全量预加载，内存从1.7GB降至~100MB
2. **Bar事件化**：Bar以`bar_open/bar_close`事件进入全局EventQueue，保证与Tick/OrderBook严格时间排序
3. **Broker三件套**：
   - `BackBroker`：bar OHLC撮合（现有不变）
   - `TickBroker`：纯tick/OB撮合
   - `MixBroker`：tick即时撮合 + bar兜底撮合
4. **批处理通知**：收集-分发模式，避免同timestamp内通知乱序
5. **ChannelBridge限制**：明确不支持runonce，强制使用next模式
6. **多策略Channel共享**：支持shared参数控制Channel共享模式
7. **回调执行顺序**：
   - broker处理事件（不立即通知）
   - 分发到策略回调
   - 统一发送broker通知
   - next()在主时钟bar_close后触发

---

## 4. 整体架构

```
┌──────────────────────────────────────────────────────────┐
│                        Cerebro                            │
│                                                           │
│  ┌──────────────┐    ┌─────────────────────────────────┐ │
│  │ Bar System   │    │ Channel System (新增)            │ │
│  │ (现有不变)    │    │                                 │ │
│  │ DataBase     │    │  StreamingEventQueue            │ │
│  │ ├─data0(1m)  │    │  (流式加载, 可控内存)            │ │
│  │ └─data1(5m)  │    │  ├─ TickChannel                 │ │
│  │              │    │  ├─ OrderBookChannel            │ │
│  │ Indicators   │    │  ├─ FundingRateChannel           │ │
│  └──────┬───────┘    │  └─ CustomChannel               │ │
│         │            └──────────┬──────────────────────┘ │
│         │     Bridge(可选,不支持runonce)  │               │
│  ┌──────┴───────────────────────────┴──────────────────┐ │
│  │                Strategy                              │ │
│  │  next()         ← K线回调(不变)                      │ │
│  │  on_tick()      ← Tick事件回调                       │ │
│  │  on_orderbook() ← OrderBook回调                      │ │
│  │  on_bar()       ← Bar到达时回调（MIX/TICK模式）       │ │
│  │  on_funding()   ← FundingRate回调                    │ │
│  │  on_channel()   ← 通用自定义回调                     │ │
│  └──────┬──────────────────────────────────────────────┘ │
│  ┌──────┴──────────────────────────────────────────────┐ │
│  │  BackBroker(bar OHLC撮合,不变)                       │ │
│  │  TickBroker(tick/OB撮合,纯Tick模式)                  │ │
│  │  MixBroker(tick即时撮合 + bar兜底)                   │ │
│  └─────────────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────────────┘
```

### 模块划分

```
backtrader/
├── channel.py                  # DataChannel基类 + StreamingEventQueue
├── channels/
│   ├── __init__.py
│   ├── tick.py                 # TickChannel + TickEvent
│   ├── orderbook.py            # OrderBookChannel + OrderBookSnapshot
│   ├── funding.py              # FundingRateChannel + FundingEvent
│   ├── bridge.py               # LineSeries桥接层（不支持runonce）
│   └── ccxt/                   # CCXT实盘实现
│       ├── ccxt_tick.py
│       ├── ccxt_orderbook.py
│       └── ccxt_funding.py
├── brokers/
│   ├── bbroker.py              # 现有(不变)
│   ├── tickbroker.py           # Tick/OrderBook撮合
│   └── mixbroker.py            # Tick+Bar混合撮合（finalize_bar模式）
├── cerebro.py                  # 增加add_channel() + 批处理通知
└── strategy.py                 # 增加on_tick/on_orderbook等回调
```

详细设计见 [TICK_LEVEL_DESIGN_PART2.md](./TICK_LEVEL_DESIGN_PART2.md)
