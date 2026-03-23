#!/usr/bin/env python
"""Example 2: Mixed Tick+Bar backtesting with MixBroker.

Demonstrates using MixBroker + Cerebro for hybrid matching: ticks first,
bar fallback after timeout.

Usage:
    # First generate test data:
    python tools/generate_test_data.py --type tick --rows 10000
    python tools/generate_test_data.py --type bar --rows 1000

    # Then run:
    python examples/mixed_mode_backtest.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import backtrader as bt
from backtrader.channels.tick import TickChannel
from backtrader.channel import StreamingEventQueue
from backtrader.brokers.mixbroker import MixBroker


class MixedStrategy(bt.Strategy):
    """Strategy using both tick and bar data.

    Uses ticks for precise entry, bars for trend confirmation.
    """

    params = (
        ('symbol', 'BTC/USDT'),
    )

    def __init__(self):
        """Initialize the strategy with tracking variables.

        Sets up lists to track tick prices and bar closes, position state,
        and creates a mock data object for order placement.
        """
        self.tick_prices = []
        self.bar_closes = []
        self.pos = 0
        self.trades = 0
        self._data_obj = type('Data', (), {
            '_name': self.p.symbol, 'symbol': self.p.symbol})()

    def notify_tick(self, tick):
        """Process incoming tick events for the configured symbol.

        Args:
            tick: Tick event containing symbol and price data.

        Maintains a rolling window of the last 200 tick prices for
        entry signal calculation.
        """
        if tick.symbol != self.p.symbol:
            return
        self.tick_prices.append(tick.price)
        if len(self.tick_prices) > 200:
            self.tick_prices.pop(0)

    def notify_bar(self, bar):
        """Process incoming bar events for the configured symbol.

        Args:
            bar: Bar event containing OHLCV data.

        Implements a mean-reversion strategy: buy when tick price is
        below bar average (suggesting oversold), sell when above.
        Uses bars for trend confirmation via moving average.
        """
        if bar.symbol != self.p.symbol:
            return
        self.bar_closes.append(bar.close)
        if len(self.bar_closes) > 20:
            self.bar_closes.pop(0)

        if len(self.bar_closes) < 10 or len(self.tick_prices) < 50:
            return

        bar_avg = sum(self.bar_closes) / len(self.bar_closes)
        tick_avg = sum(self.tick_prices[-50:]) / 50

        # Trend from bars, entry from tick deviation
        if tick_avg < bar_avg * 0.998 and self.pos <= 0:
            self.buy(data=self._data_obj, size=0.1, exectype=0)
            self.pos += 1
            self.trades += 1
        elif tick_avg > bar_avg * 1.002 and self.pos >= 1:
            self.sell(data=self._data_obj, size=0.1, exectype=0)
            self.pos -= 1
            self.trades += 1

    def stop(self):
        """Print final trade count when strategy stops.

        Called when Cerebro finishes running.
        """
        print(f"Strategy finished: {self.trades} trades")


def main():
    """Run the mixed-mode backtest demo.

    Loads tick data from CSV file, creates a TickChannel with
    StreamingEventQueue, and runs a backtest with MixBroker.
    Demonstrates hybrid tick+bar matching with bar fallback timeout.
    """
    symbol = 'BTC/USDT'
    tick_file = os.path.join('tests', 'datas', 'tick_data',
                             f'tick_{symbol.replace("/", "_")}.csv')

    if not os.path.exists(tick_file):
        print(f"Data file not found: {tick_file}")
        print("Generate test data first: python tools/generate_test_data.py")
        return

    # 1. Create channel + event queue
    channel = TickChannel(symbol=symbol, dataname=tick_file)
    queue = StreamingEventQueue(channels=[channel], preload_window=5.0)

    # 2. Set up Cerebro with MixBroker
    cerebro = bt.Cerebro()
    cerebro.setbroker(MixBroker(cash=100000.0))
    cerebro.addstrategy(MixedStrategy, symbol=symbol)

    # 3. Run
    print(f"Running mixed-mode backtest...")
    print(f"Initial cash: {cerebro.broker.getcash():.2f}")

    results = cerebro.run(channel=queue)

    # 4. Report
    strat = results[0]
    broker = cerebro.broker
    print(f"\n{'='*50}")
    print(f"Mixed Mode Backtest Results")
    print(f"{'='*50}")
    print(f"Events processed: {strat._event_count}")
    print(f"Trades executed:  {strat.trades}")
    print(f"Final cash:       {broker.getcash():.2f}")
    print(f"Portfolio value:  {broker.getvalue():.2f}")


if __name__ == '__main__':
    main()
