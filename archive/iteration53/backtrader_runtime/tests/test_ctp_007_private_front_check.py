"""Offline coverage for the 007 private read-only CTP front-check route.

All config material in this file is generated under pytest's temporary
directory. The front probe uses an in-memory socket implementation and never
opens a real network connection.
"""

from __future__ import annotations

import io
import json
import socket
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from backtrader_runtime import cli
from backtrader_runtime import config as runtime_config
from backtrader_runtime import ctp_configured_front_check as front_check
from backtrader_runtime.errors import RuntimeConfigError
from backtrader_runtime.inventory import (
    ITERATION41_007_CTP_PRIVATE_READONLY_BINDING,
    ITERATION41_007_CTP_PRIVATE_READONLY_REGISTRATION,
    ITERATION41_007_CTP_PRIVATE_RUNTIME_DIR,
    ITERATION41_007_CTP_PRIVATE_RUNTIME_ID,
    ITERATION41_007_CTP_PRIVATE_STRATEGY_ID,
    ITERATION41_013_3_CTP_PRIVATE_RUNTIME_ID,
    iteration41_runtime_registry,
)
from backtrader_runtime.registry import RuntimeRegistry
from backtrader_runtime.ctp_simnow_operator import CtpSimNowConfigReadOnlyBinding


_MD_PORT_BASE = 21001
_TD_PORT_BASE = 22001
_ACCOUNT_MARKER = "offline-test-account"
_PASSWORD_MARKER = "offline-test-password"


def _source_registration(runtime_id: str):
    registrations = {
        item.runtime_id: item for item in iteration41_runtime_registry().registrations
    }
    return registrations[runtime_id]


def _write_synthetic_private_config(runtime_dir: Path, strategy_id: str, pair_count: int) -> None:
    pairs = []
    for index in range(pair_count):
        pairs.extend(
            (
                f"    - md_front: tcp://127.0.0.1:{_MD_PORT_BASE + index}",
                f"      td_front: tcp://127.0.0.1:{_TD_PORT_BASE + index}",
            )
        )
    lines = [
        "config_schema_version: 4",
        "strategy:",
        f"  id: {strategy_id}",
        "runtime:",
        "  mode: simulation",
        "  preset: sandbox",
        "parameters: {}",
        "secrets_ref: config_yaml",
        "ctp:",
        "  front_pairs:",
        *pairs,
        "  instrument_id: rb2701",
        "  exchange_id: SHFE",
        "  hedge_flag: '1'",
        "  broker_id: '9999'",
        f"  user_id: {_ACCOUNT_MARKER}",
        f"  password: {_PASSWORD_MARKER}",
        "  app_id: offline_test_app",
        "  auth_code: offline_test_auth",
        "",
    ]
    (runtime_dir / "config.yaml").write_text("\n".join(lines), encoding="utf-8")


def _synthetic_sealed_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    runtime_id: str,
    *,
    pair_count: int = 5,
):
    """Clone only the code-owned policy shape and load temporary dummy config."""

    source = _source_registration(runtime_id)
    runtime_dir = tmp_path / runtime_id.rsplit(".", 1)[-1]
    runtime_dir.mkdir()
    registration = replace(source, runtime_dir=runtime_dir)
    binding = CtpSimNowConfigReadOnlyBinding(runtime_id=runtime_id)
    registry = RuntimeRegistry(
        (registration,),
        ctp_simnow_readonly_bindings=(binding,),
        registry_id="backtrader.iteration41.offline-007-front-test",
    )
    _write_synthetic_private_config(runtime_dir, registration.strategy_id, pair_count)

    # This bypass applies only to the synthetic tmp_path config. It avoids
    # Windows ACL dependence and never touches the protected suite config.
    monkeypatch.setattr(
        runtime_config,
        "_require_private_config_security",
        lambda *_args, **_kwargs: None,
    )
    effective = cli.validate_runtime_config(runtime_dir, registry)

    supported = set(front_check._SUPPORTED_PRIVATE_RUNTIME_IDENTITIES)
    supported.add((registration.runtime_id, registration.runtime_dir))
    monkeypatch.setattr(
        front_check, "_SUPPORTED_PRIVATE_RUNTIME_IDENTITIES", frozenset(supported)
    )
    return registry, registration, binding, effective, runtime_dir


def _install_fake_sockets(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, int]]:
    calls: list[tuple[str, int]] = []

    class FakeSocket:
        def settimeout(self, _timeout: float) -> None:
            return None

        def connect(self, address: tuple[str, int]) -> None:
            calls.append((address[0], address[1]))

        def close(self) -> None:
            return None

    monkeypatch.setattr(socket, "socket", lambda *_args, **_kwargs: FakeSocket())

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("offline test attempted a non-fake network operation")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    return calls


def _forbid_front_probe(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []

    def record(*_args: object, **_kwargs: object) -> None:
        calls.append("probe")

    monkeypatch.setattr(front_check, "select_ctp_front_pair", record)
    return calls


def test_default_007_registration_is_exact_private_zero_write_shape() -> None:
    registry = iteration41_runtime_registry()
    registration = registry.require_runtime_dir(ITERATION41_007_CTP_PRIVATE_RUNTIME_DIR)
    profile = registration.profile_for("simulation", "sandbox")

    assert registration is ITERATION41_007_CTP_PRIVATE_READONLY_REGISTRATION
    assert registration.runtime_id == ITERATION41_007_CTP_PRIVATE_RUNTIME_ID
    assert registration.runtime_dir == ITERATION41_007_CTP_PRIVATE_RUNTIME_DIR
    assert registration.strategy_id == ITERATION41_007_CTP_PRIVATE_STRATEGY_ID
    assert registration.allowed_presets == ()
    assert registration.allowed_parameter_keys == ()
    assert registration.allowed_secrets_refs == ("none",)
    assert registration.available_capabilities == ()
    assert registration.capability_modules == ()
    assert registration.offline_managed_execution is False
    assert registration.sandbox_write_policy == "deny"
    assert registration.runner_module is None
    assert registration.runner_entrypoint == "run_runtime"
    assert profile is registration.profiles[0]
    assert profile.allowed_parameter_keys == ()
    assert profile.allowed_secrets_refs == ("config_yaml",)
    assert profile.available_capabilities == ()
    assert profile.runner_module is None
    assert profile.sandbox_write_policy == "deny"
    assert (
        registry.require_ctp_simnow_readonly_binding(registration.runtime_id)
        is ITERATION41_007_CTP_PRIVATE_READONLY_BINDING
    )


@pytest.mark.parametrize(
    "runtime_id",
    (
        ITERATION41_007_CTP_PRIVATE_RUNTIME_ID,
        ITERATION41_013_3_CTP_PRIVATE_RUNTIME_ID,
    ),
)
def test_sealed_five_pair_config_check_uses_only_fake_sockets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runtime_id: str
) -> None:
    registry, _registration, _binding, effective, _runtime_dir = _synthetic_sealed_runtime(
        tmp_path, monkeypatch, runtime_id
    )
    calls = _install_fake_sockets(monkeypatch)

    result = front_check.check_configured_ctp_fronts(effective, registry)
    public = result.as_public_dict()
    rendered = json.dumps(public, sort_keys=True)

    assert result.succeeded is True
    assert result.configured_pair_count == 5
    assert result.selected_config_index in range(5)
    assert [pair["config_index"] for pair in public["pairs"]] == list(range(5))
    assert all(pair["status"] == "reachable" for pair in public["pairs"])
    assert public["trading_writes"] == public["settlement_writes"] == 0
    assert public["authentication_attempted"] is False
    assert public["credential_resolver_invoked"] is False
    assert public["sdk_imported"] is False
    assert _ACCOUNT_MARKER not in rendered
    assert _PASSWORD_MARKER not in rendered
    counts = Counter(calls)
    assert len(calls) == 5 * 2 * 3
    assert counts == Counter(
        {
            ("127.0.0.1", _MD_PORT_BASE + index): 3
            for index in range(5)
        }
    ) + Counter(
        {
            ("127.0.0.1", _TD_PORT_BASE + index): 3
            for index in range(5)
        }
    )


@pytest.mark.parametrize("tamper", ("profile", "binding"))
def test_invalid_profile_or_binding_is_rejected_before_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tamper: str
) -> None:
    registry, _registration, _binding, effective, _runtime_dir = _synthetic_sealed_runtime(
        tmp_path, monkeypatch, ITERATION41_007_CTP_PRIVATE_RUNTIME_ID
    )
    probe_calls = _forbid_front_probe(monkeypatch)

    if tamper == "profile":
        object.__setattr__(effective, "profile", None)
    else:
        monkeypatch.setattr(
            registry, "require_ctp_simnow_readonly_binding", lambda _runtime_id: object()
        )

    with pytest.raises(RuntimeConfigError):
        front_check.check_configured_ctp_fronts(effective, registry)
    assert probe_calls == []


def test_unregistered_same_shape_directory_is_rejected_before_config_or_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    unregistered_dir = tmp_path / "same-shaped-unregistered-runtime"
    unregistered_dir.mkdir()
    _write_synthetic_private_config(
        unregistered_dir, ITERATION41_007_CTP_PRIVATE_STRATEGY_ID, pair_count=5
    )
    validate_calls: list[object] = []
    probe_calls = _forbid_front_probe(monkeypatch)

    def forbidden_validate(*args: object, **kwargs: object) -> Any:
        validate_calls.append((args, kwargs))
        raise AssertionError("unregistered path must be rejected before config loading")

    monkeypatch.setattr(cli, "validate_runtime_config", forbidden_validate)
    stdout, stderr = io.StringIO(), io.StringIO()
    status = cli.main(
        ["check-ctp-fronts", "--strategy-dir", str(unregistered_dir)],
        registry=iteration41_runtime_registry(),
        environ={},
        stdout=stdout,
        stderr=stderr,
    )

    assert status == 2
    assert stdout.getvalue() == ""
    assert json.loads(stderr.getvalue())
    assert validate_calls == []
    assert probe_calls == []


def test_doctor_stays_offline_for_synthetic_007_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, _registration, _binding, _effective, runtime_dir = _synthetic_sealed_runtime(
        tmp_path, monkeypatch, ITERATION41_007_CTP_PRIVATE_RUNTIME_ID
    )

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("doctor must not dispatch provider preflight or a front probe")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(cli, "dispatch_registered_ctp_front_check", forbidden)
    monkeypatch.setattr(cli, "dispatch_registered_ctp_simnow_readonly_preflight", forbidden)
    stdout, stderr = io.StringIO(), io.StringIO()
    status = cli.main(
        ["doctor", "--strategy-dir", str(runtime_dir)],
        registry=registry,
        environ={},
        stdout=stdout,
        stderr=stderr,
    )

    assert status == 0, stderr.getvalue()
    payload = json.loads(stdout.getvalue())
    diagnostic = payload["diagnostic"]
    assert payload["status"] == "diagnostic"
    assert diagnostic["offline"] is True
    assert diagnostic["provider_preflight_started"] is False
    rendered = json.dumps(payload, sort_keys=True)
    assert _ACCOUNT_MARKER not in rendered
    assert _PASSWORD_MARKER not in rendered


def test_007_preflight_blocks_before_config_credentials_or_provider_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validation_calls: list[object] = []
    dispatch_calls: list[object] = []

    def forbidden_validation(*args: object, **kwargs: object) -> Any:
        validation_calls.append((args, kwargs))
        raise AssertionError("007 preflight must stop before config loading")

    def forbidden_dispatch(*args: object, **kwargs: object) -> Any:
        dispatch_calls.append((args, kwargs))
        raise AssertionError("007 preflight must not open provider preflight")

    monkeypatch.setattr(cli, "validate_runtime_config", forbidden_validation)
    monkeypatch.setattr(cli, "dispatch_registered_ctp_simnow_readonly_preflight", forbidden_dispatch)
    monkeypatch.setattr(socket, "socket", forbidden_dispatch)
    stdout, stderr = io.StringIO(), io.StringIO()
    status = cli.main(
        ["preflight", "--strategy-dir", str(ITERATION41_007_CTP_PRIVATE_RUNTIME_DIR)],
        registry=iteration41_runtime_registry(),
        environ={},
        stdout=stdout,
        stderr=stderr,
    )

    assert status == 2
    assert stdout.getvalue() == ""
    payload = json.loads(stderr.getvalue())
    assert payload["reason"] == "ctp_simnow_preflight_supervisor_required"
    assert validation_calls == []
    assert dispatch_calls == []
