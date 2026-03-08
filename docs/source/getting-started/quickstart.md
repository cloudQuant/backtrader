---
title: Quick Start Tutorial
description: Create your first backtesting strategy in 5 minutes

---
# Quick Start Tutorial

Learn how to create a simple trading strategy and backtest it with historical data.

## Your First Strategy

```python
import backtrader as bt

class SimpleStrategy(bt.Strategy):
    """
    A simple moving average crossover strategy.
    Buy when short MA crosses above long MA.
    Sell when short MA crosses below long MA.
    """

    params = (
        ('short_period', 10),
        ('long_period', 30),
    )

    def __init__(self):

# Calculate moving averages
        self.short_ma = bt.indicators.SMA(self.data.close, period=self.p.short_period)
        self.long_ma = bt.indicators.SMA(self.data.close, period=self.p.long_period)

# Crossover indicator
        self.crossover = bt.indicators.CrossOver(self.short_ma, self.long_ma)

    def next(self):

# If not in position
        if not self.position:

# Buy when short MA crosses above long MA
            if self.crossover > 0:
                self.buy()
        else:

# Sell when short MA crosses below long MA
            if self.crossover < 0:
                self.sell()

```

## Running the Backtest

```python

# Create a cerebro instance

cerebro = bt.Cerebro()

# Add the strategy

cerebro.addstrategy(SimpleStrategy)

# Load data (example with Yahoo Finance)

data = bt.feeds.YahooFinanceData(
    dataname='AAPL',
    fromdate=datetime.datetime(2023, 1, 1),
    todate=datetime.datetime(2023, 12, 31)
)
cerebro.adddata(data)

# Set initial cash

cerebro.broker.setcash(10000.0)

# Run the backtest

results = cerebro.run()

# Print final portfolio value

print(f'Final Portfolio Value: {cerebro.broker.getvalue():.2f}')

```

## Plotting the Results

```python
import matplotlib.pyplot as plt

# Plot the results

cerebro.plot()
plt.show()

```

## Complete Example

```python
import backtrader as bt
import datetime

class SimpleStrategy(bt.Strategy):
    params = (
        ('short_period', 10),
        ('long_period', 30),
    )

    def __init__(self):
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

# Create and run

cerebro = bt.Cerebro()
cerebro.addstrategy(SimpleStrategy)

# Add data (using CSV file as example)

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

# Set broker

cerebro.broker.setcash(10000.0)
cerebro.broker.setcommission(commission=0.001)  # 0.1% commission

# Run

print(f'Starting Portfolio Value: {cerebro.broker.getvalue():.2f}')
results = cerebro.run()
print(f'Final Portfolio Value: {cerebro.broker.getvalue():.2f}')

# Plot

cerebro.plot()

```

## What's Next?

- [Basic Concepts](concepts.md) - Understand Cerebro, Data Feeds, Strategies
- [Indicators](indicators.md) - Explore 60+ built-in indicators
- [Data Feeds](data-feeds.md) - Load data from various sources
- [Analyzers](analyzers.md) - Analyze strategy performance
