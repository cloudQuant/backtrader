#!/usr/bin/env python
"""Example 4: Live tick trading demo (simulated).

Demonstrates the live trading architecture using LiveEventQueue + Cerebro
with a mock exchange producer (no real connection needed).

For real usage, replace the mock with actual exchange credentials.

Usage:
    python examples/live_tick_demo.py
"""

import os
import sys
import threading
import time
import random

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import backtrader as bt
from backtrader.channels.live_queue import LiveEventQueue
from backtrader.channels.live_validator import LiveDataValidator
from backtrader.channel import EventPriority
from backtrader.events import TickEvent
from backtrader.brokers.tickbroker import TickBroker


class LiveTickStrategy(bt.Strategy):
    """Simple live strategy that prints tick info and tracks stats."""

    def __init__(self):
        """Initialize the strategy with high/low price tracking."""
        self.high = 0
        self.low = float('inf')

    def notify_tick(self, tick):
        """Process incoming tick event and update high/low prices.

        Args:
            tick: TickEvent containing price, volume, and direction data.
        """
        self.high = max(self.high, tick.price)
        self.low = min(self.low, tick.price)

        if self._tick_count % 50 == 0:
            print(f"  [Strategy] Tick #{self._tick_count}: "
                  f"price={tick.price:.2f}, "
                  f"range=[{self.low:.2f}, {self.high:.2f}]")

    def stop(self):
        """Print final statistics when strategy stops.

        Called when Cerebro stops running. Displays total ticks processed
        and the price range observed.
        """
        print(f"Strategy stopped: {self._tick_count} ticks, "
              f"range=[{self.low:.2f}, {self.high:.2f}]")


def mock_exchange_producer(queue, symbol='BTC/USDT', num_ticks=500, rate=100):
    """Simulate a WebSocket producing ticks.

    In real usage, this would be replaced by CCXTLiveTickFeed.

    Args:
        queue: LiveEventQueue to push events into.
        symbol: Trading pair.
        num_ticks: Number of ticks to generate.
        rate: Ticks per second.
    """
    price = 50000.0
    ts = time.time()

    for i in range(num_ticks):
        price += random.gauss(0, 10)
        price = max(price, 40000)
        volume = round(random.lognormvariate(-1, 1.5), 6)
        direction = 'buy' if random.random() > 0.5 else 'sell'
        ts += 1.0 / rate

        tick = TickEvent(
            timestamp=ts,
            symbol=symbol,
            price=round(price, 2),
            volume=volume,
            direction=direction,
        )

        queue.put(
            tick,
            priority=EventPriority.TICK,
            channel_type='tick',
            channel_name=symbol,
            timestamp=ts,
        )

        # Simulate real-time rate
        time.sleep(1.0 / rate)

    # Signal completion
    queue.close()


class ValidatingLiveQueue:
    """Wraps LiveEventQueue to add validation, usable as an iterator."""

    def __init__(self, queue, validator, timeout=2.0):
        """Initialize the validating queue wrapper.

        Args:
            queue: LiveEventQueue to read events from.
            validator: LiveDataValidator instance for validation.
            timeout: Maximum seconds to wait for events before giving up.
        """
        self._queue = queue
        self._validator = validator
        self._timeout = timeout

    def __iter__(self):
        """Yield validated events from the queue until exhausted.

        Yields:
            Validated events from the underlying queue. Stops when
            the queue is closed (returns None).

        Raises:
            QueueEmptyTimeout: If no event is received within timeout.
        """
        while True:
            event = self._queue.get(timeout=self._timeout)
            if event is None:
                break
            if self._validator.validate(event):
                yield event


def main():
    """Run the live tick trading demo with simulated exchange data.

    Creates a mock exchange producer that generates ticks at a configurable
    rate, then processes them through Cerebro with LiveTickStrategy.
    """
    print("Live Tick Trading Demo (Simulated)")
    print("=" * 50)

    symbol = 'BTC/USDT'

    # 1. Create live event queue + validator
    queue = LiveEventQueue(maxsize=10000)
    validator = LiveDataValidator()
    iterable = ValidatingLiveQueue(queue, validator)

    # 2. Set up Cerebro (TickBroker, no cash needed for this demo)
    cerebro = bt.Cerebro()
    cerebro.setbroker(TickBroker(cash=100000.0))
    cerebro.addstrategy(LiveTickStrategy)

    # 3. Start mock producer in background thread
    producer = threading.Thread(
        target=mock_exchange_producer,
        args=(queue, symbol, 500, 200),
        daemon=True,
    )
    producer.start()
    print(f"Mock exchange started for {symbol} (500 ticks @ 200/s)")

    # 4. Run channel event loop (blocks until queue is exhausted)
    print("Processing events...\n")
    start = time.time()

    results = cerebro.run(channel=iterable)

    elapsed = time.time() - start
    strat = results[0]

    # 5. Report
    print(f"\n{'=' * 50}")
    print(f"Live Demo Results")
    print(f"{'=' * 50}")
    print(f"Events processed:   {strat._event_count}")
    print(f"Ticks received:     {strat._tick_count}")
    print(f"Price range:        [{strat.low:.2f}, {strat.high:.2f}]")
    print(f"Elapsed time:       {elapsed:.2f}s")
    if elapsed > 0:
        print(f"Throughput:         {strat._tick_count / elapsed:.0f} ticks/s")

    # Validator stats
    stats = validator.stats
    print(f"Validation rejects: {stats['total_rejected']}")
    if stats['total_rejected'] > 0:
        print(f"Anomaly report:     {validator.get_anomaly_report()}")


if __name__ == '__main__':
    main()
