- --

title: Common Patterns Cookbook
description: Practical trading patterns and implementations

- --

# Common Patterns Cookbook

This cookbook provides practical implementations of common trading patterns in Backtrader. Each pattern includes a complete, working example with explanations.

## Table of Contents

1. [Stop Loss and Take Profit](#stop-loss-and-take-profit)
2. [Dynamic Position Sizing](#dynamic-position-sizing)
3. [Multi-Indicator Combination](#multi-indicator-combination)
4. [Time-Based Trading Filters](#time-based-trading-filters)
5. [Event-Driven Patterns](#event-driven-patterns)
6. [Pyramiding Positions](#pyramiding-positions)
7. [Trailing Stop Implementation](#trailing-stop-implementation)
8. [Bracket Orders](#bracket-orders)

- --

## Stop Loss and Take Profit

### Fixed Percentage Stop Loss

```python
import backtrader as bt

class FixedStopLoss(bt.Strategy):
    """
    Strategy with fixed percentage stop loss.

    Parameters:
        stop_loss_pct: Stop loss percentage (default: 2%)
    """

    params = (
        ('stop_loss_pct', 0.02),
    )

    def __init__(self):

# Track entry price for stop loss calculation
        self.entry_price = None
        self.order = None

    def next(self):
        if self.order:
            return  # Wait for pending order

        if not self.position:

# Entry logic - buy when price crosses above SMA
            if len(self.data) >= 20:
                if self.data.close[0] > self.data.close[-1]:
                    self.order = self.buy()
                    self.entry_price = self.data.close[0]
        else:

# Check stop loss
            current_price = self.data.close[0]
            stop_price = self.entry_price *(1 - self.p.stop_loss_pct)

            if current_price <= stop_price:
                self.order = self.close()  # Stop loss hit

    def notify_order(self, order):
        if order.status in [order.Completed]:
            self.order = None
            if not self.position:
                self.entry_price = None

```bash

### ATR-Based Stop Loss

```python
class ATRStopLoss(bt.Strategy):
    """
    Strategy with ATR-based dynamic stop loss.

    Uses Average True Range to set stop loss at a multiple
    of ATR below entry price, adapting to volatility.
    """

    params = (
        ('atr_period', 14),
        ('atr_multiplier', 2.0),
    )

    def __init__(self):
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.entry_price = None
        self.stop_price = None
        self.order = None

    def next(self):
        if self.order:
            return

        if not self.position:

# Simple entry: buy when price rises
            if len(self.data) > self.p.atr_period:
                if self.data.close[0] > self.data.close[-1]:
                    self.order = self.buy()
                    self.entry_price = self.data.close[0]

# Set initial stop loss
                    self.stop_price = self.entry_price - (self.atr[0]*self.p.atr_multiplier)
        else:

# Check if stop loss is hit
            if self.data.close[0] <= self.stop_price:
                self.order = self.close()
            else:

# Trailing stop: update stop price if price moves favorably
                new_stop = self.data.close[0] - (self.atr[0]*self.p.atr_multiplier)
                if new_stop > self.stop_price:
                    self.stop_price = new_stop

```bash

### Take Profit with Risk-Reward Ratio

```python
class RiskRewardStrategy(bt.Strategy):
    """
    Strategy with fixed risk-reward ratio.

    For every unit of risk, targets multiple units of reward.
    """

    params = (
        ('stop_loss_pct', 0.02),
        ('risk_reward_ratio', 2.0),  # 2:1 reward to risk
    )

    def __init__(self):
        self.entry_price = None
        self.stop_price = None
        self.target_price = None
        self.order = None

    def next(self):
        if self.order:
            return

        if not self.position:

# Entry condition
            if len(self.data) >= 20:
                sma = bt.indicators.SMA(self.data.close, period=20)
                if self.data.close[0] > sma[0] and self.data.close[-1] <= sma[-1]:
                    self.order = self.buy()
                    self.entry_price = self.data.close[0]

# Calculate stop and target
                    self.stop_price = self.entry_price*(1 - self.p.stop_loss_pct)
                    risk = self.entry_price - self.stop_price
                    self.target_price = self.entry_price + (risk*self.p.risk_reward_ratio)
        else:
            current_price = self.data.close[0]

# Check stop loss
            if current_price <= self.stop_price:
                self.order = self.close()

# Check take profit
            elif current_price >= self.target_price:
                self.order = self.close()

```bash

- --

## Dynamic Position Sizing

### Percent of Equity Sizing

```python
class PercentEquitySizer(bt.Sizer):
    """
    Sizer that allocates a fixed percentage of equity per trade.

    Parameters:
        percents: Percentage of equity to use (default: 20)
    """

    params = (('percents', 20),)

    def _getsizing(self, comminfo, cash, data, isbuy):
        if isbuy:

# Calculate position size based on percentage of equity
            position_value = self.broker.getvalue()*(self.p.percents / 100)
            size = position_value / data.close[0]
            return int(size)
        return self.broker.getposition(data).size

# Usage in strategy

class PercentEquityStrategy(bt.Strategy):
    params = (('trade_size', 20),)  # 20% of equity per trade

    def __init__(self):
        self.setsizer(PercentEquitySizer(percents=self.p.trade_size))

```bash

### Volatility-Adjusted Sizing

```python
class VolatilitySizer(bt.Sizer):
    """
    Sizer that adjusts position size based on volatility.

    Uses ATR to determine position size - smaller positions
    in high volatility, larger positions in low volatility.
    """

    params = (
        ('atr_period', 14),
        ('atr_multiplier', 2.0),
        ('risk_pct', 0.02),  # 2% of equity at risk
    )

    def _getsizing(self, comminfo, cash, data, isbuy):
        if not isbuy:
            return self.broker.getposition(data).size

# Calculate ATR
        if len(data) < self.p.atr_period:
            return 0

        atr = bt.indicators.ATR(data, period=self.p.atr_period)
        current_atr = atr[0] if len(atr) > 0 else data.close[0]*0.02

# Calculate position size based on risk
        risk_amount = self.broker.getvalue()*self.p.risk_pct
        stop_distance = current_atr*self.p.atr_multiplier

        if stop_distance > 0:
            size = risk_amount / stop_distance
            return int(size)

        return 0

```bash

### Kelly Criterion Sizing

```python
class KellySizer(bt.Sizer):
    """
    Position sizing using the Kelly Criterion.

    Kelly % = (Win%*WinLossRatio - Loss%) / WinLossRatio

    Parameters:
        win_rate: Historical win rate (0-1)
        avg_win: Average winning trade amount
        avg_loss: Average losing trade amount (positive value)
        max_position_pct: Maximum position as percentage of equity
    """

    params = (
        ('win_rate', 0.55),
        ('avg_win', 100),
        ('avg_loss', 80),
        ('max_position_pct', 25),
    )

    def _getsizing(self, comminfo, cash, data, isbuy):
        if not isbuy:
            return self.broker.getposition(data).size

# Calculate Kelly percentage
        win_loss_ratio = self.p.avg_win / self.p.avg_loss
        kelly_pct = (self.p.win_rate*win_loss_ratio - (1 - self.p.win_rate)) / win_loss_ratio

# Apply fractional Kelly (half-Kelly for safety)
        kelly_pct = max(0, min(kelly_pct*0.5, self.p.max_position_pct / 100))

# Calculate position size
        position_value = self.broker.getvalue()*kelly_pct
        size = position_value / data.close[0]

        return int(size)

```bash

- --

## Multi-Indicator Combination

### Trend + Momentum + Volatility

```python
class TripleConfirmationStrategy(bt.Strategy):
    """
    Combines trend, momentum, and volatility indicators.

    Entry conditions (all must be true):

    1. Trend: Price above 200-period SMA
    2. Momentum: RSI below 30 (oversold)
    3. Volatility: ATR above average (expanding volatility)

    """

    params = (
        ('trend_period', 200),
        ('rsi_period', 14),
        ('rsi_threshold', 30),
        ('atr_period', 14),
    )

    def __init__(self):

# Trend indicator
        self.sma_trend = bt.indicators.SMA(self.data.close, period=self.p.trend_period)

# Momentum indicator
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)

# Volatility indicator
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.atr_sma = bt.indicators.SMA(self.atr, period=self.p.atr_period)

    def next(self):
        if len(self.data) < self.p.trend_period:
            return

        if not self.position:

# Check all three conditions
            trend_ok = self.data.close[0] > self.sma_trend[0]
            momentum_ok = self.rsi[0] < self.p.rsi_threshold
            volatility_ok = self.atr[0] > self.atr_sma[0]

            if trend_ok and momentum_ok and volatility_ok:
                self.buy()
        else:

# Exit when RSI becomes overbought
            if self.rsi[0] > 70:
                self.sell()

```bash

### MACD + Stochastic Confirmation

```python
class MACDStochasticStrategy(bt.Strategy):
    """
    Combines MACD and Stochastic for entry confirmation.

    Buy when:

    - MACD line crosses above signal line
    - Stochastic %K crosses above %D from below 20

    Sell when:

    - MACD line crosses below signal line
    - Stochastic %K crosses below %D from above 80

    """

    params = (
        ('macd_fast', 12),
        ('macd_slow', 26),
        ('macd_signal', 9),
        ('stoch_period', 14),
        ('stoch_d_period', 3),
    )

    def __init__(self):

# MACD indicators
        self.macd = bt.indicators.MACD(self.data.close,
                                       period_me1=self.p.macd_fast,
                                       period_me2=self.p.macd_slow,
                                       period_signal=self.p.macd_signal)
        self.macd_cross = bt.indicators.CrossOver(self.macd.macd, self.macd.signal)

# Stochastic indicators
        self.stoch = bt.indicators.Stochastic(self.data,
                                              period=self.p.stoch_period,
                                              period_dfast=self.p.stoch_d_period)
        self.stoch_cross = bt.indicators.CrossOver(self.stoch.percK,
                                                   self.stoch.percD)

    def next(self):
        if not self.position:

# Buy signal: MACD crossover up + Stochastic crossover up from oversold
            if (self.macd_cross[0] > 0 and
                self.stoch_cross[0] > 0 and
                self.stoch.percK[-1] < 20):
                self.buy()
        else:

# Sell signal: MACD crossover down + Stochastic crossover down from overbought
            if (self.macd_cross[0] < 0 and
                self.stoch_cross[0] < 0 and
                self.stoch.percK[-1] > 80):
                self.sell()

```bash

### Bollinger Band + RSI Reversal

```python
class BBRSIReversalStrategy(bt.Strategy):
    """
    Mean reversion strategy combining Bollinger Bands and RSI.

    Buy when:

    - Price touches lower Bollinger Band
    - RSI is below 30

    Sell when:

    - Price touches upper Bollinger Band
    - RSI is above 70

    """

    params = (
        ('bb_period', 20),
        ('bb_dev', 2.0),
        ('rsi_period', 14),
    )

    def __init__(self):
        self.bb = bt.indicators.BollingerBands(self.data.close,
                                               period=self.p.bb_period,
                                               devfactor=self.p.bb_dev)
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)

    def next(self):
        if not self.position:

# Buy at lower band with RSI confirmation
            if (self.data.close[0] <= self.bb.lines.bot[0] and
                self.rsi[0] < 30):
                self.buy()
        else:

# Sell at upper band with RSI confirmation
            if (self.data.close[0] >= self.bb.lines.top[0] and
                self.rsi[0] > 70):
                self.sell()

```bash

- --

## Time-Based Trading Filters

### Trading Session Filter

```python
import datetime

class SessionFilterStrategy(bt.Strategy):
    """
    Only trades during specific hours of the day.

    Parameters:
        start_hour: Trading session start hour (24-hour format)
        end_hour: Trading session end hour (24-hour format)
        exclude_first_bars: Skip first N bars of session
    """

    params = (
        ('start_hour', 10),
        ('end_hour', 15),
        ('exclude_first_bars', 5),
    )

    def __init__(self):
        self.bars_in_session = 0
        self.was_in_session = False

    def next(self):
        current_time = self.data.datetime.time(0)
        in_session = (self.p.start_hour <= current_time.hour < self.p.end_hour)

# Reset counter when entering new session
        if in_session and not self.was_in_session:
            self.bars_in_session = 0
        elif in_session:
            self.bars_in_session += 1

        self.was_in_session = in_session

# Skip if outside session or during warmup period
        if not in_session or self.bars_in_session < self.p.exclude_first_bars:
            return

# Trading logic here
        if not self.position:
            self.buy()

```bash

### Day of Week Filter

```python
class DayOfWeekStrategy(bt.Strategy):
    """
    Only trades on specific days of the week.

    Parameters:
        trade_days: Tuple of weekdays to trade (0=Monday, 6=Sunday)
    """

    params = (
        ('trade_days', (0, 1, 2, 3, 4)),  # Monday to Friday
    )

    def next(self):
        current_weekday = self.data.datetime.date(0).weekday()

# Only trade on specified days
        if current_weekday not in self.p.trade_days:
            return

# Trading logic
        if not self.position and len(self.data) >= 20:
            sma = bt.indicators.SMA(self.data.close, period=20)
            if self.data.close[0] > sma[0]:
                self.buy()

```bash

### Month/Season-Based Filter

```python
class SeasonalStrategy(bt.Strategy):
    """
    Implements seasonal trading patterns.

    Example: "Sell in May and go away" - avoid trading summer months.
    """

    params = (
        ('avoid_months', (5, 6, 7, 8)),  # May to August
    )

    def next(self):
        current_month = self.data.datetime.date(0).month

# Skip trading during specified months
        if current_month in self.p.avoid_months:

# Close any existing position
            if self.position:
                self.close()
            return

# Trading logic for active months
        if not self.position and len(self.data) >= 20:
            if self.data.close[0] > self.data.close[-1]:
                self.buy()

```bash

### End-of-Day Exit

```python
class EndOfDayExit(bt.Strategy):
    """
    Closes all positions before market close.

    Useful for day trading strategies that don't want overnight exposure.
    """

    params = (
        ('exit_hour', 15),
        ('exit_minute', 30),
    )

    def __init__(self):
        self.exit_triggered = False

    def next(self):
        current_time = self.data.datetime.time(0)
        exit_time = datetime.time(self.p.exit_hour, self.p.exit_minute)

# Close positions at specified time
        if current_time >= exit_time:
            if self.position and not self.exit_triggered:
                self.close()
                self.exit_triggered = True
        else:
            self.exit_triggered = False

# Trading logic before exit time
        if current_time < exit_time and not self.position:
            if len(self.data) >= 20:
                if self.data.close[0] > self.data.close[-1]:
                    self.buy()

```bash

- --

## Event-Driven Patterns

### Order Status Notification

```python
class OrderNotificationStrategy(bt.Strategy):
    """
    Comprehensive order tracking and notification.

    Handles all order states: Submitted, Accepted, Partial, Completed, Cancelled, Rejected.
    """

    def __init__(self):
        self.order = None
        self.pending_orders = {}  # Track orders by reference

    def next(self):

# Only place new order if none pending
        if self.order:
            return

        if not self.position:
            self.order = self.buy(size=100)

    def notify_order(self, order):
        """Called when order status changes."""

# Order is still pending
        if order.status in [order.Submitted, order.Accepted]:
            return

# Order completed
        if order.status == order.Completed:
            if order.isbuy():
                self.log(f'BUY EXECUTED: Price {order.executed.price:.2f}, '
                        f'Cost {order.executed.value:.2f}, '
                        f'Comm {order.executed.comm:.2f}')
            else:
                self.log(f'SELL EXECUTED: Price {order.executed.price:.2f}, '
                        f'Cost {order.executed.value:.2f}, '
                        f'Comm {order.executed.comm:.2f}')

# Order cancelled
        elif order.status == order.Cancelled:
            self.log(f'ORDER CANCELLED: {order.getstatusname()}')

# Order rejected
        elif order.status == order.Rejected:
            self.log(f'ORDER REJECTED: {order.getstatusname()}')

# Order margin
        elif order.status == order.Margin:
            self.log(f'ORDER MARGIN: {order.getstatusname()}')

# Reset order reference
        self.order = None

    def log(self, txt):
        """Logging helper."""
        dt = self.data.datetime.date(0)
        print(f'{dt.isoformat()}: {txt}')

```bash

### Trade Notification

```python
class TradeNotificationStrategy(bt.Strategy):
    """
    Track completed trades with profit/loss calculations.
    """

    params = (
        ('print_log', True),
    )

    def notify_trade(self, trade):
        """
        Called when a trade is completed (position closed).

        Provides comprehensive trade statistics.
        """
        if not trade.isclosed:
            return

# Calculate trade metrics
        pnl_net = trade.pnlnet  # Net profit (after commission)
        pnl_comm = trade.commission  # Commission paid
        pnl_gross = trade.pnl  # Gross profit (before commission)

        log_txt = (
            f'TRADE CLOSED | '

            f'PnL: ${pnl_net:.2f} | '

            f'Gross: ${pnl_gross:.2f} | '

            f'Comm: ${pnl_comm:.2f}'
        )

        if self.p.print_log:
            self.log(log_txt)

    def log(self, txt):
        dt = self.data.datetime.date(0)
        print(f'{dt.isoformat()}: {txt}')

```bash

### Data Notification (Live Trading)

```python
class DataNotificationStrategy(bt.Strategy):
    """
    Handles data feed events for live trading.

    Useful for detecting connection issues, data delays, etc.
    """

    def __init__(self):
        self.last_data_time = None
        self.data_gap_detected = False

    def notify_data(self, data, status,*args, **kwargs):
        """Called when data feed status changes."""

# Data is live
        if status == data.LIVE:
            self.log('Data feed is LIVE')

# Data is delayed
        elif status == data.DELAYED:
            self.log('Data feed is DELAYED')

# Data connection lost
        elif status == data.DISCONNECTED:
            self.log('Data feed DISCONNECTED - Check connection')
            self.data_gap_detected = True

# Data reconnected
        elif status == data.CONNECTED:
            if self.data_gap_detected:
                self.log('Data feed RECONNECTED')
                self.data_gap_detected = False

# New data arriving
        if hasattr(data, 'datetime') and len(data) > 0:
            self.last_data_time = data.datetime.datetime(0)

    def log(self, txt):
        print(f'{self.data.datetime.datetime(0)}: {txt}')

```bash

### Cash Value Notification

```python
class CashNotificationStrategy(bt.Strategy):
    """
    Monitor account equity and cash value changes.

    Useful for risk management and performance tracking.
    """

    def __init__(self):
        self.starting_cash = self.broker.getcash()
        self.peak_equity = self.starting_cash
        self.drawdown = 0.0
        self.max_drawdown = 0.0

    def next(self):
        current_equity = self.broker.getvalue()

# Update peak equity
        if current_equity > self.peak_equity:
            self.peak_equity = current_equity

# Calculate drawdown
        if self.peak_equity > 0:
            self.drawdown = (self.peak_equity - current_equity) / self.peak_equity
            self.max_drawdown = max(self.max_drawdown, self.drawdown)

# Risk management: stop trading if drawdown exceeds threshold
        if self.drawdown > 0.20:  # 20% max drawdown
            if self.position:
                self.log(f'Max drawdown exceeded: {self.drawdown:.1%}')
                self.close()

    def stop(self):
        """Called when backtesting ends."""
        final_equity = self.broker.getvalue()
        total_return = (final_equity - self.starting_cash) / self.starting_cash

        print('=' *50)
        print('FINAL RESULTS')
        print('='*50)
        print(f'Starting Cash: ${self.starting_cash:.2f}')
        print(f'Final Equity:  ${final_equity:.2f}')
        print(f'Total Return:  {total_return:.2%}')
        print(f'Max Drawdown:  {self.max_drawdown:.2%}')
        print('='*50)

    def log(self, txt):
        dt = self.data.datetime.date(0)
        print(f'{dt.isoformat()}: {txt}')

```bash

- --

## Pyramiding Positions

### Fixed Pyramid Levels

```python
class PyramidStrategy(bt.Strategy):
    """
    Pyramiding: Adding to winning positions.

    Parameters:
        pyramid_levels: Number of additional entries (default: 3)
        pyramid_distance: Price move % before adding (default: 2%)
        level_size: Size of each pyramid entry as % of initial (default: 50%)
    """

    params = (
        ('pyramid_levels', 3),
        ('pyramid_distance', 0.02),  # 2% price move
        ('level_size', 0.5),  # 50% of initial position
    )

    def __init__(self):
        self.entry_prices = []  # Track entry prices
        self.current_level = 0
        self.initial_size = 0
        self.order = None

    def next(self):
        if self.order:
            return

        if not self.position:

# Initial entry
            self.order = self.buy(size=100)
            self.initial_size = 100
            self.entry_prices.append(self.data.close[0])
            self.current_level = 0
        else:

# Check if we can add to position
            if (self.current_level < self.p.pyramid_levels and
                len(self.entry_prices) > 0):

                last_entry = self.entry_prices[-1]
                price_move_pct = (self.data.close[0] - last_entry) / last_entry

# Add to position if price moved favorably
                if price_move_pct >= self.p.pyramid_distance:
                    add_size = int(self.initial_size*self.p.level_size)
                    self.order = self.buy(size=add_size)
                    self.entry_prices.append(self.data.close[0])
                    self.current_level += 1

    def notify_order(self, order):
        if order.status == order.Completed:
            self.order = None

```bash

### ATR-Based Pyramiding

```python
class ATRPyramidStrategy(bt.Strategy):
    """
    Pyramid positions based on ATR multiples.

    Adds to position at specific ATR intervals from the initial entry.
    """

    params = (
        ('atr_period', 14),
        ('atr_multiplier', 1.5),  # Add every 1.5 ATR move
        ('max_levels', 4),
    )

    def __init__(self):
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.entry_price = None
        self.pyramid_levels = 0
        self.order = None

    def next(self):
        if self.order:
            return

        if not self.position:

# Initial entry
            if len(self.data) > self.p.atr_period:
                self.order = self.buy(size=100)
                self.entry_price = self.data.close[0]
                self.pyramid_levels = 0
        else:

# Check if we can pyramid
            if (self.pyramid_levels < self.p.max_levels and
                self.entry_price is not None):

                profit_distance = self.data.close[0] - self.entry_price
                atr_distance = self.atr[0]*self.p.atr_multiplier*(self.pyramid_levels + 1)

                if profit_distance >= atr_distance:
                    add_size = 100  # Fixed add size
                    self.order = self.buy(size=add_size)
                    self.pyramid_levels += 1

    def notify_order(self, order):
        if order.status == order.Completed:
            self.order = None

```bash

### Fibonacci Pyramiding

```python
class FibonacciPyramidStrategy(bt.Strategy):
    """
    Pyramid at Fibonacci retracement levels of the move.

    Adds positions at 23.6%, 38.2%, 50%, and 61.8% of the initial profit target.
    """

    params = (
        ('profit_target', 0.10),  # 10% profit target
    )

# Fibonacci levels
    fib_levels = [0.236, 0.382, 0.50, 0.618]

    def __init__(self):
        self.entry_price = None
        self.target_price = None
        self.triggered_levels = []
        self.order = None

    def next(self):
        if self.order:
            return

        if not self.position:

# Initial entry
            self.order = self.buy(size=100)
            self.entry_price = self.data.close[0]
            self.target_price = self.entry_price*(1 + self.p.profit_target)
            self.triggered_levels = []
        else:

# Check each Fibonacci level
            profit = self.data.close[0] - self.entry_price
            total_profit = self.target_price - self.entry_price

            for i, fib_level in enumerate(self.fib_levels):
                if i not in self.triggered_levels:
                    fib_price = self.entry_price + (total_profit*fib_level)

                    if self.data.close[0] >= fib_price:

# Add position at this level
                        add_size = int(100*(1 - fib_level))  # Smaller adds at higher levels
                        self.order = self.buy(size=add_size)
                        self.triggered_levels.append(i)
                        break

    def notify_order(self, order):
        if order.status == order.Completed:
            self.order = None

```bash

- --

## Trailing Stop Implementation

### Percentage Trailing Stop

```python
class TrailingStopStrategy(bt.Strategy):
    """
    Implements a percentage-based trailing stop.

    The stop price moves up as price moves in favor, but never down.
    """

    params = (
        ('trail_pct', 0.03),  # 3% trailing stop
    )

    def __init__(self):
        self.entry_price = None
        self.stop_price = None
        self.highest_price = None
        self.order = None

    def next(self):
        if self.order:
            return

        if not self.position:

# Entry logic
            if len(self.data) >= 20:
                if self.data.close[0] > self.data.close[-1]:
                    self.order = self.buy()
                    self.entry_price = self.data.close[0]
                    self.highest_price = self.entry_price

# Set initial stop
                    self.stop_price = self.highest_price*(1 - self.p.trail_pct)
        else:

# Update highest price
            self.highest_price = max(self.highest_price, self.data.close[0])

# Update trailing stop
            new_stop = self.highest_price*(1 - self.p.trail_pct)
            if new_stop > self.stop_price:
                self.stop_price = new_stop

# Check stop
            if self.data.close[0] <= self.stop_price:
                self.order = self.close()

    def notify_order(self, order):
        if order.status == order.Completed:
            self.order = None
            if not self.position:
                self.entry_price = None
                self.stop_price = None
                self.highest_price = None

```bash

### ATR Trailing Stop

```python
class ATRTrailingStopStrategy(bt.Strategy):
    """
    ATR-based trailing stop that adapts to volatility.

    Uses Chandelier Exit principle: stop is set at
    ATR multiple below the highest high since entry.
    """

    params = (
        ('atr_period', 22),
        ('atr_multiplier', 3.0),
    )

    def __init__(self):
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.highest_high = bt.indicators.Highest(self.data.high,
                                                   period=self.p.atr_period)
        self.entry_price = None
        self.stop_price = None
        self.order = None

    def next(self):
        if self.order:
            return

        if not self.position:

# Entry
            if len(self.data) > self.p.atr_period:
                self.order = self.buy()
                self.entry_price = self.data.close[0]
        else:

# Calculate trailing stop using Chandelier Exit
            self.stop_price = self.highest_high[0] - (self.atr[0]*self.p.atr_multiplier)

# Ensure stop is below current price for long position
            if self.stop_price >= self.data.close[0]:
                self.stop_price = self.data.close[0]*0.99

# Check stop
            if self.data.close[0] <= self.stop_price:
                self.order = self.close()

    def notify_order(self, order):
        if order.status == order.Completed:
            self.order = None

```bash

### High-Water Mark Trailing Stop

```python
class HighWaterMarkTrailingStop(bt.Strategy):
    """
    Trailing stop based on highest closing price since entry.

    More aggressive than percentage-based - only locks in profits
    when price makes new highs.
    """

    params = (
        ('trail_pct', 0.05),  # 5% below highest close
        ('min_profit_pct', 0.02),  # Must have 2% profit before trailing activates
    )

    def __init__(self):
        self.highest_close = None
        self.stop_price = None
        self.order = None

    def next(self):
        if self.order:
            return

        if not self.position:

# Entry
            if len(self.data) >= 20:
                sma = bt.indicators.SMA(self.data.close, period=20)
                if self.data.close[0] > sma[0]:
                    self.order = self.buy()
                    self.highest_close = self.data.close[0]
                    self.stop_price = None  # No stop until minimum profit
        else:

# Update highest close
            self.highest_close = max(self.highest_close, self.data.close[0])

# Calculate profit
            profit_pct = (self.data.close[0] - self.highest_close) / self.highest_close

# Only set trailing stop after minimum profit is achieved
            if profit_pct > -self.p.min_profit_pct:
                new_stop = self.highest_close*(1 - self.p.trail_pct)

# Only update stop if it's higher (trailing)
                if self.stop_price is None or new_stop > self.stop_price:
                    self.stop_price = new_stop

# Check stop
                if self.data.close[0] <= self.stop_price:
                    self.order = self.close()

    def notify_order(self, order):
        if order.status == order.Completed:
            self.order = None
            if not self.position:
                self.highest_close = None
                self.stop_price = None

```bash

### PSAR Trailing Stop

```python
class PSARTrailingStopStrategy(bt.Strategy):
    """
    Uses Parabolic SAR as a trailing stop.

    PSAR automatically adjusts its acceleration based on trend strength.
    """

    def __init__(self):
        self.psar = bt.indicators.PSAR(self.data)
        self.in_position = False
        self.order = None

    def next(self):
        if self.order:
            return

# Entry: When PSAR indicates uptrend
        if not self.position:
            if len(self.psar) > 2:

# PSAR below price = uptrend
                if self.psar.psar[0] < self.data.low[0]:
                    if self.psar.psar[-1] >= self.data.low[-1]:  # Was above, now below
                        self.order = self.buy()
                        self.in_position = True
        else:

# Exit: When PSAR crosses above price (trend reversal)
            if self.psar.psar[0] > self.data.high[0]:
                self.order = self.close()
                self.in_position = False

    def notify_order(self, order):
        if order.status == order.Completed:
            self.order = None

```bash

- --

## Bracket Orders

### OCO (One-Cancels-Other) Bracket

```python
class BracketOrderStrategy(bt.Strategy):
    """
    Implements bracket orders with entry, stop loss, and take profit.

    When entry is filled, both stop-loss and take-profit orders are placed.
    If one is filled, the other is automatically cancelled.
    """

    params = (
        ('stop_loss_pct', 0.02),
        ('take_profit_pct', 0.04),
    )

    def __init__(self):
        self.entry_order = None
        self.stop_order = None
        self.limit_order = None
        self.entry_price = None

    def next(self):

# Only place bracket if no orders are pending
        if any([self.entry_order, self.stop_order, self.limit_order]):
            return

        if not self.position:

# Place entry order
            self.entry_order = self.buy()
            self.entry_price = self.data.close[0]

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order == self.entry_order:

# Entry order filled - place bracket
            if order.status == order.Completed:
                self.entry_order = None
                self.place_bracket()

        elif order in [self.stop_order, self.limit_order]:

# Bracket order filled - cancel the other
            if order.status == order.Completed:
                self.cancel_bracket()
                self.stop_order = None
                self.limit_order = None

        elif order.status == order.Cancelled:

# Handle cancelled orders
            if order == self.entry_order:
                self.entry_order = None
            elif order == self.stop_order:
                self.stop_order = None
            elif order == self.limit_order:
                self.limit_order = None

    def place_bracket(self):
        """Place stop loss and take profit orders."""
        if self.entry_price is None:
            return

# Calculate stop and limit prices
        stop_price = self.entry_price*(1 - self.p.stop_loss_pct)
        limit_price = self.entry_price*(1 + self.p.take_profit_pct)

# Place bracket orders
        self.stop_order = self.sell(exectype=order.Stop, price=stop_price)
        self.limit_order = self.sell(exectype=order.Limit, price=limit_price)

    def cancel_bracket(self):
        """Cancel all pending bracket orders."""
        if self.stop_order:
            self.cancel(self.stop_order)
        if self.limit_order:
            self.cancel(self.limit_order)

```bash

### Multi-Level Bracket (Scale Out)

```python
class ScaleOutBracketStrategy(bt.Strategy):
    """
    Scales out of position at multiple profit targets.

    Closes portions of position at different price levels.
    """

    params = (
        ('stop_loss_pct', 0.02),
        ('targets', ((0.02, 0.25), (0.04, 0.25), (0.06, 0.50))),  # (profit%, close%)
    )

    def __init__(self):
        self.entry_order = None
        self.stop_order = None
        self.target_orders = []
        self.triggered_targets = []
        self.entry_price = None
        self.position_size = 0

    def next(self):
        if self.entry_order or self.stop_order or any(self.target_orders):
            return

        if not self.position:
            self.entry_order = self.buy(size=100)
            self.position_size = 100

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order == self.entry_order and order.status == order.Completed:
            self.entry_order = None
            self.entry_price = order.executed.price
            self.place_initial_orders()

        elif order == self.stop_order and order.status == order.Completed:
            self.stop_order = None
            self.cancel_all_targets()

        elif order in self.target_orders and order.status == order.Completed:
            self.target_orders.remove(order)

# Update stop loss to breakeven after first target
            if len(self.triggered_targets) == 1:
                self.update_stop_to_breakeven()

# Track which targets have been triggered
        for i, target_order in enumerate(self.target_orders):
            if target_order == order and i not in self.triggered_targets:
                self.triggered_targets.append(i)

# Place next target if there are more
                if len(self.triggered_targets) < len(self.p.targets):
                    self.place_next_target()

    def place_initial_orders(self):
        """Place initial stop loss and first target."""
        if self.entry_price is None:
            return

# Place stop loss
        stop_price = self.entry_price*(1 - self.p.stop_loss_pct)
        self.stop_order = self.sell(size=self.position_size, exectype=order.Stop,
                                    price=stop_price)

# Place first target
        self.place_next_target()

    def place_next_target(self):
        """Place the next target order based on triggered level."""
        level = len(self.triggered_targets)
        if level >= len(self.p.targets):
            return

        target_pct, close_pct = self.p.targets[level]
        target_price = self.entry_price*(1 + target_pct)
        close_size = int(self.position_size*close_pct)

        target_order = self.sell(size=close_size, exectype=order.Limit,
                                 price=target_price)
        self.target_orders.append(target_order)

    def update_stop_to_breakeven(self):
        """Move stop loss to breakeven after first target is hit."""
        if self.stop_order:
            self.cancel(self.stop_order)

# Calculate remaining position size
        remaining_size = self.position_size
        for _, close_pct in self.p.targets:
            remaining_size = int(remaining_size*(1 - close_pct))
            break  # Just subtract first target

        breakeven_price = self.entry_price*1.001  # Slight buffer
        self.stop_order = self.sell(size=remaining_size, exectype=order.Stop,
                                    price=breakeven_price)

    def cancel_all_targets(self):
        """Cancel all remaining target orders."""
        for order in self.target_orders:
            self.cancel(order)
        self.target_orders = []

```bash

### Dynamic Bracket with Trailing

```python
class DynamicBracketStrategy(bt.Strategy):
    """
    Bracket orders with dynamic adjustments.

    - Stop loss trails with price
    - Take profit adjusts based on volatility

    """

    params = (
        ('atr_period', 14),
        ('stop_atr_mult', 2.0),
        ('target_atr_mult', 4.0),
    )

    def __init__(self):
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.highest_high = bt.indicators.Highest(self.data.high, period=20)
        self.entry_order = None
        self.stop_order = None
        self.limit_order = None
        self.entry_price = None
        self.highest_price = None

    def next(self):
        if self.entry_order:
            return

        if not self.position:

# Entry
            if len(self.data) > self.p.atr_period:
                self.entry_order = self.buy()
        else:

# Update trailing stop
            self.update_trailing_stop()

# Update take profit based on volatility
            self.update_take_profit()

    def update_trailing_stop(self):
        """Update the trailing stop order."""
        if self.entry_price is None or len(self.data) < 2:
            return

# Calculate new stop price
        new_stop = self.highest_price - (self.atr[0]*self.p.stop_atr_mult)

# Cancel existing stop and place new one if price moved favorably
        if self.stop_order:

# Get current stop price from order
            current_stop = self.stop_order.created.price if hasattr(self.stop_order, 'created') else new_stop

            if new_stop > current_stop:
                self.cancel(self.stop_order)
                stop_size = self.position.size
                self.stop_order = self.sell(size=stop_size, exectype=order.Stop,
                                            price=new_stop)
        else:

# Place initial stop
            stop_size = self.position.size
            self.stop_order = self.sell(size=stop_size, exectype=order.Stop,
                                        price=new_stop)

    def update_take_profit(self):
        """Update take profit based on current volatility."""
        if self.entry_price is None:
            return

# Dynamic target based on ATR
        target_price = self.entry_price + (self.atr[0]* self.p.target_atr_mult)

# Only place/update if we don't have a limit order or it needs moving
        if not self.limit_order:
            limit_size = self.position.size
            self.limit_order = self.sell(size=limit_size, exectype=order.Limit,
                                         price=target_price)

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order == self.entry_order and order.status == order.Completed:
            self.entry_order = None
            self.entry_price = order.executed.price
            self.highest_price = order.executed.price

# Update highest price on each bar
        if self.position:
            self.highest_price = max(self.highest_price, self.data.close[0])

# Handle completed orders
        if order.status == order.Completed:
            if order == self.stop_order:
                self.stop_order = None
                if self.limit_order:
                    self.cancel(self.limit_order)
                    self.limit_order = None
            elif order == self.limit_order:
                self.limit_order = None
                if self.stop_order:
                    self.cancel(self.stop_order)
                    self.stop_order = None

```bash

- --

## Usage Examples

### Running the Strategies

```python
import backtrader as bt
import backtrader.feeds as btfeeds

# Create cerebro

cerebro = bt.Cerebro()

# Add data feed

data = btfeeds.CSVData(
    dataname='your_data.csv',
    datetime=0,
    open=1,
    high=2,
    low=3,
    close=4,
    volume=5,
    openinterest=-1
)
cerebro.adddata(data)

# Add strategy with parameters

cerebro.addstrategy(
    ATRStopLoss,
    atr_period=14,
    atr_multiplier=2.0
)

# Set initial cash

cerebro.broker.setcash(10000.0)

# Set commission

cerebro.broker.setcommission(commission=0.001)  # 0.1%

# Add analyzers

cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')

# Run

results = cerebro.run()
strat = results[0]

# Print results

print(f'Sharpe Ratio: {strat.analyzers.sharpe.get_analysis()}')
print(f'DrawDown: {strat.analyzers.drawdown.get_analysis()}')
print(f'Returns: {strat.analyzers.returns.get_analysis()}')

# Plot

cerebro.plot()

```bash

- --

## Next Steps

- [Indicators Reference](../user_guide/indicators.md) - Available indicators
- [Strategies Guide](../user_guide/strategies.md) - Strategy development
- [Analyzers](../user_guide/analyzers.md) - Performance evaluation
