"""Durable, route-neutral decision and dispatch evidence for ordinary Strategies.

This journal binds a Strategy's economic decision to immutable business and
intent keys before a caller invokes a Broker/Store.  A dispatch claim is a
one-way PREPARED -> DISPATCHING transition.  If a process dies after the claim,
the next process can inspect the original Backtrader/provider identities, but
cannot claim the same intent for dispatch again.  This deliberately chooses
at-most-once dispatch over a blind retry when the network outcome is uncertain.

Callbacks are stored as deduplicated evidence and delivered at least once until
acknowledged.  A caller may attach a same-transaction projection for narrow,
source-owned evidence such as factor-position attribution; it does not replace
the selected execution route's authoritative fills, commissions, cash, or
balances.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import time
import uuid
from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import MappingProxyType
from threading import Lock, RLock
from typing import Any, Callable, Iterator, Optional, Tuple, Union

from .execution_journal_archive import (
    DEFAULT_ARCHIVE_TIMEOUT_SECONDS,
    ExecutionJournalArchiveError,
    ExecutionJournalArchiveReceipt,
    create_verified_execution_journal_archive,
    validate_archive_timeout,
)
from .execution_dispatch_gate import (
    ExecutionDispatchGateError,
    ExecutionDispatchGateLease,
    acquire_dispatch_gate,
    dispatch_gate_path,
    validate_dispatch_gate_timeout,
)
from .execution_durable_capacity import (
    DEFAULT_MAX_DURABLE_BASE_BYTES,
    DEFAULT_MAX_DURABLE_BASE_RECORDS,
    DEFAULT_MAX_DURABLE_SETTLEMENT_BYTES,
    DEFAULT_MAX_DURABLE_SETTLEMENT_RECORDS,
    DurableCapacityError,
    DurableCapacityLimits,
    DurableCapacityUsage,
    canonical_sql_row_bytes,
    durable_capacity_transaction,
    ensure_durable_capacity_usage_schema,
    read_durable_capacity_usage,
    track_durable_row_change,
)


_ECONOMIC_DECIMAL_FIELDS = frozenset(
    {
        "average_cost",
        "average_price",
        "amount",
        "cash",
        "commission",
        "cumulative_commission",
        "filled_quantity",
        "fee",
        "limit_price",
        "margin",
        "notional",
        "position",
        "price",
        "quantity",
        "qty",
        "size",
        "stop_price",
        "trigger_price",
        "unrealized_pnl",
        "realized_pnl",
        "value",
        "volume",
    }
)
_RFC3339_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$"
)
_RUN_ORDER_RESERVATION_FIELD = "_journal_run_order_reservation"
_DISPATCHING_CRASH_NO_FILL_OUTCOME = "complete_orders_query_dispatching_no_fill_terminal"
_DISPATCHING_CANCEL_CHILD_OUTCOME = "complete_orders_query_cancel_dispatching_terminal"
_DISPATCHING_CANCEL_PARENT_OUTCOME = "complete_orders_query_terminal"
_CALLBACK_QUERY_DISPOSITION = "QUERY_MATCHED_BROKER_ACK_UNOBSERVED_AFTER_RESTART"
# Shared by journal instances in this OS process, so reopening the same SQLite
# file does not masquerade as a process restart. PID distinguishes a POSIX fork
# that inherited this module constant; Windows spawn imports a fresh value.
_PROCESS_INSTANCE_NONCE = uuid.uuid4().hex


def _current_process_instance_id() -> str:
    return "{}:{}".format(os.getpid(), _PROCESS_INSTANCE_NONCE)


class ExecutionDecisionJournalError(RuntimeError):
    """A durable decision or execution-evidence operation failed closed."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ExecutionDecisionKey:
    """Stable business identity for one close-time Strategy decision."""

    account_scope: str
    strategy_scope: str
    logical_run_id: str
    cohort_id: str
    close_time: str
    decision_kind: str

    def __post_init__(self) -> None:
        for name, value in (
            ("account_scope", self.account_scope),
            ("strategy_scope", self.strategy_scope),
            ("logical_run_id", self.logical_run_id),
            ("cohort_id", self.cohort_id),
            ("decision_kind", self.decision_kind),
        ):
            if not _identifier(value):
                raise ExecutionDecisionJournalError("INVALID_DECISION_KEY")
        object.__setattr__(self, "close_time", _normalize_close_time(self.close_time))


@dataclass(frozen=True)
class ExecutionIntentKey:
    """Stable identity for one serialized submit or cancel leg in a decision."""

    action: str
    instrument: str
    side: str
    position_effect: str
    leg: int

    def __post_init__(self) -> None:
        if (
            self.action not in ("SUBMIT", "CANCEL")
            or self.side not in ("BUY", "SELL")
            or not _identifier(self.instrument)
            or not _identifier(self.position_effect)
            or type(self.leg) is not int
            or self.leg < 0
        ):
            raise ExecutionDecisionJournalError("INVALID_INTENT_KEY")


@dataclass(frozen=True)
class ExecutionDecisionRecord:
    decision_id: str
    key: ExecutionDecisionKey
    economic_payload: Mapping[str, Any]
    intent_keys: Tuple[ExecutionIntentKey, ...]
    created_at_ns: int

    @property
    def is_noop(self) -> bool:
        """Whether this immutable decision explicitly declared no intents."""

        return not self.intent_keys


@dataclass(frozen=True)
class ExecutionDecisionCapacitySnapshot:
    """Read-only decision high-water usage and current SQLite footprint.

    Payload-byte counters cover the canonical decision key, economics, and
    ordered intent-key JSON stored for each decision.  Database/WAL byte
    fields report the current physical footprint separately; they are
    diagnostics, not a hard cap on every journal table or SQLite allocation.
    """

    base_record_count: int
    base_record_limit: int
    base_payload_bytes: int
    base_payload_byte_limit: int
    settlement_record_count: int
    settlement_record_limit: int
    settlement_payload_bytes: int
    settlement_payload_byte_limit: int
    database_bytes: int
    wal_bytes: int

    @property
    def physical_bytes(self) -> int:
        return self.database_bytes + self.wal_bytes


@dataclass(frozen=True)
class ExecutionIntentRecord:
    intent_id: str
    decision_id: str
    key: ExecutionIntentKey
    economic_payload: Mapping[str, Any]
    original_identity: Mapping[str, Any]
    owner_intent_id: Optional[str]
    state: str
    dispatch_state: Optional[str]
    provider_identity: Optional[Mapping[str, Any]]
    outcome_code: Optional[str]
    created_at_ns: int
    updated_at_ns: int


@dataclass(frozen=True)
class ExecutionDispatchClaim:
    """One durable, single-use permission to invoke the route for an intent."""

    intent: ExecutionIntentRecord


@dataclass(frozen=True)
class ExecutionCallbackReceipt:
    receipt_id: str
    intent_id: str
    callback_id: str
    evidence_payload: Mapping[str, Any]
    acknowledged: bool
    created_at_ns: int
    is_new: bool = False


@dataclass(frozen=True)
class ExecutionCallbackQueryDisposition:
    """Exact query evidence that supersedes delivery of one unacknowledged callback."""

    native_receipt_id: str
    query_receipt_id: str
    intent_id: str
    execution_id: str
    disposition_code: str
    query_process_instance_id: Optional[str]
    proof_payload: Mapping[str, Any]
    proof_sha256: str
    created_at_ns: int


@dataclass(frozen=True)
class ExecutionInstrumentOwner:
    account_scope: str
    instrument: str
    intent_id: str
    state: str
    cancel_intent_id: Optional[str]


@dataclass(frozen=True)
class ExecutionInstrumentResolution:
    intent_id: str
    account_scope: str
    instrument: str
    terminal_state: str
    terminal_event_id: str
    reconciliation_id: str
    position_snapshot_id: str
    position_flat: bool
    created_at_ns: int


@dataclass(frozen=True)
class ExecutionIntentReconciliation:
    """Append-only query evidence for one already-claimed route intent.

    ``original_identity`` binds the query result to the immutable caller-side
    order and client identifiers.  The record describes observations only; it
    never applies fills, fees, balances, or positions.
    """

    reconciliation_id: str
    intent_id: str
    original_identity: Mapping[str, Any]
    query_id: str
    state: str
    provider_identity: Mapping[str, Any]
    outcome_code: Optional[str]
    terminal_state: Optional[str]
    terminal_event_id: Optional[str]
    position_snapshot_id: Optional[str]
    position_flat: Optional[bool]
    created_at_ns: int


@dataclass(frozen=True)
class ExecutionIntentAbandonment:
    """Terminal evidence that a PREPARED intent was discarded before dispatch."""

    abandonment_id: str
    intent_id: str
    reason_code: str
    created_at_ns: int


@dataclass(frozen=True)
class ExecutionGridCursor:
    """Durable progress for one Strategy cohort's eligible input grids."""

    account_scope: str
    strategy_scope: str
    cohort_id: str
    ordinal: int
    epoch_id: str
    batch_id: str
    close_time: str
    decision_id: str
    updated_at_ns: int


@dataclass(frozen=True)
class ExecutionGridDecision:
    """Result of atomically persisting a decision and advancing its grid."""

    decision: Optional[ExecutionDecisionRecord]
    cursor: Optional[ExecutionGridCursor]
    eligible: bool
    is_new_grid: bool


@dataclass(frozen=True)
class ExecutionIntentSnapshotPage:
    """Bounded immutable projection of intents that can affect execution.

    The page includes all unresolved intents and KNOWN intents that still own
    an account/instrument dispatch slot. Position holdings are projected by
    ``factor_position_book`` separately; a KNOWN OPEN whose order slot has
    been reconciled does not appear here merely because a holding exists.
    """

    items: Tuple[ExecutionIntentRecord, ...]
    truncated: bool


@dataclass(frozen=True)
class ExecutionCallbackProjectionStatus:
    """Read-only projection state for one exact callback receipt."""

    status: str
    receipt_id: Optional[str] = None
    blocker_code: Optional[str] = None


class ExecutionDecisionJournal:
    """SQLite ledger for immutable decisions, dispatch claims and callback work.

    The journal is safe for multiple threads and SQLite serializes writers across
    connections.  ``max_pending_intents`` bounds unprepared, PREPARED,
    DISPATCHING and UNKNOWN intent slots.  ``max_pending_callbacks`` bounds
    unacknowledged callback receipts.  Reads of pending callbacks require a
    bounded limit.  Any SQLite write error latches this instance closed for
    further writes, so callers cannot accidentally proceed to a route after a
    failed persistence step.
    """

    _SCHEMA_VERSION = 12
    _NATIVE_IDENTITY_SCHEMA_VERSION = 8
    _DECISION_CAPACITY_SCHEMA_VERSION = 9

    def __init__(
        self,
        database_path: Union[str, Path],
        *,
        max_pending_intents: int = 1024,
        max_pending_callbacks: int = 4096,
        max_payload_bytes: int = 65536,
        max_decision_records: int = 100000,
        settlement_decision_reserve_records: int = 4096,
        max_decision_bytes: int = 536870912,
        settlement_decision_reserve_bytes: int = 67108864,
        max_durable_base_records: int = DEFAULT_MAX_DURABLE_BASE_RECORDS,
        max_durable_base_bytes: int = DEFAULT_MAX_DURABLE_BASE_BYTES,
        max_durable_settlement_records: int = DEFAULT_MAX_DURABLE_SETTLEMENT_RECORDS,
        max_durable_settlement_bytes: int = DEFAULT_MAX_DURABLE_SETTLEMENT_BYTES,
    ) -> None:
        if (
            type(max_pending_intents) is not int
            or max_pending_intents < 1
            or type(max_pending_callbacks) is not int
            or max_pending_callbacks < 1
            or type(max_payload_bytes) is not int
            or max_payload_bytes < 256
            or type(max_decision_records) is not int
            or max_decision_records < 1
            or type(settlement_decision_reserve_records) is not int
            or settlement_decision_reserve_records < 1
            or type(max_decision_bytes) is not int
            or max_decision_bytes < 1024
            or type(settlement_decision_reserve_bytes) is not int
            or settlement_decision_reserve_bytes < 1024
        ):
            raise ExecutionDecisionJournalError("INVALID_JOURNAL_LIMIT")
        self.max_pending_intents = max_pending_intents
        self.max_pending_callbacks = max_pending_callbacks
        self.max_payload_bytes = max_payload_bytes
        self.max_decision_records = max_decision_records
        self.settlement_decision_reserve_records = settlement_decision_reserve_records
        self.max_decision_bytes = max_decision_bytes
        self.settlement_decision_reserve_bytes = settlement_decision_reserve_bytes
        try:
            self.durable_capacity_limits = DurableCapacityLimits(
                max_durable_base_records=max_durable_base_records,
                max_durable_base_bytes=max_durable_base_bytes,
                max_durable_settlement_records=max_durable_settlement_records,
                max_durable_settlement_bytes=max_durable_settlement_bytes,
            )
        except DurableCapacityError as error:
            raise ExecutionDecisionJournalError(error.code) from error
        self._lock = RLock()
        # Dispatch serialization is deliberately non-reentrant. The file
        # sidecar already rejects nested acquisition; keep the in-memory
        # branch's contract identical instead of letting an RLock create a
        # second dispatch scope on the same journal instance.
        self._dispatch_lock = Lock()
        self._retained_dispatch_gate_context = None
        self._failed_closed = False
        self._closed = False

        if str(database_path) == ":memory:":
            self.path = ":memory:"
            connect_path = ":memory:"
        else:
            path = Path(database_path).expanduser().resolve(strict=False)
            path.parent.mkdir(parents=True, exist_ok=True)
            self.path = path
            connect_path = str(path)
        try:
            self._connection = sqlite3.connect(
                connect_path, isolation_level=None, check_same_thread=False
            )
            self._connection.row_factory = sqlite3.Row
            self._connection.create_function("sha256_text", 1, _sha256_text, deterministic=True)
            self._connection.execute("PRAGMA busy_timeout = 5000")
            if connect_path != ":memory:":
                self._connection.execute("PRAGMA journal_mode = WAL")
            self._connection.execute("PRAGMA synchronous = FULL")
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._create_schema()
        except ExecutionDecisionJournalError:
            connection = getattr(self, "_connection", None)
            if connection is not None:
                connection.close()
                self._closed = True
            raise
        except (OSError, sqlite3.Error) as error:
            connection = getattr(self, "_connection", None)
            if connection is not None:
                connection.close()
                self._closed = True
            raise ExecutionDecisionJournalError("JOURNAL_UNAVAILABLE") from error

    def __enter__(self) -> "ExecutionDecisionJournal":
        self._ensure_open()
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        self.close()

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                retained_gate = self._retained_dispatch_gate_context
                self._retained_dispatch_gate_context = None
                if retained_gate is not None:
                    retained_gate.__exit__(None, None, None)
                self._connection.close()
                self._closed = True

    def _retain_dispatch_serialization_gate(self, gate_context: Any) -> None:
        """Keep an unresolved same-process claim fenced until journal close.

        A claimed dispatch whose result could not be persisted is not a process
        crash merely because its Strategy scope ended. Retaining the already
        acquired sidecar makes same-process recovery fail closed; process death
        still releases the OS lock automatically.
        """

        if self._retained_dispatch_gate_context is not None:
            raise ExecutionDecisionJournalError("DISPATCH_GATE_ALREADY_RETAINED")
        self._retained_dispatch_gate_context = gate_context

    @property
    def dispatch_serialization_path(self) -> Optional[Path]:
        """Canonical sidecar path used to serialize dispatch and recovery."""

        if self.path == ":memory:":
            return None
        return dispatch_gate_path(self.path)

    @contextmanager
    def dispatch_serialization_gate(
        self, *, timeout_seconds: float = 5.0, recovery: bool = False
    ) -> Iterator[ExecutionDispatchGateLease]:
        """Serialize a complete prepare/claim/provider/result interval.

        File-backed journals use a same-directory SQLite sidecar EXCLUSIVE
        lock, which is released by the OS on process death. The lock is
        separate from the journal DB so nested journal transactions remain
        available while the dispatch interval is held. In-memory journals
        have only a bounded per-instance thread lock and may not be used for
        process-crash recovery.
        """

        try:
            timeout = validate_dispatch_gate_timeout(timeout_seconds)
        except ExecutionDispatchGateError as error:
            raise ExecutionDecisionJournalError(error.code) from error
        if type(recovery) is not bool:
            raise ExecutionDecisionJournalError("INVALID_DISPATCH_GATE_RECOVERY_FLAG")
        deadline = time.monotonic() + timeout
        if not self._dispatch_lock.acquire(timeout=timeout):
            raise ExecutionDecisionJournalError("DISPATCH_SERIALIZATION_BUSY")
        dispatch_lock_acquired = True
        journal_lock_acquired = False
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not self._lock.acquire(timeout=remaining):
                raise ExecutionDecisionJournalError("DISPATCH_SERIALIZATION_BUSY")
            journal_lock_acquired = True
            self._ensure_writable()
            if self._connection.in_transaction:
                raise ExecutionDecisionJournalError("JOURNAL_TRANSACTION_ACTIVE")
            if self.path == ":memory:":
                if recovery:
                    raise ExecutionDecisionJournalError(
                        "DISPATCH_RECOVERY_REQUIRES_DURABLE_JOURNAL"
                    )
                yield ExecutionDispatchGateLease(cross_process=False)
                return

            remaining = deadline - time.monotonic()
            if remaining < 0.001:
                raise ExecutionDecisionJournalError("DISPATCH_SERIALIZATION_BUSY")
            gate_context = acquire_dispatch_gate(self.path, timeout_seconds=remaining)
            try:
                lease = gate_context.__enter__()
            except ExecutionDispatchGateError as error:
                raise ExecutionDecisionJournalError(error.code) from error
            try:
                yield lease
            finally:
                gate_context.__exit__(None, None, None)
        finally:
            if journal_lock_acquired:
                self._lock.release()
            if dispatch_lock_acquired:
                self._dispatch_lock.release()

    def archive_snapshot(
        self,
        destination: Union[str, Path],
        *,
        timeout_seconds: float = DEFAULT_ARCHIVE_TIMEOUT_SECONDS,
    ) -> ExecutionJournalArchiveReceipt:
        """Create a complete verified SQLite snapshot without changing this journal.

        The exclusive lock wait and SQLite online backup share a cooperative
        deadline checked between operations; one native SQLite or filesystem
        call cannot be interrupted. This is an audit snapshot only: it does not
        reset capacity, release owners, rotate the active database, or remove
        UNKNOWN intents.
        """

        try:
            timeout = validate_archive_timeout(timeout_seconds)
        except ExecutionJournalArchiveError as error:
            raise ExecutionDecisionJournalError(error.code) from error
        deadline = time.monotonic() + timeout
        if not self._lock.acquire(timeout=timeout):
            raise ExecutionDecisionJournalError("ARCHIVE_LOCK_TIMEOUT")
        try:
            self._ensure_open()
            if self._connection.in_transaction:
                raise ExecutionDecisionJournalError("ARCHIVE_SOURCE_TRANSACTION_ACTIVE")
            remaining = deadline - time.monotonic()
            if remaining < 0.001:
                raise ExecutionDecisionJournalError("ARCHIVE_DEADLINE_EXCEEDED")
            try:
                return create_verified_execution_journal_archive(
                    self._connection,
                    destination,
                    expected_schema_version=self._SCHEMA_VERSION,
                    timeout_seconds=remaining,
                    source_path=self.path,
                )
            except ExecutionJournalArchiveError as error:
                raise ExecutionDecisionJournalError(error.code) from error
        finally:
            self._lock.release()

    def record_decision(
        self,
        key: ExecutionDecisionKey,
        economic_payload: Mapping[str, Any],
        *,
        intent_keys: Tuple[ExecutionIntentKey, ...] = (),
    ) -> ExecutionDecisionRecord:
        """Persist one decision, including an explicit no-op when keys are empty.

        Repeating the same business key with the same canonical economics and
        ordered intent keys returns the existing record.  Any changed economics
        or intent set raises ``DECISION_CONFLICT``.
        """

        if not isinstance(key, ExecutionDecisionKey):
            raise ExecutionDecisionJournalError("INVALID_DECISION_KEY")
        payload_json = self._payload_json(economic_payload)
        normalized_keys = _normalize_intent_keys(intent_keys, self.max_pending_intents)
        keys_json = _canonical_json([_intent_key_values(item) for item in normalized_keys])
        key_json = _canonical_json(_decision_key_values(key))
        decision_id = _stable_id("decision", key_json)
        now_ns = time.time_ns()

        with self._transaction() as cursor:
            record, _created = self._record_decision_in_transaction(
                cursor,
                decision_id=decision_id,
                key_json=key_json,
                payload_json=payload_json,
                keys_json=keys_json,
                normalized_keys=normalized_keys,
                now_ns=now_ns,
            )
            return record

    def record_grid_decision(
        self,
        key: ExecutionDecisionKey,
        economic_payload: Mapping[str, Any],
        *,
        intent_keys: Tuple[ExecutionIntentKey, ...] = (),
        epoch_id: str,
        batch_id: str,
        eligible: bool,
        complete: bool,
        live_ready: bool,
        inputs_complete: bool,
        max_order_intents_per_run: Optional[int] = None,
        expected_run_order_intents_used: Optional[int] = None,
        remaining_exit_intent_reserve: Optional[int] = None,
    ) -> ExecutionGridDecision:
        """Persist one eligible decision and advance its cohort cursor atomically.

        The cohort cursor preserves epoch-local ordinals. A second durable
        highwater keyed by account and stable strategy scope prevents a new
        cohort, run, mode, or configuration from admitting an already-consumed
        close time. An exact immutable decision replay returns its prior
        decision with ``is_new_grid=False`` without rewinding either cursor.
        Ineligible, incomplete, not-live-ready, or missing-input batches do not
        write a decision row or advance either cursor. When a run limit is configured,
        new decisions also require the caller's expected durable usage and the
        post-plan exit reserve. The compare-and-swap, reservation, decision,
        and cursor update commit together.
        """

        if not isinstance(key, ExecutionDecisionKey):
            raise ExecutionDecisionJournalError("INVALID_DECISION_KEY")
        _require_identifier(epoch_id, "INVALID_GRID_EPOCH")
        _require_identifier(batch_id, "INVALID_GRID_BATCH")
        flags = (eligible, complete, live_ready, inputs_complete)
        if any(type(flag) is not bool for flag in flags):
            raise ExecutionDecisionJournalError("INVALID_GRID_ELIGIBILITY")
        if max_order_intents_per_run is not None and (
            type(max_order_intents_per_run) is not int or max_order_intents_per_run < 0
        ):
            raise ExecutionDecisionJournalError("INVALID_RUN_ORDER_BUDGET")
        self._validate_run_order_reservation(
            max_order_intents_per_run=max_order_intents_per_run,
            expected_run_order_intents_used=expected_run_order_intents_used,
            remaining_exit_intent_reserve=remaining_exit_intent_reserve,
        )
        if not all(flags):
            return ExecutionGridDecision(
                decision=None,
                cursor=self.grid_cursor(key.account_scope, key.strategy_scope, key.cohort_id),
                eligible=False,
                is_new_grid=False,
            )

        payload_json, replay_payload_json, reservation = self._budgeted_payload_json(
            economic_payload,
            max_order_intents_per_run=max_order_intents_per_run,
            remaining_exit_intent_reserve=remaining_exit_intent_reserve,
        )
        normalized_keys = _normalize_intent_keys(intent_keys, self.max_pending_intents)
        keys_json = _canonical_json([_intent_key_values(item) for item in normalized_keys])
        key_json = _canonical_json(_decision_key_values(key))
        decision_id = _stable_id("decision", key_json)
        now_ns = time.time_ns()
        cursor_key = (key.account_scope, key.strategy_scope, key.cohort_id)

        with self._transaction() as db_cursor:
            decision, created = self._record_decision_in_transaction(
                db_cursor,
                decision_id=decision_id,
                key_json=key_json,
                payload_json=payload_json,
                replay_payload_json=replay_payload_json,
                run_order_reservation=reservation,
                keys_json=keys_json,
                normalized_keys=normalized_keys,
                now_ns=now_ns,
            )
            current = db_cursor.execute(
                """SELECT * FROM execution_grid_cursors
                   WHERE account_scope = ? AND strategy_scope = ? AND cohort_id = ?""",
                cursor_key,
            ).fetchone()
            if current is not None:
                same_grid = (
                    current["decision_id"] == decision_id
                    and current["epoch_id"] == epoch_id
                    and current["batch_id"] == batch_id
                    and current["close_time"] == key.close_time
                )
                if same_grid:
                    self._apply_run_order_budget(
                        db_cursor,
                        key,
                        capacity_class=_decision_capacity_class(normalized_keys),
                        max_order_intents_per_run=max_order_intents_per_run,
                        added_count=0,
                        created=False,
                        expected_run_order_intents_used=expected_run_order_intents_used,
                        remaining_exit_intent_reserve=remaining_exit_intent_reserve,
                        require_reservation=True,
                    )
                    return ExecutionGridDecision(
                        decision=decision,
                        cursor=_grid_cursor_record(current),
                        eligible=True,
                        is_new_grid=False,
                    )
            if not created:
                # Exact immutable decision replays stay idempotent even after
                # this cohort has advanced. They never rewind either cursor
                # and never dispatch again.
                self._apply_run_order_budget(
                    db_cursor,
                    key,
                    capacity_class=_decision_capacity_class(normalized_keys),
                    max_order_intents_per_run=max_order_intents_per_run,
                    added_count=0,
                    created=False,
                    expected_run_order_intents_used=expected_run_order_intents_used,
                    remaining_exit_intent_reserve=remaining_exit_intent_reserve,
                    require_reservation=True,
                )
                return ExecutionGridDecision(
                    decision=decision,
                    cursor=None if current is None else _grid_cursor_record(current),
                    eligible=True,
                    is_new_grid=False,
                )

            highwater = db_cursor.execute(
                """SELECT close_time FROM execution_grid_highwaters
                   WHERE account_scope = ? AND strategy_scope = ?""",
                (key.account_scope, key.strategy_scope),
            ).fetchone()
            if highwater is not None and _parse_normalized_close_time(
                key.close_time
            ) <= _parse_normalized_close_time(highwater["close_time"]):
                raise ExecutionDecisionJournalError("GRID_CURSOR_STALE_OR_CONFLICT")

            candidate_time = _parse_normalized_close_time(key.close_time)
            if current is not None:
                current_time = _parse_normalized_close_time(current["close_time"])
                if candidate_time <= current_time:
                    raise ExecutionDecisionJournalError("GRID_CURSOR_STALE_OR_CONFLICT")

            self._apply_run_order_budget(
                db_cursor,
                key,
                capacity_class=_decision_capacity_class(normalized_keys),
                max_order_intents_per_run=max_order_intents_per_run,
                added_count=len(normalized_keys),
                created=True,
                expected_run_order_intents_used=expected_run_order_intents_used,
                remaining_exit_intent_reserve=remaining_exit_intent_reserve,
                require_reservation=True,
            )

            ordinal = 1 if current is None else int(current["ordinal"]) + 1
            decision_class = _decision_capacity_class(normalized_keys)
            with track_durable_row_change(
                db_cursor, "execution_grid_cursors", cursor_key, decision_class
            ):
                db_cursor.execute(
                    """INSERT INTO execution_grid_cursors
                       (account_scope, strategy_scope, cohort_id, ordinal, epoch_id,
                        batch_id, close_time, decision_id, updated_at_ns)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(account_scope, strategy_scope, cohort_id) DO UPDATE SET
                         ordinal = excluded.ordinal,
                         epoch_id = excluded.epoch_id,
                         batch_id = excluded.batch_id,
                         close_time = excluded.close_time,
                         decision_id = excluded.decision_id,
                         updated_at_ns = excluded.updated_at_ns""",
                    cursor_key + (ordinal, epoch_id, batch_id, key.close_time, decision_id, now_ns),
                )
            saved_cursor = db_cursor.execute(
                """SELECT * FROM execution_grid_cursors
                   WHERE account_scope = ? AND strategy_scope = ? AND cohort_id = ?""",
                cursor_key,
            ).fetchone()
            from .factor_position_book import record_factor_position_grid

            record_factor_position_grid(
                db_cursor,
                account_scope=key.account_scope,
                strategy_scope=key.strategy_scope,
                cohort_id=key.cohort_id,
                batch_id=batch_id,
                close_time=key.close_time,
                ordinal=ordinal,
                capacity_class=decision_class,
            )
            highwater_key = (key.account_scope, key.strategy_scope)
            with track_durable_row_change(
                db_cursor, "execution_grid_highwaters", highwater_key, decision_class
            ):
                db_cursor.execute(
                    """INSERT INTO execution_grid_highwaters
                       (account_scope, strategy_scope, close_time, cohort_id, decision_id,
                        updated_at_ns)
                       VALUES (?, ?, ?, ?, ?, ?)
                       ON CONFLICT(account_scope, strategy_scope) DO UPDATE SET
                         close_time = excluded.close_time,
                         cohort_id = excluded.cohort_id,
                         decision_id = excluded.decision_id,
                         updated_at_ns = excluded.updated_at_ns""",
                    (
                        key.account_scope,
                        key.strategy_scope,
                        key.close_time,
                        key.cohort_id,
                        decision_id,
                        now_ns,
                    ),
                )
            return ExecutionGridDecision(
                decision=decision,
                cursor=_grid_cursor_record(saved_cursor),
                eligible=True,
                is_new_grid=True,
            )

    def record_risk_decision(
        self,
        key: ExecutionDecisionKey,
        economic_payload: Mapping[str, Any],
        *,
        intent_keys: Tuple[ExecutionIntentKey, ...],
        max_order_intents_per_run: int,
        expected_run_order_intents_used: Optional[int] = None,
        remaining_exit_intent_reserve: Optional[int] = None,
    ) -> ExecutionGridDecision:
        """Persist a non-grid risk reduction decision and its order budget.

        This path is for recorded cancels and position-reducing closes when a
        factor snapshot is unavailable. It intentionally does not advance the
        eligible-grid cursor. Opening SUBMIT intents are never accepted here.
        Its expected-use compare-and-swap and remaining exit reserve are checked
        in the same transaction as the immutable decision and intent charge.
        """

        if not isinstance(key, ExecutionDecisionKey):
            raise ExecutionDecisionJournalError("INVALID_DECISION_KEY")
        if type(max_order_intents_per_run) is not int or max_order_intents_per_run < 0:
            raise ExecutionDecisionJournalError("INVALID_RUN_ORDER_BUDGET")
        self._validate_run_order_reservation(
            max_order_intents_per_run=max_order_intents_per_run,
            expected_run_order_intents_used=expected_run_order_intents_used,
            remaining_exit_intent_reserve=remaining_exit_intent_reserve,
        )
        normalized_keys = _normalize_intent_keys(intent_keys, self.max_pending_intents)
        if any(
            item.action == "SUBMIT" and item.position_effect != "CLOSE" for item in normalized_keys
        ):
            raise ExecutionDecisionJournalError("RISK_DECISION_MAY_NOT_OPEN")
        payload_json, replay_payload_json, reservation = self._budgeted_payload_json(
            economic_payload,
            max_order_intents_per_run=max_order_intents_per_run,
            remaining_exit_intent_reserve=remaining_exit_intent_reserve,
        )
        keys_json = _canonical_json([_intent_key_values(item) for item in normalized_keys])
        key_json = _canonical_json(_decision_key_values(key))
        decision_id = _stable_id("decision", key_json)
        now_ns = time.time_ns()
        with self._transaction() as cursor:
            decision, created = self._record_decision_in_transaction(
                cursor,
                decision_id=decision_id,
                key_json=key_json,
                payload_json=payload_json,
                replay_payload_json=replay_payload_json,
                run_order_reservation=reservation,
                keys_json=keys_json,
                normalized_keys=normalized_keys,
                now_ns=now_ns,
            )
            self._apply_run_order_budget(
                cursor,
                key,
                capacity_class=_decision_capacity_class(normalized_keys),
                max_order_intents_per_run=max_order_intents_per_run,
                added_count=len(normalized_keys),
                created=created,
                expected_run_order_intents_used=expected_run_order_intents_used,
                remaining_exit_intent_reserve=remaining_exit_intent_reserve,
                require_reservation=True,
            )
            return ExecutionGridDecision(
                decision=decision,
                cursor=None,
                eligible=True,
                is_new_grid=created,
            )

    def grid_cursor(
        self, account_scope: str, strategy_scope: str, cohort_id: str
    ) -> Optional[ExecutionGridCursor]:
        """Read one cohort cursor without retaining an in-memory bar counter."""

        _require_identifier(account_scope, "INVALID_ACCOUNT_SCOPE")
        _require_identifier(strategy_scope, "INVALID_STRATEGY_SCOPE")
        _require_identifier(cohort_id, "INVALID_COHORT_ID")
        with self._read_lock():
            row = self._connection.execute(
                """SELECT * FROM execution_grid_cursors
                   WHERE account_scope = ? AND strategy_scope = ? AND cohort_id = ?""",
                (account_scope, strategy_scope, cohort_id),
            ).fetchone()
        return None if row is None else _grid_cursor_record(row)

    def run_order_count(self, account_scope: str, strategy_scope: str, logical_run_id: str) -> int:
        """Return durable submit/cancel intents declared by one logical run."""

        _require_identifier(account_scope, "INVALID_ACCOUNT_SCOPE")
        _require_identifier(strategy_scope, "INVALID_STRATEGY_SCOPE")
        _require_identifier(logical_run_id, "INVALID_LOGICAL_RUN_ID")
        with self._read_lock():
            row = self._connection.execute(
                """SELECT intent_count FROM execution_run_order_budgets
                   WHERE account_scope = ? AND strategy_scope = ? AND logical_run_id = ?""",
                (account_scope, strategy_scope, logical_run_id),
            ).fetchone()
        return 0 if row is None else int(row["intent_count"])

    @staticmethod
    def _apply_run_order_budget(
        cursor: sqlite3.Cursor,
        key: ExecutionDecisionKey,
        *,
        capacity_class: str,
        max_order_intents_per_run: Optional[int],
        added_count: int,
        created: bool,
        expected_run_order_intents_used: Optional[int] = None,
        remaining_exit_intent_reserve: Optional[int] = None,
        require_reservation: bool = False,
    ) -> None:
        budget_key = (key.account_scope, key.strategy_scope, key.logical_run_id)
        row = cursor.execute(
            """SELECT max_intents, intent_count FROM execution_run_order_budgets
               WHERE account_scope = ? AND strategy_scope = ? AND logical_run_id = ?""",
            budget_key,
        ).fetchone()
        if max_order_intents_per_run is None:
            if row is not None:
                raise ExecutionDecisionJournalError("RUN_ORDER_BUDGET_REQUIRED")
            return
        if row is None:
            if not created:
                raise ExecutionDecisionJournalError("RUN_ORDER_BUDGET_MISSING")
            count = 0
            with track_durable_row_change(
                cursor, "execution_run_order_budgets", budget_key, capacity_class
            ):
                cursor.execute(
                    """INSERT INTO execution_run_order_budgets
                       (account_scope, strategy_scope, logical_run_id, max_intents,
                        intent_count, created_at_ns)
                       VALUES (?, ?, ?, ?, 0, ?)""",
                    budget_key + (max_order_intents_per_run, time.time_ns()),
                )
        else:
            if int(row["max_intents"]) != max_order_intents_per_run:
                raise ExecutionDecisionJournalError("RUN_ORDER_BUDGET_CONFLICT")
            count = int(row["intent_count"])
        if not created:
            return
        if require_reservation and (
            expected_run_order_intents_used is None or remaining_exit_intent_reserve is None
        ):
            raise ExecutionDecisionJournalError("RUN_ORDER_BUDGET_RESERVATION_REQUIRED")
        if expected_run_order_intents_used is not None and count != expected_run_order_intents_used:
            raise ExecutionDecisionJournalError("RUN_ORDER_BUDGET_STALE")
        reserve_count = remaining_exit_intent_reserve or 0
        if count + added_count + reserve_count > max_order_intents_per_run:
            raise ExecutionDecisionJournalError("RUN_ORDER_BUDGET_EXCEEDED")
        with track_durable_row_change(
            cursor, "execution_run_order_budgets", budget_key, capacity_class
        ):
            cursor.execute(
                """UPDATE execution_run_order_budgets SET intent_count = ?
                   WHERE account_scope = ? AND strategy_scope = ? AND logical_run_id = ?""",
                (count + added_count,) + budget_key,
            )

    @staticmethod
    def _validate_run_order_reservation(
        *,
        max_order_intents_per_run: Optional[int],
        expected_run_order_intents_used: Optional[int],
        remaining_exit_intent_reserve: Optional[int],
    ) -> None:
        if max_order_intents_per_run is None:
            if (
                expected_run_order_intents_used is not None
                or remaining_exit_intent_reserve is not None
            ):
                raise ExecutionDecisionJournalError("INVALID_RUN_ORDER_BUDGET_RESERVATION")
            return
        if expected_run_order_intents_used is None and remaining_exit_intent_reserve is None:
            # Missing values remain valid for exact replay. A newly admitted
            # budgeted decision is rejected inside the write transaction.
            return
        if (
            type(expected_run_order_intents_used) is not int
            or expected_run_order_intents_used < 0
            or type(remaining_exit_intent_reserve) is not int
            or remaining_exit_intent_reserve < 0
        ):
            raise ExecutionDecisionJournalError("INVALID_RUN_ORDER_BUDGET_RESERVATION")

    def _budgeted_payload_json(
        self,
        economic_payload: Mapping[str, Any],
        *,
        max_order_intents_per_run: Optional[int],
        remaining_exit_intent_reserve: Optional[int],
    ) -> Tuple[str, str, Optional[Mapping[str, int]]]:
        """Bind the post-plan reserve to immutable economics, separate from CAS state."""

        base_payload_json = self._payload_json(economic_payload)
        if _RUN_ORDER_RESERVATION_FIELD in economic_payload:
            raise ExecutionDecisionJournalError("RUN_ORDER_BUDGET_EVIDENCE_RESERVED")
        if max_order_intents_per_run is None or remaining_exit_intent_reserve is None:
            return base_payload_json, base_payload_json, None
        reservation = {
            "max_order_intents_per_run": max_order_intents_per_run,
            "remaining_exit_intent_reserve": remaining_exit_intent_reserve,
        }
        persisted_payload = dict(economic_payload)
        persisted_payload[_RUN_ORDER_RESERVATION_FIELD] = reservation
        return self._payload_json(persisted_payload), base_payload_json, reservation

    def _record_decision_in_transaction(
        self,
        cursor: sqlite3.Cursor,
        *,
        decision_id: str,
        key_json: str,
        payload_json: str,
        keys_json: str,
        normalized_keys: Tuple[ExecutionIntentKey, ...],
        now_ns: int,
        replay_payload_json: Optional[str] = None,
        run_order_reservation: Optional[Mapping[str, int]] = None,
    ) -> Tuple[ExecutionDecisionRecord, bool]:
        row = cursor.execute(
            "SELECT * FROM execution_decisions WHERE decision_id = ?", (decision_id,)
        ).fetchone()
        if row is not None:
            economics_match = row["economic_payload_json"] == payload_json
            if not economics_match and replay_payload_json is not None:
                try:
                    persisted_economics = json.loads(row["economic_payload_json"])
                except (TypeError, ValueError):
                    persisted_economics = None
                if isinstance(persisted_economics, Mapping):
                    persisted_evidence = persisted_economics.pop(_RUN_ORDER_RESERVATION_FIELD, None)
                    economics_match = _canonical_json(persisted_economics) == replay_payload_json
                    if economics_match:
                        economics_match = _valid_run_order_reservation_evidence(
                            persisted_evidence,
                            requested=run_order_reservation,
                        )
            if (
                row["business_key_json"] != key_json
                or not economics_match
                or row["intent_keys_json"] != keys_json
            ):
                raise ExecutionDecisionJournalError("DECISION_CONFLICT")
            return _decision_record(row), False

        decision_class = _decision_capacity_class(normalized_keys)
        decision_payload_bytes = sum(
            len(value.encode("utf-8")) for value in (key_json, payload_json, keys_json)
        )
        self._check_decision_capacity(
            cursor,
            decision_class=decision_class,
            added_bytes=decision_payload_bytes,
        )

        if normalized_keys:
            pending = int(
                cursor.execute(
                    """SELECT COUNT(*) FROM execution_decision_slots AS s
                       LEFT JOIN execution_decision_intents AS i ON i.intent_id = s.intent_id
                       WHERE (i.intent_id IS NULL OR i.state IN ('PREPARED','DISPATCHING','UNKNOWN'))
                         AND NOT EXISTS (
                             SELECT 1 FROM execution_intent_abandonments AS a
                             WHERE a.intent_id = s.intent_id
                         )
                         AND NOT EXISTS (
                             SELECT 1 FROM execution_slot_abandonments AS a
                             WHERE a.intent_id = s.intent_id
                         )"""
                ).fetchone()[0]
            )
            if pending + len(normalized_keys) > self.max_pending_intents:
                raise ExecutionDecisionJournalError("PENDING_INTENT_LIMIT")
        if any(
            item.action == "SUBMIT" and item.position_effect == "OPEN" for item in normalized_keys
        ):
            self._ensure_new_open_capacity(cursor)
        with track_durable_row_change(
            cursor, "execution_decisions", (decision_id,), decision_class
        ):
            cursor.execute(
                """INSERT INTO execution_decisions
                   (decision_id, business_key_json, economic_payload_json,
                     intent_keys_json, created_at_ns, capacity_class)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (decision_id, key_json, payload_json, keys_json, now_ns, decision_class),
            )
        cursor.execute(
            """UPDATE execution_decision_capacity_usage
               SET record_count=record_count+1,payload_bytes=payload_bytes+?
               WHERE capacity_class=?""",
            (decision_payload_bytes, decision_class),
        )
        if cursor.rowcount != 1:
            raise ExecutionDecisionJournalError("DECISION_CAPACITY_USAGE_UNAVAILABLE")
        for intent_key in normalized_keys:
            intent_key_json = _canonical_json(_intent_key_values(intent_key))
            intent_id = _stable_id("intent", decision_id + ":" + intent_key_json)
            with track_durable_row_change(
                cursor, "execution_decision_slots", (intent_id,), decision_class
            ):
                cursor.execute(
                    """INSERT INTO execution_decision_slots
                       (intent_id, decision_id, intent_key_json, leg)
                       VALUES (?, ?, ?, ?)""",
                    (intent_id, decision_id, intent_key_json, intent_key.leg),
                )
        row = cursor.execute(
            "SELECT * FROM execution_decisions WHERE decision_id = ?", (decision_id,)
        ).fetchone()
        return _decision_record(row), True

    def _ensure_new_open_capacity(self, cursor: sqlite3.Cursor) -> None:
        """Require room in both cumulative classes before admitting new OPEN risk."""

        try:
            usage = read_durable_capacity_usage(cursor)
        except DurableCapacityError as error:
            raise ExecutionDecisionJournalError(error.code) from error
        limits = self.durable_capacity_limits
        if usage.base_records >= limits.max_durable_base_records:
            raise ExecutionDecisionJournalError("DURABLE_BASE_RECORDS_EXHAUSTED")
        if usage.base_bytes >= limits.max_durable_base_bytes:
            raise ExecutionDecisionJournalError("DURABLE_BASE_BYTES_EXHAUSTED")
        if usage.settlement_records >= limits.max_durable_settlement_records:
            raise ExecutionDecisionJournalError("DURABLE_SETTLEMENT_RECORDS_EXHAUSTED")
        if usage.settlement_bytes >= limits.max_durable_settlement_bytes:
            raise ExecutionDecisionJournalError("DURABLE_SETTLEMENT_BYTES_EXHAUSTED")

    def _check_decision_capacity(
        self, cursor: sqlite3.Cursor, *, decision_class: str, added_bytes: int
    ) -> None:
        row = cursor.execute(
            """SELECT record_count,payload_bytes
               FROM execution_decision_capacity_usage WHERE capacity_class=?""",
            (decision_class,),
        ).fetchone()
        if row is None:
            raise ExecutionDecisionJournalError("DECISION_CAPACITY_USAGE_UNAVAILABLE")
        record_count = int(row["record_count"])
        stored_bytes = int(row["payload_bytes"])
        if record_count < 0 or stored_bytes < 0:
            raise ExecutionDecisionJournalError("DECISION_CAPACITY_USAGE_INVALID")
        if decision_class == "SETTLEMENT":
            record_limit = self.settlement_decision_reserve_records
            byte_limit = self.settlement_decision_reserve_bytes
            error_code = "SETTLEMENT_CAPACITY_EXHAUSTED"
        else:
            record_limit = self.max_decision_records
            byte_limit = self.max_decision_bytes
            error_code = "DECISION_CAPACITY_HIGH_WATER"
        if (
            record_count >= record_limit
            or stored_bytes + added_bytes > byte_limit
            or record_count >= 9223372036854775807
            or stored_bytes + added_bytes > 9223372036854775807
        ):
            raise ExecutionDecisionJournalError(error_code)

    def decision(self, decision_id: str) -> Optional[ExecutionDecisionRecord]:
        _require_identifier(decision_id, "INVALID_DECISION_ID")
        with self._read_lock():
            row = self._connection.execute(
                "SELECT * FROM execution_decisions WHERE decision_id = ?", (decision_id,)
            ).fetchone()
        return None if row is None else _decision_record(row)

    def decision_capacity_snapshot(self) -> ExecutionDecisionCapacitySnapshot:
        """Return bounded decision usage plus a read-only SQLite size sample.

        Exact decision replay does not consume capacity.  BASE includes NOOP,
        OPEN, and mixed plans; SETTLEMENT is reserved for decisions consisting
        only of CLOSE and/or CANCEL intents.  The physical DB/WAL sample is
        informational; decision JSON bytes are the enforced byte high-water.
        """

        with self._read_lock():
            rows = self._connection.execute(
                """SELECT capacity_class,record_count,payload_bytes
                   FROM execution_decision_capacity_usage ORDER BY capacity_class"""
            ).fetchall()
            usage = {}
            for row in rows:
                count = row["record_count"]
                payload_bytes = row["payload_bytes"]
                if (
                    row["capacity_class"] not in ("BASE", "SETTLEMENT")
                    or type(count) is not int
                    or type(payload_bytes) is not int
                    or count < 0
                    or payload_bytes < 0
                    or row["capacity_class"] in usage
                ):
                    raise ExecutionDecisionJournalError("DECISION_CAPACITY_USAGE_INVALID")
                usage[row["capacity_class"]] = (count, payload_bytes)
            if set(usage) != {"BASE", "SETTLEMENT"}:
                raise ExecutionDecisionJournalError("DECISION_CAPACITY_USAGE_UNAVAILABLE")
            page_count = int(self._connection.execute("PRAGMA page_count").fetchone()[0])
            page_size = int(self._connection.execute("PRAGMA page_size").fetchone()[0])
            if self.path == ":memory:":
                database_bytes = page_count * page_size
                wal_bytes = 0
            else:
                try:
                    database_bytes = Path(self.path).stat().st_size
                except FileNotFoundError:
                    database_bytes = page_count * page_size
                try:
                    wal_bytes = Path(str(self.path) + "-wal").stat().st_size
                except FileNotFoundError:
                    wal_bytes = 0
        base_records, base_bytes = usage.get("BASE", (0, 0))
        settlement_records, settlement_bytes = usage.get("SETTLEMENT", (0, 0))
        return ExecutionDecisionCapacitySnapshot(
            base_record_count=base_records,
            base_record_limit=self.max_decision_records,
            base_payload_bytes=base_bytes,
            base_payload_byte_limit=self.max_decision_bytes,
            settlement_record_count=settlement_records,
            settlement_record_limit=self.settlement_decision_reserve_records,
            settlement_payload_bytes=settlement_bytes,
            settlement_payload_byte_limit=self.settlement_decision_reserve_bytes,
            database_bytes=database_bytes,
            wal_bytes=wal_bytes,
        )

    def prepare_intent(
        self,
        decision_id: str,
        intent_key: ExecutionIntentKey,
        economic_payload: Mapping[str, Any],
        *,
        original_identity: Optional[Mapping[str, Any]] = None,
        owner_intent_id: Optional[str] = None,
    ) -> ExecutionIntentRecord:
        """Bind economics and original IDs, reserving one account/instrument owner.

        SUBMIT intents acquire a persistent owner for their account/instrument.
        CANCEL intents must name the active submit's ``owner_intent_id`` and
        cannot replace that owner. The owner remains held after a KNOWN API
        response until ``release_instrument_owner`` consumes a persisted
        terminal-order and current-position reconciliation record. Reversals
        are sequenced as a close decision followed by a later open decision
        after terminal reconciliation; one decision cannot declare multiple
        legs for an instrument. This journal tracks pending orders, not
        position policy.
        """

        _require_identifier(decision_id, "INVALID_DECISION_ID")
        if not isinstance(intent_key, ExecutionIntentKey):
            raise ExecutionDecisionJournalError("INVALID_INTENT_KEY")
        payload_json = self._payload_json(economic_payload)
        identity_json = self._payload_json({} if original_identity is None else original_identity)
        intent_key_json = _canonical_json(_intent_key_values(intent_key))
        intent_id = _stable_id("intent", decision_id + ":" + intent_key_json)
        now_ns = time.time_ns()

        with self._transaction() as cursor:
            decision_row = cursor.execute(
                "SELECT business_key_json,capacity_class FROM execution_decisions WHERE decision_id = ?",
                (decision_id,),
            ).fetchone()
            slot = cursor.execute(
                "SELECT * FROM execution_decision_slots WHERE intent_id = ?", (intent_id,)
            ).fetchone()
            if decision_row is None or slot is None or slot["decision_id"] != decision_id:
                raise ExecutionDecisionJournalError("INTENT_NOT_DECLARED")
            row = cursor.execute(
                "SELECT * FROM execution_decision_intents WHERE intent_id = ?", (intent_id,)
            ).fetchone()
            if row is not None:
                if (
                    row["intent_key_json"] != intent_key_json
                    or row["economic_payload_json"] != payload_json
                    or row["original_identity_json"] != identity_json
                    or row["owner_intent_id"] != owner_intent_id
                ):
                    raise ExecutionDecisionJournalError("INTENT_CONFLICT")
                self._index_native_intent_identity(
                    cursor,
                    intent_id=intent_id,
                    account_scope=json.loads(decision_row["business_key_json"])["account_scope"],
                    strategy_scope=json.loads(decision_row["business_key_json"])["strategy_scope"],
                    intent_key=intent_key,
                    original_identity=json.loads(identity_json),
                    capacity_class=(
                        "SETTLEMENT"
                        if intent_key.action == "CANCEL" or intent_key.position_effect == "CLOSE"
                        else self._durable_decision_class(decision_row["capacity_class"])
                    ),
                )
                return _intent_record(row)

            account_scope = json.loads(decision_row["business_key_json"])["account_scope"]
            intent_capacity_class = (
                "SETTLEMENT"
                if intent_key.action == "CANCEL" or intent_key.position_effect == "CLOSE"
                else self._durable_decision_class(decision_row["capacity_class"])
            )
            owner = cursor.execute(
                """SELECT * FROM execution_instrument_owners
                   WHERE account_scope = ? AND instrument = ?""",
                (account_scope, intent_key.instrument),
            ).fetchone()
            if intent_key.action == "SUBMIT":
                if owner is not None and owner["owner_intent_id"] is not None:
                    raise ExecutionDecisionJournalError("INSTRUMENT_OWNER_ACTIVE")
                factor_owned_close = intent_key.position_effect == "CLOSE" and (
                    owner_intent_id is not None
                    or any(
                        name in economic_payload
                        for name in ("risk_policy_id", "factor_stop_price", "entry_grid_ordinal")
                    )
                )
                if intent_key.position_effect == "OPEN":
                    if owner_intent_id is not None:
                        raise ExecutionDecisionJournalError("UNEXPECTED_OWNER_INTENT")
                    self._ensure_new_open_capacity(cursor)
                elif intent_key.position_effect == "CLOSE":
                    if factor_owned_close and owner_intent_id is None:
                        raise ExecutionDecisionJournalError("CLOSE_OWNER_REQUIRED")
                    if factor_owned_close:
                        _require_identifier(owner_intent_id, "INVALID_OWNER_INTENT_ID")
                        try:
                            from .factor_position_book import validate_factor_position_close_owner

                            validate_factor_position_close_owner(
                                cursor,
                                account_scope=account_scope,
                                strategy_scope=json.loads(decision_row["business_key_json"])[
                                    "strategy_scope"
                                ],
                                instrument=intent_key.instrument,
                                exchange=str(economic_payload.get("exchange") or ""),
                                owner_intent_id=owner_intent_id,
                            )
                        except ImportError as error:
                            raise ExecutionDecisionJournalError(
                                "POSITION_BOOK_UNAVAILABLE"
                            ) from error
                else:
                    raise ExecutionDecisionJournalError("INVALID_POSITION_EFFECT")
                if owner is None:
                    with track_durable_row_change(
                        cursor,
                        "execution_instrument_owners",
                        (account_scope, intent_key.instrument),
                        intent_capacity_class,
                    ):
                        cursor.execute(
                            """INSERT INTO execution_instrument_owners
                               (account_scope, instrument, owner_intent_id, cancel_intent_id)
                               VALUES (?, ?, ?, NULL)""",
                            (account_scope, intent_key.instrument, intent_id),
                        )
                else:
                    with track_durable_row_change(
                        cursor,
                        "execution_instrument_owners",
                        (account_scope, intent_key.instrument),
                        intent_capacity_class,
                    ):
                        cursor.execute(
                            """UPDATE execution_instrument_owners
                               SET owner_intent_id = ?, cancel_intent_id = NULL
                               WHERE account_scope = ? AND instrument = ?
                                 AND owner_intent_id IS NULL""",
                            (intent_id, account_scope, intent_key.instrument),
                        )
            else:
                if owner_intent_id is None:
                    raise ExecutionDecisionJournalError("CANCEL_OWNER_REQUIRED")
                _require_identifier(owner_intent_id, "INVALID_OWNER_INTENT_ID")
                if owner is None or owner["owner_intent_id"] != owner_intent_id:
                    raise ExecutionDecisionJournalError("CANCEL_OWNER_MISMATCH")
                owner_row = cursor.execute(
                    "SELECT state FROM execution_decision_intents WHERE intent_id = ?",
                    (owner_intent_id,),
                ).fetchone()
                if owner_row is None or owner_row["state"] != "KNOWN":
                    raise ExecutionDecisionJournalError("CANCEL_OWNER_NOT_KNOWN")
                if owner["cancel_intent_id"] not in (None, intent_id):
                    raise ExecutionDecisionJournalError("CANCEL_ALREADY_PREPARED")
                with track_durable_row_change(
                    cursor,
                    "execution_instrument_owners",
                    (account_scope, intent_key.instrument),
                    intent_capacity_class,
                ):
                    cursor.execute(
                        """UPDATE execution_instrument_owners SET cancel_intent_id = ?
                           WHERE account_scope = ? AND instrument = ?
                             AND owner_intent_id = ?""",
                        (intent_id, account_scope, intent_key.instrument, owner_intent_id),
                    )
            with track_durable_row_change(
                cursor, "execution_decision_intents", (intent_id,), intent_capacity_class
            ):
                cursor.execute(
                    """INSERT INTO execution_decision_intents
                       (intent_id, decision_id, intent_key_json, economic_payload_json,
                        original_identity_json, owner_intent_id, state, provider_identity_json,
                        outcome_code, dispatch_result_json, created_at_ns, updated_at_ns)
                       VALUES (?, ?, ?, ?, ?, ?, 'PREPARED', NULL, NULL, NULL, ?, ?)""",
                    (
                        intent_id,
                        decision_id,
                        intent_key_json,
                        payload_json,
                        identity_json,
                        owner_intent_id,
                        now_ns,
                        now_ns,
                    ),
                )
            self._index_native_intent_identity(
                cursor,
                intent_id=intent_id,
                account_scope=account_scope,
                strategy_scope=json.loads(decision_row["business_key_json"])["strategy_scope"],
                intent_key=intent_key,
                original_identity=json.loads(identity_json),
                capacity_class=intent_capacity_class,
            )
            row = cursor.execute(
                "SELECT * FROM execution_decision_intents WHERE intent_id = ?", (intent_id,)
            ).fetchone()
            return _intent_record(row)

    def intent(self, intent_id: str) -> Optional[ExecutionIntentRecord]:
        _require_identifier(intent_id, "INVALID_INTENT_ID")
        with self._read_lock():
            row = self._connection.execute(
                "SELECT * FROM execution_decision_intents WHERE intent_id = ?", (intent_id,)
            ).fetchone()
        return None if row is None else _intent_record(row)

    def intent_by_native_order_ref(
        self,
        *,
        account_scope: str,
        strategy_scope: str,
        trading_day: str,
        instrument: str,
        exchange: str,
        order_ref: str,
    ) -> Optional[ExecutionIntentRecord]:
        """Resolve one exact CTP OrderRef through the durable route index.

        The trading day and complete instrument/exchange route are mandatory
        because providers may reuse references after a session reset. Ambiguous
        matches fail closed instead of selecting the newest row.
        """

        for name, value in (
            ("account_scope", account_scope),
            ("strategy_scope", strategy_scope),
            ("trading_day", trading_day),
            ("instrument", instrument),
            ("exchange", exchange),
            ("order_ref", order_ref),
        ):
            _require_identifier(value, "INVALID_" + name.upper())
        if len(trading_day) != 8 or not trading_day.isdigit():
            raise ExecutionDecisionJournalError("INVALID_TRADING_DAY")
        with self._read_lock():
            rows = self._connection.execute(
                """SELECT i.* FROM execution_native_intent_identities AS n
                   JOIN execution_decision_intents AS i ON i.intent_id=n.intent_id
                   WHERE n.account_scope=? AND n.strategy_scope=? AND n.trading_day=?
                     AND n.instrument=? AND n.exchange=? AND n.order_ref=?
                   LIMIT 2""",
                (account_scope, strategy_scope, trading_day, instrument, exchange, order_ref),
            ).fetchall()
        if len(rows) > 1:
            raise ExecutionDecisionJournalError("NATIVE_ORDER_IDENTITY_AMBIGUOUS")
        return None if not rows else _intent_record(rows[0])

    def callback_projection_status(
        self,
        intent_id: str,
        callback_id: str,
        evidence_payload: Mapping[str, Any],
    ) -> ExecutionCallbackProjectionStatus:
        """Check exact persisted callback evidence and its durable fill projection."""

        _require_identifier(intent_id, "INVALID_INTENT_ID")
        _require_identifier(callback_id, "INVALID_CALLBACK_ID")
        payload_json = self._payload_json(evidence_payload)
        receipt_id = _stable_id("callback", intent_id + ":" + callback_id)
        execution_id = evidence_payload.get("execution_id")
        if not _identifier(execution_id):
            return ExecutionCallbackProjectionStatus("UNRECONCILED", receipt_id)
        try:
            with self._read_lock():
                receipt = self._connection.execute(
                    """SELECT intent_id, callback_id, evidence_payload_json
                       FROM execution_decision_callbacks WHERE receipt_id=?""",
                    (receipt_id,),
                ).fetchone()
                if receipt is None:
                    return ExecutionCallbackProjectionStatus("UNRECONCILED", receipt_id)
                if (
                    receipt["intent_id"] != intent_id
                    or receipt["callback_id"] != callback_id
                    or receipt["evidence_payload_json"] != payload_json
                ):
                    return ExecutionCallbackProjectionStatus(
                        "BLOCKED", receipt_id, "CALLBACK_EVIDENCE_CONFLICT"
                    )
                issue = self._connection.execute(
                    """SELECT blocker_code FROM factor_position_evidence_issues
                       WHERE receipt_id=?""",
                    (receipt_id,),
                ).fetchone()
                if issue is not None:
                    return ExecutionCallbackProjectionStatus(
                        "BLOCKED", receipt_id, issue["blocker_code"]
                    )
                intent = self._connection.execute(
                    """SELECT i.intent_key_json, i.economic_payload_json,
                              d.business_key_json
                       FROM execution_decision_intents AS i
                       JOIN execution_decisions AS d ON d.decision_id=i.decision_id
                       WHERE i.intent_id=?""",
                    (intent_id,),
                ).fetchone()
                if intent is None:
                    return ExecutionCallbackProjectionStatus(
                        "BLOCKED", receipt_id, "CALLBACK_INTENT_NOT_FOUND"
                    )
                key = json.loads(intent["intent_key_json"])
                economics = json.loads(intent["economic_payload_json"])
                business_key = json.loads(intent["business_key_json"])
                fill = self._connection.execute(
                    """SELECT * FROM factor_position_fills
                       WHERE account_scope=? AND instrument=? AND exchange=?
                         AND execution_id=?""",
                    (
                        business_key.get("account_scope"),
                        key.get("instrument"),
                        economics.get("exchange"),
                        execution_id,
                    ),
                ).fetchone()
        except (sqlite3.Error, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise ExecutionDecisionJournalError("JOURNAL_READ_FAILED") from error
        if fill is None:
            return ExecutionCallbackProjectionStatus("UNRECONCILED", receipt_id)
        if (
            fill["intent_id"] != intent_id
            or fill["strategy_scope"] != business_key.get("strategy_scope")
            or fill["position_effect"] != key.get("position_effect")
            or fill["order_side"] != key.get("side")
            or fill["quantity"] != _canonical_decimal(evidence_payload.get("quantity"))
            or fill["price"] != _canonical_decimal(evidence_payload.get("price"))
            or fill["filled_at_ns"] != evidence_payload.get("filled_at_ns")
        ):
            return ExecutionCallbackProjectionStatus(
                "BLOCKED", receipt_id, "CALLBACK_FILL_PROJECTION_CONFLICT"
            )
        # A query observation may omit commission. That absence does not
        # contradict a fee already observed on the native callback.
        fee = evidence_payload.get("fee")
        if fee is not None and fill["fee"] != _canonical_decimal(fee):
            return ExecutionCallbackProjectionStatus(
                "BLOCKED", receipt_id, "CALLBACK_FILL_FEE_CONFLICT"
            )
        return ExecutionCallbackProjectionStatus("APPLIED", receipt_id)

    def callback_receipt(
        self, intent_id: str, callback_id: str
    ) -> Optional[ExecutionCallbackReceipt]:
        """Read one exact dedupe receipt without scanning callback history."""

        _require_identifier(intent_id, "INVALID_INTENT_ID")
        _require_identifier(callback_id, "INVALID_CALLBACK_ID")
        receipt_id = _stable_id("callback", intent_id + ":" + callback_id)
        with self._read_lock():
            row = self._connection.execute(
                """SELECT * FROM execution_decision_callbacks
                   WHERE receipt_id=? AND intent_id=? AND callback_id=?""",
                (receipt_id, intent_id, callback_id),
            ).fetchone()
        return None if row is None else _callback_record(row)

    def callback_query_disposition(
        self, native_receipt_id: str
    ) -> Optional[ExecutionCallbackQueryDisposition]:
        """Read one exact, immutable query-matched native callback disposition."""

        _require_identifier(native_receipt_id, "INVALID_NATIVE_CALLBACK_RECEIPT_ID")
        with self._read_lock():
            row = self._connection.execute(
                """SELECT d.*,n.callback_id AS native_callback_id,
                          n.evidence_payload_json AS native_evidence_json,
                          n.acknowledged AS native_acknowledged,
                          n.delivery_pending AS native_delivery_pending,
                          n.process_instance_id AS native_process_instance_id,
                          q.callback_id AS query_callback_id,
                          q.evidence_payload_json AS query_evidence_json,
                          q.acknowledged AS query_acknowledged
                    FROM execution_callback_query_dispositions AS d
                    LEFT JOIN execution_decision_callbacks AS n
                     ON n.receipt_id=d.native_receipt_id AND n.intent_id=d.intent_id
                    LEFT JOIN execution_decision_callbacks AS q
                     ON q.receipt_id=d.query_receipt_id AND q.intent_id=d.intent_id
                   WHERE d.native_receipt_id=?""",
                (native_receipt_id,),
            ).fetchone()
            if row is None:
                return None
            if row["native_callback_id"] is None or row["query_callback_id"] is None:
                raise ExecutionDecisionJournalError("CALLBACK_QUERY_DISPOSITION_CORRUPT")
            proof_json = row["proof_payload_json"]
            if _sha256_text(proof_json) != row["proof_sha256"]:
                raise ExecutionDecisionJournalError("CALLBACK_QUERY_DISPOSITION_CORRUPT")
            try:
                proof = json.loads(proof_json)
                native_evidence = json.loads(row["native_evidence_json"])
                query_evidence = json.loads(row["query_evidence_json"])
            except (TypeError, ValueError) as error:
                raise ExecutionDecisionJournalError("CALLBACK_QUERY_DISPOSITION_CORRUPT") from error
            if (
                not isinstance(proof, Mapping)
                or proof.get("native_receipt_id") != row["native_receipt_id"]
                or proof.get("query_receipt_id") != row["query_receipt_id"]
                or proof.get("intent_id") != row["intent_id"]
                or proof.get("execution_id") != row["execution_id"]
                or proof.get("disposition_code") != _CALLBACK_QUERY_DISPOSITION
                or proof.get("native_callback_id") != row["native_callback_id"]
                or proof.get("query_callback_id") != row["query_callback_id"]
                or proof.get("native_evidence_sha256") != _sha256_text(row["native_evidence_json"])
                or proof.get("query_evidence_sha256") != _sha256_text(row["query_evidence_json"])
                or row["disposition_code"] != _CALLBACK_QUERY_DISPOSITION
                or row["native_acknowledged"] != 0
                or row["native_delivery_pending"] != 0
                or row["query_acknowledged"] != 1
                or not isinstance(row["query_process_instance_id"], str)
                or not row["query_process_instance_id"]
                or not isinstance(row["native_process_instance_id"], str)
                or not row["native_process_instance_id"]
                or row["query_process_instance_id"] == row["native_process_instance_id"]
            ):
                raise ExecutionDecisionJournalError("CALLBACK_QUERY_DISPOSITION_CORRUPT")
            cursor = self._connection.cursor()
            try:
                self._validate_callback_query_disposition_proof(
                    cursor,
                    proof,
                    native_receipt_id=row["native_receipt_id"],
                    query_receipt_id=row["query_receipt_id"],
                    intent_id=row["intent_id"],
                    execution_id=row["execution_id"],
                    native_callback_id=row["native_callback_id"],
                    query_callback_id=row["query_callback_id"],
                    native_evidence_sha256=_sha256_text(row["native_evidence_json"]),
                    query_evidence_sha256=_sha256_text(row["query_evidence_json"]),
                    native_evidence=native_evidence,
                    query_evidence=query_evidence,
                )
            except ExecutionDecisionJournalError as error:
                raise ExecutionDecisionJournalError("CALLBACK_QUERY_DISPOSITION_CORRUPT") from error
            finally:
                cursor.close()
            return _callback_query_disposition_record(row)

    def active_instrument_owner(
        self, account_scope: str, instrument: str
    ) -> Optional[ExecutionInstrumentOwner]:
        """Read the durable owner that blocks another run for this instrument."""

        _require_identifier(account_scope, "INVALID_ACCOUNT_SCOPE")
        _require_identifier(instrument, "INVALID_INSTRUMENT")
        with self._read_lock():
            row = self._connection.execute(
                """SELECT o.account_scope, o.instrument, o.owner_intent_id,
                          o.cancel_intent_id, i.state
                   FROM execution_instrument_owners AS o
                   JOIN execution_decision_intents AS i ON i.intent_id = o.owner_intent_id
                   WHERE o.account_scope = ? AND o.instrument = ?
                     AND o.owner_intent_id IS NOT NULL""",
                (account_scope, instrument),
            ).fetchone()
        if row is None:
            return None
        return ExecutionInstrumentOwner(
            account_scope=row["account_scope"],
            instrument=row["instrument"],
            intent_id=row["owner_intent_id"],
            state=row["state"],
            cancel_intent_id=row["cancel_intent_id"],
        )

    def record_reconciliation(
        self,
        intent_id: str,
        *,
        reconciliation_id: str,
        query_id: str,
        state: str,
        provider_identity: Optional[Mapping[str, Any]] = None,
        outcome_code: Optional[str] = None,
        terminal_state: Optional[str] = None,
        terminal_event_id: Optional[str] = None,
        position_snapshot_id: Optional[str] = None,
        position_flat: Optional[bool] = None,
    ) -> ExecutionIntentReconciliation:
        """Append a query observation while preserving the original dispatch.

        A query returning UNKNOWN appends evidence and leaves the intent
        unresolved. A later KNOWN query may update current knowledge, but the
        original ``dispatch_state`` and response fields remain immutable and
        the dispatch claim never becomes available again. Terminal release
        facts are stored with this query so release cannot accept detached
        caller-supplied booleans or identifiers.
        """

        _require_identifier(intent_id, "INVALID_INTENT_ID")
        _require_identifier(reconciliation_id, "INVALID_RECONCILIATION_ID")
        _require_identifier(query_id, "INVALID_RECONCILIATION_QUERY_ID")
        if state not in ("KNOWN", "UNKNOWN"):
            raise ExecutionDecisionJournalError("INVALID_RECONCILIATION_STATE")
        if outcome_code is not None and not _identifier(outcome_code):
            raise ExecutionDecisionJournalError("INVALID_OUTCOME_CODE")
        identity_json = self._payload_json({} if provider_identity is None else provider_identity)
        terminal_values = (
            terminal_state,
            terminal_event_id,
            position_snapshot_id,
            position_flat,
        )
        has_terminal_evidence = any(value is not None for value in terminal_values)
        if state == "UNKNOWN" and has_terminal_evidence:
            raise ExecutionDecisionJournalError("UNKNOWN_WITH_TERMINAL_EVIDENCE")
        if has_terminal_evidence:
            if terminal_state not in ("FILLED", "CANCELLED", "REJECTED"):
                raise ExecutionDecisionJournalError("INVALID_TERMINAL_STATE")
            _require_identifier(terminal_event_id, "INVALID_TERMINAL_EVENT_ID")
            _require_identifier(position_snapshot_id, "INVALID_POSITION_SNAPSHOT_ID")
            if type(position_flat) is not bool:
                raise ExecutionDecisionJournalError("INVALID_POSITION_FLAT_FACT")
        terminal_json = None if terminal_state is None else terminal_state
        now_ns = time.time_ns()

        with self._transaction() as cursor:
            intent_row = cursor.execute(
                "SELECT * FROM execution_decision_intents WHERE intent_id = ?", (intent_id,)
            ).fetchone()
            if intent_row is None:
                raise ExecutionDecisionJournalError("INTENT_NOT_PREPARED")
            if intent_row["dispatch_state"] not in ("KNOWN", "UNKNOWN"):
                raise ExecutionDecisionJournalError("DISPATCH_RESULT_REQUIRED")

            existing = cursor.execute(
                "SELECT * FROM execution_intent_reconciliations WHERE reconciliation_id = ?",
                (reconciliation_id,),
            ).fetchone()
            if existing is not None:
                if not _reconciliation_matches(
                    existing,
                    intent_id=intent_id,
                    original_identity_json=intent_row["original_identity_json"],
                    query_id=query_id,
                    state=state,
                    provider_identity_json=identity_json,
                    outcome_code=outcome_code,
                    terminal_state=terminal_json,
                    terminal_event_id=terminal_event_id,
                    position_snapshot_id=position_snapshot_id,
                    position_flat=position_flat,
                ):
                    raise ExecutionDecisionJournalError("RECONCILIATION_CONFLICT")
                return _reconciliation_record(existing)

            same_query = cursor.execute(
                """SELECT reconciliation_id FROM execution_intent_reconciliations
                   WHERE intent_id = ? AND query_id = ?""",
                (intent_id, query_id),
            ).fetchone()
            if same_query is not None:
                raise ExecutionDecisionJournalError("RECONCILIATION_QUERY_CONFLICT")

            with track_durable_row_change(
                cursor, "execution_intent_reconciliations", (reconciliation_id,), "SETTLEMENT"
            ):
                cursor.execute(
                    """INSERT INTO execution_intent_reconciliations
                       (reconciliation_id, intent_id, original_identity_json, query_id,
                        state, provider_identity_json, outcome_code, terminal_state,
                        terminal_event_id, position_snapshot_id, position_flat, created_at_ns)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        reconciliation_id,
                        intent_id,
                        intent_row["original_identity_json"],
                        query_id,
                        state,
                        identity_json,
                        outcome_code,
                        terminal_json,
                        terminal_event_id,
                        position_snapshot_id,
                        None if position_flat is None else int(position_flat),
                        now_ns,
                    ),
                )
            if state == "KNOWN" and intent_row["state"] == "UNKNOWN":
                with track_durable_row_change(
                    cursor, "execution_decision_intents", (intent_id,), "SETTLEMENT"
                ):
                    cursor.execute(
                        """UPDATE execution_decision_intents SET state = 'KNOWN', updated_at_ns = ?
                           WHERE intent_id = ? AND state = 'UNKNOWN'""",
                        (now_ns, intent_id),
                    )
            row = cursor.execute(
                "SELECT * FROM execution_intent_reconciliations WHERE reconciliation_id = ?",
                (reconciliation_id,),
            ).fetchone()
            return _reconciliation_record(row)

    def reconciliations(
        self, intent_id: str, *, limit: int
    ) -> Tuple[ExecutionIntentReconciliation, ...]:
        """Return a bounded, immutable history of query observations."""

        _require_identifier(intent_id, "INVALID_INTENT_ID")
        if type(limit) is not int or not 1 <= limit <= 4096:
            raise ExecutionDecisionJournalError("INVALID_RECONCILIATION_LIMIT")
        with self._read_lock():
            rows = self._connection.execute(
                """SELECT * FROM execution_intent_reconciliations WHERE intent_id = ?
                   ORDER BY created_at_ns, reconciliation_id LIMIT ?""",
                (intent_id, limit),
            ).fetchall()
        return tuple(_reconciliation_record(row) for row in rows)

    def reconciliation(self, reconciliation_id: str) -> Optional[ExecutionIntentReconciliation]:
        """Read one exact durable query observation by its immutable identity."""

        _require_identifier(reconciliation_id, "INVALID_RECONCILIATION_ID")
        with self._read_lock():
            row = self._connection.execute(
                "SELECT * FROM execution_intent_reconciliations WHERE reconciliation_id=?",
                (reconciliation_id,),
            ).fetchone()
        return None if row is None else _reconciliation_record(row)

    def instrument_resolution(self, intent_id: str) -> Optional[ExecutionInstrumentResolution]:
        """Read the terminal resolution that freed one pending-order owner."""

        _require_identifier(intent_id, "INVALID_INTENT_ID")
        with self._read_lock():
            row = self._connection.execute(
                "SELECT * FROM execution_intent_resolutions WHERE intent_id=?",
                (intent_id,),
            ).fetchone()
        return None if row is None else _resolution_record(row)

    def release_instrument_owner(
        self, intent_id: str, *, reconciliation_id: str
    ) -> ExecutionInstrumentResolution:
        """Release a pending-order owner using a stored terminal reconciliation.

        The selected route must establish that the query, event, and position
        snapshot are authoritative before recording them. This generic journal
        binds those evidence identities but cannot verify their provenance or
        decide whether a non-flat position permits an OPEN versus CLOSE. A
        Strategy integration must apply its actual Broker-position and risk
        policy before preparing a later decision.
        """

        _require_identifier(intent_id, "INVALID_INTENT_ID")
        _require_identifier(reconciliation_id, "INVALID_RECONCILIATION_ID")
        with self._transaction() as cursor:
            return self._release_instrument_owner_in_transaction(
                cursor,
                intent_id,
                reconciliation_id=reconciliation_id,
                now_ns=time.time_ns(),
            )

    def record_dispatching_no_fill_terminal(
        self,
        intent_id: str,
        *,
        reconciliation_id: str,
        query_id: str,
        provider_identity: Mapping[str, Any],
        terminal_state: str,
        terminal_event_id: str,
        position_snapshot_id: str,
        expected_original_identity: Mapping[str, Any],
    ) -> Tuple[ExecutionIntentReconciliation, ExecutionInstrumentResolution]:
        """Atomically recover one crashed INSERT proven terminal with no fills.

        This is the sole path that may resolve ``DISPATCHING`` with a NULL
        dispatch result. It deliberately leaves all provider ACK/UNKNOWN
        fields NULL: a complete query proves the order's current terminal
        state, not what the interrupted synchronous RPC returned.
        """

        _require_identifier(intent_id, "INVALID_INTENT_ID")
        _require_identifier(reconciliation_id, "INVALID_RECONCILIATION_ID")
        _require_identifier(query_id, "INVALID_RECONCILIATION_QUERY_ID")
        _require_identifier(terminal_event_id, "INVALID_TERMINAL_EVENT_ID")
        _require_identifier(position_snapshot_id, "INVALID_POSITION_SNAPSHOT_ID")
        if terminal_state not in ("CANCELLED", "REJECTED"):
            raise ExecutionDecisionJournalError("INVALID_TERMINAL_STATE")
        if not isinstance(provider_identity, Mapping) or not isinstance(
            expected_original_identity, Mapping
        ):
            raise ExecutionDecisionJournalError("INVALID_JOURNAL_PAYLOAD")
        try:
            provider_json = self._payload_json(provider_identity)
            expected_identity_json = self._payload_json(expected_original_identity)
        except (TypeError, ValueError) as error:
            raise ExecutionDecisionJournalError("INVALID_JOURNAL_PAYLOAD") from error
        now_ns = time.time_ns()

        with self._transaction() as cursor:
            intent_row = cursor.execute(
                """SELECT i.*,d.business_key_json FROM execution_decision_intents AS i
                   JOIN execution_decisions AS d ON d.decision_id=i.decision_id
                   WHERE i.intent_id=?""",
                (intent_id,),
            ).fetchone()
            if intent_row is None:
                raise ExecutionDecisionJournalError("INTENT_NOT_PREPARED")
            intent_key = ExecutionIntentKey(**json.loads(intent_row["intent_key_json"]))
            business_key = json.loads(intent_row["business_key_json"])
            original_identity = json.loads(intent_row["original_identity_json"])
            economics = json.loads(intent_row["economic_payload_json"])
            if (
                intent_key.action != "SUBMIT"
                or intent_key.position_effect != "OPEN"
                or intent_row["original_identity_json"] != expected_identity_json
                or original_identity.get("operation") != "insert"
                or not _dispatching_no_fill_provider_identity_matches(
                    provider_identity,
                    intent_id=intent_id,
                    intent_key=intent_key,
                    business_key=business_key,
                    original_identity=original_identity,
                    economics=economics,
                    query_id=query_id,
                    terminal_state=terminal_state,
                    terminal_event_id=terminal_event_id,
                    position_snapshot_id=position_snapshot_id,
                )
            ):
                raise ExecutionDecisionJournalError("DISPATCHING_NO_FILL_EVIDENCE_MISMATCH")

            existing_resolution = cursor.execute(
                "SELECT * FROM execution_intent_resolutions WHERE intent_id=?", (intent_id,)
            ).fetchone()
            if existing_resolution is not None:
                if (
                    intent_row["state"] != "KNOWN"
                    or intent_row["dispatch_state"] is not None
                    or intent_row["provider_identity_json"] is not None
                    or intent_row["outcome_code"] is not None
                    or intent_row["dispatch_result_json"] is not None
                ):
                    raise ExecutionDecisionJournalError("DISPATCHING_NO_FILL_RECOVERY_CONFLICT")
                existing_reconciliation = cursor.execute(
                    """SELECT * FROM execution_intent_reconciliations
                       WHERE reconciliation_id=? AND intent_id=?""",
                    (existing_resolution["reconciliation_id"], intent_id),
                ).fetchone()
                if not _dispatching_no_fill_replay_matches(
                    existing_reconciliation,
                    provider_identity=provider_identity,
                    original_identity_json=intent_row["original_identity_json"],
                    terminal_state=terminal_state,
                ):
                    raise ExecutionDecisionJournalError("DISPATCHING_NO_FILL_RECOVERY_CONFLICT")
                durable_reconciliation_id = existing_resolution["reconciliation_id"]
                resolution = self._release_instrument_owner_in_transaction(
                    cursor,
                    intent_id,
                    reconciliation_id=durable_reconciliation_id,
                    now_ns=now_ns,
                    allow_dispatching_no_fill=True,
                )
                return _reconciliation_record(existing_reconciliation), resolution

            if (
                intent_row["state"] != "DISPATCHING"
                or intent_row["dispatch_state"] is not None
                or intent_row["provider_identity_json"] is not None
                or intent_row["outcome_code"] is not None
                or intent_row["dispatch_result_json"] is not None
            ):
                raise ExecutionDecisionJournalError("DISPATCHING_NO_FILL_STATE_MISMATCH")
            callbacks = cursor.execute(
                """SELECT evidence_payload_json FROM execution_decision_callbacks
                   WHERE intent_id=? LIMIT 4097""",
                (intent_id,),
            ).fetchall()
            if len(callbacks) > 4096:
                raise ExecutionDecisionJournalError("DISPATCHING_NO_FILL_CALLBACKS_UNBOUNDED")
            for callback in callbacks:
                try:
                    callback_payload = json.loads(callback["evidence_payload_json"])
                except (TypeError, ValueError) as error:
                    raise ExecutionDecisionJournalError(
                        "DISPATCHING_NO_FILL_CALLBACK_CONFLICT"
                    ) from error
                if isinstance(callback_payload, Mapping) and callback_payload.get("event_type") in (
                    "execution_fill",
                    "unresolved_trade_callback",
                ):
                    raise ExecutionDecisionJournalError("DISPATCHING_NO_FILL_CALLBACK_CONFLICT")
            owner = cursor.execute(
                """SELECT owner_intent_id,cancel_intent_id FROM execution_instrument_owners
                   WHERE account_scope=? AND instrument=?""",
                (business_key["account_scope"], intent_key.instrument),
            ).fetchone()
            if (
                owner is None
                or owner["owner_intent_id"] != intent_id
                or owner["cancel_intent_id"] is not None
            ):
                raise ExecutionDecisionJournalError("INSTRUMENT_OWNER_MISMATCH")

            same_query = cursor.execute(
                """SELECT reconciliation_id FROM execution_intent_reconciliations
                   WHERE intent_id=? AND query_id=?""",
                (intent_id, query_id),
            ).fetchone()
            if same_query is not None:
                raise ExecutionDecisionJournalError("RECONCILIATION_QUERY_CONFLICT")
            with track_durable_row_change(
                cursor, "execution_intent_reconciliations", (reconciliation_id,), "SETTLEMENT"
            ):
                cursor.execute(
                    """INSERT INTO execution_intent_reconciliations
                       (reconciliation_id,intent_id,original_identity_json,query_id,state,
                        provider_identity_json,outcome_code,terminal_state,terminal_event_id,
                        position_snapshot_id,position_flat,created_at_ns)
                       VALUES(?,?,?,?,?,?,?,?,?,?,1,?)""",
                    (
                        reconciliation_id,
                        intent_id,
                        intent_row["original_identity_json"],
                        query_id,
                        "KNOWN",
                        provider_json,
                        _DISPATCHING_CRASH_NO_FILL_OUTCOME,
                        terminal_state,
                        terminal_event_id,
                        position_snapshot_id,
                        now_ns,
                    ),
                )
            with track_durable_row_change(
                cursor, "execution_decision_intents", (intent_id,), "SETTLEMENT"
            ):
                updated = cursor.execute(
                    """UPDATE execution_decision_intents SET state='KNOWN',updated_at_ns=?
                       WHERE intent_id=? AND state='DISPATCHING' AND dispatch_state IS NULL
                         AND provider_identity_json IS NULL AND outcome_code IS NULL
                         AND dispatch_result_json IS NULL""",
                    (now_ns, intent_id),
                )
            if updated.rowcount != 1:
                raise ExecutionDecisionJournalError("DISPATCHING_NO_FILL_STATE_MISMATCH")
            resolution = self._release_instrument_owner_in_transaction(
                cursor,
                intent_id,
                reconciliation_id=reconciliation_id,
                now_ns=now_ns,
                allow_dispatching_no_fill=True,
            )
            reconciliation = cursor.execute(
                """SELECT * FROM execution_intent_reconciliations
                   WHERE reconciliation_id=?""",
                (reconciliation_id,),
            ).fetchone()
            return _reconciliation_record(reconciliation), resolution

    def record_dispatching_cancel_terminal(
        self,
        parent_intent_id: str,
        cancel_intent_id: str,
        *,
        parent_reconciliation_id: str,
        cancel_reconciliation_id: str,
        query_id: str,
        parent_provider_identity: Mapping[str, Any],
        cancel_provider_identity: Mapping[str, Any],
        terminal_state: str,
        terminal_event_id: str,
        position_snapshot_id: str,
        position_flat: bool,
        expected_parent_original_identity: Mapping[str, Any],
        expected_cancel_original_identity: Mapping[str, Any],
    ) -> Tuple[
        ExecutionIntentReconciliation,
        ExecutionIntentReconciliation,
        ExecutionInstrumentResolution,
    ]:
        """Resolve a crashed CANCEL from one exact original-order terminal query.

        The parent SUBMIT keeps its recorded KNOWN dispatch result. The child
        CANCEL changes from DISPATCHING to KNOWN while all four dispatch-result
        columns remain NULL: terminal order evidence does not reconstruct the
        interrupted cancel RPC response. Both reconciliation proofs, that CAS,
        the parent resolution, and release of the pending-order owner are one
        settlement transaction. FactorPositionBook ownership is deliberately
        independent and is never changed here.

        The provider mappings bind both proofs to the same order observation.
        Their ``observation_id``, ``query_set_id``, ``snapshot_id`` and
        ``position_snapshot_id`` values must agree, and the parent proof names
        the child proof and intent. A caller must validate the complete query,
        fills, positions, and callback evidence before using this journal CAS.
        """

        for value, code in (
            (parent_intent_id, "INVALID_INTENT_ID"),
            (cancel_intent_id, "INVALID_INTENT_ID"),
            (parent_reconciliation_id, "INVALID_RECONCILIATION_ID"),
            (cancel_reconciliation_id, "INVALID_RECONCILIATION_ID"),
            (query_id, "INVALID_RECONCILIATION_QUERY_ID"),
            (terminal_event_id, "INVALID_TERMINAL_EVENT_ID"),
            (position_snapshot_id, "INVALID_POSITION_SNAPSHOT_ID"),
        ):
            _require_identifier(value, code)
        if parent_reconciliation_id == cancel_reconciliation_id:
            raise ExecutionDecisionJournalError(
                "DISPATCHING_CANCEL_RECONCILIATION_IDS_NOT_DISTINCT"
            )
        if terminal_state != "CANCELLED":
            raise ExecutionDecisionJournalError("INVALID_TERMINAL_STATE")
        if type(position_flat) is not bool:
            raise ExecutionDecisionJournalError("INVALID_POSITION_FLAT_FACT")
        if terminal_event_id != query_id:
            raise ExecutionDecisionJournalError("DISPATCHING_CANCEL_EVIDENCE_MISMATCH")
        try:
            parent_identity_json = self._payload_json(expected_parent_original_identity)
            cancel_identity_json = self._payload_json(expected_cancel_original_identity)
            parent_provider_json = self._payload_json(parent_provider_identity)
            cancel_provider_json = self._payload_json(cancel_provider_identity)
        except ExecutionDecisionJournalError:
            raise
        except (TypeError, ValueError) as error:
            raise ExecutionDecisionJournalError("INVALID_JOURNAL_PAYLOAD") from error
        if not _dispatching_cancel_terminal_providers_match(
            parent_intent_id=parent_intent_id,
            cancel_intent_id=cancel_intent_id,
            parent_reconciliation_id=parent_reconciliation_id,
            cancel_reconciliation_id=cancel_reconciliation_id,
            query_id=query_id,
            position_snapshot_id=position_snapshot_id,
            parent_provider_identity=parent_provider_identity,
            cancel_provider_identity=cancel_provider_identity,
        ):
            raise ExecutionDecisionJournalError("DISPATCHING_CANCEL_EVIDENCE_MISMATCH")

        now_ns = time.time_ns()
        with self._transaction() as cursor:
            parent = cursor.execute(
                """SELECT i.*,d.business_key_json FROM execution_decision_intents AS i
                   JOIN execution_decisions AS d ON d.decision_id=i.decision_id
                   WHERE i.intent_id=?""",
                (parent_intent_id,),
            ).fetchone()
            cancel = cursor.execute(
                """SELECT i.*,d.business_key_json FROM execution_decision_intents AS i
                   JOIN execution_decisions AS d ON d.decision_id=i.decision_id
                   WHERE i.intent_id=?""",
                (cancel_intent_id,),
            ).fetchone()
            if parent is None or cancel is None:
                raise ExecutionDecisionJournalError("INTENT_NOT_PREPARED")

            try:
                parent_key = ExecutionIntentKey(**json.loads(parent["intent_key_json"]))
                cancel_key = ExecutionIntentKey(**json.loads(cancel["intent_key_json"]))
                parent_business = json.loads(parent["business_key_json"])
                cancel_business = json.loads(cancel["business_key_json"])
                parent_identity = json.loads(parent["original_identity_json"])
                cancel_identity = json.loads(cancel["original_identity_json"])
            except (TypeError, ValueError) as error:
                raise ExecutionDecisionJournalError("DISPATCHING_CANCEL_STATE_MISMATCH") from error

            if (
                parent["original_identity_json"] != parent_identity_json
                or cancel["original_identity_json"] != cancel_identity_json
                or parent_key.action != "SUBMIT"
                or cancel_key.action != "CANCEL"
                or parent_key.instrument != cancel_key.instrument
                or parent_key.side != cancel_key.side
                or parent_key.position_effect != cancel_key.position_effect
                or parent_business.get("account_scope") != cancel_business.get("account_scope")
                or parent_business.get("strategy_scope") != cancel_business.get("strategy_scope")
                or cancel["owner_intent_id"] != parent_intent_id
                or parent_identity.get("operation") != "insert"
                or cancel_identity.get("operation") != "cancel"
                or cancel_identity.get("owner_intent_id") != parent_intent_id
                or parent_identity.get("order_ref") != cancel_identity.get("order_ref")
                or not _identifier(parent_identity.get("order_ref"))
                or parent_identity.get("instrument_id") != parent_key.instrument
                or cancel_identity.get("instrument_id") != cancel_key.instrument
                or parent_identity.get("exchange_id") != cancel_identity.get("exchange_id")
                or not _identifier(parent_identity.get("exchange_id"))
                or not _identifier(parent_identity.get("account_fingerprint"))
                or not _identifier(parent_identity.get("trading_day"))
                or len(parent_identity["trading_day"]) != 8
                or not parent_identity["trading_day"].isdigit()
                or type(parent_identity.get("connection_generation")) is not int
                or parent_identity["connection_generation"] <= 0
                or type(parent_identity.get("front_id")) is not int
                or parent_identity["front_id"] <= 0
                or type(parent_identity.get("session_id")) is not int
                or parent_identity["session_id"] <= 0
                or any(
                    parent_identity.get(name) != cancel_identity.get(name)
                    for name in (
                        "account_fingerprint",
                        "connection_generation",
                        "trading_day",
                        "front_id",
                        "session_id",
                    )
                    if name in parent_identity or name in cancel_identity
                )
            ):
                raise ExecutionDecisionJournalError("DISPATCHING_CANCEL_EVIDENCE_MISMATCH")

            if (
                parent["state"] != "KNOWN"
                or parent["dispatch_state"] != "KNOWN"
                or parent["provider_identity_json"] is None
                or parent["dispatch_result_json"] is None
            ):
                raise ExecutionDecisionJournalError("DISPATCHING_CANCEL_PARENT_NOT_KNOWN")

            parent_resolution = cursor.execute(
                "SELECT * FROM execution_intent_resolutions WHERE intent_id=?",
                (parent_intent_id,),
            ).fetchone()
            cancel_resolution = cursor.execute(
                "SELECT * FROM execution_intent_resolutions WHERE intent_id=?",
                (cancel_intent_id,),
            ).fetchone()
            stored_parent_proof = cursor.execute(
                "SELECT * FROM execution_intent_reconciliations WHERE reconciliation_id=?",
                (parent_reconciliation_id,),
            ).fetchone()
            stored_cancel_proof = cursor.execute(
                "SELECT * FROM execution_intent_reconciliations WHERE reconciliation_id=?",
                (cancel_reconciliation_id,),
            ).fetchone()

            if parent_resolution is not None or cancel_resolution is not None:
                if (
                    cancel["state"] != "KNOWN"
                    or cancel["dispatch_state"] is not None
                    or cancel["provider_identity_json"] is not None
                    or cancel["outcome_code"] is not None
                    or cancel["dispatch_result_json"] is not None
                    or cancel_resolution is not None
                    or parent_resolution is None
                    or stored_parent_proof is None
                    or stored_cancel_proof is None
                    or not _reconciliation_matches(
                        stored_cancel_proof,
                        intent_id=cancel_intent_id,
                        original_identity_json=cancel_identity_json,
                        query_id=query_id,
                        state="KNOWN",
                        provider_identity_json=cancel_provider_json,
                        outcome_code=_DISPATCHING_CANCEL_CHILD_OUTCOME,
                        terminal_state=terminal_state,
                        terminal_event_id=terminal_event_id,
                        position_snapshot_id=position_snapshot_id,
                        position_flat=position_flat,
                    )
                    or not _reconciliation_matches(
                        stored_parent_proof,
                        intent_id=parent_intent_id,
                        original_identity_json=parent_identity_json,
                        query_id=query_id,
                        state="KNOWN",
                        provider_identity_json=parent_provider_json,
                        outcome_code=_DISPATCHING_CANCEL_PARENT_OUTCOME,
                        terminal_state=terminal_state,
                        terminal_event_id=terminal_event_id,
                        position_snapshot_id=position_snapshot_id,
                        position_flat=position_flat,
                    )
                    or (
                        parent_resolution["account_scope"],
                        parent_resolution["instrument"],
                        parent_resolution["terminal_state"],
                        parent_resolution["terminal_event_id"],
                        parent_resolution["reconciliation_id"],
                        parent_resolution["position_snapshot_id"],
                        int(parent_resolution["position_flat"]),
                    )
                    != (
                        parent_business["account_scope"],
                        parent_key.instrument,
                        terminal_state,
                        terminal_event_id,
                        parent_reconciliation_id,
                        position_snapshot_id,
                        int(position_flat),
                    )
                ):
                    raise ExecutionDecisionJournalError("DISPATCHING_CANCEL_RECOVERY_CONFLICT")
                current_owner = cursor.execute(
                    """SELECT owner_intent_id,cancel_intent_id
                       FROM execution_instrument_owners
                       WHERE account_scope=? AND instrument=?""",
                    (parent_business["account_scope"], parent_key.instrument),
                ).fetchone()
                if current_owner is None or (
                    current_owner["owner_intent_id"] == parent_intent_id
                    or current_owner["cancel_intent_id"] == cancel_intent_id
                ):
                    raise ExecutionDecisionJournalError("DISPATCHING_CANCEL_RECOVERY_CONFLICT")
                return (
                    _reconciliation_record(stored_cancel_proof),
                    _reconciliation_record(stored_parent_proof),
                    _resolution_record(parent_resolution),
                )

            if (
                cancel["state"] != "DISPATCHING"
                or cancel["dispatch_state"] is not None
                or cancel["provider_identity_json"] is not None
                or cancel["outcome_code"] is not None
                or cancel["dispatch_result_json"] is not None
            ):
                raise ExecutionDecisionJournalError("DISPATCHING_CANCEL_STATE_MISMATCH")

            owner = cursor.execute(
                """SELECT owner_intent_id,cancel_intent_id FROM execution_instrument_owners
                   WHERE account_scope=? AND instrument=?""",
                (parent_business["account_scope"], parent_key.instrument),
            ).fetchone()
            if (
                owner is None
                or owner["owner_intent_id"] != parent_intent_id
                or owner["cancel_intent_id"] != cancel_intent_id
            ):
                raise ExecutionDecisionJournalError("INSTRUMENT_OWNER_MISMATCH")

            if stored_parent_proof is not None or stored_cancel_proof is not None:
                raise ExecutionDecisionJournalError("DISPATCHING_CANCEL_RECOVERY_CONFLICT")
            for intent_id in (parent_intent_id, cancel_intent_id):
                same_query = cursor.execute(
                    """SELECT reconciliation_id FROM execution_intent_reconciliations
                       WHERE intent_id=? AND query_id=?""",
                    (intent_id, query_id),
                ).fetchone()
                if same_query is not None:
                    raise ExecutionDecisionJournalError("RECONCILIATION_QUERY_CONFLICT")

            proof_values = (
                terminal_state,
                terminal_event_id,
                position_snapshot_id,
                int(position_flat),
                now_ns,
            )
            with track_durable_row_change(
                cursor,
                "execution_intent_reconciliations",
                (cancel_reconciliation_id,),
                "SETTLEMENT",
            ):
                inserted = cursor.execute(
                    """INSERT INTO execution_intent_reconciliations
                       (reconciliation_id,intent_id,original_identity_json,query_id,state,
                        provider_identity_json,outcome_code,terminal_state,terminal_event_id,
                        position_snapshot_id,position_flat,created_at_ns)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        cancel_reconciliation_id,
                        cancel_intent_id,
                        cancel_identity_json,
                        query_id,
                        "KNOWN",
                        cancel_provider_json,
                        _DISPATCHING_CANCEL_CHILD_OUTCOME,
                    )
                    + proof_values,
                )
            if inserted.rowcount != 1:
                raise ExecutionDecisionJournalError("DISPATCHING_CANCEL_RECOVERY_CONFLICT")
            with track_durable_row_change(
                cursor,
                "execution_intent_reconciliations",
                (parent_reconciliation_id,),
                "SETTLEMENT",
            ):
                inserted = cursor.execute(
                    """INSERT INTO execution_intent_reconciliations
                       (reconciliation_id,intent_id,original_identity_json,query_id,state,
                        provider_identity_json,outcome_code,terminal_state,terminal_event_id,
                        position_snapshot_id,position_flat,created_at_ns)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        parent_reconciliation_id,
                        parent_intent_id,
                        parent_identity_json,
                        query_id,
                        "KNOWN",
                        parent_provider_json,
                        _DISPATCHING_CANCEL_PARENT_OUTCOME,
                    )
                    + proof_values,
                )
            if inserted.rowcount != 1:
                raise ExecutionDecisionJournalError("DISPATCHING_CANCEL_RECOVERY_CONFLICT")

            with track_durable_row_change(
                cursor, "execution_decision_intents", (cancel_intent_id,), "SETTLEMENT"
            ):
                updated = cursor.execute(
                    """UPDATE execution_decision_intents
                       SET state='KNOWN',updated_at_ns=?
                       WHERE intent_id=? AND owner_intent_id=? AND state='DISPATCHING'
                         AND dispatch_state IS NULL AND provider_identity_json IS NULL
                         AND outcome_code IS NULL AND dispatch_result_json IS NULL""",
                    (now_ns, cancel_intent_id, parent_intent_id),
                )
            if updated.rowcount != 1:
                raise ExecutionDecisionJournalError("DISPATCHING_CANCEL_STATE_MISMATCH")

            with track_durable_row_change(
                cursor,
                "execution_intent_resolutions",
                (parent_intent_id,),
                "SETTLEMENT",
            ):
                inserted = cursor.execute(
                    """INSERT INTO execution_intent_resolutions
                       (intent_id,account_scope,instrument,terminal_state,terminal_event_id,
                        reconciliation_id,position_snapshot_id,position_flat,created_at_ns)
                       VALUES(?,?,?,?,?,?,?,?,?)""",
                    (
                        parent_intent_id,
                        parent_business["account_scope"],
                        parent_key.instrument,
                        terminal_state,
                        terminal_event_id,
                        parent_reconciliation_id,
                        position_snapshot_id,
                        int(position_flat),
                        now_ns,
                    ),
                )
            if inserted.rowcount != 1:
                raise ExecutionDecisionJournalError("DISPATCHING_CANCEL_RECOVERY_CONFLICT")
            with track_durable_row_change(
                cursor,
                "execution_instrument_owners",
                (parent_business["account_scope"], parent_key.instrument),
                "SETTLEMENT",
            ):
                updated = cursor.execute(
                    """UPDATE execution_instrument_owners
                       SET owner_intent_id=NULL,cancel_intent_id=NULL
                       WHERE account_scope=? AND instrument=? AND owner_intent_id=?
                         AND cancel_intent_id=?""",
                    (
                        parent_business["account_scope"],
                        parent_key.instrument,
                        parent_intent_id,
                        cancel_intent_id,
                    ),
                )
            if updated.rowcount != 1:
                raise ExecutionDecisionJournalError("INSTRUMENT_OWNER_MISMATCH")

            cancel_proof = cursor.execute(
                "SELECT * FROM execution_intent_reconciliations WHERE reconciliation_id=?",
                (cancel_reconciliation_id,),
            ).fetchone()
            parent_proof = cursor.execute(
                "SELECT * FROM execution_intent_reconciliations WHERE reconciliation_id=?",
                (parent_reconciliation_id,),
            ).fetchone()
            resolution = cursor.execute(
                "SELECT * FROM execution_intent_resolutions WHERE intent_id=?",
                (parent_intent_id,),
            ).fetchone()
            return (
                _reconciliation_record(cancel_proof),
                _reconciliation_record(parent_proof),
                _resolution_record(resolution),
            )

    def _release_instrument_owner_in_transaction(
        self,
        cursor: sqlite3.Cursor,
        intent_id: str,
        *,
        reconciliation_id: str,
        now_ns: int,
        allow_dispatching_no_fill: bool = False,
    ) -> ExecutionInstrumentResolution:
        intent_row = cursor.execute(
            """SELECT i.*, d.business_key_json FROM execution_decision_intents AS i
               JOIN execution_decisions AS d ON d.decision_id=i.decision_id
               WHERE i.intent_id=?""",
            (intent_id,),
        ).fetchone()
        if intent_row is None:
            raise ExecutionDecisionJournalError("INTENT_NOT_PREPARED")
        intent_key = ExecutionIntentKey(**json.loads(intent_row["intent_key_json"]))
        account_scope = json.loads(intent_row["business_key_json"])["account_scope"]
        if intent_key.action != "SUBMIT" or intent_row["state"] != "KNOWN":
            raise ExecutionDecisionJournalError("INTENT_NOT_RECONCILED_TERMINAL")
        reconciliation = cursor.execute(
            """SELECT * FROM execution_intent_reconciliations
               WHERE reconciliation_id=? AND intent_id=?""",
            (reconciliation_id, intent_id),
        ).fetchone()
        if (
            reconciliation is None
            or reconciliation["state"] != "KNOWN"
            or reconciliation["terminal_state"] is None
            or reconciliation["terminal_event_id"] is None
            or reconciliation["position_snapshot_id"] is None
            or reconciliation["position_flat"] is None
            or reconciliation["original_identity_json"] != intent_row["original_identity_json"]
        ):
            raise ExecutionDecisionJournalError("INTENT_NOT_RECONCILED_TERMINAL")
        dispatching_no_fill = bool(
            allow_dispatching_no_fill
            and reconciliation["outcome_code"] == _DISPATCHING_CRASH_NO_FILL_OUTCOME
            and intent_row["dispatch_state"] is None
            and intent_row["provider_identity_json"] is None
            and intent_row["outcome_code"] is None
            and intent_row["dispatch_result_json"] is None
        )
        if intent_row["dispatch_state"] not in ("KNOWN", "UNKNOWN") and not dispatching_no_fill:
            raise ExecutionDecisionJournalError("DISPATCH_RESULT_REQUIRED")
        values = (
            account_scope,
            intent_key.instrument,
            reconciliation["terminal_state"],
            reconciliation["terminal_event_id"],
            reconciliation_id,
            reconciliation["position_snapshot_id"],
            reconciliation["position_flat"],
        )
        existing = cursor.execute(
            "SELECT * FROM execution_intent_resolutions WHERE intent_id=?", (intent_id,)
        ).fetchone()
        if existing is not None:
            existing_values = (
                existing["account_scope"],
                existing["instrument"],
                existing["terminal_state"],
                existing["terminal_event_id"],
                existing["reconciliation_id"],
                existing["position_snapshot_id"],
                int(existing["position_flat"]),
            )
            if existing_values != values:
                raise ExecutionDecisionJournalError("INSTRUMENT_RESOLUTION_CONFLICT")
            if bool(existing["position_flat"]) and _factor_book_checkpoint_required(
                intent_key, intent_row["economic_payload_json"]
            ):
                from .factor_position_book import record_factor_position_flat_checkpoint

                record_factor_position_flat_checkpoint(
                    cursor,
                    intent_id=intent_id,
                    reconciliation_id=reconciliation_id,
                )
            return _resolution_record(existing)
        owner = cursor.execute(
            """SELECT owner_intent_id FROM execution_instrument_owners
               WHERE account_scope=? AND instrument=?""",
            (account_scope, intent_key.instrument),
        ).fetchone()
        if owner is None or owner["owner_intent_id"] != intent_id:
            raise ExecutionDecisionJournalError("INSTRUMENT_OWNER_MISMATCH")
        with track_durable_row_change(
            cursor, "execution_intent_resolutions", (intent_id,), "SETTLEMENT"
        ):
            cursor.execute(
                """INSERT INTO execution_intent_resolutions
                   (intent_id,account_scope,instrument,terminal_state,terminal_event_id,
                    reconciliation_id,position_snapshot_id,position_flat,created_at_ns)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (intent_id,) + values + (now_ns,),
            )
        with track_durable_row_change(
            cursor,
            "execution_instrument_owners",
            (account_scope, intent_key.instrument),
            "SETTLEMENT",
        ):
            cursor.execute(
                """UPDATE execution_instrument_owners
                   SET owner_intent_id=NULL,cancel_intent_id=NULL
                   WHERE account_scope=? AND instrument=? AND owner_intent_id=?""",
                (account_scope, intent_key.instrument, intent_id),
            )
        if bool(reconciliation["position_flat"]) and _factor_book_checkpoint_required(
            intent_key, intent_row["economic_payload_json"]
        ):
            from .factor_position_book import record_factor_position_flat_checkpoint

            record_factor_position_flat_checkpoint(
                cursor,
                intent_id=intent_id,
                reconciliation_id=reconciliation_id,
            )
        return _resolution_record(
            cursor.execute(
                "SELECT * FROM execution_intent_resolutions WHERE intent_id=?", (intent_id,)
            ).fetchone()
        )

    def abandon_prepared_intent(
        self, intent_id: str, *, reason_code: str
    ) -> ExecutionIntentAbandonment:
        """Abandon one provably never-claimed intent without changing history.

        Only PREPARED intents can be abandoned. DISPATCHING, KNOWN, and UNKNOWN
        intents require reconciliation and can never use this path. The stable
        abandonment identity makes a repeated identical call idempotent.
        """

        _require_identifier(intent_id, "INVALID_INTENT_ID")
        _require_identifier(reason_code, "INVALID_ABANDONMENT_REASON")
        abandonment_id = _stable_id("abandonment", intent_id)
        now_ns = time.time_ns()
        with self._transaction() as cursor:
            row = cursor.execute(
                """SELECT i.*, d.business_key_json FROM execution_decision_intents AS i
                   JOIN execution_decisions AS d ON d.decision_id = i.decision_id
                   WHERE i.intent_id = ?""",
                (intent_id,),
            ).fetchone()
            if row is None:
                raise ExecutionDecisionJournalError("INTENT_NOT_PREPARED")
            existing = cursor.execute(
                "SELECT * FROM execution_intent_abandonments WHERE intent_id = ?", (intent_id,)
            ).fetchone()
            if existing is not None:
                if existing["reason_code"] != reason_code:
                    raise ExecutionDecisionJournalError("INTENT_ABANDONMENT_CONFLICT")
                return _abandonment_record(existing)
            if row["state"] != "PREPARED" or row["dispatch_state"] is not None:
                raise ExecutionDecisionJournalError("INTENT_NOT_ABANDONABLE")

            intent_key = ExecutionIntentKey(**json.loads(row["intent_key_json"]))
            account_scope = json.loads(row["business_key_json"])["account_scope"]
            if intent_key.action == "SUBMIT":
                with track_durable_row_change(
                    cursor,
                    "execution_instrument_owners",
                    (account_scope, intent_key.instrument),
                    "SETTLEMENT",
                ):
                    cursor.execute(
                        """UPDATE execution_instrument_owners
                           SET owner_intent_id = NULL, cancel_intent_id = NULL
                           WHERE account_scope = ? AND instrument = ? AND owner_intent_id = ?""",
                        (account_scope, intent_key.instrument, intent_id),
                    )
            else:
                with track_durable_row_change(
                    cursor,
                    "execution_instrument_owners",
                    (account_scope, intent_key.instrument),
                    "SETTLEMENT",
                ):
                    cursor.execute(
                        """UPDATE execution_instrument_owners SET cancel_intent_id = NULL
                           WHERE account_scope = ? AND instrument = ? AND cancel_intent_id = ?""",
                        (account_scope, intent_key.instrument, intent_id),
                    )
            with track_durable_row_change(
                cursor, "execution_intent_abandonments", (abandonment_id,), "SETTLEMENT"
            ):
                cursor.execute(
                    """INSERT INTO execution_intent_abandonments
                       (abandonment_id, intent_id, reason_code, created_at_ns)
                       VALUES (?, ?, ?, ?)""",
                    (abandonment_id, intent_id, reason_code, now_ns),
                )
            abandonment = cursor.execute(
                "SELECT * FROM execution_intent_abandonments WHERE intent_id = ?", (intent_id,)
            ).fetchone()
            return _abandonment_record(abandonment)

    def abandon_unprepared_slot(
        self,
        decision_id: str,
        intent_key: ExecutionIntentKey,
        *,
        reason_code: str,
    ) -> ExecutionIntentAbandonment:
        """Close a declared slot that never acquired a durable intent.

        A slot is safe to abandon only while no intent row exists. Dispatch
        claim creation always follows intent preparation, so an absent row is
        proof this leg never reached the route boundary.
        """

        _require_identifier(decision_id, "INVALID_DECISION_ID")
        _require_identifier(reason_code, "INVALID_ABANDONMENT_REASON")
        if not isinstance(intent_key, ExecutionIntentKey):
            raise ExecutionDecisionJournalError("INVALID_INTENT_KEY")
        intent_key_json = _canonical_json(_intent_key_values(intent_key))
        intent_id = _stable_id("intent", decision_id + ":" + intent_key_json)
        abandonment_id = _stable_id("slot-abandonment", intent_id)
        now_ns = time.time_ns()
        with self._transaction() as cursor:
            slot = cursor.execute(
                """SELECT decision_id FROM execution_decision_slots WHERE intent_id=?""",
                (intent_id,),
            ).fetchone()
            if slot is None or slot["decision_id"] != decision_id:
                raise ExecutionDecisionJournalError("INTENT_NOT_DECLARED")
            if (
                cursor.execute(
                    "SELECT 1 FROM execution_decision_intents WHERE intent_id=?", (intent_id,)
                ).fetchone()
                is not None
            ):
                raise ExecutionDecisionJournalError("INTENT_ALREADY_PREPARED")
            existing = cursor.execute(
                "SELECT * FROM execution_slot_abandonments WHERE intent_id=?", (intent_id,)
            ).fetchone()
            if existing is not None:
                if existing["reason_code"] != reason_code:
                    raise ExecutionDecisionJournalError("INTENT_ABANDONMENT_CONFLICT")
                return _slot_abandonment_record(existing)
            with track_durable_row_change(
                cursor, "execution_slot_abandonments", (abandonment_id,), "SETTLEMENT"
            ):
                cursor.execute(
                    """INSERT INTO execution_slot_abandonments
                       (abandonment_id, intent_id, reason_code, created_at_ns)
                       VALUES (?, ?, ?, ?)""",
                    (abandonment_id, intent_id, reason_code, now_ns),
                )
            return _slot_abandonment_record(
                cursor.execute(
                    "SELECT * FROM execution_slot_abandonments WHERE intent_id=?", (intent_id,)
                ).fetchone()
            )

    def claim_dispatch(self, intent_id: str) -> Optional[ExecutionDispatchClaim]:
        """Atomically claim the only dispatch attempt for one prepared intent.

        Returns ``None`` for DISPATCHING, KNOWN or UNKNOWN intents.  A process
        restart cannot turn an ambiguous dispatch back into permission to send.
        Multi-intent decisions may dispatch sequentially. Earlier declared
        legs must be KNOWN before a later leg is claimed; an unprepared later
        leg does not make the first leg atomic or block its dispatch.
        """

        _require_identifier(intent_id, "INVALID_INTENT_ID")
        with self._transaction() as cursor:
            row = cursor.execute(
                "SELECT * FROM execution_decision_intents WHERE intent_id = ?", (intent_id,)
            ).fetchone()
            if row is None:
                raise ExecutionDecisionJournalError("INTENT_NOT_PREPARED")
            if (
                cursor.execute(
                    "SELECT 1 FROM execution_intent_abandonments WHERE intent_id = ?", (intent_id,)
                ).fetchone()
                or cursor.execute(
                    "SELECT 1 FROM execution_slot_abandonments WHERE intent_id = ?", (intent_id,)
                ).fetchone()
            ):
                raise ExecutionDecisionJournalError("INTENT_ABANDONED")
            if row["state"] != "PREPARED":
                return None
            intent_key = ExecutionIntentKey(**json.loads(row["intent_key_json"]))
            if intent_key.action == "CANCEL":
                decision_row = cursor.execute(
                    "SELECT business_key_json FROM execution_decisions WHERE decision_id = ?",
                    (row["decision_id"],),
                ).fetchone()
                account_scope = json.loads(decision_row["business_key_json"])["account_scope"]
                owner_row = cursor.execute(
                    """SELECT owner_intent_id FROM execution_instrument_owners
                       WHERE account_scope = ? AND instrument = ?""",
                    (account_scope, intent_key.instrument),
                ).fetchone()
                if owner_row is None or owner_row["owner_intent_id"] != row["owner_intent_id"]:
                    raise ExecutionDecisionJournalError("CANCEL_OWNER_RELEASED")
            prior_unresolved = int(
                cursor.execute(
                    """SELECT COUNT(*) FROM execution_decision_slots AS s
                       JOIN execution_decision_intents AS current
                         ON current.intent_id = ?
                       LEFT JOIN execution_decision_intents AS prior
                         ON prior.intent_id = s.intent_id
                       WHERE s.decision_id = current.decision_id
                         AND s.leg < (SELECT leg FROM execution_decision_slots
                                      WHERE intent_id = ?)
                         AND (prior.intent_id IS NULL OR prior.state <> 'KNOWN')""",
                    (intent_id, intent_id),
                ).fetchone()[0]
            )
            if prior_unresolved:
                raise ExecutionDecisionJournalError("PRIOR_INTENT_NOT_KNOWN")
            decision_row = cursor.execute(
                "SELECT capacity_class FROM execution_decisions WHERE decision_id = ?",
                (row["decision_id"],),
            ).fetchone()
            if decision_row is None:
                raise ExecutionDecisionJournalError("DECISION_NOT_FOUND")
            intent_capacity_class = (
                "SETTLEMENT"
                if intent_key.action == "CANCEL" or intent_key.position_effect == "CLOSE"
                else self._durable_decision_class(decision_row["capacity_class"])
            )
            if intent_key.action == "SUBMIT" and intent_key.position_effect == "OPEN":
                self._ensure_new_open_capacity(cursor)
            now_ns = time.time_ns()
            with track_durable_row_change(
                cursor, "execution_decision_intents", (intent_id,), intent_capacity_class
            ):
                cursor.execute(
                    """UPDATE execution_decision_intents
                       SET state = 'DISPATCHING', updated_at_ns = ?
                       WHERE intent_id = ? AND state = 'PREPARED'""",
                    (now_ns, intent_id),
                )
            if cursor.rowcount != 1:
                raise ExecutionDecisionJournalError("DISPATCH_CLAIM_LOST")
            claimed = cursor.execute(
                "SELECT * FROM execution_decision_intents WHERE intent_id = ?", (intent_id,)
            ).fetchone()
            return ExecutionDispatchClaim(_intent_record(claimed))

    def record_dispatch_result(
        self,
        intent_id: str,
        *,
        state: str,
        provider_identity: Optional[Mapping[str, Any]] = None,
        outcome_code: Optional[str] = None,
    ) -> ExecutionIntentRecord:
        """Record a known or unknown result for the already claimed dispatch."""

        _require_identifier(intent_id, "INVALID_INTENT_ID")
        if state not in ("KNOWN", "UNKNOWN"):
            raise ExecutionDecisionJournalError("INVALID_DISPATCH_STATE")
        if outcome_code is not None and not _identifier(outcome_code):
            raise ExecutionDecisionJournalError("INVALID_OUTCOME_CODE")
        identity_json = self._payload_json({} if provider_identity is None else provider_identity)
        result_json = _canonical_json(
            {"provider_identity": json.loads(identity_json), "outcome_code": outcome_code}
        )
        now_ns = time.time_ns()
        with self._transaction() as cursor:
            row = cursor.execute(
                "SELECT * FROM execution_decision_intents WHERE intent_id = ?", (intent_id,)
            ).fetchone()
            if row is None:
                raise ExecutionDecisionJournalError("INTENT_NOT_PREPARED")
            if row["dispatch_state"] in ("KNOWN", "UNKNOWN"):
                if (
                    row["dispatch_state"] == state
                    and row["provider_identity_json"] == identity_json
                    and row["outcome_code"] == outcome_code
                    and row["dispatch_result_json"] == result_json
                ):
                    return _intent_record(row)
                raise ExecutionDecisionJournalError("DISPATCH_RESULT_CONFLICT")
            if row["state"] != "DISPATCHING":
                raise ExecutionDecisionJournalError("DISPATCH_NOT_CLAIMED")
            # This is durable provider-outcome settlement even when the
            # original decision consumed BASE capacity.
            with track_durable_row_change(
                cursor, "execution_decision_intents", (intent_id,), "SETTLEMENT"
            ):
                cursor.execute(
                    """UPDATE execution_decision_intents
                       SET state = ?, dispatch_state = ?, provider_identity_json = ?, outcome_code = ?,
                           dispatch_result_json = ?, updated_at_ns = ?
                       WHERE intent_id = ? AND state = 'DISPATCHING'""",
                    (state, state, identity_json, outcome_code, result_json, now_ns, intent_id),
                )
            if cursor.rowcount != 1:
                raise ExecutionDecisionJournalError("DISPATCH_RESULT_CONFLICT")
            row = cursor.execute(
                "SELECT * FROM execution_decision_intents WHERE intent_id = ?", (intent_id,)
            ).fetchone()
            return _intent_record(row)

    def recoverable_intents(self, *, limit: int) -> Tuple[ExecutionIntentRecord, ...]:
        """Return bounded intents requiring dispatch or outcome recovery review."""

        if type(limit) is not int or not 1 <= limit <= self.max_pending_intents:
            raise ExecutionDecisionJournalError("INVALID_RECOVERY_LIMIT")
        with self._read_lock():
            rows = self._connection.execute(
                """SELECT * FROM execution_decision_intents
                   WHERE state IN ('PREPARED','DISPATCHING','UNKNOWN')
                     AND NOT EXISTS (
                         SELECT 1 FROM execution_intent_abandonments AS a
                         WHERE a.intent_id = execution_decision_intents.intent_id
                     )
                   ORDER BY created_at_ns, intent_id LIMIT ?""",
                (limit,),
            ).fetchall()
        return tuple(_intent_record(row) for row in rows)

    def execution_intent_snapshot(self, *, limit: int = 128) -> ExecutionIntentSnapshotPage:
        """Return a bounded page of unresolved or still-owned intent evidence.

        The projection is read-only and contains no Backtrader objects. It is
        suitable for strategy/fact reconciliation, not as a command queue.
        """

        if type(limit) is not int or not 1 <= limit <= self.max_pending_intents:
            raise ExecutionDecisionJournalError("INVALID_INTENT_SNAPSHOT_LIMIT")
        with self._read_lock():
            rows = self._connection.execute(
                """SELECT i.*
                   FROM execution_decision_intents AS i
                   WHERE (
                          i.state IN ('PREPARED','DISPATCHING','UNKNOWN')
                          AND NOT EXISTS (
                              SELECT 1 FROM execution_intent_abandonments AS a
                              WHERE a.intent_id=i.intent_id
                          )
                   )
                      OR EXISTS (
                          SELECT 1 FROM execution_instrument_owners AS o
                          WHERE o.owner_intent_id = i.intent_id
                             OR o.cancel_intent_id = i.intent_id
                      )
                   ORDER BY i.created_at_ns, i.intent_id
                   LIMIT ?""",
                (limit + 1,),
            ).fetchall()
        truncated = len(rows) > limit
        return ExecutionIntentSnapshotPage(
            items=tuple(_intent_record(row) for row in rows[:limit]),
            truncated=truncated,
        )

    def record_callback(
        self, intent_id: str, callback_id: str, evidence_payload: Mapping[str, Any]
    ) -> ExecutionCallbackReceipt:
        """Persist deduplicated callback evidence without applying economics."""

        _require_identifier(intent_id, "INVALID_INTENT_ID")
        _require_identifier(callback_id, "INVALID_CALLBACK_ID")
        payload_json = self._payload_json(evidence_payload)
        receipt_id = _stable_id("callback", intent_id + ":" + callback_id)
        now_ns = time.time_ns()
        with self._transaction() as cursor:
            if (
                cursor.execute(
                    "SELECT 1 FROM execution_decision_intents WHERE intent_id = ?", (intent_id,)
                ).fetchone()
                is None
            ):
                raise ExecutionDecisionJournalError("INTENT_NOT_PREPARED")
            existing = cursor.execute(
                "SELECT * FROM execution_decision_callbacks WHERE receipt_id = ?", (receipt_id,)
            ).fetchone()
            if existing is not None:
                if (
                    existing["intent_id"] != intent_id
                    or existing["callback_id"] != callback_id
                    or existing["evidence_payload_json"] != payload_json
                ):
                    raise ExecutionDecisionJournalError("CALLBACK_CONFLICT")
                return _callback_record(existing, is_new=False)
            pending = int(
                cursor.execute(
                    "SELECT COUNT(*) FROM execution_decision_callbacks " "WHERE delivery_pending=1"
                ).fetchone()[0]
            )
            if pending >= self.max_pending_callbacks:
                raise ExecutionDecisionJournalError("PENDING_CALLBACK_LIMIT")
            with track_durable_row_change(
                cursor, "execution_decision_callbacks", (receipt_id,), "SETTLEMENT"
            ):
                cursor.execute(
                    """INSERT INTO execution_decision_callbacks
                       (receipt_id, intent_id, callback_id, evidence_payload_json,
                        acknowledged, created_at_ns, process_instance_id, delivery_pending)
                       VALUES (?, ?, ?, ?, 0, ?, ?, 1)""",
                    (
                        receipt_id,
                        intent_id,
                        callback_id,
                        payload_json,
                        now_ns,
                        _current_process_instance_id(),
                    ),
                )
            row = cursor.execute(
                "SELECT * FROM execution_decision_callbacks WHERE receipt_id = ?",
                (receipt_id,),
            ).fetchone()
            return _callback_record(row, is_new=True)

    def record_callback_projected(
        self,
        intent_id: str,
        callback_id: str,
        evidence_payload: Mapping[str, Any],
        *,
        project: Callable[[sqlite3.Cursor, str], Any],
    ) -> Tuple[ExecutionCallbackReceipt, Any]:
        """Persist callback evidence and run its durable projection atomically.

        The projector receives this journal's write cursor and immutable
        receipt id. It is invoked for both a new receipt and an exact replay so
        an idempotent projector can repair a missing derived projection after
        recovery. A provider fill projector must deduplicate by its stable
        execution id. The callback receipt and projection commit together.
        """

        _require_identifier(intent_id, "INVALID_INTENT_ID")
        _require_identifier(callback_id, "INVALID_CALLBACK_ID")
        if not callable(project):
            raise ExecutionDecisionJournalError("CALLBACK_PROJECTOR_REQUIRED")
        payload_json = self._payload_json(evidence_payload)
        receipt_id = _stable_id("callback", intent_id + ":" + callback_id)
        now_ns = time.time_ns()
        with self._transaction() as cursor:
            if (
                cursor.execute(
                    "SELECT 1 FROM execution_decision_intents WHERE intent_id = ?", (intent_id,)
                ).fetchone()
                is None
            ):
                raise ExecutionDecisionJournalError("INTENT_NOT_PREPARED")
            existing = cursor.execute(
                "SELECT * FROM execution_decision_callbacks WHERE receipt_id = ?", (receipt_id,)
            ).fetchone()
            is_new = existing is None
            if existing is not None:
                if (
                    existing["intent_id"] != intent_id
                    or existing["callback_id"] != callback_id
                    or existing["evidence_payload_json"] != payload_json
                ):
                    raise ExecutionDecisionJournalError("CALLBACK_CONFLICT")
                row = existing
            else:
                pending = int(
                    cursor.execute(
                        "SELECT COUNT(*) FROM execution_decision_callbacks "
                        "WHERE delivery_pending=1"
                    ).fetchone()[0]
                )
                if pending >= self.max_pending_callbacks:
                    raise ExecutionDecisionJournalError("PENDING_CALLBACK_LIMIT")
                with track_durable_row_change(
                    cursor, "execution_decision_callbacks", (receipt_id,), "SETTLEMENT"
                ):
                    cursor.execute(
                        """INSERT INTO execution_decision_callbacks
                           (receipt_id, intent_id, callback_id, evidence_payload_json,
                            acknowledged, created_at_ns, process_instance_id, delivery_pending)
                           VALUES (?, ?, ?, ?, 0, ?, ?, 1)""",
                        (
                            receipt_id,
                            intent_id,
                            callback_id,
                            payload_json,
                            now_ns,
                            _current_process_instance_id(),
                        ),
                    )
                row = cursor.execute(
                    "SELECT * FROM execution_decision_callbacks WHERE receipt_id = ?",
                    (receipt_id,),
                ).fetchone()
            projected = project(cursor, receipt_id)
            row = cursor.execute(
                "SELECT * FROM execution_decision_callbacks WHERE receipt_id = ?",
                (receipt_id,),
            ).fetchone()
            return _callback_record(row, is_new=is_new), projected

    def record_callback_query_disposition(
        self,
        cursor: sqlite3.Cursor,
        *,
        native_receipt_id: str,
        query_receipt_id: str,
        intent_id: str,
        execution_id: str,
        proof_payload: Mapping[str, Any],
    ) -> ExecutionCallbackQueryDisposition:
        """Append an exact query match for an unacknowledged native fill.

        This cursor helper is intentionally usable only from the transaction
        passed to ``record_callback_projected``. It neither acknowledges nor
        rewrites the native callback receipt.
        """

        if (
            not isinstance(cursor, sqlite3.Cursor)
            or cursor.connection is not self._connection
            or not self._connection.in_transaction
        ):
            raise ExecutionDecisionJournalError("CALLBACK_QUERY_DISPOSITION_TRANSACTION_REQUIRED")
        for value, code in (
            (native_receipt_id, "INVALID_NATIVE_CALLBACK_RECEIPT_ID"),
            (query_receipt_id, "INVALID_QUERY_CALLBACK_RECEIPT_ID"),
            (intent_id, "INVALID_INTENT_ID"),
            (execution_id, "INVALID_EXECUTION_ID"),
        ):
            _require_identifier(value, code)
        native = cursor.execute(
            "SELECT * FROM execution_decision_callbacks WHERE receipt_id=?",
            (native_receipt_id,),
        ).fetchone()
        query = cursor.execute(
            "SELECT * FROM execution_decision_callbacks WHERE receipt_id=?",
            (query_receipt_id,),
        ).fetchone()
        if native is None or query is None:
            raise ExecutionDecisionJournalError("CALLBACK_QUERY_RECEIPT_NOT_FOUND")
        if (
            native["intent_id"] != intent_id
            or query["intent_id"] != intent_id
            or native["acknowledged"] != 0
        ):
            raise ExecutionDecisionJournalError("CALLBACK_QUERY_RECEIPT_BINDING_MISMATCH")
        producer_process = native["process_instance_id"]
        if not isinstance(producer_process, str) or not producer_process:
            raise ExecutionDecisionJournalError("CALLBACK_QUERY_RESTART_ORIGIN_UNKNOWN")
        if producer_process == _current_process_instance_id():
            raise ExecutionDecisionJournalError("CALLBACK_QUERY_RESTART_NOT_PROVEN")
        try:
            native_evidence = json.loads(native["evidence_payload_json"])
            query_evidence = json.loads(query["evidence_payload_json"])
        except (TypeError, ValueError) as error:
            raise ExecutionDecisionJournalError("CALLBACK_QUERY_EVIDENCE_INVALID") from error
        execution_digest = hashlib.sha256(execution_id.encode("utf-8")).hexdigest()
        native_callback_id = "ctp-trade:" + execution_digest
        query_callback_id = "query-trade:" + execution_digest
        if (
            native["callback_id"] != native_callback_id
            or query["callback_id"] != query_callback_id
            or _stable_id("callback", intent_id + ":" + native_callback_id) != native_receipt_id
            or _stable_id("callback", intent_id + ":" + query_callback_id) != query_receipt_id
        ):
            raise ExecutionDecisionJournalError("CALLBACK_QUERY_RECEIPT_IDENTITY_MISMATCH")
        native_digest = hashlib.sha256(native["evidence_payload_json"].encode("utf-8")).hexdigest()
        query_digest = hashlib.sha256(query["evidence_payload_json"].encode("utf-8")).hexdigest()
        if not isinstance(proof_payload, Mapping) or set(proof_payload) != {
            "original_order",
            "matched_order",
            "trade",
            "query_set",
        }:
            raise ExecutionDecisionJournalError("CALLBACK_QUERY_PROOF_FIELDS_INVALID")
        proof_payload = {
            "schema_version": 1,
            "disposition_code": _CALLBACK_QUERY_DISPOSITION,
            "native_receipt_id": native_receipt_id,
            "query_receipt_id": query_receipt_id,
            "intent_id": intent_id,
            "execution_id": execution_id,
            "native_callback_id": native["callback_id"],
            "native_evidence_sha256": native_digest,
            "query_callback_id": query["callback_id"],
            "query_evidence_sha256": query_digest,
            **dict(proof_payload),
        }
        existing = cursor.execute(
            """SELECT * FROM execution_callback_query_dispositions
               WHERE native_receipt_id=?""",
            (native_receipt_id,),
        ).fetchone()
        if existing is not None:
            if (
                existing["query_receipt_id"] != query_receipt_id
                or existing["intent_id"] != intent_id
                or existing["execution_id"] != execution_id
                or existing["disposition_code"] != _CALLBACK_QUERY_DISPOSITION
                or not isinstance(existing["query_process_instance_id"], str)
                or not existing["query_process_instance_id"]
                or existing["query_process_instance_id"] == producer_process
                or _sha256_text(existing["proof_payload_json"]) != existing["proof_sha256"]
                or native["delivery_pending"] != 0
                or query["acknowledged"] != 1
            ):
                raise ExecutionDecisionJournalError("CALLBACK_QUERY_DISPOSITION_CORRUPT")
            try:
                original_proof = json.loads(existing["proof_payload_json"])
            except (TypeError, ValueError) as error:
                raise ExecutionDecisionJournalError("CALLBACK_QUERY_DISPOSITION_CORRUPT") from error
            self._validate_callback_query_disposition_proof(
                cursor,
                original_proof,
                native_receipt_id=native_receipt_id,
                query_receipt_id=query_receipt_id,
                intent_id=intent_id,
                execution_id=execution_id,
                native_callback_id=native_callback_id,
                query_callback_id=query_callback_id,
                native_evidence_sha256=native_digest,
                query_evidence_sha256=query_digest,
                native_evidence=native_evidence,
                query_evidence=query_evidence,
            )
            if not _callback_query_disposition_replay_matches(original_proof, proof_payload):
                raise ExecutionDecisionJournalError("CALLBACK_QUERY_DISPOSITION_CONFLICT")
            # The first complete query proof is immutable. A later complete
            # query can confirm the same stable execution with a new request,
            # snapshot and observation time; it must not replace that proof.
            return _callback_query_disposition_record(existing)

        if native["delivery_pending"] != 1 or query["acknowledged"] != 1:
            raise ExecutionDecisionJournalError("CALLBACK_QUERY_DELIVERY_STATE_MISMATCH")

        self._validate_callback_query_disposition_proof(
            cursor,
            proof_payload,
            native_receipt_id=native_receipt_id,
            query_receipt_id=query_receipt_id,
            intent_id=intent_id,
            execution_id=execution_id,
            native_callback_id=native_callback_id,
            query_callback_id=query_callback_id,
            native_evidence_sha256=native_digest,
            query_evidence_sha256=query_digest,
            native_evidence=native_evidence,
            query_evidence=query_evidence,
        )
        query_process_instance_id = _current_process_instance_id()
        proof_json = self._payload_json(proof_payload)
        proof_sha256 = hashlib.sha256(proof_json.encode("utf-8")).hexdigest()
        with track_durable_row_change(
            cursor,
            "execution_callback_query_dispositions",
            (native_receipt_id,),
            "SETTLEMENT",
        ):
            cursor.execute(
                """INSERT INTO execution_callback_query_dispositions
                   (native_receipt_id,query_receipt_id,intent_id,execution_id,
                    disposition_code,query_process_instance_id,proof_payload_json,
                    proof_sha256,created_at_ns)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    native_receipt_id,
                    query_receipt_id,
                    intent_id,
                    execution_id,
                    _CALLBACK_QUERY_DISPOSITION,
                    query_process_instance_id,
                    proof_json,
                    proof_sha256,
                    time.time_ns(),
                ),
            )
        row = cursor.execute(
            """SELECT * FROM execution_callback_query_dispositions
               WHERE native_receipt_id=?""",
            (native_receipt_id,),
        ).fetchone()
        with track_durable_row_change(
            cursor, "execution_decision_callbacks", (native_receipt_id,), "SETTLEMENT"
        ):
            cursor.execute(
                """UPDATE execution_decision_callbacks SET delivery_pending=0
                   WHERE receipt_id=? AND acknowledged=0 AND delivery_pending=1""",
                (native_receipt_id,),
            )
        if cursor.rowcount != 1:
            raise ExecutionDecisionJournalError("CALLBACK_QUERY_DELIVERY_STATE_MISMATCH")
        return _callback_query_disposition_record(row)

    def _validate_callback_query_disposition_proof(
        self,
        cursor: sqlite3.Cursor,
        proof: Any,
        *,
        native_receipt_id: str,
        query_receipt_id: str,
        intent_id: str,
        execution_id: str,
        native_callback_id: str,
        query_callback_id: str,
        native_evidence_sha256: str,
        query_evidence_sha256: str,
        native_evidence: Any,
        query_evidence: Any,
    ) -> None:
        root_fields = {
            "schema_version",
            "disposition_code",
            "native_receipt_id",
            "query_receipt_id",
            "intent_id",
            "execution_id",
            "native_callback_id",
            "native_evidence_sha256",
            "query_callback_id",
            "query_evidence_sha256",
            "original_order",
            "matched_order",
            "trade",
            "query_set",
        }
        if not isinstance(proof, Mapping) or set(proof) != root_fields:
            raise ExecutionDecisionJournalError("CALLBACK_QUERY_PROOF_FIELDS_INVALID")
        if (
            proof.get("schema_version") != 1
            or proof.get("disposition_code") != _CALLBACK_QUERY_DISPOSITION
            or proof.get("native_receipt_id") != native_receipt_id
            or proof.get("query_receipt_id") != query_receipt_id
            or proof.get("intent_id") != intent_id
            or proof.get("execution_id") != execution_id
            or proof.get("native_callback_id") != native_callback_id
            or proof.get("native_evidence_sha256") != native_evidence_sha256
            or proof.get("query_callback_id") != query_callback_id
            or proof.get("query_evidence_sha256") != query_evidence_sha256
        ):
            raise ExecutionDecisionJournalError("CALLBACK_QUERY_PROOF_BINDING_MISMATCH")
        if not isinstance(native_evidence, Mapping) or not isinstance(query_evidence, Mapping):
            raise ExecutionDecisionJournalError("CALLBACK_QUERY_EVIDENCE_INVALID")
        if (
            native_evidence.get("event_type") != "execution_fill"
            or native_evidence.get("evidence_kind") != "native_trade_callback"
            or query_evidence.get("event_type") != "execution_fill"
            or native_evidence.get("execution_id") != execution_id
            or query_evidence.get("execution_id") != execution_id
            or native_evidence.get("order_ref") != query_evidence.get("order_ref")
            or native_evidence.get("instrument_id") != query_evidence.get("instrument_id")
            or native_evidence.get("exchange") != query_evidence.get("exchange")
        ):
            raise ExecutionDecisionJournalError("CALLBACK_QUERY_ECONOMICS_MISMATCH")
        for name in ("quantity", "price"):
            try:
                if _canonical_decimal(native_evidence.get(name)) != _canonical_decimal(
                    query_evidence.get(name)
                ):
                    raise ExecutionDecisionJournalError("CALLBACK_QUERY_ECONOMICS_MISMATCH")
            except (InvalidOperation, TypeError, ValueError) as error:
                raise ExecutionDecisionJournalError("CALLBACK_QUERY_ECONOMICS_INVALID") from error
        native_fee = native_evidence.get("fee")
        query_fee = query_evidence.get("fee")
        if native_fee is not None and query_fee is not None:
            try:
                if _canonical_decimal(native_fee) != _canonical_decimal(query_fee):
                    raise ExecutionDecisionJournalError("CALLBACK_QUERY_FEE_CONFLICT")
            except (InvalidOperation, TypeError, ValueError) as error:
                raise ExecutionDecisionJournalError("CALLBACK_QUERY_FEE_INVALID") from error
        native_time = native_evidence.get("filled_at_ns")
        query_time = query_evidence.get("filled_at_ns")
        if type(query_time) is not int or query_time <= 0:
            raise ExecutionDecisionJournalError("CALLBACK_QUERY_TIME_CONFLICT")
        if native_time is not None and native_time != query_time:
            raise ExecutionDecisionJournalError("CALLBACK_QUERY_TIME_CONFLICT")
        if (
            native_evidence.get("order_sys_id") is not None
            and query_evidence.get("order_sys_id") is not None
            and native_evidence.get("order_sys_id") != query_evidence.get("order_sys_id")
        ):
            raise ExecutionDecisionJournalError("CALLBACK_QUERY_ORDER_SYS_ID_CONFLICT")

        original = proof.get("original_order")
        matched = proof.get("matched_order")
        trade = proof.get("trade")
        query_set = proof.get("query_set")
        if (
            not isinstance(original, Mapping)
            or set(original)
            != {
                "account_scope",
                "strategy_scope",
                "trading_day",
                "instrument",
                "exchange",
                "order_ref",
                "front_id",
                "session_id",
                "order_sys_id",
            }
            or not isinstance(matched, Mapping)
            or set(matched)
            != {"front_id", "session_id", "order_ref", "instrument", "exchange", "order_sys_id"}
            or not isinstance(trade, Mapping)
            or set(trade)
            != {
                "trade_id",
                "trade_date",
                "trade_time",
                "query_set_id",
                "observation_id",
                "snapshot_id",
                "request_id",
                "account_fingerprint",
                "connection_generation",
                "trading_day",
                "side",
                "position_effect",
                "order_sys_id",
                "quantity",
                "price",
                "fee",
                "filled_at_ns",
            }
            or not isinstance(query_set, Mapping)
            or set(query_set)
            != {
                "query_set_id",
                "account_fingerprint",
                "connection_generation",
                "trading_day",
                "started_at_utc",
                "completed_at_utc",
                "available_at_utc",
                "family_request_ids",
            }
        ):
            raise ExecutionDecisionJournalError("CALLBACK_QUERY_PROOF_FIELDS_INVALID")
        intent_row = cursor.execute(
            """SELECT i.intent_key_json,i.economic_payload_json,i.original_identity_json,
                      d.business_key_json
               FROM execution_decision_intents AS i
               JOIN execution_decisions AS d ON d.decision_id=i.decision_id
               WHERE i.intent_id=?""",
            (intent_id,),
        ).fetchone()
        if intent_row is None:
            raise ExecutionDecisionJournalError("CALLBACK_QUERY_INTENT_NOT_FOUND")
        try:
            intent_key = json.loads(intent_row["intent_key_json"])
            economics = json.loads(intent_row["economic_payload_json"])
            stored_identity = json.loads(intent_row["original_identity_json"])
            business_key = json.loads(intent_row["business_key_json"])
        except (TypeError, ValueError) as error:
            raise ExecutionDecisionJournalError("CALLBACK_QUERY_INTENT_INVALID") from error
        native_identity = cursor.execute(
            "SELECT * FROM execution_native_intent_identities WHERE intent_id=?",
            (intent_id,),
        ).fetchone()
        if native_identity is None:
            raise ExecutionDecisionJournalError("CALLBACK_QUERY_NATIVE_IDENTITY_MISSING")
        expected_original = {
            "account_scope": business_key.get("account_scope"),
            "strategy_scope": business_key.get("strategy_scope"),
            "trading_day": native_identity["trading_day"],
            "instrument": intent_key.get("instrument"),
            "exchange": economics.get("exchange"),
            "order_ref": native_identity["order_ref"],
            "front_id": stored_identity.get("front_id"),
            "session_id": stored_identity.get("session_id"),
            "order_sys_id": stored_identity.get("order_sys_id"),
        }
        if (
            intent_key.get("action") != "SUBMIT"
            or intent_key.get("position_effect") not in ("OPEN", "CLOSE")
            or intent_key.get("side") not in ("BUY", "SELL")
            or dict(original) != expected_original
            or matched.get("front_id") != expected_original["front_id"]
            or matched.get("session_id") != expected_original["session_id"]
            or matched.get("order_ref") != expected_original["order_ref"]
            or matched.get("instrument") != expected_original["instrument"]
            or matched.get("exchange") != expected_original["exchange"]
            or native_identity["account_scope"] != expected_original["account_scope"]
            or native_identity["strategy_scope"] != expected_original["strategy_scope"]
            or native_identity["instrument"] != expected_original["instrument"]
            or native_identity["exchange"] != expected_original["exchange"]
            or native_evidence.get("order_ref") != expected_original["order_ref"]
            or native_evidence.get("instrument_id") != expected_original["instrument"]
            or native_evidence.get("exchange") != expected_original["exchange"]
            or native_evidence.get("quantity") is None
            or query_evidence.get("provider_trade_id") != trade.get("trade_id")
            or query_evidence.get("account_scope") != expected_original["account_scope"]
            or query_evidence.get("strategy_scope") != expected_original["strategy_scope"]
            or query_evidence.get("evidence_kind") != "complete_trades_query_observation"
            or query_evidence.get("query_observation_id") != trade.get("observation_id")
            or query_evidence.get("snapshot_id") != trade.get("snapshot_id")
            or query_evidence.get("request_id") != trade.get("request_id")
            or query_evidence.get("account_fingerprint") != trade.get("account_fingerprint")
            or query_evidence.get("connection_generation") != trade.get("connection_generation")
            or query_evidence.get("trading_day") != trade.get("trading_day")
        ):
            raise ExecutionDecisionJournalError("CALLBACK_QUERY_ORIGINAL_IDENTITY_MISMATCH")
        families = (
            "account_result",
            "orders_result",
            "trades_result",
            "instruments_result",
            "positions_result",
        )
        family_ids = query_set.get("family_request_ids")
        if (
            not _identifier(query_set.get("query_set_id"))
            or query_set.get("account_fingerprint") != trade.get("account_fingerprint")
            or query_set.get("connection_generation") != trade.get("connection_generation")
            or query_set.get("trading_day") != trade.get("trading_day")
            or trade.get("query_set_id") != query_set.get("query_set_id")
            or type(family_ids) not in (tuple, list)
            or len(family_ids) != len(families)
            or any(
                type(item) not in (tuple, list)
                or len(item) != 2
                or type(item[0]) is not str
                or type(item[1]) is not int
                or item[1] <= 0
                for item in family_ids
            )
            or tuple(item[0] for item in family_ids) != families
            or len({item[1] for item in family_ids}) != len(families)
            or dict(family_ids).get("trades_result") != trade.get("request_id")
        ):
            raise ExecutionDecisionJournalError("CALLBACK_QUERY_PROOF_FAMILIES_INVALID")
        for name in (
            "account_scope",
            "strategy_scope",
            "trading_day",
            "instrument",
            "exchange",
            "order_ref",
        ):
            _require_identifier(
                expected_original.get(name), "CALLBACK_QUERY_ORIGINAL_IDENTITY_MISMATCH"
            )
        for value in (matched.get("front_id"), matched.get("session_id")):
            if type(value) is not int or value <= 0:
                raise ExecutionDecisionJournalError("CALLBACK_QUERY_ORIGINAL_IDENTITY_MISMATCH")
        if (
            type(query_set.get("connection_generation")) is not int
            or query_set["connection_generation"] <= 0
            or type(trade.get("request_id")) is not int
            or trade["request_id"] <= 0
            or type(trade.get("filled_at_ns")) is not int
            or trade["filled_at_ns"] <= 0
            or not _identifier(trade.get("trade_id"))
            or not _identifier(trade.get("observation_id"))
            or not _identifier(trade.get("snapshot_id"))
            or not _identifier(trade.get("account_fingerprint"))
            or trade.get("side") != intent_key.get("side")
            or trade.get("position_effect") != intent_key.get("position_effect")
            or _execution_id_parts(execution_id) != (trade.get("trade_date"), trade.get("trade_id"))
            or trade.get("trading_day") != native_identity["trading_day"]
            or (trade.get("order_sys_id") is not None and not _identifier(trade["order_sys_id"]))
            or (
                matched.get("order_sys_id") is not None
                and trade.get("order_sys_id") is not None
                and matched.get("order_sys_id") != trade.get("order_sys_id")
            )
            or (
                stored_identity.get("order_sys_id") is not None
                and matched.get("order_sys_id") != stored_identity.get("order_sys_id")
            )
        ):
            raise ExecutionDecisionJournalError("CALLBACK_QUERY_PROOF_FIELDS_INVALID")
        try:
            proof_quantity = _canonical_decimal(trade.get("quantity"))
            proof_price = _canonical_decimal(trade.get("price"))
            proof_fee = None if trade.get("fee") is None else _canonical_decimal(trade.get("fee"))
            query_quantity = _canonical_decimal(query_evidence.get("quantity"))
            query_price = _canonical_decimal(query_evidence.get("price"))
            query_fee = (
                None
                if query_evidence.get("fee") is None
                else _canonical_decimal(query_evidence.get("fee"))
            )
        except (InvalidOperation, TypeError, ValueError) as error:
            raise ExecutionDecisionJournalError("CALLBACK_QUERY_ECONOMICS_INVALID") from error
        if (
            query_evidence.get("execution_id") != execution_id
            or query_evidence.get("order_ref") != expected_original["order_ref"]
            or query_evidence.get("instrument_id") != expected_original["instrument"]
            or query_evidence.get("exchange") != expected_original["exchange"]
            or query_quantity != proof_quantity
            or query_price != proof_price
            or query_evidence.get("filled_at_ns") != trade.get("filled_at_ns")
            or (query_fee is not None and proof_fee is not None and query_fee != proof_fee)
            or (
                query_evidence.get("order_sys_id") is not None
                and trade.get("order_sys_id") is not None
                and query_evidence.get("order_sys_id") != trade.get("order_sys_id")
            )
        ):
            raise ExecutionDecisionJournalError("CALLBACK_QUERY_ECONOMICS_MISMATCH")
        parsed_query_times = {}
        for name in ("started_at_utc", "completed_at_utc", "available_at_utc"):
            value = query_set[name]
            parse_text = value[:-1] + "+00:00" if value.endswith("Z") else value
            try:
                parsed = datetime.fromisoformat(parse_text)
            except ValueError as error:
                raise ExecutionDecisionJournalError("CALLBACK_QUERY_PROOF_TIME_INVALID") from error
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                raise ExecutionDecisionJournalError("CALLBACK_QUERY_PROOF_TIME_INVALID")
            parsed_query_times[name] = parsed.astimezone(timezone.utc)
        if not (
            parsed_query_times["started_at_utc"]
            <= parsed_query_times["completed_at_utc"]
            == parsed_query_times["available_at_utc"]
        ):
            raise ExecutionDecisionJournalError("CALLBACK_QUERY_PROOF_TIME_INVALID")
        for name in ("started_at_utc", "completed_at_utc", "available_at_utc"):
            value = query_set.get(name)
            if type(value) is not str or not value:
                raise ExecutionDecisionJournalError("CALLBACK_QUERY_PROOF_TIME_INVALID")
            parse_text = value[:-1] + "+00:00" if value.endswith("Z") else value
            try:
                parsed = datetime.fromisoformat(parse_text)
            except ValueError as error:
                raise ExecutionDecisionJournalError("CALLBACK_QUERY_PROOF_TIME_INVALID") from error
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                raise ExecutionDecisionJournalError("CALLBACK_QUERY_PROOF_TIME_INVALID")
        fill = cursor.execute(
            """SELECT * FROM factor_position_fills
               WHERE account_scope=? AND instrument=? AND exchange=? AND execution_id=?""",
            (
                expected_original["account_scope"],
                expected_original["instrument"],
                expected_original["exchange"],
                execution_id,
            ),
        ).fetchone()
        if fill is None:
            raise ExecutionDecisionJournalError("CALLBACK_QUERY_POSITION_FILL_MISSING")
        try:
            query_quantity = _canonical_decimal(query_evidence.get("quantity"))
            query_price = _canonical_decimal(query_evidence.get("price"))
            query_fee = (
                None
                if query_evidence.get("fee") is None
                else _canonical_decimal(query_evidence.get("fee"))
            )
        except (InvalidOperation, TypeError, ValueError) as error:
            raise ExecutionDecisionJournalError("CALLBACK_QUERY_ECONOMICS_INVALID") from error
        if (
            fill["intent_id"] != intent_id
            or fill["strategy_scope"] != expected_original["strategy_scope"]
            or fill["position_effect"] != intent_key["position_effect"]
            or fill["order_side"] != intent_key["side"]
            or fill["quantity"] != query_quantity
            or fill["price"] != query_price
            or fill["filled_at_ns"] != query_time
            or (query_fee is not None and fill["fee"] != query_fee)
        ):
            raise ExecutionDecisionJournalError("CALLBACK_QUERY_POSITION_FILL_CONFLICT")

    def pending_callbacks(self, *, limit: int) -> Tuple[ExecutionCallbackReceipt, ...]:
        """Fetch a bounded page of callback evidence awaiting caller delivery."""

        if type(limit) is not int or not 1 <= limit <= self.max_pending_callbacks:
            raise ExecutionDecisionJournalError("INVALID_CALLBACK_LIMIT")
        with self._read_lock():
            rows = self._connection.execute(
                """SELECT c.*,
                          EXISTS(SELECT 1 FROM execution_callback_query_dispositions AS d
                                 WHERE d.native_receipt_id=c.receipt_id) AS has_disposition
                   FROM execution_decision_callbacks AS c
                   WHERE c.delivery_pending=1
                   ORDER BY c.created_at_ns,c.receipt_id LIMIT ?""",
                (limit,),
            ).fetchall()
        if any(row["acknowledged"] != 0 or row["has_disposition"] for row in rows):
            raise ExecutionDecisionJournalError("CALLBACK_DELIVERY_STATE_CORRUPT")
        return tuple(_callback_record(row) for row in rows)

    def _validate_callback_delivery_state_on_open(self) -> None:
        """Validate persisted delivery dispositions once, streaming bounded batches.

        Query-matched callbacks are no longer pending, but their immutable proof
        is the only reason an unacknowledged native receipt may be omitted from
        delivery. Validate every stored disposition and check for unacknowledged
        receipts whose delivery bit was cleared without a disposition. Keeping
        this scan at open avoids hashing callback history on each hot-path read.
        """

        with self._lock:
            self._ensure_open()
            connection = self._connection
            cursor = connection.cursor()
            try:
                cursor.execute("BEGIN")
                dispositions = connection.cursor()
                try:
                    dispositions.execute(
                        """SELECT native_receipt_id
                           FROM execution_callback_query_dispositions
                           ORDER BY native_receipt_id"""
                    )
                    while rows := dispositions.fetchmany(64):
                        for row in rows:
                            receipt_id = row["native_receipt_id"]
                            if self.callback_query_disposition(receipt_id) is None:
                                raise ExecutionDecisionJournalError(
                                    "CALLBACK_QUERY_DISPOSITION_CORRUPT"
                                )
                finally:
                    dispositions.close()

                hidden_receipts = connection.cursor()
                try:
                    hidden_receipts.execute(
                        """SELECT c.receipt_id
                           FROM execution_decision_callbacks AS c
                           LEFT JOIN execution_callback_query_dispositions AS d
                             ON d.native_receipt_id=c.receipt_id
                           WHERE c.acknowledged=0 AND c.delivery_pending=0
                             AND d.native_receipt_id IS NULL
                           ORDER BY c.receipt_id"""
                    )
                    if hidden_receipts.fetchone() is not None:
                        raise ExecutionDecisionJournalError("CALLBACK_DELIVERY_STATE_CORRUPT")
                finally:
                    hidden_receipts.close()
                cursor.execute("COMMIT")
            except BaseException:
                if connection.in_transaction:
                    cursor.execute("ROLLBACK")
                raise
            finally:
                cursor.close()

    def acknowledge_callback(self, receipt_id: str) -> None:
        """Acknowledge only after caller code has returned successfully."""

        _require_identifier(receipt_id, "INVALID_CALLBACK_RECEIPT_ID")
        with self._transaction() as cursor:
            self.acknowledge_callback_in_transaction(cursor, receipt_id)

    def acknowledge_callback_in_transaction(self, cursor: sqlite3.Cursor, receipt_id: str) -> None:
        """Acknowledge a projected non-native receipt atomically with its projection."""

        if (
            not isinstance(cursor, sqlite3.Cursor)
            or cursor.connection is not self._connection
            or not self._connection.in_transaction
        ):
            raise ExecutionDecisionJournalError("CALLBACK_ACK_TRANSACTION_REQUIRED")
        _require_identifier(receipt_id, "INVALID_CALLBACK_RECEIPT_ID")
        row = cursor.execute(
            "SELECT acknowledged FROM execution_decision_callbacks WHERE receipt_id = ?",
            (receipt_id,),
        ).fetchone()
        if row is None:
            raise ExecutionDecisionJournalError("CALLBACK_NOT_FOUND")
        if not row["acknowledged"]:
            with track_durable_row_change(
                cursor, "execution_decision_callbacks", (receipt_id,), "SETTLEMENT"
            ):
                cursor.execute(
                    """UPDATE execution_decision_callbacks
                       SET acknowledged=1,delivery_pending=0 WHERE receipt_id=?""",
                    (receipt_id,),
                )

    def _payload_json(self, value: Mapping[str, Any]) -> str:
        if not isinstance(value, Mapping):
            raise ExecutionDecisionJournalError("INVALID_JOURNAL_PAYLOAD")
        try:
            encoded = _canonical_json(value)
        except (TypeError, ValueError, InvalidOperation, OverflowError) as error:
            raise ExecutionDecisionJournalError("INVALID_JOURNAL_PAYLOAD") from error
        if len(encoded.encode("utf-8")) > self.max_payload_bytes:
            raise ExecutionDecisionJournalError("JOURNAL_PAYLOAD_TOO_LARGE")
        return encoded

    @staticmethod
    def _index_native_intent_identity(
        cursor: sqlite3.Cursor,
        *,
        intent_id: str,
        account_scope: str,
        strategy_scope: str,
        intent_key: ExecutionIntentKey,
        original_identity: Mapping[str, Any],
        capacity_class: str = "BASE",
    ) -> None:
        """Persist an exact CTP insert identity for bounded restart lookup.

        Generic journal users may provide an ``order_ref`` without claiming a
        CTP identity. A trading day or explicit registered-SimNow insert
        operation claims the CTP tuple, which must then be complete and
        immutable. Cancel intents refer to the original submit identity and
        never claim a second OrderRef.
        """

        if intent_key.action != "SUBMIT":
            return
        names = ("trading_day", "instrument_id", "exchange_id", "order_ref")
        # ``order_ref`` is also used by generic adapters. A CTP identity is
        # claimed only by its route-specific trading day or the explicit
        # registered-SimNow insert operation; older generic rows containing
        # only an order reference remain valid and unindexed.
        native_claimed = (
            "trading_day" in original_identity or original_identity.get("operation") == "insert"
        )
        if not native_claimed:
            existing = cursor.execute(
                "SELECT 1 FROM execution_native_intent_identities WHERE intent_id=?",
                (intent_id,),
            ).fetchone()
            if existing is not None:
                raise ExecutionDecisionJournalError("NATIVE_ORDER_IDENTITY_CONFLICT")
            return
        present = tuple(name in original_identity for name in names)
        if not all(present) or original_identity.get("operation") != "insert":
            raise ExecutionDecisionJournalError("NATIVE_ORDER_IDENTITY_INCOMPLETE")
        trading_day = original_identity.get("trading_day")
        instrument = original_identity.get("instrument_id")
        exchange = original_identity.get("exchange_id")
        order_ref = original_identity.get("order_ref")
        if (
            not _identifier(account_scope)
            or not _identifier(strategy_scope)
            or type(trading_day) is not str
            or len(trading_day) != 8
            or not trading_day.isdigit()
            or not _identifier(instrument)
            or instrument != intent_key.instrument
            or not _identifier(exchange)
            or type(order_ref) is not str
            or re.fullmatch(r"[1-9][0-9]{0,19}", order_ref) is None
        ):
            raise ExecutionDecisionJournalError("NATIVE_ORDER_IDENTITY_INVALID")
        values = (
            account_scope,
            strategy_scope,
            trading_day,
            instrument,
            exchange,
            order_ref,
        )
        existing = cursor.execute(
            """SELECT account_scope,strategy_scope,trading_day,instrument,exchange,order_ref
               FROM execution_native_intent_identities WHERE intent_id=?""",
            (intent_id,),
        ).fetchone()
        if existing is not None:
            if tuple(existing) != values:
                raise ExecutionDecisionJournalError("NATIVE_ORDER_IDENTITY_CONFLICT")
            return
        claimed = cursor.execute(
            """SELECT intent_id FROM execution_native_intent_identities
               WHERE account_scope=? AND trading_day=? AND order_ref=?""",
            (account_scope, trading_day, order_ref),
        ).fetchone()
        if claimed is not None and claimed["intent_id"] != intent_id:
            raise ExecutionDecisionJournalError("NATIVE_ORDER_IDENTITY_CONFLICT")
        with track_durable_row_change(
            cursor, "execution_native_intent_identities", (intent_id,), capacity_class
        ):
            cursor.execute(
                """INSERT INTO execution_native_intent_identities
                   (intent_id,account_scope,strategy_scope,trading_day,instrument,exchange,order_ref)
                   VALUES(?,?,?,?,?,?,?)""",
                (intent_id,) + values,
            )

    def _backfill_native_intent_identities(self, cursor: sqlite3.Cursor) -> None:
        """Rebuild the bounded CTP lookup index from immutable v7 intent rows.

        This runs transactionally for every pre-v8 database, including v7
        databases that already have the index table but predate startup
        backfill. Intent and dispatch rows are read-only here; any malformed or
        conflicting native identity aborts the migration.
        """

        rows = cursor.execute(
            """SELECT i.intent_id, i.intent_key_json, i.original_identity_json,
                      d.business_key_json
               FROM execution_decision_intents AS i
               JOIN execution_decisions AS d ON d.decision_id=i.decision_id
               ORDER BY i.created_at_ns, i.intent_id"""
        ).fetchall()
        for row in rows:
            try:
                intent_key_data = json.loads(row["intent_key_json"])
                original_identity = json.loads(row["original_identity_json"])
                business_key = json.loads(row["business_key_json"])
                if not isinstance(original_identity, Mapping) or not isinstance(
                    business_key, Mapping
                ):
                    raise ValueError("journal identity rows must be objects")
                intent_key = ExecutionIntentKey(**intent_key_data)
                self._index_native_intent_identity(
                    cursor,
                    intent_id=row["intent_id"],
                    account_scope=business_key["account_scope"],
                    strategy_scope=business_key["strategy_scope"],
                    intent_key=intent_key,
                    original_identity=original_identity,
                )
            except ExecutionDecisionJournalError:
                raise
            except (KeyError, TypeError, ValueError) as error:
                raise ExecutionDecisionJournalError("NATIVE_ORDER_IDENTITY_INVALID") from error

    @staticmethod
    def _backfill_decision_capacity_usage(cursor: sqlite3.Cursor) -> None:
        """Rebuild the two bounded capacity rows once during the v9 migration."""

        cursor.execute("DELETE FROM execution_decision_capacity_usage")
        rows = cursor.execute(
            """SELECT capacity_class,COUNT(*) AS record_count,
                      COALESCE(SUM(LENGTH(CAST(business_key_json AS BLOB)) +
                                   LENGTH(CAST(economic_payload_json AS BLOB)) +
                                   LENGTH(CAST(intent_keys_json AS BLOB))),0) AS payload_bytes
               FROM execution_decisions GROUP BY capacity_class"""
        ).fetchall()
        usage = {
            row["capacity_class"]: (int(row["record_count"]), int(row["payload_bytes"]))
            for row in rows
        }
        for capacity_class in ("BASE", "SETTLEMENT"):
            record_count, payload_bytes = usage.get(capacity_class, (0, 0))
            cursor.execute(
                """INSERT INTO execution_decision_capacity_usage
                   (capacity_class,record_count,payload_bytes) VALUES(?,?,?)""",
                (capacity_class, record_count, payload_bytes),
            )

    @staticmethod
    def _backfill_execution_grid_highwaters(cursor: sqlite3.Cursor) -> None:
        """Migrate per-cohort cursors into the stable account/strategy highwater."""

        rows = cursor.execute(
            """SELECT account_scope,strategy_scope,close_time,cohort_id,decision_id,
                      updated_at_ns
               FROM execution_grid_cursors
               ORDER BY account_scope,strategy_scope,updated_at_ns,cohort_id"""
        ).fetchall()
        highwaters = {}
        for row in rows:
            scope = (row["account_scope"], row["strategy_scope"])
            close_time = row["close_time"]
            parsed_time = _parse_normalized_close_time(close_time)
            current = highwaters.get(scope)
            if current is None or parsed_time > current[0]:
                highwaters[scope] = (
                    parsed_time,
                    close_time,
                    row["cohort_id"],
                    row["decision_id"],
                    int(row["updated_at_ns"]),
                )

        cursor.execute("DELETE FROM execution_grid_highwaters")
        for (account_scope, strategy_scope), value in highwaters.items():
            _parsed_time, close_time, cohort_id, decision_id, updated_at_ns = value
            cursor.execute(
                """INSERT INTO execution_grid_highwaters
                   (account_scope,strategy_scope,close_time,cohort_id,decision_id,updated_at_ns)
                   VALUES(?,?,?,?,?,?)""",
                (
                    account_scope,
                    strategy_scope,
                    close_time,
                    cohort_id,
                    decision_id,
                    updated_at_ns,
                ),
            )

    @staticmethod
    def _backfill_callback_delivery_pending(cursor: sqlite3.Cursor) -> None:
        """Restore the indexed delivery projection from immutable receipts."""

        cursor.execute(
            """UPDATE execution_decision_callbacks
               SET delivery_pending=CASE WHEN acknowledged=0 THEN 1 ELSE 0 END"""
        )

    def _durable_capacity_config_values(self) -> Tuple[int, int, int, int]:
        limits = self.durable_capacity_limits
        return (
            limits.max_durable_base_records,
            limits.max_durable_base_bytes,
            limits.max_durable_settlement_records,
            limits.max_durable_settlement_bytes,
        )

    def _validate_durable_capacity_tables(self, cursor: sqlite3.Cursor) -> DurableCapacityUsage:
        tables = {
            row[0]
            for row in cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN (?,?)",
                ("execution_durable_capacity_limits", "execution_durable_capacity_usage"),
            ).fetchall()
        }
        if tables != {
            "execution_durable_capacity_limits",
            "execution_durable_capacity_usage",
        }:
            raise ExecutionDecisionJournalError("DURABLE_CAPACITY_SCHEMA_CORRUPT")

        config_columns = [
            (row["name"], row["type"].upper(), int(row["pk"]))
            for row in cursor.execute(
                "PRAGMA table_info(execution_durable_capacity_limits)"
            ).fetchall()
        ]
        expected_config_columns = [
            ("singleton", "INTEGER", 1),
            ("max_durable_base_records", "INTEGER", 0),
            ("max_durable_base_bytes", "INTEGER", 0),
            ("max_durable_settlement_records", "INTEGER", 0),
            ("max_durable_settlement_bytes", "INTEGER", 0),
        ]
        usage_columns = [
            (row["name"], row["type"].upper(), int(row["pk"]))
            for row in cursor.execute(
                "PRAGMA table_info(execution_durable_capacity_usage)"
            ).fetchall()
        ]
        expected_usage_columns = [
            ("capacity_class", "TEXT", 1),
            ("record_count", "INTEGER", 0),
            ("payload_bytes", "INTEGER", 0),
        ]
        if config_columns != expected_config_columns or usage_columns != expected_usage_columns:
            raise ExecutionDecisionJournalError("DURABLE_CAPACITY_SCHEMA_CORRUPT")
        try:
            config_rows = cursor.execute(
                "SELECT * FROM execution_durable_capacity_limits ORDER BY singleton"
            ).fetchall()
            usage = read_durable_capacity_usage(cursor)
        except DurableCapacityError as error:
            raise ExecutionDecisionJournalError(error.code) from error
        if len(config_rows) != 1 or type(config_rows[0]["singleton"]) is not int:
            raise ExecutionDecisionJournalError("DURABLE_CAPACITY_CONFIG_INVALID")
        actual = tuple(
            config_rows[0][name]
            for name in (
                "max_durable_base_records",
                "max_durable_base_bytes",
                "max_durable_settlement_records",
                "max_durable_settlement_bytes",
            )
        )
        if any(type(value) is not int for value in actual):
            raise ExecutionDecisionJournalError("DURABLE_CAPACITY_CONFIG_INVALID")
        if actual != self._durable_capacity_config_values():
            raise ExecutionDecisionJournalError("DURABLE_CAPACITY_CONFIG_MISMATCH")
        return usage

    @staticmethod
    def _durable_decision_class(value: Any) -> str:
        if value not in ("BASE", "SETTLEMENT"):
            raise ExecutionDecisionJournalError("DURABLE_CAPACITY_CLASSIFICATION_INVALID")
        return value

    def _backfill_durable_capacity_usage(self, cursor: sqlite3.Cursor) -> None:
        """Count present v11 payload rows once using typed canonical row bytes."""

        decision_classes = {}
        grid_candidates = {}
        run_classes = {}
        try:
            decisions = cursor.execute(
                "SELECT decision_id,business_key_json,capacity_class FROM execution_decisions"
            )
            while rows := decisions.fetchmany(256):
                for row in rows:
                    capacity_class = self._durable_decision_class(row["capacity_class"])
                    try:
                        key = json.loads(row["business_key_json"])
                    except (TypeError, ValueError) as error:
                        raise ExecutionDecisionJournalError(
                            "DURABLE_CAPACITY_CLASSIFICATION_INVALID"
                        ) from error
                    if not isinstance(key, Mapping):
                        raise ExecutionDecisionJournalError(
                            "DURABLE_CAPACITY_CLASSIFICATION_INVALID"
                        )
                    decision_classes[row["decision_id"]] = capacity_class
                    identity = (
                        key.get("account_scope"),
                        key.get("strategy_scope"),
                        key.get("cohort_id"),
                        key.get("close_time"),
                    )
                    if all(type(value) is str and value for value in identity):
                        grid_candidates.setdefault(identity, []).append(
                            (row["decision_id"], capacity_class)
                        )
                    run_identity = (
                        key.get("account_scope"),
                        key.get("strategy_scope"),
                        key.get("logical_run_id"),
                    )
                    if any(type(value) is not str or not value for value in run_identity):
                        raise ExecutionDecisionJournalError(
                            "DURABLE_CAPACITY_CLASSIFICATION_INVALID"
                        )
                    classes = run_classes.setdefault(run_identity, set())
                    classes.add(capacity_class)
        except sqlite3.Error as error:
            raise ExecutionDecisionJournalError("DURABLE_CAPACITY_BACKFILL_FAILED") from error

        intent_preparation_classes = {}
        try:
            intents = cursor.execute(
                """SELECT i.intent_id,i.decision_id,i.intent_key_json,i.state,
                          i.dispatch_state,i.dispatch_result_json
                   FROM execution_decision_intents AS i"""
            )
            while rows := intents.fetchmany(256):
                for row in rows:
                    decision_class = decision_classes.get(row["decision_id"])
                    ambiguous_dispatch = (
                        row["state"] in ("DISPATCHING", "KNOWN", "UNKNOWN")
                        or row["dispatch_state"] in ("KNOWN", "UNKNOWN")
                        or row["dispatch_result_json"] is not None
                    )
                    try:
                        intent_key_data = json.loads(row["intent_key_json"])
                        if not isinstance(intent_key_data, Mapping):
                            raise ValueError("intent key is not an object")
                        intent_key = ExecutionIntentKey(**intent_key_data)
                        if (
                            _canonical_json(_intent_key_values(intent_key))
                            != row["intent_key_json"]
                        ):
                            raise ValueError("intent key is not canonical")
                    except (TypeError, ValueError, ExecutionDecisionJournalError) as error:
                        raise ExecutionDecisionJournalError(
                            "DURABLE_CAPACITY_CLASSIFICATION_INVALID"
                        ) from error
                    if intent_key.action == "CANCEL" or intent_key.position_effect == "CLOSE":
                        preparation_class = "SETTLEMENT"
                    elif intent_key.action == "SUBMIT" and intent_key.position_effect == "OPEN":
                        if decision_class is None and not ambiguous_dispatch:
                            raise ExecutionDecisionJournalError(
                                "DURABLE_CAPACITY_CLASSIFICATION_INVALID"
                            )
                        # A legacy ambiguous OPEN with no usable parent is
                        # conservatively classified as settlement.
                        preparation_class = decision_class or "SETTLEMENT"
                    else:
                        raise ExecutionDecisionJournalError(
                            "DURABLE_CAPACITY_CLASSIFICATION_INVALID"
                        )
                    intent_preparation_classes[row["intent_id"]] = preparation_class
        except sqlite3.Error as error:
            raise ExecutionDecisionJournalError("DURABLE_CAPACITY_BACKFILL_FAILED") from error

        book_meta = cursor.execute(
            "SELECT version FROM factor_position_book_meta WHERE singleton=1"
        ).fetchone()
        if book_meta is None or type(book_meta["version"]) is not int or book_meta["version"] != 6:
            raise ExecutionDecisionJournalError("POSITION_BOOK_SCHEMA_UNAVAILABLE")

        totals = {"BASE": [0, 0], "SETTLEMENT": [0, 0]}

        def account_rows(table: str, classifier: Callable[[sqlite3.Row], str]) -> None:
            try:
                source = cursor.execute("SELECT * FROM {}".format(table))
                while rows := source.fetchmany(256):
                    for row in rows:
                        capacity_class = self._durable_decision_class(classifier(row))
                        totals[capacity_class][0] += 1
                        totals[capacity_class][1] += len(canonical_sql_row_bytes(row))
                        if any(
                            value > 9_223_372_036_854_775_807 for value in totals[capacity_class]
                        ):
                            raise ExecutionDecisionJournalError(
                                "DURABLE_CAPACITY_BACKFILL_OVERFLOW"
                            )
            except DurableCapacityError as error:
                raise ExecutionDecisionJournalError(error.code) from error
            except sqlite3.Error as error:
                raise ExecutionDecisionJournalError("DURABLE_CAPACITY_BACKFILL_FAILED") from error

        account_rows(
            "execution_decisions", lambda row: self._durable_decision_class(row["capacity_class"])
        )
        account_rows(
            "execution_decision_slots",
            lambda row: decision_classes.get(row["decision_id"])
            or self._raise_capacity_classification_invalid(),
        )
        account_rows(
            "execution_run_order_budgets",
            lambda row: self._classify_run_budget_row(row, run_classes),
        )
        account_rows(
            "execution_grid_cursors",
            lambda row: decision_classes.get(row["decision_id"])
            or self._raise_capacity_classification_invalid(),
        )
        account_rows(
            "execution_grid_highwaters",
            lambda row: decision_classes.get(row["decision_id"])
            or self._raise_capacity_classification_invalid(),
        )

        def history_class(row: sqlite3.Row) -> str:
            identity = (
                row["account_scope"],
                row["strategy_scope"],
                row["cohort_id"],
                row["close_time"],
            )
            candidates = grid_candidates.get(identity, ())
            if len(candidates) != 1:
                return self._raise_capacity_classification_invalid()
            return candidates[0][1]

        account_rows("factor_position_grid_history", history_class)

        def intent_class(row: sqlite3.Row) -> str:
            if (
                row["state"] in ("DISPATCHING", "KNOWN", "UNKNOWN")
                or row["dispatch_state"] in ("KNOWN", "UNKNOWN")
                or row["dispatch_result_json"] is not None
            ):
                return "SETTLEMENT"
            return (
                intent_preparation_classes.get(row["intent_id"])
                or self._raise_capacity_classification_invalid()
            )

        account_rows("execution_decision_intents", intent_class)
        account_rows(
            "execution_native_intent_identities",
            lambda row: intent_preparation_classes.get(row["intent_id"])
            or self._raise_capacity_classification_invalid(),
        )

        def owner_class(row: sqlite3.Row) -> str:
            if row["owner_intent_id"] is None or row["cancel_intent_id"] is not None:
                return "SETTLEMENT"
            return (
                intent_preparation_classes.get(row["owner_intent_id"])
                or self._raise_capacity_classification_invalid()
            )

        account_rows("execution_instrument_owners", owner_class)

        for table in (
            "execution_decision_callbacks",
            "execution_intent_resolutions",
            "execution_intent_reconciliations",
            "execution_callback_query_dispositions",
            "execution_intent_abandonments",
            "execution_slot_abandonments",
            "factor_position_openings",
            "factor_position_fills",
            "factor_position_evidence_issues",
            "factor_position_dated_trade_facts",
            "factor_position_current",
            "factor_position_active_issues",
            "factor_position_fill_attributes",
            "factor_position_open_intent_totals",
        ):
            account_rows(table, lambda _row: "SETTLEMENT")

        for capacity_class in ("BASE", "SETTLEMENT"):
            changed = cursor.execute(
                """UPDATE execution_durable_capacity_usage
                   SET record_count=?,payload_bytes=? WHERE capacity_class=?""",
                (totals[capacity_class][0], totals[capacity_class][1], capacity_class),
            )
            if changed.rowcount != 1:
                raise ExecutionDecisionJournalError("DURABLE_CAPACITY_USAGE_UNAVAILABLE")

    @staticmethod
    def _raise_capacity_classification_invalid() -> str:
        raise ExecutionDecisionJournalError("DURABLE_CAPACITY_CLASSIFICATION_INVALID")

    @classmethod
    def _classify_run_budget_row(cls, row: sqlite3.Row, run_classes: Mapping[Any, set]) -> str:
        key = (row["account_scope"], row["strategy_scope"], row["logical_run_id"])
        classes = run_classes.get(key)
        if not classes:
            return cls._raise_capacity_classification_invalid()
        # A pre-v12 aggregate row records only its current canonical value,
        # not the historical split of prior growth. Use this deterministic
        # one-time migration convention; future growth is charged by the
        # operation's live capacity class.
        return "BASE" if "BASE" in classes else "SETTLEMENT"

    def _migrate_durable_capacity_v12(self, cursor: sqlite3.Cursor, version: int) -> None:
        existing = {
            row[0]
            for row in cursor.execute(
                """SELECT name FROM sqlite_master WHERE type='table'
                   AND name IN ('execution_durable_capacity_limits',
                                'execution_durable_capacity_usage')"""
            ).fetchall()
        }
        if version < self._SCHEMA_VERSION:
            if existing:
                raise ExecutionDecisionJournalError("DURABLE_CAPACITY_SCHEMA_CORRUPT")
            cursor.execute(
                """CREATE TABLE execution_durable_capacity_limits (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                    max_durable_base_records INTEGER NOT NULL CHECK(max_durable_base_records>0),
                    max_durable_base_bytes INTEGER NOT NULL CHECK(max_durable_base_bytes>0),
                    max_durable_settlement_records INTEGER NOT NULL
                        CHECK(max_durable_settlement_records>0),
                    max_durable_settlement_bytes INTEGER NOT NULL
                        CHECK(max_durable_settlement_bytes>0)
                )"""
            )
            cursor.execute(
                """INSERT INTO execution_durable_capacity_limits
                   (singleton,max_durable_base_records,max_durable_base_bytes,
                    max_durable_settlement_records,max_durable_settlement_bytes)
                   VALUES(1,?,?,?,?)""",
                self._durable_capacity_config_values(),
            )
            try:
                ensure_durable_capacity_usage_schema(cursor)
            except DurableCapacityError as error:
                raise ExecutionDecisionJournalError(error.code) from error
            self._backfill_durable_capacity_usage(cursor)
        self._validate_durable_capacity_tables(cursor)

    def _create_schema(self) -> None:
        with self._lock:
            version = int(self._connection.execute("PRAGMA user_version").fetchone()[0])
            if version not in (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, self._SCHEMA_VERSION):
                raise ExecutionDecisionJournalError("UNSUPPORTED_SCHEMA_VERSION")
            if version == self._SCHEMA_VERSION:
                required_tables = {
                    row["name"]
                    for row in self._connection.execute(
                        """SELECT name FROM sqlite_master WHERE type='table'
                           AND name IN ('execution_decision_callbacks',
                                        'execution_callback_query_dispositions')"""
                    ).fetchall()
                }
                if required_tables != {
                    "execution_decision_callbacks",
                    "execution_callback_query_dispositions",
                }:
                    raise ExecutionDecisionJournalError("CALLBACK_DELIVERY_SCHEMA_CORRUPT")
                callback_columns = {
                    row["name"]
                    for row in self._connection.execute(
                        "PRAGMA table_info(execution_decision_callbacks)"
                    ).fetchall()
                }
                disposition_columns = {
                    row["name"]
                    for row in self._connection.execute(
                        "PRAGMA table_info(execution_callback_query_dispositions)"
                    ).fetchall()
                }
                if (
                    not {"delivery_pending", "process_instance_id"} <= callback_columns
                    or not {
                        "query_process_instance_id",
                        "proof_payload_json",
                        "proof_sha256",
                    }
                    <= disposition_columns
                ):
                    raise ExecutionDecisionJournalError("CALLBACK_DELIVERY_SCHEMA_CORRUPT")
                cursor = self._connection.cursor()
                try:
                    self._validate_durable_capacity_tables(cursor)
                finally:
                    cursor.close()
            try:
                self._connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS execution_decisions (
                        decision_id TEXT PRIMARY KEY,
                        business_key_json TEXT NOT NULL UNIQUE,
                        economic_payload_json TEXT NOT NULL,
                        intent_keys_json TEXT NOT NULL,
                        created_at_ns INTEGER NOT NULL,
                        capacity_class TEXT NOT NULL DEFAULT 'BASE'
                            CHECK(capacity_class IN ('BASE','SETTLEMENT'))
                    );
                    CREATE TABLE IF NOT EXISTS execution_journal_capacity (
                        singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
                        max_decision_records INTEGER NOT NULL CHECK(max_decision_records > 0),
                        settlement_decision_reserve_records INTEGER NOT NULL
                            CHECK(settlement_decision_reserve_records > 0),
                        max_decision_bytes INTEGER NOT NULL CHECK(max_decision_bytes >= 1024),
                        settlement_decision_reserve_bytes INTEGER NOT NULL
                            CHECK(settlement_decision_reserve_bytes >= 1024)
                    );
                    CREATE TABLE IF NOT EXISTS execution_decision_capacity_usage (
                        capacity_class TEXT PRIMARY KEY
                            CHECK(capacity_class IN ('BASE','SETTLEMENT')),
                        record_count INTEGER NOT NULL CHECK(record_count >= 0),
                        payload_bytes INTEGER NOT NULL CHECK(payload_bytes >= 0)
                    );
                    CREATE TABLE IF NOT EXISTS execution_grid_cursors (
                        account_scope TEXT NOT NULL,
                        strategy_scope TEXT NOT NULL,
                        cohort_id TEXT NOT NULL,
                        ordinal INTEGER NOT NULL CHECK(ordinal >= 1),
                        epoch_id TEXT NOT NULL,
                        batch_id TEXT NOT NULL,
                        close_time TEXT NOT NULL,
                        decision_id TEXT NOT NULL REFERENCES execution_decisions(decision_id),
                        updated_at_ns INTEGER NOT NULL,
                        PRIMARY KEY(account_scope, strategy_scope, cohort_id)
                    );
                    CREATE TABLE IF NOT EXISTS execution_grid_highwaters (
                        account_scope TEXT NOT NULL,
                        strategy_scope TEXT NOT NULL,
                        close_time TEXT NOT NULL,
                        cohort_id TEXT NOT NULL,
                        decision_id TEXT NOT NULL REFERENCES execution_decisions(decision_id),
                        updated_at_ns INTEGER NOT NULL,
                        PRIMARY KEY(account_scope, strategy_scope)
                    );
                    CREATE TABLE IF NOT EXISTS execution_run_order_budgets (
                        account_scope TEXT NOT NULL,
                        strategy_scope TEXT NOT NULL,
                        logical_run_id TEXT NOT NULL,
                        max_intents INTEGER NOT NULL CHECK(max_intents >= 0),
                        intent_count INTEGER NOT NULL CHECK(intent_count >= 0),
                        created_at_ns INTEGER NOT NULL,
                        PRIMARY KEY(account_scope, strategy_scope, logical_run_id),
                        CHECK(intent_count <= max_intents)
                    );
                    CREATE TABLE IF NOT EXISTS execution_decision_slots (
                        intent_id TEXT PRIMARY KEY,
                        decision_id TEXT NOT NULL REFERENCES execution_decisions(decision_id),
                        intent_key_json TEXT NOT NULL,
                        leg INTEGER NOT NULL CHECK(leg >= 0),
                        UNIQUE(decision_id, intent_key_json)
                    );
                    CREATE TABLE IF NOT EXISTS execution_decision_intents (
                        intent_id TEXT PRIMARY KEY REFERENCES execution_decision_slots(intent_id),
                        decision_id TEXT NOT NULL REFERENCES execution_decisions(decision_id),
                        intent_key_json TEXT NOT NULL,
                        economic_payload_json TEXT NOT NULL,
                        original_identity_json TEXT NOT NULL,
                        owner_intent_id TEXT,
                        state TEXT NOT NULL CHECK(state IN ('PREPARED','DISPATCHING','KNOWN','UNKNOWN')),
                        dispatch_state TEXT CHECK(dispatch_state IN ('KNOWN','UNKNOWN') OR dispatch_state IS NULL),
                        provider_identity_json TEXT,
                        outcome_code TEXT,
                        dispatch_result_json TEXT,
                        created_at_ns INTEGER NOT NULL,
                        updated_at_ns INTEGER NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS execution_native_intent_identities (
                        intent_id TEXT PRIMARY KEY
                            REFERENCES execution_decision_intents(intent_id),
                        account_scope TEXT NOT NULL,
                        strategy_scope TEXT NOT NULL,
                        trading_day TEXT NOT NULL CHECK(length(trading_day) = 8),
                        instrument TEXT NOT NULL,
                        exchange TEXT NOT NULL,
                        order_ref TEXT NOT NULL,
                        UNIQUE(account_scope, trading_day, order_ref)
                    );
                    CREATE TABLE IF NOT EXISTS execution_decision_callbacks (
                        receipt_id TEXT PRIMARY KEY,
                        intent_id TEXT NOT NULL REFERENCES execution_decision_intents(intent_id),
                        callback_id TEXT NOT NULL,
                        evidence_payload_json TEXT NOT NULL,
                        acknowledged INTEGER NOT NULL CHECK(acknowledged IN (0,1)),
                        created_at_ns INTEGER NOT NULL,
                        process_instance_id TEXT,
                        delivery_pending INTEGER NOT NULL DEFAULT 1
                            CHECK(delivery_pending IN (0,1)),
                        UNIQUE(intent_id, callback_id)
                    );
                    CREATE TABLE IF NOT EXISTS execution_instrument_owners (
                        account_scope TEXT NOT NULL,
                        instrument TEXT NOT NULL,
                        owner_intent_id TEXT,
                        cancel_intent_id TEXT,
                        PRIMARY KEY(account_scope, instrument)
                    );
                    CREATE TABLE IF NOT EXISTS execution_intent_resolutions (
                        intent_id TEXT PRIMARY KEY REFERENCES execution_decision_intents(intent_id),
                        account_scope TEXT NOT NULL,
                        instrument TEXT NOT NULL,
                        terminal_state TEXT NOT NULL,
                        terminal_event_id TEXT NOT NULL,
                        reconciliation_id TEXT NOT NULL,
                        position_snapshot_id TEXT NOT NULL,
                        position_flat INTEGER NOT NULL CHECK(position_flat IN (0,1)),
                        created_at_ns INTEGER NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS execution_intent_reconciliations (
                        reconciliation_id TEXT PRIMARY KEY,
                        intent_id TEXT NOT NULL REFERENCES execution_decision_intents(intent_id),
                        original_identity_json TEXT NOT NULL,
                        query_id TEXT NOT NULL,
                        state TEXT NOT NULL CHECK(state IN ('KNOWN','UNKNOWN')),
                        provider_identity_json TEXT NOT NULL,
                        outcome_code TEXT,
                        terminal_state TEXT CHECK(terminal_state IN ('FILLED','CANCELLED','REJECTED') OR terminal_state IS NULL),
                        terminal_event_id TEXT,
                        position_snapshot_id TEXT,
                        position_flat INTEGER CHECK(position_flat IN (0,1) OR position_flat IS NULL),
                        created_at_ns INTEGER NOT NULL,
                        UNIQUE(intent_id, query_id),
                        CHECK(
                            (terminal_state IS NULL AND terminal_event_id IS NULL
                             AND position_snapshot_id IS NULL AND position_flat IS NULL)
                            OR
                            (state = 'KNOWN' AND terminal_state IS NOT NULL
                             AND terminal_event_id IS NOT NULL
                             AND position_snapshot_id IS NOT NULL
                             AND position_flat IS NOT NULL)
                        )
                    );
                    CREATE TABLE IF NOT EXISTS execution_callback_query_dispositions (
                        native_receipt_id TEXT PRIMARY KEY
                            REFERENCES execution_decision_callbacks(receipt_id),
                        query_receipt_id TEXT NOT NULL UNIQUE
                            REFERENCES execution_decision_callbacks(receipt_id),
                        intent_id TEXT NOT NULL REFERENCES execution_decision_intents(intent_id),
                        execution_id TEXT NOT NULL,
                        disposition_code TEXT NOT NULL
                            CHECK(disposition_code = 'QUERY_MATCHED_BROKER_ACK_UNOBSERVED_AFTER_RESTART'),
                        query_process_instance_id TEXT NOT NULL,
                        proof_payload_json TEXT NOT NULL,
                        proof_sha256 TEXT NOT NULL CHECK(length(proof_sha256) = 64),
                        created_at_ns INTEGER NOT NULL
                    );
                    CREATE TRIGGER IF NOT EXISTS execution_callback_query_disposition_no_update
                    BEFORE UPDATE ON execution_callback_query_dispositions
                    BEGIN SELECT RAISE(ABORT, 'callback query disposition is append only'); END;
                    CREATE TRIGGER IF NOT EXISTS execution_callback_query_disposition_no_delete
                    BEFORE DELETE ON execution_callback_query_dispositions
                    BEGIN SELECT RAISE(ABORT, 'callback query disposition is append only'); END;
                    CREATE TRIGGER IF NOT EXISTS execution_callback_disposition_no_ack
                    BEFORE UPDATE OF acknowledged ON execution_decision_callbacks
                    WHEN NEW.acknowledged=1 AND EXISTS (
                        SELECT 1 FROM execution_callback_query_dispositions AS d
                        WHERE d.native_receipt_id=OLD.receipt_id
                    )
                    BEGIN SELECT RAISE(ABORT, 'query-dispositioned callback remains unacknowledged'); END;
                    CREATE TABLE IF NOT EXISTS execution_intent_abandonments (
                        abandonment_id TEXT PRIMARY KEY,
                        intent_id TEXT NOT NULL UNIQUE REFERENCES execution_decision_intents(intent_id),
                        reason_code TEXT NOT NULL,
                        created_at_ns INTEGER NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS execution_slot_abandonments (
                        abandonment_id TEXT PRIMARY KEY,
                        intent_id TEXT NOT NULL UNIQUE
                            REFERENCES execution_decision_slots(intent_id),
                        reason_code TEXT NOT NULL,
                        created_at_ns INTEGER NOT NULL
                    );
                    CREATE TRIGGER IF NOT EXISTS execution_reconciliation_no_update
                    BEFORE UPDATE ON execution_intent_reconciliations
                    BEGIN SELECT RAISE(ABORT, 'reconciliation is append only'); END;
                    CREATE TRIGGER IF NOT EXISTS execution_reconciliation_no_delete
                    BEFORE DELETE ON execution_intent_reconciliations
                    BEGIN SELECT RAISE(ABORT, 'reconciliation is append only'); END;
                    CREATE TRIGGER IF NOT EXISTS execution_abandonment_no_update
                    BEFORE UPDATE ON execution_intent_abandonments
                    BEGIN SELECT RAISE(ABORT, 'abandonment is append only'); END;
                    CREATE TRIGGER IF NOT EXISTS execution_abandonment_no_delete
                    BEFORE DELETE ON execution_intent_abandonments
                    BEGIN SELECT RAISE(ABORT, 'abandonment is append only'); END;
                    CREATE TRIGGER IF NOT EXISTS execution_slot_abandonment_no_update
                    BEFORE UPDATE ON execution_slot_abandonments
                    BEGIN SELECT RAISE(ABORT, 'slot abandonment is append only'); END;
                    CREATE TRIGGER IF NOT EXISTS execution_slot_abandonment_no_delete
                    BEFORE DELETE ON execution_slot_abandonments
                    BEGIN SELECT RAISE(ABORT, 'slot abandonment is append only'); END;
                    CREATE INDEX IF NOT EXISTS execution_decision_intents_recovery
                        ON execution_decision_intents(state, created_at_ns);
                    CREATE INDEX IF NOT EXISTS execution_intent_reconciliations_order
                        ON execution_intent_reconciliations(intent_id, created_at_ns);
                    CREATE INDEX IF NOT EXISTS execution_native_intent_lookup
                        ON execution_native_intent_identities(
                            account_scope, strategy_scope, trading_day,
                            instrument, exchange, order_ref
                        );
                    """
                )
                from .factor_position_book import ensure_factor_position_book_schema

                cursor = self._connection.cursor()
                try:
                    ensure_factor_position_book_schema(cursor)
                finally:
                    cursor.close()
                self._connection.execute("BEGIN IMMEDIATE")
                # Multiple processes can read an old user_version before either
                # obtains the write lock. Re-read under BEGIN IMMEDIATE so a
                # waiter observes the migration committed by the first opener.
                locked_version = int(self._connection.execute("PRAGMA user_version").fetchone()[0])
                if locked_version not in (
                    0,
                    1,
                    2,
                    3,
                    4,
                    5,
                    6,
                    7,
                    8,
                    9,
                    10,
                    11,
                    self._SCHEMA_VERSION,
                ):
                    raise ExecutionDecisionJournalError("UNSUPPORTED_SCHEMA_VERSION")
                callback_columns = {
                    row["name"]
                    for row in self._connection.execute(
                        "PRAGMA table_info(execution_decision_callbacks)"
                    ).fetchall()
                }
                if (
                    locked_version == self._SCHEMA_VERSION
                    and not {
                        "process_instance_id",
                        "delivery_pending",
                    }
                    <= callback_columns
                ):
                    raise ExecutionDecisionJournalError("CALLBACK_DELIVERY_SCHEMA_CORRUPT")
                if "process_instance_id" not in callback_columns:
                    self._connection.execute(
                        "ALTER TABLE execution_decision_callbacks ADD COLUMN process_instance_id TEXT"
                    )
                if "delivery_pending" not in callback_columns:
                    if locked_version == self._SCHEMA_VERSION:
                        raise ExecutionDecisionJournalError("CALLBACK_DELIVERY_SCHEMA_CORRUPT")
                    self._connection.execute(
                        """ALTER TABLE execution_decision_callbacks
                           ADD COLUMN delivery_pending INTEGER NOT NULL DEFAULT 0
                           CHECK(delivery_pending IN (0,1))"""
                    )
                disposition_columns = {
                    row["name"]
                    for row in self._connection.execute(
                        "PRAGMA table_info(execution_callback_query_dispositions)"
                    ).fetchall()
                }
                if (
                    locked_version == self._SCHEMA_VERSION
                    and not {
                        "query_process_instance_id",
                        "proof_payload_json",
                        "proof_sha256",
                    }
                    <= disposition_columns
                ):
                    raise ExecutionDecisionJournalError("CALLBACK_DELIVERY_SCHEMA_CORRUPT")
                if "query_process_instance_id" not in disposition_columns:
                    # Any intermediate/legacy disposition has no durable
                    # process-incarnation witness and remains unusable.
                    self._connection.execute(
                        "ALTER TABLE execution_callback_query_dispositions "
                        "ADD COLUMN query_process_instance_id TEXT"
                    )
                if locked_version in (0, 1):
                    columns = {
                        row["name"]
                        for row in self._connection.execute(
                            "PRAGMA table_info(execution_decision_intents)"
                        ).fetchall()
                    }
                    if "dispatch_state" not in columns:
                        self._connection.execute(
                            """ALTER TABLE execution_decision_intents ADD COLUMN dispatch_state
                               TEXT CHECK(dispatch_state IN ('KNOWN','UNKNOWN')
                                           OR dispatch_state IS NULL)"""
                        )
                    self._connection.execute(
                        """UPDATE execution_decision_intents SET dispatch_state = state
                           WHERE state IN ('KNOWN','UNKNOWN') AND dispatch_state IS NULL"""
                    )
                # Version 3 added the durable eligible-grid cursor. Version 4
                # added the position book. Version 5 records unused decision slots.
                # Version 6 indexes exact native order IDs for bounded restart recovery.
                columns = {
                    row["name"]
                    for row in self._connection.execute(
                        "PRAGMA table_info(execution_decisions)"
                    ).fetchall()
                }
                if "capacity_class" not in columns:
                    self._connection.execute(
                        """ALTER TABLE execution_decisions ADD COLUMN capacity_class
                           TEXT NOT NULL DEFAULT 'BASE'
                           CHECK(capacity_class IN ('BASE','SETTLEMENT'))"""
                    )
                self._connection.execute(
                    """CREATE INDEX IF NOT EXISTS execution_decisions_capacity
                       ON execution_decisions(capacity_class, created_at_ns)"""
                )
                if locked_version < self._NATIVE_IDENTITY_SCHEMA_VERSION:
                    cursor = self._connection.cursor()
                    try:
                        self._backfill_native_intent_identities(cursor)
                    finally:
                        cursor.close()
                if locked_version < self._DECISION_CAPACITY_SCHEMA_VERSION:
                    cursor = self._connection.cursor()
                    try:
                        self._backfill_decision_capacity_usage(cursor)
                    finally:
                        cursor.close()
                if locked_version < self._SCHEMA_VERSION:
                    cursor = self._connection.cursor()
                    try:
                        self._backfill_execution_grid_highwaters(cursor)
                        self._backfill_callback_delivery_pending(cursor)
                    finally:
                        cursor.close()
                    for trigger in (
                        "execution_callback_delivery_state",
                        "execution_callback_delivery_insert",
                        "execution_callback_delivery_acknowledged",
                        "execution_callback_delivery_disposition",
                    ):
                        self._connection.execute("DROP TRIGGER IF EXISTS {}".format(trigger))
                    self._connection.execute(
                        "DROP TABLE IF EXISTS execution_callback_delivery_queue"
                    )
                self._connection.execute(
                    """CREATE INDEX IF NOT EXISTS execution_callback_delivery_order
                       ON execution_decision_callbacks(delivery_pending,created_at_ns,receipt_id)"""
                )
                self._connection.execute(
                    """CREATE INDEX IF NOT EXISTS execution_callback_disposition_startup
                       ON execution_decision_callbacks(acknowledged,delivery_pending,receipt_id)"""
                )
                self._connection.execute(
                    """CREATE TRIGGER IF NOT EXISTS execution_callback_delivery_state
                       BEFORE UPDATE OF delivery_pending ON execution_decision_callbacks
                       WHEN (OLD.delivery_pending=0 AND NEW.delivery_pending=1)
                            OR (OLD.delivery_pending=1 AND NEW.delivery_pending=0
                                AND NEW.acknowledged=0
                                AND NOT EXISTS (
                                    SELECT 1 FROM execution_callback_query_dispositions AS d
                                    WHERE d.native_receipt_id=OLD.receipt_id
                                ))
                       BEGIN
                           SELECT RAISE(ABORT, 'callback delivery requires ACK or disposition');
                       END"""
                )
                self._connection.execute(
                    """INSERT OR IGNORE INTO execution_journal_capacity
                       (singleton,max_decision_records,settlement_decision_reserve_records,
                        max_decision_bytes,settlement_decision_reserve_bytes)
                       VALUES (1,?,?,?,?)""",
                    (
                        self.max_decision_records,
                        self.settlement_decision_reserve_records,
                        self.max_decision_bytes,
                        self.settlement_decision_reserve_bytes,
                    ),
                )
                capacity = self._connection.execute(
                    "SELECT * FROM execution_journal_capacity WHERE singleton=1"
                ).fetchone()
                expected_capacity = (
                    self.max_decision_records,
                    self.settlement_decision_reserve_records,
                    self.max_decision_bytes,
                    self.settlement_decision_reserve_bytes,
                )
                actual_capacity = (
                    int(capacity["max_decision_records"]),
                    int(capacity["settlement_decision_reserve_records"]),
                    int(capacity["max_decision_bytes"]),
                    int(capacity["settlement_decision_reserve_bytes"]),
                )
                if actual_capacity != expected_capacity:
                    raise ExecutionDecisionJournalError("JOURNAL_CAPACITY_CONFIG_MISMATCH")
                cursor = self._connection.cursor()
                try:
                    self._migrate_durable_capacity_v12(cursor, locked_version)
                finally:
                    cursor.close()
                self._connection.execute("PRAGMA user_version = {}".format(self._SCHEMA_VERSION))
                self._connection.execute("COMMIT")
                # V3 added the cohort grid cursor, V4 the position book, V5 slot
                # abandonment, V6 native-id recovery, V7 capacity bounds, V8
                # transactional native-identity backfill, V9 materialized bounded
                # decision-capacity usage, V10 the cross-cohort grid highwater,
                # V11 callback query dispositions and indexed delivery state,
                # V12 cumulative typed payload budgets across journal and book rows.
            except ExecutionDecisionJournalError:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise
            except sqlite3.Error as error:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise ExecutionDecisionJournalError("JOURNAL_SCHEMA_FAILED") from error
            self._validate_callback_delivery_state_on_open()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Cursor]:
        with self._lock:
            self._ensure_writable()
            cursor = self._connection.cursor()
            try:
                cursor.execute("BEGIN IMMEDIATE")
                with durable_capacity_transaction(cursor, self.durable_capacity_limits):
                    yield cursor
                cursor.execute("COMMIT")
            except DurableCapacityError as error:
                try:
                    cursor.execute("ROLLBACK")
                except sqlite3.Error:
                    self._failed_closed = True
                if not error.code.endswith("_EXHAUSTED"):
                    self._failed_closed = True
                raise ExecutionDecisionJournalError(error.code) from error
            except sqlite3.Error as error:
                self._failed_closed = True
                try:
                    cursor.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise ExecutionDecisionJournalError("JOURNAL_WRITE_FAILED") from error
            except BaseException:
                try:
                    cursor.execute("ROLLBACK")
                except sqlite3.Error:
                    self._failed_closed = True
                raise
            finally:
                cursor.close()

    @contextmanager
    def _read_lock(self) -> Iterator[None]:
        with self._lock:
            self._ensure_open()
            try:
                yield
            except sqlite3.Error as error:
                raise ExecutionDecisionJournalError("JOURNAL_READ_FAILED") from error

    def _ensure_open(self) -> None:
        if self._closed:
            raise ExecutionDecisionJournalError("JOURNAL_CLOSED")

    def _ensure_writable(self) -> None:
        self._ensure_open()
        if self._failed_closed:
            raise ExecutionDecisionJournalError("JOURNAL_FAILED_CLOSED")


def _normalize_intent_keys(
    intent_keys: Tuple[ExecutionIntentKey, ...], max_count: int
) -> Tuple[ExecutionIntentKey, ...]:
    if type(intent_keys) not in (tuple, list):
        raise ExecutionDecisionJournalError("INVALID_INTENT_KEYS")
    if len(intent_keys) > max_count:
        raise ExecutionDecisionJournalError("PENDING_INTENT_LIMIT")
    if any(not isinstance(item, ExecutionIntentKey) for item in intent_keys):
        raise ExecutionDecisionJournalError("INVALID_INTENT_KEYS")
    keys = tuple(sorted(intent_keys, key=lambda item: item.leg))
    if tuple(item.leg for item in keys) != tuple(range(len(keys))):
        raise ExecutionDecisionJournalError("INTENT_LEGS_NOT_CONTIGUOUS")
    if len({item.instrument for item in keys}) != len(keys):
        raise ExecutionDecisionJournalError("DUPLICATE_INSTRUMENT_INTENT")
    return keys


def _decision_capacity_class(intent_keys: Tuple[ExecutionIntentKey, ...]) -> str:
    if intent_keys and all(
        item.action == "CANCEL" or item.position_effect == "CLOSE" for item in intent_keys
    ):
        return "SETTLEMENT"
    return "BASE"


def _canonical_json(value: Any) -> str:
    return json.dumps(
        _canonical_value(value),
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _sha256_text(value: Any) -> Optional[str]:
    """SQLite scalar used only to detect proof-payload corruption on migration."""

    if type(value) is not str:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _valid_run_order_reservation_evidence(
    evidence: Any, *, requested: Optional[Mapping[str, int]]
) -> bool:
    """Check persisted reservation evidence while allowing legacy replay without it."""

    if evidence is None:
        return requested is None
    if not isinstance(evidence, Mapping) or set(evidence) != {
        "max_order_intents_per_run",
        "remaining_exit_intent_reserve",
    }:
        return False
    maximum = evidence.get("max_order_intents_per_run")
    reserve = evidence.get("remaining_exit_intent_reserve")
    if type(maximum) is not int or maximum < 0 or type(reserve) is not int or reserve < 0:
        return False
    if requested is None:
        return True
    return reserve == requested.get("remaining_exit_intent_reserve")


def _canonical_value(value: Any, *, field_name: Optional[str] = None) -> Any:
    if value is None or type(value) in (str, bool, int):
        if field_name in _ECONOMIC_DECIMAL_FIELDS and type(value) is bool:
            raise ValueError("boolean is not an economic decimal")
        if field_name in _ECONOMIC_DECIMAL_FIELDS and type(value) in (str, int):
            return _canonical_decimal(value)
        return value
    if isinstance(value, Decimal):
        return _canonical_decimal(value)
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("non-finite float")
        if field_name in _ECONOMIC_DECIMAL_FIELDS:
            return _canonical_decimal(repr(value))
        return value
    if isinstance(value, Mapping):
        result = {}
        for key, item in value.items():
            if type(key) is not str:
                raise TypeError("mapping keys must be strings")
            result[key] = _canonical_value(item, field_name=key)
        return result
    if type(value) in (tuple, list):
        return [_canonical_value(item) for item in value]
    raise TypeError("unsupported journal payload value")


def _canonical_decimal(value: Any) -> str:
    if type(value) is bool:
        raise ValueError("boolean is not a decimal")
    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError("invalid decimal") from error
    if not number.is_finite():
        raise ValueError("non-finite decimal")
    parts = number.as_tuple()
    if abs(parts.exponent) > 1000 or abs(number.adjusted()) > 1000:
        raise ValueError("decimal exponent out of bounds")
    text = format(number, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in ("", "-0", "+0"):
        return "0"
    return text


def _identifier(value: Any) -> bool:
    return bool(
        type(value) is str
        and 1 <= len(value) <= 256
        and value == value.strip()
        and all(character.isascii() and character.isprintable() for character in value)
    )


def _normalize_close_time(value: Any) -> str:
    if (
        type(value) is not str
        or value.endswith("-00:00")
        or not _RFC3339_TIMESTAMP.fullmatch(value)
    ):
        raise ExecutionDecisionJournalError("INVALID_DECISION_CLOSE_TIME")
    parse_text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(parse_text)
    except ValueError as error:
        raise ExecutionDecisionJournalError("INVALID_DECISION_CLOSE_TIME") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ExecutionDecisionJournalError("NAIVE_DECISION_CLOSE_TIME")
    normalized = parsed.astimezone(timezone.utc).isoformat()
    return normalized[:-6] + "Z"


def _parse_normalized_close_time(value: str) -> datetime:
    """Parse a journal-normalized UTC timestamp for monotonic cursor checks."""

    if type(value) is not str or not value.endswith("Z"):
        raise ExecutionDecisionJournalError("INVALID_STORED_GRID_CLOSE_TIME")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise ExecutionDecisionJournalError("INVALID_STORED_GRID_CLOSE_TIME") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ExecutionDecisionJournalError("INVALID_STORED_GRID_CLOSE_TIME")
    return parsed.astimezone(timezone.utc)


def _require_identifier(value: Any, code: str) -> None:
    if not _identifier(value):
        raise ExecutionDecisionJournalError(code)


def _decision_key_values(key: ExecutionDecisionKey) -> dict[str, str]:
    return {
        "account_scope": key.account_scope,
        "strategy_scope": key.strategy_scope,
        "logical_run_id": key.logical_run_id,
        "cohort_id": key.cohort_id,
        "close_time": key.close_time,
        "decision_kind": key.decision_kind,
    }


def _intent_key_values(key: ExecutionIntentKey) -> dict[str, Any]:
    return {
        "action": key.action,
        "instrument": key.instrument,
        "side": key.side,
        "position_effect": key.position_effect,
        "leg": key.leg,
    }


def _stable_id(kind: str, value: str) -> str:
    return hashlib.sha256((kind + ":v1:" + value).encode("utf-8")).hexdigest()


def _decision_record(row: sqlite3.Row) -> ExecutionDecisionRecord:
    key_data = json.loads(row["business_key_json"])
    key = ExecutionDecisionKey(**key_data)
    keys = tuple(ExecutionIntentKey(**item) for item in json.loads(row["intent_keys_json"]))
    return ExecutionDecisionRecord(
        decision_id=row["decision_id"],
        key=key,
        economic_payload=_deep_freeze(json.loads(row["economic_payload_json"])),
        intent_keys=keys,
        created_at_ns=int(row["created_at_ns"]),
    )


def _grid_cursor_record(row: sqlite3.Row) -> ExecutionGridCursor:
    return ExecutionGridCursor(
        account_scope=row["account_scope"],
        strategy_scope=row["strategy_scope"],
        cohort_id=row["cohort_id"],
        ordinal=int(row["ordinal"]),
        epoch_id=row["epoch_id"],
        batch_id=row["batch_id"],
        close_time=row["close_time"],
        decision_id=row["decision_id"],
        updated_at_ns=int(row["updated_at_ns"]),
    )


def _intent_record(row: sqlite3.Row) -> ExecutionIntentRecord:
    result = None
    if row["provider_identity_json"] is not None:
        result = json.loads(row["provider_identity_json"])
    key = ExecutionIntentKey(**json.loads(row["intent_key_json"]))
    return ExecutionIntentRecord(
        intent_id=row["intent_id"],
        decision_id=row["decision_id"],
        key=key,
        economic_payload=_deep_freeze(json.loads(row["economic_payload_json"])),
        original_identity=_deep_freeze(json.loads(row["original_identity_json"])),
        owner_intent_id=row["owner_intent_id"],
        state=row["state"],
        dispatch_state=row["dispatch_state"],
        provider_identity=None if result is None else _deep_freeze(result),
        outcome_code=row["outcome_code"],
        created_at_ns=int(row["created_at_ns"]),
        updated_at_ns=int(row["updated_at_ns"]),
    )


def _callback_record(row: sqlite3.Row, *, is_new: bool = False) -> ExecutionCallbackReceipt:
    return ExecutionCallbackReceipt(
        receipt_id=row["receipt_id"],
        intent_id=row["intent_id"],
        callback_id=row["callback_id"],
        evidence_payload=_deep_freeze(json.loads(row["evidence_payload_json"])),
        acknowledged=bool(row["acknowledged"]),
        created_at_ns=int(row["created_at_ns"]),
        is_new=is_new,
    )


def _callback_query_disposition_record(
    row: sqlite3.Row,
) -> ExecutionCallbackQueryDisposition:
    return ExecutionCallbackQueryDisposition(
        native_receipt_id=row["native_receipt_id"],
        query_receipt_id=row["query_receipt_id"],
        intent_id=row["intent_id"],
        execution_id=row["execution_id"],
        disposition_code=row["disposition_code"],
        query_process_instance_id=row["query_process_instance_id"],
        proof_payload=_deep_freeze(json.loads(row["proof_payload_json"])),
        proof_sha256=row["proof_sha256"],
        created_at_ns=int(row["created_at_ns"]),
    )


def _callback_query_disposition_replay_matches(original: Any, candidate: Any) -> bool:
    """Compare a later query proof to the first proof's stable execution facts.

    Query IDs, session generation, snapshot IDs and collection timestamps are
    expected to change across a legitimate fresh query. The order lineage and
    the provider execution's identity, economics and fill time must remain the
    same. A nullable fee is unavailable evidence, so it neither erases nor
    contradicts a fee that was already observed.
    """

    if not isinstance(original, Mapping) or not isinstance(candidate, Mapping):
        return False
    if set(original) != set(candidate):
        return False
    for name in (
        "schema_version",
        "disposition_code",
        "native_receipt_id",
        "query_receipt_id",
        "intent_id",
        "execution_id",
        "native_callback_id",
        "native_evidence_sha256",
        "query_callback_id",
        "query_evidence_sha256",
        "original_order",
        "matched_order",
    ):
        if original.get(name) != candidate.get(name):
            return False

    old_trade = original.get("trade")
    new_trade = candidate.get("trade")
    old_query = original.get("query_set")
    new_query = candidate.get("query_set")
    if (
        not isinstance(old_trade, Mapping)
        or not isinstance(new_trade, Mapping)
        or set(old_trade) != set(new_trade)
        or not isinstance(old_query, Mapping)
        or not isinstance(new_query, Mapping)
        or set(old_query) != set(new_query)
    ):
        return False

    for name in (
        "trade_id",
        "trade_date",
        "trade_time",
        "account_fingerprint",
        "trading_day",
        "side",
        "position_effect",
        "order_sys_id",
        "filled_at_ns",
    ):
        if old_trade.get(name) != new_trade.get(name):
            return False
    try:
        if _canonical_decimal(old_trade.get("quantity")) != _canonical_decimal(
            new_trade.get("quantity")
        ) or _canonical_decimal(old_trade.get("price")) != _canonical_decimal(
            new_trade.get("price")
        ):
            return False
        old_fee = None if old_trade.get("fee") is None else _canonical_decimal(old_trade["fee"])
        new_fee = None if new_trade.get("fee") is None else _canonical_decimal(new_trade["fee"])
    except (InvalidOperation, TypeError, ValueError):
        return False
    if old_fee is not None and new_fee is not None and old_fee != new_fee:
        return False

    if (
        old_query.get("account_fingerprint") != new_query.get("account_fingerprint")
        or old_query.get("trading_day") != new_query.get("trading_day")
        or new_query.get("account_fingerprint") != new_trade.get("account_fingerprint")
        or new_query.get("trading_day") != new_trade.get("trading_day")
        or new_trade.get("query_set_id") != new_query.get("query_set_id")
        or new_trade.get("connection_generation") != new_query.get("connection_generation")
        or type(new_query.get("connection_generation")) is not int
        or new_query["connection_generation"] <= 0
        or not _identifier(new_query.get("query_set_id"))
    ):
        return False

    family_ids = new_query.get("family_request_ids")
    families = (
        "account_result",
        "orders_result",
        "trades_result",
        "instruments_result",
        "positions_result",
    )
    if (
        type(family_ids) not in (tuple, list)
        or len(family_ids) != len(families)
        or any(
            type(item) not in (tuple, list)
            or len(item) != 2
            or type(item[0]) is not str
            or type(item[1]) is not int
            or item[1] <= 0
            for item in family_ids
        )
        or tuple(item[0] for item in family_ids) != families
        or len({item[1] for item in family_ids}) != len(families)
        or dict(family_ids).get("trades_result") != new_trade.get("request_id")
    ):
        return False

    try:
        parsed_times = {}
        for name in ("started_at_utc", "completed_at_utc", "available_at_utc"):
            value = new_query.get(name)
            if type(value) is not str or not value:
                return False
            parse_text = value[:-1] + "+00:00" if value.endswith("Z") else value
            parsed = datetime.fromisoformat(parse_text)
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                return False
            parsed_times[name] = parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return False
    return bool(
        parsed_times["started_at_utc"]
        <= parsed_times["completed_at_utc"]
        == parsed_times["available_at_utc"]
    )


def _execution_id_parts(value: Any) -> Tuple[Optional[str], Optional[str]]:
    if type(value) is not str:
        return None, None
    parts = value.split(":", 2)
    if len(parts) != 3 or parts[0] != "ctp" or not re.fullmatch(r"\d{8}", parts[1]):
        return None, None
    if not parts[2] or parts[2] != parts[2].strip():
        return None, None
    return parts[1], parts[2]


def _factor_book_checkpoint_required(intent_key: ExecutionIntentKey, economics_json: str) -> bool:
    """Keep the factor-owned position projection out of generic journal orders."""

    try:
        economics = json.loads(economics_json)
    except (TypeError, ValueError):
        return False
    if not isinstance(economics, Mapping):
        return False
    if intent_key.position_effect == "OPEN":
        return bool(
            _identifier(economics.get("risk_policy_id"))
            and economics.get("factor_stop_price") is not None
        )
    return bool(
        intent_key.position_effect == "CLOSE"
        and _identifier(economics.get("owner_intent_id"))
        and economics.get("owner_position_effect") == "OPEN"
        and economics.get("owner_side") in ("BUY", "SELL")
        and _identifier(economics.get("exchange"))
    )


def _resolution_record(row: sqlite3.Row) -> ExecutionInstrumentResolution:
    return ExecutionInstrumentResolution(
        intent_id=row["intent_id"],
        account_scope=row["account_scope"],
        instrument=row["instrument"],
        terminal_state=row["terminal_state"],
        terminal_event_id=row["terminal_event_id"],
        reconciliation_id=row["reconciliation_id"],
        position_snapshot_id=row["position_snapshot_id"],
        position_flat=bool(row["position_flat"]),
        created_at_ns=int(row["created_at_ns"]),
    )


def _reconciliation_matches(
    row: sqlite3.Row,
    *,
    intent_id: str,
    original_identity_json: str,
    query_id: str,
    state: str,
    provider_identity_json: str,
    outcome_code: Optional[str],
    terminal_state: Optional[str],
    terminal_event_id: Optional[str],
    position_snapshot_id: Optional[str],
    position_flat: Optional[bool],
) -> bool:
    return (
        row["intent_id"] == intent_id
        and row["original_identity_json"] == original_identity_json
        and row["query_id"] == query_id
        and row["state"] == state
        and row["provider_identity_json"] == provider_identity_json
        and row["outcome_code"] == outcome_code
        and row["terminal_state"] == terminal_state
        and row["terminal_event_id"] == terminal_event_id
        and row["position_snapshot_id"] == position_snapshot_id
        and row["position_flat"] == (None if position_flat is None else int(position_flat))
    )


def _dispatching_no_fill_provider_identity_matches(
    provider: Mapping[str, Any],
    *,
    intent_id: str,
    intent_key: ExecutionIntentKey,
    business_key: Mapping[str, Any],
    original_identity: Mapping[str, Any],
    economics: Mapping[str, Any],
    query_id: str,
    terminal_state: str,
    terminal_event_id: str,
    position_snapshot_id: str,
) -> bool:
    """Check the narrow immutable evidence shape accepted for crash recovery."""

    evidence_kind = "complete_orders_query_dispatching_no_fill_terminal"
    expected_ctp_terminal = {
        "5": ("CANCELED", "CANCELLED"),
        "4": ("NO_TRADE_NOT_QUEUEING", "REJECTED"),
    }
    terminal = expected_ctp_terminal.get(provider.get("terminal_status"))
    if terminal is None:
        return False
    expected_families = (
        "account_result",
        "orders_result",
        "trades_result",
        "instruments_result",
        "positions_result",
    )
    family_ids = provider.get("query_family_request_ids")
    if not isinstance(family_ids, (tuple, list)) or len(family_ids) != len(expected_families):
        return False
    normalized_family_ids = []
    for row in family_ids:
        if not isinstance(row, (tuple, list)) or len(row) != 2:
            return False
        family, request_id = row
        if type(family) is not str or type(request_id) is not int or request_id <= 0:
            return False
        normalized_family_ids.append((family, request_id))
    if tuple(family for family, _request_id in normalized_family_ids) != expected_families or len(
        {request_id for _family, request_id in normalized_family_ids}
    ) != len(expected_families):
        return False
    family_request_ids = dict(normalized_family_ids)
    try:
        original_volume = Decimal(str(provider.get("volume_total_original")))
        traded_volume = Decimal(str(provider.get("volume_traded")))
        remaining_volume = Decimal(str(provider.get("volume_total")))
        requested_volume = Decimal(str(economics.get("quantity")))
    except (InvalidOperation, TypeError, ValueError):
        return False
    if any(not value.is_finite() for value in (original_volume, traded_volume, remaining_volume)):
        return False
    timestamps = {}
    timestamp_fields = (
        "query_set_started_at",
        "query_set_completed_at",
        "refresh_started_at",
        "refresh_completed_at",
        "orders_completed_at",
        "position_available_at",
    )
    for name in timestamp_fields:
        value = provider.get(name)
        if not isinstance(value, str) or _RFC3339_TIMESTAMP.fullmatch(value) is None:
            return False
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return False
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return False
        timestamps[name] = parsed.astimezone(timezone.utc)
    if not (
        timestamps["refresh_started_at"]
        <= timestamps["query_set_started_at"]
        <= timestamps["orders_completed_at"]
        <= timestamps["query_set_completed_at"]
        <= timestamps["refresh_completed_at"]
        and timestamps["orders_completed_at"] <= timestamps["position_available_at"]
    ):
        return False
    account_scope = business_key.get("account_scope")
    strategy_scope = business_key.get("strategy_scope")
    if not _identifier(account_scope) or not _identifier(strategy_scope):
        return False
    expected = {
        "account_scope": account_scope,
        "strategy_scope": strategy_scope,
        "instrument": intent_key.instrument,
        "exchange": economics.get("exchange"),
        "order_ref": original_identity.get("order_ref"),
        "account_fingerprint": original_identity.get("account_fingerprint"),
        "trading_day": original_identity.get("trading_day"),
        "front_id": original_identity.get("front_id"),
        "session_id": original_identity.get("session_id"),
        "original_order_ref": original_identity.get("order_ref"),
        "original_account_fingerprint": original_identity.get("account_fingerprint"),
        "original_trading_day": original_identity.get("trading_day"),
        "original_front_id": original_identity.get("front_id"),
        "original_session_id": original_identity.get("session_id"),
        "position_snapshot_id": position_snapshot_id,
        "broker_quantity": "0",
        "ctp_long_quantity": "0",
        "ctp_short_quantity": "0",
        "position_flat": True,
    }
    return bool(
        provider.get("evidence_kind") == evidence_kind
        and provider.get("intent_id") == intent_id
        and provider.get("observation_id") == query_id
        and _identifier(provider.get("query_set_id"))
        and _identifier(provider.get("snapshot_id"))
        and provider.get("orders_request_id") is not None
        and type(provider.get("orders_request_id")) is int
        and provider["orders_request_id"] > 0
        and family_request_ids.get("orders_result") == provider.get("orders_request_id")
        and all(
            isinstance(provider.get(name), str) and _RFC3339_TIMESTAMP.fullmatch(provider[name])
            for name in (*timestamp_fields,)
        )
        and type(provider.get("connection_generation")) is int
        and provider["connection_generation"] > 0
        and type(provider.get("original_connection_generation")) is int
        and provider["original_connection_generation"]
        == original_identity.get("connection_generation")
        and type(provider.get("front_id")) is int
        and provider["front_id"] > 0
        and type(provider.get("session_id")) is int
        and provider["session_id"] > 0
        and type(provider.get("matching_trade_count")) is int
        and provider["matching_trade_count"] == 0
        and terminal[0] == provider.get("terminal_state")
        and terminal[1] == terminal_state
        and terminal_event_id == query_id
        and provider.get("position_snapshot_id") == position_snapshot_id
        and original_volume.is_finite()
        and original_volume > 0
        and original_volume == original_volume.to_integral_value()
        and requested_volume == original_volume
        and traded_volume == 0
        and remaining_volume == original_volume
        and all(provider.get(name) == value for name, value in expected.items())
        and original_identity.get("operation") == "insert"
        and original_identity.get("instrument_id") == intent_key.instrument
        and original_identity.get("exchange_id") == economics.get("exchange")
        and original_identity.get("order_ref") == provider.get("order_ref")
        and (
            original_identity.get("order_sys_id") is None
            or original_identity.get("order_sys_id") == provider.get("order_sys_id")
        )
        and original_identity.get("account_fingerprint") is not None
        and original_identity.get("trading_day") is not None
        and original_identity.get("front_id") is not None
        and original_identity.get("session_id") is not None
        and intent_key.position_effect == "OPEN"
    )


def _dispatching_cancel_terminal_providers_match(
    *,
    parent_intent_id: str,
    cancel_intent_id: str,
    parent_reconciliation_id: str,
    cancel_reconciliation_id: str,
    query_id: str,
    position_snapshot_id: str,
    parent_provider_identity: Mapping[str, Any],
    cancel_provider_identity: Mapping[str, Any],
) -> bool:
    """Require both durable proofs to point at one exact terminal observation."""

    query_set_id = cancel_provider_identity.get("query_set_id")
    snapshot_id = cancel_provider_identity.get("snapshot_id")
    return bool(
        parent_provider_identity.get("evidence_kind") == "complete_orders_query_observation"
        and cancel_provider_identity.get("evidence_kind") == _DISPATCHING_CANCEL_CHILD_OUTCOME
        and parent_provider_identity.get("observation_id") == query_id
        and cancel_provider_identity.get("observation_id") == query_id
        and parent_provider_identity.get("parent_intent_id") == parent_intent_id
        and parent_provider_identity.get("cancel_intent_id") == cancel_intent_id
        and parent_provider_identity.get("cancel_reconciliation_id") == cancel_reconciliation_id
        and cancel_provider_identity.get("parent_intent_id") == parent_intent_id
        and cancel_provider_identity.get("cancel_intent_id") == cancel_intent_id
        and cancel_provider_identity.get("parent_reconciliation_id") == parent_reconciliation_id
        and cancel_provider_identity.get("cancel_reconciliation_id") == cancel_reconciliation_id
        and _identifier(query_set_id)
        and parent_provider_identity.get("query_set_id") == query_set_id
        and _identifier(snapshot_id)
        and parent_provider_identity.get("snapshot_id") == snapshot_id
        and parent_provider_identity.get("position_snapshot_id") == position_snapshot_id
        and cancel_provider_identity.get("position_snapshot_id") == position_snapshot_id
    )


def _dispatching_no_fill_replay_matches(
    row: Optional[sqlite3.Row],
    *,
    provider_identity: Mapping[str, Any],
    original_identity_json: str,
    terminal_state: str,
) -> bool:
    """Allow a fresh exact query to retry Store retirement after a crash."""

    if (
        row is None
        or row["state"] != "KNOWN"
        or row["outcome_code"] != _DISPATCHING_CRASH_NO_FILL_OUTCOME
        or row["terminal_state"] != terminal_state
        or row["position_flat"] != 1
        or row["original_identity_json"] != original_identity_json
    ):
        return False
    try:
        durable = json.loads(row["provider_identity_json"])
    except (TypeError, ValueError):
        return False
    stable_fields = (
        "evidence_kind",
        "intent_id",
        "account_scope",
        "strategy_scope",
        "terminal_status",
        "terminal_state",
        "volume_total_original",
        "volume_traded",
        "volume_total",
        "instrument",
        "exchange",
        "order_ref",
        "order_sys_id",
        "front_id",
        "session_id",
        "account_fingerprint",
        "trading_day",
        "original_order_ref",
        "original_front_id",
        "original_session_id",
        "original_account_fingerprint",
        "original_trading_day",
        "original_connection_generation",
        "position_flat",
        "matching_trade_count",
        "broker_quantity",
        "ctp_long_quantity",
        "ctp_short_quantity",
    )
    return bool(
        isinstance(durable, Mapping)
        and all(durable.get(name) == provider_identity.get(name) for name in stable_fields)
    )


def _reconciliation_record(row: sqlite3.Row) -> ExecutionIntentReconciliation:
    return ExecutionIntentReconciliation(
        reconciliation_id=row["reconciliation_id"],
        intent_id=row["intent_id"],
        original_identity=_deep_freeze(json.loads(row["original_identity_json"])),
        query_id=row["query_id"],
        state=row["state"],
        provider_identity=_deep_freeze(json.loads(row["provider_identity_json"])),
        outcome_code=row["outcome_code"],
        terminal_state=row["terminal_state"],
        terminal_event_id=row["terminal_event_id"],
        position_snapshot_id=row["position_snapshot_id"],
        position_flat=None if row["position_flat"] is None else bool(row["position_flat"]),
        created_at_ns=int(row["created_at_ns"]),
    )


def _abandonment_record(row: sqlite3.Row) -> ExecutionIntentAbandonment:
    return ExecutionIntentAbandonment(
        abandonment_id=row["abandonment_id"],
        intent_id=row["intent_id"],
        reason_code=row["reason_code"],
        created_at_ns=int(row["created_at_ns"]),
    )


def _slot_abandonment_record(row: sqlite3.Row) -> ExecutionIntentAbandonment:
    return ExecutionIntentAbandonment(
        abandonment_id=row["abandonment_id"],
        intent_id=row["intent_id"],
        reason_code=row["reason_code"],
        created_at_ns=int(row["created_at_ns"]),
    )


def _deep_freeze(value: Any) -> Any:
    """Return recursively read-only snapshots from frozen record dataclasses."""

    if isinstance(value, Mapping):
        return MappingProxyType({key: _deep_freeze(item) for key, item in value.items()})
    if type(value) in (list, tuple):
        return tuple(_deep_freeze(item) for item in value)
    return value
