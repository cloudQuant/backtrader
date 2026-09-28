"""Synthetic checks for exact mode/preset profiles on one runtime registration."""

from __future__ import annotations

import io
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from backtrader_runtime.cli import main
from backtrader_runtime.config import load_runtime_config
from backtrader_runtime.errors import RuntimeConfigError
from backtrader_runtime.policy import MANAGED_WRITE_CAPABILITIES
from backtrader_runtime.registry import (
    RegisteredRuntime,
    RuntimeProfile,
    RuntimeRegistry,
    UnavailableModeProfile,
    bootstrap_runtime_config,
    resolve_runtime_config,
    require_effective_runtime_config_seal,
    select_bootstrap_preset,
)


STRATEGY_ID = "example.synthetic_profiles"
APPROVAL_DIGEST = "a" * 64


def _profile(
    mode: str,
    preset: str,
    *,
    parameter_keys: tuple[str, ...],
    secret_refs: tuple[str, ...],
    capabilities: tuple[str, ...] = (),
    approval: str | None = None,
    runner_module: str | None = None,
    capability_modules: tuple[str, ...] = (),
) -> RuntimeProfile:
    return RuntimeProfile(
        mode=mode,
        preset=preset,
        allowed_parameter_keys=parameter_keys,
        allowed_secrets_refs=secret_refs,
        available_capabilities=capabilities,
        approval_receipt_digest=approval,
        runner_module=runner_module,
        runner_entrypoint="run_runtime",
        capability_modules=capability_modules,
        offline_managed_execution=False,
        sandbox_write_policy="deny",
    )


def _sandbox_profile() -> RuntimeProfile:
    return _profile(
        "simulation",
        "sandbox",
        parameter_keys=("sandbox_case",),
        secret_refs=("none",),
        runner_module="tests.synthetic_profiles.sandbox_runner",
    )


def _sandbox_private_profile() -> RuntimeProfile:
    return _profile(
        "simulation",
        "sandbox",
        parameter_keys=(),
        secret_refs=("config_yaml",),
    )


def _replay_profile(
    *,
    runner_module: str | None = "tests.synthetic_profiles.replay_runner",
    capabilities: tuple[str, ...] = (),
    capability_modules: tuple[str, ...] = (),
) -> RuntimeProfile:
    return _profile(
        "simulation",
        "replay",
        parameter_keys=("replay_case",),
        secret_refs=("none",),
        capabilities=capabilities,
        runner_module=runner_module,
        capability_modules=capability_modules,
    )


def _live_profile(
    *,
    capabilities: tuple[str, ...] = MANAGED_WRITE_CAPABILITIES,
    approval: str | None = APPROVAL_DIGEST,
) -> RuntimeProfile:
    return _profile(
        "live",
        "managed_live_direct",
        parameter_keys=("live_case",),
        secret_refs=("runtime_secrets",),
        capabilities=capabilities,
        approval=approval,
        runner_module="tests.synthetic_profiles.live_writer",
        capability_modules=("bt_api_ctp",),
    )


def _registry(
    runtime_dir: Path,
    profiles: tuple[RuntimeProfile, ...],
    *,
    unavailable: tuple[UnavailableModeProfile, ...] = (),
) -> RuntimeRegistry:
    registration = RegisteredRuntime(
        runtime_dir=runtime_dir,
        strategy_id=STRATEGY_ID,
        runtime_id="synthetic.profiles",
        allowed_presets=(),
        profiles=profiles,
        unavailable_mode_profiles=unavailable,
    )
    return RuntimeRegistry((registration,), registry_id="test.synthetic.profiles")


def _write_config(
    runtime_dir: Path,
    *,
    mode: str,
    preset: str,
    parameter_key: str,
    secrets_ref: str,
) -> None:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    (runtime_dir / "config.yaml").write_text(
        "config_schema_version: 4\n"
        "strategy:\n"
        "  id: {strategy_id}\n"
        "runtime:\n"
        "  mode: {mode}\n"
        "  preset: {preset}\n"
        "parameters:\n"
        "  {parameter_key}: sample\n"
        "secrets_ref: {secrets_ref}\n".format(
            strategy_id=STRATEGY_ID,
            mode=mode,
            preset=preset,
            parameter_key=parameter_key,
            secrets_ref=secrets_ref,
        ),
        encoding="utf-8",
    )


def test_two_profiles_resolve_independently_from_one_registration_and_file(
    tmp_path: Path,
) -> None:
    registry = _registry(tmp_path, (_sandbox_profile(), _live_profile()))
    registration = registry.require_runtime_dir(tmp_path)

    _write_config(
        tmp_path,
        mode="simulation",
        preset="sandbox",
        parameter_key="sandbox_case",
        secrets_ref="none",
    )
    sandbox = resolve_runtime_config(load_runtime_config(tmp_path, registry=registry), registry)

    assert sandbox.registration is registration
    assert sandbox.profile is registration.profile_for("simulation", "sandbox")
    assert sandbox.profile is not None
    assert sandbox.profile.runner_module == "tests.synthetic_profiles.sandbox_runner"
    assert sandbox.profile.allowed_secrets_refs == ("none",)
    assert sandbox.required_capabilities == ()
    assert sandbox.requires_approval is False
    assert sandbox.allows_production_writes is False
    assert sandbox.as_public_dict()["profile"] == {"mode": "simulation", "preset": "sandbox"}

    _write_config(
        tmp_path,
        mode="live",
        preset="managed_live_direct",
        parameter_key="live_case",
        secrets_ref="runtime_secrets",
    )
    live = resolve_runtime_config(load_runtime_config(tmp_path, registry=registry), registry)

    assert live.registration is registration
    assert live.profile is registration.profile_for("live", "managed_live_direct")
    assert live.profile is not None
    assert live.profile.runner_module == "tests.synthetic_profiles.live_writer"
    assert live.profile.allowed_secrets_refs == ("runtime_secrets",)
    assert live.profile.available_capabilities == MANAGED_WRITE_CAPABILITIES
    assert live.required_capabilities == MANAGED_WRITE_CAPABILITIES
    assert live.requires_approval is True
    assert live.allows_production_writes is True
    assert live.as_public_dict()["profile_dispatch_available"] is False
    assert live.as_public_dict()["order_route"] is None
    assert live.as_public_dict()["account_access"] is None
    assert live.as_public_dict()["allows_external_writes"] is False
    assert live.as_public_dict()["allows_production_writes"] is False
    assert live.effective_digest != sandbox.effective_digest

    # Legacy fields stay closed; selecting a profile never overlays them.
    assert registration.allowed_presets == ()
    assert registration.available_capabilities == ()
    assert registration.approval_receipt_digest is None
    assert registration.runner_module is None
    assert registration.capability_modules == ()


def test_offline_replay_profile_dispatches_the_sealed_selected_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backtrader_runtime.runner import resolve_runner_effective_config

    module_name = "tests.synthetic_profiles.replay_runner"
    calls = []
    module = types.ModuleType(module_name)

    def run_runtime(runtime_dir, *, registry, effective, runtime_directory=None):
        resolved = resolve_runner_effective_config(runtime_dir, registry, effective=effective)
        calls.append(
            (
                resolved.profile.mode,
                resolved.profile.preset,
                resolved.profile.runner_module,
                resolved.profile.digest,
            )
        )
        return {"status": "SYNTHETIC_REPLAY_PASS"}

    module.run_runtime = run_runtime  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, module_name, module)
    registry = _registry(tmp_path, (_replay_profile(),))
    _write_config(
        tmp_path,
        mode="simulation",
        preset="replay",
        parameter_key="replay_case",
        secrets_ref="none",
    )
    effective = resolve_runtime_config(load_runtime_config(tmp_path, registry=registry), registry)

    assert effective.profile_dispatch_available is True
    assert effective.as_public_dict()["profile_dispatch_available"] is True
    stdout, stderr = io.StringIO(), io.StringIO()
    status = main(
        ["run", "--strategy-dir", str(tmp_path)],
        registry=registry,
        environ={},
        stdout=stdout,
        stderr=stderr,
    )

    assert status == 0, stderr.getvalue()
    assert json.loads(stdout.getvalue())["status"] == "completed"
    assert calls == [
        (
            "simulation",
            "replay",
            module_name,
            effective.profile.digest,
        )
    ]


@pytest.mark.parametrize(
    ("profile", "mode", "preset", "parameter_key", "secrets_ref", "expected_reason"),
    (
        (_sandbox_profile(), "simulation", "sandbox", "sandbox_case", "none", "profile_dispatch_unavailable"),
        (
            _replay_profile(runner_module=None),
            "simulation",
            "replay",
            "replay_case",
            "none",
            "profile_dispatch_unavailable",
        ),
        (
            _replay_profile(capabilities=("execution",)),
            "simulation",
            "replay",
            "replay_case",
            "none",
            "profile_dispatch_unavailable",
        ),
        (
            _replay_profile(capability_modules=("bt_api_execution",)),
            "simulation",
            "replay",
            "replay_case",
            "none",
            "profile_dispatch_unavailable",
        ),
        (
            _live_profile(),
            "live",
            "managed_live_direct",
            "live_case",
            "runtime_secrets",
            "live_execution_admission_required",
        ),
    ),
)
def test_ineligible_profile_dispatch_stops_before_runner_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    profile: RuntimeProfile,
    mode: str,
    preset: str,
    parameter_key: str,
    secrets_ref: str,
    expected_reason: str,
) -> None:
    from backtrader_runtime import runner

    registry = _registry(tmp_path, (profile,))
    _write_config(
        tmp_path,
        mode=mode,
        preset=preset,
        parameter_key=parameter_key,
        secrets_ref=secrets_ref,
    )
    effective = resolve_runtime_config(load_runtime_config(tmp_path, registry=registry), registry)
    monkeypatch.setattr(
        runner,
        "_loaded_registered_runner",
        lambda *args, **kwargs: pytest.fail("ineligible profile runner was imported"),
    )

    if expected_reason == "profile_dispatch_unavailable":
        assert effective.profile_dispatch_available is False
    with pytest.raises(RuntimeConfigError) as caught:
        runner.dispatch_registered_runtime(effective, registry)

    assert caught.value.reason == expected_reason


def test_profile_config_cannot_select_an_unregistered_mode_preset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = _registry(tmp_path, (_replay_profile(),))
    _write_config(
        tmp_path,
        mode="backtest",
        preset="local_backtest",
        parameter_key="replay_case",
        secrets_ref="none",
    )
    monkeypatch.setattr(
        "backtrader_runtime.runner._loaded_registered_runner",
        lambda *args, **kwargs: pytest.fail("unregistered profile runner was imported"),
    )

    with pytest.raises(RuntimeConfigError) as caught:
        resolve_runtime_config(load_runtime_config(tmp_path, registry=registry), registry)

    assert caught.value.reason == "profile_not_registered"


def test_profile_dispatch_rejects_a_forged_effective_before_runner_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dataclasses import replace

    from backtrader_runtime import runner

    imported = []
    attacker_name = "tests.synthetic_profiles.attacker"
    attacker = types.ModuleType(attacker_name)
    attacker.run_runtime = lambda *args, **kwargs: imported.append(True)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, attacker_name, attacker)
    registered_profile = _replay_profile()
    registry = _registry(tmp_path, (registered_profile,))
    _write_config(
        tmp_path,
        mode="simulation",
        preset="replay",
        parameter_key="replay_case",
        secrets_ref="none",
    )
    effective = resolve_runtime_config(load_runtime_config(tmp_path, registry=registry), registry)
    forged = replace(effective, profile=replace(registered_profile, runner_module=attacker_name))
    monkeypatch.setattr(
        runner,
        "_loaded_registered_runner",
        lambda *args, **kwargs: pytest.fail("forged profile runner was imported"),
    )

    with pytest.raises(RuntimeConfigError) as caught:
        runner.dispatch_registered_runtime(forged, registry)

    assert caught.value.reason == "effective_config_mismatch"
    assert imported == []


def test_profile_secrets_parameters_approval_and_capabilities_do_not_inherit(
    tmp_path: Path,
) -> None:
    registry = _registry(tmp_path, (_sandbox_profile(), _live_profile()))

    _write_config(
        tmp_path,
        mode="simulation",
        preset="sandbox",
        parameter_key="live_case",
        secrets_ref="runtime_secrets",
    )
    with pytest.raises(RuntimeConfigError) as sandbox_rejected:
        resolve_runtime_config(load_runtime_config(tmp_path, registry=registry), registry)
    assert sandbox_rejected.value.reason == "parameter_not_registered"

    _write_config(
        tmp_path,
        mode="simulation",
        preset="sandbox",
        parameter_key="sandbox_case",
        secrets_ref="runtime_secrets",
    )
    with pytest.raises(RuntimeConfigError) as sandbox_secret_rejected:
        resolve_runtime_config(load_runtime_config(tmp_path, registry=registry), registry)
    assert sandbox_secret_rejected.value.reason == "secrets_ref_not_registered"

    _write_config(
        tmp_path,
        mode="live",
        preset="managed_live_direct",
        parameter_key="live_case",
        secrets_ref="none",
    )
    with pytest.raises(RuntimeConfigError) as live_rejected:
        resolve_runtime_config(load_runtime_config(tmp_path, registry=registry), registry)
    assert live_rejected.value.reason == "secrets_ref_not_registered"

    no_approval_registry = _registry(
        tmp_path,
        (_sandbox_profile(), _live_profile(approval=None)),
    )
    _write_config(
        tmp_path,
        mode="live",
        preset="managed_live_direct",
        parameter_key="live_case",
        secrets_ref="runtime_secrets",
    )
    with pytest.raises(RuntimeConfigError) as approval_rejected:
        resolve_runtime_config(
            load_runtime_config(tmp_path, registry=no_approval_registry), no_approval_registry
        )
    assert approval_rejected.value.reason == "approval_receipt_missing"

    no_capabilities_registry = _registry(
        tmp_path,
        (_sandbox_profile(), _live_profile(capabilities=())),
    )
    with pytest.raises(RuntimeConfigError) as capabilities_rejected:
        resolve_runtime_config(
            load_runtime_config(tmp_path, registry=no_capabilities_registry),
            no_capabilities_registry,
        )
    assert capabilities_rejected.value.reason == "required_capability_not_declared"


def test_unavailable_gate_cannot_be_shadowed_by_an_available_profile(tmp_path: Path) -> None:
    live = _live_profile()
    unavailable = UnavailableModeProfile(
        mode="live",
        preset="managed_live_direct",
        reason="live_profile_not_enabled",
    )
    with pytest.raises(ValueError, match="cannot also be an available profile"):
        RegisteredRuntime(
            runtime_dir=tmp_path,
            strategy_id=STRATEGY_ID,
            allowed_presets=(),
            profiles=(_sandbox_profile(), live),
            unavailable_mode_profiles=(unavailable,),
        )

    registry = _registry(
        tmp_path,
        (_sandbox_profile(),),
        unavailable=(unavailable,),
    )
    _write_config(
        tmp_path,
        mode="live",
        preset="managed_live_direct",
        parameter_key="live_case",
        secrets_ref="runtime_secrets",
    )
    with pytest.raises(RuntimeConfigError) as rejected:
        resolve_runtime_config(load_runtime_config(tmp_path, registry=registry), registry)
    assert rejected.value.reason == "live_profile_not_enabled"


def test_profile_cli_keeps_unavailable_live_before_any_dispatch(
    tmp_path: Path, monkeypatch
) -> None:
    unavailable = UnavailableModeProfile(
        mode="live",
        preset="managed_live_direct",
        reason="live_profile_not_enabled",
    )
    registry = _registry(
        tmp_path,
        (_sandbox_profile(),),
        unavailable=(unavailable,),
    )
    _write_config(
        tmp_path,
        mode="live",
        preset="managed_live_direct",
        parameter_key="live_case",
        secrets_ref="runtime_secrets",
    )
    calls = []
    monkeypatch.setattr(
        "backtrader_runtime.cli.dispatch_registered_runtime",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    stdout, stderr = io.StringIO(), io.StringIO()

    status = main(
        ["run", "--strategy-dir", str(tmp_path), "--confirm-live"],
        registry=registry,
        environ={},
        stdout=stdout,
        stderr=stderr,
    )

    assert status == 2
    assert stdout.getvalue() == ""
    assert '"reason": "live_profile_not_enabled"' in stderr.getvalue()
    assert calls == []


def test_doctor_reports_profile_scoped_live_approval_and_capability_gaps(tmp_path: Path) -> None:
    registry = _registry(
        tmp_path,
        (_sandbox_profile(), _live_profile(approval=None, capabilities=())),
    )
    _write_config(
        tmp_path,
        mode="live",
        preset="managed_live_direct",
        parameter_key="live_case",
        secrets_ref="runtime_secrets",
    )
    stderr = io.StringIO()

    status = main(
        ["doctor", "--strategy-dir", str(tmp_path)],
        registry=registry,
        environ={},
        stdout=io.StringIO(),
        stderr=stderr,
    )

    assert status == 2
    payload = json.loads(stderr.getvalue())
    blocker_reasons = {blocker["reason"] for blocker in payload["diagnostic"]["blockers"]}
    assert blocker_reasons >= {"approval_receipt_missing", "required_capability_not_declared"}
    assert payload["diagnostic"]["operator_summary"]["profile_dispatch_available"] is False
    assert payload["diagnostic"]["operator_summary"]["admission_status"] == "blocked"
    assert payload["diagnostic"]["profile_dispatch_unavailable_reason"] == (
        "profile_dispatch_unavailable"
    )


def test_validate_and_doctor_do_not_expose_profile_route_or_write_authority(
    tmp_path: Path,
) -> None:
    registry = _registry(tmp_path, (_sandbox_profile(), _live_profile()))
    _write_config(
        tmp_path,
        mode="live",
        preset="managed_live_direct",
        parameter_key="live_case",
        secrets_ref="runtime_secrets",
    )
    stdout, stderr = io.StringIO(), io.StringIO()

    status = main(
        ["validate", "--strategy-dir", str(tmp_path)],
        registry=registry,
        environ={},
        stdout=stdout,
        stderr=stderr,
    )

    assert status == 0
    validated = json.loads(stdout.getvalue())
    assert validated["profile_dispatch_available"] is False
    assert validated["profile_dispatch_unavailable_reason"] == "profile_dispatch_unavailable"
    assert validated["order_route"] is None
    assert validated["account_access"] is None
    assert validated["allows_network"] is False
    assert validated["allows_external_writes"] is False
    assert validated["allows_production_writes"] is False

    stdout, stderr = io.StringIO(), io.StringIO()
    status = main(
        ["doctor", "--strategy-dir", str(tmp_path)],
        registry=registry,
        environ={},
        stdout=stdout,
        stderr=stderr,
    )
    assert status == 0
    diagnostic = json.loads(stdout.getvalue())["diagnostic"]
    assert diagnostic["next_actions"] == [
        {
            "action": "review_profile_dispatch",
            "field_path": "runtime.preset",
            "note": "profile validation is offline; profile-scoped dispatch is not enabled",
        }
    ]
    operator = diagnostic["operator_summary"]
    assert operator["destination"] == "profile_dispatch_unavailable"
    assert operator["write_boundary"] == "blocked_before_external_writes"
    assert operator["admission_status"] == "blocked"
    assert operator["profile_dispatch_available"] is False


def test_effective_profile_seal_detects_profile_mutation(tmp_path: Path) -> None:
    registry = _registry(tmp_path, (_sandbox_profile(), _live_profile()))
    _write_config(
        tmp_path,
        mode="live",
        preset="managed_live_direct",
        parameter_key="live_case",
        secrets_ref="runtime_secrets",
    )
    effective = resolve_runtime_config(load_runtime_config(tmp_path, registry=registry), registry)
    assert effective.profile is not None
    object.__setattr__(effective.profile, "runner_module", "tests.synthetic_profiles.mutated")

    with pytest.raises(RuntimeConfigError) as rejected:
        require_effective_runtime_config_seal(effective, registry)

    assert rejected.value.reason == "effective_config_mismatch"


def test_registry_snapshot_detects_profile_mutation_before_resolution(tmp_path: Path) -> None:
    registry = _registry(tmp_path, (_sandbox_profile(), _live_profile()))
    _write_config(
        tmp_path,
        mode="live",
        preset="managed_live_direct",
        parameter_key="live_case",
        secrets_ref="runtime_secrets",
    )
    loaded = load_runtime_config(tmp_path, registry=registry)
    registration = registry.require_runtime_dir(tmp_path)
    live_profile = registration.profile_for("live", "managed_live_direct")
    assert live_profile is not None
    object.__setattr__(live_profile, "approval_receipt_digest", None)

    with pytest.raises(RuntimeConfigError) as rejected:
        resolve_runtime_config(loaded, registry)

    assert rejected.value.reason == "runtime_registration_identity_changed"


def test_profile_scoped_credentials_reject_before_secret_source_access(
    tmp_path: Path, monkeypatch
) -> None:
    from backtrader_runtime import credential_resolver

    registry = _registry(tmp_path, (_sandbox_profile(), _live_profile()))
    _write_config(
        tmp_path,
        mode="live",
        preset="managed_live_direct",
        parameter_key="live_case",
        secrets_ref="runtime_secrets",
    )
    effective = resolve_runtime_config(load_runtime_config(tmp_path, registry=registry), registry)
    reads = []
    monkeypatch.setattr(
        credential_resolver,
        "_read_runtime_secrets_text",
        lambda *args, **kwargs: reads.append((args, kwargs)),
    )

    with pytest.raises(credential_resolver.CredentialResolutionError) as rejected:
        credential_resolver.resolve_runtime_credentials(effective, registry, object())

    assert rejected.value.reason == "profile_scoped_credentials_unavailable"
    assert reads == []


def test_profile_registration_requires_exact_mode_preset_match(tmp_path: Path) -> None:
    registry = _registry(tmp_path, (_sandbox_profile(), _live_profile()))
    _write_config(
        tmp_path,
        mode="simulation",
        preset="paper",
        parameter_key="sandbox_case",
        secrets_ref="none",
    )

    with pytest.raises(RuntimeConfigError) as rejected:
        resolve_runtime_config(load_runtime_config(tmp_path, registry=registry), registry)

    assert rejected.value.reason == "profile_not_registered"


def test_profiles_preserve_registered_runtime_positional_bootstrap_argument(
    tmp_path: Path,
) -> None:
    registration = RegisteredRuntime(
        tmp_path,
        STRATEGY_ID,
        ("replay",),
        ("bootstrap_case",),
        ("none",),
        (),
        False,
        "deny",
        None,
        "synthetic.positional",
        None,
        "run_runtime",
        (),
        (),
        (("bootstrap_case", "preserved"),),
    )

    assert registration.bootstrap_parameters == (("bootstrap_case", "preserved"),)
    assert registration.profiles == ()


def test_profile_managed_execution_binding_rejects_before_store_or_provider_access(
    tmp_path: Path,
) -> None:
    from backtrader_runtime.managed_execution import (
        ManagedExecutionBindingError,
        bind_managed_execution,
    )

    registry = _registry(tmp_path, (_sandbox_profile(), _live_profile()))
    _write_config(
        tmp_path,
        mode="live",
        preset="managed_live_direct",
        parameter_key="live_case",
        secrets_ref="runtime_secrets",
    )
    effective = resolve_runtime_config(load_runtime_config(tmp_path, registry=registry), registry)
    calls = []

    class _Store:
        @property
        def _sdk_mode(self):
            calls.append("sdk_mode")
            return False

        def _is_ctp_session_provider(self):
            calls.append("provider_route_check")
            return False

        def attach_managed_execution_adapter(self, adapter):
            calls.append("attach")

    class _Runtime:
        @property
        def contract(self):
            calls.append("contract")
            return SimpleNamespace(
                strategy_id=effective.strategy_id,
                mode=effective.mode,
                preset=effective.preset,
                environment=effective.policy.environment,
                order_route=effective.order_route,
                effective_digest=effective.effective_digest,
                required_capabilities=effective.required_capabilities,
            )

        @property
        def scope(self):
            calls.append("scope")
            return SimpleNamespace(
                strategy_id=effective.strategy_id,
                environment=effective.policy.environment,
            )

        def submit(self, intent, dispatch):
            calls.append("provider_submit")

    with pytest.raises(ManagedExecutionBindingError, match="profile_dispatch_unavailable"):
        bind_managed_execution(_Store(), effective, _Runtime())

    assert calls == []

    # The dataclass seal is not a reason to trust profile=None at this binder
    # boundary: hostile in-process code can mutate frozen objects directly.
    object.__setattr__(effective, "profile", None)
    with pytest.raises(ManagedExecutionBindingError, match="profile_dispatch_unavailable"):
        bind_managed_execution(_Store(), effective, _Runtime())

    assert calls == []


def test_profile_registration_stays_closed_in_legacy_ctp_production_admission(
    tmp_path: Path,
) -> None:
    from decimal import Decimal

    from backtrader_runtime.ctp_production_execution_admission import (
        CtpProductionExecutionAdmissionError,
        CtpProductionExecutionRegistration,
        require_ctp_production_execution_config_binding,
    )

    registry = _registry(tmp_path, (_sandbox_profile(), _live_profile()))
    _write_config(
        tmp_path,
        mode="live",
        preset="managed_live_direct",
        parameter_key="live_case",
        secrets_ref="runtime_secrets",
    )
    loaded = load_runtime_config(tmp_path, registry=registry)
    effective = resolve_runtime_config(loaded, registry)
    registration = registry.require_runtime_dir(tmp_path)
    admission = CtpProductionExecutionRegistration(
        runtime_registration=registration,
        environment="production",
        account_binding_sha256=None,
        md_front=None,
        td_front=None,
        instrument_id=None,
        exchange_id=None,
        hedge_flag=None,
        approval_receipt_id="ctp-production:receipt.synthetic",
        approval_receipt_sha256="c" * 64,
        artifact_id="ctp-production:artifact.synthetic",
        artifact_sha256="d" * 64,
        allowed_sides=("BUY",),
        allowed_offsets=("OPEN",),
        quantity_step=1,
        max_order_quantity=10,
        max_gross_position=10,
        min_price=Decimal("1"),
        max_price=Decimal("100"),
        price_tick=Decimal("1"),
        max_order_notional=Decimal("1000"),
        scope_binding_mode="sealed_config",
    )

    with pytest.raises(CtpProductionExecutionAdmissionError) as rejected:
        require_ctp_production_execution_config_binding(
            loaded,
            registry,
            admission,
            effective_runtime=effective,
        )

    assert rejected.value.reason == "runtime_contract_mismatch"


def test_profile_style_private_config_is_protected_before_yaml_parse(
    tmp_path: Path, monkeypatch
) -> None:
    from backtrader_runtime import config as runtime_config

    registry = _registry(tmp_path, (_sandbox_private_profile(), _live_profile()))
    _write_config(
        tmp_path,
        mode="simulation",
        preset="sandbox",
        parameter_key="unknown_for_private_profile",
        secrets_ref="none",
    )
    private_security_flags = []
    security_checks = []
    original_read_config_text = runtime_config._read_config_text

    def capture_private_config_security(*args, **kwargs):
        private_security_flags.append(kwargs.get("require_private_config_security"))
        return original_read_config_text(*args, **kwargs)

    monkeypatch.setattr(runtime_config, "_read_config_text", capture_private_config_security)
    monkeypatch.setattr(
        runtime_config,
        "_require_private_config_security",
        lambda *args, **kwargs: security_checks.append(kwargs),
    )

    loaded = load_runtime_config(tmp_path, registry=registry)
    with pytest.raises(RuntimeConfigError) as rejected:
        resolve_runtime_config(loaded, registry)

    assert private_security_flags == [True]
    assert security_checks
    assert rejected.value.reason == "parameter_not_registered"


def test_profile_registration_cannot_use_legacy_bootstrap_or_readonly_binding(
    tmp_path: Path,
) -> None:
    from backtrader_runtime.ctp_simnow_operator import CtpSimNowConfigReadOnlyBinding

    registration = RegisteredRuntime(
        runtime_dir=tmp_path,
        strategy_id=STRATEGY_ID,
        runtime_id="synthetic.profiles",
        allowed_presets=(),
        profiles=(_sandbox_private_profile(), _live_profile()),
    )
    registry = RuntimeRegistry((registration,), registry_id="test.synthetic.profiles")

    with pytest.raises(RuntimeConfigError) as bootstrap_rejected:
        select_bootstrap_preset(registration)
    assert bootstrap_rejected.value.reason == "bootstrap_safe_preset_unavailable"

    with pytest.raises(RuntimeConfigError) as config_rejected:
        bootstrap_runtime_config(tmp_path, registry, "sandbox")
    assert config_rejected.value.reason == "preset_not_registered"
    assert not (tmp_path / "config.yaml").exists()

    with pytest.raises(ValueError, match="exact sandbox-only runtime"):
        RuntimeRegistry(
            (registration,),
            ctp_simnow_readonly_bindings=(
                CtpSimNowConfigReadOnlyBinding(runtime_id="synthetic.profiles"),
            ),
            registry_id="test.synthetic.profiles.readonly",
        )


def test_confirmed_synthetic_live_profile_stops_before_runner_import(
    tmp_path: Path, monkeypatch
) -> None:
    from backtrader_runtime import cli as runtime_cli
    from backtrader_runtime import runner

    registry = _registry(tmp_path, (_sandbox_profile(), _live_profile()))
    _write_config(
        tmp_path,
        mode="live",
        preset="managed_live_direct",
        parameter_key="live_case",
        secrets_ref="runtime_secrets",
    )
    dispatches = []
    monkeypatch.setattr(
        runtime_cli,
        "dispatch_registered_runtime",
        lambda *args, **kwargs: dispatches.append((args, kwargs)),
    )
    stderr = io.StringIO()

    status = main(
        ["run", "--strategy-dir", str(tmp_path), "--confirm-live"],
        registry=registry,
        environ={},
        stdout=io.StringIO(),
        stderr=stderr,
    )

    assert status == 2
    assert '"reason": "profile_dispatch_unavailable"' in stderr.getvalue()
    assert dispatches == []

    stderr = io.StringIO()
    status = main(
        ["preflight", "--strategy-dir", str(tmp_path)],
        registry=registry,
        environ={},
        stdout=io.StringIO(),
        stderr=stderr,
    )
    assert status == 2
    assert '"reason": "profile_dispatch_unavailable"' in stderr.getvalue()
    assert dispatches == []

    effective = resolve_runtime_config(load_runtime_config(tmp_path, registry=registry), registry)
    monkeypatch.setattr(
        runner,
        "_loaded_registered_runner",
        lambda *args, **kwargs: pytest.fail("profile runner was imported"),
    )
    with pytest.raises(RuntimeConfigError) as direct_dispatch_rejected:
        runner.dispatch_registered_runtime(effective, registry)
    assert direct_dispatch_rejected.value.reason == "live_execution_admission_required"
