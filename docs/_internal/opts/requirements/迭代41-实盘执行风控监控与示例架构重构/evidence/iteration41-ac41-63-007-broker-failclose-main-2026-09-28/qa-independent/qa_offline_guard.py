from __future__ import annotations

import builtins
import inspect
import io
import os
from pathlib import Path
import socket
import sys

ROOT = Path(__file__).resolve().parent
EVENTS = {"provider_imports": [], "env_getenv": [], "env_files": [], "socket_calls": []}
PREFIXES = ("bt_api_py", "bt_api_ctp", "bt_api_execution", "thosttrader", "thostmduserapi", "ctpbee", "ctp_api", "_ctp", "vnpy_ctp")


def _in_project():
    frame = inspect.currentframe()
    try:
        caller = frame.f_back if frame is not None else None
        if caller is None:
            return False
        try:
            Path(caller.f_code.co_filename).resolve().relative_to(ROOT)
            return Path(caller.f_code.co_filename).resolve() != Path(__file__).resolve()
        except (OSError, ValueError):
            return False
    finally:
        del frame

def pytest_configure(config):
    EVENTS["preloaded_provider_modules"] = [name for name in sys.modules if any(name == p or name.startswith(p + ".") for p in PREFIXES)]
    original_import = builtins.__import__
    def guarded_import(name, *args, **kwargs):
        if any(name == p or name.startswith(p + ".") for p in PREFIXES):
            EVENTS["provider_imports"].append(name)
            raise AssertionError("offline QA blocked CTP provider/native import: " + name)
        if name == "talib":
            raise ImportError("offline QA omitted unrelated optional TA-Lib integration")
        return original_import(name, *args, **kwargs)
    builtins.__import__ = guarded_import

    original_getenv = os.getenv
    def guarded_getenv(name, default=None):
        EVENTS["env_getenv"].append(str(name))
        raise AssertionError("offline QA blocked process os.getenv access: " + str(name))
    os.getenv = guarded_getenv

    def guard_open(original):
        def guarded(file, *args, **kwargs):
            try:
                name = Path(os.fsdecode(os.fspath(file))).name.casefold()
            except (TypeError, ValueError, OSError):
                name = ""
            if name == ".env":
                EVENTS["env_files"].append(os.fsdecode(os.fspath(file)))
                raise AssertionError("offline QA blocked .env read")
            return original(file, *args, **kwargs)
        return guarded
    builtins.open = guard_open(builtins.open)
    io.open = guard_open(io.open)
    os.open = guard_open(os.open)

    def deny(name):
        def blocked(*args, **kwargs):
            EVENTS["socket_calls"].append(name)
            raise AssertionError("offline QA blocked socket call: " + name)
        return blocked
    for name in ("getaddrinfo", "gethostbyname", "gethostbyname_ex", "gethostbyaddr", "getnameinfo", "create_connection"):
        if hasattr(socket, name):
            setattr(socket, name, deny("socket." + name))
    for name in ("connect", "connect_ex", "send", "sendall", "sendto", "sendmsg", "recv", "recv_into", "recvfrom", "recvfrom_into", "bind", "listen", "accept", "sendfile", "shutdown"):
        if hasattr(socket.socket, name):
            setattr(socket.socket, name, deny("socket.socket." + name))


def pytest_sessionfinish(session, exitstatus):
    failures = {key: value for key, value in EVENTS.items() if value}
    if failures:
        session.config._offline_guard_failures = failures
        session.exitstatus = 1


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    failures = getattr(config, "_offline_guard_failures", None)
    if failures:
        terminalreporter.write_sep("=", "offline QA guard observed forbidden attempts")
        terminalreporter.write_line(repr(failures))
    else:
        terminalreporter.write_sep("=", "offline QA guard summary")
        terminalreporter.write_line("No provider/native imports, .env reads, os.getenv calls, or socket calls observed.")