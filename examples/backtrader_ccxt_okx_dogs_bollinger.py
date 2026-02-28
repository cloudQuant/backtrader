#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""OKX DOGS/USDT Spot Bollinger Bands Breakout Strategy.

Strategy Description:
    1. Uses 60-period, 2-standard deviation Bollinger Bands
    2. Trading pair: DOGS/USDT spot
    3. Order amount per trade: 0.4 USDT
    4. 1-minute candles

Trading Logic (spot long-only trading):
    - Price breaks above upper band -> Open long position (buy)
    - Price breaks below lower band -> Close long position (sell)
    - Uses ATR for dynamic stop loss

Note: Spot trading allows only long positions, no shorting.
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


class BollingerBandsStrategy(bt.Strategy):
    """Bollinger Bands breakout strategy (spot long-only).

    This strategy implements a Bollinger Bands breakout trading system
    for spot trading, which only allows long positions.

    Attributes:
        period: Bollinger Bands period, default 60.
        devfactor: Standard deviation multiplier, default 2.
        order_size: Order amount in USDT per trade, default 0.4.
        atr_period: ATR period, default 14.
        atr_mult: ATR stop loss multiplier, default 2.
        position_size_pct: Position size ratio, default 1.0 (full position).
        log_bars: Whether to output detailed bar info, default True.
    """

    params = (
        ('period', 60),           # Bollinger Bands period
        ('devfactor', 2.0),       # Standard deviation multiplier
        ('order_size', 0.4),      # Order amount per trade (USDT)
        ('atr_period', 14),       # ATR period
        ('atr_mult', 2.0),        # ATR stop loss multiplier
        ('position_size_pct', 1.0),  # Position size ratio
        ('log_bars', True),       # Whether to output bar information
    )

    def __init__(self):
        """Initialize strategy indicators and state."""
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

        # Trading state (spot trading only allows long)
        self.order = None
        self.stop_price = None  # Stop loss price
        self.entry_price = None  # Entry price

        # Trading statistics
        self.trade_count = 0
        self.last_bar_logged = 0

        # Live trading flag: historical data initializes indicators, no trading
        self.is_live_mode = False  # Whether in live mode
        self.live_bar_count = 0  # Live bar count
        self.historical_bar_count = 0  # Historical bar count

    def log(self, msg, with_date=True):
        """Output log message.

        Args:
            msg: Message to log.
            with_date: Whether to include timestamp in the log.
        """
        if with_date:
            timestamp = time.time()
            dt = datetime.fromtimestamp(timestamp)
            msg = f'{dt.strftime("%Y-%m-%d %H:%M:%S")} {msg}'
        print(msg)

    def notify_data(self, data, status, *args, **kwargs):
        """Listen for data status changes.

        Backtrader calls this method when the data source status changes.
        - DELAYED: Backfilling historical data
        - LIVE: Entered real-time mode
        - DISCONNECTED: Data disconnected

        Args:
            data: The data object that triggered the notification.
            status: The new status of the data feed.
        """
        if status == data.DELAYED and not self.is_live_mode:
            self.log('[DATA] Loading historical data...', with_date=True)

        elif status == data.LIVE:
            if not self.is_live_mode:
                self.is_live_mode = True
                self.log('=' * 80, with_date=True)
                self.log('[LIVE] Historical data loaded, entering real-time trading mode!', with_date=True)
                self.log(f'[LIVE] Current position: {self.getposition().size}', with_date=True)
                self.log('=' * 80, with_date=True)
            else:
                # Ensure staying in live mode
                self.is_live_mode = True

        elif status == data.DISCONNECTED:
            self.log('[DATA] Data source disconnected - strategy may stop', with_date=True)
            self.log(f'[DATA] Position at disconnect: {self.getposition().size}', with_date=True)

    def log_historical_bar(self, bar_num, bar_time, price, upper, lower, middle):
        """Output historical data loading progress.

        Args:
            bar_num: Current bar number.
            bar_time: Bar timestamp.
            price: Current price.
            upper: Upper band value.
            lower: Lower band value.
            middle: Middle band value.
        """
        mode_str = "HIST" if not self.is_live_mode else "LIVE"
        print(f"[{mode_str}] #{bar_num:3d} | {bar_time} | Price: ${price:.6f} | "
              f"Upper: ${upper:.6f} | Mid: ${middle:.6f} | Lower: ${lower:.6f}")

    def log_bar_info(self):
        """Output detailed information for the current bar."""
        if not self.p.log_bars:
            return

        # Avoid duplicate output for the same bar
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
        mode_str = "LIVE" if self.is_live_mode else "HIST"
        print(f"Bar #{len(self.data)} [{mode_str}] | Time: {bar_time}")
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
            print(f"  Entry Price: ${position_price:.6f}")
            unrealized_pnl = (current_price - position_price) * position_size
            print(f"  Unrealized P&L: ${unrealized_pnl:.4f} USDT")
            if self.stop_price:
                stop_distance = (current_price - self.stop_price) / current_price * 100
                print(f"  Stop Loss: ${self.stop_price:.6f} (Distance: {stop_distance:.2f}%)")
        else:
            print(f"  Entry Price: N/A (No position)")
            print(f"  Stop Price: N/A (No position)")

        # Trading signals (spot only allows long)
        signals = []
        if position_size == 0:
            if current_price > upper_band:
                signals.append("BUY SIGNAL (Break above upper band)")
        elif position_size > 0:
            if current_price > upper_band:
                signals.append("HOLD LONG (Above upper band)")
            elif current_price < lower_band:
                signals.append("CLOSE LONG SIGNAL (Below lower band)")
            elif self.stop_price and current_price <= self.stop_price:
                signals.append("STOP LOSS SIGNAL")

        if signals:
            print(f"\nTrading Signals:")
            for signal in signals:
                print(f"  >>> {signal}")

        print(f"{'='*100}\n")

    def calculate_order_size(self, price):
        """Calculate order quantity, ensuring proper rounding.

        Futures trading typically has minimum quantity limits that require rounding.

        Args:
            price: Current price for calculating quantity.

        Returns:
            Rounded order quantity.
        """
        # Calculate theoretical quantity
        theoretical_size = self.p.order_size / price

        # Get minimum quantity limit from market info
        min_amount = 1.0  # Default minimum 1 unit

        # Round up to nearest integer multiple of minimum unit
        size = int(theoretical_size)
        if size < min_amount:
            size = int(min_amount)

        # Ensure at least 1
        if size < 1:
            size = 1

        return size

    def next(self):
        """Called on each bar."""
        try:
            self._next_impl()
        except Exception as e:
            self.log(f'[ERROR] Exception in next(): {e}', with_date=True)
            self.log(f'[ERROR] Exception details: {traceback.format_exc()}', with_date=True)

    def _next_impl(self):
        """Actual implementation of next()."""
        # Count bars
        if self.is_live_mode:
            self.live_bar_count += 1
        else:
            self.historical_bar_count += 1

        # Historical data: output simplified info every 10 bars
        if not self.is_live_mode and self.historical_bar_count % 10 == 0:
            bar_time = self.data.datetime.datetime(0)
            current_price = self.data.close[0]
            upper_band = self.top[0]
            lower_band = self.bot[0]
            middle_band = self.mid[0]
            self.log_historical_bar(self.historical_bar_count, bar_time, current_price,
                                    upper_band, lower_band, middle_band)

        # Live data: output progress every 60 bars or first 3 bars
        if self.is_live_mode:
            if self.live_bar_count % 60 == 0 or self.live_bar_count <= 3:
                self.log(f'[LIVE] Live bar #{self.live_bar_count}, total bars: {len(self.data)}', with_date=True)

        # Output detailed bar info (only in live mode or first/last 3 historical bars)
        if self.is_live_mode or len(self.data) <= 3 or (not self.is_live_mode and self.historical_bar_count > self.p.period - 3):
            self.log_bar_info()

        # Ensure no pending orders
        if self.order:
            return

        # Ensure sufficient data (at least period+1 bars)
        if len(self.data) < self.p.period + 1:
            return

        # === Historical data does not trigger trading signals ===
        # Only trigger trading signals after receiving LIVE notification
        if not self.is_live_mode:
            return

        # Get current price and indicator values
        current_price = self.data.close[0]
        upper_band = self.top[0]
        lower_band = self.bot[0]
        middle_band = self.mid[0]
        atr_value = self.atr[0]

        # Check indicator validity
        if any(x is None for x in [current_price, upper_band, lower_band, middle_band, atr_value]):
            return

        # Get current position
        position_size = self.getposition().size

        # Calculate order quantity (rounded)
        size = self.calculate_order_size(current_price)

        # === Spot long-only trading logic ===

        # 1. Check stop loss (executed first)
        if position_size > 0 and self.stop_price is not None:
            if current_price <= self.stop_price:
                self.log(f'[STOP LOSS] Stop triggered: current=${current_price:.6f}, stop=${self.stop_price:.6f}')
                self.order = self.sell(size=position_size)
                self.stop_price = None
                self.entry_price = None
                self.trade_count += 1
                return

        # 2. Entry logic when no position
        if position_size == 0:
            # Break above upper band -> open long
            if current_price > upper_band:
                self.log(f'[LONG ENTRY] Break above upper band: price=${current_price:.6f}, upper=${upper_band:.6f}, qty={size}')
                self.order = self.buy(size=size)
                self.entry_price = current_price
                self.stop_price = current_price - (atr_value * self.p.atr_mult)
                self.log(f'[ORDER] Long order submitted, waiting for exchange confirmation...', with_date=True)
                return

        # 3. Logic when holding long position
        elif position_size > 0:
            # Break below lower band -> close long
            if current_price < lower_band:
                self.log(f'[LONG EXIT] Break below lower band: price=${current_price:.6f}, lower=${lower_band:.6f}, qty={position_size}')
                self.order = self.sell(size=position_size)
                self.stop_price = None
                self.entry_price = None
                self.trade_count += 1
                return

            # Holding log (output every 30 bars)
            if len(self.data) % 30 == 0:
                pnl = (current_price - self.entry_price) * position_size
                self.log(f'[LONG HOLD] Holding long: entry=${self.entry_price:.6f}, current=${current_price:.6f}, unrealized=${pnl:.4f}')

    def notify_order(self, order):
        """Order status notification.

        Args:
            order: The order object with updated status.
        """
        try:
            self._notify_order_impl(order)
        except Exception as e:
            self.log(f'[ERROR] Exception in notify_order(): {e}', with_date=True)
            self.log(f'[ERROR] Exception details: {traceback.format_exc()}', with_date=True)
            # Reset order to prevent blocking subsequent trades
            self.order = None

    def _notify_order_impl(self, order):
        """Actual implementation of notify_order()."""
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
            self.log(f'[ORDER] Order status: {status_name} - waiting for execution', with_date=True)
            return

        if order.status in [order.Completed]:
            if order.isbuy():
                self.log(f'[ORDER EXECUTED] Buy: price=${order.executed.price:.6f}, '
                        f'qty={order.executed.size:.0f}, '
                        f'value=${order.executed.value:.2f} USDT', with_date=True)
            else:
                self.log(f'[ORDER EXECUTED] Sell: price=${order.executed.price:.6f}, '
                        f'qty={order.executed.size:.0f}, '
                        f'value=${order.executed.value:.2f} USDT', with_date=True)
            # Display current balance
            self.log(f'[BALANCE] Current balance: ${self.broker.getvalue():.2f} USDT', with_date=True)

        elif order.status in [order.Canceled]:
            self.log('[ORDER] Order canceled', with_date=True)
        elif order.status in [order.Rejected]:
            self.log(f'[ORDER] Order rejected: {order}', with_date=True)
            self.log(f'[ORDER] Rejection details - Status: {status_name}, Size: {order.size}, Price: {order.price}', with_date=True)
        elif order.status in [order.Margin]:
            self.log('[ORDER] Insufficient margin for order', with_date=True)

        # Reset order
        self.order = None

    def notify_trade(self, trade):
        """Trade completion notification.

        Args:
            trade: The trade object.
        """
        try:
            if trade.isclosed:
                self.log(f'[TRADE CLOSED] Trade closed: gross_pnl=${trade.pnl:.4f} USDT, '
                        f'net_pnl=${trade.pnlcomm:.4f} USDT', with_date=True)
            elif trade.justopened:
                self.log(f'[TRADE OPENED] New trade opened: {trade.gettradename()}', with_date=True)
        except Exception as e:
            self.log(f'[ERROR] Exception in notify_trade(): {e}', with_date=True)

    def stop(self):
        """Called when strategy stops."""
        self.log('=' * 80, with_date=True)
        self.log('Strategy stopped', with_date=True)
        self.log(f'Final balance: {self.broker.getvalue():.2f} USDT', with_date=True)
        self.log(f'Total return: {self.broker.getvalue() - self.broker.startingcash:.2f} USDT', with_date=True)
        self.log(f'Historical bars: {self.historical_bar_count}', with_date=True)
        self.log(f'Live bars: {self.live_bar_count}', with_date=True)
        self.log(f'Total trades: {self.trade_count}', with_date=True)
        self.log('=' * 80, with_date=True)


def run_strategy():
    """Run the strategy."""

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

    # Add proxy configuration (if environment variables are set)
    proxy_host = os.getenv('PROXY_HOST') or os.getenv('HTTP_PROXY') or os.getenv('http_proxy')
    socks_proxy = os.getenv('SOCKS_PROXY') or os.getenv('socks_proxy')

    if proxy_host:
        # If http/https proxy
        if not proxy_host.startswith(('http://', 'https://', 'socks')):
            proxy_host = f'http://{proxy_host}'
        config['proxies'] = {
            'http': proxy_host,
            'https': proxy_host,
        }
        print(f'[PROXY] Using HTTP proxy: {proxy_host}')

    elif socks_proxy:
        # If socks proxy
        config['proxies'] = {
            'http': socks_proxy,
            'https': socks_proxy,
        }
        print(f'[PROXY] Using SOCKS proxy: {socks_proxy}')

    # Add additional connection configuration
    config.update({
        'timeout': 30000,  # 30 second timeout
        'enableRateLimit': True,
        'options': {
            'defaultType': 'spot',
            'adjustForTimeDifference': True,  # Adjust time difference
        }
    })

    # Create Cerebro engine
    cerebro = bt.Cerebro()

    # Add strategy
    cerebro.addstrategy(
        BollingerBandsStrategy,
        period=60,              # 60-period Bollinger Bands
        devfactor=2.0,          # 2x standard deviation
        order_size=0.4,         # 0.4 USDT per order
        atr_period=14,          # ATR period
        atr_mult=2.0,           # Stop loss multiplier
    )

    # Set initial capital (small capital for testing)
    cerebro.broker.setcash(10.0)  # 10 USDT

    # Create OKX Store (spot trading)
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

    # Get spot data (DOGS/USDT)
    data = store.getdata(
        dataname='DOGS/USDT',           # Spot trading pair
        name='DOGS/USDT',
        timeframe=bt.TimeFrame.Minutes,  # 1 minute
        compression=1,
        fromdate=datetime.utcnow() - timedelta(minutes=200),  # Historical data start time
        backfill_start=True,                 # Enable historical data backfill
        historical=False,                    # False=continue with live mode after historical data
        ohlcv_limit=100,
        drop_newest=False,
        debug=False
    )

    cerebro.adddata(data)

    # Print initial information
    print('=' * 80)
    print('OKX DOGS/USDT Spot Bollinger Bands Breakout Strategy')
    print('=' * 80)
    print(f'Initial Capital: {cerebro.broker.getvalue():.2f} USDT')
    print(f'Order Size: 0.4 USDT per trade')
    print(f'Trading Pair: DOGS/USDT spot')
    print(f'Timeframe: 1 minute')
    print(f'Bollinger Bands: 60 period, 2x standard deviation')
    print(f'ATR Stop Loss: 14 period, 2x ATR')
    print(f'Trading Mode: Spot long-only (no shorting)')
    print('=' * 80)
    print()

    # Run strategy
    try:
        print("\nStarting strategy...")
        print(f"Loading historical data (requires at least {60+10} bars for indicator initialization)...")
        print("Historical data loading progress will display every 10 bars")
        print("After historical data loads, live trading signals will be monitored")
        print("Press Ctrl+C to stop the strategy at any time\n")

        results = cerebro.run()

        # Strategy execution complete
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
