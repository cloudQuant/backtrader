"""Focused, zero-I/O coverage for the sealed provider-preflight binding."""

from __future__ import annotations

import json
import socket
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

import backtrader_runtime.provider_deployment as provider_deployment
from backtrader_runtime import (
    RegisteredRuntime,
    RuntimeConfigError,
    RuntimeRegistry,
    load_runtime_config,
    resolve_runtime_config,
)
from backtrader_runtime.policy import MANAGED_WRITE_CAPABILITIES
from backtrader_runtime.provider_deployment import (
    ACTIVE_RECEIPT_STATUS,
    PROVIDER_DEPLOYMENT_RECEIPT_SCHEMA_VERSION,
    ProviderDeploymentReceiptError,
    ProviderDeploymentRegistration,
)
from backtrader_runtime.provider_preflight import (
    ProviderSessionPreflightRegistration,
    validate_provider_session_preflight_binding,
)


NOW = 1_700_100_000.0
SECRET_REF = "os_secret_store:iteration41.ctp.simnow"
CAPABILITY_MODULES = (
    "bt_api_ctp",
    "bt_api_execution",
    "bt_api_monitor",
    "bt_api_py",
    "bt_api_risk",
)


@pytest.fixture(autouse=True)
def receipt_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise the production clock path while using fixed receipt vectors."""

    monkeypatch.setattr(provider_deployment.time, "time", lambda: NOW)


class _AcceptingOfflineVerifier:
    """Test-only verifier with no trust material, SDK access, or provider I/O."""

    def __init__(self) -> None:
        self.calls = 0

    def verify(self, receipt, canonical_payload: bytes) -> bool:
        self.calls += 1
        assert receipt.receipt_id == "provider-receipt-1"
        assert canonical_payload
        return True


def _write_config(runtime_dir: Path) -> None:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    (runtime_dir / "config.yaml").write_text(
        """config_schema_version: 4
strategy:
  id: example.provider_preflight
runtime:
  mode: simulation
  preset: sandbox
parameters: {{}}
secrets_ref: {secret_ref}
""".format(
            secret_ref=SECRET_REF
        ),
        encoding="utf-8",
    )


def _registry(runtime_dir: Path) -> RuntimeRegistry:
    return RuntimeRegistry(
        (
            RegisteredRuntime(
                runtime_dir=runtime_dir,
                runtime_id="example.provider_preflight.simnow",
                strategy_id="example.provider_preflight",
                allowed_presets=("sandbox",),
                allowed_secrets_refs=(SECRET_REF,),
                available_capabilities=MANAGED_WRITE_CAPABILITIES,
                sandbox_write_policy="receipt_required",
                approval_receipt_digest="a" * 64,
                capability_modules=CAPABILITY_MODULES,
            ),
        ),
        registry_id="iteration41.provider-preflight-test",
    )


def _effective(runtime_dir: Path):
    _write_config(runtime_dir)
    registry = _registry(runtime_dir)
    return (
        resolve_runtime_config(load_runtime_config(runtime_dir, registry=registry), registry),
        registry,
    )


def _deployment(effective) -> ProviderDeploymentRegistration:
    return ProviderDeploymentRegistration(
        registration_id="iteration41.ctp.simnow-readonly-preflight",
        runtime_id=effective.registration.runtime_id,
        strategy_id=effective.strategy_id,
        provider="ctp",
        environment="simnow_set2",
        allowed_secrets_refs=(SECRET_REF,),
        account_fingerprint_sha256="b" * 64,
        approval_receipt_digest=effective.registration.approval_receipt_digest,
        artifact_sha256="c" * 64,
        effective_config_digest=effective.effective_digest,
        capability_receipt_digest="d" * 64,
        required_capability_modules=tuple(sorted(CAPABILITY_MODULES)),
    )


def _profile(deployment: ProviderDeploymentRegistration) -> ProviderSessionPreflightRegistration:
    return ProviderSessionPreflightRegistration(
        deployment=deployment,
        mode="simulation",
        preset="sandbox",
        account_access="sandbox_direct_provider",
    )


def _receipt(deployment: ProviderDeploymentRegistration) -> dict:
    return {
        "account_fingerprint_sha256": deployment.account_fingerprint_sha256,
        "approval_receipt_digest": deployment.approval_receipt_digest,
        "artifact_sha256": deployment.artifact_sha256,
        "capability_receipt_digest": deployment.capability_receipt_digest,
        "created_at": NOW - 10.0,
        "effective_config_digest": deployment.effective_config_digest,
        "environment": deployment.environment,
        "expires_at": NOW + 60.0,
        "provider": deployment.provider,
        "receipt_id": "provider-receipt-1",
        "registration_id": deployment.registration_id,
        "required_capability_modules": list(deployment.required_capability_modules),
        "revoked_at": None,
        "runtime_id": deployment.runtime_id,
        "schema_version": PROVIDER_DEPLOYMENT_RECEIPT_SCHEMA_VERSION,
        "secrets_ref": SECRET_REF,
        "status": ACTIVE_RECEIPT_STATUS,
        "strategy_id": deployment.strategy_id,
    }


def test_sandbox_receipt_binding_cannot_connect_or_authorize_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    effective, registry = _effective(tmp_path / "runtime")
    deployment = _deployment(effective)
    verifier = _AcceptingOfflineVerifier()
    socket_attempts = []

    def reject_socket(*args, **kwargs):
        socket_attempts.append((args, kwargs))
        raise AssertionError("offline provider preflight binding must not open a socket")

    monkeypatch.setattr(socket, "socket", reject_socket)
    binding = validate_provider_session_preflight_binding(
        effective,
        registry,
        _profile(deployment),
        _receipt(deployment),
        verifier=verifier,
    )

    assert verifier.calls == 1
    assert binding.mode == "simulation"
    assert binding.preset == "sandbox"
    assert binding.preflight_binding_valid is True
    assert binding.provider_preflight_started is False
    assert binding.secrets_resolved is False
    assert binding.session_connected is False
    assert binding.execution_authorized is False
    assert binding.external_writes_authorized is False
    assert binding.valid_until == NOW + 60.0
    assert socket_attempts == []
    with pytest.raises(TypeError, match="not a session or execution authorization"):
        bool(binding)
    public = json.dumps(binding.as_public_dict(), sort_keys=True)
    assert SECRET_REF not in public


def test_caller_cannot_override_receipt_clock(tmp_path: Path) -> None:
    effective, registry = _effective(tmp_path / "runtime")
    deployment = _deployment(effective)
    verifier = _AcceptingOfflineVerifier()

    with pytest.raises(TypeError, match="unexpected keyword argument 'now'"):
        validate_provider_session_preflight_binding(
            effective,
            registry,
            _profile(deployment),
            _receipt(deployment),
            verifier=verifier,
            now=NOW - 1_000.0,  # type: ignore[call-arg]
        )

    assert verifier.calls == 0


def test_default_receipt_verifier_stops_before_any_session_preflight(tmp_path: Path) -> None:
    effective, registry = _effective(tmp_path / "runtime")
    deployment = _deployment(effective)

    with pytest.raises(ProviderDeploymentReceiptError) as caught:
        validate_provider_session_preflight_binding(
            effective,
            registry,
            _profile(deployment),
            _receipt(deployment),
        )

    assert caught.value.reason == "receipt_untrusted"


def test_binding_rejects_a_deployment_for_a_different_effective_config(tmp_path: Path) -> None:
    effective, registry = _effective(tmp_path / "runtime")
    deployment = replace(_deployment(effective), effective_config_digest="e" * 64)

    with pytest.raises(RuntimeConfigError) as caught:
        validate_provider_session_preflight_binding(
            effective,
            registry,
            _profile(deployment),
            _receipt(deployment),
            verifier=_AcceptingOfflineVerifier(),
        )

    assert getattr(caught.value, "reason", None) == "provider_effective_config_mismatch"


def test_binding_rejects_a_deployment_for_a_different_runtime_approval_digest(
    tmp_path: Path,
) -> None:
    effective, registry = _effective(tmp_path / "runtime")
    deployment = replace(_deployment(effective), approval_receipt_digest="f" * 64)
    verifier = _AcceptingOfflineVerifier()

    with pytest.raises(RuntimeConfigError) as caught:
        validate_provider_session_preflight_binding(
            effective,
            registry,
            _profile(deployment),
            _receipt(deployment),
            verifier=verifier,
        )

    assert getattr(caught.value, "reason", None) == "provider_approval_receipt_digest_mismatch"
    assert verifier.calls == 0


def test_binding_rejects_different_capability_modules_before_receipt_verification(
    tmp_path: Path,
) -> None:
    effective, registry = _effective(tmp_path / "runtime")
    deployment = replace(
        _deployment(effective),
        required_capability_modules=("bt_api_ctp", "bt_api_py"),
    )
    verifier = _AcceptingOfflineVerifier()

    with pytest.raises(RuntimeConfigError) as caught:
        validate_provider_session_preflight_binding(
            effective,
            registry,
            _profile(deployment),
            _receipt(deployment),
            verifier=verifier,
        )

    assert getattr(caught.value, "reason", None) == "provider_capability_modules_mismatch"
    assert verifier.calls == 0


@pytest.mark.parametrize(
    "mode,preset,account_access",
    (
        ("simulation", "replay", "sandbox_direct_provider"),
        ("simulation", "sandbox", "direct_provider"),
        ("live", "sandbox", "sandbox_direct_provider"),
    ),
)
def test_preflight_registration_only_accepts_reviewed_managed_route_shapes(
    tmp_path: Path, mode: str, preset: str, account_access: str
) -> None:
    effective, _ = _effective(tmp_path / "runtime")

    with pytest.raises(ValueError):
        ProviderSessionPreflightRegistration(
            deployment=_deployment(effective),
            mode=mode,
            preset=preset,
            account_access=account_access,
        )


@pytest.mark.parametrize(
    "provider,environment",
    (
        ("ctp", "sandbox"),
        ("ctp", "production"),
        ("ctp", "simnow_set0"),
        ("ctp", "simnow_set01"),
        ("okx", "simnow_set2"),
        ("unreviewed", "demo"),
    ),
)
def test_sandbox_preflight_requires_a_code_owned_nonproduction_environment(
    tmp_path: Path, provider: str, environment: str
) -> None:
    effective, _ = _effective(tmp_path / "runtime")
    deployment = replace(_deployment(effective), provider=provider, environment=environment)

    with pytest.raises(ValueError, match="environment"):
        _profile(deployment)


def test_ctp_simnow_environment_is_rechecked_at_binding_time(tmp_path: Path) -> None:
    effective, registry = _effective(tmp_path / "runtime")
    deployment = _deployment(effective)
    registration = _profile(deployment)
    object.__setattr__(deployment, "environment", "production")
    verifier = _AcceptingOfflineVerifier()

    with pytest.raises(RuntimeConfigError) as caught:
        validate_provider_session_preflight_binding(
            effective,
            registry,
            registration,
            _receipt(_deployment(effective)),
            verifier=verifier,
        )

    assert getattr(caught.value, "reason", None) == "provider_preflight_registration_invalid"
    assert verifier.calls == 0


def test_live_preflight_requires_the_exact_production_environment(tmp_path: Path) -> None:
    effective, _ = _effective(tmp_path / "runtime")
    deployment = replace(_deployment(effective), provider="ctp", environment="production-us")

    with pytest.raises(ValueError, match="exact production"):
        ProviderSessionPreflightRegistration(
            deployment=deployment,
            mode="live",
            preset="managed_live_direct",
            account_access="direct_provider",
        )


def test_live_preflight_accepts_the_exact_production_environment(tmp_path: Path) -> None:
    effective, _ = _effective(tmp_path / "runtime")
    deployment = replace(_deployment(effective), environment="production")

    registration = ProviderSessionPreflightRegistration(
        deployment=deployment,
        mode="live",
        preset="managed_live_direct",
        account_access="direct_provider",
    )

    assert registration.deployment.environment == "production"


def test_preflight_module_imports_no_provider_or_backtrader_framework() -> None:
    program = """
import sys
import backtrader_runtime.provider_preflight
blocked = ('backtrader', 'bt_api', 'bt_api_py', 'bt_api_ctp', 'bt_api_execution', 'bt_api_risk', 'bt_api_monitor')
assert not any(name == item or name.startswith(item + '.') for item in blocked for name in sys.modules)
"""
    result = subprocess.run(
        [sys.executable, "-c", program],
        cwd=Path(__file__).resolve().parents[3],
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 0, result.stderr
