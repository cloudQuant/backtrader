- --

title: Strategy API
description: Complete Strategy class API reference

- --

# Strategy API

The `Strategy` class is the base class for all user-defined trading strategies in Backtrader. It provides order management, position tracking, indicator integration, and event-driven execution.

## Class Definition

```python
class backtrader.Strategy:
    """Base class for trading strategies."""

```bash

## Parameters

### `params`

Tuple of parameter definitions for the strategy.

```python
class MyStrategy(bt.Strategy):
    params = (
        ('period', 20),
        ('threshold', 1.5),
    )

```bash
Access parameters via `self.p.parameter_name` or `self.params.parameter_name`.

## Core Methods

### `__init__(self)`

Called once before backtesting starts. Use to initialize indicators and calculations.

```python
def __init__(self):
    super().__init__()  # Always call super first
    self.sma = bt.indicators.SMA(self.data.close, period=self.p.period)

```bash

### `start(self)`

Called before backtesting begins, after initialization is complete.

```python
def start(self):
    self.initial_cash = self.broker.getcash()

```bash

### `prenext(self)`

Called for each bar before minimum period is reached.

### `nextstart(self)`

Called once when minimum period is first reached.

### `next(self)`

Called for each bar after minimum period is reached. Contains main trading logic.

```python
def next(self):
    if self.data.close[0] > self.sma[0]:
        self.buy()

```bash

### `stop(self)`

Called after backtesting ends.

```python
def stop(self):
    final_value = self.broker.getvalue()
    print(f'Final Portfolio Value: {final_value}')

```bash

## Order Methods

### `buy(self, **kwargs)`

Create a buy order.

| Parameter | Type | Default | Description |

|-----------|------|---------|-------------|

| `data` | Data | None | Data feed to trade |

| `size` | float | None | Position size (positive) |

| `price` | float | None | Limit price |

| `plimit` | float | None | Limit price for stop-limit |

| `stoplimit` | float | None | Stop-limit activation price |

| `exectype` | Order.ExecType | None | Execution type |

| `valid` | Order.Valid | None | Validity period |

| `oco` | Order | None | One-cancels-other order |

```python

# Market order

order = self.buy()

# Limit order

order = self.buy(price=100.0)

# Specific size

order = self.buy(size=10)

# Stop-limit order

order = self.buy(stoplimit=95.0, price=94.5)

```bash

### `sell(self, **kwargs)`

Create a sell order. Same parameters as `buy()`.

```python

# Sell entire position

order = self.sell()

# Stop loss

order = self.sell(stop=95.0)

```bash

### `close(self, **kwargs)`

Close existing position. Same parameters as `buy()` but automatically determines size.

```python

# Close position

order = self.close()

# Close with limit price

order = self.close(price=105.0)

```bash

### `cancel(self, order)`

Cancel a pending order.

```python
self.cancel(order)

```bash

## Order Notification

### `notify_order(self, order)`

Called when order status changes.

```python
def notify_order(self, order):
    if order.status in [order.Submitted, order.Accepted]:
        return

    if order.status == order.Completed:
        if order.isbuy():
            self.log(f'BUY EXECUTED, Price: {order.executed.price:.2f}')
        else:
            self.log(f'SELL EXECUTED, Price: {order.executed.price:.2f}')

    elif order.status in [order.Canceled, order.Margin, order.Rejected]:
        self.log(f'Order {order.getstatusname()}')

```bash

- *Order Status Values**:

| Status | Description |

|--------|-------------|

| `Order.Created` | Order created |

| `Order.Submitted` | Submitted to broker |

| `Order.Accepted` | Accepted by broker |

| `Order.Partial` | Partially filled |

| `Order.Completed` | Fully filled |

| `Order.Canceled` | Canceled |

| `Order.Margin` | Margin insufficient |

| `Order.Rejected` | Rejected |

## Trade Notification

### `notify_trade(self, trade)`

Called when a trade is closed.

```python
def notify_trade(self, trade):
    if not trade.isclosed:
        return

    self.log(f'Trade P&L: {trade.pnl:.2f}, Commission: {trade.commission:.2f}')

```bash

- *Trade Attributes**:

| Attribute | Description |

|-----------|-------------|

| `trade.pnl` | Gross profit/loss |

| `trade.pnlcomm` | Net profit/loss (after commission) |

| `trade.commission` | Commission paid |

| `trade.isclosed` | Whether trade is closed |

## Position Management

### `position`

Access position information for a data feed.

```python

# Get position for current data

position = self.position

# Get position for specific data

position = self.getposition(data)

# Check if has position

if self.position:
    size = self.position.size
    price = self.position.price

```bash

- *Position Attributes**:

| Attribute | Type | Description |

|-----------|------|-------------|

| `size` | float | Current position size (positive=long, negative=short) |

| `price` | float | Average entry price |

| `price_adj` | float | Adjusted price (for stocks) |

### `getposition(self, data=None, broker=None)`

Get position object for specific data feed.

```python
position = self.getposition(self.datas[1])

```bash

## Data Access

### `data` / `datas`

Access data feeds in the strategy.

```python

# Current (first) data feed

price = self.data.close[0]

# Access by index

price1 = self.datas[0].close[0]
price2 = self.datas[1].close[0]

# Access by name if specified

price = self.aapl.close[0]

```bash

### `getdatabyname(self, name)`

Get data feed by name.

```python
data = self.getdatabyname('AAPL')

```bash

## Broker Access

### `broker`

Access broker methods.

```python
cash = self.broker.getcash()
value = self.broker.getvalue()

```bash

- *Common Broker Methods**:

| Method | Description |

|--------|-------------|

| `getcash()` | Get available cash |

| `getvalue()` | Get portfolio value |

| `getposition(data)` | Get position for data |

| `setcash(amount)` | Set cash amount |

## Indicator Integration

Indicators defined in `__init__` are automatically calculated and updated.

```python
def __init__(self):
    self.sma20 = bt.indicators.SMA(self.data.close, period=20)
    self.sma50 = bt.indicators.SMA(self.data.close, period=50)
    self.crossover = bt.indicators.CrossOver(self.sma20, self.sma50)

def next(self):
    if self.crossover > 0:
        self.buy()

```bash

## Logging

### `log(self, msg, dt=None)`

Log messages with timestamp.

```python
def next(self):
    self.log(f'Close: {self.data.close[0]:.2f}')

```bash

## Strategy Lifecycle

```mermaid
stateDiagram-v2
    [*] --> __init__: Strategy Created
    __init__ --> start: Initialization Complete
    start --> prenext: Backtest Starts
    prenext --> prenext: minperiod not reached
    prenext --> nextstart: minperiod reached
    nextstart --> next: First valid bar
    next --> next: Processing bars
    next --> stop: Backtest ends
    stop --> [*]: Cleanup

```bash

## Multiple Data Feeds

```python
class MyStrategy(bt.Strategy):
    def __init__(self):

# Access multiple data feeds
        self.data0 = self.datas[0]  # First data
        self.data1 = self.datas[1]  # Second data

    def next(self):

# Trade based on both data feeds
        if self.data0.close[0] > self.data1.close[0]:
            self.buy(data=self.data0)

```bash

## Timer Events

### `notify_timer(self, timer, when)`

Called when a timer event fires.

```python
def __init__(self):

# Add timer
    self.add_timer(
        when=datetime.time(hour=14, minute=30),
        allow=True
    )

def notify_timer(self, timer, when):
    self.log(f'Timer fired at {when}')

```bash

## Data Events

### `notify_data(self, data, status, *args, **kwargs)`

Called when data status changes.

```python
def notify_data(self, data, status, *args, **kwargs):
    if status == data.LIVE:
        self.log(f'{data._name} is now LIVE')

```bash

## Signal Strategy

For signal-based trading, use `SignalStrategy`:

```python
class MySignalStrategy(bt.SignalStrategy):
    params = (('period', 20),)

    def __init__(self):
        self.sma = bt.indicators.SMA(self.data.close, period=self.p.period)
        self.signal_add(bt.SIGNAL_LONG, self.data.close > self.sma)

```bash

## Full Example

```python
import backtrader as bt

class MyStrategy(bt.Strategy):
    """
    Sample moving average crossover strategy.
    """

    params = (
        ('fast_period', 10),
        ('slow_period', 30),
    )

    def __init__(self):
        super().__init__()
        self.fast_ma = bt.indicators.SMA(self.data.close, period=self.p.fast_period)
        self.slow_ma = bt.indicators.SMA(self.data.close, period=self.p.slow_period)
        self.crossover = bt.indicators.CrossOver(self.fast_ma, self.slow_ma)
        self.order = None

    def next(self):
        if self.order:
            return

        if not self.position:
            if self.crossover > 0:
                self.order = self.buy()
        else:
            if self.crossover < 0:
                self.order = self.sell()

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status == order.Completed:
            if order.isbuy():
                self.log(f'BUY EXECUTED: {order.executed.price:.2f}')
            else:
                self.log(f'SELL EXECUTED: {order.executed.price:.2f}')

        self.order = None

    def notify_trade(self, trade):
        if trade.isclosed:
            self.log(f'Trade P&L: {trade.pnl:.2f}')

    def stop(self):
        self.log(f'Final Value: {self.broker.getvalue():.2f}')

```bash

## Next Steps

- [Indicators API](indicator.md) - Indicator development
- [Analyzers API](analyzer.md) - Performance analysis
- [Data Feeds API](data-feeds.md) - Data sources
