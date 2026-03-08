---
title: 绘图
description: 可视化回测结果

---
# 绘图

Backtrader 提供多种绘图选项来可视化您的回测结果。

## 基本绘图

```python
import backtrader as bt

# 运行回测

cerebro = bt.Cerebro()

# ... 添加数据、策略等

results = cerebro.run()

# 绘制结果

cerebro.plot()

```

## 绘图选项

### 图形大小

```python

# 设置图形大小

import matplotlib.pyplot as plt

plt.rcParams['figure.figsize'] = [15, 10]
cerebro.plot()
plt.show()

```

### 样式

```python

# 使用不同样式

plt.style.use('dark_background')
cerebro.plot()
plt.show()

```

## Plotly 交互式绘图

对于大数据集 (10 万+ 点)，使用 Plotly 进行交互式缩放和平移：

```python

# 创建 cerebro

cerebro = bt.Cerebro()

# 使用 Plotly 添加绘图

plotter = bt.plot.Plotly(style='plotly', scheme='plotly')
fig = plotter.plot(cerebro, style='plotly')

# 保存或显示

fig.show()

```

## 绘图方案

使用方案控制绘图外观：

```python
from backtrader.plot.scheme import Scheme

# 自定义方案

scheme = Scheme(
    title='我的策略回测',
    background='white',
    grid=True,
    grid_color='#e0e0e0',
    barup='green',
    bardown='red',
    volup='green',
    voldown='red',
)

cerebro.plot(scheme=scheme)

```

## 多数据源

```python
cerebro = bt.Cerebro()
cerebro.adddata(data1, name='AAPL')
cerebro.adddata(data2, name='MSFT')

# 绘制两个数据源

cerebro.plot()

```

## 保存图表

### Matplotlib

```python
import matplotlib.pyplot as plt

fig = cerebro.plot()
fig.savefig('backtest_results.png', dpi=300, bbox_inches='tight')

```

### Plotly

```python
plotter = bt.plot.Plotly()
fig = plotter.plot(cerebro)
fig.write_html('backtest_results.html')

```

## 自定义绘图

### 绘制指标值

```python
class MyStrategy(bt.Strategy):
    def __init__(self):
        self.sma = bt.indicators.SMA(self.data.close, period=20)

    def next(self):

# SMA 自动绘制
        pass

```

### 禁用指标绘图

```python
class MyStrategy(bt.Strategy):
    def __init__(self):
        self.sma = bt.indicators.SMA(self.data.close, period=20)
        self.sma.plotinfo.plot = False  # 不绘制

```

## Bokeh 实时绘图

用于回测期间的实时可视化：

```python
from backtrader.plot import Bokeh

# 创建 cerebro

cerebro = bt.Cerebro()

# 添加实时绘图

plotter = Bokeh(style='bar', scheme='plotly')
cerebro.setbroker(plotter.getbroker())

# 运行并绘图

strats = cerebro.run(plotter=plotter)
plotter.show()

```

## 绘图示例

### 价格和成交量

```python
cerebro = bt.Cerebro()

# 添加数据

data = bt.feeds.YahooFinanceData(dataname='AAPL', ...)
cerebro.adddata(data)

# 成交量如果可用会自动绘制

cerebro.plot()

```

### 多指标

```python
class MyStrategy(bt.Strategy):
    def __init__(self):
        self.sma20 = bt.indicators.SMA(self.data.close, period=20)
        self.sma50 = bt.indicators.SMA(self.data.close, period=50)
        self.rsi = bt.indicators.RSI(self.data.close, period=14)

```

### 回撤子图

回撤自动绘制为子图。

## 下一步学习

- [实盘交易](../CCXT_LIVE_TRADING_GUIDE.md) - 实时交易
- [分析器](analyzers_zh.md) - 性能分析
