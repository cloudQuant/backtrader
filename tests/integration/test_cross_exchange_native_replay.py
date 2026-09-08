"""Native offline order-book replay for the two cross-exchange examples."""

from collections import Counter, deque
from decimal import Decimal
from importlib import import_module
import threading
import time

import backtrader as bt
import pytest

from backtrader.brokers.hft.exchange import SimpleExchangeModel
from backtrader.brokers.mixbroker import MixBroker
from backtrader.comminfo import ComminfoFuturesPercent
from backtrader.events import OrderBookSnapshot
from backtrader.feeds.btapifeed import BtApiFeed
from backtrader.stores.btapistore import BtApiStore

EXAMPLES = (
    pytest.param(
        import_module("examples.012_1_midfreq_cross_exchange.run"),
        import_module("examples.012_1_midfreq_cross_exchange.strategy"),
        id="mid-frequency",
    ),
    pytest.param(
        import_module("examples.012_2_event_driven_cross_exchange.run"),
        import_module("examples.012_2_event_driven_cross_exchange.strategy"),
        id="event-driven",
    ),
)


class OfflineOrderBookClient:
    """Market-input-only client for the real BtApiStore polling surface."""

    def __init__(self, books):
        self.books = {symbol: deque(symbol_books) for symbol, symbol_books in books.items()}
        self.subscriptions = []
        self.served = Counter()
        self.connected = False
        self.stop_requested = False
        self._stop_callback = None
        self._empty_polls = 0

    def set_stop_callback(self, callback):
        self._stop_callback = callback

    def connect(self):
        self.connected = True

    def disconnect(self):
        self.connected = False

    def subscribe(self, symbol):
        self.subscriptions.append(symbol)

    def supports_live_orderbook(self, symbol):
        return symbol in self.books

    def has_pending_orderbook(self, symbol):
        return bool(self.books.get(symbol))

    def poll_orderbook(self, symbol):
        queue = self.books.get(symbol)
        if queue:
            self._empty_polls = 0
            self.served[symbol] += 1
            return queue.popleft()

        if all(not pending for pending in self.books.values()):
            self._empty_polls += 1
            if self._empty_polls >= 4 and self._stop_callback is not None:
                callback, self._stop_callback = self._stop_callback, None
                self.stop_requested = True
                callback()
        return None


def _offline_books(rules, venue_symbols):
    wall_time = time.time()
    received_monotonic_ns = time.monotonic_ns()
    prices = {
        "okx": (59999.0, 60000.0),
        "binance": (60400.0, 60401.0),
    }
    books = {}
    for venue, symbol in venue_symbols.items():
        bid, ask = prices[venue]
        native_depth = float(rules[venue].base_to_native(Decimal("0.10")))
        books[symbol] = [
            OrderBookSnapshot(
                timestamp=wall_time,
                local_time=wall_time,
                exchange_time=wall_time,
                received_wall_time=wall_time,
                received_monotonic_ns=received_monotonic_ns,
                clock_domain_id="offline-native-replay",
                sequence=1,
                snapshot_or_delta="snapshot",
                continuity_status="snapshot",
                source="offline-fixture",
                symbol=symbol,
                exchange=venue,
                asset_type="swap",
                bids=[(bid, native_depth)],
                asks=[(ask, native_depth)],
            )
        ]
    return books


@pytest.mark.integration
@pytest.mark.parametrize(("runner", "strategy_module"), EXAMPLES)
def test_cross_exchange_shadow_consumes_native_orderbooks_without_execution(
    runner, strategy_module
):
    """Both examples consume Store/Feed events while shadow stays execution-free."""
    rules = runner.replay_rules()
    risk = runner.risk_from_config(runner.load_config())
    venue_symbols = strategy_module.VENUE_SYMBOLS
    client = OfflineOrderBookClient(_offline_books(rules, venue_symbols))
    store = BtApiStore(provider="btapi", api=client)
    broker = MixBroker(
        cash=2000.0,
        position_mode="dual_side",
        exchange_model=SimpleExchangeModel(),
    )
    cerebro = bt.Cerebro(stdstats=False, quicknotify=True)
    cerebro.setbroker(broker)

    feeds = []
    for venue, symbol in venue_symbols.items():
        rule = rules[venue]
        broker.addcommissioninfo(
            ComminfoFuturesPercent(
                commission=float(rule.taker_fee),
                mult=float(rule.multiplier),
                margin=1,
            ),
            name=symbol,
        )
        feed = store.getdata(
            dataname=symbol,
            timeframe=bt.TimeFrame.Ticks,
            orderbook_as_ticks=True,
            backfill_start=False,
            qcheck=0.001,
        )
        feeds.append(feed)
        cerebro.adddata(feed, name=symbol)

    cerebro.addstrategy(
        strategy_module.CrossExchangeArbitrageStrategy,
        rules=rules,
        risk=risk,
        funding={venue: (Decimal(0), Decimal("99999999999")) for venue in venue_symbols},
        execution_enabled=False,
        shadow=True,
    )
    assert store.set_source_stop_callback(cerebro.runstop) is True
    initial_value = broker.getvalue()
    watchdog = threading.Timer(2.0, cerebro.runstop)
    watchdog.daemon = True
    watchdog.start()
    try:
        results = cerebro.run(preload=False, runonce=False)
    finally:
        watchdog.cancel()
        store.stop()

    strategy = results[0]
    report = strategy.report()
    expected_symbols = set(venue_symbols.values())
    final_value = broker.getvalue()

    assert type(store) is BtApiStore
    assert type(cerebro) is bt.Cerebro
    assert type(broker) is MixBroker
    assert all(type(feed) is BtApiFeed for feed in feeds)
    assert type(strategy) is strategy_module.CrossExchangeArbitrageStrategy
    assert not hasattr(client, "submit_order")
    assert not hasattr(client, "cancel_order")
    assert not hasattr(client, "poll_broker_update")
    assert client.stop_requested is True
    assert client.connected is False
    assert set(client.subscriptions) == expected_symbols
    assert client.served == Counter(dict.fromkeys(expected_symbols, 1))
    assert set(strategy._last_ob) == expected_symbols
    assert set(strategy.engine.books) == set(venue_symbols)

    assert report["order_count"] == 0
    assert report["submitted_order_count"] == 0
    assert report["confirmed_fill_events"] == 0
    assert report["confirmed_fill_ledger"] == []
    assert report["execution_economics"] == []
    assert Decimal(report["fees_paid"]) == 0
    assert broker._pending_orders == []
    assert broker._order_history == []
    assert all(broker.getposition(feed).size == 0 for feed in feeds)
    assert final_value == pytest.approx(initial_value)
    assert Decimal(str(final_value)) - Decimal(str(initial_value)) == 0
    assert Decimal(report["broker_value"]) == Decimal(str(initial_value))
