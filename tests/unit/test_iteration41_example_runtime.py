"""Offline acceptance of the first schema-v4 example entrypoint.

These tests exercise the shared runtime loader and real local replay. They do
not certify managed execution, sandbox admission or live trading.
"""

from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys

import pytest
import yaml

from backtrader_runtime import (
    RegisteredRuntime,
    RuntimeConfigError,
    RuntimeRegistry,
    validate_runtime_config,
)

REPO = Path(__file__).resolve().parents[2]
EXAMPLE = REPO / "examples" / "014_1_ctp_options_lowfreq"


@pytest.fixture
def runner():
    return importlib.import_module("examples.014_1_ctp_options_lowfreq.run_runtime")


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    """Fail on attempted DNS, TCP or UDP operations, not just reported counts."""
    attempted = []

    def reject(*args, **kwargs):
        attempted.append(True)
        raise AssertionError("The Iteration 41 local replay must not access the network")

    monkeypatch.setattr(socket, "getaddrinfo", reject)
    monkeypatch.setattr(socket, "create_connection", reject)
    monkeypatch.setattr(socket.socket, "connect", reject)
    monkeypatch.setattr(socket.socket, "connect_ex", reject)
    monkeypatch.setattr(socket.socket, "sendto", reject)
    yield
    assert attempted == []


@pytest.fixture
def runtime(tmp_path, runner):
    directory = tmp_path / "runtime"
    directory.mkdir()
    raw = yaml.safe_load((EXAMPLE / "runtime" / "config.example.yaml").read_text(encoding="utf-8"))
    registry = RuntimeRegistry(
        (
            RegisteredRuntime(
                runtime_dir=directory,
                strategy_id=runner.STRATEGY_ID,
                allowed_presets=("replay",),
                allowed_parameter_keys=("scenario",),
            ),
        )
    )
    return directory, raw, registry


def _write_config(directory, raw):
    (directory / "config.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")


def _run_sealed(runner, directory, registry):
    """Invoke an example runner only with a loader-issued effective config."""

    effective = validate_runtime_config(directory, registry)
    return runner.run_runtime(directory, registry=registry, effective=effective)


@pytest.mark.parametrize(
    "scenario, decisions",
    [("eligible", 2), ("no_edge", 0), ("budget_reject", 0), ("misaligned", 0)],
)
def test_real_replay_uses_v4_config_without_external_clients(
    runner, runtime, monkeypatch, scenario, decisions
):
    from backtrader.stores.btapistore import BtApiStore

    def reject_store(*args, **kwargs):
        pytest.fail("Offline replay must not construct an external provider store")

    monkeypatch.setattr(BtApiStore, "__init__", reject_store)
    directory, raw, registry = runtime
    raw["parameters"]["scenario"] = scenario
    _write_config(directory, raw)
    report = _run_sealed(runner, directory, registry)

    assert report["status"] == "LOCAL_REPLAY_PASS"
    assert report["scenario"] == scenario
    assert report["ordinary_decisions"] == decisions
    assert report["external_request_counts"] == {"network": 0, "order_write": 0}
    assert report["timing_projection"]["confirmed_fill_quantity"] == 0
    assert "no CTP request" in report["evidence_boundary"]
    accepted = report["runtime_config"]
    assert accepted["mode"] == "simulation"
    assert accepted["preset"] == "replay"
    assert accepted["scope"] == "LOCAL_REPLAY_ONLY"
    assert accepted["config_digest"]
    assert not accepted["allows_network"]
    assert not accepted["allows_external_writes"]
    assert not accepted["allows_production_writes"]


def _forbid_strategy_import(monkeypatch, runner):
    def reject():
        pytest.fail("Rejected configuration must not load the strategy or adapter")

    monkeypatch.setattr(runner, "_load_replay_runner", reject)


def test_unsealed_example_runner_call_is_rejected_before_config_or_strategy_load(
    runner, runtime, monkeypatch
):
    """Public example runners may only consume a loader-issued effective config."""

    directory, _, registry = runtime
    _forbid_strategy_import(monkeypatch, runner)

    with pytest.raises(RuntimeConfigError) as failure:
        runner.run_runtime(directory, registry=registry)

    assert failure.value.code == "PRESET_POLICY_VIOLATION"
    assert failure.value.reason == "runner_dispatch_required"


def test_missing_runtime_config_cannot_fall_back_to_legacy_or_working_directory(
    runner, runtime, monkeypatch, tmp_path
):
    directory, raw, registry = runtime
    _write_config(tmp_path, raw)
    monkeypatch.chdir(tmp_path)
    _forbid_strategy_import(monkeypatch, runner)

    with pytest.raises(RuntimeConfigError) as failure:
        _run_sealed(runner, directory, registry)
    assert failure.value.code == "CONFIG_REQUIRED"


@pytest.mark.parametrize(
    "replacement",
    ["config_schema_version: 3\n", "config_schema_version: [\n", "{}\n"],
)
def test_invalid_or_old_schema_is_rejected_before_strategy(
    runner, runtime, monkeypatch, replacement
):
    directory, _, registry = runtime
    (directory / "config.yaml").write_text(replacement, encoding="utf-8")
    _forbid_strategy_import(monkeypatch, runner)

    with pytest.raises(RuntimeConfigError) as failure:
        _run_sealed(runner, directory, registry)
    assert failure.value.code == "CONFIG_SCHEMA_UNSUPPORTED"


@pytest.mark.parametrize(
    "mode,preset",
    [
        ("backtest", "local_backtest"),
        ("simulation", "paper"),
        ("simulation", "shadow"),
        ("simulation", "sandbox"),
        ("live", "managed_live_direct"),
        ("live", "managed_live_gateway"),
    ],
)
def test_other_valid_presets_are_not_silently_executed_as_replay(
    runner, runtime, monkeypatch, mode, preset
):
    directory, raw, registry = runtime
    raw["runtime"] = {"mode": mode, "preset": preset}
    _write_config(directory, raw)
    _forbid_strategy_import(monkeypatch, runner)

    with pytest.raises(RuntimeConfigError) as failure:
        _run_sealed(runner, directory, registry)
    assert failure.value.code == "PRESET_POLICY_VIOLATION"


def test_mode_preset_mismatch_is_rejected_before_strategy(runner, runtime, monkeypatch):
    directory, raw, registry = runtime
    raw["runtime"]["mode"] = "live"
    _write_config(directory, raw)
    _forbid_strategy_import(monkeypatch, runner)

    with pytest.raises(RuntimeConfigError) as failure:
        _run_sealed(runner, directory, registry)
    assert failure.value.code == "MODE_PRESET_MISMATCH"


def test_replay_rejects_provider_secret_references_before_strategy(runner, runtime, monkeypatch):
    directory, raw, registry = runtime
    raw["secrets_ref"] = "runtime_secrets"
    _write_config(directory, raw)
    _forbid_strategy_import(monkeypatch, runner)

    with pytest.raises(RuntimeConfigError) as failure:
        _run_sealed(runner, directory, registry)
    assert failure.value.code == "ENVIRONMENT_MISMATCH"
    assert failure.value.field_path == "secrets_ref"


@pytest.mark.parametrize("scenario", ["simnow", True, ["eligible"]])
def test_scenario_is_an_enum_and_cannot_select_a_live_path(runner, runtime, monkeypatch, scenario):
    directory, raw, registry = runtime
    raw["parameters"]["scenario"] = scenario
    _write_config(directory, raw)
    _forbid_strategy_import(monkeypatch, runner)

    with pytest.raises(RuntimeConfigError) as failure:
        _run_sealed(runner, directory, registry)
    assert failure.value.code == "CONFIG_SCHEMA_UNSUPPORTED"
    assert failure.value.field_path == "parameters.scenario"


@pytest.mark.parametrize("key", ["mode", "preset", "write_policy", "capital_limit"])
def test_unknown_parameters_cannot_change_mode_or_frozen_candidate_budget(
    runner, runtime, monkeypatch, key
):
    directory, raw, registry = runtime
    raw["parameters"][key] = "untrusted_override"
    _write_config(directory, raw)
    _forbid_strategy_import(monkeypatch, runner)

    with pytest.raises(RuntimeConfigError):
        _run_sealed(runner, directory, registry)


def test_explicit_unregistered_directory_is_not_automatically_trusted(runner, runtime, monkeypatch):
    directory, raw, _ = runtime
    _write_config(directory, raw)
    _forbid_strategy_import(monkeypatch, runner)

    with pytest.raises(RuntimeConfigError) as failure:
        validate_runtime_config(directory, runner.runtime_registry())
    assert failure.value.code == "PRESET_POLICY_VIOLATION"


@pytest.mark.parametrize(
    "strategy_id,mode,preset",
    [
        ("example.014_1.ctp_options_lowfreq", "backtest", "local_backtest"),
        ("another.strategy", "simulation", "replay"),
    ],
)
def test_runner_fence_also_applies_to_programmatic_registry_injection(
    runner, runtime, monkeypatch, strategy_id, mode, preset
):
    directory, raw, _ = runtime
    raw["strategy"]["id"] = strategy_id
    raw["runtime"] = {"mode": mode, "preset": preset}
    _write_config(directory, raw)
    registry = RuntimeRegistry(
        (
            RegisteredRuntime(
                runtime_dir=directory,
                strategy_id=strategy_id,
                allowed_presets=(preset,),
                allowed_parameter_keys=("scenario",),
            ),
        )
    )
    _forbid_strategy_import(monkeypatch, runner)

    with pytest.raises(RuntimeConfigError) as failure:
        _run_sealed(runner, directory, registry)
    assert failure.value.code == "PRESET_POLICY_VIOLATION"


def _copied_example(tmp_path, *, config):
    """Copy only public source/fixture files, never ignored credentials or logs."""
    example = tmp_path / "014_1_ctp_options_lowfreq"
    example.mkdir()
    for source in EXAMPLE.glob("*.py"):
        shutil.copy2(source, example / source.name)
    shutil.copy2(EXAMPLE / "config.yaml", example / "config.yaml")
    runtime = example / "runtime"
    runtime.mkdir()
    if config:
        shutil.copy2(EXAMPLE / "runtime" / "config.example.yaml", runtime / "config.yaml")
    return example


def _run_cli(example, *arguments, forbid_framework=False):
    # Guard the fresh interpreter as well as pytest: no DNS/TCP/UDP operation is
    # permitted, including during imports. run_path exercises direct-script imports.
    program = """
import runpy
import socket
import sys
import importlib.abc
from pathlib import Path
def reject(*args, **kwargs):
    raise AssertionError('offline subprocess attempted network access')
socket.getaddrinfo = reject
socket.create_connection = reject
socket.socket.connect = reject
socket.socket.connect_ex = reject
socket.socket.sendto = reject
class RejectFramework(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'backtrader', 'bt_api_py'}:
            raise AssertionError('rejected config attempted a framework/provider import')
if DENY_FRAMEWORK:
    sys.meta_path.insert(0, RejectFramework())
sys.argv = sys.argv[1:]
# Match the native interpreter's script-directory import path.
sys.path.insert(0, str(Path(sys.argv[0]).resolve().parent))
runpy.run_path(sys.argv[0], run_name='__main__')
"""
    program = program.replace("DENY_FRAMEWORK", repr(forbid_framework))
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO)
    return subprocess.run(
        [sys.executable, "-c", program, str(example / "run_runtime.py"), *arguments],
        cwd=example.parent,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )


def test_cli_unregistered_copy_is_rejected_before_legacy_or_framework_import(tmp_path):
    example = _copied_example(tmp_path, config=False)
    result = _run_cli(example, forbid_framework=True)

    assert result.returncode == 2, result.stderr
    report = json.loads(result.stdout)
    assert report["error"]["error_code"] == "PRESET_POLICY_VIOLATION"
    assert report["error"]["reason"] == "runtime_not_registered"
    assert report["external_request_counts"] == {"network": 0, "order_write": 0}


@pytest.mark.parametrize(
    "config_text", ["config_schema_version: 3\n", "config_schema_version: [\n"]
)
def test_cli_unregistered_copy_stays_rejected_even_with_invalid_config(tmp_path, config_text):
    example = _copied_example(tmp_path, config=False)
    (example / "runtime" / "config.yaml").write_text(config_text, encoding="utf-8")
    result = _run_cli(example, forbid_framework=True)

    assert result.returncode == 2, result.stderr
    report = json.loads(result.stdout)
    assert report["error"]["error_code"] == "PRESET_POLICY_VIOLATION"
    assert report["error"]["reason"] == "runtime_not_registered"
    assert report["external_request_counts"] == {"network": 0, "order_write": 0}


def test_cli_copied_example_is_not_trusted_even_with_a_valid_config(tmp_path):
    example = _copied_example(tmp_path, config=True)
    result = _run_cli(example, forbid_framework=True)

    assert result.returncode == 2, result.stderr
    report = json.loads(result.stdout)
    assert report["error"]["error_code"] == "PRESET_POLICY_VIOLATION"
    assert report["error"]["reason"] == "runtime_not_registered"
    assert report["external_request_counts"] == {"network": 0, "order_write": 0}


def test_cli_unregistered_copy_does_not_read_legacy_fixture(tmp_path):
    example = _copied_example(tmp_path, config=True)
    (example / "config.yaml").unlink()
    result = _run_cli(example, forbid_framework=True)

    assert result.returncode == 2, result.stderr
    report = json.loads(result.stdout)
    assert report["error"]["error_code"] == "PRESET_POLICY_VIOLATION"
    assert report["error"]["reason"] == "runtime_not_registered"
    assert report["external_request_counts"] == {"network": 0, "order_write": 0}


@pytest.mark.parametrize("flag", ["--mode", "--preset", "--config", "--scenario", "--registry"])
def test_cli_rejects_override_flags(tmp_path, flag):
    example = _copied_example(tmp_path, config=True)
    result = _run_cli(example, flag, "live", forbid_framework=True)

    assert result.returncode == 2
    assert "unrecognized arguments" in result.stderr
    assert "LOCAL_REPLAY_PASS" not in result.stdout
