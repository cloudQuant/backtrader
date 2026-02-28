---
title: Observers
description: Monitor and log strategy behavior
---

# Observers

Observers monitor and record strategy behavior during backtesting. Unlike analyzers, observers focus on data collection rather than calculation.

## Basic Usage

```python
# Add observer during cerebro setup
cerebro.addobserver(bt.observers.DrawDown)

# Or disable default observers
cerebro.run(stdstats=False)  # Disable default observers
```

## Built-in Observers

### DrawDown

```python
cerebro.addobserver(bt.observers.DrawDown)

# Access in strategy
class MyStrategy(bt.Strategy):
    def next(self):
        # Access drawdown observer
        if hasattr(self, 'observers'):
            drawdown = self.observers.drawdown
            print(f'Drawdown: {drawdown.drawdown[0]:.2%}')
```

### Broker

```python
cerebro.addobserver(bt.observers.Broker)

# Tracks:
# - Cash balance
# - Portfolio value
# - Positions
```

### Trades

```python
cerebro.addobserver(bt.observers.Trades)

# Records each trade
# Entry/exit prices
# Trade profit/loss
```

### BuySell

```python
cerebro.addobserver(bt.observers.BuySell)

# Marks buy and sell points on plots
```

### DataTrades

```python
cerebro.addobserver(bt.observers.DataTrades)

# Records trades per data feed
```

### DrawDown

```python
# Already added by default with stdstats=True
# Tracks:
# - Current drawdown
# - Maximum drawdown
# - Drawdown duration
```

### Benchmark

```python
# Add a benchmark data feed
data = bt.feeds.YahooFinanceData(dataname='AAPL', ...)
bench = bt.feeds.YahooFinanceData(dataname='SPY', ...)

cerebro.adddata(data)
cerebro.adddata(bench)

# Add benchmark observer
cerebro.addobserver(bt.observers.Benchmark, data=bench)
```

### LogReturns

```python
cerebro.addobserver(bt.observers.LogReturns)

# Logs returns over time
# Useful for analyzing return patterns
```

### TimeReturn

```python
cerebro.addobserver(bt.observers.TimeReturn)

# Returns by time period
# Can specify timeframe
cerebro.addobserver(bt.observers.TimeReturn, timeframe=bt.TimeFrame.Days)
```

## Default Observers

When you run `cerebro.run()` without `stdstats=False`, these observers are added automatically:

| Observer | Purpose |
|----------|---------|
| `Broker` | Track broker state |
| `Trades` | Record all trades |
| `BuySell` | Mark buy/sell on plots |
| `DrawDown` | Track drawdown metrics |

## Custom Observer

Create your own observer:

```python
class TradeLogger(bt.Observer):
    """
    Custom observer that logs all trades.
    """
    _stclock = True  # Use system clock
    _ltype = 2        # Observer type
    lines = ('dummy',)  # Must have at least one line

    params = dict(enabled=True)

    def start(self):
        # Register to lineiterators
        if hasattr(self, '_owner') and self._owner:
            if hasattr(self._owner, '_lineiterators'):
                if self._ltype in self._owner._lineiterators:
                    if self not in self._owner._lineiterators[self._ltype]:
                        self._owner._lineiterators[self._ltype].append(self)

    def next(self):
        self.lines.dummy[0] = 0  # Must set a value

# Add to cerebro
cerebro.addobserver(TradeLogger)
```

## Observer vs Analyzer

| Feature | Observer | Analyzer |
|---------|----------|----------|
| **Purpose** | Data collection | Calculation |
| **When Called** | Every bar | After backtest |
| **Output** | Time series data | Summary statistics |
| **Plotting** | Can be plotted | Not plotted |

## Accessing Observer Data

### After Backtest

```python
strats = cerebro.run()
strat = strats[0]

# Access observer data
print(strat.observers.broker.getvalue())
print(strat.observers.drawdown.drawdown)
```

### In Strategy

```python
class MyStrategy(bt.Strategy):
    def next(self):
        # Access observers if available
        if hasattr(self, 'observers'):
            if hasattr(self.observers, 'drawdown'):
                dd = self.observers.drawdown.drawdown[0]
                if dd > 0.10:  # 10% drawdown
                    self.log(f'High drawdown: {dd:.2%}')
```

## Disabling Observers

```python
# Disable default observers
cerebro.run(stdstats=False)

# Add specific observers
cerebro.addobserver(bt.observers.DrawDown)
cerebro.addobserver(bt.observers.Trades)
```

## Plotting with Observers

Observers automatically appear on plots:

```python
import matplotlib.pyplot as plt

cerebro.plot()
plt.show()

# Observers appear as subplots:
# - Drawdown
# - Trades
# - Buy/Sell markers
```

## Next Steps

- [Plotting](plotting.md) - Visualize results
- [Analyzers](analyzers.md) - Calculate performance metrics
