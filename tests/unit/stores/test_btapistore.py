"""Unit tests for the unified BtApiStore."""

import pytest

from backtrader.brokers.btapibroker import BtApiBroker
from backtrader.feeds.btapifeed import BtApiFeed
from backtrader.stores.btapistore import (
    BtApiMissingDependencyError,
    BtApiProviderNotImplementedError,
    BtApiStore,
    _split_ctp_symbol,
)
from tests.fixtures.fake_btapi import DEFAULT_SYMBOL, FakeBtApiClient, make_bar, make_store


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


def test_store_factories_return_btapi_types(fake_client):
    """Store factory helpers should return the unified broker/feed implementations."""
    store = make_store(api=fake_client)

    assert isinstance(store.getbroker(), BtApiBroker)
    assert isinstance(store.getdata(dataname=DEFAULT_SYMBOL), BtApiFeed)


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
