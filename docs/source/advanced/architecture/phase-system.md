- --

title: Phase System
description: Understanding Backtrader's execution phases

- --

# Phase System

Backtrader executes strategies through distinct phases to handle the minimum period requirements of indicators and data feeds.

## Execution Phases

```mermaid
stateDiagram-v2
    [*] --> Prenext: Start
    Prenext --> Prenext: minperiod not reached
    Prenext --> Nextstart: minperiod == bars
    Nextstart --> Next: Single bar transition
    Next --> Next: Normal execution
    Next --> [*]: End of data

```bash

## 1. Prenext Phase

The **prenext** phase runs before enough data bars have been accumulated for indicators to produce valid values.

```python
class MyStrategy(bt.Strategy):
    def __init__(self):
        self.sma = bt.indicators.SMA(period=20)

# minperiod = 20

    def prenext(self):

# Called when len(self.data) < self.sma.minperiod
        print(f"Bar {len(self)}: Accumulating data...")

```bash

- *Characteristics:**
- Runs from bar 0 until `minperiod - 1`
- Indicators may not have valid values
- Use for initialization and warm-up

## 2. Nextstart Phase

The **nextstart** phase runs exactly once when `minperiod` is first reached.

```python
def nextstart(self):

# Called once when len(self.data) == self.sma.minperiod
    print(f"Bar {len(self)}: First valid bar!")

# Default implementation calls next() automatically

```bash

- *Characteristics:**
- Runs exactly once at bar `minperiod`
- Transition point between prenext and next
- Override for special first-bar logic

## 3. Next Phase

The **next** phase is the main execution loop.

```python
def next(self):

# Called for each bar after minperiod is satisfied
    if self.sma[0] > self.data.close[0]:
        self.sell()

```bash

- *Characteristics:**
- Runs from bar `minperiod` to end of data
- All indicators have valid values
- Main strategy logic goes here

## Minimum Period System

Each component has a `minperiod` attribute that indicates how many bars it needs before producing valid output.

```python

# Indicator minimum periods

SMA(period=20).minperiod  # 20

EMA(period=12).minperiod  # 12 (adjusted internally)

RSI(period=14).minperiod  # 15 (14 + 1 for calculation)

# Strategy minperiod is the maximum of its indicators

class MyStrategy(bt.Strategy):
    def __init__(self):
        self.sma20 = bt.indicators.SMA(period=20)
        self.sma50 = bt.indicators.SMA(period=50)

# Strategy.minperiod = 50 (maximum)

```bash

## Practical Example

```python
import backtrader as bt

class PhaseExample(bt.Strategy):
    params = (('period', 20),)

    def __init__(self):
        self.sma = bt.indicators.SMA(period=self.params.period)
        self.prenext_count = 0

    def prenext(self):
        self.prenext_count += 1

# Logging not recommended during backtest

# Use observer instead

    def nextstart(self):

# This is the first bar with valid SMA value
        print(f"First valid bar: {len(self)}")

    def next(self):

# Normal execution
        if len(self) == self.params.period + 1:
            print(f"Second valid bar: SMA = {self.sma[0]:.2f}")

cerebro = bt.Cerebro()
data = bt.feeds.YahooFinanceData(dataname='AAPL',
                                  fromdate=datetime(2020, 1, 1),
                                  todate=datetime(2020, 12, 31))
cerebro.adddata(data)
cerebro.addstrategy(PhaseExample)
cerebro.run()

```bash

## Execution Order

```mermaid
sequenceDiagram
    participant Data
    participant Cerebro
    participant Strategy
    participant Indicators

    Data->>Cerebro: New bar
    Cerebro->>Indicators: Calculate (always)
    Indicators-->>Cerebro: Values updated

    alt minperiod not reached
        Cerebro->>Strategy: prenext()
    else minperiod just reached
        Cerebro->>Strategy: nextstart()
    else minperiod satisfied
        Cerebro->>Strategy: next()
    end

    Strategy->>Cerebro: Orders (optional)
    Cerebro->>Cerebro: Process orders

```bash

## Key Points

1. **Indicators update every bar**- Even during prenext

2.**Strategy phases control execution**- Different logic for each phase
3.**Minimum period is automatic**- Calculated from components
4.**Observers follow same pattern** - Also have prenext/nextstart/next

## Best Practices

```python

# DO: Use minperiod for warm-up

class GoodStrategy(bt.Strategy):
    def __init__(self):
        self.warmup = 50  # Extra warm-up bars

    def next(self):
        if len(self) < self.warmup:
            return  # Skip warm-up period

# Main logic here

# DON'T: Assume indicators are valid in prenext

class BadStrategy(bt.Strategy):
    def prenext(self):
        value = self.sma[0]  # May be NaN or invalid!

```bash
