"""Integration tests for BtApiBroker batch-cancel flows."""

from __future__ import annotations

import backtrader as bt
import pytest

from tests.fixtures.fake_btapi import DEFAULT_SYMBOL, FakeBtApiClient, make_bar, make_store


def _start_live_stack():
    """Create a started store/broker/data stack with deterministic history."""
    client = FakeBtApiClient(
        history={
            DEFAULT_SYMBOL: [
                make_bar(0, 100.0, 101.0, 99.0, 100.5),
                make_bar(1, 100.5, 102.0, 100.0, 101.0),
            ]
        }
    )
    store = make_store(api=client)
    data = store.getdata(dataname=DEFAULT_SYMBOL)
    broker = store.getbroker(account_refresh_interval=60.0, positions_refresh_interval=60.0)

    data._start()
    assert data.load() is True
    broker.start()
    return client, store, data, broker


@pytest.mark.integration
def test_batch_cancel_cancels_multiple_live_orders():
    """Batch cancel should cancel every currently open live order."""
    client, store, data, broker = _start_live_stack()

    try:
        order_a = broker.buy(
            owner=None,
            data=data,
            size=1,
            price=101.0,
            exectype=bt.Order.Limit,
        )
        order_b = broker.sell(
            owner=None,
            data=data,
            size=1,
            price=99.0,
            exectype=bt.Order.Limit,
        )

        cancelled = broker.batch_cancel()

        assert [order.ref for order in cancelled] == [order_a.ref, order_b.ref]
        assert all(order.status == bt.Order.Canceled for order in cancelled)
        assert client.cancelled_orders == [
            {"order_ref": "btapi-1", "dataname": DEFAULT_SYMBOL},
            {"order_ref": "btapi-2", "dataname": DEFAULT_SYMBOL},
        ]

        event_types = [kwargs["event"]["event_type"] for _msg, _args, kwargs in store.get_notifications()]
        assert event_types.count("order_cancel_request") == 2
        assert event_types.count("order_cancel_submitted") == 2
    finally:
        broker.stop()


@pytest.mark.integration
def test_batch_cancel_keeps_partial_fill_position_and_cancels_remainder():
    """Partially filled live orders should remain cancellable as a batch."""
    client, _store, data, broker = _start_live_stack()

    try:
        partial_order = broker.buy(
            owner=None,
            data=data,
            size=3,
            price=101.0,
            exectype=bt.Order.Limit,
        )
        queued_order = broker.sell(
            owner=None,
            data=data,
            size=1,
            price=99.0,
            exectype=bt.Order.Limit,
        )

        client.push_broker_update(
            {
                "kind": "trade",
                "external_order_id": "btapi-1",
                "order_ref": "btapi-1",
                "trade_id": "trade-partial-1",
                "data_name": DEFAULT_SYMBOL,
                "side": "buy",
                "offset": "open",
                "size": 1,
                "price": 101.0,
                "timestamp": "09:30:00",
            }
        )

        broker.next()

        assert partial_order.status == bt.Order.Partial
        assert partial_order.executed.size == pytest.approx(1.0)
        assert broker.positions[DEFAULT_SYMBOL].size == pytest.approx(1.0)

        cancelled = broker.batch_cancel([partial_order, queued_order])

        assert [order.ref for order in cancelled] == [partial_order.ref, queued_order.ref]
        assert partial_order.status == bt.Order.Canceled
        assert queued_order.status == bt.Order.Canceled
        assert client.cancelled_orders == [
            {"order_ref": "btapi-1", "dataname": DEFAULT_SYMBOL},
            {"order_ref": "btapi-2", "dataname": DEFAULT_SYMBOL},
        ]
        assert broker.positions[DEFAULT_SYMBOL].size == pytest.approx(1.0)
    finally:
        broker.stop()
