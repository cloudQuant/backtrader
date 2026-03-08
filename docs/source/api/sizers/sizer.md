---
title: Sizer API
description: Complete Sizer class API reference for position sizing

---
# Sizer API

Position Sizers determine the size of orders placed during trading. They calculate position sizes based on available cash, risk parameters, and other factors. Backtrader provides several built-in sizers and allows custom sizer development.

## Class Definition

```python
class backtrader.Sizer:
    """Base class for position sizers."""

```

## Parameters

### `params`

Tuple of parameter definitions for the sizer (legacy format).

```python
class MySizer(bt.Sizer):
    params = (
        ('stake', 1),
        ('percents', 10),
    )

```

### Modern Parameter Descriptors

New sizers use `ParameterDescriptor` for type-safe parameter definitions:

```python
from backtrader.parameters import Int, ParameterDescriptor

class MySizer(bt.Sizer):
    stake = ParameterDescriptor(
        default=1,
        type_=int,
        validator=Int(min_val=1),
        doc="Fixed stake size for operations"
    )

```

## Core Methods

### `__init__(self, **kwargs)`

Initialize the Sizer with parameters.

```python
def __init__(self, **kwargs):
    super().__init__(**kwargs)

```

### `getsizing(self, data, isbuy)`

Get the position size for an order. This method retrieves commission info and available cash before calling `_getsizing`.

```python
def getsizing(self, data, isbuy):
    """Get the position size for an order.

    Args:
        data: The target data for the order.
        isbuy: True for buy operations, False for sell operations.

    Returns:
        int: The position size to use for the order.
    """

```

### `_getsizing(self, comminfo, cash, data, isbuy)`

Override this method to implement custom sizing logic. This is the main method that determines position size.

```python
def _getsizing(self, comminfo, cash, data, isbuy):
    """Calculate position size for an order.

    Args:
        comminfo: CommissionInfo instance with commission and margin info
        cash: Current available cash in the broker
        data: Target data feed for the operation
        isbuy: True for buy operations, False for sell operations

    Returns:
        int: The position size to execute. Returns 0 for no action.
    """
    raise NotImplementedError

```

### `set(self, strategy, broker)`

Set the strategy and broker references for this sizer.

```python
def set(self, strategy, broker):
    """Set the strategy and broker references.

    Args:
        strategy: The strategy instance using this sizer.
        broker: The broker instance for portfolio information.
    """

```

## Built-in Sizers

### FixedSize

Returns a fixed stake size for any operation. Supports tranches for scaling into positions.

```python
import backtrader as bt

cerebro.addsizer(bt.sizers.FixedSize, stake=100)

```

| Parameter | Type | Default | Description |

|-----------|------|---------|-------------|

| `stake` | int | 1 | Fixed stake size for operations |

| `tranches` | int | 1 | Number of tranches to divide stake into |

```python

# Fixed size of 100 shares

sizer = bt.sizers.FixedSize(stake=100)

# Scale in using 3 tranches

sizer = bt.sizers.FixedSize(stake=300, tranches=3)

# Each order will be 100 shares (300/3)

```

### FixedReverser

Returns the fixed size needed to reverse an open position or open a new one.

```python
cerebro.addsizer(bt.sizers.FixedReverser, stake=50)

```

| Parameter | Type | Default | Description |

|-----------|------|---------|-------------|

| `stake` | int | 1 | Fixed stake size for operations |

Behavior:

- To open a position: returns `stake`
- To reverse a position: returns `2 * stake`

```python

# If current position is 0: returns 50

# If current position is 50 (long): returns 100 (to close 50 and short 50)

sizer = bt.sizers.FixedReverser(stake=50)

```

### FixedSizeTarget

Returns a fixed target position size, useful with Target Orders.

```python
cerebro.addsizer(bt.sizers.FixedSizeTarget, stake=100)

```

| Parameter | Type | Default | Description |

|-----------|------|---------|-------------|

| `stake` | int | 1 | Fixed target stake size |

| `tranches` | int | 1 | Number of tranches for scaling |

### PercentSizer

Uses a percentage of available cash for position sizing.

```python
cerebro.addsizer(bt.sizers.PercentSizer, percents=20)

```

| Parameter | Type | Default | Description |

|-----------|------|---------|-------------|

| `percents` | float | 20 | Percentage of available cash to use (0-100) |

| `retint` | bool | False | Return int size or float value |

```python

# Use 30% of available cash

sizer = bt.sizers.PercentSizer(percents=30)

# Use 10% of cash, return integer

sizer = bt.sizers.PercentSizer(percents=10, retint=True)

```

### AllInSizer

Uses 100% of available cash for each order.

```python
cerebro.addsizer(bt.sizers.AllInSizer)

```
This is a `PercentSizer` with `percents=100`.

### PercentSizerInt

Percentage-based sizer that returns integer values.

```python
cerebro.addsizer(bt.sizers.PercentSizerInt, percents=15)

```
This is a `PercentSizer` with `retint=True` by default.

### AllInSizerInt

Uses 100% of available cash and returns integer values.

```python
cerebro.addsizer(bt.sizers.AllInSizerInt)

```
Combines `percents=100` with `retint=True`.

## Integration with Cerebro

### Adding a Default Sizer

Use `addsizer()` to set the default sizer for all strategies:

```python
cerebro = bt.Cerebro()
cerebro.addsizer(bt.sizers.FixedSize, stake=100)

```

### Adding a Strategy-Specific Sizer

Use `addsizer_byidx()` to assign a sizer to a specific strategy:

```python

# Add strategies and get their indices

idx1 = cerebro.addstrategy(MyStrategy1)
idx2 = cerebro.addstrategy(MyStrategy2)

# Assign different sizers to each strategy

cerebro.addsizer_byidx(idx1, bt.sizers.PercentSizer, percents=10)
cerebro.addsizer_byidx(idx2, bt.sizers.FixedSize, stake=50)

```

## Integration with Strategy

### Setting Sizer in Strategy

```python
class MyStrategy(bt.Strategy):
    def __init__(self):
        super().__init__()

# Set a custom sizer
        self.setsizer(bt.sizers.PercentSizer(percents=20))

    def next(self):

# buy() and sell() will use the sizer automatically
        if self.data.close[0] > self.sma[0]:
            self.buy()  # Uses sizer to determine size

```

### Getting Sizer from Strategy

```python

# Get the current sizer

sizer = self.getsizer()

# Or via property

sizer = self.sizer

```

### Manual Sizing

```python
def next(self):

# Get size manually from sizer
    size = self.getsizing(self.data, isbuy=True)
    self.buy(size=size)

```

## Custom Sizer Development

### Basic Custom Sizer

```python
import backtrader as bt

class VolatilitySizer(bt.Sizer):
    """Size positions based on volatility."""
    params = (
        ('risk_pct', 0.02),  # 2% risk per trade
        ('atr_period', 14),
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def _getsizing(self, comminfo, cash, data, isbuy):

# Calculate position size based on ATR
        atr = bt.indicators.ATR(data, period=self.p.atr_period)
        risk_amount = cash *self.p.risk_pct

# Avoid division by zero
        if atr[0] == 0:
            return 0

# Size = Risk Amount / ATR
        size = risk_amount / atr[0]

        return int(size)

```

### Using Custom Sizer

```python
cerebro = bt.Cerebro()
cerebro.addsizer(VolatilitySizer, risk_pct=0.03, atr_period=20)

```

### Kelly Criterion Sizer

```python
class KellySizer(bt.Sizer):
    """Size positions using Kelly Criterion."""
    params = (
        ('win_rate', 0.55),
        ('avg_win', 100),
        ('avg_loss', 80),
        ('capital_pct', 0.25),  # Fraction of Kelly to use
    )

    def _getsizing(self, comminfo, cash, data, isbuy):

# Kelly % = (W - (1-W)) / R

# where W = win rate, R = win/loss ratio
        win_loss_ratio = self.p.avg_win / self.p.avg_loss
        kelly_pct = (self.p.win_rate - (1 - self.p.win_rate)) / win_loss_ratio

# Use fraction of Kelly for safety
        safe_pct = kelly_pct*self.p.capital_pct

# Calculate position size
        size = (cash* safe_pct) / data.close[0]

        return int(size)

```

### Risk Parity Sizer

```python
class RiskParitySizer(bt.Sizer):
    """Allocate capital based on risk parity."""
    params = (
        ('target_vol', 0.15),  # Target portfolio volatility
        ('lookback', 20),
    )

    def _getsizing(self, comminfo, cash, data, isbuy):

# Calculate recent volatility
        returns = [data.close[-i] / data.close[-i-1] - 1
                   for i in range(1, self.p.lookback)]
        volatility = (sum(r*r for r in returns) / len(returns)) ** 0.5

        if volatility == 0:
            return 0

# Scale position inversely to volatility
        scale = self.p.target_vol / volatility
        size = (cash * scale) / data.close[0]

        return int(size)

```

## Sizer Reference by Strategy

When a strategy calls `buy()` or `sell()` without specifying size:

1. The strategy uses its assigned sizer
2. The sizer's `getsizing()` method is called
3. `_getsizing()` computes the position size
4. The order is placed with the computed size

```python
class MyStrategy(bt.Strategy):
    def next(self):

# All these use the sizer automatically
        self.buy()           # Sizer determines size
        self.sell()          # Sizer determines size
        self.close()         # Sizer determines size

# Override with explicit size
        self.buy(size=100)   # Ignores sizer

```

## CommissionInfo Object

The `comminfo` parameter passed to `_getsizing()` provides:

```python
def _getsizing(self, comminfo, cash, data, isbuy):

# Get margin information
    margin = comminfo.getmargin(data)

# Get commission for a hypothetical order
    commission = comminfo.getcommission(size, price)

# Check if leveraged
    leverage = comminfo.getleveragemargin()

    return size

```

## Full Example

```python
import backtrader as bt
import datetime

class TestStrategy(bt.Strategy):
    params = (('period', 20),)

    def __init__(self):
        super().__init__()
        self.sma = bt.indicators.SMA(self.data.close, period=self.p.period)
        self.crossover = bt.indicators.CrossOver(self.data.close, self.sma)

    def next(self):
        if self.crossover > 0:
            self.buy()  # Size determined by sizer
        elif self.crossover < 0:
            self.sell()  # Size determined by sizer

# Create cerebro

cerebro = bt.Cerebro()

# Add data

data = bt.feeds.YahooFinanceData(
    dataname='AAPL',
    fromdate=datetime.datetime(2020, 1, 1),
    todate=datetime.datetime(2021, 12, 31)
)
cerebro.adddata(data)

# Add strategy

cerebro.addstrategy(TestStrategy)

# Add sizer - use 10% of available cash

cerebro.addsizer(bt.sizers.PercentSizer, percents=10)

# Set initial cash

cerebro.broker.setcash(10000)

# Run

results = cerebro.run()

```

## Available Aliases

| Sizer | Alias |

|-------|-------|

| `FixedSize` | `SizerFix` |

## Next Steps

- [Strategy API](strategy.md) - Strategy development
- [Broker API](broker.md) - Order execution
- [Indicator API](indicator.md) - Technical indicators
- [Analyzer API](analyzer.md) - Performance analysis
