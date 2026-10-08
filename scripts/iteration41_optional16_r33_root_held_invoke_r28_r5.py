"""R28_r5 source-only adapter for the frozen R27 public root chain.

The adapter keeps activation disabled. Its source-fake entrypoints exercise the
real R27 child binder, R15 glue, complete held-source verification, and root
review. Custody bytes come only from indexed public snapshots; the protected
material creation leaf is replaced with an explicit refusal seam.
"""

from __future__ import annotations

import ast
import builtins as _builtins
import copy
import dataclasses
import dis
import hashlib
import importlib.machinery
import json
import ntpath
import os
from pathlib import Path
import sys
import types


ROOT = Path(r"D:\source_code\backtrader")
EVIDENCE = ROOT / "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence"
R27_INVOKE = ROOT / "scripts/iteration41_optional16_r33_root_held_invoke_r27.py"
R27_INVOKE_SHA256 = "ea0a4f9ec5978508b854fe457dd1cfc3c0e9c41b7b23b89ec461bfed4d798339"
R27_WHOLE = ROOT / "scripts/iteration41_optional16_r33_whole_call_supervisor_r27.py"
R27_WHOLE_SHA256 = "bfdd7bc9530b9ded9722ec86c1c184f36de3fb6337fb6688cbe15fa0f77f2876"
R27_TEST = ROOT / "tests/unit/scripts/test_iteration41_optional16_r33_activation_r27_source_fake.py"
R27_TEST_SHA256 = "d1794b07e9f742dc7ee893bf31194ca16729542d6936a303bc05b1ed55f4039f"
R19_DRIVER = ROOT / "scripts/iteration41_optional16_r33_root_driver_r19.py"
R2_PREDECESSOR_HELPER = ROOT / "scripts/iteration41_optional16_r33_root_held_invoke_r28_r2.py"
R2_PREDECESSOR_HELPER_SHA256 = "fea25e15d535e7cd47d0637e060d464cbc982e8cdedfc2a1b620d166118cb213"
R2_GLUE_PATH = ROOT / "scripts/iteration41_optional16_r33_root_held_glue_r15.py"
R2_GLUE_SHA256 = "f9c9a5332a9d2456db8179d7a7e63103269c16feb2712a2b039479d97fe2dd98"
R19_DRIVER_SHA256 = "d7cd9a173e44510e8e2df8fbf68ff5420e495b5a7dd82c589bd1cbef3351c890"
CUV2_SHA256 = "e856be8e4056835d4a7e54f5c6b449c69ab3f1c2ebb049bcbcc1c95a9ad3f246"
CUV2_PUBLIC_SNAPSHOT = (
    EVIDENCE / "iteration41-cuv2-public-source-snapshot-r1-2026-10-08/cuv2-source.py"
)
R25_SUPPLEMENT_BUNDLE = (
    EVIDENCE
    / "iteration41-optional16-installed-matrix-r25-cold-chain-supplement-independent-review-r1-2026-10-04/candidate/source-bundle-r1.zip"
)
R25_SUPPLEMENT_BUNDLE_SHA256 = "b80fc6b6d6851fbc0fa31cbd5efda91ce8dcf9c323cda65c2a09e9d718ad3b7e"
R25_PUBLIC_PINS_SHA256 = "99251a5d7225cf4334d927563b4915bafdbc2caa6bded7488c8a503d97ae51da"
R25_STAGE_ADAPT_SHA256 = "4e4c641b42bb3e3f6389ebef60362f32cfe8eda58344d06d3a6fe852ccaedc85"

ROOT_ACTUAL_ENABLED = False
ROOT_REVIEW_READY = False
ROOT_REVIEWED_ACTIVATION = False
ROOT_NATIVE_ENABLED = False
ROOT_EXTERNAL_SOURCE_HOLDS_VERIFIED = False
WHOLE_CALL_SECONDS = 100.0
CLEANUP_SECONDS = 5.0
EXPECTED_COLD_REQUEST_PATHS = 518
EXPECTED_R2_BASE_COLD_PATHS = 515
EXPECTED_R2_OUTER_EXTRA_PATHS = 14
EXPECTED_R2_COLD_OUTER_OVERLAPS = 11
EXPECTED_ACTIVE_PATHS = 575
EXPECTED_OUTER_ONLY_PATHS = 7
EXPECTED_FULL_PATHS = 582
EXPECTED_SOFTWARE_PATHS = 5
EXPECTED_ACTIVE_ALIASES = 19
EXPECTED_ACTIVE_ONLY_PATHS = 64

_HASH = frozenset("0123456789abcdef")
_R2_REVIEW_PIN_FIELDS = frozenset(
    {"review.json", "review-bundle.zip", "review-index.json", "review-checkpoint.json"}
)
_R19_REVIEW_PIN_FIELDS = _R2_REVIEW_PIN_FIELDS | {"README.md"}


class SourceContractError(RuntimeError):
    """A bounded source-contract failure with no caller data attached."""


# Expected function contracts live outside the module they attest. A reused
# sys.modules object cannot authorize its own changed function attributes.
_VERIFIED_MODULE_CONTRACTS: dict[int, dict[str, object]] = {}
_R5_BOUND_INVOKES: dict[int, dict[str, object]] = {}
_NAMESPACE_MAX_DEPTH = 16
_NAMESPACE_MAX_ITEMS = 8192
_MISSING_NAMESPACE_VALUE = object()
_TRUSTED_BUILTINS_MODULE = _builtins
_TRUSTED_BUILTINS_MAPPING = _builtins.__dict__
_TRUSTED_BUILTINS_BASELINE = types.MappingProxyType(dict(_TRUSTED_BUILTINS_MAPPING))


class _PinnedR19ActiveMap:
    """Result of deriving active pins from the exact held R19 source."""

    __slots__ = (
        "raw",
        "path",
        "name",
        "module",
        "source_reader",
        "pins",
        "software",
        "aliases",
        "module_code_fingerprint",
        "expected_pins_fingerprint",
        "global_dependency_names",
        "global_dependency_fingerprint",
        "global_dependency_objects",
        "packet_path",
        "packet_pins",
        "review_path",
        "review_pins",
        "test_path",
        "test_digest",
    )

    def __init__(
        self,
        *,
        raw: bytes,
        path: Path,
        name: str,
        module: types.ModuleType,
        source_reader,
        pins: dict[str, str],
        software: dict[str, str],
        aliases: int,
        packet_path: Path,
        packet_pins: dict[str, str],
        review_path: Path,
        review_pins: dict[str, str],
        test_path: Path,
        test_digest: str,
    ) -> None:
        self.raw = raw
        self.path = path
        self.name = name
        self.module = module
        self.source_reader = source_reader
        self.pins = dict(pins)
        self.software = dict(software)
        self.aliases = aliases
        self.module_code_fingerprint = _module_code_fingerprint(module)
        self.expected_pins_fingerprint = _code_fingerprint(module._expected_pins.__code__)
        self.global_dependency_names = _global_dependency_names(module, ("_expected_pins",))
        self.global_dependency_fingerprint = _module_global_dependency_fingerprint(
            module, self.global_dependency_names
        )
        self.global_dependency_objects = tuple(
            (name, module.__dict__[name]) for name in self.global_dependency_names
        )
        self.packet_path = packet_path
        self.packet_pins = dict(packet_pins)
        self.review_path = review_path
        self.review_pins = dict(review_pins)
        self.test_path = test_path
        self.test_digest = test_digest


def _need(condition: bool, code: str) -> None:
    if not condition:
        raise SourceContractError(code)


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _valid_hash(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in _HASH for character in value)
    )


def path_key(path: str | os.PathLike[str]) -> str:
    _need(isinstance(path, (str, os.PathLike)), "path_type_invalid")
    return ntpath.normcase(ntpath.normpath(os.fspath(path)))


def _constant_fingerprint(value: object) -> object:
    if isinstance(value, types.CodeType):
        return ("code", _code_fingerprint(value))
    if type(value) is tuple:
        return ("tuple", tuple(_constant_fingerprint(item) for item in value))
    if type(value) is frozenset:
        items = [_constant_fingerprint(item) for item in value]
        return ("frozenset", tuple(sorted(items, key=repr)))
    if value is None:
        return ("none",)
    if type(value) is bool:
        return ("bool", value)
    if type(value) is int:
        return ("int", str(value))
    if type(value) is float:
        return ("float", value.hex())
    if type(value) is complex:
        return ("complex", value.real.hex(), value.imag.hex())
    if type(value) is str:
        return ("str", value)
    if type(value) is bytes:
        return ("bytes", value.hex())
    if value is Ellipsis:
        return ("ellipsis",)
    raise SourceContractError("module_constant_type_unsupported")


def _code_fingerprint(code: types.CodeType) -> str:
    fields = (
        code.co_argcount,
        code.co_posonlyargcount,
        code.co_kwonlyargcount,
        code.co_nlocals,
        code.co_stacksize,
        code.co_flags,
        code.co_code.hex(),
        tuple(_constant_fingerprint(value) for value in code.co_consts),
        code.co_names,
        code.co_varnames,
        code.co_filename,
        code.co_name,
        code.co_qualname,
        code.co_firstlineno,
        code.co_linetable.hex(),
        code.co_exceptiontable.hex(),
        code.co_freevars,
        code.co_cellvars,
    )
    canonical = json.dumps(fields, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return hashlib.sha256(canonical).hexdigest()


def _module_code_fingerprint(module: types.ModuleType) -> tuple[tuple[str, str], ...]:
    rows = []
    for name, value in vars(module).items():
        if isinstance(value, types.FunctionType):
            rows.append((name, _code_fingerprint(value.__code__)))
    return tuple(sorted(rows))


def _global_dependency_names(module: types.ModuleType, roots: tuple[str, ...]) -> tuple[str, ...]:
    found: set[str] = set()
    pending = [getattr(module, name, None) for name in roots]
    seen_functions: set[int] = set()
    while pending:
        function = pending.pop()
        if type(function) is not types.FunctionType or function.__globals__ is not module.__dict__:
            continue
        if id(function) in seen_functions:
            continue
        seen_functions.add(id(function))
        for name in function.__code__.co_names:
            if name not in module.__dict__:
                continue
            found.add(name)
            value = module.__dict__[name]
            if type(value) is types.FunctionType and value.__globals__ is module.__dict__:
                pending.append(value)
    return tuple(sorted(found))


def _namespace_function_roots(module: types.ModuleType) -> tuple[types.FunctionType, ...]:
    roots = {
        value
        for value in vars(module).values()
        if type(value) is types.FunctionType and value.__globals__ is module.__dict__
    }
    for value in vars(module).values():
        if type(value) is not type or value.__module__ != module.__name__:
            continue
        for member in vars(value).values():
            if type(member) is types.FunctionType and member.__globals__ is module.__dict__:
                roots.add(member)
            elif type(member) in (staticmethod, classmethod):
                function = member.__func__
                if type(function) is types.FunctionType and function.__globals__ is module.__dict__:
                    roots.add(function)
            elif type(member) is property:
                for function in (member.fget, member.fset, member.fdel):
                    if type(function) is types.FunctionType and function.__globals__ is module.__dict__:
                        roots.add(function)
    return tuple(sorted(roots, key=lambda function: (function.__qualname__, id(function))))


def _nested_code_names(code: types.CodeType) -> set[str]:
    names = {
        instruction.argval
        for instruction in dis.get_instructions(code)
        if instruction.opname in {"LOAD_GLOBAL", "LOAD_NAME", "STORE_GLOBAL", "DELETE_GLOBAL"}
        and type(instruction.argval) is str
    }
    for value in code.co_consts:
        if type(value) is types.CodeType:
            names.update(_nested_code_names(value))
    return names


def _nested_code_builtin_dependencies(code: types.CodeType) -> tuple[str, ...]:
    """Return bounded builtin names loaded or addressed by pinned code."""
    found: set[str] = set()
    pending = [code]
    while pending:
        current = pending.pop()
        instructions = tuple(dis.get_instructions(current))
        loads_builtin_mapping = False
        reads_builtin_mapping = False
        literal_keys: set[str] = set()
        for instruction in instructions:
            if instruction.opname in {
                "LOAD_GLOBAL", "LOAD_NAME", "STORE_GLOBAL", "DELETE_GLOBAL",
                "LOAD_ATTR", "LOAD_METHOD",
            } and type(instruction.argval) is str:
                if instruction.argval in _TRUSTED_BUILTINS_BASELINE:
                    found.add(instruction.argval)
                if instruction.argval == "__builtins__" and instruction.opname in {"LOAD_GLOBAL", "LOAD_NAME"}:
                    loads_builtin_mapping = True
            if instruction.opname in {"LOAD_ATTR", "LOAD_METHOD", "BINARY_SUBSCR"}:
                reads_builtin_mapping = True
            if instruction.opname == "LOAD_CONST" and type(instruction.argval) is str:
                if instruction.argval in _TRUSTED_BUILTINS_BASELINE:
                    literal_keys.add(instruction.argval)
            if instruction.opname == "IMPORT_NAME":
                found.add("__import__")
            elif instruction.opname == "LOAD_BUILD_CLASS":
                found.add("__build_class__")
            elif instruction.opname == "LOAD_ASSERTION_ERROR":
                found.add("AssertionError")
        if loads_builtin_mapping and reads_builtin_mapping:
            if not literal_keys:
                raise SourceContractError("module_builtin_dynamic_lookup_unsupported")
            found.update(literal_keys)
        pending.extend(value for value in current.co_consts if type(value) is types.CodeType)
    return tuple(sorted(found))


def _trusted_builtin_dependency(value: object) -> bool:
    """Accept only immutable builtin values whose source identity is stable."""
    return (
        value is None
        or value is Ellipsis
        or value is NotImplemented
        or type(value) in (bool, int, float, complex, str, bytes)
        or type(value) in (type, types.BuiltinFunctionType, types.BuiltinMethodType)
    )


def _module_function_builtin_dependencies(module: types.ModuleType) -> tuple[str, ...]:
    names: set[str] = set()
    for value in vars(module).values():
        if type(value) is not types.FunctionType:
            continue
        mapping = value.__globals__.get("__builtins__", _MISSING_NAMESPACE_VALUE)
        _need(
            value.__builtins__ is mapping
            and mapping is _TRUSTED_BUILTINS_MAPPING,
            "module_function_builtin_mapping_untrusted",
        )
        names.update(_nested_code_builtin_dependencies(value.__code__))
    for function in _namespace_function_roots(module):
        names.update(_nested_code_builtin_dependencies(function.__code__))
    return tuple(sorted(names))


def _check_builtin_dependency_values(
    mapping: object,
    names: tuple[str, ...],
) -> None:
    _need(mapping is _TRUSTED_BUILTINS_MAPPING, "module_builtin_mapping_untrusted")
    for name in names:
        expected = _TRUSTED_BUILTINS_BASELINE.get(name, _MISSING_NAMESPACE_VALUE)
        _need(
            expected is not _MISSING_NAMESPACE_VALUE
            and _trusted_builtin_dependency(expected),
            "module_builtin_dependency_unsupported",
        )
        _need(
            mapping.get(name, _MISSING_NAMESPACE_VALUE) is expected,
            "module_builtin_dependency_changed",
        )


def _module_builtin_contract(module: types.ModuleType, raw: bytes) -> tuple[str, ...]:
    """Bind effective module/function builtins to the pre-admission snapshot."""
    effective = module.__dict__.get("__builtins__", _MISSING_NAMESPACE_VALUE)
    _need(
        type(effective) is dict and effective is _TRUSTED_BUILTINS_MAPPING,
        "module_builtin_mapping_untrusted",
    )
    try:
        compiled = compile(raw, str(getattr(module, "__file__", "<pinned-source>")), "exec", dont_inherit=True)
    except (SyntaxError, TypeError, ValueError):
        raise SourceContractError("module_builtin_source_compile_invalid") from None
    names = tuple(sorted(set(_nested_code_builtin_dependencies(compiled)) | set(_module_function_builtin_dependencies(module))))
    _check_builtin_dependency_values(effective, names)
    return names


def _module_namespace_names(module: types.ModuleType) -> tuple[str, ...]:
    pending = list(_namespace_function_roots(module))
    seen: set[int] = set()
    found: set[str] = set()
    while pending:
        function = pending.pop()
        if type(function) is not types.FunctionType or function.__globals__ is not module.__dict__:
            continue
        if id(function) in seen:
            continue
        seen.add(id(function))
        for name in _nested_code_names(function.__code__):
            if name not in module.__dict__:
                continue
            found.add(name)
            value = module.__dict__[name]
            if type(value) is types.FunctionType and value.__globals__ is module.__dict__:
                pending.append(value)
    return tuple(sorted(found))


def _namespace_function_fingerprint(
    function: types.FunctionType,
    module: types.ModuleType,
    include_identity: bool,
    *,
    depth: int = 0,
    seen: dict[int, int] | None = None,
    budget: list[int] | None = None,
) -> object:
    if seen is None:
        seen = {}
    if budget is None:
        budget = [0]
    budget[0] += 1
    if budget[0] > _NAMESPACE_MAX_ITEMS or depth > _NAMESPACE_MAX_DEPTH:
        raise SourceContractError("module_namespace_limit_exceeded")
    prior = seen.get(id(function))
    if prior is not None:
        return ("function_ref", prior)
    seen[id(function)] = len(seen)
    closure = []
    for cell in function.__closure__ or ():
        try:
            item = cell.cell_contents
        except ValueError:
            item = _EMPTY_CELL
        closure.append(
            ("empty",)
            if item is _EMPTY_CELL
            else _namespace_value_fingerprint(
                item, module, include_identity=include_identity, depth=depth + 1,
                seen=seen, budget=budget
            )
        )
    return (
        "function",
        id(function) if include_identity else None,
        function.__module__,
        function.__name__,
        function.__qualname__,
        _code_fingerprint(function.__code__),
        _contract_value(function.__defaults__),
        _contract_value(function.__kwdefaults__),
        _contract_value(function.__annotations__),
        function.__code__.co_freevars,
        tuple(closure),
        function.__globals__ is module.__dict__,
        id(function.__globals__) if include_identity else None,
    )


def _namespace_value_fingerprint(
    value: object,
    module: types.ModuleType,
    *,
    include_identity: bool,
    depth: int = 0,
    seen: dict[int, int] | None = None,
    budget: list[int] | None = None,
) -> object:
    """Fingerprint a bounded set of exact builtin/source dependency values."""
    if depth > _NAMESPACE_MAX_DEPTH:
        raise SourceContractError("module_namespace_depth_exceeded")
    if seen is None:
        seen = {}
    if budget is None:
        budget = [0]
    budget[0] += 1
    if budget[0] > _NAMESPACE_MAX_ITEMS:
        raise SourceContractError("module_namespace_item_limit_exceeded")
    kind = type(value)
    if value is _TRUSTED_BUILTINS_MAPPING:
        return ("trusted_builtins_mapping", id(value) if include_identity else None)
    if value is None or kind in (bool, int, float, complex, str, bytes):
        return _contract_value(value)
    if value is Ellipsis:
        return ("ellipsis",)
    if isinstance(value, Path):
        return ("path", os.fspath(value))
    if kind is bytearray:
        return ("bytearray", id(value) if include_identity else None, bytes(value).hex())
    if kind in (tuple, list, dict, set, frozenset):
        prior = seen.get(id(value))
        if prior is not None:
            return ("ref", prior)
        ordinal = len(seen)
        seen[id(value)] = ordinal
        identity = id(value) if include_identity and kind in (list, dict, set) else None
        if kind is tuple:
            contents = tuple(
                _namespace_value_fingerprint(
                    item, module, include_identity=include_identity, depth=depth + 1,
                    seen=seen, budget=budget
                )
                for item in value
            )
            return ("tuple", contents)
        if kind is list:
            contents = tuple(
                _namespace_value_fingerprint(
                    item, module, include_identity=include_identity, depth=depth + 1,
                    seen=seen, budget=budget
                )
                for item in value
            )
            return ("list", identity, contents)
        if kind is dict:
            pairs = [
                (
                    _namespace_value_fingerprint(
                        key, module, include_identity=include_identity, depth=depth + 1,
                        seen=seen, budget=budget
                    ),
                    _namespace_value_fingerprint(
                        item, module, include_identity=include_identity, depth=depth + 1,
                        seen=seen, budget=budget
                    ),
                )
                for key, item in value.items()
            ]
            pairs.sort(key=lambda pair: repr(pair[0]))
            return ("dict", identity, tuple(pairs))
        items = [
            _namespace_value_fingerprint(
                item, module, include_identity=include_identity, depth=depth + 1,
                seen=seen, budget=budget
            )
            for item in value
        ]
        return (kind.__name__, identity, tuple(sorted(items, key=repr)))
    if kind is types.FunctionType:
        return _namespace_function_fingerprint(
            value, module, include_identity, depth=depth, seen=seen, budget=budget
        )
    if kind is types.MethodType:
        function = value.__func__
        return (
            "method",
            id(value) if include_identity else None,
            id(value.__self__) if include_identity else None,
            _namespace_function_fingerprint(function, module, include_identity),
        )
    if kind is types.BuiltinFunctionType:
        return (
            "builtin_function",
            id(value),
            getattr(value, "__module__", None),
            getattr(value, "__qualname__", getattr(value, "__name__", None)),
            id(getattr(value, "__self__", None)) if include_identity else None,
        )
    if kind is types.ModuleType:
        attrs = vars(value)
        spec = attrs.get("__spec__")
        origin = vars(spec).get("origin") if type(spec) is importlib.machinery.ModuleSpec else None
        return (
            "module",
            id(value),
            attrs.get("__name__"),
            attrs.get("__file__"),
            origin,
        )
    if value is dataclasses.MISSING:
        return ("dataclasses_missing",)
    if kind is types.MappingProxyType:
        pairs = [
            (
                _namespace_value_fingerprint(
                    key, module, include_identity=include_identity, depth=depth + 1,
                    seen=seen, budget=budget
                ),
                _namespace_value_fingerprint(
                    item, module, include_identity=include_identity, depth=depth + 1,
                    seen=seen, budget=budget
                ),
            )
            for key, item in value.items()
        ]
        pairs.sort(key=lambda pair: repr(pair[0]))
        return ("mappingproxy", tuple(pairs))
    if kind.__module__ == "dataclasses" and kind.__qualname__ == "Field":
        field_names = (
            "name", "type", "default", "default_factory", "init", "repr",
            "hash", "compare", "metadata", "kw_only",
        )
        parts = []
        for name in field_names:
            try:
                item = object.__getattribute__(value, name)
            except AttributeError:
                item = None
            parts.append(
                (
                    name,
                    _namespace_value_fingerprint(
                        item, module, include_identity=include_identity, depth=depth + 1,
                        seen=seen, budget=budget
                    ),
                )
            )
        return ("dataclass_field", tuple(parts))
    if kind.__module__ == "dataclasses" and kind.__qualname__ == "_DataclassParams":
        field_names = (
            "init", "repr", "eq", "order", "unsafe_hash", "frozen",
            "match_args", "kw_only", "slots", "weakref_slot",
        )
        parts = []
        for name in field_names:
            try:
                item = object.__getattribute__(value, name)
            except AttributeError:
                continue
            parts.append((name, _namespace_value_fingerprint(
                item, module, include_identity=include_identity, depth=depth + 1,
                seen=seen, budget=budget
            )))
        return ("dataclass_params", tuple(parts))
    if kind is importlib.machinery.ModuleSpec:
        return (
            "module_spec",
            value.name,
            value.origin,
            value.parent,
            value.has_location,
            _namespace_value_fingerprint(
                value.loader,
                module,
                include_identity=include_identity,
                depth=depth + 1,
                seen=seen,
                budget=budget,
            ) if value.loader is not None else None,
            _namespace_value_fingerprint(
                value.submodule_search_locations,
                module,
                include_identity=include_identity,
                depth=depth + 1,
                seen=seen,
                budget=budget,
            ) if value.submodule_search_locations is not None else None,
        )
    if kind is type:
        if value.__module__ != module.__name__:
            return ("external_type", id(value), value.__module__, value.__qualname__)
        prior = seen.get(id(value))
        if prior is not None:
            return ("type_ref", prior)
        seen[id(value)] = len(seen)
        members = []
        is_dataclass = "__dataclass_fields__" in vars(value)
        generated_dataclass_methods = {
            "__init__", "__repr__", "__eq__", "__hash__", "__setattr__", "__delattr__"
        }
        for name, member in sorted(vars(value).items()):
            if name in {
                "__dict__", "__weakref__", "__module__", "__doc__", "__qualname__",
                "__dataclass_fields__", "__dataclass_params__",
            }:
                continue
            if is_dataclass and not include_identity and name in generated_dataclass_methods:
                continue
            if type(member) is staticmethod:
                member_value = ("staticmethod", _namespace_function_fingerprint(
                    member.__func__, module, include_identity, depth=depth + 1,
                    seen=seen, budget=budget
                ))
            elif type(member) is classmethod:
                member_value = ("classmethod", _namespace_function_fingerprint(
                    member.__func__, module, include_identity, depth=depth + 1,
                    seen=seen, budget=budget
                ))
            elif type(member) is property:
                member_value = (
                    "property",
                    *(
                        None if function is None else _namespace_function_fingerprint(
                            function, module, include_identity, depth=depth + 1,
                            seen=seen, budget=budget
                        )
                        for function in (member.fget, member.fset, member.fdel)
                    ),
                )
            elif type(member) is types.FunctionType:
                member_value = _namespace_function_fingerprint(
                    member, module, include_identity, depth=depth + 1,
                    seen=seen, budget=budget
                )
            else:
                member_value = _namespace_value_fingerprint(
                    member, module, include_identity=include_identity, depth=depth + 1,
                    seen=seen, budget=budget
                )
            members.append((name, member_value))
            budget[0] += 1
            if budget[0] > _NAMESPACE_MAX_ITEMS:
                raise SourceContractError("module_namespace_item_limit_exceeded")
        if is_dataclass:
            fields = []
            for field in dataclasses.fields(value):
                fields.append(
                    (
                        field.name,
                        _namespace_value_fingerprint(
                            field.type, module, include_identity=include_identity,
                            depth=depth + 1, seen=seen, budget=budget
                        ),
                        _namespace_value_fingerprint(
                            field.default, module, include_identity=include_identity,
                            depth=depth + 1, seen=seen, budget=budget
                        ),
                        _namespace_value_fingerprint(
                            field.default_factory, module, include_identity=include_identity,
                            depth=depth + 1, seen=seen, budget=budget
                        ),
                        field.init, field.repr, field.hash, field.compare, field.kw_only,
                        _namespace_value_fingerprint(
                            field.metadata, module, include_identity=include_identity,
                            depth=depth + 1, seen=seen, budget=budget
                        ),
                    )
                )
            members.append(("__dataclass_fields_contract__", tuple(fields)))
        return (
            "source_type",
            id(value) if include_identity else None,
            value.__module__,
            value.__qualname__,
            tuple(
                (base.__module__, base.__qualname__, id(base) if include_identity else None)
                for base in value.__bases__
            ),
            tuple(members),
        )
    if kind is object:
        return ("object_token", id(value) if include_identity else None)
    if kind.__module__ == "re" and kind.__qualname__ == "Pattern":
        return ("regex_pattern", value.pattern, value.flags)
    raise SourceContractError("module_namespace_value_type_unsupported")


def _module_namespace_fingerprint(
    module: types.ModuleType,
    names: tuple[str, ...],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for name in names:
        if name not in module.__dict__:
            raise SourceContractError("module_namespace_binding_missing")
        value = module.__dict__[name]
        if name == "__builtins__":
            result[name] = (
                "module_builtins_mapping",
                id(value),
                type(value).__module__,
                type(value).__qualname__,
            )
            continue
        if type(value) is types.FunctionType:
            continue
        result[name] = _namespace_value_fingerprint(
            value, module, include_identity=True
        )
    return result


def _verify_source_namespace(
    module: types.ModuleType,
    reference: types.ModuleType,
    *,
    allowed_differences: frozenset[str] = frozenset(),
) -> tuple[str, ...]:
    """Compare source-derived global dependencies before stage authorization."""
    names = _module_namespace_names(reference)
    _need(allowed_differences <= set(names), "module_namespace_stage_name_unbound")
    for name in names:
        _need(name in module.__dict__ and name in reference.__dict__, "module_namespace_binding_missing")
        if name == "__builtins__":
            _need(
                module.__dict__[name] is _TRUSTED_BUILTINS_MAPPING
                and type(reference.__dict__[name]) is dict,
                "module_builtin_mapping_untrusted",
            )
            continue
        if name in allowed_differences:
            continue
        actual = module.__dict__[name]
        expected = reference.__dict__[name]
        if (
            type(expected) is types.FunctionType
            and expected.__globals__ is reference.__dict__
        ):
            continue
        actual_fingerprint = _namespace_value_fingerprint(actual, module, include_identity=False)
        expected_fingerprint = _namespace_value_fingerprint(expected, reference, include_identity=False)
        _need(
            actual_fingerprint == expected_fingerprint,
            "module_namespace_source_value_changed",
        )
    return names


def _global_value_fingerprint(value: object, module: types.ModuleType, seen=None) -> object:
    if seen is None:
        seen = set()
    if type(value) in (tuple, list, dict, set, frozenset):
        if id(value) in seen:
            return ("cycle", type(value).__name__)
        seen.add(id(value))
    if value is None or type(value) in (bool, int, float, complex, str, bytes):
        return _contract_value(value)
    if isinstance(value, Path):
        return ("path", type(value).__module__, type(value).__qualname__, os.fspath(value))
    if type(value) is tuple:
        return ("tuple", tuple(_global_value_fingerprint(item, module, seen) for item in value))
    if type(value) is list:
        return ("list", tuple(_global_value_fingerprint(item, module, seen) for item in value))
    if type(value) in (set, frozenset):
        items = [_global_value_fingerprint(item, module, seen) for item in value]
        return (type(value).__name__, tuple(sorted(items, key=repr)))
    if type(value) is dict:
        items = [
            (
                _global_value_fingerprint(key, module, seen),
                _global_value_fingerprint(item, module, seen),
            )
            for key, item in value.items()
        ]
        return ("dict", tuple(sorted(items, key=lambda pair: repr(pair[0]))))
    if type(value) is types.FunctionType:
        _need(value.__globals__ is module.__dict__, "source_function_global_owner_invalid")
        closure = []
        for cell in value.__closure__ or ():
            try:
                item = cell.cell_contents
            except ValueError:
                item = _EMPTY_CELL
            closure.append(_global_value_fingerprint(item, module, seen))
        return (
            "source_function",
            value.__name__,
            value.__qualname__,
            _code_fingerprint(value.__code__),
            _contract_value(value.__defaults__),
            _contract_value(value.__kwdefaults__),
            _contract_value(value.__annotations__),
            value.__code__.co_freevars,
            tuple(closure),
        )
    if isinstance(value, types.ModuleType):
        return (
            "module_identity",
            id(value),
            value.__name__,
            getattr(value, "__file__", None),
            getattr(getattr(value, "__spec__", None), "origin", None),
        )
    if isinstance(value, type):
        return ("type_identity", id(value), value.__module__, value.__qualname__)
    pattern = getattr(value, "pattern", None)
    flags = getattr(value, "flags", None)
    if type(pattern) is str and type(flags) is int:
        return ("pattern", type(value).__module__, type(value).__qualname__, pattern, flags)
    if isinstance(value, types.MethodType):
        return ("method_identity", id(value), id(value.__self__), id(value.__func__))
    return ("object_identity", type(value).__module__, type(value).__qualname__, id(value))


def _module_global_dependency_fingerprint(
    module: types.ModuleType,
    names: tuple[str, ...],
    *,
    overrides: dict[str, object] | None = None,
    override_owners: dict[str, types.ModuleType] | None = None,
) -> tuple[tuple[str, object], ...]:
    overrides = overrides or {}
    override_owners = override_owners or {}
    return tuple(
        (
            name,
            _global_value_fingerprint(
                overrides[name] if name in overrides else module.__dict__[name],
                override_owners.get(name, module),
            ),
        )
        for name in names
    )


def _contract_value(value: object, *, mutable_identity: bool = False) -> object:
    """Fingerprint function metadata without evaluating caller-defined code."""
    if value is None:
        return ("none",)
    if type(value) is bool:
        return ("bool", value)
    if type(value) is int:
        return ("int", str(value))
    if type(value) is float:
        return ("float", value.hex())
    if type(value) is complex:
        return ("complex", value.real.hex(), value.imag.hex())
    if type(value) is str:
        return ("str", value)
    if type(value) is bytes:
        return ("bytes", value.hex())
    if value is Ellipsis:
        return ("ellipsis",)
    if type(value) is tuple:
        return ("tuple", tuple(_contract_value(item) for item in value))
    if type(value) is frozenset:
        parts = [_contract_value(item) for item in value]
        return ("frozenset", tuple(sorted(parts, key=repr)))
    if type(value) is list:
        return (
            "list",
            id(value) if mutable_identity else None,
            tuple(_contract_value(item) for item in value),
        )
    if type(value) is dict:
        items = [(_contract_value(key), _contract_value(item)) for key, item in value.items()]
        items.sort(key=lambda pair: repr(pair[0]))
        return ("dict", id(value) if mutable_identity else None, tuple(items))
    if isinstance(value, Path):
        return ("path", type(value).__module__, type(value).__qualname__, os.fspath(value))
    if isinstance(value, types.ModuleType):
        return (
            "module_identity", id(value), getattr(value, "__name__", None),
            getattr(value, "__file__", None),
            getattr(getattr(value, "__spec__", None), "origin", None),
        )
    if isinstance(value, type):
        return ("type_identity", id(value), value.__module__, value.__qualname__)
    if isinstance(value, types.FunctionType):
        return (
            "function_identity", id(value), _code_fingerprint(value.__code__),
            _contract_value(value.__defaults__), _contract_value(value.__kwdefaults__),
            id(value.__globals__),
        )
    if isinstance(value, types.MethodType):
        return ("method_identity", id(value), id(value.__self__), id(value.__func__))
    pattern = getattr(value, "pattern", None)
    flags = getattr(value, "flags", None)
    if type(pattern) is str and type(flags) is int:
        return ("pattern", type(value).__module__, type(value).__qualname__, pattern, flags)
    return ("object_identity", type(value).__module__, type(value).__qualname__, id(value))


_EMPTY_CELL = object()


def _function_contract(function: types.FunctionType) -> dict[str, object]:
    closure = function.__closure__ or ()
    closure_values = []
    closure_semantics = []
    for cell in closure:
        try:
            value = cell.cell_contents
        except ValueError:
            value = _EMPTY_CELL
        closure_semantics.append(
            ("empty_cell",) if value is _EMPTY_CELL else _contract_value(value)
        )
        if type(value) in (dict, list, set, bytearray):
            value_contract = ("mutable_cell_identity", type(value).__module__, type(value).__qualname__, id(value))
        else:
            value_contract = _contract_value(value)
        closure_values.append((id(value), value_contract))
    return {
        "function": function,
        "name": function.__name__,
        "qualname": function.__qualname__,
        "module": function.__module__,
        "code": _code_fingerprint(function.__code__),
        "defaults": _contract_value(function.__defaults__),
        "kwdefaults": _contract_value(function.__kwdefaults__),
        "annotations": _contract_value(function.__annotations__),
        "attributes": _contract_value(function.__dict__),
        "annotation_mapping": function.__annotations__,
        "attribute_mapping": function.__dict__,
        "globals": function.__globals__,
        "builtins": function.__builtins__,
        "closure_cells": tuple(closure),
        "closure_values": tuple(closure_values),
        "closure_semantics": tuple(closure_semantics),
        "freevars": function.__code__.co_freevars,
    }


def _contract_matches(
    function: object,
    expected: dict[str, object],
    *,
    require_identity: bool = True,
) -> bool:
    if type(function) is not types.FunctionType:
        return False
    if require_identity and function is not expected.get("function"):
        return False
    actual = _function_contract(function)
    for field in (
        "name", "qualname", "module", "code", "defaults", "kwdefaults",
        "annotations", "attributes", "closure_values", "freevars",
    ):
        if actual[field] != expected[field]:
            return False
    if require_identity and (
        actual["annotation_mapping"] is not expected["annotation_mapping"]
        or actual["attribute_mapping"] is not expected["attribute_mapping"]
    ):
        return False
    if actual["globals"] is not expected["globals"]:
        return False
    if actual["builtins"] is not expected["builtins"]:
        return False
    actual_cells = actual["closure_cells"]
    expected_cells = expected["closure_cells"]
    return len(actual_cells) == len(expected_cells) and all(
        left is right for left, right in zip(actual_cells, expected_cells)
    )


def _reference_module(raw: bytes, path: Path, name: str) -> types.ModuleType:
    probe = types.ModuleType(name)
    probe.__file__ = str(path)
    probe.__package__ = ""
    probe.__cached__ = None
    probe.__loader__ = None
    probe.__spec__ = importlib.machinery.ModuleSpec(name, loader=None, origin=str(path))
    probe.__dict__["__builtins__"] = dict(_TRUSTED_BUILTINS_BASELINE)
    exec(compile(raw, str(path), "exec", dont_inherit=True), probe.__dict__)
    return probe


def _function_matches_reference(
    actual: object,
    reference: object,
    *,
    actual_module: types.ModuleType,
    _seen: set[tuple[int, int]] | None = None,
) -> bool:
    if type(actual) is not types.FunctionType or type(reference) is not types.FunctionType:
        return False
    pair = (id(actual), id(reference))
    seen = set() if _seen is None else _seen
    if pair in seen:
        return True
    seen.add(pair)
    actual_contract = _function_contract(actual)
    reference_contract = _function_contract(reference)
    for field in (
        "name", "qualname", "code", "defaults", "kwdefaults", "annotations", "freevars",
    ):
        if actual_contract[field] != reference_contract[field]:
            return False
    if reference.__module__ != actual_module.__name__:
        return actual is reference and actual.__globals__ is reference.__globals__
    if actual.__module__ != actual_module.__name__:
        return False
    if (
        actual.__builtins__ is not actual.__globals__.get("__builtins__")
        or reference.__builtins__ is not reference.__globals__.get("__builtins__")
    ):
        return False
    if (
        actual.__globals__ is not actual_module.__dict__
        and actual.__globals__ is not reference.__globals__
    ):
        return False
    return (
        _function_attribute_mapping_matches(
            actual.__dict__, reference.__dict__, actual_module=actual_module, _seen=seen
        )
        and _function_closure_matches(actual, reference, actual_module=actual_module, _seen=seen)
    )


def _function_closure_matches(
    actual: types.FunctionType,
    reference: types.FunctionType,
    *,
    actual_module: types.ModuleType,
    _seen: set[tuple[int, int]],
) -> bool:
    actual_cells = actual.__closure__ or ()
    reference_cells = reference.__closure__ or ()
    if len(actual_cells) != len(reference_cells):
        return False
    for actual_cell, reference_cell in zip(actual_cells, reference_cells):
        try:
            actual_value = actual_cell.cell_contents
        except ValueError:
            actual_value = _EMPTY_CELL
        try:
            reference_value = reference_cell.cell_contents
        except ValueError:
            reference_value = _EMPTY_CELL
        if actual_value is _EMPTY_CELL or reference_value is _EMPTY_CELL:
            if actual_value is not reference_value:
                return False
            continue
        if not _function_attribute_value_matches(
            actual_value,
            reference_value,
            actual_module=actual_module,
            _seen=_seen,
        ):
            return False
    return True


def _function_attribute_value_matches(
    actual: object,
    reference: object,
    *,
    actual_module: types.ModuleType,
    _seen: set[tuple[int, int]],
) -> bool:
    if type(actual) is types.FunctionType and type(reference) is types.FunctionType:
        if reference.__module__ != actual_module.__name__:
            return actual is reference
        return _function_matches_reference(
            actual, reference, actual_module=actual_module, _seen=_seen
        )
    if type(actual) is not type(reference):
        return False
    if type(actual) in (type(None), bool, int, float, str, bytes):
        return actual == reference
    if type(actual) is tuple:
        return len(actual) == len(reference) and all(
            _function_attribute_value_matches(
                left, right, actual_module=actual_module, _seen=_seen
            )
            for left, right in zip(actual, reference)
        )
    if type(actual) is frozenset:
        if len(actual) != len(reference):
            return False
        return all(
            any(
                _function_attribute_value_matches(
                    left, right, actual_module=actual_module, _seen=_seen
                )
                for right in reference
            )
            for left in actual
        )
    if type(actual) is list:
        return len(actual) == len(reference) and all(
            _function_attribute_value_matches(
                left, right, actual_module=actual_module, _seen=_seen
            )
            for left, right in zip(actual, reference)
        )
    if type(actual) is dict:
        return actual.keys() == reference.keys() and all(
            _function_attribute_value_matches(
                actual[key], reference[key], actual_module=actual_module, _seen=_seen
            )
            for key in actual
        )
    return actual is reference


def _function_attribute_mapping_matches(
    actual: object,
    reference: object,
    *,
    actual_module: types.ModuleType,
    _seen: set[tuple[int, int]],
) -> bool:
    return (
        type(actual) is dict
        and type(reference) is dict
        and actual.keys() == reference.keys()
        and all(
            _function_attribute_value_matches(
                actual[key], reference[key], actual_module=actual_module, _seen=_seen
            )
            for key in actual
        )
    )


def _function_reference_issue(
    actual: object,
    reference: object,
    *,
    actual_module: types.ModuleType,
) -> str | None:
    if type(actual) is not types.FunctionType or type(reference) is not types.FunctionType:
        return "function_type"
    actual_contract = _function_contract(actual)
    reference_contract = _function_contract(reference)
    for field in (
        "name", "qualname", "code", "defaults", "kwdefaults", "annotations", "freevars",
    ):
        if actual_contract[field] != reference_contract[field]:
            return field
    if reference.__module__ != actual_module.__name__:
        return None if actual is reference and actual.__globals__ is reference.__globals__ else "reference_module"
    if actual.__module__ != actual_module.__name__:
        return "reference_module"
    if (
        actual.__globals__ is not actual_module.__dict__
        and actual.__globals__ is not reference.__globals__
    ):
        return "globals_owner"
    if not _function_attribute_mapping_matches(
        actual.__dict__, reference.__dict__, actual_module=actual_module, _seen={(id(actual), id(reference))}
    ):
        return "attributes"
    if not _function_closure_matches(
        actual,
        reference,
        actual_module=actual_module,
        _seen={(id(actual), id(reference))},
    ):
        return "closure"
    return None


def _module_function_names(module: types.ModuleType) -> set[str]:
    return {name for name, value in vars(module).items() if type(value) is types.FunctionType}


def _assert_module_contract(module: types.ModuleType) -> None:
    contract = _VERIFIED_MODULE_CONTRACTS.get(id(module))
    _need(type(contract) is dict and contract.get("module") is module, "module_contract_missing")
    builtin_names = contract.get("builtin_names")
    _need(type(builtin_names) is tuple, "module_builtin_contract_missing")
    effective_builtins = module.__dict__.get("__builtins__", _MISSING_NAMESPACE_VALUE)
    _need(
        contract.get("builtin_mapping") is _TRUSTED_BUILTINS_MAPPING
        and effective_builtins is _TRUSTED_BUILTINS_MAPPING,
        "module_builtin_mapping_untrusted",
    )
    runtime_builtin_names = _module_function_builtin_dependencies(module)
    _need(
        set(runtime_builtin_names) <= set(builtin_names),
        "module_builtin_dependency_set_changed",
    )
    _check_builtin_dependency_values(effective_builtins, builtin_names)
    expected = contract.get("functions")
    if type(expected) is not dict or _module_function_names(module) != set(expected):
        actual_names = _module_function_names(module)
        expected_names = set(expected) if type(expected) is dict else set()
        _need(
            False,
            "module_function_set_changed:extra="
            + ",".join(sorted(actual_names - expected_names))
            + ":missing="
            + ",".join(sorted(expected_names - actual_names)),
        )
    for name, function_contract in expected.items():
        _need(_contract_matches(getattr(module, name, None), function_contract), "module_function_contract_changed")
    bindings = contract.get("global_bindings")
    _need(
        type(bindings) is dict
        and all(module.__dict__.get(name) is value for name, value in bindings.items()),
        "module_global_binding_changed",
    )
    namespace_names = contract.get("namespace_names")
    namespace = contract.get("namespace")
    current_namespace = (
        _module_namespace_fingerprint(module, namespace_names)
        if type(namespace_names) is tuple else None
    )
    _need(
        type(namespace_names) is tuple
        and type(namespace) is dict
        and current_namespace == namespace,
        "module_namespace_value_changed",
    )


def _record_verified_module_code(
    module: types.ModuleType,
    namespace_names: tuple[str, ...],
    builtin_names: tuple[str, ...],
) -> None:
    functions = {
        name: _function_contract(value)
        for name, value in vars(module).items()
        if type(value) is types.FunctionType
    }
    _VERIFIED_MODULE_CONTRACTS[id(module)] = {
        "module": module,
        "path": getattr(module, "__file__", None),
        "source_sha256": getattr(module, "__r28_verified_source_sha256__", None),
        "builtin_mapping": module.__dict__.get("__builtins__"),
        "builtin_names": builtin_names,
        "functions": functions,
        "global_bindings": {},
        "namespace_names": namespace_names,
        "namespace": _module_namespace_fingerprint(module, namespace_names),
        "stages": ("source_compile",),
    }


def _accept_module_namespace_stage(
    module: types.ModuleType,
    allowed_bindings: dict[str, object] | None,
    *,
    stage: str,
) -> None:
    """Advance only globals named by a validator-backed source stage."""
    contract = _VERIFIED_MODULE_CONTRACTS.get(id(module))
    _need(type(contract) is dict and contract.get("module") is module, "module_namespace_contract_missing")
    allowed = {} if allowed_bindings is None else allowed_bindings
    _need(type(allowed) is dict, "module_namespace_stage_shape_invalid")
    prior_names = contract.get("namespace_names")
    prior_fingerprint = contract.get("namespace")
    _need(type(prior_names) is tuple and type(prior_fingerprint) is dict, "module_namespace_contract_missing")
    current_names = _module_namespace_names(module)
    added_names = set(current_names) - set(prior_names)
    _need(added_names <= set(allowed), "module_namespace_new_dependency_unlisted")
    names = tuple(sorted(set(prior_names) | set(current_names)))
    current_fingerprint = _module_namespace_fingerprint(module, names)
    changed = {
        name
        for name in set(prior_fingerprint) | set(current_fingerprint)
        if prior_fingerprint.get(name) != current_fingerprint.get(name)
    }
    _need(changed <= set(allowed), "module_namespace_stage_change_unlisted")
    for name in changed | added_names:
        expected = allowed.get(name, _MISSING_NAMESPACE_VALUE)
        _need(expected is not _MISSING_NAMESPACE_VALUE, "module_namespace_stage_expected_missing")
        _need(module.__dict__.get(name, _MISSING_NAMESPACE_VALUE) is expected, "module_namespace_stage_value_unbound")
    prior_builtin_names = contract.get("builtin_names")
    _need(type(prior_builtin_names) is tuple, "module_builtin_contract_missing")
    builtin_names = tuple(
        sorted(set(prior_builtin_names) | set(_module_function_builtin_dependencies(module)))
    )
    _check_builtin_dependency_values(
        module.__dict__.get("__builtins__", _MISSING_NAMESPACE_VALUE),
        builtin_names,
    )
    contract["builtin_names"] = builtin_names
    contract["namespace_names"] = names
    contract["namespace"] = current_fingerprint
    contract["stages"] = tuple(contract["stages"]) + (stage,)


def _install_module_global_binding(
    module: types.ModuleType,
    name: str,
    value: object,
    *,
    stage: str,
) -> None:
    _assert_module_contract(module)
    _need(type(name) is str and name in module.__dict__, "module_global_binding_name_invalid")
    contract = _VERIFIED_MODULE_CONTRACTS[id(module)]
    old = module.__dict__[name]
    if type(old) is types.FunctionType:
        expected_functions = dict(contract["functions"])
        _need(
            name in expected_functions and expected_functions[name]["function"] is old,
            "module_global_binding_old_function_unbound",
        )
        expected_functions.pop(name)
    else:
        expected_functions = dict(contract["functions"])
    module.__dict__[name] = value
    if type(value) is types.FunctionType:
        expected_functions[name] = _function_contract(value)
    contract["functions"] = expected_functions
    bindings = dict(contract["global_bindings"])
    bindings[name] = value
    contract["global_bindings"] = bindings
    _accept_module_namespace_stage(module, {name: value}, stage=stage)


def _advance_module_contract(
    module: types.ModuleType,
    replacements: dict[str, types.FunctionType],
    additions: dict[str, types.FunctionType] | None = None,
    *,
    stage: str,
    namespace_bindings: dict[str, object] | None = None,
) -> None:
    """Accept only the named functions installed by a source-bound stage."""
    additions = additions or {}
    namespace_bindings = {} if namespace_bindings is None else dict(namespace_bindings)
    prior = _VERIFIED_MODULE_CONTRACTS.get(id(module))
    _need(
        type(prior) is dict
        and prior.get("module") is module
        and prior.get("path") == getattr(module, "__file__", None)
        and prior.get("source_sha256") == getattr(module, "__r28_verified_source_sha256__", None),
        "module_stage_source_unbound",
    )
    previous = dict(prior["functions"])
    allowed = set(replacements) | set(additions)
    for name, function_contract in previous.items():
        if name not in allowed:
            _need(
                _contract_matches(getattr(module, name, None), function_contract),
                "module_stage_unlisted_function_changed:" + name,
            )
    expected = {name: value for name, value in previous.items() if name not in replacements}
    for name, function in replacements.items():
        actual = getattr(module, name, None)
        _need(name in previous, "module_stage_replacement_invalid")
        replacement_contract = _function_contract(function)
        _need(
            _contract_matches(actual, replacement_contract, require_identity=actual is function),
            "module_stage_replacement_invalid",
        )
        replacement_contract["function"] = actual
        replacement_contract["annotation_mapping"] = actual.__annotations__
        replacement_contract["attribute_mapping"] = actual.__dict__
        expected[name] = replacement_contract
    for name, function in additions.items():
        _need(name not in expected and getattr(module, name, None) is function, "module_stage_addition_invalid")
        expected[name] = _function_contract(function)
    _need(_module_function_names(module) == set(expected), "module_stage_function_set_invalid")
    for name, function in replacements.items():
        if function.__globals__ is not module.__dict__:
            namespace_bindings.setdefault(name, function)
    for name, function in additions.items():
        namespace_bindings.setdefault(name, function)
    _accept_module_namespace_stage(module, namespace_bindings, stage=stage)
    prior["functions"] = expected


def _verify_loaded_module(
    module: object,
    raw: bytes,
    path: Path,
    name: str,
) -> types.ModuleType:
    _need(type(module) is types.ModuleType and module.__name__ == name, "module_alias_unbound")
    expected = sha256(raw)
    _need(
        _valid_hash(expected)
        and getattr(module, "__file__", None) == str(path)
        and getattr(getattr(module, "__spec__", None), "origin", None) == str(path),
        "module_origin_unbound",
    )
    declared = getattr(module, "__verified_source_sha256__", None)
    if declared is not None:
        _need(declared == expected, "module_digest_unbound")
    prior_contract = _VERIFIED_MODULE_CONTRACTS.get(id(module))
    if prior_contract is not None:
        _need(prior_contract.get("module") is module, "module_contract_identity_changed")
        _need(
            prior_contract.get("path") == str(path)
            and prior_contract.get("source_sha256") == expected,
            "module_reuse_origin_changed",
        )
        _assert_module_contract(module)
        return module
    builtin_names = _module_builtin_contract(module, raw)
    reference = _reference_module(raw, path, name)
    actual_names = _module_function_names(module)
    reference_names = _module_function_names(reference)
    _need(actual_names == reference_names, "module_function_set_unbound")
    for function_name in sorted(actual_names):
        _need(
            _function_matches_reference(
                getattr(module, function_name),
                getattr(reference, function_name),
                actual_module=module,
            ),
            "module_function_source_unbound:" + function_name,
        )
    namespace_names = _verify_source_namespace(module, reference)
    module.__verified_source_sha256__ = expected
    module.__r28_verified_source_sha256__ = expected
    module.__r28_verified_path__ = str(path)
    _record_verified_module_code(module, namespace_names, builtin_names)
    return module


def _install_exact_nested_loaders(module: types.ModuleType, source_reader=None) -> None:
    _assert_module_contract(module)
    if getattr(module, "__r28_nested_loaders_installed__", False) is True:
        return
    module.__r28_nested_reuse_audit__ = []
    replacements: dict[str, types.FunctionType] = {}
    nested = getattr(module, "_load_declared", None)
    if callable(nested):
        original_nested = nested

        def verified_declared(raw: bytes, path: Path, name: str):
            reused = name in sys.modules
            result = _verified_load(original_nested, raw, path, name, source_reader)
            if reused:
                module.__r28_nested_reuse_audit__.append(name)
            return result

        verified_declared.__r28_loader__ = True
        module._load_declared = verified_declared
        replacements["_load_declared"] = verified_declared

    load_r16 = getattr(module, "_load_r16_helper", None)
    if callable(load_r16):
        original_load_r16 = load_r16

        def verified_r16(raw: bytes | None = None):
            helper_path = Path(module.R16_HELPER_PATH)
            expected = module.R16_HELPER_SHA256
            if raw is None:
                _need(callable(source_reader), "r16_reuse_requires_pinned_reader")
                raw = source_reader(helper_path, expected)
            _need(type(raw) is bytes, "r16_reuse_requires_held_bytes")
            _need(sha256(raw) == expected and _valid_hash(expected), "r16_helper_digest_invalid")
            name = "_iteration41_optional16_r33_r16_frozen_binding_" + expected[:12]
            prior = sys.modules.get(name)
            if prior is not None:
                result = _verify_loaded_module(prior, raw, helper_path, name)
                module.__r28_nested_reuse_audit__.append(name)
                return result
            result = original_load_r16(raw)
            return _verify_loaded_module(result, raw, helper_path, name)

        verified_r16.__r28_loader__ = True
        module._load_r16_helper = verified_r16
        replacements["_load_r16_helper"] = verified_r16
    module.__r28_nested_loaders_installed__ = True
    _advance_module_contract(module, replacements, stage="r28_exact_nested_loaders")


def _verified_load(original_loader, raw: bytes, path: Path, name: str, source_reader=None) -> types.ModuleType:
    _need(type(raw) is bytes and isinstance(path, Path) and type(name) is str, "module_load_shape")
    digest = sha256(raw)
    _need(_valid_hash(digest), "module_source_digest_invalid")
    prior = sys.modules.get(name)
    if prior is not None:
        module = _verify_loaded_module(prior, raw, path, name)
    else:
        module = original_loader(raw, path, name)
        module = _verify_loaded_module(module, raw, path, name)
    _install_exact_nested_loaders(module, source_reader)
    return module


def install_verified_module_reuse(invoke: types.ModuleType, source_reader=None) -> None:
    """Allow only byte- and origin-matched reuse of frozen helper aliases."""
    _need(callable(source_reader), "invoke_source_reader_required")
    invoke_raw = source_reader(R27_INVOKE, R27_INVOKE_SHA256)
    _need(type(invoke_raw) is bytes and sha256(invoke_raw) == R27_INVOKE_SHA256,
          "invoke_source_pin_invalid")
    _verify_loaded_module(invoke, invoke_raw, R27_INVOKE, invoke.__name__)
    _assert_module_contract(invoke)
    original_loader = invoke._load_declarations
    invoke.__r28_module_reuse_audit__ = []

    def exact_loader(raw: bytes, path: Path, name: str) -> types.ModuleType:
        reused = name in sys.modules
        result = _verified_load(original_loader, raw, path, name, source_reader)
        if reused:
            invoke.__r28_module_reuse_audit__.append(name)
        return result

    exact_loader.__r28_loader__ = True
    invoke._load_declarations = exact_loader
    _advance_module_contract(
        invoke,
        {"_load_declarations": exact_loader},
        stage="r28_declared_module_loader",
    )


def install_sourcefake_fixed_reader(
    invoke: types.ModuleType,
    context: dict[str, object],
) -> None:
    """Bind the existing fixed-source read leaf to the authorized public map."""
    _assert_module_contract(invoke)
    reader = context.get("source_snapshot_reader")
    _need(
        type(context) is dict
        and context.get("mode") == "actual"
        and callable(reader),
        "sourcefake_fixed_reader_context_invalid",
    )
    _install_module_global_binding(
        invoke,
        "_read_fixed",
        reader,
        stage="r28_sourcefake_public_fixed_reader",
    )


def install_verified_exact_reuse(module: types.ModuleType) -> None:
    """Reuse an already-loaded fixed alias only after exact byte/origin checks."""
    _assert_module_contract(module)
    original_loader = module._load_exact
    module.__r28_exact_reuse_audit__ = []

    def exact_loader(raw: bytes, path: Path, name: str, pin: str) -> types.ModuleType:
        _need(type(raw) is bytes and _valid_hash(pin) and sha256(raw) == pin,
              "exact_module_source_pin_invalid")
        prior = sys.modules.get(name)
        if prior is not None:
            loaded = _verify_loaded_module(prior, raw, path, name)
            module.__r28_exact_reuse_audit__.append(name)
        else:
            loaded = original_loader(raw, path, name, pin)
            loaded = _verify_loaded_module(loaded, raw, path, name)
        _install_exact_nested_loaders(loaded)
        return loaded

    exact_loader.__r28_loader__ = True
    module._load_exact = exact_loader
    _advance_module_contract(
        module,
        {"_load_exact": exact_loader},
        stage="r28_exact_module_loader",
    )


def _normalize_map(mapping: object, code: str) -> dict[str, str]:
    _need(type(mapping) is dict, code)
    result: dict[str, str] = {}
    for path, digest in mapping.items():
        key = path_key(path)
        _need(_valid_hash(digest), "pin_digest_invalid")
        prior = result.get(key)
        _need(prior is None or prior == digest, "path_digest_conflict")
        result[key] = digest
    return result


def project_r19_review_pins(
    review_pins: object,
    readme_digest: object,
    review_path: object,
    held_pins: object,
    expected_review_path: object,
    expected_readme_digest: object,
) -> dict[str, str]:
    """Join R2's four pins with its separately bound, held README pin."""
    _need(type(review_pins) is dict and set(review_pins) == _R2_REVIEW_PIN_FIELDS,
          "r2_review_projection_four_pin_shape")
    _need(all(_valid_hash(value) for value in review_pins.values()), "r2_review_projection_pin_invalid")
    _need(_valid_hash(readme_digest), "r2_review_projection_readme_digest_invalid")
    _need(isinstance(review_path, (str, os.PathLike)), "r2_review_projection_path_type")
    raw_path = os.fspath(review_path)
    _need(type(raw_path) is str and ntpath.isabs(raw_path), "r2_review_projection_path_invalid")
    _need(
        isinstance(expected_review_path, (str, os.PathLike))
        and ntpath.isabs(os.fspath(expected_review_path))
        and path_key(review_path) == path_key(expected_review_path),
        "r2_review_projection_context_path_mismatch",
    )
    _need(
        _valid_hash(expected_readme_digest) and readme_digest == expected_readme_digest,
        "r2_review_projection_context_readme_mismatch",
    )
    _need(type(held_pins) is dict, "r2_review_projection_held_map_type")
    result = dict(review_pins)
    _need("README.md" not in result, "r2_review_projection_readme_already_present")
    result["README.md"] = readme_digest
    _need(set(result) == _R19_REVIEW_PIN_FIELDS, "r19_review_projection_five_pin_shape")
    root = path_key(review_path)
    for name, digest in result.items():
        held_digest = held_pins.get(path_key(Path(review_path) / name))
        _need(held_digest == digest, "r2_review_projection_path_digest_mismatch")
    _need(bool(root), "r2_review_projection_path_context_invalid")
    return result


def install_r2_review_projection(r2: types.ModuleType, context: dict[str, object]) -> None:
    """Patch one exact, source-pinned R2 copy site to pass the full R19 review map.

    R2 validates four review files plus a separate README digest. Its frozen
    caller then copies only the four fields to R19, whose unchanged activation
    validator requires five. This transformation replaces only that exact
    assignment RHS with a checked adapter call; all R2 and R19 validators stay
    intact.
    """
    _assert_module_contract(r2)
    raw = context.get("r2_raw")
    original = getattr(r2, "main", None)
    code = getattr(original, "__code__", None)
    _need(type(raw) is bytes and sha256(raw) == R2_GLUE_SHA256, "r2_projection_source_pin_invalid")
    _need(
        type(r2) is types.ModuleType
        and getattr(r2, "__verified_source_sha256__", None) == R2_GLUE_SHA256
        and type(original) is types.FunctionType
        and original.__globals__ is r2.__dict__
        and type(code) is types.CodeType
        and code.co_name == "main"
        and not code.co_freevars,
        "r2_projection_main_identity_invalid",
    )
    try:
        tree = ast.parse(raw.decode("utf-8", "strict"))
    except (UnicodeError, SyntaxError):
        raise SourceContractError("r2_projection_source_parse_invalid") from None
    main_nodes = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "main"]
    _need(len(main_nodes) == 1 and isinstance(main_nodes[0], ast.FunctionDef), "r2_projection_main_ast_invalid")
    original_node = main_nodes[0]
    transformed_node = copy.deepcopy(original_node)
    anchors = []
    for node in ast.walk(transformed_node):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        value = node.value
        if (
            isinstance(target, ast.Attribute)
            and isinstance(target.value, ast.Name)
            and target.value.id == "active"
            and target.attr == "ROOT_DRIVER_REVIEW_PINS"
            and isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id == "dict"
            and len(value.args) == 1
            and isinstance(value.args[0], ast.Name)
            and value.args[0].id == "ROOT_REVIEW_PINS"
            and not value.keywords
        ):
            anchors.append(node)
    _need(len(anchors) == 1, "r2_projection_exact_anchor_count_invalid")
    callsite = anchors[0]
    callsite.value = ast.Call(
        func=ast.Name(id="_r28_project_r19_review_pins", ctx=ast.Load()),
        args=[
            callsite.value,
            ast.Name(id="ROOT_REVIEW_README_SHA", ctx=ast.Load()),
            ast.Name(id="REVIEW", ctx=ast.Load()),
        ],
        keywords=[],
    )
    ast.fix_missing_locations(transformed_node)
    transformed_module = ast.Module(body=[transformed_node], type_ignores=[])
    try:
        compiled = compile(
            transformed_module,
            code.co_filename,
            "exec",
            dont_inherit=True,
        )
    except (SyntaxError, TypeError, ValueError):
        raise SourceContractError("r2_projection_compile_invalid") from None
    schema_bridge = context.get("r2_parent_schema_bridge")
    _need(
        type(schema_bridge) is dict
        and schema_bridge.get("source_sha256") == R2_GLUE_SHA256
        and schema_bridge.get("changed_constant_count") == 1,
        "r2_projection_parent_schema_provenance_missing",
    )
    scratch: dict[str, object] = {"__builtins__": __builtins__}
    exec(compiled, scratch)
    transformed_main = scratch.get("main")
    transformed_code = getattr(transformed_main, "__code__", None)
    _need(
        type(transformed_main) is types.FunctionType
        and type(transformed_code) is types.CodeType,
        "r2_projection_transformed_code_invalid",
    )
    old_schema = schema_bridge.get("original_schema")
    new_schema = schema_bridge.get("accepted_schema")
    schema_indexes = [
        index
        for index, value in enumerate(transformed_code.co_consts)
        if type(value) is str and value == old_schema
    ]
    _need(len(schema_indexes) == 1 and type(new_schema) is str,
          "r2_projection_parent_schema_anchor_invalid")
    schema_constants = list(transformed_code.co_consts)
    schema_constants[schema_indexes[0]] = new_schema
    transformed_code = transformed_code.replace(co_consts=tuple(schema_constants))
    _need(
        transformed_code.co_name == code.co_name
        and transformed_code.co_filename == code.co_filename
        and transformed_code.co_argcount == code.co_argcount
        and transformed_code.co_kwonlyargcount == code.co_kwonlyargcount
        and transformed_code.co_freevars == code.co_freevars,
        "r2_projection_transformed_code_invalid",
    )

    def project(review_pins, readme_digest, review_path):
        _need(context.get("mode") == "actual", "r2_review_projection_wrong_mode")
        held_pins = context.get("expected_pins")
        projected = project_r19_review_pins(
            review_pins,
            readme_digest,
            review_path,
            held_pins,
            r2.REVIEW,
            r2.ROOT_REVIEW_README_SHA,
        )
        context["r2_review_projection_runtime"] = {
            "four_review_pins_validated": True,
            "separate_readme_path_and_digest_validated": True,
            "same_review_directory_validated": True,
            "projected_pin_count": len(projected),
        }
        return projected

    r2._r28_project_r19_review_pins = project
    prior_fingerprint = _code_fingerprint(code)
    transformed_fingerprint = _code_fingerprint(transformed_code)
    expected_main = types.FunctionType(
        transformed_code,
        r2.__dict__,
        original.__name__,
        original.__defaults__,
        original.__closure__,
    )
    expected_main.__module__ = original.__module__
    expected_main.__qualname__ = original.__qualname__
    expected_main.__kwdefaults__ = original.__kwdefaults__
    expected_main.__annotations__ = dict(original.__annotations__)
    expected_main.__dict__.update(original.__dict__)
    original.__code__ = transformed_code
    _advance_module_contract(
        r2,
        {"main": expected_main},
        {"_r28_project_r19_review_pins": project},
        stage="r28_r2_exact_ast_review_projection",
    )
    context["r2_review_projection_install"] = {
        "source_sha256": R2_GLUE_SHA256,
        "source_function": "main",
        "exact_anchor_count": 1,
        "changed_assignment": "active.ROOT_DRIVER_REVIEW_PINS",
        "original_code_fingerprint": prior_fingerprint,
        "transformed_code_fingerprint": transformed_fingerprint,
        "schema_bridge_original": old_schema,
        "schema_bridge_accepted": new_schema,
        "r2_r19_validators_changed": False,
    }


def derive_review_required_paths(invoke: types.ModuleType) -> set[str]:
    """Rebuild the binder's exact source/artifact input set from frozen helpers."""
    r19_binding = sys.modules.get("_iteration41_optional16_r33_r19_driver_validate")
    driver = sys.modules.get("_iteration41_optional16_r33_r19_child_driver_activation")
    r17 = sys.modules.get("_iteration41_optional16_r33_r17_driver_validate")
    r18 = sys.modules.get("_iteration41_optional16_r33_r18_driver_validate")
    _need(
        all(type(module) is types.ModuleType for module in (r19_binding, driver, r17, r18)),
        "review_helper_aliases_missing",
    )
    r16_name = "_iteration41_optional16_r33_r16_frozen_binding_" + r17.R16_HELPER_SHA256[:12]
    r16 = sys.modules.get(r16_name)
    _need(type(r16) is types.ModuleType, "r16_review_helper_missing")

    source_names = (
        set(r16.SUCCESSOR_ROLE_PATHS.values())
        | {r16.SUCCESSOR_TEST_PATH}
        | set(r17.R17_ROLE_PATHS.values())
        | {r17.R17_TEST_PATH}
        | set(r18.R18_ROLE_PATHS.values())
        | {r18.R18_TEST_PATH}
        | set(r19_binding.R19_ROLE_PATHS.values())
        | {r19_binding.R19_TEST_PATH}
    )
    result = {path_key(invoke.ROOT / name) for name in source_names}
    for folder, mapping in (
        (r19_binding.R16_PACKET, r19_binding.R16_PACKET_PINS),
        (r19_binding.R16_REVIEW, r19_binding.R16_REVIEW_PINS),
        (r19_binding.R17_PACKET, r19_binding.R17_PACKET_PINS),
        (r19_binding.R17_REVIEW, r19_binding.R17_REVIEW_PINS),
        (r19_binding.R18_PACKET, r19_binding.R18_PACKET_PINS),
        (r19_binding.R18_REVIEW, r19_binding.R18_REVIEW_PINS),
        (driver.DRIVER_PACKET, driver.ROOT_DRIVER_PACKET_PINS),
        (driver.DRIVER_REVIEW, driver.ROOT_DRIVER_REVIEW_PINS),
    ):
        result.update(path_key(folder / name) for name in mapping)
    return result


def build_full_hold_map(
    cold_request: dict[str | Path, str],
    active_pins: dict[str | Path, str],
    r27_outer_pins: dict[str | Path, str],
    software_pins: dict[str | Path, str],
    active_software_pins: dict[str | Path, str],
    *,
    active_aliases: int,
) -> tuple[dict[str, str], dict[str, int]]:
    """Derive the complete request from the real cold map and validated map.

    The seven outer-only rows are computed from set differences. Their path
    names are never supplied as a hand-authored allowlist.
    """
    cold = _normalize_map(cold_request, "cold_map_shape_invalid")
    active = _normalize_map(active_pins, "active_map_shape_invalid")
    extra = _normalize_map(r27_outer_pins, "outer_map_shape_invalid")
    software = _normalize_map(software_pins, "software_map_shape_invalid")
    active_software = _normalize_map(active_software_pins, "active_software_shape_invalid")
    _need(len(cold) == EXPECTED_COLD_REQUEST_PATHS, "cold_request_count_mismatch")
    _need(len(active) == EXPECTED_ACTIVE_PATHS, "active_map_count_mismatch")
    _need(len(software) == EXPECTED_SOFTWARE_PATHS, "software_map_count_mismatch")
    _need(software == active_software, "software_map_binding_mismatch")
    _need(type(active_aliases) is int and active_aliases == EXPECTED_ACTIVE_ALIASES, "active_alias_count_mismatch")

    for key in cold.keys() & active.keys():
        _need(cold[key] == active[key], "shared_pin_digest_conflict")
    for key in extra.keys() & active.keys():
        _need(extra[key] == active[key], "outer_pin_digest_conflict")
    for key in extra.keys() & cold.keys():
        _need(extra[key] == cold[key], "cold_outer_digest_conflict")

    cold_missing_active = set(active) - set(cold)
    _need(len(cold_missing_active) == EXPECTED_ACTIVE_ONLY_PATHS, "active_difference_count_mismatch")
    union_outer = dict(cold)
    union_outer.update(extra)
    outer_only = {key: digest for key, digest in union_outer.items() if key not in active}
    _need(len(outer_only) == EXPECTED_OUTER_ONLY_PATHS, "outer_difference_count_mismatch")

    full = dict(active)
    full.update(outer_only)
    _need(len(full) == EXPECTED_FULL_PATHS, "complete_hold_count_mismatch")
    _need(set(full) == set(active) | set(outer_only), "complete_hold_set_mismatch")
    metrics = {
        "cold_request_paths": len(cold),
        "validated_active_paths": len(active),
        "active_missing_from_cold": len(cold_missing_active),
        "outer_only_paths": len(outer_only),
        "complete_public_paths": len(full),
        "software_paths": len(software),
        "active_aliases": active_aliases,
        "review_required_paths": 0,
        "review_required_missing_from_cold": 0,
    }
    return full, metrics


def derive_pinned_r19_active_map(
    payload: dict[str, object],
    *,
    source_reader,
    artifact_reader,
) -> _PinnedR19ActiveMap:
    """Derive the R19 active map from its exact source and payload-bound review.

    This caller-side derivation runs before the unchanged R27 binder. Both the
    source and every packet/review artifact are read through pinned public
    readers; no candidate-supplied map is treated as authoritative.
    """
    _need(type(payload) is dict and type(payload.get("driver")) is dict, "r19_derivation_payload_invalid")
    driver = payload["driver"]
    _need(
        path_key(driver.get("path", "")) == path_key(R19_DRIVER)
        and driver.get("sha256") == R19_DRIVER_SHA256,
        "r19_derivation_source_pin_invalid",
    )
    active_path_value = driver.get("active_path")
    _need(type(active_path_value) is str and ntpath.isabs(active_path_value), "r19_derivation_active_path_invalid")
    active_path = Path(active_path_value)
    _need(callable(source_reader) and callable(artifact_reader), "r19_derivation_readers_missing")
    raw = source_reader(R19_DRIVER, R19_DRIVER_SHA256)
    _need(type(raw) is bytes and sha256(raw) == R19_DRIVER_SHA256, "r19_derivation_source_digest_invalid")
    name = "_r28_r5_source_derived_r19_active_map"
    module = types.ModuleType(name)
    module.__file__ = str(active_path)
    module.__package__ = ""
    module.__cached__ = None
    module.__loader__ = None
    module.__spec__ = importlib.machinery.ModuleSpec(name, loader=None, origin=str(active_path))
    module.__verified_source_sha256__ = R19_DRIVER_SHA256
    try:
        exec(compile(raw, str(active_path), "exec", dont_inherit=True), module.__dict__)
    except (SyntaxError, TypeError, ValueError):
        raise SourceContractError("r19_derivation_source_compile_invalid") from None
    module = _verify_loaded_module(module, raw, active_path, name)

    packet_value = driver.get("packet_dir")
    review_value = driver.get("review_dir")
    packet_pins_value = driver.get("packet_pins")
    review_pins_value = driver.get("review_pins")
    test_path_value = driver.get("test_path")
    test_digest = driver.get("test_sha256")
    _need(
        isinstance(packet_value, (str, os.PathLike))
        and isinstance(review_value, (str, os.PathLike))
        and isinstance(test_path_value, (str, os.PathLike))
        and _valid_hash(test_digest),
        "r19_derivation_artifact_paths_invalid",
    )
    packet_path = Path(packet_value)
    review_path = Path(review_value)
    test_path = Path(test_path_value)
    packet_pins_normalized = _normalize_map(
        packet_pins_value, "r19_derivation_packet_pins_invalid"
    )
    review_pins_normalized = _normalize_map(
        review_pins_value, "r19_derivation_review_pins_invalid"
    )
    packet_pins = dict(packet_pins_value)
    review_pins = dict(review_pins_value)
    _need(
        set(packet_pins_normalized)
        == {
            path_key("source-bundle.zip"),
            path_key("source-index.json"),
            path_key("source-pins.json"),
            path_key("checkpoint.json"),
            path_key("README.md"),
            path_key("qa/qa-summary.json"),
        },
        "r19_derivation_packet_pin_shape_invalid",
    )
    _need(
        set(review_pins_normalized) == {path_key(name) for name in _R19_REVIEW_PIN_FIELDS},
        "r19_derivation_review_pin_shape_invalid",
    )
    _need(
        driver.get("review_readme_sha256") == review_pins.get("README.md"),
        "r19_derivation_readme_binding_invalid",
    )
    _need(
        path_key(packet_path) == path_key(module.DRIVER_PACKET)
        and path_key(review_path) == path_key(module.DRIVER_REVIEW)
        and path_key(test_path) == path_key(module.DRIVER_TEST),
        "r19_derivation_artifact_context_mismatch",
    )
    _need(
        path_key(test_path) == path_key(module.DRIVER_TEST),
        "r19_derivation_test_path_mismatch",
    )
    for folder, mapping in ((packet_path, packet_pins), (review_path, review_pins)):
        for name_part, digest in mapping.items():
            artifact_path = folder / name_part
            raw_artifact = artifact_reader(artifact_path)
            _need(
                type(raw_artifact) is bytes and sha256(raw_artifact) == digest,
                "r19_derivation_artifact_digest_mismatch",
            )
    raw_test = artifact_reader(test_path)
    _need(type(raw_test) is bytes and sha256(raw_test) == test_digest, "r19_derivation_test_digest_invalid")

    module.ROOT_DRIVER_PATH = active_path
    module.ROOT_DRIVER_SHA256 = R19_DRIVER_SHA256
    module.DRIVER_TEST_SHA256 = test_digest
    module.ROOT_DRIVER_REVIEW_READY = True
    module.ROOT_DRIVER_REVIEW_PINS = dict(review_pins)
    module.ROOT_DRIVER_PACKET_PINS = dict(packet_pins)
    module.ROOT_ENABLED = True
    module.ROOT_REVIEWED_ACTIVATION = True
    _need(module._activation_ready() is True, "r19_derivation_activation_fields_invalid")
    projection_names = (
        "ROOT_DRIVER_PATH",
        "ROOT_DRIVER_SHA256",
        "DRIVER_TEST_SHA256",
        "ROOT_DRIVER_REVIEW_READY",
        "ROOT_DRIVER_REVIEW_PINS",
        "ROOT_DRIVER_PACKET_PINS",
        "ROOT_ENABLED",
        "ROOT_REVIEWED_ACTIVATION",
    )
    _accept_module_namespace_stage(
        module,
        {name: module.__dict__[name] for name in projection_names},
        stage="r28_held_source_review_projection",
    )
    _install_module_global_binding(
        module,
        "_read_pin",
        source_reader,
        stage="r28_held_public_source_reader",
    )
    try:
        pins, software, aliases = module._expected_pins()
    except SourceContractError:
        raise
    except BaseException:
        raise SourceContractError("r19_derivation_map_builder_failed") from None
    normalized_pins = _normalize_map(pins, "r19_derivation_public_map_invalid")
    normalized_software = _normalize_map(software, "r19_derivation_software_map_invalid")
    expected_counts = payload.get("counts")
    _need(
        type(expected_counts) is dict
        and expected_counts.get("active_public_paths") == len(normalized_pins) == EXPECTED_ACTIVE_PATHS
        and expected_counts.get("software_paths") == len(normalized_software) == EXPECTED_SOFTWARE_PATHS
        and expected_counts.get("path_aliases") == aliases == EXPECTED_ACTIVE_ALIASES,
        "r19_derivation_counts_invalid",
    )
    for path, digest in normalized_pins.items():
        _need(_valid_hash(digest), "r19_derivation_public_digest_invalid")
        _need(path_key(path) == path, "r19_derivation_public_path_not_canonical")
    for path, digest in normalized_software.items():
        _need(_valid_hash(digest), "r19_derivation_software_digest_invalid")
        _need(path_key(path) == path, "r19_derivation_software_path_not_canonical")
    return _PinnedR19ActiveMap(
        raw=raw,
        path=active_path,
        name=name,
        module=module,
        source_reader=source_reader,
        pins=normalized_pins,
        software=normalized_software,
        aliases=aliases,
        packet_path=packet_path,
        packet_pins=packet_pins,
        review_path=review_path,
        review_pins=review_pins,
        test_path=test_path,
        test_digest=test_digest,
    )


def validate_active_map_candidate(
    derivation: object,
    active_pins: object,
    active_software_pins: object,
    active_aliases: object,
) -> tuple[dict[str, str], dict[str, str], int]:
    """Reject any caller map that diverges from the held production builder."""
    _need(type(derivation) is _PinnedR19ActiveMap, "r19_derivation_unbound")
    module = derivation.module
    _assert_module_contract(module)
    _need(
        type(derivation.raw) is bytes
        and sha256(derivation.raw) == R19_DRIVER_SHA256
        and path_key(derivation.path) == path_key(module.ROOT_DRIVER_PATH)
        and module.__name__ == derivation.name
        and module.__file__ == str(derivation.path)
        and getattr(getattr(module, "__spec__", None), "origin", None) == str(derivation.path)
        and getattr(module, "__verified_source_sha256__", None) == R19_DRIVER_SHA256
        and module._read_pin is derivation.source_reader
        and _module_code_fingerprint(module) == derivation.module_code_fingerprint
        and _code_fingerprint(module._expected_pins.__code__) == derivation.expected_pins_fingerprint
        and _global_dependency_names(module, ("_expected_pins",)) == derivation.global_dependency_names
        and _module_global_dependency_fingerprint(module, derivation.global_dependency_names)
        == derivation.global_dependency_fingerprint,
        "r19_derivation_source_identity_changed",
    )
    _need(
        all(module.__dict__.get(name) is value for name, value in derivation.global_dependency_objects),
        "r19_derivation_global_object_identity_changed",
    )
    _need(
        module._activation_ready() is True
        and path_key(module.DRIVER_PACKET) == path_key(derivation.packet_path)
        and path_key(module.DRIVER_REVIEW) == path_key(derivation.review_path)
        and module.ROOT_DRIVER_SHA256 == R19_DRIVER_SHA256
        and module.DRIVER_TEST_SHA256 == derivation.test_digest
        and module.ROOT_DRIVER_PACKET_PINS == derivation.packet_pins
        and module.ROOT_DRIVER_REVIEW_PINS == derivation.review_pins,
        "r19_derivation_context_changed",
    )
    try:
        fresh_pins, fresh_software, fresh_aliases = module._expected_pins()
    except SourceContractError:
        raise
    except BaseException:
        raise SourceContractError("r19_derivation_recheck_failed") from None
    expected_pins = _normalize_map(fresh_pins, "r19_derivation_recheck_map_invalid")
    expected_software = _normalize_map(fresh_software, "r19_derivation_recheck_software_invalid")
    _need(
        expected_pins == derivation.pins
        and expected_software == derivation.software
        and fresh_aliases == derivation.aliases,
        "r19_derivation_recheck_changed",
    )
    candidate_pins = _normalize_map(active_pins, "active_map_candidate_shape_invalid")
    candidate_software = _normalize_map(active_software_pins, "active_software_candidate_shape_invalid")
    _need(candidate_pins == expected_pins, "active_map_candidate_source_mismatch")
    _need(candidate_software == expected_software, "active_software_candidate_source_mismatch")
    _need(
        type(active_aliases) is int and active_aliases == fresh_aliases,
        "active_alias_candidate_source_mismatch",
    )
    return expected_pins, expected_software, fresh_aliases


def _verify_r19_runtime_builder(
    module: types.ModuleType,
    derivation: _PinnedR19ActiveMap,
    expected_reader,
    expected_alias: str,
    active_context: dict[str, object],
    invoke: types.ModuleType,
    builder: types.FunctionType,
) -> tuple[dict[str, str], dict[str, str], int]:
    """Bind the production active module to the independently held R19 map."""
    _need(type(module) is types.ModuleType, "active_r19_module_invalid")
    _need(type(derivation) is _PinnedR19ActiveMap, "active_r19_derivation_invalid")
    _need(type(expected_alias) is str and module.__name__ == expected_alias,
          "active_r19_stage_alias_invalid")
    _need(
        module.__file__ == str(derivation.path)
        and getattr(getattr(module, "__spec__", None), "origin", None) == str(derivation.path)
        and getattr(module, "__verified_source_sha256__", None) == R19_DRIVER_SHA256
        and sha256(derivation.raw) == R19_DRIVER_SHA256,
        "active_r19_source_origin_invalid",
    )
    _need(
        type(builder) is types.FunctionType
        and builder.__globals__ is module.__dict__
        and builder.__module__ == module.__name__
        and builder.__name__ == "_expected_pins"
        and builder.__qualname__ == "_expected_pins"
        and _code_fingerprint(builder.__code__) == derivation.expected_pins_fingerprint
        and builder.__defaults__ is None
        and builder.__kwdefaults__ is None
        and builder.__annotations__ == {},
        "active_r19_original_map_builder_function_invalid",
    )
    record = _bound_invoke_record(invoke, derivation)
    candidate_pins, candidate_software, candidate_aliases = validate_active_map_candidate(
        derivation,
        dict(record["active_rows"]),
        dict(record["software_rows"]),
        record["aliases"],
    )
    _need(
        candidate_pins == dict(record["active_rows"])
        and candidate_software == dict(record["software_rows"])
        and candidate_aliases == record["aliases"],
        "active_r19_map_bound_rows_changed",
    )
    driver_projection = record.get("driver_projection")
    _need(
        type(driver_projection) is tuple and len(driver_projection) == 10,
        "active_r19_driver_projection_missing",
    )
    (
        driver_path,
        driver_digest,
        test_path,
        test_digest,
        packet_path,
        packet_pin_rows,
        review_path,
        review_pin_rows,
        readme_digest,
        active_path,
    ) = driver_projection
    _need(
        driver_path == path_key(R19_DRIVER)
        and driver_digest == R19_DRIVER_SHA256
        and test_path == path_key(derivation.test_path)
        and test_digest == derivation.test_digest
        and packet_path == path_key(derivation.packet_path)
        and dict(packet_pin_rows) == derivation.packet_pins
        and review_path == path_key(derivation.review_path)
        and dict(review_pin_rows) == derivation.review_pins
        and readme_digest == derivation.review_pins.get("README.md")
        and active_path == path_key(derivation.path),
        "active_r19_driver_projection_not_derivation_bound",
    )
    expected_projection = {
        "ROOT_DRIVER_PATH": derivation.path,
        "ROOT_DRIVER_SHA256": driver_digest,
        "DRIVER_TEST_SHA256": test_digest,
        "DRIVER_PACKET": derivation.packet_path,
        "ROOT_DRIVER_PACKET_PINS": dict(packet_pin_rows),
        "DRIVER_REVIEW": derivation.review_path,
        "ROOT_DRIVER_REVIEW_PINS": dict(review_pin_rows),
        "ROOT_ENABLED": True,
        "ROOT_REVIEWED_ACTIVATION": True,
        "ROOT_DRIVER_REVIEW_READY": True,
    }
    for name, expected_value in expected_projection.items():
        actual_value = module.__dict__.get(name)
        if name in {"ROOT_DRIVER_PATH", "DRIVER_PACKET", "DRIVER_REVIEW"}:
            matches = isinstance(actual_value, (str, os.PathLike)) and (
                path_key(actual_value) == path_key(expected_value)
            )
        elif name in {"ROOT_DRIVER_PACKET_PINS", "ROOT_DRIVER_REVIEW_PINS"}:
            matches = type(actual_value) is dict and actual_value == expected_value
        else:
            matches = type(actual_value) is type(expected_value) and actual_value == expected_value
        _need(matches, "active_r19_driver_projection_changed:" + name)
    names = derivation.global_dependency_names
    _need(set(names) <= set(module.__dict__), "active_r19_map_builder_globals_missing")
    expected_globals = dict(derivation.global_dependency_fingerprint)
    for name, expected_value in expected_projection.items():
        if name in expected_globals:
            expected_globals[name] = _global_value_fingerprint(expected_value, module)
    _need("_read_pin" in names and module.__dict__.get("_read_pin") is expected_reader,
          "active_r19_reader_origin_invalid")
    current = _module_global_dependency_fingerprint(
        module,
        names,
        overrides={"_read_pin": derivation.module._read_pin, "_need": derivation.module._need},
        override_owners={"_read_pin": derivation.module, "_need": derivation.module},
    )
    current_globals = dict(current)
    changed_globals = tuple(
        name for name in names if current_globals.get(name) != expected_globals.get(name)
    )
    _need(
        current_globals == expected_globals,
        "active_r19_map_builder_global_value_changed:" + ",".join(changed_globals),
    )
    _accept_module_namespace_stage(
        module,
        {name: module.__dict__[name] for name in expected_projection},
        stage="r28_r2_active_driver_projection",
    )
    try:
        pins, software, aliases = builder()
    except SourceContractError:
        raise
    except BaseException:
        raise SourceContractError("active_r19_map_builder_execution_failed") from None
    _need(
        _normalize_map(pins, "active_r19_map_builder_rows_invalid") == candidate_pins
        and _normalize_map(software, "active_r19_map_builder_software_invalid") == candidate_software
        and aliases == candidate_aliases,
        "active_r19_map_builder_rows_changed",
    )
    active_context["active_r19_map_binding"] = {
        "verified": True,
        "public_paths": len(derivation.pins),
        "software_rows": len(derivation.software),
        "aliases": derivation.aliases,
    }
    return pins, software, aliases


def _install_r19_map_verification_hook(
    module: types.ModuleType,
    derivation: _PinnedR19ActiveMap,
    expected_reader,
    expected_alias: str,
    active_context: dict[str, object],
    invoke: types.ModuleType,
) -> None:
    """Bind a source-owned wrapper that verifies the real builder at call time.

    R2 sets the held R19 activation fields after ``load`` returns.  The wrapper
    therefore verifies at the actual production ``_expected_pins`` call, once
    those fields have been installed, and delegates to the unchanged builder.
    """
    _assert_module_contract(module)
    original_builder = module.__dict__.get("_expected_pins")
    _need(
        type(original_builder) is types.FunctionType
        and original_builder.__globals__ is module.__dict__
        and original_builder.__module__ == module.__name__
        and original_builder.__name__ == "_expected_pins"
        and _code_fingerprint(original_builder.__code__)
        == derivation.expected_pins_fingerprint,
        "active_r19_map_builder_hook_target_invalid",
    )
    verifier = _verify_r19_runtime_builder

    def expected_pins_with_r4_binding():
        active_context["r3_last_stage"] = "r19_builder_verification"
        result = verifier(
            module,
            derivation,
            expected_reader,
            expected_alias,
            active_context,
            invoke,
            original_builder,
        )
        active_context["r3_last_stage"] = "r19_builder_bound"
        return result

    wrapper = types.FunctionType(
        expected_pins_with_r4_binding.__code__,
        module.__dict__,
        original_builder.__name__,
        original_builder.__defaults__,
        expected_pins_with_r4_binding.__closure__,
    )
    wrapper.__kwdefaults__ = original_builder.__kwdefaults__
    wrapper.__annotations__ = dict(original_builder.__annotations__)
    wrapper.__dict__.update(original_builder.__dict__)
    wrapper.__module__ = original_builder.__module__
    wrapper.__qualname__ = original_builder.__qualname__
    expected_closure = {
        "active_context": active_context,
        "derivation": derivation,
        "expected_alias": expected_alias,
        "expected_reader": expected_reader,
        "invoke": invoke,
        "module": module,
        "original_builder": original_builder,
        "verifier": verifier,
    }
    _need(
        set(wrapper.__code__.co_freevars)
        == set(expected_closure)
        and wrapper.__globals__ is module.__dict__
        and all(
            cell.cell_contents is expected_closure[name]
            for name, cell in zip(wrapper.__code__.co_freevars, wrapper.__closure__ or ())
        ),
        "active_r19_map_builder_hook_closure_invalid",
    )
    module.__dict__["_expected_pins"] = wrapper
    _advance_module_contract(
        module,
        {"_expected_pins": wrapper},
        stage="r28_source_bound_active_map_verification_hook",
    )
    active_context["r19_map_hook_provenance"] = {
        "source_module_path": str(Path(__file__)),
        "source_function": "_install_r19_map_verification_hook.expected_pins_with_r4_binding",
        "source_sha256": globals().get("__verified_source_sha256__"),
        "target_source_sha256": R19_DRIVER_SHA256,
        "target_function": "_expected_pins",
        "original_code_fingerprint": derivation.expected_pins_fingerprint,
        "wrapper_code_fingerprint": _code_fingerprint(wrapper.__code__),
        "original_builder_delegated": True,
        "verification_timing": "production_r2_expected_pins_call",
    }


def _nested_code(
    parent: types.FunctionType | types.CodeType,
    nested_name: str,
) -> types.CodeType:
    parent_code = parent.__code__ if type(parent) is types.FunctionType else parent
    _need(type(parent_code) is types.CodeType, "r27_wrapper_parent_code_invalid")
    matches = [
        item
        for item in parent_code.co_consts
        if type(item) is types.CodeType and item.co_name == nested_name
    ]
    _need(
        len(matches) == 1,
        "r27_wrapper_source_code_ambiguous:" + parent_code.co_name + ":" + nested_name,
    )
    return matches[0]


def _cell_map(function: types.FunctionType) -> dict[str, object]:
    closure = function.__closure__ or ()
    _need(len(closure) == len(function.__code__.co_freevars), "r27_wrapper_closure_shape_invalid")
    try:
        return dict(zip(function.__code__.co_freevars, (cell.cell_contents for cell in closure)))
    except ValueError:
        raise SourceContractError("r27_wrapper_empty_closure") from None


def _same_expected_cell(actual: object, expected: object) -> bool:
    if type(expected) in (dict, list, set, types.FunctionType, types.ModuleType):
        return actual is expected
    return type(actual) is type(expected) and actual == expected


def _generated_wrapper_matches(
    function: object,
    parent: types.FunctionType | types.CodeType,
    nested_name: str,
    *,
    globals_owner: types.ModuleType,
    expected_cells: dict[str, object],
    defaults: tuple[object, ...] | None,
    annotations: dict[str, object] | None = None,
) -> bool:
    if type(function) is not types.FunctionType:
        return False
    code = _nested_code(parent, nested_name)
    if not (
        function.__code__ is code
        and function.__globals__ is globals_owner.__dict__
        and function.__module__ == globals_owner.__name__
        and function.__name__ == code.co_name
        and function.__qualname__ == code.co_qualname
        and function.__defaults__ == defaults
        and function.__kwdefaults__ is None
        and function.__annotations__ == ({} if annotations is None else annotations)
        and function.__dict__ == {}
    ):
        return False
    cells = _cell_map(function)
    cell_names_match = set(cells) == set(expected_cells)
    cell_values_match = cell_names_match and all(
        _same_expected_cell(cells[name], value) for name, value in expected_cells.items()
    )
    return cell_values_match


def _seed_r27_cuv2_module_contract(
    module: types.ModuleType,
    raw: bytes,
    path: Path,
    name: str,
    invoke: types.ModuleType,
    context: dict[str, object],
) -> None:
    """Bind R27's two known CUV2 wrappers to exact held source functions."""
    _assert_module_contract(invoke)
    digest = sha256(raw)
    _need(
        type(module) is types.ModuleType
        and module.__name__ == name
        and getattr(module, "__file__", None) == str(path)
        and getattr(getattr(module, "__spec__", None), "origin", None) == str(path)
        and digest == CUV2_SHA256
        and getattr(module, "__verified_source_sha256__", None) == digest,
        "r27_cuv2_module_origin_or_pin_invalid",
    )
    _need(id(module) not in _VERIFIED_MODULE_CONTRACTS, "r27_cuv2_module_already_registered")
    baseline = _reference_module(raw, path, name)
    expected_names = _module_function_names(baseline)
    _need(_module_function_names(module) == expected_names, "r27_cuv2_function_set_invalid")
    namespace_names = _verify_source_namespace(module, baseline)
    replacements = {"check", "held_public_sources"}
    _need(replacements <= expected_names, "r27_cuv2_wrapper_targets_missing")
    for function_name in sorted(expected_names - replacements):
        _need(
            _function_matches_reference(
                getattr(module, function_name),
                getattr(baseline, function_name),
                actual_module=module,
            ),
            "r27_cuv2_unmodified_function_changed:" + function_name,
        )

    actual_check = getattr(module, "check", None)
    check_cells = _cell_map(actual_check)
    original_check = check_cells.get("original")
    _need(
        _function_matches_reference(original_check, baseline.check, actual_module=module),
        "r27_cuv2_check_original_unbound",
    )
    _need(
        _generated_wrapper_matches(
            actual_check,
            invoke._wrap_reason_function,
            "observed",
            globals_owner=invoke,
            expected_cells={
                "original": original_check,
                "context": context,
                "role": "cuv2",
                "argument_name": "code",
            },
            defaults=None,
        ),
        "r27_cuv2_check_wrapper_invalid",
    )
    adaptation_source = context.get("r27_original_install_adaptation")
    r2 = context.get("r2_module_under_test")
    diagnostic_codes = context.get("diagnostic_source_codes")
    captured_holder = context.get("captured_cuv2_source_factory")
    actual_hold = getattr(module, "held_public_sources", None)
    hold_cells = _cell_map(actual_hold)
    original_hold = hold_cells.get("original_held_public_sources")
    _need(
        type(adaptation_source) is types.FunctionType
        and adaptation_source.__globals__ is invoke.__dict__
        and adaptation_source.__name__ == "_install_adaptation",
        "r27_cuv2_adaptation_context_invalid",
    )
    _need(type(r2) is types.ModuleType, "r27_cuv2_adaptation_r2_unbound")
    _need(type(diagnostic_codes) is dict, "r27_cuv2_diagnostic_map_unbound")
    _need(captured_holder is original_hold, "r27_cuv2_captured_holder_identity_invalid")
    holder_issue = _function_reference_issue(
        captured_holder,
        baseline.held_public_sources,
        actual_module=module,
    )
    _need(holder_issue is None, "r27_cuv2_captured_holder_source_invalid:" + str(holder_issue))
    _need(
        _function_matches_reference(original_hold, baseline.held_public_sources, actual_module=module),
        "r27_cuv2_hold_original_unbound",
    )
    adapted_load_code = _nested_code(adaptation_source, "adapted_load")
    _need(
        _generated_wrapper_matches(
            actual_hold,
            adapted_load_code,
            "adapted_hold",
            globals_owner=invoke,
            expected_cells={
                "context": context,
                "original_held_public_sources": original_hold,
                "r2": r2,
            },
            defaults=None,
            annotations={
                "pins": "dict[str | Path, str]",
                "software": "dict[str | Path, str]",
            },
        ),
        "r27_cuv2_hold_wrapper_invalid",
    )
    module.__r28_verified_source_sha256__ = digest
    module.__r28_verified_path__ = str(path)
    builtin_names = _module_builtin_contract(module, raw)
    _VERIFIED_MODULE_CONTRACTS[id(module)] = {
        "module": module,
        "path": str(path),
        "source_sha256": digest,
        "builtin_mapping": module.__dict__.get("__builtins__"),
        "builtin_names": builtin_names,
        "functions": {
            function_name: _function_contract(getattr(module, function_name))
            for function_name in sorted(expected_names)
        },
        "global_bindings": {},
        "namespace_names": namespace_names,
        "namespace": _module_namespace_fingerprint(module, namespace_names),
        "stages": ("r28_compiled_cuv2_baseline",),
    }
    _advance_module_contract(
        module,
        {"check": actual_check, "held_public_sources": actual_hold},
        stage="r27_source_bound_cuv2_adaptation",
    )


def _attest_r27_r2_adaptation(
    r2: types.ModuleType,
    invoke: types.ModuleType,
    context: dict[str, object],
    adaptation_source: types.FunctionType,
) -> None:
    """Validate R27's known R2 parser and diagnostic-adapter transforms."""
    _assert_module_contract(invoke)
    record = _VERIFIED_MODULE_CONTRACTS.get(id(r2))
    _need(
        type(record) is dict
        and record.get("module") is r2
        and record.get("source_sha256") == R2_GLUE_SHA256
        and record.get("path") == str(R2_GLUE_PATH),
        "r27_r2_stage_source_unbound",
    )
    _need(
        type(adaptation_source) is types.FunctionType
        and adaptation_source.__globals__ is invoke.__dict__
        and adaptation_source.__name__ == "_install_adaptation",
        "r27_r2_adaptation_function_unbound",
    )
    prior = record["functions"]
    raw = context.get("r2_raw")
    _need(type(raw) is bytes and sha256(raw) == R2_GLUE_SHA256, "r27_r2_stage_bytes_unbound")
    baseline = _reference_module(raw, R2_GLUE_PATH, r2.__name__)
    expected_packet_pins = {
        name: invoke.DRIVER_PACKET_PINS[name] for name in invoke._PACKET_REQUIRED
    }
    expected_review_pins = {
        name: invoke.DRIVER_REVIEW_PINS[name] for name in _R2_REVIEW_PIN_FIELDS
    }
    expected_r2_globals = {
        "SOURCE": invoke.DRIVER,
        "SOURCE_SHA": invoke.DRIVER_SHA256,
        "ACTIVE_SOURCE": invoke._driver_active_path(),
        "TEST": invoke.DRIVER_TEST,
        "TEST_SHA": invoke.DRIVER_TEST_SHA256,
        "PACKET": invoke.DRIVER_PACKET,
        "PACKET_PINS": expected_packet_pins,
        "REVIEW": invoke.DRIVER_REVIEW,
        "ROOT_REVIEW_PINS": expected_review_pins,
        "ROOT_REVIEW_README_SHA": invoke.DRIVER_REVIEW_PINS["README.md"],
        "ROOT_ACTUAL_ENABLED": True,
        "ROOT_REVIEW_READY": True,
        "_ROOT_SELF_SHA256": R2_GLUE_SHA256,
        "CONTROL": invoke.ROOT_CONTROL,
        "OUT": invoke.ROOT_PRECHECK_OUTPUT if context.get("mode") == "precheck" else invoke.ROOT_OUTPUT,
        "APPLICATION_WAIT_SECONDS": invoke.OUTER_WAIT_SECONDS,
        "PARENT_DEADLINE_MONOTONIC": invoke.PARENT_DEADLINE_MONOTONIC,
        "PARENT_DEADLINE_DOMAIN": invoke.PARENT_DEADLINE_DOMAIN,
        "INERT_PIN_COUNT": invoke.R2_INERT_DRIVER_PIN_COUNT,
        "ACTIVE_PIN_COUNT": invoke.ACTIVE_DRIVER_PUBLIC_PATH_COUNT,
        "ACTIVE_ALIAS_COUNT": invoke.ACTIVE_DRIVER_ALIAS_COUNT,
    }
    r2_namespace_names = _module_namespace_names(baseline)
    changed_r2_names = frozenset(
        name
        for name in expected_r2_globals
        if name in r2_namespace_names
        and name in r2.__dict__
        and name in baseline.__dict__
        and _namespace_value_fingerprint(
            r2.__dict__[name], r2, include_identity=False
        )
        != _namespace_value_fingerprint(
            baseline.__dict__[name], baseline, include_identity=False
        )
    )
    _verify_source_namespace(
        r2,
        baseline,
        allowed_differences=changed_r2_names,
    )
    for name, expected_value in expected_r2_globals.items():
        actual_value = r2.__dict__.get(name, _MISSING_NAMESPACE_VALUE)
        if isinstance(expected_value, Path):
            matches = isinstance(actual_value, Path) and path_key(actual_value) == path_key(expected_value)
        elif type(expected_value) is dict:
            matches = type(actual_value) is dict and actual_value == expected_value
        else:
            matches = type(actual_value) is type(expected_value) and actual_value == expected_value
        _need(matches, "r27_r2_global_projection_changed:" + name)
    _accept_module_namespace_stage(
        r2,
        {name: r2.__dict__[name] for name in expected_r2_globals},
        stage="r27_r2_production_binding_projection",
    )

    baseline_main = baseline.main
    old_schema = invoke._R2_PARENT_SCHEMA_V1
    new_schema = invoke._R5_PARENT_SCHEMA_V1
    indices = [
        index
        for index, value in enumerate(baseline_main.__code__.co_consts)
        if type(value) is str and value == old_schema
    ]
    _need(len(indices) == 1, "r27_r2_schema_literal_invalid")
    constants = list(baseline_main.__code__.co_consts)
    constants[indices[0]] = new_schema
    expected_main_code = baseline_main.__code__.replace(co_consts=tuple(constants))
    actual_main = getattr(r2, "main", None)
    main_proxy = types.FunctionType(
        expected_main_code,
        r2.__dict__,
        baseline_main.__name__,
        baseline_main.__defaults__,
        baseline_main.__closure__,
    )
    main_proxy.__module__ = r2.__name__
    main_proxy.__qualname__ = baseline_main.__qualname__
    main_proxy.__kwdefaults__ = baseline_main.__kwdefaults__
    main_proxy.__annotations__ = dict(baseline_main.__annotations__)
    main_proxy.__dict__.update(baseline_main.__dict__)
    _need(
        type(actual_main) is types.FunctionType
        and actual_main.__globals__ is r2.__dict__
        and _code_fingerprint(actual_main.__code__) == _code_fingerprint(expected_main_code)
        and actual_main.__defaults__ == baseline_main.__defaults__
        and actual_main.__kwdefaults__ == baseline_main.__kwdefaults__
        and actual_main.__closure__ == baseline_main.__closure__,
        "r27_r2_schema_bridge_function_invalid",
    )

    original_need = prior["need"]["function"]
    expected_need_cells = {"original": original_need, "context": context}
    _need(
        _generated_wrapper_matches(
            getattr(r2, "need", None),
            invoke._wrap_r2_need,
            "observed",
            globals_owner=invoke,
            expected_cells=expected_need_cells,
            defaults=("root_public_contract",),
        ),
        "r27_r2_need_wrapper_invalid",
    )

    diagnostic_codes = context.get("diagnostic_source_codes")
    _need(type(diagnostic_codes) is dict, "r27_r2_diagnostic_code_map_invalid")
    adapted_load = getattr(r2, "load", None)
    _need(
        _generated_wrapper_matches(
            adapted_load,
            adaptation_source,
            "adapted_load",
            globals_owner=invoke,
            expected_cells={
                "context": context,
                "original_load": prior["load"]["function"],
                "r2": r2,
                "r2_codes": diagnostic_codes,
            },
            defaults=None,
            annotations={"raw": "bytes", "path": "Path", "name": "str"},
        ),
        "r27_r2_load_wrapper_invalid",
    )
    adapted_save = getattr(r2, "save_new", None)
    _need(
        _generated_wrapper_matches(
            adapted_save,
            adaptation_source,
            "adapted_save",
            globals_owner=invoke,
            expected_cells={
                "context": context,
                "original_save": prior["save_new"]["function"],
                "r2": r2,
            },
            defaults=None,
            annotations={"path": "Path", "value": "dict[str, object]", "return": "None"},
        ),
        "r27_r2_save_wrapper_invalid",
    )

    _advance_module_contract(
        r2,
        {
            "main": main_proxy,
            "need": r2.need,
            "load": adapted_load,
            "save_new": adapted_save,
        },
        stage="r27_source_bound_r2_adaptation",
    )


def _attest_r27_active_driver_stage(
    module: types.ModuleType,
    invoke: types.ModuleType,
    active_context: dict[str, object],
) -> None:
    """Validate R27's diagnostic wrappers against its held source functions."""
    _assert_module_contract(invoke)
    module_record = _VERIFIED_MODULE_CONTRACTS.get(id(module))
    _need(
        type(module_record) is dict
        and module_record.get("module") is module
        and module_record.get("source_sha256") == R19_DRIVER_SHA256
        and module_record.get("path") == getattr(module, "__file__", None),
        "r27_active_driver_prior_source_unbound",
    )
    prior = module_record["functions"]

    def wrapper_source_valid(function, parent, nested_name):
        code = _nested_code(parent, nested_name)
        return (
            type(function) is types.FunctionType
            and _code_fingerprint(function.__code__) == _code_fingerprint(code)
            and function.__globals__ is invoke.__dict__
            and function.__module__ == invoke.__name__
            and function.__name__ == code.co_name
            and function.__qualname__ == code.co_qualname
            and function.__annotations__ == {}
            and function.__dict__ == {}
        )

    wrappers: dict[str, types.FunctionType] = {}
    need_wrapper = getattr(module, "_need", None)
    _need(
        wrapper_source_valid(need_wrapper, invoke._wrap_reason_function, "observed")
        and need_wrapper.__defaults__ is None
        and need_wrapper.__kwdefaults__ is None,
        "r27_need_wrapper_source_invalid",
    )
    need_cells = _cell_map(need_wrapper)
    need_original = prior["_need"]["function"]
    _need(
        set(need_cells) == {"original", "context", "role", "argument_name"},
        "r27_need_wrapper_closure_shape_invalid",
    )
    _need(need_cells["original"] is need_original, "r27_need_wrapper_original_binding_invalid")
    _need(need_cells["context"] is active_context, "r27_need_wrapper_context_binding_invalid")
    _need(need_cells["role"] == "driver", "r27_need_wrapper_role_binding_invalid")
    _need(need_cells["argument_name"] == "code", "r27_need_wrapper_argument_binding_invalid")
    wrappers["_need"] = need_wrapper

    nested_validator_code = _nested_code(invoke._active_driver_loaded, "observed_validator")
    for attribute in (
        "_validate_candidate_review",
        "_validate_r33_candidate_review",
        "_validate_r28_lineage",
    ):
        wrapper = getattr(module, attribute, None)
        _need(
            wrapper_source_valid(wrapper, invoke._active_driver_loaded, "observed_validator")
            and wrapper.__code__ is nested_validator_code
            and wrapper.__defaults__ is None
            and type(wrapper.__kwdefaults__) is dict
            and set(wrapper.__kwdefaults__) == {"_validator"},
            "r27_validator_wrapper_source_invalid",
        )
        cells = _cell_map(wrapper)
        expected_original = prior[attribute]["function"]
        _need(
            wrapper.__kwdefaults__["_validator"] is expected_original
            and set(cells) == {"context"}
            and cells["context"] is active_context,
            "r27_validator_wrapper_binding_invalid",
        )
        wrappers[attribute] = wrapper

    aggregate = getattr(module, "_validate_driver_review", None)
    _need(
        type(aggregate) is types.FunctionType
        and getattr(module, "_validate_r32_candidate_review", None) is aggregate,
        "r27_aggregate_alias_invalid",
    )
    if "_validate_r32_candidate_review" in prior:
        wrappers["_validate_r32_candidate_review"] = aggregate
    else:
        pass

    driver_main = active_context.get("fake_active_main")
    main_wrapper = getattr(module, "main", None)
    _need(
        callable(driver_main)
        and wrapper_source_valid(main_wrapper, invoke._active_driver_loaded, "observed_driver_main")
        and main_wrapper.__defaults__ is None
        and main_wrapper.__kwdefaults__ is None,
        "r27_main_wrapper_source_invalid",
    )
    main_cells = _cell_map(main_wrapper)
    _need(
        set(main_cells) == {"context", "driver_main"}
        and main_cells["context"] is active_context
        and main_cells["driver_main"] is driver_main,
        "r27_main_wrapper_binding_invalid",
    )
    wrappers["main"] = main_wrapper

    additions = {}
    replacements = {}
    for name, function in wrappers.items():
        if name in prior:
            replacements[name] = function
        else:
            additions[name] = function
    if "_validate_r32_candidate_review" not in prior:
        additions["_validate_r32_candidate_review"] = aggregate
    _advance_module_contract(
        module,
        replacements,
        additions,
        stage="r27_source_bound_active_driver_wrappers",
    )


def _seed_r27_active_driver_module_contract(
    module: types.ModuleType,
    path: Path,
    name: str,
    invoke: types.ModuleType,
    context: dict[str, object],
) -> None:
    """Check the active module's held source and R27-owned global projection."""
    _assert_module_contract(invoke)
    raw = context.get("active_driver_raw")
    digest = sha256(raw) if type(raw) is bytes else None
    _need(
        type(raw) is bytes
        and digest == R19_DRIVER_SHA256
        and module.__name__ == name
        and module.__file__ == str(path)
        and getattr(getattr(module, "__spec__", None), "origin", None) == str(path)
        and getattr(module, "__verified_source_sha256__", None) == digest,
        "r27_active_driver_source_origin_invalid",
    )
    _need(id(module) not in _VERIFIED_MODULE_CONTRACTS, "r27_active_driver_module_already_registered")
    baseline = _reference_module(raw, path, name)
    baseline_names = _module_function_names(baseline)
    expected_values = {
        "DRIVER_REVIEW": invoke.DRIVER_REVIEW,
        "ROOT_DRIVER_PATH": invoke._driver_active_path(),
        "CONTROL": invoke.ROOT_DRIVER_CONTROL,
        "SCRATCH": invoke.ROOT_DRIVER_SCRATCH,
        "PROGRESS_PATH": invoke.ROOT_DRIVER_CONTROL / module.PROGRESS_NAME,
    }
    source_namespace_names = _module_namespace_names(baseline)
    changed_source_names = frozenset(
        name
        for name, expected_value in expected_values.items()
        if name in source_namespace_names
        and name in baseline.__dict__
        and name in module.__dict__
        and _namespace_value_fingerprint(
            module.__dict__[name], module, include_identity=False
        )
        != _namespace_value_fingerprint(
            baseline.__dict__[name], baseline, include_identity=False
        )
    )
    namespace_names = _verify_source_namespace(
        module,
        baseline,
        allowed_differences=changed_source_names,
    )
    _need(source_namespace_names == namespace_names, "r27_active_driver_namespace_names_changed")
    active_alias = "_validate_r32_candidate_review"
    expected_names = baseline_names | {active_alias}
    _need(_module_function_names(module) == expected_names, "r27_active_driver_function_set_invalid")
    wrappers = {
        "_need",
        "_validate_candidate_review",
        "_validate_r33_candidate_review",
        "_validate_r28_lineage",
        "main",
    }
    _need(wrappers <= baseline_names, "r27_active_driver_wrapper_targets_missing")
    replacement_targets: dict[str, types.FunctionType] = {}
    need_wrapper = getattr(module, "_need", None)
    need_original = _cell_map(need_wrapper).get("original")
    need_issue = _function_reference_issue(
        need_original, baseline._need, actual_module=module
    )
    _need(
        type(need_original) is types.FunctionType and need_issue is None,
        "r27_active_driver_original_need_unbound:" + str(need_issue),
    )
    replacement_targets["_need"] = need_original
    for function_name in (
        "_validate_candidate_review",
        "_validate_r33_candidate_review",
        "_validate_r28_lineage",
    ):
        wrapper = getattr(module, function_name, None)
        kwdefaults = getattr(wrapper, "__kwdefaults__", None)
        original = (
            kwdefaults.get("_validator")
            if type(kwdefaults) is dict and set(kwdefaults) == {"_validator"}
            else None
        )
        issue = _function_reference_issue(
            original, getattr(baseline, function_name), actual_module=module
        )
        _need(
            type(original) is types.FunctionType and issue is None,
            "r27_active_driver_original_validator_unbound:" + function_name + ":" + str(issue),
        )
        replacement_targets[function_name] = original
    # The source-fake main wrapper deliberately captures fake_active_main,
    # replacing the source main before this stage.  Bind that slot to the
    # separately compiled exact source reference; _attest below validates
    # the wrapper's exact R27 code and fake-main closure.
    replacement_targets["main"] = baseline.main
    for function_name in sorted(baseline_names - wrappers - {active_alias}):
        _need(
            _function_matches_reference(
                getattr(module, function_name),
                getattr(baseline, function_name),
                actual_module=module,
            ),
            "r27_active_driver_unmodified_function_changed:" + function_name,
        )
    _need(
        getattr(module, active_alias, None) is getattr(module, "_validate_driver_review", None),
        "r27_active_driver_aggregate_alias_invalid",
    )

    for attribute, expected_value in expected_values.items():
        actual_value = module.__dict__.get(attribute)
        _need(
            actual_value is expected_value if attribute == "DRIVER_REVIEW" else actual_value == expected_value,
            "r27_active_driver_global_projection_invalid:" + attribute,
        )

    replacement_names = wrappers | ({active_alias} if active_alias in baseline_names else set())
    builtin_names = _module_builtin_contract(module, raw)
    _VERIFIED_MODULE_CONTRACTS[id(module)] = {
        "module": module,
        "path": str(path),
        "source_sha256": digest,
        "builtin_mapping": module.__dict__.get("__builtins__"),
        "builtin_names": builtin_names,
        "functions": {
            function_name: _function_contract(
                replacement_targets[function_name]
                if function_name in replacement_names
                else getattr(module, function_name)
            )
            for function_name in sorted(baseline_names)
        },
        "global_bindings": {
            attribute: module.__dict__[attribute]
            for attribute in sorted(expected_values)
        },
        "namespace_names": namespace_names,
        "namespace": _module_namespace_fingerprint(module, namespace_names),
        "stages": ("r28_compiled_active_driver_baseline",),
    }
    module.__r28_verified_source_sha256__ = digest
    module.__r28_verified_path__ = str(path)


def bind_child_activation_with_production_map(
    invoke: types.ModuleType,
    payload: dict[str, object],
    *,
    derivation: _PinnedR19ActiveMap,
    active_pins: dict[str | Path, str],
    active_software_pins: dict[str | Path, str],
    active_aliases: int,
    artifact_reader,
    source_reader=None,
) -> tuple[dict[str, object], dict[str, str], dict[str, str], int]:
    """Run the unchanged R27 binder and bind its result to a source-derived map.

    The source-derived module is rechecked, and each caller-supplied map row is
    compared to a fresh call to its exact production ``_expected_pins`` code.
    R27 then runs its own unchanged validator and reports its validated counts.
    """
    active, software, aliases = validate_active_map_candidate(
        derivation, active_pins, active_software_pins, active_aliases
    )
    install_verified_module_reuse(invoke, source_reader=source_reader)
    binding = invoke.bind_child_activation(payload, artifact_reader=artifact_reader)
    _need(binding.get("activation_enabled") is True, "production_child_binding_failed")
    _need(len(active) == EXPECTED_ACTIVE_PATHS, "validated_active_count_invalid")
    _need(len(software) == EXPECTED_SOFTWARE_PATHS, "validated_software_count_invalid")
    _need(type(aliases) is int and aliases == EXPECTED_ACTIVE_ALIASES, "validated_alias_count_invalid")
    _need(
        binding.get("driver_expected_public_pin_count") == len(active)
        and binding.get("driver_software_pin_count") == len(software)
        and binding.get("driver_path_alias_count") == aliases,
        "production_binder_counts_do_not_match_map",
    )
    driver = payload.get("driver") if type(payload) is dict else None
    driver_fields = {
        "path",
        "sha256",
        "test_path",
        "test_sha256",
        "packet_dir",
        "packet_pins",
        "review_dir",
        "review_pins",
        "review_readme_sha256",
        "active_path",
    }
    _need(type(driver) is dict and set(driver) == driver_fields, "r27_driver_binding_projection_shape")
    packet_pins = _normalize_map(driver.get("packet_pins"), "r27_packet_projection_invalid")
    review_pins = _normalize_map(driver.get("review_pins"), "r27_review_projection_invalid")
    _need(
        path_key(driver["path"]) == path_key(R19_DRIVER)
        and driver["sha256"] == R19_DRIVER_SHA256
        and path_key(driver["active_path"]) == path_key(derivation.path)
        and path_key(driver["test_path"]) == path_key(derivation.test_path)
        and driver["test_sha256"] == derivation.test_digest
        and path_key(driver["packet_dir"]) == path_key(derivation.packet_path)
        and path_key(driver["review_dir"]) == path_key(derivation.review_path)
        and packet_pins == _normalize_map(derivation.packet_pins, "r27_expected_packet_invalid")
        and review_pins == _normalize_map(derivation.review_pins, "r27_expected_review_invalid")
        and driver["review_readme_sha256"] == derivation.review_pins.get("README.md"),
        "r27_driver_binding_projection_mismatch",
    )
    fresh_paths = payload.get("fresh_paths")
    counts = payload.get("counts")
    _need(type(fresh_paths) is dict and type(counts) is dict, "r27_binding_projection_shape_invalid")
    expected_binding_globals = {
        "ROOT_SELF_SHA256": payload["invoke"]["sha256"],
        "ROOT_TEST_SHA256": payload["invoke"]["test_sha256"],
        "ROOT_PACKET_PINS": dict(payload["invoke"]["packet_pins"]),
        "ROOT_REVIEW_PINS": dict(payload["invoke"]["review_pins"]),
        "ROOT_REVIEW_README_SHA256": payload["invoke"]["review_readme_sha256"],
        "DRIVER_SHA256": driver["sha256"],
        "DRIVER_TEST_SHA256": driver["test_sha256"],
        "DRIVER_PACKET_PINS": dict(driver["packet_pins"]),
        "DRIVER_REVIEW_PINS": dict(driver["review_pins"]),
        "PARENT_DEADLINE_MONOTONIC": payload["parent_deadline_monotonic"],
        "PARENT_DEADLINE_DOMAIN": payload["parent_deadline_domain"],
        "INERT_DRIVER_PUBLIC_PATH_COUNT": counts["inert_public_paths"],
        "ACTIVE_DRIVER_PUBLIC_PATH_COUNT": counts["active_public_paths"],
        "ACTIVE_DRIVER_ALIAS_COUNT": counts["path_aliases"],
        "R2_INERT_DRIVER_PIN_COUNT": binding["r2_inert_driver_pin_count"],
        "ROOT_ACTUAL_ENABLED": True,
        "ROOT_REVIEW_READY": True,
        "ROOT_REVIEWED_ACTIVATION": True,
        "ROOT_CONTROL": Path(fresh_paths["ROOT_CONTROL"]),
        "ROOT_SCRATCH": Path(fresh_paths["ROOT_SCRATCH"]),
        "ROOT_DRIVER_CONTROL": Path(fresh_paths["ROOT_DRIVER_CONTROL"]),
        "ROOT_DRIVER_SCRATCH": Path(fresh_paths["ROOT_DRIVER_SCRATCH"]),
        "ROOT_OUTPUT": Path(fresh_paths["ROOT_OUTPUT"]),
        "ROOT_PRECHECK_OUTPUT": Path(fresh_paths["ROOT_PRECHECK_OUTPUT"]),
    }
    for name, expected_value in expected_binding_globals.items():
        actual_value = invoke.__dict__.get(name, _MISSING_NAMESPACE_VALUE)
        if isinstance(expected_value, Path):
            matches = isinstance(actual_value, Path) and path_key(actual_value) == path_key(expected_value)
        elif type(expected_value) is dict:
            matches = type(actual_value) is dict and actual_value == expected_value
        else:
            matches = type(actual_value) is type(expected_value) and actual_value == expected_value
        _need(matches, "r27_binding_global_projection_changed:" + name)
    _need(invoke.activation_ready() is True, "r27_binding_activation_projection_invalid")
    _accept_module_namespace_stage(
        invoke,
        {name: invoke.__dict__[name] for name in expected_binding_globals},
        stage="r27_production_child_binding_projection",
    )
    _need(id(invoke) not in _R5_BOUND_INVOKES, "r5_production_binding_record_already_exists")
    _R5_BOUND_INVOKES[id(invoke)] = types.MappingProxyType({
        "invoke": invoke,
        "derivation": derivation,
        "active_rows": tuple(sorted(active.items())),
        "software_rows": tuple(sorted(software.items())),
        "aliases": aliases,
        "driver_projection": (
            path_key(driver["path"]),
            driver["sha256"],
            path_key(driver["test_path"]),
            driver["test_sha256"],
            path_key(driver["packet_dir"]),
            tuple(sorted(driver["packet_pins"].items())),
            path_key(driver["review_dir"]),
            tuple(sorted(driver["review_pins"].items())),
            driver["review_readme_sha256"],
            path_key(driver["active_path"]),
        ),
    })
    return binding, active, software, aliases, derivation


def _bound_invoke_record(invoke: types.ModuleType, derivation: _PinnedR19ActiveMap):
    record = _R5_BOUND_INVOKES.get(id(invoke))
    _need(
        type(record) is types.MappingProxyType
        and record.get("invoke") is invoke
        and record.get("derivation") is derivation,
        "r5_production_binding_record_missing",
    )
    return record


def install_full_hold_adaptation(invoke: types.ModuleType, context: dict[str, object]) -> None:
    """Extend the real R27 adaptation before its R2 main call reaches custody."""
    _assert_module_contract(invoke)
    record = _R5_BOUND_INVOKES.get(id(invoke))
    derivation = (
        record.get("derivation")
        if type(record) is types.MappingProxyType and record.get("invoke") is invoke
        else None
    )
    _need(type(derivation) is _PinnedR19ActiveMap, "r5_bound_derivation_missing")
    context["r19_derivation"] = derivation
    original_install = invoke._install_adaptation
    context["r27_original_install_adaptation"] = original_install

    def install(r2: types.ModuleType, active_context: dict[str, object]) -> None:
        active_context["r3_last_stage"] = "r27_original_install"
        original_install(r2, active_context)
        active_context["r2_module_under_test"] = r2
        active_context["r3_last_stage"] = "r27_r2_adaptation_attestation"
        _attest_r27_r2_adaptation(
            r2,
            invoke,
            active_context,
            active_context.get("r27_original_install_adaptation"),
        )
        original_load = r2.load
        original_read_pin = r2.read_pin

        def load_with_full_hold(raw: bytes, path: Path, name: str):
            active_context["r3_last_stage"] = "r27_active_driver_load"
            module = original_load(raw, path, name)
            active_context["r3_active_source_path_seen"] = (
                path_key(path) == path_key(r2.ACTIVE_SOURCE)
            )
            active_context["r3_active_source_alias_seen"] = (
                name == getattr(invoke, "_R2_ACTIVE_DRIVER_ALIAS", None)
            )
            if (
                path_key(path) == path_key(r2.ACTIVE_SOURCE)
                and name == getattr(invoke, "_R2_ACTIVE_DRIVER_ALIAS", None)
            ):
                active_context["r3_active_driver_branch_entered"] = True
                active_context["r3_last_stage"] = "r27_active_driver_baseline"
                try:
                    _seed_r27_active_driver_module_contract(
                        module, path, name, invoke, active_context
                    )
                except BaseException as error:
                    active_context["r3_contract_failure"] = (
                        error.args[0]
                        if type(error) is SourceContractError
                        and len(error.args) == 1
                        and type(error.args[0]) is str
                        else type(error).__name__
                    )
                    raise
                active_context["r3_last_stage"] = "r27_active_driver_attestation"
                try:
                    _attest_r27_active_driver_stage(module, invoke, active_context)
                except BaseException as error:
                    active_context["r3_contract_failure"] = (
                        error.args[0]
                        if type(error) is SourceContractError
                        and len(error.args) == 1
                        and type(error.args[0]) is str
                        else type(error).__name__
                    )
                    raise
                install_verified_exact_reuse(module)
                # Keep the active R19 map builder on the same bounded reader
                # used by the enclosing R27 binder.  Its map derivation stays
                # production code; only the source-byte leaf is redirected.
                _install_module_global_binding(
                    module,
                    "_read_pin",
                    public_read_pin,
                    stage="r28_source_snapshot_reader",
                )
                active_context["r3_last_stage"] = "r19_builder_hook_installation"
                try:
                    _install_r19_map_verification_hook(
                        module,
                        active_context["r19_derivation"],
                        public_read_pin,
                        name,
                        active_context,
                        invoke,
                    )
                except BaseException as error:
                    active_context["r3_contract_failure"] = (
                        error.args[0]
                        if type(error) is SourceContractError
                        and len(error.args) == 1
                        and type(error.args[0]) is str
                        else type(error).__name__
                    )
                    raise
            elif (
                path_key(path) == path_key(r2.SOURCE)
                and name == getattr(invoke, "_R2_INERT_DRIVER_ALIAS", None)
            ):
                # The R2 cold map uses the identical fixed R19 source.  Route
                # its public metadata reads through the catalog as well, so a
                # sourcefake cannot fall through to ambient file reads.
                module._read_pin = public_read_pin
            else:
                active_context["r3_last_stage"] = "r4_other_source_load"
            if path_key(path) == path_key(r2.CU):
                active_context["r3_last_stage"] = "r28_full_hold_builder"
                _need(
                    type(raw) is bytes and sha256(raw) == r2.CU_SHA,
                    "cuv2_source_pin_invalid",
                )
                active_context["r3_last_stage"] = "r28_cuv2_holder_capture"
                original_holder = active_context.get("captured_cuv2_source_factory")
                _need(callable(original_holder), "cuv2_holder_not_captured")
                active_context["r3_last_stage"] = "r27_cuv2_wrapper_attestation"
                try:
                    _seed_r27_cuv2_module_contract(
                        module,
                        raw,
                        path,
                        name,
                        invoke,
                        active_context,
                    )
                except BaseException as error:
                    active_context["r3_contract_failure"] = (
                        error.args[0]
                        if type(error) is SourceContractError
                        and len(error.args) == 1
                        and type(error.args[0]) is str
                        else type(error).__name__
                    )
                    raise

                def full_hold(cold_pins, software_pins):
                    active_context["r3_last_stage"] = "r2_full_hold_entered"
                    invoke._set_diagnostic_phase(active_context, "public_map_assembly")
                    active_pins = active_context.get("validated_active_pins")
                    active_software = active_context.get("validated_active_software")
                    active_aliases = active_context.get("validated_active_aliases")
                    _need(type(active_pins) is dict, "validated_active_map_missing")
                    outer = invoke._extra_pins(active_context["mode"])
                    outer_normalized = _normalize_map(outer, "outer_map_shape_invalid")
                    base_cold = _normalize_map(cold_pins, "cold_map_shape_invalid")
                    active_context["r2_base_cold_paths_observed"] = len(base_cold)
                    active_context["r2_outer_extra_paths_observed"] = len(outer_normalized)
                    _need(len(base_cold) == EXPECTED_R2_BASE_COLD_PATHS, "r2_base_cold_count_mismatch")
                    _need(
                        len(outer_normalized) == EXPECTED_R2_OUTER_EXTRA_PATHS,
                        "r2_outer_extra_count_mismatch",
                    )
                    overlap = set(base_cold) & set(outer_normalized)
                    _need(
                        len(overlap) == EXPECTED_R2_COLD_OUTER_OVERLAPS,
                        "r2_cold_outer_overlap_count_mismatch",
                    )
                    active_context["r3_last_stage"] = "r2_full_hold_count_contract"
                    cold_normalized = dict(base_cold)
                    for key, digest in outer_normalized.items():
                        prior = cold_normalized.get(key)
                        _need(prior is None or prior == digest, "r2_cold_outer_pin_conflict")
                        cold_normalized[key] = digest
                    full, metrics = build_full_hold_map(
                        cold_normalized,
                        active_pins,
                        outer_normalized,
                        software_pins,
                        active_software,
                        active_aliases=active_aliases,
                    )
                    active_context["r3_last_stage"] = "r2_full_hold_merged_map"
                    # The review requirements are derived from the exact helper
                    # roles and artifact maps used by R27's production binder.
                    required = active_context.get("review_required_paths")
                    _need(type(required) is set and len(required) == 64, "review_required_set_missing")
                    cold_keys = set(cold_normalized)
                    active_context["review_required_missing_from_cold_observed"] = len(required - cold_keys)
                    metrics["review_required_paths"] = len(required)
                    metrics["review_required_missing_from_cold"] = len(required - cold_keys)
                    _need(metrics["review_required_missing_from_cold"] == 49, "review_difference_count_mismatch")
                    active_context["r3_last_stage"] = "r2_full_hold_review_bound"
                    active_context["expected_pins"] = full
                    active_context["expected_software"] = _normalize_map(
                        software_pins, "software_map_shape_invalid"
                    )
                    active_context["cold_request_pins"] = cold_normalized
                    active_context["r2_base_cold_paths"] = len(base_cold)
                    active_context["r2_outer_extra_paths"] = len(outer_normalized)
                    active_context["r2_cold_outer_overlap_paths"] = len(overlap)
                    active_context["outer_pins"] = outer_normalized
                    active_context["outer_only_path_keys"] = set(full) - set(active_pins)
                    active_context["full_alias_count"] = active_aliases
                    active_context["full_hold_metrics"] = metrics
                    active_context["r3_last_stage"] = "r2_full_hold_before_fake_custody"
                    fake_factory = active_context.get("source_fake_scope_factory")
                    if active_context.get("source_fake_mode") is True and callable(fake_factory):
                        raw_scope = fake_factory(full, active_context["expected_software"])
                    else:
                        raw_scope = original_holder(full, active_context["expected_software"])
                    active_context["r3_last_stage"] = "r2_full_hold_after_fake_custody"
                    scope = invoke._DeferredScope(raw_scope, active_context, r2)
                    active_context["r3_last_stage"] = "r2_full_hold_scope_created"
                    active_context["scope"] = scope
                    return scope

                module.held_public_sources = full_hold
                active_context["r3_last_stage"] = "r28_cuv2_contract_advance"
                _advance_module_contract(
                    module,
                    {"held_public_sources": full_hold},
                    stage="r28_full_public_hold_builder",
                )
                active_context["r3_last_stage"] = "r28_cuv2_contract_advanced"
            return module

        def public_read_pin(path: Path, digest: str) -> bytes:
            _need(active_context.get("source_fake_mode") is True, "sourcefake_snapshot_reader_required")
            reader = active_context.get("source_snapshot_reader")
            _need(callable(reader), "source_snapshot_reader_missing")
            raw = reader(path, digest)
            _need(type(raw) is bytes and sha256(raw) == digest, "source_snapshot_pin_mismatch")
            return raw

        r2.load = load_with_full_hold
        r2.read_pin = public_read_pin
        active_context["r3_last_stage"] = "r2_review_projection"
        _advance_module_contract(
            r2,
            {"load": load_with_full_hold, "read_pin": public_read_pin},
            stage="r28_sourcefake_reader_adaptation",
        )
        install_r2_review_projection(r2, active_context)

    invoke._install_adaptation = install
    _advance_module_contract(
        invoke,
        {"_install_adaptation": install},
        stage="r28_full_hold_adaptation",
    )


def build_child_payload(invoke: types.ModuleType, whole: types.ModuleType, deadline: float) -> dict[str, object]:
    """Build the exact frozen R27 child payload without changing activation flags."""
    return {
        "schema": invoke._CHILD_ACTIVATION_SCHEMA,
        "invoke": {
            "path": str(invoke.ROOT_SELF_PATH),
            "sha256": R27_INVOKE_SHA256,
            "test_path": str(invoke.ROOT_TEST_PATH),
            "test_sha256": R27_TEST_SHA256,
            "packet_dir": str(invoke.ROOT_PACKET),
            "packet_pins": dict(whole.R19_PACKET_PINS),
            "review_dir": str(invoke.ROOT_REVIEW),
            "review_pins": dict(whole.R19_REVIEW_PINS),
            "review_readme_sha256": whole.R19_REVIEW_PINS["README.md"],
        },
        "driver": {
            "path": str(invoke.DRIVER),
            "sha256": R19_DRIVER_SHA256,
            "test_path": str(invoke.DRIVER_TEST),
            "test_sha256": whole.R19_TEST_SHA256,
            "packet_dir": str(whole.R19_PACKET),
            "packet_pins": dict(whole.R19_PACKET_PINS),
            "review_dir": str(whole.R19_REVIEW),
            "review_pins": dict(whole.R19_REVIEW_PINS),
            "review_readme_sha256": whole.R19_REVIEW_PINS["README.md"],
            "active_path": str(invoke.DRIVER_ACTIVE_PATH),
        },
        "counts": {
            "inert_public_paths": 379,
            "active_public_paths": EXPECTED_ACTIVE_PATHS,
            "software_paths": EXPECTED_SOFTWARE_PATHS,
            "path_aliases": EXPECTED_ACTIVE_ALIASES,
        },
        "fresh_paths": {
            "ROOT_CONTROL": str(invoke.ROOT_CONTROL),
            "ROOT_SCRATCH": str(invoke.ROOT_SCRATCH),
            "ROOT_DRIVER_CONTROL": str(invoke.ROOT_DRIVER_CONTROL),
            "ROOT_DRIVER_SCRATCH": str(invoke.ROOT_DRIVER_SCRATCH),
            "ROOT_OUTPUT": str(invoke.ROOT_OUTPUT),
            "ROOT_PRECHECK_OUTPUT": str(invoke.ROOT_PRECHECK_OUTPUT),
        },
        "parent_deadline_monotonic": deadline,
        "parent_deadline_domain": invoke.PARENT_DEADLINE_CLOCK_DOMAIN,
    }
