"""Offline tests for the shared, non-authorizing CTP mode scope binder."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from typing import Optional

import pytest

import backtrader_runtime.config as runtime_config
from backtrader_runtime.ctp_mode_scope import (
    CtpModeScopeBinding,
    CtpModeScopeError,
    bind_ctp_mode_scope,
    require_ctp_mode_scope_binding,
)
from backtrader_runtime.ctp_simulation_execution import (
    CtpSimulationExecutionError,
    open_ctp_simulation_execution,
)
from backtrader_runtime.errors import RuntimeConfigError
from backtrader_runtime.registry import (
    RegisteredRuntime,
    RuntimeProfile,
    RuntimeRegistry,
    validate_runtime_config,
)


RUNTIME_ID = "iteration41.ctp.shared-mode-scope-test"
STRATEGY_ID = "iteration41.ctp.shared_mode_scope_test"
RUNNER_MODULE = "tests.synthetic_ctp_runner"
RECEIPT_SIM = "a" * 64
RECEIPT_LIVE = "b" * 64
PAIRS = (
    ("tcp://127.0.0.1:11001", "tcp://127.0.0.1:12001"),
    ("tcp://127.0.0.1:11002", "tcp://127.0.0.1:12002"),
)


@pytest.fixture(autouse=True)
def _allow_synthetic_private_file(monkeypatch: pytest.MonkeyPatch) -> None:
    # Private-file ACL behavior is covered by config-loader tests. These tests
    # use only synthetic credentials and exercise profile/scope binding.
    monkeypatch.setattr(runtime_config, "_require_private_config_security", lambda *a, **k: None)


def _write_config(
    runtime_dir: Path,
    *,
    mode: str = "simulation",
    preset: str = "sandbox",
    legacy_alias: bool = False,
    production_block: bool = False,
) -> None:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    pair_lines = ["  front_pairs:"]
    for md_front, td_front in PAIRS:
        pair_lines.extend(("    - md_front: " + md_front, "      td_front: " + td_front))
    private_key = "ctp_production" if production_block else "ctp"
    lines = [
        "config_schema_version: 4",
        "strategy:",
        "  id: " + STRATEGY_ID,
        "runtime:",
        "  mode: " + mode,
        "  preset: " + preset,
        "parameters: {}",
        "secrets_ref: config_yaml",
        private_key + ":",
        *pair_lines,
        "  instrument_id: rb2701",
        "  exchange_id: SHFE",
        "  hedge_flag: '1'",
        "  broker_id: '9999'",
        "  user_id: synthetic-user",
        "  password: synthetic-password-only",
        "  app_id: synthetic-app-only",
        "  auth_code: synthetic-auth-only",
    ]
    if legacy_alias:
        lines.extend(("ctp_simnow:", "  instrument_id: rb2701"))
    (runtime_dir / "config.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _profile(
    mode: str,
    preset: str,
    *,
    runner_module: Optional[str] = RUNNER_MODULE,
    runner_entrypoint: str = "run_runtime",
    receipt: Optional[str] = None,
) -> RuntimeProfile:
    return RuntimeProfile(
        mode=mode,
        preset=preset,
        allowed_parameter_keys=(),
        allowed_secrets_refs=("config_yaml",),
        available_capabilities=("execution", "risk", "monitor")
        if mode == "live"
        else (),
        approval_receipt_digest=RECEIPT_LIVE if mode == "live" and receipt is None else receipt,
        runner_module=runner_module,
        runner_entrypoint=runner_entrypoint,
        capability_modules=(),
        offline_managed_execution=False,
        sandbox_write_policy="deny",
    )


def _registry(
    runtime_dir: Path,
    *,
    runner_module: Optional[str] = RUNNER_MODULE,
    simulation_receipt: Optional[str] = RECEIPT_SIM,
    live_receipt: str = RECEIPT_LIVE,
    live_unavailable: bool = False,
    trusted: bool = True,
) -> RuntimeRegistry:
    _write_config(runtime_dir)
    profiles = (
        _profile(
            "simulation",
            "sandbox",
            runner_module=runner_module,
            receipt=simulation_receipt,
        ),
    )
    unavailable = ()
    if live_unavailable:
        from backtrader_runtime.registry import UnavailableModeProfile

        unavailable = (
            UnavailableModeProfile(
                mode="live",
                preset="managed_live_direct",
                reason="managed_live_direct_profile_unavailable",
            ),
        )
    else:
        profiles += (
            _profile(
                "live",
                "managed_live_direct",
                runner_module=runner_module,
                receipt=live_receipt,
            ),
        )
    registered = RegisteredRuntime(
        runtime_dir=runtime_dir,
        runtime_id=RUNTIME_ID,
        strategy_id=STRATEGY_ID,
        allowed_presets=(),
        profiles=profiles,
        unavailable_mode_profiles=unavailable,
    )
    return RuntimeRegistry(
        (registered,), registry_id="test.ctp.shared-mode-scope", trusted=trusted
    )


def _select(effective, registry, pair=PAIRS[0]) -> CtpModeScopeBinding:
    return bind_ctp_mode_scope(effective, registry, selected_front_pair=pair)


def test_same_canonical_config_path_binds_simulation_and_live_profiles(
    tmp_path: Path,
) -> None:
    registry = _registry(tmp_path / "runtime")
    simulation = validate_runtime_config(tmp_path / "runtime", registry)
    simulation_scope = _select(simulation, registry)

    assert simulation_scope.mode == "simulation"
    assert simulation_scope.preset == "sandbox"
    assert simulation_scope.runner_module == RUNNER_MODULE
    assert simulation_scope.profile_approval_receipt_digest == RECEIPT_SIM
    assert simulation_scope.provider_access_authorized is False
    assert simulation_scope.credentials_resolved is False
    assert simulation_scope.execution_authorized is False
    assert simulation_scope.external_writes_authorized is False
    assert simulation_scope.production_writes_authorized is False
    assert simulation_scope.order_submission_authorized is False
    assert simulation_scope.cancellation_authorized is False
    assert simulation_scope.arming_authorized is False
    assert simulation_scope.scope_digest
    require_ctp_mode_scope_binding(simulation_scope)
    with pytest.raises(TypeError, match="non-authorizing"):
        bool(simulation_scope)
    with pytest.raises(FrozenInstanceError):
        simulation_scope.mode = "live"  # type: ignore[misc]

    # Change only the mode/preset in the same synthetic config directory.
    _write_config(
        tmp_path / "runtime", mode="live", preset="managed_live_direct"
    )
    with pytest.raises(CtpModeScopeError):
        _select(simulation, registry)

    live = validate_runtime_config(tmp_path / "runtime", registry)
    live_scope = _select(live, registry)
    assert live_scope.mode == "live"
    assert live_scope.preset == "managed_live_direct"
    assert live_scope.runner_module == simulation_scope.runner_module
    assert live_scope.profile_approval_receipt_digest == RECEIPT_LIVE
    assert live_scope.config_digest != simulation_scope.config_digest
    assert live_scope.effective_digest != simulation_scope.effective_digest
    assert live_scope.profile_digest != simulation_scope.profile_digest
    assert live_scope.scope_digest != simulation_scope.scope_digest
    assert live_scope.front_pair_set_sha256 == simulation_scope.front_pair_set_sha256
    assert live_scope.selected_front_pair_sha256 == simulation_scope.selected_front_pair_sha256
    assert live_scope.as_public_dict()["provider_access_authorized"] is False
    assert "account_binding_sha256" not in live_scope.as_public_dict()
    assert "scope_digest" not in live_scope.as_public_dict()
    assert live_scope.account_binding_sha256 not in repr(live_scope)
    assert live_scope.scope_digest not in repr(live_scope)
    assert "synthetic-password-only" not in repr(live_scope)


def test_scope_binds_account_contract_candidate_set_and_exact_selected_pair(
    tmp_path: Path,
) -> None:
    registry = _registry(tmp_path / "runtime")
    effective = validate_runtime_config(tmp_path / "runtime", registry)

    scope = _select(effective, registry, PAIRS[1])

    assert scope.selected_front_pair == PAIRS[1]
    assert scope.selected_front_pair_sha256 != _select(effective, registry).selected_front_pair_sha256
    assert scope.account_binding_sha256
    assert scope.instrument_id == "rb2701"
    assert scope.exchange_id == "SHFE"
    assert scope.hedge_flag == "1"
    with pytest.raises(CtpModeScopeError) as rejected:
        _select(effective, registry, ("tcp://127.0.0.1:19999", "tcp://127.0.0.1:29999"))
    assert rejected.value.reason == "selected_front_pair_outside_config"


def test_forged_effective_and_old_profile_receipt_are_rejected(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime"
    registry = _registry(runtime_dir)
    effective = validate_runtime_config(runtime_dir, registry)

    forged = replace(effective, effective_digest="f" * 64)
    with pytest.raises(CtpModeScopeError) as rejected:
        _select(forged, registry)
    assert rejected.value.reason == "sealed_runtime_rejected"

    # A fresh registry with a changed code-owned receipt cannot reuse the old
    # effective object, even though both registries name the same runtime path.
    changed_registry = _registry(runtime_dir, live_receipt="c" * 64)
    with pytest.raises(CtpModeScopeError) as rejected:
        _select(effective, changed_registry)
    assert rejected.value.reason == "sealed_runtime_rejected"

    stale_profile = replace(effective.profile, approval_receipt_digest="d" * 64)
    forged_profile_effective = replace(effective, profile=stale_profile)
    with pytest.raises(CtpModeScopeError) as rejected:
        _select(forged_profile_effective, registry)
    assert rejected.value.reason == "sealed_runtime_rejected"


def test_untrusted_registry_cannot_issue_a_scope(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "untrusted"
    trusted_registry = _registry(runtime_dir)
    effective = validate_runtime_config(runtime_dir, trusted_registry)
    untrusted_registry = RuntimeRegistry(
        trusted_registry.registrations,
        registry_id="test.ctp.untrusted-shared-scope",
        trusted=False,
    )

    with pytest.raises(CtpModeScopeError) as rejected:
        _select(effective, untrusted_registry)
    assert rejected.value.reason == "trusted_registry_required"


def test_unregistered_counterpart_profile_is_rejected(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "missing-live-profile"
    registry = _registry(runtime_dir, live_unavailable=True)
    effective = validate_runtime_config(runtime_dir, registry)

    with pytest.raises(CtpModeScopeError) as rejected:
        _select(effective, registry)
    assert rejected.value.reason == "shared_ctp_runner_profile_pair_required"


def test_default_deny_profile_and_unavailable_live_remain_closed_before_runner_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime_dir = tmp_path / "default-deny"
    registry = _registry(
        runtime_dir,
        runner_module=None,
        simulation_receipt=None,
        live_unavailable=True,
    )
    effective = validate_runtime_config(runtime_dir, registry)

    def unexpected_reload(*_args, **_kwargs):
        raise AssertionError("default deny profile must fail before fresh config work")

    monkeypatch.setattr("backtrader_runtime.ctp_mode_scope.validate_runtime_config", unexpected_reload)
    with pytest.raises(CtpModeScopeError) as rejected:
        _select(effective, registry)
    assert rejected.value.reason == "runner_not_registered"

    _write_config(runtime_dir, mode="live", preset="managed_live_direct")
    with pytest.raises(RuntimeConfigError) as unavailable:
        validate_runtime_config(runtime_dir, registry)
    assert unavailable.value.reason == "managed_live_direct_profile_unavailable"


@pytest.mark.parametrize("bad_shape", ("alias", "production"))
def test_legacy_private_blocks_do_not_enter_the_shared_binder(
    tmp_path: Path, bad_shape: str
) -> None:
    runtime_dir = tmp_path / bad_shape
    registry = _registry(runtime_dir)
    if bad_shape == "alias":
        _write_config(runtime_dir, legacy_alias=True)
    else:
        _write_config(
            runtime_dir,
            mode="live",
            preset="managed_live_direct",
            production_block=True,
        )

    with pytest.raises(RuntimeConfigError):
        validate_runtime_config(runtime_dir, registry)


def test_missing_or_divergent_shared_runner_is_rejected(tmp_path: Path) -> None:
    missing_registry = _registry(tmp_path / "missing", runner_module=None)
    missing_effective = validate_runtime_config(tmp_path / "missing", missing_registry)
    with pytest.raises(CtpModeScopeError) as rejected:
        _select(missing_effective, missing_registry)
    assert rejected.value.reason == "runner_not_registered"

    _write_config(tmp_path / "divergent")
    sim = _profile("simulation", "sandbox", runner_module="tests.sim_ctp_runner")
    live = _profile("live", "managed_live_direct", runner_module="tests.live_ctp_runner")
    divergent = RuntimeRegistry(
        (
            RegisteredRuntime(
                runtime_dir=tmp_path / "divergent",
                runtime_id=RUNTIME_ID,
                strategy_id=STRATEGY_ID,
                allowed_presets=(),
                profiles=(sim, live),
            ),
        ),
        registry_id="test.ctp.divergent-runner",
    )
    effective = validate_runtime_config(tmp_path / "divergent", divergent)
    with pytest.raises(CtpModeScopeError) as rejected:
        _select(effective, divergent)
    assert rejected.value.reason == "shared_ctp_runner_mismatch"


def test_scope_dto_cannot_be_forged_as_binder_output(tmp_path: Path) -> None:
    registry = _registry(tmp_path / "runtime")
    effective = validate_runtime_config(tmp_path / "runtime", registry)
    scope = _select(effective, registry)
    forged = replace(scope, profile_approval_receipt_digest="f" * 64)

    with pytest.raises(CtpModeScopeError) as rejected:
        require_ctp_mode_scope_binding(forged)
    assert rejected.value.reason == "scope_binding_provenance_invalid"

    tampered_authority = _select(effective, registry)
    object.__setattr__(tampered_authority, "provider_access_authorized", True)
    with pytest.raises(CtpModeScopeError) as rejected:
        require_ctp_mode_scope_binding(tampered_authority)
    assert rejected.value.reason == "scope_binding_provenance_invalid"


def test_scope_dto_is_not_a_simulation_session_registration(tmp_path: Path) -> None:
    registry = _registry(tmp_path / "runtime")
    effective = validate_runtime_config(tmp_path / "runtime", registry)
    scope = _select(effective, registry)
    factory_calls = []

    with pytest.raises(CtpSimulationExecutionError):
        open_ctp_simulation_execution(
            effective=effective,
            registry=registry,
            registration=scope,  # type: ignore[arg-type]
            native_session_factory=lambda *_: factory_calls.append("factory"),
            approval_verifier=object(),
            query_evidence_verifier=object(),
            writer_fence=object(),
        )
    assert factory_calls == []
