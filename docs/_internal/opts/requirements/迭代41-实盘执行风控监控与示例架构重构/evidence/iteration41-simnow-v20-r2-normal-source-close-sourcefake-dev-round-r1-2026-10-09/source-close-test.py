"""Focused public-source-fake tests for the SimNow R2 source-lease close.

The exact pinned Root launch and caller run the production R6 preparation and
driver against an in-memory CUv2 module plus synthetic held bytes. No external
CUv2, Python executable/DLL, private input, native API, process, network,
provider, account, Gate, or retained host/session is used.
"""

from __future__ import annotations

import ast
import builtins
import contextlib
import ctypes
import hashlib
import importlib.abc
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path, PurePosixPath
import socket
import subprocess
import sys
import sysconfig
import unittest
import warnings
from types import MappingProxyType, ModuleType


ROOT = Path(r"D:\source_code\backtrader")
CALLER_RELATIVE = ".codex-tmp/simnow_v20_root_preparation_actual_caller_r2_20261009.py"
CALLER_PIN = (
    24722,
    "359fd47ec9bb9e516b73b51465b675c977ae045167580ebb0ed0cb3b846c8ad0",
)
PREPARATION_RELATIVE = ".codex-tmp/simnow_v20_root_preparation_host_r6_20261009.py"
PREPARATION_PIN = (
    24159,
    "02ac13bfd45c6ad94e0c8666bca4e05182a727eaf2449a1b21cb6b7b72be581f",
)
LAUNCH_RELATIVE = ".codex-tmp/simnow_v20_root_preparation_launch_r2_20261009.py"
LAUNCH_PIN = (
    5782,
    "9af785b32f1a807867789f70268c2580b43c032bcf2f7857ef4231a6a5ec7429",
)
HELPER_RELATIVE = ".codex-tmp/simnow_v20_r2_normal_source_close_root_20261009.py"
HELPER_PIN = (
    35246,
    "a42726bab6052e537e27df3349b1ac562138368190ebcf0646e15989c37a109e",
)
TEST_RELATIVE = ".codex-tmp/simnow_v20_r2_normal_source_close_root_test_20261009.py"
PRECHECK_RELATIVE = (
    "docs/_internal/opts/requirements/"
    "迭代41-实盘执行风控监控与示例架构重构/evidence/"
    "iteration41-simnow-c01-v20-root-public-precheck-r2-bounded-2026-10-09/"
    "prepare_root_precheck.py"
)
PRECHECK_PIN = (
    27892,
    "3f14a1ae6033717a8d05a90d7bade9ca0c96c6f7cfbea22c9f3176397fe066f6",
)
CORE_CALLER_RELATIVE = (
    "docs/_internal/opts/requirements/"
    "迭代41-实盘执行风控监控与示例架构重构/evidence/"
    "iteration41-simnow-c01-v20-root-credential-free-caller-r2-bounded-precheck-2026-10-09/"
    "run_root_credential_free_gate.py"
)
CORE_CALLER_PIN = (
    16708,
    "00c1485a89d91ade093ee353cf1dfd709026f83bcb8c1c4342161b5d22b4e5a4",
)
MANIFEST_RELATIVE = (
    "docs/_internal/opts/requirements/"
    "迭代41-实盘执行风控监控与示例架构重构/evidence/"
    "iteration41-simnow-c01-v20-credential-free-job-channel-r3-2026-10-09/"
    "runtime-source-pins.json"
)
MANIFEST_PIN = (
    9069,
    "e3e6940ba4799b6e783ef4227a07dd43d628ba74b96e5e958a6c7ffec3a6e387",
)
CUV2_FIXTURE_PATH = "D:/synthetic/simnow-v20-cuv2-fixture.py"
EXE_FIXTURE_PATH = "C:/synthetic/simnow-python-fixture.exe"
DLL_FIXTURE_PATH = "C:/synthetic/simnow-python-fixture.dll"
CALLER_MODULE_NAME = "_c01_simnow_v20_root_preparation_actual_caller_r2"
LAUNCH_MODULE_NAME = "_simnow_v20_r2_root_launch_source_fake"


def _pin_read(relative: str, pin: tuple[int, str]) -> bytes:
    raw = ROOT.joinpath(*PurePosixPath(relative).parts).read_bytes()
    if type(raw) is not bytes or len(raw) != pin[0] or hashlib.sha256(raw).hexdigest() != pin[1]:
        raise AssertionError("public_source_pin_mismatch")
    return raw


_CALLER_RAW = _pin_read(CALLER_RELATIVE, CALLER_PIN)
_PREPARATION_RAW = _pin_read(PREPARATION_RELATIVE, PREPARATION_PIN)
_LAUNCH_RAW = _pin_read(LAUNCH_RELATIVE, LAUNCH_PIN)
_PRECHECK_RAW = _pin_read(PRECHECK_RELATIVE, PRECHECK_PIN)
_CORE_CALLER_RAW = _pin_read(CORE_CALLER_RELATIVE, CORE_CALLER_PIN)
_MANIFEST_RAW = _pin_read(MANIFEST_RELATIVE, MANIFEST_PIN)
_MANIFEST = json.loads(_MANIFEST_RAW.decode("utf-8"))
_HELPER_PATH = ROOT.joinpath(*PurePosixPath(HELPER_RELATIVE).parts)
_ALLOWED_PUBLIC_PATHS = {
    ROOT.joinpath(*PurePosixPath(relative).parts).resolve(strict=True)
    for relative in (
        CALLER_RELATIVE,
        PREPARATION_RELATIVE,
        LAUNCH_RELATIVE,
        HELPER_RELATIVE,
        TEST_RELATIVE,
        PRECHECK_RELATIVE,
        CORE_CALLER_RELATIVE,
        MANIFEST_RELATIVE,
    )
}
_ALLOWED_PUBLIC_PATHS.update(
    ROOT.joinpath(*PurePosixPath(row["path"]).parts).resolve(strict=True)
    for row in _MANIFEST["public_source_rows"]
)
_GUARD_DIAGNOSTICS: list[str] = []
_LAST_PUBLIC_SOURCE_EXEC: str | None = None


def _guarded_path(value: object) -> Path:
    if not isinstance(value, (str, bytes, os.PathLike)):
        raise AssertionError("non_path_open_denied")
    path = Path(os.fsdecode(value)).resolve(strict=False)
    if path not in _ALLOWED_PUBLIC_PATHS:
        try:
            path.relative_to(ROOT.resolve(strict=True))
        except ValueError:
            try:
                path.relative_to(Path(sys.base_prefix).resolve(strict=True))
            except ValueError:
                _GUARD_DIAGNOSTICS.append("outside_root_open")
            else:
                _GUARD_DIAGNOSTICS.append("stdlib_open:" + path.stem)
        else:
            _GUARD_DIAGNOSTICS.append("repo_unlisted_open")
        raise AssertionError("non_public_or_software_open_denied")
    return path


def _deny_operation(*_args: object, **_kwargs: object) -> None:
    raise AssertionError("native_network_or_process_operation_denied")


_ORIGINAL_IMPORT = builtins.__import__
_ORIGINAL_PATH_OPEN = Path.open
_ORIGINAL_IO_OPEN = io.open
_ORIGINAL_BUILTIN_OPEN = builtins.open
_ORIGINAL_OS_OPEN = os.open
_ORIGINAL_SUBPROCESS = {
    name: getattr(subprocess, name)
    for name in ("Popen", "run", "call", "check_call", "check_output")
}
_ORIGINAL_SOCKET = {
    name: getattr(socket, name)
    for name in ("socket", "create_connection", "getaddrinfo", "getnameinfo")
    if hasattr(socket, name)
}
_ORIGINAL_CTYPES = {
    name: getattr(ctypes, name)
    for name in ("CDLL", "PyDLL", "WinDLL", "OleDLL")
    if hasattr(ctypes, name)
}
_ORIGINAL_OS_PROCESS = {
    name: getattr(os, name)
    for name in ("system", "startfile", "fork", "execv", "spawnv", "spawnve")
    if hasattr(os, name)
}


def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    root = name.partition(".")[0].casefold() if type(name) is str else ""
    if root in {"backtrader", "ssl", "http", "_winapi", "multiprocessing"} or root.startswith(
        ("win32", "bt_api_")
    ):
        _GUARD_DIAGNOSTICS.append("forbidden_import:" + root)
        raise AssertionError("candidate_import_denied")
    if root and root not in sys.modules:
        _GUARD_DIAGNOSTICS.append("new_import:" + root)
    return _ORIGINAL_IMPORT(name, globals, locals, fromlist, level)


def _audit_guard(event: str, args: tuple[object, ...]) -> None:
    if event == "open" and args:
        _guarded_path(args[0])
    if event.startswith(("socket.", "ctypes.", "_ctypes.", "_winapi.", "win32api.")) or event in {
        "subprocess.Popen",
        "os.system",
        "os.fork",
        "os.exec",
        "os.spawn",
    }:
        _GUARD_DIAGNOSTICS.append("protected_audit:" + event.split(".", 1)[0])
        raise AssertionError("native_network_or_process_audit_denied")


def _install_guards() -> None:
    warnings.filterwarnings("ignore", message=".*deprecated.*", category=DeprecationWarning)
    Path.open = lambda self, *a, **kw: _ORIGINAL_PATH_OPEN(_guarded_path(self), *a, **kw)  # type: ignore[method-assign]
    io.open = lambda file, *a, **kw: _ORIGINAL_IO_OPEN(_guarded_path(file), *a, **kw)  # type: ignore[assignment]
    builtins.open = lambda file, *a, **kw: _ORIGINAL_BUILTIN_OPEN(_guarded_path(file), *a, **kw)  # type: ignore[assignment]
    os.open = lambda path, *a, **kw: _ORIGINAL_OS_OPEN(str(_guarded_path(path)), *a, **kw)  # type: ignore[assignment]
    builtins.__import__ = _guarded_import
    for name in _ORIGINAL_SUBPROCESS:
        setattr(subprocess, name, _deny_operation)
    for name in _ORIGINAL_SOCKET:
        setattr(socket, name, _deny_operation)
    for name in _ORIGINAL_CTYPES:
        setattr(ctypes, name, _deny_operation)
    for name in _ORIGINAL_OS_PROCESS:
        setattr(os, name, _deny_operation)
    sys.addaudithook(_audit_guard)


def _fresh_bytes(raw: bytes) -> bytes:
    value = bytes(bytearray(raw))
    if type(value) is not bytes or value is raw or value != raw:
        raise AssertionError("synthetic_bytes_copy_invalid")
    return value


def _cuv2_source(*, mutate_alias_on_exit: bool) -> bytes:
    suffix = (
        "        if _TEST_MUTATE_ALIAS is not None:\n"
        "            sys.modules.pop(_TEST_MUTATE_ALIAS, None)\n"
        if mutate_alias_on_exit
        else "        _TEST_CLOSE_COUNT += 1\n"
    )
    if mutate_alias_on_exit:
        suffix = "        _TEST_CLOSE_COUNT += 1\n" + suffix
    source = (
        "import contextlib, sys, types\n"
        "_private = types.ModuleType('_root_public_custody_private')\n"
        "_TEST_HELD_RAW_MAP = {}\n"
        "_TEST_CLOSE_COUNT = 0\n"
        "_TEST_MUTATE_ALIAS = None\n"
        "@contextlib.contextmanager\n"
        "def held_public_sources(public_source_pins, software_source_pins):\n"
        "    global _TEST_CLOSE_COUNT\n"
        "    try:\n"
        "        yield _private, sys.modules[__name__], _TEST_HELD_RAW_MAP\n"
        "    finally:\n"
        + suffix
    )
    return source.encode("utf-8")


def _module(name: str, path: Path, raw: bytes) -> ModuleType:
    module = ModuleType(name)
    module.__file__ = str(path.resolve(strict=True))
    module.__package__ = ""
    module.__loader__ = None
    module.__spec__ = importlib.machinery.ModuleSpec(name, loader=None, origin=module.__file__)
    sys.modules[name] = module
    exec(compile(raw, module.__file__, "exec", dont_inherit=True), module.__dict__, module.__dict__)
    return module


class SimNowR2SourceCloseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if HELPER_PIN[0] and (len(_HELPER_PATH.read_bytes()) != HELPER_PIN[0] or hashlib.sha256(_HELPER_PATH.read_bytes()).hexdigest() != HELPER_PIN[1]):
            raise AssertionError("helper_source_pin_mismatch")
        # Load stdlib modules used by the exact production sources before the
        # import guard is installed. Candidate native/process leaves stay denied.
        for name in (
            "ast",
            "base64",
            "binascii",
            "collections.abc",
            "concurrent.futures",
            "concurrent.futures.thread",
            "contextlib",
            "copy",
            "csv",
            "ctypes.wintypes",
            "dataclasses",
            "datetime",
            "decimal",
            "enum",
            "hashlib",
            "importlib.machinery",
            "importlib.util",
            "importlib.abc",
            "ipaddress",
            "json",
            "math",
            "ntpath",
            "pathlib",
            "re",
            "secrets",
            "socket",
            "stat",
            "statistics",
            "statistics",
            "subprocess",
            "sysconfig",
            "threading",
            "time",
            "tokenize",
            "types",
            "typing",
            "unicodedata",
            "urllib.parse",
            "urllib.parse",
            "uuid",
        ):
            _ORIGINAL_IMPORT(name)
        _install_guards()

    def setUp(self) -> None:
        self.loaded_aliases: list[str] = []

    def tearDown(self) -> None:
        for name in self.loaded_aliases:
            sys.modules.pop(name, None)

    def _launch(self, *, mutate_alias_on_exit: bool = False) -> tuple[ModuleType, bytes]:
        self.loaded_aliases.extend(
            (
                LAUNCH_MODULE_NAME,
                CALLER_MODULE_NAME,
                "_c01_simnow_v20_root_preparation_payload_r2",
                "_c01_v20_root_public_precheck_r2",
                "_c01_v20_root_credential_free_caller_r2",
                "_c01_v20_root_actual_driver",
                "_root_public_custody_cli",
            )
        )
        cuv2_raw = _cuv2_source(mutate_alias_on_exit=mutate_alias_on_exit)
        cuv2_pin = hashlib.sha256(cuv2_raw).hexdigest()
        software_bytes = {
            CUV2_FIXTURE_PATH: cuv2_raw,
            EXE_FIXTURE_PATH: b"synthetic executable metadata only",
            # This is synthetic test data. It proves DLL bytes are not subject
            # to the public-source 2 MiB cap and is never read from disk.
            DLL_FIXTURE_PATH: b"synthetic-dll-byte-" * (120_000),
        }
        if len(software_bytes[DLL_FIXTURE_PATH]) <= 2 * 1024 * 1024:
            raise AssertionError("synthetic_dll_fixture_too_small")
        software_pins = MappingProxyType(
            {path: hashlib.sha256(raw).hexdigest() for path, raw in software_bytes.items()}
        )
        launch = ModuleType(LAUNCH_MODULE_NAME)
        launch.__file__ = str(ROOT.joinpath(*PurePosixPath(LAUNCH_RELATIVE).parts))
        launch.__package__ = ""
        launch.__loader__ = None
        sys.modules[LAUNCH_MODULE_NAME] = launch

        patched: set[str] = set()
        module_ast = ast.parse(_LAUNCH_RAW, filename=launch.__file__)
        cuv2_load_line = next(
            node.lineno
            for node in module_ast.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "root_cuv2_source_bytes"
                for target in node.targets
            )
        )

        def trace(frame, event, _arg):
            global _LAST_PUBLIC_SOURCE_EXEC
            if (
                event == "line"
                and frame.f_code.co_name == "_bind_public_modules"
                and type(frame.f_locals.get("relative")) is str
                and frame.f_locals.get("relative") != "scripts/iteration41_simnow_c01_v20_root_actual_driver_r3.py"
            ):
                _LAST_PUBLIC_SOURCE_EXEC = frame.f_locals["relative"]
            if frame.f_globals is launch.__dict__ and frame.f_code.co_name == "<module>":
                if event == "line" and frame.f_lineno == cuv2_load_line and "launch_cuv2" not in patched:
                    frame.f_globals["ROOT_CUV2_PATH"] = Path(CUV2_FIXTURE_PATH)
                    frame.f_globals["ROOT_CUV2_PIN"] = (len(cuv2_raw), cuv2_pin)
                    read_fixed = frame.f_globals["_root_read_fixed"]

                    def read_cuv2_fixture(path, expected, cap):
                        if path == frame.f_globals["ROOT_CUV2_PATH"]:
                            if expected != (len(cuv2_raw), cuv2_pin) or cap != 8 * 1024 * 1024:
                                raise AssertionError("synthetic_cuv2_read_contract_invalid")
                            return _fresh_bytes(cuv2_raw)
                        return read_fixed(path, expected, cap)

                    frame.f_globals["_root_read_fixed"] = read_cuv2_fixture
                    patched.add("launch_cuv2")
                return trace
            if event == "call" and frame.f_code.co_name == "prepare_once":
                frame.f_globals["CUV2_SOURCE_PATH"] = CUV2_FIXTURE_PATH
                frame.f_globals["CUV2_SOURCE_BYTES"] = len(cuv2_raw)
                frame.f_globals["CUV2_SOURCE_SHA256"] = cuv2_pin
                frame.f_globals["EXPECTED_SOFTWARE_SOURCE_PINS"] = dict(software_pins)
                patched.add("caller_constants")
                return trace
            if event == "call" and frame.f_code.co_name == "prepare_root_gate_host":
                if frame.f_globals.get("SCHEMA") != "iteration41-simnow-c01-v20-root-gate-host-preparation-r6":
                    return None
                return trace
            if event != "line" or frame.f_code.co_name != "prepare_root_gate_host":
                return trace

            prep_globals = frame.f_globals
            if "prep_constants" not in patched:
                prep_globals["CUV2_SOURCE_PATH"] = CUV2_FIXTURE_PATH
                prep_globals["CUV2_SOURCE_BYTES"] = len(cuv2_raw)
                prep_globals["CUV2_SOURCE_SHA256"] = cuv2_pin
                patched.add("prep_constants")

            prepared = frame.f_locals.get("prepared")
            if prepared is not None and "software_precheck" not in patched:
                object.__setattr__(prepared, "software_source_pins", software_pins)
                patched.add("software_precheck")

            driver = frame.f_locals.get("driver")
            if driver is not None and "driver_objects" not in patched:
                driver.__dict__["CUV2_SOURCE_PATH"] = CUV2_FIXTURE_PATH
                driver.__dict__["CUV2_SOURCE_BYTES"] = len(cuv2_raw)
                driver.__dict__["CUV2_SOURCE_SHA256"] = cuv2_pin
                object.__setattr__(prepared, "driver_objects", driver.capture_c01_v20_driver_objects(driver))
                patched.add("driver_objects")

            core_caller = frame.f_locals.get("caller_module")
            if core_caller is not None and "core_caller_pins" not in patched:
                core_caller.__dict__["EXPECTED_SOFTWARE_PINS"] = software_pins
                patched.add("core_caller_pins")

            cuv2 = frame.f_locals.get("cuv2_module")
            if cuv2 is not None and "cuv2_rows" not in patched:
                root = driver._source_root_for_driver()
                held_map = {
                    driver._absolute_public_path(root, path): _fresh_bytes(raw)
                    for path, raw in prepared.public_source_bytes.items()
                }
                held_map.update(
                    {
                        driver._normalize_absolute_path(path): _fresh_bytes(raw)
                        for path, raw in software_bytes.items()
                    }
                )
                cuv2.__dict__["_TEST_HELD_RAW_MAP"] = held_map
                patched.add("cuv2_rows")
            return trace

        try:
            sys.settrace(trace)
            exec(compile(_LAUNCH_RAW, launch.__file__, "exec", dont_inherit=True), launch.__dict__, launch.__dict__)
        finally:
            sys.settrace(None)
        expected_patches = {
            "launch_cuv2",
            "caller_constants",
            "prep_constants",
            "software_precheck",
            "driver_objects",
            "core_caller_pins",
            "cuv2_rows",
        }
        if patched != expected_patches:
            exception = launch.ROOT_PREPARATION_LAUNCH_STATE.get("_exception")
            raise AssertionError(
                "faithful_launch_fixture_incomplete:patches="
                + ",".join(sorted(patched))
                + ":exception="
                + str(getattr(exception, "code", type(exception).__name__ if exception else "none"))
                + ":phase="
                + str(launch.ROOT_PREPARATION_LAUNCH_STATE.get("summary", {}).get("phase"))
                + ":source="
                + str(_LAST_PUBLIC_SOURCE_EXEC)
                + ":guard="
                + ",".join(_GUARD_DIAGNOSTICS[-3:])
            )
        caller = launch.__dict__["root_simnow_v20_caller_module_r2"]
        attempt = caller.__dict__["_ATTEMPTS"][0]
        exception = launch.ROOT_PREPARATION_LAUNCH_STATE.get("_exception")
        if (
            launch.ROOT_PREPARATION_LAUNCH_STATE["phase"] != "preparation_exception_retained"
            or launch.ROOT_PREPARATION_LAUNCH_STATE["invocation_count"] != 1
            or launch.ROOT_PREPARATION_LAUNCH_STATE["source_phase"] != "prepare_once_entry"
            or attempt.phase != "postbinding_checks"
            or attempt.status != "PREPARATION_EXCEPTION_PROPAGATED"
            or getattr(exception, "code", None) != "public_source_binding_invalid"
            or attempt.host is None
            or attempt.host.lease.state != "entered"
            or attempt.host.lease.exit_started is not False
            or attempt.host.lease.parent_process_receipt is not None
            or attempt.host._used is not False
            or attempt.host._result is not None
        ):
            raise AssertionError(
                "r2_consumed_failure_fixture_not_reproduced:"
                + str(getattr(exception, "code", type(exception).__name__ if exception else "none"))
                + ":phase="
                + str(launch.ROOT_PREPARATION_LAUNCH_STATE.get("summary", {}).get("phase"))
                + ":host_lease="
                + str(
                    getattr(
                        getattr(getattr(attempt, "host", None), "lease", None),
                        "state",
                        "none",
                    )
                )
                + ":patches="
                + ",".join(sorted(patched))
                + ":source="
                + str(_LAST_PUBLIC_SOURCE_EXEC)
                + ":guard="
                + ",".join(_GUARD_DIAGNOSTICS[-3:])
            )
        for name, module in attempt.host.source_modules.items():
            if type(name) is str and sys.modules.get(name) is module:
                self.loaded_aliases.append(name)
        return launch, cuv2_raw

    def _load_helper(self, launch: ModuleType) -> None:
        helper_raw = _pin_read(HELPER_RELATIVE, HELPER_PIN) if HELPER_PIN[0] else _HELPER_PATH.read_bytes()
        if HELPER_PIN[0] and hashlib.sha256(helper_raw).hexdigest() != HELPER_PIN[1]:
            raise AssertionError("helper_source_pin_mismatch")
        exec(
            compile(helper_raw, str(_HELPER_PATH), "exec", dont_inherit=True),
            launch.__dict__,
            launch.__dict__,
        )

    def test_normal_close_runs_production_postverify_and_preserves_r2_objects(self) -> None:
        launch, _ = self._launch()
        self._load_helper(launch)
        state = launch.ROOT_PREPARATION_LAUNCH_STATE
        caller = launch.root_simnow_v20_caller_module_r2
        attempt = caller._ATTEMPTS[0]
        host = attempt.host
        lease = host.lease
        summary = state["summary"]
        exception = state["_exception"]
        attempts = caller._ATTEMPTS
        keepalive = lease.keepalive_container_ref
        cuv2 = host.cuv2_module

        result = launch.simnow_v20_r2_close_source_lease_once()

        self.assertEqual(
            result["status"],
            "SOURCE_SCOPE_NORMAL_CLOSE_RETURNED",
            msg="finite close projection: " + repr(result),
        )
        self.assertIs(result["credential_free_gate_invoked"], False)
        self.assertIs(result["formal_c01_pass"], False)
        self.assertIs(lease.state, "closed")
        self.assertIs(lease.exit_started, True)
        self.assertIs(lease.close_result, False)
        self.assertIsNone(lease.generator.gi_frame)
        self.assertEqual(cuv2._TEST_CLOSE_COUNT, 1)
        self.assertEqual(keepalive, [])
        self.assertIs(state["summary"], summary)
        self.assertIs(state["_exception"], exception)
        self.assertNotIn("root_simnow_v20_preparation_exception_r2", launch.__dict__)
        self.assertIs(caller._ATTEMPTS, attempts)
        self.assertIs(attempts[0], attempt)
        self.assertEqual(attempt.phase, "postbinding_checks")
        self.assertEqual(attempt.status, "PREPARATION_EXCEPTION_PROPAGATED")
        self.assertIs(attempt.postbinding_verified, False)
        self.assertEqual(summary["phase"], "postbinding_checks")
        self.assertIs(summary["postbinding_verified"], False)
        self.assertIsNone(lease.parent_process_receipt)
        self.assertIs(host._used, False)
        self.assertIsNone(host._result)

    def test_precheck_rejection_does_not_enter_exit(self) -> None:
        launch, _ = self._launch()
        self._load_helper(launch)
        caller = launch.root_simnow_v20_caller_module_r2
        attempt = caller._ATTEMPTS[0]
        host = attempt.host
        lease = host.lease
        keepalive = lease.keepalive_container_ref
        relative = next(iter(lease.public_source_pins))
        alias = attempt.preparation_module._module_name_for(relative, caller.DRIVER_RELATIVE)
        original = sys.modules[alias]
        sys.modules[alias] = ModuleType("_synthetic_wrong_public_alias")
        try:
            result = launch.simnow_v20_r2_close_source_lease_once()
        finally:
            sys.modules[alias] = original

        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["phase"], "precheck")
        self.assertIs(result["exit_invoked"], False)
        self.assertIs(lease.state, "entered")
        self.assertIs(lease.exit_started, False)
        self.assertIsNone(lease.close_result)
        self.assertEqual(len(keepalive), 1)
        self.assertIs(keepalive[0], lease.keepalive_ref)
        self.assertEqual(host.cuv2_module._TEST_CLOSE_COUNT, 0)

    def test_postclose_uncertainty_retains_one_shot_reference(self) -> None:
        launch, _ = self._launch(mutate_alias_on_exit=True)
        self._load_helper(launch)
        caller = launch.root_simnow_v20_caller_module_r2
        attempt = caller._ATTEMPTS[0]
        host = attempt.host
        lease = host.lease
        keepalive = lease.keepalive_container_ref
        cuv2 = host.cuv2_module
        alias_path = next(path for path in lease.public_source_pins if path != caller.DRIVER_RELATIVE)
        alias = attempt.preparation_module._module_name_for(alias_path, caller.DRIVER_RELATIVE)
        cuv2._TEST_MUTATE_ALIAS = alias

        first = launch.simnow_v20_r2_close_source_lease_once()
        second = launch.simnow_v20_r2_close_source_lease_once()

        self.assertEqual(first["status"], "BLOCKED")
        self.assertEqual(first["phase"], "postverify")
        self.assertIs(first["exit_invoked"], True)
        self.assertIs(first["retained_reference"], True)
        self.assertEqual(second["status"], "BLOCKED")
        self.assertIs(second["exit_invoked"], False)
        self.assertIs(lease.state, "uncertain")
        self.assertIs(lease.exit_started, True)
        self.assertIs(lease.close_result, False)
        self.assertEqual(cuv2._TEST_CLOSE_COUNT, 1)
        self.assertEqual(len(keepalive), 1)
        self.assertIs(keepalive[0], lease.keepalive_ref)
        self.assertIsNone(lease.generator.gi_frame)


if __name__ == "__main__":
    unittest.main(verbosity=2)
