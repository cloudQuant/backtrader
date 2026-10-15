"""Exercise the real schema-v4 local-backtest CLI and packaged Cerebro runner.

This is an offline framework integration check, not a provider or account test.
The code-owned fixture uses its real CSV, production runtime dispatcher,
Backtrader Cerebro, and default local broker. The child process guards optional
service-package imports, sockets, threads, and child processes so a local run
cannot silently turn into service startup.
"""

from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_FIXTURE_ROOT = _REPO_ROOT / "backtrader_runtime" / "_iteration41_backtest_fixture"
_RUNTIME_DIR = _FIXTURE_ROOT / "runtimes" / "local_backtest"
_CONFIG_PATH = _RUNTIME_DIR / "config.yaml"
_DATA_PATH = _FIXTURE_ROOT / "data" / "bars.csv"
_STRATEGY_ID = "backtrader.iteration41.local_backtest_fixture"
_RUNNER_MODULE = "backtrader_runtime._iteration41_backtest_fixture.run"

_OPTIONAL_SERVICE_PREFIXES = (
    "bt_api_py",
    "bt_api_base",
    "bt_api_gateway",
    "bt_api_execution",
    "bt_api_risk",
    "bt_api_monitor",
    "bt_api_transport_zmq",
    "bt_api_binance",
    "bt_api_okx",
    "bt_api_ctp",
)

_CLI_CHILD = r'''
from __future__ import annotations

import contextlib
import importlib.abc
import io
import json
import multiprocessing
import os
import runpy
import socket
import sys
import threading

OPTIONAL_PREFIXES = (
    "bt_api_py",
    "bt_api_base",
    "bt_api_gateway",
    "bt_api_execution",
    "bt_api_risk",
    "bt_api_monitor",
    "bt_api_transport_zmq",
    "bt_api_binance",
    "bt_api_okx",
    "bt_api_ctp",
)
optional_import_attempts = []

class _OptionalPackageBlocker(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        del path, target
        if any(fullname == prefix or fullname.startswith(prefix + ".")
               for prefix in OPTIONAL_PREFIXES):
            optional_import_attempts.append(fullname)
            raise ModuleNotFoundError("CFG05 local-backtest service import blocked")
        return None

sys.meta_path.insert(0, _OptionalPackageBlocker())

network_attempts = []
real_socket = socket.socket

class _NetworkAndServiceSocketGuard(real_socket):
    def connect(self, *args, **kwargs):
        network_attempts.append("socket.connect")
        raise RuntimeError("CFG05 local-backtest network guard")

    def connect_ex(self, *args, **kwargs):
        network_attempts.append("socket.connect_ex")
        raise RuntimeError("CFG05 local-backtest network guard")

    def bind(self, *args, **kwargs):
        network_attempts.append("socket.bind")
        raise RuntimeError("CFG05 local-backtest service-bind guard")

    def listen(self, *args, **kwargs):
        network_attempts.append("socket.listen")
        raise RuntimeError("CFG05 local-backtest service-listen guard")

socket.socket = _NetworkAndServiceSocketGuard
for name in ("create_connection", "getaddrinfo", "gethostbyaddr", "gethostbyname", "getnameinfo"):
    if hasattr(socket, name):
        original = getattr(socket, name)
        def _deny_socket_operation(*args, _name=name, **kwargs):
            del args, kwargs
            network_attempts.append("socket." + _name)
            raise RuntimeError("CFG05 local-backtest network guard")
        setattr(socket, name, _deny_socket_operation)

thread_attempts = []
def _deny_thread_start(self, *args, **kwargs):
    del args, kwargs
    thread_attempts.append(type(self).__name__)
    raise RuntimeError("CFG05 local-backtest thread-start guard")
threading.Thread.start = _deny_thread_start

import multiprocessing.process

process_attempts = []
def _deny_process_start(self, *args, **kwargs):
    del args, kwargs
    process_attempts.append(type(self).__name__)
    raise RuntimeError("CFG05 local-backtest child-process guard")
multiprocessing.process.BaseProcess.start = _deny_process_start

runtime_dir = os.environ["CFG05_LOCAL_BACKTEST_RUNTIME_DIR"]
arguments = ["run", "--strategy-dir", runtime_dir, "--full-report"]
sys.argv = ["bt-runtime", *arguments]
cli_stdout = io.StringIO()
cli_stderr = io.StringIO()
cli_return_code = None
with contextlib.redirect_stdout(cli_stdout), contextlib.redirect_stderr(cli_stderr):
    try:
        runpy.run_module("backtrader_runtime", run_name="__main__", alter_sys=True)
    except SystemExit as exc:
        cli_return_code = exc.code if type(exc.code) is int else 1

try:
    cli_payload = json.loads(cli_stdout.getvalue())
except (TypeError, ValueError):
    cli_payload = None

loaded_optional_packages = sorted(
    name for name in sys.modules
    if any(name == prefix or name.startswith(prefix + ".") for prefix in OPTIONAL_PREFIXES)
)
backtrader_module = sys.modules.get("backtrader")
runtime_module = sys.modules.get("backtrader_runtime")
from backtrader_runtime.registry import default_runtime_registry

registration = default_runtime_registry().require_runtime_dir(runtime_dir)
diagnostics = {
    "arguments": arguments,
    "cli_return_code": cli_return_code,
    "cli_payload": cli_payload,
    "cli_stdout": cli_stdout.getvalue(),
    "cli_stderr": cli_stderr.getvalue(),
    "optional_import_attempts": optional_import_attempts,
    "loaded_optional_packages": loaded_optional_packages,
    "network_attempts": network_attempts,
    "thread_attempts": thread_attempts,
    "process_attempts": process_attempts,
    "active_thread_names": sorted(thread.name for thread in threading.enumerate()),
    "active_child_processes": len(multiprocessing.active_children()),
    "backtrader_origin": None if backtrader_module is None else backtrader_module.__file__,
    "runtime_origin": None if runtime_module is None else runtime_module.__file__,
    "registered_runner_module": registration.runner_module,
    "registered_capability_modules": list(registration.capability_modules),
}
print(json.dumps(diagnostics, sort_keys=True))
'''


def _within(path: Optional[str], root: Path) -> bool:
    if not path:
        return False
    try:
        Path(path).resolve().relative_to(root.resolve())
    except (OSError, RuntimeError, ValueError):
        return False
    return True


@pytest.mark.integration
def test_schema_v4_local_backtest_runs_real_cerebro_through_the_normal_cli() -> None:
    """The v4 direct route completes its real local engine without service activation."""

    assert _CONFIG_PATH.is_file()
    assert _DATA_PATH.is_file()
    config_text = _CONFIG_PATH.read_text(encoding="utf-8")
    assert "config_schema_version: 4" in config_text
    assert f"id: {_STRATEGY_ID}" in config_text
    assert "mode: backtest" in config_text
    assert "preset: local_backtest" in config_text
    with _DATA_PATH.open(encoding="utf-8", newline="") as data_file:
        assert len(list(csv.DictReader(data_file))) == 4

    child_env = dict(os.environ)
    for name in tuple(child_env):
        if (
            name in {
                "BT_STORE_PROVIDER",
                "BT_RUNTIME_MODE",
                "BT_RUNTIME_PRESET",
                "BACKTRADER_RUNTIME_MODE",
                "BACKTRADER_RUNTIME_PRESET",
                "PYTHONPATH",
                "PYTHONHOME",
            }
            or name.startswith("BT_GATEWAY_")
        ):
            child_env.pop(name, None)
    child_env["PYTHONDONTWRITEBYTECODE"] = "1"
    child_env["CFG05_LOCAL_BACKTEST_RUNTIME_DIR"] = str(_RUNTIME_DIR)

    completed = subprocess.run(
        [sys.executable, "-c", _CLI_CHILD],
        cwd=_REPO_ROOT,
        env=child_env,
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    diagnostics: Dict[str, Any] = json.loads(completed.stdout)

    assert diagnostics["arguments"] == [
        "run",
        "--strategy-dir",
        str(_RUNTIME_DIR),
        "--full-report",
    ]
    assert diagnostics["cli_return_code"] == 0
    assert diagnostics["cli_stderr"] == ""
    assert diagnostics["optional_import_attempts"] == []
    assert diagnostics["loaded_optional_packages"] == []
    assert diagnostics["network_attempts"] == []
    assert diagnostics["thread_attempts"] == []
    assert diagnostics["process_attempts"] == []
    assert diagnostics["active_thread_names"] == ["MainThread"]
    assert diagnostics["active_child_processes"] == 0
    assert _within(diagnostics["runtime_origin"], _REPO_ROOT / "backtrader_runtime")
    assert _within(diagnostics["backtrader_origin"], _REPO_ROOT / "backtrader")
    assert diagnostics["registered_runner_module"] == _RUNNER_MODULE
    assert diagnostics["registered_capability_modules"] == []

    payload = diagnostics["cli_payload"]
    assert payload["status"] == "completed"
    assert payload["runner_dispatch"] == "code_owned"
    assert payload["started"] is True
    assert payload["strategy_id"] == _STRATEGY_ID
    assert payload["mode"] == "backtest"
    assert payload["preset"] == "local_backtest"
    assert payload["required_capabilities"] == []

    report = payload["report"]
    assert report["detail"] == "full"
    result = report["result"]
    assert result["status"] == "LOCAL_BACKTEST_CEREBRO_PASS"
    assert result["data_bars"] == 4
    assert result["actual_fills"] == 0
    assert result["provider_submissions"] == 0
    assert result["external_network_requests"] == 0
    assert result["external_write_requests"] == 0
    assert result["network_guard_attempts"] == []
    assert result["actual_pnl"] == "NOT_APPLICABLE"
    assert result["pnl_source"] == "local_backtest_no_orders"
    assert result["runtime_config"]["strategy_id"] == _STRATEGY_ID
    assert result["runtime_config"]["mode"] == "backtest"
    assert result["runtime_config"]["preset"] == "local_backtest"
    assert result["runtime_config"]["allows_network"] is False
    assert result["runtime_config"]["allows_external_writes"] is False
    assert result["runtime_config"]["allows_production_writes"] is False

