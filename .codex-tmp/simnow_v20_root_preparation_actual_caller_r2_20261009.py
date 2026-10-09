"""Root-only caller for a still-held SimNow V20 preparation host.

Importing this module is inert. Root loads its exact pinned bytes into the
fresh module alias below, then calls ``prepare_once`` with the exact CUv2
source bytes returned by Root's protected bounded reader. This caller enters
the accepted source lease and returns its host; it never invokes the Gate or
activation and never closes, clears, or exits a retained scope.

Only fixed public Python sources are read here. The two interpreter payloads
are read only by the exact pinned CUv2 hold. This caller checks their path and
hash metadata without inspecting their bytes.
"""

from __future__ import annotations

import builtins
import hashlib
import importlib.machinery
from pathlib import Path, PurePosixPath
import sys
from types import FunctionType, MappingProxyType, ModuleType
from typing import Any


SCHEMA = "iteration41-simnow-c01-v20-root-preparation-actual-caller-r2"
ROOT_CALLER_MODULE_NAME = "_c01_simnow_v20_root_preparation_actual_caller_r2"
REPOSITORY_ROOT = Path(r"D:\source_code\backtrader")
MAX_PUBLIC_SOURCE_BYTES = 2 * 1024 * 1024

PREPARATION_RELATIVE = ".codex-tmp/simnow_v20_root_preparation_host_r6_20261009.py"
PREPARATION_BYTES = 24159
PREPARATION_SHA256 = "02ac13bfd45c6ad94e0c8666bca4e05182a727eaf2449a1b21cb6b7b72be581f"
PREPARATION_MODULE_NAME = "_c01_simnow_v20_root_preparation_payload_r2"

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
EXPECTED_PUBLIC_ROWS = 26

CUV2_SOURCE_PATH = "D:/temp/iteration41-root-public-custody-v2.py"
CUV2_SOURCE_BYTES = 2344
CUV2_SOURCE_SHA256 = "e856be8e4056835d4a7e54f5c6b449c69ab3f1c2ebb049bcbcc1c95a9ad3f246"
CUV2_MODULE_NAME = "_root_public_custody_cli"
EXPECTED_SOFTWARE_SOURCE_PINS = {
    CUV2_SOURCE_PATH: CUV2_SOURCE_SHA256,
    "C:/anaconda3/python.exe": (
        "c98caee82c66433f0e89d4abbf152b39a7dc2e99979b28dcb021598b4e3f5642"
    ),
    "C:/anaconda3/python311.dll": (
        "162e8557fbed5f39ae24983ee62b2d435b4796c937d9c1a34371888c7e43af00"
    ),
}

_FIXED_FRESH_ALIASES = (
    PREPARATION_MODULE_NAME,
    PRECHECK_MODULE_NAME,
    CALLER_MODULE_NAME,
    DRIVER_MODULE_NAME,
    CUV2_MODULE_NAME,
)
_FORBIDDEN_IMPORT_ROOTS = frozenset(
    {
        "backtrader",
        "bt_api_base",
        "bt_api_ctp",
        "bt_api_execution",
        "bt_api_py",
        "bt_api_monitor",
        "ctp",
        "ctpbeebt",
        "ctp_wrap",
        "ctpsdk",
        "thostmduserapi",
        "thosttraderapi",
        "vnpy",
        "vnpy_ctp",
        "xtquant",
    }
)


class RootPreparationCallerError(ValueError):
    """Fixed, non-sensitive error code for caller contract failures."""

    def __init__(self, code: str) -> None:
        safe = code if type(code) is str and code.isascii() else "root_preparation_blocked"
        super().__init__(safe)
        self.code = safe


class _ImportGuard:
    """Deny SDK/trading package imports while selected sources are bound."""

    __slots__ = ("original",)

    def __init__(self, original: Any) -> None:
        self.original = original

    def __call__(
        self,
        name: str,
        globals: Any = None,
        locals: Any = None,
        fromlist: Any = (),
        level: int = 0,
    ) -> Any:
        root = name.partition(".")[0].casefold() if type(name) is str else ""
        if root in _FORBIDDEN_IMPORT_ROOTS or root.startswith("bt_api_"):
            raise RootPreparationCallerError("forbidden_package_import_blocked")
        return self.original(name, globals, locals, fromlist, level)


class _Attempt:
    """One retained attempt with a finite public diagnostic projection."""

    __slots__ = (
        "phase",
        "status",
        "preparation_module",
        "host",
        "preparation_source_bytes",
        "preparation_functions",
        "host_list",
        "factory_token",
        "public_source_count",
        "software_pin_count",
        "cuv2_argument_verified",
        "import_guard_installed",
        "import_guard_restored",
        "postbinding_verified",
    )

    def __init__(self) -> None:
        self.phase = "caller_preflight"
        self.status = "STARTED"
        self.preparation_module = None
        self.host = None
        self.preparation_source_bytes = None
        self.preparation_functions = None
        self.host_list = None
        self.factory_token = None
        self.public_source_count = None
        self.software_pin_count = None
        self.cuv2_argument_verified = False
        self.import_guard_installed = False
        self.import_guard_restored = False
        self.postbinding_verified = False

    def public_summary(self) -> dict[str, Any]:
        prep = self.preparation_module
        hosts = prep.__dict__.get("_ROOT_HOSTS") if prep is not None else None
        retained = type(hosts) is list and bool(hosts)
        host = self.host or (hosts[-1] if retained else None)
        lease = getattr(host, "lease", None) if host is not None else None
        return {
            "schema": SCHEMA,
            "status": self.status,
            "phase": self.phase,
            "preparation_source_verified": self.preparation_source_bytes is not None,
            "cuv2_argument_verified": self.cuv2_argument_verified,
            "public_source_count": self.public_source_count,
            "software_pin_metadata_count": self.software_pin_count,
            "preparation_host_retained": retained,
            "outer_source_lease_entered": (
                None if lease is None else getattr(lease, "state", None) == "entered"
            ),
            "gate_invoked_by_caller": False,
            "gate_used_observed": None if host is None else getattr(host, "_used", None) is True,
            "activation_started_observed": (
                None
                if lease is None
                else getattr(lease, "activation_started", None) is True
                or getattr(lease, "supervisor_started", None) is True
            ),
            "import_guard_installed": self.import_guard_installed,
            "import_guard_restored": self.import_guard_restored,
            "postbinding_verified": self.postbinding_verified,
            "formal_c01_pass": False,
            "official_c01_pass_count": 0,
        }


_ATTEMPTS: list[_Attempt] = []


def _require(ok: bool, code: str) -> None:
    if ok is not True:
        raise RootPreparationCallerError(code)


def _forbidden_root(name: str) -> bool:
    root = name.partition(".")[0].casefold()
    return root in _FORBIDDEN_IMPORT_ROOTS or root.startswith("bt_api_")


def _bounded_public_read(relative: str, size: int, digest: str) -> tuple[Path, bytes]:
    pure = PurePosixPath(relative)
    _require(
        type(relative) is str and not pure.is_absolute() and ".." not in pure.parts,
        "fixed_public_path_invalid",
    )
    _require(type(size) is int and 0 < size <= MAX_PUBLIC_SOURCE_BYTES, "fixed_public_size_invalid")
    root = REPOSITORY_ROOT.resolve(strict=True)
    path = root.joinpath(*pure.parts).resolve(strict=True)
    try:
        path.relative_to(root)
    except ValueError:
        raise RootPreparationCallerError("fixed_public_path_escape") from None
    _require(path.is_file(), "fixed_public_file_invalid")
    try:
        with path.open("rb") as stream:
            raw = stream.read(size + 1)
    except OSError:
        raise RootPreparationCallerError("fixed_public_read_failed") from None
    _require(type(raw) is bytes and len(raw) == size, "fixed_public_size_mismatch")
    _require(hashlib.sha256(raw).hexdigest() == digest, "fixed_public_pin_mismatch")
    return path, raw


def _load_preparation(path: Path, raw: bytes) -> ModuleType:
    _require(PREPARATION_MODULE_NAME not in sys.modules, "preparation_alias_not_fresh")
    module = ModuleType(PREPARATION_MODULE_NAME)
    module.__file__ = str(path)
    module.__package__ = ""
    module.__loader__ = None
    module.__spec__ = importlib.machinery.ModuleSpec(
        PREPARATION_MODULE_NAME, loader=None, origin=str(path)
    )
    module.__c01_source_sha256__ = PREPARATION_SHA256
    module.__c01_source_bytes__ = PREPARATION_BYTES
    try:
        exec(compile(raw, str(path), "exec", dont_inherit=True), module.__dict__)
    except Exception:
        raise RootPreparationCallerError("preparation_component_load_failed") from None
    return module


def _function_snapshot(module: ModuleType) -> tuple[tuple[str, Any, Any, Any], ...]:
    return tuple(
        (name, value, value.__code__, value.__globals__)
        for name, value in sorted(module.__dict__.items())
        if type(value) is FunctionType
    )


def _require_function(module: ModuleType, name: str) -> FunctionType:
    function = module.__dict__.get(name)
    _require(
        type(function) is FunctionType
        and function.__globals__ is module.__dict__
        and function.__code__.co_filename == module.__file__,
        "source_function_binding_invalid",
    )
    return function


def _cuv2_postcheck_binding_valid(prep: ModuleType, cuv2: ModuleType, lease: Any) -> bool:
    """Recheck the canonical contextmanager wrapper and its CUv2 generator."""

    try:
        matcher = prep.__dict__.get("_contextmanager_wrapper_matches")
        held = cuv2.__dict__.get("held_public_sources")
        generator = getattr(held, "__wrapped__", None)
        return (
            type(matcher) is FunctionType
            and matcher.__globals__ is prep.__dict__
            and matcher.__code__.co_filename == prep.__file__
            and type(held) is FunctionType
            and type(generator) is FunctionType
            and generator.__globals__ is cuv2.__dict__
            and generator.__code__.co_filename == CUV2_SOURCE_PATH
            and matcher(held, generator) is True
            and lease.cuv2_function is held
            and lease.cuv2_function_code is held.__code__
            and lease.cuv2_function_globals is held.__globals__
            and lease.cuv2_generator_function is generator
            and lease.cuv2_generator_code is generator.__code__
            and lease.cuv2_generator_globals is cuv2.__dict__
            and lease.generator.gi_code is generator.__code__
            and lease.generator.gi_frame is not None
            and lease.generator.gi_frame.f_globals is cuv2.__dict__
        )
    except Exception:
        return False


def _postcheck(attempt: _Attempt, source_bytes: bytes) -> None:
    prep = attempt.preparation_module
    host = attempt.host
    _require(type(prep) is ModuleType and prep.__dict__ is vars(prep), "preparation_module_invalid")
    _require(
        prep.__dict__.get("__c01_source_sha256__") == PREPARATION_SHA256
        and prep.__dict__.get("__c01_source_bytes__") == PREPARATION_BYTES
        and prep.__dict__.get("__file__")
        == str(REPOSITORY_ROOT.resolve(strict=True).joinpath(*PurePosixPath(PREPARATION_RELATIVE).parts))
        and _function_snapshot(prep) == attempt.preparation_functions,
        "preparation_source_binding_changed",
    )
    _require(prep.__dict__.get("_ROOT_HOSTS") is attempt.host_list, "preparation_registry_changed")
    _require(prep.__dict__.get("_ROOT_HOST_FACTORY") is attempt.factory_token, "preparation_factory_changed")
    _require(type(host) is prep.__dict__.get("PreparedRootGateHost"), "prepared_host_type_invalid")
    _require(host._used is False and host._result is None, "gate_used_during_preparation")
    _require(host.cuv2_source_bytes is source_bytes, "cuv2_source_object_changed")
    _require(attempt.host_list == [host] and attempt.host_list[0] is host, "preparation_host_not_retained")

    precheck = host.precheck_module
    prepared = host.prepared_precheck
    precheck_codes = host._precheck_function_codes
    validate_entered = _require_function(precheck, "validate_precheck_against_entered_lease")
    _require(
        type(prepared) is precheck.__dict__.get("PreparedRootPrecheck")
        and precheck.__dict__.get("__name__") == PRECHECK_MODULE_NAME
        and precheck.__dict__.get("__c01_source_sha256__") == PRECHECK_SHA256
        and precheck.__dict__.get("__c01_source_bytes__") == PRECHECK_BYTES
        and precheck.__dict__.get("__file__")
        == str(REPOSITORY_ROOT.resolve(strict=True).joinpath(*PurePosixPath(PRECHECK_RELATIVE).parts))
        and type(precheck_codes) is MappingProxyType
        and set(precheck_codes)
        == {
            "prepare_root_public_precheck",
            "validate_prepared_root_precheck",
            "validate_precheck_against_entered_lease",
        }
        and all(
            type(precheck.__dict__.get(name)) is FunctionType
            and precheck.__dict__[name].__globals__ is precheck.__dict__
            and precheck.__dict__[name].__code__ is precheck_codes[name]
            for name in precheck_codes
        )
        and validate_entered(prepared, host.lease) is True,
        "entered_precheck_binding_invalid",
    )
    _require(
        dict(prepared.software_source_pins) == EXPECTED_SOFTWARE_SOURCE_PINS
        and type(prepared.software_source_pins) is MappingProxyType,
        "software_pin_metadata_invalid",
    )
    _require(
        type(prepared.public_source_pins) is MappingProxyType
        and type(prepared.public_source_bytes) is MappingProxyType
        and len(prepared.public_source_pins) == EXPECTED_PUBLIC_ROWS
        and set(prepared.public_source_pins) == set(prepared.public_source_bytes),
        "public_precheck_map_invalid",
    )

    caller = host.caller_module
    invoke = _require_function(caller, "invoke_root_credential_free_gate")
    _require(
        host._invoke is invoke
        and host._invoke_code is invoke.__code__
        and host._invoke_globals is caller.__dict__
        and caller.__name__ == CALLER_MODULE_NAME
        and caller.__dict__.get("__c01_source_bytes__") == CALLER_BYTES
        and caller.__dict__.get("__c01_source_sha256__") == CALLER_SHA256
        and caller.__dict__.get("__file__")
        == str(REPOSITORY_ROOT.resolve(strict=True).joinpath(*PurePosixPath(CALLER_RELATIVE).parts))
        and dict(caller.__dict__.get("EXPECTED_SOFTWARE_PINS", {}))
        == EXPECTED_SOFTWARE_SOURCE_PINS,
        "gate_caller_binding_invalid",
    )

    driver = host.driver_module
    objects = host.driver_objects
    lease = host.lease
    validate_driver = _require_function(driver, "validate_c01_v20_driver_source_objects")
    validate_modules = _require_function(driver, "_validate_source_module_snapshots")
    current_lease = _require_function(driver, "_outer_lease_current")
    _require(
        driver.__name__ == DRIVER_MODULE_NAME
        and driver.__dict__.get("__file__")
        == str(REPOSITORY_ROOT.resolve(strict=True).joinpath(*PurePosixPath(DRIVER_RELATIVE).parts))
        and driver.__dict__.get("__c01_source_sha256__")
        == prepared.public_source_pins.get(DRIVER_RELATIVE)
        and type(objects) is MappingProxyType
        and validate_driver(driver, objects) is True,
        "driver_source_binding_invalid",
    )
    _require(
        type(lease) is driver.__dict__.get("C01V20OuterSourceLease")
        and current_lease(lease, require_entered=True) is True
        and lease.state == "entered"
        and lease.exit_started is False,
        "outer_source_lease_invalid",
    )
    _require(
        lease.cuv2_module is host.cuv2_module
        and lease.cuv2_source_bytes is source_bytes
        and dict(lease.software_source_pins) == EXPECTED_SOFTWARE_SOURCE_PINS
        and type(lease.held_software_bytes) is MappingProxyType
        and set(lease.held_software_bytes) == set(EXPECTED_SOFTWARE_SOURCE_PINS),
        "software_source_hold_binding_invalid",
    )
    _require(
        lease.activation_started is False
        and lease.supervisor_started is False
        and lease.credential_free_gate_started is False
        and lease.credential_free_gate_nonce is None
        and lease.credential_free_gate_supervisor_started is False
        and lease.parent_process_receipt is None,
        "gate_or_activation_started_during_preparation",
    )

    _require(
        set(lease.source_modules) == set(prepared.public_source_pins)
        and set(lease.source_objects) == set(prepared.public_source_pins)
        and set(lease.held_source_bytes) == set(prepared.public_source_pins)
        and lease.source_pins is lease.public_source_pins
        and validate_modules(
            lease.source_modules,
            lease.source_objects,
            lease.public_source_pins,
            lease.held_source_bytes,
        )
        is True,
        "public_source_snapshots_invalid",
    )
    for path, digest in prepared.public_source_pins.items():
        raw = prepared.public_source_bytes[path]
        module_name = prep.__dict__["_module_name_for"](path, DRIVER_RELATIVE)
        module = driver if path == DRIVER_RELATIVE else host.source_modules.get(module_name)
        _require(
            type(raw) is bytes
            and len(raw) <= MAX_PUBLIC_SOURCE_BYTES
            and hashlib.sha256(raw).hexdigest() == digest
            and lease.held_source_bytes[path] is raw
            and host.source_bytes[path] is raw
            and lease.source_modules[path] is module
            and sys.modules.get(module_name) is module,
            "public_source_binding_invalid",
        )
        _require(lease.source_objects[path] is host.source_objects[path], "source_object_identity_invalid")
        for package_name in prep.__dict__["_package_names"](module_name):
            package = host.source_modules.get(package_name)
            _require(
                type(package) is ModuleType and sys.modules.get(package_name) is package,
                "source_package_alias_invalid",
            )

    cuv2 = host.cuv2_module
    _require(
        sys.modules.get(CUV2_MODULE_NAME) is cuv2
        and cuv2.__dict__.get("__c01_source_sha256__") == CUV2_SOURCE_SHA256
        and cuv2.__dict__.get("__c01_source_bytes__") == CUV2_SOURCE_BYTES
        and _cuv2_postcheck_binding_valid(prep, cuv2, lease) is True,
        "cuv2_source_binding_invalid",
    )

    gate_state = driver.__dict__.get("_CREDENTIAL_FREE_GATE_STATE")
    activation = driver.__dict__.get("_HOST_ACTIVATION_STATE")
    keepalive = driver.__dict__.get("_OUTER_KEEPALIVE")
    native_keepalive = driver.__dict__.get("_PARENT_NATIVE_KEEPALIVE")
    _require(
        type(gate_state) is dict
        and gate_state.get("used") is False
        and gate_state.get("receipt") is None
        and type(activation) is dict
        and activation.get("used") is False
        and activation.get("lease") is None
        and activation.get("call_nonce") is None
        and activation.get("gate_receipt") is None
        and type(keepalive) is list
        and len(keepalive) == 1
        and keepalive[0] is lease.keepalive_ref
        and lease.keepalive_container_ref is keepalive
        and type(native_keepalive) is list
        and not native_keepalive,
        "root_gate_or_native_state_invalid",
    )
    attempt.public_source_count = len(prepared.public_source_pins)
    attempt.software_pin_count = len(prepared.software_source_pins)


def prepare_once(cuv2_source_bytes: bytes) -> _Attempt:
    """Enter one source lease and return its retained host without running it."""

    if _ATTEMPTS:
        raise RootPreparationCallerError("preparation_attempt_already_started")
    caller_module = sys.modules.get(ROOT_CALLER_MODULE_NAME)
    _require(
        __name__ == ROOT_CALLER_MODULE_NAME
        and type(caller_module) is ModuleType
        and caller_module.__dict__ is prepare_once.__globals__,
        "root_caller_alias_invalid",
    )
    caller_functions = _function_snapshot(caller_module)
    attempt = _Attempt()
    _ATTEMPTS.append(attempt)
    guard: _ImportGuard | None = None
    original_import: Any = None
    try:
        attempt.phase = "cuv2_argument_check"
        _require(
            type(cuv2_source_bytes) is bytes
            and len(cuv2_source_bytes) == CUV2_SOURCE_BYTES
            and hashlib.sha256(cuv2_source_bytes).hexdigest() == CUV2_SOURCE_SHA256,
            "root_held_cuv2_source_invalid",
        )
        attempt.cuv2_argument_verified = True

        attempt.phase = "fresh_host_preflight"
        _require(
            not any(_forbidden_root(name) for name in tuple(sys.modules))
            and all(name not in sys.modules for name in _FIXED_FRESH_ALIASES),
            "root_host_or_module_alias_not_fresh",
        )

        attempt.phase = "preparation_source_read"
        path, raw = _bounded_public_read(
            PREPARATION_RELATIVE, PREPARATION_BYTES, PREPARATION_SHA256
        )
        prep = _load_preparation(path, raw)
        attempt.preparation_module = prep
        entry = _require_function(prep, "prepare_root_gate_host")
        hosts = prep.__dict__.get("_ROOT_HOSTS")
        token = prep.__dict__.get("_ROOT_HOST_FACTORY")
        _require(type(hosts) is list and not hosts and token is not None, "preparation_state_not_fresh")
        attempt.preparation_source_bytes = raw
        attempt.preparation_functions = _function_snapshot(prep)
        attempt.host_list = hosts
        attempt.factory_token = token
        attempt.status = "PUBLIC_SOURCE_BINDINGS_VERIFIED"

        # Root attests current dev/index separately before this call.  A local
        # import guard blocks SDK/trading roots while the pinned sources load.
        before_modules = frozenset(sys.modules)
        original_import = builtins.__import__
        _require(callable(original_import), "root_import_hook_invalid")
        guard = _ImportGuard(original_import)
        builtins.__import__ = guard
        _require(builtins.__import__ is guard, "root_import_guard_install_failed")
        attempt.import_guard_installed = True
        try:
            attempt.phase = "source_lease_preparation"
            host = entry(cuv2_source_bytes)
            attempt.host = host
            attempt.phase = "postbinding_checks"
            _postcheck(attempt, cuv2_source_bytes)
            _require(
                sys.modules.get(ROOT_CALLER_MODULE_NAME) is caller_module
                and caller_module.__dict__ is prepare_once.__globals__
                and _function_snapshot(caller_module) == caller_functions,
                "root_caller_binding_changed",
            )
            _require(
                builtins.__import__ is guard
                and not any(
                    _forbidden_root(name)
                    for name in set(sys.modules).difference(before_modules)
                ),
                "root_import_guard_or_module_state_changed",
            )
            attempt.postbinding_verified = True
            attempt.status = "ROOT_GATE_HOST_PREPARED"
            attempt.phase = "prepared_host_retained"
        except BaseException:
            attempt.status = "PREPARATION_EXCEPTION_PROPAGATED"
            raise
        finally:
            if builtins.__import__ is guard:
                builtins.__import__ = original_import
                attempt.import_guard_restored = builtins.__import__ is original_import
            else:
                attempt.import_guard_restored = False
        _require(attempt.import_guard_restored, "root_import_guard_restore_uncertain")
        return attempt
    except BaseException:
        if attempt.status not in ("PREPARATION_EXCEPTION_PROPAGATED", "ROOT_GATE_HOST_PREPARED"):
            attempt.status = "PREPARATION_EXCEPTION_PROPAGATED"
        raise


def last_attempt_summary() -> dict[str, Any] | None:
    """Return the finite summary, including after an exception was re-raised."""

    return None if not _ATTEMPTS else _ATTEMPTS[-1].public_summary()


__all__ = ["RootPreparationCallerError", "last_attempt_summary", "prepare_once"]
