"""Small transactional helpers for finite logical journal-payload budgets.

The caller owns the journal schema migration and the surrounding SQLite
transaction.  Capacity usage is cumulative: inserts charge one record and its
canonical row bytes, while updates charge only positive byte growth.  Shrinks,
deletes, acknowledgements, and exact replays never return previously consumed
capacity.  These counters bound logical payload growth; they are not a physical
SQLite or WAL byte limit.
"""

from __future__ import annotations

import json
import math
import sqlite3
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Iterator, Optional, Tuple


_MAX_SQLITE_INTEGER = 9_223_372_036_854_775_807
_CAPACITY_CLASSES = ("BASE", "SETTLEMENT")
_USAGE_TABLE = "execution_durable_capacity_usage"
_ACTIVE_RECORDER: ContextVar[Optional["DurableCapacityRecorder"]] = ContextVar(
    "backtrader_durable_capacity_recorder", default=None
)

_DURABLE_ROW_KEYS = {
    "execution_decisions": ("decision_id",),
    "execution_decision_slots": ("intent_id",),
    "execution_run_order_budgets": ("account_scope", "strategy_scope", "logical_run_id"),
    "execution_run_loss_guards": ("account_scope", "strategy_scope", "logical_run_id"),
    "execution_grid_cursors": ("account_scope", "strategy_scope", "cohort_id"),
    "execution_grid_highwaters": ("account_scope", "strategy_scope"),
    "execution_fee_pair_required_scopes": ("account_scope", "strategy_scope"),
    "execution_fee_pair_scope_events": ("event_id",),
    "execution_fee_pair_candidates": ("candidate_id",),
    "execution_fee_pair_candidate_events": ("event_id",),
    "execution_fee_pair_candidate_capacity_reservations": ("candidate_id",),
    "execution_fee_pair_workflows": ("candidate_id",),
    "execution_fee_pair_workflow_events": ("event_id",),
    "execution_fee_pair_workflow_durable_reservations": ("candidate_id",),
    "execution_fee_pair_workflow_decision_reservations": ("candidate_id",),
    "execution_fee_pair_workflow_grid_settlements": ("candidate_id",),
    "execution_fee_pair_grid_single_row_tape_intents": ("candidate_id",),
    "execution_fee_pair_legacy_unresolved_v23": ("candidate_id",),
    "execution_fee_pair_amount_reservations": ("candidate_id",),
    "execution_fee_pair_amount_open_reservations": ("candidate_id",),
    "execution_fee_pair_amount_lifecycle_events": ("event_id",),
    "execution_fee_pair_amount_active_holds": ("account_scope",),
    "execution_source_highwaters": (
        "account_scope",
        "strategy_scope",
        "logical_run_id",
        "source_kind",
    ),
    "execution_decision_intents": ("intent_id",),
    "execution_native_intent_identities": ("intent_id",),
    "execution_known_ctp_order_sysid_bindings": ("intent_id",),
    "execution_registered_sim_cancel_dispatch_claims": ("cancel_intent_id",),
    "execution_registered_sim_cancel_dispatch_tombstones": ("cancel_intent_id",),
    "execution_decision_callbacks": ("receipt_id",),
    "execution_instrument_owners": ("account_scope", "instrument"),
    "execution_intent_resolutions": ("intent_id",),
    "execution_intent_reconciliations": ("reconciliation_id",),
    "execution_callback_query_dispositions": ("native_receipt_id",),
    "execution_intent_abandonments": ("abandonment_id",),
    "execution_slot_abandonments": ("abandonment_id",),
    "factor_position_grid_history": (
        "account_scope",
        "strategy_scope",
        "cohort_id",
        "ordinal",
    ),
    "factor_position_openings": ("intent_id",),
    "factor_position_fills": ("account_scope", "instrument", "exchange", "execution_id"),
    "factor_position_evidence_issues": ("receipt_id",),
    "factor_position_dated_trade_facts": (
        "account_scope",
        "instrument",
        "exchange",
        "execution_id",
    ),
    "factor_position_current": ("account_scope", "instrument", "exchange"),
    "factor_position_active_issues": ("account_scope", "instrument", "exchange_key"),
    "factor_position_fill_attributes": (
        "account_scope",
        "instrument",
        "exchange",
        "execution_id",
    ),
    "factor_position_open_intent_totals": ("intent_id",),
}

DEFAULT_MAX_DURABLE_BASE_RECORDS = 500_000
DEFAULT_MAX_DURABLE_BASE_BYTES = 1_073_741_824
DEFAULT_MAX_DURABLE_SETTLEMENT_RECORDS = 100_000
DEFAULT_MAX_DURABLE_SETTLEMENT_BYTES = 1_073_741_824


class DurableCapacityError(RuntimeError):
    """A malformed capacity contract or exhausted durable budget."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class DurableCapacityLimits:
    """Independent finite limits for cumulative BASE and SETTLEMENT payloads."""

    max_durable_base_records: int = DEFAULT_MAX_DURABLE_BASE_RECORDS
    max_durable_base_bytes: int = DEFAULT_MAX_DURABLE_BASE_BYTES
    max_durable_settlement_records: int = DEFAULT_MAX_DURABLE_SETTLEMENT_RECORDS
    max_durable_settlement_bytes: int = DEFAULT_MAX_DURABLE_SETTLEMENT_BYTES

    def __post_init__(self) -> None:
        for name, value in (
            ("max_durable_base_records", self.max_durable_base_records),
            ("max_durable_base_bytes", self.max_durable_base_bytes),
            ("max_durable_settlement_records", self.max_durable_settlement_records),
            ("max_durable_settlement_bytes", self.max_durable_settlement_bytes),
        ):
            if type(value) is not int or not 1 <= value <= _MAX_SQLITE_INTEGER:
                raise DurableCapacityError("INVALID_DURABLE_CAPACITY_LIMITS")


@dataclass(frozen=True)
class DurableCapacityCharge:
    """An aggregated positive usage delta for one journal transaction."""

    base_records: int = 0
    base_bytes: int = 0
    settlement_records: int = 0
    settlement_bytes: int = 0

    def __post_init__(self) -> None:
        for value in (
            self.base_records,
            self.base_bytes,
            self.settlement_records,
            self.settlement_bytes,
        ):
            if type(value) is not int or not 0 <= value <= _MAX_SQLITE_INTEGER:
                raise DurableCapacityError("INVALID_DURABLE_CAPACITY_CHARGE")

    @classmethod
    def for_row_change(
        cls,
        capacity_class: str,
        before: Optional[Any],
        after: Optional[Any],
    ) -> DurableCapacityCharge:
        """Measure one INSERT/UPDATE/DELETE without refunding prior usage.

        An INSERT charges one row and the new serialized size.  An UPDATE
        charges only the positive size difference.  A DELETE or a non-growing
        update charges zero.  Callers combine per-row results before writing
        the two aggregate usage rows.
        """

        if capacity_class not in _CAPACITY_CLASSES:
            raise DurableCapacityError("INVALID_DURABLE_CAPACITY_CLASS")
        records = 0
        byte_growth = 0
        if before is None and after is not None:
            records = 1
            byte_growth = len(canonical_sql_row_bytes(after))
        elif before is not None and after is not None:
            byte_growth = max(
                0,
                len(canonical_sql_row_bytes(after)) - len(canonical_sql_row_bytes(before)),
            )

        if capacity_class == "BASE":
            return cls(base_records=records, base_bytes=byte_growth)
        return cls(settlement_records=records, settlement_bytes=byte_growth)

    @classmethod
    def combine(cls, *charges: DurableCapacityCharge) -> DurableCapacityCharge:
        """Combine row changes so each capacity class is written at most once."""

        if any(not isinstance(charge, cls) for charge in charges):
            raise DurableCapacityError("INVALID_DURABLE_CAPACITY_CHARGE")
        return cls(
            base_records=sum(charge.base_records for charge in charges),
            base_bytes=sum(charge.base_bytes for charge in charges),
            settlement_records=sum(charge.settlement_records for charge in charges),
            settlement_bytes=sum(charge.settlement_bytes for charge in charges),
        )


@dataclass(frozen=True)
class DurableCapacityUsage:
    """Validated cumulative logical usage for both fixed capacity classes."""

    base_records: int
    base_bytes: int
    settlement_records: int
    settlement_bytes: int


class DurableCapacityRecorder:
    """Collect explicit row changes for one journal write transaction."""

    def __init__(self, connection: sqlite3.Connection, limits: DurableCapacityLimits) -> None:
        self.connection = connection
        self.limits = limits
        self.charge = DurableCapacityCharge()
        self.active = True

    def add(self, capacity_class: str, before: Any, after: Any) -> None:
        if not self.active:
            raise DurableCapacityError("DURABLE_CAPACITY_TRANSACTION_REQUIRED")
        self.charge = DurableCapacityCharge.combine(
            self.charge,
            DurableCapacityCharge.for_row_change(capacity_class, before, after),
        )


@contextmanager
def durable_capacity_transaction(
    cursor: sqlite3.Cursor, limits: DurableCapacityLimits
) -> Iterator[DurableCapacityRecorder]:
    """Bind a transaction-local recorder and charge its aggregate before commit."""

    if (
        not isinstance(cursor, sqlite3.Cursor)
        or not cursor.connection.in_transaction
        or not isinstance(limits, DurableCapacityLimits)
    ):
        raise DurableCapacityError("DURABLE_CAPACITY_TRANSACTION_REQUIRED")
    active = _ACTIVE_RECORDER.get()
    if active is not None and active.active and active.connection is cursor.connection:
        raise DurableCapacityError("DURABLE_CAPACITY_TRANSACTION_NESTED")
    recorder = DurableCapacityRecorder(cursor.connection, limits)
    token = _ACTIVE_RECORDER.set(recorder)
    try:
        yield recorder
        if recorder.charge != DurableCapacityCharge():
            charge_durable_capacity(cursor, limits, recorder.charge)
    finally:
        # Context copies retain the same recorder object even after this
        # context resets its own ContextVar token. Invalidate the object before
        # returning so a copied context cannot append an unflushed charge.
        recorder.active = False
        _ACTIVE_RECORDER.reset(token)


@contextmanager
def track_durable_row_change(
    cursor: sqlite3.Cursor,
    table: str,
    key_values: tuple[Any, ...],
    capacity_class: str,
) -> Iterator[None]:
    """Measure one explicit keyed payload-row write without parsing its SQL."""

    if not isinstance(cursor, sqlite3.Cursor) or not cursor.connection.in_transaction:
        raise DurableCapacityError("DURABLE_CAPACITY_TRANSACTION_REQUIRED")
    key_columns = _DURABLE_ROW_KEYS.get(table)
    if key_columns is None or len(key_values) != len(key_columns):
        raise DurableCapacityError("DURABLE_ROW_KEY_INVALID")
    if capacity_class not in _CAPACITY_CLASSES:
        raise DurableCapacityError("INVALID_DURABLE_CAPACITY_CLASS")
    recorder = _ACTIVE_RECORDER.get()
    if recorder is None or not recorder.active or recorder.connection is not cursor.connection:
        # Standalone position-book fixtures/databases have no journal budget.
        # A journal-owned v12 database must never let a book mutation bypass it.
        exists = cursor.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (_USAGE_TABLE,)
        ).fetchone()
        if exists is not None:
            raise DurableCapacityError("DURABLE_CAPACITY_TRANSACTION_REQUIRED")
        yield
        return

    predicate = " AND ".join("{}=?".format(column) for column in key_columns)

    def snapshot() -> Any:
        # Read through a separate cursor so this observation cannot replace
        # the caller's DML rowcount before its optimistic-concurrency check.
        read_cursor = cursor.connection.cursor()
        try:
            return read_cursor.execute(
                "SELECT * FROM {} WHERE {}".format(table, predicate), key_values
            ).fetchone()
        finally:
            read_cursor.close()

    before = snapshot()
    try:
        yield
    except BaseException:
        raise
    else:
        recorder.add(capacity_class, before, snapshot())


def canonical_sql_row_bytes(row: Any) -> bytes:
    """Serialize a SQLite row as deterministic, typed, strict UTF-8 JSON."""

    keys_method = getattr(row, "keys", None)
    if not callable(keys_method):
        raise DurableCapacityError("DURABLE_ROW_VALUE_INVALID")
    try:
        keys = list(keys_method())
        if any(type(key) is not str or not key for key in keys) or len(set(keys)) != len(keys):
            raise DurableCapacityError("DURABLE_ROW_VALUE_INVALID")
        encoded = {key: _canonical_sql_value(row[key]) for key in keys}
        payload = json.dumps(
            encoded,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    except DurableCapacityError:
        raise
    except (KeyError, TypeError, ValueError, OverflowError) as error:
        raise DurableCapacityError("DURABLE_ROW_VALUE_INVALID") from error
    return payload.encode("utf-8")


def _canonical_sql_value(value: Any) -> dict[str, Any]:
    if value is None:
        return {"type": "null"}
    if type(value) is int:
        if not -_MAX_SQLITE_INTEGER - 1 <= value <= _MAX_SQLITE_INTEGER:
            raise DurableCapacityError("DURABLE_ROW_VALUE_INVALID")
        return {"type": "integer", "value": value}
    if type(value) is float:
        if not math.isfinite(value):
            raise DurableCapacityError("DURABLE_ROW_VALUE_INVALID")
        return {"type": "real", "value": value.hex()}
    if type(value) is str:
        return {"type": "text", "value": value}
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"type": "blob", "value": bytes(value).hex()}
    raise DurableCapacityError("DURABLE_ROW_VALUE_INVALID")


def ensure_durable_capacity_usage_schema(cursor: sqlite3.Cursor) -> None:
    """Create the fixed two-row cumulative usage table if absent.

    Schema-version migration and configuration persistence belong to the
    journal owner.  This helper initializes rows only when creating the table;
    an existing incomplete or duplicated ledger is never repaired.
    """

    if not isinstance(cursor, sqlite3.Cursor):
        raise DurableCapacityError("DURABLE_CAPACITY_CURSOR_INVALID")
    try:
        existing = cursor.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (_USAGE_TABLE,)
        ).fetchone()
        if existing is None:
            if not cursor.connection.in_transaction:
                raise DurableCapacityError("DURABLE_CAPACITY_TRANSACTION_REQUIRED")
            cursor.execute(
                f"""CREATE TABLE {_USAGE_TABLE} (
                    capacity_class TEXT PRIMARY KEY
                        CHECK(capacity_class IN ('BASE','SETTLEMENT')),
                    record_count INTEGER NOT NULL CHECK(record_count >= 0),
                    payload_bytes INTEGER NOT NULL CHECK(payload_bytes >= 0)
                )"""
            )
            cursor.executemany(
                f"""INSERT INTO {_USAGE_TABLE}
                    (capacity_class,record_count,payload_bytes) VALUES(?,0,0)""",
                ((capacity_class,) for capacity_class in _CAPACITY_CLASSES),
            )
        else:
            # A reopen validates historical usage; it never fills in missing
            # class rows with zero and thereby erases prior capacity history.
            read_durable_capacity_usage(cursor)
    except DurableCapacityError:
        raise
    except sqlite3.Error as error:
        raise DurableCapacityError("DURABLE_CAPACITY_SCHEMA_INVALID") from error
    if existing is None:
        read_durable_capacity_usage(cursor)


def read_durable_capacity_usage(cursor: sqlite3.Cursor) -> DurableCapacityUsage:
    """Return usage only when the ledger has exactly two valid class rows."""

    try:
        rows = cursor.execute(
            f"SELECT capacity_class,record_count,payload_bytes FROM {_USAGE_TABLE}"
        ).fetchall()
    except sqlite3.Error as error:
        raise DurableCapacityError("DURABLE_CAPACITY_USAGE_UNAVAILABLE") from error
    usage: dict[str, tuple[int, int]] = {}
    for row in rows:
        capacity_class, records, payload_bytes = row[0], row[1], row[2]
        if (
            capacity_class not in _CAPACITY_CLASSES
            or capacity_class in usage
            or type(records) is not int
            or type(payload_bytes) is not int
            or not 0 <= records <= _MAX_SQLITE_INTEGER
            or not 0 <= payload_bytes <= _MAX_SQLITE_INTEGER
        ):
            raise DurableCapacityError("DURABLE_CAPACITY_USAGE_INVALID")
        usage[capacity_class] = (records, payload_bytes)
    if set(usage) != set(_CAPACITY_CLASSES):
        raise DurableCapacityError("DURABLE_CAPACITY_USAGE_UNAVAILABLE")
    return DurableCapacityUsage(
        base_records=usage["BASE"][0],
        base_bytes=usage["BASE"][1],
        settlement_records=usage["SETTLEMENT"][0],
        settlement_bytes=usage["SETTLEMENT"][1],
    )


def read_durable_capacity_reservations(cursor: sqlite3.Cursor) -> Tuple[int, int]:
    """Return outstanding BASE reservations across the v16 and v17 ledgers."""

    records = 0
    payload_bytes = 0
    tables = (
        ("execution_fee_pair_candidate_capacity_reservations", "RESERVED", "CONSUMED"),
        ("execution_fee_pair_workflow_durable_reservations", "ACTIVE", "CONSUMED"),
    )
    for table, active_state, consumed_state in tables:
        exists = cursor.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        if exists is None:
            continue
        try:
            rows = cursor.execute(
                """SELECT capacity_class,reserved_records,reserved_bytes,state
                   FROM {}""".format(table)
            ).fetchall()
        except sqlite3.Error as error:
            raise DurableCapacityError("DURABLE_CAPACITY_RESERVATION_INVALID") from error
        for capacity_class, row_records, row_bytes, state in rows:
            active_invalid = state == active_state and (
                type(row_records) is not int
                or type(row_bytes) is not int
                or row_records <= 0
                or row_bytes <= 0
            )
            if (
                capacity_class != "BASE"
                or type(row_records) is not int
                or type(row_bytes) is not int
                or row_records < 0
                or row_bytes < 0
                or active_invalid
                or (state == consumed_state and (row_records != 0 or row_bytes != 0))
                or state not in (active_state, consumed_state)
                or (table.endswith("candidate_capacity_reservations")
                    and state == active_state and row_records != 1)
            ):
                raise DurableCapacityError("DURABLE_CAPACITY_RESERVATION_INVALID")
            records += row_records
            payload_bytes += row_bytes
            if records > _MAX_SQLITE_INTEGER or payload_bytes > _MAX_SQLITE_INTEGER:
                raise DurableCapacityError("DURABLE_CAPACITY_RESERVATION_INVALID")
    return (records, payload_bytes)


def charge_durable_capacity(
    cursor: sqlite3.Cursor,
    limits: DurableCapacityLimits,
    charge: DurableCapacityCharge,
) -> DurableCapacityUsage:
    """Atomically add a bounded delta inside the caller's write transaction.

    All four caps are checked before either usage row is updated, so a
    rejected combined delta leaves the usage ledger unchanged.  Callers should
    compute and charge the aggregate before mutating payload rows, in the same
    ``BEGIN IMMEDIATE`` transaction; then a rejection can roll back the whole
    business operation without partial accounting.
    """

    if not isinstance(cursor, sqlite3.Cursor):
        raise DurableCapacityError("DURABLE_CAPACITY_CURSOR_INVALID")
    if not isinstance(limits, DurableCapacityLimits):
        raise DurableCapacityError("INVALID_DURABLE_CAPACITY_LIMITS")
    if not isinstance(charge, DurableCapacityCharge):
        raise DurableCapacityError("INVALID_DURABLE_CAPACITY_CHARGE")
    if not cursor.connection.in_transaction:
        raise DurableCapacityError("DURABLE_CAPACITY_TRANSACTION_REQUIRED")

    current = read_durable_capacity_usage(cursor)
    reserved_base_records, reserved_base_bytes = read_durable_capacity_reservations(cursor)
    requested = (
        (
            "BASE",
            current.base_records,
            current.base_bytes,
            reserved_base_records,
            reserved_base_bytes,
            charge.base_records,
            charge.base_bytes,
            limits.max_durable_base_records,
            limits.max_durable_base_bytes,
        ),
        (
            "SETTLEMENT",
            current.settlement_records,
            current.settlement_bytes,
            0,
            0,
            charge.settlement_records,
            charge.settlement_bytes,
            limits.max_durable_settlement_records,
            limits.max_durable_settlement_bytes,
        ),
    )
    updated: dict[str, tuple[int, int]] = {}
    for (
        capacity_class,
        records,
        payload_bytes,
        reserved_records,
        reserved_bytes,
        record_delta,
        byte_delta,
        record_limit,
        byte_limit,
    ) in requested:
        if record_delta == 0 and byte_delta == 0:
            updated[capacity_class] = (records, payload_bytes)
            continue
        if record_delta > record_limit - records - reserved_records:
            raise DurableCapacityError(f"DURABLE_{capacity_class}_RECORDS_EXHAUSTED")
        if byte_delta > byte_limit - payload_bytes - reserved_bytes:
            raise DurableCapacityError(f"DURABLE_{capacity_class}_BYTES_EXHAUSTED")
        updated[capacity_class] = (records + record_delta, payload_bytes + byte_delta)

    try:
        for capacity_class in _CAPACITY_CLASSES:
            record_delta = (
                charge.base_records if capacity_class == "BASE" else charge.settlement_records
            )
            byte_delta = charge.base_bytes if capacity_class == "BASE" else charge.settlement_bytes
            if record_delta == 0 and byte_delta == 0:
                continue
            cursor.execute(
                f"""UPDATE {_USAGE_TABLE}
                    SET record_count=?,payload_bytes=? WHERE capacity_class=?""",
                (*updated[capacity_class], capacity_class),
            )
            if cursor.rowcount != 1:
                raise DurableCapacityError("DURABLE_CAPACITY_USAGE_UNAVAILABLE")
    except sqlite3.Error as error:
        raise DurableCapacityError("DURABLE_CAPACITY_USAGE_UPDATE_FAILED") from error
    return DurableCapacityUsage(
        base_records=updated["BASE"][0],
        base_bytes=updated["BASE"][1],
        settlement_records=updated["SETTLEMENT"][0],
        settlement_bytes=updated["SETTLEMENT"][1],
    )


__all__ = [
    "DEFAULT_MAX_DURABLE_BASE_BYTES",
    "DEFAULT_MAX_DURABLE_BASE_RECORDS",
    "DEFAULT_MAX_DURABLE_SETTLEMENT_BYTES",
    "DEFAULT_MAX_DURABLE_SETTLEMENT_RECORDS",
    "DurableCapacityCharge",
    "DurableCapacityError",
    "DurableCapacityLimits",
    "DurableCapacityUsage",
    "canonical_sql_row_bytes",
    "charge_durable_capacity",
    "durable_capacity_transaction",
    "ensure_durable_capacity_usage_schema",
    "read_durable_capacity_usage",
    "read_durable_capacity_reservations",
    "track_durable_row_change",
]
