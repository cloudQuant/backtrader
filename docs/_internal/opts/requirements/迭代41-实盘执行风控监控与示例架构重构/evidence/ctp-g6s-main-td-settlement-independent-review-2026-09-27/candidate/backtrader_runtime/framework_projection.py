"""Durable, session-scoped receipts for managed Backtrader fill projection.

The execution SDK is authoritative for provider identity and normalized fill
facts.  Backtrader's order, position and observer state is deliberately
in-process, so it cannot share the SDK's SQLite transaction.  This small
journal records which *framework runtime session* has taken one evidenced
checkpoint.  A later process session may replay the same checkpoint into its
fresh framework state; a second callback in the same session is rejected.

This is intentionally a local crash-recovery mechanism.  It never performs
provider I/O, does not infer cash or fees, and cannot turn separate execution,
risk, monitor and provider stores into a distributed transaction.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from threading import RLock
from typing import Any, Optional


class FrameworkProjectionRecoveryError(RuntimeError):
    """A framework projection checkpoint cannot be claimed or completed safely."""


@dataclass(frozen=True)
class FrameworkProjectionClaim:
    """One private in-process claim to apply a durable execution checkpoint."""

    receipt_id: str
    scope_key: str
    intent_id: str
    evidence_sha256: str
    session_id: str
    claim_token: str
    intent_fingerprint: str
    canonical_fingerprint: str
    state: str
    provider_order_id: str
    filled_quantity: Decimal
    average_price: Decimal
    cumulative_commission: Decimal


@dataclass(frozen=True)
class FrameworkSourceEventClaim:
    """Private receipt for one immutable execution-outbox event."""

    receipt_id: str
    scope_key: str
    journal_incarnation_id: str
    session_id: str
    sequence: int
    event_id: str
    event_sha256: str
    intent_id: str
    canonical_fingerprint: str
    claim_token: str
    event_type: str
    state: str
    provider_order_id: Optional[str]
    filled_quantity: Decimal
    average_price: Optional[Decimal]
    cumulative_commission: Optional[Decimal]


class FrameworkProjectionJournal:
    """SQLite receipt store that provides exactly once *per framework session*.

    A process crash destroys Backtrader's in-memory broker state.  The next
    reviewed runtime therefore gets a distinct session id and is allowed to
    apply the same checkpoint once into its fresh state.  Within one session,
    the completed receipt blocks a duplicate strategy callback from booking the
    same position/commission/observer event twice.
    """

    _SCHEMA_VERSION = 1
    _CLAIMED = "CLAIMED"
    _APPLIED = "APPLIED"

    def __init__(self, state_directory: str | Path) -> None:
        root = Path(state_directory).expanduser().resolve(strict=False)
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "framework_projection.sqlite3"
        try:
            self._connection = sqlite3.connect(
                str(self.path), isolation_level=None, check_same_thread=False
            )
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA busy_timeout = 5000")
            self._connection.execute("PRAGMA journal_mode = WAL")
            self._connection.execute("PRAGMA synchronous = FULL")
            self._lock = RLock()
            self._create_schema()
        except sqlite3.Error as error:
            raise FrameworkProjectionRecoveryError(
                "unable to initialize framework projection journal"
            ) from error

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def claim(
        self,
        *,
        record: Any,
        canonical_fingerprint: str,
        session_id: str,
        lease_fencing_token: int,
    ) -> FrameworkProjectionClaim:
        """Claim one fill checkpoint for one fresh framework runtime session.

        ``record`` must be the SDK's durable execution record, rather than a
        provider response.  Therefore a crash after SDK confirmation but
        before this bridge runs can still be recovered when the same sealed
        intent is materialized after restart.
        """

        scope_key, intent_id, intent_fingerprint = self._record_identity(record)
        canonical_fingerprint = self._digest_text(
            canonical_fingerprint, "canonical framework projection fingerprint"
        )
        session_id = self._identifier(session_id, "framework projection session")
        if type(lease_fencing_token) is not int or lease_fencing_token <= 0:
            raise FrameworkProjectionRecoveryError("invalid framework projection writer fence")
        state, provider_order_id, filled, average, commission = self._fill_evidence(record)
        evidence_sha256 = self._evidence_digest(
            scope_key=scope_key,
            intent_id=intent_id,
            intent_fingerprint=intent_fingerprint,
            canonical_fingerprint=canonical_fingerprint,
            state=state,
            provider_order_id=provider_order_id,
            filled_quantity=filled,
            average_price=average,
            cumulative_commission=commission,
        )
        now_ns = time.time_ns()
        with self._transaction() as cursor:
            prior_rows = cursor.execute(
                """
                SELECT intent_fingerprint, canonical_fingerprint
                FROM framework_projection_checkpoints
                WHERE scope_key = ? AND intent_id = ?
                """,
                (scope_key, intent_id),
            ).fetchall()
            if any(
                str(prior["intent_fingerprint"]) != intent_fingerprint
                or str(prior["canonical_fingerprint"]) != canonical_fingerprint
                for prior in prior_rows
            ):
                # A new local order must materialize the same sealed intent
                # and framework mapping.  Letting a changed Backtrader order
                # create a second receipt for one durable intent would turn a
                # recovery journal into a duplicate-accounting bypass.
                raise FrameworkProjectionRecoveryError(
                    "framework projection intent was materialized with different order facts"
                )
            row = cursor.execute(
                """
                SELECT * FROM framework_projection_checkpoints
                WHERE scope_key = ? AND intent_id = ? AND evidence_sha256 = ?
                """,
                (scope_key, intent_id, evidence_sha256),
            ).fetchone()
            if row is None:
                receipt_id = uuid.uuid4().hex
                claim_token = uuid.uuid4().hex
                cursor.execute(
                    """
                    INSERT INTO framework_projection_checkpoints(
                        scope_key, intent_id, evidence_sha256, receipt_id,
                        intent_fingerprint, canonical_fingerprint, state,
                        provider_order_id, filled_quantity, average_price,
                        cumulative_commission, status, claim_session_id,
                        claim_token, lease_fencing_token, projection_count,
                        created_at_ns, updated_at_ns
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        scope_key,
                        intent_id,
                        evidence_sha256,
                        receipt_id,
                        intent_fingerprint,
                        canonical_fingerprint,
                        state,
                        provider_order_id,
                        format(filled, "f"),
                        format(average, "f"),
                        format(commission, "f"),
                        self._CLAIMED,
                        session_id,
                        claim_token,
                        lease_fencing_token,
                        0,
                        now_ns,
                        now_ns,
                    ),
                )
                return self._claim_from_values(
                    receipt_id,
                    scope_key,
                    intent_id,
                    evidence_sha256,
                    session_id,
                    claim_token,
                    intent_fingerprint,
                    canonical_fingerprint,
                    state,
                    provider_order_id,
                    filled,
                    average,
                    commission,
                )

            self._assert_row_evidence(
                row,
                intent_fingerprint=intent_fingerprint,
                canonical_fingerprint=canonical_fingerprint,
                state=state,
                provider_order_id=provider_order_id,
                filled_quantity=filled,
                average_price=average,
                cumulative_commission=commission,
            )
            if str(row["claim_session_id"]) == session_id:
                raise FrameworkProjectionRecoveryError(
                    "framework projection checkpoint is already claimed by this session"
                )
            # A new session is a restart boundary: the prior Backtrader state
            # is gone, so the same durable checkpoint must be reconstructed
            # once again.  The caller already owns the current SDK writer
            # lease; its fencing token is kept as audit evidence only.
            claim_token = uuid.uuid4().hex
            cursor.execute(
                """
                UPDATE framework_projection_checkpoints
                SET status = ?, claim_session_id = ?, claim_token = ?,
                    lease_fencing_token = ?, updated_at_ns = ?
                WHERE scope_key = ? AND intent_id = ? AND evidence_sha256 = ?
                """,
                (
                    self._CLAIMED,
                    session_id,
                    claim_token,
                    lease_fencing_token,
                    now_ns,
                    scope_key,
                    intent_id,
                    evidence_sha256,
                ),
            )
            return self._claim_from_values(
                str(row["receipt_id"]),
                scope_key,
                intent_id,
                evidence_sha256,
                session_id,
                claim_token,
                intent_fingerprint,
                canonical_fingerprint,
                state,
                provider_order_id,
                filled,
                average,
                commission,
            )

    def validate(self, claim: FrameworkProjectionClaim) -> bool:
        """Return whether the response still owns an active projection claim."""

        with self._lock:
            try:
                row = self._connection.execute(
                    """
                    SELECT receipt_id, status, claim_session_id, claim_token
                    FROM framework_projection_checkpoints
                    WHERE scope_key = ? AND intent_id = ? AND evidence_sha256 = ?
                    """,
                    (claim.scope_key, claim.intent_id, claim.evidence_sha256),
                ).fetchone()
            except sqlite3.Error as error:
                raise FrameworkProjectionRecoveryError(
                    "unable to validate framework projection receipt"
                ) from error
        return bool(
            row is not None
            and str(row["receipt_id"]) == claim.receipt_id
            and str(row["status"]) == self._CLAIMED
            and str(row["claim_session_id"]) == claim.session_id
            and str(row["claim_token"]) == claim.claim_token
        )

    def complete(self, claim: FrameworkProjectionClaim) -> None:
        """Commit that this session has applied exactly this checkpoint once."""

        now_ns = time.time_ns()
        with self._transaction() as cursor:
            result = cursor.execute(
                """
                UPDATE framework_projection_checkpoints
                SET status = ?, projection_count = projection_count + 1, updated_at_ns = ?
                WHERE scope_key = ? AND intent_id = ? AND evidence_sha256 = ?
                  AND receipt_id = ? AND status = ? AND claim_session_id = ?
                  AND claim_token = ?
                """,
                (
                    self._APPLIED,
                    now_ns,
                    claim.scope_key,
                    claim.intent_id,
                    claim.evidence_sha256,
                    claim.receipt_id,
                    self._CLAIMED,
                    claim.session_id,
                    claim.claim_token,
                ),
            )
            if result.rowcount != 1:
                raise FrameworkProjectionRecoveryError(
                    "framework projection receipt was not active for completion"
                )

    def claim_source_event(
        self,
        *,
        event: Any,
        session_id: str,
        expected_scope_key: str,
        canonical_fingerprint: str,
    ) -> Optional[FrameworkSourceEventClaim]:
        """Claim an immutable source event in sequence for one Broker session.

        A fresh framework process gets a new ``session_id`` and can replay the
        complete source journal into its empty Broker. Within that session,
        duplicate events are no-ops and older or conflicting sequence facts
        fail closed.
        """

        try:
            sequence = getattr(event, "sequence", None)
            if type(sequence) is not int or sequence <= 0:
                raise FrameworkProjectionRecoveryError("invalid source event sequence")
            event_id = self._identifier(getattr(event, "event_id", None), "source event id")
            scope_key = self._identifier(getattr(event, "scope_key", None), "source event scope")
            intent_id = self._identifier(getattr(event, "intent_id", None), "source event intent")
            incarnation = self._identifier(
                getattr(event, "journal_incarnation_id", None), "source journal incarnation"
            )
            raw_state = getattr(
                getattr(event, "state", None), "value", getattr(event, "state", None)
            )
            event_type = self._identifier(getattr(event, "event_type", None), "source event type")
            payload = getattr(event, "payload", None)
            created_at_ns = getattr(event, "created_at_ns", None)
        except AttributeError as error:
            raise FrameworkProjectionRecoveryError("invalid immutable source event") from error
        if scope_key != expected_scope_key:
            raise FrameworkProjectionRecoveryError("source event scope does not match runtime")
        if event_type not in {
            "provider_observation",
            "reconciled_observation",
            "provider_commission_evidence",
            "cancelled_by_cancel_intent",
        }:
            raise FrameworkProjectionRecoveryError("unsupported source event type")
        if raw_state not in {"ACKED", "PARTIALLY_FILLED", "FILLED", "CANCELLED", "REJECTED"}:
            raise FrameworkProjectionRecoveryError("unsupported source event state")
        if type(created_at_ns) is not int or created_at_ns <= 0:
            raise FrameworkProjectionRecoveryError("invalid source event timestamp")
        if not isinstance(payload, Mapping):
            raise FrameworkProjectionRecoveryError("invalid source event payload")
        canonical_fingerprint = self._digest_text(
            canonical_fingerprint, "canonical framework projection fingerprint"
        )
        session_id = self._identifier(session_id, "framework projection session")
        filled = self._nonnegative_decimal(payload.get("filled_quantity"), "source event quantity")
        average_raw = payload.get("average_price")
        average = (
            None
            if average_raw is None
            else self._positive_decimal(average_raw, "source event average price")
        )
        commission_raw = payload.get("cumulative_commission")
        commission = (
            None
            if commission_raw is None
            else self._finite_decimal(commission_raw, "source event cumulative commission")
        )
        provider_order_id = payload.get("provider_order_id")
        if provider_order_id is not None:
            provider_order_id = self._identifier(provider_order_id, "source event provider order")
        if filled > 0 and (average is None or commission is None or provider_order_id is None):
            raise FrameworkProjectionRecoveryError(
                "source fill event lacks price, cumulative fee, or provider identity"
            )
        if filled == 0 and raw_state in {"PARTIALLY_FILLED", "FILLED"}:
            raise FrameworkProjectionRecoveryError("source fill event has no filled quantity")

        event_facts = {
            "sequence": sequence,
            "event_id": event_id,
            "scope_key": scope_key,
            "intent_id": intent_id,
            "journal_incarnation_id": incarnation,
            "event_type": event_type,
            "state": str(raw_state),
            "created_at_ns": created_at_ns,
            "payload": dict(payload),
        }
        try:
            encoded = json.dumps(
                event_facts, sort_keys=True, separators=(",", ":"), ensure_ascii=True
            ).encode("ascii")
        except (TypeError, ValueError) as error:
            raise FrameworkProjectionRecoveryError("source event is not canonical JSON") from error
        event_sha256 = hashlib.sha256(encoded).hexdigest()
        now_ns = time.time_ns()
        with self._transaction() as cursor:
            stream = cursor.execute(
                """
                SELECT high_water_sequence, blocked FROM framework_projection_source_streams
                WHERE scope_key = ? AND journal_incarnation_id = ? AND session_id = ?
                """,
                (scope_key, incarnation, session_id),
            ).fetchone()
            if stream is None:
                cursor.execute(
                    """
                    INSERT INTO framework_projection_source_streams(
                        scope_key, journal_incarnation_id, session_id,
                        high_water_sequence, blocked, block_reason, updated_at_ns
                    ) VALUES (?, ?, ?, 0, 0, NULL, ?)
                    """,
                    (scope_key, incarnation, session_id, now_ns),
                )
                high_water = 0
            else:
                if int(stream["blocked"]):
                    raise FrameworkProjectionRecoveryError(
                        "framework projection source session is fenced"
                    )
                high_water = int(stream["high_water_sequence"])
            prior = cursor.execute(
                """
                SELECT event_sha256, canonical_fingerprint, status
                FROM framework_projection_source_events
                WHERE scope_key = ? AND journal_incarnation_id = ? AND session_id = ?
                  AND event_id = ?
                """,
                (scope_key, incarnation, session_id, event_id),
            ).fetchone()
            if prior is not None:
                if str(prior["event_sha256"]) != event_sha256:
                    raise FrameworkProjectionRecoveryError(
                        "source event identity was reused with different facts"
                    )
                if str(prior["canonical_fingerprint"]) != canonical_fingerprint:
                    raise FrameworkProjectionRecoveryError(
                        "source event was rebound to a different framework order"
                    )
                if str(prior["status"]) == self._APPLIED:
                    return None
                raise FrameworkProjectionRecoveryError("source event claim is still active")
            if sequence <= high_water:
                raise FrameworkProjectionRecoveryError("source event sequence moved backwards")
            conflicting = cursor.execute(
                """
                SELECT event_id, event_sha256 FROM framework_projection_source_events
                WHERE scope_key = ? AND journal_incarnation_id = ? AND session_id = ?
                  AND sequence = ?
                """,
                (scope_key, incarnation, session_id, sequence),
            ).fetchone()
            if conflicting is not None:
                raise FrameworkProjectionRecoveryError(
                    "source sequence was reused with different event identity"
                )
            receipt_id = uuid.uuid4().hex
            claim_token = uuid.uuid4().hex
            cursor.execute(
                """
                INSERT INTO framework_projection_source_events(
                    scope_key, journal_incarnation_id, session_id, sequence,
                    event_id, event_sha256, intent_id, canonical_fingerprint,
                    status, receipt_id, claim_token, created_at_ns, updated_at_ns
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    scope_key,
                    incarnation,
                    session_id,
                    sequence,
                    event_id,
                    event_sha256,
                    intent_id,
                    canonical_fingerprint,
                    self._CLAIMED,
                    receipt_id,
                    claim_token,
                    now_ns,
                    now_ns,
                ),
            )
            return FrameworkSourceEventClaim(
                receipt_id=receipt_id,
                scope_key=scope_key,
                journal_incarnation_id=incarnation,
                session_id=session_id,
                sequence=sequence,
                event_id=event_id,
                event_sha256=event_sha256,
                intent_id=intent_id,
                canonical_fingerprint=canonical_fingerprint,
                claim_token=claim_token,
                event_type=event_type,
                state=str(raw_state),
                provider_order_id=provider_order_id,
                filled_quantity=filled,
                average_price=average,
                cumulative_commission=commission,
            )

    def source_high_water(
        self, *, scope_key: str, journal_incarnation_id: str, session_id: str
    ) -> int:
        """Read the durable scoped source cursor for this Broker session."""

        scope_key = self._identifier(scope_key, "framework projection scope")
        incarnation = self._identifier(journal_incarnation_id, "source journal incarnation")
        session_id = self._identifier(session_id, "framework projection session")
        with self._lock:
            try:
                row = self._connection.execute(
                    """
                    SELECT high_water_sequence, blocked
                    FROM framework_projection_source_streams
                    WHERE scope_key = ? AND journal_incarnation_id = ? AND session_id = ?
                    """,
                    (scope_key, incarnation, session_id),
                ).fetchone()
            except sqlite3.Error as error:
                raise FrameworkProjectionRecoveryError(
                    "unable to read source event cursor"
                ) from error
        if row is None:
            return 0
        if int(row["blocked"]):
            raise FrameworkProjectionRecoveryError("framework projection source session is fenced")
        return int(row["high_water_sequence"])

    def advance_source_event(
        self,
        *,
        event: Any,
        session_id: str,
        expected_scope_key: str,
    ) -> bool:
        """Durably consume a known non-projection outbox row in stream order.

        Callers must use this only for explicitly allowlisted lifecycle events
        that carry no Broker execution facts. Unknown event kinds must fence,
        not advance the cursor.
        """

        try:
            sequence = getattr(event, "sequence", None)
            if type(sequence) is not int or sequence <= 0:
                raise FrameworkProjectionRecoveryError("invalid source event sequence")
            event_id = self._identifier(getattr(event, "event_id", None), "source event id")
            scope_key = self._identifier(getattr(event, "scope_key", None), "source event scope")
            intent_id = self._identifier(getattr(event, "intent_id", None), "source event intent")
            incarnation = self._identifier(
                getattr(event, "journal_incarnation_id", None), "source journal incarnation"
            )
            event_type = self._identifier(getattr(event, "event_type", None), "source event type")
            state = getattr(getattr(event, "state", None), "value", getattr(event, "state", None))
            created_at_ns = getattr(event, "created_at_ns", None)
            payload = getattr(event, "payload", None)
        except AttributeError as error:
            raise FrameworkProjectionRecoveryError("invalid immutable source event") from error
        if scope_key != expected_scope_key:
            raise FrameworkProjectionRecoveryError("source event scope does not match runtime")
        if (
            type(state) is not str
            or not state
            or type(created_at_ns) is not int
            or created_at_ns <= 0
        ):
            raise FrameworkProjectionRecoveryError("invalid non-projection source event facts")
        if not isinstance(payload, Mapping):
            raise FrameworkProjectionRecoveryError("invalid non-projection source event payload")
        session_id = self._identifier(session_id, "framework projection session")
        facts = {
            "sequence": sequence,
            "event_id": event_id,
            "scope_key": scope_key,
            "intent_id": intent_id,
            "journal_incarnation_id": incarnation,
            "event_type": event_type,
            "state": state,
            "created_at_ns": created_at_ns,
            "payload": dict(payload),
        }
        try:
            encoded = json.dumps(
                facts, sort_keys=True, separators=(",", ":"), ensure_ascii=True
            ).encode("ascii")
        except (TypeError, ValueError) as error:
            raise FrameworkProjectionRecoveryError("source event is not canonical JSON") from error
        event_sha256 = hashlib.sha256(encoded).hexdigest()
        noop_fingerprint = hashlib.sha256(
            ("non-projection:" + event_type).encode("utf-8")
        ).hexdigest()
        now_ns = time.time_ns()
        with self._transaction() as cursor:
            stream = cursor.execute(
                """
                SELECT high_water_sequence, blocked
                FROM framework_projection_source_streams
                WHERE scope_key = ? AND journal_incarnation_id = ? AND session_id = ?
                """,
                (scope_key, incarnation, session_id),
            ).fetchone()
            if stream is None:
                cursor.execute(
                    """
                    INSERT INTO framework_projection_source_streams(
                        scope_key, journal_incarnation_id, session_id,
                        high_water_sequence, blocked, block_reason, updated_at_ns
                    ) VALUES (?, ?, ?, 0, 0, NULL, ?)
                    """,
                    (scope_key, incarnation, session_id, now_ns),
                )
                high_water = 0
            else:
                if int(stream["blocked"]):
                    raise FrameworkProjectionRecoveryError(
                        "framework projection source session is fenced"
                    )
                high_water = int(stream["high_water_sequence"])
            prior = cursor.execute(
                """
                SELECT event_sha256, status FROM framework_projection_source_events
                WHERE scope_key = ? AND journal_incarnation_id = ? AND session_id = ?
                  AND event_id = ?
                """,
                (scope_key, incarnation, session_id, event_id),
            ).fetchone()
            if prior is not None:
                if str(prior["event_sha256"]) != event_sha256:
                    raise FrameworkProjectionRecoveryError(
                        "source event identity was reused with different facts"
                    )
                if str(prior["status"]) == self._APPLIED:
                    return False
                raise FrameworkProjectionRecoveryError("source event claim is still active")
            if sequence <= high_water:
                raise FrameworkProjectionRecoveryError("source event sequence moved backwards")
            conflicting = cursor.execute(
                """
                SELECT event_id FROM framework_projection_source_events
                WHERE scope_key = ? AND journal_incarnation_id = ? AND session_id = ?
                  AND sequence = ?
                """,
                (scope_key, incarnation, session_id, sequence),
            ).fetchone()
            if conflicting is not None:
                raise FrameworkProjectionRecoveryError(
                    "source sequence was reused with different event identity"
                )
            cursor.execute(
                """
                INSERT INTO framework_projection_source_events(
                    scope_key, journal_incarnation_id, session_id, sequence,
                    event_id, event_sha256, intent_id, canonical_fingerprint,
                    status, receipt_id, claim_token, created_at_ns, updated_at_ns
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    scope_key,
                    incarnation,
                    session_id,
                    sequence,
                    event_id,
                    event_sha256,
                    intent_id,
                    noop_fingerprint,
                    self._APPLIED,
                    uuid.uuid4().hex,
                    uuid.uuid4().hex,
                    now_ns,
                    now_ns,
                ),
            )
            updated = cursor.execute(
                """
                UPDATE framework_projection_source_streams
                SET high_water_sequence = ?, updated_at_ns = ?
                WHERE scope_key = ? AND journal_incarnation_id = ? AND session_id = ?
                  AND blocked = 0 AND high_water_sequence < ?
                """,
                (sequence, now_ns, scope_key, incarnation, session_id, sequence),
            )
            if updated.rowcount != 1:
                raise FrameworkProjectionRecoveryError(
                    "source stream high-water moved unexpectedly"
                )
        return True

    def complete_source_event(self, claim: FrameworkSourceEventClaim) -> None:
        """Persist the source high-water only after Broker accounting succeeds."""

        now_ns = time.time_ns()
        with self._transaction() as cursor:
            result = cursor.execute(
                """
                UPDATE framework_projection_source_events SET status = ?, updated_at_ns = ?
                WHERE scope_key = ? AND journal_incarnation_id = ? AND session_id = ?
                  AND sequence = ? AND event_id = ? AND event_sha256 = ?
                  AND receipt_id = ? AND claim_token = ? AND status = ?
                """,
                (
                    self._APPLIED,
                    now_ns,
                    claim.scope_key,
                    claim.journal_incarnation_id,
                    claim.session_id,
                    claim.sequence,
                    claim.event_id,
                    claim.event_sha256,
                    claim.receipt_id,
                    claim.claim_token,
                    self._CLAIMED,
                ),
            )
            if result.rowcount != 1:
                raise FrameworkProjectionRecoveryError(
                    "source event receipt was not active for completion"
                )
            stream = cursor.execute(
                """
                UPDATE framework_projection_source_streams
                SET high_water_sequence = ?, updated_at_ns = ?
                WHERE scope_key = ? AND journal_incarnation_id = ? AND session_id = ?
                  AND blocked = 0 AND high_water_sequence < ?
                """,
                (
                    claim.sequence,
                    now_ns,
                    claim.scope_key,
                    claim.journal_incarnation_id,
                    claim.session_id,
                    claim.sequence,
                ),
            )
            if stream.rowcount != 1:
                raise FrameworkProjectionRecoveryError(
                    "source stream high-water moved unexpectedly"
                )

    def validate_source_event(self, claim: FrameworkSourceEventClaim) -> bool:
        """Return whether a private source-event claim is still active."""

        with self._lock:
            try:
                row = self._connection.execute(
                    """
                    SELECT e.event_sha256, e.status, e.receipt_id, e.claim_token,
                           s.blocked
                    FROM framework_projection_source_events AS e
                    JOIN framework_projection_source_streams AS s
                      ON s.scope_key = e.scope_key
                     AND s.journal_incarnation_id = e.journal_incarnation_id
                     AND s.session_id = e.session_id
                    WHERE e.scope_key = ? AND e.journal_incarnation_id = ?
                      AND e.session_id = ? AND e.sequence = ? AND e.event_id = ?
                    """,
                    (
                        claim.scope_key,
                        claim.journal_incarnation_id,
                        claim.session_id,
                        claim.sequence,
                        claim.event_id,
                    ),
                ).fetchone()
            except sqlite3.Error as error:
                raise FrameworkProjectionRecoveryError(
                    "unable to validate source event receipt"
                ) from error
        return bool(
            row is not None
            and not int(row["blocked"])
            and str(row["event_sha256"]) == claim.event_sha256
            and str(row["status"]) == self._CLAIMED
            and str(row["receipt_id"]) == claim.receipt_id
            and str(row["claim_token"]) == claim.claim_token
        )

    def fence_source_session(
        self, *, scope_key: str, journal_incarnation_id: str, session_id: str, reason: str
    ) -> None:
        """Permanently fence the current framework session after uncertain apply."""

        now_ns = time.time_ns()
        scope_key = self._identifier(scope_key, "framework projection scope")
        incarnation = self._identifier(journal_incarnation_id, "source journal incarnation")
        session_id = self._identifier(session_id, "framework projection session")
        reason = self._identifier(reason, "framework projection failure reason")
        with self._transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO framework_projection_source_streams(
                    scope_key, journal_incarnation_id, session_id,
                    high_water_sequence, blocked, block_reason, updated_at_ns
                ) VALUES (?, ?, ?, 0, 1, ?, ?)
                ON CONFLICT(scope_key, journal_incarnation_id, session_id) DO UPDATE SET
                    blocked = 1, block_reason = excluded.block_reason,
                    updated_at_ns = excluded.updated_at_ns
                """,
                (scope_key, incarnation, session_id, reason, now_ns),
            )

    def pending_intent_ids(self, scope_key: str) -> tuple[str, ...]:
        """List durable fill checkpoints not completed by the current process.

        This is an operator/recovery discovery aid.  It performs no provider
        activity and does not claim that an arbitrary strategy can be rebuilt
        without its reviewed order factory.
        """

        scope_key = self._identifier(scope_key, "framework projection scope")
        with self._lock:
            try:
                rows = self._connection.execute(
                    """
                    SELECT DISTINCT intent_id FROM framework_projection_checkpoints
                    WHERE scope_key = ? ORDER BY intent_id ASC
                    """,
                    (scope_key,),
                ).fetchall()
            except sqlite3.Error as error:
                raise FrameworkProjectionRecoveryError(
                    "unable to read framework projection recovery work"
                ) from error
        return tuple(str(row["intent_id"]) for row in rows)

    def _create_schema(self) -> None:
        with self._transaction() as cursor:
            cursor.executescript(
                """
                CREATE TABLE IF NOT EXISTS framework_projection_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS framework_projection_checkpoints (
                    scope_key TEXT NOT NULL,
                    intent_id TEXT NOT NULL,
                    evidence_sha256 TEXT NOT NULL,
                    receipt_id TEXT NOT NULL UNIQUE,
                    intent_fingerprint TEXT NOT NULL,
                    canonical_fingerprint TEXT NOT NULL,
                    state TEXT NOT NULL,
                    provider_order_id TEXT NOT NULL,
                    filled_quantity TEXT NOT NULL,
                    average_price TEXT NOT NULL,
                    cumulative_commission TEXT NOT NULL,
                    status TEXT NOT NULL,
                    claim_session_id TEXT NOT NULL,
                    claim_token TEXT NOT NULL,
                    lease_fencing_token INTEGER NOT NULL,
                    projection_count INTEGER NOT NULL DEFAULT 0,
                    created_at_ns INTEGER NOT NULL,
                    updated_at_ns INTEGER NOT NULL,
                    PRIMARY KEY(scope_key, intent_id, evidence_sha256)
                );
                CREATE INDEX IF NOT EXISTS framework_projection_scope_intent
                    ON framework_projection_checkpoints(scope_key, intent_id, updated_at_ns);
                CREATE TABLE IF NOT EXISTS framework_projection_source_streams (
                    scope_key TEXT NOT NULL,
                    journal_incarnation_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    high_water_sequence INTEGER NOT NULL,
                    blocked INTEGER NOT NULL DEFAULT 0,
                    block_reason TEXT,
                    updated_at_ns INTEGER NOT NULL,
                    PRIMARY KEY(scope_key, journal_incarnation_id, session_id)
                );
                CREATE TABLE IF NOT EXISTS framework_projection_source_events (
                    scope_key TEXT NOT NULL,
                    journal_incarnation_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    event_id TEXT NOT NULL,
                    event_sha256 TEXT NOT NULL,
                    intent_id TEXT NOT NULL,
                    canonical_fingerprint TEXT NOT NULL,
                    status TEXT NOT NULL,
                    receipt_id TEXT NOT NULL UNIQUE,
                    claim_token TEXT NOT NULL,
                    created_at_ns INTEGER NOT NULL,
                    updated_at_ns INTEGER NOT NULL,
                    PRIMARY KEY(scope_key, journal_incarnation_id, session_id, event_id),
                    UNIQUE(scope_key, journal_incarnation_id, session_id, sequence)
                );
                CREATE INDEX IF NOT EXISTS framework_projection_source_event_order
                    ON framework_projection_source_events(
                        scope_key, journal_incarnation_id, session_id, sequence
                    );
                """
            )
            row = cursor.execute(
                "SELECT value FROM framework_projection_meta WHERE key = ?", ("schema_version",)
            ).fetchone()
            if row is None:
                cursor.execute(
                    "INSERT INTO framework_projection_meta(key, value) VALUES (?, ?)",
                    ("schema_version", str(self._SCHEMA_VERSION)),
                )
            elif str(row["value"]) != str(self._SCHEMA_VERSION):
                raise FrameworkProjectionRecoveryError(
                    "unsupported framework projection journal schema"
                )

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Cursor]:
        with self._lock:
            cursor = self._connection.cursor()
            try:
                cursor.execute("BEGIN IMMEDIATE")
                yield cursor
            except sqlite3.Error as error:
                self._connection.rollback()
                raise FrameworkProjectionRecoveryError(
                    "framework projection journal transaction failed"
                ) from error
            except BaseException:
                self._connection.rollback()
                raise
            else:
                try:
                    self._connection.commit()
                except sqlite3.Error as error:
                    self._connection.rollback()
                    raise FrameworkProjectionRecoveryError(
                        "framework projection journal commit failed"
                    ) from error
            finally:
                cursor.close()

    @staticmethod
    def _identifier(value: Any, field_name: str) -> str:
        if not isinstance(value, str) or not value or value != value.strip() or len(value) > 256:
            raise FrameworkProjectionRecoveryError("invalid " + field_name)
        return value

    @classmethod
    def _digest_text(cls, value: Any, field_name: str) -> str:
        value = cls._identifier(value, field_name)
        if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            raise FrameworkProjectionRecoveryError("invalid " + field_name)
        return value

    @classmethod
    def _record_identity(cls, record: Any) -> tuple[str, str, str]:
        return (
            cls._identifier(getattr(record, "scope_key", None), "framework projection scope"),
            cls._identifier(getattr(record, "intent_id", None), "framework projection intent"),
            cls._digest_text(
                getattr(record, "payload_sha256", None), "framework projection intent fingerprint"
            ),
        )

    @classmethod
    def _fill_evidence(cls, record: Any) -> tuple[str, str, Decimal, Decimal, Decimal]:
        raw_state = getattr(getattr(record, "state", None), "value", getattr(record, "state", None))
        if raw_state not in {"PARTIALLY_FILLED", "FILLED"}:
            raise FrameworkProjectionRecoveryError(
                "framework projection recovery requires a durable fill checkpoint"
            )
        provider_order_id = cls._identifier(
            getattr(record, "provider_order_id", None), "framework projection provider order"
        )
        filled = cls._positive_decimal(
            getattr(record, "filled_quantity", None), "framework projection filled quantity"
        )
        average = cls._positive_decimal(
            getattr(record, "average_price", None), "framework projection average price"
        )
        commission = cls._finite_decimal(
            getattr(record, "cumulative_commission", None),
            "framework projection cumulative commission",
        )
        return str(raw_state), provider_order_id, filled, average, commission

    @staticmethod
    def _positive_decimal(value: Any, field_name: str) -> Decimal:
        if isinstance(value, bool):
            raise FrameworkProjectionRecoveryError("invalid " + field_name)
        try:
            result = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError) as error:
            raise FrameworkProjectionRecoveryError("invalid " + field_name) from error
        if not result.is_finite() or result <= 0:
            raise FrameworkProjectionRecoveryError("invalid " + field_name)
        return result

    @staticmethod
    def _nonnegative_decimal(value: Any, field_name: str) -> Decimal:
        if isinstance(value, bool):
            raise FrameworkProjectionRecoveryError("invalid " + field_name)
        try:
            result = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError) as error:
            raise FrameworkProjectionRecoveryError("invalid " + field_name) from error
        if not result.is_finite() or result < 0:
            raise FrameworkProjectionRecoveryError("invalid " + field_name)
        return result

    @staticmethod
    def _finite_decimal(value: Any, field_name: str) -> Decimal:
        if isinstance(value, bool):
            raise FrameworkProjectionRecoveryError("invalid " + field_name)
        try:
            result = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError) as error:
            raise FrameworkProjectionRecoveryError("invalid " + field_name) from error
        if not result.is_finite():
            raise FrameworkProjectionRecoveryError("invalid " + field_name)
        return result

    @staticmethod
    def _evidence_digest(**values: Any) -> str:
        serializable = {
            name: format(value, "f") if isinstance(value, Decimal) else value
            for name, value in values.items()
        }
        payload = json.dumps(serializable, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @classmethod
    def _assert_row_evidence(cls, row: sqlite3.Row, **expected: Any) -> None:
        comparisons = {
            "intent_fingerprint": expected["intent_fingerprint"],
            "canonical_fingerprint": expected["canonical_fingerprint"],
            "state": expected["state"],
            "provider_order_id": expected["provider_order_id"],
            "filled_quantity": format(expected["filled_quantity"], "f"),
            "average_price": format(expected["average_price"], "f"),
            "cumulative_commission": format(expected["cumulative_commission"], "f"),
        }
        if any(str(row[name]) != value for name, value in comparisons.items()):
            raise FrameworkProjectionRecoveryError(
                "framework projection checkpoint evidence changed"
            )

    @staticmethod
    def _claim_from_values(
        receipt_id: str,
        scope_key: str,
        intent_id: str,
        evidence_sha256: str,
        session_id: str,
        claim_token: str,
        intent_fingerprint: str,
        canonical_fingerprint: str,
        state: str,
        provider_order_id: str,
        filled_quantity: Decimal,
        average_price: Decimal,
        cumulative_commission: Decimal,
    ) -> FrameworkProjectionClaim:
        return FrameworkProjectionClaim(
            receipt_id=receipt_id,
            scope_key=scope_key,
            intent_id=intent_id,
            evidence_sha256=evidence_sha256,
            session_id=session_id,
            claim_token=claim_token,
            intent_fingerprint=intent_fingerprint,
            canonical_fingerprint=canonical_fingerprint,
            state=state,
            provider_order_id=provider_order_id,
            filled_quantity=filled_quantity,
            average_price=average_price,
            cumulative_commission=cumulative_commission,
        )


def canonical_framework_projection_fingerprint(canonical: Any) -> str:
    """Hash the immutable order facts that must survive a restart.

    Framework order references deliberately stay out of this digest: a new
    process may materialize the same reviewed intent with a new local ref.
    """

    provider_info = getattr(canonical, "provider_info", None)
    if not isinstance(provider_info, Mapping):
        raise FrameworkProjectionRecoveryError("managed canonical order lacks provider facts")
    side = getattr(getattr(canonical, "side", None), "value", getattr(canonical, "side", None))
    effect = getattr(
        getattr(canonical, "position_effect", None),
        "value",
        getattr(canonical, "position_effect", None),
    )
    payload = {
        "instrument": getattr(canonical, "instrument", None),
        "side": side,
        "quantity": format(Decimal(str(getattr(canonical, "quantity", None))), "f"),
        "price": format(Decimal(str(getattr(canonical, "price", None))), "f"),
        "position_effect": effect,
        "reduce_only": getattr(canonical, "reduce_only", None),
        "metadata_digest": getattr(canonical, "metadata_digest", None),
        "quantity_unit": getattr(canonical, "quantity_unit", None),
        "provider_info": dict(provider_info),
    }
    try:
        canonical_json = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str
        )
    except (TypeError, ValueError) as error:
        raise FrameworkProjectionRecoveryError(
            "managed canonical order cannot be fingerprinted"
        ) from error
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


__all__ = [
    "FrameworkProjectionClaim",
    "FrameworkProjectionJournal",
    "FrameworkProjectionRecoveryError",
    "canonical_framework_projection_fingerprint",
]
