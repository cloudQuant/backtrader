"""Durable journal authority for the two offline managed-replay fixtures.

This authority is deliberately limited to the exact fixture provider labels
listed in :mod:`managed`.  It records only typed fake-provider observations,
keeps accepted orders in a durable exposure table, and can attest only the
``SIMULATION_JOURNAL`` evidence class.  It cannot bind a sandbox, SimNow, or
production scope and it does not interpret framework callbacks as fills.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

_SCHEMA_VERSION = 3
_HEX = frozenset("0123456789abcdef")

_CANCEL_PROOF_FIELDS = (
    "permit_id",
    "intent_id",
    "intent_hash",
    "cause_id",
    "claim_digest",
    "evidence_class",
    "dispatch_attempt_count",
    "execution_scope_key",
    "cancel_id",
    "target_intent_id",
    "provider_order_id",
    "cancel_intent_fingerprint",
    "terminal_state",
    "cancel_event_id",
    "cancel_event_sequence",
    "cancel_event_sha256",
    "cancel_source",
    "source_evidence_sha256",
    "target_postcondition",
    "target_state",
    "target_filled_quantity",
    "target_updated_at_ns",
    "target_record_sha256",
    "target_event_id",
    "target_event_sequence",
    "target_event_type",
    "target_event_sha256",
    "writer_owner_id",
    "writer_fencing_token",
    "writer_fence_sha256",
)


def _enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


def _cancel_event_payload(event: Any) -> dict[str, Any]:
    """Return every durable scalar and payload field in a cancellation event."""

    payload = getattr(event, "payload", None)
    if not isinstance(payload, Mapping):
        raise FakeDispatchJournalError("stored cancellation event payload is unreadable")
    values = {
        "sequence": getattr(event, "sequence", None),
        "event_id": getattr(event, "event_id", None),
        "cancel_id": getattr(event, "cancel_id", None),
        "target_intent_id": getattr(event, "target_intent_id", None),
        "scope_key": getattr(event, "scope_key", None),
        "event_type": getattr(event, "event_type", None),
        "state": _enum_value(getattr(event, "state", None)),
        "payload": dict(payload),
        "created_at_ns": getattr(event, "created_at_ns", None),
    }
    _validate_outbox_event_scalars(values, "cancellation")
    return values


def _execution_event_payload(event: Any) -> dict[str, Any]:
    """Return every durable scalar and payload field in an order event."""

    payload = getattr(event, "payload", None)
    if not isinstance(payload, Mapping):
        raise FakeDispatchJournalError("stored execution event payload is unreadable")
    values = {
        "sequence": getattr(event, "sequence", None),
        "event_id": getattr(event, "event_id", None),
        "intent_id": getattr(event, "intent_id", None),
        "scope_key": getattr(event, "scope_key", None),
        "event_type": getattr(event, "event_type", None),
        "state": _enum_value(getattr(event, "state", None)),
        "payload": dict(payload),
        "created_at_ns": getattr(event, "created_at_ns", None),
    }
    if hasattr(event, "journal_incarnation_id"):
        values["journal_incarnation_id"] = event.journal_incarnation_id
    _validate_outbox_event_scalars(values, "execution")
    return values


def _validate_outbox_event_scalars(values: dict[str, Any], label: str) -> None:
    if (
        type(values.get("sequence")) is not int
        or values["sequence"] <= 0
        or type(values.get("created_at_ns")) is not int
        or values["created_at_ns"] <= 0
        or any(
            type(values.get(name)) is not str or not values[name]
            for name in ("event_id", "scope_key", "event_type", "state")
        )
        or not isinstance(values.get("payload"), dict)
    ):
        raise FakeDispatchJournalError(f"stored {label} outbox event is malformed")


def _cancel_resolution_proof_payload(proof: Any) -> dict[str, Any]:
    """Canonical scalar payload shared with the risk proof fingerprint."""

    scope = getattr(proof, "scope", None)
    scope_key = getattr(scope, "key", None)
    if type(scope_key) is not str or not scope_key:
        raise FakeDispatchJournalError("cancel resolution proof scope is invalid")
    values: dict[str, Any] = {
        "schema": "bt-api-risk-cancel-dispatch-resolution-v1",
        "scope_key": scope_key,
    }
    for name in _CANCEL_PROOF_FIELDS:
        value = getattr(proof, name, None)
        values[name] = _enum_value(value)
    return values


class FakeDispatchJournalError(RuntimeError):
    """The local fake-provider journal cannot prove an exact dispatch fact."""


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _decimal_text(value: Any) -> str:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise FakeDispatchJournalError("invalid fake dispatch decimal") from error
    if not number.is_finite():
        raise FakeDispatchJournalError("non-finite fake dispatch decimal")
    if number == 0:
        return "0"
    return format(number.normalize(), "f")


def _valid_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in _HEX for character in value)
    )


class ManagedFakeProviderJournalAuthority:
    """Persist and verify an exact fake ACK-to-exposure transfer.

    The authority's SQLite ``BEGIN IMMEDIATE`` transaction is the account
    writer fence.  It remains open while the risk package commits its
    one-time dispatch resolution.  Every proof is bound to the current SDK
    execution record, the single dispatch attempt, an exact stable fake order
    ID, and a durable exposure row.  The risk package retains the settled
    reservation after an ACKED transfer. Digests are re-derived across the
    request, response, reconciliation, execution, and exposure records to
    detect partial or inconsistent edits. The local SQLite state is not
    authenticated against an actor able to rewrite every local file; this
    authority is limited to owner-controlled offline fixture state and is
    never native CTP, SimNow, or live-provider evidence.
    """

    def __init__(
        self,
        *,
        database_path: str | Path,
        execution_scope: Any,
        risk_scope: Any,
        execution_store: Any,
        facade: Any | None,
        risk_types: Any,
        risk_intent_mapper: Callable[[Any], Any] | None = None,
    ) -> None:
        if getattr(risk_scope, "provider", None) != "fake":
            raise FakeDispatchJournalError("simulation journal requires the fake risk provider")
        if getattr(risk_scope, "environment", None) != "offline":
            raise FakeDispatchJournalError(
                "simulation journal requires the offline risk environment"
            )
        if getattr(execution_scope, "environment", None) != "offline":
            raise FakeDispatchJournalError("simulation journal requires the offline environment")
        self._database_path = Path(database_path)
        self._execution_scope = execution_scope
        self._risk_scope = risk_scope
        self._execution_store = execution_store
        self._facade = facade
        self._risk_types = risk_types
        if risk_intent_mapper is not None and not callable(risk_intent_mapper):
            raise FakeDispatchJournalError("fake risk intent mapper must be callable")
        self._risk_intent_mapper = risk_intent_mapper
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def bind_facade(self, facade: Any) -> None:
        """Bind the exact facade whose account lease fences these records."""

        if self._facade is not None and self._facade is not facade:
            raise FakeDispatchJournalError("fake authority facade cannot be replaced")
        self._facade = facade

    def close(self) -> None:
        """No persistent connection is held between authority operations."""

    def record_provider_observation(self, intent: Any, observation: Any) -> None:
        """Durably record the fake provider response before the SDK projection.

        Accepted observations create an outstanding exposure reservation only
        when the response has one exact stable provider ID and proves zero
        fills.  Missing IDs and ambiguous outcomes remain journaled without a
        reservation and therefore cannot clear the dispatch latch.
        """

        self._require_intent_scope(intent)
        self._require_dispatching_before_provider_call(intent)
        state = self._state_value(observation)
        provider_order_id = getattr(observation, "provider_order_id", None)
        filled_quantity = _decimal_text(getattr(observation, "filled_quantity", 0))
        average_price = getattr(observation, "average_price", None)
        if state == "ACKED" and provider_order_id is not None:
            if filled_quantity != "0" or average_price is not None:
                raise FakeDispatchJournalError("fake ACK carries fill evidence")
            if not isinstance(provider_order_id, str) or not provider_order_id.strip():
                raise FakeDispatchJournalError("fake ACK provider ID is invalid")

        intent_payload = intent.to_payload()
        request_sha256 = _sha256(intent_payload)
        response = {
            "average_price": None if average_price is None else _decimal_text(average_price),
            "filled_quantity": filled_quantity,
            "intent_id": intent.intent_id,
            "provider_order_id": provider_order_id,
            "reason_code": getattr(observation, "reason_code", None),
            "request_sha256": request_sha256,
            "scope_key": intent.scope.key,
            "state": state,
        }
        response_sha256 = _sha256(response)
        response_json = _canonical(response)
        exposure = (
            self._exposure_facts(intent, provider_order_id, request_sha256)
            if state == "ACKED"
            else None
        )
        now_ns = time.time_ns()
        with self._transaction() as connection:
            prior = connection.execute(
                "SELECT * FROM fake_dispatch_journal WHERE scope_key = ? AND intent_id = ?",
                (intent.scope.key, intent.intent_id),
            ).fetchone()
            if prior is not None:
                if prior["provider_response_sha256"] == response_sha256:
                    return
                raise FakeDispatchJournalError("duplicate fake provider result conflicts")
            exposure_id = exposure["reservation_id"] if exposure is not None else None
            exposure_sha256 = exposure["reservation_sha256"] if exposure is not None else None
            reconciliation_sha256 = _sha256(
                {
                    "exposure_reservation_sha256": exposure_sha256,
                    "provider_response_sha256": response_sha256,
                    "schema": "fake-dispatch-evidence-v1",
                }
            )
            connection.execute(
                """
                INSERT INTO fake_dispatch_journal (
                    scope_key, intent_id, intent_payload_sha256, provider_state,
                    provider_order_id, request_sha256, provider_filled_quantity,
                    provider_trade_count, provider_response_sha256, provider_response_json,
                    exposure_reservation_id, exposure_reservation_sha256,
                    reconciliation_evidence_sha256, revision, created_at_ns, updated_at_ns
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    intent.scope.key,
                    intent.intent_id,
                    intent.fingerprint,
                    state,
                    provider_order_id,
                    request_sha256,
                    filled_quantity,
                    response_sha256,
                    response_json,
                    exposure_id,
                    exposure_sha256,
                    reconciliation_sha256,
                    now_ns,
                    now_ns,
                ),
            )
            if exposure is not None:
                connection.execute(
                    """
                    INSERT INTO fake_order_exposures (
                        risk_scope_key, execution_scope_key, intent_id,
                        provider_order_id, intent_payload_sha256, request_sha256,
                        reservation_id, reservation_sha256, instrument,
                        metadata_digest, side, position_effect, quantity, limit_price,
                        worst_case_notional, state, filled_quantity, trade_count,
                        created_at_ns
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', '0', 0, ?)
                    """,
                    (
                        self._risk_scope.key,
                        intent.scope.key,
                        intent.intent_id,
                        provider_order_id,
                        intent.fingerprint,
                        request_sha256,
                        exposure["reservation_id"],
                        exposure["reservation_sha256"],
                        exposure["instrument"],
                        exposure["metadata_digest"],
                        exposure["side"],
                        exposure["position_effect"],
                        exposure["quantity"],
                        exposure["limit_price"],
                        exposure["worst_case_notional"],
                        now_ns,
                    ),
                )

    def record_execution_result(self, intent: Any, record: Any) -> None:
        """Bind a fake provider result to the exact durable SDK record."""

        self._require_intent_scope(intent)
        self._current_writer_lease()
        if (
            getattr(record, "intent_id", None) != intent.intent_id
            or getattr(record, "scope_key", None) != intent.scope.key
            or getattr(record, "payload_sha256", None) != intent.fingerprint
        ):
            raise FakeDispatchJournalError("SDK execution record identity mismatch")
        now_ns = time.time_ns()
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM fake_dispatch_journal WHERE scope_key = ? AND intent_id = ?",
                (intent.scope.key, intent.intent_id),
            ).fetchone()
            if row is None:
                # No normalized response means the dispatch is unknown.  It is
                # not permissible to synthesize a provider journal row from
                # the SDK projection alone.
                return
            fact = self._execution_fact(intent, record)
            existing = self._row_execution_fact(row)
            if existing is not None:
                if existing == fact:
                    return
                differing_fields = sorted(
                    key for key in set(existing) | set(fact) if existing.get(key) != fact.get(key)
                )
                raise FakeDispatchJournalError(
                    "SDK execution projection changed: " + ",".join(differing_fields)
                )
            revision = int(row["revision"]) + 1
            updated_values = dict(fact)
            updated_values["revision"] = revision
            record_sha256 = _sha256(updated_values)
            connection.execute(
                """
                UPDATE fake_dispatch_journal
                SET record_state = ?, record_provider_order_id = ?,
                    record_filled_quantity = ?, record_permit_reference = ?,
                    record_dispatch_attempts = ?, record_review_required = ?,
                    record_updated_at_ns = ?, revision = ?, record_sha256 = ?,
                    updated_at_ns = ?
                WHERE scope_key = ? AND intent_id = ? AND revision = ?
                """,
                (
                    fact["state"],
                    fact["provider_order_id"],
                    fact["filled_quantity"],
                    fact["permit_reference"],
                    fact["dispatch_attempts"],
                    fact["review_required"],
                    fact["updated_at_ns"],
                    revision,
                    record_sha256,
                    now_ns,
                    intent.scope.key,
                    intent.intent_id,
                    int(row["revision"]),
                ),
            )

    def create_resolution_proof(self, intent_id: str, risk_gate: Any) -> Any:
        """Create the typed no-fill or ACKED_TRACKED proof from durable facts."""

        record = self._execution_store.get(intent_id, scope=self._execution_scope)
        intent = self._execution_store.get_intent(intent_id, scope=self._execution_scope)
        if record is None or intent is None:
            raise FakeDispatchJournalError("current SDK execution row is unavailable")
        self._require_intent_scope(intent)
        self._require_current_record(intent, record)
        permit_id = getattr(record, "permit_reference", None)
        if not isinstance(permit_id, str) or not permit_id:
            raise FakeDispatchJournalError("SDK record lacks the risk permit reference")
        claim = risk_gate.dispatch_claim_binding(permit_id)
        if (
            claim.scope != self._risk_scope
            or claim.intent_id != intent.intent_id
            or claim.intent_hash != self._risk_intent_hash(intent)
            or claim.permit_id != permit_id
        ):
            raise FakeDispatchJournalError("risk dispatch claim does not match SDK intent")

        lease = self._current_writer_lease()
        with self._transaction() as connection:
            self._execution_store.assert_writer_lease(self._execution_scope, lease)
            row = self._journal_row(connection, intent.scope.key, intent.intent_id)
            self._verify_journal_row(row, intent, record)
            exposure = self._verify_exposure_for_row(connection, row, intent, record)
            fence_generation = self._next_fence_generation(connection, lease)
            writer_fence_sha256 = self._writer_fence_digest(lease, fence_generation)
            connection.execute(
                """
                INSERT INTO fake_writer_fences (
                    risk_scope_key, generation, writer_fence_sha256,
                    execution_scope_key, owner_id, fencing_token, updated_at_ns
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(risk_scope_key) DO UPDATE SET
                    generation = excluded.generation,
                    writer_fence_sha256 = excluded.writer_fence_sha256,
                    execution_scope_key = excluded.execution_scope_key,
                    owner_id = excluded.owner_id,
                    fencing_token = excluded.fencing_token,
                    updated_at_ns = excluded.updated_at_ns
                """,
                (
                    self._risk_scope.key,
                    fence_generation,
                    writer_fence_sha256,
                    lease.scope_key,
                    lease.owner_id,
                    lease.fencing_token,
                    time.time_ns(),
                ),
            )
        common = {
            "scope": self._risk_scope,
            "permit_id": permit_id,
            "intent_id": intent.intent_id,
            "intent_hash": claim.intent_hash,
            "cause_id": claim.cause_id,
            "claim_digest": claim.claim_digest,
            "evidence_class": self._risk_types.DispatchEvidenceClass.SIMULATION_JOURNAL,
            "dispatch_attempt_count": int(record.dispatch_attempts),
            "journal_revision": int(row["revision"]),
            "journal_record_sha256": str(row["record_sha256"]),
            "reconciliation_evidence_sha256": str(row["reconciliation_evidence_sha256"]),
            "writer_fence_sha256": writer_fence_sha256,
            "filled_quantity": 0,
            "trade_count": 0,
        }
        if record.state.value == "ACKED" and exposure is not None:
            return self._risk_types.DispatchTrackedOrderProof(
                **common,
                provider_order_id=str(row["provider_order_id"]),
                accepted_request_sha256=str(row["request_sha256"]),
                exposure_reservation_id=str(exposure["reservation_id"]),
                exposure_reservation_sha256=str(exposure["reservation_sha256"]),
            )
        if record.state.value == "REJECTED" and exposure is None:
            return self._risk_types.DispatchTerminalProof(
                **common,
                terminal_state=self._risk_types.DispatchTerminalState.REJECTED_NO_FILL,
            )
        raise FakeDispatchJournalError("SDK outcome has no eligible fake dispatch resolution")

    @contextmanager
    def dispatch_resolution_guard(self, proof: Any, *, claim: Any) -> Iterator[Any]:
        """Verify the exact row and hold the fake account fence through commit."""

        lease = self._current_writer_lease()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._execution_store.assert_writer_lease(self._execution_scope, lease)
            if proof.scope != self._risk_scope or claim.scope != self._risk_scope:
                raise FakeDispatchJournalError("dispatch proof scope mismatch")
            if (
                proof.permit_id != claim.permit_id
                or proof.intent_id != claim.intent_id
                or proof.intent_hash != claim.intent_hash
                or proof.cause_id != claim.cause_id
                or proof.claim_digest != claim.claim_digest
            ):
                raise FakeDispatchJournalError("dispatch proof claim mismatch")
            row = self._journal_row(connection, self._execution_scope.key, proof.intent_id)
            intent = self._execution_store.get_intent(proof.intent_id, scope=self._execution_scope)
            record = self._execution_store.get(proof.intent_id, scope=self._execution_scope)
            if intent is None or record is None:
                raise FakeDispatchJournalError("current SDK journal row is unavailable")
            self._require_current_record(intent, record)
            if proof.intent_hash != self._risk_intent_hash(intent):
                raise FakeDispatchJournalError("risk proof does not map to the SDK intent")
            self._verify_journal_row(row, intent, record)
            if (
                proof.journal_revision != int(row["revision"])
                or proof.journal_record_sha256 != row["record_sha256"]
                or proof.reconciliation_evidence_sha256 != row["reconciliation_evidence_sha256"]
            ):
                raise FakeDispatchJournalError("dispatch proof is stale or journal-mismatched")
            fence = connection.execute(
                "SELECT * FROM fake_writer_fences WHERE risk_scope_key = ?",
                (self._risk_scope.key,),
            ).fetchone()
            if fence is None:
                raise FakeDispatchJournalError("account writer fence is unavailable")
            expected_fence_sha256 = self._writer_fence_digest(lease, int(fence["generation"]))
            if (
                fence["writer_fence_sha256"] != proof.writer_fence_sha256
                or expected_fence_sha256 != proof.writer_fence_sha256
                or fence["execution_scope_key"] != lease.scope_key
                or fence["owner_id"] != lease.owner_id
                or int(fence["fencing_token"]) != lease.fencing_token
            ):
                raise FakeDispatchJournalError("account writer fence changed")
            exposure = self._verify_exposure_for_row(connection, row, intent, record)
            if type(proof) is self._risk_types.DispatchTrackedOrderProof:
                if (
                    record.state.value != "ACKED"
                    or exposure is None
                    or proof.provider_order_id != row["provider_order_id"]
                    or proof.accepted_request_sha256 != row["request_sha256"]
                    or proof.exposure_reservation_id != exposure["reservation_id"]
                    or proof.exposure_reservation_sha256 != exposure["reservation_sha256"]
                    or int(record.dispatch_attempts) != 1
                    or record.review_required
                    or _decimal_text(record.filled_quantity) != "0"
                    or str(row["provider_filled_quantity"]) != "0"
                    or int(row["provider_trade_count"]) != 0
                ):
                    raise FakeDispatchJournalError("ACKED exposure transfer is not exact")
            elif type(proof) is self._risk_types.DispatchTerminalProof:
                if (
                    proof.terminal_state
                    is not self._risk_types.DispatchTerminalState.REJECTED_NO_FILL
                    or record.state.value != "REJECTED"
                    or exposure is not None
                    or row["provider_state"] != "REJECTED"
                    or row["provider_order_id"] is not None
                    or int(record.dispatch_attempts) != 1
                    or record.review_required
                    or _decimal_text(record.filled_quantity) != "0"
                    or str(row["provider_filled_quantity"]) != "0"
                    or int(row["provider_trade_count"]) != 0
                ):
                    raise FakeDispatchJournalError("rejected no-fill proof is not exact")
            else:
                raise FakeDispatchJournalError("unsupported fake dispatch proof type")
            attestation = self._risk_types.VerifiedDispatchResolution(
                scope=proof.scope,
                permit_id=proof.permit_id,
                intent_id=proof.intent_id,
                intent_hash=proof.intent_hash,
                claim_digest=proof.claim_digest,
                proof_sha256=proof.fingerprint,
                journal_revision=proof.journal_revision,
                journal_record_sha256=proof.journal_record_sha256,
                writer_fence_sha256=proof.writer_fence_sha256,
            )
            yield attestation
        finally:
            try:
                connection.rollback()
            finally:
                connection.close()

    def create_cancel_dispatch_resolution_proof(self, cancel_id: str, risk_gate: Any) -> Any:
        """Issue a separately typed proof for one evidenced fake cancellation.

        Order terminal proofs deliberately cannot enter this path.  The exact
        cancellation event, its source label, the current target-order event,
        and the live writer lease are all re-read before the immutable proof
        row is committed.
        """

        if type(cancel_id) is not str or not cancel_id or cancel_id != cancel_id.strip():
            raise FakeDispatchJournalError("invalid cancellation proof identifier")
        lease = self._current_writer_lease()
        evidence = self._cancel_dispatch_evidence(cancel_id, lease)
        claim = self._cancel_dispatch_claim(evidence, risk_gate)
        with self._transaction() as connection:
            self._execution_store.assert_writer_lease(self._execution_scope, lease)
            current = self._cancel_dispatch_evidence(cancel_id, lease)
            if current != evidence:
                raise FakeDispatchJournalError("cancellation evidence changed during proof issue")
            generation = self._next_fence_generation(connection, lease)
            writer_fence_sha256 = self._writer_fence_digest(lease, generation)
            connection.execute(
                """
                INSERT INTO fake_writer_fences (
                    risk_scope_key, generation, writer_fence_sha256,
                    execution_scope_key, owner_id, fencing_token, updated_at_ns
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(risk_scope_key) DO UPDATE SET
                    generation = excluded.generation,
                    writer_fence_sha256 = excluded.writer_fence_sha256,
                    execution_scope_key = excluded.execution_scope_key,
                    owner_id = excluded.owner_id,
                    fencing_token = excluded.fencing_token,
                    updated_at_ns = excluded.updated_at_ns
                """,
                (
                    self._risk_scope.key,
                    generation,
                    writer_fence_sha256,
                    lease.scope_key,
                    lease.owner_id,
                    lease.fencing_token,
                    time.time_ns(),
                ),
            )
            proof = self._make_cancel_resolution_proof(evidence, claim, lease, writer_fence_sha256)
            proof_payload = _cancel_resolution_proof_payload(proof)
            proof_sha256 = getattr(proof, "fingerprint", None)
            if not _valid_sha256(proof_sha256) or _sha256(proof_payload) != proof_sha256:
                raise FakeDispatchJournalError("risk cancel proof fingerprint is inconsistent")
            connection.execute(
                """
                INSERT INTO fake_cancel_resolution_proofs (
                    risk_scope_key, execution_scope_key, cancel_id, writer_fence_sha256,
                    proof_sha256, proof_json, created_at_ns
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self._risk_scope.key,
                    self._execution_scope.key,
                    cancel_id,
                    writer_fence_sha256,
                    proof_sha256,
                    _canonical(proof_payload),
                    time.time_ns(),
                ),
            )
        return proof

    @contextmanager
    def cancel_dispatch_resolution_guard(self, proof: Any, *, claim: Any) -> Iterator[Any]:
        """Re-read immutable cancel/target events under the current fake fence."""

        proof_type = getattr(self._risk_types, "CancelDispatchResolutionProof", None)
        claim_type = getattr(self._risk_types, "DispatchClaimBinding", None)
        if proof_type is None or type(proof) is not proof_type:
            raise FakeDispatchJournalError("typed cancel dispatch proof is required")
        if claim_type is None or type(claim) is not claim_type:
            raise FakeDispatchJournalError("typed dispatch claim binding is required")
        lease = self._current_writer_lease()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._execution_store.assert_writer_lease(self._execution_scope, lease)
            if proof.scope != self._risk_scope or claim.scope != self._risk_scope:
                raise FakeDispatchJournalError("cancel proof scope mismatch")
            if (
                proof.permit_id != claim.permit_id
                or proof.intent_id != claim.intent_id
                or proof.intent_hash != claim.intent_hash
                or proof.cause_id != claim.cause_id
                or proof.claim_digest != claim.claim_digest
            ):
                raise FakeDispatchJournalError("cancel proof claim mismatch")
            evidence = self._cancel_dispatch_evidence(proof.cancel_id, lease)
            self._validate_cancel_dispatch_claim(evidence, claim)
            fence = connection.execute(
                "SELECT * FROM fake_writer_fences WHERE risk_scope_key = ?",
                (self._risk_scope.key,),
            ).fetchone()
            if fence is None:
                raise FakeDispatchJournalError("account writer fence is unavailable")
            expected_fence_sha256 = self._writer_fence_digest(lease, int(fence["generation"]))
            if (
                fence["writer_fence_sha256"] != proof.writer_fence_sha256
                or expected_fence_sha256 != proof.writer_fence_sha256
                or fence["execution_scope_key"] != lease.scope_key
                or fence["owner_id"] != lease.owner_id
                or int(fence["fencing_token"]) != lease.fencing_token
                or proof.writer_owner_id != lease.owner_id
                or proof.writer_fencing_token != lease.fencing_token
            ):
                raise FakeDispatchJournalError("cancel proof writer fence changed")
            expected_proof = self._make_cancel_resolution_proof(
                evidence, claim, lease, expected_fence_sha256
            )
            supplied_payload = _cancel_resolution_proof_payload(proof)
            expected_payload = _cancel_resolution_proof_payload(expected_proof)
            proof_sha256 = getattr(proof, "fingerprint", None)
            if (
                supplied_payload != expected_payload
                or not _valid_sha256(proof_sha256)
                or _sha256(supplied_payload) != proof_sha256
            ):
                raise FakeDispatchJournalError("cancel proof is stale or evidence-mismatched")
            stored = connection.execute(
                """
                SELECT proof_sha256, proof_json FROM fake_cancel_resolution_proofs
                WHERE risk_scope_key = ? AND execution_scope_key = ? AND cancel_id = ?
                  AND writer_fence_sha256 = ?
                """,
                (
                    self._risk_scope.key,
                    self._execution_scope.key,
                    proof.cancel_id,
                    proof.writer_fence_sha256,
                ),
            ).fetchone()
            if (
                stored is None
                or stored["proof_sha256"] != proof_sha256
                or stored["proof_json"] != _canonical(supplied_payload)
            ):
                raise FakeDispatchJournalError("persisted cancel proof readback failed")
            attestation = self._risk_types.VerifiedCancelDispatchResolution(
                scope=proof.scope,
                permit_id=proof.permit_id,
                intent_id=proof.intent_id,
                intent_hash=proof.intent_hash,
                claim_digest=proof.claim_digest,
                proof_sha256=proof_sha256,
                cancel_event_id=proof.cancel_event_id,
                cancel_event_sequence=proof.cancel_event_sequence,
                cancel_event_sha256=proof.cancel_event_sha256,
                source_evidence_sha256=proof.source_evidence_sha256,
                target_postcondition=proof.target_postcondition,
                target_record_sha256=proof.target_record_sha256,
                target_event_id=proof.target_event_id,
                target_event_sequence=proof.target_event_sequence,
                target_event_sha256=proof.target_event_sha256,
                writer_owner_id=proof.writer_owner_id,
                writer_fencing_token=proof.writer_fencing_token,
                writer_fence_sha256=proof.writer_fence_sha256,
            )
            yield attestation
        finally:
            try:
                connection.rollback()
            finally:
                connection.close()

    def _cancel_dispatch_claim(self, evidence: dict[str, Any], risk_gate: Any) -> Any:
        permit_id = evidence["cancel_record"].permit_reference
        if type(permit_id) is not str or not permit_id:
            raise FakeDispatchJournalError("cancel record lacks a risk permit reference")
        intent_id = f"cancel-admission:{self._execution_scope.key}:{evidence['cancel_id']}"
        risk_intent = self._risk_types.RiskIntent(
            intent_id=intent_id,
            scope=self._risk_scope,
            action=self._risk_types.IntentAction.CANCEL,
            notional=Decimal("0"),
            payload_fingerprint=evidence["cancel_intent_fingerprint"],
        )
        if not _valid_sha256(risk_intent.fingerprint):
            raise FakeDispatchJournalError("cancel risk intent fingerprint is invalid")
        dispatch_claim_binding = getattr(risk_gate, "dispatch_claim_binding", None)
        if not callable(dispatch_claim_binding):
            raise FakeDispatchJournalError("risk gate lacks dispatch claim readback")
        claim = dispatch_claim_binding(permit_id)
        self._validate_cancel_dispatch_claim(evidence, claim, permit_id=permit_id)
        return claim

    def _validate_cancel_dispatch_claim(
        self, evidence: dict[str, Any], claim: Any, *, permit_id: str | None = None
    ) -> None:
        expected_permit_id = evidence["cancel_record"].permit_reference
        if permit_id is not None and permit_id != expected_permit_id:
            raise FakeDispatchJournalError("risk cancel permit differs from durable cancel")
        claim_type = getattr(self._risk_types, "DispatchClaimBinding", None)
        if claim_type is None or type(claim) is not claim_type:
            raise FakeDispatchJournalError("risk gate returned an invalid cancel claim")
        intent_id = f"cancel-admission:{self._execution_scope.key}:{evidence['cancel_id']}"
        risk_intent = self._risk_types.RiskIntent(
            intent_id=intent_id,
            scope=self._risk_scope,
            action=self._risk_types.IntentAction.CANCEL,
            notional=Decimal("0"),
            payload_fingerprint=evidence["cancel_intent_fingerprint"],
        )
        if (
            claim.scope != self._risk_scope
            or claim.permit_id != expected_permit_id
            or claim.intent_id != intent_id
            or claim.intent_hash != risk_intent.fingerprint
            or claim.cause_id != "dispatch-inflight:" + intent_id
            or not _valid_sha256(claim.claim_digest)
        ):
            raise FakeDispatchJournalError("risk cancel claim does not match immutable cancel")

    def _cancel_dispatch_evidence(self, cancel_id: str, lease: Any) -> dict[str, Any]:
        try:
            from bt_api_execution.contracts import (
                CancelIntent,
                ExecutionEvent,
                ExecutionScope,
                OrderIntent,
                payload_sha256,
            )
            from bt_api_execution.store import (
                CancelEvent,
                CancelObservationCommitV1,
                CancelRecord,
                ExecutionRecord,
                WriterLease,
            )
        except Exception as error:
            raise FakeDispatchJournalError("typed execution commit contract is unavailable") from error

        self._execution_store.assert_writer_lease(self._execution_scope, lease)
        readback = getattr(self._execution_store, "read_terminal_cancel_commit", None)
        if not callable(readback):
            raise FakeDispatchJournalError("execution store lacks atomic terminal cancel readback")
        try:
            commit = readback(self._execution_scope, cancel_id, writer_lease=lease)
        except Exception as error:
            raise FakeDispatchJournalError("atomic terminal cancellation readback failed") from error
        if type(commit) is not CancelObservationCommitV1:
            raise FakeDispatchJournalError("execution store returned an invalid terminal commit")

        cancel_intent = commit.cancel_intent
        cancel_record = commit.cancel_record
        cancel_event = commit.cancel_event
        target_record = commit.target_record
        target_event = commit.target_event
        writer_lease = commit.writer_lease
        if (
            type(self._execution_scope) is not ExecutionScope
            or type(lease) is not WriterLease
            or type(cancel_intent) is not CancelIntent
            or type(cancel_record) is not CancelRecord
            or type(cancel_event) is not CancelEvent
            or type(target_record) is not ExecutionRecord
            or type(target_event) is not ExecutionEvent
            or type(writer_lease) is not WriterLease
            or cancel_intent.scope != self._execution_scope
            or type(cancel_intent.scope) is not ExecutionScope
            or cancel_intent.cancel_id != cancel_id
            or cancel_record.cancel_id != cancel_id
            or cancel_record.scope_key != self._execution_scope.key
            or cancel_record.target_intent_id != cancel_intent.target_intent_id
            or cancel_record.provider_order_id != cancel_intent.provider_order_id
            or cancel_record.payload_sha256 != cancel_intent.fingerprint
            or payload_sha256(cancel_intent.to_payload()) != cancel_intent.fingerprint
            or writer_lease.scope_key != lease.scope_key
            or writer_lease.owner_id != lease.owner_id
            or writer_lease.fencing_token != lease.fencing_token
            or writer_lease.expires_at_ns != lease.expires_at_ns
        ):
            raise FakeDispatchJournalError("atomic terminal cancellation binding is inconsistent")
        if (
            cancel_record.state.value not in {"CANCELLED", "REJECTED"}
            or type(cancel_record.dispatch_attempts) is not int
            or cancel_record.dispatch_attempts != 1
            or type(cancel_record.review_required) is not bool
            or cancel_record.review_required
            or cancel_record.unknown_reason is not None
            or type(cancel_record.updated_at_ns) is not int
            or cancel_record.updated_at_ns <= 0
        ):
            raise FakeDispatchJournalError("cancel action has no eligible terminal outcome")

        event_payload = _cancel_event_payload(cancel_event)
        source_by_type = {
            "cancel_provider_observation": "provider",
            "cancel_reconciled_observation": "reconcile",
        }
        source = event_payload["payload"].get("source")
        if (
            event_payload["cancel_id"] != cancel_id
            or event_payload["target_intent_id"] != cancel_intent.target_intent_id
            or event_payload["scope_key"] != self._execution_scope.key
            or event_payload["state"] != cancel_record.state.value
            or source_by_type.get(event_payload["event_type"]) != source
            or source not in {"provider", "reconcile"}
            or set(event_payload["payload"])
            != {"provider_order_id", "reason_code", "source"}
            or event_payload["payload"].get("provider_order_id")
            != cancel_intent.provider_order_id
            or event_payload["created_at_ns"] != cancel_record.updated_at_ns
        ):
            raise FakeDispatchJournalError("terminal cancellation event binding is inconsistent")
        if payload_sha256(event_payload) != commit.cancel_event_sha256:
            raise FakeDispatchJournalError("terminal cancellation event digest is inconsistent")
        source_evidence_sha256 = payload_sha256(
            {
                "source": source,
                "provider_order_id": cancel_intent.provider_order_id,
                "reason_code": event_payload["payload"].get("reason_code"),
            }
        )
        if source_evidence_sha256 != commit.source_evidence_sha256:
            raise FakeDispatchJournalError("terminal cancellation source digest is inconsistent")

        target_intent = self._execution_store.get_intent(
            cancel_intent.target_intent_id, scope=self._execution_scope
        )
        if (
            type(target_intent) is not OrderIntent
            or target_intent.scope != self._execution_scope
            or target_intent.intent_id != cancel_intent.target_intent_id
            or target_record.intent_id != cancel_intent.target_intent_id
            or target_record.scope_key != self._execution_scope.key
            or target_record.payload_sha256 != target_intent.fingerprint
            or target_record.provider_order_id != cancel_intent.provider_order_id
            or type(target_record.dispatch_attempts) is not int
            or target_record.dispatch_attempts != 1
            or type(target_record.review_required) is not bool
            or target_record.review_required
            or target_record.unknown_reason is not None
            or type(target_record.updated_at_ns) is not int
            or target_record.updated_at_ns <= 0
            or payload_sha256(target_record) != commit.target_record_sha256
        ):
            raise FakeDispatchJournalError("atomic cancellation target binding is inconsistent")
        target_state = target_record.state.value
        if cancel_record.state.value == "CANCELLED":
            if target_state != "CANCELLED":
                raise FakeDispatchJournalError("cancelled action lacks a terminal target")
            target_postcondition = self._risk_types.CancelTargetPostcondition.TARGET_TERMINAL
        else:
            if target_state not in {"ACKED", "PARTIALLY_FILLED"}:
                raise FakeDispatchJournalError("rejected cancel target is no longer open")
            target_postcondition = self._risk_types.CancelTargetPostcondition.TARGET_REMAINS_OPEN

        target_event_payload = _execution_event_payload(target_event)
        if (
            target_event_payload["intent_id"] != target_intent.intent_id
            or target_event_payload["scope_key"] != self._execution_scope.key
            or target_event_payload["state"] != target_state
            or target_event_payload["created_at_ns"] != target_record.updated_at_ns
            or target_event_payload["created_at_ns"] > event_payload["created_at_ns"]
            or payload_sha256(target_event_payload) != commit.target_event_sha256
        ):
            raise FakeDispatchJournalError("atomic cancellation target event digest is inconsistent")
        if cancel_record.state.value == "CANCELLED" and (
            target_event_payload["event_type"] != "cancelled_by_cancel_intent"
            or target_event_payload["payload"].get("cancel_id") != cancel_id
            or target_event_payload["payload"].get("provider_order_id")
            != cancel_intent.provider_order_id
            or target_event_payload["payload"].get("source") != source
        ):
            raise FakeDispatchJournalError("terminal target event belongs to another cancel")
        self._validate_cancel_target_event_projection(
            target_event_payload,
            target_record,
            cancel_record=cancel_record,
            cancel_id=cancel_id,
            source=source,
        )
        if cancel_record.state.value == "CANCELLED":
            expected_target_payload = {
                "cancel_id": cancel_id,
                "provider_order_id": cancel_intent.provider_order_id,
                "source": source,
                "filled_quantity": _decimal_text(target_record.filled_quantity),
                "average_price": (
                    None
                    if target_record.average_price is None
                    else _decimal_text(target_record.average_price)
                ),
                "cumulative_commission": (
                    None
                    if target_record.cumulative_commission is None
                    else _decimal_text(target_record.cumulative_commission)
                ),
            }
            if target_event_payload["payload"] != expected_target_payload:
                raise FakeDispatchJournalError("cancelled target payload is not exact")
        else:
            target_event_type = target_event_payload["event_type"]
            target_source = (
                "provider" if target_event_type == "provider_observation" else "reconcile"
            )
            expected_target_payload = {
                "provider_order_id": target_record.provider_order_id,
                "filled_quantity": _decimal_text(target_record.filled_quantity),
                "average_price": (
                    None
                    if target_record.average_price is None
                    else _decimal_text(target_record.average_price)
                ),
                "cumulative_commission": (
                    None
                    if target_record.cumulative_commission is None
                    else _decimal_text(target_record.cumulative_commission)
                ),
                "reason_code": target_event_payload["payload"].get("reason_code"),
                "source": target_source,
            }
            if (
                target_event_type not in {"provider_observation", "reconciled_observation"}
                or target_event_payload["payload"] != expected_target_payload
            ):
                raise FakeDispatchJournalError("rejected cancel target payload is not exact")
        self._execution_store.assert_writer_lease(self._execution_scope, lease)
        return {
            "cancel_id": cancel_id,
            "cancel_intent": cancel_intent,
            "cancel_intent_fingerprint": cancel_intent.fingerprint,
            "cancel_record": cancel_record,
            "cancel_event": cancel_event,
            "cancel_event_payload": event_payload,
            "cancel_event_sha256": commit.cancel_event_sha256,
            "cancel_source": source,
            "source_evidence_sha256": source_evidence_sha256,
            "target_intent": target_intent,
            "target_record": target_record,
            "target_postcondition": target_postcondition,
            "target_record_sha256": commit.target_record_sha256,
            "target_event": target_event,
            "target_event_payload": target_event_payload,
            "target_event_sha256": commit.target_event_sha256,
        }

    @staticmethod
    def _validate_cancel_target_event_projection(
        event: dict[str, Any],
        record: Any,
        *,
        cancel_record: Any,
        cancel_id: str,
        source: str,
    ) -> None:
        """Require the latest immutable event to describe the current target row."""

        payload = event["payload"]
        expected_values = {
            "provider_order_id": record.provider_order_id,
            "filled_quantity": _decimal_text(record.filled_quantity),
            "average_price": (
                None if record.average_price is None else _decimal_text(record.average_price)
            ),
            "cumulative_commission": (
                None
                if record.cumulative_commission is None
                else _decimal_text(record.cumulative_commission)
            ),
        }
        event_type = event["event_type"]
        if event_type in {"provider_observation", "reconciled_observation"}:
            expected_source = (
                "provider" if event_type == "provider_observation" else "reconcile"
            )
            if payload.get("source") != expected_source:
                raise FakeDispatchJournalError("target observation source is inconsistent")
        elif event_type == "provider_commission_evidence":
            if payload.get("source") not in {"provider", "reconcile"}:
                raise FakeDispatchJournalError("target commission source is inconsistent")
        elif event_type == "cancelled_by_cancel_intent":
            if (
                cancel_record.state.value != "CANCELLED"
                or payload.get("cancel_id") != cancel_id
                or payload.get("source") != source
            ):
                raise FakeDispatchJournalError("target cancel event identity is inconsistent")
        else:
            raise FakeDispatchJournalError("target event type is not a current provider fact")
        if any(payload.get(name) != value for name, value in expected_values.items()):
            raise FakeDispatchJournalError("target event differs from current target projection")

    def _make_cancel_resolution_proof(
        self, evidence: dict[str, Any], claim: Any, lease: Any, writer_fence_sha256: str
    ) -> Any:
        record = evidence["cancel_record"]
        cancel_event = evidence["cancel_event_payload"]
        target_record = evidence["target_record"]
        target_event = evidence["target_event_payload"]
        terminal_state = self._risk_types.CancelDispatchTerminalState(record.state.value)
        cancel_source = self._risk_types.CancelDispatchSource(evidence["cancel_source"])
        return self._risk_types.CancelDispatchResolutionProof(
            scope=self._risk_scope,
            permit_id=claim.permit_id,
            intent_id=claim.intent_id,
            intent_hash=claim.intent_hash,
            cause_id=claim.cause_id,
            claim_digest=claim.claim_digest,
            evidence_class=self._risk_types.DispatchEvidenceClass.SIMULATION_JOURNAL,
            dispatch_attempt_count=record.dispatch_attempts,
            execution_scope_key=self._execution_scope.key,
            cancel_id=evidence["cancel_id"],
            target_intent_id=record.target_intent_id,
            provider_order_id=record.provider_order_id,
            cancel_intent_fingerprint=evidence["cancel_intent_fingerprint"],
            terminal_state=terminal_state,
            cancel_event_id=cancel_event["event_id"],
            cancel_event_sequence=cancel_event["sequence"],
            cancel_event_sha256=evidence["cancel_event_sha256"],
            cancel_source=cancel_source,
            source_evidence_sha256=evidence["source_evidence_sha256"],
            target_postcondition=evidence["target_postcondition"],
            target_state=target_record.state.value,
            target_filled_quantity=_decimal_text(target_record.filled_quantity),
            target_updated_at_ns=target_record.updated_at_ns,
            target_record_sha256=evidence["target_record_sha256"],
            target_event_id=target_event["event_id"],
            target_event_sequence=target_event["sequence"],
            target_event_type=target_event["event_type"],
            target_event_sha256=evidence["target_event_sha256"],
            writer_owner_id=lease.owner_id,
            writer_fencing_token=lease.fencing_token,
            writer_fence_sha256=writer_fence_sha256,
        )

    def _exposure_facts(
        self, intent: Any, provider_order_id: object, request_sha256: str
    ) -> dict[str, str] | None:
        if not isinstance(provider_order_id, str) or not provider_order_id.strip():
            return None
        if getattr(intent, "order_type", None).value != "LIMIT" or intent.price is None:
            return None
        metadata_digest = intent.tags.get("instrument_metadata_digest")
        if not _valid_sha256(metadata_digest):
            return None
        quantity = _decimal_text(intent.quantity)
        limit_price = _decimal_text(intent.price)
        worst_case_notional = _decimal_text(Decimal(quantity) * Decimal(limit_price))
        base = {
            "accepted_request_sha256": request_sha256,
            "execution_scope_key": intent.scope.key,
            "instrument": intent.instrument,
            "limit_price": limit_price,
            "metadata_digest": metadata_digest,
            "position_effect": intent.position_effect.value,
            "provider_order_id": provider_order_id,
            "quantity": quantity,
            "risk_scope_key": self._risk_scope.key,
            "side": intent.side.value,
            "worst_case_notional": worst_case_notional,
        }
        reservation_sha256 = _sha256({"schema": "fake-order-exposure-v1", **base})
        reservation_id = "fake-exposure." + _sha256(base)[:32]
        return {
            **base,
            "reservation_id": reservation_id,
            "reservation_sha256": reservation_sha256,
        }

    def _risk_intent_hash(self, intent: Any) -> str:
        """Recreate the exact risk mapping used by managed composition.

        The risk claim hashes a RiskIntent, not the SDK OrderIntent directly.
        Its payload fingerprint links both layers; reproducing the sealed
        mapping here prevents a proof from substituting an unrelated claim.
        """

        if self._risk_intent_mapper is not None:
            try:
                mapped = self._risk_intent_mapper(intent)
            except Exception as error:
                raise FakeDispatchJournalError(
                    "sealed risk mapper could not map the SDK intent"
                ) from error
            if (
                getattr(mapped, "intent_id", None) != intent.intent_id
                or getattr(mapped, "scope", None) != self._risk_scope
            ):
                raise FakeDispatchJournalError("sealed risk mapper returned a mismatched intent")
            fingerprint = getattr(mapped, "fingerprint", None)
            if not _valid_sha256(fingerprint):
                raise FakeDispatchJournalError("sealed risk mapper returned an invalid fingerprint")
            return fingerprint

        if intent.position_effect.value == "OPEN":
            if intent.price is None:
                raise FakeDispatchJournalError("opening risk intent has no executable price")
            action = self._risk_types.IntentAction.INCREASE
            notional = intent.quantity * intent.price
        else:
            action = self._risk_types.IntentAction.REDUCE
            notional = Decimal("0")
        return self._risk_types.RiskIntent(
            intent_id=intent.intent_id,
            scope=self._risk_scope,
            action=action,
            notional=notional,
            payload_fingerprint=intent.fingerprint,
        ).fingerprint

    def _verify_exposure_for_row(
        self, connection: sqlite3.Connection, row: sqlite3.Row, intent: Any, record: Any
    ) -> sqlite3.Row | None:
        if row["provider_state"] != "ACKED" or not row["provider_order_id"]:
            if row["exposure_reservation_id"] is not None:
                raise FakeDispatchJournalError("non-ACK row unexpectedly has exposure")
            return None
        exposure = connection.execute(
            """
            SELECT * FROM fake_order_exposures
            WHERE risk_scope_key = ? AND execution_scope_key = ?
              AND intent_id = ? AND provider_order_id = ?
            """,
            (
                self._risk_scope.key,
                intent.scope.key,
                intent.intent_id,
                row["provider_order_id"],
            ),
        ).fetchone()
        if exposure is None:
            raise FakeDispatchJournalError("stable ACK lacks durable exposure reservation")
        expected = self._exposure_facts(intent, row["provider_order_id"], row["request_sha256"])
        if (
            expected is None
            or exposure["request_sha256"] != expected["accepted_request_sha256"]
            or any(
                exposure[key] != expected[key]
                for key in (
                    "reservation_id",
                    "reservation_sha256",
                    "instrument",
                    "metadata_digest",
                    "side",
                    "position_effect",
                    "quantity",
                    "limit_price",
                    "worst_case_notional",
                )
            )
        ):
            raise FakeDispatchJournalError("durable exposure reservation mismatch")
        if (
            exposure["state"] != "OPEN"
            or str(exposure["filled_quantity"]) != "0"
            or int(exposure["trade_count"]) != 0
            or exposure["intent_payload_sha256"] != record.payload_sha256
        ):
            raise FakeDispatchJournalError("fake exposure is not an outstanding zero-fill order")
        if (
            row["exposure_reservation_id"] != exposure["reservation_id"]
            or row["exposure_reservation_sha256"] != exposure["reservation_sha256"]
        ):
            raise FakeDispatchJournalError("dispatch row does not bind its exposure row")
        return exposure

    def _verify_journal_row(self, row: sqlite3.Row, intent: Any, record: Any) -> None:
        request_sha256 = _sha256(intent.to_payload())
        if row["request_sha256"] != request_sha256:
            raise FakeDispatchJournalError("fake request digest differs from immutable SDK intent")
        try:
            response = json.loads(row["provider_response_json"])
        except (TypeError, ValueError) as error:
            raise FakeDispatchJournalError("fake provider response record is invalid") from error
        response_identity = {
            "filled_quantity": row["provider_filled_quantity"],
            "intent_id": intent.intent_id,
            "provider_order_id": row["provider_order_id"],
            "request_sha256": request_sha256,
            "scope_key": intent.scope.key,
            "state": row["provider_state"],
        }
        if (
            not isinstance(response, dict)
            or any(response.get(key) != value for key, value in response_identity.items())
            or _sha256(response) != row["provider_response_sha256"]
        ):
            raise FakeDispatchJournalError("fake provider response digest mismatch")
        record_average_price = (
            None if record.average_price is None else _decimal_text(record.average_price)
        )
        response_average_price = response.get("average_price")
        if (
            record.state.value != row["provider_state"]
            or record.provider_order_id != row["provider_order_id"]
            or _decimal_text(record.filled_quantity) != str(row["provider_filled_quantity"])
            or record_average_price != response_average_price
        ):
            raise FakeDispatchJournalError(
                "SDK execution projection differs from fake provider observation"
            )
        expected_reconciliation_sha256 = _sha256(
            {
                "exposure_reservation_sha256": row["exposure_reservation_sha256"],
                "provider_response_sha256": row["provider_response_sha256"],
                "schema": "fake-dispatch-evidence-v1",
            }
        )
        if row["reconciliation_evidence_sha256"] != expected_reconciliation_sha256:
            raise FakeDispatchJournalError("fake reconciliation evidence digest mismatch")
        if row["provider_state"] == "ACKED" and (
            str(row["provider_filled_quantity"]) != "0" or response_average_price is not None
        ):
            raise FakeDispatchJournalError("fake ACK response carries fill evidence")
        if (
            row["provider_state"] == "REJECTED"
            and str(row["provider_filled_quantity"]) == "0"
            and response_average_price is not None
        ):
            raise FakeDispatchJournalError("fake rejection carries average-price evidence")
        if (
            row["intent_payload_sha256"] != intent.fingerprint
            or row["intent_payload_sha256"] != record.payload_sha256
            or row["record_sha256"] is None
            or self._row_execution_fact(row) != self._execution_fact(intent, record)
        ):
            raise FakeDispatchJournalError("execution result is not the current fake journal row")
        fact = self._row_execution_fact(row)
        assert fact is not None
        if _sha256({**fact, "revision": int(row["revision"])}) != row["record_sha256"]:
            raise FakeDispatchJournalError("fake execution journal digest mismatch")
        if int(record.dispatch_attempts) != 1:
            raise FakeDispatchJournalError("fake journal requires exactly one dispatch attempt")

    @staticmethod
    def _execution_fact(intent: Any, record: Any) -> dict[str, Any]:
        return {
            "dispatch_attempts": int(record.dispatch_attempts),
            "filled_quantity": _decimal_text(record.filled_quantity),
            "intent_id": intent.intent_id,
            "payload_sha256": record.payload_sha256,
            "permit_reference": record.permit_reference,
            "provider_order_id": record.provider_order_id,
            "review_required": int(bool(record.review_required)),
            "scope_key": intent.scope.key,
            "state": record.state.value,
            "updated_at_ns": int(record.updated_at_ns),
        }

    @staticmethod
    def _row_execution_fact(row: sqlite3.Row) -> dict[str, Any] | None:
        if row["record_state"] is None:
            return None
        return {
            "dispatch_attempts": int(row["record_dispatch_attempts"]),
            "filled_quantity": str(row["record_filled_quantity"]),
            "intent_id": row["intent_id"],
            "payload_sha256": row["intent_payload_sha256"],
            "permit_reference": row["record_permit_reference"],
            "provider_order_id": row["record_provider_order_id"],
            "review_required": int(row["record_review_required"]),
            "scope_key": row["scope_key"],
            "state": row["record_state"],
            "updated_at_ns": int(row["record_updated_at_ns"]),
        }

    def _require_current_record(self, intent: Any, record: Any) -> None:
        current_intent = self._execution_store.get_intent(
            intent.intent_id, scope=self._execution_scope
        )
        current_record = self._execution_store.get(intent.intent_id, scope=self._execution_scope)
        if (
            current_intent is None
            or current_record is None
            or current_intent.fingerprint != intent.fingerprint
            or current_record != record
        ):
            raise FakeDispatchJournalError("SDK execution row is stale")

    def _require_intent_scope(self, intent: Any) -> None:
        if getattr(intent, "scope", None) != self._execution_scope:
            raise FakeDispatchJournalError("intent is outside the offline fake scope")

    @staticmethod
    def _state_value(observation: Any) -> str:
        state = getattr(observation, "state", None)
        value = getattr(state, "value", None)
        if not isinstance(value, str):
            raise FakeDispatchJournalError("provider observation state is invalid")
        return value

    def _current_writer_lease(self) -> Any:
        if self._facade is None:
            raise FakeDispatchJournalError("execution writer authority is not bound")
        lease = self._facade.acquire_writer_lease()
        self._execution_store.assert_writer_lease(self._execution_scope, lease)
        return lease

    def _require_dispatching_before_provider_call(self, intent: Any) -> None:
        """Bind provider evidence to the sole current SDK dispatch attempt."""

        self._current_writer_lease()
        current_intent = self._execution_store.get_intent(
            intent.intent_id, scope=self._execution_scope
        )
        record = self._execution_store.get(intent.intent_id, scope=self._execution_scope)
        if (
            current_intent is None
            or record is None
            or current_intent.fingerprint != intent.fingerprint
            or record.payload_sha256 != intent.fingerprint
            or record.state.value != "DISPATCHING"
            or record.dispatch_attempts != 1
            or not record.permit_reference
            or record.review_required
        ):
            raise FakeDispatchJournalError(
                "fake provider result is outside the sole claimed SDK dispatch"
            )

    def _writer_fence_digest(self, lease: Any, generation: int) -> str:
        return _sha256(
            {
                "execution_scope_key": lease.scope_key,
                "fencing_token": int(lease.fencing_token),
                "generation": generation,
                "owner_id": lease.owner_id,
                "risk_scope_key": self._risk_scope.key,
                "schema": "fake-account-writer-fence-v1",
            }
        )

    def _next_fence_generation(self, connection: sqlite3.Connection, lease: Any) -> int:
        row = connection.execute(
            "SELECT generation FROM fake_writer_fences WHERE risk_scope_key = ?",
            (self._risk_scope.key,),
        ).fetchone()
        generation = 1 if row is None else int(row["generation"]) + 1
        return generation

    @staticmethod
    def _journal_row(connection: sqlite3.Connection, scope_key: str, intent_id: str) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM fake_dispatch_journal WHERE scope_key = ? AND intent_id = ?",
            (scope_key, intent_id),
        ).fetchone()
        if row is None:
            raise FakeDispatchJournalError("fake provider journal row is unavailable")
        return row

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self._database_path), timeout=10.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=10000")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def _initialize(self) -> None:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if version not in {0, 1, 2, _SCHEMA_VERSION}:
                raise FakeDispatchJournalError("unsupported fake journal schema")
            if version in {0, 1}:
                columns = {
                    str(row["name"])
                    for row in connection.execute(
                        "PRAGMA table_info(fake_dispatch_journal)"
                    ).fetchall()
                }
                if columns and "provider_response_json" not in columns:
                    # Legacy rows cannot be upgraded into authenticated
                    # response evidence.  Keep the column nullable so the
                    # journal can reopen, but proof verification rejects any
                    # such row until a new, fully observed fake dispatch is
                    # written under this schema.
                    connection.execute(
                        "ALTER TABLE fake_dispatch_journal ADD COLUMN provider_response_json TEXT"
                    )
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS fake_dispatch_journal (
                    scope_key TEXT NOT NULL,
                    intent_id TEXT NOT NULL,
                    intent_payload_sha256 TEXT NOT NULL,
                    provider_state TEXT NOT NULL,
                    provider_order_id TEXT,
                    request_sha256 TEXT NOT NULL,
                    provider_filled_quantity TEXT NOT NULL,
                    provider_trade_count INTEGER NOT NULL,
                    provider_response_sha256 TEXT NOT NULL,
                    provider_response_json TEXT NOT NULL,
                    exposure_reservation_id TEXT,
                    exposure_reservation_sha256 TEXT,
                    reconciliation_evidence_sha256 TEXT NOT NULL,
                    record_state TEXT,
                    record_provider_order_id TEXT,
                    record_filled_quantity TEXT,
                    record_permit_reference TEXT,
                    record_dispatch_attempts INTEGER,
                    record_review_required INTEGER,
                    record_updated_at_ns INTEGER,
                    revision INTEGER NOT NULL,
                    record_sha256 TEXT,
                    created_at_ns INTEGER NOT NULL,
                    updated_at_ns INTEGER NOT NULL,
                    PRIMARY KEY(scope_key, intent_id)
                );
                CREATE TABLE IF NOT EXISTS fake_order_exposures (
                    risk_scope_key TEXT NOT NULL,
                    execution_scope_key TEXT NOT NULL,
                    intent_id TEXT NOT NULL,
                    provider_order_id TEXT NOT NULL,
                    intent_payload_sha256 TEXT NOT NULL,
                    request_sha256 TEXT NOT NULL,
                    reservation_id TEXT NOT NULL UNIQUE,
                    reservation_sha256 TEXT NOT NULL,
                    instrument TEXT NOT NULL,
                    metadata_digest TEXT NOT NULL,
                    side TEXT NOT NULL,
                    position_effect TEXT NOT NULL,
                    quantity TEXT NOT NULL,
                    limit_price TEXT NOT NULL,
                    worst_case_notional TEXT NOT NULL,
                    state TEXT NOT NULL,
                    filled_quantity TEXT NOT NULL,
                    trade_count INTEGER NOT NULL,
                    created_at_ns INTEGER NOT NULL,
                    PRIMARY KEY(risk_scope_key, provider_order_id),
                    UNIQUE(execution_scope_key, intent_id)
                );
                CREATE TABLE IF NOT EXISTS fake_writer_fences (
                    risk_scope_key TEXT PRIMARY KEY,
                    generation INTEGER NOT NULL,
                    writer_fence_sha256 TEXT NOT NULL,
                    execution_scope_key TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    fencing_token INTEGER NOT NULL,
                    updated_at_ns INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS fake_cancel_resolution_proofs (
                    risk_scope_key TEXT NOT NULL,
                    execution_scope_key TEXT NOT NULL,
                    cancel_id TEXT NOT NULL,
                    writer_fence_sha256 TEXT NOT NULL,
                    proof_sha256 TEXT NOT NULL,
                    proof_json TEXT NOT NULL,
                    created_at_ns INTEGER NOT NULL,
                    PRIMARY KEY(risk_scope_key, cancel_id, writer_fence_sha256),
                    UNIQUE(risk_scope_key, proof_sha256)
                );
                CREATE TRIGGER IF NOT EXISTS fake_cancel_resolution_proofs_immutable_update
                BEFORE UPDATE ON fake_cancel_resolution_proofs
                BEGIN
                    SELECT RAISE(ABORT, 'fake cancel resolution proof is immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS fake_cancel_resolution_proofs_immutable_delete
                BEFORE DELETE ON fake_cancel_resolution_proofs
                BEGIN
                    SELECT RAISE(ABORT, 'fake cancel resolution proof is immutable');
                END;
                """
            )
            connection.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
