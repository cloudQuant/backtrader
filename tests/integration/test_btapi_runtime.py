"""Integration tests for the unified bt_api_py broker/feed/store stack."""

import pytest
import backtrader as bt

from tests.fixtures.fake_btapi import DEFAULT_SYMBOL


@pytest.mark.integration
def test_btapi_store_broker_and_feed_work_together(btapi_client, btapi_store):
    """Unified store, feed, and broker should work together without venue-specific adapters."""
    data = btapi_store.getdata(dataname=DEFAULT_SYMBOL)
    broker = btapi_store.getbroker()

    data._start()
    broker.start()

    assert data.load() is True
    assert data.close[0] == pytest.approx(100.5)

    order = broker.buy(
        owner=None,
        data=data,
        size=1,
        price=101.0,
        exectype=bt.Order.Limit,
    )

    assert order.status == bt.Order.Accepted
    assert btapi_client.submitted_orders[0]["symbol"] == DEFAULT_SYMBOL

    broker.cancel(order)

    assert order.status == bt.Order.Canceled
    assert btapi_client.cancelled_orders == [{"order_ref": "btapi-1", "dataname": DEFAULT_SYMBOL}]
