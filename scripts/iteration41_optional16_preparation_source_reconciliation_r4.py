"""Close the retained Optional16 preparation source scopes, once, from Root.

This component verifies the consumed R1/R2/R3 reconciliation chain, then closes
the exact source-custody leases left open by the original Root preparation
attempt. It does not retry preparation, enter an installer, create a worker,
or claim account/provider/Optional16 authority.
"""

from __future__ import annotations

import ast
import contextlib
import hashlib
import importlib.machinery
import inspect
import json
import ntpath
from pathlib import Path, PurePath
import re
import sys
import threading
import types
import stat
import time


SCHEMA = "iteration41.optional16.preparation.source-reconciliation.r4"
ROOT = Path(r"D:\source_code\backtrader")
EVIDENCE = "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/"
ROOT_RUNNER_REL = ".codex-tmp/optional16_root_preparation_actual_20261009.py"
ROOT_RUNNER_SHA256 = "5fb9fb55fbfbfda43687b6020d40db9653269a422dae5478dc7ede3ee8f7dd35"
ROOT_RUNNER_ARGV0 = ".codex-tmp/optional16_root_preparation_actual_20261009.py"
ROOT_SYS_EXECUTABLE = "C:/anaconda3/python.exe"
ROOT_SYS_VERSION = (3, 11, 5)
DRIVER_REL = "scripts/iteration41_optional16_r33_root_preparation_driver_r1.py"
DRIVER_SHA256 = "7930bb76a89b4a29721b30aac40163bebb2714667474961a4a058e066d62d71c"
CALL_REL = "scripts/iteration41_optional16_r33_root_preparation_call_r1.py"
CALL_SHA256 = "762cf58ed2d9d4e2eed2c089a967946610ba660854327d7786c63f463ae4ef8e"
ENTRY_REL = "scripts/iteration41_optional16_r33_root_held_entry_r2.py"
ENTRY_SHA256 = "80295025d0145893f4f63745182042812284434e4e7e5b4388b89d82623c2ead"
PREPARATION_REL = "scripts/iteration41_optional16_r33_root_preparation_r1.py"
PREPARATION_SHA256 = "a626001a9f80bee26996a0fd3effb0e670c96ffd7a167ba154d23521eca64aa4"
V3_REL = "scripts/iteration41_root_held_source_scope_v3.py"
V3_SHA256 = "f3270495d3ddb046f8617d689510d4ae6ee700d639e0db769c518a15099a7677"
V4_REL = "scripts/iteration41_root_held_source_scope_v4.py"
V4_SHA256 = "138c86e21de773822eceac07034e113e0adb5ea5d9056fcc16cee10a75c0e830"
R1_HELPER_REL = "scripts/iteration41_optional16_preparation_source_reconciliation_r1.py"
R1_HELPER_SHA256 = "5277b470a05cf956e29c826c4a8434e7bbd5697d90fb617df6756663cd09e4ba"
R1_HELPER_NAME = "_root_optional16_reconciliation_helper_oct9"
R2_HELPER_REL = "scripts/iteration41_optional16_preparation_source_reconciliation_r2.py"
R2_HELPER_SHA256 = "b3323d01597f180905d9d33ffb86429b7d91104eb950af95544d2a3ac1567efd"
R2_HELPER_NAME = "_root_optional16_reconciliation_r2_helper_oct9"
R3_HELPER_REL = "scripts/iteration41_optional16_preparation_source_reconciliation_r3.py"
R3_HELPER_SHA256 = "769f6af037ee47ae8a0b165f49046cccd0b163f8f3992dd6490ec31ec90332ca"
R3_HELPER_NAME = "_root_optional16_reconciliation_r3_helper_oct9"
PRELOADED_SOURCES = (
    ("scripts/iteration41_optional16_r33_root_held_invoke_r28_r5.py",
     "710452c8358887faa152cd2c6d11333ccf8ecb18fbe64d511ce86eb8f112c99c",
     "_optional16_r33_r5_payload_builder"),
    ("scripts/iteration41_optional16_r33_root_held_invoke_r27.py",
     "ea0a4f9ec5978508b854fe457dd1cfc3c0e9c41b7b23b89ec461bfed4d798339",
     "_optional16_r33_r27_invoke_payload_source"),
    ("scripts/iteration41_optional16_r33_whole_call_supervisor_r27.py",
     "bfdd7bc9530b9ded9722ec86c1c184f36de3fb6337fb6688cbe15fa0f77f2876",
     "_optional16_r33_r27_whole_payload_source"),
)
CALL_MODULE_NAME = "_optional16_r33_root_preparation_call_r1"
DRIVER_MODULE_NAME = "_root_optional16_preparation_driver_oct9"
ENTRY_MODULE_NAME = "_optional16_r33_root_entry_preparation_driver"
V3_MODULE_NAME = "_iteration41_root_held_source_scope_v3_pinned_for_v4"
V4_MODULE_NAME = "_iteration41_optional16_r33_entry_v4"
CUV2_REL = "D:/temp/iteration41-root-public-custody-v2.py"
CUV2_SHA256 = "e856be8e4056835d4a7e54f5c6b449c69ab3f1c2ebb049bcbcc1c95a9ad3f246"
CU_PRIVATE_NAME = "_root_public_custody_private"
CU_CLI_NAME = "_root_public_custody_cli"
CU_PRIVATE_SHA256 = "b866194bdc56d91cc7a6678e83b0af8e4e018ee53a2c136325344c2ee8a5ecfd"
CU_CLI_SHA256 = "62b96a9040d530c8ec592471f0595154fb60239ca03bd6d3b56a6c094dfc7c76"
SOURCE_INDEX_REL = (
    EVIDENCE
    + "iteration41-optional16-r33-root-preparation-driver-source-fake-r1-2026-10-09/"
    + "source-index.json"
)
SOURCE_INDEX_SHA256 = "5d9f43ff4c6e28d87f44e551e062b798c8e02c22cafca5f978d920d3938d9afb"
SUPPORT = {
    EVIDENCE + "iteration41-optional16-r33-root-preparation-driver-source-fake-r1-2026-10-09/source-index.json": SOURCE_INDEX_SHA256,
    EVIDENCE + "iteration41-optional16-r33-root-preparation-driver-source-fake-r1-2026-10-09/README.md": "ac6d32e0d5ea074b8a6d8f741e49e8312ff8adeda14aa6c21aa16d81adb273a8",
    EVIDENCE + "iteration41-optional16-r33-root-preparation-driver-source-fake-r1-2026-10-09/checkpoint.json": "a62ab186aa6ca375d259ac7169ac89ba7f94288891721e8694a9ad39026011b7",
    EVIDENCE + "iteration41-optional16-r33-root-preparation-driver-independent-review-r1-2026-10-09/review.json": "b48e45c950d1bdd65197af01a37db4d5fb2896ef119a265376cda7675f3010c4",
    "backtrader_runtime/certification_roundtrip_private.py": "b866194bdc56d91cc7a6678e83b0af8e4e018ee53a2c136325344c2ee8a5ecfd",
    "backtrader_runtime/certification_binance_roundtrip_r3_cli.py": "62b96a9040d530c8ec592471f0595154fb60239ca03bd6d3b56a6c094dfc7c76",
}
CUV2_ROOT_SOFTWARE_KEY = str(Path(CUV2_REL))
SOFTWARE = {
    "C:/anaconda3/python.exe": "c98caee82c66433f0e89d4abbf152b39a7dc2e99979b28dcb021598b4e3f5642",
    "C:/anaconda3/python311.dll": "162e8557fbed5f39ae24983ee62b2d435b4796c937d9c1a34371888c7e43af00",
    CUV2_ROOT_SOFTWARE_KEY: CUV2_SHA256,
}
EXPECTED_RECEIPT = {
    "schema": "iteration41.optional16.r33.root-preparation-driver.r1",
    "status": "BLOCKED_RETAINED",
    "reason_code": "source_binding_or_preparation_failed",
    "scope_state": "OPEN",
    "authority": "NONE",
    "activation": "NOT_ENTERED",
    "control": "NOT_ENTERED",
    "child": "NOT_ENTERED",
    "worker": "NOT_ENTERED",
    "installer": "NOT_ENTERED",
}
_RETAINED: list[dict[str, object]] = []
_SOURCEFAKE_TOKEN = object()
_MISSING = object()
_MODULE_METADATA = {
    "__name__", "__doc__", "__package__", "__loader__", "__spec__",
    "__file__", "__cached__", "__builtins__",
}
_CLASS_METADATA = {"__dict__", "__weakref__", "__classcell__"}
_ROOT_FUNCTIONS = ("sha", "public_bytes", "load", "all_codes", "bind", "verify", "audit", "run")
_IMMUTABLE = (str, bytes, int, bool, float, complex, type(None))
_OUTER_EXIT_FUNCTION = contextlib._GeneratorContextManager.__exit__
_OUTER_EXIT_CODE = _OUTER_EXIT_FUNCTION.__code__
_OUTER_EXIT_GLOBALS = _OUTER_EXIT_FUNCTION.__globals__


class ReconciliationError(RuntimeError):
    """Finite error code only; never carries a path, handle, or source bytes."""


def _need(condition: object, code: str) -> None:
    if not condition:
        raise ReconciliationError(code)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _key(path: object) -> str:
    return ntpath.normcase(ntpath.normpath(str(path).replace("/", "\\")))


def _code_index(raw: bytes, origin: str) -> dict[str, list[types.CodeType]]:
    try:
        root = compile(raw, origin, "exec", dont_inherit=True)
    except BaseException:
        raise ReconciliationError("source_compile_failed") from None
    result: dict[str, list[types.CodeType]] = {}

    def visit(code: types.CodeType) -> None:
        result.setdefault(code.co_qualname, []).append(code)
        for value in code.co_consts:
            if type(value) is types.CodeType:
                visit(value)

    visit(root)
    return result


def _function_matches(
    actual: object,
    expected: object,
    actual_globals: dict[str, object],
    expected_globals: dict[str, object],
    module_pairs: dict[int, types.ModuleType],
    class_pairs: dict[int, type],
    seen: set[tuple[int, int]],
) -> bool:
    if type(actual) is not types.FunctionType or type(expected) is not types.FunctionType:
        return False
    pair = (id(actual), id(expected))
    if pair in seen:
        return True
    seen.add(pair)
    same_module_globals = (
        actual.__globals__ is actual_globals and expected.__globals__ is expected_globals
    )
    shared_external_globals = actual.__globals__ is expected.__globals__
    if not (same_module_globals or shared_external_globals):
        return False
    if not (
        actual.__code__ == expected.__code__
        and actual.__name__ == expected.__name__
        and actual.__qualname__ == expected.__qualname__
        and actual.__module__ == expected.__module__
        and actual.__defaults__ == expected.__defaults__
        and actual.__kwdefaults__ == expected.__kwdefaults__
        and actual.__annotations__ == expected.__annotations__
    ):
        return False
    actual_closure = actual.__closure__
    expected_closure = expected.__closure__
    if (actual_closure is None) != (expected_closure is None):
        return False
    if actual_closure is not None:
        if expected_closure is None or len(actual_closure) != len(expected_closure):
            return False
        if any(
            not _same_data(a.cell_contents, e.cell_contents, module_pairs, class_pairs, seen)
            for a, e in zip(actual_closure, expected_closure)
        ):
            return False
    if not _same_data(actual.__dict__, expected.__dict__, module_pairs, class_pairs, seen):
        return False
    wrapped_a = getattr(actual, "__wrapped__", _MISSING)
    wrapped_e = getattr(expected, "__wrapped__", _MISSING)
    if (wrapped_a is _MISSING) != (wrapped_e is _MISSING):
        return False
    return wrapped_a is _MISSING or _function_matches(
        wrapped_a, wrapped_e, wrapped_a.__globals__, wrapped_e.__globals__,
        module_pairs, class_pairs, seen,
    )


def _same_data(
    actual: object,
    expected: object,
    module_pairs: dict[int, types.ModuleType],
    class_pairs: dict[int, type],
    seen: set[tuple[int, int]],
) -> bool:
    if actual is expected:
        return True
    if type(expected) in _IMMUTABLE:
        return type(actual) is type(expected) and actual == expected
    if type(expected) is object:
        return type(actual) is object
    if type(expected) is types.ModuleType:
        target = module_pairs.get(id(expected), expected)
        return actual is target
    if isinstance(expected, type):
        return actual is class_pairs.get(id(expected), expected)
    if type(expected) is types.FunctionType:
        expected_globals = expected.__globals__
        actual_globals = actual.__globals__ if type(actual) is types.FunctionType else {}
        return _function_matches(
            actual, expected, actual_globals, expected_globals,
            module_pairs, class_pairs, seen,
        )
    if (type(expected).__module__ == "_ctypes"
            and type(expected).__name__ == "CField"):
        return (
            type(actual) is type(expected)
            and all(getattr(actual, name, _MISSING) == getattr(expected, name, _MISSING)
                    for name in ("name", "offset", "size", "bit_size", "bit_offset"))
        )
    if type(expected) in {types.MemberDescriptorType, types.GetSetDescriptorType}:
        actual_owner = getattr(actual, "__objclass__", None)
        expected_owner = getattr(expected, "__objclass__", None)
        return (
            type(actual) is type(expected)
            and getattr(actual, "__name__", None) == getattr(expected, "__name__", None)
            and actual_owner is class_pairs.get(id(expected_owner), expected_owner)
        )
    if isinstance(expected, PurePath):
        return type(actual) is type(expected) and str(actual) == str(expected)
    if isinstance(expected, re.Pattern):
        return (
            isinstance(actual, re.Pattern)
            and type(actual) is type(expected)
            and actual.pattern == expected.pattern
            and actual.flags == expected.flags
        )
    if type(expected) is tuple:
        return (
            type(actual) is tuple
            and len(actual) == len(expected)
            and all(_same_data(a, e, module_pairs, class_pairs, seen)
                    for a, e in zip(actual, expected))
        )
    if type(expected) is list:
        return (
            type(actual) is list
            and len(actual) == len(expected)
            and all(_same_data(a, e, module_pairs, class_pairs, seen)
                    for a, e in zip(actual, expected))
        )
    if type(expected) is dict:
        return (
            type(actual) is dict
            and set(actual) == set(expected)
            and all(_same_data(actual[k], expected[k], module_pairs, class_pairs, seen)
                    for k in expected)
        )
    if type(expected) is set:
        return type(actual) is set and actual == expected
    if type(expected) is frozenset:
        return type(actual) is frozenset and actual == expected
    if type(expected) is types.MappingProxyType:
        return type(actual) is types.MappingProxyType and actual == expected
    if (type(expected).__module__ == "dataclasses"
            and type(expected).__name__ == "_DataclassParams"):
        names = ("init", "repr", "eq", "order", "unsafe_hash", "frozen",
                 "match_args", "kw_only", "slots")
        return (type(actual) is type(expected)
                and all(getattr(actual, name, _MISSING) == getattr(expected, name, _MISSING)
                        for name in names))
    if (type(expected).__module__ == "dataclasses"
            and type(expected).__name__ == "Field"):
        names = ("name", "type", "default", "default_factory", "init", "repr", "hash",
                 "compare", "metadata", "kw_only", "_field_type")
        return (type(actual) is type(expected)
                and all(_same_data(getattr(actual, name, _MISSING),
                                   getattr(expected, name, _MISSING),
                                   module_pairs, class_pairs, seen)
                        for name in names))
    return False


def _class_matches(
    actual: object,
    expected: type,
    actual_globals: dict[str, object],
    expected_globals: dict[str, object],
    module_pairs: dict[int, types.ModuleType],
    class_pairs: dict[int, type],
    seen_classes: set[int],
    seen_functions: set[tuple[int, int]],
) -> bool:
    if (not isinstance(actual, type) or type(actual) is not type(expected)
            or class_pairs.get(id(expected), actual) is not actual):
        return False
    if id(expected) in seen_classes:
        return True
    seen_classes.add(id(expected))
    if not (
        actual.__module__ == expected.__module__
        and actual.__qualname__ == expected.__qualname__
        and len(actual.__bases__) == len(expected.__bases__)
        and all(_same_data(a, e, module_pairs, class_pairs, seen_functions)
                for a, e in zip(actual.__bases__, expected.__bases__))
    ):
        return False
    actual_values = dict(actual.__dict__)
    expected_values = dict(expected.__dict__)
    actual_keys = set(actual_values) - _CLASS_METADATA
    expected_keys = set(expected_values) - _CLASS_METADATA
    if actual_keys != expected_keys:
        return False
    for name in expected_keys:
        candidate = actual_values[name]
        reference = expected_values[name]
        if type(reference) is types.FunctionType:
            if not _function_matches(
                candidate, reference, actual_globals, expected_globals,
                module_pairs, class_pairs, seen_functions,
            ):
                return False
        elif isinstance(reference, (staticmethod, classmethod)):
            if type(candidate) is not type(reference) or not _function_matches(
                candidate.__func__, reference.__func__, actual_globals, expected_globals,
                module_pairs, class_pairs, seen_functions,
            ):
                return False
        elif isinstance(reference, property):
            if type(candidate) is not property:
                return False
            for candidate_fn, reference_fn in (
                (candidate.fget, reference.fget),
                (candidate.fset, reference.fset),
                (candidate.fdel, reference.fdel),
            ):
                if (candidate_fn is None) != (reference_fn is None):
                    return False
                if reference_fn is not None and not _function_matches(
                    candidate_fn, reference_fn, actual_globals, expected_globals,
                    module_pairs, class_pairs, seen_functions,
                ):
                    return False
            if candidate.__doc__ != reference.__doc__:
                return False
        elif not _same_data(candidate, reference, module_pairs, class_pairs, seen_functions):
            return False
    return True


def _compare_modules(
    actual: types.ModuleType,
    reference: types.ModuleType,
    *,
    allowed_mutable: dict[str, object] | None = None,
    allow_missing_cached: bool = False,
    extra_module_pairs: dict[int, types.ModuleType] | None = None,
    extra_class_pairs: dict[int, type] | None = None,
) -> None:
    allowed_mutable = allowed_mutable or {}
    _need(type(actual) is types.ModuleType, "module_type_invalid")
    for name in ("__name__", "__doc__", "__package__", "__loader__", "__file__"):
        _need(actual.__dict__.get(name, _MISSING) == reference.__dict__.get(name, _MISSING),
              "module_metadata_mismatch")
    _need(actual.__dict__.get("__builtins__") is reference.__dict__.get("__builtins__"),
          "module_builtins_mismatch")
    actual_spec = actual.__dict__.get("__spec__", _MISSING)
    expected_spec = reference.__dict__.get("__spec__", _MISSING)
    if expected_spec is _MISSING or expected_spec is None:
        _need(actual_spec is expected_spec, "module_spec_mismatch")
    else:
        _need(type(actual_spec) is importlib.machinery.ModuleSpec
              and type(expected_spec) is importlib.machinery.ModuleSpec
              and all(getattr(actual_spec, name, _MISSING)
                      == getattr(expected_spec, name, _MISSING)
                      for name in ("name", "origin", "loader", "parent", "has_location", "cached"))
              and actual_spec.submodule_search_locations
              == expected_spec.submodule_search_locations,
              "module_spec_mismatch")
    actual_cached = actual.__dict__.get("__cached__", _MISSING)
    expected_cached = reference.__dict__.get("__cached__", _MISSING)
    _need(
        (allow_missing_cached and actual_cached in (_MISSING, None) and expected_cached is None)
        or (actual_cached is expected_cached),
        "module_cache_metadata_mismatch",
    )
    metadata = _MODULE_METADATA | {"__verified_source_sha256__"}
    _need(
        actual.__dict__.get("__verified_source_sha256__", _MISSING)
        == reference.__dict__.get("__verified_source_sha256__", _MISSING),
        "module_source_pin_metadata_mismatch",
    )
    actual_keys = set(actual.__dict__) - metadata - set(allowed_mutable)
    reference_keys = set(reference.__dict__) - metadata - set(allowed_mutable)
    _need(actual_keys == reference_keys, "module_global_names_mismatch")
    for name, expected in allowed_mutable.items():
        candidate = actual.__dict__.get(name, _MISSING)
        if type(expected) in (dict, list, set, bytearray, types.ModuleType, type):
            matches = candidate is expected
        else:
            matches = type(candidate) is type(expected) and candidate == expected
        _need(matches, "module_mutable_global_identity_mismatch")
    module_pairs = {id(reference): actual, **(extra_module_pairs or {})}
    for expected_name, candidate_name in (("_V3_MODULE", "_V3_MODULE"),):
        expected = reference.__dict__.get(expected_name, _MISSING)
        candidate = actual.__dict__.get(candidate_name, _MISSING)
        if type(expected) is types.ModuleType and type(candidate) is types.ModuleType:
            module_pairs[id(expected)] = candidate
    class_pairs: dict[int, type] = dict(extra_class_pairs or {})
    for name in reference_keys:
        expected = reference.__dict__[name]
        candidate = actual.__dict__[name]
        if isinstance(expected, type) and expected.__module__ == reference.__name__:
            _need(isinstance(candidate, type) and type(candidate) is type(expected),
                  "module_class_missing")
            class_pairs[id(expected)] = candidate
    seen_functions: set[tuple[int, int]] = set()
    seen_classes: set[int] = set()
    for name in reference_keys:
        expected = reference.__dict__[name]
        candidate = actual.__dict__[name]
        if type(expected) is types.FunctionType:
            _need(_function_matches(candidate, expected, actual.__dict__, reference.__dict__,
                                    module_pairs, class_pairs, seen_functions),
                  "module_function_binding_mismatch")
        elif isinstance(expected, type) and expected.__module__ == reference.__name__:
            matched = _class_matches(candidate, expected, actual.__dict__, reference.__dict__,
                                     module_pairs, class_pairs, seen_classes, seen_functions)
            _need(matched, "module_class_binding_mismatch")
        else:
            _need(_same_data(candidate, expected, module_pairs, class_pairs, seen_functions),
                  "module_global_value_mismatch")


def _reference_module(raw: bytes, name: str, origin: str) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__file__ = origin
    try:
        _exec_reference_source(module, raw, origin)
    except BaseException:
        raise ReconciliationError("reference_module_load_failed") from None
    return module


def _exec_reference_source(module: types.ModuleType, raw: bytes, origin: str) -> None:
    """Compile a temporary source reference with its normal module-name context."""
    name = module.__name__
    prior = sys.modules.get(name, _MISSING)
    sys.modules[name] = module
    try:
        exec(compile(raw, origin, "exec", dont_inherit=True), module.__dict__, module.__dict__)
    finally:
        if prior is _MISSING:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = prior


def _pinned_loader_reference(raw: bytes, name: str, origin: str, digest: str) -> types.ModuleType:
    """Mirror the exact metadata convention of the pinned Root module loader."""
    module = types.ModuleType(name)
    module.__file__ = origin
    module.__package__ = ""
    module.__loader__ = None
    module.__cached__ = None
    module.__spec__ = importlib.machinery.ModuleSpec(name, loader=None, origin=origin)
    module.__verified_source_sha256__ = digest
    try:
        _exec_reference_source(module, raw, origin)
    except BaseException:
        raise ReconciliationError("reference_module_load_failed") from None
    return module


def _module_code_bound(
    module: types.ModuleType,
    raw: bytes,
    origin: str,
) -> None:
    pinned_digests = {
        DRIVER_SHA256, CALL_SHA256, ENTRY_SHA256, V3_SHA256, V4_SHA256,
        CUV2_SHA256, R1_HELPER_SHA256, R2_HELPER_SHA256, R3_HELPER_SHA256,
    }
    pinned_digests.update(item[1] for item in PRELOADED_SOURCES)
    pinned_digests.update({CU_PRIVATE_SHA256, CU_CLI_SHA256})
    _need(_sha(raw) in pinned_digests,
          "module_source_not_pinned")
    codes = _code_index(raw, origin)
    for owner in (module, *tuple(value for value in vars(module).values()
                                 if isinstance(value, type) and value.__module__ == module.__name__)):
        for name, value in tuple(vars(owner).items()):
            if isinstance(value, (staticmethod, classmethod)):
                value = value.__func__
            if type(value) is not types.FunctionType or value.__module__ != module.__name__:
                continue
            unwrapped = inspect.unwrap(value)
            _need(unwrapped.__globals__ is module.__dict__, "module_function_globals_changed")
            if (owner is not module and getattr(owner, "__dataclass_fields__", None) is not None
                    and unwrapped.__code__.co_filename == "<string>"):
                # dataclasses generates these methods at import time; their
                # exact code and class fields are checked by _compare_modules.
                continue
            _need(unwrapped.__code__.co_filename == origin, "module_function_origin_changed")
            candidates = codes.get(unwrapped.__code__.co_qualname, ())
            _need(any(unwrapped.__code__ == candidate for candidate in candidates),
                  "module_function_code_changed")


def _root_namespace_origin(root_ns: dict[str, object], origin: str,
                           *, sourcefake: bool) -> None:
    _need(type(root_ns) is dict and _key(origin) == _key(ROOT / ROOT_RUNNER_REL),
          "root_namespace_origin_invalid")
    _need("__file__" not in root_ns, "root_runner_path_changed")
    _need(root_ns.get("__name__") == "__main__", "root_interactive_main_name_invalid")
    runtime_sys = root_ns.get("sys")
    if not sourcefake:
        _need(runtime_sys is sys, "root_interactive_sys_module_invalid")
    _need(type(getattr(runtime_sys, "modules", None)) is dict,
          "root_interactive_module_registry_invalid")
    main_module = runtime_sys.modules.get("__main__")
    _need(type(main_module) is types.ModuleType and main_module.__dict__ is root_ns,
          "root_interactive_main_binding_invalid")
    argv = getattr(runtime_sys, "argv", None)
    _need(type(argv) is list and len(argv) == 1 and type(argv[0]) is str
          and argv[0] == ROOT_RUNNER_ARGV0
          and _key(ROOT / argv[0]) == _key(origin),
          "root_interactive_argv_origin_invalid")
    flags = getattr(runtime_sys, "flags", None)
    _need(flags is not None and all(type(getattr(flags, name, None)) is int
                                    and getattr(flags, name) == 1
                                    for name in ("isolated", "no_site", "interactive", "utf8_mode")),
          "root_interactive_flags_invalid")
    _need(getattr(runtime_sys, "dont_write_bytecode", None) is True,
          "root_interactive_bytecode_flag_invalid")
    try:
        version = tuple(runtime_sys.version_info[:3])
    except BaseException:
        version = ()
    _need(version == ROOT_SYS_VERSION, "root_interactive_version_invalid")
    _need(type(getattr(runtime_sys, "executable", None)) is str
          and _key(runtime_sys.executable) == _key(ROOT_SYS_EXECUTABLE),
          "root_interactive_executable_invalid")
    _need(_key(str(Path.cwd())) == _key(ROOT), "root_interactive_cwd_invalid")


def _root_source_functions(root_ns: dict[str, object], raw: bytes, origin: str,
                           *, sourcefake: bool) -> None:
    _root_namespace_origin(root_ns, origin, sourcefake=sourcefake)
    codes = _code_index(raw, origin)
    for name in _ROOT_FUNCTIONS:
        candidate = root_ns.get(name)
        _need(type(candidate) is types.FunctionType, "root_function_missing")
        _need(candidate.__globals__ is root_ns
              and candidate.__name__ == name
              and candidate.__qualname__ == name
              and candidate.__module__ == root_ns.get("__name__")
              and candidate.__defaults__ is None
              and candidate.__kwdefaults__ is None
              and candidate.__closure__ is None
              and candidate.__annotations__ == {}
              and candidate.__dict__ == {},
              "root_function_globals_or_metadata_changed")
        _need(candidate.__code__.co_filename == origin, "root_function_origin_changed")
        expected = codes.get(name, ())
        _need(any(candidate.__code__ == code for code in expected), "root_function_code_changed")


def _source_index_pins(raw: bytes) -> dict[str, str]:
    _need(type(raw) is bytes and _sha(raw) == SOURCE_INDEX_SHA256,
          "root_source_index_pin_mismatch")
    try:
        index = json.loads(raw.decode("utf-8", "strict"))
    except BaseException:
        raise ReconciliationError("root_source_index_invalid") from None
    rows = index.get("candidate_sources", []) + index.get("fixed_dependencies", [])
    _need(type(rows) is list and len(rows) == 35, "root_source_index_count_mismatch")
    pins: dict[str, str] = {}
    for row in rows:
        _need(type(row) is dict, "root_source_index_row_invalid")
        path = row.get("path")
        digest = row.get("sha256")
        _need(type(path) is str and type(digest) is str and len(digest) == 64,
              "root_source_index_row_invalid")
        _need(path not in pins, "root_source_index_duplicate")
        pins[path] = digest
    return pins


def _exact_outer_maps(root_ns: dict[str, object], raw_map: dict[str, bytes], frame_locals: dict[str, object], *, sourcefake: bool) -> None:
    pins = frame_locals.get("pins")
    software = frame_locals.get("software_pins")
    _need(type(pins) is dict and type(software) is dict, "outer_pin_maps_invalid")
    sourcefake_full_maps = sourcefake and len(pins) == 42 and len(software) == 3
    if sourcefake:
        _need(type(pins) is dict and len(pins) >= 1
              and type(software) is dict and len(software) in (0, 3),
              "sourcefake_outer_map_invalid")
    if not sourcefake or sourcefake_full_maps:
        _need(root_ns.get("ROOT") == ROOT, "root_source_root_changed")
        _need(root_ns.get("E") == EVIDENCE, "root_source_evidence_changed")
        _need(root_ns.get("P") == EVIDENCE + "iteration41-optional16-r33-root-preparation-driver-source-fake-r1-2026-10-09/",
              "root_source_packet_changed")
        _need(root_ns.get("DRIVER") == DRIVER_REL, "root_driver_path_changed")
        _need(root_ns.get("CU_SHA") == CUV2_SHA256, "root_cuv2_pin_changed")
        _need(type(root_ns.get("CU")) is type(Path(CUV2_REL))
              and str(root_ns["CU"]) == CUV2_ROOT_SOFTWARE_KEY,
              "root_cuv2_software_path_construction_changed")
        _need(root_ns.get("SUPPORT") == SUPPORT and root_ns.get("SOFTWARE") == SOFTWARE,
              "root_fixed_maps_changed")
        source_index_key = _key(ROOT / SOURCE_INDEX_REL)
        source_index_raw = None
        for key, value in raw_map.items():
            if _key(key) == source_index_key:
                source_index_raw = value
                break
        _need(type(source_index_raw) is bytes, "root_source_index_missing")
        expected = _source_index_pins(source_index_raw)
        expected.update(SUPPORT)
        root_path = ROOT / ROOT_RUNNER_REL
        expected[ROOT_RUNNER_REL] = ROOT_RUNNER_SHA256
        _need(len(expected) == 42, "outer_public_expected_count_mismatch")
        _need(pins == expected and software == SOFTWARE, "outer_pin_maps_mismatch")
    all_pins = frame_locals.get("all_pins")
    identities = frame_locals.get("identities")
    _need(type(all_pins) is dict and type(identities) is dict, "outer_lease_maps_invalid")
    expected_keys = {_key(ROOT / path) for path in pins}
    expected_keys.update(_key(path) for path in software)
    _need(len(expected_keys) == len(pins) + len(software), "outer_pin_path_collision")
    _need({_key(path) for path in all_pins} == expected_keys, "outer_all_pin_paths_changed")
    _need({_key(path) for path in identities} == expected_keys, "outer_identity_paths_changed")
    _need({_key(path) for path in raw_map} == expected_keys, "outer_raw_path_set_changed")
    expected_all = {_key(ROOT / path): digest for path, digest in pins.items()}
    expected_all.update({_key(path): digest for path, digest in software.items()})
    observed_all = {_key(path): digest for path, digest in all_pins.items()}
    _need(observed_all == expected_all, "outer_all_pin_values_changed")
    if not sourcefake or sourcefake_full_maps:
        _need(len(pins) == 42 and len(software) == 3 and len(expected_keys) == 45,
              "outer_pin_count_mismatch")
    for path, digest in pins.items():
        _need(type(path) is str and type(digest) is str and len(digest) == 64,
              "outer_public_pin_row_invalid")
    for path, digest in software.items():
        _need(type(path) is str and type(digest) is str and len(digest) == 64,
              "outer_software_pin_row_invalid")
    for pin_map, root_relative, failure_code in (
        (pins, True, "outer_public_raw_source_changed"),
        (software, False, "outer_software_raw_source_changed"),
    ):
        if sourcefake_full_maps and not root_relative:
            # The sourcefake fixture carries opaque placeholders for the two
            # interpreter rows. It checks exact pinned metadata and key sets,
            # while deliberately never reading or hashing software bodies.
            for path in pin_map:
                raw = next((value for key, value in raw_map.items()
                            if _key(key) == _key(path)), None)
                _need(type(raw) is bytes, failure_code)
            continue
        for path, digest in pin_map.items():
            target = ROOT / path if root_relative else path
            raw = next((value for key, value in raw_map.items()
                        if _key(key) == _key(target)), None)
            _need(type(raw) is bytes and _sha(raw) == digest, failure_code)


def _check_root_globals(root_ns: dict[str, object], state: dict[str, object], result: dict[str, object], *, sourcefake: bool) -> None:
    _need(root_ns.get("PREP_STATE") is state, "root_state_replaced")
    _need(root_ns.get("PREP_RESULT") is result, "root_result_replaced")
    _need(type(state) is dict, "root_state_invalid")
    _need(state.get("outer") is not None and state.get("held") is not None
          and state.get("driver") is not None, "root_state_incomplete")
    _root_namespace_origin(root_ns, str(ROOT / ROOT_RUNNER_REL), sourcefake=sourcefake)
    if not sourcefake:
        _need(set(state) == {"outer", "held", "driver", "bindings"}, "root_state_keys_changed")
        _need(root_ns.get("PREP_EXEC") is not None and str(ROOT / DRIVER_REL) in root_ns["PREP_EXEC"],
              "root_driver_execution_not_recorded")
        _need(root_ns.get("hashlib") is hashlib and root_ns.get("inspect") is inspect
              and root_ns.get("json") is json and root_ns.get("Path") is Path
              and root_ns.get("stat") is stat and root_ns.get("sys") is sys
              and root_ns.get("time") is time and root_ns.get("types") is types,
              "root_import_binding_changed")
    _need(type(result) is dict, "root_result_invalid")
    _need(result.get("schema") == "iteration41.optional16.preparation.root_actual.v1"
          and result.get("status") == "BLOCKED"
          and result.get("reason") == "source_binding_or_preparation_failed"
          and result.get("preparation_invocations") == 1
          and result.get("retained_attempts") == 1
          and result.get("public_outer_pin_count") == 42
          and result.get("software_outer_pin_count") == 3
          and result.get("outer_normal_postverify_and_close") is False
          and result.get("host_exit_permitted") is False
          and result.get("activation") is False
          and result.get("provider_call") is False
          and result.get("formal_optional16_pass_count") == 0,
          "root_result_projection_mismatch")
    receipt = result.get("receipt")
    _need(type(receipt) is dict and all(receipt.get(key) == value
                                        for key, value in EXPECTED_RECEIPT.items()),
          "root_receipt_projection_mismatch")


def _verify_outer_context(outer: object, held: object, cu_source: bytes,
                          root_ns: dict[str, object], *, sourcefake: bool):
    _need(type(outer) is contextlib._GeneratorContextManager, "outer_manager_type_invalid")
    _need(set(vars(outer)) == {"gen", "__doc__"}
          and outer.__doc__ == "Helper for @contextmanager decorator.",
          "outer_manager_instance_state_changed")
    _need(type(held) is tuple and len(held) == 3, "outer_yield_shape_invalid")
    gen = outer.gen
    frame = gen.gi_frame
    _need(frame is not None and gen.gi_running is False and gen.gi_suspended is True,
          "outer_generator_not_suspended")
    cu_globals = frame.f_globals
    held_fn = cu_globals.get("held_public_sources")
    _need(type(held_fn) is types.FunctionType, "cuv2_hold_function_missing")
    original = inspect.unwrap(held_fn)
    _need(type(original) is types.FunctionType and original.__globals__ is cu_globals,
          "cuv2_hold_globals_changed")
    _need(_sha(cu_source) == CUV2_SHA256 and gen.gi_code == original.__code__
          and frame.f_code == original.__code__, "cuv2_generator_source_mismatch")
    _need(_key(original.__code__.co_filename) == _key(CUV2_REL),
          "cuv2_generator_origin_mismatch")
    cu_origin = cu_globals.get("__file__")
    _need(type(cu_origin) is str and _key(cu_origin) == _key(CUV2_REL),
          "cuv2_module_origin_mismatch")
    local = frame.f_locals
    raw_map = local.get("raw_bytes")
    _need(type(raw_map) is dict and held[2] is raw_map, "outer_raw_map_identity_changed")
    _need(held[0] is local.get("private") and held[1] is local.get("cli"),
          "outer_yield_references_changed")
    _exact_outer_maps(root_ns, raw_map, local, sourcefake=sourcefake)
    # The manager method is the standard CPython contextlib normal-exit API.
    # We can bind its current code and guard it against changes during this
    # reconciliation; the original caller did not separately retain a
    # pre-call bound-method reference, so this is not a historical identity
    # claim.
    _need("__exit__" not in vars(outer), "outer_instance_exit_shadowed")
    exit_method = outer.__exit__
    exit_function = type(outer).__exit__
    _need(exit_method.__self__ is outer and exit_method.__func__ is exit_function
          and exit_function is _OUTER_EXIT_FUNCTION
          and exit_function.__code__ is _OUTER_EXIT_CODE
          and exit_function.__globals__ is _OUTER_EXIT_GLOBALS
          and exit_function.__module__ == "contextlib"
          and exit_function.__qualname__ == "_GeneratorContextManager.__exit__"
          and exit_function.__globals__ is contextlib.__dict__,
          "outer_normal_exit_binding_invalid")
    _need(outer.gen is gen and gen.gi_frame is frame,
          "outer_generator_identity_changed_during_binding")
    return cu_globals, original, frame, gen, exit_method, exit_function, raw_map, cu_origin


def _outer_exit_target_matches(outer: object, retained: dict[str, object]) -> bool:
    gen = retained.get("outer_gen")
    frame = retained.get("outer_frame")
    exit_method = retained.get("outer_exit_method")
    exit_function = retained.get("outer_exit_function")
    try:
        current_method = outer.__exit__
        return (
            outer.gen is gen
            and type(gen) is types.GeneratorType
            and gen.gi_frame is frame
            and frame is not None
            and type(exit_method) is types.MethodType
            and exit_method.__self__ is outer
            and exit_method.__func__ is exit_function
            and current_method.__self__ is outer
            and current_method.__func__ is exit_function
            and type(outer).__exit__ is exit_function
            and exit_function.__code__ is retained.get("outer_exit_code")
            and exit_function.__globals__ is retained.get("outer_exit_globals")
        )
    except BaseException:
        return False


def _bind_cuv2_loaded_helpers(cuv2: types.ModuleType, held: tuple[object, ...],
                              raw_map: dict[str, bytes], *, sourcefake: bool) -> None:
    private, cli = held[0], held[1]
    if sourcefake:
        _need(not isinstance(private, types.ModuleType)
              and not isinstance(cli, types.ModuleType), "sourcefake_cuv2_helpers_invalid")
        return
    for module, relative, digest, name in (
        (private, cuv2.PRIVATE, cuv2.PRIVATE_SHA, CU_PRIVATE_NAME),
        (cli, cuv2.CLI, cuv2.CLI_SHA, CU_CLI_NAME),
    ):
        origin = str(cuv2.ROOT / relative)
        _simple_module_source(module, _module_raw(raw_map, origin), name,
                              origin, digest,
                              allowed_mutable={"_API": private._API}
                              if module is private else None)
    _need(private._API is not None and type(private._API) is private._Win32,
          "cuv2_private_api_binding_invalid")


def _simple_module_source(
    actual: object,
    raw: bytes,
    name: str,
    origin: str,
    digest: str,
    *,
    allow_missing_cached: bool = False,
    allowed_mutable: dict[str, object] | None = None,
    sourcefake: bool = False,
    sourcefake_cuv2: bool = False,
) -> tuple[types.ModuleType, bytes]:
    selected = raw
    _need(type(selected) is bytes and _sha(selected) == digest,
          "outer_held_source_missing_or_changed")
    candidate = actual
    if sourcefake and sourcefake_cuv2:
        # Sourcefake replaces only the filesystem leaves in the CUV2 module;
        # generator code, frame globals, and yielded references remain real.
        allowed_mutable = {
            **(allowed_mutable or {}),
            "Path": candidate.__dict__["Path"],
            "ROOT": candidate.__dict__["ROOT"],
            "load": candidate.__dict__["load"],
        }
    _module_code_bound(candidate, selected, origin)
    if name in {CALL_MODULE_NAME, ENTRY_MODULE_NAME,
                *(item[2] for item in PRELOADED_SOURCES)}:
        reference = _pinned_loader_reference(selected, name, origin, digest)
    else:
        reference = _reference_module(selected, name, origin)
    if allowed_mutable:
        for key, value in allowed_mutable.items():
            reference.__dict__[key] = value
    _compare_modules(candidate, reference, allowed_mutable=allowed_mutable,
                     allow_missing_cached=allow_missing_cached)
    return candidate, selected


def _bind_v3_v4(call_module: types.ModuleType, v4: types.ModuleType,
                source_map: dict[str, bytes], scope: object,
                root_namespace: dict[str, object]) -> tuple[types.ModuleType, types.ModuleType]:
    v3_raw = source_map.get("v3")
    v4_raw = source_map.get("v4")
    _need(type(v3_raw) is bytes and _sha(v3_raw) == V3_SHA256
          and type(v4_raw) is bytes and _sha(v4_raw) == V4_SHA256,
          "inner_module_bytes_invalid")
    # Bind Call R1 itself to its exact held source before using its pinned
    # isolated reference builders and comparison primitives.
    _module_code_bound(call_module, _RETAINED[-1]["call_raw"], str(ROOT / CALL_REL))
    v3 = getattr(v4, "_V3_MODULE", None)
    _need(type(v3) is types.ModuleType and v4.__dict__.get("_V3_MODULE") is v3,
          "nested_v3_module_identity_invalid")
    _need(sys.modules.get(V3_MODULE_NAME) is v3,
          "nested_v3_module_alias_invalid")
    root_sys = root_namespace.get("sys")
    root_modules = getattr(root_sys, "modules", None)
    _need(type(root_modules) is dict and root_modules.get(V3_MODULE_NAME) is v3,
          "root_nested_v3_module_alias_invalid")
    v3_ref = call_module._make_module(V3_MODULE_NAME, Path(V3_REL), v3_raw, V3_SHA256)
    _need(type(v3._RETAINED_SCOPES) is list
          and len(v3._RETAINED_SCOPES) == 1
          and v3._RETAINED_SCOPES[0] is scope
          and type(v3_ref._RETAINED_SCOPES) is list
          and not v3_ref._RETAINED_SCOPES,
          "inner_retained_scope_identity_mismatch")
    v3_ref._RETAINED_SCOPES[:] = [scope]
    _module_code_bound(v3, v3_raw, str(ROOT / V3_REL))
    _compare_modules(v3, v3_ref, allow_missing_cached=True)
    # The original V4 loader resolves V3 through its canonical sys.modules
    # alias. Temporarily point that exact alias at the independently compiled
    # V3 reference, then execute the unchanged V4 bytes through the pinned
    # loader. Root's audit hook accepts this code because its canonical
    # filename and code object match the held source exactly.
    prior_sys_v3 = sys.modules.get(V3_MODULE_NAME, _MISSING)
    prior_root_v3 = root_modules.get(V3_MODULE_NAME, _MISSING)
    _need(prior_sys_v3 is v3 and prior_root_v3 is v3,
          "nested_v3_alias_changed_before_reference_load")
    try:
        sys.modules[V3_MODULE_NAME] = v3_ref
        if root_modules is not sys.modules:
            root_modules[V3_MODULE_NAME] = v3_ref
        v4_ref = call_module._make_module(V4_MODULE_NAME, Path(V4_REL), v4_raw, V4_SHA256)
    finally:
        if prior_sys_v3 is _MISSING:
            sys.modules.pop(V3_MODULE_NAME, None)
        else:
            sys.modules[V3_MODULE_NAME] = prior_sys_v3
        if root_modules is not sys.modules:
            if prior_root_v3 is _MISSING:
                root_modules.pop(V3_MODULE_NAME, None)
            else:
                root_modules[V3_MODULE_NAME] = prior_root_v3
    _need(sys.modules.get(V3_MODULE_NAME) is v3
          and root_modules.get(V3_MODULE_NAME) is v3
          and v4_ref.__dict__.get("_V3_MODULE") is v3_ref,
          "nested_v3_alias_not_restored_or_reference_not_consumed")
    _need(type(v3.__dict__.get("_RETAINED_SCOPES")) is list
          and len(v3._RETAINED_SCOPES) == 1
          and v3._RETAINED_SCOPES[0] is scope,
          "inner_retained_scope_identity_mismatch")
    _need(v4_ref.RootHeldScopeV4.__bases__ == (v3_ref.RootHeldScopeV3,)
          and v4.RootHeldScopeV4.__bases__ == (v3.RootHeldScopeV3,),
          "v4_v3_base_identity_mismatch")
    _need(v3.__name__ == V3_MODULE_NAME and v4.__name__ == V4_MODULE_NAME
          and v3.__file__ == str(ROOT / V3_REL)
          and v4.__file__ == str(ROOT / V4_REL), "inner_module_metadata_mismatch")
    _need(v3.__dict__.get("__verified_source_sha256__") == V3_SHA256
          and v4.__dict__.get("__verified_source_sha256__") == V4_SHA256,
          "inner_module_pin_metadata_mismatch")
    _need(v3.__dict__.get("__cached__", None) is None
          and v4.__dict__.get("__cached__", None) is None,
          "inner_cached_slot_invalid")
    _module_code_bound(v3, v3_raw, str(ROOT / V3_REL))
    _module_code_bound(v4, v4_raw, str(ROOT / V4_REL))
    class_pairs: dict[int, type] = {}
    for actual, reference in ((v3, v3_ref), (v4, v4_ref)):
        for name, expected in reference.__dict__.items():
            if isinstance(expected, type) and expected.__module__ == reference.__name__:
                candidate = actual.__dict__.get(name, _MISSING)
                _need(type(candidate) is type, "inner_module_class_missing")
                class_pairs[id(expected)] = candidate
    module_pairs = {id(v3_ref): v3, id(v4_ref): v4}
    _compare_modules(v3, v3_ref, allow_missing_cached=True,
                     extra_module_pairs={id(v4_ref): v4},
                     extra_class_pairs=class_pairs)
    _compare_modules(v4, v4_ref, allow_missing_cached=True,
                     extra_module_pairs={id(v3_ref): v3},
                     extra_class_pairs=class_pairs)
    return v3, v4


def _scope_rows(scope: object, v4: types.ModuleType, *, sourcefake: bool) -> None:
    _need(type(scope) is v4.RootHeldScopeV4, "inner_scope_type_invalid")
    _need(not (set(vars(scope)) & {
        "release", "postverify", "read_held", "verify_pin", "manifest",
        "public_map", "software_map", "support_map", "_read_row_handle",
    }), "inner_scope_method_shadowed")
    _need(scope.state == "OPEN" and scope._failure is None
          and scope._postverified is False
          and scope._owner == threading.get_ident(), "inner_scope_state_invalid")
    _need(scope._proofs == {} and scope._lending is False
          and v4._RETAINED_LENDING == [], "inner_profiler_or_lending_state_changed")
    if sourcefake:
        _need(scope.test_only is True, "sourcefake_scope_not_test_only")
        _need(type(scope.public_map) is dict and len(scope.public_map) >= 2
              and scope.software_map == {} and scope.support_map == {},
              "sourcefake_scope_rows_invalid")
    else:
        _need(scope.test_only is False, "production_scope_test_only")
        manifest = scope.manifest()
        public = scope.public_map
        _need(type(manifest) is dict and type(public) is dict
              and len(manifest) == 457 and public == manifest
              and scope.software_map == {} and scope.support_map == {},
              "inner_public_scope_count_or_origin_mismatch")


def _read_module_sources(scope: object, module_sources: dict[str, bytes]) -> None:
    for label, relative, digest in (("v3", V3_REL, V3_SHA256), ("v4", V4_REL, V4_SHA256)):
        observed = scope.read_held(ROOT / relative, digest, 256 * 1024)
        _need(type(observed) is bytes and observed == module_sources[label],
              "inner_same_handle_source_mismatch")


def _snapshot_json(value: object) -> object:
    if value is None or type(value) in (bool, str, int):
        return (type(value).__name__, value)
    if type(value) is list:
        return ("list", tuple(_snapshot_json(item) for item in value))
    if type(value) is tuple:
        return ("tuple", tuple(_snapshot_json(item) for item in value))
    if type(value) is dict:
        _need(all(type(key) is str for key in value), "result_key_invalid")
        return ("dict", tuple((key, _snapshot_json(value[key])) for key in sorted(value)))
    raise ReconciliationError("result_projection_not_finite")


def _freeze_helper_state(value: object) -> object:
    """Mirror the R3 caller's finite function/global snapshot encoding."""
    if type(value) in (str, bytes, int, bool, float, complex, type(None)):
        return (type(value), value)
    if type(value) in (tuple, list):
        return (type(value), tuple(_freeze_helper_state(item) for item in value))
    if type(value) is dict:
        return (dict, tuple(
            (_freeze_helper_state(key), _freeze_helper_state(item))
            for key, item in value.items()
        ))
    if type(value) in (set, frozenset):
        return (type(value), frozenset(_freeze_helper_state(item) for item in value))
    return (type(value), id(value))


def _helper_function_state(function: types.FunctionType) -> tuple[object, ...]:
    closure = function.__closure__ or ()
    return (
        function, function.__code__, function.__globals__, function.__module__,
        function.__name__, function.__qualname__,
        _freeze_helper_state(function.__defaults__),
        _freeze_helper_state(function.__kwdefaults__),
        _freeze_helper_state(function.__annotations__),
        _freeze_helper_state(function.__dict__), function.__closure__,
        tuple(_freeze_helper_state(cell.cell_contents) for cell in closure),
    )


def _verify_r3_helper_binding(
    module: types.ModuleType,
    binding: tuple[object, ...],
    registry: list[object],
) -> None:
    function_rows = tuple(
        (name, _helper_function_state(value))
        for name, value in module.__dict__.items()
        if type(value) is types.FunctionType and value.__module__ == module.__name__
    )
    global_state = {
        key: _freeze_helper_state(value)
        for key, value in module.__dict__.items() if key != "_RETAINED"
    }
    _need(len(binding) == 3 and binding[0] == function_rows
          and binding[1] == global_state and binding[2] is registry,
          "r3_helper_captured_binding_changed")


def _check_result_unchanged(root_ns: dict[str, object], state: dict[str, object],
                            result: dict[str, object], snapshot: object) -> None:
    _need(root_ns.get("PREP_STATE") is state and root_ns.get("PREP_RESULT") is result,
          "root_reference_changed_during_reconciliation")
    _need(_snapshot_json(result) == snapshot, "root_result_changed_during_reconciliation")


def _receipt(status: str, phase: str, *, inner_released: bool = False,
             outer_closed: bool = False, reason: str | None = None,
             physical_file_lease_state: str = "UNKNOWN",
             r1_registry_preserved: bool = False,
             r2_registry_preserved: bool = False,
             r3_registry_preserved: bool = False) -> dict[str, object]:
    return {
        "schema": SCHEMA,
        "status": status,
        "reason_code": reason,
        "phase": phase,
        "inner_release": inner_released,
        "outer_normal_exit": outer_closed,
        "formal_optional16_pass_count": 0,
        "authority": "NONE",
        "activation": "NOT_ENTERED",
        "installer": "NOT_ENTERED",
        "worker": "NOT_ENTERED",
        "provider_call": "NOT_ENTERED",
        "original_result_mutated": False,
        "original_result_identity_claim": "SAME_ROOT_SUPPLIED_REFERENCE_DURING_THIS_CALL_ONLY",
        "historical_run_assignment_identity_proven": False,
        "r1_registry_preserved": r1_registry_preserved,
        "r1_retry": "NOT_ENTERED",
        "r2_registry_preserved": r2_registry_preserved,
        "r2_retry": "NOT_ENTERED",
        "r3_registry_preserved": r3_registry_preserved,
        "r3_retry": "NOT_ENTERED",
        "opaque_payload_read_by_component": False,
        "physical_file_lease_state": physical_file_lease_state,
    }


def _check_r1_record(r1_module: types.ModuleType, r1_registry: list[object],
                     r1_record: dict[str, object], root_namespace: dict[str, object],
                     root_state: dict[str, object], original_result: dict[str, object]) -> None:
    _need(r1_module.__dict__.get("_RETAINED") is r1_registry
          and type(r1_registry) is list and len(r1_registry) == 1
          and r1_registry[0] is r1_record,
          "r1_registry_identity_or_count_changed")
    _need(set(r1_record) == {
        "root_namespace", "root_state", "root_result", "phase", "exit_started",
    }
          and r1_record.get("root_namespace") is root_namespace
          and r1_record.get("root_state") is root_state
          and r1_record.get("root_result") is original_result
          and r1_record.get("phase") == "source_binding_blocked"
          and r1_record.get("exit_started") is False,
          "r1_blocked_record_changed")


def _verify_prior_r1_reconciliation(
    r1_module: object,
    r1_registry: object,
    r1_raw: object,
    root_namespace: dict[str, object],
    root_state: dict[str, object],
    original_result: dict[str, object],
) -> dict[str, object]:
    _need(type(r1_module) is types.ModuleType and r1_module.__name__ == R1_HELPER_NAME,
          "r1_helper_module_identity_invalid")
    root_sys = root_namespace.get("sys")
    root_modules = getattr(root_sys, "modules", None)
    _need(type(root_modules) is dict
          and root_modules.get(R1_HELPER_NAME) is r1_module,
          "r1_helper_not_bound_at_root_module_slot")
    _need(type(r1_raw) is bytes and _sha(r1_raw) == R1_HELPER_SHA256,
          "r1_helper_source_pin_invalid")
    r1_origin = r1_module.__dict__.get("__file__")
    _need(type(r1_origin) is str and _key(r1_origin) == _key(ROOT / R1_HELPER_REL),
          "r1_helper_origin_invalid")
    _need(type(r1_registry) is list and r1_module.__dict__.get("_RETAINED") is r1_registry,
          "r1_registry_not_prebound_module_state")
    _simple_module_source(
        r1_module, r1_raw, R1_HELPER_NAME, r1_origin, R1_HELPER_SHA256,
        allowed_mutable={"_RETAINED": r1_registry},
    )
    _need(len(r1_registry) == 1 and type(r1_registry[0]) is dict,
          "r1_registry_count_or_record_invalid")
    record = r1_registry[0]
    _check_r1_record(r1_module, r1_registry, record,
                     root_namespace, root_state, original_result)
    return record


_R2_RETAINED_KEYS = {
    "attempt", "call_module", "call_raw", "call_record", "cuv2_globals",
    "driver", "entry", "exit_started", "held", "module_sources", "outer",
    "outer_frame", "outer_gen", "phase", "prep_raw", "r1_module", "r1_raw",
    "r1_record", "r1_registry", "result_snapshot", "root_namespace",
    "root_result", "root_state", "scope", "v3_raw", "v4", "v4_raw",
}


def _check_r2_record(
    r2_module: types.ModuleType,
    r2_registry: list[object],
    r2_record: dict[str, object],
    r2_held: tuple[object, ...],
    r2_raw: bytes,
    root_namespace: dict[str, object],
    root_state: dict[str, object],
    original_result: dict[str, object],
    r1_module: types.ModuleType,
    r1_registry: list[object],
    r1_record: dict[str, object],
    r1_raw: bytes,
    *,
    outer_closed: bool = False,
    captured_outer_frame: object | None = None,
) -> None:
    root_sys = root_namespace.get("sys")
    root_modules = getattr(root_sys, "modules", None)
    _need(type(r2_module) is types.ModuleType and r2_module.__name__ == R2_HELPER_NAME
          and type(root_modules) is dict
          and root_modules.get(R2_HELPER_NAME) is r2_module,
          "r2_helper_module_alias_changed")
    _need(type(r2_registry) is list and r2_module.__dict__.get("_RETAINED") is r2_registry
          and len(r2_registry) == 1 and r2_registry[0] is r2_record
          and type(r2_record) is dict and set(r2_record) == _R2_RETAINED_KEYS,
          "r2_registry_or_record_changed")
    _need(type(r2_held) is tuple and len(r2_held) == 3
          and type(r2_held[2]) is dict,
          "r2_source_review_hold_shape_invalid")
    held_r2_raw = _module_raw(r2_held[2], str(ROOT / R2_HELPER_REL))
    _need(type(r2_raw) is bytes and held_r2_raw is r2_raw
          and _sha(r2_raw) == R2_HELPER_SHA256,
          "r2_helper_source_reference_changed")
    r2_origin = r2_module.__dict__.get("__file__")
    _need(type(r2_origin) is str and _key(r2_origin) == _key(ROOT / R2_HELPER_REL),
          "r2_helper_origin_changed")
    _simple_module_source(
        r2_module, r2_raw, R2_HELPER_NAME, r2_origin, R2_HELPER_SHA256,
        allowed_mutable={"_RETAINED": r2_registry},
    )

    driver = root_state.get("driver")
    outer = root_state.get("outer")
    held = root_state.get("held")
    _need(type(driver) is types.ModuleType
          and type(driver._RETAINED_ATTEMPTS) is list
          and len(driver._RETAINED_ATTEMPTS) == 1,
          "r2_driver_attempt_binding_changed")
    attempt = driver._RETAINED_ATTEMPTS[0]
    _need(type(attempt) is tuple and len(attempt) == 10
          and r2_record.get("attempt") is attempt,
          "r2_attempt_reference_changed")
    (entry, v4, _payload_raw, _preloaded, scope, call_module,
     prep_raw, call_raw, v3_raw, v4_raw) = attempt
    _need(type(call_module) is types.ModuleType
          and type(call_module._RETAINED) is list
          and len(call_module._RETAINED) == 1,
          "r2_call_registry_changed")
    call_record = call_module._RETAINED[0]
    _need(type(call_record) is tuple and len(call_record) == 4
          and call_record[0] is scope and call_record[1] is v4
          and call_record[3] is prep_raw,
          "r2_call_record_changed")
    module_sources = call_record[2]
    _need(type(module_sources) is dict
          and module_sources.get("v3") is v3_raw
          and module_sources.get("v4") is v4_raw,
          "r2_module_source_references_changed")
    outer_gen = getattr(outer, "gen", None)
    current_frame = getattr(outer_gen, "gi_frame", None)
    if outer_closed:
        _need(current_frame is None and captured_outer_frame is not None
              and r2_record.get("outer_frame") is captured_outer_frame,
              "r2_original_outer_close_state_changed")
        outer_frame = captured_outer_frame
    else:
        _need(current_frame is not None and outer_gen.gi_suspended is True,
              "r2_original_outer_lease_changed")
        outer_frame = current_frame
    expected_refs = {
        "call_module": call_module,
        "call_raw": call_raw,
        "call_record": call_record,
        "cuv2_globals": outer_frame.f_globals,
        "driver": driver,
        "entry": entry,
        "held": held,
        "module_sources": module_sources,
        "outer": outer,
        "outer_frame": outer_frame,
        "outer_gen": outer_gen,
        "prep_raw": prep_raw,
        "r1_module": r1_module,
        "r1_raw": r1_raw,
        "r1_record": r1_record,
        "r1_registry": r1_registry,
        "root_namespace": root_namespace,
        "root_result": original_result,
        "root_state": root_state,
        "scope": scope,
        "v3_raw": v3_raw,
        "v4": v4,
        "v4_raw": v4_raw,
    }
    _need(all(r2_record.get(key) is value for key, value in expected_refs.items())
          and r2_record.get("phase") == "source_binding_blocked"
          and r2_record.get("exit_started") is False
          and r2_record.get("result_snapshot") == _snapshot_json(original_result),
          "r2_blocked_record_reference_changed")


def _verify_prior_r2_reconciliation(
    r2_module: object,
    r2_registry: object,
    r2_held: object,
    r2_raw: object,
    root_namespace: dict[str, object],
    root_state: dict[str, object],
    original_result: dict[str, object],
    r1_module: types.ModuleType,
    r1_registry: list[object],
    r1_record: dict[str, object],
    r1_raw: bytes,
) -> dict[str, object]:
    _need(type(r2_module) is types.ModuleType and r2_module.__name__ == R2_HELPER_NAME,
          "r2_helper_module_identity_invalid")
    _need(type(r2_registry) is list and type(r2_held) is tuple
          and type(r2_raw) is bytes,
          "r2_helper_reference_shape_invalid")
    _need(len(r2_registry) == 1 and type(r2_registry[0]) is dict,
          "r2_registry_count_or_record_invalid")
    record = r2_registry[0]
    _check_r2_record(
        r2_module, r2_registry, record, r2_held, r2_raw,
        root_namespace, root_state, original_result,
        r1_module, r1_registry, r1_record, r1_raw,
    )
    return record


def _check_prior_reconciliation_records(
    r1_module: types.ModuleType,
    r1_registry: list[object],
    r1_record: dict[str, object],
    r1_raw: bytes,
    r2_module: types.ModuleType,
    r2_registry: list[object],
    r2_record: dict[str, object],
    r2_held: tuple[object, ...],
    r2_raw: bytes,
    root_namespace: dict[str, object],
    root_state: dict[str, object],
    original_result: dict[str, object],
    *,
    outer_closed: bool = False,
    captured_outer_frame: object | None = None,
) -> None:
    _check_r1_record(r1_module, r1_registry, r1_record,
                     root_namespace, root_state, original_result)
    _check_r2_record(
        r2_module, r2_registry, r2_record, r2_held, r2_raw,
        root_namespace, root_state, original_result,
        r1_module, r1_registry, r1_record, r1_raw,
        outer_closed=outer_closed,
        captured_outer_frame=captured_outer_frame,
    )


_R3_RETAINED_KEYS = {
    "root_namespace", "root_state", "root_result", "r1_module", "r1_registry",
    "r1_raw", "r2_module", "r2_registry", "r2_held", "r2_raw", "phase",
    "exit_started", "r1_record", "r2_record", "result_snapshot", "driver",
    "attempt", "entry", "v4", "scope", "call_module", "call_record",
    "module_sources", "prep_raw", "call_raw", "v3_raw", "v4_raw", "outer",
    "held", "outer_gen", "outer_frame", "cuv2_globals", "cuv2_module",
    "cuv2_function", "outer_exit_method", "outer_exit_function",
    "outer_exit_code", "outer_exit_globals",
}


def _prior_r3_context(
    root_namespace: dict[str, object],
    root_state: dict[str, object],
    original_result: dict[str, object],
    r3_state: object,
) -> dict[str, object]:
    _need(type(r3_state) is dict
          and root_namespace.get("RECONCILIATION_ROOT_STATE_R3") is r3_state,
          "r3_root_state_identity_invalid")
    _need(r3_state.get("original_state") is root_state
          and r3_state.get("original_result") is original_result
          and r3_state.get("original_scope") is not None,
          "r3_original_root_references_changed")
    r3_module = r3_state.get("helper")
    binding = r3_state.get("binding")
    r3_held = r3_state.get("held")
    _need(type(r3_module) is types.ModuleType
          and r3_module.__name__ == R3_HELPER_NAME
          and type(binding) is tuple and len(binding) == 3
          and type(binding[0]) is tuple and type(binding[1]) is dict
          and type(r3_held) is tuple and len(r3_held) == 3
          and type(r3_held[2]) is dict,
          "r3_helper_state_shape_invalid")
    r3_registry = binding[2]
    _need(type(r3_registry) is list and r3_module._RETAINED is r3_registry
          and len(r3_registry) == 1 and type(r3_registry[0]) is dict,
          "r3_retained_registry_invalid")
    r3_record = r3_registry[0]
    _need(set(r3_record) == _R3_RETAINED_KEYS
          and r3_record.get("phase") == "inner_scope_retained"
          and r3_record.get("exit_started") is False
          and "v3" not in r3_record
          and "module_source_reference_verified" not in r3_record,
          "r3_blocked_record_stage_invalid")
    root_sys = root_namespace.get("sys")
    root_modules = getattr(root_sys, "modules", None)
    _need(type(root_modules) is dict
          and root_modules.get(R3_HELPER_NAME) is r3_module
          and sys.modules.get(R3_HELPER_NAME) is r3_module,
          "r3_helper_module_alias_invalid")
    r3_raw = _module_raw(r3_held[2], str(ROOT / R3_HELPER_REL))
    _need(_sha(r3_raw) == R3_HELPER_SHA256,
          "r3_helper_source_pin_invalid")
    _simple_module_source(
        r3_module, r3_raw, R3_HELPER_NAME, str(ROOT / R3_HELPER_REL),
        R3_HELPER_SHA256, allowed_mutable={"_RETAINED": r3_registry},
    )
    _verify_r3_helper_binding(r3_module, binding, r3_registry)
    r3_receipt = r3_state.get("receipt")
    observation = r3_state.get("observation")
    _need(type(r3_receipt) is dict
          and r3_receipt.get("schema") == "iteration41.optional16.preparation.source-reconciliation.r3"
          and r3_receipt.get("status") == "BLOCKED_RETAINED"
          and r3_receipt.get("reason_code") == "inner_binding_failed"
          and r3_receipt.get("inner_release") is False
          and r3_receipt.get("outer_normal_exit") is False
          and type(observation) is dict and observation.get("receipt") is r3_receipt,
          "r3_consumed_result_changed")
    review_scope = r3_state.get("review_scope")
    _need(type(review_scope) is contextlib._GeneratorContextManager
          and review_scope.gen.gi_frame is None,
          "r3_review_scope_not_normally_closed")
    r1_module = r3_record.get("r1_module")
    r1_registry = r3_record.get("r1_registry")
    r1_raw = r3_record.get("r1_raw")
    r1_record = r3_record.get("r1_record")
    r2_module = r3_record.get("r2_module")
    r2_registry = r3_record.get("r2_registry")
    r2_held = r3_record.get("r2_held")
    r2_raw = r3_record.get("r2_raw")
    r2_record = r3_record.get("r2_record")
    _check_prior_reconciliation_records(
        r1_module, r1_registry, r1_record, r1_raw,
        r2_module, r2_registry, r2_record, r2_held, r2_raw,
        root_namespace, root_state, original_result,
    )
    _need(r3_record.get("root_namespace") is root_namespace
          and r3_record.get("root_state") is root_state
          and r3_record.get("root_result") is original_result
          and r3_state.get("original_attempt") is r3_record.get("attempt")
          and r3_state.get("original_call_record") is r3_record.get("call_record")
          and r3_state.get("original_gen") is r3_record.get("outer_gen")
          and r3_state.get("original_scope") is r3_record.get("scope"),
          "r3_retained_reference_projection_changed")
    _need(r3_record.get("r1_module") is r1_module
          and r3_record.get("r1_registry") is r1_registry
          and r3_record.get("r1_raw") is r1_raw
          and r3_record.get("r2_module") is r2_module
          and r3_record.get("r2_registry") is r2_registry
          and r3_record.get("r2_held") is r2_held
          and r3_record.get("r2_raw") is r2_raw,
          "r3_prior_reconciliation_reference_changed")
    return {
        "state": r3_state, "binding": binding, "module": r3_module,
        "registry": r3_registry,
        "record": r3_record, "held": r3_held, "raw": r3_raw,
        "receipt": r3_receipt, "observation": observation,
        "observation_snapshot": _snapshot_json(observation),
        "r1_module": r1_module, "r1_registry": r1_registry,
        "r1_record": r1_record, "r1_raw": r1_raw,
        "r2_module": r2_module, "r2_registry": r2_registry,
        "r2_record": r2_record, "r2_held": r2_held, "r2_raw": r2_raw,
    }


def _check_prior_r3_context(
    context: dict[str, object],
    root_namespace: dict[str, object],
    root_state: dict[str, object],
    original_result: dict[str, object],
    *,
    inner_closed: bool = False,
    outer_closed: bool = False,
    captured_outer_frame: object | None = None,
) -> None:
    state = context["state"]
    module = context["module"]
    registry = context["registry"]
    record = context["record"]
    held = context["held"]
    raw = context["raw"]
    binding = context["binding"]
    _need(root_namespace.get("RECONCILIATION_ROOT_STATE_R3") is state
          and state.get("helper") is module and state.get("binding")[2] is registry
          and state.get("binding") is binding
          and state.get("held") is held
          and _module_raw(held[2], str(ROOT / R3_HELPER_REL)) is raw
          and module._RETAINED is registry and len(registry) == 1
          and registry[0] is record
          and sys.modules.get(R3_HELPER_NAME) is module
          and getattr(root_namespace.get("sys"), "modules", {}).get(R3_HELPER_NAME) is module,
          "r3_prior_registry_identity_changed")
    _need(record.get("phase") == "inner_scope_retained"
          and record.get("exit_started") is False
          and record.get("root_namespace") is root_namespace
          and record.get("root_state") is root_state
          and record.get("root_result") is original_result
          and state.get("receipt") is context["receipt"]
          and state.get("observation") is context["observation"]
          and _snapshot_json(context["observation"]) == context["observation_snapshot"],
          "r3_prior_record_or_result_changed")
    outer = record["outer"]
    outer_gen = record["outer_gen"]
    outer_frame = record["outer_frame"]
    scope = record["scope"]
    _need(outer.gen is outer_gen,
          "r3_original_outer_generator_replaced")
    if outer_closed:
        _need(outer_gen.gi_frame is None and captured_outer_frame is outer_frame,
              "r3_original_outer_close_state_changed")
    else:
        _need(outer_gen.gi_frame is outer_frame and outer_frame is not None,
              "r3_original_outer_frame_changed")
    _need(scope.state == ("CLOSED" if inner_closed else "OPEN"),
          "r3_original_inner_scope_state_changed")


def _check_prior_chain(
    context: dict[str, object],
    root_namespace: dict[str, object],
    root_state: dict[str, object],
    original_result: dict[str, object],
    *,
    inner_closed: bool = False,
    outer_closed: bool = False,
    captured_outer_frame: object | None = None,
) -> None:
    _check_prior_reconciliation_records(
        context["r1_module"], context["r1_registry"], context["r1_record"],
        context["r1_raw"], context["r2_module"], context["r2_registry"],
        context["r2_record"], context["r2_held"], context["r2_raw"],
        root_namespace, root_state, original_result,
        outer_closed=outer_closed,
        captured_outer_frame=captured_outer_frame,
    )
    _check_prior_r3_context(
        context, root_namespace, root_state, original_result,
        inner_closed=inner_closed,
        outer_closed=outer_closed,
        captured_outer_frame=captured_outer_frame,
    )


def reconcile_retained_preparation_r4(
    root_namespace: dict[str, object],
    root_state: dict[str, object],
    original_result: dict[str, object],
    r3_state: dict[str, object],
    *,
    requested: bool = False,
    _sourcefake_token: object = None,
) -> dict[str, object]:
    """Close the exact original V3 lease then outer CUv2 context, once.

    The production call must use the original Root namespace, state, result,
    modules, and retained tuples. It preserves consumed R1/R2/R3 reconciliation
    records and never invokes those helpers again. ``_sourcefake_token`` exists
    only for fake tests and cannot authorize a production scope.
    """
    sourcefake = _sourcefake_token is _SOURCEFAKE_TOKEN
    if requested is not True:
        return _receipt("BLOCKED", "request", reason="request_required",
                        physical_file_lease_state="NOT_TOUCHED")
    if _RETAINED:
        return _receipt("BLOCKED_ALREADY_USED", "one_shot", reason="reconciliation_already_attempted",
                        physical_file_lease_state="PRIOR_ATTEMPT_STATE_RETAINED")
    retained: dict[str, object] = {
        "root_namespace": root_namespace,
        "root_state": root_state,
        "root_result": original_result,
        "r3_state": r3_state,
        "phase": "authenticated_references",
        "exit_started": False,
    }
    _RETAINED.append(retained)
    try:
        r3_context = _prior_r3_context(
            root_namespace, root_state, original_result, r3_state,
        )
        r1_module = r3_context["r1_module"]
        r1_registry = r3_context["r1_registry"]
        r1_record = r3_context["r1_record"]
        r1_raw = r3_context["r1_raw"]
        r2_module = r3_context["r2_module"]
        r2_registry = r3_context["r2_registry"]
        r2_record = r3_context["r2_record"]
        r2_held = r3_context["r2_held"]
        r2_raw = r3_context["r2_raw"]
        r3_module = r3_context["module"]
        r3_registry = r3_context["registry"]
        r3_record = r3_context["record"]
        r3_held = r3_context["held"]
        r3_raw = r3_context["raw"]
        retained.update({
            "r1_module": r1_module, "r1_registry": r1_registry,
            "r1_raw": r1_raw, "r1_record": r1_record,
            "r2_module": r2_module, "r2_registry": r2_registry,
            "r2_held": r2_held, "r2_raw": r2_raw, "r2_record": r2_record,
            "r3_module": r3_module, "r3_registry": r3_registry,
            "r3_held": r3_held, "r3_raw": r3_raw, "r3_record": r3_record,
            "r3_context": r3_context,
        })
        r1_record = _verify_prior_r1_reconciliation(
            r1_module, r1_registry, r1_raw,
            root_namespace, root_state, original_result,
        )
        retained["r1_record"] = r1_record
        r2_record = _verify_prior_r2_reconciliation(
            r2_module, r2_registry, r2_held, r2_raw,
            root_namespace, root_state, original_result,
            r1_module, r1_registry, r1_record, r1_raw,
        )
        retained["r2_record"] = r2_record
        _need(r2_record is r3_context["r2_record"],
              "r3_r2_record_identity_changed")
        _check_root_globals(root_namespace, root_state, original_result, sourcefake=sourcefake)
        _need(root_namespace.get("PREP_STATE") is root_state
              and root_namespace.get("PREP_RESULT") is original_result,
              "root_original_reference_mismatch")
        result_snapshot = _snapshot_json(original_result)
        retained["result_snapshot"] = result_snapshot
        bindings = root_state.get("bindings")
        _need(type(bindings) is list and len(bindings) == 1,
              "root_driver_binding_record_invalid")
        bind_record = bindings[0]
        _need(type(bind_record) is tuple and len(bind_record) == 2
              and bind_record[0] is root_state.get("driver"),
              "root_driver_binding_identity_invalid")
        driver = root_state["driver"]
        outer = root_state["outer"]
        held = root_state["held"]
        _need(type(driver) is types.ModuleType and type(held) is tuple and len(held) == 3,
              "root_retained_reference_shape_invalid")
        _need(type(driver._RETAINED_ATTEMPTS) is list and len(driver._RETAINED_ATTEMPTS) == 1,
              "driver_retained_attempt_count_invalid")
        attempt = driver._RETAINED_ATTEMPTS[0]
        _need(type(attempt) is tuple and len(attempt) == 10,
              "driver_retained_attempt_shape_invalid")
        (entry, v4, payload_raw, preloaded, scope, call_module,
         prep_raw, call_raw, v3_raw, v4_raw) = attempt
        _need(type(entry) is types.ModuleType and type(v4) is types.ModuleType
              and type(scope) is v4.RootHeldScopeV4
              and type(call_module) is types.ModuleType,
              "driver_retained_module_identity_invalid")
        _need(type(payload_raw) is bytes and type(preloaded) is tuple
              and len(preloaded) == len(PRELOADED_SOURCES),
              "driver_retained_payload_shape_invalid")
        _need(call_module.__name__ == CALL_MODULE_NAME
              and type(call_module._RETAINED) is list
              and len(call_module._RETAINED) == 1,
              "call_retained_record_count_invalid")
        call_record = call_module._RETAINED[0]
        _need(type(call_record) is tuple and len(call_record) == 4,
              "call_retained_record_shape_invalid")
        call_scope, call_v4, module_sources, call_prep_raw = call_record
        _need(call_scope is scope and call_v4 is v4 and call_prep_raw is prep_raw
              and type(module_sources) is dict
              and set(module_sources) == {"v3", "v4"}
              and module_sources["v3"] is v3_raw
              and module_sources["v4"] is v4_raw,
              "call_retained_reference_mismatch")
        _need(_sha(prep_raw) == PREPARATION_SHA256
              and _sha(call_raw) == CALL_SHA256
              and _sha(v3_raw) == V3_SHA256
              and _sha(v4_raw) == V4_SHA256,
              "retained_source_bytes_pin_mismatch")
        _need(entry.__name__ == ENTRY_MODULE_NAME
              and entry.ROOT_ACTUAL_ENABLED is False
              and entry.ROOT_ENTRY_SOURCE_SHA256 == ENTRY_SHA256
              and entry._RETAINED == [], "entry_preparation_state_changed")
        _need(driver._ATTEMPT_STARTED is True
              and driver._OWNER_THREAD == threading.get_ident(),
              "driver_one_shot_or_thread_state_changed")
        _need(root_state.get("driver") is driver, "driver_reference_replaced")
        _need(_snapshot_json(original_result) == result_snapshot,
              "root_result_changed_before_reconciliation")

        outer_gen = outer.gen
        outer_frame = outer_gen.gi_frame
        _need(outer_frame is not None, "outer_frame_missing")
        cu_globals = outer_frame.f_globals
        cu_name = cu_globals.get("__name__")
        _need(type(cu_name) is str, "cuv2_module_name_invalid")
        raw_map = held[2]
        _need(type(raw_map) is dict, "outer_raw_bytes_map_invalid")
        retained.update({
            "driver": driver, "attempt": attempt, "entry": entry, "v4": v4,
            "scope": scope, "call_module": call_module, "call_record": call_record,
            "module_sources": module_sources, "prep_raw": prep_raw, "call_raw": call_raw,
            "v3_raw": v3_raw, "v4_raw": v4_raw, "outer": outer, "held": held,
            "outer_gen": outer_gen,
            "outer_frame": outer_frame, "cuv2_globals": cu_globals,
        })

        root_origin = str(ROOT / ROOT_RUNNER_REL)
        root_raw = None
        for path, raw in raw_map.items():
            if _key(path) == _key(root_origin):
                root_raw = raw
                break
        _need(type(root_raw) is bytes and _sha(root_raw) == ROOT_RUNNER_SHA256,
              "root_runner_source_pin_mismatch")
        _root_source_functions(root_namespace, root_raw, root_origin, sourcefake=sourcefake)
        root_namespace["verify"](bind_record)
        if not sourcefake:
            _exact_outer_maps(root_namespace, raw_map, outer_frame.f_locals, sourcefake=False)

        cu_source = None
        for path, raw in raw_map.items():
            if _key(path) == _key(CUV2_REL):
                cu_source = raw
                break
        _need(type(cu_source) is bytes and _sha(cu_source) == CUV2_SHA256,
              "cuv2_source_pin_mismatch")
        cu_module = sys.modules.get(cu_name)
        _need(type(cu_module) is types.ModuleType and cu_module.__dict__ is cu_globals,
              "cuv2_module_not_bound_to_generator_globals")
        retained["cuv2_module"] = cu_module
        (verified_cu_globals, verified_cu_function, verified_outer_frame,
         verified_outer_gen, verified_exit_method, verified_exit_function,
         verified_raw_map, verified_cu_origin) = _verify_outer_context(
             outer, held, cu_source, root_namespace, sourcefake=sourcefake
         )
        _need(verified_cu_globals is cu_globals and verified_outer_frame is outer_frame
              and verified_outer_gen is outer_gen and outer.gen is outer_gen
              and outer_gen.gi_frame is outer_frame and verified_raw_map is raw_map,
              "outer_binding_projection_changed")
        retained.update({
            "cuv2_function": verified_cu_function,
            "outer_gen": verified_outer_gen,
            "outer_exit_method": verified_exit_method,
            "outer_exit_function": verified_exit_function,
            "outer_exit_code": verified_exit_function.__code__,
            "outer_exit_globals": verified_exit_function.__globals__,
        })
        # The generator frame, not sys.modules, is the authority. The module
        # alias is used only after proving that it owns this exact globals dict.
        _simple_module_source(cu_module, cu_source, cu_name,
                              verified_cu_origin, CUV2_SHA256,
                              sourcefake=sourcefake, sourcefake_cuv2=True)
        _bind_cuv2_loaded_helpers(cu_module, held, raw_map, sourcefake=sourcefake)
    except BaseException:
        retained["phase"] = "source_binding_blocked"
        return _receipt("BLOCKED_RETAINED", "source_binding", reason="source_binding_failed")

    try:
        driver_origin = str(ROOT / DRIVER_REL)
        call_origin = str(ROOT / CALL_REL)
        entry_origin = str(ROOT / ENTRY_REL)
        _simple_module_source(driver, _module_raw(raw_map, driver_origin), DRIVER_MODULE_NAME,
                              driver_origin, DRIVER_SHA256,
                              allowed_mutable={
                                  "_RETAINED_ATTEMPTS": driver._RETAINED_ATTEMPTS,
                                  "_ATTEMPT_STARTED": True,
                                  "_OWNER_THREAD": driver._OWNER_THREAD,
                              })
        _simple_module_source(call_module, call_raw, CALL_MODULE_NAME, call_origin,
                              CALL_SHA256, allowed_mutable={"_RETAINED": call_module._RETAINED})
        _simple_module_source(entry, _module_raw(raw_map, entry_origin), ENTRY_MODULE_NAME,
                              entry_origin, ENTRY_SHA256,
                              allowed_mutable={"ROOT_ENTRY_SOURCE_SHA256": ENTRY_SHA256})
        for module, (relative, digest, name) in zip(preloaded, PRELOADED_SOURCES):
            origin = str(ROOT / relative)
            _simple_module_source(module, _module_raw(raw_map, origin), name,
                                  origin, digest)
        v3, _ = _bind_v3_v4(call_module, v4, module_sources, scope, root_namespace)
        retained.update({"v3": v3, "module_source_reference_verified": True})
        _scope_rows(scope, v4, sourcefake=sourcefake)
        _read_module_sources(scope, module_sources)
        _check_prior_chain(r3_context, root_namespace, root_state, original_result)
        _check_result_unchanged(root_namespace, root_state, original_result, result_snapshot)
    except BaseException:
        retained["phase"] = "inner_scope_retained"
        return _receipt("BLOCKED_RETAINED", "source_binding", reason="inner_binding_failed")

    retained["phase"] = "inner_release_started"
    try:
        _check_prior_chain(r3_context, root_namespace, root_state, original_result)
        inner_closed = scope.release(0, True)
    except BaseException:
        inner_closed = False
    if inner_closed is not True or scope.state != "CLOSED":
        retained["phase"] = "inner_release_failed"
        return _receipt("BLOCKED_RETAINED", "inner_release", reason="inner_release_failed",
                        physical_file_lease_state="INNER_SCOPE_OPEN_OR_PARTIAL")
    retained["inner_released"] = True
    try:
        _check_prior_chain(
            r3_context, root_namespace, root_state, original_result,
            inner_closed=True,
        )
        _need(scope._postverified is True and scope._failure is None,
              "inner_release_poststate_invalid")
        _need(type(v3._RETAINED_SCOPES) is list and not v3._RETAINED_SCOPES,
              "inner_registry_not_normally_released")
        _check_result_unchanged(root_namespace, root_state, original_result, result_snapshot)
    except BaseException:
        retained["phase"] = "inner_closed_poststate_uncertain"
        return _receipt("BLOCKED_RETAINED", "inner_poststate", inner_released=True,
                        reason="inner_release_poststate_invalid",
                        physical_file_lease_state="INNER_CLOSED_OUTER_OPEN")

    if not _outer_exit_target_matches(outer, retained):
        retained["phase"] = "outer_exit_target_changed"
        return _receipt("BLOCKED_RETAINED", "outer_exit", inner_released=True,
                        reason="outer_exit_target_changed",
                        physical_file_lease_state="INNER_CLOSED_OUTER_OPEN")

    retained["phase"] = "outer_exit_started"
    retained["exit_started"] = True
    try:
        normal_result = retained["outer_exit_method"](None, None, None)
    except BaseException:
        retained["phase"] = "outer_exit_failed"
        return _receipt("BLOCKED_RETAINED", "outer_exit", inner_released=True,
                        reason="outer_postverify_or_close_failed",
                        physical_file_lease_state="UNKNOWN_AFTER_OUTER_EXIT_EXCEPTION")
    if (normal_result is not False
            or outer.gen is not retained["outer_gen"]
            or retained["outer_gen"].gi_frame is not None):
        retained["phase"] = "outer_exit_uncertain"
        return _receipt("BLOCKED_RETAINED", "outer_exit", inner_released=True,
                        reason="outer_normal_exit_not_verified",
                        physical_file_lease_state="UNKNOWN_AFTER_OUTER_EXIT_RETURN")
    try:
        _check_prior_chain(
            r3_context, root_namespace, root_state, original_result,
            inner_closed=True,
            outer_closed=True,
            captured_outer_frame=retained.get("outer_frame"),
        )
    except BaseException:
        retained["phase"] = "outer_closed_r1_record_uncertain"
        return _receipt("BLOCKED_RETAINED", "closed", inner_released=True,
                        outer_closed=True, reason="r1_record_changed_after_outer_close",
                        physical_file_lease_state="CLOSED")
    if (type(outer).__exit__ is not retained["outer_exit_function"]
            or type(outer).__exit__.__code__ is not retained["outer_exit_code"]
            or type(outer).__exit__.__globals__ is not retained["outer_exit_globals"]):
        retained["phase"] = "outer_exit_callback_changed"
        return _receipt("BLOCKED_RETAINED", "outer_exit",
                        inner_released=True, outer_closed=True,
                        reason="outer_exit_callback_changed",
                        physical_file_lease_state="CLOSED")
    retained["phase"] = "closed"
    try:
        _check_result_unchanged(root_namespace, root_state, original_result, result_snapshot)
    except BaseException:
        retained["phase"] = "closed_result_reference_uncertain"
        return _receipt("BLOCKED_RETAINED", "closed", inner_released=True,
                        outer_closed=True, reason="root_result_changed_after_close",
                        physical_file_lease_state="CLOSED")
    return _receipt("ROOT_SOURCE_CUSTODY_CLOSED", "closed", inner_released=True,
                    outer_closed=True, physical_file_lease_state="CLOSED",
                    r1_registry_preserved=True,
                    r2_registry_preserved=True,
                    r3_registry_preserved=True)


def _module_raw(raw_map: dict[str, bytes], origin: str) -> bytes:
    for path, raw in raw_map.items():
        if _key(path) == _key(origin):
            _need(type(raw) is bytes, "outer_held_module_source_invalid")
            return raw
    raise ReconciliationError("outer_held_module_source_missing")


__all__ = ("SCHEMA", "reconcile_retained_preparation_r4")
