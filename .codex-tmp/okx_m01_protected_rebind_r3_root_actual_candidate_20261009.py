"""Root-only one-call OKX M01 metadata rebind and source admission check.

This fixed caller is intentionally not registered. It does not load account
credentials, invoke the M01 runner, or contact a provider. Root must review the
exact source and run it once in a fresh isolated CPython 3.11.5 host only after
all fixed public/software pins and the R3 backup/output namespaces are fresh.
"""

from __future__ import annotations

import ast
import contextlib
import hashlib
import inspect
import json
import os
from pathlib import Path
import stat
import sys
import types


ROOT = Path("D:/source_code/backtrader")
EVIDENCE = (
    "docs/_internal/opts/requirements/"
    "迭代41-实盘执行风控监控与示例架构重构/evidence/"
)
MAP_RELATIVE = EVIDENCE + "iteration41-okx-m01-root-helper-lifecycle-integration-r1-2026-10-09/source-map.json"
CURRENT_REVIEW_RELATIVE = (
    EVIDENCE
    + "iteration41-okx-m01-root-helper-lifecycle-integration-r1-independent-review-r1-"
    "2026-10-09-oct7f/README.md"
)
CURRENT_REVIEW_TEST_RELATIVE = (
    "tests/unit/scripts/test_iteration41_okx_m01_reader_lifecycle_integration_r1.py"
)
HELPER = "scripts/iteration41_okx_m01_v3_protected_rebind_r2.py"
HELPER_TEST = "tests/unit/scripts/test_iteration41_okx_m01_v3_protected_rebind_r2.py"
CANDIDATE_DIR = (
    EVIDENCE + "iteration41-okx-m01-v3-protected-rebind-r2-source-candidate-r1-2026-10-09/"
)
CANDIDATE_README = CANDIDATE_DIR + "README.md"
CANDIDATE_PINS = CANDIDATE_DIR + "candidate-pins.json"
STATIC_REVIEW = (
    EVIDENCE
    + "iteration41-okx-m01-v3-protected-rebind-r2-require-binding-independent-review-r1-"
    "2026-10-09/review.md"
)
DELIVERY_DIR = (
    EVIDENCE + "iteration41-okx-m01-v3-protected-rebind-r2-dev-delivery-proposal-r1-2026-10-09/"
)
ROOT_QA_DRIVER = DELIVERY_DIR + "root-source-qa.py"
ROOT_QA_RESULT = DELIVERY_DIR + "root-source-qa-result.json"
DELIVERY_MANIFEST = DELIVERY_DIR + "delivery-manifest.json"
POSTCOMMIT_RESULT = ".codex-tmp/okx_m01_rebind_r2_root_postcommit_20261009.json"

READER_RELATIVE = (
    "examples/000_live_certification/okx_penetration/"
    "_m01_readonly_monitor_v3/current_reader.py"
)
READER_PACKAGE_RELATIVE = (
    "examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v3/__init__.py"
)
CURRENT_TYPES_RELATIVE = (
    "examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v2/current_types.py"
)
SUPERVISOR_RELATIVE = (
    "examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v2/job_supervisor.py"
)
WORKER_RELATIVE = (
    "examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v2/worker.py"
)
PRIVATE_RELATIVE = "backtrader_runtime/certification_roundtrip_private.py"
CLI_RELATIVE = "backtrader_runtime/certification_binance_roundtrip_r3_cli.py"
CU = Path("D:/temp/iteration41-root-public-custody-v2.py")
CU_SHA256 = "e856be8e4056835d4a7e54f5c6b449c69ab3f1c2ebb049bcbcc1c95a9ad3f246"
CLI_SHA256 = "62b96a9040d530c8ec592471f0595154fb60239ca03bd6d3b56a6c094dfc7c76"
CLI_SIZE = 33887

MAP_SHA256 = "07f0eb60d60f37919c75cc3ec6833b41653fdbc9952c8478dbbc36ba0cda1ff3"
MAP_SIZE = 2877
REVIEW_SHA256 = "c09eb8be009567b70d50a063e042ef7d75af8ce8d2368fd568bdb4b82e38263b"
REVIEW_SIZE = 3820
REVIEW_TEST_SHA256 = "21d43a5e8d1c517c2ffaa147c96f58343fb188432d4fae47717a5b68b6ec040d"
REVIEW_TEST_SIZE = 9809
HELPER_SHA256 = "0baa2191b8d5b99b42e7a13ddc217f0d90291db8279b20f74a3d92c676649810"
HELPER_SIZE = 28418
HELPER_TEST_SHA256 = "4268d340cae45dbcf7574c38f98f2546df78f9a7ff82049f0baecad2904b5eea"
HELPER_TEST_SIZE = 23557
OLD_MAP_SHA256 = "db7b351656a0e26aac3778332ed7eb838a92a73605a5bb3604cb4b770c06ebe3"
TARGET_REVIEW_REF = "iteration41-okx-m01-source-owned-v3-review-r2"
TARGET_MAP_SHA256 = MAP_SHA256
R3_BACKUP_CHILD = "r3-20261009-preservation"
DEPLOYMENT = Path("D:/temp/iteration41-okx-m01-v3-deployment")
R3_BACKUP = DEPLOYMENT / R3_BACKUP_CHILD

CURRENT_REVIEWED_SOURCES = {
    READER_RELATIVE: (
        68215,
        "5a8fd479c999279d9efde625cac1938d794201f04e1beaa6f3663b267d7a7ebc",
    ),
    "examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v3/entry.py": (
        5952,
        "e0613b66fa54d5ea155da263d1e901e8ada78adf7d83a7e1c8dc5430ea440d1e",
    ),
    "examples/000_live_certification/okx_penetration/cases/M01/run.py": (
        1992,
        "d498e32fcb573781a3eec25eff4c7ba98bfe2c8d4d94f9e5a9b078ab4074641e",
    ),
}

SUPPORT_PINS = {
    MAP_RELATIVE: (MAP_SIZE, MAP_SHA256),
    CURRENT_REVIEW_RELATIVE: (REVIEW_SIZE, REVIEW_SHA256),
    CURRENT_REVIEW_TEST_RELATIVE: (REVIEW_TEST_SIZE, REVIEW_TEST_SHA256),
    HELPER: (HELPER_SIZE, HELPER_SHA256),
    HELPER_TEST: (HELPER_TEST_SIZE, HELPER_TEST_SHA256),
    CANDIDATE_README: (
        4183,
        "f474779d3dda9b88568fc35a6cc2faccff9765fbed9ef23783a0f6fc9b94ca37",
    ),
    CANDIDATE_PINS: (
        2165,
        "dad69ff22275926d824b895a60b59995ecd7e8659f223c88d852cb01a6394043",
    ),
    STATIC_REVIEW: (
        1834,
        "fe530a9e8323a5ee492c1d7b1fc80028423df70ad5fd032143ce1790c965f2d4",
    ),
    ROOT_QA_DRIVER: (
        7952,
        "54540781820cab39cdfd3ce2f62b7fc2be4688bffec5a72e0fa7881a411fe583",
    ),
    ROOT_QA_RESULT: (
        6751,
        "e08ca3aac8f6479117c0066b741ad557ff4d24cfb9da556785a6eaa3af7d1744",
    ),
    DELIVERY_MANIFEST: (
        6340,
        "2d0c87fdcfe2a0a06cfb1617655fb87bb047ba66d1e0089af37b2a247efdeb7a",
    ),
    POSTCOMMIT_RESULT: (
        2416,
        "3a13f0f612e63d543ee47cc140e1d6f72db98814f59f56b258a4bca96b4fc55c",
    ),
    CLI_RELATIVE: (CLI_SIZE, CLI_SHA256),
}

SOFTWARE = {
    "C:/anaconda3/python.exe": "c98caee82c66433f0e89d4abbf152b39a7dc2e99979b28dcb021598b4e3f5642",
    "C:/anaconda3/python311.dll": "162e8557fbed5f39ae24983ee62b2d435b4796c937d9c1a34371888c7e43af00",
    str(CU): CU_SHA256,
}
PUBLIC_SOURCE_MAX_BYTES = 2 * 1024 * 1024
SOFTWARE_BINARY_MAX_BYTES = 8 * 1024 * 1024
PYTHON_DLL_EXPECTED_BYTES = 5_991_424
OUT = ROOT / EVIDENCE / "iteration41-okx-m01-v3-protected-rebind-root-actual-r3-2026-10-09"

SAFE_HELPER_ERRORS = frozenset(
    {
        "invalid_root_inputs",
        "review_identity_mismatch",
        "reader_binding_mismatch",
        "source_map_invalid",
        "source_pin_mismatch",
        "old_metadata_invalid",
        "protected_path_invalid",
        "backup_name_in_use",
        "protected_io_failed",
        "protected_write_uncertain",
        "protected_close_uncertain",
        "operation_deadline",
    }
)
SAFE_ROOT_REASONS = frozenset(
    {
        "public_input_invalid",
        "root_scope_acquire_failed",
        "root_source_binding_failed",
        "metadata_helper_failed",
        "fresh_source_admission_failed",
        "source_admission_release_failed",
        "source_cleanup_uncertain",
        "root_normal_postverify_failed",
        "root_call_failed",
    }
)
ROOT_STATE = {
    "output_owned": False,
    "scope": None,
    "held": None,
    "cu": None,
    "private": None,
    "raw": None,
    "cli_module": None,
    "reader": None,
    "helper": None,
    "modules": (),
    "bindings": (),
    "admission": None,
    "admission_private_binding": None,
    "registries": (),
    "bindings_complete": False,
    "registry_snapshot_complete": False,
}


class RootCallError(RuntimeError):
    def __init__(self, code: str):
        self.code = code if code in SAFE_ROOT_REASONS else "root_call_failed"
        super().__init__(self.code)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _read_regular(path: Path, *, maximum: int, expected_sha256: str | None = None):
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or (getattr(info, "st_file_attributes", 0) & 0x400)
        or not 0 < info.st_size <= maximum
    ):
        raise RootCallError("public_input_invalid")
    with path.open("rb") as stream:
        raw = stream.read(maximum + 1)
    if len(raw) != info.st_size or len(raw) > maximum:
        raise RootCallError("public_input_invalid")
    if expected_sha256 is not None and sha(raw) != expected_sha256:
        raise RootCallError("public_input_invalid")
    return raw


def _verify_repo_path(path: Path) -> Path:
    candidate = Path(os.path.abspath(path))
    root = Path(os.path.abspath(ROOT))
    if candidate != root and root not in candidate.parents:
        raise RootCallError("public_input_invalid")
    try:
        if candidate.resolve(strict=True) != candidate:
            raise RootCallError("public_input_invalid")
        file_info = candidate.lstat()
        if (
            not stat.S_ISREG(file_info.st_mode)
            or (getattr(file_info, "st_file_attributes", 0) & 0x400)
        ):
            raise RootCallError("public_input_invalid")
        for ancestor in candidate.parents:
            if ancestor != root and root not in ancestor.parents:
                continue
            info = ancestor.lstat()
            if (
                not stat.S_ISDIR(info.st_mode)
                or (getattr(info, "st_file_attributes", 0) & 0x400)
            ):
                raise RootCallError("public_input_invalid")
    except RootCallError:
        raise
    except Exception:
        raise RootCallError("public_input_invalid") from None
    return candidate


def public_bytes(relative: str, expected_size: int, expected_sha256: str) -> bytes:
    raw = _read_regular(
        _verify_repo_path(ROOT / Path(relative)),
        maximum=PUBLIC_SOURCE_MAX_BYTES,
        expected_sha256=expected_sha256,
    )
    if len(raw) != expected_size:
        raise RootCallError("public_input_invalid")
    return raw


def software_binary_bytes(path: Path, expected_sha256: str, *, expected_size: int | None = None):
    raw = _read_regular(path, maximum=SOFTWARE_BINARY_MAX_BYTES, expected_sha256=expected_sha256)
    if expected_size is not None and len(raw) != expected_size:
        raise RootCallError("public_input_invalid")
    return raw


def load_held(
    raw: bytes,
    path: Path,
    name: str,
    *,
    package_name: str | None = None,
    is_package: bool = False,
):
    if name in sys.modules:
        raise RootCallError("root_source_binding_failed")
    module = types.ModuleType(name)
    module.__file__ = str(path)
    module.__package__ = name if is_package else (package_name or name.rpartition(".")[0])
    module.__cached__ = None
    if is_package:
        module.__path__ = [str(path.parent)]
    sys.modules[name] = module
    try:
        exec(compile(raw, str(path), "exec", dont_inherit=True), module.__dict__)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def _code_objects(code: types.CodeType, result: dict[str, list[types.CodeType]]):
    result.setdefault(code.co_qualname, []).append(code)
    for value in code.co_consts:
        if isinstance(value, types.CodeType):
            _code_objects(value, result)


def _descriptor_functions(value):
    if isinstance(value, (staticmethod, classmethod)):
        return (("function", value.__func__),)
    if isinstance(value, property):
        return tuple(
            (slot, function)
            for slot, function in (("fget", value.fget), ("fset", value.fset), ("fdel", value.fdel))
            if function is not None
        )
    if type(value) is types.FunctionType:
        return (("function", value),)
    return ()


def _descriptor_kind(value):
    if type(value) is property:
        return "property", {
            slot
            for slot, function in (
                ("fget", value.fget),
                ("fset", value.fset),
                ("fdel", value.fdel),
            )
            if function is not None
        }
    if type(value) is staticmethod:
        return "staticmethod", {"function"}
    if type(value) is classmethod:
        return "classmethod", {"function"}
    if type(value) is types.FunctionType:
        return "function", {"function"}
    return None, set()


_VOLATILE_GLOBALS = {
    "_m01_readonly_monitor_v3.current_reader": {
        "_ADMISSIONS",
        "_CONSUMED_ADMISSIONS",
        "_CURRENT_READ_EVIDENCE",
        "_ORPHANED_SOURCE_ADMISSIONS",
        "_ROOT_HELPER_RETAINED_CONTEXTS",
    },
    "_m01_readonly_monitor_v2.current_types": {"_ISSUED", "_CONSUMED"},
    "_m01_readonly_monitor_v2.job_supervisor": {"_ORPHANED_RUNTIME_HANDLE_SETS"},
    "_root_okx_m01_metadata_helper_r2": {"_ORPHANED_CONTEXTS"},
    "_root_public_custody_private": {"_API"},
    "_okx_m01_v3_admission_private": {"_API"},
}

_MISSING = object()


def _contextmanager_wrapper_matches(wrapper, generator):
    expected = contextlib.contextmanager(generator)
    wrapper_closure = tuple(cell.cell_contents for cell in (wrapper.__closure__ or ()))
    expected_closure = tuple(cell.cell_contents for cell in (expected.__closure__ or ()))
    return (
        type(wrapper) is types.FunctionType
        and wrapper.__code__ is expected.__code__
        and wrapper.__globals__ is expected.__globals__
        and tuple(map(id, wrapper_closure)) == tuple(map(id, expected_closure))
    )


def _expected_definitions(tree: ast.Module):
    definitions: dict[str, dict[str, object]] = {}
    dataclass_classes: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            definitions[node.name] = {
                "kind": "function",
                "slots": {"function"},
                "contextmanager": any(
                    isinstance(item, ast.Name) and item.id == "contextmanager"
                    for item in node.decorator_list
                ),
            }
        elif isinstance(node, ast.ClassDef):
            class_name = node.name
            if any(
                (isinstance(item, ast.Name) and item.id == "dataclass")
                or (isinstance(item, ast.Call) and isinstance(item.func, ast.Name) and item.func.id == "dataclass")
                for item in node.decorator_list
            ):
                dataclass_classes.add(class_name)
            for item in node.body:
                if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                qualname = f"{class_name}.{item.name}"
                kind = "function"
                slots = {"function"}
                for decorator in item.decorator_list:
                    if isinstance(decorator, ast.Name) and decorator.id == "property":
                        kind, slots = "property", {"fget"}
                    elif isinstance(decorator, ast.Name) and decorator.id == "staticmethod":
                        kind = "staticmethod"
                    elif isinstance(decorator, ast.Name) and decorator.id == "classmethod":
                        kind = "classmethod"
                    elif isinstance(decorator, ast.Attribute) and decorator.attr in {"setter", "deleter"}:
                        kind = "property"
                        slots = {"fset" if decorator.attr == "setter" else "fdel"}
                wrapped_by_contextmanager = any(
                    isinstance(value, ast.Name) and value.id == "contextmanager"
                    for value in item.decorator_list
                )
                previous = definitions.get(qualname)
                if previous is not None and previous["kind"] == "property" and kind == "property":
                    previous["slots"].add(next(iter(slots)))
                    previous["contextmanager"] = (
                        previous["contextmanager"] or wrapped_by_contextmanager
                    )
                else:
                    definitions[qualname] = {
                        "kind": kind,
                        "slots": set(slots),
                        "contextmanager": wrapped_by_contextmanager,
                    }
    return definitions, dataclass_classes


_GENERATED_DATACLASS_METHODS = {
    "_m01_readonly_monitor_v3.current_reader": {
        "_HeldFile": {"__init__", "__repr__", "__eq__"},
        "_HeldDirectory": {"__init__", "__repr__", "__eq__"},
        "SourceAdmission": {"__init__", "__setattr__", "__delattr__"},
        "VerifiedAccountConfigurationRead": {"__init__", "__setattr__", "__delattr__"},
    },
    "_m01_readonly_monitor_v2.current_types": {
        "M01Invocation": {"__init__", "__setattr__", "__delattr__"},
        "CurrentReadProof": {"__init__", "__setattr__", "__delattr__"},
    },
    "_m01_readonly_monitor_v2.worker": {
        "LaunchRequest": {"__init__", "__eq__", "__setattr__", "__delattr__", "__hash__"},
        "DemoCredentials": {"__init__", "__eq__", "__setattr__", "__delattr__", "__hash__"},
        "SocketCloseObservation": {
            "__init__",
            "__repr__",
            "__eq__",
            "__setattr__",
            "__delattr__",
            "__hash__",
        },
    },
    "_m01_readonly_monitor_v2.job_supervisor": {
        "PrivateEvent": {"__init__", "__eq__", "__setattr__", "__delattr__", "__hash__"},
        "ObserverReady": {
            "__init__",
            "__repr__",
            "__eq__",
            "__setattr__",
            "__delattr__",
            "__hash__",
        },
        "ObserverWorkerReceipt": {
            "__init__",
            "__eq__",
            "__setattr__",
            "__delattr__",
            "__hash__",
        },
        "QuietWindow": {
            "__init__",
            "__repr__",
            "__eq__",
            "__setattr__",
            "__delattr__",
            "__hash__",
        },
        "ObservationDrain": {
            "__init__",
            "__repr__",
            "__eq__",
            "__setattr__",
            "__delattr__",
            "__hash__",
        },
        "ObserverCloseReceipt": {
            "__init__",
            "__repr__",
            "__eq__",
            "__setattr__",
            "__delattr__",
            "__hash__",
        },
    },
    "_certification.m01_private_monitor_v2": {
        "PrivateCredentials": {
            "__init__",
            "__eq__",
            "__setattr__",
            "__delattr__",
            "__hash__",
        },
        "LaunchRequest": {
            "__init__",
            "__eq__",
            "__setattr__",
            "__delattr__",
            "__hash__",
        },
        "EventJournalSummary": {
            "__init__",
            "__repr__",
            "__eq__",
            "__setattr__",
            "__delattr__",
            "__hash__",
        },
        "PrivateEventRef": {
            "__init__",
            "__eq__",
            "__setattr__",
            "__delattr__",
            "__hash__",
        },
        "WorkerReceipt": {
            "__init__",
            "__eq__",
            "__setattr__",
            "__delattr__",
            "__hash__",
        },
        "ProcessLifecycleReceipt": {
            "__init__",
            "__eq__",
            "__setattr__",
            "__delattr__",
            "__hash__",
        },
        "MonitorAssessment": {
            "__init__",
            "__repr__",
            "__eq__",
            "__setattr__",
            "__delattr__",
            "__hash__",
        },
    },
    "_root_public_custody_private": {
        "PrivateArtifactDirectory": {
            "__init__",
            "__repr__",
            "__eq__",
            "__setattr__",
            "__delattr__",
            "__hash__",
        },
    },
    "_okx_m01_v3_admission_private": {
        "PrivateArtifactDirectory": {
            "__init__",
            "__repr__",
            "__eq__",
            "__setattr__",
            "__delattr__",
            "__hash__",
        },
    },
}


def bind_module(
    module: types.ModuleType,
    raw: bytes,
    expected_path: Path,
    expected_name: str,
):
    expected_path = expected_path.resolve(strict=True)
    if (
        type(module) is not types.ModuleType
        or module.__name__ != expected_name
        or type(module.__file__) is not str
        or Path(module.__file__).resolve(strict=True) != expected_path
    ):
        raise RootCallError("root_source_binding_failed")
    source = raw.decode("utf-8", errors="strict")
    tree = ast.parse(source, filename=str(expected_path))
    expected_defs, dataclass_classes = _expected_definitions(tree)
    code_index: dict[str, list[types.CodeType]] = {}
    _code_objects(compile(raw, str(expected_path), "exec", dont_inherit=True), code_index)
    seen: set[str] = set()
    functions = []
    classes = []
    owners = [(module, vars(module))]
    for key, cls in tuple(vars(module).items()):
        if isinstance(cls, type) and cls.__module__ == expected_name:
            owners.append((cls, vars(cls)))
            class_items = tuple((name, id(value)) for name, value in vars(cls).items())
            classes.append((key, cls, class_items))
    generated = _GENERATED_DATACLASS_METHODS.get(expected_name, {})
    for owner, namespace in owners:
        for key, descriptor in tuple(namespace.items()):
            if owner is not module:
                source_def = expected_defs.get(f"{owner.__name__}.{key}")
                if source_def is not None:
                    actual_kind, actual_slots = _descriptor_kind(descriptor)
                    if actual_kind != source_def["kind"] or actual_slots != source_def["slots"]:
                        raise RootCallError("root_source_binding_failed")
            for slot, function in _descriptor_functions(descriptor):
                if type(function) is not types.FunctionType:
                    raise RootCallError("root_source_binding_failed")
                unwrapped = inspect.unwrap(function)
                if unwrapped.__module__ != expected_name:
                    continue
                if (
                    type(function) is not types.FunctionType
                    or type(unwrapped) is not types.FunctionType
                    or unwrapped.__globals__ is not module.__dict__
                ):
                    raise RootCallError("root_source_binding_failed")
                qualname = unwrapped.__qualname__
                if unwrapped.__code__.co_filename == str(expected_path):
                    expected = code_index.get(qualname, ())
                    if len(expected) != 1 or unwrapped.__code__ != expected[0]:
                        raise RootCallError("root_source_binding_failed")
                    source_def = expected_defs.get(qualname)
                    if source_def is None:
                        raise RootCallError("root_source_binding_failed")
                    wrapped_by_contextmanager = function is not unwrapped
                    if wrapped_by_contextmanager != source_def["contextmanager"]:
                        raise RootCallError("root_source_binding_failed")
                    if wrapped_by_contextmanager and not _contextmanager_wrapper_matches(
                        function, unwrapped
                    ):
                        raise RootCallError("root_source_binding_failed")
                    if owner is module:
                        if source_def["kind"] != "function" or slot != "function":
                            raise RootCallError("root_source_binding_failed")
                    elif slot not in source_def["slots"]:
                        raise RootCallError("root_source_binding_failed")
                    seen.add(qualname)
                else:
                    class_name, separator, method_name = qualname.rpartition(".")
                    allowed = generated.get(class_name, set())
                    if (
                        unwrapped.__code__.co_filename != "<string>"
                        or not separator
                        or class_name not in dataclass_classes
                        or method_name not in allowed
                        or key != method_name
                        or type(owner) is not type
                    ):
                        raise RootCallError("root_source_binding_failed")
                    seen.add(qualname)
                chain = []
                current = function
                while True:
                    chain.append(
                        (
                            current,
                            current.__code__,
                            current.__globals__,
                            current.__defaults__,
                            repr(current.__defaults__),
                            current.__kwdefaults__,
                            repr(current.__kwdefaults__),
                        )
                    )
                    wrapped = getattr(current, "__wrapped__", None)
                    if wrapped is None:
                        break
                    if type(wrapped) is not types.FunctionType:
                        raise RootCallError("root_source_binding_failed")
                    current = wrapped
                if current is not unwrapped:
                    raise RootCallError("root_source_binding_failed")
                functions.append((owner, key, slot, function, tuple(chain)))
    expected_names = set(expected_defs)
    if expected_names - seen:
        raise RootCallError("root_source_binding_failed")
    allowed_generated = {
        f"{class_name}.{method}"
        for class_name, names in generated.items()
        for method in names
    }
    if seen - expected_names - allowed_generated:
        raise RootCallError("root_source_binding_failed")
    module_constants = {
        key: (id(value), repr(value))
        for key, value in vars(module).items()
        if key.isupper() and key not in _VOLATILE_GLOBALS.get(expected_name, set())
    }
    module_globals = tuple(
        (key, id(value))
        for key, value in vars(module).items()
        if key not in _VOLATILE_GLOBALS.get(expected_name, set())
    )
    return (
        module,
        expected_name,
        expected_path,
        tuple(functions),
        tuple(classes),
        module_constants,
        module_globals,
    )


def verify_binding(record):
    module, expected_name, expected_path, functions, classes, constants, module_globals = record
    if (
        module.__name__ != expected_name
        or type(module.__file__) is not str
        or Path(module.__file__).resolve(strict=True) != expected_path
    ):
        raise RootCallError("root_source_binding_failed")
    for owner, key, slot, original, chain in functions:
        current = dict(_descriptor_functions(vars(owner).get(key))).get(slot)
        if current is not original or type(current) is not types.FunctionType:
            raise RootCallError("root_source_binding_failed")
        current_chain = []
        while True:
            current_chain.append(
                (
                    current,
                    current.__code__,
                    current.__globals__,
                    current.__defaults__,
                    repr(current.__defaults__),
                    current.__kwdefaults__,
                    repr(current.__kwdefaults__),
                )
            )
            wrapped = getattr(current, "__wrapped__", None)
            if wrapped is None:
                break
            if type(wrapped) is not types.FunctionType:
                raise RootCallError("root_source_binding_failed")
            current = wrapped
        if tuple(current_chain) != chain or current.__globals__ is not module.__dict__:
            raise RootCallError("root_source_binding_failed")
    for name, cls, class_items in classes:
        if vars(module).get(name) is not cls:
            raise RootCallError("root_source_binding_failed")
        if tuple((key, id(value)) for key, value in vars(cls).items()) != class_items:
            raise RootCallError("root_source_binding_failed")
    for key, (identity, representation) in constants.items():
        value = vars(module).get(key, _MISSING)
        if value is _MISSING or id(value) != identity or repr(value) != representation:
            raise RootCallError("root_source_binding_failed")
    current_globals = tuple(
        (key, id(value))
        for key, value in vars(module).items()
        if key not in _VOLATILE_GLOBALS.get(expected_name, set())
    )
    if current_globals != module_globals:
        raise RootCallError("root_source_binding_failed")


def _audit(event, args):
    if event in {
        "subprocess.Popen",
        "os.system",
        "os.posix_spawn",
        "os.spawn",
        "socket.connect",
        "socket.connect_ex",
        "socket.getaddrinfo",
        "socket.sendto",
        "socket.bind",
        "socket.listen",
    }:
        raise RuntimeError("root_metadata_process_network_forbidden")
    if event == "import" and isinstance(args[0], str):
        blocked = ("bt_api", "ccxt", "binance", "websocket", "requests", "httpx")
        if args[0].lower().startswith(blocked):
            raise RuntimeError("root_metadata_provider_import_forbidden")
    if event == "open" and isinstance(args[0], (str, bytes)):
        value = str(args[0]).replace("\\", "/").lower()
        if (
            value.endswith("/.env")
            or value.endswith("/config.yaml")
            or "private-capture" in value
        ):
            raise RuntimeError("root_metadata_private_input_forbidden")


def _source_map_doc(raw: bytes):
    value = json.loads(raw.decode("utf-8", errors="strict"))
    if (
        type(value) is not dict
        or set(value) != {"schema", "source_pins"}
        or value["schema"] != "iteration41.okx.m01.case-source-map.v3"
        or type(value["source_pins"]) is not dict
        or len(value["source_pins"]) != 19
        or raw != (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode("ascii")
    ):
        raise RootCallError("public_input_invalid")
    if set(value["source_pins"]) != set(SOURCE_MAP_EXPECTED_PATHS):
        raise RootCallError("public_input_invalid")
    return value


SOURCE_MAP_EXPECTED_PATHS = {
    READER_PACKAGE_RELATIVE,
    READER_RELATIVE,
    "examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v3/issuer.py",
    "examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v3/entry.py",
    "examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v2/__init__.py",
    CURRENT_TYPES_RELATIVE,
    SUPERVISOR_RELATIVE,
    WORKER_RELATIVE,
    "examples/000_live_certification/okx_penetration/_certification/m01_private_monitor_v2.py",
    "examples/000_live_certification/okx_penetration/_certification/__init__.py",
    "examples/000_live_certification/okx_penetration/_certification/models.py",
    "examples/000_live_certification/okx_penetration/_certification/cases.py",
    "examples/000_live_certification/okx_penetration/_certification/config.py",
    "examples/000_live_certification/okx_penetration/_certification/evidence.py",
    "examples/000_live_certification/okx_penetration/_certification/fixed_owner_routes.py",
    "examples/000_live_certification/okx_penetration/_certification/runner.py",
    "examples/000_live_certification/okx_penetration/cases/M01/M01_strategy.py",
    "examples/000_live_certification/okx_penetration/cases/M01/run.py",
    PRIVATE_RELATIVE,
}


def _safe_reason(error):
    code = getattr(error, "code", None)
    if type(code) is str and code in SAFE_HELPER_ERRORS:
        return code
    code = getattr(error, "reason", None)
    if type(code) is str and code in SAFE_HELPER_ERRORS:
        return code
    if isinstance(error, RootCallError) and error.code in SAFE_ROOT_REASONS:
        return error.code
    return "root_call_failed"


def _registry_counts(reader, helper):
    registry_values = []
    registry_counts = {}
    intact = True
    for label, module, name, expected_type, original in ROOT_STATE["registries"]:
        value = vars(module).get(name, _MISSING)
        current_ok = value is original and type(value) is expected_type
        intact = intact and current_ok
        count = len(value) if type(value) is expected_type else None
        registry_counts[label] = count
        registry_values.append(current_ok and count == 0)
    return registry_counts, intact, intact and all(registry_values)


def _capture_registries(reader, helper):
    expected = (
        ("retained_metadata_contexts", helper, "_ORPHANED_CONTEXTS", list),
        ("retained_admissions", reader, "_ADMISSIONS", dict),
        ("consumed_admissions", reader, "_CONSUMED_ADMISSIONS", set),
        ("orphaned_source_admissions", reader, "_ORPHANED_SOURCE_ADMISSIONS", list),
        ("reader_current_read_evidence", reader, "_CURRENT_READ_EVIDENCE", dict),
        ("reader_root_helper_contexts", reader, "_ROOT_HELPER_RETAINED_CONTEXTS", list),
        (
            "orphaned_runtime_handle_sets",
            reader.job_supervisor,
            "_ORPHANED_RUNTIME_HANDLE_SETS",
            list,
        ),
        ("current_type_issued", reader.current_types, "_ISSUED", dict),
        ("current_type_consumed", reader.current_types, "_CONSUMED", set),
    )
    records = []
    for label, module, name, expected_type in expected:
        value = vars(module).get(name, _MISSING)
        if value is _MISSING or type(value) is not expected_type:
            raise RootCallError("root_source_binding_failed")
        records.append((label, module, name, expected_type, value))
    ROOT_STATE["registries"] = tuple(records)
    return _registry_counts(reader, helper)


def _verify_private_api(module):
    api = vars(module).get("_API", _MISSING)
    api_type = vars(module).get("_Win32", _MISSING)
    if api is _MISSING or api_type is _MISSING or type(api) is not api_type:
        raise RootCallError("root_source_binding_failed")
    return module, api, api_type


def _verify_private_api_bindings(records):
    for module, api, api_type in records:
        if (
            vars(module).get("_API", _MISSING) is not api
            or type(api) is not api_type
            or vars(module).get("_Win32", _MISSING) is not api_type
        ):
            raise RootCallError("root_source_binding_failed")


def _verify_directory_chain(path: Path, stop: Path | None = None):
    current = Path(os.path.abspath(path))
    stop_path = Path(os.path.abspath(stop)) if stop is not None else None
    while True:
        info = current.lstat()
        if (
            not stat.S_ISDIR(info.st_mode)
            or (getattr(info, "st_file_attributes", 0) & 0x400)
        ):
            raise RootCallError("public_input_invalid")
        if stop_path is not None and current == stop_path:
            return
        parent = current.parent
        if parent == current:
            if stop_path is not None:
                raise RootCallError("public_input_invalid")
            return
        current = parent


def _initial_result():
    return {
        "schema": "iteration41.okx.m01.root_protected_metadata_rebind_r3.v1",
        "scope": "PROTECTED_METADATA_REBIND_AND_SOURCE_ADMISSION_RELEASE_ONLY",
        "status": "BLOCKED",
        "reason": None,
        "public_pin_count": 0,
        "software_pin_count": len(SOFTWARE),
        "source_map_sha256_matches": False,
        "r3_backup_fresh_before_call": False,
        "fixed_parent_ancestry_verified": False,
        "cu_source_code_globals_verified": False,
        "cli_source_code_globals_verified": False,
        "reader_source_code_globals_verified": False,
        "private_helper_source_code_globals_verified": False,
        "metadata_helper_invoked": False,
        "metadata_helper_invocations": 0,
        "metadata_backup_created": False,
        "metadata_source_map_updated": False,
        "metadata_deployment_updated": False,
        "metadata_readback_verified": False,
        "metadata_handles_released": False,
        "metadata_rebound": False,
        "metadata_write_or_close_uncertain": False,
        "fresh_source_admission_returned": False,
        "fresh_source_admission_map_matches": False,
        "fresh_source_admission_released": False,
        "retained_metadata_contexts": None,
        "retained_admissions": None,
        "consumed_admissions": None,
        "orphaned_source_admissions": None,
        "reader_current_read_evidence": None,
        "reader_root_helper_contexts": None,
        "orphaned_runtime_handle_sets": None,
        "current_type_issued": None,
        "current_type_consumed": None,
        "retained_registry_bindings_intact": False,
        "all_retained_contexts_empty": False,
        "outer_normal_postverify_and_close": False,
        "credentials_read": False,
        "provider_call": False,
        "account_call": False,
        "c01_helper_invoked": False,
        "websocket_started": False,
        "formal_m01_pass_count": 0,
        "host_exit_permitted": False,
    }


def _record_helper_state(result, state):
    if type(state) is not dict:
        return
    mapping = {
        "backup_created": "metadata_backup_created",
        "source_map_updated": "metadata_source_map_updated",
        "deployment_updated": "metadata_deployment_updated",
        "readback_verified": "metadata_readback_verified",
        "handles_released": "metadata_handles_released",
    }
    for source, target in mapping.items():
        result[target] = state.get(source) is True


def run():
    result = _initial_result()
    if (
        sys.version_info[:3] != (3, 11, 5)
        or not sys.flags.isolated
        or not sys.flags.no_site
        or not sys.dont_write_bytecode
        or not sys.flags.interactive
        or sys.argv[1:]
    ):
        raise RootCallError("public_input_invalid")

    if os.path.lexists(OUT):
        raise RootCallError("public_input_invalid")
    _verify_directory_chain(OUT.parent, ROOT)
    OUT.mkdir(exist_ok=False)
    ROOT_STATE["output_owned"] = True

    own_path = _verify_repo_path(Path(__file__))
    own_relative = own_path.relative_to(ROOT).as_posix()
    own_raw = _read_regular(own_path, maximum=PUBLIC_SOURCE_MAX_BYTES)
    own_sha = sha(own_raw)

    map_raw = public_bytes(MAP_RELATIVE, MAP_SIZE, MAP_SHA256)
    map_doc = _source_map_doc(map_raw)
    pins = dict(map_doc["source_pins"])
    for relative, (size, digest) in SUPPORT_PINS.items():
        raw = public_bytes(relative, size, digest)
        pins[relative] = digest
        if relative == CANDIDATE_PINS:
            candidate = json.loads(raw.decode("utf-8", errors="strict"))
            rows = {row["path"]: (row["bytes"], row["sha256"]) for row in candidate["candidate_files"]}
            if rows.get(HELPER) != (HELPER_SIZE, HELPER_SHA256) or rows.get(HELPER_TEST) != (
                HELPER_TEST_SIZE,
                HELPER_TEST_SHA256,
            ):
                raise RootCallError("public_input_invalid")
        if relative == STATIC_REVIEW and b"GO_REQUIRE_BINDING_FIX_STATIC_ONLY" not in raw:
            raise RootCallError("public_input_invalid")
        if relative == ROOT_QA_RESULT:
            qa = json.loads(raw.decode("utf-8", errors="strict"))
            if not (
                qa.get("status") == "SOURCE_FAKE_COMPONENT_ONLY"
                and qa.get("pytest_exit") == 0
                and qa.get("passed") == 11
                and qa.get("guard_selfchecks") == 4
                and qa.get("candidate_blocked_categories") == []
                and qa.get("inputs_unchanged") is True
                and qa.get("live_function_bindings_preserved") is True
            ):
                raise RootCallError("public_input_invalid")
    pins[own_relative] = own_sha
    result["public_pin_count"] = len(pins)
    result["source_map_sha256_matches"] = sha(map_raw) == MAP_SHA256

    # The two signed binaries use their own cap; the 5,991,424-byte DLL is
    # intentionally outside the 2 MiB public-source reader.
    software_binary_bytes(
        Path("C:/anaconda3/python.exe"), SOFTWARE["C:/anaconda3/python.exe"]
    )
    software_binary_bytes(
        Path("C:/anaconda3/python311.dll"),
        SOFTWARE["C:/anaconda3/python311.dll"],
        expected_size=PYTHON_DLL_EXPECTED_BYTES,
    )
    cu_raw = _read_regular(CU, maximum=PUBLIC_SOURCE_MAX_BYTES, expected_sha256=CU_SHA256)

    backup_parent = R3_BACKUP.parent
    if os.path.lexists(R3_BACKUP):
        raise RootCallError("public_input_invalid")
    _verify_directory_chain(backup_parent, Path("D:/"))
    result["r3_backup_fresh_before_call"] = True
    result["fixed_parent_ancestry_verified"] = True

    cu = load_held(cu_raw, CU, "_root_public_custody_v2")
    cu_binding = bind_module(cu, cu_raw, CU, "_root_public_custody_v2")
    ROOT_STATE.update(cu=cu, bindings=(cu_binding,))
    result["cu_source_code_globals_verified"] = True
    sys.addaudithook(_audit)
    bindings = [cu_binding]
    private_api_bindings = []
    try:
        verify_binding(cu_binding)
        scope = cu.held_public_sources(pins, SOFTWARE)
        ROOT_STATE["scope"] = scope
        held = scope.__enter__()
        ROOT_STATE["held"] = held
        private, cli, raw = held
        ROOT_STATE.update(private=private, cli_module=cli, raw=raw)
        if (
            type(raw) is not dict
            or type(private) is not types.ModuleType
            or type(cli) is not types.ModuleType
        ):
            raise RootCallError("root_scope_acquire_failed")
        for relative, digest in pins.items():
            key = str(ROOT / Path(relative))
            value = raw.get(key)
            if (
                type(value) is not bytes
                or len(value) > PUBLIC_SOURCE_MAX_BYTES
                or sha(value) != digest
            ):
                raise RootCallError("root_scope_acquire_failed")
        if raw.get(str(CU)) != cu_raw:
            raise RootCallError("root_scope_acquire_failed")
        for software_path, digest in SOFTWARE.items():
            value = raw.get(str(Path(software_path)))
            cap = PUBLIC_SOURCE_MAX_BYTES if software_path == str(CU) else SOFTWARE_BINARY_MAX_BYTES
            if type(value) is not bytes or len(value) > cap or sha(value) != digest:
                raise RootCallError("root_scope_acquire_failed")
            if software_path.endswith("python311.dll") and len(value) != PYTHON_DLL_EXPECTED_BYTES:
                raise RootCallError("root_scope_acquire_failed")
        for relative, (size, digest) in CURRENT_REVIEWED_SOURCES.items():
            value = raw.get(str(ROOT / relative))
            if (
                map_doc["source_pins"].get(relative) != digest
                or type(value) is not bytes
                or len(value) != size
            ):
                raise RootCallError("root_scope_acquire_failed")
        loaded_names = (
            "_m01_readonly_monitor_v2",
            "_m01_readonly_monitor_v2.current_types",
            "_m01_readonly_monitor_v2.worker",
            "_m01_readonly_monitor_v2.job_supervisor",
            "_certification",
            "_certification.m01_private_monitor_v2",
            "_m01_readonly_monitor_v3",
            "_m01_readonly_monitor_v3.current_reader",
            "_root_okx_m01_metadata_helper_r2",
        )
        if any(name in sys.modules for name in loaded_names):
            raise RootCallError("root_source_binding_failed")

        v2_package_relative = (
            "examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v2/__init__.py"
        )
        v2_package = load_held(
            raw[str(ROOT / v2_package_relative)],
            ROOT / v2_package_relative,
            "_m01_readonly_monitor_v2",
            is_package=True,
        )
        current_types = load_held(
            raw[str(ROOT / CURRENT_TYPES_RELATIVE)],
            ROOT / CURRENT_TYPES_RELATIVE,
            "_m01_readonly_monitor_v2.current_types",
        )
        v2_package.current_types = current_types
        worker = load_held(
            raw[str(ROOT / WORKER_RELATIVE)],
            ROOT / WORKER_RELATIVE,
            "_m01_readonly_monitor_v2.worker",
        )
        v2_package.worker = worker

        certification_package_relative = (
            "examples/000_live_certification/okx_penetration/_certification/__init__.py"
        )
        contract_relative = (
            "examples/000_live_certification/okx_penetration/_certification/m01_private_monitor_v2.py"
        )
        certification_package = load_held(
            raw[str(ROOT / certification_package_relative)],
            ROOT / certification_package_relative,
            "_certification",
            is_package=True,
        )
        contract = load_held(
            raw[str(ROOT / contract_relative)],
            ROOT / contract_relative,
            "_certification.m01_private_monitor_v2",
        )
        certification_package.m01_private_monitor_v2 = contract
        supervisor = load_held(
            raw[str(ROOT / SUPERVISOR_RELATIVE)],
            ROOT / SUPERVISOR_RELATIVE,
            "_m01_readonly_monitor_v2.job_supervisor",
        )
        v2_package.job_supervisor = supervisor

        v3_package = load_held(
            raw[str(ROOT / READER_PACKAGE_RELATIVE)],
            ROOT / READER_PACKAGE_RELATIVE,
            "_m01_readonly_monitor_v3",
            is_package=True,
        )
        reader = load_held(
            raw[str(ROOT / READER_RELATIVE)],
            ROOT / READER_RELATIVE,
            "_m01_readonly_monitor_v3.current_reader",
        )
        v3_package.current_reader = reader
        helper = load_held(
            raw[str(ROOT / HELPER)],
            ROOT / HELPER,
            "_root_okx_m01_metadata_helper_r2",
        )
        ROOT_STATE.update(
            reader=reader,
            helper=helper,
            modules=(
                v2_package,
                current_types,
                worker,
                certification_package,
                contract,
                supervisor,
                v3_package,
                reader,
                helper,
                private,
                cli,
            ),
        )
        if not (
            reader.current_types is current_types
            and reader.worker is worker
            and reader.job_supervisor is supervisor
            and supervisor.worker is worker
            and supervisor.current_types is current_types
            and supervisor.contract is contract
        ):
            raise RootCallError("root_source_binding_failed")

        modules = (
            (v2_package, v2_package_relative, "_m01_readonly_monitor_v2"),
            (current_types, CURRENT_TYPES_RELATIVE, "_m01_readonly_monitor_v2.current_types"),
            (worker, WORKER_RELATIVE, "_m01_readonly_monitor_v2.worker"),
            (certification_package, certification_package_relative, "_certification"),
            (contract, contract_relative, "_certification.m01_private_monitor_v2"),
            (supervisor, SUPERVISOR_RELATIVE, "_m01_readonly_monitor_v2.job_supervisor"),
            (v3_package, READER_PACKAGE_RELATIVE, "_m01_readonly_monitor_v3"),
            (reader, READER_RELATIVE, "_m01_readonly_monitor_v3.current_reader"),
            (helper, HELPER, "_root_okx_m01_metadata_helper_r2"),
            (private, PRIVATE_RELATIVE, "_root_public_custody_private"),
            (cli, CLI_RELATIVE, "_root_public_custody_cli"),
            (cu, str(CU), "_root_public_custody_v2"),
        )
        for module, relative, expected_name in modules:
            source_raw = cu_raw if relative == str(CU) else raw[str(ROOT / relative)]
            source_path = Path(relative) if relative == str(CU) else ROOT / relative
            binding = bind_module(module, source_raw, source_path, expected_name)
            bindings.append(binding)
            ROOT_STATE["bindings"] = tuple(bindings)
        result["reader_source_code_globals_verified"] = True
        result["private_helper_source_code_globals_verified"] = True
        result["cli_source_code_globals_verified"] = True
        ROOT_STATE["bindings_complete"] = True
        private_api_bindings.append(_verify_private_api(private))
        registry_counts, registries_intact, registries_empty = _capture_registries(reader, helper)
        ROOT_STATE["registry_snapshot_complete"] = True
        result.update(registry_counts)
        result["retained_registry_bindings_intact"] = registries_intact
        if not registries_empty:
            raise RootCallError("source_cleanup_uncertain")
        if not (
            helper.REVIEW_REF == TARGET_REVIEW_REF
            and reader.SOURCE_REVIEW_REF == TARGET_REVIEW_REF
            and helper.OLD_SOURCE_MAP_SHA256 == OLD_MAP_SHA256
            and helper.R2_SOURCE_MAP_SHA256 == MAP_SHA256
            and helper.R2_SOURCE_MAP_SIZE == MAP_SIZE
            and helper.BACKUP_CHILD == R3_BACKUP_CHILD
            and helper._DEPLOYMENT == DEPLOYMENT
            and helper.CURRENT_REVIEW_SHA256 == REVIEW_SHA256
            and helper.CURRENT_REVIEW_SIZE == REVIEW_SIZE
            and helper.CURRENT_REVIEW_TEST_SHA256 == REVIEW_TEST_SHA256
            and helper.CURRENT_REVIEW_TEST_SIZE == REVIEW_TEST_SIZE
            and helper.CURRENT_REVIEW_RELATIVE == CURRENT_REVIEW_RELATIVE
            and helper.CURRENT_REVIEW_TEST_RELATIVE == CURRENT_REVIEW_TEST_RELATIVE
            and reader.DEPLOYMENT_DIRECTORY == DEPLOYMENT
            and reader.ADMISSION_FILE == DEPLOYMENT / "deployment.json"
            and reader.SOURCE_MAP_FILE == DEPLOYMENT / "source-map.json"
            and reader.SOURCE_MAP_RELATIVES == frozenset(SOURCE_MAP_EXPECTED_PATHS)
        ):
            raise RootCallError("root_source_binding_failed")

        for binding in bindings:
            verify_binding(binding)
        _verify_private_api_bindings(private_api_bindings)
        result["metadata_helper_invoked"] = True
        result["metadata_helper_invocations"] = 1
        rebound = helper.rebind_fixed_deployment(
            held_source_map_raw=raw[str(ROOT / MAP_RELATIVE)],
            source_review_ref=TARGET_REVIEW_REF,
            held_current_review_raw=raw[str(ROOT / CURRENT_REVIEW_RELATIVE)],
            held_current_review_test_raw=raw[str(ROOT / CURRENT_REVIEW_TEST_RELATIVE)],
            reader_module=reader,
            private_module=private,
        )
        _record_helper_state(result, rebound)
        if rebound.get("status") != "REBOUND" or any(
            rebound.get(key) is not True for key in helper._STATE_KEYS
        ):
            raise RootCallError("metadata_helper_failed")
        result["metadata_rebound"] = True

        for binding in bindings:
            verify_binding(binding)
        _verify_private_api_bindings(private_api_bindings)
        token = reader.admit_source()
        ROOT_STATE["admission"] = token
        if type(token) is not reader.SourceAdmission:
            raise RootCallError("fresh_source_admission_failed")
        result["fresh_source_admission_returned"] = True
        result["fresh_source_admission_map_matches"] = (
            token.source_map_sha256 == TARGET_MAP_SHA256
        )
        if not result["fresh_source_admission_map_matches"]:
            raise RootCallError("fresh_source_admission_failed")
        admission_private = bind_module(
            token.private_module,
            raw[str(ROOT / PRIVATE_RELATIVE)],
            ROOT / PRIVATE_RELATIVE,
            "_okx_m01_v3_admission_private",
        )
        ROOT_STATE["admission_private_binding"] = admission_private
        bindings.append(admission_private)
        ROOT_STATE["bindings"] = tuple(bindings)
        private_api_bindings.append(_verify_private_api(token.private_module))
        for binding in bindings:
            verify_binding(binding)
        _verify_private_api_bindings(private_api_bindings)
        reader.release_admission(token)
        if not token.leases._closed or token.leases.files:
            raise RootCallError("source_admission_release_failed")
        ROOT_STATE["admission"] = None
        result["fresh_source_admission_released"] = True
    except BaseException as error:
        result["reason"] = _safe_reason(error)
        if result["metadata_helper_invoked"]:
            _record_helper_state(result, getattr(error, "state", None))
            result["metadata_write_or_close_uncertain"] = (
                result["metadata_source_map_updated"]
                or result["metadata_deployment_updated"]
                or not result["metadata_handles_released"]
            ) and not result["metadata_rebound"]

    reader = ROOT_STATE["reader"]
    helper = ROOT_STATE["helper"]
    if reader is not None and helper is not None:
        try:
            counts, registries_intact, registries_empty = _registry_counts(reader, helper)
            result.update(counts)
            result["retained_registry_bindings_intact"] = registries_intact
        except BaseException:
            result["retained_registry_bindings_intact"] = False
            registries_empty = False
        admission_clear = ROOT_STATE["admission"] is None
        registry_snapshot_complete = ROOT_STATE["registry_snapshot_complete"]
        result["all_retained_contexts_empty"] = (
            registries_empty and admission_clear and registry_snapshot_complete
        )
        clean = (
            registries_empty
            and admission_clear
            and not result["metadata_write_or_close_uncertain"]
            and ROOT_STATE["bindings_complete"]
            and registry_snapshot_complete
        )
    else:
        clean = False

    if clean and ROOT_STATE["held"] is not None:
        try:
            for binding in bindings:
                verify_binding(binding)
            _verify_private_api_bindings(private_api_bindings)
            ROOT_STATE["scope"].__exit__(None, None, None)
            result["outer_normal_postverify_and_close"] = True
            ROOT_STATE.update(scope=None, held=None)
        except BaseException as error:
            result["reason"] = _safe_reason(error)
            clean = False
    result["host_exit_permitted"] = clean and result["outer_normal_postverify_and_close"]
    if (
        result["metadata_rebound"]
        and result["fresh_source_admission_released"]
        and result["host_exit_permitted"]
    ):
        result["status"] = "METADATA_REBOUND_SOURCE_ADMISSION_RELEASED"
        result["reason"] = None
    return result


def _emit_result(result):
    payload = (json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")
    if ROOT_STATE["output_owned"]:
        try:
            result_path = OUT / "observation.json"
            with result_path.open("xb") as stream:
                stream.write(payload)
        except BaseException:
            pass
    print(json.dumps(result, sort_keys=True, separators=(",", ":")), flush=True)


ROOT_RESULT = None
try:
    ROOT_RESULT = run()
except BaseException as error:
    ROOT_RESULT = _initial_result()
    ROOT_RESULT["reason"] = _safe_reason(error)
_emit_result(ROOT_RESULT)
if not ROOT_RESULT.get("host_exit_permitted") and ROOT_STATE["scope"] is not None:
    print("ROOT_METADATA_CONTEXT_RETAINED", flush=True)
