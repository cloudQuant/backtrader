"""Source-bound, credential-free probe for the repaired M01 root-helper lifecycle.

The actual Root caller must load the five guarded modules freshly from their held
source bytes, capture their complete module/class/function/global state before
calling this gate or any untrusted code, then verify that state afterward. This
gate's own entry snapshot does not certify arbitrary pre-existing module globals.
"""

from __future__ import annotations

import ast
import copy
import ctypes
import __future__
from ctypes import wintypes
import dataclasses
import hashlib
import os
from pathlib import Path
import re
import stat
import threading
from types import FunctionType, SimpleNamespace
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
VENUE = ROOT / "examples/000_live_certification/okx_penetration"
READER_RELATIVE = "_m01_readonly_monitor_v3/current_reader.py"
SUPERVISOR_RELATIVE = "_m01_readonly_monitor_v2/job_supervisor.py"
WORKER_RELATIVE = "_m01_readonly_monitor_v2/worker.py"
READER_SHA256 = "5a8fd479c999279d9efde625cac1938d794201f04e1beaa6f3663b267d7a7ebc"
SUPERVISOR_SHA256 = "188b929b4e74b6e16a54d21093b6d52a7471849b161b2777945561e6d8d62e82"
WORKER_SHA256 = "aea9651c571d4bbd93592ccbd06c630a2a73df8286e9425a357433d598ca4f41"
CURRENT_TYPES_RELATIVE = "_m01_readonly_monitor_v2/current_types.py"
CURRENT_TYPES_SHA256 = "cd896051b0580195baa569989622c18fec594afc3772e7ea4af9e4cf226778ea"
CONTRACT_RELATIVE = "_certification/m01_private_monitor_v2.py"
CONTRACT_SHA256 = "1c319502dcec4da91a7166ad1a532e4610319ca837ac93f2391f21fda87ae1db"
SYNTHETIC_OUTPUT = b"OKX_M01_ROOT_HELPER_GATE_R8_OK\n"
SYNTHETIC_HELPER = (
    b"from datetime import datetime, timezone\n"
    b"import sys\n"
    b"sys.stdout.buffer.write(b'OKX_M01_ROOT_HELPER_GATE_R8_OK\\n')\n"
)
_MAX_SOURCE_BYTES = 256 * 1024
_SAFE_CODE = re.compile(r"[a-z0-9_]{1,64}\Z")
_WINERROR_MAX = 65535
_WAIT_OBJECT_0 = 0
_WAIT_TIMEOUT = 0x102
_ERROR_BROKEN_PIPE = 109
_INVALID_HANDLE = ctypes.c_void_p(-1).value
_MAX_HELPER_OUTPUT_BYTES = 32 * 1024
_MAX_JOB_COUNT_OBSERVATIONS = 256
_ORPHANED_GATE_CONTEXTS: list[tuple[Any, ...]] = []
_OBSERVATION_LOCK = threading.RLock()
_WIN32_NAMES = frozenset(
    {
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
    }
)
_SUPERVISOR_FUNCTIONS = (
    "_winapi",
    "_new_pipe_state",
    "_create_suspended",
    "_drain",
    "_write_all",
    "_wait_process",
    "_process_exit_code",
    "_active_count",
    "_assign_control_to_job",
    "_resume_control",
    "_terminate_control",
    "_close_handle",
)
_SUPERVISOR_BOUND_FUNCTIONS = _SUPERVISOR_FUNCTIONS + (
    "_new_job",
    "_new_pipe",
    "_environment_block",
    "_worker_bootstrap",
)
_SUPERVISOR_IDENTITY_FUNCTIONS = _SUPERVISOR_BOUND_FUNCTIONS + ("_hold_runtime_files",)
_PHASES = frozenset(
    {
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
)


class GateError(ValueError):
    """Finite gate rejection."""

    def __init__(self, code: str):
        self.code = code if type(code) is str and _SAFE_CODE.fullmatch(code) else "gate_rejected"
        super().__init__(self.code)


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise GateError(code)


def _module_source(
    module: Any, expected_name: str, relative: str, expected_sha: str
) -> tuple[Path, bytes]:
    path = (VENUE / relative).resolve(strict=True)
    try:
        module_name = module.__name__
        origin_value = module.__file__
    except Exception:
        raise GateError("source_module_unavailable") from None
    _require(module_name == expected_name, "source_module_name_mismatch")
    _require(
        type(origin_value) is str
        and os.path.normcase(os.path.abspath(origin_value)) == os.path.normcase(str(path)),
        "source_module_origin_mismatch",
    )
    try:
        before = path.lstat()
    except Exception:
        raise GateError("source_module_unavailable") from None
    attributes = getattr(before, "st_file_attributes", 0)
    _require(
        stat.S_ISREG(before.st_mode)
        and not (type(attributes) is int and attributes & 0x00000400)
        and getattr(before, "st_nlink", 1) == 1
        and 0 <= before.st_size <= _MAX_SOURCE_BYTES,
        "source_module_file_type_invalid",
    )
    try:
        with path.open("rb") as stream:
            raw = stream.read(_MAX_SOURCE_BYTES + 1)
        after = path.lstat()
    except Exception:
        raise GateError("source_module_unavailable") from None
    _require(
        len(raw) == before.st_size
        and len(raw) <= _MAX_SOURCE_BYTES
        and (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        and hashlib.sha256(raw).hexdigest() == expected_sha,
        "source_module_pin_mismatch",
    )
    return path, raw


def _source_code_index(source: bytes, path: Path) -> dict[str, Any]:
    try:
        root_code = compile(source, str(path), "exec")
    except Exception:
        raise GateError("source_module_compile_failed") from None
    code_type = type(root_code)
    result = {}
    pending = [root_code]
    while pending:
        code = pending.pop()
        qualname = getattr(code, "co_qualname", code.co_name)
        if type(qualname) is str:
            result.setdefault(qualname, []).append(code)
        pending.extend(value for value in code.co_consts if isinstance(value, code_type))
    return {qualname: tuple(codes) for qualname, codes in result.items()}


def _function_matches_source(function: Any, index: dict[str, Any], qualname: str) -> bool:
    if type(function) is not FunctionType:
        return False
    code = getattr(function, "__code__", None)
    expected = index.get(qualname, ())
    return code is not None and any(code == candidate for candidate in expected)


def _safe_value_snapshot(value: Any, depth: int = 0) -> Any:
    if value is None or type(value) in (bool, int, str, bytes):
        return ("value", type(value), value)
    if type(value) is float:
        return ("float", value.hex())
    if depth >= 16:
        return ("identity", id(value))
    if type(value) is tuple:
        return ("tuple", tuple(_safe_value_snapshot(item, depth + 1) for item in value))
    if type(value) is list:
        return ("list", tuple(_safe_value_snapshot(item, depth + 1) for item in value))
    if type(value) is dict:
        return (
            "dict",
            tuple(
                (_safe_value_snapshot(key, depth + 1), _safe_value_snapshot(item, depth + 1))
                for key, item in value.items()
            ),
        )
    if type(value) in (set, frozenset):
        items = [_safe_value_snapshot(item, depth + 1) for item in value]
        return (type(value).__name__, tuple(sorted(items, key=repr)))
    return ("identity", id(value))


def _validate_literal_module_bindings(module: Any, tree: ast.Module) -> None:
    for statement in tree.body:
        if isinstance(statement, ast.Assign):
            targets = tuple(statement.targets)
            value = statement.value
        elif isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
            targets = (statement.target,)
            value = statement.value
        else:
            continue
        if value is None or not all(isinstance(target, ast.Name) for target in targets):
            continue
        try:
            expected = ast.literal_eval(value)
        except (TypeError, ValueError, SyntaxError, MemoryError, RecursionError):
            continue
        for target in targets:
            if (
                module.__name__ == "_m01_readonly_monitor_v3.current_reader"
                and target.id == "_ROOT_HELPER_RETAINED_CONTEXTS"
            ):
                continue
            actual = module.__dict__.get(target.id)
            _require(
                target.id in module.__dict__
                and type(actual) is type(expected)
                and _safe_value_snapshot(actual) == _safe_value_snapshot(expected),
                "module_literal_binding_mismatch",
            )


def _descriptor_functions(value: Any) -> tuple[Any, ...]:
    if type(value) is FunctionType:
        return (value,)
    if type(value) in (staticmethod, classmethod):
        return (value.__func__,)
    if type(value) is property:
        return tuple(function for function in (value.fget, value.fset, value.fdel) if function)
    return ()


def _source_method_descriptor(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> tuple[str, str | None]:
    if not node.decorator_list:
        return "function", None
    if len(node.decorator_list) != 1:
        raise GateError("module_class_descriptor_source_unsupported")
    decorator = node.decorator_list[0]
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    if isinstance(target, ast.Name) and target.id == "property":
        return "property", "fget"
    if isinstance(target, ast.Name) and target.id in {"classmethod", "staticmethod"}:
        return target.id, None
    if (
        isinstance(target, ast.Attribute)
        and target.attr in {"setter", "getter", "deleter"}
        and isinstance(target.value, ast.Name)
    ):
        return (
            "property",
            {
                "getter": "fget",
                "setter": "fset",
                "deleter": "fdel",
            }[target.attr],
        )
    raise GateError("module_class_descriptor_source_unsupported")


def _property_accessors(value: Any) -> dict[str, Any]:
    if type(value) is not property:
        return {}
    return {
        name: function
        for name, function in (
            ("fget", value.fget),
            ("fset", value.fset),
            ("fdel", value.fdel),
        )
        if function is not None
    }


def _function_matches_source_node(
    function: Any,
    index: dict[str, Any],
    qualname: str,
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> bool:
    if type(function) is not FunctionType:
        return False
    first_source_line = min([node.lineno] + [decorator.lineno for decorator in node.decorator_list])
    return any(
        code.co_firstlineno == first_source_line and function.__code__ == code
        for code in index.get(qualname, ())
    )


def _runtime_method_descriptor_kind(value: Any) -> str:
    if type(value) is FunctionType:
        return "function"
    if type(value) is property:
        return "property"
    if type(value) is classmethod:
        return "classmethod"
    if type(value) is staticmethod:
        return "staticmethod"
    return "other"


def _generated_dataclass_method_matches(
    function: Any, reference_class: Any, module: Any, name: str
) -> bool:
    if (
        type(function) is not FunctionType
        or function.__module__ != module.__name__
        or function.__qualname__.rsplit(".", 1)[-1] != name
    ):
        return False
    expected = _descriptor_functions(vars(reference_class).get(name))
    return any(
        function.__code__ == candidate.__code__
        and function.__module__ == candidate.__module__
        and function.__qualname__ == candidate.__qualname__
        and function.__globals__ is candidate.__globals__
        and _safe_value_snapshot(function.__defaults__)
        == _safe_value_snapshot(candidate.__defaults__)
        and _safe_value_snapshot(function.__kwdefaults__)
        == _safe_value_snapshot(candidate.__kwdefaults__)
        for candidate in expected
    )


def _safe_dataclass_default(node: ast.AST) -> bool:
    if isinstance(node, (ast.Constant, ast.Name)):
        return True
    if isinstance(node, ast.Attribute):
        return _safe_dataclass_default(node.value)
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return all(_safe_dataclass_default(value) for value in node.elts)
    if isinstance(node, ast.Dict):
        return all(key is None or _safe_dataclass_default(key) for key in node.keys) and all(
            _safe_dataclass_default(value) for value in node.values
        )
    if isinstance(node, ast.UnaryOp):
        return isinstance(node.op, (ast.UAdd, ast.USub, ast.Invert, ast.Not)) and (
            _safe_dataclass_default(node.operand)
        )
    if isinstance(node, ast.Call):
        return (
            isinstance(node.func, ast.Name)
            and node.func.id == "field"
            and not node.args
            and all(
                keyword.arg is not None and _safe_dataclass_default(keyword.value)
                for keyword in node.keywords
            )
        )
    return False


def _dataclass_reference_class(
    node: ast.ClassDef, module: Any, path: Path, tree: ast.Module
) -> Any:
    _require(
        len(node.decorator_list) == 1
        and isinstance(
            node.decorator_list[0].func
            if isinstance(node.decorator_list[0], ast.Call)
            else node.decorator_list[0],
            ast.Name,
        )
        and (
            node.decorator_list[0].func.id
            if isinstance(node.decorator_list[0], ast.Call)
            else node.decorator_list[0].id
        )
        == "dataclass"
        and module.__dict__.get("dataclass") is dataclasses.dataclass
        and module.__dict__.get("field") is dataclasses.field
        and not node.bases
        and not node.keywords,
        "module_dataclass_reference_unavailable",
    )
    for child in node.body:
        if isinstance(child, ast.Expr) and isinstance(child.value, ast.Constant):
            continue
        if isinstance(child, ast.AnnAssign):
            _require(
                isinstance(child.target, ast.Name)
                and (child.value is None or _safe_dataclass_default(child.value)),
                "module_dataclass_reference_unsafe",
            )
            continue
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _require(not child.decorator_list, "module_dataclass_reference_unsafe")
            continue
        raise GateError("module_dataclass_reference_unsafe")

    future_annotations = any(
        isinstance(child, ast.ImportFrom)
        and child.module == "__future__"
        and any(alias.name == "annotations" for alias in child.names)
        for child in tree.body
    )
    _require(future_annotations, "module_dataclass_reference_unsafe")
    flags = __future__.annotations.compiler_flag if future_annotations else 0
    isolated_globals = dict(module.__dict__)
    isolated_globals["__name__"] = module.__name__
    isolated_globals["__file__"] = str(path)
    try:
        replay = ast.Module(body=[copy.deepcopy(node)], type_ignores=[])
        code = compile(
            ast.fix_missing_locations(replay),
            str(path),
            "exec",
            flags=flags,
            dont_inherit=True,
        )
        exec(code, isolated_globals, isolated_globals)
        reference = isolated_globals.get(node.name)
    except Exception:
        raise GateError("module_dataclass_reference_failed") from None
    _require(
        isinstance(reference, type)
        and reference.__module__ == module.__name__
        and reference.__qualname__ == node.name,
        "module_dataclass_reference_failed",
    )
    return reference


def _dataclass_generated_methods(node: ast.ClassDef) -> frozenset[str]:
    decorator = None
    for candidate in node.decorator_list:
        target = candidate.func if isinstance(candidate, ast.Call) else candidate
        name = (
            target.id
            if isinstance(target, ast.Name)
            else (target.attr if isinstance(target, ast.Attribute) else None)
        )
        if name == "dataclass":
            decorator = candidate
            break
    if decorator is None:
        return frozenset()

    options: dict[str, Any] = {}
    if isinstance(decorator, ast.Call):
        for keyword in decorator.keywords:
            if keyword.arg is None:
                raise GateError("module_dataclass_binding_invalid")
            try:
                options[keyword.arg] = ast.literal_eval(keyword.value)
            except Exception:
                raise GateError("module_dataclass_binding_invalid") from None
    init = options.get("init", True) is True
    repr_enabled = options.get("repr", True) is True
    eq = options.get("eq", True) is True
    order = options.get("order", False) is True
    frozen = options.get("frozen", False) is True
    unsafe_hash = options.get("unsafe_hash", False) is True
    declared = {
        child.name
        for child in node.body
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    generated: set[str] = set()
    for enabled, name in ((init, "__init__"), (repr_enabled, "__repr__"), (eq, "__eq__")):
        if enabled and name not in declared:
            generated.add(name)
    if order:
        generated.update(
            name for name in ("__lt__", "__le__", "__gt__", "__ge__") if name not in declared
        )
    if frozen:
        generated.update(name for name in ("__setattr__", "__delattr__") if name not in declared)
    if (unsafe_hash or (eq and frozen)) and "__hash__" not in declared:
        generated.add("__hash__")
    return frozenset(generated)


def _module_source_bindings(
    module: Any,
    source: bytes,
    path: Path,
    index: dict[str, Any],
    *,
    allow_runtime_hold_fake: bool = False,
) -> tuple[tuple[Any, ...], bool]:
    """Verify and snapshot all source-owned functions, methods, and classes."""
    try:
        tree = ast.parse(source)
    except Exception:
        raise GateError("module_source_parse_failed") from None
    _validate_literal_module_bindings(module, tree)
    bindings: list[tuple[Any, ...]] = []
    sourcefake_hold = False

    def record_function(function: Any) -> None:
        bindings.append(
            (
                "function",
                function,
                function.__code__,
                function.__globals__,
                function.__defaults__,
                _safe_value_snapshot(function.__defaults__),
                function.__kwdefaults__,
                _safe_value_snapshot(function.__kwdefaults__),
            )
        )

    def check_function(function: Any, qualname: str) -> None:
        _require(
            type(function) is FunctionType
            and function.__module__ == module.__name__
            and function.__globals__ is module.__dict__
            and _code_origin(function, path)
            and _function_matches_source(function, index, qualname),
            "module_function_binding_mismatch",
        )
        record_function(function)

    def check_class(node: ast.ClassDef, owner: Any, prefix: str = "") -> None:
        qualname = f"{prefix}.{node.name}" if prefix else node.name
        try:
            class_object = getattr(owner, node.name)
        except Exception:
            raise GateError("module_class_binding_mismatch") from None
        _require(
            isinstance(class_object, type)
            and class_object.__module__ == module.__name__
            and class_object.__qualname__ == qualname
            and bool(index.get(qualname)),
            "module_class_binding_mismatch",
        )
        bindings.append(("class", class_object, tuple(vars(class_object).items())))
        generated = _dataclass_generated_methods(node)
        generated_reference = None
        if generated:
            _require(not prefix, "module_nested_dataclass_reference_unsupported")
            generated_reference = _dataclass_reference_class(node, module, path, tree)
        method_nodes = [
            child
            for child in node.body
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        attrs = vars(class_object)
        source_property_accessors: dict[str, dict[str, ast.FunctionDef | ast.AsyncFunctionDef]] = {}
        for property_node in method_nodes:
            descriptor_kind, accessor_name = _source_method_descriptor(property_node)
            if descriptor_kind == "property":
                _require(
                    accessor_name is not None,
                    "module_class_descriptor_source_unsupported",
                )
                source_property_accessors.setdefault(property_node.name, {})[
                    accessor_name
                ] = property_node
        verified_properties: set[str] = set()
        for method_node in method_nodes:
            value = attrs.get(method_node.name)
            descriptor_kind, accessor_name = _source_method_descriptor(method_node)
            _require(
                _runtime_method_descriptor_kind(value) == descriptor_kind,
                "module_class_descriptor_kind_mismatch",
            )
            qual = f"{qualname}.{method_node.name}"
            if descriptor_kind == "property":
                expected_accessors = source_property_accessors[method_node.name]
                actual_accessors = _property_accessors(value)
                _require(
                    set(actual_accessors) == set(expected_accessors),
                    "module_class_descriptor_accessor_mismatch",
                )
                if method_node.name not in verified_properties:
                    for slot, accessor_node in expected_accessors.items():
                        function = actual_accessors[slot]
                        _require(
                            _function_matches_source_node(function, index, qual, accessor_node),
                            "module_class_descriptor_accessor_mismatch",
                        )
                        check_function(function, qual)
                    verified_properties.add(method_node.name)
                continue
            functions = _descriptor_functions(value)
            matches = tuple(
                function
                for function in functions
                if _function_matches_source(function, index, qual)
            )
            _require(bool(matches), "module_class_method_missing")
            for function in matches:
                check_function(function, qual)
        for attr_name, value in attrs.items():
            for function in _descriptor_functions(value):
                if function.__module__ != module.__name__:
                    continue
                method_qualname = function.__qualname__
                if _function_matches_source(function, index, method_qualname):
                    check_function(function, method_qualname)
                else:
                    short_name = method_qualname.rsplit(".", 1)[-1]
                    _require(
                        short_name in generated
                        and generated_reference is not None
                        and _generated_dataclass_method_matches(
                            function, generated_reference, module, short_name
                        ),
                        "module_generated_method_unexpected",
                    )
                    record_function(function)
            if isinstance(value, type) and value.__module__ == module.__name__:
                nested = next(
                    (
                        child
                        for child in node.body
                        if isinstance(child, ast.ClassDef) and child.name == attr_name
                    ),
                    None,
                )
                _require(nested is not None, "module_nested_class_unexpected")
                check_class(nested, class_object, qualname)

        for generated_name in generated:
            expected = (
                _descriptor_functions(vars(generated_reference).get(generated_name))
                if generated_reference is not None
                else ()
            )
            _require(
                generated_name in attrs
                and any(
                    function.__qualname__ == f"{qualname}.{generated_name}"
                    for function in _descriptor_functions(attrs[generated_name])
                )
                and bool(expected)
                and any(
                    _generated_dataclass_method_matches(
                        function, generated_reference, module, generated_name
                    )
                    for function in _descriptor_functions(attrs[generated_name])
                ),
                "module_generated_method_missing",
            )

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            function = module.__dict__.get(node.name)
            if (
                module.__name__ == "_m01_readonly_monitor_v2.job_supervisor"
                and node.name == "_hold_runtime_files"
                and allow_runtime_hold_fake
                and type(function) is FunctionType
                and function.__globals__ is not module.__dict__
                and function.__module__ != module.__name__
            ):
                sourcefake_hold = True
                record_function(function)
            else:
                check_function(function, node.name)
        elif isinstance(node, ast.ClassDef):
            check_class(node, module)

    global_snapshot = tuple(module.__dict__.items())
    return (module, module.__dict__, global_snapshot, tuple(bindings)), sourcefake_hold


def _module_bindings_unchanged(snapshots: tuple[tuple[Any, ...], ...]) -> bool:
    try:
        for module, module_dict, globals_before, bindings in snapshots:
            if module.__dict__ is not module_dict or len(module_dict) != len(globals_before):
                return False
            if any(module_dict.get(name) is not value for name, value in globals_before):
                return False
            for binding in bindings:
                if binding[0] == "class":
                    _kind, class_object, class_members = binding
                    current_members = tuple(vars(class_object).items())
                    if len(current_members) != len(class_members):
                        return False
                    if any(
                        dict(current_members).get(name) is not value
                        for name, value in class_members
                    ):
                        return False
                    continue
                (
                    _kind,
                    function,
                    code,
                    globals_dict,
                    defaults_ref,
                    defaults_value,
                    kwdefaults_ref,
                    kwdefaults_value,
                ) = binding
                if (
                    type(function) is not FunctionType
                    or function.__code__ is not code
                    or function.__globals__ is not globals_dict
                    or function.__defaults__ is not defaults_ref
                    or _safe_value_snapshot(function.__defaults__) != defaults_value
                    or function.__kwdefaults__ is not kwdefaults_ref
                    or _safe_value_snapshot(function.__kwdefaults__) != kwdefaults_value
                ):
                    return False
        return True
    except Exception:
        return False


def _code_origin(function: Any, path: Path) -> bool:
    code = getattr(function, "__code__", None)
    if code is None:
        return False
    try:
        return Path(code.co_filename).resolve(strict=False) == path
    except Exception:
        return False


def _bind_sources(
    reader: Any, expected_supervisor: Any, expected_worker: Any
) -> tuple[Any, Path, Path, tuple[bytes, ...], tuple[tuple[Any, ...], ...]]:
    _require(os.name == "nt", "windows_required")
    _require(
        getattr(reader, "job_supervisor", None) is expected_supervisor
        and getattr(reader, "worker", None) is expected_worker,
        "held_module_binding_mismatch",
    )
    reader_path, reader_source = _module_source(
        reader,
        "_m01_readonly_monitor_v3.current_reader",
        READER_RELATIVE,
        READER_SHA256,
    )
    supervisor = expected_supervisor
    supervisor_path, supervisor_source = _module_source(
        supervisor,
        "_m01_readonly_monitor_v2.job_supervisor",
        SUPERVISOR_RELATIVE,
        SUPERVISOR_SHA256,
    )
    worker = expected_worker
    worker_path, worker_source = _module_source(
        worker,
        "_m01_readonly_monitor_v2.worker",
        WORKER_RELATIVE,
        WORKER_SHA256,
    )
    current_types = getattr(supervisor, "current_types", None)
    _require(
        getattr(reader, "current_types", None) is current_types,
        "current_types_binding_mismatch",
    )
    types_path, current_types_source = _module_source(
        current_types,
        "_m01_readonly_monitor_v2.current_types",
        CURRENT_TYPES_RELATIVE,
        CURRENT_TYPES_SHA256,
    )
    contract = getattr(supervisor, "contract", None)
    contract_path, contract_source = _module_source(
        contract,
        "_certification.m01_private_monitor_v2",
        CONTRACT_RELATIVE,
        CONTRACT_SHA256,
    )
    _require(supervisor.worker is worker, "worker_binding_mismatch")
    _require(
        getattr(supervisor, "current_types", None) is current_types
        and getattr(supervisor, "contract", None) is contract,
        "supervisor_dependency_binding_mismatch",
    )
    _require(
        reader._root_helper_wrapper.__globals__ is reader.__dict__
        and reader._run_pinned_root_helper.__globals__ is reader.__dict__
        and reader._wait_for_job_zero.__globals__ is reader.__dict__
        and reader._sha.__globals__ is reader.__dict__
        and reader._require.__globals__ is reader.__dict__,
        "reader_global_binding_mismatch",
    )
    reader_error = getattr(reader, "CurrentReaderError", None)
    _require(
        isinstance(reader_error, type)
        and issubclass(reader_error, ValueError)
        and reader_error.__module__ == reader.__name__
        and _code_origin(reader_error.__init__, reader_path)
        and reader_error.__init__.__globals__ is reader.__dict__,
        "reader_error_binding_mismatch",
    )
    _require(
        type(getattr(reader, "MAX_HELPER_OUTPUT_BYTES", None)) is int
        and reader.MAX_HELPER_OUTPUT_BYTES == _MAX_HELPER_OUTPUT_BYTES,
        "reader_output_limit_mismatch",
    )
    _require(
        reader.__dict__.get("job_supervisor") is supervisor
        and reader.__dict__.get("worker") is worker,
        "reader_global_module_mismatch",
    )
    _require(
        supervisor.__dict__.get("worker") is worker,
        "supervisor_global_worker_mismatch",
    )
    reader_code = _source_code_index(reader_source, reader_path)
    supervisor_code = _source_code_index(supervisor_source, supervisor_path)
    module_sources = (
        (reader, reader_source, reader_path, reader_code),
        (supervisor, supervisor_source, supervisor_path, supervisor_code),
        (worker, worker_source, worker_path, _source_code_index(worker_source, worker_path)),
        (
            current_types,
            current_types_source,
            types_path,
            _source_code_index(current_types_source, types_path),
        ),
        (
            contract,
            contract_source,
            contract_path,
            _source_code_index(contract_source, contract_path),
        ),
    )
    binding_snapshots = []
    sourcefake_hold = False
    for module, source, path, code_index in module_sources:
        snapshot, is_fake_hold = _module_source_bindings(
            module,
            source,
            path,
            code_index,
            allow_runtime_hold_fake=(module is supervisor),
        )
        binding_snapshots.append(snapshot)
        sourcefake_hold = sourcefake_hold or is_fake_hold
    _require(
        sourcefake_hold or _is_source_function(supervisor._hold_runtime_files, supervisor_path),
        "runtime_holder_source_binding_mismatch",
    )
    _require(
        _code_origin(reader._root_helper_wrapper, reader_path)
        and _code_origin(reader._run_pinned_root_helper, reader_path)
        and _code_origin(reader._wait_for_job_zero, reader_path),
        "reader_code_origin_mismatch",
    )
    _require(_code_origin(reader._sha, reader_path), "reader_sha_code_origin_mismatch")
    _require(_code_origin(reader._require, reader_path), "reader_require_code_origin_mismatch")
    for name in (
        "_root_helper_wrapper",
        "_run_pinned_root_helper",
        "_wait_for_job_zero",
        "_sha",
        "_require",
    ):
        _require(
            _function_matches_source(getattr(reader, name, None), reader_code, name),
            "reader_code_object_mismatch",
        )
    _require(
        _function_matches_source(reader_error.__init__, reader_code, "CurrentReaderError.__init__"),
        "reader_error_code_object_mismatch",
    )
    for name in _SUPERVISOR_BOUND_FUNCTIONS:
        function = getattr(supervisor, name, None)
        _require(
            callable(function)
            and _code_origin(function, supervisor_path)
            and function.__globals__ is supervisor.__dict__,
            "supervisor_code_origin_mismatch",
        )
        _require(
            _function_matches_source(function, supervisor_code, name),
            "supervisor_code_object_mismatch",
        )
    runtime_holder = getattr(supervisor, "_hold_runtime_files", None)
    if _is_source_function(runtime_holder, supervisor_path):
        _require(
            runtime_holder.__globals__ is supervisor.__dict__,
            "runtime_holder_global_binding_mismatch",
        )
        _require(
            _function_matches_source(runtime_holder, supervisor_code, "_hold_runtime_files"),
            "runtime_holder_code_object_mismatch",
        )
    return (
        supervisor,
        reader_path,
        supervisor_path,
        (
            reader_source,
            supervisor_source,
            worker_source,
            current_types_source,
            contract_source,
        ),
        tuple(binding_snapshots),
    )


def _error_category(
    exc: BaseException, reader: Any, supervisor: Any
) -> tuple[str, str | None, int | None]:
    code = None
    if isinstance(exc, GateError):
        category = "gate_error"
        code = exc.code
    elif isinstance(exc, reader.CurrentReaderError):
        category = "reader_error"
        value = getattr(exc, "code", None)
        code = value if type(value) is str and _SAFE_CODE.fullmatch(value) else None
    elif isinstance(exc, supervisor.ObserverError):
        category = "supervisor_error"
        value = getattr(exc, "reason", None)
        code = value if type(value) is str and _SAFE_CODE.fullmatch(value) else None
    elif isinstance(exc, TimeoutError):
        category = "timeout"
    elif isinstance(exc, OSError):
        category = "os_error"
    elif isinstance(exc, ValueError):
        category = "value_error"
    elif isinstance(exc, Exception):
        category = "exception"
    else:
        category = "base_exception"
    raw_winerror = getattr(exc, "winerror", None)
    winerror = (
        raw_winerror if type(raw_winerror) is int and 0 < raw_winerror <= _WINERROR_MAX else None
    )
    return category, code, winerror


class _Observation:
    def __init__(self, reader: Any, supervisor: Any, held_source_bytes: tuple[bytes, ...]):
        self.reader = reader
        self.supervisor = supervisor
        self.held_source_bytes = held_source_bytes
        self.lock = threading.RLock()
        self.local = threading.local()
        self.phase = "source_binding"
        self.failed_phase = None
        self.error_category = None
        self.error_code = None
        self.native_api = None
        self.native_winerror = None
        self.native_failure_phase = None
        self.native_failure_seen = False
        self.reader_check_code = None
        self.reader_exception_category = None
        self.reader_exception_code = None
        self.control = None
        self.raw_kernel = None
        self.kernel_proxy = None
        self.open_handles: set[int] = set()
        self.created = False
        self.assigned = False
        self.resumed = False
        self.source_write_ok = False
        self.stdin_closed = False
        self.wait_results: list[bool] = []
        self.process_exit_code_present = False
        self.process_exit_code_zero = False
        self.job_counts: list[int] = []
        self.job_count_observations: list[tuple[str, int]] = []
        self.job_count_observations_truncated = False
        self.job_count_after_exit = None
        self.job_count_after_cleanup = None
        self.job_count_after_cleanup_error = None
        self.job_count_after_cleanup_attempted = False
        self.stdout_eof = False
        self.stderr_eof = False
        self.stdout_done = False
        self.stderr_done = False
        self.stdout_error = False
        self.stderr_error = False
        self.stdout_overflow = False
        self.stderr_overflow = False
        self.thread_starts = {"stdout": False, "stderr": False}
        self.thread_joins = {"stdout": False, "stderr": False}
        self.thread_references: list[Any] = []
        self.pipe_state_references: list[Any] = []
        self.terminate_requested = False
        self.terminate_succeeded = False
        self.close_calls = 0
        self.close_failures = 0
        self.last_close_all_succeeded = False
        self.pipes_eof_complete = False
        self.output_matches = False
        self.stderr_empty = False
        self.sourcefake = False
        self.control_reference = None
        self.kernel_reference = None
        self.sibling_registry = None
        self.runtime_registry = getattr(supervisor, "_ORPHANED_RUNTIME_HANDLE_SETS", None)
        self.runtime_registry_empty_before = (
            isinstance(self.runtime_registry, list) and not self.runtime_registry
        )
        self.runtime_registry_length_before = (
            len(self.runtime_registry) if isinstance(self.runtime_registry, list) else None
        )
        self.reader_retained_registry = reader.__dict__.get("_ROOT_HELPER_RETAINED_CONTEXTS")
        self.reader_retained_length_before = (
            len(self.reader_retained_registry)
            if type(self.reader_retained_registry) is list
            else None
        )

    def current_phase(self) -> str:
        return getattr(self.local, "phase", self.phase)

    def enter(self, phase: str) -> str:
        previous = self.current_phase()
        with self.lock:
            self.phase = phase if phase in _PHASES else "create_suspended"
        self.local.phase = phase
        return previous

    def leave(self, previous: str) -> None:
        self.local.phase = previous
        with self.lock:
            self.phase = previous if previous in _PHASES else "create_suspended"

    def failed(self, phase: str, exc: BaseException) -> None:
        category, code, winerror = _error_category(exc, self.reader, self.supervisor)
        with self.lock:
            if self.failed_phase is None:
                self.failed_phase = phase if phase in _PHASES else "create_suspended"
                self.error_category = category
                self.error_code = code
                if winerror is not None:
                    self.native_winerror = winerror

    def reader_check_failed(self, exc: BaseException) -> None:
        _category, code, _winerror = _error_category(exc, self.reader, self.supervisor)
        with self.lock:
            if self.reader_check_code is None:
                self.reader_check_code = code or "reader_check_failed"

    def reader_failed(self, exc: BaseException) -> None:
        category, code, _winerror = _error_category(exc, self.reader, self.supervisor)
        with self.lock:
            self.reader_exception_category = category
            self.reader_exception_code = code

    def record_job_count(self, phase: str, value: Any) -> None:
        if type(value) is not int:
            return
        with self.lock:
            self.job_counts.append(value)
            if len(self.job_count_observations) < _MAX_JOB_COUNT_OBSERVATIONS:
                self.job_count_observations.append((phase, value))
            else:
                self.job_count_observations_truncated = True
            if phase == "job_count_after_exit":
                self.job_count_after_exit = value
            elif phase == "job_count_after_cleanup":
                self.job_count_after_cleanup = value

    def native_failure(self, name: str, phase: str, winerror: int | None) -> None:
        with self.lock:
            self.native_failure_seen = True
            if self.native_api is None:
                self.native_api = name if name in _WIN32_NAMES else "other_win32_call"
                self.native_failure_phase = phase if phase in _PHASES else "create_suspended"
                self.native_winerror = (
                    winerror if type(winerror) is int and 0 < winerror <= _WINERROR_MAX else None
                )
                if self.failed_phase is None:
                    self.failed_phase = phase if phase in _PHASES else "create_suspended"
                    self.error_category = "win32_call_failed"

    def native_exception(self, name: str, phase: str, exc: BaseException) -> None:
        category, _code, winerror = _error_category(exc, self.reader, self.supervisor)
        if winerror is None:
            winerror = _last_error()
        self.native_failure(name, phase, winerror)
        if self.error_category is None:
            with self.lock:
                self.error_category = category

    def result(self) -> dict[str, Any]:
        with self.lock:
            has_output = self.output_matches and self.stderr_empty
            live_reader_registry = self.reader.__dict__.get("_ROOT_HELPER_RETAINED_CONTEXTS")
            reader_registry_identity_unchanged = (
                type(live_reader_registry) is list
                and live_reader_registry is self.reader_retained_registry
            )
            live_reader_registry_count = (
                len(live_reader_registry) if type(live_reader_registry) is list else None
            )
            cleanup_certain = (
                bool(self.wait_results)
                and self.wait_results[0]
                and bool(self.wait_results[-1])
                and self.process_exit_code_present
                and self.assigned
                and self.job_count_after_cleanup_attempted
                and type(self.job_count_after_cleanup) is int
                and self.job_count_after_cleanup == 0
                and self.job_count_after_cleanup_error is None
                and (not self.terminate_requested or self.terminate_succeeded)
                and self.stdout_eof
                and self.stderr_eof
                and self.stdout_done
                and self.stderr_done
                and not self.stdout_error
                and not self.stderr_error
                and not self.stdout_overflow
                and not self.stderr_overflow
                and self.thread_starts["stdout"]
                and self.thread_starts["stderr"]
                and self.thread_joins["stdout"]
                and self.thread_joins["stderr"]
                and self.last_close_all_succeeded
                and not self.open_handles
                and type(self.reader_retained_registry) is list
                and self.reader_retained_length_before == 0
                and len(self.reader_retained_registry) == self.reader_retained_length_before
                and reader_registry_identity_unchanged
                and live_reader_registry_count == 0
            )
            if self.reader_check_code is not None:
                phase = "reader_check"
                status = "LIFECYCLE_BLOCKED"
            elif (
                self.reader_exception_code is not None or self.reader_exception_category is not None
            ):
                phase = "reader_exception"
                status = "LIFECYCLE_BLOCKED"
            elif self.failed_phase is not None:
                phase = self.failed_phase
                status = "LIFECYCLE_BLOCKED"
            elif not cleanup_certain:
                phase = self.phase if self.phase in _PHASES else "cleanup_close"
                status = "CLEANUP_UNCONFIRMED"
            elif not has_output or not self.process_exit_code_zero:
                phase = "complete"
                status = "OUTPUT_MISMATCH"
            else:
                phase = "complete"
                status = "SOURCE_FAKE_ONLY" if self.sourcefake else "LOCAL_SYNTHETIC_CHILD"
            retained = bool(_ORPHANED_GATE_CONTEXTS and _ORPHANED_GATE_CONTEXTS[-1][0] is self)
            return {
                "schema": "iteration41.okx.m01.root-helper-lifecycle-gate.v7",
                "status": status,
                "phase": phase,
                "error_category": (
                    "reader_error"
                    if self.reader_check_code is not None
                    else self.reader_exception_category
                    if self.reader_exception_code is not None
                    or self.reader_exception_category is not None
                    else self.error_category
                ),
                "error_code": self.reader_check_code
                or self.reader_exception_code
                or self.error_code,
                "reader_check_failed": self.reader_check_code is not None,
                "reader_check_code": self.reader_check_code,
                "reader_exception_seen": (
                    self.reader_exception_code is not None
                    or self.reader_exception_category is not None
                ),
                "reader_exception_code": self.reader_exception_code,
                "first_observed_failure_phase": self.failed_phase,
                "win32_api": self.native_api,
                "winerror": self.native_winerror,
                "native_failure_phase": self.native_failure_phase,
                "reader_source_pinned": True,
                "supervisor_source_pinned": True,
                "worker_source_pinned": True,
                "source_bytes_held": len(self.held_source_bytes),
                "source_functions_restored": True,
                "process_created": self.created,
                "job_assigned_before_resume": self.assigned,
                "resumed": self.resumed,
                "source_frame_write_succeeded": self.source_write_ok,
                "stdin_close_succeeded": self.stdin_closed,
                "process_wait_succeeded": bool(self.wait_results and self.wait_results[0]),
                "wait_results": tuple(self.wait_results),
                "cleanup_wait_attempted": len(self.wait_results) > 1,
                "cleanup_wait_succeeded": len(self.wait_results) > 1 and self.wait_results[1],
                "process_reaped_after_cleanup": bool(self.wait_results and self.wait_results[-1]),
                "cleanup_confirmed": cleanup_certain,
                "process_exit_code_present": self.process_exit_code_present,
                "process_exit_code_zero": self.process_exit_code_zero,
                "job_count_observed": bool(self.job_counts),
                "job_count_observations": tuple(self.job_count_observations),
                "job_count_observations_truncated": self.job_count_observations_truncated,
                "job_zero_after_exit": self.job_count_after_exit == 0,
                "job_nonzero_after_exit": (
                    type(self.job_count_after_exit) is int and self.job_count_after_exit != 0
                ),
                "job_count_after_cleanup_observed": self.job_count_after_cleanup_attempted
                and type(self.job_count_after_cleanup) is int,
                "job_zero_after_cleanup": self.job_count_after_cleanup == 0,
                "job_nonzero_after_cleanup": (
                    type(self.job_count_after_cleanup) is int and self.job_count_after_cleanup != 0
                ),
                "job_count_after_cleanup_error": self.job_count_after_cleanup_error,
                "stdout_eof": self.stdout_eof,
                "stderr_eof": self.stderr_eof,
                "stdout_read_done": self.stdout_done,
                "stderr_read_done": self.stderr_done,
                "stdout_read_error": self.stdout_error,
                "stderr_read_error": self.stderr_error,
                "stdout_overflow": self.stdout_overflow,
                "stderr_overflow": self.stderr_overflow,
                "stdout_matches_fixed": self.output_matches,
                "stderr_empty": self.stderr_empty,
                "stdout_thread_started": self.thread_starts["stdout"],
                "stderr_thread_started": self.thread_starts["stderr"],
                "stdout_thread_joined": self.thread_joins["stdout"],
                "stderr_thread_joined": self.thread_joins["stderr"],
                "termination_requested": self.terminate_requested,
                "termination_succeeded": self.terminate_succeeded,
                "handle_close_calls": self.close_calls,
                "handle_close_failures": self.close_failures,
                "all_observed_handles_closed": not self.open_handles,
                "runtime_registry_empty_before": self.runtime_registry_empty_before,
                "runtime_registry_empty_after": (
                    isinstance(self.runtime_registry, list) and not self.runtime_registry
                ),
                "runtime_registry_unchanged": (
                    self.supervisor._ORPHANED_RUNTIME_HANDLE_SETS is self.runtime_registry
                    and isinstance(self.runtime_registry, list)
                    and len(self.runtime_registry) == self.runtime_registry_length_before
                ),
                "reader_retained_contexts_empty_before": self.reader_retained_length_before == 0,
                "reader_retained_contexts_empty_after": (
                    reader_registry_identity_unchanged and live_reader_registry_count == 0
                ),
                "reader_retained_registry_identity_unchanged": (reader_registry_identity_unchanged),
                "reader_retained_context_count_after": (live_reader_registry_count),
                "reader_retained_context_count_captured_after": (
                    len(self.reader_retained_registry)
                    if type(self.reader_retained_registry) is list
                    else None
                ),
                "retained_context": retained,
                "source_fake_only": self.sourcefake,
                "production_acceptance": False,
            }


def _last_error() -> int | None:
    getter = getattr(ctypes, "get_last_error", None)
    try:
        value = getter() if callable(getter) else None
    except Exception:
        return None
    return value if type(value) is int and 0 < value <= _WINERROR_MAX else None


def _handle_value(value: Any) -> int | None:
    if type(value) is int:
        return value if value else None
    raw = getattr(value, "value", None)
    return raw if type(raw) is int and raw else None


class _ObservedWinCall:
    def __init__(self, kernel: "_ObservedKernel", name: str, original: Any):
        self.kernel = kernel
        self.name = name
        self.original = original

    def __call__(self, *args, **kwargs):
        phase = self.kernel.observation.current_phase()
        try:
            result = self.original(*args, **kwargs)
        except BaseException as exc:
            self.kernel.observation.native_exception(self.name, phase, exc)
            raise
        native_error = _last_error()
        self.kernel.capture_handles(self.name, args, result)
        if self.kernel.failed_result(self.name, args, result, native_error):
            self.kernel.observation.native_failure(self.name, phase, native_error)
        return result


class _ObservedKernel:
    def __init__(self, raw: Any, observation: _Observation):
        self.raw = raw
        self.observation = observation

    def __getattr__(self, name: str):
        if name not in _WIN32_NAMES:
            raise AttributeError(name)
        return _ObservedWinCall(self, name, getattr(self.raw, name))

    def failed_result(
        self, name: str, args: tuple[Any, ...], result: Any, error: int | None
    ) -> bool:
        if name == "DeleteProcThreadAttributeList":
            return False
        if name == "InitializeProcThreadAttributeList" and args and args[0] is None:
            return False
        if (
            name == "ReadFile"
            and type(result) in (bool, int)
            and result == 0
            and error == _ERROR_BROKEN_PIPE
        ):
            return False
        if name == "WaitForSingleObject" and result in (_WAIT_OBJECT_0, _WAIT_TIMEOUT):
            return False
        if name == "ResumeThread":
            return result != 1
        if name in {"CreateJobObjectW", "CreateFileW"}:
            value = _handle_value(result)
            return value is None or value == _INVALID_HANDLE
        if name == "CreatePipe":
            return not bool(result)
        if name == "CreateProcessW":
            return not bool(result)
        if name == "GetExitCodeProcess":
            return not bool(result)
        if name in _WIN32_NAMES:
            return result is False or result == 0
        return False

    def capture_handles(self, name: str, args: tuple[Any, ...], result: Any) -> None:
        if name in {"CreateFileW", "CreateJobObjectW"}:
            value = _handle_value(result)
            if value is not None and value != _INVALID_HANDLE:
                with self.observation.lock:
                    self.observation.open_handles.add(value)
        elif name == "CreatePipe" and bool(result) and len(args) >= 2:
            try:
                read_handle = ctypes.cast(args[0], ctypes.POINTER(wintypes.HANDLE)).contents.value
                write_handle = ctypes.cast(args[1], ctypes.POINTER(wintypes.HANDLE)).contents.value
                for value in (read_handle, write_handle):
                    if value:
                        with self.observation.lock:
                            self.observation.open_handles.add(int(value))
            except Exception:
                pass
        elif name == "CreateProcessW" and bool(result) and args:
            try:
                process_info = ctypes.cast(
                    args[-1], ctypes.POINTER(self.observation.supervisor._PROCESS_INFORMATION)
                ).contents
                for value in (process_info.hProcess, process_info.hThread):
                    handle = _handle_value(value)
                    if handle is not None:
                        with self.observation.lock:
                            self.observation.open_handles.add(handle)
            except Exception:
                pass
        elif name == "CloseHandle" and args:
            value = _handle_value(args[0])
            if value is not None:
                self.observation.close_calls += 1
                if bool(result):
                    with self.observation.lock:
                        self.observation.open_handles.discard(value)
                else:
                    self.observation.close_failures += 1
                    self.observation.native_failure(
                        "CloseHandle", self.observation.current_phase(), _last_error()
                    )


def _phase_for_close(observation: _Observation, handle: Any) -> str:
    control = observation.control
    value = _handle_value(handle)
    if observation.current_phase() == "create_suspended" or control is None:
        return "pipe_setup"
    if value == _handle_value(control.get("thread")):
        return "thread_handle_close"
    if value == _handle_value(control.get("stdin")):
        return "stdin_close"
    return "cleanup_close"


def _install_wrappers(reader: Any, supervisor: Any, observation: _Observation):
    originals = {name: getattr(supervisor, name) for name in _SUPERVISOR_FUNCTIONS}
    original_reader_bindings = {"threading": reader.threading, "_require": reader._require}
    original_thread = original_reader_bindings["threading"].Thread
    wrappers: dict[str, Any] = {}

    def wrap(name: str, phase_fn):
        original = originals[name]

        def observed(*args, **kwargs):
            phase = phase_fn(args, kwargs)
            previous = observation.enter(phase)
            try:
                if (
                    name == "_close_handle"
                    and observation.control is not None
                    and not observation.job_count_after_cleanup_attempted
                    and _handle_value(args[2]) == _handle_value(observation.control.get("job"))
                ):
                    observation.job_count_after_cleanup_attempted = True
                    query_previous = observation.enter("job_count_after_cleanup")
                    try:
                        active_after_cleanup = originals["_active_count"](
                            args[0], observation.control["job"]
                        )
                        observation.record_job_count(
                            "job_count_after_cleanup", active_after_cleanup
                        )
                    except BaseException as exc:
                        category, code, _winerror = _error_category(exc, reader, supervisor)
                        observation.job_count_after_cleanup_error = (
                            code if code is not None else category
                        )
                    finally:
                        observation.leave(query_previous)
                result = original(*args, **kwargs)
            except BaseException as exc:
                observation.failed(phase, exc)
                raise
            else:
                if name == "_winapi":
                    observation.raw_kernel = result
                    observation.kernel_proxy = _ObservedKernel(result, observation)
                    return observation.kernel_proxy
                if name == "_create_suspended":
                    observation.control = result
                    observation.created = type(result) is dict and bool(result.get("process"))
                    observation.control_reference = result
                    observation.kernel_reference = args[0] if args else None
                    observation.sibling_registry = supervisor._ORPHANED_RUNTIME_HANDLE_SETS
                elif name == "_drain":
                    handle, state = args[1], args[2]
                    observation.pipe_state_references.append(state)
                    label = (
                        "stdout"
                        if observation.control and handle == observation.control.get("stdout")
                        else "stderr"
                    )
                    setattr(observation, label + "_eof", state.get("eof") is True)
                    setattr(observation, label + "_done", state.get("done") is True)
                    setattr(observation, label + "_error", state.get("error") is True)
                    setattr(observation, label + "_overflow", state.get("overflow") is True)
                elif name == "_write_all":
                    observation.source_write_ok = result is True
                elif name == "_wait_process":
                    observation.wait_results.append(result is True)
                    if observation.terminate_requested:
                        observation.phase = "cleanup_wait"
                elif name == "_process_exit_code":
                    observation.process_exit_code_present = type(result) is int
                    observation.process_exit_code_zero = type(result) is int and result == 0
                elif name == "_active_count":
                    if phase == "job_count_after_cleanup":
                        observation.job_count_after_cleanup_attempted = True
                    observation.record_job_count(phase, result)
                elif name == "_assign_control_to_job":
                    observation.assigned = bool(
                        observation.control and observation.control.get("assigned")
                    )
                elif name == "_resume_control":
                    observation.resumed = True
                elif name == "_terminate_control":
                    observation.terminate_requested = True
                    observation.terminate_succeeded = bool(result)
                elif name == "_close_handle":
                    if observation.control is not None:
                        observation.stdin_closed = (
                            observation.stdin_closed
                            or _handle_value(args[2])
                            == _handle_value(observation.control.get("stdin"))
                            and result is True
                        )
                return result
            finally:
                observation.leave(previous)

        wrappers[name] = observed
        setattr(supervisor, name, observed)

    try:
        phase_functions = {
            "_winapi": lambda _args, _kwargs: "winapi_factory",
            "_new_pipe_state": lambda _args, _kwargs: "pipe_setup",
            "_create_suspended": lambda _args, _kwargs: "create_suspended",
            "_drain": lambda args, _kwargs: (
                "stdout_drain"
                if observation.control and args[1] == observation.control.get("stdout")
                else "stderr_drain"
            ),
            "_write_all": lambda _args, _kwargs: "stdin_write",
            "_wait_process": lambda _args, _kwargs: (
                "cleanup_wait"
                if observation.terminate_requested or observation.wait_results
                else "process_wait"
            ),
            "_process_exit_code": lambda _args, _kwargs: "process_exit_code",
            "_active_count": lambda _args, _kwargs: (
                "job_count_assign"
                if observation.current_phase() == "job_assign"
                else "job_count_resume"
                if observation.current_phase() == "resume"
                else "job_count_after_cleanup"
                if observation.terminate_requested
                else "job_count_after_exit"
            ),
            "_assign_control_to_job": lambda _args, _kwargs: "job_assign",
            "_resume_control": lambda _args, _kwargs: "resume",
            "_terminate_control": lambda _args, _kwargs: "cleanup_terminate",
            "_close_handle": lambda args, _kwargs: _phase_for_close(observation, args[2]),
        }
        for name in _SUPERVISOR_FUNCTIONS:
            wrap(name, phase_functions[name])

        class ObservedThread(original_thread):
            def _label(self):
                return (
                    "stdout"
                    if str(getattr(self, "name", "")).endswith("stdout-drain")
                    else "stderr"
                )

            def start(self):
                label = self._label()
                previous = observation.enter("pipe_setup")
                try:
                    observation.thread_references.append(self)
                    result = super().start()
                    observation.thread_starts[label] = True
                    return result
                except BaseException as exc:
                    observation.failed("pipe_setup", exc)
                    raise
                finally:
                    observation.leave(previous)

            def join(self, timeout=None):
                label = self._label()
                previous = observation.enter("pipe_join")
                try:
                    result = super().join(timeout)
                    observation.thread_joins[label] = not self.is_alive()
                    return result
                except BaseException as exc:
                    observation.failed("pipe_join", exc)
                    raise
                finally:
                    observation.leave(previous)

        original_require = original_reader_bindings["_require"]

        def observed_require(condition, code):
            try:
                return original_require(condition, code)
            except reader.CurrentReaderError as exc:
                observation.reader_check_failed(exc)
                raise

        reader.threading = SimpleNamespace(Thread=ObservedThread)
        reader._require = observed_require
        return originals, original_reader_bindings
    except BaseException:
        for name, original in originals.items():
            setattr(supervisor, name, original)
        reader.threading = original_reader_bindings["threading"]
        reader._require = original_reader_bindings["_require"]
        raise


def _restore_wrappers(
    reader: Any,
    supervisor: Any,
    originals: dict[str, Any],
    original_reader_bindings: dict[str, Any],
) -> bool:
    try:
        for name, original in originals.items():
            setattr(supervisor, name, original)
        reader.threading = original_reader_bindings["threading"]
        reader._require = original_reader_bindings["_require"]
        return (
            all(getattr(supervisor, name) is original for name, original in originals.items())
            and reader.threading is original_reader_bindings["threading"]
            and reader._require is original_reader_bindings["_require"]
        )
    except Exception:
        return False


def _is_source_function(function: Any, path: Path) -> bool:
    return type(function) is FunctionType and _code_origin(function, path)


def run_fixed_synthetic_probe(
    reader_module: Any, supervisor_module: Any, worker_module: Any
) -> dict[str, Any]:
    """Run one fixed no-network child through the transformed reader and supervisor.

    Root must pass its exact held reader, V2 supervisor, and worker module
    objects, with current_types and contract bound through those modules. The
    gate retains the reader module and verified public source bytes on every
    uncertain exit. Root must also keep its outer source lease and patch bytes
    through normal postverification. This helper emits only finite lifecycle
    facts, never child output, paths, handles, environment values, credentials,
    or exception text.
    """
    with _OBSERVATION_LOCK:
        (
            supervisor,
            reader_path,
            supervisor_path,
            held_source_bytes,
            module_bindings,
        ) = _bind_sources(reader_module, supervisor_module, worker_module)
        observation = _Observation(reader_module, supervisor, held_source_bytes)
        _observation_originals = {
            name: getattr(supervisor, name) for name in _SUPERVISOR_IDENTITY_FUNCTIONS
        }
        reader_wrapper_originals = (
            reader_module._root_helper_wrapper,
            reader_module._run_pinned_root_helper,
            reader_module._require,
        )
        wrappers = None
        original_reader_bindings = {
            "threading": reader_module.threading,
            "_require": reader_module._require,
        }
        result = None
        outer_error = None
        wrappers_restored = False
        try:
            if observation.reader_retained_length_before != 0:
                observation.failed("source_binding", GateError("reader_retained_context_not_fresh"))
                wrappers_restored = True
            elif not _module_bindings_unchanged(module_bindings):
                observation.failed(
                    "source_binding", GateError("module_binding_changed_before_call")
                )
                wrappers_restored = True
            else:
                wrappers, original_reader_bindings = _install_wrappers(
                    reader_module, supervisor, observation
                )
                wrapper = reader_module._root_helper_wrapper(SYNTHETIC_HELPER)
                system_root = (
                    os.environ.get("SYSTEMROOT") or os.environ.get("WINDIR") or "C:\\Windows"
                )
                environment = {"SYSTEMROOT": system_root, "WINDIR": system_root}
                result = reader_module._run_pinned_root_helper(
                    wrapper,
                    environment,
                    timeout_seconds=60.0,
                )
        except BaseException as exc:
            outer_error = exc
            phase = observation.current_phase()
            observation.reader_failed(exc)
            if observation.reader_check_code is None:
                observation.failed(phase, exc)
        finally:
            if wrappers is not None:
                wrappers_restored = _restore_wrappers(
                    reader_module, supervisor, wrappers, original_reader_bindings
                )

        observation.pipes_eof_complete = (
            observation.stdout_eof
            and observation.stderr_eof
            and observation.stdout_done
            and observation.stderr_done
            and not observation.stdout_error
            and not observation.stderr_error
            and not observation.stdout_overflow
            and not observation.stderr_overflow
        )
        if result is not None:
            try:
                observation.output_matches = result[0] == SYNTHETIC_OUTPUT
                observation.stderr_empty = result[1] == b""
                observation.assigned = (
                    observation.assigned and result[4].get("assigned_before_resume") is True
                )
                if observation.job_count_after_exit is None:
                    observation.record_job_count(
                        "job_count_after_exit", result[4].get("active_count_after_exit")
                    )
            except Exception:
                observation.output_matches = False
                observation.stderr_empty = False
        if outer_error is not None and observation.error_category is None:
            category, code, winerror = _error_category(outer_error, reader_module, supervisor)
            observation.error_category = category
            observation.error_code = code
            observation.native_winerror = winerror
        observation.last_close_all_succeeded = (
            not observation.open_handles and observation.close_failures == 0
        )
        if not wrappers_restored:
            observation.failed("cleanup_close", GateError("source_restore_failed"))
        identities_restored = (
            all(
                getattr(supervisor, name) is original
                for name, original in _observation_originals.items()
            )
            and reader_module._root_helper_wrapper is reader_wrapper_originals[0]
            and reader_module._run_pinned_root_helper is reader_wrapper_originals[1]
            and reader_module._require is reader_wrapper_originals[2]
            and reader_module.threading is original_reader_bindings["threading"]
        )
        if not identities_restored:
            observation.failed("cleanup_close", GateError("source_identity_restore_failed"))
        module_bindings_unchanged_after = _module_bindings_unchanged(module_bindings)
        if not module_bindings_unchanged_after:
            observation.failed("cleanup_close", GateError("module_binding_changed_after_call"))
        observation.sourcefake = not _is_source_function(
            _observation_originals["_hold_runtime_files"], supervisor_path
        )
        uncertain = (
            not observation.wait_results
            or not observation.wait_results[0]
            or not observation.wait_results[-1]
            or not observation.process_exit_code_present
            or not observation.job_count_after_cleanup_attempted
            or type(observation.job_count_after_cleanup) is not int
            or observation.job_count_after_cleanup != 0
            or observation.job_count_after_cleanup_error is not None
            or (observation.terminate_requested and not observation.terminate_succeeded)
            or not observation.pipes_eof_complete
            or not all(observation.thread_joins.values())
            or bool(observation.open_handles)
            or observation.close_failures > 0
            or type(observation.reader_retained_registry) is not list
            or observation.reader_retained_length_before != 0
            or reader_module.__dict__.get("_ROOT_HELPER_RETAINED_CONTEXTS")
            is not observation.reader_retained_registry
            or type(reader_module.__dict__.get("_ROOT_HELPER_RETAINED_CONTEXTS")) is not list
            or len(observation.reader_retained_registry)
            != observation.reader_retained_length_before
            or len(reader_module.__dict__["_ROOT_HELPER_RETAINED_CONTEXTS"]) != 0
            or not module_bindings_unchanged_after
            or not wrappers_restored
        )
        if uncertain:
            _ORPHANED_GATE_CONTEXTS.append(
                (
                    observation,
                    reader_module,
                    supervisor,
                    observation.raw_kernel,
                    observation.kernel_proxy,
                    observation.control_reference,
                    tuple(observation.thread_references),
                    tuple(observation.pipe_state_references),
                    tuple(observation.open_handles),
                    supervisor._ORPHANED_RUNTIME_HANDLE_SETS,
                    observation.held_source_bytes,
                    module_bindings,
                )
            )
        output = observation.result()
        output["module_bindings_unchanged_after"] = module_bindings_unchanged_after
        output["source_functions_restored"] = (
            wrappers_restored and identities_restored and module_bindings_unchanged_after
        )
        output["retained_context"] = bool(
            _ORPHANED_GATE_CONTEXTS and _ORPHANED_GATE_CONTEXTS[-1][0] is observation
        )
        return output
