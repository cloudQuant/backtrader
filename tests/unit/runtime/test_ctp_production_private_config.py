"""Parser-only boundary tests for the reserved CTP production config."""

from __future__ import annotations

import builtins
import hashlib
import io
import json
import os
from pathlib import Path

import pytest

import backtrader_runtime.config as runtime_config
from backtrader_runtime import (
    RegisteredRuntime,
    RuntimeConfigError,
    RuntimeRegistry,
    load_runtime_config,
    resolve_runtime_config,
)
from backtrader_runtime.cli import main
from backtrader_runtime.config import require_loaded_runtime_config_seal


_PRIVATE_VALUES = {
    # TEST-NET addresses keep this parser-only fixture disconnected from any
    # real CTP front. They are selectors, not a code-owned production pin.
    "md_front": "tcp://192.0.2.11:41211",
    "td_front": "tcp://192.0.2.10:41201",
    "instrument_id": "IF2612",
    "exchange_id": "CFFEX",
    "hedge_flag": "1",
    "broker_id": "synthetic-broker-001",
    "user_id": "synthetic-account-001",
    "password": "synthetic-production-password-never-use",
    "app_id": "synthetic-production-app",
    "auth_code": "synthetic-production-auth",
}


def _production_document(
    *,
    private_values: dict | None = None,
    mode: str = "live",
    preset: str = "managed_live_direct",
    secrets_ref: str = "config_yaml",
) -> dict:
    return {
        "config_schema_version": 4,
        "strategy": {"id": "example.007_ctp.production"},
        "runtime": {"mode": mode, "preset": preset},
        "parameters": {},
        "secrets_ref": secrets_ref,
        "ctp_production": dict(_PRIVATE_VALUES if private_values is None else private_values),
    }


def _parse_production(
    *,
    strategy_dir: Path | None = None,
    document: dict | None = None,
) -> runtime_config.RuntimeConfig:
    path = strategy_dir or runtime_config.CTP_PRODUCTION_RUNTIME_DIR
    return runtime_config._validate_schema(
        _production_document() if document is None else document,
        path,
        path / "config.yaml",
    )


def test_production_private_fields_are_redacted_and_sealed() -> None:
    config = _parse_production()
    runtime_config._seal_loaded_runtime_config(config)

    private_text = repr(config) + repr(config.ctp_production)
    public_text = json.dumps(config.as_public_dict(), sort_keys=True)
    assert "CtpProductionPrivateConfig(<redacted>)" in private_text
    for private_key, private_value in _PRIVATE_VALUES.items():
        if private_key == "hedge_flag":
            continue
        assert private_value not in private_text + public_text
        if private_key in {"broker_id", "user_id", "password", "app_id", "auth_code"}:
            assert hashlib.sha256(private_value.encode("utf-8")).hexdigest() not in public_text
    assert config.ctp_production is not None
    assert "synthetic-account-001" not in config.config_digest

    require_loaded_runtime_config_seal(config)
    object.__setattr__(config.ctp_production, "password", "mutated-synthetic-password")
    with pytest.raises(RuntimeConfigError) as caught:
        require_loaded_runtime_config_seal(config)
    assert caught.value.reason == "config_provenance_invalid"
    assert "mutated-synthetic-password" not in str(caught.value)


def test_production_private_credentials_do_not_change_public_digest() -> None:
    first = _parse_production()
    changed_private = dict(_PRIVATE_VALUES)
    changed_private.update(
        broker_id="synthetic-broker-002",
        user_id="synthetic-account-002",
        password="different-synthetic-password",
        app_id="different-synthetic-app",
        auth_code="different-synthetic-auth",
    )
    second = _parse_production(
        document=_production_document(private_values=changed_private)
    )

    assert first.config_digest == second.config_digest
    assert first.ctp_production.user_id != second.ctp_production.user_id
    assert "different-synthetic-password" not in repr(second)


def test_production_front_pair_changes_public_config_digest() -> None:
    first = _parse_production()
    changed_fronts = dict(_PRIVATE_VALUES)
    changed_fronts.update(
        md_front="tcp://192.0.2.21:41211",
        td_front="tcp://192.0.2.20:41201",
    )
    second = _parse_production(
        document=_production_document(private_values=changed_fronts)
    )

    assert first.config_digest != second.config_digest
    assert first.ctp_production is not None
    assert second.ctp_production is not None
    assert first.ctp_production.md_front == _PRIVATE_VALUES["md_front"]
    assert first.ctp_production.td_front == _PRIVATE_VALUES["td_front"]


@pytest.mark.parametrize("pair_count", (1, 8))
def test_production_front_pairs_are_preserved_without_selecting_a_pair(
    pair_count: int,
) -> None:
    pairs = [
        {
            "md_front": "tcp://md-{0}.example.net:{1}".format(index, 42000 + index),
            "td_front": "tcp://td-{0}.example.net:{1}".format(index, 43000 + index),
        }
        for index in range(pair_count)
    ]
    private_values = {
        key: value
        for key, value in _PRIVATE_VALUES.items()
        if key not in {"md_front", "td_front"}
    }
    private_values["front_pairs"] = pairs

    config = _parse_production(
        document=_production_document(private_values=private_values)
    )

    assert config.ctp_production is not None
    assert config.ctp_production.md_front is None
    assert config.ctp_production.td_front is None
    assert [dict(pair) for pair in config.ctp_production.front_pairs] == pairs
    assert config.ctp_production._private_facts()[2] == tuple(
        (pair["md_front"], pair["td_front"]) for pair in pairs
    )


def test_production_front_pairs_affect_public_config_digest_in_order() -> None:
    base = {
        key: value
        for key, value in _PRIVATE_VALUES.items()
        if key not in {"md_front", "td_front"}
    }
    pairs = [
        {"md_front": "tcp://md-a.example.net:42001", "td_front": "tcp://td-a.example.net:43001"},
        {"md_front": "tcp://md-b.example.net:42002", "td_front": "tcp://td-b.example.net:43002"},
    ]
    first = _parse_production(
        document=_production_document(private_values=dict(base, front_pairs=pairs))
    )
    reordered = _parse_production(
        document=_production_document(
            private_values=dict(base, front_pairs=list(reversed(pairs)))
        )
    )

    assert first.config_digest != reordered.config_digest


@pytest.mark.parametrize(
    "pairs",
    (
        [],
        [
            {
                "md_front": "tcp://md-{0}.example.net:{1}".format(i, 42000 + i),
                "td_front": "tcp://td-{0}.example.net:{1}".format(i, 43000 + i),
            }
            for i in range(9)
        ],
    ),
)
def test_production_front_pairs_reject_empty_or_oversized_lists(pairs: list) -> None:
    private_values = {
        key: value
        for key, value in _PRIVATE_VALUES.items()
        if key not in {"md_front", "td_front"}
    }
    private_values["front_pairs"] = pairs

    with pytest.raises(RuntimeConfigError) as caught:
        _parse_production(
            document=_production_document(private_values=private_values)
        )

    assert caught.value.reason == "invalid_ctp_production_front_pairs"
    assert caught.value.field_path == "ctp_production.front_pairs"


def test_production_front_pairs_reject_mixed_duplicate_or_malformed_entries() -> None:
    base = {
        key: value
        for key, value in _PRIVATE_VALUES.items()
        if key not in {"md_front", "td_front"}
    }
    pair = {"md_front": "tcp://md-a.example.net:42001", "td_front": "tcp://td-a.example.net:43001"}
    malformed_cases = (
        (
            dict(base, front_pairs=[{"md_front": pair["md_front"]}]),
            "required_field_missing",
        ),
        (
            dict(base, front_pairs=[dict(pair, fallback="tcp://other.example.net:43002")]),
            "field_not_allowed",
        ),
        (
            dict(base, front_pairs=[pair, dict(pair)]),
            "duplicate_ctp_production_front_pair",
        ),
        (
            dict(base, front_pairs=[dict(pair, md_front="tcp://md.example.net:42001/path")]),
            "invalid_ctp_production_front",
        ),
    )
    for private_values, expected_reason in malformed_cases:
        with pytest.raises(RuntimeConfigError) as caught:
            _parse_production(
                document=_production_document(private_values=private_values)
            )
        assert caught.value.reason == expected_reason

    mixed = dict(base, front_pairs=[pair], md_front=_PRIVATE_VALUES["md_front"])
    with pytest.raises(RuntimeConfigError) as caught:
        _parse_production(document=_production_document(private_values=mixed))
    assert caught.value.reason == "mixed_ctp_production_front_forms"


def test_production_multi_pair_config_stays_unresolved_and_cannot_become_a_route(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runtime_config, "CTP_PRODUCTION_RUNTIME_DIR", tmp_path)
    registration = RegisteredRuntime(
        runtime_dir=tmp_path,
        strategy_id="example.007_ctp.production",
        allowed_presets=("managed_live_direct",),
        allowed_secrets_refs=("config_yaml",),
    )
    registry = RuntimeRegistry((registration,))
    private_values = {
        key: value
        for key, value in _PRIVATE_VALUES.items()
        if key not in {"md_front", "td_front"}
    }
    private_values["front_pairs"] = [
        {"md_front": "tcp://md-a.example.net:42001", "td_front": "tcp://td-a.example.net:43001"},
        {"md_front": "tcp://md-b.example.net:42002", "td_front": "tcp://td-b.example.net:43002"},
    ]
    config = runtime_config._seal_loaded_runtime_config(
        _parse_production(
            strategy_dir=tmp_path,
            document=_production_document(private_values=private_values),
        ),
        registry,
    )
    assert config.ctp_production is not None
    assert config.ctp_production.md_front is None
    assert config.ctp_production.td_front is None

    with pytest.raises(RuntimeConfigError) as caught:
        resolve_runtime_config(config, registry)

    assert caught.value.reason == "ctp_production_admission_unavailable"


@pytest.mark.parametrize("missing_field", ("md_front", "td_front"))
def test_production_front_pair_is_required(missing_field: str) -> None:
    private_values = dict(_PRIVATE_VALUES)
    private_values.pop(missing_field)

    with pytest.raises(RuntimeConfigError) as caught:
        _parse_production(
            document=_production_document(private_values=private_values)
        )

    assert caught.value.reason == "required_field_missing"
    assert caught.value.field_path == "ctp_production." + missing_field


def test_older_production_schema_without_fronts_fails_closed() -> None:
    legacy_values = dict(_PRIVATE_VALUES)
    legacy_values.pop("md_front")
    legacy_values.pop("td_front")

    with pytest.raises(RuntimeConfigError) as caught:
        _parse_production(
            document=_production_document(private_values=legacy_values)
        )

    assert caught.value.reason == "required_field_missing"
    assert caught.value.field_path == "ctp_production.md_front"


@pytest.mark.parametrize(
    "field_name,bad_front",
    (
        ("td_front", "192.0.2.10:41201"),
        ("td_front", "tcp://192.0.2.10"),
        ("md_front", "tcp://192.0.2.11:70000"),
        ("md_front", "tcp://user@192.0.2.11:41211"),
        ("md_front", "tcp://192.0.2.11:41211/path"),
    ),
)
def test_production_front_addresses_require_tcp_host_and_valid_port(
    field_name: str, bad_front: str
) -> None:
    private_values = dict(_PRIVATE_VALUES)
    private_values[field_name] = bad_front

    with pytest.raises(RuntimeConfigError) as caught:
        _parse_production(
            document=_production_document(private_values=private_values)
        )

    assert caught.value.reason == "invalid_ctp_production_front"
    assert caught.value.field_path == "ctp_production." + field_name
    assert bad_front not in str(caught.value)


def test_production_front_pair_is_covered_by_the_private_config_seal() -> None:
    config = _parse_production()
    runtime_config._seal_loaded_runtime_config(config)
    assert config.ctp_production is not None

    object.__setattr__(config.ctp_production, "td_front", "tcp://192.0.2.30:41201")

    with pytest.raises(RuntimeConfigError) as caught:
        require_loaded_runtime_config_seal(config)
    assert caught.value.reason == "config_provenance_invalid"
    assert "192.0.2.30" not in str(caught.value)


def test_production_front_pairs_are_covered_by_the_private_config_seal() -> None:
    private_values = {
        key: value
        for key, value in _PRIVATE_VALUES.items()
        if key not in {"md_front", "td_front"}
    }
    private_values["front_pairs"] = [
        {"md_front": "tcp://md-a.example.net:42001", "td_front": "tcp://td-a.example.net:43001"}
    ]
    config = _parse_production(
        document=_production_document(private_values=private_values)
    )
    runtime_config._seal_loaded_runtime_config(config)
    assert config.ctp_production is not None
    object.__setattr__(
        config.ctp_production,
        "front_pairs",
        (
            {
                "md_front": "tcp://md-mutated.example.net:42001",
                "td_front": "tcp://td-a.example.net:43001",
            },
        ),
    )

    with pytest.raises(RuntimeConfigError) as caught:
        require_loaded_runtime_config_seal(config)

    assert caught.value.reason == "config_provenance_invalid"
    assert "md-mutated" not in str(caught.value)


def test_production_parser_does_not_import_provider_or_open_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import socket

    original_import = builtins.__import__
    provider_import_attempts = []
    socket_attempts = []

    def reject_provider_import(name, *args, **kwargs):
        if any(
            name == prefix or name.startswith(prefix + ".")
            for prefix in ("backtrader", "bt_api_ctp", "bt_api_py", "bt_api_base")
        ):
            provider_import_attempts.append(name)
            raise AssertionError("parser imported Backtrader or a CTP provider")
        return original_import(name, *args, **kwargs)

    def reject_socket(*args, **kwargs):
        socket_attempts.append((args, kwargs))
        raise AssertionError("parser attempted network I/O")

    monkeypatch.setattr(builtins, "__import__", reject_provider_import)
    monkeypatch.setattr(socket, "socket", reject_socket)

    private_values = {
        key: value
        for key, value in _PRIVATE_VALUES.items()
        if key not in {"md_front", "td_front"}
    }
    private_values["front_pairs"] = [
        {"md_front": "tcp://md-a.example.net:42001", "td_front": "tcp://td-a.example.net:43001"},
        {"md_front": "tcp://md-b.example.net:42002", "td_front": "tcp://td-b.example.net:43002"},
    ]
    config = _parse_production(
        document=_production_document(private_values=private_values)
    )

    assert config.ctp_production is not None
    assert config.ctp_production.md_front is None
    assert config.ctp_production.td_front is None
    assert len(config.ctp_production.front_pairs) == 2
    assert not provider_import_attempts
    assert not socket_attempts


def test_registered_production_private_config_hits_security_gate_before_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runtime_config, "CTP_PRODUCTION_RUNTIME_DIR", tmp_path)
    tmp_path.mkdir(exist_ok=True)
    config_path = tmp_path / "config.yaml"
    values = "\n".join(
        "  {0}: {1}".format(key, json.dumps(value))
        for key, value in _PRIVATE_VALUES.items()
    )
    config_path.write_text(
        "config_schema_version: 4\n"
        "strategy: {id: example.007_ctp.production}\n"
        "runtime: {mode: live, preset: managed_live_direct}\n"
        "parameters: {}\n"
        "secrets_ref: config_yaml\n"
        "ctp_production:\n"
        + values
        + "\n",
        encoding="utf-8",
    )
    if os.name == "posix":
        tmp_path.chmod(0o700)
        config_path.chmod(0o600)

    registration = RegisteredRuntime(
        runtime_dir=tmp_path,
        strategy_id="example.007_ctp.production",
        allowed_presets=("managed_live_direct",),
        allowed_secrets_refs=("config_yaml",),
    )
    registry = RuntimeRegistry((registration,))
    gate_calls = []

    def deny_at_private_gate(*args, **kwargs):
        gate_calls.append((args, kwargs))
        raise runtime_config._private_config_security_error("synthetic_gate_rejection")

    def unexpected_read(*args, **kwargs):
        raise AssertionError("private config bytes were read before the security gate")

    monkeypatch.setattr(runtime_config, "_require_private_config_security", deny_at_private_gate)
    monkeypatch.setattr(runtime_config.os, "read", unexpected_read)
    with pytest.raises(RuntimeConfigError) as caught:
        load_runtime_config(tmp_path, registry=registry)

    assert caught.value.reason == "synthetic_gate_rejection"
    assert len(gate_calls) == 1
    assert "synthetic-production-password-never-use" not in str(caught.value)


@pytest.mark.skipif(os.name != "posix", reason="POSIX private config permission gate")
def test_owner_only_production_config_loads_through_private_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runtime_config, "CTP_PRODUCTION_RUNTIME_DIR", tmp_path)
    tmp_path.mkdir(exist_ok=True)
    tmp_path.chmod(0o700)
    config_path = tmp_path / "config.yaml"
    values = "\n".join(
        "  {0}: {1}".format(key, json.dumps(value))
        for key, value in _PRIVATE_VALUES.items()
    )
    config_path.write_text(
        "config_schema_version: 4\n"
        "strategy: {id: example.007_ctp.production}\n"
        "runtime: {mode: live, preset: managed_live_direct}\n"
        "parameters: {}\n"
        "secrets_ref: config_yaml\n"
        "ctp_production:\n"
        + values
        + "\n",
        encoding="utf-8",
    )
    config_path.chmod(0o600)
    registration = RegisteredRuntime(
        runtime_dir=tmp_path,
        strategy_id="example.007_ctp.production",
        allowed_presets=("managed_live_direct",),
        allowed_secrets_refs=("config_yaml",),
    )
    registry = RuntimeRegistry((registration,))

    config = load_runtime_config(tmp_path, registry=registry)
    require_loaded_runtime_config_seal(config, registry)
    assert config.ctp_production is not None
    assert config.ctp_production.user_id == _PRIVATE_VALUES["user_id"]
    assert _PRIVATE_VALUES["password"] not in repr(config)


@pytest.mark.parametrize(
    "field_name",
    ("front", "environment", "route", "receipt", "approval", "capabilities"),
)
def test_production_yaml_cannot_choose_route_or_admission(
    field_name: str,
) -> None:
    private_values = dict(_PRIVATE_VALUES)
    private_values[field_name] = "synthetic-forbidden-value"
    with pytest.raises(RuntimeConfigError) as caught:
        _parse_production(document=_production_document(private_values=private_values))

    assert caught.value.field_path == "ctp_production"
    assert caught.value.reason == "field_not_allowed"
    assert "synthetic-forbidden-value" not in str(caught.value)


@pytest.mark.parametrize(
    "document,strategy_dir,expected_reason",
    (
        (
            _production_document(),
            Path(__file__).resolve().parents[3] / "examples" / "007_ctp" / "runtime",
            "ctp_production_runtime_path_mismatch",
        ),
        (
            _production_document(mode="simulation", preset="replay"),
            runtime_config.CTP_PRODUCTION_RUNTIME_DIR,
            "ctp_production_scope_not_allowed",
        ),
        (
            _production_document(secrets_ref="runtime_secrets"),
            runtime_config.CTP_PRODUCTION_RUNTIME_DIR,
            "ctp_production_secret_source_mismatch",
        ),
    ),
)
def test_production_config_rejects_path_mode_and_secret_source_mismatch(
    document: dict, strategy_dir: Path, expected_reason: str
) -> None:
    with pytest.raises(RuntimeConfigError) as caught:
        _parse_production(strategy_dir=strategy_dir, document=document)

    assert caught.value.reason == expected_reason
    assert "synthetic-production-password-never-use" not in str(caught.value)


def test_production_config_rejects_simnow_block_and_invalid_hedge_flag() -> None:
    both = _production_document()
    both["ctp_simnow"] = {"selection": "synthetic"}
    with pytest.raises(RuntimeConfigError) as caught:
        _parse_production(document=both)
    assert caught.value.reason == "ctp_private_blocks_mutually_exclusive"

    invalid_values = dict(_PRIVATE_VALUES, hedge_flag="unexpected")
    with pytest.raises(RuntimeConfigError) as caught:
        _parse_production(document=_production_document(private_values=invalid_values))
    assert caught.value.reason == "invalid_ctp_production_value"
    assert "unexpected" not in str(caught.value)


def test_registered_config_still_cannot_resolve_a_production_route(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runtime_config, "CTP_PRODUCTION_RUNTIME_DIR", tmp_path)
    registration = RegisteredRuntime(
        runtime_dir=tmp_path,
        strategy_id="example.007_ctp.production",
        allowed_presets=("managed_live_direct",),
        allowed_secrets_refs=("config_yaml",),
    )
    registry = RuntimeRegistry((registration,))
    config = runtime_config._seal_loaded_runtime_config(
        _parse_production(strategy_dir=tmp_path), registry
    )
    assert config.ctp_production is not None
    assert config.ctp_production.md_front == _PRIVATE_VALUES["md_front"]
    assert config.ctp_production.td_front == _PRIVATE_VALUES["td_front"]

    with pytest.raises(RuntimeConfigError) as caught:
        resolve_runtime_config(config, registry)

    assert caught.value.reason == "ctp_production_admission_unavailable"
    assert "synthetic-production-password-never-use" not in str(caught.value)


def test_default_cli_rejects_reserved_production_path_before_config_or_provider_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    read_attempts = []
    socket_attempts = []
    provider_import_attempts = []

    def unexpected_config_read(*args, **kwargs):
        read_attempts.append((args, kwargs))
        raise AssertionError("unregistered production path reached config file read")

    import socket

    original_import = builtins.__import__

    def reject_provider_import(name, *args, **kwargs):
        if name == "backtrader" or name.startswith("backtrader."):
            provider_import_attempts.append(name)
            raise AssertionError("unregistered production path imported Backtrader")
        if any(name == prefix or name.startswith(prefix + ".") for prefix in (
            "bt_api_ctp",
            "bt_api_py",
            "bt_api_base",
        )):
            provider_import_attempts.append(name)
            raise AssertionError("unregistered production path imported a provider package")
        return original_import(name, *args, **kwargs)

    def unexpected_socket(*args, **kwargs):
        socket_attempts.append((args, kwargs))
        raise AssertionError("unregistered production path attempted network I/O")

    monkeypatch.setattr(runtime_config, "_read_config_text", unexpected_config_read)
    monkeypatch.setattr(socket, "socket", unexpected_socket)
    monkeypatch.setattr(builtins, "__import__", reject_provider_import)
    stdout = io.StringIO()
    stderr = io.StringIO()

    status = main(
        ["validate", "--strategy-dir", str(runtime_config.CTP_PRODUCTION_RUNTIME_DIR)],
        stdout=stdout,
        stderr=stderr,
    )

    payload = json.loads(stderr.getvalue().strip())
    assert status == 2
    assert payload["reason"] == "runtime_not_registered"
    assert not read_attempts
    assert not socket_attempts
    assert not provider_import_attempts
