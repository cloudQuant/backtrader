"""One-use Root cleanup capsule for a proven prelaunch V18 namespace block.

This module is source-only until an independent review authorizes Root to call
``prepare_prelaunch_cleanup`` and then ``cleanup_once`` in the original owner
process/thread.  It does not start or retry activation.  It accepts only the
frozen R4B driver, frozen R5 wrapper, exact retained CUv2 lease, and the exact
public BLOCKED projection whose namespace guard precedes every credential and
worker operation.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
import hashlib
import json
import ntpath
import os
from pathlib import Path
import sys
import threading
import types
from typing import Any


PACKET_ID = "iteration41-c01-v18-root-prelaunch-cleanup-capsule-r3-2026-10-08"
DRIVER_PACKET_ID = "iteration41-c01-v18-root-actual-driver-draft-r4b-2026-10-08"
DRIVER_SHA256 = "f23aa6af03f8687ff99198cdc4184c72c3b9ee70d2be463fb1177b19e5c06fec"
V18_PINS_SHA256 = "3c1fdd78d0eaf6103478a534a51809948839daa9096a226a57d16f784890691d"
WRAPPER_SHA256 = "ce221c68a92bfce4ef0f273347f09c3260f127b6b68f985b16505ef7a1cda4bb"
CUV2_PATH = r"D:\temp\iteration41-root-public-custody-v2.py"
CUV2_SHA256 = "e856be8e4056835d4a7e54f5c6b449c69ab3f1c2ebb049bcbcc1c95a9ad3f246"
WRAPPER_MODULE_NAME = "_iteration41_simnow_c01_v18_root_activation_wrapper"
WRAPPER_RELATIVE = "scripts/run_simnow_c01_native_td_read_v18_root_activation_r2.py"
PUBLIC_COUNT = 31
SOFTWARE_COUNT = 2
HELD_COUNT = 33
MAX_DRIVER_BYTES = 2 * 1024 * 1024
MAX_PIN_BYTES = 256 * 1024

_LOCK = threading.RLock()
_ISSUED_LEASE_IDS: set[int] = set()
_DRIVER_FUNCTIONS = {
    "run_root_activation": "run_root_activation",
    "activate_with_held_sources": "activate_with_held_sources",
    "invoke_fixed_wrapper_main": "invoke_fixed_wrapper_main",
    "verify_held_source_map": "verify_held_source_map",
    "_expected_absolute_pins": "_expected_absolute_pins",
    "_expected_full_held_map": "_expected_full_held_map",
    "_load_module": "_load_module",
}
_LEASE_METHODS = ("verify_held", "postverify_and_close", "keepalive")
_HEX = frozenset("0123456789abcdef")
_PROFILE = "C01_NATIVE_TD_READ_V18"
_REASON = "admission_namespace_not_fresh"


class CleanupBlocked(RuntimeError):
    """A fixed safe cleanup reason; never carries source or provider details."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class CleanupReceipt:
    schema: str
    classification: str
    reason: str
    prelaunch_namespace_proven: bool
    full_held_map_verified: bool
    normal_cuv2_close_verified: bool
    exact_retained_tuple_removed: bool
    wrapper_retained_list_empty: bool
    wrapper_call_count: int
    official_c01_pass_count: int
    original_blocked_result_unchanged: bool


def _blocked(reason: str) -> CleanupReceipt:
    return CleanupReceipt(
        schema="iteration41.simnow.v18.root_prelaunch_cleanup_receipt.r3",
        classification="CLEANUP_BLOCKED_REFERENCES_RETAINED",
        reason=reason,
        prelaunch_namespace_proven=False,
        full_held_map_verified=False,
        normal_cuv2_close_verified=False,
        exact_retained_tuple_removed=False,
        wrapper_retained_list_empty=False,
        wrapper_call_count=0,
        official_c01_pass_count=0,
        original_blocked_result_unchanged=False,
    )


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _read_bounded(path: Path, limit: int) -> bytes:
    if not isinstance(path, Path) or type(limit) is not int or limit <= 0:
        raise CleanupBlocked("public_source_path_invalid")
    try:
        with path.open("rb") as stream:
            raw = stream.read(limit + 1)
    except Exception:
        raise CleanupBlocked("public_source_unavailable") from None
    if len(raw) > limit:
        raise CleanupBlocked("public_source_size_invalid")
    return raw


def _strict_json(raw: bytes) -> Any:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate")
            result[key] = value
        return result

    try:
        return json.loads(raw.decode("ascii"), object_pairs_hook=pairs)
    except Exception:
        raise CleanupBlocked("pinned_map_invalid") from None


def _module_source_identity(module: types.ModuleType, path: Path) -> bool:
    if type(module) is not types.ModuleType:
        return False
    try:
        origin = Path(module.__file__).resolve(strict=True)
        spec = module.__spec__
        spec_origin = Path(spec.origin).resolve(strict=True)
        expected = path.resolve(strict=True)
    except Exception:
        return False
    return origin == expected and spec_origin == expected


def _compiled_codes(raw: bytes, filename: str) -> dict[str, Any]:
    try:
        root = compile(raw, filename, "exec", dont_inherit=True, optimize=0)
    except Exception:
        raise CleanupBlocked("source_compile_binding_invalid") from None
    found: dict[str, Any] = {}

    def visit(code):
        found.setdefault(code.co_qualname, code)
        for item in code.co_consts:
            if isinstance(item, types.CodeType):
                visit(item)

    visit(root)
    return found


def _constant_signature(value: Any) -> Any:
    if isinstance(value, types.CodeType):
        return ("code", _code_signature(value))
    if type(value) is tuple:
        return ("tuple", tuple(_constant_signature(item) for item in value))
    return (type(value).__name__, value)


def _code_signature(code: types.CodeType) -> tuple:
    return (
        code.co_argcount,
        code.co_posonlyargcount,
        code.co_kwonlyargcount,
        code.co_nlocals,
        code.co_stacksize,
        code.co_flags,
        code.co_code,
        tuple(_constant_signature(item) for item in code.co_consts),
        code.co_names,
        code.co_varnames,
        code.co_freevars,
        code.co_cellvars,
        code.co_filename,
        code.co_name,
        code.co_qualname,
        code.co_firstlineno,
        code.co_linetable,
        code.co_exceptiontable,
    )


def _function_matches(function: Any, module: types.ModuleType, codes: dict[str, Any], qualname: str) -> bool:
    if not callable(function):
        return False
    code = getattr(function, "__code__", None)
    expected = codes.get(qualname)
    closure = getattr(function, "__closure__", None)
    return bool(
        isinstance(code, types.CodeType)
        and isinstance(expected, types.CodeType)
        and getattr(function, "__globals__", None) is module.__dict__
        and getattr(function, "__module__", None) == module.__name__
        and code.co_qualname == qualname
        and len(closure or ()) == len(code.co_freevars)
        and _code_signature(code) == _code_signature(expected)
    )


def _class_function(cls: Any, name: str) -> Any:
    value = getattr(cls, name, None)
    return getattr(value, "__func__", value)


def _driver_binding(driver: types.ModuleType) -> tuple[Path, bytes, dict[str, Any]]:
    if type(driver) is not types.ModuleType:
        raise CleanupBlocked("driver_module_identity_invalid")
    packet_dir = Path(__file__).resolve(strict=True).parents[0]
    expected_driver = (
        Path(driver.ROOT)
        / "docs"
        / "_internal"
        / "opts"
        / "requirements"
        / "迭代41-实盘执行风控监控与示例架构重构"
        / "evidence"
        / DRIVER_PACKET_ID
        / "root-actual-driver.py"
    )
    try:
        actual_driver = Path(driver.__file__).resolve(strict=True)
        actual_packet = Path(driver.PACKET_DIR).resolve(strict=True)
        expected_driver = expected_driver.resolve(strict=True)
    except Exception:
        raise CleanupBlocked("driver_origin_invalid") from None
    if (
        actual_driver != expected_driver
        or actual_packet != expected_driver.parent
        or driver.PACKET_ID != DRIVER_PACKET_ID
        or Path(driver.ROOT).resolve(strict=True) != Path("D:/source_code/backtrader").resolve(strict=True)
        or str(driver.CUV2_PATH).casefold() != CUV2_PATH.casefold()
        or driver.CUV2_SHA256 != CUV2_SHA256
        or not _module_source_identity(driver, expected_driver)
    ):
        raise CleanupBlocked("driver_origin_invalid")
    raw = _read_bounded(expected_driver, MAX_DRIVER_BYTES)
    if _sha(raw) != DRIVER_SHA256:
        raise CleanupBlocked("driver_source_pin_mismatch")
    codes = _compiled_codes(raw, str(expected_driver))
    required = {
        "run_root_activation": "run_root_activation",
        "activate_with_held_sources": "activate_with_held_sources",
        "invoke_fixed_wrapper_main": "invoke_fixed_wrapper_main",
        "verify_held_source_map": "verify_held_source_map",
        "_expected_absolute_pins": "_expected_absolute_pins",
        "_expected_full_held_map": "_expected_full_held_map",
        "_load_module": "_load_module",
    }
    for attribute, qualname in required.items():
        if not _function_matches(getattr(driver, attribute, None), driver, codes, qualname):
            raise CleanupBlocked("driver_code_identity_invalid")
    cls = getattr(driver, "HeldSourceLease", None)
    if not isinstance(cls, type) or cls.__module__ != driver.__name__:
        raise CleanupBlocked("lease_type_identity_invalid")
    for name in ("verify_held", "postverify_and_close", "keepalive"):
        if not _function_matches(_class_function(cls, name), driver, codes, f"HeldSourceLease.{name}"):
            raise CleanupBlocked("lease_code_identity_invalid")
    if getattr(driver, "KEEPALIVE", None) is None or type(driver.KEEPALIVE) is not list:
        raise CleanupBlocked("driver_keepalive_identity_invalid")
    return expected_driver, raw, codes


@dataclass(frozen=True)
class _RuntimeDriverBinding:
    lease_class: type
    driver_functions: dict[str, tuple[Any, types.CodeType, dict[str, Any]]]
    lease_methods: dict[str, tuple[Any, types.CodeType, dict[str, Any]]]


def _capture_runtime_driver_binding(
    driver: types.ModuleType,
    lease: Any,
    codes: dict[str, Any],
) -> _RuntimeDriverBinding:
    """Capture exact pinned callable/class identities and reject instance shadows."""

    if type(driver) is not types.ModuleType:
        raise CleanupBlocked("driver_module_identity_invalid")
    driver_functions = {}
    for name, qualname in _DRIVER_FUNCTIONS.items():
        function = getattr(driver, name, None)
        if type(function) is not types.FunctionType or not _function_matches(function, driver, codes, qualname):
            raise CleanupBlocked("driver_code_identity_invalid")
        driver_functions[name] = (function, function.__code__, function.__globals__)

    cls = getattr(driver, "HeldSourceLease", None)
    if (
        type(cls) is not type
        or cls.__module__ != driver.__name__
        or cls.__qualname__ != "HeldSourceLease"
        or type(lease) is not cls
    ):
        raise CleanupBlocked("lease_type_identity_invalid")
    try:
        instance_namespace = object.__getattribute__(lease, "__dict__")
    except Exception:
        raise CleanupBlocked("lease_instance_namespace_invalid") from None
    if type(instance_namespace) is not dict:
        raise CleanupBlocked("lease_instance_namespace_invalid")
    if any(name in instance_namespace for name in _LEASE_METHODS):
        raise CleanupBlocked("lease_method_shadow_invalid")

    lease_methods = {}
    for name in _LEASE_METHODS:
        function = cls.__dict__.get(name)
        qualname = f"HeldSourceLease.{name}"
        if (
            type(function) is not types.FunctionType
            or getattr(cls, name, None) is not function
            or not _function_matches(function, driver, codes, qualname)
        ):
            raise CleanupBlocked("lease_code_identity_invalid")
        lease_methods[name] = (function, function.__code__, function.__globals__)
    return _RuntimeDriverBinding(cls, driver_functions, lease_methods)


def _same_callable_refs(
    current: dict[str, tuple[Any, types.CodeType, dict[str, Any]]],
    expected: dict[str, tuple[Any, types.CodeType, dict[str, Any]]],
) -> bool:
    return bool(
        current.keys() == expected.keys()
        and all(
            current[name][0] is expected[name][0]
            and current[name][1] is expected[name][1]
            and current[name][2] is expected[name][2]
            for name in expected
        )
    )


def _recheck_runtime_driver_binding(
    driver: types.ModuleType,
    lease: Any,
    codes: dict[str, Any],
    expected: _RuntimeDriverBinding,
) -> types.FunctionType:
    current = _capture_runtime_driver_binding(driver, lease, codes)
    if current.lease_class is not expected.lease_class:
        raise CleanupBlocked("lease_class_identity_changed")
    if not _same_callable_refs(current.driver_functions, expected.driver_functions):
        raise CleanupBlocked("driver_callable_identity_changed")
    if not _same_callable_refs(current.lease_methods, expected.lease_methods):
        raise CleanupBlocked("lease_callable_identity_changed")
    close_function = expected.lease_methods["postverify_and_close"][0]
    if type(close_function) is not types.FunctionType:
        raise CleanupBlocked("lease_close_function_invalid")
    return close_function


def _exact_projection(result: Any) -> bool:
    if type(result) is not dict:
        return False
    expected_top = {
        "schema",
        "classification",
        "profile_result",
        "independent_review_verified",
        "root_readback_verified",
        "intended_public_source_count",
        "intended_software_pin_count",
        "intended_held_file_count",
        "cuv2_scope_entered",
        "held_source_map_verified",
        "observed_public_source_count",
        "observed_software_pin_count",
        "observed_held_file_count",
        "wrapper_call_count",
        "wrapper_projection_verified",
        "outer_cuv2_postverify_verified",
        "outer_cuv2_scope_closed",
        "writes",
        "official_c01_pass_count",
        "formal_c01_pass",
        "private_capture_read_by_driver",
        "opaque_receipt_seen_by_driver",
        "late_private_capture_read",
    }
    if set(result) != expected_top:
        return False
    profile = result.get("profile_result")
    expected_profile_keys = {
        "case_id",
        "certification",
        "mode",
        "profile",
        "reason",
        "write_policy",
        "writes",
        "receipt_type",
        "receipt_verified",
        "source_closure_verified",
        "root_postverify_verified",
        "request_count",
        "query_callback_count",
        "snapshot_count",
        "write_invocation_count",
        "outer_job_empty",
        "stdout_eof",
        "stderr_eof",
        "stderr_empty",
        "job_handles_closed",
        "reader_threads_joined",
        "cleanup_verified",
    }
    if type(profile) is not dict or set(profile) != expected_profile_keys:
        return False
    if (
        result.get("schema") != "iteration41.simnow.v18.root_actual_driver.public_result.r4b"
        or result.get("classification") != "ROOT_PROFILE_RESULT_NOT_OFFICIAL_C01_ACCEPTANCE"
        or profile.get("case_id") != "C01"
        or profile.get("certification") != "BLOCKED"
        or profile.get("mode") != _PROFILE
        or profile.get("profile") != _PROFILE
        or profile.get("reason") != _REASON
        or profile.get("write_policy") != "NO_WRITE"
        or profile.get("receipt_type") is not None
    ):
        return False
    for key in (
        "receipt_verified",
        "source_closure_verified",
        "root_postverify_verified",
        "outer_job_empty",
        "stdout_eof",
        "stderr_eof",
        "stderr_empty",
        "job_handles_closed",
        "reader_threads_joined",
        "cleanup_verified",
    ):
        if profile.get(key) is not False:
            return False
    for key in ("writes", "request_count", "query_callback_count", "snapshot_count", "write_invocation_count"):
        if type(profile.get(key)) is not int or profile[key] != 0:
            return False
    true_state = (
        "independent_review_verified",
        "root_readback_verified",
        "cuv2_scope_entered",
        "held_source_map_verified",
        "wrapper_projection_verified",
    )
    false_state = (
        "outer_cuv2_postverify_verified",
        "outer_cuv2_scope_closed",
        "formal_c01_pass",
        "private_capture_read_by_driver",
        "opaque_receipt_seen_by_driver",
        "late_private_capture_read",
    )
    if any(result.get(key) is not True for key in true_state):
        return False
    if any(result.get(key) is not False for key in false_state):
        return False
    exact_counts = {
        "intended_public_source_count": PUBLIC_COUNT,
        "intended_software_pin_count": SOFTWARE_COUNT,
        "intended_held_file_count": HELD_COUNT,
        "observed_public_source_count": PUBLIC_COUNT,
        "observed_software_pin_count": SOFTWARE_COUNT,
        "observed_held_file_count": HELD_COUNT,
        "wrapper_call_count": 1,
        "writes": 0,
        "official_c01_pass_count": 0,
    }
    return all(type(result.get(key)) is int and result[key] == value for key, value in exact_counts.items())


def _path_key(value: str) -> str:
    return ntpath.normcase(ntpath.normpath(value))


def _same_expected_map(actual: Any, expected: dict[str, tuple[str, str]]) -> bool:
    if type(actual) is not dict or len(actual) != len(expected):
        return False
    if any(type(key) is not str for key in actual):
        return False
    if set(actual) != set(expected):
        return False
    for key, want in expected.items():
        row = actual.get(key)
        if type(row) is not tuple or len(row) != 2 or row != want:
            return False
    return True


def _require_empty_retained_list(activation: Any, expected_list: Any = None) -> list:
    current = getattr(activation, "_ROOT_RETAINED_UNRESOLVED_JOB_REFS", None)
    if type(current) is not list or len(current) != 0:
        raise CleanupBlocked("wrapper_job_refs_not_empty_list")
    if expected_list is not None and current is not expected_list:
        raise CleanupBlocked("wrapper_job_refs_list_identity_changed")
    return current


def _remove_exact_closed_holder(
    keepalive: Any,
    holder: Any,
    *,
    normal_exit_verified: Any,
    postverify_verified: Any,
) -> bool:
    if (
        type(keepalive) is not list
        or type(holder) is not tuple
        or normal_exit_verified is not True
        or postverify_verified is not True
        or len(keepalive) != 1
        or keepalive[0] is not holder
    ):
        return False
    keepalive.pop(0)
    if len(keepalive) == 0:
        return True
    keepalive.insert(0, holder)
    return False


def _expected_map(driver: types.ModuleType) -> tuple[dict[str, tuple[str, str]], bytes]:
    if (
        driver.V18_PINS_SHA256 != V18_PINS_SHA256
        or driver.WRAPPER_SHA256 != WRAPPER_SHA256
        or driver.WRAPPER_RELATIVE != WRAPPER_RELATIVE
    ):
        raise CleanupBlocked("pinned_source_contract_invalid")
    packet_path = Path(driver.PACKET_DIR) / "reference" / "v18-activation-r5" / "pins.json"
    raw = _read_bounded(packet_path, MAX_PIN_BYTES)
    if _sha(raw) != V18_PINS_SHA256:
        raise CleanupBlocked("pinned_map_hash_mismatch")
    pins = _strict_json(raw)
    public = pins.get("public_source_pins") if type(pins) is dict else None
    software = pins.get("software_pins") if type(pins) is dict else None
    if type(public) is not dict or type(software) is not dict or len(public) != PUBLIC_COUNT or len(software) != SOFTWARE_COUNT:
        raise CleanupBlocked("pinned_map_cardinality_invalid")
    root = Path(driver.ROOT)
    expected: dict[str, tuple[str, str]] = {}
    for rel, digest in public.items():
        if type(rel) is not str or Path(rel).is_absolute() or type(digest) is not str or len(digest) != 64 or not set(digest) <= _HEX:
            raise CleanupBlocked("pinned_map_row_invalid")
        path = str(root / rel)
        key = _path_key(path)
        if key in expected:
            raise CleanupBlocked("pinned_map_duplicate")
        expected[key] = (path, digest)
    for path, digest in software.items():
        if type(path) is not str or not ntpath.isabs(path) or type(digest) is not str or len(digest) != 64 or not set(digest) <= _HEX:
            raise CleanupBlocked("pinned_map_row_invalid")
        key = _path_key(path)
        if key in expected:
            raise CleanupBlocked("pinned_map_overlap")
        expected[key] = (path, digest)
    if len(expected) != HELD_COUNT:
        raise CleanupBlocked("pinned_map_cardinality_invalid")
    wrapper_key = _path_key(str(root / WRAPPER_RELATIVE))
    if expected.get(wrapper_key) != (str(root / WRAPPER_RELATIVE), WRAPPER_SHA256):
        raise CleanupBlocked("wrapper_pin_invalid")
    return expected, raw


def _held_map(lease: Any, expected: dict[str, tuple[str, str]]) -> dict[str, bytes]:
    held = getattr(lease, "held", None)
    if type(held) is not dict:
        raise CleanupBlocked("held_map_type_invalid")
    normalized: dict[str, bytes] = {}
    for path, raw in held.items():
        if type(path) is not str or not ntpath.isabs(path) or type(raw) is not bytes:
            raise CleanupBlocked("held_map_row_invalid")
        key = _path_key(path)
        if key in normalized:
            raise CleanupBlocked("held_map_duplicate")
        normalized[key] = raw
    if set(normalized) != set(expected):
        raise CleanupBlocked("held_map_keys_invalid")
    for key, (_path, digest) in expected.items():
        if _sha(normalized[key]) != digest:
            raise CleanupBlocked("held_map_hash_invalid")
    return normalized


def _wrapper_static_gate(raw: bytes, filename: str) -> tuple[dict[str, Any], ast.Module]:
    if type(raw) is not bytes or _sha(raw) != WRAPPER_SHA256:
        raise CleanupBlocked("wrapper_source_pin_mismatch")
    try:
        tree = ast.parse(raw.decode("utf-8"), filename=filename)
    except Exception:
        raise CleanupBlocked("wrapper_source_parse_invalid") from None
    reason_literals = [node for node in ast.walk(tree) if isinstance(node, ast.Constant) and node.value == _REASON]
    if len(reason_literals) != 1:
        raise CleanupBlocked("namespace_reason_not_unique")
    cls = next(
        (node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "_ProductionPorts"),
        None,
    )
    if cls is None:
        raise CleanupBlocked("namespace_gate_source_missing")
    namespace = next(
        (node for node in cls.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "activation_namespace_lease"),
        None,
    )
    core = next(
        (node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "_run_core"),
        None,
    )
    if namespace is None or core is None:
        raise CleanupBlocked("namespace_gate_source_missing")
    if not any(
        isinstance(decorator, ast.Name) and decorator.id == "contextmanager"
        for decorator in namespace.decorator_list
    ):
        raise CleanupBlocked("namespace_gate_contextmanager_invalid")
    raises = []
    yields = []
    for node in ast.walk(namespace):
        if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
            function = node.exc.func
            if isinstance(function, ast.Name) and function.id == "RootActivationError" and node.exc.args:
                if isinstance(node.exc.args[0], ast.Constant) and node.exc.args[0].value == _REASON:
                    raises.append(node)
        if isinstance(node, (ast.Yield, ast.YieldFrom)):
            yields.append(node)
    if len(raises) != 1 or len(yields) != 1 or raises[0].lineno >= yields[0].lineno:
        raise CleanupBlocked("namespace_gate_not_prelaunch")
    namespace_with = []
    run_calls = []
    for node in ast.walk(core):
        if isinstance(node, ast.With):
            for item in node.items:
                context = item.context_expr
                if (
                    isinstance(context, ast.Call)
                    and isinstance(context.func, ast.Attribute)
                    and isinstance(context.func.value, ast.Name)
                    and context.func.value.id == "ports"
                    and context.func.attr == "activation_namespace_lease"
                ):
                    namespace_with.append(node)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
            if node.func.value.id == "ports" and node.func.attr == "run_fixed_cli":
                run_calls.append(node)
    if len(namespace_with) != 1 or len(run_calls) != 1 or run_calls[0].lineno <= namespace_with[0].end_lineno:
        raise CleanupBlocked("fixed_cli_not_after_namespace_gate")
    codes = _compiled_codes(raw, filename)
    return codes, tree


def _check_wrapper_module(activation: types.ModuleType, wrapper_path: Path, raw: bytes) -> None:
    if (
        type(activation) is not types.ModuleType
        or activation.__name__ != WRAPPER_MODULE_NAME
        or sys.modules.get(WRAPPER_MODULE_NAME) is not activation
        or not _module_source_identity(activation, wrapper_path)
    ):
        raise CleanupBlocked("activation_module_identity_invalid")
    codes, _tree = _wrapper_static_gate(raw, str(wrapper_path))
    if (
        getattr(activation, "CASE_ID", None) != "C01"
        or getattr(activation, "PROFILE_ID", None) != _PROFILE
        or not _function_matches(getattr(activation, "_public_blocked", None), activation, codes, "_public_blocked")
        or not _function_matches(getattr(activation, "_run_production", None), activation, codes, "_run_production")
    ):
        raise CleanupBlocked("wrapper_prelaunch_dispatch_identity_invalid")
    error_type = getattr(activation, "RootActivationError", None)
    if (
        not isinstance(error_type, type)
        or error_type.__module__ != activation.__name__
        or error_type.__qualname__ != "RootActivationError"
        or error_type.__bases__ != (RuntimeError,)
        or not _function_matches(error_type.__init__, activation, codes, "RootActivationError.__init__")
    ):
        raise CleanupBlocked("wrapper_error_type_identity_invalid")
    error_init = error_type.__init__
    error_cells = tuple(cell.cell_contents for cell in (error_init.__closure__ or ()))
    if error_cells != (error_type,):
        raise CleanupBlocked("wrapper_error_type_closure_invalid")
    if not _function_matches(getattr(activation, "main", None), activation, codes, "main"):
        raise CleanupBlocked("wrapper_main_code_identity_invalid")
    if not _function_matches(getattr(activation, "_run_core", None), activation, codes, "_run_core"):
        raise CleanupBlocked("wrapper_core_code_identity_invalid")
    ports = getattr(activation, "_ProductionPorts", None)
    if not isinstance(ports, type) or ports.__module__ != activation.__name__:
        raise CleanupBlocked("wrapper_ports_type_invalid")
    if not _function_matches(_class_function(ports, "__init__"), activation, codes, "_ProductionPorts.__init__"):
        raise CleanupBlocked("wrapper_ports_constructor_identity_invalid")
    namespace_factory = _class_function(ports, "activation_namespace_lease")
    namespace_generator = getattr(namespace_factory, "__wrapped__", None)
    if not _function_matches(namespace_generator, activation, codes, "_ProductionPorts.activation_namespace_lease"):
        raise CleanupBlocked("namespace_code_identity_invalid")
    try:
        from contextlib import contextmanager

        expected_factory = contextmanager(namespace_generator)
    except Exception:
        raise CleanupBlocked("namespace_factory_identity_invalid") from None
    if (
        getattr(namespace_factory, "__wrapped__", None) is not namespace_generator
        or getattr(namespace_factory, "__globals__", None) is not expected_factory.__globals__
        or tuple(cell.cell_contents for cell in (namespace_factory.__closure__ or ())) != (namespace_generator,)
        or _code_signature(namespace_factory.__code__) != _code_signature(expected_factory.__code__)
    ):
        raise CleanupBlocked("namespace_factory_identity_invalid")
    if not _function_matches(_class_function(ports, "run_fixed_cli"), activation, codes, "_ProductionPorts.run_fixed_cli"):
        raise CleanupBlocked("fixed_cli_code_identity_invalid")


def _find_retained(driver: types.ModuleType, activation: types.ModuleType) -> tuple[Any, Any, list]:
    keepalive = getattr(driver, "KEEPALIVE", None)
    if type(keepalive) is not list:
        raise CleanupBlocked("driver_keepalive_identity_invalid")
    unresolved = _require_empty_retained_list(activation)
    cls = driver.HeldSourceLease
    matches = [item for item in keepalive if type(item) is tuple and len(item) >= 8 and type(item[0]) is cls]
    if len(keepalive) != 1 or len(matches) != 1:
        raise CleanupBlocked("retained_lease_membership_invalid")
    holder = matches[0]
    lease = holder[0]
    refs = getattr(lease, "references", None)
    if type(refs) is not list or len(refs) != 1 or refs[0] is not activation:
        raise CleanupBlocked("lease_reference_membership_invalid")
    expected_holder = (
        lease,
        lease.manager,
        lease.private_module,
        lease.cli_module,
        lease.held,
        lease.expected,
        lease.cuv2_raw,
        activation,
        *refs,
    )
    if len(holder) != len(expected_holder) or any(a is not b for a, b in zip(holder, expected_holder)):
        raise CleanupBlocked("retained_tuple_identity_invalid")
    if getattr(driver, "ACTIVATION", None) is not activation:
        raise CleanupBlocked("activation_global_identity_invalid")
    return lease, holder, unresolved


def _check_lease_state(lease: Any) -> None:
    if (
        getattr(lease, "entered", None) is not True
        or getattr(lease, "closed", None) is not False
        or getattr(lease, "exit_started", None) is not False
        or getattr(lease, "postverify_complete", None) is not False
    ):
        raise CleanupBlocked("lease_not_open_uncertain")


def _canonical_result(result: dict) -> bytes:
    try:
        return json.dumps(result, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("ascii")
    except Exception:
        raise CleanupBlocked("result_projection_invalid") from None


class RootPrelaunchCleanupCapsule:
    """A one-use capability bound to one result, one lease, and one thread."""

    __slots__ = (
        "_driver",
        "_keepalive_list",
        "_activation",
        "_lease",
        "_holder",
        "_unresolved_list",
        "_result",
        "_result_bytes",
        "_expected_map",
        "_wrapper_raw",
        "_wrapper_path",
        "_driver_path",
        "_driver_raw",
        "_driver_codes",
        "_runtime_binding",
        "_owner_pid",
        "_owner_thread",
        "_used",
        "_issued_id",
    )

    def __init__(self, token: object, *, driver: types.ModuleType, result: dict):
        if token is not _CAPSULE_TOKEN:
            raise CleanupBlocked("capsule_constructor_closed")
        self._driver = driver
        self._keepalive_list = None
        self._activation = None
        self._lease = None
        self._holder = None
        self._unresolved_list = None
        self._result = result
        self._result_bytes = _canonical_result(result)
        self._expected_map = None
        self._wrapper_raw = None
        self._wrapper_path = None
        self._driver_path = None
        self._driver_raw = None
        self._driver_codes = None
        self._runtime_binding = None
        self._owner_pid = os.getpid()
        self._owner_thread = threading.get_ident()
        self._used = False
        self._issued_id = None
        self._preflight()

    def _preflight(self) -> None:
        if not _exact_projection(self._result):
            raise CleanupBlocked("actual_blocked_projection_mismatch")
        driver_path, driver_raw, codes = _driver_binding(self._driver)
        expected, _pins_raw = _expected_map(self._driver)
        activation = getattr(self._driver, "ACTIVATION", None)
        if type(activation) is not types.ModuleType or activation.__name__ != WRAPPER_MODULE_NAME:
            raise CleanupBlocked("activation_global_identity_invalid")
        keepalive_list = getattr(self._driver, "KEEPALIVE", None)
        if type(keepalive_list) is not list:
            raise CleanupBlocked("driver_keepalive_identity_invalid")
        lease, holder, unresolved = _find_retained(self._driver, activation)
        if getattr(self._driver, "KEEPALIVE", None) is not keepalive_list:
            raise CleanupBlocked("driver_keepalive_identity_changed")
        runtime_binding = _capture_runtime_driver_binding(self._driver, lease, codes)
        _check_lease_state(lease)
        if not _same_expected_map(getattr(lease, "expected", None), expected):
            raise CleanupBlocked("lease_expected_map_mismatch")
        expected_snapshot = dict(expected)
        if type(getattr(lease, "cuv2_raw", None)) is not bytes or _sha(lease.cuv2_raw) != CUV2_SHA256:
            raise CleanupBlocked("cuv2_held_source_mismatch")
        public_count = getattr(lease, "public_source_count", None)
        software_count = getattr(lease, "software_pin_count", None)
        if type(public_count) is not int or public_count != PUBLIC_COUNT or type(software_count) is not int or software_count != SOFTWARE_COUNT:
            raise CleanupBlocked("lease_pin_counts_mismatch")
        held = _held_map(lease, expected_snapshot)
        wrapper_path = Path(self._driver.ROOT) / WRAPPER_RELATIVE
        wrapper_key = _path_key(str(wrapper_path))
        wrapper_raw = held.get(wrapper_key)
        if type(wrapper_raw) is not bytes or _sha(wrapper_raw) != WRAPPER_SHA256:
            raise CleanupBlocked("wrapper_held_source_mismatch")
        if not _module_source_identity(activation, wrapper_path):
            raise CleanupBlocked("activation_origin_invalid")
        _check_wrapper_module(activation, wrapper_path, wrapper_raw)
        self._expected_map = expected_snapshot
        self._wrapper_raw = wrapper_raw
        self._wrapper_path = wrapper_path
        self._driver_path = driver_path
        self._driver_raw = driver_raw
        self._driver_codes = codes
        self._runtime_binding = runtime_binding
        self._keepalive_list = keepalive_list
        self._activation = activation
        self._lease = lease
        self._holder = holder
        self._unresolved_list = unresolved

    def _recheck_before_close(self) -> types.FunctionType:
        if os.getpid() != self._owner_pid or threading.get_ident() != self._owner_thread:
            raise CleanupBlocked("cleanup_owner_changed")
        if not _exact_projection(self._result) or _canonical_result(self._result) != self._result_bytes:
            raise CleanupBlocked("actual_result_changed")
        if getattr(self._driver, "ACTIVATION", None) is not self._activation:
            raise CleanupBlocked("activation_global_identity_changed")
        if type(getattr(self._driver, "KEEPALIVE", None)) is not list:
            raise CleanupBlocked("driver_keepalive_identity_invalid")
        if self._driver.KEEPALIVE is not self._keepalive_list:
            raise CleanupBlocked("driver_keepalive_identity_changed")
        # Exact list type, same container object, and len==0 are all required.
        if (
            _require_empty_retained_list(self._activation, self._unresolved_list) is not self._unresolved_list
        ):
            raise CleanupBlocked("wrapper_job_refs_not_empty_list")
        if len(self._driver.KEEPALIVE) != 1 or self._driver.KEEPALIVE[0] is not self._holder:
            raise CleanupBlocked("retained_tuple_membership_changed")
        lease, holder, unresolved = _find_retained(self._driver, self._activation)
        if lease is not self._lease or holder is not self._holder or unresolved is not self._unresolved_list:
            raise CleanupBlocked("retained_lease_identity_changed")
        _check_lease_state(self._lease)
        if not _same_expected_map(self._lease.expected, self._expected_map):
            raise CleanupBlocked("lease_expected_map_changed")
        if type(getattr(self._lease, "cuv2_raw", None)) is not bytes or _sha(self._lease.cuv2_raw) != CUV2_SHA256:
            raise CleanupBlocked("cuv2_held_source_changed")
        held = _held_map(self._lease, self._expected_map)
        if held.get(_path_key(str(self._wrapper_path))) != self._wrapper_raw:
            raise CleanupBlocked("wrapper_held_source_changed")
        _check_wrapper_module(self._activation, self._wrapper_path, self._wrapper_raw)
        # Recheck the exact empty list immediately before lease close.
        if (
            _require_empty_retained_list(self._activation, self._unresolved_list) is not self._unresolved_list
        ):
            raise CleanupBlocked("wrapper_job_refs_not_empty_list")
        # Rebind the frozen driver and its live function/class objects after
        # every mutable holder, lease, source-map, wrapper, and retained-list
        # check.  The caller uses this captured class function directly.
        driver_path, driver_raw, codes = _driver_binding(self._driver)
        if driver_path != self._driver_path or driver_raw != self._driver_raw:
            raise CleanupBlocked("driver_source_binding_changed")
        return _recheck_runtime_driver_binding(
            self._driver,
            self._lease,
            codes,
            self._runtime_binding,
        )

    def cleanup_once(self) -> CleanupReceipt:
        with _LOCK:
            if self._used:
                return _blocked("cleanup_capsule_already_used")
            self._used = True
            if os.getpid() != self._owner_pid or threading.get_ident() != self._owner_thread:
                return _blocked("cleanup_owner_changed")
            lease = self._lease
            if lease is None or self._issued_id != id(lease) or id(lease) not in _ISSUED_LEASE_IDS:
                return _blocked("cleanup_lease_already_issued")
            try:
                close_function = self._recheck_before_close()
            except CleanupBlocked as error:
                return _blocked(error.reason)
            except Exception:
                return _blocked("cleanup_preflight_failed")
            try:
                closed = close_function(
                    lease,
                    cuv2_path=self._driver.CUV2_PATH,
                    cuv2_sha256=self._driver.CUV2_SHA256,
                )
            except BaseException:
                return _blocked("normal_cuv2_close_failed")
            if (
                closed is not True
                or getattr(lease, "closed", None) is not True
                or getattr(lease, "exit_started", None) is not True
                or getattr(lease, "postverify_complete", None) is not True
                or getattr(lease, "entered", None) is not True
            ):
                return _blocked("normal_cuv2_close_unverified")
            try:
                _held_map(lease, self._expected_map)
                if (
                    _require_empty_retained_list(self._activation, self._unresolved_list) is not self._unresolved_list
                    or type(self._driver.KEEPALIVE) is not list
                    or self._driver.KEEPALIVE is not self._keepalive_list
                    or len(self._driver.KEEPALIVE) != 1
                    or self._driver.KEEPALIVE[0] is not self._holder
                    or self._result.get("official_c01_pass_count") != 0
                    or self._result.get("formal_c01_pass") is not False
                ):
                    return _blocked("postclose_retention_state_unverified")
            except Exception:
                return _blocked("postclose_retention_state_unverified")
            if not _exact_projection(self._result) or _canonical_result(self._result) != self._result_bytes:
                return _blocked("original_result_changed")
            # Remove only the exact holder tuple, and only after the normal
            # postverify/close path has positively completed.
            if not _remove_exact_closed_holder(
                self._keepalive_list,
                self._holder,
                normal_exit_verified=lease.closed is True and lease.exit_started is True,
                postverify_verified=lease.postverify_complete is True,
            ):
                return _blocked("retained_tuple_removal_unverified")
            if not _exact_projection(self._result) or _canonical_result(self._result) != self._result_bytes:
                if type(self._keepalive_list) is list and not any(
                    item is self._holder for item in self._keepalive_list
                ):
                    self._keepalive_list.insert(0, self._holder)
                return _blocked("original_result_changed")
            receipt = CleanupReceipt(
                schema="iteration41.simnow.v18.root_prelaunch_cleanup_receipt.r3",
                classification="PRELAUNCH_NAMESPACE_BLOCK_CLEANED",
                reason="prelaunch_namespace_block_normal_cuv2_close",
                prelaunch_namespace_proven=True,
                full_held_map_verified=True,
                normal_cuv2_close_verified=True,
                exact_retained_tuple_removed=True,
                wrapper_retained_list_empty=True,
                wrapper_call_count=1,
                official_c01_pass_count=0,
                original_blocked_result_unchanged=(
                    _exact_projection(self._result)
                    and _canonical_result(self._result) == self._result_bytes
                ),
            )
            if not receipt.original_blocked_result_unchanged:
                if type(self._keepalive_list) is list and not any(
                    item is self._holder for item in self._keepalive_list
                ):
                    self._keepalive_list.insert(0, self._holder)
                return _blocked("original_result_changed")
            self._driver = None
            self._keepalive_list = None
            self._activation = None
            self._lease = None
            self._holder = None
            self._unresolved_list = None
            self._result = None
            self._expected_map = None
            self._wrapper_raw = None
            self._wrapper_path = None
            self._driver_path = None
            self._driver_raw = None
            self._driver_codes = None
            self._runtime_binding = None
            return receipt


_CAPSULE_TOKEN = object()


def prepare_prelaunch_cleanup(driver_module: types.ModuleType, actual_result: dict) -> RootPrelaunchCleanupCapsule:
    """Validate the exact live R4B/R5 state and return a single-use capability.

    The caller must pass the same Root-owned driver module and public result
    object returned by the original activation call.  This function performs
    source/hash/identity checks only; it does not close or retry anything.
    """

    with _LOCK:
        capsule = RootPrelaunchCleanupCapsule(_CAPSULE_TOKEN, driver=driver_module, result=actual_result)
        lease = capsule._lease
        if lease is None or id(lease) in _ISSUED_LEASE_IDS:
            raise CleanupBlocked("cleanup_lease_already_issued")
        _ISSUED_LEASE_IDS.add(id(lease))
        # The lease id is reserved at admission. cleanup_once recognizes this
        # capsule's own reservation via the local token stored below.
        capsule._issued_id = id(lease)
        return capsule

