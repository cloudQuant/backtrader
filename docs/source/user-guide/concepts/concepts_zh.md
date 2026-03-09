- --

title: 基本概念
description: 理解 Backtrader 的核心概念

- --

# 基本概念

Backtrader 使用事件驱动架构来回测交易策略。理解这些核心概念对于有效开发策略至关重要。

## 核心组件

```mermaid
flowchart TD
    Data[数据源] --> Cerebro[Cerebro 引擎]
    Cerebro --> Strategy[策略]
    Cerebro --> Broker[经纪人]
    Strategy -->|订单| Broker

    Broker -->|成交| Strategy

    Cerebro --> Analyzer[分析器]
    Cerebro --> Observer[观察器]

```bash

## Cerebro

- *Cerebro** 是协调整个回测过程的中央引擎。

```python
cerebro = bt.Cerebro()

# 添加组件

cerebro.adddata(data)           # 添加数据源

cerebro.addstrategy(MyStrategy)  # 添加策略

cerebro.addanalyzer(bt.analyzers.SharpeRatio)  # 添加分析器

# 配置

cerebro.broker.setcash(10000)   # 设置初始资金

cerebro.broker.setcommission(0.001)  # 设置佣金

# 运行

results = cerebro.run()

```bash

## 数据源

数据源为您的策略提供市场数据。Backtrader 支持多种数据源。

### 创建数据源

```python

# 从 CSV

data = bt.feeds.CSVGeneric(
    dataname='AAPL.csv',
    datetime=0,    # 日期时间列索引
    open=1,        # 开盘价列索引
    high=2,        # 最高价列索引
    low=3,         # 最低价列索引
    close=4,       # 收盘价列索引
    volume=5,      # 成交量列索引
    dtformat='%Y-%m-%d'
)

# 从 Pandas DataFrame

import pandas as pd
df = pd.read_csv('data.csv')
data = bt.feeds.PandasData(dataname=df)

# 从 Yahoo Finance

data = bt.feeds.YahooFinanceData(
    dataname='AAPL',
    fromdate=datetime(2023, 1, 1),
    todate=datetime(2023, 12, 31)
)

```bash

### 在策略中访问数据

```python
class MyStrategy(bt.Strategy):
    def next(self):

# 当前 K 线数据
        current_price = self.data.close[0]
        current_high = self.data.high[0]
        current_low = self.data.low[0]

# 前一根 K 线数据
        previous_price = self.data.close[-1]

# 数据长度
        print(f"当前 K 线: {len(self.data)}")

```bash

## Lines (时间序列)

- *Lines** 是时间序列数据结构。每个数据源都有预定义的 lines：

| Line | 描述 |

|------|------|

| `datetime` | K 线时间戳 |

| `open` | 开盘价 |

| `high` | 最高价 |

| `low` | 最低价 |

| `close` | 收盘价 |

| `volume` | 成交量 |

| `openinterest` | 持仓量 (期货) |

### 访问 Line 数据

```python

# 当前值 (索引 0)

current_close = self.data.close[0]

# 历史值 (负索引)

prev_close = self.data.close[-1]   # 1 根 K 线前

prev_close2 = self.data.close[-2]  # 2 根 K 线前

# Line 长度

data_length = len(self.data.close)

```bash

## 策略

策略包含您的交易逻辑。

```python
class MyStrategy(bt.Strategy):
    """
    策略参数
    """
    params = (
        ('period', 20),
        ('threshold', 0.5),
    )

    def __init__(self):
        """
        初始化指标和计算
        """
        super().__init__()
        self.sma = bt.indicators.SMA(self.data.close, period=self.p.period)

    def next(self):
        """
        每根 K 线调用
        """
        if self.sma[0] > self.data.close[0]:
            self.buy()

```bash

### 策略生命周期

```mermaid
stateDiagram-v2
    [*] --> __init__: 策略创建
    __init__ --> prenext: minperiod 之前
    prenext --> prenext: 处理 K 线
    prenext --> nextstart: 达到 minperiod
    nextstart --> next: 过渡完成
    next --> next: 正常运行
    next --> [*]: 回测结束

```bash

| 阶段 | 描述 |

|------|------|

| `__init__` | 初始化策略，创建指标 |

| `prenext()` | 指标数据不足时调用 |

| `nextstart()` | 首次满足 minperiod 时调用一次 |

| `next()` | 满足 minperiod 后每根 K 线调用 |

## 指标

指标计算技术分析值。

### 内置指标

```python

# 移动平均线

sma = bt.indicators.SMA(self.data.close, period=20)
ema = bt.indicators.EMA(self.data.close, period=20)

# 动量指标

rsi = bt.indicators.RSI(self.data.close, period=14)
macd = bt.indicators.MACD(self.data.close)

# 波动率指标

atr = bt.indicators.ATR(self.data, period=14)
bollinger = bt.indicators.BollingerBands(self.data.close)

```bash

### 访问指标值

```python
class MyStrategy(bt.Strategy):
    def __init__(self):
        super().__init__()
        self.sma = bt.indicators.SMA(self.data.close, period=20)

    def next(self):

# 当前 SMA 值
        current_sma = self.sma[0]

# 前一 SMA 值
        previous_sma = self.sma[-1]

```bash

## 经纪人

经纪人模拟订单执行和组合管理。

```python

# 配置经纪人

cerebro.broker.setcash(10000)           # 设置初始资金

cerebro.broker.setcommission(0.001)     # 设置佣金 (0.1%)

cerebro.broker.set_slippage_perc(0.5)   # 设置滑点 (0.5%)

```bash

### 订单

```python

# 市价单

self.buy()                              # 买入默认数量

self.buy(size=100)                      # 买入指定数量

self.sell()                             # 卖出平仓

self.close()                            # 平仓

# 限价单

self.buy(price=100.5)                   # 以指定价格买入

self.sell(limit=105.0)                  # 以限价卖出

# 止损单

self.sell(stop=95.0)                    # 止损卖出

```bash

## 持仓

跟踪您当前的持仓。

```python
class MyStrategy(bt.Strategy):
    def next(self):

# 检查是否有持仓
        if self.position:
            print(f"持仓数量: {self.position.size}")

# 检查持仓详情
        if self.position:
            print(f"入场价格: {self.position.price}")
            print(f"当前盈亏: {self.position.price * self.position.size}")

```bash

## 下一步学习

- [指标](indicators.md) - 探索所有内置指标
- [策略](strategies.md) - 高级策略模式
- [分析器](analyzers.md) - 性能分析
- [数据源](data-feeds.md) - 更多数据源
