"""Unregistered Root-only synthetic gate for the TH01 fixed-GET spawn path.

This gate cold-loads the pinned public launcher in the parent and Windows
spawn child, then calls the accepted fixed-GET owner with synthetic
credentials and a synthetic HTTPS response. It never creates an account
factory, reads protected inputs, or produces certification evidence.
"""

from __future__ import annotations

import contextlib
import builtins
import hashlib
import http.client
import importlib.abc
import io
import json
import multiprocessing
import multiprocessing.connection
import multiprocessing.context
import multiprocessing.process
import multiprocessing.util
import os
from pathlib import Path
import socket
import sqlite3
import ssl
import stat
import subprocess
import sys
import time
from types import FunctionType, ModuleType, SimpleNamespace
from typing import Any


GATE_ROOT = Path(__file__).resolve().parents[1]
GATE_LAUNCHER_PATH = (
    GATE_ROOT / "scripts" / "iteration41_binance_th01_account_window_candidate_r2.py"
)
GATE_LAUNCHER_BYTES = 11_391
GATE_LAUNCHER_SHA256 = "698d607e6abce0f5595470c5207a4e065b11200df5b895db35fb6af816364cd6"
GATE_SYNTHETIC_KEY = "PUBLIC_SYNTHETIC_KEY"
GATE_SYNTHETIC_SECRET = "PUBLIC_SYNTHETIC_SECRET"
GATE_FAKE_CONTEXT = object()
GATE_RETAINED_OWNER_NAMESPACES: list[dict[str, Any]] = []
_GATE_SYNTHETIC_CAPABILITY = [False]
_GATE_DENIED_IMPORT_ROOTS = frozenset(
    {
        "ctypes",
        "win32api",
        "win32con",
        "win32event",
        "win32file",
        "win32job",
        "win32pipe",
        "win32process",
        "win32security",
        "win32service",
        "win32timezone",
        "pywintypes",
        "win32com",
        "comtypes",
        "backtrader_runtime",
    }
)
_GATE_PRIVATE_PATH_MARKERS = frozenset(
    {
        ".env",
        "config.yaml",
        "config.yml",
        "secrets.yaml",
        "secrets.yml",
        "monitor.log",
        "th01_monitor_outbox.sqlite",
    }
)
_GATE_PUBLIC_SOURCE_PATHS = frozenset(
    str(path).replace("\\", "/").lower()
    for path in (
        GATE_LAUNCHER_PATH,
        GATE_ROOT / "scripts" / "iteration41_binance_th01_spawn_pipe_gate_r1.py",
        GATE_ROOT
        / "examples"
        / "000_live_certification"
        / "binance_penetration"
        / "_certification"
        / "th01_root_protected_owner_r1.py",
        GATE_ROOT
        / "examples"
        / "000_live_certification"
        / "binance_penetration"
        / "_certification"
        / "th01_account_window_candidate_r2.py",
        GATE_ROOT / "backtrader_runtime" / "certification_binance_roundtrip_r3_cli.py",
        GATE_ROOT / "backtrader_runtime" / "certification_roundtrip_private.py",
    )
)
_GATE_EXPECTED_QUERY: dict[str, int] | None = None
_GATE_EXPECTED_HISTORY_START_MS: int | None = None
_GATE_ACTIVE_ENDPOINTS: list[Any] | None = None
_GATE_ACTIVE_PROCESSES: list[Any] | None = None
_GATE_KEEP_HOST_OPEN = False
_GATE_ATTEMPTED = False
_GATE_SOURCE_GUARDS: dict[str, Any] | None = None
_GATE_CONTEXT_PIPE_DELEGATION = [False]
_GATE_CONTEXT_PROCESS_DELEGATION = [False]
_GATE_PROCESS_START_DELEGATION: list[Any] = [None]


class _GateImportDenyFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        root = fullname.split(".", 1)[0].lower()
        if (
            root in _GATE_DENIED_IMPORT_ROOTS
            or root.startswith("win32")
            or root in {"pywintypes", "comtypes"}
        ):
            raise ImportError("native and private runtime imports are disabled in this gate")
        return None


class _GateBlocked(Exception):
    pass


class _GateFakeSocket:
    def settimeout(self, seconds: float) -> None:
        if type(seconds) not in (int, float) or not 0 < seconds <= 8.25:
            raise _GateBlocked()


class _GateFakeResponse:
    def __init__(self) -> None:
        self.body = b"[]"
        self._read = False
        self.status = 200

    def getheader(self, name: str, default: Any = None) -> Any:
        key = name.lower()
        if key == "content-encoding":
            return "identity"
        if key == "transfer-encoding":
            return None
        if key == "content-length":
            return str(len(self.body))
        return default

    def read1(self, size: int) -> bytes:
        if type(size) is not int or size <= 0:
            raise _GateBlocked()
        if self._read:
            return b""
        self._read = True
        return self.body[:size]


class _GateFakeHTTPSConnection:
    """HTTPS stand-in that accepts one fixed-route request only."""

    instances: list["_GateFakeHTTPSConnection"] = []

    def __init__(self, host: str, *, timeout: float, context: Any) -> None:
        if (
            host != "demo-fapi.binance.com"
            or type(timeout) not in (int, float)
            or not 0 < timeout <= 8.0
            or context is not GATE_FAKE_CONTEXT
        ):
            raise _GateBlocked()
        self.sock: _GateFakeSocket | None = None
        self.auto_open = 1
        self._request_seen = False
        self._response: _GateFakeResponse | None = None
        self.closed = False
        self.__class__.instances.append(self)

    def connect(self) -> None:
        if self.sock is not None:
            raise _GateBlocked()
        self.sock = _GateFakeSocket()

    def request(self, method: str, target: str, *, headers: dict[str, str]) -> None:
        if (
            self._request_seen
            or method != "GET"
            or target.split("?", 1)[0] != "/fapi/v1/allOrders"
            or headers.get("X-MBX-APIKEY") != GATE_SYNTHETIC_KEY
            or headers.get("Accept") != "application/json"
            or headers.get("Accept-Encoding") != "identity"
        ):
            raise _GateBlocked()
        self._request_seen = True

    def getresponse(self) -> _GateFakeResponse:
        if not self._request_seen or self._response is not None:
            raise _GateBlocked()
        self._response = _GateFakeResponse()
        return self._response

    def close(self) -> None:
        self.closed = True
        self.sock = None


def _gate_read_pinned_launcher() -> bytes:
    """Bounded exact-source read, with shape checks before opening the file."""
    try:
        root = Path(os.path.abspath(str(GATE_ROOT)))
        source = Path(os.path.abspath(str(GATE_LAUNCHER_PATH)))
        relative = source.relative_to(root)
        if relative.as_posix() != "scripts/iteration41_binance_th01_account_window_candidate_r2.py":
            raise _GateBlocked()
        current = Path(root.anchor)
        for part in root.parts[1:]:
            current = current / part
            info = current.lstat()
            if (
                not stat.S_ISDIR(info.st_mode)
                or stat.S_ISLNK(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & 0x400
            ):
                raise _GateBlocked()
        before = source.lstat()
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_ISLNK(before.st_mode)
            or getattr(before, "st_file_attributes", 0) & 0x400
            or getattr(before, "st_nlink", 1) != 1
            or before.st_size != GATE_LAUNCHER_BYTES
        ):
            raise _GateBlocked()
        descriptor = os.open(str(source), os.O_RDONLY | getattr(os, "O_BINARY", 0))
        try:
            opened = os.fstat(descriptor)
            before_id = (
                before.st_dev,
                before.st_ino,
                before.st_size,
                getattr(before, "st_mtime_ns", None),
                getattr(before, "st_ctime_ns", None),
            )
            opened_id = (
                opened.st_dev,
                opened.st_ino,
                opened.st_size,
                getattr(opened, "st_mtime_ns", None),
                getattr(opened, "st_ctime_ns", None),
            )
            if before_id != opened_id or getattr(opened, "st_nlink", 1) != 1:
                raise _GateBlocked()
            chunks = bytearray()
            while len(chunks) <= GATE_LAUNCHER_BYTES:
                piece = os.read(descriptor, min(8192, GATE_LAUNCHER_BYTES + 1 - len(chunks)))
                if not piece:
                    break
                chunks.extend(piece)
            after_handle = os.fstat(descriptor)
            after_path = source.lstat()
            after_id = (
                after_handle.st_dev,
                after_handle.st_ino,
                after_handle.st_size,
                getattr(after_handle, "st_mtime_ns", None),
                getattr(after_handle, "st_ctime_ns", None),
            )
            path_id = (
                after_path.st_dev,
                after_path.st_ino,
                after_path.st_size,
                getattr(after_path, "st_mtime_ns", None),
                getattr(after_path, "st_ctime_ns", None),
            )
            if (
                after_id != before_id
                or path_id != before_id
                or stat.S_ISLNK(after_path.st_mode)
                or getattr(after_path, "st_file_attributes", 0) & 0x400
                or getattr(after_path, "st_nlink", 1) != 1
            ):
                raise _GateBlocked()
        finally:
            os.close(descriptor)
        raw = bytes(chunks)
        if (
            len(raw) != GATE_LAUNCHER_BYTES
            or hashlib.sha256(raw).hexdigest() != GATE_LAUNCHER_SHA256
        ):
            raise _GateBlocked()
        return raw
    except _GateBlocked:
        raise
    except Exception as exc:
        raise _GateBlocked() from exc


def _gate_path_is_private(value: Any) -> bool:
    try:
        text = os.fsdecode(os.fspath(value)).replace("\\", "/")
    except (TypeError, ValueError, OSError):
        return False
    if os.path.abspath(text).replace("\\", "/").lower() in _GATE_PUBLIC_SOURCE_PATHS:
        return False
    parts = tuple(part.lower() for part in text.split("/") if part)
    return any(
        part in _GATE_PRIVATE_PATH_MARKERS
        or part == ".env.local"
        or ".env." in part
        or "private" in part
        or "capture" in part
        or "secret" in part
        or "credential" in part
        for part in parts
    )


def _gate_make_open_guard(original):
    def guarded_open(file, *args, **kwargs):
        if _gate_path_is_private(file):
            raise PermissionError("private input access is disabled in this gate")
        return original(file, *args, **kwargs)

    return guarded_open


def _gate_deny_process_launch(*_args: Any, **_kwargs: Any) -> None:
    raise PermissionError("process launch is disabled outside the synthetic spawn capability")


def _gate_install_source_guards() -> dict[str, Any]:
    """Block private input paths, native extension imports and other launch APIs."""
    originals: dict[str, Any] = {
        "builtins_open": builtins.open,
        "io_open": io.open,
        "io_open_code": getattr(io, "open_code", None),
        "os_open": os.open,
        "subprocess_popen": subprocess.Popen,
        "multiprocessing_process": multiprocessing.Process,
        "multiprocessing_pipe": multiprocessing.Pipe,
        "multiprocessing_get_context": multiprocessing.get_context,
        "multiprocessing_context_process": multiprocessing.context.Process,
        "spawn_context_process": multiprocessing.context.SpawnContext.Process,
        "spawn_process_class": multiprocessing.context.SpawnProcess,
        "base_context_pipe": multiprocessing.context.BaseContext.Pipe,
        "connection_pipe": multiprocessing.connection.Pipe,
        "base_process_start": multiprocessing.process.BaseProcess.start,
        "sqlite3_connect": sqlite3.connect,
        "os_system": os.system,
        "meta_finder": _GateImportDenyFinder(),
    }
    for name in dir(os):
        if name.startswith(("spawn", "exec")) or name in {"system", "startfile", "fork"}:
            value = getattr(os, name)
            if callable(value):
                originals["os_" + name] = value
    builtins.open = _gate_make_open_guard(originals["builtins_open"])
    io.open = _gate_make_open_guard(originals["io_open"])
    if callable(originals["io_open_code"]):
        io.open_code = _gate_make_open_guard(originals["io_open_code"])
    os.open = _gate_make_open_guard(originals["os_open"])
    subprocess.Popen = _gate_deny_process_launch  # type: ignore[assignment]
    multiprocessing.Process = _gate_deny_process_launch  # type: ignore[assignment]
    # multiprocessing.Pipe is a module-level alias bound when multiprocessing
    # imports BaseContext.Pipe. Replacing BaseContext.Pipe later does not
    # replace this alias, so deny it directly outside the observed context.
    multiprocessing.Pipe = _gate_deny_process_launch  # type: ignore[assignment]
    sqlite3.connect = _gate_deny_process_launch  # type: ignore[assignment]

    def guarded_connection_pipe(*args: Any, **kwargs: Any):
        if (
            _GATE_SYNTHETIC_CAPABILITY[0] is not True
            or _GATE_CONTEXT_PIPE_DELEGATION[0] is not True
            or args != (False,)
            or kwargs
        ):
            raise PermissionError("only the fixed one-way worker pipe is allowed")
        return originals["connection_pipe"](*args, **kwargs)

    def guarded_base_context_pipe(context: Any, duplex: bool = True):
        if (
            _GATE_SYNTHETIC_CAPABILITY[0] is not True
            or _GATE_CONTEXT_PIPE_DELEGATION[0] is not True
            or getattr(context, "_name", None) != "spawn"
            or duplex is not False
        ):
            raise PermissionError("only the fixed spawn worker pipe is allowed")
        return originals["base_context_pipe"](context, duplex=duplex)

    def guarded_spawn_process_factory(context: Any, *args: Any, **kwargs: Any):
        if (
            _GATE_SYNTHETIC_CAPABILITY[0] is not True
            or _GATE_CONTEXT_PROCESS_DELEGATION[0] is not True
            or type(context) is not multiprocessing.context.SpawnContext
            or args
            or set(kwargs) != {"target", "args", "name", "daemon"}
            or kwargs.get("target") is not globals().get("_root_fixed_signed_get_worker")
            or kwargs.get("name") != "th01-fixed-signed-read"
            or kwargs.get("daemon") is not True
        ):
            raise PermissionError("only the fixed signed-read worker process is allowed")
        return originals["spawn_context_process"](**kwargs)

    def guarded_base_process_start(process: Any):
        if (
            _GATE_SYNTHETIC_CAPABILITY[0] is not True
            or _GATE_PROCESS_START_DELEGATION[0] is not process
            or not any(
                getattr(recorded, "_process", None) is process
                for recorded in (_GATE_ACTIVE_PROCESSES or [])
            )
        ):
            raise PermissionError("process start is disabled outside the fixed gate")
        return originals["base_process_start"](process)

    multiprocessing.context.Process = _gate_deny_process_launch  # type: ignore[assignment]
    multiprocessing.context.SpawnProcess = _gate_deny_process_launch  # type: ignore[assignment]
    multiprocessing.context.SpawnContext.Process = guarded_spawn_process_factory  # type: ignore[assignment]
    multiprocessing.context.BaseContext.Pipe = guarded_base_context_pipe  # type: ignore[assignment]
    multiprocessing.connection.Pipe = guarded_connection_pipe  # type: ignore[assignment]
    multiprocessing.process.BaseProcess.start = guarded_base_process_start  # type: ignore[assignment]
    for name in dir(os):
        if name.startswith(("spawn", "exec")) or name in {"system", "startfile", "fork"}:
            if "os_" + name in originals:
                setattr(os, name, _gate_deny_process_launch)
    sys.meta_path.insert(0, originals["meta_finder"])

    def guarded_get_context(method: str | None = None):
        if (
            _GATE_SYNTHETIC_CAPABILITY[0] is True
            and method == "spawn"
            and type(_GATE_ACTIVE_ENDPOINTS) is list
            and type(_GATE_ACTIVE_PROCESSES) is list
        ):
            context = originals["multiprocessing_get_context"](method)
            return _GateObservedSpawnContext(
                context, _GATE_ACTIVE_ENDPOINTS, _GATE_ACTIVE_PROCESSES
            )
        raise PermissionError("multiprocessing contexts are disabled outside the fixed gate")

    originals["guarded_get_context"] = guarded_get_context
    multiprocessing.get_context = guarded_get_context  # type: ignore[assignment]
    return originals


def _gate_restore_source_guards(originals: dict[str, Any]) -> None:
    builtins.open = originals["builtins_open"]
    io.open = originals["io_open"]
    if callable(originals["io_open_code"]):
        io.open_code = originals["io_open_code"]
    os.open = originals["os_open"]
    subprocess.Popen = originals["subprocess_popen"]
    multiprocessing.Process = originals["multiprocessing_process"]
    multiprocessing.Pipe = originals["multiprocessing_pipe"]
    multiprocessing.get_context = originals["multiprocessing_get_context"]
    multiprocessing.context.Process = originals["multiprocessing_context_process"]
    multiprocessing.context.SpawnContext.Process = originals["spawn_context_process"]
    multiprocessing.context.SpawnProcess = originals["spawn_process_class"]
    multiprocessing.context.BaseContext.Pipe = originals["base_context_pipe"]
    multiprocessing.connection.Pipe = originals["connection_pipe"]
    multiprocessing.process.BaseProcess.start = originals["base_process_start"]
    sqlite3.connect = originals["sqlite3_connect"]
    for key, value in originals.items():
        if key.startswith("os_") and key != "os_open":
            setattr(os, key[3:], value)
    finder = originals["meta_finder"]
    if finder in sys.meta_path:
        sys.meta_path.remove(finder)


def _gate_bootstrap_current_sources(
    namespace: dict[str, Any] | None = None,
) -> dict[str, object]:
    """Compile exact sources, registering the spawn namespace for dataclasses."""
    namespace = globals() if namespace is None else namespace
    runtime_name = namespace.get("__name__")
    namespace["_GATE_BOOTSTRAP_STAGE"] = "launcher_source_load"
    source = _gate_read_pinned_launcher()
    saved_argv = list(sys.argv)
    captured = io.StringIO()
    target_namespace = namespace
    if runtime_name == "__mp_main__":
        child_module = ModuleType("__mp_main__")
        child_module.__dict__.update(namespace)
        sys.modules["__mp_main__"] = child_module
        target_namespace = child_module.__dict__
    try:
        namespace["_GATE_BOOTSTRAP_STAGE"] = "launcher_source_exec"
        if runtime_name == "__main__":
            sys.argv = [str(GATE_LAUNCHER_PATH), "--qa-source-only"]
        with contextlib.redirect_stdout(captured):
            exec(
                compile(source, str(GATE_LAUNCHER_PATH), "exec", dont_inherit=True),
                target_namespace,
            )
    except SystemExit as exc:
        if runtime_name != "__main__" or exc.code != 0:
            if runtime_name == "__main__":
                lines = [line for line in captured.getvalue().splitlines() if line.strip()]
                if len(lines) == 1:
                    try:
                        qa = json.loads(lines[0])
                    except Exception:
                        qa = {}
                    status = qa.get("status")
                    if status in {"SOURCE_ONLY_QA", "BLOCKED_SOURCE_QA"}:
                        namespace["_GATE_BOOTSTRAP_SAFE_QA_STATUS"] = status
            raise _GateBlocked() from None
    finally:
        sys.argv = saved_argv

    if target_namespace is not namespace:
        namespace.update(
            {
                key: value
                for key, value in target_namespace.items()
                if key not in {"__name__", "__file__", "__package__", "__spec__", "__cached__"}
            }
        )
    namespace["_GATE_BOOTSTRAP_STAGE"] = "owner_source_binding"
    owner_sha = target_namespace.get("__th01_verified_owner_source_sha256__")
    candidate = target_namespace.get("_CANDIDATE_MODULE")
    if (
        type(owner_sha) is not str
        or owner_sha != target_namespace.get("OWNER_SHA256")
        or candidate is None
        or getattr(candidate, "__th01_verified_candidate_source_sha256__", None)
        != target_namespace.get("CANDIDATE_SHA256")
        or target_namespace.get("_root_fixed_signed_get_worker") is None
        or target_namespace["_root_fixed_signed_get_worker"].__module__ != runtime_name
    ):
        raise _GateBlocked()

    if runtime_name == "__main__":
        namespace["_GATE_BOOTSTRAP_STAGE"] = "launcher_qa_parse"
        lines = [line for line in captured.getvalue().splitlines() if line.strip()]
        if len(lines) != 1:
            raise _GateBlocked()
        try:
            qa = json.loads(lines[0])
        except Exception as exc:
            raise _GateBlocked() from exc
        namespace["_GATE_BOOTSTRAP_SAFE_QA_STATUS"] = (
            qa.get("status")
            if qa.get("status") in {"SOURCE_ONLY_QA", "BLOCKED_SOURCE_QA"}
            else "unclassified"
        )
        namespace["_GATE_BOOTSTRAP_SAFE_QA_FLAGS"] = {
            key: qa.get(key) is True
            for key in (
                "owner_source_bound",
                "candidate_source_bound",
                "protected_source_pins_checked",
                "runtime_package_loaded",
                "private_helper_loaded",
                "protected_credential_read",
                "provider_read_started",
                "trading_write_started",
                "account_full_snapshot_issued",
                "formal_case_pass",
            )
        }
        if not (
            qa.get("status") == "SOURCE_ONLY_QA"
            and qa.get("owner_source_bound") is True
            and qa.get("candidate_source_bound") is True
            and qa.get("protected_source_pins_checked") is True
            and qa.get("runtime_package_loaded") is False
            and qa.get("private_helper_loaded") is False
            and qa.get("protected_credential_read") is False
            and qa.get("provider_read_started") is False
            and qa.get("trading_write_started") is False
            and qa.get("account_full_snapshot_issued") is False
            and qa.get("formal_case_pass") is False
        ):
            namespace["_GATE_BOOTSTRAP_STAGE"] = "launcher_qa_rejected"
            raise _GateBlocked()
        return {"launcher_source_qa": True, "child_source_qa": False}

    try:
        namespace["_GATE_BOOTSTRAP_STAGE"] = "child_dependency_preflight"
        source_hashes = candidate.source_preflight(target_namespace["ROOT"])
        candidate._verify_candidate_source_binding()
    except Exception as exc:
        raise _GateBlocked() from exc
    if len(source_hashes) != 3:
        raise _GateBlocked()
    return {"launcher_source_qa": False, "child_source_qa": True}


def _gate_deny_network(*_args: Any, **_kwargs: Any) -> None:
    raise _GateBlocked()


def _gate_install_synthetic_transport() -> tuple[object, object, object, object, object, object]:
    old_https = http.client.HTTPSConnection
    old_ssl_factory = ssl.create_default_context
    old_create_connection = socket.create_connection
    old_socket_connect = socket.socket.connect
    old_socket_connect_ex = socket.socket.connect_ex
    old_getaddrinfo = socket.getaddrinfo
    http.client.HTTPSConnection = _GateFakeHTTPSConnection  # type: ignore[assignment]
    ssl.create_default_context = lambda: GATE_FAKE_CONTEXT  # type: ignore[assignment]
    socket.create_connection = _gate_deny_network  # type: ignore[assignment]
    socket.socket.connect = _gate_deny_network  # type: ignore[assignment]
    socket.socket.connect_ex = _gate_deny_network  # type: ignore[assignment]
    socket.getaddrinfo = _gate_deny_network  # type: ignore[assignment]
    return (
        old_https,
        old_ssl_factory,
        old_create_connection,
        old_socket_connect,
        old_socket_connect_ex,
        old_getaddrinfo,
    )


def _gate_restore_transport(
    originals: tuple[object, object, object, object, object, object]
) -> None:
    (
        old_https,
        old_ssl_factory,
        old_create_connection,
        old_socket_connect,
        old_socket_connect_ex,
        old_getaddrinfo,
    ) = originals
    http.client.HTTPSConnection = old_https  # type: ignore[assignment]
    ssl.create_default_context = old_ssl_factory  # type: ignore[assignment]
    socket.create_connection = old_create_connection  # type: ignore[assignment]
    socket.socket.connect = old_socket_connect  # type: ignore[assignment]
    socket.socket.connect_ex = old_socket_connect_ex  # type: ignore[assignment]
    socket.getaddrinfo = old_getaddrinfo  # type: ignore[assignment]


def _gate_forbidden_native_modules_loaded() -> bool:
    roots = _GATE_DENIED_IMPORT_ROOTS
    return any(
        type(name) is str
        and (
            name.split(".", 1)[0].lower() in roots
            or name.split(".", 1)[0].lower().startswith("win32")
        )
        for name in sys.modules
    )


def _gate_root_tty_ready() -> bool:
    if not sys.flags.inspect:
        return False
    try:
        return bool(sys.stdin.isatty() and sys.stdout.isatty())
    except Exception:
        return False


def _gate_child_spawn_flags_safe() -> bool:
    """Prove -i is omitted by the current multiprocessing flag builder."""
    try:
        actual = multiprocessing.util._args_from_interpreter_flags
        if (
            actual.__module__ != "subprocess"
            or Path(actual.__code__.co_filename).name.lower() != "subprocess.py"
        ):
            return False
        fake_sys = SimpleNamespace(
            flags=SimpleNamespace(
                debug=0,
                inspect=1,
                interactive=1,
                dont_write_bytecode=1,
                no_site=1,
                verbose=0,
                bytes_warning=0,
                quiet=0,
                isolated=1,
                ignore_environment=1,
                no_user_site=1,
                safe_path=1,
                dev_mode=False,
            ),
            warnoptions=[],
            _xoptions={},
        )
        synthetic_globals = dict(actual.__globals__)
        synthetic_globals["sys"] = fake_sys
        synthetic_globals["_optim_args_from_interpreter_flags"] = lambda: []
        simulated = FunctionType(actual.__code__, synthetic_globals)()
        return simulated == ["-B", "-S", "-I"] and "-i" not in simulated
    except BaseException:
        return False


def _gate_post_call_source_pins(owner: dict[str, Any]) -> dict[str, bool]:
    """Re-read every public executable member after the call, returning booleans only."""
    checks = {
        "launcher": False,
        "owner": False,
        "candidate": False,
        "candidate_dependencies": False,
    }
    try:
        checks["launcher"] = hashlib.sha256(_gate_read_pinned_launcher()).hexdigest() == (
            GATE_LAUNCHER_SHA256
        )
        read_public = owner.get("_read_pinned_public_source")
        if not callable(read_public):
            return checks
        owner_path = owner.get("OWNER_PATH")
        owner_sha = owner.get("OWNER_SHA256")
        candidate_path = owner.get("CANDIDATE_PATH")
        candidate_sha = owner.get("CANDIDATE_SHA256")
        maximum = owner.get("MAX_SOURCE_BYTES")
        if (
            not isinstance(owner_path, Path)
            or type(owner_sha) is not str
            or not isinstance(candidate_path, Path)
            or type(candidate_sha) is not str
            or type(maximum) is not int
        ):
            return checks
        owner_raw = read_public(owner_path, owner_sha, maximum)
        checks["owner"] = hashlib.sha256(owner_raw).hexdigest() == owner_sha
        candidate_raw = read_public(candidate_path, candidate_sha, maximum)
        candidate = owner.get("_CANDIDATE_MODULE")
        checks["candidate"] = (
            hashlib.sha256(candidate_raw).hexdigest() == candidate_sha
            and getattr(candidate, "__th01_verified_candidate_source_sha256__", None)
            == candidate_sha
            and Path(getattr(candidate, "__file__", "")).resolve() == candidate_path.resolve()
        )
        hashes = candidate.source_preflight(owner["ROOT"])
        candidate._verify_candidate_source_binding()
        checks["candidate_dependencies"] = type(hashes) is dict and len(hashes) == 3
    except BaseException:
        return checks
    return checks


def _gate_owner_is_uncertain(owner: dict[str, Any]) -> bool:
    active = owner.get("_ACTIVE_ROOT_FIXED_WORKERS")
    return type(active) is list and bool(active)


GATE_RETAINED_GATE_RESOURCES: list[Any] = []


def _gate_retain_owner_if_uncertain(
    owner: dict[str, Any], endpoints: list[Any] | None = None, processes: list[Any] | None = None
) -> bool:
    """Keep live worker ownership in this RootTTY host when cleanup is uncertain."""
    global _GATE_KEEP_HOST_OPEN
    endpoints = [] if endpoints is None else endpoints
    processes = [] if processes is None else processes
    uncertain = (
        _gate_owner_is_uncertain(owner)
        or any(getattr(endpoint, "closed", None) is not True for endpoint in endpoints)
        or any(getattr(process, "_closed", False) is not True for process in processes)
    )
    if not uncertain:
        _GATE_KEEP_HOST_OPEN = False
        return False
    if not any(existing is owner for existing in GATE_RETAINED_OWNER_NAMESPACES):
        GATE_RETAINED_OWNER_NAMESPACES.append(owner)
    for resource in [*endpoints, *processes]:
        if not any(existing is resource for existing in GATE_RETAINED_GATE_RESOURCES):
            GATE_RETAINED_GATE_RESOURCES.append(resource)
    _GATE_KEEP_HOST_OPEN = True
    return True


def _gate_exit_permitted() -> bool:
    return _GATE_KEEP_HOST_OPEN is not True and not _gate_owner_is_uncertain(globals())


class _GateObservedSpawnProcess:
    """Record lifecycle facts while forwarding to a real SpawnProcess."""

    def __init__(self, process: Any) -> None:
        self._process = process
        self.pid: int | None = None
        self._closed = False

    def _require_active_owner_call(self) -> None:
        if _GATE_SYNTHETIC_CAPABILITY[0] is not True or not any(
            recorded is self for recorded in (_GATE_ACTIVE_PROCESSES or [])
        ):
            raise PermissionError("worker lifecycle access is disabled outside the fixed gate")

    @property
    def exitcode(self) -> int | None:
        return self._process.exitcode

    def start(self) -> None:
        self._require_active_owner_call()
        if self._closed or self.pid is not None:
            raise PermissionError("the fixed worker may start only once")
        _GATE_PROCESS_START_DELEGATION[0] = self._process
        try:
            self._process.start()
            self.pid = self._process.pid
        finally:
            _GATE_PROCESS_START_DELEGATION[0] = None

    def is_alive(self) -> bool:
        self._require_active_owner_call()
        return self._process.is_alive()

    def join(self, timeout: float | None = None) -> None:
        self._require_active_owner_call()
        self._process.join(timeout=timeout)

    def terminate(self) -> None:
        self._require_active_owner_call()
        self._process.terminate()

    def close(self) -> None:
        self._require_active_owner_call()
        self._process.close()
        self._closed = True


class _GateObservedSpawnContext:
    """Allow exactly one synthetic worker over real context Process/Pipe APIs."""

    def __init__(self, context: Any, endpoints: list[Any], processes: list[Any]) -> None:
        self._context = context
        self._endpoints = endpoints
        self._processes = processes

    def Pipe(self, *, duplex: bool) -> tuple[Any, Any]:
        if _GATE_SYNTHETIC_CAPABILITY[0] is not True or duplex is not False or self._endpoints:
            raise PermissionError("only one synthetic one-way Pipe is allowed")
        _GATE_CONTEXT_PIPE_DELEGATION[0] = True
        try:
            pair = self._context.Pipe(duplex=duplex)
        finally:
            _GATE_CONTEXT_PIPE_DELEGATION[0] = False
        self._endpoints.extend(pair)
        return pair

    def Process(self, **kwargs: Any) -> Any:
        args = kwargs.get("args")
        now = time.monotonic()
        if (
            _GATE_SYNTHETIC_CAPABILITY[0] is not True
            or self._processes
            or set(kwargs) != {"target", "args", "name", "daemon"}
            or kwargs.get("target") is not globals().get("_root_fixed_signed_get_worker")
            or kwargs.get("name") != "th01-fixed-signed-read"
            or kwargs.get("daemon") is not True
            or type(args) is not tuple
            or len(args) != 7
            or len(self._endpoints) != 2
            or args[0] is not self._endpoints[1]
            or args[1] != "all_orders_in_window"
            or args[2] != globals().get("_GATE_EXPECTED_QUERY")
            or args[3] != GATE_SYNTHETIC_KEY
            or args[4] != GATE_SYNTHETIC_SECRET
            or args[5] != globals().get("_GATE_EXPECTED_HISTORY_START_MS")
            or type(args[6]) not in (int, float)
            or not now < float(args[6]) <= now + 7.5
        ):
            raise PermissionError("only the pinned synthetic worker invocation is allowed")
        _GATE_CONTEXT_PROCESS_DELEGATION[0] = True
        try:
            raw_process = self._context.Process(**kwargs)
        finally:
            _GATE_CONTEXT_PROCESS_DELEGATION[0] = False
        process = _GateObservedSpawnProcess(raw_process)
        self._processes.append(process)
        return process


def _root_local_synthetic_worker_gate() -> dict[str, Any]:
    """Callable RootTTY entry; returns one finite synthetic transport result."""
    global _GATE_ATTEMPTED, _GATE_EXPECTED_QUERY, _GATE_EXPECTED_HISTORY_START_MS
    global _GATE_ACTIVE_ENDPOINTS, _GATE_ACTIVE_PROCESSES, _GATE_SYNTHETIC_CAPABILITY
    global _GATE_SOURCE_GUARDS
    if _GATE_ATTEMPTED:
        return {
            "schema": "iteration41.binance.th01.spawn-pipe-gate.r1",
            "status": "BLOCKED_ALREADY_ATTEMPTED",
            "provider_call": False,
            "formal_case_pass": False,
        }
    _GATE_ATTEMPTED = True
    owner = globals()
    endpoints: list[Any] = []
    processes: list[Any] = []
    _GATE_ACTIVE_ENDPOINTS = endpoints
    _GATE_ACTIVE_PROCESSES = processes
    result: dict[str, Any] = {
        "schema": "iteration41.binance.th01.spawn-pipe-gate.r1",
        "status": "BLOCKED_SYNTHETIC_GATE",
        "first_failure": "synthetic_spawn_or_pipe_gate_failed",
        "provider_call": False,
        "account_full_snapshot_issued": False,
        "formal_case_pass": False,
        "evidence_level": "ROOT_LOCAL_SYNTHETIC_TRANSPORT_ONLY",
    }
    invoked_owner = False
    try:
        source_qa = owner.get("_GATE_SOURCE_QA")
        if not _gate_root_tty_ready():
            result["first_failure"] = "root_tty_required"
            return result
        if (
            type(source_qa) is not dict
            or source_qa.get("launcher_source_qa") is not True
            or _GATE_SOURCE_GUARDS is None
            or _gate_forbidden_native_modules_loaded()
            or owner.get("_ACTIVE_ROOT_FIXED_WORKERS") != []
            or not _gate_child_spawn_flags_safe()
        ):
            result["first_failure"] = "source_guard_or_clean_host_required"
            return result
        before = _gate_post_call_source_pins(owner)
        if not all(before.values()):
            result["first_failure"] = "pre_call_source_pins_failed"
            result["source_pins"] = before
            return result

        now_ms = int(time.time() * 1000)
        history_start_ms = now_ms - 60_000
        query = {
            "startTime": now_ms - 5000,
            "endTime": now_ms - 1000,
            "limit": 1000,
        }
        _GATE_EXPECTED_QUERY = dict(query)
        _GATE_EXPECTED_HISTORY_START_MS = history_start_ms
        _GATE_SYNTHETIC_CAPABILITY[0] = True
        invoked_owner = True
        try:
            outcome = owner["_run_root_fixed_signed_get"](
                "all_orders_in_window",
                query,
                GATE_SYNTHETIC_KEY,
                GATE_SYNTHETIC_SECRET,
                history_start_ms,
                time.monotonic() + 7.0,
            )
        finally:
            _GATE_SYNTHETIC_CAPABILITY[0] = False
        payload = json.loads(outcome.body.decode("ascii"))
        observed_pid = processes[0].pid if len(processes) == 1 else None
        checks = {
            "launcher_owner_candidate_source_bound": True,
            "child_executed_actual_worker": type(observed_pid) is int
            and observed_pid != os.getpid()
            and payload == [],
            "synthetic_http_200_complete": outcome.status == 200
            and outcome.complete is True
            and outcome.reason is None,
            "worker_exit_zero": outcome.worker_exit_code == 0,
            "single_frame_eof": outcome.pipe_eof is True,
            "no_forced_shutdown": outcome.forced_shutdown is False,
            "child_interactive_flag_excluded": _gate_child_spawn_flags_safe(),
            "real_pipe_endpoints_closed": len(endpoints) == 2
            and all(getattr(endpoint, "closed", False) is True for endpoint in endpoints),
            "real_spawn_process_closed": len(processes) == 1 and processes[0]._closed is True,
            "active_workers_zero": owner.get("_ACTIVE_ROOT_FIXED_WORKERS") == [],
        }
        if not all(checks.values()):
            result["checks"] = checks
            result["first_failure"] = "transport_lifecycle_check_failed"
        else:
            result = {
                "schema": "iteration41.binance.th01.spawn-pipe-gate.r1",
                "status": "ROOT_LOCAL_SYNTHETIC_GATE_PASSED",
                "checks": checks,
                "real_spawned_worker": True,
                "real_one_way_pipe": True,
                "synthetic_credentials_only": True,
                "outbound_socket_connect_denied": True,
                "private_paths_blocked": True,
                "external_native_api_imports_denied": True,
                "process_launch_allowlist": "fixed_synthetic_owner_worker",
                "provider_call": False,
                "account_full_snapshot_issued": False,
                "formal_case_pass": False,
                "evidence_level": "ROOT_LOCAL_SYNTHETIC_TRANSPORT_ONLY",
            }
    except BaseException:
        # Only fixed local categories are public; exception details can include
        # platform paths or request material and are deliberately discarded.
        result["first_failure"] = "synthetic_spawn_or_pipe_gate_failed"
    finally:
        _GATE_SYNTHETIC_CAPABILITY[0] = False
        if invoked_owner:
            post_pins = _gate_post_call_source_pins(owner)
            result["post_call_source_pins"] = post_pins
            result["post_call_source_pins_valid"] = all(post_pins.values())
            if not result["post_call_source_pins_valid"]:
                result["status"] = "BLOCKED_POST_CALL_SOURCE_PINS"
                result["first_failure"] = "post_call_source_pins_failed"
        uncertain = _gate_retain_owner_if_uncertain(owner, endpoints, processes)
        result["host_exit_forbidden"] = uncertain
        if uncertain:
            result["status"] = "BLOCKED_CLEANUP_UNCERTAIN"
            result["first_failure"] = "owner_worker_cleanup_uncertain"
            result["retained_owner_and_worker_references"] = True
        else:
            _GATE_ACTIVE_ENDPOINTS = None
            _GATE_ACTIVE_PROCESSES = None
            source_guards = _GATE_SOURCE_GUARDS
            if type(source_guards) is dict:
                _gate_restore_source_guards(source_guards)
                _GATE_SOURCE_GUARDS = None
            originals = owner.get("_GATE_NETWORK_ORIGINALS")
            if type(originals) is tuple:
                _gate_restore_transport(originals)
                owner["_GATE_NETWORK_ORIGINALS"] = None
    return result


def _gate_main(argv: list[str]) -> int:
    global _GATE_LAST_RESULT
    source_qa = globals().get("_GATE_SOURCE_QA")
    if argv == ["--qa-source-only"]:
        valid = type(source_qa) is dict and source_qa.get("launcher_source_qa") is True
        result = {
            "schema": "iteration41.binance.th01.spawn-pipe-gate.r1",
            "status": "SOURCE_ONLY_QA" if valid else "BLOCKED_SOURCE_QA",
            "launcher_owner_candidate_source_bound": valid,
            "protected_source_pins_checked": valid,
            "runtime_package_loaded": "backtrader_runtime" in sys.modules,
            "private_helper_loaded": "certification_roundtrip_private" in sys.modules,
            "protected_credential_read": False,
            "private_paths_blocked": _GATE_SOURCE_GUARDS is not None,
            "external_native_api_imports_denied": _GATE_SOURCE_GUARDS is not None,
            "process_launch_allowlist": "fixed_synthetic_owner_worker",
            "provider_read_started": False,
            "trading_write_started": False,
            "worker_spawned": False,
            "account_full_snapshot_issued": False,
            "formal_case_pass": False,
        }
        _GATE_LAST_RESULT = result
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0 if valid else 2
    if argv != ["--root-local-synthetic-worker-gate"]:
        result = {
            "schema": "iteration41.binance.th01.spawn-pipe-gate.r1",
            "status": "BLOCKED_UNSUPPORTED_INVOCATION",
            "formal_case_pass": False,
            "account_full_snapshot_issued": False,
        }
        _GATE_LAST_RESULT = result
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 2
    result = _root_local_synthetic_worker_gate()
    _GATE_LAST_RESULT = result
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result.get("status") == "ROOT_LOCAL_SYNTHETIC_GATE_PASSED" else 2


if __name__ in {"__main__", "__mp_main__"}:
    _GATE_SOURCE_GUARDS = _gate_install_source_guards()
    if _gate_forbidden_native_modules_loaded():
        raise SystemExit(2)
    _GATE_NETWORK_ORIGINALS = _gate_install_synthetic_transport()
    try:
        _GATE_SOURCE_QA = _gate_bootstrap_current_sources()
    except _GateBlocked:
        print(
            json.dumps(
                {
                    "schema": "iteration41.binance.th01.spawn-pipe-gate.r1",
                    "status": "BLOCKED_SOURCE_QA",
                    "launcher_qa_status": globals().get(
                        "_GATE_BOOTSTRAP_SAFE_QA_STATUS", "unclassified"
                    ),
                    "launcher_qa_flags": globals().get("_GATE_BOOTSTRAP_SAFE_QA_FLAGS", {}),
                    "bootstrap_stage": globals().get("_GATE_BOOTSTRAP_STAGE", "unknown"),
                    "private_inputs_read": False,
                    "provider_call": False,
                    "formal_case_pass": False,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        raise SystemExit(2)
else:
    _GATE_SOURCE_QA = None
    _GATE_NETWORK_ORIGINALS = None
    _GATE_SOURCE_GUARDS = None


if __name__ == "__main__":
    _GATE_MAIN_STATUS = _gate_main(sys.argv[1:])
    if _gate_exit_permitted():
        raise SystemExit(_GATE_MAIN_STATUS)
