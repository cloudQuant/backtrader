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
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

_SCHEMA_VERSION = 2
_HEX = frozenset("0123456789abcdef")


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
            if version not in {0, 1, _SCHEMA_VERSION}:
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
                """
            )
            connection.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
