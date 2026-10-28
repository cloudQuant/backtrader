"""Complete, read-only, no-rotation journal archive contracts."""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from threading import Event

import pytest

from backtrader.stores import execution_journal_archive as archive_module
from backtrader.stores import execution_decision_journal as journal_module
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


def _downgrade_archive_to_v16(connection: sqlite3.Connection) -> None:
    """Remove only v17 objects before modeling a genuine v16 archive."""

    _downgrade_archive_to_v18(connection)
    for trigger in (
        "execution_fee_pair_workflow_state",
        "execution_fee_pair_workflow_no_delete",
        "execution_fee_pair_workflow_event_no_update",
        "execution_fee_pair_workflow_event_no_delete",
        "execution_fee_pair_workflow_durable_reservation_state",
        "execution_fee_pair_workflow_decision_reservation_state",
        "execution_fee_pair_workflow_durable_reservation_no_delete",
        "execution_fee_pair_workflow_decision_reservation_no_delete",
    ):
        connection.execute("DROP TRIGGER IF EXISTS {}".format(trigger))
    connection.execute("DROP INDEX IF EXISTS execution_fee_pair_workflow_one_active")
    connection.execute("DROP TABLE execution_fee_pair_workflow_decision_reservations")
    connection.execute("DROP TABLE execution_fee_pair_workflow_durable_reservations")
    connection.execute("DROP TABLE execution_fee_pair_workflow_events")
    connection.execute("DROP TABLE execution_fee_pair_workflows")
    connection.execute("PRAGMA user_version=16")


def _downgrade_archive_to_v19(connection: sqlite3.Connection) -> None:
    """Restore the exact v19 workflow DDL from the current v20 archive schema."""

    connection.row_factory = sqlite3.Row

    def table_bytes(table):
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
        "execution_fee_pair_workflow_state",
        "execution_fee_pair_workflow_grid_settlement_insert",
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
        """SELECT candidate_id,reserved_bytes FROM
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
        restored_bytes = reservation["reserved_bytes"] - (4 - last_event) * event_column_growth
        if restored_bytes <= 0:
            raise AssertionError("v20 reservation cannot be restored to v19")
        connection.execute(
            """UPDATE execution_fee_pair_workflow_durable_reservations
               SET reserved_bytes=? WHERE candidate_id=? AND state='ACTIVE'""",
            (restored_bytes, reservation["candidate_id"]),
        )

    connection.execute(journal_module._FEE_PAIR_WORKFLOW_EVENT_NO_UPDATE_TRIGGER_SQL)
    connection.execute(journal_module._FEE_PAIR_WORKFLOW_EVENT_NO_DELETE_TRIGGER_SQL)
    connection.execute(journal_module._FEE_PAIR_WORKFLOW_STATE_TRIGGER_SQL)
    connection.execute(journal_module._FEE_PAIR_WORKFLOW_GRID_SETTLEMENT_INSERT_TRIGGER_SQL)
    connection.execute(journal_module._FEE_PAIR_WORKFLOW_DURABLE_RESERVATION_TRIGGER_SQL)
    new_bytes = sum(table_bytes(table) for table in changed_tables)
    connection.execute(
        """UPDATE execution_durable_capacity_usage SET payload_bytes=?
           WHERE capacity_class='BASE'""",
        (old_usage_bytes + new_bytes - old_bytes,),
    )
    connection.execute("PRAGMA user_version=19")


def _downgrade_archive_to_v18(connection: sqlite3.Connection) -> None:
    """Restore the exact v18 workflow DDL from the current v20 archive schema."""

    _downgrade_archive_to_v19(connection)

    connection.execute("DROP TRIGGER execution_fee_pair_workflow_state")
    connection.execute("DROP INDEX execution_fee_pair_workflow_one_active")
    connection.execute("DROP TABLE execution_fee_pair_workflow_grid_settlements")
    connection.execute("DROP TRIGGER execution_fee_pair_workflow_event_no_update")
    connection.execute("DROP TRIGGER execution_fee_pair_workflow_event_no_delete")
    connection.execute(
        "ALTER TABLE execution_fee_pair_workflow_events "
        "RENAME TO execution_fee_pair_workflow_events_v19"
    )
    connection.execute(journal_module._FEE_PAIR_WORKFLOW_EVENT_TABLE_SQL_V18)
    connection.execute(
        """INSERT INTO execution_fee_pair_workflow_events
           (event_id,candidate_id,event_sequence,event_kind,event_payload_json,created_at_ns)
           SELECT event_id,candidate_id,event_sequence,event_kind,event_payload_json,created_at_ns
           FROM execution_fee_pair_workflow_events_v19"""
    )
    connection.execute("DROP TABLE execution_fee_pair_workflow_events_v19")
    connection.execute(
        "ALTER TABLE execution_fee_pair_workflows DROP COLUMN grid_decision_id"
    )
    connection.execute(journal_module._FEE_PAIR_WORKFLOW_ACTIVE_INDEX_SQL_V18)
    connection.execute(journal_module._FEE_PAIR_WORKFLOW_STATE_TRIGGER_SQL_V18)
    connection.execute(journal_module._FEE_PAIR_WORKFLOW_EVENT_NO_UPDATE_TRIGGER_SQL)
    connection.execute(journal_module._FEE_PAIR_WORKFLOW_EVENT_NO_DELETE_TRIGGER_SQL)
    connection.execute("PRAGMA user_version=18")


def _downgrade_archive_to_v17(connection: sqlite3.Connection) -> None:
    """Restore the v17 workflow DDL and version-specific size contract."""

    _downgrade_archive_to_v18(connection)
    connection.execute("PRAGMA user_version=17")


def _candidate_bounds_database(path, encoding, table, payload):
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA encoding='{}'".format(encoding))
    connection.execute(
        "CREATE TABLE execution_fee_pair_candidates (candidate_payload_json)"
    )
    connection.execute(
        "CREATE TABLE execution_fee_pair_workflows (candidate_payload_json)"
    )
    connection.execute(
        "INSERT INTO {} (candidate_payload_json) VALUES (?)".format(table),
        (payload,),
    )
    return connection


def _utf16_v18_archive_with_workflow_payload(
    source_path, archive_path, payload, *, verify_on_create=True
):
    # Establish the encoding before the journal creates its first schema page.
    connection = sqlite3.connect(source_path)
    try:
        connection.execute("PRAGMA encoding='UTF-16le'")
        connection.execute("CREATE TABLE encoding_seed (value TEXT)")
        connection.execute("DROP TABLE encoding_seed")
        connection.commit()
    finally:
        connection.close()

    journal = ExecutionDecisionJournal(source_path)
    try:
        assert journal._connection.execute("PRAGMA encoding").fetchone()[0] == "UTF-16le"
        journal.register_fee_pair_required_scope("archive-account", "archive-strategy")
        journal._connection.execute(
            """INSERT INTO execution_fee_pair_workflows
               (candidate_id,account_scope,strategy_scope,logical_run_id,cohort_id,
                close_time,decision_kind,batch_id,candidate_sha256,candidate_payload_json,
                source_predecessor_sha256,owner_process_id,owner_instance_id,
                owner_token_sha256,deadline_monotonic_ns,state,verified_receipt_sha256,
                verified_receipt_json,created_at_ns,updated_at_ns)
               VALUES (?,?,?,?,?,?,?,?,?,?,NULL,?,?,?,?,?,NULL,NULL,?,?)""",
            (
                "archive-candidate",
                "archive-account",
                "archive-strategy",
                "archive-run",
                "archive-cohort",
                "2026-10-28T10:00:00Z",
                "simnow-live",
                "archive-batch",
                "0" * 64,
                payload,
                1,
                "archive-owner",
                "1" * 64,
                1,
                "RESERVED",
                1,
                1,
            ),
        )
        journal._connection.commit()
        # Exercise a real v18 database: no settlement table/column and the
        # historical SOURCE_ONLY-only terminal event constraint.
        _downgrade_archive_to_v18(journal._connection)
        # archive_snapshot intentionally accepts only the running Journal
        # version; use SQLite backup here to preserve a real historical v18
        # source, then exercise the public verifier at that version.
        target = sqlite3.connect(archive_path)
        try:
            target.execute("PRAGMA journal_mode=DELETE")
            journal._connection.backup(target)
            target.execute("PRAGMA journal_mode=DELETE")
        finally:
            target.close()
        if verify_on_create:
            receipt = archive_module.verify_execution_journal_archive(
                archive_path, expected_schema_version=18
            )
            assert receipt.schema_version == 18
    finally:
        journal.close()

    with sqlite3.connect(archive_path) as archived:
        assert archived.execute("PRAGMA encoding").fetchone()[0] == "UTF-16le"
    return archive_path


_LEGACY_CANDIDATE_ARCHIVE_CASES = (
    (16, "execution_fee_pair_candidates", 16_384),
    (17, "execution_fee_pair_candidates", 16_384),
    (18, "execution_fee_pair_candidates", 16_384),
)
_WORKFLOW_CANDIDATE_ARCHIVE_CASES = (
    (17, "execution_fee_pair_workflows", 16_384),
    (18, "execution_fee_pair_workflows", 1_048_576),
)
_CANDIDATE_ARCHIVE_CASES = (
    _LEGACY_CANDIDATE_ARCHIVE_CASES + _WORKFLOW_CANDIDATE_ARCHIVE_CASES
)


def _downgrade_archive_to_v15(connection: sqlite3.Connection) -> None:
    """Restore the exact pre-v16 object set in a copied archive fixture."""

    _downgrade_archive_to_v16(connection)

    connection.execute(
        "DROP TABLE execution_fee_pair_candidate_capacity_reservations"
    )
    connection.execute("DROP TABLE execution_fee_pair_candidate_events")
    connection.execute("DROP TABLE execution_fee_pair_candidates")
    connection.execute("PRAGMA user_version=15")


def _downgrade_archive_to_v14(connection: sqlite3.Connection) -> None:
    """Restore a v14 archive while retaining its required source highwater."""

    _downgrade_archive_to_v15(connection)
    connection.execute("DROP TABLE execution_fee_pair_scope_events")
    connection.execute("DROP TABLE execution_fee_pair_required_scopes")
    connection.execute("PRAGMA user_version=14")


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
        assert receipt.schema_version == ExecutionDecisionJournal._SCHEMA_VERSION
        assert receipt.size_bytes == archive_path.stat().st_size
        assert receipt.table_row_counts["execution_decisions"] == 2
        assert receipt.table_row_counts["execution_decision_intents"] == 2
        assert receipt.table_row_counts["execution_intent_resolutions"] == 1
        assert receipt.table_row_counts["execution_fee_pair_required_scopes"] == 1
        assert receipt.table_row_counts["execution_fee_pair_scope_events"] == 1
        assert receipt.table_row_counts["execution_fee_pair_candidates"] == 0
        assert receipt.table_row_counts["execution_fee_pair_candidate_events"] == 0

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
    source_path = tmp_path / "v16-source.sqlite3"
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

    # Older immutable snapshots predate later schema additions and remain
    # verifiable against their own cumulative version contract.
    with sqlite3.connect(archive_path) as archived:
        _downgrade_archive_to_v14(archived)

    verified = archive_module.verify_execution_journal_archive(
        archive_path, expected_schema_version=14
    )
    assert verified.schema_version == 14
    assert verified.table_row_counts["execution_decisions"] == 1


def test_archive_verifier_keeps_v16_snapshots_compatible(tmp_path):
    source_path = tmp_path / "v17-source-for-v16.sqlite3"
    archive_path = tmp_path / "valid-v16-archive.sqlite3"
    journal = ExecutionDecisionJournal(source_path)
    try:
        journal.archive_snapshot(archive_path)
    finally:
        journal.close()
    with sqlite3.connect(archive_path) as archived:
        _downgrade_archive_to_v16(archived)

    verified = archive_module.verify_execution_journal_archive(
        archive_path, expected_schema_version=16
    )
    assert verified.schema_version == 16


@pytest.mark.parametrize("encoding", ("UTF-8", "UTF-16le"))
@pytest.mark.parametrize(
    "schema_version,table,limit", _CANDIDATE_ARCHIVE_CASES
)
def test_archive_candidate_bounds_use_utf8_bytes_for_legal_rows(
    tmp_path, encoding, schema_version, table, limit
):
    payload = "x" * (limit // 2 + 1)
    path = tmp_path / "candidate-bounds-legal-{}-{}-{}.sqlite3".format(
        encoding.replace("-", "").lower(), schema_version, table
    )
    connection = _candidate_bounds_database(path, encoding, table, payload)
    try:
        stored_bytes = connection.execute(
            "SELECT length(CAST(candidate_payload_json AS BLOB)) FROM {}".format(table)
        ).fetchone()[0]
        assert len(payload.encode("utf-8")) <= limit
        if encoding.upper() != "UTF-8":
            assert stored_bytes > limit
        archive_module._validate_fee_pair_candidate_payload_bounds(
            connection,
            schema_version,
            legacy_candidate_bytes=journal_module._MAX_FEE_PAIR_CANDIDATE_BYTES,
            workflow_candidate_bytes=(
                journal_module._MAX_FEE_PAIR_CANDIDATE_BYTES
                if schema_version < journal_module._FEE_PAIR_WORKFLOW_CANDIDATE_SCHEMA_VERSION
                else journal_module._MAX_FEE_PAIR_WORKFLOW_CANDIDATE_BYTES
            ),
        )
    finally:
        connection.close()


@pytest.mark.parametrize("encoding", ("UTF-8", "UTF-16le"))
@pytest.mark.parametrize(
    "schema_version,table,limit", _CANDIDATE_ARCHIVE_CASES
)
def test_archive_candidate_bounds_reject_utf8_oversized_bmp_rows(
    tmp_path, encoding, schema_version, table, limit
):
    payload = "é" * (limit // 2 + 1)
    path = tmp_path / "candidate-bounds-oversized-{}-{}-{}.sqlite3".format(
        encoding.replace("-", "").lower(), schema_version, table
    )
    connection = _candidate_bounds_database(path, encoding, table, payload)
    try:
        stored_bytes = connection.execute(
            "SELECT length(CAST(candidate_payload_json AS BLOB)) FROM {}".format(table)
        ).fetchone()[0]
        assert len(payload) <= limit
        assert len(payload.encode("utf-8")) > limit
        if encoding.upper() != "UTF-8":
            assert stored_bytes <= 2 * limit
        with pytest.raises(
            archive_module.ExecutionJournalArchiveError,
            match="ARCHIVE_FEE_PAIR_CANDIDATE_TOO_LARGE",
        ):
            archive_module._validate_fee_pair_candidate_payload_bounds(
                connection,
                schema_version,
                legacy_candidate_bytes=journal_module._MAX_FEE_PAIR_CANDIDATE_BYTES,
                workflow_candidate_bytes=(
                    journal_module._MAX_FEE_PAIR_CANDIDATE_BYTES
                    if schema_version
                    < journal_module._FEE_PAIR_WORKFLOW_CANDIDATE_SCHEMA_VERSION
                    else journal_module._MAX_FEE_PAIR_WORKFLOW_CANDIDATE_BYTES
                ),
            )
    finally:
        connection.close()


@pytest.mark.parametrize(
    "schema_version,table",
    (
        (16, "execution_fee_pair_candidates"),
        (17, "execution_fee_pair_workflows"),
        (18, "execution_fee_pair_workflows"),
    ),
)
def test_archive_candidate_bounds_reject_non_text_rows(tmp_path, schema_version, table):
    path = tmp_path / "candidate-bounds-non-text-{}-{}.sqlite3".format(
        schema_version, table
    )
    connection = _candidate_bounds_database(
        path, "UTF-16le", table, sqlite3.Binary(b"{}")
    )
    try:
        assert connection.execute(
            "SELECT typeof(candidate_payload_json) FROM {}".format(table)
        ).fetchone()[0] == "blob"
        with pytest.raises(
            archive_module.ExecutionJournalArchiveError,
            match="ARCHIVE_FEE_PAIR_CANDIDATE_TOO_LARGE",
        ):
            archive_module._validate_fee_pair_candidate_payload_bounds(
                connection,
                schema_version,
                legacy_candidate_bytes=journal_module._MAX_FEE_PAIR_CANDIDATE_BYTES,
                workflow_candidate_bytes=(
                    journal_module._MAX_FEE_PAIR_CANDIDATE_BYTES
                    if schema_version
                    < journal_module._FEE_PAIR_WORKFLOW_CANDIDATE_SCHEMA_VERSION
                    else journal_module._MAX_FEE_PAIR_WORKFLOW_CANDIDATE_BYTES
                ),
            )
    finally:
        connection.close()


@pytest.mark.parametrize(
    "payload,expected_valid",
    (
        ("x" * (journal_module._MAX_FEE_PAIR_WORKFLOW_CANDIDATE_BYTES // 2 + 1), True),
        ("é" * (journal_module._MAX_FEE_PAIR_WORKFLOW_CANDIDATE_BYTES // 2 + 1), False),
    ),
    ids=("utf16-storage-over-limit-but-utf8-valid", "utf8-bytes-over-limit"),
)
def test_archive_verifier_enforces_utf8_bound_on_utf16_workflow_archive(
    tmp_path, payload, expected_valid
):
    limit = journal_module._MAX_FEE_PAIR_WORKFLOW_CANDIDATE_BYTES
    payload_utf8_bytes = len(payload.encode("utf-8"))
    assert (payload_utf8_bytes <= limit) is expected_valid
    source_path = tmp_path / "utf16-v18-source.sqlite3"
    archive_path = tmp_path / "utf16-v18-workflow.sqlite3"
    _utf16_v18_archive_with_workflow_payload(
        source_path,
        archive_path,
        payload,
        verify_on_create=expected_valid,
    )
    with sqlite3.connect(archive_path) as archived:
        database_bytes = archived.execute(
            """SELECT length(CAST(candidate_payload_json AS BLOB))
               FROM execution_fee_pair_workflows"""
        ).fetchone()[0]
    assert database_bytes <= 2 * limit
    if expected_valid:
        assert database_bytes > limit
        verified = archive_module.verify_execution_journal_archive(
            archive_path, expected_schema_version=18
        )
        assert verified.table_row_counts["execution_fee_pair_workflows"] == 1
    else:
        with pytest.raises(
            archive_module.ExecutionJournalArchiveError,
            match="ARCHIVE_FEE_PAIR_CANDIDATE_TOO_LARGE",
        ):
            archive_module.verify_execution_journal_archive(
                archive_path, expected_schema_version=18
            )


def test_archive_verifier_rejects_non_text_row_in_utf16_workflow_archive(tmp_path):
    source_path = tmp_path / "utf16-v18-source-with-blob.sqlite3"
    archive_path = tmp_path / "utf16-v18-workflow-with-blob.sqlite3"
    _utf16_v18_archive_with_workflow_payload(
        source_path,
        archive_path,
        sqlite3.Binary(b"{}"),
        verify_on_create=False,
    )
    with pytest.raises(
        archive_module.ExecutionJournalArchiveError,
        match="ARCHIVE_FEE_PAIR_CANDIDATE_TOO_LARGE",
    ):
        archive_module.verify_execution_journal_archive(
            archive_path, expected_schema_version=18
        )


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
    source_path = tmp_path / "v16-source.sqlite3"
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
        _downgrade_archive_to_v15(archived)
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
        _downgrade_archive_to_v14(archived)
        archived.execute("DROP TABLE execution_source_highwaters")

    with pytest.raises(
        archive_module.ExecutionJournalArchiveError,
        match="ARCHIVE_SCHEMA_INCOMPLETE",
    ):
        archive_module.verify_execution_journal_archive(
            archive_path, expected_schema_version=14
        )


@pytest.mark.parametrize(
    "statement",
    (
        "DROP TABLE execution_fee_pair_candidates",
        "DROP TABLE execution_fee_pair_candidate_events",
        "DROP TABLE execution_fee_pair_candidate_capacity_reservations",
        "DROP TRIGGER execution_fee_pair_candidate_state",
        "DROP TRIGGER execution_fee_pair_candidate_no_delete",
        "DROP TRIGGER execution_fee_pair_candidate_event_no_update",
        "DROP TRIGGER execution_fee_pair_candidate_event_no_delete",
        "DROP TRIGGER execution_fee_pair_candidate_capacity_state",
        "DROP TRIGGER execution_fee_pair_candidate_capacity_no_delete",
        "ALTER TABLE execution_fee_pair_candidate_events "
        "DROP COLUMN event_payload_json",
        "PRAGMA writable_schema=ON; "
        "UPDATE sqlite_master SET sql=replace(sql, "
        "'CHECK(length(candidate_sha256)=64)', "
        "'CHECK(length(candidate_sha256)=63)') "
        "WHERE type='table' AND name='execution_fee_pair_candidates'; "
        "PRAGMA writable_schema=OFF; "
        "PRAGMA schema_version=1000;",
        "CREATE TRIGGER execution_fee_pair_candidate_unexpected_guard "
        "BEFORE INSERT ON execution_fee_pair_candidates BEGIN SELECT 1; END",
        "CREATE TRIGGER execution_fee_pair_candidate_event_unexpected_guard "
        "BEFORE INSERT ON execution_fee_pair_candidate_events BEGIN SELECT 1; END",
    ),
)
def test_v16_archive_rejects_incomplete_or_unexpected_candidate_schema(
    tmp_path, statement
):
    source_path = tmp_path / "v16-source.sqlite3"
    archive_path = tmp_path / "damaged-v16.sqlite3"
    journal = ExecutionDecisionJournal(source_path)
    try:
        journal.archive_snapshot(archive_path)
    finally:
        journal.close()

    with sqlite3.connect(archive_path) as archived:
        _downgrade_archive_to_v16(archived)
        archived.executescript(statement)

    with pytest.raises(
        archive_module.ExecutionJournalArchiveError,
        match="ARCHIVE_SCHEMA_INCOMPLETE",
    ):
        archive_module.verify_execution_journal_archive(
            archive_path, expected_schema_version=16
        )


@pytest.mark.parametrize(
    "statement",
    (
        "DROP TABLE execution_fee_pair_workflows",
        "DROP TABLE execution_fee_pair_workflow_events",
        "DROP TABLE execution_fee_pair_workflow_durable_reservations",
        "DROP TABLE execution_fee_pair_workflow_decision_reservations",
        "DROP TRIGGER execution_fee_pair_workflow_state",
        "DROP TRIGGER execution_fee_pair_workflow_decision_reservation_no_delete",
        "ALTER TABLE execution_fee_pair_workflow_events DROP COLUMN event_payload_json",
        "PRAGMA writable_schema=ON; "
        "UPDATE sqlite_master SET sql=replace(sql, "
        "'CHECK(length(candidate_sha256)=64)', "
        "'CHECK(length(candidate_sha256)=63)') "
        "WHERE type='table' AND name='execution_fee_pair_workflows'; "
        "PRAGMA writable_schema=OFF; PRAGMA schema_version=1000;",
        "CREATE TRIGGER execution_fee_pair_workflow_unexpected_guard "
        "BEFORE INSERT ON execution_fee_pair_workflows BEGIN SELECT 1; END",
        "CREATE TRIGGER execution_fee_pair_workflow_event_unexpected_guard "
        "BEFORE INSERT ON execution_fee_pair_workflow_events BEGIN SELECT 1; END",
        "CREATE INDEX execution_fee_pair_workflow_event_unexpected_index "
        "ON execution_fee_pair_workflow_events(candidate_id)",
    ),
)
def test_v17_archive_rejects_incomplete_or_unexpected_workflow_schema(
    tmp_path, statement
):
    source_path = tmp_path / "v17-source.sqlite3"
    archive_path = tmp_path / "damaged-v17.sqlite3"
    journal = ExecutionDecisionJournal(source_path)
    try:
        journal.archive_snapshot(archive_path)
    finally:
        journal.close()

    with sqlite3.connect(archive_path) as archived:
        _downgrade_archive_to_v17(archived)
        archived.executescript(statement)

    with pytest.raises(
        archive_module.ExecutionJournalArchiveError,
        match="ARCHIVE_SCHEMA_INCOMPLETE",
    ):
        archive_module.verify_execution_journal_archive(
            archive_path, expected_schema_version=17
        )


@pytest.mark.parametrize(
    "statement",
    (
        "DROP TABLE execution_fee_pair_workflow_grid_settlements",
        "DROP TRIGGER execution_fee_pair_workflow_grid_settlement_insert",
        "DROP TRIGGER execution_fee_pair_workflow_grid_settlement_insert; "
        "ALTER TABLE execution_fee_pair_workflow_grid_settlements "
        "DROP COLUMN source_receipt_sha256",
        "CREATE TRIGGER execution_fee_pair_workflow_grid_settlement_unexpected_guard "
        "BEFORE INSERT ON execution_fee_pair_workflow_grid_settlements BEGIN SELECT 1; END",
    ),
)
def test_v19_archive_rejects_incomplete_or_unexpected_settlement_schema(
    tmp_path, statement
):
    source_path = tmp_path / "v19-source.sqlite3"
    archive_path = tmp_path / "damaged-v19.sqlite3"
    journal = ExecutionDecisionJournal(source_path)
    try:
        journal.archive_snapshot(archive_path)
    finally:
        journal.close()

    with sqlite3.connect(archive_path) as archived:
        _downgrade_archive_to_v19(archived)
        archived.executescript(statement)

    with pytest.raises(
        archive_module.ExecutionJournalArchiveError,
        match="ARCHIVE_SCHEMA_INCOMPLETE",
    ):
        archive_module.verify_execution_journal_archive(
            archive_path, expected_schema_version=19
        )


@pytest.mark.parametrize(
    "statement",
    (
        "CREATE TRIGGER source_highwater_unexpected_guard "
        "BEFORE INSERT ON execution_source_highwaters BEGIN SELECT 1; END",
        "ALTER TABLE execution_source_highwaters DROP COLUMN receipt_sha256",
        "PRAGMA writable_schema=ON; "
        "UPDATE sqlite_master SET sql=replace(sql, "
        "'CHECK(anchor_kind IN (''GRID'',''SOURCE_ONLY''))', "
        "'CHECK(anchor_kind IN (''GRID''))') "
        "WHERE type='table' AND name='execution_source_highwaters'; "
        "PRAGMA writable_schema=OFF; "
        "PRAGMA schema_version=1000;",
    ),
)
def test_v14_archive_rejects_incomplete_or_unexpected_source_highwater_schema(
    tmp_path, statement
):
    source_path = tmp_path / "v16-source-for-v14-corruption.sqlite3"
    archive_path = tmp_path / "damaged-v14-source-highwater.sqlite3"
    journal = ExecutionDecisionJournal(source_path)
    try:
        journal.archive_snapshot(archive_path)
    finally:
        journal.close()

    with sqlite3.connect(archive_path) as archived:
        _downgrade_archive_to_v14(archived)
        archived.executescript(statement)

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
