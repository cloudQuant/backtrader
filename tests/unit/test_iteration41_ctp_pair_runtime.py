"""Offline acceptance coverage for the migrated 013 CTP pair examples.

The tests exercise only the schema-v4 wrapper and its synthetic replay. They
do not admit a SimNow, live, HFT, profitability, or real-trading path.
"""

from __future__ import annotations

from contextlib import contextmanager
import importlib
import importlib.abc
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
RUNTIMES = (
    {
        "directory": "013_1_midfreq_cross_arbitrage",
        "module": "examples.013_1_midfreq_cross_arbitrage.run_runtime",
        "strategy_id": "example.013_1.midfreq_cross_arbitrage",
        "hft": False,
    },
    {
        "directory": "013_2_highfreq_calendar_arbitrage",
        "module": "examples.013_2_highfreq_calendar_arbitrage.run_runtime",
        "strategy_id": "example.013_2.highfreq_calendar_arbitrage",
        "hft": True,
    },
)


@pytest.fixture(params=RUNTIMES, ids=lambda item: item["directory"])
def runtime_spec(request):
    return request.param


@pytest.fixture
def runner(runtime_spec):
    """Import only the safe wrapper; legacy runner imports remain delayed."""

    return importlib.import_module(runtime_spec["module"])


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    """Fail every attempted DNS/TCP/UDP operation, including during replay."""

    attempted = []

    def reject(*args, **kwargs):
        attempted.append(True)
        raise AssertionError("Iteration 41 replay must not access the network")

    monkeypatch.setattr(socket, "getaddrinfo", reject)
    monkeypatch.setattr(socket, "create_connection", reject)
    monkeypatch.setattr(socket.socket, "connect", reject)
    monkeypatch.setattr(socket.socket, "connect_ex", reject)
    monkeypatch.setattr(socket.socket, "sendto", reject)
    yield
    assert attempted == []


@pytest.fixture
def runtime(tmp_path, runner, runtime_spec):
    directory = tmp_path / "runtime"
    directory.mkdir()
    example = REPO / "examples" / runtime_spec["directory"]
    raw = yaml.safe_load((example / "runtime" / "config.example.yaml").read_text(encoding="utf-8"))
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


def _forbid_strategy_import(monkeypatch, runner):
    def reject():
        pytest.fail("rejected configuration must not load the strategy or adapter")

    monkeypatch.setattr(runner, "_load_replay_runner", reject)


@pytest.mark.parametrize(
    "content, expected_code",
    (
        (None, "CONFIG_REQUIRED"),
        ("config_schema_version: 3\n", "CONFIG_SCHEMA_UNSUPPORTED"),
        (
            """config_schema_version: 4
strategy:
  id: example.invalid
runtime:
  mode: live
  preset: replay
""",
            "MODE_PRESET_MISMATCH",
        ),
    ),
)
def test_missing_or_illegal_config_is_rejected_before_strategy_import(
    runner, runtime, monkeypatch, content, expected_code
):
    directory, _, registry = runtime
    if content is not None:
        (directory / "config.yaml").write_text(content, encoding="utf-8")
    _forbid_strategy_import(monkeypatch, runner)

    with pytest.raises(RuntimeConfigError) as failure:
        _run_sealed(runner, directory, registry)

    assert failure.value.code == expected_code


@pytest.mark.parametrize(
    "mode,preset",
    (("backtest", "local_backtest"), ("simulation", "paper"), ("live", "managed_live_direct")),
)
def test_nonreplay_modes_are_rejected_before_strategy_import(
    runner, runtime, monkeypatch, mode, preset
):
    directory, raw, registry = runtime
    raw["runtime"] = {"mode": mode, "preset": preset}
    _write_config(directory, raw)
    _forbid_strategy_import(monkeypatch, runner)

    with pytest.raises(RuntimeConfigError) as failure:
        _run_sealed(runner, directory, registry)

    assert failure.value.code == "PRESET_POLICY_VIOLATION"
    assert failure.value.reason == "preset_not_registered"


def test_ambient_provider_override_is_rejected_before_strategy_import(runner, runtime, monkeypatch):
    directory, raw, registry = runtime
    _write_config(directory, raw)
    monkeypatch.setenv("BT_STORE_PROVIDER", "ctp_gateway")
    _forbid_strategy_import(monkeypatch, runner)

    with pytest.raises(RuntimeConfigError) as failure:
        _run_sealed(runner, directory, registry)

    assert failure.value.code == "PRESET_POLICY_VIOLATION"
    assert failure.value.reason == "offline_provider_override_not_allowed"


@pytest.mark.parametrize("flag", ("--mode", "--preset", "--scenario", "--config"))
def test_cli_cannot_override_the_config_selected_runtime(runner, monkeypatch, flag):
    _forbid_strategy_import(monkeypatch, runner)

    with pytest.raises(SystemExit) as failure:
        runner.main((flag, "live"))

    assert failure.value.code == 2


@contextmanager
def _isolated_legacy_import(runner):
    """Avoid bare legacy ``strategy`` modules crossing between the two examples."""

    legacy_module = "{0}.run".format(runner.__package__)
    module_names = (legacy_module, "strategy", "ctp_example_support")
    saved_modules = {name: sys.modules.pop(name) for name in module_names if name in sys.modules}
    package = sys.modules[runner.__package__]
    sentinel = object()
    previous_run = getattr(package, "run", sentinel)
    if previous_run is not sentinel:
        delattr(package, "run")
    previous_path = list(sys.path)
    example_path = str(runner.HERE)
    sys.path[:] = [path for path in sys.path if path != example_path]
    try:
        yield
    finally:
        for name in module_names:
            sys.modules.pop(name, None)
        sys.modules.update(saved_modules)
        if previous_run is sentinel:
            package.__dict__.pop("run", None)
        else:
            setattr(package, "run", previous_run)
        sys.path[:] = previous_path


def test_real_replay_has_no_network_or_provider_write(runner, runtime, runtime_spec, monkeypatch):
    """Synthetic ticks may use the local Store feed but must never write a provider."""

    from backtrader.stores.btapistore import BtApiStore

    def reject_write(*args, **kwargs):
        pytest.fail("offline replay attempted a provider order write")

    for method_name in ("submit_order", "cancel_order", "cancel_order_ref"):
        monkeypatch.setattr(BtApiStore, method_name, reject_write)
    monkeypatch.delenv("BT_STORE_PROVIDER", raising=False)
    monkeypatch.setenv("TRADE_LOGGER_CONSOLE", "0")
    directory, raw, registry = runtime
    raw["parameters"]["scenario"] = "no_edge"
    _write_config(directory, raw)

    with _isolated_legacy_import(runner):
        report = _run_sealed(runner, directory, registry)

    assert report["scenario"] == "no_edge"
    assert report["external_request_counts"] == {"network": 0, "order_write": 0}
    assert report["admission_status"] == "LOCAL_REPLAY_ONLY"
    accepted = report["runtime_config"]
    assert accepted["mode"] == "simulation"
    assert accepted["preset"] == "replay"
    assert accepted["scope"] == "LOCAL_REPLAY_ONLY"
    assert accepted["config_digest"]
    assert not accepted["allows_network"]
    assert not accepted["allows_external_writes"]
    assert not accepted["allows_production_writes"]
    if runtime_spec["hft"]:
        assert report["hft_status"] == "FAIL/NOT_ADMITTED"
        assert "not HFT capability" in report["evidence_boundary"]


def _copied_runtime(tmp_path, runtime_spec):
    """Copy only the wrapper and explicit v4 fixture, never legacy credentials/logs."""

    source = REPO / "examples" / runtime_spec["directory"]
    copied = tmp_path / runtime_spec["directory"]
    copied.mkdir()
    shutil.copy2(source / "run_runtime.py", copied / "run_runtime.py")
    copied_runtime = copied / "runtime"
    copied_runtime.mkdir()
    shutil.copy2(source / "runtime" / "config.example.yaml", copied_runtime / "config.yaml")
    return copied


def _run_copied_cli(example):
    """Run a copy in a fresh process with framework imports and network blocked."""

    program = """
import importlib.abc
import runpy
import socket
import sys
from pathlib import Path
def reject(*args, **kwargs):
    raise AssertionError('copied runtime attempted network access')
socket.getaddrinfo = reject
socket.create_connection = reject
socket.socket.connect = reject
socket.socket.connect_ex = reject
socket.socket.sendto = reject
class RejectFramework(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'backtrader', 'bt_api_py'}:
            raise AssertionError('unregistered runtime attempted framework/provider import')
sys.meta_path.insert(0, RejectFramework())
sys.argv = sys.argv[1:]
sys.path.insert(0, str(Path(sys.argv[0]).resolve().parent))
runpy.run_path(sys.argv[0], run_name='__main__')
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(REPO)
    return subprocess.run(
        [sys.executable, "-c", program, str(example / "run_runtime.py")],
        cwd=example.parent,
        env=environment,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )


def test_copied_runtime_is_not_default_registry_trusted(tmp_path, runtime_spec):
    example = _copied_runtime(tmp_path, runtime_spec)
    result = _run_copied_cli(example)

    assert result.returncode == 2, result.stderr
    report = json.loads(result.stdout)
    assert report["error"]["error_code"] == "PRESET_POLICY_VIOLATION"
    assert report["error"]["reason"] == "runtime_not_registered"
    assert report["external_request_counts"] == {"network": 0, "order_write": 0}


def _copied_legacy_example(tmp_path, runtime_spec, config_text=None):
    """Copy only a legacy script and an optional isolated runtime config."""

    source = REPO / "examples" / runtime_spec["directory"]
    copied = tmp_path / runtime_spec["directory"]
    copied.mkdir()
    shutil.copy2(source / "run.py", copied / "run.py")
    runtime = copied / "runtime"
    runtime.mkdir()
    if config_text is not None:
        (runtime / "config.yaml").write_text(config_text, encoding="utf-8")
    return copied


def _run_legacy_cli(example, strategy_id, *arguments):
    """Execute a legacy script with its runtime registered and all I/O guarded.

    The subprocess patches the central registry to the copied runtime directory
    before running the script.  This proves a missing configuration or an
    unsupported write profile fails at the intended config-v4 boundary rather
    than merely because a copied directory is unregistered.
    """

    program = """
import importlib.abc
from pathlib import Path
import runpy
import socket
import sys
import backtrader_runtime.cli as runtime_cli
from backtrader_runtime import RegisteredRuntime, RuntimeRegistry

script = Path(sys.argv[1]).resolve()
strategy_id = sys.argv[2]
runtime_dir = script.parent / 'runtime'
registry = RuntimeRegistry((
    RegisteredRuntime(
        runtime_dir=runtime_dir,
        strategy_id=strategy_id,
        allowed_presets=('replay',),
        allowed_parameter_keys=('scenario',),
    ),
))
runtime_cli.default_runtime_registry = lambda: registry

def reject(*args, **kwargs):
    raise AssertionError('legacy CLI attempted network access')

socket.getaddrinfo = reject
socket.create_connection = reject
socket.socket.connect = reject
socket.socket.connect_ex = reject
socket.socket.sendto = reject

class RejectFramework(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'backtrader', 'bt_api_py'}:
            raise AssertionError('legacy CLI imported framework/provider before config fence')

sys.meta_path.insert(0, RejectFramework())
sys.argv = [str(script), *sys.argv[3:]]
sys.path.insert(0, str(script.parent))
runpy.run_path(script, run_name='__main__')
"""
    environment = os.environ.copy()
    for name in (
        "BT_RUNTIME_MODE",
        "BT_RUNTIME_PRESET",
        "BACKTRADER_RUNTIME_MODE",
        "BACKTRADER_RUNTIME_PRESET",
    ):
        environment.pop(name, None)
    environment["PYTHONPATH"] = str(REPO)
    return subprocess.run(
        [
            sys.executable,
            "-c",
            program,
            str(example / "run.py"),
            strategy_id,
            *arguments,
        ],
        cwd=example.parent,
        env=environment,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )


def test_legacy_default_requires_config_before_framework_or_network(runtime_spec, tmp_path):
    """A direct ``python run.py`` cannot fall through to the old SimNow branch."""

    example = _copied_legacy_example(tmp_path, runtime_spec)
    result = _run_legacy_cli(example, runtime_spec["strategy_id"])

    assert result.returncode == 2, result.stderr
    error = json.loads(result.stderr)
    assert error["error_code"] == "CONFIG_REQUIRED"
    assert error["reason"] == "missing_config"


@pytest.mark.parametrize(
    "legacy_arguments", (("--replay",), ("--config", "config.yaml"), ("--mode", "live"))
)
def test_legacy_cli_flags_are_rejected_before_config_or_framework(
    runtime_spec, tmp_path, legacy_arguments
):
    """Historical mode/config switches cannot revive direct SimNow execution."""

    example = _copied_legacy_example(tmp_path, runtime_spec)
    result = _run_legacy_cli(example, runtime_spec["strategy_id"], *legacy_arguments)

    assert result.returncode == 2, result.stderr
    error = json.loads(result.stderr)
    assert error["error_code"] == "PRESET_POLICY_VIOLATION"
    assert error["reason"] == "legacy_cli_arguments_not_supported"


def test_legacy_default_rejects_an_unsupported_live_profile_before_framework_or_network(
    runtime_spec, tmp_path
):
    """A valid v4 live pair cannot use this replay-only registration as an escape hatch."""

    config = (
        "config_schema_version: 4\n"
        "strategy:\n"
        "  id: {0}\n"
        "runtime:\n"
        "  mode: live\n"
        "  preset: managed_live_direct\n"
        "secrets_ref: runtime_secrets\n"
    ).format(runtime_spec["strategy_id"])
    example = _copied_legacy_example(tmp_path, runtime_spec, config)
    result = _run_legacy_cli(example, runtime_spec["strategy_id"])

    assert result.returncode == 2, result.stderr
    error = json.loads(result.stderr)
    assert error["error_code"] == "PRESET_POLICY_VIOLATION"
    assert error["reason"] == "preset_not_registered"


def test_programmatic_legacy_live_function_is_fail_closed(runner):
    """The retained function name must not construct the old direct client either."""

    with _isolated_legacy_import(runner):
        legacy = importlib.import_module(runner.__package__ + ".run")
        with pytest.raises(RuntimeConfigError) as failure:
            legacy.run_live()

    assert failure.value.code == "PRESET_POLICY_VIOLATION"
    assert failure.value.reason == "legacy_direct_live_not_supported"
