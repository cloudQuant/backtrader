---
title: Backtrader Upgrade Guide
description: Guide for upgrading between versions of Backtrader
---

# Backtrader Upgrade Guide

This guide helps you upgrade between different versions of Backtrader. It covers version-specific changes, deprecated features, breaking changes, and migration paths.

## Table of Contents

- [Version Overview](#version-overview)
- [Python Version Compatibility](#python-version-compatibility)
- [Upgrade Paths](#upgrade-paths)
- [Breaking Changes by Version](#breaking-changes-by-version)
- [New Features Migration](#new-features-migration)
- [Data Format Migrations](#data-format-migrations)
- [Configuration Changes](#configuration-changes)
- [Testing After Upgrade](#testing-after-upgrade)
- [Troubleshooting](#troubleshooting)

---

## Version Overview

| Version | Release Date | Status | Key Changes |
|---------|--------------|--------|-------------|
| **1.1.0** | 2026 (dev branch) | Active | Metaclass removal, 45% performance improvement, CCXT/CTP integration |
| **1.0.0** | 2025 | Stable | Initial performance-optimized release baseline |
| **0.x** | Pre-2025 | Legacy | Original backtrader architecture |

### Current Stable Version: 1.1.0

The dev branch (version 1.1.0) represents the actively developed version with significant improvements over the original backtrader.

---

## Python Version Compatibility

| Python Version | 1.1.0 Status | 1.0.0 Status | Notes |
|----------------|--------------|---------------|-------|
| **3.13** | ✅ Recommended | ✅ Best Performance | ~15% faster than 3.8 |
| **3.12** | ✅ Supported | ✅ Supported | Some dependencies may have issues |
| **3.11** | ✅ Supported | ✅ Supported | Good performance balance |
| **3.10** | ✅ Supported | ✅ Supported | Stable |
| **3.9** | ✅ Supported | ✅ Supported | Minimum recommended |
| **3.8** | ⚠️ Deprecated | ✅ Supported | Security updates only |
| **< 3.8** | ❌ Not Supported | ❌ Not Supported | Upgrade required |

### Recommendation

- **New Projects**: Use Python 3.11 or 3.13 for best performance
- **Existing Projects**: Upgrade from 3.8 to 3.11+ when possible

---

## Upgrade Paths

### Path 1: From Original Backtrader (mementum/backtrader) to 1.1.0

```bash
# Step 1: Remove original backtrader
pip uninstall backtrader

# Step 2: Clone this fork
git clone https://github.com/cloudQuant/backtrader.git
cd backtrader

# Step 3: Install dependencies
pip install -r requirements.txt

# Step 4: Install in development mode
pip install -e .

# Step 5: Verify installation
python -c "import backtrader as bt; print(bt.__version__)"
# Expected output: 1.1.0
```

### Path 2: From Version 1.0.0 to 1.1.0

```bash
# Step 1: Pull latest changes
git fetch origin
git checkout dev  # or main branch for 1.1.0

# Step 2: Update dependencies
pip install -r requirements.txt --upgrade

# Step 3: Reinstall
pip install -e .

# Step 4: (Optional) Recompile Cython extensions
cd backtrader
python -W ignore compile_cython_numba_files.py
cd ..
pip install -U .
```

### Path 3: Direct Installation from Source

```bash
# Install with all optional dependencies
pip install -e ".[ccxt,ctp,plotly,bokeh]"
```

---

## Breaking Changes by Version

### Version 1.1.0 (Current)

#### Internal Changes (API Compatible)

While version 1.1.0 maintains 100% API compatibility with the original backtrader, the following internal changes may affect advanced users who subclass internal components:

| Change Area | Before | After | Migration Required |
|-------------|--------|-------|-------------------|
| **Metaclass Usage** | `MetaBase`, `MetaLineRoot`, `MetaIndicator` | `donew()` + `BaseMixin` pattern | No (unless overriding `__new__`) |
| **Parameter Initialization** | In metaclass `__call__` | In `__init__` after `super().__init__()` | No for normal usage |
| **Indicator Registration** | Automatic via metaclass | Explicit in `__init__` | No (automatic) |

#### Code Examples

**Before (Original - with metaclasses)**:
```python
# This still works in 1.1.0 - no changes needed!
class MyStrategy(bt.Strategy):
    params = (('period', 20),)

    def __init__(self):
        self.sma = bt.indicators.SMA(self.data.close, period=self.p.period)

    def next(self):
        if self.data.close[0] > self.sma[0]:
            self.buy()
```

**After (1.1.0 - same code works)**:
```python
# No changes required - API is identical
class MyStrategy(bt.Strategy):
    params = (('period', 20),)

    def __init__(self):
        # Parameters available after super().__init__()
        super().__init__()  # Recommended but not required
        self.sma = bt.indicators.SMA(self.data.close, period=self.p.period)

    def next(self):
        if self.data.close[0] > self.sma[0]:
            self.buy()
```

### Version 1.0.0

#### Initial Performance Release

- First version with metaclass removal
- 45% performance improvement over original
- Cython acceleration support added

---

## New Features Migration

### 1. CCXT Live Trading (New in 1.1.0)

#### Before: Backtesting Only

```python
import backtrader as bt
from datetime import datetime

cerebro = bt.Cerebro()
data = bt.feeds.GenericCSVData(
    dataname='data.csv',
    fromdate=datetime(2020, 1, 1),
    todate=datetime(2023, 12, 31)
)
cerebro.adddata(data)
cerebro.run()
```

#### After: Live Trading with CCXT

```python
import backtrader as bt

# Create store for exchange connection
store = bt.stores.CCXTStore(
    exchange='binance',
    currency='USDT',
    config={
        'apiKey': 'your_api_key',
        'secret': 'your_secret',
        'enableRateLimit': True,
    }
)

# Get live data feed with WebSocket
data = store.getdata(
    dataname='BTC/USDT',
    timeframe=bt.TimeFrame.Minutes,
    compression=1,
    use_websocket=True,  # Enable low-latency WebSocket
    backfill_start=True,  # Backfill historical data on start
)

# Get broker for live trading
broker = store.getbroker(use_threaded_order_manager=True)

cerebro = bt.Cerebro()
cerebro.adddata(data)
cerebro.setbroker(broker)
cerebro.run()
```

#### Key Migration Points

| Aspect | Backtesting | Live Trading |
|--------|-------------|--------------|
| **Data Source** | CSV/Pandas files | CCXT Store (REST/WebSocket) |
| **Broker** | Simulated | Real exchange via CCXT |
| **Order Execution** | Instant | Depends on exchange latency |
| **Error Handling** | Not needed | Critical - implement `notify_order()` |

### 2. CTP Futures Trading (New in 1.1.0)

```python
import backtrader as bt

# CTP Store for Chinese futures markets
store = bt.stores.CTPStore(
    broker_id='9999',
    investor_id='your_investor_id',
    password='your_password',
    td_address='tcp://180.168.146.187:10130',  # Trading front
    md_address='tcp://180.168.146.187:10131',  # Market data front
    app_id='simnow_client',
    auth_code='simnow_auth',
)

data = store.getdata(dataname='au2506')  # Gold futures contract
broker = store.getbroker()

cerebro = bt.Cerebro()
cerebro.adddata(data)
cerebro.setbroker(broker)
```

### 3. Performance Modes (New in 1.1.0)

#### TS Mode (Time Series Vectorization)

```python
# Optimized for single-asset strategies
cerebro = bt.Cerebro()
# ... setup ...
cerebro.run(ts_mode=True)  # 10-50x faster for suitable strategies
```

#### CS Mode (Cross-Sectional)

```python
# Optimized for multi-asset portfolios
cerebro = bt.Cerebro()
# ... setup ...
cerebro.run(cs_mode=True)  # Efficient cross-sectional signals
```

### 4. Interactive Plotting (New in 1.1.0)

#### Before: Static Matplotlib

```python
cerebro.plot()  # Opens static matplotlib window
```

#### After: Interactive Plotly

```python
# Interactive web-based plotting
cerebro.plot(style='plotly')

# Or save to HTML
from backtrader.plot.plot_plotly import PlotlyPlot
plotter = PlotlyPlot(style='candle')
figs = plotter.plot(strategy)
figs[0].write_html('backtest.html')
```

---

## Data Format Migrations

### CSV Data Format

No changes required - existing CSV files work unchanged:

```python
data = bt.feeds.GenericCSVData(
    dataname='data.csv',
    datetime=0, open=1, high=2, low=3, close=4, volume=5,
    dtformat='%Y-%m-%d',
)
```

### Pandas Data Format

No changes required:

```python
import pandas as pd

# Existing DataFrame format works
df = pd.read_csv('data.csv', parse_dates=['date'], index_col='date'])
data = bt.feeds.PandasData(dataname=df)
```

### New Data Feed Parameters (1.1.0)

```python
# CCXT-specific parameters
data = bt.feeds.CCXTData(
    dataname='BTC/USDT',
    timeframe=bt.TimeFrame.Minutes,
    compression=1,
    ohlcv_limit=100,          # NEW: Bars per fetch
    drop_newest=True,         # NEW: Drop incomplete current bar
    use_websocket=True,       # NEW: Enable WebSocket
    backfill_start=True,      # NEW: Backfill on connection
)
```

---

## Configuration Changes

### Cerebro Configuration

#### New Parameters (1.1.0)

```python
cerebro = bt.Cerebro(
    exactbars=1,        # Memory optimization: -2 (min), -1 (save), 1 (limited), False (full)
    preload=True,       # Preload data for performance
    runonce=True,       # Use vectorized execution
    maxcpus=4,          # Parallel optimization
)
```

### Store Configuration

#### CCXT Store

```python
store = bt.stores.CCXTStore(
    exchange='binance',
    currency='USDT',
    config={
        # Standard CCXT config
        'apiKey': 'your_key',
        'secret': 'your_secret',
        'enableRateLimit': True,

        # NEW: Exchange-specific options
        'options': {
            'defaultType': 'future',  # For futures trading
            'adjustForTimeDifference': True,
        }
    },

    # NEW: Connection management
    reconnect_delay=5.0,
    max_reconnect_delay=60.0,
)
```

### Broker Configuration

#### New Error Handling Options (1.1.0)

```python
broker = store.getbroker(
    debug=False,                      # Debug output
    use_threaded_order_manager=True,  # Non-blocking order updates
    max_retries=3,                    # API retry attempts (NEW)
    retry_delay=1.0,                  # Retry base delay (NEW)
)
```

---

## Testing After Upgrade

### 1. Run Existing Tests

```bash
# Run all tests
pytest tests/ -n 4 -v

# Run specific test categories
pytest tests/original_tests/ -v    # Core functionality
pytest tests/add_tests/ -v         # Additional tests
pytest tests/new_functions/ -v     # New feature tests

# Run with coverage
pytest tests/ --cov=backtrader --cov-report=term-missing
```

### 2. Verify Strategy Output

Create a test script to verify your strategies produce expected results:

```python
import backtrader as bt
from datetime import datetime

# Your strategy
class MyStrategy(bt.Strategy):
    params = (('period', 20),)

    def __init__(self):
        super().__init__()
        self.sma = bt.indicators.SMA(self.data.close, period=self.p.period)

    def next(self):
        if len(self.data) >= self.p.period:
            assert self.sma[0] is not None, "SMA should not be None"

# Test with known data
cerebro = bt.Cerebro()
data = bt.feeds.GenericCSVData(
    dataname='test_data.csv',
    fromdate=datetime(2020, 1, 1),
    todate=datetime(2020, 12, 31)
)
cerebro.adddata(data)
cerebro.addstrategy(MyStrategy)
strats = cerebro.run()

# Verify results
assert len(strats) == 1
assert strats[0].analyzers is not None
print("✅ Strategy test passed")
```

### 3. Performance Benchmark

```python
import time

start = time.time()
cerebro.run()
elapsed = time.time() - start

print(f"Backtest completed in {elapsed:.2f} seconds")
# Compare with previous version times
```

### 4. Numerical Precision Check

```python
# Verify indicator calculations match expected values
# (within floating-point precision tolerance)

import numpy as np

def assert_close(actual, expected, tol=1e-10):
    assert np.abs(actual - expected) < tol, \
        f"Values differ: {actual} vs {expected}"

# Test critical indicators
class IndicatorTest(bt.Strategy):
    def __init__(self):
        self.sma = bt.indicators.SMA(self.data.close, period=20)

    def next(self):
        if len(self.data) == 100:  # At known point
            # Replace with your expected value
            assert_close(self.sma[0], 123.45, tol=1e-8)
            cerebro.runstop()
```

---

## Troubleshooting

### Issue 1: Import Errors After Upgrade

**Symptom**:
```python
ImportError: cannot import name 'CCXTStore' from 'backtrader.stores'
```

**Solution**:
```bash
# Ensure you're using the correct version
python -c "import backtrader; print(backtrader.__version__)"

# Reinstall in development mode
pip uninstall backtrader
pip install -e /path/to/backtrader
```

### Issue 2: Cython Extensions Not Compiled

**Symptom**:
```python
AttributeError: module 'backtrader.utils' has no attribute 'ts_cal_value'
```

**Solution**:
```bash
# Install Cython
pip install cython

# Recompile
cd backtrader
python -W ignore compile_cython_numba_files.py
cd ..
pip install -U .
```

### Issue 3: Different Test Results

**Symptom**: Strategy produces slightly different results after upgrade.

**Possible Causes**:
1. Floating-point precision improvements (within tolerance)
2. Indicator calculation fixes (verify against known values)
3. Data loading differences (check timezones, preprocessing)

**Solution**:
```python
# Enable debug output
cerebro = bt.Cerebro(stdstats=False)

# Add data observers
cerebro.addobserver(bt.observers.DataTriggers)

# Compare bar-by-bar
class DebugStrategy(bt.Strategy):
    def next(self):
        if len(self.data) % 100 == 0:
            print(f"Bar {len(self.data)}: close={self.data.close[0]:.4f}")
```

### Issue 4: WebSocket Connection Failures

**Symptom**: CCXT WebSocket fails to connect.

**Solution**:
```python
# Check ccxtpro installation
pip install ccxtpro

# Or disable WebSocket, use REST polling
data = store.getdata(
    dataname='BTC/USDT',
    use_websocket=False,  # Fall back to REST
)

# Verify exchange supports WebSocket
import ccxtpro as ccxt
exchange = ccxt.binance()
print(f"WebSocket support: {exchange.has['watchOHLCV']}")
```

### Issue 5: Memory Issues on Large Backtests

**Symptom**: Out of memory errors during long backtests.

**Solution**:
```python
# Enable memory optimization
cerebro = bt.Cerebro(
    exactbars=1,  # Limited memory mode
    preload=False,  # Don't preload all data
)

# Or use qbuffer for data feeds
data = bt.feeds.GenericCSVData(
    dataname='large_data.csv',
    qbuffer=True,  # Use circular buffer
)
```

### Issue 6: Parameter Access Errors

**Symptom**:
```python
AttributeError: 'MyStrategy' object has no attribute 'p'
```

**Solution**:
```python
class MyStrategy(bt.Strategy):
    params = (('period', 20),)

    def __init__(self):
        # CRITICAL: Call super().__init__() FIRST
        super().__init__()
        # NOW parameters are available
        self.sma = bt.indicators.SMA(period=self.p.period)
```

---

## Automated Upgrade Script

```python
#!/usr/bin/env python
"""
upgrade_check.py - Check if your code is compatible with Backtrader 1.1.0

Usage:
    python upgrade_check.py my_strategy.py
"""

import ast
import sys
from pathlib import Path

class UpgradeChecker(ast.NodeVisitor):
    def __init__(self):
        self.issues = []
        self.warnings = []

    def visit_ClassDef(self, node):
        # Check for Strategy subclasses
        for base in node.bases:
            if isinstance(base, ast.Name) and base.id == 'Strategy':
                # Check __init__ method
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name == '__init__':
                        # Check if super().__init__() is called
                        has_super = any(
                            isinstance(stmt, ast.Expr) and
                            isinstance(stmt.value, ast.Call) and
                            isinstance(stmt.value.func, ast.Attribute) and
                            stmt.value.func.attr == '__init__'
                            for stmt in item.body
                        )
                        if not has_super:
                            self.warnings.append({
                                'line': item.lineno,
                                'msg': f'Class {node.name}: Consider adding super().__init__() call',
                            })
        self.generic_visit(node)

def check_file(filepath):
    with open(filepath, 'r') as f:
        code = f.read()

    tree = ast.parse(code, filename=filepath)
    checker = UpgradeChecker()
    checker.visit(tree)

    return checker.issues, checker.warnings

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python upgrade_check.py <file.py>")
        sys.exit(1)

    filepath = sys.argv[1]
    issues, warnings = check_file(filepath)

    if issues:
        print(f"\n❌ Issues found in {filepath}:")
        for issue in issues:
            print(f"  Line {issue['line']}: {issue['msg']}")
        sys.exit(1)

    if warnings:
        print(f"\n⚠️  Warnings for {filepath}:")
        for warning in warnings:
            print(f"  Line {warning['line']}: {warning['msg']}")
    else:
        print(f"\n✅ No issues found in {filepath}")

    print("\nYour code appears compatible with Backtrader 1.1.0!")
```

---

## Quick Reference: Before/After Summary

| Feature | Before (Original) | After (1.1.0) |
|---------|-------------------|---------------|
| **Performance** | Baseline | 45% faster |
| **Metaclasses** | Heavy use | Removed (internal) |
| **Live Trading** | Limited | Full CCXT/CTP support |
| **WebSocket** | No | Yes, with auto-reconnect |
| **Plotting** | Matplotlib | Matplotlib + Plotly + Bokeh |
| **Python 3.13** | Not supported | Recommended |
| **Cython** | Optional | Enhanced core calculations |
| **TS/CS Modes** | No | Yes, for specialized strategies |
| **Documentation** | Basic | Comprehensive bilingual |

---

## Additional Resources

- [Migration from Original Backtrader](from-original.md)
- [CCXT Live Trading Guide](../CCXT_LIVE_TRADING_GUIDE.md)
- [Architecture Documentation](../ARCHITECTURE.md)
- [Project Status](../PROJECT_STATUS.md)
- [Contributing Guidelines](../../CONTRIBUTING.md)

---

## Checklist for Successful Upgrade

- [ ] Verify Python version (3.9+ recommended)
- [ ] Backup existing strategy files
- [ ] Run existing test suite before upgrade
- [ ] Install new version (`pip install -e .`)
- [ ] Compile Cython extensions (optional but recommended)
- [ ] Run test suite after upgrade
- [ ] Verify strategy output matches expected values
- [ ] (Optional) Migrate to CCXT live trading
- [ ] (Optional) Enable performance modes
- [ ] (Optional) Try Plotly interactive plotting
- [ ] Update any custom indicators/strategies if needed

---

**Last Updated**: 2026-03-01

**Version**: 1.1.0
