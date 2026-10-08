"""Bounded, unregistered Optional16 Root source-preparation adapter.

The helper runs the source-derived prefix of the fixed Entry R2 owner path on
an already-open production V4 held scope. It performs the pinned V4/R29
profiler checks and the Entry R2 R5/R27 source transformations, then stops
before the R5 worker installer. It never creates a scope, reads private
configuration, creates control files, starts a child, imports an SDK, or
activates a runner. Importing this module has no operational effect.

The request switch only permits this bounded preparation call. It does not
grant authority and is never serialized in the receipt.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.machinery
import ntpath
from pathlib import Path
import re
import types


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "iteration41.optional16.r33.root-held-preparation.r1"
MAX_ENTRY_BYTES = 2 * 1024 * 1024
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_CODE = re.compile(r"[a-z0-9_:]{1,96}\Z")
_RETAINED: list[tuple[object, ...]] = []

ENTRY_REL = Path("scripts/iteration41_optional16_r33_root_held_entry_r2.py")
ENTRY_SHA256 = "80295025d0145893f4f63745182042812284434e4e7e5b4388b89d82623c2ead"
ENTRY_MODULE_NAME = "_iteration41_optional16_r33_root_held_entry_preparation_r1"

V3_REL = Path("scripts/iteration41_root_held_source_scope_v3.py")
V3_SHA256 = "f3270495d3ddb046f8617d689510d4ae6ee700d639e0db769c518a15099a7677"
V4_REL = Path("scripts/iteration41_root_held_source_scope_v4.py")
V4_SHA256 = "138c86e21de773822eceac07034e113e0adb5ea5d9056fcc16cee10a75c0e830"

R27_INVOKE_REL = Path("scripts/iteration41_optional16_r33_root_held_invoke_r27.py")
R27_INVOKE_SHA256 = "ea0a4f9ec5978508b854fe457dd1cfc3c0e9c41b7b23b89ec461bfed4d798339"
R27_WHOLE_REL = Path("scripts/iteration41_optional16_r33_whole_call_supervisor_r27.py")
R27_WHOLE_SHA256 = "bfdd7bc9530b9ded9722ec86c1c184f36de3fb6337fb6688cbe15fa0f77f2876"
R27_TEST_REL = Path("tests/unit/scripts/test_iteration41_optional16_r33_activation_r27_source_fake.py")
R27_TEST_SHA256 = "d1794b07e9f742dc7ee893bf31194ca16729542d6936a303bc05b1ed55f4039f"
R5_HELPER_REL = Path("scripts/iteration41_optional16_r33_root_held_invoke_r28_r5.py")
R5_HELPER_SHA256 = "710452c8358887faa152cd2c6d11333ccf8ecb18fbe64d511ce86eb8f112c99c"
R15_GLUE_REL = Path("scripts/iteration41_optional16_r33_root_held_glue_r15.py")
R15_GLUE_SHA256 = "f9c9a5332a9d2456db8179d7a7e63103269c16feb2712a2b039479d97fe2dd98"
R19_DRIVER_REL = Path("scripts/iteration41_optional16_r33_root_driver_r19.py")
R19_DRIVER_SHA256 = "d7cd9a173e44510e8e2df8fbf68ff5420e495b5a7dd82c589bd1cbef3351c890"
R2_PREDECESSOR_REL = Path("scripts/iteration41_optional16_r33_root_held_invoke_r28_r2.py")
R2_PREDECESSOR_SHA256 = "fea25e15d535e7cd47d0637e060d464cbc982e8cdedfc2a1b620d166118cb213"
R19_BINDING_REL = Path("scripts/iteration41_optional16_r33_deadline_r19_binding.py")
R19_BINDING_SHA256 = "1774b2776c9c03c0e10574fda4f58093f3c2947d902d78c2d41bac9d4c47ba58"
R18_BINDING_REL = Path("scripts/iteration41_optional16_r33_deadline_r18_binding.py")
R18_BINDING_SHA256 = "5977009ff0d6bfafb98f5e9eace3e49cd9e49a15c760237ff5cee4d0f9c2fb43"
R17_BINDING_REL = Path("scripts/iteration41_optional16_r33_deadline_r17_binding.py")
R17_BINDING_SHA256 = "f4526bd40433fb74fe0c3d360c863d07e5613924a9bba243611026c058b442bd"
R16_BINDING_REL = Path("scripts/iteration41_optional16_r33_deadline_r15_root_binding_r1.py")
R16_BINDING_SHA256 = "5b30bb4a1516fcc632362a8be9073b4dfbdaafe8476b8d73c5b300ca05433a75"

_ENTRY_EXPECTED_BINDINGS = {
    "R27_INVOKE_REL": R27_INVOKE_REL,
    "R27_INVOKE_SHA256": R27_INVOKE_SHA256,
    "R27_WHOLE_REL": R27_WHOLE_REL,
    "R27_WHOLE_SHA256": R27_WHOLE_SHA256,
    "R27_TEST_REL": R27_TEST_REL,
    "R27_TEST_SHA256": R27_TEST_SHA256,
    "R28_R5_REL": R5_HELPER_REL,
    "R28_R5_SHA256": R5_HELPER_SHA256,
    "R2_GLUE_REL": R15_GLUE_REL,
    "R2_GLUE_SHA256": R15_GLUE_SHA256,
    "R19_DRIVER_REL": R19_DRIVER_REL,
    "R19_DRIVER_SHA256": R19_DRIVER_SHA256,
    "V3_REL": V3_REL,
    "V3_SHA256": V3_SHA256,
    "V4_REL": V4_REL,
    "V4_SHA256": V4_SHA256,
    "R2_PREDECESSOR_REL": R2_PREDECESSOR_REL,
    "R2_PREDECESSOR_SHA256": R2_PREDECESSOR_SHA256,
    "R19_BINDING_HELPER_REL": R19_BINDING_REL,
    "R19_BINDING_HELPER_SHA256": R19_BINDING_SHA256,
    "R18_BINDING_HELPER_REL": R18_BINDING_REL,
    "R18_BINDING_HELPER_SHA256": R18_BINDING_SHA256,
    "R17_BINDING_HELPER_REL": R17_BINDING_REL,
    "R17_BINDING_HELPER_SHA256": R17_BINDING_SHA256,
    "R16_BINDING_HELPER_REL": R16_BINDING_REL,
    "R16_BINDING_HELPER_SHA256": R16_BINDING_SHA256,
}


class PreparationError(RuntimeError):
    """Finite preparation errors; never include source paths or raw input."""


def _need(condition: object, code: str) -> None:
    if not condition:
        raise PreparationError(code)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _path_key(path: str | Path) -> str:
    value = str(path).replace("/", "\\")
    return ntpath.normcase(ntpath.normpath(value))


def _validate_v4_module(v4: object) -> types.ModuleType:
    _need(type(v4) is types.ModuleType, "v4_module_type_invalid")
    expected_path = ROOT / V4_REL
    spec = getattr(v4, "__spec__", None)
    _need(
        getattr(v4, "__name__", None) == "_iteration41_optional16_r33_entry_v4"
        and type(spec) is importlib.machinery.ModuleSpec
        and getattr(spec, "origin", None) == str(expected_path)
        and getattr(v4, "__verified_source_sha256__", None) == V4_SHA256
        and getattr(v4, "__file__", None) == str(expected_path)
        and getattr(v4, "ROOT_HELD_SCOPE_V4_ENABLED", None) is False
        and getattr(v4, "ROOT_HELD_SCOPE_V4_SCHEMA", None)
        == "iteration41.root-held-source-scope.v4",
        "v4_module_source_invalid",
    )
    return v4


def _validate_production_scope(scope: object, v4: types.ModuleType) -> None:
    _need(type(scope) is v4.RootHeldScopeV4, "production_scope_type_invalid")
    _need(getattr(scope, "schema", None) == v4.ROOT_HELD_SCOPE_V4_SCHEMA, "production_scope_schema_invalid")
    _need(getattr(scope, "state", None) == "OPEN", "production_scope_state_invalid")
    _need(getattr(scope, "test_only", None) is False, "test_scope_rejected_for_production")
    # manifest() enforces same-thread ownership on the actual scope API.
    _need(type(scope.manifest()) is dict, "production_scope_manifest_invalid")


def _load_entry_module(entry_raw: bytes) -> types.ModuleType:
    _need(type(entry_raw) is bytes and 0 < len(entry_raw) <= MAX_ENTRY_BYTES, "entry_source_size_invalid")
    _need(_sha(entry_raw) == ENTRY_SHA256, "entry_source_pin_mismatch")
    path = ROOT / ENTRY_REL
    module = types.ModuleType(ENTRY_MODULE_NAME)
    module.__file__ = str(path)
    module.__package__ = ""
    module.__loader__ = None
    module.__cached__ = None
    module.__spec__ = importlib.machinery.ModuleSpec(ENTRY_MODULE_NAME, loader=None, origin=str(path))
    module.__verified_source_sha256__ = ENTRY_SHA256
    try:
        exec(compile(entry_raw, str(path), "exec", dont_inherit=True), module.__dict__, module.__dict__)
    except BaseException:
        raise PreparationError("entry_source_compile_failed") from None
    _need(
        module.__dict__.get("ENTRY_SCHEMA") == "iteration41.optional16.r33.root-held-entry.r2"
        and module.__dict__.get("ROOT_ACTUAL_ENABLED") is False
        and module.__dict__.get("ROOT_ENTRY_SOURCE_SHA256") is None,
        "entry_source_defaults_invalid",
    )
    for name, expected in _ENTRY_EXPECTED_BINDINGS.items():
        _need(module.__dict__.get(name) == expected, "entry_source_dependency_binding_invalid")
    _need(type(module.__dict__.get("_execute_with_scope")) is types.FunctionType, "entry_executor_missing")
    _need(module.__dict__["_execute_with_scope"].__globals__ is module.__dict__, "entry_executor_globals_invalid")
    return module


def _installer_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Attribute)
        and isinstance(node.value.func.value, ast.Name)
        and node.value.func.value.id == "helper"
        and node.value.func.attr == "install_full_hold_adaptation"
    )


def _call_matches(node: ast.AST, root: str, attribute: str) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == root
        and node.func.attr == attribute
    )


def _name_call(node: ast.AST, name: str) -> bool:
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == name


def _compile_preinstaller_prefix(entry_module: types.ModuleType, entry_raw: bytes) -> types.FunctionType:
    _need(type(entry_module) is types.ModuleType, "entry_module_type_invalid")
    _need(entry_module.__dict__.get("__verified_source_sha256__") == ENTRY_SHA256, "entry_module_pin_invalid")
    try:
        tree = ast.parse(entry_raw.decode("utf-8", "strict"))
    except (UnicodeError, SyntaxError):
        raise PreparationError("entry_source_parse_failed") from None
    functions = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_execute_with_scope"
    ]
    _need(len(functions) == 1, "entry_executor_anchor_invalid")
    original = functions[0]
    installer_indexes = [index for index, node in enumerate(original.body) if _installer_call(node)]
    _need(len(installer_indexes) == 1, "worker_installer_boundary_invalid")
    boundary = installer_indexes[0]
    prefix = original.body[:boundary]
    _need(prefix and not any(isinstance(node, ast.Return) for node in prefix), "preinstaller_prefix_shape_invalid")

    all_calls = [node for statement in prefix for node in ast.walk(statement) if isinstance(node, ast.Call)]
    _need(sum(_call_matches(node, "scope", "verify_profiler_module_cache") for node in all_calls) == 1,
          "v4_profiler_call_anchor_invalid")
    _need(sum(_call_matches(node, "helper", "derive_pinned_r19_active_map") for node in all_calls) == 1,
          "r19_derivation_anchor_invalid")
    _need(sum(_call_matches(node, "helper", "build_full_hold_map") for node in all_calls) == 1,
          "full_map_builder_anchor_invalid")
    _need(sum(_name_call(node, "_transform_deferred_scope") for node in all_calls) == 1,
          "r5_scope_transform_anchor_invalid")
    _need(sum(_name_call(node, "_transform_r28_worker_installer") for node in all_calls) == 1,
          "r5_installer_transform_anchor_invalid")
    _need(
        not any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "invoke"
            and node.func.attr in {"_r2_main", "_start", "start", "run"}
            for node in all_calls
        ),
        "active_invoke_call_before_installer",
    )
    _need(not any(_installer_call(node) for node in prefix), "worker_installer_before_boundary")

    function = ast.FunctionDef(
        name="_prepare_before_worker_installer",
        args=original.args,
        body=list(prefix)
        + [
            ast.Return(
                value=ast.Dict(
                    keys=[
                        ast.Constant("public_rows"),
                        ast.Constant("full_union_rows"),
                        ast.Constant("software_rows"),
                        ast.Constant("held_rows"),
                        ast.Constant("profiler_modules"),
                        ast.Constant("boundary"),
                    ],
                    values=[
                        ast.Call(func=ast.Name(id="len", ctx=ast.Load()), args=[ast.Name(id="full", ctx=ast.Load())], keywords=[]),
                        ast.Call(func=ast.Name(id="len", ctx=ast.Load()), args=[ast.Name(id="full_union", ctx=ast.Load())], keywords=[]),
                        ast.Call(func=ast.Name(id="len", ctx=ast.Load()), args=[ast.Name(id="software", ctx=ast.Load())], keywords=[]),
                        ast.Call(func=ast.Name(id="len", ctx=ast.Load()), args=[ast.Name(id="rows", ctx=ast.Load())], keywords=[]),
                        ast.Call(func=ast.Name(id="len", ctx=ast.Load()), args=[ast.Name(id="profiler_rows", ctx=ast.Load())], keywords=[]),
                        ast.Constant("before_r5_worker_installer"),
                    ],
                )
            )
        ],
        decorator_list=[],
        returns=None,
        type_comment=None,
    )
    ast.copy_location(function, original)
    ast.fix_missing_locations(function)
    try:
        code = compile(ast.Module(body=[function], type_ignores=[]), str(ROOT / ENTRY_REL), "exec", dont_inherit=True)
        namespace = entry_module.__dict__
        exec(code, namespace, namespace)
    except BaseException:
        raise PreparationError("preinstaller_prefix_compile_failed") from None
    prepared = namespace.get("_prepare_before_worker_installer")
    _need(
        type(prepared) is types.FunctionType
        and prepared.__globals__ is namespace
        and prepared.__code__.co_filename == str(ROOT / ENTRY_REL)
        and prepared.__code__.co_name == "_prepare_before_worker_installer",
        "preinstaller_prefix_binding_invalid",
    )
    return prepared


def _safe_failure_code(error: BaseException, entry_module: types.ModuleType | None, v4: types.ModuleType):
    allowed_types = [PreparationError, v4.RootHeldScopeV4Error, v4._V3_MODULE.RootHeldSourceError]
    if entry_module is not None:
        allowed_types.append(entry_module.RootHeldEntryError)
    if type(error) not in tuple(allowed_types) or not error.args:
        return "preparation_failed"
    value = error.args[0]
    return value if type(value) is str and _SAFE_CODE.fullmatch(value) else "preparation_failed"


def prepare_root_source_verification(
    scope: object,
    v4: object,
    payload_raw: bytes,
    *,
    requested: bool = False,
) -> dict[str, object]:
    """Run Entry R2 through its fixed pre-installer boundary.

    ``scope`` must already be a same-thread, production ``RootHeldScopeV4``
    with the complete source map held. This function does not create or extend
    a scope itself; Entry R2 derives/validates the complete map and performs
    the pinned V4/R29 proof and source transforms. On success the same scope
    receives its ordinary V3 postverify and close. Any failure retains it.
    """

    if requested is not True:
        return {
            "schema": SCHEMA,
            "status": "BLOCKED",
            "reason_code": "preparation_request_required",
            "evidence_level": "NONE",
        }
    try:
        module = _validate_v4_module(v4)
        _validate_production_scope(scope, module)
    except BaseException as error:
        return {
            "schema": SCHEMA,
            "status": "BLOCKED",
            "reason_code": "production_scope_required",
            "evidence_level": "NONE",
        }

    entry_module = None
    try:
        _need(type(payload_raw) is bytes and 0 < len(payload_raw) <= 2 * 1024 * 1024,
              "payload_bytes_invalid")
        public = scope.public_map
        _need(type(public) is dict and public.get(_path_key(ROOT / ENTRY_REL)) == ENTRY_SHA256,
              "entry_source_not_in_public_scope")
        entry_raw = scope.read_held(ROOT / ENTRY_REL, ENTRY_SHA256, MAX_ENTRY_BYTES)
        _need(type(entry_raw) is bytes and _sha(entry_raw) == ENTRY_SHA256, "entry_source_held_bytes_invalid")
        entry_module = _load_entry_module(entry_raw)
        prefix = _compile_preinstaller_prefix(entry_module, entry_raw)
        summary = prefix(scope, module, payload_raw, require_production=True)
        expected = {
            "public_rows": 582,
            "software_rows": 5,
            "profiler_modules": 3,
            "boundary": "before_r5_worker_installer",
        }
        _need(type(summary) is dict and all(summary.get(key) == value for key, value in expected.items()),
              "preinstaller_summary_invalid")
        _need(type(summary.get("full_union_rows")) is int and summary["full_union_rows"] >= 582,
              "preinstaller_full_union_count_invalid")
        _need(type(summary.get("held_rows")) is int and summary["held_rows"] >= 587,
              "preinstaller_held_row_count_invalid")
        closed = scope.release(0, True)
        if closed is not True:
            _retain(scope, module, entry_module)
            return {
                "schema": SCHEMA,
                "status": "BLOCKED_RETAINED",
                "reason_code": "source_scope_close_not_confirmed",
                "evidence_level": "ROOT_HELD_PREPARATION_ONLY",
                "scope_state": str(scope.state),
            }
        return {
            "schema": SCHEMA,
            "status": "PREPARATION_VERIFIED_NO_AUTHORITY",
            "reason_code": "preinstaller_source_gate_complete",
            "evidence_level": "ROOT_HELD_PREPARATION_ONLY",
            "public_rows": summary["public_rows"],
            "full_union_rows": summary["full_union_rows"],
            "software_rows": summary["software_rows"],
            "held_rows": summary["held_rows"],
            "profiler_modules": summary["profiler_modules"],
            "boundary": summary["boundary"],
            "scope_state": "CLOSED",
            "authority": "NONE",
            "installer": "NOT_ENTERED",
            "worker": "NOT_ENTERED",
        }
    except BaseException as error:
        code = _safe_failure_code(error, entry_module, module)
        try:
            scope.release(2, False)
        except BaseException:
            pass
        _retain(scope, module, entry_module)
        return {
            "schema": SCHEMA,
            "status": "BLOCKED_RETAINED",
            "reason_code": code,
            "evidence_level": "ROOT_HELD_PREPARATION_ONLY",
            "scope_state": "RETAINED",
            "authority": "NONE",
            "installer": "NOT_ENTERED",
            "worker": "NOT_ENTERED",
        }


def _retain(*references: object) -> None:
    if references and not any(item is references[0] for item in _RETAINED):
        _RETAINED.append(references)

