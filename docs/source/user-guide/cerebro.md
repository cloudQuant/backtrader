- --

title: Cerebro API Reference
description: Core backtesting engine API

- --

# Cerebro API Reference

`Cerebro` is the core backtesting engine that orchestrates strategies, data feeds, brokers, and analyzers.

## Basic Usage

```python
import backtrader as bt

# Create cerebro instance

cerebro = bt.Cerebro()

# Add components

cerebro.adddata(data)
cerebro.addstrategy(MyStrategy, param1=value1)
cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')

# Run backtest

results = cerebro.run()

# Plot results

cerebro.plot()

```bash

## Constructor

```python
bt.Cerebro()

```bash
Creates a new Cerebro instance.

## Data Management

### adddata

```python
cerebro.adddata(data, name=None)

```bash
Add a data feed to the system.

- **data**: Data feed instance
- **name**: Optional name for the data feed

```python
data = bt.feeds.YahooFinanceData(dataname='AAPL')
cerebro.adddata(data, name='AAPL')

```bash

### resampledata

```python
cerebro.resampledata(data, timeframe=bt.TimeFrame.Days, compression=1)

```bash
Add and resample data to a different timeframe.

### replaydata

```python
cerebro.replaydata(data, timeframe=bt.TimeFrame.Weeks)

```bash
Add and replay data on a different timeframe.

## Strategy Management

### addstrategy

```python
cerebro.addstrategy(strategy_class, *args, **kwargs)

```bash
Add a strategy to the system.

```python
cerebro.addstrategy(MyStrategy,
                   period=20,
                   threshold=1.5)

```bash

### optstrategy

```python
cerebro.optstrategy(strategy_class, *args, **kwargs)

```bash
Add strategy for optimization. Pass iterables for parameters to optimize.

```python
cerebro.optstrategy(MyStrategy,
                   period=[10, 20, 30],
                   threshold=[1.0, 1.5, 2.0])

```bash

### runstrategies

```python
cerebro.runstrategies()

```bash
Run the backtest (same as `run()`).

## Broker Management

### getbroker

```python
broker = cerebro.getbroker()

```bash
Get the broker instance.

### setbroker

```python
cerebro.setbroker(broker_instance)

```bash
Set a custom broker instance.

### broker_setcash

```python
cerebro.broker_setcash(100000)

```bash
Set initial cash.

### broker_setcommission

```python
cerebro.broker_setcommission(commission=0.001)
cerebro.broker_setcommission(commission=0.001, leverage=10.0)

```bash
Set commission structure.

## Analyzer Management

### addanalyzer

```python
cerebro.addanalyzer(analyzer_class, *args, **kwargs)

```bash
Add an analyzer to the system.

```python
cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')

```bash

## Observer Management

### addobserver

```python
cerebro.addobserver(observer_class, *args, **kwargs)

```bash
Add an observer to the system.

```python
cerebro.addobserver(bt.observers.DrawDown)

```bash

## Writer Management

### addwriter

```python
cerebro.addwriter(writer_class, *args, **kwargs)

```bash
Add a writer for output.

```python
cerebro.addwriter(bt.WriterFile, csv=True, out='results.csv')

```bash

## Execution

### run

```python
results = cerebro.run()

```bash
Execute the backtest.

Returns a list of strategy instances.

```python
strats = cerebro.run()
strat = strats[0]

# Access analyzers

sharpe = strat.analyzers.sharpe.get_analysis()
drawdown = strat.analyzers.drawdown.get_analysis()

```bash

### runstop

```python
cerebro.runstop = False  # Set to True to stop execution

```bash
Stop flag for early termination.

## Plotting

### plot

```python
cerebro.plot(plotter=None, figsize=None, style='plotly', **kwargs)

```bash
Plot the results.

```python

# Plotly (interactive, recommended)

cerebro.plot(style='plotly')

# Matplotlib (static)

cerebro.plot(style='matplotlib')

# Bokeh (interactive)

cerebro.plot(style='bokeh')

```bash

## Configuration

### stdstats

```python
cerebro.stdstats = True  # Enable standard observers

```bash
Enable/disable standard observers (cash, value, trades).

### maxcpus

```python
cerebro.maxcpus = None  # Use all CPUs

cerebro.maxcpus = 4     # Use 4 CPUs

```bash
Set CPU limit for optimization.

## Performance Options

### runonce

```python
cerebro.runonce = True  # Use vectorized mode (faster)

cerebro.runonce = False  # Use event-driven mode

```bash
Execution mode:

- `True`: Vectorized (runonce) - faster for simple strategies
- `False`: Event-driven (runnext) - more control

### preload

```python
cerebro.preload = True  # Load all data into memory

```bash
Preload data into memory for faster access.

### exactbars

```python
cerebro.exactbars = 1  # Keep minimum bars in memory

```bash
Memory optimization for long backtests.

## Complete Example

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

# Create cerebro

cerebro = bt.Cerebro()

# Add data

data = bt.feeds.YahooFinanceData(
    dataname='AAPL',
    fromdate=datetime(2020, 1, 1),
    todate=datetime(2023, 12, 31)
)
cerebro.adddata(data)

# Add strategy

cerebro.addstrategy(SmaCross, fast=10, slow=30)

# Set broker parameters

cerebro.broker_setcash(100000)
cerebro.broker_setcommission(commission=0.001)

# Add analyzers

cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', riskfreerate=0.0)
cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')

# Run

results = cerebro.run()
strat = results[0]

# Print results

print(f"Final Portfolio Value: {cerebro.broker.getvalue():.2f}")
print(f"Sharpe Ratio: {strat.analyzers.sharpe.get_analysis()['sharperatio']:.2f}")
print(f"Max Drawdown: {strat.analyzers.drawdown.get_analysis()['max']['drawdown']:.2f}%")

# Plot

cerebro.plot(style='plotly', volume=False)

```bash

## Properties

| Property | Type | Default | Description |

|----------|------|---------|-------------|

| `runonce` | bool | True | Vectorized execution |

| `preload` | bool | True | Preload data |

| `maxcpus` | int | None | CPU limit for optimization |

| `stdstats` | bool | True | Standard observers |

| `exactbars` | int | 0 | Memory optimization level |

## Methods Reference

| Method | Description |

|--------|-------------|

| `adddata()` | Add data feed |

| `resampledata()` | Add and resample data |

| `replaydata()` | Add and replay data |

| `addstrategy()` | Add strategy |

| `optstrategy()` | Add strategy for optimization |

| `addanalyzer()` | Add analyzer |

| `addobserver()` | Add observer |

| `addwriter()` | Add writer |

| `setbroker()` | Set custom broker |

| `getbroker()` | Get broker instance |

| `broker_setcash()` | Set initial cash |

| `broker_setcommission()` | Set commission |

| `run()` | Run backtest |

| `plot()` | Plot results |
