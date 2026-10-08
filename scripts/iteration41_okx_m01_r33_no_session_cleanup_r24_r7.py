"""Close only the pinned R23 source lease after a rejected no-session attempt.

This is a same-process recovery capsule for the exact R23 root driver.  It does
not retry authentication, launch a process, inspect private files, or turn an
unknown child result into a clean result.  The only release operation is the
driver's already-bound CUV2 source-scope callback.
"""

from __future__ import annotations

import dataclasses
import ast
import contextlib
import hashlib
import json
import ntpath
import os
from pathlib import Path
import threading
from types import CodeType, FunctionType, GeneratorType, MethodType, ModuleType
from typing import Any


_PATH_CLASS = Path
_CUV2_CONTEXTMANAGER = contextlib.contextmanager
_CUV2_EXIT_STACK = contextlib.ExitStack
_GENERATOR_CONTEXT_MANAGER = contextlib._GeneratorContextManager
_GENERATOR_CONTEXT_MANAGER_EXIT = _GENERATOR_CONTEXT_MANAGER.__exit__


R24R7_SCHEMA = "iteration41.okx.m01.r33.no-session-cleanup-receipt.r24.r7.v1"
R24R7_RELATIVE_PATH = "scripts/iteration41_okx_m01_r33_no_session_cleanup_r24_r7.py"
R23_DRIVER_RELATIVE_PATH = (
    "docs/_internal/opts/requirements/"
    "迭代41-实盘执行风控监控与示例架构重构/evidence/"
    "iteration41-m01-r33-r23-root-driver-draft-r1-2026-10-08/"
    "root-actual-driver.py"
)
R13_SOURCE_RELATIVE_PATH = "scripts/iteration41_okx_m01_r33_active_outer_activation_r13_r1.py"
R13_MODULE_NAME = "scripts.iteration41_okx_m01_r33_active_outer_activation_r13_r1"
CUV2_PUBLIC_SOURCE_RELATIVE_PATH = (
    "docs/_internal/opts/requirements/"
    "迭代41-实盘执行风控监控与示例架构重构/evidence/"
    "iteration41-cuv2-public-source-snapshot-r1-2026-10-08/cuv2-source.py"
)
CUV2_PUBLIC_SOURCE_SHA256 = "e856be8e4056835d4a7e54f5c6b449c69ab3f1c2ebb049bcbcc1c95a9ad3f246"

# These are public source files.  No config, account, capture, or private
# artifact path is included here.
RUNTIME_SOURCE_PINS = {
    R23_DRIVER_RELATIVE_PATH: "726c3a3c276271d4f8ba1333cb169da200076b20b1a44d8c55b8b80c53aabfe8",
    "scripts/iteration41_okx_m01_r33_root_reason_class_r23_r1.py": "b6cb9226638d4394ee443a439499dada034aeca6213b8886f09c3afd438e7bda",
    "scripts/iteration41_okx_m01_r32_external_parent_budget_r1.py": "5f9986146991188be4f0121e754c0a1e231e90700d167fe265464154cab8af1e",
    "scripts/iteration41_okx_m01_r33_active_outer_activation_r13_r1.py": "23c98a7d0012499050309f3dcdd8cd8f2710698867654776125e8a3d9a1fe580",
    "scripts/iteration41_okx_m01_r33_parent_adapter_transport_r14_r1.py": "fe2bd4fc008680fe5dc9099d0cb6782e4071070bf5ab259b53c3e763b6c413ef",
    "scripts/iteration41_okx_m01_r33_final_output_hold_r15_r1.py": "7cc20345462859b92ddfe843caded7935ece3a759f8eff5a8371c10c7d94e79f",
    "scripts/iteration41_okx_m01_r33_final_output_hold_r16_r1.py": "06e61947222e8639b700a8749c083d35e82202366b6c7105a354c8a7ff1b8e78",
    "scripts/iteration41_okx_m01_r33_source_map_gate_r17_r1.py": "cb05433078bddcd779914c6eb0e9b99d942b3e1a55d5fb39e756928f3249fc5f",
    "scripts/iteration41_okx_m01_r33_parent_adapter_constructor_r18_r1.py": "f9dd76909adeff5b0f6e76a9664c427b213e10a2915109e1f7dda32b1ea47902",
    "scripts/iteration41_okx_m01_r33_child_source_scope_r19_r1.py": "424edf3aecc997f36bbe9ba713c3278b594132016ab893164ecf822d734aa1d4",
    "scripts/iteration41_okx_m01_r33_child_entry_path_r20_r1.py": "18b47fd4681a59418f54cead5133e7a853b1db64acdfc144aafba23640c6180a",
    "scripts/iteration41_okx_m01_r33_child_main_map_r21_r1.py": "02bc37a707093ed1afd9c7befcb167cccf1820a242e821357bba83f3b18aa770",
    "scripts/iteration41_okx_m01_r33_root_prepare_r22_r1.py": "81f72804244407b1ef010ee9361b030980923c758624a4e1ced35fcd7162bf9b",
    "scripts/iteration41_okx_m01_r33_windows_parent_adapter_r2.py": "544cbfe4afba327f69c528d9b31da8982405f57acd1ecd3e4d5b1e87838d8e83",
    "scripts/iteration41_okx_m01_r33_windows_parent_adapter_r4.py": "2a1ea13020b54d54fe41ace3fca2a1f05c4f0cdb89d71b8c06c66de1a8bd140c",
    "scripts/iteration41_okx_m01_r33_windows_parent_adapter_r5.py": "5d11a2aae8af7d9e98e956dfc4258453709ea9a86d481591a15676b0aa7d5f3c",
    "scripts/iteration41_okx_m01_r33_windows_parent_adapter_r6.py": "cc12ad98a17275c5781be50314a1de6c9084603ffb7f0207d07218280a22b7aa",
    "scripts/iteration41_okx_m01_r33_outer_route_phase_observer_r8_r1.py": "cfc7044f9863e76dc16499dd1c9b5047fc00309ddb437929ae990e148b27b38c",
    "backtrader_runtime/certification_roundtrip_private.py": "b866194bdc56d91cc7a6678e83b0af8e4e018ee53a2c136325344c2ee8a5ecfd",
}

_FAILURE_CODES = frozenset(
    {
        "capsule_source_pin",
        "capsule_owner_mismatch",
        "capsule_same_call_required",
        "capsule_result_not_no_session",
        "capsule_adapter_chain",
        "capsule_control_shape",
        "capsule_source_maps",
        "capsule_source_validators",
        "capsule_registry_binding",
        "capsule_scope_release_failed",
        "capsule_registry_close_failed",
        "capsule_reference_drop_failed",
        "capsule_scope_binding",
        "capsule_receipt_reused",
    }
)
_VERIFIER_PHASES = frozenset({10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120, 130})
_ACTIVE_VERIFIER_PHASE = threading.local()


@contextlib.contextmanager
def _verifier_phase(ordinal: int):
    _require(type(ordinal) is int and ordinal in _VERIFIER_PHASES, "capsule_same_call_required")
    previous = getattr(_ACTIVE_VERIFIER_PHASE, "ordinal", None)
    _ACTIVE_VERIFIER_PHASE.ordinal = ordinal
    try:
        yield
    finally:
        if previous is None:
            try:
                del _ACTIVE_VERIFIER_PHASE.ordinal
            except AttributeError:
                pass
        else:
            _ACTIVE_VERIFIER_PHASE.ordinal = previous


class NoSessionCleanupBlocked(ValueError):
    """A fixed-code failure to prove the exact no-session cleanup contract."""

    def __init__(self, code: str, phase_ordinal: Any = None) -> None:
        self.code = code if code in _FAILURE_CODES else "capsule_same_call_required"
        self.phase_ordinal = (
            phase_ordinal if type(phase_ordinal) is int and phase_ordinal in _VERIFIER_PHASES else None
        )
        super().__init__(self.code)


class NoSessionCleanupReceipt:
    """One-use finite proof that both held source scopes were normally closed."""

    __slots__ = ("_payload_bytes", "_owner_pid", "_owner_thread", "_lock", "_used")

    def __init__(self, payload: dict[str, Any], owner_pid: int, owner_thread: int) -> None:
        object.__setattr__(
            self,
            "_payload_bytes",
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"),
        )
        object.__setattr__(self, "_owner_pid", owner_pid)
        object.__setattr__(self, "_owner_thread", owner_thread)
        object.__setattr__(self, "_lock", threading.Lock())
        object.__setattr__(self, "_used", False)

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("receipt fields are immutable")

    def consume(self) -> dict[str, Any]:
        if os.getpid() != self._owner_pid or threading.get_ident() != self._owner_thread:
            raise NoSessionCleanupBlocked("capsule_owner_mismatch")
        with self._lock:
            if self._used:
                raise NoSessionCleanupBlocked("capsule_receipt_reused")
            object.__setattr__(self, "_used", True)
            return json.loads(self._payload_bytes)


def _fail(code: str) -> None:
    raise NoSessionCleanupBlocked(code, getattr(_ACTIVE_VERIFIER_PHASE, "ordinal", None))


def _require(condition: Any, code: str) -> None:
    if not condition:
        _fail(code)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _key(value: Any) -> str:
    _require(type(value) is str and value, "capsule_source_maps")
    return ntpath.normcase(ntpath.normpath(value))


def _repo_root() -> Path:
    path = Path(__file__).resolve()
    root = path.parent.parent
    _require(path == (root / R24R7_RELATIVE_PATH).resolve(), "capsule_source_pin")
    return root


def _read_fixed_public_source(root: Path, relative_path: str, expected_sha256: str) -> bytes:
    path = (root / Path(*relative_path.split("/"))).resolve()
    try:
        path.relative_to(root)
        before = path.stat()
        _require(0 < before.st_size <= 1024 * 1024, "capsule_source_pin")
        with path.open("rb") as stream:
            raw = stream.read(before.st_size + 1)
        after = path.stat()
    except NoSessionCleanupBlocked:
        raise
    except BaseException:
        _fail("capsule_source_pin")
    _require(
        len(raw) == before.st_size
        and (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        and _sha(raw) == expected_sha256,
        "capsule_source_pin",
    )
    return raw


def _verify_loaded_module(
    module: Any, root: Path, relative_path: str, expected_sha256: str
) -> None:
    _require(module is not None, "capsule_source_pin")
    value = getattr(module, "__file__", None)
    _require(type(value) is str, "capsule_source_pin")
    try:
        actual = Path(value).resolve()
        expected = (root / Path(*relative_path.split("/"))).resolve()
    except BaseException:
        _fail("capsule_source_pin")
    _require(actual == expected, "capsule_source_pin")


def _verify_loaded_modules(namespace: dict[str, Any], root: Path) -> None:
    module_bindings = {
        "a": "scripts/iteration41_okx_m01_r33_active_outer_activation_r13_r1.py",
        "r14": "scripts/iteration41_okx_m01_r33_parent_adapter_transport_r14_r1.py",
        "r15": "scripts/iteration41_okx_m01_r33_final_output_hold_r15_r1.py",
        "r16": "scripts/iteration41_okx_m01_r33_final_output_hold_r16_r1.py",
        "r17": "scripts/iteration41_okx_m01_r33_source_map_gate_r17_r1.py",
        "r18": "scripts/iteration41_okx_m01_r33_parent_adapter_constructor_r18_r1.py",
        "r19": "scripts/iteration41_okx_m01_r33_child_source_scope_r19_r1.py",
        "r20": "scripts/iteration41_okx_m01_r33_child_entry_path_r20_r1.py",
        "r21": "scripts/iteration41_okx_m01_r33_child_main_map_r21_r1.py",
        "r22": "scripts/iteration41_okx_m01_r33_root_prepare_r22_r1.py",
        "r23": "scripts/iteration41_okx_m01_r33_root_reason_class_r23_r1.py",
    }
    for name, relative_path in module_bindings.items():
        _verify_loaded_module(namespace.get(name), root, relative_path, RUNTIME_SOURCE_PINS[relative_path])


def _verify_runtime_sources(
    namespace: dict[str, Any], capsule_sha256: str
) -> tuple[Path, dict[str, str], bytes]:
    root = _repo_root()
    _require(
        type(capsule_sha256) is str
        and len(capsule_sha256) == 64
        and all(character in "0123456789abcdef" for character in capsule_sha256),
        "capsule_source_pin",
    )
    _read_fixed_public_source(root, R24R7_RELATIVE_PATH, capsule_sha256)
    driver_path = namespace.get("__file__")
    _require(type(driver_path) is str, "capsule_source_pin")
    try:
        actual_driver = Path(driver_path).resolve()
        expected_driver = (root / Path(*R23_DRIVER_RELATIVE_PATH.split("/"))).resolve()
    except BaseException:
        _fail("capsule_source_pin")
    _require(actual_driver == expected_driver, "capsule_source_pin")
    verified = {}
    driver_source = None
    for relative_path, expected_sha256 in RUNTIME_SOURCE_PINS.items():
        raw = _read_fixed_public_source(root, relative_path, expected_sha256)
        if relative_path == R23_DRIVER_RELATIVE_PATH:
            driver_source = raw
        verified[relative_path] = expected_sha256
    _require(type(driver_source) is bytes, "capsule_source_pin")
    cuv2_source = _read_fixed_public_source(
        root, CUV2_PUBLIC_SOURCE_RELATIVE_PATH, CUV2_PUBLIC_SOURCE_SHA256
    )
    _require(
        _driver_cuv2_binding(driver_source)[1] == CUV2_PUBLIC_SOURCE_SHA256,
        "capsule_scope_binding",
    )
    verified[CUV2_PUBLIC_SOURCE_RELATIVE_PATH] = _sha(cuv2_source)
    verified[R24R7_RELATIVE_PATH] = capsule_sha256
    return root, verified, driver_source


def _constant_signature(value: Any) -> Any:
    if isinstance(value, CodeType):
        return ("code", _code_signature(value))
    if type(value) is tuple:
        return ("tuple", tuple(_constant_signature(item) for item in value))
    if type(value) is frozenset:
        items = [_constant_signature(item) for item in value]
        return ("frozenset", tuple(sorted(items, key=repr)))
    return (type(value), value)


def _code_signature(code: CodeType) -> tuple[Any, ...]:
    return (
        code.co_argcount,
        getattr(code, "co_posonlyargcount", 0),
        code.co_kwonlyargcount,
        code.co_nlocals,
        code.co_stacksize,
        code.co_flags,
        code.co_code,
        tuple(_constant_signature(value) for value in code.co_consts),
        code.co_names,
        code.co_varnames,
        code.co_filename,
        code.co_name,
        getattr(code, "co_qualname", code.co_name),
        code.co_firstlineno,
        getattr(code, "co_linetable", code.co_lnotab),
        getattr(code, "co_exceptiontable", b""),
        code.co_freevars,
        code.co_cellvars,
    )


def _nested_code_objects(code: CodeType):
    for value in code.co_consts:
        if isinstance(value, CodeType):
            yield value
            yield from _nested_code_objects(value)


def _verify_function_source(function: Any, raw: bytes, path: Path) -> None:
    _require(type(function) is FunctionType, "capsule_source_pin")
    try:
        module_code = compile(raw, str(path.resolve()), "exec", dont_inherit=True)
        actual_code = function.__code__
        matches = [
            code
            for code in _nested_code_objects(module_code)
            if code.co_name == actual_code.co_name
            and code.co_firstlineno == actual_code.co_firstlineno
        ]
    except BaseException:
        _fail("capsule_source_pin")
    _require(
        len(matches) == 1 and _code_signature(matches[0]) == _code_signature(actual_code),
        "capsule_source_pin",
    )


def _verify_class_source(cls: Any, globals_dict: Any, raw: bytes, path: Path) -> None:
    _require(type(cls) is type and type(globals_dict) is dict, "capsule_source_pin")
    try:
        module_code = compile(raw, str(path.resolve()), "exec", dont_inherit=True)
        class_codes = [
            code for code in _nested_code_objects(module_code) if code.co_name == cls.__name__
        ]
        _require(len(class_codes) == 1, "capsule_source_pin")
        expected_methods = {
            code.co_name: code
            for code in class_codes[0].co_consts
            if isinstance(code, CodeType)
        }
        actual_methods = {}
        for name, value in cls.__dict__.items():
            if type(value) is FunctionType:
                actual_methods[name] = value
            elif type(value) is property:
                if value.fget is not None:
                    actual_methods[name] = value.fget
                if value.fset is not None:
                    actual_methods[name + ".setter"] = value.fset
                if value.fdel is not None:
                    actual_methods[name + ".deleter"] = value.fdel
            elif type(value) in (staticmethod, classmethod):
                actual_methods[name] = value.__func__
    except NoSessionCleanupBlocked:
        raise
    except BaseException:
        _fail("capsule_source_pin")
    _require(
        set(actual_methods) == set(expected_methods), "capsule_source_pin"
    )
    for name, function in actual_methods.items():
        expected = expected_methods[name]
        _require(
            type(function) is FunctionType
            and function.__globals__ is globals_dict
            and _code_signature(function.__code__) == _code_signature(expected),
            "capsule_source_pin",
        )


def _verified_module_source(root: Path, module_globals: Any, relative_path: str) -> bytes:
    _require(type(module_globals) is dict, "capsule_source_pin")
    path_value = module_globals.get("__file__")
    module_name = module_globals.get("__name__")
    _require(type(path_value) is str and type(module_name) is str, "capsule_source_pin")
    path = (root / Path(*relative_path.split("/"))).resolve()
    try:
        actual = Path(path_value).resolve()
    except BaseException:
        _fail("capsule_source_pin")
    _require(actual == path, "capsule_source_pin")
    raw = _read_fixed_public_source(
        root, relative_path, RUNTIME_SOURCE_PINS[relative_path]
    )
    return raw


def _verify_root_driver_callbacks(
    namespace: dict[str, Any], root: Path, driver_source: bytes
) -> None:
    try:
        driver_path = str((root / Path(*R23_DRIVER_RELATIVE_PATH.split("/"))).resolve())
        module_code = compile(driver_source, driver_path, "exec", dont_inherit=True)
        code_objects = tuple(_nested_code_objects(module_code))
        for name, first_line in (("authenticate", 434), ("release", 477)):
            expected = [
                code
                for code in code_objects
                if code.co_name == name and code.co_firstlineno == first_line
            ]
            function = namespace.get(name)
            _require(
                len(expected) == 1
                and type(function) is FunctionType
                and function.__globals__ is namespace
                and function.__name__ == name
                and function.__code__.co_filename == driver_path
                and function.__code__.co_firstlineno == first_line
                and _code_signature(function.__code__) == _code_signature(expected[0]),
                "capsule_same_call_required",
            )
        expected_load = [code for code in code_objects if code.co_name == "load"]
        load_function = namespace.get("load")
        _require(
            len(expected_load) == 1
            and type(load_function) is FunctionType
            and load_function.__globals__ is namespace
            and load_function.__name__ == "load"
            and load_function.__code__.co_filename == driver_path
            and load_function.__code__.co_firstlineno == expected_load[0].co_firstlineno
            and _code_signature(load_function.__code__) == _code_signature(expected_load[0]),
            "capsule_same_call_required",
        )
    except NoSessionCleanupBlocked:
        raise
    except BaseException:
        _fail("capsule_source_pin")


def _driver_cuv2_binding(driver_source: bytes) -> tuple[str, str, str]:
    try:
        tree = ast.parse(driver_source.decode("utf-8"), filename=R23_DRIVER_RELATIVE_PATH)
        assignments = {}
        for node in tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target = node.targets[0]
                if isinstance(target, ast.Name):
                    assignments[target.id] = node.value
        path_node = assignments.get("CU")
        pin_node = assignments.get("CU_SHA")
        _require(
            isinstance(path_node, ast.Call)
            and isinstance(path_node.func, ast.Name)
            and path_node.func.id == "Path"
            and len(path_node.args) == 1
            and type(ast.literal_eval(path_node.args[0])) is str,
            "capsule_scope_binding",
        )
        cu_path = ast.literal_eval(path_node.args[0])
        cu_sha256 = ast.literal_eval(pin_node)
        module_name = None
        for node in tree.body:
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            target = node.targets[0]
            value = node.value
            if (
                isinstance(target, ast.Name)
                and target.id == "cu"
                and isinstance(value, ast.Call)
                and isinstance(value.func, ast.Name)
                and value.func.id == "load"
                and len(value.args) == 3
            ):
                module_name = ast.literal_eval(value.args[2])
                break
        _require(
            ntpath.isabs(cu_path)
            and type(cu_sha256) is str
            and len(cu_sha256) == 64
            and all(character in "0123456789abcdef" for character in cu_sha256)
            and type(module_name) is str
            and module_name,
            "capsule_scope_binding",
        )
        return cu_path, cu_sha256, module_name
    except NoSessionCleanupBlocked:
        raise
    except BaseException:
        _fail("capsule_scope_binding")


def _validate_cuv2_scope_binding(
    namespace: dict[str, Any], root: Path, driver_source: bytes
) -> tuple[Any, ...]:
    cu_path, cu_sha256, module_name = _driver_cuv2_binding(driver_source)
    cu_path_value = namespace.get("CU")
    cu_module = namespace.get("cu")
    sys_module = namespace.get("sys")
    extra_held = namespace.get("extra_held")
    extra_scope = namespace.get("extra_scope")
    main_scope = namespace.get("main_scope")
    _require(
        isinstance(cu_path_value, Path)
        and _key(str(cu_path_value)) == _key(cu_path)
        and type(cu_module) is ModuleType
        and cu_module.__name__ == module_name
        and type(getattr(cu_module, "__file__", None)) is str
        and _key(cu_module.__file__) == _key(cu_path)
        and type(sys_module) is ModuleType
        and sys_module.modules.get(module_name) is cu_module
        and type(extra_held) is dict,
        "capsule_scope_binding",
    )
    expected_key = _key(cu_path)
    try:
        matches = [(path, raw) for path, raw in extra_held.items() if _key(path) == expected_key]
    except BaseException:
        _fail("capsule_scope_binding")
    _require(
        len(matches) == 1
        and type(matches[0][1]) is bytes
        and _sha(matches[0][1]) == cu_sha256 == CUV2_PUBLIC_SOURCE_SHA256
        and matches[0][1]
        == _read_fixed_public_source(
            root, CUV2_PUBLIC_SOURCE_RELATIVE_PATH, CUV2_PUBLIC_SOURCE_SHA256
        ),
        "capsule_scope_binding",
    )
    cu_source = matches[0][1]
    try:
        # The pinned R23 loader compiles with `str(path)`. On Windows this
        # normalizes the AST's slash spelling to the active Path string; use
        # that same filename so the code signature matches the loaded module.
        cu_filename = str(cu_path_value)
        module_code = compile(cu_source, cu_filename, "exec", dont_inherit=True)
        expected_generators = [
            code for code in _nested_code_objects(module_code) if code.co_name == "held_public_sources"
        ]
        held_public_sources = getattr(cu_module, "held_public_sources", None)
        generator_function = getattr(held_public_sources, "__wrapped__", None)
        manager_type = contextlib._GeneratorContextManager
        exit_method = manager_type.__exit__
        _require(
            len(expected_generators) == 1
            and manager_type is _GENERATOR_CONTEXT_MANAGER
            and exit_method is _GENERATOR_CONTEXT_MANAGER_EXIT
            and type(held_public_sources) is FunctionType
            and type(generator_function) is FunctionType
            and generator_function.__name__ == "held_public_sources"
            and generator_function.__module__ == module_name
            and generator_function.__globals__ is cu_module.__dict__
            and generator_function.__code__.co_filename == cu_filename
            and cu_module.__dict__.get("Path") is _PATH_CLASS
            and cu_module.__dict__.get("contextmanager") is _CUV2_CONTEXTMANAGER
            and cu_module.__dict__.get("ExitStack") is _CUV2_EXIT_STACK
            and _code_signature(generator_function.__code__)
            == _code_signature(expected_generators[0])
            and isinstance(manager_type, type)
            and manager_type.__module__ == "contextlib"
            and manager_type.__name__ == "_GeneratorContextManager"
            and type(exit_method) is FunctionType
            and exit_method.__module__ == "contextlib"
            and exit_method.__qualname__ == "_GeneratorContextManager.__exit__"
            and exit_method.__code__.co_filename == contextlib.__file__,
            "capsule_scope_binding",
        )
        scope_facts = []
        expected_inputs = (
            (extra_scope, namespace.get("extra"), None, extra_held),
            (main_scope, namespace.get("pub_parent"), namespace.get("soft"), namespace.get("held")),
        )
        for scope, expected_public, expected_software, expected_held in expected_inputs:
            scope_attributes = vars(scope)
            generator = getattr(scope, "gen", None)
            frame = getattr(generator, "gi_frame", None)
            frame_locals = frame.f_locals if frame is not None else None
            _require(
                type(scope) is manager_type
                and type(scope_attributes) is dict
                and "__exit__" not in scope_attributes
                and type(generator) is GeneratorType
                and generator.gi_code is generator_function.__code__
                and _code_signature(generator.gi_code) == _code_signature(expected_generators[0])
                and frame is not None
                and frame.f_code is generator.gi_code
                and frame.f_globals is cu_module.__dict__
                and frame_locals.get("pins") is expected_public
                and frame_locals.get("raw_bytes") is expected_held
                and generator.gi_running is False,
                "capsule_scope_binding",
            )
            if expected_software is None:
                _require(
                    type(frame_locals.get("software_pins")) is dict
                    and not frame_locals["software_pins"],
                    "capsule_scope_binding",
                )
            else:
                _require(
                    type(expected_software) is dict
                    and frame_locals.get("software_pins") is expected_software,
                    "capsule_scope_binding",
                )
            scope_facts.append((scope, generator))
    except NoSessionCleanupBlocked:
        raise
    except BaseException:
        _fail("capsule_scope_binding")
    return (
        cu_path,
        cu_sha256,
        module_name,
        cu_module,
        held_public_sources,
        generator_function,
        expected_generators[0],
        manager_type,
        exit_method,
        _code_signature(exit_method.__code__),
        tuple(scope_facts),
    )


def _capture_release_callback(namespace: dict[str, Any]) -> tuple[Any, ...]:
    release = namespace.get("release")
    _require(
        type(release) is FunctionType
        and type(getattr(release, "__code__", None)) is CodeType
        and release.__globals__ is namespace
        and release.__defaults__ is None
        and release.__kwdefaults__ is None,
        "capsule_same_call_required",
    )
    return release, release.__code__, release.__globals__, _code_signature(release.__code__)


def _recheck_release_callback(
    namespace: dict[str, Any], root: Path, driver_source: bytes, captured: tuple[Any, ...]
) -> Any:
    release, code, globals_dict, signature = captured
    _verify_root_driver_callbacks(namespace, root, driver_source)
    _require(
        namespace.get("release") is release
        and type(release) is FunctionType
        and release.__code__ is code
        and release.__globals__ is globals_dict is namespace
        and release.__defaults__ is None
        and release.__kwdefaults__ is None
        and _code_signature(release.__code__) == signature,
        "capsule_same_call_required",
    )
    return release


def _same_cuv2_scope_binding(first: tuple[Any, ...], current: tuple[Any, ...]) -> bool:
    if len(first) != len(current) or len(first) != 11:
        return False
    if first[:3] != current[:3]:
        return False
    if any(first[index] is not current[index] for index in (3, 4, 5, 7, 8)):
        return False
    if (
        _code_signature(first[6]) != _code_signature(current[6])
        or first[9] != current[9]
        or len(first[10]) != len(current[10])
    ):
        return False
    return all(
        first_fact[0] is current_fact[0] and first_fact[1] is current_fact[1]
        for first_fact, current_fact in zip(first[10], current[10])
    )


def _verify_live_r13_source_binding(namespace: dict[str, Any], root: Path) -> None:
    """Bind R13's disk-pinned source bytes to the exact held and loaded module."""
    expected_sha256 = RUNTIME_SOURCE_PINS[R13_SOURCE_RELATIVE_PATH]
    expected_path = (root / Path(*R13_SOURCE_RELATIVE_PATH.split("/"))).resolve()
    expected_key = _key(str(expected_path))
    extra_held = namespace.get("extra_held")
    _require(type(extra_held) is dict, "capsule_source_pin")
    try:
        matches = [raw for path, raw in extra_held.items() if _key(path) == expected_key]
    except BaseException:
        _fail("capsule_source_pin")
    _require(
        len(matches) == 1 and type(matches[0]) is bytes and _sha(matches[0]) == expected_sha256,
        "capsule_source_pin",
    )
    module = namespace.get("a")
    sys_module = namespace.get("sys")
    _require(
        type(module) is ModuleType
        and type(sys_module) is ModuleType
        and module.__name__ == R13_MODULE_NAME
        and type(getattr(module, "__file__", None)) is str
        and Path(module.__file__).resolve() == expected_path
        and sys_module.modules.get(R13_MODULE_NAME) is module,
        "capsule_source_pin",
    )
    spec = getattr(module, "__spec__", None)
    _require(
        spec is not None
        and getattr(spec, "name", None) == R13_MODULE_NAME
        and getattr(spec, "origin", None) == str(expected_path),
        "capsule_source_pin",
    )


def _hash_map(value: Any) -> dict[str, str]:
    _require(type(value) is dict, "capsule_source_maps")
    result: dict[str, str] = {}
    for path, raw in value.items():
        normalized = _key(path)
        _require(type(raw) is bytes and normalized not in result, "capsule_source_maps")
        result[normalized] = _sha(raw)
    return result


def _originless_producer_rows(namespace: dict[str, Any]) -> dict[str, tuple[str, dict[str, Any], bytes]]:
    """Bind only the two legacy rows the pinned R9/R10 producers emit without origin."""
    r23_result = namespace.get("r23_adapter_result")
    try:
        prepared_r13 = r23_result.prepared_hold.prepared_r13
        r10_prepared = prepared_r13.r10_prepared
        r9_prepared = r10_prepared.r9_prepared
        sidecar_path = r9_prepared.sidecar_path
        sidecar_raw = r9_prepared.r8_bootstrap_bytes
        sidecar_sha256 = r9_prepared.sidecar_sha256
        sidecar_size_bytes = r9_prepared.sidecar_size_bytes
        composer_path = r10_prepared.composer_path
        composer_raw = r10_prepared.composer_bytes
        composer_sha256 = r10_prepared.composer_sha256
        composer_size_bytes = len(composer_raw)
    except BaseException:
        _fail("capsule_source_maps")

    _require(
        type(sidecar_path) is str
        and type(sidecar_raw) is bytes
        and type(sidecar_sha256) is str
        and type(sidecar_size_bytes) is int
        and sidecar_size_bytes == len(sidecar_raw)
        and _sha(sidecar_raw) == sidecar_sha256
        and type(composer_path) is str
        and type(composer_raw) is bytes
        and type(composer_sha256) is str
        and composer_size_bytes > 0
        and _sha(composer_raw) == composer_sha256,
        "capsule_source_maps",
    )
    rows = {
        _key(sidecar_path): (
            sidecar_path,
            {
                "sha256": sidecar_sha256,
                "size_bytes": sidecar_size_bytes,
                "role": "r9_r8_bootstrap_sidecar",
            },
            sidecar_raw,
        ),
        _key(composer_path): (
            composer_path,
            {
                "sha256": composer_sha256,
                "size_bytes": composer_size_bytes,
                "role": "r10_public_source_composer",
            },
            composer_raw,
        ),
    }
    _require(len(rows) == 2 and _key(sidecar_path) != _key(composer_path), "capsule_source_maps")
    return rows


def _validate_maps(namespace: dict[str, Any]) -> None:
    pub = namespace.get("pub")
    software = namespace.get("soft")
    canonical = namespace.get("expected")
    parent_public = namespace.get("pub_parent")
    expected_parent = namespace.get("expected_parent")
    extra = namespace.get("extra")
    held = namespace.get("held")
    extra_held = namespace.get("extra_held")
    hold_addition = namespace.get("hold_addition")
    hold_snapshot = namespace.get("hold_addition_snapshot")
    r23_result = namespace.get("r23_adapter_result")

    _require(
        all(type(value) is dict for value in (pub, software, canonical, parent_public, expected_parent, extra, held, extra_held))
        and type(hold_addition) is dict
        and type(hold_snapshot) is bytes,
        "capsule_source_maps",
    )
    pub_norm = {_key(path): digest for path, digest in pub.items()}
    software_norm = {_key(path): digest for path, digest in software.items()}
    canonical_norm = {_key(path): digest for path, digest in canonical.items()}
    parent_norm = {_key(path): digest for path, digest in parent_public.items()}
    expected_parent_norm = {_key(path): digest for path, digest in expected_parent.items()}
    extra_norm = {_key(path): digest for path, digest in extra.items()}
    for mapping in (pub, software, canonical, parent_public, expected_parent, extra):
        for path, digest in mapping.items():
            _key(path)
            _require(
                type(digest) is str
                and len(digest) == 64
                and all(character in "0123456789abcdef" for character in digest),
                "capsule_source_maps",
            )
    _require(
        len(pub) == 118
        and len(software) == 36
        and len(canonical) == 154
        and len(pub_norm) == len(pub)
        and len(software_norm) == len(software)
        and len(canonical_norm) == len(canonical)
        and len(parent_norm) == len(parent_public)
        and len(expected_parent_norm) == len(expected_parent)
        and len(extra_norm) == len(extra)
        and {**pub_norm, **software_norm} == canonical_norm
        and not (set(pub_norm) & set(software_norm))
        and len(parent_public) + len(software) == len(expected_parent)
        and len(parent_public) == 154
        and len(expected_parent) == 190
        and len(extra) == 299
        and not (set(parent_norm) & set(software_norm))
        and {**parent_norm, **software_norm} == expected_parent_norm,
        "capsule_source_maps",
    )
    expected_main = {_key(path): digest for path, digest in {**parent_public, **software}.items()}
    _require(
        len(expected_main) == len(parent_public) + len(software)
        and _hash_map(held) == expected_main
        and _hash_map(extra_held) == {_key(path): digest for path, digest in extra.items()},
        "capsule_source_maps",
    )
    _require(
        type(hold_addition.get("canonical_child_map_count")) is int
        and hold_addition["canonical_child_map_count"] == 154
        and type(hold_addition.get("entries")) is dict
        and type(getattr(r23_result, "hold_addition_sha256", None)) is str
        and getattr(r23_result, "hold_addition", None) is hold_addition,
        "capsule_source_maps",
    )
    r15 = namespace.get("r15")
    try:
        canonical_addition = r15._canonical_json(hold_addition)
    except BaseException:
        _fail("capsule_source_maps")
    _require(
        canonical_addition == hold_snapshot
        and _sha(hold_snapshot) == r23_result.hold_addition_sha256,
        "capsule_source_maps",
    )
    held_by_key = {_key(path): raw for path, raw in held.items()}
    _require(len(held_by_key) == len(held), "capsule_source_maps")
    originless_rows = _originless_producer_rows(namespace)
    seen_originless = set()
    for path, row in hold_addition["entries"].items():
        normalized = _key(path)
        expected_originless = originless_rows.get(normalized)
        if expected_originless is not None:
            expected_path, expected_row, expected_raw = expected_originless
            _require(path == expected_path and row == expected_row, "capsule_source_maps")
            seen_originless.add(normalized)
        else:
            _require(
                type(row) is dict
                and set(row) == {"sha256", "size_bytes", "role", "origin"}
                and type(row.get("sha256")) is str
                and type(row.get("size_bytes")) is int
                and row["size_bytes"] > 0
                and type(row.get("role")) is str
                and type(row.get("origin")) is str
                and bool(row["origin"]),
                "capsule_source_maps",
            )
            expected_raw = None
        _require(
            type(row) is dict
            and type(row.get("sha256")) is str
            and type(row.get("size_bytes")) is int
            and row["size_bytes"] > 0
            and type(row.get("role")) is str,
            "capsule_source_maps",
        )
        raw = held_by_key.get(_key(path))
        _require(
            type(raw) is bytes
            and len(raw) == row["size_bytes"]
            and _sha(raw) == row["sha256"]
            and (expected_raw is None or raw == expected_raw),
            "capsule_source_maps",
        )
    _require(seen_originless == set(originless_rows), "capsule_source_maps")

    r16_result = namespace.get("r16_result")
    try:
        r16_path = r16_result.r16_helper_path
        r16_raw = r16_result.r16_helper_bytes
        r16_sha = r16_result.r16_helper_sha256
        r16_key = _key(r16_path)
        extra_value = extra_held.get(r16_key)
        main_value = held_by_key.get(r16_key)
        public_pin = parent_public.get(r16_key)
    except BaseException:
        _fail("capsule_source_maps")
    _require(
        type(r16_raw) is bytes
        and type(r16_sha) is str
        and _sha(r16_raw) == r16_sha
        and extra_value == r16_raw
        and main_value == r16_raw
        and public_pin == r16_sha,
        "capsule_source_maps",
    )
    # Reconstruct the exact maps built by the pinned R23 root driver:
    # pub_parent starts as `pub`, receives each hold-addition row, then the
    # separately pinned R16 helper; expected_parent starts as `canonical`
    # and receives the same rows. Keep both maps tied to the actual held bytes.
    expected_full = dict(canonical_norm)
    expected_public_from_driver = dict(pub_norm)
    addition_entries = hold_addition["entries"]
    addition_norm = set()
    for path, row in addition_entries.items():
        normalized = _key(path)
        _require(normalized not in addition_norm, "capsule_source_maps")
        addition_norm.add(normalized)
        digest = row["sha256"]
        _require(normalized not in software_norm, "capsule_source_maps")
        _require(
            normalized not in expected_public_from_driver
            or expected_public_from_driver[normalized] == digest,
            "capsule_source_maps",
        )
        _require(
            normalized not in expected_full or expected_full[normalized] == digest,
            "capsule_source_maps",
        )
        expected_public_from_driver[normalized] = digest
        expected_full[normalized] = digest
    _require(r16_key not in software_norm, "capsule_source_maps")
    _require(
        r16_key not in expected_public_from_driver
        or expected_public_from_driver[r16_key] == r16_sha,
        "capsule_source_maps",
    )
    _require(r16_key not in expected_full or expected_full[r16_key] == r16_sha, "capsule_source_maps")
    expected_public_from_driver[r16_key] = r16_sha
    expected_full[r16_key] = r16_sha
    expected_public = {path: digest for path, digest in expected_full.items() if path not in software_norm}
    _require(
        len(expected_public_from_driver) == 154
        and len(expected_public) == 154
        and len(expected_full) == 190
        and expected_public_from_driver == expected_public
        and parent_norm == expected_public
        and expected_parent_norm == expected_full,
        "capsule_source_maps",
    )


def _validate_adapter_chain(
    namespace: dict[str, Any], owner_thread: int
) -> tuple[Any, Any, Any, Any, Any]:
    r14 = namespace.get("r14")
    r19 = namespace.get("r19")
    r20 = namespace.get("r20")
    r21 = namespace.get("r21")
    r22 = namespace.get("r22")
    r23 = namespace.get("r23")
    r17 = namespace.get("r17")
    r23_result = namespace.get("r23_adapter_result")
    r22_result = namespace.get("r22_adapter_result")
    r21_result = namespace.get("r21_adapter_result")
    r20_result = namespace.get("r20_adapter_result")
    r19_result = namespace.get("r19_adapter_result")
    adapter = namespace.get("adapter")
    try:
        _require(type(r23_result) is r23.R23ParentAdapterResult, "capsule_adapter_chain")
        _require(type(r22_result) is r22.R22ParentAdapterResult, "capsule_adapter_chain")
        _require(type(r21_result) is r21.R21ParentAdapterResult, "capsule_adapter_chain")
        _require(type(r20_result) is r20.R20ParentAdapterResult, "capsule_adapter_chain")
        _require(type(r19_result) is r19.R19ParentAdapterResult, "capsule_adapter_chain")
        _require(r23_result.r22_adapter_result is r22_result, "capsule_adapter_chain")
        _require(r22_result.r21_adapter_result is r21_result, "capsule_adapter_chain")
        _require(r21_result.r20_adapter_result is r20_result, "capsule_adapter_chain")
        _require(r20_result.r19_adapter_result is r19_result, "capsule_adapter_chain")
        _require(r23_result.adapter is adapter, "capsule_adapter_chain")
        _require(type(adapter) is r23.R23ParentAdapter, "capsule_adapter_chain")
        _require(adapter._base_adapter is r22_result.adapter, "capsule_adapter_chain")
        _require(r22_result.adapter is r21_result.adapter is r20_result.adapter is r19_result.adapter, "capsule_adapter_chain")
        r14_adapter = r19_result.adapter
        _require(type(r14_adapter) is r14.M01WindowsParentAdapter, "capsule_adapter_chain")

        r8_adapter = r14_adapter._r8_adapter
        r5_adapter = r8_adapter._r5
        r4_adapter = r5_adapter._base
        r2_adapter = r4_adapter._inner
        r2_module = r4_adapter._r2_module
        r32 = r2_adapter._r32
        _require(r5_adapter._inner is r2_adapter, "capsule_adapter_chain")
        _require(r5_adapter._r2_module is r2_module, "capsule_adapter_chain")
        _require(type(r2_adapter) is r2_module.M01WindowsParentAdapter, "capsule_adapter_chain")
        _require(r32 is r2_adapter._r32, "capsule_adapter_chain")
        _require(r2_adapter.fake_leaves is False, "capsule_adapter_chain")
        _require(r2_adapter.native is None and r2_adapter.process_factory is None, "capsule_adapter_chain")
        _require(
            r2_adapter._scope_authenticated is False
            and type(r2_adapter._retained_late) is list
            and len(r2_adapter._retained_late) == 0,
            "capsule_adapter_chain",
        )
        _require(
            type(r2_adapter._owner_thread) is int and r2_adapter._owner_thread == owner_thread,
            "capsule_owner_mismatch",
        )
        _require(
            type(r4_adapter._owner_thread) is int
            and r4_adapter._owner_thread == owner_thread
            and type(r5_adapter._owner_thread) is int
            and r5_adapter._owner_thread == owner_thread,
            "capsule_owner_mismatch",
        )
        _require(r4_adapter._supervising is False and r4_adapter._scope_callback_verified is False, "capsule_adapter_chain")
        _require(r2_module.ROOT_REAL_ADAPTER_ENABLED is False, "capsule_adapter_chain")
        _require(r5_adapter._target_observation_attempted is False, "capsule_adapter_chain")
        lock_type = type(threading.Lock())
        _require(
            type(r14_adapter._used_lock) is lock_type
            and r14_adapter._used is True
            and r14_adapter._used_lock.locked() is False,
            "capsule_adapter_chain",
        )
        _require(
            type(adapter._used_lock) is lock_type
            and adapter._used is True
            and adapter._used_lock.locked() is False,
            "capsule_adapter_chain",
        )
        _require(type(r23._PATCH_LOCK) is lock_type and r23._PATCH_LOCK.locked() is False, "capsule_adapter_chain")
        _require(r23._PATCH_OWNER_THREAD is None, "capsule_adapter_chain")
        _require(r23._R12._parent_projection is r23._ORIGINAL_PARENT_PROJECTION, "capsule_adapter_chain")
        root = _repo_root()
        r14_path = "scripts/iteration41_okx_m01_r33_parent_adapter_transport_r14_r1.py"
        _require(type(r14) is ModuleType, "capsule_source_pin")
        r14_globals = vars(r14)
        r14_raw = _verified_module_source(root, r14_globals, r14_path)
        r14_type = type(r14_adapter)
        r14_check = r14_globals.get("_check")
        _require(
            r14_globals.get("__name__") == r14_type.__module__
            and r14_globals.get("M01WindowsParentAdapter") is r14_type
            and r14_globals.get("_R13") is namespace.get("a")
            and type(r14_check) is FunctionType
            and r14_check.__globals__ is r14_globals,
            "capsule_source_pin",
        )
        _verify_class_source(r14_type, r14_globals, r14_raw, root / r14_path)
        _verify_function_source(r14_check, r14_raw, root / r14_path)
        _verify_loaded_module(
            r32,
            root,
            "scripts/iteration41_okx_m01_r32_external_parent_budget_r1.py",
            RUNTIME_SOURCE_PINS["scripts/iteration41_okx_m01_r32_external_parent_budget_r1.py"],
        )
        _verify_loaded_module(
            r2_module,
            root,
            "scripts/iteration41_okx_m01_r33_windows_parent_adapter_r2.py",
            RUNTIME_SOURCE_PINS["scripts/iteration41_okx_m01_r33_windows_parent_adapter_r2.py"],
        )
        _require(
            type(r4_adapter._r2_source) is bytes
            and _sha(r4_adapter._r2_source)
            == RUNTIME_SOURCE_PINS["scripts/iteration41_okx_m01_r33_windows_parent_adapter_r2.py"],
            "capsule_source_pin",
        )
        r8_path = "scripts/iteration41_okx_m01_r33_outer_route_phase_observer_r8_r1.py"
        r6_path = "scripts/iteration41_okx_m01_r33_windows_parent_adapter_r6.py"
        r5_path = "scripts/iteration41_okx_m01_r33_windows_parent_adapter_r5.py"
        r4_path = "scripts/iteration41_okx_m01_r33_windows_parent_adapter_r4.py"
        r2_path = "scripts/iteration41_okx_m01_r33_windows_parent_adapter_r2.py"

        # R8 imports R6, and R6 deliberately loads R5 into a fresh module then
        # removes its sys.modules entry. Follow the actual object chain through
        # function globals instead of rediscovering R5 by its temporary name.
        r8_type = type(r8_adapter)
        r8_init = r8_type.__dict__.get("__init__")
        _require(type(r8_init) is FunctionType, "capsule_source_pin")
        r8_globals = r8_init.__globals__
        r8_raw = _verified_module_source(root, r8_globals, r8_path)
        _require(
            r8_globals.get("__name__") == r8_type.__module__
            and r8_globals.get("M01WindowsParentAdapter") is r8_type,
            "capsule_source_pin",
        )
        _verify_class_source(r8_type, r8_globals, r8_raw, root / r8_path)
        r8_attributes = vars(r8_adapter)
        r8_projection = getattr(r8_adapter, "_project_r7_parent_result", None)
        r8_projection_function = r8_type.__dict__.get("_project_r7_parent_result")
        r8_projection_shadow = r8_attributes.get("_project_r7_parent_result")
        _require(
            type(r8_attributes) is dict
            and type(r8_projection) is MethodType
            and r8_projection.__self__ is r8_adapter
            and type(r8_projection_function) is FunctionType
            and r8_projection.__func__ is r8_projection_function,
            "capsule_adapter_chain",
        )
        if "_project_r7_parent_result" in r8_attributes:
            _require(
                type(r8_projection_shadow) is MethodType
                and r8_projection_shadow.__self__ is r8_adapter
                and r8_projection_shadow.__func__ is r8_projection_function,
                "capsule_adapter_chain",
            )

        r6_module = r8_globals.get("_R6")
        _require(type(r6_module) is ModuleType, "capsule_source_pin")
        _verify_loaded_module(
            r6_module, root, r6_path, RUNTIME_SOURCE_PINS[r6_path]
        )
        r6_globals = vars(r6_module)
        r6_raw = _verified_module_source(root, r6_globals, r6_path)
        r6_result_type = r6_globals.get("M01ParentDiagnosticResult")
        _require(
            type(r6_result_type) is type
            and r6_result_type.__name__ == "M01ParentDiagnosticResult"
            and r6_result_type.__module__ == r6_globals.get("__name__")
            and r6_result_type.__qualname__ == "M01ParentDiagnosticResult",
            "capsule_source_pin",
        )
        _require(
            r6_globals.get("R5_SOURCE_SHA256") == RUNTIME_SOURCE_PINS[r5_path],
            "capsule_source_pin",
        )
        _verify_function_source(r6_globals.get("_load_pinned_r5"), r6_raw, root / r6_path)
        r5_module = r6_globals.get("_R5")
        _require(type(r5_module) is ModuleType, "capsule_source_pin")
        _verify_loaded_module(r5_module, root, r5_path, RUNTIME_SOURCE_PINS[r5_path])
        r5_globals = vars(r5_module)
        r5_type = type(r5_adapter)
        r5_init = r5_type.__dict__.get("__init__")
        _require(
            type(r5_init) is FunctionType
            and r5_init.__globals__ is r5_globals
            and r5_globals.get("__name__") == r5_type.__module__
            and r5_globals.get("M01WindowsParentAdapter") is r5_type,
            "capsule_source_pin",
        )
        r5_raw = _verified_module_source(root, r5_globals, r5_path)
        _verify_class_source(r5_type, r5_globals, r5_raw, root / r5_path)
        _verify_function_source(
            r5_globals.get("_load_pinned_r4"), r5_raw, root / r5_path
        )
        _require(
            r5_globals.get("R4_SOURCE_SHA256") == RUNTIME_SOURCE_PINS[r4_path],
            "capsule_source_pin",
        )

        r4_module = r5_globals.get("_R4")
        _require(type(r4_module) is ModuleType, "capsule_source_pin")
        _verify_loaded_module(r4_module, root, r4_path, RUNTIME_SOURCE_PINS[r4_path])
        r4_globals = vars(r4_module)
        r4_raw = _verified_module_source(root, r4_globals, r4_path)
        r4_type = type(r4_adapter)
        r4_init = r4_type.__dict__.get("__init__")
        _require(
            type(r4_init) is FunctionType
            and r4_init.__globals__ is r4_globals
            and r4_globals.get("__name__") == r4_type.__module__
            and r4_globals.get("M01WindowsParentAdapter") is r4_type,
            "capsule_source_pin",
        )
        _verify_class_source(r4_type, r4_globals, r4_raw, root / r4_path)
        _verify_function_source(r4_globals.get("_load_private_r2"), r4_raw, root / r4_path)
        _require(
            r4_globals.get("R2_SOURCE_SHA256") == RUNTIME_SOURCE_PINS[r2_path],
            "capsule_source_pin",
        )

        _require(type(r2_module) is ModuleType, "capsule_source_pin")
        _verify_loaded_module(r2_module, root, r2_path, RUNTIME_SOURCE_PINS[r2_path])
        r2_globals = vars(r2_module)
        r2_raw = _verified_module_source(root, r2_globals, r2_path)
        r2_type = type(r2_adapter)
        r2_init = r2_type.__dict__.get("__init__")
        _require(
            type(r2_init) is FunctionType
            and r2_init.__globals__ is r2_globals
            and r2_globals.get("__name__") == r2_type.__module__
            and r2_globals.get("M01WindowsParentAdapter") is r2_type,
            "capsule_source_pin",
        )
        _verify_class_source(r2_type, r2_globals, r2_raw, root / r2_path)
        _require(r4_adapter._r2_module is r2_module, "capsule_adapter_chain")
        return adapter, r14_adapter, r2_adapter, r32, r6_module
    except NoSessionCleanupBlocked:
        raise
    except BaseException:
        _fail("capsule_adapter_chain")


def _validate_controls(namespace: dict[str, Any]) -> None:
    private = namespace.get("private")
    control = namespace.get("control")
    deploy = namespace.get("deploy")
    root_namespace = namespace.get("ns")
    _require(type(root_namespace) is dict, "capsule_control_shape")
    cls = getattr(private, "PrivateArtifactDirectory", None)
    _require(isinstance(cls, type), "capsule_control_shape")
    try:
        names = tuple(field.name for field in dataclasses.fields(cls))
    except BaseException:
        _fail("capsule_control_shape")
    _require(names == ("path", "device", "inode", "operation_deadline"), "capsule_control_shape")
    expected = (
        (control, root_namespace.get("control_dir")),
        (deploy, root_namespace.get("deployment_dir")),
    )
    for value, path in expected:
        _require(type(value) is cls and type(path) is str, "capsule_control_shape")
        _require(_key(str(value.path)) == _key(path), "capsule_control_shape")
        _require(type(value.device) is int and value.device >= 0, "capsule_control_shape")
        _require(type(value.inode) is int and value.inode > 0, "capsule_control_shape")
        _require(value.operation_deadline is None, "capsule_control_shape")
        try:
            attributes = vars(value)
        except BaseException:
            _fail("capsule_control_shape")
        _require(
            type(attributes) is dict
            and set(attributes) == set(names)
            and not any("job" in name.lower() or "worker" in name.lower() for name in attributes),
            "capsule_control_shape",
        )


def _validate_live_facts(
    namespace: dict[str, Any],
    owner_pid: int,
    owner_thread: int,
) -> tuple[Any, Any, Any, Any, Any, Any, Any, Any, Any, Any, Any]:
    _require(
        type(namespace.get("parent_started")) is bool
        and namespace["parent_started"] is True
        and namespace.get("phase") == "actual_parent_returned"
        and namespace.get("parent_call_returned") is True
        and namespace.get("plan_created") is True
        and namespace.get("auth_called") is True
        and namespace.get("auth_succeeded") is False
        and namespace.get("release_called") is False
        and namespace.get("release_succeeded") is False
        and namespace.get("main_entered") is True
        and namespace.get("extra_entered") is True
        and namespace.get("main_retained") is True
        and namespace.get("extra_retained") is True
        and namespace.get("main_postverified") is False
        and namespace.get("extra_postverified") is False,
        "capsule_same_call_required",
    )
    phases = namespace.get("root_phase_seconds")
    _require(
        type(phases) is dict
        and "plan_contract_source_slice" in phases
        and type(phases.get("plan_contract_source_slice")) in (int, float)
        and phases["plan_contract_source_slice"] >= 0
        and type(phases.get("actual_parent_supervise")) in (int, float)
        and phases["actual_parent_supervise"] >= 0,
        "capsule_same_call_required",
    )
    _require(
        type(owner_pid) is int
        and owner_pid > 0
        and owner_pid == os.getpid()
        and type(owner_thread) is int
        and owner_thread > 0
        and owner_thread == threading.get_ident(),
        "capsule_owner_mismatch",
    )
    result = namespace.get("result")
    summary = namespace.get("summary")
    adapter, r14_adapter, r2_adapter, r32, r6_module = _validate_adapter_chain(
        namespace, owner_thread
    )
    try:
        result_type = r6_module.M01ParentDiagnosticResult
        _require(
            type(result) is result_type
            and dataclasses.is_dataclass(result_type)
            and result_type.__dataclass_params__.frozen is True
            and tuple(field.name for field in dataclasses.fields(result_type))
            == (
                "schema",
                "status",
                "reason",
                "cleanup_reason",
                "child_returncode",
                "capture_complete",
                "cleanup_complete",
                "scope_released",
                "scope_retained",
                "stdout_bytes",
                "stderr_bytes",
                "child_phase",
            ),
            "capsule_result_not_no_session",
        )
        result_attributes = vars(result)
        _require(
            type(result_attributes) is dict
            and set(result_attributes)
            == {
                "schema",
                "status",
                "reason",
                "cleanup_reason",
                "child_returncode",
                "capture_complete",
                "cleanup_complete",
                "scope_released",
                "scope_retained",
                "stdout_bytes",
                "stderr_bytes",
                "child_phase",
            }
            and result.schema == r32.RESULT_SCHEMA
            and type(result.schema) is str
            and type(result.status) is str
            and type(result.reason) is str
            and type(result.cleanup_reason) is str
            and result.status == "CLEANUP_UNCERTAIN"
            and result.reason == "source_scope_unverified"
            and result.cleanup_reason == "session_unavailable"
            and result.child_returncode is None
            and type(result.capture_complete) is bool
            and result.capture_complete is False
            and type(result.cleanup_complete) is bool
            and result.cleanup_complete is False
            and type(result.scope_released) is bool
            and result.scope_released is False
            and type(result.scope_retained) is bool
            and result.scope_retained is True
            and result.stdout_bytes is None
            and result.stderr_bytes is None
            and type(result.child_phase) is dict
            and result.child_phase.get("authority") is False
            and type(result.child_phase.get("strict_cases_passed")) is int
            and result.child_phase.get("strict_cases_passed") == 0,
            "capsule_result_not_no_session",
        )
        _require(type(summary) is dict, "capsule_result_not_no_session")
        current_summary = adapter.summarize_result(result)
        _require(
            type(current_summary) is dict
            and current_summary.get("status") == "CLEANUP_UNCERTAIN"
            and type(current_summary.get("status")) is str
            and current_summary.get("reason") == "source_scope_unverified"
            and type(current_summary.get("reason")) is str
            and current_summary.get("cleanup_reason") == "session_unavailable"
            and type(current_summary.get("cleanup_reason")) is str
            and current_summary.get("child_returncode") is None
            and current_summary.get("capture_complete") is False
            and current_summary.get("cleanup_complete") is False
            and current_summary.get("scope_released") is False
            and current_summary.get("scope_retained") is True
            and current_summary.get("stdout_bytes") is None
            and current_summary.get("stderr_bytes") is None
            and current_summary.get("authority") is False
            and type(current_summary.get("strict_cases_passed")) is int
            and current_summary.get("strict_cases_passed") == 0
            and current_summary.get("child_phase") == result.child_phase
            and summary.get("schema") == current_summary.get("schema")
            and summary.get("status") == current_summary.get("status")
            and summary.get("reason") == current_summary.get("reason")
            and summary.get("cleanup_reason") == current_summary.get("cleanup_reason")
            and summary.get("child_returncode") is None
            and summary.get("capture_complete") is False
            and summary.get("cleanup_complete") is False
            and summary.get("scope_released") is False
            and summary.get("scope_retained") is True
            and summary.get("stdout_bytes") is None
            and summary.get("stderr_bytes") is None
            and summary.get("authority") is False
            and type(summary.get("strict_cases_passed")) is int
            and summary.get("strict_cases_passed") == 0
            and summary.get("child_phase") == current_summary.get("child_phase"),
            "capsule_result_not_no_session",
        )
    except NoSessionCleanupBlocked:
        raise
    except BaseException:
        _fail("capsule_result_not_no_session")

    source_scope = namespace.get("source_scope")
    extra_scope = namespace.get("extra_scope")
    main_scope = namespace.get("main_scope")
    extra_held = namespace.get("extra_held")
    held = namespace.get("held")
    extra_lease = namespace.get("extra_lease")
    main_lease = namespace.get("main_lease")
    keepalive = namespace.get("KEEPALIVE")
    r23_result = namespace.get("r23_adapter_result")
    _require(
        type(source_scope) is tuple
        and len(source_scope) == 4
        and source_scope[0] is extra_scope
        and source_scope[1] is extra_held
        and source_scope[2] is main_scope
        and source_scope[3] is held,
        "capsule_same_call_required",
    )
    try:
        draft = namespace["draft"]
        prepared = namespace["prepared"]
        prepared_r13 = namespace["prepared_r13"]
        active_source_map = namespace["active_source_map"]
        plan_path = namespace["ns"]["plan_path"]
        plan_bytes = draft["plan_bytes"]
        plan_sha256 = _sha(plan_bytes)
        held_plan = held[_key(plan_path)]
    except BaseException:
        _fail("capsule_source_maps")
    _require(
        type(plan_bytes) is bytes
        and type(active_source_map) is dict
        and held_plan == plan_bytes
        and active_source_map.get("plan_sha256") == plan_sha256
        and prepared.transform_binding.get("plan_sha256") == plan_sha256
        and prepared_r13.binding.get("plan_sha256") == plan_sha256,
        "capsule_source_maps",
    )
    _require(
        type(extra_lease) is list
        and len(extra_lease) == 4
        and extra_lease[0] is extra_scope
        and extra_lease[1] is namespace.get("private")
        and extra_lease[2] is namespace.get("cli")
        and extra_lease[3] is extra_held
        and type(main_lease) is list
        and len(main_lease) == 5
        and main_lease[0] is main_scope
        and main_lease[1] is namespace.get("mp")
        and main_lease[2] is namespace.get("mc")
        and main_lease[3] is held
        and main_lease[4] is namespace.get("prepared")
        and type(keepalive) is list
        and len(keepalive) == 3
        and keepalive[0] is extra_lease
        and keepalive[1] is r23_result
        and keepalive[2] is main_lease
        and sum(value is extra_lease for value in keepalive) == 1
        and sum(value is main_lease for value in keepalive) == 1,
        "capsule_same_call_required",
    )

    registry = r32._DEFAULT_RETENTION_REGISTRY
    _require(type(registry) is r32.StrongRetentionRegistry, "capsule_registry_binding")
    lock = getattr(registry, "_lock", None)
    _require(type(lock) is type(threading.Lock()), "capsule_registry_binding")
    if not lock.acquire(False):
        _fail("capsule_registry_binding")
    try:
        entries = getattr(registry, "_entries", None)
        _require(type(entries) is list, "capsule_registry_binding")
        matches = [
            entry
            for entry in entries
            if type(entry) is tuple
            and len(entry) == 5
            and entry[0] is source_scope
            and entry[1] is r2_adapter
        ]
        _require(len(matches) == 1, "capsule_registry_binding")
        entry = matches[0]
        cleanup_state = entry[3]
        _require(
            entry[2] is None
            and entry[4] is None
            and type(cleanup_state) is dict
            and set(cleanup_state) == {"clean", "reason"}
            and cleanup_state.get("clean") is False
            and cleanup_state.get("reason") == "session_unavailable",
            "capsule_registry_binding",
        )
    finally:
        lock.release()
    return (
        source_scope,
        registry,
        entries,
        entry,
        extra_lease,
        main_lease,
        adapter,
        r32,
        r2_adapter,
        r2_adapter._retained_late,
        lock,
    )


def _run_source_validators(namespace: dict[str, Any]) -> None:
    r23 = namespace["r23"]
    r22 = namespace["r22"]
    r21 = namespace["r21"]
    r20 = namespace["r20"]
    r19 = namespace["r19"]
    r17 = namespace["r17"]
    try:
        _require(r23.verify_root_hold(namespace["r23_prepared_hold"]), "capsule_source_validators")
        _require(r23.verify_parent_adapter_result(namespace["r23_adapter_result"]), "capsule_source_validators")
        _require(r22.verify_parent_adapter_result(namespace["r22_adapter_result"]), "capsule_source_validators")
        _require(r21.verify_parent_adapter_result(namespace["r21_adapter_result"]), "capsule_source_validators")
        _require(r20.verify_parent_adapter_result(namespace["r20_adapter_result"]), "capsule_source_validators")
        _require(r19.verify_parent_adapter_result(namespace["r19_adapter_result"]), "capsule_source_validators")
        _require(r17.verify_hold_addition(namespace["r17_result"]), "capsule_source_validators")
    except NoSessionCleanupBlocked:
        raise
    except BaseException:
        _fail("capsule_source_validators")


def close_rejected_no_session_scope(
    namespace: dict[str, Any],
    *,
    expected_owner_pid: int,
    expected_owner_thread: int,
    capsule_sha256: str,
) -> NoSessionCleanupReceipt:
    """Close the exact R23 main/extra CUV2 leases after proven no-session rejection.

    The caller must execute this in the original owner process and thread and
    provide the reviewed capsule SHA-256.  Any uncertain precondition keeps
    both leases and the R32 registry tuple intact.
    """

    with _verifier_phase(10):
        _require(type(namespace) is dict, "capsule_same_call_required")
        captured_release = _capture_release_callback(namespace)
    with _verifier_phase(20):
        root, verified_pins, driver_source = _verify_runtime_sources(namespace, capsule_sha256)
    with _verifier_phase(30):
        _verify_loaded_modules(namespace, root)
    with _verifier_phase(40):
        _verify_root_driver_callbacks(namespace, root, driver_source)
    with _verifier_phase(50):
        captured_cuv2 = _validate_cuv2_scope_binding(namespace, root, driver_source)
    with _verifier_phase(60):
        _verify_live_r13_source_binding(namespace, root)
    with _verifier_phase(70):
        facts = _validate_live_facts(namespace, expected_owner_pid, expected_owner_thread)
    (
        source_scope,
        registry,
        entries,
        registry_entry,
        extra_lease,
        main_lease,
        adapter,
        r32,
        r2_adapter,
        retained_late,
        registry_lock,
    ) = facts
    with _verifier_phase(80):
        _validate_controls(namespace)
    with _verifier_phase(90):
        _validate_maps(namespace)
    with _verifier_phase(100):
        _run_source_validators(namespace)

    # Recheck owner, registry identity, and no-session state immediately before
    # invoking the original thread-affine release callback.
    with _verifier_phase(110):
        _require(
            os.getpid() == expected_owner_pid
            and threading.get_ident() == expected_owner_thread
            and registry._lock is registry_lock
            and namespace.get("auth_called") is True
            and namespace.get("auth_succeeded") is False
            and namespace.get("release_called") is False
            and namespace.get("release_succeeded") is False,
            "capsule_same_call_required",
        )
        if not registry_lock.acquire(False):
            _fail("capsule_registry_binding")
        try:
            _require(
                registry._entries is entries
                and sum(value is registry_entry for value in entries) == 1,
                "capsule_registry_binding",
            )
        finally:
            registry_lock.release()
        _require(
            r2_adapter.native is None
            and r2_adapter.process_factory is None
            and r2_adapter._scope_authenticated is False
            and r2_adapter._retained_late is retained_late
            and type(retained_late) is list
            and len(retained_late) == 0
            and r2_adapter._owner_thread == expected_owner_thread
            and registry._lock is registry_lock
            and type(registry_lock) is type(threading.Lock())
            and registry_entry[0] is source_scope
            and registry_entry[1] is r2_adapter
            and registry_entry[2] is None
            and registry_entry[3].get("clean") is False
            and registry_entry[3].get("reason") == "session_unavailable"
            and registry_entry[4] is None,
            "capsule_registry_binding",
        )
        _require(
            r32._DEFAULT_RETENTION_REGISTRY is registry
            and type(r32.PARENT_CLEANUP_SECONDS) is float
            and r32.PARENT_CLEANUP_SECONDS == 5.0,
            "capsule_registry_binding",
        )
        current_cuv2 = _validate_cuv2_scope_binding(namespace, root, driver_source)
        _require(
            _same_cuv2_scope_binding(captured_cuv2, current_cuv2),
            "capsule_scope_binding",
        )
        release = _recheck_release_callback(namespace, root, driver_source, captured_release)
    try:
        with _verifier_phase(120):
            released = release(source_scope, float(r32.PARENT_CLEANUP_SECONDS))
            _require(
                released is True
                and namespace.get("release_called") is True
                and namespace.get("release_succeeded") is True
                and namespace.get("main_retained") is False
                and namespace.get("extra_retained") is False
                and namespace.get("main_postverified") is True
                and namespace.get("extra_postverified") is True,
                "capsule_scope_release_failed",
            )
    except BaseException:
        with _verifier_phase(120):
            _fail("capsule_scope_release_failed")

    with _verifier_phase(130):
        payload = {
        "schema": R24R7_SCHEMA,
        "status": "SOURCE_SCOPES_CLOSED_AFTER_AUTH_REJECTION",
        "original_parent_status": "CLEANUP_UNCERTAIN",
        "original_parent_reason": "source_scope_unverified",
        "session_created": False,
        "worker_created": False,
        "child_returncode_observed": False,
        "main_scope_postverified_closed": True,
        "extra_scope_postverified_closed": True,
        "r32_registry_entry_removed": True,
        "root_scope_references_dropped": True,
            "strict_cases_passed": 0,
            "case_pass": False,
            "authority": False,
            "owner_process_id": expected_owner_pid,
            "owner_thread_id": expected_owner_thread,
            "verifier_phase_ordinal": 130,
            "source_pins": dict(sorted(verified_pins.items())),
        }
        receipt = NoSessionCleanupReceipt(payload, expected_owner_pid, expected_owner_thread)
        _require(registry._lock is registry_lock, "capsule_registry_close_failed")
        if not registry_lock.acquire(False):
            _fail("capsule_registry_close_failed")
        try:
            current = registry._entries
            _require(
                current is entries and sum(value is registry_entry for value in entries) == 1,
                "capsule_registry_close_failed",
            )
            index = next(index for index, value in enumerate(current) if value is registry_entry)
            keepalive = namespace["KEEPALIVE"]
            try:
                keepalive[:] = [
                    value
                    for value in keepalive
                    if value is not extra_lease and value is not main_lease
                ]
                for name, expected in (
                    ("extra_lease", extra_lease),
                    ("main_lease", main_lease),
                    ("source_scope", source_scope),
                    ("extra_scope", source_scope[0]),
                    ("extra_held", source_scope[1]),
                    ("main_scope", source_scope[2]),
                    ("held", source_scope[3]),
                ):
                    if namespace.get(name) is expected:
                        namespace.pop(name)
                for name in ("private", "cli", "mp", "mc"):
                    namespace.pop(name, None)
                _require(
                    not any(value is extra_lease or value is main_lease for value in keepalive)
                    and all(
                        name not in namespace
                        for name in (
                            "extra_lease",
                            "main_lease",
                            "source_scope",
                            "extra_scope",
                            "extra_held",
                            "main_scope",
                            "held",
                        )
                    ),
                    "capsule_reference_drop_failed",
                )
            except NoSessionCleanupBlocked:
                raise
            except BaseException:
                _fail("capsule_reference_drop_failed")

            # The registry remains the strong owner while Root references are
            # dropped. Remove only the exact no-session tuple as the final step.
            current.pop(index)
        except NoSessionCleanupBlocked:
            raise
        except BaseException:
            _fail("capsule_registry_close_failed")
        finally:
            registry_lock.release()

    return receipt

