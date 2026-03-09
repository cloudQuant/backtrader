- --

title: Performance Optimization
description: Techniques for optimizing backtrader performance

- --

# Performance Optimization

Backtrader's dev branch achieves **45% faster execution** through removing metaclasses and various optimizations. This guide covers techniques to maximize your backtesting performance.

## Quick Wins

### 1. Disable Observers

Observers add overhead. Disable if not needed:

```python

# Disable default observers

cerebro.run(stdstats=False)

# Add only needed observers

cerebro.addobserver(bt.observers.DrawDown)

```bash

### 2. Disable Plotting

Plotting consumes memory. Disable for long backtests:

```python

# Disable all plotting

cerebro.plot = False  # or simply don't call cerebro.plot()

# Disable specific indicators

self.sma.plotinfo.plot = False

```bash

### 3. Use qbuffer

Limit memory usage with circular buffers:

```python
data = bt.feeds.CSVGeneric(dataname='data.csv')
data.qbuffer(1000)  # Keep only last 1000 bars in memory

```bash

## Execution Modes

### `next()` vs `once()`

Backtrader has two execution modes:

| Mode | Speed | Complexity |

|------|-------|------------|

| `next()` | Baseline | Simple |

| `once()` | 2-3x faster | Complex |

- *next() mode** (default):

```python

# Simple, bar-by-bar execution

def next(self):
    if self.data.close[0] > self.sma[0]:
        self.buy()

```bash

- *once() mode** (requires implementation):

```python
def once(self):

# Process all bars at once

# Must handle array operations
    pass

```bash
Most built-in indicators implement optimized `once()` methods.

## Indicator Optimization

### Vectorized Operations

Use vectorized calculations in indicators:

```python
class FastSMA(bt.Indicator):
    lines = ('sma',)
    params = (('period', 20),)

    def __init__(self):

# Vectorized calculation
        self.lines.sma = bt.indicators.PeriodN(
            self.data.close,
            period=self.p.period
        )

```bash

### Avoid Repeated Calculations

Cache expensive calculations:

```python
def __init__(self):
    self.atr = bt.indicators.ATR(self.data, period=14)
    self.upper = self.data.close + self.atr *2
    self.lower = self.data.close - self.atr* 2

def next(self):

# Use pre-calculated values
    if self.data.close[0] > self.upper[0]:
        pass

```bash

## Data Loading Optimization

### Use Binary Formats

Binary formats load faster than CSV:

```python

# Use HDF5 or Parquet for large datasets

import pandas as pd

# Save to binary format once

df.to_parquet('data.parquet')

# Load faster

df = pd.read_parquet('data.parquet')
data = bt.feeds.PandasData(dataname=df)

```bash

### Preload Data

```python

# Preload all data into memory (faster execution)

data = bt.feeds.CSVGeneric(
    dataname='data.csv',
    preload=True  # Load entire file at startup

)

```bash

### Resample Early

Resample data once instead of using filters:

```python

# Instead of runtime resampling

cerebro.resampledata(data, timeframe=bt.TimeFrame.Days)

# Pre-resample your data files

```bash

## Cython Acceleration

Backtrader uses Cython for performance-critical calculations:

### TS (Time Series) Mode

```python

# Fast vectorized operations using pandas

cerebro = bt.Cerebro()
cerebro.run(ts_mode=True)  # Enable TS mode

```bash

### CS (Cross-Section) Mode

```python

# Multi-asset portfolio optimization

cerebro = bt.Cerebro()
cerebro.run(cs_mode=True)  # Enable CS mode

```bash

### Compile Cython Extensions

```bash
cd backtrader
python -W ignore compile_cython_numba_files.py
cd ..
pip install -U .

```bash

## Minimize Hot Path Operations

### Avoid in next()

```python
def next(self):

# ❌ AVOID - expensive calls in hot path
    if len(self.data) > 100:  # len() is called every bar
        pass

# ✅ BETTER - use direct attribute
    if self.data._len > 100:
        pass

```bash

### Cache Attributes

```python
def __init__(self):

# Cache lookups
    self._data_close = self.data.close
    self._sma = self.sma

def next(self):

# Use cached references
    if self._data_close[0] > self._sma[0]:
        self.buy()

```bash

## Parallel Optimization

### Multi-Strategy Backtesting

Run multiple strategies in parallel:

```python

# This will run in parallel if maxcpu > 1

cerebro.optstrategy(
    MyStrategy,
    period=range(10, 50, 10)
)
results = cerebro.run(maxcpu=4)  # Use 4 CPU cores

```bash

## Memory Optimization

### Limit Bars in Memory

```python

# Only keep necessary bars

cerebro = bt.Cerebro()
cerebro.run(
    maxcpu=1,
    runonce=True,  # Single pass
    preload=True   # Optimize memory access

)

```bash

### Use Efficient Data Types

```python

# Use float32 instead of float64 where precision isn't critical

import numpy as np

data = bt.feeds.PandasData(
    dataname=df.astype(np.float32)
)

```bash

## Broker Optimization

### Disable Commission for Speed Testing

```python

# Skip commission calculations for raw speed tests

cerebro.broker.setcommission(commission=0.0)

```bash

### Use Simple Cash Settings

```python

# Direct cash setting is faster

cerebro.broker.setcash(100000)

# Avoid complex margin calculations if not needed

cerebro.broker.set_coc(True)  # Cash-on-close (faster)

```bash

## Specific Optimizations

### Indicator Grouping

Group related indicators:

```python
def __init__(self):

# Group calculations together
    ma_group = bt.indicators.SMA(self.data.close, period=20)
    self.sma = ma_group
    self.sma_lag = ma_group(-1)  # Uses cached calculation

```bash

### Avoid Data Access in Loops

```python

# ❌ AVOID

def next(self):
    for i in range(100):
        value = self.data.close[i]  # Repeated access

# ✅ BETTER

def __init__(self):
    self.data_close = self.data.close.get()  # Get once

```bash

## Profiling

### Profile Your Strategy

```python
import cProfile
import pstats

# Profile execution

profiler = cProfile.Profile()
profiler.enable()

cerebro.run()

profiler.disable()
stats = pstats.Stats(profiler)
stats.sort_stats('cumulative')
stats.print_stats(20)  # Top 20 functions

```bash

### Time Execution

```python
import time

start = time.time()
cerebro.run()
elapsed = time.time() - start

print(f'Execution time: {elapsed:.2f} seconds')
print(f'Bars processed: {len(data)}')
print(f'Bars per second: {len(data)/elapsed:.0f}')

```bash

## Performance Benchmarks

Expected performance on modern hardware:

| Data Points | Strategy | Time |

|-------------|----------|------|

| 10K | Simple | < 1s |

| 100K | Simple | 1-3s |

| 1M | Simple | 10-30s |

| 100K | Complex | 5-15s |

| 1M | Complex | 60-180s |

- Complex = multiple indicators, multiple data feeds, custom logic*

## Optimization Checklist

- [ ] Disable unused observers (`stdstats=False`)
- [ ] Disable unused indicator plots (`plotinfo.plot = False`)
- [ ] Use `qbuffer()` for long backtests
- [ ] Preload data (`preload=True`)
- [ ] Use binary data formats
- [ ] Cache attribute lookups in `__init__`
- [ ] Minimize `len()`, `isinstance()` in hot paths
- [ ] Consider TS/CS mode for large datasets
- [ ] Compile Cython extensions
- [ ] Profile before optimizing

## Next Steps

- [TS Mode Guide](ts-mode.md) - Time series optimization
- [CS Mode Guide](cs-mode.md) - Cross-section optimization
- [Strategy API](/api/strategy.md) - Strategy development
