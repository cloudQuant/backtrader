"""P0-G regression coverage for the retired direct examples/sample.py path.

The registered profile is a schema-v4, no-action migration report. It neither
restores CTP connectivity nor presents a fake execution path as managed.
"""

from __future__ import annotations

import ast
import importlib
import importlib.abc
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
from types import SimpleNamespace
from typing import Any, Dict, Tuple

import pytest
import yaml

from backtrader_runtime import (
    RegisteredRuntime,
    RuntimeConfigError,
    RuntimeRegistry,
    validate_runtime_config,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SAMPLE_PATH = REPOSITORY_ROOT / "examples" / "sample.py"
SAMPLE_RUNTIME_TEMPLATE = (
    REPOSITORY_ROOT / "examples" / "sample" / "runtime" / "config.example.yaml"
)


@pytest.fixture
def runner():
    return importlib.import_module("examples.sample")


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    attempted = []

    def reject(*args, **kwargs):
        attempted.append((args, kwargs))
        raise AssertionError("P0-G no-action migration attempted network I/O")

    monkeypatch.setattr(socket, "getaddrinfo", reject)
    monkeypatch.setattr(socket, "create_connection", reject)
    monkeypatch.setattr(socket.socket, "connect", reject)
    monkeypatch.setattr(socket.socket, "connect_ex", reject)
    monkeypatch.setattr(socket.socket, "sendto", reject)
    yield
    assert attempted == []


@pytest.fixture
def runtime(tmp_path: Path, runner) -> Tuple[Path, Dict[str, Any], RuntimeRegistry]:
    directory = tmp_path / "sample-runtime"
    directory.mkdir()
    raw = yaml.safe_load(SAMPLE_RUNTIME_TEMPLATE.read_text(encoding="utf-8"))
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


def _write_config(directory: Path, raw: Dict[str, Any]) -> None:
    (directory / "config.yaml").write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")


def _run_sealed(runner, directory, registry):
    """Invoke an example runner only with a loader-issued effective config."""

    effective = validate_runtime_config(directory, registry)
    return runner.run_runtime(directory, registry=registry, effective=effective)


@pytest.mark.parametrize(
    "content, expected_code",
    (
        (None, "CONFIG_REQUIRED"),
        ("config_schema_version: 3\n", "CONFIG_SCHEMA_UNSUPPORTED"),
        (
            """config_schema_version: 4
strategy:
  id: example.sample.ctp_legacy
runtime:
  mode: live
  preset: replay
""",
            "MODE_PRESET_MISMATCH",
        ),
    ),
)
def test_missing_or_invalid_config_rejects_before_profile_execution(
    runner, runtime, monkeypatch, content, expected_code
):
    directory, _, registry = runtime
    if content is not None:
        (directory / "config.yaml").write_text(content, encoding="utf-8")

    monkeypatch.setattr(
        runner,
        "_validate_sample_profile",
        lambda *args, **kwargs: pytest.fail("invalid config reached the sample profile"),
    )
    with pytest.raises(RuntimeConfigError) as failure:
        _run_sealed(runner, directory, registry)

    assert failure.value.code == expected_code


@pytest.mark.parametrize(
    "mode,preset",
    (
        ("backtest", "local_backtest"),
        ("simulation", "paper"),
        ("live", "managed_live_direct"),
    ),
)
def test_nonreplay_contracts_are_rejected_before_the_no_action_profile(
    runner, runtime, monkeypatch, mode, preset
):
    directory, raw, registry = runtime
    raw["runtime"] = {"mode": mode, "preset": preset}
    _write_config(directory, raw)
    monkeypatch.setattr(
        runner,
        "_validate_sample_profile",
        lambda *args, **kwargs: pytest.fail("unsupported contract reached the sample profile"),
    )
    with pytest.raises(RuntimeConfigError) as failure:
        _run_sealed(runner, directory, registry)

    assert failure.value.code == "PRESET_POLICY_VIOLATION"
    assert failure.value.reason == "preset_not_registered"


def test_valid_profile_does_not_read_legacy_params_or_touch_a_provider(
    runner, runtime, monkeypatch
):
    directory, raw, registry = runtime
    _write_config(directory, raw)
    (directory / runner.LEGACY_PARAMS_FILENAME).write_text("not valid json", encoding="utf-8")

    original_open = Path.open

    def guarded_open(path: Path, *args, **kwargs):
        if path.name == runner.LEGACY_PARAMS_FILENAME:
            pytest.fail("Iteration 41 migration read legacy params_01.json")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    report = _run_sealed(runner, directory, registry)

    assert report["status"] == "LOCAL_REPLAY_PASS"
    assert report["admission_status"] == "LOCAL_REPLAY_ONLY"
    assert report["scenario"] == "no_action"
    assert report["external_request_counts"] == {"network": 0, "order_write": 0}
    assert report["legacy_direct_execution"] == "NOT_SUPPORTED"
    assert report["legacy_parameter_source"] == {
        "path": "params_01.json",
        "status": "IGNORED_BY_ITERATION41_RUNTIME",
    }
    assert report["runtime_config"]["mode"] == "simulation"
    assert report["runtime_config"]["preset"] == "replay"
    assert report["runtime_config"]["scope"] == "LOCAL_REPLAY_ONLY"
    assert not report["runtime_config"]["allows_network"]
    assert not report["runtime_config"]["allows_external_writes"]
    assert not report["runtime_config"]["allows_production_writes"]


def test_legacy_action_names_do_not_dereference_a_fake_beeapi_action(runner):
    class FakeAction:
        def __init__(self) -> None:
            self.lookups = []

        def __getattr__(self, name: str):
            self.lookups.append(name)
            pytest.fail("disabled legacy action dereferenced fake provider action")

    fake_action = FakeAction()
    strategy = runner.SmaCross()
    strategy.beeapi = SimpleNamespace(action=fake_action)

    for method_name, expected_action in (
        ("open_long", "buy"),
        ("open_short", "short"),
        ("close_long", "cover"),
        ("close_short", "sell"),
    ):
        with pytest.raises(runner.LegacyDirectExecutionDisabled) as failure:
            getattr(strategy, method_name)(1, 1, object())
        assert failure.value.action == expected_action

    assert fake_action.lookups == []


@pytest.mark.parametrize("flag", ("--mode", "--preset", "--config", "--params"))
def test_legacy_cli_flags_cannot_override_the_required_config(runner, monkeypatch, flag):
    monkeypatch.setattr(
        runner,
        "run_runtime",
        lambda *args, **kwargs: pytest.fail("legacy CLI flag reached runtime execution"),
    )
    with pytest.raises(SystemExit) as failure:
        runner.main((flag, "live"))

    assert failure.value.code == 2


def test_source_has_no_ctp_import_or_direct_action_attribute() -> None:
    tree = ast.parse(SAMPLE_PATH.read_text(encoding="utf-8"), filename=str(SAMPLE_PATH))
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module.split(".")[0])

    assert "ctpbeebt" not in imported
    assert not [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and node.attr == "action"
        and isinstance(node.ctx, ast.Load)
    ]


def _run_fresh_no_action_subprocess() -> subprocess.CompletedProcess[str]:
    program = """
import importlib.abc
import json
import socket
import sys
import tempfile
from pathlib import Path

class RejectTradingImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'backtrader', 'ctpbeebt'}:
            raise AssertionError('sample migration imported a trading dependency')

def reject(*args, **kwargs):
    raise AssertionError('sample migration attempted network I/O')

sys.meta_path.insert(0, RejectTradingImports())
socket.getaddrinfo = reject
socket.create_connection = reject
socket.socket.connect = reject
socket.socket.connect_ex = reject
socket.socket.sendto = reject

from backtrader_runtime import (
    RegisteredRuntime,
    RuntimeRegistry,
    load_runtime_config,
    resolve_runtime_config,
)
from backtrader_runtime.runner import dispatch_registered_runtime

with tempfile.TemporaryDirectory() as temporary:
    runtime_dir = Path(temporary) / 'runtime'
    runtime_dir.mkdir()
    (runtime_dir / 'config.yaml').write_text(
        'config_schema_version: 4\\n'
        'strategy:\\n'
        '  id: example.sample.ctp_legacy\\n'
        'runtime:\\n'
        '  mode: simulation\\n'
        '  preset: replay\\n'
        'parameters:\\n'
        '  scenario: no_action\\n',
        encoding='utf-8',
    )
    registry = RuntimeRegistry((RegisteredRuntime(
        runtime_dir=runtime_dir,
        strategy_id='example.sample.ctp_legacy',
        allowed_presets=('replay',),
        allowed_parameter_keys=('scenario',),
        runner_module='examples.sample',
    ),))
    effective = resolve_runtime_config(load_runtime_config(runtime_dir, registry=registry), registry)
    print(json.dumps(dispatch_registered_runtime(effective, registry), sort_keys=True))
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(REPOSITORY_ROOT)
    return subprocess.run(
        [sys.executable, "-c", program],
        cwd=REPOSITORY_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )


def test_fresh_process_valid_profile_has_no_framework_ctp_or_network_import() -> None:
    result = _run_fresh_no_action_subprocess()

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["admission_status"] == "LOCAL_REPLAY_ONLY"
    assert report["external_request_counts"] == {"network": 0, "order_write": 0}


def _run_copied_cli(example: Path) -> subprocess.CompletedProcess[str]:
    program = """
import builtins
import importlib.abc
import runpy
import socket
import sys

def reject(*args, **kwargs):
    raise AssertionError('copied sample migration attempted network I/O')

native_open = builtins.open
def guarded_open(file, *args, **kwargs):
    if str(file).endswith('params_01.json'):
        raise AssertionError('copied sample migration read legacy params')
    return native_open(file, *args, **kwargs)

class RejectTradingImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'backtrader', 'ctpbeebt'}:
            raise AssertionError('copied sample migration imported a trading dependency')

builtins.open = guarded_open
socket.getaddrinfo = reject
socket.create_connection = reject
socket.socket.connect = reject
socket.socket.connect_ex = reject
socket.socket.sendto = reject
sys.meta_path.insert(0, RejectTradingImports())
sys.argv = sys.argv[1:]
runpy.run_path(sys.argv[0], run_name='__main__')
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(REPOSITORY_ROOT)
    return subprocess.run(
        [sys.executable, "-c", program, str(example / "sample.py")],
        cwd=example,
        env=environment,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )


def test_copied_direct_script_rejects_before_config_or_trading_import(tmp_path: Path) -> None:
    copied = tmp_path / "copied-sample"
    copied.mkdir()
    shutil.copy2(SAMPLE_PATH, copied / "sample.py")
    copied_runtime = copied / "sample" / "runtime"
    copied_runtime.mkdir(parents=True)
    shutil.copy2(SAMPLE_RUNTIME_TEMPLATE, copied_runtime / "config.yaml")
    (copied / "params_01.json").write_text("{}", encoding="utf-8")

    result = _run_copied_cli(copied)

    assert result.returncode == 2, result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == "REJECTED"
    assert report["error"]["error_code"] == "PRESET_POLICY_VIOLATION"
    assert report["error"]["reason"] == "runtime_not_registered"
    assert report["external_request_counts"] == {"network": 0, "order_write": 0}
