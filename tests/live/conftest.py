"""Shared fixtures for unified bt_api_py live-surface tests."""

import pytest

from tests.fixtures.fake_btapi import DEFAULT_SYMBOL, FakeBtApiClient, make_bar, make_store


@pytest.fixture
def btapi_client():
    """Provide a fake bt_api_py client for live-surface tests."""
    return FakeBtApiClient(
        balance={"cash": 2000.0, "value": 2150.0},
        positions=[{"instrument": DEFAULT_SYMBOL, "volume": 1, "price": 100.0}],
        history={DEFAULT_SYMBOL: [make_bar(0, 100.0, 101.0, 99.0, 100.5)]},
        live={DEFAULT_SYMBOL: [make_bar(1, 100.5, 102.0, 100.0, 101.0)]},
    )


@pytest.fixture
def btapi_store(btapi_client):
    """Provide a started BtApiStore for live-surface tests."""
    store = make_store(api=btapi_client)
    store.start()
    yield store
    store.stop()
