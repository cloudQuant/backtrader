"""Offline tests for the unregistered production per-action scope contract."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest

from backtrader_runtime.ctp_production_action_binding import (
    CtpProductionActionApproval,
    CtpProductionActionBindingError,
    CtpProductionActionCredentialBinding,
    CtpProductionActionDispatchObservation,
    RejectingCtpProductionActionTrustSource,
    ctp_production_action_scope_sha256,
    derive_ctp_production_action_credential_scope,
    observe_ctp_production_action_dispatch_revalidation,
    require_ctp_production_action_credential_binding,
)
from backtrader_runtime.ctp_simulation_execution import CtpSimulationWriteApproval
from backtrader_runtime.ctp_production_execution_admission import (
    production_front_pair_set_sha256,
)
from backtrader_runtime.ctp_production_readonly_admission import (
    production_account_binding_sha256,
)
from backtrader_runtime.ctp_trader_client_port import CtpSimulationTraderConfig
from backtrader_runtime.registry import resolve_runtime_config

import backtrader_runtime.config as runtime_config

from test_ctp_production_execution_admission import (
    _PRIVATE_VALUES,
    _PROFILE_RECEIPT_SHA256,
    _profile_scope_inputs,
    _stub_private_config_security_for_synthetic_test,
    _write_profile_scope_config,
)


_FRONT_PAIRS = [
    {"md_front": "tcp://192.0.2.11:41211", "td_front": "tcp://192.0.2.10:41201"},
    {"md_front": "tcp://192.0.2.21:41211", "td_front": "tcp://192.0.2.20:41201"},
]
_SELECTED_PAIR = (_FRONT_PAIRS[1]["md_front"], _FRONT_PAIRS[1]["td_front"])
_REQUEST_DIGEST = hashlib.sha256(b"synthetic production order request").hexdigest()


class _AcceptExactApproval:
    def __init__(self, expected: CtpProductionActionApproval) -> None:
        self.expected = expected
        self.calls: list[CtpProductionActionApproval] = []

    def verify(self, approval: CtpProductionActionApproval) -> bool:
        self.calls.append(approval)
        return approval is self.expected


class _SyntheticTrustSource(_AcceptExactApproval):
    def __init__(
        self,
        expected: CtpProductionActionApproval,
        *,
        times: tuple[Any, ...] = (100.0, 100.0),
        revoked: Any = False,
        verify_result: bool = True,
        verify_error: bool = False,
        revocation_error: bool = False,
    ) -> None:
        super().__init__(expected)
        self.times = times
        self.revoked = revoked
        self.verify_result = verify_result
        self.verify_error = verify_error
        self.revocation_error = revocation_error
        self.clock_calls = 0
        self.revocation_calls: list[tuple[str, str, str]] = []

    def now(self) -> float:
        index = min(self.clock_calls, len(self.times) - 1)
        self.clock_calls += 1
        value = self.times[index]
        if isinstance(value, Exception):
            raise value
        return value

    def verify(self, approval: CtpProductionActionApproval) -> bool:
        self.calls.append(approval)
        if self.verify_error:
            raise RuntimeError("synthetic signature service failure")
        return approval is self.expected and self.verify_result

    def is_revoked(self, approval_id: str, receipt_sha256: str, action_scope_sha256: str) -> Any:
        if self.revocation_error:
            raise RuntimeError("synthetic revocation service failure")
        self.revocation_calls.append((approval_id, receipt_sha256, action_scope_sha256))
        return self.revoked


def _synthetic_live_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    private_values: dict[str, Any] | None = None,
):
    runtime_dir = tmp_path / "single-private-runtime"
    registry, registered, admission = _profile_scope_inputs(runtime_dir)
    _stub_private_config_security_for_synthetic_test(monkeypatch)
    values = dict(_PRIVATE_VALUES if private_values is None else private_values)
    values.pop("md_front", None)
    values.pop("td_front", None)
    values["front_pairs"] = [dict(pair) for pair in _FRONT_PAIRS]
    _write_profile_scope_config(
        runtime_dir,
        mode="live",
        preset="managed_live_direct",
        private_values=values,
    )
    config = runtime_config.load_runtime_config(runtime_dir, registry=registry)
    effective = resolve_runtime_config(config, registry)
    return runtime_dir, values, registry, registered, admission, config, effective


def _approval(scope, admission, *, now: float = 100.0) -> CtpProductionActionApproval:
    intent_id = "synthetic-order-001"
    action_scope_digest = ctp_production_action_scope_sha256(
        scope,
        operation="SUBMIT",
        request_digest=_REQUEST_DIGEST,
        managed_intent_id=intent_id,
    )
    return CtpProductionActionApproval(
        approval_id="ctp-production:approval.synthetic.001",
        receipt_sha256=admission.approval_receipt_sha256,
        credential_scope_sha256=scope.credential_scope_sha256,
        action_scope_sha256=action_scope_digest,
        operation="SUBMIT",
        request_digest=_REQUEST_DIGEST,
        managed_intent_id=intent_id,
        action_id=None,
        issued_at=now - 1,
        expires_at=now + 10,
        signature_hex="e" * 64,
    )


def _simnow_approval() -> CtpSimulationWriteApproval:
    return CtpSimulationWriteApproval(
        approval_id="old-simnow-approval",
        key_id="simnow-test-key",
        registration_digest="a" * 64,
        receipt_digest="b" * 64,
        account_fingerprint_sha256="c" * 64,
        environment="simnow",
        td_front="tcp://192.0.2.10:41201",
        md_front="tcp://192.0.2.11:41211",
        request_digest=_REQUEST_DIGEST,
        issued_at=90.0,
        expires_at=110.0,
        signature_hex="d" * 64,
    )


def test_same_config_file_switches_from_sandbox_to_exact_production_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime_dir = tmp_path / "same-protected-runtime"
    registry, _registered, admission = _profile_scope_inputs(runtime_dir)
    _stub_private_config_security_for_synthetic_test(monkeypatch)
    config_path = runtime_dir / "config.yaml"

    _write_profile_scope_config(
        runtime_dir,
        mode="simulation",
        preset="sandbox",
    )
    sandbox_config = runtime_config.load_runtime_config(runtime_dir, registry=registry)
    sandbox_effective = resolve_runtime_config(sandbox_config, registry)
    assert sandbox_config.source_path == config_path
    with pytest.raises(CtpProductionActionBindingError) as sandbox_error:
        derive_ctp_production_action_credential_scope(
            sandbox_config,
            registry,
            admission,
            selected_front_pair=(_PRIVATE_VALUES["md_front"], _PRIVATE_VALUES["td_front"]),
            effective_runtime=sandbox_effective,
        )
    assert sandbox_error.value.reason == "production_execution_scope_rejected"

    production_values = dict(_PRIVATE_VALUES)
    production_values.pop("md_front")
    production_values.pop("td_front")
    production_values["front_pairs"] = [dict(pair) for pair in _FRONT_PAIRS]
    _write_profile_scope_config(
        runtime_dir,
        mode="live",
        preset="managed_live_direct",
        private_values=production_values,
    )
    live_config = runtime_config.load_runtime_config(runtime_dir, registry=registry)
    live_effective = resolve_runtime_config(live_config, registry)
    assert live_config.source_path == config_path

    scope = derive_ctp_production_action_credential_scope(
        live_config,
        registry,
        admission,
        selected_front_pair=_SELECTED_PAIR,
        effective_runtime=live_effective,
    )
    assert scope.environment == "production"
    assert scope.mode == "live"
    assert scope.preset == "managed_live_direct"
    assert scope.config_digest == live_config.config_digest
    assert scope.effective_digest == live_effective.effective_digest
    assert scope.account_binding_sha256 == production_account_binding_sha256(
        production_values["broker_id"], production_values["user_id"]
    )
    assert scope.front_pair_set_sha256 == production_front_pair_set_sha256(
        [(_FRONT_PAIRS[0]["md_front"], _FRONT_PAIRS[0]["td_front"]), _SELECTED_PAIR]
    )
    assert scope.front_pair_sha256 != "0" * 64
    assert scope.instrument_id == production_values["instrument_id"]
    assert scope.exchange_id == production_values["exchange_id"]
    assert scope.hedge_flag == production_values["hedge_flag"]
    assert scope.credential_values_resolved is False
    assert scope.credential_access_authorized is False
    assert scope.provider_access_authorized is False
    assert scope.execution_authorized is False
    assert scope.external_writes_authorized is False


def test_production_action_binding_verifies_exact_scope_and_remains_non_authorizing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, registry, _registered, admission, config, effective = _synthetic_live_config(
        tmp_path, monkeypatch
    )
    scope = derive_ctp_production_action_credential_scope(
        config,
        registry,
        admission,
        selected_front_pair=_SELECTED_PAIR,
        effective_runtime=effective,
    )
    approval = _approval(scope, admission)
    verifier = _AcceptExactApproval(approval)

    binding = require_ctp_production_action_credential_binding(
        config,
        registry,
        admission,
        effective_runtime=effective,
        selected_front_pair=_SELECTED_PAIR,
        credential_scope=scope,
        approval=approval,
        checked_at=100.0,
        verifier=verifier,
    )

    assert isinstance(binding, CtpProductionActionCredentialBinding)
    assert verifier.calls == [approval]
    assert binding.credential_scope_sha256 == scope.credential_scope_sha256
    assert binding.action_scope_sha256 == approval.action_scope_sha256
    assert binding.config_digest == config.config_digest
    assert binding.effective_digest == effective.effective_digest
    assert binding.receipt_sha256 == _PROFILE_RECEIPT_SHA256
    assert binding.operation == "SUBMIT"
    assert binding.managed_intent_id == approval.managed_intent_id
    assert binding.injected_verifier_accepted is True
    assert binding.credential_values_resolved is False
    assert binding.credential_access_authorized is False
    assert binding.provider_access_authorized is False
    assert binding.execution_authorized is False
    assert binding.external_writes_authorized is False
    assert binding.order_submission_authorized is False
    assert binding.cancellation_authorized is False
    assert binding.arming_authorized is False
    with pytest.raises(TypeError, match="non-authorizing"):
        bool(binding)


def test_production_action_approval_is_rejected_without_an_injected_verifier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, registry, _registered, admission, config, effective = _synthetic_live_config(
        tmp_path, monkeypatch
    )
    scope = derive_ctp_production_action_credential_scope(
        config,
        registry,
        admission,
        selected_front_pair=_SELECTED_PAIR,
        effective_runtime=effective,
    )
    approval = _approval(scope, admission)

    with pytest.raises(CtpProductionActionBindingError) as caught:
        require_ctp_production_action_credential_binding(
            config,
            registry,
            admission,
            effective_runtime=effective,
            selected_front_pair=_SELECTED_PAIR,
            credential_scope=scope,
            approval=approval,
            checked_at=100.0,
        )

    assert caught.value.reason == "production_action_approval_rejected"


def test_dispatch_revalidation_uses_fresh_clock_and_returns_only_non_authorizing_observation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, registry, _registered, admission, config, effective = _synthetic_live_config(
        tmp_path, monkeypatch
    )
    scope = derive_ctp_production_action_credential_scope(
        config,
        registry,
        admission,
        selected_front_pair=_SELECTED_PAIR,
        effective_runtime=effective,
    )
    approval = _approval(scope, admission)
    trust = _SyntheticTrustSource(approval, times=(100.0, 101.0))

    observation = observe_ctp_production_action_dispatch_revalidation(
        config,
        registry,
        admission,
        effective_runtime=effective,
        selected_front_pair=_SELECTED_PAIR,
        credential_scope=scope,
        approval=approval,
        trust_source=trust,
    )

    assert isinstance(observation, CtpProductionActionDispatchObservation)
    assert trust.calls == [approval]
    assert trust.clock_calls == 2
    assert trust.revocation_calls == [
        (approval.approval_id, approval.receipt_sha256, approval.action_scope_sha256)
    ]
    assert observation.checked_at == 100.0
    assert observation.rechecked_at == 101.0
    assert observation.injected_verifier_accepted is True
    assert observation.injected_revocation_checker_clear is True
    assert observation.deployment_trust_established is False
    assert observation.credential_access_authorized is False
    assert observation.provider_access_authorized is False
    assert observation.execution_authorized is False
    assert observation.external_writes_authorized is False
    with pytest.raises(TypeError, match="non-authorizing"):
        bool(observation)


def test_dispatch_revalidation_fails_closed_without_deployment_trust_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, registry, _registered, admission, config, effective = _synthetic_live_config(
        tmp_path, monkeypatch
    )
    scope = derive_ctp_production_action_credential_scope(
        config,
        registry,
        admission,
        selected_front_pair=_SELECTED_PAIR,
        effective_runtime=effective,
    )
    approval = _approval(scope, admission)
    rejecting = RejectingCtpProductionActionTrustSource()

    assert rejecting.verify(approval) is False
    assert (
        rejecting.is_revoked(
            approval.approval_id, approval.receipt_sha256, approval.action_scope_sha256
        )
        is None
    )
    with pytest.raises(RuntimeError, match="not installed"):
        rejecting.now()
    with pytest.raises(CtpProductionActionBindingError) as caught:
        observe_ctp_production_action_dispatch_revalidation(
            config,
            registry,
            admission,
            effective_runtime=effective,
            selected_front_pair=_SELECTED_PAIR,
            credential_scope=scope,
            approval=approval,
        )

    assert caught.value.reason == "production_action_trust_clock_failed"


@pytest.mark.parametrize(
    ("times", "revoked", "verify_result", "revocation_error", "reason"),
    (
        ((100.0, 111.0), False, True, False, "production_action_approval_expired"),
        ((100.0, 99.0), False, True, False, "production_action_clock_rollback"),
        ((100.0, 100.0), True, True, False, "production_action_revoked"),
        ((100.0, 100.0), None, True, False, "production_action_revocation_unknown"),
        ((100.0, 100.0), False, False, False, "production_action_approval_rejected"),
        ((100.0, 100.0), False, True, True, "production_action_revocation_check_failed"),
        (
            (RuntimeError("clock unavailable"),),
            False,
            True,
            False,
            "production_action_trust_clock_failed",
        ),
    ),
)
def test_dispatch_revalidation_rejects_stale_untrusted_or_uncertain_observations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    times: tuple[Any, ...],
    revoked: Any,
    verify_result: bool,
    revocation_error: bool,
    reason: str,
) -> None:
    _, _, registry, _registered, admission, config, effective = _synthetic_live_config(
        tmp_path, monkeypatch
    )
    scope = derive_ctp_production_action_credential_scope(
        config,
        registry,
        admission,
        selected_front_pair=_SELECTED_PAIR,
        effective_runtime=effective,
    )
    approval = _approval(scope, admission)
    trust = _SyntheticTrustSource(
        approval,
        times=times,
        revoked=revoked,
        verify_result=verify_result,
        revocation_error=revocation_error,
    )

    with pytest.raises(CtpProductionActionBindingError) as caught:
        observe_ctp_production_action_dispatch_revalidation(
            config,
            registry,
            admission,
            effective_runtime=effective,
            selected_front_pair=_SELECTED_PAIR,
            credential_scope=scope,
            approval=approval,
            trust_source=trust,
        )

    assert caught.value.reason == reason


def test_dispatch_revalidation_rejects_future_issued_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, registry, _registered, admission, config, effective = _synthetic_live_config(
        tmp_path, monkeypatch
    )
    scope = derive_ctp_production_action_credential_scope(
        config,
        registry,
        admission,
        selected_front_pair=_SELECTED_PAIR,
        effective_runtime=effective,
    )
    approval = _approval(scope, admission, now=102.0)
    trust = _SyntheticTrustSource(approval, times=(100.0, 100.0))

    with pytest.raises(CtpProductionActionBindingError) as caught:
        observe_ctp_production_action_dispatch_revalidation(
            config,
            registry,
            admission,
            effective_runtime=effective,
            selected_front_pair=_SELECTED_PAIR,
            credential_scope=scope,
            approval=approval,
            trust_source=trust,
        )

    assert caught.value.reason == "production_action_approval_expired"
    assert trust.calls == []


def test_dispatch_revalidation_rejects_signature_verifier_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, registry, _registered, admission, config, effective = _synthetic_live_config(
        tmp_path, monkeypatch
    )
    scope = derive_ctp_production_action_credential_scope(
        config,
        registry,
        admission,
        selected_front_pair=_SELECTED_PAIR,
        effective_runtime=effective,
    )
    approval = _approval(scope, admission)
    trust = _SyntheticTrustSource(approval, verify_error=True)

    with pytest.raises(CtpProductionActionBindingError) as caught:
        observe_ctp_production_action_dispatch_revalidation(
            config,
            registry,
            admission,
            effective_runtime=effective,
            selected_front_pair=_SELECTED_PAIR,
            credential_scope=scope,
            approval=approval,
            trust_source=trust,
        )

    assert caught.value.reason == "production_action_approval_verifier_failed"
    assert trust.revocation_calls == []


@pytest.mark.parametrize("change", ("account", "front", "contract"))
def test_old_production_action_scope_is_rejected_after_same_file_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    (
        runtime_dir,
        values,
        registry,
        _registered,
        admission,
        config,
        effective,
    ) = _synthetic_live_config(tmp_path, monkeypatch)
    old_scope = derive_ctp_production_action_credential_scope(
        config,
        registry,
        admission,
        selected_front_pair=_SELECTED_PAIR,
        effective_runtime=effective,
    )
    old_approval = _approval(old_scope, admission)
    trust = _SyntheticTrustSource(old_approval)

    changed_values = dict(values)
    changed_values["front_pairs"] = [dict(pair) for pair in values["front_pairs"]]
    if change == "account":
        changed_values["user_id"] = "synthetic-production-account-rotated"
    elif change == "front":
        changed_values["front_pairs"][0]["md_front"] = "tcp://192.0.2.31:41211"
    else:
        changed_values["instrument_id"] = "IH2612"
    _write_profile_scope_config(
        runtime_dir,
        mode="live",
        preset="managed_live_direct",
        private_values=changed_values,
    )
    changed_config = runtime_config.load_runtime_config(runtime_dir, registry=registry)
    changed_effective = resolve_runtime_config(changed_config, registry)

    with pytest.raises(CtpProductionActionBindingError) as caught:
        observe_ctp_production_action_dispatch_revalidation(
            changed_config,
            registry,
            admission,
            effective_runtime=changed_effective,
            selected_front_pair=_SELECTED_PAIR,
            credential_scope=old_scope,
            approval=old_approval,
            trust_source=trust,
        )

    assert caught.value.reason == "production_credential_scope_stale"
    assert trust.calls == []
    assert trust.revocation_calls == []


def test_simnow_approval_type_cannot_reach_production_action_verifier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, registry, _registered, admission, config, effective = _synthetic_live_config(
        tmp_path, monkeypatch
    )
    scope = derive_ctp_production_action_credential_scope(
        config,
        registry,
        admission,
        selected_front_pair=_SELECTED_PAIR,
        effective_runtime=effective,
    )
    verifier = _AcceptExactApproval(_approval(scope, admission))

    with pytest.raises(CtpProductionActionBindingError) as caught:
        require_ctp_production_action_credential_binding(
            config,
            registry,
            admission,
            effective_runtime=effective,
            selected_front_pair=_SELECTED_PAIR,
            credential_scope=scope,
            approval=_simnow_approval(),  # type: ignore[arg-type]
            checked_at=100.0,
            verifier=verifier,
        )

    assert caught.value.reason == "production_action_approval_type_mismatch"
    assert verifier.calls == []


def test_simnow_credential_binding_type_cannot_reach_production_action_verifier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, registry, _registered, admission, config, effective = _synthetic_live_config(
        tmp_path, monkeypatch
    )
    scope = derive_ctp_production_action_credential_scope(
        config,
        registry,
        admission,
        selected_front_pair=_SELECTED_PAIR,
        effective_runtime=effective,
    )
    approval = _approval(scope, admission)
    verifier = _AcceptExactApproval(approval)
    simnow_credentials = CtpSimulationTraderConfig(
        td_front=_SELECTED_PAIR[1],
        md_front=_SELECTED_PAIR[0],
        broker_id="synthetic-simnow-broker",
        user_id="synthetic-simnow-account",
        password="synthetic-simnow-password-never-use",
        auth_code="synthetic-simnow-auth",
        app_id="synthetic-simnow-app",
    )

    with pytest.raises(CtpProductionActionBindingError) as caught:
        require_ctp_production_action_credential_binding(
            config,
            registry,
            admission,
            effective_runtime=effective,
            selected_front_pair=_SELECTED_PAIR,
            credential_scope=simnow_credentials,  # type: ignore[arg-type]
            approval=approval,
            checked_at=100.0,
            verifier=verifier,
        )

    assert caught.value.reason == "production_credential_scope_type_mismatch"
    assert verifier.calls == []
