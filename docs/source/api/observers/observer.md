---
title: Observer API
description: Complete Observer class API reference
---

# Observer API

The `Observer` class is the base class for monitoring strategy execution and collecting data during backtesting. Observers track metrics like cash, value, drawdown, trades, and other performance statistics.

Unlike indicators which generate signals, observers primarily record and visualize strategy state.

## Class Definition

```python
class backtrader.Observer:
    """Base class for monitoring strategy execution."""
```

## Core Attributes

### `csv`

Whether to save observer data to CSV files (default: `True`).

```python
class MyObserver(bt.Observer):
    csv = True  # Include in CSV output
```

### `plotinfo`

Plotting configuration dictionary.

```python
plotinfo = dict(
    plot=True,       # Whether to plot this observer
    subplot=True,    # Whether to use a separate subplot
    plotname='',     # Name in plot legend
)
```

### `plotlines`

Line-specific plotting settings.

```python
plotlines = dict(
    line1=dict(color='blue', linewidth=2),
    line2=dict(_plotskip=True),  # Skip plotting this line
)
```

### `_stclock`

Controls clock synchronization. When `True`, the observer uses strategy-wide clock (default: `False`).

### `_ltype`

Line iterator type. Set to `LineIterator.ObsType` (value: 2) for observers.

## Core Methods

### `__init__(self)`

Called during observer initialization. Initialize tracking variables and add analyzers if needed.

```python
def __init__(self):
    super().__init__()
    self._analyzers = list()
    # Initialize tracking variables
    self.peak = float('-inf')
```

### `start(self)`

Called at the start of the backtesting run.

```python
def start(self):
    # Perform initialization before data processing
    self.initial_value = self._owner.broker.getvalue()
```

### `_start(self)`

Internal method that ensures owner is set before calling `start()`.

### `prenext(self)`

Called for each bar before minimum period is reached. By default, observers call `next()` during prenext to track all bars from the beginning.

```python
def prenext(self):
    self.next()  # Default behavior - process every bar
```

### `next(self)`

Called for each bar. Contains the main logic for updating observer values.

```python
def next(self):
    self.lines.cash[0] = self._owner.broker.getcash()
```

### `stop(self)`

Called after backtesting ends.

### `_register_analyzer(self, analyzer)`

Register an analyzer with this observer.

## Line System

Observers use the same line system as indicators:

```python
class MyObserver(bt.Observer):
    lines = ('metric1', 'metric2')

    def next(self):
        self.lines.metric1[0] = calculate_metric1()
        self.lines.metric2[0] = calculate_metric2()
```

## Built-in Observers

### Broker Observers

#### Cash

Tracks current cash amount in the broker.

```python
cerebro.addobserver(bt.observers.Cash)
```

**Lines**: `cash`

#### Value

Tracks portfolio value including cash.

```python
cerebro.addobserver(bt.observers.Value)
```

**Parameters**:
- `fund` (default: `None`) - Use fund value instead of total value

**Lines**: `value`

#### Broker

Combines Cash and Value observers.

```python
cerebro.addobserver(bt.observers.Broker)
```

**Parameters**:
- `fund` (default: `None`) - Use fund mode

**Lines**: `cash`, `value`

#### FundValue

Tracks fund-like value.

**Lines**: `fundval`

#### FundShares

Tracks fund-like shares.

**Lines**: `fundshares`

### Drawdown Observers

#### DrawDown

Tracks current and maximum drawdown levels.

```python
cerebro.addobserver(bt.observers.DrawDown)
```

**Parameters**:
- `fund` (default: `None`) - Use fund mode for returns

**Lines**:
- `drawdown` - Current drawdown percentage (plotted)
- `maxdrawdown` - Maximum drawdown (not plotted)

```python
class DrawDown(Observer):
    _stclock = True
    lines = ('drawdown', 'maxdrawdown')
    plotlines = dict(maxdrawdown=dict(_plotskip=True))
```

#### DrawDownLength

Tracks current drawdown length and maximum length.

**Lines**:
- `len` - Current drawdown length
- `maxlen` - Maximum drawdown length

### Trade Observers

#### Trades

Tracks completed trades and plots PnL when trades close.

```python
cerebro.addobserver(bt.observers.Trades)
```

**Parameters**:
- `pnlcomm` (default: `True`) - Show net PnL after commission

**Lines**:
- `pnlplus` - Positive PnL values (blue markers)
- `pnlminus` - Negative PnL values (red markers)

```python
# Trades observer tracks:
# - Total trades count
# - Long/short trade counts
# - Win/loss statistics
# - Trade length statistics
```

#### DataTrades

Tracks PnL for multiple data feeds separately.

**Parameters**:
- `usenames` (default: `True`) - Use data names for labels

### BuySell Observer

Visualizes buy and sell orders on the chart.

```python
cerebro.addobserver(bt.observers.BuySell)
```

**Parameters**:
- `barplot` (default: `False`) - Plot signals at bar extremes
- `bardist` (default: `0.015`) - Distance from high/low (1.5%)

**Lines**:
- `buy` - Buy marker (green triangle up)
- `sell` - Sell marker (red triangle down)

```python
# Customize marker appearance
cerebro.addobserver(bt.observers.BuySell, barplot=True, bardist=0.02)
```

### Return Observers

#### TimeReturn

Tracks strategy returns over time periods.

```python
cerebro.addobserver(bt.observers.TimeReturn, timeframe=bt.TimeFrame.Days)
```

**Parameters**:
- `timeframe` (default: `None`) - Time aggregation period
- `compression` (default: `None`) - Compression for sub-day timeframes
- `fund` (default: `None`) - Use fund mode

**Lines**: `timereturn`

```python
# Track daily returns
cerebro.addobserver(bt.observers.TimeReturn, timeframe=bt.TimeFrame.Days)

# Track weekly returns
cerebro.addobserver(bt.observers.TimeReturn, timeframe=bt.TimeFrame.Weeks)
```

#### LogReturns

Tracks log returns of the strategy.

```python
cerebro.addobserver(bt.observers.LogReturns)
```

**Parameters**:
- `timeframe` (default: `None`) - Time aggregation period
- `compression` (default: `None`) - Compression for sub-day timeframes
- `fund` (default: `None`) - Use fund mode

**Lines**: `logret1`

#### LogReturns2

Extends LogReturns to show two instruments.

**Lines**: `logret1`, `logret2`

### Benchmark Observer

Compares strategy returns to a reference asset.

```python
data = bt.feeds.GenericCSVData(dataname='benchmark.csv')
cerebro.adddata(data)
cerebro.addobserver(bt.observers.Benchmark, data=data)
```

**Parameters**:
- `data` (default: `None`) - Reference data feed
- `_doprenext` (default: `False`) - Track from data start
- `firstopen` (default: `False`) - Use opening price for first comparison
- `fund` (default: `None`) - Use fund mode

**Lines**: `benchmark`

### TradeLogger

Comprehensive logging observer for all trading activities.

```python
cerebro.addobserver(bt.observers.TradeLogger,
                    log_dir='./logs',
                    log_orders=True,
                    log_trades=True,
                    log_positions=True,
                    log_indicators=True,
                    log_signals=True)
```

**Parameters**:
- `log_dir` (default: `'./logs'`) - Directory for log files
- `log_orders` (default: `True`) - Log order status changes
- `log_trades` (default: `True`) - Log trade openings/closings
- `log_positions` (default: `True`) - Log positions every bar
- `log_indicators` (default: `True`) - Log indicator values every bar
- `log_signals` (default: `True`) - Log buy/sell signals
- `log_position_snapshot` (default: `True`) - Save position snapshot to YAML
- `snapshot_file` (default: `'current_position.yaml'`) - Snapshot filename
- `log_format` (default: `'json'`) - Log format ('json' or 'text')
- `log_to_console` (default: `False`) - Also print to console
- `mysql_enabled` (default: `False`) - Enable MySQL logging
- `mysql_host` (default: `'localhost'`) - MySQL host
- `mysql_port` (default: `3306`) - MySQL port
- `mysql_user` (default: `'root'`) - MySQL user
- `mysql_password` (default: `''`) - MySQL password
- `mysql_database` (default: `'backtrader'`) - MySQL database

**Generated Files**:
- `order.log` - Order status changes
- `trade.log` - Trade openings and closings
- `position.log` - Position values every bar
- `indicator.log` - Indicator values every bar
- `signal.log` - Buy/sell signals
- `current_position.yaml` - Position snapshot

## Custom Observer Development

### Basic Observer

```python
import backtrader as bt

class CustomMetric(bt.Observer):
    """
    Observer that tracks a custom metric.
    """
    _stclock = True  # Use strategy clock

    lines = ('custom_value',)

    params = (
        ('period', 20),
    )

    plotinfo = dict(
        plot=True,
        subplot=True,
        plotname='Custom Metric',
    )

    def __init__(self):
        super().__init__()
        self.high_watermark = float('-inf')

    def next(self):
        # Calculate custom metric
        value = self._owner.broker.getvalue()

        # Track high watermark
        if value > self.high_watermark:
            self.high_watermark = value

        # Store in line
        self.lines.custom_value[0] = value - self.high_watermark
```

### Observer with Analyzer

```python
class SharpeRatioObserver(bt.Observer):
    """
    Observer that tracks Sharpe ratio using an analyzer.
    """
    _stclock = True

    lines = ('sharpe',)

    params = (
        ('period', 252),  # Annualization period
        ('riskfreerate', 0.0),
    )

    plotinfo = dict(plot=True, subplot=True)

    def __init__(self):
        super().__init__()
        # Add analyzer as slave
        self._sharpe = self._owner._addanalyzer_slave(
            bt.analyzers.SharpeRatio,
            period=self.p.period,
            riskfreerate=self.p.riskfreerate
        )

    def next(self):
        # Get current Sharpe ratio from analyzer
        if hasattr(self._sharpe, 'rets') and self._sharpe.rets:
            self.lines.sharpe[0] = self._sharpe.rets.get('sharperatio', float('NaN'))
```

### Multi-Line Observer

```python
class PortfolioStats(bt.Observer):
    """
    Observer tracking multiple portfolio statistics.
    """
    _stclock = True

    lines = (
        'exposure',
        'leverage',
        'cash_ratio',
    )

    plotinfo = dict(plot=True, subplot=True)

    plotlines = dict(
        exposure=dict(color='blue'),
        leverage=dict(color='orange'),
        cash_ratio=dict(color='green'),
    )

    def next(self):
        portfolio_value = self._owner.broker.getvalue()
        cash = self._owner.broker.getcash()

        # Calculate metrics
        self.lines.cash_ratio[0] = cash / portfolio_value if portfolio_value else 0
        self.lines.exposure[0] = 1 - self.lines.cash_ratio[0]

        # Calculate leverage (total position value / portfolio value)
        total_position = 0
        for data in self._owner.datas:
            position = self._owner.getposition(data)
            total_position += abs(position.size) * data.close[0]

        self.lines.leverage[0] = total_position / portfolio_value if portfolio_value else 0
```

## Registration Process

Observers are automatically registered when added via `cerebro.addobserver()`:

```python
# Observer registration
cerebro.addobserver(bt.observers.DrawDown)

# With parameters
cerebro.addobserver(bt.observers.DrawDown, fund=True)

# Multiple instances
cerebro.addobserver(bt.observers.DrawDown)
cerebro.addobserver(bt.observers.Trades)
```

The registration process:
1. Observer instance is created
2. `_ltype` is set to `LineIterator.ObsType` (2)
3. Observer is added to strategy's `_lineiterators[ObsType]` list
4. `prenext()`, `next()`, `stop()` are called during execution

## Observer vs Indicator

| Feature | Observer | Indicator |
|---------|----------|-----------|
| Purpose | Monitor and record | Generate signals |
| `_ltype` | `ObsType` (2) | `IndType` (0) |
| `_stclock` | Often `True` | Usually `False` |
| Default `prenext` | Calls `next()` | Does nothing |
| Plotting | Subplot by default | Overlay on data |
| Line calculation | External (broker/trades) | Internal calculation |

## Plotting Configuration

### Disable Plotting

```python
# Individual observer
cerebro.addobserver(bt.observers.DrawDown, _plot=False)

# Or modify plotinfo
class MyObserver(bt.Observer):
    plotinfo = dict(plot=False)
```

### Subplot Configuration

```python
class MyObserver(bt.Observer):
    plotinfo = dict(
        plot=True,
        subplot=True,      # Separate subplot
        plotlinelabels=True,
        plotymargin=0.10,  # Y-axis margin
        plothlines=[0.0],  # Horizontal lines
    )
```

### Line Styling

```python
class MyObserver(bt.Observer):
    plotlines = dict(
        metric1=dict(
            color='blue',
            linewidth=2,
            linestyle='-',
            marker='o',
            markersize=4,
        ),
        metric2=dict(
            color='red',
            _plotskip=True,  # Don't plot
        ),
    )
```

## Full Example

```python
import backtrader as bt

class MyStrategy(bt.Strategy):
    params = (
        ('sma_period', 20),
    )

    def __init__(self):
        self.sma = bt.indicators.SMA(self.data.close, period=self.p.sma_period)

    def next(self):
        if not self.position:
            if self.data.close[0] > self.sma[0]:
                self.buy()
        else:
            if self.data.close[0] < self.sma[0]:
                self.sell()

# Create cerebro
cerebro = bt.Cerebro()

# Add strategy
cerebro.addstrategy(MyStrategy)

# Add data
data = bt.feeds.YahooFinanceData(dataname='AAPL', fromdate='2020-01-01', todate='2023-12-31')
cerebro.adddata(data)

# Add observers
cerebro.addobserver(bt.observers.Broker)        # Cash and Value
cerebro.addobserver(bt.observers.DrawDown)      # Drawdown tracking
cerebro.addobserver(bt.observers.Trades)        # Trade PnL
cerebro.addobserver(bt.observers.BuySell)       # Buy/sell markers

# Add custom observer
class PositionSize(bt.Observer):
    _stclock = True
    lines = ('possize',)
    plotinfo = dict(plot=True, subplot=True, plotname='Position Size')

    def next(self):
        self.lines.possize[0] = self._owner.getposition().size

cerebro.addobserver(PositionSize)

# Run
cerebro.run()

# Plot
cerebro.plot()
```

## Next Steps

- [Strategy API](strategy.md) - Strategy development
- [Analyzer API](analyzer.md) - Performance analysis
- [Indicator API](indicator.md) - Custom indicators
