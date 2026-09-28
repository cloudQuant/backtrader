"""Offline-only Iteration 41 entrypoints preserve the frozen 012 candidates.

These exercise the real hash-bound formula replay, not a replacement strategy,
provider client or simulated admission. They do not certify native execution.
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
EXAMPLES = ("012_1_midfreq_cross_exchange", "012_2_event_driven_cross_exchange")


@pytest.fixture(params=EXAMPLES)
def runner(request):
    return importlib.import_module("examples." + request.param + ".run_runtime")


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    """Detect attempted DNS, TCP and UDP calls even if application code catches them."""
    attempted = []

    def reject(*args, **kwargs):
        attempted.append(True)
        raise AssertionError("The local replay attempted network access")

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
    raw = yaml.safe_load(
        (runner.HERE / "runtime" / "config.example.yaml").read_text(encoding="utf-8")
    )
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


@pytest.fixture
def legacy_runner(runner, monkeypatch):
    from tests.test_utils.optional_sdk import optional_sdk

    optional_sdk()
    legacy = importlib.import_module(runner.__package__ + ".run")

    def reject(*args, **kwargs):
        pytest.fail("A local formula replay must not construct a provider or enter admission")

    monkeypatch.setattr(legacy.BtApiStore, "__init__", reject)
    for name in ("build_store", "run_network", "require_demo_approval", "_load_demo_credentials"):
        monkeypatch.setattr(legacy, name, reject)
    return legacy


def _write_config(directory, raw):
    (directory / "config.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")


def _run_sealed(runner, directory, registry):
    """Invoke an example runner only with a loader-issued effective config."""

    effective = validate_runtime_config(directory, registry)
    return runner.run_runtime(directory, registry=registry, effective=effective)


def _forbid_strategy_import(monkeypatch, runner):
    def reject():
        pytest.fail("Rejected configuration attempted a strategy/provider import")

    monkeypatch.setattr(runner, "_load_replay_runner", reject)


@pytest.mark.parametrize("scenario", ["profitable", "loss", "no_edge", "partial", "unknown", "gap"])
def test_real_candidate_bound_replay_is_offline_and_has_no_execution_claim(
    runner, runtime, legacy_runner, scenario
):
    directory, raw, registry = runtime
    raw["parameters"]["scenario"] = scenario
    _write_config(directory, raw)
    report = _run_sealed(runner, directory, registry)

    assert report["status"] == "FORMULA_CHECK_PASS"
    assert report["scenario"] == scenario
    assert report["evidence_level"] == "R0_FORMULA_FIXTURE"
    assert report["research_status"] == "RESEARCH_REJECTED"
    assert report["execution_status"] == "NOT_RUN"
    assert report["profitability_claim"] == "NONE_SYNTHETIC_FIXTURE_ONLY"
    assert report["orders_submitted"] == report["fills"] == 0
    assert report["gross_pnl"] is report["net_pnl"] is None
    assert report["external_request_counts"] == {"network": 0, "order_write": 0}
    expected_state = "FORMULA_UNKNOWN_BRANCH" if scenario == "unknown" else "NO_EXECUTION"
    assert report["final_state"] == expected_state
    if scenario == "gap":
        assert report["reject_reasons"]["sequence_gap"] > 0
    accepted = report["runtime_config"]
    assert (accepted["mode"], accepted["preset"]) == ("simulation", "replay")
    assert accepted["scope"] == "LOCAL_REPLAY_ONLY"
    assert accepted["evidence_boundary"] == "R0_FORMULA_FIXTURE_ONLY_NOT_NATIVE_EXECUTION"
    assert len(accepted["config_digest"]) == 64
    assert accepted["strategy_id"] == runner.STRATEGY_ID
    assert not accepted["allows_network"]
    assert not accepted["allows_external_writes"]
    assert not accepted["allows_production_writes"]


def test_optional_scenario_defaults_to_no_edge(runner, runtime, legacy_runner):
    directory, raw, registry = runtime
    raw.pop("parameters")
    _write_config(directory, raw)
    assert _run_sealed(runner, directory, registry)["scenario"] == "no_edge"


def test_candidate_config_hash_cannot_be_bypassed(runner, runtime, legacy_runner, monkeypatch):
    directory, raw, registry = runtime
    _write_config(directory, raw)
    changed = directory / "changed-fixture.yaml"
    changed.write_bytes(legacy_runner.DEFAULT_CONFIG.read_bytes() + b"\n")
    monkeypatch.setattr(legacy_runner, "DEFAULT_CONFIG", changed)

    with pytest.raises(RuntimeConfigError) as failure:
        _run_sealed(runner, directory, registry)
    assert failure.value.code == "CONFIG_SCHEMA_UNSUPPORTED"
    assert failure.value.reason == "invalid_replay_fixture"
    assert "not bound" in str(failure.value.__cause__)


def test_missing_config_cannot_fall_back_to_legacy_or_cwd(runner, runtime, monkeypatch, tmp_path):
    directory, raw, registry = runtime
    _write_config(tmp_path, raw)
    monkeypatch.chdir(tmp_path)
    _forbid_strategy_import(monkeypatch, runner)
    with pytest.raises(RuntimeConfigError) as failure:
        _run_sealed(runner, directory, registry)
    assert failure.value.code == "CONFIG_REQUIRED"


@pytest.mark.parametrize("text", ["config_schema_version: 3\n", "config_schema_version: [\n"])
def test_old_or_invalid_config_fails_before_strategy(runner, runtime, monkeypatch, text):
    directory, _, registry = runtime
    (directory / "config.yaml").write_text(text, encoding="utf-8")
    _forbid_strategy_import(monkeypatch, runner)
    with pytest.raises(RuntimeConfigError) as failure:
        _run_sealed(runner, directory, registry)
    assert failure.value.code == "CONFIG_SCHEMA_UNSUPPORTED"


def test_mode_preset_mismatch_fails_before_strategy(runner, runtime, monkeypatch):
    directory, raw, registry = runtime
    raw["runtime"]["mode"] = "live"
    _write_config(directory, raw)
    _forbid_strategy_import(monkeypatch, runner)
    with pytest.raises(RuntimeConfigError) as failure:
        _run_sealed(runner, directory, registry)
    assert failure.value.code == "MODE_PRESET_MISMATCH"


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
def test_other_presets_are_rejected_not_silently_replayed(
    runner, runtime, monkeypatch, mode, preset
):
    directory, raw, registry = runtime
    raw["runtime"] = {"mode": mode, "preset": preset}
    _write_config(directory, raw)
    _forbid_strategy_import(monkeypatch, runner)
    with pytest.raises(RuntimeConfigError) as failure:
        _run_sealed(runner, directory, registry)
    assert failure.value.code == "PRESET_POLICY_VIOLATION"


@pytest.mark.parametrize("scenario", ["demo", True, ["no_edge"]])
def test_scenario_cannot_select_network_or_admission(runner, runtime, monkeypatch, scenario):
    directory, raw, registry = runtime
    raw["parameters"]["scenario"] = scenario
    _write_config(directory, raw)
    _forbid_strategy_import(monkeypatch, runner)
    with pytest.raises(RuntimeConfigError) as failure:
        _run_sealed(runner, directory, registry)
    assert failure.value.code == "CONFIG_SCHEMA_UNSUPPORTED"
    assert failure.value.field_path == "parameters.scenario"


@pytest.mark.parametrize(
    "key,error_code",
    [
        ("config_path", "PRESET_POLICY_VIOLATION"),
        ("manifest_path", "PRESET_POLICY_VIOLATION"),
        ("mode", "CONFIG_SCHEMA_UNSUPPORTED"),
        ("write_policy", "CONFIG_SCHEMA_UNSUPPORTED"),
    ],
)
def test_parameters_cannot_replace_candidate_inputs(runner, runtime, monkeypatch, key, error_code):
    directory, raw, registry = runtime
    raw["parameters"][key] = "untrusted"
    _write_config(directory, raw)
    _forbid_strategy_import(monkeypatch, runner)
    with pytest.raises(RuntimeConfigError) as failure:
        _run_sealed(runner, directory, registry)
    assert failure.value.code == error_code
    assert failure.value.field_path == "parameters." + key


def test_replay_rejects_secret_references_before_strategy(runner, runtime, monkeypatch):
    directory, raw, registry = runtime
    raw["secrets_ref"] = "runtime_secrets"
    _write_config(directory, raw)
    _forbid_strategy_import(monkeypatch, runner)
    with pytest.raises(RuntimeConfigError) as failure:
        _run_sealed(runner, directory, registry)
    assert failure.value.code == "ENVIRONMENT_MISMATCH"


def test_copied_runtime_is_not_automatically_registered(runner, runtime, monkeypatch):
    directory, raw, _ = runtime
    _write_config(directory, raw)
    _forbid_strategy_import(monkeypatch, runner)
    with pytest.raises(RuntimeConfigError) as failure:
        validate_runtime_config(directory, runner.runtime_registry())
    assert failure.value.code == "PRESET_POLICY_VIOLATION"
    assert failure.value.reason == "runtime_not_registered"


def test_entrypoint_rejects_a_different_strategy_even_with_trusted_registry(
    runner, runtime, monkeypatch
):
    directory, raw, _ = runtime
    raw["strategy"]["id"] = "another.strategy"
    _write_config(directory, raw)
    registry = RuntimeRegistry(
        (RegisteredRuntime(directory, "another.strategy", allowed_presets=("replay",)),)
    )
    # Reach the entrypoint's identity fence without an unrelated parameter error.
    raw.pop("parameters")
    _write_config(directory, raw)
    _forbid_strategy_import(monkeypatch, runner)
    with pytest.raises(RuntimeConfigError) as failure:
        _run_sealed(runner, directory, registry)
    assert failure.value.code == "PRESET_POLICY_VIOLATION"
    assert failure.value.reason == "strategy_not_bound"


def test_legacy_main_is_only_a_fixed_runtime_alias(runner, monkeypatch):
    from tests.test_utils.optional_sdk import optional_sdk

    optional_sdk()
    legacy = importlib.import_module(runner.__package__ + ".run")
    calls = []
    monkeypatch.setattr(
        legacy,
        "_run_legacy_config_first_cli",
        lambda runtime_dir, argv: calls.append((Path(runtime_dir), argv)) or 0,
    )

    assert legacy.main([]) == 0
    assert calls == [(legacy.HERE / "runtime", [])]


def test_imported_legacy_network_and_store_entrypoints_fail_before_local_inputs(
    runner, monkeypatch
):
    # Importing run.py still imports Backtrader and the SDK. This verifies the
    # function-call gate after that historical import-time behavior has occurred.
    from tests.test_utils.optional_sdk import optional_sdk

    optional_sdk()
    legacy = importlib.import_module(runner.__package__ + ".run")
    calls = []

    def record(*_args, **_kwargs):
        calls.append(True)
        raise AssertionError("a legacy entrypoint reached configuration or Store setup")

    monkeypatch.setattr(legacy, "load_config", record)
    monkeypatch.setattr(legacy, "_load_demo_credentials", record)
    monkeypatch.setattr(legacy, "_build_store_impl", record)
    for entrypoint, arguments in (
        (legacy.run_network, ("shadow", 60)),
        (legacy.run_network, ("demo", 60)),
        (legacy.build_store, ("shadow",)),
        (legacy.build_store, ("demo",)),
    ):
        with pytest.raises(RuntimeConfigError) as failure:
            entrypoint(*arguments)
        assert failure.value.code == "PRESET_POLICY_VIOLATION"
        assert getattr(failure.value, "reason", None) == "legacy_direct_execution_not_supported"
    assert calls == []


def _run_copied_cli(tmp_path, runner, *arguments, entrypoint="run_runtime.py"):
    """Copy public files only and forbid heavy imports in the fresh interpreter."""
    copied = tmp_path / runner.HERE.name
    copied.mkdir()
    shutil.copy2(runner.HERE / "run_runtime.py", copied / "run_runtime.py")
    shutil.copy2(runner.HERE / "run.py", copied / "run.py")
    runtime = copied / "runtime"
    runtime.mkdir()
    shutil.copy2(runner.HERE / "runtime" / "config.example.yaml", runtime / "config.yaml")
    program = """
import importlib.abc
from pathlib import Path
import runpy
import socket
import sys
def reject(*args, **kwargs):
    raise AssertionError('offline CLI attempted network access')
socket.getaddrinfo = reject
socket.create_connection = reject
socket.socket.connect = reject
socket.socket.connect_ex = reject
socket.socket.sendto = reject
class RejectFramework(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'backtrader', 'bt_api_py'}:
            raise AssertionError('rejected config imported the framework/provider')
sys.meta_path.insert(0, RejectFramework())
sys.argv = sys.argv[1:]
sys.path.insert(0, str(Path(sys.argv[0]).resolve().parent))
runpy.run_path(sys.argv[0], run_name='__main__')
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO)
    return subprocess.run(
        [sys.executable, "-c", program, str(copied / entrypoint), *arguments],
        cwd=copied.parent,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )


def test_copied_example_cli_stays_unregistered_before_framework_import(runner, tmp_path):
    result = _run_copied_cli(tmp_path, runner)
    assert result.returncode == 2, result.stderr
    report = json.loads(result.stdout)
    assert report["error"]["error_code"] == "PRESET_POLICY_VIOLATION"
    assert report["error"]["reason"] == "runtime_not_registered"
    assert report["external_request_counts"] == {"network": 0, "order_write": 0}


@pytest.mark.parametrize("mode", ["shadow", "demo", "live"])
def test_old_direct_cli_modes_reject_before_framework_or_provider_import(runner, tmp_path, mode):
    result = _run_copied_cli(tmp_path, runner, "--mode", mode, entrypoint="run.py")
    assert result.returncode == 2, result.stderr
    report = json.loads(result.stderr)
    assert report["error_code"] == "PRESET_POLICY_VIOLATION"
    assert report["reason"] == "legacy_cli_arguments_not_supported"
    assert result.stdout == ""


@pytest.mark.parametrize("flag", ["--mode", "--preset", "--config", "--scenario", "--registry"])
def test_cli_rejects_runtime_override_flags(runner, tmp_path, flag):
    result = _run_copied_cli(tmp_path, runner, flag, "live")
    assert result.returncode == 2, result.stderr
    assert "unrecognized arguments" in result.stderr
    assert "FORMULA_CHECK_PASS" not in result.stdout
