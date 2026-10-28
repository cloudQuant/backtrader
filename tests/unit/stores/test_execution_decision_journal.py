"""Route-neutral durable decision and intent journal contracts."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from threading import Barrier, Event, RLock

import pytest

from backtrader.stores import execution_decision_journal as journal_module
from backtrader.stores.execution_decision_journal import (
    ExecutionFeePairCandidate,
    ExecutionDecisionJournal,
    ExecutionDecisionJournalError,
    ExecutionDecisionKey,
    ExecutionIntentKey,
    ExecutionSourceHighWaterRef,
    ExecutionSourceMemberReceipt,
)
from backtrader.stores.execution_durable_capacity import (
    read_durable_capacity_usage,
    track_durable_row_change,
)
from backtrader.stores.registered_sim import RegisteredSimOrderIdentityQueryReceipt
from backtrader.stores.factor_position_book import apply_factor_execution_fill


def _drop_v12_durable_capacity_tables(connection: sqlite3.Connection) -> None:
    """Restore a pre-v12 schema before exercising an older migration path."""

    # Test databases are made by downgrading a current journal; remove the
    # later v15/v16/v17 additions too so the fixture represents the requested
    # old schema instead of a corrupt user_version/table combination.
    _drop_v17_fee_pair_workflow_tables(connection)
    connection.execute(
        "DROP TABLE IF EXISTS execution_fee_pair_candidate_capacity_reservations"
    )
    connection.execute("DROP TABLE IF EXISTS execution_fee_pair_candidate_events")
    connection.execute("DROP TABLE IF EXISTS execution_fee_pair_candidates")
    connection.execute("DROP TABLE IF EXISTS execution_fee_pair_scope_events")
    connection.execute("DROP TABLE IF EXISTS execution_fee_pair_required_scopes")
    connection.execute("DROP TABLE IF EXISTS execution_durable_capacity_usage")
    connection.execute("DROP TABLE IF EXISTS execution_durable_capacity_limits")
    connection.execute("DROP TABLE IF EXISTS execution_run_loss_guards")
    connection.execute("DROP TABLE IF EXISTS execution_source_highwaters")
    connection.execute(
        "DROP TRIGGER IF EXISTS execution_known_ctp_order_sysid_binding_no_update"
    )
    connection.execute(
        "DROP TRIGGER IF EXISTS execution_known_ctp_order_sysid_binding_no_delete"
    )
    connection.execute("DROP TABLE IF EXISTS execution_known_ctp_order_sysid_bindings")
    connection.execute(
        "DROP TRIGGER IF EXISTS execution_registered_sim_cancel_dispatch_claim_no_update"
    )
    connection.execute(
        "DROP TRIGGER IF EXISTS execution_registered_sim_cancel_dispatch_claim_no_delete"
    )
    connection.execute(
        "DROP TABLE IF EXISTS execution_registered_sim_cancel_dispatch_claims"
    )
    connection.execute(
        "DROP TRIGGER IF EXISTS execution_registered_sim_cancel_dispatch_tombstone_no_update"
    )
    connection.execute(
        "DROP TRIGGER IF EXISTS execution_registered_sim_cancel_dispatch_tombstone_no_delete"
    )
    connection.execute(
        "DROP TABLE IF EXISTS execution_registered_sim_cancel_dispatch_tombstones"
    )


def _drop_v23_fee_pair_grid_single_row_objects(connection: sqlite3.Connection) -> None:
    """Restore the pre-v23 fee-pair schema before exercising older migrations."""

    amount_table = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' "
        "AND name='execution_fee_pair_amount_reservations'"
    ).fetchone()
    if amount_table is not None:
        if connection.execute(
            "SELECT COUNT(*) FROM execution_fee_pair_amount_reservations"
        ).fetchone()[0]:
            raise AssertionError("cannot downgrade a journal with v24 amount reservations")
        connection.execute(
            "DROP TRIGGER IF EXISTS execution_fee_pair_amount_reservation_no_update"
        )
        connection.execute(
            "DROP TRIGGER IF EXISTS execution_fee_pair_amount_reservation_no_delete"
        )
        connection.execute("DROP TABLE execution_fee_pair_amount_reservations")

    for trigger in (
        "execution_fee_pair_grid_single_row_tape_intent_no_update",
        "execution_fee_pair_grid_single_row_tape_intent_no_delete",
        "execution_fee_pair_legacy_unresolved_v23_no_update",
        "execution_fee_pair_legacy_unresolved_v23_no_delete",
    ):
        connection.execute("DROP TRIGGER IF EXISTS " + trigger)
    connection.execute("DROP INDEX IF EXISTS execution_fee_pair_grid_single_row_tape_position")
    connection.execute("DROP TABLE IF EXISTS execution_fee_pair_grid_single_row_tape_intents")
    connection.execute("DROP TABLE IF EXISTS execution_fee_pair_legacy_unresolved_v23")

    reservation_trigger = connection.execute(
        """SELECT 1 FROM sqlite_master
           WHERE type='trigger' AND name='execution_fee_pair_workflow_durable_reservation_state'"""
    ).fetchone()
    reservation_table = connection.execute(
        """SELECT 1 FROM sqlite_master
           WHERE type='table' AND name='execution_fee_pair_workflow_durable_reservations'"""
    ).fetchone()
    if reservation_trigger is not None:
        connection.execute(
            "DROP TRIGGER execution_fee_pair_workflow_durable_reservation_state"
        )
    if reservation_table is not None:
        connection.execute(journal_module._FEE_PAIR_WORKFLOW_DURABLE_RESERVATION_TRIGGER_SQL_V20)


def _drop_v17_fee_pair_workflow_tables(connection: sqlite3.Connection) -> None:
    """Remove all v17+ workflow objects from a historical-schema fixture."""

    _drop_v23_fee_pair_grid_single_row_objects(connection)
    # The fixture starts from today's schema, so remove the v19 settlement
    # ledger before lowering user_version. Historical v17/v18 databases never
    # contained this table or its append-only triggers.
    connection.execute(
        "DROP TABLE IF EXISTS execution_fee_pair_workflow_grid_settlements"
    )
    connection.execute(
        "DROP TABLE IF EXISTS execution_fee_pair_workflow_decision_reservations"
    )
    connection.execute(
        "DROP TABLE IF EXISTS execution_fee_pair_workflow_durable_reservations"
    )
    connection.execute("DROP TABLE IF EXISTS execution_fee_pair_workflow_events")
    connection.execute("DROP TABLE IF EXISTS execution_fee_pair_workflows")
    connection.execute(
        "DROP TRIGGER IF EXISTS execution_known_ctp_order_sysid_binding_no_update"
    )
    connection.execute(
        "DROP TRIGGER IF EXISTS execution_known_ctp_order_sysid_binding_no_delete"
    )
    connection.execute("DROP TABLE IF EXISTS execution_known_ctp_order_sysid_bindings")
    connection.execute(
        "DROP TRIGGER IF EXISTS execution_registered_sim_cancel_dispatch_claim_no_update"
    )
    connection.execute(
        "DROP TRIGGER IF EXISTS execution_registered_sim_cancel_dispatch_claim_no_delete"
    )
    connection.execute(
        "DROP TABLE IF EXISTS execution_registered_sim_cancel_dispatch_claims"
    )
    connection.execute(
        "DROP TRIGGER IF EXISTS execution_registered_sim_cancel_dispatch_tombstone_no_update"
    )
    connection.execute(
        "DROP TRIGGER IF EXISTS execution_registered_sim_cancel_dispatch_tombstone_no_delete"
    )
    connection.execute(
        "DROP TABLE IF EXISTS execution_registered_sim_cancel_dispatch_tombstones"
    )


def _drop_v22_registered_sim_cancel_objects(connection: sqlite3.Connection) -> None:
    _drop_v23_fee_pair_grid_single_row_objects(connection)
    for trigger in (
        "execution_registered_sim_cancel_dispatch_claim_no_update",
        "execution_registered_sim_cancel_dispatch_claim_no_delete",
        "execution_registered_sim_cancel_dispatch_tombstone_no_update",
        "execution_registered_sim_cancel_dispatch_tombstone_no_delete",
    ):
        connection.execute("DROP TRIGGER IF EXISTS " + trigger)
    connection.execute(
        "DROP TABLE IF EXISTS execution_registered_sim_cancel_dispatch_claims"
    )
    connection.execute(
        "DROP TABLE IF EXISTS execution_registered_sim_cancel_dispatch_tombstones"
    )


def _durable_usage(journal: ExecutionDecisionJournal):
    with journal._read_lock():
        cursor = journal._connection.cursor()
        try:
            return read_durable_capacity_usage(cursor)
        finally:
            cursor.close()


def _restore_v15_journal_schema(connection: sqlite3.Connection) -> None:
    """Restore the cumulative v15 object set from a current journal fixture."""

    _drop_v17_fee_pair_workflow_tables(connection)
    connection.execute(
        "DROP TABLE IF EXISTS execution_fee_pair_candidate_capacity_reservations"
    )
    connection.execute("DROP TABLE IF EXISTS execution_fee_pair_candidate_events")
    connection.execute("DROP TABLE IF EXISTS execution_fee_pair_candidates")
    connection.execute("PRAGMA user_version = 15")


def _decision_key(
    run_id: str = "run-a", *, close_time: str = "2026-10-20T10:00:00Z", kind: str = "bar"
) -> ExecutionDecisionKey:
    return ExecutionDecisionKey(
        account_scope="account-a",
        strategy_scope="strategy-a",
        logical_run_id=run_id,
        cohort_id="cohort-1",
        close_time=close_time,
        decision_kind=kind,
    )


def _grid_key(
    *,
    account_scope="account-a",
    strategy_scope="strategy-a",
    run_id="run-a",
    cohort_id="cohort-a",
    close_time="2026-10-20T10:00:00Z",
    kind="bar",
):
    return ExecutionDecisionKey(
        account_scope=account_scope,
        strategy_scope=strategy_scope,
        logical_run_id=run_id,
        cohort_id=cohort_id,
        close_time=close_time,
        decision_kind=kind,
    )


def _fee_pair_candidate(
    *,
    run_id="fee-pair-candidate-run",
    close_time="2026-10-24T10:30:00Z",
    batch_id=None,
    epoch_id=1,
    slot_index=0,
    session_id="session-a",
    session_generation="generation-a",
    source_predecessor_sha256=None,
    source_predecessor=None,
    source_restart_marker=None,
    source_members=None,
):
    digest = lambda value: hashlib.sha256(value.encode("ascii")).hexdigest()
    cohort_id = "cohort-a"
    key = _grid_key(run_id=run_id, cohort_id=cohort_id, close_time=close_time, kind="simnow-live")
    batch_id = batch_id or "{}:{}:{}:{}:{}".format(
        cohort_id, "calendar-a", epoch_id, "calendar-v1", slot_index
    )
    if source_predecessor is not None and source_predecessor_sha256 is None:
        source_predecessor_sha256 = source_predecessor.receipt_sha256
    if source_members is None:
        parsed_close = datetime.fromisoformat(close_time.replace("Z", "+00:00"))

        def timestamp(value):
            return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
                "+00:00", "Z"
            )

        source_members = (
            ExecutionSourceMemberReceipt(
                member_id="SIM-A",
                source_ref="simnow-live",
                source_role="live",
                connection_generation="generation-a",
                feed_sequence=1,
                bar_id="bar-{}".format(close_time),
                bucket_start=timestamp(parsed_close - timedelta(minutes=1)),
                close_time=close_time,
                available_at=timestamp(parsed_close + timedelta(seconds=1)),
                trading_day="20261024",
                session_segment="morning",
                timezone_id="UTC",
                clock_domain_id="synthetic-clock",
                complete=True,
                quality="GOOD",
                present=True,
            ),
        )
    return ExecutionFeePairCandidate(
        key=key,
        source_kind="simnow-live",
        calendar_id="calendar-a",
        calendar_version="calendar-v1",
        calendar_fingerprint=digest("calendar-a"),
        epoch_id=epoch_id,
        slot_index=slot_index,
        slot_id="slot-{}".format(slot_index),
        batch_id=batch_id,
        readiness="LIVE_READY",
        expected_tape_file_id="tape-file-a",
        expected_tape_record_index=slot_index + 1,
        source_candidate_sha256=digest("source-candidate-a"),
        source_predecessor_sha256=source_predecessor_sha256,
        source_predecessor=source_predecessor,
        source_restart_marker=source_restart_marker,
        source_members=source_members,
        signal_sha256=digest("signal-a"),
        factor_snapshot_sha256=digest("factor-snapshot-a"),
        target_ids=("SIM-A", "SIM-B"),
        directions=(1, -1),
        quote_identity_sha256s=(digest("quote-a"), digest("quote-b")),
        account_session_id=session_id,
        account_session_generation=session_generation,
    )


def _record_grid_noop(journal, key, *, epoch_id, batch_id, economics=None):
    return journal.record_grid_decision(
        key,
        {"signal": "flat"} if economics is None else economics,
        epoch_id=epoch_id,
        batch_id=batch_id,
        eligible=True,
        complete=True,
        live_ready=True,
        inputs_complete=True,
    )


def _intent_key(
    instrument: str = "SIM-IF-1",
    *,
    action: str = "SUBMIT",
    leg: int = 0,
    side: str = "BUY",
    effect: str = "OPEN",
) -> ExecutionIntentKey:
    return ExecutionIntentKey(
        action=action,
        instrument=instrument,
        side=side,
        position_effect=effect,
        leg=leg,
    )


def _decision_payload(**changes):
    payload = {"signal": "cross-up", "confidence": 0.75}
    payload.update(changes)
    return payload


def _order_payload(**changes):
    payload = {
        "quantity": Decimal("2.000"),
        "price": Decimal("4012.50"),
        "order_type": "LIMIT",
        "time_in_force": "DAY",
    }
    payload.update(changes)
    return payload


def _native_order_identity(order_ref, *, instrument="SIM-IF-1"):
    return {
        "backtrader_order_ref": 41,
        "order_ref": str(order_ref),
        "instrument_id": instrument,
        "exchange_id": "CFFEX",
        "trading_day": "20261024",
        "operation": "insert",
    }


def _prepare(journal, *, key=None, intent_key=None, original_identity=None):
    decision = journal.record_decision(
        key or _decision_key(),
        _decision_payload(),
        intent_keys=(intent_key or _intent_key(),),
    )
    intent = journal.prepare_intent(
        decision.decision_id,
        intent_key or _intent_key(),
        _order_payload(),
        original_identity=original_identity or {"backtrader_order_ref": 41},
    )
    return decision, intent


def _record_terminal_reconciliation(
    journal,
    intent,
    *,
    reconciliation_id,
    query_id,
    terminal_state="FILLED",
    event_id="provider-event-1",
    snapshot_id="position-snapshot-1",
    position_flat=False,
    provider_order_id="provider-order-1",
):
    return journal.record_reconciliation(
        intent.intent_id,
        reconciliation_id=reconciliation_id,
        query_id=query_id,
        state="KNOWN",
        provider_identity={"order_id": provider_order_id},
        outcome_code=terminal_state.lower(),
        terminal_state=terminal_state,
        terminal_event_id=event_id,
        position_snapshot_id=snapshot_id,
        position_flat=position_flat,
    )


def test_noop_and_canonical_economics_are_durable_and_immutable(tmp_path):
    path = tmp_path / "decisions.sqlite3"
    journal = ExecutionDecisionJournal(path)
    key = _decision_key()
    first = journal.record_decision(
        key,
        {
            "quantity": Decimal("1.000"),
            "price": 123.0,
            "tags": {"z": 1, "a": 2},
            "path": ["strategy", {"phase": "close"}],
        },
    )
    assert first.is_noop is True
    assert first.intent_keys == ()
    assert first.economic_payload == {
        "quantity": "1",
        "price": "123",
        "tags": {"a": 2, "z": 1},
        "path": ("strategy", {"phase": "close"}),
    }
    with pytest.raises(TypeError):
        first.economic_payload["quantity"] = "99"
    with pytest.raises(TypeError):
        first.economic_payload["tags"]["a"] = 99
    with pytest.raises(TypeError):
        first.economic_payload["path"][1]["phase"] = "changed"
    replay = journal.record_decision(
        key,
        {
            "tags": {"a": 2, "z": 1},
            "price": "123.00",
            "quantity": "1.0",
            "path": ["strategy", {"phase": "close"}],
        },
    )
    assert replay.decision_id == first.decision_id
    with pytest.raises(ExecutionDecisionJournalError, match="DECISION_CONFLICT"):
        journal.record_decision(
            key,
            {"quantity": "1.01", "price": "123", "tags": {"a": 2, "z": 1}},
        )
    with pytest.raises(ExecutionDecisionJournalError, match="INVALID_JOURNAL_PAYLOAD"):
        journal.record_decision(_decision_key("bool-quantity"), {"quantity": True})
    journal.close()

    reopened = ExecutionDecisionJournal(path)
    restored = reopened.decision(first.decision_id)
    assert restored is not None
    assert restored.is_noop is True
    assert restored.economic_payload["quantity"] == "1"
    reopened.close()


def test_fee_pair_scope_registration_is_immutable_idempotent_and_durable(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "fee-pair-registration.sqlite3")
    try:
        registration = journal.register_fee_pair_required_scope("account-a", "strategy-a")
        assert registration.state == "REQUIRE_PAIR_FAIL_CLOSED"
        assert journal.register_fee_pair_required_scope("account-a", "strategy-a") == registration
        assert journal.fee_pair_required_scope("account-a", "strategy-a") == registration
        assert journal._connection.execute(
            "SELECT COUNT(*) FROM execution_fee_pair_required_scopes"
        ).fetchone()[0] == 1
        assert journal._connection.execute(
            "SELECT COUNT(*) FROM execution_fee_pair_scope_events"
        ).fetchone()[0] == 1

        with pytest.raises(sqlite3.IntegrityError, match="FEE_PAIR_SCOPE_IMMUTABLE"):
            journal._connection.execute(
                "UPDATE execution_fee_pair_required_scopes SET state='OPEN'"
            )
        with pytest.raises(sqlite3.IntegrityError, match="FEE_PAIR_SCOPE_IMMUTABLE"):
            journal._connection.execute("DELETE FROM execution_fee_pair_required_scopes")
        with pytest.raises(sqlite3.IntegrityError, match="FEE_PAIR_SCOPE_EVENT_APPEND_ONLY"):
            journal._connection.execute(
                "UPDATE execution_fee_pair_scope_events SET event_payload_json='{}'"
            )
        with pytest.raises(sqlite3.IntegrityError, match="FEE_PAIR_SCOPE_EVENT_APPEND_ONLY"):
            journal._connection.execute("DELETE FROM execution_fee_pair_scope_events")

        usage = tuple(
            tuple(row)
            for row in journal._connection.execute(
                "SELECT capacity_class,record_count,payload_bytes "
                "FROM execution_durable_capacity_usage ORDER BY capacity_class"
            )
        )
        assert usage[1][0] == "SETTLEMENT"
        assert usage[1][1] == 2
        assert usage[1][2] > 0
    finally:
        journal.close()


def test_fee_pair_scope_registration_capacity_failure_rolls_back_both_rows(tmp_path):
    journal = ExecutionDecisionJournal(
        tmp_path / "fee-pair-registration-capacity.sqlite3",
        max_durable_settlement_records=1,
        max_durable_settlement_bytes=4096,
    )
    try:
        before_usage = tuple(
            tuple(row)
            for row in journal._connection.execute(
                "SELECT capacity_class,record_count,payload_bytes "
                "FROM execution_durable_capacity_usage ORDER BY capacity_class"
            )
        )
        with pytest.raises(
            ExecutionDecisionJournalError, match="DURABLE_SETTLEMENT_RECORDS_EXHAUSTED"
        ):
            journal.register_fee_pair_required_scope("account-a", "strategy-a")
        assert journal._connection.execute(
            "SELECT COUNT(*) FROM execution_fee_pair_required_scopes"
        ).fetchone()[0] == 0
        assert journal._connection.execute(
            "SELECT COUNT(*) FROM execution_fee_pair_scope_events"
        ).fetchone()[0] == 0
        after_usage = tuple(
            tuple(row)
            for row in journal._connection.execute(
                "SELECT capacity_class,record_count,payload_bytes "
                "FROM execution_durable_capacity_usage ORDER BY capacity_class"
            )
        )
        assert after_usage == before_usage
        assert journal.fee_pair_required_scope("account-a", "strategy-a") is None
    finally:
        journal.close()


def test_fee_pair_candidate_reserves_base_capacity_and_records_one_journal_only_claim(
    tmp_path,
):
    journal = ExecutionDecisionJournal(tmp_path / "fee-pair-candidate-claim.sqlite3")
    token = "owner-token-" + "x" * 40
    candidate = _fee_pair_candidate()
    try:
        with pytest.raises(
            ExecutionDecisionJournalError, match="FEE_PAIR_SCOPE_NOT_REGISTERED"
        ):
            journal.reserve_fee_pair_candidate(
                candidate, owner_token=token, ttl_seconds=10
            )

        journal.register_fee_pair_required_scope("account-a", "strategy-a")
        before_settlement = tuple(
            journal._connection.execute(
                """SELECT record_count,payload_bytes FROM execution_durable_capacity_usage
                   WHERE capacity_class='SETTLEMENT'"""
            ).fetchone()
        )
        reserved = journal.reserve_fee_pair_candidate(
            candidate, owner_token=token, ttl_seconds=10
        )
        assert reserved.state == "RESERVED"
        assert reserved.owner_matches_current_process is True
        assert reserved.expired_for_current_process is False
        assert reserved.candidate_sha256 == hashlib.sha256(
            journal._connection.execute(
                "SELECT candidate_payload_json FROM execution_fee_pair_candidates"
            ).fetchone()[0].encode("utf-8")
        ).hexdigest()

        usage = {
            row["capacity_class"]: (row["record_count"], row["payload_bytes"])
            for row in journal._connection.execute(
                """SELECT capacity_class,record_count,payload_bytes
                   FROM execution_durable_capacity_usage"""
            )
        }
        assert usage["BASE"][0] == 3  # candidate, reservation event and capacity row
        assert usage["SETTLEMENT"] == before_settlement == (2, before_settlement[1])
        reservation = journal._connection.execute(
            """SELECT capacity_class,reserved_records,reserved_bytes,state
               FROM execution_fee_pair_candidate_capacity_reservations"""
        ).fetchone()
        assert tuple(reservation) == ("BASE", 1, reservation["reserved_bytes"], "RESERVED")
        assert reservation["reserved_bytes"] > 0
        assert journal._connection.execute(
            "SELECT COUNT(*) FROM execution_source_highwaters"
        ).fetchone()[0] == 0

        with pytest.raises(
            ExecutionDecisionJournalError, match="FEE_PAIR_SCOPE_FAIL_CLOSED"
        ):
            journal.record_grid_decision(
                candidate.key,
                {"signal": "candidate-does-not-settle"},
                epoch_id="epoch-1",
                batch_id=candidate.batch_id,
                eligible=True,
                complete=True,
                live_ready=True,
                inputs_complete=True,
            )

        claimed = journal.record_fee_pair_append_claim(
            reserved.candidate_id, owner_token=token
        )
        assert claimed.state == "APPEND_CLAIMED"
        assert claimed.owner_matches_current_process is True
        assert not hasattr(claimed, "writer_capability")
        assert journal.fee_pair_candidate(reserved.candidate_id) == claimed
        with pytest.raises(
            ExecutionDecisionJournalError, match="FEE_PAIR_CANDIDATE_ALREADY_CLAIMED"
        ):
            journal.record_fee_pair_append_claim(reserved.candidate_id, owner_token=token)

        # Exact reserve replay is read-only after its first commit. Neither the
        # candidate event nor the physical source lineage is fabricated again.
        assert journal.reserve_fee_pair_candidate(
            candidate, owner_token=token, ttl_seconds=10
        ) == claimed
        assert journal._connection.execute(
            "SELECT COUNT(*) FROM execution_fee_pair_candidate_events"
        ).fetchone()[0] == 2
        assert journal._connection.execute(
            "SELECT COUNT(*) FROM execution_source_highwaters"
        ).fetchone()[0] == 0
        assert journal._connection.execute(
            "SELECT COUNT(*) FROM execution_decisions"
        ).fetchone()[0] == 0
        consumed = journal._connection.execute(
            """SELECT capacity_class,reserved_records,reserved_bytes,state
               FROM execution_fee_pair_candidate_capacity_reservations"""
        ).fetchone()
        assert tuple(consumed) == ("BASE", 0, 0, "CONSUMED")
        after_settlement = tuple(
            journal._connection.execute(
                """SELECT record_count,payload_bytes FROM execution_durable_capacity_usage
                   WHERE capacity_class='SETTLEMENT'"""
            ).fetchone()
        )
        assert after_settlement == before_settlement
    finally:
        journal.close()


def test_fee_pair_candidate_binds_source_head_and_never_releases_quarantine_scope(
    tmp_path, monkeypatch
):
    journal = ExecutionDecisionJournal(tmp_path / "fee-pair-candidate-quarantine.sqlite3")
    token = "owner-token-" + "y" * 40
    candidate = _fee_pair_candidate()
    try:
        journal.register_fee_pair_required_scope("account-a", "strategy-a")
        wrong_predecessor = _fee_pair_candidate(
            source_predecessor=ExecutionSourceHighWaterRef(
                account_scope="account-a",
                strategy_scope="strategy-a",
                logical_run_id=candidate.key.logical_run_id,
                source_kind=candidate.source_kind,
                decision_id=hashlib.sha256(b"wrong-decision").hexdigest(),
                receipt_sha256=hashlib.sha256(b"wrong-head").hexdigest(),
                cohort_id=candidate.key.cohort_id,
                calendar_id=candidate.calendar_id,
                calendar_version=candidate.calendar_version,
                calendar_fingerprint=candidate.calendar_fingerprint,
                epoch_id=candidate.epoch_id,
                slot_index=0,
                slot_id="prior-slot",
                close_time=candidate.key.close_time,
                batch_id="prior-batch",
                tape_file_id=candidate.expected_tape_file_id,
                tape_record_id="prior-record",
                tape_record_index=1,
            )
        )
        with pytest.raises(
            ExecutionDecisionJournalError,
            match="FEE_PAIR_CANDIDATE_SOURCE_HEAD_MISMATCH",
        ):
            journal.reserve_fee_pair_candidate(
                wrong_predecessor, owner_token=token, ttl_seconds=10
            )
        assert journal._connection.execute(
            "SELECT COUNT(*) FROM execution_fee_pair_candidates"
        ).fetchone()[0] == 0

        reserved = journal.reserve_fee_pair_candidate(
            candidate, owner_token=token, ttl_seconds=0.001
        )
        changed_session = _fee_pair_candidate(
            run_id="later-run",
            close_time="2026-10-24T10:31:00Z",
            session_id="session-b",
            session_generation="generation-b",
        )
        with pytest.raises(
            ExecutionDecisionJournalError,
            match="FEE_PAIR_CANDIDATE_SCOPE_ALREADY_RESERVED",
        ):
            journal.reserve_fee_pair_candidate(
                changed_session, owner_token="new-owner-token-" + "z" * 32, ttl_seconds=10
            )

        import backtrader.stores.execution_decision_journal as journal_module

        monkeypatch.setattr(
            journal_module.time,
            "monotonic_ns",
            lambda: reserved.deadline_monotonic_ns,
        )
        with pytest.raises(
            ExecutionDecisionJournalError, match="FEE_PAIR_CANDIDATE_EXPIRED"
        ):
            journal.record_fee_pair_append_claim(reserved.candidate_id, owner_token=token)
        quarantined = journal.quarantine_fee_pair_candidate(
            reserved.candidate_id, owner_token=token, reason_code="EXPIRED"
        )
        assert quarantined.state == "QUARANTINED"
        assert journal._connection.execute(
            "SELECT COUNT(*) FROM execution_fee_pair_candidate_events"
        ).fetchone()[0] == 2

        # Quarantine is terminal in this round. It does not release the scope,
        # create a source-only decision, or permit another batch/session.
        with pytest.raises(
            ExecutionDecisionJournalError,
            match="FEE_PAIR_CANDIDATE_SCOPE_ALREADY_RESERVED",
        ):
            journal.reserve_fee_pair_candidate(
                changed_session, owner_token="new-owner-token-" + "z" * 32, ttl_seconds=10
            )
        ineligible = journal.record_grid_decision(
            changed_session.key,
            {"signal": "new-batch"},
            epoch_id="epoch-2",
            batch_id=changed_session.batch_id,
            eligible=False,
            complete=True,
            live_ready=True,
            inputs_complete=True,
        )
        assert ineligible.eligible is False
        assert ineligible.source_anchor is None
        assert journal._connection.execute(
            "SELECT COUNT(*) FROM execution_source_highwaters"
        ).fetchone()[0] == 0
        assert journal._connection.execute(
            "SELECT COUNT(*) FROM execution_decisions"
        ).fetchone()[0] == 0
    finally:
        journal.close()


def test_fee_pair_candidate_connection_reopen_is_not_process_restart_and_claim_is_cas(
    tmp_path,
):
    path = tmp_path / "fee-pair-candidate-concurrent.sqlite3"
    first = ExecutionDecisionJournal(path)
    second = ExecutionDecisionJournal(path)
    token = "owner-token-" + "c" * 40
    candidate = _fee_pair_candidate()
    barrier = Barrier(2)
    try:
        first.register_fee_pair_required_scope("account-a", "strategy-a")
        second_registered = second.fee_pair_required_scope("account-a", "strategy-a")
        assert second_registered is not None

        def reserve(journal):
            barrier.wait(timeout=5)
            return journal.reserve_fee_pair_candidate(
                candidate, owner_token=token, ttl_seconds=10
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(reserve, (first, second)))
        assert results[0].candidate_id == results[1].candidate_id
        assert results[0].owner_matches_current_process is True
        assert results[1].owner_matches_current_process is True
        assert first._connection.execute(
            "SELECT COUNT(*) FROM execution_fee_pair_candidates"
        ).fetchone()[0] == 1

        barrier.reset()

        def claim(journal):
            barrier.wait(timeout=5)
            try:
                return journal.record_fee_pair_append_claim(
                    results[0].candidate_id, owner_token=token
                )
            except ExecutionDecisionJournalError as error:
                return error.code

        with ThreadPoolExecutor(max_workers=2) as pool:
            claims = list(pool.map(claim, (first, second)))
        assert sum(
            1 for result in claims if getattr(result, "state", None) == "APPEND_CLAIMED"
        ) == 1
        assert sum(
            1 for result in claims if result == "FEE_PAIR_CANDIDATE_ALREADY_CLAIMED"
        ) == 1
        assert first.fee_pair_candidate(results[0].candidate_id).state == "APPEND_CLAIMED"
    finally:
        second.close()
        first.close()


def test_registered_fee_pair_scope_fences_legacy_open_paths_but_allows_close_cancel(
    tmp_path,
):
    journal = ExecutionDecisionJournal(tmp_path / "fee-pair-open-fence.sqlite3")
    try:
        known_open_key = _intent_key("SIM-OWNER-1", side="BUY", effect="OPEN")
        known_open_decision = journal.record_decision(
            _decision_key("owner-run", close_time="2026-10-20T10:00:00Z"),
            {"signal": "open-before-registration"},
            intent_keys=(known_open_key,),
        )
        known_open = journal.prepare_intent(
            known_open_decision.decision_id,
            known_open_key,
            _order_payload(),
            original_identity={"backtrader_order_ref": 51},
        )
        assert journal.claim_dispatch(known_open.intent_id) is not None
        journal.record_dispatch_result(
            known_open.intent_id,
            state="KNOWN",
            provider_identity={"order_id": "synthetic-open-51"},
            outcome_code="accepted",
        )

        prepared_open_key = _intent_key("SIM-PREPARED-2", side="BUY", effect="OPEN")
        prepared_open_decision = journal.record_decision(
            _decision_key("prepared-run", close_time="2026-10-20T10:01:00Z"),
            {"signal": "prepared-before-registration"},
            intent_keys=(prepared_open_key,),
        )
        prepared_open = journal.prepare_intent(
            prepared_open_decision.decision_id,
            prepared_open_key,
            _order_payload(),
            original_identity={"backtrader_order_ref": 52},
        )

        unprepared_open_key = _intent_key("SIM-UNPREPARED-3", side="BUY", effect="OPEN")
        unprepared_open_decision = journal.record_decision(
            _decision_key("unprepared-run", close_time="2026-10-20T10:02:00Z"),
            {"signal": "declared-before-registration"},
            intent_keys=(unprepared_open_key,),
        )
        journal.register_fee_pair_required_scope("account-a", "strategy-a")
        # A completed dispatch may still be a working provider order. Its
        # owner remains available to risk cancellation, while replays cannot
        # dispatch the already-claimed OPEN a second time.
        assert journal.claim_dispatch(known_open.intent_id) is None
        assert journal.active_instrument_owner("account-a", "SIM-OWNER-1").intent_id == (
            known_open.intent_id
        )

        with pytest.raises(
            ExecutionDecisionJournalError, match="FEE_PAIR_SCOPE_FAIL_CLOSED"
        ):
            journal.record_decision(
                _decision_key("different-run", close_time="2026-10-20T10:03:00Z"),
                {"signal": "open-after-registration"},
                intent_keys=(_intent_key("SIM-NEW-4", side="BUY", effect="OPEN"),),
            )
        with pytest.raises(
            ExecutionDecisionJournalError, match="FEE_PAIR_SCOPE_FAIL_CLOSED"
        ):
            journal.record_grid_decision(
                _grid_key(
                    run_id="different-run",
                    cohort_id="different-cohort",
                    close_time="2026-10-20T10:03:00Z",
                ),
                {"signal": "flat"},
                epoch_id="epoch-next",
                batch_id="batch-next",
                eligible=True,
                complete=True,
                live_ready=True,
                inputs_complete=True,
            )
        with pytest.raises(
            ExecutionDecisionJournalError,
            match="FEE_PAIR_OPEN_RISK_RESERVATION_REQUIRED",
        ):
            journal.prepare_intent(
                unprepared_open_decision.decision_id,
                unprepared_open_key,
                _order_payload(),
                original_identity={"backtrader_order_ref": 53},
            )
        with pytest.raises(
            ExecutionDecisionJournalError,
            match="FEE_PAIR_OPEN_RISK_RESERVATION_REQUIRED",
        ):
            journal.claim_dispatch(prepared_open.intent_id)
        assert journal.intent(prepared_open.intent_id).state == "PREPARED"
        assert journal.intent(known_open.intent_id).state == "KNOWN"

        # Different account or strategy scopes retain the legacy OPEN path.
        other_key = ExecutionDecisionKey(
            account_scope="account-other",
            strategy_scope="strategy-a",
            logical_run_id="different-run",
            cohort_id="cohort-1",
            close_time="2026-10-20T10:04:00Z",
            decision_kind="bar",
        )
        other_decision = journal.record_decision(
            other_key,
            {"signal": "open-other-account"},
            intent_keys=(_intent_key("SIM-OTHER-ACCOUNT", effect="OPEN"),),
        )
        assert other_decision.intent_keys
        other_strategy_key = ExecutionDecisionKey(
            account_scope="account-a",
            strategy_scope="strategy-other",
            logical_run_id="different-run",
            cohort_id="cohort-1",
            close_time="2026-10-20T10:05:00Z",
            decision_kind="bar",
        )
        other_strategy_decision = journal.record_decision(
            other_strategy_key,
            {"signal": "open-other-strategy"},
            intent_keys=(_intent_key("SIM-OTHER-STRATEGY", effect="OPEN"),),
        )
        assert other_strategy_decision.intent_keys

        close_key = _intent_key("SIM-CLOSE-SAFE", side="SELL", effect="CLOSE")
        close_decision = journal.record_risk_decision(
            _decision_key("close-safe-run", close_time="2026-10-20T10:06:00Z", kind="risk"),
            {"signal": "risk-close"},
            intent_keys=(close_key,),
            max_order_intents_per_run=5,
            expected_run_order_intents_used=0,
            remaining_exit_intent_reserve=4,
        )
        close_intent = journal.prepare_intent(
            close_decision.decision.decision_id,
            close_key,
            _order_payload(),
            original_identity={"backtrader_order_ref": 54},
        )
        assert journal.claim_dispatch(close_intent.intent_id) is not None

        cancel_key = _intent_key(
            "SIM-OWNER-1", action="CANCEL", side="BUY", effect="OPEN"
        )
        cancel_decision = journal.record_risk_decision(
            _decision_key("cancel-safe-run", close_time="2026-10-20T10:07:00Z", kind="risk"),
            {"signal": "risk-cancel"},
            intent_keys=(cancel_key,),
            max_order_intents_per_run=5,
            expected_run_order_intents_used=0,
            remaining_exit_intent_reserve=4,
        )
        cancel_intent = journal.prepare_intent(
            cancel_decision.decision.decision_id,
            cancel_key,
            {"order_ref": "synthetic-open-51"},
            original_identity={"backtrader_order_ref": 55},
            owner_intent_id=known_open.intent_id,
        )
        assert journal.claim_dispatch(cancel_intent.intent_id) is not None
    finally:
        journal.close()

    invalid = ExecutionDecisionJournal(tmp_path / "invalid-economic.sqlite3")
    decision = invalid.record_decision(_decision_key("invalid-economic"), _decision_payload())
    with pytest.raises(ExecutionDecisionJournalError, match="INVALID_JOURNAL_PAYLOAD"):
        invalid.prepare_intent(
            decision.decision_id,
            _intent_key(),
            _order_payload(price=False),
        )
    invalid.close()


@pytest.mark.parametrize("dispatch_state", ("DISPATCHING", "UNKNOWN"))
def test_fee_pair_registration_rejects_claimed_open_until_authoritatively_resolved(
    tmp_path, dispatch_state
):
    path = tmp_path / ("fee-pair-register-{}-open.sqlite3".format(dispatch_state.lower()))
    claiming = ExecutionDecisionJournal(path)
    prepared = None
    registered = ExecutionDecisionJournal(path)
    try:
        open_key = _intent_key("SIM-RACE-OPEN", side="BUY", effect="OPEN")
        decision = claiming.record_decision(
            _decision_key("claim-before-register"),
            {"signal": "open-before-register"},
            intent_keys=(open_key,),
        )
        prepared = claiming.prepare_intent(
            decision.decision_id,
            open_key,
            _order_payload(),
            original_identity={"backtrader_order_ref": 901},
        )
        claim = claiming.claim_dispatch(prepared.intent_id)
        assert claim is not None
        if dispatch_state == "UNKNOWN":
            claiming.record_dispatch_result(
                prepared.intent_id,
                state="UNKNOWN",
                outcome_code="synthetic-response-lost-after-send",
            )

        # The registration's BEGIN IMMEDIATE sees the committed claim state
        # from the other Journal connection and refuses to fence over it.
        with pytest.raises(
            ExecutionDecisionJournalError,
            match="FEE_PAIR_SCOPE_OPEN_INTENT_UNRESOLVED",
        ):
            registered.register_fee_pair_required_scope("account-a", "strategy-a")
        assert registered.fee_pair_required_scope("account-a", "strategy-a") is None
        assert claiming.claim_dispatch(prepared.intent_id) is None
        if dispatch_state == "UNKNOWN":
            resolved = claiming.record_reconciliation(
                prepared.intent_id,
                reconciliation_id="synthetic-open-terminal-reconciliation",
                query_id="synthetic-complete-orders-query",
                state="KNOWN",
                provider_identity={"order_id": "synthetic-open-order"},
                outcome_code="terminal_order_observed",
                terminal_state="CANCELLED",
                terminal_event_id="synthetic-open-terminal-event",
                position_snapshot_id="synthetic-position-snapshot",
                position_flat=True,
            )
            assert resolved.terminal_state == "CANCELLED"
            assert (
                registered.register_fee_pair_required_scope("account-a", "strategy-a").state
                == "REQUIRE_PAIR_FAIL_CLOSED"
            )
    finally:
        registered.close()
        claiming.close()


def test_fee_pair_registration_winning_before_old_prepared_claim_fences_it(tmp_path):
    path = tmp_path / "fee-pair-register-before-claim.sqlite3"
    registering = ExecutionDecisionJournal(path)
    claiming = ExecutionDecisionJournal(path)
    try:
        open_key = _intent_key("SIM-PREPARED-OPEN", side="BUY", effect="OPEN")
        decision = registering.record_decision(
            _decision_key("register-before-claim"),
            {"signal": "prepared-before-register"},
            intent_keys=(open_key,),
        )
        prepared = registering.prepare_intent(
            decision.decision_id,
            open_key,
            _order_payload(),
            original_identity={"backtrader_order_ref": 902},
        )
        registration = registering.register_fee_pair_required_scope(
            "account-a", "strategy-a"
        )

        # A second connection cannot turn an old PREPARED row into a send
        # after registration commits.
        with pytest.raises(
            ExecutionDecisionJournalError,
            match="FEE_PAIR_OPEN_RISK_RESERVATION_REQUIRED",
        ):
            claiming.claim_dispatch(prepared.intent_id)
        assert claiming.intent(prepared.intent_id).state == "PREPARED"
        assert claiming.fee_pair_required_scope("account-a", "strategy-a") == registration
    finally:
        claiming.close()
        registering.close()


def test_decision_for_key_reads_after_reopen_without_mutating_journal(tmp_path):
    path = tmp_path / "decision-for-key.sqlite3"
    journal = ExecutionDecisionJournal(path)
    key = _grid_key()
    grid = _record_grid_noop(
        journal,
        key,
        epoch_id="epoch-a",
        batch_id="batch-a",
    )
    assert grid.decision is not None
    assert grid.cursor is not None
    expected = grid.decision
    journal.close()

    reopened = ExecutionDecisionJournal(path)
    cursor_before = reopened.grid_cursor(
        key.account_scope, key.strategy_scope, key.cohort_id
    )
    capacity_before = reopened.decision_capacity_snapshot()
    changes_before = reopened._connection.total_changes

    assert reopened.decision_for_key(key) == expected
    equivalent_time_key = _grid_key(close_time="2026-10-20T18:00:00+08:00")
    assert reopened.decision_for_key(equivalent_time_key) == expected
    for missing_key in (
        _grid_key(account_scope="account-other"),
        _grid_key(strategy_scope="strategy-other"),
        _grid_key(close_time="2026-10-20T10:00:01Z"),
        _grid_key(kind="tick"),
        _grid_key(run_id="run-other"),
    ):
        assert reopened.decision_for_key(missing_key) is None

    with pytest.raises(ExecutionDecisionJournalError, match="INVALID_DECISION_KEY"):
        reopened.decision_for_key(None)

    assert reopened.grid_cursor(key.account_scope, key.strategy_scope, key.cohort_id) == (
        cursor_before
    )
    capacity_after = reopened.decision_capacity_snapshot()
    assert (
        capacity_after.base_record_count,
        capacity_after.base_payload_bytes,
        capacity_after.settlement_record_count,
        capacity_after.settlement_payload_bytes,
    ) == (
        capacity_before.base_record_count,
        capacity_before.base_payload_bytes,
        capacity_before.settlement_record_count,
        capacity_before.settlement_payload_bytes,
    )
    assert reopened._connection.total_changes == changes_before
    reopened.close()


def test_equivalent_close_times_normalize_to_one_business_key(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "time.sqlite3")
    utc_key = _decision_key(close_time="2026-10-20T10:00:00Z")
    offset_key = _decision_key(close_time="2026-10-20T18:00:00+08:00")
    assert utc_key.close_time == offset_key.close_time == "2026-10-20T10:00:00Z"
    first = journal.record_decision(utc_key, {"signal": "flat"})
    replay = journal.record_decision(offset_key, {"signal": "flat"})
    assert first.decision_id == replay.decision_id
    with pytest.raises(ExecutionDecisionJournalError, match="INVALID_DECISION_CLOSE_TIME"):
        _decision_key(close_time="2026-10-20T10:00:00")
    with pytest.raises(ExecutionDecisionJournalError, match="INVALID_DECISION_CLOSE_TIME"):
        _decision_key(close_time="2026-10-20T10:00:00.1234567Z")
    with pytest.raises(ExecutionDecisionJournalError, match="INVALID_DECISION_CLOSE_TIME"):
        _decision_key(close_time="2026-10-20T10:00:00-00:00")
    journal.close()


def test_finite_decision_high_water_allows_replay_and_reserved_settlement(tmp_path):
    path = tmp_path / "finite-capacity.sqlite3"
    limits = {
        "max_decision_records": 1,
        "settlement_decision_reserve_records": 2,
        "max_decision_bytes": 10000,
        "settlement_decision_reserve_bytes": 10000,
    }
    journal = ExecutionDecisionJournal(path, **limits)
    base = _decision_key("capacity-base")
    first = journal.record_decision(base, {"signal": "flat"})
    capacity_before_replay = journal.decision_capacity_snapshot()

    # Exact replay is idempotent and does not consume another capacity slot.
    replay = journal.record_decision(base, {"signal": "flat"})
    assert replay.decision_id == first.decision_id
    replay_capacity = journal.decision_capacity_snapshot()
    assert replay_capacity.base_record_count == capacity_before_replay.base_record_count
    assert replay_capacity.base_payload_bytes == capacity_before_replay.base_payload_bytes
    with pytest.raises(ExecutionDecisionJournalError, match="DECISION_CAPACITY_HIGH_WATER"):
        journal.record_decision(_decision_key("capacity-base-2"), {"signal": "flat"})

    close_key = _intent_key(effect="CLOSE")
    close = journal.record_decision(
        _decision_key("capacity-close"),
        {"signal": "reduce"},
        intent_keys=(close_key,),
    )
    assert close.intent_keys == (close_key,)
    cancel_key = _intent_key(action="CANCEL", instrument="SIM-IF-2")
    cancel = journal.record_decision(
        _decision_key("capacity-cancel"),
        {"signal": "cancel"},
        intent_keys=(cancel_key,),
    )
    assert cancel.intent_keys == (cancel_key,)
    with pytest.raises(ExecutionDecisionJournalError, match="SETTLEMENT_CAPACITY_EXHAUSTED"):
        journal.record_decision(
            _decision_key("capacity-settlement-3"),
            {"signal": "cancel"},
            intent_keys=(_intent_key(action="CANCEL", instrument="SIM-IF-3"),),
        )
    journal.close()

    reopened = ExecutionDecisionJournal(path, **limits)
    assert reopened.decision(first.decision_id) is not None
    assert reopened.decision(close.decision_id) is not None
    assert reopened.decision(cancel.decision_id) is not None
    with pytest.raises(ExecutionDecisionJournalError, match="JOURNAL_CAPACITY_CONFIG_MISMATCH"):
        ExecutionDecisionJournal(path, **{**limits, "max_decision_records": 2})
    # Capacity rejection is not a SQLite failure; exact settlement replay survives.
    assert (
        reopened.record_decision(
            _decision_key("capacity-cancel"),
            {"signal": "cancel"},
            intent_keys=(cancel_key,),
        ).decision_id
        == cancel.decision_id
    )
    usage = reopened.decision_capacity_snapshot()
    assert usage.base_record_count == usage.base_record_limit == 1
    assert usage.settlement_record_count == usage.settlement_record_limit == 2
    assert usage.base_payload_bytes > 0
    assert usage.settlement_payload_bytes > 0
    assert usage.physical_bytes >= usage.database_bytes
    reopened.close()


def test_capacity_usage_migration_backfills_exact_bytes_once(tmp_path):
    path = tmp_path / "capacity-v8-migration.sqlite3"
    journal = ExecutionDecisionJournal(path)
    journal.record_decision(_decision_key("capacity-migration-base"), {"symbol": "螺纹"})
    journal.record_decision(
        _decision_key("capacity-migration-settlement"),
        {"signal": "reduce"},
        intent_keys=(_intent_key(action="SUBMIT", effect="CLOSE"),),
    )
    journal.close()

    with sqlite3.connect(path) as connection:
        history = connection.execute(
            """SELECT capacity_class,business_key_json,economic_payload_json,intent_keys_json
               FROM execution_decisions"""
        ).fetchall()
        expected = {"BASE": [0, 0], "SETTLEMENT": [0, 0]}
        for capacity_class, business_key, economics, intent_keys in history:
            expected[capacity_class][0] += 1
            expected[capacity_class][1] += sum(
                len(value.encode("utf-8")) for value in (business_key, economics, intent_keys)
            )
        connection.execute("DROP TABLE execution_decision_capacity_usage")
        _drop_v12_durable_capacity_tables(connection)
        connection.execute("PRAGMA user_version = 8")

    migrated = ExecutionDecisionJournal(path)
    assert migrated._connection.execute("PRAGMA user_version").fetchone()[0] == ExecutionDecisionJournal._SCHEMA_VERSION
    usage = migrated._connection.execute(
        """SELECT capacity_class,record_count,payload_bytes
           FROM execution_decision_capacity_usage ORDER BY capacity_class"""
    ).fetchall()
    assert {
        row["capacity_class"]: (row["record_count"], row["payload_bytes"]) for row in usage
    } == {capacity_class: tuple(values) for capacity_class, values in expected.items()}
    snapshot = migrated.decision_capacity_snapshot()
    assert snapshot.base_record_count == expected["BASE"][0]
    assert snapshot.base_payload_bytes == expected["BASE"][1]
    assert snapshot.settlement_record_count == expected["SETTLEMENT"][0]
    assert snapshot.settlement_payload_bytes == expected["SETTLEMENT"][1]
    with migrated._transaction() as cursor:
        cursor.execute(
            """CREATE TRIGGER capacity_backfill_runs_once
               BEFORE DELETE ON execution_decision_capacity_usage
               BEGIN SELECT RAISE(ABORT,'migration repeated'); END"""
        )
    migrated.close()

    reopened = ExecutionDecisionJournal(path)
    assert reopened.decision_capacity_snapshot().base_record_count == expected["BASE"][0]
    assert (
        reopened.decision_capacity_snapshot().settlement_record_count == expected["SETTLEMENT"][0]
    )
    reopened.close()


@pytest.mark.parametrize(
    "damaged_object,statement",
    (
        (
            "execution_fee_pair_scope_event_no_delete",
            "DROP TRIGGER execution_fee_pair_scope_event_no_delete",
        ),
        (
            "execution_fee_pair_scope_events",
            "DROP TABLE execution_fee_pair_scope_events",
        ),
    ),
)
def test_v15_open_rejects_incomplete_fee_pair_scope_schema(tmp_path, damaged_object, statement):
    path = tmp_path / "v15-corrupt-pair-scope-{}.sqlite3".format(damaged_object)
    journal = ExecutionDecisionJournal(path)
    journal.close()
    with sqlite3.connect(path) as connection:
        _restore_v15_journal_schema(connection)
        connection.execute(statement)

    with pytest.raises(
        ExecutionDecisionJournalError, match="FEE_PAIR_SCOPE_SCHEMA_CORRUPT"
    ):
        ExecutionDecisionJournal(path)

    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 15


def test_v15_schema_migrates_to_v19_without_rewriting_history(tmp_path):
    path = tmp_path / "v15-to-v16-candidate-migration.sqlite3"
    journal = ExecutionDecisionJournal(path)
    decision = journal.record_decision(
        _decision_key("v15-history", close_time="2026-10-24T10:00:00Z"),
        {"signal": "flat"},
    )
    journal.register_fee_pair_required_scope("account-a", "strategy-a")
    before_usage = journal.decision_capacity_snapshot()
    before_source_highwaters = journal._connection.execute(
        "SELECT COUNT(*) FROM execution_source_highwaters"
    ).fetchone()[0]
    journal.close()

    with sqlite3.connect(path) as connection:
        _restore_v15_journal_schema(connection)

    migrated = ExecutionDecisionJournal(path)
    try:
        assert migrated._connection.execute("PRAGMA user_version").fetchone()[0] == ExecutionDecisionJournal._SCHEMA_VERSION
        assert migrated.decision(decision.decision_id) == decision
        assert migrated.fee_pair_required_scope("account-a", "strategy-a") is not None
        assert migrated._connection.execute(
            "SELECT COUNT(*) FROM execution_fee_pair_candidates"
        ).fetchone()[0] == 0
        assert migrated._connection.execute(
            "SELECT COUNT(*) FROM execution_source_highwaters"
        ).fetchone()[0] == before_source_highwaters
        after_usage = migrated.decision_capacity_snapshot()
        assert after_usage.base_record_count == before_usage.base_record_count
        assert after_usage.base_payload_bytes == before_usage.base_payload_bytes
        assert after_usage.settlement_record_count == before_usage.settlement_record_count
        assert after_usage.settlement_payload_bytes == before_usage.settlement_payload_bytes
    finally:
        migrated.close()


def test_v11_upgrade_creates_empty_order_sysid_bindings_after_capacity_backfill(tmp_path):
    path = tmp_path / "v11-to-v21-order-sysid-binding.sqlite3"
    journal = ExecutionDecisionJournal(path)
    decision = journal.record_decision(
        _decision_key("v11-binding-upgrade"),
        {"signal": "preserve"},
    )
    before_capacity = journal.decision_capacity_snapshot()
    journal.close()

    with sqlite3.connect(path) as connection:
        _drop_v17_fee_pair_workflow_tables(connection)
        connection.execute(
            "DROP TABLE IF EXISTS execution_fee_pair_candidate_capacity_reservations"
        )
        connection.execute("DROP TABLE IF EXISTS execution_fee_pair_candidate_events")
        connection.execute("DROP TABLE IF EXISTS execution_fee_pair_candidates")
        connection.execute("DROP TABLE IF EXISTS execution_fee_pair_scope_events")
        connection.execute("DROP TABLE IF EXISTS execution_fee_pair_required_scopes")
        _drop_v12_durable_capacity_tables(connection)
        connection.execute("PRAGMA user_version = 11")

    migrated = ExecutionDecisionJournal(path)
    try:
        assert (
            migrated._connection.execute("PRAGMA user_version").fetchone()[0]
            == ExecutionDecisionJournal._SCHEMA_VERSION
        )
        assert migrated.decision(decision.decision_id) == decision
        assert migrated._connection.execute(
            "SELECT COUNT(*) FROM execution_known_ctp_order_sysid_bindings"
        ).fetchone()[0] == 0
        assert migrated._connection.execute(
            "SELECT COUNT(*) FROM execution_registered_sim_cancel_dispatch_claims"
        ).fetchone()[0] == 0
        after_capacity = migrated.decision_capacity_snapshot()
        assert after_capacity.base_record_count == before_capacity.base_record_count
        assert after_capacity.base_payload_bytes == before_capacity.base_payload_bytes
        assert after_capacity.settlement_record_count == before_capacity.settlement_record_count
        assert after_capacity.settlement_payload_bytes == before_capacity.settlement_payload_bytes
    finally:
        migrated.close()


def test_fresh_journal_creates_empty_order_sysid_binding_schema():
    journal = ExecutionDecisionJournal(":memory:")
    try:
        assert (
            journal._connection.execute("PRAGMA user_version").fetchone()[0]
            == ExecutionDecisionJournal._SCHEMA_VERSION
        )
        assert journal._connection.execute(
            "SELECT COUNT(*) FROM execution_known_ctp_order_sysid_bindings"
        ).fetchone()[0] == 0
        assert journal._connection.execute(
            "SELECT COUNT(*) FROM execution_registered_sim_cancel_dispatch_claims"
        ).fetchone()[0] == 0
    finally:
        journal.close()


def test_v21_journal_migrates_one_shot_cancel_claim_schema(tmp_path):
    path = tmp_path / "v21-to-v22-registered-cancel-claim.sqlite3"
    journal = ExecutionDecisionJournal(path)
    decision = journal.record_decision(
        _decision_key("v21-cancel-admission"), {"signal": "preserve"}
    )
    before_capacity = journal.decision_capacity_snapshot()
    journal.close()

    with sqlite3.connect(path) as connection:
        _drop_v23_fee_pair_grid_single_row_objects(connection)
        connection.execute(
            "DROP TRIGGER IF EXISTS execution_registered_sim_cancel_dispatch_claim_no_update"
        )
        connection.execute(
            "DROP TRIGGER IF EXISTS execution_registered_sim_cancel_dispatch_claim_no_delete"
        )
        connection.execute(
            "DROP TABLE IF EXISTS execution_registered_sim_cancel_dispatch_claims"
        )
        connection.execute(
            "DROP TRIGGER IF EXISTS execution_registered_sim_cancel_dispatch_tombstone_no_update"
        )
        connection.execute(
            "DROP TRIGGER IF EXISTS execution_registered_sim_cancel_dispatch_tombstone_no_delete"
        )
        connection.execute(
            "DROP TABLE IF EXISTS execution_registered_sim_cancel_dispatch_tombstones"
        )
        connection.execute("PRAGMA user_version=21")

    migrated = ExecutionDecisionJournal(path)
    try:
        assert (
            migrated._connection.execute("PRAGMA user_version").fetchone()[0]
            == ExecutionDecisionJournal._SCHEMA_VERSION
        )
        assert migrated.decision(decision.decision_id) == decision
        assert migrated._connection.execute(
            "SELECT COUNT(*) FROM execution_registered_sim_cancel_dispatch_claims"
        ).fetchone()[0] == 0
        after_capacity = migrated.decision_capacity_snapshot()
        assert after_capacity.base_record_count == before_capacity.base_record_count
        assert after_capacity.base_payload_bytes == before_capacity.base_payload_bytes
        assert after_capacity.settlement_record_count == before_capacity.settlement_record_count
        assert after_capacity.settlement_payload_bytes == before_capacity.settlement_payload_bytes
        cursor = migrated._connection.cursor()
        try:
            migrated._validate_registered_sim_cancel_dispatch_claim_schema(cursor)
        finally:
            cursor.close()
    finally:
        migrated.close()


def _create_v21_unresolved_ctp_cancel(path):
    journal = ExecutionDecisionJournal(path)
    submit, instrument, order_ref, order_sys_id = _prepare_known_ctp_submit_for_cancel(
        journal, suffix="legacy-v21"
    )
    cancel_key = _intent_key(instrument, action="CANCEL", side="BUY", effect="OPEN")
    decision = journal.record_decision(
        ExecutionDecisionKey(
            account_scope="account-a",
            strategy_scope="strategy-a",
            logical_run_id="legacy-cancel-run",
            cohort_id="legacy-cancel-cohort",
            close_time="2026-10-20T10:09:00Z",
            decision_kind="risk",
        ),
        {"signal": "cancel"},
        intent_keys=(cancel_key,),
    )
    cancel = journal.prepare_intent(
        decision.decision_id,
        cancel_key,
        {"target_id": "target", "instrument": instrument, "exchange": "SHFE"},
        original_identity={
            "backtrader_order_ref": 94,
            "operation": "cancel",
            "instrument_id": instrument,
            "exchange_id": "SHFE",
            "order_ref": order_ref,
            "order_sys_id": order_sys_id,
            "front_id": 4,
            "session_id": 7,
            "account_fingerprint": "account-fingerprint",
            "connection_generation": 3,
            "trading_day": "20261020",
            "owner_intent_id": submit.intent_id,
        },
        owner_intent_id=submit.intent_id,
    )
    assert journal.claim_dispatch(cancel.intent_id) is not None
    before_usage = _durable_usage(journal)
    journal.close()
    with sqlite3.connect(path) as connection:
        _drop_v22_registered_sim_cancel_objects(connection)
        connection.execute("PRAGMA user_version=21")
    return cancel, instrument, order_ref, order_sys_id, before_usage


def _legacy_cancel_target_identity(instrument, order_ref, order_sys_id):
    digest = hashlib.sha256(b"legacy-complete-query").hexdigest()
    return {
        "order_ref": order_ref,
        "order_sys_id": order_sys_id,
        "instrument_id": instrument,
        "exchange_id": "SHFE",
        "broker_id": "broker-a",
        "investor_id": "investor-a",
        "front_id": 4,
        "session_id": 7,
        "account_fingerprint": "account-fingerprint",
        "connection_generation": 3,
        "trading_day": "20261020",
        "query_request_id": 3,
        "query_rows_sha256": digest,
        "matched_row_sha256": digest,
        "source_expires_monotonic": time.monotonic() + 60.0,
    }


def test_v21_migration_tombstones_unresolved_cancel_and_charges_capacity(tmp_path):
    path = tmp_path / "v21-unresolved-cancel-tombstone.sqlite3"
    cancel, instrument, order_ref, order_sys_id, before = _create_v21_unresolved_ctp_cancel(
        path
    )

    migrated = ExecutionDecisionJournal(path)
    try:
        row = migrated._connection.execute(
            "SELECT * FROM execution_registered_sim_cancel_dispatch_tombstones"
        ).fetchone()
        assert row["cancel_intent_id"] == cancel.intent_id
        assert row["migration_schema_version"] == 22
        assert row["reason"] == "LEGACY_DISPATCHING_CANCEL_AMBIGUOUS"
        with pytest.raises(
            ExecutionDecisionJournalError,
            match="CANCEL_NATIVE_DISPATCH_LEGACY_AMBIGUOUS",
        ):
            migrated.registered_sim_cancel_dispatch_records(cancel.intent_id)
        with pytest.raises(
            ExecutionDecisionJournalError,
            match="CANCEL_NATIVE_DISPATCH_LEGACY_AMBIGUOUS",
        ):
            migrated.claim_registered_sim_cancel_dispatch(
                cancel.intent_id,
                _legacy_cancel_target_identity(instrument, order_ref, order_sys_id),
            )
        after = _durable_usage(migrated)
        assert after.settlement_records == before.settlement_records + 1
        assert after.settlement_bytes > before.settlement_bytes
        assert migrated._connection.execute(
            "SELECT state,dispatch_state FROM execution_decision_intents WHERE intent_id=?",
            (cancel.intent_id,),
        ).fetchone()[:] == ("DISPATCHING", None)
    finally:
        migrated.close()


def test_v21_migration_cancel_tombstone_capacity_exhaustion_rolls_back(tmp_path):
    path = tmp_path / "v21-unresolved-cancel-capacity.sqlite3"
    cancel, _instrument, _order_ref, _order_sys_id, before = (
        _create_v21_unresolved_ctp_cancel(path)
    )
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE execution_durable_capacity_limits "
            "SET max_durable_settlement_records=? WHERE singleton=1",
            (before.settlement_records,),
        )

    with pytest.raises(
        ExecutionDecisionJournalError,
        match="DURABLE_SETTLEMENT_RECORDS_EXHAUSTED",
    ):
        ExecutionDecisionJournal(
            path, max_durable_settlement_records=before.settlement_records
        )

    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 21
        assert connection.execute(
            "SELECT COUNT(*) FROM execution_decision_intents "
            "WHERE intent_id=? AND state='DISPATCHING' AND dispatch_state IS NULL",
            (cancel.intent_id,),
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM execution_durable_capacity_usage "
            "WHERE capacity_class='SETTLEMENT' AND record_count=?",
            (before.settlement_records,),
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name IN (?,?)",
            (
                "execution_registered_sim_cancel_dispatch_claims",
                "execution_registered_sim_cancel_dispatch_tombstones",
            ),
        ).fetchone()[0] == 0


def test_v21_migration_unclassifiable_dispatching_cancel_rolls_back(tmp_path):
    path = tmp_path / "v21-unresolved-cancel-malformed.sqlite3"
    cancel, _instrument, _order_ref, _order_sys_id, before = (
        _create_v21_unresolved_ctp_cancel(path)
    )
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE execution_decision_intents SET original_identity_json='{' "
            "WHERE intent_id=?",
            (cancel.intent_id,),
        )

    with pytest.raises(
        ExecutionDecisionJournalError,
        match="REGISTERED_SIM_CANCEL_CLAIM_MIGRATION_IDENTITY_INVALID",
    ):
        ExecutionDecisionJournal(path)

    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 21
        assert connection.execute(
            "SELECT COUNT(*) FROM execution_durable_capacity_usage "
            "WHERE capacity_class='SETTLEMENT' AND record_count=?",
            (before.settlement_records,),
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name IN (?,?)",
            (
                "execution_registered_sim_cancel_dispatch_claims",
                "execution_registered_sim_cancel_dispatch_tombstones",
            ),
        ).fetchone()[0] == 0


def test_v21_migration_tombstones_every_cancel_across_batches_and_skips_submit(tmp_path):
    path = tmp_path / "v21-many-unresolved-cancels.sqlite3"
    journal = ExecutionDecisionJournal(path)
    cancel_count = 258
    cancel_keys = tuple(
        _intent_key(
            "SIM-LEGACY-CANCEL-{:03d}".format(index),
            action="CANCEL",
            leg=index,
        )
        for index in range(cancel_count)
    )
    submit_key = _intent_key("SIM-LEGACY-SUBMIT", action="SUBMIT", leg=cancel_count)
    all_keys = cancel_keys + (submit_key,)
    decision = journal.record_decision(
        ExecutionDecisionKey(
            account_scope="account-a",
            strategy_scope="strategy-a",
            logical_run_id="legacy-many-cancel-run",
            cohort_id="legacy-many-cancel-cohort",
            close_time="2026-10-20T10:09:00Z",
            decision_kind="risk",
        ),
        {"signal": "legacy-cancel-batch"},
        intent_keys=all_keys,
    )
    slots = journal._connection.execute(
        "SELECT intent_id,intent_key_json FROM execution_decision_slots "
        "WHERE decision_id=? ORDER BY leg",
        (decision.decision_id,),
    ).fetchall()
    assert len(slots) == cancel_count + 1
    cancel_ids = []
    submit_id = None
    now_ns = time.time_ns()
    with journal._transaction() as cursor:
        for slot in slots:
            key_values = json.loads(slot["intent_key_json"])
            is_cancel = key_values["action"] == "CANCEL"
            intent_id = slot["intent_id"]
            original_identity = (
                {"operation": "cancel", "backtrader_order_ref": 1000 + len(cancel_ids)}
                if is_cancel
                else {"operation": "insert", "backtrader_order_ref": 2000}
            )
            if is_cancel:
                cancel_ids.append(intent_id)
            else:
                submit_id = intent_id
            identity_json = json.dumps(
                original_identity, ensure_ascii=True, separators=(",", ":"), sort_keys=True
            )
            economic_json = json.dumps(
                {"instrument": key_values["instrument"], "exchange": "SHFE"},
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            )
            with track_durable_row_change(
                cursor, "execution_decision_intents", (intent_id,), "SETTLEMENT"
            ):
                cursor.execute(
                    """INSERT INTO execution_decision_intents (
                           intent_id,decision_id,intent_key_json,economic_payload_json,
                           original_identity_json,owner_intent_id,state,dispatch_state,
                           provider_identity_json,outcome_code,dispatch_result_json,
                           created_at_ns,updated_at_ns
                       ) VALUES (?,?,?,?,?,?, 'DISPATCHING',NULL,NULL,NULL,NULL,?,?)""",
                    (
                        intent_id,
                        decision.decision_id,
                        slot["intent_key_json"],
                        economic_json,
                        identity_json,
                        "legacy-owner" if is_cancel else None,
                        now_ns,
                        now_ns,
                    ),
                )
    before = _durable_usage(journal)
    journal.close()

    with sqlite3.connect(path) as connection:
        _drop_v22_registered_sim_cancel_objects(connection)
        connection.execute("PRAGMA user_version=21")

    migrated = ExecutionDecisionJournal(path)
    try:
        tombstone_ids = tuple(
            row[0]
            for row in migrated._connection.execute(
                "SELECT cancel_intent_id FROM "
                "execution_registered_sim_cancel_dispatch_tombstones"
            ).fetchall()
        )
        assert set(tombstone_ids) == set(cancel_ids)
        assert len(tombstone_ids) == cancel_count
        assert submit_id not in set(tombstone_ids)
        identity = _legacy_cancel_target_identity(
            "SIM-LEGACY-CANCEL-000", "94", "legacy-sysid"
        )
        for cancel_id in cancel_ids:
            with pytest.raises(
                ExecutionDecisionJournalError,
                match="CANCEL_NATIVE_DISPATCH_LEGACY_AMBIGUOUS",
            ):
                migrated.registered_sim_cancel_dispatch_records(cancel_id)
            with pytest.raises(
                ExecutionDecisionJournalError,
                match="CANCEL_NATIVE_DISPATCH_LEGACY_AMBIGUOUS",
            ):
                migrated.claim_registered_sim_cancel_dispatch(cancel_id, identity)
        after = _durable_usage(migrated)
        assert after.settlement_records == before.settlement_records + cancel_count
        assert after.settlement_bytes > before.settlement_bytes
    finally:
        migrated.close()


def test_order_sysid_binding_rejects_publicly_constructed_fake_store_receipt():
    journal = ExecutionDecisionJournal(":memory:")
    fake_store = object()
    now = datetime.now(timezone.utc)
    receipt = RegisteredSimOrderIdentityQueryReceipt(
        request_id=1,
        connection_generation=1,
        account_fingerprint="fake-account",
        trading_day="20261024",
        started_at_utc=now,
        completed_at_utc=now,
        front_id=4,
        session_id=7,
        broker_id="fake-broker",
        investor_id="fake-investor",
        rows_sha256="a" * 64,
        rows=(),
        source_expires_monotonic=time.monotonic() + 30,
        _store=fake_store,
        _issuer=object(),
    )
    try:
        with pytest.raises(
            ExecutionDecisionJournalError,
            match="KNOWN_CTP_ORDER_SYSID_QUERY_UNTRUSTED",
        ):
            journal.bind_known_ctp_order_sysid_from_query(
                "fabricated-intent",
                receipt,
                source_store=fake_store,
                broker_order_ref=1,
                expected_side="BUY",
                expected_position_effect="OPEN",
                expected_remaining_quantity=Decimal("1"),
                expected_instrument="rb2510",
                expected_exchange="SHFE",
                expected_front_id=4,
                expected_session_id=7,
            )
    finally:
        journal.close()


def test_committed_v16_candidate_history_survives_v19_upgrade_without_reclassification(
    tmp_path,
):
    path = tmp_path / "committed-v16-to-v17-fee-pair-migration.sqlite3"
    candidate = _fee_pair_candidate(run_id="committed-v16-history")
    token = "v16-history-owner-" + "h" * 40
    journal = ExecutionDecisionJournal(path)
    journal.register_fee_pair_required_scope("account-a", "strategy-a")
    legacy = journal.reserve_fee_pair_candidate(candidate, owner_token=token, ttl_seconds=10)
    before = {
        table: tuple(
            tuple(row)
            for row in journal._connection.execute(
                "SELECT * FROM {} WHERE candidate_id=?".format(table),
                (legacy.candidate_id,),
            )
        )
        for table in (
            "execution_fee_pair_candidates",
            "execution_fee_pair_candidate_events",
            "execution_fee_pair_candidate_capacity_reservations",
        )
    }
    journal.close()

    # Reconstruct the committed v16 schema on a synthetic fixture. The v17
    # workflow tables did not exist at that version; v16 candidate history did.
    with sqlite3.connect(path) as connection:
        _drop_v17_fee_pair_workflow_tables(connection)
        connection.execute("PRAGMA user_version = 16")

    migrated = ExecutionDecisionJournal(path)
    try:
        assert migrated._connection.execute("PRAGMA user_version").fetchone()[0] == ExecutionDecisionJournal._SCHEMA_VERSION
        for table, expected in before.items():
            actual = tuple(
                tuple(row)
                for row in migrated._connection.execute(
                    "SELECT * FROM {} WHERE candidate_id=?".format(table),
                    (legacy.candidate_id,),
                )
            )
            assert actual == expected
        assert migrated.fee_pair_candidate(legacy.candidate_id).state == "RESERVED"
        with pytest.raises(
            ExecutionDecisionJournalError,
            match="FEE_PAIR_SCOPE_LEGACY_CANDIDATE_QUARANTINED",
        ):
            migrated.reserve_fee_pair_workflow_candidate(
                candidate, owner_token=token, ttl_seconds=10
            )
        assert migrated._connection.execute(
            "SELECT COUNT(*) FROM execution_fee_pair_workflows"
        ).fetchone()[0] == 0
    finally:
        migrated.close()


def test_capacity_usage_concurrent_v8_openers_backfill_once(tmp_path, monkeypatch):
    path = tmp_path / "capacity-v8-concurrent-migration.sqlite3"
    journal = ExecutionDecisionJournal(path)
    journal.record_decision(_decision_key("capacity-concurrent-migration"), {"signal": "flat"})
    capacity_limits = journal.durable_capacity_limits
    journal.close()

    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE execution_decision_capacity_usage")
        _drop_v12_durable_capacity_tables(connection)
        connection.execute("PRAGMA user_version = 8")

    def schema_instance(connection):
        instance = object.__new__(ExecutionDecisionJournal)
        instance._connection = connection
        instance._lock = RLock()
        instance._closed = False
        instance._failed_closed = False
        instance.max_decision_records = 100000
        instance.settlement_decision_reserve_records = 4096
        instance.max_decision_bytes = 536870912
        instance.settlement_decision_reserve_bytes = 67108864
        instance.durable_capacity_limits = capacity_limits
        return instance

    connections = [
        sqlite3.connect(path, isolation_level=None, check_same_thread=False) for _ in range(2)
    ]
    for connection in connections:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
        connection.execute("PRAGMA foreign_keys = ON")
    first, second = (schema_instance(connection) for connection in connections)

    second_pre_migration = Event()
    allow_second = Event()
    paused = False

    def pause_second_before_ddl(statement):
        nonlocal paused
        normalized = " ".join(statement.upper().split())
        if not paused and normalized.startswith("CREATE TABLE IF NOT EXISTS EXECUTION_DECISIONS"):
            paused = True
            second_pre_migration.set()
            allow_second.wait(10)

    second._connection.set_trace_callback(pause_second_before_ddl)
    original_backfill = ExecutionDecisionJournal._backfill_decision_capacity_usage
    backfill_calls = []

    def count_backfill(cursor):
        backfill_calls.append("called")
        return original_backfill(cursor)

    monkeypatch.setattr(
        ExecutionDecisionJournal,
        "_backfill_decision_capacity_usage",
        staticmethod(count_backfill),
    )
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            second_future = pool.submit(second._create_schema)
            assert second_pre_migration.wait(10)
            first_future = pool.submit(first._create_schema)
            first_future.result(timeout=10)
            allow_second.set()
            second_future.result(timeout=10)
    finally:
        allow_second.set()
        for connection in connections:
            connection.close()

    assert len(backfill_calls) == 1
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == ExecutionDecisionJournal._SCHEMA_VERSION
        usage = connection.execute(
            """SELECT capacity_class,record_count
               FROM execution_decision_capacity_usage ORDER BY capacity_class"""
        ).fetchall()
    assert usage == [("BASE", 1), ("SETTLEMENT", 0)]


def test_capacity_usage_update_rolls_back_with_decision(tmp_path):
    path = tmp_path / "capacity-rollback.sqlite3"
    journal = ExecutionDecisionJournal(path)
    baseline = journal.decision_capacity_snapshot()
    journal.close()
    with sqlite3.connect(path) as connection:
        connection.execute(
            """CREATE TRIGGER reject_capacity_usage_update
               BEFORE UPDATE ON execution_decision_capacity_usage
               BEGIN SELECT RAISE(ABORT,'synthetic capacity failure'); END"""
        )

    failing = ExecutionDecisionJournal(path)
    with pytest.raises(ExecutionDecisionJournalError, match="JOURNAL_WRITE_FAILED"):
        failing.record_decision(_decision_key("capacity-rollback"), {"signal": "flat"})
    failing.close()

    recovered = ExecutionDecisionJournal(path)
    usage = recovered.decision_capacity_snapshot()
    assert usage.base_record_count == baseline.base_record_count == 0
    assert usage.base_payload_bytes == baseline.base_payload_bytes == 0
    assert usage.settlement_record_count == baseline.settlement_record_count == 0
    assert usage.settlement_payload_bytes == baseline.settlement_payload_bytes == 0
    assert (
        recovered._connection.execute("SELECT COUNT(*) FROM execution_decisions").fetchone()[0] == 0
    )
    recovered.close()


def test_noop_capacity_queries_are_bounded_and_indexed(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "capacity-bounded-queries.sqlite3")
    statements = []
    journal._connection.set_trace_callback(statements.append)
    journal.record_decision(_decision_key("capacity-bounded-noop"), {"signal": "flat"})
    snapshot = journal.decision_capacity_snapshot()
    journal._connection.set_trace_callback(None)

    traced = [" ".join(statement.upper().split()) for statement in statements]
    assert any(
        "SELECT RECORD_COUNT,PAYLOAD_BYTES FROM EXECUTION_DECISION_CAPACITY_USAGE" in statement
        for statement in traced
    )
    assert any("UPDATE EXECUTION_DECISION_CAPACITY_USAGE" in statement for statement in traced)
    assert not any("EXECUTION_DECISION_SLOTS" in statement for statement in traced)
    assert not any(
        ("COUNT(*)" in statement or "SUM(" in statement) and "EXECUTION_DECISIONS" in statement
        for statement in traced
    )
    assert snapshot.base_record_count == 1
    assert snapshot.settlement_record_count == 0

    plan = journal._connection.execute(
        """EXPLAIN QUERY PLAN SELECT record_count,payload_bytes
           FROM execution_decision_capacity_usage WHERE capacity_class=?""",
        ("BASE",),
    ).fetchall()
    details = " ".join(row["detail"].upper() for row in plan)
    assert "SEARCH EXECUTION_DECISION_CAPACITY_USAGE" in details
    assert "CAPACITY_CLASS=?" in details
    assert "SCAN EXECUTION_DECISION_CAPACITY_USAGE" not in details
    journal.close()


def test_capacity_usage_updates_are_serialized_across_connections(tmp_path):
    path = tmp_path / "capacity-connections.sqlite3"
    first = ExecutionDecisionJournal(path, max_decision_records=100)
    second = ExecutionDecisionJournal(path, max_decision_records=100)

    def record(journal, ordinal):
        return journal.record_decision(
            _decision_key("capacity-connection-{}".format(ordinal)),
            {"ordinal": ordinal, "signal": "flat"},
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [
            pool.submit(record, first if ordinal % 2 == 0 else second, ordinal)
            for ordinal in range(40)
        ]
        records = [future.result(timeout=30) for future in futures]
    assert len({record.decision_id for record in records}) == 40
    for journal in (first, second):
        usage = journal.decision_capacity_snapshot()
        assert usage.base_record_count == 40
        assert usage.settlement_record_count == 0
    first.close()
    second.close()


def test_decision_byte_high_water_is_transactional_and_replay_free(tmp_path):
    journal = ExecutionDecisionJournal(
        tmp_path / "decision-bytes.sqlite3",
        max_decision_records=10,
        settlement_decision_reserve_records=2,
        max_decision_bytes=1024,
        settlement_decision_reserve_bytes=1024,
    )
    key = _decision_key("decision-byte-a")
    first = journal.record_decision(key, {"note": "x" * 400})
    assert journal.record_decision(key, {"note": "x" * 400}).decision_id == first.decision_id
    with pytest.raises(ExecutionDecisionJournalError, match="DECISION_CAPACITY_HIGH_WATER"):
        journal.record_decision(_decision_key("decision-byte-b"), {"note": "y" * 400})
    assert journal.decision(first.decision_id) is not None
    usage = journal.decision_capacity_snapshot()
    assert usage.base_record_count == 1
    assert usage.base_payload_bytes <= usage.base_payload_byte_limit == 1024
    journal.close()


def test_schema_v1_migration_preserves_original_dispatch_outcome(tmp_path):
    path = tmp_path / "schema-v1.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """CREATE TABLE execution_decision_intents (
                   intent_id TEXT PRIMARY KEY,
                   decision_id TEXT NOT NULL,
                   intent_key_json TEXT NOT NULL,
                   economic_payload_json TEXT NOT NULL,
                   original_identity_json TEXT NOT NULL,
                   owner_intent_id TEXT,
                   state TEXT NOT NULL,
                   provider_identity_json TEXT,
                   outcome_code TEXT,
                   dispatch_result_json TEXT,
                   created_at_ns INTEGER NOT NULL,
                   updated_at_ns INTEGER NOT NULL
               )"""
        )
        connection.execute(
            """INSERT INTO execution_decision_intents VALUES
               ('intent-v1', 'decision-v1',
                    '{"action":"SUBMIT","instrument":"SIM-IF-1","leg":0,"position_effect":"OPEN","side":"BUY"}',
                '{"quantity":"1"}', '{"order_ref":9}', NULL, 'UNKNOWN', '{}',
                'connection_lost', '{"outcome_code":"connection_lost","provider_identity":{}}', 1, 2)"""
        )
        connection.execute("PRAGMA user_version = 1")

    journal = ExecutionDecisionJournal(path)
    intent = journal.intent("intent-v1")
    assert intent is not None
    assert intent.state == "UNKNOWN"
    assert intent.dispatch_state == "UNKNOWN"
    assert intent.outcome_code == "connection_lost"
    assert journal._connection.execute("PRAGMA user_version").fetchone()[0] == ExecutionDecisionJournal._SCHEMA_VERSION
    journal.close()


def test_schema_v2_migrates_grid_and_run_budget_tables(tmp_path):
    path = tmp_path / "schema-v2.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """CREATE TABLE execution_decision_intents (
                   intent_id TEXT PRIMARY KEY,
                   decision_id TEXT NOT NULL,
                   intent_key_json TEXT NOT NULL,
                   economic_payload_json TEXT NOT NULL,
                   original_identity_json TEXT NOT NULL,
                   owner_intent_id TEXT,
                   state TEXT NOT NULL,
                   dispatch_state TEXT,
                   provider_identity_json TEXT,
                   outcome_code TEXT,
                   dispatch_result_json TEXT,
                   created_at_ns INTEGER NOT NULL,
                   updated_at_ns INTEGER NOT NULL
               )"""
        )
        connection.execute("PRAGMA user_version = 2")

    journal = ExecutionDecisionJournal(path)
    assert journal._connection.execute("PRAGMA user_version").fetchone()[0] == ExecutionDecisionJournal._SCHEMA_VERSION
    names = {
        row["name"]
        for row in journal._connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    assert "execution_grid_cursors" in names
    assert "execution_run_order_budgets" in names
    journal.close()


def test_schema_v7_startup_backfills_native_ref_without_rewriting_dispatch(tmp_path):
    path = tmp_path / "schema-v7-native-index.sqlite3"
    journal = ExecutionDecisionJournal(path)
    decision = journal.record_decision(
        _decision_key("native-v7"),
        _decision_payload(),
        intent_keys=(_intent_key(),),
    )
    intent = journal.prepare_intent(
        decision.decision_id,
        _intent_key(),
        _order_payload(),
        original_identity=_native_order_identity("417"),
    )
    journal.claim_dispatch(intent.intent_id)
    unknown = journal.record_dispatch_result(
        intent.intent_id,
        state="UNKNOWN",
        provider_identity={"front_id": 13, "session_id": 7},
        outcome_code="connection_lost",
    )
    journal.close()

    with sqlite3.connect(path) as connection:
        original_rows = connection.execute(
            """SELECT original_identity_json, state, dispatch_state,
                      provider_identity_json, outcome_code, dispatch_result_json
               FROM execution_decision_intents WHERE intent_id=?""",
            (intent.intent_id,),
        ).fetchone()
        connection.execute(
            "DELETE FROM execution_native_intent_identities WHERE intent_id=?",
            (intent.intent_id,),
        )
        _drop_v12_durable_capacity_tables(connection)
        connection.execute("PRAGMA user_version = 7")

    recovered = ExecutionDecisionJournal(path)
    indexed = recovered.intent_by_native_order_ref(
        account_scope="account-a",
        strategy_scope="strategy-a",
        trading_day="20261024",
        instrument="SIM-IF-1",
        exchange="CFFEX",
        order_ref="417",
    )
    assert indexed == unknown
    assert recovered.intent(intent.intent_id) == unknown
    assert recovered._connection.execute("PRAGMA user_version").fetchone()[0] == ExecutionDecisionJournal._SCHEMA_VERSION
    recovered.close()

    with sqlite3.connect(path) as connection:
        recovered_rows = connection.execute(
            """SELECT original_identity_json, state, dispatch_state,
                      provider_identity_json, outcome_code, dispatch_result_json
               FROM execution_decision_intents WHERE intent_id=?""",
            (intent.intent_id,),
        ).fetchone()
        assert recovered_rows == original_rows
        assert connection.execute(
            "SELECT intent_id FROM execution_native_intent_identities"
        ).fetchall() == [(intent.intent_id,)]


def test_legacy_order_ref_without_ctp_identity_stays_unindexed(tmp_path):
    path = tmp_path / "legacy-order-ref.sqlite3"
    journal = ExecutionDecisionJournal(path)
    _, intent = _prepare(journal, original_identity={"order_ref": 9})
    journal.close()

    with sqlite3.connect(path) as connection:
        _drop_v12_durable_capacity_tables(connection)
        connection.execute("PRAGMA user_version = 7")

    recovered = ExecutionDecisionJournal(path)
    assert recovered.intent(intent.intent_id) is not None
    assert (
        recovered.intent_by_native_order_ref(
            account_scope="account-a",
            strategy_scope="strategy-a",
            trading_day="20261024",
            instrument="SIM-IF-1",
            exchange="CFFEX",
            order_ref="9",
        )
        is None
    )
    assert (
        recovered._connection.execute(
            "SELECT COUNT(*) FROM execution_native_intent_identities"
        ).fetchone()[0]
        == 0
    )
    recovered.close()


def test_native_order_ref_collision_rolls_back_second_intent(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "native-ref-collision.sqlite3")
    first_key = _intent_key("SIM-IF-1")
    first_decision = journal.record_decision(
        _decision_key("native-collision-a"),
        _decision_payload(),
        intent_keys=(first_key,),
    )
    first = journal.prepare_intent(
        first_decision.decision_id,
        first_key,
        _order_payload(),
        original_identity=_native_order_identity("9001"),
    )
    second_key = _intent_key("SIM-IF-2")
    second_decision = journal.record_decision(
        _decision_key("native-collision-b"),
        _decision_payload(),
        intent_keys=(second_key,),
    )

    with pytest.raises(ExecutionDecisionJournalError, match="NATIVE_ORDER_IDENTITY_CONFLICT"):
        journal.prepare_intent(
            second_decision.decision_id,
            second_key,
            _order_payload(),
            original_identity=_native_order_identity("9001", instrument="SIM-IF-2"),
        )

    assert (
        journal.intent_by_native_order_ref(
            account_scope="account-a",
            strategy_scope="strategy-a",
            trading_day="20261024",
            instrument="SIM-IF-1",
            exchange="CFFEX",
            order_ref="9001",
        ).intent_id
        == first.intent_id
    )
    assert (
        journal._connection.execute(
            "SELECT COUNT(*) FROM execution_decision_intents WHERE decision_id=?",
            (second_decision.decision_id,),
        ).fetchone()[0]
        == 0
    )
    assert journal.active_instrument_owner("account-a", "SIM-IF-2") is None
    journal.close()


def test_v7_native_ref_collision_aborts_backfill_without_mutating_intents(tmp_path):
    path = tmp_path / "schema-v7-native-collision.sqlite3"
    journal = ExecutionDecisionJournal(path)
    first_key = _intent_key("SIM-IF-1")
    first_decision = journal.record_decision(
        _decision_key("native-migration-collision-a"),
        _decision_payload(),
        intent_keys=(first_key,),
    )
    first = journal.prepare_intent(
        first_decision.decision_id,
        first_key,
        _order_payload(),
        original_identity=_native_order_identity("9101"),
    )
    second_key = _intent_key("SIM-IF-2")
    second_decision = journal.record_decision(
        _decision_key("native-migration-collision-b"),
        _decision_payload(),
        intent_keys=(second_key,),
    )
    second = journal.prepare_intent(
        second_decision.decision_id,
        second_key,
        _order_payload(),
        original_identity=_native_order_identity("9102", instrument="SIM-IF-2"),
    )
    journal.claim_dispatch(first.intent_id)
    journal.record_dispatch_result(first.intent_id, state="UNKNOWN", outcome_code="connection_lost")
    journal.claim_dispatch(second.intent_id)
    journal.record_dispatch_result(
        second.intent_id, state="UNKNOWN", outcome_code="connection_lost"
    )
    journal.close()

    with sqlite3.connect(path) as connection:
        second_row = connection.execute(
            "SELECT original_identity_json FROM execution_decision_intents WHERE intent_id=?",
            (second.intent_id,),
        ).fetchone()
        second_identity = json.loads(second_row[0])
        second_identity["order_ref"] = "9101"
        connection.execute(
            "UPDATE execution_decision_intents SET original_identity_json=? WHERE intent_id=?",
            (json.dumps(second_identity, sort_keys=True, separators=(",", ":")), second.intent_id),
        )
        connection.execute("DELETE FROM execution_native_intent_identities")
        _drop_v12_durable_capacity_tables(connection)
        connection.execute("PRAGMA user_version = 7")
        raw_conflict = connection.execute(
            """SELECT intent_id, original_identity_json, state, dispatch_state,
                      outcome_code, dispatch_result_json
               FROM execution_decision_intents ORDER BY intent_id"""
        ).fetchall()

    with pytest.raises(ExecutionDecisionJournalError, match="NATIVE_ORDER_IDENTITY_CONFLICT"):
        ExecutionDecisionJournal(path)

    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 7
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM execution_native_intent_identities"
            ).fetchone()[0]
            == 0
        )
        assert (
            connection.execute(
                """SELECT intent_id, original_identity_json, state, dispatch_state,
                      outcome_code, dispatch_result_json
               FROM execution_decision_intents ORDER BY intent_id"""
            ).fetchall()
            == raw_conflict
        )


def test_multileg_partial_dispatch_is_sequential_and_unknown_never_retries(tmp_path):
    path = tmp_path / "multi.sqlite3"
    journal = ExecutionDecisionJournal(path, max_pending_intents=4)
    keys = (
        _intent_key("SIM-IF-1", leg=0),
        _intent_key("SIM-IF-2", leg=1, side="SELL", effect="CLOSE"),
    )
    decision = journal.record_decision(_decision_key(), _decision_payload(), intent_keys=keys)
    first = journal.prepare_intent(
        decision.decision_id,
        keys[0],
        _order_payload(),
        original_identity={"backtrader_order_ref": 10, "client_order_id": "bt-10"},
    )
    first_claim = journal.claim_dispatch(first.intent_id)
    assert first_claim is not None
    assert first_claim.intent.state == "DISPATCHING"
    second = journal.prepare_intent(
        decision.decision_id,
        keys[1],
        _order_payload(quantity="1"),
        original_identity={"backtrader_order_ref": 11, "client_order_id": "bt-11"},
    )
    with pytest.raises(ExecutionDecisionJournalError, match="PRIOR_INTENT_NOT_KNOWN"):
        journal.claim_dispatch(second.intent_id)

    claim = first_claim
    assert claim.intent.original_identity["client_order_id"] == "bt-10"
    with pytest.raises(TypeError):
        claim.intent.original_identity["client_order_id"] = "changed"
    assert journal.claim_dispatch(first.intent_id) is None
    unknown = journal.record_dispatch_result(
        first.intent_id, state="UNKNOWN", outcome_code="connection_lost"
    )
    assert unknown.state == "UNKNOWN"
    assert journal.claim_dispatch(first.intent_id) is None
    with pytest.raises(ExecutionDecisionJournalError, match="PRIOR_INTENT_NOT_KNOWN"):
        journal.claim_dispatch(second.intent_id)
    journal.close()

    recovered = ExecutionDecisionJournal(path)
    recovered_first = recovered.intent(first.intent_id)
    assert recovered_first is not None
    assert recovered_first.state == "UNKNOWN"
    assert recovered_first.original_identity == {
        "backtrader_order_ref": 10,
        "client_order_id": "bt-10",
    }
    assert recovered.claim_dispatch(first.intent_id) is None
    recovered.close()


def test_same_instrument_close_open_reversal_is_two_decisions(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "reversal.sqlite3")
    reversal = (
        _intent_key("SIM-IF-1", leg=0, side="SELL", effect="CLOSE"),
        _intent_key("SIM-IF-1", leg=1, side="BUY", effect="OPEN"),
    )
    with pytest.raises(ExecutionDecisionJournalError, match="DUPLICATE_INSTRUMENT_INTENT"):
        journal.record_decision(_decision_key(), _decision_payload(), intent_keys=reversal)
    journal.close()


@pytest.mark.parametrize("final_state", ["DISPATCHING", "UNKNOWN"])
def test_fresh_process_recovery_never_reclaims_original_dispatch(tmp_path, final_state):
    path = tmp_path / (final_state.lower() + ".sqlite3")
    journal = ExecutionDecisionJournal(path)
    _, intent = _prepare(
        journal,
        original_identity={"backtrader_order_ref": 77, "provider_client_id": "client-77"},
    )
    assert journal.claim_dispatch(intent.intent_id) is not None
    if final_state == "UNKNOWN":
        journal.record_dispatch_result(intent.intent_id, state="UNKNOWN")
    journal.close()

    child = r"""
import json, sys
from backtrader.stores.execution_decision_journal import ExecutionDecisionJournal
journal = ExecutionDecisionJournal(sys.argv[1])
intent = journal.intent(sys.argv[2])
claim = journal.claim_dispatch(sys.argv[2])
assert intent is not None
print(json.dumps({"state": intent.state, "identity": dict(intent.original_identity),
                  "claimed": claim is not None}, sort_keys=True))
journal.close()
"""
    completed = subprocess.run(
        [sys.executable, "-c", child, str(path), intent.intent_id],
        cwd=os.getcwd(),
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    report = json.loads(completed.stdout)
    assert report == {
        "state": final_state,
        "identity": {"backtrader_order_ref": 77, "provider_client_id": "client-77"},
        "claimed": False,
    }


def test_cross_run_owner_survives_known_ack_until_terminal_position_reconcile(tmp_path):
    path = tmp_path / "owners.sqlite3"
    journal = ExecutionDecisionJournal(path)
    open_key = _intent_key("SIM-IF-1", leg=0, side="BUY", effect="OPEN")
    first_decision, opening = _prepare(
        journal,
        key=_decision_key("run-open"),
        intent_key=open_key,
        original_identity={"backtrader_order_ref": 101, "client_order_id": "open-101"},
    )
    assert journal.claim_dispatch(opening.intent_id) is not None
    known = journal.record_dispatch_result(
        opening.intent_id,
        state="KNOWN",
        provider_identity={"order_id": "sim-5001"},
        outcome_code="accepted",
    )
    assert known.state == "KNOWN"
    owner = journal.active_instrument_owner("account-a", "SIM-IF-1")
    assert owner is not None and owner.intent_id == opening.intent_id

    close_key = _intent_key("SIM-IF-1", leg=0, side="SELL", effect="CLOSE")
    next_decision = journal.record_decision(
        _decision_key("run-close"),
        _decision_payload(direction="close"),
        intent_keys=(close_key,),
    )
    with pytest.raises(ExecutionDecisionJournalError, match="INSTRUMENT_OWNER_ACTIVE"):
        journal.prepare_intent(next_decision.decision_id, close_key, _order_payload())

    with pytest.raises(ExecutionDecisionJournalError, match="INTENT_NOT_RECONCILED_TERMINAL"):
        journal.release_instrument_owner(
            opening.intent_id,
            reconciliation_id="recon-1",
        )
    open_reconciliation = _record_terminal_reconciliation(
        journal,
        opening,
        reconciliation_id="recon-1",
        query_id="query-open-1",
        event_id="sim-event-5001-filled",
        snapshot_id="position-after-open-1",
        position_flat=False,
        provider_order_id="sim-5001",
    )
    resolution = journal.release_instrument_owner(
        opening.intent_id,
        reconciliation_id=open_reconciliation.reconciliation_id,
    )
    assert resolution.position_flat is False
    assert journal.active_instrument_owner("account-a", "SIM-IF-1") is None

    close_intent = journal.prepare_intent(
        next_decision.decision_id,
        close_key,
        _order_payload(quantity="2", price="4010"),
        original_identity={"backtrader_order_ref": 102, "client_order_id": "close-102"},
    )
    assert close_intent.state == "PREPARED"
    assert close_intent.owner_intent_id is None
    assert journal.claim_dispatch(close_intent.intent_id) is not None
    close_known = journal.record_dispatch_result(
        close_intent.intent_id,
        state="KNOWN",
        provider_identity={"order_id": "sim-5002"},
        outcome_code="accepted",
    )
    assert close_known.state == "KNOWN"
    close_reconciliation = _record_terminal_reconciliation(
        journal,
        close_intent,
        reconciliation_id="recon-2",
        query_id="query-close-1",
        event_id="sim-event-5002-filled",
        snapshot_id="position-after-close-1",
        position_flat=True,
        provider_order_id="sim-5002",
    )
    close_resolution = journal.release_instrument_owner(
        close_intent.intent_id,
        reconciliation_id=close_reconciliation.reconciliation_id,
    )
    assert close_resolution.position_flat is True
    assert journal.active_instrument_owner("account-a", "SIM-IF-1") is None
    journal.close()


def test_unknown_owner_blocks_same_instrument_in_a_new_logical_run(tmp_path):
    path = tmp_path / "unknown-owner.sqlite3"
    journal = ExecutionDecisionJournal(path)
    _, original = _prepare(journal)
    journal.claim_dispatch(original.intent_id)
    journal.record_dispatch_result(original.intent_id, state="UNKNOWN")
    journal.close()

    recovered = ExecutionDecisionJournal(path)
    owner = recovered.active_instrument_owner("account-a", "SIM-IF-1")
    assert owner is not None
    assert owner.intent_id == original.intent_id
    assert owner.state == "UNKNOWN"
    recovered_intent = recovered.intent(original.intent_id)
    assert recovered_intent.dispatch_state == "UNKNOWN"
    assert recovered_intent.provider_identity == {}
    next_key = _intent_key("SIM-IF-1", side="SELL", effect="CLOSE")
    next_decision = recovered.record_decision(
        _decision_key("run-next"), _decision_payload(), intent_keys=(next_key,)
    )
    with pytest.raises(ExecutionDecisionJournalError, match="INSTRUMENT_OWNER_ACTIVE"):
        recovered.prepare_intent(next_decision.decision_id, next_key, _order_payload())
    recovered.close()


def test_dispatching_crash_recovery_rejects_unproven_terminal_and_keeps_owner(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "dispatching-no-fill.sqlite3")
    _decision, intent = _prepare(
        journal,
        original_identity={
            "backtrader_order_ref": 41,
            "order_ref": "501",
            "instrument_id": "SIM-IF-1",
            "exchange_id": "CFFEX",
            "trading_day": "20261024",
            "operation": "insert",
        },
    )
    assert journal.claim_dispatch(intent.intent_id) is not None

    with pytest.raises(
        ExecutionDecisionJournalError,
        match="DISPATCHING_NO_FILL_EVIDENCE_MISMATCH",
    ):
        journal.record_dispatching_no_fill_terminal(
            intent.intent_id,
            reconciliation_id="crash-recovery-unproven",
            query_id="orders-query-unproven",
            provider_identity={},
            terminal_state="CANCELLED",
            terminal_event_id="orders-query-unproven",
            position_snapshot_id="positions-snapshot-unproven",
            expected_original_identity=intent.original_identity,
        )

    current = journal.intent(intent.intent_id)
    owner = journal.active_instrument_owner("account-a", intent.key.instrument)
    assert current is not None
    assert current.state == "DISPATCHING"
    assert current.dispatch_state is None
    assert current.provider_identity is None
    assert current.outcome_code is None
    assert owner is not None and owner.intent_id == intent.intent_id
    with pytest.raises(
        ExecutionDecisionJournalError,
        match="INTENT_NOT_RECONCILED_TERMINAL",
    ):
        journal.release_instrument_owner(
            intent.intent_id,
            reconciliation_id="crash-recovery-unproven",
        )
    journal.close()


def test_unknown_query_resolution_is_append_only_and_allows_close_after_fill(tmp_path):
    path = tmp_path / "resolve-unknown.sqlite3"
    journal = ExecutionDecisionJournal(path)
    _, opening = _prepare(
        journal,
        original_identity={"backtrader_order_ref": 81, "client_order_id": "client-81"},
    )
    assert journal.claim_dispatch(opening.intent_id) is not None
    original_unknown = journal.record_dispatch_result(
        opening.intent_id,
        state="UNKNOWN",
        outcome_code="connection_lost_after_send",
    )
    journal.close()

    recovered = ExecutionDecisionJournal(path)
    unknown_query = recovered.record_reconciliation(
        opening.intent_id,
        reconciliation_id="recon-query-unknown",
        query_id="provider-query-1",
        state="UNKNOWN",
        outcome_code="order_not_visible_yet",
    )
    replay_unknown = recovered.record_reconciliation(
        opening.intent_id,
        reconciliation_id="recon-query-unknown",
        query_id="provider-query-1",
        state="UNKNOWN",
        outcome_code="order_not_visible_yet",
    )
    assert replay_unknown == unknown_query
    assert recovered.intent(opening.intent_id).state == "UNKNOWN"
    assert recovered.intent(opening.intent_id).dispatch_state == "UNKNOWN"
    assert recovered.claim_dispatch(opening.intent_id) is None
    with pytest.raises(ExecutionDecisionJournalError, match="INTENT_NOT_RECONCILED_TERMINAL"):
        recovered.release_instrument_owner(
            opening.intent_id, reconciliation_id=unknown_query.reconciliation_id
        )
    with pytest.raises(ExecutionDecisionJournalError, match="RECONCILIATION_CONFLICT"):
        recovered.record_reconciliation(
            opening.intent_id,
            reconciliation_id="recon-query-unknown",
            query_id="provider-query-1",
            state="KNOWN",
            provider_identity={"order_id": "sim-810"},
        )
    with pytest.raises(ExecutionDecisionJournalError, match="RECONCILIATION_QUERY_CONFLICT"):
        recovered.record_reconciliation(
            opening.intent_id,
            reconciliation_id="different-receipt-same-query",
            query_id="provider-query-1",
            state="UNKNOWN",
            outcome_code="order_not_visible_yet",
        )

    filled = _record_terminal_reconciliation(
        recovered,
        opening,
        reconciliation_id="recon-query-filled",
        query_id="provider-query-2",
        event_id="sim-event-810-filled",
        snapshot_id="position-after-open-810",
        position_flat=False,
        provider_order_id="sim-810",
    )
    assert filled.original_identity == {
        "backtrader_order_ref": 81,
        "client_order_id": "client-81",
    }
    with pytest.raises(TypeError):
        filled.original_identity["client_order_id"] = "mutated"
    resolved_intent = recovered.intent(opening.intent_id)
    assert resolved_intent.state == "KNOWN"
    assert resolved_intent.dispatch_state == "UNKNOWN"
    assert resolved_intent.provider_identity == {}
    assert resolved_intent.outcome_code == "connection_lost_after_send"
    assert recovered.claim_dispatch(opening.intent_id) is None
    assert (
        recovered.record_reconciliation(
            opening.intent_id,
            reconciliation_id="recon-query-filled",
            query_id="provider-query-2",
            state="KNOWN",
            provider_identity={"order_id": "sim-810"},
            outcome_code="filled",
            terminal_state="FILLED",
            terminal_event_id="sim-event-810-filled",
            position_snapshot_id="position-after-open-810",
            position_flat=False,
        )
        == filled
    )
    with pytest.raises(ExecutionDecisionJournalError, match="RECONCILIATION_CONFLICT"):
        recovered.record_reconciliation(
            opening.intent_id,
            reconciliation_id="recon-query-filled",
            query_id="provider-query-2",
            state="KNOWN",
            provider_identity={"order_id": "sim-810"},
            outcome_code="filled",
            terminal_state="FILLED",
            terminal_event_id="different-event",
            position_snapshot_id="position-after-open-810",
            position_flat=False,
        )
    with pytest.raises(ExecutionDecisionJournalError, match="INTENT_NOT_RECONCILED_TERMINAL"):
        recovered.release_instrument_owner(
            opening.intent_id, reconciliation_id=unknown_query.reconciliation_id
        )
    resolution = recovered.release_instrument_owner(
        opening.intent_id, reconciliation_id=filled.reconciliation_id
    )
    assert resolution.position_flat is False
    assert resolution.terminal_event_id == "sim-event-810-filled"
    assert recovered.active_instrument_owner("account-a", "SIM-IF-1") is None

    close_key = _intent_key("SIM-IF-1", side="SELL", effect="CLOSE")
    close_decision = recovered.record_decision(
        _decision_key("run-close-after-recovery"),
        _decision_payload(direction="close"),
        intent_keys=(close_key,),
    )
    close_intent = recovered.prepare_intent(
        close_decision.decision_id,
        close_key,
        _order_payload(quantity="2", price="4000"),
        original_identity={"backtrader_order_ref": 82, "client_order_id": "client-82"},
    )
    assert recovered.claim_dispatch(close_intent.intent_id) is not None
    recovered.record_dispatch_result(
        close_intent.intent_id,
        state="KNOWN",
        provider_identity={"order_id": "sim-811"},
        outcome_code="accepted",
    )
    close_reconciliation = _record_terminal_reconciliation(
        recovered,
        close_intent,
        reconciliation_id="recon-close-flat",
        query_id="provider-query-3",
        event_id="sim-event-811-filled",
        snapshot_id="position-after-close-811",
        position_flat=True,
        provider_order_id="sim-811",
    )
    assert (
        recovered.release_instrument_owner(
            close_intent.intent_id,
            reconciliation_id=close_reconciliation.reconciliation_id,
        ).position_flat
        is True
    )
    assert original_unknown.dispatch_state == "UNKNOWN"
    recovered.close()


def test_cancel_is_bound_to_active_owner_and_does_not_replace_it(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "cancel.sqlite3")
    _, submit = _prepare(journal)
    journal.claim_dispatch(submit.intent_id)
    journal.record_dispatch_result(
        submit.intent_id, state="KNOWN", provider_identity={"order_id": "sim-10"}
    )

    cancel_key = _intent_key("SIM-IF-1", action="CANCEL", leg=0)
    cancel_decision = journal.record_decision(
        _decision_key(kind="cancel"),
        {"target_backtrader_order_ref": 41},
        intent_keys=(cancel_key,),
    )
    with pytest.raises(ExecutionDecisionJournalError, match="CANCEL_OWNER_MISMATCH"):
        journal.prepare_intent(
            cancel_decision.decision_id,
            cancel_key,
            {"provider_order_id": "sim-10"},
            owner_intent_id="wrong-owner",
        )
    cancel = journal.prepare_intent(
        cancel_decision.decision_id,
        cancel_key,
        {"provider_order_id": "sim-10"},
        original_identity={"backtrader_order_ref": 41, "provider_order_id": "sim-10"},
        owner_intent_id=submit.intent_id,
    )
    assert cancel.owner_intent_id == submit.intent_id
    assert journal.claim_dispatch(cancel.intent_id) is not None
    assert journal.active_instrument_owner("account-a", "SIM-IF-1").intent_id == submit.intent_id
    journal.close()


def _prepare_known_ctp_submit_for_cancel(journal, *, suffix="safe", omit_sys_id=False):
    instrument = "SIM-CTP-{}".format(suffix)
    order_ref = "94"
    order_sys_id = None if omit_sys_id else "sys-{}".format(suffix)
    decision_key = ExecutionDecisionKey(
        account_scope="account-a",
        strategy_scope="strategy-a",
        logical_run_id="run-{}".format(suffix),
        cohort_id="cohort-{}".format(suffix),
        close_time="2026-10-20T10:08:00Z",
        decision_kind="alpha003-rebalance",
    )
    submit_key = _intent_key(instrument, side="BUY", effect="OPEN")
    decision = journal.record_decision(
        decision_key,
        {"signal": "known-ctp-submit"},
        intent_keys=(submit_key,),
    )
    submit = journal.prepare_intent(
        decision.decision_id,
        submit_key,
        {"instrument": instrument, "exchange": "SHFE", "target_id": "target"},
        original_identity={
            "backtrader_order_ref": 94,
            "operation": "insert",
            "instrument_id": instrument,
            "exchange_id": "SHFE",
            "order_ref": order_ref,
            "front_id": 4,
            "session_id": 7,
            "account_fingerprint": "account-fingerprint",
            "connection_generation": 3,
            "trading_day": "20261020",
        },
    )
    assert journal.claim_dispatch(submit.intent_id) is not None
    journal.record_dispatch_result(
        submit.intent_id,
        state="KNOWN",
        provider_identity={
            "operation": "insert",
            "instrument_id": instrument,
            "exchange_id": "SHFE",
            "order_ref": order_ref,
            "order_sys_id": order_sys_id,
            "front_id": 4,
            "session_id": 7,
        },
        outcome_code="accepted",
    )
    return submit, instrument, order_ref, order_sys_id


@pytest.mark.parametrize(
    "mismatch",
    (
        "order_ref",
        "order_sys_id",
        "backtrader_order_ref",
        "instrument_id",
        "exchange_id",
        "front_id",
        "session_id",
        "connection_generation",
        "account_fingerprint",
        "trading_day",
    ),
)
def test_ctp_cancel_prepare_rejects_provider_identity_not_owned_by_known_submit(
    tmp_path, mismatch
):
    journal = ExecutionDecisionJournal(tmp_path / "cancel-provider-{}.sqlite3".format(mismatch))
    try:
        submit, instrument, order_ref, order_sys_id = _prepare_known_ctp_submit_for_cancel(
            journal, suffix=mismatch
        )
        cancel_key = _intent_key(
            instrument, action="CANCEL", side="BUY", effect="OPEN"
        )
        cancel_decision = journal.record_decision(
            ExecutionDecisionKey(
                account_scope="account-a",
                strategy_scope="strategy-a",
                logical_run_id="cancel-run-{}".format(mismatch),
                cohort_id="cancel-cohort-{}".format(mismatch),
                close_time="2026-10-20T10:09:00Z",
                decision_kind="risk",
            ),
            {"signal": "cancel"},
            intent_keys=(cancel_key,),
        )
        identity = {
            "backtrader_order_ref": 95 if mismatch == "backtrader_order_ref" else 94,
            "operation": "cancel",
            "instrument_id": "wrong-instrument" if mismatch == "instrument_id" else instrument,
            "exchange_id": "DCE" if mismatch == "exchange_id" else "SHFE",
            "order_ref": "wrong-ref" if mismatch == "order_ref" else order_ref,
            "order_sys_id": "wrong-sysid" if mismatch == "order_sys_id" else order_sys_id,
            "front_id": 5 if mismatch == "front_id" else 4,
            "session_id": 8 if mismatch == "session_id" else 7,
            "account_fingerprint": (
                "other-account-fingerprint"
                if mismatch == "account_fingerprint"
                else "account-fingerprint"
            ),
            "connection_generation": 2 if mismatch == "connection_generation" else 3,
            "trading_day": "20261021" if mismatch == "trading_day" else "20261020",
            "owner_intent_id": submit.intent_id,
        }
        with pytest.raises(ExecutionDecisionJournalError, match="CANCEL_PROVIDER_IDENTITY_MISMATCH"):
            journal.prepare_intent(
                cancel_decision.decision_id,
                cancel_key,
                {"target_id": "target", "instrument": instrument, "exchange": "SHFE"},
                original_identity=identity,
                owner_intent_id=submit.intent_id,
            )
        assert journal._connection.execute(
            "SELECT COUNT(*) FROM execution_decision_intents WHERE decision_id=?",
            (cancel_decision.decision_id,),
        ).fetchone()[0] == 0
        owner = journal.active_instrument_owner("account-a", instrument)
        assert owner is not None and owner.intent_id == submit.intent_id
        assert owner.cancel_intent_id is None
    finally:
        journal.close()


def test_ctp_cancel_prepare_and_claim_accept_exact_parent_provider_identity(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "cancel-provider-exact.sqlite3")
    try:
        submit, instrument, order_ref, order_sys_id = _prepare_known_ctp_submit_for_cancel(
            journal
        )
        cancel_key = _intent_key(instrument, action="CANCEL", side="BUY", effect="OPEN")
        decision = journal.record_decision(
            ExecutionDecisionKey(
                account_scope="account-a",
                strategy_scope="strategy-a",
                logical_run_id="cancel-run-safe",
                cohort_id="cancel-cohort-safe",
                close_time="2026-10-20T10:09:00Z",
                decision_kind="risk",
            ),
            {"signal": "cancel"},
            intent_keys=(cancel_key,),
        )
        cancel = journal.prepare_intent(
            decision.decision_id,
            cancel_key,
            {"target_id": "target", "instrument": instrument, "exchange": "SHFE"},
            original_identity={
                "backtrader_order_ref": 94,
                "operation": "cancel",
                "instrument_id": instrument,
                "exchange_id": "SHFE",
                "order_ref": order_ref,
                "order_sys_id": order_sys_id,
                "front_id": 4,
                "session_id": 7,
                "account_fingerprint": "account-fingerprint",
                "connection_generation": 3,
                "trading_day": "20261020",
                "owner_intent_id": submit.intent_id,
            },
            owner_intent_id=submit.intent_id,
        )
        assert cancel.state == "PREPARED"
        claim = journal.claim_dispatch(cancel.intent_id)
        assert claim is not None
        assert claim.intent.intent_id == cancel.intent_id
    finally:
        journal.close()


def test_ctp_cancel_prepare_rejects_known_parent_without_provider_sysid(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "cancel-provider-missing-sysid.sqlite3")
    try:
        submit, instrument, order_ref, order_sys_id = _prepare_known_ctp_submit_for_cancel(
            journal, suffix="missing-sysid", omit_sys_id=True
        )
        assert order_sys_id is None
        cancel_key = _intent_key(instrument, action="CANCEL", side="BUY", effect="OPEN")
        decision = journal.record_decision(
            ExecutionDecisionKey(
                account_scope="account-a",
                strategy_scope="strategy-a",
                logical_run_id="cancel-run-missing-sysid",
                cohort_id="cancel-cohort-missing-sysid",
                close_time="2026-10-20T10:09:00Z",
                decision_kind="risk",
            ),
            {"signal": "cancel"},
            intent_keys=(cancel_key,),
        )
        with pytest.raises(ExecutionDecisionJournalError, match="CANCEL_PROVIDER_IDENTITY_MISMATCH"):
            journal.prepare_intent(
                decision.decision_id,
                cancel_key,
                {"target_id": "target", "instrument": instrument, "exchange": "SHFE"},
                original_identity={
                    "backtrader_order_ref": 94,
                    "operation": "cancel",
                    "instrument_id": instrument,
                    "exchange_id": "SHFE",
                    "order_ref": order_ref,
                    "order_sys_id": None,
                    "front_id": 4,
                    "session_id": 7,
                    "account_fingerprint": "account-fingerprint",
                    "connection_generation": 3,
                    "trading_day": "20261020",
                    "owner_intent_id": submit.intent_id,
                },
                owner_intent_id=submit.intent_id,
            )
        assert journal._connection.execute(
            "SELECT COUNT(*) FROM execution_decision_intents WHERE decision_id=?",
            (decision.decision_id,),
        ).fetchone()[0] == 0
        owner = journal.active_instrument_owner("account-a", instrument)
        assert owner is not None and owner.intent_id == submit.intent_id
        assert owner.cancel_intent_id is None
    finally:
        journal.close()


def test_execution_intent_snapshot_filters_account_before_bounded_limit_and_keeps_strategy_scope(
    tmp_path,
):
    journal = ExecutionDecisionJournal(tmp_path / "intent-snapshot-account-scope.sqlite3")
    try:
        # More rows than the bounded page from account B are deliberately
        # older than account A's rows. Filtering after LIMIT would hide A.
        for index in range(130):
            instrument = "ACCOUNT-B-{:03d}".format(index)
            key = ExecutionIntentKey("SUBMIT", instrument, "BUY", "OPEN", 0)
            decision = journal.record_decision(
                ExecutionDecisionKey(
                    account_scope="account-b",
                    strategy_scope="strategy-b",
                    logical_run_id="run-b",
                    cohort_id="cohort-b-{:03d}".format(index),
                    close_time="2026-10-20T10:00:00Z",
                    decision_kind="bar",
                ),
                {"signal": "unresolved"},
                intent_keys=(key,),
            )
            journal.prepare_intent(
                decision.decision_id,
                key,
                {"instrument": instrument, "exchange": "SHFE"},
            )

        for strategy, run, cohort in (
            ("strategy-a", "old-run", "account-a-old-run"),
            ("strategy-a", "new-run", "account-a-new-run"),
            ("strategy-other", "other-run", "account-a-other-strategy"),
        ):
            instrument = "A-" + cohort
            key = ExecutionIntentKey("SUBMIT", instrument, "BUY", "OPEN", 0)
            decision = journal.record_decision(
                ExecutionDecisionKey(
                    account_scope="account-a",
                    strategy_scope=strategy,
                    logical_run_id=run,
                    cohort_id=cohort,
                    close_time="2026-10-20T10:00:00Z",
                    decision_kind="bar",
                ),
                {"signal": "unresolved"},
                intent_keys=(key,),
            )
            journal.prepare_intent(
                decision.decision_id,
                key,
                {"instrument": instrument, "exchange": "SHFE"},
            )

        page = journal.execution_intent_snapshot(account_scope="account-a", limit=3)
        assert page.account_scope == "account-a"
        assert page.truncated is False
        assert len(page.items) == 3
        assert {item.decision_key.account_scope for item in page.items} == {"account-a"}
        assert {
            (item.decision_key.strategy_scope, item.decision_key.logical_run_id)
            for item in page.items
        } == {
            ("strategy-a", "old-run"),
            ("strategy-a", "new-run"),
            ("strategy-other", "other-run"),
        }
        assert {item.decision_key.account_scope for item in page.items} == {"account-a"}
        smaller_page = journal.execution_intent_snapshot(account_scope="account-a", limit=2)
        assert smaller_page.truncated is True
        assert all(item.decision_key.account_scope == "account-a" for item in smaller_page.items)
    finally:
        journal.close()


@pytest.mark.parametrize(
    "corrupt_field",
    (
        "decision_key",
        "intent_key",
        "malformed_decision_json",
        "malformed_intent_json",
        "duplicate_decision_scope",
        "orphan_decision",
    ),
)
def test_execution_intent_snapshot_fails_closed_on_unclassifiable_effective_key(
    tmp_path, corrupt_field
):
    journal = ExecutionDecisionJournal(tmp_path / "intent-snapshot-corrupt.sqlite3")
    try:
        _decision, intent = _prepare(journal)
        if corrupt_field == "decision_key":
            journal._connection.execute(
                "UPDATE execution_decisions SET business_key_json=? WHERE decision_id=?",
                ('{"strategy_scope":"strategy-a"}', intent.decision_id),
            )
        elif corrupt_field == "intent_key":
            journal._connection.execute(
                "UPDATE execution_decision_intents SET intent_key_json=? WHERE intent_id=?",
                ('{"action":"SUBMIT","instrument":"SIM-IF-1"}', intent.intent_id),
            )
        elif corrupt_field == "malformed_decision_json":
            journal._connection.execute(
                "UPDATE execution_decisions SET business_key_json=? WHERE decision_id=?",
                ("{", intent.decision_id),
            )
        elif corrupt_field == "malformed_intent_json":
            journal._connection.execute(
                "UPDATE execution_decision_intents SET intent_key_json=? WHERE intent_id=?",
                ("{", intent.intent_id),
            )
        elif corrupt_field == "duplicate_decision_scope":
            current = journal._connection.execute(
                "SELECT business_key_json FROM execution_decisions WHERE decision_id=?",
                (intent.decision_id,),
            ).fetchone()[0]
            duplicate = current.replace(
                '"account_scope":"account-a"',
                '"account_scope":"other-account","account_scope":"account-a"',
                1,
            )
            assert duplicate != current
            journal._connection.execute(
                "UPDATE execution_decisions SET business_key_json=? WHERE decision_id=?",
                (duplicate, intent.decision_id),
            )
        else:
            # Model a damaged on-disk database with a missing decision parent.
            # SQLite's normal foreign-key guard is disabled only for this
            # synthetic corruption fixture; the Journal reader remains the
            # production API under test.
            journal._connection.execute("PRAGMA foreign_keys=OFF")
            journal._connection.execute(
                "UPDATE execution_decision_intents SET decision_id=? WHERE intent_id=?",
                ("missing-decision", intent.intent_id),
            )
        with pytest.raises(
            ExecutionDecisionJournalError, match="INTENT_SCOPE_UNCLASSIFIABLE"
        ):
            journal.execution_intent_snapshot(account_scope="different-account", limit=8)
    finally:
        journal.close()


def test_callbacks_are_deduplicated_bounded_and_acknowledged_after_delivery(tmp_path):
    path = tmp_path / "callbacks.sqlite3"
    journal = ExecutionDecisionJournal(path, max_pending_callbacks=1)
    _, intent = _prepare(journal)
    evidence = {"event_id": "fill-1", "state": "PARTIALLY_FILLED", "filled_quantity": "1.00"}
    receipt = journal.record_callback(intent.intent_id, "provider-event-1", evidence)
    replay = journal.record_callback(
        intent.intent_id,
        "provider-event-1",
        {
            "filled_quantity": Decimal("1.000"),
            "state": "PARTIALLY_FILLED",
            "event_id": "fill-1",
        },
    )
    assert replay.receipt_id == receipt.receipt_id
    assert len(journal.pending_callbacks(limit=1)) == 1
    with pytest.raises(ExecutionDecisionJournalError, match="CALLBACK_CONFLICT"):
        journal.record_callback(
            intent.intent_id,
            "provider-event-1",
            {"event_id": "fill-1", "state": "FILLED", "filled_quantity": "2"},
        )
    with pytest.raises(ExecutionDecisionJournalError, match="PENDING_CALLBACK_LIMIT"):
        journal.record_callback(intent.intent_id, "provider-event-2", {"state": "FILLED"})
    journal.close()

    # A crash after caller delivery but before acknowledgment replays the same
    # durable identity; the caller can deduplicate before acknowledging it.
    reopened = ExecutionDecisionJournal(path, max_pending_callbacks=1)
    pending = reopened.pending_callbacks(limit=1)
    assert len(pending) == 1
    assert pending[0].receipt_id == receipt.receipt_id
    redelivery = reopened.record_callback(intent.intent_id, "provider-event-1", evidence)
    assert redelivery.receipt_id == receipt.receipt_id
    assert redelivery.acknowledged is False
    reopened.acknowledge_callback(receipt.receipt_id)
    assert reopened.pending_callbacks(limit=1) == ()
    acknowledged_replay = reopened.record_callback(intent.intent_id, "provider-event-1", evidence)
    assert acknowledged_replay.acknowledged is True
    assert reopened.pending_callbacks(limit=1) == ()
    with pytest.raises(TypeError):
        acknowledged_replay.evidence_payload["state"] = "MUTATED"
    assert not hasattr(reopened, "fills")
    assert not hasattr(reopened, "balances")
    reopened.close()


def test_projected_callback_roundtrip_replay_and_exact_key_blocking(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "projected-callback.sqlite3")
    intent_key = _intent_key("SIM-IF-1", effect="OPEN")
    decision = journal.record_decision(
        _decision_key("projected-callback"),
        _decision_payload(),
        intent_keys=(intent_key,),
    )
    intent = journal.prepare_intent(
        decision.decision_id,
        intent_key,
        {
            "quantity": "1",
            "price": "100",
            "exchange": "CFFEX",
            "factor_stop_price": "90",
            "risk_policy_id": "risk-v1",
            "risk_policy": {"max_loss_per_position": "10"},
        },
    )
    callback_id = "trade-event-1"
    evidence = {
        "event_type": "execution_fill",
        "execution_id": "trade-1",
        "quantity": "1",
        "price": "100",
        "fee": None,
        "filled_at_ns": 1_798_192_800_000_000_000,
        "exchange": "CFFEX",
    }
    claim = journal.claim_dispatch(intent.intent_id)
    assert claim is not None
    assert claim.intent.state == "DISPATCHING"

    def project(cursor, receipt_id):
        return apply_factor_execution_fill(cursor, receipt_id=receipt_id)

    before_receipt = journal.callback_projection_status(intent.intent_id, callback_id, evidence)
    assert before_receipt.status == "UNRECONCILED"
    first, first_projection = journal.record_callback_projected(
        intent.intent_id, callback_id, evidence, project=project
    )
    assert first.is_new is True
    assert first_projection.status == "APPLIED"
    assert journal.callback_projection_status(intent.intent_id, callback_id, evidence).status == (
        "APPLIED"
    )

    replay, replay_projection = journal.record_callback_projected(
        intent.intent_id, callback_id, evidence, project=project
    )
    assert replay.receipt_id == first.receipt_id
    assert replay.is_new is False
    assert replay_projection.status == "DUPLICATE"
    assert journal.callback_projection_status(intent.intent_id, callback_id, evidence).status == (
        "APPLIED"
    )

    wrong_callback = journal.callback_projection_status(
        intent.intent_id, "different-trade-event", evidence
    )
    assert wrong_callback.status == "UNRECONCILED"
    mismatched_evidence = dict(evidence, quantity="2")
    wrong_payload = journal.callback_projection_status(
        intent.intent_id, callback_id, mismatched_evidence
    )
    assert wrong_payload.status == "BLOCKED"
    assert wrong_payload.blocker_code == "CALLBACK_EVIDENCE_CONFLICT"
    with pytest.raises(ExecutionDecisionJournalError, match="CALLBACK_CONFLICT"):
        journal.record_callback_projected(
            intent.intent_id, callback_id, mismatched_evidence, project=project
        )
    persisted = journal.callback_receipt(intent.intent_id, callback_id)
    assert persisted is not None
    assert persisted.receipt_id == first.receipt_id
    assert persisted.evidence_payload == first.evidence_payload
    with pytest.raises(ExecutionDecisionJournalError, match="INTENT_NOT_PREPARED"):
        journal.record_callback_projected("missing-intent", callback_id, evidence, project=project)
    journal.close()


def test_pending_intent_limit_and_sqlite_write_failure_fail_closed(tmp_path):
    path = tmp_path / "failure.sqlite3"
    journal = ExecutionDecisionJournal(path, max_pending_intents=1)
    _, first = _prepare(journal)
    with pytest.raises(ExecutionDecisionJournalError, match="PENDING_INTENT_LIMIT"):
        journal.record_decision(
            _decision_key("run-b"),
            _decision_payload(),
            intent_keys=(_intent_key("SIM-IF-2"),),
        )

    with sqlite3.connect(path) as connection:
        connection.execute(
            """CREATE TRIGGER reject_dispatch_claim
               BEFORE UPDATE OF state ON execution_decision_intents
               BEGIN SELECT RAISE(ABORT, 'synthetic storage failure'); END"""
        )
    with pytest.raises(ExecutionDecisionJournalError, match="JOURNAL_WRITE_FAILED"):
        journal.claim_dispatch(first.intent_id)
    with pytest.raises(ExecutionDecisionJournalError, match="JOURNAL_FAILED_CLOSED"):
        journal.claim_dispatch(first.intent_id)
    journal.close()

    reopened = ExecutionDecisionJournal(path, max_pending_intents=1)
    persisted = reopened.intent(first.intent_id)
    assert persisted is not None
    assert persisted.state == "PREPARED"
    assert persisted.dispatch_state is None
    reopened.close()


def test_partial_write_failures_roll_back_and_latch_the_instance(tmp_path):
    decision_path = tmp_path / "decision-rollback.sqlite3"
    decision_journal = ExecutionDecisionJournal(decision_path)
    with sqlite3.connect(decision_path) as connection:
        connection.execute(
            """CREATE TRIGGER reject_decision_slot
               BEFORE INSERT ON execution_decision_slots
               BEGIN SELECT RAISE(ABORT, 'synthetic slot write failure'); END"""
        )
    with pytest.raises(ExecutionDecisionJournalError, match="JOURNAL_WRITE_FAILED"):
        decision_journal.record_decision(
            _decision_key("rollback-decision"),
            _decision_payload(),
            intent_keys=(_intent_key(),),
        )
    with pytest.raises(ExecutionDecisionJournalError, match="JOURNAL_FAILED_CLOSED"):
        decision_journal.record_decision(_decision_key("after-failure"), _decision_payload())
    decision_journal.close()
    with sqlite3.connect(decision_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM execution_decisions").fetchone()[0] == 0
        assert (
            connection.execute("SELECT COUNT(*) FROM execution_decision_slots").fetchone()[0] == 0
        )

    intent_path = tmp_path / "intent-rollback.sqlite3"
    intent_journal = ExecutionDecisionJournal(intent_path)
    decision = intent_journal.record_decision(
        _decision_key("rollback-intent"),
        _decision_payload(),
        intent_keys=(_intent_key(),),
    )
    with sqlite3.connect(intent_path) as connection:
        connection.execute(
            """CREATE TRIGGER reject_intent_insert
               BEFORE INSERT ON execution_decision_intents
               BEGIN SELECT RAISE(ABORT, 'synthetic intent write failure'); END"""
        )
    with pytest.raises(ExecutionDecisionJournalError, match="JOURNAL_WRITE_FAILED"):
        intent_journal.prepare_intent(decision.decision_id, _intent_key(), _order_payload())
    with pytest.raises(ExecutionDecisionJournalError, match="JOURNAL_FAILED_CLOSED"):
        intent_journal.prepare_intent(decision.decision_id, _intent_key(), _order_payload())
    intent_journal.close()

    reopened = ExecutionDecisionJournal(intent_path)
    assert reopened.decision(decision.decision_id) is not None
    with sqlite3.connect(intent_path) as connection:
        intent_id = connection.execute(
            "SELECT intent_id FROM execution_decision_slots WHERE decision_id = ?",
            (decision.decision_id,),
        ).fetchone()[0]
    assert reopened.intent(intent_id) is None
    assert reopened.active_instrument_owner("account-a", "SIM-IF-1") is None
    with sqlite3.connect(intent_path) as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM execution_instrument_owners WHERE owner_intent_id IS NOT NULL"
            ).fetchone()[0]
            == 0
        )
    reopened.close()


def test_prepared_intent_can_be_abandoned_without_dispatch(tmp_path):
    path = tmp_path / "abandon.sqlite3"
    journal = ExecutionDecisionJournal(path, max_pending_intents=1)
    _, stale = _prepare(journal)
    owner = journal.active_instrument_owner("account-a", "SIM-IF-1")
    assert owner is not None and owner.intent_id == stale.intent_id

    abandonment = journal.abandon_prepared_intent(
        stale.intent_id, reason_code="quote_expired_before_dispatch"
    )
    assert abandonment == journal.abandon_prepared_intent(
        stale.intent_id, reason_code="quote_expired_before_dispatch"
    )
    assert journal.active_instrument_owner("account-a", "SIM-IF-1") is None
    assert journal.recoverable_intents(limit=1) == ()
    assert journal.execution_intent_snapshot(account_scope="account-a", limit=1).items == ()
    assert journal.intent(stale.intent_id) == stale
    assert abandonment.intent_id == stale.intent_id
    with pytest.raises(ExecutionDecisionJournalError, match="INTENT_ABANDONED"):
        journal.claim_dispatch(stale.intent_id)
    with pytest.raises(ExecutionDecisionJournalError, match="INTENT_ABANDONMENT_CONFLICT"):
        journal.abandon_prepared_intent(stale.intent_id, reason_code="different_reason")

    next_key = _intent_key("SIM-IF-1", side="BUY", effect="OPEN")
    decision = journal.record_decision(
        _decision_key("run-after-abandon"), _decision_payload(), intent_keys=(next_key,)
    )
    next_intent = journal.prepare_intent(decision.decision_id, next_key, _order_payload())
    assert next_intent.state == "PREPARED"
    assert journal.claim_dispatch(next_intent.intent_id) is not None
    with pytest.raises(ExecutionDecisionJournalError, match="INTENT_NOT_ABANDONABLE"):
        journal.abandon_prepared_intent(next_intent.intent_id, reason_code="claimed_cannot_abandon")
    journal.close()


def test_two_journal_connections_cannot_claim_the_same_intent_twice(tmp_path):
    path = tmp_path / "concurrent.sqlite3"
    first_journal = ExecutionDecisionJournal(path)
    _, intent = _prepare(first_journal)
    second_journal = ExecutionDecisionJournal(path)
    first_claim = first_journal.claim_dispatch(intent.intent_id)
    second_claim = second_journal.claim_dispatch(intent.intent_id)
    assert first_claim is not None
    assert second_claim is None
    first_journal.close()
    second_journal.close()


def test_two_subprocesses_racing_for_one_dispatch_have_one_winner(tmp_path):
    path = tmp_path / "subprocess-race.sqlite3"
    journal = ExecutionDecisionJournal(path)
    _, intent = _prepare(journal)
    journal.close()

    gate = tmp_path / "race-start"
    ready_paths = (tmp_path / "worker-1-ready", tmp_path / "worker-2-ready")
    worker = r"""
import json, pathlib, sys, time
from backtrader.stores.execution_decision_journal import ExecutionDecisionJournal
database, intent_id, ready_path, start_path = sys.argv[1:]
pathlib.Path(ready_path).write_text("ready", encoding="ascii")
deadline = time.monotonic() + 20
while not pathlib.Path(start_path).exists():
    if time.monotonic() >= deadline:
        raise SystemExit("start barrier timed out")
    time.sleep(0.005)
journal = ExecutionDecisionJournal(database)
claim = journal.claim_dispatch(intent_id)
print(json.dumps({"claimed": claim is not None}))
journal.close()
"""
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", worker, str(path), intent.intent_id, str(ready), str(gate)],
            cwd=os.getcwd(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for ready in ready_paths
    ]
    try:
        deadline = time.monotonic() + 20
        while not all(ready.exists() for ready in ready_paths):
            if time.monotonic() >= deadline:
                raise AssertionError("subprocess workers did not reach the start barrier")
            if any(process.poll() is not None for process in processes):
                raise AssertionError("a subprocess worker exited before the start barrier")
            time.sleep(0.005)
        gate.touch()
        results = [process.communicate(timeout=30) for process in processes]
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)

    assert all(process.returncode == 0 for process in processes), results
    claims = [json.loads(stdout)["claimed"] for stdout, _stderr in results]
    assert sum(claims) == 1
    assert all(stderr == "" for _stdout, stderr in results)


def test_eligible_grid_decision_and_cursor_commit_atomically_including_noop(tmp_path):
    path = tmp_path / "grid.sqlite3"
    journal = ExecutionDecisionJournal(path)
    key = _decision_key(close_time="2026-10-20T10:00:00Z")
    first = journal.record_grid_decision(
        key,
        {"signal": "flat", "quantity": "0"},
        epoch_id="epoch-a",
        batch_id="batch-a",
        eligible=True,
        complete=True,
        live_ready=True,
        inputs_complete=True,
    )
    assert first.eligible is True
    assert first.is_new_grid is True
    assert first.decision is not None and first.decision.is_noop is True
    assert first.cursor is not None
    assert first.cursor.ordinal == 1
    assert first.cursor.decision_id == first.decision.decision_id

    replay = journal.record_grid_decision(
        _decision_key(close_time="2026-10-20T18:00:00+08:00"),
        {"quantity": Decimal("0.0"), "signal": "flat"},
        epoch_id="epoch-a",
        batch_id="batch-a",
        eligible=True,
        complete=True,
        live_ready=True,
        inputs_complete=True,
    )
    assert replay.decision == first.decision
    assert replay.cursor == first.cursor
    assert replay.is_new_grid is False

    ineligible = journal.record_grid_decision(
        _decision_key(run_id="run-b", close_time="2026-10-20T10:01:00Z"),
        {"signal": "must-not-be-written"},
        epoch_id="epoch-a",
        batch_id="batch-gap",
        eligible=True,
        complete=True,
        live_ready=True,
        inputs_complete=False,
    )
    assert ineligible.eligible is False
    assert ineligible.decision is None
    assert ineligible.cursor == first.cursor
    assert (
        journal._connection.execute("SELECT COUNT(*) FROM execution_decisions").fetchone()[0] == 1
    )

    # A later eligible grid advances once even when logical-run and epoch
    # identities change; neither identity resets consumed grid progress.
    next_grid = journal.record_grid_decision(
        _decision_key(run_id="run-b", close_time="2026-10-20T10:01:00Z"),
        {"signal": "flat"},
        epoch_id="epoch-b",
        batch_id="batch-b",
        eligible=True,
        complete=True,
        live_ready=True,
        inputs_complete=True,
    )
    assert next_grid.is_new_grid is True
    assert next_grid.cursor is not None and next_grid.cursor.ordinal == 2
    assert journal.grid_cursor("account-a", "strategy-a", "cohort-1") == next_grid.cursor

    with pytest.raises(ExecutionDecisionJournalError, match="GRID_CURSOR_STALE_OR_CONFLICT"):
        journal.record_grid_decision(
            _decision_key(run_id="run-c", close_time="2026-10-20T10:00:00Z"),
            {"signal": "cross-up"},
            epoch_id="epoch-c",
            batch_id="mode-changed-same-old-grid",
            eligible=True,
            complete=True,
            live_ready=True,
            inputs_complete=True,
        )
    assert journal.grid_cursor("account-a", "strategy-a", "cohort-1") == next_grid.cursor
    journal.close()


def test_grid_highwater_blocks_same_close_across_028_epochs_but_allows_later_and_other_scope(
    tmp_path,
):
    journal = ExecutionDecisionJournal(tmp_path / "alpha003-grid-highwater.sqlite3")
    close_time = "2026-10-24T10:00:00Z"
    epoch_a = "epoch-live-1"
    epoch_b = "epoch-live-2"
    cohort_a = f"alpha003:20261024:{epoch_a}"
    cohort_b = f"alpha003:20261024:{epoch_b}"

    first_key = _grid_key(cohort_id=cohort_a, close_time=close_time)
    first_economics = {"signal": "flat", "mode": "native", "config": "cfg-a"}
    first = _record_grid_noop(
        journal,
        first_key,
        epoch_id=epoch_a,
        batch_id="batch-1",
        economics=first_economics,
    )
    assert first.is_new_grid is True

    # Epoch/config/run changes do not make an already-consumed close new.
    second_epoch_same_close = _grid_key(
        run_id="run-b",
        cohort_id=cohort_b,
        close_time="2026-10-24T18:00:00+08:00",
    )
    with pytest.raises(ExecutionDecisionJournalError, match="GRID_CURSOR_STALE_OR_CONFLICT"):
        _record_grid_noop(
            journal,
            second_epoch_same_close,
            epoch_id=epoch_b,
            batch_id="batch-replay",
            economics={"signal": "flat", "mode": "build", "config": "cfg-b"},
        )
    assert journal.grid_cursor("account-a", "strategy-a", cohort_b) is None
    assert (
        journal._connection.execute("SELECT COUNT(*) FROM execution_decisions").fetchone()[0] == 1
    )

    # The same exact historical decision remains a no-dispatch replay after
    # its own cohort cursor has advanced.
    same_cohort_later = _grid_key(
        run_id="run-b",
        cohort_id=cohort_a,
        close_time="2026-10-24T10:00:30Z",
    )
    advanced_a = _record_grid_noop(
        journal,
        same_cohort_later,
        epoch_id=epoch_a,
        batch_id="batch-2",
    )
    assert advanced_a.is_new_grid is True
    replay = _record_grid_noop(
        journal,
        first_key,
        epoch_id=epoch_a,
        batch_id="batch-1",
        economics=first_economics,
    )
    assert replay.decision == first.decision
    assert replay.is_new_grid is False
    assert replay.cursor == advanced_a.cursor

    # Compare instants, not their normalized strings: a positive microsecond
    # timestamp sorts textually before the second-level timestamp ending in Z.
    fractional_later = _grid_key(
        run_id="run-c",
        cohort_id=cohort_b,
        close_time="2026-10-24T10:00:30.000001Z",
    )
    assert (
        _record_grid_noop(
            journal, fractional_later, epoch_id=epoch_b, batch_id="batch-fractional"
        ).is_new_grid
        is True
    )

    # A later eligible grid under a new epoch is allowed, while a genuinely
    # independent strategy scope has its own highwater at the earlier close.
    later_b = _grid_key(
        run_id="run-c",
        cohort_id=cohort_b,
        close_time="2026-10-24T10:01:00Z",
    )
    assert (
        _record_grid_noop(journal, later_b, epoch_id=epoch_b, batch_id="batch-3").is_new_grid
        is True
    )
    other_strategy = _grid_key(
        strategy_scope="strategy-b",
        cohort_id=cohort_b,
        close_time=close_time,
    )
    assert (
        _record_grid_noop(
            journal, other_strategy, epoch_id=epoch_b, batch_id="other-strategy"
        ).is_new_grid
        is True
    )
    journal.close()


def test_grid_highwater_migration_backfills_maximum_from_v9_cohort_cursors(tmp_path):
    path = tmp_path / "grid-highwater-v9-migration.sqlite3"
    journal = ExecutionDecisionJournal(path)
    epoch_a = "epoch-live-1"
    epoch_b = "epoch-live-2"
    first = _grid_key(
        cohort_id=f"alpha003:20261024:{epoch_a}",
        close_time="2026-10-24T10:00:00Z",
    )
    later = _grid_key(
        run_id="run-b",
        cohort_id=f"alpha003:20261024:{epoch_b}",
        close_time="2026-10-24T10:01:00Z",
    )
    _record_grid_noop(journal, first, epoch_id=epoch_a, batch_id="batch-1")
    _record_grid_noop(journal, later, epoch_id=epoch_b, batch_id="batch-2")
    journal.close()

    # Recreate the v9 layout: per-cohort cursors exist, the new materialized
    # stream highwater does not.
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE execution_grid_highwaters")
        _drop_v12_durable_capacity_tables(connection)
        connection.execute("PRAGMA user_version = 9")

    migrated = ExecutionDecisionJournal(path)
    assert migrated._connection.execute("PRAGMA user_version").fetchone()[0] == ExecutionDecisionJournal._SCHEMA_VERSION
    highwater = migrated._connection.execute(
        """SELECT close_time,cohort_id,decision_id FROM execution_grid_highwaters
           WHERE account_scope='account-a' AND strategy_scope='strategy-a'"""
    ).fetchone()
    assert highwater["close_time"] == "2026-10-24T10:01:00Z"
    assert highwater["cohort_id"] == later.cohort_id

    stale = _grid_key(
        run_id="run-c",
        cohort_id="alpha003:20261024:epoch-live-3",
        close_time="2026-10-24T10:00:30Z",
    )
    with pytest.raises(ExecutionDecisionJournalError, match="GRID_CURSOR_STALE_OR_CONFLICT"):
        _record_grid_noop(migrated, stale, epoch_id="epoch-live-3", batch_id="batch-3")
    next_grid = _grid_key(
        run_id="run-c",
        cohort_id="alpha003:20261024:epoch-live-3",
        close_time="2026-10-24T10:02:00Z",
    )
    assert (
        _record_grid_noop(
            migrated, next_grid, epoch_id="epoch-live-3", batch_id="batch-4"
        ).is_new_grid
        is True
    )
    migrated.close()


def test_grid_highwater_migration_rejects_noncanonical_legacy_cursor_time(tmp_path):
    path = tmp_path / "grid-highwater-invalid-v9-migration.sqlite3"
    journal = ExecutionDecisionJournal(path)
    epoch_a = "epoch-live-1"
    epoch_b = "epoch-live-2"
    _record_grid_noop(
        journal,
        _grid_key(
            cohort_id=f"alpha003:20261024:{epoch_a}",
            close_time="2026-10-24T10:00:00Z",
        ),
        epoch_id=epoch_a,
        batch_id="batch-1",
    )
    second = _grid_key(
        run_id="run-b",
        cohort_id=f"alpha003:20261024:{epoch_b}",
        close_time="2026-10-24T10:01:00Z",
    )
    _record_grid_noop(journal, second, epoch_id=epoch_b, batch_id="batch-2")
    journal.close()

    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE execution_grid_highwaters")
        connection.execute(
            """UPDATE execution_grid_cursors SET close_time='2026-10-24T10:01:00+00:00'
               WHERE cohort_id=?""",
            (second.cohort_id,),
        )
        _drop_v12_durable_capacity_tables(connection)
        connection.execute("PRAGMA user_version = 9")

    with pytest.raises(ExecutionDecisionJournalError, match="INVALID_STORED_GRID_CLOSE_TIME"):
        ExecutionDecisionJournal(path)

    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 9
        assert connection.execute("SELECT COUNT(*) FROM execution_grid_cursors").fetchone()[0] == 2
        assert (
            connection.execute("SELECT COUNT(*) FROM execution_grid_highwaters").fetchone()[0] == 0
        )


def test_grid_highwater_and_decision_roll_back_together_on_sqlite_failure(tmp_path):
    path = tmp_path / "grid-highwater-rollback.sqlite3"
    journal = ExecutionDecisionJournal(path)
    with sqlite3.connect(path) as connection:
        connection.execute(
            """CREATE TRIGGER reject_grid_highwater
               BEFORE INSERT ON execution_grid_highwaters
               BEGIN SELECT RAISE(ABORT, 'synthetic highwater failure'); END"""
        )

    key = _grid_key(cohort_id="alpha003:20261024:epoch-live-1")
    with pytest.raises(ExecutionDecisionJournalError, match="JOURNAL_WRITE_FAILED"):
        _record_grid_noop(journal, key, epoch_id="epoch-live-1", batch_id="batch-1")
    assert journal._failed_closed is True
    journal.close()

    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM execution_decisions").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM execution_grid_cursors").fetchone()[0] == 0
        assert (
            connection.execute("SELECT COUNT(*) FROM execution_grid_highwaters").fetchone()[0] == 0
        )
        assert (
            connection.execute("SELECT COUNT(*) FROM factor_position_grid_history").fetchone()[0]
            == 0
        )
        assert (
            connection.execute(
                "SELECT SUM(record_count) FROM execution_decision_capacity_usage"
            ).fetchone()[0]
            == 0
        )
        connection.execute("DROP TRIGGER reject_grid_highwater")

    reopened = ExecutionDecisionJournal(path)
    assert (
        _record_grid_noop(reopened, key, epoch_id="epoch-live-1", batch_id="batch-1").is_new_grid
        is True
    )
    reopened.close()


def test_grid_decision_cursor_is_recovered_and_replay_does_not_redispatch(tmp_path):
    path = tmp_path / "grid-recovery.sqlite3"
    journal = ExecutionDecisionJournal(path)
    key = _decision_key(close_time="2026-10-20T10:00:00Z")
    result = journal.record_grid_decision(
        key,
        {"signal": "flat"},
        epoch_id="epoch-a",
        batch_id="batch-a",
        eligible=True,
        complete=True,
        live_ready=True,
        inputs_complete=True,
    )
    journal.close()

    child = r"""
import json, sys
from backtrader.stores.execution_decision_journal import ExecutionDecisionJournal, ExecutionDecisionKey
journal = ExecutionDecisionJournal(sys.argv[1])
key = ExecutionDecisionKey("account-a", "strategy-a", "run-a", "cohort-1", "2026-10-20T10:00:00Z", "bar")
saved = journal.grid_cursor("account-a", "strategy-a", "cohort-1")
replay = journal.record_grid_decision(key, {"signal":"flat"}, epoch_id="epoch-a", batch_id="batch-a", eligible=True, complete=True, live_ready=True, inputs_complete=True)
assert replay.is_new_grid is False
assert replay.decision is not None and replay.decision.is_noop
assert replay.cursor == saved
print(json.dumps({"ordinal":saved.ordinal, "decision_id":saved.decision_id, "new":replay.is_new_grid}, sort_keys=True))
journal.close()
"""
    completed = subprocess.run(
        [sys.executable, "-c", child, str(path)],
        cwd=os.getcwd(),
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    assert json.loads(completed.stdout) == {
        "ordinal": 1,
        "decision_id": result.decision.decision_id,
        "new": False,
    }


def test_grid_decision_and_cursor_roll_back_together_on_sqlite_failure(tmp_path):
    path = tmp_path / "grid-rollback.sqlite3"
    journal = ExecutionDecisionJournal(path)
    with sqlite3.connect(path) as connection:
        connection.execute(
            """CREATE TRIGGER reject_grid_cursor
               BEFORE INSERT ON execution_grid_cursors
               BEGIN SELECT RAISE(ABORT, 'synthetic cursor failure'); END"""
        )
    key = _decision_key(run_id="rollback-grid")
    with pytest.raises(ExecutionDecisionJournalError, match="JOURNAL_WRITE_FAILED"):
        journal.record_grid_decision(
            key,
            {"signal": "cross-up"},
            intent_keys=(_intent_key(),),
            epoch_id="epoch-a",
            batch_id="batch-a",
            eligible=True,
            complete=True,
            live_ready=True,
            inputs_complete=True,
        )
    with pytest.raises(ExecutionDecisionJournalError, match="JOURNAL_FAILED_CLOSED"):
        journal.record_grid_decision(
            key,
            {"signal": "cross-up"},
            intent_keys=(_intent_key(),),
            epoch_id="epoch-a",
            batch_id="batch-a",
            eligible=True,
            complete=True,
            live_ready=True,
            inputs_complete=True,
        )
    journal.close()

    reopened = ExecutionDecisionJournal(path)
    assert (
        reopened._connection.execute("SELECT COUNT(*) FROM execution_decisions").fetchone()[0] == 0
    )
    assert reopened.grid_cursor("account-a", "strategy-a", "cohort-1") is None
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM execution_decisions").fetchone()[0] == 0
        assert (
            connection.execute("SELECT COUNT(*) FROM execution_decision_slots").fetchone()[0] == 0
        )
        assert connection.execute("SELECT COUNT(*) FROM execution_grid_cursors").fetchone()[0] == 0
    reopened.close()


def test_grid_order_budget_counts_submits_and_cancels_once_per_logical_run(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "grid-budget.sqlite3")
    first_key = _decision_key(run_id="budget-run", close_time="2026-10-20T10:00:00Z")
    first = journal.record_grid_decision(
        first_key,
        {"signal": "cancel-then-close"},
        intent_keys=(_intent_key("SIM-IF-1", action="CANCEL", leg=0),),
        epoch_id="epoch-a",
        batch_id="batch-a",
        eligible=True,
        complete=True,
        live_ready=True,
        inputs_complete=True,
        max_order_intents_per_run=2,
        expected_run_order_intents_used=0,
        remaining_exit_intent_reserve=1,
    )
    assert first.is_new_grid is True
    assert journal.run_order_count("account-a", "strategy-a", "budget-run") == 1

    replay = journal.record_grid_decision(
        first_key,
        {"signal": "cancel-then-close"},
        intent_keys=(_intent_key("SIM-IF-1", action="CANCEL", leg=0),),
        epoch_id="epoch-a",
        batch_id="batch-a",
        eligible=True,
        complete=True,
        live_ready=True,
        inputs_complete=True,
        max_order_intents_per_run=2,
    )
    assert replay.is_new_grid is False
    assert journal.run_order_count("account-a", "strategy-a", "budget-run") == 1
    with pytest.raises(ExecutionDecisionJournalError, match="RUN_ORDER_BUDGET_CONFLICT"):
        journal.record_grid_decision(
            first_key,
            {"signal": "cancel-then-close"},
            intent_keys=(_intent_key("SIM-IF-1", action="CANCEL", leg=0),),
            epoch_id="epoch-a",
            batch_id="batch-a",
            eligible=True,
            complete=True,
            live_ready=True,
            inputs_complete=True,
            max_order_intents_per_run=3,
        )

    with pytest.raises(ExecutionDecisionJournalError, match="DECISION_CONFLICT"):
        journal.record_grid_decision(
            first_key,
            {"signal": "cancel-then-close"},
            intent_keys=(_intent_key("SIM-IF-1", action="CANCEL", leg=0),),
            epoch_id="epoch-a",
            batch_id="batch-a",
            eligible=True,
            complete=True,
            live_ready=True,
            inputs_complete=True,
            max_order_intents_per_run=2,
            expected_run_order_intents_used=1,
            remaining_exit_intent_reserve=0,
        )
    assert journal.run_order_count("account-a", "strategy-a", "budget-run") == 1
    assert journal.grid_cursor("account-a", "strategy-a", "cohort-1") == first.cursor

    with pytest.raises(ExecutionDecisionJournalError, match="RUN_ORDER_BUDGET_STALE"):
        journal.record_grid_decision(
            _decision_key(run_id="budget-run", close_time="2026-10-20T10:01:00Z"),
            {"signal": "submit"},
            intent_keys=(_intent_key("SIM-IF-2", leg=0),),
            epoch_id="epoch-a",
            batch_id="batch-b",
            eligible=True,
            complete=True,
            live_ready=True,
            inputs_complete=True,
            max_order_intents_per_run=2,
            expected_run_order_intents_used=0,
            remaining_exit_intent_reserve=1,
        )
    assert journal.run_order_count("account-a", "strategy-a", "budget-run") == 1
    assert journal.grid_cursor("account-a", "strategy-a", "cohort-1") == first.cursor
    assert (
        journal._connection.execute("SELECT COUNT(*) FROM execution_decisions").fetchone()[0] == 1
    )

    with pytest.raises(ExecutionDecisionJournalError, match="RUN_ORDER_BUDGET_EXCEEDED"):
        journal.record_grid_decision(
            _decision_key(run_id="budget-run", close_time="2026-10-20T10:01:00Z"),
            {"signal": "submit"},
            intent_keys=(_intent_key("SIM-IF-2", leg=0),),
            epoch_id="epoch-a",
            batch_id="batch-b",
            eligible=True,
            complete=True,
            live_ready=True,
            inputs_complete=True,
            max_order_intents_per_run=2,
            expected_run_order_intents_used=1,
            remaining_exit_intent_reserve=1,
        )
    assert journal.run_order_count("account-a", "strategy-a", "budget-run") == 1
    assert journal.grid_cursor("account-a", "strategy-a", "cohort-1") == first.cursor
    assert (
        journal._connection.execute("SELECT COUNT(*) FROM execution_decisions").fetchone()[0] == 1
    )

    second = journal.record_grid_decision(
        _decision_key(run_id="budget-run", close_time="2026-10-20T10:01:00Z"),
        {"signal": "submit"},
        intent_keys=(_intent_key("SIM-IF-2", leg=0),),
        epoch_id="epoch-a",
        batch_id="batch-b",
        eligible=True,
        complete=True,
        live_ready=True,
        inputs_complete=True,
        max_order_intents_per_run=2,
        expected_run_order_intents_used=1,
        remaining_exit_intent_reserve=0,
    )
    assert second.is_new_grid is True
    assert second.cursor.ordinal == 2
    assert journal.run_order_count("account-a", "strategy-a", "budget-run") == 2
    journal.close()


def test_budgeted_decisions_require_reserved_evidence_and_reject_payload_collision(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "budget-evidence.sqlite3")
    key = _decision_key(run_id="budget-evidence")
    common = {
        "epoch_id": "epoch-a",
        "batch_id": "batch-a",
        "eligible": True,
        "complete": True,
        "live_ready": True,
        "inputs_complete": True,
        "max_order_intents_per_run": 0,
    }
    with pytest.raises(
        ExecutionDecisionJournalError, match="RUN_ORDER_BUDGET_RESERVATION_REQUIRED"
    ):
        journal.record_grid_decision(key, {"signal": "flat"}, **common)
    assert journal.grid_cursor("account-a", "strategy-a", "cohort-1") is None
    assert (
        journal._connection.execute("SELECT COUNT(*) FROM execution_decisions").fetchone()[0] == 0
    )
    assert journal.run_order_count("account-a", "strategy-a", "budget-evidence") == 0

    with pytest.raises(ExecutionDecisionJournalError, match="INVALID_RUN_ORDER_BUDGET_RESERVATION"):
        journal.record_grid_decision(
            key,
            {"signal": "flat"},
            **common,
            expected_run_order_intents_used=0,
        )
    assert (
        journal._connection.execute("SELECT COUNT(*) FROM execution_decisions").fetchone()[0] == 0
    )

    with pytest.raises(ExecutionDecisionJournalError, match="RUN_ORDER_BUDGET_EVIDENCE_RESERVED"):
        journal.record_grid_decision(
            key,
            {"signal": "flat", "_journal_run_order_reservation": {"fake": True}},
            **common,
            expected_run_order_intents_used=0,
            remaining_exit_intent_reserve=0,
        )
    assert (
        journal._connection.execute("SELECT COUNT(*) FROM execution_decisions").fetchone()[0] == 0
    )

    noop = journal.record_grid_decision(
        key,
        {"signal": "flat"},
        **common,
        expected_run_order_intents_used=0,
        remaining_exit_intent_reserve=0,
    )
    assert noop.is_new_grid is True
    assert noop.decision.economic_payload["_journal_run_order_reservation"] == {
        "max_order_intents_per_run": 0,
        "remaining_exit_intent_reserve": 0,
    }
    journal.close()


def test_risk_decision_uses_atomic_run_budget_and_reserve(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "risk-budget.sqlite3")
    opening = journal.record_grid_decision(
        _decision_key(run_id="risk-budget"),
        {"signal": "open"},
        intent_keys=(_intent_key("SIM-IF-1", leg=0, effect="OPEN"),),
        epoch_id="epoch-a",
        batch_id="batch-a",
        eligible=True,
        complete=True,
        live_ready=True,
        inputs_complete=True,
        max_order_intents_per_run=3,
        expected_run_order_intents_used=0,
        remaining_exit_intent_reserve=2,
    )
    assert opening.is_new_grid is True
    assert journal.run_order_count("account-a", "strategy-a", "risk-budget") == 1

    missing_reservation_key = _decision_key(
        run_id="risk-budget", close_time="2026-10-20T10:00:30Z", kind="risk"
    )
    before = journal._connection.execute("SELECT COUNT(*) FROM execution_decisions").fetchone()[0]
    with pytest.raises(
        ExecutionDecisionJournalError, match="RUN_ORDER_BUDGET_RESERVATION_REQUIRED"
    ):
        journal.record_risk_decision(
            missing_reservation_key,
            {"signal": "reduce"},
            intent_keys=(_intent_key("SIM-IF-1", side="SELL", effect="CLOSE"),),
            max_order_intents_per_run=3,
        )
    assert (
        journal._connection.execute("SELECT COUNT(*) FROM execution_decisions").fetchone()[0]
        == before
    )
    assert journal.run_order_count("account-a", "strategy-a", "risk-budget") == 1

    close_key = _decision_key(run_id="risk-budget", close_time="2026-10-20T10:01:00Z", kind="risk")
    close_intents = (_intent_key("SIM-IF-1", action="SUBMIT", side="SELL", effect="CLOSE"),)
    close = journal.record_risk_decision(
        close_key,
        {"signal": "reduce"},
        intent_keys=close_intents,
        max_order_intents_per_run=3,
        expected_run_order_intents_used=1,
        remaining_exit_intent_reserve=1,
    )
    assert close.is_new_grid is True
    assert journal.run_order_count("account-a", "strategy-a", "risk-budget") == 2

    replay = journal.record_risk_decision(
        close_key,
        {"signal": "reduce"},
        intent_keys=close_intents,
        max_order_intents_per_run=3,
        expected_run_order_intents_used=0,
        remaining_exit_intent_reserve=1,
    )
    assert replay.is_new_grid is False
    assert journal.run_order_count("account-a", "strategy-a", "risk-budget") == 2

    with pytest.raises(ExecutionDecisionJournalError, match="DECISION_CONFLICT"):
        journal.record_risk_decision(
            close_key,
            {"signal": "reduce"},
            intent_keys=close_intents,
            max_order_intents_per_run=3,
            expected_run_order_intents_used=2,
            remaining_exit_intent_reserve=0,
        )

    next_risk_key = _decision_key(
        run_id="risk-budget", close_time="2026-10-20T10:02:00Z", kind="risk"
    )
    before = journal._connection.execute("SELECT COUNT(*) FROM execution_decisions").fetchone()[0]
    with pytest.raises(ExecutionDecisionJournalError, match="RUN_ORDER_BUDGET_STALE"):
        journal.record_risk_decision(
            next_risk_key,
            {"signal": "reduce-again"},
            intent_keys=close_intents,
            max_order_intents_per_run=3,
            expected_run_order_intents_used=1,
            remaining_exit_intent_reserve=0,
        )
    assert (
        journal._connection.execute("SELECT COUNT(*) FROM execution_decisions").fetchone()[0]
        == before
    )

    with pytest.raises(ExecutionDecisionJournalError, match="RUN_ORDER_BUDGET_EXCEEDED"):
        journal.record_risk_decision(
            next_risk_key,
            {"signal": "reduce-again"},
            intent_keys=close_intents,
            max_order_intents_per_run=3,
            expected_run_order_intents_used=2,
            remaining_exit_intent_reserve=1,
        )
    assert (
        journal._connection.execute("SELECT COUNT(*) FROM execution_decisions").fetchone()[0]
        == before
    )
    assert journal.run_order_count("account-a", "strategy-a", "risk-budget") == 2
    journal.close()


def test_run_order_budget_compare_and_swap_serializes_two_connections(tmp_path):
    path = tmp_path / "budget-concurrent.sqlite3"
    journals = (ExecutionDecisionJournal(path), ExecutionDecisionJournal(path))
    start = Barrier(2)

    def admit(index):
        start.wait(timeout=5)
        key = _grid_key(
            run_id="shared-run",
            cohort_id=f"cohort-{index}",
            close_time=f"2026-10-20T10:00:0{index}Z",
            kind="risk",
        )
        try:
            result = journals[index].record_risk_decision(
                key,
                {"signal": f"candidate-{index}"},
                intent_keys=(_intent_key(f"SIM-IF-{index + 1}", action="CANCEL"),),
                max_order_intents_per_run=2,
                expected_run_order_intents_used=0,
                remaining_exit_intent_reserve=1,
            )
            return "admitted" if result.is_new_grid else "replayed"
        except ExecutionDecisionJournalError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(admit, index) for index in range(2)]
        outcomes = [future.result(timeout=10) for future in futures]

    assert outcomes.count("admitted") == 1
    assert outcomes.count("RUN_ORDER_BUDGET_STALE") == 1
    assert journals[0].run_order_count("account-a", "strategy-a", "shared-run") == 1
    assert (
        journals[0]._connection.execute("SELECT COUNT(*) FROM execution_decisions").fetchone()[0]
        == 1
    )
    assert (
        journals[0]._connection.execute("SELECT COUNT(*) FROM execution_grid_cursors").fetchone()[0]
        == 0
    )
    for journal in journals:
        journal.close()


def test_run_order_budget_restart_respects_saved_usage_and_replays_without_charge(tmp_path):
    path = tmp_path / "budget-restart.sqlite3"
    journal = ExecutionDecisionJournal(path)
    first = journal.record_grid_decision(
        _decision_key(run_id="restart-budget"),
        {"signal": "open"},
        intent_keys=(_intent_key("SIM-IF-1"),),
        epoch_id="epoch-a",
        batch_id="batch-a",
        eligible=True,
        complete=True,
        live_ready=True,
        inputs_complete=True,
        max_order_intents_per_run=2,
        expected_run_order_intents_used=0,
        remaining_exit_intent_reserve=1,
    )
    assert first.is_new_grid is True
    journal.close()

    child = r"""
import json, sys
from backtrader.stores.execution_decision_journal import ExecutionDecisionJournal, ExecutionDecisionJournalError, ExecutionDecisionKey, ExecutionIntentKey
journal = ExecutionDecisionJournal(sys.argv[1])
first = journal.grid_cursor("account-a", "strategy-a", "cohort-1")
key = ExecutionDecisionKey("account-a", "strategy-a", "restart-budget", "cohort-1", "2026-10-20T10:01:00Z", "bar")
intent = ExecutionIntentKey("SUBMIT", "SIM-IF-2", "BUY", "OPEN", 0)
try:
    journal.record_grid_decision(key, {"signal":"open-again"}, intent_keys=(intent,), epoch_id="epoch-a", batch_id="batch-b", eligible=True, complete=True, live_ready=True, inputs_complete=True, max_order_intents_per_run=2, expected_run_order_intents_used=1, remaining_exit_intent_reserve=1)
except ExecutionDecisionJournalError as error:
    assert error.code == "RUN_ORDER_BUDGET_EXCEEDED"
else:
    raise AssertionError("reserved exit slot was consumed")
assert journal.run_order_count("account-a", "strategy-a", "restart-budget") == 1
assert journal.grid_cursor("account-a", "strategy-a", "cohort-1") == first
assert journal._connection.execute("SELECT COUNT(*) FROM execution_decisions").fetchone()[0] == 1
risk_key = ExecutionDecisionKey("account-a", "strategy-a", "restart-budget", "cohort-1", "2026-10-20T10:02:00Z", "risk")
close = ExecutionIntentKey("SUBMIT", "SIM-IF-1", "SELL", "CLOSE", 0)
saved = journal.record_risk_decision(risk_key, {"signal":"reduce"}, intent_keys=(close,), max_order_intents_per_run=2, expected_run_order_intents_used=1, remaining_exit_intent_reserve=0)
replay = journal.record_risk_decision(risk_key, {"signal":"reduce"}, intent_keys=(close,), max_order_intents_per_run=2, expected_run_order_intents_used=0, remaining_exit_intent_reserve=0)
assert saved.is_new_grid and not replay.is_new_grid
assert journal.run_order_count("account-a", "strategy-a", "restart-budget") == 2
print(json.dumps({"cursor_ordinal": first.ordinal, "risk_replayed": not replay.is_new_grid, "used": journal.run_order_count("account-a", "strategy-a", "restart-budget")}, sort_keys=True))
journal.close()
"""
    completed = subprocess.run(
        [sys.executable, "-c", child, str(path)],
        cwd=os.getcwd(),
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    assert json.loads(completed.stdout) == {
        "cursor_ordinal": 1,
        "risk_replayed": True,
        "used": 2,
    }


def test_run_order_budget_sql_failure_rolls_back_decision_cursor_and_usage(tmp_path):
    path = tmp_path / "budget-rollback.sqlite3"
    journal = ExecutionDecisionJournal(path)
    first = journal.record_grid_decision(
        _decision_key(run_id="rollback-budget"),
        {"signal": "first"},
        intent_keys=(_intent_key("SIM-IF-1"),),
        epoch_id="epoch-a",
        batch_id="batch-a",
        eligible=True,
        complete=True,
        live_ready=True,
        inputs_complete=True,
        max_order_intents_per_run=2,
        expected_run_order_intents_used=0,
        remaining_exit_intent_reserve=0,
    )
    with sqlite3.connect(path) as connection:
        connection.execute(
            """CREATE TRIGGER reject_budget_increment
               BEFORE UPDATE OF intent_count ON execution_run_order_budgets
               BEGIN SELECT RAISE(ABORT, 'synthetic budget failure'); END"""
        )
    with pytest.raises(ExecutionDecisionJournalError, match="JOURNAL_WRITE_FAILED"):
        journal.record_grid_decision(
            _decision_key(run_id="rollback-budget", close_time="2026-10-20T10:01:00Z"),
            {"signal": "second"},
            intent_keys=(_intent_key("SIM-IF-2"),),
            epoch_id="epoch-a",
            batch_id="batch-b",
            eligible=True,
            complete=True,
            live_ready=True,
            inputs_complete=True,
            max_order_intents_per_run=2,
            expected_run_order_intents_used=1,
            remaining_exit_intent_reserve=0,
        )
    journal.close()
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TRIGGER reject_budget_increment")

    recovered = ExecutionDecisionJournal(path)
    assert recovered.run_order_count("account-a", "strategy-a", "rollback-budget") == 1
    assert recovered.grid_cursor("account-a", "strategy-a", "cohort-1") == first.cursor
    assert (
        recovered._connection.execute("SELECT COUNT(*) FROM execution_decisions").fetchone()[0] == 1
    )
    recovered.close()
