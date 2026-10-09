"""Three-case guarded Root source QA for the frozen SimNow R2 source close.

This harness imports only preloaded stdlib modules, validates bounded public
source pins, installs its outer guards and guard selfchecks, then runs exactly
the faithful synthetic R6-entry/R2-close unittests. It never reads CUv2,
Python executable, DLL, credential, provider, or account payload bytes and
does not launch pytest, a process, a Gate, or an activation.
"""

from __future__ import annotations

import ast
import builtins
import ctypes
import hashlib
import importlib
import importlib.util
import io
import json
import os
from pathlib import Path, PurePosixPath
import socket
import subprocess
import sys
import sysconfig
import types
import unittest
from collections import Counter
from typing import Any
import warnings


ROOT = Path(r"D:\source_code\backtrader")
HARNESS_PATH = ROOT / ".codex-tmp/simnow_v20_r2_normal_source_close_root_focused_qa_r1_20261009.py"
RESULT_PATH = ROOT / ".codex-tmp/simnow_v20_r2_normal_source_close_root_focused_qa_r1_result_20261009.json"
MAX_PUBLIC_BYTES = 2 * 1024 * 1024

CALLER_RELATIVE = ".codex-tmp/simnow_v20_root_preparation_actual_caller_r2_20261009.py"
CALLER_PIN = (24722, "359fd47ec9bb9e516b73b51465b675c977ae045167580ebb0ed0cb3b846c8ad0")
TEST_RELATIVE = ".codex-tmp/simnow_v20_r2_normal_source_close_root_test_20261009.py"
TEST_PIN = (26165, "7978e86158ef8443915556dc0fa9b93d6b737e23ecb1f33115515aec0ba0e959")
PREPARATION_RELATIVE = ".codex-tmp/simnow_v20_root_preparation_host_r6_20261009.py"
PREPARATION_PIN = (24159, "02ac13bfd45c6ad94e0c8666bca4e05182a727eaf2449a1b21cb6b7b72be581f")
LAUNCH_RELATIVE = ".codex-tmp/simnow_v20_root_preparation_launch_r2_20261009.py"
LAUNCH_PIN = (5782, "9af785b32f1a807867789f70268c2580b43c032bcf2f7857ef4231a6a5ec7429")
HELPER_RELATIVE = ".codex-tmp/simnow_v20_r2_normal_source_close_root_20261009.py"
HELPER_PIN = (35246, "a42726bab6052e537e27df3349b1ac562138368190ebcf0646e15989c37a109e")
PRECHECK_RELATIVE = (
    "docs/_internal/opts/requirements/"
    "迭代41-实盘执行风控监控与示例架构重构/evidence/"
    "iteration41-simnow-c01-v20-root-public-precheck-r2-bounded-2026-10-09/"
    "prepare_root_precheck.py"
)
PRECHECK_PIN = (27892, "3f14a1ae6033717a8d05a90d7bade9ca0c96c6f7cfbea22c9f3176397fe066f6")
CORE_CALLER_RELATIVE = (
    "docs/_internal/opts/requirements/"
    "迭代41-实盘执行风控监控与示例架构重构/evidence/"
    "iteration41-simnow-c01-v20-root-credential-free-caller-r2-bounded-precheck-2026-10-09/"
    "run_root_credential_free_gate.py"
)
CORE_CALLER_PIN = (16708, "00c1485a89d91ade093ee353cf1dfd709026f83bcb8c1c4342161b5d22b4e5a4")
MANIFEST_RELATIVE = (
    "docs/_internal/opts/requirements/"
    "迭代41-实盘执行风控监控与示例架构重构/evidence/"
    "iteration41-simnow-c01-v20-credential-free-job-channel-r3-2026-10-09/"
    "runtime-source-pins.json"
)
MANIFEST_PIN = (9069, "e3e6940ba4799b6e783ef4227a07dd43d628ba74b96e5e958a6c7ffec3a6e387")

MANIFEST_SCHEMA = "iteration41-simnow-c01-v20-credential-free-job-channel-source-pins-r3"
TEST_CASES = (
    "test_normal_close_runs_production_postverify_and_preserves_r2_objects",
    "test_precheck_rejection_does_not_enter_exit",
    "test_postclose_uncertainty_retains_one_shot_reference",
)
TEST_CLASS = "SimNowR2SourceCloseTests"
TEST_MODULE_NAME = "_root_simnow_v20_r2_source_close_focused_test"
BLOCKED_IMPORT_ROOTS = {"backtrader", "ssl", "http", "_winapi", "multiprocessing"}
PROVIDER_IMPORT_ROOTS = {"backtrader"}
AUDIT_BLOCKED_EVENTS = {
    "ctypes.dlopen",
    "ctypes.dlsym",
    "ctypes.call_function",
    "ctypes.set_exception",
    "_ctypes.dlopen",
    "_ctypes.dlsym",
    "_ctypes.callproc",
    "subprocess.Popen",
    "os.system",
    "os.fork",
    "os.exec",
    "os.spawn",
}
FILE_MUTATION_EVENTS = {
    "os.chmod",
    "os.chown",
    "os.link",
    "os.mkdir",
    "os.remove",
    "os.rename",
    "os.rmdir",
    "os.symlink",
    "os.truncate",
    "os.unlink",
    "os.utime",
}

_REAL_OPEN = builtins.open
_REAL_IO_OPEN = io.open
_REAL_PATH_OPEN = Path.open
_REAL_OS_OPEN = os.open
_JSON_DUMPS = json.dumps
_JSON_LOADS = json.loads
_SHA256 = hashlib.sha256
_WARNINGS_CONTEXT = warnings.catch_warnings
_REAL_IMPORT_MODULE = importlib.import_module
_MISSING = object()


class HarnessIssue(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _path_for(relative: str) -> Path:
    if type(relative) is not str:
        raise HarnessIssue("public_path_type_invalid")
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts or not pure.parts:
        raise HarnessIssue("public_path_shape_invalid")
    root = ROOT.resolve(strict=True)
    path = root.joinpath(*pure.parts).resolve(strict=True)
    try:
        path.relative_to(root)
    except ValueError:
        raise HarnessIssue("public_path_escape") from None
    if not path.is_file():
        raise HarnessIssue("public_source_not_file")
    return path


def _read_bounded(relative: str, pin: tuple[int, str]) -> bytes:
    size, digest = pin
    if type(size) is not int or not 0 < size <= MAX_PUBLIC_BYTES:
        raise HarnessIssue("public_source_size_pin_invalid")
    if type(digest) is not str or len(digest) != 64:
        raise HarnessIssue("public_source_digest_pin_invalid")
    path = _path_for(relative)
    try:
        with _REAL_OPEN(path, "rb") as stream:
            raw = stream.read(size + 1)
    except OSError:
        raise HarnessIssue("public_source_read_failed") from None
    if type(raw) is not bytes or len(raw) != size or _SHA256(raw).hexdigest() != digest:
        raise HarnessIssue("public_source_pin_mismatch")
    return raw


def _manifest_specs() -> tuple[dict[str, tuple[int, str]], bytes, dict[str, Any]]:
    manifest_raw = _read_bounded(MANIFEST_RELATIVE, MANIFEST_PIN)
    try:
        manifest = _JSON_LOADS(manifest_raw.decode("utf-8"))
    except Exception:
        raise HarnessIssue("public_manifest_invalid") from None
    if (
        type(manifest) is not dict
        or manifest.get("schema") != MANIFEST_SCHEMA
        or manifest.get("status") != "SOURCE_FAKE_ONLY"
        or manifest.get("parent_module_source_count") != 26
        or type(manifest.get("public_source_rows")) is not list
        or len(manifest["public_source_rows"]) != 26
    ):
        raise HarnessIssue("public_manifest_shape_invalid")
    specs: dict[str, tuple[int, str]] = {
        CALLER_RELATIVE: CALLER_PIN,
        TEST_RELATIVE: TEST_PIN,
        PREPARATION_RELATIVE: PREPARATION_PIN,
        LAUNCH_RELATIVE: LAUNCH_PIN,
        HELPER_RELATIVE: HELPER_PIN,
        PRECHECK_RELATIVE: PRECHECK_PIN,
        CORE_CALLER_RELATIVE: CORE_CALLER_PIN,
        MANIFEST_RELATIVE: MANIFEST_PIN,
    }
    for row in manifest["public_source_rows"]:
        if type(row) is not dict:
            raise HarnessIssue("public_manifest_row_invalid")
        relative = row.get("path")
        size = row.get("bytes")
        digest = row.get("sha256")
        if (
            type(relative) is not str
            or type(size) is not int
            or not 0 < size <= MAX_PUBLIC_BYTES
            or type(digest) is not str
            or len(digest) != 64
            or any(ch not in "0123456789abcdef" for ch in digest)
            or relative in specs
        ):
            raise HarnessIssue("public_manifest_row_pin_invalid")
        specs[relative] = (size, digest)
    if len(specs) != 34:
        raise HarnessIssue("public_input_count_invalid")
    return specs, manifest_raw, manifest


def _stdlib_roots() -> set[str]:
    return (
        set(sys.stdlib_module_names)
        | set(sys.builtin_module_names)
        | {"ssl", "http", "_winapi", "multiprocessing"}
    )


def _stdlib_origin(module: types.ModuleType) -> str:
    spec = getattr(module, "__spec__", None)
    origin = getattr(spec, "origin", None)
    if origin in {"built-in", "frozen"}:
        return origin
    if type(origin) is not str or not origin:
        raise HarnessIssue("stdlib_module_origin_missing")
    candidate = Path(origin).resolve(strict=False)
    roots: set[Path] = set()
    paths = sysconfig.get_paths()
    for key in ("stdlib", "platstdlib"):
        value = paths.get(key)
        if value:
            roots.add(Path(value).resolve(strict=False))
    for prefix in {Path(sys.base_prefix), Path(sys.exec_prefix)}:
        roots.add((prefix / "DLLs").resolve(strict=False))
        roots.add((prefix / "Lib").resolve(strict=False))
        roots.add((prefix / f"python{sys.version_info.major}{sys.version_info.minor}.zip").resolve(strict=False))
    if not any(candidate == root or root in candidate.parents for root in roots):
        raise HarnessIssue("stdlib_module_origin_noncanonical")
    return os.path.normcase(str(candidate))


def _capture_stdlib_bindings() -> dict[str, tuple[types.ModuleType, str]]:
    roots = _stdlib_roots()
    bindings: dict[str, tuple[types.ModuleType, str]] = {}
    for name, module in tuple(sys.modules.items()):
        if name.partition(".")[0] not in roots or not isinstance(module, types.ModuleType):
            continue
        bindings[name] = (module, _stdlib_origin(module))
    return bindings


def _verify_stdlib_bindings(
    expected: dict[str, tuple[types.ModuleType, str]],
) -> None:
    current = _capture_stdlib_bindings()
    if set(current) != set(expected):
        raise HarnessIssue("stdlib_module_set_changed")
    for name, (module, origin) in expected.items():
        current_module, current_origin = current[name]
        if current_module is not module or current_origin != origin:
            raise HarnessIssue("stdlib_module_identity_changed")


def _stdlib_binding_fingerprint(
    bindings: dict[str, tuple[types.ModuleType, str]],
) -> str:
    rows = [
        [name, origin, id(module)]
        for name, (module, origin) in sorted(bindings.items())
    ]
    raw = _JSON_DUMPS(rows, separators=(",", ":")).encode("utf-8")
    return _SHA256(raw).hexdigest()


def _preload_stdlib(
    sources: dict[str, bytes],
) -> tuple[
    tuple[str, ...],
    dict[str, tuple[types.ModuleType, str]],
    dict[tuple[str, str], object],
]:
    names: set[str] = set()
    from_imports: list[tuple[str, tuple[str, ...]]] = []
    for relative, raw in sources.items():
        try:
            tree = ast.parse(raw, filename=relative)
        except Exception:
            raise HarnessIssue("public_source_ast_invalid") from None
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module)
                from_imports.append((node.module, tuple(alias.name for alias in node.names)))
    stdlib_roots = _stdlib_roots()
    preload: set[str] = set()
    for name in names:
        if name == "__future__":
            continue
        root = name.partition(".")[0]
        if root in stdlib_roots:
            preload.add(name)
    for name in sorted(preload):
        try:
            importlib.import_module(name)
        except Exception:
            raise HarnessIssue("stdlib_preload_failed") from None
    attribute_bindings: dict[tuple[str, str], object] = {}
    for module_name, attributes in from_imports:
        if module_name.partition(".")[0] not in stdlib_roots:
            continue
        try:
            module = importlib.import_module(module_name)
            for attribute in attributes:
                if attribute == "*":
                    raise HarnessIssue("stdlib_star_import_unsupported")
                value = getattr(module, attribute, _MISSING)
                if value is not _MISSING:
                    attribute_bindings[(module_name, attribute)] = value
                    continue
                child_name = module_name + "." + attribute
                if child_name.partition(".")[0] in stdlib_roots:
                    try:
                        value = importlib.import_module(child_name)
                    except Exception:
                        raise HarnessIssue("stdlib_attribute_preload_failed") from None
                    attribute_bindings[(module_name, attribute)] = value
                if attribute not in module.__dict__ and child_name not in sys.modules:
                    raise HarnessIssue("stdlib_attribute_preload_failed")
        except HarnessIssue:
            raise
        except Exception:
            raise HarnessIssue("stdlib_attribute_preload_failed") from None
    bindings = _capture_stdlib_bindings()
    # Bind every already-present attribute on each canonical stdlib module by
    # identity. This permits stable internal ``from module import name`` uses
    # without accepting attributes installed or replaced after guard setup.
    for module_name, (module, _origin) in bindings.items():
        for attribute, value in tuple(module.__dict__.items()):
            if type(attribute) is str:
                attribute_bindings.setdefault((module_name, attribute), value)
    return tuple(sorted(bindings)), bindings, attribute_bindings


def _canonical(value: object) -> str:
    if not isinstance(value, (str, bytes, os.PathLike)):
        raise HarnessIssue("non_path_open_denied")
    try:
        path = Path(os.fsdecode(value)).resolve(strict=False)
    except (OSError, TypeError, ValueError):
        raise HarnessIssue("path_resolution_denied") from None
    return os.path.normcase(str(path))


def _write_mode(mode: object) -> bool:
    return (
        type(mode) is not str
        or not mode.startswith("r")
        or any(character in mode for character in "wax+")
    )


def _write_flags(flags: object) -> bool:
    if type(flags) is not int:
        return False
    write_bits = (
        getattr(os, "O_WRONLY", 1)
        | getattr(os, "O_RDWR", 2)
        | getattr(os, "O_CREAT", 0)
        | getattr(os, "O_TRUNC", 0)
        | getattr(os, "O_APPEND", 0)
    )
    return bool(flags & write_bits)


def _install_outer_guards(
    allowed: set[str],
    counts: Counter[str],
    stdlib_bindings: dict[str, tuple[types.ModuleType, str]],
    stdlib_attributes: dict[tuple[str, str], object],
    public_source_labels: dict[str, str],
    first_denied_stdlib_import: list[dict[str, str]],
) -> None:
    original_import = builtins.__import__
    stdlib_roots = _stdlib_roots()
    native_names = tuple(
        name for name in ("CDLL", "PyDLL", "WinDLL", "OleDLL", "_dlopen")
        if hasattr(ctypes, name)
    )
    socket_names = tuple(
        name for name in ("socket", "create_connection", "getaddrinfo", "getnameinfo", "gethostbyname", "gethostbyaddr")
        if hasattr(socket, name)
    )
    subprocess_names = tuple(
        name for name in ("Popen", "run", "call", "check_call", "check_output")
        if hasattr(subprocess, name)
    )
    os_process_names = tuple(
        name for name in ("system", "startfile", "fork", "execv", "execve", "spawnv", "spawnve")
        if hasattr(os, name)
    )
    os_mutation_names = tuple(
        name for name in ("chmod", "chown", "link", "mkdir", "makedirs", "remove", "rename", "replace", "rmdir", "symlink", "truncate", "unlink", "utime")
        if hasattr(os, name)
    )

    def deny(category: str) -> None:
        counts[category] += 1
        raise HarnessIssue(category)

    def _safe_import_token(value: object, fallback: str) -> str:
        if (
            type(value) is str
            and 0 < len(value) <= 128
            and value.isascii()
            and all(character.isalnum() or character in "._" for character in value)
        ):
            return value
        return fallback

    def _caller_origin_label(frame: types.FrameType | None) -> str:
        if frame is None:
            return "unclassified"
        filename = frame.f_code.co_filename
        if type(filename) is str:
            key = os.path.normcase(os.path.normpath(filename))
            public_label = public_source_labels.get(key)
            if public_label is not None:
                return "public:" + public_label
            if filename.startswith("<frozen "):
                return "stdlib:frozen"
        module_name = frame.f_globals.get("__name__")
        if (
            type(module_name) is str
            and module_name in stdlib_bindings
            and sys.modules.get(module_name) is stdlib_bindings[module_name][0]
        ):
            return "stdlib:" + _safe_import_token(module_name, "unclassified")
        return "unclassified"

    def record_stdlib_import_denial(
        module_name: object,
        attribute: object,
        reason: str,
        caller_frame: types.FrameType | None,
    ) -> None:
        if first_denied_stdlib_import:
            return
        first_denied_stdlib_import.append(
            {
                "module": _safe_import_token(module_name, "unclassified"),
                "attribute": _safe_import_token(attribute, "unclassified"),
                "reason": reason,
                "caller_origin": _caller_origin_label(caller_frame),
            }
        )

    def _import_site_frame() -> types.FrameType | None:
        frame = sys._getframe(2)
        if frame.f_code.co_name == "_guarded_import" and frame.f_back is not None:
            return frame.f_back
        return frame

    def check_path(value: object) -> str:
        value = _canonical(value)
        if value not in allowed:
            deny("file_read_denied")
        return value

    def guarded_open(file: object, mode: str = "r", *args: object, **kwargs: object):
        path = check_path(file)
        if _write_mode(mode):
            deny("file_write_denied")
        return _REAL_OPEN(path, mode, *args, **kwargs)

    def guarded_io_open(file: object, mode: str = "r", *args: object, **kwargs: object):
        path = check_path(file)
        if _write_mode(mode):
            deny("file_write_denied")
        return _REAL_IO_OPEN(path, mode, *args, **kwargs)

    def guarded_path_open(self: Path, mode: str = "r", *args: object, **kwargs: object):
        path = check_path(self)
        if _write_mode(mode):
            deny("file_write_denied")
        return _REAL_PATH_OPEN(Path(path), mode, *args, **kwargs)

    def guarded_os_open(path: object, flags: int, *args: object, **kwargs: object):
        normalized = check_path(path)
        if _write_flags(flags):
            deny("file_write_denied")
        return _REAL_OS_OPEN(normalized, flags, *args, **kwargs)

    def guarded_import(name: str, globals=None, locals=None, fromlist=(), level=0):
        caller_frame = _import_site_frame()
        root = name.partition(".")[0].casefold() if type(name) is str else ""
        if root == "backtrader" or root.startswith(("win32", "bt_api_")):
            deny("candidate_import_denied")
        if root in stdlib_roots:
            binding = stdlib_bindings.get(name)
            if binding is None or sys.modules.get(name) is not binding[0]:
                record_stdlib_import_denial(
                    name,
                    "module_import",
                    "module_not_preloaded",
                    caller_frame,
                )
                deny("stdlib_import_not_preloaded")
            try:
                if _stdlib_origin(binding[0]) != binding[1]:
                    record_stdlib_import_denial(
                        name,
                        "module_origin",
                        "origin_changed",
                        caller_frame,
                    )
                    deny("stdlib_binding_changed")
            except HarnessIssue:
                record_stdlib_import_denial(
                    name,
                    "module_origin",
                    "origin_changed",
                    caller_frame,
                )
                deny("stdlib_binding_changed")
            for attribute in fromlist or ():
                expected_attribute = stdlib_attributes.get((name, attribute), _MISSING)
                if expected_attribute is _MISSING:
                    record_stdlib_import_denial(
                        name,
                        attribute,
                        "attribute_not_in_preguard_snapshot",
                        caller_frame,
                    )
                    deny("stdlib_attribute_not_preloaded")
                try:
                    actual_attribute = getattr(binding[0], attribute, _MISSING)
                except Exception:
                    record_stdlib_import_denial(
                        name,
                        attribute,
                        "attribute_lookup_failed",
                        caller_frame,
                    )
                    deny("stdlib_attribute_not_preloaded")
                if actual_attribute is not expected_attribute:
                    child = stdlib_bindings.get(name + "." + attribute)
                    if (
                        child is None
                        or sys.modules.get(name + "." + attribute) is not child[0]
                        or actual_attribute is not child[0]
                    ):
                        record_stdlib_import_denial(
                            name,
                            attribute,
                            "attribute_identity_changed",
                            caller_frame,
                        )
                        deny("stdlib_attribute_not_preloaded")
        elif root in BLOCKED_IMPORT_ROOTS:
            deny("candidate_import_denied")
        return original_import(name, globals, locals, fromlist, level)

    def guarded_import_module(name: str, package: str | None = None):
        caller_frame = sys._getframe(1)
        absolute = name
        if type(name) is not str:
            deny("candidate_import_denied")
        if name.startswith("."):
            if type(package) is not str:
                deny("candidate_import_denied")
            absolute = importlib.util.resolve_name(name, package)
        root = absolute.partition(".")[0].casefold()
        if root == "backtrader" or root.startswith(("win32", "bt_api_")):
            deny("candidate_import_denied")
        if root in stdlib_roots:
            binding = stdlib_bindings.get(absolute)
            if binding is None or sys.modules.get(absolute) is not binding[0]:
                record_stdlib_import_denial(
                    absolute,
                    "module_import",
                    "module_not_preloaded",
                    caller_frame,
                )
                deny("stdlib_import_not_preloaded")
            try:
                if _stdlib_origin(binding[0]) != binding[1]:
                    record_stdlib_import_denial(
                        absolute,
                        "module_origin",
                        "origin_changed",
                        caller_frame,
                    )
                    deny("stdlib_binding_changed")
            except HarnessIssue:
                record_stdlib_import_denial(
                    absolute,
                    "module_origin",
                    "origin_changed",
                    caller_frame,
                )
                deny("stdlib_binding_changed")
        elif root in BLOCKED_IMPORT_ROOTS:
            deny("candidate_import_denied")
        return _REAL_IMPORT_MODULE(name, package)

    def make_denier(category: str):
        def denied(*_args: object, **_kwargs: object):
            deny(category)
        return denied

    def audit_guard(event: str, args: tuple[object, ...]) -> None:
        if event == "open" and args:
            normalized = check_path(args[0])
            mode = args[1] if len(args) > 1 else "r"
            flags = args[2] if len(args) > 2 else 0
            if _write_mode(mode) or _write_flags(flags):
                deny("file_write_denied")
            if normalized not in allowed:
                deny("file_read_denied")
        if event.startswith("socket."):
            deny("network_audit_denied")
        if event in AUDIT_BLOCKED_EVENTS:
            deny("native_process_audit_denied")
        if event in FILE_MUTATION_EVENTS:
            deny("file_mutation_audit_denied")

    builtins.open = guarded_open
    io.open = guarded_io_open
    Path.open = guarded_path_open
    os.open = guarded_os_open
    builtins.__import__ = guarded_import
    importlib.import_module = guarded_import_module
    for name in native_names:
        setattr(ctypes, name, make_denier("native_wrapper_denied"))
    for name in socket_names:
        setattr(socket, name, make_denier("network_wrapper_denied"))
    for name in subprocess_names:
        setattr(subprocess, name, make_denier("process_wrapper_denied"))
    for name in os_process_names:
        setattr(os, name, make_denier("process_wrapper_denied"))
    for name in os_mutation_names:
        setattr(os, name, make_denier("file_mutation_wrapper_denied"))

    def bind_installed_wrapper(module_name: str, module: types.ModuleType, names: tuple[str, ...]) -> None:
        binding = stdlib_bindings.get(module_name)
        if binding is None or binding[0] is not module:
            return
        for name in names:
            value = module.__dict__.get(name, _MISSING)
            if value is not _MISSING:
                stdlib_attributes[(module_name, name)] = value

    builtins_module = sys.modules.get("builtins")
    if isinstance(builtins_module, types.ModuleType):
        bind_installed_wrapper("builtins", builtins_module, ("open", "__import__"))
    bind_installed_wrapper("io", io, ("open",))
    bind_installed_wrapper("os", os, ("open",) + os_process_names + os_mutation_names)
    bind_installed_wrapper("ctypes", ctypes, native_names)
    bind_installed_wrapper("socket", socket, socket_names)
    bind_installed_wrapper("subprocess", subprocess, subprocess_names)
    bind_installed_wrapper("importlib", importlib, ("import_module",))
    sys.addaudithook(audit_guard)


def _expect_denied(expected: str, operation) -> None:
    try:
        operation()
    except HarnessIssue as exc:
        if exc.code != expected:
            raise HarnessIssue("guard_selfcheck_wrong_category") from None
        return
    except Exception:
        raise HarnessIssue("guard_selfcheck_unexpected_exception") from None
    raise HarnessIssue("guard_selfcheck_not_blocked")


def _guard_selfchecks(counts: Counter[str], allowed: set[str]) -> dict[str, int]:
    sentinel = r"Z:\__codex_simnow_r2_source_close_guard_sentinel__\private.env"
    public_path = str(_path_for(TEST_RELATIVE))
    _expect_denied(
        "file_read_denied",
        lambda: builtins.open(sentinel, "rb"),
    )
    _expect_denied(
        "file_write_denied",
        lambda: builtins.open(public_path, "wb"),
    )
    _expect_denied(
        "candidate_import_denied",
        lambda: builtins.__import__("backtrader"),
    )
    _expect_denied(
        "native_wrapper_denied",
        lambda: ctypes.CDLL("never-load-native-sentinel.dll"),
    )
    _expect_denied(
        "network_wrapper_denied",
        lambda: socket.socket(),
    )
    _expect_denied(
        "process_wrapper_denied",
        lambda: subprocess.Popen(["never-spawn-sentinel"]),
    )
    _expect_denied(
        "process_wrapper_denied",
        lambda: os.system("never-run-sentinel"),
    )
    _expect_denied(
        "file_mutation_wrapper_denied",
        lambda: os.remove(sentinel),
    )
    for event, args, category in (
        ("open", (sentinel, "r", 0), "file_read_denied"),
        ("ctypes.dlopen", ("never-load-audit-sentinel.dll",), "native_process_audit_denied"),
        ("socket.connect", (("127.0.0.1", 9),), "network_audit_denied"),
        ("subprocess.Popen", (["never-spawn-audit-sentinel"], None, None, None), "native_process_audit_denied"),
        ("os.system", ("never-run-audit-sentinel",), "native_process_audit_denied"),
        ("os.remove", (sentinel,), "file_mutation_audit_denied"),
    ):
        _expect_denied(category, lambda event=event, args=args: sys.audit(event, *args))
    expected = {
        "file_read_denied": 2,
        "file_write_denied": 1,
        "candidate_import_denied": 1,
        "native_wrapper_denied": 1,
        "network_wrapper_denied": 1,
        "process_wrapper_denied": 2,
        "file_mutation_wrapper_denied": 1,
        "native_process_audit_denied": 3,
        "network_audit_denied": 1,
        "file_mutation_audit_denied": 1,
    }
    if {key: counts[key] for key in expected} != expected:
        raise HarnessIssue("guard_selfcheck_counts_invalid")
    return expected


def _run_focused_cases(test_raw: bytes, test_path: Path) -> tuple[bool, int, int, int]:
    module = types.ModuleType(TEST_MODULE_NAME)
    module.__file__ = str(test_path)
    module.__package__ = ""
    sys.modules[TEST_MODULE_NAME] = module
    try:
        exec(compile(test_raw, module.__file__, "exec", dont_inherit=True), module.__dict__)
        case_class = module.__dict__.get(TEST_CLASS)
        if not isinstance(case_class, type) or not issubclass(case_class, unittest.TestCase):
            raise HarnessIssue("focused_test_class_invalid")
        for test_case in TEST_CASES:
            method = getattr(case_class, test_case, None)
            if not callable(method):
                raise HarnessIssue("focused_test_method_invalid")
        suite = unittest.TestSuite(case_class(test_case) for test_case in TEST_CASES)
        runner = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0)
        result = runner.run(suite)
        return (
            result.wasSuccessful(),
            result.testsRun,
            len(result.failures),
            len(result.errors) + len(result.skipped),
        )
    finally:
        sys.modules.pop(TEST_MODULE_NAME, None)


def main() -> None:
    if not RESULT_PATH.parent.is_dir() or RESULT_PATH.exists():
        raise SystemExit(2)
    try:
        result_stream = _REAL_OPEN(RESULT_PATH, "xb")
    except OSError:
        raise SystemExit(2) from None

    phase = "public_preflight"
    status = "BLOCKED"
    failure_code = None
    manifest: dict[str, Any] | None = None
    source_specs: dict[str, tuple[int, str]] = {}
    source_before: dict[str, bytes] = {}
    stdlib_preloaded: tuple[str, ...] = ()
    stdlib_bindings: dict[str, tuple[types.ModuleType, str]] = {}
    stdlib_attributes: dict[tuple[str, str], object] = {}
    stdlib_bindings_unchanged = False
    stdlib_binding_fingerprint = None
    preload_warning_count = 0
    candidate_warning_count = 0
    stdlib_origin_kind_counts: dict[str, int] = {}
    stdlib_origins_canonical = False
    provider_sdk_absence_verified = False
    public_inputs_unchanged = False
    guard_counts: Counter[str] = Counter()
    guard_selfcheck_counts: dict[str, int] = {}
    guard_selfchecks_complete = False
    selfcheck_baseline_counts: Counter[str] = Counter()
    selfcheck_observed_counts: Counter[str] = Counter()
    post_selfcheck_counts: Counter[str] = Counter()
    test_counts = {"tests_run": 0, "failures": 0, "errors_or_skips": 0}
    input_pins: list[dict[str, Any]] = []
    candidate_denial_delta: dict[str, int] = {}
    first_denied_stdlib_import: list[dict[str, str]] = []
    try:
        source_specs, _manifest_raw, manifest = _manifest_specs()
        for relative, pin in source_specs.items():
            source_before[relative] = _read_bounded(relative, pin)
        input_pins = [
            {"path": relative, "bytes": pin[0], "sha256": pin[1]}
            for relative, pin in sorted(source_specs.items())
        ]

        phase = "stdlib_preload"
        with _WARNINGS_CONTEXT(record=True) as preload_warnings:
            warnings.simplefilter("always")
            stdlib_preloaded, stdlib_bindings, stdlib_attributes = _preload_stdlib(source_before)
        preload_warning_count = len(preload_warnings)
        origin_kinds = Counter(
            "builtin" if origin == "built-in" else
            "frozen" if origin == "frozen" else
            "file"
            for _module, origin in stdlib_bindings.values()
        )
        stdlib_origin_kind_counts = dict(sorted(origin_kinds.items()))
        stdlib_origins_canonical = True
        provider_sdk_modules = tuple(
            sorted(
                name
                for name in sys.modules
                if name.partition(".")[0].casefold() == "backtrader"
                or name.partition(".")[0].casefold().startswith("bt_api_")
            )
        )
        if provider_sdk_modules:
            raise HarnessIssue("provider_sdk_module_present_before_candidate")
        provider_sdk_absence_verified = True
        stdlib_binding_fingerprint = _stdlib_binding_fingerprint(stdlib_bindings)

        allowed_paths: set[str] = set()
        public_source_labels: dict[str, str] = {}
        for relative in source_specs:
            source_path = _path_for(relative)
            allowed_paths.add(_canonical(source_path))
            public_source_labels[
                os.path.normcase(os.path.normpath(str(source_path)))
            ] = relative
        phase = "outer_guard_install"
        _install_outer_guards(
            allowed_paths,
            guard_counts,
            stdlib_bindings,
            stdlib_attributes,
            public_source_labels,
            first_denied_stdlib_import,
        )
        phase = "guard_selfchecks"
        selfcheck_baseline_counts = Counter(guard_counts)
        guard_selfcheck_counts = _guard_selfchecks(guard_counts, allowed_paths)
        selfcheck_observed_counts = Counter(guard_counts - selfcheck_baseline_counts)
        guard_selfchecks_complete = True
        post_selfcheck_counts = Counter(guard_counts)

        phase = "three_focused_source_close_cases"
        candidate_error = None
        with _WARNINGS_CONTEXT(record=True) as candidate_warnings:
            warnings.simplefilter("always")
            try:
                success, tests_run, failures, errors_or_skips = _run_focused_cases(
                    source_before[TEST_RELATIVE], _path_for(TEST_RELATIVE)
                )
            except HarnessIssue as exc:
                candidate_error = exc.code
                success, tests_run, failures, errors_or_skips = False, 0, 0, 1
            except BaseException:
                candidate_error = "focused_case_runner_exception"
                success, tests_run, failures, errors_or_skips = False, 0, 0, 1
        candidate_warning_count = len(candidate_warnings)
        test_counts = {
            "tests_run": tests_run,
            "failures": failures,
            "errors_or_skips": errors_or_skips,
        }
        candidate_denial_delta = {
            key: guard_counts[key] - post_selfcheck_counts[key]
            for key in sorted(set(guard_counts) | set(post_selfcheck_counts))
        }
        phase = "stdlib_identity_postcheck"
        _verify_stdlib_bindings(stdlib_bindings)
        stdlib_bindings_unchanged = True

        phase = "public_postcheck"
        for relative, pin in source_specs.items():
            after = _read_bounded(relative, pin)
            if after != source_before[relative]:
                raise HarnessIssue("public_input_changed_during_test")
        public_inputs_unchanged = True
        if candidate_error is not None:
            raise HarnessIssue(candidate_error)
        if (
            not success
            or tests_run != len(TEST_CASES)
            or failures != 0
            or errors_or_skips != 0
        ):
            raise HarnessIssue("focused_source_fake_case_failed")
        if any(candidate_denial_delta.values()):
            raise HarnessIssue("candidate_operation_guard_denial")
        if preload_warning_count or candidate_warning_count:
            raise HarnessIssue("source_qa_warnings_observed")
        status = "PASS_ROOT_FOCUSED_SOURCE_FAKE_ONLY"
        phase = "complete"
    except HarnessIssue as exc:
        failure_code = exc.code
    except BaseException:
        failure_code = "harness_unexpected_exception"
    finally:
        observed_selfcheck_counts = (
            selfcheck_observed_counts
            if guard_selfchecks_complete
            else Counter(guard_counts - selfcheck_baseline_counts)
        )
        record = {
            "schema": "iteration41-simnow-v20-r2-normal-source-close-root-focused-qa-r1",
            "status": status,
            "phase": phase,
            "failure_code": failure_code,
            "evidence_level": "ROOT_FOCUSED_SOURCE_FAKE_ONLY",
            "test_cases": [f"{TEST_CLASS}.{test_case}" for test_case in TEST_CASES],
            "expected_test_count": len(TEST_CASES),
            "test_counts": test_counts,
            "public_input_count": len(input_pins),
            "public_input_pins": input_pins,
            "all_public_inputs_unchanged": public_inputs_unchanged,
            "outer_guard_selfcheck_expected_counts": guard_selfcheck_counts,
            "outer_guard_selfcheck_complete": guard_selfchecks_complete,
            "outer_guard_selfcheck_expected_denial_count": 14,
            "outer_guard_selfcheck_observed_counts": dict(
                sorted(observed_selfcheck_counts.items())
            ),
            "outer_guard_selfcheck_denial_count": sum(observed_selfcheck_counts.values()),
            "candidate_operation_guard_denial_delta": candidate_denial_delta,
            "first_denied_stdlib_import": first_denied_stdlib_import[0]
            if first_denied_stdlib_import
            else None,
            "stdlib_preloaded_count": len(stdlib_preloaded),
            "stdlib_preloaded_names": list(stdlib_preloaded),
            "stdlib_bindings_canonical_and_unchanged": stdlib_bindings_unchanged,
            "stdlib_binding_fingerprint": stdlib_binding_fingerprint,
            "stdlib_origin_count": len(stdlib_bindings),
            "stdlib_origin_kind_counts": stdlib_origin_kind_counts,
            "stdlib_origins_canonical": stdlib_origins_canonical,
            "stdlib_attribute_binding_snapshot_count": len(stdlib_attributes),
            "preload_warning_count": preload_warning_count,
            "candidate_warning_count": candidate_warning_count,
            "warning_count": preload_warning_count + candidate_warning_count,
            "provider_sdk_absence_before_candidate": provider_sdk_absence_verified,
            "runtime_source_manifest_schema": manifest.get("schema") if type(manifest) is dict else None,
            "software_source_metadata_rows": 3,
            "software_or_cuv2_payload_bytes_read": 0,
            "actual_root_preparation": False,
            "synthetic_source_close_tests": True,
            "actual_source_lease_close": False,
            "retained_host_or_session_access": False,
            "credential_free_gate_invoked": False,
            "activation_started": False,
            "provider_or_account_action": False,
            "formal_c01_pass": False,
        }
        encoded = (_JSON_DUMPS(record, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        try:
            result_stream.write(encoded)
            result_stream.flush()
        finally:
            result_stream.close()
    if status != "PASS_ROOT_FOCUSED_SOURCE_FAKE_ONLY":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
