# Funding Rate Strategy Guide

This document explains how to use **WebSocket real-time**funding rate data for perpetual contract trading strategy development in Backtrader.

---
## Table of Contents

1. [What is Funding Rate](#what-is-funding-rate)
2. [Quick Start](#quick-start)
3. [WebSocket Real-Time Data](#websocket-real-time-data)
4. [API Reference](#api-reference)
5. [Strategy Examples](#strategy-examples)
6. [Exchange Support](#exchange-support)

---
## What is Funding Rate

### Funding Rate Overview

Perpetual contracts have no expiration date. To anchor the contract price to the spot price, exchanges use a**funding rate**mechanism:

- **Positive rate**: Contract price > spot price → longs pay shorts
- **Negative rate**: Contract price < spot price → shorts pay longs
- **Collection frequency**: Usually every 8 hours (00:00, 08:00, 16:00 UTC)

### Fee Calculation

```bash
Funding Fee = Position Value × Funding Rate

```
Example:

- Holding a 100 USDT long position
- Funding rate is +0.01% (0.0001)
- Fee paid: 100 × 0.0001 = 0.01 USDT

### Typical Rate Ranges

| Rate Range | Meaning | Strategy Suggestion |

|-----------|---------|-------------------|

| > 0.05% | Extreme greed, overcrowded longs | Consider short arbitrage |

| 0.01% ~ 0.05% | Long-biased | Wait and observe |

| -0.01% ~ 0.01% | Balanced zone | No clear bias |

| -0.05% ~ -0.01% | Short-biased | Wait and observe |

| < -0.05% | Extreme fear, overcrowded shorts | Consider long arbitrage |

---
## Quick Start

### Install Dependencies

```bash

# Install ccxt.pro (WebSocket support)

pip install ccxtpro

# Or install full ccxt

pip install ccxt[pro]

```

### Using the Funding Rate Data Feed

```python
import backtrader as bt
from backtrader.feeds import CCXTFeedWithFunding
from backtrader.stores import CCXTStore
from datetime import datetime, timedelta

# Create Store

store = CCXTStore(
    exchange='binance',
    config={'apiKey': 'xxx', 'secret': 'xxx'},
    currency='USDT'
)

# Create data feed with funding rate (WebSocket enabled by default)

data = CCXTFeedWithFunding(
    store=store,
    dataname='BTC/USDT:USDT',  # Perpetual contract
    name='BTC/USDT:USDT',
    timeframe=bt.TimeFrame.Minutes,
    compression=1,
    fromdate=datetime.utcnow() - timedelta(hours=24),
    backfill_start=True,
    historical=False,
    use_websocket=True,              # Use WebSocket (default True)
    include_funding=True,              # Enable funding rate
    funding_history_days=3,            # Fetch 3 days of history
    debug=False
)

cerebro = bt.Cerebro()
cerebro.adddata(data)

```

### Accessing Funding Rate in Strategy

```python
class MyStrategy(bt.Strategy):
    def __init__(self):

# Check if data feed supports funding rate
        if hasattr(self.data, 'funding_rate'):
            print("Data feed supports funding rate")
        else:
            raise ValueError("Please use CCXTFeedWithFunding data feed")

    def next(self):

# Get current funding rate (real-time WebSocket update)
        current_funding = self.data.funding_rate[0]

# Get mark price
        if hasattr(self.data, 'mark_price'):
            mark_price = self.data.mark_price[0]

# Get predicted rate
        if hasattr(self.data, 'predicted_funding_rate'):
            predicted = self.data.predicted_funding_rate[0]

# Get next funding time
        if hasattr(self.data, 'next_funding_time'):
            next_funding_time = self.data.next_funding_time[0]

# Get current price
        price = self.data.close[0]

# Trade based on funding rate
        if current_funding > 0.0005:  # Above 0.05%
            self.sell()  # Short arbitrage
        elif current_funding < -0.0005:  # Below -0.05%
            self.buy()   # Long arbitrage

```

---
## WebSocket Real-Time Data

### WebSocket Connection Notes

CCXTFeedWithFunding **requires**a WebSocket connection to work. When WebSocket is unavailable, the system will**raise an error** rather than falling back to HTTP polling.

### Install Dependencies

```bash

# ccxt.pro is required

pip install ccxtpro

```

### WebSocket Subscribed Data Streams

| Data Stream | Description | Update Frequency |

|-------------|-------------|-----------------|

| `watch_ohlcv` | OHLCV bar data | On each bar close |

| `watch_funding_rate` | Funding rate | Real-time push (typically per second) |

| `watch_mark_price` | Mark price | Real-time push |

### Data Integration Flow

```bash
WebSocket OHLCV Push          WebSocket Funding Push
        |                              |

        v                              v
   [timestamp, O, H, L, C, V]    {fundingRate, markPrice, ...}
        |                              |

        - -----------> Merge <----------+

                     |

                     v
   [timestamp, O, H, L, C, V, funding_rate, mark_price, ...]
                     |

                     v
               self.lines.close[0]
               self.lines.funding_rate[0]
               self.lines.mark_price[0]

```

### Error Handling

When WebSocket is unavailable, a `WebSocketRequiredError` is raised:

```python
from backtrader.feeds import CCXTFeedWithFunding

try:
    data = CCXTFeedWithFunding(
        store=store,
        dataname='BTC/USDT:USDT',
        use_websocket=True  # Must be True
    )
except WebSocketRequiredError as e:
    print(f"Error: {e}")

# Make sure ccxt.pro is installed: pip install ccxtpro

```

---
## API Reference

### CCXTFeedWithFunding

#### Lines

| Line | Type | Description |

|------|------|-------------|

| `funding_rate` | float | Current funding rate (8-hour rate, e.g., 0.0001 = 0.01%) |

| `mark_price` | float | Current mark price (used for funding fee calculation) |

| `next_funding_time` | float | Next funding fee collection time |

| `predicted_funding_rate` | float | Predicted next funding rate |

#### Params

| Parameter | Default | Description |

|-----------|---------|-------------|

| `use_websocket` | True | Use WebSocket real-time data (must be True) |

| `include_funding` | True | Whether to fetch funding rate data |

| `funding_history_days` | 3 | Historical days to fetch on startup |

| `ws_startup_timeout` | 10 | WebSocket startup timeout (seconds) |

| `debug` | False | Debug output |

### CCXTWebSocketManager

#### New Methods

```python

# Subscribe to funding rate

manager.subscribe_funding_rate(symbol, callback)

# Subscribe to mark price

manager.subscribe_mark_price(symbol, callback)

```

---
## Strategy Examples

### Example 1: Real-Time Funding Rate Monitor

```python
class FundingMonitor(bt.Strategy):
    """Monitor and print real-time funding rates"""

    def __init__(self):
        if not hasattr(self.data, 'funding_rate'):
            raise ValueError("Please use CCXTFeedWithFunding")

        self.bar_count = 0
        self.is_live = False

    def notify_data(self, data, status):
        if status == data.LIVE and not self.is_live:
            self.is_live = True
            print("[LIVE] Entered live mode!")

    def next(self):
        if not self.is_live:
            return

        self.bar_count += 1
        if self.bar_count % 10 != 0:  # Output every 10 bars
            return

        funding = self.data.funding_rate[0]
        mark_price = self.data.mark_price[0] if hasattr(self.data, 'mark_price') else 0
        price = self.data.close[0]

# Calculate premium
        premium = (mark_price - price) / price * 100 if price > 0 else 0

        print(f"\n{'='*60}")
        print(f"[FUNDING] {self.data.datetime.datetime(0)}")
        print(f"  Price:      ${price:.6f}")
        print(f"  Mark Price: ${mark_price:.6f} (Premium: {premium:+.4f}%)")
        print(f"  Fund Rate:  {funding:.6f} ({funding*100:.4f}%)")
        print(f"  Annualized: {funding*3*365*100:.2f}%")
        print(f"{'='*60}\n")

```

### Example 2: Funding Rate Arbitrage Strategy

```python
class FundingArbitrage(bt.Strategy):
    """Funding rate arbitrage strategy (WebSocket real-time version)"""

    params = (
        ('funding_high', 0.0005),   # Above 0.05% go short
        ('funding_low', -0.0005),   # Below -0.05% go long
        ('position_size', 10),
    )

    def __init__(self):
        if not hasattr(self.data, 'funding_rate'):
            raise ValueError("Please use CCXTFeedWithFunding")

    def next(self):
        funding = self.data.funding_rate[0]
        position = self.getposition()

# High rate = overcrowded longs = short arbitrage
        if funding > self.p.funding_high and position.size == 0:
            print(f"[SIGNAL] Rate {funding:.6f} > {self.p.funding_high}, short arbitrage")
            self.sell(size=self.p.position_size)

# Low rate = overcrowded shorts = long arbitrage
        elif funding < self.p.funding_low and position.size == 0:
            print(f"[SIGNAL] Rate {funding:.6f} < {self.p.funding_low}, long arbitrage")
            self.buy(size=self.p.position_size)

# Close when rate normalizes
        elif abs(funding) < abs(self.p.funding_high) / 2 and position.size != 0:
            print(f"[EXIT] Rate normalized to {funding:.6f}, closing position")
            if position.size > 0:
                self.sell(size=position.size)
            else:
                self.buy(size=abs(position.size))

```

### Example 3: Mark Price Spread Trading

```python
class MarkPriceArbitrage(bt.Strategy):
    """Trade based on mark price vs last price spread"""

    params = (
        ('premium_threshold', 0.001),  # 0.1% premium threshold
    )

    def __init__(self):
        if not hasattr(self.data, 'mark_price'):
            raise ValueError("Data feed requires mark_price")

    def next(self):
        price = self.data.close[0]
        mark_price = self.data.mark_price[0]

# Calculate premium
        premium = (mark_price - price) / price if price > 0 else 0

# Mark > Last = premium = go long (expect mean reversion)

# Mark < Last = discount = go short (expect mean reversion)
        if premium > self.p.premium_threshold:
            self.buy()  # Long on premium
        elif premium < -self.p.premium_threshold:
            self.sell()  # Short on discount

```

---
## Exchange Support

### WebSocket Funding Rate Support

| Exchange | watch_funding_rate | watch_mark_price | Notes |

|----------|-------------------|------------------|-------|

| **Binance**| ✅ (via markPrice) | ✅ | Via mark price stream |

|**OKX**| ✅ | ✅ | Native support |

|**Bybit**| ✅ | ✅ | Supported |

|**Bitget**| ⚠️ | ✅ | Partial support |

|**KuCoin**| ⚠️ | ✅ | Needs testing |

### Exchange-Specific Configuration

#### Binance

```python
store = CCXTStore(
    exchange='binance',
    config={
        'apiKey': 'xxx',
        'secret': 'xxx',
        'options': {
            'defaultType': 'future'  # Use futures API
        }
    }
)

# Binance gets funding rate via markPrice stream

data = CCXTFeedWithFunding(
    store=store,
    dataname='BTC/USDT:USDT',  # Perpetual contract
    use_websocket=True
)

```

#### OKX

```python
store = CCXTStore(
    exchange='okx',
    config={
        'apiKey': 'xxx',
        'secret': 'xxx',
        'password': 'xxx',
        'options': {
            'defaultType': 'swap'
        }
    }
)

data = CCXTFeedWithFunding(
    store=store,
    dataname='BTC/USDT:USDT',
    use_websocket=True
)

```

---
## Debugging and Monitoring

### Enable Debug Output

```python
data = CCXTFeedWithFunding(
    store=store,
    dataname='BTC/USDT:USDT',
    debug=True  # Enable debug output

)

```

### Debug Output Example

```bash
[WS] WebSocket connected to binance
[WS] WebSocket started for BTC/USDT:USDT with funding rate
[FUNDING] Fetching historical funding rates for BTC/USDT:USDT...
[FUNDING] Loaded 72 historical rates
[FUNDING WS] Rate: 0.00010000, Mark: 43250.50000000
[FUNDING WS] Rate: 0.00010500, Mark: 43252.30000000

```

---
## Important Notes

1.**ccxt.pro License**: ccxt.pro requires a commercial license for production use

1. **WebSocket Required**: This data feed mandates WebSocket; it will not fall back to HTTP
2. **WebSocket Stability**: WebSocket may disconnect; built-in auto-reconnect is included
3. **Data Sync**: Funding rate updates less frequently than price — this is normal
4. **Startup Check**: If WebSocket connection times out, `WebSocketRequiredError` is raised

## Network Troubleshooting

### WebSocket Connection Failure

If you encounter WebSocket connection issues, check the following:

1. **DNS Resolution**

   ```bash

# Test DNS resolution
   ping ws.okx.com      # OKX
   ping stream.binance.com  # Binance
   ```

1. **Firewall Settings**
   - Ensure WebSocket connections are allowed (typically port 443)
   - Some corporate networks may block WebSocket connections

1. **Proxy Configuration**

   ```python

# If a proxy is needed, set it in config
   config = {
       'proxies': {
           'https': '<http://your-proxy:port',>
           'ws': 'ws://your-proxy:port',  # WebSocket proxy
       }
   }
   ```

1. **Test Script**

   Run a simple WebSocket test to verify connectivity:
   ```bash
   python examples/test_websocket_simple.py
   ```

### Common Errors

| Error Message | Cause | Solution |

|--------------|-------|---------|

| `Could not contact DNS servers` | DNS resolution failure | Check network, try VPN |

| `Connection refused` | Firewall blocking | Open WebSocket port |

| `Timeout` | High network latency | Check network quality, increase timeout |

| `Authentication failed` | Incorrect API key | Verify API key configuration |

---
## Related Documentation

- [WebSocket Guide](./websocket.md)
- [CCXT Official Docs](<https://docs.ccxt.com/)>
