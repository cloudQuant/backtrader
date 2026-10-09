"""Root-only caller for one credential-free R7 Win32 helper lifecycle probe.

This module does not run at import time. Root supplies a fresh CUv2 module,
its exact public source pins, exact software hash pins, a one-use nonce, and a
new evidence directory. A failure after source custody begins retains the
scope and every loaded module reference; only a fully typed clean synthetic
result permits normal CUv2 postverification and close.
"""

from __future__ import annotations

import ast
import builtins
import contextlib
import hashlib
import importlib
import importlib.util
import io
import inspect
import json
import os
from pathlib import Path
import re
import sys
import types
from typing import Any, Mapping


ROOT = Path("D:/source_code/backtrader")
EVIDENCE_ROOT = ROOT / "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence"
CURRENT_PACKET = (
    EVIDENCE_ROOT / "iteration41-okx-m01-root-helper-lifecycle-integration-r1-2026-10-09"
)
SOURCE_MAP_RELATIVE = CURRENT_PACKET.relative_to(ROOT).as_posix() + "/source-map.json"
SOURCE_INDEX_RELATIVE = CURRENT_PACKET.relative_to(ROOT).as_posix() + "/source-index.json"
SOURCE_MAP_BYTES = 2877
SOURCE_MAP_SHA256 = "07f0eb60d60f37919c75cc3ec6833b41653fdbc9952c8478dbbc36ba0cda1ff3"
SOURCE_INDEX_BYTES = 9970
SOURCE_INDEX_SHA256 = "8cd0360bb9519daf785412a6176091d2ca0ff4471e2bf65aba011aeec3444564"
SOURCE_INDEX_ROW_COUNT = 26
CUV2_SOURCE_RELATIVE = (
    "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/"
    "iteration41-cuv2-public-source-snapshot-r1-2026-10-08/cuv2-source.py"
)
CUV2_SOURCE_BYTES = 2344
CUV2_SOURCE_SHA256 = "e856be8e4056835d4a7e54f5c6b449c69ab3f1c2ebb049bcbcc1c95a9ad3f246"
CUV2_SOFTWARE_ORIGIN = "D:/temp/iteration41-root-public-custody-v2.py"
ROOT_PUBLIC_PIN_COUNT = 31
ACTUAL_OUTPUT_NAME = "iteration41-okx-m01-r7-five-module-root-gate-actual-r2-2026-10-09"
GATE_RELATIVE = "scripts/iteration41_okx_m01_root_helper_lifecycle_gate_r7.py"
GATE_BYTES = 75271
GATE_SHA256 = "43e2b3cee8da9f1ebcf148992160512893615bfa15fc118ced491b04dd05ac72"
GATE_TEST_RELATIVE = "tests/unit/scripts/test_iteration41_okx_m01_root_helper_lifecycle_gate_r7.py"
GATE_TEST_BYTES = 27576
GATE_TEST_SHA256 = "73fd436e5de9327f0d02f59baab66b60b1887bf1bf0d27ceeaca7a5c018b3038"
CALLER_RELATIVE = "scripts/iteration41_okx_m01_root_helper_lifecycle_r7_root_caller_r2.py"
CALLER_TEST_RELATIVE = "tests/unit/scripts/test_iteration41_okx_m01_root_helper_lifecycle_r7_root_caller_r2_source_fake.py"

MODULE_SPECS = {
    "reader": (
        "_m01_readonly_monitor_v3.current_reader",
        "examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v3/current_reader.py",
        "5a8fd479c999279d9efde625cac1938d794201f04e1beaa6f3663b267d7a7ebc",
        68215,
    ),
    "supervisor": (
        "_m01_readonly_monitor_v2.job_supervisor",
        "examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v2/job_supervisor.py",
        "188b929b4e74b6e16a54d21093b6d52a7471849b161b2777945561e6d8d62e82",
        71188,
    ),
    "worker": (
        "_m01_readonly_monitor_v2.worker",
        "examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v2/worker.py",
        "aea9651c571d4bbd93592ccbd06c630a2a73df8286e9425a357433d598ca4f41",
        60000,
    ),
    "current_types": (
        "_m01_readonly_monitor_v2.current_types",
        "examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v2/current_types.py",
        "cd896051b0580195baa569989622c18fec594afc3772e7ea4af9e4cf226778ea",
        7364,
    ),
    "contract": (
        "_certification.m01_private_monitor_v2",
        "examples/000_live_certification/okx_penetration/_certification/m01_private_monitor_v2.py",
        "1c319502dcec4da91a7166ad1a532e4610319ca837ac93f2391f21fda87ae1db",
        25108,
    ),
}
REQUIRED_PACKAGE_MODULES = {
    "_certification",
    "_certification.m01_private_monitor_v2",
    "_m01_readonly_monitor_v2",
    "_m01_readonly_monitor_v2.current_types",
    "_m01_readonly_monitor_v2.job_supervisor",
    "_m01_readonly_monitor_v2.worker",
    "_m01_readonly_monitor_v3",
    "_m01_readonly_monitor_v3.current_reader",
}
PACKAGE_SPECS = {
    "_certification": "examples/000_live_certification/okx_penetration/_certification/__init__.py",
    "_m01_readonly_monitor_v2": "examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v2/__init__.py",
    "_m01_readonly_monitor_v3": "examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v3/__init__.py",
}
SOFTWARE_PIN_KEYS = {
    "C:/anaconda3/python.exe",
    "C:/anaconda3/python311.dll",
    CUV2_SOFTWARE_ORIGIN,
}
PHASES = {
    "source_binding",
    "winapi_factory",
    "create_suspended",
    "pipe_setup",
    "job_assign",
    "job_count_assign",
    "resume",
    "job_count_resume",
    "thread_handle_close",
    "stdin_write",
    "stdin_close",
    "process_wait",
    "process_exit_code",
    "stdout_drain",
    "stderr_drain",
    "pipe_join",
    "job_count_after_exit",
    "job_count_after_cleanup",
    "reader_check",
    "reader_exception",
    "cleanup_terminate",
    "cleanup_wait",
    "cleanup_close",
    "complete",
}
GATE_TRUE_FIELDS = (
    "reader_source_pinned",
    "supervisor_source_pinned",
    "worker_source_pinned",
    "source_functions_restored",
    "process_created",
    "job_assigned_before_resume",
    "resumed",
    "source_frame_write_succeeded",
    "stdin_close_succeeded",
    "process_wait_succeeded",
    "process_reaped_after_cleanup",
    "process_exit_code_present",
    "process_exit_code_zero",
    "cleanup_confirmed",
    "job_count_observed",
    "job_zero_after_exit",
    "job_count_after_cleanup_observed",
    "job_zero_after_cleanup",
    "stdout_eof",
    "stderr_eof",
    "stdout_read_done",
    "stderr_read_done",
    "stdout_matches_fixed",
    "stderr_empty",
    "stdout_thread_started",
    "stderr_thread_started",
    "stdout_thread_joined",
    "stderr_thread_joined",
    "all_observed_handles_closed",
    "runtime_registry_empty_before",
    "runtime_registry_empty_after",
    "runtime_registry_unchanged",
    "reader_retained_contexts_empty_before",
    "reader_retained_contexts_empty_after",
    "reader_retained_registry_identity_unchanged",
    "module_bindings_unchanged_after",
)
GATE_FALSE_FIELDS = (
    "job_count_observations_truncated",
    "stdout_read_error",
    "stderr_read_error",
    "stdout_overflow",
    "stderr_overflow",
    "termination_requested",
    "retained_context",
    "source_fake_only",
    "production_acceptance",
    "job_nonzero_after_exit",
    "job_nonzero_after_cleanup",
    "reader_check_failed",
    "reader_exception_seen",
)
_SAFE_CODE = re.compile(r"[a-z0-9_]{1,64}\Z")
_SAFE_NONCE = re.compile(r"[a-f0-9]{32}\Z")
_MAX_RESULT_BYTES = 32 * 1024
_MAX_SOURCE_BYTES = 2 * 1024 * 1024
_MAX_JOB_OBSERVATIONS = 256
_INVOCATION_STARTED = False
_RETAINED_CONTEXTS: list[tuple[Any, ...]] = []


class CallerError(ValueError):
    def __init__(self, code: str):
        self.code = code if type(code) is str and _SAFE_CODE.fullmatch(code) else "caller_rejected"
        super().__init__(self.code)


class _BoundedText(io.StringIO):
    def write(self, value: str) -> int:
        if not isinstance(value, str) or self.tell() + len(value) > 4096:
            raise CallerError("gate_output_limit_exceeded")
        return super().write(value)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _contextmanager_wrapper_reference() -> Any:
    @contextlib.contextmanager
    def reference_generator():
        yield None

    return reference_generator


def _safe_value_snapshot(value: Any) -> Any:
    value_type = type(value)
    if value is None or value_type in (bool, int, float, str, bytes):
        return (value_type, value)
    if value_type is tuple:
        return (tuple, tuple(_safe_value_snapshot(item) for item in value))
    if value_type is list:
        return (list, tuple(_safe_value_snapshot(item) for item in value))
    if value_type is dict:
        return (
            dict,
            tuple(
                (_safe_value_snapshot(key), _safe_value_snapshot(item))
                for key, item in value.items()
            ),
        )
    if value_type in (set, frozenset):
        values = tuple(_safe_value_snapshot(item) for item in value)
        return (value_type, tuple(sorted(values, key=repr)))
    return ("identity", id(value))


def _function_binding_snapshot(function: types.FunctionType) -> tuple[Any, ...]:
    return (
        function.__code__,
        function.__globals__,
        function.__module__,
        function.__qualname__,
        function.__defaults__,
        _safe_value_snapshot(function.__defaults__),
        function.__kwdefaults__,
        _safe_value_snapshot(function.__kwdefaults__),
        function.__closure__,
        tuple(cell.cell_contents for cell in function.__closure__ or ()),
        tuple(function.__dict__.items()),
    )


def _function_binding_unchanged(function: Any, snapshot: tuple[Any, ...]) -> bool:
    if type(function) is not types.FunctionType:
        return False
    (
        code,
        globals_dict,
        module_name,
        qualname,
        defaults,
        defaults_snapshot,
        kwdefaults,
        kwdefaults_snapshot,
        closure,
        closure_values,
        attributes,
    ) = snapshot
    return (
        function.__code__ is code
        and function.__globals__ is globals_dict
        and function.__module__ == module_name
        and function.__qualname__ == qualname
        and function.__defaults__ is defaults
        and _safe_value_snapshot(function.__defaults__) == defaults_snapshot
        and function.__kwdefaults__ is kwdefaults
        and _safe_value_snapshot(function.__kwdefaults__) == kwdefaults_snapshot
        and function.__closure__ is closure
        and tuple(cell.cell_contents for cell in function.__closure__ or ()) == closure_values
        and len(function.__dict__) == len(attributes)
        and all(function.__dict__.get(name) is value for name, value in attributes)
    )


def _norm(path: str | Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path))).replace(chr(92), "/").rstrip("/")


def _safe_code(value: Any) -> str:
    candidate = getattr(value, "code", None) or getattr(value, "reason", None)
    return (
        candidate
        if type(candidate) is str and _SAFE_CODE.fullmatch(candidate)
        else "caller_blocked"
    )


def _code_index(raw: bytes, origin: str) -> dict[str, tuple[types.CodeType, ...]]:
    try:
        root_code = compile(raw, origin, "exec", dont_inherit=True)
    except Exception:
        raise CallerError("source_compile_failed") from None
    pending = [root_code]
    found: dict[str, list[types.CodeType]] = {}
    while pending:
        code = pending.pop()
        qualname = getattr(code, "co_qualname", code.co_name)
        found.setdefault(qualname, []).append(code)
        pending.extend(value for value in code.co_consts if isinstance(value, types.CodeType))
    return {name: tuple(codes) for name, codes in found.items()}


def _source_execution_guard(raw_sources: Mapping[str, bytes]) -> tuple[Any, set[str]]:
    expected = {}
    for origin, raw in raw_sources.items():
        if not origin.casefold().endswith(".py"):
            continue
        expected[_norm(origin)] = compile(raw, origin, "exec", dont_inherit=True)
    executed: set[str] = set()
    blocked_imports = {
        "bt_api",
        "bt_api_py",
        "ccxt",
        "okx",
        "binance",
        "binance_sdk",
        "binance_common",
        "bitget",
        "bybit",
        "gate_api",
        "requests",
        "httpx",
        "aiohttp",
        "urllib3",
        "websocket",
        "websockets",
        "vnpy",
        "ctp",
        "tqsdk",
    }
    blocked_events = {
        "socket.connect",
        "socket.connect_ex",
        "socket.getaddrinfo",
        "socket.bind",
        "socket.listen",
        "socket.sendto",
        "subprocess.Popen",
        "os.system",
        "os.posix_spawn",
        "os.spawn",
        "os.fork",
        "os.forkpty",
        "os.exec",
        "os.startfile",
    }

    def audit(event: str, args: tuple[Any, ...]) -> None:
        if event == "exec" and args:
            code = args[0]
            filename = getattr(code, "co_filename", None)
            if type(filename) is str and _norm(filename) in expected:
                origin = _norm(filename)
                if code != expected[origin]:
                    raise CallerError("pinned_source_code_object_mismatch")
                executed.add(origin)
        elif event == "import" and args and type(args[0]) is str:
            if args[0].split(".", 1)[0].casefold() in blocked_imports:
                raise CallerError("provider_sdk_import_denied")
        elif event in blocked_events:
            raise CallerError("external_operation_denied")
        elif event == "open" and args:
            path = args[0]
            if isinstance(path, (str, bytes, os.PathLike)):
                text = os.fsdecode(os.fspath(path)).replace(chr(92), "/").casefold()
                basename = text.rsplit("/", 1)[-1]
                if (
                    basename == ".env"
                    or basename.startswith(".env.")
                    or basename in {"config.yaml", "config.yml", "secrets.yaml", "credentials.yaml"}
                    or "private-capture" in text
                    or "private_capture" in text
                ):
                    raise CallerError("private_input_open_denied")

    return audit, executed


def _verify_function(
    function: Any,
    module: Any,
    code_index: Mapping[str, tuple[types.CodeType, ...]],
    origin: str,
    qualname: str,
) -> None:
    if (
        type(function) is not types.FunctionType
        or function.__globals__ is not module.__dict__
        or function.__module__ != module.__name__
        or function.__qualname__ != qualname
        or _norm(function.__code__.co_filename) != _norm(origin)
        or function.__code__ not in code_index.get(qualname, ())
    ):
        raise CallerError("source_function_binding_mismatch")


def _verify_literal_module_globals(
    module: Any, raw: bytes, ignored: frozenset[str] = frozenset()
) -> None:
    try:
        tree = ast.parse(raw, filename=str(getattr(module, "__file__", "")))
    except Exception:
        raise CallerError("caller_source_parse_failed") from None
    for statement in tree.body:
        if isinstance(statement, ast.Assign):
            targets = statement.targets
            value_node = statement.value
        elif isinstance(statement, ast.AnnAssign) and statement.value is not None:
            targets = [statement.target]
            value_node = statement.value
        else:
            continue
        try:
            literal = ast.literal_eval(value_node)
        except Exception:
            continue
        for target in targets:
            if not isinstance(target, ast.Name) or target.id in ignored:
                continue
            current = module.__dict__.get(target.id, object())
            if type(current) is not type(literal) or current != literal:
                raise CallerError("caller_literal_global_mismatch")


def _verify_caller_computed_globals(module: Any, root: Path) -> None:
    expected_root = Path(root)
    expected_evidence = expected_root / (
        "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence"
    )
    expected_packet = expected_evidence / (
        "iteration41-okx-m01-root-helper-lifecycle-integration-r1-2026-10-09"
    )
    checks = (
        ("ROOT", expected_root),
        ("EVIDENCE_ROOT", expected_evidence),
        ("CURRENT_PACKET", expected_packet),
        (
            "SOURCE_MAP_RELATIVE",
            "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-okx-m01-root-helper-lifecycle-integration-r1-2026-10-09/source-map.json",
        ),
        (
            "SOURCE_INDEX_RELATIVE",
            "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-okx-m01-root-helper-lifecycle-integration-r1-2026-10-09/source-index.json",
        ),
    )
    for name, expected in checks:
        if (
            type(module.__dict__.get(name)) is not type(expected)
            or module.__dict__[name] != expected
        ):
            raise CallerError("caller_computed_global_mismatch")


def _verify_cuv2_software_pin(software_pins: Mapping[str, str]) -> None:
    if software_pins.get(CUV2_SOFTWARE_ORIGIN) != CUV2_SOURCE_SHA256:
        raise CallerError("cuv2_software_source_pin_mismatch")


def _validate_output_directory(path: Path, root: Path) -> Path:
    expected_parent = Path(root) / (
        "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence"
    )
    candidate = Path(path)
    if (
        candidate.name != ACTUAL_OUTPUT_NAME
        or _norm(candidate.parent) != _norm(expected_parent)
        or not expected_parent.is_dir()
        or candidate.exists()
    ):
        raise CallerError("output_namespace_not_fresh")
    candidate.mkdir(exist_ok=False)
    return candidate


def _gate_module_snapshot(
    module: Any,
    raw: bytes,
    origin: str,
    *,
    ignored_state_names: frozenset[str] = frozenset(),
) -> tuple[Any, ...]:
    if (
        type(getattr(module, "__name__", None)) is not str
        or _norm(getattr(module, "__file__", "")) != _norm(origin)
        or _norm(getattr(getattr(module, "__spec__", None), "origin", "")) != _norm(origin)
    ):
        raise CallerError("gate_module_origin_mismatch")
    index = _code_index(raw, origin)
    classes = []
    functions = []
    for name, value in tuple(module.__dict__.items()):
        if type(value) is types.FunctionType and value.__module__ == module.__name__:
            _verify_function(value, module, index, origin, value.__qualname__)
            functions.append(
                (
                    module,
                    name,
                    value,
                    value.__code__,
                    value.__defaults__,
                    _safe_value_snapshot(value.__defaults__),
                    value.__kwdefaults__,
                    _safe_value_snapshot(value.__kwdefaults__),
                )
            )
        elif isinstance(value, type) and value.__module__ == module.__name__:
            classes.append(
                (
                    name,
                    value,
                    tuple(
                        (member_name, member, _safe_value_snapshot(member))
                        for member_name, member in vars(value).items()
                    ),
                )
            )
            for member_name, member in tuple(vars(value).items()):
                if isinstance(member, (staticmethod, classmethod)):
                    member = member.__func__
                elif isinstance(member, property):
                    for accessor in (member.fget, member.fset, member.fdel):
                        if accessor is not None:
                            _verify_function(accessor, module, index, origin, accessor.__qualname__)
                            functions.append(
                                (
                                    value,
                                    member_name,
                                    accessor,
                                    accessor.__code__,
                                    accessor.__defaults__,
                                    _safe_value_snapshot(accessor.__defaults__),
                                    accessor.__kwdefaults__,
                                    _safe_value_snapshot(accessor.__kwdefaults__),
                                )
                            )
                    continue
                if type(member) is types.FunctionType and member.__module__ == module.__name__:
                    _verify_function(member, module, index, origin, member.__qualname__)
                    functions.append(
                        (
                            value,
                            member_name,
                            member,
                            member.__code__,
                            member.__defaults__,
                            _safe_value_snapshot(member.__defaults__),
                            member.__kwdefaults__,
                            _safe_value_snapshot(member.__kwdefaults__),
                        )
                    )
    globals_before = tuple(
        (name, value, _safe_value_snapshot(value))
        for name, value in module.__dict__.items()
        if name not in ignored_state_names
    )
    return (
        module,
        module.__dict__,
        origin,
        globals_before,
        tuple(ignored_state_names),
        tuple(classes),
        tuple(functions),
    )


def _gate_snapshot_unchanged(snapshot: tuple[Any, ...]) -> bool:
    module, namespace, origin, globals_before, ignored_names, classes, functions = snapshot
    if (
        module.__dict__ is not namespace
        or len(namespace) != len(globals_before) + len(ignored_names)
        or _norm(getattr(module, "__file__", "")) != _norm(origin)
        or _norm(getattr(getattr(module, "__spec__", None), "origin", "")) != _norm(origin)
    ):
        return False
    if any(name not in namespace for name in ignored_names):
        return False
    if any(
        namespace.get(name) is not value
        or _safe_value_snapshot(namespace.get(name)) != expected_snapshot
        for name, value, expected_snapshot in globals_before
    ):
        return False
    for name, class_object, class_items in classes:
        current_items = tuple(vars(class_object).items())
        if (
            namespace.get(name) is not class_object
            or len(current_items) != len(class_items)
            or any(
                current[0] != expected[0]
                or current[1] is not expected[1]
                or _safe_value_snapshot(current[1]) != expected[2]
                for current, expected in zip(current_items, class_items)
            )
        ):
            return False
    for (
        owner,
        name,
        function,
        code,
        defaults,
        defaults_snapshot,
        kwdefaults,
        kwdefaults_snapshot,
    ) in functions:
        current = vars(owner).get(name)
        if isinstance(current, (staticmethod, classmethod)):
            current = current.__func__
        elif isinstance(current, property):
            current = current.fget
        if (
            current is not function
            or current.__code__ is not code
            or current.__globals__ is not namespace
            or current.__defaults__ is not defaults
            or _safe_value_snapshot(current.__defaults__) != defaults_snapshot
            or current.__kwdefaults__ is not kwdefaults
            or _safe_value_snapshot(current.__kwdefaults__) != kwdefaults_snapshot
        ):
            return False
    return True


def _module_origins(
    modules: Mapping[str, Any], paths: Mapping[str, Path], root: Path
) -> tuple[tuple[str, Any], ...]:
    if set(modules) != set(MODULE_SPECS):
        raise CallerError("dependency_module_set_invalid")
    refs = []
    for key, module in modules.items():
        expected_name, _relative, _digest, _size = MODULE_SPECS[key]
        path = paths[key]
        if (
            module.__name__ != expected_name
            or _norm(module.__file__) != _norm(path)
            or _norm(getattr(getattr(module, "__spec__", None), "origin", "")) != _norm(path)
            or sys.modules.get(expected_name) is not module
        ):
            raise CallerError("dependency_module_origin_mismatch")
        refs.append((expected_name, module))
    for name, relative in PACKAGE_SPECS.items():
        module = sys.modules.get(name)
        expected_path = Path(root) / relative
        if (
            module is None
            or _norm(getattr(module, "__file__", "")) != _norm(expected_path)
            or _norm(getattr(getattr(module, "__spec__", None), "origin", ""))
            != _norm(expected_path)
        ):
            raise CallerError("dependency_package_origin_mismatch")
        refs.append((name, module))
    if not {name for name, _module in refs} >= REQUIRED_PACKAGE_MODULES:
        raise CallerError("dependency_module_set_incomplete")
    owned_names = {
        name
        for name in sys.modules
        if name.startswith(
            ("_certification", "_m01_readonly_monitor_v2", "_m01_readonly_monitor_v3")
        )
    }
    if owned_names != REQUIRED_PACKAGE_MODULES:
        raise CallerError("dependency_module_set_unexpected")
    return tuple(refs)


def _module_refs_unchanged(refs: tuple[tuple[str, Any], ...]) -> bool:
    return all(sys.modules.get(name) is module for name, module in refs)


def _module_origins_unchanged(
    modules: Mapping[str, Any], paths: Mapping[str, Path], root: Path
) -> bool:
    try:
        _module_origins(modules, paths, root)
    except CallerError:
        return False
    return True


def _module_globals_unchanged(
    snapshots: tuple[tuple[Any, dict[str, Any], tuple[tuple[str, Any, Any], ...]], ...]
) -> bool:
    return all(
        module.__dict__ is namespace
        and len(namespace) == len(values)
        and all(
            namespace.get(name) is value and _safe_value_snapshot(namespace.get(name)) == snapshot
            for name, value, snapshot in values
        )
        for module, namespace, values in snapshots
    )


def _module_globals_snapshot(module: types.ModuleType) -> tuple[Any, ...]:
    return (
        module,
        module.__dict__,
        tuple(
            (name, value, _safe_value_snapshot(value)) for name, value in module.__dict__.items()
        ),
    )


def _bind_cuv2_method(
    module: Any, origin: Path, source_raw: bytes, root: Path
) -> tuple[
    types.FunctionType,
    types.FunctionType,
    tuple[Any, ...],
    tuple[Any, ...],
    tuple[tuple[str, types.FunctionType, tuple[Any, ...]], ...],
]:
    if (
        not isinstance(module, types.ModuleType)
        or _norm(getattr(module, "__file__", "")) != _norm(origin)
        or _norm(getattr(getattr(module, "__spec__", None), "origin", "")) != _norm(origin)
        or type(getattr(module, "__name__", None)) is not str
        or sys.modules.get(module.__name__) is not module
    ):
        raise CallerError("cuv2_module_origin_invalid")
    if type(source_raw) is not bytes or len(source_raw) != CUV2_SOURCE_BYTES:
        raise CallerError("cuv2_source_bytes_invalid")
    if _sha(source_raw) != CUV2_SOURCE_SHA256:
        raise CallerError("cuv2_source_pin_mismatch")
    code_index = _code_index(source_raw, str(origin))
    try:
        tree = ast.parse(source_raw, filename=str(origin))
    except Exception:
        raise CallerError("cuv2_source_parse_failed") from None
    source_function_names = {
        node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    expected_function_names = {"check", "sha", "load", "held_public_sources"}
    actual_function_names = {
        name
        for name, value in module.__dict__.items()
        if type(value) is types.FunctionType and value.__module__ == module.__name__
    }
    if (
        source_function_names != expected_function_names
        or actual_function_names != expected_function_names
    ):
        raise CallerError("cuv2_function_set_invalid")
    _verify_literal_module_globals(module, source_raw)
    expected_imports = {
        "__builtins__": builtins.__dict__,
        "ExitStack": contextlib.ExitStack,
        "contextmanager": contextlib.contextmanager,
        "Path": Path,
        "hashlib": hashlib,
        "sys": sys,
        "types": types,
    }
    if any(
        module.__dict__.get(name) is not expected for name, expected in expected_imports.items()
    ):
        raise CallerError("cuv2_import_binding_invalid")
    if type(module.__dict__.get("ROOT")) is not type(root) or root != module.ROOT:
        raise CallerError("cuv2_root_binding_invalid")
    source_function_snapshots = []
    for name in sorted(expected_function_names - {"held_public_sources"}):
        function = module.__dict__.get(name)
        _verify_function(function, module, code_index, str(origin), name)
        if (
            function.__defaults__ is not None
            or function.__kwdefaults__ is not None
            or function.__closure__ is not None
        ):
            raise CallerError("cuv2_function_defaults_invalid")
        source_function_snapshots.append((name, function, _function_binding_snapshot(function)))
    method = module.__dict__.get("held_public_sources")
    wrapped = getattr(method, "__wrapped__", None)
    wrapper_reference = _contextmanager_wrapper_reference()
    if (
        type(method) is not types.FunctionType
        or type(wrapped) is not types.FunctionType
        or not inspect.isgeneratorfunction(wrapped)
        or wrapped.__globals__ is not module.__dict__
        or wrapped.__module__ != module.__name__
        or wrapped.__qualname__ != "held_public_sources"
        or _norm(wrapped.__code__.co_filename) != _norm(origin)
        or wrapped.__code__ not in code_index.get("held_public_sources", ())
        or wrapped.__defaults__ is not None
        or wrapped.__kwdefaults__ is not None
        or wrapped.__closure__ is not None
        or method.__code__ is not wrapper_reference.__code__
        or method.__globals__ is not wrapper_reference.__globals__
        or method.__defaults__ != wrapper_reference.__defaults__
        or method.__kwdefaults__ != wrapper_reference.__kwdefaults__
        or method.__module__ != module.__name__
        or method.__qualname__ != "held_public_sources"
        or getattr(method, "__wrapped__", None) is not wrapped
        or method.__closure__ is None
        or len(method.__closure__) != 1
        or method.__closure__[0].cell_contents is not wrapped
    ):
        raise CallerError("cuv2_method_binding_invalid")
    source_function_snapshots.append(
        ("held_public_sources", method, _function_binding_snapshot(method))
    )
    return (
        method,
        wrapped,
        _function_binding_snapshot(method),
        _function_binding_snapshot(wrapped),
        tuple(source_function_snapshots),
    )


def _cuv2_function_bindings_unchanged(
    module: types.ModuleType,
    snapshots: tuple[tuple[str, types.FunctionType, tuple[Any, ...]], ...],
) -> bool:
    return all(
        module.__dict__.get(name) is function and _function_binding_unchanged(function, snapshot)
        for name, function, snapshot in snapshots
    )


def _enter_cuv2_scope(
    scope: Any, wrapped: types.FunctionType, module: types.ModuleType
) -> tuple[types.GeneratorType, dict[str, Any], Any]:
    manager_type = getattr(contextlib, "_GeneratorContextManager", None)
    generator = getattr(scope, "gen", None)
    if (
        type(scope) is not manager_type
        or type(generator) is not types.GeneratorType
        or generator.gi_code is not wrapped.__code__
        or generator.gi_frame is None
        or generator.gi_frame.f_globals is not module.__dict__
    ):
        raise CallerError("cuv2_scope_generator_binding_invalid")
    module_globals = generator.gi_frame.f_globals
    held = contextlib._GeneratorContextManager.__enter__(scope)
    if (
        scope.gen is not generator
        or generator.gi_frame is None
        or generator.gi_frame.f_globals is not module_globals
        or module_globals is not module.__dict__
    ):
        raise CallerError("cuv2_scope_generator_rebound")
    return generator, module_globals, held


def _bind_five_modules(
    gate_module: Any,
    modules: Mapping[str, Any],
    sources: Mapping[str, tuple[bytes, Path]],
) -> tuple[tuple[Any, ...], ...]:
    snapshots = []
    for key in MODULE_SPECS:
        module = modules[key]
        raw, path = sources[key]
        code_index = gate_module._source_code_index(raw, path)
        snapshot, sourcefake = gate_module._module_source_bindings(
            module,
            raw,
            path,
            code_index,
            allow_runtime_hold_fake=False,
        )
        if sourcefake is not False:
            raise CallerError("production_runtime_holder_is_sourcefake")
        snapshots.append(snapshot)
    return tuple(snapshots)


def _bind_gate_module(gate_module: Any, raw: bytes, path: Path) -> tuple[Any, ...]:
    code_index = gate_module._source_code_index(raw, path)
    snapshot, sourcefake = gate_module._module_source_bindings(
        gate_module,
        raw,
        path,
        code_index,
        allow_runtime_hold_fake=False,
    )
    if sourcefake is not False:
        raise CallerError("gate_sourcefake_binding_rejected")
    return snapshot


def _snapshots_unchanged(gate_module: Any, snapshots: tuple[tuple[Any, ...], ...]) -> bool:
    return gate_module._module_bindings_unchanged(snapshots) is True


def _require_empty_registry(module: Any, name: str) -> list[Any]:
    value = module.__dict__.get(name)
    if type(value) is not list or value:
        raise CallerError("retained_registry_not_fresh")
    return value


def _registries_unchanged(references: tuple[tuple[Any, str, list[Any]], ...]) -> bool:
    return all(
        type(expected) is list
        and not expected
        and module.__dict__.get(name) is expected
        and type(module.__dict__.get(name)) is list
        for module, name, expected in references
    )


def _validate_gate_result(result: Any) -> dict[str, Any]:
    if type(result) is not dict:
        raise CallerError("gate_result_type_invalid")
    if result.get("schema") != "iteration41.okx.m01.root-helper-lifecycle-gate.v6":
        raise CallerError("gate_result_schema_invalid")
    statuses = {
        "LOCAL_SYNTHETIC_CHILD",
        "SOURCE_FAKE_ONLY",
        "LIFECYCLE_BLOCKED",
        "CLEANUP_UNCONFIRMED",
        "OUTPUT_MISMATCH",
    }
    if result.get("status") not in statuses:
        raise CallerError("gate_result_status_invalid")
    if result.get("phase") not in PHASES:
        raise CallerError("gate_result_phase_invalid")
    for name in GATE_TRUE_FIELDS:
        if type(result.get(name)) is not bool:
            raise CallerError("gate_result_boolean_shape_invalid")
    for name in GATE_FALSE_FIELDS:
        if type(result.get(name)) is not bool:
            raise CallerError("gate_result_boolean_shape_invalid")
    for name in ("error_category", "error_code", "job_count_after_cleanup_error"):
        value = result.get(name)
        if value is not None and (type(value) is not str or not _SAFE_CODE.fullmatch(value)):
            raise CallerError("gate_result_code_invalid")
    if (
        type(result.get("source_bytes_held")) is not int
        or not 0 <= result["source_bytes_held"] <= 5
    ):
        raise CallerError("gate_source_byte_count_invalid")
    if (
        type(result.get("handle_close_failures")) is not int
        or not 0 <= result["handle_close_failures"] <= 65535
    ):
        raise CallerError("gate_handle_close_failures_present")
    handle_close_calls = result.get("handle_close_calls")
    if type(handle_close_calls) is not int or not 0 <= handle_close_calls <= 65535:
        raise CallerError("gate_handle_close_calls_invalid")
    waits = result.get("wait_results")
    if type(waits) is not tuple or len(waits) > 4 or any(type(item) is not bool for item in waits):
        raise CallerError("gate_wait_observation_invalid")
    cleanup_wait_attempted = result.get("cleanup_wait_attempted")
    cleanup_wait_succeeded = result.get("cleanup_wait_succeeded")
    if type(cleanup_wait_attempted) is not bool or type(cleanup_wait_succeeded) is not bool:
        raise CallerError("gate_cleanup_wait_observation_invalid")
    job_observations = result.get("job_count_observations")
    if type(job_observations) is not tuple or len(job_observations) > _MAX_JOB_OBSERVATIONS:
        raise CallerError("gate_job_observations_invalid")
    for item in job_observations:
        if (
            type(item) is not tuple
            or len(item) != 2
            or item[0] not in PHASES
            or type(item[1]) is not int
            or not 0 <= item[1] <= 65535
        ):
            raise CallerError("gate_job_observations_invalid")
    win32_names = {
        "CloseHandle",
        "CreateFileW",
        "GetFileInformationByHandle",
        "GetFinalPathNameByHandleW",
        "GetFileSizeEx",
        "CreateJobObjectW",
        "SetInformationJobObject",
        "QueryInformationJobObject",
        "CreatePipe",
        "SetHandleInformation",
        "CreateProcessW",
        "InitializeProcThreadAttributeList",
        "UpdateProcThreadAttribute",
        "DeleteProcThreadAttributeList",
        "AssignProcessToJobObject",
        "ResumeThread",
        "WaitForSingleObject",
        "TerminateJobObject",
        "TerminateProcess",
        "GetExitCodeProcess",
        "ReadFile",
        "WriteFile",
        "other_win32_call",
    }
    win32_api = result.get("win32_api")
    if win32_api is not None and win32_api not in win32_names:
        raise CallerError("gate_result_win32_api_invalid")
    native_phase = result.get("native_failure_phase")
    if native_phase is not None and native_phase not in PHASES:
        raise CallerError("gate_result_phase_invalid")
    winerror = result.get("winerror")
    if winerror is not None and (type(winerror) is not int or not 0 < winerror <= 65535):
        raise CallerError("gate_result_winerror_invalid")
    reader_count = result.get("reader_retained_context_count_after")
    if reader_count is not None and (
        type(reader_count) is not int or not 0 <= reader_count <= 65535
    ):
        raise CallerError("gate_reader_registry_count_invalid")
    captured_reader_count = result.get("reader_retained_context_count_captured_after")
    if captured_reader_count is not None and (
        type(captured_reader_count) is not int or not 0 <= captured_reader_count <= 65535
    ):
        raise CallerError("gate_reader_registry_count_invalid")
    projection = {
        "schema": result["schema"],
        "status": result["status"],
        "phase": result["phase"],
        "error_category": result.get("error_category"),
        "error_code": result.get("error_code"),
        "job_count_after_cleanup_error": result.get("job_count_after_cleanup_error"),
        "source_bytes_held": result["source_bytes_held"],
        "win32_api": win32_api,
        "native_failure_phase": native_phase,
        "winerror": winerror,
        "reader_retained_context_count_after": reader_count,
        "reader_retained_context_count_captured_after": captured_reader_count,
        "handle_close_failures": result["handle_close_failures"],
        "handle_close_calls": handle_close_calls,
        "cleanup_wait_attempted": cleanup_wait_attempted,
        "cleanup_wait_succeeded": cleanup_wait_succeeded,
        "wait_results": list(waits),
        "job_count_observations": [list(item) for item in job_observations],
    }
    projection.update({name: result[name] for name in (*GATE_TRUE_FIELDS, *GATE_FALSE_FIELDS)})
    return projection


def _clean_gate_facts(facts: Mapping[str, Any]) -> bool:
    count_observations = facts.get("job_count_observations", ())
    expected_phases = {item[0] for item in count_observations}
    counts_by_phase: dict[str, list[int]] = {}
    for phase, count in count_observations:
        counts_by_phase.setdefault(phase, []).append(count)
    zero_after_exit = counts_by_phase.get("job_count_after_exit", ())
    zero_after_cleanup = counts_by_phase.get("job_count_after_cleanup", ())
    return (
        facts.get("status") == "LOCAL_SYNTHETIC_CHILD"
        and facts.get("phase") == "complete"
        and all(facts.get(name) is True for name in GATE_TRUE_FIELDS)
        and all(facts.get(name) is False for name in GATE_FALSE_FIELDS)
        and facts.get("error_category") is None
        and facts.get("error_code") is None
        and facts.get("job_count_after_cleanup_error") is None
        and facts.get("win32_api") is None
        and facts.get("native_failure_phase") is None
        and facts.get("winerror") is None
        and facts.get("source_bytes_held") == 5
        and facts.get("handle_close_failures") == 0
        and facts.get("handle_close_calls", 0) > 0
        and facts.get("wait_results") == [True, True]
        and facts.get("cleanup_wait_attempted") is True
        and facts.get("cleanup_wait_succeeded") is True
        and {"job_count_after_exit", "job_count_after_cleanup"} <= expected_phases
        and bool(zero_after_exit)
        and all(count == 0 for count in zero_after_exit)
        and bool(zero_after_cleanup)
        and all(count == 0 for count in zero_after_cleanup)
        and facts.get("source_fake_only") is False
        and facts.get("production_acceptance") is False
        and facts.get("retained_context") is False
        and facts.get("process_exit_code_zero") is True
        and facts.get("job_zero_after_exit") is True
        and facts.get("job_zero_after_cleanup") is True
        and facts.get("stdout_eof") is True
        and facts.get("stderr_eof") is True
        and facts.get("stdout_thread_joined") is True
        and facts.get("stderr_thread_joined") is True
        and facts.get("all_observed_handles_closed") is True
        and facts.get("handle_close_failures") == 0
        and facts.get("runtime_registry_empty_after") is True
        and facts.get("reader_retained_contexts_empty_after") is True
        and facts.get("reader_retained_context_count_after") == 0
        and facts.get("reader_retained_context_count_captured_after") == 0
    )


def _write_observation(directory: Path, observation: Mapping[str, Any]) -> None:
    raw = (json.dumps(observation, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")
    if len(raw) > _MAX_RESULT_BYTES:
        raise CallerError("observation_size_invalid")
    with (directory / "observation.json").open("xb") as stream:
        stream.write(raw)


def _safe_registry_count(module: Any, name: str) -> int | None:
    if not isinstance(module, types.ModuleType):
        return None
    value = module.__dict__.get(name)
    return len(value) if type(value) is list else None


def _verify_source_index_rows(source_index: Any) -> list[Any]:
    if (
        type(source_index) is not dict
        or source_index.get("archive_member_count") != SOURCE_INDEX_ROW_COUNT
        or type(source_index.get("rows")) is not list
        or len(source_index["rows"]) != SOURCE_INDEX_ROW_COUNT
    ):
        raise CallerError("source_index_row_count_invalid")
    return source_index["rows"]


def _expected_public_pin_paths(indexed_paths: set[str]) -> set[str]:
    return set(indexed_paths) | {
        SOURCE_MAP_RELATIVE,
        SOURCE_INDEX_RELATIVE,
        CUV2_SOURCE_RELATIVE,
        CALLER_RELATIVE,
        CALLER_TEST_RELATIVE,
    }


def _retain_state(state: dict[str, Any], nonce_hash: str) -> None:
    if state.get("retained_python_references"):
        return
    _RETAINED_CONTEXTS.append(
        (
            state.get("cu_module"),
            state.get("cu_method"),
            state.get("cu_wrapped"),
            state.get("cuv2_source_raw"),
            state.get("cu_function_snapshots"),
            state.get("scope_generator"),
            state.get("scope_generator_globals"),
            state.get("raw_source_bytes"),
            state.get("scope"),
            state.get("held"),
            state.get("gate"),
            state.get("modules"),
            state.get("module_snapshots"),
            state.get("gate_snapshot"),
            state.get("gate_module_bindings"),
            nonce_hash,
        )
    )
    state["retained_python_references"] = True


def _set_scope_exit_state(state: Mapping[str, Any], result: dict[str, Any]) -> None:
    attempted = state.get("scope_exit_attempted") is True
    confirmed = state.get("scope_exit_confirmed") is True
    result["scope_exit_attempted"] = attempted
    result["scope_exit_confirmed"] = confirmed
    if confirmed:
        result["scope_exit_state"] = "closed_verified"
    elif attempted:
        result["scope_exit_state"] = "unconfirmed"
    elif state.get("scope") is not None:
        result["scope_exit_state"] = "still_open"
    else:
        result["scope_exit_state"] = "not_started"


def _close_scope_if_clean(
    scope: Any,
    generator: Any,
    module_globals: dict[str, Any],
    state: dict[str, Any],
    result: dict[str, Any],
    *,
    clean_facts: bool,
) -> None:
    if clean_facts is not True:
        raise CallerError("gate_cleanup_not_certain")
    manager_type = getattr(contextlib, "_GeneratorContextManager", None)
    if (
        type(scope) is not manager_type
        or scope.gen is not generator
        or type(generator) is not types.GeneratorType
        or generator.gi_frame is None
        or generator.gi_frame.f_globals is not module_globals
    ):
        raise CallerError("cuv2_scope_binding_changed_before_exit")
    state["scope_exit_attempted"] = True
    state["scope_exit_state"] = "unconfirmed"
    result["scope_exit_attempted"] = True
    result["scope_exit_state"] = "unconfirmed"
    exit_result = contextlib._GeneratorContextManager.__exit__(scope, None, None, None)
    if exit_result is not False or scope.gen is not generator or generator.gi_frame is not None:
        raise CallerError("cuv2_normal_exit_not_false_or_reaped")
    state["scope_exit_confirmed"] = True
    state["scope_exit_state"] = "closed_verified"
    result["scope_exit_confirmed"] = True
    result["scope_exit_state"] = "closed_verified"


def run_one(
    cu_module: Any,
    *,
    cuv2_source_raw: bytes,
    public_pins: Mapping[str, str],
    software_pins: Mapping[str, str],
    root_nonce: str,
    output_dir: Path,
    root: Path = ROOT,
) -> dict[str, Any]:
    """Acquire normal CUv2 custody and call the fixed R7 probe once.

    Root supplies the exact public CUv2 snapshot bytes before this caller
    enters its source generator. The module loader is fixed to the pinned
    repository imports; test seams do not replace those production modules.
    """
    global _INVOCATION_STARTED
    if _INVOCATION_STARTED:
        raise CallerError("caller_already_used")
    _INVOCATION_STARTED = True
    if type(root_nonce) is not str or not _SAFE_NONCE.fullmatch(root_nonce):
        raise CallerError("root_nonce_invalid")
    nonce_hash = _sha(root_nonce.encode("ascii"))
    output_dir = Path(output_dir)
    state: dict[str, Any] = {
        "cu_module": cu_module,
        "cu_method": None,
        "cu_globals": None,
        "cu_global_values": (),
        "cuv2_source_raw": cuv2_source_raw,
        "cu_function_snapshots": (),
        "scope": None,
        "held": None,
        "raw_source_bytes": None,
        "gate": None,
        "modules": {},
        "module_snapshots": (),
        "gate_snapshot": None,
        "gate_module_bindings": (),
        "gate_invocations": 0,
        "scope_exit_attempted": False,
        "scope_exit_confirmed": False,
        "scope_exit_state": "not_started",
        "retained_python_references": False,
        "sys_path_object": None,
        "sys_path_values": (),
    }
    result: dict[str, Any] = {
        "schema": "iteration41.okx.m01.r7_root_caller.v1",
        "operation": "FIXED_CREDENTIAL_FREE_LOCAL_CHILD",
        "status": "BLOCKED",
        "reason": None,
        "root_nonce_sha256": nonce_hash,
        "gate_invocations": 0,
        "source_count": 0,
        "source_pre_post_bindings_verified": False,
        "gate_cleanup_facts_verified": False,
        "outer_normal_postverify_and_close": False,
        "cuv2_origin_verified": False,
        "cuv2_source_pin_verified": False,
        "cuv2_method_identity_unchanged": False,
        "cuv2_global_state_unchanged": False,
        "software_pins_verified_by_cuv2": False,
        "host_exit_permitted": False,
        "account_provider_operations": False,
        "private_inputs_read": False,
        "caller_opened_opaque_software_payload": False,
        "software_payload_bytes_returned_to_caller": False,
        "opaque_software_payload_read_by_caller": False,
        "formal_m01_pass_count": 0,
        "gate_result": None,
        "retained_python_references": False,
        "scope_exit_attempted": False,
        "scope_exit_confirmed": False,
        "scope_exit_state": "not_started",
    }
    phase = "source_custody"
    try:
        if os.name != "nt":
            raise CallerError("windows_required")
        if _norm(root) != _norm(ROOT):
            raise CallerError("fixed_repository_root_mismatch")
        output_dir = _validate_output_directory(output_dir, Path(root))
        if type(public_pins) is not dict or type(software_pins) is not dict:
            raise CallerError("custody_pin_map_invalid")
        if public_pins.get(CUV2_SOURCE_RELATIVE) != CUV2_SOURCE_SHA256:
            raise CallerError("cuv2_snapshot_pin_missing")
        if set(software_pins) != SOFTWARE_PIN_KEYS or any(
            type(value) is not str
            or len(value) != 64
            or any(ch not in "0123456789abcdef" for ch in value)
            for value in software_pins.values()
        ):
            raise CallerError("software_pin_map_invalid")
        _verify_cuv2_software_pin(software_pins)
        if any(
            type(relative) is not str
            or Path(relative).is_absolute()
            or ".." in Path(relative).parts
            or type(digest) is not str
            or len(digest) != 64
            or any(ch not in "0123456789abcdef" for ch in digest)
            for relative, digest in public_pins.items()
        ):
            raise CallerError("public_pin_map_invalid")
        current_modules = {
            name
            for name in sys.modules
            if name.startswith(
                (
                    "_certification",
                    "_m01_readonly_monitor_v2",
                    "_m01_readonly_monitor_v3",
                    "_root_m01_r7_gate_",
                )
            )
        }
        if current_modules:
            raise CallerError("module_namespace_not_fresh")
        cuv2_origin = Path("D:/temp/iteration41-root-public-custody-v2.py")
        (
            cu_method,
            cu_wrapped,
            cu_method_snapshot,
            cu_wrapped_snapshot,
            cu_function_snapshots,
        ) = _bind_cuv2_method(cu_module, cuv2_origin, cuv2_source_raw, Path(root))
        state["cu_globals"] = cu_module.__dict__
        state["cu_global_values"] = _module_globals_snapshot(cu_module)
        state["cu_method"] = cu_method
        state["cu_wrapped"] = cu_wrapped
        state["cu_method_snapshot"] = cu_method_snapshot
        state["cu_wrapped_snapshot"] = cu_wrapped_snapshot
        state["cu_function_snapshots"] = cu_function_snapshots
        result["cuv2_origin_verified"] = True
        result["cuv2_source_pin_verified"] = True
        scope = cu_method(dict(public_pins), dict(software_pins))
        state["scope"] = scope
        scope_generator, scope_globals, held = _enter_cuv2_scope(scope, cu_wrapped, cu_module)
        state["scope_generator"] = scope_generator
        state["scope_generator_globals"] = scope_globals
        state["held"] = held
        result["software_pins_verified_by_cuv2"] = True
        if type(held) is not tuple or len(held) < 3 or type(held[2]) is not dict:
            raise CallerError("cuv2_held_shape_invalid")
        raw_sources = held[2]
        state["raw_source_bytes"] = dict(raw_sources)
        normalized_raw = {_norm(path): raw for path, raw in raw_sources.items()}
        expected_paths = {
            _norm(Path(root) / relative): digest for relative, digest in public_pins.items()
        }
        if len(normalized_raw) != len(raw_sources) or len(expected_paths) != len(public_pins):
            raise CallerError("cuv2_source_path_alias")
        if set(normalized_raw) != set(expected_paths):
            raise CallerError("cuv2_source_set_mismatch")
        for path, digest in expected_paths.items():
            raw = normalized_raw[path]
            if type(raw) is not bytes or _sha(raw) != digest or len(raw) > _MAX_SOURCE_BYTES:
                raise CallerError("cuv2_source_pin_mismatch")
        if normalized_raw.get(_norm(Path(root) / CUV2_SOURCE_RELATIVE)) != cuv2_source_raw:
            raise CallerError("cuv2_held_source_mismatch")
        result["source_count"] = len(raw_sources)
        path_by_key = {key: Path(root) / MODULE_SPECS[key][1] for key in MODULE_SPECS}
        gate_path = Path(root) / GATE_RELATIVE
        caller_path = Path(root) / CALLER_RELATIVE
        source_map_raw = normalized_raw[_norm(Path(root) / SOURCE_MAP_RELATIVE)]
        source_index_raw = normalized_raw[_norm(Path(root) / SOURCE_INDEX_RELATIVE)]
        if len(source_map_raw) != SOURCE_MAP_BYTES or _sha(source_map_raw) != SOURCE_MAP_SHA256:
            raise CallerError("source_map_pin_mismatch")
        if (
            len(source_index_raw) != SOURCE_INDEX_BYTES
            or _sha(source_index_raw) != SOURCE_INDEX_SHA256
        ):
            raise CallerError("source_index_pin_mismatch")
        source_map = json.loads(source_map_raw.decode("ascii"))
        source_index = json.loads(source_index_raw.decode("ascii"))
        if (
            source_index.get("schema")
            != "iteration41.okx.m01.root-helper-lifecycle-integration-source-index.v1"
            or source_index.get("source_map_file_sha256") != SOURCE_MAP_SHA256
            or source_index.get("source_map_sha256") != SOURCE_MAP_SHA256
            or source_index.get("source_map_bytes") != SOURCE_MAP_BYTES
            or source_index.get("runtime_source_count") != 19
            or source_index.get("archive_member_count") != SOURCE_INDEX_ROW_COUNT
        ):
            raise CallerError("source_index_metadata_invalid")
        source_rows = source_map.get("source_pins")
        index_rows = _verify_source_index_rows(source_index)
        if type(source_rows) is not dict or len(source_rows) != 19:
            raise CallerError("current_source_inventory_shape_invalid")
        if source_map.get("schema") != "iteration41.okx.m01.case-source-map.v3":
            raise CallerError("source_map_schema_invalid")
        indexed = {row["path"]: row for row in index_rows if type(row) is dict}
        if len(indexed) != len(index_rows):
            raise CallerError("source_index_duplicate_path")
        if not set(source_rows) <= set(indexed):
            raise CallerError("source_index_map_mismatch")
        runtime_paths = {
            path for path, row in indexed.items() if row.get("role") == "runtime_source"
        }
        if runtime_paths != set(source_rows):
            raise CallerError("source_map_runtime_set_mismatch")
        if any(indexed[path].get("sha256") != digest for path, digest in source_rows.items()):
            raise CallerError("source_index_map_mismatch")
        if any(relative not in public_pins for relative in indexed):
            raise CallerError("source_index_pin_missing")
        for relative, row in indexed.items():
            if (
                public_pins.get(relative) != row.get("sha256")
                or type(row.get("bytes")) is not int
                or row["bytes"] < 0
            ):
                raise CallerError("source_index_pin_mismatch")
            indexed_raw = normalized_raw.get(_norm(Path(root) / relative))
            if (
                type(indexed_raw) is not bytes
                or len(indexed_raw) != row["bytes"]
                or _sha(indexed_raw) != row["sha256"]
            ):
                raise CallerError("source_index_source_mismatch")
        expected_pin_paths = _expected_public_pin_paths(set(indexed))
        if (
            len(expected_pin_paths) != ROOT_PUBLIC_PIN_COUNT
            or len(public_pins) != ROOT_PUBLIC_PIN_COUNT
            or set(public_pins) != expected_pin_paths
        ):
            raise CallerError("public_source_pin_set_not_exact")
        expected_supported = {
            GATE_RELATIVE: GATE_SHA256,
            GATE_TEST_RELATIVE: GATE_TEST_SHA256,
            CALLER_RELATIVE: public_pins.get(CALLER_RELATIVE),
            CALLER_TEST_RELATIVE: public_pins.get(CALLER_TEST_RELATIVE),
            CUV2_SOURCE_RELATIVE: CUV2_SOURCE_SHA256,
        }
        for relative, digest in expected_supported.items():
            if type(digest) is not str or public_pins.get(relative) != digest:
                raise CallerError("required_support_source_pin_missing")
        gate_raw = normalized_raw[_norm(gate_path)]
        if len(gate_raw) != GATE_BYTES or _sha(gate_raw) != GATE_SHA256:
            raise CallerError("gate_source_pin_mismatch")
        caller_raw = normalized_raw[_norm(caller_path)]
        caller_module = sys.modules.get(__name__)
        if caller_module is None or _norm(getattr(caller_module, "__file__", "")) != _norm(
            caller_path
        ):
            raise CallerError("caller_source_origin_mismatch")
        _verify_literal_module_globals(
            caller_module, caller_raw, frozenset({"_INVOCATION_STARTED"})
        )
        _verify_caller_computed_globals(caller_module, Path(root))
        caller_snapshot = _gate_module_snapshot(
            caller_module,
            caller_raw,
            str(caller_path),
            ignored_state_names=frozenset({"_INVOCATION_STARTED"}),
        )
        if caller_module.__dict__.get("_INVOCATION_STARTED") is not True:
            raise CallerError("caller_single_use_state_invalid")
        if GATE_TEST_RELATIVE not in public_pins:
            raise CallerError("gate_test_pin_missing")
        raw_by_origin = {
            str(Path(root) / relative): normalized_raw[_norm(Path(root) / relative)]
            for relative in public_pins
            if relative.casefold().endswith(".py")
        }
        audit_hook, executed_sources = _source_execution_guard(raw_by_origin)
        sys.addaudithook(audit_hook)
        phase = "module_loading"
        original_sys_path = sys.path
        prior_path = tuple(original_sys_path)
        state["sys_path_object"] = original_sys_path
        state["sys_path_values"] = prior_path
        venue = Path(root) / "examples/000_live_certification/okx_penetration"
        original_sys_path[:0] = [str(root), str(venue)]
        try:
            modules = {key: importlib.import_module(spec[0]) for key, spec in MODULE_SPECS.items()}
        finally:
            original_sys_path[:] = prior_path
        if sys.path is not original_sys_path:
            raise CallerError("sys_path_object_rebound")
        gate_name = "_root_m01_r7_gate_" + root_nonce[:12]
        if gate_name in sys.modules:
            raise CallerError("gate_namespace_not_fresh")
        gate_module = types.ModuleType(gate_name)
        gate_module.__file__ = str(gate_path)
        gate_module.__package__ = ""
        gate_module.__spec__ = importlib.util.spec_from_file_location(gate_name, gate_path)
        sys.modules[gate_name] = gate_module
        exec(compile(gate_raw, str(gate_path), "exec", dont_inherit=True), gate_module.__dict__)
        state["modules"] = modules
        state["gate"] = gate_module
        gate_snapshot = _gate_module_snapshot(gate_module, gate_raw, str(gate_path))
        state["gate_snapshot"] = gate_snapshot
        state["gate_module_bindings"] = _bind_gate_module(gate_module, gate_raw, gate_path)
        module_refs = _module_origins(modules, path_by_key, Path(root))
        if sys.modules.get(gate_name) is not gate_module:
            raise CallerError("gate_module_registration_invalid")
        module_refs = (
            *module_refs,
            (gate_name, gate_module),
            (cu_module.__name__, cu_module),
            (caller_module.__name__, caller_module),
        )
        source_inputs = {}
        for key, module in modules.items():
            _name, relative, digest, size = MODULE_SPECS[key]
            module_raw = normalized_raw[_norm(Path(root) / relative)]
            if len(module_raw) != size or _sha(module_raw) != digest:
                raise CallerError("guarded_module_pin_mismatch")
            source_inputs[key] = (module, module_raw, str(path_by_key[key]))
        state["module_snapshots"] = _bind_five_modules(
            gate_module,
            modules,
            {key: (value[1], Path(value[2])) for key, value in source_inputs.items()},
        )
        supervisor = modules["supervisor"]
        reader = modules["reader"]
        worker = modules["worker"]
        if not (
            reader.job_supervisor is supervisor
            and reader.worker is worker
            and reader.current_types is modules["current_types"]
            and supervisor.worker is worker
            and supervisor.current_types is modules["current_types"]
            and supervisor.contract is modules["contract"]
        ):
            raise CallerError("module_dependency_identity_mismatch")
        import_refs = module_refs
        import_state = tuple(
            _module_globals_snapshot(module)
            for _name, module in import_refs
            if module is not cu_module
        )
        import_state = (*import_state, state["cu_global_values"])
        required_executions = {
            _norm(Path(root) / relative) for _name, relative in PACKAGE_SPECS.items()
        }
        required_executions.update(_norm(path) for path in path_by_key.values())
        required_executions.add(_norm(gate_path))
        gate_registry = _require_empty_registry(gate_module, "_ORPHANED_GATE_CONTEXTS")
        runtime_registry = _require_empty_registry(supervisor, "_ORPHANED_RUNTIME_HANDLE_SETS")
        reader_registry = _require_empty_registry(reader, "_ROOT_HELPER_RETAINED_CONTEXTS")
        caller_registry = _require_empty_registry(caller_module, "_RETAINED_CONTEXTS")
        registry_refs = (
            (gate_module, "_ORPHANED_GATE_CONTEXTS", gate_registry),
            (supervisor, "_ORPHANED_RUNTIME_HANDLE_SETS", runtime_registry),
            (reader, "_ROOT_HELPER_RETAINED_CONTEXTS", reader_registry),
            (caller_module, "_RETAINED_CONTEXTS", caller_registry),
        )
        source_snapshots = (state["gate_module_bindings"], *state["module_snapshots"])
        if not _snapshots_unchanged(gate_module, source_snapshots):
            raise CallerError("module_binding_precheck_failed")
        if not _gate_snapshot_unchanged(gate_snapshot) or not _gate_snapshot_unchanged(
            caller_snapshot
        ):
            raise CallerError("caller_gate_binding_precheck_failed")
        phase = "gate_call"
        output = _BoundedText()
        state["gate_invocations"] = 1
        result["gate_invocations"] = 1
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            gate_result = gate_module.run_fixed_synthetic_probe(reader, supervisor, worker)
        if output.getvalue():
            raise CallerError("unexpected_gate_output")
        phase = "post_binding_check"
        facts = _validate_gate_result(gate_result)
        result["gate_result"] = facts
        if not _snapshots_unchanged(gate_module, source_snapshots):
            raise CallerError("module_binding_postcheck_failed")
        if not _gate_snapshot_unchanged(gate_snapshot) or not _gate_snapshot_unchanged(
            caller_snapshot
        ):
            raise CallerError("caller_gate_binding_postcheck_failed")
        if not _module_refs_unchanged(import_refs):
            raise CallerError("dependency_module_rebound")
        if not _module_origins_unchanged(modules, path_by_key, Path(root)):
            raise CallerError("dependency_module_origin_postcheck_failed")
        if (
            cu_module.__dict__.get("held_public_sources") is not state["cu_method"]
            or getattr(state["cu_method"], "__wrapped__", None) is not state["cu_wrapped"]
            or not _function_binding_unchanged(state["cu_method"], state["cu_method_snapshot"])
            or not _function_binding_unchanged(state["cu_wrapped"], state["cu_wrapped_snapshot"])
            or not _cuv2_function_bindings_unchanged(cu_module, cu_function_snapshots)
            or _norm(getattr(cu_module, "__file__", "")) != _norm(cuv2_origin)
            or _norm(getattr(getattr(cu_module, "__spec__", None), "origin", ""))
            != _norm(cuv2_origin)
            or state["scope"].gen is not state["scope_generator"]
            or state["scope_generator_globals"] is not cu_module.__dict__
            or state["scope_generator"].gi_frame is None
            or state["scope_generator"].gi_frame.f_globals is not cu_module.__dict__
        ):
            raise CallerError("cuv2_method_rebound")
        if not _module_globals_unchanged(import_state):
            raise CallerError("dependency_module_globals_rebound")
        if not required_executions <= executed_sources:
            raise CallerError("required_source_execution_missing")
        result["required_source_execution_verified"] = True
        result["executed_pinned_source_count"] = len(executed_sources)
        if not _registries_unchanged(registry_refs):
            raise CallerError("retained_registry_postcheck_failed")
        if caller_module.__dict__.get("_INVOCATION_STARTED") is not True:
            raise CallerError("caller_single_use_state_changed")
        if sys.path is not state["sys_path_object"] or tuple(sys.path) != state["sys_path_values"]:
            raise CallerError("sys_path_state_changed")
        result["source_pre_post_bindings_verified"] = True
        result["gate_cleanup_facts_verified"] = _clean_gate_facts(facts)
        if not result["gate_cleanup_facts_verified"]:
            raise CallerError("gate_cleanup_not_certain")
        phase = "outer_source_close"
        _close_scope_if_clean(
            scope,
            state["scope_generator"],
            state["scope_generator_globals"],
            state,
            result,
            clean_facts=result["gate_cleanup_facts_verified"],
        )
        state["scope"] = None
        state["held"] = None
        result["outer_normal_postverify_and_close"] = True
        if (
            not _snapshots_unchanged(gate_module, source_snapshots)
            or not _gate_snapshot_unchanged(gate_snapshot)
            or not _gate_snapshot_unchanged(caller_snapshot)
            or not _module_refs_unchanged(import_refs)
            or not _module_origins_unchanged(modules, path_by_key, Path(root))
            or not _module_globals_unchanged(import_state)
            or sys.path is not state["sys_path_object"]
            or tuple(sys.path) != state["sys_path_values"]
        ):
            raise CallerError("post_close_binding_check_failed")
        if not _registries_unchanged(registry_refs):
            raise CallerError("post_close_registry_check_failed")
        if (
            cu_module.__dict__.get("held_public_sources") is not state["cu_method"]
            or getattr(state["cu_method"], "__wrapped__", None) is not state["cu_wrapped"]
            or not _function_binding_unchanged(state["cu_method"], state["cu_method_snapshot"])
            or not _function_binding_unchanged(state["cu_wrapped"], state["cu_wrapped_snapshot"])
            or not _cuv2_function_bindings_unchanged(cu_module, cu_function_snapshots)
            or _norm(getattr(cu_module, "__file__", ""))
            != _norm(Path("D:/temp/iteration41-root-public-custody-v2.py"))
            or _norm(getattr(getattr(cu_module, "__spec__", None), "origin", ""))
            != _norm(Path("D:/temp/iteration41-root-public-custody-v2.py"))
            or state["scope_generator"].gi_frame is not None
        ):
            raise CallerError("cuv2_method_postclose_rebound")
        result["cuv2_method_identity_unchanged"] = True
        result["cuv2_global_state_unchanged"] = True
        if caller_module.__dict__.get("_INVOCATION_STARTED") is not True:
            raise CallerError("caller_single_use_postclose_changed")
        result["status"] = "LOCAL_SYNTHETIC_CHILD"
        result["host_exit_permitted"] = True
        phase = "complete"
    except BaseException as error:
        result["reason"] = _safe_code(error)
        result["failure_phase"] = phase
        if (
            state["scope"] is not None
            or state["held"] is not None
            or state["gate_invocations"] > 0
            or state["scope_exit_attempted"]
        ):
            _retain_state(state, nonce_hash)
        result["retained_python_references"] = state["retained_python_references"]
    _set_scope_exit_state(state, result)
    result["phase"] = phase
    result["retained_gate_context_count"] = _safe_registry_count(
        state["gate"], "_ORPHANED_GATE_CONTEXTS"
    )
    result["retained_runtime_registry_count"] = _safe_registry_count(
        state["modules"].get("supervisor"), "_ORPHANED_RUNTIME_HANDLE_SETS"
    )
    result["retained_reader_context_count"] = _safe_registry_count(
        state["modules"].get("reader"), "_ROOT_HELPER_RETAINED_CONTEXTS"
    )
    result["caller_retained_reference_count"] = _safe_registry_count(
        sys.modules.get(__name__), "_RETAINED_CONTEXTS"
    )
    result["observation_write_succeeded"] = True
    try:
        _write_observation(output_dir, result)
    except Exception as error:
        if state["scope"] is not None or state["gate_invocations"] > 0:
            _retain_state(state, nonce_hash)
        result["status"] = "BLOCKED"
        result["reason"] = _safe_code(error)
        result["host_exit_permitted"] = False
        result["retained_python_references"] = state["retained_python_references"]
        result["caller_retained_reference_count"] = _safe_registry_count(
            sys.modules.get(__name__), "_RETAINED_CONTEXTS"
        )
        result["observation_write_succeeded"] = False
    return result


__all__ = ["CallerError", "run_one"]
