"""Unit tests for the unified BtApiFeed."""

import logging

import backtrader as bt
import pytest

from backtrader.feeds.btapifeed import BtApiFeed
from backtrader.stores.btapistore import BtApiStore
from tests.fixtures.fake_btapi import (
    DEFAULT_SYMBOL,
    FakeBtApiClient,
    make_bar,
    make_orderbook,
    make_tick,
    make_store,
)


@pytest.fixture
def feed_stack():
    """Create a feed with deterministic history and live data."""
    client = FakeBtApiClient(
        history={
            DEFAULT_SYMBOL: [
                make_bar(0, 100.0, 101.0, 99.0, 100.5),
                make_bar(1, 100.5, 102.0, 100.0, 101.5),
            ]
        },
    )
    store = make_store(
        api=client,
        live_bars={DEFAULT_SYMBOL: [make_bar(2, 101.5, 103.0, 101.0, 102.5)]},
    )
    feed = store.getdata(dataname=DEFAULT_SYMBOL)
    feed._start()
    return client, store, feed


def test_feed_loads_history_then_live(feed_stack):
    """Feed should backfill history before consuming live bars."""
    _client, _store, feed = feed_stack

    assert feed.load() is True
    assert feed.close[0] == pytest.approx(100.5)

    assert feed.load() is True
    assert feed.close[0] == pytest.approx(101.5)

    assert feed.load() is True
    assert feed.close[0] == pytest.approx(102.5)

    notifications = feed.get_notifications()
    assert notifications == [(feed.LIVE, (), {})]


def test_feed_emits_live_notification_only_once(feed_stack):
    _client, _store, feed = feed_stack

    assert feed.load() is True
    assert feed.load() is True
    assert feed.load() is True
    assert feed.get_notifications() == [(feed.LIVE, (), {})]

    assert feed.load() is None
    assert feed.get_notifications() == []


def test_feed_subscribes_and_reports_live_data(feed_stack):
    """Feed should register its symbol and detect pending live bars."""
    client, _store, feed = feed_stack

    assert client.subscriptions == [DEFAULT_SYMBOL]
    assert feed.haslivedata() is True


def test_feed_start_succeeds_without_api_subscribe_method():
    class NoSubscribeClient:
        def __init__(self):
            self.connected = False
            self.balance = {"cash": 1000.0, "value": 1200.0}
            self.connected = True

        def disconnect(self):
            self.connected = False

    store = make_store(api=NoSubscribeClient())
    feed = store.getdata(dataname=DEFAULT_SYMBOL, backfill_start=False)

    feed._start()

    assert feed in store._data_feeds
    assert DEFAULT_SYMBOL not in store._subscribed_datanames


def test_feed_start_falls_back_to_bound_store_attribute_when_store_param_is_missing():
    class TrackingStore:
        def __init__(self):
            self.calls = []

        def start(self, data=None):
            self.calls.append(("start", data))

        def register(self, data):
            self.calls.append(("register", data))

        def subscribe(self, dataname):
            self.calls.append(("subscribe", dataname))

    store = TrackingStore()
    feed = BtApiFeed(dataname=DEFAULT_SYMBOL, backfill_start=False)
    feed._store = store

    feed.start()

    assert feed.store is store
    assert store.calls[0] == ("start", feed)
    assert store.calls[1] == ("register", feed)
    assert store.calls[2] == ("subscribe", DEFAULT_SYMBOL)


def test_feed_start_continues_to_subscribe_when_initial_backfill_fails():
    class TrackingStore:
        def __init__(self):
            self.calls = []

        def start(self, data=None):
            self.calls.append(("start", data))

        def register(self, data):
            self.calls.append(("register", data))

        def fetch_history(self, dataname, timeframe=None, compression=None):
            self.calls.append(("fetch_history", dataname, timeframe, compression))
            raise RuntimeError("history unavailable")

        def subscribe(self, dataname):
            self.calls.append(("subscribe", dataname))

    store = TrackingStore()
    feed = BtApiFeed(dataname=DEFAULT_SYMBOL, store=store)

    feed.start()

    assert feed.store is store
    assert store.calls[0] == ("start", feed)
    assert store.calls[1] == ("register", feed)
    assert store.calls[2][0] == "fetch_history"
    assert store.calls[2][1] == DEFAULT_SYMBOL
    assert store.calls[3] == ("subscribe", DEFAULT_SYMBOL)
    assert len(feed._history) == 0
    assert feed._history_backfilled is False


def test_feed_start_with_bound_store_fallback_continues_to_subscribe_when_initial_backfill_fails():
    class TrackingStore:
        def __init__(self):
            self.calls = []

        def start(self, data=None):
            self.calls.append(("start", data))

        def register(self, data):
            self.calls.append(("register", data))

        def fetch_history(self, dataname, timeframe=None, compression=None):
            self.calls.append(("fetch_history", dataname, timeframe, compression))
            raise RuntimeError("history unavailable")

        def subscribe(self, dataname):
            self.calls.append(("subscribe", dataname))

    store = TrackingStore()
    feed = BtApiFeed(dataname=DEFAULT_SYMBOL)
    feed._store = store

    feed.start()

    assert feed.store is store
    assert store.calls[0] == ("start", feed)
    assert store.calls[1] == ("register", feed)
    assert store.calls[2][0] == "fetch_history"
    assert store.calls[2][1] == DEFAULT_SYMBOL
    assert store.calls[3] == ("subscribe", DEFAULT_SYMBOL)
    assert len(feed._history) == 0
    assert feed._history_backfilled is False


def test_feed_reports_not_live_without_any_live_capability():
    client = FakeBtApiClient(
        history={DEFAULT_SYMBOL: [make_bar(0, 100.0, 101.0, 99.0, 100.5)]}
    )
    store = make_store(api=client)
    feed = store.getdata(dataname=DEFAULT_SYMBOL)

    feed._start()

    assert feed.islive() is False
    assert feed.haslivedata() is False


def test_feed_islive_returns_false_when_capability_probes_raise_errors():
    class FailingCapabilityClient:
        def __init__(self):
            self.connected = False

        def connect(self):
            self.connected = True

        def disconnect(self):
            self.connected = False

        def supports_live_ticks(self, _symbol):
            raise RuntimeError("tick probe failed")

        def supports_live_orderbook(self, _symbol):
            raise RuntimeError("orderbook probe failed")

    store = make_store(api=FailingCapabilityClient())
    feed = store.getdata(dataname=DEFAULT_SYMBOL, backfill_start=False)

    feed._start()

    assert feed.islive() is False
    assert feed.haslivedata() is False


def test_feed_reports_live_when_store_has_preseeded_live_bars():
    client = FakeBtApiClient()
    store = make_store(api=client, live_bars={DEFAULT_SYMBOL: [make_bar(0, 100.0, 101.0, 99.0, 100.5)]})
    feed = store.getdata(dataname=DEFAULT_SYMBOL, backfill_start=False)

    feed._start()

    assert feed.islive() is True
    assert feed.haslivedata() is True


def test_feed_store_preseeded_live_bars_are_drained_from_haslivedata():
    client = FakeBtApiClient()
    store = make_store(api=client, live_bars={DEFAULT_SYMBOL: [make_bar(0, 100.0, 101.0, 99.0, 100.5)]})
    feed = store.getdata(dataname=DEFAULT_SYMBOL, backfill_start=False)

    feed._start()

    assert feed.haslivedata() is True
    assert feed.load() is True
    assert feed.close[0] == pytest.approx(100.5)
    assert feed.haslivedata() is False


def test_feed_reports_live_when_orderbook_source_is_available():
    client = FakeBtApiClient(
        live_orderbooks={DEFAULT_SYMBOL: [make_orderbook(0, 100.0, 100.5)]}
    )
    store = make_store(api=client)
    feed = store.getdata(dataname=DEFAULT_SYMBOL)

    feed._start()

    assert feed.islive() is True
    assert feed.haslivedata() is True


def test_feed_reports_live_for_attribute_only_live_orderbooks():
    class AttributeOnlyOrderbookClient:
        def __init__(self):
            self.connected = False
            self.live_orderbooks = {DEFAULT_SYMBOL: [make_orderbook(0, 100.0, 100.5)]}

        def connect(self):
            self.connected = True

        def disconnect(self):
            self.connected = False

    store = make_store(api=AttributeOnlyOrderbookClient())
    feed = store.getdata(dataname=DEFAULT_SYMBOL, backfill_start=False)

    feed._start()

    assert feed.islive() is True
    assert feed.haslivedata() is True


def test_feed_reports_live_when_tick_source_is_available():
    client = FakeBtApiClient(
        live_ticks={DEFAULT_SYMBOL: [make_tick(0, 100.0)]}
    )
    store = make_store(api=client)
    feed = store.getdata(dataname=DEFAULT_SYMBOL)

    feed._start()

    assert feed.islive() is True
    assert feed.haslivedata() is True


def test_feed_reports_live_for_attribute_only_live_ticks():
    class AttributeOnlyTickClient:
        def __init__(self):
            self.connected = False
            self.live_ticks = {DEFAULT_SYMBOL: [make_tick(0, 100.0)]}

        def connect(self):
            self.connected = True

        def disconnect(self):
            self.connected = False

    store = make_store(api=AttributeOnlyTickClient())
    feed = store.getdata(dataname=DEFAULT_SYMBOL, backfill_start=False)

    feed._start()

    assert feed.islive() is True
    assert feed.haslivedata() is True


def test_feed_reports_live_with_api_cls_even_before_any_live_data_is_available():
    store = BtApiStore(provider="okx", api=None, api_cls=FakeBtApiClient)
    feed = store.getdata(dataname=DEFAULT_SYMBOL, backfill_start=False)

    assert feed.islive() is True
    assert feed.haslivedata() is False


def test_feed_reports_live_for_attribute_only_api_live_bars():
    class AttributeOnlyLiveBarsClient:
        def __init__(self):
            self.connected = False
            self.live = {DEFAULT_SYMBOL: []}

        def connect(self):
            self.connected = True

        def disconnect(self):
            self.connected = False

    store = make_store(api=AttributeOnlyLiveBarsClient())
    feed = store.getdata(dataname=DEFAULT_SYMBOL, backfill_start=False)

    feed._start()

    assert feed.islive() is True
    assert feed.haslivedata() is False


def test_feed_reports_live_when_store_exists_without_api_instance():
    class ApiLessStore:
        def __init__(self):
            self._live_bars = {}
            self._api = None
            self._api_cls = None

    feed = BtApiFeed(dataname=DEFAULT_SYMBOL, store=ApiLessStore(), backfill_start=False)

    assert feed.islive() is True
    assert feed.haslivedata() is False


def test_feed_live_detection_falls_back_to_bound_store_attribute_when_store_param_is_missing():
    class FallbackStore:
        def __init__(self):
            self._live_bars = {
                DEFAULT_SYMBOL: [make_bar(0, 100.0, 101.0, 99.0, 100.5)]
            }
            self._api = None
            self._api_cls = None

    feed = BtApiFeed(dataname=DEFAULT_SYMBOL, backfill_start=False)
    feed._store = FallbackStore()

    assert feed.islive() is True
    assert feed.haslivedata() is True


def test_feed_haslivedata_falls_back_to_bound_store_pending_orderbook_when_store_param_is_missing():
    class FallbackStore:
        _api = None
        _api_cls = None

        def has_pending_orderbook(self, dataname):
            return dataname == DEFAULT_SYMBOL

    feed = BtApiFeed(dataname=DEFAULT_SYMBOL, backfill_start=False)
    feed._store = FallbackStore()

    assert feed.haslivedata() is True


def test_feed_haslivedata_falls_back_to_bound_store_pending_tick_when_store_param_is_missing():
    class FallbackStore:
        _api = None
        _api_cls = None

        def has_pending_tick(self, dataname):
            return dataname == DEFAULT_SYMBOL

    feed = BtApiFeed(dataname=DEFAULT_SYMBOL, backfill_start=False)
    feed._store = FallbackStore()

    assert feed.haslivedata() is True


@pytest.mark.parametrize("helper_name", ["has_pending_tick", "has_pending_orderbook"])
def test_feed_haslivedata_uses_explicit_store_pending_helpers(helper_name):
    class ExplicitStore:
        _api = None
        _api_cls = None

    store = ExplicitStore()
    setattr(store, helper_name, lambda dataname: dataname == DEFAULT_SYMBOL)

    feed = BtApiFeed(dataname=DEFAULT_SYMBOL, store=store, backfill_start=False)

    assert feed.haslivedata() is True


def test_feed_start_without_store_is_silent_and_preserves_local_live_queue():
    feed = BtApiFeed(
        dataname=DEFAULT_SYMBOL,
        live_bars=[make_bar(0, 100.0, 101.0, 99.0, 100.5)],
        backfill_start=False,
    )

    feed.start()

    assert feed.islive() is True
    assert feed.haslivedata() is True
    assert len(feed._live) == 1


def test_feed_start_without_store_is_silent_and_preserves_local_history_queue():
    feed = BtApiFeed(
        dataname=DEFAULT_SYMBOL,
        historical_bars=[make_bar(0, 100.0, 101.0, 99.0, 100.5)],
    )

    feed.start()

    assert feed.islive() is False
    assert feed.haslivedata() is False
    assert len(feed._history) == 1


def test_feed_stop_without_store_is_silent_and_preserves_local_queues():
    feed = BtApiFeed(
        dataname=DEFAULT_SYMBOL,
        historical_bars=[make_bar(0, 100.0, 101.0, 99.0, 100.5)],
        live_bars=[make_bar(1, 100.5, 101.5, 100.0, 101.0)],
        backfill_start=False,
    )

    feed.stop()

    assert len(feed._history) == 1
    assert len(feed._live) == 1


def test_feed_without_store_can_stream_injected_live_bars():
    feed = BtApiFeed(
        dataname=DEFAULT_SYMBOL,
        live_bars=[make_bar(0, 100.0, 101.0, 99.0, 100.5)],
        backfill_start=False,
    )

    feed._start()

    assert feed.islive() is True
    assert feed.haslivedata() is True
    assert feed.load() is True
    assert feed.close[0] == pytest.approx(100.5)
    assert feed.haslivedata() is False


def test_feed_without_store_can_replay_injected_historical_bars():
    feed = BtApiFeed(
        dataname=DEFAULT_SYMBOL,
        historical_bars=[make_bar(0, 100.0, 101.0, 99.0, 100.5)],
    )

    feed._start()

    assert feed.islive() is False
    assert feed.haslivedata() is False
    assert feed.load() is True
    assert feed.close[0] == pytest.approx(100.5)
    assert feed.load() is None


def test_feed_repeated_start_does_not_duplicate_subscription_within_session_but_resubscribes_after_restart():
    class CountingClient(FakeBtApiClient):
        def __init__(self):
            super().__init__(
                history={DEFAULT_SYMBOL: [make_bar(0, 100.0, 101.0, 99.0, 100.5)]},
            )
            self.history_calls = 0

        def fetch_bars(self, dataname: str, **kwargs):
            self.history_calls += 1
            return super().fetch_bars(dataname, **kwargs)

    client = CountingClient()
    store = make_store(api=client)
    feed = store.getdata(dataname=DEFAULT_SYMBOL)

    feed._start()
    feed.start()

    assert client.subscriptions == [DEFAULT_SYMBOL]

    store.stop()
    feed.start()

    assert client.subscriptions == [DEFAULT_SYMBOL, DEFAULT_SYMBOL]


def test_feed_repeated_start_does_not_refetch_backfill_history():
    class CountingClient(FakeBtApiClient):
        def __init__(self):
            super().__init__(
                history={
                    DEFAULT_SYMBOL: [
                        make_bar(0, 100.0, 101.0, 99.0, 100.5),
                        make_bar(1, 100.5, 102.0, 100.0, 101.5),
                    ]
                }
            )
            self.history_calls = 0

        def fetch_bars(self, dataname: str, **kwargs):
            self.history_calls += 1
            return super().fetch_bars(dataname, **kwargs)

    client = CountingClient()
    store = make_store(api=client)
    feed = store.getdata(dataname=DEFAULT_SYMBOL)

    feed._start()
    assert client.history_calls == 1

    assert feed.load() is True
    assert feed.load() is True
    assert feed.load() is None

    store.stop()
    feed.start()
    assert client.history_calls == 1
    assert feed.load() is None


def test_feed_start_skips_history_backfill_when_disabled():
    class CountingClient(FakeBtApiClient):
        def __init__(self):
            super().__init__(
                history={DEFAULT_SYMBOL: [make_bar(0, 100.0, 101.0, 99.0, 100.5)]}
            )
            self.history_calls = 0

        def fetch_bars(self, dataname: str, **kwargs):
            self.history_calls += 1
            return super().fetch_bars(dataname, **kwargs)

    client = CountingClient()
    store = make_store(api=client)
    feed = store.getdata(dataname=DEFAULT_SYMBOL, backfill_start=False)

    feed._start()

    assert client.history_calls == 0
    assert feed.load() is None


def test_feed_start_skips_history_backfill_when_history_is_preseeded():
    class CountingClient(FakeBtApiClient):
        def __init__(self):
            super().__init__(
                history={DEFAULT_SYMBOL: [make_bar(1, 100.5, 101.5, 100.0, 101.0)]}
            )
            self.history_calls = 0

        def fetch_bars(self, dataname: str, **kwargs):
            self.history_calls += 1
            return super().fetch_bars(dataname, **kwargs)

    client = CountingClient()
    store = make_store(api=client)
    feed = store.getdata(
        dataname=DEFAULT_SYMBOL,
        historical_bars=[make_bar(0, 100.0, 101.0, 99.0, 100.5)],
    )

    feed._start()

    assert client.history_calls == 0
    assert feed.load() is True
    assert feed.close[0] == pytest.approx(100.5)
    assert feed.load() is None


def test_feed_start_logs_backfill_failure_and_continues(caplog):
    class FailingHistoryClient(FakeBtApiClient):
        def fetch_bars(self, dataname: str, **kwargs):
            raise RuntimeError("history unavailable")

    client = FailingHistoryClient()
    store = make_store(api=client)
    feed = store.getdata(dataname=DEFAULT_SYMBOL)

    with caplog.at_level(logging.DEBUG):
        feed._start()

    assert client.subscriptions == [DEFAULT_SYMBOL]
    assert any("Failed to backfill history" in record.message for record in caplog.records)
    assert feed.load() is None


def test_feed_drains_live_ticks_into_channel_events():
    client = FakeBtApiClient(
        live_ticks={DEFAULT_SYMBOL: [make_tick(0, 100.0), make_tick(1, 101.0)]}
    )
    store = make_store(api=client)
    feed = store.getdata(dataname=DEFAULT_SYMBOL, backfill_start=False)
    dispatched = []

    class _Env:
        _tradingcal = None

        def dispatch_channel_event(self, event):
            dispatched.append(event)

    feed.setenvironment(_Env())
    feed._start()

    assert feed.islive() is True
    assert feed.haslivedata() is True

    feed._check()

    assert [event.channel_type for event in dispatched] == ["tick", "tick"]
    assert dispatched[0].data.price == pytest.approx(100.0)
    assert dispatched[1].data.price == pytest.approx(101.0)
    assert feed.haslivedata() is False


def test_feed_tick_timeframe_turns_live_ticks_into_immediate_bars():
    client = FakeBtApiClient(
        live_ticks={DEFAULT_SYMBOL: [make_tick(0, 100.0), make_tick(1, 101.0)]}
    )
    store = make_store(api=client)
    feed = store.getdata(
        dataname=DEFAULT_SYMBOL,
        backfill_start=False,
        timeframe=bt.TimeFrame.Ticks,
    )
    dispatched = []

    class _Env:
        _tradingcal = None

        def dispatch_channel_event(self, event):
            dispatched.append(event)

    feed.setenvironment(_Env())
    feed._start()

    feed._check()

    assert [event.channel_type for event in dispatched] == ["tick", "bar", "tick", "bar"]
    assert feed.haslivedata() is True

    assert feed.load() is True
    assert feed.close[0] == pytest.approx(100.0)
    assert feed.get_notifications() == [(feed.LIVE, (), {})]

    assert feed.load() is True
    assert feed.close[0] == pytest.approx(101.0)
    assert feed.haslivedata() is False


def test_feed_drains_live_orderbooks_into_channel_events():
    """Feed should dispatch queued live orderbooks through the channel callback surface."""
    client = FakeBtApiClient(
        live_orderbooks={
            DEFAULT_SYMBOL: [
                make_orderbook(0, 100.0, 100.5),
                make_orderbook(1, 100.1, 100.6),
            ]
        }
    )
    store = make_store(api=client)
    feed = store.getdata(dataname=DEFAULT_SYMBOL, backfill_start=False)
    dispatched = []

    class _Env:
        _tradingcal = None

        def dispatch_channel_event(self, event):
            dispatched.append(event)

    feed.setenvironment(_Env())
    feed._start()

    assert feed.islive() is True
    assert feed.haslivedata() is True

    feed._check()

    assert [event.channel_type for event in dispatched] == ["orderbook", "orderbook"]
    assert dispatched[0].data.best_bid == pytest.approx(100.0)
    assert dispatched[0].data.best_ask == pytest.approx(100.5)
    assert feed.haslivedata() is False
