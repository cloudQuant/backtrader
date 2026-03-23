import time

import pytest

from backtrader.brokers.mixbroker import MixBroker
from backtrader.events import BarEvent, OrderBookSnapshot, TickEvent


@pytest.mark.slow
def test_midfreq_runtime_baseline_100k_ticks_1000_bars_under_30_seconds():
    broker = MixBroker(cash=100000.0, max_ob_window=100, max_bar_history=200)

    start = time.perf_counter()
    for index in range(100000):
        broker.process_tick(
            TickEvent(
                timestamp=float(index) * 0.01,
                symbol="BTC/USDT",
                price=100.0 + (index % 50) * 0.01,
                volume=1.0,
            )
        )
    for index in range(1000):
        broker.process_bar(
            BarEvent(
                timestamp=1000.0 + float(index),
                symbol="BTC/USDT",
                open=100.0,
                high=101.0,
                low=99.0,
                close=100.0 + (index % 20),
                volume=10.0,
            )
        )
    elapsed = time.perf_counter() - start

    assert elapsed < 30.0, f"elapsed {elapsed:.2f}s exceeds 30s baseline"


@pytest.mark.slow
def test_midfreq_get_ob_ratio_average_latency_under_1ms():
    broker = MixBroker(cash=100000.0, max_ob_window=100)
    context = broker.get_context()

    for index in range(100):
        broker.process_orderbook(
            OrderBookSnapshot(
                timestamp=float(index),
                symbol="BTC/USDT",
                bids=[(100.0 + index * 0.01, 10.0)],
                asks=[(101.0 + index * 0.01, 10.0)],
            )
        )

    start = time.perf_counter()
    for _ in range(1000):
        context.get_ob_ratio("BTC/USDT", levels=10, window=30)
    avg_ms = (time.perf_counter() - start) / 1000.0 * 1000.0

    assert avg_ms < 1.0, f"average latency {avg_ms:.3f}ms exceeds 1ms baseline"
