- --

title: 观察器
description: 监控和记录策略行为

- --

# 观察器

观察器在回测期间监控和记录策略行为。与分析器不同，观察器专注于数据收集而非计算。

## 基本用法

```python

# 在 cerebro 设置时添加观察器

cerebro.addobserver(bt.observers.DrawDown)

# 或禁用默认观察器

cerebro.run(stdstats=False)  # 禁用默认观察器

```bash

## 内置观察器

### DrawDown (回撤)

```python
cerebro.addobserver(bt.observers.DrawDown)

# 在策略中访问

class MyStrategy(bt.Strategy):
    def next(self):

# 访问回撤观察器
        if hasattr(self, 'observers'):
            drawdown = self.observers.drawdown
            print(f'回撤: {drawdown.drawdown[0]:.2%}')

```bash

### Broker (经纪人)

```python
cerebro.addobserver(bt.observers.Broker)

# 跟踪:

# - 现金余额

# - 组合价值

# - 持仓

```bash

### Trades (交易)

```python
cerebro.addobserver(bt.observers.Trades)

# 记录每笔交易

# 入场/出场价格

# 交易盈亏

```bash

### BuySell (买卖)

```python
cerebro.addobserver(bt.observers.BuySell)

# 在图表上标记买卖点

```bash

### DataTrades (数据交易)

```python
cerebro.addobserver(bt.observers.DataTrades)

# 按数据源记录交易

```bash

### Benchmark (基准)

```python

# 添加基准数据源

data = bt.feeds.YahooFinanceData(dataname='AAPL', ...)
bench = bt.feeds.YahooFinanceData(dataname='SPY', ...)

cerebro.adddata(data)
cerebro.adddata(bench)

# 添加基准观察器

cerebro.addobserver(bt.observers.Benchmark, data=bench)

```bash

### LogReturns (对数收益)

```python
cerebro.addobserver(bt.observers.LogReturns)

# 记录随时间变化的收益

# 用于分析收益模式

```bash

### TimeReturn (时间收益)

```python
cerebro.addobserver(bt.observers.TimeReturn)

# 按时间段统计收益

# 可以指定时间周期

cerebro.addobserver(bt.observers.TimeReturn, timeframe=bt.TimeFrame.Days)

```bash

## 默认观察器

当您运行 `cerebro.run()` 而不带 `stdstats=False` 时，这些观察器会自动添加：

| 观察器 | 用途 |

|----------|---------|

| `Broker` | 跟踪经纪人状态 |

| `Trades` | 记录所有交易 |

| `BuySell` | 在图表上标记买卖 |

| `DrawDown` | 跟踪回撤指标 |

## 自定义观察器

创建您自己的观察器：

```python
class TradeLogger(bt.Observer):
    """
    记录所有交易的自定义观察器。
    """
    _stclock = True  # 使用系统时钟
    _ltype = 2        # 观察器类型
    lines = ('dummy',)  # 必须至少有一条线

    params = dict(enabled=True)

    def start(self):

# 注册到 lineiterators
        if hasattr(self, '_owner') and self._owner:
            if hasattr(self._owner, '_lineiterators'):
                if self._ltype in self._owner._lineiterators:
                    if self not in self._owner._lineiterators[self._ltype]:
                        self._owner._lineiterators[self._ltype].append(self)

    def next(self):
        self.lines.dummy[0] = 0  # 必须设置一个值

# 添加到 cerebro

cerebro.addobserver(TradeLogger)

```bash

## 观察器 vs 分析器

| 特性 | 观察器 | 分析器 |

|---------|----------|----------|

| **用途**| 数据收集 | 计算 |

|**调用时机**| 每根 K 线 | 回测后 |

|**输出**| 时间序列数据 | 汇总统计 |

|**绘图** | 可绘制 | 不绘制 |

## 访问观察器数据

### 回测后

```python
strats = cerebro.run()
strat = strats[0]

# 访问观察器数据

print(strat.observers.broker.getvalue())
print(strat.observers.drawdown.drawdown)

```bash

### 在策略中

```python
class MyStrategy(bt.Strategy):
    def next(self):

# 如果有观察器则访问
        if hasattr(self, 'observers'):
            if hasattr(self.observers, 'drawdown'):
                dd = self.observers.drawdown.drawdown[0]
                if dd > 0.10:  # 10% 回撤
                    self.log(f'高回撤: {dd:.2%}')

```bash

## 禁用观察器

```python

# 禁用默认观察器

cerebro.run(stdstats=False)

# 添加特定观察器

cerebro.addobserver(bt.observers.DrawDown)
cerebro.addobserver(bt.observers.Trades)

```bash

## 使用观察器绘图

观察器自动出现在图表上：

```python
import matplotlib.pyplot as plt

cerebro.plot()
plt.show()

# 观察器显示为子图:

# - 回撤

# - 交易

# - 买入/卖出标记

```bash

## 下一步学习

- [绘图](plotting_zh.md) - 可视化结果
- [分析器](analyzers_zh.md) - 计算性能指标
