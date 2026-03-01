---
title: Trading Strategies
description: Building effective trading strategies
---

# Trading Strategies

Strategies contain your trading logic and decision-making rules. This guide covers strategy development patterns and best practices.

## Strategy Template

```python
class MyStrategy(bt.Strategy):
    """
    Strategy description.

    Parameters:
        param1: Description
        param2: Description
    """

    params = (
        ('param1', 20),
        ('param2', 0.5),
    )

    def __init__(self):
        """
        Initialize indicators and calculations.
        Called once before backtesting starts.
        """
        # Your initialization code here
        pass

    def next(self):
        """
        Called for each bar.
        Contains your trading logic.
        """
        # Your trading logic here
        pass
```

## Order Management

### Market Orders

```python
class MyStrategy(bt.Strategy):
    def next(self):
        # Buy with default size
        self.buy()

        # Buy specific size
        self.buy(size=100)

        # Sell entire position
        self.sell()

        # Close existing position
        self.close()

        # Buy with percent of available cash
        self.buy(size=0.5)  # 50% of cash
```

### Limit Orders

```python
class MyStrategy(bt.Strategy):
    def next(self):
        # Buy at specific price or better
        order = self.buy(price=100.0)

        # Sell with limit price
        order = self.sell(limit=105.0)

        # Stop loss order
        order = self.sell(stop=95.0)

        # Stop limit order
        order = self.sell(stop=95.0, limit=94.5)
```

### Order Tracking

```python
class MyStrategy(bt.Strategy):
    def __init__(self):
        self.order = None

    def next(self):
        # Only place new order if no pending order
        if self.order:
            return

        # Place order and store reference
        self.order = self.buy()

    def notify_order(self, order):
        """Called when order status changes."""
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status in [order.Completed]:
            if order.isbuy():
                self.log(f'BUY EXECUTED, Price: {order.executed.price:.2f}')
            else:
                self.log(f'SELL EXECUTED, Price: {order.executed.price:.2f}')

        self.order = None  # Reset order reference
```

## Trade Notification

```python
class MyStrategy(bt.Strategy):
    def notify_trade(self, trade):
        """Called when trade is closed."""
        if not trade.isclosed:
            return

        self.log(f'Trade P&L: {trade.pnl:.2f}, '
                f'Commission: {trade.commission:.2f}')
```

## Position Management

### Checking Position

```python
class MyStrategy(bt.Strategy):
    def next(self):
        # Check if in position
        if self.position:
            self.log(f'Position size: {self.position.size}')
        else:
            self.log('No position')
```

### Position Sizing

```python
class MyStrategy(bt.Strategy):
    def __init__(self):
        self.sizer = bt.sizers.FixedSize(stake=0.1)  # 10% per trade

    def next(self):
        # Buy 10% of portfolio value
        self.buy(size=self.broker.getcash() * 0.1 / self.data.close[0])
```

## Stop Loss and Take Profit

```python
class MyStrategy(bt.Strategy):
    params = (
        ('stop_loss_pct', 0.02),   # 2% stop loss
        ('take_profit_pct', 0.05), # 5% take profit
    )

    def next(self):
        if not self.position:
            self.buy()
        else:
            entry_price = self.position.price
            current_price = self.data.close[0]

            # Calculate stop loss and take profit levels
            stop_loss = entry_price * (1 - self.p.stop_loss_pct)
            take_profit = entry_price * (1 + self.p.take_profit_pct)

            # Check if stop loss or take profit is hit
            if current_price <= stop_loss:
                self.sell()  # Stop loss

            elif current_price >= take_profit:
                self.sell()  # Take profit
```

## Multi-Strategy

```python
# Create multiple strategies
cerebro = bt.Cerebro()

cerebro.addstrategy(Strategy1, period=10)
cerebro.addstrategy(Strategy2, period=20)
cerebro.addstrategy(Strategy3, period=30)

# Each strategy runs independently
```

## Time-Based Trading

```python
import datetime

class MyStrategy(bt.Strategy):
    params = (
        ('trade_start_hour', 10),
        ('trade_end_hour', 15),
    )

    def next(self):
        # Only trade during specific hours
        current_time = self.data.datetime.time(0)

        if current_time.hour < self.p.trade_start_hour:
            return  # Too early

        if current_time.hour >= self.p.trade_end_hour:
            return  # Too late

        # Trading logic here
        self.buy()
```

## Strategy Logging

```python
class MyStrategy(bt.Strategy):
    def __init__(self):
        # Enable logging
        pass

    def next(self):
        # Log messages
        self.log(f'Close price: {self.data.close[0]:.2f}')

    def notify_order(self, order):
        self.log(f'Order status: {order.getstatusname()}')
```

## Strategy Parameters Optimization

```python
# Define parameter ranges
cerebro.optstrategy(
    MyStrategy,
    ma_period=range(10, 31, 5),      # 10, 15, 20, 25, 30
    threshold=[0.5, 1.0, 1.5]         # 0.5, 1.0, 1.5
)

# Run optimization
results = cerebro.run(maxcpu=1)  # Use 1 CPU core

# Get best result
best_result = results[0]
print(f'Best parameters: {best_result.params._getitems()}')
```

## Common Strategy Patterns

### Trend Following

```python
class TrendFollowing(bt.Strategy):
    params = (
        ('fast_period', 10),
        ('slow_period', 30),
    )

    def __init__(self):
        self.fast_ma = bt.indicators.SMA(self.data.close, period=self.p.fast_period)
        self.slow_ma = bt.indicators.SMA(self.data.close, period=self.p.slow_period)
        self.crossover = bt.indicators.CrossOver(self.fast_ma, self.slow_ma)

    def next(self):
        if self.crossover > 0:
            self.buy()  # Uptrend start
        elif self.crossover < 0:
            self.sell()  # Downtrend start
```

### Mean Reversion

```python
class MeanReversion(bt.Strategy):
    params = (
        ('period', 20),
        ('threshold', 2),  # Standard deviations
    )

    def __init__(self):
        self.sma = bt.indicators.SMA(self.data.close, period=self.p.period)
        self.stddev = bt.indicators.StdDev(self.data.close, period=self.p.period)
        self.upper_band = self.sma + self.stddev * self.p.threshold
        self.lower_band = self.sma - self.stddev * self.p.threshold

    def next(self):
        if self.data.close[0] < self.lower_band[0]:
            self.buy()  # Price too low, buy
        elif self.data.close[0] > self.upper_band[0]:
            self.sell()  # Price too high, sell
```

### Breakout

```python
class Breakout(bt.Strategy):
    params = (
        ('period', 20),
    )

    def __init__(self):
        self.high_band = bt.indicators.Highest(self.data.high, period=self.p.period)
        self.low_band = bt.indicators.Lowest(self.data.low, period=self.p.period)

    def next(self):
        if self.data.close[0] > self.high_band[-1]:
            self.buy()  # Breakout above

        elif self.data.close[0] < self.low_band[-1]:
            self.sell()  # Breakout below
```

## Next Steps

- [Analyzers](analyzers.md) - Evaluate strategy performance
- [Observers](observers.md) - Monitor strategy behavior
- [Plotting](plotting.md) - Visualize results
