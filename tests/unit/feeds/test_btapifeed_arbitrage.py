"""Native orderbook feeds drive the native broker and strategy callback path."""

import threading
import time

import backtrader as bt
import pytest

from backtrader.brokers.btapibroker import BtApiBroker
from backtrader.brokers.mixbroker import MixBroker
from backtrader.feeds import btapifeed as feed_module
from tests.fixtures.fake_btapi import (
    DEFAULT_SYMBOL,
    FakeBtApiClient,
    make_bar,
    make_orderbook,
    make_store,
)


def run_bounded(cerebro):
    timer = threading.Timer(2, cerebro.runstop)
    timer.daemon = True
    timer.start()
    try:
        return cerebro.run()[0]
    finally:
        timer.cancel()


def test_orderbook_tick_prepares_actual_feed_before_native_callback_and_matching():
    client = FakeBtApiClient(
        live_orderbooks={DEFAULT_SYMBOL: [make_orderbook(i, 100 + i, 101 + i) for i in range(3)]}
    )
    store = make_store(api=client)
    feed = store.getdata(
        dataname=DEFAULT_SYMBOL,
        timeframe=bt.TimeFrame.Ticks,
        backfill_start=False,
        orderbook_as_ticks=True,
        qcheck=0.01,
    )
    matched = []

    class NativePaperBroker(MixBroker):
        def process_orderbook(self, book, data=None):
            matched.append((book.timestamp, data))
            super().process_orderbook(book, data=data)

    class Strategy(bt.Strategy):
        def __init__(self):
            self.books = 0
            self.filled = []

        def notify_orderbook(self, book):
            self.books += 1
            assert matched[-1] == (book.timestamp, self.data)
            assert self.data.close[0] == pytest.approx(book.mid_price)
            assert self.data.datetime[0] > 1
            if self.books == 1:
                self.buy(data=self.data, size=0.1, price=200, exectype=bt.Order.Limit)

        def notify_order(self, order):
            if order.status == order.Completed:
                self.filled.append(order.executed.size)
                self.cerebro.runstop()

    cerebro = bt.Cerebro(stdstats=False, quicknotify=True)
    cerebro.setbroker(NativePaperBroker(cash=10000))
    cerebro.adddata(feed)
    cerebro.addstrategy(Strategy)
    strategy = run_bounded(cerebro)
    assert strategy.filled == [pytest.approx(0.1)]
    assert strategy.books == 2
    assert len(client.live_orderbooks[DEFAULT_SYMBOL]) == 1


def test_orderbook_tick_does_not_dispatch_from_check_before_allocating_lines():
    client = FakeBtApiClient(live_orderbooks={DEFAULT_SYMBOL: [make_orderbook(0, 100, 101)]})
    store = make_store(api=client)
    feed = store.getdata(
        dataname=DEFAULT_SYMBOL,
        timeframe=bt.TimeFrame.Ticks,
        backfill_start=False,
        orderbook_as_ticks=True,
    )
    feed._start()
    feed._check()
    assert len(client.live_orderbooks[DEFAULT_SYMBOL]) == 1
    assert len(feed) == 0
    assert feed.load() is True
    assert feed.close[0] == pytest.approx(100.5)
    assert feed.volume[0] == 0
    store.stop()


def test_orderbook_tick_rejects_bar_timeframe():
    feed = feed_module.BtApiFeed(dataname=DEFAULT_SYMBOL, orderbook_as_ticks=True)
    with pytest.raises(ValueError, match="TimeFrame.Ticks"):
        feed.start()
    assert feed._session_active is False


def test_feed_restart_emits_a_fresh_live_transition():
    client = FakeBtApiClient(live_orderbooks={DEFAULT_SYMBOL: []})
    store = make_store(api=client)
    feed = store.getdata(
        dataname=DEFAULT_SYMBOL,
        timeframe=bt.TimeFrame.Ticks,
        backfill_start=False,
    )
    try:
        feed._start()
        feed._mark_live()
        feed._mark_live()
        first = [status for status, _args, _kwargs in feed.get_notifications()]
        assert first == [feed.LIVE]

        feed.stop()
        store.stop()
        feed._start()
        feed._mark_live()
        second = [status for status, _args, _kwargs in feed.get_notifications()]
        assert second == [feed.LIVE]
    finally:
        feed.stop()
        store.stop()


@pytest.mark.parametrize("quicknotify", [False, True])
def test_remote_ioc_notification_is_delivered_during_market_data_gap(quicknotify):
    client = FakeBtApiClient(
        history={DEFAULT_SYMBOL: [make_bar(0, 100, 101, 99, 100)]},
        live_orderbooks={DEFAULT_SYMBOL: []},
    )
    original_submit = client.submit_order

    def submit(payload):
        response = original_submit(payload)
        client.broker_updates.append(
            {
                "kind": "order",
                "bt_order_ref": payload["bt_order_ref"],
                "status": "expired",
                "filled": 0.4,
                "avg_price": 100,
                "cumulative_commission": 0.02,
            }
        )
        return response

    client.submit_order = submit
    store = make_store(api=client)
    data = store.getdata(dataname=DEFAULT_SYMBOL, qcheck=0.01)
    broker = store.getbroker(validation_enabled=False, force_refresh_queries=False)

    class Strategy(bt.Strategy):
        def __init__(self):
            self.bars = 0
            self.terminals = []

        def next(self):
            self.bars += 1
            self.buy(data=self.data, size=1, price=101, exectype=bt.Order.Limit)

        def notify_order(self, order):
            if order.status == order.Expired:
                self.terminals.append((order.executed.size, order.executed.comm))
                self.cerebro.runstop()

    cerebro = bt.Cerebro(stdstats=False, quicknotify=quicknotify)
    cerebro.setbroker(broker)
    cerebro.adddata(data)
    cerebro.addstrategy(Strategy)
    strategy = run_bounded(cerebro)
    assert strategy.bars == 1
    assert strategy.terminals == [pytest.approx((0.4, 0.02))]


def test_orderbook_only_idle_loop_polls_live_broker_without_spinning(monkeypatch):
    sleeps = []
    monkeypatch.setattr(feed_module._time, "sleep", sleeps.append)
    client = FakeBtApiClient(live_orderbooks={DEFAULT_SYMBOL: []})
    store = make_store(api=client)
    data = store.getdata(dataname=DEFAULT_SYMBOL, backfill_start=False, qcheck=0.02)
    cerebro = bt.Cerebro(stdstats=False)

    class CountingBroker(BtApiBroker):
        def next(self):
            self.calls = getattr(self, "calls", 0) + 1
            super().next()
            if self.calls == 3:
                cerebro.runstop()

    broker = CountingBroker(store=store)
    cerebro.setbroker(broker)
    cerebro.adddata(data)
    cerebro.addstrategy(bt.Strategy)
    run_bounded(cerebro)
    assert broker.calls == 3
    assert len(sleeps) == 3
    assert all(0 < delay <= 0.02 for delay in sleeps)


def test_normalized_sdk_ctp_book_uses_native_feed_broker_and_strategy():
    """A standard non-crypto SDK event follows the same native Cerebro path."""
    from collections import deque

    from backtrader.stores.btapistore import BtApiStore

    class Sdk:
        def __init__(self):
            self.books = deque(
                {
                    "kind": "orderbook",
                    "symbol": "IF2609",
                    "exchange": "CFFEX",
                    "asset_type": "futures",
                    "timestamp": 1788600000 + i,
                    "received_monotonic_ns": time.monotonic_ns() + i,
                    "clock_domain_id": "ctp-sdk-test-process-monotonic",
                    "bids": [(4000 + i, 5)],
                    "asks": [(4001 + i, 5)],
                    "sequence": i + 1,
                    "snapshot_or_delta": "snapshot",
                    "continuity_status": "continuous",
                }
                for i in range(3)
            )
            self.closed = False

        def subscribe(self, name, topics):
            assert name == "CTP___FUTURE___IF2609"

        def configure_execution(self, config):
            assert config["market_data_only"] is True

        def get_all_balances(self, *, normalized):
            assert normalized
            return {"CTP___FUTURE": {"cash": 0, "value": 0, "currency": "CNY"}}

        def get_portfolio_balance(self, *, venue_balances):
            return {"cash": 0, "value": 0}

        def poll_event(self, venue):
            assert venue == "CTP___FUTURE"
            return self.books.popleft() if self.books else None

        def close(self):
            self.closed = True

    sdk = Sdk()
    store = BtApiStore(
        provider="btapi",
        api=sdk,
        config={
            "exchange_kwargs": {"CTP___FUTURE": {}},
            "symbol_routes": {"IF2609": "CTP___FUTURE"},
            "market_data_only": True,
        },
    )
    data = store.getdata(
        dataname="IF2609",
        timeframe=bt.TimeFrame.Ticks,
        backfill_start=False,
        orderbook_as_ticks=True,
        qcheck=0.01,
    )

    class Strategy(bt.Strategy):
        def __init__(self):
            self.books = []
            self.fills = []

        def notify_orderbook(self, book):
            self.books.append(book)
            assert self.data.close[0] == book.mid_price
            if len(self.books) == 1:
                self.buy(
                    data=self.data, size=1, price=4100, exectype=bt.Order.Limit, time_in_force="IOC"
                )

        def notify_order(self, order):
            if order.status == order.Completed:
                self.fills.append(order.executed.size)
                self.cerebro.runstop()

    cerebro = bt.Cerebro(stdstats=False, quicknotify=True)
    cerebro.setbroker(MixBroker(cash=100000))
    cerebro.adddata(data)
    cerebro.addstrategy(Strategy)
    strategy = run_bounded(cerebro)
    assert strategy.fills == [1]
    assert strategy.books[0].exchange == "CFFEX"
    assert strategy.books[0].asset_type == "futures"
    assert sdk.closed
