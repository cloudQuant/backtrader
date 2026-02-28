#!/usr/bin/env python
"""Example 1: Pure tick-level backtesting.

Demonstrates using TickChannel + TickBroker + Cerebro for tick-level order
matching with a standard bt.Strategy subclass.

Usage:
    # First generate test data:
    python tools/generate_test_data.py --type tick --rows 10000

    # Then run:
    python examples/tick_backtest.py
"""

import os
import sys

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import backtrader as bt
from backtrader.channels.tick import TickChannel
from backtrader.channel import StreamingEventQueue
from backtrader.brokers.tickbroker import TickBroker


class SimpleTickStrategy(bt.Strategy):
    """Simple mean-reversion strategy on tick data.

    Buys when price drops below moving average, sells when above.
    Uses a simple rolling average of last N tick prices.
    """

    params = (
        ('symbol', 'BTC/USDT'),
        ('window', 50),
    )

    def __init__(self):
        """Initialize the strategy with price tracking and position state."""
        self.prices = []
        self.pos = 0
        self.trades = 0
        # Dummy data object for broker order placement in channel mode
        self._data_obj = type('Data', (), {
            '_name': self.p.symbol, 'symbol': self.p.symbol})()

    def notify_order(self, order):
        """Handle order status changes.

        Args:
            order: The order object that changed status.
        """
        if order.status in [order.Completed]:
            self.log(f"Order {order.isbuy() and 'BUY' or 'SELL'} executed")

    def notify_tick(self, tick):
        """Process incoming tick data and execute mean-reversion logic.

        Args:
            tick: The tick object containing price data.
        """
        if tick.symbol != self.p.symbol:
            return

        self.prices.append(tick.price)
        if len(self.prices) > self.p.window:
            self.prices.pop(0)

        if len(self.prices) < self.p.window:
            return

        avg = sum(self.prices) / len(self.prices)

        # Simple mean reversion
        if tick.price < avg * 0.999 and self.pos <= 0:
            self.buy(data=self._data_obj, size=0.1, exectype=0)
            self.pos += 1
            self.trades += 1

        elif tick.price > avg * 1.001 and self.pos >= 1:
            self.sell(data=self._data_obj, size=0.1, exectype=0)
            self.pos -= 1
            self.trades += 1

    def log(self, txt, dt=None, level='info'):
        """Log a message with strategy prefix.

        Args:
            txt: The message text to log.
            dt: Deprecated timestamp parameter (unused).
            level: Log level (unused).
        """
        print(f"[Strategy] {txt}")

    def stop(self):
        """Print strategy completion statistics."""
        print(f"Strategy finished: {self.trades} trades, "
              f"ticks processed: {self._tick_count}")


def main():
    """Run the tick-level backtest example.

    Creates a TickChannel with test data, sets up Cerebro with TickBroker,
    runs the strategy, and prints results.
    """
    symbol = 'BTC/USDT'
    data_file = os.path.join('tests', 'datas', 'tick_data',
                             f'tick_{symbol.replace("/", "_")}.csv')

    if not os.path.exists(data_file):
        print(f"Data file not found: {data_file}")
        print("Generate test data first: python tools/generate_test_data.py --type tick")
        return

    # 1. Create tick channel + event queue
    channel = TickChannel(symbol=symbol, dataname=data_file)
    queue = StreamingEventQueue(channels=[channel], preload_window=5.0)

    # 2. Set up Cerebro with TickBroker
    cerebro = bt.Cerebro()
    cerebro.setbroker(TickBroker(cash=100000.0, slippage_perc=0.0001))
    cerebro.addstrategy(SimpleTickStrategy, symbol=symbol, window=100)

    # 3. Run channel event loop
    print(f"Running tick backtest on {data_file}...")
    print(f"Initial cash: {cerebro.broker.getcash():.2f}")

    results = cerebro.run(channel=queue)

    # 4. Report
    strat = results[0]
    broker = cerebro.broker
    print(f"\n{'='*50}")
    print(f"Tick Backtest Results")
    print(f"{'='*50}")
    print(f"Events processed: {strat._event_count}")
    print(f"Trades executed:  {strat.trades}")
    print(f"Final cash:       {broker.getcash():.2f}")
    print(f"Portfolio value:  {broker.getvalue():.2f}")
    print(f"P&L:              {broker.getvalue() - 100000:.2f}")
    print(f"Ticks processed:  {broker.tick_count}")


if __name__ == '__main__':
    main()
