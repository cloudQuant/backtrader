# CCXT Live Trading Guide

> Updated: 2026-02-24

This guide explains how to use Backtrader + CCXT for cryptocurrency live trading.

---

## 1. Quick Start

### 1.1 Install Dependencies

```bash
pip install ccxt        # REST API
pip install ccxtpro     # WebSocket (optional but recommended)
```

### 1.2 Configure Exchange

**Method A: Direct Parameters**

```python
import backtrader as bt

store = bt.stores.CCXTStore(
    exchange='binance',
    currency='USDT',
    config={
        'apiKey': 'your_api_key',
        'secret': 'your_secret',
        'enableRateLimit': True,
    }
)
```

**Method B: Using .env File (Recommended)**

Create a `.env` file:

```env
EXCHANGE_ID=binance
EXCHANGE_API_KEY=your_api_key
EXCHANGE_SECRET=your_secret
EXCHANGE_CURRENCY=USDT
```

```python
from backtrader.ccxt.config_helper import load_exchange_config

config = load_exchange_config()
store = bt.stores.CCXTStore(**config)
```

### 1.3 Minimal Live Trading Example

```python
import backtrader as bt

class SimpleStrategy(bt.Strategy):
    params = (('period', 20),)

    def __init__(self):
        super().__init__()
        self.sma = bt.indicators.SMA(self.data, period=self.p.period)

    def next(self):
        if self.data.close[0] > self.sma[0] and not self.position:
            self.buy(size=0.001)
        elif self.data.close[0] < self.sma[0] and self.position:
            self.sell(size=0.001)

# Create engine
cerebro = bt.Cerebro()

# Create Store
store = bt.stores.CCXTStore(
    exchange='binance',
    currency='USDT',
    config={
        'apiKey': 'YOUR_KEY',
        'secret': 'YOUR_SECRET',
        'enableRateLimit': True,
    }
)

# Add data feed (REST polling)
data = store.getdata(
    dataname='BTC/USDT',
    timeframe=bt.TimeFrame.Minutes,
    compression=15,
    ohlcv_limit=100,
    drop_newest=True,
)
cerebro.adddata(data)

# Set Broker
broker = store.getbroker()
cerebro.setbroker(broker)

# Add strategy
cerebro.addstrategy(SimpleStrategy)

# Run
cerebro.run()
```

---

## 2. Data Feed Configuration

### 2.1 REST Polling Mode (Default)

```python
data = store.getdata(
    dataname='BTC/USDT',
    timeframe=bt.TimeFrame.Minutes,
    compression=15,
    ohlcv_limit=100,       # Number of bars per request
    drop_newest=True,       # Drop incomplete newest bar
    historical=False,       # False = live mode
    backfill_start=True,    # Backfill historical data on start
)
```

### 2.2 WebSocket Mode (Recommended, Low Latency)

Requires `ccxtpro`:

```python
data = store.getdata(
    dataname='BTC/USDT',
    timeframe=bt.TimeFrame.Minutes,
    compression=1,
    use_websocket=True,                # Enable WebSocket
    ws_reconnect_delay=5.0,            # Reconnect delay (seconds)
    ws_max_reconnect_delay=60.0,       # Max reconnect delay
    ws_health_check_interval=30.0,     # Health check interval
    backfill_start=True,
)
```

**WebSocket Features**:
- Auto-reconnect (exponential backoff: 5s → 10s → 20s → ... → 60s)
- Automatic fallback to REST polling on disconnect
- Auto data backfill on reconnect (triggered when gap > 60s)
- Stale connection detection

### 2.3 Historical Data Mode

```python
from datetime import datetime

data = store.getdata(
    dataname='BTC/USDT',
    timeframe=bt.TimeFrame.Minutes,
    compression=60,
    historical=True,                    # Fetch historical data only
    fromdate=datetime(2025, 1, 1),
    todate=datetime(2025, 12, 31),
    ohlcv_limit=500,
)
```

---

## 3. Broker Configuration

### 3.1 Basic Configuration

```python
broker = store.getbroker(
    debug=False,                        # Debug output
    use_threaded_order_manager=True,    # Background order checking (recommended)
    max_retries=3,                      # API retry count
    retry_delay=1.0,                    # Base retry delay (seconds)
)
cerebro.setbroker(broker)
```

### 3.2 ThreadedOrderManager

When enabled, order status checks run in a background thread without blocking the main strategy loop:

```python
broker = store.getbroker(
    use_threaded_order_manager=True,    # Enable
)
```

**Advantages**:
- Strategy `next()` is not blocked by API latency
- Order updates delivered via thread-safe queue
- Auto-cleanup of completed/canceled orders

### 3.3 Error Handling

The broker has comprehensive built-in error handling:

| Scenario | Behavior |
|----------|----------|
| Network timeout | Auto-retry (up to 3 times, exponential backoff) |
| Exchange unavailable | Auto-retry |
| Insufficient balance | Reject order, notify strategy |
| Order not found | Mark as canceled, remove from tracking |
| Exchange disconnected | Skip API calls, wait for reconnect |
| ≥ 10 consecutive failures | Polling interval backs off from 3s to 30s |

**Handling order notifications in your strategy**:

```python
class MyStrategy(bt.Strategy):
    def notify_order(self, order):
        if order.status in [order.Completed]:
            print(f'Order completed: {order.executed.price}')
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            print(f'Order failed: {order.getstatusname()}')
```

---

## 4. Exchange-Specific Configuration

### 4.1 Using ExchangeConfig

```python
from backtrader.ccxt.config import ExchangeConfig

# Get exchange default parameters
params = ExchangeConfig.get_params('binance')
# {'rateLimit': 1200, 'enableRateLimit': True, ...}

# Get fee structure
fees = ExchangeConfig.get_fees('binance')
# {'maker': 0.001, 'taker': 0.001}

# Merge user config with defaults
config = ExchangeConfig.merge_config('okx', {
    'apiKey': 'your_key',
    'secret': 'your_secret',
    'password': 'your_passphrase',
})
```

### 4.2 Supported Exchanges

| Exchange | exchange_id | Special Configuration |
|----------|-------------|----------------------|
| Binance | `binance` | Futures require `defaultType: 'future'` |
| OKX | `okx` | Requires `password` (passphrase) |
| Bybit | `bybit` | Futures require `defaultType: 'linear'` |
| Bitget | `bitget` | Requires `password` |
| Gate.io | `gate` | — |
| Huobi | `huobi` | — |

### 4.3 Futures Trading Example (Binance)

```python
store = bt.stores.CCXTStore(
    exchange='binance',
    currency='USDT',
    config={
        'apiKey': 'your_key',
        'secret': 'your_secret',
        'enableRateLimit': True,
        'options': {
            'defaultType': 'future',    # Futures mode
        },
    }
)
```

---

## 5. Rate Limiting

### 5.1 Automatic Rate Limiting

CCXTStore automatically integrates RateLimiter:

```python
# Default: auto-configured based on exchange settings
store = bt.stores.CCXTStore(exchange='binance', ...)

# Custom RPM (requests per minute)
from backtrader.ccxt.ratelimit import RateLimiter
limiter = RateLimiter(requests_per_minute=600)
```

### 5.2 Adaptive Rate Limiting

```python
from backtrader.ccxt.ratelimit import AdaptiveRateLimiter

limiter = AdaptiveRateLimiter(
    initial_rpm=1200,    # Initial RPM
    min_rpm=60,          # Minimum RPM (when rate-limited)
    max_rpm=2400,        # Maximum RPM (gradually increases when no errors)
)
```

---

## 6. Connection Management

### 6.1 ConnectionManager

Automatically manages connection health and reconnection:

```python
from backtrader.ccxt.connection import ConnectionManager

# Usually no need to create manually; CCXTStore manages it
# But you can register callbacks:
manager = store._connection_manager  # If available

manager.on_disconnect(lambda: print("Exchange disconnected!"))
manager.on_reconnect(lambda: print("Reconnected"))
```

### 6.2 Reconnection Mechanism

```
Disconnect detected (health check failure)
    │
    ├── Trigger disconnect callback
    │
    └── Reconnection loop (exponential backoff):
        ├── Attempt 1: wait 5s
        ├── Attempt 2: wait 10s
        ├── Attempt 3: wait 20s
        ├── ...
        └── Maximum: wait 60s
            │
            └── Reconnection successful
                ├── Trigger reconnect callback
                └── Backfill missing data
```

---

## 7. Complete Live Trading Template

```python
import backtrader as bt
from datetime import datetime

class LiveStrategy(bt.Strategy):
    params = (
        ('fast', 10),
        ('slow', 30),
        ('stake', 0.001),
    )

    def __init__(self):
        super().__init__()
        self.fast_sma = bt.indicators.SMA(self.data, period=self.p.fast)
        self.slow_sma = bt.indicators.SMA(self.data, period=self.p.slow)
        self.crossover = bt.indicators.CrossOver(self.fast_sma, self.slow_sma)
        self.order = None

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status in [order.Completed]:
            if order.isbuy():
                print(f'[BUY] Price: {order.executed.price:.2f}, '
                      f'Size: {order.executed.size:.6f}')
            else:
                print(f'[SELL] Price: {order.executed.price:.2f}, '
                      f'Size: {order.executed.size:.6f}')
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            print(f'[ORDER FAILED] {order.getstatusname()}')
        self.order = None

    def next(self):
        if self.order:
            return

        if not self.position:
            if self.crossover > 0:
                self.order = self.buy(size=self.p.stake)
        else:
            if self.crossover < 0:
                self.order = self.sell(size=self.p.stake)


# === Configuration ===
cerebro = bt.Cerebro()

store = bt.stores.CCXTStore(
    exchange='binance',
    currency='USDT',
    config={
        'apiKey': 'YOUR_KEY',
        'secret': 'YOUR_SECRET',
        'enableRateLimit': True,
    }
)

# WebSocket data feed
data = store.getdata(
    dataname='BTC/USDT',
    timeframe=bt.TimeFrame.Minutes,
    compression=5,
    use_websocket=True,
    backfill_start=True,
    ohlcv_limit=100,
    drop_newest=True,
)
cerebro.adddata(data)

# Broker (with background order checking)
broker = store.getbroker(
    use_threaded_order_manager=True,
    max_retries=3,
)
cerebro.setbroker(broker)

# Strategy
cerebro.addstrategy(LiveStrategy)

# Run
print('Starting live trading...')
cerebro.run()
```

---

## 8. FAQ

### Q: What if WebSocket connection fails?

Make sure `ccxtpro` is installed:

```bash
pip install ccxtpro
```

If the exchange doesn't support WebSocket, the system will automatically fall back to REST polling.

### Q: How do I view API call logs?

```python
broker = store.getbroker(debug=True)
data = store.getdata(..., debug=True)
```

### Q: Order stuck in Submitted status?

Possible causes:

1. Price too far from market (limit order)
2. Exchange API delay
3. Network issue preventing status update

Solution: Enable `use_threaded_order_manager=True` for continuous background status checking.

### Q: How do I trade multiple symbols?

```python
data_btc = store.getdata(dataname='BTC/USDT', ...)
data_eth = store.getdata(dataname='ETH/USDT', ...)
cerebro.adddata(data_btc)
cerebro.adddata(data_eth)
```

### Q: How do I handle funding rates?

Use `ccxtfeed_funding.py`:

```python
from backtrader.feeds.ccxtfeed_funding import CCXTFeedWithFunding

data = CCXTFeedWithFunding(
    store=store,
    dataname='BTC/USDT',
    use_websocket=True,
)
```

---

## 9. Reference

| Document | Path |
|----------|------|
| Architecture | `docs/ARCHITECTURE.md` |
| WebSocket Guide | `docs/WEBSOCKET_GUIDE.md` |
| Funding Rate Guide | `docs/FUNDING_RATE_GUIDE.md` |
| Environment Config | `CCXT_ENV_CONFIG.md` |
| Tests | `tests/new_functions/test_ccxt_*.py` |
