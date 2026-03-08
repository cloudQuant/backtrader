---
title: LineSeries Time Series API
description: Complete Backtrader LineSeries API Reference

---
# LineSeries Time Series API

`LineSeries` is the core class for managing multi-line time-series data in Backtrader. It provides a unified time-series data access interface for data feeds, indicators, observers, and more, supporting historical data access, slicing operations, pandas conversion, and more.

## Class Hierarchy

```bash
LineRoot (base class for all line objects)
    LineSingle (single line object)
        LineBuffer (circular buffer implementation)
    LineMultiple (multiple line object)
        LineSeries (multi-line time series)
            Indicator (technical indicator base class)
            DataSeries (data feed base class)
            Strategy (strategy base class)

```

## Core Concepts

### Line (线条)

Line is the basic unit for storing time-series data in Backtrader. It uses a circular buffer implementation with the following characteristics:

- **Index 0 always points to the current value**: The latest data value is always at index 0
- **Positive indices access historical data**: `data[-1]` gets the previous value, `data[-2]` gets the value before that
- **Negative indices access future data**: `data[1]` can access the next value in replay or live scenarios
- **Automatic memory management**: Control memory usage through qbuffer mode

### Time Index Pattern

```bash
Historical Data         Current         Future Data
    |                 |               |

    v                 v               v
  ...  [-3]  [-2]  [-1]   [0]   [1]   [2]  ...
                  Previous Bar   Current Bar

```

## LineSeries Class

### Class Definition

```python
class backtrader.LineSeries(LineMultiple, LineSeriesMixin, ParamsMixin):
    """Base class for objects managing multiple time-series lines."""

```

### Core Attributes

| Attribute | Type | Description |

|-----------|------|-------------|

| `lines` | Lines | Container object storing all LineBuffer instances |

| `plotinfo` | PlotInfoObj | Plotting configuration object |

| `plotlines` | PlotLinesObj | Line plotting configuration |

| `csv` | bool | Whether CSV export is supported |

### Line Operation Attributes

| Attribute | Return Value | Description |

|-----------|--------------|-------------|

| `array` | array | Underlying array of the first line |

| `line` | LineBuffer | First line (shortcut for single-line indicators) |

| `l` | Lines | Alias for lines |

## Time Series Operations

### Data Access

```python
class MyStrategy(bt.Strategy):
    def next(self):

# Current value (index 0)
        current_close = self.data.close[0]
        current_sma = self.sma[0]

# Historical values (negative indices)
        prev_close = self.data.close[-1]    # Previous bar
        prev_close_2 = self.data.close[-2]  # Two bars ago
        prev_close_5 = self.data.close[-5]  # Five bars ago

# Future values (positive indices, valid only in replay/live scenarios)

# next_close = self.data.close[1]

```

### Data Length

```python
def next(self):

# Get data length (number of loaded bars)
    current_bar = len(self.data)
    total_bars = len(self)

# Check if there's enough historical data
    if len(self.data) >= 20:

# Can calculate 20-period indicator
        pass

```

### Time Operations

```python
def next(self):

# Get current bar time (multiple methods)
    dt_num = self.data.datetime[0]              # Internal numeric format
    dt = self.data.datetime.datetime(0)         # datetime object
    dt_date = self.data.datetime.date(0)        # date object
    dt_time = self.data.datetime.time(0)        # time object

# Previous bar time
    prev_dt = self.data.datetime.datetime(-1)

```

## Data Access Pattern Table

| Expression | Meaning | Use Case |

|------------|---------|----------|

| `data[0]` | Current bar value | Get latest data |

| `data[-1]` | Previous bar value | Get last historical value |

| `data[-n]` | n bars ago value | Get value n periods ago |

| `data[1]` | Next bar value | Future values in replay/live scenarios |

| `len(data)` | Data length | Get number of loaded bars |

| `data.array` | Underlying array | Direct access to complete data |

## Slicing and Indexing

### get() Method

Get a slice of data at a specified position and size:

```python
def next(self):

# Get the last 3 bars' close prices

# Returns: [close[-2], close[-1], close[0]]
    recent_3 = self.data.close.get(ago=0, size=3)

# Get the last 5 bars from current position
    last_5 = self.data.close.get(ago=-4, size=5)

# Usage
    avg_price = sum(recent_3) / len(recent_3)

```

### Slicing Operations

```python
def next(self):

# Get array slice (based on internal array index)

# Note: This directly operates on the underlying array
    array_data = self.data.close.array

# Common pattern: Get the most recent N values
    recent_values = array_data[-self.p.period:]

```

## Alignment and Synchronization

### Multiple Data Source Synchronization

When using multiple data sources, Backtrader automatically aligns them:

```python
cerebro = bt.Cerebro()

# Add multiple data sources

cerebro.adddata(daily_data, name='daily')
cerebro.adddata(weekly_data, name='weekly')

class MyStrategy(bt.Strategy):
    def next(self):

# Data sources are automatically aligned by date

# When weekly data has a new bar, next() is called for both
        daily_len = len(self.data0)  # Daily data length
        weekly_len = len(self.data1)  # Weekly data length

# Access different data sources
        if self.data0.close[0] > self.data1.close[0]:
            self.buy(data=self.data0)

```

### Data Source Access Methods

```python
class MyStrategy(bt.Strategy):
    def __init__(self):

# Method 1: Access by index
        self.data0 = self.datas[0]
        self.data1 = self.datas[1]

# Method 2: Access by name (requires name to be set)
        self.daily = self.getdatabyname('daily')
        self.weekly = self.getdatabyname('weekly')

```

## Period and Timeframe Handling

### TimeFrame Constants

```python

# TimeFrame definitions

TimeFrame.Ticks        # 1 - Tick data

TimeFrame.MicroSeconds # 2 - Microseconds

TimeFrame.Seconds      # 3 - Seconds

TimeFrame.Minutes      # 4 - Minutes

TimeFrame.Days         # 5 - Days

TimeFrame.Weeks        # 6 - Weeks

TimeFrame.Months       # 7 - Months

TimeFrame.Years        # 8 - Years

TimeFrame.NoTimeFrame  # 9 - No timeframe

```

### Getting Data Source Timeframe

```python
class MyStrategy(bt.Strategy):
    def next(self):

# Get timeframe type
        tf = self.data._timeframe
        comp = self.data._compression

# Determine data type
        if tf == bt.TimeFrame.Days:
            if comp == 1:
                print("Daily data")
            elif comp == 7:
                print("Weekly data (7-day compression)")

```

### TimeFrame Methods

```python

# Get timeframe name

name = bt.TimeFrame.getname(bt.TimeFrame.Days)

# Returns: 'Day'

name = bt.TimeFrame.getname(bt.TimeFrame.Minutes, 5)

# Returns: 'Minutes'

# Get name from constant

name = bt.TimeFrame.TName(bt.TimeFrame.Days)

# Returns: 'Days'

# Get constant from name

tf = bt.TimeFrame.TFrame('Days')

# Returns: TimeFrame.Days (5)

```

## Relationship with Pandas

### Convert to pandas Series

```python
import backtrader as bt
import pandas as pd

class MyStrategy(bt.Strategy):
    def stop(self):

# Get complete data array
        close_array = self.data.close.array

# Create pandas Series

# Note: Need to manually build date index
        dates = []
        for i in range(len(self.data)):
            dt = self.data.datetime.date(i)
            dates.append(dt)

        df = pd.DataFrame({
            'close': close_array[:len(dates)],
        }, index=dates)
        df.index.name = 'date'

```

### Create Data Feed from pandas

```python
import pandas as pd
import backtrader as bt

# Create DataFrame

df = pd.DataFrame({
    'datetime': pd.date_range('2020-01-01', periods=100),
    'open': np.random.randn(100).cumsum() + 100,
    'high': np.random.randn(100).cumsum() + 102,
    'low': np.random.randn(100).cumsum() + 98,
    'close': np.random.randn(100).cumsum() + 100,
    'volume': np.random.randint(1000, 10000, 100),
})

# Set index

df.set_index('datetime', inplace=True)

# Create data feed

data = bt.feeds.PandasData(dataname=df)

```

### PandasData Parameter Mapping

```python
class CustomPandasData(bt.feeds.PandasData):

# Custom column name mapping
    lines = ('close', 'volume', 'custom_line')

# Parameter mapping
    params = (
        ('datetime', None),      # None = use index
        ('open', 'open_price'),
        ('high', 'high_price'),
        ('low', 'low_price'),
        ('close', 'close_price'),
        ('volume', 'vol'),
        ('openinterest', None),  # None = column doesn't exist
    )

```

## Common Usage Patterns

### Pattern 1: Access Historical Data to Calculate Indicators

```python
class CustomIndicator(bt.Indicator):
    lines = ('value',)
    params = (('period', 20),)

    def __init__(self):
        super().__init__()
        self.addminperiod(self.p.period)

    def next(self):

# Calculate average of the last N periods
        total = 0.0
        for i in range(self.p.period):
            total += self.data.close[-i]

        self.lines.value[0] = total / self.p.period

```

### Pattern 2: Compare Current and Previous Values

```python
def next(self):

# Check if close price has risen consecutively
    if (self.data.close[0] > self.data.close[-1] and
        self.data.close[-1] > self.data.close[-2] and
        self.data.close[-2] > self.data.close[-3]):

# 3 consecutive bars rising
        self.buy()

```

### Pattern 3: Conditional Access to Avoid Out of Bounds

```python
def next(self):

# Ensure there's enough historical data
    if len(self.data) < self.p.period:
        return

# Safe access to historical data
    prev_close = self.data.close[-self.p.period]

# Or use minperiod
    if len(self.data) > self.p.period:

# Sufficient data here
        pass

```

### Pattern 4: Get Complete Historical Data

```python
def next(self):

# Method 1: Use array attribute
    all_closes = self.data.close.array

# Method 2: Loop to get values
    closes = []
    for i in range(len(self.data)):
        closes.append(self.data.close[i - len(self.data) + 1])

# Method 3: Use getzero
    all_data = self.data.close.getzero(0, len(self.data))

```

### Pattern 5: Multi-Line Indicator Access

```python
class BollingerBands(bt.Indicator):
    lines = ('mid', 'top', 'bot')
    params = (('period', 20), ('devfactor', 2.0))

    def next(self):

# Access different output lines
        mid = self.lines.mid[0]
        top = self.lines.top[0]
        bot = self.lines.bot[0]

# Or access by name
        mid = self.mid[0]
        top = self.top[0]
        bot = self.bot[0]

```

## LineSeries Methods

### Length Operations

#### `len(self)`

Returns the length of the LineSeries (number of processed data points).

```python
current_length = len(self.indicator)

```

#### `size(self)`

Returns the number of lines (excluding extra lines).

```python
num_lines = self.indicator.size()

```

### Index Operations

#### `__getitem__(self, key)`

Gets a value from the primary line.

```python
value = self.indicator[0]      # Current value

value = self.indicator[-1]     # Previous value

```

#### `__call__(self, ago=None, line=-1)`

Returns a delayed line or value at specified index/name.

```python

# Return current line

current = self.indicator()

# Return line delayed by 3 periods

delayed = self.indicator(ago=3)

# Return current value of specified line

value = self.indicator(line='close')

```

### Buffer Operations

#### `qbuffer(self, savemem=0)`

Enable queued buffer mode to save memory.

```python

# Only keep recent data

self.data.qbuffer(savemem=1000)

# For indicators

self.sma.qbuffer()

```

#### `minbuffer(self, size)`

Set minimum buffer size.

```python

# Ensure at least 100 data points

self.indicator.minbuffer(100)

```

### Navigation Operations

#### `home(self)`

Reset all lines to the starting position.

```python
self.indicator.home()

```

#### `rewind(self, size=1)`

Rewind by the specified number of positions.

```python
self.indicator.rewind(5)  # Rewind 5 positions

```

#### `advance(self, size=1)`

Advance by the specified number of positions.

```python
self.indicator.advance(1)  # Advance 1 position

```

#### `forward(self, value=0.0, size=1)`

Advance all lines and fill with values.

```python
self.indicator.forward(size=1)

```

#### `backwards(self, size=1, force=False)`

Move all lines backward.

```python
self.indicator.backwards(size=1)

```

#### `reset(self)`

Reset all lines to initial state.

```python
self.indicator.reset()

```

#### `extend(self, value=0.0, size=0)`

Extend all lines.

```python
self.indicator.extend(size=10)

```

### Line Operations

#### `_getline(self, line, minusall=False)`

Get a line by name or index.

```python

# By index

line = self.indicator._getline(0)

# By name

line = self.indicator._getline('close')

# Use minusall parameter

line = self.indicator._getline(-1, minusall=True)  # Last line

```

## Performance Optimization

### Using array Attribute

For scenarios requiring access to all data, use the array attribute directly:

```python
def next(self):

# Fast access to all data
    data_array = self.data.close.array

# Use NumPy operations (if imported)
    import numpy as np
    mean = np.mean(data_array[-20:])

```

### Enable Cache Mode

For long-running backtests:

```python

# Set in Cerebro

cerebro = bt.Cerebro()

# Enable cache for data source

data = bt.feeds.PandasData(dataname=df)
cerebro.adddata(data)
data.qbuffer(savemem=1000)  # Only keep last 1000 bars

```

### Use runonce Mode

```python

# Batch processing mode, faster

cerebro.run(runonce=True)

```

## Complete Examples

### Example 1: Custom Multi-Line Indicator

```python
import backtrader as bt

class MultiOutputIndicator(bt.Indicator):
    """
    Custom indicator: Price channel
    Returns three lines: upper, middle, lower
    """
    lines = ('upper', 'middle', 'lower')
    params = (('period', 20),)

    plotinfo = dict(
        subplot=False,  # Plot on main chart
    )

    def __init__(self):
        super().__init__()
        self.addminperiod(self.p.period)

    def next(self):

# Calculate middle band (SMA)
        total = 0.0
        high_max = self.data.high[-self.p.period]
        low_min = self.data.low[-self.p.period]

        for i in range(self.p.period):
            price = (self.data.high[-i] + self.data.low[-i] + self.data.close[-i]) / 3
            total += price
            if self.data.high[-i] > high_max:
                high_max = self.data.high[-i]
            if self.data.low[-i] < low_min:
                low_min = self.data.low[-i]

        self.lines.middle[0] = total / self.p.period
        self.lines.upper[0] = high_max
        self.lines.lower[0] = low_min


class MyStrategy(bt.Strategy):
    def __init__(self):

# Create custom indicator
        self.channel = MultiOutputIndicator(self.data, period=20)

# Built-in indicator
        self.sma = bt.indicators.SMA(self.data.close, period=20)

    def next(self):

# Access multiple lines of custom indicator
        if self.data.close[0] > self.channel.upper[0]:

# Price breaks above upper band
            self.buy()
        elif self.data.close[0] < self.channel.lower[0]:

# Price breaks below lower band
            self.sell()

```

### Example 2: Historical Data Analysis

```python
class AnalysisStrategy(bt.Strategy):
    def __init__(self):
        self.sma20 = bt.indicators.SMA(self.data.close, period=20)
        self.sma50 = bt.indicators.SMA(self.data.close, period=50)

    def next(self):

# Get list of last N values
        recent_20 = self.data.close.get(ago=0, size=20)

# Calculate custom statistics
        avg = sum(recent_20) / len(recent_20)

# Check trend
        if self.sma20[0] > self.sma20[-1] > self.sma20[-2]:

# MA rising
            pass

# Time-based analysis
        current_dt = self.data.datetime.datetime(0)
        if current_dt.hour >= 9 and current_dt.hour < 15:

# Trading hours
            pass

```

### Example 3: Multi-Timeframe Analysis

```python
class MultiTimeFrameStrategy(bt.Strategy):
    def __init__(self):

# Get data from different timeframes
        self.daily = self.data0  # Daily
        self.weekly = self.data1  # Weekly

# Create indicators for each timeframe
        self.daily_sma = bt.indicators.SMA(self.daily.close, period=20)
        self.weekly_sma = bt.indicators.SMA(self.weekly.close, period=20)

    def next(self):

# Check multi-timeframe alignment
        if len(self.weekly) > len(self.weekly_sma):

# Weekly indicator valid
            if self.daily.close[0] > self.daily_sma[0]:
                if self.weekly.close[0] > self.weekly_sma[0]:

# Both timeframes trend aligned
                    self.buy(data=self.daily)

```

## Common Pitfalls

1. **Index out of bounds**: Check `len(data)` before accessing historical data
2. **Minimum period**: Use `addminperiod()` to ensure indicators have enough data
3. **Future data leakage**: Avoid using `data[1]` and other future data in backtests
4. **Data alignment**: Multiple data sources may not be perfectly aligned
5. **Time handling**: datetime is in internal numeric format, needs conversion

## Related Documentation

- [Data Feeds API](data-feeds.md) - Data source configuration
- [Indicator API](indicator.md) - Indicator development
- [Strategy API](strategy.md) - Strategy development
- [Cerebro API](cerebro.md) - Backtesting engine
