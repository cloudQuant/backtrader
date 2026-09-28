from __future__ import annotations

import builtins
import importlib.util
import io
import os
import socket
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SUPPORT_MODULES = (
    (
        "013_1_midfreq_cross_arbitrage",
        REPO / "examples" / "013_1_midfreq_cross_arbitrage" / "ctp_example_support.py",
    ),
    (
        "013_2_highfreq_calendar_arbitrage",
        REPO / "examples" / "013_2_highfreq_calendar_arbitrage" / "ctp_example_support.py",
    ),
)


def _is_env_file(file: object) -> bool:
    try:
        return Path(os.fsdecode(os.fspath(file))).name.casefold() == ".env"
    except (TypeError, ValueError, OSError):
        return False


def _guard_open(original, label: str, env_reads: list[tuple[str, str]]):
    def guarded(file, *args, **kwargs):
        if _is_env_file(file):
            env_reads.append((label, os.fsdecode(os.fspath(file))))
            raise AssertionError("support-module import attempted to read .env")
        return original(file, *args, **kwargs)

    return guarded


def test_legacy_support_import_is_inert_and_live_helpers_default_deny(monkeypatch):
    """Real imports stay offline; all four retired CTP factories refuse first."""

    dotenv_imports = []
    dotenv_calls = []
    env_reads = []
    sdk_imports = []
    network_calls = []

    fake_dotenv = types.ModuleType("dotenv")

    def trap_load_dotenv(*args, **kwargs):
        dotenv_calls.append((args, kwargs))
        raise AssertionError("dotenv.load_dotenv called during support-module import")

    fake_dotenv.load_dotenv = trap_load_dotenv
    monkeypatch.setitem(sys.modules, "dotenv", fake_dotenv)

    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "dotenv" or name.startswith("dotenv."):
            dotenv_imports.append(name)
        sdk_prefixes = ("bt_api_py", "bt_api_ctp", "bt_api_execution", "thosttrader", "ctpbee", "_ctp", "ctp_api")
        if any(name == prefix or name.startswith(prefix + ".") for prefix in sdk_prefixes):
            sdk_imports.append(name)
            raise AssertionError("SDK/native import blocked in source-only regression")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    monkeypatch.setattr(builtins, "open", _guard_open(builtins.open, "builtins.open", env_reads))
    monkeypatch.setattr(io, "open", _guard_open(io.open, "io.open", env_reads))
    monkeypatch.setattr(os, "open", _guard_open(os.open, "os.open", env_reads))

    def deny_network(name):
        def denied(*args, **kwargs):
            network_calls.append(name)
            raise AssertionError(f"network operation blocked: {name}")

        return denied

    for name in ("getaddrinfo", "create_connection"):
        monkeypatch.setattr(socket, name, deny_network("socket." + name))
    for name in ("connect", "connect_ex", "send", "sendall", "sendto", "bind", "listen", "accept", "sendfile"):
        monkeypatch.setattr(socket.socket, name, deny_network("socket.socket." + name))

    monkeypatch.syspath_prepend(str(REPO))
    loaded = []
    for label, path in SUPPORT_MODULES:
        assert path.is_file(), f"missing support module: {path}"
        module_name = "iteration41_inert_ctp_support_" + label
        spec = importlib.util.spec_from_file_location(module_name, path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, module_name, module)
        spec.loader.exec_module(module)
        loaded.append((label, module))

    assert dotenv_imports == []
    assert dotenv_calls == []
    assert env_reads == []
    assert sdk_imports == []
    assert network_calls == []

    class Bomb:
        def __getattr__(self, name):
            raise AssertionError(f"helper inspected a forbidden argument: {name}")

    constructor_calls = []

    def forbidden_constructor(*args, **kwargs):
        constructor_calls.append((args, kwargs))
        raise AssertionError("legacy helper reached a Store/Broker constructor")

    for label, module in loaded:
        monkeypatch.setattr(module, "BtApiStore", forbidden_constructor)
        monkeypatch.setattr(module, "BtApiBroker", forbidden_constructor)
        for helper, args in (
            ("create_live_store", (Bomb(),)),
            ("create_live_broker", (Bomb(), Bomb())),
        ):
            with pytest.raises(Exception) as failure:
                getattr(module, helper)(*args)
            assert getattr(failure.value, "reason", None) == "legacy_direct_execution_not_supported", (
                label,
                helper,
                type(failure.value).__name__,
            )

    assert constructor_calls == []
    assert dotenv_imports == []
    assert dotenv_calls == []
    assert env_reads == []
    assert sdk_imports == []
    assert network_calls == []
