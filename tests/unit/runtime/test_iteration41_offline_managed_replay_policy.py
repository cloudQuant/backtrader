"""Fail-closed policy coverage for the separately registered offline L2 fixture."""

from __future__ import annotations

from pathlib import Path

import pytest

from backtrader_runtime import (
    MODE_PRESET_MISMATCH,
    RegisteredRuntime,
    RuntimeConfigError,
    RuntimeRegistry,
    load_runtime_config,
    resolve_runtime_config,
)
from backtrader_runtime.managed_execution import (
    ManagedExecutionBindingError,
    bind_managed_execution,
)
from backtrader_runtime.policy import MANAGED_WRITE_CAPABILITIES


_STRATEGY_ID = "example.013_3.sa_midfreq_simnow"
_RUNNER = "examples.013_3_sa_midfreq_simnow.run_managed_replay_runtime"


def _write_config(runtime_dir: Path, *, mode: str = "simulation", preset: str = "replay") -> None:
    runtime_dir.mkdir(exist_ok=True)
    (runtime_dir / "config.yaml").write_text(
        "config_schema_version: 4\n"
        "strategy:\n"
        "  id: " + _STRATEGY_ID + "\n"
        "runtime:\n"
        "  mode: " + mode + "\n"
        "  preset: " + preset + "\n"
        "parameters: {}\n"
        "secrets_ref: none\n",
        encoding="utf-8",
    )


def _managed_registration(runtime_dir: Path) -> RegisteredRuntime:
    return RegisteredRuntime(
        runtime_dir=runtime_dir,
        runtime_id="fixture.iteration41.managed-replay",
        strategy_id=_STRATEGY_ID,
        allowed_presets=("replay",),
        available_capabilities=MANAGED_WRITE_CAPABILITIES,
        offline_managed_execution=True,
        runner_module=_RUNNER,
    )


def test_explicit_registered_offline_flag_is_the_only_managed_replay_route(tmp_path: Path) -> None:
    _write_config(tmp_path)
    registration = _managed_registration(tmp_path)
    registry = RuntimeRegistry((registration,))
    effective = resolve_runtime_config(
        load_runtime_config(tmp_path, registry=registry),
        registry,
    )

    assert effective.mode == "simulation"
    assert effective.preset == "replay"
    assert effective.order_route == "managed_execution"
    assert effective.account_access == "fake_provider"
    assert effective.required_capabilities == MANAGED_WRITE_CAPABILITIES
    assert effective.allows_network is False
    assert effective.allows_external_writes is False
    assert effective.allows_production_writes is False
    assert effective.requires_approval is False


def test_forging_the_flag_on_an_ordinary_replay_cannot_create_a_managed_route(
    tmp_path: Path,
) -> None:
    _write_config(tmp_path)
    registration = RegisteredRuntime(
        runtime_dir=tmp_path,
        strategy_id=_STRATEGY_ID,
        allowed_presets=("replay",),
        runner_module=_RUNNER,
    )
    # A frozen dataclass can still be tampered with by hostile in-process
    # code.  Resolver capability revalidation must reject that state rather
    # than trusting this boolean alone.
    object.__setattr__(registration, "offline_managed_execution", True)
    with pytest.raises(ValueError, match="requires exactly execution, risk, and monitor"):
        RuntimeRegistry((registration,))


@pytest.mark.parametrize(
    "kwargs, message",
    (
        (
            {"allowed_presets": ("replay", "managed_live_direct")},
            "restricted to the replay preset",
        ),
        (
            {"allowed_secrets_refs": ("none", "runtime_secrets")},
            "must not accept provider secrets",
        ),
        (
            {"available_capabilities": ("execution", "risk")},
            "requires exactly execution, risk, and monitor",
        ),
        (
            {"sandbox_write_policy": "receipt_required"},
            "receipt-required sandbox policy",
        ),
    ),
)
def test_offline_managed_flag_rejects_unsealed_registration_shapes(
    tmp_path: Path, kwargs: dict[str, object], message: str
) -> None:
    values: dict[str, object] = {
        "runtime_dir": tmp_path,
        "strategy_id": _STRATEGY_ID,
        "allowed_presets": ("replay",),
        "available_capabilities": MANAGED_WRITE_CAPABILITIES,
        "offline_managed_execution": True,
        "runner_module": _RUNNER,
    }
    values.update(kwargs)

    with pytest.raises(ValueError, match=message):
        RegisteredRuntime(**values)


def test_live_upgrade_attempt_for_managed_replay_is_rejected_before_runner_import(
    tmp_path: Path,
) -> None:
    _write_config(tmp_path, mode="live", preset="replay")
    registry = RuntimeRegistry((_managed_registration(tmp_path),))

    with pytest.raises(RuntimeConfigError) as caught:
        load_runtime_config(tmp_path, registry=registry)

    assert caught.value.code == MODE_PRESET_MISMATCH
    assert caught.value.reason == "mode_preset_mismatch"


def test_ordinary_replay_with_even_capabilities_cannot_bind_managed_bridge(tmp_path: Path) -> None:
    _write_config(tmp_path)
    ordinary = RegisteredRuntime(
        runtime_dir=tmp_path,
        strategy_id=_STRATEGY_ID,
        allowed_presets=("replay",),
        available_capabilities=MANAGED_WRITE_CAPABILITIES,
        runner_module=_RUNNER,
    )
    registry = RuntimeRegistry((ordinary,))
    effective = resolve_runtime_config(load_runtime_config(tmp_path, registry=registry), registry)

    assert ordinary.offline_managed_execution is False
    assert effective.order_route is None
    assert effective.required_capabilities == ()
    with pytest.raises(ManagedExecutionBindingError, match="not a managed execution route"):
        bind_managed_execution(object(), effective, object())
