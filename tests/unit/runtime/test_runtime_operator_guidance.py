"""Operator guidance contracts for the strict configuration-first CLI.

These are deliberately local tests.  A rejected command must provide one
safe next step without importing the code-owned runner, opening a socket, or
turning an override attempt into a different effective configuration.
"""

from __future__ import annotations

import builtins
import importlib
import io
import json
import socket
import sys
from pathlib import Path
from typing import List

import pytest

import backtrader_runtime
from backtrader_runtime import RegisteredRuntime, RuntimeRegistry
from backtrader_runtime.cli import _next_actions_for_error, main
from backtrader_runtime.errors import PRESET_POLICY_VIOLATION, RuntimeConfigError


_RUNNER_MODULE = "iteration41_operator_guidance_runner"


def test_runner_guidance_without_registry_stays_generic(tmp_path: Path) -> None:
    error = RuntimeConfigError(
        PRESET_POLICY_VIOLATION,
        "runner unavailable",
        reason="runner_not_registered",
    )

    actions = _next_actions_for_error(error, tmp_path)

    assert actions[0]["action"] == "review_registration"


def _payload(stream: io.StringIO) -> dict:
    return json.loads(stream.getvalue())


def _registry(runtime_dir: Path, *, secrets: bool = False) -> RuntimeRegistry:
    return RuntimeRegistry(
        (
            RegisteredRuntime(
                runtime_dir=runtime_dir,
                strategy_id="operator.guidance",
                allowed_presets=("replay",),
                allowed_secrets_refs=("none", "runtime_secrets") if secrets else ("none",),
                runner_module=_RUNNER_MODULE,
            ),
        )
    )


def _write_config(
    runtime_dir: Path,
    *,
    mode: str = "simulation",
    preset: str = "replay",
    secrets_ref: str = "none",
) -> None:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    (runtime_dir / "config.yaml").write_text(
        "config_schema_version: 4\n"
        "strategy:\n"
        "  id: operator.guidance\n"
        "runtime:\n"
        "  mode: {0}\n"
        "  preset: {1}\n"
        "parameters: {{}}\n"
        "secrets_ref: {2}\n".format(mode, preset, secrets_ref),
        encoding="utf-8",
    )


def _forbid_runner_import(monkeypatch: pytest.MonkeyPatch) -> List[str]:
    attempted: List[str] = []
    original = importlib.import_module

    def guarded(name: str, package: object = None) -> object:
        if name == _RUNNER_MODULE:
            attempted.append(name)
            raise AssertionError("a rejected command must not import its runner")
        return original(name, package)

    monkeypatch.setattr(importlib, "import_module", guarded)
    return attempted


def test_fresh_cli_module_keeps_doctor_runner_lazy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Offline doctor must not load the dispatch module merely by importing CLI."""

    runtime_dir = tmp_path / "runner-lazy-doctor"
    _write_config(runtime_dir)
    attempted = []
    original_import = builtins.__import__

    def guarded_import(
        name: str,
        globals_value: object = None,
        locals_value: object = None,
        fromlist: tuple = (),
        level: int = 0,
    ) -> object:
        if name == "runner" and level == 1:
            attempted.append(name)
            raise AssertionError("doctor must not import backtrader_runtime.runner")
        return original_import(name, globals_value, locals_value, fromlist, level)

    monkeypatch.delitem(sys.modules, "backtrader_runtime.cli", raising=False)
    monkeypatch.delitem(sys.modules, "backtrader_runtime.runner", raising=False)
    monkeypatch.delattr(backtrader_runtime, "cli", raising=False)
    monkeypatch.delattr(backtrader_runtime, "runner", raising=False)
    monkeypatch.setattr(builtins, "__import__", guarded_import)
    fresh_cli = importlib.import_module("backtrader_runtime.cli")
    stderr = io.StringIO()

    status = fresh_cli.main(
        ["doctor", "--strategy-dir", str(runtime_dir)],
        registry=_registry(runtime_dir),
        environ={},
        stdout=io.StringIO(),
        stderr=stderr,
    )

    assert status == 0
    assert stderr.getvalue() == ""
    assert attempted == []
    assert "backtrader_runtime.runner" not in sys.modules


@pytest.mark.parametrize("command", ("validate", "doctor", "run"))
def test_missing_config_has_the_same_safe_bootstrap_next_step_without_runner_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
) -> None:
    runtime_dir = tmp_path / "registered-runtime"
    runtime_dir.mkdir()
    attempted_imports = _forbid_runner_import(monkeypatch)
    socket_attempts = []

    def reject_socket(*args: object, **kwargs: object) -> object:
        socket_attempts.append((args, kwargs))
        raise AssertionError("a rejected command must not create a socket")

    monkeypatch.setattr(socket, "socket", reject_socket)
    stderr = io.StringIO()

    status = main(
        [command, "--strategy-dir", str(runtime_dir)],
        registry=_registry(runtime_dir),
        environ={},
        stdout=io.StringIO(),
        stderr=stderr,
    )

    assert status == 2
    rejection = _payload(stderr)
    assert rejection["reason"] == "missing_config"
    assert rejection["diagnostic"] == {
        "offline": True,
        "provider_preflight_started": False,
        "next_actions": [
            {
                "action": "bootstrap",
                "command": ["bt-runtime", "bootstrap", "--strategy-dir", str(runtime_dir)],
                "note": "creates only the reviewed safe config; it never overwrites an existing file",
            }
        ],
    }
    assert attempted_imports == []
    assert socket_attempts == []


def test_doctor_aggregates_missing_config_and_environment_override_blockers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing required config and ignored overrides are independently actionable."""

    runtime_dir = tmp_path / "missing-config-and-overrides"
    runtime_dir.mkdir()
    attempted_imports = _forbid_runner_import(monkeypatch)
    stderr = io.StringIO()

    status = main(
        ["doctor", "--strategy-dir", str(runtime_dir)],
        registry=_registry(runtime_dir),
        environ={
            "BT_RUNTIME_MODE": "live",
            "BACKTRADER_RUNTIME_PRESET": "managed_live_direct",
        },
        stdout=io.StringIO(),
        stderr=stderr,
    )

    assert status == 2
    rejection = _payload(stderr)
    assert rejection["reason"] == "missing_config"
    diagnostic = rejection["diagnostic"]
    assert diagnostic["offline"] is True
    assert diagnostic["provider_preflight_started"] is False
    assert [(item["field_path"], item["reason"]) for item in diagnostic["blockers"]] == [
        ("config.yaml", "missing_config"),
        ("environment.BT_RUNTIME_MODE", "environment_override_not_allowed"),
        ("environment.BACKTRADER_RUNTIME_PRESET", "environment_override_not_allowed"),
    ]
    assert [item["action"] for item in diagnostic["next_actions"]] == [
        "bootstrap",
        "remove_environment_override",
        "remove_environment_override",
    ]
    assert not (runtime_dir / "config.yaml").exists()
    assert attempted_imports == []


def test_bootstrap_unregistered_directory_explains_that_cwd_cannot_be_a_route(
    tmp_path: Path,
) -> None:
    external_dir = tmp_path / "not-reviewed"
    external_dir.mkdir()
    stderr = io.StringIO()

    status = main(
        ["bootstrap", "--strategy-dir", str(external_dir)],
        registry=RuntimeRegistry(()),
        environ={},
        stdout=io.StringIO(),
        stderr=stderr,
    )

    assert status == 2
    rejection = _payload(stderr)
    assert rejection["reason"] == "runtime_not_registered"
    action = rejection["diagnostic"]["next_actions"]
    assert action[0]["action"] == "review_registration"
    assert "current directory" in action[0]["note"]
    assert "AI output" in action[0]["note"]
    assert "command" not in action[0]


def test_bootstrap_existing_config_preserves_it_and_suggests_only_offline_doctor(
    tmp_path: Path,
) -> None:
    runtime_dir = tmp_path / "existing-config"
    _write_config(runtime_dir)
    original = (runtime_dir / "config.yaml").read_bytes()
    stderr = io.StringIO()

    status = main(
        ["bootstrap", "--strategy-dir", str(runtime_dir)],
        registry=_registry(runtime_dir),
        environ={},
        stdout=io.StringIO(),
        stderr=stderr,
    )

    assert status == 2
    rejection = _payload(stderr)
    assert rejection["reason"] == "config_exists"
    action = rejection["diagnostic"]["next_actions"][0]
    assert action["action"] == "review_existing_config"
    assert action["command"] == ["bt-runtime", "doctor", "--strategy-dir", str(runtime_dir)]
    assert (runtime_dir / "config.yaml").read_bytes() == original


@pytest.mark.parametrize("command", ("validate", "doctor", "run"))
def test_mode_preset_mismatch_gives_a_config_review_step_before_runner_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
) -> None:
    runtime_dir = tmp_path / "mode-mismatch"
    _write_config(runtime_dir, mode="live", preset="replay")
    attempted_imports = _forbid_runner_import(monkeypatch)
    stderr = io.StringIO()

    status = main(
        [command, "--strategy-dir", str(runtime_dir)],
        registry=_registry(runtime_dir),
        environ={},
        stdout=io.StringIO(),
        stderr=stderr,
    )

    assert status == 2
    rejection = _payload(stderr)
    assert rejection["reason"] == "mode_preset_mismatch"
    action = rejection["diagnostic"]["next_actions"][0]
    assert action["action"] == "review_configuration"
    assert action["field_path"] == "runtime.preset"
    assert "override" in action["note"]
    assert attempted_imports == []


def test_validate_reports_secret_and_independent_environment_override_together(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_dir = tmp_path / "secret-and-override"
    _write_config(runtime_dir, secrets_ref="runtime_secrets")
    attempted_imports = _forbid_runner_import(monkeypatch)
    stderr = io.StringIO()

    status = main(
        ["validate", "--strategy-dir", str(runtime_dir)],
        registry=_registry(runtime_dir, secrets=True),
        environ={
            "BT_RUNTIME_MODE": "live",
            "BACKTRADER_RUNTIME_PRESET": "managed_live_direct",
        },
        stdout=io.StringIO(),
        stderr=stderr,
    )

    assert status == 2
    rejection = _payload(stderr)
    assert rejection["reason"] == "secrets_not_allowed_for_preset"
    diagnostic = rejection["diagnostic"]
    assert diagnostic["offline"] is True
    assert diagnostic["provider_preflight_started"] is False
    assert [(item["field_path"], item["reason"]) for item in diagnostic["blockers"]] == [
        ("secrets_ref", "secrets_not_allowed_for_preset"),
        ("environment.BT_RUNTIME_MODE", "environment_override_not_allowed"),
        ("environment.BACKTRADER_RUNTIME_PRESET", "environment_override_not_allowed"),
    ]
    assert [item["action"] for item in diagnostic["next_actions"]] == [
        "review_secret_reference",
        "remove_environment_override",
        "remove_environment_override",
    ]
    assert "runtime_secrets" not in json.dumps(rejection).lower()
    assert attempted_imports == []


def test_run_rejects_all_cli_override_flags_before_config_or_runner_loading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_dir = tmp_path / "override"
    _write_config(runtime_dir)
    attempted_imports = _forbid_runner_import(monkeypatch)
    stderr = io.StringIO()

    status = main(
        [
            "run",
            "--strategy-dir",
            str(runtime_dir),
            "--mode=live",
            "--preset=managed_live_direct",
            "--config=other.yaml",
        ],
        registry=_registry(runtime_dir),
        environ={},
        stdout=io.StringIO(),
        stderr=stderr,
    )

    assert status == 2
    rejection = _payload(stderr)
    assert rejection["reason"] == "cli_override_not_allowed"
    action = rejection["diagnostic"]["next_actions"][0]
    assert action["action"] == "remove_cli_override"
    assert action["rejected_arguments"] == ["--mode", "--preset", "--config"]
    assert attempted_imports == []


@pytest.mark.parametrize(
    "arguments",
    (
        ("validate",),
        ("validate", "--ai-config", "proposal.yaml"),
    ),
)
def test_cli_never_uses_cwd_or_ai_arguments_as_a_runtime(arguments: tuple) -> None:
    stderr = io.StringIO()

    status = main(
        list(arguments),
        registry=RuntimeRegistry(()),
        environ={},
        stdout=io.StringIO(),
        stderr=stderr,
    )

    assert status == 2
    rejection = _payload(stderr)
    assert rejection["reason"] == "cli_argument_not_allowed"
    action = rejection["diagnostic"]["next_actions"][0]
    assert action["action"] == "use_explicit_registered_runtime"
    assert "CWD" in action["note"]
    assert "AI-produced" in action["note"]


def test_run_failure_after_dispatch_does_not_claim_offline_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime_dir = tmp_path / "public-run-failure"
    _write_config(runtime_dir)

    def failed_dispatch(*_args: object) -> object:
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "a bounded public market read failed",
            field_path="runtime.runner",
            reason="public_market_read_failed",
        )

    monkeypatch.setitem(main.__globals__, "dispatch_registered_runtime", failed_dispatch)
    stderr = io.StringIO()
    status = main(
        ["run", "--strategy-dir", str(runtime_dir)],
        registry=_registry(runtime_dir),
        environ={},
        stdout=io.StringIO(),
        stderr=stderr,
    )

    assert status == 2
    rejection = _payload(stderr)
    diagnostic = rejection["diagnostic"]
    assert diagnostic["offline"] is False
    assert diagnostic["provider_io_may_have_started"] is True
    assert diagnostic["next_actions"][0]["action"] == "inspect_public_market_session"


def test_missing_managed_replay_capability_is_reported_before_provider_io(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime_dir = tmp_path / "missing-local-capability"
    _write_config(runtime_dir)

    def failed_dispatch(*_args: object) -> object:
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "reviewed local capability package is unavailable",
            field_path="runtime.capabilities.bt_api_execution",
            reason="capability_dependency_missing",
        )

    monkeypatch.setitem(main.__globals__, "dispatch_registered_runtime", failed_dispatch)
    stderr = io.StringIO()
    status = main(
        ["run", "--strategy-dir", str(runtime_dir)],
        registry=_registry(runtime_dir),
        environ={},
        stdout=io.StringIO(),
        stderr=stderr,
    )

    assert status == 2
    rejection = _payload(stderr)
    assert rejection["reason"] == "capability_dependency_missing"
    assert rejection["diagnostic"]["offline"] is True
    assert rejection["diagnostic"]["provider_preflight_started"] is False
    assert "provider_io_may_have_started" not in rejection["diagnostic"]
