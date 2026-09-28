"""Read-only projector for one frozen bt_api_execution schema-21 SQLite copy.

This module is LOCAL_OFFLINE_ONLY. Its hashes and consistency checks do not
authenticate a source, establish an account cutover, or grant write authority.
It uses only the Python standard library and never opens a database for writing.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_SCHEMA_VERSION = "21"
_MAX_ACTION_REF = 2_147_483_647
_HEX_64 = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_ORDER_REF = re.compile(r"^[0-9]{12}$", re.ASCII)
_RUNTIME_ORDER_ID = re.compile(r"^bt-managed-v1:[0-9a-f]{64}$", re.ASCII)
_ALLOWED_STATES = frozenset({"READY", "CLAIMED", "COMPLETED"})

_TABLE_COLUMNS: dict[str, tuple[tuple[str, str], ...]] = {
    "execution_meta": (("key", "TEXT"), ("value", "TEXT")),
    "ctp_order_identity_reservations": (
        ("account_key", "TEXT"),
        ("trading_day", "TEXT"),
        ("scope_key", "TEXT"),
        ("managed_intent_id", "TEXT"),
        ("runtime_order_id", "TEXT"),
        ("order_ref", "TEXT"),
        ("created_at_ns", "INTEGER"),
    ),
    "ctp_dispatch_commands": (
        ("account_key", "TEXT"),
        ("scope_key", "TEXT"),
        ("trading_day", "TEXT"),
        ("operation", "TEXT"),
        ("command_id", "TEXT"),
        ("request_payload_json", "TEXT"),
        ("request_payload_sha256", "TEXT"),
        ("reservation_managed_intent_id", "TEXT"),
        ("order_ref", "TEXT"),
        ("cancel_target_order_ref", "TEXT"),
        ("cancel_target_exchange_id", "TEXT"),
        ("cancel_target_order_sys_id", "TEXT"),
        ("cancel_target_front_id", "INTEGER"),
        ("cancel_target_session_id", "INTEGER"),
        ("approval_use_id", "TEXT"),
        ("approval_digest", "TEXT"),
        ("session_binding_json", "TEXT"),
        ("session_binding_sha256", "TEXT"),
        ("correlation_version", "INTEGER"),
        ("runtime_order_id", "TEXT"),
        ("managed_action_id", "TEXT"),
        ("session_generation_id", "TEXT"),
        ("dispatch_front_id", "INTEGER"),
        ("dispatch_session_id", "INTEGER"),
        ("native_request_id", "INTEGER"),
        ("native_action_ref", "TEXT"),
        ("native_action_ref_int", "INTEGER"),
        ("native_request_payload_json", "TEXT"),
        ("native_request_payload_sha256", "TEXT"),
        ("local_queue_receipt_id", "TEXT"),
        ("local_queue_receipt_queued", "INTEGER"),
        ("status", "TEXT"),
        ("created_at_ns", "INTEGER"),
        ("updated_at_ns", "INTEGER"),
        ("claimed_at_ns", "INTEGER"),
        ("claimed_owner_id", "TEXT"),
        ("claimed_fencing_token", "INTEGER"),
        ("callback_owner_intent_id", "TEXT"),
        ("native_call_inflight", "INTEGER"),
        ("completed_at_ns", "INTEGER"),
        ("unknown_at_ns", "INTEGER"),
        ("unknown_reason", "TEXT"),
        ("native_receipt_payload_json", "TEXT"),
        ("native_receipt_sha256", "TEXT"),
        ("completion_echo_json", "TEXT"),
        ("completion_echo_sha256", "TEXT"),
    ),
    "ctp_native_action_ref_counters": (
        ("account_key", "TEXT"),
        ("last_action_ref", "INTEGER"),
        ("updated_at_ns", "INTEGER"),
    ),
    "ctp_native_action_ref_allocations": (
        ("account_key", "TEXT"),
        ("native_action_ref", "INTEGER"),
        ("scope_key", "TEXT"),
        ("command_id", "TEXT"),
        ("managed_action_id", "TEXT"),
        ("allocated_at_ns", "INTEGER"),
    ),
}

_PRIMARY_KEYS: dict[str, tuple[str, ...]] = {
    "execution_meta": ("key",),
    "ctp_order_identity_reservations": (
        "account_key",
        "scope_key",
        "managed_intent_id",
    ),
    "ctp_dispatch_commands": ("account_key", "command_id"),
    "ctp_native_action_ref_counters": ("account_key",),
    "ctp_native_action_ref_allocations": ("account_key", "native_action_ref"),
}
_UNIQUE_INDEXES: dict[str, tuple[tuple[str, ...], ...]] = {
    "execution_meta": (("key",),),
    "ctp_order_identity_reservations": (
        ("account_key", "scope_key", "managed_intent_id"),
        ("account_key", "runtime_order_id"),
        ("account_key", "order_ref"),
    ),
    "ctp_dispatch_commands": (
        ("account_key", "command_id"),
        ("account_key", "approval_use_id"),
        ("account_key", "session_generation_id", "native_request_id"),
        ("account_key", "scope_key", "managed_action_id"),
        ("account_key", "native_action_ref_int"),
        ("account_key", "local_queue_receipt_id"),
    ),
    "ctp_native_action_ref_counters": (("account_key",),),
    "ctp_native_action_ref_allocations": (
        ("account_key", "native_action_ref"),
        ("account_key", "command_id"),
        ("account_key", "scope_key", "managed_action_id"),
    ),
}
_UNIQUE_INDEX_SQL = {
    "ctp_dispatch_session_request_unique": (
        "CREATE UNIQUE INDEX ctp_dispatch_session_request_unique "
        "ON ctp_dispatch_commands(account_key, session_generation_id, native_request_id) "
        "WHERE correlation_version IN (1, 2)"
    ),
    "ctp_dispatch_managed_action_unique": (
        "CREATE UNIQUE INDEX ctp_dispatch_managed_action_unique "
        "ON ctp_dispatch_commands(account_key, scope_key, managed_action_id) "
        "WHERE correlation_version IN (1, 2)"
    ),
    "ctp_dispatch_native_action_ref_unique": (
        "CREATE UNIQUE INDEX ctp_dispatch_native_action_ref_unique "
        "ON ctp_dispatch_commands(account_key, native_action_ref_int) "
        "WHERE correlation_version = 2 AND native_action_ref_int IS NOT NULL"
    ),
    "ctp_dispatch_local_queue_receipt_unique": (
        "CREATE UNIQUE INDEX ctp_dispatch_local_queue_receipt_unique "
        "ON ctp_dispatch_commands(account_key, local_queue_receipt_id) "
        "WHERE local_queue_receipt_id IS NOT NULL"
    ),
}
_REQUIRED_TRIGGER_SQL = {
    "ctp_native_action_ref_counter_monotonic": (
        "CREATE TRIGGER ctp_native_action_ref_counter_monotonic "
        "BEFORE UPDATE OF last_action_ref ON ctp_native_action_ref_counters "
        "WHEN NEW.last_action_ref != OLD.last_action_ref + 1 "
        "OR NEW.last_action_ref > 2147483647 BEGIN SELECT RAISE(ABORT, "
        "'CTP native ActionRef counter must increment by one'); END"
    ),
    "ctp_native_action_ref_counter_no_delete": (
        "CREATE TRIGGER ctp_native_action_ref_counter_no_delete "
        "BEFORE DELETE ON ctp_native_action_ref_counters BEGIN SELECT RAISE(ABORT, "
        "'CTP native ActionRef counter is durable'); END"
    ),
    "ctp_native_action_ref_allocations_immutable_update": (
        "CREATE TRIGGER ctp_native_action_ref_allocations_immutable_update "
        "BEFORE UPDATE ON ctp_native_action_ref_allocations BEGIN SELECT RAISE(ABORT, "
        "'CTP native ActionRef allocation is immutable'); END"
    ),
    "ctp_native_action_ref_allocations_immutable_delete": (
        "CREATE TRIGGER ctp_native_action_ref_allocations_immutable_delete "
        "BEFORE DELETE ON ctp_native_action_ref_allocations BEGIN SELECT RAISE(ABORT, "
        "'CTP native ActionRef allocation is immutable'); END"
    ),
}


class ActionRefAuditError(ValueError):
    """Stable fail-closed error code from the offline projector."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class V21ActionRefRow:
    account_key: str
    trading_day: str
    scope_key: str
    managed_action_id: str
    managed_intent_id: str
    runtime_order_id: str
    order_ref: str
    native_action_ref: int
    command_id: str
    state: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "account_key": self.account_key,
            "trading_day": self.trading_day,
            "scope_key": self.scope_key,
            "managed_action_id": self.managed_action_id,
            "managed_intent_id": self.managed_intent_id,
            "runtime_order_id": self.runtime_order_id,
            "order_ref": self.order_ref,
            "native_action_ref": self.native_action_ref,
            "command_id": self.command_id,
            "state": self.state,
        }


@dataclass(frozen=True)
class V21ActionRefLedgerProjection:
    account_key: str
    schema_version: str
    rows: tuple[V21ActionRefRow, ...]
    counter_high_water: int
    observed_high_water: int
    projection_sha256: str
    source_bundle_sha256: str
    authority: bool = False
    cutover_enabled: bool = False


def _reject(code: str) -> None:
    raise ActionRefAuditError(code)


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as error:
        raise ActionRefAuditError("payload_not_canonical_json") from error


def _payload_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _hash_path(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while True:
            block = stream.read(1024 * 1024)
            if not block:
                break
            size += len(block)
            digest.update(block)
    return size, digest.hexdigest()


def _source_bundle_sha256(path: Path) -> str:
    components: list[dict[str, Any]] = []
    for suffix in ("", "-wal", "-shm", "-journal"):
        component = Path(str(path) + suffix)
        if component.is_file():
            size, digest = _hash_path(component)
            components.append({"suffix": suffix, "size": size, "sha256": digest})
    if not components or components[0]["suffix"] != "":
        _reject("database_missing")
    return _payload_sha256({"schema": "v21-source-bundle.v1", "components": components})


def _quote_identifier(value: str) -> str:
    if not value or any(
        char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"
        for char in value
    ):
        _reject("schema_identifier_invalid")
    return '"' + value + '"'


def _table_signature(connection: sqlite3.Connection, table: str) -> tuple[tuple[str, str], ...]:
    quoted = _quote_identifier(table)
    rows = connection.execute(f"PRAGMA table_info({quoted})").fetchall()
    if not rows:
        _reject("schema_table_missing")
    return tuple((str(row[1]), str(row[2]).upper()) for row in rows)


def _primary_key(connection: sqlite3.Connection, table: str) -> tuple[str, ...]:
    quoted = _quote_identifier(table)
    rows = connection.execute(f"PRAGMA table_info({quoted})").fetchall()
    ordered = sorted((int(row[5]), str(row[1])) for row in rows if int(row[5]) > 0)
    return tuple(name for _, name in ordered)


def _unique_indexes(connection: sqlite3.Connection, table: str) -> tuple[tuple[str, ...], ...]:
    quoted = _quote_identifier(table)
    result: list[tuple[str, ...]] = []
    for index_row in connection.execute(f"PRAGMA index_list({quoted})").fetchall():
        if int(index_row[2]) != 1:
            continue
        index_name = str(index_row[1])
        index_quoted = _quote_identifier(index_name)
        columns = tuple(
            str(row[2])
            for row in connection.execute(f"PRAGMA index_info({index_quoted})").fetchall()
            if int(row[0]) >= 0
        )
        result.append(columns)
    return tuple(sorted(result))


def _normalized_sql(value: Any) -> str:
    if type(value) is not str:
        _reject("schema_sql_missing")
    return " ".join(value.split()).casefold()


def _verify_schema(connection: sqlite3.Connection) -> None:
    for table, expected_columns in _TABLE_COLUMNS.items():
        if _table_signature(connection, table) != expected_columns:
            _reject("schema_columns_mismatch")
        if _primary_key(connection, table) != _PRIMARY_KEYS[table]:
            _reject("schema_primary_key_mismatch")
        if _unique_indexes(connection, table) != tuple(sorted(_UNIQUE_INDEXES[table])):
            _reject("schema_unique_indexes_mismatch")

    command_indexes = connection.execute('PRAGMA index_list("ctp_dispatch_commands")').fetchall()
    explicit_unique_names = {
        str(row[1])
        for row in command_indexes
        if int(row[2]) == 1 and not str(row[1]).startswith("sqlite_autoindex_")
    }
    explicit_indexes = {
        str(row[0]): row[1]
        for row in connection.execute(
            "SELECT name, sql FROM sqlite_master "
            "WHERE type = 'index' AND tbl_name = 'ctp_dispatch_commands'"
        ).fetchall()
        if str(row[0]) in explicit_unique_names
    }
    if set(explicit_indexes) != set(_UNIQUE_INDEX_SQL):
        _reject("schema_named_indexes_mismatch")
    if any(
        _normalized_sql(explicit_indexes[name]) != _normalized_sql(expected)
        for name, expected in _UNIQUE_INDEX_SQL.items()
    ):
        _reject("schema_named_indexes_mismatch")

    triggers = {
        str(row[0]): (str(row[1]), str(row[2]))
        for row in connection.execute(
            "SELECT name, tbl_name, sql FROM sqlite_master "
            "WHERE type = 'trigger' AND tbl_name IN (?, ?) ",
            ("ctp_native_action_ref_counters", "ctp_native_action_ref_allocations"),
        ).fetchall()
    }
    if set(triggers) != set(_REQUIRED_TRIGGER_SQL):
        _reject("schema_triggers_mismatch")
    expected_trigger_tables = {
        "ctp_native_action_ref_counter_monotonic": "ctp_native_action_ref_counters",
        "ctp_native_action_ref_counter_no_delete": "ctp_native_action_ref_counters",
        "ctp_native_action_ref_allocations_immutable_update": "ctp_native_action_ref_allocations",
        "ctp_native_action_ref_allocations_immutable_delete": "ctp_native_action_ref_allocations",
    }
    if any(
        triggers[name][0] != table
        or _normalized_sql(triggers[name][1]) != _normalized_sql(_REQUIRED_TRIGGER_SQL[name])
        for name, table in expected_trigger_tables.items()
    ):
        _reject("schema_triggers_mismatch")

    schema_row = connection.execute(
        "SELECT value FROM execution_meta WHERE key = ?", ("schema_version",)
    ).fetchone()
    if schema_row is None or type(schema_row[0]) is not str or schema_row[0] != _SCHEMA_VERSION:
        _reject("schema_version_unsupported")


def _required_text(row: sqlite3.Row, name: str, code: str = "row_identity_invalid") -> str:
    value = row[name]
    if type(value) is not str or not value:
        _reject(code)
    return value


def _load_json_object(value: Any, *, expected_digest: Any, code: str) -> dict[str, Any]:
    if (
        type(value) is not str
        or type(expected_digest) is not str
        or not _HEX_64.fullmatch(expected_digest)
    ):
        _reject(code)
    try:
        payload = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        _reject(code)
    if type(payload) is not dict or _payload_sha256(payload) != expected_digest:
        _reject(code)
    return payload


def _project_rows(
    connection: sqlite3.Connection, account_key: str
) -> tuple[tuple[V21ActionRefRow, ...], int, int]:
    counter_row = connection.execute(
        "SELECT last_action_ref FROM ctp_native_action_ref_counters WHERE account_key = ?",
        (account_key,),
    ).fetchone()
    if counter_row is None:
        counter_high_water = 0
    else:
        counter_high_water = counter_row[0]
        if type(counter_high_water) is not int or not 0 <= counter_high_water <= _MAX_ACTION_REF:
            _reject("counter_value_invalid")

    command_rows = connection.execute(
        "SELECT * FROM ctp_dispatch_commands WHERE account_key = ? ORDER BY command_id",
        (account_key,),
    ).fetchall()
    commands: dict[str, sqlite3.Row] = {}
    for command in command_rows:
        command_id = _required_text(command, "command_id")
        commands[command_id] = command
        if type(command["correlation_version"]) is not int or command["correlation_version"] != 2:
            _reject("legacy_command_present")
        if command["operation"] not in {"SUBMIT", "CANCEL"}:
            _reject("command_operation_invalid")
        state = command["status"]
        if state == "UNKNOWN":
            _reject("unknown_action_present")
        if state not in _ALLOWED_STATES:
            _reject("command_state_invalid")
        if command["operation"] == "SUBMIT" and command["native_action_ref_int"] is not None:
            _reject("submit_action_ref_present")

    allocation_rows = connection.execute(
        "SELECT * FROM ctp_native_action_ref_allocations WHERE account_key = ? "
        "ORDER BY native_action_ref",
        (account_key,),
    ).fetchall()
    allocations_by_command: dict[str, sqlite3.Row] = {}
    action_refs: set[int] = set()
    projected: list[V21ActionRefRow] = []
    observed_high_water = 0

    for allocation in allocation_rows:
        action_ref = allocation["native_action_ref"]
        if type(action_ref) is not int or not 1 <= action_ref <= _MAX_ACTION_REF:
            _reject("allocation_action_ref_invalid")
        observed_high_water = max(observed_high_water, action_ref)
        if action_ref in action_refs:
            _reject("allocation_action_ref_duplicate")
        action_refs.add(action_ref)

        command_id = _required_text(allocation, "command_id")
        if command_id in allocations_by_command:
            _reject("allocation_command_duplicate")
        allocations_by_command[command_id] = allocation
        command = commands.get(command_id)
        if command is None:
            _reject("allocation_command_missing")
        if command["operation"] != "CANCEL":
            _reject("allocation_not_cancel")
        if command["native_action_ref_int"] != action_ref:
            _reject("command_action_ref_mismatch")
        if (
            _required_text(allocation, "scope_key") != command["scope_key"]
            or _required_text(allocation, "managed_action_id") != command["managed_action_id"]
        ):
            _reject("allocation_command_identity_mismatch")
        if command["order_ref"] is not None:
            _reject("cancel_order_ref_shape_invalid")

        logical = _load_json_object(
            command["request_payload_json"],
            expected_digest=command["request_payload_sha256"],
            code="logical_payload_invalid",
        )
        native = _load_json_object(
            command["native_request_payload_json"],
            expected_digest=command["native_request_payload_sha256"],
            code="native_payload_invalid",
        )
        if "OrderActionRef" in logical or native != dict(logical, OrderActionRef=action_ref):
            _reject("native_payload_action_ref_mismatch")

        account = _required_text(allocation, "account_key")
        scope_key = _required_text(command, "scope_key")
        managed_action_id = _required_text(command, "managed_action_id")
        managed_intent_id = _required_text(command, "reservation_managed_intent_id")
        reservation = connection.execute(
            "SELECT * FROM ctp_order_identity_reservations "
            "WHERE account_key = ? AND scope_key = ? AND managed_intent_id = ?",
            (account, scope_key, managed_intent_id),
        ).fetchone()
        if reservation is None:
            _reject("order_reservation_missing")
        trading_day = _required_text(command, "trading_day")
        order_ref = _required_text(command, "cancel_target_order_ref")
        runtime_order_id = _required_text(command, "runtime_order_id")
        if (
            _required_text(reservation, "trading_day") != trading_day
            or _required_text(reservation, "order_ref") != order_ref
            or _required_text(reservation, "runtime_order_id") != runtime_order_id
            or _required_text(reservation, "managed_intent_id") != managed_intent_id
            or not _ORDER_REF.fullmatch(order_ref)
            or not _RUNTIME_ORDER_ID.fullmatch(runtime_order_id)
        ):
            _reject("order_reservation_command_mismatch")
        if len(trading_day) != 8 or not trading_day.isascii() or not trading_day.isdigit():
            _reject("trading_day_invalid")
        if not _required_text(command, "scope_key") or not managed_action_id:
            _reject("row_identity_invalid")

        projected.append(
            V21ActionRefRow(
                account_key=account,
                trading_day=trading_day,
                scope_key=scope_key,
                managed_action_id=managed_action_id,
                managed_intent_id=managed_intent_id,
                runtime_order_id=runtime_order_id,
                order_ref=order_ref,
                native_action_ref=action_ref,
                command_id=command_id,
                state=str(command["status"]),
            )
        )

    for command in command_rows:
        command_id = str(command["command_id"])
        if command["operation"] == "CANCEL" and command_id not in allocations_by_command:
            _reject("cancel_allocation_missing")
        if command["operation"] == "SUBMIT" and command_id in allocations_by_command:
            _reject("submit_allocation_present")

    if allocation_rows and counter_row is None:
        _reject("counter_missing")
    if counter_high_water < observed_high_water:
        _reject("counter_below_allocations")
    if counter_high_water > observed_high_water:
        _reject("counter_ahead_of_allocations")
    projected.sort(key=lambda row: (row.native_action_ref, row.command_id))
    return tuple(projected), counter_high_water, observed_high_water


def project_v21_actionref_ledger(
    database_path: str | Path,
    *,
    account_key: str,
) -> V21ActionRefLedgerProjection:
    """Project V21 ActionRef allocations from an offline SQLite copy.

    The account key must be explicit. The function accepts only schema 21 and
    validates exact relevant columns, keys, indexes, and immutability triggers.
    It rejects legacy command rows and UNKNOWN actions rather than inferring
    lifecycle facts. The returned hashes establish byte consistency only.
    """

    if type(account_key) is not str or not re.fullmatch(
        r"account:[0-9a-f]{64}", account_key, re.ASCII
    ):
        _reject("account_key_invalid")
    try:
        path = Path(database_path).expanduser().resolve(strict=True)
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        raise ActionRefAuditError("database_path_invalid") from error
    if not path.is_file():
        _reject("database_path_invalid")

    before_digest = _source_bundle_sha256(path)
    if Path(str(path) + "-journal").is_file():
        _reject("database_rollback_journal_present")

    # SQLite may create or update WAL shared-memory files even for a read-only
    # connection. Work from a private snapshot so source-bundle byte stability
    # is meaningful and never depends on SQLite's sidecar housekeeping.
    try:
        with tempfile.TemporaryDirectory(prefix="v21-actionref-audit-") as scratch:
            snapshot = Path(scratch) / "source.sqlite3"
            shutil.copyfile(path, snapshot)
            source_wal = Path(str(path) + "-wal")
            if source_wal.is_file():
                shutil.copyfile(source_wal, Path(str(snapshot) + "-wal"))
            if _source_bundle_sha256(path) != before_digest:
                _reject("source_changed_during_snapshot")

            connection: sqlite3.Connection | None = None
            began = False
            try:
                uri = snapshot.resolve(strict=True).as_uri() + "?mode=ro"
                connection = sqlite3.connect(uri, uri=True, isolation_level=None, timeout=1.0)
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA query_only = ON")
                connection.execute("BEGIN")
                began = True
                integrity = connection.execute("PRAGMA quick_check").fetchone()
                if integrity is None or str(integrity[0]) != "ok":
                    _reject("database_integrity_check_failed")
                _verify_schema(connection)
                rows, counter_high_water, observed_high_water = _project_rows(
                    connection, account_key
                )
                projection_material = {
                    "schema": "iteration41.v21-actionref-projection.v1",
                    "account_key": account_key,
                    "schema_version": _SCHEMA_VERSION,
                    "counter_high_water": counter_high_water,
                    "observed_high_water": observed_high_water,
                    "rows": [row.to_payload() for row in rows],
                }
                projection_sha256 = _payload_sha256(projection_material)
            except ActionRefAuditError:
                raise
            except (sqlite3.Error, OSError, ValueError, TypeError) as error:
                raise ActionRefAuditError("database_read_failed") from error
            finally:
                if connection is not None:
                    if began:
                        with suppress(sqlite3.Error):
                            connection.execute("ROLLBACK")
                    connection.close()
    except ActionRefAuditError:
        raise
    except (OSError, sqlite3.Error, ValueError, TypeError) as error:
        raise ActionRefAuditError("database_snapshot_failed") from error

    after_digest = _source_bundle_sha256(path)
    if after_digest != before_digest:
        _reject("source_changed_during_read")
    return V21ActionRefLedgerProjection(
        account_key=account_key,
        schema_version=_SCHEMA_VERSION,
        rows=rows,
        counter_high_water=counter_high_water,
        observed_high_water=observed_high_water,
        projection_sha256=projection_sha256,
        source_bundle_sha256=before_digest,
    )


__all__ = [
    "ActionRefAuditError",
    "V21ActionRefLedgerProjection",
    "V21ActionRefRow",
    "project_v21_actionref_ledger",
]
