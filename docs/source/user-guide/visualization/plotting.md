---
title: Plotting
description: Visualize backtest results

---
# Plotting

Backtrader provides multiple plotting options to visualize your backtest results.

## Basic Plotting

```python
import backtrader as bt

# Run backtest

cerebro = bt.Cerebro()

# ... add data, strategy, etc.

results = cerebro.run()

# Plot results

cerebro.plot()

```

## Plot Options

### Figure Size

```python

# Set figure size

import matplotlib.pyplot as plt

plt.rcParams['figure.figsize'] = [15, 10]
cerebro.plot()
plt.show()

```

### Style

```python

# Use different style

plt.style.use('dark_background')
cerebro.plot()
plt.show()

```

## Plotly Interactive Plotting

For large datasets (100k+ points), use Plotly for interactive zooming and panning:

```python

# Create cerebro

cerebro = bt.Cerebro()

# Add plot with Plotly

plotter = bt.plot.Plotly(style='plotly', scheme='plotly')
fig = plotter.plot(cerebro, style='plotly')

# Save or show

fig.show()

```

## Plot Schemes

Control plot appearance with schemes:

```python
from backtrader.plot.scheme import Scheme

# Custom scheme

scheme = Scheme(
    title='My Strategy Backtest',
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

## Multiple Data Feeds

```python
cerebro = bt.Cerebro()
cerebro.adddata(data1, name='AAPL')
cerebro.adddata(data2, name='MSFT')

# Plot both feeds

cerebro.plot()

```

## Saving Plots

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

## Custom Plots

### Plotting Indicator Values

```python
class MyStrategy(bt.Strategy):
    def __init__(self):
        self.sma = bt.indicators.SMA(self.data.close, period=20)

    def next(self):

# SMA is automatically plotted
        pass

```

### Disabling Indicator Plots

```python
class MyStrategy(bt.Strategy):
    def __init__(self):
        self.sma = bt.indicators.SMA(self.data.close, period=20)
        self.sma.plotinfo.plot = False  # Don't plot

```

## Bokeh Live Plotting

For real-time visualization during backtesting:

```python
from backtrader.plot import Bokeh

# Create cerebro

cerebro = bt.Cerebro()

# Add live plotting

plotter = Bokeh(style='bar', scheme='plotly')
cerebro.setbroker(plotter.getbroker())

# Run with plotting

strats = cerebro.run(plotter=plotter)
plotter.show()

```

## Plot Examples

### Price and Volume

```python
cerebro = bt.Cerebro()

# Add data

data = bt.feeds.YahooFinanceData(dataname='AAPL', ...)
cerebro.adddata(data)

# Volume is automatically plotted if available

cerebro.plot()

```

### Multiple Indicators

```python
class MyStrategy(bt.Strategy):
    def __init__(self):
        self.sma20 = bt.indicators.SMA(self.data.close, period=20)
        self.sma50 = bt.indicators.SMA(self.data.close, period=50)
        self.rsi = bt.indicators.RSI(self.data.close, period=14)

```

### Drawdown Subplot

Drawdown is automatically plotted as a subplot.

## Next Steps

- [Live Trading](../live-trading/ccxt-guide.md) - Real-time trading
- [Analyzers](analyzers.md) - Performance analysis
