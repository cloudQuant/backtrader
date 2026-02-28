---
title: Broker API
description: Complete Broker class API reference
---

# Broker API

The `Broker` class handles order execution, position tracking, and cash management in Backtrader. It simulates broker behavior during backtesting and supports various order types, commission schemes, and margin requirements.

## Class Definition

```python
class backtrader.BrokerBase:
    """Base class for broker implementations."""

class backtrader.brokers.BackBroker:
    """Broker simulator for backtesting (alias: BrokerBack)."""
```

## Broker Parameters

### `cash` (default: 10000.0)

Starting cash amount for the backtest.

```python
cerebro = bt.Cerebro()
cerebro.broker.setcash(100000.0)
```

### `commission` (default: CommInfoBase(percabs=True))

Default commission scheme for all assets.

```python
# Percentage commission
cerebro.broker.setcommission(commission=0.001)  # 0.1%

# Fixed commission
cerebro.broker.setcommission(commission=2.0, commtype=bt.CommInfoBase.COMM_FIXED)
```

### `checksubmit` (default: True)

Whether to check margin/cash before accepting orders.

### `eosbar` (default: False)

Consider bar with same time as end of session as end of session.

### `filler` (default: None)

Volume filler callable for partial order execution.

### Slippage Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `slip_perc` | float | 0.0 | Percentage slippage (0.01 = 1%) |
| `slip_fixed` | float | 0.0 | Fixed slippage in price units |
| `slip_open` | bool | False | Apply slippage to opening prices |
| `slip_match` | bool | True | Cap slippage at high/low prices |
| `slip_limit` | bool | True | Allow limit order matching with slippage |
| `slip_out` | bool | False | Provide slippage outside high-low range |

### `coc` (default: False)

Cheat-On-Close: Match market orders to closing price of same bar.

### `coo` (default: False)

Cheat-On-Open: Match market orders to opening price.

### `fundmode` / `fundstartval` (default: False / 100.0)

Fund-like performance tracking mode.

## Cash and Value Methods

### `getcash()` / `get_cash()`

Get current available cash.

```python
cash = cerebro.broker.getcash()
# or from strategy
cash = self.broker.getcash()
```

### `setcash(amount)` / `set_cash(amount)`

Set broker cash amount.

```python
cerebro.broker.setcash(100000.0)
```

### `getvalue(datas=None)` / `get_value(datas=None)`

Get portfolio value. If `datas` is None, returns total portfolio value.

```python
# Total value
total_value = self.broker.getvalue()

# Value for specific data
data_value = self.broker.getvalue([self.data])
```

### `add_cash(amount)` / `add_cash(amount)`

Add or remove cash from the system.

```python
# Add cash
cerebro.broker.add_cash(50000.0)

# Remove cash
cerebro.broker.add_cash(-10000.0)
```

## Position Management

### `getposition(data)`

Get position for a specific data feed.

```python
position = self.broker.getposition(self.data)
size = position.size  # Positive=long, negative=short
price = position.price  # Average entry price
```

**Position Attributes**:

| Attribute | Type | Description |
|-----------|------|-------------|
| `size` | float | Position size (positive=long, negative=short) |
| `price` | float | Average entry price |
| `price_adj` | float | Adjusted price (for stocks) |
| `adjbase` | float | Adjustment base for futures |

## Commission Settings

### `setcommission(...)`

Set commission scheme for trading.

```python
# Stock-like with percentage commission
cerebro.broker.setcommission(
    commission=0.001,      # 0.1% commission
    stocklike=True
)

# Futures with margin and fixed commission
cerebro.broker.setcommission(
    commission=2.0,        # $2 per contract
    margin=5000,           # $5000 margin per contract
    mult=10,               # multiplier
    stocklike=False,       # futures
    commtype=bt.CommInfoBase.COMM_FIXED
)

# Leverage trading
cerebro.broker.setcommission(
    commission=0.0005,
    leverage=2.0,          # 2x leverage
    margin=0.5             # 50% margin
)
```

**Parameters**:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `commission` | float | 0.0 | Commission amount |
| `margin` | float | None | Margin requirement |
| `mult` | float | 1.0 | Multiplier for value/profit |
| `commtype` | int | None | COMM_PERC (0) or COMM_FIXED (1) |
| `stocklike` | bool | False | Stock-like (True) or futures-like (False) |
| `percabs` | bool | True | Percentage as absolute (0.01 = 1%) |
| `interest` | float | 0.0 | Annual interest rate for shorts |
| `leverage` | float | 1.0 | Leverage multiplier |
| `automargin` | bool/float | False | Auto margin calculation |
| `name` | str | None | Asset name (None = default) |

### `addcommissioninfo(comminfo, name=None)`

Add a custom CommissionInfo object.

```python
class MyCommInfo(bt.CommInfoBase):
    def _getcommission(self, size, price, pseudoexec):
        return abs(size) * 5.0  # Fixed $5 commission

cerebro.broker.addcommissioninfo(MyCommInfo(), name='AAPL')
```

## Order Management

### `buy(owner, data, size, **kwargs)`

Create a buy order.

```python
# From strategy
order = self.buy(size=10)

# From cerebro
order = cerebro.broker.buy(
    owner=strategy,
    data=data,
    size=10,
    price=100.0
)
```

**Parameters**:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `owner` | Strategy | Required | Strategy creating the order |
| `data` | Data feed | Required | Data feed for the order |
| `size` | float | Required | Order size (positive) |
| `price` | float | None | Limit price |
| `plimit` | float | None | Limit price for stop-limit |
| `exectype` | Order.ExecType | None | Execution type |
| `valid` | Order.Valid | None | Validity period |
| `tradeid` | int | 0 | Trade identifier |
| `oco` | Order | None | One-cancels-other order |
| `trailamount` | float | None | Trailing amount |
| `trailpercent` | float | None | Trailing percent |
| `parent` | Order | None | Parent order (bracket) |
| `transmit` | bool | True | Transmit immediately |

### `sell(owner, data, size, **kwargs)`

Create a sell order. Same parameters as `buy()`.

```python
# Sell entire position
order = self.sell()

# Stop loss
order = self.sell(price=95.0, exectype=bt.Order.Stop)
```

### `cancel(order, bracket=False)`

Cancel a pending order.

```python
self.cancel(order)
```

### `get_orders_open(safe=False)`

Get iterable of pending orders.

```python
# Get orders (read-only)
open_orders = self.broker.get_orders_open()

# Get editable copies
open_orders = self.broker.get_orders_open(safe=True)
```

## Order Types

### Market Order

Execute at next available price.

```python
order = self.buy()  # Market order
```

### Limit Order

Execute at specified price or better.

```python
# Buy at 100 or lower
order = self.buy(price=100.0, exectype=bt.Order.Limit)
```

### Stop Order

Convert to market order when stop price is reached.

```python
# Stop loss at 95
order = self.sell(price=95.0, exectype=bt.Order.Stop)
```

### Stop-Limit Order

Convert to limit order when stop price is reached.

```python
# Stop at 95, limit at 94.5
order = self.sell(price=94.5, plimit=95.0, exectype=bt.Order.StopLimit)
```

### Close Order

Execute at session closing price.

```python
order = self.buy(exectype=bt.Order.Close)
```

### Trailing Stop Order

Stop price adjusts with price movement.

```python
order = self.sell(trailamount=2.0, exectype=bt.Order.StopTrail)
order = self.sell(trailpercent=0.05, exectype=bt.Order.StopTrail)
```

## Slippage Configuration

### Percentage Slippage

```python
cerebro.broker.set_slippage_perc(
    perc=0.001,        # 0.1% slippage
    slip_open=True,
    slip_limit=True,
    slip_match=True,
    slip_out=False
)
```

### Fixed Slippage

```python
cerebro.broker.set_slippage_fixed(
    fixed=0.02,        # $0.02 per share
    slip_open=True,
    slip_limit=True,
    slip_match=True
)
```

## Fund Mode

### `set_fundmode(fundmode, fundstartval=None)`

Enable fund-like performance tracking.

```python
# Enable fund mode with $100 initial NAV
cerebro.broker.set_fundmode(True, fundstartval=100.0)

# Get fund value
fund_value = cerebro.broker.get_fundvalue()
fund_shares = cerebro.broker.get_fundshares()
```

### `set_fundstartval(fundstartval)`

Set starting value for fund tracking.

```python
cerebro.broker.set_fundstartval(100.0)
```

## Other Configuration Methods

### `set_coc(coc)`

Enable/disable Cheat-On-Close.

```python
cerebro.broker.set_coc(True)  # Allow same-day execution
```

### `set_coo(coo)`

Enable/disable Cheat-On-Open.

```python
cerebro.broker.set_coo(True)
```

### `set_checksubmit(checksubmit)`

Enable/disable cash/margin checking before submission.

```python
cerebro.broker.set_checksubmit(False)  # Disable checks
```

### `set_filler(filler)`

Set volume filler for partial execution.

```python
def my_filler(order, price, ago):
    # Return executable size based on volume
    volume = order.data.volume[ago]
    return min(order.executed.remsize, volume * 0.1)

cerebro.broker.set_filler(my_filler)
```

## Order History

### `add_order_history(orders, notify=True)`

Add historical orders to broker.

```python
# Format: [datetime, size, price, data_index]
orders = [
    [datetime(2023, 1, 1), 100, 150.0, 0],
    [datetime(2023, 1, 2), -100, 155.0, 0],
]
cerebro.broker.add_order_history(orders, notify=False)
```

### `set_fund_history(fund)`

Set fund history for tracking.

```python
# Format: [datetime, share_value, net_asset_value]
fund_history = [
    [datetime(2023, 1, 1), 100.0, 100000.0],
    [datetime(2023, 1, 2), 101.5, 101500.0],
]
cerebro.broker.set_fund_history(fund_history)
```

## Commission Info Classes

### CommInfoBase

Base commission scheme class.

```python
comminfo = bt.CommInfoBase(
    commission=0.001,
    margin=5000,
    mult=10,
    stocklike=False,
    commtype=bt.CommInfoBase.COMM_PERC,
    leverage=2.0
)
```

### CommissionInfo

Standard commission scheme (percabs=True by default).

### ComminfoDC

Digital currency commission scheme.

```python
cerebro.broker.setcommission(
    commission=0.001,
    margin=0.1,
    mult=10,
    interest=3.0
)
```

### ComminfoFuturesPercent

Futures percentage commission.

### ComminfoFuturesFixed

Futures fixed commission.

### ComminfoFundingRate

Funding rate for perpetual futures.

## Built-in Broker Implementations

### BackBroker

Default backtesting broker.

```python
# Automatic (default)
cerebro = bt.Cerebro()

# Manual
broker = bt.brokers.BackBroker(cash=100000)
cerebro.setbroker(broker)
```

### CCXTBroker

Cryptocurrency exchange broker (requires ccxt).

```python
import ccxt
exchange = ccxt.binance()

broker = bt.brokers.CCXTBroker(
    exchange=exchange,
    wallet_exposure=0.33  # Use 33% of wallet
)
cerebro.setbroker(broker)
```

### CTPBroker

China futures broker (requires ctpbee).

### IBBroker

Interactive Brokers broker (requires ibpy).

### OandaBroker

OANDA broker (requires oandapy).

### VCBroker

VisualChart broker.

## Full Example

```python
import backtrader as bt

class MyStrategy(bt.Strategy):
    def __init__(self):
        self.sma = bt.indicators.SMA(self.data.close, period=20)
        self.order = None

    def next(self):
        if self.order:
            return

        if not self.position:
            if self.data.close[0] > self.sma[0]:
                # Buy with limit order
                cash = self.broker.getcash()
                size = int(cash / self.data.close[0] * 0.95)
                self.order = self.buy(
                    size=size,
                    price=self.data.close[0] * 0.99,
                    exectype=bt.Order.Limit
                )
        else:
            if self.data.close[0] < self.sma[0]:
                # Sell with stop-loss
                self.order = self.sell(
                    size=self.position.size,
                    exectype=bt.Order.Stop,
                    price=self.position.price * 0.95
                )

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status == order.Completed:
            if order.isbuy():
                print(f'BUY: {order.executed.size:.2f} @ {order.executed.price:.2f}')
            else:
                print(f'SELL: {order.executed.size:.2f} @ {order.executed.price:.2f}')

        self.order = None

    def notify_trade(self, trade):
        if trade.isclosed:
            print(f'Trade P&L: {trade.pnl:.2f}, Comm: {trade.commission:.2f}')

# Create cerebro
cerebro = bt.Cerebro()

# Add strategy
cerebro.addstrategy(MyStrategy)

# Add data
data = bt.feeds.YahooFinanceData(dataname='AAPL', fromdate=datetime(2020, 1, 1))
cerebro.adddata(data)

# Set broker parameters
cerebro.broker.setcash(100000.0)
cerebro.broker.setcommission(commission=0.001)  # 0.1%

# Set slippage
cerebro.broker.set_slippage_perc(perc=0.0005)  # 0.05%

# Run
result = cerebro.run()
print(f'Final Value: {cerebro.broker.getvalue():.2f}')
```

## Next Steps

- [Strategy API](strategy.md) - Trading strategies
- [Indicators API](indicator.md) - Technical indicators
- [Analyzers API](analyzer.md) - Performance analysis
- [Data Feeds API](data-feeds.md) - Data sources
