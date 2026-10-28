"""Focused contracts for v16 candidates and v17-v20 journal-only workflows."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
import hashlib
import json
import shutil
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from threading import Barrier, Event

import pytest

from backtrader.stores import execution_journal_archive as archive_module
import backtrader.stores.execution_decision_journal as journal_module
from backtrader.stores.execution_decision_journal import (
    ExecutionDecisionJournal,
    ExecutionDecisionJournalError,
    ExecutionDecisionKey,
    ExecutionFeePairCandidate,
    ExecutionFeePairOpenContext,
    ExecutionFeePairTargetRoute,
    ExecutionIntentKey,
    ExecutionSourceMemberReceipt,
    ExecutionSourceRestartMarker,
    ExecutionSourceReceipt,
)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def _candidate(
    *,
    run_id="candidate-run",
    close_time="2026-10-28T10:00:00Z",
    epoch=1,
    cohort=None,
    calendar_id="calendar-a",
    calendar_version="calendar-v1",
    calendar_fingerprint=None,
    slot_index=0,
    slot_id=None,
    batch_id=None,
    tape_file_id="tape-file-a",
    tape_record_index=None,
    source_predecessor=None,
    source_restart_marker=None,
    source_members=None,
    member_sequence=1,
    member_role="live",
    member_generation="generation-source",
    session_id="session-a",
):
    cohort = cohort or "cohort-{}".format(epoch)
    key = ExecutionDecisionKey(
        account_scope="pair-account",
        strategy_scope="pair-strategy",
        logical_run_id=run_id,
        cohort_id=cohort,
        close_time=close_time,
        decision_kind="simnow-live",
    )
    slot_id = slot_id or "slot-{}-{}".format(epoch, slot_index)
    batch_id = batch_id or "{}:{}:{}:{}:{}".format(
        cohort, calendar_id, epoch, calendar_version, slot_index
    )
    calendar_fingerprint = calendar_fingerprint or _digest("calendar")
    if source_members is None:
        close = datetime.fromisoformat(close_time.replace("Z", "+00:00"))

        def timestamp(value):
            return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
                "+00:00", "Z"
            )

        source_members = (
            ExecutionSourceMemberReceipt(
                member_id="SIM-A",
                source_ref="synthetic-ctp",
                source_role=member_role,
                connection_generation=member_generation,
                feed_sequence=member_sequence,
                bar_id="bar-{}".format(member_sequence),
                bucket_start=timestamp(close - timedelta(minutes=1)),
                close_time=close_time,
                available_at=timestamp(close + timedelta(seconds=1)),
                trading_day="20261028",
                session_segment="morning",
                timezone_id="UTC",
                clock_domain_id="synthetic-clock",
                complete=True,
                quality="GOOD",
                present=True,
            ),
        )
    if source_predecessor is not None:
        source_predecessor_sha256 = source_predecessor.receipt_sha256
    else:
        source_predecessor_sha256 = None
    if tape_record_index is None:
        tape_record_index = slot_index + 1
    return ExecutionFeePairCandidate(
        key=key,
        source_kind="simnow-live",
        calendar_id=calendar_id,
        calendar_version=calendar_version,
        calendar_fingerprint=calendar_fingerprint,
        epoch_id=epoch,
        slot_index=slot_index,
        slot_id=slot_id,
        batch_id=batch_id,
        readiness="LIVE_READY",
        expected_tape_file_id=tape_file_id,
        expected_tape_record_index=tape_record_index,
        source_candidate_sha256=_digest("source-{}".format(run_id)),
        source_predecessor_sha256=source_predecessor_sha256,
        source_predecessor=source_predecessor,
        source_restart_marker=source_restart_marker,
        source_members=source_members,
        signal_sha256=_digest("signal-{}".format(run_id)),
        factor_snapshot_sha256=_digest("factor-{}".format(run_id)),
        target_ids=("SIM-A", "SIM-B"),
        directions=(1, -1),
        quote_identity_sha256s=(_digest("quote-a"), _digest("quote-b")),
        account_session_id=session_id,
        account_session_generation="generation-{}".format(session_id),
    )


def _candidate_with_members(*, run_id, member_count, source_ref_length):
    base = _candidate(run_id=run_id)
    template = base.source_members[0]
    members = tuple(
        replace(
            template,
            member_id="SIM-{0:03d}".format(index),
            source_ref="source-" + "x" * source_ref_length,
            feed_sequence=index + 1,
        )
        for index in range(member_count)
    )
    return replace(base, source_members=members)


def _canonical_candidate_bytes(candidate):
    return journal_module._canonical_json(
        journal_module._fee_pair_candidate_values(candidate)
    ).encode("utf-8")


def _candidate_87_members_71659_bytes():
    candidate = _candidate_with_members(
        run_id="workflow-87-members",
        member_count=87,
        source_ref_length=280,
    )
    padding = 71_659 - len(_canonical_candidate_bytes(candidate))
    assert 0 <= padding <= 2_048 - len(candidate.source_members[0].source_ref)
    first = replace(
        candidate.source_members[0],
        source_ref=candidate.source_members[0].source_ref + "x" * padding,
    )
    candidate = replace(candidate, source_members=(first,) + candidate.source_members[1:])
    assert len(_canonical_candidate_bytes(candidate)) == 71_659
    return candidate


def _source_receipt(*, run_id="candidate-run", close_time="2026-10-28T10:00:00Z"):
    cohort = "cohort-1"
    batch_id = "{}:{}:{}:{}:{}".format(cohort, "calendar-a", 1, "calendar-v1", 0)
    member = _candidate(
        run_id=run_id,
        close_time=close_time,
        cohort=cohort,
        member_sequence=1,
    ).source_members[0]
    return ExecutionSourceReceipt(
        source_kind="simnow-live",
        cohort_id=cohort,
        calendar_id="calendar-a",
        calendar_version="calendar-v1",
        calendar_fingerprint=_digest("calendar"),
        epoch_id=1,
        slot_index=0,
        slot_id="slot-1-0",
        close_time=close_time,
        batch_id=batch_id,
        readiness="LIVE_READY",
        tape_file_id="tape-file-a",
        tape_record_id="record-1",
        tape_record_index=1,
        members=(member,),
    )


def _record_source_grid(journal, *, run_id="candidate-run", close_time="2026-10-28T10:00:00Z"):
    receipt = _source_receipt(run_id=run_id, close_time=close_time)
    key = ExecutionDecisionKey(
        account_scope="pair-account",
        strategy_scope="pair-strategy",
        logical_run_id=run_id,
        cohort_id=receipt.cohort_id,
        close_time=receipt.close_time,
        decision_kind=receipt.source_kind,
    )
    return journal.record_grid_decision(
        key,
        {"signal": "flat"},
        epoch_id=str(receipt.epoch_id),
        batch_id=receipt.batch_id,
        eligible=True,
        complete=True,
        live_ready=True,
        inputs_complete=True,
        source_receipt=receipt,
    )


def _drop_v23_single_row_tape_schema(connection: sqlite3.Connection) -> None:
    amount_schema = connection.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
        "AND name='execution_fee_pair_amount_reservations'"
    ).fetchone()[0]
    if amount_schema:
        amount_rows = connection.execute(
            "SELECT COUNT(*) FROM execution_fee_pair_amount_reservations"
        ).fetchone()[0]
        if amount_rows:
            raise AssertionError("cannot downgrade a journal with v24 amount reservations")
        connection.execute(
            "DROP TRIGGER IF EXISTS execution_fee_pair_amount_reservation_no_update"
        )
        connection.execute(
            "DROP TRIGGER IF EXISTS execution_fee_pair_amount_reservation_no_delete"
        )
        connection.execute("DROP TABLE execution_fee_pair_amount_reservations")
    count = connection.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
        "AND name='execution_fee_pair_grid_single_row_tape_intents'"
    ).fetchone()[0]
    if count:
        rows = connection.execute(
            "SELECT COUNT(*) FROM execution_fee_pair_grid_single_row_tape_intents"
        ).fetchone()[0]
        if rows:
            raise AssertionError("cannot downgrade a journal with v23 single-row intents")
    quarantine_count = connection.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
        "AND name='execution_fee_pair_legacy_unresolved_v23'"
    ).fetchone()[0]
    if quarantine_count:
        quarantined = connection.execute(
            "SELECT COUNT(*) FROM execution_fee_pair_legacy_unresolved_v23"
        ).fetchone()[0]
        if quarantined:
            raise AssertionError("cannot downgrade a journal with v23 legacy quarantine rows")
    for trigger in (
        "execution_fee_pair_grid_single_row_tape_intent_no_update",
        "execution_fee_pair_grid_single_row_tape_intent_no_delete",
        "execution_fee_pair_legacy_unresolved_v23_no_update",
        "execution_fee_pair_legacy_unresolved_v23_no_delete",
        "execution_fee_pair_workflow_durable_reservation_state",
    ):
        connection.execute("DROP TRIGGER IF EXISTS {}".format(trigger))
    connection.execute("DROP INDEX IF EXISTS execution_fee_pair_grid_single_row_tape_position")
    connection.execute("DROP TABLE IF EXISTS execution_fee_pair_grid_single_row_tape_intents")
    connection.execute("DROP TABLE IF EXISTS execution_fee_pair_legacy_unresolved_v23")


def _downgrade_to_v15(connection: sqlite3.Connection) -> None:
    _drop_v23_single_row_tape_schema(connection)
    _drop_v21_order_sysid_binding_schema(connection)
    for trigger in (
        "execution_fee_pair_workflow_grid_settlement_insert",
        "execution_fee_pair_workflow_grid_settlement_no_update",
        "execution_fee_pair_workflow_grid_settlement_no_delete",
        "execution_fee_pair_workflow_state",
    ):
        connection.execute("DROP TRIGGER IF EXISTS {}".format(trigger))
    connection.execute("DROP INDEX IF EXISTS execution_fee_pair_workflow_one_active")
    connection.execute("DROP TABLE IF EXISTS execution_fee_pair_workflow_grid_settlements")
    connection.execute("DROP TABLE execution_fee_pair_workflow_decision_reservations")
    connection.execute("DROP TABLE execution_fee_pair_workflow_durable_reservations")
    connection.execute("DROP TABLE execution_fee_pair_workflow_events")
    connection.execute("DROP TABLE execution_fee_pair_workflows")
    connection.execute("DROP TABLE execution_fee_pair_candidate_capacity_reservations")
    connection.execute("DROP TABLE execution_fee_pair_candidate_events")
    connection.execute("DROP TABLE execution_fee_pair_candidates")
    connection.execute("PRAGMA user_version=15")


def _drop_v21_order_sysid_binding_schema(connection: sqlite3.Connection) -> None:
    """Remove the current-only identity/dispatch schemas from old fixtures."""

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

    connection.execute(
        "DROP TRIGGER IF EXISTS execution_known_ctp_order_sysid_binding_no_update"
    )
    connection.execute(
        "DROP TRIGGER IF EXISTS execution_known_ctp_order_sysid_binding_no_delete"
    )
    connection.execute("DROP TABLE IF EXISTS execution_known_ctp_order_sysid_bindings")


def _downgrade_v20_workflow_to_v18(connection: sqlite3.Connection) -> None:
    """Restore v18 DDL and its exact capacity projection for migration tests."""

    _drop_v23_single_row_tape_schema(connection)
    _drop_v21_order_sysid_binding_schema(connection)
    connection.row_factory = sqlite3.Row

    def table_bytes(table: str) -> int:
        return sum(
            len(journal_module.canonical_sql_row_bytes(row))
            for row in connection.execute("SELECT * FROM {}".format(table))
        )

    changed_tables = (
        "execution_fee_pair_workflows",
        "execution_fee_pair_workflow_events",
        "execution_fee_pair_workflow_durable_reservations",
    )
    old_bytes = sum(table_bytes(table) for table in changed_tables)
    usage = connection.execute(
        "SELECT payload_bytes FROM execution_durable_capacity_usage WHERE capacity_class='BASE'"
    ).fetchone()
    if usage is None:
        raise AssertionError("BASE capacity usage row is missing")
    old_usage_bytes = usage["payload_bytes"]
    if connection.execute(
        "SELECT COUNT(*) FROM execution_fee_pair_workflow_grid_settlements"
    ).fetchone()[0]:
        raise AssertionError("cannot downgrade a journal with settled grid rows")
    if connection.execute(
        "SELECT COUNT(*) FROM execution_fee_pair_workflow_events "
        "WHERE event_sequence>4 OR event_kind='GRID_TAPE_APPEND_INTENT'"
    ).fetchone()[0]:
        raise AssertionError("cannot downgrade a journal with v20 tape-intent rows")

    old_event = {
        "event_id": "e" * 64,
        "candidate_id": "c" * 64,
        "event_sequence": 4,
        "event_kind": "SOURCE_ONLY",
        "event_payload_json": "{}",
        "created_at_ns": 1,
    }
    v20_event = {
        **old_event,
        "tape_file_id": None,
        "record_index": None,
        "tape_record_json": None,
    }
    event_column_growth = len(journal_module.canonical_sql_row_bytes(v20_event)) - len(
        journal_module.canonical_sql_row_bytes(old_event)
    )

    for trigger in (
        "execution_fee_pair_workflow_grid_settlement_insert",
        "execution_fee_pair_workflow_grid_settlement_no_update",
        "execution_fee_pair_workflow_grid_settlement_no_delete",
        "execution_fee_pair_workflow_state",
        "execution_fee_pair_workflow_durable_reservation_state",
        "execution_fee_pair_workflow_event_no_update",
        "execution_fee_pair_workflow_event_no_delete",
    ):
        connection.execute("DROP TRIGGER IF EXISTS {}".format(trigger))
    connection.execute("DROP INDEX IF EXISTS execution_fee_pair_workflow_tape_position")
    connection.execute("DROP INDEX IF EXISTS execution_fee_pair_workflow_one_active")
    connection.execute("DROP TABLE execution_fee_pair_workflow_grid_settlements")
    connection.execute(
        "ALTER TABLE execution_fee_pair_workflow_events "
        "RENAME TO execution_fee_pair_workflow_events_v20"
    )
    connection.execute(journal_module._FEE_PAIR_WORKFLOW_EVENT_TABLE_SQL_V18)
    connection.execute(
        """INSERT INTO execution_fee_pair_workflow_events
           (event_id,candidate_id,event_sequence,event_kind,event_payload_json,created_at_ns)
           SELECT event_id,candidate_id,event_sequence,event_kind,event_payload_json,created_at_ns
           FROM execution_fee_pair_workflow_events_v20"""
    )
    connection.execute("DROP TABLE execution_fee_pair_workflow_events_v20")
    connection.execute("ALTER TABLE execution_fee_pair_workflows DROP COLUMN grid_decision_id")

    reservation_rows = connection.execute(
        """SELECT candidate_id,reserved_records,reserved_bytes FROM
           execution_fee_pair_workflow_durable_reservations WHERE state='ACTIVE'"""
    ).fetchall()
    for reservation in reservation_rows:
        last_event = connection.execute(
            """SELECT MAX(event_sequence) AS sequence FROM
               execution_fee_pair_workflow_events WHERE candidate_id=?""",
            (reservation["candidate_id"],),
        ).fetchone()["sequence"]
        if type(last_event) is not int or not 1 <= last_event <= 3:
            raise AssertionError("unexpected active workflow event sequence")
        future_rows = 4 - last_event
        restored_bytes = reservation["reserved_bytes"] - future_rows * event_column_growth
        if restored_bytes <= 0:
            raise AssertionError("v20 reservation cannot be restored to v18")
        connection.execute(
            """UPDATE execution_fee_pair_workflow_durable_reservations
               SET reserved_bytes=? WHERE candidate_id=? AND state='ACTIVE'""",
            (restored_bytes, reservation["candidate_id"]),
        )

    connection.execute(journal_module._FEE_PAIR_WORKFLOW_ACTIVE_INDEX_SQL_V18)
    connection.execute(journal_module._FEE_PAIR_WORKFLOW_STATE_TRIGGER_SQL_V18)
    connection.execute(journal_module._FEE_PAIR_WORKFLOW_EVENT_NO_UPDATE_TRIGGER_SQL)
    connection.execute(journal_module._FEE_PAIR_WORKFLOW_EVENT_NO_DELETE_TRIGGER_SQL)
    connection.execute(journal_module._FEE_PAIR_WORKFLOW_DURABLE_RESERVATION_TRIGGER_SQL)
    new_bytes = sum(table_bytes(table) for table in changed_tables)
    connection.execute(
        """UPDATE execution_durable_capacity_usage SET payload_bytes=?
           WHERE capacity_class='BASE'""",
        (old_usage_bytes + new_bytes - old_bytes,),
    )


def _downgrade_v20_workflow_to_v19(connection: sqlite3.Connection) -> None:
    """Restore the v19 event DDL and reservation accounting for migration tests."""

    _drop_v23_single_row_tape_schema(connection)
    _drop_v21_order_sysid_binding_schema(connection)
    connection.row_factory = sqlite3.Row

    def table_bytes(table: str) -> int:
        return sum(
            len(journal_module.canonical_sql_row_bytes(row))
            for row in connection.execute("SELECT * FROM {}".format(table))
        )

    changed_tables = (
        "execution_fee_pair_workflow_events",
        "execution_fee_pair_workflow_durable_reservations",
    )
    old_bytes = sum(table_bytes(table) for table in changed_tables)
    usage = connection.execute(
        "SELECT payload_bytes FROM execution_durable_capacity_usage WHERE capacity_class='BASE'"
    ).fetchone()
    if usage is None:
        raise AssertionError("BASE capacity usage row is missing")
    old_usage_bytes = usage["payload_bytes"]
    if connection.execute(
        "SELECT COUNT(*) FROM execution_fee_pair_workflow_events "
        "WHERE event_sequence>4 OR event_kind='GRID_TAPE_APPEND_INTENT'"
    ).fetchone()[0]:
        raise AssertionError("cannot downgrade a journal with v20 tape-intent rows")
    if connection.execute(
        "SELECT COUNT(*) FROM execution_fee_pair_workflow_grid_settlements"
    ).fetchone()[0]:
        raise AssertionError("cannot downgrade a journal with settled grid rows")

    old_event = {
        "event_id": "e" * 64,
        "candidate_id": "c" * 64,
        "event_sequence": 4,
        "event_kind": "GRID_SETTLED",
        "event_payload_json": "{}",
        "created_at_ns": 1,
    }
    v20_event = {
        **old_event,
        "tape_file_id": None,
        "record_index": None,
        "tape_record_json": None,
    }
    event_column_growth = len(journal_module.canonical_sql_row_bytes(v20_event)) - len(
        journal_module.canonical_sql_row_bytes(old_event)
    )

    for trigger in (
        "execution_fee_pair_workflow_grid_settlement_insert",
        "execution_fee_pair_workflow_state",
        "execution_fee_pair_workflow_durable_reservation_state",
        "execution_fee_pair_workflow_event_no_update",
        "execution_fee_pair_workflow_event_no_delete",
    ):
        connection.execute("DROP TRIGGER IF EXISTS {}".format(trigger))
    connection.execute("DROP INDEX IF EXISTS execution_fee_pair_workflow_tape_position")
    connection.execute(
        "ALTER TABLE execution_fee_pair_workflow_events "
        "RENAME TO execution_fee_pair_workflow_events_v20"
    )
    connection.execute(journal_module._FEE_PAIR_WORKFLOW_EVENT_TABLE_SQL)
    connection.execute(
        """INSERT INTO execution_fee_pair_workflow_events
           (event_id,candidate_id,event_sequence,event_kind,event_payload_json,created_at_ns)
           SELECT event_id,candidate_id,event_sequence,event_kind,event_payload_json,created_at_ns
           FROM execution_fee_pair_workflow_events_v20"""
    )
    connection.execute("DROP TABLE execution_fee_pair_workflow_events_v20")

    reservation_rows = connection.execute(
        """SELECT candidate_id,reserved_records,reserved_bytes FROM
           execution_fee_pair_workflow_durable_reservations WHERE state='ACTIVE'"""
    ).fetchall()
    for reservation in reservation_rows:
        last_event = connection.execute(
            """SELECT MAX(event_sequence) AS sequence FROM
               execution_fee_pair_workflow_events WHERE candidate_id=?""",
            (reservation["candidate_id"],),
        ).fetchone()["sequence"]
        if type(last_event) is not int or not 1 <= last_event <= 3:
            raise AssertionError("unexpected active workflow event sequence")
        future_rows = 4 - last_event
        restored_bytes = reservation["reserved_bytes"] - future_rows * event_column_growth
        if restored_bytes <= 0:
            raise AssertionError("v20 reservation cannot be restored to v19")
        connection.execute(
            """UPDATE execution_fee_pair_workflow_durable_reservations
               SET reserved_bytes=? WHERE candidate_id=? AND state='ACTIVE'""",
            (restored_bytes, reservation["candidate_id"]),
        )

    connection.execute(journal_module._FEE_PAIR_WORKFLOW_STATE_TRIGGER_SQL)
    connection.execute(journal_module._FEE_PAIR_WORKFLOW_EVENT_NO_UPDATE_TRIGGER_SQL)
    connection.execute(journal_module._FEE_PAIR_WORKFLOW_EVENT_NO_DELETE_TRIGGER_SQL)
    connection.execute(journal_module._FEE_PAIR_WORKFLOW_GRID_SETTLEMENT_INSERT_TRIGGER_SQL)
    connection.execute(journal_module._FEE_PAIR_WORKFLOW_DURABLE_RESERVATION_TRIGGER_SQL)
    new_bytes = sum(table_bytes(table) for table in changed_tables)
    connection.execute(
        """UPDATE execution_durable_capacity_usage SET payload_bytes=?
           WHERE capacity_class='BASE'""",
        (old_usage_bytes + new_bytes - old_bytes,),
    )


def test_candidate_capacity_reservation_is_atomic_and_settlement_neutral(tmp_path):
    path = tmp_path / "candidate-base-capacity.sqlite3"
    limits = {
        "max_durable_base_records": 4,
        "max_durable_base_bytes": 1_000_000,
        "max_durable_settlement_records": 100,
        "max_durable_settlement_bytes": 1_000_000,
    }
    first = ExecutionDecisionJournal(path, **limits)
    second = ExecutionDecisionJournal(path, **limits)
    token = "owner-token-" + "b" * 40
    try:
        first.register_fee_pair_required_scope("pair-account", "pair-strategy")
        record = first.reserve_fee_pair_candidate(_candidate(), owner_token=token, ttl_seconds=10)
        baseline = {
            row["capacity_class"]: (row["record_count"], row["payload_bytes"])
            for row in first._connection.execute(
                "SELECT capacity_class,record_count,payload_bytes "
                "FROM execution_durable_capacity_usage"
            )
        }
        assert baseline["BASE"][0] == 3
        assert baseline["SETTLEMENT"][0] == 2

        barrier = Barrier(2)

        def write_base(journal, run_id):
            barrier.wait(timeout=5)
            try:
                journal.record_decision(
                    ExecutionDecisionKey(
                        account_scope="unregistered-account",
                        strategy_scope="unregistered-strategy",
                        logical_run_id=run_id,
                        cohort_id="cohort-a",
                        close_time="2026-10-28T10:01:00Z",
                        decision_kind="bar",
                    ),
                    {"signal": "flat"},
                )
            except ExecutionDecisionJournalError as error:
                return error.code
            return "WRITTEN"

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(
                pool.map(
                    lambda args: write_base(*args),
                    (
                        (first, "capacity-racer-a"),
                        (second, "capacity-racer-b"),
                    ),
                )
            )
        assert results == [
            "DURABLE_BASE_RECORDS_EXHAUSTED",
            "DURABLE_BASE_RECORDS_EXHAUSTED",
        ]
        assert (
            first._connection.execute("SELECT COUNT(*) FROM execution_decisions").fetchone()[0] == 0
        )

        first._connection.execute(
            """CREATE TRIGGER reject_candidate_claim_event
               BEFORE INSERT ON execution_fee_pair_candidate_events
               WHEN NEW.event_sequence=2
               BEGIN SELECT RAISE(ABORT,'synthetic candidate event failure'); END"""
        )
        with pytest.raises(ExecutionDecisionJournalError, match="JOURNAL_WRITE_FAILED"):
            first.record_fee_pair_append_claim(record.candidate_id, owner_token=token)
        assert first.fee_pair_candidate(record.candidate_id).state == "RESERVED"
        assert (
            first._connection.execute(
                "SELECT COUNT(*) FROM execution_fee_pair_candidate_events"
            ).fetchone()[0]
            == 1
        )
        reserved = first._connection.execute(
            """SELECT reserved_records,reserved_bytes,state
               FROM execution_fee_pair_candidate_capacity_reservations"""
        ).fetchone()
        assert tuple(reserved) == (1, reserved[1], "RESERVED") and reserved[1] > 0
        first._connection.execute("DROP TRIGGER reject_candidate_claim_event")

        # SQLite write errors intentionally latch the caller object closed.
        # Reopening this journal on the same process does not change owner
        # identity and lets the test verify the committed RESERVED state.
        first.close()
        first = ExecutionDecisionJournal(path, **limits)
        claimed = first.record_fee_pair_append_claim(record.candidate_id, owner_token=token)
        assert claimed.state == "APPEND_CLAIMED"
        with pytest.raises(
            ExecutionDecisionJournalError, match="FEE_PAIR_CANDIDATE_ALREADY_CLAIMED"
        ):
            second.record_fee_pair_append_claim(record.candidate_id, owner_token=token)
        assert (
            first._connection.execute(
                "SELECT record_count FROM execution_durable_capacity_usage "
                "WHERE capacity_class='BASE'"
            ).fetchone()[0]
            == 4
        )
        after = {
            row["capacity_class"]: (row["record_count"], row["payload_bytes"])
            for row in first._connection.execute(
                "SELECT capacity_class,record_count,payload_bytes "
                "FROM execution_durable_capacity_usage"
            )
        }
        assert after["SETTLEMENT"] == baseline["SETTLEMENT"]
        assert (
            first._connection.execute(
                "SELECT reserved_records FROM execution_fee_pair_candidate_capacity_reservations"
            ).fetchone()[0]
            == 0
        )
    finally:
        second.close()
        first.close()


def test_candidate_identity_matches_source_kind_batch_and_decision(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "candidate-source-identity.sqlite3")
    token = "owner-token-identity-" + "i" * 32
    try:
        journal.register_fee_pair_required_scope("pair-account", "pair-strategy")
        with pytest.raises(ExecutionDecisionJournalError, match="INVALID_FEE_PAIR_CANDIDATE"):
            replace(_candidate(), source_kind="other-source")
        with pytest.raises(ExecutionDecisionJournalError, match="INVALID_FEE_PAIR_CANDIDATE"):
            _candidate(batch_id="batch-a")
        candidate = _candidate()
        member = candidate.source_members[0]
        mismatched_origin = replace(
            member,
            origin_partition={
                "schema": "backtrader.execution_source_origin_partition.v1",
                "cohort_id": candidate.key.cohort_id,
                "epoch_id": candidate.epoch_id,
                "member_id": member.member_id,
                "source_ref": member.source_ref,
                "source_role": "history",
                "connection_generation": member.connection_generation,
            },
        )
        with pytest.raises(ExecutionDecisionJournalError, match="INVALID_FEE_PAIR_CANDIDATE"):
            replace(candidate, source_members=(mismatched_origin,))

        record = journal.reserve_fee_pair_candidate(
            candidate, owner_token=token, ttl_seconds=10
        )
        assert record.candidate_id
        assert journal.fee_pair_candidate(record.candidate_id).state == "RESERVED"
    finally:
        journal.close()


def test_candidate_validates_nonempty_same_epoch_source_highwater(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "candidate-source-continuity.sqlite3")
    token = "owner-token-continuity-" + "s" * 32
    try:
        _record_source_grid(journal)
        highwater = journal.source_highwater(
            "pair-account", "pair-strategy", "candidate-run", "simnow-live"
        )
        assert highwater is not None
        journal.register_fee_pair_required_scope("pair-account", "pair-strategy")

        later = _candidate(
            close_time="2026-10-28T10:01:00Z",
            cohort=highwater.receipt.cohort_id,
            calendar_fingerprint=highwater.receipt.calendar_fingerprint,
            slot_index=1,
            slot_id="slot-1-1",
            tape_record_index=2,
            source_predecessor=highwater.reference,
            member_sequence=2,
        )
        wrong_head = replace(
            highwater.reference,
            receipt_sha256=_digest("different-head"),
        )
        with pytest.raises(
            ExecutionDecisionJournalError,
            match="FEE_PAIR_CANDIDATE_SOURCE_HEAD_MISMATCH",
        ):
            journal.reserve_fee_pair_candidate(
                _candidate(
                    close_time="2026-10-28T10:01:00Z",
                    cohort=highwater.receipt.cohort_id,
                    calendar_fingerprint=highwater.receipt.calendar_fingerprint,
                    slot_index=1,
                    tape_record_index=2,
                    source_predecessor=wrong_head,
                    member_sequence=2,
                ),
                owner_token="owner-token-other-" + "o" * 32,
                ttl_seconds=10,
            )
        assert journal._connection.execute(
            "SELECT COUNT(*) FROM execution_fee_pair_candidates"
        ).fetchone()[0] == 0

        reserved = journal.reserve_fee_pair_candidate(
            later, owner_token=token, ttl_seconds=10
        )
        assert reserved.state == "RESERVED"
    finally:
        journal.close()


def test_candidate_accepts_existing_legacy_live_member_origin_binding(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "candidate-legacy-live-origin.sqlite3")
    token = "owner-token-origin-" + "g" * 32
    try:
        _record_source_grid(journal)
        highwater = journal.source_highwater(
            "pair-account", "pair-strategy", "candidate-run", "simnow-live"
        )
        assert highwater is not None
        journal.register_fee_pair_required_scope("pair-account", "pair-strategy")
        member = _candidate(
            close_time="2026-10-28T10:01:00Z",
            cohort=highwater.receipt.cohort_id,
            calendar_fingerprint=highwater.receipt.calendar_fingerprint,
            slot_index=1,
            member_sequence=2,
        ).source_members[0]
        member = replace(
            member,
            origin_partition={
                "schema": "backtrader.execution_source_origin_partition.v1",
                "cohort_id": highwater.receipt.cohort_id,
                "epoch_id": highwater.receipt.epoch_id,
                "member_id": member.member_id,
                "source_ref": member.source_ref,
                "source_role": "live",
                "connection_generation": member.connection_generation,
            },
        )
        candidate = _candidate(
            close_time="2026-10-28T10:01:00Z",
            cohort=highwater.receipt.cohort_id,
            calendar_fingerprint=highwater.receipt.calendar_fingerprint,
            slot_index=1,
            tape_record_index=2,
            source_predecessor=highwater.reference,
            source_members=(member,),
            member_sequence=2,
        )
        reserved = journal.reserve_fee_pair_candidate(
            candidate, owner_token=token, ttl_seconds=10
        )
        assert reserved.state == "RESERVED"
    finally:
        journal.close()


def test_candidate_rejects_noncontiguous_slot_and_corrupt_source_head(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "candidate-source-invalid.sqlite3")
    token = "owner-token-invalid-" + "v" * 32
    try:
        _record_source_grid(journal)
        highwater = journal.source_highwater(
            "pair-account", "pair-strategy", "candidate-run", "simnow-live"
        )
        assert highwater is not None
        journal.register_fee_pair_required_scope("pair-account", "pair-strategy")

        same_epoch = {
            "close_time": "2026-10-28T10:01:00Z",
            "cohort": highwater.receipt.cohort_id,
            "calendar_fingerprint": highwater.receipt.calendar_fingerprint,
            "slot_index": 1,
            "slot_id": "slot-1-1",
            "source_predecessor": highwater.reference,
            "member_sequence": 2,
        }
        invalid_candidates = (
            (
                _candidate(
                    **dict(same_epoch, close_time="2026-10-28T10:02:00Z", slot_index=2,
                           slot_id="slot-1-2", tape_record_index=3)
                ),
                "SOURCE_RECEIPT_SEQUENCE_INVALID",
            ),
            (
                _candidate(**dict(same_epoch, tape_record_index=3)),
                "SOURCE_RECEIPT_SEQUENCE_INVALID",
            ),
            (
                _candidate(**dict(same_epoch, calendar_fingerprint=_digest("calendar-drift"))),
                "SOURCE_RECEIPT_SEQUENCE_INVALID",
            ),
            (
                _candidate(**dict(same_epoch, calendar_id="calendar-drift")),
                "SOURCE_RECEIPT_SEQUENCE_INVALID",
            ),
            (
                _candidate(**dict(same_epoch, calendar_version="calendar-drift")),
                "SOURCE_RECEIPT_SEQUENCE_INVALID",
            ),
            (
                _candidate(**dict(same_epoch, tape_file_id="tape-file-drift")),
                "SOURCE_RECEIPT_SEQUENCE_INVALID",
            ),
            (
                _candidate(**dict(same_epoch, cohort="cohort-drift")),
                "SOURCE_RECEIPT_SEQUENCE_INVALID",
            ),
            (
                _candidate(
                    epoch=3,
                    cohort="cohort-3",
                    close_time="2026-10-28T10:01:00Z",
                    calendar_fingerprint=_digest("calendar-epoch-3"),
                    tape_file_id="tape-file-epoch-3",
                    source_predecessor=highwater.reference,
                ),
                "SOURCE_RECEIPT_EPOCH_INVALID",
            ),
        )
        for candidate, expected_code in invalid_candidates:
            with pytest.raises(ExecutionDecisionJournalError, match=expected_code):
                journal.reserve_fee_pair_candidate(
                    candidate, owner_token=token, ttl_seconds=10
                )
        assert journal._connection.execute(
            "SELECT COUNT(*) FROM execution_fee_pair_candidates"
        ).fetchone()[0] == 0

        journal._connection.execute(
            "UPDATE execution_source_highwaters SET receipt_json='{}' "
            "WHERE account_scope='pair-account' AND strategy_scope='pair-strategy' "
            "AND logical_run_id='candidate-run' AND source_kind='simnow-live'"
        )
        valid_next = _candidate(
            close_time="2026-10-28T10:01:00Z",
            cohort=highwater.receipt.cohort_id,
            calendar_fingerprint=highwater.receipt.calendar_fingerprint,
            slot_index=1,
            tape_record_index=2,
            source_predecessor=highwater.reference,
            member_sequence=2,
        )
        with pytest.raises(
            ExecutionDecisionJournalError, match="SOURCE_HIGHWATER_CORRUPT"
        ):
            journal.reserve_fee_pair_candidate(
                valid_next, owner_token=token, ttl_seconds=10
            )
        assert journal._connection.execute(
            "SELECT COUNT(*) FROM execution_fee_pair_candidates"
        ).fetchone()[0] == 0
    finally:
        journal.close()


def test_candidate_validates_epoch_restart_marker_against_full_head(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "candidate-source-restart.sqlite3")
    token = "owner-token-restart-" + "r" * 32
    try:
        _record_source_grid(journal)
        highwater = journal.source_highwater(
            "pair-account", "pair-strategy", "candidate-run", "simnow-live"
        )
        assert highwater is not None
        journal.register_fee_pair_required_scope("pair-account", "pair-strategy")
        history_member = _candidate(
            epoch=2,
            cohort="cohort-2",
            member_role="history",
            member_sequence=1,
        ).source_members[0]
        missing_marker = _candidate(
            epoch=2,
            cohort="cohort-2",
            calendar_fingerprint=_digest("calendar-epoch-2"),
            tape_file_id="tape-file-epoch-2",
            source_predecessor=highwater.reference,
            source_members=(history_member,),
        )
        with pytest.raises(
            ExecutionDecisionJournalError, match="SOURCE_RESTART_MARKER_REQUIRED"
        ):
            journal.reserve_fee_pair_candidate(
                missing_marker, owner_token=token, ttl_seconds=10
            )

        restart = _candidate(
            epoch=2,
            cohort="cohort-2",
            calendar_fingerprint=_digest("calendar-epoch-2"),
            tape_file_id="tape-file-epoch-2",
            source_predecessor=highwater.reference,
            source_restart_marker=ExecutionSourceRestartMarker(
                prior_highwater=highwater.reference
            ),
            source_members=(history_member,),
        )
        reserved = journal.reserve_fee_pair_candidate(
            restart, owner_token=token, ttl_seconds=10
        )
        assert reserved.state == "RESERVED"
    finally:
        journal.close()


def test_candidate_reserve_starts_monotonic_ttl_after_write_lock(tmp_path, monkeypatch):
    path = tmp_path / "candidate-reserve-lock-deadline.sqlite3"
    journal = ExecutionDecisionJournal(path)
    blocker = ExecutionDecisionJournal(path)
    token = "owner-token-lock-reserve-" + "l" * 32
    journal.register_fee_pair_required_scope("pair-account", "pair-strategy")
    blocker._connection.execute("BEGIN IMMEDIATE")

    transaction_entered = Event()
    original_transaction = ExecutionDecisionJournal._transaction

    @contextmanager
    def mark_transaction(self):
        if self is journal:
            transaction_entered.set()
        with original_transaction(self) as cursor:
            yield cursor

    clock = [1_000_000_000]
    monotonic_samples = []

    def monotonic_ns():
        monotonic_samples.append(clock[0])
        return clock[0]

    monkeypatch.setattr(ExecutionDecisionJournal, "_transaction", mark_transaction)
    monkeypatch.setattr(journal_module.time, "monotonic_ns", monotonic_ns)
    with ThreadPoolExecutor(max_workers=1) as pool:
        try:
            future = pool.submit(
                journal.reserve_fee_pair_candidate,
                _candidate(),
                owner_token=token,
                ttl_seconds=1,
            )
            assert transaction_entered.wait(timeout=5)
            time.sleep(0.03)
            assert not future.done()
            assert monotonic_samples == []
            clock[0] = 5_000_000_000
            blocker._connection.execute("COMMIT")
            reserved = future.result(timeout=5)
            assert reserved.state == "RESERVED"
            assert reserved.expired_for_current_process is False
            assert monotonic_samples == [5_000_000_000, 5_000_000_000]
        finally:
            if blocker._connection.in_transaction:
                blocker._connection.execute("ROLLBACK")
            journal.close()
            blocker.close()


def test_candidate_claim_checks_expiry_after_waiting_for_write_lock(tmp_path, monkeypatch):
    path = tmp_path / "candidate-claim-lock-deadline.sqlite3"
    journal = ExecutionDecisionJournal(path)
    blocker = ExecutionDecisionJournal(path)
    token = "owner-token-lock-claim-" + "c" * 32
    journal.register_fee_pair_required_scope("pair-account", "pair-strategy")
    clock = [1_000_000_000]
    monkeypatch.setattr(journal_module.time, "monotonic_ns", lambda: clock[0])
    reserved = journal.reserve_fee_pair_candidate(
        _candidate(), owner_token=token, ttl_seconds=0.001
    )
    assert reserved.expired_for_current_process is False
    blocker._connection.execute("BEGIN IMMEDIATE")

    transaction_entered = Event()
    original_transaction = ExecutionDecisionJournal._transaction

    @contextmanager
    def mark_transaction(self):
        if self is journal:
            transaction_entered.set()
        with original_transaction(self) as cursor:
            yield cursor

    monkeypatch.setattr(ExecutionDecisionJournal, "_transaction", mark_transaction)
    with ThreadPoolExecutor(max_workers=1) as pool:
        try:
            future = pool.submit(
                journal.record_fee_pair_append_claim,
                reserved.candidate_id,
                owner_token=token,
            )
            assert transaction_entered.wait(timeout=5)
            time.sleep(0.03)
            assert not future.done()
            clock[0] = reserved.deadline_monotonic_ns + 1
            blocker._connection.execute("COMMIT")
            with pytest.raises(
                ExecutionDecisionJournalError, match="FEE_PAIR_CANDIDATE_EXPIRED"
            ):
                future.result(timeout=5)
            assert journal.fee_pair_candidate(reserved.candidate_id).state == "RESERVED"
        finally:
            if blocker._connection.in_transaction:
                blocker._connection.execute("ROLLBACK")
            journal.close()
            blocker.close()


def test_candidate_read_uses_one_snapshot_while_another_connection_claims(tmp_path):
    path = tmp_path / "candidate-read-snapshot.sqlite3"
    reader = ExecutionDecisionJournal(path)
    writer = ExecutionDecisionJournal(path)
    token = "owner-token-snapshot-" + "p" * 32
    reader.register_fee_pair_required_scope("pair-account", "pair-strategy")
    reserved = reader.reserve_fee_pair_candidate(
        _candidate(), owner_token=token, ttl_seconds=10
    )
    selected_events = Event()
    continue_read = Event()
    trace_seen = [False]

    def trace(statement):
        if (
            not trace_seen[0]
            and "from execution_fee_pair_candidate_events" in statement.lower()
        ):
            trace_seen[0] = True
            selected_events.set()
            continue_read.wait(timeout=5)

    reader._connection.set_trace_callback(trace)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(reader.fee_pair_candidate, reserved.candidate_id)
        try:
            assert selected_events.wait(timeout=5)
            claimed = writer.record_fee_pair_append_claim(
                reserved.candidate_id, owner_token=token
            )
            assert claimed.state == "APPEND_CLAIMED"
        finally:
            continue_read.set()
        read_record = future.result(timeout=5)

    reader._connection.set_trace_callback(None)
    try:
        assert read_record.state == "RESERVED"
        assert reader.fee_pair_candidate(reserved.candidate_id).state == "APPEND_CLAIMED"
    finally:
        writer.close()
        reader.close()


def test_same_process_reopen_does_not_adopt_or_renew_candidate_owner(tmp_path, monkeypatch):
    path = tmp_path / "candidate-owner-reopen.sqlite3"
    first = ExecutionDecisionJournal(path)
    token = "owner-token-" + "r" * 40
    try:
        first.register_fee_pair_required_scope("pair-account", "pair-strategy")
        reserved = first.reserve_fee_pair_candidate(_candidate(), owner_token=token, ttl_seconds=10)
        first.close()

        # A new SQLite connection in the same process has the same process
        # instance identity; it is not treated as restart recovery.
        reopened = ExecutionDecisionJournal(path)
        try:
            replay = reopened.reserve_fee_pair_candidate(
                _candidate(), owner_token=token, ttl_seconds=10
            )
            assert replay.candidate_id == reserved.candidate_id
            assert replay.owner_matches_current_process is True
            claimed = reopened.record_fee_pair_append_claim(replay.candidate_id, owner_token=token)
            assert claimed.state == "APPEND_CLAIMED"
        finally:
            reopened.close()

        # A different process nonce fails closed on read/claim. This synthetic
        # identity switch checks the owner binding; it does not revoke any
        # physical writer capability (this API grants none).
        monkeypatch.setattr(journal_module, "_PROCESS_INSTANCE_NONCE", "different-process")
        restarted = ExecutionDecisionJournal(path)
        try:
            owner_view = restarted.fee_pair_candidate(reserved.candidate_id)
            assert owner_view.owner_matches_current_process is False
            with pytest.raises(
                ExecutionDecisionJournalError, match="FEE_PAIR_CANDIDATE_OWNER_MISMATCH"
            ):
                restarted.record_fee_pair_append_claim(reserved.candidate_id, owner_token=token)
        finally:
            restarted.close()
    finally:
        if not first._closed:
            first.close()


def test_v15_migration_preserves_history_and_adds_empty_candidate_schema(tmp_path):
    path = tmp_path / "candidate-v15-migration.sqlite3"
    journal = ExecutionDecisionJournal(path)
    key = ExecutionDecisionKey(
        account_scope="pair-account",
        strategy_scope="pair-strategy",
        logical_run_id="v15-existing-run",
        cohort_id="v15-cohort",
        close_time="2026-10-28T10:00:00Z",
        decision_kind="bar",
    )
    decision = journal.record_decision(key, {"signal": "flat"})
    journal.register_fee_pair_required_scope("pair-account", "pair-strategy")
    before = journal.decision_capacity_snapshot()
    journal.close()

    with sqlite3.connect(path) as connection:
        _downgrade_to_v15(connection)

    migrated = ExecutionDecisionJournal(path)
    try:
        assert migrated._connection.execute("PRAGMA user_version").fetchone()[0] == 24
        assert migrated.decision(decision.decision_id) == decision
        assert migrated.fee_pair_required_scope("pair-account", "pair-strategy") is not None
        assert (
            migrated._connection.execute(
                "SELECT COUNT(*) FROM execution_fee_pair_candidates"
            ).fetchone()[0]
            == 0
        )
        after = migrated.decision_capacity_snapshot()
        assert after.base_record_count == before.base_record_count
        assert after.base_payload_bytes == before.base_payload_bytes
        assert after.settlement_record_count == before.settlement_record_count
        assert after.settlement_payload_bytes == before.settlement_payload_bytes
    finally:
        migrated.close()


def test_registered_scope_rejects_valid_source_only_receipt_without_advancing_head(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "candidate-source-only-fence.sqlite3")
    close_time = "2026-10-28T10:01:00Z"
    cohort_id = "source-only-cohort"
    batch_id = "{}:{}:{}:{}:{}".format(cohort_id, "calendar-a", 1, "calendar-v1", 0)
    member = ExecutionSourceMemberReceipt(
        member_id="SIM-A",
        source_ref="synthetic-ctp",
        source_role="live",
        connection_generation="generation-a",
        feed_sequence=1,
        bar_id="bar-a",
        bucket_start="2026-10-28T10:00:00Z",
        close_time=close_time,
        available_at="2026-10-28T10:01:01Z",
        trading_day="20261028",
        session_segment="morning",
        timezone_id="UTC",
        clock_domain_id="synthetic-clock",
        complete=True,
        quality="GOOD",
        present=True,
    )
    receipt = ExecutionSourceReceipt(
        source_kind="simnow-live",
        cohort_id=cohort_id,
        calendar_id="calendar-a",
        calendar_version="calendar-v1",
        calendar_fingerprint=_digest("source-calendar"),
        epoch_id=1,
        slot_index=0,
        slot_id="slot-0",
        close_time=close_time,
        batch_id=batch_id,
        readiness="WARMUP",
        tape_file_id="synthetic-tape-file",
        tape_record_id="synthetic-record-1",
        tape_record_index=1,
        members=(member,),
    )
    key = ExecutionDecisionKey(
        account_scope="pair-account",
        strategy_scope="pair-strategy",
        logical_run_id="source-only-run",
        cohort_id=cohort_id,
        close_time=close_time,
        decision_kind="simnow-live",
    )
    try:
        journal.register_fee_pair_required_scope("pair-account", "pair-strategy")
        candidate = journal.reserve_fee_pair_candidate(
            _candidate(), owner_token="source-only-owner-" + "s" * 40, ttl_seconds=10
        )
        with pytest.raises(ExecutionDecisionJournalError, match="FEE_PAIR_SCOPE_FAIL_CLOSED"):
            journal.record_grid_decision(
                key,
                {"signal": "synthetic-ineligible"},
                epoch_id="1",
                batch_id=batch_id,
                eligible=False,
                complete=True,
                live_ready=False,
                inputs_complete=True,
                source_receipt=receipt,
            )
        assert (
            journal._connection.execute("SELECT COUNT(*) FROM execution_decisions").fetchone()[0]
            == 0
        )
        assert (
            journal._connection.execute(
                "SELECT COUNT(*) FROM execution_source_highwaters"
            ).fetchone()[0]
            == 0
        )
        assert journal.fee_pair_candidate(candidate.candidate_id).state == "RESERVED"
    finally:
        journal.close()


def test_v17_workflow_attaches_exact_receipt_and_commits_source_only_once(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "workflow-source-only.sqlite3")
    token = "workflow-owner-" + "w" * 40
    candidate = _candidate()
    try:
        journal.register_fee_pair_required_scope("pair-account", "pair-strategy")
        reserved = journal.reserve_fee_pair_workflow_candidate(
            candidate, owner_token=token, ttl_seconds=10
        )
        assert reserved.state == "RESERVED"
        assert reserved.owner_matches_current_process
        with pytest.raises(ExecutionDecisionJournalError, match="FEE_PAIR_WORKFLOW_RECEIPT_REQUIRED"):
            journal.finalize_fee_pair_source_only_from_attached_receipt(
                reserved.candidate_id, owner_token=token
            )

        claimed = journal.record_fee_pair_workflow_append_claim(
            reserved.candidate_id, owner_token=token
        )
        assert claimed.state == "APPEND_CLAIMED"
        with pytest.raises(ExecutionDecisionJournalError, match="FEE_PAIR_WORKFLOW_ALREADY_CLAIMED"):
            journal.record_fee_pair_workflow_append_claim(
                reserved.candidate_id, owner_token=token
            )
        assert journal._connection.execute(
            "SELECT COUNT(*) FROM execution_fee_pair_workflow_events WHERE candidate_id=?",
            (reserved.candidate_id,),
        ).fetchone()[0] == 2

        # This is a synthetic receipt passed by trusted test code. The Journal
        # verifies its typed binding; it does not claim that a physical tape row exists.
        receipt = journal_module._fee_pair_receipt_from_candidate(
            candidate, "verified-synthetic-tape-record"
        )
        attached = journal.attach_verified_fee_pair_source_receipt(
            reserved.candidate_id, receipt, owner_token=token
        )
        assert attached.state == "RECEIPT_VERIFIED"
        assert attached.verified_receipt_sha256 == journal_module._source_receipt_sha256(receipt)
        assert journal.attach_verified_fee_pair_source_receipt(
            reserved.candidate_id, receipt, owner_token=token
        ) == attached

        decision = journal.finalize_fee_pair_source_only_from_attached_receipt(
            reserved.candidate_id, owner_token=token
        )
        assert decision.key == candidate.key
        assert decision.is_noop
        assert decision.economic_payload["_execution_source_anchor_only"] is True
        assert decision.economic_payload["_execution_fee_pair_workflow"] == {
            "candidate_id": reserved.candidate_id,
            "candidate_sha256": reserved.candidate_sha256,
        }
        assert journal.finalize_fee_pair_source_only_from_attached_receipt(
            reserved.candidate_id, owner_token=token
        ) == decision
        workflow = journal.fee_pair_workflow_candidate(reserved.candidate_id)
        assert workflow.state == "SOURCE_ONLY"
        assert workflow.source_only_decision_id == decision.decision_id
        assert journal.source_highwater(
            candidate.key.account_scope,
            candidate.key.strategy_scope,
            candidate.key.logical_run_id,
            candidate.source_kind,
        ).anchor_kind == "SOURCE_ONLY"
        assert tuple(
            row[0]
            for row in journal._connection.execute(
                """SELECT event_kind FROM execution_fee_pair_workflow_events
                   WHERE candidate_id=? ORDER BY event_sequence""",
                (reserved.candidate_id,),
            )
        ) == ("RESERVED", "APPEND_CLAIMED", "RECEIPT_VERIFIED", "SOURCE_ONLY")
        assert tuple(
            row
            for row in journal._connection.execute(
                """SELECT state,reserved_records,reserved_bytes
                   FROM execution_fee_pair_workflow_durable_reservations
                   WHERE candidate_id=?""",
                (reserved.candidate_id,),
            ).fetchone()
        ) == ("CONSUMED", 0, 0)
        assert tuple(
            row
            for row in journal._connection.execute(
                """SELECT state,reserved_records,reserved_bytes
                   FROM execution_fee_pair_workflow_decision_reservations
                   WHERE candidate_id=?""",
                (reserved.candidate_id,),
            ).fetchone()
        ) == ("CONSUMED", 0, 0)
    finally:
        journal.close()


def test_v18_87_member_workflow_fits_default_payload_limit_and_archives(tmp_path, monkeypatch):
    path = tmp_path / "workflow-87-member.sqlite3"
    archive_path = tmp_path / "workflow-87-member.archive.sqlite3"
    journal = ExecutionDecisionJournal(path)
    token = "workflow-87-member-owner-" + "m" * 40
    candidate = _candidate_87_members_71659_bytes()
    try:
        assert journal.max_payload_bytes == 65_536
        ordinary_key = ExecutionDecisionKey(
            account_scope="ordinary-account",
            strategy_scope="ordinary-strategy",
            logical_run_id="ordinary-payload-bound",
            cohort_id="ordinary-cohort",
            close_time=candidate.key.close_time,
            decision_kind="bar",
        )
        with pytest.raises(
            ExecutionDecisionJournalError, match="JOURNAL_PAYLOAD_TOO_LARGE"
        ):
            journal.record_decision(ordinary_key, {"text": "x" * 65_536})
        assert journal.decision_for_key(ordinary_key) is None

        journal.register_fee_pair_required_scope("pair-account", "pair-strategy")
        candidate_json = _canonical_candidate_bytes(candidate)
        assert len(candidate_json) == 71_659
        reserved = journal.reserve_fee_pair_workflow_candidate(
            candidate, owner_token=token, ttl_seconds=10
        )
        stored_candidate = journal._connection.execute(
            "SELECT candidate_payload_json FROM execution_fee_pair_workflows WHERE candidate_id=?",
            (reserved.candidate_id,),
        ).fetchone()[0]
        assert len(stored_candidate.encode("utf-8")) == 71_659

        claimed = journal.record_fee_pair_workflow_append_claim(
            reserved.candidate_id, owner_token=token
        )
        assert claimed.state == "APPEND_CLAIMED"
        receipt = journal_module._fee_pair_receipt_from_candidate(
            candidate, "synthetic-record-87"
        )
        receipt_json = journal_module._canonical_json(
            journal_module._source_receipt_values(receipt)
        )
        attached = journal.attach_verified_fee_pair_source_receipt(
            reserved.candidate_id, receipt, owner_token=token
        )
        assert attached.state == "RECEIPT_VERIFIED"
        assert len(receipt_json.encode("utf-8")) <= journal_module._MAX_SOURCE_RECEIPT_BYTES

        decision = journal.finalize_fee_pair_source_only_from_attached_receipt(
            reserved.candidate_id, owner_token=token
        )
        assert journal.fee_pair_workflow_candidate(reserved.candidate_id).state == "SOURCE_ONLY"
        assert decision.is_noop
        assert journal_module._canonical_json(
            decision.economic_payload["_execution_source_receipt"]
        ) == journal_module._canonical_json(journal_module._source_receipt_values(receipt))
        assert journal.source_highwater(
            candidate.key.account_scope,
            candidate.key.strategy_scope,
            candidate.key.logical_run_id,
            candidate.source_kind,
        ).receipt == receipt
        economics_json = journal_module._canonical_json(decision.economic_payload)
        envelope_overhead = len(economics_json.encode("utf-8")) - len(
            receipt_json.encode("utf-8")
        )
        assert 0 < envelope_overhead <= journal_module._MAX_FEE_PAIR_WORKFLOW_DECISION_OVERHEAD_BYTES
        assert len(economics_json.encode("utf-8")) <= (
            journal_module._MAX_SOURCE_RECEIPT_BYTES
            + journal_module._MAX_FEE_PAIR_WORKFLOW_DECISION_OVERHEAD_BYTES
        )

        archive_receipt = journal.archive_snapshot(archive_path)
        verified = archive_module.verify_execution_journal_archive(
            archive_path,
            expected_schema_version=24,
            expected_sha256=archive_receipt.sha256,
        )
        assert verified == archive_receipt
        assert verified.table_row_counts["execution_fee_pair_workflows"] == 1
    finally:
        journal.close()

    # A reader implementing the v17 version ceiling rejects the v20 writer's
    # larger-candidate schema before interpreting any of its rows.
    with monkeypatch.context() as patch:
        patch.setattr(ExecutionDecisionJournal, "_SCHEMA_VERSION", 17)
        with pytest.raises(
            ExecutionDecisionJournalError, match="UNSUPPORTED_SCHEMA_VERSION"
        ):
            ExecutionDecisionJournal(path)

    legacy_archive = tmp_path / "workflow-87-member-as-v17.archive.sqlite3"
    shutil.copyfile(archive_path, legacy_archive)
    with sqlite3.connect(legacy_archive) as connection:
        _downgrade_v20_workflow_to_v18(connection)
        connection.execute("PRAGMA user_version=17")
    with pytest.raises(
        archive_module.ExecutionJournalArchiveError,
        match="ARCHIVE_FEE_PAIR_CANDIDATE_TOO_LARGE",
    ):
        archive_module.verify_execution_journal_archive(
            legacy_archive, expected_schema_version=17
        )


def test_v18_rejects_candidate_above_workflow_limit_without_partial_rows(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "workflow-candidate-over-cap.sqlite3")
    token = "workflow-over-cap-owner-" + "o" * 40
    candidate = _candidate_with_members(
        run_id="workflow-over-cap",
        member_count=512,
        source_ref_length=2_041,
    )
    assert len(_canonical_candidate_bytes(candidate)) > journal_module._MAX_FEE_PAIR_WORKFLOW_CANDIDATE_BYTES
    try:
        journal.register_fee_pair_required_scope("pair-account", "pair-strategy")
        before = tuple(
            tuple(row)
            for row in journal._connection.execute(
                "SELECT capacity_class,record_count,payload_bytes "
                "FROM execution_durable_capacity_usage ORDER BY capacity_class"
            )
        )
        with pytest.raises(
            ExecutionDecisionJournalError, match="FEE_PAIR_CANDIDATE_TOO_LARGE"
        ):
            journal.reserve_fee_pair_workflow_candidate(
                candidate, owner_token=token, ttl_seconds=10
            )
        after = tuple(
            tuple(row)
            for row in journal._connection.execute(
                "SELECT capacity_class,record_count,payload_bytes "
                "FROM execution_durable_capacity_usage ORDER BY capacity_class"
            )
        )
        assert after == before
        for table in (
            "execution_fee_pair_workflows",
            "execution_fee_pair_workflow_events",
            "execution_fee_pair_workflow_durable_reservations",
            "execution_fee_pair_workflow_decision_reservations",
        ):
            assert journal._connection.execute(
                "SELECT COUNT(*) FROM {}".format(table)
            ).fetchone()[0] == 0
    finally:
        journal.close()


def test_v17_small_workflow_migrates_to_v20_and_remains_readable(tmp_path):
    path = tmp_path / "workflow-v17-to-v18.sqlite3"
    archive_path = tmp_path / "workflow-v17-small.archive.sqlite3"
    legacy_archive = tmp_path / "workflow-v17-small-legacy.archive.sqlite3"
    token = "workflow-v17-migration-owner-" + "v" * 32
    candidate = _candidate(run_id="workflow-v17-migration")
    journal = ExecutionDecisionJournal(path)
    try:
        journal.register_fee_pair_required_scope("pair-account", "pair-strategy")
        reserved = journal.reserve_fee_pair_workflow_candidate(
            candidate, owner_token=token, ttl_seconds=10
        )
        journal.record_fee_pair_workflow_append_claim(
            reserved.candidate_id, owner_token=token
        )
        receipt = journal_module._fee_pair_receipt_from_candidate(
            candidate, "synthetic-v17-record"
        )
        journal.attach_verified_fee_pair_source_receipt(
            reserved.candidate_id, receipt, owner_token=token
        )
        expected = journal.finalize_fee_pair_source_only_from_attached_receipt(
            reserved.candidate_id, owner_token=token
        )
    finally:
        journal.close()

    # Restore the actual v17/v18 workflow schema, then let the new reader
    # migrate that bounded row without rewriting its history.
    with sqlite3.connect(path) as connection:
        _downgrade_v20_workflow_to_v18(connection)
        connection.execute("PRAGMA user_version=17")

    migrated = ExecutionDecisionJournal(path)
    try:
        assert migrated._connection.execute("PRAGMA user_version").fetchone()[0] == 24
        assert migrated.fee_pair_workflow_candidate(reserved.candidate_id).state == "SOURCE_ONLY"
        assert migrated.decision(expected.decision_id) == expected
        archive_receipt = migrated.archive_snapshot(archive_path)
        assert archive_receipt.schema_version == 24
    finally:
        migrated.close()

    shutil.copyfile(archive_path, legacy_archive)
    with sqlite3.connect(legacy_archive) as connection:
        _downgrade_v20_workflow_to_v18(connection)
        connection.execute("PRAGMA user_version=17")
    verified = archive_module.verify_execution_journal_archive(
        legacy_archive, expected_schema_version=17
    )
    assert verified.schema_version == 17
    assert verified.table_row_counts["execution_fee_pair_workflows"] == 1


@pytest.mark.parametrize(
    "tampering",
    ("oversized_text", "oversized_utf8", "oversized_utf8_utf16", "non_text"),
)
def test_v17_upgrade_rejects_candidate_outside_legacy_bound_without_mutation(
    tmp_path, tampering
):
    path = tmp_path / "workflow-v17-upgrade-invalid-candidate.sqlite3"
    token = "workflow-v17-invalid-owner-" + "i" * 32
    candidate = _candidate_87_members_71659_bytes()
    if tampering == "oversized_utf8_utf16":
        with sqlite3.connect(path) as connection:
            connection.execute("PRAGMA encoding='UTF-16le'")
    journal = ExecutionDecisionJournal(path)
    try:
        journal.register_fee_pair_required_scope("pair-account", "pair-strategy")
        reserved = journal.reserve_fee_pair_workflow_candidate(
            candidate, owner_token=token, ttl_seconds=10
        )
    finally:
        journal.close()

    with sqlite3.connect(path) as connection:
        if tampering != "oversized_text":
            connection.execute("DROP TRIGGER execution_fee_pair_workflow_state")
            if tampering in ("oversized_utf8", "oversized_utf8_utf16"):
                payload = '{"padding":"' + "é" * 9_000 + '"}'
                assert len(payload) <= journal_module._MAX_FEE_PAIR_CANDIDATE_BYTES
                assert len(payload.encode("utf-8")) > journal_module._MAX_FEE_PAIR_CANDIDATE_BYTES
                connection.execute(
                    "UPDATE execution_fee_pair_workflows SET candidate_payload_json=? "
                    "WHERE candidate_id=?",
                    (payload, reserved.candidate_id),
                )
            else:
                connection.execute(
                    "UPDATE execution_fee_pair_workflows "
                    "SET candidate_payload_json=CAST(candidate_payload_json AS BLOB) "
                    "WHERE candidate_id=?",
                    (reserved.candidate_id,),
                )
            connection.execute(journal_module._FEE_PAIR_WORKFLOW_STATE_TRIGGER_SQL)
        connection.execute("PRAGMA user_version=17")

    tables = (
        "execution_fee_pair_workflows",
        "execution_fee_pair_workflow_events",
        "execution_fee_pair_workflow_durable_reservations",
        "execution_fee_pair_workflow_decision_reservations",
        "execution_durable_capacity_usage",
    )

    def snapshot():
        with sqlite3.connect(path) as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            rows = tuple(
                tuple(tuple(row) for row in connection.execute("SELECT * FROM {}".format(table)))
                for table in tables
            )
            return version, rows

    before = snapshot()
    with pytest.raises(
        ExecutionDecisionJournalError, match="FEE_PAIR_WORKFLOW_SCHEMA_CORRUPT"
    ):
        ExecutionDecisionJournal(path)
    assert snapshot() == before
    assert before[0] == 17


def test_v18_underfunded_87_member_reservation_rolls_back_atomically(tmp_path):
    candidate = _candidate_87_members_71659_bytes()
    token = "workflow-87-underfunded-owner-" + "u" * 32
    probe = ExecutionDecisionJournal(
        tmp_path / "workflow-87-capacity-probe.sqlite3",
        max_durable_base_records=16,
        max_durable_base_bytes=5_000_000,
    )
    try:
        probe.register_fee_pair_required_scope("pair-account", "pair-strategy")
        record = probe.reserve_fee_pair_workflow_candidate(
            candidate, owner_token=token, ttl_seconds=10
        )
        used = probe._connection.execute(
            "SELECT payload_bytes FROM execution_durable_capacity_usage "
            "WHERE capacity_class='BASE'"
        ).fetchone()[0]
        reserved = probe._connection.execute(
            "SELECT reserved_bytes FROM execution_fee_pair_workflow_durable_reservations "
            "WHERE candidate_id=?",
            (record.candidate_id,),
        ).fetchone()[0]
        exact_limit = used + reserved
    finally:
        probe.close()

    underfunded = ExecutionDecisionJournal(
        tmp_path / "workflow-87-capacity-underfunded.sqlite3",
        max_durable_base_records=16,
        max_durable_base_bytes=exact_limit - 1,
    )
    try:
        underfunded.register_fee_pair_required_scope("pair-account", "pair-strategy")
        with pytest.raises(
            ExecutionDecisionJournalError, match="DURABLE_BASE_BYTES_EXHAUSTED"
        ):
            underfunded.reserve_fee_pair_workflow_candidate(
                candidate, owner_token=token, ttl_seconds=10
            )
        assert tuple(
            underfunded._connection.execute(
                "SELECT record_count,payload_bytes FROM execution_durable_capacity_usage "
                "WHERE capacity_class='BASE'"
            ).fetchone()
        ) == (0, 0)
        for table in (
            "execution_fee_pair_workflows",
            "execution_fee_pair_workflow_events",
            "execution_fee_pair_workflow_durable_reservations",
            "execution_fee_pair_workflow_decision_reservations",
        ):
            assert underfunded._connection.execute(
                "SELECT COUNT(*) FROM {}".format(table)
            ).fetchone()[0] == 0
    finally:
        underfunded.close()


def test_v17_workflow_rejects_receipt_mismatch_and_keeps_reservation(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "workflow-receipt-mismatch.sqlite3")
    token = "workflow-mismatch-" + "m" * 40
    candidate = _candidate()
    try:
        journal.register_fee_pair_required_scope("pair-account", "pair-strategy")
        reserved = journal.reserve_fee_pair_workflow_candidate(
            candidate, owner_token=token, ttl_seconds=10
        )
        journal.record_fee_pair_workflow_append_claim(reserved.candidate_id, owner_token=token)
        receipt = journal_module._fee_pair_receipt_from_candidate(candidate, "record-exact")
        with pytest.raises(
            ExecutionDecisionJournalError, match="FEE_PAIR_WORKFLOW_RECEIPT_MISMATCH"
        ):
            journal.attach_verified_fee_pair_source_receipt(
                reserved.candidate_id,
                replace(receipt, tape_record_index=receipt.tape_record_index + 1),
                owner_token=token,
            )
        assert journal.fee_pair_workflow_candidate(reserved.candidate_id).state == "APPEND_CLAIMED"
        with pytest.raises(ExecutionDecisionJournalError, match="FEE_PAIR_WORKFLOW_RECEIPT_REQUIRED"):
            journal.finalize_fee_pair_source_only_from_attached_receipt(
                reserved.candidate_id, owner_token=token
            )
        assert journal._connection.execute(
            "SELECT COUNT(*) FROM execution_decisions"
        ).fetchone()[0] == 0
        reservation = journal._connection.execute(
            """SELECT state,reserved_records,reserved_bytes
               FROM execution_fee_pair_workflow_durable_reservations WHERE candidate_id=?""",
            (reserved.candidate_id,),
        ).fetchone()
        assert reservation["state"] == "ACTIVE"
        assert reservation["reserved_records"] == 11
        assert reservation["reserved_bytes"] > 0
    finally:
        journal.close()


def test_v17_late_verified_receipt_can_only_close_source_only(tmp_path, monkeypatch):
    journal = ExecutionDecisionJournal(tmp_path / "workflow-late-safety-close.sqlite3")
    token = "workflow-late-close-" + "l" * 40
    candidate = _candidate(run_id="workflow-late-close")
    clock = [1_000_000_000]
    monkeypatch.setattr(journal_module.time, "monotonic_ns", lambda: clock[0])
    try:
        journal.register_fee_pair_required_scope("pair-account", "pair-strategy")
        reserved = journal.reserve_fee_pair_workflow_candidate(
            candidate, owner_token=token, ttl_seconds=1
        )
        assert reserved.deadline_monotonic_ns == 2_000_000_000
        journal.record_fee_pair_workflow_append_claim(
            reserved.candidate_id, owner_token=token
        )

        # Deadline only gates the initial claim. A trusted late receipt may be
        # attached to close safely, but the workflow remains ineligible for OPEN.
        clock[0] = reserved.deadline_monotonic_ns + 1
        assert journal.fee_pair_workflow_candidate(
            reserved.candidate_id
        ).expired_for_current_process
        receipt = journal_module._fee_pair_receipt_from_candidate(
            candidate, "late-verified-synthetic-row"
        )
        journal.attach_verified_fee_pair_source_receipt(
            reserved.candidate_id, receipt, owner_token=token
        )
        decision = journal.finalize_fee_pair_source_only_from_attached_receipt(
            reserved.candidate_id, owner_token=token
        )

        assert decision.is_noop
        assert decision.intent_keys == ()
        assert journal.source_highwater(
            candidate.key.account_scope,
            candidate.key.strategy_scope,
            candidate.key.logical_run_id,
            candidate.source_kind,
        ).anchor_kind == "SOURCE_ONLY"
        assert journal.grid_cursor(
            candidate.key.account_scope,
            candidate.key.strategy_scope,
            candidate.key.cohort_id,
        ) is None
        assert journal._connection.execute(
            "SELECT COUNT(*) FROM execution_decisions WHERE decision_id=?",
            (decision.decision_id,),
        ).fetchone()[0] == 1
        assert journal._connection.execute(
            "SELECT COUNT(*) FROM execution_source_highwaters WHERE account_scope=? "
            "AND strategy_scope=? AND logical_run_id=? AND source_kind=?",
            (
                candidate.key.account_scope,
                candidate.key.strategy_scope,
                candidate.key.logical_run_id,
                candidate.source_kind,
            ),
        ).fetchone()[0] == 1
        assert journal._connection.execute(
            "SELECT COUNT(*) FROM execution_fee_pair_workflow_events WHERE candidate_id=?",
            (reserved.candidate_id,),
        ).fetchone()[0] == 4

        open_key = ExecutionDecisionKey(
            account_scope="pair-account",
            strategy_scope="pair-strategy",
            logical_run_id="workflow-late-close-open-attempt",
            cohort_id=candidate.key.cohort_id,
            close_time="2026-10-28T10:01:00Z",
            decision_kind="bar",
        )
        with pytest.raises(
            ExecutionDecisionJournalError, match="FEE_PAIR_SCOPE_FAIL_CLOSED"
        ):
            journal.record_decision(
                open_key,
                {"signal": "must-remain-blocked"},
                intent_keys=(
                    ExecutionIntentKey("SUBMIT", "SIM-OPEN", "BUY", "OPEN", 0),
                ),
            )
        assert journal.decision_for_key(open_key) is None
        assert journal.finalize_fee_pair_source_only_from_attached_receipt(
            reserved.candidate_id, owner_token=token
        ) == decision
        assert journal._connection.execute(
            "SELECT COUNT(*) FROM execution_fee_pair_workflow_events WHERE candidate_id=?",
            (reserved.candidate_id,),
        ).fetchone()[0] == 4
    finally:
        journal.close()


def test_v17_source_only_failure_rolls_back_decision_highwater_and_terminal_event(tmp_path):
    path = tmp_path / "workflow-source-only-rollback.sqlite3"
    token = "workflow-rollback-" + "r" * 40
    candidate = _candidate(run_id="workflow-source-only-rollback")
    journal = ExecutionDecisionJournal(path)
    journal.register_fee_pair_required_scope("pair-account", "pair-strategy")
    reserved = journal.reserve_fee_pair_workflow_candidate(
        candidate, owner_token=token, ttl_seconds=10
    )
    journal.record_fee_pair_workflow_append_claim(reserved.candidate_id, owner_token=token)
    receipt = journal_module._fee_pair_receipt_from_candidate(
        candidate, "rollback-verified-synthetic-row"
    )
    journal.attach_verified_fee_pair_source_receipt(
        reserved.candidate_id, receipt, owner_token=token
    )
    before_usage = tuple(
        tuple(row)
        for row in journal._connection.execute(
            "SELECT capacity_class,record_count,payload_bytes "
            "FROM execution_durable_capacity_usage ORDER BY capacity_class"
        )
    )
    before_reservations = tuple(
        tuple(row)
        for row in journal._connection.execute(
            "SELECT candidate_id,reserved_records,reserved_bytes,state "
            "FROM execution_fee_pair_workflow_durable_reservations"
        )
    )
    before_decision_reservation = tuple(
        journal._connection.execute(
            "SELECT reserved_records,reserved_bytes,state "
            "FROM execution_fee_pair_workflow_decision_reservations WHERE candidate_id=?",
            (reserved.candidate_id,),
        ).fetchone()
    )
    journal._connection.execute(
        """CREATE TRIGGER inject_source_only_terminal_failure
           BEFORE INSERT ON execution_fee_pair_workflow_events
           WHEN NEW.candidate_id='{}' AND NEW.event_sequence=4
           BEGIN SELECT RAISE(ABORT,'injected terminal event failure'); END""".format(
            reserved.candidate_id
        )
    )
    try:
        with pytest.raises(ExecutionDecisionJournalError, match="JOURNAL_WRITE_FAILED"):
            journal.finalize_fee_pair_source_only_from_attached_receipt(
                reserved.candidate_id, owner_token=token
            )

        assert journal._connection.execute(
            "SELECT state FROM execution_fee_pair_workflows WHERE candidate_id=?",
            (reserved.candidate_id,),
        ).fetchone()[0] == "RECEIPT_VERIFIED"
        assert journal._connection.execute(
            "SELECT COUNT(*) FROM execution_fee_pair_workflow_events WHERE candidate_id=?",
            (reserved.candidate_id,),
        ).fetchone()[0] == 3
        assert journal.decision_for_key(candidate.key) is None
        assert journal.source_highwater(
            candidate.key.account_scope,
            candidate.key.strategy_scope,
            candidate.key.logical_run_id,
            candidate.source_kind,
        ) is None
        assert tuple(
            tuple(row)
            for row in journal._connection.execute(
                "SELECT capacity_class,record_count,payload_bytes "
                "FROM execution_durable_capacity_usage ORDER BY capacity_class"
            )
        ) == before_usage
        assert tuple(
            tuple(row)
            for row in journal._connection.execute(
                "SELECT candidate_id,reserved_records,reserved_bytes,state "
                "FROM execution_fee_pair_workflow_durable_reservations"
            )
        ) == before_reservations
        assert tuple(
            journal._connection.execute(
                "SELECT reserved_records,reserved_bytes,state "
                "FROM execution_fee_pair_workflow_decision_reservations WHERE candidate_id=?",
                (reserved.candidate_id,),
            ).fetchone()
        ) == before_decision_reservation
    finally:
        journal.close()

    # Reopen after removing the injected fault. This is still the same process
    # owner; the retry only consumes the verified receipt into SOURCE_ONLY.
    raw = sqlite3.connect(path)
    try:
        raw.execute("DROP TRIGGER inject_source_only_terminal_failure")
        raw.commit()
    finally:
        raw.close()
    recovered = ExecutionDecisionJournal(path)
    try:
        decision = recovered.finalize_fee_pair_source_only_from_attached_receipt(
            reserved.candidate_id, owner_token=token
        )
        assert decision.is_noop
        assert recovered.decision_for_key(candidate.key) == decision
        assert recovered.source_highwater(
            candidate.key.account_scope,
            candidate.key.strategy_scope,
            candidate.key.logical_run_id,
            candidate.source_kind,
        ).anchor_kind == "SOURCE_ONLY"
        assert recovered._connection.execute(
            "SELECT COUNT(*) FROM execution_fee_pair_workflow_events WHERE candidate_id=?",
            (reserved.candidate_id,),
        ).fetchone()[0] == 4
        assert recovered._connection.execute(
            "SELECT COUNT(*) FROM execution_decisions WHERE decision_id=?",
            (decision.decision_id,),
        ).fetchone()[0] == 1
    finally:
        recovered.close()


def test_v16_candidate_stays_quarantined_across_v17_open_and_blocks_workflow(tmp_path):
    path = tmp_path / "workflow-preserves-v16.sqlite3"
    token = "legacy-owner-" + "l" * 40
    candidate = _candidate()
    journal = ExecutionDecisionJournal(path)
    journal.register_fee_pair_required_scope("pair-account", "pair-strategy")
    legacy = journal.reserve_fee_pair_candidate(candidate, owner_token=token, ttl_seconds=10)
    legacy_rows = tuple(
        tuple(row)
        for row in journal._connection.execute(
            """SELECT * FROM execution_fee_pair_candidates WHERE candidate_id=?""",
            (legacy.candidate_id,),
        )
    )
    legacy_events = tuple(
        tuple(row)
        for row in journal._connection.execute(
            """SELECT * FROM execution_fee_pair_candidate_events WHERE candidate_id=?
               ORDER BY event_sequence""",
            (legacy.candidate_id,),
        )
    )
    legacy_capacity = tuple(
        tuple(row)
        for row in journal._connection.execute(
            """SELECT * FROM execution_fee_pair_candidate_capacity_reservations
               WHERE candidate_id=?""",
            (legacy.candidate_id,),
        )
    )
    journal.close()

    reopened = ExecutionDecisionJournal(path)
    try:
        assert tuple(
            tuple(row)
            for row in reopened._connection.execute(
                "SELECT * FROM execution_fee_pair_candidates WHERE candidate_id=?",
                (legacy.candidate_id,),
            )
        ) == legacy_rows
        assert tuple(
            tuple(row)
            for row in reopened._connection.execute(
                """SELECT * FROM execution_fee_pair_candidate_events WHERE candidate_id=?
                   ORDER BY event_sequence""",
                (legacy.candidate_id,),
            )
        ) == legacy_events
        assert tuple(
            tuple(row)
            for row in reopened._connection.execute(
                """SELECT * FROM execution_fee_pair_candidate_capacity_reservations
                   WHERE candidate_id=?""",
                (legacy.candidate_id,),
            )
        ) == legacy_capacity
        with pytest.raises(
            ExecutionDecisionJournalError,
            match="FEE_PAIR_SCOPE_LEGACY_CANDIDATE_QUARANTINED",
        ):
            reopened.reserve_fee_pair_workflow_candidate(
                candidate, owner_token=token, ttl_seconds=10
            )
        assert reopened._connection.execute(
            "SELECT COUNT(*) FROM execution_fee_pair_workflows"
        ).fetchone()[0] == 0
    finally:
        reopened.close()


def test_v17_workflow_fence_is_bidirectional_and_capacity_is_base_only(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "workflow-fence-capacity.sqlite3")
    token = "workflow-fence-" + "f" * 40
    candidate = _candidate()
    try:
        journal.register_fee_pair_required_scope("pair-account", "pair-strategy")
        before = tuple(
            tuple(row)
            for row in journal._connection.execute(
                "SELECT capacity_class,record_count,payload_bytes "
                "FROM execution_durable_capacity_usage ORDER BY capacity_class"
            )
        )
        reserved = journal.reserve_fee_pair_workflow_candidate(
            candidate, owner_token=token, ttl_seconds=10
        )
        capacity = journal._connection.execute(
            """SELECT capacity_class,reserved_records,reserved_bytes,state
               FROM execution_fee_pair_workflow_durable_reservations WHERE candidate_id=?""",
            (reserved.candidate_id,),
        ).fetchone()
        assert tuple(capacity)[:1] == ("BASE",)
        assert capacity["reserved_records"] == 12
        assert capacity["state"] == "ACTIVE"
        after = tuple(
            tuple(row)
            for row in journal._connection.execute(
                "SELECT capacity_class,record_count,payload_bytes "
                "FROM execution_durable_capacity_usage ORDER BY capacity_class"
            )
        )
        assert after[1] == before[1]
        with pytest.raises(
            ExecutionDecisionJournalError, match="FEE_PAIR_CANDIDATE_SCOPE_ALREADY_RESERVED"
        ):
            journal.reserve_fee_pair_candidate(
                candidate, owner_token=token, ttl_seconds=10
            )
        key = candidate.key
        with pytest.raises(ExecutionDecisionJournalError, match="FEE_PAIR_SCOPE_FAIL_CLOSED"):
            journal.record_grid_decision(
                key,
                {"signal": "synthetic"},
                intent_keys=(),
                epoch_id=str(candidate.epoch_id),
                batch_id=candidate.batch_id,
                eligible=False,
                complete=True,
                live_ready=True,
                inputs_complete=True,
                source_receipt=journal_module._fee_pair_receipt_from_candidate(
                    candidate, "unattached-grid-row"
                ),
            )
        assert journal.fee_pair_workflow_candidate(reserved.candidate_id).state == "RESERVED"
    finally:
        journal.close()


def test_v17_same_scope_reservations_serialize_across_journal_connections(tmp_path):
    path = tmp_path / "workflow-scope-race.sqlite3"
    first = ExecutionDecisionJournal(path)
    second = ExecutionDecisionJournal(path)
    first.register_fee_pair_required_scope("pair-account", "pair-strategy")
    barrier = Barrier(2)
    candidates = (_candidate(run_id="reserve-racer-a"), _candidate(run_id="reserve-racer-b"))
    tokens = ("workflow-racer-a-" + "a" * 40, "workflow-racer-b-" + "b" * 40)

    def reserve(journal, candidate, token):
        barrier.wait(timeout=5)
        try:
            record = journal.reserve_fee_pair_workflow_candidate(
                candidate, owner_token=token, ttl_seconds=10
            )
        except ExecutionDecisionJournalError as error:
            return ("ERROR", error.code)
        return ("RESERVED", record.candidate_id)

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(
                pool.map(
                    lambda args: reserve(*args),
                    (
                        (first, candidates[0], tokens[0]),
                        (second, candidates[1], tokens[1]),
                    ),
                )
            )

        winners = [result for result in results if result[0] == "RESERVED"]
        losers = [result for result in results if result[0] == "ERROR"]
        assert len(winners) == len(losers) == 1
        assert losers[0][1] == "FEE_PAIR_WORKFLOW_ALREADY_RESERVED"
        assert first._connection.execute(
            "SELECT COUNT(*) FROM execution_fee_pair_workflows"
        ).fetchone()[0] == 1
        assert first._connection.execute(
            "SELECT COUNT(*) FROM execution_fee_pair_workflow_events"
        ).fetchone()[0] == 1
        assert first._connection.execute(
            "SELECT COUNT(*) FROM execution_fee_pair_workflow_durable_reservations"
        ).fetchone()[0] == 1
        assert first._connection.execute(
            "SELECT COUNT(*) FROM execution_fee_pair_workflow_decision_reservations"
        ).fetchone()[0] == 1
        winner = first.fee_pair_workflow_candidate(winners[0][1])
        assert winner is not None
        assert winner.state == "RESERVED"
        stored_scope = first._connection.execute(
            """SELECT account_scope,strategy_scope FROM execution_fee_pair_workflows
               WHERE candidate_id=?""",
            (winner.candidate_id,),
        ).fetchone()
        assert tuple(stored_scope) == ("pair-account", "pair-strategy")
    finally:
        second.close()
        first.close()


def test_v17_workflow_reservation_fails_atomically_when_base_budget_cannot_hold_terminal(
    tmp_path,
):
    journal = ExecutionDecisionJournal(
        tmp_path / "workflow-capacity-atomic.sqlite3",
        max_durable_base_records=6,
        max_durable_base_bytes=1_000_000,
        max_durable_settlement_records=20,
        max_durable_settlement_bytes=1_000_000,
    )
    try:
        journal.register_fee_pair_required_scope("pair-account", "pair-strategy")
        before_usage = tuple(
            tuple(row)
            for row in journal._connection.execute(
                "SELECT capacity_class,record_count,payload_bytes "
                "FROM execution_durable_capacity_usage ORDER BY capacity_class"
            )
        )
        with pytest.raises(ExecutionDecisionJournalError, match="DURABLE_BASE_RECORDS_EXHAUSTED"):
            journal.reserve_fee_pair_workflow_candidate(
                _candidate(), owner_token="workflow-capacity-" + "c" * 40, ttl_seconds=10
            )
        after_usage = tuple(
            tuple(row)
            for row in journal._connection.execute(
                "SELECT capacity_class,record_count,payload_bytes "
                "FROM execution_durable_capacity_usage ORDER BY capacity_class"
            )
        )
        assert after_usage == before_usage
        assert journal._connection.execute(
            "SELECT COUNT(*) FROM execution_fee_pair_workflows"
        ).fetchone()[0] == 0
        assert journal._connection.execute(
            "SELECT COUNT(*) FROM execution_fee_pair_workflow_events"
        ).fetchone()[0] == 0
        assert journal._connection.execute(
            "SELECT COUNT(*) FROM execution_fee_pair_workflow_durable_reservations"
        ).fetchone()[0] == 0
    finally:
        journal.close()


def test_v17_capacity_counts_reservation_rows_once_and_keeps_terminal_budget(tmp_path):
    token = "workflow-exact-capacity-" + "x" * 32
    candidate = _candidate(run_id="workflow-exact-capacity")

    probe = ExecutionDecisionJournal(
        tmp_path / "workflow-reservation-row-capacity-probe.sqlite3",
        max_durable_base_records=16,
        max_durable_base_bytes=5_000_000,
        max_durable_settlement_records=20,
        max_durable_settlement_bytes=1_000_000,
    )
    try:
        probe.register_fee_pair_required_scope("pair-account", "pair-strategy")
        probe_record = probe.reserve_fee_pair_workflow_candidate(
            candidate, owner_token=token, ttl_seconds=10
        )
        probe_usage = probe._connection.execute(
            """SELECT payload_bytes FROM execution_durable_capacity_usage
               WHERE capacity_class='BASE'"""
        ).fetchone()[0]
        probe_reserve = probe._connection.execute(
            """SELECT reserved_bytes FROM execution_fee_pair_workflow_durable_reservations
               WHERE candidate_id=?""",
            (probe_record.candidate_id,),
        ).fetchone()[0]
        exact_base_byte_limit = probe_usage + probe_reserve
    finally:
        probe.close()

    underfunded = ExecutionDecisionJournal(
        tmp_path / "workflow-reservation-row-capacity-underfunded.sqlite3",
        max_durable_base_records=16,
        max_durable_base_bytes=exact_base_byte_limit - 1,
        max_durable_settlement_records=20,
        max_durable_settlement_bytes=1_000_000,
    )
    try:
        underfunded.register_fee_pair_required_scope("pair-account", "pair-strategy")
        with pytest.raises(
            ExecutionDecisionJournalError, match="DURABLE_BASE_BYTES_EXHAUSTED"
        ):
            underfunded.reserve_fee_pair_workflow_candidate(
                candidate, owner_token=token, ttl_seconds=10
            )
        base_usage = underfunded._connection.execute(
            "SELECT record_count,payload_bytes FROM execution_durable_capacity_usage "
            "WHERE capacity_class='BASE'"
        ).fetchone()
        assert tuple(base_usage) == (0, 0)
        for table in (
            "execution_fee_pair_workflows",
            "execution_fee_pair_workflow_events",
            "execution_fee_pair_workflow_durable_reservations",
            "execution_fee_pair_workflow_decision_reservations",
        ):
            assert underfunded._connection.execute(
                "SELECT COUNT(*) FROM {}".format(table)
            ).fetchone()[0] == 0
    finally:
        underfunded.close()

    journal = ExecutionDecisionJournal(
        tmp_path / "workflow-reservation-row-capacity.sqlite3",
        max_durable_base_records=16,
        max_durable_base_bytes=exact_base_byte_limit,
        max_durable_settlement_records=20,
        max_durable_settlement_bytes=1_000_000,
    )

    def usage():
        return {
            row["capacity_class"]: (row["record_count"], row["payload_bytes"])
            for row in journal._connection.execute(
                "SELECT capacity_class,record_count,payload_bytes "
                "FROM execution_durable_capacity_usage"
            )
        }

    try:
        journal.register_fee_pair_required_scope("pair-account", "pair-strategy")
        baseline = usage()
        assert baseline["BASE"][0] == 0
        assert baseline["SETTLEMENT"][0] == 2
        reserved = journal.reserve_fee_pair_workflow_candidate(
            candidate, owner_token=token, ttl_seconds=10
        )
        after_reserve = usage()
        assert after_reserve["BASE"][0] - baseline["BASE"][0] == 4
        assert after_reserve["SETTLEMENT"] == baseline["SETTLEMENT"]
        future = journal._connection.execute(
            """SELECT reserved_records,state FROM
               execution_fee_pair_workflow_durable_reservations WHERE candidate_id=?""",
            (reserved.candidate_id,),
        ).fetchone()
        assert future["state"] == "ACTIVE"
        assert future["reserved_records"] == 12
        assert after_reserve["BASE"][0] + future["reserved_records"] == 16
        assert after_reserve["BASE"][1] + journal._connection.execute(
            """SELECT reserved_bytes FROM execution_fee_pair_workflow_durable_reservations
               WHERE candidate_id=?""",
            (reserved.candidate_id,),
        ).fetchone()[0] == exact_base_byte_limit

        journal.record_fee_pair_workflow_append_claim(
            reserved.candidate_id, owner_token=token
        )
        after_claim = usage()
        future_records = journal._connection.execute(
            """SELECT reserved_records FROM execution_fee_pair_workflow_durable_reservations
               WHERE candidate_id=?""",
            (reserved.candidate_id,),
        ).fetchone()[0]
        assert after_claim["BASE"][0] + future_records == 16
        future_bytes = journal._connection.execute(
            """SELECT reserved_bytes FROM execution_fee_pair_workflow_durable_reservations
               WHERE candidate_id=?""",
            (reserved.candidate_id,),
        ).fetchone()[0]
        assert after_claim["BASE"][1] + future_bytes <= exact_base_byte_limit

        receipt = journal_module._fee_pair_receipt_from_candidate(
            candidate, "\U0001f600" * 512
        )
        journal.attach_verified_fee_pair_source_receipt(
            reserved.candidate_id, receipt, owner_token=token
        )
        after_attach = usage()
        future_records = journal._connection.execute(
            """SELECT reserved_records FROM execution_fee_pair_workflow_durable_reservations
               WHERE candidate_id=?""",
            (reserved.candidate_id,),
        ).fetchone()[0]
        assert after_attach["BASE"][0] + future_records == 16
        future_bytes = journal._connection.execute(
            """SELECT reserved_bytes FROM execution_fee_pair_workflow_durable_reservations
               WHERE candidate_id=?""",
            (reserved.candidate_id,),
        ).fetchone()[0]
        assert after_attach["BASE"][1] + future_bytes <= exact_base_byte_limit
        decision = journal.finalize_fee_pair_source_only_from_attached_receipt(
            reserved.candidate_id, owner_token=token
        )

        terminal = usage()
        assert terminal["BASE"][0] == 9
        assert terminal["BASE"][1] <= exact_base_byte_limit
        assert terminal["SETTLEMENT"] == baseline["SETTLEMENT"]
        reservations = journal._connection.execute(
            """SELECT reserved_records,state FROM execution_fee_pair_workflow_durable_reservations
               WHERE candidate_id=?""",
            (reserved.candidate_id,),
        ).fetchone()
        assert tuple(reservations) == (0, "CONSUMED")
        assert journal.decision(decision.decision_id) == decision

        extra_key = ExecutionDecisionKey(
            account_scope="unregistered-account",
            strategy_scope="unregistered-strategy",
            logical_run_id="post-boundary-write",
            cohort_id="post-boundary-cohort",
            close_time="2026-10-28T10:01:00Z",
            decision_kind="bar",
        )
        extra = journal.record_decision(extra_key, {"signal": "flat"})
        assert extra.key == extra_key
        assert journal.decision_for_key(extra_key) == extra
        assert usage()["BASE"][0] == terminal["BASE"][0] + 1
    finally:
        journal.close()


def _fee_pair_settlement_fixture(
    run_id,
    *,
    target_order=("A", "B"),
    missing_template=(),
):
    """Build the real Store projection used by the typed Journal settlement."""

    from tests.unit.stores.test_factor_execution_facts import (
        _commission_row,
        _multi_target_commission_projection_case,
    )

    case = _multi_target_commission_projection_case(
        (
            _commission_row(instrument="rb2510", exchange="SHFE"),
            _commission_row(instrument="i2510", exchange="DCE"),
        ),
        execution_target_ids=("A", "B"),
        missing_template=missing_template,
    )
    facts = case.facts
    if not missing_template:
        assert facts.open_risk_ready is True, facts.open_risk_blockers
    quote_by_route = {(item.instrument, item.exchange): item for item in facts.quotes}
    route_by_id = {
        "A": ExecutionFeePairTargetRoute("A", "rb2510", "SHFE"),
        "B": ExecutionFeePairTargetRoute("B", "i2510", "DCE"),
    }
    routes = tuple(route_by_id[target_id] for target_id in target_order)
    close_time = (
        datetime.now(timezone.utc).replace(second=0, microsecond=0) - timedelta(minutes=2)
    ).isoformat(timespec="seconds").replace("+00:00", "Z")
    base = _candidate(run_id=run_id, close_time=close_time)
    source_member = base.source_members[0]
    members = (
        replace(source_member, member_id="A"),
        replace(
            source_member,
            member_id="B",
            source_ref="synthetic-ctp-b",
            feed_sequence=2,
            bar_id="bar-2",
        ),
    )
    key = replace(
        base.key,
        account_scope=facts.account_scope,
        strategy_scope=facts.strategy_scope,
        logical_run_id=run_id,
    )
    candidate = replace(
        base,
        key=key,
        source_members=members,
        target_ids=target_order,
        directions=tuple(1 if target_id == "A" else -1 for target_id in target_order),
        quote_identity_sha256s=tuple(
            journal_module._fee_pair_quote_identity_sha256(
                quote_by_route[(route.instrument, route.exchange)]
            )
            for route in routes
        ),
        account_session_id="store-session-1",
        account_session_generation="store-session-generation-1",
        target_routes=routes,
        account_fingerprint=facts.account.account_fingerprint,
        connection_generation=facts.account.connection_generation,
        trading_day=facts.account.trading_day,
    )
    assert facts.target_ids is not None and set(candidate.target_ids).issubset(facts.target_ids)
    return case, candidate, quote_by_route


def _fresh_fee_pair_facts_after_route_switch(case, candidate, target_id):
    """Switch the real Store's one-route grant, then reproject from its caches."""

    from backtrader.stores.factor_execution_facts import project_factor_execution_facts

    client = case.api.trader_client
    previous_capability = case.api._registered_sim_capability

    def disarm_execution_gate(capability, reason):
        assert capability is previous_capability
        client._gate_state.update(
            {
                "armed": False,
                "instrument": None,
                "authorized_instruments": [],
                "revocation_reason": reason,
            }
        )
        return {"revoked": True}

    client.disarm_execution_gate = disarm_execution_gate
    route = next(route for route in candidate.target_routes if route.target_id == target_id)
    expected_session = {
        "account_fingerprint": candidate.account_fingerprint,
        "connection_generation": candidate.connection_generation,
        "trading_day": candidate.trading_day,
    }
    case.store.registered_sim_ensure_arm(
        route.instrument,
        route.exchange,
        expected_session=expected_session,
    )
    return project_factor_execution_facts(
        case.store,
        case.broker,
        targets=case.targets,
        account_scope=candidate.key.account_scope,
        strategy_scope=candidate.key.strategy_scope,
        now=datetime.now(timezone.utc),
        quote_max_age=timedelta(seconds=10),
        max_query_age=timedelta(seconds=20),
        query_set=case.receipt.query_set,
        execution_target_ids=("A", "B"),
        commission_identity_by_target={
            "A": {"account_id": "configured-account", "invest_unit_id": ""},
            "B": {"account_id": "configured-account", "invest_unit_id": ""},
        },
        commission_required_for_open=True,
    )


def _fee_pair_grid_economic_payload(candidate, facts, quote_by_route, receipt):
    actions = []
    economics = []
    for leg, route in enumerate(candidate.target_routes):
        quote = quote_by_route[(route.instrument, route.exchange)]
        side = "BUY" if candidate.directions[leg] > 0 else "SELL"
        limit_price = quote.ask if side == "BUY" else quote.bid
        stop_price = limit_price - Decimal("1") if side == "BUY" else limit_price + Decimal("1")
        action = {
            "action": "SUBMIT",
            "target_id": route.target_id,
            "instrument": route.instrument,
            "exchange": route.exchange,
            "side": side,
            "position_effect": "OPEN",
            "quantity": 1,
            "limit_price": str(limit_price),
            "planned_stop_price": str(stop_price),
            "entry_grid_ordinal": 1,
        }
        actions.append(action)
        economics.append(
            {
                "instrument": route.instrument,
                "instrument_id": route.instrument,
                "exchange": route.exchange,
                "side": side,
                "position_effect": "OPEN",
                "quantity": 1,
                "limit_price": str(limit_price),
                "offset": "OPEN",
                "reason": "synthetic-ready-pair",
                "batch_id": candidate.batch_id,
                "factor_stop_price": str(stop_price),
                "stop_price": str(stop_price),
                "risk_policy_id": "synthetic-risk-policy-v1",
                "risk_policy": {"risk_policy_id": "synthetic-risk-policy-v1"},
                "entry_grid_ordinal": 1,
            }
        )
    return {
        "plan_id": "alpha003",
        "snapshot_id": facts.snapshot_id,
        "execution_evidence": ExecutionDecisionJournal._fee_pair_execution_evidence_payload(
            facts
        ),
        "batch_id": candidate.batch_id,
        "epoch_id": str(candidate.epoch_id),
        "signal_batch_id": candidate.batch_id,
        "decision_tape_status": "DURABLE",
        "decision_tape_file_id": receipt.tape_file_id,
        "decision_tape_record_id": receipt.tape_record_id,
        "decision_tape_record_index": receipt.tape_record_index,
        "decision_tape_batch_id": candidate.batch_id,
        "intent_economics": economics,
        "proposed_actions": actions,
        "dispatch_suppressed": False,
        "plan_status": "READY",
        "plan_reason": None,
    }


def _attach_fee_pair_receipt(journal, candidate, owner_token):
    reserved = journal.reserve_fee_pair_workflow_candidate(
        candidate, owner_token=owner_token, ttl_seconds=10
    )
    journal.record_fee_pair_workflow_append_claim(
        reserved.candidate_id, owner_token=owner_token
    )
    receipt = journal_module._fee_pair_receipt_from_candidate(candidate, "synthetic-record-id")
    journal.attach_verified_fee_pair_source_receipt(
        reserved.candidate_id, receipt, owner_token=owner_token
    )
    return reserved.candidate_id, receipt


def test_v18_migration_preserves_events_and_quarantines_unresolved_receipt(tmp_path):
    path = tmp_path / "workflow-v18-to-v20.sqlite3"
    case, candidate, quote_by_route = _fee_pair_settlement_fixture("typed-grid-v18-migration")
    owner_token = "typed-grid-v18-migration-owner-" + "m" * 32
    journal = ExecutionDecisionJournal(path)
    try:
        journal.register_fee_pair_required_scope("acct-scope", "alpha003")
        candidate_id, receipt = _attach_fee_pair_receipt(journal, candidate, owner_token)
        payload = _fee_pair_grid_economic_payload(candidate, case.facts, quote_by_route, receipt)
        old_events = tuple(
            tuple(row)
            for row in journal._connection.execute(
                """SELECT event_id,candidate_id,event_sequence,event_kind,event_payload_json,
                          created_at_ns FROM execution_fee_pair_workflow_events
                   WHERE candidate_id=? ORDER BY event_sequence""",
                (candidate_id,),
            )
        )
    finally:
        journal.close()

    # Reconstruct the exact committed v18 schema and data before changing the
    # version tag. Opening it exercises the production v18 -> v19 -> v20 migrations.
    with sqlite3.connect(path) as connection:
        _downgrade_v20_workflow_to_v18(connection)
        connection.execute("PRAGMA user_version=18")
        connection.commit()

    migrated = ExecutionDecisionJournal(path)
    try:
        assert migrated._connection.execute("PRAGMA user_version").fetchone()[0] == 24
        assert migrated.fee_pair_workflow_candidate(candidate_id).state == "RECEIPT_VERIFIED"
        migrated_events = tuple(
            tuple(row)
            for row in migrated._connection.execute(
                """SELECT event_id,candidate_id,event_sequence,event_kind,event_payload_json,
                          created_at_ns FROM execution_fee_pair_workflow_events
                   WHERE candidate_id=? ORDER BY event_sequence""",
                (candidate_id,),
            )
        )
        assert migrated_events == old_events
        marker = migrated._connection.execute(
            """SELECT candidate_sha256,legacy_state,migration_schema_version,reason
               FROM execution_fee_pair_legacy_unresolved_v23 WHERE candidate_id=?""",
            (candidate_id,),
        ).fetchone()
        assert tuple(marker) == (
            migrated.fee_pair_workflow_candidate(candidate_id).candidate_sha256,
            "RECEIPT_VERIFIED",
            23,
            "LEGACY_UNRESOLVED_V23_UPGRADE",
        )
        with pytest.raises(
            ExecutionDecisionJournalError,
            match="FEE_PAIR_WORKFLOW_LEGACY_UNRESOLVED_AFTER_V23",
        ):
            migrated.attach_verified_fee_pair_source_receipt(
                candidate_id, receipt, owner_token=owner_token
            )
        with pytest.raises(
            ExecutionDecisionJournalError,
            match="FEE_PAIR_WORKFLOW_LEGACY_UNRESOLVED_AFTER_V23",
        ):
            migrated.finalize_fee_pair_source_only_from_attached_receipt(
                candidate_id, owner_token=owner_token
            )
        with pytest.raises(
            ExecutionDecisionJournalError,
            match="FEE_PAIR_WORKFLOW_LEGACY_UNRESOLVED_AFTER_V23",
        ):
            migrated.settle_fee_pair_grid_decision(
                candidate_id,
                owner_token=owner_token,
                facts=case.facts,
                current_account_session_id=candidate.account_session_id,
                current_account_session_generation=candidate.account_session_generation,
                max_query_age_seconds=20.0,
                max_quote_age_seconds=10.0,
                economic_payload=payload,
                max_order_intents_per_run=100,
                expected_run_order_intents_used=0,
                remaining_exit_intent_reserve=0,
            )
        legacy_workflow = migrated.fee_pair_workflow_candidate(candidate_id)
        assert legacy_workflow.state == "RECEIPT_VERIFIED"
        assert legacy_workflow.tape_append_state is None
        assert legacy_workflow.grid_settled_decision_id is None
        assert migrated.decision_for_key(candidate.key) is None
        assert migrated._connection.execute(
            "SELECT COUNT(*) FROM execution_fee_pair_workflow_grid_settlements"
        ).fetchone()[0] == 0
        assert migrated._connection.execute(
            "SELECT COUNT(*) FROM execution_source_highwaters"
        ).fetchone()[0] == 0
    finally:
        migrated.close()


def test_v22_upgrade_quarantines_unresolved_append_claim_from_legacy_transitions(
    tmp_path,
):
    path = tmp_path / "workflow-v22-unresolved-append.sqlite3"
    case, candidate, quote_by_route = _fee_pair_settlement_fixture(
        "typed-grid-v22-unresolved-append"
    )
    owner_token = "typed-grid-v22-unresolved-owner-" + "q" * 32
    journal = ExecutionDecisionJournal(path)
    try:
        journal.register_fee_pair_required_scope("acct-scope", "alpha003")
        reserved = journal.reserve_fee_pair_workflow_candidate(
            candidate, owner_token=owner_token, ttl_seconds=10
        )
        candidate_id = reserved.candidate_id
        journal.record_fee_pair_workflow_append_claim(
            candidate_id, owner_token=owner_token
        )
        events_before_upgrade = tuple(
            tuple(row)
            for row in journal._connection.execute(
                """SELECT event_sequence,event_kind,event_payload_json
                   FROM execution_fee_pair_workflow_events WHERE candidate_id=?
                   ORDER BY event_sequence""",
                (candidate_id,),
            )
        )
    finally:
        journal.close()

    # Reopen as an exact v22 journal: only the new v23 objects are absent.
    with sqlite3.connect(path) as connection:
        _drop_v23_single_row_tape_schema(connection)
        connection.execute(
            journal_module._FEE_PAIR_WORKFLOW_DURABLE_RESERVATION_TRIGGER_SQL_V20
        )
        connection.execute("PRAGMA user_version=22")
        connection.commit()

    migrated = ExecutionDecisionJournal(path)
    try:
        workflow_before = migrated.fee_pair_workflow_candidate(candidate_id)
        assert workflow_before.state == "APPEND_CLAIMED"
        assert workflow_before.tape_append_state is None
        marker = migrated._connection.execute(
            """SELECT candidate_sha256,legacy_state,migration_schema_version,reason
               FROM execution_fee_pair_legacy_unresolved_v23 WHERE candidate_id=?""",
            (candidate_id,),
        ).fetchone()
        assert tuple(marker) == (
            workflow_before.candidate_sha256,
            "APPEND_CLAIMED",
            23,
            "LEGACY_UNRESOLVED_V23_UPGRADE",
        )
        receipt = journal_module._fee_pair_receipt_from_candidate(
            candidate, "synthetic-v22-unresolved-record"
        )
        payload = _fee_pair_grid_economic_payload(
            candidate, case.facts, quote_by_route, receipt
        )
        snapshots = {
            table: tuple(
                tuple(row)
                for row in migrated._connection.execute(
                    "SELECT * FROM {} ORDER BY 1".format(table)
                )
            )
            for table in (
                "execution_fee_pair_workflows",
                "execution_fee_pair_workflow_events",
                "execution_fee_pair_workflow_durable_reservations",
                "execution_fee_pair_workflow_decision_reservations",
                "execution_durable_capacity_usage",
                "execution_source_highwaters",
                "execution_decisions",
                "execution_fee_pair_workflow_grid_settlements",
                "execution_grid_cursors",
                "execution_grid_highwaters",
                "execution_run_order_budgets",
            )
        }
        assert tuple(
            tuple(row)
            for row in migrated._connection.execute(
                """SELECT event_sequence,event_kind,event_payload_json
                   FROM execution_fee_pair_workflow_events WHERE candidate_id=?
                   ORDER BY event_sequence""",
                (candidate_id,),
            )
        ) == events_before_upgrade

        with pytest.raises(
            ExecutionDecisionJournalError,
            match="FEE_PAIR_WORKFLOW_LEGACY_UNRESOLVED_AFTER_V23",
        ):
            migrated.attach_verified_fee_pair_source_receipt(
                candidate_id, receipt, owner_token=owner_token
            )
        with pytest.raises(
            ExecutionDecisionJournalError,
            match="FEE_PAIR_WORKFLOW_LEGACY_UNRESOLVED_AFTER_V23",
        ):
            migrated.finalize_fee_pair_source_only_from_attached_receipt(
                candidate_id, owner_token=owner_token
            )
        with pytest.raises(
            ExecutionDecisionJournalError,
            match="FEE_PAIR_WORKFLOW_LEGACY_UNRESOLVED_AFTER_V23",
        ):
            migrated.settle_fee_pair_grid_decision(
                candidate_id,
                owner_token=owner_token,
                facts=case.facts,
                current_account_session_id=candidate.account_session_id,
                current_account_session_generation=candidate.account_session_generation,
                max_query_age_seconds=20.0,
                max_quote_age_seconds=10.0,
                economic_payload=payload,
                max_order_intents_per_run=100,
                expected_run_order_intents_used=0,
                remaining_exit_intent_reserve=0,
            )

        for table, before in snapshots.items():
            after = tuple(
                tuple(row)
                for row in migrated._connection.execute(
                    "SELECT * FROM {} ORDER BY 1".format(table)
                )
            )
            assert after == before, table
        assert migrated.fee_pair_workflow_candidate(candidate_id) == workflow_before
        assert migrated._connection.execute(
            "SELECT COUNT(*) FROM execution_fee_pair_grid_single_row_tape_intents"
        ).fetchone()[0] == 0
    finally:
        migrated.close()


def test_v19_workflow_migration_preserves_legacy_append_history(tmp_path):
    path = tmp_path / "workflow-v19-to-v20.sqlite3"
    candidate = _candidate(run_id="typed-grid-v19-migration")
    owner_token = "typed-grid-v19-migration-owner-" + "n" * 32
    journal = ExecutionDecisionJournal(path)
    try:
        journal.register_fee_pair_required_scope("pair-account", "pair-strategy")
        candidate_id, _receipt = _attach_fee_pair_receipt(journal, candidate, owner_token)
        old_events = tuple(
            tuple(row)
            for row in journal._connection.execute(
                """SELECT event_id,candidate_id,event_sequence,event_kind,event_payload_json,
                          created_at_ns FROM execution_fee_pair_workflow_events
                   WHERE candidate_id=? ORDER BY event_sequence""",
                (candidate_id,),
            )
        )
        reserved_before = tuple(
            journal._connection.execute(
                """SELECT reserved_records,reserved_bytes,state
                   FROM execution_fee_pair_workflow_durable_reservations
                   WHERE candidate_id=?""",
                (candidate_id,),
            ).fetchone()
        )
        capacity_before = tuple(
            tuple(row)
            for row in journal._connection.execute(
                "SELECT capacity_class,record_count,payload_bytes "
                "FROM execution_durable_capacity_usage ORDER BY capacity_class"
            )
        )
    finally:
        journal.close()

    with sqlite3.connect(path) as connection:
        _downgrade_v20_workflow_to_v19(connection)
        connection.execute("PRAGMA user_version=19")
        connection.commit()

    migrated = ExecutionDecisionJournal(path)
    try:
        assert migrated._connection.execute("PRAGMA user_version").fetchone()[0] == 24
        assert migrated.fee_pair_workflow_candidate(candidate_id).state == "RECEIPT_VERIFIED"
        assert migrated.fee_pair_workflow_candidate(candidate_id).tape_append_state is None
        migrated_events = tuple(
            tuple(row)
            for row in migrated._connection.execute(
                """SELECT event_id,candidate_id,event_sequence,event_kind,event_payload_json,
                          created_at_ns FROM execution_fee_pair_workflow_events
                   WHERE candidate_id=? ORDER BY event_sequence""",
                (candidate_id,),
            )
        )
        assert migrated_events == old_events
        assert tuple(
            migrated._connection.execute(
                """SELECT reserved_records,reserved_bytes,state
                   FROM execution_fee_pair_workflow_durable_reservations
                   WHERE candidate_id=?""",
                (candidate_id,),
            ).fetchone()
        ) == reserved_before
        after_capacity = tuple(
            tuple(row)
            for row in migrated._connection.execute(
                "SELECT capacity_class,record_count,payload_bytes "
                "FROM execution_durable_capacity_usage ORDER BY capacity_class"
            )
        )
        quarantine_row = migrated._connection.execute(
            "SELECT * FROM execution_fee_pair_legacy_unresolved_v23 WHERE candidate_id=?",
            (candidate_id,),
        ).fetchone()
        quarantine_bytes = len(journal_module.canonical_sql_row_bytes(quarantine_row))
        before_by_class = {row[0]: row[1:] for row in capacity_before}
        after_by_class = {row[0]: row[1:] for row in after_capacity}
        assert after_by_class["BASE"] == (
            before_by_class["BASE"][0] + 1,
            before_by_class["BASE"][1] + quarantine_bytes,
        )
        assert after_by_class["SETTLEMENT"] == before_by_class["SETTLEMENT"]
        extra_columns = tuple(
            row["name"]
            for row in migrated._connection.execute(
                "PRAGMA table_info(execution_fee_pair_workflow_events)"
            ).fetchall()
        )[-3:]
        assert extra_columns == ("tape_file_id", "record_index", "tape_record_json")
    finally:
        migrated.close()


def test_v19_typed_grid_settlement_is_atomic_replayable_and_fences_both_pair_legs(
    tmp_path,
):
    case, candidate, quote_by_route = _fee_pair_settlement_fixture("typed-grid-settlement")
    owner_token = "typed-grid-settlement-owner-" + "x" * 32
    journal = ExecutionDecisionJournal(tmp_path / "typed-grid-settlement.sqlite3")
    try:
        journal.register_fee_pair_required_scope("acct-scope", "alpha003")
        candidate_id, receipt = _attach_fee_pair_receipt(journal, candidate, owner_token)
        payload = _fee_pair_grid_economic_payload(
            candidate, case.facts, quote_by_route, receipt
        )
        kwargs = {
            "owner_token": owner_token,
            "facts": case.facts,
            "current_account_session_id": candidate.account_session_id,
            "current_account_session_generation": candidate.account_session_generation,
            "max_query_age_seconds": 20.0,
            "max_quote_age_seconds": 10.0,
            "economic_payload": payload,
            "max_order_intents_per_run": 100,
            "expected_run_order_intents_used": 0,
            "remaining_exit_intent_reserve": 0,
        }

        settled = journal.settle_fee_pair_grid_decision(candidate_id, **kwargs)
        assert settled.is_new_grid is True
        assert settled.eligible is True
        assert settled.cursor.ordinal == 1
        assert settled.decision.intent_keys == (
            ExecutionIntentKey("SUBMIT", "rb2510", "BUY", "OPEN", 0),
            ExecutionIntentKey("SUBMIT", "i2510", "SELL", "OPEN", 1),
        )
        assert journal.source_highwater(
            "acct-scope", "alpha003", candidate.key.logical_run_id, candidate.source_kind
        ).anchor_kind == "GRID"
        assert journal._connection.execute(
            "SELECT COUNT(*) FROM execution_decision_slots WHERE decision_id=?",
            (settled.decision.decision_id,),
        ).fetchone()[0] == 2
        assert journal._connection.execute(
            "SELECT COUNT(*) FROM execution_fee_pair_workflow_grid_settlements WHERE candidate_id=?",
            (candidate_id,),
        ).fetchone()[0] == 1
        event = journal._connection.execute(
            """SELECT event_sequence,event_kind FROM execution_fee_pair_workflow_events
               WHERE candidate_id=? ORDER BY event_sequence DESC LIMIT 1""",
            (candidate_id,),
        ).fetchone()
        assert tuple(event) == (4, "GRID_SETTLED")
        assert journal.fee_pair_workflow_candidate(candidate_id).grid_settled_decision_id == (
            settled.decision.decision_id
        )
        reservations = journal._connection.execute(
            """SELECT reserved_records,reserved_bytes,state FROM
               execution_fee_pair_workflow_durable_reservations WHERE candidate_id=?""",
            (candidate_id,),
        ).fetchone()
        assert tuple(reservations) == (0, 0, "CONSUMED")
        decision_reservation = journal._connection.execute(
            """SELECT reserved_records,reserved_bytes,state FROM
               execution_fee_pair_workflow_decision_reservations WHERE candidate_id=?""",
            (candidate_id,),
        ).fetchone()
        assert tuple(decision_reservation) == (0, 0, "CONSUMED")

        before = tuple(
            tuple(row)
            for row in journal._connection.execute(
                """SELECT capacity_class,record_count,payload_bytes
                   FROM execution_durable_capacity_usage ORDER BY capacity_class"""
            )
        )
        replay = journal.settle_fee_pair_grid_decision(candidate_id, **kwargs)
        after = tuple(
            tuple(row)
            for row in journal._connection.execute(
                """SELECT capacity_class,record_count,payload_bytes
                   FROM execution_durable_capacity_usage ORDER BY capacity_class"""
            )
        )
        assert replay.is_new_grid is False
        assert replay.decision == settled.decision
        assert replay.cursor == settled.cursor
        assert after == before

        first_key = settled.decision.intent_keys[0]
        first_economics = payload["intent_economics"][0]
        context = ExecutionFeePairOpenContext(
            facts=case.facts,
            account_session_id=candidate.account_session_id,
            account_session_generation=candidate.account_session_generation,
            owner_token=owner_token,
            max_query_age_seconds=20.0,
            max_quote_age_seconds=10.0,
        )
        with pytest.raises(
            ExecutionDecisionJournalError,
            match="FEE_PAIR_OPEN_RISK_RESERVATION_REQUIRED",
        ):
            journal.prepare_intent(
                settled.decision.decision_id,
                first_key,
                first_economics,
            )
        with pytest.raises(
            ExecutionDecisionJournalError,
            match="FEE_PAIR_OPEN_RISK_RESERVATION_REQUIRED",
        ):
            journal.prepare_intent(
                settled.decision.decision_id,
                first_key,
                first_economics,
                fee_pair_open_context=context,
            )
        first_intent_id = journal_module._stable_id(
            "intent",
            settled.decision.decision_id
            + ":"
            + journal_module._canonical_json(journal_module._intent_key_values(first_key)),
        )
        assert journal.intent(first_intent_id) is None
        with pytest.raises(ExecutionDecisionJournalError, match="INTENT_NOT_PREPARED"):
            journal.claim_dispatch(first_intent_id, fee_pair_open_context=context)

        # Exercise the claim boundary against a previously persisted PREPARED
        # row as well. This is unreachable through current prepare_intent but
        # ensures a stale/preexisting row cannot bypass the same risk fence.
        with journal._transaction() as cursor:
            with journal_module.track_durable_row_change(
                cursor,
                "execution_decision_intents",
                (first_intent_id,),
                "BASE",
            ):
                cursor.execute(
                    """INSERT INTO execution_decision_intents
                       (intent_id,decision_id,intent_key_json,economic_payload_json,
                        original_identity_json,owner_intent_id,state,dispatch_state,
                        provider_identity_json,outcome_code,dispatch_result_json,
                        created_at_ns,updated_at_ns)
                       VALUES (?,?,?,?,?,NULL,'PREPARED',NULL,NULL,NULL,NULL,1,1)""",
                    (
                        first_intent_id,
                        settled.decision.decision_id,
                        journal_module._canonical_json(
                            journal_module._intent_key_values(first_key)
                        ),
                        journal_module._canonical_json(first_economics),
                        "{}",
                    ),
                )
        with pytest.raises(
            ExecutionDecisionJournalError,
            match="FEE_PAIR_OPEN_RISK_RESERVATION_REQUIRED",
        ):
            journal.claim_dispatch(first_intent_id, fee_pair_open_context=context)
        assert journal.intent(first_intent_id).state == "PREPARED"
        assert journal.intent(first_intent_id).dispatch_state is None
    finally:
        journal.close()


def test_v19_pair_settlement_keeps_templates_but_fences_both_active_grant_legs(
    tmp_path,
):
    # The production Store exposes one active native grant at a time. The
    # settled candidate retains both configured templates, but even a fresh
    # projection with the matching A or B grant cannot authorize either OPEN
    # until the Journal has a durable numeric pair-risk reservation.
    case, candidate, quote_by_route = _fee_pair_settlement_fixture(
        "typed-grid-one-active-route", target_order=("B", "A")
    )
    owner_token = "typed-grid-one-active-route-owner-" + "x" * 32
    journal = ExecutionDecisionJournal(tmp_path / "typed-grid-one-active-route.sqlite3")
    try:
        initial_routes = {route.target_id: route for route in case.facts.route_eligibilities}
        assert initial_routes["A"].capability_matches_route is True
        assert initial_routes["B"].capability_matches_route is False
        assert initial_routes["B"].arm_template_membership is True
        journal.register_fee_pair_required_scope("acct-scope", "alpha003")
        candidate_id, receipt = _attach_fee_pair_receipt(journal, candidate, owner_token)
        payload = _fee_pair_grid_economic_payload(
            candidate, case.facts, quote_by_route, receipt
        )
        settled = journal.settle_fee_pair_grid_decision(
            candidate_id,
            owner_token=owner_token,
            facts=case.facts,
            current_account_session_id=candidate.account_session_id,
            current_account_session_generation=candidate.account_session_generation,
            max_query_age_seconds=20.0,
            max_quote_age_seconds=10.0,
            economic_payload=payload,
            max_order_intents_per_run=100,
            expected_run_order_intents_used=0,
            remaining_exit_intent_reserve=0,
        )
        assert settled.is_new_grid is True

        for leg, target_id in enumerate(candidate.target_ids):
            fresh_facts = _fresh_fee_pair_facts_after_route_switch(
                case, candidate, target_id
            )
            fresh_routes = {
                route.target_id: route for route in fresh_facts.route_eligibilities
            }
            assert fresh_facts.open_risk_ready is True, fresh_facts.open_risk_blockers
            assert fresh_routes[target_id].capability_matches_route is True
            assert all(
                route.capability_matches_route is (route.target_id == target_id)
                for route in fresh_facts.route_eligibilities
            )
            fresh_context = ExecutionFeePairOpenContext(
                facts=fresh_facts,
                account_session_id=candidate.account_session_id,
                account_session_generation=candidate.account_session_generation,
                owner_token=owner_token,
                max_query_age_seconds=20.0,
                max_quote_age_seconds=10.0,
            )
            leg_key = settled.decision.intent_keys[leg]
            leg_economics = payload["intent_economics"][leg]
            with pytest.raises(
                ExecutionDecisionJournalError,
                match="FEE_PAIR_OPEN_RISK_RESERVATION_REQUIRED",
            ):
                journal.prepare_intent(
                    settled.decision.decision_id,
                    leg_key,
                    leg_economics,
                    fee_pair_open_context=fresh_context,
                )
            leg_intent_id = journal_module._stable_id(
                "intent",
                settled.decision.decision_id
                + ":"
                + journal_module._canonical_json(
                    journal_module._intent_key_values(leg_key)
                ),
            )
            assert journal.intent(leg_intent_id) is None
            with pytest.raises(ExecutionDecisionJournalError, match="INTENT_NOT_PREPARED"):
                journal.claim_dispatch(leg_intent_id, fee_pair_open_context=fresh_context)
        assert journal._connection.execute(
            "SELECT COUNT(*) FROM execution_decision_intents WHERE decision_id=?",
            (settled.decision.decision_id,),
        ).fetchone()[0] == 0
    finally:
        journal.close()


@pytest.mark.parametrize("dispatch_state", ("DISPATCHING", "UNKNOWN"))
def test_v19_pair_open_fence_keeps_unresolved_first_leg_non_reclaimable(
    tmp_path, dispatch_state
):
    case, candidate, quote_by_route = _fee_pair_settlement_fixture(
        "typed-grid-unresolved-{}".format(dispatch_state.lower())
    )
    owner_token = "typed-grid-unresolved-owner-" + "u" * 32
    journal = case.journal
    try:
        journal.register_fee_pair_required_scope("acct-scope", "alpha003")
        candidate_id, receipt = _attach_fee_pair_receipt(journal, candidate, owner_token)
        payload = _fee_pair_grid_economic_payload(
            candidate, case.facts, quote_by_route, receipt
        )
        settled = journal.settle_fee_pair_grid_decision(
            candidate_id,
            owner_token=owner_token,
            facts=case.facts,
            current_account_session_id=candidate.account_session_id,
            current_account_session_generation=candidate.account_session_generation,
            max_query_age_seconds=20.0,
            max_quote_age_seconds=10.0,
            economic_payload=payload,
            max_order_intents_per_run=100,
            expected_run_order_intents_used=0,
            remaining_exit_intent_reserve=0,
        )
        first_key = settled.decision.intent_keys[0]
        context = ExecutionFeePairOpenContext(
            facts=case.facts,
            account_session_id=candidate.account_session_id,
            account_session_generation=candidate.account_session_generation,
            owner_token=owner_token,
            max_query_age_seconds=20.0,
            max_quote_age_seconds=10.0,
        )
        first_intent_id = journal_module._stable_id(
            "intent",
            settled.decision.decision_id
            + ":"
            + journal_module._canonical_json(
                journal_module._intent_key_values(first_key)
            ),
        )
        # Seed a preexisting unresolved marker to prove that the new fence
        # cannot reclaim/retry a possible first dispatch. Current prepare_intent
        # does not create such a row for a pair OPEN without risk reservation.
        result_json = (
            journal_module._canonical_json(
                {"provider_identity": {}, "outcome_code": "synthetic_timeout"}
            )
            if dispatch_state == "UNKNOWN"
            else None
        )
        with journal._transaction() as cursor:
            with journal_module.track_durable_row_change(
                cursor,
                "execution_decision_intents",
                (first_intent_id,),
                "BASE",
            ):
                cursor.execute(
                    """INSERT INTO execution_decision_intents
                       (intent_id,decision_id,intent_key_json,economic_payload_json,
                        original_identity_json,owner_intent_id,state,dispatch_state,
                        provider_identity_json,outcome_code,dispatch_result_json,
                        created_at_ns,updated_at_ns)
                       VALUES (?,?,?,?,?,NULL,?,?,?,?,?,1,1)""",
                    (
                        first_intent_id,
                        settled.decision.decision_id,
                        journal_module._canonical_json(
                            journal_module._intent_key_values(first_key)
                        ),
                        journal_module._canonical_json(payload["intent_economics"][0]),
                        "{}",
                        dispatch_state,
                        "UNKNOWN" if dispatch_state == "UNKNOWN" else None,
                        "{}" if dispatch_state == "UNKNOWN" else None,
                        "synthetic_timeout" if dispatch_state == "UNKNOWN" else None,
                        result_json,
                    ),
                )
        assert journal.claim_dispatch(
            first_intent_id, fee_pair_open_context=context
        ) is None

        # Even if a fresh B grant exists, neither the settlement facts nor an
        # unresolved prior marker authorize another pair OPEN.
        second_facts = _fresh_fee_pair_facts_after_route_switch(case, candidate, "B")
        assert next(
            route
            for route in second_facts.route_eligibilities
            if route.target_id == "B"
        ).capability_matches_route is True
        second_context = replace(context, facts=second_facts)
        with pytest.raises(
            ExecutionDecisionJournalError,
            match="FEE_PAIR_OPEN_RISK_RESERVATION_REQUIRED",
        ):
            journal.prepare_intent(
                settled.decision.decision_id,
                settled.decision.intent_keys[1],
                payload["intent_economics"][1],
                fee_pair_open_context=second_context,
            )
        second_intent_id = journal_module._stable_id(
            "intent",
            settled.decision.decision_id
            + ":"
            + journal_module._canonical_json(
                journal_module._intent_key_values(settled.decision.intent_keys[1])
            ),
        )
        assert journal.intent(second_intent_id) is None
    finally:
        journal.close()


def test_v19_known_working_first_leg_does_not_admit_second_without_risk_reservation(
    tmp_path,
):
    from tests.unit.stores.test_factor_execution_facts import (
        _multi_target_facts_with_known_working_order,
    )

    case, candidate, quote_by_route = _fee_pair_settlement_fixture(
        "typed-grid-known-working"
    )
    owner_token = "typed-grid-known-working-owner-" + "w" * 32
    journal = case.journal
    try:
        # Establish a genuine Journal owner before the pair fence is installed.
        # Scope registration preserves its known working order for risk
        # cancellation, but it must not turn that exposure into permission to
        # start a new pair leg without a numerical risk reservation.
        owner_route = candidate.target_routes[0]
        prior_key = ExecutionDecisionKey(
            account_scope=candidate.key.account_scope,
            strategy_scope=candidate.key.strategy_scope,
            logical_run_id="preexisting-known-owner",
            cohort_id=candidate.key.cohort_id,
            close_time=(datetime.now(timezone.utc) - timedelta(minutes=5))
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z"),
            decision_kind="bar",
        )
        prior_decision = journal.record_decision(
            prior_key,
            {"signal": "known-working-owner"},
            intent_keys=(
                ExecutionIntentKey("SUBMIT", owner_route.instrument, "BUY", "OPEN", 0),
            ),
        )
        prior = journal.prepare_intent(
            prior_decision.decision_id,
            prior_decision.intent_keys[0],
            {"exchange": owner_route.exchange, "quantity": "1", "price": "100"},
            original_identity={"backtrader_order_ref": 94},
        )
        assert journal.claim_dispatch(prior.intent_id) is not None
        journal.record_dispatch_result(
            prior.intent_id,
            state="KNOWN",
            provider_identity={"order_ref": "94", "order_sys_id": "sys-pair-94"},
            outcome_code="accepted",
        )
        journal.register_fee_pair_required_scope("acct-scope", "alpha003")
        candidate_id, receipt = _attach_fee_pair_receipt(journal, candidate, owner_token)
        payload = _fee_pair_grid_economic_payload(
            candidate, case.facts, quote_by_route, receipt
        )
        settled = journal.settle_fee_pair_grid_decision(
            candidate_id,
            owner_token=owner_token,
            facts=case.facts,
            current_account_session_id=candidate.account_session_id,
            current_account_session_generation=candidate.account_session_generation,
            max_query_age_seconds=20.0,
            max_quote_age_seconds=10.0,
            economic_payload=payload,
            max_order_intents_per_run=100,
            expected_run_order_intents_used=0,
            remaining_exit_intent_reserve=0,
        )
        second_facts = _multi_target_facts_with_known_working_order(
            case, owner_intent_id=prior.intent_id, target_id=owner_route.target_id
        )
        assert len(second_facts.working_orders) == 1
        working = second_facts.working_orders[0]
        assert working.owner_intent_id == prior.intent_id
        assert working.state == "ACCEPTED"
        assert working.execution_unknown is False
        assert second_facts.open_risk_ready is False
        assert "open_order_risk_capacity_unobserved" in second_facts.open_risk_blockers
        second_key = settled.decision.intent_keys[1]
        second_context = ExecutionFeePairOpenContext(
            facts=second_facts,
            account_session_id=candidate.account_session_id,
            account_session_generation=candidate.account_session_generation,
            owner_token=owner_token,
            max_query_age_seconds=20.0,
            max_quote_age_seconds=10.0,
        )
        with pytest.raises(
            ExecutionDecisionJournalError,
            match="FEE_PAIR_OPEN_RISK_RESERVATION_REQUIRED",
        ):
            journal.prepare_intent(
                settled.decision.decision_id,
                second_key,
                payload["intent_economics"][1],
                fee_pair_open_context=second_context,
            )
        second_intent_id = journal_module._stable_id(
            "intent",
            settled.decision.decision_id
            + ":"
            + journal_module._canonical_json(journal_module._intent_key_values(second_key)),
        )
        assert journal.intent(second_intent_id) is None

        # The workflow fence does not suppress independent risk reduction or
        # cancellation of the already-known first leg.
        risk_close_key = ExecutionDecisionKey(
            account_scope=candidate.key.account_scope,
            strategy_scope=candidate.key.strategy_scope,
            logical_run_id="risk-close-known-working",
            cohort_id=candidate.key.cohort_id,
            close_time=(datetime.now(timezone.utc) + timedelta(seconds=1))
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z"),
            decision_kind="risk",
        )
        close_key = ExecutionIntentKey(
            "SUBMIT", candidate.target_routes[1].instrument, "BUY", "CLOSE", 0
        )
        close_decision = journal.record_risk_decision(
            risk_close_key,
            {"signal": "close-known-working"},
            intent_keys=(close_key,),
            max_order_intents_per_run=10,
            expected_run_order_intents_used=0,
            remaining_exit_intent_reserve=0,
        )
        close = journal.prepare_intent(
            close_decision.decision.decision_id,
            close_key,
            {
                "exchange": candidate.target_routes[1].exchange,
                "quantity": "1",
                "price": "100",
            },
        )
        assert journal.claim_dispatch(close.intent_id) is not None

        cancel_key = ExecutionIntentKey(
            "CANCEL", candidate.target_routes[0].instrument, "BUY", "OPEN", 0
        )
        cancel_decision = journal.record_risk_decision(
            replace(risk_close_key, logical_run_id="risk-cancel-known-working"),
            {"signal": "cancel-known-working"},
            intent_keys=(cancel_key,),
            max_order_intents_per_run=10,
            expected_run_order_intents_used=0,
            remaining_exit_intent_reserve=0,
        )
        cancel = journal.prepare_intent(
            cancel_decision.decision.decision_id,
            cancel_key,
            {"order_ref": "94"},
            owner_intent_id=prior.intent_id,
        )
        assert journal.claim_dispatch(cancel.intent_id) is not None
    finally:
        journal.close()


@pytest.mark.parametrize("scenario", ("missing_template", "session_mismatch"))
def test_v19_settlement_fails_closed_for_missing_template_or_session_mismatch(
    tmp_path, scenario
):
    missing_template = (
        (("B", "i2510", "DCE"),) if scenario == "missing_template" else ()
    )
    case, candidate, quote_by_route = _fee_pair_settlement_fixture(
        "typed-grid-{}".format(scenario), missing_template=missing_template
    )
    owner_token = "typed-grid-{}-owner-{}".format(scenario, "x" * 32)
    journal = ExecutionDecisionJournal(tmp_path / "typed-grid-{}.sqlite3".format(scenario))
    try:
        if scenario == "missing_template":
            route = next(
                item for item in case.facts.route_eligibilities if item.target_id == "B"
            )
            assert route.arm_template_membership is False
        journal.register_fee_pair_required_scope("acct-scope", "alpha003")
        candidate_id, receipt = _attach_fee_pair_receipt(journal, candidate, owner_token)
        payload = _fee_pair_grid_economic_payload(
            candidate, case.facts, quote_by_route, receipt
        )
        session_generation = (
            "stale-session-generation"
            if scenario == "session_mismatch"
            else candidate.account_session_generation
        )
        with pytest.raises(
            ExecutionDecisionJournalError, match="FEE_PAIR_FACTS_SESSION_MISMATCH"
        ):
            journal.settle_fee_pair_grid_decision(
                candidate_id,
                owner_token=owner_token,
                facts=case.facts,
                current_account_session_id=candidate.account_session_id,
                current_account_session_generation=session_generation,
                max_query_age_seconds=20.0,
                max_quote_age_seconds=10.0,
                economic_payload=payload,
                max_order_intents_per_run=100,
                expected_run_order_intents_used=0,
                remaining_exit_intent_reserve=0,
            )
        workflow = journal.fee_pair_workflow_candidate(candidate_id)
        assert workflow.state == "RECEIPT_VERIFIED"
        assert workflow.grid_settled_decision_id is None
        assert journal.decision_for_key(candidate.key) is None
    finally:
        journal.close()


def test_v19_typed_grid_settlement_failure_rolls_back_every_grid_artifact(tmp_path):
    case, candidate, quote_by_route = _fee_pair_settlement_fixture("typed-grid-rollback")
    owner_token = "typed-grid-rollback-owner-" + "x" * 32
    journal = ExecutionDecisionJournal(tmp_path / "typed-grid-rollback.sqlite3")
    try:
        journal.register_fee_pair_required_scope("acct-scope", "alpha003")
        candidate_id, receipt = _attach_fee_pair_receipt(journal, candidate, owner_token)
        payload = _fee_pair_grid_economic_payload(
            candidate, case.facts, quote_by_route, receipt
        )
        journal._connection.execute(
            """CREATE TRIGGER fail_fee_pair_grid_terminal_event
               BEFORE INSERT ON execution_fee_pair_workflow_events
               WHEN NEW.candidate_id='{}' AND NEW.event_kind='GRID_SETTLED'
               BEGIN SELECT RAISE(ABORT,'injected settlement event failure'); END""".format(
                candidate_id
            )
        )
        with pytest.raises(ExecutionDecisionJournalError, match="JOURNAL_WRITE_FAILED"):
            journal.settle_fee_pair_grid_decision(
                candidate_id,
                owner_token=owner_token,
                facts=case.facts,
                current_account_session_id=candidate.account_session_id,
                current_account_session_generation=candidate.account_session_generation,
                max_query_age_seconds=20.0,
                max_quote_age_seconds=10.0,
                economic_payload=payload,
                max_order_intents_per_run=100,
                expected_run_order_intents_used=0,
                remaining_exit_intent_reserve=0,
            )
        assert journal._connection.execute(
            "SELECT COUNT(*) FROM execution_decisions WHERE business_key_json=?",
            (
                journal_module._canonical_json(
                    journal_module._decision_key_values(candidate.key)
                ),
            ),
        ).fetchone()[0] == 0
        for table in (
            "execution_decision_slots",
            "execution_fee_pair_workflow_grid_settlements",
            "execution_grid_cursors",
            "execution_grid_highwaters",
            "factor_position_grid_history",
            "execution_run_order_budgets",
        ):
            assert journal._connection.execute(
                "SELECT COUNT(*) FROM {}".format(table)
            ).fetchone()[0] == 0
        assert journal._connection.execute(
            "SELECT COUNT(*) FROM execution_source_highwaters"
        ).fetchone()[0] == 0
        assert journal._connection.execute(
            """SELECT grid_decision_id FROM execution_fee_pair_workflows
               WHERE candidate_id=?""",
            (candidate_id,),
        ).fetchone()[0] is None
        assert tuple(
            journal._connection.execute(
                """SELECT reserved_records,state FROM
                   execution_fee_pair_workflow_durable_reservations WHERE candidate_id=?""",
                (candidate_id,),
            ).fetchone()
        ) == (10, "ACTIVE")
        assert tuple(
            journal._connection.execute(
                """SELECT event_sequence,event_kind FROM execution_fee_pair_workflow_events
                   WHERE candidate_id=? ORDER BY event_sequence DESC LIMIT 1""",
                (candidate_id,),
            ).fetchone()
        ) == (3, "RECEIPT_VERIFIED")
    finally:
        journal.close()
