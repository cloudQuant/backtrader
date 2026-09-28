"""Offline acceptance tests for the Iteration 41 015 replay entrypoint.

The legacy example has a separate, bounded engineering-observation tool.  This
module covers only the new v4 runtime entrypoint and demonstrates that it
cannot use that tool, a provider, credentials, or a copied directory.
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
EXAMPLE = REPO / "examples" / "015_ctp_options_highfreq"


@pytest.fixture
def runner():
    return importlib.import_module("examples.015_ctp_options_highfreq.run_runtime")


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    """Fail on DNS, TCP, or UDP use rather than trusting report counters."""

    attempted = []

    def reject(*args, **kwargs):
        attempted.append(True)
        raise AssertionError("The Iteration 41 local replay must not access the network")

    for name in ("BT_STORE_PROVIDER", "ITER30_SIMNOW_PROFILE"):
        monkeypatch.delenv(name, raising=False)
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


@pytest.fixture
def legacy_runner(runner, monkeypatch):
    """Make external provider construction a test failure, not a report claim."""

    legacy = importlib.import_module(runner.__package__ + ".run")

    def reject_store(*args, **kwargs):
        pytest.fail("A local HFT replay must not construct a provider store")

    monkeypatch.setattr(legacy.BtApiStore, "__init__", reject_store)
    return legacy


def _write_config(directory, raw):
    (directory / "config.yaml").write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")


def _run_sealed(runner, directory, registry):
    """Invoke an example runner only with a loader-issued effective config."""

    effective = validate_runtime_config(directory, registry)
    return runner.run_runtime(directory, registry=registry, effective=effective)


def _forbid_strategy_import(monkeypatch, runner):
    def reject():
        pytest.fail("Rejected configuration attempted to import the legacy runner")

    monkeypatch.setattr(runner, "_load_replay_runner", reject)


@pytest.mark.parametrize(
    ("scenario", "ordinary_intents"),
    (("valid_cohort", 1), ("insufficient_cohort", 0), ("bar_only", 0)),
)
def test_real_replay_is_local_only_and_never_constructs_a_provider(
    runner, runtime, legacy_runner, scenario, ordinary_intents
):
    directory, raw, registry = runtime
    raw["parameters"]["scenario"] = scenario
    _write_config(directory, raw)

    report = _run_sealed(runner, directory, registry)

    assert report["status"] == "LOCAL_REPLAY_PASS"
    assert report["scenario"] == scenario
    assert report["ordinary_intent_count"] == ordinary_intents
    assert report["external_network_requests"] == 0
    assert report["external_write_requests"] == 0
    assert report["external_request_counts"] == {"network": 0, "order_write": 0}
    assert report["simulated_broker_orders"] == report["actual_fills"] == 0
    assert report["hft_status"] == "NOT_ADMITTED"
    assert report["admission_status"] == "LOCAL_REPLAY_ONLY"
    assert "not HFT capability" in report["evidence_boundary"]

    accepted = report["runtime_config"]
    assert accepted["strategy_id"] == runner.STRATEGY_ID
    assert (accepted["mode"], accepted["preset"]) == ("simulation", "replay")
    assert accepted["scope"] == "LOCAL_REPLAY_ONLY"
    assert len(accepted["config_digest"]) == 64
    assert not accepted["allows_network"]
    assert not accepted["allows_external_writes"]
    assert not accepted["allows_production_writes"]


def test_missing_runtime_config_cannot_fall_back_to_legacy_or_cwd(
    runner, runtime, monkeypatch, tmp_path
):
    directory, raw, registry = runtime
    _write_config(tmp_path, raw)
    monkeypatch.chdir(tmp_path)
    _forbid_strategy_import(monkeypatch, runner)

    with pytest.raises(RuntimeConfigError) as failure:
        _run_sealed(runner, directory, registry)
    assert failure.value.code == "CONFIG_REQUIRED"


def test_imported_simnow_launcher_main_uses_the_configured_replay_route():
    """Importing and calling the historical launcher cannot create a CTP client."""

    program = r"""
import importlib.abc
import importlib
import socket
import sys

class RejectProviderImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'bt_api_py', 'bt_api_ctp', 'ctpbeebt'}:
            raise AssertionError('the retired launcher imported a CTP provider')

def reject(*args, **kwargs):
    raise AssertionError('the Iteration 41 launcher attempted network I/O')

socket.getaddrinfo = reject
socket.create_connection = reject
socket.socket.connect = reject
socket.socket.connect_ex = reject
socket.socket.sendto = reject
sys.meta_path.insert(0, RejectProviderImports())
simnow_launcher = importlib.import_module('examples.015_ctp_options_highfreq.simnow_launcher')
from backtrader_runtime import RuntimeConfigError

def reject_store(*args, **kwargs):
    raise AssertionError('retired session helper constructed a Store')

simnow_launcher.run.BtApiStore.__init__ = reject_store
try:
    simnow_launcher.wait_ctp_session_ready(object())
except RuntimeConfigError as exc:
    assert exc.reason == 'legacy_direct_execution_not_supported'
else:
    raise AssertionError('default session wait unexpectedly accepted an unconfigured API')
print('wait_status=blocked')
print('main_status=' + str(simnow_launcher.main()))
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(REPO)
    result = subprocess.run(
        [sys.executable, "-c", program],
        cwd=REPO,
        env=environment,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "wait_status=blocked" in result.stdout
    assert "main_status=0" in result.stdout or "main_status=2" in result.stdout


def test_simnow_session_wait_is_fake_only_and_never_starts_lazy_connect():
    launcher = importlib.import_module("examples.015_ctp_options_highfreq.simnow_launcher")

    class Feed:
        def get_query_session_scope(self):
            pytest.fail("session wait must not trigger lazy CTP connection")

    class FakeApi:
        __backtrader_test_double__ = True
        exchange_feeds = {launcher.CTP_EXCHANGE: Feed()}

        @staticmethod
        def get_ctp_session_state(*, exchange_name):
            assert exchange_name == launcher.CTP_EXCHANGE
            return {"account_fingerprint": "offline-fake", "read_only_ready": True}

    fake = FakeApi()
    with pytest.raises(RuntimeConfigError) as failure:
        launcher.wait_ctp_session_ready(fake)
    assert failure.value.reason == "legacy_direct_execution_not_supported"

    observed = launcher.wait_ctp_session_ready(
        fake,
        _test_only_injection=launcher._SESSION_WAIT_TEST_TOKEN,
    )
    assert observed["account_fingerprint"] == "offline-fake"
    assert observed["read_only_ready"] is True


@pytest.mark.parametrize("text", ("config_schema_version: 3\n", "config_schema_version: [\n"))
def test_old_or_invalid_v4_config_fails_before_legacy_import(runner, runtime, monkeypatch, text):
    directory, _, registry = runtime
    (directory / "config.yaml").write_text(text, encoding="utf-8")
    _forbid_strategy_import(monkeypatch, runner)

    with pytest.raises(RuntimeConfigError) as failure:
        _run_sealed(runner, directory, registry)
    assert failure.value.code == "CONFIG_SCHEMA_UNSUPPORTED"


@pytest.mark.parametrize(
    ("mode", "preset"),
    (
        ("backtest", "local_backtest"),
        ("simulation", "paper"),
        ("simulation", "shadow"),
        ("simulation", "sandbox"),
        ("live", "managed_live_direct"),
        ("live", "managed_live_gateway"),
    ),
)
def test_other_modes_and_presets_are_rejected_before_legacy_import(
    runner, runtime, monkeypatch, mode, preset
):
    directory, raw, registry = runtime
    raw["runtime"] = {"mode": mode, "preset": preset}
    _write_config(directory, raw)
    _forbid_strategy_import(monkeypatch, runner)

    with pytest.raises(RuntimeConfigError) as failure:
        _run_sealed(runner, directory, registry)
    assert failure.value.code == "PRESET_POLICY_VIOLATION"


def test_mode_preset_mismatch_is_rejected_before_legacy_import(runner, runtime, monkeypatch):
    directory, raw, registry = runtime
    raw["runtime"]["mode"] = "live"
    _write_config(directory, raw)
    _forbid_strategy_import(monkeypatch, runner)

    with pytest.raises(RuntimeConfigError) as failure:
        _run_sealed(runner, directory, registry)
    assert failure.value.code == "MODE_PRESET_MISMATCH"


@pytest.mark.parametrize("scenario", ("simnow", True, ["valid_cohort"]))
def test_scenario_cannot_select_an_engineering_or_live_path(runner, runtime, monkeypatch, scenario):
    directory, raw, registry = runtime
    raw["parameters"]["scenario"] = scenario
    _write_config(directory, raw)
    _forbid_strategy_import(monkeypatch, runner)

    with pytest.raises(RuntimeConfigError) as failure:
        _run_sealed(runner, directory, registry)
    assert failure.value.code == "CONFIG_SCHEMA_UNSUPPORTED"
    assert failure.value.field_path == "parameters.scenario"


@pytest.mark.parametrize(
    ("key", "error_code"),
    (
        ("mode", "CONFIG_SCHEMA_UNSUPPORTED"),
        ("fixture", "PRESET_POLICY_VIOLATION"),
        ("provider", "CONFIG_SCHEMA_UNSUPPORTED"),
        ("approval_receipt", "PRESET_POLICY_VIOLATION"),
    ),
)
def test_runtime_parameters_cannot_replace_candidate_or_provider_inputs(
    runner, runtime, monkeypatch, key, error_code
):
    directory, raw, registry = runtime
    raw["parameters"][key] = "untrusted"
    _write_config(directory, raw)
    _forbid_strategy_import(monkeypatch, runner)

    with pytest.raises(RuntimeConfigError) as failure:
        _run_sealed(runner, directory, registry)
    assert failure.value.code == error_code
    assert failure.value.field_path == "parameters." + key


def test_secret_reference_is_rejected_before_legacy_import(runner, runtime, monkeypatch):
    directory, raw, registry = runtime
    raw["secrets_ref"] = "runtime_secrets"
    _write_config(directory, raw)
    _forbid_strategy_import(monkeypatch, runner)

    with pytest.raises(RuntimeConfigError) as failure:
        _run_sealed(runner, directory, registry)
    assert failure.value.code == "ENVIRONMENT_MISMATCH"
    assert failure.value.field_path == "secrets_ref"


@pytest.mark.parametrize("name", ("BT_STORE_PROVIDER", "ITER30_SIMNOW_PROFILE"))
def test_ambient_provider_or_simnow_override_is_rejected_before_legacy_import(
    runner, runtime, monkeypatch, name
):
    directory, raw, registry = runtime
    _write_config(directory, raw)
    monkeypatch.setenv(name, "untrusted")
    _forbid_strategy_import(monkeypatch, runner)

    with pytest.raises(RuntimeConfigError) as failure:
        _run_sealed(runner, directory, registry)
    assert failure.value.code == "PRESET_POLICY_VIOLATION"
    assert failure.value.reason == "offline_environment_override_not_allowed"


def test_copied_runtime_directory_is_not_automatically_registered(runner, runtime, monkeypatch):
    directory, raw, _ = runtime
    _write_config(directory, raw)
    _forbid_strategy_import(monkeypatch, runner)

    with pytest.raises(RuntimeConfigError) as failure:
        validate_runtime_config(directory, runner.runtime_registry())
    assert failure.value.code == "PRESET_POLICY_VIOLATION"
    assert failure.value.reason == "runtime_not_registered"


def test_entrypoint_rejects_a_different_strategy_even_with_a_trusted_registry(
    runner, runtime, monkeypatch
):
    directory, raw, _ = runtime
    raw["strategy"]["id"] = "another.strategy"
    raw.pop("parameters")
    _write_config(directory, raw)
    registry = RuntimeRegistry(
        (RegisteredRuntime(directory, "another.strategy", allowed_presets=("replay",)),)
    )
    _forbid_strategy_import(monkeypatch, runner)

    with pytest.raises(RuntimeConfigError) as failure:
        _run_sealed(runner, directory, registry)
    assert failure.value.code == "PRESET_POLICY_VIOLATION"
    assert failure.value.reason == "strategy_not_bound"


def _run_copied_cli(tmp_path, runner, *arguments):
    """Copy only public v4 files and prove rejection precedes framework imports."""

    copied = tmp_path / runner.HERE.name
    copied.mkdir()
    shutil.copy2(runner.HERE / "run_runtime.py", copied / "run_runtime.py")
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
        [sys.executable, "-c", program, str(copied / "run_runtime.py"), *arguments],
        cwd=copied.parent,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )


def test_copied_example_cli_rejects_before_framework_import(runner, tmp_path):
    result = _run_copied_cli(tmp_path, runner)
    assert result.returncode == 2, result.stderr
    report = json.loads(result.stdout)
    assert report["error"]["error_code"] == "PRESET_POLICY_VIOLATION"
    assert report["error"]["reason"] == "runtime_not_registered"
    assert report["external_request_counts"] == {"network": 0, "order_write": 0}


@pytest.mark.parametrize("flag", ("--mode", "--preset", "--config", "--scenario", "--registry"))
def test_cli_rejects_runtime_override_flags(runner, tmp_path, flag):
    result = _run_copied_cli(tmp_path, runner, flag, "live")
    assert result.returncode == 2, result.stderr
    assert "unrecognized arguments" in result.stderr
    assert "LOCAL_REPLAY_PASS" not in result.stdout


def test_runtime_gitignore_ignores_only_private_config_template_is_trackable():
    runtime_ignore = (EXAMPLE / "runtime" / ".gitignore").read_text(encoding="utf-8")
    example_ignore = (EXAMPLE / ".gitignore").read_text(encoding="utf-8")
    assert "/config.yaml" in runtime_ignore
    assert "/runtime/config.yaml" in example_ignore
    assert "!/runtime/config.example.yaml" in example_ignore
