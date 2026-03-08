"""Unit tests for the unified BtApiStore."""

import pytest

from backtrader.brokers.btapibroker import BtApiBroker
from backtrader.feeds.btapifeed import BtApiFeed
from backtrader.stores.btapistore import (
    BtApiMissingDependencyError,
    BtApiProviderNotImplementedError,
    BtApiStore,
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
