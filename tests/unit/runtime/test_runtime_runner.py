"""Tests for code-owned dispatch after Iteration 41 config resolution."""

from __future__ import annotations

import ast
import io
import importlib.util
import json
import os
import subprocess
import sys
import types
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
from typing import Generator, Optional

import pytest

import backtrader_runtime.inventory as runtime_inventory
import backtrader_runtime.runner as runtime_runner
from backtrader_runtime import (
    PRESET_POLICY_VIOLATION,
    RegisteredRuntime,
    RuntimeConfigError,
    RuntimeRegistry,
    EffectiveRuntimeConfig,
    load_runtime_config,
    resolve_runtime_config,
    iteration41_runtime_registry,
)
from backtrader_runtime.cli import main
from backtrader_runtime.config import RuntimeConfig
from backtrader_runtime.policy import get_preset_policy
from backtrader_runtime.runner import (
    RuntimeDirectoryCapability,
    _loaded_registered_runner,
    dispatch_registered_runtime,
    resolve_runner_effective_config,
)


# The fresh replay process performs real offline framework imports.  xdist can
# deschedule it behind CPU-bound workers, so this is a bounded liveness guard,
# not a replay latency requirement.
_FRESH_REPLAY_SUBPROCESS_TIMEOUT_SECONDS = 180


def _config(runtime_dir: Path) -> None:
    (runtime_dir / "config.yaml").write_text(
        "config_schema_version: 4\n"
        "strategy:\n"
        "  id: example.runner\n"
        "runtime:\n"
        "  mode: simulation\n"
        "  preset: replay\n"
        "parameters: {}\n"
        "secrets_ref: none\n",
        encoding="utf-8",
    )


def _registry(runtime_dir: Path, *, runner_module: Optional[str] = None) -> RuntimeRegistry:
    return RuntimeRegistry(
        (
            RegisteredRuntime(
                runtime_dir=runtime_dir,
                strategy_id="example.runner",
                allowed_presets=("replay",),
                runner_module=runner_module,
            ),
        )
    )


def _public_examples_modules() -> dict:
    """Snapshot public example modules without touching their package state."""

    return {
        name: module
        for name, module in sys.modules.items()
        if name == "examples" or name.startswith("examples.")
    }


def _assert_public_examples_unchanged(before: dict) -> None:
    after = _public_examples_modules()
    assert set(after) == set(before)
    assert all(after[name] is module for name, module in before.items())


def _is_external_capability_module(name: object) -> bool:
    """Return whether a module name belongs to the external SDK family."""

    return isinstance(name, str) and name.split(".", 1)[0].startswith("bt_api_")


@contextmanager
def _isolated_external_capability_modules() -> Generator[None, None, None]:
    """Give one shipped-runner test a clean, exactly-restored SDK module cache.

    xdist workers run unrelated tests in the same interpreter.  A worker can
    therefore arrive here with a preloaded ``bt_api_*`` module which the
    runner's capability guard deliberately rejects as unregistered.  This
    helper removes *all* such worker residue before the test's dispatch and
    removes every module created during the dispatch before restoring the
    exact pre-test module objects.  Tests which need to prove fail-closed
    behavior inject their deliberate ambient module inside this context.
    """

    before = {
        name: module
        for name, module in tuple(sys.modules.items())
        if _is_external_capability_module(name)
    }
    for name in before:
        sys.modules.pop(name, None)
    try:
        yield
    finally:
        for name in tuple(sys.modules):
            if _is_external_capability_module(name):
                sys.modules.pop(name, None)
        sys.modules.update(before)


def _dispatch_with_isolated_external_capabilities(
    effective: EffectiveRuntimeConfig, registry: RuntimeRegistry
) -> dict:
    """Dispatch a shipped runner without unrelated worker SDK imports."""

    with _isolated_external_capability_modules():
        return dispatch_registered_runtime(effective, registry)


def test_external_capability_module_isolation_clears_all_nested_entries_and_restores_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Worker residue is cleared, while the exact prior module cache survives."""

    top_level = "bt_api_iteration41_worker_residue"
    nested = top_level + ".nested"
    partially_initialized = top_level + ".partial"
    created_during_dispatch = "bt_api_iteration41_created_during_dispatch"
    root_module = types.ModuleType(top_level)
    nested_module = types.ModuleType(nested)
    created_module = types.ModuleType(created_during_dispatch)
    monkeypatch.setitem(sys.modules, top_level, root_module)
    monkeypatch.setitem(sys.modules, nested, nested_module)
    monkeypatch.setitem(sys.modules, partially_initialized, None)
    monkeypatch.delitem(sys.modules, created_during_dispatch, raising=False)

    with _isolated_external_capability_modules():
        assert top_level not in sys.modules
        assert nested not in sys.modules
        assert partially_initialized not in sys.modules
        sys.modules[created_during_dispatch] = created_module

    assert sys.modules[top_level] is root_module
    assert sys.modules[nested] is nested_module
    assert sys.modules[partially_initialized] is None
    assert created_during_dispatch not in sys.modules


def _attempt_directory_rename(source: Path, target: Path) -> str:
    """Ask a separate process to rename a directory and return its outcome."""

    program = """
from pathlib import Path
import sys

source = Path(sys.argv[1])
target = Path(sys.argv[2])
try:
    source.rename(target)
except OSError:
    print("blocked")
else:
    print("renamed")
"""
    result = subprocess.run(
        [sys.executable, "-c", program, str(source), str(target)],
        capture_output=True,
        check=False,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_dispatch_imports_only_the_registered_entrypoint_after_resolution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _config(tmp_path)
    calls = []
    module_name = "iteration41_test_runner"
    module = types.ModuleType(module_name)

    def run_runtime(
        runtime_dir: Optional[Path],
        *,
        registry: RuntimeRegistry,
        effective: EffectiveRuntimeConfig,
        runtime_directory: Optional[RuntimeDirectoryCapability] = None,
    ) -> dict:
        calls.append((runtime_dir, registry, effective, runtime_directory))
        return {"status": "LOCAL_REPLAY_PASS", "network": 0, "order_write": 0}

    module.run_runtime = run_runtime
    monkeypatch.setitem(sys.modules, module_name, module)
    registry = _registry(tmp_path, runner_module=module_name)
    effective = resolve_runtime_config(load_runtime_config(tmp_path, registry=registry), registry)

    report = dispatch_registered_runtime(effective, registry)

    assert report == {"status": "LOCAL_REPLAY_PASS", "network": 0, "order_write": 0}
    assert len(calls) == 1
    received_runtime_dir, received_registry, received_effective, received_capability = calls[0]
    assert received_runtime_dir == (None if os.name == "posix" else tmp_path.resolve())
    if os.name == "posix":
        assert isinstance(received_capability, RuntimeDirectoryCapability)
        assert received_registry is not registry
        assert received_effective is not effective
        assert received_effective.config.strategy_id == effective.config.strategy_id
        assert received_effective.effective_digest == effective.effective_digest
    else:
        assert received_capability is None
        assert received_registry is registry
        assert received_effective == effective


def test_cli_run_projects_the_runner_report_without_accepting_mode_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _config(tmp_path)
    module_name = "iteration41_cli_runner"
    module = types.ModuleType(module_name)
    module.run_runtime = lambda runtime_dir, *, registry, effective: {  # type: ignore[attr-defined]
        "status": "LOCAL_REPLAY_PASS",
        "runtime_dir": str(runtime_dir),
    }
    monkeypatch.setitem(sys.modules, module_name, module)
    registry = _registry(tmp_path, runner_module=module_name)
    stdout = io.StringIO()

    status = main(
        ["run", "--strategy-dir", str(tmp_path)],
        registry=registry,
        stdout=stdout,
        stderr=io.StringIO(),
    )

    assert status == 0
    payload = json.loads(stdout.getvalue())
    assert payload["status"] == "completed"
    assert payload["started"] is True
    assert payload["runner_dispatch"] == "code_owned"
    assert payload["report"]["detail"] == "summary"
    assert payload["report"]["result"]["status"] == "LOCAL_REPLAY_PASS"


def test_cli_dispatch_uses_the_sealed_config_after_the_path_is_replaced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A runner receives validated in-memory values, never a second path read."""

    (tmp_path / "config.yaml").write_text(
        "config_schema_version: 4\n"
        "strategy:\n"
        "  id: example.runner\n"
        "runtime:\n"
        "  mode: simulation\n"
        "  preset: replay\n"
        "parameters:\n"
        "  scenario: sealed\n"
        "secrets_ref: none\n",
        encoding="utf-8",
    )
    module_name = "iteration41_sealed_config_runner"
    module = types.ModuleType(module_name)

    def run_runtime(
        runtime_dir: Optional[Path],
        *,
        registry: RuntimeRegistry,
        effective: EffectiveRuntimeConfig,
        runtime_directory: Optional[RuntimeDirectoryCapability] = None,
    ) -> dict:
        del registry
        # This simulates a post-validation replacement.  The runner must use
        # the already sealed descriptor, rather than opening this pathname.
        if runtime_dir is not None:
            (runtime_dir / "config.yaml").write_text("not a runtime config\n", encoding="utf-8")
        else:
            assert runtime_directory is not None
        return {"status": "LOCAL_REPLAY_PASS", "scenario": effective.parameters["scenario"]}

    module.run_runtime = run_runtime
    monkeypatch.setitem(sys.modules, module_name, module)
    registry = RuntimeRegistry(
        (
            RegisteredRuntime(
                runtime_dir=tmp_path,
                strategy_id="example.runner",
                allowed_presets=("replay",),
                allowed_parameter_keys=("scenario",),
                runner_module=module_name,
            ),
        )
    )

    stdout = io.StringIO()
    assert (
        main(
            ["run", "--strategy-dir", str(tmp_path)],
            registry=registry,
            stdout=stdout,
            stderr=io.StringIO(),
        )
        == 0
    )

    payload = json.loads(stdout.getvalue())
    assert payload["report"]["result"]["scenario"] == "sealed"


def test_unsealed_direct_runner_call_is_rejected_before_config_path_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A public runner may not revalidate a mutable config pathname by itself."""

    registry = _registry(tmp_path)

    def fail_config_validation(*_args, **_kwargs):
        raise AssertionError("an unsealed direct runner call must not read config.yaml")

    monkeypatch.setattr(runtime_runner, "validate_runtime_config", fail_config_validation)
    with pytest.raises(RuntimeConfigError) as caught:
        resolve_runner_effective_config(tmp_path, registry)

    assert caught.value.code == PRESET_POLICY_VIOLATION
    assert caught.value.reason == "runner_dispatch_required"
    assert "bt-runtime run --strategy-dir" in caught.value.message


def test_config_first_dispatch_helper_rejects_environment_overrides_before_runner_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Standalone shims retain the CLI environment-override boundary."""

    _config(tmp_path)
    imported = []
    module_name = "iteration41_environment_override_runner"
    module = types.ModuleType(module_name)
    module.run_runtime = lambda *_args, **_kwargs: imported.append(True)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, module_name, module)
    monkeypatch.setenv("BT_RUNTIME_MODE", "live")
    registry = _registry(tmp_path, runner_module=module_name)

    with pytest.raises(RuntimeConfigError) as caught:
        runtime_runner.dispatch_configured_runtime(tmp_path, registry)

    assert caught.value.code == PRESET_POLICY_VIOLATION
    assert caught.value.reason == "environment_override_not_allowed"
    assert imported == []


def test_config_first_dispatch_helper_hands_the_runner_a_sealed_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The compatibility helper validates first and still uses code-owned dispatch."""

    _config(tmp_path)
    calls = []
    module_name = "iteration41_config_first_dispatch_runner"
    module = types.ModuleType(module_name)

    def run_runtime(runtime_dir, *, registry, effective, **kwargs):
        calls.append((runtime_dir, registry, effective, kwargs))
        assert effective.config.strategy_id == "example.runner"
        assert effective.effective_digest
        return {"status": "LOCAL_REPLAY_PASS"}

    module.run_runtime = run_runtime
    monkeypatch.setitem(sys.modules, module_name, module)
    registry = _registry(tmp_path, runner_module=module_name)

    assert runtime_runner.dispatch_configured_runtime(tmp_path, registry) == {
        "status": "LOCAL_REPLAY_PASS"
    }
    assert len(calls) == 1


def test_sealed_runner_config_rechecks_policy_without_reopening_config_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _config(tmp_path)
    registry = _registry(tmp_path)
    effective = resolve_runtime_config(load_runtime_config(tmp_path, registry=registry), registry)

    def fail_path_load(*_args, **_kwargs):
        raise AssertionError("a sealed runner dispatch must not reopen config.yaml")

    monkeypatch.setattr("backtrader_runtime.registry.load_runtime_config", fail_path_load)
    resolved = resolve_runner_effective_config(tmp_path, registry, effective=effective)

    assert resolved.config is effective.config
    assert resolved.effective_digest == effective.effective_digest


def test_dispatch_rejects_a_forged_registration_before_attacker_module_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A public EffectiveRuntimeConfig must not choose an arbitrary import."""

    _config(tmp_path)
    trusted_name = "iteration41_trusted_runner"
    trusted = types.ModuleType(trusted_name)
    trusted.run_runtime = lambda runtime_dir, *, registry, effective: {  # type: ignore[attr-defined]
        "status": "TRUSTED"
    }
    monkeypatch.setitem(sys.modules, trusted_name, trusted)
    registry = _registry(tmp_path, runner_module=trusted_name)
    effective = resolve_runtime_config(load_runtime_config(tmp_path, registry=registry), registry)

    attacker_directory = tmp_path / "attacker-import"
    attacker_directory.mkdir()
    sentinel = tmp_path / "attacker-imported"
    (attacker_directory / "iteration41_attacker_runner.py").write_text(
        "from pathlib import Path\nPath({0!r}).write_text('imported', encoding='utf-8')\n".format(
            str(sentinel)
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(attacker_directory))
    forged_registration = RegisteredRuntime(
        runtime_dir=tmp_path,
        strategy_id="example.runner",
        allowed_presets=("replay",),
        runner_module="iteration41_attacker_runner",
    )

    with pytest.raises(RuntimeConfigError) as caught:
        dispatch_registered_runtime(replace(effective, registration=forged_registration), registry)

    assert caught.value.code == PRESET_POLICY_VIOLATION
    assert caught.value.reason == "effective_config_mismatch"
    assert not sentinel.exists()


def test_manual_config_or_effective_never_authorises_runner_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only a verified config.yaml loader may create dispatchable policy state."""

    attacker_name = "iteration41_manual_config_attacker"
    attacker = types.ModuleType(attacker_name)
    imported = []
    attacker.run_runtime = lambda runtime_dir, *, registry, effective: imported.append(runtime_dir)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, attacker_name, attacker)
    registry = _registry(tmp_path, runner_module=attacker_name)
    manual_config = RuntimeConfig(
        strategy_dir=tmp_path.resolve(),
        source_path=tmp_path / "config.yaml",
        strategy_id="example.runner",
        mode="simulation",
        preset="replay",
        parameters=MappingProxyType({}),
        secrets_ref="none",
        config_digest="0" * 64,
    )

    with pytest.raises(RuntimeConfigError) as caught:
        resolve_runtime_config(manual_config, registry)

    assert caught.value.code == PRESET_POLICY_VIOLATION
    assert caught.value.reason == "config_provenance_invalid"

    policy = get_preset_policy("replay")
    assert policy is not None
    registration = registry.require_runtime_dir(tmp_path)
    forged_effective = EffectiveRuntimeConfig(
        config=manual_config,
        registration=registration,
        policy=policy,
        order_route=policy.order_route,
        account_access=policy.account_access,
        required_capabilities=policy.required_capabilities,
        allows_network=policy.allows_network,
        allows_external_writes=policy.allows_external_writes,
        allows_production_writes=policy.allows_production_writes,
        allows_hypothetical_fills=policy.allows_hypothetical_fills,
        requires_approval=policy.requires_approval,
        requires_live_confirmation=policy.requires_live_confirmation,
        effective_digest="0" * 64,
    )

    with pytest.raises(RuntimeConfigError) as caught:
        dispatch_registered_runtime(forged_effective, registry)

    assert caught.value.code == PRESET_POLICY_VIOLATION
    assert caught.value.reason == "effective_config_mismatch"
    assert imported == []


def test_replaced_loaded_config_loses_private_loader_provenance(tmp_path: Path) -> None:
    _config(tmp_path)
    registry = _registry(tmp_path)
    loaded = load_runtime_config(tmp_path, registry=registry)

    with pytest.raises(RuntimeConfigError) as caught:
        resolve_runtime_config(replace(loaded), registry)

    assert caught.value.reason == "config_provenance_invalid"


def test_loaded_config_cannot_be_resolved_by_a_different_registry_instance(
    tmp_path: Path,
) -> None:
    """A descriptor seal belongs to the registry that checked its directory."""

    _config(tmp_path)
    original_registry = _registry(tmp_path)
    loaded = load_runtime_config(tmp_path, registry=original_registry)
    replacement_registry = _registry(tmp_path)

    with pytest.raises(RuntimeConfigError) as caught:
        resolve_runtime_config(loaded, replacement_registry)

    assert caught.value.reason == "config_provenance_invalid"


def test_replaced_effective_loses_private_resolver_provenance_before_runner_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """dataclasses.replace cannot turn a public effective copy into authority."""

    _config(tmp_path)
    calls = []
    module_name = "iteration41_replaced_effective_runner"
    module = types.ModuleType(module_name)
    module.run_runtime = lambda runtime_dir, *, registry, effective: calls.append(runtime_dir)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, module_name, module)
    registry = _registry(tmp_path, runner_module=module_name)
    effective = resolve_runtime_config(load_runtime_config(tmp_path, registry=registry), registry)

    with pytest.raises(RuntimeConfigError) as caught:
        dispatch_registered_runtime(replace(effective), registry)

    assert caught.value.reason == "effective_config_mismatch"
    assert calls == []


def test_dispatch_rejects_a_replaced_registered_directory_before_runner_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The pre/post runner identity seal is also a pre-import execution gate."""

    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    _config(runtime_dir)
    calls = []
    module_name = "iteration41_identity_guard_runner"
    module = types.ModuleType(module_name)
    module.run_runtime = lambda runtime_dir, *, registry, effective: calls.append(runtime_dir)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, module_name, module)
    registry = _registry(runtime_dir, runner_module=module_name)
    effective = resolve_runtime_config(
        load_runtime_config(runtime_dir, registry=registry), registry
    )

    runtime_dir.rename(tmp_path / "old-runtime")
    replacement = tmp_path / "runtime"
    replacement.mkdir()
    _config(replacement)

    with pytest.raises(RuntimeConfigError) as caught:
        dispatch_registered_runtime(effective, registry)

    assert caught.value.code == PRESET_POLICY_VIOLATION
    assert caught.value.reason == "config_directory_identity_changed"
    assert calls == []


@pytest.mark.skipif(os.name != "nt", reason="Windows directory lease coverage")
def test_windows_runner_directory_lease_blocks_path_swap_before_runner_side_effect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The runner pathname remains bound to the reviewed directory for its call."""

    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    _config(runtime_dir)
    old_runtime = tmp_path / "runtime-before-run"
    module_name = "iteration41_windows_directory_lease_runner"
    module = types.ModuleType(module_name)

    def run_runtime(
        runner_runtime_dir: Path, *, registry: RuntimeRegistry, effective: EffectiveRuntimeConfig
    ) -> dict:
        del registry, effective
        replacement = _attempt_directory_rename(runner_runtime_dir, old_runtime)
        (runner_runtime_dir / "runner-output.txt").write_text("reviewed", encoding="utf-8")
        return {"status": "LOCAL_REPLAY_PASS", "replacement": replacement}

    module.run_runtime = run_runtime
    monkeypatch.setitem(sys.modules, module_name, module)
    registry = _registry(runtime_dir, runner_module=module_name)
    effective = resolve_runtime_config(
        load_runtime_config(runtime_dir, registry=registry), registry
    )

    report = dispatch_registered_runtime(effective, registry)

    assert report == {"status": "LOCAL_REPLAY_PASS", "replacement": "blocked"}
    assert (runtime_dir / "runner-output.txt").read_text(encoding="utf-8") == "reviewed"
    assert not old_runtime.exists()
    assert _attempt_directory_rename(runtime_dir, old_runtime) == "renamed"
    assert (old_runtime / "runner-output.txt").read_text(encoding="utf-8") == "reviewed"


def test_descriptor_dispatch_contract_with_a_portable_fake_posix_lease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CI can verify path suppression even when the host is not POSIX."""

    _config(tmp_path)
    module_name = "iteration41_descriptor_dispatch_contract_runner"
    module = types.ModuleType(module_name)
    received = []

    class FakeRuntimeDirectoryCapability:
        instances = []

        def __init__(self, descriptor: int) -> None:
            self.descriptor = descriptor
            self.invalidated = False
            type(self).instances.append(self)

        def invalidate(self) -> None:
            self.invalidated = True

    def run_runtime(
        runtime_dir,
        *,
        registry: RuntimeRegistry,
        effective: EffectiveRuntimeConfig,
        runtime_directory,
    ) -> dict:
        received.append((runtime_dir, registry, effective, runtime_directory))
        return {"status": "LOCAL_REPLAY_PASS"}

    @contextmanager
    def fake_directory_lease(_registration):
        yield 2468

    module.run_runtime = run_runtime
    monkeypatch.setitem(sys.modules, module_name, module)
    registry = _registry(tmp_path, runner_module=module_name)
    effective = resolve_runtime_config(load_runtime_config(tmp_path, registry=registry), registry)
    monkeypatch.setattr(registry, "verified_runtime_directory", fake_directory_lease)
    monkeypatch.setattr(
        runtime_runner, "RuntimeDirectoryCapability", FakeRuntimeDirectoryCapability
    )

    assert dispatch_registered_runtime(effective, registry) == {"status": "LOCAL_REPLAY_PASS"}
    assert len(received) == 1
    runtime_dir, received_registry, received_effective, capability = received[0]
    assert runtime_dir is None
    assert received_registry is not registry
    assert received_effective is not effective
    assert received_effective.config.strategy_id == effective.config.strategy_id
    assert received_effective.effective_digest == effective.effective_digest
    assert capability.descriptor == 2468
    assert capability.invalidated is True

    with pytest.raises(RuntimeConfigError) as expired:
        resolve_runner_effective_config(None, received_registry, effective=received_effective)
    assert expired.value.reason == "runner_dispatch_context_expired"


def test_posix_dispatch_views_reject_all_normal_runtime_path_recovery_routes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A runner-facing POSIX contract has policy values but no mutable path."""

    _config(tmp_path)
    module_name = "iteration41_posix_path_view_rejection_runner"
    module = types.ModuleType(module_name)
    rejections = []

    class FakeRuntimeDirectoryCapability:
        def __init__(self, descriptor: int) -> None:
            self.descriptor = descriptor

        def invalidate(self) -> None:
            pass

    def expect_rejected(access) -> None:
        with pytest.raises(RuntimeConfigError) as caught:
            access()
        rejections.append(caught.value.reason)

    def run_runtime(
        runtime_dir,
        *,
        registry,
        effective,
        runtime_directory,
    ) -> dict:
        assert runtime_dir is None
        assert runtime_directory.descriptor == 97531
        assert effective.config.strategy_id == "example.runner"
        assert effective.config.parameters == {}
        assert effective.as_public_dict()["effective_digest"] == effective.effective_digest
        assert resolve_runner_effective_config(None, registry, effective=effective) is effective

        expect_rejected(lambda: effective.registration.runtime_dir)
        expect_rejected(lambda: effective.registration.directory_identity)
        expect_rejected(lambda: effective.config.strategy_dir)
        expect_rejected(lambda: effective.config.source_path)
        expect_rejected(lambda: registry.registrations)
        expect_rejected(lambda: registry.require_runtime_dir(tmp_path))
        return {"status": "LOCAL_REPLAY_PASS"}

    @contextmanager
    def fake_directory_lease(_registration):
        yield 97531

    module.run_runtime = run_runtime
    monkeypatch.setitem(sys.modules, module_name, module)
    registry = _registry(tmp_path, runner_module=module_name)
    effective = resolve_runtime_config(load_runtime_config(tmp_path, registry=registry), registry)
    monkeypatch.setattr(registry, "verified_runtime_directory", fake_directory_lease)
    monkeypatch.setattr(
        runtime_runner, "RuntimeDirectoryCapability", FakeRuntimeDirectoryCapability
    )

    assert dispatch_registered_runtime(effective, registry) == {"status": "LOCAL_REPLAY_PASS"}
    assert rejections == ["runner_runtime_path_access_denied"] * 6


@pytest.mark.skipif(
    os.name != "posix" or not hasattr(os, "O_DIRECTORY"),
    reason="POSIX directory capability coverage",
)
def test_posix_runtime_directory_capability_exposes_no_public_path_or_descriptor(
    tmp_path: Path,
) -> None:
    """The runner gets an operation capability, never a pathname or raw fd API."""

    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    _config(runtime_dir)
    registry = _registry(runtime_dir)
    registration = registry.registrations[0]

    with registry.verified_runtime_directory(registration) as directory_fd:
        assert directory_fd is not None
        capability = RuntimeDirectoryCapability(directory_fd)
        assert not hasattr(capability, "directory_fd")
        assert not hasattr(capability, "runtime_dir")
        assert not hasattr(capability, "__dict__")
        with pytest.raises(TypeError):
            os.fspath(capability)
        capability.write_text("audit/marker.txt", "reviewed")
        capability.invalidate()

    assert (runtime_dir / "audit" / "marker.txt").read_text(encoding="utf-8") == "reviewed"


@pytest.mark.skipif(
    os.name != "posix" or not hasattr(os, "O_DIRECTORY"),
    reason="POSIX directory capability coverage",
)
def test_posix_runner_capability_keeps_local_output_off_a_replacement_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A POSIX runner receives no mutable runtime pathname after fd acquisition."""

    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    _config(runtime_dir)
    old_runtime = tmp_path / "runtime-before-run"
    module_name = "iteration41_posix_directory_capability_runner"
    module = types.ModuleType(module_name)
    received_capabilities = []

    def run_runtime(
        runner_runtime_dir,
        *,
        registry: RuntimeRegistry,
        effective: EffectiveRuntimeConfig,
        runtime_directory: RuntimeDirectoryCapability,
    ) -> dict:
        del registry, effective
        assert runner_runtime_dir is None
        assert isinstance(runtime_directory, RuntimeDirectoryCapability)
        received_capabilities.append(runtime_directory)
        assert _attempt_directory_rename(runtime_dir, old_runtime) == "renamed"
        runtime_dir.mkdir()
        runtime_directory.write_text("runner/audit.txt", "reviewed")
        return {"status": "LOCAL_REPLAY_PASS"}

    module.run_runtime = run_runtime
    monkeypatch.setitem(sys.modules, module_name, module)
    registry = _registry(runtime_dir, runner_module=module_name)
    effective = resolve_runtime_config(
        load_runtime_config(runtime_dir, registry=registry), registry
    )

    with pytest.raises(RuntimeConfigError) as caught:
        dispatch_registered_runtime(effective, registry)

    # The final identity check still fails closed, but the runner's already
    # executed local side effect remained attached to the fd's original
    # directory rather than the attacker's same-name replacement.
    assert caught.value.reason == "config_directory_identity_changed"
    assert (old_runtime / "runner" / "audit.txt").read_text(encoding="utf-8") == "reviewed"
    assert not (runtime_dir / "runner" / "audit.txt").exists()
    with pytest.raises(RuntimeConfigError) as expired:
        received_capabilities[0].write_text("runner/late.txt", "late")
    assert expired.value.reason == "runtime_directory_capability_expired"


@pytest.mark.skipif(
    os.name != "posix" or not hasattr(os, "O_DIRECTORY"),
    reason="POSIX directory capability coverage",
)
def test_posix_runner_capability_rejects_a_symlinked_child_component(tmp_path: Path) -> None:
    """A capability never follows a runtime-relative symlink to write output."""

    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    _config(runtime_dir)
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (runtime_dir / "redirect").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("this platform does not permit test directory symlink creation")
    registry = _registry(runtime_dir)
    registration = registry.registrations[0]

    with registry.verified_runtime_directory(registration) as directory_fd:
        assert directory_fd is not None
        capability = RuntimeDirectoryCapability(directory_fd)
        with pytest.raises(RuntimeConfigError) as caught:
            capability.write_text("redirect/audit.txt", "must not escape")
        capability.invalidate()

    assert caught.value.reason == "runtime_directory_capability_io_failed"
    assert not (outside / "audit.txt").exists()


def test_effective_cannot_cross_to_a_new_registry_after_directory_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An old effective value cannot adopt a replacement directory's registry."""

    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    _config(runtime_dir)
    attacker_directory = tmp_path / "attacker"
    attacker_directory.mkdir()
    attacker_module_name = "iteration41_registry_swap_attacker"
    sentinel = tmp_path / "replacement-runner-imported"
    (attacker_directory / (attacker_module_name + ".py")).write_text(
        "from pathlib import Path\nPath({0!r}).write_text('imported', encoding='utf-8')\n".format(
            str(sentinel)
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(attacker_directory))
    original_registry = _registry(runtime_dir, runner_module=attacker_module_name)
    effective = resolve_runtime_config(
        load_runtime_config(runtime_dir, registry=original_registry), original_registry
    )

    runtime_dir.rename(tmp_path / "old-runtime")
    replacement = tmp_path / "runtime"
    replacement.mkdir()
    _config(replacement)
    replacement_registry = _registry(replacement, runner_module=attacker_module_name)

    with pytest.raises(RuntimeConfigError) as caught:
        dispatch_registered_runtime(effective, replacement_registry)

    assert caught.value.reason == "effective_config_mismatch"
    assert not sentinel.exists()


def test_shipped_inventory_runner_ignores_a_same_name_cwd_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A runner-only test source keeps fixed-file protection without a core guard."""

    import backtrader_runtime.inventory as runtime_inventory

    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    _config(runtime_dir)
    registration = RegisteredRuntime(
        runtime_dir=runtime_dir,
        strategy_id="example.runner",
        allowed_presets=("replay",),
        runner_module="examples.safe.run_runtime",
    )
    registry = RuntimeRegistry((registration,))
    effective = resolve_runtime_config(
        load_runtime_config(runtime_dir, registry=registry), registry
    )

    trusted_root = tmp_path / "trusted-source"
    trusted_runner = trusted_root / "examples" / "safe" / "run_runtime.py"
    trusted_runner.parent.mkdir(parents=True)
    trusted_runner.write_text(
        "from . import helper\n"
        "def run_runtime(runtime_dir, *, registry, effective):\n"
        "    return {'status': helper.STATUS}\n",
        encoding="utf-8",
    )
    (trusted_runner.parent / "helper.py").write_text(
        "STATUS = 'TRUSTED_INVENTORY_SOURCE'\n", encoding="utf-8"
    )
    assert not (trusted_root / "backtrader").exists()
    fake_cwd = tmp_path / "fake-cwd"
    fake_runner = fake_cwd / "examples" / "safe" / "run_runtime.py"
    fake_runner.parent.mkdir(parents=True)
    sentinel = tmp_path / "cwd-runner-imported"
    fake_runner.write_text(
        "from pathlib import Path\nPath({0!r}).write_text('imported', encoding='utf-8')\n".format(
            str(sentinel)
        ),
        encoding="utf-8",
    )
    unrelated_core_root = fake_cwd / "backtrader"
    unrelated_core_root.mkdir()
    unrelated_core = types.ModuleType("backtrader")
    unrelated_core.__file__ = str(unrelated_core_root / "__init__.py")
    unrelated_core.__path__ = [str(unrelated_core_root)]  # type: ignore[attr-defined]

    previous_examples = _public_examples_modules()
    monkeypatch.setitem(sys.modules, "backtrader", unrelated_core)
    monkeypatch.setattr(runtime_inventory, "SOURCE_ROOT", trusted_root)
    monkeypatch.setattr(runtime_inventory, "iteration41_runtime_registry", lambda: registry)
    monkeypatch.chdir(fake_cwd)
    monkeypatch.syspath_prepend(str(fake_cwd))
    previous_sys_path = tuple(sys.path)
    try:
        report = _dispatch_with_isolated_external_capabilities(effective, registry)
        assert report == {"status": "TRUSTED_INVENTORY_SOURCE"}
        assert not sentinel.exists()
        assert tuple(sys.path) == previous_sys_path
        _assert_public_examples_unchanged(previous_examples)
    finally:
        for name in tuple(sys.modules):
            if name == "examples" or name.startswith("examples."):
                sys.modules.pop(name, None)
        sys.modules.update(previous_examples)


def test_shipped_inventory_capability_imports_ignore_cwd_sdk_shadows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reviewed SDK allow-list wins over fake CWD provider packages."""

    import backtrader_runtime.inventory as runtime_inventory

    capability_modules = (
        "bt_api_py",
        "bt_api_execution",
        "bt_api_risk",
        "bt_api_monitor",
    )
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    _config(runtime_dir)
    registration = RegisteredRuntime(
        runtime_dir=runtime_dir,
        strategy_id="example.runner",
        allowed_presets=("replay",),
        runner_module="examples.safe.run_runtime",
        capability_modules=capability_modules,
    )
    registry = RuntimeRegistry((registration,))
    effective = resolve_runtime_config(
        load_runtime_config(runtime_dir, registry=registry), registry
    )

    trusted_root = tmp_path / "trusted-source"
    trusted_runner = trusted_root / "examples" / "safe" / "run_runtime.py"
    trusted_runner.parent.mkdir(parents=True)
    trusted_runner.write_text(
        "import bt_api_execution\n"
        "import bt_api_monitor\n"
        "import bt_api_py\n"
        "import bt_api_risk\n"
        "def run_runtime(runtime_dir, *, registry, effective):\n"
        "    return {\n"
        "        'status': 'LOCAL_REPLAY_PASS',\n"
        "        'sources': (\n"
        "            bt_api_py.STATUS,\n"
        "            bt_api_execution.STATUS,\n"
        "            bt_api_risk.STATUS,\n"
        "            bt_api_monitor.STATUS,\n"
        "        ),\n"
        "    }\n",
        encoding="utf-8",
    )
    trusted_sdk_root = tmp_path / "trusted-sdk"
    for module_name in capability_modules:
        package = trusted_sdk_root / module_name
        package.mkdir(parents=True)
        (package / "__init__.py").write_text(
            "STATUS = {0!r}\n".format("trusted-" + module_name), encoding="utf-8"
        )

    fake_cwd = tmp_path / "fake-cwd"
    fake_cwd.mkdir()
    sentinel = tmp_path / "cwd-sdk-shadow-imported"
    for module_name in capability_modules:
        package = fake_cwd / module_name
        package.mkdir()
        (package / "__init__.py").write_text(
            "from pathlib import Path\n"
            "Path({0!r}).write_text({1!r}, encoding='utf-8')\n"
            "raise AssertionError('CWD SDK shadow must not be imported')\n".format(
                str(sentinel), module_name
            ),
            encoding="utf-8",
        )

    monkeypatch.setattr(runtime_inventory, "SOURCE_ROOT", trusted_root)
    monkeypatch.setattr(runtime_inventory, "iteration41_runtime_registry", lambda: registry)
    monkeypatch.chdir(fake_cwd)
    monkeypatch.syspath_prepend(str(trusted_sdk_root))
    monkeypatch.syspath_prepend(str(fake_cwd))
    report = _dispatch_with_isolated_external_capabilities(effective, registry)

    assert report == {
        "status": "LOCAL_REPLAY_PASS",
        "sources": tuple("trusted-" + name for name in capability_modules),
    }
    assert not sentinel.exists()


def test_shipped_inventory_capability_guard_rejects_cached_cwd_sdk_shadow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cached foreign SDK package is rejected before the runner source loads."""

    import backtrader_runtime.inventory as runtime_inventory

    capability_modules = ("bt_api_py",)
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    _config(runtime_dir)
    registration = RegisteredRuntime(
        runtime_dir=runtime_dir,
        strategy_id="example.runner",
        allowed_presets=("replay",),
        runner_module="examples.safe.run_runtime",
        capability_modules=capability_modules,
    )
    registry = RuntimeRegistry((registration,))
    effective = resolve_runtime_config(
        load_runtime_config(runtime_dir, registry=registry), registry
    )

    trusted_root = tmp_path / "trusted-source"
    trusted_runner = trusted_root / "examples" / "safe" / "run_runtime.py"
    trusted_runner.parent.mkdir(parents=True)
    import_sentinel = tmp_path / "runner-source-imported"
    trusted_runner.write_text(
        "from pathlib import Path\nPath({0!r}).write_text('imported', encoding='utf-8')\n".format(
            str(import_sentinel)
        ),
        encoding="utf-8",
    )
    trusted_sdk_root = tmp_path / "trusted-sdk"
    trusted_package = trusted_sdk_root / "bt_api_py"
    trusted_package.mkdir(parents=True)
    (trusted_package / "__init__.py").write_text("STATUS = 'trusted'\n", encoding="utf-8")

    fake_cwd = tmp_path / "fake-cwd"
    fake_package = fake_cwd / "bt_api_py"
    fake_package.mkdir(parents=True)
    fake_initializer = fake_package / "__init__.py"
    fake_initializer.write_text("STATUS = 'fake'\n", encoding="utf-8")
    fake_module = types.ModuleType("bt_api_py")
    fake_module.__file__ = str(fake_initializer)
    fake_module.__path__ = [str(fake_package)]  # type: ignore[attr-defined]

    monkeypatch.setattr(runtime_inventory, "SOURCE_ROOT", trusted_root)
    monkeypatch.setattr(runtime_inventory, "iteration41_runtime_registry", lambda: registry)
    monkeypatch.chdir(fake_cwd)
    monkeypatch.syspath_prepend(str(trusted_sdk_root))
    monkeypatch.syspath_prepend(str(fake_cwd))
    with _isolated_external_capability_modules():
        sys.modules["bt_api_py"] = fake_module
        with pytest.raises(RuntimeConfigError) as caught:
            dispatch_registered_runtime(effective, registry)

        assert caught.value.reason == "capability_origin_mismatch"
        assert not import_sentinel.exists()


def test_shipped_inventory_capability_guard_rejects_unregistered_sdk_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A runner cannot expand its reviewed SDK import allow-list at runtime."""

    import backtrader_runtime.inventory as runtime_inventory

    capability_modules = ("bt_api_py",)
    unregistered_module = "bt_api_unreviewed"
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    _config(runtime_dir)
    registration = RegisteredRuntime(
        runtime_dir=runtime_dir,
        strategy_id="example.runner",
        allowed_presets=("replay",),
        runner_module="examples.safe.run_runtime",
        capability_modules=capability_modules,
    )
    registry = RuntimeRegistry((registration,))
    effective = resolve_runtime_config(
        load_runtime_config(runtime_dir, registry=registry), registry
    )

    trusted_root = tmp_path / "trusted-source"
    trusted_runner = trusted_root / "examples" / "safe" / "run_runtime.py"
    trusted_runner.parent.mkdir(parents=True)
    trusted_runner.write_text(
        "import importlib\n"
        "def run_runtime(runtime_dir, *, registry, effective):\n"
        "    importlib.import_module('bt_api_unreviewed')\n"
        "    return {'status': 'UNREACHABLE'}\n",
        encoding="utf-8",
    )

    fake_cwd = tmp_path / "fake-cwd"
    fake_package = fake_cwd / unregistered_module
    fake_package.mkdir(parents=True)
    sentinel = tmp_path / "unregistered-sdk-imported"
    (fake_package / "__init__.py").write_text(
        "from pathlib import Path\nPath({0!r}).write_text('imported', encoding='utf-8')\n".format(
            str(sentinel)
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(runtime_inventory, "SOURCE_ROOT", trusted_root)
    monkeypatch.setattr(runtime_inventory, "iteration41_runtime_registry", lambda: registry)
    monkeypatch.chdir(fake_cwd)
    monkeypatch.syspath_prepend(str(fake_cwd))
    with _isolated_external_capability_modules(), pytest.raises(RuntimeConfigError) as caught:
        dispatch_registered_runtime(effective, registry)

    assert caught.value.reason == "capability_module_not_registered"
    assert not sentinel.exists()


def test_shipped_inventory_capability_guard_rejects_preloaded_unregistered_sdk_module(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cached ambient SDK module cannot bypass the import finder."""

    import backtrader_runtime.inventory as runtime_inventory

    capability_modules = ("bt_api_py",)
    unregistered_module = "bt_api_unreviewed"
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    _config(runtime_dir)
    registration = RegisteredRuntime(
        runtime_dir=runtime_dir,
        strategy_id="example.runner",
        allowed_presets=("replay",),
        runner_module="examples.safe.run_runtime",
        capability_modules=capability_modules,
    )
    registry = RuntimeRegistry((registration,))
    effective = resolve_runtime_config(
        load_runtime_config(runtime_dir, registry=registry), registry
    )

    trusted_root = tmp_path / "trusted-source"
    trusted_runner = trusted_root / "examples" / "safe" / "run_runtime.py"
    trusted_runner.parent.mkdir(parents=True)
    import_sentinel = tmp_path / "runner-source-imported"
    trusted_runner.write_text(
        "from pathlib import Path\nPath({0!r}).write_text('imported', encoding='utf-8')\n".format(
            str(import_sentinel)
        ),
        encoding="utf-8",
    )

    fake_cwd = tmp_path / "fake-cwd"
    fake_package = fake_cwd / unregistered_module
    fake_package.mkdir(parents=True)
    fake_initializer = fake_package / "__init__.py"
    fake_initializer.write_text("STATUS = 'ambient'\n", encoding="utf-8")
    ambient_module = types.ModuleType(unregistered_module)
    ambient_module.__file__ = str(fake_initializer)
    ambient_module.__path__ = [str(fake_package)]  # type: ignore[attr-defined]

    monkeypatch.setattr(runtime_inventory, "SOURCE_ROOT", trusted_root)
    monkeypatch.setattr(runtime_inventory, "iteration41_runtime_registry", lambda: registry)
    monkeypatch.chdir(fake_cwd)
    monkeypatch.syspath_prepend(str(fake_cwd))
    with _isolated_external_capability_modules():
        # The clean test-worker cache must not weaken the runner's own cache
        # gate.  Deliberately preload an unregistered module after isolation,
        # then verify dispatch fails before runner source is imported.
        sys.modules[unregistered_module] = ambient_module
        with pytest.raises(RuntimeConfigError) as caught:
            dispatch_registered_runtime(effective, registry)

        assert caught.value.reason == "capability_module_not_registered"
        assert not import_sentinel.exists()


def test_shipped_inventory_capability_guard_blocks_meta_path_submodule_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An ambient finder cannot execute a child outside the pinned SDK package."""

    import backtrader_runtime.inventory as runtime_inventory

    capability_modules = ("bt_api_py",)
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    _config(runtime_dir)
    registration = RegisteredRuntime(
        runtime_dir=runtime_dir,
        strategy_id="example.runner",
        allowed_presets=("replay",),
        runner_module="examples.safe.run_runtime",
        capability_modules=capability_modules,
    )
    registry = RuntimeRegistry((registration,))
    effective = resolve_runtime_config(
        load_runtime_config(runtime_dir, registry=registry), registry
    )

    trusted_root = tmp_path / "trusted-source"
    trusted_runner = trusted_root / "examples" / "safe" / "run_runtime.py"
    trusted_runner.parent.mkdir(parents=True)
    runner_sentinel = tmp_path / "runner-source-imported"
    trusted_runner.write_text(
        "import bt_api_py.evil\n"
        "from pathlib import Path\n"
        "Path({0!r}).write_text('imported', encoding='utf-8')\n".format(str(runner_sentinel)),
        encoding="utf-8",
    )
    trusted_sdk_root = tmp_path / "trusted-sdk"
    trusted_package = trusted_sdk_root / "bt_api_py"
    trusted_package.mkdir(parents=True)
    (trusted_package / "__init__.py").write_text("STATUS = 'trusted'\n", encoding="utf-8")

    fake_cwd = tmp_path / "fake-cwd"
    fake_cwd.mkdir()
    finder_sentinel = tmp_path / "ambient-meta-finder-used"

    class AmbientChildFinder:
        def find_spec(self, fullname, path=None, target=None):
            del path, target
            if fullname == "bt_api_py.evil":
                finder_sentinel.write_text("called", encoding="utf-8")
            return

    monkeypatch.setattr(runtime_inventory, "SOURCE_ROOT", trusted_root)
    monkeypatch.setattr(runtime_inventory, "iteration41_runtime_registry", lambda: registry)
    monkeypatch.chdir(fake_cwd)
    monkeypatch.syspath_prepend(str(trusted_sdk_root))
    monkeypatch.syspath_prepend(str(fake_cwd))
    monkeypatch.setattr(sys, "meta_path", list(sys.meta_path) + [AmbientChildFinder()])
    with _isolated_external_capability_modules(), pytest.raises(RuntimeConfigError) as caught:
        dispatch_registered_runtime(effective, registry)

    assert caught.value.reason == "capability_origin_unavailable"
    assert not finder_sentinel.exists()
    assert not runner_sentinel.exists()


def test_actual_shipped_inventory_binding_never_executes_cwd_examples_sentinel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exercise the real inventory binding rather than a test-only module."""

    import backtrader_runtime.inventory as runtime_inventory

    fake_cwd = tmp_path / "fake-cwd"
    fake_source = fake_cwd / "examples" / "sample.py"
    fake_source.parent.mkdir(parents=True)
    sentinel = tmp_path / "cwd-sample-imported"
    fake_source.write_text(
        "from pathlib import Path\nPath({0!r}).write_text('imported', encoding='utf-8')\n".format(
            str(sentinel)
        ),
        encoding="utf-8",
    )
    previous_examples = _public_examples_modules()
    monkeypatch.chdir(fake_cwd)
    monkeypatch.syspath_prepend(str(fake_cwd))
    try:
        with _loaded_registered_runner(runtime_inventory.ITERATION41_SAMPLE_REGISTRATION) as module:
            assert (
                Path(module.__file__).resolve()
                == (runtime_inventory.SOURCE_ROOT / "examples" / "sample.py").resolve()
            )
            assert not sentinel.exists()
            _assert_public_examples_unchanged(previous_examples)
    finally:
        for name in tuple(sys.modules):
            if name == "examples" or name.startswith("examples."):
                sys.modules.pop(name, None)
        sys.modules.update(previous_examples)


def test_package_l2_fixture_binding_never_executes_cwd_runner_shadow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The isolated-wheel fixture gets the same fixed-file loader boundary."""

    import backtrader_runtime.inventory as runtime_inventory

    fake_cwd = tmp_path / "fake-cwd"
    fake_source = fake_cwd / "backtrader_runtime" / "_iteration41_l2_fixture" / "managed_013_3.py"
    fake_source.parent.mkdir(parents=True)
    sentinel = tmp_path / "cwd-package-fixture-imported"
    fake_source.write_text(
        "from pathlib import Path\nPath({0!r}).write_text('imported', encoding='utf-8')\n".format(
            str(sentinel)
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(fake_cwd)
    monkeypatch.syspath_prepend(str(fake_cwd))

    with _loaded_registered_runner(
        runtime_inventory.ITERATION41_PACKAGE_013_3_MANAGED_REPLAY_REGISTRATION
    ) as module:
        assert (
            Path(module.__file__).resolve()
            == (runtime_inventory.PACKAGE_L2_FIXTURE_ROOT / "managed_013_3.py").resolve()
        )
        assert module.__name__ == ("backtrader_runtime._iteration41_l2_fixture.managed_013_3")
        assert not sentinel.exists()


def test_managed_l2_capability_preflight_finds_a_real_missing_package_before_runner_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The public run path names an absent package before strategy or provider startup."""

    import backtrader_runtime.capability_imports as capability_imports
    import backtrader_runtime.inventory as runtime_inventory

    registration = runtime_inventory.ITERATION41_PACKAGE_013_3_MANAGED_REPLAY_REGISTRATION
    registry = runtime_inventory.iteration41_l2_fixture_registry()
    empty_deployment_root = tmp_path / "empty-deployment-root"
    empty_deployment_root.mkdir()
    original_init = capability_imports._CapabilityOriginResolver.__init__

    def isolated_init(resolver: object, modules: object, source_root: Path) -> None:
        original_init(resolver, modules, source_root)  # type: ignore[arg-type]
        resolver.search_roots = (empty_deployment_root,)  # type: ignore[attr-defined]
        resolver._deployment_meta_finders = ()  # type: ignore[attr-defined]

    monkeypatch.setattr(capability_imports._CapabilityOriginResolver, "__init__", isolated_init)
    runner_loads = []
    original_loader = runtime_runner._loaded_registered_runner

    @contextmanager
    def track_runner_load(*args: object, **kwargs: object):
        runner_loads.append(True)
        with original_loader(*args, **kwargs) as module:  # type: ignore[arg-type]
            yield module

    monkeypatch.setattr(runtime_runner, "_loaded_registered_runner", track_runner_load)
    stderr = io.StringIO()
    with _isolated_external_capability_modules():
        status = main(
            ["run", "--strategy-dir", str(registration.runtime_dir)],
            registry=registry,
            stdout=io.StringIO(),
            stderr=stderr,
        )

    payload = json.loads(stderr.getvalue())
    assert status == 2
    assert payload["reason"] == "capability_dependency_missing"
    assert payload["field_path"] == "runtime.capabilities.bt_api_execution"
    assert "bt_api_execution" in payload["message"]
    assert payload["diagnostic"]["provider_preflight_started"] is False
    action = payload["diagnostic"]["next_actions"][0]
    assert action["action"] == "install_runtime_dependency"
    assert action["command"] == [
        "bt-runtime",
        "run",
        "--strategy-dir",
        str(registration.runtime_dir),
    ]
    assert runner_loads == []


def test_managed_l2_capability_preflight_accepts_local_fake_packages_without_importing_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A complete local fake capability set passes the same origin-only preflight."""

    import backtrader_runtime.capability_imports as capability_imports
    import backtrader_runtime.inventory as runtime_inventory

    trusted_root = tmp_path / "trusted-deployment"
    trusted_root.mkdir()
    required_modules = ("bt_api_execution", "bt_api_risk", "bt_api_monitor")
    for module_name in required_modules:
        package = trusted_root / module_name
        package.mkdir()
        (package / "__init__.py").write_text(
            "from pathlib import Path\nPath({0!r}).write_text('imported', encoding='utf-8')\n".format(
                str(tmp_path / "package-initializer-ran")
            ),
            encoding="utf-8",
        )

    original_init = capability_imports._CapabilityOriginResolver.__init__

    def isolated_init(resolver: object, modules: object, source_root: Path) -> None:
        original_init(resolver, modules, source_root)  # type: ignore[arg-type]
        resolver.search_roots = (trusted_root,)  # type: ignore[attr-defined]
        resolver._deployment_meta_finders = ()  # type: ignore[attr-defined]

    monkeypatch.setattr(capability_imports._CapabilityOriginResolver, "__init__", isolated_init)
    registration = runtime_inventory.ITERATION41_PACKAGE_013_3_MANAGED_REPLAY_REGISTRATION

    with _isolated_external_capability_modules():
        missing_module = capability_imports.first_unavailable_trusted_capability_module(
            trusted_root,
            registration.capability_modules,
            required_modules,
        )
        assert not any(module_name in sys.modules for module_name in required_modules)

    assert missing_module is None
    assert not (tmp_path / "package-initializer-ran").exists()


def test_private_inventory_loader_keeps_foreign_examples_modules_during_runner_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Shipped runner execution cannot evict a preloaded public examples module."""

    import backtrader_runtime.inventory as runtime_inventory

    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    _config(runtime_dir)
    registration = RegisteredRuntime(
        runtime_dir=runtime_dir,
        strategy_id="example.runner",
        allowed_presets=("replay",),
        runner_module="examples.safe.run_runtime",
    )
    registry = RuntimeRegistry((registration,))
    effective = resolve_runtime_config(
        load_runtime_config(runtime_dir, registry=registry), registry
    )
    trusted_root = tmp_path / "trusted-source"
    runner_source = trusted_root / "examples" / "safe" / "run_runtime.py"
    runner_source.parent.mkdir(parents=True)
    foreign_name = "examples.foreign_runtime_sentinel"
    foreign = types.ModuleType(foreign_name)
    foreign.marker = "preserved"  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, foreign_name, foreign)
    runner_source.write_text(
        "import sys\n"
        "def run_runtime(runtime_dir, *, registry, effective):\n"
        "    foreign = sys.modules.get({0!r})\n"
        "    return {{'status': getattr(foreign, 'marker', 'missing')}}\n".format(foreign_name),
        encoding="utf-8",
    )
    before = _public_examples_modules()
    monkeypatch.setattr(runtime_inventory, "SOURCE_ROOT", trusted_root)
    monkeypatch.setattr(runtime_inventory, "iteration41_runtime_registry", lambda: registry)

    try:
        report = _dispatch_with_isolated_external_capabilities(effective, registry)
        assert report == {"status": "preserved"}
        _assert_public_examples_unchanged(before)
        assert sys.modules[foreign_name] is foreign
    finally:
        for name in tuple(sys.modules):
            if name == "examples" or name.startswith("examples."):
                sys.modules.pop(name, None)
        sys.modules.update(before)


def test_private_inventory_loader_restores_foreign_examples_modules_after_import_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed private runner import also leaves public examples untouched."""

    import backtrader_runtime.inventory as runtime_inventory

    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    _config(runtime_dir)
    registration = RegisteredRuntime(
        runtime_dir=runtime_dir,
        strategy_id="example.runner",
        allowed_presets=("replay",),
        runner_module="examples.safe.run_runtime",
    )
    registry = RuntimeRegistry((registration,))
    effective = resolve_runtime_config(
        load_runtime_config(runtime_dir, registry=registry), registry
    )
    trusted_root = tmp_path / "trusted-source"
    runner_source = trusted_root / "examples" / "safe" / "run_runtime.py"
    runner_source.parent.mkdir(parents=True)
    foreign_name = "examples.foreign_import_sentinel"
    foreign = types.ModuleType(foreign_name)
    foreign.marker = "preserved"  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, foreign_name, foreign)
    mutation_sentinel = tmp_path / "foreign-examples-was-evicted"
    runner_source.write_text(
        "import sys\n"
        "from pathlib import Path\n"
        "if getattr(sys.modules.get({0!r}), 'marker', None) != 'preserved':\n"
        "    Path({1!r}).write_text('evicted', encoding='utf-8')\n"
        "raise RuntimeError('intentional private loader failure')\n".format(
            foreign_name, str(mutation_sentinel)
        ),
        encoding="utf-8",
    )
    before = _public_examples_modules()
    monkeypatch.setattr(runtime_inventory, "SOURCE_ROOT", trusted_root)
    monkeypatch.setattr(runtime_inventory, "iteration41_runtime_registry", lambda: registry)

    try:
        with pytest.raises(RuntimeConfigError) as caught:
            _dispatch_with_isolated_external_capabilities(effective, registry)

        assert caught.value.reason == "runner_import_failed"
        assert not mutation_sentinel.exists()
        _assert_public_examples_unchanged(before)
        assert sys.modules[foreign_name] is foreign
        assert not any(name.startswith("_backtrader_runtime_inventory_") for name in sys.modules)
    finally:
        for name in tuple(sys.modules):
            if name == "examples" or name.startswith("examples."):
                sys.modules.pop(name, None)
        sys.modules.update(before)


def test_shipped_inventory_dispatch_rejects_a_cached_foreign_backtrader_module(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cached CWD Backtrader package fails before the runner source executes."""

    import backtrader_runtime.inventory as runtime_inventory

    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    _config(runtime_dir)
    registration = RegisteredRuntime(
        runtime_dir=runtime_dir,
        strategy_id="example.runner",
        allowed_presets=("replay",),
        runner_module="examples.safe.run_runtime",
    )
    registry = RuntimeRegistry((registration,))
    effective = resolve_runtime_config(
        load_runtime_config(runtime_dir, registry=registry), registry
    )
    trusted_root = tmp_path / "trusted-source"
    runner_source = trusted_root / "examples" / "safe" / "run_runtime.py"
    runner_source.parent.mkdir(parents=True)
    trusted_core = trusted_root / "backtrader"
    trusted_core.mkdir()
    (trusted_core / "__init__.py").write_text("# trusted test core\n", encoding="utf-8")
    import_sentinel = tmp_path / "runner-source-imported"
    runner_source.write_text(
        "from pathlib import Path\nPath({0!r}).write_text('imported', encoding='utf-8')\n".format(
            str(import_sentinel)
        ),
        encoding="utf-8",
    )
    fake_root = tmp_path / "fake-cwd" / "backtrader"
    fake_root.mkdir(parents=True)
    fake_module = types.ModuleType("backtrader")
    fake_module.__file__ = str(fake_root / "__init__.py")
    fake_module.__path__ = [str(fake_root)]  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "backtrader", fake_module)
    monkeypatch.setattr(runtime_inventory, "SOURCE_ROOT", trusted_root)
    monkeypatch.setattr(runtime_inventory, "iteration41_runtime_registry", lambda: registry)

    with _isolated_external_capability_modules(), pytest.raises(RuntimeConfigError) as caught:
        dispatch_registered_runtime(effective, registry)

    assert caught.value.reason == "backtrader_origin_mismatch"
    assert not import_sentinel.exists()


@pytest.mark.parametrize(
    "registration_name, expected_status",
    (
        ("ITERATION41_013_3_REGISTRATION", "LOCAL_REPLAY_PASS"),
        ("ITERATION41_014_1_REGISTRATION", "LOCAL_REPLAY_PASS"),
    ),
)
def test_real_legacy_replay_ignores_a_cwd_backtrader_shadow_in_a_fresh_process(
    tmp_path: Path, registration_name: str, expected_status: str
) -> None:
    """The dispatch-wide guards cover delayed core and SDK imports."""

    import backtrader_runtime.inventory as runtime_inventory

    registration = getattr(runtime_inventory, registration_name)
    runtime_dir = registration.runtime_dir
    config_path = runtime_dir / "config.yaml"
    if config_path.exists():
        pytest.skip("the fresh-process shadow test will not replace an operator config.yaml")

    fake_cwd = tmp_path / "fake-cwd"
    fake_backtrader = fake_cwd / "backtrader"
    fake_backtrader.mkdir(parents=True)
    sentinel = tmp_path / "cwd-backtrader-imported"
    (fake_backtrader / "__init__.py").write_text(
        "from pathlib import Path\n"
        "Path({0!r}).write_text('imported', encoding='utf-8')\n"
        "raise AssertionError('CWD backtrader shadow must not be imported')\n".format(
            str(sentinel)
        ),
        encoding="utf-8",
    )
    fake_sdk = fake_cwd / "bt_api_py"
    fake_sdk.mkdir()
    sdk_sentinel = tmp_path / "cwd-sdk-imported"
    (fake_sdk / "__init__.py").write_text(
        "from pathlib import Path\n"
        "Path({0!r}).write_text('imported', encoding='utf-8')\n"
        "raise AssertionError('CWD bt_api_py shadow must not be imported')\n".format(
            str(sdk_sentinel)
        ),
        encoding="utf-8",
    )
    program = """
import json
import os
import shutil
from pathlib import Path

from backtrader_runtime import load_runtime_config, resolve_runtime_config
from backtrader_runtime import inventory
from backtrader_runtime.runner import dispatch_registered_runtime

registration = getattr(inventory, os.environ['ITERATION41_REGISTRATION_NAME'])
runtime_dir = registration.runtime_dir
config_path = runtime_dir / 'config.yaml'
template = runtime_dir / 'config.example.yaml'
report_root = runtime_dir / 'reports'
existing_reports = set(report_root.iterdir()) if report_root.exists() else set()
config_path.write_bytes(template.read_bytes())
try:
    registry = inventory.iteration41_runtime_registry()
    effective = resolve_runtime_config(load_runtime_config(runtime_dir, registry=registry), registry)
    report = dispatch_registered_runtime(effective, registry)
    print('ITERATION41_RESULT:' + json.dumps({'status': report.get('status')}))
finally:
    if config_path.exists():
        config_path.unlink()
    if report_root.exists():
        for child in tuple(report_root.iterdir()):
            if child not in existing_reports:
                if child.is_dir():
                    shutil.rmtree(str(child))
                else:
                    child.unlink()
        if not existing_reports and not tuple(report_root.iterdir()):
            report_root.rmdir()
"""
    environment = os.environ.copy()
    previous_pythonpath = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = str(runtime_inventory.SOURCE_ROOT)
    environment["ITERATION41_REGISTRATION_NAME"] = registration_name
    if previous_pythonpath:
        environment["PYTHONPATH"] += os.pathsep + previous_pythonpath

    try:
        result = subprocess.run(
            [sys.executable, "-c", program],
            cwd=str(fake_cwd),
            env=environment,
            text=True,
            capture_output=True,
            timeout=_FRESH_REPLAY_SUBPROCESS_TIMEOUT_SECONDS,
            check=False,
        )
    finally:
        # A child killed by the timeout must not leave a test config behind.
        if config_path.exists():
            config_path.unlink()

    assert result.returncode == 0, result.stderr + "\n" + result.stdout
    result_lines = [
        line for line in result.stdout.splitlines() if line.startswith("ITERATION41_RESULT:")
    ]
    assert result_lines
    assert json.loads(result_lines[-1].split(":", 1)[1]) == {"status": expected_status}
    assert not sentinel.exists()
    assert not sdk_sentinel.exists()


def test_all_registered_runners_use_the_shared_sealed_effective_config_helper() -> None:
    """Keep a future runner from silently adding a second runtime config read."""

    registrations = iteration41_runtime_registry().registrations
    assert len(registrations) == 17
    ctp_private = runtime_inventory.ITERATION41_013_3_CTP_PRIVATE_READONLY_REGISTRATION
    assert ctp_private in registrations
    assert ctp_private.runner_module is None
    ctp_private_007 = runtime_inventory.ITERATION41_007_CTP_PRIVATE_READONLY_REGISTRATION
    assert ctp_private_007 in registrations
    assert ctp_private_007.runner_module is None
    assert ctp_private_007.sandbox_write_policy == "deny"
    assert ctp_private_007.available_capabilities == ()
    shadow_registration = runtime_inventory.ITERATION41_010_OKX_SHADOW_REGISTRATION
    assert shadow_registration in registrations
    assert shadow_registration.runner_module == "examples.010_live_examples.run_okx_shadow_runtime"
    for registration in registrations:
        if registration.runner_module is None:
            continue
        assert registration.runner_module is not None
        specification = importlib.util.find_spec(registration.runner_module)
        assert specification is not None
        assert specification.origin is not None
        source = Path(specification.origin).read_text(encoding="utf-8")

        assert "resolve_runner_effective_config" in source
        assert "load_runtime_config(" not in source
        assert "resolve_runtime_config(" not in source


def test_all_source_registered_runners_accept_the_posix_directory_capability_contract() -> None:
    """Keep source-runner POSIX dispatch from silently restoring a path argument."""

    all_registrations = iteration41_runtime_registry().registrations
    assert len(all_registrations) == 17
    package_backtests = tuple(
        registration
        for registration in all_registrations
        if registration.runtime_id
        == runtime_inventory.ITERATION41_PACKAGE_LOCAL_BACKTEST_RUNTIME_ID
    )
    assert package_backtests == (runtime_inventory.ITERATION41_PACKAGE_LOCAL_BACKTEST_REGISTRATION,)
    private_readonly = tuple(
        registration for registration in all_registrations if registration.runner_module is None
    )
    assert private_readonly == (
        runtime_inventory.ITERATION41_013_3_CTP_PRIVATE_READONLY_REGISTRATION,
        runtime_inventory.ITERATION41_007_CTP_PRIVATE_READONLY_REGISTRATION,
    )
    registrations = tuple(
        registration
        for registration in all_registrations
        if registration.runner_module is not None
        and registration.runner_module.startswith("examples.")
    )
    assert runtime_inventory.ITERATION41_007_CTP_PRIVATE_READONLY_REGISTRATION not in registrations
    assert runtime_inventory.ITERATION41_007_CTP_REGISTRATION in registrations
    assert runtime_inventory.ITERATION41_010_OKX_SHADOW_REGISTRATION in registrations
    assert len(registrations) + len(package_backtests) + len(private_readonly) == len(
        all_registrations
    )
    allowed_runtime_dir_consumers = {
        "resolve_runner_effective_config",
        "_require_managed_replay",
        "_evidence_directory",
    }
    for registration in registrations:
        assert registration.runner_module is not None
        specification = importlib.util.find_spec(registration.runner_module)
        assert specification is not None
        assert specification.origin is not None
        tree = ast.parse(Path(specification.origin).read_text(encoding="utf-8"))
        runners = [
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == registration.runner_entrypoint
        ]
        assert len(runners) == 1
        runner = runners[0]
        assert runner.args.posonlyargs == []
        assert [argument.arg for argument in runner.args.args] == ["runtime_dir"]
        assert len(runner.args.defaults) == 1
        assert isinstance(runner.args.defaults[0], ast.Name)
        assert runner.args.defaults[0].id == "DEFAULT_RUNTIME_DIR"
        assert runner.args.vararg is None
        assert [argument.arg for argument in runner.args.kwonlyargs] == [
            "registry",
            "effective",
            "runtime_directory",
        ]
        assert len(runner.args.kw_defaults) == 3
        assert all(
            isinstance(default, ast.Constant) and default.value is None
            for default in runner.args.kw_defaults
        )
        assert runner.args.kwarg is None

        consumers = []
        for call in ast.walk(runner):
            if not isinstance(call, ast.Call) or not any(
                isinstance(argument, ast.Name) and argument.id == "runtime_dir"
                for argument in call.args
            ):
                continue
            if isinstance(call.func, ast.Name):
                consumers.append(call.func.id)
            else:
                consumers.append("<attribute-or-dynamic>")
        assert set(consumers) <= allowed_runtime_dir_consumers

        def root_name(node):
            value = node
            while isinstance(value, ast.Attribute):
                value = value.value
            return value.id if isinstance(value, ast.Name) else None

        path_bearing_attributes = {
            "directory_identity",
            "runtime_dir",
            "runtime_dir_lookup_key",
            "source_path",
            "strategy_dir",
        }
        unsafe_accesses = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and node.attr in path_bearing_attributes
            and root_name(node)
            in {"effective", "config", "registration", "registry", "trusted_registry"}
        ]
        assert unsafe_accesses == []


def test_runner_is_rejected_when_no_code_owned_entrypoint_is_registered(tmp_path: Path) -> None:
    _config(tmp_path)
    registry = _registry(tmp_path)
    effective = resolve_runtime_config(load_runtime_config(tmp_path, registry=registry), registry)

    with pytest.raises(RuntimeConfigError) as caught:
        dispatch_registered_runtime(effective, registry)

    assert caught.value.code == PRESET_POLICY_VIOLATION
    assert caught.value.reason == "runner_not_registered"


def test_full_report_is_an_explicit_read_only_output_choice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _config(tmp_path)
    module_name = "iteration41_full_report_runner"
    module = types.ModuleType(module_name)
    module.run_runtime = lambda runtime_dir, *, registry, effective: {  # type: ignore[attr-defined]
        "status": "LOCAL_REPLAY_PASS",
        "nested": {"fixture": "complete"},
    }
    monkeypatch.setitem(sys.modules, module_name, module)
    stdout = io.StringIO()

    status = main(
        ["run", "--strategy-dir", str(tmp_path), "--full-report"],
        registry=_registry(tmp_path, runner_module=module_name),
        stdout=stdout,
        stderr=io.StringIO(),
    )

    assert status == 0
    report = json.loads(stdout.getvalue())["report"]
    assert report["detail"] == "full"
    assert report["result"]["nested"] == {"fixture": "complete"}


def test_runner_cannot_return_an_unstructured_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _config(tmp_path)
    module_name = "iteration41_bad_runner"
    module = types.ModuleType(module_name)
    module.run_runtime = lambda runtime_dir, *, registry, effective: None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, module_name, module)
    registry = _registry(tmp_path, runner_module=module_name)
    effective = resolve_runtime_config(load_runtime_config(tmp_path, registry=registry), registry)

    with pytest.raises(RuntimeConfigError) as caught:
        dispatch_registered_runtime(effective, registry)

    assert caught.value.reason == "runner_report_invalid"
