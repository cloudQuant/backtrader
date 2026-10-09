"""Fixed same-process caller for Root's credential-free V20 host gate.

This module defines a call boundary only. Importing or compiling it does not
open CUv2, read software payloads, inspect environment values, or invoke the
gate. Root must first prepare the pinned public-source handle, enter and bind
the exact CUv2 lease using its protected source loader, then explicitly call
``invoke_root_credential_free_gate`` once in that same process.

The pinned driver performs the parent Job/pipe lifecycle and closes the exact
CUv2 manager normally before returning its typed gate receipt. This caller
rechecks that receipt and returns a finite sanitized projection. It never
clears the driver's gate receipt or exits the Root host.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import CodeType, FunctionType, MappingProxyType, ModuleType
from typing import Any, Mapping


SCHEMA = "iteration41-simnow-c01-v20-root-credential-free-caller-v2"
REPOSITORY_ROOT = r"D:\source_code\backtrader"
PRECHECK_RELATIVE = (
    "docs/_internal/opts/requirements/"
    "迭代41-实盘执行风控监控与示例架构重构/evidence/"
    "iteration41-simnow-c01-v20-root-public-precheck-r2-bounded-2026-10-09/"
    "prepare_root_precheck.py"
)
PRECHECK_BYTES = 27892
PRECHECK_SHA256 = "3f14a1ae6033717a8d05a90d7bade9ca0c96c6f7cfbea22c9f3176397fe066f6"
DRIVER_RELATIVE = "scripts/iteration41_simnow_c01_v20_root_actual_driver_r3.py"
DRIVER_SHA256 = "4f05194dea1a029a0950dba69e3644ce5e518253aa0d8a727687d707fed0b963"
WRAPPER_RELATIVE = "scripts/run_simnow_c01_native_td_read_v20_root_activation_r2.py"
WRAPPER_SHA256 = "6323c537f852838cdd40f1f92482eb9fd9c57a994cd296074b6e18246badeadd"
DRIVER_MODULE_NAME = "_c01_v20_root_actual_driver"
GATE_ID = "C01_V20_CREDENTIAL_FREE_JOB_CHANNEL_R1"
EXPECTED_PUBLIC_ROWS = 26
MAX_PUBLIC_SOURCE_BYTES = 2 * 1024 * 1024
EXPECTED_SOFTWARE_PINS = {
    "D:/temp/iteration41-root-public-custody-v2.py": (
        "e856be8e4056835d4a7e54f5c6b449c69ab3f1c2ebb049bcbcc1c95a9ad3f246"
    ),
    "C:/anaconda3/python.exe": "c98caee82c66433f0e89d4abbf152b39a7dc2e99979b28dcb021598b4e3f5642",
    "C:/anaconda3/python311.dll": "162e8557fbed5f39ae24983ee62b2d435b4796c937d9c1a34371888c7e43af00",
}


class CredentialFreeCallerError(ValueError):
    """Fixed, non-sensitive caller contract error."""

    def __init__(self, code: str) -> None:
        safe = code if type(code) is str and code.isascii() else "caller_blocked"
        super().__init__(safe)
        self.code = safe


def _require_precheck_function(api: Mapping[str, Any], name: str) -> FunctionType:
    function = api.get(name)
    if (
        type(function) is not FunctionType
        or function.__globals__ is not api
        or type(function.__code__) is not CodeType
        or function.__code__.co_filename != api.get("__file__")
    ):
        raise CredentialFreeCallerError("precheck_function_binding_invalid")
    return function


def _require_driver_function(
    module: ModuleType, objects: Mapping[str, Any], name: str
) -> FunctionType:
    function = module.__dict__.get(name)
    if (
        type(function) is not FunctionType
        or function.__globals__ is not module.__dict__
        or objects.get(name) is not function
        or objects.get(name + ".__code__") is not function.__code__
        or objects.get(name + ".__globals__") is not module.__dict__
    ):
        raise CredentialFreeCallerError("driver_function_binding_invalid")
    return function


def _expected_precheck_path() -> str:
    return os.path.normcase(
        os.path.abspath(str(Path(REPOSITORY_ROOT).joinpath(*PRECHECK_RELATIVE.split("/"))))
    )


def _bool_fields(value: Any, names: tuple[str, ...]) -> bool:
    return all(type(getattr(value, name, None)) is bool for name in names)


def invoke_root_credential_free_gate(
    precheck_globals: Mapping[str, Any], prepared: Any, entered_lease: Any
) -> dict[str, Any]:
    """Invoke the one fixed host gate and return only its sanitized receipt.

    ``precheck_globals`` and ``prepared`` must be the same in-process objects
    produced by the pinned public precheck helper. ``entered_lease`` must be
    entered and bound to modules compiled from its exact CUv2-held bytes; this
    function checks that binding without opening files or changing the lease.
    The gate function owns its normal CUv2 postverify/close and consumes the
    module-wide gate latch before parent API construction.

    The caller intentionally does not catch exceptions from the gate call:
    the driver may retain uncertain process/source custody, and converting
    such a path into a finite success-looking record would be unsafe.
    """

    if type(precheck_globals) is not dict:
        raise CredentialFreeCallerError("precheck_handle_invalid")
    precheck_file = precheck_globals.get("__file__")
    if (
        type(precheck_file) is not str
        or os.path.normcase(os.path.abspath(precheck_file)) != _expected_precheck_path()
        or precheck_globals.get("__c01_source_sha256__") != PRECHECK_SHA256
        or precheck_globals.get("__c01_source_bytes__") != PRECHECK_BYTES
        or precheck_globals.get("SCHEMA") != "iteration41-simnow-c01-v20-root-public-precheck-v2"
        or precheck_globals.get("PIN_MANIFEST_BYTES") != 9069
        or precheck_globals.get("PIN_MANIFEST_SHA256")
        != "e3e6940ba4799b6e783ef4227a07dd43d628ba74b96e5e958a6c7ffec3a6e387"
    ):
        raise CredentialFreeCallerError("precheck_source_path_invalid")
    validate_prepared = _require_precheck_function(
        precheck_globals, "validate_prepared_root_precheck"
    )
    validate_entered = _require_precheck_function(
        precheck_globals, "validate_precheck_against_entered_lease"
    )
    prepared_type = precheck_globals.get("PreparedRootPrecheck")
    if (
        not isinstance(prepared_type, type)
        or type(prepared) is not prepared_type
        or validate_prepared(prepared) is not True
    ):
        raise CredentialFreeCallerError("precheck_result_invalid")

    driver = prepared.driver_module
    objects = prepared.driver_objects
    if (
        type(driver) is not ModuleType
        or driver.__name__ != DRIVER_MODULE_NAME
        or driver.__dict__ is not vars(driver)
        or type(driver.__dict__.get("__file__")) is not str
        or os.path.normcase(os.path.abspath(driver.__dict__["__file__"]))
        != os.path.normcase(
            os.path.abspath(str(Path(REPOSITORY_ROOT).joinpath(*DRIVER_RELATIVE.split("/"))))
        )
        or driver.__dict__.get("__c01_source_sha256__") != DRIVER_SHA256
        or type(objects) is not MappingProxyType
        or type(prepared.public_source_pins) is not MappingProxyType
        or type(prepared.public_source_bytes) is not MappingProxyType
        or type(prepared.software_source_pins) is not MappingProxyType
        or len(prepared.public_source_pins) != EXPECTED_PUBLIC_ROWS
        or set(prepared.public_source_pins) != set(prepared.public_source_bytes)
        or any(
            type(raw) is not bytes or len(raw) > MAX_PUBLIC_SOURCE_BYTES
            for raw in prepared.public_source_bytes.values()
        )
        or prepared.public_source_pins.get(DRIVER_RELATIVE) != DRIVER_SHA256
        or prepared.public_source_pins.get(WRAPPER_RELATIVE) != WRAPPER_SHA256
        or dict(prepared.software_source_pins) != EXPECTED_SOFTWARE_PINS
    ):
        raise CredentialFreeCallerError("prepared_source_binding_invalid")

    validate_driver = _require_driver_function(
        driver, objects, "validate_c01_v20_driver_source_objects"
    )
    run_gate = _require_driver_function(
        driver, objects, "run_root_credential_free_job_channel_gate"
    )
    validate_gate = _require_driver_function(
        driver, objects, "validate_c01_v20_credential_free_gate_receipt"
    )
    validate_close = _require_driver_function(
        driver, objects, "validate_c01_v20_outer_close_receipt"
    )
    lease_check = _require_driver_function(driver, objects, "_outer_lease_current")
    if validate_driver(driver, objects) is not True:
        raise CredentialFreeCallerError("driver_object_snapshot_invalid")
    if validate_entered(prepared, entered_lease) is not True:
        raise CredentialFreeCallerError("entered_lease_binding_invalid")
    if (
        type(entered_lease.held_source_bytes) is not MappingProxyType
        or set(entered_lease.held_source_bytes) != set(prepared.public_source_pins)
        or any(
            type(raw) is not bytes or len(raw) > MAX_PUBLIC_SOURCE_BYTES
            for raw in entered_lease.held_source_bytes.values()
        )
    ):
        raise CredentialFreeCallerError("held_public_source_size_invalid")

    # Capture the exact module-level latch/list objects before the one call.
    # The precheck has already required pristine gate/activation state and one
    # exact source keepalive tuple for this entered lease.
    namespace = driver.__dict__
    outer_keepalive = namespace.get("_OUTER_KEEPALIVE")
    gate_state = namespace.get("_CREDENTIAL_FREE_GATE_STATE")
    activation_state = namespace.get("_HOST_ACTIVATION_STATE")
    native_keepalive = namespace.get("_PARENT_NATIVE_KEEPALIVE")
    if (
        type(outer_keepalive) is not list
        or type(gate_state) is not dict
        or type(activation_state) is not dict
        or type(native_keepalive) is not list
        or gate_state.get("used") is not False
        or gate_state.get("receipt") is not None
        or activation_state.get("used") is not False
        or activation_state.get("lease") is not None
        or activation_state.get("call_nonce") is not None
        or activation_state.get("gate_receipt") is not None
        or native_keepalive
    ):
        raise CredentialFreeCallerError("driver_latches_not_pristine")

    receipt = run_gate(entered_lease)
    receipt_type = namespace.get("C01V20CredentialFreeGateReceipt")
    close_type = namespace.get("C01V20OuterCloseReceipt")
    if (
        not isinstance(receipt_type, type)
        or type(receipt) is not receipt_type
        or validate_gate(receipt) is not True
        or not isinstance(close_type, type)
        or type(receipt._outer_close_receipt) is not close_type
        or validate_close(receipt._outer_close_receipt) is not True
    ):
        raise CredentialFreeCallerError("gate_receipt_invalid")

    close_receipt = receipt._outer_close_receipt
    closed_lease = close_receipt.source_lease
    if (
        closed_lease is not entered_lease
        or close_receipt.parent_process_receipt is not receipt._process_receipt
        or close_receipt.call_nonce is not receipt._process_receipt.call_nonce
        or closed_lease.credential_free_gate_started is not True
        or closed_lease.credential_free_gate_nonce is not receipt._process_receipt.call_nonce
        or closed_lease.credential_free_gate_supervisor_started is not True
        or close_receipt.source_modules.get(DRIVER_RELATIVE) is not driver
        or close_receipt.source_objects.get(DRIVER_RELATIVE) is not objects
        or close_receipt.public_source_pins != prepared.public_source_pins
        or close_receipt.software_source_pins != prepared.software_source_pins
        or lease_check(entered_lease, require_entered=False, closed=True) is not True
        or close_receipt.normal_close_verified is not True
        or close_receipt.outer_postverify_verified is not True
        or close_receipt.cleanup_verified is not True
        or close_receipt.retained_reference_count != 0
        or type(close_receipt.retained_reference_count) is not int
        or driver.__dict__.get("_OUTER_KEEPALIVE") is not outer_keepalive
        or outer_keepalive
        or driver.__dict__.get("_CREDENTIAL_FREE_GATE_STATE") is not gate_state
        or driver.__dict__.get("_HOST_ACTIVATION_STATE") is not activation_state
        or driver.__dict__.get("_PARENT_NATIVE_KEEPALIVE") is not native_keepalive
        or native_keepalive
        or activation_state.get("used") is not False
        or activation_state.get("lease") is not None
        or activation_state.get("call_nonce") is not None
        or activation_state.get("gate_receipt") is not None
    ):
        raise CredentialFreeCallerError("postclose_state_invalid")

    expected_counts = {
        "observed_held_public_count": EXPECTED_PUBLIC_ROWS,
        "observed_held_software_count": len(EXPECTED_SOFTWARE_PINS),
        "observed_held_count": EXPECTED_PUBLIC_ROWS + len(EXPECTED_SOFTWARE_PINS),
    }
    if any(
        type(getattr(close_receipt, name, None)) is not int
        or getattr(close_receipt, name) != expected
        for name, expected in expected_counts.items()
    ):
        raise CredentialFreeCallerError("postclose_source_counts_invalid")

    if receipt.status == "PASS":
        if (
            gate_state.get("used") is not True
            or gate_state.get("receipt") is not receipt
            or receipt.reason != "credential_free_gate_verified"
            or receipt.forced_cleanup is not False
            or receipt.exit_code != 0
            or receipt.formal_c01_pass is not False
            or type(receipt.official_c01_pass_count) is not int
            or receipt.official_c01_pass_count != 0
            or receipt.frame_payload_bytes != 0
            or receipt.writes != 0
            or not _bool_fields(
                receipt,
                (
                    "os_profile_matches",
                    "environment_allowlist_verified",
                    "credential_names_absent",
                    "outer_job_empty",
                    "stdout_eof",
                    "stderr_eof",
                    "stderr_empty",
                    "frame_eof",
                    "job_handles_closed",
                    "reader_threads_joined",
                ),
            )
            or not all(
                getattr(receipt, name) is True
                for name in (
                    "os_profile_matches",
                    "environment_allowlist_verified",
                    "credential_names_absent",
                    "outer_job_empty",
                    "stdout_eof",
                    "stderr_eof",
                    "stderr_empty",
                    "frame_eof",
                    "job_handles_closed",
                    "reader_threads_joined",
                )
            )
        ):
            raise CredentialFreeCallerError("credential_free_gate_pass_invalid")
    elif receipt.status == "BLOCKED":
        if gate_state.get("used") is not True or gate_state.get("receipt") is not None:
            raise CredentialFreeCallerError("credential_free_gate_blocked_state_invalid")
    else:
        raise CredentialFreeCallerError("credential_free_gate_status_invalid")

    # Fixed finite result: no paths, source hashes, environment values,
    # account/session identifiers, raw channels, or exception reprs.
    return {
        "schema": SCHEMA,
        "gate_id": GATE_ID,
        "status": receipt.status,
        "reason": receipt.reason,
        "os_profile_matches": receipt.os_profile_matches,
        "environment_allowlist_verified": receipt.environment_allowlist_verified,
        "credential_names_absent": receipt.credential_names_absent,
        "frame_payload_bytes": receipt.frame_payload_bytes,
        "writes": receipt.writes,
        "formal_c01_pass": False,
        "official_c01_pass_count": 0,
        "forced_cleanup": receipt.forced_cleanup,
        "exit_code": receipt.exit_code,
        "outer_postverify_verified": receipt.outer_postverify_verified,
        "outer_close_verified": receipt.outer_close_verified,
        "cleanup_verified": receipt.cleanup_verified,
        "outer_job_empty": receipt.outer_job_empty,
        "stdout_eof": receipt.stdout_eof,
        "stderr_eof": receipt.stderr_eof,
        "stderr_empty": receipt.stderr_empty,
        "frame_eof": receipt.frame_eof,
        "job_handles_closed": receipt.job_handles_closed,
        "reader_threads_joined": receipt.reader_threads_joined,
        "held_public_source_count": close_receipt.observed_held_public_count,
        "held_software_source_count": close_receipt.observed_held_software_count,
        "held_source_count": close_receipt.observed_held_count,
        "source_lease_closed": True,
        "gate_nonce_retained": True,
        "gate_credit_stored": gate_state.get("receipt") is receipt,
        "activation_not_started": activation_state.get("used") is False,
        "outer_keepalive_empty": not outer_keepalive,
        "parent_native_keepalive_empty": not native_keepalive,
    }


__all__ = ["CredentialFreeCallerError", "invoke_root_credential_free_gate"]
