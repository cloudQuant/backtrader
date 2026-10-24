"""Durable, route-neutral decision and dispatch evidence for ordinary Strategies.

This journal binds a Strategy's economic decision to immutable business and
intent keys before a caller invokes a Broker/Store.  A dispatch claim is a
one-way PREPARED -> DISPATCHING transition.  If a process dies after the claim,
the next process can inspect the original Backtrader/provider identities, but
cannot claim the same intent for dispatch again.  This deliberately chooses
at-most-once dispatch over a blind retry when the network outcome is uncertain.

Callbacks are stored as deduplicated evidence and delivered at least once until
acknowledged.  The journal does not project callback payloads into fills,
positions, commissions, cash, or balances; those remain authoritative only in
the selected execution route.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import time
from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import MappingProxyType
from threading import RLock
from typing import Any, Iterator, Optional, Tuple, Union


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

    _SCHEMA_VERSION = 2

    def __init__(
        self,
        database_path: Union[str, Path],
        *,
        max_pending_intents: int = 1024,
        max_pending_callbacks: int = 4096,
        max_payload_bytes: int = 65536,
    ) -> None:
        if (
            type(max_pending_intents) is not int
            or max_pending_intents < 1
            or type(max_pending_callbacks) is not int
            or max_pending_callbacks < 1
            or type(max_payload_bytes) is not int
            or max_payload_bytes < 256
        ):
            raise ExecutionDecisionJournalError("INVALID_JOURNAL_LIMIT")
        self.max_pending_intents = max_pending_intents
        self.max_pending_callbacks = max_pending_callbacks
        self.max_payload_bytes = max_payload_bytes
        self._lock = RLock()
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
            self._connection.execute("PRAGMA busy_timeout = 5000")
            if connect_path != ":memory:":
                self._connection.execute("PRAGMA journal_mode = WAL")
            self._connection.execute("PRAGMA synchronous = FULL")
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._create_schema()
        except (OSError, sqlite3.Error) as error:
            raise ExecutionDecisionJournalError("JOURNAL_UNAVAILABLE") from error

    def __enter__(self) -> "ExecutionDecisionJournal":
        self._ensure_open()
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        self.close()

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._connection.close()
                self._closed = True

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
            row = cursor.execute(
                "SELECT * FROM execution_decisions WHERE decision_id = ?", (decision_id,)
            ).fetchone()
            if row is not None:
                if (
                    row["business_key_json"] != key_json
                    or row["economic_payload_json"] != payload_json
                    or row["intent_keys_json"] != keys_json
                ):
                    raise ExecutionDecisionJournalError("DECISION_CONFLICT")
                return _decision_record(row)

            pending = int(
                cursor.execute(
                    """SELECT COUNT(*) FROM execution_decision_slots AS s
                       LEFT JOIN execution_decision_intents AS i ON i.intent_id = s.intent_id
                       WHERE (i.intent_id IS NULL OR i.state IN ('PREPARED','DISPATCHING','UNKNOWN'))
                         AND NOT EXISTS (
                             SELECT 1 FROM execution_intent_abandonments AS a
                             WHERE a.intent_id = s.intent_id
                         )"""
                ).fetchone()[0]
            )
            if pending + len(normalized_keys) > self.max_pending_intents:
                raise ExecutionDecisionJournalError("PENDING_INTENT_LIMIT")

            cursor.execute(
                """INSERT INTO execution_decisions
                   (decision_id, business_key_json, economic_payload_json,
                    intent_keys_json, created_at_ns)
                   VALUES (?, ?, ?, ?, ?)""",
                (decision_id, key_json, payload_json, keys_json, now_ns),
            )
            for intent_key in normalized_keys:
                intent_key_json = _canonical_json(_intent_key_values(intent_key))
                intent_id = _stable_id("intent", decision_id + ":" + intent_key_json)
                cursor.execute(
                    """INSERT INTO execution_decision_slots
                       (intent_id, decision_id, intent_key_json, leg)
                       VALUES (?, ?, ?, ?)""",
                    (intent_id, decision_id, intent_key_json, intent_key.leg),
                )
            row = cursor.execute(
                "SELECT * FROM execution_decisions WHERE decision_id = ?", (decision_id,)
            ).fetchone()
            return _decision_record(row)

    def decision(self, decision_id: str) -> Optional[ExecutionDecisionRecord]:
        _require_identifier(decision_id, "INVALID_DECISION_ID")
        with self._read_lock():
            row = self._connection.execute(
                "SELECT * FROM execution_decisions WHERE decision_id = ?", (decision_id,)
            ).fetchone()
        return None if row is None else _decision_record(row)

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
                "SELECT business_key_json FROM execution_decisions WHERE decision_id = ?",
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
                return _intent_record(row)

            account_scope = json.loads(decision_row["business_key_json"])["account_scope"]
            owner = cursor.execute(
                """SELECT * FROM execution_instrument_owners
                   WHERE account_scope = ? AND instrument = ?""",
                (account_scope, intent_key.instrument),
            ).fetchone()
            if intent_key.action == "SUBMIT":
                if owner_intent_id is not None:
                    raise ExecutionDecisionJournalError("UNEXPECTED_OWNER_INTENT")
                if owner is not None and owner["owner_intent_id"] is not None:
                    raise ExecutionDecisionJournalError("INSTRUMENT_OWNER_ACTIVE")
                if owner is None:
                    cursor.execute(
                        """INSERT INTO execution_instrument_owners
                           (account_scope, instrument, owner_intent_id, cancel_intent_id)
                           VALUES (?, ?, ?, NULL)""",
                        (account_scope, intent_key.instrument, intent_id),
                    )
                else:
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
                cursor.execute(
                    """UPDATE execution_instrument_owners SET cancel_intent_id = ?
                       WHERE account_scope = ? AND instrument = ?
                         AND owner_intent_id = ?""",
                    (intent_id, account_scope, intent_key.instrument, owner_intent_id),
                )
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
        now_ns = time.time_ns()
        with self._transaction() as cursor:
            intent_row = cursor.execute(
                """SELECT i.*, d.business_key_json FROM execution_decision_intents AS i
                   JOIN execution_decisions AS d ON d.decision_id = i.decision_id
                   WHERE i.intent_id = ?""",
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
                   WHERE reconciliation_id = ? AND intent_id = ?""",
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
                "SELECT * FROM execution_intent_resolutions WHERE intent_id = ?", (intent_id,)
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
                return _resolution_record(existing)
            owner = cursor.execute(
                """SELECT owner_intent_id FROM execution_instrument_owners
                   WHERE account_scope = ? AND instrument = ?""",
                (account_scope, intent_key.instrument),
            ).fetchone()
            if owner is None or owner["owner_intent_id"] != intent_id:
                raise ExecutionDecisionJournalError("INSTRUMENT_OWNER_MISMATCH")
            cursor.execute(
                """INSERT INTO execution_intent_resolutions
                   (intent_id, account_scope, instrument, terminal_state, terminal_event_id,
                    reconciliation_id, position_snapshot_id, position_flat, created_at_ns)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (intent_id,) + values + (now_ns,),
            )
            cursor.execute(
                """UPDATE execution_instrument_owners
                   SET owner_intent_id = NULL, cancel_intent_id = NULL
                   WHERE account_scope = ? AND instrument = ? AND owner_intent_id = ?""",
                (account_scope, intent_key.instrument, intent_id),
            )
            row = cursor.execute(
                "SELECT * FROM execution_intent_resolutions WHERE intent_id = ?", (intent_id,)
            ).fetchone()
            return _resolution_record(row)

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
                cursor.execute(
                    """UPDATE execution_instrument_owners
                       SET owner_intent_id = NULL, cancel_intent_id = NULL
                       WHERE account_scope = ? AND instrument = ? AND owner_intent_id = ?""",
                    (account_scope, intent_key.instrument, intent_id),
                )
            else:
                cursor.execute(
                    """UPDATE execution_instrument_owners SET cancel_intent_id = NULL
                       WHERE account_scope = ? AND instrument = ? AND cancel_intent_id = ?""",
                    (account_scope, intent_key.instrument, intent_id),
                )
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

    def claim_dispatch(self, intent_id: str) -> Optional[ExecutionDispatchClaim]:
        """Atomically claim the only dispatch attempt for one prepared intent.

        Returns ``None`` for DISPATCHING, KNOWN or UNKNOWN intents.  A process
        restart cannot turn an ambiguous dispatch back into permission to send.
        A multi-intent decision must have every declared leg prepared before
        its first leg can be claimed.
        """

        _require_identifier(intent_id, "INVALID_INTENT_ID")
        with self._transaction() as cursor:
            row = cursor.execute(
                "SELECT * FROM execution_decision_intents WHERE intent_id = ?", (intent_id,)
            ).fetchone()
            if row is None:
                raise ExecutionDecisionJournalError("INTENT_NOT_PREPARED")
            if cursor.execute(
                "SELECT 1 FROM execution_intent_abandonments WHERE intent_id = ?", (intent_id,)
            ).fetchone():
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
            missing = int(
                cursor.execute(
                    """SELECT COUNT(*) FROM execution_decision_slots AS s
                       LEFT JOIN execution_decision_intents AS i ON i.intent_id = s.intent_id
                       WHERE s.decision_id = ? AND i.intent_id IS NULL""",
                    (row["decision_id"],),
                ).fetchone()[0]
            )
            if missing:
                raise ExecutionDecisionJournalError("DECISION_INTENTS_INCOMPLETE")
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
            now_ns = time.time_ns()
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
                return _callback_record(existing)
            pending = int(
                cursor.execute(
                    "SELECT COUNT(*) FROM execution_decision_callbacks WHERE acknowledged = 0"
                ).fetchone()[0]
            )
            if pending >= self.max_pending_callbacks:
                raise ExecutionDecisionJournalError("PENDING_CALLBACK_LIMIT")
            cursor.execute(
                """INSERT INTO execution_decision_callbacks
                   (receipt_id, intent_id, callback_id, evidence_payload_json,
                    acknowledged, created_at_ns)
                   VALUES (?, ?, ?, ?, 0, ?)""",
                (receipt_id, intent_id, callback_id, payload_json, now_ns),
            )
            row = cursor.execute(
                "SELECT * FROM execution_decision_callbacks WHERE receipt_id = ?",
                (receipt_id,),
            ).fetchone()
            return _callback_record(row)

    def pending_callbacks(self, *, limit: int) -> Tuple[ExecutionCallbackReceipt, ...]:
        """Fetch a bounded page of callback evidence awaiting caller delivery."""

        if type(limit) is not int or not 1 <= limit <= self.max_pending_callbacks:
            raise ExecutionDecisionJournalError("INVALID_CALLBACK_LIMIT")
        with self._read_lock():
            rows = self._connection.execute(
                """SELECT * FROM execution_decision_callbacks WHERE acknowledged = 0
                   ORDER BY created_at_ns, receipt_id LIMIT ?""",
                (limit,),
            ).fetchall()
        return tuple(_callback_record(row) for row in rows)

    def acknowledge_callback(self, receipt_id: str) -> None:
        """Acknowledge only after caller code has returned successfully."""

        _require_identifier(receipt_id, "INVALID_CALLBACK_RECEIPT_ID")
        with self._transaction() as cursor:
            row = cursor.execute(
                "SELECT acknowledged FROM execution_decision_callbacks WHERE receipt_id = ?",
                (receipt_id,),
            ).fetchone()
            if row is None:
                raise ExecutionDecisionJournalError("CALLBACK_NOT_FOUND")
            if not row["acknowledged"]:
                cursor.execute(
                    "UPDATE execution_decision_callbacks SET acknowledged = 1 WHERE receipt_id = ?",
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

    def _create_schema(self) -> None:
        with self._lock:
            version = int(self._connection.execute("PRAGMA user_version").fetchone()[0])
            if version not in (0, 1, self._SCHEMA_VERSION):
                raise ExecutionDecisionJournalError("UNSUPPORTED_SCHEMA_VERSION")
            try:
                self._connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS execution_decisions (
                        decision_id TEXT PRIMARY KEY,
                        business_key_json TEXT NOT NULL UNIQUE,
                        economic_payload_json TEXT NOT NULL,
                        intent_keys_json TEXT NOT NULL,
                        created_at_ns INTEGER NOT NULL
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
                    CREATE TABLE IF NOT EXISTS execution_decision_callbacks (
                        receipt_id TEXT PRIMARY KEY,
                        intent_id TEXT NOT NULL REFERENCES execution_decision_intents(intent_id),
                        callback_id TEXT NOT NULL,
                        evidence_payload_json TEXT NOT NULL,
                        acknowledged INTEGER NOT NULL CHECK(acknowledged IN (0,1)),
                        created_at_ns INTEGER NOT NULL,
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
                    CREATE TABLE IF NOT EXISTS execution_intent_abandonments (
                        abandonment_id TEXT PRIMARY KEY,
                        intent_id TEXT NOT NULL UNIQUE REFERENCES execution_decision_intents(intent_id),
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
                    CREATE INDEX IF NOT EXISTS execution_decision_intents_recovery
                        ON execution_decision_intents(state, created_at_ns);
                    CREATE INDEX IF NOT EXISTS execution_decision_callbacks_pending
                        ON execution_decision_callbacks(acknowledged, created_at_ns);
                    CREATE INDEX IF NOT EXISTS execution_intent_reconciliations_order
                        ON execution_intent_reconciliations(intent_id, created_at_ns);
                    """
                )
                if version in (0, 1):
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
                if version in (0, 1):
                    self._connection.execute("PRAGMA user_version = 2")
            except sqlite3.Error as error:
                raise ExecutionDecisionJournalError("JOURNAL_SCHEMA_FAILED") from error

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Cursor]:
        with self._lock:
            self._ensure_writable()
            cursor = self._connection.cursor()
            try:
                cursor.execute("BEGIN IMMEDIATE")
                yield cursor
                cursor.execute("COMMIT")
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
                    pass
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


def _canonical_json(value: Any) -> str:
    return json.dumps(
        _canonical_value(value),
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


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


def _callback_record(row: sqlite3.Row) -> ExecutionCallbackReceipt:
    return ExecutionCallbackReceipt(
        receipt_id=row["receipt_id"],
        intent_id=row["intent_id"],
        callback_id=row["callback_id"],
        evidence_payload=_deep_freeze(json.loads(row["evidence_payload_json"])),
        acknowledged=bool(row["acknowledged"]),
        created_at_ns=int(row["created_at_ns"]),
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


def _deep_freeze(value: Any) -> Any:
    """Return recursively read-only snapshots from frozen record dataclasses."""

    if isinstance(value, Mapping):
        return MappingProxyType({key: _deep_freeze(item) for key, item in value.items()})
    if type(value) in (list, tuple):
        return tuple(_deep_freeze(item) for item in value)
    return value
