"""Durable manifest, receipt, cursor and callback contracts for service execution."""

from __future__ import annotations

import hashlib
from typing import Any

import pytest

from backtrader.stores.service_execution_recovery import (
    ServiceExecutionRecoveryCallback,
    ServiceExecutionRecoveryError,
    ServiceExecutionRecoveryJournal,
    ServiceExecutionRecoveryNamespace,
)


_ACCOUNT = "account-a"
_STRATEGY = "strategy-a"
_RUN = "stable-run-1"
_SCOPE_KEY = "execution-scope-a"
_GENERATION = "0123456789abcdef0123456789abcdef"
_DIRECTORY = "directory-revision-a"
_INTENT = "intent-1"


def _namespace(run_id: str = _RUN) -> ServiceExecutionRecoveryNamespace:
    return ServiceExecutionRecoveryNamespace(_ACCOUNT, _STRATEGY, run_id)


def _submit_payload(intent_id: str = _INTENT, **changes: Any) -> dict[str, Any]:
    payload = {
        "intent_id": intent_id,
        "signal_id": "signal-1",
        "instrument": "BTC-USDT",
        "side": "BUY",
        "position_effect": "OPEN",
        "order_type": "LIMIT",
        "quantity": "1.0",
        "price": "20.25",
        "time_in_force": "GTC",
        "reduce_only": False,
        "metadata_version": "metadata-v1",
        "deadline_ns": None,
        "tags": {"framework_order_ref": "stable-order-1"},
    }
    payload.update(changes)
    return payload


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _snapshot_order(
    intent_id: str, submit_fingerprint: str, *, sequence: int = 10
) -> dict[str, Any]:
    return {
        "scope_key": _SCOPE_KEY,
        "intent_id": intent_id,
        "intent_fingerprint": _digest("server-intent:" + intent_id),
        "submit_fingerprint": submit_fingerprint,
        "signal_id": "signal-1",
        "instrument": "BTC-USDT",
        "side": "BUY",
        "position_effect": "OPEN",
        "order_type": "LIMIT",
        "quantity": "1.0",
        "price": "20.25",
        "time_in_force": "GTC",
        "reduce_only": False,
        "metadata_version": "metadata-v1",
        "deadline_ns": None,
        "state": "ACKED",
        "provider_order_id": "provider-order-1",
        "filled_quantity": "0",
        "average_price": None,
        "cumulative_commission": "0",
        "cumulative_commission_currency": "USD",
        "dispatch_attempts": 1,
        "unknown_reason_code": None,
        "review_required": False,
        "latest_source_sequence": sequence,
        "latest_source_event_id": f"{sequence:032x}",
        "latest_observation_sequence": None,
        "latest_observation_event_id": None,
    }


def _snapshot(orders: list[dict[str, Any]], *, high_water: int = 10) -> dict[str, Any]:
    return {
        "view": "RECOVERY_SNAPSHOT",
        "version": 1,
        "coverage": {
            "account_key": "canonical-account-a",
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
        },
        "orders": orders,
    }


def _event(
    intent_id: str,
    submit_fingerprint: str,
    sequence: int,
    *,
    event_id: str | None = None,
    event_type: str = "provider_observation",
) -> dict[str, Any]:
    return {
        "scope_key": _SCOPE_KEY,
        "intent_id": intent_id,
        "intent_fingerprint": _digest("server-intent:" + intent_id),
        "submit_fingerprint": submit_fingerprint,
        "event_id": event_id or f"{sequence:032x}",
        "sequence": sequence,
        "journal_generation": _GENERATION,
        "event_type": event_type,
        "state": "PARTIALLY_FILLED",
        "event_sha256": _digest("source-row:{}".format(sequence)),
        "details": {
            "provider_order_id": "provider-order-1",
            "filled_quantity": "0.5",
            "average_price": "20.25",
            "cumulative_commission": "0.01",
            "cumulative_commission_currency": "USD",
            "reason_code": None,
            "source": "reconcile" if event_type == "reconciled_observation" else "provider",
        },
    }


def _page(
    after: int,
    scanned_through: int,
    high_water: int,
    events: list[dict[str, Any]],
    *,
    has_more: bool,
) -> dict[str, Any]:
    return {
        "view": "EVENTS_AFTER",
        "version": 1,
        "coverage": {
            "account_key": "canonical-account-a",
            "owner_kind": "STRATEGY",
            "owner_ref": _STRATEGY,
            "scope_directory_revision": _DIRECTORY,
            "journal_generation": _GENERATION,
            "first_sequence": 1,
            "last_sequence": high_water if high_water else None,
            "high_water_sequence": high_water,
            "source": "EXECUTION_SQLITE_JOURNAL",
            "freshness": "DURABLE_CUT_NOT_PROVIDER_LIVE",
            "after_sequence": after,
            "scanned_through": scanned_through,
            "has_more": has_more,
            "complete": True,
            "scope_semantics": "DURABLE_STRATEGY_SCOPE_NO_RUN_ISOLATION",
        },
        "events": events,
    }


def test_manifest_is_durable_immutable_and_logical_run_scoped(tmp_path) -> None:
    path = tmp_path / "recovery.sqlite3"
    namespace = _namespace()
    payload = _submit_payload()
    journal = ServiceExecutionRecoveryJournal(path)
    fingerprint = journal.prepare_intent(namespace, intent_id=_INTENT, submit_payload=payload)
    journal.close()

    reopened = ServiceExecutionRecoveryJournal(path)
    assert (
        reopened.prepare_intent(namespace, intent_id=_INTENT, submit_payload=payload) == fingerprint
    )
    manifest = reopened.intent_manifest(namespace, _INTENT)
    assert manifest is not None
    assert manifest["submit_fingerprint"] == fingerprint
    assert manifest["submit_payload"] == payload
    with pytest.raises(ServiceExecutionRecoveryError, match="INTENT_MANIFEST_CONFLICT"):
        reopened.prepare_intent(
            namespace,
            intent_id=_INTENT,
            submit_payload=_submit_payload(price="20.26"),
        )
    with pytest.raises(ServiceExecutionRecoveryError, match="INTENT_ID_BOUND_TO_OTHER_RUN"):
        reopened.prepare_intent(
            _namespace("stable-run-2"), intent_id=_INTENT, submit_payload=payload
        )

    cancel_fingerprint = reopened.prepare_cancel(
        namespace,
        cancel_id="cancel.intent-1",
        target_intent_id=_INTENT,
        provider_order_id="provider-order-1",
        metadata_version="metadata-v1",
    )
    assert reopened.cancel_manifest(namespace, "cancel.intent-1")["cancel_fingerprint"] == (
        cancel_fingerprint
    )
    with pytest.raises(ServiceExecutionRecoveryError, match="CANCEL_MANIFEST_CONFLICT"):
        reopened.prepare_cancel(
            namespace,
            cancel_id="cancel.intent-1",
            target_intent_id=_INTENT,
            provider_order_id="provider-order-changed",
            metadata_version="metadata-v1",
        )
    reopened.close()


def test_snapshot_is_restore_only_and_filters_to_the_current_manifest(tmp_path) -> None:
    path = tmp_path / "recovery.sqlite3"
    namespace = _namespace()
    journal = ServiceExecutionRecoveryJournal(path)
    fingerprint = journal.prepare_intent(
        namespace, intent_id=_INTENT, submit_payload=_submit_payload()
    )
    snapshot = _snapshot(
        [
            _snapshot_order(_INTENT, fingerprint),
            _snapshot_order("older-run-intent", _digest("older-payload"), sequence=8),
        ]
    )

    assert journal.install_snapshot(namespace, snapshot) is True
    assert journal.install_snapshot(namespace, snapshot) is False
    matched = journal.snapshot_orders(namespace)
    all_rows = journal.snapshot_orders(namespace, matched_only=False)
    assert [row["intent_id"] for row in matched] == [_INTENT]
    assert {row["intent_id"] for row in all_rows} == {_INTENT, "older-run-intent"}
    assert journal.cursor(namespace)["event_cursor"] == 10
    assert journal.claim_pending_callbacks(namespace) == ()
    assert journal.event_projection(namespace, _INTENT) is None
    journal.close()


def test_snapshot_preserves_negative_cumulative_commission_rebate(tmp_path) -> None:
    namespace = _namespace()
    journal = ServiceExecutionRecoveryJournal(tmp_path / "recovery.sqlite3")
    fingerprint = journal.prepare_intent(
        namespace, intent_id=_INTENT, submit_payload=_submit_payload()
    )
    order = _snapshot_order(_INTENT, fingerprint)
    order["cumulative_commission"] = "-0.01"

    assert journal.install_snapshot(namespace, _snapshot([order])) is True
    assert journal.snapshot_orders(namespace)[0]["cumulative_commission"] == "-0.01"
    journal.close()


def test_recovery_views_require_strategy_owner_kind_not_legacy_view_name(tmp_path) -> None:
    namespace = _namespace()
    journal = ServiceExecutionRecoveryJournal(tmp_path / "recovery.sqlite3")
    fingerprint = journal.prepare_intent(
        namespace, intent_id=_INTENT, submit_payload=_submit_payload()
    )

    legacy_named_snapshot = _snapshot([_snapshot_order(_INTENT, fingerprint)])
    legacy_named_snapshot["coverage"]["owner_kind"] = "OWNER_BOOK"
    with pytest.raises(
        ServiceExecutionRecoveryError,
        match="RECOVERY_SNAPSHOT_NOT_COMPLETE_STRATEGY_SCOPE",
    ):
        journal.install_snapshot(namespace, legacy_named_snapshot)

    journal.install_snapshot(namespace, _snapshot([_snapshot_order(_INTENT, fingerprint)]))
    legacy_named_page = _page(10, 11, 11, [_event(_INTENT, fingerprint, 11)], has_more=False)
    legacy_named_page["coverage"]["owner_kind"] = "OWNER_BOOK"
    with pytest.raises(ServiceExecutionRecoveryError, match="RECOVERY_EVENT_PAGE_INCOMPLETE"):
        journal.apply_events_page(namespace, legacy_named_page)
    assert journal.cursor(namespace)["event_cursor"] == 10
    assert journal.event_projection(namespace, _INTENT) is None
    assert journal.claim_pending_callbacks(namespace) == ()
    journal.close()


def test_recovery_views_reject_unknown_top_level_fields_and_boolean_version(tmp_path) -> None:
    namespace = _namespace()
    journal = ServiceExecutionRecoveryJournal(tmp_path / "recovery.sqlite3")
    fingerprint = journal.prepare_intent(
        namespace, intent_id=_INTENT, submit_payload=_submit_payload()
    )

    extra_snapshot_field = _snapshot([_snapshot_order(_INTENT, fingerprint)])
    extra_snapshot_field["unprojected_payload"] = {"permit_reference": "private"}
    with pytest.raises(ServiceExecutionRecoveryError, match="INVALID_RECOVERY_SNAPSHOT"):
        journal.install_snapshot(namespace, extra_snapshot_field)
    boolean_snapshot_version = _snapshot([_snapshot_order(_INTENT, fingerprint)])
    boolean_snapshot_version["version"] = True
    with pytest.raises(ServiceExecutionRecoveryError, match="INVALID_RECOVERY_SNAPSHOT"):
        journal.install_snapshot(namespace, boolean_snapshot_version)

    journal.install_snapshot(namespace, _snapshot([_snapshot_order(_INTENT, fingerprint)]))
    extra_page_field = _page(10, 11, 11, [_event(_INTENT, fingerprint, 11)], has_more=False)
    extra_page_field["unprojected_payload"] = {"permit_reference": "private"}
    with pytest.raises(ServiceExecutionRecoveryError, match="INVALID_RECOVERY_EVENT_PAGE"):
        journal.apply_events_page(namespace, extra_page_field)
    boolean_page_version = _page(10, 11, 11, [_event(_INTENT, fingerprint, 11)], has_more=False)
    boolean_page_version["version"] = True
    with pytest.raises(ServiceExecutionRecoveryError, match="INVALID_RECOVERY_EVENT_PAGE"):
        journal.apply_events_page(namespace, boolean_page_version)

    assert journal.cursor(namespace)["event_cursor"] == 10
    assert journal.event_projection(namespace, _INTENT) is None
    assert journal.claim_pending_callbacks(namespace) == ()
    journal.close()


def test_event_page_requires_its_pinned_source_and_freshness_claim(tmp_path) -> None:
    namespace = _namespace()
    journal = ServiceExecutionRecoveryJournal(tmp_path / "recovery.sqlite3")
    fingerprint = journal.prepare_intent(
        namespace, intent_id=_INTENT, submit_payload=_submit_payload()
    )
    journal.install_snapshot(namespace, _snapshot([_snapshot_order(_INTENT, fingerprint)]))

    for field, value in (
        ("source", "UNVERIFIED_SOURCE"),
        ("freshness", "PROVIDER_LIVE"),
    ):
        bad_page = _page(10, 11, 11, [_event(_INTENT, fingerprint, 11)], has_more=False)
        bad_page["coverage"][field] = value
        with pytest.raises(ServiceExecutionRecoveryError, match="RECOVERY_EVENT_PAGE_INCOMPLETE"):
            journal.apply_events_page(namespace, bad_page)

    assert journal.cursor(namespace)["event_cursor"] == 10
    assert journal.event_projection(namespace, _INTENT) is None
    assert journal.claim_pending_callbacks(namespace) == ()
    journal.close()


@pytest.mark.parametrize(
    ("event_type", "state"),
    (
        ("dispatch_claimed", "FILLED"),
        ("provider_observation", "UNKNOWN"),
        ("cancelled_by_cancel_intent", "REJECTED"),
    ),
)
def test_event_page_rejects_states_not_allowed_for_the_event_type(
    tmp_path,
    event_type: str,
    state: str,
) -> None:
    namespace = _namespace()
    journal = ServiceExecutionRecoveryJournal(tmp_path / "recovery.sqlite3")
    fingerprint = journal.prepare_intent(
        namespace, intent_id=_INTENT, submit_payload=_submit_payload()
    )
    journal.install_snapshot(namespace, _snapshot([_snapshot_order(_INTENT, fingerprint)]))
    event = _event(_INTENT, fingerprint, 11, event_type=event_type)
    event["state"] = state

    with pytest.raises(ServiceExecutionRecoveryError, match="RECOVERY_EVENT_STATE_MISMATCH"):
        journal.apply_events_page(namespace, _page(10, 11, 11, [event], has_more=False))

    assert journal.cursor(namespace)["event_cursor"] == 10
    assert journal.event_projection(namespace, _INTENT) is None
    assert journal.claim_pending_callbacks(namespace) == ()
    journal.close()


@pytest.mark.parametrize(
    ("event_type", "source"),
    (
        ("provider_observation", "reconcile"),
        ("reconciled_observation", "provider"),
    ),
)
def test_event_page_rejects_observation_source_that_disagrees_with_type(
    tmp_path,
    event_type: str,
    source: str,
) -> None:
    namespace = _namespace()
    journal = ServiceExecutionRecoveryJournal(tmp_path / "recovery.sqlite3")
    fingerprint = journal.prepare_intent(
        namespace, intent_id=_INTENT, submit_payload=_submit_payload()
    )
    journal.install_snapshot(namespace, _snapshot([_snapshot_order(_INTENT, fingerprint)]))
    event = _event(_INTENT, fingerprint, 11, event_type=event_type)
    event["details"]["source"] = source

    with pytest.raises(ServiceExecutionRecoveryError, match="INVALID_RECOVERY_EVENT_DETAILS"):
        journal.apply_events_page(namespace, _page(10, 11, 11, [event], has_more=False))

    assert journal.cursor(namespace)["event_cursor"] == 10
    assert journal.event_projection(namespace, _INTENT) is None
    assert journal.claim_pending_callbacks(namespace) == ()
    journal.close()


def test_event_page_rejects_unsanitized_reason_code_before_commit(tmp_path) -> None:
    namespace = _namespace()
    journal = ServiceExecutionRecoveryJournal(tmp_path / "recovery.sqlite3")
    fingerprint = journal.prepare_intent(
        namespace, intent_id=_INTENT, submit_payload=_submit_payload()
    )
    journal.install_snapshot(namespace, _snapshot([_snapshot_order(_INTENT, fingerprint)]))
    event = _event(_INTENT, fingerprint, 11)
    event["details"]["reason_code"] = "provider order timed out"

    with pytest.raises(ServiceExecutionRecoveryError, match="INVALID_RECOVERY_EVENT_DETAILS"):
        journal.apply_events_page(namespace, _page(10, 11, 11, [event], has_more=False))

    assert journal.cursor(namespace)["event_cursor"] == 10
    assert journal.event_projection(namespace, _INTENT) is None
    assert journal.claim_pending_callbacks(namespace) == ()
    journal.close()


def test_event_page_rejects_currency_without_commission_before_commit(tmp_path) -> None:
    namespace = _namespace()
    journal = ServiceExecutionRecoveryJournal(tmp_path / "recovery.sqlite3")
    fingerprint = journal.prepare_intent(
        namespace, intent_id=_INTENT, submit_payload=_submit_payload()
    )
    journal.install_snapshot(namespace, _snapshot([_snapshot_order(_INTENT, fingerprint)]))
    event = _event(_INTENT, fingerprint, 11)
    event["details"]["cumulative_commission"] = None

    with pytest.raises(ServiceExecutionRecoveryError, match="INVALID_RECOVERY_EVENT_DETAILS"):
        journal.apply_events_page(namespace, _page(10, 11, 11, [event], has_more=False))

    assert journal.cursor(namespace)["event_cursor"] == 10
    assert journal.event_projection(namespace, _INTENT) is None
    assert journal.claim_pending_callbacks(namespace) == ()
    journal.close()


def test_event_page_preserves_negative_cumulative_commission_rebate(tmp_path) -> None:
    namespace = _namespace()
    journal = ServiceExecutionRecoveryJournal(tmp_path / "recovery.sqlite3")
    fingerprint = journal.prepare_intent(
        namespace, intent_id=_INTENT, submit_payload=_submit_payload()
    )
    journal.install_snapshot(namespace, _snapshot([_snapshot_order(_INTENT, fingerprint)]))
    event = _event(_INTENT, fingerprint, 11)
    event["details"]["cumulative_commission"] = "-0.01"

    assert journal.apply_events_page(namespace, _page(10, 11, 11, [event], has_more=False)) is True
    projection = journal.event_projection(namespace, _INTENT)
    assert projection["event"]["details"]["cumulative_commission"] == "-0.01"
    pending = journal.claim_pending_callbacks(namespace)
    assert len(pending) == 1
    assert pending[0].event["details"]["cumulative_commission"] == "-0.01"
    journal.close()


def test_event_page_rejects_noncanonical_decimal_before_commit(tmp_path) -> None:
    namespace = _namespace()
    journal = ServiceExecutionRecoveryJournal(tmp_path / "recovery.sqlite3")
    fingerprint = journal.prepare_intent(
        namespace, intent_id=_INTENT, submit_payload=_submit_payload()
    )
    journal.install_snapshot(namespace, _snapshot([_snapshot_order(_INTENT, fingerprint)]))
    event = _event(_INTENT, fingerprint, 11)
    event["details"]["cumulative_commission"] = "1e-2"

    with pytest.raises(ServiceExecutionRecoveryError, match="INVALID_RECOVERY_DECIMAL"):
        journal.apply_events_page(namespace, _page(10, 11, 11, [event], has_more=False))

    assert journal.cursor(namespace)["event_cursor"] == 10
    assert journal.event_projection(namespace, _INTENT) is None
    assert journal.claim_pending_callbacks(namespace) == ()
    journal.close()


def test_snapshot_requires_a_real_generation_and_consistent_order_sequences(tmp_path) -> None:
    namespace = _namespace()
    journal = ServiceExecutionRecoveryJournal(tmp_path / "recovery.sqlite3")
    fingerprint = journal.prepare_intent(
        namespace, intent_id=_INTENT, submit_payload=_submit_payload()
    )

    wrong_generation = _snapshot([_snapshot_order(_INTENT, fingerprint)])
    wrong_generation["coverage"]["journal_generation"] = "generation-a"
    with pytest.raises(ServiceExecutionRecoveryError, match="INVALID_RECOVERY_COVERAGE"):
        journal.install_snapshot(namespace, wrong_generation)

    no_source = _snapshot_order(_INTENT, fingerprint, sequence=0)
    with pytest.raises(ServiceExecutionRecoveryError, match="INVALID_RECOVERY_ORDER"):
        journal.install_snapshot(namespace, _snapshot([no_source]))

    inverted_observation = _snapshot_order(_INTENT, fingerprint, sequence=8)
    inverted_observation["latest_observation_sequence"] = 9
    inverted_observation["latest_observation_event_id"] = f"{9:032x}"
    with pytest.raises(ServiceExecutionRecoveryError, match="INVALID_RECOVERY_ORDER"):
        journal.install_snapshot(namespace, _snapshot([inverted_observation]))

    assert journal.snapshot_orders(namespace, matched_only=False) == ()
    journal.close()


def test_snapshot_requires_hex_source_event_identity(tmp_path) -> None:
    namespace = _namespace()
    journal = ServiceExecutionRecoveryJournal(tmp_path / "recovery.sqlite3")
    fingerprint = journal.prepare_intent(
        namespace, intent_id=_INTENT, submit_payload=_submit_payload()
    )
    order = _snapshot_order(_INTENT, fingerprint)
    order["latest_source_event_id"] = "source-event-10"

    with pytest.raises(ServiceExecutionRecoveryError, match="INVALID_RECOVERY_ORDER"):
        journal.install_snapshot(namespace, _snapshot([order]))

    assert journal.snapshot_orders(namespace, matched_only=False) == ()
    journal.close()


def test_event_receipt_projection_cursor_and_callback_pending_commit_together(tmp_path) -> None:
    path = tmp_path / "recovery.sqlite3"
    namespace = _namespace()
    journal = ServiceExecutionRecoveryJournal(path)
    fingerprint = journal.prepare_intent(
        namespace, intent_id=_INTENT, submit_payload=_submit_payload()
    )
    journal.install_snapshot(namespace, _snapshot([_snapshot_order(_INTENT, fingerprint)]))
    own_event = _event(_INTENT, fingerprint, 11)
    old_run_event = _event("older-run-intent", _digest("older-payload"), 12)
    page_one = _page(10, 11, 12, [own_event], has_more=True)
    page_two = _page(11, 12, 12, [old_run_event], has_more=False)

    assert journal.apply_events_page(namespace, page_one) is True
    assert journal.cursor(namespace)["event_cursor"] == 11
    own_projection = journal.event_projection(namespace, _INTENT)
    assert own_projection["sequence"] == 11
    assert journal.event_projection(namespace, "older-run-intent") is None
    journal.close()

    reopened = ServiceExecutionRecoveryJournal(path)
    # The page commit survived reopening; retrying its exact bytes cannot
    # reapply the projection or create another callback receipt.
    assert reopened.apply_events_page(namespace, page_one) is False
    assert reopened.apply_events_page(namespace, page_two) is True
    assert reopened.cursor(namespace)["event_cursor"] == 12
    assert reopened.event_projection(namespace, _INTENT) == own_projection

    deliveries: list[ServiceExecutionRecoveryCallback] = []

    def _crash_after_commit(item: ServiceExecutionRecoveryCallback) -> None:
        deliveries.append(item)
        raise RuntimeError("synthetic callback interruption")

    with pytest.raises(RuntimeError, match="synthetic callback interruption"):
        reopened.deliver_pending_callbacks(namespace, _crash_after_commit)
    first_delivery = tuple(deliveries)
    assert len(first_delivery) == 1
    assert first_delivery[0].intent_id == _INTENT
    assert first_delivery[0].delivery_attempt == 1
    assert first_delivery[0].event["event_id"] == f"{11:032x}"
    reopened.close()

    after_callback_crash = ServiceExecutionRecoveryJournal(path)
    retry_delivery = after_callback_crash.claim_pending_callbacks(namespace)
    assert len(retry_delivery) == 1
    assert retry_delivery[0].receipt_id == first_delivery[0].receipt_id
    assert retry_delivery[0].delivery_attempt == 2
    assert after_callback_crash.event_projection(namespace, _INTENT) == own_projection
    after_callback_crash.acknowledge_callback(namespace, retry_delivery[0].receipt_id)
    assert after_callback_crash.claim_pending_callbacks(namespace) == ()

    delivered_after_retry: list[ServiceExecutionRecoveryCallback] = []
    assert (
        after_callback_crash.deliver_pending_callbacks(namespace, delivered_after_retry.append) == 0
    )
    assert delivered_after_retry == []
    after_callback_crash.close()


def test_unknown_or_wrong_cut_page_does_not_advance_durable_cursor(tmp_path) -> None:
    namespace = _namespace()
    journal = ServiceExecutionRecoveryJournal(tmp_path / "recovery.sqlite3")
    fingerprint = journal.prepare_intent(
        namespace, intent_id=_INTENT, submit_payload=_submit_payload()
    )
    journal.install_snapshot(namespace, _snapshot([_snapshot_order(_INTENT, fingerprint)]))
    unknown = _event(_INTENT, fingerprint, 11, event_type="future_unknown_event")
    with pytest.raises(ServiceExecutionRecoveryError, match="RECOVERY_EVENT_TYPE_UNSUPPORTED"):
        journal.apply_events_page(namespace, _page(10, 11, 11, [unknown], has_more=False))
    changed_cut = _page(10, 11, 11, [_event(_INTENT, fingerprint, 11)], has_more=False)
    changed_cut["coverage"]["journal_generation"] = "abcdef0123456789abcdef0123456789"
    changed_cut["events"][0]["journal_generation"] = "abcdef0123456789abcdef0123456789"
    with pytest.raises(ServiceExecutionRecoveryError, match="RECOVERY_PAGE_CUT_CHANGED"):
        journal.apply_events_page(namespace, changed_cut)
    assert journal.cursor(namespace)["event_cursor"] == 10
    assert journal.event_projection(namespace, _INTENT) is None
    assert journal.claim_pending_callbacks(namespace) == ()
    journal.close()


def test_quiet_event_poll_at_the_same_global_cut_is_repeatable(tmp_path) -> None:
    namespace = _namespace()
    journal = ServiceExecutionRecoveryJournal(tmp_path / "recovery.sqlite3")
    fingerprint = journal.prepare_intent(
        namespace, intent_id=_INTENT, submit_payload=_submit_payload()
    )
    journal.install_snapshot(namespace, _snapshot([_snapshot_order(_INTENT, fingerprint)]))
    empty = _page(10, 10, 10, [], has_more=False)

    assert journal.apply_events_page(namespace, empty) is False
    assert journal.apply_events_page(namespace, empty) is False
    assert journal.cursor(namespace)["event_cursor"] == 10
    assert journal.event_projection(namespace, _INTENT) is None
    journal.close()


def test_adapter_pulls_snapshot_pages_and_delivers_only_committed_callbacks(tmp_path) -> None:
    from backtrader.stores.service_execution_adapter import ServiceExecutionAdapter

    namespace = _namespace()
    journal = ServiceExecutionRecoveryJournal(tmp_path / "recovery.sqlite3")
    fingerprint = journal.prepare_intent(
        namespace, intent_id=_INTENT, submit_payload=_submit_payload()
    )
    snapshot = _snapshot([_snapshot_order(_INTENT, fingerprint)])
    own_event = _event(_INTENT, fingerprint, 11)
    next_event = _event(_INTENT, fingerprint, 12, event_type="reconciled_observation")
    pages = [
        _page(10, 11, 12, [own_event], has_more=True),
        _page(11, 12, 12, [next_event], has_more=False),
        _page(12, 12, 12, [], has_more=False),
    ]
    calls = []

    class _RecoveryClient:
        def submit(self, **_kwargs):
            raise AssertionError("the recovery pull must not submit an intent")

        def cancel(self, **_kwargs):
            raise AssertionError("the recovery pull must not cancel an intent")

        def query(self, *_args, **_kwargs):
            raise AssertionError("the recovery pull must not query per-order records")

        def query_recovery_snapshot(self):
            return snapshot

        def query_recovery_events_after(self, **kwargs):
            calls.append(kwargs)
            return pages.pop(0)

    adapter = ServiceExecutionAdapter(_RecoveryClient(), recovery_journal=journal)
    adapter.bind_recovery_namespace(namespace)

    initialized = adapter.initialize_recovery(page_limit=2)
    assert initialized["snapshot_changed"] is True
    assert initialized["pages_applied"] == 2
    assert initialized["event_cursor"] == 12
    assert calls[:2] == [
        {
            "after_sequence": 10,
            "expected_journal_generation": _GENERATION,
            "expected_directory_revision": _DIRECTORY,
            "limit": 2,
        },
        {
            "after_sequence": 11,
            "expected_journal_generation": _GENERATION,
            "expected_directory_revision": _DIRECTORY,
            "limit": 2,
        },
    ]
    assert journal.event_projection(namespace, _INTENT)["sequence"] == 12

    delivered: list[ServiceExecutionRecoveryCallback] = []
    refreshed = adapter.refresh_recovery_events(
        callback=delivered.append,
        page_limit=2,
    )
    assert refreshed["pages_applied"] == 0
    assert refreshed["callbacks_delivered"] == 2
    assert [item.sequence for item in delivered] == [11, 12]
    assert [item.delivery_attempt for item in delivered] == [1, 1]
    assert journal.claim_pending_callbacks(namespace) == ()
    journal.close()


def test_event_page_rejects_private_or_unrecognized_details_before_commit(tmp_path) -> None:
    namespace = _namespace()
    journal = ServiceExecutionRecoveryJournal(tmp_path / "recovery.sqlite3")
    fingerprint = journal.prepare_intent(
        namespace, intent_id=_INTENT, submit_payload=_submit_payload()
    )
    journal.install_snapshot(namespace, _snapshot([_snapshot_order(_INTENT, fingerprint)]))
    event = _event(_INTENT, fingerprint, 11)
    event["details"]["permit_reference"] = "not-for-the-client"
    with pytest.raises(ServiceExecutionRecoveryError, match="INVALID_RECOVERY_EVENT_DETAILS"):
        journal.apply_events_page(namespace, _page(10, 11, 11, [event], has_more=False))
    assert journal.cursor(namespace)["event_cursor"] == 10
    assert journal.event_projection(namespace, _INTENT) is None
    assert journal.claim_pending_callbacks(namespace) == ()
    journal.close()


def test_event_page_requires_hex_event_identity_before_commit(tmp_path) -> None:
    namespace = _namespace()
    journal = ServiceExecutionRecoveryJournal(tmp_path / "recovery.sqlite3")
    fingerprint = journal.prepare_intent(
        namespace, intent_id=_INTENT, submit_payload=_submit_payload()
    )
    journal.install_snapshot(namespace, _snapshot([_snapshot_order(_INTENT, fingerprint)]))
    event = _event(_INTENT, fingerprint, 11, event_id="event-11")

    with pytest.raises(ServiceExecutionRecoveryError, match="INVALID_RECOVERY_EVENT"):
        journal.apply_events_page(namespace, _page(10, 11, 11, [event], has_more=False))

    assert journal.cursor(namespace)["event_cursor"] == 10
    assert journal.event_projection(namespace, _INTENT) is None
    assert journal.claim_pending_callbacks(namespace) == ()
    journal.close()
