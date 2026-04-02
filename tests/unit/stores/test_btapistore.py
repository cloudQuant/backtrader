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
    class TrackingClient(FakeBtApiClient):
        def __init__(self):
            super().__init__()
            self.connect_calls = 0

        def connect(self):
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
    store = make_store(api=fake_client)

    store.start()

    assert store.getcash() == pytest.approx(store.get_cash())
    assert store.getvalue() == pytest.approx(store.get_value())
    assert store.getpositions() == store.get_positions()


def test_store_seeded_account_queries_return_cached_values_before_start():
    class TrackingClient(FakeBtApiClient):
        def __init__(self):
            super().__init__()
            self.connect_calls = 0

        def connect(self):
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
    class FailingBalanceClient(FakeBtApiClient):
        def __init__(self):
            super().__init__()
            self.connect_calls = 0

        def connect(self):
            self.connect_calls += 1
            return super().connect()

        def get_balance(self):
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
    class FailingAccountAliasClient:
        def __init__(self):
            self.connected = False
            self.connect_calls = 0

        def connect(self):
            self.connect_calls += 1
            self.connected = True

        def disconnect(self):
            self.connected = False

        def get_account(self):
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
    class TrackingClient(FakeBtApiClient):
        def __init__(self):
            super().__init__()
            self.connect_calls = 0

        def connect(self):
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
    class FailingPositionsClient(FakeBtApiClient):
        def __init__(self):
            super().__init__()
            self.connect_calls = 0

        def connect(self):
            self.connect_calls += 1
            return super().connect()

        def get_positions(self):
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
    class TrackingClient(FakeBtApiClient):
        def __init__(self):
            super().__init__()
            self.connect_calls = 0

        def connect(self):
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
    class FailingOpenOrdersClient(FakeBtApiClient):
        def __init__(self):
            super().__init__()
            self.connect_calls = 0

        def connect(self):
            self.connect_calls += 1
            return super().connect()

        def fetch_open_orders(self):
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
    class TrackingClient(FakeBtApiClient):
        def __init__(self):
            super().__init__()
            self.connect_calls = 0

        def connect(self):
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
    class LightweightBalanceClient:
        def get_balance(self):
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
    class AccountOnlyClient:
        def __init__(self):
            self.connected = False
            self.connect_calls = 0

        def connect(self):
            self.connect_calls += 1
            self.connected = True

        def disconnect(self):
            self.connected = False

        def get_account(self):
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
    class LightweightAccountOnlyClient:
        def get_account(self):
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
    class NoAccountQueryClient:
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
    class TrackingClient(FakeBtApiClient):
        def __init__(self):
            super().__init__(open_orders=[{"id": "btapi-1", "symbol": DEFAULT_SYMBOL, "side": "buy"}])
            self.connect_calls = 0

        def connect(self):
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
    class LightweightOpenOrdersClient:
        def fetch_open_orders(self):
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
    class LightweightAliasOpenOrdersClient:
        def get_open_orders(self):
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
    class NoOpenOrderClient(FakeBtApiClient):
        def __init__(self):
            super().__init__()
            self.connect_calls = 0

        def connect(self):
            self.connect_calls += 1
            return super().connect()

        def fetch_open_orders(self):
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
    class LightweightPositionsClient:
        def get_positions(self):
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
    class NoPositionsClient(FakeBtApiClient):
        def __init__(self):
            super().__init__()
            self.connect_calls = 0

        def connect(self):
            self.connect_calls += 1
            return super().connect()

        def get_positions(self):
            raise AttributeError("unsupported")

    client = NoPositionsClient()
    store = make_store(api=client)

    assert store.is_connected is False
    assert store.get_positions() == []
    assert store.getpositions() == []
    assert store.is_connected is True
    assert client.connect_calls == 1


def test_store_query_results_do_not_expose_mutable_internal_caches():
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
    class AliasOnlyLiveBarClient:
        def __init__(self):
            self.connected = False
            self._bar = make_bar(0, 100.0, 101.0, 99.0, 100.5)

        def connect(self):
            self.connected = True

        def disconnect(self):
            self.connected = False

        def get_next_bar(self, symbol):
            bar, self._bar = self._bar, None
            return bar

    client = AliasOnlyLiveBarClient()
    store = make_store(api=client)
    store.start()

    live_bar = store.poll_live(DEFAULT_SYMBOL)

    assert live_bar["close"] == pytest.approx(100.5)
    assert store.poll_live(DEFAULT_SYMBOL) is None


def test_store_live_bar_queries_work_before_start_with_lightweight_get_next_bar_client_without_connect_method():
    class LightweightLiveBarClient:
        def __init__(self):
            self._bar = make_bar(0, 100.0, 101.0, 99.0, 100.5)

        def get_next_bar(self, symbol):
            bar, self._bar = self._bar, None
            return bar

    store = make_store(api=LightweightLiveBarClient())

    assert store.is_connected is False

    live_bar = store.poll_live(DEFAULT_SYMBOL)

    assert live_bar["close"] == pytest.approx(100.5)
    assert store.poll_live(DEFAULT_SYMBOL) is None
    assert store.is_connected is True


def test_store_live_bar_queries_work_before_start_with_lightweight_poll_bar_client_without_connect_method():
    class LightweightPollBarClient:
        def __init__(self):
            self._bar = make_bar(0, 100.0, 101.0, 99.0, 100.5)

        def poll_bar(self, symbol):
            bar, self._bar = self._bar, None
            return bar

    store = make_store(api=LightweightPollBarClient())

    assert store.is_connected is False

    live_bar = store.poll_live(DEFAULT_SYMBOL)

    assert live_bar["close"] == pytest.approx(100.5)
    assert store.poll_live(DEFAULT_SYMBOL) is None
    assert store.is_connected is True


def test_store_history_queries_fall_back_to_fetch_ohlcv_alias():
    class AliasOnlyHistoryClient:
        def __init__(self):
            self.connected = False

        def connect(self):
            self.connected = True

        def disconnect(self):
            self.connected = False

        def fetch_ohlcv(self, symbol, timeframe=None, compression=1, since=None, limit=None):
            return [make_bar(0, 100.0, 101.0, 99.0, 100.5)]

    client = AliasOnlyHistoryClient()
    store = make_store(api=client)
    store.start()

    history = store.fetch_history(DEFAULT_SYMBOL)

    assert len(history) == 1
    assert history[0]["close"] == pytest.approx(100.5)


def test_store_history_queries_work_before_start_with_lightweight_fetch_ohlcv_client_without_connect_method():
    class LightweightHistoryClient:
        def fetch_ohlcv(self, symbol, timeframe=None, compression=1, since=None, limit=None):
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
    class ParameterAwareHistoryClient:
        def __init__(self):
            self.connected = False
            self.calls = []

        def connect(self):
            self.connected = True

        def disconnect(self):
            self.connected = False

        def fetch_bars(self, symbol, timeframe=None, compression=1, since=None, limit=None):
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
    class AliasOnlyTickClient:
        def __init__(self):
            self.connected = False
            self._tick = make_tick(0, 100.0)

        def connect(self):
            self.connected = True

        def disconnect(self):
            self.connected = False

        def get_next_tick(self, symbol):
            tick, self._tick = self._tick, None
            return tick

    client = AliasOnlyTickClient()
    store = make_store(api=client)
    store.start()

    tick = store.poll_tick(DEFAULT_SYMBOL)

    assert tick.price == pytest.approx(100.0)
    assert store.poll_tick(DEFAULT_SYMBOL) is None


def test_store_live_tick_queries_return_none_before_start_with_lightweight_get_next_tick_client_without_connect_method():
    class LightweightTickClient:
        def __init__(self):
            self._tick = make_tick(0, 100.0)

        def get_next_tick(self, symbol):
            tick, self._tick = self._tick, None
            return tick

    store = make_store(api=LightweightTickClient())

    assert store.is_connected is False

    assert store.poll_tick(DEFAULT_SYMBOL) is None
    assert store.is_connected is False


def test_store_live_orderbook_queries_fall_back_to_get_next_orderbook_alias():
    class AliasOnlyOrderbookClient:
        def __init__(self):
            self.connected = False
            self._orderbook = make_orderbook(0, 100.0, 100.5)

        def connect(self):
            self.connected = True

        def disconnect(self):
            self.connected = False

        def get_next_orderbook(self, symbol):
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
    class LightweightOrderbookClient:
        def __init__(self):
            self._orderbook = make_orderbook(0, 100.0, 100.5)

        def get_next_orderbook(self, symbol):
            orderbook, self._orderbook = self._orderbook, None
            return orderbook

    store = make_store(api=LightweightOrderbookClient())

    assert store.is_connected is False
    assert store.poll_orderbook(DEFAULT_SYMBOL) is None
    assert store.is_connected is False


def test_store_supports_live_orderbook_falls_back_to_live_orderbooks_attribute():
    class AttributeOnlyOrderbookClient:
        def __init__(self):
            self.connected = False
            self.live_orderbooks = {DEFAULT_SYMBOL: [make_orderbook(0, 100.0, 100.5)]}

        def connect(self):
            self.connected = True

        def disconnect(self):
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
    class AttributeOnlyLiveClient:
        def __init__(self):
            self.connected = False
            setattr(self, client_attr, payload)

    store = make_store(api=AttributeOnlyLiveClient())

    assert store.is_connected is False
    assert getattr(store, helper_name)(DEFAULT_SYMBOL) is False
    assert store.is_connected is False


def test_store_live_tick_state_falls_back_to_live_ticks_attribute():
    class AttributeOnlyTickClient:
        def __init__(self):
            self.connected = False
            self.live_ticks = {DEFAULT_SYMBOL: [make_tick(0, 100.0)]}

        def connect(self):
            self.connected = True

        def disconnect(self):
            self.connected = False

    client = AttributeOnlyTickClient()
    store = make_store(api=client)
    store.start()

    assert store.supports_live_ticks(DEFAULT_SYMBOL) is True
    assert store.supports_live_ticks("UNKNOWN") is False
    assert store.has_pending_tick(DEFAULT_SYMBOL) is True
    assert store.has_pending_tick("UNKNOWN") is False


def test_store_subscription_is_idempotent_within_session_and_resets_after_stop():
    client = FakeBtApiClient()
    store = make_store(api=client)

    store.start()
    store.subscribe(DEFAULT_SYMBOL)
    store.subscribe(DEFAULT_SYMBOL)

    assert client.subscriptions == [DEFAULT_SYMBOL]


def test_store_subscribe_without_api_method_is_noop_and_does_not_mark_symbol_subscribed():
    class NoSubscribeClient:
        def __init__(self):
            self.connected = False

        def connect(self):
            self.connected = True

        def disconnect(self):
            self.connected = False

    store = make_store(api=NoSubscribeClient())

    store.start()
    store.subscribe(DEFAULT_SYMBOL)

    assert DEFAULT_SYMBOL not in store._subscribed_datanames
    event_types = [kwargs["event"]["event_type"] for _msg, _args, kwargs in store.get_notifications()]
    assert "market_data_subscribe_request" not in event_types


def test_store_subscribe_works_before_start_with_lightweight_client_without_connect_method():
    class LightweightSubscribeClient:
        def __init__(self):
            self.subscriptions = []

        def subscribe(self, dataname):
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
    class NoSubscribeClient:
        pass

    store = make_store(api=NoSubscribeClient())

    assert store.is_connected is False

    store.subscribe(DEFAULT_SYMBOL)

    assert store.is_connected is True
    assert DEFAULT_SYMBOL not in store._subscribed_datanames
    event_types = [kwargs["event"]["event_type"] for _msg, _args, kwargs in store.get_notifications()]
    assert "market_data_subscribe_request" not in event_types


def test_store_subscribe_connects_on_demand_before_start():
    class TrackingSubscribeClient:
        def __init__(self):
            self.connected = False
            self.connect_calls = 0
            self.subscriptions = []

        def connect(self):
            self.connect_calls += 1
            self.connected = True

        def disconnect(self):
            self.connected = False

        def subscribe(self, dataname):
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
    class TrackingClient(FakeBtApiClient):
        def __init__(self):
            super().__init__()
            self.disconnect_calls = 0

        def disconnect(self):
            self.disconnect_calls += 1
            return super().disconnect()

    client = TrackingClient()
    store = make_store(api=client)

    store.stop()

    assert client.disconnect_calls == 0
    assert store.get_notifications() == []


def test_store_deduplicates_subscriptions_within_session_but_resubscribes_after_restart():
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
    client = FakeBtApiClient()
    store = make_store(api=client)

    store.start()
    store.stop()
    store.stop()

    event_types = [kwargs["event"]["event_type"] for _msg, _args, kwargs in store.get_notifications()]

    assert event_types.count("store_disconnect_requested") == 1
    assert event_types.count("store_disconnected") == 1


def test_store_stop_falls_back_to_api_stop_when_disconnect_is_unavailable():
    class StopOnlyClient:
        def __init__(self):
            self.connected = False
            self.stop_calls = 0

        def connect(self):
            self.connected = True

        def stop(self):
            self.stop_calls += 1
            self.connected = False

    client = StopOnlyClient()
    store = make_store(api=client)

    store.start()
    store.stop()

    assert client.stop_calls == 1
    assert store.is_connected is False


def test_store_start_falls_back_to_api_start_when_connect_is_unavailable():
    class StartOnlyClient:
        def __init__(self):
            self.connected = False
            self.start_calls = 0

        def start(self):
            self.start_calls += 1
            self.connected = True

        def stop(self):
            self.connected = False

    client = StartOnlyClient()
    store = make_store(api=client)

    store.start()

    assert client.start_calls == 1
    assert store.is_connected is True


def test_store_start_marks_lightweight_client_ready_without_connect_or_start_methods():
    class LightweightClient:
        def get_balance(self):
            return {"cash": 1000.0, "value": 1200.0}

    store = make_store(api=LightweightClient())

    store.start()

    assert store.is_connected is True
    event_types = [kwargs["event"]["event_type"] for _msg, _args, kwargs in store.get_notifications()]
    assert event_types[:3] == ["store_connecting", "store_connected", "store_ready"]


def test_store_autostart_connects_during_construction_and_emits_startup_events():
    class CountingClient(FakeBtApiClient):
        def __init__(self):
            super().__init__()
            self.connect_calls = 0

        def connect(self):
            self.connect_calls += 1
            return super().connect()

    client = CountingClient()
    store = make_store(api=client, autostart=True)

    assert client.connect_calls == 1
    assert store.is_connected is True
    event_types = [kwargs["event"]["event_type"] for _msg, _args, kwargs in store.get_notifications()]
    assert event_types[:3] == ["store_connecting", "store_connected", "store_ready"]


def test_store_start_is_idempotent_and_does_not_duplicate_connect_events():
    class CountingClient(FakeBtApiClient):
        def __init__(self):
            super().__init__()
            self.connect_calls = 0

        def connect(self):
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


def test_store_start_does_not_duplicate_same_data_feed_binding():
    store = make_store(api=FakeBtApiClient())
    feed = store.getdata(dataname=DEFAULT_SYMBOL, backfill_start=False)

    store.start(data=feed)
    store.start(data=feed)

    assert store._data_feeds == [feed]


def test_store_register_does_not_duplicate_same_data_feed_binding():
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
    class DummyFeed(BtApiFeed):
        pass

    store = make_store(api=fake_client, provider="btapi")
    data = store.getdata(dataname=DEFAULT_SYMBOL, data_cls=DummyFeed)

    assert isinstance(data, DummyFeed)
    assert data.store is store
    assert data._store is store
    assert data.provider == "btapi"


def test_store_getdata_preserves_explicit_store_and_provider_arguments(fake_client):
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
    class DummyBroker(BtApiBroker):
        pass

    store = make_store(api=fake_client, provider="btapi")
    broker = store.getbroker(broker_cls=DummyBroker)

    assert isinstance(broker, DummyBroker)
    assert broker.store is store
    assert broker.p.provider == "btapi"
    assert store._broker is broker


def test_store_getbroker_updates_store_broker_reference_to_latest_instance(fake_client):
    store = make_store(api=fake_client)

    broker_a = store.getbroker()
    broker_b = store.getbroker()

    assert broker_a is not broker_b
    assert store._broker is broker_b


def test_store_start_binds_provided_broker_instance(fake_client):
    store = make_store(api=fake_client)
    broker = BtApiBroker(store=store, provider=store.provider)

    store.start(broker=broker)

    assert store._broker is broker


def test_store_start_binds_data_and_broker_in_single_call(fake_client):
    store = make_store(api=fake_client)
    broker = BtApiBroker(store=store, provider=store.provider)
    data = store.getdata(dataname=DEFAULT_SYMBOL, backfill_start=False)

    store.start(data=data, broker=broker)

    assert store._broker is broker
    assert store._data_feeds == [data]


def test_store_repeated_start_with_data_and_new_broker_updates_broker_without_duplicating_feed(fake_client):
    store = make_store(api=fake_client)
    broker_a = BtApiBroker(store=store, provider=store.provider)
    broker_b = BtApiBroker(store=store, provider=store.provider)
    data = store.getdata(dataname=DEFAULT_SYMBOL, backfill_start=False)

    store.start(data=data, broker=broker_a)
    store.start(data=data, broker=broker_b)

    assert store._broker is broker_b
    assert store._data_feeds == [data]


def test_store_submit_order_uses_create_order_alias_and_emits_runtime_events():
    class CreateOrderOnlyClient:
        def __init__(self):
            self.connected = False
            self.created_orders = []

        def connect(self):
            self.connected = True

        def disconnect(self):
            self.connected = False

        def create_order(self, **payload):
            self.created_orders.append(dict(payload))
            return {"id": "alias-1", "order_ref": "alias-ref-1"}

    class DummyOrder:
        def __init__(self):
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
            return "Limit"

        def isbuy(self):
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
    class NoSubmitClient:
        def __init__(self):
            self.connected = False

        def connect(self):
            self.connected = True

        def disconnect(self):
            self.connected = False

    class DummyOrder:
        def __init__(self):
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
            return "Limit"

        def isbuy(self):
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
    class OrderRefOnlyClient:
        def __init__(self):
            self.connected = False
            self.created_orders = []

        def connect(self):
            self.connected = True

        def disconnect(self):
            self.connected = False

        def create_order(self, **payload):
            self.created_orders.append(dict(payload))
            return {"order_ref": "alias-ref-1"}

    class DummyOrder:
        def __init__(self):
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
            return "Limit"

        def isbuy(self):
            return True

    store = make_store(api=OrderRefOnlyClient())

    response = store.submit_order(DummyOrder())

    assert response["order_ref"] == "alias-ref-1"
    runtime_events = [kwargs["event"] for _msg, _args, kwargs in store.get_notifications()]
    accepted = next(event for event in runtime_events if event["event_type"] == "order_submit_accepted")
    assert accepted["order_ref"] == 7
    assert accepted["status"] == "accepted"


def test_store_cancel_order_uses_external_order_id_and_emits_runtime_events():
    class CancelOrderClient:
        def __init__(self):
            self.connected = False
            self.cancelled_orders = []

        def connect(self):
            self.connected = True

        def disconnect(self):
            self.connected = False

        def cancel_order(self, order_ref, dataname=None):
            self.cancelled_orders.append({"order_ref": order_ref, "dataname": dataname})
            return True

    class DummyOrder:
        def __init__(self):
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
    class CancelOrderClient:
        def __init__(self):
            self.connected = False
            self.cancelled_orders = []

        def connect(self):
            self.connected = True

        def disconnect(self):
            self.connected = False

        def cancel_order(self, order_ref, dataname=None):
            self.cancelled_orders.append({"order_ref": order_ref, "dataname": dataname})
            return True

    class DummyOrder:
        def __init__(self):
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
    class NoCancelClient:
        def __init__(self):
            self.connected = False

        def connect(self):
            self.connected = True

        def disconnect(self):
            self.connected = False

    class DummyOrder:
        def __init__(self):
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
    class CountingClient(FakeBtApiClient):
        def __init__(self):
            super().__init__(
                balance={"cash": 1000.0, "value": 1200.0},
                positions=[{"instrument": DEFAULT_SYMBOL, "volume": 2, "price": 99.5}],
            )
            self.balance_calls = 0
            self.position_calls = 0

        def get_balance(self):
            self.balance_calls += 1
            return super().get_balance()

        def get_positions(self):
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
    class FlakyClient(FakeBtApiClient):
        def __init__(self):
            super().__init__(
                balance={"cash": 800.0, "value": 900.0},
                positions=[{"instrument": DEFAULT_SYMBOL, "volume": 1, "price": 100.0}],
            )
            self.fail = False

        def get_balance(self):
            if self.fail:
                raise RuntimeError("temporary balance failure")
            return super().get_balance()

        def get_positions(self):
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
    class AccountOnlyClient:
        def __init__(self):
            self.connected = False

        def connect(self):
            self.connected = True

        def disconnect(self):
            self.connected = False

        def get_account(self):
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
    class AliasOnlyOpenOrdersClient:
        def __init__(self):
            self.connected = False

        def connect(self):
            self.connected = True

        def disconnect(self):
            self.connected = False

        def get_open_orders(self):
            return [{"id": "btapi-1", "symbol": DEFAULT_SYMBOL, "side": "buy"}]

    client = AliasOnlyOpenOrdersClient()
    store = make_store(api=client)
    store.start()

    assert [item["id"] for item in store.fetch_open_orders()] == ["btapi-1"]
    assert [item["id"] for item in store.get_open_orders()] == ["btapi-1"]
    assert [item["id"] for item in store.getopenorders()] == ["btapi-1"]


def test_store_open_order_queries_honor_ttl_cache():
    class CountingClient(FakeBtApiClient):
        def __init__(self):
            super().__init__(open_orders=[{"id": "btapi-1", "symbol": DEFAULT_SYMBOL, "side": "buy"}])
            self.open_order_calls = 0

        def fetch_open_orders(self):
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
    class FlakyOpenOrdersClient(FakeBtApiClient):
        def __init__(self):
            super().__init__(open_orders=[{"id": "btapi-1", "symbol": DEFAULT_SYMBOL, "side": "buy"}])
            self.fail = False

        def fetch_open_orders(self):
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
    class NoOpenOrderClient(FakeBtApiClient):
        def fetch_open_orders(self):
            raise AttributeError("unsupported")

    client = NoOpenOrderClient()
    store = make_store(api=client)
    store.start()

    assert store.fetch_open_orders() == []
    assert store.get_open_orders() == []
    assert store.getopenorders() == []


def test_ctp_provider_switches_to_gateway_from_env(monkeypatch):
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
    _create_ctp_wrapper_class()

    import bt_api_py.ctp.client as ctp_client_module

    assert hasattr(ctp_client_module._MdSpi, "OnRspQryInvestorPositionDetail")
    assert hasattr(ctp_client_module._MdSpi, "OnRspQryNotice")
    assert hasattr(ctp_client_module._TraderSpi, "OnRspQryInvestorPositionDetail")
    assert hasattr(ctp_client_module._TraderSpi, "OnRspQryNotice")


def test_ctp_provider_switches_to_generic_gateway_from_env(monkeypatch):
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
    assert _split_ctp_symbol("CF2609.CZCE") == ("CF609", "CZCE")


def test_split_ctp_symbol_normalizes_known_czce_prefix_without_exchange():
    assert _split_ctp_symbol("MA2609") == ("MA609", "")


def test_split_ctp_symbol_does_not_change_cffex_style_symbol_without_exchange():
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
