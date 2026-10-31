"""Synthetic CLI regression for same-path CTP sandbox-to-live rejection."""

from __future__ import annotations

import builtins
import importlib
import importlib.util
import io
import json
import socket
from dataclasses import replace
from pathlib import Path
from typing import Callable

import pytest

import backtrader_runtime.cli as runtime_cli
import backtrader_runtime.config as runtime_config
import backtrader_runtime.credential_resolver as credential_resolver
from backtrader_runtime.inventory import (
    ITERATION41_013_3_CTP_PRIVATE_RUNTIME_ID,
    ITERATION41_013_3_STRATEGY_ID,
    iteration41_runtime_registry,
)
from backtrader_runtime.registry import RuntimeRegistry


def _write_synthetic_ctp_config(runtime_dir: Path, *, mode: str, preset: str) -> None:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    (runtime_dir / "config.yaml").write_text(
        "\n".join(
            (
                "config_schema_version: 4",
                "strategy:",
                "  id: " + ITERATION41_013_3_STRATEGY_ID,
                "runtime:",
                "  mode: " + mode,
                "  preset: " + preset,
                "parameters: {}",
                "secrets_ref: config_yaml",
                "ctp:",
                "  front_pairs:",
                "    - md_front: tcp://127.0.0.1:11001",
                "      td_front: tcp://127.0.0.1:12001",
                "  instrument_id: rb2701",
                "  exchange_id: SHFE",
                "  hedge_flag: '1'",
                "  broker_id: '9999'",
                "  user_id: synthetic-user",
                "  password: synthetic-password",
                "  app_id: synthetic-app",
                "  auth_code: synthetic-auth",
                "",
            )
        ),
        encoding="utf-8",
    )


def _default_registration_clone(tmp_path: Path) -> RuntimeRegistry:
    source = iteration41_runtime_registry()
    source_registration = next(
        item
        for item in source.registrations
        if item.runtime_id == ITERATION41_013_3_CTP_PRIVATE_RUNTIME_ID
    )
    runtime_dir = tmp_path / "registered-runtime"
    runtime_dir.mkdir()
    registration = replace(source_registration, runtime_dir=runtime_dir)
    return RuntimeRegistry(
        (registration,),
        ctp_simnow_readonly_bindings=tuple(
            binding
            for binding in source.ctp_simnow_readonly_bindings
            if binding.runtime_id == source_registration.runtime_id
        ),
        registry_id="backtrader.iteration41.synthetic-same-path-cli-test",
    )


def test_default_ctp_profile_rejects_same_path_live_cli_before_side_effects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Clone only the code-owned registration; never load the private config."""

    registry = _default_registration_clone(tmp_path)
    registration = registry.registrations[0]
    runtime_dir = Path(registration.runtime_dir)

    # The real CTP config permission contract is tested separately. This fixture
    # contains only dummy values under pytest's disposable temp directory.
    monkeypatch.setattr(runtime_config, "_require_private_config_security", lambda *_a, **_k: None)

    dispatch_calls: list[object] = []
    credential_calls: list[object] = []
    runner_imports: list[str] = []
    sdk_imports: list[str] = []
    socket_calls: list[str] = []

    def unexpected_dispatch(*args: object, **kwargs: object) -> None:
        dispatch_calls.append((args, kwargs))
        raise AssertionError("unavailable CTP profile reached runtime dispatch")

    def unexpected_credentials(*args: object, **kwargs: object) -> None:
        credential_calls.append((args, kwargs))
        raise AssertionError("unavailable CTP profile resolved credentials")

    monkeypatch.setattr(runtime_cli, "dispatch_registered_runtime", unexpected_dispatch)
    monkeypatch.setattr(credential_resolver, "resolve_runtime_credentials", unexpected_credentials)

    original_import = builtins.__import__
    original_import_module = importlib.import_module
    sdk_roots = {"bt_api_base", "bt_api_ctp", "bt_api_py"}

    def reject_sensitive_import(resolved: str) -> None:
        root = resolved.split(".", 1)[0]
        if resolved == "backtrader_runtime.runner":
            runner_imports.append(resolved)
            raise AssertionError("unavailable CTP profile imported its runner")
        if root in sdk_roots:
            sdk_imports.append(resolved)
            raise AssertionError("unavailable CTP profile imported a provider SDK")

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        package = (globals or {}).get("__package__", "")
        resolved = importlib.util.resolve_name(name, package) if level else name
        reject_sensitive_import(resolved)
        return original_import(name, globals, locals, fromlist, level)

    def guarded_import_module(name, package=None):
        resolved = importlib.util.resolve_name(name, package) if name.startswith(".") else name
        reject_sensitive_import(resolved)
        return original_import_module(name, package)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    monkeypatch.setattr(importlib, "import_module", guarded_import_module)

    real_socket = socket.socket

    class GuardedSocket(real_socket):
        def connect(self, *args, **kwargs):
            socket_calls.append("connect")
            raise AssertionError("unavailable CTP profile attempted a socket connection")

        def connect_ex(self, *args, **kwargs):
            socket_calls.append("connect_ex")
            raise AssertionError("unavailable CTP profile attempted a socket connection")

    def guarded_socket_call(name: str) -> Callable[..., object]:
        def reject(*args, **kwargs):
            socket_calls.append(name)
            raise AssertionError("unavailable CTP profile attempted a socket operation")

        return reject

    monkeypatch.setattr(socket, "socket", GuardedSocket)
    monkeypatch.setattr(socket, "create_connection", guarded_socket_call("create_connection"))
    monkeypatch.setattr(socket, "getaddrinfo", guarded_socket_call("getaddrinfo"))

    def invoke(arguments: list[str], *, reason: str) -> dict[str, object]:
        stdout, stderr = io.StringIO(), io.StringIO()
        status = runtime_cli.main(
            arguments,
            registry=registry,
            environ={},
            stdout=stdout,
            stderr=stderr,
        )
        assert status == 2
        assert stdout.getvalue() == ""
        payload = json.loads(stderr.getvalue())
        assert payload["reason"] == reason
        return payload

    _write_synthetic_ctp_config(runtime_dir, mode="simulation", preset="sandbox")
    sandbox_error = invoke(
        ["run", "--strategy-dir", str(runtime_dir)], reason="profile_dispatch_unavailable"
    )
    assert sandbox_error["diagnostic"]["offline"] is True

    # Rewrite the same temporary config path, as an operator would switch the
    # eventual shared config. The code-owned live profile is still unavailable.
    _write_synthetic_ctp_config(runtime_dir, mode="live", preset="managed_live_direct")
    live_run = invoke(
        ["run", "--strategy-dir", str(runtime_dir), "--confirm-live"],
        reason="managed_live_direct_profile_unavailable",
    )
    live_front_check = invoke(
        ["check-ctp-fronts", "--strategy-dir", str(runtime_dir)],
        reason="managed_live_direct_profile_unavailable",
    )
    live_doctor = invoke(
        ["doctor", "--strategy-dir", str(runtime_dir)],
        reason="managed_live_direct_profile_unavailable",
    )
    assert live_run["diagnostic"]["offline"] is True
    assert live_front_check["diagnostic"]["offline"] is True
    assert live_doctor["diagnostic"]["offline"] is True

    assert dispatch_calls == []
    assert credential_calls == []
    assert runner_imports == []
    assert sdk_imports == []
    assert socket_calls == []
