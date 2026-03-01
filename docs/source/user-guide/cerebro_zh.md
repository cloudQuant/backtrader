---
title: Cerebro API 参考
description: 核心回测引擎 API
---

# Cerebro API 参考

`Cerebro` 是核心回测引擎，用于协调策略、数据源、经纪人和分析器。

## 基本用法

```python
import backtrader as bt

# 创建 cerebro 实例
cerebro = bt.Cerebro()

# 添加组件
cerebro.adddata(data)
cerebro.addstrategy(MyStrategy, param1=value1)
cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')

# 运行回测
results = cerebro.run()

# 绘图结果
cerebro.plot()
```

## 构造函数

```python
bt.Cerebro()
```

创建一个新的 Cerebro 实例。

## 数据管理

### adddata

```python
cerebro.adddata(data, name=None)
```

向系统添加数据源。

- **data**: 数据源实例
- **name**: 数据源的可选名称

```python
data = bt.feeds.YahooFinanceData(dataname='AAPL')
cerebro.adddata(data, name='AAPL')
```

### resampledata

```python
cerebro.resampledata(data, timeframe=bt.TimeFrame.Days, compression=1)
```

添加数据并将其重采样到不同的时间周期。

### replaydata

```python
cerebro.replaydata(data, timeframe=bt.TimeFrame.Weeks)
```

添加数据并在不同的时间周期上重放。

## 策略管理

### addstrategy

```python
cerebro.addstrategy(strategy_class, *args, **kwargs)
```

向系统添加策略。

```python
cerebro.addstrategy(MyStrategy,
                   period=20,
                   threshold=1.5)
```

### optstrategy

```python
cerebro.optstrategy(strategy_class, *args, **kwargs)
```

添加策略用于优化。为要优化的参数传递可迭代对象。

```python
cerebro.optstrategy(MyStrategy,
                   period=[10, 20, 30],
                   threshold=[1.0, 1.5, 2.0])
```

### runstrategies

```python
cerebro.runstrategies()
```

运行回测（与 `run()` 相同）。

## 经纪人管理

### getbroker

```python
broker = cerebro.getbroker()
```

获取经纪人实例。

### setbroker

```python
cerebro.setbroker(broker_instance)
```

设置自定义经纪人实例。

### broker_setcash

```python
cerebro.broker_setcash(100000)
```

设置初始资金。

### broker_setcommission

```python
cerebro.broker_setcommission(commission=0.001)
cerebro.broker_setcommission(commission=0.001, leverage=10.0)
```

设置佣金结构。

## 分析器管理

### addanalyzer

```python
cerebro.addanalyzer(analyzer_class, *args, **kwargs)
```

向系统添加分析器。

```python
cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
```

## 观察器管理

### addobserver

```python
cerebro.addobserver(observer_class, *args, **kwargs)
```

向系统添加观察器。

```python
cerebro.addobserver(bt.observers.DrawDown)
```

## 写入器管理

### addwriter

```python
cerebro.addwriter(writer_class, *args, **kwargs)
```

添加输出写入器。

```python
cerebro.addwriter(bt.WriterFile, csv=True, out='results.csv')
```

## 执行

### run

```python
results = cerebro.run()
```

执行回测。

返回策略实例列表。

```python
strats = cerebro.run()
strat = strats[0]

# 访问分析器
sharpe = strat.analyzers.sharpe.get_analysis()
drawdown = strat.analyzers.drawdown.get_analysis()
```

### runstop

```python
cerebro.runstop = False  # 设置为 True 以停止执行
```

提前终止的停止标志。

## 绘图

### plot

```python
cerebro.plot(plotter=None, figsize=None, style='plotly', **kwargs)
```

绘制结果。

```python
# Plotly (交互式，推荐)
cerebro.plot(style='plotly')

# Matplotlib (静态)
cerebro.plot(style='matplotlib')

# Bokeh (交互式)
cerebro.plot(style='bokeh')
```

## 配置

### stdstats

```python
cerebro.stdstats = True  # 启用标准观察器
```

启用/禁用标准观察器（资金、价值、交易）。

### maxcpus

```python
cerebro.maxcpus = None  # 使用所有 CPU
cerebro.maxcpus = 4     # 使用 4 个 CPU
```

设置优化的 CPU 限制。

## 性能选项

### runonce

```python
cerebro.runonce = True  # 使用向量化模式 (更快)
cerebro.runonce = False  # 使用事件驱动模式
```

执行模式：
- `True`: 向量化 (runonce) - 简单策略更快
- `False`: 事件驱动 (runnext) - 更多控制

### preload

```python
cerebro.preload = True  # 将所有数据加载到内存
```

将数据预加载到内存以加快访问。

### exactbars

```python
cerebro.exactbars = 1  # 在内存中保留最少的K线
```

长回测的内存优化。

## 完整示例

```python
import backtrader as bt
from datetime import datetime

class SmaCross(bt.Strategy):
    params = (('fast', 10), ('slow', 30))

    def __init__(self):
        super().__init__()
        fast_ma = bt.indicators.SMA(period=self.params.fast)
        slow_ma = bt.indicators.SMA(period=self.params.slow)
        self.crossover = bt.indicators.CrossOver(fast_ma, slow_ma)

    def next(self):
        if not self.position and self.crossover > 0:
            self.buy(size=100)
        elif self.position and self.crossover < 0:
            self.close()

# 创建 cerebro
cerebro = bt.Cerebro()

# 添加数据
data = bt.feeds.YahooFinanceData(
    dataname='AAPL',
    fromdate=datetime(2020, 1, 1),
    todate=datetime(2023, 12, 31)
)
cerebro.adddata(data)

# 添加策略
cerebro.addstrategy(SmaCross, fast=10, slow=30)

# 设置经纪人参数
cerebro.broker_setcash(100000)
cerebro.broker_setcommission(commission=0.001)

# 添加分析器
cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', riskfreerate=0.0)
cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')

# 运行
results = cerebro.run()
strat = results[0]

# 打印结果
print(f"最终组合价值: {cerebro.broker.getvalue():.2f}")
print(f"夏普比率: {strat.analyzers.sharpe.get_analysis()['sharperatio']:.2f}")
print(f"最大回撤: {strat.analyzers.drawdown.get_analysis()['max']['drawdown']:.2f}%")

# 绘图
cerebro.plot(style='plotly', volume=False)
```

## 属性

| 属性 | 类型 | 默认值 | 描述 |
|------|------|--------|------|
| `runonce` | bool | True | 向量化执行 |
| `preload` | bool | True | 预加载数据 |
| `maxcpus` | int | None | 优化的 CPU 限制 |
| `stdstats` | bool | True | 标准观察器 |
| `exactbars` | int | 0 | 内存优化级别 |

## 方法参考

| 方法 | 描述 |
|------|------|
| `adddata()` | 添加数据源 |
| `resampledata()` | 添加并重采样数据 |
| `replaydata()` | 添加并重放数据 |
| `addstrategy()` | 添加策略 |
| `optstrategy()` | 添加策略用于优化 |
| `addanalyzer()` | 添加分析器 |
| `addobserver()` | 添加观察器 |
| `addwriter()` | 添加写入器 |
| `setbroker()` | 设置自定义经纪人 |
| `getbroker()` | 获取经纪人实例 |
| `broker_setcash()` | 设置初始资金 |
| `broker_setcommission()` | 设置佣金 |
| `run()` | 运行回测 |
| `plot()` | 绘制结果 |
