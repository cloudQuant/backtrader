#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Funding Rate Arbitrage Strategy - WebSocket Real-time Version.

This strategy implements a funding rate arbitrage trading system for perpetual
futures using real-time WebSocket data streams.

Strategy Description:
    1. Fetches funding rates in real-time via WebSocket
    2. When funding rate is high (longs pay shorts), opens short arbitrage position
    3. When funding rate is low (shorts pay longs), opens long arbitrage position
    4. Funding rate data is integrated into each candle bar

Data Sources:
    - OHLCV prices: WebSocket OHLCV stream
    - Funding rate: WebSocket Funding Rate stream
    - Mark price: WebSocket Mark Price stream

Usage:
    python strategy_funding_rate_arbitrage.py
"""

import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

import backtrader as bt
from backtrader import Order

# Import data feed with WebSocket funding rate support
from backtrader.feeds.ccxtfeed_funding import CCXTFeedWithFunding, WebSocketRequiredError
from backtrader.stores.ccxtstore import CCXTStore
from backtrader.ccxt import load_ccxt_config_from_env


class FundingRateMonitor(bt.Strategy):
    """Funding rate monitoring strategy - prints rate information.

    This strategy monitors and displays funding rate information in real-time
    without executing trades. Useful for observing market conditions.

    Attributes:
        print_interval: Number of bars between print outputs (default: 10).
    """

    params = (
        ('print_interval', 10),  # Print every N bars
    )

    def __init__(self):
        """Initialize the strategy."""
        # Verify data source
        if not hasattr(self.data, 'funding_rate'):
            raise ValueError("Please use CCXTFeedWithFunding data source")

        self.bar_count = 0
        self.is_live = False

    def notify_data(self, data, status):
        """Listen for data status changes.

        Args:
            data: The data object that triggered the notification.
            status: The new status of the data feed.
        """
        if status == data.LIVE and not self.is_live:
            self.is_live = True
            print('\n' + '=' * 70)
            print('[LIVE] Entering real-time trading mode!')
            print('[LIVE] Funding rates update via WebSocket in real-time')
            print('=' * 70 + '\n')

    def next(self):
        """Called on each bar."""
        if not self.is_live:
            if self.bar_count % 100 == 0:
                print(f"[HIST] Loading historical data... {self.bar_count} bars")
            self.bar_count += 1
            return

        self.bar_count += 1

        # Print at intervals
        if self.bar_count % self.p.print_interval != 0:
            return

        # Get data
        price = self.data.close[0]
        funding = self.data.funding_rate[0]

        # Get mark price if available
        if hasattr(self.data, 'mark_price'):
            mark_price = self.data.mark_price[0]
            premium = (mark_price - price) / price * 100 if price > 0 else 0
        else:
            mark_price = price
            premium = 0

        # Get predicted funding rate
        if hasattr(self.data, 'predicted_funding_rate'):
            predicted = self.data.predicted_funding_rate[0]
        else:
            predicted = 0

        # Calculate annualized rate (3 times per day, 365 days)
        annual_rate = funding * 3 * 365 * 100

        # Determine signal
        signal = "Neutral"
        if funding > 0.0005:
            signal = "Short Signal (rate too high)"
        elif funding < -0.0005:
            signal = "Long Signal (rate too low)"

        # Output
        bar_time = self.data.datetime.datetime(0)
        print(f"\n{'='*70}")
        print(f"[FUNDING] {bar_time}")
        print(f"{'='*70}")
        print(f"  Price:           ${price:.6f}")
        print(f"  Mark Price:      ${mark_price:.6f} (premium: {premium:+.4f}%)")
        print(f"  Funding Rate:    {funding:.8f} ({funding*100:.4f}%)")
        if predicted != 0:
            print(f"  Predicted Rate:  {predicted:.8f} ({predicted*100:.4f}%)")
        print(f"  Annualized Rate: {annual_rate:.2f}%")
        print(f"  Signal:          {signal}")
        print(f"{'='*70}\n")


class FundingArbitrage(bt.Strategy):
    """Funding rate arbitrage strategy.

    This strategy executes trades based on funding rate arbitrage opportunities.
    Opens positions when funding rates deviate significantly from zero and
    closes when rates normalize.

    Attributes:
        funding_high: Threshold above which to open short arbitrage (default: 0.0005).
        funding_low: Threshold below which to open long arbitrage (default: -0.0005).
        exit_threshold: Rate level to close positions (default: 0.0001).
        position_size: Order size in USDT (default: 1.0).
    """

    params = (
        ('funding_high', 0.0005),    # Short when above 0.05%
        ('funding_low', -0.0005),    # Long when below -0.05%
        ('exit_threshold', 0.0001),  # Close position when rate returns to this level
        ('position_size', 1.0),      # Order amount (USDT)
    )

    def __init__(self):
        """Initialize the strategy."""
        if not hasattr(self.data, 'funding_rate'):
            raise ValueError("Please use CCXTFeedWithFunding data source")

        self.order = None
        self.entry_funding = None
        self.is_live = False

    def notify_data(self, data, status):
        """Listen for data status changes.

        Args:
            data: The data object that triggered the notification.
            status: The new status of the data feed.
        """
        if status == data.LIVE and not self.is_live:
            self.is_live = True
            print('[LIVE] Entering real-time mode!')

    def log(self, msg):
        """Output log message.

        Args:
            msg: Message to log.
        """
        dt = datetime.now(timezone.utc).astimezone()
        print(f'{dt.strftime("%H:%M:%S")} {msg}')

    def next(self):
        """Main strategy logic."""
        if not self.is_live:
            return

        # Wait for pending orders
        if self.order:
            return

        funding = self.data.funding_rate[0]
        position = self.getposition()
        price = self.data.close[0]

        # Entry logic when no position
        if position.size == 0:
            # High rate = longs pay shorts = short arbitrage
            if funding > self.p.funding_high:
                size = int(self.p.position_size / price)
                if size < 1:
                    size = 1

                self.log(f'[SHORT ARB] Rate {funding:.6f} > {self.p.funding_high:.6f}, short arbitrage')
                self.log(f'[SHORT ARB] Price ${price:.6f}, quantity {size}')
                self.order = self.sell(size=size)
                self.entry_funding = funding

            # Low rate = shorts pay longs = long arbitrage
            elif funding < self.p.funding_low:
                size = int(self.p.position_size / price)
                if size < 1:
                    size = 1

                self.log(f'[LONG ARB] Rate {funding:.6f} < {self.p.funding_low:.6f}, long arbitrage')
                self.log(f'[LONG ARB] Price ${price:.6f}, quantity {size}')
                self.order = self.buy(size=size)
                self.entry_funding = funding

        # Exit logic when holding position
        else:
            # Close when rate normalizes
            if abs(funding) < self.p.exit_threshold:
                if position.size > 0:
                    self.log(f'[EXIT] Rate normalized to {funding:.6f}, close long position')
                    self.order = self.sell(size=position.size)
                else:
                    self.log(f'[EXIT] Rate normalized to {funding:.6f}, close short position')
                    self.order = self.buy(size=abs(position.size))

            # Stop loss when rate reverses
            elif position.size > 0 and funding < self.p.funding_low:
                self.log(f'[STOP] Rate reversed to {funding:.6f}, stop loss long position')
                self.order = self.sell(size=position.size)
            elif position.size < 0 and funding > self.p.funding_high:
                self.log(f'[STOP] Rate reversed to {funding:.6f}, stop loss short position')
                self.order = self.buy(size=abs(position.size))

    def notify_order(self, order):
        """Order status notification.

        Args:
            order: The order object with updated status.
        """
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status == order.Completed:
            if order.isbuy():
                self.log(f'[ORDER] Buy: ${order.executed.price:.6f} x {order.executed.size:.0f}')
            else:
                self.log(f'[ORDER] Sell: ${order.executed.price:.6f} x {order.executed.size:.0f}')
        elif order.status in [order.Canceled, order.Rejected]:
            self.log(f'[ORDER] Order {order.getstatusname()}')

        self.order = None

    def notify_trade(self, trade):
        """Trade completion notification.

        Args:
            trade: The trade object.
        """
        if trade.isclosed:
            self.log(f'[TRADE] Profit: ${trade.pnlcomm:.4f} USDT')

    def stop(self):
        """Called when strategy stops."""
        print('\n' + '=' * 70)
        print('Strategy stopped')
        print('=' * 70)


def run_strategy():
    """Run the funding rate arbitrage strategy."""

    # Load environment variables
    env_path = Path(__file__).resolve().parent.parent / ".env"
    load_dotenv(dotenv_path=env_path)

    # Select exchange
    exchange = os.getenv('EXCHANGE', 'okx')

    try:
        # Network configuration options (set in .env file):
        # OKX_USE_AWS=true  - Use AWS endpoint
        # OKX_PROXY=http://127.0.0.1:7890  - Use proxy
        config = load_ccxt_config_from_env(exchange, enable_rate_limit=True)
    except ValueError as e:
        print(f"Error: {e}")
        print("\nPlease configure API credentials in .env file:")
        print(f"{exchange.upper()}_API_KEY=your_api_key")
        if exchange == 'okx':
            print(f"{exchange.upper()}_PASSWORD=your_password")
        print(f"{exchange.upper()}_SECRET=your_secret")
        return

    # Check ccxt.pro installation
    try:
        import ccxt.pro as ccxtpro
        print(f"[OK] ccxt.pro installed (version: {ccxtpro.__version__})")
    except ImportError:
        print("[Error] ccxt.pro is required")
        print("Please run: pip install ccxtpro")
        return

    # Create Cerebro engine
    cerebro = bt.Cerebro()

    # Add strategy (choose one)
    # 1. Monitor strategy - only prints rate information
    cerebro.addstrategy(FundingRateMonitor, print_interval=10)

    # 2. Arbitrage strategy - actual trading
    # cerebro.addstrategy(
    #     FundingArbitrage,
    #     funding_high=0.0005,
    #     funding_low=-0.0005,
    #     position_size=1.0
    # )

    # Set initial capital
    cerebro.broker.setcash(10.0)

    # Create Store
    store = CCXTStore(
        exchange=exchange,
        currency='USDT',
        config=config,
        retries=5,
        debug=False
    )

    # Get broker
    broker = store.getbroker()
    cerebro.setbroker(broker)

    # Use data feed with WebSocket funding rate support
    try:
        data = CCXTFeedWithFunding(
            store=store,
            dataname='BTC/USDT:USDT',  # Perpetual contract
            name='BTC/USDT:USDT',
            timeframe=bt.TimeFrame.Minutes,
            compression=1,
            fromdate=datetime.now(timezone.utc) - timedelta(minutes=500),
            backfill_start=True,
            historical=False,
            # WebSocket settings
            use_websocket=True,              # Enable WebSocket (default)
            include_funding=True,            # Enable funding rate
            funding_history_days=3,          # Days of historical data
            debug=True  # Enable debug output to see connection process
        )
    except WebSocketRequiredError as e:
        print(f"[Error] {e}")
        return

    cerebro.adddata(data)

    # Print initial information
    print('=' * 70)
    print('Funding Rate Arbitrage Strategy - WebSocket Real-time Version')
    print('=' * 70)
    print(f'Exchange: {exchange}')
    print(f'Symbol: BTC/USDT perpetual')
    print(f'Initial Capital: {cerebro.broker.getvalue():.2f} USDT')
    print(f'Data Source: WebSocket (OHLCV + Funding Rate + Mark Price)')
    print('=' * 70)
    print()

    # Run strategy
    try:
        print("Starting strategy...")
        print("Loading historical data...\n")
        results = cerebro.run()

        if results and len(results) > 0:
            print('\n' + '=' * 70)
            print('Strategy execution completed')
            print('=' * 70)

    except KeyboardInterrupt:
        print("\n\nStrategy interrupted by user")
    except WebSocketRequiredError as e:
        print(f"\n[Error] WebSocket connection failed: {e}")
        print("Please ensure:")
        print("1. ccxt.pro is installed: pip install ccxtpro")
        print("2. Network connection is working")
        print("3. Exchange API keys are correct")
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    run_strategy()
