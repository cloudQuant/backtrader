"""Faithful public-only R3 preparation caller regression.

The test runs the exact R6 preparation source and exact R3 caller against a
synthetic canonical CUv2 contextmanager. The synthetic holder returns fresh
byte objects with the same public source content as the independently bounded
precheck read. No external CUv2, interpreter, DLL, private, SDK, native,
network, process, provider, account, or Gate operation is performed.
"""

from __future__ import annotations

import builtins
import ast
import base64
import binascii
import contextlib
import copy
import csv
import ctypes
from ctypes import wintypes
from concurrent.futures import ThreadPoolExecutor
import dataclasses
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.machinery
import importlib.util
import importlib.abc
from collections.abc import Mapping
import io
import ipaddress
import json
import math
import ntpath
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import socket
import stat
import subprocess
import sys
import sysconfig
import threading
import time
import tokenize
import types
import typing
import unicodedata
import uuid
import unittest
from types import MappingProxyType, ModuleType
import warnings
from decimal import Decimal, InvalidOperation, localcontext
from statistics import median
from urllib.parse import urlsplit


ROOT = Path(r"D:\source_code\backtrader")
CALLER_PATH = ROOT / ".codex-tmp/simnow_v20_root_preparation_actual_caller_r3_20261009.py"
PREPARATION_PATH = ROOT / ".codex-tmp/simnow_v20_root_preparation_host_r6_20261009.py"
TEST_PATH = ROOT / ".codex-tmp/simnow_v20_root_preparation_actual_caller_r3_test_20261009.py"
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
PREPARATION_PIN = (
    24159,
    "02ac13bfd45c6ad94e0c8666bca4e05182a727eaf2449a1b21cb6b7b72be581f",
)
CALLER_PIN = (
    25011,
    "12e7009e6e6e794c377bd9811701596929bdfb86676509bc6bd10ab4c0ba4dda",
)
MANIFEST_PATH = ROOT.joinpath(*PurePosixPath(MANIFEST_RELATIVE).parts)


def _read_pin(path: Path, pin: tuple[int, str]) -> bytes:
    raw = path.read_bytes()
    if len(raw) != pin[0] or hashlib.sha256(raw).hexdigest() != pin[1]:
        raise AssertionError("public_source_pin_mismatch")
    return raw


MANIFEST_RAW = _read_pin(MANIFEST_PATH, MANIFEST_PIN)
MANIFEST = json.loads(MANIFEST_RAW.decode("utf-8"))
ALLOWED_PUBLIC_PATHS = {
    path.resolve(strict=True)
    for path in (
        CALLER_PATH,
        PREPARATION_PATH,
        TEST_PATH,
        MANIFEST_PATH,
        ROOT.joinpath(*PurePosixPath(PRECHECK_RELATIVE).parts),
        ROOT.joinpath(*PurePosixPath(CORE_CALLER_RELATIVE).parts),
    )
}
ALLOWED_PUBLIC_PATHS.update(
    ROOT.joinpath(*PurePosixPath(row["path"]).parts).resolve(strict=True)
    for row in MANIFEST["public_source_rows"]
)


def _guarded_path(value: object) -> Path:
    if not isinstance(value, (str, bytes, os.PathLike)):
        raise AssertionError("non_path_open_denied")
    resolved = Path(os.fsdecode(value)).resolve(strict=False)
    if resolved not in ALLOWED_PUBLIC_PATHS:
        raise AssertionError("non_public_or_software_open_denied")
    return resolved


def _deny_operation(*_args: object, **_kwargs: object) -> None:
    raise AssertionError("native_network_or_process_operation_denied")


_ORIGINAL_IMPORT = builtins.__import__
_ORIGINAL_PATH_OPEN = Path.open
_ORIGINAL_IO_OPEN = io.open
_ORIGINAL_BUILTIN_OPEN = builtins.open
_ORIGINAL_OS_OPEN = os.open
_ORIGINAL_CTYPES_NATIVE = {
    name: getattr(ctypes, name)
    for name in ("CDLL", "PyDLL", "WinDLL", "OleDLL")
    if hasattr(ctypes, name)
}
_ORIGINAL_SOCKET_OPERATIONS = {
    name: getattr(socket, name)
    for name in (
        "socket",
        "create_connection",
        "getaddrinfo",
        "getnameinfo",
        "gethostbyname",
        "gethostbyaddr",
    )
    if hasattr(socket, name)
}
_ORIGINAL_SUBPROCESS = {
    name: getattr(subprocess, name)
    for name in ("Popen", "run", "call", "check_call", "check_output")
}
_ORIGINAL_OS_PROCESS = {
    name: getattr(os, name)
    for name in ("system", "startfile", "fork", "execv", "spawnv", "spawnve")
    if hasattr(os, name)
}


def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    root = name.partition(".")[0].casefold() if type(name) is str else ""
    if (
        root
        in {
            "backtrader",
            "ssl",
            "http",
            "_winapi",
            "multiprocessing",
        }
        or root.startswith(("win32", "bt_api_"))
    ):
        raise AssertionError("candidate_import_denied")
    return _ORIGINAL_IMPORT(name, globals, locals, fromlist, level)


def _audit_guard(event: str, args: tuple[object, ...]) -> None:
    if event == "open" and args:
        _guarded_path(args[0])
    if (
        event.startswith(("socket.", "ctypes.", "_ctypes.", "_winapi.", "win32api."))
        or event in {"subprocess.Popen", "os.system", "os.fork", "os.exec", "os.spawn"}
    ):
        raise AssertionError("native_network_or_process_audit_denied")


def _install_guards() -> None:
    warnings.filterwarnings(
        "ignore",
        message="'importlib.abc.TraversableResources' is deprecated.*",
        category=DeprecationWarning,
    )
    Path.open = lambda self, *args, **kwargs: _ORIGINAL_PATH_OPEN(  # type: ignore[method-assign]
        _guarded_path(self), *args, **kwargs
    )
    io.open = lambda file, *args, **kwargs: _ORIGINAL_IO_OPEN(  # type: ignore[assignment]
        _guarded_path(file), *args, **kwargs
    )
    builtins.open = lambda file, *args, **kwargs: _ORIGINAL_BUILTIN_OPEN(  # type: ignore[assignment]
        _guarded_path(file), *args, **kwargs
    )
    os.open = lambda path, *args, **kwargs: _ORIGINAL_OS_OPEN(  # type: ignore[assignment]
        str(_guarded_path(path)), *args, **kwargs
    )
    builtins.__import__ = _guarded_import
    for name in _ORIGINAL_SUBPROCESS:
        setattr(subprocess, name, _deny_operation)
    for name in _ORIGINAL_CTYPES_NATIVE:
        setattr(ctypes, name, _deny_operation)
    for name in _ORIGINAL_SOCKET_OPERATIONS:
        setattr(socket, name, _deny_operation)
    for name in _ORIGINAL_OS_PROCESS:
        setattr(os, name, _deny_operation)
    sys.addaudithook(_audit_guard)


def _compile_module(name: str, path: Path, raw: bytes) -> ModuleType:
    module = ModuleType(name)
    module.__file__ = str(path.resolve(strict=True))
    module.__package__ = ""
    module.__loader__ = None
    module.__spec__ = importlib.machinery.ModuleSpec(name, loader=None, origin=module.__file__)
    sys.modules[name] = module
    exec(compile(raw, module.__file__, "exec", dont_inherit=True), module.__dict__, module.__dict__)
    return module


def _fresh_clone(raw: bytes) -> bytes:
    cloned = bytes(bytearray(raw))
    if type(cloned) is not bytes or cloned is raw or cloned != raw:
        raise AssertionError("synthetic_hold_copy_invalid")
    return cloned


class SimNowActualCallerR3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if CALLER_PIN[0] <= 0:
            raise AssertionError("caller_pin_not_frozen")
        cls.caller_raw = _read_pin(CALLER_PATH, CALLER_PIN)
        cls.preparation_raw = _read_pin(PREPARATION_PATH, PREPARATION_PIN)
        _read_pin(ROOT.joinpath(*PurePosixPath(PRECHECK_RELATIVE).parts), PRECHECK_PIN)
        _read_pin(ROOT.joinpath(*PurePosixPath(CORE_CALLER_RELATIVE).parts), CORE_CALLER_PIN)
        _install_guards()
        cls.caller = _compile_module(
            "_c01_simnow_v20_root_preparation_actual_caller_r3",
            CALLER_PATH,
            cls.caller_raw,
        )
        cls.prep_reference = _compile_module(
            "_simnow_v20_root_preparation_payload_r6_fixture",
            PREPARATION_PATH,
            cls.preparation_raw,
        )
        cls.reference_precheck, cls.reference_prepared = cls.prep_reference._load_precheck(ROOT)
        cls.driver_reference = cls.reference_prepared.driver_module
        cls.synthetic_cuv2_path = "D:/synthetic/simnow-v20-cuv2-fixture.py"
        cls.synthetic_exe_path = "C:/synthetic/simnow-python-fixture.exe"
        cls.synthetic_dll_path = "C:/synthetic/simnow-python-fixture.dll"
        cls.cuv2_raw = (
            b"import contextlib, sys, types\n"
            b"_private = types.ModuleType('_root_public_custody_private')\n"
            b"@contextlib.contextmanager\n"
            b"def held_public_sources(public_source_pins, software_source_pins):\n"
            b"    yield _private, sys.modules[__name__], _TEST_HELD_RAW_MAP\n"
        )
        cls.synthetic_software_bytes = {
            cls.synthetic_cuv2_path: cls.cuv2_raw,
            cls.synthetic_exe_path: b"synthetic-executable-metadata-only",
            cls.synthetic_dll_path: b"synthetic-runtime-dll-metadata-only",
        }
        cls.synthetic_software_pins = MappingProxyType(
            {
                path: hashlib.sha256(raw).hexdigest()
                for path, raw in cls.synthetic_software_bytes.items()
            }
        )
        cls.cuv2_sha256 = hashlib.sha256(cls.cuv2_raw).hexdigest()
        if len(cls.synthetic_software_bytes[cls.synthetic_cuv2_path]) == 0:
            raise AssertionError("synthetic_cuv2_metadata_invalid")
        cls.held_raw_map = {}
        driver = cls.driver_reference
        source_root = driver._source_root_for_driver()
        for relative, raw in cls.reference_prepared.public_source_bytes.items():
            cloned = _fresh_clone(raw)
            absolute = driver._absolute_public_path(source_root, relative)
            cls.held_raw_map[absolute] = cloned
        for path, raw in cls.synthetic_software_bytes.items():
            cloned = _fresh_clone(raw)
            cls.held_raw_map[driver._normalize_absolute_path(path)] = cloned
        if len(cls.held_raw_map) != 29:
            raise AssertionError("synthetic_hold_map_count_invalid")

    @classmethod
    def tearDownClass(cls) -> None:
        for name in (
            cls.caller.ROOT_CALLER_MODULE_NAME,
            cls.caller.CUV2_MODULE_NAME,
            cls.prep_reference.DRIVER_MODULE_NAME,
            cls.prep_reference.PRECHECK_MODULE_NAME,
            cls.prep_reference.CALLER_MODULE_NAME,
            "_simnow_v20_root_preparation_payload_r6_fixture",
        ):
            sys.modules.pop(name, None)

    def test_full_r6_entry_and_r3_postcheck_accept_distinct_equal_public_reads(self) -> None:
        caller = self.caller
        fake_software = self.synthetic_software_pins
        caller.CUV2_SOURCE_PATH = self.synthetic_cuv2_path
        caller.CUV2_SOURCE_BYTES = len(self.cuv2_raw)
        caller.CUV2_SOURCE_SHA256 = self.cuv2_sha256
        caller.EXPECTED_SOFTWARE_SOURCE_PINS = fake_software

        patched: set[str] = set()

        def trace(frame, event, _arg):
            if event == "call":
                if (
                    frame.f_code.co_name == "prepare_root_gate_host"
                    and frame.f_globals.get("SCHEMA")
                    == "iteration41-simnow-c01-v20-root-gate-host-preparation-r6"
                ):
                    return trace
                return None
            if event != "line" or frame.f_code.co_name != "prepare_root_gate_host":
                return trace

            prep_globals = frame.f_globals
            if "r6_constants" not in patched:
                prep_globals["CUV2_SOURCE_PATH"] = self.synthetic_cuv2_path
                prep_globals["CUV2_SOURCE_BYTES"] = len(self.cuv2_raw)
                prep_globals["CUV2_SOURCE_SHA256"] = self.cuv2_sha256
                patched.add("r6_constants")

            prepared = frame.f_locals.get("prepared")
            if prepared is not None and "precheck_software" not in patched:
                object.__setattr__(prepared, "software_source_pins", fake_software)
                patched.add("precheck_software")

            driver = frame.f_locals.get("driver")
            if driver is not None and "driver_constants" not in patched:
                driver.__dict__["CUV2_SOURCE_PATH"] = self.synthetic_cuv2_path
                driver.__dict__["CUV2_SOURCE_BYTES"] = len(self.cuv2_raw)
                driver.__dict__["CUV2_SOURCE_SHA256"] = self.cuv2_sha256
                object.__setattr__(
                    prepared,
                    "driver_objects",
                    driver.capture_c01_v20_driver_objects(driver),
                )
                patched.add("driver_constants")

            caller_module = frame.f_locals.get("caller_module")
            if caller_module is not None and "core_caller_software" not in patched:
                caller_module.__dict__["EXPECTED_SOFTWARE_PINS"] = fake_software
                patched.add("core_caller_software")

            cuv2_module = frame.f_locals.get("cuv2_module")
            if cuv2_module is not None and "cuv2_rows" not in patched:
                cuv2_module.__dict__["_TEST_HELD_RAW_MAP"] = self.held_raw_map
                patched.add("cuv2_rows")
            return trace

        sys.settrace(trace)
        try:
            attempt = caller.prepare_once(self.cuv2_raw)
        finally:
            sys.settrace(None)

        self.assertEqual(
            patched,
            {
                "r6_constants",
                "precheck_software",
                "driver_constants",
                "core_caller_software",
                "cuv2_rows",
            },
        )
        summary = attempt.public_summary()
        self.assertEqual(summary["status"], "ROOT_GATE_HOST_PREPARED")
        self.assertEqual(summary["public_source_count"], 26)
        self.assertEqual(summary["software_pin_metadata_count"], 3)
        self.assertIs(summary["postbinding_verified"], True)
        self.assertIs(summary["gate_invoked_by_caller"], False)
        self.assertIs(summary["activation_started_observed"], False)

        host = attempt.host
        lease = host.lease
        prepared = host.prepared_precheck
        for path, digest in prepared.public_source_pins.items():
            precheck_raw = prepared.public_source_bytes[path]
            held_raw = lease.held_source_bytes[path]
            self.assertIsNot(precheck_raw, held_raw)
            self.assertEqual(precheck_raw, held_raw)
            self.assertEqual(hashlib.sha256(held_raw).hexdigest(), digest)
            self.assertIs(host.source_bytes[path], held_raw)

        original_held = lease.held_source_bytes
        changed = dict(original_held)
        first_path = next(iter(changed))
        changed_raw = bytearray(changed[first_path])
        changed_raw[0] ^= 1
        changed[first_path] = bytes(changed_raw)
        object.__setattr__(lease, "held_source_bytes", MappingProxyType(changed))
        with self.assertRaises(caller.RootPreparationCallerError) as caught:
            caller._postcheck(attempt, self.cuv2_raw)
        self.assertEqual(caught.exception.code, "entered_precheck_binding_invalid")
        object.__setattr__(lease, "held_source_bytes", original_held)

        alias_path = next(path for path in prepared.public_source_pins if path != caller.DRIVER_RELATIVE)
        module_name = attempt.preparation_module._module_name_for(
            alias_path, caller.DRIVER_RELATIVE
        )
        original_module = sys.modules[module_name]
        foreign_module = ModuleType("_synthetic_foreign_public_alias")
        sys.modules[module_name] = foreign_module
        try:
            with self.assertRaises(caller.RootPreparationCallerError) as caught:
                caller._postcheck(attempt, self.cuv2_raw)
            self.assertEqual(caught.exception.code, "public_source_binding_invalid")
        finally:
            sys.modules[module_name] = original_module

        caller._postcheck(attempt, self.cuv2_raw)
        self.assertIs(attempt.postbinding_verified, True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
