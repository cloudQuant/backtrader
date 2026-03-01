---
title: 快速开始教程
description: 在 5 分钟内创建您的第一个回测策略
---

# 快速开始教程

学习如何创建一个简单的交易策略并使用历史数据进行回测。

## 您的第一个策略

```python
import backtrader as bt

class SimpleStrategy(bt.Strategy):
    """
    简单移动平均线交叉策略。
    当短期均线向上穿越长期均线时买入。
    当短期均线向下穿越长期均线时卖出。
    """

    params = (
        ('short_period', 10),
        ('long_period', 30),
    )

    def __init__(self):
        # 重要：首先调用 super().__init__()
        super().__init__()

        # 计算移动平均线
        self.short_ma = bt.indicators.SMA(self.data.close, period=self.p.short_period)
        self.long_ma = bt.indicators.SMA(self.data.close, period=self.p.long_period)

        # 交叉指标
        self.crossover = bt.indicators.CrossOver(self.short_ma, self.long_ma)

    def next(self):
        # 如果没有持仓
        if not self.position:
            # 当短期均线向上穿越长期均线时买入
            if self.crossover > 0:
                self.buy()
        else:
            # 当短期均线向下穿越长期均线时卖出
            if self.crossover < 0:
                self.sell()
```

## 运行回测

```python
# 创建 cerebro 实例
cerebro = bt.Cerebro()

# 添加策略
cerebro.addstrategy(SimpleStrategy)

# 加载数据 (以 Yahoo Finance 为例)
data = bt.feeds.YahooFinanceData(
    dataname='AAPL',
    fromdate=datetime.datetime(2023, 1, 1),
    todate=datetime.datetime(2023, 12, 31)
)
cerebro.adddata(data)

# 设置初始资金
cerebro.broker.setcash(10000.0)

# 运行回测
results = cerebro.run()

# 打印最终组合价值
print(f'最终组合价值: {cerebro.broker.getvalue():.2f}')
```

## 绘制结果

```python
# 绘制结果
cerebro.plot(style='plotly')  # 交互式图表
# 或者
# cerebro.plot(style='matplotlib')  # 静态图表
```

## 完整示例

```python
import backtrader as bt
import datetime

class SimpleStrategy(bt.Strategy):
    params = (
        ('short_period', 10),
        ('long_period', 30),
    )

    def __init__(self):
        super().__init__()
        self.short_ma = bt.indicators.SMA(self.data.close, period=self.p.short_period)
        self.long_ma = bt.indicators.SMA(self.data.close, period=self.p.long_period)
        self.crossover = bt.indicators.CrossOver(self.short_ma, self.long_ma)

    def next(self):
        if not self.position:
            if self.crossover > 0:
                self.buy()
        else:
            if self.crossover < 0:
                self.sell()

# 创建并运行
cerebro = bt.Cerebro()
cerebro.addstrategy(SimpleStrategy)

# 添加数据 (以 CSV 文件为例)
data = bt.feeds.CSVGeneric(
    dataname='data.csv',
    datetime=0,
    open=1,
    high=2,
    low=3,
    close=4,
    volume=5,
    dtformat='%Y-%m-%d'
)
cerebro.adddata(data)

# 设置经纪人
cerebro.broker.setcash(10000.0)
cerebro.broker.setcommission(commission=0.001)  # 0.1% 佣金

# 运行
print(f'起始组合价值: {cerebro.broker.getvalue():.2f}')
results = cerebro.run()
print(f'最终组合价值: {cerebro.broker.getvalue():.2f}')

# 绘图
cerebro.plot(style='plotly')
```

## 策略说明

这个策略使用了：

1. **简单移动平均线 (SMA)** - 计算价格的平均值
2. **交叉指标 (CrossOver)** - 检测两条均线的穿越
3. **持仓检查** - 避免重复开仓

### 策略参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `short_period` | 10 | 短期均线周期 |
| `long_period` | 30 | 长期均线周期 |

### 调整参数

```python
# 自定义参数运行
cerebro.addstrategy(SimpleStrategy, short_period=5, long_period=20)
```

## 下一步学习

- [基本概念](concepts.md) - 理解 Cerebro、数据源、策略
- [指标](indicators.md) - 探索 60+ 内置指标
- [数据源](data-feeds.md) - 从各种来源加载数据
- [分析器](analyzers.md) - 分析策略性能
