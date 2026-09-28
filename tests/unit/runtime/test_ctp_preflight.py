"""Zero-SDK tests for the sealed CTP SimNow read-only preflight contract."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, Optional, Tuple

import pytest

import backtrader_runtime.ctp_preflight as ctp_preflight
from backtrader_runtime import (
    RegisteredRuntime,
    RuntimeRegistry,
    load_runtime_config,
    resolve_runtime_config,
)
from backtrader_runtime.ctp_preflight import (
    CTP_PROVIDER,
    REQUIRED_CTP_READ_ONLY_QUERIES,
    CtpReadOnlyPreflightError,
    CtpReadOnlyQuerySnapshot,
    CtpReadOnlySessionIdentity,
    run_ctp_simnow_readonly_preflight,
)
from backtrader_runtime.policy import MANAGED_WRITE_CAPABILITIES
from backtrader_runtime.provider_deployment import (
    ACTIVE_RECEIPT_STATUS,
    PROVIDER_DEPLOYMENT_RECEIPT_SCHEMA_VERSION,
    ProviderDeploymentRegistration,
)
from backtrader_runtime.provider_preflight import ProviderSessionPreflightRegistration
from backtrader_runtime.test_execution_profile import (
    TEST_EXECUTION_PROFILE_SCHEMA_VERSION,
    TestExecutionPreflightContext as _TestExecutionPreflightContext,
)


NOW = 1_700_200_000.0
SECRET_REF = "os_secret_store:iteration41.ctp.simnow"
CAPABILITY_MODULES = (
    "bt_api_ctp",
    "bt_api_execution",
    "bt_api_monitor",
    "bt_api_py",
    "bt_api_risk",
)


def test_public_ctp_identity_omits_reversible_account_hash() -> None:
    account_hash = hashlib.sha256(b"9999:synthetic-user").hexdigest()
    identity = CtpReadOnlySessionIdentity(
        provider="ctp",
        environment="simnow_set1",
        account_fingerprint_sha256=account_hash,
        trading_day="20260921",
        connection_generation=1,
    )

    public = json.dumps(identity.as_public_dict())
    assert account_hash not in public
    assert account_hash not in repr(identity)
    assert account_hash not in repr(_snapshot(identity))
    assert "synthetic-user" not in public
    assert identity.as_public_dict()["account_scope"] == "redacted"


@pytest.fixture(autouse=True)
def ctp_clock(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Control the actual wall-clock lookup used by every validation layer."""

    clock = [NOW]
    monkeypatch.setattr(ctp_preflight.time, "time", lambda: clock[0])
    return clock


class _AcceptingReceiptVerifier:
    def verify(self, receipt, canonical_payload: bytes) -> bool:
        del receipt
        return bool(canonical_payload)


class _AcceptingProfileVerifier:
    def verify(self, profile, canonical_payload: bytes) -> bool:
        del profile
        return bool(canonical_payload)


def _write_config(runtime_dir: Path) -> None:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    (runtime_dir / "config.yaml").write_text(
        """config_schema_version: 4
strategy:
  id: example.ctp
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


def _sealed_inputs(runtime_dir: Path) -> dict[str, Any]:
    _write_config(runtime_dir)
    registry = RuntimeRegistry(
        (
            RegisteredRuntime(
                runtime_dir=runtime_dir,
                runtime_id="example.ctp.simnow",
                strategy_id="example.ctp",
                allowed_presets=("sandbox",),
                allowed_secrets_refs=(SECRET_REF,),
                available_capabilities=MANAGED_WRITE_CAPABILITIES,
                sandbox_write_policy="receipt_required",
                approval_receipt_digest="a" * 64,
                capability_modules=CAPABILITY_MODULES,
            ),
        ),
        registry_id="iteration41.ctp-preflight-test",
    )
    effective = resolve_runtime_config(
        load_runtime_config(runtime_dir, registry=registry), registry
    )
    deployment = ProviderDeploymentRegistration(
        registration_id="iteration41.ctp.simnow-readonly-preflight",
        runtime_id=effective.registration.runtime_id,
        strategy_id=effective.strategy_id,
        provider=CTP_PROVIDER,
        environment="simnow_set2",
        allowed_secrets_refs=(SECRET_REF,),
        approval_receipt_digest="a" * 64,
        account_fingerprint_sha256="b" * 64,
        artifact_sha256="c" * 64,
        effective_config_digest=effective.effective_digest,
        capability_receipt_digest="d" * 64,
        required_capability_modules=tuple(sorted(CAPABILITY_MODULES)),
    )
    provider_registration = ProviderSessionPreflightRegistration(
        deployment=deployment,
        mode="simulation",
        preset="sandbox",
        account_access="sandbox_direct_provider",
    )
    provider_receipt = {
        "account_fingerprint_sha256": deployment.account_fingerprint_sha256,
        "approval_receipt_digest": deployment.approval_receipt_digest,
        "artifact_sha256": deployment.artifact_sha256,
        "capability_receipt_digest": deployment.capability_receipt_digest,
        "created_at": NOW - 10.0,
        "effective_config_digest": deployment.effective_config_digest,
        "environment": deployment.environment,
        "expires_at": NOW + 60.0,
        "provider": deployment.provider,
        "receipt_id": "ctp-simnow-receipt-1",
        "registration_id": deployment.registration_id,
        "required_capability_modules": list(deployment.required_capability_modules),
        "revoked_at": None,
        "runtime_id": deployment.runtime_id,
        "schema_version": PROVIDER_DEPLOYMENT_RECEIPT_SCHEMA_VERSION,
        "secrets_ref": SECRET_REF,
        "status": ACTIVE_RECEIPT_STATUS,
        "strategy_id": deployment.strategy_id,
    }
    test_profile = {
        "account_fingerprint_sha256": deployment.account_fingerprint_sha256,
        "approval_receipt_digest": deployment.approval_receipt_digest,
        "allowed_instruments": ["rb2401"],
        "artifact_sha256": deployment.artifact_sha256,
        "capability_receipt_digest": deployment.capability_receipt_digest,
        "cleanup_required": True,
        "created_at": NOW - 10.0,
        "effective_config_digest": deployment.effective_config_digest,
        "environment": "simnow",
        "expires_at": NOW + 60.0,
        "max_external_writes": 0,
        "max_quantity": "1",
        "profile_id": "ctp-simnow-readonly",
        "provider": CTP_PROVIDER,
        "reconciliation_required": True,
        "schema_version": TEST_EXECUTION_PROFILE_SCHEMA_VERSION,
        "valid_from": NOW - 10.0,
    }
    test_profile_context = _TestExecutionPreflightContext(
        provider=CTP_PROVIDER,
        environment="simnow",
        account_fingerprint_sha256=deployment.account_fingerprint_sha256,
        approval_receipt_digest=deployment.approval_receipt_digest,
        effective_config_digest=deployment.effective_config_digest,
        artifact_sha256=deployment.artifact_sha256,
        capability_receipt_digest=deployment.capability_receipt_digest,
        instrument="rb2401",
        quantity="1",
        requested_external_writes=0,
        cleanup_ready=True,
        reconciliation_ready=True,
    )
    return {
        "effective": effective,
        "provider_receipt": provider_receipt,
        "provider_receipt_verifier": _AcceptingReceiptVerifier(),
        "provider_registration": provider_registration,
        "registry": registry,
        "test_profile": test_profile,
        "test_profile_context": test_profile_context,
        "test_profile_verifier": _AcceptingProfileVerifier(),
    }


def _identity(*, generation: int = 7) -> CtpReadOnlySessionIdentity:
    return CtpReadOnlySessionIdentity(
        provider=CTP_PROVIDER,
        environment="simnow_set2",
        account_fingerprint_sha256="b" * 64,
        trading_day="20260923",
        connection_generation=generation,
    )


def _snapshot(identity: CtpReadOnlySessionIdentity) -> CtpReadOnlyQuerySnapshot:
    return CtpReadOnlyQuerySnapshot.from_query_digests(
        identity,
        tuple(
            (name, hashlib.sha256(name.encode("ascii")).hexdigest())
            for name in REQUIRED_CTP_READ_ONLY_QUERIES
        ),
    )


def test_optional_native_certificate_digest_is_bound_to_snapshot_digest() -> None:
    identity = _identity()
    local = _snapshot(identity)
    native = CtpReadOnlyQuerySnapshot.from_query_digests(
        identity,
        local.query_digests,
        native_certificate_sha256="a" * 64,
        rate_exchange_scopes=(
            ("margin_rates", "unverified"),
            ("commission_rates", "exact"),
        ),
    )
    assert native.native_certificate_sha256 == "a" * 64
    assert native.rate_exchange_scopes == (
        ("commission_rates", "exact"),
        ("margin_rates", "unverified"),
    )
    assert native.snapshot_sha256 != local.snapshot_sha256
    assert native.as_public_dict()["native_certificate_sha256"] == "a" * 64
    assert native.as_public_dict()["rate_exchange_scopes"] == native.rate_exchange_scopes
    with pytest.raises(CtpReadOnlyPreflightError) as caught:
        replace(native, native_certificate_sha256="b" * 64)
    assert caught.value.reason == "snapshot_digest_mismatch"
    with pytest.raises(CtpReadOnlyPreflightError) as scope_tampered:
        replace(
            native, rate_exchange_scopes=(("margin_rates", "exact"), ("commission_rates", "exact"))
        )
    assert scope_tampered.value.reason == "snapshot_digest_mismatch"


def test_native_certificate_requires_complete_typed_rate_exchange_scopes() -> None:
    identity = _identity()
    digests = tuple(
        (name, hashlib.sha256(name.encode("ascii")).hexdigest())
        for name in REQUIRED_CTP_READ_ONLY_QUERIES
    )
    with pytest.raises(CtpReadOnlyPreflightError) as missing:
        CtpReadOnlyQuerySnapshot.from_query_digests(
            identity, digests, native_certificate_sha256="a" * 64
        )
    assert missing.value.reason == "missing_rate_exchange_scope"
    with pytest.raises(CtpReadOnlyPreflightError) as unknown:
        CtpReadOnlyQuerySnapshot.from_query_digests(
            identity,
            digests,
            native_certificate_sha256="a" * 64,
            rate_exchange_scopes=(("margin_rates", "unknown"), ("commission_rates", "exact")),
        )
    assert unknown.value.reason == "invalid_rate_exchange_scope"


class _FakeReadOnlySession:
    def __init__(
        self,
        identities: Tuple[CtpReadOnlySessionIdentity, ...],
        snapshot: Optional[CtpReadOnlyQuerySnapshot],
        *,
        query_error: Optional[Exception] = None,
    ) -> None:
        self._identities = identities
        self._snapshot = snapshot
        self._query_error = query_error
        self.identity_calls = 0
        self.snapshot_calls = 0
        self.close_calls = 0
        self.forbidden_calls = {"order": 0, "cancel": 0, "settlement": 0, "arm": 0}

    def read_identity(self) -> CtpReadOnlySessionIdentity:
        index = min(self.identity_calls, len(self._identities) - 1)
        self.identity_calls += 1
        return self._identities[index]

    def read_query_snapshot(self) -> CtpReadOnlyQuerySnapshot:
        self.snapshot_calls += 1
        if self._query_error is not None:
            raise self._query_error
        assert self._snapshot is not None
        return self._snapshot

    def close_read_only(self) -> None:
        self.close_calls += 1

    def submit_order(self) -> None:
        self.forbidden_calls["order"] += 1

    def cancel_order(self) -> None:
        self.forbidden_calls["cancel"] += 1

    def confirm_settlement(self) -> None:
        self.forbidden_calls["settlement"] += 1

    def arm_execution(self) -> None:
        self.forbidden_calls["arm"] += 1


class _FakeFactory:
    def __init__(self, session: _FakeReadOnlySession) -> None:
        self.session = session
        self.open_calls = 0
        self.request = None

    def open_read_only(self, request) -> _FakeReadOnlySession:
        self.open_calls += 1
        self.request = request
        return self.session


def _run(inputs: dict[str, Any], factory: Optional[_FakeFactory] = None, **overrides: Any):
    arguments = dict(inputs)
    arguments["session_factory"] = factory
    arguments.update(overrides)
    return run_ctp_simnow_readonly_preflight(**arguments)


def _assert_zero_writes(session: _FakeReadOnlySession) -> None:
    assert session.forbidden_calls == {"order": 0, "cancel": 0, "settlement": 0, "arm": 0}


def test_sealed_inputs_return_stable_zero_write_evidence(tmp_path: Path) -> None:
    inputs = _sealed_inputs(tmp_path / "runtime")
    identity = _identity()
    session = _FakeReadOnlySession((identity, identity), _snapshot(identity))
    factory = _FakeFactory(session)

    result = _run(inputs, factory)

    assert factory.open_calls == 1
    assert factory.request.provider == CTP_PROVIDER
    assert factory.request.environment == "simnow_set2"
    assert factory.request.account_fingerprint_sha256 == "b" * 64
    assert "b" * 64 not in repr(factory.request)
    assert session.identity_calls == 2
    assert session.snapshot_calls == 1
    assert session.close_calls == 1
    _assert_zero_writes(session)
    assert result.provider == CTP_PROVIDER
    assert result.trading_day == "20260923"
    assert result.connection_generation == 7
    assert result.test_profile_id == "ctp-simnow-readonly"
    assert result.execution_authorized is False
    assert result.external_writes_authorized is False
    assert result.order_submission_authorized is False
    assert result.cancellation_authorized is False
    assert result.settlement_authorized is False
    assert result.arming_authorized is False
    assert "b" * 64 not in repr(result)
    with pytest.raises(TypeError, match="not an execution authorization"):
        bool(result)


def test_rejected_sealed_inputs_never_construct_a_session(tmp_path: Path) -> None:
    inputs = _sealed_inputs(tmp_path / "runtime")
    identity = _identity()
    session = _FakeReadOnlySession((identity, identity), _snapshot(identity))
    factory = _FakeFactory(session)

    with pytest.raises(CtpReadOnlyPreflightError) as default_reject:
        _run(inputs, factory, provider_receipt_verifier=None)
    assert default_reject.value.reason == "provider_binding_validation_failed"
    assert factory.open_calls == 0

    mismatched_context = replace(inputs["test_profile_context"], environment="sandbox")
    with pytest.raises(CtpReadOnlyPreflightError) as profile_mismatch:
        _run(inputs, factory, test_profile_context=mismatched_context)
    assert profile_mismatch.value.reason == "test_profile_environment_mismatch"
    assert factory.open_calls == 0
    _assert_zero_writes(session)


def test_generation_change_rejects_and_closes_without_writes(tmp_path: Path) -> None:
    inputs = _sealed_inputs(tmp_path / "runtime")
    identity = _identity(generation=7)
    changed_identity = replace(identity, connection_generation=8)
    session = _FakeReadOnlySession((identity, changed_identity), _snapshot(identity))

    with pytest.raises(CtpReadOnlyPreflightError) as caught:
        _run(inputs, _FakeFactory(session))

    assert caught.value.reason == "session_identity_changed"
    assert session.identity_calls == 2
    assert session.snapshot_calls == 1
    assert session.close_calls == 1
    _assert_zero_writes(session)


def test_receipt_bound_account_identity_mismatch_never_reaches_query(tmp_path: Path) -> None:
    inputs = _sealed_inputs(tmp_path / "runtime")
    mismatched_identity = CtpReadOnlySessionIdentity(
        provider=CTP_PROVIDER,
        environment="simnow_set2",
        account_fingerprint_sha256="f" * 64,
        trading_day="20260923",
        connection_generation=7,
    )
    session = _FakeReadOnlySession(
        (mismatched_identity, mismatched_identity),
        _snapshot(mismatched_identity),
    )

    with pytest.raises(CtpReadOnlyPreflightError) as caught:
        _run(inputs, _FakeFactory(session))

    assert caught.value.reason == "session_identity_mismatch"
    assert session.identity_calls == 1
    assert session.snapshot_calls == 0
    assert session.close_calls == 1
    _assert_zero_writes(session)


@pytest.mark.parametrize("kind", ("missing", "duplicate"))
def test_incomplete_or_duplicate_query_summary_fails_closed(tmp_path: Path, kind: str) -> None:
    inputs = _sealed_inputs(tmp_path / "runtime")
    identity = _identity()
    snapshot = _snapshot(identity)
    if kind == "missing":
        object.__setattr__(snapshot, "query_digests", snapshot.query_digests[:-1])
        expected_reason = "missing_required_query"
    else:
        object.__setattr__(
            snapshot,
            "query_digests",
            (snapshot.query_digests[0], snapshot.query_digests[0], *snapshot.query_digests[1:]),
        )
        expected_reason = "duplicate_query"
    session = _FakeReadOnlySession((identity, identity), snapshot)

    with pytest.raises(CtpReadOnlyPreflightError) as caught:
        _run(inputs, _FakeFactory(session))

    assert caught.value.reason == expected_reason
    assert session.close_calls == 1
    _assert_zero_writes(session)


def test_session_exception_and_missing_factory_fail_closed(tmp_path: Path) -> None:
    inputs = _sealed_inputs(tmp_path / "runtime")
    identity = _identity()
    session = _FakeReadOnlySession(
        (identity, identity),
        _snapshot(identity),
        query_error=RuntimeError("untrusted provider failure"),
    )

    with pytest.raises(CtpReadOnlyPreflightError) as caught:
        _run(inputs, _FakeFactory(session))
    assert caught.value.reason == "read_only_session_failed"
    assert session.close_calls == 1
    _assert_zero_writes(session)

    with pytest.raises(CtpReadOnlyPreflightError) as no_factory:
        _run(inputs)
    assert no_factory.value.reason == "session_factory_required"


def test_public_route_rejects_caller_supplied_historical_time(tmp_path: Path) -> None:
    inputs = _sealed_inputs(tmp_path / "runtime")
    identity = _identity()
    factory = _FakeFactory(_FakeReadOnlySession((identity, identity), _snapshot(identity)))

    with pytest.raises(TypeError, match="unexpected keyword argument 'now'"):
        _run(inputs, factory, now=NOW - 1_000.0)
    assert factory.open_calls == 0


def test_session_deadline_is_shortest_receipt_or_profile_expiry(tmp_path: Path) -> None:
    inputs = _sealed_inputs(tmp_path / "runtime")
    inputs["test_profile"]["expires_at"] = NOW + 20.0
    identity = _identity()
    factory = _FakeFactory(_FakeReadOnlySession((identity, identity), _snapshot(identity)))

    _run(inputs, factory)

    assert factory.request.valid_until == NOW + 20.0


def test_verifier_expiry_prevents_session_factory_call(
    tmp_path: Path, ctp_clock: list[float]
) -> None:
    inputs = _sealed_inputs(tmp_path / "runtime")
    identity = _identity()
    factory = _FakeFactory(_FakeReadOnlySession((identity, identity), _snapshot(identity)))

    class _SlowReceiptVerifier:
        def verify(self, receipt, canonical_payload: bytes) -> bool:
            del receipt, canonical_payload
            ctp_clock[0] = NOW + 60.0
            return True

    with pytest.raises(CtpReadOnlyPreflightError) as caught:
        _run(inputs, factory, provider_receipt_verifier=_SlowReceiptVerifier())

    assert caught.value.reason == "provider_binding_validation_failed"
    assert factory.open_calls == 0


def test_factory_expiry_closes_session_and_rejects(tmp_path: Path, ctp_clock: list[float]) -> None:
    inputs = _sealed_inputs(tmp_path / "runtime")
    identity = _identity()
    session = _FakeReadOnlySession((identity, identity), _snapshot(identity))

    class _SlowFactory(_FakeFactory):
        def open_read_only(self, request) -> _FakeReadOnlySession:
            opened = super().open_read_only(request)
            ctp_clock[0] = NOW + 60.0
            return opened

    factory = _SlowFactory(session)
    with pytest.raises(CtpReadOnlyPreflightError) as caught:
        _run(inputs, factory)

    assert caught.value.reason == "session_deadline_expired"
    assert factory.open_calls == 1
    assert session.close_calls == 1
    assert session.identity_calls == 0
    _assert_zero_writes(session)


def test_read_expiry_closes_session_and_rejects(tmp_path: Path, ctp_clock: list[float]) -> None:
    inputs = _sealed_inputs(tmp_path / "runtime")
    identity = _identity()

    class _SlowReadSession(_FakeReadOnlySession):
        def read_query_snapshot(self) -> CtpReadOnlyQuerySnapshot:
            snapshot = super().read_query_snapshot()
            ctp_clock[0] = NOW + 60.0
            return snapshot

    session = _SlowReadSession((identity, identity), _snapshot(identity))
    with pytest.raises(CtpReadOnlyPreflightError) as caught:
        _run(inputs, _FakeFactory(session))

    assert caught.value.reason == "session_deadline_expired"
    assert session.close_calls == 1
    _assert_zero_writes(session)


def test_wall_clock_rewind_cannot_extend_session_deadline(
    tmp_path: Path, ctp_clock: list[float], monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = _sealed_inputs(tmp_path / "runtime")
    identity = _identity()
    monotonic_clock = [1_000.0]
    monkeypatch.setattr(ctp_preflight.time, "monotonic", lambda: monotonic_clock[0])

    class _RewindingSession(_FakeReadOnlySession):
        def read_query_snapshot(self) -> CtpReadOnlyQuerySnapshot:
            snapshot = super().read_query_snapshot()
            ctp_clock[0] = NOW - 1_000.0
            monotonic_clock[0] = 1_060.0
            return snapshot

    session = _RewindingSession((identity, identity), _snapshot(identity))
    with pytest.raises(CtpReadOnlyPreflightError) as caught:
        _run(inputs, _FakeFactory(session))

    assert caught.value.reason == "session_deadline_expired"
    assert session.close_calls == 1
    _assert_zero_writes(session)


def test_close_expiry_rejects_preflight_result(tmp_path: Path, ctp_clock: list[float]) -> None:
    inputs = _sealed_inputs(tmp_path / "runtime")
    identity = _identity()

    class _SlowCloseSession(_FakeReadOnlySession):
        def close_read_only(self) -> None:
            super().close_read_only()
            ctp_clock[0] = NOW + 60.0

    session = _SlowCloseSession((identity, identity), _snapshot(identity))
    with pytest.raises(CtpReadOnlyPreflightError) as caught:
        _run(inputs, _FakeFactory(session))

    assert caught.value.reason == "session_deadline_expired"
    assert session.close_calls == 1
    _assert_zero_writes(session)


def test_read_attribute_failure_still_closes_session_once(tmp_path: Path) -> None:
    inputs = _sealed_inputs(tmp_path / "runtime")
    identity = _identity()

    class _BrokenAttributeSession(_FakeReadOnlySession):
        def __getattribute__(self, name):
            if name == "read_identity":
                raise RuntimeError("untrusted SDK attribute error")
            return super().__getattribute__(name)

    session = _BrokenAttributeSession((identity, identity), _snapshot(identity))
    with pytest.raises(CtpReadOnlyPreflightError) as caught:
        _run(inputs, _FakeFactory(session))

    assert caught.value.reason == "read_only_session_failed"
    assert session.close_calls == 1
    _assert_zero_writes(session)


def test_interrupted_read_still_closes_session_once(tmp_path: Path) -> None:
    inputs = _sealed_inputs(tmp_path / "runtime")
    identity = _identity()

    class _InterruptedSession(_FakeReadOnlySession):
        def read_query_snapshot(self) -> CtpReadOnlyQuerySnapshot:
            self.snapshot_calls += 1
            raise KeyboardInterrupt

    session = _InterruptedSession((identity, identity), _snapshot(identity))
    with pytest.raises(KeyboardInterrupt):
        _run(inputs, _FakeFactory(session))

    assert session.identity_calls == 1
    assert session.snapshot_calls == 1
    assert session.close_calls == 1
    _assert_zero_writes(session)


def test_public_route_rejects_legacy_handbuilt_observation_signature() -> None:
    with pytest.raises(TypeError):
        run_ctp_simnow_readonly_preflight(object(), object())  # type: ignore[call-arg]


def test_module_imports_no_ctp_sdk_or_backtrader_framework() -> None:
    program = """
import sys
import backtrader_runtime.ctp_preflight
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
