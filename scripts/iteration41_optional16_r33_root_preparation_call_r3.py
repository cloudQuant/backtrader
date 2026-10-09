"""Root-only call gate for the frozen Optional16 preparation helper.

This adapter binds the supplied V3/V4 module instances to exact source bytes
from the same open Root-held scope before it calls the frozen R1 preparation
helper. The helper performs Entry R2's derived map, V4/R29 proof, R5/R27
transforms, and normal postverify/close, stopping before its worker installer.
R3 accepts the exact pinned V3 loader's absent ``__cached__`` slot while
retaining all other source, function, class, and global binding checks. It
loads an isolated V4 reference from unchanged held bytes under the original
Root audit by temporarily binding only V4's canonical V3 module alias. Its
failure projection adds finite phase/category/code fields without exposing
exception text. This module creates no scope, claim, control file, child, or
activation.
"""

from __future__ import annotations

import builtins
import hashlib
import importlib.machinery
import ntpath
from pathlib import Path, PurePath
import re
import sys
import types


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "iteration41.optional16.r33.root-preparation-call.r3"
MAX_MODULE_SOURCE_BYTES = 256 * 1024
MAX_PREPARATION_SOURCE_BYTES = 256 * 1024
_SAFE_CODE = re.compile(r"[a-z0-9_:]{1,96}\Z")
_RETAINED: list[tuple[object, ...]] = []
_MISSING = object()
_FAILURE_PHASES = frozenset(
    {
        "input_shape",
        "module_binding",
        "scope_reread",
        "helper_load",
        "helper_call",
        "result_check",
    }
)
_FAILURE_CATEGORIES = frozenset(
    {"source_contract", "preparation_result", "scope_state", "unexpected", "none"}
)
_FAILURE_CODES = frozenset(
    {
        "input_rejected",
        "module_binding_rejected",
        "scope_reread_rejected",
        "helper_pin_rejected",
        "helper_load_rejected",
        "preparation_rejected",
        "scope_not_closed",
        "unexpected_exception",
        "none",
        "preparation_complete",
    }
)

V3_REL = Path("scripts/iteration41_root_held_source_scope_v3.py")
V3_SHA256 = "f3270495d3ddb046f8617d689510d4ae6ee700d639e0db769c518a15099a7677"
V3_MODULE_NAME = "_iteration41_root_held_source_scope_v3_pinned_for_v4"
V4_REL = Path("scripts/iteration41_root_held_source_scope_v4.py")
V4_SHA256 = "138c86e21de773822eceac07034e113e0adb5ea5d9056fcc16cee10a75c0e830"
V4_MODULE_NAME = "_iteration41_optional16_r33_entry_v4"
PREPARATION_REL = Path("scripts/iteration41_optional16_r33_root_preparation_r1.py")
PREPARATION_SHA256 = "a626001a9f80bee26996a0fd3effb0e670c96ffd7a167ba154d23521eca64aa4"
ENTRY_REL = Path("scripts/iteration41_optional16_r33_root_held_entry_r2.py")
ENTRY_SHA256 = "80295025d0145893f4f63745182042812284434e4e7e5b4388b89d82623c2ead"


class RootPreparationCallError(RuntimeError):
    """Finite error codes; no source paths or artifact bytes are included."""


def _need(condition: object, code: str) -> None:
    if not condition:
        raise RootPreparationCallError(code)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _path_key(path: str | Path) -> str:
    value = str(path).replace("/", "\\")
    return ntpath.normcase(ntpath.normpath(value))


def _module_metadata(module: types.ModuleType, name: str, relative: Path, digest: str) -> None:
    path = ROOT / relative
    spec = getattr(module, "__spec__", None)
    is_pinned_v3_loader = (
        name == V3_MODULE_NAME and relative == V3_REL and digest == V3_SHA256
    )
    cached_slot_ok = (
        module.__dict__.get("__cached__") is None
        if is_pinned_v3_loader
        else "__cached__" in module.__dict__ and module.__dict__["__cached__"] is None
    )
    _need(
        module.__name__ == name
        and type(spec) is importlib.machinery.ModuleSpec
        and spec.name == name
        and spec.origin == str(path)
        and module.__file__ == str(path)
        and module.__package__ == ""
        and module.__loader__ is None
        and cached_slot_ok
        and module.__dict__.get("__builtins__") is builtins.__dict__
        and module.__dict__.get("__verified_source_sha256__") == digest,
        "module_source_metadata_mismatch",
    )


def _make_module(name: str, relative: Path, raw: bytes, digest: str) -> types.ModuleType:
    path = ROOT / relative
    module = types.ModuleType(name)
    module.__file__ = str(path)
    module.__package__ = ""
    module.__loader__ = None
    module.__cached__ = None
    module.__spec__ = importlib.machinery.ModuleSpec(name, loader=None, origin=str(path))
    module.__verified_source_sha256__ = digest
    try:
        exec(compile(raw, str(path), "exec", dont_inherit=True), module.__dict__, module.__dict__)
    except BaseException:
        raise RootPreparationCallError("reference_source_compile_failed") from None
    return module


def _v4_reference(
    v3_reference: types.ModuleType,
    v4_raw: bytes,
    actual_v3: types.ModuleType,
) -> types.ModuleType:
    """Run the original V4 loader over unchanged bytes under Root's audit.

    V4's top-level loader resolves V3 through its canonical ``sys.modules``
    alias. The actual loaded module must own that alias before this function
    temporarily swaps it to the independently compiled V3 reference. Restoring
    the exact prior object in ``finally`` keeps the live production binding
    unchanged even if reference loading fails.
    """

    prior = sys.modules.get(V3_MODULE_NAME, _MISSING)
    _need(
        type(v3_reference) is types.ModuleType
        and type(actual_v3) is types.ModuleType
        and prior is actual_v3,
        "v3_reference_alias_invalid",
    )
    try:
        sys.modules[V3_MODULE_NAME] = v3_reference
        try:
            module = _make_module(V4_MODULE_NAME, V4_REL, v4_raw, V4_SHA256)
        except BaseException:
            raise RootPreparationCallError("v4_reference_compile_failed") from None
    finally:
        if prior is _MISSING:
            sys.modules.pop(V3_MODULE_NAME, None)
        else:
            sys.modules[V3_MODULE_NAME] = prior
    _need(
        sys.modules.get(V3_MODULE_NAME) is actual_v3
        and module.__dict__.get("_V3_MODULE") is v3_reference,
        "v4_reference_alias_restore_failed",
    )
    return module


def _same_data(
    actual: object,
    expected: object,
    module_pairs: dict[int, types.ModuleType],
    class_pairs: dict[int, type],
) -> bool:
    if actual is expected:
        return True
    if type(expected) in (str, bytes, int, bool, float, complex, type(None)):
        return type(actual) is type(expected) and actual == expected
    if type(expected) is object:
        return type(actual) is object
    if type(expected) is types.ModuleType:
        target = module_pairs.get(id(expected))
        return actual is target if target is not None else actual is expected
    if type(expected) is type:
        target = class_pairs.get(id(expected))
        return actual is target if target is not None else actual is expected
    if type(expected) in {types.MemberDescriptorType, types.GetSetDescriptorType}:
        expected_owner = getattr(expected, "__objclass__", None)
        actual_owner = getattr(actual, "__objclass__", None)
        target_owner = class_pairs.get(id(expected_owner))
        return (
            type(actual) is type(expected)
            and getattr(actual, "__name__", None) == getattr(expected, "__name__", None)
            and actual_owner is (target_owner if target_owner is not None else expected_owner)
        )
    if type(expected) is tuple:
        return (
            type(actual) is tuple
            and len(actual) == len(expected)
            and all(_same_data(a, e, module_pairs, class_pairs) for a, e in zip(actual, expected))
        )
    if type(expected) is list:
        return (
            type(actual) is list
            and len(actual) == len(expected)
            and all(_same_data(a, e, module_pairs, class_pairs) for a, e in zip(actual, expected))
        )
    if type(expected) is set:
        return type(actual) is set and actual == expected
    if type(expected) is frozenset:
        return type(actual) is frozenset and actual == expected
    if type(expected) is dict:
        return (
            type(actual) is dict
            and set(actual) == set(expected)
            and all(
                _same_data(actual[key], expected[key], module_pairs, class_pairs)
                for key in expected
            )
        )
    if isinstance(expected, re.Pattern):
        return (
            isinstance(actual, re.Pattern)
            and type(actual) is type(expected)
            and actual.pattern == expected.pattern
            and actual.flags == expected.flags
        )
    if isinstance(expected, PurePath):
        return type(actual) is type(expected) and str(actual) == str(expected)
    return False


def _compare_function(
    actual: object,
    expected: types.FunctionType,
    actual_owner: types.ModuleType,
    reference_owner: types.ModuleType,
    module_pairs: dict[int, types.ModuleType],
    class_pairs: dict[int, type],
) -> None:
    _need(type(actual) is types.FunctionType, "module_function_type_mismatch")
    function = actual
    expected_global_owner = expected.__globals__
    if expected_global_owner is reference_owner.__dict__:
        globals_match = function.__globals__ is actual_owner.__dict__
    else:
        globals_match = function.__globals__ is expected_global_owner
    _need(
        globals_match
        and function.__code__ == expected.__code__
        and function.__name__ == expected.__name__
        and function.__qualname__ == expected.__qualname__
        and function.__module__ == expected.__module__
        and _same_data(function.__defaults__, expected.__defaults__, module_pairs, class_pairs)
        and _same_data(function.__kwdefaults__, expected.__kwdefaults__, module_pairs, class_pairs)
        and _same_data(function.__annotations__, expected.__annotations__, module_pairs, class_pairs),
        "module_function_source_or_global_mismatch",
    )
    actual_closure = function.__closure__
    expected_closure = expected.__closure__
    _need(
        (actual_closure is None) == (expected_closure is None)
        and (
            actual_closure is None
            or (
                len(actual_closure) == len(expected_closure)
                and all(
                    _same_data(a.cell_contents, e.cell_contents, module_pairs, class_pairs)
                    for a, e in zip(actual_closure, expected_closure)
                )
            )
        ),
        "module_function_closure_mismatch",
    )


def _compare_class(
    actual: object,
    expected: type,
    actual_owner: types.ModuleType,
    reference_owner: types.ModuleType,
    module_pairs: dict[int, types.ModuleType],
    class_pairs: dict[int, type],
    visited: set[int],
) -> None:
    target = class_pairs.get(id(expected))
    _need(type(actual) is type and (target is None or actual is target), "module_class_identity_mismatch")
    if id(expected) in visited:
        return
    visited.add(id(expected))
    _need(
        actual.__module__ == expected.__module__
        and actual.__qualname__ == expected.__qualname__
        and len(actual.__bases__) == len(expected.__bases__)
        and all(
            _same_data(a, e, module_pairs, class_pairs)
            for a, e in zip(actual.__bases__, expected.__bases__)
        ),
        "module_class_shape_mismatch",
    )
    actual_values = dict(actual.__dict__)
    expected_values = dict(expected.__dict__)
    skipped = {"__dict__", "__weakref__", "__classcell__"}
    actual_keys = set(actual_values) - skipped
    expected_keys = set(expected_values) - skipped
    _need(actual_keys == expected_keys, "module_class_members_mismatch")
    for name in expected_keys:
        value = expected_values[name]
        candidate = actual_values[name]
        if type(value) is types.FunctionType:
            _compare_function(
                candidate, value, actual_owner, reference_owner, module_pairs, class_pairs
            )
        elif isinstance(value, (staticmethod, classmethod)):
            _need(type(candidate) is type(value), "module_class_descriptor_mismatch")
            _compare_function(
                candidate.__func__, value.__func__, actual_owner, reference_owner,
                module_pairs, class_pairs,
            )
        elif isinstance(value, property):
            _need(type(candidate) is property, "module_class_property_mismatch")
            for actual_fn, expected_fn in (
                (candidate.fget, value.fget),
                (candidate.fset, value.fset),
                (candidate.fdel, value.fdel),
            ):
                _need((actual_fn is None) == (expected_fn is None), "module_class_property_mismatch")
                if expected_fn is not None:
                    _compare_function(
                        actual_fn, expected_fn, actual_owner, reference_owner,
                        module_pairs, class_pairs,
                    )
            _need(candidate.__doc__ == value.__doc__, "module_class_property_doc_mismatch")
        else:
            if not _same_data(candidate, value, module_pairs, class_pairs):
                raise RootPreparationCallError(
                    "module_class_value_mismatch:" + expected.__qualname__ + ":" + name
                )


def _compare_module(
    actual: object,
    reference: types.ModuleType,
    module_pairs: dict[int, types.ModuleType],
    class_pairs: dict[int, type],
    visited_classes: set[int],
) -> None:
    _need(type(actual) is types.ModuleType, "module_type_mismatch")
    module = actual
    pinned_v3_reference = (
        reference.__name__ == V3_MODULE_NAME
        and reference.__file__ == str(ROOT / V3_REL)
        and reference.__dict__.get("__verified_source_sha256__") == V3_SHA256
    )
    cached_slot_ok = (
        module.__dict__.get("__cached__") is None
        if pinned_v3_reference
        else "__cached__" in module.__dict__ and module.__dict__["__cached__"] is None
    )
    _need(
        module.__name__ == reference.__name__
        and module.__file__ == reference.__file__
        and module.__package__ == reference.__package__
        and module.__loader__ is None
        and cached_slot_ok
        and module.__dict__.get("__builtins__") is builtins.__dict__
        and module.__dict__.get("__verified_source_sha256__")
        == reference.__dict__.get("__verified_source_sha256__")
        and type(module.__spec__) is importlib.machinery.ModuleSpec
        and module.__spec__.name == reference.__spec__.name
        and module.__spec__.origin == reference.__spec__.origin,
        "module_metadata_mismatch",
    )
    metadata = {
        "__name__", "__doc__", "__package__", "__loader__", "__spec__", "__file__",
        "__cached__", "__builtins__", "__verified_source_sha256__",
    }
    actual_keys = set(module.__dict__) - metadata
    reference_keys = set(reference.__dict__) - metadata
    _need(actual_keys == reference_keys, "module_global_names_mismatch")
    _need(module.__doc__ == reference.__doc__, "module_docstring_mismatch")
    for name in reference_keys:
        expected = reference.__dict__[name]
        candidate = module.__dict__[name]
        if type(expected) is types.FunctionType:
            _compare_function(candidate, expected, module, reference, module_pairs, class_pairs)
        elif isinstance(expected, type) and expected.__module__ == reference.__name__:
            _compare_class(
                candidate, expected, module, reference, module_pairs, class_pairs,
                visited_classes,
            )
        else:
            _need(
                _same_data(candidate, expected, module_pairs, class_pairs),
                "module_global_value_mismatch",
            )


def bind_v4_module_to_held_source(
    v4: object,
    module_sources: object,
    *,
    scope: object | None = None,
) -> tuple[types.ModuleType, types.ModuleType]:
    """Bind the supplied V4 and nested V3 modules to exact held source bytes.

    ``module_sources`` must contain exactly ``{"v3": bytes, "v4": bytes}``,
    obtained by Root from the active held source scope. This function compiles
    isolated references without registering them in ``sys.modules`` and
    compares function code, globals, module state, and class descriptors. If
    ``scope`` is supplied, V3's live retained-scope list must contain only that
    exact object; this preserves the legitimate open-scope identity without
    accepting unrelated retained scopes.
    """

    _need(type(module_sources) is dict and set(module_sources) == {"v3", "v4"},
          "module_source_set_invalid")
    v3_raw = module_sources["v3"]
    v4_raw = module_sources["v4"]
    _need(
        type(v3_raw) is bytes
        and 0 < len(v3_raw) <= MAX_MODULE_SOURCE_BYTES
        and _sha(v3_raw) == V3_SHA256,
        "v3_held_source_invalid",
    )
    _need(
        type(v4_raw) is bytes
        and 0 < len(v4_raw) <= MAX_MODULE_SOURCE_BYTES
        and _sha(v4_raw) == V4_SHA256,
        "v4_held_source_invalid",
    )
    v3_reference = _make_module(V3_MODULE_NAME, V3_REL, v3_raw, V3_SHA256)
    _module_metadata(v4, V4_MODULE_NAME, V4_REL, V4_SHA256)
    actual_v3 = getattr(v4, "_V3_MODULE", None)
    _module_metadata(actual_v3, V3_MODULE_NAME, V3_REL, V3_SHA256)
    v4_reference = _v4_reference(v3_reference, v4_raw, actual_v3)
    if scope is not None:
        retained_scopes = actual_v3.__dict__.get("_RETAINED_SCOPES")
        _need(
            type(retained_scopes) is list
            and len(retained_scopes) == 1
            and retained_scopes[0] is scope,
            "v3_retained_scope_identity_mismatch",
        )
        v3_reference.__dict__["_RETAINED_SCOPES"][:] = [scope]
    module_pairs = {id(v3_reference): actual_v3, id(v4_reference): v4}
    class_pairs: dict[int, type] = {}
    for actual, reference in ((actual_v3, v3_reference), (v4, v4_reference)):
        for name, expected in reference.__dict__.items():
            if isinstance(expected, type) and expected.__module__ == reference.__name__:
                candidate = actual.__dict__.get(name, _MISSING)
                _need(type(candidate) is type, "module_class_missing")
                class_pairs[id(expected)] = candidate
    visited_classes: set[int] = set()
    _compare_module(actual_v3, v3_reference, module_pairs, class_pairs, visited_classes)
    _compare_module(v4, v4_reference, module_pairs, class_pairs, visited_classes)
    _need(
        v4.RootHeldScopeV4.__bases__ == (actual_v3.RootHeldScopeV3,),
        "v4_scope_base_identity_mismatch",
    )
    return v3_reference, v4_reference


def _load_pinned_preparation_helper(raw: bytes) -> types.ModuleType:
    _need(
        type(raw) is bytes
        and 0 < len(raw) <= MAX_PREPARATION_SOURCE_BYTES
        and _sha(raw) == PREPARATION_SHA256,
        "preparation_helper_pin_mismatch",
    )
    return _make_module(
        "_iteration41_optional16_r33_root_preparation_r1_pinned",
        PREPARATION_REL,
        raw,
        PREPARATION_SHA256,
    )


def _scope_matches_sources(scope: object, v4: types.ModuleType, sources: dict[str, bytes]) -> None:
    _need(type(scope) is v4.RootHeldScopeV4, "production_scope_type_invalid")
    _need(scope.state == "OPEN" and scope.test_only is False, "production_scope_state_invalid")
    manifest = scope.manifest()
    _need(type(manifest) is dict, "production_scope_manifest_invalid")
    normalized = {_path_key(path): digest for path, digest in manifest.items()}
    for name, relative, digest in (("v3", V3_REL, V3_SHA256), ("v4", V4_REL, V4_SHA256)):
        key = _path_key(ROOT / relative)
        _need(normalized.get(key) == digest, "module_source_not_in_scope")
        observed = scope.read_held(ROOT / relative, digest, MAX_MODULE_SOURCE_BYTES)
        _need(type(observed) is bytes and observed == sources[name], "module_source_scope_mismatch")


def _safe_reason(value: object) -> str:
    return value if type(value) is str and _SAFE_CODE.fullmatch(value) else "preparation_call_failed"


def _failure_projection(phase: str, category: str, code: str) -> dict[str, str]:
    """Return only fixed diagnostic labels; never include exception data."""
    if type(phase) is not str or phase not in _FAILURE_PHASES:
        phase = "result_check"
    if type(category) is not str or category not in _FAILURE_CATEGORIES:
        category = "unexpected"
    if type(code) is not str or code not in _FAILURE_CODES:
        code = "unexpected_exception"
    return {
        "diagnostic_phase": phase,
        "diagnostic_category": category,
        "diagnostic_code": code,
    }


def prepare_root_source_verification(
    scope: object,
    v4: object,
    payload_raw: bytes,
    module_sources: object,
    preparation_helper_raw: bytes,
    *,
    requested: bool = False,
) -> dict[str, object]:
    """Run the pinned R1 preparation helper after binding V3/V4 source.

    Root supplies V3/V4 bytes obtained from the same open source scope. The
    function verifies those bytes against the module objects, re-reads them
    through the now source-bound scope to prove same-scope custody, then calls
    the exact R1 helper. It retains scope and module references on every
    failure or uncertain close.
    """

    if requested is not True:
        return {
            "schema": SCHEMA,
            "status": "BLOCKED",
            "reason_code": "preparation_request_required",
            "evidence_level": "NONE",
            **_failure_projection("input_shape", "source_contract", "input_rejected"),
        }
    references: tuple[object, ...] = (scope, v4, module_sources, preparation_helper_raw)
    helper_module = None
    phase = "input_shape"
    try:
        _need(type(module_sources) is dict, "module_source_set_invalid")
        held_sources = dict(module_sources)
        phase = "module_binding"
        v3_reference, v4_reference = bind_v4_module_to_held_source(
            v4, held_sources, scope=scope
        )
        phase = "scope_reread"
        _scope_matches_sources(scope, v4, held_sources)
        phase = "helper_load"
        helper_module = _load_pinned_preparation_helper(preparation_helper_raw)
        references = (*references, v3_reference, v4_reference, helper_module)
        phase = "helper_call"
        result = helper_module.prepare_root_source_verification(
            scope, v4, payload_raw, requested=True
        )
        phase = "result_check"
        if (
            type(result) is dict
            and result.get("status") == "PREPARATION_VERIFIED_NO_AUTHORITY"
            and result.get("scope_state") == "CLOSED"
            and scope.state == "CLOSED"
        ):
            return {
                "schema": SCHEMA,
                "status": "PREPARATION_VERIFIED_NO_AUTHORITY",
                "reason_code": "held_source_preparation_complete",
                "evidence_level": "ROOT_HELD_PREPARATION_ONLY",
                "public_rows": result.get("public_rows"),
                "full_union_rows": result.get("full_union_rows"),
                "software_rows": result.get("software_rows"),
                "held_rows": result.get("held_rows"),
                "profiler_modules": result.get("profiler_modules"),
                "boundary": "before_r5_worker_installer",
                "scope_state": "CLOSED",
                "authority": "NONE",
                "activation": "NOT_ENTERED",
                "control": "NOT_ENTERED",
                "child": "NOT_ENTERED",
                **_failure_projection("result_check", "none", "preparation_complete"),
            }
        reason = _safe_reason(result.get("reason_code") if type(result) is dict else None)
        if reason == "production_scope_required":
            diagnostic = _failure_projection(
                "helper_call", "preparation_result", "preparation_rejected"
            )
        elif reason == "source_scope_close_not_confirmed":
            diagnostic = _failure_projection(
                "helper_call", "scope_state", "scope_not_closed"
            )
        else:
            diagnostic = _failure_projection(
                "helper_call", "preparation_result", "preparation_rejected"
            )
        _RETAINED.append(references)
        return {
            "schema": SCHEMA,
            "status": "BLOCKED_RETAINED",
            "reason_code": reason,
            "evidence_level": "ROOT_HELD_PREPARATION_ONLY",
            "scope_state": "RETAINED",
            "authority": "NONE",
            "activation": "NOT_ENTERED",
            "control": "NOT_ENTERED",
            "child": "NOT_ENTERED",
            **diagnostic,
        }
    except BaseException as error:
        if helper_module is not None:
            references = (*references, helper_module)
        _RETAINED.append(references)
        if type(error) is RootPreparationCallError and phase == "module_binding":
            diagnostic = _failure_projection(
                phase, "source_contract", "module_binding_rejected"
            )
        elif type(error) is RootPreparationCallError and phase == "scope_reread":
            diagnostic = _failure_projection(
                phase, "source_contract", "scope_reread_rejected"
            )
        elif type(error) is RootPreparationCallError and phase == "helper_load":
            diagnostic = _failure_projection(
                phase, "source_contract", "helper_pin_rejected"
            )
        elif type(error) is RootPreparationCallError and phase == "input_shape":
            diagnostic = _failure_projection(
                phase, "source_contract", "input_rejected"
            )
        elif phase == "helper_load":
            diagnostic = _failure_projection(phase, "unexpected", "helper_load_rejected")
        else:
            diagnostic = _failure_projection(phase, "unexpected", "unexpected_exception")
        return {
            "schema": SCHEMA,
            "status": "BLOCKED_RETAINED",
            "reason_code": "source_binding_or_preparation_failed",
            "evidence_level": "ROOT_HELD_PREPARATION_ONLY",
            "scope_state": "RETAINED",
            "authority": "NONE",
            "activation": "NOT_ENTERED",
            "control": "NOT_ENTERED",
            "child": "NOT_ENTERED",
            **diagnostic,
        }
