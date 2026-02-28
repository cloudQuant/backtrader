---
title: Indicator API
description: Complete Indicator class API reference for custom technical indicators
---

# Indicator API

The `Indicator` class is the base class for all technical indicators in Backtrader. It provides the foundation for creating custom indicators by managing line data, minimum periods, calculation logic, and automatic integration with the strategy execution flow.

## Class Definition

```python
class backtrader.Indicator(IndicatorBase):
    """Base class for all technical indicators."""
```

## Core Attributes

### `lines`

Tuple defining the output lines of the indicator.

```python
class MyIndicator(bt.Indicator):
    lines = ('value1', 'value2',)
```

### `params`

Tuple of parameter definitions for the indicator.

```python
class MyIndicator(bt.Indicator):
    params = (
        ('period', 20),
        ('multiplier', 2.0),
    )
```

Access via `self.p.parameter_name` or `self.params.parameter_name`.

### `alias`

Alternate names for the indicator (optional).

```python
class MyIndicator(bt.Indicator):
    alias = ('MyInd', 'CustomIndicator',)
```

### `_mindatas`

Minimum number of data feeds required (default: 1).

```python
class MyIndicator(bt.Indicator):
    _mindatas = 2  # Requires 2 data feeds
```

### `plotinfo` / `plotlines`

Plotting configuration for the indicator.

```python
class MyIndicator(bt.Indicator):
    plotinfo = dict(subplot=False)  # Plot on main chart
    plotlines = dict(
        value1=dict(color='blue'),
        value2=dict(ls='--'),
    )
```

## Core Methods

### `__init__(self)`

Called when the indicator is created. Use to set up sub-indicators, define line calculations, and set the minimum period.

```python
def __init__(self):
    super().__init__()  # Always call super first
    # Set minimum period
    self.addminperiod(self.p.period)
    # Create sub-indicators
    self.sma = bt.indicators.SMA(self.data.close, period=self.p.period)
```

**Important**: Always call `super().__init__()` first to ensure proper initialization.

### `prenext(self)`

Called for each bar before the minimum period is reached. Use for warmup calculations.

```python
def prenext(self):
    # Track values during warmup period
    self._sum += self.data[0]
```

### `nextstart(self)`

Called once when the minimum period is first reached. Use for initialization after warmup.

```python
def nextstart(self):
    # Initialize with first valid value
    self.lines.value[0] = self._sum / self.p.period
```

### `next(self)`

Called for each bar after the minimum period is reached. Contains main calculation logic.

```python
def next(self):
    # Calculate indicator value for current bar
    self.lines.value[0] = self.calculate()
```

### `once(self, start, end)`

Batch calculation mode for improved performance. Processes all bars in a single call.

```python
def once(self, start, end):
    # Vectorized calculation for all bars
    src = self.data.array
    dst = self.lines[0].array

    for i in range(start, end):
        dst[i] = self._calculate_at(i)
```

If you only override `next()` without `once()`, Backtrader automatically generates `once()` using `next()`.

## Minimum Period Management

### `addminperiod(self, period)`

Add to the minimum period required by the indicator.

```python
def __init__(self):
    super().__init__()
    # Requires 'period' bars before producing valid output
    self.addminperiod(self.p.period)
```

The actual minimum period is calculated as:
1. Maximum of all data source minimum periods
2. Maximum of all sub-indicator minimum periods
3. Value set by `addminperiod()` calls

## Line System Usage

### Accessing Lines

Access output lines using dot notation or index:

```python
# By name
value = self.indicator.line_name[0]

# By index
value = self.indicator.lines[0][0]

# Direct access (for single-line indicators)
value = self.indicator[0]
```

### Historical Access

Access historical values:

```python
# Current value
current = self.lines.value[0]

# Previous value
previous = self.lines.value[-1]

# N periods ago
past = self.lines.value[-n]
```

### Setting Line Values

Set output line values in calculation methods:

```python
def next(self):
    self.lines.value[0] = calculated_value
```

## Indicator Development Patterns

### Pattern 1: Simple Calculation

For simple calculations that don't require state:

```python
class SimpleMA(bt.Indicator):
    lines = ('sma',)
    params = (('period', 20),)

    def __init__(self):
        super().__init__()
        self.addminperiod(self.p.period)

    def next(self):
        # Calculate average of last 'period' values
        sma = sum(self.data[-i] for i in range(self.p.period)) / self.p.period
        self.lines.sma[0] = sma
```

### Pattern 2: Using Sub-Indicators

Compose indicators from other indicators:

```python
class CustomOscillator(bt.Indicator):
    lines = ('osc',)
    params = (('fast', 10), ('slow', 20))

    def __init__(self):
        super().__init__()
        self.fast_ma = bt.indicators.SMA(self.data, period=self.p.fast)
        self.slow_ma = bt.indicators.SMA(self.data, period=self.p.slow)

    def next(self):
        self.lines.osc[0] = self.fast_ma[0] - self.slow_ma[0]
```

### Pattern 3: Multi-Line Indicator

Create indicators with multiple output lines:

```python
class Bands(bt.Indicator):
    lines = ('mid', 'top', 'bot')
    params = (('period', 20), ('devfactor', 2.0))

    def __init__(self):
        super().__init__()
        self.addminperiod(self.p.period)

    def next(self):
        # Calculate middle band (SMA)
        mid = sum(self.data[-i] for i in range(self.p.period)) / self.p.period

        # Calculate standard deviation
        variance = sum((self.data[-i] - mid) ** 2 for i in range(self.p.period)) / self.p.period
        stddev = variance ** 0.5

        # Set all lines
        self.lines.mid[0] = mid
        self.lines.top[0] = mid + self.p.devfactor * stddev
        self.lines.bot[0] = mid - self.p.devfactor * stddev
```

### Pattern 4: Indicator with State

For indicators that need to maintain state between bars:

```python
class EMA(bt.Indicator):
    lines = ('ema',)
    params = (('period', 20),)

    def __init__(self):
        super().__init__()
        self.addminperiod(self.p.period)
        self.alpha = 2.0 / (self.p.period + 1)
        self.alpha1 = 1.0 - self.alpha

    def nextstart(self):
        # Seed with SMA
        self.lines.ema[0] = sum(self.data[-i] for i in range(self.p.period)) / self.p.period

    def next(self):
        # EMA formula: EMA(today) = EMA(yesterday) * alpha1 + price(today) * alpha
        self.lines.ema[0] = self.lines.ema[-1] * self.alpha1 + self.data[0] * self.alpha
```

### Pattern 5: Multiple Data Inputs

Create indicators that use multiple data sources:

```python
class Spread(bt.Indicator):
    lines = ('spread',)
    _mindatas = 2  # Requires 2 data feeds

    def __init__(self):
        super().__init__()

    def next(self):
        self.lines.spread[0] = self.data0[0] - self.data1[0]
```

## Calculation Modes

Backtrader supports two calculation modes:

### next() Mode (Default)

Calculates one bar at a time. Simpler to implement, easier to debug.

```python
def next(self):
    # Calculate for current bar only
    self.lines.value[0] = calculation()
```

### once() Mode (Performance)

Calculates all bars at once using array operations. Faster for large datasets.

```python
def once(self, start, end):
    src = self.data.array
    dst = self.lines[0].array

    for i in range(start, end):
        dst[i] = calculation(src, i)
```

If you only implement `next()`, Backtrader automatically generates `once()` by calling `next()` for each bar. For best performance, implement `once()` directly.

## Indicator Registration

Indicators are automatically registered when created as class attributes:

```python
class MyStrategy(bt.Strategy):
    def __init__(self):
        # These indicators are automatically registered and calculated
        self.sma20 = bt.indicators.SMA(self.data.close, period=20)
        self.sma50 = bt.indicators.SMA(self.data.close, period=50)
        self.crossover = bt.indicators.CrossOver(self.sma20, self.sma50)

    def next(self):
        if self.crossover[0] > 0:
            self.buy()
```

## Built-in Indicator Reference

### Moving Averages

| Indicator | Description | Parameters |
|-----------|-------------|------------|
| `SMA` | Simple Moving Average | `period` |
| `EMA` | Exponential Moving Average | `period` |
| `SMMA` | Smoothed Moving Average | `period` |
| `WMA` | Weighted Moving Average | `period` |
| `DEMA` | Double Exponential Moving Average | `period` |
| `TEMA` | Triple Exponential Moving Average | `period` |
| `HMA` | Hull Moving Average | `period` |
| `KAMA` | Kaufman Adaptive Moving Average | `period`, `fast`, `slow` |

### Momentum Indicators

| Indicator | Description | Parameters |
|-----------|-------------|------------|
| `RSI` | Relative Strength Index | `period`, `lookback` |
| `Stochastic` | Stochastic Oscillator | `period`, `period_dfast` |
| `MACD` | Moving Average Convergence Divergence | `period_me1`, `period_me2`, `period_signal` |
| `ROC` | Rate of Change | `period` |
| `Momentum` | Momentum | `period` |

### Volatility Indicators

| Indicator | Description | Parameters |
|-----------|-------------|------------|
| `ATR` | Average True Range | `period` |
| `BollingerBands` | Bollinger Bands | `period`, `devfactor` |
| `StandardDeviation` | Standard Deviation | `period` |

### Trend Indicators

| Indicator | Description | Parameters |
|-----------|-------------|------------|
| `ADX` | Average Directional Index | `period` |
| `Aroon` | Aroon Indicator | `period` |
| `ParabolicSAR` | Parabolic Stop and Reverse | `af`, `afmax` |
| `Ichimoku` | Ichimoku Cloud | Various |

### Crossover Indicators

| Indicator | Description | Parameters |
|-----------|-------------|------------|
| `CrossOver` | Detects both crossovers (returns 1 or -1) | None |
| `CrossUp` | Detects upward crossover only | None |
| `CrossDown` | Detects downward crossover only | None |

### Volume Indicators

| Indicator | Description | Parameters |
|-----------|-------------|------------|
| `OBV` | On-Balance Volume | None |
| `MFI` | Money Flow Index | `period` |

## Complete Example: Custom Indicator

```python
import backtrader as bt

class RelativeVolatility(bt.Indicator):
    """
    Custom indicator: Relative Volatility Index
    Measures volatility relative to its own historical average
    """

    lines = ('rvi',)
    params = (
        ('period', 20),
        ('stddev_period', 20),
    )

    plotinfo = dict(subplot=True)

    def __init__(self):
        super().__init__()
        self.addminperiod(max(self.p.period, self.p.stddev_period))

        # Calculate rolling standard deviation
        self.stddev = bt.indicators.StandardDeviation(
            self.data,
            period=self.p.stddev_period
        )

        # Calculate rolling mean of standard deviation
        self.stddev_sma = bt.indicators.SMA(
            self.stddev,
            period=self.p.period
        )

    def next(self):
        current_stddev = self.stddev[0]
        avg_stddev = self.stddev_sma[0]

        if avg_stddev != 0:
            self.lines.rvi[0] = current_stddev / avg_stddev
        else:
            self.lines.rvi[0] = 1.0


class MyStrategy(bt.Strategy):
    def __init__(self):
        # Custom indicator
        self.rvi = RelativeVolatility(self.data.close)

        # Built-in indicator
        self.sma = bt.indicators.SMA(self.data.close, period=20)

    def next(self):
        # Use custom indicator
        if self.rvi[0] > 1.5 and self.data.close[0] > self.sma[0]:
            self.buy()
```

## Plotting Configuration

### `plotinfo` Options

| Option | Type | Description |
|--------|------|-------------|
| `subplot` | bool | Plot in separate subplot (default: True) |
| `plotabove` | bool | Plot above price chart |
| `plotymargin` | float | Y-axis margin |
| `plothlines` | list | Horizontal lines to plot |
| `plotyticks` | list | Y-axis tick values |
| `_name` | str | Display name |

### `plotlines` Options

| Option | Type | Description |
|--------|------|-------------|
| `color` | str | Line color |
| `ls` / `linestyle` | str | Line style ('-', '--', ':', '.') |
| `lw` / `linewidth` | float | Line width |
| `_method` | str | Plotting method ('line', 'bar') |
| `_samecolor` | bool | Use same color as previous line |
| `_name` | str | Line display name |

## Indicator Caching

Indicators support caching to avoid duplicate calculations:

```python
# Enable indicator caching
bt.Indicator.usecache(True)

# Clear cache
bt.Indicator.cleancache()
```

## Common Pitfalls

1. **Forget to call `super().__init__()`**: Always call parent `__init__` first.

2. **Incorrect minperiod**: Use `addminperiod()` to specify warmup requirements.

3. **Array access in next()**: Use relative indexing (`data[0]`, `data[-1]`) in `next()`, not absolute indices.

4. **State initialization**: Use `nextstart()` for one-time initialization after warmup.

5. **Line naming**: Define lines as tuples with trailing comma for single line: `lines = ('value',)`

6. **Multiple data sources**: Set `_mindatas` when requiring multiple data feeds.

## Next Steps

- [Strategy API](strategy.md) - Using indicators in strategies
- [Data Feeds API](data-feeds.md) - Data source configuration
- [Observer API](observer.md) - Chart observers and visualization
