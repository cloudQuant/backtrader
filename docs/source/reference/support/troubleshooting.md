# Troubleshooting Guide

This comprehensive guide helps you diagnose and resolve common issues when using Backtrader for backtesting and live trading.

## Table of Contents

- [Error Diagnosis Techniques](#error-diagnosis-techniques)
- [Strategy Debugging](#strategy-debugging)
- [Data Feed Issues](#data-feed-issues)
- [Order Execution Problems](#order-execution-problems)
- [Performance Bottlenecks](#performance-bottlenecks)
- [Platform-Specific Issues](#platform-specific-issues)
- [Memory Leaks and Resource Management](#memory-leaks-and-resource-management)
- [Common Error Patterns](#common-error-patterns)
- [Getting Help Resources](#getting-help-resources)
- [Issue Reporting Template](#issue-reporting-template)

---
## Error Diagnosis Techniques

### Enable Verbose Logging

Backtrader uses Python's logging system. Enable detailed logging to diagnose issues:

```python
import logging
import backtrader as bt

# Set up logging

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Or use cerebro's logging

cerebro = bt.Cerebro()

# Enable cerebro debug output

cerebro.run(stdstats=False)  # Disable default observers for cleaner output

```

### Strategy State Inspection

Add debug output to understand strategy execution flow:

```python
class DebugStrategy(bt.Strategy):
    def __init__(self):
        self.debug_mode = True  # Toggle debug output

    def log(self, txt, dt=None):
        if self.debug_mode:
            dt = dt or self.datas[0].datetime.date(0)
            print(f'{dt.isoformat()} {txt}')

    def prenext(self):
        self.log(f'Prenext - Bar: {len(self)} - Minperiod not reached')

    def nextstart(self):
        self.log(f'Nextstart - First bar with valid data - len={len(self)}')

    def next(self):
        self.log(f'Next - Close: {self.data.close[0]:.2f} - Position: {self.position.size}')

```

### Line/Indicator Inspection

Inspect indicator values to diagnose calculation issues:

```python
class IndicatorInspectionStrategy(bt.Strategy):
    def __init__(self):
        self.sma = bt.indicators.SMA(period=20)
        self.rsi = bt.indicators.RSI(period=14)

    def next(self):

# Print indicator values
        if len(self) % 10 == 0:  # Every 10 bars
            print(f"Bar {len(self)}:")
            print(f"  Price: {self.data.close[0]:.2f}")
            print(f"  SMA[0]: {self.sma[0]:.2f}")
            print(f"  SMA[-1]: {self.sma[-1]:.2f}")
            print(f"  RSI[0]: {self.rsi[0]:.2f}")
            print(f"  SMA minperiod: {self.sma._minperiod}")
            print(f"  SMA size: {len(self.sma)}")

```

### Cerebro State Inspection

Inspect cerebro configuration before running:

```python
cerebro = bt.Cerebro()

# Add your strategy, data, etc.

# Print configuration

print(f"Strategies: {cerebro.strats}")
print(f"Data feeds: {len(cerebro.datas)}")
print(f"Analyzers: {len(cerebro.analyzers)}")
print(f"Observers: {len(cerebro.observers)}")
print(f"Broker cash: {cerebro.broker.get_cash()}")
print(f"Broker commission: {cerebro.broker.getcommission()}")

```

---
## Strategy Debugging

### Using pdb for Interactive Debugging

#### Breakpoint in Strategy Methods

```python
import pdb

class DebuggableStrategy(bt.Strategy):
    def next(self):

# Set breakpoint conditionally
        if len(self) == 50:  # At specific bar
            pdb.set_trace()

# Your strategy logic
        if self.data.close[0] > self.sma[0]:
            self.buy()

```

#### Debugging Indicator Values

```python
class DebugStrategy(bt.Strategy):
    def __init__(self):
        self.sma_fast = bt.indicators.SMA(period=10)
        self.sma_slow = bt.indicators.SMA(period=30)

    def next(self):

# Check if indicators have valid values
        if len(self.sma_fast) < self.sma_fast._minperiod:
            print(f"Fast SMA indicators not ready: {len(self.sma_fast)}/{self.sma_fast._minperiod}")
            return

# Debug crossover logic
        cross = self.sma_fast[0] - self.sma_slow[0]
        cross_prev = self.sma_fast[-1] - self.sma_slow[-1]

        print(f"Cross diff: {cross:.4f}, Prev: {cross_prev:.4f}")

        if cross > 0 and cross_prev <= 0:
            print(f"GOLDEN CROSS at bar {len(self)}")

```

### Common Strategy Issues

#### Issue: Strategy Not Executing

- *Problem**: `next()` method never called or called fewer times than expected.

- *Diagnostic Steps**:

1. Check data feed length:

```python
data = bt.feeds.GenericCSVData(dataname='data.csv')
print(f"Data bars loaded: {len(data)}")

```

1. Verify minimum period is satisfied:

```python
class MinPeriodStrategy(bt.Strategy):
    def __init__(self):
        print(f"Strategy minperiod: {self._minperiod}")

    def prenext(self):
        print(f"Prenext called - current len: {len(self)}, needed: {self._minperiod}")

    def nextstart(self):
        print(f"First valid bar - len: {len(self)}")

```

- *Solutions**:
- Ensure data has enough bars for all indicators
- Check `preload` and `runonce` settings
- Verify data timeframe alignment

#### Issue: Strategy Trading on First Bar

- *Problem**: Strategy executes immediately without waiting for indicators.

- *Solution**: Implement proper minimum period checking:

```python
class SafeStrategy(bt.Strategy):
    def next(self):

# Don't trade if indicators aren't ready
        if len(self) < max(self.sma._minperiod, self.rsi._minperiod):
            return

# Normal trading logic

# ...

```

#### Issue: Multiple Orders Executing Same Bar

- *Problem**: Strategy opens multiple positions when only one is intended.

- *Diagnosis**:

```python
class OrderTrackingStrategy(bt.Strategy):
    def __init__(self):
        self.order = None

    def next(self):
        if self.order:

# Previous order still pending
            return

# Place new order
        self.order = self.buy()

    def notify_order(self, order):
        if order.status in [order.Completed, order.Cancelled, order.Rejected]:
            self.order = None

```

### Logging Best Practices

```python
import logging
from datetime import datetime

class LoggingStrategy(bt.Strategy):
    params = (
        ('log_level', logging.INFO),
    )

    def __init__(self):
        self.logger = logging.getLogger(f'{self.__class__.__name__}')
        self.logger.setLevel(self.params.log_level)

# Log indicator setup
        for attr in dir(self):
            obj = getattr(self, attr)
            if isinstance(obj, bt.Indicator):
                self.logger.info(f'Initialized {attr}: minperiod={obj._minperiod}')

    def next(self):
        if len(self) % 100 == 0:  # Log every 100 bars
            self.logger.info(
                f'Bar {len(self)} | '

                f'Price: {self.data.close[0]:.2f} | '

                f'Position: {self.position.size} | '

                f'Cash: {self.broker.get_cash():.2f}'
            )

    def notify_order(self, order):
        self.logger.info(
            f'Order {order.ref} | '

            f'Status: {order.getstatusname()} | '

            f'Type: {order.ordtypename()} | '

            f'Size: {order.created.size} | '

            f'Price: {order.created.price:.2f}'
        )

```

---
## Data Feed Issues

### Missing Bars

#### Problem: Data Gaps in Time Series

- *Diagnosis**:

```python

# Check for gaps

class GapDetectionStrategy(bt.Strategy):
    def next(self):
        if len(self) > 1:
            current_time = self.data.datetime.datetime(0)
            prev_time = self.data.datetime.datetime(-1)

            expected_delta = bt.timedelta(days=1)  # Adjust for your timeframe
            actual_delta = current_time - prev_time

            if actual_delta > expected_delta *1.5:
                print(f"Gap detected: {prev_time} -> {current_time}")

```

- *Solutions**:

1. Use `fillsql` argument for SQL data feeds
2. Pre-fill gaps in pandas:

```python
import pandas as pd

# Load data

df = pd.read_csv('data.csv', parse_dates=['datetime'], index_col='datetime')

# Create complete date range

complete_range = pd.date_range(start=df.index.min(), end=df.index.max(), freq='D')

# Reindex to fill gaps

df = df.reindex(complete_range)

# Forward fill missing values

df = df.fillna(method='ffill')

data = bt.feeds.PandasData(dataname=df)

```

### Timezone Problems

#### Problem: Incorrect Time Alignment

- *Diagnosis**:

```python

# Check timezone information

class TimezoneCheckStrategy(bt.Strategy):
    def next(self):
        if len(self) <= 3:
            print(f"Bar {len(self)}: {self.data.datetime.datetime(0)}")
            print(f"  Timezone: {self.data.datetime._tz}")

```

- *Solutions**:

1. Explicitly set timezone:

```python
import pytz

data = bt.feeds.PandasData(
    dataname=df,
    tz=pytz.timezone('US/Eastern')  # Set your timezone

)

```

1. Normalize timezone before loading:

```python
df.index = df.index.tz_localize('UTC').tz_convert('US/Eastern')

```

1. Use `tzinput` parameter:

```python
data = bt.feeds.YahooFinanceData(
    dataname='AAPL',
    tzinput='US/Eastern',
    fromdate=datetime(2020, 1, 1),
    todate=datetime(2023, 12, 31)
)

```

### Data Validation

Before running strategy, validate data:

```python
def validate_data(data):
    """Check for common data issues."""
    print(f"Data validation for {data.dataname}")

# Check length
    print(f"  Total bars: {len(data)}")

# Check for NaN values
    data_array = data.array  # Get numpy array
    nan_count = np.isnan(data_array).sum()
    print(f"  NaN values: {nan_count}")

# Check for negative values in price data
    if hasattr(data, 'close'):
        negative_prices = (data.array < 0).sum()
        print(f"  Negative prices: {negative_prices}")

# Check date range
    if len(data) > 0:
        print(f"  Start: {data.datetime.date(0)}")
        print(f"  End: {data.datetime.date(-1)}")

    return nan_count == 0 and negative_prices == 0

# Use before adding to cerebro

if validate_data(data):
    cerebro.adddata(data)
else:
    print("Data validation failed!")

```

### Pandas Data Issues

#### Problem: Wrong Column Mapping

- *Diagnosis**:

```python

# Verify pandas data structure

print(df.head())
print(df.columns)
print(df.dtypes)

```

- *Solution**: Use correct data feed or specify column mapping:

```python

# Option 1: Rename columns to match backtrader conventions

df.columns = ['datetime', 'open', 'high', 'low', 'close', 'volume']
df.set_index('datetime', inplace=True)

# Option 2: Create custom data feed with explicit mapping

class CustomPandasData(bt.feeds.PandasData):
    params = (
        ('datetime', None),
        ('open', 'Open'),
        ('high', 'High'),
        ('low', 'Low'),
        ('close', 'Close'),
        ('volume', 'Volume'),
        ('openinterest', None),
    )

data = CustomPandasData(dataname=df)

```

### CSV Data Loading Issues

#### Problem: Wrong Date Format

- *Diagnosis**:

```python

# Test date parsing

from datetime import datetime
test_date = datetime.strptime('2020-01-15', '%Y-%m-%d')
print(test_date)  # Should print: 2020-01-15 00:00:00

```

- *Solution**: Specify correct format:

```python
data = bt.feeds.GenericCSVData(
    dataname='data.csv',
    datetime=0,
    open=1,
    high=2,
    low=3,
    close=4,
    volume=5,
    openinterest=-1,
    dtformat='%Y-%m-%d',  # Adjust to match your CSV format
    tmformat='%H:%M:%S',   # Add if time column exists
    timeframe=bt.TimeFrame.Days,
    compression=1
)

```

### Multiple Data Feed Issues

#### Problem: Synchronization Issues

- *Diagnosis**:

```python
class MultiDataCheckStrategy(bt.Strategy):
    def next(self):
        print(f"Bar {len(self)}")
        for i, data in enumerate(self.datas):
            print(f"  Data {i}: {data.datetime.date(0)} - Close: {data.close[0]:.2f}")

```

- *Solution**: Use same timeframe and compression for all feeds, or use `resampledata`:

```python

# Load data

data1 = bt.feeds.PandasData(dataname=df_daily)
data2 = bt.feeds.PandasData(dataname=df_hourly)

# Resample to same timeframe

cerebro.resampledata(data2, timeframe=bt.TimeFrame.Days, compression=1)
cerebro.adddata(data1)

```

---
## Order Execution Problems

### Rejected Orders

#### Problem: Orders Rejected Due to Insufficient Funds

- *Diagnosis**:

```python
class CashTrackingStrategy(bt.Strategy):
    def next(self):
        available_cash = self.broker.get_cash()
        portfolio_value = self.broker.getvalue()
        print(f"Cash: {available_cash:.2f} | Portfolio: {portfolio_value:.2f}")

    def notify_order(self, order):
        if order.status == order.Rejected:
            print(f"Order REJECTED - Size: {order.created.size}")
            print(f"  Required: {order.created.price *order.created.size*1.001:.2f}")
            print(f"  Available: {self.broker.get_cash():.2f}")

```

- *Solutions**:

1. Calculate position size based on available cash:

```python
def next(self):
    if not self.position:
        available_cash = self.broker.get_cash()
        price = self.data.close[0]

# Calculate size considering commission
        commission_info = self.broker.getcommissioninfo(self.data)
        size = commission_info.getsize(available_cash *0.95, price)

        if size > 0:
            self.buy(size=size)

```

1. Use `order_target_percent`:

```python

# Target 50% of portfolio

self.order_target_percent(target=0.5)

```

#### Problem: Invalid Order Price

- *Diagnosis**:

```python
class OrderValidationStrategy(bt.Strategy):
    def next(self):

# For limit orders, check price validity
        if self.data.close[0] > self.data.high[0]:
            print(f"Warning: Close > High at bar {len(self)}")

        if self.data.close[0] < self.data.low[0]:
            print(f"Warning: Close < Low at bar {len(self)}")

```

- *Solution**: Use price validation:

```python
def next(self):

# Validate price before placing order
    limit_price = self.data.close[0] *0.99  # 1% below close

# Ensure price is within daily range
    low = self.data.low[0]
    high = self.data.high[0]

    limit_price = max(min(limit_price, high), low)

    self.buy(price=limit_price, exectype=bt.Order.Limit)

```

### Partial Fills

#### Problem: Order Not Fully Executed

- *Diagnosis**:

```python
class FillTrackingStrategy(bt.Strategy):
    def notify_order(self, order):
        if order.status == order.Partial:
            print(f"Partial fill: {order.executed.size}/{order.created.size}")
        elif order.status == order.Completed:
            print(f"Completed: {order.executed.size} at {order.executed.price:.2f}")

```

- *Solutions**:

1. Use All-or-None orders:

```python
self.buy(exectype=bt.Order.Limit, price=limit_price, valid=bt.Order.ValidAllOrNone)

```

1. Handle partial fills:

```python
class PartialFillStrategy(bt.Strategy):
    def __init__(self):
        self.target_size = 100
        self.filled_size = 0

    def next(self):
        if self.filled_size < self.target_size:
            remaining = self.target_size - self.filled_size
            self.buy(size=remaining)

    def notify_order(self, order):
        if order.status == order.Completed:
            self.filled_size += order.executed.size

```

### Order Status Tracking

```python
class OrderStatusStrategy(bt.Strategy):
    def notify_order(self, order):
        date = self.data.datetime.date(0)

        if order.status in [order.Submitted, order.Accepted]:
            print(f'{date} Order {order.ref} - Status: {order.getstatusname()}')

        elif order.status in [order.Completed]:
            print(f'{date} Order {order.ref} - Completed')
            print(f'  Type: {order.ordtypename()}')
            print(f'  Size: {order.executed.size}')
            print(f'  Price: {order.executed.price:.2f}')
            print(f'  Commission: {order.executed.comm:.2f}')

        elif order.status == order.Canceled:
            print(f'{date} Order {order.ref} - Canceled')

        elif order.status == order.Rejected:
            print(f'{date} Order {order.ref} - REJECTED')
            print(f'  Reason: Check margin/cash')

        elif order.status == order.Margin:
            print(f'{date} Order {order.ref} - Margin Call')

        elif order.status == order.Expired:
            print(f'{date} Order {order.ref} - Expired')

```

### Commission Calculation Issues

#### Problem: Incorrect Commission Charged

- *Diagnosis**:

```python
cerebro.addanalyzer(bt.analyzers.Transactions, _name='txn')
results = cerebro.run()

transactions = results[0].analyzers.txn.get_analysis()
for date, txn_list in transactions.items():
    for txn in txn_list:
        print(f"{date}: {txn[0]:.2f} @ {txn[1]:.2f}, Comm: {txn[4]:.4f}")

```

- *Solution**: Configure commission correctly:

```python

# Percentage commission

cerebro.broker.setcommission(commission=0.001)  # 0.1%

# Fixed per share commission

cerebro.broker.setcommission(commission=0.01, commtype=bt.CommInfoBase.COMM_PERC)

# Fixed per trade commission

class FixedCommInfo(bt.CommInfoBase):
    params = (
        ('commission', 5.0),  # $5 per trade
        ('stocklike', True),
        ('commtype', bt.CommInfoBase.COMM_FIXED),
    )

cerebro.broker.addcommissioninfo(FixedCommInfo())

```

### Slippage Simulation

```python

# Add slippage to simulate realistic execution

cerebro.broker.set_slippage_perc(0.001)  # 0.1% slippage

# Or

cerebro.broker.set_slippage_fixed(0.01)  # Fixed slippage

```

---
## Performance Bottlenecks

### Profiling Backtest Execution

#### Using cProfile

```python
import cProfile
import pstats
from io import StringIO

# Profile the backtest

pr = cProfile.Profile()
pr.enable()

results = cerebro.run()

pr.disable()

# Print statistics

s = StringIO()
ps = pstats.Stats(pr, stream=s).sort_stats('cumulative')
ps.print_stats(20)  # Top 20 functions

print(s.getvalue())

```

#### Using line_profiler

```python

# Install: pip install line_profiler

# Add @profile decorator to strategy methods

@profile
def next(self):

# Your strategy logic
    pass

# Run with: kernprof -l -v your_script.py

```

### Slow Optimization Runs

#### Problem: Parameter Optimization Takes Too Long

- *Diagnosis**:

```python
import time

start = time.time()
results = cerebro.run(maxcpus=4)
end = time.time()

print(f"Optimization took {end - start:.2f} seconds")
print(f"Total combinations: {len(results)}")

```

- *Solutions**:

1. Use `runonce=True` (default for optimization):

```python

# Already default, but ensure it's enabled

cerebro.run(runonce=True)

```

1. Limit parameter combinations:

```python

# Instead of testing 100 values

cerebro.optstrategy(MyStrategy, period=range(5, 105, 1))

# Use coarser steps first

cerebro.optstrategy(MyStrategy, period=range(5, 105, 10))

```

1. Use preload and exactbars:

```python
cerebro = bt.Cerebro(
    preload=True,      # Load all data at once
    runonce=True,      # Use vectorized mode
    exactbars=1,       # Memory optimization
    maxcpus=4          # Use multiple CPUs for optimization

)

```

### Indicator Performance

#### Problem: Custom Indicators Are Slow

- *Diagnosis**:

```python
import time

class TimedIndicator(bt.Indicator):
    def __init__(self):
        start = time.time()

# Indicator calculation
        end = time.time()
        print(f"Indicator init took {end - start:.4f} seconds")

```

- *Solutions**:

1. Implement `once()` method for vectorized calculation:

```python
class FastSMA(bt.Indicator):
    lines = ('sma',)
    params = (('period', 20),)

    def __init__(self):
        pass  # Defer calculation

    def once(self, start, end):

# Vectorized calculation using NumPy
        src = self.data.array
        dst = self.lines.sma.array

        for i in range(start, end):
            if i >= self.p.period - 1:
                dst[i] = src[i-self.p.period+1:i+1].mean()
            else:
                dst[i] = float('nan')

```

1. Use Cython for critical calculations:

```python

# In utils/ts_cal_value/ directory

# Use pre-compiled Cython modules for 10-100x speedup

```

### Data Loading Performance

#### Problem: Loading Large CSV Files Is Slow

- *Solution**: Use optimized data formats:

```python

# Option 1: Use pandas with efficient reading

import pandas as pd

# For very large files, read in chunks and save as parquet

chunks = pd.read_csv('large_file.csv', chunksize=100000)
df = pd.concat(chunks)
df.to_parquet('data.parquet')  # Much faster to load later

# Load parquet

df = pd.read_parquet('data.parquet')
data = bt.feeds.PandasData(dataname=df)

```

```python

# Option 2: Use preloading with exactbars

cerebro = bt.Cerebro(preload=True, exactbars=1)

# exactbars options:

# 1: Keep minimum bars (lowest memory)

# 2: Keep full dataset (default)

```

### Memory Issues

#### Problem: Out of Memory Errors

- *Diagnosis**:

```python
import psutil
import os

process = psutil.Process(os.getpid())
print(f"Memory usage: {process.memory_info().rss / 1024 / 1024:.2f} MB")

```

- *Solutions**:

1. Use `qbuffer` to limit memory:

```python

# In strategy or indicator

self.data.qbuffer(size=1000)  # Keep only last 1000 bars

```

1. Use `exactbars` in cerebro:

```python
cerebro = bt.Cerebro(exactbars=1)  # Minimal memory usage

```

1. Process data in batches:

```python

# Split large backtest into smaller chunks

def run_chunked_backtest(data, chunk_size=1000):
    results = []
    for i in range(0, len(data), chunk_size):
        chunk = data[i:i+chunk_size]
        cerebro = bt.Cerebro()
        cerebro.adddata(chunk)
        cerebro.addstrategy(MyStrategy)
        chunk_result = cerebro.run()
        results.append(chunk_result)
    return results

```

### Visualization Performance

#### Problem: Plotting Large Datasets Is Slow

- *Solutions**:

1. Use Plotly for large datasets (handles 100k+ points):

```python
cerebro.plot(backend='plotly', style='candle')

```

1. Downsample data for visualization:

```python
def downsample(df, rule='1D'):
    """Downsample OHLCV data."""
    return df.resample(rule).agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum'
    })

# Load full data for backtest, downsampled for plotting

df_full = pd.read_csv('data.csv')
df_plot = downsample(df_full, '1W')  # Weekly for plotting

```

1. Disable plotting for optimization:

```python

# When running optimization

results = cerebro.run()

# Only plot best result

best_strategy = results[0]
cerebro.plot(strat=best_strategy)

```

---
## Platform-Specific Issues

### Windows-Specific Issues

#### Issue: Multiprocessing Fails on Windows

- *Problem**: `cerebro.run(maxcpus=4)` fails on Windows.

- *Cause**: Windows doesn't support fork-based multiprocessing.

- *Solution**:

```python

# On Windows, ensure code is in if __name__ == '__main__' block

if __name__ == '__main__':
    cerebro = bt.Cerebro()
    cerebro.addstrategy(MyStrategy)
    cerebro.adddata(data)

# Use spawn instead of fork
    import multiprocessing
    multiprocessing.set_start_method('spawn')

    results = cerebro.run(maxcpus=4)

```

#### Issue: Path Handling Problems

- *Problem**: Data file paths not found on Windows.

- *Solution**:

```python
from pathlib import Path

# Use Path for cross-platform compatibility

data_path = Path('data') / 'stock_data.csv'

data = bt.feeds.GenericCSVData(
    dataname=str(data_path),  # Convert to string

# ...

)

```

#### Issue: Time Limit Exceeded

- *Problem**: Long-running backtests timeout on Windows.

- *Solution**: Increase timeout or use single process:

```python

# On Windows, optimization with multiprocessing can be slower

# Try using single process first

results = cerebro.run(maxcpus=1)

# Or use multiprocessing with timeout

import multiprocessing

pool = multiprocessing.Pool(processes=2, timeout=300)

```

### macOS-Specific Issues

#### Issue: Plotting Window Doesn't Close

- *Problem**: Plot window stays open after script completes.

- *Solution**:

```python

# For matplotlib backend

import matplotlib.pyplot as plt

cerebro.plot()
plt.show(block=True)  # or plt.show(block=False)

# For interactive use

plt.ion()
cerebro.plot()
plt.ioff()

```

#### Issue: High DPI Display Issues

- *Problem**: Plots look blurry on Retina displays.

- *Solution**:

```python

# Set matplotlib to use high DPI

%matplotlib inline
%config InlineBackend.figure_format = 'retina'

import matplotlib.pyplot as plt
plt.rcParams['figure.dpi'] = 144

```

### Linux-Specific Issues

#### Issue: Missing Dependencies

- *Problem**: Import errors for matplotlib or other packages.

- *Solution**:

```bash

# Install system dependencies

sudo apt-get install python3-dev
sudo apt-get install libfreetype6-dev
sudo apt-get install pkg-config

# Then reinstall Python packages

pip install --upgrade matplotlib pandas numpy

```

#### Issue: File Permission Errors

- *Problem**: Cannot write to data directories.

- *Solution**:

```python
import os

# Ensure directory exists and is writable

data_dir = Path('data')
data_dir.mkdir(exist_ok=True)

# Check permissions

if not os.access(data_dir, os.W_OK):
    print(f"Warning: No write permission for {data_dir}")

```

---
## Memory Leaks and Resource Management

### Detecting Memory Leaks

#### Using tracemalloc

```python
import tracemalloc

tracemalloc.start()

# Run backtest

snapshot1 = tracemalloc.take_snapshot()
results = cerebro.run()
snapshot2 = tracemalloc.take_snapshot()

# Compare snapshots

top_stats = snapshot2.compare_to(snapshot1, 'lineno')
for stat in top_stats[:10]:
    print(stat)

```

#### Using memory_profiler

```python

# Install: pip install memory_profiler

# Run with: python -m memory_profiler your_script.py

@profile
def run_backtest():
    cerebro = bt.Cerebro()

# ... setup ...
    results = cerebro.run()
    return results

```

### Common Memory Leak Sources

#### Issue: Circular References in Strategies

- *Problem**: Strategy holds references to objects that hold references back.

- *Solution**: Use weak references:

```python
import weakref

class CleanStrategy(bt.Strategy):
    def __init__(self):

# Use weakref to avoid circular references
        self._data_ref = weakref.ref(self.data)

    def stop(self):

# Clean up references when done
        self._data_ref = None

```

#### Issue: Large Indicator History

- *Problem**: Indicators keep all historical values.

- *Solution**:

```python

# Use qbuffer to limit history

class MemoryEfficientIndicator(bt.Indicator):
    def __init__(self):

# Keep only last 1000 values
        self.lines.buffer.qbuffer(size=1000)

```

### Resource Cleanup

```python
class CleanStrategy(bt.Strategy):
    def start(self):
        """Called when strategy starts."""
        self.temp_data = []
        self.temp_files = []

    def stop(self):
        """Called when strategy stops. Clean up resources."""

# Close any open files
        for f in self.temp_files:
            try:
                f.close()
            except:
                pass

# Clear large data structures
        self.temp_data.clear()

    def prenext(self):

# For long backtests, periodic cleanup
        if len(self) % 1000 == 0:

# Trigger garbage collection
            import gc
            gc.collect()

```

---
## Common Error Patterns

### IndexError

#### Pattern: Index Out of Range

```python

# Problem: Accessing data before enough bars exist

class BugStrategy(bt.Strategy):
    def next(self):

# This will fail on first bar
        avg = (self.data.close[-1] + self.data.close[0]) / 2

# Solution: Check length

class FixedStrategy(bt.Strategy):
    def next(self):
        if len(self) < 2:
            return
        avg = (self.data.close[-1] + self.data.close[0]) / 2

```

### AttributeError

#### Pattern: Attribute Doesn't Exist

```python

# Problem: Accessing indicator before it's defined

class BugStrategy(bt.Strategy):
    def next(self):
        value = self.sma[0]  # sma not defined

# Solution: Define in __init__

class FixedStrategy(bt.Strategy):
    def __init__(self):
        self.sma = bt.indicators.SMA(period=20)

    def next(self):
        value = self.sma[0]

```

### TypeError

#### Pattern: Wrong Data Type

```python

# Problem: Passing string where number expected

cerebro.broker.setcash("100000")  # Wrong!

# Solution: Pass number

cerebro.broker.setcash(100000.0)

```

### ValueError

#### Pattern: Invalid Parameter Values

```python

# Problem: Negative period

sma = bt.indicators.SMA(period=-10)  # Wrong!

# Solution: Validate parameters

period = max(1, int(user_input_period))
sma = bt.indicators.SMA(period=period)

```

---
## Getting Help Resources

### Official Resources

1. **Documentation**: <https://www.backtrader.com/docu/>
2. **Blog Posts**: <https://www.backtrader.com/blog/>
3. **GitHub Issues**: <https://github.com/cloudQuant/backtrader/issues>
4. **GitHub Discussions**: <https://github.com/cloudQuant/backtrader/discussions>

### Community Resources

1. **Stack Overflow**: Tag questions with `backtrader`
2. **Reddit**: r/algotrading
3. **Discord/Slack**: Various quant trading communities

### Debug Checklist

Before asking for help, verify:

- [ ] Using latest version of Backtrader
- [ ] Checked documentation for similar issues
- [ ] Searched existing GitHub issues
- [ ] Created minimal reproducible example
- [ ] Verified data quality (no NaN, correct dates)
- [ ] Checked parameter values are valid
- [ ] Tested with simple strategy first
- [ ] Enabled logging for more details
- [ ] Tried on different platforms if possible

### Self-Diagnosis Flow

```bash
Start
  |

  v
Does script run? --> No --> Syntax/Import error --> Check Python version and dependencies
  |

 Yes
  v
Does cerebro.run() work? --> No --> Data/Strategy error --> Check data format and strategy logic
  |

 Yes
  v
Are results as expected? --> No --> Logic error --> Add logging/debugging
  |

 Yes
  v
Is performance acceptable? --> No --> Optimization needed --> See Performance section
  |

 Yes
  v
Success!

```

---
## Issue Reporting Template

When reporting an issue, use this template:

### Bug Report

- *Title**: [Brief description of the issue]

- *Description**:

A clear and concise description of what the bug is.

- *Environment**:
- Backtrader version: `python -c "import backtrader; print(backtrader.__version__)"`
- Python version: `python --version`
- Operating System: [e.g., Windows 10, macOS 12, Ubuntu 20.04]
- Installation method: pip, conda, or from source

- *Steps to Reproduce**:
1. Minimal, complete, and verifiable code example:

```python
import backtrader as bt

# ... minimal code to reproduce the issue

```

1. Data file or description (sanitized if necessary)

- *Expected Behavior**:

What should happen?

- *Actual Behavior**:

What actually happens? Include error messages, stack traces, etc.

- *Screenshots/Logs**:

If applicable, add screenshots or logs to help explain the problem.

- *Additional Context**:
- Any other relevant information
- Workarounds tried
- Related issues or documentation

### Feature Request

- *Title**: [Brief feature description]

- *Problem Statement**:

What problem would this feature solve?

- *Proposed Solution**:

How would you like the feature to work?

- *Alternatives Considered**:

What other solutions have you considered?

- *Additional Context**:

Any other context, mockups, or examples?

---
## Quick Reference: Common Error Messages

| Error | Cause | Solution |

|-------|-------|----------|

| `IndexError: array index out of range` | Accessing data before enough bars | Check `len()` before accessing negative indices |

| `AttributeError: 'Lines_LineSeries_DataSeries' object has no attribute 'xxx'` | Wrong attribute name | Check line names in indicator/strategy definition |

| `KeyError: 'datetime'` | Missing datetime column in CSV | Verify CSV column mapping |

| `TypeError: 'float' object is not callable` | Accidentally overwrote method | Check for variable names matching method names |

| `RuntimeWarning: invalid value encountered in` | Division by zero or NaN values | Add checks for zero/NaN in calculations |

| `MemoryError` | Not enough memory | Use `exactbars`, `qbuffer`, or process in chunks |

| `AssertionError` | Failed assertion in code | Check assertion conditions, may be data issue |

---
For additional help, please refer to the main documentation or open an issue on GitHub.
