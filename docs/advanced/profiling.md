---
title: Performance Analysis and Profiling
description: Guide to profiling and analyzing Backtrader strategy performance
---

# Performance Analysis and Profiling

Effective performance analysis is crucial for optimizing quantitative trading strategies. This guide provides comprehensive techniques for profiling Backtrader strategies, identifying bottlenecks, and measuring performance improvements.

## Table of Contents

- [cProfile Usage](#cprofile-usage)
- [Hot Path Identification](#hot-path-identification)
- [Memory Profiling](#memory-profiling)
- [Strategy-Specific Profiling](#strategy-specific-profiling)
- [Benchmarking Methodologies](#benchmarking-methodologies)
- [Performance Optimization Tips](#performance-optimization-tips)

## cProfile Usage

### Basic Profiling

The simplest way to profile a Backtrader strategy:

```python
import cProfile
import pstats
import backtrader as bt

class MyStrategy(bt.Strategy):
    def __init__(self):
        self.sma = bt.indicators.SMA(period=20)

    def next(self):
        if self.data.close[0] > self.sma[0]:
            self.buy()

# Setup cerebro
cerebro = bt.Cerebro()
cerebro.addstrategy(MyStrategy)
data = bt.feeds.CSVGeneric(dataname='data.csv')
cerebro.adddata(data)

# Profile the execution
profiler = cProfile.Profile()
profiler.enable()

results = cerebro.run()

profiler.disable()

# Print results
stats = pstats.Stats(profiler)
stats.sort_stats('cumulative')
stats.print_stats(20)  # Top 20 functions by cumulative time
```

### Saving Profile Results

For detailed analysis, save profile to file:

```python
# Save profile to file
profiler.dump_stats('my_strategy.prof')

# Load later for analysis
stats = pstats.Stats('my_strategy.prof')
stats.sort_stats('cumulative')
stats.print_stats(30)
```

### SnakeViz Visualization

For visual profile analysis:

```bash
pip install snakeviz

# Generate visualization
snakeviz my_strategy.prof
```

This opens an interactive visualization showing:
- Icicle plot of call stack
- Time distribution per function
- Navigation to hot paths

### Profiling with Context Manager

Create a reusable profiler context manager:

```python
import cProfile
import pstats
import io
from contextlib import contextmanager

@contextmanager
def profile(output_file=None, print_stats=20):
    """Context manager for profiling code blocks.

    Args:
        output_file: If provided, save profile to this file
        print_stats: Number of top functions to print
    """
    profiler = cProfile.Profile()
    profiler.enable()

    yield

    profiler.disable()

    if output_file:
        profiler.dump_stats(output_file)

    stats = pstats.Stats(profiler)
    stats.sort_stats('cumulative')
    stats.strip_dirs()
    if print_stats:
        stats.print_stats(print_stats)

# Usage
with profile('strategy.prof', print_stats=30):
    cerebro.run()
```

## Hot Path Identification

### Finding Expensive Functions

Identify functions consuming the most CPU time:

```python
import cProfile
import pstats

profiler = cProfile.Profile()
profiler.enable()

cerebro.run()

profiler.disable()

# Sort by total time in function (not including subcalls)
stats = pstats.Stats(profiler)
stats.sort_stats('time')  # 'tottime' - time in function excluding children
stats.print_stats(10)

# Sort by cumulative time (including subcalls)
stats.sort_stats('cumulative')
stats.print_stats(10)
```

### Identifying Indicator Bottlenecks

Profile specific indicator calculations:

```python
class ProfiledStrategy(bt.Strategy):
    def __init__(self):
        # Profile indicator creation
        import cProfile
        self.ind_profiler = cProfile.Profile()
        self.ind_profiler.enable()

        self.sma20 = bt.indicators.SMA(period=20)
        self.ema50 = bt.indicators.EMA(period=50)
        self.rsi = bt.indicators.RSI(period=14)
        self.macd = bt.indicators.MACD()

        self.ind_profiler.disable()

    def start(self):
        # Print indicator initialization profile
        stats = pstats.Stats(self.ind_profiler)
        stats.sort_stats('cumulative')
        stats.strip_dirs()
        stats.print_stats(15)
```

### Line-by-Line Profiling

For detailed analysis, use line_profiler:

```bash
pip install line_profiler
```

```python
# Add @profile decorator to methods you want to profile
class MyStrategy(bt.Strategy):
    @profile
    def next(self):
        # Complex logic to analyze line-by-line
        if self.data.close[0] > self.sma[0]:
            if self.rsi[0] < 30:
                self.buy()

# Run with: kernprof -l -v my_script.py
```

## Memory Profiling

### Memory Usage Tracking

Track memory usage during backtesting:

```python
import memory_profiler
import backtrader as bt

class MemoryTrackedStrategy(bt.Strategy):
    def __init__(self):
        self.sma = bt.indicators.SMA(period=20)

    @memory_profiler.profile
    def next(self):
        if self.data.close[0] > self.sma[0]:
            self.buy()

# Run with: python -m memory_profiler my_script.py
```

### Memory Peak Analysis

Find peak memory usage:

```python
import tracemalloc
import backtrader as bt

# Start tracing
tracemalloc.start()

# Run backtest
cerebro.run()

# Get peak memory usage
current, peak = tracemalloc.get_traced_memory()
print(f"Current memory: {current / 10**6:.2f} MB")
print(f"Peak memory: {peak / 10**6:.2f} MB")

# Get snapshot of largest allocations
snapshot = tracemalloc.take_snapshot()
top_stats = snapshot.statistics('lineno')

print("[Top 10 memory allocations]")
for stat in top_stats[:10]:
    print(stat)

tracemalloc.stop()
```

### Memory Profiling with mprof

```bash
pip install memory_profiler

# Run with memory tracking
mprof run python my_backtest.py

# Plot memory usage over time
mprof plot

# Peak memory details
mprof clean
mprof run --include-children python my_backtest.py
```

### Reducing Memory Usage

```python
import gc
import backtrader as bt

# Configure for low memory usage
cerebro = bt.Cerebro()

# Use qbuffer to limit data history
data = bt.feeds.CSVGeneric(dataname='large_data.csv')
data.qbuffer(1000)  # Keep only last 1000 bars in memory
cerebro.adddata(data)

# Disable observers that consume memory
cerebro.run(stdstats=False)

# Explicit garbage collection
results = cerebro.run()
gc.collect()
```

## Strategy-Specific Profiling

### Execution Time Breakdown

Break down time spent in different phases:

```python
import time
import backtrader as bt

class TimedStrategy(bt.Strategy):
    """Strategy with detailed timing metrics."""

    def __init__(self):
        self.timings = {
            'indicator_calc': 0,
            'signal_generation': 0,
            'order_execution': 0,
        }

    def next(self):
        # Time indicator access
        start = time.perf_counter()
        sma_val = self.sma[0]
        rsi_val = self.rsi[0]
        self.timings['indicator_calc'] += time.perf_counter() - start

        # Time signal logic
        start = time.perf_counter()
        signal = self.generate_signal(sma_val, rsi_val)
        self.timings['signal_generation'] += time.perf_counter() - start

        # Time order execution
        start = time.perf_counter()
        if signal == 'BUY':
            self.buy()
        self.timings['order_execution'] += time.perf_counter() - start

    def generate_signal(self, sma, rsi):
        """Custom signal generation logic."""
        if sma > 0 and rsi < 30:
            return 'BUY'
        return 'HOLD'

    def stop(self):
        """Print timing statistics on completion."""
        total = sum(self.timings.values())
        print("\n=== Timing Breakdown ===")
        for phase, duration in self.timings.items():
            pct = (duration / total) * 100 if total > 0 else 0
            print(f"{phase}: {duration:.4f}s ({pct:.1f}%)")
```

### Per-Bar Timing

Identify slow bars:

```python
import time
import backtrader as bt

class PerBarTimedStrategy(bt.Strategy):
    """Track timing for each bar."""

    params = (('slow_threshold', 0.001),)  # 1ms threshold

    def __init__(self):
        self.bar_timings = []

    def prenext(self):
        self.time_bar()

    def next(self):
        self.time_bar()

    def time_bar(self):
        """Time execution for current bar."""
        start = time.perf_counter()

        # Your strategy logic here
        if self.data.close[0] > self.sma[0]:
            self.buy()

        elapsed = time.perf_counter() - start
        self.bar_timings.append(elapsed)

        # Warn about slow bars
        if elapsed > self.p.slow_threshold:
            print(f"Slow bar at {self.data.datetime.date(0)}: {elapsed*1000:.2f}ms")

    def stop(self):
        """Analyze bar timing statistics."""
        import statistics
        if self.bar_timings:
            print("\n=== Bar Timing Statistics ===")
            print(f"Total bars: {len(self.bar_timings)}")
            print(f"Mean: {statistics.mean(self.bar_timings)*1000:.3f}ms")
            print(f"Median: {statistics.median(self.bar_timings)*1000:.3f}ms")
            print(f"Max: {max(self.bar_timings)*1000:.3f}ms")
            print(f"Min: {min(self.bar_timings)*1000:.3f}ms")
```

### Indicator Caching Analysis

Test if indicator caching helps:

```python
import cProfile
import pstats

def test_without_cache():
    """Run without indicator caching."""
    bt.indicators.IndicatorRegistry.usecache(False)
    cerebro = create_cerebro()  # Your setup function
    cerebro.run()

def test_with_cache():
    """Run with indicator caching."""
    bt.indicators.IndicatorRegistry.usecache(True)
    cerebro = create_cerebro()
    cerebro.run()

# Profile both
for func in [test_without_cache, test_with_cache]:
    profiler = cProfile.Profile()
    profiler.enable()
    func()
    profiler.disable()
    stats = pstats.Stats(profiler)
    stats.sort_stats('cumulative')
    stats.print_stats(10)
    print("-" * 50)
```

## Benchmarking Methodologies

### Comparative Benchmarking

Compare strategy performance:

```python
import time
import statistics

def benchmark_strategy(strategycls, iterations=5):
    """Run multiple iterations and collect statistics."""
    times = []

    for i in range(iterations):
        cerebro = bt.Cerebro()
        cerebro.addstrategy(strategycls)
        setup_data(cerebro)  # Your data setup

        start = time.perf_counter()
        cerebro.run()
        elapsed = time.perf_counter() - start
        times.append(elapsed)

        print(f"Run {i+1}: {elapsed:.4f}s")

    return {
        'mean': statistics.mean(times),
        'stdev': statistics.stdev(times) if len(times) > 1 else 0,
        'min': min(times),
        'max': max(times),
    }

# Compare strategies
results = {
    'Simple': benchmark_strategy(SimpleStrategy),
    'Complex': benchmark_strategy(ComplexStrategy),
}

for name, stats in results.items():
    print(f"{name}: {stats['mean']:.4f}s ± {stats['stdev']:.4f}s")
```

### Scale Testing

Test performance vs data size:

```python
import time
import backtrader as bt

def benchmark_data_size(sizes):
    """Test performance with different data sizes."""
    results = []

    for size in sizes:
        # Generate data of this size
        data = generate_test_data(size)  # Your data generator

        cerebro = bt.Cerebro()
        cerebro.adddata(data)
        cerebro.addstrategy(MyStrategy)

        start = time.perf_counter()
        cerebro.run()
        elapsed = time.perf_counter() - start

        bars_per_sec = size / elapsed
        results.append((size, elapsed, bars_per_sec))
        print(f"{size} bars: {elapsed:.2f}s ({bars_per_sec:.0f} bars/sec)")

    return results

# Test with increasing data sizes
sizes = [1000, 5000, 10000, 50000, 100000]
benchmark_data_size(sizes)
```

### Progress Monitoring

Monitor long-running backtests:

```python
import time
import backtrader as bt

class ProgressStrategy(bt.Strategy):
    """Strategy that reports progress."""

    params = (('report_interval', 1000),)

    def __init__(self):
        self.start_time = time.time()
        self.last_report = 0

    def next(self):
        current_bar = len(self.data)

        # Report progress at intervals
        if current_bar - self.last_report >= self.p.report_interval:
            elapsed = time.time() - self.start_time
            bars_per_sec = current_bar / elapsed

            print(f"Progress: {current_bar} bars | "
                  f"{bars_per_sec:.0f} bars/sec | "
                  f"{elapsed:.0f}s elapsed")

            self.last_report = current_bar

    def stop(self):
        """Final report."""
        elapsed = time.time() - self.start_time
        total_bars = len(self.data)
        print(f"\nCompleted: {total_bars} bars in {elapsed:.2f}s")
        print(f"Average: {total_bars/elapsed:.0f} bars/sec")
```

## Performance Optimization Tips

### Before You Optimize

1. **Profile first**: Measure before making changes
2. **Establish baseline**: Know your current performance
3. **Set goals**: Know what improvement you need
4. **Test thoroughly**: Ensure optimization doesn't break functionality

### Quick Wins

```python
# 1. Disable unnecessary observers
cerebro.run(stdstats=False)

# 2. Disable plotting
# Don't call cerebro.plot() during profiling

# 3. Use preload
cerebro = bt.Cerebro()
cerebro.run(preload=True)

# 4. Limit data in memory
data.qbuffer(1000)

# 5. Use runonce for indicators
cerebro.run(runonce=True)
```

### Hot Path Optimizations

```python
class OptimizedStrategy(bt.Strategy):
    """Strategy with optimized hot path."""

    def __init__(self):
        # Cache attribute lookups
        self._data_close = self.data.close
        self._data_high = self.data.high
        self._data_low = self.data.low
        self._sma = self.sma

        # Cache calculations
        self.atr = bt.indicators.ATR(period=14)
        self.upper_band = self._data_close + self.atr * 2
        self.lower_band = self._data_close - self.atr * 2

    def next(self):
        # Use cached references
        close = self._data_close[0]
        sma = self._sma[0]

        # Avoid repeated attribute access
        if close > sma:
            # Direct attribute access instead of len()
            if self.data._len > 20:  # Not len(self.data)
                self.buy()
```

### Indicator Optimization

```python
# ❌ SLOW: Calculate indicator inside next()
def next(self):
    sma = bt.indicators.SMA(self.data.close, period=20)
    if self.data.close[0] > sma[0]:
        self.buy()

# ✅ FAST: Calculate in __init__
def __init__(self):
    self.sma = bt.indicators.SMA(period=20)

def next(self):
    if self.data.close[0] > self.sma[0]:
        self.buy()
```

### Batch Processing

```python
# For large optimizations, use optstrategy
cerebro = bt.Cerebro()
cerebro.optstrategy(
    MyStrategy,
    period=[10, 20, 30, 50],
    dev_mult=[1.5, 2.0, 2.5]
)

# Parallel execution
results = cerebro.run(maxcpu=4)
```

## Complete Profiling Example

```python
#!/usr/bin/env python
"""Complete profiling example for Backtrader strategies."""

import cProfile
import pstats
import time
import tracemalloc
import backtrader as bt

class ProfilingStrategy(bt.Strategy):
    """Example strategy with built-in profiling."""

    params = (
        ('period', 20),
        ('verbose', True),
    )

    def __init__(self):
        # Create indicators
        self.sma = bt.indicators.SMA(period=self.p.period)
        self.rsi = bt.indicators.RSI(period=14)

        # Timing
        self.next_times = []
        self.next_count = 0

    def next(self):
        start = time.perf_counter()

        # Strategy logic
        if self.data.close[0] > self.sma[0] and self.rsi[0] < 70:
            if not self.position:
                self.buy()

        elif self.data.close[0] < self.sma[0] or self.rsi[0] > 30:
            if self.position:
                self.sell()

        # Track timing
        elapsed = time.perf_counter() - start
        self.next_times.append(elapsed)
        self.next_count += 1

    def stop(self):
        if self.p.verbose and self.next_times:
            total = sum(self.next_times)
            avg = total / len(self.next_times)
            print(f"\n{self.__class__.__name__} Statistics:")
            print(f"  Total next() calls: {self.next_count}")
            print(f"  Total time in next(): {total:.4f}s")
            print(f"  Avg time per next(): {avg*1000:.4f}ms")
            print(f"  Max time: {max(self.next_times)*1000:.4f}ms")

def run_profiled_backtest(data_file='data.csv'):
    """Run backtest with full profiling."""

    # Memory profiling
    tracemalloc.start()

    # CPU profiling
    profiler = cProfile.Profile()
    profiler.enable()

    # Setup cerebro
    cerebro = bt.Cerebro()
    cerebro.addstrategy(ProfilingStrategy, period=20, verbose=True)
    data = bt.feeds.CSVGeneric(dataname=data_file)
    cerebro.adddata(data)

    # Run backtest
    start_time = time.time()
    results = cerebro.run()
    total_time = time.time() - start_time

    profiler.disable()

    # Memory results
    current, peak = tracemalloc.get_traced_memory()
    print(f"\nMemory Usage:")
    print(f"  Current: {current / 10**6:.2f} MB")
    print(f"  Peak: {peak / 10**6:.2f} MB")

    # CPU results
    stats = pstats.Stats(profiler)
    stats.sort_stats('cumulative')
    stats.strip_dirs()
    print(f"\nTop 20 Functions by Cumulative Time:")
    stats.print_stats(20)

    # Overall stats
    print(f"\nOverall Performance:")
    print(f"  Total time: {total_time:.2f}s")
    print(f"  Bars processed: {len(data)}")
    print(f"  Bars per second: {len(data)/total_time:.0f}")

    return results

if __name__ == '__main__':
    run_profiled_backtest()
```

## Performance Analysis Checklist

- [ ] Profile with cProfile to identify hot functions
- [ ] Use line_profiler for detailed code analysis
- [ ] Check memory usage with memory_profiler
- [ ] Establish baseline metrics (bars/sec, memory)
- [ ] Test with different data sizes
- [ ] Profile indicator calculations separately
- [ ] Check for unnecessary attribute lookups
- [ ] Verify data loading time vs calculation time
- [ ] Test parallel execution for optimizations
- [ ] Document performance improvements

## Related Documentation

- [Performance Optimization Guide](performance-optimization.md) - Optimization techniques
- [TS Mode Guide](ts-mode.md) - Time series optimization
- [CS Mode Guide](cs-mode.md) - Cross-section optimization
- [Cerebro API](../api_reference/cerebro.md) - Engine configuration options
