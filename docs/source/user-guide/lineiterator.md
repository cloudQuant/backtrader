- --

title: LineIterator API
description: Complete LineIterator class API reference - the foundation for Indicators, Strategies, and Observers

- --

# LineIterator API

The `LineIterator` class is the foundational base class for all objects that iterate over time-series data in Backtrader. It provides the core infrastructure for `Indicator`, `Strategy`, and `Observer` classes, managing execution phases, data flow, minimum period calculations, and child object registration.

## Class Definition

```python
class backtrader.LineIterator(LineSeries):
    """Base class for all time-series iterating objects."""

```bash

## Line Type Constants

The `_ltype` attribute identifies the type of LineIterator object:

| Constant | Value | Type |

|----------|-------|------|

| `LineIterator.IndType` | 0 | Indicator |

| `LineIterator.StratType` | 1 | Strategy |

| `LineIterator.ObsType` | 2 | Observer |

```python

# Check type at runtime

if obj._ltype == LineIterator.IndType:
    print("This is an indicator")

```bash

## Core Attributes

### `_ltype`

Line type identifier (IndType=0, StratType=1, ObsType=2).

```python

# Defined in base classes

class IndicatorBase(LineIterator):
    _ltype = LineIterator.IndType  # = 0

class StrategyBase(LineIterator):
    _ltype = LineIterator.StratType  # = 1

class ObserverBase(LineIterator):
    _ltype = LineIterator.ObsType  # = 2

```bash

### `_lineiterators`

Dictionary mapping line types to lists of registered child objects.

```python

# Structure: {_ltype: [list of objects]}

self._lineiterators = {
    LineIterator.IndType: [],  # Registered indicators
    LineIterator.ObsType: [],  # Registered observers
    LineIterator.StratType: [],  # Registered strategies

}

```bash

### `_minperiod`

Minimum number of bars required before the object produces valid output.

```python

# Set minimum period

self._minperiod = 20

# Or use helper method

self.addminperiod(20)

# Get minimum period

period = self._minperiod

```bash

### `_nextforce`

Force cerebro to run in `next()` mode instead of `runonce()` mode.

```python
class MyIndicator(bt.Indicator):
    _nextforce = True  # Force next() mode for this indicator

```bash

### `_mindatas`

Minimum number of data feeds required (default: 1).

```python
class SpreadIndicator(bt.Indicator):
    _mindatas = 2  # Requires 2 data feeds

```bash

### `plotinfo` / `plotlines`

Plotting configuration objects.

```python
class MyIndicator(bt.Indicator):
    plotinfo = dict(
        subplot=True,
        plotname='My Indicator',
    )
    plotlines = dict(
        value=dict(color='blue', linewidth=2),
    )

```bash

## Execution Phases

LineIterator implements a three-phase execution model:

```mermaid
graph LR
    A[Data Feed] --> B[prenext Phase]
    B -->|minperiod not reached| B

    B -->|minperiod reached| C[nextstart Phase]

    C -->|called once| D[next Phase]

    D -->|for each bar| D

    D -->|no more data| E[stop]

```bash

### Phase Flow Diagram

```mermaid
sequenceDiagram
    participant C as Cerebro
    participant L as LineIterator
    participant I as Indicators

    C->>L: Call _next()
    L->>L: _clk_update() - Update clock
    L->>I: Call _next() for each indicator

    alt clock_len <= _minperiod
        L->>L: Call prenext()
    else clock_len == _minperiod
        L->>L: Call nextstart()
    else clock_len > _minperiod
        L->>L: Call next()
    end

    L->>L: Call _notify()

```bash

### `prenext(self)`

Called for each bar before the minimum period is reached. Use for warmup calculations and data collection.

```python
def prenext(self):
    """Called during warmup period."""

# Accumulate data for later calculation
    if not hasattr(self, '_warmup_data'):
        self._warmup_data = []
    self._warmup_data.append(self.data[0])

```bash

### `nextstart(self)`

Called once when the minimum period is first reached. Use for initialization after warmup.

```python
def nextstart(self):
    """Called once when minperiod is satisfied."""

# Initialize with first valid value
    self.lines.value[0] = sum(self._warmup_data) / len(self._warmup_data)

# Clean up warmup data
    delattr(self, '_warmup_data')

```bash
Default implementation calls `next()`.

### `next(self)`

Called for each bar after the minimum period is reached. Contains main calculation logic.

```python
def next(self):
    """Main calculation logic."""
    self.lines.value[0] = self.calculate()

```bash

### `stop(self)`

Called when backtesting stops.

```python
def stop(self):
    """Cleanup and final reporting."""
    print(f'Final value: {self.lines.value[0]}')

```bash

## Indicator Registration

### `getindicators(self)`

Get all indicators registered with this lineiterator.

```python
indicators = self.getindicators()
for ind in indicators:
    print(f'{ind.__class__.__name__}: {ind[0]}')

```bash

### `getobservers(self)`

Get all observers registered with this lineiterator.

```python
observers = self.getobservers()

```bash

### `_register_indicator(self, indicator)`

Register an indicator with this lineiterator (automatic in most cases).

```python

# Usually called automatically

self._lineiterators[LineIterator.IndType].append(indicator)

```bash

## Owner Management and donew() Pattern

The `donew()` pattern replaces the original metaclass-based initialization:

```python
@classmethod
def donew(cls, *args, **kwargs):
    """Process data arguments before instance creation.

    1. Extract data feeds from args
    2. Set up data aliases (data0, data1, etc.)
    3. Configure clock reference
    4. Calculate minimum period from data sources
    5. Return (instance, remaining_args, kwargs)

    """
    _obj = super().donew(*args, **kwargs)[0]

# Extract data feeds
    _obj.datas = [arg for arg in args if hasattr(arg, 'lines')]

# Set up data aliases
    for i, data in enumerate(_obj.datas):
        setattr(_obj, f'data{i}', data)

# Set clock
    _obj._clock = _obj.datas[0] if _obj.datas else None

    return _obj, args, kwargs

```bash

### `dopreinit(cls, _obj, *args, **kwargs)`

Handle pre-initialization setup before `__init__()`.

```python
@classmethod
def dopreinit(cls, _obj, *args, **kwargs):
    """Setup before __init__: datas, clock, minperiod."""

# Ensure datas is set up
    if not _obj.datas:
        _obj.datas = [_obj._owner] if _obj._owner else []

# Set clock from first data
    if _obj.datas:
        _obj._clock = _obj.datas[0]

# Calculate minperiod from datas
    if _obj.datas:
        data_minperiods = [getattr(d, '_minperiod', 1) for d in _obj.datas]
        _obj._minperiod = max(data_minperiods + [_obj._minperiod])

    return _obj, args, kwargs

```bash

### `dopostinit(cls, _obj, *args, **kwargs)`

Handle post-initialization setup after `__init__()`.

```python
@classmethod
def dopostinit(cls, _obj, *args, **kwargs):
    """Final setup after __init__: minperiod, registration."""

# Recalculate minperiod from lines
    line_minperiods = [getattr(x, '_minperiod', 1) for x in _obj.lines]
    if line_minperiods:
        _obj._minperiod = max(_obj._minperiod, max(line_minperiods))

# Register with owner
    if _obj._owner:
        _obj._owner.addindicator(_obj)

    return _obj, args, kwargs

```bash

## Data Flow in LineIterator

### Clock Management

The clock synchronizes data processing across multiple data feeds:

```python

# Internal clock update

def _clk_update(self):
    """Update clock and return current data length."""
    if self._clock:
        return len(self._clock)
    return 0

```bash

### Data Access Patterns

```python

# Access data by index

current = self.data[0]      # Current bar

previous = self.data[-1]    # Previous bar

ago_5 = self.data[-5]       # 5 bars ago

# Access by name (for multi-line data)

close = self.data.close[0]
high = self.data.high[0]
volume = self.data.volume[0]

# Access multiple data feeds

data0_close = self.data0.close[0]
data1_close = self.data1.close[0]

```bash

### Forward Method

Advance the internal position:

```python
def forward(self, value=1):
    """Advance the internal position by value steps."""
    self.lines.advance(value)

```bash

## Minimum Period and Warmup Handling

### Minimum Period Calculation

The minimum period is calculated as the maximum of:

1. All data source minimum periods
2. All sub-indicator minimum periods
3. Value set by `addminperiod()` calls

```python

# The effective minimum period

effective_minperiod = max(
    data._minperiod for data in self.datas
)
effective_minperiod = max(effective_minperiod, self._minperiod)

```bash

### `addminperiod(self, period)`

Add to the minimum period required.

```python
def __init__(self):
    super().__init__()
    self.addminperiod(20)  # Requires 20 bars warmup

```bash

### `updateminperiod(self, period)`

Update minimum period if the new value is greater.

```python

# Updates to max(current, new)

self.updateminperiod(30)  # Sets to max(current, 30)

```bash

### `setminperiod(self, period)`

Directly set the minimum period (use with caution).

```python

# Override calculated minperiod

self.setminperiod(10)

```bash

### `_periodrecalc(self)`

Recalculate minimum period based on child indicators.

```python
def _periodrecalc(self):
    """Recalculate minperiod from child indicators."""
    indicators = self._lineiterators[LineIterator.IndType]
    indperiods = [ind._minperiod for ind in indicators]
    self.updateminperiod(max(indperiods or [self._minperiod]))

```bash

## once() Mode Optimization

### next() vs once() Mode Comparison

| Aspect | next() Mode | once() Mode |

|--------|-------------|-------------|

| **Execution**| Bar-by-bar | Batch processing |

|**Complexity**| Simpler | More complex |

|**Performance**| Slower | Faster (2-10x) |

|**Debugging**| Easier | Harder |

|**Default** | Yes (with `_nextforce`) | No |

### `preonce(self, start, end)`

Called during minimum period phase in runonce mode.

```python
def preonce(self, start, end):
    """Batch processing during warmup in runonce mode."""
    for i in range(start, end):

# Accumulate warmup data
        pass

```bash

### `oncestart(self, start, end)`

Called once when minimum period is reached in runonce mode.

```python
def oncestart(self, start, end):
    """Transition from preonce to once."""
    self.once(start, end)

```bash

### `once(self, start, end)`

Batch calculation mode for all bars at once.

```python
def once(self, start, end):
    """Vectorized calculation for all bars."""
    src = self.data.array
    dst = self.lines[0].array

    for i in range(start, end):
        dst[i] = self._calculate_at(i)

```bash

### Performance Considerations

For best performance in `once()` mode:

```python
def once(self, start, end):
    """Optimized batch calculation."""

# Access arrays directly
    src = self.data.array
    dst = self.lines[0].array

# Use local variables for speed
    period = self.p.period

# Batch calculation
    for i in range(start, end):

# Calculate using array access
        dst[i] = sum(src[i-period:i]) / period

```bash

## Internal Methods

### `_next(self)`

Internal next method called for each bar.

```python
def _next(self):
    """Update indicators and call phase methods."""

# Update clock
    clock_len = self._clk_update()

# Update child indicators
    for indicator in self._lineiterators[LineIterator.IndType]:
        indicator._next()

# Call notification
    self._notify()

# Call phase method
    if clock_len > self._minperiod:
        self.next()
    elif clock_len == self._minperiod:
        self.nextstart()
    elif clock_len:
        self.prenext()

```bash

### `_notify(self)`

Process pending notifications.

```python
def _notify(self):
    """Process notifications (empty by default)."""
    pass

```bash

### `_stage1(self)`

Stage 1 initialization for line operators.

```python
def _stage1(self):
    """Reset line operators."""
    self._opstage = 1
    for data in self.datas:
        data._stage1()

```bash

### `_stage2(self)`

Stage 2 initialization for line operators.

```python
def _stage2(self):
    """Set up line operators."""
    self._opstage = 2
    for data in self.datas:
        data._stage2()

```bash

## Memory Management

### `qbuffer(self, savemem=0)`

Enable memory saving mode for lines.

```python

# Save memory for all lines

self.qbuffer(savemem=1)

# savemem values:

# 0  - No memory saving

# 1  - Save memory for all lines and indicators

# -1  - Don't save for indicators at strategy level

# -2  - Also don't save for indicators with plot=False

```bash

## Plotting Support

### `_plotinit(self)`

Initialize plotting configuration.

```python
def _plotinit(self):
    """Initialize plotinfo defaults."""

# Set up plotinfo if not present
    if not hasattr(self, 'plotinfo'):
        self.plotinfo = PlotInfoObj()
    return True

```bash

## Base Classes

### `IndicatorBase`

Base class for all indicators.

```python
class IndicatorBase(DataAccessor):
    """Base class for indicators."""
    _ltype = LineIterator.IndType  # = 0

```bash

### `ObserverBase`

Base class for all observers.

```python
class ObserverBase(DataAccessor):
    """Base class for observers."""
    _ltype = LineIterator.ObsType  # = 2
    _mindatas = 0  # Observers don't consume data arguments

```bash

### `StrategyBase`

Base class for all strategies.

```python
class StrategyBase(DataAccessor):
    """Base class for strategies."""
    _ltype = LineIterator.StratType  # = 1

    def once(self, start, end):
        """Strategies override once to do nothing."""
        pass

```bash

## Complete Example: Custom LineIterator

```python
import backtrader as bt

class CustomOscillator(bt.Indicator):
    """Custom oscillator demonstrating LineIterator usage."""

    lines = ('oscillator', 'signal')
    params = (
        ('fast_period', 12),
        ('slow_period', 26),
        ('signal_period', 9),
    )

    def __init__(self):
        super().__init__()

# Set minimum period
        self.addminperiod(self.p.slow_period + self.p.signal_period)

# Create sub-indicators
        self.fast_ma = bt.indicators.SMA(self.data, period=self.p.fast_period)
        self.slow_ma = bt.indicators.SMA(self.data, period=self.p.slow_period)

# Initialize signal line calculation
        self.signal_line = bt.indicators.SMA(self.lines.oscillator,
                                             period=self.p.signal_period)

    def next(self):
        """Calculate oscillator value for current bar."""

# Oscillator = fast_ma - slow_ma
        self.lines.oscillator[0] = self.fast_ma[0] - self.slow_ma[0]

    def prenext(self):
        """Track values during warmup."""
        if not hasattr(self, '_warmup_count'):
            self._warmup_count = 0
        self._warmup_count += 1

    def nextstart(self):
        """Initialize after warmup."""
        print(f'Warmup complete after {self._warmup_count} bars')

# Call regular next()
        self.next()

```bash

## Implementation Examples

### Example 1: Simple Moving Average with once() Optimization

```python
class FastSMA(bt.Indicator):
    lines = ('sma',)
    params = (('period', 20),)

    def __init__(self):
        super().__init__()
        self.addminperiod(self.p.period)

    def next(self):
        """Bar-by-bar calculation."""
        self.lines.sma[0] = sum(self.data[-i] for i in range(self.p.period)) / self.p.period

    def once(self, start, end):
        """Vectorized batch calculation (2-5x faster)."""
        src = self.data.array
        dst = self.lines.sma.array
        period = self.p.period

        for i in range(start, end):
            dst[i] = sum(src[i-period:i]) / period

```bash

### Example 2: Multi-Data Indicator

```python
class SpreadIndicator(bt.Indicator):
    lines = ('spread', 'zscore')
    _mindatas = 2  # Requires 2 data feeds
    params = (
        ('period', 20),
        ('stddev_period', 20),
    )

    def __init__(self):
        super().__init__()
        self.addminperiod(self.p.stddev_period)

# Calculate spread statistics
        self.spread_mean = bt.indicators.SMA(
            self.data0 - self.data1,
            period=self.p.period
        )
        self.spread_std = bt.indicators.StandardDeviation(
            self.data0 - self.data1,
            period=self.p.stddev_period
        )

    def next(self):
        spread = self.data0[0] - self.data1[0]
        mean = self.spread_mean[0]
        std = self.spread_std[0]

        self.lines.spread[0] = spread
        if std != 0:
            self.lines.zscore[0] = (spread - mean) / std

```bash

### Example 3: Stateful Indicator (EMA)

```python
class CustomEMA(bt.Indicator):
    lines = ('ema',)
    params = (('period', 20),)

    def __init__(self):
        super().__init__()
        self.addminperiod(self.p.period)

# Pre-calculate alpha
        self.alpha = 2.0 / (self.p.period + 1)
        self.alpha1 = 1.0 - self.alpha

    def nextstart(self):
        """Seed EMA with SMA."""
        sma = sum(self.data[-i] for i in range(self.p.period)) / self.p.period
        self.lines.ema[0] = sma

    def next(self):
        """EMA formula: EMA = prior_ema *alpha1 + price*alpha"""
        self.lines.ema[0] = (
            self.lines.ema[-1]*self.alpha1 +
            self.data[0]*self.alpha
        )

    def once(self, start, end):
        """Optimized batch EMA calculation."""
        src = self.data.array
        dst = self.lines.ema.array

# Seed with SMA
        if start < self.p.period:
            sma_start = max(0, start)
            for i in range(sma_start, min(self.p.period, end)):
                dst[i] = sum(src[max(0, i-self.p.period+1):i+1]) / (i+1)
            start = max(start, self.p.period)

# Calculate EMA for remaining bars
        for i in range(start, end):
            dst[i] = dst[i-1]*self.alpha1 + src[i]* self.alpha

```bash

## Common Pitfalls

1. **Forget to call `super().__init__()`**: Always call parent `__init__` first.

2. **Incorrect minperiod**: Use `addminperiod()` to specify warmup requirements.

3. **Mixing next() and once()**: If implementing `once()`, ensure logic matches `next()`.

4. **Array access in next()**: Use relative indexing (`data[0]`, `data[-1]`), not absolute indices.

5. **State initialization**: Use `nextstart()` for one-time initialization after warmup.

6. **Forgetting _ltype**: When subclassing LineIterator directly, set `_ltype` appropriately.

7. **Indicator registration**: Indicators created outside `__init__` may not register properly.

## Next Steps

- [Indicator API](indicator.md) - Creating custom indicators
- [Strategy API](strategy.md) - Building trading strategies
- [Observer API](observer.md) - Chart observers and visualization
- [Data Feeds API](data-feeds.md) - Data source configuration
