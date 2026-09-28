from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from dataclasses import dataclass, replace
from decimal import Decimal
from enum import Enum
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace

import pytest

_EXECUTION_SRC = Path(
    r"D:\temp\iteration41_v20_r3_cancel_terminal_candidate_20260927\src"
)
sys.path.insert(0, str(_EXECUTION_SRC))
from bt_api_execution import contracts as _execution_contracts  # noqa: E402
from bt_api_execution import store as _execution_store_types  # noqa: E402

_ROOT = Path(__file__).parents[1]
_SPEC = spec_from_file_location(
    "cancel_proof_authority_under_test", _ROOT / "src" / "fake_dispatch_authority.py"
)
assert _SPEC is not None and _SPEC.loader is not None
authority_module = module_from_spec(_SPEC)
sys.modules[_SPEC.name] = authority_module
_SPEC.loader.exec_module(authority_module)
FakeDispatchJournalError = authority_module.FakeDispatchJournalError
ManagedFakeProviderJournalAuthority = authority_module.ManagedFakeProviderJournalAuthority

_V2_SPEC = spec_from_file_location(
    "cancel_proof_authority_v2_fixture", _ROOT / "tests" / "fixtures" / "fake_dispatch_authority_v2.py"
)
assert _V2_SPEC is not None and _V2_SPEC.loader is not None
v2_authority_module = module_from_spec(_V2_SPEC)
sys.modules[_V2_SPEC.name] = v2_authority_module
_V2_SPEC.loader.exec_module(v2_authority_module)


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


_State = _execution_contracts.ExecutionState


class _IntentAction(str, Enum):
    CANCEL = "cancel"


class _EvidenceClass(str, Enum):
    SIMULATION_JOURNAL = "SIMULATION_JOURNAL"


class _CancelTerminal(str, Enum):
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class _CancelSource(str, Enum):
    PROVIDER = "provider"
    RECONCILE = "reconcile"


class _TargetPostcondition(str, Enum):
    TARGET_TERMINAL = "TARGET_TERMINAL"
    TARGET_REMAINS_OPEN = "TARGET_REMAINS_OPEN"


@dataclass(frozen=True)
class _Scope:
    key: str
    provider: str = "fake"
    environment: str = "offline"


@dataclass(frozen=True)
class _RiskIntent:
    intent_id: str
    scope: _Scope
    action: _IntentAction
    notional: Decimal
    payload_fingerprint: str

    @property
    def fingerprint(self) -> str:
        return _sha(
            {
                "action": self.action.value,
                "notional": format(self.notional.normalize(), "f"),
                "payload_fingerprint": self.payload_fingerprint,
                "scope": self.scope.key,
            }
        )


@dataclass(frozen=True)
class _Claim:
    scope: _Scope
    permit_id: str
    intent_id: str
    intent_hash: str
    cause_id: str
    claim_digest: str


@dataclass(frozen=True)
class _CancelProof:
    scope: _Scope
    permit_id: str
    intent_id: str
    intent_hash: str
    cause_id: str
    claim_digest: str
    evidence_class: _EvidenceClass
    dispatch_attempt_count: int
    execution_scope_key: str
    cancel_id: str
    target_intent_id: str
    provider_order_id: str
    cancel_intent_fingerprint: str
    terminal_state: _CancelTerminal
    cancel_event_id: str
    cancel_event_sequence: int
    cancel_event_sha256: str
    cancel_source: _CancelSource
    source_evidence_sha256: str
    target_postcondition: _TargetPostcondition
    target_state: str
    target_filled_quantity: str
    target_updated_at_ns: int
    target_record_sha256: str
    target_event_id: str
    target_event_sequence: int
    target_event_type: str
    target_event_sha256: str
    writer_owner_id: str
    writer_fencing_token: int
    writer_fence_sha256: str

    @property
    def fingerprint(self) -> str:
        payload = authority_module._cancel_resolution_proof_payload(self)
        return _sha(payload)


@dataclass(frozen=True)
class _Verified:
    scope: _Scope
    permit_id: str
    intent_id: str
    intent_hash: str
    claim_digest: str
    proof_sha256: str
    cancel_event_id: str
    cancel_event_sequence: int
    cancel_event_sha256: str
    source_evidence_sha256: str
    target_postcondition: _TargetPostcondition
    target_record_sha256: str
    target_event_id: str
    target_event_sequence: int
    target_event_sha256: str
    writer_owner_id: str
    writer_fencing_token: int
    writer_fence_sha256: str


class _RiskTypes:
    RiskIntent = _RiskIntent
    IntentAction = _IntentAction
    DispatchClaimBinding = _Claim
    CancelDispatchResolutionProof = _CancelProof
    VerifiedCancelDispatchResolution = _Verified
    DispatchEvidenceClass = _EvidenceClass
    CancelDispatchTerminalState = _CancelTerminal
    CancelDispatchSource = _CancelSource
    CancelTargetPostcondition = _TargetPostcondition


_Lease = _execution_store_types.WriterLease


@dataclass(frozen=True)
class _CancelIntent:
    cancel_id: str
    scope: _Scope
    target_intent_id: str
    provider_order_id: str

    def to_payload(self) -> dict[str, object]:
        return {
            "cancel_id": self.cancel_id,
            "scope": {"key": self.scope.key},
            "target_intent_id": self.target_intent_id,
            "provider_order_id": self.provider_order_id,
        }

    @property
    def fingerprint(self) -> str:
        return _sha(self.to_payload())


@dataclass(frozen=True)
class _CancelRecord:
    cancel_id: str
    scope_key: str
    target_intent_id: str
    provider_order_id: str
    payload_sha256: str
    state: _State
    permit_reference: str | None
    dispatch_attempts: int
    unknown_reason: str | None
    review_required: bool
    created_at_ns: int
    updated_at_ns: int


@dataclass(frozen=True)
class _OrderIntent:
    intent_id: str
    scope: _Scope
    fingerprint: str


@dataclass(frozen=True)
class _OrderRecord:
    intent_id: str
    scope_key: str
    payload_sha256: str
    state: _State
    provider_order_id: str
    filled_quantity: Decimal
    average_price: Decimal | None
    cumulative_commission: Decimal | None
    permit_reference: str | None
    dispatch_attempts: int
    unknown_reason: str | None
    review_required: bool
    created_at_ns: int
    updated_at_ns: int


@dataclass(frozen=True)
class _CancelEvent:
    sequence: int
    event_id: str
    cancel_id: str
    target_intent_id: str
    scope_key: str
    event_type: str
    state: _State
    payload: dict[str, object]
    created_at_ns: int


@dataclass(frozen=True)
class _ExecutionEvent:
    sequence: int
    event_id: str
    intent_id: str
    scope_key: str
    event_type: str
    state: _State
    payload: dict[str, object]
    created_at_ns: int
    journal_incarnation_id: str = "incarnation"


class _ExecutionStore:
    def __init__(self, scope: _Scope, lease: _Lease, state: str, source: str = "provider"):
        self.scope = scope
        self.lease = lease
        self.cancel_id = "cancel-17"
        self.target_id = "managed-order-17"
        self.provider_order_id = "provider-order-17"
        self.cancel_intent = _execution_contracts.CancelIntent(
            self.cancel_id,
            scope,
            self.target_id,
            self.provider_order_id,
            metadata_version="meta-v1",
        )
        self.cancel_record = _CancelRecord(
            self.cancel_id,
            scope.key,
            self.target_id,
            self.provider_order_id,
            self.cancel_intent.fingerprint,
            _State(state),
            "permit-cancel-17",
            1,
            None,
            False,
            10,
            50,
        )
        target_state = _State.CANCELLED if state == "CANCELLED" else _State.ACKED
        self.target_intent = _execution_contracts.OrderIntent.limit(
            intent_id=self.target_id,
            scope=scope,
            signal_id="signal-proof",
            instrument="BTC-USDT",
            side=_execution_contracts.Side.BUY,
            quantity=Decimal("2"),
            price=Decimal("5.5"),
            metadata_version="meta-v1",
        )
        self.target_record = _OrderRecord(
            self.target_id,
            scope.key,
            self.target_intent.fingerprint,
            target_state,
            self.provider_order_id,
            Decimal("1.25") if state == "REJECTED" else Decimal("0.25"),
            Decimal("5.5"),
            Decimal("-0.01"),
            "order-permit",
            1,
            None,
            False,
            1,
            50 if state == "CANCELLED" else 40,
        )
        self.source = source
        self.cancel_events = [
            _CancelEvent(
                4,
                "cancel-event-4",
                self.cancel_id,
                self.target_id,
                scope.key,
                "cancel_provider_observation"
                if source == "provider"
                else "cancel_reconciled_observation",
                _State(state),
                {"provider_order_id": self.provider_order_id, "reason_code": None, "source": source},
                50,
            )
        ]
        if state == "CANCELLED":
            target_event_type = "cancelled_by_cancel_intent"
            target_payload = {
                "cancel_id": self.cancel_id,
                "provider_order_id": self.provider_order_id,
                "source": source,
                "filled_quantity": "0.25",
                "average_price": "5.5",
                "cumulative_commission": "-0.01",
            }
        else:
            target_event_type = "provider_observation"
            target_payload = {
                "provider_order_id": self.provider_order_id,
                "filled_quantity": "1.25",
                "average_price": "5.5",
                "cumulative_commission": "-0.01",
                "reason_code": None,
                "source": source,
            }
        self.target_events = [
            _ExecutionEvent(
                7,
                "order-event-7",
                self.target_id,
                scope.key,
                target_event_type,
                target_state,
                target_payload,
                50 if state == "CANCELLED" else 40,
            )
        ]
        self.page_read_calls = 0

    def assert_writer_lease(self, scope: _Scope, lease: _Lease) -> None:
        if scope != self.scope or lease != self.lease:
            raise RuntimeError("writer lease mismatch")

    def get_cancel(self, cancel_id: str, *, scope: _Scope):
        return self.cancel_record if cancel_id == self.cancel_id and scope == self.scope else None

    def get_cancel_intent(self, cancel_id: str, *, scope: _Scope):
        return self.cancel_intent if cancel_id == self.cancel_id and scope == self.scope else None

    def get(self, intent_id: str, *, scope: _Scope):
        return self.target_record if intent_id == self.target_id and scope == self.scope else None

    def get_intent(self, intent_id: str, *, scope: _Scope):
        return self.target_intent if intent_id == self.target_id and scope == self.scope else None

    def read_terminal_cancel_commit(self, scope, cancel_id, *, writer_lease):
        if scope != self.scope or cancel_id != self.cancel_id:
            raise RuntimeError("terminal cancellation is unavailable")
        if writer_lease != self.lease:
            raise RuntimeError("writer lease mismatch")
        cancel_record = _execution_store_types.CancelRecord(
            self.cancel_record.cancel_id,
            self.cancel_record.scope_key,
            self.cancel_record.target_intent_id,
            self.cancel_record.provider_order_id,
            self.cancel_record.payload_sha256,
            self.cancel_record.state,
            self.cancel_record.permit_reference,
            self.cancel_record.dispatch_attempts,
            self.cancel_record.unknown_reason,
            self.cancel_record.review_required,
            self.cancel_record.created_at_ns,
            self.cancel_record.updated_at_ns,
        )
        target_record = _execution_store_types.ExecutionRecord(
            self.target_record.intent_id,
            self.target_record.scope_key,
            self.target_record.payload_sha256,
            self.target_record.state,
            self.target_record.provider_order_id,
            self.target_record.filled_quantity,
            self.target_record.average_price,
            self.target_record.permit_reference,
            self.target_record.dispatch_attempts,
            self.target_record.unknown_reason,
            self.target_record.review_required,
            self.target_record.created_at_ns,
            self.target_record.updated_at_ns,
            self.target_record.cumulative_commission,
        )
        source = self.cancel_events[-1].payload.get("source") if self.cancel_events else None
        cancel_source = source if source in {"provider", "reconcile"} else "provider"
        cancel_event_type = (
            "cancel_provider_observation"
            if cancel_source == "provider"
            else "cancel_reconciled_observation"
        )
        cancel_event = _execution_contracts.CancelEvent(
            self.cancel_events[-1].sequence,
            self.cancel_events[-1].event_id,
            self.cancel_events[-1].cancel_id,
            self.cancel_events[-1].target_intent_id,
            self.cancel_events[-1].scope_key,
            cancel_event_type,
            self.cancel_events[-1].state,
            self.cancel_events[-1].payload,
            self.cancel_events[-1].created_at_ns,
        )
        target = self.target_events[-1]
        target_event = _execution_contracts.ExecutionEvent(
            target.sequence,
            target.event_id,
            target.intent_id,
            target.scope_key,
            target.event_type,
            target.state,
            target.payload,
            target.created_at_ns,
            "a" * 32,
        )
        cancel_event_doc = {
            "sequence": cancel_event.sequence,
            "event_id": cancel_event.event_id,
            "cancel_id": cancel_event.cancel_id,
            "target_intent_id": cancel_event.target_intent_id,
            "scope_key": cancel_event.scope_key,
            "event_type": cancel_event.event_type,
            "state": cancel_event.state.value,
            "payload": dict(cancel_event.payload),
            "created_at_ns": cancel_event.created_at_ns,
        }
        target_event_doc = {
            "sequence": target_event.sequence,
            "event_id": target_event.event_id,
            "intent_id": target_event.intent_id,
            "scope_key": target_event.scope_key,
            "event_type": target_event.event_type,
            "state": target_event.state.value,
            "payload": dict(target_event.payload),
            "created_at_ns": target_event.created_at_ns,
            "journal_incarnation_id": target_event.journal_incarnation_id,
        }
        source_digest = _execution_contracts.payload_sha256(
            {
                "source": cancel_source,
                "provider_order_id": cancel_record.provider_order_id,
                "reason_code": cancel_event.payload.get("reason_code"),
            }
        )
        return _execution_store_types.CancelObservationCommitV1(
            cancel_intent=self.cancel_intent,
            cancel_record=cancel_record,
            cancel_event=cancel_event,
            cancel_event_sha256=_execution_contracts.payload_sha256(cancel_event_doc),
            source_evidence_sha256=source_digest,
            target_record=target_record,
            target_record_sha256=_execution_contracts.payload_sha256(target_record),
            target_event=target_event,
            target_event_sha256=_execution_contracts.payload_sha256(target_event_doc),
            writer_lease=writer_lease,
        )

    @staticmethod
    def _page(events, *, after_sequence: int, limit: int):
        return tuple(event for event in events if event.sequence > after_sequence)[:limit]

    def read_cancel_outbox(self, *, after_sequence: int, limit: int, scope: _Scope):
        self.page_read_calls += 1
        if scope != self.scope:
            return ()
        return self._page(self.cancel_events, after_sequence=after_sequence, limit=limit)

    def read_outbox(self, *, after_sequence: int, limit: int, scope: _Scope):
        self.page_read_calls += 1
        if scope != self.scope:
            return ()
        return self._page(self.target_events, after_sequence=after_sequence, limit=limit)


class _Facade:
    def __init__(self, lease: _Lease):
        self.lease = lease

    def acquire_writer_lease(self):
        return self.lease


class _RiskGate:
    def __init__(
        self, scope: _Scope, cancel: _CancelIntent, execution_scope: _Scope | None = None
    ):
        self.scope = scope
        execution_scope = _EXECUTION_SCOPE if execution_scope is None else execution_scope
        self.intent_id = f"cancel-admission:{execution_scope.key}:{cancel.cancel_id}"
        risk_intent = _RiskIntent(
            self.intent_id,
            scope,
            _IntentAction.CANCEL,
            Decimal("0"),
            cancel.fingerprint,
        )
        self.claim = _Claim(
            scope,
            "permit-cancel-17",
            self.intent_id,
            risk_intent.fingerprint,
            "dispatch-inflight:" + self.intent_id,
            "c" * 64,
        )

    def dispatch_claim_binding(self, permit_id: str):
        return self.claim if permit_id == self.claim.permit_id else None


_EXECUTION_SCOPE = _execution_contracts.ExecutionScope(
    provider="fake", environment="offline", account_ref="acct-17", strategy_id="strategy-17"
)
_RISK_SCOPE = _Scope("risk-scope-17", provider="fake", environment="offline")


def _setup(tmp_path: Path, state: str):
    lease = _Lease(_EXECUTION_SCOPE.account_key, "fixture-writer", 3, 10**30)
    store = _ExecutionStore(_EXECUTION_SCOPE, lease, state)
    gate = _RiskGate(_RISK_SCOPE, store.cancel_intent)
    authority = ManagedFakeProviderJournalAuthority(
        database_path=tmp_path / "fake.sqlite3",
        execution_scope=_EXECUTION_SCOPE,
        risk_scope=_RISK_SCOPE,
        execution_store=store,
        facade=_Facade(lease),
        risk_types=_RiskTypes,
    )
    return authority, store, gate, lease


def test_reconcile_source_uses_same_atomic_cancel_commit_contract(tmp_path: Path) -> None:
    lease = _Lease(_EXECUTION_SCOPE.account_key, "fixture-writer", 3, 10**30)
    store = _ExecutionStore(_EXECUTION_SCOPE, lease, "CANCELLED", source="reconcile")
    gate = _RiskGate(_RISK_SCOPE, store.cancel_intent)
    authority = ManagedFakeProviderJournalAuthority(
        database_path=tmp_path / "fake.sqlite3",
        execution_scope=_EXECUTION_SCOPE,
        risk_scope=_RISK_SCOPE,
        execution_store=store,
        facade=_Facade(lease),
        risk_types=_RiskTypes,
    )
    proof = authority.create_cancel_dispatch_resolution_proof(store.cancel_id, gate)
    assert proof.cancel_source is _CancelSource.RECONCILE
    assert store.page_read_calls == 0


@pytest.mark.parametrize(
    ("state", "target_postcondition"),
    [("CANCELLED", _TargetPostcondition.TARGET_TERMINAL),
     ("REJECTED", _TargetPostcondition.TARGET_REMAINS_OPEN)],
)
def test_cancel_resolution_proof_uses_distinct_action_and_persisted_readback(
    tmp_path: Path, state: str, target_postcondition: _TargetPostcondition
) -> None:
    authority, store, gate, _lease = _setup(tmp_path, state)
    proof = authority.create_cancel_dispatch_resolution_proof(store.cancel_id, gate)

    assert type(proof) is _CancelProof
    assert proof.cancel_id == store.cancel_id
    assert proof.intent_id == gate.intent_id
    assert proof.cancel_intent_fingerprint == store.cancel_intent.fingerprint
    assert proof.dispatch_attempt_count == 1
    assert proof.terminal_state.value == state
    assert proof.target_postcondition is target_postcondition
    expected_filled = "0.25" if state == "CANCELLED" else "1.25"
    assert proof.target_filled_quantity == expected_filled
    assert proof.cancel_source is _CancelSource.PROVIDER
    assert store.page_read_calls == 0

    with authority.cancel_dispatch_resolution_guard(proof, claim=gate.claim) as verified:
        assert type(verified) is _Verified
        assert verified.proof_sha256 == proof.fingerprint
        assert verified.cancel_event_id == proof.cancel_event_id
        assert verified.target_event_id == proof.target_event_id

    with sqlite3.connect(tmp_path / "fake.sqlite3") as connection:
        row = connection.execute(
            "SELECT proof_sha256, proof_json FROM fake_cancel_resolution_proofs "
            "WHERE risk_scope_key = ? AND cancel_id = ?",
            (_RISK_SCOPE.key, store.cancel_id),
        ).fetchone()
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        assert connection.execute(
            "SELECT COUNT(*) FROM fake_cancel_resolution_proofs"
        ).fetchone()[0] == 1
        assert row[0] == proof.fingerprint
        assert json.loads(row[1])["cancel_event_sha256"] == proof.cancel_event_sha256
        assert version == 3

    with sqlite3.connect(tmp_path / "fake.sqlite3") as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE fake_cancel_resolution_proofs SET proof_sha256 = ?",
                ("d" * 64,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("DELETE FROM fake_cancel_resolution_proofs")


@pytest.mark.parametrize("state", ["ACKED", "UNKNOWN"])
def test_nonterminal_cancel_action_cannot_issue_resolution_proof(
    tmp_path: Path, state: str
) -> None:
    authority, store, gate, _lease = _setup(tmp_path, "REJECTED")
    store.cancel_record = replace(store.cancel_record, state=_State(state))
    with pytest.raises(FakeDispatchJournalError):
        authority.create_cancel_dispatch_resolution_proof(store.cancel_id, gate)


@pytest.mark.parametrize("attempts", [0, 2])
def test_cancel_proof_requires_exactly_one_dispatch_attempt(tmp_path: Path, attempts: int) -> None:
    authority, store, gate, _lease = _setup(tmp_path, "CANCELLED")
    store.cancel_record = replace(store.cancel_record, dispatch_attempts=attempts)
    with pytest.raises(FakeDispatchJournalError):
        authority.create_cancel_dispatch_resolution_proof(store.cancel_id, gate)


def test_acknowledged_cancel_is_not_a_terminal_cancel_proof(tmp_path: Path) -> None:
    authority, store, gate, _lease = _setup(tmp_path, "CANCELLED")
    event = store.cancel_events[-1]
    store.cancel_record = replace(store.cancel_record, state=_State.ACKED)
    store.cancel_events[-1] = replace(event, state=_State.ACKED)
    with pytest.raises(FakeDispatchJournalError):
        authority.create_cancel_dispatch_resolution_proof(store.cancel_id, gate)


def test_cancelled_action_must_have_matching_target_cancel_event(tmp_path: Path) -> None:
    authority, store, gate, _lease = _setup(tmp_path, "CANCELLED")
    target = store.target_events[-1]
    store.target_events[-1] = replace(target, payload={**target.payload, "cancel_id": "other"})
    with pytest.raises(FakeDispatchJournalError):
        authority.create_cancel_dispatch_resolution_proof(store.cancel_id, gate)


def test_rejected_cancel_cannot_claim_no_fill_or_terminal_target(tmp_path: Path) -> None:
    authority, store, gate, _lease = _setup(tmp_path, "REJECTED")
    store.target_record = replace(store.target_record, state=_State.CANCELLED)
    store.target_events[-1] = replace(store.target_events[-1], state=_State.CANCELLED)
    with pytest.raises(FakeDispatchJournalError):
        authority.create_cancel_dispatch_resolution_proof(store.cancel_id, gate)


def test_rejected_cancel_target_event_must_match_current_exposure(tmp_path: Path) -> None:
    authority, store, gate, _lease = _setup(tmp_path, "REJECTED")
    event = store.target_events[-1]
    store.target_events[-1] = replace(
        event, payload={**event.payload, "filled_quantity": "0"}
    )
    with pytest.raises(FakeDispatchJournalError):
        authority.create_cancel_dispatch_resolution_proof(store.cancel_id, gate)


def test_terminal_cancel_requires_provider_or_reconcile_source_and_event(tmp_path: Path) -> None:
    authority, store, gate, _lease = _setup(tmp_path, "CANCELLED")
    store.cancel_events[-1] = replace(
        store.cancel_events[-1], payload={**store.cancel_events[-1].payload, "source": "local"}
    )
    with pytest.raises(FakeDispatchJournalError):
        authority.create_cancel_dispatch_resolution_proof(store.cancel_id, gate)


def test_missing_terminal_cancel_outbox_event_fails_closed(tmp_path: Path) -> None:
    authority, store, gate, _lease = _setup(tmp_path, "CANCELLED")
    store.cancel_events.clear()
    with pytest.raises(FakeDispatchJournalError):
        authority.create_cancel_dispatch_resolution_proof(store.cancel_id, gate)


def test_cancel_resolution_rejects_cross_risk_scope_and_target_rebinding(
    tmp_path: Path,
) -> None:
    authority, store, _gate, _lease = _setup(tmp_path, "CANCELLED")
    foreign_gate = _RiskGate(
        _Scope("other-risk-account", provider="fake", environment="offline"),
        store.cancel_intent,
    )
    with pytest.raises(FakeDispatchJournalError):
        authority.create_cancel_dispatch_resolution_proof(store.cancel_id, foreign_gate)

    store.cancel_intent = replace(store.cancel_intent, target_intent_id="other-order")
    with pytest.raises(FakeDispatchJournalError):
        authority.create_cancel_dispatch_resolution_proof(store.cancel_id, foreign_gate)


def test_old_proof_is_stale_after_a_new_writer_fence_generation(tmp_path: Path) -> None:
    authority, store, gate, _lease = _setup(tmp_path, "REJECTED")
    first = authority.create_cancel_dispatch_resolution_proof(store.cancel_id, gate)
    second = authority.create_cancel_dispatch_resolution_proof(store.cancel_id, gate)
    assert first.writer_fence_sha256 != second.writer_fence_sha256
    with pytest.raises(FakeDispatchJournalError):
        with authority.cancel_dispatch_resolution_guard(first, claim=gate.claim):
            pass
    with authority.cancel_dispatch_resolution_guard(second, claim=gate.claim):
        pass


def test_v2_schema_migrates_and_cancel_proof_survives_reopen(tmp_path: Path) -> None:
    database_path = tmp_path / "fake.sqlite3"
    lease = _Lease(_EXECUTION_SCOPE.account_key, "fixture-writer", 3, 10**30)
    store = _ExecutionStore(_EXECUTION_SCOPE, lease, "REJECTED")
    gate = _RiskGate(_RISK_SCOPE, store.cancel_intent)
    # Recreate the exact prior schema with the frozen parent v2 implementation.
    v2_authority_module.ManagedFakeProviderJournalAuthority(
        database_path=database_path,
        execution_scope=_EXECUTION_SCOPE,
        risk_scope=_RISK_SCOPE,
        execution_store=store,
        facade=_Facade(lease),
        risk_types=_RiskTypes,
    )
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2

    migrated = ManagedFakeProviderJournalAuthority(
        database_path=database_path,
        execution_scope=_EXECUTION_SCOPE,
        risk_scope=_RISK_SCOPE,
        execution_store=store,
        facade=_Facade(lease),
        risk_types=_RiskTypes,
    )
    proof = migrated.create_cancel_dispatch_resolution_proof(store.cancel_id, gate)
    assert proof.terminal_state is _CancelTerminal.REJECTED
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 3

    reopened = ManagedFakeProviderJournalAuthority(
        database_path=database_path,
        execution_scope=_EXECUTION_SCOPE,
        risk_scope=_RISK_SCOPE,
        execution_store=store,
        facade=_Facade(lease),
        risk_types=_RiskTypes,
    )
    with reopened.cancel_dispatch_resolution_guard(proof, claim=gate.claim) as verified:
        assert verified.proof_sha256 == proof.fingerprint


def test_cancel_proof_guard_rechecks_target_freshness(tmp_path: Path) -> None:
    authority, store, gate, _lease = _setup(tmp_path, "REJECTED")
    proof = authority.create_cancel_dispatch_resolution_proof(store.cancel_id, gate)
    store.target_record = replace(store.target_record, updated_at_ns=41)
    with pytest.raises(FakeDispatchJournalError):
        with authority.cancel_dispatch_resolution_guard(proof, claim=gate.claim):
            pass


def test_cancel_proof_guard_rechecks_cancel_event_and_persisted_row(tmp_path: Path) -> None:
    authority, store, gate, _lease = _setup(tmp_path, "CANCELLED")
    proof = authority.create_cancel_dispatch_resolution_proof(store.cancel_id, gate)
    event = store.cancel_events[-1]
    store.cancel_events[-1] = replace(
        event, payload={**event.payload, "reason_code": "changed-after-issue"}
    )
    with pytest.raises(FakeDispatchJournalError):
        with authority.cancel_dispatch_resolution_guard(proof, claim=gate.claim):
            pass
    assert store.page_read_calls == 0

    store.cancel_events[-1] = event
    with sqlite3.connect(tmp_path / "fake.sqlite3") as connection:
        connection.execute("DROP TRIGGER fake_cancel_resolution_proofs_immutable_update")
        connection.execute(
            "UPDATE fake_cancel_resolution_proofs SET proof_json = ?",
            ("{}",),
        )
    with pytest.raises(FakeDispatchJournalError):
        with authority.cancel_dispatch_resolution_guard(proof, claim=gate.claim):
            pass


def test_order_only_proof_type_cannot_enter_cancel_resolution_guard(tmp_path: Path) -> None:
    authority, _store, gate, _lease = _setup(tmp_path, "REJECTED")
    order_proof = SimpleNamespace(scope=_RISK_SCOPE)
    with pytest.raises(FakeDispatchJournalError):
        with authority.cancel_dispatch_resolution_guard(order_proof, claim=gate.claim):
            pass


def test_missing_atomic_cancel_readback_never_falls_back_to_outbox_pages(
    tmp_path: Path,
) -> None:
    authority, store, gate, _lease = _setup(tmp_path, "CANCELLED")
    store.read_terminal_cancel_commit = None
    with pytest.raises(FakeDispatchJournalError, match="atomic terminal cancel readback"):
        authority.create_cancel_dispatch_resolution_proof(store.cancel_id, gate)
    assert store.page_read_calls == 0


def test_atomic_cancel_readback_digest_is_recomputed_by_parent_issuer(tmp_path: Path) -> None:
    authority, store, gate, _lease = _setup(tmp_path, "REJECTED")
    readback = store.read_terminal_cancel_commit

    def corrupted_readback(scope, cancel_id, *, writer_lease):
        commit = readback(scope, cancel_id, writer_lease=writer_lease)
        corrupted = object.__new__(type(commit))
        for name in commit.__dataclass_fields__:
            object.__setattr__(corrupted, name, getattr(commit, name))
        object.__setattr__(corrupted, "cancel_event_sha256", "0" * 64)
        return corrupted

    store.read_terminal_cancel_commit = corrupted_readback
    with pytest.raises(FakeDispatchJournalError, match="event digest"):
        authority.create_cancel_dispatch_resolution_proof(store.cancel_id, gate)
    assert store.page_read_calls == 0
