"""Unit tests for the unified BtApiFeed."""

import datetime as dt
import logging

import backtrader as bt
import pytest

from backtrader.feeds import btapifeed as btapifeed_module
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


def test_tick_datetime_prefers_epoch_timestamp_over_provider_datetime():
    """Provider datetime fields may be mislabeled; epoch timestamp is canonical."""
    timestamp = 1782357359.0
    tick = {
        "timestamp": timestamp,
        "datetime": "2026-06-25T11:15:00.000+00:00",
        "price": 100.0,
    }

    assert btapifeed_module._tick_datetime(tick) == dt.datetime(2026, 6, 25, 3, 15, 59)
    assert btapifeed_module._tick_timestamp(tick) == pytest.approx(timestamp)


def test_tick_datetime_converts_aware_values_to_utc_naive_without_timestamp():
    """Timezone-aware tick datetimes should enter backtrader as UTC-naive values."""
    shanghai = dt.timezone(dt.timedelta(hours=8))
    tick = {"datetime": dt.datetime(2026, 6, 25, 11, 15, 59, tzinfo=shanghai)}

    assert btapifeed_module._tick_datetime(tick) == dt.datetime(2026, 6, 25, 3, 15, 59)
    assert btapifeed_module._tick_timestamp(tick) == pytest.approx(1782357359.0)


def test_tick_timestamp_treats_naive_datetime_as_utc():
    """Naive tick datetimes are already normalized UTC values."""
    tick = {"datetime": dt.datetime(2026, 6, 25, 3, 15, 59)}

    assert btapifeed_module._tick_timestamp(tick) == pytest.approx(1782357359.0)


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
    """Test that feed emits live notification only once."""
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
    """Test that feed start succeeds without api subscribe method."""

    class NoSubscribeClient:
        """Client without subscribe API."""

        def __init__(self):
            """Initialize the no-subscribe client."""
            self.connected = False
            self.balance = {"cash": 1000.0, "value": 1200.0}
            self.connected = True

        def disconnect(self):
            """Disconnect from the client."""
            self.connected = False

    store = make_store(api=NoSubscribeClient())
    feed = store.getdata(dataname=DEFAULT_SYMBOL, backfill_start=False)

    feed._start()

    assert feed in store._data_feeds
    assert DEFAULT_SYMBOL not in store._subscribed_datanames


def test_feed_start_falls_back_to_bound_store_attribute_when_store_param_is_missing():
    """Test that feed start falls back to bound store attribute when store param is missing."""

    class TrackingStore:
        """Store that tracks calls for testing."""

        def __init__(self):
            """Initialize the tracking store."""
            self.calls = []

        def start(self, data=None):
            """Start the store."""
            self.calls.append(("start", data))

        def register(self, data):
            """Register data with the store."""
            self.calls.append(("register", data))

        def subscribe(self, dataname):
            """Subscribe to a dataname."""
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
    """Test that feed start continues to subscribe when initial backfill fails."""

    class TrackingStore:
        """Store that tracks calls for testing backfill failure."""

        def __init__(self):
            """Initialize the tracking store."""
            self.calls = []

        def start(self, data=None):
            """Start the store."""
            self.calls.append(("start", data))

        def register(self, data):
            """Register data with the store."""
            self.calls.append(("register", data))

        def fetch_history(self, dataname, timeframe=None, compression=None):
            """Fetch history that always fails."""
            self.calls.append(("fetch_history", dataname, timeframe, compression))
            raise RuntimeError("history unavailable")

        def subscribe(self, dataname):
            """Subscribe to a dataname."""
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
    """Test that feed start with bound store fallback continues to subscribe when initial backfill fails."""

    class TrackingStore:
        """Store that tracks calls for testing backfill failure with bound store."""

        def __init__(self):
            """Initialize the tracking store."""
            self.calls = []

        def start(self, data=None):
            """Start the store."""
            self.calls.append(("start", data))

        def register(self, data):
            """Register data with the store."""
            self.calls.append(("register", data))

        def fetch_history(self, dataname, timeframe=None, compression=None):
            """Fetch history that always fails."""
            self.calls.append(("fetch_history", dataname, timeframe, compression))
            raise RuntimeError("history unavailable")

        def subscribe(self, dataname):
            """Subscribe to a dataname."""
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
    """Test that feed reports not live without any live capability."""
    client = FakeBtApiClient(
        history={DEFAULT_SYMBOL: [make_bar(0, 100.0, 101.0, 99.0, 100.5)]}
    )
    store = make_store(api=client)
    feed = store.getdata(dataname=DEFAULT_SYMBOL)

    feed._start()

    assert feed.islive() is False
    assert feed.haslivedata() is False


def test_feed_islive_returns_false_when_capability_probes_raise_errors():
    """Test that feed islive returns false when capability probes raise errors."""

    class FailingCapabilityClient:
        """Client whose capability probes always fail."""

        def __init__(self):
            """Initialize the failing capability client."""
            self.connected = False

        def connect(self):
            """Connect to the client."""
            self.connected = True

        def disconnect(self):
            """Disconnect from the client."""
            self.connected = False

        def supports_live_ticks(self, _symbol):
            """Check live ticks support that always fails."""
            raise RuntimeError("tick probe failed")

        def supports_live_orderbook(self, _symbol):
            """Check live orderbook support that always fails."""
            raise RuntimeError("orderbook probe failed")

    store = make_store(api=FailingCapabilityClient())
    feed = store.getdata(dataname=DEFAULT_SYMBOL, backfill_start=False)

    feed._start()

    assert feed.islive() is False
    assert feed.haslivedata() is False


def test_feed_reports_live_when_store_has_preseeded_live_bars():
    """Test that feed reports live when store has preseeded live bars."""
    client = FakeBtApiClient()
    store = make_store(api=client, live_bars={DEFAULT_SYMBOL: [make_bar(0, 100.0, 101.0, 99.0, 100.5)]})
    feed = store.getdata(dataname=DEFAULT_SYMBOL, backfill_start=False)

    feed._start()

    assert feed.islive() is True
    assert feed.haslivedata() is True


def test_feed_reports_live_when_client_declares_streaming_capability_before_subscription():
    """Test that feed reports live when client declares streaming capability before subscription."""

    class StreamingCapabilityClient(FakeBtApiClient):
        """Client that declares streaming capability."""

        def supports_live_streaming(self, _symbol):
            """Check streaming support."""
            return True

    store = make_store(api=StreamingCapabilityClient())
    feed = store.getdata(dataname=DEFAULT_SYMBOL, backfill_start=False)

    feed._start()

    assert feed.islive() is True
    assert feed.haslivedata() is False


def test_feed_store_preseeded_live_bars_are_drained_from_haslivedata():
    """Test that feed store preseeded live bars are drained from haslivedata."""
    client = FakeBtApiClient()
    store = make_store(api=client, live_bars={DEFAULT_SYMBOL: [make_bar(0, 100.0, 101.0, 99.0, 100.5)]})
    feed = store.getdata(dataname=DEFAULT_SYMBOL, backfill_start=False)

    feed._start()

    assert feed.haslivedata() is True
    assert feed.load() is True
    assert feed.close[0] == pytest.approx(100.5)
    assert feed.haslivedata() is False


def test_feed_reports_live_when_orderbook_source_is_available():
    """Test that feed reports live when orderbook source is available."""
    client = FakeBtApiClient(
        live_orderbooks={DEFAULT_SYMBOL: [make_orderbook(0, 100.0, 100.5)]}
    )
    store = make_store(api=client)
    feed = store.getdata(dataname=DEFAULT_SYMBOL)

    feed._start()

    assert feed.islive() is True
    assert feed.haslivedata() is False


def test_feed_reports_live_for_attribute_only_live_orderbooks():
    """Test that feed reports live for attribute-only live orderbooks."""

    class AttributeOnlyOrderbookClient:
        """Client with live orderbook attribute."""

        def __init__(self):
            """Initialize the attribute-only orderbook client."""
            self.connected = False
            self.live_orderbooks = {DEFAULT_SYMBOL: [make_orderbook(0, 100.0, 100.5)]}

        def connect(self):
            """Connect to the client."""
            self.connected = True

        def disconnect(self):
            """Disconnect from the client."""
            self.connected = False

    store = make_store(api=AttributeOnlyOrderbookClient())
    feed = store.getdata(dataname=DEFAULT_SYMBOL, backfill_start=False)

    feed._start()

    assert feed.islive() is True
    assert feed.haslivedata() is False


def test_feed_reports_live_when_tick_source_is_available():
    """Test that feed reports live when tick source is available."""
    client = FakeBtApiClient(
        live_ticks={DEFAULT_SYMBOL: [make_tick(0, 100.0)]}
    )
    store = make_store(api=client)
    feed = store.getdata(dataname=DEFAULT_SYMBOL)

    feed._start()

    assert feed.islive() is True
    assert feed.haslivedata() is False


def test_feed_reports_live_for_attribute_only_live_ticks():
    """Test that feed reports live for attribute-only live ticks."""

    class AttributeOnlyTickClient:
        """Client with live tick attribute."""

        def __init__(self):
            """Initialize the attribute-only tick client."""
            self.connected = False
            self.live_ticks = {DEFAULT_SYMBOL: [make_tick(0, 100.0)]}

        def connect(self):
            """Connect to the client."""
            self.connected = True

        def disconnect(self):
            """Disconnect from the client."""
            self.connected = False

    store = make_store(api=AttributeOnlyTickClient())
    feed = store.getdata(dataname=DEFAULT_SYMBOL, backfill_start=False)

    feed._start()

    assert feed.islive() is True
    assert feed.haslivedata() is False


def test_feed_reports_live_with_api_cls_even_before_any_live_data_is_available():
    """Test that feed reports live with api_cls even before any live data is available."""
    store = BtApiStore(provider="okx", api=None, api_cls=FakeBtApiClient)
    feed = store.getdata(dataname=DEFAULT_SYMBOL, backfill_start=False)

    assert feed.islive() is True
    assert feed.haslivedata() is False


def test_feed_reports_live_for_attribute_only_api_live_bars():
    """Test that feed reports live for attribute-only API live bars."""

    class AttributeOnlyLiveBarsClient:
        """Client with live bars attribute."""

        def __init__(self):
            """Initialize the attribute-only live bars client."""
            self.connected = False
            self.live = {DEFAULT_SYMBOL: []}

        def connect(self):
            """Connect to the client."""
            self.connected = True

        def disconnect(self):
            """Disconnect from the client."""
            self.connected = False

    store = make_store(api=AttributeOnlyLiveBarsClient())
    feed = store.getdata(dataname=DEFAULT_SYMBOL, backfill_start=False)

    feed._start()

    assert feed.islive() is True
    assert feed.haslivedata() is False


def test_feed_reports_live_when_store_exists_without_api_instance():
    """Test that feed reports live when store exists without API instance."""

    class ApiLessStore:
        """Store without API instance."""

        def __init__(self):
            """Initialize the API-less store."""
            self._live_bars = {}
            self._api = None
            self._api_cls = None

    feed = BtApiFeed(dataname=DEFAULT_SYMBOL, store=ApiLessStore(), backfill_start=False)

    assert feed.islive() is True
    assert feed.haslivedata() is False


def test_feed_live_detection_falls_back_to_bound_store_attribute_when_store_param_is_missing():
    """Test that feed live detection falls back to bound store attribute when store param is missing."""

    class FallbackStore:
        """Store that provides fallback live bars."""

        def __init__(self):
            """Initialize the fallback store."""
            self._live_bars = {
                DEFAULT_SYMBOL: [make_bar(0, 100.0, 101.0, 99.0, 100.5)]
            }
            self._api = None
            self._api_cls = None

    feed = BtApiFeed(dataname=DEFAULT_SYMBOL, backfill_start=False)
    feed._store = FallbackStore()

    assert feed.islive() is True
    assert feed.haslivedata() is True


def test_feed_haslivedata_ignores_bound_store_pending_orderbook_when_store_param_is_missing():
    """Pending orderbook traffic is not a completed live bar."""

    class FallbackStore:
        """Store with fallback pending orderbook."""

        _api = None
        _api_cls = None

        def has_pending_orderbook(self, dataname):
            """Check for pending orderbook."""
            return dataname == DEFAULT_SYMBOL

    feed = BtApiFeed(dataname=DEFAULT_SYMBOL, backfill_start=False)
    feed._store = FallbackStore()

    assert feed.haslivedata() is False


def test_feed_haslivedata_ignores_bound_store_pending_tick_when_store_param_is_missing():
    """Pending tick traffic is not a completed live bar."""

    class FallbackStore:
        """Store with fallback pending tick."""

        _api = None
        _api_cls = None

        def has_pending_tick(self, dataname):
            """Check for pending tick."""
            return dataname == DEFAULT_SYMBOL

    feed = BtApiFeed(dataname=DEFAULT_SYMBOL, backfill_start=False)
    feed._store = FallbackStore()

    assert feed.haslivedata() is False


@pytest.mark.parametrize("helper_name", ["has_pending_tick", "has_pending_orderbook"])
def test_feed_haslivedata_ignores_explicit_store_pending_helpers(helper_name):
    """Pending tick/orderbook helpers must not bypass qcheck."""

    class ExplicitStore:
        """Store with explicit pending helpers."""

        _api = None
        _api_cls = None

    store = ExplicitStore()
    setattr(store, helper_name, lambda dataname: dataname == DEFAULT_SYMBOL)

    feed = BtApiFeed(dataname=DEFAULT_SYMBOL, store=store, backfill_start=False)

    assert feed.haslivedata() is False


def test_feed_start_without_store_is_silent_and_preserves_local_live_queue():
    """Test that feed start without store is silent and preserves local live queue."""
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
    """Test that feed start without store is silent and preserves local history queue."""
    feed = BtApiFeed(
        dataname=DEFAULT_SYMBOL,
        historical_bars=[make_bar(0, 100.0, 101.0, 99.0, 100.5)],
    )

    feed.start()

    assert feed.islive() is False
    assert feed.haslivedata() is False
    assert len(feed._history) == 1


def test_feed_stop_without_store_is_silent_and_preserves_local_queues():
    """Test that feed stop without store is silent and preserves local queues."""
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
    """Test that feed without store can stream injected live bars."""
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
    """Test that feed without store can replay injected historical bars."""
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
    """Test that feed repeated start does not duplicate subscription within session but resubscribes after restart."""

    class CountingClient(FakeBtApiClient):
        """Client that counts fetch_bars calls."""

        def __init__(self):
            """Initialize the counting client."""
            super().__init__(
                history={DEFAULT_SYMBOL: [make_bar(0, 100.0, 101.0, 99.0, 100.5)]},
            )
            self.history_calls = 0

        def fetch_bars(self, dataname: str, **kwargs):
            """Fetch bars and count the call."""
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
    """Test that feed repeated start does not refetch backfill history."""

    class CountingClient(FakeBtApiClient):
        """Client that counts fetch_bars calls."""

        def __init__(self):
            """Initialize the counting client."""
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
            """Fetch bars and count the call."""
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
    """Test that feed start skips history backfill when disabled."""

    class CountingClient(FakeBtApiClient):
        """Client that counts fetch_bars calls."""

        def __init__(self):
            """Initialize the counting client."""
            super().__init__(
                history={DEFAULT_SYMBOL: [make_bar(0, 100.0, 101.0, 99.0, 100.5)]}
            )
            self.history_calls = 0

        def fetch_bars(self, dataname: str, **kwargs):
            """Fetch bars and count the call."""
            self.history_calls += 1
            return super().fetch_bars(dataname, **kwargs)

    client = CountingClient()
    store = make_store(api=client)
    feed = store.getdata(dataname=DEFAULT_SYMBOL, backfill_start=False)

    feed._start()

    assert client.history_calls == 0
    assert feed.load() is None


def test_feed_start_skips_history_backfill_when_history_is_preseeded():
    """Test that feed start skips history backfill when history is preseeded."""

    class CountingClient(FakeBtApiClient):
        """Client that counts fetch_bars calls."""

        def __init__(self):
            """Initialize the counting client."""
            super().__init__(
                history={DEFAULT_SYMBOL: [make_bar(1, 100.5, 101.5, 100.0, 101.0)]}
            )
            self.history_calls = 0

        def fetch_bars(self, dataname: str, **kwargs):
            """Fetch bars and count the call."""
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
    """Test that feed start logs backfill failure and continues."""

    class FailingHistoryClient(FakeBtApiClient):
        """Client whose fetch_bars always fails."""

        def fetch_bars(self, dataname: str, **kwargs):
            """Fetch bars that always fails."""
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
    """Test that feed drains live ticks into channel events."""
    client = FakeBtApiClient(
        live_ticks={DEFAULT_SYMBOL: [make_tick(0, 100.0), make_tick(1, 101.0)]}
    )
    store = make_store(api=client)
    feed = store.getdata(dataname=DEFAULT_SYMBOL, backfill_start=False)
    dispatched = []

    class _Env:
        _tradingcal = None

        def dispatch_channel_event(self, event):
            """Dispatch channel event to list."""
            dispatched.append(event)

    feed.setenvironment(_Env())
    feed._start()

    assert feed.islive() is True
    assert feed.haslivedata() is False

    feed._check()

    assert [event.channel_type for event in dispatched] == ["tick", "tick"]
    assert dispatched[0].data.price == pytest.approx(100.0)
    assert dispatched[1].data.price == pytest.approx(101.0)
    assert feed.haslivedata() is False


def test_feed_can_disable_raw_tick_channel_dispatch_while_building_bars():
    """Raw tick callbacks can be disabled without disabling tick-to-bar aggregation."""
    client = FakeBtApiClient(
        live_ticks={DEFAULT_SYMBOL: [make_tick(0, 100.0), make_tick(1, 101.0)]}
    )
    store = make_store(api=client)
    feed = store.getdata(
        dataname=DEFAULT_SYMBOL,
        backfill_start=False,
        dispatch_ticks=False,
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

    assert [event.channel_type for event in dispatched] == ["bar", "bar"]
    assert feed.haslivedata() is True
    assert feed.load() is True
    assert feed.close[0] == pytest.approx(100.0)


def test_feed_waits_qcheck_when_realtime_ticks_do_not_complete_a_bar(monkeypatch):
    """A pending tick is realtime traffic, not a completed bar; qcheck must throttle it."""
    client = FakeBtApiClient(live_ticks={DEFAULT_SYMBOL: [make_tick(0, 100.0)]})
    store = make_store(api=client)
    feed = store.getdata(
        dataname=DEFAULT_SYMBOL,
        backfill_start=False,
        qcheck=0.25,
        timeframe=bt.TimeFrame.Minutes,
        compression=1,
    )
    sleeps = []
    monkeypatch.setattr(btapifeed_module._time, "sleep", sleeps.append)

    feed._start()
    feed.do_qcheck(True, 0.0)

    assert feed.load() is None
    assert sleeps == [pytest.approx(0.25)]
    assert feed.haslivedata() is False


def test_feed_tick_timeframe_turns_live_ticks_into_immediate_bars():
    """Test that feed tick timeframe turns live ticks into immediate bars."""
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
            """Dispatch channel event to list."""
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


def test_feed_tick_timeframe_loads_bar_datetime_from_epoch_timestamp():
    """Loaded tick bars should use UTC-naive datetime derived from epoch timestamp."""
    tick = make_tick(0, 100.0)
    tick.timestamp = 1782357359.0
    tick.datetime = "2026-06-25T11:15:00.000+00:00"
    client = FakeBtApiClient(live_ticks={DEFAULT_SYMBOL: [tick]})
    store = make_store(api=client)
    feed = store.getdata(
        dataname=DEFAULT_SYMBOL,
        backfill_start=False,
        timeframe=bt.TimeFrame.Ticks,
    )

    feed._start()
    feed._check()

    assert feed.load() is True
    assert bt.num2date(feed.lines.datetime[0]).replace(microsecond=0) == dt.datetime(
        2026, 6, 25, 3, 15, 59
    )


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
            """Dispatch channel event to list."""
            dispatched.append(event)

    feed.setenvironment(_Env())
    feed._start()

    assert feed.islive() is True
    assert feed.haslivedata() is False

    feed._check()

    assert [event.channel_type for event in dispatched] == ["orderbook", "orderbook"]
    assert dispatched[0].data.best_bid == pytest.approx(100.0)
    assert dispatched[0].data.best_ask == pytest.approx(100.5)
    assert feed.haslivedata() is False


@pytest.mark.parametrize(
    "client_kwargs",
    [
        {"live_ticks": {DEFAULT_SYMBOL: [make_tick(0, 100.0)]}},
        {"live_orderbooks": {DEFAULT_SYMBOL: [make_orderbook(0, 100.0, 100.5)]}},
    ],
)
def test_feed_marks_live_when_realtime_events_arrive_before_a_completed_bar(client_kwargs):
    """Test that feed marks live when realtime events arrive before a completed bar."""
    client = FakeBtApiClient(**client_kwargs)
    store = make_store(api=client)
    feed = store.getdata(
        dataname=DEFAULT_SYMBOL,
        backfill_start=False,
        timeframe=bt.TimeFrame.Seconds,
        compression=5,
    )

    feed._start()

    assert feed.get_notifications() == []

    feed._check()

    assert feed.get_notifications() == [(feed.LIVE, (), {})]

    feed._check()

    assert feed.get_notifications() == []
