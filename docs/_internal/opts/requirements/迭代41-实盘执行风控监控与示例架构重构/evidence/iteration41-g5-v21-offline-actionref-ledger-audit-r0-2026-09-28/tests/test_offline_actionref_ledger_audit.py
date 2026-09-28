from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from bt_api_execution.offline_actionref_ledger_audit import (
    ActionRefAuditError,
    project_v21_actionref_ledger,
)

ACCOUNT = "account:" + "a" * 64
SCOPE = "scope:" + "b" * 64
INTENT = "intent-0001"
ACTION = "action-0001"
COMMAND = "command-0001"
RUNTIME_ORDER = "bt-managed-v1:" + "c" * 64
ORDER_REF = "000000000123"
TRADING_DAY = "20260927"

_SCHEMA = """
CREATE TABLE execution_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE ctp_order_identity_reservations (
    account_key TEXT NOT NULL,
    trading_day TEXT NOT NULL,
    scope_key TEXT NOT NULL,
    managed_intent_id TEXT NOT NULL,
    runtime_order_id TEXT NOT NULL,
    order_ref TEXT NOT NULL,
    created_at_ns INTEGER NOT NULL,
    PRIMARY KEY (account_key, scope_key, managed_intent_id),
    UNIQUE (account_key, runtime_order_id),
    UNIQUE (account_key, order_ref)
);
CREATE TABLE ctp_dispatch_commands (
    account_key TEXT NOT NULL,
    scope_key TEXT NOT NULL,
    trading_day TEXT NOT NULL,
    operation TEXT NOT NULL,
    command_id TEXT NOT NULL,
    request_payload_json TEXT NOT NULL,
    request_payload_sha256 TEXT NOT NULL,
    reservation_managed_intent_id TEXT NOT NULL,
    order_ref TEXT,
    cancel_target_order_ref TEXT,
    cancel_target_exchange_id TEXT,
    cancel_target_order_sys_id TEXT,
    cancel_target_front_id INTEGER,
    cancel_target_session_id INTEGER,
    approval_use_id TEXT NOT NULL,
    approval_digest TEXT NOT NULL,
    session_binding_json TEXT NOT NULL,
    session_binding_sha256 TEXT NOT NULL,
    correlation_version INTEGER NOT NULL,
    runtime_order_id TEXT,
    managed_action_id TEXT,
    session_generation_id TEXT,
    dispatch_front_id INTEGER,
    dispatch_session_id INTEGER,
    native_request_id INTEGER,
    native_action_ref TEXT,
    native_action_ref_int INTEGER,
    native_request_payload_json TEXT,
    native_request_payload_sha256 TEXT,
    local_queue_receipt_id TEXT,
    local_queue_receipt_queued INTEGER,
    status TEXT NOT NULL,
    created_at_ns INTEGER NOT NULL,
    updated_at_ns INTEGER NOT NULL,
    claimed_at_ns INTEGER,
    claimed_owner_id TEXT,
    claimed_fencing_token INTEGER,
    callback_owner_intent_id TEXT,
    native_call_inflight INTEGER NOT NULL DEFAULT 0,
    completed_at_ns INTEGER,
    unknown_at_ns INTEGER,
    unknown_reason TEXT,
    native_receipt_payload_json TEXT,
    native_receipt_sha256 TEXT,
    completion_echo_json TEXT,
    completion_echo_sha256 TEXT,
    PRIMARY KEY (account_key, command_id),
    UNIQUE (account_key, approval_use_id)
);
CREATE UNIQUE INDEX ctp_dispatch_session_request_unique
    ON ctp_dispatch_commands(account_key, session_generation_id, native_request_id)
    WHERE correlation_version IN (1, 2);
CREATE UNIQUE INDEX ctp_dispatch_managed_action_unique
    ON ctp_dispatch_commands(account_key, scope_key, managed_action_id)
    WHERE correlation_version IN (1, 2);
CREATE UNIQUE INDEX ctp_dispatch_native_action_ref_unique
    ON ctp_dispatch_commands(account_key, native_action_ref_int)
    WHERE correlation_version = 2 AND native_action_ref_int IS NOT NULL;
CREATE UNIQUE INDEX ctp_dispatch_local_queue_receipt_unique
    ON ctp_dispatch_commands(account_key, local_queue_receipt_id)
    WHERE local_queue_receipt_id IS NOT NULL;
CREATE TABLE ctp_native_action_ref_counters (
    account_key TEXT PRIMARY KEY,
    last_action_ref INTEGER NOT NULL,
    updated_at_ns INTEGER NOT NULL
);
CREATE TABLE ctp_native_action_ref_allocations (
    account_key TEXT NOT NULL,
    native_action_ref INTEGER NOT NULL,
    scope_key TEXT NOT NULL,
    command_id TEXT NOT NULL,
    managed_action_id TEXT NOT NULL,
    allocated_at_ns INTEGER NOT NULL,
    PRIMARY KEY (account_key, native_action_ref),
    UNIQUE (account_key, command_id),
    UNIQUE (account_key, scope_key, managed_action_id)
);
CREATE TRIGGER ctp_native_action_ref_counter_monotonic
BEFORE UPDATE OF last_action_ref ON ctp_native_action_ref_counters
WHEN NEW.last_action_ref != OLD.last_action_ref + 1
     OR NEW.last_action_ref > 2147483647
BEGIN SELECT RAISE(ABORT, 'CTP native ActionRef counter must increment by one'); END;
CREATE TRIGGER ctp_native_action_ref_counter_no_delete
BEFORE DELETE ON ctp_native_action_ref_counters
BEGIN SELECT RAISE(ABORT, 'CTP native ActionRef counter is durable'); END;
CREATE TRIGGER ctp_native_action_ref_allocations_immutable_update
BEFORE UPDATE ON ctp_native_action_ref_allocations
BEGIN SELECT RAISE(ABORT, 'CTP native ActionRef allocation is immutable'); END;
CREATE TRIGGER ctp_native_action_ref_allocations_immutable_delete
BEFORE DELETE ON ctp_native_action_ref_allocations
BEGIN SELECT RAISE(ABORT, 'CTP native ActionRef allocation is immutable'); END;
"""


def _json_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _bundle_bytes(path: Path) -> dict[str, bytes]:
    return {
        suffix: candidate.read_bytes()
        for suffix in ("", "-wal", "-shm", "-journal")
        if (candidate := Path(str(path) + suffix)).is_file()
    }


def _insert_reservation(connection: sqlite3.Connection) -> None:
    connection.execute(
        "INSERT INTO ctp_order_identity_reservations VALUES (?, ?, ?, ?, ?, ?, ?)",
        (ACCOUNT, TRADING_DAY, SCOPE, INTENT, RUNTIME_ORDER, ORDER_REF, 1),
    )


def _insert_cancel(
    connection: sqlite3.Connection,
    *,
    command_id: str = COMMAND,
    state: str = "READY",
    action_ref: int = 38,
    cancel_order_ref: str = ORDER_REF,
) -> None:
    logical_json = '{"InstrumentID":"rb2610","Volume":1}'
    native_json = '{"InstrumentID":"rb2610","OrderActionRef":' + str(action_ref) + ',"Volume":1}'
    values = (
        ACCOUNT,
        SCOPE,
        TRADING_DAY,
        "CANCEL",
        command_id,
        logical_json,
        _json_digest(logical_json),
        INTENT,
        None,
        cancel_order_ref,
        "SHFE",
        "sys-1",
        7,
        9,
        "permit-1",
        "d" * 64,
        "{}",
        "e" * 64,
        2,
        RUNTIME_ORDER,
        ACTION,
        "session-1",
        7,
        9,
        41,
        None,
        action_ref,
        native_json,
        _json_digest(native_json),
        None,
        state,
        1,
        1,
    )
    connection.execute(
        """INSERT INTO ctp_dispatch_commands(
            account_key, scope_key, trading_day, operation, command_id,
            request_payload_json, request_payload_sha256,
            reservation_managed_intent_id, order_ref, cancel_target_order_ref,
            cancel_target_exchange_id, cancel_target_order_sys_id,
            cancel_target_front_id, cancel_target_session_id,
            approval_use_id, approval_digest, session_binding_json,
            session_binding_sha256, correlation_version, runtime_order_id,
            managed_action_id, session_generation_id, dispatch_front_id,
            dispatch_session_id, native_request_id, native_action_ref,
            native_action_ref_int, native_request_payload_json,
            native_request_payload_sha256, local_queue_receipt_id,
            status, created_at_ns, updated_at_ns
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        values,
    )
    connection.execute(
        "INSERT INTO ctp_native_action_ref_allocations VALUES (?, ?, ?, ?, ?, ?)",
        (ACCOUNT, action_ref, SCOPE, command_id, ACTION, 1),
    )


def make_database(
    path: Path,
    *,
    version: str = "21",
    action_ref: int = 38,
    counter: int | None = None,
    state: str = "READY",
    cancel_order_ref: str = ORDER_REF,
    add_cancel: bool = True,
) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.executescript(_SCHEMA)
        connection.execute(
            "INSERT INTO execution_meta(key, value) VALUES ('schema_version', ?)", (version,)
        )
        _insert_reservation(connection)
        if add_cancel:
            _insert_cancel(
                connection,
                state=state,
                action_ref=action_ref,
                cancel_order_ref=cancel_order_ref,
            )
        high_water = (action_ref if add_cancel else 0) if counter is None else counter
        if high_water or add_cancel:
            connection.execute(
                "INSERT INTO ctp_native_action_ref_counters VALUES (?, ?, ?)",
                (ACCOUNT, high_water, 1),
            )
        connection.commit()
    finally:
        connection.close()


def _insert_allocation_only(connection: sqlite3.Connection) -> None:
    connection.execute(
        "INSERT INTO ctp_native_action_ref_allocations VALUES (?, ?, ?, ?, ?, ?)",
        (ACCOUNT, 38, SCOPE, "missing-command", ACTION, 1),
    )
    connection.commit()


def _expect_code(code: str, path: Path) -> None:
    with pytest.raises(ActionRefAuditError) as error:
        project_v21_actionref_ledger(path, account_key=ACCOUNT)
    assert error.value.code == code


def test_projects_durable_v21_cancel_join_and_is_non_authorizing(tmp_path: Path) -> None:
    path = tmp_path / "v21.sqlite3"
    make_database(path, action_ref=38, counter=38)

    result = project_v21_actionref_ledger(path, account_key=ACCOUNT)

    assert len(result.rows) == 1
    row = result.rows[0]
    assert (row.command_id, row.native_action_ref, row.state) == (COMMAND, 38, "READY")
    assert (row.order_ref, row.managed_intent_id, row.runtime_order_id) == (
        ORDER_REF,
        INTENT,
        RUNTIME_ORDER,
    )
    assert result.counter_high_water == 38
    assert result.observed_high_water == 38
    assert result.authority is False
    assert result.cutover_enabled is False
    assert len(result.projection_sha256) == 64
    assert len(result.source_bundle_sha256) == 64


def test_projector_is_read_only_and_repeatable(tmp_path: Path) -> None:
    path = tmp_path / "read-only.sqlite3"
    make_database(path)
    before = path.read_bytes()

    first = project_v21_actionref_ledger(path, account_key=ACCOUNT)
    second = project_v21_actionref_ledger(path, account_key=ACCOUNT)

    assert path.read_bytes() == before
    assert first == second
    uri = path.resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        with pytest.raises(sqlite3.OperationalError):
            connection.execute(
                "UPDATE ctp_native_action_ref_counters SET last_action_ref = 39 "
                "WHERE account_key = ?",
                (ACCOUNT,),
            )
    finally:
        connection.close()


def test_wal_snapshot_is_read_only_and_repeatable(tmp_path: Path) -> None:
    path = tmp_path / "wal.sqlite3"
    make_database(path)
    connection = sqlite3.connect(path)
    try:
        assert connection.execute("PRAGMA journal_mode = WAL").fetchone()[0] == "wal"
        connection.execute("INSERT INTO execution_meta(key, value) VALUES ('wal-probe', 'present')")
        connection.commit()
        before = _bundle_bytes(path)
        assert "-wal" in before and "-shm" in before

        first = project_v21_actionref_ledger(path, account_key=ACCOUNT)
        second = project_v21_actionref_ledger(path, account_key=ACCOUNT)

        assert first == second
        assert _bundle_bytes(path) == before
    finally:
        connection.close()


def test_empty_account_has_zero_high_water_and_no_rows(tmp_path: Path) -> None:
    path = tmp_path / "empty.sqlite3"
    make_database(path, add_cancel=False)

    result = project_v21_actionref_ledger(path, account_key=ACCOUNT)

    assert result.rows == ()
    assert result.counter_high_water == result.observed_high_water == 0


def test_schema_version_and_relevant_column_shape_are_exact(tmp_path: Path) -> None:
    path = tmp_path / "schema.sqlite3"
    make_database(path, version="22")
    _expect_code("schema_version_unsupported", path)

    path = tmp_path / "extra-column.sqlite3"
    make_database(path)
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "ALTER TABLE ctp_native_action_ref_allocations ADD COLUMN unexpected TEXT"
        )
        connection.commit()
    finally:
        connection.close()
    _expect_code("schema_columns_mismatch", path)


def test_missing_uniqueness_or_immutability_contract_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "index.sqlite3"
    make_database(path)
    connection = sqlite3.connect(path)
    try:
        connection.execute("DROP INDEX ctp_dispatch_native_action_ref_unique")
        connection.commit()
    finally:
        connection.close()
    _expect_code("schema_unique_indexes_mismatch", path)

    path = tmp_path / "index-predicate.sqlite3"
    make_database(path)
    connection = sqlite3.connect(path)
    try:
        connection.execute("DROP INDEX ctp_dispatch_session_request_unique")
        connection.execute(
            """CREATE UNIQUE INDEX ctp_dispatch_session_request_unique
            ON ctp_dispatch_commands(account_key, session_generation_id, native_request_id)
            WHERE correlation_version = 2"""
        )
        connection.commit()
    finally:
        connection.close()
    _expect_code("schema_named_indexes_mismatch", path)

    path = tmp_path / "trigger.sqlite3"
    make_database(path)
    connection = sqlite3.connect(path)
    try:
        connection.execute("DROP TRIGGER ctp_native_action_ref_allocations_immutable_delete")
        connection.commit()
    finally:
        connection.close()
    _expect_code("schema_triggers_mismatch", path)

    path = tmp_path / "no-op-trigger.sqlite3"
    make_database(path)
    connection = sqlite3.connect(path)
    try:
        connection.execute("DROP TRIGGER ctp_native_action_ref_allocations_immutable_delete")
        connection.execute(
            """CREATE TRIGGER ctp_native_action_ref_allocations_immutable_delete
            BEFORE DELETE ON ctp_native_action_ref_allocations
            BEGIN SELECT 1; END"""
        )
        connection.commit()
    finally:
        connection.close()
    _expect_code("schema_triggers_mismatch", path)


def test_missing_allocation_or_orphan_allocation_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "missing-map.sqlite3"
    make_database(path)
    connection = sqlite3.connect(path)
    try:
        connection.execute("DROP TRIGGER ctp_native_action_ref_allocations_immutable_delete")
        connection.execute(
            "DELETE FROM ctp_native_action_ref_allocations WHERE account_key = ?",
            (ACCOUNT,),
        )
        connection.execute(
            """CREATE TRIGGER ctp_native_action_ref_allocations_immutable_delete
            BEFORE DELETE ON ctp_native_action_ref_allocations
            BEGIN SELECT RAISE(ABORT, 'CTP native ActionRef allocation is immutable'); END"""
        )
        connection.commit()
    finally:
        connection.close()
    _expect_code("cancel_allocation_missing", path)

    path = tmp_path / "orphan-map.sqlite3"
    make_database(path, add_cancel=False)
    connection = sqlite3.connect(path)
    try:
        _insert_allocation_only(connection)
    finally:
        connection.close()
    _expect_code("allocation_command_missing", path)


def test_actionref_payload_target_and_counter_mismatches_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / "action-mismatch.sqlite3"
    make_database(path)
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "UPDATE ctp_dispatch_commands SET native_action_ref_int = 39 WHERE command_id = ?",
            (COMMAND,),
        )
        connection.commit()
    finally:
        connection.close()
    _expect_code("command_action_ref_mismatch", path)

    path = tmp_path / "target-mismatch.sqlite3"
    make_database(path, cancel_order_ref="000000000999")
    _expect_code("order_reservation_command_mismatch", path)

    path = tmp_path / "counter-low.sqlite3"
    make_database(path, action_ref=38, counter=37)
    _expect_code("counter_below_allocations", path)

    path = tmp_path / "counter-ahead.sqlite3"
    make_database(path, action_ref=38, counter=39)
    _expect_code("counter_ahead_of_allocations", path)


def test_unknown_legacy_and_bad_payload_rows_are_not_projected(tmp_path: Path) -> None:
    path = tmp_path / "unknown.sqlite3"
    make_database(path, state="UNKNOWN")
    _expect_code("unknown_action_present", path)

    path = tmp_path / "legacy.sqlite3"
    make_database(path)
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "UPDATE ctp_dispatch_commands SET correlation_version = 1 WHERE command_id = ?",
            (COMMAND,),
        )
        connection.commit()
    finally:
        connection.close()
    _expect_code("legacy_command_present", path)

    path = tmp_path / "payload.sqlite3"
    make_database(path)
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "UPDATE ctp_dispatch_commands SET native_request_payload_json = ? WHERE command_id = ?",
            ('{"OrderActionRef":39}', COMMAND),
        )
        connection.commit()
    finally:
        connection.close()
    _expect_code("native_payload_invalid", path)


def test_account_and_database_inputs_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / "input.sqlite3"
    make_database(path)
    with pytest.raises(ActionRefAuditError) as error:
        project_v21_actionref_ledger(path, account_key="account:wrong")
    assert error.value.code == "account_key_invalid"
    with pytest.raises(ActionRefAuditError) as error:
        project_v21_actionref_ledger(tmp_path / "missing.sqlite3", account_key=ACCOUNT)
    assert error.value.code == "database_path_invalid"
