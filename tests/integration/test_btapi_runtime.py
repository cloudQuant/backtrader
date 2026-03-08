"""Integration tests for the unified bt_api_py broker/feed/store stack."""

import threading
import time

import pytest
import backtrader as bt

from tests.fixtures.fake_btapi import DEFAULT_SYMBOL, FakeBtApiClient, make_store, make_tick


@pytest.mark.integration
def test_btapi_store_broker_and_feed_work_together(btapi_client, btapi_store):
    """Unified store, feed, and broker should work together without venue-specific adapters."""
    data = btapi_store.getdata(dataname=DEFAULT_SYMBOL)
    broker = btapi_store.getbroker()

    data._start()
    broker.start()

    assert data.load() is True
    assert data.close[0] == pytest.approx(100.5)

    order = broker.buy(
        owner=None,
        data=data,
        size=1,
        price=101.0,
        exectype=bt.Order.Limit,
    )

    assert order.status == bt.Order.Accepted
    assert btapi_client.submitted_orders[0]["symbol"] == DEFAULT_SYMBOL

    broker.cancel(order)

    assert order.status == bt.Order.Canceled
    assert btapi_client.cancelled_orders == [{"order_ref": "btapi-1", "dataname": DEFAULT_SYMBOL}]


@pytest.mark.integration
def test_btapi_feed_dispatches_tick_and_bar_events_before_next():
    """Live ticks should surface through notify_tick/notify_bar and then advance next()."""
    client = FakeBtApiClient(
        live_ticks={
            DEFAULT_SYMBOL: [
                make_tick(0, 100.0, volume=1.0),
                make_tick(2, 101.0, volume=2.0),
                make_tick(6, 99.5, volume=3.0),
            ]
        }
    )
    store = make_store(api=client)
    data = store.getdata(
        dataname=DEFAULT_SYMBOL,
        timeframe=bt.TimeFrame.Seconds,
        compression=5,
        backfill_start=False,
    )
    broker = store.getbroker()
    cerebro = bt.Cerebro()

    class TickBarStrategy(bt.Strategy):
        def __init__(self):
            self.tick_count = 0
            self.bar_count = 0
            self.next_count = 0
            self.event_order = []
            self.last_tick = None
            self.last_bar = None

        def notify_tick(self, tick):
            self.tick_count += 1
            self.last_tick = tick
            self.event_order.append("tick")

        def notify_bar(self, bar):
            self.bar_count += 1
            self.last_bar = bar
            self.event_order.append("bar")

        def next(self):
            self.next_count += 1
            self.event_order.append("next")
            self.cerebro.runstop()

    cerebro.setbroker(broker)
    cerebro.adddata(data)
    cerebro.addstrategy(TickBarStrategy)

    results = cerebro.run()
    strategy = results[0]

    assert strategy.tick_count == 3
    assert strategy.bar_count == 1
    assert strategy.next_count == 1
    assert strategy.last_tick.price == pytest.approx(99.5)
    assert strategy.last_bar.open == pytest.approx(100.0)
    assert strategy.last_bar.high == pytest.approx(101.0)
    assert strategy.last_bar.low == pytest.approx(100.0)
    assert strategy.last_bar.close == pytest.approx(101.0)
    assert strategy.last_bar.volume == pytest.approx(3.0)
    assert strategy.event_order.index("bar") < strategy.event_order.index("next")


@pytest.mark.integration
def test_btapi_multidata_waits_for_all_completed_bars_before_next():
    """With multiple live feeds, next() should run only after each data produced a bar."""
    symbol_a = "rb2610"
    symbol_b = "hc2610"
    client = FakeBtApiClient(
        live_ticks={
            symbol_a: [
                make_tick(0, 100.0, volume=1.0, symbol=symbol_a),
                make_tick(6, 101.0, volume=1.0, symbol=symbol_a),
            ],
            symbol_b: [
                make_tick(1, 200.0, volume=1.0, symbol=symbol_b),
                make_tick(7, 202.0, volume=1.0, symbol=symbol_b),
            ],
        }
    )
    store = make_store(api=client)
    data_a = store.getdata(
        dataname=symbol_a,
        timeframe=bt.TimeFrame.Seconds,
        compression=5,
        backfill_start=False,
    )
    data_b = store.getdata(
        dataname=symbol_b,
        timeframe=bt.TimeFrame.Seconds,
        compression=5,
        backfill_start=False,
    )
    broker = store.getbroker()
    cerebro = bt.Cerebro()

    class MultiDataStrategy(bt.Strategy):
        def __init__(self):
            self.bar_symbols = []
            self.next_count = 0

        def notify_bar(self, bar):
            self.bar_symbols.append(bar.symbol)

        def next(self):
            self.next_count += 1
            self.cerebro.runstop()

    cerebro.setbroker(broker)
    cerebro.adddata(data_a)
    cerebro.adddata(data_b)
    cerebro.addstrategy(MultiDataStrategy)

    results = cerebro.run()
    strategy = results[0]

    assert strategy.bar_symbols.count(symbol_a) == 1
    assert strategy.bar_symbols.count(symbol_b) == 1
    assert strategy.next_count == 1


@pytest.mark.integration
def test_btapi_broker_keeps_live_run_waiting_before_first_tick():
    """BtApiBroker should keep a live run alive while the feed waits for its first tick."""
    client = FakeBtApiClient(live_ticks={"rb2610": []})
    store = make_store(api=client)
    broker = store.getbroker()
    data = store.getdata(
        dataname="rb2610",
        timeframe=bt.TimeFrame.Seconds,
        compression=5,
        backfill_start=False,
    )
    cerebro = bt.Cerebro()

    class WaitingStrategy(bt.Strategy):
        def __init__(self):
            self.next_count = 0

        def next(self):
            self.next_count += 1

    cerebro.setbroker(broker)
    cerebro.adddata(data)
    cerebro.addstrategy(WaitingStrategy)

    stop_timer = threading.Timer(0.3, cerebro.runstop)
    stop_timer.daemon = True
    stop_timer.start()
    try:
        started_at = time.perf_counter()
        results = cerebro.run()
        elapsed = time.perf_counter() - started_at
    finally:
        stop_timer.cancel()

    strategy = results[0]

    assert elapsed >= 0.25
    assert strategy.next_count == 0
