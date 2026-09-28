"""Offline contract for the retired 007 direct Cerebro runner."""

from __future__ import annotations

import builtins
import importlib.util
import socket
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from backtrader_runtime.errors import RuntimeConfigError

REPO = Path(__file__).resolve().parents[2]
SUPPORT_PATH = REPO / "examples" / "007_ctp" / "ctp_example_support.py"
SDK_PREFIXES = (
    "bt_api_py",
    "bt_api_ctp",
    "bt_api_execution",
    "thosttrader",
    "thostmduserapi",
    "ctpbee",
    "ctp_api",
    "_ctp",
    "vnpy_ctp",
)


def test_007_timeout_runner_rejects_before_timer_or_cerebro_access(monkeypatch):
    """The retired runner must reject before touching caller state or starting I/O."""
    sdk_imports = []
    network_calls = []
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if any(name == prefix or name.startswith(prefix + ".") for prefix in SDK_PREFIXES):
            sdk_imports.append(name)
            raise AssertionError("provider/native import blocked")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    def denied(name):
        def deny(*_args, **_kwargs):
            network_calls.append(name)
            raise AssertionError("network operation blocked")

        return deny

    for name in ("getaddrinfo", "create_connection"):
        monkeypatch.setattr(socket, name, denied("socket." + name))
    for name in (
        "connect",
        "connect_ex",
        "send",
        "sendall",
        "sendto",
        "bind",
        "listen",
        "accept",
        "sendfile",
    ):
        monkeypatch.setattr(socket.socket, name, denied("socket.socket." + name))

    spec = importlib.util.spec_from_file_location("iteration41_007_timeout_failclose", SUPPORT_PATH)
    assert spec is not None and spec.loader is not None
    support = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "iteration41_007_timeout_failclose", support)
    spec.loader.exec_module(support)

    input_accesses = []

    class CerebroBomb:
        def __getattribute__(self, name):
            input_accesses.append(name)
            raise AssertionError("helper inspected the supplied Cerebro")

    timer_calls = []

    def forbidden_timer(*args, **kwargs):
        timer_calls.append((args, kwargs))
        raise AssertionError("helper constructed a timeout timer")

    # Replace only the retained module's re-export; no real Timer is started.
    assert hasattr(support, "threading")
    monkeypatch.setattr(support, "threading", SimpleNamespace(Timer=forbidden_timer))

    with pytest.raises(RuntimeConfigError) as failure:
        support.run_cerebro_with_timeout(CerebroBomb(), timeout_seconds=object())

    assert failure.value.reason == "legacy_direct_execution_not_supported"
    assert input_accesses == []
    assert timer_calls == []
    assert sdk_imports == []
    assert network_calls == []
