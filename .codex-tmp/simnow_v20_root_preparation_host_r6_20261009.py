"""Prepare Root's exact same-process V20 credential-free gate host.

This module is inert when imported. Root must call
``prepare_root_gate_host(cuv2_source_bytes)`` with bytes obtained and verified
by its protected CUv2 source read. This module never reads the CUv2 path,
software payload paths, private inputs, environment values, SDK/native origins,
or network resources. The returned host retains the precheck handle, entered
lease, loaded source modules and caller in-process. Root explicitly calls
``host.invoke_once()`` only after its review gate.

Importing the 26 source modules uses only byte objects yielded by the entered
lease. It installs inert package shells and never executes package
``__init__.py`` files. A partial or uncertain CUv2 entry remains retained by
the fixed R3 driver's own keepalive.
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.machinery
import os
from pathlib import Path, PurePosixPath
import sys
from types import FunctionType, MappingProxyType, ModuleType
from typing import Any


SCHEMA = "iteration41-simnow-c01-v20-root-gate-host-preparation-r6"
REPOSITORY_ROOT = Path(r"D:\source_code\backtrader")
PRECHECK_RELATIVE = (
    "docs/_internal/opts/requirements/"
    "迭代41-实盘执行风控监控与示例架构重构/evidence/"
    "iteration41-simnow-c01-v20-root-public-precheck-r2-bounded-2026-10-09/"
    "prepare_root_precheck.py"
)
PRECHECK_BYTES = 27892
PRECHECK_SHA256 = "3f14a1ae6033717a8d05a90d7bade9ca0c96c6f7cfbea22c9f3176397fe066f6"
PRECHECK_MODULE_NAME = "_c01_v20_root_public_precheck_r2"
CALLER_RELATIVE = (
    "docs/_internal/opts/requirements/"
    "迭代41-实盘执行风控监控与示例架构重构/evidence/"
    "iteration41-simnow-c01-v20-root-credential-free-caller-r2-bounded-precheck-2026-10-09/"
    "run_root_credential_free_gate.py"
)
CALLER_BYTES = 16708
CALLER_SHA256 = "00c1485a89d91ade093ee353cf1dfd709026f83bcb8c1c4342161b5d22b4e5a4"
CALLER_MODULE_NAME = "_c01_v20_root_credential_free_caller_r2"
DRIVER_RELATIVE = "scripts/iteration41_simnow_c01_v20_root_actual_driver_r3.py"
DRIVER_MODULE_NAME = "_c01_v20_root_actual_driver"
CUV2_SOURCE_PATH = "D:/temp/iteration41-root-public-custody-v2.py"
CUV2_SOURCE_BYTES = 2344
CUV2_SOURCE_SHA256 = "e856be8e4056835d4a7e54f5c6b449c69ab3f1c2ebb049bcbcc1c95a9ad3f246"
MAX_PUBLIC_SOURCE_BYTES = 2 * 1024 * 1024
_ROOT_HOST_FACTORY = object()
_ROOT_HOSTS: list["PreparedRootGateHost"] = []

_LOAD_DEPENDENCIES = {
    "backtrader_runtime/certification_simnow_c01_v3_contract.py": (
        "backtrader_runtime/certification_simnow_c01_v3_protocol.py",
    ),
    "backtrader_runtime/certification_simnow_c01_v4_supervisor.py": (
        "backtrader_runtime/certification_simnow_c01_v3_protocol.py",
        "backtrader_runtime/certification_simnow_c01_interpreter_binding_v1.py",
    ),
    "scripts/ctp_i13_i15_windows_job_backend.py": (
        "scripts/ctp_i13_i15_outer_watchdog.py",
    ),
}


class RootPreparationError(ValueError):
    """Fixed safe preparation failure; never includes path or input values."""

    def __init__(self, code: str) -> None:
        safe = code if type(code) is str and code.isascii() else "root_preparation_blocked"
        super().__init__(safe)
        self.code = safe


class PreparedRootGateHost:
    """One-use same-process caller handle retaining all source and lease state."""

    __slots__ = (
        "precheck_module",
        "prepared_precheck",
        "caller_module",
        "driver_module",
        "driver_objects",
        "cuv2_module",
        "cuv2_source_bytes",
        "lease",
        "source_modules",
        "source_objects",
        "source_bytes",
        "_invoke",
        "_invoke_code",
        "_invoke_globals",
        "_precheck_function_codes",
        "_used",
        "_result",
    )

    def __init__(self, *, _factory: Any = None, **values: Any) -> None:
        if _factory is not _ROOT_HOST_FACTORY:
            raise RootPreparationError("root_gate_host_factory_required")
        for name in self.__slots__:
            if name in values:
                object.__setattr__(self, name, values[name])
        object.__setattr__(self, "_used", False)
        object.__setattr__(self, "_result", None)

    def invoke_once(self) -> dict[str, Any]:
        """Invoke exactly one gate call; preserve the host and original errors."""

        if self._used is not False:
            raise RootPreparationError("root_gate_host_already_used")
        precheck = self.precheck_module.__dict__
        caller = self.caller_module
        function = caller.__dict__.get("invoke_root_credential_free_gate")
        if (
            type(function) is not FunctionType
            or function.__globals__ is not caller.__dict__
            or function.__code__.co_filename != caller.__dict__.get("__file__")
            or caller.__dict__.get("__c01_source_sha256__") != CALLER_SHA256
            or caller.__dict__.get("__c01_source_bytes__") != CALLER_BYTES
            or function is not self._invoke
            or function.__code__ is not self._invoke_code
            or function.__globals__ is not self._invoke_globals
            or any(
                type(precheck.get(name)) is not FunctionType
                or precheck[name].__code__ is not self._precheck_function_codes[name]
                or precheck[name].__globals__ is not precheck
                for name in self._precheck_function_codes
            )
            or self.lease is None
        ):
            raise RootPreparationError("root_gate_caller_binding_invalid")
        object.__setattr__(self, "_used", True)
        result = function(precheck, self.prepared_precheck, self.lease)
        if type(result) is not dict:
            raise RootPreparationError("root_gate_result_shape_invalid")
        object.__setattr__(self, "_result", result)
        return dict(result)

    def public_summary(self) -> dict[str, Any]:
        prepared = self.prepared_precheck
        return {
            "schema": SCHEMA,
            "status": "ROOT_GATE_HOST_INVOKED" if self._used else "ROOT_GATE_HOST_PREPARED",
            "precheck_verified": True,
            "public_source_count": len(prepared.public_source_pins),
            "software_pin_metadata_count": len(prepared.software_source_pins),
            "cuv2_entered": self.lease is not None,
            "gate_invoked": self._used,
            "formal_c01_pass": False,
            "official_c01_pass_count": 0,
        }

    def __repr__(self) -> str:
        return "PreparedRootGateHost(<source objects, bytes, CUv2 lease and gate result redacted>)"


def _fixed_bounded_read(root: Path, relative: str, byte_limit: int, expected_sha256: str) -> bytes:
    pure = PurePosixPath(relative)
    if (
        type(byte_limit) is not int
        or byte_limit <= 0
        or byte_limit > MAX_PUBLIC_SOURCE_BYTES
        or pure.is_absolute()
        or ".." in pure.parts
        or pure.as_posix() != relative
    ):
        raise RootPreparationError("fixed_source_contract_invalid")
    base = root.resolve(strict=True)
    path = base.joinpath(*pure.parts).resolve(strict=True)
    try:
        path.relative_to(base)
    except ValueError:
        raise RootPreparationError("fixed_source_path_escape") from None
    if not path.is_file():
        raise RootPreparationError("fixed_source_missing")
    try:
        with path.open("rb") as stream:
            raw = stream.read(byte_limit + 1)
    except OSError:
        raise RootPreparationError("fixed_source_read_failed") from None
    if type(raw) is not bytes or len(raw) != byte_limit:
        raise RootPreparationError("fixed_source_size_mismatch")
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise RootPreparationError("fixed_source_pin_mismatch")
    return raw


def _load_exact_component(
    raw: bytes, *, root: Path, relative: str, module_name: str, expected_sha256: str
) -> ModuleType:
    if type(raw) is not bytes or hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise RootPreparationError("component_pin_mismatch")
    path = root.joinpath(*PurePosixPath(relative).parts).resolve(strict=True)
    module = ModuleType(module_name)
    module.__file__ = str(path)
    module.__package__ = module_name.rpartition(".")[0]
    module.__loader__ = None
    module.__spec__ = importlib.machinery.ModuleSpec(module_name, loader=None, origin=str(path))
    module.__c01_source_sha256__ = expected_sha256
    module.__c01_source_bytes__ = len(raw)
    try:
        exec(compile(raw, str(path), "exec", dont_inherit=True), module.__dict__)
    except Exception:
        raise RootPreparationError("component_compile_failed") from None
    return module


def _load_precheck(root: Path) -> tuple[ModuleType, Any]:
    raw = _fixed_bounded_read(root, PRECHECK_RELATIVE, PRECHECK_BYTES, PRECHECK_SHA256)
    module = _load_exact_component(
        raw,
        root=root,
        relative=PRECHECK_RELATIVE,
        module_name=PRECHECK_MODULE_NAME,
        expected_sha256=PRECHECK_SHA256,
    )
    if module.__dict__.get("SCHEMA") != "iteration41-simnow-c01-v20-root-public-precheck-v2":
        raise RootPreparationError("precheck_schema_invalid")
    prepare = module.__dict__.get("prepare_root_public_precheck")
    validate = module.__dict__.get("validate_prepared_root_precheck")
    if (
        type(prepare) is not FunctionType
        or prepare.__globals__ is not module.__dict__
        or prepare.__code__.co_filename != module.__file__
        or type(validate) is not FunctionType
        or validate.__globals__ is not module.__dict__
        or validate.__code__.co_filename != module.__file__
    ):
        raise RootPreparationError("precheck_function_binding_invalid")
    try:
        prepared = prepare()
    except Exception:
        raise RootPreparationError("precheck_prepare_failed") from None
    if type(prepared) is not module.__dict__.get("PreparedRootPrecheck") or validate(prepared) is not True:
        raise RootPreparationError("precheck_result_invalid")
    return module, prepared


def _load_caller(root: Path) -> ModuleType:
    raw = _fixed_bounded_read(root, CALLER_RELATIVE, CALLER_BYTES, CALLER_SHA256)
    return _load_exact_component(
        raw,
        root=root,
        relative=CALLER_RELATIVE,
        module_name=CALLER_MODULE_NAME,
        expected_sha256=CALLER_SHA256,
    )


def _module_name_for(relative: str, driver_path: str) -> str:
    if relative == driver_path:
        return DRIVER_MODULE_NAME
    pure = PurePosixPath(relative)
    if not relative.endswith(".py") or pure.is_absolute() or ".." in pure.parts:
        raise RootPreparationError("public_module_path_invalid")
    return pure.as_posix()[:-3].replace("/", ".")


def _package_names(module_name: str) -> tuple[str, ...]:
    parts = module_name.split(".")
    if len(parts) < 2:
        return ()
    return tuple(".".join(parts[:index]) for index in range(1, len(parts)))


def _make_package_shell(name: str) -> ModuleType:
    package = ModuleType(name)
    package.__package__ = name
    package.__path__ = []
    package.__loader__ = None
    package.__spec__ = importlib.machinery.ModuleSpec(
        name, loader=None, origin=None, is_package=True
    )
    return package


def _ordered_paths(paths: tuple[str, ...]) -> tuple[str, ...]:
    remaining = list(paths)
    result: list[str] = []
    done: set[str] = set()
    while remaining:
        progressed = False
        for path in tuple(remaining):
            dependencies = _LOAD_DEPENDENCIES.get(path, ())
            if not set(dependencies).issubset(done):
                continue
            result.append(path)
            done.add(path)
            remaining.remove(path)
            progressed = True
        if not progressed:
            raise RootPreparationError("fixed_module_dependency_cycle")
    return tuple(result)


def _preflight_aliases(paths: tuple[str, ...]) -> tuple[tuple[str, ...], dict[str, str]]:
    names = {path: _module_name_for(path, DRIVER_RELATIVE) for path in paths}
    packages = sorted({package for name in names.values() for package in _package_names(name)})
    aliases = set(packages) | set(names.values())
    if aliases.intersection(sys.modules):
        raise RootPreparationError("fixed_module_alias_already_loaded")
    return tuple(packages), names


def _contextmanager_wrapper_matches(wrapper: Any, generator: Any) -> bool:
    """Bind a standard contextmanager wrapper to its exact generator function.

    ``contextlib.contextmanager`` returns a FunctionType whose globals are
    ``contextlib.__dict__``; the wrapped generator retains the CUv2 module's
    globals.  Reconstructing the canonical wrapper lets both the loader and
    Root's later postcheck compare wrapper code/globals and closure contents
    without treating those two legitimate global namespaces as one.
    """

    if (
        type(wrapper) is not FunctionType
        or type(generator) is not FunctionType
        or getattr(wrapper, "__wrapped__", None) is not generator
        or type(contextlib.contextmanager) is not FunctionType
        or contextlib.contextmanager.__globals__ is not contextlib.__dict__
        or contextlib.contextmanager.__module__ != "contextlib"
        or contextlib.contextmanager.__name__ != "contextmanager"
    ):
        return False
    try:
        expected = contextlib.contextmanager(generator)
        wrapper_closure = tuple(
            cell.cell_contents for cell in (wrapper.__closure__ or ())
        )
        expected_closure = tuple(
            cell.cell_contents for cell in (expected.__closure__ or ())
        )
    except Exception:
        return False
    return (
        wrapper.__code__ is expected.__code__
        and wrapper.__globals__ is expected.__globals__
        and wrapper.__globals__ is contextlib.__dict__
        and tuple(map(id, wrapper_closure)) == tuple(map(id, expected_closure))
    )


def _cu_v2_module(raw: bytes, driver_module: ModuleType) -> ModuleType:
    if (
        type(raw) is not bytes
        or len(raw) != CUV2_SOURCE_BYTES
        or hashlib.sha256(raw).hexdigest() != CUV2_SOURCE_SHA256
    ):
        raise RootPreparationError("cuv2_source_pin_invalid")
    module_name = "_root_public_custody_cli"
    if module_name in sys.modules:
        raise RootPreparationError("cuv2_module_alias_already_loaded")
    module = ModuleType(module_name)
    module.__file__ = CUV2_SOURCE_PATH
    module.__package__ = ""
    module.__loader__ = None
    module.__spec__ = importlib.machinery.ModuleSpec(
        module_name, loader=None, origin=CUV2_SOURCE_PATH
    )
    module.__c01_source_sha256__ = CUV2_SOURCE_SHA256
    module.__c01_source_bytes__ = CUV2_SOURCE_BYTES
    sys.modules[module_name] = module
    try:
        exec(compile(raw, CUV2_SOURCE_PATH, "exec", dont_inherit=True), module.__dict__)
    except Exception:
        raise RootPreparationError("cuv2_source_compile_failed") from None
    held = module.__dict__.get("held_public_sources")
    generator = getattr(held, "__wrapped__", None)
    driver_objects = driver_module.__dict__.get("capture_c01_v20_driver_objects")
    if (
        type(held) is not FunctionType
        or type(generator) is not FunctionType
        or generator.__globals__ is not module.__dict__
        or generator.__code__.co_filename != CUV2_SOURCE_PATH
        or _contextmanager_wrapper_matches(held, generator) is not True
        or type(driver_objects) is not FunctionType
    ):
        raise RootPreparationError("cuv2_function_binding_invalid")
    return module


def _driver_function(prepared: Any, name: str) -> FunctionType:
    module = prepared.driver_module
    objects = prepared.driver_objects
    function = module.__dict__.get(name)
    if (
        type(function) is not FunctionType
        or function.__globals__ is not module.__dict__
        or objects.get(name) is not function
        or objects.get(name + ".__code__") is not function.__code__
        or objects.get(name + ".__globals__") is not module.__dict__
    ):
        raise RootPreparationError("driver_function_binding_invalid")
    return function


def _normalized_source_root(value: Any) -> str:
    """Match the pinned driver's Windows root normalization exactly."""

    if type(value) is not str or not value:
        raise RootPreparationError("entered_source_root_invalid")
    normalized = os.path.normcase(os.path.normpath(value))
    if not os.path.isabs(normalized):
        raise RootPreparationError("entered_source_root_invalid")
    return normalized


def _bind_public_modules(host: PreparedRootGateHost) -> None:
    prepared = host.prepared_precheck
    lease = host.lease
    driver = host.driver_module
    capture = _driver_function(prepared, "_capture_source_module_objects")
    absolute_path = _driver_function(prepared, "_absolute_public_path")
    bind = _driver_function(prepared, "bind_c01_v20_outer_source_modules")
    rows = tuple(prepared.public_source_pins)
    if len(rows) != 26 or set(rows) != set(prepared.public_source_bytes):
        raise RootPreparationError("public_source_map_invalid")
    package_names, module_names = _preflight_aliases(rows)
    expected_root = _normalized_source_root(str(REPOSITORY_ROOT.resolve(strict=True)))
    driver_root = _driver_function(prepared, "_source_root_for_driver")()
    if (
        _normalized_source_root(driver_root) != expected_root
        or _normalized_source_root(lease.source_root) != expected_root
    ):
        raise RootPreparationError("entered_source_root_mismatch")

    for name in package_names:
        package = _make_package_shell(name)
        sys.modules[name] = package
        host.source_modules[name] = package

    held_public: dict[str, bytes] = {}
    for path in rows:
        absolute = absolute_path(lease.source_root, path)
        raw = lease.held_raw_by_absolute_path.get(absolute)
        if (
            type(raw) is not bytes
            or len(raw) > MAX_PUBLIC_SOURCE_BYTES
            or hashlib.sha256(raw).hexdigest() != prepared.public_source_pins[path]
        ):
            raise RootPreparationError("held_public_source_pin_invalid")
        held_public[path] = raw

    ordered = _ordered_paths(rows)
    for relative in ordered:
        name = module_names[relative]
        raw = held_public[relative]
        if relative == DRIVER_RELATIVE:
            module = driver
            if name in sys.modules:
                raise RootPreparationError("fixed_driver_module_alias_changed")
            sys.modules[name] = module
        else:
            module = ModuleType(name)
            module.__file__ = str(
                REPOSITORY_ROOT.resolve(strict=True).joinpath(*PurePosixPath(relative).parts)
            )
            module.__package__ = name.rpartition(".")[0]
            module.__loader__ = None
            module.__spec__ = importlib.machinery.ModuleSpec(
                name, loader=None, origin=module.__file__
            )
            module.__c01_source_sha256__ = prepared.public_source_pins[relative]
            sys.modules[name] = module
            host.source_modules[name] = module
            try:
                exec(compile(raw, module.__file__, "exec", dont_inherit=True), module.__dict__)
            except Exception:
                raise RootPreparationError("held_source_module_compile_failed") from None
        if sys.modules.get(name) is not module:
            raise RootPreparationError("held_source_module_registration_changed")
        host.source_modules[relative] = module
        if relative == DRIVER_RELATIVE:
            object_map = prepared.driver_objects
        else:
            object_map = capture(module)
        host.source_objects[relative] = object_map
        host.source_bytes[relative] = raw

    module_map = {path: host.source_modules[path] for path in rows}
    object_map = {path: host.source_objects[path] for path in rows}
    bind(
        lease,
        source_modules=module_map,
        source_objects=object_map,
        source_pins=prepared.public_source_pins,
        held_source_bytes=host.source_bytes,
    )
    validate_entered = host.precheck_module.__dict__.get(
        "validate_precheck_against_entered_lease"
    )
    if (
        type(validate_entered) is not FunctionType
        or validate_entered.__globals__ is not host.precheck_module.__dict__
        or validate_entered(host.prepared_precheck, lease) is not True
    ):
        raise RootPreparationError("precheck_lease_binding_invalid")


def prepare_root_gate_host(cuv2_source_bytes: bytes) -> PreparedRootGateHost:
    """Prepare the one-use Root gate host from Root-verified CUv2 bytes.

    Root obtains ``cuv2_source_bytes`` with its protected, bounded reader and
    verifies the exact fixed software pin before calling this function. The
    argument is checked again here, compiled directly, and never read from a
    path. This function enters the real outer source lease; Root must invoke it
    only in the reviewed host after the separate software read is complete.
    It does not invoke the credential-free gate or C01 activation.
    """

    if (
        type(cuv2_source_bytes) is not bytes
        or len(cuv2_source_bytes) != CUV2_SOURCE_BYTES
        or hashlib.sha256(cuv2_source_bytes).hexdigest() != CUV2_SOURCE_SHA256
    ):
        raise RootPreparationError("cuv2_source_pin_invalid")
    if _ROOT_HOSTS:
        raise RootPreparationError("root_gate_host_already_prepared")
    root = REPOSITORY_ROOT.resolve(strict=True)
    precheck_module, prepared = _load_precheck(root)
    caller_module = _load_caller(root)
    _preflight_aliases(tuple(prepared.public_source_pins))
    driver = prepared.driver_module
    cuv2_module = _cu_v2_module(cuv2_source_bytes, driver)
    caller_function = caller_module.__dict__.get("invoke_root_credential_free_gate")
    if (
        type(caller_function) is not FunctionType
        or caller_function.__globals__ is not caller_module.__dict__
        or caller_function.__code__.co_filename != caller_module.__file__
    ):
        raise RootPreparationError("caller_function_binding_invalid")
    precheck_codes: dict[str, Any] = {}
    for name in (
        "prepare_root_public_precheck",
        "validate_prepared_root_precheck",
        "validate_precheck_against_entered_lease",
    ):
        function = precheck_module.__dict__.get(name)
        if (
            type(function) is not FunctionType
            or function.__globals__ is not precheck_module.__dict__
            or function.__code__.co_filename != precheck_module.__file__
        ):
            raise RootPreparationError("precheck_function_binding_invalid")
        precheck_codes[name] = function.__code__
    host = PreparedRootGateHost(
        _factory=_ROOT_HOST_FACTORY,
        precheck_module=precheck_module,
        prepared_precheck=prepared,
        caller_module=caller_module,
        driver_module=driver,
        driver_objects=prepared.driver_objects,
        cuv2_module=cuv2_module,
        cuv2_source_bytes=cuv2_source_bytes,
        lease=None,
        source_modules={},
        source_objects={},
        source_bytes={},
        _invoke=caller_function,
        _invoke_code=caller_function.__code__,
        _invoke_globals=caller_module.__dict__,
        _precheck_function_codes=MappingProxyType(precheck_codes),
    )
    _ROOT_HOSTS.append(host)
    enter = _driver_function(prepared, "enter_c01_v20_outer_source_lease")
    try:
        lease = enter(
            cuv2_module=cuv2_module,
            cuv2_source_bytes=cuv2_source_bytes,
            public_source_pins=prepared.public_source_pins,
            software_source_pins=prepared.software_source_pins,
        )
    except BaseException:
        # The fixed driver retains uncertain CUv2 entry state itself. Preserve
        # every module/byte object prepared by this host and propagate intact.
        raise
    object.__setattr__(host, "lease", lease)
    _bind_public_modules(host)
    return host


__all__ = [
    "PreparedRootGateHost",
    "RootPreparationError",
    "prepare_root_gate_host",
]
