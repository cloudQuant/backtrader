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


def test_refresh_budget_counts_none_results_and_rotates_across_unchanged_orders(
    managed_stack,
) -> None:
    client, _store, data, broker, adapter = managed_stack
    orders = _submit_managed_orders(broker, data)
    assert adapter.refresh_calls == []  # refresh remains explicitly caller-driven

    for expected_calls in (
        [f"managed-refresh-{index}" for index in (0, 1)],
        [f"managed-refresh-{index}" for index in (2, 3)],
        [f"managed-refresh-{index}" for index in (4, 0)],
    ):
        assert broker.refresh_managed_orders(limit=2) == ()
        assert adapter.refresh_calls[-2:] == expected_calls

    assert all(order.alive() for order in orders)
    assert client.submitted_orders == []


def test_none_and_replayed_projections_each_consume_one_attempt(managed_stack) -> None:
    client, _store, data, broker, adapter = managed_stack
    _submit_managed_orders(broker, data)

    def projection(intent_id: str) -> dict[str, bool] | None:
        if intent_id.endswith("-0"):
            return None
        return {"managed_execution_replayed": True}

    adapter.projection_for_intent = projection

    assert broker.refresh_managed_orders(limit=2) == ()
    assert adapter.refresh_calls == ["managed-refresh-0", "managed-refresh-1"]
    assert broker.refresh_managed_orders(limit=2) == ()
    assert adapter.refresh_calls == [
        "managed-refresh-0",
        "managed-refresh-1",
        "managed-refresh-2",
        "managed-refresh-3",
    ]
    assert client.submitted_orders == []


def test_a_repeatedly_mutating_first_order_does_not_starve_the_suffix(managed_stack) -> None:
    client, _store, data, broker, adapter = managed_stack
    orders = _submit_managed_orders(broker, data)
    revision = 0

    def projection(intent_id: str) -> dict[str, Any] | None:
        nonlocal revision
        if intent_id != "managed-refresh-0":
            return None
        revision += 1
        return _accepted_projection(revision)

    adapter.projection_for_intent = projection

    for expected_calls in (
        ["managed-refresh-0", "managed-refresh-1"],
        ["managed-refresh-2", "managed-refresh-3"],
        ["managed-refresh-4", "managed-refresh-0"],
    ):
        broker.refresh_managed_orders(limit=2)
        assert adapter.refresh_calls[-2:] == expected_calls

    assert Counter(adapter.refresh_calls) == Counter(
        {
            "managed-refresh-0": 2,
            "managed-refresh-1": 1,
            "managed-refresh-2": 1,
            "managed-refresh-3": 1,
            "managed-refresh-4": 1,
        }
    )
    assert orders[0].info["service_refresh_applied"][:2] == ("ACKED", 2)
    assert client.submitted_orders == []


def test_refresh_failure_advances_the_cursor_before_adapter_call(managed_stack) -> None:
    client, _store, data, broker, adapter = managed_stack
    _submit_managed_orders(broker, data)
    failed = False

    def projection(intent_id: str) -> None:
        nonlocal failed
        if intent_id == "managed-refresh-0" and not failed:
            failed = True
            raise RuntimeError("synthetic refresh failure")
        return

    adapter.projection_for_intent = projection

    with pytest.raises(RuntimeError, match="synthetic refresh failure"):
        broker.refresh_managed_orders(limit=1)
    assert adapter.refresh_calls == ["managed-refresh-0"]

    assert broker.refresh_managed_orders(limit=1) == ()
    assert adapter.refresh_calls == ["managed-refresh-0", "managed-refresh-1"]
    assert client.submitted_orders == []


def test_refresh_queue_prunes_terminal_and_removed_orders_and_adds_new_orders(
    managed_stack,
) -> None:
    client, _store, data, broker, adapter = managed_stack
    orders = _submit_managed_orders(broker, data)

    assert broker.refresh_managed_orders(limit=2) == ()
    assert adapter.refresh_calls == ["managed-refresh-0", "managed-refresh-1"]

    orders[2].status = bt.Order.Canceled
    broker.orders.pop(orders[3].ref)
    new_order = _submit_managed_orders(broker, data, count=1, start=5)[0]
    assert new_order.info["managed_intent_id"] == "managed-refresh-5"

    assert broker.refresh_managed_orders(limit=2) == ()
    assert adapter.refresh_calls[-2:] == ["managed-refresh-4", "managed-refresh-0"]
    assert broker.refresh_managed_orders(limit=2) == ()
    assert adapter.refresh_calls[-2:] == ["managed-refresh-1", "managed-refresh-5"]
    assert "managed-refresh-2" not in adapter.refresh_calls
    assert "managed-refresh-3" not in adapter.refresh_calls
    assert client.submitted_orders == []
