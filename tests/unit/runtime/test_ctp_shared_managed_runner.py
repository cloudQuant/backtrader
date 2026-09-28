"""Offline contracts for the shared mode-selected managed CTP preparation path."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

import pytest

import backtrader_runtime.config as runtime_config
import backtrader_runtime.ctp_production_managed_composition as production_composition
import backtrader_runtime.ctp_shared_managed_runtime as shared_runtime_module
import backtrader_runtime.ctp_simnow_managed_runtime as simnow_runtime_module
from backtrader_runtime.ctp_front_pair_probe import (
    CtpConfiguredFrontPair,
    CtpFrontEndpointEvidence,
    CtpFrontPairEvidence,
    CtpFrontPairSelection,
    CtpFrontProbeSample,
)
from backtrader_runtime.ctp_production_execution_admission import (
    CtpProductionExecutionRegistration,
)
from backtrader_runtime.ctp_shared_managed_runner import (
    CtpProductionManagedRunnerAdapter,
    CtpSharedManagedRunnerError,
    CtpSimNowManagedRunnerAdapter,
    prepare_shared_ctp_managed_runner,
    require_fresh_shared_managed_runner_plan,
    require_shared_managed_runner_plan,
)
from backtrader_runtime.ctp_shared_managed_runtime import (
    CtpProductionManagedSessionAdapter,
    CtpSharedManagedRuntimeError,
    CtpSimNowManagedSessionAdapter,
    CtpSimNowManagedSessionDependencies,
    open_shared_ctp_managed_runtime,
    require_fresh_shared_managed_runtime,
)
from backtrader_runtime.ctp_simnow_managed_operator import (
    CtpSimNowManagedExecutionPolicy,
)
from backtrader_runtime.policy import MANAGED_WRITE_CAPABILITIES
from backtrader_runtime.registry import (
    RegisteredRuntime,
    RuntimeProfile,
    RuntimeRegistry,
    validate_runtime_config,
)


RUNTIME_ID = "iteration41.ctp.shared-runner-test"
STRATEGY_ID = "iteration41.ctp.shared_runner_test"
RUNNER_MODULE = "tests.synthetic_shared_ctp_runner"
SIM_RECEIPT = "a" * 64
LIVE_RECEIPT = "b" * 64
PAIRS = (
    ("tcp://127.0.0.1:11001", "tcp://127.0.0.1:12001"),
    ("tcp://127.0.0.1:11002", "tcp://127.0.0.1:12002"),
)


@pytest.fixture(autouse=True)
def _allow_synthetic_private_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runtime_config, "_require_private_config_security", lambda *a, **k: None)


def _write_config(
    runtime_dir: Path,
    *,
    mode: str = "simulation",
    preset: str = "sandbox",
    front_pairs=PAIRS,
    user_id: str = "synthetic-user",
    instrument_id: str = "rb2701",
    exchange_id: str = "SHFE",
    hedge_flag: str = "1",
    password: str = "synthetic-password-only",
    auth_code: str = "synthetic-auth-only",
) -> None:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    pair_lines = ["  front_pairs:"]
    for md_front, td_front in front_pairs:
        pair_lines.extend(("    - md_front: " + md_front, "      td_front: " + td_front))
    (runtime_dir / "config.yaml").write_text(
        "\n".join(
            [
                "config_schema_version: 4",
                "strategy:",
                "  id: " + STRATEGY_ID,
                "runtime:",
                "  mode: " + mode,
                "  preset: " + preset,
                "parameters: {}",
                "secrets_ref: config_yaml",
                "ctp:",
                *pair_lines,
                "  instrument_id: " + instrument_id,
                "  exchange_id: " + exchange_id,
                "  hedge_flag: '" + hedge_flag + "'",
                "  broker_id: '9999'",
                '  user_id: "' + user_id + '"',
                '  password: "' + password + '"',
                "  app_id: synthetic-app-only",
                '  auth_code: "' + auth_code + '"',
                "",
            ]
        ),
        encoding="utf-8",
    )


def _profile(
    mode: str,
    preset: str,
    *,
    runner_module: Optional[str] = RUNNER_MODULE,
    available_capabilities=MANAGED_WRITE_CAPABILITIES,
    sandbox_write_policy: Optional[str] = None,
    approval_receipt_digest: Optional[str] = None,
) -> RuntimeProfile:
    if sandbox_write_policy is None:
        sandbox_write_policy = "receipt_required" if mode == "simulation" else "deny"
    if approval_receipt_digest is None:
        approval_receipt_digest = SIM_RECEIPT if mode == "simulation" else LIVE_RECEIPT
    return RuntimeProfile(
        mode=mode,
        preset=preset,
        allowed_parameter_keys=(),
        allowed_secrets_refs=("config_yaml",),
        available_capabilities=tuple(available_capabilities),
        approval_receipt_digest=approval_receipt_digest,
        runner_module=runner_module,
        runner_entrypoint="run_runtime",
        capability_modules=(),
        offline_managed_execution=False,
        sandbox_write_policy=sandbox_write_policy,
    )


def _runtime(
    runtime_dir: Path,
    *,
    mode: str = "simulation",
    live_capabilities=MANAGED_WRITE_CAPABILITIES,
    live_profile: bool = True,
) -> tuple[RuntimeRegistry, RegisteredRuntime]:
    _write_config(
        runtime_dir,
        mode=mode,
        preset="sandbox" if mode == "simulation" else "managed_live_direct",
    )
    profiles = [_profile("simulation", "sandbox")]
    if live_profile:
        profiles.append(
            _profile(
                "live",
                "managed_live_direct",
                available_capabilities=live_capabilities,
            )
        )
    registration = RegisteredRuntime(
        runtime_dir=runtime_dir,
        runtime_id=RUNTIME_ID,
        strategy_id=STRATEGY_ID,
        allowed_presets=(),
        profiles=tuple(profiles),
    )
    registry = RuntimeRegistry(
        (registration,), registry_id="test.ctp.shared-managed-runner", trusted=True
    )
    return registry, registration


def _simnow_policy(registration: RegisteredRuntime) -> CtpSimNowManagedExecutionPolicy:
    return CtpSimNowManagedExecutionPolicy(
        runtime_registration=registration,
        allowed_sides=("BUY", "SELL"),
        quantity_step=1,
        max_quantity=2,
        max_gross_position=4,
        min_price=Decimal("10"),
        max_price=Decimal("20"),
        price_tick=Decimal("1"),
        approval_key_id="test-simnow-key",
        approval_ttl_seconds=20,
    )


def _production_registration(
    registration: RegisteredRuntime,
) -> CtpProductionExecutionRegistration:
    return CtpProductionExecutionRegistration(
        runtime_registration=registration,
        environment="production",
        account_binding_sha256=None,
        md_front=None,
        td_front=None,
        instrument_id=None,
        exchange_id=None,
        hedge_flag=None,
        approval_receipt_id="ctp-production:receipt.shared-runner-test",
        approval_receipt_sha256=LIVE_RECEIPT,
        artifact_id="ctp-production:artifact.shared-runner-test",
        artifact_sha256="c" * 64,
        allowed_sides=("BUY", "SELL"),
        allowed_offsets=("OPEN",),
        quantity_step=1,
        max_order_quantity=2,
        max_gross_position=4,
        min_price=Decimal("10"),
        max_price=Decimal("20"),
        price_tick=Decimal("1"),
        max_order_notional=Decimal("100"),
        scope_binding_mode="sealed_config",
    )


def _sim_connector(host: str, port: int, timeout: float):
    return SimpleNamespace(
        latency_ms=1.0,
        dns_resolution_ms=0.0,
        tcp_connect_ms=1.0,
        close=lambda: None,
    )


def _production_selection(front_pairs, *, timeout_seconds: float, repeated_samples: int):
    candidates = tuple(CtpConfiguredFrontPair(**pair) for pair in front_pairs)
    evidence = tuple(
        CtpFrontPairEvidence(
            config_index=index,
            pair=pair,
            md=CtpFrontEndpointEvidence(pair.md_front, (CtpFrontProbeSample(True, 2.0),)),
            td=CtpFrontEndpointEvidence(pair.td_front, (CtpFrontProbeSample(True, 2.0),)),
            reachable=True,
            latency_score_ms=2.0,
        )
        for index, pair in enumerate(candidates)
    )
    selected_index = len(candidates) - 1
    return CtpFrontPairSelection(
        pair=candidates[selected_index],
        config_index=selected_index,
        latency_score_ms=2.0,
        evidence=evidence,
        timeout_seconds=timeout_seconds,
        repeated_samples=repeated_samples,
    )


def test_simulation_uses_shared_preparation_and_binds_typed_simnow_admission(
    tmp_path: Path,
) -> None:
    registry, registration = _runtime(tmp_path / "runtime")
    effective = validate_runtime_config(registration.runtime_dir, registry)
    connector_calls = []

    def connector(host: str, port: int, timeout: float):
        connector_calls.append((host, port))
        return _sim_connector(host, port, timeout)

    plan = prepare_shared_ctp_managed_runner(
        effective,
        registry,
        simnow_adapter=CtpSimNowManagedRunnerAdapter(
            policy=_simnow_policy(registration),
            connector=connector,
            repeated_samples=1,
        ),
    )

    assert connector_calls
    assert plan.scope.mode == "simulation"
    assert plan.scope.preset == "sandbox"
    assert plan.scope.runner_module == RUNNER_MODULE
    assert plan.scope.selected_front_pair == PAIRS[0]
    assert plan.admission.execution_registration.environment == "simnow"
    assert plan.admission.execution_registration.config_digest == effective.config.config_digest
    assert plan.provider_access_authorized is False
    assert plan.credentials_resolved is False
    assert plan.execution_authorized is False
    assert plan.order_submission_authorized is False
    assert plan.cancellation_authorized is False
    require_shared_managed_runner_plan(plan)
    with pytest.raises(TypeError, match="non-authorizing"):
        bool(plan)


def test_live_uses_same_preparation_and_binds_production_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, registration = _runtime(tmp_path / "runtime", mode="live")
    effective = validate_runtime_config(registration.runtime_dir, registry)
    probe_calls = []

    def fake_select(front_pairs, *, timeout_seconds: float, max_pairs: int, repeated_samples: int):
        probe_calls.append((len(front_pairs), max_pairs))
        return _production_selection(
            front_pairs,
            timeout_seconds=timeout_seconds,
            repeated_samples=repeated_samples,
        )

    monkeypatch.setattr(production_composition, "select_ctp_front_pair", fake_select)
    plan = prepare_shared_ctp_managed_runner(
        effective,
        registry,
        production_adapter=CtpProductionManagedRunnerAdapter(
            registration=_production_registration(registration), repeated_samples=1
        ),
    )

    assert probe_calls == [(len(PAIRS), 8)]
    assert plan.scope.mode == "live"
    assert plan.scope.preset == "managed_live_direct"
    assert plan.scope.runner_module == RUNNER_MODULE
    assert plan.scope.selected_front_pair == PAIRS[1]
    assert plan.admission.binding.environment == "production"
    assert plan.admission.binding.config_digest == effective.config.config_digest
    assert plan.admission.binding.effective_digest == effective.effective_digest
    assert plan.provider_access_authorized is False
    assert plan.execution_authorized is False
    require_shared_managed_runner_plan(plan)


def test_profile_grant_gap_rejects_before_simnow_front_probe(tmp_path: Path) -> None:
    registry, registration = _runtime(tmp_path / "runtime", live_capabilities=())
    effective = validate_runtime_config(registration.runtime_dir, registry)
    calls = []

    def connector(host: str, port: int, timeout: float):
        calls.append((host, port))
        return _sim_connector(host, port, timeout)

    with pytest.raises(CtpSharedManagedRunnerError) as rejected:
        prepare_shared_ctp_managed_runner(
            effective,
            registry,
            simnow_adapter=CtpSimNowManagedRunnerAdapter(
                policy=_simnow_policy(registration), connector=connector, repeated_samples=1
            ),
        )

    assert rejected.value.reason == "shared_runner_profile_grant_missing"
    assert calls == []


def test_missing_live_profile_rejects_before_any_mode_adapter(tmp_path: Path) -> None:
    registry, registration = _runtime(tmp_path / "runtime", live_profile=False)
    effective = validate_runtime_config(registration.runtime_dir, registry)
    calls = []

    def connector(host: str, port: int, timeout: float):
        calls.append((host, port))
        return _sim_connector(host, port, timeout)

    with pytest.raises(CtpSharedManagedRunnerError) as rejected:
        prepare_shared_ctp_managed_runner(
            effective,
            registry,
            simnow_adapter=CtpSimNowManagedRunnerAdapter(
                policy=_simnow_policy(registration), connector=connector, repeated_samples=1
            ),
        )
    assert rejected.value.reason == "shared_runner_profile_grant_missing"
    assert calls == []


def test_mode_is_taken_from_fresh_config_and_old_effective_cannot_override_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, registration = _runtime(tmp_path / "runtime")
    old_simulation = validate_runtime_config(registration.runtime_dir, registry)
    _write_config(registration.runtime_dir, mode="live", preset="managed_live_direct")
    live = validate_runtime_config(registration.runtime_dir, registry)
    monkeypatch.setattr(
        production_composition,
        "select_ctp_front_pair",
        lambda front_pairs, *, timeout_seconds, max_pairs, repeated_samples: _production_selection(
            front_pairs,
            timeout_seconds=timeout_seconds,
            repeated_samples=repeated_samples,
        ),
    )
    production_adapter = CtpProductionManagedRunnerAdapter(
        registration=_production_registration(registration), repeated_samples=1
    )

    with pytest.raises(CtpSharedManagedRunnerError):
        prepare_shared_ctp_managed_runner(
            old_simulation,
            registry,
            production_adapter=production_adapter,
        )

    plan = prepare_shared_ctp_managed_runner(
        live,
        registry,
        production_adapter=production_adapter,
    )
    assert plan.scope.mode == "live"


def test_stale_effective_mode_rejects_before_the_mode_adapter(tmp_path: Path) -> None:
    registry, registration = _runtime(tmp_path / "runtime")
    old_simulation = validate_runtime_config(registration.runtime_dir, registry)
    _write_config(registration.runtime_dir, mode="live", preset="managed_live_direct")
    probe_calls = []

    def connector(host: str, port: int, timeout: float):
        probe_calls.append((host, port))
        return _sim_connector(host, port, timeout)

    with pytest.raises(CtpSharedManagedRunnerError) as rejected:
        prepare_shared_ctp_managed_runner(
            old_simulation,
            registry,
            simnow_adapter=CtpSimNowManagedRunnerAdapter(
                policy=_simnow_policy(registration), connector=connector, repeated_samples=1
            ),
        )

    assert rejected.value.reason == "shared_runner_config_stale"
    assert probe_calls == []


def test_plan_cannot_be_mutated_into_an_alternate_selected_pair(
    tmp_path: Path,
) -> None:
    registry, registration = _runtime(tmp_path / "runtime")
    effective = validate_runtime_config(registration.runtime_dir, registry)
    plan = prepare_shared_ctp_managed_runner(
        effective,
        registry,
        simnow_adapter=CtpSimNowManagedRunnerAdapter(
            policy=_simnow_policy(registration), connector=_sim_connector, repeated_samples=1
        ),
    )
    object.__setattr__(plan.scope, "selected_front_pair", PAIRS[1])

    with pytest.raises(CtpSharedManagedRunnerError) as rejected:
        require_shared_managed_runner_plan(plan)
    assert rejected.value.reason == "shared_runner_plan_provenance_invalid"


def test_replacing_the_admission_object_invalidates_plan_provenance(tmp_path: Path) -> None:
    registry, registration = _runtime(tmp_path / "runtime")
    effective = validate_runtime_config(registration.runtime_dir, registry)
    adapter = CtpSimNowManagedRunnerAdapter(
        policy=_simnow_policy(registration), connector=_sim_connector, repeated_samples=1
    )
    first = prepare_shared_ctp_managed_runner(effective, registry, simnow_adapter=adapter)
    second = prepare_shared_ctp_managed_runner(effective, registry, simnow_adapter=adapter)
    object.__setattr__(first, "admission", second.admission)

    with pytest.raises(CtpSharedManagedRunnerError) as rejected:
        require_shared_managed_runner_plan(first)
    assert rejected.value.reason == "shared_runner_plan_provenance_invalid"


def test_nested_simnow_selected_pair_mutation_invalidates_admission(tmp_path: Path) -> None:
    registry, registration = _runtime(tmp_path / "runtime")
    effective = validate_runtime_config(registration.runtime_dir, registry)
    plan = prepare_shared_ctp_managed_runner(
        effective,
        registry,
        simnow_adapter=CtpSimNowManagedRunnerAdapter(
            policy=_simnow_policy(registration), connector=_sim_connector, repeated_samples=1
        ),
    )
    object.__setattr__(
        plan.admission.front_pair_selection,
        "pair",
        CtpConfiguredFrontPair(*PAIRS[1]),
    )

    with pytest.raises(CtpSharedManagedRunnerError):
        require_shared_managed_runner_plan(plan)


def test_production_binding_pair_mutation_invalidates_admission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, registration = _runtime(tmp_path / "runtime", mode="live")
    effective = validate_runtime_config(registration.runtime_dir, registry)
    monkeypatch.setattr(
        production_composition,
        "select_ctp_front_pair",
        lambda front_pairs, *, timeout_seconds, max_pairs, repeated_samples: _production_selection(
            front_pairs,
            timeout_seconds=timeout_seconds,
            repeated_samples=repeated_samples,
        ),
    )
    plan = prepare_shared_ctp_managed_runner(
        effective,
        registry,
        production_adapter=CtpProductionManagedRunnerAdapter(
            registration=_production_registration(registration), repeated_samples=1
        ),
    )
    object.__setattr__(plan.admission.binding, "md_front", PAIRS[0][0])
    object.__setattr__(plan.admission.binding, "td_front", PAIRS[0][1])

    with pytest.raises(CtpSharedManagedRunnerError):
        require_shared_managed_runner_plan(plan)


def test_mutated_authority_fact_invalidates_plan_provenance(tmp_path: Path) -> None:
    registry, registration = _runtime(tmp_path / "runtime")
    effective = validate_runtime_config(registration.runtime_dir, registry)
    plan = prepare_shared_ctp_managed_runner(
        effective,
        registry,
        simnow_adapter=CtpSimNowManagedRunnerAdapter(
            policy=_simnow_policy(registration), connector=_sim_connector, repeated_samples=1
        ),
    )
    object.__setattr__(plan, "execution_authorized", True)

    with pytest.raises(CtpSharedManagedRunnerError):
        require_shared_managed_runner_plan(plan)


def test_freshness_gate_rejects_plan_after_config_mode_switch(
    tmp_path: Path,
) -> None:
    registry, registration = _runtime(tmp_path / "runtime")
    simulation = validate_runtime_config(registration.runtime_dir, registry)
    plan = prepare_shared_ctp_managed_runner(
        simulation,
        registry,
        simnow_adapter=CtpSimNowManagedRunnerAdapter(
            policy=_simnow_policy(registration), connector=_sim_connector, repeated_samples=1
        ),
    )

    _write_config(registration.runtime_dir, mode="live", preset="managed_live_direct")
    live = validate_runtime_config(registration.runtime_dir, registry)

    # Issuance-time object integrity still holds; freshness is a separate gate.
    require_shared_managed_runner_plan(plan)
    with pytest.raises(CtpSharedManagedRunnerError) as rejected:
        require_fresh_shared_managed_runner_plan(plan, live, registry)
    assert rejected.value.reason == "shared_runner_plan_stale"


def test_front_probe_config_switch_is_caught_by_disk_reseal(tmp_path: Path) -> None:
    registry, registration = _runtime(tmp_path / "runtime")
    effective = validate_runtime_config(registration.runtime_dir, registry)
    probe_calls = []

    def connector(host: str, port: int, timeout: float):
        if not probe_calls:
            # Simulate an operator replacing the shared config while the
            # credential-free front probe is in flight.
            _write_config(registration.runtime_dir, mode="live", preset="managed_live_direct")
        probe_calls.append((host, port))
        return _sim_connector(host, port, timeout)

    with pytest.raises(CtpSharedManagedRunnerError) as rejected:
        prepare_shared_ctp_managed_runner(
            effective,
            registry,
            simnow_adapter=CtpSimNowManagedRunnerAdapter(
                policy=_simnow_policy(registration), connector=connector, repeated_samples=1
            ),
        )

    assert probe_calls
    assert "fresh" in rejected.value.reason or "stale" in rejected.value.reason


def _session_dependencies(calls=None) -> CtpSimNowManagedSessionDependencies:
    def observed(name, result=None):
        def record(*_args, **_kwargs):
            if calls is not None:
                calls.append(name)
            return result

        return record

    return CtpSimNowManagedSessionDependencies(
        execution_capability=object(),
        runtime_admission_check=observed("admission", True),
        runtime_order_binding=observed("order_ref", {}),
        runtime_credential_binding_factory=observed("credentials", object()),
        approval_verifier=object(),
        sdk_approval_rechecker=observed("approval", True),
        query_evidence_verifier=object(),
        writer_fence=object(),
        native_client_factory=observed("sdk_client", object()),
        native_readiness_check=observed("native_readiness", object()),
        connector=observed("front_probe", _sim_connector),
        repeated_samples=1,
    )


def test_shared_runtime_opens_through_existing_simnow_composition_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, registration = _runtime(tmp_path / "runtime")
    effective = validate_runtime_config(registration.runtime_dir, registry)
    calls = []
    fake_session = SimpleNamespace(close=lambda: calls.append("closed"))

    def fake_simnow_open(actual_effective, actual_registry, policy, **kwargs):
        calls.append((actual_effective.mode, actual_effective.preset, kwargs.keys()))
        plan = prepare_shared_ctp_managed_runner(
            actual_effective,
            actual_registry,
            simnow_adapter=CtpSimNowManagedRunnerAdapter(
                policy=policy, connector=_sim_connector, repeated_samples=1
            ),
        )
        return simnow_runtime_module.CtpSimNowManagedRuntime(
            selection=plan.admission,
            session=fake_session,
        )

    monkeypatch.setattr(shared_runtime_module, "open_ctp_simnow_managed_runtime", fake_simnow_open)
    adapter = CtpSimNowManagedSessionAdapter(
        policy=_simnow_policy(registration), dependencies=_session_dependencies()
    )
    runtime = open_shared_ctp_managed_runtime(effective, registry, simnow_adapter=adapter)

    assert calls[0][0:2] == ("simulation", "sandbox")
    assert runtime.context.scope.mode == "simulation"
    assert runtime.context.scope.preset == "sandbox"
    assert runtime.context.scope.selected_front_pair == PAIRS[0]
    assert runtime.context.approval_scope_digest == runtime.context.mode_registration_digest
    assert runtime.context.journal_scope_digest
    assert runtime.context.state_partition.startswith("ctp-managed/simulation/sandbox/")
    assert runtime.session is fake_session
    runtime.close()
    assert calls[-1] == "closed"


def test_config_switch_during_session_open_closes_and_rejects_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, registration = _runtime(tmp_path / "runtime")
    effective = validate_runtime_config(registration.runtime_dir, registry)
    calls = []

    def fake_simnow_open(actual_effective, actual_registry, policy, **kwargs):
        plan = prepare_shared_ctp_managed_runner(
            actual_effective,
            actual_registry,
            simnow_adapter=CtpSimNowManagedRunnerAdapter(
                policy=policy, connector=_sim_connector, repeated_samples=1
            ),
        )
        _write_config(registration.runtime_dir, mode="live", preset="managed_live_direct")
        return simnow_runtime_module.CtpSimNowManagedRuntime(
            selection=plan.admission,
            session=SimpleNamespace(close=lambda: calls.append("closed")),
        )

    monkeypatch.setattr(shared_runtime_module, "open_ctp_simnow_managed_runtime", fake_simnow_open)
    adapter = CtpSimNowManagedSessionAdapter(
        policy=_simnow_policy(registration), dependencies=_session_dependencies()
    )

    with pytest.raises(CtpSharedManagedRuntimeError) as rejected:
        open_shared_ctp_managed_runtime(effective, registry, simnow_adapter=adapter)

    assert rejected.value.reason in {
        "shared_runtime_stale",
        "simnow_session_scope_rejected",
    }
    assert calls == ["closed"]


def test_production_session_adapter_rejects_before_probe_credentials_or_sdk(
    tmp_path: Path,
) -> None:
    registry, registration = _runtime(tmp_path / "runtime", mode="live")
    effective = validate_runtime_config(registration.runtime_dir, registry)
    calls = []
    sim_adapter = CtpSimNowManagedSessionAdapter(
        policy=_simnow_policy(registration), dependencies=_session_dependencies()
    )
    production_adapter = CtpProductionManagedSessionAdapter(
        registration=_production_registration(registration)
    )

    with pytest.raises(CtpSharedManagedRuntimeError) as rejected:
        open_shared_ctp_managed_runtime(
            effective,
            registry,
            simnow_adapter=sim_adapter,
            production_adapter=production_adapter,
        )

    assert rejected.value.reason == "production_native_session_authority_unavailable"
    assert calls == []


def test_stale_effective_mode_rejects_before_opening_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, registration = _runtime(tmp_path / "runtime")
    old_simulation = validate_runtime_config(registration.runtime_dir, registry)
    _write_config(registration.runtime_dir, mode="live", preset="managed_live_direct")
    open_calls = []
    monkeypatch.setattr(
        shared_runtime_module,
        "open_ctp_simnow_managed_runtime",
        lambda *args, **kwargs: open_calls.append("simnow"),
    )
    adapter = CtpSimNowManagedSessionAdapter(
        policy=_simnow_policy(registration), dependencies=_session_dependencies()
    )

    with pytest.raises(CtpSharedManagedRuntimeError):
        open_shared_ctp_managed_runtime(
            old_simulation, registry, simnow_adapter=adapter
        )

    assert open_calls == []


def test_shared_session_and_bound_approval_journal_scope_go_stale_after_mode_switch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, registration = _runtime(tmp_path / "runtime")
    simulation = validate_runtime_config(registration.runtime_dir, registry)
    sim_open_calls = []
    provider_side_effects = []
    fake_sessions = []

    def fake_simnow_open(actual_effective, actual_registry, policy, **kwargs):
        sim_open_calls.append((actual_effective.mode, actual_effective.preset))
        plan = prepare_shared_ctp_managed_runner(
            actual_effective,
            actual_registry,
            simnow_adapter=CtpSimNowManagedRunnerAdapter(
                policy=policy, connector=_sim_connector, repeated_samples=1
            ),
        )
        fake_session = SimpleNamespace(close=lambda: None)
        fake_sessions.append(fake_session)
        return simnow_runtime_module.CtpSimNowManagedRuntime(
            selection=plan.admission,
            session=fake_session,
        )

    monkeypatch.setattr(shared_runtime_module, "open_ctp_simnow_managed_runtime", fake_simnow_open)
    sim_adapter = CtpSimNowManagedSessionAdapter(
        policy=_simnow_policy(registration),
        dependencies=_session_dependencies(provider_side_effects),
    )
    prior = open_shared_ctp_managed_runtime(simulation, registry, simnow_adapter=sim_adapter)
    prior_context = prior.context

    # The wrapper must reseal from disk even when its caller still has the old
    # sealed object; mode alone changes the profile/scope identity.
    _write_config(registration.runtime_dir, mode="live", preset="managed_live_direct")
    live = validate_runtime_config(registration.runtime_dir, registry)

    with pytest.raises(CtpSharedManagedRuntimeError):
        prior.require_current()
    with pytest.raises(CtpSharedManagedRuntimeError):
        require_fresh_shared_managed_runtime(prior, live, registry)
    with pytest.raises(CtpSharedManagedRuntimeError):
        _ = prior.session

    production = CtpProductionManagedSessionAdapter(
        registration=_production_registration(registration)
    )
    monkeypatch.setattr(
        production_composition,
        "select_ctp_front_pair",
        lambda *args, **kwargs: pytest.fail("live session must reject before probing"),
    )
    with pytest.raises(CtpSharedManagedRuntimeError) as rejected:
        open_shared_ctp_managed_runtime(live, registry, production_adapter=production)

    assert rejected.value.reason == "production_native_session_authority_unavailable"
    assert sim_open_calls == [("simulation", "sandbox")]
    assert provider_side_effects == []

    # Switch the same config back to simulation under another account. The
    # previous approval registration and action-journal scope must not follow.
    _write_config(registration.runtime_dir, user_id="synthetic-user-2")
    account_rotated = validate_runtime_config(registration.runtime_dir, registry)
    second = open_shared_ctp_managed_runtime(account_rotated, registry, simnow_adapter=sim_adapter)
    assert sim_open_calls[-1] == ("simulation", "sandbox")
    assert second.context.mode_registration_digest != prior_context.mode_registration_digest
    assert second.context.approval_scope_digest != prior_context.approval_scope_digest
    assert second.context.journal_scope_digest != prior_context.journal_scope_digest
    with pytest.raises(CtpSharedManagedRuntimeError):
        require_fresh_shared_managed_runtime(prior, account_rotated, registry)

    # A front candidate change invalidates the selected-pair context and the
    # old journal scope before a new fake session can be used.
    changed_pairs = (
        ("tcp://127.0.0.1:11003", "tcp://127.0.0.1:12003"),
        ("tcp://127.0.0.1:11004", "tcp://127.0.0.1:12004"),
    )
    _write_config(registration.runtime_dir, user_id="synthetic-user-2", front_pairs=changed_pairs)
    front_rotated = validate_runtime_config(registration.runtime_dir, registry)
    with pytest.raises(CtpSharedManagedRuntimeError):
        second.require_current()
    third = open_shared_ctp_managed_runtime(front_rotated, registry, simnow_adapter=sim_adapter)
    assert third.context.scope.selected_front_pair == changed_pairs[0]
    assert third.context.approval_scope_digest != second.context.approval_scope_digest
    assert third.context.journal_scope_digest != second.context.journal_scope_digest

    # Contract-only changes also make the old simulated registration,
    # approval identity and durable journal scope stale.
    _write_config(
        registration.runtime_dir,
        user_id="synthetic-user-2",
        front_pairs=changed_pairs,
        instrument_id="rb2702",
        exchange_id="DCE",
        hedge_flag="2",
    )
    contract_rotated = validate_runtime_config(registration.runtime_dir, registry)
    with pytest.raises(CtpSharedManagedRuntimeError):
        third.require_current()
    fourth = open_shared_ctp_managed_runtime(contract_rotated, registry, simnow_adapter=sim_adapter)
    assert fourth.context.scope.instrument_id == "rb2702"
    assert fourth.context.scope.exchange_id == "DCE"
    assert fourth.context.approval_scope_digest != third.context.approval_scope_digest
    assert fourth.context.journal_scope_digest != third.context.journal_scope_digest
    assert len(fake_sessions) == 4


def test_shared_context_does_not_claim_to_bind_password_or_auth_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, registration = _runtime(tmp_path / "runtime")
    effective = validate_runtime_config(registration.runtime_dir, registry)

    def fake_simnow_open(actual_effective, actual_registry, policy, **kwargs):
        plan = prepare_shared_ctp_managed_runner(
            actual_effective,
            actual_registry,
            simnow_adapter=CtpSimNowManagedRunnerAdapter(
                policy=policy, connector=_sim_connector, repeated_samples=1
            ),
        )
        return simnow_runtime_module.CtpSimNowManagedRuntime(
            selection=plan.admission,
            session=SimpleNamespace(close=lambda: None),
        )

    monkeypatch.setattr(shared_runtime_module, "open_ctp_simnow_managed_runtime", fake_simnow_open)
    adapter = CtpSimNowManagedSessionAdapter(
        policy=_simnow_policy(registration), dependencies=_session_dependencies()
    )
    runtime = open_shared_ctp_managed_runtime(effective, registry, simnow_adapter=adapter)
    original_context = runtime.context
    _write_config(
        registration.runtime_dir,
        password="rotated-fake-password",
        auth_code="rotated-fake-auth-code",
    )
    rotated_secrets = validate_runtime_config(registration.runtime_dir, registry)

    # The public config/effective identity intentionally excludes secrets.
    # This wrapper therefore does not revoke a raw session handle on secret
    # rotation; the managed port's per-action typed credential-binding refresh
    # and SDK approval callback are the required write-time gate.
    assert rotated_secrets.config.config_digest == effective.config.config_digest
    assert rotated_secrets.effective_digest == effective.effective_digest
    require_fresh_shared_managed_runtime(runtime, rotated_secrets, registry)
    assert runtime.context == original_context
    public = runtime.context.as_public_dict()
    assert "password" not in repr(public)
    assert "auth_code" not in repr(public)


def test_unavailable_shared_profile_rejects_before_either_session_adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, registration = _runtime(tmp_path / "runtime", live_profile=False)
    effective = validate_runtime_config(registration.runtime_dir, registry)
    calls = []
    monkeypatch.setattr(
        shared_runtime_module,
        "open_ctp_simnow_managed_runtime",
        lambda *args, **kwargs: calls.append("simnow"),
    )
    adapter = CtpSimNowManagedSessionAdapter(
        policy=_simnow_policy(registration), dependencies=_session_dependencies()
    )

    with pytest.raises(CtpSharedManagedRuntimeError) as rejected:
        open_shared_ctp_managed_runtime(effective, registry, simnow_adapter=adapter)

    assert rejected.value.reason == "shared_runner_contract_rejected"
    assert calls == []
