"""Shared fixtures for unified bt_api_py integration tests."""

import pytest

from tests.fixtures.fake_btapi import DEFAULT_SYMBOL, FakeBtApiClient, make_bar, make_store


@pytest.fixture
def btapi_client():
    """Provide a fake bt_api_py client for integration tests."""
    return FakeBtApiClient(
        balance={"cash": 3000.0, "value": 3200.0},
        positions=[{"instrument": DEFAULT_SYMBOL, "volume": 3, "price": 100.0}],
        history={
            DEFAULT_SYMBOL: [
                make_bar(0, 100.0, 101.0, 99.0, 100.5),
                make_bar(1, 100.5, 102.0, 100.0, 101.5),
            ]
        },
        live={DEFAULT_SYMBOL: [make_bar(2, 101.5, 103.0, 101.0, 102.5)]},
    )


@pytest.fixture
def btapi_store(btapi_client):
    """Provide a unified BtApiStore instance for integration tests."""
    store = make_store(api=btapi_client)
    yield store
    store.stop()
