---
title: Strategy Examples Library
description: Complete working examples of common trading strategies
---

# Strategy Examples Library

This section provides complete, working implementations of popular trading strategies. Each example includes the full source code, parameter descriptions, and expected performance characteristics.

## Table of Contents

- [Trend Following Strategy](#trend-following-strategy-dual-moving-average)
- [Mean Reversion Strategy](#mean-reversion-strategy-bollinger-bands)
- [Breakout Strategy](#breakout-strategy-donchian-channels)
- [Grid Trading Strategy](#grid-trading-strategy)
- [Arbitrage Strategy](#arbitrage-strategy-calendar-spread)
- [Momentum Strategy](#momentum-strategy-supertrend)

---

## Trend Following Strategy (Dual Moving Average)

### Overview

The dual moving average crossover strategy is one of the most fundamental trend-following approaches. It generates buy signals when the short-term moving average crosses above the long-term moving average (golden cross) and sell signals when the short-term crosses below (death cross).

### Strategy Code

```python
import backtrader as bt

class DualMovingAverageStrategy(bt.Strategy):
    """Dual moving average crossover trend-following strategy.

    This strategy buys when the short-term MA crosses above the long-term MA
    (golden cross) and sells when the short-term MA crosses below (death cross).

    Parameters:
        short_period (int): Period for short-term moving average (default: 10)
        long_period (int): Period for long-term moving average (default: 30)
        position_size (float): Fraction of available cash to use per trade (default: 0.95)
    """

    params = (
        ('short_period', 10),
        ('long_period', 30),
        ('position_size', 0.95),
    )

    def __init__(self):
        # Calculate moving averages
        self.short_ma = bt.indicators.SMA(self.data.close, period=self.p.short_period)
        self.long_ma = bt.indicators.SMA(self.data.close, period=self.p.long_period)

        # Crossover indicator: +1 for golden cross, -1 for death cross
        self.crossover = bt.indicators.CrossOver(self.short_ma, self.long_ma)

        # Track orders to avoid duplicate entries
        self.order = None

    def next(self):
        # Wait for pending order to complete
        if self.order:
            return

        # No position - look for entry
        if not self.position:
            if self.crossover > 0:  # Golden cross
                cash = self.broker.getcash()
                price = self.data.close[0]
                size = int(cash * self.p.position_size / price)
                if size > 0:
                    self.order = self.buy(size=size)
        else:
            # Have position - look for exit
            if self.crossover < 0:  # Death cross
                self.order = self.close()

    def notify_order(self, order):
        """Handle order status updates."""
        if order.status in [order.Submitted, order.Accepted]:
            return
        self.order = None
```

### Performance Expectations

- **Market Type**: Works best in trending markets
- **Whipsaw Risk**: High in ranging/consolidating markets
- **Win Rate**: Typically 35-45% (relies on few large wins)
- **Risk/Reward**: Can achieve 2:1 or better in strong trends

### Optimization Parameters

| Parameter | Range | Effect |
|-----------|-------|--------|
| short_period | 5-20 | Shorter = more signals, more noise |
| long_period | 20-60 | Longer = fewer signals, more lag |

---

## Mean Reversion Strategy (Bollinger Bands)

### Overview

Mean reversion strategies profit from price returning to its average value. Bollinger Bands provide dynamic support/resistance levels based on standard deviations from a moving average, identifying overbought and oversold conditions.

### Strategy Code

```python
import backtrader as bt

class BollingerBandsMeanReversion(bt.Strategy):
    """Bollinger Bands mean reversion strategy.

    This strategy identifies overbought/oversold conditions using Bollinger Bands
    and enters positions when price shows signs of reverting to the mean.

    Entry Rules:
        - Buy when price closes below lower band then rises above middle band
        - Sell when price closes above upper band then falls below middle band

    Parameters:
        period (int): Period for Bollinger Bands calculation (default: 20)
        devfactor (float): Standard deviation multiplier (default: 2.0)
    """

    params = (
        ('period', 20),
        ('devfactor', 2.0),
    )

    def __init__(self):
        # Bollinger Bands indicator
        self.bband = bt.indicators.BBands(
            self.data.close,
            period=self.p.period,
            devfactor=self.p.devfactor
        )

        # Track signals
        self.oversold = False  # Price broke below lower band
        self.overbought = False  # Price broke above upper band
        self.order = None

    def next(self):
        if self.order:
            return

        # Check for oversold condition
        if self.data.close[0] < self.bband.lines.bot[0]:
            self.oversold = True

        # Check for overbought condition
        if self.data.close[0] > self.bband.lines.top[0]:
            self.overbought = True

        # Entry: Price rose back above middle band after being oversold
        if self.oversold and self.data.close[0] > self.bband.lines.mid[0]:
            if not self.position:
                cash = self.broker.getcash()
                size = int(cash * 0.95 / self.data.close[0])
                self.order = self.buy(size=size)
                self.oversold = False

        # Entry: Short when price falls below middle band after being overbought
        if self.overbought and self.data.close[0] < self.bband.lines.mid[0]:
            if not self.position:
                cash = self.broker.getcash()
                size = int(cash * 0.95 / self.data.close[0])
                self.order = self.sell(size=size)
                self.overbought = False

        # Exit long positions
        if self.position and self.position.size > 0:
            if self.data.close[0] > self.bband.lines.top[0]:
                self.order = self.close()

        # Exit short positions
        if self.position and self.position.size < 0:
            if self.data.close[0] < self.bband.lines.bot[0]:
                self.order = self.close()

    def notify_order(self, order):
        """Handle order status updates."""
        if order.status in [order.Submitted, order.Accepted]:
            return
        self.order = None
```

### Performance Expectations

- **Market Type**: Works best in ranging/oscillating markets
- **Trend Risk**: Can suffer large losses in strong trending markets
- **Win Rate**: Typically 55-65%
- **Risk/Reward**: Aim for 1:1 to 1.5:1

### Optimization Parameters

| Parameter | Range | Effect |
|-----------|-------|--------|
| period | 15-30 | Affects band responsiveness |
| devfactor | 1.5-2.5 | Wider bands = fewer signals |

---

## Breakout Strategy (Donchian Channels)

### Overview

Breakout strategies trade momentum when price breaks through significant support or resistance levels. Donchian Channels use the highest high and lowest low over a period to define these levels, making them ideal for catching trending moves early.

### Strategy Code

```python
import backtrader as bt

class DonchianChannelBreakout(bt.Strategy):
    """Donchian Channel breakout strategy.

    This classic trend-following strategy buys when price breaks above
    the N-period high and sells when price breaks below the N-period low.

    Entry Rules:
        - Buy when price closes above the highest high of the period
        - Sell when price closes below the lowest low of the period

    Exit Rules:
        - Exit long when price closes below the lowest low
        - Exit short when price closes above the highest high

    Parameters:
        period (int): Lookback period for channel calculation (default: 20)
    """

    params = (
        ('period', 20),
    )

    def __init__(self):
        # Donchian Channel components
        self.highest = bt.indicators.Highest(self.data.high, period=self.p.period)
        self.lowest = bt.indicators.Lowest(self.data.low, period=self.p.period)
        self.order = None

    def next(self):
        if self.order:
            return

        # No position - look for breakout entry
        if not self.position:
            # Breakout above previous high
            if self.data.close[0] > self.highest[-1]:
                cash = self.broker.getcash()
                size = int(cash * 0.95 / self.data.close[0])
                if size > 0:
                    self.order = self.buy(size=size)

            # Breakdown below previous low
            elif self.data.close[0] < self.lowest[-1]:
                cash = self.broker.getcash()
                size = int(cash * 0.95 / self.data.close[0])
                if size > 0:
                    self.order = self.sell(size=size)

        # Long position - look for exit
        elif self.position.size > 0:
            if self.data.close[0] < self.lowest[-1]:
                self.order = self.close()

        # Short position - look for exit
        else:
            if self.data.close[0] > self.highest[-1]:
                self.order = self.close()

    def notify_order(self, order):
        """Handle order status updates."""
        if order.status in [order.Submitted, order.Accepted]:
            return
        self.order = None
```

### Performance Expectations

- **Market Type**: Excels in markets with clear trends
- **False Breakouts**: Common in choppy markets
- **Win Rate**: Typically 30-40% (depends on big trends)
- **Risk/Reward**: Can achieve 3:1 in strong trends

### Optimization Parameters

| Parameter | Range | Effect |
|-----------|-------|--------|
| period | 10-40 | Shorter = more breakouts, more false signals |

---

## Grid Trading Strategy

### Overview

Grid trading places buy and sell orders at regular intervals above and below a current price level. This strategy profits from market volatility and works best in ranging markets where price oscillates within a defined range.

### Strategy Code

```python
import backtrader as bt

class GridTradingStrategy(bt.Strategy):
    """Grid trading strategy for ranging markets.

    This strategy places a grid of buy orders below current price and
    sell orders above current price. As price moves, it fills orders
    at grid levels and takes profit at the next level.

    Parameters:
        grid_size (float): Price distance between grid levels (e.g., 0.01 for 1%)
        grid_levels (int): Number of grid levels above and below (default: 5)
        max_position (int): Maximum concurrent positions (default: 10)
    """

    params = (
        ('grid_size', 0.01),  # 1% grid
        ('grid_levels', 5),
        ('max_position', 10),
    )

    def __init__(self):
        self.grid_buy_orders = {}  # price -> order
        self.grid_sell_orders = {}  # price -> order
        self.grid_initialized = False
        self.base_price = None

    def next(self):
        current_price = self.data.close[0]

        # Initialize grid on first bar
        if not self.grid_initialized:
            self.base_price = current_price
            self.initialize_grid(current_price)
            self.grid_initialized = True
            return

        # Check for filled orders and place opposite orders
        self.check_filled_orders(current_price)

        # Maintain grid levels
        self.rebalance_grid(current_price)

    def initialize_grid(self, current_price):
        """Initialize buy and sell grid levels."""
        for i in range(1, self.p.grid_levels + 1):
            buy_price = round(current_price * (1 - self.p.grid_size * i), 2)
            sell_price = round(current_price * (1 + self.p.grid_size * i), 2)

            # Place buy orders below current price
            if len([o for o in self.grid_buy_orders.values() if o]) < self.p.max_position:
                order = self.buy(price=buy_price, exectype=bt.Order.Limit)
                self.grid_buy_orders[buy_price] = order

            # Place sell orders above current price
            if len([o for o in self.grid_sell_orders.values() if o]) < self.p.max_position:
                order = self.sell(price=sell_price, exectype=bt.Order.Limit)
                self.grid_sell_orders[sell_price] = order

    def check_filled_orders(self, current_price):
        """Check for filled orders and place profit-taking orders."""
        # Check if any buy orders were filled
        for price, order in list(self.grid_buy_orders.items()):
            if order and order.status == order.Completed:
                # Place sell order at next grid level for profit
                profit_price = round(price * (1 + self.p.grid_size), 2)
                if profit_price not in self.grid_sell_orders:
                    self.sell(price=profit_price, size=order.executed.size,
                             exectype=bt.Order.Limit)
                del self.grid_buy_orders[price]

        # Check if any sell orders were filled
        for price, order in list(self.grid_sell_orders.items()):
            if order and order.status == order.Completed:
                # Place buy order at next grid level for profit
                profit_price = round(price * (1 - self.p.grid_size), 2)
                if profit_price not in self.grid_buy_orders:
                    self.buy(price=profit_price, size=abs(order.executed.size),
                            exectype=bt.Order.Limit)
                del self.grid_sell_orders[price]

    def rebalance_grid(self, current_price):
        """Maintain grid levels as price moves."""
        # Cancel orders that are too far from current price
        for price, order in list(self.grid_buy_orders.items()):
            if order and price < current_price * (1 - self.p.grid_size * (self.p.grid_levels + 2)):
                self.cancel(order)
                del self.grid_buy_orders[price]

        for price, order in list(self.grid_sell_orders.items()):
            if order and price > current_price * (1 + self.p.grid_size * (self.p.grid_levels + 2)):
                self.cancel(order)
                del self.grid_sell_orders[price]

        # Add new grid levels as needed
        active_orders = len([o for o in self.grid_buy_orders.values() if o]) + \
                       len([o for o in self.grid_sell_orders.values() if o])

        if active_orders < self.p.max_position:
            self.initialize_grid(current_price)
```

### Performance Expectations

- **Market Type**: Optimized for ranging/consolidating markets
- **Trend Risk**: Can accumulate losing positions in strong trends
- **Win Rate**: High win rate, small profits per trade
- **Requirements**: Sufficient capital for multiple positions

### Optimization Parameters

| Parameter | Range | Effect |
|-----------|-------|--------|
| grid_size | 0.005-0.02 | Smaller = more trades, more exposure |
| grid_levels | 3-10 | More levels = more capital required |
| max_position | 5-20 | Limit risk exposure |

---

## Arbitrage Strategy (Calendar Spread)

### Overview

Calendar spread arbitrage profits from the price difference between near-term and far-term futures contracts. This market-neutral strategy trades the relationship between two related instruments rather than directional price movement.

### Strategy Code

```python
import backtrader as bt

class CalendarSpreadArbitrage(bt.Strategy):
    """Calendar spread arbitrage strategy.

    Trades the price difference between near-term and far-term contracts.
    Goes long the spread when near price - far price is low (contango),
    goes short the spread when near price - far price is high (backwardation).

    Parameters:
        spread_low (float): Lower threshold to enter long spread
        spread_high (float): Upper threshold to enter short spread
    """

    params = (
        ('spread_low', 0.06),
        ('spread_high', 0.52),
    )

    def __init__(self):
        # Assumes data[0] is near contract, data[1] is far contract
        self.near = self.datas[0]
        self.far = self.datas[1]
        self.spread_position = 0  # 1=long spread, -1=short spread, 0=flat
        self.order = None

    def next(self):
        if self.order:
            return

        current_spread = self.near.close[0] - self.far.close[0]

        # No position - look for entry
        if self.spread_position == 0:
            # Spread is low - buy near, sell far (long spread)
            if current_spread < self.p.spread_low:
                self.order = self.buy(data=self.near, size=1)
                self.order = self.sell(data=self.far, size=1)
                self.spread_position = 1

            # Spread is high - sell near, buy far (short spread)
            elif current_spread > self.p.spread_high:
                self.order = self.sell(data=self.near, size=1)
                self.order = self.buy(data=self.far, size=1)
                self.spread_position = -1

        # Long spread position - look for exit
        elif self.spread_position == 1:
            if current_spread > self.p.spread_high:
                self.close(data=self.near)
                self.close(data=self.far)
                self.spread_position = 0

        # Short spread position - look for exit
        elif self.spread_position == -1:
            if current_spread < self.p.spread_low:
                self.close(data=self.near)
                self.close(data=self.far)
                self.spread_position = 0

    def notify_order(self, order):
        """Handle order status updates."""
        if order.status in [order.Submitted, order.Accepted]:
            return
        self.order = None

    def notify_trade(self, trade):
        """Log trade completion."""
        if trade.isclosed:
            print(f'Trade P&L: {trade.pnl:.2f}, Commission: {trade.commission:.2f}')
```

### Performance Expectations

- **Market Type**: Futures markets with term structure
- **Market Neutral**: Profits from relative value, not direction
- **Win Rate**: High win rate, steady profits
- **Capital Efficiency**: Requires margin for both legs

### Optimization Parameters

| Parameter | Range | Effect |
|-----------|-------|--------|
| spread_low | Varies by market | Entry for long spread |
| spread_high | Varies by market | Entry for short spread |

---

## Momentum Strategy (SuperTrend)

### Overview

The SuperTrend indicator combines trend direction with volatility to produce clear buy and sell signals. It's particularly effective in markets with sustained trends and automatically adjusts to changing volatility conditions.

### Strategy Code

```python
import backtrader as bt

class SuperTrendIndicator(bt.Indicator):
    """SuperTrend indicator.

    A trend-following indicator that uses ATR to calculate dynamic
    support/resistance levels.
    """

    lines = ('supertrend', 'direction')
    params = dict(
        period=10,
        multiplier=3.0,
    )

    def __init__(self):
        self.atr = bt.indicators.ATR(self.data, period=self.p.period)
        self.hl2 = (self.data.high + self.data.low) / 2.0

    def next(self):
        if len(self) < self.p.period + 1:
            self.lines.supertrend[0] = self.hl2[0]
            self.lines.direction[0] = 1
            return

        atr = self.atr[0]
        hl2 = self.hl2[0]

        upper_band = hl2 + self.p.multiplier * atr
        lower_band = hl2 - self.p.multiplier * atr

        prev_supertrend = self.lines.supertrend[-1]
        prev_direction = self.lines.direction[-1]

        if prev_direction == 1:  # Uptrend
            if self.data.close[0] < prev_supertrend:
                self.lines.supertrend[0] = upper_band
                self.lines.direction[0] = -1
            else:
                self.lines.supertrend[0] = max(lower_band, prev_supertrend)
                self.lines.direction[0] = 1
        else:  # Downtrend
            if self.data.close[0] > prev_supertrend:
                self.lines.supertrend[0] = lower_band
                self.lines.direction[0] = 1
            else:
                self.lines.supertrend[0] = min(upper_band, prev_supertrend)
                self.lines.direction[0] = -1


class SuperTrendStrategy(bt.Strategy):
    """SuperTrend momentum strategy.

    Goes long when trend turns up and exits when trend turns down.

    Parameters:
        period (int): ATR period for SuperTrend calculation (default: 10)
        multiplier (float): ATR multiplier for band width (default: 3.0)
    """

    params = (
        ('period', 10),
        ('multiplier', 3.0),
    )

    def __init__(self):
        self.supertrend = SuperTrendIndicator(
            self.data,
            period=self.p.period,
            multiplier=self.p.multiplier
        )
        self.order = None

    def next(self):
        if self.order:
            return

        # Buy when trend turns from down to up
        if not self.position:
            if (self.supertrend.direction[0] == 1 and
                self.supertrend.direction[-1] == -1):
                cash = self.broker.getcash()
                size = int(cash * 0.95 / self.data.close[0])
                if size > 0:
                    self.order = self.buy(size=size)
        else:
            # Exit when trend turns down
            if self.supertrend.direction[0] == -1:
                self.order = self.close()

    def notify_order(self, order):
        """Handle order status updates."""
        if order.status in [order.Submitted, order.Accepted]:
            return
        self.order = None
```

### Performance Expectations

- **Market Type**: Trending markets with sustained moves
- **Whipsaw Risk**: Moderate in choppy markets
- **Win Rate**: Typically 40-50%
- **Risk/Reward**: Can achieve 2:1 or better

### Optimization Parameters

| Parameter | Range | Effect |
|-----------|-------|--------|
| period | 7-15 | Shorter = more sensitive |
| multiplier | 2.0-4.0 | Higher = fewer signals, better trend filter |

---

## Running These Examples

To use any of these strategies:

```python
import backtrader as bt
import backtrader.feeds as btfeeds

# Create Cerebro engine
cerebro = bt.Cerebro()

# Add your chosen strategy
cerebro.addstrategy(DualMovingAverageStrategy, short_period=10, long_period=30)

# Load data
data = btfeeds.GenericCSVData(
    dataname='your_data.csv',
    dtformat='%Y-%m-%d',
    datetime=0,
    open=1,
    high=2,
    low=3,
    close=4,
    volume=5,
    openinterest=-1
)
cerebro.adddata(data)

# Set initial capital and commission
cerebro.broker.setcash(100000)
cerebro.broker.setcommission(commission=0.001)

# Run
results = cerebro.run()

# Plot
cerebro.plot()
```

## Next Steps

- [Custom Indicators](../user_guide/indicators.md) - Create your own indicators
- [Analyzers](../user_guide/analyzers.md) - Evaluate strategy performance
- [Optimization](../user_guide/optimization.md) - Find optimal parameters
