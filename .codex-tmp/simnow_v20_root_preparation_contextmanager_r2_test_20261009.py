"""Narrow public source checks for the SimNow V20 R6/C2 wrapper repair."""

from __future__ import annotations

import ast
import builtins
import contextlib
import hashlib
import importlib.machinery
import importlib.util
import io
import json
import ntpath
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import threading
import time
import types
import typing
import unittest


ROOT = Path(r"D:\source_code\backtrader")
PREPARATION_PATH = ROOT / ".codex-tmp/simnow_v20_root_preparation_host_r6_20261009.py"
CALLER_PATH = ROOT / ".codex-tmp/simnow_v20_root_preparation_actual_caller_r2_20261009.py"
TEST_PATH = ROOT / ".codex-tmp/simnow_v20_root_preparation_contextmanager_r2_test_20261009.py"
PREPARATION_PIN = (
    24159,
    "02ac13bfd45c6ad94e0c8666bca4e05182a727eaf2449a1b21cb6b7b72be581f",
)
CALLER_PIN = (
    24722,
    "359fd47ec9bb9e516b73b51465b675c977ae045167580ebb0ed0cb3b846c8ad0",
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
PRECHECK_RELATIVE = (
    "docs/_internal/opts/requirements/"
    "迭代41-实盘执行风控监控与示例架构重构/evidence/"
    "iteration41-simnow-c01-v20-root-public-precheck-r2-bounded-2026-10-09/"
    "prepare_root_precheck.py"
)


def _read_pin(path: Path, pin: tuple[int, str]) -> bytes:
    raw = path.read_bytes()
    if len(raw) != pin[0] or hashlib.sha256(raw).hexdigest() != pin[1]:
        raise AssertionError("public_source_pin_mismatch")
    return raw


PREPARATION_RAW = _read_pin(PREPARATION_PATH, PREPARATION_PIN)
CALLER_RAW = _read_pin(CALLER_PATH, CALLER_PIN)
MANIFEST_PATH = ROOT.joinpath(*PurePosixPath(MANIFEST_RELATIVE).parts)
MANIFEST_RAW = _read_pin(MANIFEST_PATH, MANIFEST_PIN)
MANIFEST = json.loads(MANIFEST_RAW.decode("utf-8"))
ALLOWED_PUBLIC_PATHS = {
    MANIFEST_PATH.resolve(strict=True),
    ROOT.joinpath(*PurePosixPath(PRECHECK_RELATIVE).parts).resolve(strict=True),
    PREPARATION_PATH.resolve(strict=True),
    TEST_PATH.resolve(strict=True),
}
ALLOWED_PUBLIC_PATHS.update(
    ROOT.joinpath(*PurePosixPath(row["path"]).parts).resolve(strict=True)
    for row in MANIFEST["public_source_rows"]
)


def _guarded_path(path: object) -> Path:
    if not isinstance(path, (str, bytes, os.PathLike)):
        raise AssertionError("non_path_open_denied")
    resolved = Path(os.fsdecode(path)).resolve(strict=False)
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
        root in {"backtrader", "socket", "ssl", "urllib", "http", "ctypes", "_ctypes", "_winapi", "multiprocessing"}
        or root.startswith("win32")
        or root.startswith("bt_api_")
    ):
        raise AssertionError("candidate_import_denied")
    return _ORIGINAL_IMPORT(name, globals, locals, fromlist, level)


def _install_guards() -> None:
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
    for name in _ORIGINAL_OS_PROCESS:
        setattr(os, name, _deny_operation)
    sys.addaudithook(_audit_guard)


def _audit_guard(event: str, args: tuple[object, ...]) -> None:
    if event == "open" and args:
        _guarded_path(args[0])
    if (
        event.startswith(("socket.", "ctypes.", "_ctypes.", "_winapi.", "win32api."))
        or event in {"subprocess.Popen", "os.system", "os.fork", "os.exec", "os.spawn"}
    ):
        raise AssertionError("native_network_or_process_audit_denied")


def _compile_module(name: str, path: Path, raw: bytes) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__file__ = str(path)
    module.__package__ = ""
    module.__loader__ = None
    module.__spec__ = importlib.machinery.ModuleSpec(name, loader=None, origin=str(path))
    sys.modules[name] = module
    exec(compile(raw, str(path), "exec", dont_inherit=True), module.__dict__, module.__dict__)
    return module


def _cell(value: object):
    return (lambda: value).__closure__[0]


GOOD_SOURCE = b"""from contextlib import contextmanager\n@contextmanager\ndef held_public_sources():\n    yield None\n"""
BAD_SOURCES = {
    "malformed_closure": b"""import contextlib, types\ndef _generator():\n    yield None\ndef _cell(value):\n    return (lambda: value).__closure__[0]\n_wrapper = contextlib.contextmanager(_generator)\nheld_public_sources = types.FunctionType(_wrapper.__code__, _wrapper.__globals__, _wrapper.__name__, _wrapper.__defaults__, (_cell(object()),))\nheld_public_sources.__wrapped__ = _generator\n""",
    "foreign_generator_globals": b"""import contextlib, types\ndef _template():\n    yield None\n_foreign = types.FunctionType(_template.__code__, {'__builtins__': __builtins__}, '_template')\nheld_public_sources = contextlib.contextmanager(_foreign)\n""",
    "wrapper_code_tamper": b"""import contextlib\n@contextlib.contextmanager\ndef held_public_sources():\n    yield None\ndef _different_code():\n    marker = None\n    def helper(*args, **kwargs):\n        return marker\n    return helper.__code__\nheld_public_sources.__code__ = _different_code()\n""",
}


class SimNowContextmanagerRepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _install_guards()
        cls.caller = _compile_module(
            "_c01_simnow_v20_root_preparation_actual_caller_r2",
            CALLER_PATH,
            CALLER_RAW,
        )
        cls.prep = _compile_module(
            "_c01_simnow_v20_root_preparation_payload_r2",
            PREPARATION_PATH,
            PREPARATION_RAW,
        )
        cls.original_prep_constants = (
            cls.prep.CUV2_SOURCE_BYTES,
            cls.prep.CUV2_SOURCE_SHA256,
            cls.prep.CUV2_SOURCE_PATH,
        )
        cls.original_caller_constants = (
            cls.caller.CUV2_SOURCE_BYTES,
            cls.caller.CUV2_SOURCE_SHA256,
            cls.caller.CUV2_SOURCE_PATH,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        for name in (
            cls.caller.ROOT_CALLER_MODULE_NAME,
            cls.caller.PREPARATION_MODULE_NAME,
            cls.prep.PRECHECK_MODULE_NAME,
            cls.prep.CALLER_MODULE_NAME,
            cls.prep.DRIVER_MODULE_NAME,
            cls.caller.CUV2_MODULE_NAME,
        ):
            sys.modules.pop(name, None)

    def _driver(self) -> types.ModuleType:
        driver = types.ModuleType("_synthetic_driver_for_cuv2_test")
        driver.capture_c01_v20_driver_objects = lambda *_args, **_kwargs: None
        return driver

    def _set_synthetic_cuv2_pins(self, raw: bytes) -> None:
        digest = hashlib.sha256(raw).hexdigest()
        synthetic_path = "D:/synthetic/root-cuv2-contextmanager-fixture.py"
        self.prep.CUV2_SOURCE_BYTES = len(raw)
        self.prep.CUV2_SOURCE_SHA256 = digest
        self.prep.CUV2_SOURCE_PATH = synthetic_path
        self.caller.CUV2_SOURCE_BYTES = len(raw)
        self.caller.CUV2_SOURCE_SHA256 = digest
        self.caller.CUV2_SOURCE_PATH = synthetic_path

    def _lease_for(self, cuv2: types.ModuleType):
        held = cuv2.__dict__.get("held_public_sources")
        generator = getattr(held, "__wrapped__", None)
        generator_object = generator()
        return types.SimpleNamespace(
            cuv2_function=held,
            cuv2_function_code=getattr(held, "__code__", None),
            cuv2_function_globals=getattr(held, "__globals__", None),
            cuv2_generator_function=generator,
            cuv2_generator_code=getattr(generator, "__code__", None),
            cuv2_generator_globals=getattr(generator, "__globals__", None),
            generator=generator_object,
        )

    def test_real_bounded_precheck_runs_under_caller_import_guard_without_cuv2(self) -> None:
        original = builtins.__import__
        builtins.__import__ = self.caller._ImportGuard(original)
        try:
            precheck, prepared = self.prep._load_precheck(ROOT)
        finally:
            builtins.__import__ = original
        self.assertIs(precheck.__dict__["prepare_root_public_precheck"].__globals__, precheck.__dict__)
        summary = prepared.public_summary()
        self.assertEqual(summary["status"], "PUBLIC_SOURCE_PREFLIGHT_VERIFIED")
        self.assertEqual(summary["public_source_count"], 26)
        self.assertEqual(summary["software_source_count"], 3)
        for key in (
            "environment_values_read",
            "credential_values_read",
            "software_payloads_read",
            "cuv2_entered",
            "private_inputs_read",
            "windows_api_called",
            "child_process_created",
            "provider_called",
            "credential_free_gate_invoked",
            "activation_invoked",
            "formal_c01_pass",
        ):
            self.assertIs(summary[key], False)
        self.assertEqual(summary["official_c01_pass_count"], 0)

    def test_contextlib_wrapper_passes_exact_loader_and_root_postcheck(self) -> None:
        self._set_synthetic_cuv2_pins(GOOD_SOURCE)
        alias = self.caller.CUV2_MODULE_NAME
        sys.modules.pop(alias, None)
        cuv2 = self.prep._cu_v2_module(GOOD_SOURCE, self._driver())
        try:
            held = cuv2.held_public_sources
            generator = held.__wrapped__
            self.assertIs(held.__globals__, contextlib.__dict__)
            self.assertIsNot(held.__globals__, cuv2.__dict__)
            self.assertIs(generator.__globals__, cuv2.__dict__)
            self.assertFalse(held.__globals__ is cuv2.__dict__)  # R5/R1 predicate
            lease = self._lease_for(cuv2)
            self.assertTrue(self.caller._cuv2_postcheck_binding_valid(self.prep, cuv2, lease))
        finally:
            sys.modules.pop(alias, None)

    def test_exact_loader_and_root_postcheck_reject_wrapper_tampering(self) -> None:
        for label, raw in BAD_SOURCES.items():
            with self.subTest(binding=label):
                self._set_synthetic_cuv2_pins(raw)
                alias = self.caller.CUV2_MODULE_NAME
                sys.modules.pop(alias, None)
                with self.assertRaises(self.prep.RootPreparationError) as caught:
                    self.prep._cu_v2_module(raw, self._driver())
                self.assertEqual(caught.exception.code, "cuv2_function_binding_invalid")
                sys.modules.pop(alias, None)

                bad_module = _compile_module(alias, Path(self.caller.CUV2_SOURCE_PATH), raw)
                try:
                    self.assertFalse(
                        self.caller._cuv2_postcheck_binding_valid(
                            self.prep, bad_module, self._lease_for(bad_module)
                        )
                    )
                finally:
                    sys.modules.pop(alias, None)


if __name__ == "__main__":
    unittest.main(verbosity=2)
