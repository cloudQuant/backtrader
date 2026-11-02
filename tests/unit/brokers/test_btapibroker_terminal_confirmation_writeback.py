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


def test_confirmed_terminal_observation_clears_flags_and_records_origin(plain_stack) -> None:
    _client, _store, _data, broker = plain_stack
    order = _terminal_uncertain_order(broker, _data)
    notifications_before = len(broker.notifs)
    status_before = order.status

    applied = broker.apply_confirmed_terminal_observation(
        order,
        {"terminal_confirmed": True, "status": "canceled", "filled": "1", "price": "4000.0"},
        source="ctp_reconciliation_terminal_query",
    )

    assert applied is True
    assert order.info["execution_unknown"] is False
    assert order.info["cancel_execution_unknown"] is False
    assert order.info["confirmation_source"] == "ctp_reconciliation_terminal_query"
    assert order.info["confirmed_terminal_status"] == "canceled"
    assert order.status == status_before
    # The confirmation is a terminal fact only: no status transition, no fill,
    # and no second notification for a state the strategy already saw.
    assert len(broker.notifs) == notifications_before
    assert order.executed.size == 0
    assert order.executed.price == 0
    assert order.executed.comm == 0


def test_unknown_confirmation_keeps_uncertainty(plain_stack) -> None:
    _client, _store, _data, broker = plain_stack
    order = _terminal_uncertain_order(broker, _data)

    assert (
        broker.apply_confirmed_terminal_observation(
            order,
            {"terminal_confirmed": True, "status": "canceled", "execution_unknown": True},
        )
        is False
    )
    assert (
        broker.apply_confirmed_terminal_observation(
            order, {"service_execution_state": "UNKNOWN", "status": "canceled"}
        )
        is False
    )
    assert order.info["execution_unknown"] is True
    assert order.info["cancel_execution_unknown"] is True
    assert "confirmation_source" not in order.info


def test_non_terminal_or_unrecognized_confirmation_keeps_uncertainty(plain_stack) -> None:
    _client, _store, _data, broker = plain_stack
    order = _terminal_uncertain_order(broker, _data)

    for observation in (
        {"terminal_confirmed": True, "status": "accepted"},
        {"terminal_confirmed": True, "status": "partial"},
        {"service_execution_state": "ACKED", "status": "accepted"},
        {"service_execution_state": "NEVER_SEEN", "status": "wat"},
        {},
        None,
    ):
        assert broker.apply_confirmed_terminal_observation(order, observation) is False
    assert order.info["execution_unknown"] is True


def test_local_snapshot_without_confirmation_keeps_uncertainty(plain_stack) -> None:
    _client, _store, _data, broker = plain_stack
    order = _terminal_uncertain_order(broker, _data)

    assert (
        broker.apply_confirmed_terminal_observation(
            order, {"status": "canceled", "execution_source": "local"}
        )
        is False
    )
    assert order.info["execution_unknown"] is True
    assert order.info["cancel_execution_unknown"] is True


def test_ledger_mismatch_keeps_uncertainty(plain_stack) -> None:
    _client, _store, _data, broker = plain_stack
    order = _terminal_uncertain_order(broker, _data)
    order.addinfo(ledger_mismatch=True)

    applied = broker.apply_confirmed_terminal_observation(
        order, {"terminal_confirmed": True, "status": "canceled"}
    )

    assert applied is False
    assert order.info["execution_unknown"] is True


def test_repeat_confirmation_is_idempotent_and_notifies_nobody(plain_stack) -> None:
    _client, _store, _data, broker = plain_stack
    order = _terminal_uncertain_order(broker, _data)
    observation = {"terminal_confirmed": True, "status": "canceled"}

    assert broker.apply_confirmed_terminal_observation(order, observation, source="first") is True
    resolved = {
        key: order.info[key]
        for key in ("execution_unknown", "cancel_execution_unknown", "confirmation_source")
    }
    notifications = len(broker.notifs)

    assert broker.apply_confirmed_terminal_observation(order, observation, source="second") is False
    assert {key: order.info[key] for key in resolved} == resolved
    assert len(broker.notifs) == notifications


def test_order_that_was_never_uncertain_is_not_marked(plain_stack) -> None:
    _client, _store, _data, broker = plain_stack
    order = _terminal_uncertain_order(
        broker, _data, execution_unknown=False, cancel_execution_unknown=False
    )

    assert (
        broker.apply_confirmed_terminal_observation(
            order, {"terminal_confirmed": True, "status": "canceled"}
        )
        is False
    )
    assert "confirmation_source" not in order.info


def test_refresh_applies_durable_terminal_record_to_locally_terminal_order(
    managed_stack,
) -> None:
    _client, _store, data, broker, adapter = managed_stack
    live = _submit_managed(broker, data, "terminal-writeback-live")
    late = _submit_managed(broker, data, "terminal-writeback-late")
    late.status = bt.Order.Canceled
    late.addinfo(execution_unknown=True)
    assert late.alive() is False
    notifications = len(broker.notifs)
    adapter.projection_for_intent = lambda intent_id: (
        _durable_terminal_record() if intent_id.endswith("-late") else None
    )

    applied = broker.refresh_managed_orders(limit=4)

    assert applied == (late.ref,)
    assert adapter.refresh_calls == ["terminal-writeback-live", "terminal-writeback-late"]
    assert late.info["execution_unknown"] is False
    assert late.info["confirmation_source"] == "managed_service_projection"
    assert late.info["confirmed_terminal_status"] == "completed"
    assert late.status == bt.Order.Canceled
    assert late.executed.size == 0
    assert len(broker.notifs) == notifications
    assert live.alive() is True

    # The resolved order leaves eligibility, so a repeat pass is bounded.
    assert broker.refresh_managed_orders(limit=4) == ()
    assert adapter.refresh_calls == [
        "terminal-writeback-live",
        "terminal-writeback-late",
        "terminal-writeback-live",
    ]


def test_refresh_keeps_uncertainty_on_unknown_durable_record(managed_stack) -> None:
    _client, _store, data, broker, adapter = managed_stack
    order = _submit_managed(broker, data, "terminal-writeback-unknown")
    order.status = bt.Order.Canceled
    order.addinfo(execution_unknown=True)
    adapter.projection_for_intent = lambda _intent_id: {
        "kind": "service_execution_record",
        "service_execution_state": "UNKNOWN",
        "status": "pending",
        "execution_unknown": True,
    }

    assert broker.refresh_managed_orders(limit=4) == ()
    assert order.info["execution_unknown"] is True
    assert "confirmation_source" not in order.info


def test_refresh_still_prunes_terminal_orders_without_uncertainty(managed_stack) -> None:
    _client, _store, data, broker, adapter = managed_stack
    settled = _submit_managed(broker, data, "terminal-writeback-settled")
    settled.status = bt.Order.Canceled
    adapter.projection_for_intent = lambda _intent_id: None

    assert broker.refresh_managed_orders(limit=4) == ()
    assert adapter.refresh_calls == []


def test_alive_managed_order_keeps_the_ordinary_update_path(managed_stack) -> None:
    _client, _store, data, broker, adapter = managed_stack
    order = _submit_managed(broker, data, "terminal-writeback-alive")
    notifications_before = len(broker.notifs)
    adapter.projection_for_intent = lambda _intent_id: _durable_terminal_record()

    applied = broker.refresh_managed_orders(limit=4)

    assert applied == (order.ref,)
    assert order.alive() is False
    assert order.executed.size == pytest.approx(1.0)
    assert order.executed.price == pytest.approx(101.0)
    assert len(broker.notifs) > notifications_before
    assert "confirmation_source" not in order.info


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


def test_ctp_reconciliation_terminal_row_resolves_locally_terminal_order() -> None:
    _client, store, data, broker = _plain_stack(symbol=CTP_SYMBOL)
    try:
        order = _terminal_uncertain_order(broker, data)
        order.addinfo(ctp_order_ref="9001", external_order_id="sys-9001")
        broker._ctp_reconciliation_required = True

        broker.record_ctp_reconciliation(_ctp_snapshot((11, 12, 13, 14)))
        assert order.info["execution_unknown"] is True

        broker.record_ctp_reconciliation(_ctp_snapshot((21, 22, 23, 24)))

        assert order.info["execution_unknown"] is False
        assert order.info["cancel_execution_unknown"] is False
        assert order.info["confirmation_source"] == "ctp_reconciliation_terminal_query"
        assert order.info["confirmed_terminal_status"] == "canceled"
        assert order.status == bt.Order.Canceled
    finally:
        store.stop()


def test_ctp_reconciliation_without_terminal_row_keeps_uncertainty() -> None:
    _client, store, data, broker = _plain_stack(symbol=CTP_SYMBOL)
    try:
        order = _terminal_uncertain_order(broker, data)
        order.addinfo(ctp_order_ref="9001", external_order_id="sys-9001")
        broker._ctp_reconciliation_required = True
        pending = _ctp_snapshot((11, 12, 13, 14))
        pending["orders"][0]["status"] = "pending"
        replay = _ctp_snapshot((21, 22, 23, 24))
        replay["orders"][0]["status"] = "pending"

        broker.record_ctp_reconciliation(pending)
        broker.record_ctp_reconciliation(replay)

        assert order.info["execution_unknown"] is True
        assert "confirmation_source" not in order.info
    finally:
        store.stop()
