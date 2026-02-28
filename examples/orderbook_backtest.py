#!/usr/bin/env python
"""Example 3: Order book depth backtesting with OrderBookBroker.

Demonstrates using OrderBookChannel + OrderBookBroker + Cerebro for precise
order matching against order book depth, including market impact.

Usage:
    # First generate test data:
    python tools/generate_test_data.py --type orderbook --rows 5000

    # Then run:
    python examples/orderbook_backtest.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import backtrader as bt
from backtrader.channels.orderbook import OrderBookChannel
from backtrader.channel import StreamingEventQueue
from backtrader.brokers.obbroker import OrderBookBroker
from backtrader.brokers.impact_models import LinearImpactModel


class OBSpreadStrategy(bt.Strategy):
    """Strategy that trades based on order book spread and depth.

    Buys when spread narrows and bid depth is strong,
    sells when spread widens and ask depth is strong.

    Attributes:
        spreads: List of recent spread values for averaging.
        pos: Current position count (positive=long, negative=short).
        trades: Total number of trades executed.
        _data_obj: Mock data object for order submission.
    """

    params = (
        ('symbol', 'BTC/USDT'),
    )

    def __init__(self):
        """Initialize the strategy with empty tracking variables."""
        self.spreads = []
        self.pos = 0
        self.trades = 0
        self._data_obj = type('Data', (), {
            '_name': self.p.symbol, 'symbol': self.p.symbol})()

    def notify_order(self, order):
        """Handle order status updates.

        Args:
            order: The order object with updated status.
        """
        if order.status in [order.Completed]:
            print(f"  [Order] {'BUY' if order.isbuy() else 'SELL'} executed")

    def notify_orderbook(self, ob):
        """Process order book updates and generate trading signals.

        Maintains a rolling window of spreads and calculates bid/ask
        depth ratios to identify trading opportunities.

        Args:
            ob: OrderBook object with bids, asks, and spread data.
        """
        if ob.symbol != self.p.symbol:
            return

        if not ob.bids or not ob.asks:
            return

        spread = ob.spread
        self.spreads.append(spread)
        if len(self.spreads) > 100:
            self.spreads.pop(0)

        if len(self.spreads) < 20:
            return

        avg_spread = sum(self.spreads) / len(self.spreads)

        # Calculate bid/ask depth ratio
        bid_depth = sum(v for _, v in ob.bids[:5])
        ask_depth = sum(v for _, v in ob.asks[:5])
        depth_ratio = bid_depth / ask_depth if ask_depth > 0 else 1.0

        # Tight spread + strong bid depth → buy
        if spread < avg_spread * 0.8 and depth_ratio > 1.5 and self.pos <= 0:
            self.buy(data=self._data_obj, size=0.05, exectype=0)
            self.pos += 1
            self.trades += 1

        # Wide spread + strong ask depth → sell
        elif spread > avg_spread * 1.2 and depth_ratio < 0.7 and self.pos >= 1:
            self.sell(data=self._data_obj, size=0.05, exectype=0)
            self.pos -= 1
            self.trades += 1

    def stop(self):
        """Print final statistics when backtesting completes."""
        print(f"Strategy finished: {self.trades} trades")


def main():
    """Run the order book backtest demonstration.

    Loads order book data from JSONL file, initializes the Cerebro
    engine with OrderBookBroker, and executes the OBSpreadStrategy.

    Raises:
        SystemExit: If the required data file is not found.
    """
    symbol = 'BTC/USDT'
    ob_file = os.path.join('tests', 'datas', 'tick_data',
                           f'orderbook_{symbol.replace("/", "_")}.jsonl')

    if not os.path.exists(ob_file):
        print(f"Data file not found: {ob_file}")
        print("Generate test data first: python tools/generate_test_data.py --type orderbook")
        return

    # 1. Create orderbook channel + event queue
    channel = OrderBookChannel(symbol=symbol, dataname=ob_file, max_depth=20)
    queue = StreamingEventQueue(channels=[channel], preload_window=5.0)

    # 2. Set up Cerebro with OrderBookBroker
    impact_model = LinearImpactModel(coefficient=0.0005)
    cerebro = bt.Cerebro()
    cerebro.setbroker(OrderBookBroker(cash=100000.0, impact_model=impact_model))
    cerebro.addstrategy(OBSpreadStrategy, symbol=symbol)

    # 3. Run
    print(f"Running order book backtest on {ob_file}...")
    print(f"Initial cash: {cerebro.broker.getcash():.2f}")
    print(f"Market impact model: LinearImpactModel(coefficient=0.0005)")

    results = cerebro.run(channel=queue)

    # 4. Report
    strat = results[0]
    broker = cerebro.broker
    print(f"\n{'='*50}")
    print(f"Order Book Backtest Results")
    print(f"{'='*50}")
    print(f"OB snapshots processed: {strat._event_count}")
    print(f"Trades executed:        {strat.trades}")
    print(f"Final cash:             {broker.getcash():.2f}")
    print(f"Portfolio value:        {broker.getvalue():.2f}")
    print(f"P&L:                    {broker.getvalue() - 100000:.2f}")


if __name__ == '__main__':
    main()
