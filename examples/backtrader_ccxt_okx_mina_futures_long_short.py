#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""OKX MINA/USDT Perpetual Futures Bollinger Bands Breakout Strategy (Long/Short).

This strategy implements a Bollinger Bands breakout trading system for futures
trading with support for both long and short positions.

Strategy Overview:
1. Uses 60-period, 2 standard deviation Bollinger Bands
2. Trading pair: MINA/USDT perpetual futures
3. Order size: 1 USDT per trade
4. Timeframe: 1-minute candles

Trading Logic (Bidirectional futures trading):
- Long entry: Price breaks above upper band → Open long position (buy)
- Long exit: Price falls below middle band → Close long position (sell)
- Short entry: Price falls below lower band → Open short position (sell)
- Short exit: Price breaks above middle band → Close short position (buy)
- Uses ATR for dynamic stop loss

Note: Futures trading supports both long and short positions.
"""

import os
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

import backtrader as bt
from backtrader import Order
from backtrader.brokers.ccxtbroker import *
from backtrader.feeds.ccxtfeed import *
from backtrader.stores.ccxtstore import *
from backtrader.ccxt import load_ccxt_config_from_env


class BollingerBandsLongShortStrategy(bt.Strategy):
    """Bollinger Bands breakout strategy with support for long and short positions.

    This strategy implements a dual-directional trading system using Bollinger Bands
    for entry signals and ATR-based dynamic stop losses for risk management.

    Attributes:
        bollinger: Bollinger Bands indicator instance.
        atr: Average True Range indicator for stop loss calculation.
        mid: Middle band (simple moving average).
        top: Upper band (middle band + standard deviation).
        bot: Lower band (middle band - standard deviation).
        order: Current pending order.
        long_stop_price: Stop loss price for long positions.
        short_stop_price: Stop loss price for short positions.
        entry_price: Price at which current position was entered.
        position_type: Type of current position ('long', 'short', or None).
        trade_count: Total number of trades executed.
        is_live_mode: Flag indicating if strategy is in live trading mode.
        live_bar_count: Count of live bars processed.
        historical_bar_count: Count of historical bars processed.
        pending_orders: Dictionary tracking pending orders.

    Args:
        period: Bollinger Bands period. Defaults to 60.
        devfactor: Standard deviation multiplier. Defaults to 2.0.
        order_size: Order size in USDT. Defaults to 1.0.
        atr_period: ATR period for stop loss calculation. Defaults to 14.
        atr_mult: ATR multiplier for stop loss distance. Defaults to 2.0.
        position_size_pct: Position size as percentage of capital. Defaults to 1.0.
        log_bars: Whether to log detailed bar information. Defaults to True.
        use_stop_loss: Whether to enable ATR-based stop loss. Defaults to True.
        tdMode: Trading mode ('cross' for cross margin, 'isolated' for isolated). Defaults to 'cross'.
        leverage: Leverage multiplier for futures trading. Defaults to 10.
    """

    params = (
        ('period', 60),           # Bollinger Bands period
        ('devfactor', 2.0),       # Standard deviation multiplier
        ('order_size', 1.0),      # Order size in USDT
        ('atr_period', 14),       # ATR period
        ('atr_mult', 2.0),        # ATR stop loss multiplier
        ('position_size_pct', 1.0),  # Position size percentage
        ('log_bars', True),       # Whether to log bar information
        ('use_stop_loss', True),  # Whether to enable stop loss
        # OKX futures trading parameters
        ('tdMode', 'cross'),      # Trading mode: cross=cross margin, isolated=isolated margin
        ('leverage', 10),         # Leverage multiplier
    )

    def __init__(self):
        """Initialize strategy indicators and state variables.

        Sets up Bollinger Bands indicator, ATR indicator for stop loss calculation,
        and initializes all state tracking variables for the strategy.
        """
        # Bollinger Bands indicator
        self.bollinger = bt.indicators.BollingerBands(
            self.data.close,
            period=self.p.period,
            devfactor=self.p.devfactor
        )

        # ATR indicator (for dynamic stop loss)
        self.atr = bt.indicators.ATR(
            self.data,
            period=self.p.atr_period
        )

        # Moving average (middle band)
        self.mid = self.bollinger.mid

        # Upper and lower bands
        self.top = self.bollinger.top
        self.bot = self.bollinger.bot

        # Trading state (supports both long and short positions)
        self.order = None
        self.long_stop_price = None   # Long position stop loss price
        self.short_stop_price = None  # Short position stop loss price
        self.entry_price = None       # Entry price
        self.position_type = None     # Position type: 'long', 'short', None

        # Trading statistics
        self.trade_count = 0
        self.last_bar_logged = 0

        # Live trading flag: historical data is used for indicator initialization, no trading
        self.is_live_mode = False  # Whether in live mode
        self.live_bar_count = 0    # Live bar count
        self.historical_bar_count = 0  # Historical bar count

        # Order tracking
        self.pending_orders = {}  # Track pending orders

    def log(self, msg, with_date=True):
        """Log a message with optional timestamp.

        Args:
            msg: The message to log.
            with_date: Whether to prepend a timestamp. Defaults to True.
        """
        if with_date:
            timestamp = time.time()
            dt = datetime.fromtimestamp(timestamp)
            msg = f'{dt.strftime("%Y-%m-%d %H:%M:%S")} {msg}'
        print(msg)

    def notify_data(self, data, status, *args, **kwargs):
        """Monitor data feed status changes.

        Called by backtrader when the data feed status changes.

        Args:
            data: The data feed that triggered the notification.
            status: The new status of the data feed.
            *args: Additional positional arguments.
            **kwargs: Additional keyword arguments.

        Note:
            Status values:
            - DELAYED: Backfilling historical data
            - LIVE: Entered live trading mode
            - DISCONNECTED: Data feed disconnected
        """
        if status == data.DELAYED and not self.is_live_mode:
            self.log('[DATA] Loading historical data...', with_date=True)

        elif status == data.LIVE:
            if not self.is_live_mode:
                self.is_live_mode = True
                self.log('=' * 80, with_date=True)
                self.log('[LIVE] Historical data loaded, entering live trading mode!', with_date=True)
                self.log(f'[LIVE] Current position: {self.getposition().size}', with_date=True)
                self.log('=' * 80, with_date=True)
            else:
                # Ensure live mode is maintained
                self.is_live_mode = True

        elif status == data.DISCONNECTED:
            self.log('[DATA] Data feed disconnected - strategy may stop', with_date=True)
            self.log(f'[DATA] Position at disconnect: {self.getposition().size}', with_date=True)

    def log_bar_info(self):
        """Log detailed information for the current bar (live mode only).

        Prints comprehensive trading information including price data,
        indicator values, position details, and trading signals.
        """
        # Don't log detailed info for historical data
        if not self.is_live_mode:
            return

        if not self.p.log_bars:
            return

        # Avoid logging the same bar multiple times
        if len(self.data) == self.last_bar_logged:
            return

        self.last_bar_logged = len(self.data)

        # Get bar information
        bar_time = self.data.datetime.datetime(0)
        current_price = self.data.close[0]
        upper_band = self.top[0]
        lower_band = self.bot[0]
        middle_band = self.mid[0]
        atr_value = self.atr[0]

        # Get position information
        position_size = self.getposition().size
        position_price = self.getposition().price if position_size != 0 else 0

        # Calculate bandwidth (distance between bands / middle band)
        bandwidth = (upper_band - lower_band) / middle_band * 100 if middle_band > 0 else 0

        # Calculate price position within Bollinger Bands
        if upper_band != lower_band:
            bb_position = (current_price - lower_band) / (upper_band - lower_band) * 100
        else:
            bb_position = 50

        print(f"\n{'='*100}")
        print(f"[LIVE] Bar #{len(self.data)} | Time: {bar_time}")
        print(f"{'='*100}")
        print(f"Price Information:")
        print(f"  Open:   ${self.data.open[0]:.6f}")
        print(f"  High:   ${self.data.high[0]:.6f}")
        print(f"  Low:    ${self.data.low[0]:.6f}")
        print(f"  Close:  ${current_price:.6f}")
        print(f"  Volume: {self.data.volume[0]:.0f}")

        print(f"\nBollinger Bands (Period={self.p.period}, Std={self.p.devfactor}):")
        print(f"  Upper Band: ${upper_band:.6f}")
        print(f"  Middle Band: ${middle_band:.6f}")
        print(f"  Lower Band: ${lower_band:.6f}")
        print(f"  Bandwidth: {bandwidth:.2f}%")
        print(f"  BB Position: {bb_position:.1f}% ({'Oversold' if bb_position < 20 else 'Overbought' if bb_position > 80 else 'Neutral'})")

        print(f"\nATR (Period={self.p.atr_period}):")
        print(f"  ATR Value: {atr_value:.6f}")
        print(f"  ATR % of Price: {atr_value/current_price*100:.2f}%")

        print(f"\nPosition Information:")
        print(f"  Position Size: {position_size:.2f}")
        if position_size != 0:
            pos_type = "LONG" if position_size > 0 else "SHORT"
            print(f"  Position Type: {pos_type}")
            print(f"  Entry Price: ${position_price:.6f}")
            if position_size > 0:
                unrealized_pnl = (current_price - position_price) * position_size
                stop_label = "Long Stop"
                stop_price = self.long_stop_price
            else:
                unrealized_pnl = (position_price - current_price) * abs(position_size)
                stop_label = "Short Stop"
                stop_price = self.short_stop_price
            print(f"  Unrealized P&L: ${unrealized_pnl:.4f} USDT")
            if stop_price:
                stop_distance = abs(current_price - stop_price) / current_price * 100
                print(f"  {stop_label}: ${stop_price:.6f} (Distance: {stop_distance:.2f}%)")
        else:
            print(f"  Position Type: FLAT")
            print(f"  Entry Price: N/A (No position)")
            print(f"  Stop Price: N/A (No position)")

        # Trading signals (supports both long and short)
        signals = []
        if position_size == 0:
            if current_price > upper_band:
                signals.append("LONG SIGNAL (Break above upper band)")
            elif current_price < lower_band:
                signals.append("SHORT SIGNAL (Break below lower band)")
        elif position_size > 0:
            # Holding long position
            if current_price < middle_band:
                signals.append("CLOSE LONG SIGNAL (Below middle band)")
            elif self.long_stop_price and current_price <= self.long_stop_price:
                signals.append("LONG STOP LOSS SIGNAL")
            elif current_price > upper_band:
                signals.append("HOLD LONG (Above upper band - strong trend)")
        elif position_size < 0:
            # Holding short position
            if current_price > middle_band:
                signals.append("CLOSE SHORT SIGNAL (Above middle band)")
            elif self.short_stop_price and current_price >= self.short_stop_price:
                signals.append("SHORT STOP LOSS SIGNAL")
            elif current_price < lower_band:
                signals.append("HOLD SHORT (Below lower band - strong trend)")

        if signals:
            print(f"\nTrading Signals:")
            for signal in signals:
                print(f"  >>> {signal}")

        print(f"{'='*100}\n")

    def calculate_order_size(self, price):
        """Calculate order size, ensuring proper rounding.

        Futures trading typically has minimum quantity limits that require rounding.

        Args:
            price: Current price of the asset.

        Returns:
            int: The calculated order size rounded to minimum units.
        """
        # Calculate theoretical size
        theoretical_size = self.p.order_size / price

        # Get minimum quantity limit from market info
        min_amount = 1.0  # Default minimum 1 unit

        # Round up to nearest whole unit
        size = int(theoretical_size)
        if size < min_amount:
            size = int(min_amount)

        # Ensure at least 1
        if size < 1:
            size = 1

        return size

    def next(self):
        """Called on each bar/candle.

        Wraps the actual implementation with error handling to prevent
        strategy crashes due to unexpected exceptions.
        """
        try:
            self._next_impl()
        except Exception as e:
            self.log(f'[ERROR] Exception in next(): {e}', with_date=True)
            self.log(f'[ERROR] Exception details: {traceback.format_exc()}', with_date=True)

    def _next_impl(self):
        """Actual implementation of next() method.

        Implements the core trading logic:
        1. Track bar counts
        2. Log bar information in live mode
        3. Check stop loss conditions
        4. Execute entry/exit signals based on Bollinger Bands
        """
        # Track bar counts
        if self.is_live_mode:
            self.live_bar_count += 1
        else:
            self.historical_bar_count += 1

        # Live data: log progress every 60 bars or first 3 bars
        if self.is_live_mode:
            if self.live_bar_count % 60 == 0 or self.live_bar_count <= 3:
                self.log(f'[LIVE] Live bar #{self.live_bar_count}, total bars: {len(self.data)}', with_date=True)

        # Log detailed bar information (live mode only)
        if self.is_live_mode:
            self.log_bar_info()

        # Ensure no pending orders
        if self.order:
            return

        # Ensure sufficient data (at least period+1 bars)
        if len(self.data) < self.p.period + 1:
            return

        # === Historical data does not trigger trading signals ===
        # Only allow trading signals after LIVE notification is received
        if not self.is_live_mode:
            return

        # Get current price and indicator values
        current_price = self.data.close[0]
        upper_band = self.top[0]
        lower_band = self.bot[0]
        middle_band = self.mid[0]
        atr_value = self.atr[0]

        # Check if indicator values are valid
        if any(x is None for x in [current_price, upper_band, lower_band, middle_band, atr_value]):
            return

        # Get current position
        position_size = self.getposition().size

        # Calculate order size (rounded)
        size = self.calculate_order_size(current_price)

        # === Bidirectional futures trading logic ===

        # 1. Check stop loss (executed first)
        if self.p.use_stop_loss:
            # Long position stop loss (use limit order, slightly lower to ensure execution)
            if position_size > 0 and self.long_stop_price is not None:
                if current_price <= self.long_stop_price:
                    limit_price = current_price * 0.99  # Sell limit order: slightly below market
                    self.log(f'[LONG STOP LOSS] Long stop loss triggered: Current=${current_price:.6f}, Stop=${self.long_stop_price:.6f}, Limit=${limit_price:.6f}')
                    order_params = {
                        'tdMode': self.p.tdMode,
                        'Coint': 'USDT',
                    }
                    self.order = self.sell(size=abs(position_size), price=limit_price, params=order_params)
                    self.long_stop_price = None
                    self.entry_price = None
                    self.position_type = None
                    self.trade_count += 1
                    return

            # Short position stop loss (use limit order, slightly higher to ensure execution)
            elif position_size < 0 and self.short_stop_price is not None:
                if current_price >= self.short_stop_price:
                    limit_price = current_price * 1.01  # Buy limit order: slightly above market
                    self.log(f'[SHORT STOP LOSS] Short stop loss triggered: Current=${current_price:.6f}, Stop=${self.short_stop_price:.6f}, Limit=${limit_price:.6f}')
                    order_params = {
                        'tdMode': self.p.tdMode,
                        'Coint': 'USDT',
                    }
                    self.order = self.buy(size=abs(position_size), price=limit_price, params=order_params)
                    self.short_stop_price = None
                    self.entry_price = None
                    self.position_type = None
                    self.trade_count += 1
                    return

        # 2. Entry logic when no position
        if position_size == 0:
            # Break above upper band → Open long position (use limit order, slightly higher to ensure execution)
            if current_price > upper_band:
                limit_price = current_price * 1.01  # Buy limit order: slightly above market
                self.log(f'[LONG ENTRY] Break above upper band to open long: Price=${current_price:.6f}, Upper Band=${upper_band:.6f}, Limit=${limit_price:.6f}, Size={size}')
                # Futures trading parameters
                order_params = {
                    'tdMode': self.p.tdMode,
                    'Coint': 'USDT',  # Margin currency
                }
                self.order = self.buy(size=size, price=limit_price, params=order_params)
                self.entry_price = current_price
                self.long_stop_price = current_price - (atr_value * self.p.atr_mult)
                self.position_type = 'long'
                self.log(f'[ORDER] Long limit order submitted, waiting for exchange confirmation...', with_date=True)
                return

            # Break below lower band → Open short position (use limit order, slightly lower to ensure execution)
            elif current_price < lower_band:
                limit_price = current_price * 0.99  # Sell limit order: slightly below market
                self.log(f'[SHORT ENTRY] Break below lower band to open short: Price=${current_price:.6f}, Lower Band=${lower_band:.6f}, Limit=${limit_price:.6f}, Size={size}')
                # Futures trading parameters
                order_params = {
                    'tdMode': self.p.tdMode,
                    'Coint': 'USDT',  # Margin currency
                }
                self.order = self.sell(size=size, price=limit_price, params=order_params)
                self.entry_price = current_price
                self.short_stop_price = current_price + (atr_value * self.p.atr_mult)
                self.position_type = 'short'
                self.log(f'[ORDER] Short limit order submitted, waiting for exchange confirmation...', with_date=True)
                return

        # 3. Logic when holding long position
        elif position_size > 0:
            # Fall below middle band → Close long position (take profit, use limit order, slightly lower to ensure execution)
            if current_price < middle_band:
                limit_price = current_price * 0.99  # Sell limit order: slightly below market
                self.log(f'[LONG EXIT] Fall below middle band to close long: Price=${current_price:.6f}, Middle Band=${middle_band:.6f}, Limit=${limit_price:.6f}, Size={position_size}')
                # Closing position also requires parameters
                order_params = {
                    'tdMode': self.p.tdMode,
                    'Coint': 'USDT',
                }
                self.order = self.sell(size=position_size, price=limit_price, params=order_params)
                self.long_stop_price = None
                self.entry_price = None
                self.position_type = None
                self.trade_count += 1
                return

            # Position log (output every 30 bars)
            if len(self.data) % 30 == 0:
                pnl = (current_price - self.entry_price) * position_size
                self.log(f'[LONG HOLD] Holding long position: Entry=${self.entry_price:.6f}, Current=${current_price:.6f}, Unrealized P&L=${pnl:.4f}')

        # 4. Logic when holding short position
        elif position_size < 0:
            # Break above middle band → Close short position (take profit, use limit order, slightly higher to ensure execution)
            if current_price > middle_band:
                limit_price = current_price * 1.01  # Buy limit order: slightly above market
                self.log(f'[SHORT EXIT] Break above middle band to close short: Price=${current_price:.6f}, Middle Band=${middle_band:.6f}, Limit=${limit_price:.6f}, Size={abs(position_size)}')
                # Closing position also requires parameters
                order_params = {
                    'tdMode': self.p.tdMode,
                    'Coint': 'USDT',
                }
                self.order = self.buy(size=abs(position_size), price=limit_price, params=order_params)
                self.short_stop_price = None
                self.entry_price = None
                self.position_type = None
                self.trade_count += 1
                return

            # Position log (output every 30 bars)
            if len(self.data) % 30 == 0:
                pnl = (self.entry_price - current_price) * abs(position_size)
                self.log(f'[SHORT HOLD] Holding short position: Entry=${self.entry_price:.6f}, Current=${current_price:.6f}, Unrealized P&L=${pnl:.4f}')

    def notify_order(self, order):
        """Order status notification callback.

        Called by backtrader when an order's status changes. Wraps the actual
        implementation with error handling.

        Args:
            order: The order object that triggered the notification.
        """
        try:
            self._notify_order_impl(order)
        except Exception as e:
            self.log(f'[ERROR] Exception in notify_order(): {e}', with_date=True)
            self.log(f'[ERROR] Exception details: {traceback.format_exc()}', with_date=True)
            # Reset order to prevent blocking subsequent trades
            self.order = None

    def _notify_order_impl(self, order):
        """Actual implementation of notify_order() method.

        Logs order status changes and executed trade details.

        Args:
            order: The order object that triggered the notification.
        """
        # Order status mapping
        status_names = {
            order.Created: 'Created',
            order.Submitted: 'Submitted',
            order.Accepted: 'Accepted',
            order.Partial: 'Partial',
            order.Completed: 'Completed',
            order.Canceled: 'Canceled',
            order.Rejected: 'Rejected',
            order.Margin: 'Margin',
            order.Expired: 'Expired',
        }

        status_name = status_names.get(order.status, f'Unknown({order.status})')

        if order.status in [order.Submitted, order.Accepted, order.Partial]:
            self.log(f'[ORDER] Order status: {status_name} - Awaiting execution', with_date=True)
            return

        if order.status in [order.Completed]:
            if order.isbuy():
                self.log(f'[ORDER EXECUTED] Buy (close short): Price=${order.executed.price:.6f}, '
                        f'Size={order.executed.size:.0f}, '
                        f'Value=${order.executed.value:.2f} USDT', with_date=True)
            else:
                self.log(f'[ORDER EXECUTED] Sell (close long): Price=${order.executed.price:.6f}, '
                        f'Size={order.executed.size:.0f}, '
                        f'Value=${order.executed.value:.2f} USDT', with_date=True)
            # Display current balance
            self.log(f'[BALANCE] Current balance: ${self.broker.getvalue():.2f} USDT', with_date=True)

        elif order.status in [order.Canceled]:
            self.log('[ORDER] Order canceled', with_date=True)
        elif order.status in [order.Rejected]:
            self.log(f'[ORDER] Order rejected: {order}', with_date=True)
            self.log(f'[ORDER] Rejection details - Status: {status_name}, Size: {order.size}, Price: {order.price}', with_date=True)
        elif order.status in [order.Margin]:
            self.log('[ORDER] Order margin insufficient', with_date=True)

        # Reset order
        self.order = None

    def notify_trade(self, trade):
        """Trade completion notification callback.

        Called by backtrader when a trade is opened or closed.

        Args:
            trade: The trade object that triggered the notification.
        """
        try:
            if trade.isclosed:
                self.log(f'[TRADE CLOSED] Trade closed: Gross P&L=${trade.pnl:.4f} USDT, '
                        f'Net P&L=${trade.pnlcomm:.4f} USDT', with_date=True)
            elif trade.justopened:
                self.log(f'[TRADE OPENED] New trade opened: {trade.gettradename()}', with_date=True)
        except Exception as e:
            self.log(f'[ERROR] Exception in notify_trade(): {e}', with_date=True)

    def stop(self):
        """Called when the strategy stops.

        Logs final portfolio statistics and performance summary.
        """
        self.log('=' * 80, with_date=True)
        self.log('Strategy stopped', with_date=True)
        self.log(f'Final balance: {self.broker.getvalue():.2f} USDT', with_date=True)
        self.log(f'Total return: {self.broker.getvalue() - self.broker.startingcash:.2f} USDT', with_date=True)
        self.log(f'Historical bars: {self.historical_bar_count}', with_date=True)
        self.log(f'Live bars: {self.live_bar_count}', with_date=True)
        self.log(f'Total trades: {self.trade_count}', with_date=True)
        self.log('=' * 80, with_date=True)


def run_strategy():
    """Run the Bollinger Bands long/short strategy on OKX MINA/USDT perpetual futures.

    This function sets up and executes the trading strategy:
    1. Loads environment variables and OKX API configuration
    2. Creates a Cerebro engine and adds the strategy
    3. Configures the CCXT store for OKX futures trading
    4. Sets up live data feed with WebSocket support
    5. Runs the strategy and prints performance summary

    Environment Variables Required:
        OKX_API_KEY: OKX API key for authentication
        OKX_SECRET: OKX API secret
        OKX_PASSWORD: OKX API password

    Note:
        Requires ccxt.pro for WebSocket support: pip install ccxtpro
    """
    # Load environment variables
    env_path = Path(__file__).resolve().parent.parent / ".env"
    load_dotenv(dotenv_path=env_path)

    # Load OKX configuration
    try:
        config = load_ccxt_config_from_env('okx', enable_rate_limit=True)
    except ValueError as e:
        print(f"Error: {e}")
        print("\nPlease configure OKX API credentials in .env file:")
        print("OKX_API_KEY=your_api_key")
        print("OKX_SECRET=your_secret")
        print("OKX_PASSWORD=your_password")
        return

    # Create Cerebro engine
    cerebro = bt.Cerebro()

    # Add strategy
    cerebro.addstrategy(
        BollingerBandsLongShortStrategy,
        period=60,              # 60-period Bollinger Bands
        devfactor=2.0,          # 2x standard deviation
        order_size=1.0,         # 1 USDT per order
        atr_period=14,          # ATR period
        atr_mult=2.0,           # Stop loss multiplier
    )

    # Set initial capital (small capital for testing)
    cerebro.broker.setcash(10.0)  # 10 USDT

    # Create OKX Store (futures trading)
    store = CCXTStore(
        exchange='okx',
        currency='USDT',
        config=config,
        retries=5,
        debug=False
    )

    # Get broker
    broker = store.getbroker()
    cerebro.setbroker(broker)

    # Get futures data (MINA/USDT perpetual futures)
    # Use WebSocket live data stream (requires ccxt.pro: pip install ccxtpro)
    data = store.getdata(
        dataname='MINA/USDT:USDT',           # Perpetual futures trading pair
        name='MINA/USDT:USDT',
        timeframe=bt.TimeFrame.Minutes,      # 1 minute
        compression=1,
        fromdate=datetime.utcnow() - timedelta(minutes=200),  # Historical data start time
        backfill_start=True,                 # Enable historical data backfill
        historical=False,                    # False=continue live mode after historical data
        use_websocket=True,                  # Use WebSocket (requires ccxt.pro)
        ohlcv_limit=100,
        drop_newest=False,
        debug=False
    )

    cerebro.adddata(data)

    # Print initial information
    print('=' * 80)
    print('OKX MINA/USDT Perpetual Futures Bollinger Bands Strategy (Long/Short)')
    print('=' * 80)
    print(f'Initial Capital: {cerebro.broker.getvalue():.2f} USDT')
    print(f'Order Size: 1.0 USDT')
    print(f'Trading Pair: MINA/USDT Perpetual Futures')
    print(f'Timeframe: 1 minute')
    print(f'Bollinger Bands: 60 period, 2x standard deviation')
    print(f'ATR Stop Loss: 14 period, 2x ATR')
    print(f'Trading Mode: Bidirectional futures (Long + Short)')
    print('=' * 80)
    print()

    # Run strategy
    try:
        print("\nStarting strategy execution...")
        print(f"Loading historical data (requires at least {60+10} bars to initialize indicators)...")
        print("Historical data loading progress will be displayed every 10 bars")
        print("After historical data loading completes, live trading signals will be monitored")
        print("Press Ctrl+C to stop the strategy at any time\n")

        results = cerebro.run()

        # Strategy execution completed
        if results and len(results) > 0:
            strat = results[0]
            print('\n' + '=' * 80)
            print('Strategy Execution Summary')
            print('=' * 80)
            print(f'Historical bars: {strat.historical_bar_count}')
            print(f'Live bars: {strat.live_bar_count}')
            print(f'Total trades: {strat.trade_count}')
            print(f'Final balance: {cerebro.broker.getvalue():.2f} USDT')
            print('=' * 80)

    except KeyboardInterrupt:
        print("\n\nStrategy interrupted by user")
    except Exception as e:
        print(f"\nError: {e}")
        traceback.print_exc()


if __name__ == '__main__':
    run_strategy()
