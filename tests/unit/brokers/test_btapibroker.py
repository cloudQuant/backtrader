"""Unit tests for the unified BtApiBroker."""

import pytest
import backtrader as bt

from tests.fixtures.fake_btapi import DEFAULT_SYMBOL, FakeBtApiClient, make_bar, make_store


@pytest.fixture
def started_stack():
    """Create a started store, feed, and broker with one loaded bar."""
    client = FakeBtApiClient(
        balance={"cash": 1250.0, "value": 1450.0},
        positions=[{"instrument": DEFAULT_SYMBOL, "volume": 2, "price": 99.5}],
        history={DEFAULT_SYMBOL: [make_bar(0, 100.0, 101.0, 99.0, 100.5)]},
    )
    store = make_store(api=client)
    data = store.getdata(dataname=DEFAULT_SYMBOL)
    broker = store.getbroker()

    data._start()
    assert data.load() is True
    broker.start()

    yield client, store, data, broker

    broker.stop()


def test_buy_and_cancel_order_roundtrip(started_stack):
    """Broker should submit and cancel orders through BtApiStore."""
    client, _store, data, broker = started_stack

    order = broker.buy(
        owner=None,
        data=data,
        size=1,
        price=101.0,
        exectype=bt.Order.Limit,
    )

    assert order.status == bt.Order.Accepted
    assert order.info["external_order_id"] == "btapi-1"
    assert client.submitted_orders[0]["symbol"] == DEFAULT_SYMBOL
    assert client.submitted_orders[0]["side"] == "buy"

    broker.cancel(order)

    assert order.status == bt.Order.Canceled
    assert client.cancelled_orders == [{"order_ref": "btapi-1", "dataname": DEFAULT_SYMBOL}]


def test_getposition_reads_positions_from_store(started_stack):
    """Broker positions should reflect the unified store payload."""
    _client, _store, data, broker = started_stack

    position = broker.getposition(data)

    assert position.size == pytest.approx(2.0)
    assert position.price == pytest.approx(99.5)
    assert broker.getcash() == pytest.approx(1250.0)
    assert broker.getvalue() == pytest.approx(1450.0)
