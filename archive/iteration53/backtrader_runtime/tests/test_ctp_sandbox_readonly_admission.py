"""Tests for the config-first CTP SimNow sandbox read-only boundary."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
from typing import Any, Optional, Tuple

import pytest

import backtrader_runtime.config as runtime_config
import backtrader_runtime.credential_resolver as credential_resolver
import backtrader_runtime.ctp_front_pair_probe as front_pair_probe
import backtrader_runtime.ctp_sandbox_readonly_admission as sandbox_admission
import backtrader_runtime.ctp_simnow_readonly_runtime as readonly_runtime
from backtrader_runtime import (
    RegisteredRuntime,
    RuntimeRegistry,
    RuntimeProfile,
    load_runtime_config,
    resolve_runtime_config,
)
from backtrader_runtime.ctp_preflight import (
    CTP_PROVIDER,
    REQUIRED_CTP_READ_ONLY_QUERIES,
    CtpReadOnlyQuerySnapshot,
    CtpReadOnlySessionIdentity,
    CtpReadOnlySessionRequest,
)
from backtrader_runtime.ctp_sandbox_readonly_admission import (
    CtpSandboxReadOnlyAdmissionError,
    CtpSandboxReadOnlyRegistration,
    admit_ctp_simnow_sandbox_readonly,
    require_ctp_sandbox_readonly_runtime_contract,
)
from backtrader_runtime.ctp_simnow_readonly_runtime import CtpSimNowReadOnlyRuntimeError
from backtrader_runtime.ctp_simnow_operator import CtpSimNowConfigReadOnlyBinding
import backtrader_runtime.inventory as runtime_inventory
from backtrader_runtime.inventory import iteration41_runtime_registry


NOW = 1_700_400_000.0
SECRET_REF = "os_secret_store:iteration41.ctp.simnow.readonly"


@pytest.fixture(autouse=True)
def _isolate_private_config_security(monkeypatch: pytest.MonkeyPatch) -> None:
    # Config file permission contracts have dedicated platform tests. These
    # synthetic routing tests use placeholder credential fields only.
    monkeypatch.setattr(runtime_config, "_require_private_config_security", lambda *a, **k: None)


@pytest.fixture(autouse=True)
def sandbox_clock(monkeypatch: pytest.MonkeyPatch) -> tuple[list[float], list[float]]:
    """Keep request expiry deterministic without granting a caller time control."""

    wall_clock = [NOW]
    monotonic_clock = [1_000.0]
    monkeypatch.setattr(sandbox_admission.time, "time", lambda: wall_clock[0])
    monkeypatch.setattr(sandbox_admission.time, "monotonic", lambda: monotonic_clock[0])
    return wall_clock, monotonic_clock


def _write_config(
    runtime_dir: Path,
    *,
    parameters: str = "{}",
) -> None:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    (runtime_dir / "config.yaml").write_text(
        """config_schema_version: 4
strategy:
  id: example.ctp.sandbox_readonly
runtime:
  mode: simulation
  preset: sandbox
parameters: {parameters}
secrets_ref: {secret_ref}
""".format(
            parameters=parameters,
            secret_ref=SECRET_REF,
        ),
        encoding="utf-8",
    )


def _sealed_inputs(
    runtime_dir: Path,
    *,
    parameter_keys: Tuple[str, ...] = (),
    parameters: str = "{}",
) -> dict[str, Any]:
    _write_config(runtime_dir, parameters=parameters)
    runtime_registration = RegisteredRuntime(
        runtime_dir=runtime_dir,
        runtime_id="example.ctp.sandbox-readonly",
        strategy_id="example.ctp.sandbox_readonly",
        allowed_presets=("sandbox",),
        allowed_parameter_keys=parameter_keys,
        allowed_secrets_refs=(SECRET_REF,),
        available_capabilities=(),
        sandbox_write_policy="deny",
        approval_receipt_digest=None,
    )
    registry = RuntimeRegistry(
        (runtime_registration,),
        registry_id="iteration41.ctp-sandbox-readonly-test",
    )
    effective = resolve_runtime_config(
        load_runtime_config(runtime_dir, registry=registry),
        registry,
    )
    admission_registration = CtpSandboxReadOnlyRegistration(
        runtime_registration=runtime_registration,
        environment="simnow_set2",
        sdk_profile="set2_7x24",
        account_fingerprint_sha256="b" * 64,
        allowed_secrets_ref=SECRET_REF,
        instrument_id="rb2401",
        exchange_id="SHFE",
        hedge_flag="1",
        td_front="tcp://180.168.146.187:10130",
        md_front="tcp://180.168.146.187:10131",
        session_ttl_seconds=45.0,
    )
    return {
        "admission_registration": admission_registration,
        "effective": effective,
        "registry": registry,
        "runtime_registration": runtime_registration,
    }


def _profile_sealed_inputs(
    runtime_dir: Path,
    *,
    profile_overrides: Optional[dict[str, Any]] = None,
    admission_secret_ref: str = SECRET_REF,
    parameters: str = "{}",
    extra_profiles: Tuple[RuntimeProfile, ...] = (),
) -> dict[str, Any]:
    """Resolve a synthetic profile-scoped sandbox route for boundary tests."""

    runtime_dir.mkdir(parents=True, exist_ok=True)
    (runtime_dir / "config.yaml").write_text(
        """config_schema_version: 4
strategy:
  id: example.ctp.sandbox_readonly
runtime:
  mode: simulation
  preset: sandbox
parameters: {parameters}
secrets_ref: config_yaml
ctp_simnow:
  front_pairs:
    - md_front: tcp://192.0.2.11:10111
      td_front: tcp://192.0.2.10:10101
  instrument_id: rb2401
  exchange_id: SHFE
  hedge_flag: '1'
  broker_id: '9999'
  user_id: synthetic-user
  password: synthetic-password
  app_id: synthetic-app
  auth_code: synthetic-auth
""".format(
            parameters=parameters
        ),
        encoding="utf-8",
    )
    profile_values: dict[str, Any] = {
        "mode": "simulation",
        "preset": "sandbox",
        "allowed_parameter_keys": (),
        "allowed_secrets_refs": ("config_yaml",),
        "available_capabilities": (),
        "approval_receipt_digest": None,
        "runner_module": None,
        "runner_entrypoint": "run_runtime",
        "capability_modules": (),
        "offline_managed_execution": False,
        "sandbox_write_policy": "deny",
    }
    profile_values.update(profile_overrides or {})
    profile = RuntimeProfile(**profile_values)
    runtime_registration = RegisteredRuntime(
        runtime_dir=runtime_dir,
        runtime_id="synthetic.ctp.profile-sandbox",
        strategy_id="example.ctp.sandbox_readonly",
        allowed_presets=(),
        profiles=(profile,) + extra_profiles,
        unavailable_mode_profiles=(
            runtime_inventory.UnavailableModeProfile(
                mode="live",
                preset="managed_live_direct",
                reason="managed_live_direct_profile_unavailable",
            ),
        ),
    )
    registry = RuntimeRegistry(
        (runtime_registration,),
        ctp_simnow_readonly_bindings=(
            CtpSimNowConfigReadOnlyBinding(runtime_id=runtime_registration.runtime_id),
        ),
        registry_id="synthetic.ctp.profile-sandbox-test",
    )
    effective = resolve_runtime_config(
        load_runtime_config(runtime_dir, registry=registry),
        registry,
    )
    admission_registration = CtpSandboxReadOnlyRegistration(
        runtime_registration=runtime_registration,
        environment="simnow",
        sdk_profile="config_front_pair",
        account_fingerprint_sha256=hashlib.sha256(b"9999:synthetic-user").hexdigest(),
        allowed_secrets_ref=(
            "config_yaml" if admission_secret_ref == SECRET_REF else admission_secret_ref
        ),
        instrument_id="rb2401",
        exchange_id="SHFE",
        hedge_flag="1",
        td_front="tcp://192.0.2.10:10101",
        md_front="tcp://192.0.2.11:10111",
        session_ttl_seconds=45.0,
    )
    return {
        "admission_registration": admission_registration,
        "effective": effective,
        "profile": profile,
        "registry": registry,
        "runtime_registration": runtime_registration,
    }


def _identity(
    *,
    environment: str = "simnow_set2",
    account_fingerprint_sha256: str = "b" * 64,
    generation: int = 7,
) -> CtpReadOnlySessionIdentity:
    return CtpReadOnlySessionIdentity(
        provider=CTP_PROVIDER,
        environment=environment,
        account_fingerprint_sha256=account_fingerprint_sha256,
        trading_day="20260923",
        connection_generation=generation,
    )


def _snapshot(
    identity: CtpReadOnlySessionIdentity,
    *,
    native_certificate_sha256: Optional[str] = None,
    rate_exchange_scopes: Tuple[Tuple[str, str], ...] = (),
) -> CtpReadOnlyQuerySnapshot:
    return CtpReadOnlyQuerySnapshot.from_query_digests(
        identity,
        tuple(
            (name, hashlib.sha256(name.encode("ascii")).hexdigest())
            for name in REQUIRED_CTP_READ_ONLY_QUERIES
        ),
        native_certificate_sha256=native_certificate_sha256,
        rate_exchange_scopes=rate_exchange_scopes,
    )


class _FakeReadOnlySession:
    def __init__(
        self,
        identities: Tuple[CtpReadOnlySessionIdentity, ...],
        snapshot: Optional[CtpReadOnlyQuerySnapshot],
    ) -> None:
        self._identities = identities
        self._snapshot = snapshot
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
        self.request: Optional[CtpReadOnlySessionRequest] = None

    def open_read_only(self, request: CtpReadOnlySessionRequest) -> _FakeReadOnlySession:
        self.open_calls += 1
        self.request = request
        return self.session


class _UntouchedFactory:
    """Fails if the admission boundary reads its factory attribute too early."""

    def __init__(self) -> None:
        self.touches = 0

    @property
    def open_read_only(self):
        self.touches += 1
        raise AssertionError("the session factory must not be touched")


def _run(inputs: dict[str, Any], factory: Any):
    return admit_ctp_simnow_sandbox_readonly(
        effective=inputs["effective"],
        registry=inputs["registry"],
        admission_registration=inputs["admission_registration"],
        session_factory=factory,
    )


def _assert_zero_writes(session: _FakeReadOnlySession) -> None:
    assert session.forbidden_calls == {"order": 0, "cancel": 0, "settlement": 0, "arm": 0}


def test_sealed_exact_simnow_scope_returns_non_authority_read_only_observation(
    tmp_path: Path,
) -> None:
    inputs = _sealed_inputs(tmp_path / "runtime")
    identity = _identity()
    session = _FakeReadOnlySession((identity, identity), _snapshot(identity))
    factory = _FakeFactory(session)

    observation = _run(inputs, factory)

    assert factory.open_calls == 1
    assert type(factory.request) is CtpReadOnlySessionRequest
    assert factory.request.provider == CTP_PROVIDER
    assert factory.request.environment == "simnow_set2"
    assert factory.request.account_fingerprint_sha256 == "b" * 64
    assert factory.request.valid_until == NOW + 45.0
    assert tuple(factory.request.__dataclass_fields__) == (
        "provider",
        "environment",
        "account_fingerprint_sha256",
        "valid_until",
    )
    assert (observation.sdk_profile, observation.instrument_id, observation.exchange_id) == (
        "set2_7x24",
        "rb2401",
        "SHFE",
    )
    assert observation.hedge_flag == "1"
    assert observation.native_certificate_sha256 is None
    assert observation.native_certificate_provenance == "LOCAL_ONLY"
    assert observation.provider_preflight_started is False
    assert observation.approval_required is False
    assert observation.account_acceptance_established is False
    assert observation.execution_authorized is False
    assert observation.external_writes_authorized is False
    assert observation.external_write_requests == 0
    assert observation.as_public_dict()["native_certificate_provenance"] == "LOCAL_ONLY"
    assert "b" * 64 not in repr(inputs["admission_registration"])
    assert "b" * 64 not in repr(factory.request)
    assert "b" * 64 not in repr(observation)
    assert "b" * 64 not in repr(observation.query_snapshot)
    with pytest.raises(TypeError, match="non-authority"):
        bool(observation)

    assert session.identity_calls == 2
    assert session.snapshot_calls == 1
    assert session.close_calls == 1
    _assert_zero_writes(session)


def test_unsealed_or_cross_registry_config_is_rejected_before_factory_touch(tmp_path: Path) -> None:
    inputs = _sealed_inputs(tmp_path / "runtime")
    untouched = _UntouchedFactory()

    inputs["effective"] = replace(inputs["effective"])
    with pytest.raises(CtpSandboxReadOnlyAdmissionError) as unsealed:
        _run(inputs, untouched)
    assert unsealed.value.reason == "effective_config_mismatch"
    assert untouched.touches == 0

    inputs = _sealed_inputs(tmp_path / "other-runtime")
    inputs["registry"] = RuntimeRegistry(
        (inputs["runtime_registration"],),
        registry_id="different-registry-object",
    )
    untouched = _UntouchedFactory()
    with pytest.raises(CtpSandboxReadOnlyAdmissionError) as cross_registry:
        _run(inputs, untouched)
    assert cross_registry.value.reason == "effective_config_mismatch"
    assert untouched.touches == 0


def test_contract_validator_returns_only_the_normalized_code_owned_registration(
    tmp_path: Path,
) -> None:
    inputs = _sealed_inputs(tmp_path / "runtime")

    validated = require_ctp_sandbox_readonly_runtime_contract(
        inputs["effective"],
        inputs["registry"],
        inputs["admission_registration"],
    )

    assert type(validated) is CtpSandboxReadOnlyRegistration
    assert validated is not inputs["admission_registration"]
    assert (
        validated.environment,
        validated.sdk_profile,
        validated.instrument_id,
        validated.exchange_id,
        validated.hedge_flag,
    ) == ("simnow_set2", "set2_7x24", "rb2401", "SHFE", "1")
    assert validated.allowed_secrets_ref == SECRET_REF


def test_exact_profile_sandbox_runs_through_zero_write_readonly_admission(
    tmp_path: Path,
) -> None:
    inputs = _profile_sealed_inputs(tmp_path / "profile-runtime")
    validated = require_ctp_sandbox_readonly_runtime_contract(
        inputs["effective"],
        inputs["registry"],
        inputs["admission_registration"],
    )
    identity = _identity(
        environment="simnow",
        account_fingerprint_sha256=inputs["admission_registration"].account_fingerprint_sha256,
    )
    session = _FakeReadOnlySession((identity, identity), _snapshot(identity))
    factory = _FakeFactory(session)

    assert inputs["effective"].profile is inputs["profile"]
    assert validated.runtime_registration is inputs["runtime_registration"]
    observation = _run(inputs, factory)

    assert factory.open_calls == 1
    assert observation.sdk_profile == "config_front_pair"
    assert observation.instrument_id == "rb2401"
    assert observation.execution_authorized is False
    assert observation.external_writes_authorized is False
    _assert_zero_writes(session)


def test_exact_profile_credential_scope_is_narrowly_bound_without_secret_io(
    tmp_path: Path,
) -> None:
    inputs = _profile_sealed_inputs(tmp_path / "profile-runtime")
    binding = inputs["registry"].require_ctp_simnow_readonly_binding(
        inputs["runtime_registration"].runtime_id
    )
    selected = front_pair_probe.CtpConfiguredFrontPair(
        md_front="tcp://192.0.2.11:10111",
        td_front="tcp://192.0.2.10:10101",
    )
    _admission, scope = binding._route(
        inputs["effective"],
        inputs["registry"],
        selected_front_pair=selected,
        selected_config_index=0,
    )

    matched = credential_resolver._require_matching_scope(
        inputs["effective"],
        inputs["registry"],
        scope,
    )

    assert matched is not scope
    assert matched.secrets_ref == "config_yaml"
    assert matched.account_access == "sandbox_private_read"
    assert matched.mode == "simulation"
    assert matched.preset == "sandbox"


def test_profile_sandbox_composition_rejects_before_credentials_or_sdk(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _profile_sealed_inputs(tmp_path / "profile-runtime")
    object.__setattr__(inputs["profile"], "available_capabilities", ("execution",))

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        pytest.fail("profile-backed CTP dispatch reached credentials or SDK setup")

    monkeypatch.setattr(readonly_runtime, "resolve_runtime_credentials", forbidden)
    monkeypatch.setattr(readonly_runtime, "trusted_installed_capability_import_context", forbidden)
    monkeypatch.setattr(readonly_runtime, "admit_ctp_simnow_sandbox_readonly", forbidden)

    with pytest.raises(CtpSimNowReadOnlyRuntimeError) as caught:
        readonly_runtime.open_ctp_simnow_readonly_runtime(
            effective=inputs["effective"],
            registry=inputs["registry"],
            admission_registration=inputs["admission_registration"],
            credential_scope=None,
        )

    assert caught.value.reason == "runtime_admission_rejected"


@pytest.mark.parametrize(
    ("profile_overrides", "parameters", "admission_secret_ref"),
    (
        ({"allowed_parameter_keys": ("scope",)}, "{scope: rb9999}", SECRET_REF),
        ({"available_capabilities": ("execution",)}, "{}", SECRET_REF),
        ({"approval_receipt_digest": "a" * 64}, "{}", SECRET_REF),
        ({"runner_module": "tests.synthetic_profiles.private_reader"}, "{}", SECRET_REF),
        ({"capability_modules": ("bt_api_ctp",)}, "{}", SECRET_REF),
        (
            {
                "available_capabilities": ("execution", "risk", "monitor"),
                "approval_receipt_digest": "a" * 64,
                "sandbox_write_policy": "receipt_required",
            },
            "{}",
            SECRET_REF,
        ),
        ({}, "{}", "different_secret_ref"),
    ),
)
def test_profile_policy_contamination_rejects_before_factory_touch(
    tmp_path: Path,
    profile_overrides: dict[str, Any],
    parameters: str,
    admission_secret_ref: str,
) -> None:
    if admission_secret_ref == SECRET_REF:
        with pytest.raises(ValueError, match="exact sandbox-only runtime"):
            _profile_sealed_inputs(
                tmp_path / "profile-runtime",
                profile_overrides=profile_overrides,
                parameters=parameters,
            )
        return

    inputs = _profile_sealed_inputs(
        tmp_path / "profile-runtime",
        profile_overrides=profile_overrides,
        admission_secret_ref=admission_secret_ref,
        parameters=parameters,
    )
    untouched = _UntouchedFactory()

    with pytest.raises(CtpSandboxReadOnlyAdmissionError) as caught:
        _run(inputs, untouched)

    assert caught.value.reason == "runtime_policy_mismatch"
    assert untouched.touches == 0


def test_registry_rejects_ambiguous_profile_set_before_dispatch(tmp_path: Path) -> None:
    replay_profile = RuntimeProfile(
        mode="simulation",
        preset="replay",
        allowed_parameter_keys=(),
        allowed_secrets_refs=("none",),
        available_capabilities=(),
        approval_receipt_digest=None,
        runner_module=None,
        runner_entrypoint="run_runtime",
        capability_modules=(),
        offline_managed_execution=False,
        sandbox_write_policy="deny",
    )
    with pytest.raises(ValueError, match="exact sandbox-only runtime"):
        _profile_sealed_inputs(
            tmp_path / "profile-runtime",
            extra_profiles=(replay_profile,),
        )


@pytest.mark.parametrize("mutation", ("profile", "registration"))
def test_profile_seal_rejects_stale_profile_or_registration_before_factory_touch(
    tmp_path: Path,
    mutation: str,
) -> None:
    inputs = _profile_sealed_inputs(tmp_path / "profile-runtime")
    untouched = _UntouchedFactory()
    if mutation == "profile":
        object.__setattr__(inputs["profile"], "runner_module", "tests.synthetic_profiles.mutated")
    else:
        object.__setattr__(inputs["runtime_registration"], "runtime_id", "mutated.runtime")

    with pytest.raises(CtpSandboxReadOnlyAdmissionError) as caught:
        _run(inputs, untouched)

    assert caught.value.reason == "effective_config_mismatch"
    assert untouched.touches == 0


def test_config_cannot_expand_code_owned_native_query_scope_before_factory_touch(
    tmp_path: Path,
) -> None:
    inputs = _sealed_inputs(
        tmp_path / "runtime",
        parameter_keys=("instrument_id",),
        parameters="{instrument_id: rb9999}",
    )
    assert inputs["effective"].parameters["instrument_id"] == "rb9999"
    assert inputs["admission_registration"].instrument_id == "rb2401"
    untouched = _UntouchedFactory()

    with pytest.raises(CtpSandboxReadOnlyAdmissionError) as caught:
        _run(inputs, untouched)

    assert caught.value.reason == "runtime_policy_mismatch"
    assert untouched.touches == 0


def test_write_capable_registry_tampering_is_rejected_before_factory_touch(tmp_path: Path) -> None:
    inputs = _sealed_inputs(tmp_path / "runtime")
    object.__setattr__(inputs["runtime_registration"], "sandbox_write_policy", "receipt_required")
    untouched = _UntouchedFactory()

    with pytest.raises(CtpSandboxReadOnlyAdmissionError) as caught:
        _run(inputs, untouched)

    assert caught.value.reason == "runtime_policy_mismatch"
    assert untouched.touches == 0


@pytest.mark.parametrize(
    ("identity", "expected_reason"),
    (
        (_identity(environment="simnow_set1"), "session_environment_mismatch"),
        (_identity(account_fingerprint_sha256="f" * 64), "session_account_mismatch"),
    ),
)
def test_session_environment_or_account_mismatch_never_reaches_query(
    tmp_path: Path,
    identity: CtpReadOnlySessionIdentity,
    expected_reason: str,
) -> None:
    inputs = _sealed_inputs(tmp_path / "runtime")
    session = _FakeReadOnlySession((identity, identity), _snapshot(identity))

    with pytest.raises(CtpSandboxReadOnlyAdmissionError) as caught:
        _run(inputs, _FakeFactory(session))

    assert caught.value.reason == expected_reason
    assert session.identity_calls == 1
    assert session.snapshot_calls == 0
    assert session.close_calls == 1
    _assert_zero_writes(session)


def test_registration_rejects_production_or_wrong_sdk_profile_before_session_setup(
    tmp_path: Path,
) -> None:
    inputs = _sealed_inputs(tmp_path / "runtime")
    registration = inputs["admission_registration"]

    with pytest.raises(CtpSandboxReadOnlyAdmissionError) as production:
        replace(registration, environment="production")
    assert production.value.reason == "environment_not_simnow"

    with pytest.raises(CtpSandboxReadOnlyAdmissionError) as imprecise_environment:
        replace(registration, environment="simnow")
    assert imprecise_environment.value.reason == "environment_profile_mismatch"

    with pytest.raises(CtpSandboxReadOnlyAdmissionError) as unsupported_set:
        replace(registration, environment="simnow_set3")
    assert unsupported_set.value.reason == "environment_not_simnow"

    with pytest.raises(CtpSandboxReadOnlyAdmissionError) as wrong_profile:
        replace(registration, sdk_profile="set1_group1")
    assert wrong_profile.value.reason == "environment_profile_mismatch"

    with pytest.raises(CtpSandboxReadOnlyAdmissionError) as wrong_hedge_scope:
        replace(registration, hedge_flag="0")
    assert wrong_hedge_scope.value.reason == "invalid_registration"


def test_fake_snapshot_cannot_claim_native_certificate_provenance(tmp_path: Path) -> None:
    inputs = _sealed_inputs(tmp_path / "runtime")
    identity = _identity()
    observation = _run(
        inputs,
        _FakeFactory(_FakeReadOnlySession((identity, identity), _snapshot(identity))),
    )

    with pytest.raises(CtpSandboxReadOnlyAdmissionError) as caught:
        replace(
            observation,
            native_certificate_sha256="a" * 64,
            native_certificate_provenance="UNVERIFIED_DIGEST_ONLY",
        )

    assert caught.value.reason == "invalid_observation"

    with pytest.raises(CtpSandboxReadOnlyAdmissionError) as native_claim:
        replace(observation, native_certificate_provenance="NATIVE_CERTIFICATE")

    assert native_claim.value.reason == "invalid_observation"


def test_snapshot_certificate_digest_remains_unverified_metadata(tmp_path: Path) -> None:
    inputs = _sealed_inputs(tmp_path / "runtime")
    identity = _identity()
    native_certificate_sha256 = "c" * 64
    observation = _run(
        inputs,
        _FakeFactory(
            _FakeReadOnlySession(
                (identity, identity),
                _snapshot(
                    identity,
                    native_certificate_sha256=native_certificate_sha256,
                    rate_exchange_scopes=(
                        ("margin_rates", "unverified"),
                        ("commission_rates", "exact"),
                    ),
                ),
            )
        ),
    )

    assert observation.native_certificate_sha256 == native_certificate_sha256
    assert observation.native_certificate_provenance == "UNVERIFIED_DIGEST_ONLY"
    assert observation.query_snapshot.rate_exchange_scopes == (
        ("commission_rates", "exact"),
        ("margin_rates", "unverified"),
    )
    assert observation.as_public_dict()["query_snapshot"]["rate_exchange_scopes"] == (
        ("commission_rates", "exact"),
        ("margin_rates", "unverified"),
    )
    assert observation.account_acceptance_established is False
    assert observation.execution_authorized is False


def test_default_ctp_sandbox_registration_has_no_execution_authority() -> None:
    """The default config route is private-read only and has no runner or write grant."""

    registry = iteration41_runtime_registry()
    private_registrations = (
        runtime_inventory.ITERATION41_013_3_CTP_PRIVATE_READONLY_REGISTRATION,
        runtime_inventory.ITERATION41_007_CTP_PRIVATE_READONLY_REGISTRATION,
    )
    assert all(registration in registry.registrations for registration in private_registrations)
    for registration in private_registrations:
        assert registration.allowed_presets == ()
        assert registration.allowed_secrets_refs == ("none",)
        assert tuple((profile.mode, profile.preset) for profile in registration.profiles) == (
            ("simulation", "sandbox"),
        )
        assert registration.profiles[0].allowed_secrets_refs == ("config_yaml",)
        assert registration.profiles[0].available_capabilities == ()
        assert registration.profiles[0].runner_module is None
        assert registration.profiles[0].sandbox_write_policy == "deny"
        assert registration.available_capabilities == ()
        assert registration.runner_module is None
        assert registration.capability_modules == ()
        assert registration.sandbox_write_policy == "deny"
        assert not registration.offline_managed_execution
    assert registry.ctp_simnow_readonly_bindings == (
        runtime_inventory.ITERATION41_013_3_CTP_PRIVATE_READONLY_BINDING,
        runtime_inventory.ITERATION41_007_CTP_PRIVATE_READONLY_BINDING,
    )
