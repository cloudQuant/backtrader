"""Logical-run recovery history and owner-position reconciliation contracts."""

from __future__ import annotations

import hashlib
from copy import copy
from types import SimpleNamespace
from typing import Any

import pytest

from backtrader.brokers.btapibroker import BtApiBroker
from backtrader.strategy import Strategy
from backtrader.stores.service_execution_adapter import ServiceExecutionAdapter
from backtrader.stores.service_execution_recovery import (
    ServiceExecutionRecoveryError,
    ServiceExecutionRecoveryJournal,
    ServiceExecutionRecoveryNamespace,
)


_ACCOUNT = "account-recovery"
_STRATEGY = "strategy-recovery"
_RUN = "logical-run-recovery"
_ACCOUNT_KEY = "canonical-account-recovery"
_SCOPE_KEY = "durable-scope-recovery"
_GENERATION = "0123456789abcdef0123456789abcdef"
_DIRECTORY = "directory-recovery-v1"


def _namespace() -> ServiceExecutionRecoveryNamespace:
    return ServiceExecutionRecoveryNamespace(_ACCOUNT, _STRATEGY, _RUN)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _coverage(high_water: int) -> dict[str, Any]:
    return {
        "account_key": _ACCOUNT_KEY,
        "owner_kind": "STRATEGY",
        "owner_ref": _STRATEGY,
        "scope_directory_revision": _DIRECTORY,
        "journal_generation": _GENERATION,
        "first_sequence": 1 if high_water else None,
        "last_sequence": high_water if high_water else None,
        "high_water_sequence": high_water,
        "complete": True,
        "source": "EXECUTION_SQLITE_JOURNAL",
        "freshness": "DURABLE_CUT_NOT_PROVIDER_LIVE",
        "scope_semantics": "DURABLE_STRATEGY_SCOPE_NO_RUN_ISOLATION",
    }


def _snapshot(orders: list[dict[str, Any]], high_water: int) -> dict[str, Any]:
    return {
        "view": "RECOVERY_SNAPSHOT",
        "version": 1,
        "coverage": _coverage(high_water),
        "orders": orders,
    }


def _owner_book(
    *,
    cursor: int,
    positions: dict[str, str] | None = None,
    costs: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "account_key": _ACCOUNT_KEY,
        "account_ref": _ACCOUNT,
        "strategy_ref": _STRATEGY,
        "scope_directory_revision": _DIRECTORY,
        "journal_generation": _GENERATION,
        "baseline_execution_cursor": 0,
        "current_execution_cursor": cursor,
        "positions": positions or {},
        "cash_by_currency": {"USD": "10000"},
        "position_costs": costs or {},
        "financial_available": True,
        "cost_basis_complete": True,
    }


def _submit_payload(
    intent_id: str,
    *,
    side: str,
    effect: str,
    quantity: str,
    reduce_only: bool,
) -> dict[str, Any]:
    return {
        "intent_id": intent_id,
        "signal_id": f"signal-{intent_id}",
        "instrument": "BTC-USDT",
        "side": side,
        "position_effect": effect,
        "order_type": "LIMIT",
        "quantity": quantity,
        "price": "10",
        "time_in_force": "GTC",
        "reduce_only": reduce_only,
        "metadata_version": "metadata-v1",
        "deadline_ns": None,
        "tags": {"framework_order_ref": f"order-{intent_id}"},
    }


def _order_row(
    intent_id: str,
    submit_fingerprint: str,
    *,
    side: str,
    effect: str,
    quantity: str,
    filled: str,
    sequence: int,
    commission: str = "0.01",
) -> dict[str, Any]:
    return {
        "scope_key": _SCOPE_KEY,
        "intent_id": intent_id,
        "intent_fingerprint": _sha(f"intent:{intent_id}"),
        "submit_fingerprint": submit_fingerprint,
        "signal_id": f"signal-{intent_id}",
        "instrument": "BTC-USDT",
        "side": side,
        "position_effect": effect,
        "order_type": "LIMIT",
        "quantity": quantity,
        "price": "10",
        "time_in_force": "GTC",
        "reduce_only": effect != "OPEN",
        "metadata_version": "metadata-v1",
        "deadline_ns": None,
        "state": "FILLED" if filled == quantity else "PARTIALLY_FILLED",
        "provider_order_id": f"provider-{intent_id}",
        "filled_quantity": filled,
        "average_price": "10" if filled != "0" else None,
        "cumulative_commission": commission,
        "cumulative_commission_currency": "USD",
        "dispatch_attempts": 1,
        "unknown_reason_code": None,
        "review_required": False,
        "latest_source_sequence": sequence,
        "latest_source_event_id": f"{sequence:032x}",
        "latest_observation_sequence": sequence,
        "latest_observation_event_id": f"{sequence:032x}",
    }


def _fill_event(
    intent_id: str,
    submit_fingerprint: str,
    sequence: int,
    *,
    quantity: str,
    commission: str = "0.01",
) -> dict[str, Any]:
    return {
        "scope_key": _SCOPE_KEY,
        "intent_id": intent_id,
        "intent_fingerprint": _sha(f"intent:{intent_id}"),
        "submit_fingerprint": submit_fingerprint,
        "event_id": f"{sequence:032x}",
        "sequence": sequence,
        "journal_generation": _GENERATION,
        "event_type": "provider_observation",
        "state": "FILLED",
        "event_sha256": _sha(f"event:{sequence}"),
        "details": {
            "provider_order_id": f"provider-{intent_id}",
            "filled_quantity": quantity,
            "average_price": "10",
            "cumulative_commission": commission,
            "cumulative_commission_currency": "USD",
            "reason_code": None,
            "source": "provider",
        },
    }


def _page(
    events: list[dict[str, Any]], high_water: int, *, after_sequence: int = 0
) -> dict[str, Any]:
    return {
        "view": "EVENTS_AFTER",
        "version": 1,
        "coverage": {
            **_coverage(high_water),
            "after_sequence": after_sequence,
            "scanned_through": high_water,
            "has_more": False,
        },
        "events": events,
    }


def _install_flat_baseline(journal: ServiceExecutionRecoveryJournal) -> None:
    journal.install_recovery_baseline(
        _namespace(), _snapshot([], 0), _owner_book(cursor=0)
    )


def test_first_baseline_is_atomic_immutable_and_cannot_rebase_existing_intents(tmp_path) -> None:
    path = tmp_path / "broker-recovery.sqlite3"
    namespace = _namespace()
    journal = ServiceExecutionRecoveryJournal(path)
    _install_flat_baseline(journal)
    baseline = journal.recovery_baseline(namespace)
    assert baseline is not None
    assert baseline["baseline_cursor"] == 0
    assert baseline["positions"] == {}
    journal.close()

    reopened = ServiceExecutionRecoveryJournal(path)
    # A current restart cut may advance, but the original opening book/cursor
    # must survive and must never be overwritten with today's state.
    assert reopened.install_recovery_baseline(
        namespace,
        _snapshot([], 1),
        _owner_book(cursor=1, positions={"BTC-USDT": "2"}),
    ) is False
    persisted = reopened.recovery_baseline(namespace)
    assert persisted["baseline_cursor"] == 0
    assert persisted["positions"] == {}
    reopened.close()

    missing = ServiceExecutionRecoveryJournal(tmp_path / "missing-baseline.sqlite3")
    payload = _submit_payload(
        "intent-before-baseline", side="BUY", effect="OPEN", quantity="1", reduce_only=False
    )
    missing.prepare_intent(namespace, intent_id=payload["intent_id"], submit_payload=payload)
    with pytest.raises(
        ServiceExecutionRecoveryError,
        match="RECOVERY_BASELINE_MISSING_FOR_EXISTING_MANIFEST",
    ):
        missing.install_recovery_baseline(namespace, _snapshot([], 0), _owner_book(cursor=0))
    assert missing.recovery_baseline(namespace) is None
    missing.close()


def test_ordered_history_reconciles_unmatched_facts_but_only_projects_bound_intents(tmp_path) -> None:
    journal = ServiceExecutionRecoveryJournal(tmp_path / "history.sqlite3")
    namespace = _namespace()
    _install_flat_baseline(journal)

    open_payload = _submit_payload(
        "run-open", side="BUY", effect="OPEN", quantity="2", reduce_only=False
    )
    close_payload = _submit_payload(
        "run-close", side="SELL", effect="CLOSE", quantity="1", reduce_only=True
    )
    open_fingerprint = journal.prepare_intent(
        namespace,
        intent_id="run-open",
        submit_payload=open_payload,
        recovery_binding={"tradeid": 7, "data_name": "BTC-USDT"},
    )
    close_fingerprint = journal.prepare_intent(
        namespace,
        intent_id="run-close",
        submit_payload=close_payload,
        recovery_binding={"tradeid": 7, "data_name": "BTC-USDT"},
    )

    old_fingerprint = _sha("older-run-payload")
    own_open = _fill_event("run-open", open_fingerprint, 1, quantity="2")
    old_order = _fill_event("older-run-intent", old_fingerprint, 2, quantity="3")
    own_close = _fill_event("run-close", close_fingerprint, 3, quantity="1")
    assert journal.apply_events_page(
        namespace, _page([own_open, old_order, own_close], 3)
    ) is True

    orders = [
        _order_row(
            "run-open", open_fingerprint, side="BUY", effect="OPEN", quantity="2",
            filled="2", sequence=1,
        ),
        _order_row(
            "older-run-intent", old_fingerprint, side="BUY", effect="OPEN", quantity="3",
            filled="3", sequence=2,
        ),
        _order_row(
            "run-close", close_fingerprint, side="SELL", effect="CLOSE", quantity="1",
            filled="1", sequence=3,
        ),
    ]
    current = _snapshot(orders, 3)
    assert journal.install_snapshot(namespace, current) is True
    book = _owner_book(
        cursor=3,
        positions={"BTC-USDT": "4"},
        costs={
            "BTC-USDT": {
                "quantity": "4",
                "cost_basis": "40",
                "cost_currency": "USD",
                "product_model": "spot",
                "metadata_version": "metadata-v1",
                "average_cost": "10",
            }
        },
    )
    reconciliation = journal.reconcile_owner_positions(namespace, book)
    assert reconciliation["positions_match"] is True
    assert reconciliation["trade_projection_available"] is False
    assert reconciliation["trade_projection_unavailable_reason"] == (
        "provider_execution_time_unavailable"
    )
    assert reconciliation["current_positions"] == {"BTC-USDT": "4"}

    history = journal.ordered_event_history(namespace, limit=2, max_pages=4)
    assert [item["event"]["intent_id"] for item in history] == [
        "run-open", "older-run-intent", "run-close"
    ]
    assert history[0]["binding"] == {"tradeid": 7, "data_name": "BTC-USDT"}
    assert history[1]["matched_manifest"] is False
    assert history[1]["binding"] is None
    assert journal.event_projection(namespace, "older-run-intent") is None
    pending = journal.claim_pending_callbacks(namespace, limit=8)
    assert [item.intent_id for item in pending] == ["run-open", "run-close"]
    journal.close()


class _RecoveryOrder:
    Created, Submitted, Accepted, Partial, Completed, Canceled, Expired, Margin, Rejected = range(9)

    def __init__(self):
        self.ref = 91
        self.size = 2.0
        self.tradeid = 7
        self.data = SimpleNamespace(_name="BTC-USDT")
        self.info: dict[str, Any] = {"managed_intent_id": "run-open"}
        self.executed = SimpleNamespace(
            size=0.0,
            remsize=2.0,
            price=0.0,
            comm=0.0,
            dt=123.0,
            exbits=[],
        )
        self.status = self.Created
        self.broker = None

    def isbuy(self):
        return True

    def addinfo(self, **kwargs):
        self.info.update(kwargs)

    def clone(self):
        result = copy(self)
        result.info = copy(self.info)
        result.executed = copy(self.executed)
        result.executed.exbits = list(self.executed.exbits)
        return result


def test_broker_restores_snapshot_order_scalars_without_booking_owner_state() -> None:
    broker = BtApiBroker(store=None, cash=1000.0)
    order = _RecoveryOrder()
    broker._service_execution_session = SimpleNamespace(
        adapter=SimpleNamespace(
            recovery_manifest=lambda intent_id: {
                "submit_fingerprint": "submit-fingerprint",
                "recovery_binding": {"tradeid": 7, "data_name": "BTC-USDT"},
                "submit_payload": {"side": "BUY"},
            }
        ),
        recovery_journal=object(),
    )
    response = {
        "kind": "service_execution_recovery_restore",
        "intent_id": "run-open",
        "submit_fingerprint": "submit-fingerprint",
        "order_state": {
            "intent_id": "run-open",
            "submit_fingerprint": "submit-fingerprint",
            "quantity": "2",
            "filled_quantity": "1",
            "average_price": None,
            "cumulative_commission": None,
            "state": "PARTIALLY_FILLED",
            "provider_order_id": "provider-1",
            "unknown_reason_code": None,
            "review_required": False,
            "latest_source_sequence": 10,
            "latest_source_event_id": f"{10:032x}",
        },
    }

    broker.orders[order.ref] = order
    broker._restore_service_execution_order(order, response)

    assert order.status == order.Partial
    assert order.executed.size == 1.0
    assert order.executed.remsize == 1.0
    assert order.executed.exbits == []
    assert order.executed.dt == 123.0
    assert order.info["execution_time_unavailable"] is True
    assert order.info["execution_price_unavailable"] is True
    assert order.info["execution_commission_unavailable"] is True
    assert broker.getcash() == 1000.0
    assert dict(broker.positions) == {}


def test_pending_pre_cut_receipt_precedes_restored_snapshot_notification() -> None:
    order = _RecoveryOrder()
    order.info["managed_intent_id"] = "run-open"
    broker = BtApiBroker(store=None, cash=1000.0)
    partial_event = _fill_event(
        "run-open", "submit-fingerprint", 9, quantity="1", commission="0.01"
    )
    partial_event["state"] = "PARTIALLY_FILLED"
    receipt = {
        "matched_manifest": True,
        "callback_pending": True,
        "receipt_id": "b" * 64,
        "sequence": 9,
        "event": partial_event,
    }
    callback = SimpleNamespace(
        receipt_id=receipt["receipt_id"],
        intent_id="run-open",
        sequence=9,
        event=partial_event,
    )
    adapter = SimpleNamespace(
        recovery_startup_cursor=10,
        recovery_manifest=lambda intent_id: {
            "submit_fingerprint": "submit-fingerprint",
            "recovery_binding": {"tradeid": 7, "data_name": "BTC-USDT"},
            "submit_payload": {"side": "BUY"},
        },
        recovery_history=lambda: [receipt],
        claim_recovery_callback=lambda receipt_id: callback,
    )
    broker._service_execution_session = SimpleNamespace(
        adapter=adapter, recovery_journal=object()
    )
    broker.orders[order.ref] = order
    snapshot_response = {
        "kind": "service_execution_recovery_restore",
        "intent_id": "run-open",
        "submit_fingerprint": "submit-fingerprint",
        "order_state": {
            "intent_id": "run-open",
            "submit_fingerprint": "submit-fingerprint",
            "quantity": "2",
            "filled_quantity": "2",
            "average_price": "10",
            "cumulative_commission": "0.02",
            "cumulative_commission_currency": "USD",
            "state": "FILLED",
            "provider_order_id": "provider-1",
            "unknown_reason_code": None,
            "review_required": False,
            "latest_source_sequence": 10,
            "latest_source_event_id": f"{10:032x}",
        },
    }

    broker._restore_service_execution_order(order, snapshot_response)
    broker._defer_service_execution_recovery_snapshot_notification(order)
    assert broker.get_notification() is None

    broker._process_service_execution_recovery()

    historical = broker.get_notification()
    restored_snapshot = broker.get_notification()
    assert historical is not None and historical.status == order.Partial
    assert historical.executed.size == 1.0
    assert historical.info["service_execution_recovery_receipt_id"] == receipt["receipt_id"]
    assert historical.info["service_execution_recovery_restore_only"] is True
    assert restored_snapshot is not None and restored_snapshot.status == order.Completed
    assert restored_snapshot.executed.size == 2.0
    assert "service_execution_recovery_receipt_id" not in restored_snapshot.info
    assert restored_snapshot.info["service_execution_recovery_restore_only"] is True
    assert order.status == order.Completed
    assert order.executed.size == 2.0
    assert broker.get_notification() is None


def test_receipts_at_refreshed_order_cut_are_clone_only_before_snapshot() -> None:
    order = _RecoveryOrder()
    broker = BtApiBroker(store=None, cash=1000.0)
    partial_event = _fill_event(
        "run-open", "submit-fingerprint", 9, quantity="1", commission="0.01"
    )
    partial_event["state"] = "PARTIALLY_FILLED"
    filled_event = _fill_event(
        "run-open", "submit-fingerprint", 10, quantity="2", commission="0.02"
    )
    filled_event["state"] = "FILLED"
    filled_event["details"]["average_price"] = "20"
    receipts = [
        {
            "matched_manifest": True,
            "callback_pending": True,
            "receipt_id": "9" * 64,
            "sequence": 9,
            "event": partial_event,
        },
        {
            "matched_manifest": True,
            "callback_pending": True,
            "receipt_id": "a" * 64,
            "sequence": 10,
            "event": filled_event,
        },
    ]
    callbacks = {
        receipt["receipt_id"]: SimpleNamespace(
            receipt_id=receipt["receipt_id"],
            intent_id="run-open",
            sequence=receipt["sequence"],
            event=receipt["event"],
        )
        for receipt in receipts
    }
    adapter = SimpleNamespace(
        recovery_startup_cursor=8,
        recovery_manifest=lambda intent_id: {
            "submit_fingerprint": "submit-fingerprint",
            "recovery_binding": {"tradeid": 7, "data_name": "BTC-USDT"},
            "submit_payload": {"side": "BUY"},
        },
        recovery_history=lambda: receipts,
        claim_recovery_callback=lambda receipt_id: callbacks.get(receipt_id),
    )
    broker._service_execution_session = SimpleNamespace(
        adapter=adapter, recovery_journal=object()
    )
    broker.orders[order.ref] = order
    snapshot_response = {
        "kind": "service_execution_recovery_restore",
        "intent_id": "run-open",
        "submit_fingerprint": "submit-fingerprint",
        "order_state": {
            "intent_id": "run-open",
            "submit_fingerprint": "submit-fingerprint",
            "quantity": "2",
            "filled_quantity": "2",
            "average_price": "20",
            "cumulative_commission": "0.02",
            "cumulative_commission_currency": "USD",
            "state": "FILLED",
            "provider_order_id": "provider-run-open",
            "unknown_reason_code": None,
            "review_required": False,
            "latest_source_sequence": 10,
            "latest_source_event_id": f"{10:032x}",
        },
    }
    applied_updates = []
    broker._apply_order_update = applied_updates.append

    broker._restore_service_execution_order(order, snapshot_response)
    broker._defer_service_execution_recovery_snapshot_notification(order)
    broker._process_service_execution_recovery()

    partial_notice = broker.get_notification()
    filled_notice = broker.get_notification()
    snapshot_notice = broker.get_notification()
    assert partial_notice is not None and partial_notice.status == order.Partial
    assert partial_notice.executed.size == 1.0
    assert partial_notice.executed.price == pytest.approx(10.0)
    assert filled_notice is not None and filled_notice.status == order.Completed
    assert filled_notice.executed.size == 2.0
    assert filled_notice.executed.price == pytest.approx(20.0)
    assert snapshot_notice is not None and snapshot_notice.status == order.Completed
    assert snapshot_notice.executed.size == 2.0
    assert snapshot_notice.executed.price == pytest.approx(20.0)
    assert [
        partial_notice.info["service_execution_recovery_receipt_id"],
        filled_notice.info["service_execution_recovery_receipt_id"],
    ] == ["9" * 64, "a" * 64]
    assert "service_execution_recovery_receipt_id" not in snapshot_notice.info
    assert applied_updates == []
    assert order.status == order.Completed
    assert order.executed.size == 2.0
    assert order.executed.price == pytest.approx(20.0)
    assert order.executed.comm == pytest.approx(0.02)
    assert order.executed.exbits == []
    assert broker.get_notification() is None


def test_deferred_snapshot_notifications_follow_their_per_order_cuts() -> None:
    broker = BtApiBroker(store=None, cash=1000.0)
    later_cut = _RecoveryOrder()
    later_cut.ref = 92
    later_cut.info["managed_intent_id"] = "later-cut"
    later_cut.addinfo(service_execution_recovery_snapshot_sequence=10)
    earlier_cut = _RecoveryOrder()
    earlier_cut.ref = 91
    earlier_cut.info["managed_intent_id"] = "earlier-cut"
    earlier_cut.addinfo(service_execution_recovery_snapshot_sequence=8)
    broker._recovery_orders_by_intent = {
        "later-cut": later_cut,
        "earlier-cut": earlier_cut,
    }
    broker._recovery_pending_snapshot_notifications = {
        "later-cut": later_cut.clone(),
        "earlier-cut": earlier_cut.clone(),
    }

    broker._flush_service_execution_recovery_snapshot_notifications(
        before_sequence=11, startup_cursor=7
    )

    first = broker.get_notification()
    second = broker.get_notification()
    assert first is not None and first.info["managed_intent_id"] == "earlier-cut"
    assert second is not None and second.info["managed_intent_id"] == "later-cut"
    assert first.info["service_execution_recovery_restore_only"] is True
    assert second.info["service_execution_recovery_restore_only"] is True
    assert broker.get_notification() is None


def test_blocked_recovery_receipt_and_snapshot_keep_uncertainty_flag() -> None:
    order = _RecoveryOrder()
    broker = BtApiBroker(store=None, cash=1000.0)
    event = {
        "intent_id": "run-open",
        "event_type": "dispatch_blocked",
        "state": "BLOCKED",
        "sequence": 9,
        "event_id": f"{9:032x}",
        "details": {"reason_code": "dispatch_not_proven"},
    }
    receipt = {
        "matched_manifest": True,
        "callback_pending": True,
        "receipt_id": "b" * 64,
        "sequence": 9,
        "event": event,
    }
    callback = SimpleNamespace(
        receipt_id=receipt["receipt_id"],
        intent_id="run-open",
        sequence=9,
        event=event,
    )
    adapter = SimpleNamespace(
        recovery_startup_cursor=10,
        recovery_manifest=lambda intent_id: {
            "submit_fingerprint": "submit-fingerprint",
            "recovery_binding": {"tradeid": 7, "data_name": "BTC-USDT"},
            "submit_payload": {"side": "BUY"},
        },
        recovery_history=lambda: [receipt],
        claim_recovery_callback=lambda receipt_id: callback,
    )
    broker._service_execution_session = SimpleNamespace(
        adapter=adapter, recovery_journal=object()
    )
    snapshot_response = {
        "kind": "service_execution_recovery_restore",
        "intent_id": "run-open",
        "submit_fingerprint": "submit-fingerprint",
        "order_state": {
            "intent_id": "run-open",
            "submit_fingerprint": "submit-fingerprint",
            "quantity": "2",
            "filled_quantity": "0",
            "average_price": None,
            "cumulative_commission": "0",
            "cumulative_commission_currency": None,
            "state": "BLOCKED",
            "provider_order_id": None,
            "unknown_reason_code": "dispatch_not_proven",
            "review_required": False,
            "latest_source_sequence": 9,
            "latest_source_event_id": f"{9:032x}",
        },
    }

    broker._restore_service_execution_order(order, snapshot_response)
    broker._defer_service_execution_recovery_snapshot_notification(order)
    broker._process_service_execution_recovery()

    historical = broker.get_notification()
    snapshot = broker.get_notification()
    assert historical is not None and historical.status == order.Rejected
    assert historical.info["execution_unknown"] is True
    assert historical.info["error_code"] == "dispatch_not_proven"
    assert snapshot is not None and snapshot.status == order.Rejected
    assert snapshot.info["execution_unknown"] is True
    assert snapshot.info["error_code"] == "dispatch_not_proven"
    assert broker.get_notification() is None


@pytest.mark.parametrize(
    ("include_prior_fill", "expected_filled", "expected_average", "expected_commission"),
    [(True, 1.0, 10.0, 0.01), (False, 0.0, 0.0, 0.0)],
)
def test_status_only_receipt_uses_only_as_of_event_facts(
    include_prior_fill, expected_filled, expected_average, expected_commission
) -> None:
    order = _RecoveryOrder()
    order.info["managed_intent_id"] = "run-open"
    broker = BtApiBroker(store=None, cash=1000.0)
    prior_fill = _fill_event(
        "run-open", "submit-fingerprint", 8, quantity="1", commission="0.01"
    )
    prior_fill["state"] = "PARTIALLY_FILLED"
    unknown_event = {
        "intent_id": "run-open",
        "event_type": "dispatch_unknown",
        "state": "UNKNOWN",
        "sequence": 9,
        "event_id": f"{9:032x}",
        "details": {"reason_code": "provider_result_ambiguous"},
    }
    pending_receipt = {
        "matched_manifest": True,
        "callback_pending": True,
        "receipt_id": "c" * 64,
        "sequence": 9,
        "event": unknown_event,
    }
    history = [pending_receipt]
    if include_prior_fill:
        history.insert(
            0,
            {
                "matched_manifest": True,
                "callback_pending": False,
                "receipt_id": "d" * 64,
                "sequence": 8,
                "event": prior_fill,
            },
        )
    callback = SimpleNamespace(
        receipt_id=pending_receipt["receipt_id"],
        intent_id="run-open",
        sequence=9,
        event=unknown_event,
    )
    adapter = SimpleNamespace(
        recovery_startup_cursor=10,
        recovery_manifest=lambda intent_id: {
            "submit_fingerprint": "submit-fingerprint",
            "recovery_binding": {"tradeid": 7, "data_name": "BTC-USDT"},
            "submit_payload": {"side": "BUY"},
        },
        recovery_history=lambda: history,
        claim_recovery_callback=lambda receipt_id: callback,
    )
    broker._service_execution_session = SimpleNamespace(
        adapter=adapter, recovery_journal=object()
    )
    broker.orders[order.ref] = order
    snapshot_response = {
        "kind": "service_execution_recovery_restore",
        "intent_id": "run-open",
        "submit_fingerprint": "submit-fingerprint",
        "order_state": {
            "intent_id": "run-open",
            "submit_fingerprint": "submit-fingerprint",
            "quantity": "2",
            "filled_quantity": "2",
            "average_price": "20",
            "cumulative_commission": "0.02",
            "cumulative_commission_currency": "USD",
            "state": "FILLED",
            "provider_order_id": "provider-later",
            "unknown_reason_code": None,
            "review_required": False,
            "latest_source_sequence": 10,
            "latest_source_event_id": f"{10:032x}",
        },
    }

    broker._restore_service_execution_order(order, snapshot_response)
    broker._defer_service_execution_recovery_snapshot_notification(order)
    # These fields are later snapshot state. A status-only historical event
    # must not inherit them when no earlier event established them.
    order.info["error_code"] = "later_snapshot_reason"
    order.info["error_msg"] = "later snapshot message"
    broker._process_service_execution_recovery()

    historical_unknown = broker.get_notification()
    restored_snapshot = broker.get_notification()
    assert historical_unknown is not None and historical_unknown.status == order.Submitted
    assert historical_unknown.executed.size == expected_filled
    assert historical_unknown.executed.price == pytest.approx(expected_average)
    assert historical_unknown.executed.comm == pytest.approx(expected_commission)
    assert historical_unknown.info["execution_unknown"] is True
    assert historical_unknown.info["error_code"] == "provider_result_ambiguous"
    assert "error_msg" not in historical_unknown.info
    assert historical_unknown.info["service_execution_recovery_receipt_id"] == "c" * 64
    assert restored_snapshot is not None and restored_snapshot.status == order.Completed
    assert restored_snapshot.executed.size == 2.0
    assert restored_snapshot.executed.price == pytest.approx(20.0)
    assert restored_snapshot.executed.comm == pytest.approx(0.02)
    assert restored_snapshot.info["external_order_id"] == "provider-later"
    assert restored_snapshot.info["cumulative_commission_currency"] == "USD"
    if include_prior_fill:
        assert historical_unknown.info["external_order_id"] == "provider-run-open"
        assert historical_unknown.info["cumulative_commission_currency"] == "USD"
    else:
        assert "external_order_id" not in historical_unknown.info
        assert "cumulative_commission_currency" not in historical_unknown.info
    assert order.status == order.Completed
    assert order.executed.size == 2.0
    assert broker.get_notification() is None


def test_restore_only_strategy_notification_does_not_rebuild_trade_state() -> None:
    order = _RecoveryOrder()
    order.p = SimpleNamespace(simulated=False)
    order.executed.size = 1.0
    order.info["service_execution_recovery_restore_only"] = True
    strategy = SimpleNamespace(_orderspending=[])

    Strategy._addnotification(strategy, order, quicknotify=False)

    assert strategy._orderspending == [order]
    assert not hasattr(strategy, "_trades")


def test_strategy_acknowledges_only_after_notification_delivery_returns() -> None:
    receipt = "a" * 64
    actions: list[str] = []
    order = SimpleNamespace(info={"service_execution_recovery_receipt_id": receipt})

    class _StrategyHarness:
        _quicknotify = True
        broker = SimpleNamespace(
            acknowledge_service_execution_recovery_receipt=lambda value: actions.append(
                f"ack:{value}"
            ),
            release_service_execution_recovery_receipt=lambda value: actions.append(
                f"release:{value}"
            ),
        )

        def _notify_inner(self, **kwargs):
            actions.append("callback-returned")

    Strategy._notify(_StrategyHarness(), qorders=[order], qtrades=[])
    assert actions == ["callback-returned", f"ack:{receipt}"]

    actions.clear()

    class _FailingStrategyHarness(_StrategyHarness):
        def _notify_inner(self, **kwargs):
            actions.append("callback-raised")
            raise RuntimeError("synthetic callback failure")

    with pytest.raises(RuntimeError, match="synthetic callback failure"):
        Strategy._notify(_FailingStrategyHarness(), qorders=[order], qtrades=[])
    assert actions == ["callback-raised", f"release:{receipt}"]


@pytest.mark.parametrize(
    ("effect", "baseline_positions", "current_positions", "expected_code"),
    [
        ("OPEN", {"BTC-USDT": "1"}, {"BTC-USDT": "1"}, "RECOVERY_OPEN_OWNER_POSITION_ATTRIBUTION_UNAVAILABLE"),
        ("CLOSE", {"BTC-USDT": "1"}, {"BTC-USDT": "1"}, "RECOVERY_CLOSE_BASELINE_INCOMPLETE"),
    ],
)
def test_incomplete_execution_time_cut_rejects_owner_mutations(
    effect, baseline_positions, current_positions, expected_code
) -> None:
    adapter = object.__new__(ServiceExecutionAdapter)
    adapter._require_recovery_baseline = True
    adapter._owner_position_reconciliation = {
        "positions_match": True,
        "unresolved_intents": (),
        "trade_projection_available": False,
        "current_positions": current_positions,
    }
    adapter._recovery_journal = SimpleNamespace(
        recovery_baseline=lambda namespace: {
            "positions": baseline_positions,
            "trade_projection_available": True,
        },
        strategy_trade_positions=lambda namespace: {},
    )
    adapter._recovery_namespace = _namespace()
    payload = {
        "position_effect": effect,
        "instrument": "BTC-USDT",
        "side": "SELL" if effect == "CLOSE" else "BUY",
        "reduce_only": effect == "CLOSE",
        "quantity": "1",
    }

    with pytest.raises(ServiceExecutionRecoveryError, match=expected_code):
        adapter._validate_recovery_dispatch_safety(
            payload, {"data_name": "BTC-USDT", "tradeid": 7}
        )


@pytest.mark.parametrize("close_effect", ["CLOSE", "CLOSE_TODAY", "CLOSE_YESTERDAY"])
def test_multiple_intent_facts_reconcile_tradeid_quantity_and_reject_overclose(
    tmp_path, close_effect
) -> None:
    journal = ServiceExecutionRecoveryJournal(tmp_path / "trade-projection.sqlite3")
    namespace = _namespace()
    _install_flat_baseline(journal)
    payloads = (
        _submit_payload(
            "open-a", side="BUY", effect="OPEN", quantity="2", reduce_only=False
        ),
        _submit_payload(
            "close-a", side="SELL", effect=close_effect, quantity="1", reduce_only=True
        ),
        _submit_payload(
            "open-b", side="BUY", effect="OPEN", quantity="1", reduce_only=False
        ),
    )
    fingerprints = {}
    for payload in payloads:
        fingerprints[payload["intent_id"]] = journal.prepare_intent(
            namespace,
            intent_id=payload["intent_id"],
            submit_payload=payload,
            recovery_binding={"tradeid": 11, "data_name": "BTC-USDT"},
        )
    assert journal.intent_manifest(namespace, "close-a")["submit_payload"][
        "position_effect"
    ] == close_effect
    events = [
        _fill_event("open-a", fingerprints["open-a"], 1, quantity="2"),
        _fill_event("close-a", fingerprints["close-a"], 2, quantity="1"),
        _fill_event("open-b", fingerprints["open-b"], 3, quantity="1"),
    ]
    assert journal.apply_events_page(namespace, _page(events, 3)) is True
    journal.install_snapshot(
        namespace,
        _snapshot(
            [
                _order_row(
                    intent_id, fingerprints[intent_id], side=payload["side"],
                    effect=payload["position_effect"], quantity=payload["quantity"],
                    filled=payload["quantity"], sequence=index,
                )
                for index, (intent_id, payload) in enumerate(
                    ((item["intent_id"], item) for item in payloads), start=1
                )
            ],
            3,
        ),
    )
    assert journal.strategy_trade_positions(namespace) == {
        ("BTC-USDT", 11): pytest.approx(2)
    }

    # A same-trade close cannot exceed the attributable open quantity.
    overclose = _submit_payload(
        "close-too-much", side="SELL", effect=close_effect, quantity="3", reduce_only=True
    )
    journal.prepare_intent(
        namespace,
        intent_id="close-too-much",
        submit_payload=overclose,
        recovery_binding={"tradeid": 11, "data_name": "BTC-USDT"},
    )
    too_much_event = _fill_event(
        "close-too-much", journal.intent_manifest(namespace, "close-too-much")["submit_fingerprint"],
        4, quantity="3",
    )
    with pytest.raises(ServiceExecutionRecoveryError, match="RECOVERY_TRADE_CLOSE_CAPACITY_INVALID"):
        journal.apply_events_page(
            namespace,
            _page([too_much_event], 4, after_sequence=3),
        )
    assert journal.cursor(namespace)["event_cursor"] == 3
    assert journal.strategy_trade_positions(namespace) == {
        ("BTC-USDT", 11): pytest.approx(2)
    }
    journal.close()
