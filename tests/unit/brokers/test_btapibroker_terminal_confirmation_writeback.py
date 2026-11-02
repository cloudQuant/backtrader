"""A late provider-confirmed terminal fact resolves stale order uncertainty.

The Broker's ordinary update path projects orders it still treats as live.  An
order that had already reached its local terminal state therefore kept a stale
``execution_unknown`` / ``cancel_execution_unknown`` marker even after the SDK
journal durably confirmed the venue outcome.
"""

from __future__ import annotations

from typing import Any, Callable

import backtrader as bt
import pytest

from backtrader.order import SellOrder
from tests.fixtures.fake_btapi import DEFAULT_SYMBOL, FakeBtApiClient, make_bar, make_store

CTP_SYMBOL = "SHFE.ag2512"
CTP_INSTRUMENT = "AG2512"


class _RefreshAdapter:
    """Managed adapter with controllable durable reads and no legacy writes."""

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


def _managed_stack():
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
    return client, store, data, broker, adapter


def _plain_stack(symbol: str = DEFAULT_SYMBOL):
    client = FakeBtApiClient(history={symbol: [make_bar(0, 100.0, 4100.0, 99.0, 4000.0)]})
    store = make_store(api=client)
    data = store.getdata(dataname=symbol)
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
    return client, store, data, broker


def _submit_managed(broker: Any, data: Any, intent_id: str) -> Any:
    return broker.buy(
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


def _terminal_uncertain_order(broker: Any, data: Any, **flags: bool) -> Any:
    """Build a framework order that already terminated locally with uncertainty."""
    order = SellOrder(
        owner=None,
        data=data,
        size=1,
        price=4000.0,
        exectype=bt.Order.Limit,
        simulated=True,
    )
    order.submit(broker)
    order.addcomminfo(broker.getcommissioninfo(data))
    order.accept(broker)
    broker.orders[order.ref] = order
    order.cancel()
    assert order.alive() is False
    order.addinfo(
        execution_unknown=bool(flags.get("execution_unknown", True)),
        cancel_execution_unknown=bool(flags.get("cancel_execution_unknown", True)),
    )
    return order


def _durable_terminal_record(revision: int = 7) -> dict[str, Any]:
    """Return a FILLED durable service record carrying its own fill facts."""
    return {
        "kind": "service_execution_record",
        "service_execution_state": "FILLED",
        "service_record_revision": revision,
        "status": "completed",
        "data_name": DEFAULT_SYMBOL,
        "filled": "1",
        "price": "101.0",
        "avg_price": "101.0",
        "cumulative_commission": "0.1",
    }


@pytest.fixture
def managed_stack():
    client, store, data, broker, adapter = _managed_stack()
    try:
        yield client, store, data, broker, adapter
    finally:
        store.stop()


@pytest.fixture
def plain_stack():
    client, store, data, broker = _plain_stack()
    try:
        yield client, store, data, broker
    finally:
        store.stop()
























def _ctp_snapshot(request_ids: tuple[int, int, int, int]) -> dict[str, Any]:
    names = ("account", "positions", "orders", "trades")
    return {
        "evidence_complete": True,
        "flat": True,
        "unknown_intent_count": 0,
        "unmatched_trade_count": 0,
        "reconciliation_fingerprint": "c" * 64,
        "account_fingerprint": "account-scope",
        "connection_generation": 3,
        "query_results": {name: {"request_id": rid} for name, rid in zip(names, request_ids)},
        "orders": [
            {
                "status": "canceled",
                "order_ref": "9001",
                "external_order_id": "sys-9001",
                "front_id": 1,
                "session_id": 2,
                "exchange_id": "SHFE",
                "instrument_id": CTP_INSTRUMENT,
                "trading_day": "20261031",
            }
        ],
        "trades": [],
        "positions": [],
    }
