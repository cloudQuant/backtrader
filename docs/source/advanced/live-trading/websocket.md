# WebSocket Real-Time Data Stream Guide

This document explains how to use WebSocket to receive real-time market data in backtrader-ccxt.

## Table of Contents

1. [Overview](#overview)
2. [Installation](#installation)
3. [Three Data Fetching Methods Compared](#three-data-fetching-methods-compared)
4. [Using WebSocket](#using-websocket)
5. [Configuration Parameters](#configuration-parameters)
6. [Troubleshooting](#troubleshooting)

---
## Overview

backtrader-ccxt supports three data fetching methods:

| Method | Latency | API Quota | Complexity | Dependency |

|--------|---------|-----------|------------|------------|

| **REST Polling**| High (per-minute requests) | High | Low | ccxt only |

|**Multi-threaded**| Medium | Medium | Medium | ccxt only |

|**WebSocket**|**Very low (push)**|**Very low**| Medium |**ccxt.pro**|

### WebSocket Advantages

- **Low latency**: Data is pushed by the exchange, no polling needed
- **Saves quota**: Does not consume REST API request quota
- **Real-time**: New bars pushed immediately after candle close
- **Multi-symbol**: Subscribe to multiple trading pairs simultaneously

---
## Installation

### 1. Install ccxt.pro

```bash
pip install ccxtpro

```

### 2. Verify Installation

```python
import ccxt.pro
print(ccxt.__version__)  # Should display version number

```

---
## Three Data Fetching Methods Compared

### Method 1: REST Polling (Default)

```python
data = store.getdata(
    dataname='BTC/USDT',
    timeframe=bt.TimeFrame.Minutes,
    compression=1,

# Without use_websocket, defaults to REST

)

```

- *Characteristics**:
- Makes one HTTP request per minute
- Suitable for infrequent strategies
- Simple and reliable

### Method 2: Multi-threaded

```python
data = store.getdata(
    dataname='BTC/USDT',
    timeframe=bt.TimeFrame.Minutes,
    compression=1,
    use_threaded_data=True,  # Enable multi-threading

)

```

- *Characteristics**:
- Background thread fetches data on schedule
- Main thread is not blocked
- Still consumes REST API quota

### Method 3: WebSocket (Recommended)

```python
data = store.getdata(
    dataname='BTC/USDT',
    timeframe=bt.TimeFrame.Minutes,
    compression=1,
    use_websocket=True,  # Use WebSocket

)

```

- *Characteristics**:
- Ultra-low latency
- Exchange pushes data actively
- Most quota-efficient

---
## Using WebSocket

### Basic Example

```python
import backtrader as bt
from backtrader.stores.ccxtstore import CCXTStore
from backtrader.feeds.ccxtfeed import CCXTFeed

# Create Store

store = CCXTStore(
    exchange='okx',
    currency='USDT',
    config={'apiKey': 'xxx', 'secret': 'xxx', 'password': 'xxx'},
)

# Create data feed with WebSocket

data = CCXTFeed(
    store=store,
    dataname='BTC/USDT',
    timeframe=bt.TimeFrame.Minutes,
    compression=1,
    fromdate=datetime.utcnow() - timedelta(minutes=100),  # Historical data
    backfill_start=True,      # Load historical data first
    historical=False,         # Continue in live mode after history
    use_websocket=True,       # Enable WebSocket

)

cerebro = bt.Cerebro()
cerebro.adddata(data)
cerebro.run()

```

### Complete Strategy Example

```python
import backtrader as bt
from backtrader.stores.ccxtstore import CCXTStore

class MyStrategy(bt.Strategy):
    def __init__(self):
        self.dataclose = self.data.close

    def next(self):
        if len(self.data) >= 10:  # Wait for enough data
            print(f"Price: {self.data.close[0]}")

# Create engine

cerebro = bt.Cerebro()

# Add strategy

cerebro.addstrategy(MyStrategy)

# Set initial capital

cerebro.broker.setcash(1000)

# Create Store

store = CCXTStore(
    exchange='okx',
    currency='USDT',
    config={'apiKey': 'your_key', 'secret': 'your_secret', 'password': 'your_pass'}
)

# Create data feed - using WebSocket

data = store.getdata(
    dataname='BTC/USDT',
    name='BTC/USDT',
    timeframe=bt.TimeFrame.Minutes,
    compression=1,
    fromdate=datetime.utcnow() - timedelta(minutes=100),
    use_websocket=True,
    backfill_start=True,
    historical=False
)

cerebro.adddata(data)
cerebro.run()

```

---
## Configuration Parameters

### CCXTFeed Parameters

| Parameter | Default | Description |

|-----------|---------|-------------|

| `use_websocket` | `False` | Enable WebSocket |

| `use_threaded_data` | `False` | Enable multi-threading |

| `ohlcv_limit` | `100` | Max number of bars per fetch |

| `drop_newest` | `False` | Drop newest bar (may be incomplete) |

| `ws_reconnect_delay` | `5.0` | WebSocket reconnect delay (seconds) |

| `ws_max_reconnect_delay` | `60.0` | Max WebSocket reconnect delay (seconds) |

| `debug` | `False` | Enable debug output |

### WebSocket Supported Exchanges

The following exchanges support ccxt.pro WebSocket:

| Exchange | Support Status |

|----------|---------------|

| Binance | ✅ Full support |

| OKX | ✅ Full support |

| Bybit | ✅ Full support |

| KuCoin | ✅ Full support |

| Bitget | ✅ Partial support |

| Kraken | ✅ Partial support |

> **Note**: WebSocket implementations may vary by exchange. Please verify with actual testing.

---
## Data Flow

### WebSocket Data Flow

```bash
┌─────────────────────────────────────────────────────────────┐
│               Exchange WebSocket Server                      │
│                         ↑                                    │
│                         │ Push                               │
│                         │                                    │
┌────────────────────────┴────────────────────────────────────┐
│          ccxt.pro WebSocket Client (background thread)       │
│                        │                                     │
│                        │ watch_ohlcv()                       │
│                        │                                     │
│                 ┌──────┴──────────────┐                      │
│                 │                     │                      │
│             ┌───┴────┐         ┌─────┴──────────┐           │
│             │ Queue  │         │ CCXTWebSocket   │           │
│             └───┬────┘         │    Manager      │           │
│                 │              └─────────────────┘           │
│                 │                                            │
│                 │                                            │
┌────────────────┴────────────────────────────────────────────┐
│                  backtrader main thread                       │
│                                                              │
│  cerebro.run() → next() → _load() → _load_bar()            │
│                     ↑                                        │
│                     │ Read from Queue                        │
│                     │                                        │
│                 ┌───┴────────┐                               │
│                 │ CCXTFeed   │                               │
│                 └────────────┘                               │
└──────────────────────────────────────────────────────────────┘

```

### Workflow

1. **Historical Data Loading**(REST API)
   - Uses REST API to load historical bars on startup
   - Used to initialize technical indicators (e.g., Bollinger Bands, ATR)
   - Does not trigger any trading signals

2.**Switch to Live Mode**(WebSocket)

   - Sends `LIVE` notification after historical data loading completes
   - Starts WebSocket connection
   - Subscribes to real-time OHLCV data

3.**Real-Time Data Push**

   - Exchange pushes new bar data every minute
   - Placed into queue via WebSocket callback
   - Main thread reads from queue and updates strategy

1. **Disconnect Reconnection**
   - Automatically detects connection status
   - Exponential backoff reconnection (1s → 2s → 4s...)
   - Auto-restores subscriptions after reconnect

---
## Troubleshooting

### Issue 1: WebSocket Not Available

- *Error message**:

```bash
[WS] WebSocket not available. Install ccxt.pro: pip install ccxtpro

```

- *Solution**:

```bash
pip install ccxtpro

```

### Issue 2: Connection Failure

- *Error message**:

```bash
WebSocket connection error: ...

```

- *Possible causes**:
1. Network issues
2. Exchange maintenance
3. Incorrect API keys

- *Solutions**:
- Check network connection
- Verify API keys
- Check exchange status page

### Issue 3: No Data Push

- *Troubleshooting steps**:
1. Check if the trading pair is correct
2. Confirm the exchange supports WebSocket for that pair
3. Enable `debug=True` for detailed info

```python
data = store.getdata(
    ...
    debug=True,  # Enable debug output

)

```

### Issue 4: Duplicate or Missing Data

- *Possible causes**:
- Timezone issues
- Inaccurate exchange clock

- *Solutions**:
- Use `drop_newest=True` to drop potentially incomplete newest bar
- Ensure system time is accurate

---
## Best Practices

### 1. Production Configuration

```python
data = store.getdata(
    dataname='BTC/USDT',
    timeframe=bt.TimeFrame.Minutes,
    compression=1,
    fromdate=datetime.utcnow() - timedelta(minutes=500),
    backfill_start=True,
    historical=False,
    use_websocket=True,          # Use WebSocket
    ohlcv_limit=100,
    drop_newest=True,            # Drop potentially incomplete bars
    ws_reconnect_delay=5.0,       # Reconnect delay
    ws_max_reconnect_delay=60.0,  # Max reconnect delay

)

```

### 2. Multi-Symbol Subscription

```python

# Create data feeds for multiple trading pairs

symbols = ['BTC/USDT', 'ETH/USDT', 'MINA/USDT:USDT']

for symbol in symbols:
    data = store.getdata(
        dataname=symbol,
        timeframe=bt.TimeFrame.Minutes,
        use_websocket=True,
        ...
    )
    cerebro.adddata(data)

```

### 3. Error Handling

Add error handling in your strategy:

```python
class MyStrategy(bt.Strategy):
    def notify_data(self, data, status, *args, **kwargs):
        if status == data.DISCONNECTED:
            self.log('[ERROR] Data connection lost!')

# Add alerting logic here

    def notify_order(self, order):
        if order.status in [order.Rejected, order.Margin]:
            self.log(f'[ERROR] Order failed: {order.status}')

```

---
## Performance Comparison

### API Calls (Running for 1 Hour)

| Method | API Calls | Notes |

|--------|-----------|-------|

| REST Polling | ~60 | One request per minute |

| Multi-threaded | ~60 | Still REST, just runs in background |

| WebSocket | ~2 | Only initial connect + possible reconnects |

### Data Latency

| Method | Latency |

|--------|---------|

| REST Polling | 100-500ms |

| WebSocket | 10-50ms |

---
## Related Documentation

- [CCXT Official Docs](<https://docs.ccxt.com/)>
- [ccxt.pro Docs](<https://docs.ccxt.com/#pro)>
- [Backtrader Docs](<https://www.backtrader.com/docu/)>
