- --

title: LineRoot API Reference
description: Base class for line-based time-series data structures

- --

# LineRoot API Reference

`LineRoot` is the foundational base class for all line-based objects in Backtrader. It provides the core interface for time-series data management, period handling, and operator overloading for arithmetic and comparison operations.

## Class Hierarchy

```mermaid
classDiagram
    LineRoot <|-- LineSingle

    LineRoot <|-- LineMultiple

    LineRootMixin <|-- LineRoot

    BaseMixin <|-- LineRoot

    LineSingle <|-- LineBuffer

    LineMultiple <|-- LineSeries

    LineMultiple <|-- Indicator

    LineMultiple <|-- Strategy

    LineBuffer <|-- LinesOperation

    LineBuffer <|-- LineOwnOperation

    class LineRoot {
        <<abstract>>

        - _minperiod: int
        - _opstage: int
        - _OwnerCls: type
        - IndType: int
        - StratType: int
        - ObsType: int
        - prenext()
        - nextstart()
        - next()
        - preonce()
        - once()
        - setminperiod()
        - updateminperiod()
        - qbuffer()
        - minbuffer()

    }

    class LineRootMixin {
        <<mixin>>

        - donew()
        - _owner: object

    }

    class LineSingle {

        - addminperiod()
        - incminperiod()

    }

    class LineMultiple {

        - lines: Lines
        - _ltype: int
        - _clock: object
        - _lineiterators: dict
        - reset()
        - size()

    }

    class LineBuffer {

        - array: array
        - _idx: int
        - mode: int
        - home()
        - forward()
        - rewind()
        - __getitem__()
        - __setitem__()

    }

```bash

## Core Concepts

### Line System Overview

The Line system is Backtrader's core data structure for time-series manipulation:

- **Index 0 always points to the current value**- No need to track indices manually
- **Positive indices access past values**- `data.close[-1]` is the previous bar
- **Negative indices access future values**- Used in specific scenarios like replay
- **Automatic period management**- Objects wait for minimum data before calculating

### Operation Stages

LineRoot implements a two-stage operation system:

- **Stage 1 (`_opstage = 1`)**: Construction phase - Creates lazy evaluation objects
- **Stage 2 (`_opstage = 2`)**: Execution phase - Returns actual values during backtesting

## Class Attributes

### `_minperiod`

```python
obj._minperiod  # int: Minimum periods needed before valid output

```bash
The minimum number of bars required before the object produces valid output.

```python

# SMA with period 20 needs 20 bars

sma = bt.indicators.SMA(period=20)
print(sma._minperiod)  # 20

```bash

### `_opstage`

```python
obj._opstage  # int: Current operation stage (1 or 2)

```bash
Controls whether operations create objects (stage 1) or return values (stage 2).

### `_OwnerCls`

```python
obj._OwnerCls  # type: Expected owner class type

```bash
Specifies the class type that should own this object. Used by `findowner()`.

### Type Constants

```python
LineRoot.IndType   # 0 - Indicator type

LineRoot.StratType # 1 - Strategy type

LineRoot.ObsType   # 2 - Observer type

```bash
Used to identify object types in the line hierarchy.

## Period Management Methods

### `setminperiod()`

```python
obj.setminperiod(minperiod: int) -> None

```bash
Directly set the minimum period requirement.

- *Parameters:**
- `minperiod`: Minimum number of bars needed

- *Use Case:** Override indicator requirements in strategies:

```python
class MyStrategy(bt.Strategy):
    def __init__(self):
        self.sma = bt.indicators.SMA(period=50)

# Don't wait for full SMA - start after 20 bars
        self.sma.setminperiod(20)

```bash

### `updateminperiod()`

```python
obj.updateminperiod(minperiod: int) -> None

```bash
Update minimum period to the maximum of current and provided value.

- *Parameters:**
- `minperiod`: Proposed minimum period

- *Example:** Used internally when indicators chain:

```python
class MyIndicator(bt.Indicator):
    def __init__(self):
        self.sma1 = bt.indicators.SMA(period=10)
        self.sma2 = bt.indicators.SMA(period=20)

# _minperiod automatically becomes max(10, 20) = 20

```bash

### `addminperiod()`

```python
obj.addminperiod(minperiod: int) -> None

```bash
Add to minimum period (with overlap adjustment). Subtracts 1 to account for overlapping periods.

- *Note:** Implementation differs between `LineSingle` and `LineMultiple`.

### `incminperiod()`

```python
obj.incminperiod(minperiod: int) -> None

```bash
Increment minimum period without considerations (no overlap adjustment).

## Execution Phase Methods

### `prenext()`

```python
obj.prenext() -> None

```bash
Called during the minimum period phase when not enough data is available yet.

- *Override** to customize pre-period behavior:

```python
class MyIndicator(bt.Indicator):
    def prenext(self):

# Called each bar until minperiod is reached
        print(f"Accumulating data: {len(self)} bars")

```bash

### `nextstart()`

```python
obj.nextstart() -> None

```bash
Called once when minimum period is first satisfied, before normal `next()` calls.

- *Default:** Automatically calls `next()`.

- *Override** for special startup behavior:

```python
def nextstart(self):
    print(f"Indicator ready! First valid value: {self.line[0]}")
    self.next()  # Continue with normal next()

```bash

### `next()`

```python
obj.next() -> None

```bash
Called for each bar after minimum period is satisfied.

- *Override** to implement calculation logic:

```python
def next(self):
    self.line[0] = self.data.close[0] *2

```bash

### `preonce()` and `once()`

```python
obj.preonce(start: int, end: int) -> None
obj.once(start: int, end: int) -> None

```bash
Called during vectorized (`once`) mode for batch processing.

- *Parameters:**
- `start`: Starting index
- `end`: Ending index

- *Override** for optimized calculations:

```python
def once(self, start, end):

# Vectorized calculation from start to end
    for i in range(start, end):
        self.line.array[i] = self.data.close.array[i] *2

```bash

### `oncestart()`

```python
obj.oncestart(start: int, end: int) -> None

```bash
Called once in `once` mode when minimum period is first satisfied.

## Arithmetic Operators

LineRoot implements operator overloading for creating lazy-evaluated operations:

### Basic Arithmetic

```python

# Addition

result = data.close + data.open
result = data.close + 10
result = 10 + data.close  # __radd__

# Subtraction

result = data.close - data.open
result = data.close - 10
result = 10 - data.close  # __rsub__

# Multiplication

result = data.close* 2

# Division

result = data.close / 2

# Power

result = data.close ** 2

# Absolute value

result = abs(-data.close)

# Negation

result = -data.close

```bash

### Comparison Operators

```python

# Comparisons create boolean line operations

cross_up = data.close > data.high
cross_down = data.close < data.low
equals = data.close == data.open
not_equals = data.close != data.open

```bash

## Line Management

### `lines` Attribute (LineMultiple)

```python
obj.lines  # Lines collection

```bash
Container for all line objects in a multi-line object.

```python

# Access lines by index

first_line = obj.lines[0]

# Access lines by name (if aliased)

close_line = data.lines.close

# Get number of lines

num_lines = len(obj.lines)

```bash

### `linealias` Descriptor

Provides named access to lines:

```python
class MyIndicator(bt.Indicator):
    lines = ('signal', 'trend')

# Access via alias

indicator.lines.signal[0]
indicator.lines.trend[0]

```bash

### `size()`

```python
obj.size() -> int

```bash
Return the number of lines in this object.

```python
data = bt.feeds.YahooFinanceData(dataname='AAPL')
print(data.size())  # Number of data lines (OHLCV)

```bash

## Buffer Management

### `qbuffer()`

```python
obj.qbuffer(savemem: int = 0) -> None

```bash
Change lines to implement minimum-size queue buffer scheme for memory efficiency.

- *Parameters:**
- `savemem`: Memory savings level (0 = normal, higher = more aggressive)

```python

# Apply to all data feeds for large backtests

for data in cerebro.datas:
    data.qbuffer(savemem=1)

```bash

### `minbuffer()`

```python
obj.minbuffer(size: int) -> None

```bash
Notify object of minimum buffer size requirement.

## Owner Relationships

### `_owner` Attribute

```python
obj._owner  # Reference to owning object

```bash
Set automatically via `findowner()` during construction.

### Owner Finding (LineRootMixin)

```python
@classmethod
def donew(cls, *args, **kwargs):
    """Create instance with owner finding logic"""

```bash
The `LineRootMixin.donew()` method:

1. Creates the object instance
2. Calls `metabase.findowner()` to locate the owner in the call stack
3. Sets `_owner` attribute

### Owner Types

| Object Type | Typical Owner |

|-------------|---------------|

| Indicator | Strategy or another Indicator |

| Observer | Strategy or Cerebro |

| Analyzer | Strategy |

| Data Feed | Cerebro |

## Type Constants

```python

# Object type identification

LineRoot.IndType   # 0 - For indicators

LineRoot.StratType # 1 - For strategies

LineRoot.ObsType   # 2 - For observers

```bash
Used in `_ltype` attribute to identify object type:

```python
if obj._ltype == LineRoot.IndType:

# This is an indicator
    pass

```bash

## Line Access Patterns

### Current Value (Index 0)

```python

# Current bar's close price

current_close = data.close[0]

# Current indicator value

current_sma = self.sma[0]

```bash

### Past Values (Positive Indices)

```python

# Previous close

prev_close = data.close[-1]

# Close 5 bars ago

close_5_ago = data.close[-5]

```bash

### Setting Values

```python

# In indicator's next()

self.signal[0] = 1 if data.close[0] > data.close[-1] else -1

```bash

### Checking Data Availability

```python
def next(self):

# Always check length before accessing past values
    if len(self.data) >= 2:
        change = self.data.close[0] - self.data.close[-1]

```bash

## LineSingle vs LineMultiple

### LineSingle

Base for single-line objects like `LineBuffer`:

```python
class LineSingle(LineRoot):
    def addminperiod(self, minperiod):
        self._minperiod += minperiod - 1

    def incminperiod(self, minperiod):
        self._minperiod += minperiod

```bash

### LineMultiple

Base for multi-line objects like `Indicator`, `Strategy`:

```python
class LineMultiple(LineRoot):
    def __init__(self):
        self._ltype = None
        self.lines = Lines()
        self._clock = None
        self._lineiterators = {}

    def reset(self):
        self._stage1()
        self.lines.reset()

```bash

## Operation Methods (Internal)

### `_stage1()` / `_stage2()`

```python
obj._stage1()  # Set operation stage to 1 (construction)

obj._stage2()  # Set operation stage to 2 (execution)

```bash

### `_operation()`

```python
obj._operation(other, operation, r=False, intify=False)

```bash
Internal method for two-operand operations.

### `_operationown()`

```python
obj._operationown(operation)

```bash
Internal method for single-operand operations.

## Boolean Context

```python

# LineRoot objects support boolean evaluation

if data.close > data.close[-1]:

# This works because __bool__ checks current value
    pass

# Direct evaluation

if self.cross:

# True if cross line has non-zero value
    pass

```bash

## Usage Examples

### Creating a Custom Indicator

```python
import backtrader as bt

class PriceChange(bt.Indicator):
    lines = ('change', 'pct_change')

    def __init__(self):

# Requires at least 2 bars
        self.addminperiod(2)

    def next(self):
        self.lines.change[0] = self.data.close[0] - self.data.close[-1]
        if self.data.close[-1] != 0:
            self.lines.pct_change[0] = (
                self.lines.change[0] / self.data.close[-1] * 100
            )

```bash

### Using Period Management

```python
class AdaptiveStrategy(bt.Strategy):
    def __init__(self):
        self.fast_sma = bt.indicators.SMA(period=10)
        self.slow_sma = bt.indicators.SMA(period=50)

# Override: don't wait for slow SMA
        self.setminperiod(10)  # Start when fast SMA is ready

    def next(self):
        if len(self) >= self.slow_sma._minperiod:

# Both SMAs are ready
            pass

```bash

### Line Operations

```python
class Momentum(bt.Indicator):
    lines = ('momentum',)

    def __init__(self, period=14):

# Using arithmetic operators creates line operations
        self.lines.momentum = self.data.close - self.data.close(-period)

```bash

## Performance Considerations

1. **Minimize `len()` calls in hot paths**- Cache lengths when possible

2.**Use `once()` mode for vectorized operations**- Faster than `next()`
3.**Use `qbuffer()` for long backtests**- Reduces memory usage
4.**Avoid deep indicator nesting** - Each level adds overhead

## Common Patterns

### Cross Detection

```python
class CrossOver(bt.Indicator):
    lines = ('cross',)

    def __init__(self):
        self.lines.cross = bt.indicators.CrossOver(
            self.data.close, self.data.close(-1))

```bash

### Multi-Line Indicator

```python
class BollingerBands(bt.Indicator):
    lines = ('mid', 'top', 'bot')

    params = (('period', 20), ('devfactor', 2.0))

    def __init__(self):
        self.lines.mid = bt.indicators.SMA(self.data, period=self.p.period)
        self.lines.top = self.lines.mid + self.p.devfactor *bt.indicators.StandardDeviation(self.data, period=self.p.period)
        self.lines.bot = self.lines.mid - self.p.devfactor* bt.indicators.StandardDeviation(self.data, period=self.p.period)

```bash

## Related Classes

- **LineBuffer**: Circular buffer storage for single lines
- **LineSeries**: Multi-line time-series collections
- **LineIterator**: Base for iteration logic (indicators, strategies)
- **Lines**: Container class for multiple line objects
- **LineAlias**: Descriptor for named line access

## Source Files

- `backtrader/lineroot.py`: Core LineRoot implementation
- `backtrader/linebuffer.py`: LineBuffer (single line storage)
- `backtrader/lineseries.py`: LineSeries (multi-line collections)
- `backtrader/lineiterator.py`: LineIterator (iteration logic)
- `backtrader/metabase.py`: BaseMixin and owner finding
