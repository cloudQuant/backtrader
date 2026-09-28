from __future__ import annotations

import sqlite3
import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

_EXECUTION_SRC = Path(
    r"D:\temp\iteration41_v20_r3_cancel_terminal_candidate_20260927\src"
)
_RISK_SRC = Path(r"D:\temp\iteration41_risk_cancel_resolution_20260927\src")
sys.path.insert(0, str(_EXECUTION_SRC))
sys.path.insert(0, str(_RISK_SRC))

import bt_api_execution as execution  # noqa: E402
import bt_api_risk as risk  # noqa: E402

assert Path(execution.__file__).resolve() == (
    _EXECUTION_SRC / "bt_api_execution" / "__init__.py"
).resolve()
assert Path(risk.__file__).resolve() == (_RISK_SRC / "bt_api_risk" / "__init__.py").resolve()


def _real_risk_types():
    return SimpleNamespace(
        RiskIntent=risk.RiskIntent,
        IntentAction=risk.IntentAction,
        DispatchClaimBinding=risk.DispatchClaimBinding,
        CancelDispatchResolutionProof=risk.CancelDispatchResolutionProof,
        VerifiedCancelDispatchResolution=risk.VerifiedCancelDispatchResolution,
        DispatchEvidenceClass=risk.DispatchEvidenceClass,
        CancelDispatchTerminalState=risk.CancelDispatchTerminalState,
        CancelDispatchSource=risk.CancelDispatchSource,
        CancelTargetPostcondition=risk.CancelTargetPostcondition,
    )


class _RealRiskCancelAdmission:
    def __init__(self, gate, risk_scope, execution_scope):
        self._gate = gate
        self._risk_scope = risk_scope
        self._execution_scope = execution_scope
        self._intents = {}

    def _intent(self, cancel):
        return risk.RiskIntent(
            intent_id=f"cancel-admission:{self._execution_scope.key}:{cancel.cancel_id}",
            scope=self._risk_scope,
            action=risk.IntentAction.CANCEL,
            notional=Decimal("0"),
            payload_fingerprint=cancel.fingerprint,
        )

    def reserve(self, cancel):
        intent = self._intent(cancel)
        permit = self._gate.reserve(intent)
        self._intents[permit.permit_id] = intent
        return permit

    def validate(self, permit_id, _cancel):
        return self._gate.validate_permit(permit_id, self._intents[permit_id])

    def claim_before_dispatch(self, permit_reference, cancel):
        if cancel.fingerprint != self._intents[permit_reference].payload_fingerprint:
            raise AssertionError("cancel intent binding mismatch")
        self._gate.claim_for_dispatch(permit_reference, self._intents[permit_reference])
        return execution.CancelDispatchClaimReceiptV1(
            permit_reference=permit_reference,
            scope_key=cancel.scope.key,
            cancel_id=cancel.cancel_id,
            intent_fingerprint=cancel.fingerprint,
        )

    def settle(self, permit_id):
        return self._gate.settle(permit_id)

    def release(self, permit_id, reason):
        return self._gate.release(permit_id, reason)

    def dispatch_claim_binding(self, permit_id):
        return self._gate.dispatch_claim_binding(permit_id)


class _OrderGate:
    def reserve(self, intent):
        return type("Permit", (), {"permit_id": "order-permit"})()

    def validate(self, permit_id, intent):
        return type("Permit", (), {"permit_id": permit_id})()

    def settle(self, permit_id):
        return None

    def release(self, permit_id, reason):
        return None


@pytest.mark.parametrize("terminal_state", ["CANCELLED", "REJECTED"])
def test_proof_issuer_uses_real_r3_terminal_cancel_commit_snapshot(
    tmp_path: Path, terminal_state: str
) -> None:
    scope = execution.ExecutionScope(
        "FAKE", "offline", "acct-proof", "strategy.proof", "20260927"
    )
    store = execution.SqliteExecutionStore(tmp_path / "execution.sqlite3")
    order_facade = execution.ManagedExecutionFacade(
        store, scope, writer_id="cancel-proof-writer", admission_gate=_OrderGate()
    )
    order = execution.OrderIntent.limit(
        intent_id="cancel-proof-order",
        scope=scope,
        signal_id="signal-proof",
        instrument="BTC-USDT",
        side=execution.Side.BUY,
        quantity=Decimal("2"),
        price=Decimal("5"),
        metadata_version="meta-v1",
    )
    try:
        order_record = order_facade.submit(
            order,
            lambda intent: execution.ProviderObservation.accepted(
                intent.intent_id, "provider-order-proof"
            ),
        )
        assert order_record.state is execution.ExecutionState.ACKED
        order_record = order_facade.reconcile(
            execution.ProviderObservation(
                intent_id=order.intent_id,
                state=execution.ExecutionState.PARTIALLY_FILLED,
                provider_order_id="provider-order-proof",
                filled_quantity=Decimal("0.5"),
                average_price=Decimal("5"),
                cumulative_commission=Decimal("-0.01"),
            )
        )
        assert order_record.filled_quantity == Decimal("0.5")
        cancel = execution.CancelIntent(
            cancel_id="cancel-proof-1",
            scope=scope,
            target_intent_id=order.intent_id,
            provider_order_id="provider-order-proof",
            metadata_version="meta-v1",
        )
        risk_scope = risk.AccountScope(
            provider="fake", account_id="account-proof", environment="offline"
        )
        risk_types = _real_risk_types()
        authority = __import__(
            "cancel_proof_authority_under_test", fromlist=["ManagedFakeProviderJournalAuthority"]
        ).ManagedFakeProviderJournalAuthority(
            database_path=tmp_path / "fake.sqlite3",
            execution_scope=scope,
            risk_scope=risk_scope,
            execution_store=store,
            facade=order_facade,
            risk_types=risk_types,
        )
        risk_gate = risk.DurableRiskGate(
            tmp_path / "risk.sqlite3",
            risk.RiskPolicy(
                policy_id="cancel-proof-integration",
                max_increase_notional=Decimal("100"),
                max_increase_count=3,
            ),
            execution_journal_authority=authority,
        )
        admission = _RealRiskCancelAdmission(risk_gate, risk_scope, scope)
        cancel_facade = execution.ManagedCancellationFacade(
            store,
            scope,
            acquire_writer_lease=order_facade.acquire_writer_lease,
            admission_gate=admission,
        )
        if terminal_state == "CANCELLED":
            def cancel_provider(intent):
                return execution.CancelObservation.cancelled(
                    intent.cancel_id, intent.target_intent_id, intent.provider_order_id
                )
        else:
            def cancel_provider(intent):
                return execution.CancelObservation.rejected(
                    intent.cancel_id,
                    intent.target_intent_id,
                    intent.provider_order_id,
                    "provider_rejected",
                )
        cancel_record = cancel_facade.cancel(cancel, cancel_provider)
        assert cancel_record.state.value == terminal_state
        permit_id = cancel_record.permit_reference
        assert permit_id is not None
        binding = risk_gate.dispatch_claim_binding(permit_id)
        proof = authority.create_cancel_dispatch_resolution_proof(cancel.cancel_id, admission)
        assert type(proof) is risk.CancelDispatchResolutionProof
        assert proof.terminal_state.value == terminal_state
        assert proof.target_filled_quantity == "0.5"
        assert proof.cancel_event_id
        assert proof.cancel_event_sequence > 0
        assert proof.cancel_event_sha256
        assert proof.target_event_id
        assert proof.target_event_sequence > 0
        with authority.cancel_dispatch_resolution_guard(proof, claim=binding) as verified:
            assert type(verified) is risk.VerifiedCancelDispatchResolution
            assert verified.proof_sha256 == proof.fingerprint
        reopened = __import__(
            "cancel_proof_authority_under_test", fromlist=["ManagedFakeProviderJournalAuthority"]
        ).ManagedFakeProviderJournalAuthority(
            database_path=tmp_path / "fake.sqlite3",
            execution_scope=scope,
            risk_scope=risk_scope,
            execution_store=store,
            facade=order_facade,
            risk_types=risk_types,
        )
        reopened_risk_gate = risk.DurableRiskGate(
            tmp_path / "risk.sqlite3",
            risk.RiskPolicy(
                policy_id="cancel-proof-integration",
                max_increase_notional=Decimal("100"),
                max_increase_count=3,
            ),
            execution_journal_authority=reopened,
        )
        reopened_risk_gate.resolve_cancel_dispatch_freeze(proof)
        assert reopened_risk_gate.active_freeze_reasons(risk_scope) == []
        # Risk owns one-shot consumption; an exact committed proof is an idempotent replay.
        reopened_risk_gate.resolve_cancel_dispatch_freeze(proof)
        with sqlite3.connect(tmp_path / "risk.sqlite3") as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM risk_cancel_dispatch_resolutions"
            ).fetchone()[0] == 1
    finally:
        store.close()
