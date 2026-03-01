# Signal, Timer, and Store API Reference

This document provides a comprehensive reference for three important Backtrader APIs:

1. **Signal API**- Declarative trading based on signal indicators

2.**Timer API**- Time-based event scheduling during backtesting
3.**Store API** - External data source and broker connection management

- --

## Signal API

The Signal API provides a declarative approach to trading where decisions are driven by signal indicators rather than explicit order placement logic. Signals are numeric values that indicate when to enter or exit positions.

### Signal Types

The following signal type constants are defined in `backtrader.signal`:

| Constant | Value | Description |

|----------|-------|-------------|

| `SIGNAL_NONE` | 0 | No signal |

| `SIGNAL_LONGSHORT` | 1 | Both long and short signals from this indicator |

| `SIGNAL_LONG` | 2 | Long entry signals (positive = long, negative = exit long) |

| `SIGNAL_LONG_INV` | 3 | Inverted long signals |

| `SIGNAL_LONG_ANY` | 4 | Any non-zero value is a long signal |

| `SIGNAL_SHORT` | 5 | Short entry signals (negative = short, positive = exit short) |

| `SIGNAL_SHORT_INV` | 6 | Inverted short signals |

| `SIGNAL_SHORT_ANY` | 7 | Any non-zero value is a short signal |

| `SIGNAL_LONGEXIT` | 8 | Long exit signals (negative = exit long) |

| `SIGNAL_LONGEXIT_INV` | 9 | Inverted long exit signals |

| `SIGNAL_LONGEXIT_ANY` | 10 | Any non-zero value exits long |

| `SIGNAL_SHORTEXIT` | 11 | Short exit signals (positive = exit short) |

| `SIGNAL_SHORTEXIT_INV` | 12 | Inverted short exit signals |

| `SIGNAL_SHORTEXIT_ANY` | 13 | Any non-zero value exits short |

### Signal Class

```python
class backtrader.Signal(data)

```bash
The `Signal` class wraps a data line to provide trading signal values. It inherits from `Indicator` and exposes a single signal line.

- *Example: Creating a Signal from an indicator**

```python
import backtrader as bt

class MyStrategy(bt.SignalStrategy):
    def __init__(self):

# Create signals from indicator crossovers
        sma_fast = bt.indicators.SMA(period=10)
        sma_slow = bt.indicators.SMA(period=30)

# Add long signal when fast SMA crosses above slow SMA
        self.signal_add(bt.SIGNAL_LONG, bt.ind.CrossOver(sma_fast, sma_slow))

```bash

### SignalStrategy Class

```python
class backtrader.SignalStrategy

```bash
`SignalStrategy` is a specialized `Strategy` subclass that automatically executes trades based on signal indicators.

#### Parameters

| Parameter | Default | Description |

|-----------|---------|-------------|

| `signals` | `[]` | List of signal definitions (typically via `cerebro.add_signal()`) |

| `_accumulate` | `False` | Allow entering the market even if already in a position |

| `_concurrent` | `False` | Allow multiple orders at the same time |

#### Methods

##### signal_add()

```python
def signal_add(self, sigtype, signal)

```bash
Add a signal indicator to the strategy.

- *Parameters:**
- `sigtype`: Signal type constant (e.g., `SIGNAL_LONG`, `SIGNAL_SHORT`)
- `signal`: Signal indicator instance

- *Example:**

```python
class MySignalStrategy(bt.SignalStrategy):
    def __init__(self):
        super().__init__()

# Create a custom signal
        rsi = bt.indicators.RSI(period=14)

# Create signal condition: RSI < 30 = long signal
        rsi_signal = (30 - rsi)  # Positive when RSI < 30

        self.signal_add(bt.SIGNAL_LONG, rsi_signal)

```bash

#### Signal Processing Logic

The `SignalStrategy` evaluates signals in the following order:

1. **Exit signals**are checked first
   - `LONGEXIT`: Negative values trigger long position exit
   - `SHORTEXIT`: Positive values trigger short position exit

2.**Entry signals**are checked after exits

   - `LONGSHORT`: Both long and short indications from sign
   - `LONG`: Positive = long, Negative = close long
   - `SHORT`: Negative = short, Positive = close short

3.**Order execution**

   - Orders are placed as Market orders
   - Validity is Good-Until-Canceled

#### Complete Signal Strategy Example

```python
import backtrader as bt

class MultiSignalStrategy(bt.SignalStrategy):
    """Strategy using multiple signal types."""

    def __init__(self):
        super().__init__()

# Indicators
        sma_fast = bt.indicators.SMA(period=10)
        sma_slow = bt.indicators.SMA(period=30)
        rsi = bt.indicators.RSI(period=14)

# Long entry: Fast SMA crosses above slow SMA
        long_signal = bt.ind.CrossOver(sma_fast, sma_slow)
        self.signal_add(bt.SIGNAL_LONG, long_signal)

# Short entry: Fast SMA crosses below slow SMA
        short_signal = bt.ind.CrossOver(sma_slow, sma_fast)
        self.signal_add(bt.SIGNAL_SHORT, short_signal)

# Long exit: RSI over 70
        long_exit = (rsi - 70)  # Positive when RSI > 70
        self.signal_add(bt.SIGNAL_LONGEXIT, long_exit)

# Short exit: RSI under 30
        short_exit = (30 - rsi)  # Positive when RSI < 30
        self.signal_add(bt.SIGNAL_SHORTEXIT, short_exit)

# Usage

cerebro = bt.Cerebro()
data = bt.feeds.YahooFinanceData(dataname='AAPL', fromdate=datetime(2020, 1, 1))
cerebro.adddata(data)
cerebro.addstrategy(MultiSignalStrategy)
results = cerebro.run()

```bash

### Using cerebro.add_signal()

```python
cerebro.add_signal(sigtype, sigcls, *sigargs, **sigkwargs)

```bash
Add a signal to the strategy through cerebro.

- *Parameters:**
- `sigtype`: Signal type constant
- `sigcls`: Signal class (usually `bt.Signal` or a subclass)
- `*sigargs`: Arguments to pass to signal class
- `**sigkwargs`: Keyword arguments to pass to signal class

- *Example:**

```python

# Add a simple price-based signal

cerebro.add_signal(
    bt.SIGNAL_LONGSHORT,
    bt.Signal,
    data  # Use data's close price as signal

)

# With a custom signal indicator

cerebro.add_signal(
    bt.SIGNAL_LONG,
    bt.ind.CrossOver,
    bt.indicators.SMA(period=10),
    bt.indicators.SMA(period=30)
)

```bash

- --

## Timer API

The Timer API allows scheduling time-based notifications during backtesting. Timers can trigger at specific times of day, session boundaries, or at repeating intervals.

### Timer Constants

| Constant | Value | Description |

|----------|-------|-------------|

| `Timer.SESSION_TIME` | 0 | Timer triggers at a specific time |

| `Timer.SESSION_START` | 1 | Timer triggers at session start |

| `Timer.SESSION_END` | 2 | Timer triggers at session end |

### Timer Class

```python
class backtrader.Timer(**kwargs)

```bash

- *Parameters:**

| Parameter | Default | Description |

|-----------|---------|-------------|

| `tid` | `None` | Timer ID for identification |

| `owner` | `None` | Owner object of the timer |

| `strats` | `False` | Whether to notify strategies |

| `when` | `None` | When to trigger (time, SESSION_START, or SESSION_END) |

| `offset` | `timedelta()` | Time offset for the trigger |

| `repeat` | `timedelta()` | Repeat interval for recurring timers |

| `weekdays` | `[]` | List of weekdays (0=Monday, 6=Sunday) |

| `weekcarry` | `False` | Carry over to next weekday if missed |

| `monthdays` | `[]` | List of month days when timer is active |

| `monthcarry` | `True` | Carry over to next month day if missed |

| `allow` | `None` | Callback function to allow/disallow on specific dates |

| `tzdata` | `None` | Timezone data for the timer |

| `cheat` | `False` | Whether timer can execute before broker |

### Strategy Timer Methods

#### add_timer()

```python
def add_timer(self, when, offset=timedelta(), repeat=timedelta(),
              weekdays=[], weekcarry=False, monthdays=[], monthcarry=True,
              allow=None, tzdata=None, cheat=False, *args, **kwargs)

```bash
Add a timer to the strategy.

- *Parameters:**
- `when`: When to trigger (`datetime.time`, `SESSION_START`, or `SESSION_END`)
- `offset`: Time offset from the trigger time
- `repeat`: Repeat interval (e.g., `timedelta(minutes=5)`)
- `weekdays`: List of weekdays when timer is active
- `weekcarry`: Whether to carry over if weekday is missed
- `monthdays`: List of month days when timer is active
- `monthcarry`: Whether to carry over if monthday is missed
- `allow`: Callback function `allow(date) -> bool` for custom filtering
- `tzdata`: Timezone for the timer
- `cheat`: If True, timer can execute before broker
- `*args`, `**kwargs`: Additional arguments passed to `notify_timer`

- *Returns:** The created timer instance

#### notify_timer()

```python
def notify_timer(self, timer, when, *args, **kwargs)

```bash
Override this method to receive timer notifications.

- *Parameters:**
- `timer`: The timer instance that triggered
- `when`: The scheduled time when the timer was triggered
- `*args`, `**kwargs`: Additional arguments from `add_timer`

### Timer Examples

#### Example 1: Session Start Timer

```python
import backtrader as bt
from datetime import time

class SessionStartStrategy(bt.Strategy):
    """Execute actions at market open."""

    def __init__(self):
        self.order_count = 0

# Timer that triggers at session start
        self.add_timer(
            when=bt.Timer.SESSION_START,
            weekdays=[0, 1, 2, 3, 4],  # Monday to Friday
        )

    def notify_timer(self, timer, when, *args, **kwargs):
        """Called at session start."""
        self.order_count += 1

# Could place orders, update indicators, etc.
        print(f'Session started at {when}')

    def next(self):

# Regular strategy logic
        pass

```bash

#### Example 2: Specific Time Timer

```python
class TimeBasedStrategy(bt.Strategy):
    """Execute at specific time each day."""

    def __init__(self):

# Timer at 9:45 AM every trading day
        self.add_timer(
            when=time(9, 45),
            weekdays=[0, 1, 2, 3, 4],
        )

    def notify_timer(self, timer, when, *args, **kwargs):
        print(f'Timer triggered at {when}')

# Example: Cancel all pending orders at end of day
        for order in self.broker.orders:
            if order.status == order.Submitted:
                self.cancel(order)

```bash

#### Example 3: Repeating Timer

```python
class RepeatingTimerStrategy(bt.Strategy):
    """Execute every N minutes."""

    def __init__(self):
        self.execution_count = 0

# Timer that repeats every 30 minutes
        self.add_timer(
            when=bt.Timer.SESSION_START,
            repeat=timedelta(minutes=30),
        )

    def notify_timer(self, timer, when, *args, **kwargs):
        self.execution_count += 1
        print(f'Repeating timer #{self.execution_count} at {when}')

```bash

#### Example 4: Monthday Timer

```python
class MonthlyRebalanceStrategy(bt.Strategy):
    """Rebalance portfolio on specific days."""

    def __init__(self):

# Rebalance on 1st and 15th of each month
        self.add_timer(
            when=bt.Timer.SESSION_START,
            monthdays=[1, 15],
            monthcarry=True,  # If 1st is weekend, use next trading day
        )

    def notify_timer(self, timer, when, *args, **kwargs):
        print(f'Monthly rebalance at {when}')

# Rebalancing logic here

```bash

#### Example 5: Custom Allow Function

```python
class ConditionalTimerStrategy(bt.Strategy):
    """Timer with custom date filtering."""

    def __init__(self):

# Only trigger on weekdays that are also end of month
        self.add_timer(
            when=time(15, 0),  # 3 PM
            allow=self._is_eom,
        )

    def _is_eom(self, date):
        """Check if date is end of month."""
        next_day = date + timedelta(days=1)
        return date.month != next_day.month

    def notify_timer(self, timer, when, *args, **kwargs):
        print(f'EOM timer triggered at {when}')

```bash

- --

## Store API

The Store API provides a unified interface for connecting to external data sources and brokers. Stores manage connections, handle authentication, and provide data feeds and broker instances.

### Store Base Class

```python
class backtrader.Store

```bash
Base class for all Store implementations. Stores typically implement the singleton pattern to share connections between data feeds and brokers.

#### Class Attributes

| Attribute | Description |

|-----------|-------------|

| `BrokerCls` | Broker class associated with this store |

| `DataCls` | Data feed class associated with this store |

| `_started` | Whether the store has been started |

| `params` | Tuple of parameter definitions |

#### Methods

##### getdata()

```python
def getdata(self, *args, **kwargs)

```bash
Create a data feed associated with this store.

- *Returns:** A data feed instance connected to this store

##### getbroker()

```python
@classmethod
def getbroker(cls, *args, **kwargs)

```bash
Create a broker associated with this store.

- *Returns:** A broker instance connected to this store

##### start()

```python
def start(self, data=None, broker=None)

```bash
Start the store and initialize connections.

##### stop()

```python
def stop(self)

```bash
Stop the store and clean up resources.

##### put_notification()

```python
def put_notification(self, msg, *args, **kwargs)

```bash
Add a message to the notification queue.

##### get_notifications()

```python
def get_notifications(self)

```bash
Return pending store notifications.

### Available Store Implementations

#### CCXTStore - Cryptocurrency Exchanges

```python
import backtrader as bt

# Create store for cryptocurrency exchange

store = bt.stores.CCXTStore(
    exchange='binance',
    currency='USDT',
    config={
        'apiKey': 'your_api_key',
        'secret': 'your_secret',
        'enableRateLimit': True,
    },
    retries=3,
    sandbox=False,
)

# Get data feed

data = store.getdata(
    dataname='BTC/USDT',
    timeframe=bt.TimeFrame.Minutes,
    compression=1,
)

# Get broker

broker = store.getbroker()
cerebro.setbroker(broker)

```bash

- *CCXTStore Parameters:**

| Parameter | Description |

|-----------|-------------|

| `exchange` | Exchange ID (e.g., 'binance', 'okx') |

| `currency` | Base currency for balance |

| `config` | Exchange configuration dict with API keys |

| `retries` | Number of retry attempts |

| `debug` | Enable debug output |

| `sandbox` | Use exchange sandbox/testnet |

| `use_rate_limiter` | Enable intelligent rate limiting |

| `use_connection_manager` | Enable auto-reconnect |

- *CCXTStore Methods:**

```python

# Get wallet balance

balance = store.get_wallet_balance(params=None)

# Get OHLCV data

ohlcv = store.fetch_ohlcv(
    symbol='BTC/USDT',
    timeframe='1h',
    since=timestamp,
    limit=100
)

# Create order

order = store.create_order(
    symbol='BTC/USDT',
    order_type='limit',
    side='buy',
    amount=0.001,
    price=50000,
    params={}
)

# Cancel order

store.cancel_order(order_id, 'BTC/USDT')

# Check connection

if store.is_connected():
    print("Connected to exchange")

```bash

#### CTPStore - China Futures Market

```python
import backtrader as bt

# Create CTP store for China futures

store = bt.stores.CTPStore(
    ctp_setting={
        'td_front': 'tcp://180.168.146.187:10130',
        'md_front': 'tcp://180.168.146.187:10131',
        'broker_id': '9999',
        'user_id': 'your_id',
        'password': 'your_password',
        'app_id': 'simnow_client_test',
        'auth_code': '0000000000000000',
    }
)

# Get data feed

data = store.getdata(
    dataname='rb2501.SHFE',
    timeframe=bt.TimeFrame.Minutes,
)

# Get broker

broker = store.getbroker()

```bash

- *CTPStore Features:**

- Manages both trader and market data connections
- Handles order submission and cancellation
- Provides account and position queries
- Distributes tick data to data feeds
- Auto-reconnect support with callbacks

- *CTPStore Methods:**

```python

# Send order

order_ref = store.send_order(
    symbol='rb2501.SHFE',
    direction='0',  # 0=Buy, 1=Sell
    offset='0',     # 0=Open, 1=Close, 3=CloseToday
    price=3500.0,
    volume=1
)

# Cancel order

store.cancel_order(
    symbol='rb2501.SHFE',
    order_ref=order_ref,
    front_id=front_id,
    session_id=session_id
)

# Get balance

store.get_balance()
cash = store.get_cash()
value = store.get_value()

# Get positions

positions = store.get_positions()

# Register callbacks

store.on_disconnect(lambda reason: print(f'Disconnected: {reason}'))
store.on_reconnect(lambda: print('Reconnected'))

# Check connection

if store.is_connected:
    print("Connected to CTP")

```bash

#### IBStore - Interactive Brokers

```python
import backtrader as bt

# Create IB store

store = bt.stores.IBStore(
    host='127.0.0.1',
    port=7497,  # 7496 for production, 7497 for paper trading
    clientId=1,
    notifyall=False,
    reconnect=3,
    timeout=3.0,
)

# Get data feed

data = store.getdata(
    dataname='AAPL',
    what='rtbar',  # 'rtbar' for real-time bars

)

# Get broker

broker = store.getbroker()

```bash

- *IBStore Parameters:**

| Parameter | Default | Description |

|-----------|---------|-------------|

| `host` | '127.0.0.1' | IB TWS/Gateway host |

| `port` | 7496 | Connection port (7497 for paper) |

| `clientId` | None | Client ID (random if None) |

| `notifyall` | False | Notify all messages or just errors |

| `reconnect` | 3 | Reconnection attempts (-1 for infinite) |

| `timeout` | 3.0 | Connection timeout |

### Store Integration Patterns

#### Pattern 1: Single Store, Multiple Feeds

```python
import backtrader as bt

# Create one store for connection sharing

store = bt.stores.CCXTStore(
    exchange='binance',
    currency='USDT',
    config={'apiKey': 'xxx', 'secret': 'xxx'}
)

cerebro = bt.Cerebro()

# Add multiple data feeds using the same store connection

cerebro.adddata(store.getdata(dataname='BTC/USDT'))
cerebro.adddata(store.getdata(dataname='ETH/USDT'))
cerebro.adddata(store.getdata(dataname='BNB/USDT'))

# Set broker from store

cerebro.setbroker(store.getbroker())

results = cerebro.run()

```bash

#### Pattern 2: Store with Custom Data Feed

```python
import backtrader as bt

class CustomCCXTFeed(bt.feeds.CCXTFeed):
    """Custom data feed with additional processing."""

    params = (
        ('drop_new', True),  # Drop incomplete bars
        ('historical', True),  # Fetch historical data
    )

# Use store with custom feed

store = bt.stores.CCXTStore(
    exchange='binance',
    currency='USDT',
    config={'apiKey': 'xxx', 'secret': 'xxx'}
)

data = CustomCCXTFeed(
    store=store,
    dataname='BTC/USDT',
    timeframe=bt.TimeFrame.Minutes,
    compression=15
)

```bash

#### Pattern 3: Store Notifications

```python
import backtrader as bt

class NotificationStrategy(bt.Strategy):
    """Strategy that responds to store notifications."""

    def notify_store(self, msg, *args, **kwargs):
        """Handle store notifications."""
        if msg == 'DISCONNECTED':
            print('Store disconnected!')

# Take action: close positions, stop trading, etc.
        elif msg == 'CONNECTED':
            print('Store reconnected!')
        elif msg == 'ERROR':
            print(f'Store error: {args}')

# Store will send notifications to strategy

store = bt.stores.CCXTStore(
    exchange='binance',
    currency='USDT',
    config={'apiKey': 'xxx', 'secret': 'xxx'}
)

cerebro = bt.Cerebro()
cerebro.addstrategy(NotificationStrategy)
cerebro.setbroker(store.getbroker())

```bash

#### Pattern 4: Store Connection Monitoring

```python
import backtrader as bt

class MonitoredStrategy(bt.Strategy):
    """Strategy with connection monitoring."""

    def __init__(self):
        self.store = self.broker.store
        self._setup_monitoring()

    def _setup_monitoring(self):
        """Set up connection monitoring callbacks."""
        if hasattr(self.store, 'on_disconnect'):
            self.store.on_disconnect(self._on_disconnect)
        if hasattr(self.store, 'on_reconnect'):
            self.store.on_reconnect(self._on_reconnect)

    def _on_disconnect(self, reason):
        print(f'Connection lost: {reason}')

    def _on_reconnect(self):
        print('Connection restored')

    def next(self):

# Check connection before trading
        if hasattr(self.store, 'is_connected'):
            if not self.store.is_connected:
                return  # Skip trading logic

# Normal trading logic

```bash

### Store Best Practices

1. **Use Single Store Per Exchange**
   - Create one store instance per exchange/broker
   - Share the store between data feeds and brokers
   - This reduces connection overhead and ensures consistent state

1. **Handle Reconnection**
   - Implement disconnect/reconnect callbacks
   - Pause trading during disconnection
   - Resynchronize state after reconnection

1. **Rate Limiting**
   - Use built-in rate limiters where available
   - Respect exchange rate limits
   - Implement retry logic with exponential backoff

1. **Error Handling**
   - Implement `notify_store()` in strategies
   - Log errors for debugging
   - Graceful degradation when services are unavailable

1. **Resource Cleanup**
   - Call `store.stop()` when done
   - Use context managers where applicable
   - Ensure threads are properly terminated

- --

## Summary

| API | Purpose | Key Classes |

|-----|---------|-------------|

| **Signal**| Declarative trading based on indicators | `Signal`, `SignalStrategy` |

|**Timer**| Time-based event scheduling | `Timer`, `Strategy.add_timer()` |

|**Store** | External data/broker connections | `Store`, `CCXTStore`, `CTPStore`, `IBStore` |

These APIs work together to create sophisticated trading systems:

```python
import backtrader as bt

class AdvancedStrategy(bt.SignalStrategy):
    """Combine signals, timers, and store connections."""

    def __init__(self):
        super().__init__()

# Signal-based entry
        sma_cross = bt.ind.CrossOver(
            bt.indicators.SMA(period=10),
            bt.indicators.SMA(period=30)
        )
        self.signal_add(bt.SIGNAL_LONGSHORT, sma_cross)

# Time-based exits
        self.add_timer(
            when=bt.Timer.SESSION_END,
            weekdays=[0, 1, 2, 3, 4],
        )

# Store reference for live trading
        self.store = self.broker.store if hasattr(self.broker, 'store') else None

    def notify_timer(self, timer, when, *args, **kwargs):
        """Exit positions at end of day."""
        self.close()

    def notify_store(self, msg, *args, **kwargs):
        """Handle store notifications."""
        if msg == 'DISCONNECTED':
            print('Warning: Disconnected from exchange')

```bash
