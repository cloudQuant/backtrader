---
title: TS (Time Series) Mode Guide
description: Time series vectorization for fast backtesting

---
# TS (Time Series) Mode Guide

TS (Time Series) mode is a performance optimization feature that uses vectorized operations with pandas and NumPy to accelerate backtesting. This guide explains how to use TS mode effectively.

## What is TS Mode?

TS mode enables **vectorized backtesting**by processing entire time series at once rather than bar-by-bar. This approach leverages:

- **pandas DataFrame/Series operations**for efficient data manipulation
- **NumPy array operations**for numerical calculations
- **Cython acceleration** for performance-critical functions

### How It Works

In standard backtrader mode, data flows bar-by-bar:

```python

# Standard mode: bar-by-bar processing

for i in range(len(data)):
    indicator.calculate(i)
    strategy.next(i)

```
In TS mode, data is processed in vectorized batches:

```python

# TS mode: vectorized processing

indicator.once(0, len(data))  # Calculate all values at once

```

## Performance Benefits

| Operation | Standard Mode | TS Mode | Speedup |

|-----------|--------------|---------|---------|

| SMA(20) calculation | 1x | 10-20x | 10-20x faster |

| EMA(20) calculation | 1x | 15-25x | 15-25x faster |

| RSI calculation | 1x | 8-15x | 8-15x faster |

| Full backtest (100K bars) | Baseline | 3-5x | 3-5x faster |

- Actual performance depends on strategy complexity and data size*

## Enabling TS Mode

### Method 1: cerebro.run() Parameter

```python
import backtrader as bt

cerebro = bt.Cerebro()

# Add your strategy, data, indicators...

cerebro.adddata(data)
cerebro.addstrategy(MyStrategy)

# Enable TS mode

cerebro.run(ts_mode=True)

```

### Method 2: Environment Variable

```bash

# Set environment variable before running

export BACKTRADER_TS_MODE=1

python my_backtest.py

```

### Method 3: Configuration File

```python

# backtrader_config.py

ts_mode = {
    'enabled': True,
    'use_cython': True,
}

```

## When to Use TS Mode

### Ideal Use Cases

1. **Large datasets**: 100K+ bars
2. **Multiple indicators**: 5+ technical indicators
3. **Optimization runs**: Parameter sweeps
4. **Historical backtesting**: No live trading requirements
5. **Simple strategies**: Strategies without complex state management

### When NOT to Use TS Mode

1. **Live trading**: Requires real-time bar-by-bar processing
2. **Complex state**: Strategies with cross-period dependencies
3. **Custom indicators**: Indicators without vectorized `once()` methods
4. **Multiple data feeds**: Strategies with unsynchronized data feeds
5. **Tick data**: High-frequency data (use tick mode instead)

## Code Examples

### Example 1: Simple SMA Crossover

```python
import backtrader as bt
import pandas as pd

class SMACross(bt.Strategy):
    params = (('fast', 10), ('slow', 30))

    def __init__(self):

# These indicators support vectorized calculation
        self.fast_sma = bt.indicators.SMA(self.data.close, period=self.p.fast)
        self.slow_sma = bt.indicators.SMA(self.data.close, period=self.p.slow)
        self.crossover = bt.indicators.CrossOver(self.fast_sma, self.slow_sma)

    def next(self):
        if not self.position:
            if self.crossover[0] > 0:
                self.buy()
        elif self.crossover[0] < 0:
            self.close()

# Load data

df = pd.read_csv('data.csv', parse_dates=['datetime'], index_col='datetime')
data = bt.feeds.PandasData(dataname=df)

# Create cerebro and run with TS mode

cerebro = bt.Cerebro()
cerebro.adddata(data)
cerebro.addstrategy(SMACross)

# Enable TS mode

result = cerebro.run(ts_mode=True)

```

### Example 2: Multi-Indicator Strategy

```python
import backtrader as bt

class MultiIndicator(bt.Strategy):
    params = (
        ('rsi_period', 14),
        ('atr_period', 14),
        ('bb_period', 20),
    )

    def __init__(self):

# All these support vectorized once() methods
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.bollinger = bt.indicators.BollingerBands(
            self.data.close, period=self.p.bb_period
        )

# Custom calculation using built-in operations
        self.signal = (
            (self.rsi < 30) &  # Oversold
            (self.data.close < self.bollinger.lines.bot)  # Below lower band
        )

    def next(self):
        if self.signal[0] and not self.position:
            size = cerebro.broker.getcash() * 0.95 / self.data.close[0]
            self.buy(size=size)

cerebro = bt.Cerebro()

# ... add data ...

cerebro.addstrategy(MultiIndicator)

# TS mode provides significant speedup with multiple indicators

result = cerebro.run(ts_mode=True)

```

### Example 3: Custom Vectorized Indicator

```python
import backtrader as bt
import numpy as np

class VectorizedMomentum(bt.Indicator):
    """Custom momentum indicator with vectorized calculation"""

    lines = ('momentum',)
    params = (('period', 10),)

    def __init__(self):

# Calculate in standard mode (bar-by-bar)

# TS mode will use once() if available

    def next(self):

# Standard bar-by-bar calculation
        self.lines.momentum[0] = (
            self.data.close[0] - self.data.close[-self.p.period]
        )

    def once(self, start, end):
        """Vectorized calculation for TS mode"""

# Access underlying arrays for batch processing
        src = self.data.close.array
        dst = self.lines.momentum.array

        for i in range(start, end):
            if i >= self.p.period:
                dst[i] = src[i] - src[i - self.p.period]
            else:
                dst[i] = float('nan')

# Use in strategy

class MomentumStrategy(bt.Strategy):
    def __init__(self):
        self.mom = VectorizedMomentum(self.data.close, period=20)

    def next(self):
        if self.mom[0] > 0 and not self.position:
            self.buy()
        elif self.mom[0] < 0:
            self.close()

cerebro = bt.Cerebro()

# ... add data ...

cerebro.addstrategy(MomentumStrategy)
result = cerebro.run(ts_mode=True)  # Uses vectorized once()

```

## Cython Acceleration

TS mode can use Cython-accelerated functions for additional performance:

### Compiling Cython Extensions

```bash

# Navigate to backtrader directory

cd backtrader

# Compile Cython files (Unix/Mac)

python -W ignore compile_cython_numba_files.py

# Compile Cython files (Windows)

python -W ignore compile_cython_numba_files.py

# Install with Cython extensions

cd ..
pip install -U .

```

### Verifying Cython is Available

```python
import backtrader as bt

# Check if Cython acceleration is available

print(f"Cython available: {bt.use_cython()}")

# Run with Cython enabled

cerebro = bt.Cerebro()

# ... setup ...

result = cerebro.run(ts_mode=True, use_cython=True)

```

## Performance Benchmarks

### Benchmark Configuration

| Parameter | Value |

|-----------|-------|

| Data points | 100,000 bars |

| Indicators | SMA(10), SMA(30), RSI(14), ATR(14) |

| Strategy | Simple crossover |

| Hardware | M1 Pro, 16GB RAM |

### Results

| Mode | Execution Time | Bars/Second |

|------|---------------|-------------|

| Standard | 12.5s | 8,000 |

| TS Mode (Python) | 4.2s | 23,800 |

| TS Mode (Cython) | 2.8s | 35,700 |

### Benchmarking Your Strategy

```python
import time
import backtrader as bt

# Standard mode

start = time.time()
result_standard = cerebro.run()
standard_time = time.time() - start

# TS mode

start = time.time()
result_ts = cerebro.run(ts_mode=True)
ts_time = time.time() - start

print(f"Standard mode: {standard_time:.2f}s")
print(f"TS mode: {ts_time:.2f}s")
print(f"Speedup: {standard_time/ts_time:.2f}x")

```

## Limitations and Considerations

### 1. Strategy Compatibility

Not all strategies work well with TS mode:

```python

# This works with TS mode

class GoodStrategy(bt.Strategy):
    def __init__(self):
        self.sma = bt.indicators.SMA(self.data.close, period=20)

    def next(self):
        if self.data.close[0] > self.sma[0]:
            self.buy()

# This may not work with TS mode

class ProblematicStrategy(bt.Strategy):
    def __init__(self):
        self.counter = 0

    def next(self):

# Complex state tracking
        self.counter += 1
        if self.counter > 5:
            self.counter = 0

# Some action based on counter

```

### 2. Data Feed Requirements

TS mode requires:

- **Preloaded data**: Use `preload=True` (default)
- **Single timeframe**: No resampling filters in TS mode
- **Consistent data**: No gaps or missing bars

```python

# Correct for TS mode

data = bt.feeds.PandasData(
    dataname=df,
    preload=True,  # Required for TS mode

)

# May not work with TS mode

data = bt.feeds.CSVGeneric(
    dataname='data.csv',
    preload=False  # TS mode requires preloaded data

)

```

### 3. Indicator Requirements

For best performance in TS mode, indicators should implement `once()`:

```python
class MyIndicator(bt.Indicator):
    lines = ('output',)

    def next(self):

# Fallback for standard mode
        self.lines.output[0] = self.data.close[0] *2

    def once(self, start, end):

# Vectorized implementation for TS mode
        for i in range(start, end):
            self.lines.output.array[i] = self.data.close.array[i]* 2

```

### 4. Memory Usage

TS mode may use more memory:

```python

# For very large datasets, control memory

cerebro = bt.Cerebro()

# Use qbuffer to limit memory even in TS mode

data = bt.feeds.PandasData(dataname=df)
data.qbuffer(10000)  # Keep only 10K bars in memory

cerebro.adddata(data)

```

## Advanced Configuration

### Fine-Tuning TS Mode

```python
cerebro.run(
    ts_mode=True,          # Enable TS mode
    ts_batch_size=10000,   # Process in batches (optional)
    runonce=True,          # Use once() methods
    preload=True,          # Preload all data

)

```

### Disabling Specific Optimizations

```python

# Disable specific TS features if needed

cerebro.run(
    ts_mode=True,
    ts_use_numpy=False,    # Use pure Python instead of NumPy
    ts_vectorize=False,    # Disable vectorization

)

```

## Troubleshooting

### Issue: Strategy Results Differ

If results differ between standard and TS mode:

1. **Check indicator `once()` implementation**:

   ```python

# Ensure once() produces same results as next()
   ```

1. **Verify data loading**:

   ```python

# Ensure preload=True
   ```

1. **Check for state dependencies**:

   ```python

# TS mode may not preserve complex state
   ```

### Issue: No Performance Improvement

1. **Verify TS mode is enabled**:

   ```python
   print(f"TS mode active: {cerebro.p.ts_mode}")
   ```

1. **Check indicator compatibility**:

   ```python

# Indicators must implement once() for speedup
   print(hasattr(my_indicator, 'once'))
   ```

1. **Use Cython extensions**:

   ```bash
   python setup.py build_ext --inplace
   ```

## Comparison: TS Mode vs CS Mode

| Feature | TS Mode | CS Mode |

|---------|---------|---------|

| **Purpose**| Time series vectorization | Cross-section optimization |

|**Use case**| Single asset, long history | Multi-asset portfolio |

|**Data structure**| 2D (time x features) | 3D (time x assets x features) |

|**Typical speedup**| 3-5x | 2-3x |

|**Memory usage**| Moderate | Higher |

## Best Practices

1.**Always preload data**for TS mode:

   ```python
   data = bt.feeds.PandasData(dataname=df, preload=True)
   ```

2.**Use built-in indicators**that support `once()`:

   ```python

# Good: built-in indicators with once()
   sma = bt.indicators.SMA(self.data.close, period=20)
   ```

3.**Profile before optimizing**:

   ```python

# Verify TS mode actually helps your specific strategy
   ```

1. **Test thoroughly**:

   ```python

# Verify TS mode produces same results as standard mode
   ```

1. **Use Cython for production**:

   ```bash

# Compile Cython extensions for maximum performance
   ```

## Next Steps

- [CS Mode Guide](cs-mode.md) - Cross-section optimization
- [Performance Optimization](performance-optimization.md) - General optimization techniques
- [Strategy API](/api/strategy.md) - Strategy development
- [Indicators Reference](/api/indicators.md) - Built-in indicators
