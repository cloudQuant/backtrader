"""Operator-path acceptance for the small configuration-first ``bt-runtime`` CLI.

These tests intentionally use only temporary, code-built registries and an
in-memory runner.  They exercise the user-facing command boundary without
claiming a provider, socket, account, or live deployment is available.
"""

from __future__ import annotations

import builtins
import importlib
import io
import json
import os
import sys
import types
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest

from backtrader_runtime import (
    EffectiveRuntimeConfig,
    RegisteredRuntime,
    RuntimeRegistry,
    RuntimeSet,
    bootstrap_runtime_config,
)
from backtrader_runtime.cli import main
from backtrader_runtime.policy import MANAGED_WRITE_CAPABILITIES


_RUNNER_MODULE = "iteration41_operator_flow_local_runner"


def _payload(stream: io.StringIO) -> Dict[str, Any]:
    return json.loads(stream.getvalue())


def _write_config(
    runtime_dir: Path,
    *,
    strategy_id: str,
    mode: str = "simulation",
    preset: str = "replay",
    secrets_ref: str = "none",
) -> None:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    (runtime_dir / "config.yaml").write_text(
        "config_schema_version: 4\n"
        "strategy:\n"
        "  id: {0}\n"
        "runtime:\n"
        "  mode: {1}\n"
        "  preset: {2}\n"
        "parameters: {{}}\n"
        "secrets_ref: {3}\n".format(strategy_id, mode, preset, secrets_ref),
        encoding="utf-8",
    )


def _install_local_runner(monkeypatch: pytest.MonkeyPatch) -> List[Optional[Path]]:
    """Install a no-I/O runner so ``run`` remains inside this unit test."""

    calls: List[Optional[Path]] = []
    module = types.ModuleType(_RUNNER_MODULE)

    def run_runtime(
        runtime_dir: Optional[Path],
        *,
        registry: RuntimeRegistry,
        effective: EffectiveRuntimeConfig,
        runtime_directory: Optional[object] = None,
    ) -> Dict[str, Any]:
        del registry, effective, runtime_directory
        calls.append(runtime_dir)
        return {
            "status": "LOCAL_OPERATOR_FIXTURE_COMPLETED",
            "external_network_requests": 0,
            "external_write_requests": 0,
            "evidence_boundary": "LOCAL_CLI_FIXTURE_ONLY",
        }

    module.run_runtime = run_runtime
    monkeypatch.setitem(sys.modules, _RUNNER_MODULE, module)
    return calls


def _forbid_provider_or_socket_imports(monkeypatch: pytest.MonkeyPatch) -> List[str]:
    """Fail if a CLI path attempts to load a provider/network implementation."""

    attempted: List[str] = []
    original_import = builtins.__import__
    original_import_module = importlib.import_module

    def reject(name: str) -> None:
        if (
            name == "socket"
            or name == "backtrader"
            or name.startswith(("bt_api_py.", "backtrader."))
        ):
            attempted.append(name)
            raise AssertionError("operator CLI acceptance must not import " + name)

    def guarded_import(
        name: str,
        globals_value: object = None,
        locals_value: object = None,
        fromlist: Tuple[str, ...] = (),
        level: int = 0,
    ) -> object:
        reject(name)
        return original_import(name, globals_value, locals_value, fromlist, level)

    def guarded_import_module(name: str, package: object = None) -> object:
        reject(name)
        return original_import_module(name, package)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    monkeypatch.setattr(importlib, "import_module", guarded_import_module)
    return attempted


def _forbid_configured_runner_import(monkeypatch: pytest.MonkeyPatch) -> List[str]:
    """Record any attempt to import this test's registered runner."""

    attempted: List[str] = []
    original_import_module = importlib.import_module

    def guarded_import_module(name: str, package: object = None) -> object:
        if name == _RUNNER_MODULE:
            attempted.append(name)
            raise AssertionError("offline doctor must not import its configured runner")
        return original_import_module(name, package)

    monkeypatch.setattr(importlib, "import_module", guarded_import_module)
    return attempted


def _replay_registration(runtime_dir: Path, strategy_id: str) -> RegisteredRuntime:
    return RegisteredRuntime(
        runtime_dir=runtime_dir,
        strategy_id=strategy_id,
        allowed_presets=("replay",),
        runner_module=_RUNNER_MODULE,
    )


@pytest.mark.parametrize("middle_command", ("doctor", "validate"))
def test_first_run_needs_at_most_three_top_level_commands_without_mode_flags(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    middle_command: str,
) -> None:
    runtime_dir = tmp_path / "replay-runtime"
    runtime_dir.mkdir()
    strategy_id = "operator.normal_replay"
    registry = RuntimeRegistry((_replay_registration(runtime_dir, strategy_id),))
    runner_calls = _install_local_runner(monkeypatch)
    forbidden_imports = _forbid_provider_or_socket_imports(monkeypatch)

    commands = (
        ["bootstrap", "--strategy-dir", str(runtime_dir)],
        [middle_command, "--strategy-dir", str(runtime_dir)],
        ["run", "--strategy-dir", str(runtime_dir)],
    )
    results = []
    for command in commands:
        stdout = io.StringIO()
        stderr = io.StringIO()
        status = main(command, registry=registry, environ={}, stdout=stdout, stderr=stderr)
        results.append((status, _payload(stdout), stderr.getvalue()))

    assert len(commands) == 3
    assert [result[0] for result in results] == [0, 0, 0]
    assert all(result[2] == "" for result in results)
    assert results[0][1]["mode"] == "simulation"
    assert results[0][1]["preset"] == "replay"
    assert results[1][1]["status"] == ("diagnostic" if middle_command == "doctor" else "valid")
    assert results[2][1]["status"] == "completed"
    assert results[2][1]["report"]["result"]["external_network_requests"] == 0
    assert results[2][1]["report"]["result"]["external_write_requests"] == 0
    assert runner_calls == [None if os.name == "posix" else runtime_dir.resolve()]
    assert forbidden_imports == []


def test_existing_config_needs_only_doctor_then_run_and_keeps_the_route_offline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_dir = tmp_path / "existing-replay-runtime"
    strategy_id = "operator.existing_replay"
    _write_config(runtime_dir, strategy_id=strategy_id)
    registry = RuntimeRegistry((_replay_registration(runtime_dir, strategy_id),))
    runner_calls = _install_local_runner(monkeypatch)
    forbidden_imports = _forbid_provider_or_socket_imports(monkeypatch)

    commands = (
        ["doctor", "--strategy-dir", str(runtime_dir)],
        ["run", "--strategy-dir", str(runtime_dir)],
    )
    payloads = []
    for command in commands:
        stdout = io.StringIO()
        status = main(command, registry=registry, environ={}, stdout=stdout, stderr=io.StringIO())
        assert status == 0
        payloads.append(_payload(stdout))

    assert len(commands) == 2
    summary = payloads[0]["diagnostic"]["operator_summary"]
    assert summary == {
        "mode": "simulation",
        "preset": "replay",
        "destination": "local_runtime",
        "environment": "offline",
        "write_boundary": "zero_external_writes",
        "pnl_source": "not_applicable_without_external_fills",
        "required_capabilities": [],
        "requires_approval": False,
    }
    assert payloads[0]["diagnostic"]["next_actions"][0]["command"] == [
        "bt-runtime",
        "run",
        "--strategy-dir",
        str(runtime_dir),
    ]
    assert payloads[1]["report"]["result"]["status"] == "LOCAL_OPERATOR_FIXTURE_COMPLETED"
    assert runner_calls == [None if os.name == "posix" else runtime_dir.resolve()]
    assert forbidden_imports == []


def test_doctor_distinguishes_normal_and_offline_managed_fake_replay_without_importing_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    normal_dir = tmp_path / "normal-replay"
    managed_dir = tmp_path / "managed-replay"
    normal_id = "operator.normal_replay"
    managed_id = "operator.offline_managed_replay"
    _write_config(normal_dir, strategy_id=normal_id)
    _write_config(managed_dir, strategy_id=managed_id)
    registry = RuntimeRegistry(
        (
            _replay_registration(normal_dir, normal_id),
            RegisteredRuntime(
                runtime_dir=managed_dir,
                strategy_id=managed_id,
                allowed_presets=("replay",),
                available_capabilities=MANAGED_WRITE_CAPABILITIES,
                offline_managed_execution=True,
                runner_module=_RUNNER_MODULE,
            ),
        )
    )
    forbidden_imports = _forbid_provider_or_socket_imports(monkeypatch)

    summaries = {}
    for label, runtime_dir in (("normal", normal_dir), ("managed", managed_dir)):
        stdout = io.StringIO()
        status = main(
            ["doctor", "--strategy-dir", str(runtime_dir)],
            registry=registry,
            environ={},
            stdout=stdout,
            stderr=io.StringIO(),
        )
        assert status == 0
        diagnostic = _payload(stdout)["diagnostic"]
        assert diagnostic["offline"] is True
        assert diagnostic["provider_preflight_started"] is False
        assert diagnostic["next_actions"][0]["command"] == [
            "bt-runtime",
            "run",
            "--strategy-dir",
            str(runtime_dir),
        ]
        summaries[label] = diagnostic["operator_summary"]

    assert summaries["normal"]["destination"] == "local_runtime"
    assert summaries["normal"]["write_boundary"] == "zero_external_writes"
    assert summaries["normal"]["pnl_source"] == "not_applicable_without_external_fills"
    assert summaries["managed"] == {
        "mode": "simulation",
        "preset": "replay",
        "destination": "offline_fake_provider_managed_execution",
        "environment": "offline",
        "write_boundary": "zero_external_writes",
        "pnl_source": "not_applicable_without_external_fills",
        "required_capabilities": list(MANAGED_WRITE_CAPABILITIES),
        "requires_approval": False,
    }
    assert forbidden_imports == []


def test_doctor_reports_unapproved_live_route_as_blocked_without_a_run_shortcut(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_dir = tmp_path / "unapproved-live"
    strategy_id = "operator.unapproved_live"
    _write_config(
        runtime_dir,
        strategy_id=strategy_id,
        mode="live",
        preset="managed_live_direct",
        secrets_ref="runtime_secrets",
    )
    registry = RuntimeRegistry(
        (
            RegisteredRuntime(
                runtime_dir=runtime_dir,
                strategy_id=strategy_id,
                allowed_presets=("managed_live_direct",),
                allowed_secrets_refs=("runtime_secrets",),
                available_capabilities=MANAGED_WRITE_CAPABILITIES,
                runner_module=_RUNNER_MODULE,
            ),
        )
    )
    forbidden_imports = _forbid_provider_or_socket_imports(monkeypatch)
    stderr = io.StringIO()

    status = main(
        ["doctor", "--strategy-dir", str(runtime_dir)],
        registry=registry,
        environ={},
        stdout=io.StringIO(),
        stderr=stderr,
    )

    assert status == 2
    payload = _payload(stderr)
    assert payload["reason"] == "approval_receipt_missing"
    diagnostic = payload["diagnostic"]
    assert diagnostic["offline"] is True
    assert diagnostic["provider_preflight_started"] is False
    assert diagnostic["operator_summary"] == {
        "mode": "live",
        "preset": "managed_live_direct",
        "destination": "managed_execution:direct_provider",
        "environment": "production",
        "write_boundary": "blocked_before_external_writes",
        "pnl_source": "not_started_provider_reconciliation_required",
        "required_capabilities": list(MANAGED_WRITE_CAPABILITIES),
        "requires_approval": True,
        "admission_status": "blocked",
    }
    assert diagnostic["blockers"] == [
        {
            "field_path": "runtime.preset",
            "reason": "approval_receipt_missing",
            "message": "the registered write-capable profile has no trusted approval receipt",
        }
    ]
    assert diagnostic["next_actions"][0]["action"] == "review_live_contract"
    assert "--confirm-live" not in diagnostic["next_actions"][0]["note"]
    assert "cannot bypass" in diagnostic["next_actions"][0]["note"]
    assert "command" not in diagnostic["next_actions"][0]
    assert forbidden_imports == []


def test_doctor_aggregates_live_config_environment_and_contract_blockers_offline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A validly parsed live config exposes independent local blockers together."""

    runtime_dir = tmp_path / "live-blocker-aggregate"
    strategy_id = "operator.live_blocker_aggregate"
    _write_config(
        runtime_dir,
        strategy_id=strategy_id,
        mode="live",
        preset="managed_live_direct",
        secrets_ref="runtime_secrets",
    )
    registry = RuntimeRegistry(
        (
            RegisteredRuntime(
                runtime_dir=runtime_dir,
                strategy_id=strategy_id,
                allowed_presets=("managed_live_direct",),
                runner_module=_RUNNER_MODULE,
            ),
        )
    )
    forbidden_imports = _forbid_provider_or_socket_imports(monkeypatch)
    runner_imports = _forbid_configured_runner_import(monkeypatch)
    stderr = io.StringIO()

    status = main(
        ["doctor", "--strategy-dir", str(runtime_dir)],
        registry=registry,
        environ={
            "BT_RUNTIME_MODE": "simulation",
            "BACKTRADER_RUNTIME_PRESET": "replay",
        },
        stdout=io.StringIO(),
        stderr=stderr,
    )

    assert status == 2
    payload = _payload(stderr)
    assert payload["reason"] == "secrets_ref_not_registered"
    diagnostic = payload["diagnostic"]
    assert diagnostic["offline"] is True
    assert diagnostic["provider_preflight_started"] is False
    assert diagnostic["operator_summary"]["mode"] == "live"
    assert diagnostic["operator_summary"]["preset"] == "managed_live_direct"
    assert diagnostic["operator_summary"]["admission_status"] == "blocked"
    assert [(item["field_path"], item["reason"]) for item in diagnostic["blockers"]] == [
        ("secrets_ref", "secrets_ref_not_registered"),
        ("runtime.preset", "approval_receipt_missing"),
        ("runtime.preset", "required_capability_not_declared"),
        ("environment.BT_RUNTIME_MODE", "environment_override_not_allowed"),
        ("environment.BACKTRADER_RUNTIME_PRESET", "environment_override_not_allowed"),
    ]
    assert [item["action"] for item in diagnostic["next_actions"]] == [
        "review_secret_reference",
        "review_live_contract",
        "remove_environment_override",
        "remove_environment_override",
    ]
    assert "runtime_secrets" not in json.dumps(payload).lower()
    assert runner_imports == []
    assert forbidden_imports == []


@pytest.mark.parametrize("override", ("--mode=live", "--preset=managed_live_direct"))
@pytest.mark.parametrize("command", ("validate", "doctor", "run"))
def test_cli_mode_and_preset_override_flags_are_rejected_before_runtime_loading(
    tmp_path: Path,
    command: str,
    override: str,
) -> None:
    runtime_dir = tmp_path / "override-flags"
    strategy_id = "operator.override_flags"
    _write_config(runtime_dir, strategy_id=strategy_id)
    registry = RuntimeRegistry((_replay_registration(runtime_dir, strategy_id),))
    stderr = io.StringIO()

    status = main(
        [command, "--strategy-dir", str(runtime_dir), override],
        registry=registry,
        environ={},
        stdout=io.StringIO(),
        stderr=stderr,
    )

    assert status == 2
    assert _payload(stderr)["reason"] == "cli_override_not_allowed"


@pytest.mark.parametrize(
    "environment_name",
    (
        "BT_RUNTIME_MODE",
        "BT_RUNTIME_PRESET",
        "BACKTRADER_RUNTIME_MODE",
        "BACKTRADER_RUNTIME_PRESET",
    ),
)
def test_environment_mode_and_preset_overrides_are_rejected_after_static_validation(
    tmp_path: Path,
    environment_name: str,
) -> None:
    runtime_dir = tmp_path / "override-environment"
    strategy_id = "operator.override_environment"
    _write_config(runtime_dir, strategy_id=strategy_id)
    registry = RuntimeRegistry((_replay_registration(runtime_dir, strategy_id),))
    stderr = io.StringIO()

    status = main(
        ["validate", "--strategy-dir", str(runtime_dir)],
        registry=registry,
        environ={environment_name: "attempted-override"},
        stdout=io.StringIO(),
        stderr=stderr,
    )

    assert status == 2
    rejected = _payload(stderr)
    assert rejected["reason"] == "environment_override_not_allowed"
    assert rejected["field_path"] == "environment." + environment_name


def test_batch_bootstrap_conflict_writes_no_other_runtime_config(tmp_path: Path) -> None:
    conflict_dir = tmp_path / "conflict"
    matching_dir = tmp_path / "matching"
    missing_dir = tmp_path / "missing"
    for directory in (conflict_dir, matching_dir, missing_dir):
        directory.mkdir()
    conflict_id = "operator.batch_conflict"
    matching_id = "operator.batch_matching"
    missing_id = "operator.batch_missing"
    registrations = (
        _replay_registration(conflict_dir, conflict_id),
        _replay_registration(matching_dir, matching_id),
        _replay_registration(missing_dir, missing_id),
    )
    registry = RuntimeRegistry(
        registrations,
        runtime_sets=(
            RuntimeSet(
                name="operator-reviewed-set",
                runtime_ids=(conflict_id, matching_id, missing_id),
            ),
        ),
    )
    original_conflict = "operator-owned config must survive\n"
    (conflict_dir / "config.yaml").write_text(original_conflict, encoding="utf-8")
    # This byte-for-byte canonical config models a prior safe batch retry. It
    # must remain untouched when another member makes preflight fail.
    bootstrap_runtime_config(matching_dir, registry, "replay")
    original_matching = (matching_dir / "config.yaml").read_bytes()
    stderr = io.StringIO()

    status = main(
        ["bootstrap", "--runtime-set", "operator-reviewed-set"],
        registry=registry,
        environ={},
        stdout=io.StringIO(),
        stderr=stderr,
    )

    assert status == 2
    payload = _payload(stderr)
    assert payload["status"] == "preflight_failed"
    assert [item["status"] for item in payload["items"]] == [
        "conflict",
        "already_matching",
        "not_written",
    ]
    assert (conflict_dir / "config.yaml").read_text(encoding="utf-8") == original_conflict
    assert (matching_dir / "config.yaml").read_bytes() == original_matching
    assert not (missing_dir / "config.yaml").exists()
