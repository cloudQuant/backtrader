"""Source-pinned bridge from the frozen R27 child payload to Root-held entry R2.

The parent-side caller keeps the frozen R27 supervisor's validation, Job,
suspended-process, image-observation, stream, and cleanup code. This module
adds its own and the entry's source pins to that supervisor's fixed input map,
then replaces only the final child ``module.main`` dispatch with a bounded
load of the exact R2 entry and its ``run(payload_raw)`` call. The entry remains
closed on disk and is enabled in the child only after the child rechecks its
own pinned bytes. This bridge does not establish provider/account authority or
Optional16 acceptance.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.machinery
import os
from pathlib import Path
import re
import types


ROOT = Path(r"D:\source_code\backtrader")
BRIDGE_REL = Path("scripts/iteration41_optional16_r33_root_held_child_bridge_r2.py")
WHOLE_REL = Path("scripts/iteration41_optional16_r33_whole_call_supervisor_r27.py")
WHOLE_SHA256 = "bfdd7bc9530b9ded9722ec86c1c184f36de3fb6337fb6688cbe15fa0f77f2876"
ENTRY_REL = Path("scripts/iteration41_optional16_r33_root_held_entry_r2.py")
ENTRY_SHA256 = "80295025d0145893f4f63745182042812284434e4e7e5b4388b89d82623c2ead"
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_WHOLE_MODULE_NAME = "_iteration41_optional16_r33_whole_call_supervisor_r27_bridge_r2"
_ENTRY_MODULE_NAME = "_iteration41_optional16_r33_root_held_entry_r2_bridged"
_BRIDGE_INSTALL_SEAL = object()


class ChildBridgeError(RuntimeError):
    """Fixed labels only; never includes paths or source bytes."""


def _need(condition: object, code: str) -> None:
    if not condition:
        raise ChildBridgeError(code)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _valid_sha(value: object) -> bool:
    return type(value) is str and _HEX64.fullmatch(value) is not None


_ROOT_ACTIVE_ALIAS_METHOD = '''def bind_root_active_driver_alias(self, invoke, payload):
    driver = payload.get("driver") if type(payload) is dict else None
    driver_fields = {
        "path", "sha256", "test_path", "test_sha256", "packet_dir",
        "packet_pins", "review_dir", "review_pins", "review_readme_sha256",
        "active_path",
    }
    spec = getattr(invoke, "__spec__", None)
    _need(
        type(invoke) is types.ModuleType
        and getattr(invoke, "__verified_source_sha256__", None) == R27_INVOKE_SHA256
        and _path_key(getattr(invoke, "__file__", ""))
        == _path_key(ROOT / R27_INVOKE_REL)
        and _path_key(getattr(spec, "origin", ""))
        == _path_key(ROOT / R27_INVOKE_REL)
        and type(payload) is dict
        and payload.get("schema") == getattr(invoke, "_CHILD_ACTIVATION_SCHEMA", None)
        and type(driver) is dict
        and set(driver) == driver_fields
        and _path_key(Path(getattr(invoke, "DRIVER", "")))
        == _path_key(ROOT / R19_DRIVER_REL)
        and _path_key(Path(driver["path"])) == _path_key(invoke.DRIVER)
        and driver["sha256"] == R19_DRIVER_SHA256
        and _valid_sha(driver["test_sha256"])
        and type(driver["packet_pins"]) is dict
        and set(driver["packet_pins"]) == set(invoke._PACKET_REQUIRED)
        and all(_valid_sha(value) for value in driver["packet_pins"].values())
        and type(driver["review_pins"]) is dict
        and set(driver["review_pins"]) == set(invoke._REVIEW_REQUIRED)
        and all(_valid_sha(value) for value in driver["review_pins"].values())
        and _path_key(Path(driver["active_path"])) == _path_key(invoke.DRIVER_ACTIVE_PATH)
        and _path_key(Path(driver["active_path"])) != _path_key(Path(driver["path"]))
        and _path_key(Path(driver["test_path"])) == _path_key(invoke.DRIVER_TEST)
        and _path_key(Path(driver["packet_dir"])) == _path_key(invoke.DRIVER_PACKET)
        and _path_key(Path(driver["review_dir"])) == _path_key(invoke.DRIVER_REVIEW)
        and driver["review_readme_sha256"]
        == driver["review_pins"].get("README.md"),
        "root_active_driver_alias_binding_invalid",
    )
    _need(self._scope.test_only is False, "root_active_driver_alias_fake_scope")
    _need(self._worker_view_for_call() is None, "root_active_driver_alias_not_owner")
    _need(not self._artifact_aliases, "root_active_driver_alias_not_first")
    origin = _path_key(Path(driver["active_path"]))
    physical = _path_key(ROOT / R19_DRIVER_REL)
    digest = R19_DRIVER_SHA256
    target = self._rows.get(physical)
    _need(
        target is not None
        and target[0] == digest
        and target[1] == "public"
        and type(target[2]) is int
        and 0 < target[2] <= MAX_SOURCE_BYTES,
        "root_active_driver_snapshot_unheld",
    )
    self._scope.verify_pin(physical, digest)
    _need(origin not in self._rows and origin not in self._artifact_aliases,
          "root_active_driver_alias_conflict")
    self._artifact_aliases[origin] = (physical, digest)
'''


def transform_entry_source(raw: bytes) -> tuple[bytes, dict[str, object]]:
    """Add only the production active-driver alias to the exact R2 source.

    The original on-disk entry stays the source identity checked by ``run``.
    The transformed bytes are separately hashed and loaded by this pinned
    bridge. Its only behavior change is an actual-mode alias from the R27
    active label to the already held R19 source row; sourcefake behavior is
    unchanged.
    """
    _need(type(raw) is bytes and _sha(raw) == ENTRY_SHA256, "entry_transform_source_pin_invalid")
    try:
        tree = ast.parse(raw.decode("utf-8", "strict"))
    except (UnicodeError, SyntaxError):
        raise ChildBridgeError("entry_transform_parse_failed") from None
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "_ScopeReader"]
    execute_functions = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_execute_with_scope"
    ]
    _need(len(classes) == 1 and len(execute_functions) == 1, "entry_transform_anchor_missing")
    scope_class = classes[0]
    _need(
        not any(
            isinstance(node, ast.FunctionDef) and node.name == "bind_root_active_driver_alias"
            for node in scope_class.body
        ),
        "entry_transform_method_already_present",
    )
    sourcefake_methods = [
        node for node in scope_class.body
        if isinstance(node, ast.FunctionDef) and node.name == "bind_sourcefake_active_driver_alias"
    ]
    _need(len(sourcefake_methods) == 1, "entry_transform_sourcefake_method_anchor_invalid")
    method_tree = ast.parse(_ROOT_ACTIVE_ALIAS_METHOD)
    _need(
        len(method_tree.body) == 1
        and isinstance(method_tree.body[0], ast.FunctionDef)
        and method_tree.body[0].name == "bind_root_active_driver_alias",
        "entry_transform_method_template_invalid",
    )
    scope_class.body.insert(scope_class.body.index(sourcefake_methods[0]) + 1, method_tree.body[0])

    execute = execute_functions[0]
    sourcefake_anchors = []
    for node in ast.walk(execute):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if not (
            isinstance(test, ast.Compare)
            and isinstance(test.left, ast.Name)
            and test.left.id == "_sourcefake_token"
            and len(test.ops) == 1
            and isinstance(test.ops[0], ast.IsNot)
            and len(test.comparators) == 1
            and isinstance(test.comparators[0], ast.Constant)
            and test.comparators[0].value is None
        ):
            continue
        if not (
            len(node.body) == 1
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Call)
            and isinstance(node.body[0].value.func, ast.Attribute)
            and isinstance(node.body[0].value.func.value, ast.Name)
            and node.body[0].value.func.value.id == "reader"
            and node.body[0].value.func.attr == "bind_sourcefake_active_driver_alias"
            and len(node.body[0].value.args) == 1
            and isinstance(node.body[0].value.args[0], ast.Name)
            and node.body[0].value.args[0].id == "invoke"
            and not node.body[0].value.keywords
        ):
            continue
        sourcefake_anchors.append(node)
    _need(len(sourcefake_anchors) == 1, "entry_transform_sourcefake_branch_anchor_invalid")

    payload_validation_anchors = []
    for node in ast.walk(execute):
        if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
            continue
        value = node.value
        if not (
            isinstance(value.func, ast.Name)
            and value.func.id == "_need"
            and len(value.args) == 2
            and isinstance(value.args[0], ast.Compare)
            and isinstance(value.args[0].left, ast.Name)
            and value.args[0].left.id == "payload"
            and len(value.args[0].ops) == 1
            and isinstance(value.args[0].ops[0], ast.Eq)
            and len(value.args[0].comparators) == 1
            and isinstance(value.args[0].comparators[0], ast.Call)
            and isinstance(value.args[0].comparators[0].func, ast.Attribute)
            and isinstance(value.args[0].comparators[0].func.value, ast.Name)
            and value.args[0].comparators[0].func.value.id == "helper"
            and value.args[0].comparators[0].func.attr == "build_child_payload"
            and len(value.args[0].comparators[0].args) == 3
            and all(isinstance(arg, ast.Name) for arg in value.args[0].comparators[0].args)
            and [arg.id for arg in value.args[0].comparators[0].args]
            == ["invoke", "whole", "deadline"]
            and isinstance(value.args[1], ast.Constant)
            and value.args[1].value == "payload_not_parent_derived"
            and not value.keywords
        ):
            continue
        payload_validation_anchors.append(node)
    _need(len(payload_validation_anchors) == 1,
          "entry_transform_payload_validation_anchor_invalid")
    call_alias = ast.If(
        test=ast.Compare(
            left=ast.Name(id="_sourcefake_token", ctx=ast.Load()),
            ops=[ast.Is()],
            comparators=[ast.Constant(value=None)],
        ),
        body=[
            ast.Expr(
                ast.Call(
                    func=ast.Attribute(
                        value=ast.Name(id="reader", ctx=ast.Load()),
                        attr="bind_root_active_driver_alias",
                        ctx=ast.Load(),
                    ),
                    args=[ast.Name(id="invoke", ctx=ast.Load()), ast.Name(id="payload", ctx=ast.Load())],
                    keywords=[],
                )
            )
        ],
        orelse=[],
    )
    insert_at = execute.body.index(payload_validation_anchors[0]) + 1
    execute.body.insert(insert_at, call_alias)
    ast.fix_missing_locations(tree)
    transformed = (ast.unparse(tree) + "\n").encode("utf-8")
    _need(0 < len(transformed) <= 256 * 1024, "entry_transform_size_invalid")
    try:
        compile(transformed, str(ROOT / ENTRY_REL), "exec", dont_inherit=True)
    except SyntaxError:
        raise ChildBridgeError("entry_transform_compile_failed") from None
    receipt = {
        "schema": "iteration41.optional16.r33.root-held-entry-bridge-transform.r2",
        "source_sha256": ENTRY_SHA256,
        "transformed_sha256": _sha(transformed),
        "sourcefake_anchor_count": 1,
        "payload_binding_anchor_count": 1,
        "production_alias_method_count": 1,
    }
    return transformed, receipt


def _path_key(value: object) -> str:
    _need(type(value) is str or isinstance(value, Path), "bridge_path_type_invalid")
    raw = os.fspath(value)
    _need(type(raw) is str and raw and "\x00" not in raw, "bridge_path_invalid")
    return os.path.normcase(os.path.normpath(raw)).casefold()


def _module_reference(raw: bytes, path: Path, name: str) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__file__ = str(path)
    module.__package__ = ""
    module.__cached__ = None
    module.__loader__ = None
    module.__spec__ = importlib.machinery.ModuleSpec(name, loader=None, origin=str(path))
    module.__verified_source_sha256__ = _sha(raw)
    try:
        exec(compile(raw, str(path), "exec", dont_inherit=True), module.__dict__, module.__dict__)
    except BaseException:
        raise ChildBridgeError("bridge_reference_compile_failed") from None
    return module


def _verify_loaded_function(actual: object, expected: object, module: types.ModuleType) -> None:
    _need(type(actual) is types.FunctionType and type(expected) is types.FunctionType,
          "bridge_source_function_type_invalid")
    _need(
        actual.__globals__ is module.__dict__
        and actual.__code__ == expected.__code__
        and actual.__defaults__ == expected.__defaults__
        and actual.__kwdefaults__ == expected.__kwdefaults__
        and actual.__closure__ is None
        and expected.__closure__ is None
        and actual.__name__ == expected.__name__
        and actual.__qualname__ == expected.__qualname__
        and actual.__module__ == expected.__module__,
        "bridge_source_function_mismatch",
    )


def load_supervisor(raw: bytes) -> types.ModuleType:
    """Compile the exact frozen R27 supervisor from caller-held public bytes."""
    _need(type(raw) is bytes and _sha(raw) == WHOLE_SHA256, "r27_whole_source_pin_mismatch")
    path = ROOT / WHOLE_REL
    module = _module_reference(raw, path, _WHOLE_MODULE_NAME)
    _need(module.__dict__.get("ROOT_SELF_PATH") == path, "r27_whole_source_path_mismatch")
    return module


def _assert_module_source(module: object, raw: bytes, path: Path, digest: str, name: str) -> types.ModuleType:
    _need(type(module) is types.ModuleType, "bridge_module_type_invalid")
    try:
        actual_file = module.__file__
        actual_spec = module.__spec__
        actual_origin = actual_spec.origin
    except BaseException:
        raise ChildBridgeError("bridge_module_origin_invalid") from None
    _need(
        type(raw) is bytes
        and _valid_sha(digest)
        and _sha(raw) == digest
        and module.__name__ == name
        and _path_key(actual_file) == _path_key(path)
        and _path_key(actual_origin) == _path_key(path)
        and module.__dict__.get("__verified_source_sha256__") == digest,
        "bridge_module_source_unbound",
    )
    reference = _module_reference(raw, path, name)
    return reference


def _child_dispatch_tail(bridge_path: Path, bridge_sha256: str) -> str:
    bridge_literal = repr(str(bridge_path))
    entry_literal = repr(str(ROOT / ENTRY_REL))
    entry_name_literal = repr(_ENTRY_MODULE_NAME)
    return f'''_R27_CHILD_PHASE = "child_invoke_source"
_R27_DRIVER_ALIAS = "_iteration41_optional16_r33_r19_child_driver_activation"
_R27_DRIVER_MODULE = sys.modules.get(_R27_DRIVER_ALIAS)
_R27_DRIVER_SPEC = getattr(_R27_DRIVER_MODULE, "__spec__", None)
_R27_DRIVER_PATH = driver.get("path") if type(driver) is dict else None
_R27_DRIVER_ACTIVE_PATH = driver.get("active_path") if type(driver) is dict else None
_R27_BINDING_RESULT_KEYS = (
    "schema", "status", "r16_composite_validated", "r17_composite_validated",
    "r18_composite_validated", "r19_driver_activation_validated",
    "driver_expected_public_pin_count", "r2_inert_driver_pin_count",
    "driver_software_pin_count", "driver_path_alias_count",
    "driver_activation_ready", "invoke_activation_ready", "driver_sha256",
    "driver_test_sha256", "driver_packet_pin_count", "driver_review_pin_count",
    "activation_enabled",
)
if (type(result) is not dict
        or set(result) != set(_R27_BINDING_RESULT_KEYS)
        or result.get("schema") != "iteration41.optional16.r33.whole-call.r27-child-activation.v1"
        or result.get("status") != "COMPLETE_CHILD_BINDING_VALIDATED"
        or result.get("r16_composite_validated") is not True
        or result.get("r17_composite_validated") is not True
        or result.get("r18_composite_validated") is not True
        or result.get("r19_driver_activation_validated") is not True
        or result.get("driver_activation_ready") is not True
        or result.get("invoke_activation_ready") is not True
        or result.get("activation_enabled") is not True
        or result.get("driver_expected_public_pin_count") != cfg["counts"]["active_public_paths"]
        or result.get("driver_software_pin_count") != cfg["counts"]["software_paths"]
        or result.get("driver_path_alias_count") != cfg["counts"]["path_aliases"]
        or result.get("driver_sha256") != driver.get("sha256")
        or result.get("driver_test_sha256") != driver.get("test_sha256")
        or any(type(result.get(name)) is not int for name in (
            "driver_expected_public_pin_count", "r2_inert_driver_pin_count",
            "driver_software_pin_count", "driver_path_alias_count",
            "driver_packet_pin_count", "driver_review_pin_count"))
        or result.get("r2_inert_driver_pin_count", -1) < 0
        or result.get("driver_packet_pin_count") != len(driver.get("packet_pins", ()))
        or result.get("driver_review_pin_count") != len(driver.get("review_pins", ()))
        or type(getattr(_R27_DRIVER_MODULE, "_KEEPALIVES", None)) is not list
        or _R27_DRIVER_MODULE._KEEPALIVES):
    raise SystemExit(2)
_R27_BINDING_RESULT_REFERENCE = result
_R27_BINDING_RESULT_SNAPSHOT = tuple(
    (key, result[key]) for key in _R27_BINDING_RESULT_KEYS
)
if (type(driver_source) is not bytes
        or hashlib.sha256(driver_source).hexdigest() != driver.get("sha256")
        or type(_R27_DRIVER_MODULE) is not types.ModuleType
        or sys.modules.get(_R27_DRIVER_ALIAS) is not _R27_DRIVER_MODULE
        or _R27_DRIVER_MODULE.__name__ != _R27_DRIVER_ALIAS
        or _R27_DRIVER_MODULE.__file__ != _R27_DRIVER_ACTIVE_PATH
        or getattr(_R27_DRIVER_SPEC, "origin", None) != _R27_DRIVER_PATH
        or getattr(_R27_DRIVER_MODULE, "__verified_source_sha256__", None) != driver.get("sha256")
        or getattr(_R27_DRIVER_MODULE, "ROOT_DRIVER_PATH", None) != Path(_R27_DRIVER_ACTIVE_PATH)
        or getattr(_R27_DRIVER_MODULE, "ROOT_ENABLED", None) is not True
        or getattr(_R27_DRIVER_MODULE, "ROOT_REVIEWED_ACTIVATION", None) is not True
        or getattr(_R27_DRIVER_MODULE, "ROOT_DRIVER_REVIEW_READY", None) is not True
        or getattr(_R27_DRIVER_MODULE, "ROOT_DRIVER_SHA256", None) != driver.get("sha256")
        or getattr(_R27_DRIVER_MODULE, "DRIVER_TEST_SHA256", None) != driver.get("test_sha256")
        or getattr(_R27_DRIVER_MODULE, "ROOT_DRIVER_PACKET_PINS", None) != driver.get("packet_pins")
        or getattr(_R27_DRIVER_MODULE, "ROOT_DRIVER_REVIEW_PINS", None) != driver.get("review_pins")
        or getattr(_R27_DRIVER_MODULE, "DRIVER_PACKET", None) != Path(driver.get("packet_dir"))
        or getattr(_R27_DRIVER_MODULE, "DRIVER_REVIEW", None) != Path(driver.get("review_dir"))):
    raise SystemExit(2)
# R27 validated and activated this exact declaration module above. R2's pinned
# R5 binder then performs its own source admission and production bind in this
# same child. Reinitialize the same alias from the already hash-checked source
# bytes so that the second validator sees the declared source namespace; no
# alias is removed or replaced.
_R27_DRIVER_MODULE.__file__ = _R27_DRIVER_PATH
exec(compile(driver_source, _R27_DRIVER_PATH, "exec", dont_inherit=True),
     _R27_DRIVER_MODULE.__dict__, _R27_DRIVER_MODULE.__dict__)
if (result is not _R27_BINDING_RESULT_REFERENCE
        or tuple((key, result.get(key)) for key in _R27_BINDING_RESULT_KEYS)
        != _R27_BINDING_RESULT_SNAPSHOT
        or type(_R27_DRIVER_MODULE._KEEPALIVES) is not list
        or _R27_DRIVER_MODULE._KEEPALIVES
        or sys.modules.get(_R27_DRIVER_ALIAS) is not _R27_DRIVER_MODULE
        or _R27_DRIVER_MODULE.__file__ != _R27_DRIVER_PATH
        or getattr(_R27_DRIVER_SPEC, "origin", None) != _R27_DRIVER_PATH
        or getattr(_R27_DRIVER_MODULE, "__verified_source_sha256__", None) != driver.get("sha256")
        or getattr(_R27_DRIVER_MODULE, "ROOT_ENABLED", None) is not False
        or getattr(_R27_DRIVER_MODULE, "ROOT_REVIEWED_ACTIVATION", None) is not False
        or getattr(_R27_DRIVER_MODULE, "ROOT_DRIVER_REVIEW_READY", None) is not False):
    raise SystemExit(2)
_R27_BRIDGE_SOURCE_PATH = {bridge_literal}
_R27_BRIDGE_SOURCE_SHA256 = {bridge_sha256!r}
_R27_ENTRY_SOURCE_PATH = {entry_literal}
_R27_ENTRY_SOURCE_SHA256 = {ENTRY_SHA256!r}
try:
    with open(_R27_BRIDGE_SOURCE_PATH, "rb") as _r27_bridge_stream:
        _r27_bridge_raw = _r27_bridge_stream.read(128 * 1024 + 1)
    with open(_R27_ENTRY_SOURCE_PATH, "rb") as _r27_entry_stream:
        _r27_entry_raw = _r27_entry_stream.read(256 * 1024 + 1)
except OSError:
    raise SystemExit(2)
if (len(_r27_bridge_raw) > 128 * 1024
        or hashlib.sha256(_r27_bridge_raw).hexdigest() != _R27_BRIDGE_SOURCE_SHA256
        or len(_r27_entry_raw) > 256 * 1024
        or hashlib.sha256(_r27_entry_raw).hexdigest() != _R27_ENTRY_SOURCE_SHA256):
    raise SystemExit(2)
_R27_BRIDGE_MODULE_NAME = "_iteration41_optional16_r33_root_held_child_bridge_r2_loaded"
if _R27_BRIDGE_MODULE_NAME in sys.modules:
    raise SystemExit(2)
bridge_module = types.ModuleType(_R27_BRIDGE_MODULE_NAME)
bridge_module.__file__ = _R27_BRIDGE_SOURCE_PATH
bridge_module.__package__ = ""
bridge_module.__cached__ = None
bridge_module.__loader__ = None
bridge_module.__spec__ = importlib.machinery.ModuleSpec(
    _R27_BRIDGE_MODULE_NAME, loader=None, origin=_R27_BRIDGE_SOURCE_PATH
)
bridge_module.__verified_source_sha256__ = _R27_BRIDGE_SOURCE_SHA256
sys.modules[_R27_BRIDGE_MODULE_NAME] = bridge_module
exec(compile(_r27_bridge_raw, _R27_BRIDGE_SOURCE_PATH, "exec", dont_inherit=True),
     bridge_module.__dict__, bridge_module.__dict__)
if (bridge_module.__name__ != _R27_BRIDGE_MODULE_NAME
        or bridge_module.__file__ != _R27_BRIDGE_SOURCE_PATH
        or bridge_module.__spec__.origin != _R27_BRIDGE_SOURCE_PATH
        or bridge_module.__verified_source_sha256__ != _R27_BRIDGE_SOURCE_SHA256):
    raise SystemExit(2)
bridge_reference = bridge_module._module_reference(
    _r27_bridge_raw, Path(_R27_BRIDGE_SOURCE_PATH), _R27_BRIDGE_MODULE_NAME
)
for _r27_bridge_function_name in (
        "_module_reference", "_verify_loaded_function", "transform_entry_source"):
    bridge_module._verify_loaded_function(
        bridge_module.__dict__.get(_r27_bridge_function_name),
        bridge_reference.__dict__.get(_r27_bridge_function_name),
        bridge_module,
    )
_r27_transformed_entry_raw, _r27_transform_receipt = bridge_module.transform_entry_source(
    _r27_entry_raw
)
_r27_transformed_entry_sha256 = hashlib.sha256(_r27_transformed_entry_raw).hexdigest()
if (type(_r27_transform_receipt) is not dict
        or tuple(sorted(_r27_transform_receipt.items())) != tuple(sorted((
            ("schema", "iteration41.optional16.r33.root-held-entry-bridge-transform.r2"),
            ("source_sha256", _R27_ENTRY_SOURCE_SHA256),
            ("transformed_sha256", _r27_transformed_entry_sha256),
            ("sourcefake_anchor_count", 1),
            ("payload_binding_anchor_count", 1),
            ("production_alias_method_count", 1),
        )))):
    raise SystemExit(2)
transformed_entry_reference = bridge_module._module_reference(
    _r27_transformed_entry_raw,
    Path(_R27_ENTRY_SOURCE_PATH),
    {entry_name_literal},
)
_R27_ENTRY_MODULE_NAME = {entry_name_literal}
if _R27_ENTRY_MODULE_NAME in sys.modules:
    raise SystemExit(2)
_R27_CHILD_PHASE = "child_invoke_main"
entry_module = types.ModuleType(_R27_ENTRY_MODULE_NAME)
entry_module.__file__ = _R27_ENTRY_SOURCE_PATH
entry_module.__package__ = ""
entry_module.__cached__ = None
entry_module.__loader__ = None
entry_module.__spec__ = importlib.machinery.ModuleSpec(
    _R27_ENTRY_MODULE_NAME, loader=None, origin=_R27_ENTRY_SOURCE_PATH
)
entry_module.__verified_source_sha256__ = _R27_ENTRY_SOURCE_SHA256
sys.modules[_R27_ENTRY_MODULE_NAME] = entry_module
exec(compile(_r27_transformed_entry_raw, _R27_ENTRY_SOURCE_PATH, "exec", dont_inherit=True),
     entry_module.__dict__, entry_module.__dict__)
entry_module.__root_held_bridge_transform_sha256__ = _r27_transformed_entry_sha256
entry_module.__root_held_bridge_transform_receipt__ = (
    "iteration41.optional16.r33.root-held-entry-bridge-transform.r2",
    _R27_ENTRY_SOURCE_SHA256,
    _r27_transformed_entry_sha256,
    1,
    1,
    1,
)
if (entry_module.__dict__.get("ROOT_ACTUAL_ENABLED") is not False
        or entry_module.__dict__.get("ROOT_ENTRY_SOURCE_SHA256") is not None
        or entry_module.__dict__.get("__verified_source_sha256__") != _R27_ENTRY_SOURCE_SHA256
        or entry_module.__file__ != _R27_ENTRY_SOURCE_PATH
        or entry_module.__spec__.origin != _R27_ENTRY_SOURCE_PATH
        or type(entry_module.__dict__.get("run")) is not types.FunctionType
        or entry_module.run.__globals__ is not entry_module.__dict__
        or entry_module.run.__code__.co_name != "run"
        or entry_module.run.__code__.co_freevars):
    raise SystemExit(2)
bridge_module._verify_loaded_function(
    entry_module.run, transformed_entry_reference.run, entry_module
)
bridge_module._verify_loaded_function(
    entry_module._ScopeReader.bind_root_active_driver_alias,
    transformed_entry_reference._ScopeReader.bind_root_active_driver_alias,
    entry_module,
)
if (entry_module.__root_held_bridge_transform_sha256__ != _r27_transformed_entry_sha256
        or entry_module.__root_held_bridge_transform_receipt__[1] != _R27_ENTRY_SOURCE_SHA256
        or entry_module.__root_held_bridge_transform_receipt__[2] != _r27_transformed_entry_sha256):
    raise SystemExit(2)
entry_module.ROOT_ENTRY_SOURCE_SHA256 = _R27_ENTRY_SOURCE_SHA256
entry_module.ROOT_ACTUAL_ENABLED = True
if (entry_module.ROOT_ACTUAL_ENABLED is not True
        or entry_module.ROOT_ENTRY_SOURCE_SHA256 != _R27_ENTRY_SOURCE_SHA256):
    raise SystemExit(2)
entry_result = entry_module.run(raw)
if (type(entry_result) is not dict
        or entry_result.get("schema") != "iteration41.optional16.r33.root-held-entry.r2"):
    raise RuntimeError("root_entry_result_shape_invalid")
entry_status = entry_result.get("status")
if entry_status == "WORKER_CLEAN_POSTVERIFIED":
    if (entry_result.get("worker_joined") is not True
            or entry_result.get("scope_released") is not True):
        raise RuntimeError("root_entry_clean_result_invalid")
    entry_custody_state = "RELEASED"
    entry_postverified = True
    entry_retained = False
elif entry_status in {{"WORKER_UNCERTAIN_RETAINED", "WORKER_UNJOINED_RETAINED"}}:
    if entry_result.get("scope_released") is not False:
        raise RuntimeError("root_entry_retained_result_invalid")
    entry_custody_state = "HELD"
    entry_postverified = False
    entry_retained = True
else:
    raise RuntimeError("root_entry_status_unmapped")
_R27_ENTRY_RETAINED = globals().setdefault("_R27_ENTRY_RETAINED", [])
_R27_ENTRY_RETAINED.append((entry_module, entry_result))
entry_observation = {{
    "schema": "iteration41.optional16.r33.root-invoke-r12.observation.v1",
    "status": "ROOT_UNCERTAIN_RETAINED_NO_PARSE",
    "reason_code": "root_invocation_or_postverify_uncertain",
    "source_scope_released": entry_custody_state == "RELEASED",
    "complete_custody_postverified": entry_postverified,
    "source_custody_state": entry_custody_state,
    "source_scope_references_retained_until_root_process_exit": True,
    "complete_custody_retained_until_root_process_exit": entry_retained,
    "late_frame_parsed": False,
    "public_raw_saved": False,
    "strict_cases_passed": 0,
    "case_pass": False,
    "acceptance": "NOT_ACCEPTED_OPTIONAL16",
}}
sys.stdout.write(json.dumps(entry_observation, sort_keys=True, separators=(",", ":")) + "\\n")
sys.stdout.flush()
_R27_EXPECTED_EXIT = True
raise SystemExit(2)
'''


def _build_child_body(whole: types.ModuleType, bridge_path: Path, bridge_sha256: str) -> str:
    body = whole.__dict__.get("_CHILD_BOOTSTRAP_BODY")
    _need(type(body) is str and body, "r27_child_body_missing")
    try:
        tree = ast.parse(body)
    except SyntaxError:
        raise ChildBridgeError("r27_child_body_parse_failed") from None
    binder_calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "module"
        and node.func.attr == "bind_child_activation"
    ]
    main_assignments = [
        node for node in tree.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "_R27_MAIN_RESULT"
    ]
    _need(len(binder_calls) == 1 and len(main_assignments) == 1,
          "r27_child_dispatch_anchor_invalid")
    main_call = main_assignments[0].value
    _need(
        isinstance(main_call, ast.Call)
        and isinstance(main_call.func, ast.Attribute)
        and isinstance(main_call.func.value, ast.Name)
        and main_call.func.value.id == "module"
        and main_call.func.attr == "main"
        and len(main_call.args) == 1
        and isinstance(main_call.args[0], ast.List)
        and len(main_call.args[0].elts) == 1
        and isinstance(main_call.args[0].elts[0], ast.Constant)
        and main_call.args[0].elts[0].value == "--execute-r33-root-r5",
        "r27_child_main_anchor_invalid",
    )
    old_tail = '''_R27_CHILD_PHASE = "child_invoke_main"
_R27_MAIN_RESULT = module.main(["--execute-r33-root-r5"])
if type(_R27_MAIN_RESULT) is not int or _R27_MAIN_RESULT not in (0, 2):
    raise RuntimeError("child_main_return_code_invalid")
_R27_EXPECTED_EXIT = True
raise SystemExit(_R27_MAIN_RESULT)'''
    _need(body.count(old_tail) == 1, "r27_child_tail_anchor_invalid")
    updated = body.replace(old_tail, _child_dispatch_tail(bridge_path, bridge_sha256))
    _need(updated != body and len(updated.encode("utf-8")) <= 64 * 1024,
          "r27_child_bridge_size_invalid")
    try:
        compile(updated, "<r27-child-bootstrap-bridge-r2>", "exec", dont_inherit=True)
    except SyntaxError:
        raise ChildBridgeError("r27_child_bridge_compile_failed") from None
    return updated


class BridgeInstallation:
    __slots__ = (
        "whole",
        "bridge_path",
        "bridge_sha256",
        "entry_sha256",
        "child_body",
        "child_body_sha256",
        "fixed_inputs",
        "original_fixed_inputs",
        "fixed_inputs_closure",
        "_seal",
        "_frozen",
    )

    def __init__(
        self,
        *,
        whole,
        bridge_path,
        bridge_sha256,
        entry_sha256,
        child_body,
        child_body_sha256,
        fixed_inputs,
        original_fixed_inputs,
        fixed_inputs_closure,
        _seal,
    ):
        object.__setattr__(self, "whole", whole)
        object.__setattr__(self, "bridge_path", bridge_path)
        object.__setattr__(self, "bridge_sha256", bridge_sha256)
        object.__setattr__(self, "entry_sha256", entry_sha256)
        object.__setattr__(self, "child_body", child_body)
        object.__setattr__(self, "child_body_sha256", child_body_sha256)
        object.__setattr__(self, "fixed_inputs", fixed_inputs)
        object.__setattr__(self, "original_fixed_inputs", original_fixed_inputs)
        object.__setattr__(self, "fixed_inputs_closure", fixed_inputs_closure)
        object.__setattr__(self, "_seal", _seal)
        object.__setattr__(self, "_frozen", True)

    def __setattr__(self, name, value):
        if getattr(self, "_frozen", False):
            raise AttributeError("bridge_installation_immutable")
        object.__setattr__(self, name, value)


def install_child_bridge(
    whole: types.ModuleType,
    whole_raw: bytes,
    bridge_raw: bytes,
    bridge_sha256: str,
    entry_raw: bytes,
    entry_sha256: str,
) -> BridgeInstallation:
    """Install the exact entry dispatch into an already loaded frozen R27 module.

    ``whole_raw``, ``bridge_raw`` and ``entry_raw`` are caller-held bytes. The
    caller must keep the Root source scope alive across ``invoke``. This
    function adds only the bridge and entry source rows to the R27 fixed-input
    validator; it never changes any R27 readiness flag.
    """
    whole_path = ROOT / WHOLE_REL
    bridge_path = ROOT / BRIDGE_REL
    entry_path = ROOT / ENTRY_REL
    _need(
        type(whole) is types.ModuleType
        and type(whole_raw) is bytes
        and _sha(whole_raw) == WHOLE_SHA256
        and whole.__dict__.get("__verified_source_sha256__") == WHOLE_SHA256
        and whole.__name__ == _WHOLE_MODULE_NAME
        and _path_key(whole.__file__) == _path_key(whole_path)
        and _path_key(whole.__spec__.origin) == _path_key(whole_path),
        "r27_whole_module_unbound",
    )
    _need(
        type(bridge_raw) is bytes
        and _valid_sha(bridge_sha256)
        and _sha(bridge_raw) == bridge_sha256
        and _path_key(globals().get("__file__", "")) == _path_key(bridge_path)
        and type(globals().get("__spec__")) is importlib.machinery.ModuleSpec
        and _path_key(globals()["__spec__"].origin) == _path_key(bridge_path)
        and globals().get("__verified_source_sha256__") == bridge_sha256,
        "bridge_source_pin_invalid",
    )
    _need(
        type(entry_raw) is bytes
        and _valid_sha(entry_sha256)
        and entry_sha256 == ENTRY_SHA256
        and _sha(entry_raw) == ENTRY_SHA256,
        "entry_source_pin_invalid",
    )
    whole_reference = _module_reference(whole_raw, whole_path, _WHOLE_MODULE_NAME)
    for name in ("_fixed_inputs", "_verify_pins", "_activation_payload", "_wrap_child_bootstrap", "main"):
        _verify_loaded_function(
            whole.__dict__.get(name), whole_reference.__dict__.get(name), whole
        )
    bridge_reference = _module_reference(bridge_raw, bridge_path, "_bridge_reference")
    for name in ("install_child_bridge", "invoke", "load_supervisor"):
        actual = globals().get(name)
        expected = bridge_reference.__dict__.get(name)
        _need(type(actual) is types.FunctionType and type(expected) is types.FunctionType,
              "bridge_self_function_missing")
        _need(
            actual.__code__ == expected.__code__
            and actual.__defaults__ == expected.__defaults__
            and actual.__kwdefaults__ == expected.__kwdefaults__
            and actual.__closure__ is None
            and expected.__closure__ is None,
            "bridge_self_source_mismatch",
        )
    body = _build_child_body(whole, bridge_path, bridge_sha256)
    original_fixed_inputs = whole.__dict__.get("_fixed_inputs")
    _need(type(original_fixed_inputs) is types.FunctionType,
          "r27_fixed_inputs_callable_missing")

    def fixed_inputs_with_bridge():
        _need(whole.__dict__.get("_fixed_inputs") is fixed_inputs_with_bridge,
              "r27_fixed_inputs_bridge_replaced")
        pins = original_fixed_inputs()
        _need(type(pins) is dict, "r27_fixed_inputs_map_invalid")
        for path, digest in ((bridge_path, bridge_sha256), (entry_path, entry_sha256)):
            prior = pins.get(path)
            _need(prior is None or prior == digest, "r27_fixed_input_conflict")
            pins[path] = digest
        _need(20 <= len(pins) <= 64, "r27_fixed_input_count_invalid")
        return pins

    fixed_inputs_with_bridge.__name__ = "_fixed_inputs_with_root_held_child_bridge_r2"
    fixed_inputs_with_bridge.__qualname__ = fixed_inputs_with_bridge.__name__
    fixed_inputs_with_bridge.__module__ = __name__
    fixed_inputs_with_bridge.__defaults__ = None
    fixed_inputs_with_bridge.__kwdefaults__ = None
    fixed_inputs_with_bridge.__annotations__ = {}
    fixed_inputs_code = next(
        value for value in install_child_bridge.__code__.co_consts
        if type(value) is types.CodeType and value.co_name == "fixed_inputs_with_bridge"
    )
    _need(fixed_inputs_with_bridge.__code__ == fixed_inputs_code,
          "fixed_inputs_wrapper_source_mismatch")
    closure_values = tuple(
        (name, cell.cell_contents)
        for name, cell in zip(
            fixed_inputs_with_bridge.__code__.co_freevars,
            fixed_inputs_with_bridge.__closure__ or (),
        )
    )
    closure_map = dict(closure_values)
    _need(
        set(closure_map)
        == {
            "whole",
            "fixed_inputs_with_bridge",
            "original_fixed_inputs",
            "bridge_path",
            "bridge_sha256",
            "entry_path",
            "entry_sha256",
        }
        and closure_map["whole"] is whole
        and closure_map["fixed_inputs_with_bridge"] is fixed_inputs_with_bridge
        and closure_map["original_fixed_inputs"] is original_fixed_inputs
        and closure_map["bridge_path"] == bridge_path
        and closure_map["bridge_sha256"] == bridge_sha256
        and closure_map["entry_path"] == entry_path
        and closure_map["entry_sha256"] == entry_sha256,
        "fixed_inputs_wrapper_closure_invalid",
    )
    whole.__dict__["_CHILD_BOOTSTRAP_BODY"] = body
    whole.__dict__["_CHILD_BOOTSTRAP"] = whole._wrap_child_bootstrap(body)
    whole.__dict__["_fixed_inputs"] = fixed_inputs_with_bridge
    installation = BridgeInstallation(
        whole=whole,
        bridge_path=bridge_path,
        bridge_sha256=bridge_sha256,
        entry_sha256=entry_sha256,
        child_body=body,
        child_body_sha256=_sha(body.encode("utf-8")),
        fixed_inputs=fixed_inputs_with_bridge,
        original_fixed_inputs=original_fixed_inputs,
        fixed_inputs_closure=closure_values,
        _seal=_BRIDGE_INSTALL_SEAL,
    )
    whole.__dict__["__root_held_child_bridge_r2__"] = installation
    return installation


def invoke(whole: types.ModuleType, installation: BridgeInstallation, argv=None) -> int:
    """Run frozen R27 main only after the original root activation predicate passes."""
    _need(type(whole) is types.ModuleType, "r27_whole_module_type_invalid")
    _need(
        type(installation) is BridgeInstallation
        and installation._seal is _BRIDGE_INSTALL_SEAL
        and installation.whole is whole
        and whole.__dict__.get("__root_held_child_bridge_r2__") is installation
        and whole.__dict__.get("_fixed_inputs") is installation.fixed_inputs
        and installation.fixed_inputs.__code__ == next(
            value for value in install_child_bridge.__code__.co_consts
            if type(value) is types.CodeType and value.co_name == "fixed_inputs_with_bridge"
        )
        and tuple(
            (name, cell.cell_contents)
            for name, cell in zip(
                installation.fixed_inputs.__code__.co_freevars,
                installation.fixed_inputs.__closure__ or (),
            )
        )
        == installation.fixed_inputs_closure
        and dict(installation.fixed_inputs_closure)["whole"] is whole
        and dict(installation.fixed_inputs_closure)["fixed_inputs_with_bridge"] is installation.fixed_inputs
        and dict(installation.fixed_inputs_closure)["original_fixed_inputs"] is installation.original_fixed_inputs
        and whole.__dict__.get("_CHILD_BOOTSTRAP_BODY") == installation.child_body
        and whole.__dict__.get("_CHILD_BOOTSTRAP") == whole._wrap_child_bootstrap(installation.child_body)
        and _sha(installation.child_body.encode("utf-8")) == installation.child_body_sha256,
        "bridge_installation_identity_invalid",
    )
    _need(whole._activation_ready() is True, "r27_original_activation_closed")
    pins = whole._fixed_inputs()
    _need(
        pins.get(installation.bridge_path) == installation.bridge_sha256
        and pins.get(ROOT / ENTRY_REL) == installation.entry_sha256,
        "bridge_fixed_inputs_not_bound",
    )
    result = whole.main(argv)
    _need(type(result) is int and result in (0, 2), "r27_main_result_invalid")
    return result


__all__ = (
    "BRIDGE_REL",
    "BridgeInstallation",
    "ChildBridgeError",
    "ENTRY_REL",
    "ENTRY_SHA256",
    "WHOLE_REL",
    "WHOLE_SHA256",
    "install_child_bridge",
    "invoke",
    "load_supervisor",
)
