"""Complete, read-only, no-rotation journal archive contracts."""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from threading import Event

import pytest

from backtrader.stores import execution_journal_archive as archive_module
from backtrader.stores.execution_decision_journal import (
    ExecutionDecisionJournal,
    ExecutionDecisionJournalError,
    ExecutionDecisionKey,
    ExecutionIntentKey,
)


def _decision_key(run_id: str, *, close_time: str) -> ExecutionDecisionKey:
    return ExecutionDecisionKey(
        account_scope="synthetic-account",
        strategy_scope="synthetic-strategy",
        logical_run_id=run_id,
        cohort_id="synthetic-cohort",
        close_time=close_time,
        decision_kind="bar",
    )


def _intent_key(instrument: str) -> ExecutionIntentKey:
    return ExecutionIntentKey(
        action="SUBMIT",
        instrument=instrument,
        side="BUY",
        position_effect="OPEN",
        leg=0,
    )


def _record_order(journal, *, run_id: str, close_time: str, instrument: str, order_ref: str):
    key = _intent_key(instrument)
    decision = journal.record_decision(
        _decision_key(run_id, close_time=close_time),
        {"signal": "synthetic-open", "quantity": "1", "price": "100"},
        intent_keys=(key,),
    )
    intent = journal.prepare_intent(
        decision.decision_id,
        key,
        {"quantity": "1", "price": "100", "order_type": "LIMIT"},
        original_identity={
            "backtrader_order_ref": int(order_ref),
            "trading_day": "20261024",
            "instrument_id": instrument,
            "exchange_id": "CFFEX",
            "order_ref": order_ref,
            "operation": "insert",
        },
    )
    return decision, intent


def _readonly_connection(path):
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    connection.execute("PRAGMA query_only = ON")
    return connection


def test_archive_snapshot_verifies_terminal_chain_and_preserves_unknown(tmp_path):
    source_path = tmp_path / "active.sqlite3"
    archive_path = tmp_path / "session-20261024.sqlite3"
    journal = ExecutionDecisionJournal(
        source_path,
        max_pending_intents=4,
        max_pending_callbacks=4,
        max_decision_records=2,
        settlement_decision_reserve_records=2,
        max_decision_bytes=65536,
        settlement_decision_reserve_bytes=65536,
    )
    try:
        terminal_decision, terminal_intent = _record_order(
            journal,
            run_id="synthetic-terminal-run",
            close_time="2026-10-24T10:00:00Z",
            instrument="SIM-IF-1",
            order_ref="101",
        )
        assert journal.claim_dispatch(terminal_intent.intent_id) is not None
        journal.record_dispatch_result(
            terminal_intent.intent_id,
            state="KNOWN",
            provider_identity={"order_id": "synthetic-provider-order-101"},
            outcome_code="accepted",
        )
        callback = journal.record_callback(
            terminal_intent.intent_id,
            "synthetic-fill-101",
            {"event_id": "synthetic-fill-101", "state": "FILLED", "filled_quantity": "1"},
        )
        journal.acknowledge_callback(callback.receipt_id)
        reconciliation = journal.record_reconciliation(
            terminal_intent.intent_id,
            reconciliation_id="synthetic-reconciliation-101",
            query_id="synthetic-query-101",
            state="KNOWN",
            provider_identity={"order_id": "synthetic-provider-order-101"},
            outcome_code="filled",
            terminal_state="FILLED",
            terminal_event_id="synthetic-event-101",
            position_snapshot_id="synthetic-position-101",
            position_flat=True,
        )
        resolution = journal.release_instrument_owner(
            terminal_intent.intent_id,
            reconciliation_id=reconciliation.reconciliation_id,
        )
        assert resolution.terminal_state == "FILLED"
        assert journal.active_instrument_owner("synthetic-account", "SIM-IF-1") is None

        unknown_decision, unknown_intent = _record_order(
            journal,
            run_id="synthetic-unknown-run",
            close_time="2026-10-24T10:01:00Z",
            instrument="SIM-IF-2",
            order_ref="202",
        )
        assert journal.claim_dispatch(unknown_intent.intent_id) is not None
        journal.record_dispatch_result(
            unknown_intent.intent_id,
            state="UNKNOWN",
            outcome_code="synthetic-response-lost-after-send",
        )
        registration = journal.register_fee_pair_required_scope(
            "archive-only-account", "archive-only-strategy"
        )
        before = journal.decision_capacity_snapshot()

        receipt = journal.archive_snapshot(archive_path)
        independently_verified = archive_module.verify_execution_journal_archive(
            archive_path,
            expected_schema_version=ExecutionDecisionJournal._SCHEMA_VERSION,
            expected_sha256=receipt.sha256,
        )
        assert independently_verified == receipt
        assert receipt.schema_version == 15
        assert receipt.size_bytes == archive_path.stat().st_size
        assert receipt.table_row_counts["execution_decisions"] == 2
        assert receipt.table_row_counts["execution_decision_intents"] == 2
        assert receipt.table_row_counts["execution_intent_resolutions"] == 1
        assert receipt.table_row_counts["execution_fee_pair_required_scopes"] == 1
        assert receipt.table_row_counts["execution_fee_pair_scope_events"] == 1

        with closing(_readonly_connection(archive_path)) as archived:
            terminal_row = archived.execute(
                """SELECT d.decision_id,i.intent_id,n.order_ref,c.callback_id,c.acknowledged,
                          r.terminal_state,r.terminal_event_id,z.terminal_state,z.reconciliation_id
                   FROM execution_decisions AS d
                   JOIN execution_decision_slots AS s ON s.decision_id=d.decision_id
                   JOIN execution_decision_intents AS i ON i.intent_id=s.intent_id
                   JOIN execution_native_intent_identities AS n ON n.intent_id=i.intent_id
                   JOIN execution_decision_callbacks AS c ON c.intent_id=i.intent_id
                   JOIN execution_intent_reconciliations AS r ON r.intent_id=i.intent_id
                   JOIN execution_intent_resolutions AS z ON z.intent_id=i.intent_id
                   WHERE i.intent_id=?""",
                (terminal_intent.intent_id,),
            ).fetchone()
            assert terminal_row == (
                terminal_decision.decision_id,
                terminal_intent.intent_id,
                "101",
                "synthetic-fill-101",
                1,
                "FILLED",
                "synthetic-event-101",
                "FILLED",
                "synthetic-reconciliation-101",
            )
            unknown_row = archived.execute(
                """SELECT i.state,i.dispatch_state,n.order_ref,o.owner_intent_id
                   FROM execution_decision_intents AS i
                   JOIN execution_native_intent_identities AS n ON n.intent_id=i.intent_id
                   JOIN execution_instrument_owners AS o ON o.instrument=n.instrument
                   WHERE i.intent_id=?""",
                (unknown_intent.intent_id,),
            ).fetchone()
            assert unknown_row == (
                "UNKNOWN",
                "UNKNOWN",
                "202",
                unknown_intent.intent_id,
            )
            archived_registration = archived.execute(
                """SELECT account_scope,strategy_scope,policy_id,state,registered_at_ns
                   FROM execution_fee_pair_required_scopes"""
            ).fetchone()
            assert archived_registration == (
                registration.account_scope,
                registration.strategy_scope,
                registration.policy_id,
                registration.state,
                registration.registered_at_ns,
            )
            archived_event = archived.execute(
                """SELECT event_id,event_kind,event_payload_json,created_at_ns
                   FROM execution_fee_pair_scope_events"""
            ).fetchone()
            assert len(archived_event[0]) == 64
            assert all(character in "0123456789abcdef" for character in archived_event[0])
            assert archived_event[1:] == (
                "REQUIRE_PAIR_REGISTERED",
                '{"policy_id":"REQUIRE_PAIR_FEE_V1","state":"REQUIRE_PAIR_FAIL_CLOSED"}',
                registration.registered_at_ns,
            )
            with pytest.raises(sqlite3.OperationalError):
                archived.execute("DELETE FROM execution_decision_intents")

        assert journal.intent(unknown_intent.intent_id).state == "UNKNOWN"
        owner = journal.active_instrument_owner("synthetic-account", "SIM-IF-2")
        assert owner is not None and owner.intent_id == unknown_intent.intent_id
        after = journal.decision_capacity_snapshot()
        assert after.base_record_count == before.base_record_count == 2
        assert after.base_payload_bytes == before.base_payload_bytes
        assert journal.decision(terminal_decision.decision_id) is not None
        assert journal.decision(unknown_decision.decision_id) is not None
        with pytest.raises(ExecutionDecisionJournalError, match="DECISION_CAPACITY_HIGH_WATER"):
            journal.record_decision(
                _decision_key(
                    "synthetic-after-archive",
                    close_time="2026-10-24T10:02:00Z",
                ),
                {"signal": "flat"},
            )
    finally:
        journal.close()


def test_archive_verifier_keeps_v14_snapshots_compatible(tmp_path):
    source_path = tmp_path / "v15-source.sqlite3"
    archive_path = tmp_path / "v14-snapshot.sqlite3"
    journal = ExecutionDecisionJournal(source_path)
    try:
        journal.record_decision(
            _decision_key("archive-v14", close_time="2026-10-24T10:00:00Z"),
            {"signal": "synthetic-flat"},
        )
        journal.archive_snapshot(archive_path)
    finally:
        journal.close()

    # Older immutable snapshots predate the v15 pair-scope tables and remain
    # verifiable after the active archive contract advances to v15.
    with sqlite3.connect(archive_path) as archived:
        archived.execute("DROP TABLE execution_fee_pair_scope_events")
        archived.execute("DROP TABLE execution_fee_pair_required_scopes")
        archived.execute("PRAGMA user_version=14")

    verified = archive_module.verify_execution_journal_archive(
        archive_path, expected_schema_version=14
    )
    assert verified.schema_version == 14
    assert verified.table_row_counts["execution_decisions"] == 1


@pytest.mark.parametrize(
    "statement",
    (
        "DROP TABLE execution_source_highwaters",
        "DROP TRIGGER execution_fee_pair_scope_no_update",
        "DROP TRIGGER execution_fee_pair_scope_no_delete",
        "DROP TRIGGER execution_fee_pair_scope_event_no_update",
        "DROP TRIGGER execution_fee_pair_scope_event_no_delete",
        "DROP TRIGGER execution_fee_pair_scope_no_update; "
        "CREATE TRIGGER execution_fee_pair_scope_no_update "
        "BEFORE UPDATE ON execution_fee_pair_required_scopes "
        "BEGIN SELECT 1; END",
        "ALTER TABLE execution_fee_pair_required_scopes DROP COLUMN registered_at_ns",
        "CREATE TRIGGER execution_fee_pair_scope_unexpected_guard "
        "BEFORE INSERT ON execution_fee_pair_required_scopes "
        "BEGIN SELECT 1; END",
        "PRAGMA writable_schema=ON; "
        "UPDATE sqlite_master SET sql=replace(sql, "
        "'CHECK(policy_id=''REQUIRE_PAIR_FEE_V1'')', "
        "'CHECK(policy_id<>''REQUIRE_PAIR_FEE_V1'')') "
        "WHERE type='table' AND name='execution_fee_pair_required_scopes'; "
        "PRAGMA writable_schema=OFF;",
    ),
)
def test_v15_archive_rejects_missing_or_changed_cumulative_schema_object(
    tmp_path, statement
):
    source_path = tmp_path / "v15-source.sqlite3"
    archive_path = tmp_path / "damaged-v15.sqlite3"
    journal = ExecutionDecisionJournal(source_path)
    try:
        journal.record_decision(
            _decision_key(
                "archive-v15-required-object", close_time="2026-10-20T10:00:00Z"
            ),
            {"signal": "flat"},
        )
        journal.archive_snapshot(archive_path)
    finally:
        journal.close()

    with sqlite3.connect(archive_path) as archived:
        archived.executescript(statement)

    with pytest.raises(
        archive_module.ExecutionJournalArchiveError,
        match="ARCHIVE_SCHEMA_INCOMPLETE",
    ):
        archive_module.verify_execution_journal_archive(
            archive_path, expected_schema_version=15
        )


def test_v14_archive_still_requires_v14_source_highwater(tmp_path):
    source_path = tmp_path / "v15-source-for-v14.sqlite3"
    archive_path = tmp_path / "incomplete-v14.sqlite3"
    journal = ExecutionDecisionJournal(source_path)
    try:
        journal.archive_snapshot(archive_path)
    finally:
        journal.close()

    with sqlite3.connect(archive_path) as archived:
        archived.execute("DROP TABLE execution_fee_pair_scope_events")
        archived.execute("DROP TABLE execution_fee_pair_required_scopes")
        archived.execute("DROP TABLE execution_source_highwaters")
        archived.execute("PRAGMA user_version=14")

    with pytest.raises(
        archive_module.ExecutionJournalArchiveError,
        match="ARCHIVE_SCHEMA_INCOMPLETE",
    ):
        archive_module.verify_execution_journal_archive(
            archive_path, expected_schema_version=14
        )


def test_archive_snapshot_is_exclusive_and_hash_verification_detects_change(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "source.sqlite3")
    archive_path = tmp_path / "archive.sqlite3"
    try:
        receipt = journal.archive_snapshot(archive_path)
        with pytest.raises(ExecutionDecisionJournalError, match="ARCHIVE_DESTINATION_EXISTS"):
            journal.archive_snapshot(archive_path)
        assert (
            archive_module.verify_execution_journal_archive(
                archive_path,
                expected_schema_version=ExecutionDecisionJournal._SCHEMA_VERSION,
                expected_sha256=receipt.sha256,
            )
            == receipt
        )
        with archive_path.open("ab") as stream:
            stream.write(b"synthetic-corruption")
        with pytest.raises(
            archive_module.ExecutionJournalArchiveError, match="ARCHIVE_HASH_MISMATCH"
        ):
            archive_module.verify_execution_journal_archive(
                archive_path,
                expected_schema_version=ExecutionDecisionJournal._SCHEMA_VERSION,
                expected_sha256=receipt.sha256,
            )
    finally:
        journal.close()


@pytest.mark.parametrize("replacement_size", ("same", "different"))
def test_archive_publish_race_preserves_replacement_file(tmp_path, monkeypatch, replacement_size):
    journal = ExecutionDecisionJournal(tmp_path / "source.sqlite3")
    archive_path = tmp_path / "raced.sqlite3"
    replacement_path = tmp_path / "replacement.tmp"
    real_link = archive_module.os.link
    replacement = None

    def replace_after_link(source, destination):
        nonlocal replacement
        real_link(source, destination)
        source_size = archive_module.Path(source).stat().st_size
        size = source_size if replacement_size == "same" else source_size + 1
        replacement = b"r" * size
        replacement_path.write_bytes(replacement)
        archive_module.os.replace(replacement_path, destination)

    monkeypatch.setattr(archive_module.os, "link", replace_after_link)
    try:
        with pytest.raises(
            ExecutionDecisionJournalError, match="ARCHIVE_PUBLISHED_IDENTITY_MISMATCH"
        ):
            journal.archive_snapshot(archive_path)
        assert replacement is not None
        assert archive_path.read_bytes() == replacement
        assert archive_path.exists()
    finally:
        journal.close()


def test_archive_verification_failure_does_not_publish_partial_database(tmp_path, monkeypatch):
    journal = ExecutionDecisionJournal(tmp_path / "source.sqlite3")
    archive_path = tmp_path / "must-not-publish.sqlite3"

    def reject_verification(*args, **kwargs):
        del args, kwargs
        raise archive_module.ExecutionJournalArchiveError("ARCHIVE_TEST_VERIFY_REJECTED")

    monkeypatch.setattr(archive_module, "verify_execution_journal_archive", reject_verification)
    try:
        with pytest.raises(ExecutionDecisionJournalError, match="ARCHIVE_TEST_VERIFY_REJECTED"):
            journal.archive_snapshot(archive_path)
        assert not archive_path.exists()
        assert tuple(tmp_path.glob(".execution-journal-archive-*.partial")) == ()
    finally:
        journal.close()


def test_archive_lock_wait_is_bounded_and_leaves_no_destination(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "source.sqlite3")
    archive_path = tmp_path / "lock-timeout.sqlite3"
    lock_held = Event()
    release_lock = Event()

    def hold_journal_lock():
        journal._lock.acquire()
        lock_held.set()
        try:
            release_lock.wait(2.0)
        finally:
            journal._lock.release()

    with ThreadPoolExecutor(max_workers=1) as executor:
        holder = executor.submit(hold_journal_lock)
        assert lock_held.wait(1.0)
        try:
            with pytest.raises(ExecutionDecisionJournalError, match="ARCHIVE_LOCK_TIMEOUT"):
                journal.archive_snapshot(archive_path, timeout_seconds=0.01)
        finally:
            release_lock.set()
        holder.result(timeout=2.0)
    assert not archive_path.exists()
    journal.close()
