"""Unit tests for the unified BtApiStore."""

import time

import pytest

from backtrader.brokers.btapibroker import BtApiBroker
from backtrader.feeds.btapifeed import BtApiFeed
from backtrader.stores.btapistore import (
    BtApiMissingDependencyError,
    BtApiProviderNotImplementedError,
    BtApiStoreError,
    BtApiStore,
    _create_ctp_wrapper_class,
    _split_ctp_symbol,
)
from tests.fixtures.fake_btapi import (
    DEFAULT_SYMBOL,
    FakeBtApiClient,
    make_bar,
    make_orderbook,
    make_tick,
    make_store,
)


@pytest.fixture
def fake_client():
    """Create a fake bt_api_py client with history and live bars."""
    return FakeBtApiClient(
        positions=[{"instrument": DEFAULT_SYMBOL, "volume": 2, "price": 99.5}],
        history={
            DEFAULT_SYMBOL: [
                make_bar(0, 100.0, 101.0, 99.0, 100.5),
                make_bar(1, 100.5, 102.0, 100.0, 101.5),
            ]
        },
        live={DEFAULT_SYMBOL: [make_bar(2, 101.5, 103.0, 101.0, 102.5)]},
    )


def test_store_uses_injected_api_client(fake_client):
    """Store should proxy account, history, and live polling through the injected API."""
    store = make_store(api=fake_client)

    store.start()

    assert store.is_connected is True
    assert fake_client.connected is True
    assert store.get_cash() == pytest.approx(10000.0)
    assert store.get_value() == pytest.approx(10000.0)
    assert len(store.get_positions()) == 1

    store.subscribe(DEFAULT_SYMBOL)
    history = store.fetch_history(DEFAULT_SYMBOL)
    live_bar = store.poll_live(DEFAULT_SYMBOL)

    assert fake_client.subscriptions == [DEFAULT_SYMBOL]
    assert len(history) == 2
    assert history[0]["close"] == pytest.approx(100.5)
    assert live_bar["close"] == pytest.approx(102.5)

    store.stop()
    assert fake_client.connected is False


def test_store_poll_live_uses_preseeded_live_bars_before_start_without_connecting():
    """Test that poll_live uses preseeded live bars before start without connecting."""
    class TrackingClient(FakeBtApiClient):
        """Tracking client that counts connect calls."""

        def __init__(self):
            """Initialize the tracking client."""
            super().__init__()
            self.connect_calls = 0

        def connect(self):
            """Connect and increment counter."""
            self.connect_calls += 1
            return super().connect()

    client = TrackingClient()
    store = make_store(
        api=client,
        live_bars={DEFAULT_SYMBOL: [make_bar(0, 100.0, 101.0, 99.0, 100.5)]},
    )

    assert store.is_connected is False

    live_bar = store.poll_live(DEFAULT_SYMBOL)

    assert live_bar["close"] == pytest.approx(100.5)
    assert store.is_connected is False
    assert client.connect_calls == 0

    assert store.poll_live(DEFAULT_SYMBOL) is None
    assert store.is_connected is True
    assert client.connect_calls == 1


def test_store_compatibility_query_aliases_match_canonical_methods(fake_client):
    """Test that compatibility query aliases match canonical methods."""
    store = make_store(api=fake_client)

    store.start()

    assert store.getcash() == pytest.approx(store.get_cash())
    assert store.getvalue() == pytest.approx(store.get_value())
    assert store.getpositions() == store.get_positions()


def test_store_seeded_account_queries_return_cached_values_before_start():
    """Test that seeded account queries return cached values before store start."""

    class TrackingClient(FakeBtApiClient):
        """Client that tracks connect() call count."""

        def __init__(self):
            """Initialize the tracking client."""
            super().__init__()
            self.connect_calls = 0

        def connect(self):
            """Connect and increment counter."""
            self.connect_calls += 1
            return super().connect()

    client = TrackingClient()
    store = make_store(api=client, cash=321.0, value=654.0, account_cache_ttl=60.0)

    assert store.is_connected is False
    assert store.get_balance() == {"cash": 321.0, "value": 654.0}
    assert store.get_cash() == pytest.approx(321.0)
    assert store.get_value() == pytest.approx(654.0)
    assert store.getcash() == pytest.approx(321.0)
    assert store.getvalue() == pytest.approx(654.0)
    assert store.getvalue(datas=[object()]) == pytest.approx(654.0)
    assert store.is_connected is False
    assert client.connect_calls == 0


def test_store_seeded_account_queries_fall_back_to_cached_values_before_start_when_query_fails():
    """Test fallback to cached values when query fails before store start."""

    class FailingBalanceClient(FakeBtApiClient):
        """Client that fails balance queries but tracks connect calls."""

        def __init__(self):
            """Initialize the failing balance client."""
            super().__init__()
            self.connect_calls = 0

        def connect(self):
            """Connect and increment counter."""
            self.connect_calls += 1
            return super().connect()

        def get_balance(self):
            """Raise error to simulate balance unavailable."""
            raise RuntimeError("balance unavailable")

    client = FailingBalanceClient()
    store = make_store(api=client, cash=321.0, value=654.0)

    assert store.is_connected is False
    assert store.get_balance() == {"cash": 321.0, "value": 654.0}
    assert store.get_cash() == pytest.approx(321.0)
    assert store.get_value() == pytest.approx(654.0)
    assert store.getcash() == pytest.approx(321.0)
    assert store.getvalue() == pytest.approx(654.0)
    assert store.getvalue(datas=[object()]) == pytest.approx(654.0)
    assert store.is_connected is True
    assert client.connect_calls == 1


def test_store_seeded_account_queries_fall_back_to_cached_values_before_start_when_get_account_alias_fails():
    """Test fallback to cached values when get_account fails before store start."""

    class FailingAccountAliasClient:
        """Client that fails account queries."""

        def __init__(self):
            """Initialize the failing account client."""
            self.connected = False
            self.connect_calls = 0

        def connect(self):
            """Connect and increment counter."""
            self.connect_calls += 1
            self.connected = True

        def disconnect(self):
            """Disconnect and set connected to False."""
            self.connected = False

        def get_account(self):
            """Raise error to simulate account unavailable."""
            raise RuntimeError("account unavailable")

    client = FailingAccountAliasClient()
    store = make_store(api=client, cash=321.0, value=654.0)

    assert store.is_connected is False
    assert store.get_balance() == {"cash": 321.0, "value": 654.0}
    assert store.get_cash() == pytest.approx(321.0)
    assert store.get_value() == pytest.approx(654.0)
    assert store.getcash() == pytest.approx(321.0)
    assert store.getvalue() == pytest.approx(654.0)
    assert store.getvalue(datas=[object()]) == pytest.approx(654.0)
    assert store.is_connected is True
    assert client.connect_calls == 1


def test_store_seeded_position_queries_return_cached_values_before_start():
    """Test that seeded position queries return cached values before store start."""

    class TrackingClient(FakeBtApiClient):
        """Client that tracks connect() call count."""

        def __init__(self):
            """Initialize the tracking client."""
            super().__init__()
            self.connect_calls = 0

        def connect(self):
            """Connect and increment counter."""
            self.connect_calls += 1
            return super().connect()

    client = TrackingClient()
    store = make_store(
        api=client,
        positions=[{"instrument": DEFAULT_SYMBOL, "volume": 2.0, "price": 99.5}],
        positions_cache_ttl=60.0,
    )

    assert store.is_connected is False
    positions = store.get_positions()
    compat_positions = store.getpositions()
    assert positions[0]["instrument"] == DEFAULT_SYMBOL
    assert positions[0]["volume"] == pytest.approx(2.0)
    assert positions[0]["price"] == pytest.approx(99.5)
    assert compat_positions[0]["instrument"] == DEFAULT_SYMBOL
    assert compat_positions[0]["volume"] == pytest.approx(2.0)
    assert compat_positions[0]["price"] == pytest.approx(99.5)
    assert store.is_connected is False
    assert client.connect_calls == 0

    positions[0]["volume"] = 999

    assert store._positions_cache[0]["volume"] == pytest.approx(2.0)
    assert store.get_positions()[0]["volume"] == pytest.approx(2.0)


def test_store_seeded_position_queries_fall_back_to_cached_values_before_start_when_query_fails():
    """Test fallback to cached positions when query fails before store start."""

    class FailingPositionsClient(FakeBtApiClient):
        """Client that fails position queries but tracks connect calls."""

        def __init__(self):
            """Initialize the failing positions client."""
            super().__init__()
            self.connect_calls = 0

        def connect(self):
            """Connect and increment counter."""
            self.connect_calls += 1
            return super().connect()

        def get_positions(self):
            """Raise error to simulate positions unavailable."""
            raise RuntimeError("positions unavailable")

    client = FailingPositionsClient()
    store = make_store(
        api=client,
        positions=[{"instrument": DEFAULT_SYMBOL, "volume": 2.0, "price": 99.5}],
    )

    assert store.is_connected is False
    positions = store.get_positions()
    compat_positions = store.getpositions()
    assert positions[0]["instrument"] == DEFAULT_SYMBOL
    assert positions[0]["volume"] == pytest.approx(2.0)
    assert positions[0]["price"] == pytest.approx(99.5)
    assert compat_positions[0]["instrument"] == DEFAULT_SYMBOL
    assert compat_positions[0]["volume"] == pytest.approx(2.0)
    assert compat_positions[0]["price"] == pytest.approx(99.5)
    assert store.is_connected is True
    assert client.connect_calls == 1

    positions[0]["volume"] = 999
    compat_positions[0]["volume"] = 555

    assert store._positions_cache[0]["volume"] == pytest.approx(2.0)
    assert store.get_positions()[0]["volume"] == pytest.approx(2.0)


def test_store_seeded_open_order_queries_return_cached_values_before_start():
    """Test that seeded open order queries return cached values before store start."""

    class TrackingClient(FakeBtApiClient):
        """Client that tracks connect() call count."""

        def __init__(self):
            """Initialize the tracking client."""
            super().__init__()
            self.connect_calls = 0

        def connect(self):
            """Connect and increment counter."""
            self.connect_calls += 1
            return super().connect()

    client = TrackingClient()
    store = make_store(api=client, open_orders_cache_ttl=60.0)
    store._open_orders_cache = [{"id": "btapi-1", "symbol": DEFAULT_SYMBOL, "side": "buy"}]
    store._last_open_orders_refresh = time.monotonic()

    assert store.is_connected is False
    open_orders = store.fetch_open_orders()
    alias_orders = store.get_open_orders()
    compat_orders = store.getopenorders()
    assert [item["id"] for item in open_orders] == ["btapi-1"]
    assert [item["id"] for item in alias_orders] == ["btapi-1"]
    assert [item["id"] for item in compat_orders] == ["btapi-1"]
    assert store.is_connected is False
    assert client.connect_calls == 0

    open_orders[0]["id"] = "mutated"

    assert store._open_orders_cache[0]["id"] == "btapi-1"
    assert store.fetch_open_orders()[0]["id"] == "btapi-1"


def test_store_seeded_open_order_queries_fall_back_to_cached_values_before_start_when_query_fails():
    """Test fallback to cached open orders when query fails before store start."""

    class FailingOpenOrdersClient(FakeBtApiClient):
        """Client that fails open order queries but tracks connect calls."""

        def __init__(self):
            """Initialize the failing open orders client."""
            super().__init__()
            self.connect_calls = 0

        def connect(self):
            """Connect and increment counter."""
            self.connect_calls += 1
            return super().connect()

        def fetch_open_orders(self):
            """Raise error to simulate open orders unavailable."""
            raise RuntimeError("open orders unavailable")

    client = FailingOpenOrdersClient()
    store = make_store(api=client)
    store._open_orders_cache = [{"id": "btapi-1", "symbol": DEFAULT_SYMBOL, "side": "buy"}]
    store._last_open_orders_refresh = time.monotonic()

    assert store.is_connected is False
    open_orders = store.fetch_open_orders()
    alias_orders = store.get_open_orders()
    compat_orders = store.getopenorders()
    assert [item["id"] for item in open_orders] == ["btapi-1"]
    assert [item["id"] for item in alias_orders] == ["btapi-1"]
    assert [item["id"] for item in compat_orders] == ["btapi-1"]
    assert store.is_connected is True
    assert client.connect_calls == 1

    open_orders[0]["id"] = "mutated"
    alias_orders[0]["id"] = "alias-mutated"

    assert store._open_orders_cache[0]["id"] == "btapi-1"
    assert store.fetch_open_orders()[0]["id"] == "btapi-1"


def test_store_queries_connect_on_demand_before_start_when_cache_is_not_fresh():
    """Test that queries connect on demand when cache is not fresh."""

    class TrackingClient(FakeBtApiClient):
        """Client that tracks connect() call count."""

        def __init__(self):
            """Initialize the tracking client."""
            super().__init__()
            self.connect_calls = 0

        def connect(self):
            """Connect and increment counter."""
            self.connect_calls += 1
            return super().connect()

    client = TrackingClient()
    store = make_store(api=client)

    assert store.is_connected is False
    assert store.get_balance() == {"cash": 10000.0, "value": 10000.0}
    assert store.get_cash() == pytest.approx(10000.0)
    assert store.get_value() == pytest.approx(10000.0)
    assert store.getcash() == pytest.approx(10000.0)
    assert store.getvalue() == pytest.approx(10000.0)
    assert store.is_connected is True
    assert client.connect_calls == 1


def test_store_account_queries_work_before_start_with_lightweight_get_balance_client_without_connect_method():
    """Test account queries work with lightweight client that has no connect method."""

    class LightweightBalanceClient:
        """Lightweight client with only get_balance method."""

        def get_balance(self):
            """Return mock balance data."""
            return {"cash": 10000.0, "value": 10000.0}

    store = make_store(api=LightweightBalanceClient(), account_cache_ttl=60.0)

    assert store.is_connected is False
    assert store.get_balance() == {"cash": 10000.0, "value": 10000.0}
    assert store.get_cash() == pytest.approx(10000.0)
    assert store.get_value() == pytest.approx(10000.0)
    assert store.getcash() == pytest.approx(10000.0)
    assert store.getvalue() == pytest.approx(10000.0)
    assert store.getvalue(datas=[object()]) == pytest.approx(10000.0)
    assert store.is_connected is True


def test_store_account_queries_use_get_account_alias_on_demand_before_start():
    """Test that account queries use get_account on demand before store start."""

    class AccountOnlyClient:
        """Client with only connect/disconnect and get_account methods."""

        def __init__(self):
            """Initialize the account-only client."""
            self.connected = False
            self.connect_calls = 0

        def connect(self):
            """Connect and increment counter."""
            self.connect_calls += 1
            self.connected = True

        def disconnect(self):
            """Disconnect and set connected to False."""
            self.connected = False

        def get_account(self):
            """Return mock account data."""
            return {"cash": 1234.0, "value": 1500.0}

    client = AccountOnlyClient()
    store = make_store(api=client, account_cache_ttl=60.0)

    assert store.is_connected is False
    assert store.get_balance() == {"cash": 1234.0, "value": 1500.0}
    assert store.get_cash() == pytest.approx(1234.0)
    assert store.get_value() == pytest.approx(1500.0)
    assert store.getcash() == pytest.approx(1234.0)
    assert store.getvalue() == pytest.approx(1500.0)
    assert store.is_connected is True
    assert client.connect_calls == 1


def test_store_account_queries_use_get_account_alias_on_demand_before_start_without_connect_method():
    """Test that lightweight account-only client works without connect method."""

    class LightweightAccountOnlyClient:
        """Lightweight client with only get_account method."""

        def get_account(self):
            """Return mock account data."""
            return {"cash": 1234.0, "value": 1500.0}

    store = make_store(api=LightweightAccountOnlyClient(), account_cache_ttl=60.0)

    assert store.is_connected is False
    assert store.get_balance() == {"cash": 1234.0, "value": 1500.0}
    assert store.get_cash() == pytest.approx(1234.0)
    assert store.get_value() == pytest.approx(1500.0)
    assert store.getcash() == pytest.approx(1234.0)
    assert store.getvalue() == pytest.approx(1500.0)
    assert store.getvalue(datas=[object()]) == pytest.approx(1500.0)
    assert store.is_connected is True


def test_store_account_queries_fall_back_to_cached_values_before_start_when_unsupported():
    """Test fallback to cached values when account query is unsupported."""

    class NoAccountQueryClient:
        """Client with no account query capability."""

        pass

    store = make_store(api=NoAccountQueryClient(), cash=321.0, value=654.0)

    assert store.is_connected is False
    assert store.get_balance() == {"cash": 321.0, "value": 654.0}
    assert store.get_cash() == pytest.approx(321.0)
    assert store.get_value() == pytest.approx(654.0)
    assert store.getcash() == pytest.approx(321.0)
    assert store.getvalue() == pytest.approx(654.0)
    assert store.is_connected is True


def test_store_open_order_queries_connect_on_demand_before_start_when_cache_is_not_fresh():
    """Test that open order queries connect on demand when cache is not fresh."""

    class TrackingClient(FakeBtApiClient):
        """Client that tracks connect() call count."""

        def __init__(self):
            """Initialize the tracking client."""
            super().__init__(open_orders=[{"id": "btapi-1", "symbol": DEFAULT_SYMBOL, "side": "buy"}])
            self.connect_calls = 0

        def connect(self):
            """Connect and increment counter."""
            self.connect_calls += 1
            return super().connect()

    client = TrackingClient()
    store = make_store(api=client)

    assert store.is_connected is False
    open_orders = store.fetch_open_orders()
    alias_orders = store.get_open_orders()
    compat_orders = store.getopenorders()
    assert [item["id"] for item in open_orders] == ["btapi-1"]
    assert [item["id"] for item in alias_orders] == ["btapi-1"]
    assert [item["id"] for item in compat_orders] == ["btapi-1"]
    assert store.is_connected is True
    assert client.connect_calls == 1


def test_store_open_order_queries_work_before_start_with_lightweight_client_without_connect_method():
    """Test that open order queries work with lightweight client without connect method."""

    class LightweightOpenOrdersClient:
        """Lightweight client with only fetch_open_orders method."""

        def fetch_open_orders(self):
            """Return mock open orders."""
            return [{"id": "btapi-1", "symbol": DEFAULT_SYMBOL, "side": "buy"}]

    store = make_store(api=LightweightOpenOrdersClient(), open_orders_cache_ttl=60.0)

    assert store.is_connected is False
    open_orders = store.fetch_open_orders()
    alias_orders = store.get_open_orders()
    compat_orders = store.getopenorders()
    assert [item["id"] for item in open_orders] == ["btapi-1"]
    assert [item["id"] for item in alias_orders] == ["btapi-1"]
    assert [item["id"] for item in compat_orders] == ["btapi-1"]
    assert store.is_connected is True

    open_orders[0]["id"] = "mutated"
    alias_orders[0]["id"] = "alias-mutated"

    assert store._open_orders_cache[0]["id"] == "btapi-1"
    assert store.fetch_open_orders()[0]["id"] == "btapi-1"


def test_store_open_order_queries_fall_back_to_get_open_orders_alias_before_start_without_connect_method():
    """Test fallback to get_open_orders alias when fetch_open_orders is unavailable."""

    class LightweightAliasOpenOrdersClient:
        """Lightweight client with only get_open_orders method."""

        def get_open_orders(self):
            """Return mock open orders."""
            return [{"id": "btapi-1", "symbol": DEFAULT_SYMBOL, "side": "buy"}]

    store = make_store(api=LightweightAliasOpenOrdersClient(), open_orders_cache_ttl=60.0)

    assert store.is_connected is False
    open_orders = store.fetch_open_orders()
    alias_orders = store.get_open_orders()
    compat_orders = store.getopenorders()
    assert [item["id"] for item in open_orders] == ["btapi-1"]
    assert [item["id"] for item in alias_orders] == ["btapi-1"]
    assert [item["id"] for item in compat_orders] == ["btapi-1"]
    assert store.is_connected is True

    open_orders[0]["id"] = "mutated"
    compat_orders[0]["id"] = "compat-mutated"

    assert store._open_orders_cache[0]["id"] == "btapi-1"
    assert store.fetch_open_orders()[0]["id"] == "btapi-1"


def test_store_open_order_queries_fall_back_to_empty_list_before_start_when_unsupported():
    """Test fallback to empty list when open order query is unsupported."""

    class NoOpenOrderClient(FakeBtApiClient):
        """Client that raises AttributeError on fetch_open_orders."""

        def __init__(self):
            """Initialize the no open order client."""
            super().__init__()
            self.connect_calls = 0

        def connect(self):
            """Connect and increment counter."""
            self.connect_calls += 1
            return super().connect()

        def fetch_open_orders(self):
            """Raise AttributeError to simulate unsupported."""
            raise AttributeError("unsupported")

    client = NoOpenOrderClient()
    store = make_store(api=client)

    assert store.is_connected is False
    assert store.fetch_open_orders() == []
    assert store.get_open_orders() == []
    assert store.getopenorders() == []
    assert store.is_connected is True
    assert client.connect_calls == 1


def test_store_position_queries_work_before_start_with_lightweight_client_without_connect_method():
    """Test that position queries work with lightweight client without connect method."""

    class LightweightPositionsClient:
        """Lightweight client with only get_positions method."""

        def get_positions(self):
            """Return mock positions data."""
            return [{"instrument": DEFAULT_SYMBOL, "volume": 2.0, "price": 99.5}]

    store = make_store(api=LightweightPositionsClient(), positions_cache_ttl=60.0)

    assert store.is_connected is False
    positions = store.get_positions()
    compat_positions = store.getpositions()
    assert positions[0]["instrument"] == DEFAULT_SYMBOL
    assert positions[0]["volume"] == pytest.approx(2.0)
    assert positions[0]["price"] == pytest.approx(99.5)
    assert compat_positions[0]["instrument"] == DEFAULT_SYMBOL
    assert compat_positions[0]["volume"] == pytest.approx(2.0)
    assert compat_positions[0]["price"] == pytest.approx(99.5)
    assert store.is_connected is True

    positions[0]["volume"] = 999
    compat_positions[0]["volume"] = 555

    assert store._positions_cache[0]["volume"] == pytest.approx(2.0)
    assert store.get_positions()[0]["volume"] == pytest.approx(2.0)


def test_store_position_queries_fall_back_to_empty_list_before_start_when_unsupported():
    """Test fallback to empty list when position query is unsupported."""

    class NoPositionsClient(FakeBtApiClient):
        """Client that fails position queries."""

        def __init__(self):
            """Initialize the no positions client."""
            super().__init__()
            self.connect_calls = 0

        def connect(self):
            """Connect and increment counter."""
            self.connect_calls += 1
            return super().connect()

        def get_positions(self):
            """Raise AttributeError to simulate unsupported."""
            raise AttributeError("unsupported")

    client = NoPositionsClient()
    store = make_store(api=client)

    assert store.is_connected is False
    assert store.get_positions() == []
    assert store.getpositions() == []
    assert store.is_connected is True
    assert client.connect_calls == 1


def test_store_query_results_do_not_expose_mutable_internal_caches():
    """Test that query results do not expose mutable internal caches."""
    client = FakeBtApiClient(
        positions=[{"instrument": DEFAULT_SYMBOL, "volume": 2, "price": 99.5}],
        open_orders=[{"id": "btapi-1", "symbol": DEFAULT_SYMBOL, "side": "buy", "price": 101.0}],
    )
    store = make_store(api=client, positions_cache_ttl=60.0, open_orders_cache_ttl=60.0)
    store.start()

    positions = store.get_positions()
    compat_positions = store.getpositions()
    open_orders = store.fetch_open_orders()
    alias_open_orders = store.get_open_orders()
    compat_open_orders = store.getopenorders()

    positions[0]["volume"] = 999
    compat_positions[0]["volume"] = 555
    open_orders[0]["id"] = "mutated"
    alias_open_orders[0]["id"] = "alias-mutated"
    compat_open_orders[0]["id"] = "compat-mutated"

    assert store.get_positions()[0]["volume"] == pytest.approx(2.0)
    assert store.getpositions()[0]["volume"] == pytest.approx(2.0)
    assert store.fetch_open_orders()[0]["id"] == "btapi-1"
    assert store.get_open_orders()[0]["id"] == "btapi-1"
    assert store.getopenorders()[0]["id"] == "btapi-1"


def test_store_fetch_history_results_do_not_expose_mutable_cache():
    """Test that fetch history results do not expose mutable cache."""
    client = FakeBtApiClient(
        history={DEFAULT_SYMBOL: [make_bar(0, 100.0, 101.0, 99.0, 100.5)]}
    )
    store = make_store(api=client)
    store.start()

    history = store.fetch_history(DEFAULT_SYMBOL)
    history[0]["close"] = 999.0

    assert store.fetch_history(DEFAULT_SYMBOL)[0]["close"] == pytest.approx(100.5)


def test_store_proxies_live_orderbook_polling():
    """Store should expose fake-client orderbook queues through the live polling helpers."""
    client = FakeBtApiClient(
        live_orderbooks={DEFAULT_SYMBOL: [make_orderbook(0, 100.0, 100.5)]}
    )
    store = make_store(api=client)

    store.start()

    assert store.supports_live_orderbook(DEFAULT_SYMBOL) is True
    assert store.has_pending_orderbook(DEFAULT_SYMBOL) is True

    orderbook = store.poll_orderbook(DEFAULT_SYMBOL)

    assert orderbook.best_bid == pytest.approx(100.0)
    assert orderbook.best_ask == pytest.approx(100.5)
    assert store.has_pending_orderbook(DEFAULT_SYMBOL) is False


def test_store_proxies_live_tick_polling():
    """Test that store proxies live tick polling."""
    client = FakeBtApiClient(
        live_ticks={DEFAULT_SYMBOL: [make_tick(0, 100.0)]}
    )
    store = make_store(api=client)

    store.start()

    assert store.supports_live_ticks(DEFAULT_SYMBOL) is True
    assert store.has_pending_tick(DEFAULT_SYMBOL) is True

    tick = store.poll_tick(DEFAULT_SYMBOL)

    assert tick.price == pytest.approx(100.0)
    assert store.has_pending_tick(DEFAULT_SYMBOL) is False


def test_store_live_bar_queries_fall_back_to_get_next_bar_alias():
    """Test fallback to get_next_bar alias when poll_live returns None."""

    class AliasOnlyLiveBarClient:
        """Client with only get_next_bar method for live bars."""

        def __init__(self):
            """Initialize the alias-only live bar client."""
            self.connected = False
            self._bar = make_bar(0, 100.0, 101.0, 99.0, 100.5)

        def connect(self):
            """Connect and set connected to True."""
            self.connected = True

        def disconnect(self):
            """Disconnect and set connected to False."""
            self.connected = False

        def get_next_bar(self, symbol):
            """Return the next bar and clear it."""
            bar, self._bar = self._bar, None
            return bar

    client = AliasOnlyLiveBarClient()
    store = make_store(api=client)
    store.start()

    live_bar = store.poll_live(DEFAULT_SYMBOL)

    assert live_bar["close"] == pytest.approx(100.5)
    assert store.poll_live(DEFAULT_SYMBOL) is None


def test_store_live_bar_queries_work_before_start_with_lightweight_get_next_bar_client_without_connect_method():
    """Test that live bar queries work with lightweight get_next_bar client."""

    class LightweightLiveBarClient:
        """Lightweight client with only get_next_bar method."""

        def __init__(self):
            """Initialize the lightweight live bar client."""
            self._bar = make_bar(0, 100.0, 101.0, 99.0, 100.5)

        def get_next_bar(self, symbol):
            """Return the next bar and clear it."""
            bar, self._bar = self._bar, None
            return bar

    store = make_store(api=LightweightLiveBarClient())

    assert store.is_connected is False

    live_bar = store.poll_live(DEFAULT_SYMBOL)

    assert live_bar["close"] == pytest.approx(100.5)
    assert store.poll_live(DEFAULT_SYMBOL) is None
    assert store.is_connected is True


def test_store_live_bar_queries_work_before_start_with_lightweight_poll_bar_client_without_connect_method():
    """Test that live bar queries work with lightweight poll_bar client without connect method."""

    class LightweightPollBarClient:
        """Lightweight client with only poll_bar method."""

        def __init__(self):
            """Initialize the lightweight poll bar client."""
            self._bar = make_bar(0, 100.0, 101.0, 99.0, 100.5)

        def poll_bar(self, symbol):
            """Return the next bar and clear it."""
            bar, self._bar = self._bar, None
            return bar

    store = make_store(api=LightweightPollBarClient())

    assert store.is_connected is False

    live_bar = store.poll_live(DEFAULT_SYMBOL)

    assert live_bar["close"] == pytest.approx(100.5)
    assert store.poll_live(DEFAULT_SYMBOL) is None
    assert store.is_connected is True


def test_store_history_queries_fall_back_to_fetch_ohlcv_alias():
    """Test fallback to fetch_ohlcv alias for history queries."""

    class AliasOnlyHistoryClient:
        """Client with only fetch_ohlcv method for history."""

        def __init__(self):
            """Initialize the alias-only history client."""
            self.connected = False

        def connect(self):
            """Connect and set connected to True."""
            self.connected = True

        def disconnect(self):
            """Disconnect and set connected to False."""
            self.connected = False

        def fetch_ohlcv(self, symbol, timeframe=None, compression=1, since=None, limit=None):
            """Return mock OHLCV data."""
            return [make_bar(0, 100.0, 101.0, 99.0, 100.5)]

    client = AliasOnlyHistoryClient()
    store = make_store(api=client)
    store.start()

    history = store.fetch_history(DEFAULT_SYMBOL)

    assert len(history) == 1
    assert history[0]["close"] == pytest.approx(100.5)


def test_store_history_queries_work_before_start_with_lightweight_fetch_ohlcv_client_without_connect_method():
    """Test that history queries work with lightweight fetch_ohlcv client without connect method."""

    class LightweightHistoryClient:
        """Lightweight client with only fetch_ohlcv method."""

        def fetch_ohlcv(self, symbol, timeframe=None, compression=1, since=None, limit=None):
            """Return mock OHLCV data."""
            return [make_bar(0, 100.0, 101.0, 99.0, 100.5)]

    store = make_store(api=LightweightHistoryClient())

    assert store.is_connected is False

    history = store.fetch_history(DEFAULT_SYMBOL)

    assert len(history) == 1
    assert history[0]["close"] == pytest.approx(100.5)
    assert store.is_connected is True

    history[0]["close"] = 999.0

    assert store._historical_bars[DEFAULT_SYMBOL][0]["close"] == pytest.approx(100.5)
    assert store.fetch_history(DEFAULT_SYMBOL)[0]["close"] == pytest.approx(100.5)


def test_store_history_cache_is_scoped_by_query_signature():
    """Test that history cache is scoped by query parameters (timeframe, compression, limit)."""

    class ParameterAwareHistoryClient:
        """Client that tracks fetch_bars calls and returns different bars based on timeframe."""

        def __init__(self):
            """Initialize the parameter-aware history client."""
            self.connected = False
            self.calls = []

        def connect(self):
            """Connect and set connected to True."""
            self.connected = True

        def disconnect(self):
            """Disconnect and set connected to False."""
            self.connected = False

        def fetch_bars(self, symbol, timeframe=None, compression=1, since=None, limit=None):
            """Return bars based on timeframe parameter."""
            self.calls.append((symbol, timeframe, compression, since, limit))
            if timeframe == "M5":
                return [make_bar(0, 105.0, 106.0, 104.0, 105.5)]
            return [make_bar(0, 100.0, 101.0, 99.0, 100.5)]

    client = ParameterAwareHistoryClient()
    store = make_store(api=client)
    store.start()

    minute_bars = store.fetch_history(DEFAULT_SYMBOL, timeframe="M1", compression=1, limit=1)
    five_minute_bars = store.fetch_history(DEFAULT_SYMBOL, timeframe="M5", compression=5, limit=1)
    cached_minute_bars = store.fetch_history(DEFAULT_SYMBOL, timeframe="M1", compression=1, limit=1)

    assert minute_bars[0]["close"] == pytest.approx(100.5)
    assert five_minute_bars[0]["close"] == pytest.approx(105.5)
    assert cached_minute_bars[0]["close"] == pytest.approx(100.5)
    assert client.calls == [
        (DEFAULT_SYMBOL, "M1", 1, None, 1),
        (DEFAULT_SYMBOL, "M5", 5, None, 1),
    ]


def test_store_live_tick_queries_fall_back_to_get_next_tick_alias():
    """Test fallback to get_next_tick alias when poll_tick returns None."""

    class AliasOnlyTickClient:
        """Client with only get_next_tick method for live ticks."""

        def __init__(self):
            """Initialize the alias-only tick client."""
            self.connected = False
            self._tick = make_tick(0, 100.0)

        def connect(self):
            """Connect and set connected to True."""
            self.connected = True

        def disconnect(self):
            """Disconnect and set connected to False."""
            self.connected = False

        def get_next_tick(self, symbol):
            """Return the next tick and clear it."""
            tick, self._tick = self._tick, None
            return tick

    client = AliasOnlyTickClient()
    store = make_store(api=client)
    store.start()

    tick = store.poll_tick(DEFAULT_SYMBOL)

    assert tick.price == pytest.approx(100.0)
    assert store.poll_tick(DEFAULT_SYMBOL) is None


def test_store_live_tick_queries_return_none_before_start_with_lightweight_get_next_tick_client_without_connect_method():
    """Test that tick queries return None before start with lightweight client without connect method."""

    class LightweightTickClient:
        """Lightweight client with only get_next_tick method."""

        def __init__(self):
            """Initialize the lightweight tick client."""
            self._tick = make_tick(0, 100.0)

        def get_next_tick(self, symbol):
            """Return the next tick and clear it."""
            tick, self._tick = self._tick, None
            return tick

    store = make_store(api=LightweightTickClient())

    assert store.is_connected is False

    assert store.poll_tick(DEFAULT_SYMBOL) is None
    assert store.is_connected is False


def test_store_live_orderbook_queries_fall_back_to_get_next_orderbook_alias():
    """Test fallback to get_next_orderbook alias for orderbook queries."""

    class AliasOnlyOrderbookClient:
        """Client with only get_next_orderbook method for orderbook."""

        def __init__(self):
            """Initialize the alias-only orderbook client."""
            self.connected = False
            self._orderbook = make_orderbook(0, 100.0, 100.5)

        def connect(self):
            """Connect and set connected to True."""
            self.connected = True

        def disconnect(self):
            """Disconnect and set connected to False."""
            self.connected = False

        def get_next_orderbook(self, symbol):
            """Return the next orderbook and clear it."""
            orderbook, self._orderbook = self._orderbook, None
            return orderbook

    client = AliasOnlyOrderbookClient()
    store = make_store(api=client)
    store.start()

    orderbook = store.poll_orderbook(DEFAULT_SYMBOL)

    assert orderbook.best_bid == pytest.approx(100.0)
    assert orderbook.best_ask == pytest.approx(100.5)
    assert store.poll_orderbook(DEFAULT_SYMBOL) is None


def test_store_live_orderbook_queries_return_none_before_start_with_lightweight_get_next_orderbook_client_without_connect_method():
    """Test that orderbook queries return None before start with lightweight client."""

    class LightweightOrderbookClient:
        """Lightweight client with only get_next_orderbook method."""

        def __init__(self):
            """Initialize the lightweight orderbook client."""
            self._orderbook = make_orderbook(0, 100.0, 100.5)

        def get_next_orderbook(self, symbol):
            """Return the next orderbook and clear it."""
            orderbook, self._orderbook = self._orderbook, None
            return orderbook

    store = make_store(api=LightweightOrderbookClient())

    assert store.is_connected is False
    assert store.poll_orderbook(DEFAULT_SYMBOL) is None
    assert store.is_connected is False


def test_store_supports_live_orderbook_falls_back_to_live_orderbooks_attribute():
    """Test fallback to live_orderbooks attribute when poll_orderbook is unavailable."""

    class AttributeOnlyOrderbookClient:
        """Client with only live_orderbooks attribute."""

        def __init__(self):
            """Initialize the attribute-only orderbook client."""
            self.connected = False
            self.live_orderbooks = {DEFAULT_SYMBOL: [make_orderbook(0, 100.0, 100.5)]}

        def connect(self):
            """Connect and set connected to True."""
            self.connected = True

        def disconnect(self):
            """Disconnect and set connected to False."""
            self.connected = False

    client = AttributeOnlyOrderbookClient()
    store = make_store(api=client)
    store.start()

    assert store.supports_live_orderbook(DEFAULT_SYMBOL) is True
    assert store.supports_live_orderbook("UNKNOWN") is False
    assert store.has_pending_orderbook(DEFAULT_SYMBOL) is True
    assert store.has_pending_orderbook("UNKNOWN") is False


@pytest.mark.parametrize(
    ("helper_name", "client_attr", "payload"),
    [
        ("supports_live_ticks", "live_ticks", {DEFAULT_SYMBOL: [make_tick(0, 100.0)]}),
        ("has_pending_tick", "live_ticks", {DEFAULT_SYMBOL: [make_tick(0, 100.0)]}),
        (
            "supports_live_orderbook",
            "live_orderbooks",
            {DEFAULT_SYMBOL: [make_orderbook(0, 100.0, 100.5)]},
        ),
        (
            "has_pending_orderbook",
            "live_orderbooks",
            {DEFAULT_SYMBOL: [make_orderbook(0, 100.0, 100.5)]},
        ),
    ],
)
def test_store_live_state_helpers_return_false_before_start_even_when_lightweight_client_exposes_live_attributes(
    helper_name, client_attr, payload
):
    """Test that live state helpers return False before start even when client exposes live attributes."""

    class AttributeOnlyLiveClient:
        """Client that only exposes live state attributes without connect method."""

        def __init__(self):
            """Initialize the attribute-only live client."""
            self.connected = False
            setattr(self, client_attr, payload)

    store = make_store(api=AttributeOnlyLiveClient())

    assert store.is_connected is False
    assert getattr(store, helper_name)(DEFAULT_SYMBOL) is False
    assert store.is_connected is False


def test_store_live_tick_state_falls_back_to_live_ticks_attribute():
    """Test fallback to live_ticks attribute when poll_tick is unavailable."""

    class AttributeOnlyTickClient:
        """Client with only live_ticks attribute."""

        def __init__(self):
            """Initialize the attribute-only tick client."""
            self.connected = False
            self.live_ticks = {DEFAULT_SYMBOL: [make_tick(0, 100.0)]}

        def connect(self):
            """Connect and set connected to True."""
            self.connected = True

        def disconnect(self):
            """Disconnect and set connected to False."""
            self.connected = False

    client = AttributeOnlyTickClient()
    store = make_store(api=client)
    store.start()

    assert store.supports_live_ticks(DEFAULT_SYMBOL) is True
    assert store.supports_live_ticks("UNKNOWN") is False
    assert store.has_pending_tick(DEFAULT_SYMBOL) is True
    assert store.has_pending_tick("UNKNOWN") is False


def test_store_subscription_is_idempotent_within_session_and_resets_after_stop():
    """Test that subscription is idempotent within session and resets after stop."""
    client = FakeBtApiClient()
    store = make_store(api=client)

    store.start()
    store.subscribe(DEFAULT_SYMBOL)
    store.subscribe(DEFAULT_SYMBOL)

    assert client.subscriptions == [DEFAULT_SYMBOL]


def test_store_subscribe_without_api_method_is_noop_and_does_not_mark_symbol_subscribed():
    """Test that subscribe is a noop when client has no subscribe method."""

    class NoSubscribeClient:
        """Client without subscribe capability."""

        def __init__(self):
            """Initialize the no-subscribe client."""
            self.connected = False

        def connect(self):
            """Connect and set connected to True."""
            self.connected = True

        def disconnect(self):
            """Disconnect and set connected to False."""
            self.connected = False

    store = make_store(api=NoSubscribeClient())

    store.start()
    store.subscribe(DEFAULT_SYMBOL)

    assert DEFAULT_SYMBOL not in store._subscribed_datanames
    event_types = [kwargs["event"]["event_type"] for _msg, _args, kwargs in store.get_notifications()]
    assert "market_data_subscribe_request" not in event_types


def test_store_subscribe_works_before_start_with_lightweight_client_without_connect_method():
    """Test that subscribe works before start with lightweight client without connect method."""

    class LightweightSubscribeClient:
        """Lightweight client with only subscribe method."""

        def __init__(self):
            """Initialize the lightweight subscribe client."""
            self.subscriptions = []

        def subscribe(self, dataname):
            """Subscribe to a dataname."""
            self.subscriptions.append(dataname)

    store = make_store(api=LightweightSubscribeClient())

    assert store.is_connected is False

    store.subscribe(DEFAULT_SYMBOL)
    store.subscribe(DEFAULT_SYMBOL)

    assert store.is_connected is True
    assert store._subscribed_datanames == {DEFAULT_SYMBOL}
    assert store._api.subscriptions == [DEFAULT_SYMBOL]
    event_types = [kwargs["event"]["event_type"] for _msg, _args, kwargs in store.get_notifications()]
    assert "market_data_subscribe_request" in event_types


def test_store_subscribe_before_start_is_noop_for_lightweight_client_without_connect_or_subscribe_method():
    """Test that subscribe is noop when client has neither connect nor subscribe method."""

    class NoSubscribeClient:
        """Client with no subscribe or connect capability."""

        pass

    store = make_store(api=NoSubscribeClient())

    assert store.is_connected is False

    store.subscribe(DEFAULT_SYMBOL)

    assert store.is_connected is True
    assert DEFAULT_SYMBOL not in store._subscribed_datanames
    event_types = [kwargs["event"]["event_type"] for _msg, _args, kwargs in store.get_notifications()]
    assert "market_data_subscribe_request" not in event_types


def test_store_subscribe_connects_on_demand_before_start():
    """Test that subscribe connects on demand before start."""

    class TrackingSubscribeClient:
        """Client that tracks connect calls and subscriptions."""

        def __init__(self):
            """Initialize the tracking subscribe client."""
            self.connected = False
            self.connect_calls = 0
            self.subscriptions = []

        def connect(self):
            """Connect and increment counter."""
            self.connect_calls += 1
            self.connected = True

        def disconnect(self):
            """Disconnect and set connected to False."""
            self.connected = False

        def subscribe(self, dataname):
            """Subscribe to a dataname."""
            self.subscriptions.append(dataname)

    client = TrackingSubscribeClient()
    store = make_store(api=client)

    assert store.is_connected is False

    store.subscribe(DEFAULT_SYMBOL)
    store.subscribe(DEFAULT_SYMBOL)

    assert store.is_connected is True
    assert client.connect_calls == 1
    assert client.subscriptions == [DEFAULT_SYMBOL]
    assert store._subscribed_datanames == {DEFAULT_SYMBOL}


def test_store_stop_before_start_is_silent_noop():
    """Test that stop before start is a silent noop."""

    class TrackingClient(FakeBtApiClient):
        """Client that tracks disconnect() call count."""

        def __init__(self):
            """Initialize the tracking client."""
            super().__init__()
            self.disconnect_calls = 0

        def disconnect(self):
            """Disconnect and increment counter."""
            self.disconnect_calls += 1
            return super().disconnect()

    client = TrackingClient()
    store = make_store(api=client)

    store.stop()

    assert client.disconnect_calls == 0
    assert store.get_notifications() == []


def test_store_deduplicates_subscriptions_within_session_but_resubscribes_after_restart():
    """Test that subscriptions are deduplicated within session but resubscribed after restart."""
    client = FakeBtApiClient()
    store = make_store(api=client)

    store.start()
    store.subscribe(DEFAULT_SYMBOL)
    store.subscribe(DEFAULT_SYMBOL)

    assert client.subscriptions == [DEFAULT_SYMBOL]

    store.stop()
    store.start()
    store.subscribe(DEFAULT_SYMBOL)

    assert client.subscriptions == [DEFAULT_SYMBOL, DEFAULT_SYMBOL]


def test_store_stop_is_idempotent_and_does_not_duplicate_disconnect_events():
    """Test that stop is idempotent and does not duplicate disconnect events."""
    client = FakeBtApiClient()
    store = make_store(api=client)

    store.start()
    store.stop()
    store.stop()

    event_types = [kwargs["event"]["event_type"] for _msg, _args, kwargs in store.get_notifications()]

    assert event_types.count("store_disconnect_requested") == 1
    assert event_types.count("store_disconnected") == 1


def test_store_stop_falls_back_to_api_stop_when_disconnect_is_unavailable():
    """Test fallback to stop() when disconnect() is unavailable."""

    class StopOnlyClient:
        """Client with only connect and stop methods (no disconnect)."""

        def __init__(self):
            """Initialize the stop-only client."""
            self.connected = False
            self.stop_calls = 0

        def connect(self):
            """Connect and set connected to True."""
            self.connected = True

        def stop(self):
            """Stop and increment counter."""
            self.stop_calls += 1
            self.connected = False

    client = StopOnlyClient()
    store = make_store(api=client)

    store.start()
    store.stop()

    assert client.stop_calls == 1
    assert store.is_connected is False


def test_store_start_falls_back_to_api_start_when_connect_is_unavailable():
    """Test fallback to start() when connect() is unavailable."""

    class StartOnlyClient:
        """Client with only start and stop methods (no connect/disconnect)."""

        def __init__(self):
            """Initialize the start-only client."""
            self.connected = False
            self.start_calls = 0

        def start(self):
            """Start and increment counter."""
            self.start_calls += 1
            self.connected = True

        def stop(self):
            """Stop and set connected to False."""
            self.connected = False

    client = StartOnlyClient()
    store = make_store(api=client)

    store.start()

    assert client.start_calls == 1
    assert store.is_connected is True


def test_store_start_marks_lightweight_client_ready_without_connect_or_start_methods():
    """Test that lightweight client is marked ready without connect/start methods."""

    class LightweightClient:
        """Lightweight client with only get_balance method."""

        def get_balance(self):
            """Return mock balance data."""
            return {"cash": 1000.0, "value": 1200.0}

    store = make_store(api=LightweightClient())

    store.start()

    assert store.is_connected is True
    event_types = [kwargs["event"]["event_type"] for _msg, _args, kwargs in store.get_notifications()]
    assert event_types[:3] == ["store_connecting", "store_connected", "store_ready"]


def test_store_autostart_connects_during_construction_and_emits_startup_events():
    """Test that autostart connects during construction and emits startup events."""

    class CountingClient(FakeBtApiClient):
        """Client that tracks connect() call count."""

        def __init__(self):
            """Initialize the counting client."""
            super().__init__()
            self.connect_calls = 0

        def connect(self):
            """Connect and increment counter."""
            self.connect_calls += 1
            return super().connect()

    client = CountingClient()
    store = make_store(api=client, autostart=True)

    assert client.connect_calls == 1
    assert store.is_connected is True
    event_types = [kwargs["event"]["event_type"] for _msg, _args, kwargs in store.get_notifications()]
    assert event_types[:3] == ["store_connecting", "store_connected", "store_ready"]


def test_store_start_is_idempotent_and_does_not_duplicate_connect_events():
    """Test that start is idempotent and does not duplicate connect events."""

    class CountingClient(FakeBtApiClient):
        """Client that tracks connect() call count."""

        def __init__(self):
            """Initialize the counting client."""
            super().__init__()
            self.connect_calls = 0

        def connect(self):
            """Connect and increment counter."""
            self.connect_calls += 1
            return super().connect()

    client = CountingClient()
    store = make_store(api=client)

    store.start()
    store.start()

    event_types = [kwargs["event"]["event_type"] for _msg, _args, kwargs in store.get_notifications()]

    assert client.connect_calls == 1
    assert event_types.count("store_connecting") == 1
    assert event_types.count("store_connected") == 1
    assert event_types.count("store_ready") == 1


def test_ctp_store_emits_auth_login_success_from_session_state():
    """CTP auth/login success events should use real session metadata."""

    class AuthenticatedCtpClient(FakeBtApiClient):
        def get_session_state(self):
            return {
                "auth_state": "authenticated",
                "login_state": "logged_in",
                "front_id": 7,
                "session_id": 8801,
                "trading_day": "20260618",
            }

    store = make_store(api=AuthenticatedCtpClient(), provider="ctp")

    store.start()

    runtime_events = [kwargs["event"] for _msg, _args, kwargs in store.get_notifications()]
    event_types = [event["event_type"] for event in runtime_events]
    assert "store_auth_request" in event_types
    assert "store_auth_success" in event_types
    assert "store_login_success" in event_types
    assert event_types.index("store_login_success") < event_types.index("store_ready")
    login_event = next(event for event in runtime_events if event["event_type"] == "store_login_success")
    assert login_event["details"]["front_id"] == 7
    assert login_event["details"]["session_id"] == 8801
    assert login_event["details"]["trading_day"] == "20260618"


def test_ctp_store_prefers_inner_trader_session_state_over_unknown_wrapper_state():
    """Wrapper-level unknown state should not hide inner CTP trader metadata."""

    class InnerTrader:
        def get_session_state(self):
            return {
                "connected": True,
                "ready": True,
                "auth_state": "authenticated",
                "login_state": "logged_in",
                "front_id": 8,
                "session_id": 8802,
                "trading_day": "20260619",
            }

    class WrapperCtpClient(FakeBtApiClient):
        def __init__(self):
            super().__init__()
            self.trader_client = InnerTrader()

        def get_session_state(self):
            return {
                "connected": True,
                "ready": False,
                "auth_state": "unknown",
                "login_state": "unknown",
            }

    store = make_store(api=WrapperCtpClient(), provider="ctp")

    store.start()

    runtime_events = [kwargs["event"] for _msg, _args, kwargs in store.get_notifications()]
    login_event = next(event for event in runtime_events if event["event_type"] == "store_login_success")

    assert login_event["details"]["front_id"] == 8
    assert login_event["details"]["session_id"] == 8802
    assert login_event["details"]["trading_day"] == "20260619"


def test_ctp_store_blocks_ready_when_authentication_failed():
    """CTP auth failure must not be reported as store_ready/auth_success."""

    class FailedAuthCtpClient(FakeBtApiClient):
        def get_session_state(self):
            return {
                "auth_state": "failed",
                "login_state": "blocked",
                "last_auth_error": {"error_id": 63, "error_msg": "auth failed"},
            }

    store = make_store(api=FailedAuthCtpClient(), provider="ctp")

    with pytest.raises(BtApiStoreError, match="CTP authentication failed"):
        store.start()

    runtime_events = [kwargs["event"] for _msg, _args, kwargs in store.get_notifications()]
    event_types = [event["event_type"] for event in runtime_events]
    assert "store_auth_request" in event_types
    assert "store_auth_failed" in event_types
    assert "store_auth_success" not in event_types
    assert "store_login_success" not in event_types
    assert "store_ready" not in event_types
    failed_event = next(event for event in runtime_events if event["event_type"] == "store_auth_failed")
    assert failed_event["error_code"] == "63"
    assert failed_event["error_msg"] == "auth failed"
    assert store.is_connected is False


def test_store_start_does_not_duplicate_same_data_feed_binding():
    """Test that start does not duplicate same data feed binding."""
    store = make_store(api=FakeBtApiClient())
    feed = store.getdata(dataname=DEFAULT_SYMBOL, backfill_start=False)

    store.start(data=feed)
    store.start(data=feed)

    assert store._data_feeds == [feed]


def test_store_register_does_not_duplicate_same_data_feed_binding():
    """Test that register does not duplicate same data feed binding."""
    store = make_store(api=FakeBtApiClient())
    feed = store.getdata(dataname=DEFAULT_SYMBOL, backfill_start=False)

    store.register(feed)
    store.register(feed)

    assert store._data_feeds == [feed]


def test_store_factory_helpers_return_unified_components(fake_client):
    """Store factory helpers should return the unified broker/feed implementations."""
    store = make_store(api=fake_client)

    assert isinstance(store.getbroker(), BtApiBroker)
    assert isinstance(store.getdata(dataname=DEFAULT_SYMBOL), BtApiFeed)


def test_store_factory_helpers_fall_back_to_default_classes_when_cls_attributes_are_none(fake_client):
    """Test that factory helpers fall back to default classes when cls attributes are None."""
    store = make_store(api=fake_client)
    store.BrokerCls = None
    store.DataCls = None

    broker = store.getbroker()
    data = store.getdata(dataname=DEFAULT_SYMBOL, backfill_start=False)

    assert isinstance(broker, BtApiBroker)
    assert broker.store is store
    assert isinstance(data, BtApiFeed)
    assert data.store is store
    assert data._store is store


def test_store_getdata_binds_store_provider_and_store_alias_for_custom_data_cls(fake_client):
    """Test that getdata binds store, provider, and store alias for custom data class."""

    class DummyFeed(BtApiFeed):
        """Dummy feed for testing."""

        pass

    store = make_store(api=fake_client, provider="btapi")
    data = store.getdata(dataname=DEFAULT_SYMBOL, data_cls=DummyFeed)

    assert isinstance(data, DummyFeed)
    assert data.store is store
    assert data._store is store
    assert data.provider == "btapi"


def test_store_getdata_preserves_explicit_store_and_provider_arguments(fake_client):
    """Test that getdata preserves explicit store and provider arguments."""
    outer_store = make_store(api=fake_client, provider="outer")
    explicit_store = object()

    data = outer_store.getdata(
        dataname=DEFAULT_SYMBOL,
        backfill_start=False,
        store=explicit_store,
        provider="explicit",
    )

    assert data.store is explicit_store
    assert data.provider == "explicit"
    assert data._store is outer_store


def test_store_getbroker_binds_store_and_provider_for_custom_broker_cls(fake_client):
    """Test that getbroker binds store and provider for custom broker class."""

    class DummyBroker(BtApiBroker):
        """Dummy broker for testing."""

        pass

    store = make_store(api=fake_client, provider="btapi")
    broker = store.getbroker(broker_cls=DummyBroker)

    assert isinstance(broker, DummyBroker)
    assert broker.store is store
    assert broker.p.provider == "btapi"
    assert store._broker is broker


def test_store_getbroker_updates_store_broker_reference_to_latest_instance(fake_client):
    """Test that getbroker updates store broker reference to latest instance."""
    store = make_store(api=fake_client)

    broker_a = store.getbroker()
    broker_b = store.getbroker()

    assert broker_a is not broker_b
    assert store._broker is broker_b


def test_store_start_binds_provided_broker_instance(fake_client):
    """Test that start binds provided broker instance."""
    store = make_store(api=fake_client)
    broker = BtApiBroker(store=store, provider=store.provider)

    store.start(broker=broker)

    assert store._broker is broker


def test_store_start_binds_data_and_broker_in_single_call(fake_client):
    """Test that start binds data and broker in single call."""
    store = make_store(api=fake_client)
    broker = BtApiBroker(store=store, provider=store.provider)
    data = store.getdata(dataname=DEFAULT_SYMBOL, backfill_start=False)

    store.start(data=data, broker=broker)

    assert store._broker is broker
    assert store._data_feeds == [data]


def test_store_repeated_start_with_data_and_new_broker_updates_broker_without_duplicating_feed(fake_client):
    """Test that repeated start with data and new broker updates broker without duplicating feed."""
    store = make_store(api=fake_client)
    broker_a = BtApiBroker(store=store, provider=store.provider)
    broker_b = BtApiBroker(store=store, provider=store.provider)
    data = store.getdata(dataname=DEFAULT_SYMBOL, backfill_start=False)

    store.start(data=data, broker=broker_a)
    store.start(data=data, broker=broker_b)

    assert store._broker is broker_b
    assert store._data_feeds == [data]


def test_store_submit_order_uses_create_order_alias_and_emits_runtime_events():
    """Test that submit_order uses create_order alias and emits runtime events."""

    class CreateOrderOnlyClient:
        """Client with only create_order method (no submit_order)."""

        def __init__(self):
            """Initialize the create-order-only client."""
            self.connected = False
            self.created_orders = []

        def connect(self):
            """Connect and set connected to True."""
            self.connected = True

        def disconnect(self):
            """Disconnect and set connected to False."""
            self.connected = False

        def create_order(self, **payload):
            """Create an order and track it."""
            self.created_orders.append(dict(payload))
            return {"id": "alias-1", "order_ref": "alias-ref-1"}

    class DummyOrder:
        """Dummy order for testing."""

        def __init__(self):
            """Initialize the dummy order."""
            self.ref = 7
            self.exectype = "limit"
            self.price = 101.0
            self.created = type("Created", (), {"price": 101.0})()
            self.data = type("Data", (), {"_name": DEFAULT_SYMBOL})()
            self.size = 2
            self.valid = None
            self.tradeid = 0
            self.pricelimit = None
            self.info = {}

        def getordername(self):
            """Return the order name."""
            return "Limit"

        def isbuy(self):
            """Return True for buy orders."""
            return True

    client = CreateOrderOnlyClient()
    store = make_store(api=client)

    response = store.submit_order(DummyOrder())

    assert response["id"] == "alias-1"
    assert store.is_connected is True
    assert client.created_orders[0]["symbol"] == DEFAULT_SYMBOL
    assert client.created_orders[0]["side"] == "buy"
    runtime_events = [kwargs["event"] for _msg, _args, kwargs in store.get_notifications()]
    assert any(event["event_type"] == "order_submit_request" for event in runtime_events)
    accepted = next(event for event in runtime_events if event["event_type"] == "order_submit_accepted")
    assert accepted["order_ref"] == "alias-1"
    assert accepted["status"] == "accepted"


def test_store_submit_order_raises_clear_error_and_emits_reject_event_when_unsupported():
    """Test that submit_order raises clear error when unsupported."""

    class NoSubmitClient:
        """Client with no submit_order capability."""

        def __init__(self):
            """Initialize the no-submit client."""
            self.connected = False

        def connect(self):
            """Connect and set connected to True."""
            self.connected = True

        def disconnect(self):
            """Disconnect and set connected to False."""
            self.connected = False

    class DummyOrder:
        """Dummy order for testing."""

        def __init__(self):
            """Initialize the dummy order."""
            self.ref = 7
            self.exectype = "limit"
            self.price = 101.0
            self.created = type("Created", (), {"price": 101.0})()
            self.data = type("Data", (), {"_name": DEFAULT_SYMBOL})()
            self.size = 2
            self.valid = None
            self.tradeid = 0
            self.pricelimit = None
            self.info = {}

        def getordername(self):
            """Return the order name."""
            return "Limit"

        def isbuy(self):
            """Return True for buy orders."""
            return True

    store = make_store(api=NoSubmitClient())

    with pytest.raises(BtApiStoreError, match="does not support order submission"):
        store.submit_order(DummyOrder())

    assert store.is_connected is True
    runtime_events = [kwargs["event"] for _msg, _args, kwargs in store.get_notifications()]
    assert any(event["event_type"] == "order_submit_request" for event in runtime_events)
    rejected = next(event for event in runtime_events if event["event_type"] == "order_reject_remote")
    assert rejected["order_ref"] == 7
    assert rejected["status"] == "rejected"


def test_store_submit_order_accepted_event_falls_back_to_local_order_ref_when_response_has_no_id():
    """Test that submit order accepted event falls back to local order ref when response has no id."""
    class OrderRefOnlyClient:
        """Client that returns only order_ref without id in create_order response."""

        def __init__(self):
            """Initialize the order-ref-only client."""
            self.connected = False
            self.created_orders = []

        def connect(self):
            """Connect and set connected to True."""
            self.connected = True

        def disconnect(self):
            """Disconnect and set connected to False."""
            self.connected = False

        def create_order(self, **payload):
            """Create an order and return only order_ref."""
            self.created_orders.append(dict(payload))
            return {"order_ref": "alias-ref-1"}

    class DummyOrder:
        """Dummy order for testing."""

        def __init__(self):
            """Initialize the dummy order."""
            self.ref = 7
            self.exectype = "limit"
            self.price = 101.0
            self.created = type("Created", (), {"price": 101.0})()
            self.data = type("Data", (), {"_name": DEFAULT_SYMBOL})()
            self.size = 2
            self.valid = None
            self.tradeid = 0
            self.pricelimit = None
            self.info = {}

        def getordername(self):
            """Return the order name."""
            return "Limit"

        def isbuy(self):
            """Return True for buy orders."""
            return True

    store = make_store(api=OrderRefOnlyClient())

    response = store.submit_order(DummyOrder())

    assert response["order_ref"] == "alias-ref-1"
    runtime_events = [kwargs["event"] for _msg, _args, kwargs in store.get_notifications()]
    accepted = next(event for event in runtime_events if event["event_type"] == "order_submit_accepted")
    assert accepted["order_ref"] == 7
    assert accepted["status"] == "accepted"


def test_store_cancel_order_uses_external_order_id_and_emits_runtime_events():
    """Test that cancel_order uses external order id and emits runtime events."""

    class CancelOrderClient:
        """Client that tracks cancel_order calls."""

        def __init__(self):
            """Initialize the cancel-order client."""
            self.connected = False
            self.cancelled_orders = []

        def connect(self):
            """Connect and set connected to True."""
            self.connected = True

        def disconnect(self):
            """Disconnect and set connected to False."""
            self.connected = False

        def cancel_order(self, order_ref, dataname=None):
            """Cancel an order and track it."""
            self.cancelled_orders.append({"order_ref": order_ref, "dataname": dataname})
            return True

    class DummyOrder:
        """Dummy order for testing."""

        def __init__(self):
            """Initialize the dummy order."""
            self.ref = 7
            self.info = type("Info", (), {"external_order_id": "alias-1"})()
            self.data = type("Data", (), {"_name": DEFAULT_SYMBOL})()

    client = CancelOrderClient()
    store = make_store(api=client)

    response = store.cancel_order(DummyOrder())

    assert response is True
    assert store.is_connected is True
    assert client.cancelled_orders == [{"order_ref": "alias-1", "dataname": DEFAULT_SYMBOL}]
    runtime_events = [kwargs["event"] for _msg, _args, kwargs in store.get_notifications()]
    assert any(event["event_type"] == "order_cancel_request" for event in runtime_events)
    submitted = next(event for event in runtime_events if event["event_type"] == "order_cancel_submitted")
    assert submitted["order_ref"] == "alias-1"
    assert submitted["status"] == "accepted"


def test_store_cancel_order_falls_back_to_ctp_order_ref_when_external_id_is_missing():
    """Test that cancel_order falls back to CTP order ref when external ID is missing."""

    class CancelOrderClient:
        """Client that tracks cancel_order calls."""

        def __init__(self):
            """Initialize the cancel-order client."""
            self.connected = False
            self.cancelled_orders = []

        def connect(self):
            """Connect and set connected to True."""
            self.connected = True

        def disconnect(self):
            """Disconnect and set connected to False."""
            self.connected = False

        def cancel_order(self, order_ref, dataname=None):
            """Cancel an order and track it."""
            self.cancelled_orders.append({"order_ref": order_ref, "dataname": dataname})
            return True

    class DummyOrder:
        """Dummy order for testing."""

        def __init__(self):
            """Initialize the dummy order."""
            self.ref = 7
            self.info = type("Info", (), {"ctp_order_ref": "ctp-ref-1"})()
            self.data = type("Data", (), {"_name": DEFAULT_SYMBOL})()

    client = CancelOrderClient()
    store = make_store(api=client)

    response = store.cancel_order(DummyOrder())

    assert response is True
    assert client.cancelled_orders == [{"order_ref": "ctp-ref-1", "dataname": DEFAULT_SYMBOL}]
    runtime_events = [kwargs["event"] for _msg, _args, kwargs in store.get_notifications()]
    submitted = next(event for event in runtime_events if event["event_type"] == "order_cancel_submitted")
    assert submitted["order_ref"] == "ctp-ref-1"


def test_store_cancel_order_raises_clear_error_and_emits_reject_event_when_unsupported():
    """Test that cancel_order raises clear error when unsupported."""

    class NoCancelClient:
        """Client with no cancel_order capability."""

        def __init__(self):
            """Initialize the no-cancel client."""
            self.connected = False

        def connect(self):
            """Connect and set connected to True."""
            self.connected = True

        def disconnect(self):
            """Disconnect and set connected to False."""
            self.connected = False

    class DummyOrder:
        """Dummy order for testing."""

        def __init__(self):
            """Initialize the dummy order."""
            self.ref = 7
            self.info = type("Info", (), {"external_order_id": "alias-1"})()
            self.data = type("Data", (), {"_name": DEFAULT_SYMBOL})()

    store = make_store(api=NoCancelClient())

    with pytest.raises(BtApiStoreError, match="does not support order cancellation"):
        store.cancel_order(DummyOrder())

    assert store.is_connected is True
    runtime_events = [kwargs["event"] for _msg, _args, kwargs in store.get_notifications()]
    assert any(event["event_type"] == "order_cancel_request" for event in runtime_events)
    rejected = next(event for event in runtime_events if event["event_type"] == "order_cancel_reject_remote")
    assert rejected["order_ref"] == "alias-1"
    assert rejected["status"] == "rejected"


def test_store_account_and_positions_queries_honor_ttl_cache():
    """Test that account and position queries honor TTL cache."""

    class CountingClient(FakeBtApiClient):
        """Client that tracks balance and position call counts."""

        def __init__(self):
            """Initialize the counting client."""
            super().__init__(
                balance={"cash": 1000.0, "value": 1200.0},
                positions=[{"instrument": DEFAULT_SYMBOL, "volume": 2, "price": 99.5}],
            )
            self.balance_calls = 0
            self.position_calls = 0

        def get_balance(self):
            """Get balance and increment counter."""
            self.balance_calls += 1
            return super().get_balance()

        def get_positions(self):
            """Get positions and increment counter."""
            self.position_calls += 1
            return super().get_positions()

    client = CountingClient()
    store = make_store(api=client, account_cache_ttl=60.0, positions_cache_ttl=60.0)
    store.start()

    assert store.get_balance()["cash"] == pytest.approx(1000.0)
    assert store.get_balance()["cash"] == pytest.approx(1000.0)
    assert store.get_positions()[0]["volume"] == pytest.approx(2.0)
    assert store.get_positions()[0]["volume"] == pytest.approx(2.0)
    assert client.balance_calls == 1
    assert client.position_calls == 1


def test_store_query_failures_fall_back_to_last_successful_cache():
    """Test that query failures fall back to last successful cache."""

    class FlakyClient(FakeBtApiClient):
        """Client that can be toggled to fail balance/position queries."""

        def __init__(self):
            """Initialize the flaky client."""
            super().__init__(
                balance={"cash": 800.0, "value": 900.0},
                positions=[{"instrument": DEFAULT_SYMBOL, "volume": 1, "price": 100.0}],
            )
            self.fail = False

        def get_balance(self):
            """Get balance or raise error if fail is True."""
            if self.fail:
                raise RuntimeError("temporary balance failure")
            return super().get_balance()

        def get_positions(self):
            """Get positions or raise error if fail is True."""
            if self.fail:
                raise RuntimeError("temporary positions failure")
            return super().get_positions()

    client = FlakyClient()
    store = make_store(api=client)
    store.start()

    assert store.get_balance()["cash"] == pytest.approx(800.0)
    assert store.get_positions()[0]["volume"] == pytest.approx(1.0)

    client.fail = True

    assert store.get_balance()["cash"] == pytest.approx(800.0)
    assert store.get_balance()["value"] == pytest.approx(900.0)
    assert store.get_positions()[0]["volume"] == pytest.approx(1.0)
    assert store.get_positions()[0]["price"] == pytest.approx(100.0)


def test_store_balance_queries_fall_back_to_get_account_alias():
    """Test fallback to get_account alias for balance queries."""

    class AccountOnlyClient:
        """Client with only get_account method for account queries."""

        def __init__(self):
            """Initialize the account-only client."""
            self.connected = False

        def connect(self):
            """Connect and set connected to True."""
            self.connected = True

        def disconnect(self):
            """Disconnect and set connected to False."""
            self.connected = False

        def get_account(self):
            """Return mock account data."""
            return {"cash": 1234.0, "value": 1500.0}

    client = AccountOnlyClient()
    store = make_store(api=client)
    store.start()

    assert store.get_balance()["cash"] == pytest.approx(1234.0)
    assert store.get_balance()["value"] == pytest.approx(1500.0)
    assert store.get_cash() == pytest.approx(1234.0)
    assert store.get_value() == pytest.approx(1500.0)
    assert store.getcash() == pytest.approx(1234.0)
    assert store.getvalue() == pytest.approx(1500.0)
    assert store.getvalue(datas=[object()]) == pytest.approx(1500.0)


def test_store_open_order_queries_fall_back_to_get_open_orders_alias():
    """Test fallback to get_open_orders alias for open order queries."""

    class AliasOnlyOpenOrdersClient:
        """Client with only get_open_orders method for open order queries."""

        def __init__(self):
            """Initialize the alias-only open orders client."""
            self.connected = False

        def connect(self):
            """Connect and set connected to True."""
            self.connected = True

        def disconnect(self):
            """Disconnect and set connected to False."""
            self.connected = False

        def get_open_orders(self):
            """Return mock open orders."""
            return [{"id": "btapi-1", "symbol": DEFAULT_SYMBOL, "side": "buy"}]

    client = AliasOnlyOpenOrdersClient()
    store = make_store(api=client)
    store.start()

    assert [item["id"] for item in store.fetch_open_orders()] == ["btapi-1"]
    assert [item["id"] for item in store.get_open_orders()] == ["btapi-1"]
    assert [item["id"] for item in store.getopenorders()] == ["btapi-1"]


def test_store_open_order_queries_honor_ttl_cache():
    """Test that open order queries honor TTL cache."""

    class CountingClient(FakeBtApiClient):
        """Client that tracks open order call counts."""

        def __init__(self):
            """Initialize the counting client."""
            super().__init__(open_orders=[{"id": "btapi-1", "symbol": DEFAULT_SYMBOL, "side": "buy"}])
            self.open_order_calls = 0

        def fetch_open_orders(self):
            """Fetch open orders and increment counter."""
            self.open_order_calls += 1
            return super().fetch_open_orders()

    client = CountingClient()
    store = make_store(api=client, open_orders_cache_ttl=60.0)
    store.start()

    assert [item["id"] for item in store.fetch_open_orders()] == ["btapi-1"]
    client.open_orders = [{"id": "btapi-2", "symbol": DEFAULT_SYMBOL, "side": "sell"}]
    assert [item["id"] for item in store.fetch_open_orders()] == ["btapi-1"]
    assert client.open_order_calls == 1


def test_store_open_order_queries_fall_back_to_last_successful_cache_on_failure():
    """Test fallback to last successful cache when open order query fails."""

    class FlakyOpenOrdersClient(FakeBtApiClient):
        """Client that can be toggled to fail open order queries."""

        def __init__(self):
            """Initialize the flaky open orders client."""
            super().__init__(open_orders=[{"id": "btapi-1", "symbol": DEFAULT_SYMBOL, "side": "buy"}])
            self.fail = False

        def fetch_open_orders(self):
            """Fetch open orders or raise error if fail is True."""
            if self.fail:
                raise RuntimeError("temporary open order failure")
            return super().fetch_open_orders()

    client = FlakyOpenOrdersClient()
    store = make_store(api=client)
    store.start()

    assert [item["id"] for item in store.fetch_open_orders()] == ["btapi-1"]

    client.fail = True

    assert [item["id"] for item in store.fetch_open_orders()] == ["btapi-1"]


def test_store_open_order_queries_fall_back_to_empty_list_when_unsupported():
    """Test fallback to empty list when open order query is unsupported."""

    class NoOpenOrderClient(FakeBtApiClient):
        """Client that raises AttributeError on fetch_open_orders."""

        def fetch_open_orders(self):
            """Raise AttributeError to simulate unsupported."""
            raise AttributeError("unsupported")

    client = NoOpenOrderClient()
    store = make_store(api=client)
    store.start()

    assert store.fetch_open_orders() == []
    assert store.get_open_orders() == []
    assert store.getopenorders() == []


def test_ctp_provider_switches_to_gateway_from_env(monkeypatch):
    """Test that CTP provider switches to gateway from env."""
    monkeypatch.setenv("BT_STORE_PROVIDER", "ctp_gateway")
    monkeypatch.setenv("BT_GATEWAY_COMMAND_ENDPOINT", "ipc://command")
    monkeypatch.setenv("BT_GATEWAY_EVENT_ENDPOINT", "ipc://event")
    monkeypatch.setenv("BT_GATEWAY_MARKET_ENDPOINT", "ipc://market")
    monkeypatch.setenv("BT_GATEWAY_ACCOUNT_ID", "acc-1")
    monkeypatch.setenv("BT_GATEWAY_EXCHANGE_TYPE", "CTP")
    monkeypatch.setenv("BT_GATEWAY_ASSET_TYPE", "FUTURE")
    monkeypatch.setenv("BT_GATEWAY_START_LOCAL_RUNTIME", "0")

    store = BtApiStore(provider="ctp")

    assert store.provider == "ctp_gateway"
    assert store._api_kwargs["gateway_command_endpoint"] == "ipc://command"
    assert store._api_kwargs["gateway_event_endpoint"] == "ipc://event"
    assert store._api_kwargs["gateway_market_endpoint"] == "ipc://market"
    assert store._api_kwargs["account_id"] == "acc-1"
    assert store._api_kwargs["exchange_type"] == "CTP"
    assert store._api_kwargs["asset_type"] == "FUTURE"
    assert store._api_kwargs["gateway_start_local_runtime"] is False


def test_create_ctp_wrapper_patches_missing_spi_callbacks():
    """Test that create CTP wrapper patches missing SPI callbacks."""
    # Optional live-trading dependency: skip when bt_api_py CTP support is absent
    # (e.g. CI images without the proprietary package) instead of erroring.
    pytest.importorskip("bt_api_ctp.ctp.client")
    _create_ctp_wrapper_class()

    import bt_api_ctp.ctp.client as ctp_client_module

    assert hasattr(ctp_client_module._MdSpi, "OnRspQryInvestorPositionDetail")
    assert hasattr(ctp_client_module._MdSpi, "OnRspQryNotice")
    assert hasattr(ctp_client_module._TraderSpi, "OnRspQryInvestorPositionDetail")
    assert hasattr(ctp_client_module._TraderSpi, "OnRspQryNotice")


def test_ctp_wrapper_accepts_dict_snapshots_from_trader_client():
    """CTP query callbacks return dict snapshots; wrapper must read them directly."""
    pytest.importorskip("bt_api_ctp.ctp.client")
    wrapper_cls = _create_ctp_wrapper_class()

    class FakeTraderClient:
        is_ready = True

        def query_account(self, timeout=5):
            return {"Available": 80000.0, "Balance": 100000.0}

        def query_positions(self, timeout=5):
            return [
                {
                    "InstrumentID": "IF2506",
                    "PosiDirection": "2",
                    "Position": 2,
                    "PositionCost": 7000.0,
                }
            ]

    client = wrapper_cls(
        md_address="tcp://md",
        td_address="tcp://td",
        broker_id="9999",
        investor_id="demo",
        password="secret",
    )
    client.trader_client = FakeTraderClient()

    assert client.get_balance() == {"cash": 80000.0, "value": 100000.0}
    assert client.get_positions() == [
        {
            "instrument": "IF2506",
            "direction": "long",
            "volume": 2.0,
            "price": 3500.0,
        }
    ]


def test_ctp_wrapper_polls_order_insert_error_events_with_order_ref():
    """CTP order-insert errors must retain OrderRef for broker reconciliation."""
    pytest.importorskip("bt_api_ctp.ctp.client")
    wrapper_cls = _create_ctp_wrapper_class()

    class FakeTraderClient:
        is_ready = True

        def __init__(self):
            self._events = [
                {
                    "event": "order_insert_error",
                    "error_id": 31,
                    "error_msg": "资金不足",
                    "field": {
                        "OrderRef": "bt-7",
                        "InstrumentID": "rb2610",
                        "ExchangeID": "SHFE",
                    },
                }
            ]

        def wait_error_event(self, timeout=0):
            return self._events.pop(0) if self._events else None

    client = wrapper_cls(
        md_address="tcp://md",
        td_address="tcp://td",
        broker_id="9999",
        investor_id="demo",
        password="secret",
    )
    client.trader_client = FakeTraderClient()

    update = client.poll_broker_update()

    assert update["kind"] == "error"
    assert update["order_ref"] == "bt-7"
    assert update["data_name"] == "rb2610"
    assert update["error_code"] == 31
    assert update["error_msg"] == "资金不足"
    assert update["details"]["ErrorID"] == 31
    assert update["details"]["ErrorMsg"] == "资金不足"


def test_ctp_provider_switches_to_generic_gateway_from_env(monkeypatch):
    """Test that CTP provider switches to generic gateway from env."""
    monkeypatch.setenv("BT_STORE_PROVIDER", "gateway")
    monkeypatch.setenv("BT_GATEWAY_COMMAND_ENDPOINT", "ipc://command")
    monkeypatch.setenv("BT_GATEWAY_EVENT_ENDPOINT", "ipc://event")
    monkeypatch.setenv("BT_GATEWAY_MARKET_ENDPOINT", "ipc://market")
    monkeypatch.setenv("BT_GATEWAY_ACCOUNT_ID", "du123456")
    monkeypatch.setenv("BT_GATEWAY_EXCHANGE_TYPE", "IB_WEB")
    monkeypatch.setenv("BT_GATEWAY_ASSET_TYPE", "STK")
    monkeypatch.setenv("BT_GATEWAY_START_LOCAL_RUNTIME", "0")

    store = BtApiStore(provider="ctp")

    assert store.provider == "gateway"
    assert store._api_kwargs["gateway_command_endpoint"] == "ipc://command"
    assert store._api_kwargs["gateway_event_endpoint"] == "ipc://event"
    assert store._api_kwargs["gateway_market_endpoint"] == "ipc://market"
    assert store._api_kwargs["account_id"] == "du123456"
    assert store._api_kwargs["exchange_type"] == "IB_WEB"
    assert store._api_kwargs["asset_type"] == "STK"
    assert store._api_kwargs["gateway_start_local_runtime"] is False


def test_explicit_ib_web_gateway_provider_reads_gateway_env(monkeypatch):
    """Test that explicit IB web gateway provider reads gateway env."""
    monkeypatch.setenv("BT_GATEWAY_COMMAND_ENDPOINT", "ipc://command")
    monkeypatch.setenv("BT_GATEWAY_EVENT_ENDPOINT", "ipc://event")
    monkeypatch.setenv("BT_GATEWAY_MARKET_ENDPOINT", "ipc://market")
    monkeypatch.setenv("BT_GATEWAY_ACCOUNT_ID", "du654321")
    monkeypatch.setenv("BT_GATEWAY_EXCHANGE_TYPE", "IB_WEB")
    monkeypatch.setenv("BT_GATEWAY_ASSET_TYPE", "FUT")
    monkeypatch.setenv("BT_GATEWAY_START_LOCAL_RUNTIME", "1")

    store = BtApiStore(provider="ib_web_gateway")

    assert store.provider == "ib_web_gateway"
    assert store._api_kwargs["gateway_command_endpoint"] == "ipc://command"
    assert store._api_kwargs["gateway_event_endpoint"] == "ipc://event"
    assert store._api_kwargs["gateway_market_endpoint"] == "ipc://market"
    assert store._api_kwargs["account_id"] == "du654321"
    assert store._api_kwargs["exchange_type"] == "IB_WEB"
    assert store._api_kwargs["asset_type"] == "FUT"
    assert store._api_kwargs["gateway_start_local_runtime"] is True


def test_mt5_gateway_provider_is_recognized(monkeypatch):
    """mt5_gateway should be treated as a gateway provider."""
    monkeypatch.setenv("BT_STORE_PROVIDER", "mt5_gateway")
    monkeypatch.setenv("BT_GATEWAY_COMMAND_ENDPOINT", "tcp://127.0.0.1:33000")
    monkeypatch.setenv("BT_GATEWAY_EVENT_ENDPOINT", "tcp://127.0.0.1:33001")
    monkeypatch.setenv("BT_GATEWAY_MARKET_ENDPOINT", "tcp://127.0.0.1:33002")
    monkeypatch.setenv("BT_GATEWAY_ACCOUNT_ID", "mt5-12345678")
    monkeypatch.setenv("BT_GATEWAY_EXCHANGE_TYPE", "MT5")
    monkeypatch.setenv("BT_GATEWAY_ASSET_TYPE", "OTC")
    monkeypatch.setenv("BT_GATEWAY_START_LOCAL_RUNTIME", "0")

    store = BtApiStore(provider="ctp")

    assert store.provider == "mt5_gateway"
    assert store._api_kwargs["exchange_type"] == "MT5"
    assert store._api_kwargs["asset_type"] == "OTC"
    assert store._api_kwargs["account_id"] == "mt5-12345678"


def test_gateway_wrapper_fetch_bars_proxies(fake_client):
    """Gateway wrapper fetch_bars should normalize and return bars from the injected API."""
    client = FakeBtApiClient(
        history={DEFAULT_SYMBOL: [
            make_bar(0, 1.1000, 1.1010, 1.0990, 1.1005),
            make_bar(1, 1.1005, 1.1020, 1.1000, 1.1015),
        ]},
    )
    store = make_store(api=client)
    store.start()
    bars = store.fetch_history(DEFAULT_SYMBOL, timeframe="M1", limit=200)
    assert len(bars) == 2
    assert bars[0]["close"] == pytest.approx(1.1005)
    store.stop()


def test_split_ctp_symbol_normalizes_czce_with_exchange():
    """Test that split CTP symbol normalizes CZCE with exchange."""
    assert _split_ctp_symbol("CF2609.CZCE") == ("CF609", "CZCE")


def test_split_ctp_symbol_normalizes_known_czce_prefix_without_exchange():
    """Test that split CTP symbol normalizes known CZCE prefix without exchange."""
    assert _split_ctp_symbol("MA2609") == ("MA609", "")


def test_split_ctp_symbol_does_not_change_cffex_style_symbol_without_exchange():
    """Test that split CTP symbol does not change CFFEX style symbol without exchange."""
    assert _split_ctp_symbol("IF2609") == ("IF2609", "")


@pytest.mark.parametrize("provider", ["futu", "oanda", "vc"])
def test_placeholder_provider_raises(provider):
    """Providers not yet implemented in bt_api_py should fail explicitly."""
    store = BtApiStore(provider=provider)

    with pytest.raises(BtApiProviderNotImplementedError):
        store.start()


def test_missing_dependency_raises_without_api(monkeypatch):
    """Starting without bt_api_py installed should raise a clear dependency error."""
    store = BtApiStore(provider="okx")

    def _raise_import_error(_name):
        raise ImportError("bt_api_py not installed")

    monkeypatch.setattr("backtrader.stores.btapistore.importlib.import_module", _raise_import_error)

    with pytest.raises(BtApiMissingDependencyError):
        store.start()
