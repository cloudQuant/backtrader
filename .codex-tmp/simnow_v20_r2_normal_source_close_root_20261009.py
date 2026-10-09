"""Root-only one-shot normal close for the consumed V20 preparation R2 lease.

Root compiles these exact public bytes and execs them in the retained Root
namespace. This helper reads no paths and accepts no caller-built host,
lease, result, receipt, or success flag. It does not create a process receipt
or enter the credential-free Gate.
"""

from __future__ import annotations

import hashlib as _simnow_close_hashlib
import ntpath as _simnow_close_ntpath
import sys as _simnow_close_sys
from types import FunctionType as _SimNowCloseFunctionType
from types import GeneratorType as _SimNowCloseGeneratorType
from types import MappingProxyType as _SimNowCloseMappingProxyType
from types import ModuleType as _SimNowCloseModuleType


_SIMNOW_CLOSE_CALLER_PATH = (
    "D:/source_code/backtrader/.codex-tmp/"
    "simnow_v20_root_preparation_actual_caller_r2_20261009.py"
)
_SIMNOW_CLOSE_CALLER_BYTES = 24722
_SIMNOW_CLOSE_CALLER_SHA256 = (
    "359fd47ec9bb9e516b73b51465b675c977ae045167580ebb0ed0cb3b846c8ad0"
)
_SIMNOW_CLOSE_EXPECTED_EXCEPTION = "public_source_binding_invalid"
_SIMNOW_CLOSE_ATTEMPT_SLOTS = (
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
_SIMNOW_CLOSE_LAUNCH_KEYS = (
    "phase",
    "invocation_count",
    "held",
    "summary",
    "source_phase",
    "exception_category",
    "_exception",
)


class _SimNowR2CloseCheck(Exception):
    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        self.code = code


def _simnow_r2_close_require(condition: bool, code: str) -> None:
    if condition is not True:
        raise _SimNowR2CloseCheck(code)


def _simnow_r2_close_path_equal(left: object, right: object) -> bool:
    return (
        type(left) is str
        and type(right) is str
        and _simnow_close_ntpath.normcase(_simnow_close_ntpath.normpath(left))
        == _simnow_close_ntpath.normcase(_simnow_close_ntpath.normpath(right))
    )


def _simnow_r2_close_snapshot_value(value: object) -> tuple[str, object]:
    if value is None or type(value) in (bool, int, float, str, bytes):
        return ("value", value)
    return ("identity", value)


def _simnow_r2_close_snapshot_unchanged(
    target: object, slots: tuple[str, ...], snapshot: tuple[tuple[str, object], ...]
) -> bool:
    if len(snapshot) != len(slots):
        return False
    for expected_name, captured in zip(slots, snapshot):
        if type(captured) is not tuple or len(captured) != 2:
            return False
        name, encoded = captured
        if name != expected_name or type(encoded) is not tuple or len(encoded) != 2:
            return False
        kind, previous = encoded
        try:
            current = getattr(target, name)
        except Exception:
            return False
        if kind == "value":
            if type(current) is not type(previous) or current != previous:
                return False
        elif current is not previous:
            return False
    return True


def _simnow_r2_close_attempt_snapshot(attempt: object) -> tuple[tuple[str, object], ...]:
    return tuple(
        (name, _simnow_r2_close_snapshot_value(getattr(attempt, name)))
        for name in _SIMNOW_CLOSE_ATTEMPT_SLOTS
    )


def _simnow_r2_close_identity_items(mapping: object) -> tuple[tuple[object, object], ...] | None:
    if type(mapping) not in (dict, _SimNowCloseMappingProxyType):
        return None
    return tuple(mapping.items())


def _simnow_r2_close_identity_items_match(
    mapping: object, captured: tuple[tuple[object, object], ...] | None
) -> bool:
    current = _simnow_r2_close_identity_items(mapping)
    return (
        current is not None
        and captured is not None
        and len(current) == len(captured)
        and all(
            current_key == captured_key and current_value is captured_value
            for (current_key, current_value), (captured_key, captured_value) in zip(
                current, captured
            )
        )
    )


def _simnow_r2_close_validate_retained_root() -> dict[str, object]:
    """Bind the exact failed R2 launch and verify every held source map."""

    root = globals()
    require = _simnow_r2_close_require
    caller_name = "_c01_simnow_v20_root_preparation_actual_caller_r2"
    launch_state = root.get("ROOT_PREPARATION_LAUNCH_STATE")
    caller = root.get("root_simnow_v20_caller_module_r2")
    entry = root.get("root_simnow_v20_entry_r2")
    entry_code = root.get("root_simnow_v20_entry_code_r2")
    exception = launch_state.get("_exception") if type(launch_state) is dict else None
    retained_exception_alias = root.get("root_simnow_v20_preparation_exception_r2")
    caller_raw = root.get("root_caller_source_bytes")
    cuv2_raw = root.get("root_cuv2_source_bytes")

    require(type(launch_state) is dict, "root_launch_state_invalid")
    require(set(launch_state) == set(_SIMNOW_CLOSE_LAUNCH_KEYS), "root_launch_state_shape_invalid")
    require(launch_state.get("phase") == "preparation_exception_retained", "root_launch_phase_invalid")
    require(launch_state.get("source_phase") == "prepare_once_entry", "root_source_phase_invalid")
    require(launch_state.get("invocation_count") == 1, "root_invocation_count_invalid")
    require(
        launch_state.get("exception_category") == "root_caller_contract_error",
        "root_exception_category_invalid",
    )
    require(type(caller) is _SimNowCloseModuleType, "root_caller_module_invalid")
    require(caller.__name__ == caller_name, "root_caller_module_name_invalid")
    require(_simnow_close_sys.modules.get(caller_name) is caller, "root_caller_alias_invalid")
    require(type(caller_raw) is bytes, "root_caller_source_bytes_invalid")
    require(
        len(caller_raw) == _SIMNOW_CLOSE_CALLER_BYTES
        and _simnow_close_hashlib.sha256(caller_raw).hexdigest()
        == _SIMNOW_CLOSE_CALLER_SHA256,
        "root_caller_source_pin_invalid",
    )
    require(
        _simnow_r2_close_path_equal(
            caller.__dict__.get("__file__"), _SIMNOW_CLOSE_CALLER_PATH
        ),
        "root_caller_source_origin_invalid",
    )
    require(type(entry) is _SimNowCloseFunctionType, "root_caller_entry_invalid")
    require(
        caller.__dict__.get("prepare_once") is entry
        and entry.__code__ is entry_code
        and entry.__globals__ is caller.__dict__
        and _simnow_r2_close_path_equal(entry.__code__.co_filename, _SIMNOW_CLOSE_CALLER_PATH),
        "root_caller_entry_binding_invalid",
    )
    require(type(cuv2_raw) is bytes, "root_cuv2_source_bytes_invalid")
    require(
        type(launch_state.get("held")) is tuple
        and len(launch_state["held"]) == 3
        and launch_state["held"][0] is caller
        and launch_state["held"][1] is caller_raw
        and launch_state["held"][2] is cuv2_raw,
        "root_launch_held_tuple_invalid",
    )
    require(
        type(exception) is caller.__dict__.get("RootPreparationCallerError")
        and exception.code == _SIMNOW_CLOSE_EXPECTED_EXCEPTION
        and launch_state.get("_exception") is exception,
        "root_original_exception_binding_invalid",
    )
    require(
        "root_simnow_v20_preparation_exception_r2" not in root
        or retained_exception_alias is exception,
        "root_exception_alias_changed",
    )
    require(
        type(launch_state.get("summary")) is dict,
        "root_original_summary_invalid",
    )
    summary = launch_state["summary"]
    summary_before = dict(summary)
    require(
        summary_before.get("status") == "PREPARATION_EXCEPTION_PROPAGATED"
        and summary_before.get("phase") == "postbinding_checks"
        and summary_before.get("public_source_count") is None
        and summary_before.get("software_pin_metadata_count") is None
        and summary_before.get("preparation_host_retained") is True
        and summary_before.get("outer_source_lease_entered") is True
        and summary_before.get("gate_invoked_by_caller") is False
        and summary_before.get("activation_started_observed") is False
        and summary_before.get("import_guard_restored") is True
        and summary_before.get("postbinding_verified") is False
        and summary_before.get("formal_c01_pass") is False
        and summary_before.get("official_c01_pass_count") == 0,
        "root_original_summary_values_invalid",
    )
    require(
        type(caller.__dict__.get("_ATTEMPTS")) is list
        and len(caller.__dict__["_ATTEMPTS"]) == 1,
        "root_attempt_registry_invalid",
    )
    attempts = caller.__dict__["_ATTEMPTS"]
    attempt = attempts[0]
    require(
        type(attempt) is caller.__dict__.get("_Attempt")
        and attempt.phase == "postbinding_checks"
        and attempt.status == "PREPARATION_EXCEPTION_PROPAGATED"
        and attempt.postbinding_verified is False
        and attempt.import_guard_restored is True,
        "root_original_attempt_invalid",
    )
    attempt_snapshot = _simnow_r2_close_attempt_snapshot(attempt)

    prep = attempt.preparation_module
    require(type(prep) is _SimNowCloseModuleType, "preparation_module_invalid")
    require(
        prep.__dict__ is vars(prep)
        and prep.__dict__.get("__c01_source_sha256__") == caller.PREPARATION_SHA256
        and prep.__dict__.get("__c01_source_bytes__") == caller.PREPARATION_BYTES
        and type(attempt.preparation_source_bytes) is bytes
        and len(attempt.preparation_source_bytes) == caller.PREPARATION_BYTES
        and _simnow_close_hashlib.sha256(attempt.preparation_source_bytes).hexdigest()
        == caller.PREPARATION_SHA256,
        "preparation_source_binding_invalid",
    )
    require(
        type(prep.__dict__.get("_ROOT_HOSTS")) is list
        and prep.__dict__["_ROOT_HOSTS"] is attempt.host_list
        and len(attempt.host_list) == 1,
        "preparation_host_registry_invalid",
    )
    host = attempt.host
    require(host is not None and attempt.host_list[0] is host, "retained_host_identity_invalid")
    require(
        type(host) is prep.__dict__.get("PreparedRootGateHost")
        and host._used is False
        and host._result is None
        and attempt.factory_token is prep.__dict__.get("_ROOT_HOST_FACTORY"),
        "retained_host_state_invalid",
    )
    require(
        prep.__dict__.get("prepare_root_gate_host")
        and prep.__dict__.get("__name__") == caller.PREPARATION_MODULE_NAME
        and caller.PREPARATION_MODULE_NAME not in _simnow_close_sys.modules,
        "preparation_alias_invalid",
    )
    require(
        caller.__dict__.get("_function_snapshot") is not None
        and type(caller.__dict__["_function_snapshot"]) is _SimNowCloseFunctionType
        and caller.__dict__["_function_snapshot"].__globals__ is caller.__dict__
        and caller.__dict__["_function_snapshot"](prep) == attempt.preparation_functions,
        "preparation_function_snapshot_invalid",
    )

    prepared = host.prepared_precheck
    precheck = host.precheck_module
    driver = host.driver_module
    cuv2 = host.cuv2_module
    lease = host.lease
    require(type(precheck) is _SimNowCloseModuleType, "precheck_module_invalid")
    require(type(driver) is _SimNowCloseModuleType, "driver_module_invalid")
    require(type(cuv2) is _SimNowCloseModuleType, "cuv2_module_invalid")
    require(
        type(cuv2_raw) is bytes
        and len(cuv2_raw) == caller.CUV2_SOURCE_BYTES
        and _simnow_close_hashlib.sha256(cuv2_raw).hexdigest() == caller.CUV2_SOURCE_SHA256
        and host.cuv2_source_bytes is cuv2_raw,
        "root_cuv2_source_binding_invalid",
    )
    require(
        _simnow_close_sys.modules.get(caller.CUV2_MODULE_NAME) is cuv2
        and cuv2.__dict__.get("__c01_source_sha256__") == caller.CUV2_SOURCE_SHA256
        and cuv2.__dict__.get("__c01_source_bytes__") == caller.CUV2_SOURCE_BYTES,
        "cuv2_module_alias_or_pin_invalid",
    )
    precheck_path = caller.REPOSITORY_ROOT.resolve(strict=True).joinpath(
        *caller.PurePosixPath(caller.PRECHECK_RELATIVE).parts
    )
    require(
        _simnow_r2_close_path_equal(precheck.__dict__.get("__file__"), str(precheck_path))
        and precheck.__dict__.get("__name__") == caller.PRECHECK_MODULE_NAME
        and caller.PRECHECK_MODULE_NAME not in _simnow_close_sys.modules
        and precheck.__dict__.get("__c01_source_sha256__") == caller.PRECHECK_SHA256
        and precheck.__dict__.get("__c01_source_bytes__") == caller.PRECHECK_BYTES,
        "precheck_module_alias_or_pin_invalid",
    )
    precheck_codes = host._precheck_function_codes
    require(
        type(precheck_codes) is _SimNowCloseMappingProxyType
        and set(precheck_codes)
        == {
            "prepare_root_public_precheck",
            "validate_prepared_root_precheck",
            "validate_precheck_against_entered_lease",
        }
        and all(
            type(precheck.__dict__.get(name)) is _SimNowCloseFunctionType
            and precheck.__dict__[name].__globals__ is precheck.__dict__
            and precheck.__dict__[name].__code__ is precheck_codes[name]
            for name in precheck_codes
        ),
        "precheck_function_code_binding_invalid",
    )
    core_caller = host.caller_module
    require(
        type(core_caller) is _SimNowCloseModuleType
        and core_caller.__dict__.get("__name__") == caller.CALLER_MODULE_NAME
        and caller.CALLER_MODULE_NAME not in _simnow_close_sys.modules
        and core_caller.__dict__.get("__c01_source_sha256__") == caller.CALLER_SHA256
        and core_caller.__dict__.get("__c01_source_bytes__") == caller.CALLER_BYTES
        and type(core_caller.__dict__.get("invoke_root_credential_free_gate"))
        is _SimNowCloseFunctionType
        and host._invoke is core_caller.__dict__["invoke_root_credential_free_gate"]
        and host._invoke_code is host._invoke.__code__
        and host._invoke_globals is core_caller.__dict__
        and host._invoke.__globals__ is core_caller.__dict__,
        "gate_caller_module_alias_or_pin_invalid",
    )
    require(
        driver.__dict__.get("__name__") == caller.DRIVER_MODULE_NAME
        and _simnow_close_sys.modules.get(caller.DRIVER_MODULE_NAME) is driver
        and driver.__dict__.get("__c01_source_sha256__")
        == prepared.public_source_pins.get(caller.DRIVER_RELATIVE),
        "driver_module_alias_or_pin_invalid",
    )
    require(type(lease) is driver.__dict__.get("C01V20OuterSourceLease"), "outer_lease_type_invalid")
    require(
        lease.cuv2_module is cuv2
        and lease.cuv2_source_bytes is cuv2_raw
        and lease.state == "entered"
        and lease.exit_started is False
        and lease.close_result is None
        and lease.parent_process_receipt is None,
        "outer_lease_state_invalid",
    )
    require(
        lease.activation_started is False
        and lease.activation_nonce is None
        and lease.supervisor_started is False
        and lease.credential_free_gate_started is False
        and lease.credential_free_gate_nonce is None
        and lease.credential_free_gate_supervisor_started is False,
        "outer_lease_gate_state_invalid",
    )

    driver_objects = host.driver_objects
    require(type(driver_objects) is _SimNowCloseMappingProxyType, "driver_object_map_invalid")
    validate_driver = driver.__dict__.get("validate_c01_v20_driver_source_objects")
    require(
        type(validate_driver) is _SimNowCloseFunctionType
        and validate_driver.__globals__ is driver.__dict__
        and validate_driver(driver, driver_objects) is True,
        "driver_source_object_binding_invalid",
    )

    def driver_function(name: str) -> object:
        function = driver.__dict__.get(name)
        _simnow_r2_close_require(
            type(function) is _SimNowCloseFunctionType
            and function.__globals__ is driver.__dict__
            and driver_objects.get(name) is function
            and driver_objects.get(name + ".__code__") is function.__code__
            and driver_objects.get(name + ".__globals__") is driver.__dict__,
            "driver_function_binding_invalid",
        )
        return function

    current_lease = driver_function("_outer_lease_current")
    bytes_match = driver_function("_outer_bytes_match_lease")
    validate_modules = driver_function("_validate_source_module_snapshots")
    require(current_lease(lease, require_entered=True) is True, "outer_lease_current_check_failed")
    require(bytes_match(lease) is True, "outer_held_bytes_check_failed")
    require(
        type(lease.public_source_pins) is _SimNowCloseMappingProxyType
        and len(lease.public_source_pins) == 26
        and set(lease.held_source_bytes) == set(lease.public_source_pins)
        and set(lease.source_modules) == set(lease.public_source_pins)
        and set(lease.source_objects) == set(lease.public_source_pins)
        and lease.source_pins is lease.public_source_pins
        and validate_modules(
            lease.source_modules,
            lease.source_objects,
            lease.public_source_pins,
            lease.held_source_bytes,
        )
        is True,
        "public_module_source_maps_invalid",
    )
    require(
        type(prepared.public_source_pins) is _SimNowCloseMappingProxyType
        and type(prepared.public_source_bytes) is _SimNowCloseMappingProxyType
        and set(prepared.public_source_pins) == set(lease.public_source_pins)
        and len(prepared.public_source_pins) == 26,
        "precheck_public_source_map_invalid",
    )
    require(
        type(host.source_bytes) is dict
        and set(host.source_bytes) == set(prepared.public_source_pins)
        and set(host.source_modules) >= set(prepared.public_source_pins)
        and set(host.source_objects) == set(prepared.public_source_pins),
        "host_public_source_map_invalid",
    )

    module_name_for = prep.__dict__.get("_module_name_for")
    package_names = prep.__dict__.get("_package_names")
    wrapper_match = prep.__dict__.get("_contextmanager_wrapper_matches")
    require(
        all(
            type(function) is _SimNowCloseFunctionType
            and function.__globals__ is prep.__dict__
            for function in (module_name_for, package_names, wrapper_match)
        ),
        "preparation_binding_helpers_invalid",
    )
    for path, digest in prepared.public_source_pins.items():
        precheck_raw = prepared.public_source_bytes[path]
        held_raw = lease.held_source_bytes[path]
        require(
            type(precheck_raw) is bytes
            and type(held_raw) is bytes
            and len(precheck_raw) <= caller.MAX_PUBLIC_SOURCE_BYTES
            and len(held_raw) <= caller.MAX_PUBLIC_SOURCE_BYTES
            and _simnow_close_hashlib.sha256(precheck_raw).hexdigest() == digest
            and _simnow_close_hashlib.sha256(held_raw).hexdigest() == digest
            and precheck_raw == held_raw
            and host.source_bytes.get(path) is held_raw,
            "public_held_bytes_pin_invalid",
        )
        module = lease.source_modules[path]
        object_map = lease.source_objects[path]
        alias = module_name_for(path, caller.DRIVER_RELATIVE)
        require(
            host.source_modules.get(path) is module
            and host.source_objects.get(path) is object_map
            and _simnow_close_sys.modules.get(alias) is module,
            "public_source_alias_invalid",
        )
        for package_alias in package_names(alias):
            package = host.source_modules.get(package_alias)
            require(
                type(package) is _SimNowCloseModuleType
                and _simnow_close_sys.modules.get(package_alias) is package,
                "public_package_alias_invalid",
            )
    require(
        wrapper_match(
            lease.cuv2_function,
            lease.cuv2_generator_function,
        )
        is True
        and lease.cuv2_function is cuv2.__dict__.get("held_public_sources")
        and lease.cuv2_generator_function
        is getattr(lease.cuv2_function, "__wrapped__", None)
        and lease.cuv2_generator_function.__globals__ is cuv2.__dict__
        and lease.generator.gi_code is lease.cuv2_generator_code
        and lease.generator.gi_frame is not None
        and lease.generator.gi_frame.f_globals is cuv2.__dict__,
        "cuv2_wrapper_generator_binding_invalid",
    )

    expected_software = caller.__dict__.get("EXPECTED_SOFTWARE_SOURCE_PINS")
    require(
        type(expected_software) is dict
        and len(expected_software) == 3
        and dict(prepared.software_source_pins) == expected_software
        and dict(lease.software_source_pins) == expected_software
        and type(lease.held_software_bytes) is _SimNowCloseMappingProxyType
        and set(lease.held_software_bytes) == set(expected_software),
        "software_source_pin_map_invalid",
    )
    for path, digest in expected_software.items():
        software_raw = lease.held_software_bytes[path]
        normalized = driver._normalize_absolute_path(path)
        require(
            type(software_raw) is bytes
            and _simnow_close_hashlib.sha256(software_raw).hexdigest() == digest
            and software_raw is lease.held_raw_by_absolute_path.get(normalized),
            "software_held_bytes_pin_invalid",
        )

    validate_entered = precheck.__dict__.get("validate_precheck_against_entered_lease")
    require(
        type(validate_entered) is _SimNowCloseFunctionType
        and validate_entered.__globals__ is precheck.__dict__
        and validate_entered(prepared, lease) is True,
        "precheck_lease_binding_invalid",
    )
    gate_state = driver.__dict__.get("_CREDENTIAL_FREE_GATE_STATE")
    activation_state = driver.__dict__.get("_HOST_ACTIVATION_STATE")
    keepalive = driver.__dict__.get("_OUTER_KEEPALIVE")
    native_keepalive = driver.__dict__.get("_PARENT_NATIVE_KEEPALIVE")
    require(
        type(gate_state) is dict
        and gate_state.get("used") is False
        and gate_state.get("receipt") is None
        and type(activation_state) is dict
        and activation_state.get("used") is False
        and activation_state.get("lease") is None
        and activation_state.get("call_nonce") is None
        and activation_state.get("gate_receipt") is None
        and type(native_keepalive) is list
        and not native_keepalive
        and type(keepalive) is list
        and lease.keepalive_container_ref is keepalive
        and sum(value is lease.keepalive_ref for value in keepalive) == 1
        and len(keepalive) == 1,
        "root_gate_or_keepalive_state_invalid",
    )

    aliases = tuple(
        (name, module)
        for name, module in _simnow_close_sys.modules.items()
        if type(name) is str
        and (
            name in (caller_name, caller.PREPARATION_MODULE_NAME, caller.PRECHECK_MODULE_NAME,
                     caller.CALLER_MODULE_NAME, caller.DRIVER_MODULE_NAME, caller.CUV2_MODULE_NAME)
            or name in host.source_modules
        )
    )
    absent_aliases = (
        caller.PREPARATION_MODULE_NAME,
        caller.PRECHECK_MODULE_NAME,
        caller.CALLER_MODULE_NAME,
    )
    root_bindings = tuple(
        (name, root.get(name))
        for name in (
            "ROOT_PREPARATION_LAUNCH_STATE",
            "root_simnow_v20_caller_module_r2",
            "root_simnow_v20_entry_r2",
            "root_simnow_v20_entry_code_r2",
            "root_caller_source_bytes",
            "root_cuv2_source_bytes",
        )
    )
    return {
        "root": root,
        "launch_state": launch_state,
        "launch_snapshot": tuple((key, _simnow_r2_close_snapshot_value(launch_state[key])) for key in _SIMNOW_CLOSE_LAUNCH_KEYS),
        "summary": summary,
        "summary_snapshot": summary_before,
        "caller": caller,
        "entry": entry,
        "entry_code": entry_code,
        "exception": exception,
        "caller_raw": caller_raw,
        "cuv2_raw": cuv2_raw,
        "attempts": attempts,
        "attempt": attempt,
        "attempt_snapshot": attempt_snapshot,
        "prep": prep,
        "host": host,
        "lease": lease,
        "driver": driver,
        "driver_objects": driver_objects,
        "current_lease": current_lease,
        "bytes_match": bytes_match,
        "validate_modules": validate_modules,
        "aliases": aliases,
        "absent_aliases": absent_aliases,
        "root_bindings": root_bindings,
        "host_bindings": (
            ("prepared_precheck", host.prepared_precheck),
            ("precheck_module", host.precheck_module),
            ("caller_module", host.caller_module),
            ("driver_module", host.driver_module),
            ("driver_objects", host.driver_objects),
            ("cuv2_module", host.cuv2_module),
            ("cuv2_source_bytes", host.cuv2_source_bytes),
            ("lease", host.lease),
            ("_invoke", host._invoke),
            ("_invoke_code", host._invoke_code),
            ("_invoke_globals", host._invoke_globals),
            ("_precheck_function_codes", host._precheck_function_codes),
        ),
        "host_source_bytes": _simnow_r2_close_identity_items(host.source_bytes),
        "host_source_modules": _simnow_r2_close_identity_items(host.source_modules),
        "host_source_objects": _simnow_r2_close_identity_items(host.source_objects),
        "gate_state": gate_state,
        "activation_state": activation_state,
        "keepalive": keepalive,
        "native_keepalive": native_keepalive,
    }


def _simnow_r2_close_recheck_retained_root(snapshot: dict[str, object]) -> bool:
    try:
        root = snapshot["root"]
        launch_state = snapshot["launch_state"]
        summary = snapshot["summary"]
        attempt = snapshot["attempt"]
        lease = snapshot["lease"]
        driver = snapshot["driver"]
        return (
            all(root.get(name) is value for name, value in snapshot["root_bindings"])
            and all(
                getattr(snapshot["host"], name) is value
                for name, value in snapshot["host_bindings"]
            )
            and _simnow_r2_close_identity_items_match(
                snapshot["host"].source_bytes, snapshot["host_source_bytes"]
            )
            and _simnow_r2_close_identity_items_match(
                snapshot["host"].source_modules, snapshot["host_source_modules"]
            )
            and _simnow_r2_close_identity_items_match(
                snapshot["host"].source_objects, snapshot["host_source_objects"]
            )
            and launch_state is root.get("ROOT_PREPARATION_LAUNCH_STATE")
            and all(
                _simnow_r2_close_snapshot_value(launch_state[key]) == expected
                for key, expected in snapshot["launch_snapshot"]
            )
            and launch_state.get("summary") is summary
            and type(summary) is dict
            and summary == snapshot["summary_snapshot"]
            and snapshot["caller"].__dict__.get("_ATTEMPTS") is snapshot["attempts"]
            and len(snapshot["attempts"]) == 1
            and snapshot["attempts"][0] is attempt
            and _simnow_r2_close_snapshot_unchanged(
                attempt, _SIMNOW_CLOSE_ATTEMPT_SLOTS, snapshot["attempt_snapshot"]
            )
            and snapshot["prep"].__dict__.get("_ROOT_HOSTS") is not None
            and len(snapshot["prep"].__dict__["_ROOT_HOSTS"]) == 1
            and snapshot["prep"].__dict__["_ROOT_HOSTS"][0] is snapshot["host"]
            and snapshot["host"].lease is lease
            and snapshot["host"]._used is False
            and snapshot["host"]._result is None
            and all(_simnow_close_sys.modules.get(name) is module for name, module in snapshot["aliases"])
            and all(name not in _simnow_close_sys.modules for name in snapshot["absent_aliases"])
            and driver.__dict__.get("_CREDENTIAL_FREE_GATE_STATE") is snapshot["gate_state"]
            and snapshot["gate_state"].get("used") is False
            and snapshot["gate_state"].get("receipt") is None
            and driver.__dict__.get("_HOST_ACTIVATION_STATE") is snapshot["activation_state"]
            and snapshot["activation_state"].get("used") is False
            and snapshot["activation_state"].get("lease") is None
            and snapshot["activation_state"].get("call_nonce") is None
            and snapshot["activation_state"].get("gate_receipt") is None
            and driver.__dict__.get("_PARENT_NATIVE_KEEPALIVE") is snapshot["native_keepalive"]
            and not snapshot["native_keepalive"]
        )
    except BaseException:
        return False


def simnow_v20_r2_close_source_lease_once() -> dict[str, object]:
    """Close only the exact failed R2 source lease once, with normal postverify."""

    close_function = globals().get("simnow_v20_r2_close_source_lease_once")
    if (
        type(close_function) is not _SimNowCloseFunctionType
        or close_function.__globals__ is not globals()
    ):
        return {"schema": "simnow-v20-r2-normal-source-close-r1", "status": "BLOCKED", "reason": "root_function_binding_invalid"}
    try:
        snapshot = _simnow_r2_close_validate_retained_root()
    except _SimNowR2CloseCheck as exc:
        return {
            "schema": "simnow-v20-r2-normal-source-close-r1",
            "status": "BLOCKED",
            "phase": "precheck",
            "reason": exc.code,
            "exit_invoked": False,
        }
    except BaseException:
        return {
            "schema": "simnow-v20-r2-normal-source-close-r1",
            "status": "BLOCKED",
            "phase": "precheck",
            "reason": "precheck_internal_failure",
            "exit_invoked": False,
        }

    lease = snapshot["lease"]
    driver = snapshot["driver"]
    keepalive = snapshot["keepalive"]
    try:
        object.__setattr__(lease, "exit_started", True)
        object.__setattr__(lease, "state", "closing")
        if snapshot["current_lease"](lease, require_entered=False, closing=True) is not True:
            object.__setattr__(lease, "state", "uncertain")
            return {
                "schema": "simnow-v20-r2-normal-source-close-r1",
                "status": "BLOCKED",
                "phase": "pre_exit_binding_check",
                "reason": "closing_binding_changed",
                "exit_invoked": False,
                "retained_reference": sum(value is lease.keepalive_ref for value in keepalive) == 1,
            }
        try:
            close_result = lease.manager_exit(lease.manager, None, None, None)
        except BaseException:
            object.__setattr__(lease, "state", "uncertain")
            return {
                "schema": "simnow-v20-r2-normal-source-close-r1",
                "status": "BLOCKED",
                "phase": "manager_exit",
                "reason": "manager_exit_raised",
                "exit_invoked": True,
                "retained_reference": sum(value is lease.keepalive_ref for value in keepalive) == 1,
            }
        object.__setattr__(lease, "close_result", close_result)
        if (
            close_result is not False
            or type(lease.generator) is not _SimNowCloseGeneratorType
            or lease.generator.gi_running is not False
            or lease.generator.gi_frame is not None
            or snapshot["current_lease"](
                lease, require_entered=False, closing=True
            )
            is not True
            or snapshot["bytes_match"](lease) is not True
            or not _simnow_r2_close_recheck_retained_root(snapshot)
            or type(keepalive) is not list
            or driver.__dict__.get("_OUTER_KEEPALIVE") is not keepalive
            or lease.keepalive_container_ref is not keepalive
            or sum(value is lease.keepalive_ref for value in keepalive) != 1
            or len(keepalive) != 1
        ):
            object.__setattr__(lease, "state", "uncertain")
            return {
                "schema": "simnow-v20-r2-normal-source-close-r1",
                "status": "BLOCKED",
                "phase": "postverify",
                "reason": "normal_postverify_failed",
                "exit_invoked": True,
                "retained_reference": sum(value is lease.keepalive_ref for value in keepalive) == 1,
            }

        keepalive.remove(lease.keepalive_ref)
        object.__setattr__(lease, "state", "closed")
        if (
            keepalive
            or any(value is lease.keepalive_ref for value in keepalive)
            or snapshot["current_lease"](
                lease, require_entered=False, closed=True
            )
            is not True
            or not _simnow_r2_close_recheck_retained_root(snapshot)
        ):
            if type(keepalive) is list and not any(value is lease.keepalive_ref for value in keepalive):
                keepalive.append(lease.keepalive_ref)
            object.__setattr__(lease, "state", "uncertain")
            return {
                "schema": "simnow-v20-r2-normal-source-close-r1",
                "status": "BLOCKED",
                "phase": "closed_state_check",
                "reason": "closed_state_or_root_binding_invalid",
                "exit_invoked": True,
                "retained_reference": sum(value is lease.keepalive_ref for value in keepalive) == 1,
            }
        return {
            "schema": "simnow-v20-r2-normal-source-close-r1",
            "status": "SOURCE_SCOPE_NORMAL_CLOSE_RETURNED",
            "phase": "complete",
            "reason": None,
            "exit_invoked": True,
            "normal_exit_returned_false": True,
            "generator_exhausted": True,
            "public_rows_postverified": 26,
            "software_rows_postverified": 3,
            "own_keepalive_removed": True,
            "original_attempt_preserved": True,
            "original_exception_preserved": True,
            "original_summary_preserved": True,
            "credential_free_gate_invoked": False,
            "activation_started": False,
            "formal_c01_pass": False,
            "official_c01_pass_count": 0,
        }
    except BaseException:
        if lease.exit_started is True:
            object.__setattr__(lease, "state", "uncertain")
            if (
                type(keepalive) is list
                and driver.__dict__.get("_OUTER_KEEPALIVE") is keepalive
                and not any(value is lease.keepalive_ref for value in keepalive)
            ):
                try:
                    keepalive.append(lease.keepalive_ref)
                except BaseException:
                    pass
        return {
            "schema": "simnow-v20-r2-normal-source-close-r1",
            "status": "BLOCKED",
            "phase": "close_uncertain",
            "reason": "normal_close_internal_failure",
            "exit_invoked": True,
            "retained_reference": (
                type(keepalive) is list
                and sum(value is lease.keepalive_ref for value in keepalive) == 1
            ),
        }
