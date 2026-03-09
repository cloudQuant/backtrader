- --

title: 执行阶段系统
description: 理解 Backtrader 的执行阶段

- --

# 执行阶段系统

Backtrader 通过不同的阶段来执行策略，以处理指标和数据源的最小周期要求。

## 执行阶段

```mermaid
stateDiagram-v2
    [*] --> Prenext: 开始
    Prenext --> Prenext: 未达到最小周期
    Prenext --> Nextstart: 达到最小周期
    Nextstart --> Next: 单根 K 线过渡
    Next --> Next: 正常执行
    Next --> [*]: 数据结束

```bash

## 1. Prenext 阶段

- *prenext** 阶段在累积足够的数据 K 线之前运行，此时指标可能还没有产生有效值。

```python
class MyStrategy(bt.Strategy):
    def __init__(self):
        self.sma = bt.indicators.SMA(period=20)

# minperiod = 20

    def prenext(self):

# 当 len(self.data) < self.sma.minperiod 时调用
        print(f"K 线 {len(self)}: 正在累积数据...")

```bash

- *特点：**
- 从第 0 根 K 线运行到 `minperiod - 1`
- 指标可能没有有效值
- 用于初始化和预热

## 2. Nextstart 阶段

- *nextstart** 阶段在首次达到 `minperiod` 时运行一次。

```python
def nextstart(self):

# 当 len(self.data) == self.sma.minperiod 时调用一次
    print(f"K 线 {len(self)}: 第一根有效 K 线！")

# 默认实现会自动调用 next()

```bash

- *特点：**
- 在第 `minperiod` 根 K 线时运行一次
- prenext 和 next 之间的过渡点
- 可重写以实现特殊的首根 K 线逻辑

## 3. Next 阶段

- *next** 阶段是主执行循环。

```python
def next(self):

# 在满足 minperiod 后的每根 K 线调用
    if self.sma[0] > self.data.close[0]:
        self.sell()

```bash

- *特点：**
- 从第 `minperiod` 根 K 线运行到数据结束
- 所有指标都有有效值
- 主要策略逻辑写在这里

## 最小周期系统

每个组件都有一个 `minperiod` 属性，表示产生有效输出前需要多少根 K 线。

```python

# 指标的最小周期

SMA(period=20).minperiod  # 20

EMA(period=12).minperiod  # 12 (内部调整)

RSI(period=14).minperiod  # 15 (14 + 1 用于计算)

# 策略的 minperiod 是其指标的最大值

class MyStrategy(bt.Strategy):
    def __init__(self):
        self.sma20 = bt.indicators.SMA(period=20)
        self.sma50 = bt.indicators.SMA(period=50)

# Strategy.minperiod = 50 (最大值)

```bash

## 实际示例

```python
import backtrader as bt

class PhaseExample(bt.Strategy):
    params = (('period', 20),)

    def __init__(self):
        self.sma = bt.indicators.SMA(period=self.params.period)
        self.prenext_count = 0

    def prenext(self):
        self.prenext_count += 1

# 回测期间不建议使用日志输出

# 请改用 observer

    def nextstart(self):

# 这是第一根有有效 SMA 值的 K 线
        print(f"第一根有效 K 线: {len(self)}")

    def next(self):

# 正常执行
        if len(self) == self.params.period + 1:
            print(f"第二根有效 K 线: SMA = {self.sma[0]:.2f}")

cerebro = bt.Cerebro()
data = bt.feeds.YahooFinanceData(dataname='AAPL',
                                  fromdate=datetime(2020, 1, 1),
                                  todate=datetime(2020, 12, 31))
cerebro.adddata(data)
cerebro.addstrategy(PhaseExample)
cerebro.run()

```bash

## 执行顺序

```mermaid
sequenceDiagram
    participant Data as 数据
    participant Cerebro as Cerebro 引擎
    participant Strategy as 策略
    participant Indicators as 指标

    Data->>Cerebro: 新 K 线
    Cerebro->>Indicators: 计算指标 (始终)
    Indicators-->>Cerebro: 值已更新

    alt 未达到最小周期
        Cerebro->>Strategy: prenext()
    else 刚达到最小周期
        Cerebro->>Strategy: nextstart()
    else 满足最小周期
        Cerebro->>Strategy: next()
    end

    Strategy->>Cerebro: 订单 (可选)
    Cerebro->>Cerebro: 处理订单

```bash

## 关键要点

1. **指标每根 K 线都会更新**- 即使在 prenext 阶段

2.**策略阶段控制执行**- 每个阶段有不同的逻辑
3.**最小周期自动计算**- 从组件中得出
4.**观察器遵循相同模式** - 也有 prenext/nextstart/next

## 最佳实践

```python

# 推荐：使用 minperiod 进行预热

class GoodStrategy(bt.Strategy):
    def __init__(self):
        self.warmup = 50  # 额外的预热 K 线数

    def next(self):
        if len(self) < self.warmup:
            return  # 跳过预热期

# 主逻辑在这里

# 不推荐：假设 prenext 中的指标有效

class BadStrategy(bt.Strategy):
    def prenext(self):
        value = self.sma[0]  # 可能是 NaN 或无效值！

```bash
