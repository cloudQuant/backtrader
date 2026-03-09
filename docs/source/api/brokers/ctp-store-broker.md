- --

title: CTP Store and Broker API Reference
description: Complete API reference for CTP futures trading with backtrader

- --

# CTP Store and Broker API Reference

This document provides a comprehensive API reference for the CTP (Comprehensive Transaction Platform) integration in backtrader. The CTP API enables live trading of Chinese futures through the native `ctp-python` package.

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [CTPStore Class](#ctpstore-class)
- [CTPBroker Class](#ctpbroker-class)
- [CTPData Feed](#ctpdata-feed)
- [Order Types and Execution](#order-types-and-execution)
- [Market Data Handling](#market-data-handling)
- [Account and Position Management](#account-and-position-management)
- [CTP Constants](#ctp-constants)
- [Error Codes and Handling](#error-codes-and-handling)
- [SimNow Simulation Environment](#simnow-simulation-environment)
- [API Reference](#api-reference)

## Architecture Overview

The CTP integration consists of three main components that work together:

```mermaid
graph TB
    subgraph "Application Layer"
        Cerebro[Cerebro Engine]
        Strategy[Strategy]
    end

    subgraph "Broker Layer"
        CTPBroker[CTPBroker]
        BrokerBase[BrokerBase]
    end

    subgraph "Store Layer"
        CTPStore[CTPStore]
        TraderSpi[CTPTraderSpi]
        MdSpi[CTPMdSpi]
    end

    subgraph "Data Layer"
        CTPData[CTPData Feed]
        Akshare[Akshare Backfill]
    end

    subgraph "CTP API (ctp-python)"
        TraderApi[CThostFtdcTraderApi]
        MdApi[CThostFtdcMdApi]
    end

    subgraph "External Systems"
        TDFront[Trader Front<br/>td_front]
        MDFront[Market Data Front<br/>md_front]
        Exchange[Chinese Futures<br/>Exchanges]
    end

    Cerebro --> Strategy
    Strategy --> CTPBroker
    Cerebro --> CTPData
    CTPBroker --> CTPStore
    CTPData --> CTPStore
    CTPStore --> TraderSpi
    CTPStore --> MdSpi
    TraderSpi --> TraderApi
    MdSpi --> MdApi
    TraderApi --> TDFront
    MdApi --> MDFront
    TDFront --> Exchange
    MDFront --> Exchange
    Akshare --> CTPData

    style CTPStore fill:#e1f5fe
    style CTPBroker fill:#fff3e0
    style CTPData fill:#f3e5f5

```bash

### Message Flow

The CTP API uses a request/response pattern with asynchronous callbacks:

```mermaid
sequenceDiagram
    participant App as Application
    participant Store as CTPStore
    participant Trader as CTPTraderSpi
    participant API as CTP API
    participant Exchange as CTP Exchange

    Note over App,Exchange: Login Flow
    App->>Store: __init__(credentials)
    Store->>Trader: Create with front/broker_id
    Store->>Trader: Start thread
    Trader->>API: RegisterSpi(), RegisterFront(), Init()
    API->>Exchange: Connect
    Exchange-->>API: OnFrontConnected()
    API-->>Trader: OnFrontConnected()
    Trader->>API: ReqAuthenticate()
    API-->>Trader: OnRspAuthenticate()
    Trader->>API: ReqUserLogin()
    API-->>Trader: OnRspUserLogin()

    Note over App,Exchange: Order Flow
    App->>Store: send_order(symbol, direction, ...)
    Store->>Trader: send_order()
    Trader->>API: ReqOrderInsert()
    API-->>Trader: OnRtnOrder() - status update
    Trader->>Store: order_queue.put(status)
    API-->>Trader: OnRtnTrade() - fill notification
    Trader->>Store: trade_queue.put(fill)
    Store->>App: Order notification

```bash

## CTPStore Class

The `CTPStore` class manages connections to both the trader and market data fronts of CTP. It implements a singleton pattern to share a single connection across multiple data feeds and broker instances.

### Class Definition

```python
class backtrader.stores.CTPStore(ParameterizedSingletonMixin)

```bash

### Constructor

```python
CTPStore(ctp_setting=None, **kwargs)

```bash

- *Parameters:**

| Parameter | Type | Default | Description |

|-----------|------|---------|-------------|

| `td_front` | str | See defaults | Trader front address (e.g., `tcp://180.168.146.187:10130`) |

| `md_front` | str | See defaults | Market data front address |

| `broker_id` | str | `"9999"` | Broker ID assigned by CTP |

| `user_id` | str | Required | Your trading account ID |

| `password` | str | Required | Your trading account password |

| `app_id` | str | `"simnow_client_test"` | Application ID for authentication |

| `auth_code` | str | `"0000000000000000"` | Authentication code |

| `debug` | bool | `False` | Enable debug logging |

- *Default SimNow Configuration:**

```python
DEFAULT_TD_FRONT = "tcp://182.254.243.31:30001"
DEFAULT_MD_FRONT = "tcp://182.254.243.31:30011"
DEFAULT_BROKER_ID = "9999"
DEFAULT_APP_ID = "simnow_client_test"
DEFAULT_AUTH_CODE = "0000000000000000"

```bash

### Properties

| Property | Type | Description |

|----------|------|-------------|

| `is_connected` | bool | Returns `True` if connected and logged in to CTP |

### Methods

#### Broker Creation

```python
@classmethod
getbroker(**kwargs) -> CTPBroker

```bash
Returns a `CTPBroker` instance connected to this store.

#### Data Feed Creation

```python
@classmethod
getdata(**kwargs) -> CTPData

```bash
Returns a `CTPData` feed instance.

#### Store Operations

```python

# Register a data feed (internal)

register(feed) -> queue.Queue

# Subscribe to market data for an instrument

subscribe(dataname)

# Stop the store and release resources

stop()

# Register disconnect/reconnect callbacks

on_disconnect(callback: Callable)
on_reconnect(callback: Callable)

```bash

#### Order Operations

```python
send_order(symbol, direction, offset, price, volume, order_price_type) -> str

```bash
Submit an order to CTP.

- *Parameters:**

| Parameter | Type | Description |

|-----------|------|-------------|

| `symbol` | str | Instrument ID (e.g., `'rb2501.SHFE'`) |

| `direction` | str | `THOST_FTDC_D_Buy` ('0') or `THOST_FTDC_D_Sell` ('1') |

| `offset` | str | Open/Close flag (see [CTP Constants](#ctp-constants)) |

| `price` | float | Order price |

| `volume` | int | Number of contracts |

| `order_price_type` | str | `THOST_FTDC_OPT_LimitPrice` ('2') or `THOST_FTDC_OPT_AnyPrice` ('1') |

- *Returns:** `order_ref` (str) or `None` on failure

```python
cancel_order(symbol, order_ref, front_id=None, session_id=None) -> bool

```bash
Cancel an active order.

#### Account Queries

```python
get_balance() -> None

```bash
Query and update account balance with rate limiting (2 second interval).

```python
get_cash() -> float

```bash
Get current available cash.

```python
get_value() -> float

```bash
Get total account value (balance).

```python
get_positions() -> list

```bash
Query and return current positions.

- *Returns:** List of position dictionaries:

```python
[{
    'instrument': 'rb2501',
    'direction': '2',  # '2'=Long, '3'=Short
    'volume': 5,
    'yd_volume': 3,
    'today_volume': 2,
    'avg_price': 3800.0,
    'position_profit': 500.0
}, ...]

```bash

## CTPBroker Class

The `CTPBroker` class implements order management, position tracking, and account management for CTP futures trading.

### Class Definition

```python
class backtrader.brokers.CTPBroker(BrokerBase)

```bash

### Parameters

| Parameter | Type | Default | Description |

|-----------|------|---------|-------------|

| `use_positions` | bool | `True` | Use existing positions on startup |

| `commission` | float | `0.0` | Commission per contract (absolute value) |

| `stop_slippage_ticks` | float | `0.0` | Max slippage for stop orders (0=market) |

### Methods

#### Order Creation

```python
buy(owner, data, size, price=None, plimit=None, exectype=None, ...) -> Order
sell(owner, data, size, price=None, plimit=None, exectype=None, ...) -> Order

```bash

- *Parameters:**

| Parameter | Type | Description |

|-----------|------|-------------|

| `owner` | Strategy | The strategy creating the order |

| `data` | Data feed | The data feed for this order |

| `size` | int | Number of contracts (positive) |

| `price` | float | Limit price or stop trigger price |

| `plimit` | float | Limit price for stop-limit orders |

| `exectype` | Order.Type | `Order.Market`, `Order.Limit`, `Order.Stop`, `Order.StopLimit` |

#### Order Cancellation

```python
cancel(order) -> Order

```bash
Cancel an active order.

#### Account Status

```python
getcash() -> float
getvalue(datas=None) -> float
getposition(data, clone=True) -> Position
orderstatus(order) -> int

```bash

#### Notifications

```python
notify(order) -> None
get_notification() -> Order or None

```bash

### Position Management

The broker maintains detailed position tracking for SHFE/INE exchanges:

```python

# Internal position detail structure

_pos_detail = {
    'rb2501': {
        'today_long': 2,    # Long positions opened today
        'today_short': 0,   # Short positions opened today
        'yd_long': 3,       # Long positions from yesterday
        'yd_short': 1       # Short positions from yesterday
    }
}

```bash

## CTPData Feed

The `CTPData` feed provides live tick data from CTP and historical backfill from akshare.

### Class Definition

```python
class backtrader.feeds.ctpdata.CTPData(DataBase)

```bash

### Parameters

| Parameter | Type | Default | Description |

|-----------|------|---------|-------------|

| `historical` | bool | `False` | Stop after backfill (no live data) |

| `num_init_backfill` | int | `100` | Number of historical bars to load |

| `tick_mode` | bool | `False` | Emit raw ticks instead of bars |

| `backfill_retries` | int | `2` | Number of backfill retry attempts |

### Bar Aggregation

The feed aggregates ticks into bars based on `timeframe` and `compression`:

- **Minutes**: `timeframe=TimeFrame.Minutes` with `compression=1, 5, 15, 30, 60`
- **Days**: `timeframe=TimeFrame.Days` with `compression=1`

Bar times are aligned to trading session boundaries to avoid creating bars that span session breaks.

### Trading Session Alignment

```python
_TRADING_SESSIONS = [
    (21, 0, 23, 0),      # Night session part 1
    (23, 0, 2, 30),      # Night session part 2 (crosses midnight)
    (9, 0, 10, 15),      # Morning session 1
    (10, 30, 11, 30),    # Morning session 2
    (13, 30, 15, 0),     # Afternoon session

]

```bash

## Order Types and Execution

### Supported Order Types

| Order Type | Description | CTP Mapping |

|------------|-------------|-------------|

| `Order.Market` | Market order | `THOST_FTDC_OPT_AnyPrice` (IOC) |

| `Order.Limit` | Limit order | `THOST_FTDC_OPT_LimitPrice` |

| `Order.Stop` | Stop market | Local trigger + market order |

| `Order.StopLimit` | Stop limit | Local trigger + limit order |

### Order Status Flow

```mermaid
stateDiagram-v2
    [*] --> Created: _submit_order()
    Created --> Submitted: order.submit()
    Submitted --> Accepted: CTP accepts order
    Accepted --> Partial: Partial fill
    Partial --> Partial: More fills
    Partial --> Completed: Fully filled
    Accepted --> Completed: Filled in one trade
    Accepted --> Canceled: Cancel request
    Submitted --> Rejected: CTP rejects order

    note right of Stop
        Stop orders are held locally
        until trigger price is hit,
        then submitted to CTP
    end note

```bash

### Order Execution Examples

#### Market Order

```python

# Buy at market (uses AnyPrice + IOC in CTP)

order = cerebro.broker.buy(
    owner=strategy,
    data=data,
    size=1,
    exectype=bt.Order.Market
)

```bash

#### Limit Order

```python

# Buy with limit price

order = cerebro.broker.buy(
    owner=strategy,
    data=data,
    size=1,
    price=3800.0,
    exectype=bt.Order.Limit
)

```bash

#### Stop Order

```python

# Stop loss: sell when price drops below 3750

order = cerebro.broker.sell(
    owner=strategy,
    data=data,
    size=1,
    price=3750.0,  # Stop trigger price
    exectype=bt.Order.Stop
)

```bash

#### Stop-Limit Order

```python

# Stop-limit: sell when price drops below 3750,

# but limit execution price to 3748

order = cerebro.broker.sell(
    owner=strategy,
    data=data,
    size=1,
    price=3750.0,    # Stop trigger price
    plimit=3748.0,   # Limit price after trigger
    exectype=bt.Order.StopLimit
)

```bash

### SHFE/INE Close Offset Handling

For SHFE and INE exchanges, the broker automatically handles the distinction between closing today's positions and yesterday's positions:

```python

# Automatic offset selection

_determine_close_offsets(symbol, direction, volume)

```bash

- *Logic:**

1. When closing long positions (selling):
   - Close `today_long` first using `THOST_FTDC_OF_CloseToday`
   - Then close `yd_long` using `THOST_FTDC_OF_CloseYesterday`

1. When closing short positions (buying):
   - Close `today_short` first using `THOST_FTDC_OF_CloseToday`
   - Then close `yd_short` using `THOST_FTDC_OF_CloseYesterday`

1. For other exchanges (DCE, CZCE, CFFEX):
   - Use generic `THOST_FTDC_OF_Close` for all closes

## Market Data Handling

### Tick Data Structure

Each tick from CTP is structured as:

```python
tick = {
    'instrument': 'rb2501',
    'last_price': 3800.0,
    'open_price': 3795.0,
    'high_price': 3810.0,
    'low_price': 3790.0,
    'volume': 12345,
    'open_interest': 100000,
    'bid_price1': 3799.0,
    'ask_price1': 3801.0,
    'bid_volume1': 100,
    'ask_volume1': 150,
    'update_time': '09:30:15',
    'update_millisec': 500,
    'trading_day': '20250105',
    'action_day': '20250105'
}

```bash

### Tick Queue Management

- Each instrument has a dedicated `queue.Queue(maxsize=10000)`
- When full, oldest tick is discarded to prevent memory overflow
- Bounded queues protect against slow consumption

### Bar Construction

```python

# For each tick:

1. Parse datetime and convert to China timezone
2. Calculate incremental volume (tick_volume - last_tick_volume)
3. In tick_mode: emit tick immediately as bar
4. In bar mode:

   a. Initialize new bar if needed
   b. Check if tick belongs to current bar period
   c. If new bar period: emit completed bar, start new bar
   d. Otherwise: update current bar (OHLC, volume, OI)

```bash

## Account and Position Management

### Account Information

```python
account = {
    'available': 50000.0,      # Available cash for trading
    'balance': 100000.0,       # Total account balance
    'margin': 20000.0,         # Current margin used
    'commission': 500.0,       # Today's commission
    'frozen_margin': 5000.0,   # Frozen for pending orders
    'frozen_cash': 1000.0,     # Frozen for pending orders
    'trading_day': '20250105'  # Current trading day

}

```bash

### Position Information

```python
position = {
    'instrument': 'rb2501',
    'direction': '2',          # '2' = Long, '3' = Short
    'volume': 5,               # Total position
    'yd_volume': 3,            # Yesterday's position
    'today_volume': 2,         # Today's position
    'avg_price': 3800.0,       # Average opening price
    'position_profit': 500.0   # Unrealized P&L

}

```bash

### Position Tracking

The broker maintains two types of position tracking:

1. **Net Position**(`Position(size, price)`)
   - Used by backtrader strategies
   - Size: positive for long, negative for short
   - Price: weighted average entry price

2.**Detailed Position**(`_pos_detail`)

   - Used for SHFE/INE close offset logic
   - Tracks today/yesterday separately
   - Tracks long/short separately

## CTP Constants

### Direction (Direction)

```python
THOST_FTDC_D_Buy = '0'     # Buy

THOST_FTDC_D_Sell = '1'    # Sell

```bash

### Offset Flag (CombOffsetFlag)

```python
THOST_FTDC_OF_Open = '0'              # Open

THOST_FTDC_OF_Close = '1'             # Close (generic)

THOST_FTDC_OF_CloseToday = '3'        # Close today's position

THOST_FTDC_OF_CloseYesterday = '4'    # Close yesterday's position

```bash

### Order Price Type (OrderPriceType)

```python
THOST_FTDC_OPT_LimitPrice = '2'   # Limit price

THOST_FTDC_OPT_AnyPrice = '1'     # Market price (any price)

```bash

### Hedge Flag (CombHedgeFlag)

```python
THOST_FTDC_HF_Speculation = '1'   # Speculation

THOST_FTDC_HF_Arbitrage = '2'     # Arbitrage

THOST_FTDC_HF_Hedge = '3'         # Hedge

```bash

### Time Condition (TimeCondition)

```python
THOST_FTDC_TC_IOC = '1'   # Immediate or Cancel

THOST_FTDC_TC_GFD = '3'   # Good for Day

```bash

### Volume Condition (VolumeCondition)

```python
THOST_FTDC_VC_AV = '1'    # Any Volume

THOST_FTDC_VC_CV = '3'    # Complete Volume

```bash

### Order Status (OrderStatus)

```python
THOST_FTDC_OST_AllTraded = '0'                  # All filled

THOST_FTDC_OST_PartTradedQueueing = '1'         # Partial, queuing

THOST_FTDC_OST_PartTradedNotQueueing = '2'      # Partial, not queuing

THOST_FTDC_OST_NoTradeQueueing = '3'            # No trade, queuing

THOST_FTDC_OST_NoTradeNotQueueing = '4'         # No trade, not queuing

THOST_FTDC_OST_Canceled = '5'                   # Canceled

THOST_FTDC_OST_Unknown = 'a'                    # Unknown

```bash

## Error Codes and Handling

### Common CTP Error Codes

| Error ID | Description | Action |

|----------|-------------|--------|

| 0 | Success | Continue |

| 3 | Wrong user ID/password | Check credentials |

| 6 | Not logged in | Wait for login |

| 11 | No trading right | Contact broker |

| 39 | Client exceeds order frequency | Slow down orders |

| 42 | No instrument data | Check instrument ID |

| 47 | Instrument not trading | Check market hours |

| 48 | Instrument not exist | Check instrument ID |

| 52 | No enough margin | Deposit funds |

| 58 | Invalid instrument status | Contact broker |

| 75 | Login ban (too many attempts) | Wait before retry |

| 91 | Connection failed | Check network |

### Error Handling Patterns

#### Login Error Handling

```python
store = bt.stores.CTPStore(
    td_front='tcp://182.254.243.31:30001',
    md_front='tcp://182.254.243.31:30011',
    broker_id='9999',
    user_id='your_id',
    password='your_password',
    app_id='simnow_client_test',
    auth_code='0000000000000000',
)

if not store.is_connected:

# Check for login error
    if store.trader_spi.login_error:
        err_id, err_msg = store.trader_spi.login_error
        print(f"Login failed: {err_id} - {err_msg}")

```bash

#### Order Rejection Handling

```python
def notify_order(self, order):
    if order.status == order.Rejected:
        logger.error(f"Order rejected: {order}")

# Check for common causes:

# - Insufficient margin

# - Position limits

# - Invalid instrument

# - Market closed

```bash

#### Disconnect/Reconnect Handling

```python
def on_disconnect(reason):
    logger.warning(f"CTP disconnected: reason={reason}")

def on_reconnect():
    logger.info("CTP reconnected")

# Re-subscribe instruments

# Re-query positions

store.on_disconnect(on_disconnect)
store.on_reconnect(on_reconnect)

```bash

## SimNow Simulation Environment

### Overview

SimNow is a free simulation environment provided by Shanghai Futures Information Technology Co., Ltd. for testing CTP applications.

### SimNow Front Addresses

| Environment | Trader Front | Market Data Front |

|-------------|--------------|-------------------|

| 7x24 (Penetrating) | `tcp://182.254.243.31:30001` | `tcp://182.254.243.31:30011` |

| Regular Hours | `tcp://180.168.146.187:10130` | `tcp://180.168.146.187:10131` |

### SimNow Registration

1. Visit [SimNow official website](<http://www.simnow.com.cn/)>
2. Register for a demo account
3. Receive:
   - Broker ID: typically `"9999"`
   - User ID: your registered username
   - Password: your registered password

### Default SimNow Configuration

```python
import backtrader as bt

# Create CTP store with SimNow defaults

store = bt.stores.CTPStore(
    td_front='tcp://182.254.243.31:30001',  # 7x24 front
    md_front='tcp://182.254.243.31:30011',
    broker_id='9999',
    user_id='your_simnow_id',
    password='your_simnow_password',
    app_id='simnow_client_test',
    auth_code='0000000000000000',
)

```bash

### SimNow Trading Hours

The 7x24 environment allows testing anytime:

- **Day Session**: Matches real trading hours
- **Night Session**: Matches real trading hours
- **Data Generation**: Simulated market data when real market is closed

### SimNow Limitations

1. **Data Quality**: Simulated data may not reflect real market conditions
2. **Execution**: Simulated order routing, fills may differ from live
3. **Reset**: Accounts are periodically reset (check SimNow announcements)
4. **Instruments**: Not all instruments may be available

## API Reference

### Quick Reference

```python

# 1. Create store

store = bt.stores.CTPStore(
    td_front='tcp://182.254.243.31:30001',
    md_front='tcp://182.254.243.31:30011',
    broker_id='9999',
    user_id='your_id',
    password='your_password',
    app_id='simnow_client_test',
    auth_code='0000000000000000',
)

# 2. Create data feed

data = store.getdata(
    dataname='rb2501.SHFE',
    timeframe=bt.TimeFrame.Minutes,
    compression=1,
    num_init_backfill=100,
)

# 3. Create broker

cerebro.setbroker(store.getbroker(
    use_positions=True,
    commission=1.0,
))

# 4. Add to cerebro

cerebro.adddata(data)
cerebro.addstrategy(YourStrategy)

```bash

### Complete Example

```python

# !/usr/bin/env python

"""CTP Live Trading Example with API Reference"""

import backtrader as bt
import logging

logging.basicConfig(level=logging.INFO)


class TestStrategy(bt.Strategy):
    """Test strategy demonstrating CTP API usage."""

    def __init__(self):
        self.order = None
        self.log('Strategy initialized')

    def log(self, txt, dt=None):
        dt = dt or self.data.datetime[0]
        print(f'{dt} {txt}')

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status == order.Completed:
            if order.isbuy():
                self.log(f'BUY EXECUTED: Price={order.executed.price:.2f}, '
                        f'Size={order.executed.size}, Comm={order.executed.comm:.2f}')
            else:
                self.log(f'SELL EXECUTED: Price={order.executed.price:.2f}, '
                        f'Size={order.executed.size}, Comm={order.executed.comm:.2f}')

        elif order.status == order.Canceled:
            self.log('Order Canceled')
        elif order.status == order.Rejected:
            self.log('Order Rejected')

        self.order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.log(f'TRADE CLOSED: P&L={trade.pnl:.2f}, Comm={trade.commission:.2f}')

    def next(self):

# Check cash
        cash = self.broker.getcash()
        value = self.broker.getvalue()

# Check position
        pos = self.getposition()
        size = pos.size
        price = pos.price

# Place order if no pending order and no position
        if not self.order and size == 0:
            self.order = self.buy(size=1, exectype=bt.Order.Market)
            self.log(f'BUY ORDER PLACED: Cash={cash:.2f}, Value={value:.2f}')


def main():

# Create cerebro
    cerebro = bt.Cerebro()

# CTP connection settings
    ctp_setting = {
        'td_front': 'tcp://182.254.243.31:30001',
        'md_front': 'tcp://182.254.243.31:30011',
        'broker_id': '9999',
        'user_id': 'your_id',
        'password': 'your_password',
        'app_id': 'simnow_client_test',
        'auth_code': '0000000000000000',
    }

# Create store
    store = bt.stores.CTPStore(**ctp_setting)

# Check connection
    if not store.is_connected:
        print("Failed to connect to CTP")
        return

    print(f"Connected to CTP: Cash={store.get_cash():.2f}, Value={store.get_value():.2f}")

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
    cerebro.addstrategy(TestStrategy)

# Run
    try:
        cerebro.run()
    except KeyboardInterrupt:
        print("\nStopped by user")


if __name__ == '__main__':
    main()

```bash

### Supported Exchanges

| Exchange | Code | Example Instruments | CloseToday Required |

|----------|------|---------------------|---------------------|

| Shanghai Futures Exchange | SHFE | rb, hc, cu, al, au, zn, pb, ni, sn, ss | Yes |

| Dalian Commodity Exchange | DCE | m, y, p, a, b, c, cs, eb, eg, fb, i, j, jd, jm, l, lh, lu, p, pg, pp, rr, v | No |

| Zhengzhou Commodity Exchange | CZCE | AP, CF, CJ, CY, FG, GM, JR, LR, MA, OA, OI, PF, PK, PM, RI, RM, RS, SF, SM, SR, TA, UR, WH, ZC | No |

| Shanghai International Energy | INE | sc, lu, bc, nr | Yes |

| China Financial Futures Exchange | CFFEX | IC, IF, IH, IM, T, TF, TL, TS | No |

### Instrument ID Format

```bash
[instrument_code][contract_month].[exchange_code]

Examples:
rb2505.SHFE  - Rebar May 2025 on SHFE
m2505.DCE    - Soybean Meal May 2025 on DCE
SR505.CZCE   - White Sugar May 2025 on CZCE
sc2505.INE   - Crude Oil May 2025 on INE
IF2505.CFFEX - CSI 300 Index May 2025 on CFFEX

```bash

## See Also

- [CTP Live Trading User Guide](../user_guide/ctp-live-trading.md)
- [Data Feeds](data-feeds.md)
- [Broker API](broker-api.md)
- [Strategy Development](strategies.md)
