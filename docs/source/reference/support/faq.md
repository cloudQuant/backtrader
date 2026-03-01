# Frequently Asked Questions (FAQ)

This document addresses common questions, issues, and best practices when using Backtrader for quantitative trading and backtesting.

## Table of Contents

1. [Installation & Setup](#1-installation--setup)
2. [Data Feed Issues](#2-data-feed-issues)
3. [Performance Problems](#3-performance-problems)
4. [Live Trading Questions](#4-live-trading-questions)
5. [Error Messages & Solutions](#5-error-messages--solutions)
6. [Common Gotchas](#6-common-gotchas)
7. [Best Practices](#7-best-practices)

---

## 1. Installation & Setup

### Q: Why does Cython compilation fail on Windows?

**A:** Windows compilation may have minor warnings that can be safely ignored. The key is to use the correct command separator:

```bash
# Windows - use semicolons
cd backtrader; python -W ignore compile_cython_numba_files.py; cd ..; pip install -U .
```

If compilation completely fails, ensure you have:
- Microsoft Visual C++ Build Tools installed
- Python 3.11 or higher
- All required dependencies from `requirements.txt`

**Reference:** [Installation Guide](../opts/getting_started/installation.md)

### Q: Do I need to compile Cython files?

**A:** Cython compilation is recommended but not strictly required. The framework will work without it, but you'll miss out on 10-100x performance improvements for:
- Time series calculations (`ts` mode)
- Cross-section calculations (`cs` mode)
- Performance indicator calculations

For production backtesting, always compile with Cython.

### Q: Which Python version should I use?

**A:** Python 3.11 or higher is recommended. The framework is tested on Python 3.8-3.13, but 3.11+ offers the best performance and compatibility.

### Q: Can I use this framework without git?

**A:** Yes, you can download the repository as a ZIP file and extract it. However, using git makes it easier to update and track changes.

### Q: ImportError: No module named 'backtrader' after installation

**A:** This usually means the installation didn't complete successfully. Try:

```bash
# Reinstall with upgrade flag
pip install -U /path/to/backtrader

# Or if in the source directory
cd /path/to/backtrader
pip install -U .
```

---

## 2. Data Feed Issues

### Q: How do I handle missing data in my CSV file?

**A:** There are several approaches:

```python
# Option 1: Forward fill missing data
import pandas as pd
df = pd.read_csv('data.csv', parse_dates=['datetime'])
df = df.set_index('datetime').asfreq('1D').ffill()

# Option 2: Use PandasData with checks
data = bt.feeds.PandasData(dataname=df)

# Option 3: Custom data feed with preprocessing
class MyCSVData(bt.feeds.GenericCSVData):
    params = (
        ('nullvalue', 0.0),  # Replace NaN with 0
        ('fillvalue', 0.0),
    )
```

### Q: Why is my data feed not loading?

**A:** Common causes:
1. **Wrong datetime format**: Specify the correct format
   ```python
   data = bt.feeds.GenericCSVData(
       dataname='data.csv',
       dtformat='%Y-%m-%d %H:%M:%S',
   )
   ```

2. **Column mismatch**: Verify column indices match your CSV
   ```python
   data = bt.feeds.GenericCSVData(
       dataname='data.csv',
       datetime=0, open=1, high=2, low=3, close=4, volume=5,
   )
   ```

3. **File path issues**: Use absolute paths
   ```python
   import os
   path = os.path.abspath('data.csv')
   ```

### Q: How do I use multiple data feeds?

**A:** Add multiple feeds and access them by name:

```python
cerebro = bt.Cerebro()

# Add feeds with names
data1 = bt.feeds.PandasData(dataname=df1)
data2 = bt.feeds.PandasData(dataname=df2)
cerebro.adddata(data1, name='asset1')
cerebro.adddata(data2, name='asset2')

# In strategy, access by data name
class MyStrategy(bt.Strategy):
    def __init__(self):
        self.data1 = self.getdatabyname('asset1')
        self.data2 = self.getdatabyname('asset2')

    def next(self):
        if self.data1.close[0] > self.data2.close[0]:
            self.buy()
```

### Q: How do I resample data to a different timeframe?

**A:** Use `resampledata`:

```python
# Load 1-minute data
data = bt.feeds.PandasData(dataname=minute_df)

# Resample to hourly
cerebro.resampledata(
    data,
    timeframe=bt.TimeFrame.Minutes,
    compression=60,  # 60 minutes = 1 hour
)

# Keep original and resampled
cerebro.adddata(data, name='minute')
cerebro.resampledata(data, timeframe=bt.TimeFrame.Minutes, compression=60, name='hour')
```

### Q: Why are my indicators showing NaN values?

**A:** Indicators need a minimum number of bars (warmup period) before producing valid values:

```python
class MyStrategy(bt.Strategy):
    def __init__(self):
        self.sma = bt.indicators.SMA(period=20)

    def next(self):
        # Check if indicator has enough data
        if len(self.data) >= self.sma.period:
            # Now SMA has valid values
            print(f'SMA: {self.sma[0]}')
        else:
            print(f'Warming up... {len(self.data)}/{self.sma.period}')
```

**Reference:** [Data Feeds Guide](../opts/user_guide/data_feeds.md)

---

## 3. Performance Problems

### Q: Why is my backtest so slow?

**A:** Several factors affect performance:

**1. Not using Cython:**
```bash
# Compile for 10-100x speedup
cd backtrader && python -W ignore compile_cython_numba_files.py && cd .. && pip install -U .
```

**2. Using inefficient data access:**
```python
# SLOW - Repeated attribute access
for i in range(len(data)):
    close = data.close[0]  # Accesses property each time

# FAST - Cache reference
close_line = data.close
for i in range(len(data)):
    close = close_line[0]
```

**3. Too many indicators:**
```python
# Consider using only essential indicators
# Or use preloading with runonce()
cerebro.run(runonce=True)  # Much faster for large datasets
```

**4. Large datasets without limits:**
```python
# Use date range or numdos
data = bt.feeds.PandasData(
    dataname=df,
    fromdate=datetime(2023, 1, 1),
    todate=datetime(2023, 12, 31),
)
```

**5. Debug mode enabled:**
```python
# Ensure cerebro not in debug mode
cerebro = bt.Cerebro()  # Default is fastest
```

### Q: How can I speed up optimization?

**A:** Use parallel processing and reduce parameters:

```python
# Use multiprocessing
cerebro.optstrategy(
    MyStrategy,
    period=[5, 10, 20, 50],
    devfactor=[1.0, 2.0],
)
maxcpu = cerebro.run(maxcpu=4)  # Use 4 CPU cores
```

### Q: Memory usage is too high with large datasets

**A:** Implement these strategies:

```python
# 1. Use qbuffer to limit memory
cerebro.run(qbuffer=True)

# 2. Process in chunks
def run_backtest_chunks(start_date, end_date, chunk_days=30):
    results = []
    current = start_date
    while current < end_date:
        chunk_end = min(current + timedelta(days=chunk_days), end_date)
        data = load_data(current, chunk_end)
        # Run backtest for this chunk
        cerebro = bt.Cerebro()
        cerebro.adddata(data)
        result = cerebro.run()
        results.append(result)
        current = chunk_end
    return results

# 3. Use HDF5 with compression
import pandas as pd
df.to_hdf('data.h5', 'data', mode='w', complevel=9, complib='blosc')
data = bt.feeds.PandasData(dataname=pd.read_hdf('data.h5'))
```

**Reference:** [Performance Optimization Summary](../opts/performance_optimization_summary.md)

### Q: Why is the `dev` branch faster than `master`?

**A:** The `dev` branch includes:
- Metaclass removal (45% performance improvement)
- Optimized broker operations
- Cython-accelerated calculations
- Reduced redundant function calls

For production use, prefer the `dev` branch for better performance.

---

## 4. Live Trading Questions

### Q: CCXT connection errors - how to fix?

**A:** Common CCXT issues and solutions:

**1. Rate limit exceeded:**
```python
# Enable rate limiting
store = bt.stores.CCXTStore(
    exchange='binance',
    config={
        'apiKey': 'your_key',
        'secret': 'your_secret',
        'enableRateLimit': True,  # Essential
        'rateLimit': 1200,  # Requests per minute
    }
)
```

**2. Network timeout:**
```python
# Increase timeout and add retry
broker = store.getbroker(
    max_retries=3,
    retry_delay=1.0,
)
```

**3. Invalid API keys:**
```python
# Verify API keys have correct permissions
# Required: Read + Trade (no withdrawal needed)
```

**4. WebSocket fallback:**
```python
# Enable automatic fallback
data = store.getdata(
    dataname='BTC/USDT',
    use_websocket=True,
    # Falls back to REST if WS fails
)
```

**Reference:** [CCXT Live Trading Guide](../CCXT_LIVE_TRADING_GUIDE.md)

### Q: CTP login failures - what to check?

**A:** CTP (China Futures) login issues:

```python
# Common fixes:
store = bt.stores.CTPStore(
    user_id='your_id',
    password='your_password',
    broker_id='9999',  # Check broker ID
    td_address='sim.nowgateway.future.com.cn:10101',  # Check address
    md_address='sim.nowgateway.future.com.cn:10131',
    app_id='simnow_client',  # For SimNow
    auth_code='0000000000000000',  # For SimNow
    # Production uses different addresses
)

# Check:
# 1. Trading hours (CTP has specific market hours)
# 2. Network connectivity to CTP servers
# 3. User ID and password correctness
# 4. Broker ID validity
```

**Reference:** [CTP Data Feed Documentation](../backtrader/feeds/ctpdata.py)

### Q: How do I handle live data disconnections?

**A:** Implement reconnection logic:

```python
class RobustStrategy(bt.Strategy):
    def notify_data(self, data, status, *args, **kwargs):
        if status == data.DISCONNECTED:
            self.log(f'Data disconnected: {data._name}')
            # Implement alert logic
            # Could trigger reconnect or pause trading

    def next(self):
        # Check data freshness
        if hasattr(self.data, '_last_update'):
            age = datetime.now() - self.data._last_update
            if age > timedelta(minutes=5):
                self.log('WARNING: Stale data detected')
```

### Q: WebSocket vs REST for live trading?

**A:** Use WebSocket when possible:

```python
# WebSocket (Recommended)
data = store.getdata(
    dataname='BTC/USDT',
    use_websocket=True,  # Lower latency, less API usage
)

# REST Polling (Fallback)
data = store.getdata(
    dataname='BTC/USDT',
    # use_websocket=False (default)
)
```

**Comparison:**
| Feature | WebSocket | REST |
|---------|-----------|------|
| Latency | 10-50ms | 100-500ms |
| API Usage | Minimal | High |
| Complexity | Medium | Low |
| Reliability | Good | Excellent |

**Reference:** [WebSocket Guide](../WEBSOCKET_GUIDE.md)

---

## 5. Error Messages & Solutions

### Q: "KeyError: datetime" when loading CSV data

**A:** The datetime column isn't being parsed correctly:

```python
# Solution 1: Specify column
data = bt.feeds.GenericCSVData(
    dataname='data.csv',
    datetime=0,  # Column index
    dtformat='%Y-%m-%d %H:%M:%S',
)

# Solution 2: Use Pandas to preprocess
df = pd.read_csv('data.csv')
df['datetime'] = pd.to_datetime(df['datetime'])
data = bt.feeds.PandasData(dataname=df)
```

### Q: "IndexError: array index out of range"

**A:** Accessing data beyond available length:

```python
# WRONG
class MyStrategy(bt.Strategy):
    def next(self):
        ma = self.sma[-50]  # May not exist yet

# CORRECT
class MyStrategy(bt.Strategy):
    def next(self):
        if len(self.data) >= 50:
            ma = self.sma[-50]
```

### Q: "AttributeError: 'Strategy' object has no attribute 'position'"

**A:** Forgetting to call parent `__init__`:

```python
# WRONG
class MyStrategy(bt.Strategy):
    def __init__(self):
        # Missing super().__init__()
        self.sma = bt.indicators.SMA(period=20)

# CORRECT - Call super first!
class MyStrategy(bt.Strategy):
    def __init__(self):
        super().__init__()  # CRITICAL - sets up position, orders, etc.
        self.sma = bt.indicators.SMA(period=20)
```

### Q: "RuntimeError: live feed must use preloading=False and runonce=False"

**A:** Live feeds require specific settings:

```python
# This error is automatically handled
# Backtrader detects live feeds and adjusts
# But if you manually set:
cerebro = bt.Cerebro()
# Don't set:
# cerebro.run(preload=False, runonce=False)
# It's automatic for live feeds
```

### Q: "ZeroDivisionError" in custom indicators

**A:** Handle edge cases:

```python
class MyIndicator(bt.Indicator):
    lines = ('value',)

    def next(self):
        # WRONG
        self.lines.value[0] = self.data.close[0] / self.data.volume[0]

        # CORRECT
        vol = self.data.volume[0]
        if vol > 0:
            self.lines.value[0] = self.data.close[0] / vol
        else:
            self.lines.value[0] = 0.0
```

---

## 6. Common Gotchas

### Q: Why are my indicators not updating?

**A:** Common causes:

**1. Indicator not registered:**
```python
class MyStrategy(bt.Strategy):
    def __init__(self):
        super().__init__()  # Must call super!
        # Indicators auto-register after super().__init__()
        self.sma = bt.indicators.SMA(self.data, period=20)
```

**2. Missing data owner:**
```python
# WRONG - Indicator created outside strategy
sma = bt.indicators.SMA(period=20)  # No owner

# CORRECT - Created within strategy
class MyStrategy(bt.Strategy):
    def __init__(self):
        super().__init__()
        self.sma = bt.indicators.SMA(period=20)  # Strategy is owner
```

**3. Parameter access before initialization:**
```python
# WRONG - Accessing self.p before super().__init__()
class MyStrategy(bt.Strategy):
    def __init__(self):
        self.period = self.p.period  # ERROR!

# CORRECT
class MyStrategy(bt.Strategy):
    def __init__(self):
        super().__init__()  # Sets up self.p
        self.period = self.p.period  # Now it works
```

### Q: Why does my strategy miss the first bar?

**A:** Indicators need warmup period:

```python
class MyStrategy(bt.Strategy):
    def __init__(self):
        super().__init__()
        self.sma20 = bt.indicators.SMA(period=20)
        self.sma50 = bt.indicators.SMA(period=50)
        # Strategy won't trade until bar 50

    def start(self):
        # Override start() to reduce warmup
        # (Not recommended - indicators will be invalid)
        pass
```

**Solution:** Use `prenext()` to handle warmup:
```python
class MyStrategy(bt.Strategy):
    def prenext(self):
        # Called during warmup
        self.log(f'Warming up... {len(self.data)}')

    def next(self):
        # Called after warmup complete
        pass
```

### Q: Why are my order sizes incorrect?

**A:** Check broker settings and calculations:

```python
class MyStrategy(bt.Strategy):
    def next(self):
        # WRONG - Doesn't account for available cash
        self.buy(size=100)

        # CORRECT - Calculate position size
        cash = self.broker.getcash()
        price = self.data.close[0]
        size = int(cash * 0.95 / price)  # Use 95% of cash
        self.buy(size=size)
```

### Q: Plotting issues on different platforms

**A:** Platform-specific solutions:

**Linux (no display):**
```python
# Use Agg backend (no display)
import matplotlib
matplotlib.use('Agg')
import backtrader as bt

# Or save directly
cerebro.plot()[0][0].savefig('output.png')
```

**macOS (Python 3.11+):**
```bash
# May need: pip install pyqt5
export MPLBACKEND=Qt5Agg
```

**Large datasets:**
```python
# Use plotly for interactive charts
cerebro.plot(style='plotly', volume=False)  # Disable volume for speed
```

**Reference:** [Plotting Documentation](../plot/README.md)

---

## 7. Best Practices

### Q: How should I structure my backtesting project?

**A:** Recommended structure:

```
project/
├── data/              # Data files
├── strategies/        # Strategy definitions
│   ├── __init__.py
│   ├── base.py        # Base strategy class
│   └── my_strategy.py
├── indicators/        # Custom indicators
├── tests/             # Unit tests
├── configs/           # Configuration files
├── results/           # Backtest results
├── notebooks/         # Jupyter notebooks
└── main.py            # Entry point
```

### Q: How do I properly size positions?

**A:** Use risk-based position sizing:

```python
class RiskManagedStrategy(bt.Strategy):
    params = (
        ('risk_per_trade', 0.02),  # 2% risk per trade
        ('stop_distance_pct', 0.02),  # 2% stop loss
    )

    def calculate_position_size(self):
        account_value = self.broker.getvalue()
        risk_amount = account_value * self.p.risk_per_trade
        stop_distance = self.data.close[0] * self.p.stop_distance_pct
        position_size = risk_amount / stop_distance
        return int(position_size)
```

### Q: How do I validate my strategy?

**A:** Multi-step validation:

```python
# 1. In-sample test
train_data = load_data(start='2020-01-01', end='2022-12-31')
cerebro_train = bt.Cerebro()
cerebro_train.adddata(train_data)
results_train = cerebro_train.run()

# 2. Out-of-sample test
test_data = load_data(start='2023-01-01', end='2024-12-31')
cerebro_test = bt.Cerebro()
cerebro_test.adddata(test_data)
results_test = cerebro_test.run()

# 3. Walk-forward analysis
# (Split data into multiple train/test periods)

# 4. Monte Carlo simulation
# (Randomize order of trades)
```

### Q: How do I log effectively?

**A:** Use structured logging:

```python
import logging
from datetime import datetime

class LoggingStrategy(bt.Strategy):
    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)

    def log(self, txt, dt=None):
        dt = dt or self.data.datetime[0]
        if isinstance(dt, float):
            dt = datetime.fromtimestamp(dt)
        self.logger.info(f'{dt.isoformat()} {txt}')

    def next(self):
        if self.sma[0] > self.data.close[0]:
            self.log(f'SMA > Close: {self.sma[0]:.2f} > {self.data.close[0]:.2f}')
```

### Q: How do I handle commissions and slippage?

**A:** Configure broker properly:

```python
cerebro = bt.Cerebro()

# Set commission scheme
cerebro.broker.setcommission(
    commission=0.001,  # 0.1%
    mult=1,            # Multiplier
    margin=0.1,        # Margin requirement (10%)
    commtype=bt.CommInfoBase.COMM_PERC,  # Percentage-based
)

# Add slippage
cerebro.broker.set_slippage_perc(perc=0.0005)  # 0.05% slippage

# Or fixed per-share
cerebro.broker.setcommission(commission=0.001, commtype=bt.CommInfoBase.COMM_FIXED)
```

### Q: How do I export backtest results?

**A:** Multiple methods:

```python
# 1. Use analyzers
cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')

strat = cerebro.run()[0]
sharpe = strat.analyzers.sharpe.get_analysis()
drawdown = strat.analyzers.drawdown.get_analysis()
trades = strat.analyzers.trades.get_analysis()

# 2. Export to CSV
class CSVWriter(bt.Analyzer):
    def __init__(self):
        self.file = open('trades.csv', 'w')
        self.file.write('date,price,size,value\n')

    def notify_trade(self, trade):
        if trade.isclosed:
            self.file.write(f'{trade.dt},{trade.price},{trade.size},{trade.value}\n')

# 3. Save plot
fig = cerebro.plot()[0][0]
fig.savefig('backtest.png')
```

---

## Additional Resources

| Topic | Documentation |
|-------|---------------|
| Installation | [Installation Guide](../opts/getting_started/installation.md) |
| Quick Start | [Quick Start Guide](../opts/getting_started/quickstart.md) |
| Data Feeds | [Data Feeds Guide](../opts/user_guide/data_feeds.md) |
| Indicators | [Indicators Guide](../opts/user_guide/indicators.md) |
| Strategies | [Strategies Guide](../opts/user_guide/strategies.md) |
| CCXT Trading | [CCXT Live Trading Guide](../CCXT_LIVE_TRADING_GUIDE.md) |
| WebSocket | [WebSocket Guide](../WEBSOCKET_GUIDE.md) |
| Performance | [Performance Optimization](../opts/performance_optimization_summary.md) |
| Architecture | [Architecture Documentation](../ARCHITECTURE.md) |

## Getting Help

If you don't find an answer here:

1. **Search existing documentation** - Most issues are covered
2. **Check the test files** - `tests/` directory has examples
3. **Review source code** - Well-commented code explains behavior
4. **File an issue** - Include minimal reproducible example

## Quick Reference: Common Commands

```bash
# Run tests
pytest tests/ -n 4 -v

# Compile Cython
cd backtrader && python -W ignore compile_cython_numba_files.py && cd .. && pip install -U .

# Generate documentation
make docs

# Run with coverage
pytest tests/ --cov=backtrader --cov-report=term-missing

# Type checking
mypy backtrader/

# Code formatting
black backtrader/
```

---

*Last updated: 2026-03-01*
