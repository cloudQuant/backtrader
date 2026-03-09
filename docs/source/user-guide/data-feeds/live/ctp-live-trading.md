- --

title: CTP Live Trading
description: Trading Chinese futures live via CTP API

- --

# CTP Live Trading

CTP (Comprehensive Transaction Platform) is the standard API for trading Chinese futures. This guide covers connecting backtrader to CTP for live futures trading through the `ctp-python` package.

## Introduction

The CTP integration provides:

- **Live Market Data**: Real-time tick data from Chinese futures exchanges
- **Order Management**: Submit, cancel, and track orders
- **Position Tracking**: Real-time position and account updates
- **SimNow Support**: Free simulation environment for testing

### Supported Exchanges

- SHFE (Shanghai Futures Exchange) - e.g., rb, cu, al, au
- DCE (Dalian Commodity Exchange) - e.g., m, y, p, a
- CZCE (Zhengzhou Commodity Exchange) - e.g., SR, CF, MA
- INE (Shanghai International Energy Exchange) - e.g., sc, lu
- CFFEX (China Financial Futures Exchange) - e.g., IF, IH, IC, T, TF

## Prerequisites

Install the required package:

```bash
pip install ctp-python

```bash
For historical data backfill (optional but recommended):

```bash
pip install akshare

```bash

## Configuration

### Connection Parameters

| Parameter | Description | Example |

|-----------|-------------|---------|

| `td_front` | Trader front address | `tcp://182.254.243.31:30001` |

| `md_front` | Market data front address | `tcp://182.254.243.31:30011` |

| `broker_id` | Broker ID assigned by CTP | `9999` |

| `user_id` | Your trading account ID | `your_username` |

| `password` | Your trading account password | `your_password` |

| `app_id` | Application ID for authentication | `simnow_client_test` |

| `auth_code` | Authentication code | `0000000000000000` |

### SimNow Environment

SimNow provides a free simulation environment for testing:

```python

# SimNow 7x24 ( penetrates front)

SIMNOW_TD_7x24 = "tcp://182.254.243.31:30001"
SIMNOW_MD_7x24 = "tcp://182.254.243.31:30011"

# SimNow Regular trading hours

SIMNOW_TD = "tcp://180.168.146.187:10130"
SIMNOW_MD = "tcp://180.168.146.187:10131"

# Common SimNow credentials

BROKER_ID = "9999"
APP_ID = "simnow_client_test"
AUTH_CODE = "0000000000000000"

```bash
To get SimNow credentials:

1. Visit [SimNow official website](<http://www.simnow.com.cn/)>
2. Register for a demo account
3. Use the provided broker ID, user ID, and password

## Data Feed Setup

### Basic Data Feed

```python
import backtrader as bt

# Create CTP store

store = bt.stores.CTPStore(
    td_front='tcp://182.254.243.31:30001',
    md_front='tcp://182.254.243.31:30011',
    broker_id='9999',
    user_id='your_id',
    password='your_password',
    app_id='simnow_client_test',
    auth_code='0000000000000000',
)

# Create data feed

data = store.getdata(
    dataname='rb2501.SHFE',  # instrument.exchange format
    timeframe=bt.TimeFrame.Minutes,
    compression=1,
)

cerebro = bt.Cerebro()
cerebro.adddata(data)

```bash

### Data Feed Parameters

```python
data = store.getdata(
    dataname='rb2501.SHFE',
    timeframe=bt.TimeFrame.Minutes,  # Minutes or Days
    compression=1,                    # Bar compression
    historical=False,                 # True = stop after backfill
    num_init_backfill=100,           # Number of historical bars to load
    tick_mode=False,                  # True = emit raw ticks
    backfill_retries=2,              # Retry attempts for backfill

)

```bash

### Multiple Instruments

```python

# Subscribe to multiple instruments

instruments = [
    'rb2501.SHFE',  # Rebar
    'hc2501.SHFE',  # Hot rolled coil
    'IF2502.CFFEX', # CSI 300 index

]

for symbol in instruments:
    data = store.getdata(dataname=symbol, timeframe=bt.TimeFrame.Minutes)
    cerebro.adddata(data)

```bash

## Broker Setup

### Basic Broker Configuration

```python
import backtrader as bt

cerebro = bt.Cerebro()

# Create store and set broker

store = bt.stores.CTPStore(
    td_front='tcp://182.254.243.31:30001',
    md_front='tcp://182.254.243.31:30011',
    broker_id='9999',
    user_id='your_id',
    password='your_password',
    app_id='simnow_client_test',
    auth_code='0000000000000000',
)

cerebro.setbroker(store.getbroker(
    use_positions=True,   # Use existing positions on start
    commission=1.0,       # Commission per contract

))

```bash

### Broker Parameters

| Parameter | Default | Description |

|-----------|---------|-------------|

| `use_positions` | `True` | Load existing positions on startup |

| `commission` | `0.0` | Commission per contract (absolute value) |

| `stop_slippage_ticks` | `0.0` | Max slippage for stop orders (0=market) |

## Order Management

### Order Types

```python
class MyStrategy(bt.Strategy):
    def next(self):

# Market order (uses AnyPrice in CTP)
        self.buy(size=1, exectype=bt.Order.Market)

# Limit order
        self.buy(size=1, price=3800.0, exectype=bt.Order.Limit)

# Stop order (triggers when price crosses stop price)
        self.sell(size=1, price=3750.0, exectype=bt.Order.Stop)

# Stop-limit order
        self.sell(size=1,
                 price=3750.0,    # Stop trigger price
                 plimit=3748.0,   # Limit price after trigger
                 exectype=bt.Order.StopLimit)

```bash

### Order Tracking

```python
class MyStrategy(bt.Strategy):
    def __init__(self):
        self.order = None

    def next(self):
        if self.order:
            return  # Wait for pending order

# Place order
        self.order = self.buy(size=1)

    def notify_order(self, order):
        """Called when order status changes."""
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status in [order.Completed]:
            if order.isbuy():
                self.log(f'BUY EXECUTED, Price: {order.executed.price:.2f}, '
                        f'Cost: {order.executed.value:.2f}, '
                        f'Comm: {order.executed.comm:.2f}')
            else:
                self.log(f'SELL EXECUTED, Price: {order.executed.price:.2f}, '
                        f'Cost: {order.executed.value:.2f}, '
                        f'Comm: {order.executed.comm:.2f}')

        elif order.status in [order.Canceled]:
            self.log('Order Canceled')
        elif order.status in [order.Rejected]:
            self.log('Order Rejected')

        self.order = None

```bash

### Order Cancellation

```python
class MyStrategy(bt.Strategy):
    def __init__(self):
        self.order = None
        self.cancel_after = 10  # bars

    def next(self):
        if self.order:
            self.cancel_after -= 1
            if self.cancel_after <= 0:
                self.cancel(self.order)
                self.order = None
            return

        self.order = self.buy(size=1)
        self.cancel_after = 10

```bash

## SHFE/INE Close Offset Handling

For SHFE and INE exchanges, CTP requires distinguishing between closing today's positions vs. yesterday's positions. The broker handles this automatically:

```python

# The broker automatically:

# 1. Tracks today's vs yesterday's positions

# 2. Uses CloseToday for closing positions opened today

# 3. Uses CloseYesterday for closing positions from prior days

# 4. Splits orders when closing mixed positions

# No special code needed - just place orders normally

self.buy(size=5)   # Opens 5 long positions

self.sell(size=3)  # Closes 3 (automatically uses CloseToday/CloseYesterday)

```bash

## Complete Live Trading Example

```python

# !/usr/bin/env python

"""CTP Live Trading Example"""

import backtrader as bt
import logging

# Enable debug logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class SimpleMAStrategy(bt.Strategy):
    """Simple moving average crossover strategy for CTP live trading."""

    params = (
        ('fast_period', 10),
        ('slow_period', 30),
        ('size', 1),
    )

    def __init__(self):
        self.fast_ma = bt.indicators.SMA(self.data.close, period=self.p.fast_period)
        self.slow_ma = bt.indicators.SMA(self.data.close, period=self.p.slow_period)
        self.crossover = bt.indicators.CrossOver(self.fast_ma, self.slow_ma)
        self.order = None

    def log(self, txt, dt=None):
        """Log strategy messages."""
        dt = dt or self.data.datetime[0]
        logger.info(f'{dt} {txt}')

    def notify_order(self, order):
        """Handle order status changes."""
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status in [order.Completed]:
            if order.isbuy():
                self.log(f'BUY EXECUTED, Price: {order.executed.price:.2f}, '
                        f'Size: {order.executed.size}')
            else:
                self.log(f'SELL EXECUTED, Price: {order.executed.price:.2f}, '
                        f'Size: {order.executed.size}')

        elif order.status in [order.Canceled]:
            self.log('Order Canceled')
        elif order.status in [order.Rejected]:
            self.log('Order Rejected - check margin and position limits')

        self.order = None

    def notify_trade(self, trade):
        """Handle trade completion."""
        if not trade.isclosed:
            return
        self.log(f'TRADE CLOSED, P&L: {trade.pnl:.2f}, Comm: {trade.commission:.2f}')

    def next(self):
        """Main strategy logic."""

# Wait for pending order
        if self.order:
            return

# Wait for indicators to be ready
        if len(self) < self.p.slow_period:
            return

# Check if we have a position
        if not self.position:

# No position - look for entry
            if self.crossover > 0:

# Fast MA crosses above slow MA - buy signal
                self.order = self.buy(size=self.p.size)
                self.log(f'BUY SIGNAL, Price: {self.data.close[0]:.2f}')
            elif self.crossover < 0:

# Fast MA crosses below slow MA - sell signal
                self.order = self.sell(size=self.p.size)
                self.log(f'SELL SIGNAL, Price: {self.data.close[0]:.2f}')
        else:

# Have position - look for exit on opposite crossover
            if self.position.size > 0 and self.crossover < 0:
                self.order = self.close(size=self.p.size)
                self.log(f'CLOSE LONG, Price: {self.data.close[0]:.2f}')
            elif self.position.size < 0 and self.crossover > 0:
                self.order = self.close(size=self.p.size)
                self.log(f'CLOSE SHORT, Price: {self.data.close[0]:.2f}')


def run_live():
    """Run CTP live trading."""

# CEP connection settings
    ctp_setting = {
        'td_front': 'tcp://182.254.243.31:30001',
        'md_front': 'tcp://182.254.243.31:30011',
        'broker_id': '9999',
        'user_id': 'your_id',
        'password': 'your_password',
        'app_id': 'simnow_client_test',
        'auth_code': '0000000000000000',
    }

# Create cerebro
    cerebro = bt.Cerebro()

# Create store
    store = bt.stores.CTPStore(**ctp_setting)

# Add data feed
    data = store.getdata(
        dataname='rb2505.SHFE',
        timeframe=bt.TimeFrame.Minutes,
        compression=1,
        num_init_backfill=100,
    )
    cerebro.adddata(data)

# Set broker
    cerebro.setbroker(store.getbroker(
        use_positions=True,
        commission=1.0,
    ))

# Add strategy
    cerebro.addstrategy(SimpleMAStrategy, fast_period=10, slow_period=30, size=1)

# Add analyzers
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')

# Run (live trading doesn't end - use Ctrl+C to stop)
    try:
        logger.info('Starting CTP live trading...')
        results = cerebro.run()
    except KeyboardInterrupt:
        logger.info('Stopped by user')

# Print results
    strat = results[0]
    logger.info(f'Final Value: {cerebro.broker.getvalue():.2f}')
    logger.info(f'DrawDown: {strat.analyzers.drawdown.get().max.drawdown:.2f}%')


if __name__ == '__main__':
    run_live()

```bash

## Risk Control

### Position Sizing

```python
class RiskControlStrategy(bt.Strategy):
    params = (
        ('max_pos', 5),           # Maximum contracts
        ('max_loss_pct', 0.02),   # 2% max loss
    )

    def __init__(self):
        self.entry_price = None

    def next(self):

# Check position size limit
        current_pos = abs(self.position.size)
        if current_pos >= self.p.max_pos:
            return  # Max position reached

# Calculate position size based on risk
        cash = self.broker.getcash()
        risk_amount = cash *self.p.max_loss_pct
        price = self.data.close[0]
        size = int(risk_amount / price)

# Limit size
        size = min(size, self.p.max_pos - current_pos)
        if size > 0:
            self.buy(size=size)

```bash

### Stop Loss

```python
class StopLossStrategy(bt.Strategy):
    params = (
        ('stop_loss_pct', 0.01),  # 1% stop loss
    )

    def __init__(self):
        self.entry_price = None

    def next(self):
        if not self.position:
            self.entry_price = self.data.close[0]
            self.buy(size=1)
        else:

# Check stop loss
            if self.position.size > 0:  # Long position
                stop_price = self.entry_price*(1 - self.p.stop_loss_pct)
                if self.data.close[0] <= stop_price:
                    self.log(f'Stop loss triggered at {self.data.close[0]:.2f}')
                    self.close()
            else:  # Short position
                stop_price = self.entry_price*(1 + self.p.stop_loss_pct)
                if self.data.close[0] >= stop_price:
                    self.log(f'Stop loss triggered at {self.data.close[0]:.2f}')
                    self.close()

```bash

## Troubleshooting

### Connection Issues

- *Problem**: Cannot connect to CTP front

```python

# Solution 1: Check network connectivity

import socket
def check_host(host, port):
    try:
        socket.create_connection((host, port), timeout=5)
        print(f"{host}:{port} is reachable")
    except OSError:
        print(f"{host}:{port} is NOT reachable")

check_host("182.254.243.31", 30001)  # TD front

check_host("182.254.243.31", 30011)  # MD front

```bash

- *Problem**: Login timeout

```python

# Solution: Increase wait time or check credentials

store = bt.stores.CTPStore(
    td_front='tcp://182.254.243.31:30001',
    md_front='tcp://182.254.243.31:30011',
    broker_id='9999',
    user_id='your_id',
    password='your_password',
    app_id='simnow_client_test',
    auth_code='0000000000000000',
)

# Check connection status

if store.is_connected:
    print("CTP connected successfully")
else:
    print("CTP connection failed - check credentials")

```bash

### Order Rejection

- *Problem**: Orders are rejected

Common causes:

- Insufficient margin
- Position limits exceeded
- Invalid instrument ID
- Market closed (trading hours)
- Price outside limit range

```python

# Enable logging to see rejection reasons

logging.basicConfig(level=logging.DEBUG)

# Check account balance before ordering

cash = cerebro.broker.getcash()
print(f"Available cash: {cash}")

# Check if market is open

def is_market_open():
    """Simple check for day session hours."""
    now = datetime.now().time()
    morning_start = time(9, 0)
    morning_end = time(11, 30)
    afternoon_start = time(13, 30)
    afternoon_end = time(15, 0)
    return (morning_start <= now <= morning_end or
            afternoon_start <= now <= afternoon_end)

```bash

### No Data Received

- *Problem**: Data feed receives no ticks

```python

# Solution 1: Check instrument ID is correct

# Common format: symbol + month + exchange

# Examples: rb2505.SHFE, m2505.DCE, SR505.CZCE

# Solution 2: Verify subscription

data = store.getdata(dataname='rb2505.SHFE')

# The store automatically subscribes via data.start()

# Solution 3: Check backfill is working

data = store.getdata(
    dataname='rb2505.SHFE',
    num_init_backfill=100,  # Load historical data
    historical=False,       # Continue to live after backfill

)

```bash

### Memory Issues

- *Problem**: Memory grows over time

The CTP implementation uses bounded queues to prevent memory overflow:

```python

# Queues are automatically bounded to 10000 items

# Old ticks are discarded when queue is full

# Monitor memory usage

import psutil
import os

process = psutil.Process(os.getpid())
print(f"Memory usage: {process.memory_info().rss / 1024 / 1024:.2f} MB")

```bash

## Trading Hours Reference

| Exchange | Day Session | Night Session |

|----------|-------------|---------------|

| SHFE/INE | 09:00-10:15, 10:30-11:30, 13:30-15:00 | 21:00-23:00, 23:00-02:30 (next day) |

| DCE | 09:00-10:15, 10:30-11:30, 13:30-15:00 | 21:00-23:00 |

| CZCE | 09:00-10:15, 10:30-11:30, 13:30-15:00 | 21:00-23:00 |

| CFFEX | 09:15-11:30, 13:00-15:15 | - |

- Note: Trading hours may vary by product and exchange announcements.*

## Next Steps

- [Data Feeds](data-feeds.md) - More data feed options
- [Strategies](strategies.md) - Strategy development patterns
- [Analyzers](analyzers.md) - Performance analysis tools
- [Plotting](plotting.md) - Visualize live trading results
