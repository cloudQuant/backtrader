---
title: Cerebro API Reference
description: Core backtesting engine
---

# Cerebro API Reference

Cerebro is the central engine that orchestrates the backtesting process.

## Basic Usage

```python
import backtrader as bt

# Create cerebro instance
cerebro = bt.Cerebro()

# Add components
cerebro.adddata(data)
cerebro.addstrategy(MyStrategy)
cerebro.addanalyzer(bt.analyzers.SharpeRatio)

# Configure
cerebro.broker.setcash(10000)

# Run
strats = cerebro.run()
```

## Methods

### adddata

Add a data feed to the system.

```python
cerebro.adddata(data, name=None)
```

**Parameters:**
- `data`: Data feed instance
- `name`: Optional name for accessing in strategy

### addstrategy

Add a strategy to the system.

```python
cerebro.addstrategy(strategy_cls, *args, **kwargs)
```

**Parameters:**
- `strategy_cls`: Strategy class (subclass of `bt.Strategy`)
- `*args`, `**kwargs`: Strategy parameters

```python
cerebro.addstrategy(MyStrategy, period=20, threshold=0.5)
# Or using params
cerebro.addstrategy(MyStrategy, period=20)
```

### addobserver

Add an observer to monitor behavior.

```python
cerebro.addobserver(observer_cls, *args, **kwargs)
```

```python
cerebro.addobserver(bt.observers.DrawDown)
```

### addanalyzer

Add an analyzer for performance metrics.

```python
cerebro.addanalyzer(analyzer_cls, *args, **kwargs)
```

```python
cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
```

### setbroker

Set or replace the broker.

```python
cerebro.setbroker(broker_cls=None, *args, **kwargs)
```

```python
# Default broker with cash
cerebro.broker.setcash(10000)

# Custom broker
cerebro.setbroker(bt.brokers.CCBroker, cash=10000)
```

### run

Execute the backtest.

```python
strats = cerebro.run(stdstats=True)
```

**Parameters:**
- `stdstats`: Enable default observers (default: True)

**Returns:**
- List of strategy instances

### plot

Plot the results.

```python
fig = cerebro.plot(style='plotly', scheme='plotly')
```

## Attributes

### broker

Access the broker instance.

```python
cerebro.broker.setcash(10000)
cash = cerebro.broker.getcash()
```

### stores

Access registered stores.

### datas

Access data feeds.

```python
for data in cerebro.datas:
    print(data._name)
```

### strats

Access strategy instances after running.

```python
strats = cerebro.run()
strat = strats[0]
```

## Configuration

### Initial Cash

```python
cerebro.broker.setcash(10000)
```

### Commission

```python
cerebro.broker.setcommission(commission=0.001)
cerebro.broker.setcommission(commission=0.001, name='AAPL')
```

### Slippage

```python
cerebro.broker.set_slippage_perc(0.5)  # 0.5% slippage
```

### Position Size

```python
cerebro.addsizer(bt.sizers.FixedSize(stake=0.1))  # 10% per trade
```

## Complete Example

```python
import backtrader as bt
import datetime

class TestStrategy(bt.Strategy):
    pass

# Create cerebro
cerebro = bt.Cerebro()

# Add data
data = bt.feeds.YahooFinanceData(
    dataname='AAPL',
    fromdate=datetime.datetime(2023, 1, 1),
    todate=datetime.datetime(2023, 12, 31)
)
cerebro.adddata(data)

# Add strategy
cerebro.addstrategy(TestStrategy)

# Add analyzers
cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')

# Configure
cerebro.broker.setcash(10000)
cerebro.broker.setcommission(0.001)

# Run
strats = cerebro.run()

# Results
strat = strats[0]
sharpe = strat.analyzers.sharpe.get_analysis()
print(f'Sharpe Ratio: {sharpe["sharperatio"]:.3f}')

# Plot
cerebro.plot()
```

## See Also

- [Strategy](strategy.md)
- [Data Feeds](feeds.md)
- [Brokers](brokers.md)
