"""Bounded selection of dispatching-cancel Store-absence candidates."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import time

import pytest

from backtrader.stores.execution_decision_journal import (
    ExecutionDecisionJournal,
    _dispatching_cancel_absence_ack_ids,
)
from tests.unit.stores.test_execution_decision_journal_dispatching_cancel import (
    _make_dispatching_cancel,
    _recovery_args,
    _recover,
)


class _UniqueDecisionJournal:
    """Give each accepted fixture invocation its own immutable business keys."""

    def __init__(self, journal, ordinal):
        self._journal = journal
        self._ordinal = ordinal
        self._decision_number = 0

    def __getattr__(self, name):
        return getattr(self._journal, name)

    def record_decision(self, key, economic_payload, *, intent_keys=()):
        self._decision_number += 1
        suffix = f"{self._ordinal}-{self._decision_number}"
        if key.decision_kind == "cancel":
            economic_payload = dict(economic_payload)
            economic_payload["target_order_ref"] = str(500 + self._ordinal)
        unique_key = replace(
            key,
            logical_run_id=f"{key.logical_run_id}-{suffix}",
            cohort_id=f"{key.cohort_id}-{suffix}",
        )
        return self._journal.record_decision(
            unique_key,
            economic_payload,
            intent_keys=intent_keys,
        )

    def prepare_intent(
        self, decision_id, intent_key, economic_payload, *, original_identity, **kwargs
    ):
        if intent_key.action == "SUBMIT":
            order_ref = str(500 + self._ordinal)
            original_identity.update(
                backtrader_order_ref=100 + self._ordinal,
                order_ref=order_ref,
                order_sys_id=f"sys-{order_ref}",
            )
        return self._journal.prepare_intent(
            decision_id,
            intent_key,
            economic_payload,
            original_identity=original_identity,
            **kwargs,
        )

    def record_dispatch_result(self, intent_id, **kwargs):
        intent = self._journal.intent(intent_id)
        if intent is not None and intent.original_identity.get("operation") == "insert":
            provider_identity = dict(kwargs["provider_identity"])
            provider_identity.update(
                order_id=intent.original_identity["order_ref"],
                order_sys_id=intent.original_identity.get("order_sys_id"),
            )
            kwargs["provider_identity"] = provider_identity
        return self._journal.record_dispatch_result(intent_id, **kwargs)


def _append_cancel_cas(journal, ordinal):
    fixture = _UniqueDecisionJournal(journal, ordinal)
    instrument = f"IF{2700 + ordinal}"
    parent, cancel = _make_dispatching_cancel(fixture, instrument=instrument)
    args = _recovery_args(parent, cancel, position_flat=True)

    query_id = f"terminal-observation-{ordinal}"
    parent_reconciliation_id = f"parent-terminal-reconciliation-{ordinal}"
    cancel_reconciliation_id = f"cancel-terminal-reconciliation-{ordinal}"
    snapshot_id = f"account-snapshot-{ordinal}"
    position_snapshot_id = f"position-snapshot-{ordinal}"
    query_set_id = f"query-set-{ordinal}"
    args.update(
        query_id=query_id,
        parent_reconciliation_id=parent_reconciliation_id,
        cancel_reconciliation_id=cancel_reconciliation_id,
        terminal_event_id=query_id,
        position_snapshot_id=position_snapshot_id,
    )
    identity = parent.original_identity
    current_session = {
        "account_fingerprint": identity["account_fingerprint"],
        "connection_generation": identity["connection_generation"] + 1,
        "trading_day": identity["trading_day"],
        "front_id": identity["front_id"] + 1,
        "session_id": identity["session_id"] + 1,
        "read_only_ready": True,
    }
    common = {
        "cancel_recovery_kind": "dispatching_cancel",
        "parent_intent_id": parent.intent_id,
        "cancel_intent_id": cancel.intent_id,
        "parent_reconciliation_id": parent_reconciliation_id,
        "cancel_reconciliation_id": cancel_reconciliation_id,
        "observation_id": query_id,
        "query_set_id": query_set_id,
        "snapshot_id": snapshot_id,
        "connection_generation": current_session["connection_generation"],
        "account_fingerprint": identity["account_fingerprint"],
        "trading_day": identity["trading_day"],
        "order_ref": identity["order_ref"],
        "order_sys_id": identity["order_sys_id"],
        "instrument": identity["instrument_id"],
        "exchange": identity["exchange_id"],
        "front_id": identity["front_id"],
        "session_id": identity["session_id"],
        "terminal_status": "5",
        "terminal_state": "CANCELED",
        "volume_total_original": "4",
        "volume_traded": "0",
        "volume_total": "4",
        "current_session": current_session,
        "original_account_fingerprint": identity["account_fingerprint"],
        "original_connection_generation": identity["connection_generation"],
        "original_trading_day": identity["trading_day"],
        "original_order_ref": identity["order_ref"],
        "original_front_id": identity["front_id"],
        "original_session_id": identity["session_id"],
        "original_order_sys_id": identity["order_sys_id"],
        "matching_trade_count": 0,
        "matching_trade_volume": "0",
        "matching_trade_digest": hashlib.sha256(b"[]").hexdigest(),
        "broker_quantity": "0",
        "ctp_long_quantity": "0",
        "ctp_short_quantity": "0",
        "attributed_signed_quantity": "0",
        "position_book_owner_intent_id": None,
        "opening_fee_total": "0",
        "opening_fees_known": True,
        "position_snapshot_id": position_snapshot_id,
        "position_flat": True,
    }
    for provider in (args["parent_provider_identity"], args["cancel_provider_identity"]):
        provider.update(common)

    _recover(journal, args)
    return parent, cancel, args


def _record_store_absence_ack(journal, parent, cancel, args, mutate=None):
    acknowledgement_id, acknowledgement_query_id = _dispatching_cancel_absence_ack_ids(
        parent.intent_id,
        cancel.intent_id,
        args["parent_reconciliation_id"],
        args["cancel_reconciliation_id"],
    )
    original = dict(parent.original_identity)
    provider = {
        "evidence_kind": "LOCAL_STORE_ABSENCE",
        "cancel_recovery_kind": "dispatching_cancel_store_absence_ack",
        "store_assertion": "ALREADY_ABSENT",
        "parent_intent_id": parent.intent_id,
        "cancel_intent_id": cancel.intent_id,
        "parent_reconciliation_id": args["parent_reconciliation_id"],
        "cancel_reconciliation_id": args["cancel_reconciliation_id"],
        "cas_parent_reconciliation_id": args["parent_reconciliation_id"],
        "cas_cancel_reconciliation_id": args["cancel_reconciliation_id"],
        "acknowledgement_query_id": acknowledgement_query_id,
        "query_observation_id": f"store-absence-observation-{parent.intent_id}",
        "query_set_id": f"store-absence-query-set-{parent.intent_id}",
        "snapshot_id": f"store-absence-snapshot-{parent.intent_id}",
        "original_identity": original,
        "original_order_ref": original["order_ref"],
        "instrument": original["instrument_id"],
        "exchange": original["exchange_id"],
        "current_session": {
            "account_fingerprint": original["account_fingerprint"],
            "trading_day": original["trading_day"],
            "connection_generation": original["connection_generation"] + 1,
            "front_id": original["front_id"] + 1,
            "session_id": original["session_id"] + 1,
            "read_only_ready": True,
        },
    }
    if mutate is not None:
        mutate(provider)
    return journal.record_reconciliation(
        parent.intent_id,
        reconciliation_id=acknowledgement_id,
        query_id=acknowledgement_query_id,
        state="KNOWN",
        provider_identity=provider,
        outcome_code="LOCAL_STORE_ABSENCE",
    )


def _assert_only_candidate(page, parent, cancel, args):
    assert len(page.items) == 1
    candidate = page.items[0]
    assert candidate.parent_intent_id == parent.intent_id
    assert candidate.cancel_intent_id == cancel.intent_id
    assert candidate.parent_reconciliation_id == args["parent_reconciliation_id"]
    assert candidate.cancel_reconciliation_id == args["cancel_reconciliation_id"]


def test_acknowledged_history_is_filtered_before_candidate_limit(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "cancel-absence-page.sqlite3")
    try:
        for ordinal in range(1, 4):
            parent, cancel, args = _append_cancel_cas(journal, ordinal)
            _record_store_absence_ack(journal, parent, cancel, args)
            time.sleep(0.002)

        pending_parent, pending_cancel, pending_args = _append_cancel_cas(journal, 4)

        page = journal.dispatching_cancel_store_absence_candidates("account-a", limit=2)

        _assert_only_candidate(page, pending_parent, pending_cancel, pending_args)
        assert page.truncated is False
    finally:
        journal.close()


def test_all_acknowledged_history_is_not_reported_as_truncated(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "cancel-absence-all-acked.sqlite3")
    try:
        for ordinal in range(1, 4):
            parent, cancel, args = _append_cancel_cas(journal, ordinal)
            _record_store_absence_ack(journal, parent, cancel, args)
            time.sleep(0.002)

        page = journal.dispatching_cancel_store_absence_candidates("account-a", limit=2)

        assert page.items == ()
        assert page.truncated is False
    finally:
        journal.close()


@pytest.mark.parametrize(
    "mutation",
    [
        pytest.param(
            lambda provider: provider.update(cancel_intent_id="other-cancel"),
            id="wrong-child-binding",
        ),
        pytest.param(
            lambda provider: provider.pop("snapshot_id"),
            id="partial-ack-binding",
        ),
        pytest.param(
            lambda provider: provider["current_session"].update(connection_generation=True),
            id="malformed-boolean-generation",
        ),
    ],
)
def test_non_exact_acknowledgement_does_not_hide_pending_candidate(tmp_path, mutation):
    journal = ExecutionDecisionJournal(tmp_path / "cancel-absence-invalid-ack.sqlite3")
    try:
        parent, cancel, args = _append_cancel_cas(journal, 1)
        _record_store_absence_ack(journal, parent, cancel, args, mutate=mutation)

        page = journal.dispatching_cancel_store_absence_candidates("account-a", limit=1)

        _assert_only_candidate(page, parent, cancel, args)
        assert page.truncated is False
    finally:
        journal.close()
