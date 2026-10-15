"""CFG05 normal-entry fences for retired remote configuration."""

from __future__ import annotations

import builtins
import io
import json
import socket
import subprocess
import sys
import threading
import types
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

import pytest

import backtrader_runtime.cli as runtime_cli
from backtrader_runtime import MIGRATION_REVIEW_REQUIRED, RegisteredRuntime, RuntimeRegistry
from backtrader_runtime.legacy import run_legacy_config_first_cli


_OPTIONAL_SERVICE_PREFIXES = (
    "bt_api_py.forwarding",
    "bt_api_py.gateway",
    "bt_api_gateway",
    "bt_api_execution",
    "bt_api_risk",
    "bt_api_monitor",
    "bt_api_transport_zmq",
)


def _runtime_registry(runtime_dir: Path, runner_module: str) -> RuntimeRegistry:
    return RuntimeRegistry(
        (
            RegisteredRuntime(
                runtime_dir=runtime_dir,
                strategy_id="cfg05.synthetic",
                allowed_presets=("local_backtest",),
                runner_module=runner_module,
            ),
        )
    )


def _write_config(runtime_dir: Path, *, legacy_gateway: bool = False, version: int = 4) -> Path:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    text = f"""config_schema_version: {version}
strategy:
  id: cfg05.synthetic
runtime:
  mode: backtest
  preset: local_backtest
parameters: {{}}
secrets_ref: none
"""
    if legacy_gateway:
        text += """gateway:
  backend: zmq
  command_endpoint: tcp://127.0.0.1:7610
  market_endpoint: tcp://127.0.0.1:7611
  enable_trading: true
register_to: cfg05.synthetic
"""
    path = runtime_dir / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def _guard_service_side_effects(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    attempted: list[str] = []

    def forbidden(name: str):
        def fail(*_args: object, **_kwargs: object) -> None:
            attempted.append(name)
            raise AssertionError(f"normal config entry attempted {name}")

        return fail

    monkeypatch.setattr(socket, "socket", forbidden("socket"))
    monkeypatch.setattr(socket, "create_connection", forbidden("socket_connect"))
    monkeypatch.setattr(subprocess, "Popen", forbidden("process"))
    monkeypatch.setattr(threading.Thread, "start", forbidden("thread"))
    real_import = builtins.__import__

    def guarded_import(name: str, *args: object, **kwargs: object) -> Any:
        if any(name == prefix or name.startswith(prefix + ".") for prefix in _OPTIONAL_SERVICE_PREFIXES):
            attempted.append("optional_import:" + name)
            raise ImportError("optional service package is not part of normal config validation")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    return attempted


def _invoke_legacy_entry(runtime_dir: Path) -> tuple[int, dict, dict]:
    output = io.StringIO()
    errors = io.StringIO()
    with redirect_stdout(output), redirect_stderr(errors):
        result = run_legacy_config_first_cli(runtime_dir, argv=[])
    stdout_payload = json.loads(output.getvalue()) if output.getvalue() else {}
    stderr_payload = json.loads(errors.getvalue()) if errors.getvalue() else {}
    return result, stdout_payload, stderr_payload


def test_legacy_gateway_yaml_is_migration_rejected_by_the_original_normal_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The legacy no-argument shim reaches the CLI and stops before runner dispatch."""

    runtime_dir = tmp_path / "registered-runtime"
    config_path = _write_config(runtime_dir, legacy_gateway=True, version=5)
    original = config_path.read_bytes()
    runner_module = "cfg05_synthetic_runner"
    registry = _runtime_registry(runtime_dir, runner_module)
    monkeypatch.setattr(runtime_cli, "default_runtime_registry", lambda: registry)
    monkeypatch.setattr(runtime_cli.os, "environ", {})
    effects = _guard_service_side_effects(monkeypatch)
    dispatches: list[object] = []

    def forbidden_dispatch(*args: object, **kwargs: object) -> dict:
        dispatches.append((args, kwargs))
        raise AssertionError("legacy remote config reached the code-owned runner")

    monkeypatch.setattr(runtime_cli, "dispatch_registered_runtime", forbidden_dispatch)
    result, stdout_payload, stderr_payload = _invoke_legacy_entry(runtime_dir)

    assert result == 2
    assert stdout_payload == {}
    assert stderr_payload["error_code"] == MIGRATION_REVIEW_REQUIRED
    assert stderr_payload["field_path"] == "gateway"
    assert stderr_payload["reason"] == "legacy_remote_config_requires_migration"
    assert stderr_payload["diagnostic"]["offline"] is True
    assert stderr_payload["diagnostic"]["provider_preflight_started"] is False
    assert dispatches == []
    assert effects == []
    assert config_path.read_bytes() == original
    assert "127.0.0.1:7610" not in json.dumps(stderr_payload)


def test_retired_bt_gateway_environment_is_migration_rejected_before_runner_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An old BT_GATEWAY endpoint cannot implicitly select a service at the normal entry."""

    runtime_dir = tmp_path / "registered-runtime"
    _write_config(runtime_dir)
    runner_module = "cfg05_synthetic_runner"
    registry = _runtime_registry(runtime_dir, runner_module)
    effects = _guard_service_side_effects(monkeypatch)
    dispatches: list[object] = []

    def forbidden_dispatch(*args: object, **kwargs: object) -> dict:
        dispatches.append((args, kwargs))
        raise AssertionError("retired environment config reached the code-owned runner")

    monkeypatch.setattr(runtime_cli, "dispatch_registered_runtime", forbidden_dispatch)
    errors = io.StringIO()
    result = runtime_cli.main(
        ["run", "--strategy-dir", str(runtime_dir)],
        registry=registry,
        environ={"BT_GATEWAY_COMMAND_ENDPOINT": "tcp://127.0.0.1:7610"},
        stdout=io.StringIO(),
        stderr=errors,
    )
    payload = json.loads(errors.getvalue())

    assert result == 2
    assert payload["error_code"] == MIGRATION_REVIEW_REQUIRED
    assert payload["field_path"] == "environment.BT_GATEWAY_COMMAND_ENDPOINT"
    assert payload["reason"] == "legacy_gateway_environment_requires_migration"
    assert payload["diagnostic"]["offline"] is True
    assert dispatches == []
    assert effects == []
    assert "127.0.0.1:7610" not in errors.getvalue()


@pytest.mark.parametrize(
    "environ",
    (
        {"BT_GATEWAY_UNKNOWN": "local-marker"},
        {"BT_GATEWAY_COMMAND_ENDPOINT": ""},
    ),
    ids=("unknown-suffix", "empty-known-value"),
)
def test_unrecognized_or_empty_gateway_environment_keeps_v4_local_entry_available(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    environ: dict[str, str],
) -> None:
    """Only nonempty variables consumed by the legacy Gateway path trigger migration."""

    runtime_dir = tmp_path / "registered-runtime"
    _write_config(runtime_dir)
    runner_module = "cfg05_synthetic_runner"
    registry = _runtime_registry(runtime_dir, runner_module)
    module = types.ModuleType(runner_module)
    dispatches: list[dict[str, object]] = []

    def run_runtime(
        _runtime_dir: Path | None,
        *,
        effective: Any,
        registry: Any,
        runtime_directory: Any = None,
    ) -> dict[str, object]:
        del registry, runtime_directory
        dispatches.append(effective.as_public_dict())
        return {"status": "SYNTHETIC_LOCAL_BACKTEST"}

    module.run_runtime = run_runtime  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, runner_module, module)
    monkeypatch.setattr(runtime_cli, "default_runtime_registry", lambda: registry)
    monkeypatch.setattr(runtime_cli.os, "environ", environ)
    effects = _guard_service_side_effects(monkeypatch)
    output = io.StringIO()
    errors = io.StringIO()

    result = runtime_cli.main(
        ["run", "--strategy-dir", str(runtime_dir)],
        registry=registry,
        environ=environ,
        stdout=output,
        stderr=errors,
    )
    payload = json.loads(output.getvalue())

    assert result == 0, errors.getvalue()
    assert payload["status"] == "completed"
    assert payload["runner_dispatch"] == "code_owned"
    assert payload["report"]["result"]["status"] == "SYNTHETIC_LOCAL_BACKTEST"
    assert len(dispatches) == 1
    assert dispatches[0]["mode"] == "backtest"
    assert dispatches[0]["preset"] == "local_backtest"
    assert dispatches[0]["allows_network"] is False
    assert dispatches[0]["allows_external_writes"] is False
    assert effects == []


def test_v4_local_backtest_keeps_direct_semantics_through_the_normal_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Supported v4 backtests reach their registered runner without service activation."""

    runtime_dir = tmp_path / "registered-runtime"
    _write_config(runtime_dir)
    runner_module = "cfg05_synthetic_runner"
    registry = _runtime_registry(runtime_dir, runner_module)
    module = types.ModuleType(runner_module)
    observed: list[dict[str, object]] = []

    def run_runtime(
        _runtime_dir: Path | None,
        *,
        effective: Any,
        registry: Any,
        runtime_directory: Any = None,
    ) -> dict[str, object]:
        del registry, runtime_directory
        public = effective.as_public_dict()
        observed.append(public)
        return {"status": "SYNTHETIC_LOCAL_BACKTEST"}

    module.run_runtime = run_runtime  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, runner_module, module)
    monkeypatch.setattr(runtime_cli, "default_runtime_registry", lambda: registry)
    monkeypatch.setattr(runtime_cli.os, "environ", {})
    effects = _guard_service_side_effects(monkeypatch)
    output = io.StringIO()
    errors = io.StringIO()

    with redirect_stdout(output), redirect_stderr(errors):
        result = run_legacy_config_first_cli(runtime_dir, argv=[])
    payload = json.loads(output.getvalue())

    assert result == 0, errors.getvalue()
    assert payload["status"] == "completed"
    assert payload["runner_dispatch"] == "code_owned"
    assert payload["report"]["result"]["status"] == "SYNTHETIC_LOCAL_BACKTEST"
    assert len(observed) == 1
    assert observed[0]["mode"] == "backtest"
    assert observed[0]["preset"] == "local_backtest"
    assert observed[0]["allows_network"] is False
    assert observed[0]["allows_external_writes"] is False
    assert observed[0]["requires_live_confirmation"] is False
    assert observed[0]["required_capabilities"] == ()
    assert effects == []


@pytest.mark.parametrize(
    "provider_value, environ",
    (
        pytest.param(None, {}, id="unset"),
        pytest.param("ctp", {"BT_STORE_PROVIDER": "ctp"}, id="direct-ctp"),
    ),
)
def test_bt_store_provider_direct_or_unset_keeps_v4_legacy_entry_available(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider_value: str | None,
    environ: dict[str, str],
) -> None:
    """Only the retired Gateway selector is fenced; local direct runs remain available."""

    runtime_dir = tmp_path / "registered-runtime"
    _write_config(runtime_dir)
    runner_module = "cfg05_synthetic_runner"
    registry = _runtime_registry(runtime_dir, runner_module)
    module = types.ModuleType(runner_module)
    dispatches: list[dict[str, object]] = []

    def run_runtime(
        _runtime_dir: Path | None,
        *,
        effective: Any,
        registry: Any,
        runtime_directory: Any = None,
    ) -> dict[str, object]:
        del registry, runtime_directory
        dispatches.append(
            {
                "effective": effective.as_public_dict(),
                "provider_selector": runtime_cli.os.environ.get("BT_STORE_PROVIDER"),
            }
        )
        return {"status": "SYNTHETIC_LOCAL_BACKTEST"}

    module.run_runtime = run_runtime  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, runner_module, module)
    monkeypatch.setattr(runtime_cli, "default_runtime_registry", lambda: registry)
    monkeypatch.setattr(runtime_cli.os, "environ", environ)
    effects = _guard_service_side_effects(monkeypatch)
    output = io.StringIO()
    errors = io.StringIO()

    with redirect_stdout(output), redirect_stderr(errors):
        result = run_legacy_config_first_cli(runtime_dir, argv=[])
    payload = json.loads(output.getvalue())

    assert result == 0, errors.getvalue()
    assert payload["status"] == "completed"
    assert payload["runner_dispatch"] == "code_owned"
    assert payload["report"]["result"]["status"] == "SYNTHETIC_LOCAL_BACKTEST"
    assert len(dispatches) == 1
    assert dispatches[0]["provider_selector"] == provider_value
    assert dispatches[0]["effective"]["mode"] == "backtest"
    assert dispatches[0]["effective"]["preset"] == "local_backtest"
    assert dispatches[0]["effective"]["allows_network"] is False
    assert effects == []


@pytest.mark.parametrize(
    "provider_selector",
    (
        pytest.param("ctp_gateway", id="gateway-suffix"),
        pytest.param(" Gateway ", id="trimmed-exact-gateway"),
        pytest.param(" MT5_GATEWAY ", id="trimmed-case-insensitive-suffix"),
    ),
)
def test_bt_store_provider_gateway_selector_is_migration_rejected_by_legacy_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider_selector: str,
) -> None:
    """The original registered entry rejects the retired selector before runner effects."""

    runtime_dir = tmp_path / "registered-runtime"
    _write_config(runtime_dir)
    registry = _runtime_registry(runtime_dir, "cfg05_synthetic_runner")
    monkeypatch.setattr(runtime_cli, "default_runtime_registry", lambda: registry)
    monkeypatch.setattr(runtime_cli.os, "environ", {"BT_STORE_PROVIDER": provider_selector})
    effects = _guard_service_side_effects(monkeypatch)
    dispatches: list[object] = []

    def forbidden_dispatch(*args: object, **kwargs: object) -> dict:
        dispatches.append((args, kwargs))
        raise AssertionError("retired provider selector reached the code-owned runner")

    monkeypatch.setattr(runtime_cli, "dispatch_registered_runtime", forbidden_dispatch)
    result, stdout_payload, stderr_payload = _invoke_legacy_entry(runtime_dir)

    assert result == 2
    assert stdout_payload == {}
    assert stderr_payload["error_code"] == MIGRATION_REVIEW_REQUIRED
    assert stderr_payload["field_path"] == "environment.BT_STORE_PROVIDER"
    assert stderr_payload["reason"] == "legacy_gateway_environment_requires_migration"
    assert stderr_payload["diagnostic"]["offline"] is True
    assert dispatches == []
    assert effects == []
    assert stderr_payload["message"] == (
        "BT_STORE_PROVIDER cannot select a retired Gateway backend through the current "
        "runtime; convert it offline to the explicit service/client configuration or "
        "keep the matching historical release"
    )
    nonmessage_payload = {key: value for key, value in stderr_payload.items() if key != "message"}
    assert provider_selector not in json.dumps(nonmessage_payload)


def test_runtime_v5_is_not_claimed_as_supported_or_fallback_parsed(
    tmp_path: Path,
) -> None:
    """The current runtime rejects unimplemented v5 rather than treating it as v4."""

    runtime_dir = tmp_path / "registered-runtime"
    _write_config(runtime_dir, version=5)
    registry = _runtime_registry(runtime_dir, "cfg05_synthetic_runner")
    errors = io.StringIO()

    result = runtime_cli.main(
        ["run", "--strategy-dir", str(runtime_dir)],
        registry=registry,
        environ={},
        stdout=io.StringIO(),
        stderr=errors,
    )
    payload = json.loads(errors.getvalue())

    assert result == 2
    assert payload["error_code"] == "CONFIG_SCHEMA_UNSUPPORTED"
    assert payload["field_path"] == "config_schema_version"
    assert payload["reason"] == "unsupported_schema_version"
    assert payload["diagnostic"]["offline"] is True
