"""Regression tests for bounded, fair managed-order refresh passes."""

from __future__ import annotations

from collections import Counter
from typing import Any, Callable

import backtrader as bt
import pytest

from tests.fixtures.fake_btapi import DEFAULT_SYMBOL, FakeBtApiClient, make_bar, make_store


class _RefreshAdapter:
    """Managed adapter with controllable read projections and no legacy writes."""

    def __init__(self) -> None:
        self.refresh_calls: list[str] = []
        self.projection_for_intent: Callable[[str], Any] = lambda _intent_id: None
        self.submit_calls: list[str] = []

    def submit_order(self, order: Any, _legacy_dispatch: Any) -> dict[str, Any]:
        intent_id = order.info["managed_intent_id"]
        self.submit_calls.append(intent_id)
        return {
            "kind": "service_execution_record",
            "managed_intent_id": intent_id,
            "service_execution_state": "ACKED",
            "status": "accepted",
            "external_order_id": "provider-" + intent_id,
            "data_name": DEFAULT_SYMBOL,
        }

    def refresh_projection(self, intent_id: str) -> Any:
        self.refresh_calls.append(intent_id)
        return self.projection_for_intent(intent_id)


@pytest.fixture
def managed_stack():
    adapter = _RefreshAdapter()
    client = FakeBtApiClient(
        balance={"cash": 1000.0, "value": 1000.0},
        history={DEFAULT_SYMBOL: [make_bar(0, 100.0, 102.0, 99.0, 101.0)]},
    )
    store = make_store(api=client, managed_execution_adapter=adapter)
    data = store.getdata(dataname=DEFAULT_SYMBOL)
    data._start()
    assert data.load() is True
    broker = store.getbroker(
        validation_enabled=False,
        cash_check_enabled=False,
        account_refresh_interval=3600.0,
        positions_refresh_interval=3600.0,
        open_orders_refresh_interval=3600.0,
    )
    broker.start()
    try:
        yield client, store, data, broker, adapter
    finally:
        store.stop()


def _submit_managed_orders(broker: Any, data: Any, count: int = 5, start: int = 0) -> list[Any]:
    orders = []
    for index in range(start, start + count):
        intent_id = f"managed-refresh-{index}"
        order = broker.buy(
            owner=None,
            data=data,
            size=1,
            price=101.0,
            exectype=bt.Order.Limit,
            managed_order_type="LIMIT",
            managed_intent_id=intent_id,
            managed_signal_id="signal." + intent_id,
            managed_instrument=DEFAULT_SYMBOL,
            managed_position_effect="OPEN",
            managed_metadata_version="fixture.metadata.v1",
            managed_instrument_metadata_digest="a" * 64,
            offset="open",
            reduce_only=False,
        )
        assert order.alive() is True
        orders.append(order)
    return orders


def _accepted_projection(revision: int) -> dict[str, Any]:
    return {
        "kind": "service_execution_record",
        "service_execution_state": "ACKED",
        "service_record_revision": revision,
        "status": "accepted",
        "external_order_id": "provider-managed-refresh-0",
        "data_name": DEFAULT_SYMBOL,
    }
