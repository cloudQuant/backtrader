"""Atomic journal recovery for a CANCEL interrupted during dispatch."""

from __future__ import annotations

from dataclasses import replace

import pytest

from backtrader.stores.execution_decision_journal import (
    ExecutionDecisionJournal,
    ExecutionDecisionJournalError,
    ExecutionDecisionKey,
    ExecutionIntentKey,
)


def _make_dispatching_cancel(journal, *, instrument="IF2701"):
    parent_key = ExecutionIntentKey(
        action="SUBMIT",
        instrument=instrument,
        side="BUY",
        position_effect="OPEN",
        leg=0,
    )
    parent_identity = {
        "backtrader_order_ref": 11,
        "order_ref": "501",
        "order_sys_id": "sys-501",
        "front_id": 7,
        "session_id": 9,
        "instrument_id": instrument,
        "exchange_id": "CFFEX",
        "account_fingerprint": "account-fingerprint-1",
        "connection_generation": 3,
        "trading_day": "20261024",
        "operation": "insert",
    }
    parent_decision = journal.record_decision(
        ExecutionDecisionKey(
            account_scope="account-a",
            strategy_scope="strategy-a",
            logical_run_id="run-parent",
            cohort_id="cohort-a",
            close_time="2026-10-24T10:00:00Z",
            decision_kind="submit",
        ),
        {"signal": "open"},
        intent_keys=(parent_key,),
    )
    parent = journal.prepare_intent(
        parent_decision.decision_id,
        parent_key,
        {
            "quantity": "4",
            "instrument": instrument,
            "exchange": "CFFEX",
            "side": "BUY",
            "position_effect": "OPEN",
        },
        original_identity=parent_identity,
    )
    assert journal.claim_dispatch(parent.intent_id) is not None
    parent = journal.record_dispatch_result(
        parent.intent_id,
        state="KNOWN",
        provider_identity={
            "order_ref": "501",
            "order_sys_id": "sys-501",
            "instrument_id": instrument,
            "exchange_id": "CFFEX",
            "status": "ACCEPTED",
        },
        outcome_code="accepted",
    )

    cancel_key = ExecutionIntentKey(
        action="CANCEL",
        instrument=instrument,
        side="BUY",
        position_effect="OPEN",
        leg=0,
    )
    cancel_economics = {
        "target_order_ref": "501",
        "instrument": instrument,
        "exchange": "CFFEX",
        "side": "BUY",
        "position_effect": "OPEN",
    }
    cancel_decision = journal.record_decision(
        ExecutionDecisionKey(
            account_scope="account-a",
            strategy_scope="strategy-a",
            logical_run_id="run-cancel",
            cohort_id="cohort-a",
            close_time="2026-10-24T10:01:00Z",
            decision_kind="cancel",
        ),
        cancel_economics,
        intent_keys=(cancel_key,),
    )
    cancel_identity = {
        **parent_identity,
        "backtrader_order_ref": parent_identity["backtrader_order_ref"],
        "owner_intent_id": parent.intent_id,
        "operation": "cancel",
    }
    cancel = journal.prepare_intent(
        cancel_decision.decision_id,
        cancel_key,
        cancel_economics,
        original_identity=cancel_identity,
        owner_intent_id=parent.intent_id,
    )
    assert journal.claim_dispatch(cancel.intent_id) is not None
    return parent, cancel


def _recovery_args(parent, cancel, *, position_flat=False):
    query_id = "terminal-observation-1"
    parent_reconciliation_id = "parent-terminal-reconciliation-1"
    cancel_reconciliation_id = "cancel-terminal-reconciliation-1"
    snapshot_id = "account-snapshot-1"
    position_snapshot_id = "position-snapshot-1"
    parent_provider_identity = {
        "evidence_kind": "complete_orders_query_observation",
        "observation_id": query_id,
        "query_set_id": "query-set-1",
        "snapshot_id": snapshot_id,
        "position_snapshot_id": position_snapshot_id,
        "parent_intent_id": parent.intent_id,
        "cancel_intent_id": cancel.intent_id,
        "cancel_reconciliation_id": cancel_reconciliation_id,
    }
    cancel_provider_identity = {
        "evidence_kind": "complete_orders_query_cancel_dispatching_terminal",
        "observation_id": query_id,
        "query_set_id": "query-set-1",
        "snapshot_id": snapshot_id,
        "position_snapshot_id": position_snapshot_id,
        "parent_intent_id": parent.intent_id,
        "cancel_intent_id": cancel.intent_id,
        "parent_reconciliation_id": parent_reconciliation_id,
        "cancel_reconciliation_id": cancel_reconciliation_id,
    }
    return {
        "parent_intent_id": parent.intent_id,
        "cancel_intent_id": cancel.intent_id,
        "parent_reconciliation_id": parent_reconciliation_id,
        "cancel_reconciliation_id": cancel_reconciliation_id,
        "query_id": query_id,
        "parent_provider_identity": parent_provider_identity,
        "cancel_provider_identity": cancel_provider_identity,
        "terminal_state": "CANCELLED",
        "terminal_event_id": query_id,
        "position_snapshot_id": position_snapshot_id,
        "position_flat": position_flat,
        "expected_parent_original_identity": dict(parent.original_identity),
        "expected_cancel_original_identity": dict(cancel.original_identity),
    }


def _recover(journal, args):
    return journal.record_dispatching_cancel_terminal(**args)


def _settlement_record_count(journal):
    return journal._connection.execute(
        """SELECT record_count FROM execution_durable_capacity_usage
           WHERE capacity_class='SETTLEMENT'"""
    ).fetchone()[0]


def test_dispatching_cancel_terminal_is_atomic_and_exactly_replayable(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "dispatching-cancel.sqlite3")
    try:
        parent, cancel = _make_dispatching_cancel(journal)
        owner = journal.active_instrument_owner("account-a", cancel.key.instrument)
        assert owner is not None
        assert (owner.intent_id, owner.cancel_intent_id) == (parent.intent_id, cancel.intent_id)

        before_records = _settlement_record_count(journal)
        args = _recovery_args(parent, cancel, position_flat=False)
        child_proof, parent_proof, resolution = _recover(journal, args)

        assert child_proof.intent_id == cancel.intent_id
        assert child_proof.original_identity == cancel.original_identity
        assert child_proof.state == "KNOWN"
        assert child_proof.terminal_state == "CANCELLED"
        assert child_proof.position_flat is False
        assert parent_proof.intent_id == parent.intent_id
        assert parent_proof.original_identity == parent.original_identity
        assert parent_proof.terminal_state == "CANCELLED"
        assert parent_proof.position_flat is False
        assert resolution.intent_id == parent.intent_id
        assert resolution.reconciliation_id == parent_proof.reconciliation_id
        assert resolution.position_flat is False

        recovered_cancel = journal.intent(cancel.intent_id)
        recovered_parent = journal.intent(parent.intent_id)
        assert recovered_cancel is not None
        assert recovered_cancel.state == "KNOWN"
        assert recovered_cancel.dispatch_state is None
        assert recovered_cancel.provider_identity is None
        assert recovered_cancel.outcome_code is None
        assert (
            journal._connection.execute(
                "SELECT dispatch_result_json FROM execution_decision_intents WHERE intent_id=?",
                (cancel.intent_id,),
            ).fetchone()[0]
            is None
        )
        assert recovered_parent == parent
        assert recovered_parent.dispatch_state == "KNOWN"
        assert recovered_parent.provider_identity == parent.provider_identity
        assert recovered_parent.outcome_code == parent.outcome_code
        assert journal.active_instrument_owner("account-a", cancel.key.instrument) is None
        assert _settlement_record_count(journal) == before_records + 3

        # A later order may own the pending slot. Exact journal replay must
        # return the original proof without clearing that newer owner.
        next_key = ExecutionIntentKey(
            action="SUBMIT",
            instrument=cancel.key.instrument,
            side="SELL",
            position_effect="CLOSE",
            leg=0,
        )
        next_decision = journal.record_decision(
            ExecutionDecisionKey(
                account_scope="account-a",
                strategy_scope="strategy-a",
                logical_run_id="run-next",
                cohort_id="cohort-a",
                close_time="2026-10-24T10:02:00Z",
                decision_kind="submit-close",
            ),
            {"signal": "close"},
            intent_keys=(next_key,),
        )
        next_intent = journal.prepare_intent(
            next_decision.decision_id,
            next_key,
            {"quantity": "1", "instrument": cancel.key.instrument, "exchange": "CFFEX"},
            original_identity={"backtrader_order_ref": 13},
        )
        count_before_replay = _settlement_record_count(journal)
        replay = _recover(journal, args)
        assert replay == (child_proof, parent_proof, resolution)
        assert _settlement_record_count(journal) == count_before_replay
        owner_after_replay = journal.active_instrument_owner("account-a", cancel.key.instrument)
        assert owner_after_replay is not None
        assert owner_after_replay.intent_id == next_intent.intent_id
    finally:
        journal.close()


def test_dispatching_cancel_terminal_rejects_identity_and_owner_mismatches(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "dispatching-cancel-mismatch.sqlite3")
    try:
        parent, cancel = _make_dispatching_cancel(journal)
        wrong_identity = _recovery_args(parent, cancel)
        wrong_identity["expected_cancel_original_identity"] = {
            **wrong_identity["expected_cancel_original_identity"],
            "order_ref": "different-order",
        }
        with pytest.raises(
            ExecutionDecisionJournalError,
            match="DISPATCHING_CANCEL_EVIDENCE_MISMATCH",
        ):
            _recover(journal, wrong_identity)

        with journal._transaction() as cursor:
            cursor.execute(
                """UPDATE execution_instrument_owners SET cancel_intent_id=NULL
                   WHERE account_scope='account-a' AND instrument=?""",
                (cancel.key.instrument,),
            )
        with pytest.raises(ExecutionDecisionJournalError, match="INSTRUMENT_OWNER_MISMATCH"):
            _recover(journal, _recovery_args(parent, cancel))

        assert journal.intent(cancel.intent_id).state == "DISPATCHING"
        assert journal.reconciliation("cancel-terminal-reconciliation-1") is None
        assert journal.reconciliation("parent-terminal-reconciliation-1") is None
        assert journal.instrument_resolution(parent.intent_id) is None
    finally:
        journal.close()


def test_dispatching_cancel_terminal_refuses_an_observed_cancel_result(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "dispatching-cancel-result.sqlite3")
    try:
        parent, cancel = _make_dispatching_cancel(journal)
        journal.record_dispatch_result(
            cancel.intent_id,
            state="UNKNOWN",
            provider_identity={"operation": "cancel", "status": "UNKNOWN"},
            outcome_code="connection_lost",
        )
        with pytest.raises(
            ExecutionDecisionJournalError,
            match="DISPATCHING_CANCEL_STATE_MISMATCH",
        ):
            _recover(journal, _recovery_args(parent, cancel))
        current = journal.intent(cancel.intent_id)
        assert current.state == "UNKNOWN"
        assert current.dispatch_state == "UNKNOWN"
        assert current.provider_identity["status"] == "UNKNOWN"
        owner = journal.active_instrument_owner("account-a", cancel.key.instrument)
        assert owner is not None and owner.cancel_intent_id == cancel.intent_id
    finally:
        journal.close()


@pytest.mark.parametrize("terminal_state", ["FILLED", "REJECTED"])
def test_dispatching_cancel_terminal_rejects_unmodeled_terminal_state(tmp_path, terminal_state):
    journal = ExecutionDecisionJournal(tmp_path / "dispatching-cancel-unmodeled-terminal.sqlite3")
    try:
        parent, cancel = _make_dispatching_cancel(journal)
        args = _recovery_args(parent, cancel)
        args["terminal_state"] = terminal_state
        before_records = _settlement_record_count(journal)

        with pytest.raises(ExecutionDecisionJournalError, match="INVALID_TERMINAL_STATE"):
            _recover(journal, args)

        assert journal._failed_closed is False
        assert journal.intent(cancel.intent_id).state == "DISPATCHING"
        assert _settlement_record_count(journal) == before_records
        assert journal.reconciliation(args["cancel_reconciliation_id"]) is None
        assert journal.reconciliation(args["parent_reconciliation_id"]) is None
        assert journal.instrument_resolution(parent.intent_id) is None
    finally:
        journal.close()


def test_dispatching_cancel_terminal_rejects_duplicate_reconciliation_ids(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "dispatching-cancel-duplicate-ids.sqlite3")
    try:
        parent, cancel = _make_dispatching_cancel(journal)
        args = _recovery_args(parent, cancel)
        args["cancel_reconciliation_id"] = args["parent_reconciliation_id"]
        before_records = _settlement_record_count(journal)

        with pytest.raises(
            ExecutionDecisionJournalError,
            match="DISPATCHING_CANCEL_RECONCILIATION_IDS_NOT_DISTINCT",
        ):
            _recover(journal, args)

        assert journal._failed_closed is False
        assert journal.intent(cancel.intent_id).state == "DISPATCHING"
        assert _settlement_record_count(journal) == before_records
        assert journal.reconciliation(args["parent_reconciliation_id"]) is None
        assert journal.instrument_resolution(parent.intent_id) is None
    finally:
        journal.close()


def test_dispatching_cancel_conflicting_replay_is_rejected_without_mutation(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "dispatching-cancel-conflict.sqlite3")
    try:
        parent, cancel = _make_dispatching_cancel(journal)
        args = _recovery_args(parent, cancel)
        original_result = _recover(journal, args)
        before_records = _settlement_record_count(journal)
        conflicting = _recovery_args(parent, cancel)
        conflicting["cancel_provider_identity"] = {
            **conflicting["cancel_provider_identity"],
            "diagnostic_generation": 2,
        }
        with pytest.raises(
            ExecutionDecisionJournalError,
            match="DISPATCHING_CANCEL_RECOVERY_CONFLICT",
        ):
            _recover(journal, conflicting)
        assert _settlement_record_count(journal) == before_records
        assert journal.reconciliation(original_result[0].reconciliation_id) == original_result[0]
        assert journal.reconciliation(original_result[1].reconciliation_id) == original_result[1]
        assert journal.instrument_resolution(parent.intent_id) == original_result[2]
    finally:
        journal.close()


def test_dispatching_cancel_capacity_failure_rolls_back_every_write(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "dispatching-cancel-capacity.sqlite3")
    try:
        parent, cancel = _make_dispatching_cancel(journal)
        before_records = _settlement_record_count(journal)
        journal.durable_capacity_limits = replace(
            journal.durable_capacity_limits,
            max_durable_settlement_records=before_records + 2,
        )
        args = _recovery_args(parent, cancel)
        with pytest.raises(
            ExecutionDecisionJournalError,
            match="DURABLE_SETTLEMENT_RECORDS_EXHAUSTED",
        ):
            _recover(journal, args)

        current = journal.intent(cancel.intent_id)
        assert current.state == "DISPATCHING"
        assert current.dispatch_state is None
        assert current.provider_identity is None
        assert current.outcome_code is None
        assert (
            journal._connection.execute(
                "SELECT dispatch_result_json FROM execution_decision_intents WHERE intent_id=?",
                (cancel.intent_id,),
            ).fetchone()[0]
            is None
        )
        owner = journal.active_instrument_owner("account-a", cancel.key.instrument)
        assert owner is not None and owner.cancel_intent_id == cancel.intent_id
        assert journal.reconciliation("cancel-terminal-reconciliation-1") is None
        assert journal.reconciliation("parent-terminal-reconciliation-1") is None
        assert journal.instrument_resolution(parent.intent_id) is None
        assert _settlement_record_count(journal) == before_records
        assert journal._failed_closed is False
    finally:
        journal.close()
