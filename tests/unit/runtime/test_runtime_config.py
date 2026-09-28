"""Regression coverage for the configuration-first runtime boundary."""

from __future__ import annotations

import io
import json
import dataclasses
import builtins
import os
import socket
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

import pytest
import backtrader_runtime.inventory as runtime_inventory
import backtrader_runtime.config as runtime_config
import backtrader_runtime.cli as runtime_cli

from backtrader_runtime import (
    CONFIG_EXISTS,
    CONFIG_REQUIRED,
    CONFIG_SCHEMA_UNSUPPORTED,
    ENVIRONMENT_MISMATCH,
    MODE_PRESET_MISMATCH,
    PRESET_POLICY_VIOLATION,
    RegisteredRuntime,
    RuntimeConfigError,
    RuntimeRegistry,
    bootstrap_runtime_config,
    default_runtime_registry,
    load_runtime_config,
    resolve_runtime_config,
)
from backtrader_runtime.config import require_loaded_runtime_config_seal
from backtrader_runtime.cli import main
from backtrader_runtime.inventory import (
    ITERATION41_014_1_REGISTRATION,
    ITERATION41_014_1_RUNTIME_DIR,
    ITERATION41_014_1_STRATEGY_ID,
    iteration41_runtime_registry,
)
from backtrader_runtime.policy import (
    CAPABILITY_EXECUTION,
    CAPABILITY_GATEWAY,
    CAPABILITY_MONITOR,
    CAPABILITY_RISK,
    CAPABILITY_TRANSPORT_ZMQ,
)


PRESET_MODE = {
    "local_backtest": "backtest",
    "replay": "simulation",
    "shadow": "simulation",
    "paper": "simulation",
    "sandbox": "simulation",
    "managed_live_direct": "live",
    "managed_live_gateway": "live",
}
_APPROVAL_DIGEST = "a" * 64


@pytest.fixture(autouse=True)
def _use_acl_seam_for_synthetic_ctp_configs(monkeypatch: pytest.MonkeyPatch) -> None:
    # These parser tests use synthetic credentials.  Windows ACL integration is
    # exercised through the low-level policy seam because a temp directory's
    # inherited host ACL is not a safe fixture to rewrite.
    if os.name == "nt":
        monkeypatch.setattr(
            runtime_config, "_require_private_config_security", lambda *a, **k: None
        )


def _write_config(
    runtime_dir: Path,
    *,
    strategy_id: str = "example.runtime",
    mode: str = "simulation",
    preset: str = "replay",
    parameters: str = "{}",
    secrets_ref: str = "none",
) -> Path:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    content = """config_schema_version: 4
strategy:
  id: {strategy_id}
runtime:
  mode: {mode}
  preset: {preset}
parameters: {parameters}
secrets_ref: {secrets_ref}
""".format(
        strategy_id=strategy_id,
        mode=mode,
        preset=preset,
        parameters=parameters,
        secrets_ref=secrets_ref,
    )
    path = runtime_dir / "config.yaml"
    path.write_text(content, encoding="utf-8")
    return path


def _registry(
    runtime_dir: Path,
    *,
    strategy_id: str = "example.runtime",
    presets: tuple = ("replay",),
    parameter_keys: tuple = (),
    secrets_refs: tuple = ("none",),
    capabilities: tuple = (),
    sandbox_write_policy: str = "deny",
    approved: bool = False,
) -> RuntimeRegistry:
    return RuntimeRegistry(
        (
            RegisteredRuntime(
                runtime_dir=runtime_dir,
                strategy_id=strategy_id,
                allowed_presets=presets,
                allowed_parameter_keys=parameter_keys,
                allowed_secrets_refs=secrets_refs,
                available_capabilities=capabilities,
                sandbox_write_policy=sandbox_write_policy,
                approval_receipt_digest=_APPROVAL_DIGEST if approved else None,
            ),
        )
    )


def _read_json_line(stream: io.StringIO) -> dict:
    return json.loads(stream.getvalue().strip())


def test_runtime_entrypoint_import_does_not_import_legacy_backtrader() -> None:
    """The console entrypoint must be usable before legacy package imports."""

    script = (
        "import sys; import backtrader_runtime.cli; "
        "assert not any(name == 'backtrader' or name.startswith('backtrader.') "
        "for name in sys.modules), sorted(name for name in sys.modules "
        "if name == 'backtrader' or name.startswith('backtrader.'))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(Path(__file__).resolve().parents[3]),
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize(
    "content, expected_code",
    ((None, CONFIG_REQUIRED), ("config_schema_version: 3\n", CONFIG_SCHEMA_UNSUPPORTED)),
)
def test_missing_or_invalid_config_is_rejected_without_legacy_or_provider_imports(
    tmp_path: Path, content: Optional[str], expected_code: str
) -> None:
    if content is not None:
        (tmp_path / "config.yaml").write_text(content, encoding="utf-8")
    script = """
import sys
from pathlib import Path
from backtrader_runtime import RuntimeConfigError, load_runtime_config

try:
    load_runtime_config(Path(sys.argv[1]))
except RuntimeConfigError as error:
    assert error.code == sys.argv[2], error.as_dict()
else:
    raise AssertionError('invalid runtime configuration was accepted')

assert not any(
    name == 'backtrader' or name.startswith('backtrader.')
    or name == 'bt_api_py' or name.startswith('bt_api_py.')
    for name in sys.modules
)
"""
    completed = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path), expected_code],
        cwd=str(Path(__file__).resolve().parents[3]),
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_default_inventory_keeps_source_replays_separate_from_managed_l2_and_package_fixture() -> (
    None
):
    registry = iteration41_runtime_registry()
    registrations = registry.registrations
    package_backtests = tuple(
        registration
        for registration in registrations
        if registration.runtime_id
        == runtime_inventory.ITERATION41_PACKAGE_LOCAL_BACKTEST_RUNTIME_ID
    )
    normal_replays = tuple(
        registration
        for registration in registrations
        if registration.allowed_presets == ("replay",)
        and not registration.offline_managed_execution
    )

    assert len(registrations) == 17
    assert package_backtests == (runtime_inventory.ITERATION41_PACKAGE_LOCAL_BACKTEST_REGISTRATION,)
    package_backtest = package_backtests[0]
    assert (
        package_backtest.runtime_dir
        == runtime_inventory.ITERATION41_PACKAGE_LOCAL_BACKTEST_RUNTIME_DIR
    )
    assert (
        package_backtest.strategy_id
        == runtime_inventory.ITERATION41_PACKAGE_LOCAL_BACKTEST_RUNTIME_ID
    )
    assert package_backtest.allowed_presets == ("local_backtest",)
    assert package_backtest.allowed_parameter_keys == ()
    assert package_backtest.allowed_secrets_refs == ("none",)
    assert package_backtest.sandbox_write_policy == "deny"
    assert package_backtest.available_capabilities == ()
    assert package_backtest.capability_modules == ()
    assert not package_backtest.offline_managed_execution
    package_effective = resolve_runtime_config(
        load_runtime_config(package_backtest.runtime_dir, registry=registry), registry
    )
    assert package_effective.mode == "backtest"
    assert package_effective.preset == "local_backtest"
    assert not package_effective.allows_network
    assert not package_effective.allows_external_writes
    assert not package_effective.allows_production_writes
    assert not package_effective.requires_approval
    assert len(normal_replays) == 11
    assert normal_replays == (
        runtime_inventory.ITERATION41_012_1_REGISTRATION,
        runtime_inventory.ITERATION41_012_2_REGISTRATION,
        runtime_inventory.ITERATION41_013_1_REGISTRATION,
        runtime_inventory.ITERATION41_013_2_REGISTRATION,
        runtime_inventory.ITERATION41_013_3_REGISTRATION,
        ITERATION41_014_1_REGISTRATION,
        runtime_inventory.ITERATION41_014_2_REGISTRATION,
        runtime_inventory.ITERATION41_015_REGISTRATION,
        runtime_inventory.ITERATION41_SAMPLE_REGISTRATION,
        runtime_inventory.ITERATION41_007_CTP_REGISTRATION,
        runtime_inventory.ITERATION41_010_LIVE_EXAMPLES_REGISTRATION,
    )
    assert runtime_inventory.ITERATION41_007_CTP_REGISTRATION in normal_replays
    for approved in normal_replays:
        assert approved.allowed_presets == ("replay",)
        assert approved.allowed_parameter_keys == ("scenario",)
        assert approved.sandbox_write_policy == "deny"
        assert approved.available_capabilities == ()
        expected_imports = (
            ()
            if approved is runtime_inventory.ITERATION41_SAMPLE_REGISTRATION
            else ("bt_api_py", "bt_api_base", "bt_api_binance", "bt_api_okx", "bt_api_ctp")
        )
        assert approved.capability_modules == expected_imports
    ctp_private = registry.require_runtime_dir(
        runtime_inventory.ITERATION41_013_3_CTP_PRIVATE_RUNTIME_DIR
    )
    assert ctp_private is runtime_inventory.ITERATION41_013_3_CTP_PRIVATE_READONLY_REGISTRATION
    assert ctp_private.runtime_id == runtime_inventory.ITERATION41_013_3_CTP_PRIVATE_RUNTIME_ID
    assert ctp_private.strategy_id == runtime_inventory.ITERATION41_013_3_STRATEGY_ID
    assert ctp_private.allowed_presets == ()
    assert tuple((profile.mode, profile.preset) for profile in ctp_private.profiles) == (
        ("simulation", "sandbox"),
    )
    assert ctp_private.profiles[0].allowed_secrets_refs == ("config_yaml",)
    assert tuple(
        (profile.mode, profile.preset, profile.reason)
        for profile in ctp_private.unavailable_mode_profiles
    ) == (
        ("live", "managed_live_direct", "managed_live_direct_profile_unavailable"),
    )
    assert ctp_private.allowed_parameter_keys == ()
    assert ctp_private.allowed_secrets_refs == ("none",)
    assert ctp_private.available_capabilities == ()
    assert ctp_private.sandbox_write_policy == "deny"
    assert ctp_private.runner_module is None
    assert ctp_private.capability_modules == ()
    assert not ctp_private.offline_managed_execution
    assert registry.ctp_simnow_readonly_bindings == (
        runtime_inventory.ITERATION41_013_3_CTP_PRIVATE_READONLY_BINDING,
        runtime_inventory.ITERATION41_007_CTP_PRIVATE_READONLY_BINDING,
    )
    simnow_007 = registry.require_runtime_dir(
        runtime_inventory.ITERATION41_007_CTP_PRIVATE_RUNTIME_DIR
    )
    assert simnow_007 is runtime_inventory.ITERATION41_007_CTP_PRIVATE_READONLY_REGISTRATION
    assert simnow_007.runtime_id == runtime_inventory.ITERATION41_007_CTP_PRIVATE_RUNTIME_ID
    assert simnow_007.strategy_id == runtime_inventory.ITERATION41_007_CTP_PRIVATE_STRATEGY_ID
    assert simnow_007.allowed_presets == ()
    assert simnow_007.allowed_parameter_keys == ()
    assert simnow_007.allowed_secrets_refs == ("none",)
    assert simnow_007.available_capabilities == ()
    assert simnow_007.capability_modules == ()
    assert simnow_007.sandbox_write_policy == "deny"
    assert simnow_007.runner_module is None
    assert simnow_007.runner_entrypoint == "run_runtime"
    assert not simnow_007.offline_managed_execution
    assert tuple((profile.mode, profile.preset) for profile in simnow_007.profiles) == (
        ("simulation", "sandbox"),
    )
    simnow_007_sandbox = simnow_007.profiles[0]
    assert simnow_007_sandbox.allowed_parameter_keys == ()
    assert simnow_007_sandbox.allowed_secrets_refs == ("config_yaml",)
    assert simnow_007_sandbox.available_capabilities == ()
    assert simnow_007_sandbox.capability_modules == ()
    assert simnow_007_sandbox.approval_receipt_digest is None
    assert simnow_007_sandbox.runner_module is None
    assert simnow_007_sandbox.offline_managed_execution is False
    assert simnow_007_sandbox.sandbox_write_policy == "deny"
    assert tuple(
        (profile.mode, profile.preset, profile.reason)
        for profile in simnow_007.unavailable_mode_profiles
    ) == (
        ("live", "managed_live_direct", "managed_live_direct_profile_unavailable"),
    )
    legacy_007_replay = registry.require_runtime_dir(
        runtime_inventory.ITERATION41_007_CTP_RUNTIME_DIR
    )
    assert legacy_007_replay is runtime_inventory.ITERATION41_007_CTP_REGISTRATION
    assert legacy_007_replay.strategy_id == runtime_inventory.ITERATION41_007_CTP_STRATEGY_ID
    assert legacy_007_replay.allowed_presets == ("replay",)
    shadow_registration = registry.require_runtime_dir(
        runtime_inventory.ITERATION41_010_OKX_SHADOW_RUNTIME_DIR
    )
    assert shadow_registration is runtime_inventory.ITERATION41_010_OKX_SHADOW_REGISTRATION
    assert shadow_registration.strategy_id == "example.010_live_examples.okx_public_shadow"
    assert shadow_registration.allowed_presets == ("shadow",)
    assert shadow_registration.allowed_parameter_keys == (
        "symbols",
        "duration_seconds",
        "orderbook_limit",
    )
    assert shadow_registration.bootstrap_parameters == (
        ("symbols", ("BTC/USDT:USDT", "ETH/USDT:USDT")),
        ("duration_seconds", 10),
        ("orderbook_limit", 5),
    )
    registration = registry.require_runtime_dir(ITERATION41_014_1_RUNTIME_DIR)
    assert registration.strategy_id == ITERATION41_014_1_STRATEGY_ID
    assert registration.allowed_presets == ("replay",)
    assert registration.allowed_parameter_keys == ("scenario",)
    assert registration.sandbox_write_policy == "deny"
    assert registration.available_capabilities == ()
    highfreq_registration = registry.require_runtime_dir(
        runtime_inventory.ITERATION41_015_RUNTIME_DIR
    )
    assert highfreq_registration.strategy_id == runtime_inventory.ITERATION41_015_STRATEGY_ID
    assert highfreq_registration.allowed_presets == ("replay",)
    assert highfreq_registration.allowed_parameter_keys == ("scenario",)
    sample_registration = registry.require_runtime_dir(
        runtime_inventory.ITERATION41_SAMPLE_RUNTIME_DIR
    )
    assert sample_registration.strategy_id == runtime_inventory.ITERATION41_SAMPLE_STRATEGY_ID
    assert sample_registration.allowed_presets == ("replay",)
    assert sample_registration.allowed_parameter_keys == ("scenario",)
    managed = tuple(
        registration for registration in registrations if registration.offline_managed_execution
    )
    assert len(managed) == 2
    assert managed == (
        runtime_inventory.ITERATION41_013_3_MANAGED_REPLAY_REGISTRATION,
        runtime_inventory.ITERATION41_CTP_MECHANICAL_MANAGED_REPLAY_REGISTRATION,
    )
    assert tuple(item.runtime_id for item in managed) == (
        runtime_inventory.ITERATION41_013_3_MANAGED_REPLAY_RUNTIME_ID,
        runtime_inventory.ITERATION41_CTP_MECHANICAL_MANAGED_REPLAY_RUNTIME_ID,
    )
    assert all(item.available_capabilities == ("execution", "risk", "monitor") for item in managed)
    assert all(
        item.capability_modules
        == ("bt_api_py", "bt_api_base", "bt_api_execution", "bt_api_risk", "bt_api_monitor")
        for item in managed
    )
    assert registry.require_runtime_set("iteration41-replay") == normal_replays
    assert registry.require_runtime_set("iteration41-managed-replay-l2") == managed
    assert registry.require_runtime_set("iteration41-local-backtest") == package_backtests
    assert default_runtime_registry().registrations == registrations


def test_missing_config_is_rejected_before_yaml_or_provider_work(
    tmp_path: Path, monkeypatch
) -> None:
    """No config is a deterministic zero-network, zero-plugin failure."""

    registry = _registry(tmp_path)
    calls = []

    def fail_socket(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("runtime config validation must not open a socket")

    import socket

    monkeypatch.setattr(socket, "socket", fail_socket)
    with pytest.raises(RuntimeConfigError) as caught:
        load_runtime_config(tmp_path, registry=registry)

    assert caught.value.code == CONFIG_REQUIRED
    assert caught.value.reason == "missing_config"
    assert calls == []


@pytest.mark.parametrize(
    "content, field_path, reason",
    (
        ("", "config.yaml", "empty_config"),
        ("config_schema_version: 3\n", "config_schema_version", "unsupported_schema_version"),
        (
            """config_schema_version: 4
config_schema_version: 4
strategy: {id: example.runtime}
runtime: {mode: simulation, preset: replay}
""",
            "config_schema_version",
            "duplicate_field",
        ),
        (
            """config_schema_version: 4
strategy: {id: example.runtime}
runtime: {mode: simulation, preset: replay}
parameters:
  scenario: one
  scenario: two
""",
            "parameters.scenario",
            "duplicate_field",
        ),
        (
            """config_schema_version: 4
strategy: {id: example.runtime}
runtime: {mode: simulation, preset: replay}
plugins: {enabled: true}
""",
            "plugins",
            "field_not_allowed",
        ),
    ),
)
def test_schema_rejections_are_stable_and_pre_plugin(
    tmp_path: Path, content: str, field_path: str, reason: str
) -> None:
    (tmp_path / "config.yaml").write_text(content, encoding="utf-8")
    registry = _registry(tmp_path)

    with pytest.raises(RuntimeConfigError) as caught:
        load_runtime_config(tmp_path, registry=registry)

    assert caught.value.code == CONFIG_SCHEMA_UNSUPPORTED
    assert caught.value.field_path == field_path
    assert caught.value.reason == reason


def test_unregistered_directory_is_rejected_before_reading_its_file(tmp_path: Path) -> None:
    _write_config(tmp_path)
    registry = RuntimeRegistry(())

    with pytest.raises(RuntimeConfigError) as caught:
        load_runtime_config(tmp_path, registry=registry)

    assert caught.value.code == PRESET_POLICY_VIOLATION
    assert caught.value.reason == "runtime_not_registered"


@pytest.mark.parametrize("preset", tuple(PRESET_MODE))
def test_all_seven_mode_preset_policies_resolve_to_sealed_effective_config(
    tmp_path: Path, preset: str
) -> None:
    mode = PRESET_MODE[preset]
    _write_config(tmp_path, mode=mode, preset=preset)
    capabilities = (
        CAPABILITY_EXECUTION,
        CAPABILITY_RISK,
        CAPABILITY_MONITOR,
        CAPABILITY_GATEWAY,
        CAPABILITY_TRANSPORT_ZMQ,
    )
    registry = _registry(
        tmp_path,
        presets=(preset,),
        capabilities=capabilities,
        approved=preset.startswith("managed_live"),
    )

    config = load_runtime_config(tmp_path, registry=registry)
    effective = resolve_runtime_config(config, registry)

    assert effective.mode == mode
    assert effective.preset == preset
    assert effective.allows_production_writes is preset.startswith("managed_live")
    if preset in ("local_backtest", "replay"):
        assert effective.allows_network is False
        assert effective.allows_external_writes is False
        assert effective.order_route is None
    if preset in ("shadow", "paper"):
        assert effective.allows_network is True
        assert effective.allows_external_writes is False
    if preset == "sandbox":
        assert effective.allows_external_writes is False
        assert effective.allows_production_writes is False
        assert effective.order_route is None
    if preset.startswith("managed_live"):
        assert effective.allows_external_writes is True
        assert effective.requires_live_confirmation is True
        assert CAPABILITY_EXECUTION in effective.required_capabilities
        assert CAPABILITY_RISK in effective.required_capabilities
        assert CAPABILITY_MONITOR in effective.required_capabilities


def test_unbound_loader_config_can_complete_the_safe_two_stage_resolution(
    tmp_path: Path,
) -> None:
    """Inspection without a registry remains usable before trusted resolution."""

    _write_config(tmp_path)
    config = load_runtime_config(tmp_path)
    registry = _registry(tmp_path)

    effective = resolve_runtime_config(config, registry)

    assert effective.registration is registry.require_runtime_dir(tmp_path)
    assert effective.mode == "simulation"
    assert effective.preset == "replay"


def test_mismatched_mode_and_preset_is_never_auto_corrected(tmp_path: Path) -> None:
    _write_config(tmp_path, mode="live", preset="replay")
    registry = _registry(tmp_path, presets=("replay",))

    with pytest.raises(RuntimeConfigError) as caught:
        load_runtime_config(tmp_path, registry=registry)

    assert caught.value.code == MODE_PRESET_MISMATCH
    assert caught.value.reason == "mode_preset_mismatch"


def test_resolver_rejects_unregistered_parameter_and_replay_secret(tmp_path: Path) -> None:
    _write_config(tmp_path, parameters="{scenario: baseline}", secrets_ref="runtime_secrets")
    registry = _registry(tmp_path, parameter_keys=("scenario",), secrets_refs=("runtime_secrets",))
    config = load_runtime_config(tmp_path, registry=registry)

    with pytest.raises(RuntimeConfigError) as caught:
        resolve_runtime_config(config, registry)

    assert caught.value.code == ENVIRONMENT_MISMATCH
    assert caught.value.reason == "secrets_not_allowed_for_preset"

    _write_config(tmp_path, parameters="{other: baseline}", secrets_ref="none")
    config = load_runtime_config(tmp_path, registry=registry)
    with pytest.raises(RuntimeConfigError) as caught:
        resolve_runtime_config(config, registry)

    assert caught.value.code == PRESET_POLICY_VIOLATION
    assert caught.value.field_path == "parameters.other"
    assert caught.value.reason == "parameter_not_registered"


def test_inline_credentials_and_runtime_controls_are_rejected(tmp_path: Path) -> None:
    _write_config(tmp_path, parameters="{api_key: leaked}")
    registry = _registry(tmp_path, parameter_keys=("api_key",))

    with pytest.raises(RuntimeConfigError) as caught:
        load_runtime_config(tmp_path, registry=registry)

    assert caught.value.code == CONFIG_SCHEMA_UNSUPPORTED
    assert caught.value.field_path == "parameters.api_key"
    assert caught.value.reason == "inline_secret"


def _ctp_simnow_mapping(password: str = "synthetic-password-never-use") -> str:
    return "\n".join(
        (
            "md_front: tcp://180.168.146.187:10211",
            "td_front: tcp://180.168.146.187:10201",
            "instrument_id: IF2612",
            "exchange_id: CFFEX",
            "hedge_flag: '1'",
            "broker_id: '9999'",
            "user_id: synthetic-account-001",
            "password: '" + password + "'",
            "app_id: synthetic-simnow-app",
            "auth_code: synthetic-auth-code",
        )
    )


def _write_ctp_simnow_config(
    runtime_dir: Path,
    *,
    password: str = "synthetic-password-never-use",
    mode: str = "simulation",
    preset: str = "sandbox",
    secrets_ref: str = "config_yaml",
    ctp_mapping: Optional[str] = None,
) -> None:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    mapping = _ctp_simnow_mapping(password) if ctp_mapping is None else ctp_mapping
    ctp_line = (
        "ctp_simnow:\n" + "\n".join("  " + line for line in mapping.splitlines())
        if "\n" in mapping
        else "ctp_simnow: " + mapping
    )
    content = (
        "config_schema_version: 4\n"
        "strategy: {id: example.runtime}\n"
        "runtime: {mode: " + mode + ", preset: " + preset + "}\n"
        "parameters: {}\n"
        "secrets_ref: " + secrets_ref + "\n" + ctp_line + "\n"
    )
    config_path = runtime_dir / "config.yaml"
    config_path.write_text(
        content,
        encoding="utf-8",
    )
    if os.name == "posix":
        runtime_dir.chmod(0o700)
        config_path.chmod(0o600)


def _write_canonical_ctp_config(
    runtime_dir: Path,
    *,
    mode: str,
    preset: str,
    strategy_id: str = "example.runtime",
    secrets_ref: str = "config_yaml",
    ctp_mapping: Optional[str] = None,
) -> Path:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    mapping = _ctp_simnow_mapping() if ctp_mapping is None else ctp_mapping
    ctp_block = "ctp:\n" + "\n".join("  " + line for line in mapping.splitlines())
    content = (
        "config_schema_version: 4\n"
        "strategy: {id: " + strategy_id + "}\n"
        "runtime: {mode: " + mode + ", preset: " + preset + "}\n"
        "parameters: {}\n"
        "secrets_ref: " + secrets_ref + "\n" + ctp_block + "\n"
    )
    config_path = runtime_dir / "config.yaml"
    config_path.write_text(content, encoding="utf-8")
    if os.name == "posix":
        runtime_dir.chmod(0o700)
        config_path.chmod(0o600)
    return config_path


def test_private_ctp_simnow_config_is_sandbox_scoped_redacted_and_sealed(
    tmp_path: Path,
) -> None:
    _write_ctp_simnow_config(tmp_path)
    registry = _registry(tmp_path, presets=("sandbox",), secrets_refs=("config_yaml",))
    config = load_runtime_config(tmp_path, registry=registry)

    rendered = repr(config)
    public = json.dumps(config.as_public_dict(), sort_keys=True)
    assert "synthetic-password-never-use" not in rendered + public
    assert "synthetic-account-001" not in rendered + public
    assert "9999" not in rendered + public
    assert "synthetic-auth-code" not in rendered + public
    assert "CtpSimNowPrivateConfig(<redacted>)" in repr(config.ctp_simnow)
    assert config.ctp_simnow.md_front == "tcp://180.168.146.187:10211"
    assert config.ctp_simnow.td_front == "tcp://180.168.146.187:10201"
    assert (
        config.ctp_simnow.md_front,
        config.ctp_simnow.td_front,
        config.ctp_simnow.instrument_id,
        config.ctp_simnow.exchange_id,
        config.ctp_simnow.hedge_flag,
        config.ctp_simnow.broker_id,
        config.ctp_simnow.user_id,
        config.ctp_simnow.password,
        config.ctp_simnow.app_id,
        config.ctp_simnow.auth_code,
    ) == (
        "tcp://180.168.146.187:10211",
        "tcp://180.168.146.187:10201",
        "IF2612",
        "CFFEX",
        "1",
        "9999",
        "synthetic-account-001",
        "synthetic-password-never-use",
        "synthetic-simnow-app",
        "synthetic-auth-code",
    )
    assert tuple(config.ctp_simnow.front_pairs) == (
        {
            "md_front": "tcp://180.168.146.187:10211",
            "td_front": "tcp://180.168.146.187:10201",
        },
    )
    require_loaded_runtime_config_seal(config, registry)

    object.__setattr__(config.ctp_simnow, "password", "mutated-private-password")
    with pytest.raises(RuntimeConfigError) as caught:
        require_loaded_runtime_config_seal(config, registry)
    assert caught.value.reason == "config_provenance_invalid"
    assert "mutated-private-password" not in str(caught.value)


def test_canonical_ctp_block_parses_for_both_modes_at_same_registered_path_and_stays_gated(
    tmp_path: Path,
) -> None:
    registry = _registry(
        tmp_path,
        presets=("sandbox", "managed_live_direct"),
        secrets_refs=("config_yaml",),
    )
    sandbox_mapping = (
        _ctp_simnow_mapping()
        .replace("tcp://180.168.146.187:10211", "tcp://configured-md.example:41011")
        .replace("tcp://180.168.146.187:10201", "tcp://configured-td.example:41001")
    )
    config_path = _write_canonical_ctp_config(
        tmp_path,
        mode="simulation",
        preset="sandbox",
        ctp_mapping=sandbox_mapping,
    )
    sandbox_file_identity = (config_path.stat().st_dev, config_path.stat().st_ino)
    simulation = load_runtime_config(tmp_path, registry=registry)

    assert simulation.source_path == config_path
    assert type(simulation.ctp) is runtime_config.CtpPrivateConfig
    assert simulation.ctp is simulation.ctp_simnow
    assert simulation.ctp.front_pairs == simulation.ctp_simnow.front_pairs
    assert "synthetic-password-never-use" not in repr(simulation)
    require_loaded_runtime_config_seal(simulation, registry)
    resolve_runtime_config(simulation, registry)

    live_mapping = (
        sandbox_mapping.replace("configured-md.example:41011", "production-md.example:51011")
        .replace("configured-td.example:41001", "production-td.example:51001")
        .replace("instrument_id: IF2612", "instrument_id: IH2612")
        .replace("exchange_id: CFFEX", "exchange_id: SHFE")
        .replace("broker_id: '9999'", "broker_id: '8888'")
        .replace("user_id: synthetic-account-001", "user_id: synthetic-production-account")
        .replace("password: 'synthetic-password-never-use'", "password: 'synthetic-live-password'")
        .replace("app_id: synthetic-simnow-app", "app_id: synthetic-production-app")
        .replace("auth_code: synthetic-auth-code", "auth_code: synthetic-production-auth")
    )
    _write_canonical_ctp_config(
        tmp_path,
        mode="live",
        preset="managed_live_direct",
        ctp_mapping=live_mapping,
    )
    assert (config_path.stat().st_dev, config_path.stat().st_ino) == sandbox_file_identity
    live = load_runtime_config(tmp_path, registry=registry)

    assert live.source_path == config_path
    assert simulation.source_path == live.source_path
    assert simulation.strategy_dir == live.strategy_dir == tmp_path
    assert live.mode == "live"
    assert type(live.ctp) is runtime_config.CtpPrivateConfig
    assert live.ctp_simnow is None
    assert live.ctp_production is None
    assert live.ctp.front_pairs != simulation.ctp.front_pairs
    assert live.ctp.md_front == "tcp://production-md.example:51011"
    assert live.ctp.td_front == "tcp://production-td.example:51001"
    assert live.ctp.instrument_id == "IH2612"
    assert live.ctp.exchange_id == "SHFE"
    assert live.ctp.broker_id == "8888"
    assert live.ctp.user_id == "synthetic-production-account"
    assert live.config_digest != simulation.config_digest
    assert "synthetic-password-never-use" not in repr(live)
    require_loaded_runtime_config_seal(live, registry)

    # The old loader seal cannot be reused to mutate the already-loaded
    # sandbox snapshot into the new account/front/contract scope from disk.
    object.__setattr__(simulation.ctp, "md_front", live.ctp.md_front)
    object.__setattr__(simulation.ctp, "broker_id", live.ctp.broker_id)
    object.__setattr__(simulation.ctp, "instrument_id", live.ctp.instrument_id)
    with pytest.raises(RuntimeConfigError) as stale_seal:
        require_loaded_runtime_config_seal(simulation, registry)
    assert stale_seal.value.reason == "config_provenance_invalid"

    # Changing only the config's selected policy parses successfully, but the
    # same registration has no live approval or capabilities and cannot bind a
    # write-capable effective runtime.
    with pytest.raises(RuntimeConfigError) as caught:
        resolve_runtime_config(live, registry)
    assert caught.value.reason == "approval_receipt_missing"


def test_default_inventory_rejects_synthetic_same_file_live_transition_before_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registration = dataclasses.replace(
        runtime_inventory.ITERATION41_013_3_CTP_PRIVATE_READONLY_REGISTRATION,
        runtime_dir=tmp_path,
    )
    monkeypatch.setattr(
        runtime_inventory,
        "ITERATION41_013_3_CTP_PRIVATE_READONLY_REGISTRATION",
        registration,
    )
    registry = default_runtime_registry()
    assert registry.require_runtime_dir(tmp_path) is registration
    assert registration.allowed_presets == ()
    assert registration.sandbox_write_policy == "deny"
    assert registration.available_capabilities == ()
    assert registration.runner_module is None
    assert tuple(
        (profile.mode, profile.preset, profile.reason)
        for profile in registration.unavailable_mode_profiles
    ) == (
        ("live", "managed_live_direct", "managed_live_direct_profile_unavailable"),
    )

    canonical_mapping = (
        _ctp_simnow_mapping()
        .replace("tcp://180.168.146.187:10211", "tcp://configured-md.example:41011")
        .replace("tcp://180.168.146.187:10201", "tcp://configured-td.example:41001")
    )
    config_path = _write_canonical_ctp_config(
        tmp_path,
        mode="simulation",
        preset="sandbox",
        strategy_id=registration.strategy_id,
        ctp_mapping=canonical_mapping,
    )
    simulation_bytes = config_path.read_bytes()
    config_file_identity = (config_path.stat().st_dev, config_path.stat().st_ino)
    assert (
        runtime_cli.main(
            ["validate", "--strategy-dir", str(tmp_path)],
            registry=registry,
            environ={},
            stdout=io.StringIO(),
            stderr=io.StringIO(),
        )
        == 0
    )
    doctor_out, doctor_err = io.StringIO(), io.StringIO()
    assert (
        runtime_cli.main(
            ["doctor", "--strategy-dir", str(tmp_path)],
            registry=registry,
            environ={},
            stdout=doctor_out,
            stderr=doctor_err,
        )
        == 0
    ), doctor_err.getvalue()
    sandbox_diagnostic = _read_json_line(doctor_out)["diagnostic"]
    assert sandbox_diagnostic["offline"] is True
    assert sandbox_diagnostic["provider_preflight_started"] is False
    assert sandbox_diagnostic["read_only_preflight_dispatch_available"] is False
    assert (
        sandbox_diagnostic["read_only_preflight_dispatch_unavailable_reason"]
        == "ctp_simnow_preflight_supervisor_required"
    )
    assert sandbox_diagnostic["next_actions"][0]["action"] == (
        "preflight_requires_process_supervisor"
    )

    preflight_dispatches = []

    def fake_preflight(effective, selected_registry):
        preflight_dispatches.append((effective, selected_registry))
        return SimpleNamespace(as_public_dict=lambda: {"status": "synthetic_read_only"})

    monkeypatch.setattr(
        runtime_cli,
        "dispatch_registered_ctp_simnow_readonly_preflight",
        fake_preflight,
    )
    preflight_out, preflight_err = io.StringIO(), io.StringIO()
    assert (
        runtime_cli.main(
            ["preflight", "--strategy-dir", str(tmp_path)],
            registry=registry,
            environ={},
            stdout=preflight_out,
            stderr=preflight_err,
        )
        == 2
    )
    sandbox_preflight = _read_json_line(preflight_err)
    assert sandbox_preflight["reason"] == "ctp_simnow_preflight_supervisor_required"
    assert sandbox_preflight["diagnostic"]["provider_preflight_started"] is False
    assert sandbox_preflight["diagnostic"]["offline"] is True
    assert len(preflight_dispatches) == 0

    live_bytes = simulation_bytes
    for old_value, new_value in (
        (b"mode: simulation", b"mode: live"),
        (b"preset: sandbox", b"preset: managed_live_direct"),
        (b"configured-md.example:41011", b"production-md.example:51011"),
        (b"configured-td.example:41001", b"production-td.example:51001"),
        (b"instrument_id: IF2612", b"instrument_id: IH2612"),
        (b"exchange_id: CFFEX", b"exchange_id: SHFE"),
        (b"broker_id: '9999'", b"broker_id: '8888'"),
        (b"user_id: synthetic-account-001", b"user_id: synthetic-production-account"),
        (
            b"password: 'synthetic-password-never-use'",
            b"password: 'synthetic-production-password-never-use'",
        ),
        (b"app_id: synthetic-simnow-app", b"app_id: synthetic-production-app"),
        (b"auth_code: synthetic-auth-code", b"auth_code: synthetic-production-auth"),
    ):
        live_bytes = live_bytes.replace(old_value, new_value)
    assert live_bytes != simulation_bytes
    config_path.write_bytes(live_bytes)
    assert config_path.read_bytes() == live_bytes
    assert (config_path.stat().st_dev, config_path.stat().st_ino) == config_file_identity

    forbidden_calls = []

    def forbidden(name: str):
        def fail(*args, **kwargs):
            forbidden_calls.append(name)
            raise AssertionError("unexpected preflight boundary: " + name)

        return fail

    from backtrader_runtime import credential_resolver

    monkeypatch.setattr(
        credential_resolver,
        "resolve_runtime_credentials",
        forbidden("credential resolution"),
    )
    monkeypatch.setattr(socket, "socket", forbidden("socket creation"))
    monkeypatch.setattr(socket, "create_connection", forbidden("socket connection"))
    monkeypatch.setattr(
        runtime_cli,
        "dispatch_registered_runtime",
        forbidden("runner or write dispatch"),
    )
    monkeypatch.setattr(
        runtime_cli,
        "dispatch_registered_ctp_simnow_readonly_preflight",
        forbidden("CTP preflight dispatch"),
    )
    original_import = builtins.__import__

    def guard_sdk_import(name, *args, **kwargs):
        if name == "bt_api_ctp" or name.startswith("bt_api_ctp."):
            forbidden_calls.append("CTP SDK import")
            raise AssertionError("unexpected CTP SDK import")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guard_sdk_import)
    for command_args in (
        ["doctor", "--strategy-dir", str(tmp_path)],
        ["validate", "--strategy-dir", str(tmp_path)],
        ["run", "--strategy-dir", str(tmp_path), "--confirm-live"],
        ["preflight", "--strategy-dir", str(tmp_path)],
    ):
        stdout = io.StringIO()
        stderr = io.StringIO()
        assert (
            runtime_cli.main(
                command_args,
                registry=registry,
                environ={},
                stdout=stdout,
                stderr=stderr,
            )
            == 2
        ), (command_args, stdout.getvalue(), stderr.getvalue())
        failure = _read_json_line(stderr)
        assert failure["reason"] in {
            "managed_live_direct_profile_unavailable",
            "profile_dispatch_unavailable",
            "ctp_simnow_preflight_supervisor_required",
        }
        assert (
            "synthetic-production-password-never-use" not in stdout.getvalue() + stderr.getvalue()
        )
    assert forbidden_calls == []
    assert config_path.read_bytes() == live_bytes


def test_legacy_production_runtime_path_is_rejected_before_config_or_provider_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy_runtime_dir = (
        Path(__file__).resolve().parents[3]
        / "examples"
        / "007_ctp"
        / "runtime-production"
    )
    registry = default_runtime_registry()
    forbidden_calls = []

    def forbidden(name: str):
        def fail(*args, **kwargs):
            forbidden_calls.append(name)
            raise AssertionError("unexpected legacy production path access: " + name)

        return fail

    monkeypatch.setattr(runtime_config, "_read_config_text", forbidden("config read"))
    monkeypatch.setattr(runtime_cli, "bootstrap_runtime_config", forbidden("config bootstrap"))
    monkeypatch.setattr(
        runtime_cli, "dispatch_registered_runtime", forbidden("runner dispatch")
    )
    monkeypatch.setattr(
        runtime_cli,
        "dispatch_registered_ctp_simnow_readonly_preflight",
        forbidden("CTP preflight dispatch"),
    )
    monkeypatch.setattr(socket, "socket", forbidden("socket creation"))
    monkeypatch.setattr(socket, "create_connection", forbidden("socket connection"))

    from backtrader_runtime import credential_resolver

    monkeypatch.setattr(
        credential_resolver,
        "resolve_runtime_credentials",
        forbidden("credential resolution"),
    )

    for command_args in (
        ["bootstrap", "--strategy-dir", str(legacy_runtime_dir)],
        ["validate", "--strategy-dir", str(legacy_runtime_dir)],
        ["doctor", "--strategy-dir", str(legacy_runtime_dir)],
        ["preflight", "--strategy-dir", str(legacy_runtime_dir)],
        ["run", "--strategy-dir", str(legacy_runtime_dir), "--confirm-live"],
    ):
        stdout = io.StringIO()
        stderr = io.StringIO()
        assert (
            runtime_cli.main(
                command_args,
                registry=registry,
                environ={},
                stdout=stdout,
                stderr=stderr,
            )
            == 2
        ), (command_args, stdout.getvalue(), stderr.getvalue())
        failure = _read_json_line(stderr)
        assert failure["reason"] == "runtime_not_registered"
        assert failure["field_path"] == "strategy_dir"
        assert stdout.getvalue() == ""

    assert forbidden_calls == []


def test_private_ctp_credentials_do_not_enter_public_config_digest(tmp_path: Path) -> None:
    _write_ctp_simnow_config(tmp_path, password="first-synthetic-password")
    registry = _registry(tmp_path, presets=("sandbox",), secrets_refs=("config_yaml",))
    first = load_runtime_config(tmp_path, registry=registry)
    _write_ctp_simnow_config(tmp_path, password="second-synthetic-password")
    second = load_runtime_config(tmp_path, registry=registry)

    assert first.config_digest == second.config_digest
    assert first.ctp_simnow.password != second.ctp_simnow.password
    assert "first-synthetic-password" not in repr(first)
    assert "second-synthetic-password" not in json.dumps(second.as_public_dict())


def _ctp_simnow_multi_front_mapping(pairs: tuple) -> str:
    lines = ["front_pairs:"]
    for md_front, td_front in pairs:
        lines.extend(("  - md_front: " + md_front, "    td_front: " + td_front))
    lines.extend(
        (
            "instrument_id: IF2612",
            "exchange_id: CFFEX",
            "hedge_flag: '1'",
            "broker_id: '9999'",
            "user_id: synthetic-account-001",
            "password: synthetic-password-never-use",
            "app_id: synthetic-simnow-app",
            "auth_code: synthetic-auth-code",
        )
    )
    return "\n".join(lines)


def test_ctp_simnow_multiple_front_pairs_preserve_order_and_bind_digest_and_seal(
    tmp_path: Path,
) -> None:
    pairs = (
        ("tcp://180.168.146.187:10211", "tcp://180.168.146.187:10201"),
        ("tcp://180.168.146.187:10212", "tcp://180.168.146.187:10202"),
    )
    first_dir = tmp_path / "first"
    _write_ctp_simnow_config(first_dir, ctp_mapping=_ctp_simnow_multi_front_mapping(pairs))
    first_registry = _registry(first_dir, presets=("sandbox",), secrets_refs=("config_yaml",))
    first = load_runtime_config(first_dir, registry=first_registry)

    assert first.ctp_simnow is not None
    assert first.ctp_simnow.md_front is None
    assert first.ctp_simnow.td_front is None
    assert tuple(dict(pair) for pair in first.ctp_simnow.front_pairs) == tuple(
        {"md_front": md_front, "td_front": td_front} for md_front, td_front in pairs
    )
    with pytest.raises(TypeError):
        first.ctp_simnow.front_pairs[0]["md_front"] = "tcp://changed.invalid:1"
    rendered = repr(first) + json.dumps(first.as_public_dict(), sort_keys=True)
    for private_value in (
        "synthetic-password-never-use",
        "synthetic-account-001",
        "180.168.146.187",
    ):
        assert private_value not in rendered
    require_loaded_runtime_config_seal(first, first_registry)

    reordered_dir = tmp_path / "reordered"
    _write_ctp_simnow_config(
        reordered_dir,
        ctp_mapping=_ctp_simnow_multi_front_mapping(tuple(reversed(pairs))),
    )
    reordered_registry = _registry(
        reordered_dir, presets=("sandbox",), secrets_refs=("config_yaml",)
    )
    reordered = load_runtime_config(reordered_dir, registry=reordered_registry)
    assert reordered.config_digest != first.config_digest

    changed_second_pair = (
        pairs[0],
        ("tcp://changed-md.example:10212", pairs[1][1]),
    )
    changed_dir = tmp_path / "changed-second"
    _write_ctp_simnow_config(
        changed_dir,
        ctp_mapping=_ctp_simnow_multi_front_mapping(changed_second_pair),
    )
    changed_registry = _registry(changed_dir, presets=("sandbox",), secrets_refs=("config_yaml",))
    changed = load_runtime_config(changed_dir, registry=changed_registry)
    assert changed.config_digest != first.config_digest

    # Even a mutation through Python's low-level frozen-dataclass escape hatch
    # must be detected by the private loader seal for every pair.
    object.__setattr__(
        first.ctp_simnow,
        "front_pairs",
        (
            {"md_front": pairs[0][0], "td_front": pairs[0][1]},
            {"md_front": pairs[1][0], "td_front": "tcp://altered.invalid:10202"},
        ),
    )
    with pytest.raises(RuntimeConfigError) as caught:
        require_loaded_runtime_config_seal(first, first_registry)
    assert caught.value.reason == "config_provenance_invalid"
    assert "altered.invalid" not in str(caught.value)


def test_doctor_reports_every_configured_front_pair_without_selecting_or_probing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pairs = (
        ("tcp://md-a.invalid:12011", "tcp://td-a.invalid:12001"),
        ("tcp://md-b.invalid:12012", "tcp://td-b.invalid:12002"),
    )
    _write_ctp_simnow_config(tmp_path, ctp_mapping=_ctp_simnow_multi_front_mapping(pairs))
    registry = _registry(tmp_path, presets=("sandbox",), secrets_refs=("config_yaml",))
    effective = resolve_runtime_config(load_runtime_config(tmp_path, registry=registry), registry)
    monkeypatch.setattr(
        runtime_cli,
        "_require_config_driven_ctp_binding",
        lambda *_args: object(),
    )

    diagnostic = runtime_cli._doctor_projection(effective, tmp_path, registry)

    assert diagnostic["offline"] is True
    assert diagnostic["provider_preflight_started"] is False
    assert diagnostic["configured_simnow_fronts"] == {
        "front_pairs": [
            {"md_front": md_front, "td_front": td_front} for md_front, td_front in pairs
        ]
    }
    assert diagnostic["next_actions"][0]["action"] == "preflight"
    rendered = json.dumps(diagnostic)
    assert "synthetic-password-never-use" not in rendered
    assert "synthetic-auth-code" not in rendered
    assert "secret" not in json.dumps(diagnostic).casefold()


@pytest.mark.parametrize(
    "front_form,field_path,reason",
    (
        ("front_pairs: []", "ctp_simnow.front_pairs", "invalid_ctp_simnow_front_pairs"),
        (
            "front_pairs: tcp://180.168.146.187:10211",
            "ctp_simnow.front_pairs",
            "invalid_ctp_simnow_front_pairs",
        ),
        (
            "\n".join(
                (
                    "front_pairs:",
                    "  - md_front: tcp://180.168.146.187:10211",
                    "    td_front: tcp://180.168.146.187:10201",
                    "md_front: tcp://180.168.146.187:10211",
                )
            ),
            "ctp_simnow.front_pairs",
            "mixed_ctp_simnow_front_forms",
        ),
        (
            "\n".join(
                (
                    "front_pairs:",
                    "  - md_front: tcp://180.168.146.187:10211",
                    "    td_front: tcp://180.168.146.187:10201",
                    "    selection: secret-sentinel",
                )
            ),
            "ctp_simnow.front_pairs[0].selection",
            "field_not_allowed",
        ),
        (
            "front_pairs:\n  - md_front: tcp://180.168.146.187:10211",
            "ctp_simnow.front_pairs[0].td_front",
            "required_field_missing",
        ),
        (
            "\n".join(
                (
                    "front_pairs:",
                    "  - md_front: http://invalid:101",
                    "    td_front: tcp://180.168.146.187:10201",
                )
            ),
            "ctp_simnow.front_pairs[0].md_front",
            "invalid_ctp_simnow_front",
        ),
    ),
)
def test_ctp_simnow_front_pairs_reject_malformed_or_ambiguous_forms(
    tmp_path: Path, front_form: str, field_path: str, reason: str
) -> None:
    mapping = front_form + "\n" + "\n".join(_ctp_simnow_mapping().splitlines()[2:])
    _write_ctp_simnow_config(tmp_path, ctp_mapping=mapping)
    registry = _registry(tmp_path, presets=("sandbox",), secrets_refs=("config_yaml",))

    with pytest.raises(RuntimeConfigError) as caught:
        load_runtime_config(tmp_path, registry=registry)

    assert caught.value.field_path == field_path
    assert caught.value.reason == reason
    assert "secret-sentinel" not in str(caught.value)
    assert "synthetic-password-never-use" not in str(caught.value)


def test_ctp_simnow_front_pairs_reject_exact_duplicates_and_more_than_limit(
    tmp_path: Path,
) -> None:
    pair = ("tcp://180.168.146.187:10211", "tcp://180.168.146.187:10201")
    duplicate_dir = tmp_path / "duplicate"
    _write_ctp_simnow_config(
        duplicate_dir, ctp_mapping=_ctp_simnow_multi_front_mapping((pair, pair))
    )
    duplicate_registry = _registry(
        duplicate_dir, presets=("sandbox",), secrets_refs=("config_yaml",)
    )
    with pytest.raises(RuntimeConfigError) as caught:
        load_runtime_config(duplicate_dir, registry=duplicate_registry)
    assert caught.value.field_path == "ctp_simnow.front_pairs[1]"
    assert caught.value.reason == "duplicate_ctp_simnow_front_pair"

    too_many_pairs = tuple(
        (
            "tcp://md{0}.example:10211".format(index),
            "tcp://td{0}.example:10201".format(index),
        )
        for index in range(9)
    )
    too_many_dir = tmp_path / "too-many"
    _write_ctp_simnow_config(
        too_many_dir, ctp_mapping=_ctp_simnow_multi_front_mapping(too_many_pairs)
    )
    too_many_registry = _registry(too_many_dir, presets=("sandbox",), secrets_refs=("config_yaml",))
    with pytest.raises(RuntimeConfigError) as caught:
        load_runtime_config(too_many_dir, registry=too_many_registry)
    assert caught.value.field_path == "ctp_simnow.front_pairs"
    assert caught.value.reason == "invalid_ctp_simnow_front_pairs"


def test_unbound_ctp_private_config_is_rejected_before_returning_credentials(
    tmp_path: Path,
) -> None:
    _write_ctp_simnow_config(tmp_path)

    with pytest.raises(RuntimeConfigError) as caught:
        load_runtime_config(tmp_path)

    assert caught.value.reason == "private_config_registration_required"
    assert "returned or used" in str(caught.value)
    assert "synthetic-password-never-use" not in repr(caught.value)


@pytest.mark.skipif(os.name != "posix", reason="POSIX private config permission gate")
@pytest.mark.parametrize(
    ("unsafe_target", "unsafe_mode"),
    (("file", 0o644), ("directory", 0o755)),
)
def test_private_config_permission_gate_rejects_unsafe_modes_before_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    unsafe_target: str,
    unsafe_mode: int,
) -> None:
    _write_ctp_simnow_config(tmp_path)
    config_path = tmp_path / "config.yaml"
    target = config_path if unsafe_target == "file" else tmp_path
    target.chmod(unsafe_mode)
    registry = _registry(tmp_path, presets=("sandbox",), secrets_refs=("config_yaml",))

    def unexpected_read(*args, **kwargs):
        raise AssertionError("private config bytes were read before the permission gate")

    monkeypatch.setattr(runtime_config.os, "read", unexpected_read)
    with pytest.raises(RuntimeConfigError) as caught:
        load_runtime_config(tmp_path, registry=registry)

    assert caught.value.reason in {
        "private_config_directory_unsafe",
        "private_config_file_unsafe",
    }
    assert "synthetic-password-never-use" not in repr(caught.value)


@pytest.mark.skipif(os.name != "posix", reason="POSIX private config hard-link gate")
def test_private_config_hard_link_is_rejected_before_read(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime"
    _write_ctp_simnow_config(runtime_dir)
    os.link(runtime_dir / "config.yaml", tmp_path / "unignored-copy.yaml")
    registry = _registry(runtime_dir, presets=("sandbox",), secrets_refs=("config_yaml",))

    with pytest.raises(RuntimeConfigError) as caught:
        load_runtime_config(runtime_dir, registry=registry)

    assert caught.value.reason == "private_config_hardlink_not_allowed"
    assert "synthetic-password-never-use" not in repr(caught.value)


@pytest.mark.skipif(os.name != "posix", reason="POSIX config permission race check")
@pytest.mark.parametrize("unsafe_target", ("file", "directory"))
def test_private_config_permission_change_during_read_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, unsafe_target: str
) -> None:
    _write_ctp_simnow_config(tmp_path)
    config_path = tmp_path / "config.yaml"
    target = config_path if unsafe_target == "file" else tmp_path
    unsafe_mode = 0o644 if unsafe_target == "file" else 0o755
    safe_mode = 0o600 if unsafe_target == "file" else 0o700
    registry = _registry(tmp_path, presets=("sandbox",), secrets_refs=("config_yaml",))
    read = os.read
    changed_permissions = False

    def chmod_after_chunk(descriptor: int, count: int) -> bytes:
        nonlocal changed_permissions
        chunk = read(descriptor, count)
        if chunk and not changed_permissions:
            changed_permissions = True
            target.chmod(unsafe_mode)
        return chunk

    monkeypatch.setattr(runtime_config.os, "read", chmod_after_chunk)
    try:
        with pytest.raises(RuntimeConfigError) as caught:
            load_runtime_config(tmp_path, registry=registry)
    finally:
        target.chmod(safe_mode)

    assert caught.value.reason in {
        "private_config_directory_unsafe",
        "private_config_file_unsafe",
    }
    assert "synthetic-password-never-use" not in repr(caught.value)


def test_private_ctp_doctor_and_errors_use_safe_projection_not_dataclass_asdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_ctp_simnow_config(tmp_path)
    registry = _registry(tmp_path, presets=("sandbox",), secrets_refs=("config_yaml",))

    def reject_generic_serialization(*args, **kwargs):
        raise AssertionError("runtime diagnostics must use explicit redacted projections")

    monkeypatch.setattr(dataclasses, "asdict", reject_generic_serialization)
    output = io.StringIO()
    error_output = io.StringIO()
    assert (
        main(
            ["doctor", "--strategy-dir", str(tmp_path)],
            registry=registry,
            environ={},
            stdout=output,
            stderr=error_output,
        )
        == 0
    )
    rendered = output.getvalue() + error_output.getvalue()
    for private_value in (
        "synthetic-password-never-use",
        "synthetic-account-001",
        "synthetic-auth-code",
        "9999",
    ):
        assert private_value not in rendered

    _write_ctp_simnow_config(
        tmp_path,
        ctp_mapping="{selection: unsupported, password: 'synthetic-password-never-use'}",
    )
    output = io.StringIO()
    error_output = io.StringIO()
    assert (
        main(
            ["doctor", "--strategy-dir", str(tmp_path)],
            registry=registry,
            environ={},
            stdout=output,
            stderr=error_output,
        )
        != 0
    )
    assert "synthetic-password-never-use" not in output.getvalue() + error_output.getvalue()


@pytest.mark.parametrize(
    "private_mapping",
    (
        "{selection: verified_session_auto, sentinel-password-token: x}",
        "{selection: verified_session_auto, sentinel-password-token: x, sentinel-password-token: y}",
    ),
)
def test_ctp_private_unknown_or_duplicate_keys_do_not_escape_in_errors(
    tmp_path: Path, private_mapping: str
) -> None:
    _write_ctp_simnow_config(tmp_path, ctp_mapping=private_mapping)
    registry = _registry(tmp_path, presets=("sandbox",), secrets_refs=("config_yaml",))

    with pytest.raises(RuntimeConfigError) as caught:
        load_runtime_config(tmp_path, registry=registry)

    assert caught.value.field_path == "ctp_simnow"
    assert "sentinel-password-token" not in str(caught.value)
    assert "sentinel-password-token" not in repr(caught.value)


@pytest.mark.parametrize(
    "updates,field_path,reason",
    (
        (
            {"mode": "live", "preset": "managed_live_direct"},
            "ctp_simnow",
            "ctp_simnow_scope_not_allowed",
        ),
        ({"preset": "replay"}, "ctp_simnow", "ctp_simnow_scope_not_allowed"),
        ({"secrets_ref": "runtime_secrets"}, "ctp_simnow", "ctp_simnow_secret_source_mismatch"),
        (
            {"mapping": _ctp_simnow_mapping() + "\nselection: verified_session_auto"},
            "ctp_simnow",
            "field_not_allowed",
        ),
        (
            {"mapping": _ctp_simnow_mapping() + "\nset1_profile: set1_group1"},
            "ctp_simnow",
            "field_not_allowed",
        ),
        (
            {"mapping": _ctp_simnow_mapping() + "\nset2_profile: set2_7x24"},
            "ctp_simnow",
            "field_not_allowed",
        ),
        (
            {"mapping": _ctp_simnow_mapping() + "\ncalendar_artifact: evidence/calendar.json"},
            "ctp_simnow",
            "field_not_allowed",
        ),
        (
            {
                "mapping": _ctp_simnow_mapping().replace(
                    "md_front: tcp://180.168.146.187:10211", "md_front: http://invalid:101"
                )
            },
            "ctp_simnow.md_front",
            "invalid_ctp_simnow_front",
        ),
        (
            {
                "mapping": _ctp_simnow_mapping().replace(
                    "td_front: tcp://180.168.146.187:10201", "td_front: '${CTP_TD_FRONT}'"
                )
            },
            "ctp_simnow.td_front",
            "environment_interpolation_not_allowed",
        ),
    ),
)
def test_private_ctp_config_rejects_out_of_scope_or_malformed_fields(
    tmp_path: Path, updates: dict, field_path: str, reason: str
) -> None:
    mode = updates.get("mode", "simulation")
    preset = updates.get("preset", "sandbox")
    secrets_ref = updates.get("secrets_ref", "config_yaml")
    mapping = updates.get("mapping")
    _write_ctp_simnow_config(
        tmp_path,
        mode=mode,
        preset=preset,
        secrets_ref=secrets_ref,
        ctp_mapping=mapping,
    )

    with pytest.raises(RuntimeConfigError) as caught:
        load_runtime_config(tmp_path)

    assert caught.value.field_path == field_path
    assert caught.value.reason == reason
    assert "synthetic-password" not in str(caught.value)


def test_private_ctp_config_requires_private_ref_and_parameters_still_reject_password(
    tmp_path: Path,
) -> None:
    _write_ctp_simnow_config(tmp_path, secrets_ref="none")
    with pytest.raises(RuntimeConfigError) as caught:
        load_runtime_config(tmp_path)
    assert caught.value.reason == "ctp_simnow_secret_source_mismatch"

    _write_config(
        tmp_path,
        mode="simulation",
        preset="sandbox",
        secrets_ref="config_yaml",
    )
    with pytest.raises(RuntimeConfigError) as caught:
        load_runtime_config(tmp_path)
    assert caught.value.reason == "ctp_simnow_secret_source_mismatch"

    _write_config(tmp_path, mode="simulation", preset="sandbox", parameters="{password: secret}")
    with pytest.raises(RuntimeConfigError) as caught:
        load_runtime_config(tmp_path)
    assert caught.value.reason == "inline_secret"


def test_capability_import_allowlist_cannot_be_supplied_by_config_parameters(
    tmp_path: Path,
) -> None:
    """External import roots remain a reviewed registration concern."""

    _write_config(tmp_path, parameters="{capability_modules: [bt_api_py]}")
    registry = _registry(tmp_path, parameter_keys=("capability_modules",))

    with pytest.raises(RuntimeConfigError) as caught:
        load_runtime_config(tmp_path, registry=registry)

    assert caught.value.code == CONFIG_SCHEMA_UNSUPPORTED
    assert caught.value.field_path == "parameters.capability_modules"
    assert caught.value.reason == "runtime_control_field_not_allowed"


@pytest.mark.parametrize(
    "parameters, field_path",
    (
        ("{nested: {AWS_ACCESS_KEY_ID: leaked}}", "parameters.nested.AWS_ACCESS_KEY_ID"),
        ("{nested: {aws-access-key-id: leaked}}", "parameters.nested.aws-access-key-id"),
        (
            "{nested: {Aws-Secret-Access-Key: leaked}}",
            "parameters.nested.Aws-Secret-Access-Key",
        ),
        (
            "{nested: [{AWS-SESSION-TOKEN: leaked}]}",
            "parameters.nested[0].AWS-SESSION-TOKEN",
        ),
    ),
)
def test_nested_aws_inline_credentials_are_rejected_for_case_and_hyphen_variants(
    tmp_path: Path, parameters: str, field_path: str
) -> None:
    _write_config(tmp_path, parameters=parameters)
    registry = _registry(tmp_path)

    with pytest.raises(RuntimeConfigError) as caught:
        load_runtime_config(tmp_path, registry=registry)

    assert caught.value.code == CONFIG_SCHEMA_UNSUPPORTED
    assert caught.value.field_path == field_path
    assert caught.value.reason == "inline_secret"


def test_config_loader_rejects_an_identity_change_after_descriptor_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The parser must fail closed if its FD differs from the checked path."""

    _write_config(tmp_path)
    registry = _registry(tmp_path)
    real_fstat = os.fstat

    def mismatched_fstat(descriptor):
        observed = real_fstat(descriptor)
        if stat.S_ISDIR(observed.st_mode):
            return observed
        values = list(observed)
        values[1] = observed.st_ino + 1
        return os.stat_result(values)

    monkeypatch.setattr(runtime_config.os, "fstat", mismatched_fstat)

    with pytest.raises(RuntimeConfigError) as caught:
        load_runtime_config(tmp_path, registry=registry)

    assert caught.value.code == PRESET_POLICY_VIOLATION
    assert caught.value.reason == "config_identity_changed"


def test_registered_parent_replacement_is_rejected_before_config_or_bootstrap(
    tmp_path: Path,
) -> None:
    """A canonical path must not silently authorise a replacement directory."""

    reviewed_parent = tmp_path / "reviewed-parent"
    runtime_dir = reviewed_parent / "runtime"
    _write_config(runtime_dir)
    registry = _registry(runtime_dir)

    reviewed_parent.rename(tmp_path / "old-reviewed-parent")
    replacement_runtime = reviewed_parent / "runtime"
    replacement_runtime.mkdir(parents=True)
    _write_config(replacement_runtime)

    with pytest.raises(RuntimeConfigError) as caught:
        load_runtime_config(runtime_dir, registry=registry)

    assert caught.value.code == PRESET_POLICY_VIOLATION
    assert caught.value.reason == "config_directory_identity_changed"

    with pytest.raises(RuntimeConfigError) as caught:
        bootstrap_runtime_config(runtime_dir, registry, "replay")

    assert caught.value.code == PRESET_POLICY_VIOLATION
    assert caught.value.reason == "config_directory_identity_changed"


def test_registered_directory_symlink_replacement_keeps_the_identity_error(
    tmp_path: Path,
) -> None:
    """Do not downgrade a registered-directory link swap to an unknown path."""

    runtime_dir = tmp_path / "reviewed-runtime"
    _write_config(runtime_dir)
    registry = _registry(runtime_dir)
    replacement = tmp_path / "replacement-runtime"
    _write_config(replacement)
    runtime_dir.rename(tmp_path / "old-reviewed-runtime")
    try:
        runtime_dir.symlink_to(replacement, target_is_directory=True)
    except OSError:
        pytest.skip("this platform does not permit test directory symlink creation")

    with pytest.raises(RuntimeConfigError) as caught:
        load_runtime_config(runtime_dir, registry=registry)

    assert caught.value.code == PRESET_POLICY_VIOLATION
    assert caught.value.reason == "config_directory_identity_changed"


@pytest.mark.skipif(os.name != "nt", reason="Windows directory lease coverage")
def test_windows_directory_lease_closes_if_the_post_acquire_identity_check_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed post-acquire check must not leave a delete-denying handle behind."""

    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    registry = _registry(runtime_dir)
    registration = registry.registrations[0]
    original_verify = registry.verify_runtime_dir_identity
    verify_calls = 0

    def fail_post_acquire(current_registration):
        nonlocal verify_calls
        verify_calls += 1
        if verify_calls == 2:
            raise registry._directory_identity_error()
        return original_verify(current_registration)

    monkeypatch.setattr(registry, "verify_runtime_dir_identity", fail_post_acquire)

    with pytest.raises(RuntimeConfigError) as caught, registry.verified_runtime_directory(
        registration
    ):
        pytest.fail("the forced post-acquire identity failure must run before the body")

    assert caught.value.reason == "config_directory_identity_changed"
    old_runtime = tmp_path / "runtime-before-failure"
    runtime_dir.rename(old_runtime)
    assert old_runtime.is_dir()


def test_config_loader_rejects_a_symlink_before_opening_target(tmp_path: Path) -> None:
    target = tmp_path / "target.yaml"
    target.write_text(
        _write_config(tmp_path / "source").read_text(encoding="utf-8"), encoding="utf-8"
    )
    config_path = tmp_path / "config.yaml"
    try:
        config_path.symlink_to(target)
    except OSError:
        pytest.skip("this platform does not permit test symlink creation")
    registry = _registry(tmp_path)

    with pytest.raises(RuntimeConfigError) as caught:
        load_runtime_config(tmp_path, registry=registry)

    assert caught.value.code == PRESET_POLICY_VIOLATION
    assert caught.value.reason == "config_symlink_not_allowed"


def test_config_loader_uses_no_follow_when_the_platform_exposes_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if not hasattr(runtime_config.os, "O_NOFOLLOW"):
        pytest.skip("O_NOFOLLOW is not exposed by this platform")
    _write_config(tmp_path)
    registry = _registry(tmp_path)
    observed_flags = []
    real_open = os.open

    def capture_open(path, flags, *args, **kwargs):
        observed_flags.append(flags)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(runtime_config.os, "open", capture_open)
    load_runtime_config(tmp_path, registry=registry)

    assert observed_flags
    assert observed_flags[0] & runtime_config.os.O_NOFOLLOW


def test_bootstrap_is_atomic_and_does_not_create_write_capable_contract(tmp_path: Path) -> None:
    registry = _registry(tmp_path, presets=("local_backtest", "managed_live_direct"))

    config = bootstrap_runtime_config(tmp_path, registry, "local_backtest")
    assert config.mode == "backtest"
    assert config.preset == "local_backtest"
    original = (tmp_path / "config.yaml").read_text(encoding="utf-8")

    with pytest.raises(RuntimeConfigError) as caught:
        bootstrap_runtime_config(tmp_path, registry, "local_backtest")
    assert caught.value.code == CONFIG_EXISTS
    assert (tmp_path / "config.yaml").read_text(encoding="utf-8") == original

    write_runtime = tmp_path / "write"
    write_registry = _registry(write_runtime, presets=("managed_live_direct",))
    with pytest.raises(RuntimeConfigError) as caught:
        bootstrap_runtime_config(write_runtime, write_registry, "managed_live_direct")
    assert caught.value.code == PRESET_POLICY_VIOLATION
    assert caught.value.reason == "bootstrap_write_capable_preset_not_allowed"
    assert not (write_runtime / "config.yaml").exists()


def test_cli_rejects_mode_override_and_environment_override(tmp_path: Path) -> None:
    _write_config(tmp_path)
    registry = _registry(tmp_path)
    stdout = io.StringIO()
    stderr = io.StringIO()

    status = main(
        ["run", "--strategy-dir", str(tmp_path), "--mode", "live"],
        registry=registry,
        stdout=stdout,
        stderr=stderr,
    )
    assert status == 2
    assert _read_json_line(stderr)["reason"] == "cli_override_not_allowed"

    stdout = io.StringIO()
    stderr = io.StringIO()
    status = main(
        ["validate", "--strategy-dir", str(tmp_path)],
        registry=registry,
        environ={"BT_RUNTIME_MODE": "live"},
        stdout=stdout,
        stderr=stderr,
    )
    assert status == 2
    payload = _read_json_line(stderr)
    assert payload["error_code"] == PRESET_POLICY_VIOLATION
    assert payload["reason"] == "environment_override_not_allowed"


def test_cli_bootstrap_validate_doctor_and_run_complete_offline(tmp_path: Path) -> None:
    """The normal operator sequence needs no mode flags or network access."""

    registry = _registry(tmp_path, presets=("replay",))
    stdout = io.StringIO()
    stderr = io.StringIO()

    status = main(
        ["bootstrap", "--strategy-dir", str(tmp_path), "--preset", "replay"],
        registry=registry,
        stdout=stdout,
        stderr=stderr,
    )
    assert status == 0
    bootstrap_payload = _read_json_line(stdout)
    assert bootstrap_payload["status"] == "bootstrapped"
    assert bootstrap_payload["mode"] == "simulation"
    assert bootstrap_payload["preset"] == "replay"
    assert stderr.getvalue() == ""

    for command, expected_status in (("validate", "valid"), ("doctor", "diagnostic")):
        stdout = io.StringIO()
        status = main(
            [command, "--strategy-dir", str(tmp_path)],
            registry=registry,
            stdout=stdout,
            stderr=io.StringIO(),
        )
        assert status == 0
        payload = _read_json_line(stdout)
        assert payload["status"] == expected_status
        assert payload["mode"] == "simulation"
        assert payload["preset"] == "replay"
        assert payload["allows_network"] is False
        assert payload["allows_external_writes"] is False

    stderr = io.StringIO()
    status = main(
        ["run", "--strategy-dir", str(tmp_path)],
        registry=registry,
        stdout=io.StringIO(),
        stderr=stderr,
    )
    assert status == 2
    assert _read_json_line(stderr)["reason"] == "runner_not_registered"


def test_doctor_explains_the_resolved_write_and_pnl_boundaries_without_preflight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_config(tmp_path)
    registry = _registry(tmp_path)
    stdout = io.StringIO()
    network_attempts = []

    import socket

    def reject_socket(*args, **kwargs):
        network_attempts.append((args, kwargs))
        raise AssertionError("doctor must not create a socket")

    monkeypatch.setattr(socket, "socket", reject_socket)

    status = main(
        ["doctor", "--strategy-dir", str(tmp_path)],
        registry=registry,
        stdout=stdout,
        stderr=io.StringIO(),
    )

    assert status == 0
    payload = _read_json_line(stdout)
    diagnostic = payload["diagnostic"]
    assert diagnostic["offline"] is True
    assert diagnostic["provider_preflight_started"] is False
    assert "operator_actions" not in diagnostic
    assert diagnostic["operator_summary"] == {
        "mode": "simulation",
        "preset": "replay",
        "destination": "local_runtime",
        "environment": "offline",
        "write_boundary": "zero_external_writes",
        "pnl_source": "not_applicable_without_external_fills",
        "required_capabilities": [],
        "requires_approval": False,
    }
    assert diagnostic["next_actions"][0]["command"] == [
        "bt-runtime",
        "run",
        "--strategy-dir",
        str(tmp_path),
    ]
    assert network_attempts == []


def test_doctor_missing_config_gives_only_a_safe_bootstrap_next_action(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    stderr = io.StringIO()

    status = main(
        ["doctor", "--strategy-dir", str(tmp_path)],
        registry=registry,
        stdout=io.StringIO(),
        stderr=stderr,
    )

    assert status == 2
    payload = _read_json_line(stderr)
    assert payload["error_code"] == CONFIG_REQUIRED
    assert payload["diagnostic"] == {
        "offline": True,
        "provider_preflight_started": False,
        "next_actions": [
            {
                "action": "bootstrap",
                "command": ["bt-runtime", "bootstrap", "--strategy-dir", str(tmp_path)],
                "note": "creates only the reviewed safe config; it never overwrites an existing file",
            }
        ],
    }


def test_cli_bootstrap_selects_the_safest_preset_registered_for_that_runtime(
    tmp_path: Path,
) -> None:
    registry = _registry(tmp_path, presets=("replay",))
    stdout = io.StringIO()

    status = main(
        ["bootstrap", "--strategy-dir", str(tmp_path)],
        registry=registry,
        stdout=stdout,
        stderr=io.StringIO(),
    )

    assert status == 0
    payload = _read_json_line(stdout)
    assert payload["mode"] == "simulation"
    assert payload["preset"] == "replay"


def test_cli_bootstrap_refuses_a_runtime_without_a_non_write_preset(tmp_path: Path) -> None:
    registry = _registry(tmp_path, presets=("managed_live_direct",), approved=True)
    stderr = io.StringIO()

    status = main(
        ["bootstrap", "--strategy-dir", str(tmp_path)],
        registry=registry,
        stdout=io.StringIO(),
        stderr=stderr,
    )

    assert status == 2
    assert _read_json_line(stderr)["reason"] == "bootstrap_safe_preset_unavailable"


def test_cli_uses_the_default_reviewed_inventory_without_a_registry_flag(
    tmp_path: Path, monkeypatch
) -> None:
    """The installed CLI selects the code-owned inventory, never user discovery."""

    registration = RegisteredRuntime(
        runtime_dir=tmp_path,
        strategy_id=ITERATION41_014_1_STRATEGY_ID,
        allowed_presets=("replay",),
        allowed_parameter_keys=("scenario",),
        runner_module="iteration41_default_inventory_runner",
    )
    monkeypatch.setattr(runtime_inventory, "ITERATION41_014_1_REGISTRATION", registration)
    import types

    runner = types.ModuleType("iteration41_default_inventory_runner")
    runner.run_runtime = lambda runtime_dir, *, registry, effective: {"status": "LOCAL_REPLAY_PASS"}
    monkeypatch.setitem(sys.modules, "iteration41_default_inventory_runner", runner)

    stdout = io.StringIO()
    status = main(
        ["bootstrap", "--strategy-dir", str(tmp_path), "--preset", "replay"],
        stdout=stdout,
        stderr=io.StringIO(),
    )
    assert status == 0
    assert _read_json_line(stdout)["strategy_id"] == ITERATION41_014_1_STRATEGY_ID

    stdout = io.StringIO()
    status = main(
        ["run", "--strategy-dir", str(tmp_path)],
        stdout=stdout,
        stderr=io.StringIO(),
    )
    assert status == 0
    payload = _read_json_line(stdout)
    assert payload["preset"] == "replay"
    assert payload["allows_network"] is False
    assert payload["status"] == "completed"
    assert payload["report"]["detail"] == "summary"
    assert payload["report"]["result"]["status"] == "LOCAL_REPLAY_PASS"


def test_live_cli_requires_confirmation_and_a_registered_runner(tmp_path: Path) -> None:
    _write_config(
        tmp_path, mode="live", preset="managed_live_direct", secrets_ref="runtime_secrets"
    )
    registry = _registry(
        tmp_path,
        presets=("managed_live_direct",),
        secrets_refs=("runtime_secrets",),
        capabilities=(CAPABILITY_EXECUTION, CAPABILITY_RISK, CAPABILITY_MONITOR),
        approved=True,
    )

    stderr = io.StringIO()
    status = main(
        ["run", "--strategy-dir", str(tmp_path)],
        registry=registry,
        stdout=io.StringIO(),
        stderr=stderr,
    )
    assert status == 2
    assert _read_json_line(stderr)["reason"] == "live_confirmation_required"

    stderr = io.StringIO()
    status = main(
        ["run", "--strategy-dir", str(tmp_path), "--confirm-live"],
        registry=registry,
        stdout=io.StringIO(),
        stderr=stderr,
    )
    assert status == 2
    assert _read_json_line(stderr)["reason"] == "runner_not_registered"
