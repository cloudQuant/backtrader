# Backtrader Tick 级回测与实盘交易架构设计

> 版本: v1.1 | 日期: 2026-02-28 | 状态: 设计阶段（已优化）

- --

## 1. 需求概述

### 1.1 当前能力

- Strategy 只有`next()`回调，每根 K 线触发一次
- 数据源基于`OHLCDateTime`固定 7 条 lines
- Broker 用 bar 的 OHLC 进行订单撮合

### 1.2 新增需求

| 需求 | 说明 |

|------|------|

| Tick 数据 | 逐笔成交(price,volume,direction)，毫秒级 |

| OrderBook 数据 | 盘口深度(bids/asks 多档)，100ms 级 |

| FundingRate 数据 | 资金费率，8 小时级 |

| 自定义数据通道 | 用户可注册任意数据类型 |

| 纯 Tick 回测 | 无 K 线，纯 tick 驱动 |

| 混合模式 | K 线+Tick/OrderBook 共存 |

| 纯 K 线模式 | 向后兼容（不变） |

| Tick 级 Broker | 用 tick/orderbook 撮合订单 |

- --

## 2. 现有架构分析

### 2.1 LineSeries 体系核心链路

```bash
LineBuffer (array.array 存储, idx 指针)
  → LineSingle → LineRoot
    → LineSeries (多行容器, Lines 管理命名访问)
      → DataSeries (OHLCV 标准 lines + timeframe)
        → OHLCDateTime (datetime line)
          → AbstractDataBase (数据加载/过滤)
            → DataBase (replay/resample)

```bash

### 2.2 LineSeries 核心约束

| 约束 | 说明 |

|------|------|

| 定长时间序列 | 每条 line 是等长 array.array('d')，通过 idx 同步 |

| 标量值 | 每个时间点每条 line 只有一个 float 值 |

| forward/rewind | 所有 lines 同步前进/后退，由 clock 驱动 |

| minperiod | 基于历史数据量的最小周期管理 |

| idx=0 语义 | 当前活跃值始终在 index 0 |

| runonce | 向量化预计算，要求数据可预加载 |

### 2.3 Cerebro 主循环

- *_runnext**: while 循环 → 每个 data.next() → dt0=min(dts) → _brokernotify() → strategy._next()

- *_runonce**: strat._once()预计算 → for 循环 advance → _brokernotify() → strat._oncepost(dt)

关键: **主循环以 bar 为单位驱动**，所有 data 同步推进到 dt0。

- --

## 3. Channel 是否参与 LineSeries 体系：深度分析

### 3.1 方案 A：参与 LineSeries

将 Tick/OrderBook 作为特殊 DataBase 子类，每个数据点作为一个"bar"。

#### 优势

- **复用基础设施**: forward/rewind/qbuffer/bindings 全部可用
- **指标直接可用**: `bt.indicators.SMA(tick_data.price, period=100)`
- **Observer/Analyzer 可用**: TradeAnalyzer、SharpeRatio 无需修改
- **数据同步已有**: Cerebro 时间排序、rewind 机制可处理多频率对齐
- **内存管理已有**: qbuffer、exactbars 直接可用
- **绘图可用**: plot 系统可绘制 tick 数据
- **学习成本低**: 用户只需现有 API

#### 劣势

- **OrderBook 无法表达**: 2D 结构(档位×bid/ask)无法用固定 float lines 表达完整深度，只能退化为 best_bid/best_ask 摘要
- **性能开销巨大**: 每 tick 执行 forward→filter 链→check→advance，每秒数千 tick 不可接受
- **语义不匹配**: tick 是 append-only 流，不需要 rewind；OrderBook 是 snapshot 覆盖语义
- **minperiod 冲突**: tick 的 minperiod 语义与 bar 完全不同
- **时间对齐困难**: tick 频率远高于 bar，导致 bar 数据大量 rewind
- **runonce 不兼容**: tick 百万级数据预加载不现实
- **数据类型受限**: 只能存 float，无法存 string(trade_id)、嵌套结构
- **clock 污染**: tick 作为 datas[]成员干扰 bar 时间同步

#### 性能定量分析

```bash
BTC/USDT, 1 分钟 K 线, tick 约 200/秒, 每分钟 12000 tick

LineSeries.forward() 每条 line: ~220ns
4 条 line(datetime,price,vol,dir) × 12000 tick = ~10.6ms/分钟
加上 filter 链、_check: 估计 50-100ms/分钟
一天 1440 分钟: 72-144 秒 overhead

对比 deque.append: ~30ns/tick
12000 × 30ns = 0.36ms/分钟, 一天 0.5 秒

LineSeries 的 overhead 约为 deque 的 200 倍。

```bash

### 3.2 方案 B：完全独立

DataChannel 不继承 LineSeries，用 deque 作缓冲。

#### 优势

- 数据结构自由（OrderBook 完整多档、trade_id 字符串）
- 极低 overhead（deque.append）
- 语义清晰、不污染现有系统、零回归风险
- 支持可变长数据、C++移植接口清晰

#### 劣势

- 无法直接使用指标系统
- Observer/Analyzer 不兼容，需适配
- 绘图、Writer 不兼容
- 用户需学习两套概念

### 3.3 方案 C（推荐）：独立 DataChannel + LineSeries 桥接

Channel 本身独立，提供**可选桥接**机制投影到 LineSeries。

```python

# Channel 本身独立高性能

tick_channel = TickChannel(symbol='BTC/USDT', dataname='ticks.csv')

# 可选桥接到 LineSeries 使用指标

tick_as_data = tick_channel.to_lineseries()
sma = bt.indicators.SMA(tick_as_data.price, period=100)

# 或直接用 Channel 内置高性能计算

vwap = tick_channel.vwap(period=100)

```bash

### 3.4 综合对比

| 维度 | A:完全参与 | B:完全独立 | C:独立+桥接 |

|------|:---------:|:---------:|:----------:|

| OrderBook 完整表达 | ❌ | ✅ | ✅ |

| Tick 性能 | ❌慢 200× | ✅最优 | ✅最优 |

| 指标可用 | ✅直接 | ❌ | ✅可选桥接 |

| 自定义数据结构 | ❌仅 float | ✅ | ✅ |

| 向后兼容 | ⚠️有风险 | ✅零风险 | ✅零风险 |

| runonce 兼容 | ❌ | ✅不参与 | ✅不参与 |

| C++移植 | ❌耦合重 | ✅接口清晰 | ✅接口清晰 |

| 实现复杂度 | ⚠️中等 | ✅简单 | ⚠️中等 |

### 3.5 最终决策

- *推荐方案 C：独立 DataChannel + 可选 LineSeries 桥接**

理由: 性能是硬约束(200×差距)、OrderBook 是 2D 数据、桥接按需使用零开销、零回归风险、C++友好。

### 3.6 优化补充（v1.1 更新）

- *核心设计决策**：

1. **流式 EventQueue**：使用 StreamingEventQueue 替代全量预加载，内存从 1.7GB 降至~100MB
2. **Bar 事件化**：Bar 以`bar_open/bar_close`事件进入全局 EventQueue，保证与 Tick/OrderBook 严格时间排序
3. **Broker 三件套**：
   - `BackBroker`：bar OHLC 撮合（现有不变）
   - `TickBroker`：纯 tick/OB 撮合
   - `MixBroker`：tick 即时撮合 + bar 兜底撮合
1. **批处理通知**：收集-分发模式，避免同 timestamp 内通知乱序
2. **ChannelBridge 限制**：明确不支持 runonce，强制使用 next 模式
3. **多策略 Channel 共享**：支持 shared 参数控制 Channel 共享模式
4. **回调执行顺序**：
   - broker 处理事件（不立即通知）
   - 分发到策略回调
   - 统一发送 broker 通知
   - next()在主时钟 bar_close 后触发

- --

## 4. 整体架构

```bash
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
│         │     Bridge(可选,不支持 runonce)  │               │
│  ┌──────┴───────────────────────────┴──────────────────┐ │
│  │                Strategy                              │ │
│  │  next()         ← K 线回调(不变)                      │ │
│  │  on_tick()      ← Tick 事件回调                       │ │
│  │  on_orderbook() ← OrderBook 回调                      │ │
│  │  on_bar()       ← Bar 到达时回调（MIX/TICK 模式）       │ │
│  │  on_funding()   ← FundingRate 回调                    │ │
│  │  on_channel()   ← 通用自定义回调                     │ │
│  └──────┬──────────────────────────────────────────────┘ │
│  ┌──────┴──────────────────────────────────────────────┐ │
│  │  BackBroker(bar OHLC 撮合,不变)                       │ │
│  │  TickBroker(tick/OB 撮合,纯 Tick 模式)                  │ │
│  │  MixBroker(tick 即时撮合 + bar 兜底)                   │ │
│  └─────────────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────────────┘

```bash

### 模块划分

```bash
backtrader/
├── channel.py                  # DataChannel 基类 + StreamingEventQueue

├── channels/
│   ├── __init__.py
│   ├── tick.py                 # TickChannel + TickEvent

│   ├── orderbook.py            # OrderBookChannel + OrderBookSnapshot

│   ├── funding.py              # FundingRateChannel + FundingEvent

│   ├── bridge.py               # LineSeries 桥接层（不支持 runonce）

│   └── ccxt/                   # CCXT 实盘实现

│       ├── ccxt_tick.py
│       ├── ccxt_orderbook.py
│       └── ccxt_funding.py
├── brokers/
│   ├── bbroker.py              # 现有(不变)

│   ├── tickbroker.py           # Tick/OrderBook 撮合

│   └── mixbroker.py            # Tick+Bar 混合撮合（finalize_bar 模式）

├── cerebro.py                  # 增加 add_channel() + 批处理通知

└── strategy.py                 # 增加 on_tick/on_orderbook 等回调

```bash
详细设计见 [TICK_LEVEL_DESIGN_PART2.md](./TICK_LEVEL_DESIGN_PART2.md)
