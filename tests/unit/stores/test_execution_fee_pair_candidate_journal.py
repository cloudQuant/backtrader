"""Focused contracts for v16 candidates and v17 journal-only workflows."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
import hashlib
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier, Event

import pytest

import backtrader.stores.execution_decision_journal as journal_module
from backtrader.stores.execution_decision_journal import (
    ExecutionDecisionJournal,
    ExecutionDecisionJournalError,
    ExecutionDecisionKey,
    ExecutionFeePairCandidate,
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


def _downgrade_to_v15(connection: sqlite3.Connection) -> None:
    connection.execute("DROP TABLE execution_fee_pair_workflow_decision_reservations")
    connection.execute("DROP TABLE execution_fee_pair_workflow_durable_reservations")
    connection.execute("DROP TABLE execution_fee_pair_workflow_events")
    connection.execute("DROP TABLE execution_fee_pair_workflows")
    connection.execute("DROP TABLE execution_fee_pair_candidate_capacity_reservations")
    connection.execute("DROP TABLE execution_fee_pair_candidate_events")
    connection.execute("DROP TABLE execution_fee_pair_candidates")
    connection.execute("PRAGMA user_version=15")


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
        assert migrated._connection.execute("PRAGMA user_version").fetchone()[0] == 17
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
        assert reservation["reserved_records"] == 4
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
        assert capacity["reserved_records"] == 5
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
        max_durable_base_records=9,
        max_durable_base_bytes=1_000_000,
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
        max_durable_base_records=9,
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
        max_durable_base_records=9,
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
        assert future["reserved_records"] == 5
        assert after_reserve["BASE"][0] + future["reserved_records"] == 9
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
        assert after_claim["BASE"][0] + future_records == 9
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
        assert after_attach["BASE"][0] + future_records == 9
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
        with pytest.raises(
            ExecutionDecisionJournalError, match="DURABLE_BASE_RECORDS_EXHAUSTED"
        ):
            journal.record_decision(extra_key, {"signal": "flat"})
        assert journal.decision_for_key(extra_key) is None
        assert usage() == terminal
    finally:
        journal.close()
